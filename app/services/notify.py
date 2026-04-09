import asyncio
import hashlib
import os
import re
import sqlite3
import threading
import time
import urllib.parse
from datetime import datetime, timedelta
from typing import Any, Dict, List, Set, Tuple

from ..core import *  # noqa: F401,F403


NOTIFY_DEDUPE_TTL_DAYS = max(7, int(os.getenv("NOTIFY_DEDUPE_TTL_DAYS", "180") or 180))
NOTIFY_SCENE_SUBSCRIPTION_SUCCESS = "subscription_success"
NOTIFY_SCENE_MONITOR_SUCCESS = "monitor_success"
NOTIFY_CHANNEL_WECOM_BOT = "wecom_bot"
NOTIFY_CHANNEL_WECOM_APP = "wecom_app"
WECOM_APP_TOKEN_REFRESH_BUFFER_SECONDS = 120

MONITOR_MEDIA_EXTENSIONS = (
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".ts",
    ".m2ts",
    ".flv",
    ".wmv",
    ".m4v",
    ".rmvb",
    ".rm",
    ".webm",
    ".mpg",
    ".mpeg",
)

MONITOR_GENERIC_DIR_NAMES = {
    "movie",
    "movies",
    "film",
    "films",
    "tv",
    "series",
    "电视剧",
    "电影",
    "综艺",
    "动漫",
    "动画",
    "纪录片",
    "4k",
    "1080p",
    "720p",
}

_wecom_app_token_cache: Dict[str, Dict[str, Any]] = {}
_wecom_app_token_lock = threading.Lock()


def _normalize_notify_channel(value: Any) -> str:
    key = str(value or "").strip().lower()
    if key in ("wecom_app", "app", "application", "wecom-api", "wecom_api", "api"):
        return NOTIFY_CHANNEL_WECOM_APP
    return NOTIFY_CHANNEL_WECOM_BOT


def _normalize_wecom_webhook(value: Any) -> str:
    webhook = str(value or "").strip()
    if not webhook:
        return ""
    parsed = urllib.parse.urlsplit(webhook)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    return webhook


def _normalize_wecom_agent_id(value: Any) -> int:
    try:
        agent_id = int(str(value or "").strip() or "0")
    except Exception:
        agent_id = 0
    return max(0, agent_id)


def _normalize_wecom_touser(value: Any) -> str:
    tokens = unique_preserve_order(
        [
            token
            for token in re.split(r"[,\s，|]+", str(value or "").strip())
            if token and token.strip()
        ]
    )
    return "|".join(tokens)


def build_notify_runtime_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "enabled": bool(cfg.get("notify_push_enabled", False)),
        "channel": _normalize_notify_channel(cfg.get("notify_channel", NOTIFY_CHANNEL_WECOM_BOT)),
        "wecom_webhook": _normalize_wecom_webhook(cfg.get("notify_wecom_webhook", "")),
        "wecom_app_corp_id": str(cfg.get("notify_wecom_app_corp_id", "") or "").strip(),
        "wecom_app_agent_id": _normalize_wecom_agent_id(cfg.get("notify_wecom_app_agent_id", "")),
        "wecom_app_secret": str(cfg.get("notify_wecom_app_secret", "") or "").strip(),
        "wecom_app_touser": _normalize_wecom_touser(cfg.get("notify_wecom_app_touser", "")),
    }


def _ensure_notification_dedupe_table(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS notification_dedupe (
            dedupe_key TEXT PRIMARY KEY,
            scene TEXT NOT NULL DEFAULT '',
            task_name TEXT NOT NULL DEFAULT '',
            episode INTEGER NOT NULL DEFAULT 0,
            savepath TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT '',
            expires_at TEXT NOT NULL DEFAULT ''
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_notification_dedupe_expires_at ON notification_dedupe(expires_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_notification_dedupe_scene ON notification_dedupe(scene, task_name)")


def _prune_notification_dedupe(conn: sqlite3.Connection, now_iso: str) -> None:
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM notification_dedupe WHERE expires_at <> '' AND expires_at <= ?",
        (str(now_iso or now_text()).strip() or now_text(),),
    )


def _build_subscription_dedupe_key(task_name: str, savepath: str, episode: int) -> str:
    payload = safe_json_dumps(
        {
            "scene": NOTIFY_SCENE_SUBSCRIPTION_SUCCESS,
            "task_name": str(task_name or "").strip(),
            "savepath": normalize_relative_path(savepath),
            "episode": max(0, int(episode or 0)),
        }
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _build_episode_key_pairs(task_name: str, savepath: str, episodes: List[int]) -> List[Tuple[int, str]]:
    seen_keys: Set[str] = set()
    pairs: List[Tuple[int, str]] = []
    for value in episodes:
        episode_no = max(0, int(value or 0))
        dedupe_key = _build_subscription_dedupe_key(task_name, savepath, episode_no)
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        pairs.append((episode_no, dedupe_key))
    return pairs


def _filter_fresh_subscription_notification_pairs(
    task_name: str,
    savepath: str,
    episodes: List[int],
) -> List[Tuple[int, str]]:
    pairs = _build_episode_key_pairs(task_name, savepath, episodes)
    if not pairs:
        return []

    ensure_db()
    conn = open_db()
    try:
        _ensure_notification_dedupe_table(conn)
        now_iso = now_text()
        _prune_notification_dedupe(conn, now_iso)
        keys = [key for _, key in pairs]
        placeholders = ",".join(["?"] * len(keys))
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT dedupe_key
            FROM notification_dedupe
            WHERE scene = ? AND dedupe_key IN ({placeholders}) AND (expires_at = '' OR expires_at > ?)
            """,
            tuple([NOTIFY_SCENE_SUBSCRIPTION_SUCCESS] + keys + [now_iso]),
        )
        existing_keys = {str(row["dedupe_key"] or "").strip() for row in cursor.fetchall()}
        conn.commit()
    finally:
        conn.close()

    return [(episode_no, dedupe_key) for episode_no, dedupe_key in pairs if dedupe_key not in existing_keys]


def _record_subscription_notification_pairs(
    task_name: str,
    savepath: str,
    pairs: List[Tuple[int, str]],
) -> None:
    normalized_pairs = [
        (max(0, int(episode or 0)), str(key or "").strip())
        for episode, key in (pairs or [])
        if str(key or "").strip()
    ]
    if not normalized_pairs:
        return

    now_iso = now_text()
    expires_at = (datetime.now() + timedelta(days=NOTIFY_DEDUPE_TTL_DAYS)).isoformat(timespec="seconds")
    normalized_task_name = str(task_name or "").strip()
    normalized_savepath = normalize_relative_path(savepath)

    ensure_db()
    conn = open_db()
    try:
        _ensure_notification_dedupe_table(conn)
        _prune_notification_dedupe(conn, now_iso)
        cursor = conn.cursor()
        for episode_no, dedupe_key in normalized_pairs:
            cursor.execute(
                """
                INSERT OR REPLACE INTO notification_dedupe(
                    dedupe_key, scene, task_name, episode, savepath, created_at, expires_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dedupe_key,
                    NOTIFY_SCENE_SUBSCRIPTION_SUCCESS,
                    normalized_task_name,
                    episode_no,
                    normalized_savepath,
                    now_iso,
                    expires_at,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _send_wecom_bot_markdown(webhook_url: str, content: str, timeout: int = 20) -> Dict[str, Any]:
    normalized_webhook = _normalize_wecom_webhook(webhook_url)
    if not normalized_webhook:
        raise RuntimeError("企业微信群机器人 Webhook 格式无效，请检查后重试")
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "content": str(content or "").strip(),
        },
    }
    result = http_request_json(normalized_webhook, method="POST", payload=payload, timeout=max(5, int(timeout or 20)))
    if not isinstance(result, dict):
        raise RuntimeError("企业微信接口返回异常，未拿到 JSON 响应")
    errcode = int(result.get("errcode", 0) or 0)
    if errcode != 0:
        errmsg = str(result.get("errmsg", "") or "unknown error").strip()
        raise RuntimeError(f"企业微信接口返回错误（errcode={errcode}, errmsg={errmsg}）")
    return result


def _build_wecom_app_cache_key(corp_id: str, app_secret: str) -> str:
    return hashlib.sha1(f"{corp_id}|{app_secret}".encode("utf-8")).hexdigest()


def _get_wecom_app_access_token(runtime_cfg: Dict[str, Any], timeout: int = 20, force_refresh: bool = False) -> str:
    corp_id = str(runtime_cfg.get("wecom_app_corp_id", "") or "").strip()
    app_secret = str(runtime_cfg.get("wecom_app_secret", "") or "").strip()
    if not corp_id:
        raise RuntimeError("企业微信应用模式缺少 CorpID")
    if not app_secret:
        raise RuntimeError("企业微信应用模式缺少 AppSecret")

    cache_key = _build_wecom_app_cache_key(corp_id, app_secret)
    now_ts = time.time()
    if not force_refresh:
        with _wecom_app_token_lock:
            cache_entry = _wecom_app_token_cache.get(cache_key, {})
            cached_token = str(cache_entry.get("access_token", "") or "").strip()
            expires_at = float(cache_entry.get("expires_at", 0.0) or 0.0)
            if cached_token and expires_at > (now_ts + WECOM_APP_TOKEN_REFRESH_BUFFER_SECONDS):
                return cached_token

    query = urllib.parse.urlencode({"corpid": corp_id, "corpsecret": app_secret})
    token_url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?{query}"
    result = http_request_json(token_url, method="GET", timeout=max(5, int(timeout or 20)))
    if not isinstance(result, dict):
        raise RuntimeError("获取企业微信 access_token 失败：返回值不是 JSON")
    errcode = int(result.get("errcode", 0) or 0)
    if errcode != 0:
        errmsg = str(result.get("errmsg", "") or "unknown error").strip()
        raise RuntimeError(f"获取企业微信 access_token 失败（errcode={errcode}, errmsg={errmsg}）")
    access_token = str(result.get("access_token", "") or "").strip()
    if not access_token:
        raise RuntimeError("获取企业微信 access_token 失败：返回 access_token 为空")
    try:
        expires_in = int(result.get("expires_in", 7200) or 7200)
    except Exception:
        expires_in = 7200
    expires_in = max(300, expires_in)
    with _wecom_app_token_lock:
        _wecom_app_token_cache[cache_key] = {
            "access_token": access_token,
            "expires_at": time.time() + expires_in,
        }
    return access_token


def _send_wecom_app_markdown(runtime_cfg: Dict[str, Any], content: str, timeout: int = 20) -> Dict[str, Any]:
    touser = _normalize_wecom_touser(runtime_cfg.get("wecom_app_touser", ""))
    if not touser:
        raise RuntimeError("企业微信应用模式缺少接收人 UserID")
    agent_id = _normalize_wecom_agent_id(runtime_cfg.get("wecom_app_agent_id", 0))
    if agent_id <= 0:
        raise RuntimeError("企业微信应用模式 AgentID 无效，请填写数字")

    payload = {
        "touser": touser,
        "msgtype": "markdown",
        "agentid": agent_id,
        "markdown": {"content": str(content or "").strip()},
        "safe": 0,
        "enable_id_trans": 0,
        "enable_duplicate_check": 0,
    }

    retriable_errcodes = {42001, 40014, 41001}
    last_error = ""
    for attempt in range(1, 3):
        access_token = _get_wecom_app_access_token(
            runtime_cfg,
            timeout=timeout,
            force_refresh=attempt > 1,
        )
        url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={urllib.parse.quote(access_token)}"
        result = http_request_json(url, method="POST", payload=payload, timeout=max(5, int(timeout or 20)))
        if not isinstance(result, dict):
            raise RuntimeError("企业微信应用消息发送失败：返回值不是 JSON")
        errcode = int(result.get("errcode", 0) or 0)
        if errcode == 0:
            return result
        errmsg = str(result.get("errmsg", "") or "unknown error").strip()
        last_error = f"企业微信应用消息发送失败（errcode={errcode}, errmsg={errmsg}）"
        if errcode in retriable_errcodes and attempt == 1:
            continue
        raise RuntimeError(last_error)
    raise RuntimeError(last_error or "企业微信应用消息发送失败")


def _format_notify_episode_summary(episodes: List[int]) -> str:
    normalized = sorted(
        {
            max(0, int(item or 0))
            for item in (episodes or [])
            if max(0, int(item or 0)) > 0
        }
    )
    if not normalized:
        return ""
    if len(normalized) <= 8:
        return "、".join([f"E{value}" for value in normalized])
    return f"E{normalized[0]}-E{normalized[-1]}"


def _compact_text(value: Any, limit: int = 140) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if limit > 0 and len(text) > limit:
        return text[: max(1, limit - 1)] + "..."
    return text


def _build_subscription_success_markdown(
    task: Dict[str, Any],
    item: Dict[str, Any],
    savepath: str,
    job_id: int,
    successful_count: int,
    notify_episodes: List[int],
    next_episode: int,
) -> str:
    media_type = str(task.get("media_type", "movie") or "movie").strip().lower()
    media_label = "电视剧" if media_type == "tv" else "电影"
    task_label = _compact_text(task.get("title", "") or task.get("name", "") or "未命名任务", 64)
    resource_title = _compact_text(item.get("title", "") or "未命名资源", 96)
    savepath_label = _compact_text(normalize_relative_path(savepath) or "--", 128)
    now_label = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "### 订阅更新成功",
        f"> 时间：{now_label}",
        f"> 任务：{task_label}（{media_label}）",
    ]
    if media_type == "tv":
        episode_summary = _format_notify_episode_summary(notify_episodes)
        lines.append(f"> 新增集数：{episode_summary or '--'}（{len(notify_episodes)} 集）")
        if int(next_episode or 0) > 0:
            lines.append(f"> 当前进度：E{int(next_episode)}")
    lines.append(f"> 保存路径：{savepath_label}")
    lines.append(f"> 命中资源：{resource_title}")
    if int(job_id or 0) > 0:
        lines.append(f"> 导入任务：#{int(job_id)}")
    if int(successful_count or 0) > 1:
        lines.append(f"> 本轮批量成功：{int(successful_count)} 条")
    return "\n".join(lines)


def _send_notify_content(runtime_cfg: Dict[str, Any], content: str, timeout: int = 20) -> Dict[str, Any]:
    channel = _normalize_notify_channel(runtime_cfg.get("channel", NOTIFY_CHANNEL_WECOM_BOT))
    if channel == NOTIFY_CHANNEL_WECOM_APP:
        return _send_wecom_app_markdown(runtime_cfg, content, timeout=timeout)
    return _send_wecom_bot_markdown(runtime_cfg.get("wecom_webhook", ""), content, timeout=timeout)


def _build_notify_target_desc(runtime_cfg: Dict[str, Any]) -> str:
    channel = _normalize_notify_channel(runtime_cfg.get("channel", NOTIFY_CHANNEL_WECOM_BOT))
    if channel == NOTIFY_CHANNEL_WECOM_APP:
        corp_id = str(runtime_cfg.get("wecom_app_corp_id", "") or "").strip()
        touser = str(runtime_cfg.get("wecom_app_touser", "") or "").strip()
        if corp_id and touser:
            return f"企业应用（CorpID: {corp_id}，UserID: {touser}）"
        return "企业应用（参数未完整）"
    webhook = str(runtime_cfg.get("wecom_webhook", "") or "").strip()
    parsed = urllib.parse.urlsplit(webhook) if webhook else urllib.parse.SplitResult("", "", "", "", "")
    return f"群机器人（{parsed.netloc or '--'}）"


def _validate_notify_runtime_config(runtime_cfg: Dict[str, Any]) -> str:
    channel = _normalize_notify_channel(runtime_cfg.get("channel", NOTIFY_CHANNEL_WECOM_BOT))
    if channel == NOTIFY_CHANNEL_WECOM_APP:
        if not str(runtime_cfg.get("wecom_app_corp_id", "") or "").strip():
            raise RuntimeError("通知推送已启用，但企业微信应用模式缺少 CorpID")
        if not str(runtime_cfg.get("wecom_app_secret", "") or "").strip():
            raise RuntimeError("通知推送已启用，但企业微信应用模式缺少 AppSecret")
        if _normalize_wecom_agent_id(runtime_cfg.get("wecom_app_agent_id", 0)) <= 0:
            raise RuntimeError("通知推送已启用，但企业微信应用模式 AgentID 无效")
        if not _normalize_wecom_touser(runtime_cfg.get("wecom_app_touser", "")):
            raise RuntimeError("通知推送已启用，但企业微信应用模式缺少接收人 UserID")
    else:
        if not _normalize_wecom_webhook(runtime_cfg.get("wecom_webhook", "")):
            raise RuntimeError("通知推送已启用，但企业微信群机器人 Webhook 未配置或格式无效")
    return channel


def send_notify_test_message(cfg: Dict[str, Any]) -> Dict[str, Any]:
    runtime_cfg = build_notify_runtime_config(cfg)
    now_label = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    channel = _normalize_notify_channel(runtime_cfg.get("channel", NOTIFY_CHANNEL_WECOM_BOT))
    channel_label = "企业微信应用 API" if channel == NOTIFY_CHANNEL_WECOM_APP else "企业微信群机器人"
    content = "\n".join(
        [
            "### 115 Media Hub 通知测试",
            f"> 时间：{now_label}",
            f"> 渠道：{channel_label}",
            "> 说明：若收到此消息，表示通知配置可用。",
            "> 策略：按开关推送“订阅更新成功 / 文件夹监控生成成功”事件。",
        ]
    )
    _send_notify_content(runtime_cfg, content, timeout=20)
    target_desc = _build_notify_target_desc(runtime_cfg)
    webhook_host = ""
    if channel == NOTIFY_CHANNEL_WECOM_BOT:
        parsed = urllib.parse.urlsplit(str(runtime_cfg.get("wecom_webhook", "") or "").strip())
        webhook_host = str(parsed.netloc or "").strip()
    return {
        "ok": True,
        "msg": "测试消息已发送",
        "enabled": bool(runtime_cfg.get("enabled", False)),
        "channel": channel,
        "target_desc": target_desc,
        "webhook_host": webhook_host,
        "sent_at": now_text(),
    }


async def push_subscription_success_notification(
    cfg: Dict[str, Any],
    task: Dict[str, Any],
    item: Dict[str, Any],
    effective_savepath: str,
    job_id: int,
    successful_count: int,
    imported_episode_list: List[int],
    baseline_last_episode: int,
    next_episode: int,
) -> Dict[str, Any]:
    runtime_cfg = build_notify_runtime_config(cfg)
    if not bool(runtime_cfg.get("enabled", False)):
        return {"pushed": False, "reason": "disabled"}

    channel = _validate_notify_runtime_config(runtime_cfg)

    media_type = str(task.get("media_type", "movie") or "movie").strip().lower()
    if media_type == "tv":
        baseline_episode = max(0, int(baseline_last_episode or 0))
        candidate_episodes = sorted(
            {
                max(0, int(value or 0))
                for value in (imported_episode_list or [])
                if max(0, int(value or 0)) > baseline_episode
            }
        )
        if not candidate_episodes and int(next_episode or 0) > baseline_episode:
            candidate_episodes = [int(next_episode)]
        if not candidate_episodes:
            return {"pushed": False, "reason": "no_new_episode", "channel": channel}
        dedupe_episodes = candidate_episodes
    else:
        dedupe_episodes = [0]

    task_name = str(task.get("name", "") or task.get("title", "") or "").strip()
    savepath = normalize_relative_path(effective_savepath)
    fresh_pairs = await asyncio.to_thread(
        _filter_fresh_subscription_notification_pairs,
        task_name,
        savepath,
        dedupe_episodes,
    )
    if not fresh_pairs:
        return {"pushed": False, "reason": "deduped", "channel": channel}

    fresh_episode_values = sorted(
        {
            max(0, int(episode_no or 0))
            for episode_no, _ in fresh_pairs
            if max(0, int(episode_no or 0)) > 0
        }
    )
    if media_type == "tv" and not fresh_episode_values:
        return {"pushed": False, "reason": "deduped", "channel": channel}

    content = _build_subscription_success_markdown(
        task=task,
        item=item,
        savepath=savepath,
        job_id=job_id,
        successful_count=successful_count,
        notify_episodes=fresh_episode_values if media_type == "tv" else [],
        next_episode=next_episode,
    )
    await asyncio.to_thread(_send_notify_content, runtime_cfg, content, 20)
    await asyncio.to_thread(
        _record_subscription_notification_pairs,
        task_name,
        savepath,
        fresh_pairs,
    )
    return {
        "pushed": True,
        "reason": "",
        "episodes": fresh_episode_values,
        "channel": channel,
    }


def _strip_monitor_media_extension(file_name: str) -> str:
    raw_name = str(file_name or "").strip()
    if not raw_name:
        return ""
    lowered = raw_name.lower()
    for ext in MONITOR_MEDIA_EXTENSIONS:
        if lowered.endswith(ext):
            return raw_name[: -len(ext)]
    return os.path.splitext(raw_name)[0]


def _extract_monitor_year(*values: Any) -> str:
    for value in values:
        match = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", str(value or ""))
        if match:
            return str(match.group(1) or "").strip()
    return ""


def _clean_monitor_title_segment(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.replace("\\", "/").split("/")[-1].strip()
    text = re.sub(r"(?i)\.strm$", "", text)
    text = re.sub(r"[._]+", " ", text)
    text = re.sub(r"[\[\]{}()<>【】（）「」『』《》]+", " ", text)
    text = re.sub(r"(?i)\b(?:19|20)\d{2}\b", " ", text)
    text = re.sub(r"(?i)\b(?:s\d{1,2}e\d{1,3}|s\d{1,2}|e\d{1,3}|ep\d{1,3}|season\s*\d{1,2})\b", " ", text)
    text = re.sub(r"第\s*\d{1,3}\s*(?:季|集|话|話)", " ", text, flags=re.IGNORECASE)
    text = re.sub(
        r"(?i)\b(?:2160p|1080p|720p|4k|uhd|hdr10\+?|hdr|dv|dovi|x265|x264|h265|h264|hevc|avc|bluray|web[-_. ]?dl|webrip|remux|atmos|aac\d*|dts(?:-hd)?|ddp\d(?:\.\d)?)\b",
        " ",
        text,
    )
    text = re.sub(r"\s+", " ", text).strip(" -_.")
    return text[:80]


def _is_generic_monitor_title_segment(value: str) -> bool:
    compact = re.sub(r"\s+", "", str(value or "").strip()).lower()
    if not compact:
        return True
    if compact in MONITOR_GENERIC_DIR_NAMES:
        return True
    if re.fullmatch(r"(?:s\d{1,2}e?\d{0,3}|e\d{1,3}|ep\d{1,3}|season\d{1,2}|第\d{1,3}(?:季|集|话|話)?|\d{1,4})", compact):
        return True
    return False


def _pick_monitor_media_title(file_stem: str, parent_segments: List[str]) -> str:
    candidates = [_clean_monitor_title_segment(file_stem)] + [_clean_monitor_title_segment(segment) for segment in parent_segments]
    for candidate in candidates:
        if candidate and not _is_generic_monitor_title_segment(candidate):
            return candidate
    return ""


def _parse_monitor_media_from_strm_path(strm_rel_path: str) -> Dict[str, Any]:
    normalized_rel = normalize_relative_path(str(strm_rel_path or "").strip())
    if not normalized_rel:
        return {}

    rel_without_strm = normalized_rel[:-5] if normalized_rel.lower().endswith(".strm") else normalized_rel
    rel_without_strm = normalize_relative_path(rel_without_strm)
    if not rel_without_strm:
        return {}

    parts = [part for part in rel_without_strm.split("/") if part]
    if not parts:
        return {}
    file_name = parts[-1]
    parent_segments = list(reversed(parts[:-1]))[:3]
    file_stem = _strip_monitor_media_extension(file_name)
    probe_text = " ".join([file_stem] + parent_segments + [rel_without_strm])
    meta = parse_resource_episode_meta({"title": file_stem, "raw_text": probe_text})
    season = max(0, int(meta.get("season", 0) or 0))
    episode = max(0, int(meta.get("episode", 0) or 0))
    media_type = "tv" if season > 0 or episode > 0 else "movie"
    year = _extract_monitor_year(file_stem, *parent_segments, rel_without_strm)
    title = _pick_monitor_media_title(file_stem, parent_segments)
    if not title:
        return {
            "matched": False,
            "path": normalized_rel,
            "media_type": media_type,
            "season": season,
            "episode": episode,
            "year": year,
            "title": "",
        }

    return {
        "matched": True,
        "path": normalized_rel,
        "media_type": media_type,
        "season": season,
        "episode": episode,
        "year": year,
        "title": title,
    }


def _build_monitor_media_summary(generated_strm_paths: List[str]) -> Dict[str, Any]:
    normalized_paths = unique_preserve_order(
        [
            normalize_relative_path(str(item or "").strip())
            for item in (generated_strm_paths or [])
            if normalize_relative_path(str(item or "").strip())
        ]
    )

    grouped: Dict[str, Dict[str, Any]] = {}
    unmatched_paths: List[str] = []
    matched_file_count = 0
    tv_file_count = 0
    movie_file_count = 0

    for rel_path in normalized_paths:
        parsed = _parse_monitor_media_from_strm_path(rel_path)
        if not parsed or not parsed.get("matched"):
            unmatched_paths.append(rel_path)
            continue

        matched_file_count += 1
        media_type = str(parsed.get("media_type", "movie") or "movie").strip().lower()
        if media_type == "tv":
            tv_file_count += 1
        else:
            movie_file_count += 1
        title = str(parsed.get("title", "") or "").strip()
        year = str(parsed.get("year", "") or "").strip()
        season = max(0, int(parsed.get("season", 0) or 0)) if media_type == "tv" else 0
        entry_key = safe_json_dumps(
            {
                "media_type": media_type,
                "title": title.lower(),
                "year": year,
                "season": season,
            }
        )
        if entry_key not in grouped:
            grouped[entry_key] = {
                "media_type": media_type,
                "title": title,
                "year": year,
                "season": season,
                "count": 0,
                "episodes": set(),
                "sample_path": str(parsed.get("path", "") or rel_path).strip(),
            }
        entry = grouped[entry_key]
        entry["count"] = max(0, int(entry.get("count", 0) or 0)) + 1
        episode_value = max(0, int(parsed.get("episode", 0) or 0))
        if media_type == "tv" and episode_value > 0:
            entry["episodes"].add(episode_value)

    items: List[Dict[str, Any]] = []
    for entry in grouped.values():
        episodes = sorted({max(0, int(value or 0)) for value in entry.get("episodes", set()) if max(0, int(value or 0)) > 0})
        items.append(
            {
                "media_type": str(entry.get("media_type", "movie") or "movie").strip().lower(),
                "title": str(entry.get("title", "") or "").strip(),
                "year": str(entry.get("year", "") or "").strip(),
                "season": max(0, int(entry.get("season", 0) or 0)),
                "count": max(0, int(entry.get("count", 0) or 0)),
                "episodes": episodes,
                "sample_path": str(entry.get("sample_path", "") or "").strip(),
            }
        )
    items.sort(key=lambda row: (str(row.get("media_type", "")) != "tv", -max(0, int(row.get("count", 0) or 0)), str(row.get("title", ""))))

    return {
        "items": items,
        "matched_file_count": matched_file_count,
        "tv_file_count": tv_file_count,
        "movie_file_count": movie_file_count,
        "unmatched_count": len(unmatched_paths),
        "unmatched_examples": unmatched_paths[:3],
    }


def _build_monitor_success_markdown(
    task: Dict[str, Any],
    trigger: str,
    stats: Dict[str, Any],
    media_summary: Dict[str, Any],
) -> str:
    now_label = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    task_label = _compact_text(task.get("name", "") or "未命名任务", 64)
    try:
        trigger_label = format_monitor_trigger(trigger)
    except Exception:
        trigger_label = str(trigger or "manual").strip() or "manual"
    task_root = normalize_relative_path(resolve_task_root(task))

    generated_count = max(0, int((stats or {}).get("generated", 0) or 0))
    matched_count = max(0, int(media_summary.get("matched_file_count", 0) or 0))
    tv_count = max(0, int(media_summary.get("tv_file_count", 0) or 0))
    movie_count = max(0, int(media_summary.get("movie_file_count", 0) or 0))
    unmatched_count = max(0, int(media_summary.get("unmatched_count", 0) or 0))
    matched_items = media_summary.get("items", []) if isinstance(media_summary.get("items", []), list) else []
    unmatched_examples = (
        media_summary.get("unmatched_examples", []) if isinstance(media_summary.get("unmatched_examples", []), list) else []
    )

    lines = [
        "### 文件夹监控生成成功",
        f"> 时间：{now_label}",
        f"> 任务：{task_label}",
        f"> 触发：{trigger_label}",
        f"> 输出目录：/strm/{_compact_text(task_root or '--', 120)}",
        f"> 新增 .strm：{generated_count} 条",
        f"> 影视匹配：{matched_count} 条（剧集 {tv_count} / 电影 {movie_count} / 未识别 {unmatched_count}）",
    ]

    if matched_items:
        lines.append("> 识别摘要：")
        preview_limit = 8
        for row in matched_items[:preview_limit]:
            media_type = str(row.get("media_type", "movie") or "movie").strip().lower()
            title = _compact_text(row.get("title", "") or "未命名", 56)
            year = str(row.get("year", "") or "").strip()
            year_text = f" ({year})" if year else ""
            count = max(0, int(row.get("count", 0) or 0))
            if media_type == "tv":
                season = max(0, int(row.get("season", 0) or 0))
                season_text = f"S{season:02d}" if season > 0 else "S--"
                episodes = row.get("episodes", []) if isinstance(row.get("episodes", []), list) else []
                episode_text = _format_notify_episode_summary(episodes)
                if episode_text:
                    lines.append(f"> - 剧集：{title}{year_text} {season_text}，新增集数 {episode_text}")
                else:
                    lines.append(f"> - 剧集：{title}{year_text} {season_text}，新增 {count} 条")
            else:
                lines.append(f"> - 电影：{title}{year_text}（{count} 条）")
        if len(matched_items) > preview_limit:
            lines.append(f"> - 其余 {len(matched_items) - preview_limit} 条请在 Web 监控日志查看")

    if unmatched_examples:
        lines.append("> 未识别示例：")
        for rel_path in unmatched_examples[:2]:
            lines.append(f"> - /strm/{_compact_text(rel_path, 96)}")

    return "\n".join(lines)


async def push_monitor_success_notification(
    cfg: Dict[str, Any],
    task: Dict[str, Any],
    trigger: str,
    stats: Dict[str, Any],
    generated_strm_paths: List[str],
) -> Dict[str, Any]:
    if not bool(cfg.get("notify_monitor_enabled", False)):
        return {"pushed": False, "reason": "monitor_disabled"}

    generated_count = max(0, int((stats or {}).get("generated", 0) or 0))
    normalized_paths = unique_preserve_order(
        [
            normalize_relative_path(str(item or "").strip())
            for item in (generated_strm_paths or [])
            if normalize_relative_path(str(item or "").strip())
        ]
    )
    if generated_count <= 0 or not normalized_paths:
        return {"pushed": False, "reason": "no_generated"}

    runtime_cfg = build_notify_runtime_config(cfg)
    channel = _validate_notify_runtime_config(runtime_cfg)

    media_summary = _build_monitor_media_summary(normalized_paths)
    content = _build_monitor_success_markdown(task, trigger, stats, media_summary)
    await asyncio.to_thread(_send_notify_content, runtime_cfg, content, 20)

    return {
        "pushed": True,
        "reason": "",
        "scene": NOTIFY_SCENE_MONITOR_SUCCESS,
        "channel": channel,
        "generated": generated_count,
        "matched": max(0, int(media_summary.get("matched_file_count", 0) or 0)),
        "unmatched": max(0, int(media_summary.get("unmatched_count", 0) or 0)),
    }
