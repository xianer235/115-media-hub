import asyncio
import contextvars
import os
import time
import unicodedata

from ..core import *  # noqa: F401,F403
from .monitor import queue_monitor_job
from .notify import push_subscription_success_notification
from .resource import cancel_resource_job, run_resource_job


SUBSCRIPTION_INVALID_LINK_CACHE_TTL_SECONDS = max(
    60 * 60,
    int(os.getenv("SUBSCRIPTION_INVALID_LINK_CACHE_TTL_SECONDS", str(7 * 24 * 60 * 60)) or (7 * 24 * 60 * 60)),
)
SUBSCRIPTION_DUPLICATE_VERIFY_RETRIES = max(
    0,
    int(os.getenv("SUBSCRIPTION_DUPLICATE_VERIFY_RETRIES", "2") or 2),
)
SUBSCRIPTION_DUPLICATE_VERIFY_DELAY_SECONDS = max(
    0.0,
    float(os.getenv("SUBSCRIPTION_DUPLICATE_VERIFY_DELAY_SECONDS", "3") or 3),
)
SUBSCRIPTION_SHARE_SCAN_CONCURRENCY = max(
    1,
    min(6, int(os.getenv("SUBSCRIPTION_SHARE_SCAN_CONCURRENCY", "3") or 3)),
)
SUBSCRIPTION_SHARE_SCAN_REQUEST_TIMEOUT_SECONDS = max(
    6,
    min(30, int(os.getenv("SUBSCRIPTION_SHARE_SCAN_REQUEST_TIMEOUT_SECONDS", "12") or 12)),
)
SUBSCRIPTION_SHARE_SCAN_RATE_LIMIT_SECONDS = max(
    0.05,
    min(2.0, float(os.getenv("SUBSCRIPTION_SHARE_SCAN_RATE_LIMIT_SECONDS", "0.25") or 0.25)),
)
SUBSCRIPTION_SHARE_SCAN_MAX_RETRIES = max(
    0,
    min(2, int(os.getenv("SUBSCRIPTION_SHARE_SCAN_MAX_RETRIES", "1") or 1)),
)
SUBSCRIPTION_QUARK_MAX_ATTEMPTS = max(
    8,
    min(120, int(os.getenv("SUBSCRIPTION_QUARK_MAX_ATTEMPTS", "60") or 60)),
)
SUBSCRIPTION_INVALID_LINK_STRONG_HINTS = (
    "链接无效",
    "链接失效",
    "链接已失效",
    "资源链接为空",
    "未能识别 115 分享链接",
    "分享内容为空",
    "分享不存在",
    "分享已失效",
    "分享已删除",
    "分享已取消",
    "分享已过期",
    "提取码错误",
    "提取碼錯誤",
    "访问码错误",
    "訪問碼錯誤",
    "口令错误",
    "密码错误",
    "密碼錯誤",
    "invalid magnet",
    "invalid share",
    "share not found",
)
SUBSCRIPTION_INVALID_LINK_TRANSIENT_HINTS = (
    "超时",
    "timeout",
    "稍后",
    "重试",
    "繁忙",
    "连接失败",
    "connection",
    "network",
    "proxy",
    "dns",
    "cookie 未配置",
    "cookie未配置",
)


def _normalize_subscription_candidate_link(link_url: Any) -> str:
    return str(link_url or "").strip()


def _build_subscription_quark_share_dedupe_key(
    link_url: Any,
    raw_text: Any = "",
    receive_code: Any = "",
) -> str:
    normalized_link = _normalize_subscription_candidate_link(link_url)
    if not normalized_link:
        return ""
    parsed = parse_quark_share_payload(normalized_link, str(raw_text or ""), str(receive_code or ""))
    share_code = str(parsed.get("share_code", "") or parsed.get("pwd_id", "")).strip().lower()
    normalized_receive = normalize_receive_code(parsed.get("receive_code", "")) or normalize_receive_code(receive_code)
    if share_code:
        return f"{share_code}|{normalized_receive.lower()}" if normalized_receive else share_code
    return str(parsed.get("url", "") or normalized_link).strip().lower()


def _collect_subscription_item_all_links(item: Dict[str, Any]) -> List[str]:
    payload = item if isinstance(item, dict) else {}
    raw_text = str(payload.get("raw_text", "") or "")
    extra_payload = payload.get("extra") if isinstance(payload.get("extra"), dict) else safe_json_loads(payload.get("extra_json"), {})
    links: List[str] = []
    raw_all_links = extra_payload.get("all_links", []) if isinstance(extra_payload, dict) else []
    if isinstance(raw_all_links, list):
        links.extend([_normalize_subscription_candidate_link(value) for value in raw_all_links if _normalize_subscription_candidate_link(value)])
    link_url = _normalize_subscription_candidate_link(payload.get("link_url", ""))
    if link_url:
        links.append(link_url)
    links.extend(extract_resource_links(raw_text))
    normalized_links = [
        _normalize_subscription_candidate_link(trim_resource_link_token(link))
        for link in links
        if _normalize_subscription_candidate_link(trim_resource_link_token(link))
    ]
    return unique_preserve_order(normalized_links)


def _expand_subscription_quark_item_variants(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    payload = item if isinstance(item, dict) else {}
    if not payload:
        return []
    raw_text = str(payload.get("raw_text", "") or "")
    extra_payload = payload.get("extra") if isinstance(payload.get("extra"), dict) else safe_json_loads(payload.get("extra_json"), {})
    default_receive_code = normalize_receive_code(payload.get("receive_code", "")) or normalize_receive_code(
        (extra_payload or {}).get("receive_code", "")
    )
    variants: List[Dict[str, Any]] = []
    seen_variant_keys: Set[str] = set()
    for raw_link in _collect_subscription_item_all_links(payload):
        normalized_link = _normalize_subscription_candidate_link(raw_link)
        if not normalized_link:
            continue
        if detect_resource_link_type(normalized_link) != "quark":
            continue
        parsed = parse_quark_share_payload(normalized_link, raw_text, default_receive_code)
        normalized_url = _normalize_subscription_candidate_link(parsed.get("url", "") or normalized_link)
        resolved_receive_code = normalize_receive_code(parsed.get("receive_code", "")) or default_receive_code
        share_key = _build_subscription_quark_share_dedupe_key(
            normalized_url,
            raw_text,
            resolved_receive_code,
        )
        dedupe_key = f"share:{share_key}" if share_key else f"url:{normalized_url.lower()}"
        if dedupe_key in seen_variant_keys:
            continue
        seen_variant_keys.add(dedupe_key)
        variant_extra = extra_payload.copy() if isinstance(extra_payload, dict) else {}
        if resolved_receive_code:
            variant_extra["receive_code"] = resolved_receive_code
        share_code = str(parsed.get("share_code", "") or parsed.get("pwd_id", "")).strip()
        if share_code:
            variant_extra["share_code"] = share_code
        variant = {
            **payload,
            "link_url": normalized_url,
            "link_type": "quark",
            "receive_code": resolved_receive_code,
            "extra": variant_extra,
        }
        variants.append(variant)
    return variants


_subscription_share_entry_runtime_cache_var: contextvars.ContextVar[Optional[Dict[str, Dict[str, Any]]]] = (
    contextvars.ContextVar("subscription_share_entry_runtime_cache", default=None)
)
_subscription_share_entry_refreshed_keys_var: contextvars.ContextVar[Optional[Set[str]]] = (
    contextvars.ContextVar("subscription_share_entry_refreshed_keys", default=None)
)


def _build_subscription_share_entry_runtime_key(share_url: str, receive_code: str, cid: str) -> str:
    link_type = resolve_resource_link_type("", str(share_url or "").strip())
    return "|".join(
        [
            link_type,
            str(share_url or "").strip(),
            normalize_receive_code(receive_code),
            str(cid or "0").strip() or "0",
        ]
    )


async def _fetch_subscription_share_entries(
    cookie: str,
    share_url: str,
    raw_text: str,
    cid: str,
    receive_code: str,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    normalized_share_url = str(share_url or "").strip()
    normalized_cid = str(cid or "0").strip() or "0"
    normalized_receive_code = normalize_receive_code(receive_code)
    link_type = resolve_resource_link_type("", normalized_share_url)
    runtime_key = _build_subscription_share_entry_runtime_key(
        normalized_share_url,
        normalized_receive_code,
        normalized_cid,
    )
    runtime_cache = _subscription_share_entry_runtime_cache_var.get()
    refreshed_keys = _subscription_share_entry_refreshed_keys_var.get()
    refresh_pending = bool(force_refresh)
    if refresh_pending and isinstance(refreshed_keys, set) and runtime_key in refreshed_keys:
        refresh_pending = False
    if (not refresh_pending) and isinstance(runtime_cache, dict):
        cached_payload = runtime_cache.get(runtime_key)
        if isinstance(cached_payload, dict) and cached_payload:
            return cached_payload

    if link_type == "quark":
        result = await asyncio.to_thread(
            list_quark_share_entries,
            cookie,
            normalized_share_url,
            raw_text,
            normalized_cid,
            normalized_receive_code,
            refresh_pending,
            SUBSCRIPTION_SHARE_SCAN_REQUEST_TIMEOUT_SECONDS,
        )
    else:
        result = await asyncio.to_thread(
            list_115_share_entries,
            cookie,
            normalized_share_url,
            raw_text,
            normalized_cid,
            normalized_receive_code,
            refresh_pending,
            SUBSCRIPTION_SHARE_SCAN_REQUEST_TIMEOUT_SECONDS,
            SUBSCRIPTION_SHARE_SCAN_RATE_LIMIT_SECONDS,
            SUBSCRIPTION_SHARE_SCAN_MAX_RETRIES,
        )
    if isinstance(runtime_cache, dict):
        runtime_cache[runtime_key] = result
    if refresh_pending and isinstance(refreshed_keys, set) and not bool(result.get("cache_stale", False)):
        refreshed_keys.add(runtime_key)
    return result


def _ensure_subscription_invalid_link_cache_table(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS subscription_invalid_link_cache (
            link_url TEXT PRIMARY KEY,
            link_type TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            hit_count INTEGER NOT NULL DEFAULT 0,
            first_failed_at TEXT NOT NULL DEFAULT '',
            last_failed_at TEXT NOT NULL DEFAULT '',
            expires_at TEXT NOT NULL DEFAULT ''
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_subscription_invalid_link_cache_expires_at ON subscription_invalid_link_cache(expires_at)"
    )


def _prune_subscription_invalid_link_cache(conn: sqlite3.Connection, now_iso: str = "") -> int:
    now_value = str(now_iso or now_text()).strip() or now_text()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM subscription_invalid_link_cache WHERE expires_at <> '' AND expires_at <= ?",
        (now_value,),
    )
    return int(cursor.rowcount or 0)


def _load_subscription_invalid_link_cache(link_urls: List[str]) -> Dict[str, Dict[str, Any]]:
    normalized_links = unique_preserve_order(
        [_normalize_subscription_candidate_link(item) for item in (link_urls or []) if _normalize_subscription_candidate_link(item)]
    )
    if not normalized_links:
        return {}

    ensure_db()
    conn = open_db()
    try:
        _ensure_subscription_invalid_link_cache_table(conn)
        now_iso = now_text()
        _prune_subscription_invalid_link_cache(conn, now_iso)
        placeholders = ",".join(["?"] * len(normalized_links))
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT link_url, link_type, reason, hit_count, first_failed_at, last_failed_at, expires_at
            FROM subscription_invalid_link_cache
            WHERE link_url IN ({placeholders}) AND (expires_at = '' OR expires_at > ?)
            """,
            tuple(normalized_links + [now_iso]),
        )
        rows = cursor.fetchall()
        conn.commit()
    finally:
        conn.close()

    cache: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        link_url = _normalize_subscription_candidate_link(row["link_url"])
        if not link_url:
            continue
        cache[link_url] = {
            "link_url": link_url,
            "link_type": str(row["link_type"] or "").strip(),
            "reason": str(row["reason"] or "").strip(),
            "hit_count": max(0, int(row["hit_count"] or 0)),
            "first_failed_at": str(row["first_failed_at"] or "").strip(),
            "last_failed_at": str(row["last_failed_at"] or "").strip(),
            "expires_at": str(row["expires_at"] or "").strip(),
        }
    return cache


def _record_subscription_invalid_link_cache(link_url: str, link_type: str, reason: str) -> Dict[str, Any]:
    normalized_link = _normalize_subscription_candidate_link(link_url)
    if not normalized_link:
        return {}
    normalized_type = str(link_type or "").strip().lower()
    normalized_reason = str(reason or "").strip()[:240]
    now_iso = now_text()
    ttl_seconds = max(60 * 60, int(SUBSCRIPTION_INVALID_LINK_CACHE_TTL_SECONDS or (7 * 24 * 60 * 60)))
    expires_at = (datetime.now() + timedelta(seconds=ttl_seconds)).isoformat(timespec="seconds")

    ensure_db()
    conn = open_db()
    try:
        _ensure_subscription_invalid_link_cache_table(conn)
        _prune_subscription_invalid_link_cache(conn, now_iso)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT hit_count, first_failed_at FROM subscription_invalid_link_cache WHERE link_url = ?",
            (normalized_link,),
        )
        row = cursor.fetchone()
        if row:
            hit_count = max(0, int(row["hit_count"] or 0)) + 1
            first_failed_at = str(row["first_failed_at"] or "").strip() or now_iso
            cursor.execute(
                """
                UPDATE subscription_invalid_link_cache
                SET link_type = ?, reason = ?, hit_count = ?, first_failed_at = ?, last_failed_at = ?, expires_at = ?
                WHERE link_url = ?
                """,
                (
                    normalized_type,
                    normalized_reason,
                    hit_count,
                    first_failed_at,
                    now_iso,
                    expires_at,
                    normalized_link,
                ),
            )
        else:
            hit_count = 1
            first_failed_at = now_iso
            cursor.execute(
                """
                INSERT INTO subscription_invalid_link_cache(
                    link_url, link_type, reason, hit_count, first_failed_at, last_failed_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_link,
                    normalized_type,
                    normalized_reason,
                    hit_count,
                    first_failed_at,
                    now_iso,
                    expires_at,
                ),
            )
        conn.commit()
    finally:
        conn.close()

    return {
        "link_url": normalized_link,
        "link_type": normalized_type,
        "reason": normalized_reason,
        "hit_count": hit_count,
        "first_failed_at": first_failed_at,
        "last_failed_at": now_iso,
        "expires_at": expires_at,
    }


def _is_subscription_invalid_link_error(detail: str, link_type: str = "") -> bool:
    message = str(detail or "").strip()
    if not message:
        return False
    lowered = message.lower()

    strong_hit = any(str(hint).lower() in lowered for hint in SUBSCRIPTION_INVALID_LINK_STRONG_HINTS)
    transient_hit = any(str(hint).lower() in lowered for hint in SUBSCRIPTION_INVALID_LINK_TRANSIENT_HINTS)
    if strong_hit:
        return True
    if transient_hit:
        return False

    if ("提取码" in message or "提取碼" in message or "访问码" in message or "訪問碼" in message or "密码" in message or "口令" in message) and (
        "错误" in message or "失效" in message or "不存在" in message
    ):
        return True
    if "分享" in message and any(token in message for token in ("失效", "删除", "取消", "过期", "不存在", "無效")):
        return True

    normalized_type = str(link_type or "").strip().lower()
    if normalized_type == "magnet":
        if "magnet" in lowered and any(token in lowered for token in ("invalid", "unsupported", "not found")):
            return True
    elif normalized_type == "115share":
        if any(token in lowered for token in ("invalid share", "share not found", "share expired")):
            return True
    return False


def _load_subscription_task(cfg: Dict[str, Any], task_name: str) -> Dict[str, Any]:
    for raw_task in cfg.get("subscription_tasks", []) or []:
        task = normalize_subscription_task(raw_task or {})
        if task.get("name") == task_name:
            return task
    return {}


def _build_subscription_run_id(task_name: str) -> str:
    normalized_name = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(task_name or "").strip()).strip("-").lower()
    if not normalized_name:
        normalized_name = "task"
    return f"sub-{normalized_name[:36]}-{int(time.time() * 1000)}"


def _format_elapsed_seconds(seconds: float) -> str:
    normalized = max(0.0, float(seconds or 0.0))
    return f"{normalized:.2f}秒"


SUBSCRIPTION_STAGE_TIMING_ORDER: Tuple[Tuple[str, str], ...] = (
    ("prepare", "准备"),
    ("search", "搜索"),
    ("calibrate", "目录校准"),
    ("import", "候选导入"),
    ("finalize", "收口"),
)


SUBSCRIPTION_REASON_CODE_LABELS: Dict[str, str] = {
    "ok": "正常",
    "unknown": "未知原因",
    "no_precise_episode_match": "未匹配到缺失剧集文件",
    "manifest_no_precise_episode_match": "清单回退后仍未匹配到缺失剧集",
    "manifest_no_missing": "清单中未发现缺失剧集",
    "manifest_empty": "分享清单为空",
    "manifest_fallback": "按清单回退匹配",
    "no_episode_files": "未识别到剧集文件",
    "missing_episodes_empty": "缺失集为空",
    "cookie_missing": "未配置网盘 Cookie",
    "share_url_missing": "分享链接为空",
    "subdir_not_found": "未命中订阅子目录",
    "subdir_ambiguous": "订阅子目录匹配不唯一",
    "subdir_selection_empty": "子目录筛选结果为空",
    "target_is_share_root": "目标子目录等于分享根目录",
    "share_root_unreachable": "分享根目录不可访问",
    "share_anchor_unreachable": "锚点目录不可访问",
    "share_root_wrapper_unreachable": "分享根目录包装层不可访问",
    "subdir_entry_invalid": "子目录条目无效",
    "subdir_cid_missing": "子目录 CID 缺失",
    "subdir_branch_unreachable": "子目录分支不可访问",
    "subdir_target_invalid": "子目录目标无效",
    "not_found": "未找到匹配目录",
    "ambiguous": "匹配结果不唯一",
    "weak_match": "匹配度不足",
    "refine_selection_empty": "目录收敛后为空",
}


def _format_subscription_reason_code(reason_code: Any) -> str:
    normalized = str(reason_code or "").strip()
    if not normalized:
        return "未知原因"
    share_subdir_prefix = "share_subdir_"
    if normalized.startswith(share_subdir_prefix) and len(normalized) > len(share_subdir_prefix):
        nested = _format_subscription_reason_code(normalized[len(share_subdir_prefix):])
        return f"子目录解析：{nested}"
    return SUBSCRIPTION_REASON_CODE_LABELS.get(normalized, normalized)


def _format_subscription_reason_chain(reason_chain: Any) -> str:
    raw = str(reason_chain or "").strip()
    if not raw:
        return "未知原因"
    parts = [segment.strip() for segment in raw.split("->") if segment and segment.strip()]
    if not parts:
        return "未知原因"
    return " -> ".join([_format_subscription_reason_code(part) for part in parts])


def _create_subscription_stage_timer(initial_stage: str = "prepare") -> Dict[str, Any]:
    now = time.perf_counter()
    stage_name = str(initial_stage or "").strip().lower()
    return {
        "run_started_at": now,
        "current_stage": stage_name,
        "stage_started_at": now if stage_name else 0.0,
        "stages": {},
    }


def _subscription_stage_timer_enter(timer: Optional[Dict[str, Any]], stage_name: str) -> None:
    if not isinstance(timer, dict):
        return
    now = time.perf_counter()
    active_stage = str(timer.get("current_stage", "") or "").strip().lower()
    stage_started_at = float(timer.get("stage_started_at", 0.0) or 0.0)
    stage_durations = timer.get("stages")
    if not isinstance(stage_durations, dict):
        stage_durations = {}
        timer["stages"] = stage_durations
    if active_stage and stage_started_at > 0:
        stage_durations[active_stage] = float(stage_durations.get(active_stage, 0.0) or 0.0) + max(0.0, now - stage_started_at)
    next_stage = str(stage_name or "").strip().lower()
    timer["current_stage"] = next_stage
    timer["stage_started_at"] = now if next_stage else 0.0


def _subscription_stage_timer_snapshot(timer: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    now = time.perf_counter()
    if not isinstance(timer, dict):
        return {
            "total_seconds": 0.0,
            "stages": {},
        }
    run_started_at = float(timer.get("run_started_at", 0.0) or 0.0)
    if run_started_at <= 0:
        run_started_at = now
    stage_durations = timer.get("stages")
    normalized_stage_durations: Dict[str, float] = {}
    if isinstance(stage_durations, dict):
        normalized_stage_durations = {
            str(key or "").strip().lower(): max(0.0, float(value or 0.0))
            for key, value in stage_durations.items()
            if str(key or "").strip()
        }
    active_stage = str(timer.get("current_stage", "") or "").strip().lower()
    stage_started_at = float(timer.get("stage_started_at", 0.0) or 0.0)
    if active_stage and stage_started_at > 0:
        normalized_stage_durations[active_stage] = float(normalized_stage_durations.get(active_stage, 0.0) or 0.0) + max(
            0.0,
            now - stage_started_at,
        )
    return {
        "total_seconds": max(0.0, now - run_started_at),
        "stages": normalized_stage_durations,
    }


def _build_subscription_stage_timing_log_lines(timer: Optional[Dict[str, Any]]) -> Tuple[str, str]:
    snapshot = _subscription_stage_timer_snapshot(timer)
    stage_durations = snapshot.get("stages", {}) if isinstance(snapshot.get("stages"), dict) else {}
    parts = [
        f"{label} {_format_elapsed_seconds(float(stage_durations.get(stage_key, 0.0) or 0.0))}"
        for stage_key, label in SUBSCRIPTION_STAGE_TIMING_ORDER
    ]
    return (
        f"步骤耗时：{'｜'.join(parts)}",
        f"总用时：{_format_elapsed_seconds(float(snapshot.get('total_seconds', 0.0) or 0.0))}",
    )


def _collect_subscription_batch_success_jobs(created_job_ids: Set[int]) -> List[Dict[str, Any]]:
    success_jobs: List[Dict[str, Any]] = []
    unique_job_ids = sorted({max(0, int(job_id or 0)) for job_id in created_job_ids if int(job_id or 0) > 0})
    for job_id in unique_job_ids:
        job = get_resource_job(job_id, include_private=True)
        if not job:
            continue
        status = str(job.get("status", "") or "").strip().lower()
        if status not in ("submitted", "completed"):
            continue
        success_jobs.append(job)
    return success_jobs


def _recover_subscription_submitted_jobs(limit: int = 160) -> Dict[str, int]:
    jobs = list_resource_jobs_by_source("subscription_auto", limit=max(20, int(limit or 160)), scan_limit=1200)
    stale_jobs = [
        job
        for job in jobs
        if str(job.get("status", "") or "").strip().lower() == "submitted"
        and not str(job.get("last_triggered_at", "") or "").strip()
    ]
    if not stale_jobs:
        return {
            "checked": len(jobs),
            "stale": 0,
            "recovered": 0,
            "triggered_groups": 0,
            "triggered_jobs": 0,
            "skipped_no_monitor": 0,
            "skipped_missing_monitor": 0,
        }

    live_cfg = get_config()
    live_monitor_tasks = live_cfg.get("monitor_tasks", []) if isinstance(live_cfg.get("monitor_tasks"), list) else []
    active_monitor_tasks = {
        str(task.get("name", "") or "").strip()
        for task in live_monitor_tasks
        if str(task.get("name", "") or "").strip()
    }

    grouped_jobs: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    no_monitor_jobs: List[Dict[str, Any]] = []
    missing_monitor_jobs: List[Dict[str, Any]] = []
    for job in stale_jobs:
        monitor_task_name = str(job.get("monitor_task_name", "") or "").strip()
        savepath = normalize_relative_path(job.get("savepath", ""))
        if not monitor_task_name or not savepath:
            no_monitor_jobs.append(job)
            continue
        if monitor_task_name not in active_monitor_tasks:
            missing_monitor_jobs.append(job)
            continue
        grouped_jobs.setdefault((monitor_task_name, savepath), []).append(job)

    now_iso = now_text()
    completed_resource_ids: Set[int] = set()
    recovered = 0
    triggered_groups = 0
    triggered_jobs = 0
    skipped_no_monitor = 0
    skipped_missing_monitor = 0

    for job in no_monitor_jobs:
        job_id = max(0, int(job.get("id", 0) or 0))
        if job_id <= 0:
            continue
        base_detail = str(job.get("status_detail", "") or "").strip()
        detail = (
            f"{base_detail}；历史待刷新收口：当前保存路径未纳入文件夹监控，本次不触发 strm 刷新"
            if base_detail
            else "历史待刷新收口：当前保存路径未纳入文件夹监控，本次不触发 strm 刷新"
        )
        update_resource_job(
            job_id,
            status="completed",
            status_detail=detail,
            finished_at=now_iso,
        )
        recovered += 1
        skipped_no_monitor += 1
        resource_id = max(0, int(job.get("resource_id", 0) or 0))
        if resource_id > 0:
            completed_resource_ids.add(resource_id)

    for job in missing_monitor_jobs:
        job_id = max(0, int(job.get("id", 0) or 0))
        if job_id <= 0:
            continue
        monitor_task_name = str(job.get("monitor_task_name", "") or "").strip()
        base_detail = str(job.get("status_detail", "") or "").strip()
        detail = (
            f"{base_detail}；历史待刷新收口：监控任务「{monitor_task_name or '--'}」已不存在，跳过刷新"
            if base_detail
            else f"历史待刷新收口：监控任务「{monitor_task_name or '--'}」已不存在，跳过刷新"
        )
        update_resource_job(
            job_id,
            status="completed",
            status_detail=detail,
            finished_at=now_iso,
        )
        recovered += 1
        skipped_missing_monitor += 1
        resource_id = max(0, int(job.get("resource_id", 0) or 0))
        if resource_id > 0:
            completed_resource_ids.add(resource_id)

    for (monitor_task_name, savepath), grouped in grouped_jobs.items():
        queue_status = queue_monitor_job(
            monitor_task_name,
            "resource",
            {
                "savepath": savepath,
                "title": "历史待刷新收口",
            },
        )
        triggered_groups += 1
        for job in grouped:
            job_id = max(0, int(job.get("id", 0) or 0))
            if job_id <= 0:
                continue
            base_detail = str(job.get("status_detail", "") or "").strip()
            detail = (
                f"{base_detail}；历史待刷新收口：已统一触发监控「{monitor_task_name}」({queue_status})"
                if base_detail
                else f"历史待刷新收口：已统一触发监控「{monitor_task_name}」({queue_status})"
            )
            update_resource_job(
                job_id,
                status="completed",
                status_detail=detail,
                last_triggered_at=now_iso,
                finished_at=now_iso,
            )
            recovered += 1
            triggered_jobs += 1
            resource_id = max(0, int(job.get("resource_id", 0) or 0))
            if resource_id > 0:
                completed_resource_ids.add(resource_id)

    if completed_resource_ids:
        conn = open_db()
        try:
            for resource_id in sorted(completed_resource_ids):
                update_resource_item_status(conn, resource_id, "completed")
            conn.commit()
        finally:
            conn.close()

    return {
        "checked": len(jobs),
        "stale": len(stale_jobs),
        "recovered": recovered,
        "triggered_groups": triggered_groups,
        "triggered_jobs": triggered_jobs,
        "skipped_no_monitor": skipped_no_monitor,
        "skipped_missing_monitor": skipped_missing_monitor,
    }


def _finalize_subscription_batch_refresh(
    task_name: str,
    run_id: str,
    created_job_ids: Set[int],
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    result = {
        "run_id": str(run_id or "").strip(),
        "created_jobs": len({max(0, int(job_id or 0)) for job_id in created_job_ids if int(job_id or 0) > 0}),
        "successful_jobs": 0,
        "refresh_eligible_jobs": 0,
        "grouped_targets": 0,
        "triggered_groups": 0,
        "triggered_jobs": 0,
        "missing_monitor_task_groups": 0,
        "missing_monitor_task_jobs": 0,
    }
    if not result["run_id"] or result["created_jobs"] <= 0:
        return result

    success_jobs = _collect_subscription_batch_success_jobs(created_job_ids)
    result["successful_jobs"] = len(success_jobs)
    if not success_jobs:
        return result

    grouped_jobs: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    non_refresh_jobs: List[Dict[str, Any]] = []
    for job in success_jobs:
        monitor_task_name = str(job.get("monitor_task_name", "") or "").strip()
        savepath = normalize_relative_path(job.get("savepath", ""))
        if not monitor_task_name or not savepath:
            non_refresh_jobs.append(job)
            continue
        grouped_jobs.setdefault((monitor_task_name, savepath), []).append(job)
    result["refresh_eligible_jobs"] = sum(len(jobs) for jobs in grouped_jobs.values())
    result["grouped_targets"] = len(grouped_jobs)

    live_cfg = get_config()
    live_monitor_tasks = live_cfg.get("monitor_tasks", []) if isinstance(live_cfg.get("monitor_tasks"), list) else []
    fallback_monitor_tasks = cfg.get("monitor_tasks", []) if isinstance(cfg.get("monitor_tasks"), list) else []
    source_monitor_tasks = live_monitor_tasks or fallback_monitor_tasks
    active_monitor_tasks = {
        str(task.get("name", "") or "").strip()
        for task in source_monitor_tasks
        if str(task.get("name", "") or "").strip()
    }
    now_iso = now_text()
    completed_resource_ids: Set[int] = set()

    for job in non_refresh_jobs:
        job_id = max(0, int(job.get("id", 0) or 0))
        if job_id <= 0:
            continue
        base_detail = str(job.get("status_detail", "") or "").strip()
        detail = (
            f"{base_detail}；当前保存路径未纳入文件夹监控，本次不触发 strm 刷新"
            if base_detail
            else "当前保存路径未纳入文件夹监控，本次不触发 strm 刷新"
        )
        update_resource_job(
            job_id,
            status="completed",
            status_detail=detail,
            finished_at=now_iso,
        )
        resource_id = max(0, int(job.get("resource_id", 0) or 0))
        if resource_id > 0:
            completed_resource_ids.add(resource_id)

    if not grouped_jobs:
        if completed_resource_ids:
            conn = open_db()
            try:
                for resource_id in sorted(completed_resource_ids):
                    update_resource_item_status(conn, resource_id, "completed")
                conn.commit()
            finally:
                conn.close()
        return result

    for (monitor_task_name, savepath), jobs in grouped_jobs.items():
        if monitor_task_name not in active_monitor_tasks:
            result["missing_monitor_task_groups"] += 1
            result["missing_monitor_task_jobs"] += len(jobs)
            for job in jobs:
                job_id = max(0, int(job.get("id", 0) or 0))
                if job_id <= 0:
                    continue
                base_detail = str(job.get("status_detail", "") or "").strip()
                detail = (
                    f"{base_detail}；订阅批次 {result['run_id']} 跳过刷新：监控任务「{monitor_task_name}」已不存在"
                    if base_detail
                    else f"订阅批次 {result['run_id']} 跳过刷新：监控任务「{monitor_task_name}」已不存在"
                )
                update_resource_job(
                    job_id,
                    status="completed",
                    status_detail=detail,
                    finished_at=now_iso,
                )
                resource_id = max(0, int(job.get("resource_id", 0) or 0))
                if resource_id > 0:
                    completed_resource_ids.add(resource_id)
            continue

        queue_status = queue_monitor_job(
            monitor_task_name,
            "resource",
            {
                "savepath": savepath,
                "title": f"订阅批次收口：{task_name}",
            },
        )
        result["triggered_groups"] += 1
        for job in jobs:
            job_id = max(0, int(job.get("id", 0) or 0))
            if job_id <= 0:
                continue
            base_detail = str(job.get("status_detail", "") or "").strip()
            detail = (
                f"{base_detail}；订阅批次 {result['run_id']} 已统一触发监控：{monitor_task_name} ({queue_status})"
                if base_detail
                else f"订阅批次 {result['run_id']} 已统一触发监控：{monitor_task_name} ({queue_status})"
            )
            update_resource_job(
                job_id,
                status="completed",
                status_detail=detail,
                last_triggered_at=now_iso,
                finished_at=now_iso,
            )
            result["triggered_jobs"] += 1
            resource_id = max(0, int(job.get("resource_id", 0) or 0))
            if resource_id > 0:
                completed_resource_ids.add(resource_id)

    if completed_resource_ids:
        conn = open_db()
        try:
            for resource_id in sorted(completed_resource_ids):
                update_resource_item_status(conn, resource_id, "completed")
            conn.commit()
        finally:
            conn.close()

    return result


def get_subscription_task_episode_view(task_name: str) -> Dict[str, Any]:
    payload = _scan_subscription_task_episode_view_payload(task_name)
    return payload


def _scan_subscription_task_episode_view_payload(task_name: str) -> Dict[str, Any]:
    normalized_task_name = str(task_name or "").strip()
    if not normalized_task_name:
        raise RuntimeError("任务名称不能为空")

    cfg = get_config()
    task = _load_subscription_task(cfg, normalized_task_name)
    if not task:
        raise KeyError(normalized_task_name)

    if str(task.get("media_type", "movie") or "movie").strip().lower() != "tv":
        raise ValueError("仅电视剧任务支持集数视图")

    provider = normalize_subscription_provider(task.get("provider", "115"), fallback="115")

    base_savepath = normalize_relative_path(str(task.get("savepath", "")).strip())
    if not base_savepath:
        raise RuntimeError("任务未配置保存路径")

    scan_savepath = resolve_subscription_tv_base_savepath(task, base_savepath) or base_savepath
    folder_id = ""
    scan_result: Dict[str, Any] = {}
    if provider == "quark":
        cookie_quark = str(cfg.get("cookie_quark", "")).strip()
        if not cookie_quark:
            raise RuntimeError("请先在参数配置页填写 Quark Cookie")
        folder_id = ensure_quark_folder_id_by_path(cookie_quark, scan_savepath)
        scan_result = _scan_quark_existing_tv_episodes(cookie_quark, folder_id, task)
    else:
        cookie_115 = str(cfg.get("cookie_115", "")).strip()
        if not cookie_115:
            raise RuntimeError("请先在参数配置页填写 115 Cookie")
        folder_id = ensure_115_folder_id_by_path(cookie_115, scan_savepath)
        scan_result = _scan_115_existing_tv_episodes(cookie_115, folder_id, task)

    scan_episodes = scan_result.get("episodes", []) if isinstance(scan_result.get("episodes"), list) else []
    existing_episodes = sorted(
        {
            max(0, int(item or 0))
            for item in scan_episodes
            if 0 < max(0, int(item or 0)) <= 5000
        }
    )

    state = load_subscription_task_state(normalized_task_name, "tv")
    known_total = resolve_subscription_tv_total_episodes(
        task,
        state_total=max(0, int(state.get("total_episodes", 0) or 0)),
    )
    last_episode = max(0, int(state.get("last_episode", 0) or 0))
    max_episode = existing_episodes[-1] if existing_episodes else 0

    display_total = _compute_subscription_episode_display_total(
        known_total=known_total,
        last_episode=last_episode,
        max_episode=max_episode,
        multi_season_mode=is_subscription_multi_season_mode(task),
    )

    present_in_display = sum(1 for episode_no in existing_episodes if 1 <= episode_no <= display_total)
    missing_count = max(0, display_total - present_in_display)

    return {
        "task_name": normalized_task_name,
        "provider": provider,
        "media_type": "tv",
        "savepath": scan_savepath,
        "folder_id": str(folder_id or "").strip(),
        "existing_episodes": existing_episodes,
        "existing_count": len(existing_episodes),
        "max_episode": max_episode,
        "last_episode": last_episode,
        "total_episodes": known_total,
        "display_total_episodes": display_total,
        "missing_count": missing_count,
        "scan_stats": {
            "scanned_dirs": int(scan_result.get("scanned_dirs", 0) or 0),
            "scanned_entries": int(scan_result.get("scanned_entries", 0) or 0),
            "failed_dirs": int(scan_result.get("failed_dirs", 0) or 0),
            "truncated": bool(scan_result.get("truncated", False)),
        },
    }


def _compute_subscription_episode_display_total(
    known_total: int,
    last_episode: int,
    max_episode: int,
    multi_season_mode: bool,
) -> int:
    normalized_known_total = max(0, int(known_total or 0))
    normalized_last_episode = max(0, int(last_episode or 0))
    normalized_max_episode = max(0, int(max_episode or 0))

    # 单季模式下优先展示当前季总集数，避免历史多季进度把视图总格子抬高。
    if (not bool(multi_season_mode)) and normalized_known_total > 0:
        display_total = max(normalized_known_total, normalized_max_episode)
    else:
        display_total = max(normalized_known_total, normalized_last_episode, normalized_max_episode)

    if display_total <= 0:
        display_total = 60
    elif normalized_known_total <= 0 and display_total < 24:
        display_total = 24
    return max(1, min(1200, int(display_total)))


def rebuild_subscription_task_progress(task_name: str) -> Dict[str, Any]:
    normalized_task_name = str(task_name or "").strip()
    if not normalized_task_name:
        raise RuntimeError("任务名称不能为空")
    if subscription_status.get("running") and str(subscription_status.get("current_task", "") or "").strip() == normalized_task_name:
        raise RuntimeError("任务正在运行，请先中断后再重建")

    payload = _scan_subscription_task_episode_view_payload(normalized_task_name)
    scan_stats = payload.get("scan_stats", {}) if isinstance(payload.get("scan_stats"), dict) else {}
    scan_scanned_dirs = max(0, int(scan_stats.get("scanned_dirs", 0) or 0))
    scan_failed_dirs = max(0, int(scan_stats.get("failed_dirs", 0) or 0))
    scan_scanned_entries = max(0, int(scan_stats.get("scanned_entries", 0) or 0))
    scan_reliable = not (scan_scanned_dirs <= 0 and scan_failed_dirs > 0)
    if not scan_reliable:
        raise RuntimeError("目标目录扫描结果不可靠，请稍后重试")

    cfg = get_config()
    task = _load_subscription_task(cfg, normalized_task_name)
    if not task:
        raise KeyError(normalized_task_name)

    existing_episodes = {
        max(0, int(item or 0))
        for item in (payload.get("existing_episodes", []) if isinstance(payload.get("existing_episodes"), list) else [])
        if max(0, int(item or 0)) > 0
    }
    existing_count = len(existing_episodes)
    rebuilt_last_episode = max(existing_episodes) if existing_episodes else 0

    state = load_subscription_task_state(normalized_task_name, "tv")
    previous_last_episode = max(0, int(state.get("last_episode", 0) or 0))
    previous_status = str(state.get("status", "idle") or "idle").strip().lower() or "idle"
    previous_stats = state.get("stats", {}) if isinstance(state.get("stats"), dict) else {}
    known_total = resolve_subscription_tv_total_episodes(
        task,
        state_total=max(0, int(state.get("total_episodes", 0) or 0)),
    )

    ledger_sync = reconcile_subscription_episode_ledger(normalized_task_name, existing_episodes)
    activated_count = max(0, int(ledger_sync.get("activated", 0) or 0))
    staled_count = max(0, int(ledger_sync.get("staled", 0) or 0))
    active_ledger_count = sum(
        1
        for row in load_subscription_episode_ledger(normalized_task_name, include_stale=False).values()
        if str((row or {}).get("status", "active") or "active").strip().lower() == "active"
    )

    rebuilt_status = "completed" if known_total > 0 and rebuilt_last_episode >= known_total else "waiting"
    progress_label = f"E{rebuilt_last_episode}" if rebuilt_last_episode > 0 else "E0"
    total_label = f" / E{known_total}" if known_total > 0 else ""
    if existing_count > 0:
        detail = f"已按目标目录重建追更进度：{progress_label}{total_label}（识别 {existing_count} 集）"
    elif scan_scanned_entries <= 0:
        detail = f"已按目标目录重建追更进度：{progress_label}{total_label}（目录未识别到剧集文件）"
    else:
        detail = f"已按目标目录重建追更进度：{progress_label}{total_label}"
    if activated_count > 0 or staled_count > 0:
        detail += f"；账本恢复 {activated_count} 集 / 标记失效 {staled_count} 集"
    if rebuilt_status == "completed":
        detail += "；当前已与总集数对齐"
    else:
        detail += "；等待后续追更"

    merged_stats = {
        **previous_stats,
        "existing_episode_scan_ready": True,
        "existing_episode_count": existing_count,
        "existing_episode_max": rebuilt_last_episode,
        "existing_episode_scanned_dirs": scan_scanned_dirs,
        "existing_episode_scanned_entries": scan_scanned_entries,
        "existing_episode_failed_dirs": scan_failed_dirs,
        "existing_episode_scan_truncated": bool(scan_stats.get("truncated", False)),
        "episode_ledger_activated": activated_count,
        "episode_ledger_staled": staled_count,
        "episode_ledger_active_count": active_ledger_count,
        "rebuild_from_directory": True,
        "rebuild_previous_last_episode": previous_last_episode,
        "rebuild_previous_status": previous_status,
        "rebuild_at": now_text(),
    }
    upsert_subscription_task_state(
        normalized_task_name,
        media_type="tv",
        status=rebuilt_status,
        progress=100,
        detail=detail,
        last_error="",
        last_episode=rebuilt_last_episode,
        total_episodes=known_total,
        stats=merged_stats,
    )

    updated_payload = _scan_subscription_task_episode_view_payload(normalized_task_name)
    return {
        "task_name": normalized_task_name,
        "status": rebuilt_status,
        "detail": detail,
        "last_episode": rebuilt_last_episode,
        "previous_last_episode": previous_last_episode,
        "total_episodes": known_total,
        "existing_count": existing_count,
        "episode_view": updated_payload,
        "ledger": {
            "activated": activated_count,
            "staled": staled_count,
            "active_count": active_ledger_count,
        },
    }


def _sync_task_total_episodes(task_name: str, total_episodes: int) -> None:
    normalized_total = max(0, int(total_episodes or 0))
    if normalized_total <= 0:
        return
    cfg = get_config()
    tasks = cfg.get("subscription_tasks", []) if isinstance(cfg.get("subscription_tasks"), list) else []
    changed = False
    updated = []
    for raw_task in tasks:
        task = normalize_subscription_task(raw_task or {})
        if task.get("name") == task_name and int(task.get("total_episodes", 0) or 0) <= 0:
            if not is_subscription_multi_season_mode(task):
                tmdb_season_total = get_subscription_tmdb_season_total_episodes(task)
                if tmdb_season_total > 0:
                    updated.append(task)
                    continue
            task["total_episodes"] = normalized_total
            changed = True
        updated.append(task)
    if changed:
        cfg["subscription_tasks"] = updated
        save_config(cfg)


def _build_subscription_search_keywords(task: Dict[str, Any], limit: int = 4) -> List[str]:
    title = re.sub(r"\s+", " ", str(task.get("title", "") or "").strip())
    aliases = task.get("aliases", []) if isinstance(task.get("aliases"), list) else []
    tmdb_title = re.sub(r"\s+", " ", str(task.get("tmdb_title", "") or "").strip())
    tmdb_original_title = re.sub(r"\s+", " ", str(task.get("tmdb_original_title", "") or "").strip())
    tmdb_aliases = task.get("tmdb_aliases", []) if isinstance(task.get("tmdb_aliases"), list) else []
    media_type = str(task.get("media_type", "movie") or "movie").strip().lower()
    anime_mode = is_subscription_anime_compatible_task(task)
    multi_season_mode = is_subscription_multi_season_mode(task)
    year = normalize_tmdb_year(task.get("year", "")) or normalize_tmdb_year(task.get("tmdb_year", ""))
    season = max(1, int(task.get("season", 1) or 1))

    keywords: List[str] = []
    if title:
        keywords.append(title)
        if media_type == "movie" and year and re.fullmatch(r"(19|20)\d{2}", year):
            keywords.append(f"{title} {year}")
        if media_type == "tv" and season > 1 and not multi_season_mode:
            keywords.append(f"{title} S{season:02d}")
            keywords.append(f"{title} 第{season}季")
        if media_type == "tv" and anime_mode:
            keywords.append(f"{title} 动漫")
    if tmdb_title:
        keywords.append(tmdb_title)
        if media_type == "movie" and year:
            keywords.append(f"{tmdb_title} {year}")
        if media_type == "tv" and season > 1 and not multi_season_mode:
            keywords.append(f"{tmdb_title} S{season:02d}")
    if tmdb_original_title:
        keywords.append(tmdb_original_title)
    for alias in tmdb_aliases:
        alias_keyword = re.sub(r"\s+", " ", str(alias or "").strip())
        if alias_keyword:
            keywords.append(alias_keyword)
    for alias in aliases:
        alias_keyword = re.sub(r"\s+", " ", str(alias or "").strip())
        if alias_keyword:
            keywords.append(alias_keyword)

    seen: Set[str] = set()
    normalized_keywords: List[str] = []
    for keyword in keywords:
        marker = keyword.lower()
        if marker in seen:
            continue
        seen.add(marker)
        normalized_keywords.append(keyword)
    return normalized_keywords[: max(1, int(limit or 6))]


def _merge_subscription_search_errors(errors: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    merged: List[Dict[str, str]] = []
    seen: Set[str] = set()
    for raw in errors:
        payload = raw if isinstance(raw, dict) else {}
        channel_id = str(payload.get("channel_id", "") or "").strip()
        message = str(payload.get("message", "") or "").strip()
        if not channel_id and not message:
            continue
        key = f"{channel_id}|{message}"
        if key in seen:
            continue
        seen.add(key)
        merged.append(
            {
                "channel_id": channel_id,
                "name": str(payload.get("name", "") or channel_id).strip(),
                "message": message,
            }
        )
    return merged


def _expand_episode_values(start_episode: int, end_episode: int, max_expand: int = 400) -> Set[int]:
    start = max(0, int(start_episode or 0))
    end = max(0, int(end_episode or 0))
    if start <= 0 and end <= 0:
        return set()
    if start <= 0:
        start = end
    if end <= 0:
        end = start
    if end < start:
        start, end = end, start
    total_count = end - start + 1
    if total_count <= 0:
        return set()
    if total_count > max(1, int(max_expand or 400)):
        return {start, end}
    return {episode for episode in range(start, end + 1) if 0 < episode <= 5000}


def _clamp_episode_values(episode_values: Set[int], episode_upper_bound: int = 0) -> Set[int]:
    normalized = {max(0, int(value or 0)) for value in (episode_values or set()) if max(0, int(value or 0)) > 0}
    upper_bound = max(0, int(episode_upper_bound or 0))
    if upper_bound > 0:
        normalized = {value for value in normalized if value <= upper_bound}
    return normalized


def _extract_task_episodes_from_name(task: Dict[str, Any], name: str, max_expand: int = 400) -> Set[int]:
    normalized_name = str(name or "").strip()
    if not normalized_name:
        return set()
    meta = parse_resource_episode_meta({"title": normalized_name, "raw_text": normalized_name})
    episode = max(0, int(meta.get("episode", 0) or 0))
    range_start = max(0, int(meta.get("range_start", 0) or 0))
    range_end = max(0, int(meta.get("range_end", 0) or 0))
    season = max(0, int(meta.get("season", 0) or 0))
    if is_subscription_multi_season_mode(task):
        if season > 0:
            absolute_episode = convert_subscription_episode_to_absolute(task, season, episode)
            if absolute_episode > 0:
                episode = absolute_episode
            absolute_range_start, absolute_range_end = convert_subscription_episode_range_to_absolute(
                task, season, range_start, range_end
            )
            if absolute_range_end > 0:
                range_start = absolute_range_start
                range_end = absolute_range_end
        if range_end > 0:
            expanded = _expand_episode_values(range_start, range_end, max_expand=max_expand)
            if expanded:
                return expanded
        return {episode} if 0 < episode <= 5000 else set()

    target_season = max(1, int(task.get("season", 1) or 1))
    if season > 0 and season != target_season:
        return set()
    if range_end > 0:
        expanded = _expand_episode_values(range_start, range_end, max_expand=max_expand)
        if expanded:
            return expanded
        return {range_end} if 0 < range_end <= 5000 else set()
    return {episode} if 0 < episode <= 5000 else set()


def _extract_numeric_episode_from_filename(file_name: str) -> int:
    normalized_name = str(file_name or "").strip()
    if not normalized_name:
        return 0
    stem = os.path.splitext(normalized_name)[0]
    stem_tail = str(stem or "").replace("\\", "/").split("/")[-1].strip()
    if not stem_tail:
        return 0

    # 兼容类似 "04(1).mkv" 的分段命名：括号中的分段号不应并入剧集号。
    stem_tail_numeric = re.sub(r"\s*[\(\[（【]\s*\d{1,2}\s*[\)\]）】]\s*$", "", stem_tail)
    compact = re.sub(r"[\s._\-(){}\[\]<>【】（）「」《》]+", "", stem_tail_numeric or stem_tail)
    if not compact:
        return 0

    for pattern in (
        re.compile(r"^0*(\d{1,3})$"),
        re.compile(r"^第?0*(\d{1,3})(?:集|话|話)?$", re.IGNORECASE),
    ):
        matched = pattern.fullmatch(compact)
        if not matched:
            continue
        value = max(0, int(matched.group(1) or 0))
        if 0 < value <= 5000:
            return value
    return 0


def _extract_task_episodes_from_file_entry(task: Dict[str, Any], file_name: str, parent_path: str = "") -> Set[int]:
    normalized_file_name = normalize_relative_path(str(file_name or "").strip())
    if not normalized_file_name:
        return set()
    normalized_parent = normalize_relative_path(str(parent_path or "").strip())

    for probe in (normalized_file_name, os.path.splitext(normalized_file_name)[0]):
        parsed = _extract_task_episodes_from_name(task, probe)
        if parsed:
            return parsed

    numeric_episode = _extract_numeric_episode_from_filename(normalized_file_name)
    if numeric_episode > 0:
        parent_meta = parse_resource_episode_meta({"title": normalized_parent, "raw_text": normalized_parent})
        parent_season = max(0, int(parent_meta.get("season", 0) or 0))
        if is_subscription_multi_season_mode(task):
            if parent_season > 0:
                absolute_episode = convert_subscription_episode_to_absolute(task, parent_season, numeric_episode)
                if absolute_episode > 0:
                    return {absolute_episode}
            return {numeric_episode}
        target_season = max(1, int(task.get("season", 1) or 1))
        if parent_season > 0 and parent_season != target_season:
            return set()
        return {numeric_episode}

    if normalized_parent:
        full_name = normalize_relative_path(join_relative_path(normalized_parent, normalized_file_name))
        full_path_values = _extract_task_episodes_from_name(task, full_name)
        # 父目录区间（如 E01-E24）会让每个子文件都命中整段范围，容易造成整包误选。
        # 仅在全路径能明确到单集时才回退使用。
        if len(full_path_values) == 1:
            return full_path_values
    return set()


def _candidate_episode_values(
    candidate: Dict[str, Any],
    max_expand: int = 400,
    episode_upper_bound: int = 0,
) -> Set[int]:
    payload = candidate if isinstance(candidate, dict) else {}
    episode = max(0, int(payload.get("episode", 0) or 0))
    range_start = max(0, int(payload.get("range_start", 0) or 0))
    range_end = max(0, int(payload.get("range_end", 0) or 0))
    values: Set[int] = set()
    if range_end > 0:
        values.update(_expand_episode_values(range_start, range_end, max_expand=max_expand))
        if not values and range_end > 0:
            values.add(range_end)
    if episode > 0:
        values.add(episode)
    return _clamp_episode_values(values, episode_upper_bound=episode_upper_bound)


def _candidate_anchor_episode(candidate: Dict[str, Any], episode_upper_bound: int = 0) -> int:
    values = _candidate_episode_values(candidate, max_expand=200, episode_upper_bound=episode_upper_bound)
    if values:
        return max(values)
    anchor = max(0, int((candidate or {}).get("episode", 0) or 0))
    upper_bound = max(0, int(episode_upper_bound or 0))
    if upper_bound > 0 and anchor > upper_bound:
        anchor = upper_bound
    return anchor


def _candidate_confident_episode_values(candidate: Dict[str, Any], episode_upper_bound: int = 0) -> Set[int]:
    """
    候选命名中的大范围区间（如 E1-E26）并不总能代表目录里每一集都完整可用。
    为避免“先命中一个大包后把后续补档候选全部跳过”，超大区间仅保留锚点集做本轮去重。
    中小范围（如 E1-E15）按完整范围记账，减少同轮重复整包导入。
    """
    values = _candidate_episode_values(candidate, episode_upper_bound=episode_upper_bound)
    if not values:
        return set()
    range_start = max(0, int((candidate or {}).get("range_start", 0) or 0))
    range_end = max(0, int((candidate or {}).get("range_end", 0) or 0))
    if range_start > 0 and range_end > 0:
        if range_end < range_start:
            range_start, range_end = range_end, range_start
        range_size = max(1, range_end - range_start + 1)
        if range_size > 20:
            return {max(values)}
    return values


def _candidate_missing_episode_values(
    candidate: Dict[str, Any],
    existing_episodes: Set[int],
    episode_upper_bound: int = 0,
) -> Set[int]:
    episode_values = _candidate_episode_values(candidate, episode_upper_bound=episode_upper_bound)
    if not episode_values:
        return set()
    normalized_existing = _clamp_episode_values(existing_episodes or set(), episode_upper_bound=episode_upper_bound)
    return {episode_no for episode_no in episode_values if episode_no not in normalized_existing}


def _resolve_recorded_episode_values(
    candidate: Dict[str, Any],
    selected_share_episode_values: Set[int],
    episode_upper_bound: int = 0,
) -> Set[int]:
    selected_values = _clamp_episode_values(selected_share_episode_values or set(), episode_upper_bound=episode_upper_bound)
    if selected_values:
        # 精细转存时，selected_share_episode_values 才是实际入库结果，应优先作为记账依据。
        return selected_values

    confident_episode_values = _candidate_confident_episode_values(candidate, episode_upper_bound=episode_upper_bound)
    if confident_episode_values:
        return confident_episode_values

    episode = max(0, int((candidate or {}).get("episode", 0) or 0))
    upper_bound = max(0, int(episode_upper_bound or 0))
    if upper_bound > 0 and episode > upper_bound:
        return set()
    if episode > 0:
        return {episode}
    return set()


def _evaluate_duplicate_receive_validation(
    verify_target_episodes: Set[int],
    pre_attempt_existing_episodes: Set[int],
    verify_scan_episodes: Set[int],
    scan_scanned_dirs: int,
    scan_scanned_entries: int,
    scan_failed_dirs: int,
    scan_truncated: bool,
) -> Dict[str, Any]:
    normalized_target = {
        max(0, int(value or 0))
        for value in (verify_target_episodes or set())
        if max(0, int(value or 0)) > 0
    }
    normalized_pre_attempt = {
        max(0, int(value or 0))
        for value in (pre_attempt_existing_episodes or set())
        if max(0, int(value or 0)) > 0
    }
    normalized_scan = {
        max(0, int(value or 0))
        for value in (verify_scan_episodes or set())
        if max(0, int(value or 0)) > 0
    }

    newly_detected = normalized_scan.difference(normalized_pre_attempt)
    verified_new_hits = normalized_target.intersection(newly_detected)
    present_hits = normalized_target.intersection(normalized_scan)

    scanned_dirs_value = max(0, int(scan_scanned_dirs or 0))
    scanned_entries_value = max(0, int(scan_scanned_entries or 0))
    failed_dirs_value = max(0, int(scan_failed_dirs or 0))
    truncated_flag = bool(scan_truncated)

    # 扫描可靠性分级：
    # 1) basic_reliable: 至少不是“完全没扫到目录且全是失败”。
    # 2) strict_reliable: 可用于“反证不存在”的严格判断（未截断且扫描无失败且有条目）。
    basic_reliable = not (scanned_dirs_value <= 0 and failed_dirs_value > 0)
    strict_reliable = bool(
        basic_reliable
        and scanned_entries_value > 0
        and failed_dirs_value <= 0
        and (not truncated_flag)
    )

    should_fail = False
    reason = ""
    if normalized_target:
        if verified_new_hits:
            reason = "verified_new_hits"
        elif present_hits:
            reason = "already_present_hits"
        elif basic_reliable and (not truncated_flag) and scanned_entries_value <= 0:
            should_fail = True
            reason = "empty_scan_miss"
        elif strict_reliable and normalized_scan:
            should_fail = True
            reason = "strict_scan_miss"
        elif (not basic_reliable) or truncated_flag:
            reason = "scan_not_reliable"
        else:
            reason = "episode_unrecognized"

    return {
        "should_fail": should_fail,
        "reason": reason,
        "verified_new_hits": sorted(verified_new_hits),
        "present_hits": sorted(present_hits),
        "newly_detected": sorted(newly_detected),
        "basic_reliable": basic_reliable,
        "strict_reliable": strict_reliable,
    }


def _candidate_episode_ledger_skip_reason(
    candidate: Dict[str, Any],
    episode_values: Set[int],
    ledger_rows: Dict[int, Dict[str, Any]],
) -> str:
    normalized_values = sorted({max(0, int(value or 0)) for value in (episode_values or set()) if max(0, int(value or 0)) > 0})
    if not normalized_values:
        return ""

    covered_rows: List[Dict[str, Any]] = []
    for episode_no in normalized_values:
        row = ledger_rows.get(episode_no)
        if not row:
            return ""
        if str(row.get("status", "active") or "active").strip().lower() != "active":
            return ""
        covered_rows.append(row)

    candidate_resolution = max(0, int((candidate or {}).get("resolution", 0) or 0))
    candidate_score = max(0, int((candidate or {}).get("score", 0) or 0))
    for row in covered_rows:
        row_resolution = max(0, int(row.get("best_resolution", 0) or 0))
        row_score = max(0, int(row.get("best_score", 0) or 0))
        if candidate_resolution > 0:
            if row_resolution <= 0 or candidate_resolution > row_resolution:
                return ""
            if candidate_resolution == row_resolution and candidate_score >= row_score + 4:
                return ""
        else:
            if candidate_score >= row_score + 8:
                return ""

    return (
        f"候选集数已被集数账本覆盖（{_format_episode_preview(set(normalized_values))}）且未达到更优质量，已跳过"
    )


def _build_subscription_episode_ledger_fingerprints(
    item: Dict[str, Any],
    candidate: Dict[str, Any],
    episode_values: Set[int],
    selected_ids: List[str],
) -> Tuple[str, str]:
    normalized_item = item if isinstance(item, dict) else {}
    normalized_candidate = candidate if isinstance(candidate, dict) else {}
    normalized_selected_ids = sorted({str(value or "").strip() for value in (selected_ids or []) if str(value or "").strip()})[:200]
    episode_marker = ",".join([str(value) for value in sorted({max(0, int(ep or 0)) for ep in (episode_values or set()) if max(0, int(ep or 0)) > 0})])

    link_type = resolve_resource_link_type(
        normalized_item.get("link_type", ""),
        str(normalized_item.get("link_url", "")).strip(),
    )
    link_url = _normalize_subscription_candidate_link(normalized_item.get("link_url", ""))
    source_parts = [
        link_type,
        link_url,
        "|".join(normalized_selected_ids),
    ]
    source_seed = "||".join(source_parts)
    source_fp = hashlib.sha1(source_seed.encode("utf-8")).hexdigest()

    content_parts = [
        source_fp,
        f"s:{max(0, int(normalized_candidate.get('season', 0) or 0))}",
        f"e:{max(0, int(normalized_candidate.get('episode', 0) or 0))}",
        f"r:{max(0, int(normalized_candidate.get('range_start', 0) or 0))}-{max(0, int(normalized_candidate.get('range_end', 0) or 0))}",
        f"res:{max(0, int(normalized_candidate.get('resolution', 0) or 0))}",
        f"score:{max(0, int(normalized_candidate.get('score', 0) or 0))}",
        f"episodes:{episode_marker}",
    ]
    content_seed = "||".join(content_parts)
    content_fp = hashlib.sha1(content_seed.encode("utf-8")).hexdigest()
    return source_fp, content_fp


def _format_candidate_episode_label(candidate: Dict[str, Any]) -> str:
    payload = candidate if isinstance(candidate, dict) else {}
    range_start = max(0, int(payload.get("range_start", 0) or 0))
    range_end = max(0, int(payload.get("range_end", 0) or 0))
    episode = max(0, int(payload.get("episode", 0) or 0))
    if range_start > 0 and range_end > 0:
        if range_end < range_start:
            range_start, range_end = range_end, range_start
        if range_start == range_end:
            return f"E{range_start}"
        return f"E{range_start}-E{range_end}"
    if episode > 0:
        return f"E{episode}"
    return "未知集数"


def _build_subscription_episode_bucket_key(episode_values: Set[int]) -> str:
    normalized = sorted({max(0, int(value or 0)) for value in (episode_values or set()) if max(0, int(value or 0)) > 0})
    if not normalized:
        return ""
    if len(normalized) == 1:
        return f"e:{normalized[0]}"
    start = normalized[0]
    end = normalized[-1]
    expected = list(range(start, end + 1))
    if normalized == expected:
        return f"r:{start}-{end}"
    return f"m:{','.join([str(value) for value in normalized[:24]])}"


def _build_subscription_share_file_quality_rank(task: Dict[str, Any], entry: Dict[str, Any]) -> Tuple[int, int, int, str]:
    entry_name = normalize_relative_path(str((entry or {}).get("name", "") or "").strip())
    pseudo_item = {
        "title": entry_name,
        "raw_text": entry_name,
        "quality": entry_name,
    }
    quality_bonus, resolution, _ = score_subscription_quality_preference(task, pseudo_item)
    size_value = max(0, int((entry or {}).get("size", 0) or 0))
    return (
        max(0, int(quality_bonus or 0)),
        max(0, int(resolution or 0)),
        size_value,
        entry_name.lower(),
    )


def _pick_best_tv_share_files_by_episode_bucket(
    task: Dict[str, Any],
    file_entries: List[Dict[str, Any]],
    missing_episodes: Set[int],
) -> Dict[str, Any]:
    target_missing = _clamp_episode_values(missing_episodes or set())
    picked_by_bucket: Dict[str, Dict[str, Any]] = {}
    duplicate_bucket_hits = 0

    for raw_entry in file_entries if isinstance(file_entries, list) else []:
        if not isinstance(raw_entry, dict):
            continue
        entry_id = str(raw_entry.get("id", "") or raw_entry.get("fid", "") or "").strip()
        entry_name = normalize_relative_path(str(raw_entry.get("name", "") or "").strip())
        if not entry_id or not entry_name:
            continue

        entry_episodes = _clamp_episode_values(
            {
                max(0, int(value or 0))
                for value in (raw_entry.get("episodes", []) if isinstance(raw_entry.get("episodes"), list) else [])
                if max(0, int(value or 0)) > 0
            }
        )
        if not entry_episodes:
            continue
        episode_hit = entry_episodes.intersection(target_missing) if target_missing else set(entry_episodes)
        if not episode_hit:
            continue

        bucket_key = _build_subscription_episode_bucket_key(entry_episodes) or f"id:{entry_id}"
        rank = _build_subscription_share_file_quality_rank(task, raw_entry)
        current = picked_by_bucket.get(bucket_key)
        if current:
            duplicate_bucket_hits += 1
            if rank <= current.get("rank", (0, 0, 0, "")):
                continue

        picked_by_bucket[bucket_key] = {
            "entry": {
                "id": entry_id,
                "name": entry_name,
                "is_dir": False,
                "parent_id": str(raw_entry.get("parent_id", "0") or "0").strip() or "0",
                "cid": "",
                "fid": str(raw_entry.get("fid", "") or entry_id).strip(),
                "fid_token": str(raw_entry.get("fid_token", "") or "").strip(),
            },
            "episodes": entry_episodes,
            "episode_hit": episode_hit,
            "rank": rank,
        }

    ordered_entries = sorted(
        picked_by_bucket.values(),
        key=lambda item: (
            min(item.get("episodes", {999999})) if item.get("episodes") else 999999,
            normalize_relative_path(str((item.get("entry", {}) or {}).get("name", "") or "")).lower(),
        ),
    )
    covered_missing: Set[int] = set()
    selected_entries: List[Dict[str, Any]] = []
    for payload in ordered_entries:
        entry = payload.get("entry", {}) if isinstance(payload.get("entry"), dict) else {}
        if not entry:
            continue
        selected_entries.append(entry)
        covered_missing.update(payload.get("episode_hit", set()))

    return {
        "selected_entries": selected_entries,
        "selected_ids": [str(entry.get("id", "")).strip() for entry in selected_entries if str(entry.get("id", "")).strip()],
        "covered_missing": covered_missing,
        "bucket_count": len(selected_entries),
        "duplicate_bucket_hits": duplicate_bucket_hits,
    }


def _scan_115_existing_tv_episodes(
    cookie: str,
    root_folder_id: str,
    task: Dict[str, Any],
    max_depth: int = 3,
    max_dirs: int = 120,
    max_entries: int = 3000,
) -> Dict[str, Any]:
    normalized_cookie = str(cookie or "").strip()
    if not normalized_cookie:
        raise RuntimeError("115 Cookie 未配置")

    start_cid = str(root_folder_id or "0").strip() or "0"
    queue: List[Tuple[str, int, str]] = [(start_cid, 0, "")]
    visited: Set[str] = set()
    episodes: Set[int] = set()
    scanned_dirs = 0
    scanned_entries = 0
    failed_dirs = 0

    while queue and scanned_dirs < max_dirs and scanned_entries < max_entries:
        cid, depth, parent_path = queue.pop(0)
        if cid in visited:
            continue
        visited.add(cid)
        try:
            entries = list_115_entries(normalized_cookie, cid)
        except Exception:
            failed_dirs += 1
            continue

        scanned_dirs += 1
        for entry in entries:
            if scanned_entries >= max_entries:
                break
            scanned_entries += 1
            name = str(entry.get("name", "") or "").strip()
            if not name:
                continue
            rel_name = normalize_relative_path(name)
            is_dir = bool(entry.get("is_dir"))
            if is_dir and depth < max_depth:
                child_cid = str(entry.get("id", "") or entry.get("cid", "") or "").strip()
                if child_cid and child_cid not in visited:
                    child_path = normalize_relative_path(join_relative_path(parent_path, rel_name))
                    queue.append((child_cid, depth + 1, child_path or rel_name))
            if is_dir:
                continue
            parsed_episodes = _extract_task_episodes_from_file_entry(task, rel_name or name, parent_path)
            if parsed_episodes:
                episodes.update(parsed_episodes)

    sorted_episodes = sorted(episodes)
    return {
        "episodes": sorted_episodes,
        "max_episode": sorted_episodes[-1] if sorted_episodes else 0,
        "scanned_dirs": scanned_dirs,
        "scanned_entries": scanned_entries,
        "failed_dirs": failed_dirs,
        "truncated": bool(queue) or scanned_dirs >= max_dirs or scanned_entries >= max_entries,
    }


def _scan_quark_existing_tv_episodes(
    cookie: str,
    root_folder_id: str,
    task: Dict[str, Any],
    max_depth: int = 3,
    max_dirs: int = 120,
    max_entries: int = 3000,
) -> Dict[str, Any]:
    normalized_cookie = str(cookie or "").strip()
    if not normalized_cookie:
        raise RuntimeError("Quark Cookie 未配置")

    start_cid = str(root_folder_id or "0").strip() or "0"
    queue: List[Tuple[str, int, str]] = [(start_cid, 0, "")]
    visited: Set[str] = set()
    episodes: Set[int] = set()
    scanned_dirs = 0
    scanned_entries = 0
    failed_dirs = 0

    while queue and scanned_dirs < max_dirs and scanned_entries < max_entries:
        cid, depth, parent_path = queue.pop(0)
        if cid in visited:
            continue
        visited.add(cid)
        try:
            entries = list_quark_entries(normalized_cookie, cid)
        except Exception:
            failed_dirs += 1
            continue

        scanned_dirs += 1
        for entry in entries:
            if scanned_entries >= max_entries:
                break
            scanned_entries += 1
            name = str(entry.get("name", "") or "").strip()
            if not name:
                continue
            rel_name = normalize_relative_path(name)
            is_dir = bool(entry.get("is_dir"))
            if is_dir and depth < max_depth:
                child_cid = str(entry.get("id", "") or entry.get("cid", "") or "").strip()
                if child_cid and child_cid not in visited:
                    child_path = normalize_relative_path(join_relative_path(parent_path, rel_name))
                    queue.append((child_cid, depth + 1, child_path or rel_name))
            if is_dir:
                continue
            parsed_episodes = _extract_task_episodes_from_file_entry(task, rel_name or name, parent_path)
            if parsed_episodes:
                episodes.update(parsed_episodes)

    sorted_episodes = sorted(episodes)
    return {
        "episodes": sorted_episodes,
        "max_episode": sorted_episodes[-1] if sorted_episodes else 0,
        "scanned_dirs": scanned_dirs,
        "scanned_entries": scanned_entries,
        "failed_dirs": failed_dirs,
        "truncated": bool(queue) or scanned_dirs >= max_dirs or scanned_entries >= max_entries,
    }


def _format_episode_preview(episodes: Set[int], max_items: int = 8) -> str:
    ordered = sorted(max(0, int(item or 0)) for item in episodes if int(item or 0) > 0)
    if not ordered:
        return "--"
    if len(ordered) <= max_items:
        return "、".join([f"E{episode}" for episode in ordered])
    head = "、".join([f"E{episode}" for episode in ordered[:3]])
    tail = "、".join([f"E{episode}" for episode in ordered[-2:]])
    return f"{head} ... {tail}"


def _build_subscription_selected_file_samples(
    file_entries: List[Dict[str, Any]],
    selected_ids: List[str],
    target_episodes: Set[int],
    sample_limit: int = 6,
) -> List[str]:
    normalized_selected_ids = [str(value or "").strip() for value in (selected_ids or []) if str(value or "").strip()]
    if not normalized_selected_ids:
        return []
    target = _clamp_episode_values(target_episodes or set())
    entry_by_id: Dict[str, Dict[str, Any]] = {}
    for raw_entry in file_entries if isinstance(file_entries, list) else []:
        if not isinstance(raw_entry, dict):
            continue
        entry_id = str(raw_entry.get("id", "") or raw_entry.get("fid", "") or "").strip()
        if not entry_id:
            continue
        entry_by_id[entry_id] = raw_entry

    samples: List[str] = []
    for selected_id in normalized_selected_ids:
        entry = entry_by_id.get(selected_id, {})
        if not isinstance(entry, dict):
            continue
        entry_name = normalize_relative_path(str(entry.get("name", "") or "").strip())
        if not entry_name:
            continue
        entry_episodes = _clamp_episode_values(
            {
                max(0, int(value or 0))
                for value in (entry.get("episodes", []) if isinstance(entry.get("episodes"), list) else [])
                if max(0, int(value or 0)) > 0
            }
        )
        episode_hit = entry_episodes.intersection(target) if target else set(entry_episodes)
        episode_label = _format_episode_preview(episode_hit or entry_episodes, max_items=4) if (episode_hit or entry_episodes) else "--"
        samples.append(f"{episode_label} <- {entry_name[:96]}")
        if len(samples) >= max(1, int(sample_limit or 6)):
            break
    return samples


def _prioritize_tv_candidates_by_missing_episodes(
    candidates: List[Dict[str, Any]],
    existing_episodes: Set[int],
    baseline_last_episode: int,
    prefer_backfill: bool,
    episode_upper_bound: int = 0,
) -> List[Dict[str, Any]]:
    normalized_existing = _clamp_episode_values(existing_episodes, episode_upper_bound=episode_upper_bound)
    if not normalized_existing:
        if episode_upper_bound > 0:
            # 首轮目录为空时，优先尝试“在单季目标集数范围内覆盖更多集数”的候选。
            prioritized = list(candidates)
            prioritized.sort(
                key=lambda item: (
                    len(_candidate_episode_values(item, episode_upper_bound=episode_upper_bound)),
                    _candidate_anchor_episode(item, episode_upper_bound=episode_upper_bound),
                    int(item.get("score", 0) or 0),
                    get_resource_item_sort_key(item.get("item", {})),
                ),
                reverse=True,
            )
            return prioritized
        return list(candidates)

    without_episode: List[Dict[str, Any]] = []
    backfill_candidates: List[Dict[str, Any]] = []
    fresh_candidates: List[Dict[str, Any]] = []
    existing_candidates: List[Dict[str, Any]] = []
    for candidate in candidates:
        episode_values = _candidate_episode_values(candidate, episode_upper_bound=episode_upper_bound)
        if not episode_values:
            without_episode.append(candidate)
            continue
        anchor_episode = max(episode_values)
        has_missing_coverage = any(episode_no not in normalized_existing for episode_no in episode_values)
        if not has_missing_coverage:
            existing_candidates.append(candidate)
            continue
        if baseline_last_episode > 0 and anchor_episode <= baseline_last_episode:
            backfill_candidates.append(candidate)
            continue
        fresh_candidates.append(candidate)

    backfill_candidates.sort(
        key=lambda item: (
            _candidate_anchor_episode(item, episode_upper_bound=episode_upper_bound),
            -int(item.get("score", 0) or 0),
            get_resource_item_sort_key(item.get("item", {})),
        )
    )
    fresh_candidates.sort(
        key=lambda item: (
            _candidate_anchor_episode(item, episode_upper_bound=episode_upper_bound),
            int(item.get("score", 0) or 0),
            get_resource_item_sort_key(item.get("item", {})),
        ),
        reverse=True,
    )
    existing_candidates.sort(
        key=lambda item: (
            _candidate_anchor_episode(item, episode_upper_bound=episode_upper_bound),
            int(item.get("score", 0) or 0),
            get_resource_item_sort_key(item.get("item", {})),
        ),
        reverse=True,
    )

    prioritized_with_episode = (
        (backfill_candidates + fresh_candidates)
        if prefer_backfill
        else (fresh_candidates + backfill_candidates)
    )
    return prioritized_with_episode + without_episode + existing_candidates


def _prioritize_quark_tv_candidates_for_precise_scan(
    candidates: List[Dict[str, Any]],
    existing_episodes: Set[int],
    episode_upper_bound: int = 0,
) -> List[Dict[str, Any]]:
    normalized_existing = _clamp_episode_values(existing_episodes, episode_upper_bound=episode_upper_bound)
    prioritized = list(candidates or [])
    prioritized.sort(
        key=lambda item: (
            int(item.get("title_match_score", 0) or 0),
            len(_candidate_missing_episode_values(item, normalized_existing, episode_upper_bound=episode_upper_bound)),
            int(item.get("resolution", 0) or 0),
            int(item.get("score", 0) or 0),
            get_resource_item_sort_key(item.get("item", {})),
        ),
        reverse=True,
    )
    return prioritized


def _compute_quark_tv_title_missing_targets(
    existing_episodes: Set[int],
    baseline_last_episode: int,
    episode_upper_bound: int = 0,
) -> Set[int]:
    normalized_existing = _clamp_episode_values(existing_episodes or set(), episode_upper_bound=episode_upper_bound)
    upper_bound = max(0, int(episode_upper_bound or 0))
    if upper_bound > 0:
        return {episode_no for episode_no in range(1, upper_bound + 1) if episode_no not in normalized_existing}
    progress_upper = max(max(normalized_existing) if normalized_existing else 0, max(0, int(baseline_last_episode or 0)))
    if progress_upper <= 0:
        return set()
    return {episode_no for episode_no in range(1, progress_upper + 1) if episode_no not in normalized_existing}


def _filter_quark_tv_candidates_by_title_missing_episodes(
    candidates: List[Dict[str, Any]],
    missing_targets: Set[int],
    episode_upper_bound: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    normalized_missing = _clamp_episode_values(missing_targets or set(), episode_upper_bound=episode_upper_bound)
    if not normalized_missing:
        return list(candidates or []), 0
    kept: List[Dict[str, Any]] = []
    dropped = 0
    for candidate in candidates or []:
        episode_values = _candidate_episode_values(candidate, episode_upper_bound=episode_upper_bound)
        if not episode_values:
            # 标题集数无法识别时保留到精细扫描，避免漏掉命名不规范但实际可用的资源。
            kept.append(candidate)
            continue
        if episode_values.intersection(normalized_missing):
            kept.append(candidate)
            continue
        dropped += 1
    return kept, dropped


def _prune_tv_candidates_without_new_episodes(
    candidates: List[Dict[str, Any]],
    existing_episodes: Set[int],
    episode_upper_bound: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    normalized_existing = _clamp_episode_values(existing_episodes, episode_upper_bound=episode_upper_bound)
    if not normalized_existing:
        return list(candidates or []), 0
    kept: List[Dict[str, Any]] = []
    pruned = 0
    for candidate in candidates or []:
        episode_values = _candidate_episode_values(candidate, episode_upper_bound=episode_upper_bound)
        has_range_hint = (
            max(0, int((candidate or {}).get("range_start", 0) or 0)) > 0
            and max(0, int((candidate or {}).get("range_end", 0) or 0)) > 0
        )
        if has_range_hint and episode_values and episode_values.issubset(normalized_existing):
            pruned += 1
            continue
        kept.append(candidate)
    return kept, pruned


def _normalize_subscription_share_dir_match_key(name: str, drop_digits: bool = False) -> str:
    normalized = normalize_relative_path(name)
    if not normalized:
        return ""
    text = unicodedata.normalize("NFKC", normalized).lower()
    text = text.replace("｜", "|")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[。．…·•~～\-_+=]+$", "", text)
    text = re.sub(r"[^0-9a-z\u4e00-\u9fff{}#:+-]+", "", text)
    if drop_digits:
        text = re.sub(r"\d+", "", text)
    return text


def _extract_subscription_tmdbid_token(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    matched = re.search(r"tmdbid[-_:\s]*([0-9]{3,})", normalized, re.IGNORECASE)
    return str(matched.group(1) if matched else "").strip()


def _pick_unique_subscription_share_entry(candidates: List[Tuple[int, Dict[str, Any]]]) -> Dict[str, Any]:
    if not candidates:
        return {}
    ranked = sorted(candidates, key=lambda item: int(item[0] or 0), reverse=True)
    if len(ranked) > 1 and int(ranked[0][0] or 0) == int(ranked[1][0] or 0):
        return {}
    return ranked[0][1] if isinstance(ranked[0][1], dict) else {}


def _sample_subscription_share_dir_names(entries: List[Dict[str, Any]], limit: int = 6) -> List[str]:
    samples: List[str] = []
    for entry in entries if isinstance(entries, list) else []:
        if not bool(entry.get("is_dir")):
            continue
        name = normalize_relative_path(str(entry.get("name", "") or "").strip())
        if not name or name in samples:
            continue
        samples.append(name)
        if len(samples) >= max(1, int(limit or 6)):
            break
    return samples


def _collect_subscription_task_share_dir_name_candidates(task: Dict[str, Any]) -> List[str]:
    candidates: List[str] = []
    for value in (
        task.get("title", ""),
        task.get("tmdb_title", ""),
        task.get("tmdb_original_title", ""),
    ):
        text = normalize_relative_path(str(value or "").strip())
        if text:
            candidates.append(text)
    for field in ("aliases", "tmdb_aliases"):
        raw_values = task.get(field, [])
        if not isinstance(raw_values, list):
            continue
        for raw in raw_values:
            text = normalize_relative_path(str(raw or "").strip())
            if text:
                candidates.append(text)
    return unique_preserve_order(candidates)


def _score_subscription_share_dir_for_task(
    entry_name: str,
    task_name_candidates: List[str],
    task_tmdbid: str = "",
) -> int:
    normalized_entry = normalize_relative_path(entry_name)
    if not normalized_entry:
        return 0
    best_score = 0
    for expected_name in task_name_candidates if isinstance(task_name_candidates, list) else []:
        score = _score_subscription_share_dir_candidate_name(
            normalized_entry,
            expected_name,
            expected_tmdbid=task_tmdbid,
        )
        if score > best_score:
            best_score = score
    entry_key = _normalize_subscription_share_dir_match_key(normalized_entry)
    if task_tmdbid and entry_key and task_tmdbid in entry_key:
        best_score = max(best_score, 260)
    return best_score


async def _refine_subscription_share_selection_for_task(
    cookie: str,
    item: Dict[str, Any],
    task: Dict[str, Any],
    selection: Dict[str, Any],
    per_request_timeout: int = 25,
    max_depth: int = 3,
    max_dirs: int = 140,
    force_refresh: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    stats: Dict[str, Any] = {
        "reason": "",
        "scanned_dirs": 0,
        "candidate_count": 0,
        "best_score": 0,
        "ambiguous_count": 0,
        "start_child_dirs": 0,
        "current_score": 0,
        "from_path": "",
        "to_path": "",
        "candidate_samples": [],
    }
    normalized_cookie = str(cookie or "").strip()
    share_url = str(item.get("link_url", "") or "").strip()
    raw_text = str(item.get("raw_text", "") or "")
    if not normalized_cookie or not share_url:
        stats["reason"] = "missing_context"
        return {}, stats

    base_selection = normalize_share_selection_meta(selection or {})
    selected_entries = (
        base_selection.get("selected_entries", [])
        if isinstance(base_selection.get("selected_entries"), list)
        else []
    )
    start_entry = selected_entries[0] if selected_entries else {}
    if not start_entry or not bool(start_entry.get("is_dir")):
        stats["reason"] = "selection_invalid"
        return {}, stats

    start_cid = str(start_entry.get("cid", "") or start_entry.get("id", "") or "").strip()
    start_path = normalize_relative_path(str(start_entry.get("name", "") or "").strip())
    if not start_cid or not start_path:
        stats["reason"] = "selection_invalid"
        return {}, stats
    task_anchor_cid = _normalize_subscription_share_subdir_cid(task.get("share_subdir_cid", ""))
    if task_anchor_cid and task_anchor_cid == start_cid:
        stats["reason"] = "cid_anchor_locked"
        stats["current_score"] = 999
        return base_selection, stats
    stats["from_path"] = start_path

    task_tmdbid = str(max(0, int(task.get("tmdb_id", 0) or 0)))
    if task_tmdbid == "0":
        task_tmdbid = ""
    task_name_candidates = _collect_subscription_task_share_dir_name_candidates(task)
    if not task_name_candidates and not task_tmdbid:
        stats["reason"] = "task_clues_empty"
        return {}, stats

    current_leaf_name = start_path.split("/")[-1] if start_path else ""
    current_score = _score_subscription_share_dir_for_task(
        current_leaf_name,
        task_name_candidates,
        task_tmdbid=task_tmdbid,
    )
    stats["current_score"] = current_score
    if current_score >= 170:
        stats["reason"] = "current_match_strong"
        return base_selection, stats

    item_extra = item.get("extra") if isinstance(item.get("extra"), dict) else safe_json_loads(item.get("extra_json"), {})
    receive_code = (
        normalize_receive_code(item.get("receive_code", ""))
        or normalize_receive_code((item_extra or {}).get("receive_code", ""))
    )
    timeout_seconds = max(10, int(per_request_timeout or 25))
    queue: List[Tuple[str, int, str]] = [(start_cid, 0, start_path)]
    visited: Set[str] = set()
    scored_candidates: List[Tuple[int, Dict[str, Any]]] = []

    while queue and int(stats.get("scanned_dirs", 0) or 0) < max(20, int(max_dirs or 140)):
        cid, depth, parent_path = queue.pop(0)
        normalized_cid = str(cid or "").strip()
        if not normalized_cid or normalized_cid in visited:
            continue
        visited.add(normalized_cid)
        try:
            branch = await asyncio.wait_for(
                _fetch_subscription_share_entries(
                    normalized_cookie,
                    share_url,
                    raw_text,
                    normalized_cid,
                    receive_code,
                    force_refresh,
                ),
                timeout=timeout_seconds,
            )
        except Exception:
            continue

        stats["scanned_dirs"] = int(stats.get("scanned_dirs", 0) or 0) + 1
        entries = branch.get("entries", []) if isinstance(branch.get("entries"), list) else []
        if depth == 0:
            stats["start_child_dirs"] = sum(1 for entry in entries if bool(entry.get("is_dir")))
        for entry in entries:
            if not bool(entry.get("is_dir")):
                continue
            entry_name = normalize_relative_path(str(entry.get("name", "") or "").strip())
            if not entry_name:
                continue
            full_path = normalize_relative_path(join_relative_path(parent_path, entry_name))
            score = _score_subscription_share_dir_for_task(
                entry_name,
                task_name_candidates,
                task_tmdbid=task_tmdbid,
            )
            if score > 0:
                candidate = {
                    "id": str(entry.get("id", "") or entry.get("cid", "") or "").strip(),
                    "cid": str(entry.get("cid", "") or entry.get("id", "") or "").strip(),
                    "parent_id": str(entry.get("parent_id", "0") or "0").strip() or "0",
                    "name": full_path,
                    "is_dir": True,
                }
                if candidate["id"] and candidate["cid"] and candidate["name"]:
                    scored_candidates.append((score, candidate))
            if depth < max(1, int(max_depth or 3)):
                child_cid = str(entry.get("cid", "") or entry.get("id", "") or "").strip()
                if child_cid and child_cid not in visited:
                    queue.append((child_cid, depth + 1, full_path))

    stats["candidate_count"] = len(scored_candidates)
    if not scored_candidates:
        stats["reason"] = "not_found"
        return {}, stats

    scored_candidates.sort(key=lambda item: (int(item[0] or 0), len(str(item[1].get("name", "")))), reverse=True)
    best_score = int(scored_candidates[0][0] or 0)
    stats["best_score"] = best_score
    best_candidates = [item[1] for item in scored_candidates if int(item[0] or 0) == best_score]
    stats["ambiguous_count"] = len(best_candidates)
    if len(best_candidates) != 1:
        stats["reason"] = "ambiguous"
        stats["candidate_samples"] = [
            str(item.get("name", "") or "").strip()
            for item in best_candidates[:5]
            if str(item.get("name", "") or "").strip()
        ]
        return {}, stats

    best_candidate = best_candidates[0]
    if best_score < 130:
        stats["reason"] = "weak_match"
        stats["candidate_samples"] = [str(best_candidate.get("name", "") or "").strip()]
        return {}, stats
    if str(best_candidate.get("id", "") or "").strip() == str(start_entry.get("id", "") or "").strip():
        stats["reason"] = "same_as_current"
        return base_selection, stats

    refined_selection = normalize_share_selection_meta(
        {
            "selected_ids": [str(best_candidate.get("id", "") or "").strip()],
            "selected_entries": [best_candidate],
            "refresh_target_type": "folder",
            "share_root_title": str(base_selection.get("share_root_title", "") or "").strip(),
            "auto_sharetitle": str(best_candidate.get("name", "") or "").strip(),
        }
    )
    if not (
        refined_selection.get("selected_ids", [])
        if isinstance(refined_selection.get("selected_ids"), list)
        else []
    ):
        stats["reason"] = "refine_selection_empty"
        return {}, stats
    stats["reason"] = "ok_refined"
    stats["to_path"] = str(best_candidate.get("name", "") or "").strip()
    return refined_selection, stats


def _score_subscription_share_dir_candidate_name(
    entry_name: str,
    expected_name: str,
    expected_tmdbid: str = "",
) -> int:
    normalized_entry_name = normalize_relative_path(entry_name)
    normalized_expected_name = normalize_relative_path(expected_name)
    if not normalized_entry_name:
        return 0
    if normalized_entry_name == normalized_expected_name:
        return 200
    entry_key = _normalize_subscription_share_dir_match_key(normalized_entry_name)
    expected_key = _normalize_subscription_share_dir_match_key(normalized_expected_name)
    if not entry_key or not expected_key:
        return 0
    if entry_key == expected_key:
        return 180
    score = 0
    if expected_tmdbid and expected_tmdbid in entry_key:
        score = max(score, 170)
    expected_key_no_digits = _normalize_subscription_share_dir_match_key(normalized_expected_name, drop_digits=True)
    entry_key_no_digits = _normalize_subscription_share_dir_match_key(normalized_entry_name, drop_digits=True)
    if expected_key_no_digits and entry_key_no_digits and expected_key_no_digits == entry_key_no_digits and len(expected_key_no_digits) >= 6:
        score = max(score, 150)
    short_len = min(len(expected_key), len(entry_key))
    if short_len >= 6 and (expected_key in entry_key or entry_key in expected_key):
        score = max(score, 120 - abs(len(expected_key) - len(entry_key)))
    return max(0, int(score))


async def _find_subscription_share_dir_by_leaf_fallback(
    cookie: str,
    share_url: str,
    raw_text: str,
    receive_code: str,
    expected_leaf_name: str,
    expected_tmdbid: str = "",
    start_cid: str = "0",
    start_parent_path: str = "",
    per_request_timeout: int = 25,
    max_depth: int = 4,
    max_dirs: int = 120,
    force_refresh: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    stats: Dict[str, Any] = {
        "reason": "not_found",
        "scanned_dirs": 0,
        "candidate_count": 0,
        "best_score": 0,
        "ambiguous_count": 0,
    }
    normalized_cookie = str(cookie or "").strip()
    normalized_share_url = str(share_url or "").strip()
    leaf_name = normalize_relative_path(expected_leaf_name)
    if (not normalized_cookie) or (not normalized_share_url) or (not leaf_name):
        stats["reason"] = "invalid_args"
        return {}, stats

    timeout_seconds = max(10, int(per_request_timeout or 25))
    queue: List[Tuple[str, int, str]] = [(
        str(start_cid or "0").strip() or "0",
        0,
        normalize_relative_path(start_parent_path),
    )]
    visited: Set[str] = set()
    scored_candidates: List[Tuple[int, Dict[str, Any]]] = []

    while queue and int(stats.get("scanned_dirs", 0) or 0) < max(10, int(max_dirs or 120)):
        cid, depth, parent_path = queue.pop(0)
        normalized_cid = str(cid or "0").strip() or "0"
        if normalized_cid in visited:
            continue
        visited.add(normalized_cid)
        try:
            branch = await asyncio.wait_for(
                _fetch_subscription_share_entries(
                    normalized_cookie,
                    normalized_share_url,
                    raw_text,
                    normalized_cid,
                    receive_code,
                    force_refresh,
                ),
                timeout=timeout_seconds,
            )
        except Exception:
            continue

        stats["scanned_dirs"] = int(stats.get("scanned_dirs", 0) or 0) + 1
        entries = branch.get("entries", []) if isinstance(branch.get("entries"), list) else []
        for entry in entries:
            if not bool(entry.get("is_dir")):
                continue
            entry_name = normalize_relative_path(str(entry.get("name", "") or "").strip())
            if not entry_name:
                continue
            resolved_path = normalize_relative_path(f"{parent_path}/{entry_name}" if parent_path else entry_name)
            score = _score_subscription_share_dir_candidate_name(
                entry_name=entry_name,
                expected_name=leaf_name,
                expected_tmdbid=expected_tmdbid,
            )
            if score > 0:
                candidate = {
                    "id": str(entry.get("id", "") or entry.get("cid", "") or "").strip(),
                    "cid": str(entry.get("cid", "") or entry.get("id", "") or "").strip(),
                    "parent_id": str(entry.get("parent_id", "0") or "0").strip() or "0",
                    "name": entry_name,
                    "resolved_path": resolved_path,
                }
                if candidate["id"] and candidate["cid"] and candidate["resolved_path"]:
                    scored_candidates.append((score, candidate))
            if depth < max(1, int(max_depth or 4)):
                next_cid = str(entry.get("cid", "") or entry.get("id", "") or "").strip()
                if next_cid and next_cid not in visited:
                    queue.append((next_cid, depth + 1, resolved_path))

    stats["candidate_count"] = len(scored_candidates)
    if not scored_candidates:
        stats["reason"] = "not_found"
        return {}, stats

    scored_candidates.sort(key=lambda item: int(item[0] or 0), reverse=True)
    best_score = int(scored_candidates[0][0] or 0)
    best_candidates = [item[1] for item in scored_candidates if int(item[0] or 0) == best_score]
    stats["best_score"] = best_score
    stats["ambiguous_count"] = len(best_candidates)
    if len(best_candidates) != 1:
        stats["reason"] = "ambiguous"
        stats["candidate_samples"] = [
            str(item.get("resolved_path", "") or "").strip()
            for item in best_candidates[:5]
            if str(item.get("resolved_path", "") or "").strip()
        ]
        return {}, stats
    stats["reason"] = "ok"
    return best_candidates[0], stats


def _match_subscription_share_dir_entry(entries: List[Dict[str, Any]], expected_name: str) -> Dict[str, Any]:
    target_name = normalize_relative_path(expected_name)
    if not target_name:
        return {}
    target_lower = target_name.lower()
    target_key = _normalize_subscription_share_dir_match_key(target_name)
    target_key_no_digits = _normalize_subscription_share_dir_match_key(target_name, drop_digits=True)
    target_tmdbid = _extract_subscription_tmdbid_token(target_name)
    fallback: Dict[str, Any] = {}
    tmdb_hits: List[Tuple[int, Dict[str, Any]]] = []
    no_digit_hits: List[Tuple[int, Dict[str, Any]]] = []
    contains_hits: List[Tuple[int, Dict[str, Any]]] = []
    for entry in entries if isinstance(entries, list) else []:
        if not bool(entry.get("is_dir")):
            continue
        entry_name = normalize_relative_path(str(entry.get("name", "") or "").strip())
        if not entry_name:
            continue
        if entry_name == target_name:
            return entry
        if (not fallback) and entry_name.lower() == target_lower:
            fallback = entry
        entry_key = _normalize_subscription_share_dir_match_key(entry_name)
        if target_key and entry_key:
            if entry_key == target_key:
                return entry
            short_len = min(len(target_key), len(entry_key))
            if short_len >= 6 and (target_key in entry_key or entry_key in target_key):
                contains_hits.append((short_len * 10 - abs(len(target_key) - len(entry_key)), entry))
        if target_tmdbid and entry_key:
            if target_tmdbid in entry_key:
                tmdb_hits.append((len(entry_key), entry))
        if target_key_no_digits:
            entry_key_no_digits = _normalize_subscription_share_dir_match_key(entry_name, drop_digits=True)
            if entry_key_no_digits and entry_key_no_digits == target_key_no_digits and len(entry_key_no_digits) >= 6:
                no_digit_hits.append((len(entry_key_no_digits), entry))

    unique_tmdb = _pick_unique_subscription_share_entry(tmdb_hits)
    if unique_tmdb:
        return unique_tmdb
    unique_no_digits = _pick_unique_subscription_share_entry(no_digit_hits)
    if unique_no_digits:
        return unique_no_digits
    unique_contains = _pick_unique_subscription_share_entry(contains_hits)
    if unique_contains:
        return unique_contains
    return fallback


def _normalize_subscription_share_subdir_parts(share_subdir: str, share_root_title: str = "") -> List[str]:
    requested_parts = [part for part in normalize_relative_path(share_subdir).split("/") if part]
    root_parts = [part for part in normalize_relative_path(share_root_title).split("/") if part]
    if root_parts and len(requested_parts) >= len(root_parts):
        if [part.lower() for part in requested_parts[: len(root_parts)]] == [part.lower() for part in root_parts]:
            requested_parts = requested_parts[len(root_parts) :]
    return requested_parts


def _normalize_subscription_share_subdir_cid(value: Any) -> str:
    return normalize_115_cid(value)


def _format_subscription_share_scope_label(share_subdir: str, share_subdir_cid: str = "") -> str:
    normalized_subdir = normalize_relative_path(share_subdir)
    normalized_cid = _normalize_subscription_share_subdir_cid(share_subdir_cid)
    if normalized_subdir and normalized_cid:
        return f"{normalized_subdir} [CID:{normalized_cid}]"
    if normalized_subdir:
        return normalized_subdir
    if normalized_cid:
        return f"CID:{normalized_cid}"
    return "--"


async def _build_subscription_share_subdir_selection(
    cookie: str,
    item: Dict[str, Any],
    share_subdir: str,
    share_subdir_cid: str = "",
    per_request_timeout: int = 25,
    force_refresh: bool = False,
    allow_fallback: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    normalized_cookie = str(cookie or "").strip()
    share_url = str(item.get("link_url", "") or "").strip()
    raw_text = str(item.get("raw_text", "") or "")
    requested_subdir = normalize_relative_path(share_subdir)
    requested_subdir_cid = _normalize_subscription_share_subdir_cid(share_subdir_cid)
    stats: Dict[str, Any] = {
        "reason": "",
        "requested_subdir": requested_subdir,
        "requested_subdir_cid": requested_subdir_cid,
        "share_root_title": "",
        "resolved_subdir": "",
        "resolved_subdir_cid": "",
        "scanned_dirs": 0,
        "failed_segment": "",
        "matched_depth": 0,
    }
    if not requested_subdir and not requested_subdir_cid:
        stats["reason"] = "share_subdir_empty"
        return {}, stats
    if not normalized_cookie:
        stats["reason"] = "cookie_missing"
        return {}, stats
    if not share_url:
        stats["reason"] = "share_url_missing"
        return {}, stats

    item_extra = item.get("extra") if isinstance(item.get("extra"), dict) else safe_json_loads(item.get("extra_json"), {})
    receive_code = (
        normalize_receive_code(item.get("receive_code", ""))
        or normalize_receive_code((item_extra or {}).get("receive_code", ""))
    )
    request_timeout = max(10, int(per_request_timeout or 25))

    if requested_subdir_cid:
        anchor_branch: Dict[str, Any] = {}
        anchor_error = ""
        anchor_attempts = 0
        max_anchor_retries = 2
        for attempt in range(0, max_anchor_retries + 1):
            anchor_attempts = attempt + 1
            try:
                anchor_branch = await asyncio.wait_for(
                    _fetch_subscription_share_entries(
                        normalized_cookie,
                        share_url,
                        raw_text,
                        requested_subdir_cid,
                        receive_code,
                        force_refresh,
                    ),
                    timeout=request_timeout,
                )
                anchor_error = ""
                break
            except Exception as exc:
                anchor_error = str(exc or "").strip() or exc.__class__.__name__
                if attempt >= max_anchor_retries:
                    stats["anchor_error"] = anchor_error[:180]
                    stats["anchor_retry_attempts"] = anchor_attempts
                    break
                await asyncio.sleep(0.6 * (attempt + 1))

        if anchor_branch:
            stats["scanned_dirs"] = int(stats.get("scanned_dirs", 0) or 0) + 1
            share_root_title = normalize_relative_path(str(anchor_branch.get("share_title", "") or ""))
            stats["share_root_title"] = share_root_title
            resolved_subdir = requested_subdir or normalize_relative_path(f"cid-{requested_subdir_cid}")
            stats["resolved_subdir"] = resolved_subdir
            stats["resolved_subdir_cid"] = requested_subdir_cid
            stats["matched_depth"] = len([part for part in resolved_subdir.split("/") if part]) if resolved_subdir else 0
            stats["reason"] = "ok_cid_anchor"
            selection = normalize_share_selection_meta(
                {
                    "selected_ids": [requested_subdir_cid],
                    "selected_entries": [
                        {
                            "id": requested_subdir_cid,
                            "name": resolved_subdir,
                            "is_dir": True,
                            "parent_id": "0",
                            "cid": requested_subdir_cid,
                            "fid": "",
                        }
                    ],
                    "refresh_target_type": "folder",
                    "share_root_title": share_root_title,
                    "auto_sharetitle": resolved_subdir,
                }
            )
            if not (selection.get("selected_ids", []) if isinstance(selection.get("selected_ids"), list) else []):
                stats["reason"] = "subdir_selection_empty"
                return {}, stats
            return selection, stats

        if not requested_subdir:
            stats["reason"] = "share_anchor_unreachable"
            return {}, stats

    root_branch: Dict[str, Any] = {}
    root_error = ""
    root_attempts = 0
    max_root_retries = 2
    for attempt in range(0, max_root_retries + 1):
        root_attempts = attempt + 1
        try:
            root_branch = await asyncio.wait_for(
                _fetch_subscription_share_entries(
                    normalized_cookie,
                    share_url,
                    raw_text,
                    "0",
                    receive_code,
                    force_refresh,
                ),
                timeout=request_timeout,
            )
            root_error = ""
            break
        except Exception as exc:
            root_error = str(exc or "").strip() or exc.__class__.__name__
            if attempt >= max_root_retries:
                stats["reason"] = "share_root_unreachable"
                stats["root_error"] = root_error[:180]
                stats["root_retry_attempts"] = root_attempts
                return {}, stats
            await asyncio.sleep(0.6 * (attempt + 1))
    stats["scanned_dirs"] = 1
    share_root_title = normalize_relative_path(str(root_branch.get("share_title", "") or ""))
    stats["share_root_title"] = share_root_title

    requested_parts_full = [part for part in requested_subdir.split("/") if part]
    path_parts = _normalize_subscription_share_subdir_parts(requested_subdir, share_root_title)
    if not path_parts:
        stats["reason"] = "target_is_share_root"
        return {}, stats

    current_entries = root_branch.get("entries", []) if isinstance(root_branch.get("entries"), list) else []
    current_cid = "0"
    matched_entry: Dict[str, Any] = {}
    matched_parts: List[str] = []
    fallback_used = False
    root_title_stripped = bool(requested_parts_full and len(path_parts) < len(requested_parts_full))
    if root_title_stripped and share_root_title:
        root_wrapper_entry = _match_subscription_share_dir_entry(current_entries, share_root_title)
        root_wrapper_cid = str((root_wrapper_entry or {}).get("cid", "") or (root_wrapper_entry or {}).get("id", "") or "").strip()
        if root_wrapper_cid:
            try:
                branch = await asyncio.wait_for(
                    _fetch_subscription_share_entries(
                        normalized_cookie,
                        share_url,
                        raw_text,
                        root_wrapper_cid,
                        receive_code,
                        force_refresh,
                    ),
                    timeout=request_timeout,
                )
            except Exception:
                stats["reason"] = "share_root_wrapper_unreachable"
                stats["failed_segment"] = str(path_parts[0] if path_parts else "").strip()
                return {}, stats
            stats["scanned_dirs"] = int(stats.get("scanned_dirs", 0) or 0) + 1
            current_entries = branch.get("entries", []) if isinstance(branch.get("entries"), list) else []
            current_cid = root_wrapper_cid
    for idx, segment in enumerate(path_parts):
        matched_entry = _match_subscription_share_dir_entry(current_entries, segment)
        if not matched_entry:
            if not allow_fallback:
                stats["reason"] = "subdir_not_found"
                stats["failed_segment"] = str(segment or "").strip()
                stats["matched_depth"] = idx
                stats["sibling_dir_samples"] = _sample_subscription_share_dir_names(current_entries, limit=6)
                return {}, stats
            fallback_entry, fallback_stats = await _find_subscription_share_dir_by_leaf_fallback(
                normalized_cookie,
                share_url,
                raw_text,
                receive_code,
                expected_leaf_name=path_parts[-1] if path_parts else str(segment or "").strip(),
                expected_tmdbid=_extract_subscription_tmdbid_token(requested_subdir),
                start_cid=current_cid,
                start_parent_path="/".join(matched_parts),
                per_request_timeout=request_timeout,
                max_depth=max(3, len(path_parts) - idx + 1),
                max_dirs=180,
                force_refresh=force_refresh,
            )
            stats["fallback_reason"] = str((fallback_stats or {}).get("reason", "") or "").strip()
            stats["fallback_scanned_dirs"] = int((fallback_stats or {}).get("scanned_dirs", 0) or 0)
            stats["fallback_candidate_count"] = int((fallback_stats or {}).get("candidate_count", 0) or 0)
            stats["scanned_dirs"] = int(stats.get("scanned_dirs", 0) or 0) + int(
                (fallback_stats or {}).get("scanned_dirs", 0) or 0
            )
            if fallback_entry:
                matched_entry = fallback_entry
                fallback_used = True
                fallback_path = normalize_relative_path(str(fallback_entry.get("resolved_path", "") or "").strip())
                if fallback_path:
                    matched_parts = [part for part in fallback_path.split("/") if part]
                    stats["matched_depth"] = len(matched_parts)
                break
            stats["reason"] = "subdir_not_found"
            stats["failed_segment"] = str(segment or "").strip()
            stats["matched_depth"] = idx
            stats["sibling_dir_samples"] = _sample_subscription_share_dir_names(current_entries, limit=6)
            stats["fallback_candidate_samples"] = (
                (fallback_stats or {}).get("candidate_samples", [])
                if isinstance((fallback_stats or {}).get("candidate_samples", []), list)
                else []
            )
            return {}, stats

        entry_name = normalize_relative_path(str(matched_entry.get("name", "") or "").strip())
        if not entry_name:
            stats["reason"] = "subdir_entry_invalid"
            stats["failed_segment"] = str(segment or "").strip()
            stats["matched_depth"] = idx
            return {}, stats

        matched_parts.append(entry_name)
        stats["matched_depth"] = idx + 1

        if idx >= len(path_parts) - 1:
            break
        child_cid = str(matched_entry.get("cid", "") or matched_entry.get("id", "") or "").strip()
        if not child_cid:
            stats["reason"] = "subdir_cid_missing"
            stats["failed_segment"] = str(segment or "").strip()
            return {}, stats
        try:
            branch = await asyncio.wait_for(
                _fetch_subscription_share_entries(
                    normalized_cookie,
                    share_url,
                    raw_text,
                    child_cid,
                    receive_code,
                    force_refresh,
                ),
                timeout=request_timeout,
            )
        except Exception:
            stats["reason"] = "subdir_branch_unreachable"
            stats["failed_segment"] = str(segment or "").strip()
            return {}, stats
        stats["scanned_dirs"] = int(stats.get("scanned_dirs", 0) or 0) + 1
        current_entries = branch.get("entries", []) if isinstance(branch.get("entries"), list) else []
        current_cid = child_cid

    target_id = str(matched_entry.get("id", "") or matched_entry.get("cid", "") or "").strip()
    target_cid = str(matched_entry.get("cid", "") or target_id).strip()
    target_parent_id = str(matched_entry.get("parent_id", "0") or "0").strip() or "0"
    fallback_resolved_subdir = normalize_relative_path(str(matched_entry.get("resolved_path", "") or "").strip())
    resolved_subdir = fallback_resolved_subdir if fallback_used and fallback_resolved_subdir else normalize_relative_path("/".join(matched_parts))
    stats["resolved_subdir"] = resolved_subdir
    stats["resolved_subdir_cid"] = target_cid

    if not target_id or not target_cid or not resolved_subdir:
        stats["reason"] = "subdir_target_invalid"
        return {}, stats
    if fallback_used:
        stats["reason"] = "ok_fallback_leaf"
    else:
        stats["reason"] = "ok"

    selection = normalize_share_selection_meta(
        {
            "selected_ids": [target_id],
            "selected_entries": [
                {
                    "id": target_id,
                    "name": resolved_subdir,
                    "is_dir": True,
                    "parent_id": target_parent_id,
                    "cid": target_cid,
                    "fid": "",
                }
            ],
            "refresh_target_type": "folder",
            "share_root_title": share_root_title,
            "auto_sharetitle": resolved_subdir,
        }
    )
    if not (selection.get("selected_ids", []) if isinstance(selection.get("selected_ids"), list) else []):
        stats["reason"] = "subdir_selection_empty"
        return {}, stats
    return selection, stats


async def _build_tv_share_selection_for_missing_episodes(
    cookie: str,
    task: Dict[str, Any],
    item: Dict[str, Any],
    missing_episodes: Set[int],
    share_subdir_selection: Optional[Dict[str, Any]] = None,
    max_depth: int = 4,
    max_dirs: int = 80,
    max_entries: int = 3000,
    per_request_timeout: int = 25,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    normalized_cookie = str(cookie or "").strip()
    share_url = str(item.get("link_url", "") or "").strip()
    raw_text = str(item.get("raw_text", "") or "")
    target_missing = {max(0, int(value or 0)) for value in missing_episodes if max(0, int(value or 0)) > 0}
    if not normalized_cookie:
        return {}, {"reason": "cookie_missing"}
    if not share_url:
        return {}, {"reason": "share_url_missing"}
    if not target_missing:
        return {}, {"reason": "missing_episodes_empty"}

    item_extra = item.get("extra") if isinstance(item.get("extra"), dict) else safe_json_loads(item.get("extra_json"), {})
    receive_code = (
        normalize_receive_code(item.get("receive_code", ""))
        or normalize_receive_code((item_extra or {}).get("receive_code", ""))
    )

    share_subdir = normalize_relative_path(str(task.get("share_subdir", "") or "").strip())
    share_subdir_cid = _normalize_subscription_share_subdir_cid(task.get("share_subdir_cid", ""))
    subdir_selection = normalize_share_selection_meta(share_subdir_selection or {})
    subdir_stats: Dict[str, Any] = {}
    start_cid = "0"
    start_parent_path = ""
    if share_subdir or share_subdir_cid:
        if not (
            subdir_selection.get("selected_ids", [])
            if isinstance(subdir_selection.get("selected_ids"), list)
            else []
        ):
            subdir_selection, subdir_stats = await _build_subscription_share_subdir_selection(
                normalized_cookie,
                item,
                share_subdir,
                share_subdir_cid=share_subdir_cid,
                per_request_timeout=per_request_timeout,
            )
        subdir_entries = (
            subdir_selection.get("selected_entries", [])
            if isinstance(subdir_selection.get("selected_entries"), list)
            else []
        )
        subdir_entry = subdir_entries[0] if subdir_entries else {}
        if not subdir_entry or not bool(subdir_entry.get("is_dir")):
            reason = str((subdir_stats or {}).get("reason", "") or "share_subdir_unresolved").strip() or "share_subdir_unresolved"
            return {}, {
                "reason": f"share_subdir_{reason}",
                "share_subdir": share_subdir,
                "share_subdir_cid": share_subdir_cid,
                "share_subdir_stats": subdir_stats,
            }
        start_cid = str(subdir_entry.get("cid", "") or subdir_entry.get("id", "") or "").strip() or "0"
        start_parent_path = normalize_relative_path(str(subdir_entry.get("name", "") or "").strip())

    queue: List[Tuple[str, int, str]] = [(start_cid, 0, start_parent_path)]
    visited: Set[str] = set()
    matched_file_entries: List[Dict[str, Any]] = []
    covered_missing: Set[int] = set()
    share_root_title = ""
    scanned_dirs = 0
    scanned_entries = 0
    failed_dirs = 0

    request_timeout = max(10, int(per_request_timeout or 25))
    concurrency = max(1, int(SUBSCRIPTION_SHARE_SCAN_CONCURRENCY or 1))
    while queue and scanned_dirs < max_dirs and scanned_entries < max_entries and covered_missing != target_missing:
        batch: List[Tuple[str, int, str]] = []
        while queue and len(batch) < concurrency and (scanned_dirs + len(batch)) < max_dirs:
            cid, depth, parent_path = queue.pop(0)
            normalized_cid = str(cid or "0").strip() or "0"
            if normalized_cid in visited:
                continue
            visited.add(normalized_cid)
            batch.append((normalized_cid, depth, parent_path))
        if not batch:
            break

        check_subscription_cancelled()
        fetch_tasks = [
            asyncio.wait_for(
                _fetch_subscription_share_entries(
                    normalized_cookie,
                    share_url,
                    raw_text,
                    normalized_cid,
                    receive_code,
                ),
                timeout=request_timeout,
            )
            for normalized_cid, _, _ in batch
        ]
        batch_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        for (normalized_cid, depth, parent_path), branch in zip(batch, batch_results):
            if isinstance(branch, Exception):
                failed_dirs += 1
                continue

            scanned_dirs += 1
            if not share_root_title:
                share_root_title = normalize_relative_path(str(branch.get("share_title", "") or ""))
            entries = branch.get("entries", []) if isinstance(branch.get("entries"), list) else []
            for entry in entries:
                if scanned_entries >= max_entries:
                    break
                scanned_entries += 1
                entry_name = str(entry.get("name", "") or "").strip()
                if not entry_name:
                    continue

                is_dir = bool(entry.get("is_dir"))
                child_cid = str(entry.get("cid", "") or entry.get("id", "") or "").strip()
                rel_name = normalize_relative_path(entry_name)
                full_name = normalize_relative_path(join_relative_path(parent_path, rel_name))

                if is_dir and depth < max_depth and child_cid and child_cid not in visited:
                    queue.append((child_cid, depth + 1, full_name or rel_name))
                if is_dir:
                    continue

                matched_episodes = _extract_task_episodes_from_file_entry(task, rel_name or entry_name, parent_path)
                if not matched_episodes:
                    continue
                episode_hit = matched_episodes.intersection(target_missing)
                if not episode_hit:
                    continue

                entry_id = str(entry.get("id", "") or entry.get("fid", "") or "").strip()
                if not entry_id:
                    continue
                matched_file_entries.append(
                    {
                        "id": entry_id,
                        "name": full_name or rel_name,
                        "is_dir": False,
                        "parent_id": str(entry.get("parent_id", normalized_cid) or normalized_cid).strip() or "0",
                        "cid": "",
                        "fid": str(entry.get("fid", "") or entry_id).strip(),
                        "fid_token": str(entry.get("fid_token", "") or "").strip(),
                        "size": max(0, int(entry.get("size", 0) or 0)),
                        "modified_at": str(entry.get("modified_at", "") or "").strip(),
                        "episodes": sorted(matched_episodes),
                    }
                )
                covered_missing.update(episode_hit)
            if covered_missing == target_missing:
                break

    stats = {
        "reason": "",
        "scanned_dirs": scanned_dirs,
        "scanned_entries": scanned_entries,
        "failed_dirs": failed_dirs,
        "truncated": bool(queue) or scanned_dirs >= max_dirs or scanned_entries >= max_entries,
        "missing_total": len(target_missing),
        "covered_total": len(covered_missing),
        "covered_episodes": sorted(covered_missing)[:300],
        "covered_preview": _format_episode_preview(covered_missing) if covered_missing else "--",
        "selected_count": 0,
        "share_subdir": share_subdir,
        "share_subdir_cid": share_subdir_cid,
        "share_scope_cid": start_cid,
        "share_scope_path": start_parent_path,
    }

    best_selection = _pick_best_tv_share_files_by_episode_bucket(task, matched_file_entries, target_missing)
    selected_entries = (
        best_selection.get("selected_entries", [])
        if isinstance(best_selection.get("selected_entries"), list)
        else []
    )
    selected_ids = (
        best_selection.get("selected_ids", [])
        if isinstance(best_selection.get("selected_ids"), list)
        else []
    )
    covered_missing = _clamp_episode_values(best_selection.get("covered_missing", set()))
    stats["covered_total"] = len(covered_missing)
    stats["covered_episodes"] = sorted(covered_missing)[:300]
    stats["covered_preview"] = _format_episode_preview(covered_missing) if covered_missing else "--"
    stats["selected_count"] = len(selected_ids)
    stats["bucket_count"] = max(0, int(best_selection.get("bucket_count", 0) or 0))
    stats["duplicate_bucket_hits"] = max(0, int(best_selection.get("duplicate_bucket_hits", 0) or 0))
    stats["selected_file_samples"] = _build_subscription_selected_file_samples(
        matched_file_entries,
        selected_ids,
        target_missing,
        sample_limit=8,
    )

    if not selected_ids:
        stats["reason"] = "no_precise_episode_match"
        return {}, stats

    selection = normalize_share_selection_meta(
        {
            "selected_ids": selected_ids,
            "selected_entries": selected_entries,
            "refresh_target_type": "file" if len(selected_ids) == 1 else "mixed",
            "share_root_title": share_root_title,
            "auto_sharetitle": "",
        }
    )
    return selection, stats


async def _scan_subscription_share_tree_snapshot(
    cookie: str,
    task: Dict[str, Any],
    item: Dict[str, Any],
    start_cid: str = "0",
    start_parent_path: str = "",
    max_depth: int = 5,
    max_dirs: int = 180,
    max_entries: int = 5000,
    per_request_timeout: int = 25,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    normalized_cookie = str(cookie or "").strip()
    share_url = str(item.get("link_url", "") or "").strip()
    raw_text = str(item.get("raw_text", "") or "")
    normalized_start_cid = str(start_cid or "0").strip() or "0"
    normalized_start_parent_path = normalize_relative_path(str(start_parent_path or "").strip())
    if not normalized_cookie:
        return {"reason": "cookie_missing", "dirs": [], "files": []}
    if not share_url:
        return {"reason": "share_url_missing", "dirs": [], "files": []}

    item_extra = item.get("extra") if isinstance(item.get("extra"), dict) else safe_json_loads(item.get("extra_json"), {})
    receive_code = (
        normalize_receive_code(item.get("receive_code", ""))
        or normalize_receive_code((item_extra or {}).get("receive_code", ""))
    )

    queue: List[Tuple[str, int, str]] = [(normalized_start_cid, 0, normalized_start_parent_path)]
    visited: Set[str] = set()
    dirs: List[Dict[str, Any]] = []
    files: List[Dict[str, Any]] = []
    seen_dir_ids: Set[str] = set()
    seen_file_ids: Set[str] = set()
    covered_episodes: Set[int] = set()
    scanned_dirs = 0
    scanned_entries = 0
    failed_dirs = 0
    share_root_title = ""
    request_timeout = max(10, int(per_request_timeout or 25))
    concurrency = max(1, int(SUBSCRIPTION_SHARE_SCAN_CONCURRENCY or 1))

    if normalized_start_parent_path and normalized_start_cid not in ("", "0"):
        dirs.append(
            {
                "id": normalized_start_cid,
                "cid": normalized_start_cid,
                "parent_id": "0",
                "name": normalized_start_parent_path,
                "is_dir": True,
                "depth": 0,
            }
        )
        seen_dir_ids.add(normalized_start_cid)

    while queue and scanned_dirs < max_dirs and scanned_entries < max_entries:
        batch: List[Tuple[str, int, str]] = []
        while queue and len(batch) < concurrency and (scanned_dirs + len(batch)) < max_dirs:
            cid, depth, parent_path = queue.pop(0)
            normalized_cid = str(cid or "0").strip() or "0"
            if normalized_cid in visited:
                continue
            visited.add(normalized_cid)
            batch.append((normalized_cid, depth, normalize_relative_path(parent_path)))
        if not batch:
            break

        check_subscription_cancelled()
        fetch_tasks = [
            asyncio.wait_for(
                _fetch_subscription_share_entries(
                    normalized_cookie,
                    share_url,
                    raw_text,
                    normalized_cid,
                    receive_code,
                    force_refresh,
                ),
                timeout=request_timeout,
            )
            for normalized_cid, _, _ in batch
        ]
        batch_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        for (normalized_cid, depth, parent_path), branch in zip(batch, batch_results):
            if isinstance(branch, Exception):
                failed_dirs += 1
                continue

            scanned_dirs += 1
            if not share_root_title:
                share_root_title = normalize_relative_path(str(branch.get("share_title", "") or "").strip())
            entries = branch.get("entries", []) if isinstance(branch.get("entries"), list) else []
            for entry in entries:
                if scanned_entries >= max_entries:
                    break
                scanned_entries += 1
                entry_name = str(entry.get("name", "") or "").strip()
                if not entry_name:
                    continue

                rel_name = normalize_relative_path(entry_name)
                full_name = normalize_relative_path(join_relative_path(parent_path, rel_name))
                is_dir = bool(entry.get("is_dir"))
                entry_id = str(entry.get("id", "") or entry.get("cid", "") or entry.get("fid", "") or "").strip()
                child_cid = str(entry.get("cid", "") or entry.get("id", "") or "").strip()
                if is_dir:
                    if entry_id and entry_id not in seen_dir_ids:
                        dirs.append(
                            {
                                "id": entry_id,
                                "cid": child_cid or entry_id,
                                "parent_id": str(entry.get("parent_id", normalized_cid) or normalized_cid).strip() or "0",
                                "name": full_name or rel_name,
                                "is_dir": True,
                                "depth": depth + 1,
                            }
                        )
                        seen_dir_ids.add(entry_id)
                    if depth < max_depth and child_cid and child_cid not in visited:
                        queue.append((child_cid, depth + 1, full_name or rel_name))
                    continue

                if not entry_id or entry_id in seen_file_ids:
                    continue
                matched_episodes = sorted(_extract_task_episodes_from_file_entry(task, rel_name or entry_name, parent_path))
                files.append(
                    {
                        "id": entry_id,
                        "name": full_name or rel_name,
                        "is_dir": False,
                        "parent_id": str(entry.get("parent_id", normalized_cid) or normalized_cid).strip() or "0",
                        "cid": "",
                        "fid": str(entry.get("fid", "") or entry_id).strip(),
                        "fid_token": str(entry.get("fid_token", "") or "").strip(),
                        "size": max(0, int(entry.get("size", 0) or 0)),
                        "modified_at": str(entry.get("modified_at", "") or "").strip(),
                        "episodes": matched_episodes,
                    }
                )
                seen_file_ids.add(entry_id)
                if matched_episodes:
                    covered_episodes.update(matched_episodes)

    return {
        "reason": "ok",
        "share_root_title": share_root_title,
        "share_scope_cid": normalized_start_cid,
        "share_scope_path": normalized_start_parent_path,
        "dirs": dirs,
        "files": files,
        "covered_episodes": sorted(covered_episodes),
        "covered_preview": _format_episode_preview(covered_episodes) if covered_episodes else "--",
        "file_count": len(files),
        "dir_count": len(dirs),
        "scanned_dirs": scanned_dirs,
        "scanned_entries": scanned_entries,
        "failed_dirs": failed_dirs,
        "truncated": bool(queue) or scanned_dirs >= max_dirs or scanned_entries >= max_entries,
        "force_refresh": bool(force_refresh),
    }


def _build_subscription_share_selection_from_snapshot(
    snapshot: Dict[str, Any],
    share_subdir: str,
    share_subdir_cid: str = "",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    payload = snapshot if isinstance(snapshot, dict) else {}
    requested_subdir = normalize_relative_path(str(share_subdir or "").strip())
    requested_cid = _normalize_subscription_share_subdir_cid(share_subdir_cid)
    share_root_title = normalize_relative_path(str(payload.get("share_root_title", "") or "").strip())
    stats: Dict[str, Any] = {
        "reason": "",
        "requested_subdir": requested_subdir,
        "requested_subdir_cid": requested_cid,
        "share_root_title": share_root_title,
        "resolved_subdir": "",
        "resolved_subdir_cid": "",
        "scanned_dirs": int(payload.get("scanned_dirs", 0) or 0),
        "scanned_entries": int(payload.get("scanned_entries", 0) or 0),
        "failed_dirs": int(payload.get("failed_dirs", 0) or 0),
    }

    if requested_cid:
        resolved_cid = str(payload.get("share_scope_cid", "") or requested_cid).strip() or requested_cid
        resolved_subdir = requested_subdir or normalize_relative_path(str(payload.get("share_scope_path", "") or "").strip())
        resolved_subdir = resolved_subdir or normalize_relative_path(f"cid-{resolved_cid}")
        stats["reason"] = "ok_cid_anchor"
        stats["resolved_subdir"] = resolved_subdir
        stats["resolved_subdir_cid"] = resolved_cid
        return (
            normalize_share_selection_meta(
                {
                    "selected_ids": [resolved_cid],
                    "selected_entries": [
                        {
                            "id": resolved_cid,
                            "name": resolved_subdir,
                            "is_dir": True,
                            "parent_id": "0",
                            "cid": resolved_cid,
                            "fid": "",
                        }
                    ],
                    "refresh_target_type": "folder",
                    "share_root_title": share_root_title,
                    "auto_sharetitle": resolved_subdir,
                }
            ),
            stats,
        )

    if not requested_subdir:
        stats["reason"] = "share_subdir_empty"
        return {}, stats

    requested_parts = _normalize_subscription_share_subdir_parts(requested_subdir, share_root_title)
    if not requested_parts:
        stats["reason"] = "target_is_share_root"
        return {}, stats
    target_path = normalize_relative_path("/".join(requested_parts))
    target_parts_lower = [part.lower() for part in requested_parts]
    dirs = payload.get("dirs", []) if isinstance(payload.get("dirs"), list) else []

    exact_candidates: List[Dict[str, Any]] = []
    suffix_candidates: List[Dict[str, Any]] = []
    leaf_candidates: List[Tuple[int, Dict[str, Any]]] = []
    for entry in dirs:
        if not isinstance(entry, dict) or not bool(entry.get("is_dir")):
            continue
        entry_path = normalize_relative_path(str(entry.get("name", "") or "").strip())
        if not entry_path:
            continue
        entry_parts = [part for part in entry_path.split("/") if part]
        entry_parts_lower = [part.lower() for part in entry_parts]
        if entry_path.lower() == target_path.lower():
            exact_candidates.append(entry)
            continue
        if len(entry_parts_lower) >= len(target_parts_lower) and entry_parts_lower[-len(target_parts_lower) :] == target_parts_lower:
            suffix_candidates.append(entry)
        leaf_score = _score_subscription_share_dir_candidate_name(
            entry_name=entry_parts[-1] if entry_parts else entry_path,
            expected_name=requested_parts[-1],
            expected_tmdbid=_extract_subscription_tmdbid_token(requested_subdir),
        )
        if leaf_score > 0:
            leaf_candidates.append((leaf_score, entry))

    matched_entry: Dict[str, Any] = {}
    if len(exact_candidates) == 1:
        matched_entry = exact_candidates[0]
        stats["reason"] = "ok_exact_path"
    elif len(exact_candidates) > 1:
        exact_candidates.sort(key=lambda item: len(str(item.get("name", "") or "").split("/")))
        matched_entry = exact_candidates[0]
        stats["reason"] = "ok_exact_path_ambiguous"
    elif len(suffix_candidates) == 1:
        matched_entry = suffix_candidates[0]
        stats["reason"] = "ok_suffix_path"
    elif len(suffix_candidates) > 1:
        suffix_candidates.sort(key=lambda item: len(str(item.get("name", "") or "").split("/")))
        matched_entry = suffix_candidates[0]
        stats["reason"] = "ok_suffix_path_ambiguous"
    elif leaf_candidates:
        leaf_candidates.sort(key=lambda item: (int(item[0] or 0), len(str(item[1].get("name", "") or "").split("/"))), reverse=True)
        best_score = int(leaf_candidates[0][0] or 0)
        best_matches = [entry for score, entry in leaf_candidates if int(score or 0) == best_score]
        if len(best_matches) == 1 and best_score >= 130:
            matched_entry = best_matches[0]
            stats["reason"] = "ok_leaf_match"
        else:
            stats["reason"] = "subdir_ambiguous" if len(best_matches) > 1 else "subdir_not_found"
            stats["candidate_samples"] = [
                str(entry.get("name", "") or "").strip()
                for entry in best_matches[:5]
                if str(entry.get("name", "") or "").strip()
            ]
            return {}, stats
    else:
        stats["reason"] = "subdir_not_found"
        stats["candidate_samples"] = [
            str(entry.get("name", "") or "").strip()
            for entry in dirs[:8]
            if isinstance(entry, dict) and str(entry.get("name", "") or "").strip()
        ]
        return {}, stats

    target_id = str(matched_entry.get("id", "") or matched_entry.get("cid", "") or "").strip()
    target_cid = str(matched_entry.get("cid", "") or target_id).strip()
    resolved_subdir = normalize_relative_path(str(matched_entry.get("name", "") or "").strip())
    if not target_id or not target_cid or not resolved_subdir:
        stats["reason"] = "subdir_target_invalid"
        return {}, stats
    stats["resolved_subdir"] = resolved_subdir
    stats["resolved_subdir_cid"] = target_cid
    selection = normalize_share_selection_meta(
        {
            "selected_ids": [target_id],
            "selected_entries": [
                {
                    "id": target_id,
                    "name": resolved_subdir,
                    "is_dir": True,
                    "parent_id": str(matched_entry.get("parent_id", "0") or "0").strip() or "0",
                    "cid": target_cid,
                    "fid": "",
                }
            ],
            "refresh_target_type": "folder",
            "share_root_title": share_root_title,
            "auto_sharetitle": resolved_subdir,
        }
    )
    return selection, stats


def _build_subscription_share_manifest_from_snapshot(
    snapshot: Dict[str, Any],
    selection: Dict[str, Any],
) -> Dict[str, Any]:
    payload = snapshot if isinstance(snapshot, dict) else {}
    normalized_selection = normalize_share_selection_meta(selection or {})
    selected_entries = (
        normalized_selection.get("selected_entries", [])
        if isinstance(normalized_selection.get("selected_entries"), list)
        else []
    )
    start_entry = selected_entries[0] if selected_entries else {}
    if not start_entry or not bool(start_entry.get("is_dir")):
        return {"reason": "selection_invalid", "files": [], "covered_episodes": []}

    raw_scope_path = normalize_relative_path(str(payload.get("share_scope_path", "") or "").strip())
    scope_cid = str(start_entry.get("cid", "") or start_entry.get("id", "") or payload.get("share_scope_cid", "") or "").strip()
    scope_path = normalize_relative_path(str(start_entry.get("name", "") or raw_scope_path or "").strip())
    if scope_cid and scope_cid == str(payload.get("share_scope_cid", "") or "").strip() and not raw_scope_path:
        scope_path = ""
    file_entries = payload.get("files", []) if isinstance(payload.get("files"), list) else []
    scoped_files: List[Dict[str, Any]] = []
    covered_episodes: Set[int] = set()
    for raw_entry in file_entries:
        if not isinstance(raw_entry, dict):
            continue
        entry_name = normalize_relative_path(str(raw_entry.get("name", "") or "").strip())
        if not entry_name:
            continue
        if scope_path and entry_name.lower() != scope_path.lower() and not entry_name.lower().startswith(f"{scope_path.lower()}/"):
            continue
        scoped_files.append(raw_entry)
        entry_episodes = raw_entry.get("episodes", []) if isinstance(raw_entry.get("episodes"), list) else []
        covered_episodes.update(
            max(0, int(value or 0))
            for value in entry_episodes
            if max(0, int(value or 0)) > 0
        )

    return {
        "reason": "ok" if scoped_files else "no_episode_files",
        "share_root_title": str(payload.get("share_root_title", "") or "").strip(),
        "share_scope_cid": scope_cid,
        "share_scope_path": scope_path,
        "files": scoped_files,
        "covered_episodes": sorted(covered_episodes),
        "covered_preview": _format_episode_preview(covered_episodes) if covered_episodes else "--",
        "file_count": len(scoped_files),
        "scanned_dirs": int(payload.get("scanned_dirs", 0) or 0),
        "scanned_entries": int(payload.get("scanned_entries", 0) or 0),
        "failed_dirs": int(payload.get("failed_dirs", 0) or 0),
        "truncated": bool(payload.get("truncated", False)),
        "force_refresh": bool(payload.get("force_refresh", False)),
    }


async def _scan_subscription_share_episode_manifest(
    cookie: str,
    task: Dict[str, Any],
    item: Dict[str, Any],
    selection: Dict[str, Any],
    max_depth: int = 4,
    max_dirs: int = 80,
    max_entries: int = 3000,
    per_request_timeout: int = 25,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    normalized_cookie = str(cookie or "").strip()
    share_url = str(item.get("link_url", "") or "").strip()
    raw_text = str(item.get("raw_text", "") or "")
    if not normalized_cookie:
        return {"reason": "cookie_missing", "files": [], "covered_episodes": []}
    if not share_url:
        return {"reason": "share_url_missing", "files": [], "covered_episodes": []}

    normalized_selection = normalize_share_selection_meta(selection or {})
    selected_entries = (
        normalized_selection.get("selected_entries", [])
        if isinstance(normalized_selection.get("selected_entries"), list)
        else []
    )
    start_entry = selected_entries[0] if selected_entries else {}
    if not start_entry or not bool(start_entry.get("is_dir")):
        return {"reason": "selection_invalid", "files": [], "covered_episodes": []}

    start_cid = str(start_entry.get("cid", "") or start_entry.get("id", "") or "").strip()
    start_parent_path = normalize_relative_path(str(start_entry.get("name", "") or "").strip())
    if not start_cid:
        return {"reason": "selection_invalid", "files": [], "covered_episodes": []}

    item_extra = item.get("extra") if isinstance(item.get("extra"), dict) else safe_json_loads(item.get("extra_json"), {})
    receive_code = (
        normalize_receive_code(item.get("receive_code", ""))
        or normalize_receive_code((item_extra or {}).get("receive_code", ""))
    )
    queue: List[Tuple[str, int, str]] = [(start_cid, 0, start_parent_path)]
    visited: Set[str] = {start_cid}
    files: List[Dict[str, Any]] = []
    seen_file_ids: Set[str] = set()
    covered_episodes: Set[int] = set()
    scanned_dirs = 0
    scanned_entries = 0
    failed_dirs = 0
    share_root_title = normalize_relative_path(str(normalized_selection.get("share_root_title", "") or "").strip())
    concurrency = max(1, int(SUBSCRIPTION_SHARE_SCAN_CONCURRENCY or 1))

    while queue and scanned_dirs < max_dirs and scanned_entries < max_entries:
        batch: List[Tuple[str, int, str]] = []
        while queue and len(batch) < concurrency and (scanned_dirs + len(batch)) < max_dirs:
            batch.append(queue.pop(0))
        if not batch:
            break

        check_subscription_cancelled()
        fetch_tasks = [
            asyncio.wait_for(
                _fetch_subscription_share_entries(
                    normalized_cookie,
                    share_url,
                    raw_text,
                    str(cid or "0").strip() or "0",
                    receive_code,
                    force_refresh,
                ),
                timeout=max(10, int(per_request_timeout or 25)),
            )
            for cid, _, _ in batch
        ]
        batch_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        for (cid, depth, parent_path), branch in zip(batch, batch_results):
            normalized_cid = str(cid or "0").strip() or "0"
            if isinstance(branch, Exception):
                failed_dirs += 1
                continue

            scanned_dirs += 1
            if not share_root_title:
                share_root_title = normalize_relative_path(str(branch.get("share_title", "") or "").strip())
            entries = branch.get("entries", []) if isinstance(branch.get("entries"), list) else []
            for entry in entries:
                if scanned_entries >= max_entries:
                    break
                scanned_entries += 1
                entry_name = str(entry.get("name", "") or "").strip()
                if not entry_name:
                    continue

                is_dir = bool(entry.get("is_dir"))
                child_cid = str(entry.get("cid", "") or entry.get("id", "") or "").strip()
                rel_name = normalize_relative_path(entry_name)
                full_name = normalize_relative_path(join_relative_path(parent_path, rel_name))
                if is_dir:
                    if depth < max_depth and child_cid and child_cid not in visited:
                        visited.add(child_cid)
                        queue.append((child_cid, depth + 1, full_name or rel_name))
                    continue

                matched_episodes = sorted(_extract_task_episodes_from_file_entry(task, rel_name or entry_name, parent_path))
                if not matched_episodes:
                    continue
                entry_id = str(entry.get("id", "") or entry.get("fid", "") or "").strip()
                if (not entry_id) or entry_id in seen_file_ids:
                    continue
                seen_file_ids.add(entry_id)
                files.append(
                    {
                        "id": entry_id,
                        "name": full_name or rel_name,
                        "is_dir": False,
                        "parent_id": str(entry.get("parent_id", normalized_cid) or normalized_cid).strip() or "0",
                        "cid": "",
                        "fid": str(entry.get("fid", "") or entry_id).strip(),
                        "size": max(0, int(entry.get("size", 0) or 0)),
                        "modified_at": str(entry.get("modified_at", "") or "").strip(),
                        "episodes": matched_episodes,
                    }
                )
                covered_episodes.update(matched_episodes)

    return {
        "reason": "ok" if files else "no_episode_files",
        "share_root_title": share_root_title,
        "share_scope_cid": start_cid,
        "share_scope_path": start_parent_path,
        "files": files,
        "covered_episodes": sorted(covered_episodes),
        "covered_preview": _format_episode_preview(covered_episodes) if covered_episodes else "--",
        "file_count": len(files),
        "scanned_dirs": scanned_dirs,
        "scanned_entries": scanned_entries,
        "failed_dirs": failed_dirs,
        "truncated": bool(queue) or scanned_dirs >= max_dirs or scanned_entries >= max_entries,
        "force_refresh": bool(force_refresh),
    }


def _build_tv_share_selection_from_manifest(
    manifest: Dict[str, Any],
    missing_episodes: Set[int],
    task: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    payload = manifest if isinstance(manifest, dict) else {}
    target_missing = {max(0, int(value or 0)) for value in (missing_episodes or set()) if max(0, int(value or 0)) > 0}
    if not target_missing:
        return {}, {"reason": "missing_episodes_empty", "from_runtime_cache": True}

    file_entries = payload.get("files", []) if isinstance(payload.get("files"), list) else []
    best_selection = _pick_best_tv_share_files_by_episode_bucket(task or {}, file_entries, target_missing)
    selected_entries = (
        best_selection.get("selected_entries", [])
        if isinstance(best_selection.get("selected_entries"), list)
        else []
    )
    selected_ids = (
        best_selection.get("selected_ids", [])
        if isinstance(best_selection.get("selected_ids"), list)
        else []
    )
    covered_missing = _clamp_episode_values(best_selection.get("covered_missing", set()))

    stats = {
        "reason": "",
        "from_runtime_cache": True,
        "missing_total": len(target_missing),
        "covered_total": len(covered_missing),
        "covered_episodes": sorted(covered_missing)[:300],
        "covered_preview": _format_episode_preview(covered_missing) if covered_missing else "--",
        "selected_count": len(selected_entries),
        "file_count": max(0, int(payload.get("file_count", 0) or len(file_entries))),
        "scanned_dirs": max(0, int(payload.get("scanned_dirs", 0) or 0)),
        "scanned_entries": max(0, int(payload.get("scanned_entries", 0) or 0)),
        "failed_dirs": max(0, int(payload.get("failed_dirs", 0) or 0)),
        "truncated": bool(payload.get("truncated", False)),
        "share_scope_cid": str(payload.get("share_scope_cid", "") or "").strip(),
        "share_scope_path": normalize_relative_path(str(payload.get("share_scope_path", "") or "").strip()),
        "bucket_count": max(0, int(best_selection.get("bucket_count", 0) or 0)),
        "duplicate_bucket_hits": max(0, int(best_selection.get("duplicate_bucket_hits", 0) or 0)),
        "selected_file_samples": _build_subscription_selected_file_samples(
            file_entries,
            selected_ids,
            target_missing,
            sample_limit=8,
        ),
    }
    if not selected_entries:
        stats["reason"] = "no_precise_episode_match"
        return {}, stats

    selection = normalize_share_selection_meta(
        {
            "selected_ids": selected_ids,
            "selected_entries": selected_entries,
            "refresh_target_type": "file" if len(selected_entries) == 1 else "mixed",
            "share_root_title": str(payload.get("share_root_title", "") or "").strip(),
            "auto_sharetitle": "",
        }
    )
    stats["reason"] = "ok"
    return selection, stats


def _split_tv_share_selection_by_season(
    task: Dict[str, Any],
    selection: Dict[str, Any],
    manifest: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    normalized_selection = normalize_share_selection_meta(selection or {})
    selected_entries = (
        normalized_selection.get("selected_entries", [])
        if isinstance(normalized_selection.get("selected_entries"), list)
        else []
    )
    stats: Dict[str, Any] = {
        "reason": "",
        "selected_count": len(selected_entries),
        "season_count": 0,
        "resolved_count": 0,
        "unresolved_count": 0,
        "cross_season_entry_count": 0,
        "unresolved_samples": [],
    }

    if not is_subscription_multi_season_mode(task):
        stats["reason"] = "single_season_mode"
        return [], stats
    if not selected_entries:
        stats["reason"] = "selection_empty"
        return [], stats

    file_entries = [entry for entry in selected_entries if isinstance(entry, dict) and not bool(entry.get("is_dir"))]
    if not file_entries:
        stats["reason"] = "selection_has_no_files"
        return [], stats
    if len(file_entries) != len(selected_entries):
        stats["reason"] = "selection_contains_dirs"
        return [], stats

    manifest_lookup: Dict[str, Set[int]] = {}
    manifest_payload = manifest if isinstance(manifest, dict) else {}
    manifest_files = manifest_payload.get("files", []) if isinstance(manifest_payload.get("files"), list) else []
    for raw_entry in manifest_files:
        if not isinstance(raw_entry, dict):
            continue
        entry_id = str(raw_entry.get("id", "") or raw_entry.get("fid", "") or "").strip()
        if not entry_id:
            continue
        entry_episodes = _clamp_episode_values(
            {
                max(0, int(value or 0))
                for value in (raw_entry.get("episodes", []) if isinstance(raw_entry.get("episodes"), list) else [])
                if max(0, int(value or 0)) > 0
            }
        )
        if entry_episodes:
            manifest_lookup[entry_id] = entry_episodes

    grouped_entries: Dict[int, List[Dict[str, Any]]] = {}
    grouped_ids: Dict[int, List[str]] = {}
    grouped_episodes: Dict[int, Set[int]] = {}
    unresolved_samples: List[str] = []
    cross_season_entry_count = 0

    for entry in file_entries:
        entry_id = str(entry.get("id", "") or entry.get("fid", "") or "").strip()
        entry_name = normalize_relative_path(str(entry.get("name", "") or "").strip())
        if not entry_id or not entry_name:
            continue

        entry_episodes = set(manifest_lookup.get(entry_id, set()))
        if not entry_episodes:
            entry_parts = [part for part in entry_name.split("/") if part]
            file_name = entry_parts[-1] if entry_parts else entry_name
            parent_path = normalize_relative_path("/".join(entry_parts[:-1]))
            entry_episodes = _clamp_episode_values(
                _extract_task_episodes_from_file_entry(task, file_name, parent_path)
            )

        mapped_seasons: List[int] = []
        for absolute_episode in sorted(entry_episodes):
            season_no, _ = convert_subscription_absolute_to_season_episode(task, absolute_episode)
            if season_no > 0:
                mapped_seasons.append(season_no)

        if not mapped_seasons:
            if len(unresolved_samples) < 3:
                unresolved_samples.append(entry_name[:96])
            continue

        unique_seasons = sorted(set(mapped_seasons))
        target_season = unique_seasons[0]
        if len(unique_seasons) > 1:
            cross_season_entry_count += 1

        grouped_entries.setdefault(target_season, []).append(entry)
        grouped_ids.setdefault(target_season, []).append(entry_id)
        grouped_episodes.setdefault(target_season, set()).update(entry_episodes)

    if not grouped_entries:
        stats["reason"] = "season_unresolved"
        stats["unresolved_count"] = len(file_entries)
        stats["unresolved_samples"] = unresolved_samples
        return [], stats

    groups: List[Dict[str, Any]] = []
    for season_no in sorted(grouped_entries):
        group_selection = normalize_share_selection_meta(
            {
                "selected_ids": grouped_ids.get(season_no, []),
                "selected_entries": grouped_entries.get(season_no, []),
                "refresh_target_type": "file" if len(grouped_entries.get(season_no, [])) == 1 else "mixed",
                "share_root_title": normalized_selection.get("share_root_title", ""),
                "auto_sharetitle": "",
            }
        )
        group_episodes = _clamp_episode_values(grouped_episodes.get(season_no, set()))
        groups.append(
            {
                "season": season_no,
                "selection": group_selection,
                "episodes": group_episodes,
                "selected_count": len(group_selection.get("selected_ids", [])),
            }
        )

    stats["reason"] = "partial" if unresolved_samples else "ok"
    stats["season_count"] = len(groups)
    stats["resolved_count"] = sum(len(group.get("selection", {}).get("selected_ids", [])) for group in groups)
    stats["unresolved_count"] = max(0, len(file_entries) - int(stats["resolved_count"] or 0))
    stats["cross_season_entry_count"] = cross_season_entry_count
    stats["unresolved_samples"] = unresolved_samples
    return groups, stats


async def find_subscription_task_match_candidate_by_search(
    task: Dict[str, Any],
    last_episode: int = 0,
    trigger: str = "",
) -> Dict[str, Any]:
    provider = normalize_subscription_provider(task.get("provider", "115"), fallback="115")
    search_identity_mode = "link" if provider == "quark" else "message"
    trigger_mode = str(trigger or "").strip().lower()
    incremental_search_enabled = trigger_mode == "cron"
    task_name = str(task.get("name", "") or task.get("title", "") or "").strip()
    baseline_channel_watermarks = (
        load_subscription_channel_search_watermarks(task_name)
        if (incremental_search_enabled and task_name)
        else {}
    )
    incremental_since_cursor_by_channel: Dict[str, int] = {
        normalize_telegram_channel_id_from_input(channel_id): max(0, int((payload or {}).get("last_post_cursor", 0) or 0))
        for channel_id, payload in (baseline_channel_watermarks.items() if isinstance(baseline_channel_watermarks, dict) else [])
        if normalize_telegram_channel_id_from_input(channel_id)
    }
    observed_channel_watermarks: Dict[str, Dict[str, Any]] = {}
    incremental_error_channels: Set[str] = set()
    incremental_stop_channels = 0
    channel_support_stats_deltas: Dict[str, Dict[str, Any]] = {}
    query_tokens = build_subscription_query_tokens(task)
    if not query_tokens:
        return {"candidate": {}, "keywords": [], "stats": {}, "errors": []}

    keywords = _build_subscription_search_keywords(task, limit=6)
    all_items: List[Dict[str, Any]] = []
    all_errors: List[Dict[str, Any]] = []
    searched_sources = 0
    matched_channels = 0
    pages_scanned = 0

    for keyword in keywords:
        check_subscription_cancelled()
        search_meta = await search_resource_sources(
            keyword,
            identity_mode=search_identity_mode,
            incremental_since_cursor_by_channel=(
                incremental_since_cursor_by_channel if incremental_search_enabled else None
            ),
        )
        all_items.extend(search_meta.get("items", []) if isinstance(search_meta.get("items"), list) else [])
        all_errors.extend(search_meta.get("errors", []) if isinstance(search_meta.get("errors"), list) else [])
        searched_sources += max(0, int(search_meta.get("searched_sources", 0) or 0))
        matched_channels += max(0, int(search_meta.get("matched_channels", 0) or 0))
        pages_scanned += max(0, int(search_meta.get("pages_scanned", 0) or 0))
        channel_stats = search_meta.get("channel_stats", []) if isinstance(search_meta.get("channel_stats"), list) else []
        for raw_row in channel_stats:
            if not isinstance(raw_row, dict):
                continue
            channel_id = normalize_telegram_channel_id_from_input(raw_row.get("channel_id", ""))
            if not channel_id:
                continue
            row = channel_support_stats_deltas.setdefault(
                channel_id,
                {
                    "channel_id": channel_id,
                    "channel_name": str(raw_row.get("name", "") or channel_id).strip() or channel_id,
                    "searched_runs": 0,
                    "matched_runs": 0,
                    "matched_items": 0,
                    "error_runs": 0,
                    "incremental_stop_hits": 0,
                    "pages_scanned": 0,
                    "last_error": "",
                },
            )
            row["searched_runs"] = int(row.get("searched_runs", 0) or 0) + 1
            matched = bool(raw_row.get("matched", False))
            item_count = max(0, int(raw_row.get("item_count", 0) or 0))
            row["matched_runs"] = int(row.get("matched_runs", 0) or 0) + (1 if matched else 0)
            row["matched_items"] = int(row.get("matched_items", 0) or 0) + item_count
            row["pages_scanned"] = int(row.get("pages_scanned", 0) or 0) + max(
                0,
                int(raw_row.get("pages_scanned", 0) or 0),
            )
            if bool(raw_row.get("incremental_stop_hit", False)):
                row["incremental_stop_hits"] = int(row.get("incremental_stop_hits", 0) or 0) + 1
            error_text = str(raw_row.get("error", "") or "").strip()
            if error_text:
                row["error_runs"] = int(row.get("error_runs", 0) or 0) + 1
                row["last_error"] = error_text[:300]
        if incremental_search_enabled:
            incremental_stop_channels += max(0, int(search_meta.get("incremental_stop_channels", 0) or 0))
            channel_watermarks = (
                search_meta.get("channel_watermarks", {})
                if isinstance(search_meta.get("channel_watermarks"), dict)
                else {}
            )
            for raw_channel_id, raw_payload in channel_watermarks.items():
                channel_id = normalize_telegram_channel_id_from_input(raw_channel_id)
                if not channel_id or not isinstance(raw_payload, dict):
                    continue
                candidate_cursor = max(0, int(raw_payload.get("last_post_cursor", 0) or 0))
                candidate_published_at = str(raw_payload.get("last_published_at", "") or "").strip()
                existing_payload = observed_channel_watermarks.get(channel_id, {})
                existing_cursor = max(0, int(existing_payload.get("last_post_cursor", 0) or 0))
                existing_published_at = str(existing_payload.get("last_published_at", "") or "").strip()
                existing_published_ts = parse_resource_datetime_to_timestamp(existing_published_at)
                candidate_published_ts = parse_resource_datetime_to_timestamp(candidate_published_at)
                if candidate_cursor > existing_cursor:
                    observed_channel_watermarks[channel_id] = {
                        "channel_id": channel_id,
                        "last_post_cursor": candidate_cursor,
                        "last_published_at": candidate_published_at,
                    }
                    continue
                if candidate_cursor == existing_cursor and candidate_published_ts > existing_published_ts:
                    observed_channel_watermarks[channel_id] = {
                        "channel_id": channel_id,
                        "last_post_cursor": candidate_cursor,
                        "last_published_at": candidate_published_at,
                    }
            channel_errors = search_meta.get("errors", []) if isinstance(search_meta.get("errors"), list) else []
            for err in channel_errors:
                if not isinstance(err, dict):
                    continue
                channel_id = normalize_telegram_channel_id_from_input(err.get("channel_id", ""))
                if channel_id:
                    incremental_error_channels.add(channel_id)

    deduped_items = dedupe_resource_item_dicts(all_items, identity_mode=search_identity_mode)
    deduped_items.sort(key=get_resource_item_sort_key, reverse=True)
    if provider == "quark":
        expanded_quark_items: List[Dict[str, Any]] = []
        for raw_item in deduped_items:
            expanded_quark_items.extend(_expand_subscription_quark_item_variants(raw_item))
        deduped_items = dedupe_resource_item_dicts(expanded_quark_items, identity_mode="link")
        deduped_items.sort(key=get_resource_item_sort_key, reverse=True)
    merged_errors = _merge_subscription_search_errors(all_errors)
    incremental_channels_advanced = 0
    channel_support_rows_updated = 0
    if incremental_search_enabled and task_name and observed_channel_watermarks:
        writable_channel_watermarks: Dict[str, Dict[str, Any]] = {}
        for channel_id, payload in observed_channel_watermarks.items():
            normalized_channel_id = normalize_telegram_channel_id_from_input(channel_id)
            if not normalized_channel_id or normalized_channel_id in incremental_error_channels:
                continue
            if not isinstance(payload, dict):
                continue
            writable_channel_watermarks[normalized_channel_id] = {
                "last_post_cursor": max(0, int(payload.get("last_post_cursor", 0) or 0)),
                "last_published_at": str(payload.get("last_published_at", "") or "").strip(),
                "last_run_at": now_text(),
            }
        incremental_channels_advanced = upsert_subscription_channel_search_watermarks(
            task_name,
            writable_channel_watermarks,
            only_increase=True,
        )
    if task_name and channel_support_stats_deltas:
        now_iso = now_text()
        writable_support_stats: Dict[str, Dict[str, Any]] = {}
        for channel_id, payload in channel_support_stats_deltas.items():
            normalized_channel_id = normalize_telegram_channel_id_from_input(channel_id)
            if not normalized_channel_id or not isinstance(payload, dict):
                continue
            writable_support_stats[normalized_channel_id] = {
                **payload,
                "last_searched_at": now_iso,
                "last_matched_at": now_iso if int(payload.get("matched_runs", 0) or 0) > 0 else "",
            }
        channel_support_rows_updated = upsert_subscription_channel_support_stats(
            writable_support_stats,
            task_name=task_name,
            provider=provider,
            trigger=trigger_mode,
        )
    min_score = (
        max(30, min(100, int(SUBSCRIPTION_QUARK_MIN_SCORE or 60)))
        if provider == "quark"
        else max(30, min(100, int(task.get("min_score", SUBSCRIPTION_MIN_SCORE) or SUBSCRIPTION_MIN_SCORE)))
    )
    persisted_items: List[Dict[str, Any]] = []
    ensure_db()
    conn = open_db()
    try:
        for raw_item in deduped_items:
            item = raw_item if isinstance(raw_item, dict) else {}
            item_id, _ = upsert_resource_item(conn, item, identity_mode=search_identity_mode)
            if item_id <= 0:
                continue
            normalized_item = {**item, "id": item_id}
            extra = normalized_item.get("extra") if isinstance(normalized_item.get("extra"), dict) else {}
            source_post_id = str(
                normalized_item.get("source_post_id", "") or extra.get("source_post_id", "")
            ).strip()
            if source_post_id:
                normalized_item["source_post_id"] = source_post_id
            persisted_items.append(normalized_item)
        conn.commit()
    finally:
        conn.close()

    # 频道聚合时同一资源可能被多次命中；这里按资源主键/链接去重，避免后续重复候选。
    deduped_persisted_items: List[Dict[str, Any]] = []
    seen_persisted_keys: Set[str] = set()
    for item in persisted_items:
        item_id = int(item.get("id", 0) or 0)
        link_key = _normalize_subscription_candidate_link(item.get("link_url", ""))
        if provider == "quark":
            item_extra = item.get("extra") if isinstance(item.get("extra"), dict) else safe_json_loads(item.get("extra_json"), {})
            receive_code = normalize_receive_code(item.get("receive_code", "")) or normalize_receive_code(
                (item_extra or {}).get("receive_code", "")
            )
            share_key = _build_subscription_quark_share_dedupe_key(
                link_key,
                item.get("raw_text", ""),
                receive_code,
            )
            unique_key = f"share:{share_key}" if share_key else (f"id:{item_id}" if item_id > 0 else f"url:{link_key}")
        else:
            unique_key = f"id:{item_id}" if item_id > 0 else f"url:{link_key}"
        if unique_key in seen_persisted_keys:
            continue
        seen_persisted_keys.add(unique_key)
        deduped_persisted_items.append(item)
    persisted_items = deduped_persisted_items

    candidates: List[Dict[str, Any]] = []
    relaxed_candidates: List[Dict[str, Any]] = []
    scored_candidates: List[Dict[str, Any]] = []
    supported_items = 0
    unsupported_items = 0
    media_guard_filtered = 0
    media_guard_reasons: Dict[str, int] = {}
    season_guard_filtered = 0
    supported_link_types = {"quark"} if provider == "quark" else {"magnet", "115share"}
    media_type = str(task.get("media_type", "movie") or "movie").strip().lower()
    single_season_tv = media_type == "tv" and (not is_subscription_multi_season_mode(task))
    target_season = max(1, int(task.get("season", 1) or 1))
    title_blocked_candidates = 0
    quark_low_score_kept = 0
    quark_media_relaxed_pass = 0
    seen_quark_scored_keys: Set[str] = set()
    for item in persisted_items:
        link_url = str(item.get("link_url", "") or "").strip()
        link_type = resolve_resource_link_type(item.get("link_type", ""), link_url)
        if link_type not in supported_link_types:
            unsupported_items += 1
            continue
        media_match, media_reason = match_subscription_media_type(task, item)
        if not media_match:
            if provider == "quark" and media_type == "tv" and str(media_reason or "").strip() == "missing_episode_meta":
                # 夸克剧集标题经常只保留剧名，不带标准季集字段；此类候选交给后续标题/精细扫描再判定。
                quark_media_relaxed_pass += 1
            else:
                media_guard_filtered += 1
                reason_key = str(media_reason or "unknown").strip() or "unknown"
                media_guard_reasons[reason_key] = int(media_guard_reasons.get(reason_key, 0) or 0) + 1
                continue
        supported_items += 1
        item_id = int(item.get("id", 0) or 0)
        matched_before = has_subscription_match(task.get("name", ""), item_id)
        scored = (
            score_subscription_candidate_quark(task, item, query_tokens, last_episode)
            if provider == "quark"
            else score_subscription_candidate(task, item, query_tokens, last_episode)
        )
        if provider == "quark" and not bool(scored.get("title_match", False)):
            media_guard_filtered += 1
            title_blocked_candidates += 1
            reason_key = "title_mismatch"
            media_guard_reasons[reason_key] = int(media_guard_reasons.get(reason_key, 0) or 0) + 1
            continue
        if provider == "quark":
            item_extra = item.get("extra") if isinstance(item.get("extra"), dict) else safe_json_loads(item.get("extra_json"), {})
            receive_code = normalize_receive_code(item.get("receive_code", "")) or normalize_receive_code(
                (item_extra or {}).get("receive_code", "")
            )
            scored_share_key = _build_subscription_quark_share_dedupe_key(link_url, item.get("raw_text", ""), receive_code)
            if scored_share_key:
                if scored_share_key in seen_quark_scored_keys:
                    continue
                seen_quark_scored_keys.add(scored_share_key)
        if single_season_tv:
            candidate_season = max(0, int(scored.get("season", 0) or 0))
            if candidate_season > 0 and candidate_season != target_season:
                season_guard_filtered += 1
                continue
        if matched_before:
            # 电影保持“同资源仅命中一次”；电视剧允许历史命中资源再次进入候选，
            # 后续由目录缺失判定决定是否需要重导（覆盖手动删档、补档场景）。
            if media_type != "tv":
                continue
            if int(scored.get("episode", 0) or 0) <= 0 and int(scored.get("range_end", 0) or 0) <= 0:
                continue
            scored["matched_before"] = True
        scored_candidates.append(scored)
        keep_candidate = int(scored.get("score", 0) or 0) >= min_score
        if (not keep_candidate) and provider == "quark" and media_type == "tv" and bool(scored.get("title_match", False)):
            # quark 电视剧场景优先保证召回：标题命中即可入队，低分放在队尾处理。
            keep_candidate = True
            quark_low_score_kept += 1
            scored["low_score_fallback"] = True
        if not keep_candidate:
            if provider != "quark" and media_type == "tv":
                episode_no = int(scored.get("episode", 0) or 0)
                token_hits = int(scored.get("token_hits", 0) or 0)
                if episode_no > 0 and token_hits > 0:
                    relaxed_candidates.append(scored)
            continue
        candidates.append(scored)

    if media_type == "tv":
        candidates.sort(
            key=lambda candidate: (
                int(candidate.get("episode", 0) or 0),
                int(candidate.get("score", 0) or 0),
                get_resource_item_sort_key(candidate.get("item", {})),
            ),
            reverse=True,
        )
    else:
        candidates.sort(
            key=lambda candidate: (
                int(candidate.get("score", 0) or 0),
                get_resource_item_sort_key(candidate.get("item", {})),
            ),
            reverse=True,
        )
    scored_candidates.sort(
        key=lambda candidate: (
            int(candidate.get("score", 0) or 0),
            get_resource_item_sort_key(candidate.get("item", {})),
        ),
        reverse=True,
    )

    relaxed_score_mode = False
    if provider != "quark" and not candidates and media_type == "tv" and relaxed_candidates:
        relaxed_candidates.sort(
            key=lambda candidate: (
                int(candidate.get("episode", 0) or 0),
                int(candidate.get("score", 0) or 0),
                get_resource_item_sort_key(candidate.get("item", {})),
            ),
            reverse=True,
        )
        candidates = relaxed_candidates[: min(int(SUBSCRIPTION_115_SEARCH_CANDIDATE_LIMIT), len(relaxed_candidates))]
        relaxed_score_mode = True

    candidate_limit = (
        int(SUBSCRIPTION_QUARK_SEARCH_CANDIDATE_LIMIT)
        if provider == "quark"
        else int(SUBSCRIPTION_115_SEARCH_CANDIDATE_LIMIT)
    )
    return {
        "candidate": candidates[0] if candidates else {},
        "candidates": candidates[: min(candidate_limit, len(candidates))],
        "keywords": keywords,
        "errors": merged_errors,
        "stats": {
            "search_keywords": len(keywords),
            "searched_sources": searched_sources,
            "matched_channels": matched_channels,
            "pages_scanned": pages_scanned,
            "raw_items": len(all_items),
            "deduped_items": len(deduped_items),
            "persisted_items": len(persisted_items),
            "supported_items": supported_items,
            "unsupported_items": unsupported_items,
            "media_guard_filtered": media_guard_filtered,
            "media_guard_reasons": media_guard_reasons,
            "season_guard_filtered": season_guard_filtered,
            "target_season": target_season if single_season_tv else 0,
            "scored_items": len(scored_candidates),
            "scored_candidates": len(candidates),
            "relaxed_score_mode": relaxed_score_mode,
            "relaxed_candidates": len(relaxed_candidates),
            "search_errors": len(merged_errors),
            "best_score": int(scored_candidates[0].get("score", 0) or 0) if scored_candidates else 0,
            "provider": provider,
            "min_score": min_score,
            "title_blocked_candidates": title_blocked_candidates,
            "quark_low_score_kept": quark_low_score_kept,
            "quark_media_relaxed_pass": quark_media_relaxed_pass,
            "incremental_search_enabled": incremental_search_enabled,
            "incremental_stop_channels": incremental_stop_channels,
            "incremental_channel_watermarks_loaded": len(incremental_since_cursor_by_channel),
            "incremental_channel_watermarks_observed": len(observed_channel_watermarks),
            "incremental_channel_watermarks_error_channels": len(incremental_error_channels),
            "incremental_channel_watermarks_advanced": int(incremental_channels_advanced or 0),
            "channel_support_rows_updated": int(channel_support_rows_updated or 0),
        },
    }


def merge_subscription_search_results(
    fixed_result: Dict[str, Any],
    channel_result: Dict[str, Any],
) -> Dict[str, Any]:
    fixed_payload = fixed_result if isinstance(fixed_result, dict) else {}
    channel_payload = channel_result if isinstance(channel_result, dict) else {}

    def collect_candidates(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        candidate = payload.get("candidate")
        if isinstance(candidate, dict) and candidate:
            result.append(candidate)
        raw_candidates = payload.get("candidates")
        if isinstance(raw_candidates, list):
            for item in raw_candidates:
                if isinstance(item, dict) and item:
                    result.append(item)
        return result

    def build_candidate_key(candidate: Dict[str, Any]) -> str:
        item = candidate.get("item") if isinstance(candidate.get("item"), dict) else {}
        extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
        source_post_id = str(item.get("source_post_id", "") or extra.get("source_post_id", "")).strip()
        if source_post_id:
            return f"post:{source_post_id}"
        message_url = str(item.get("message_url", "")).strip()
        if message_url:
            return f"msg:{message_url}"
        link_url = str(item.get("link_url", "")).strip()
        if link_url:
            return f"link:{link_url}"
        title = str(item.get("title", "")).strip()
        raw_text = str(item.get("raw_text", "")).strip()
        return f"title:{title}|raw:{raw_text[:120]}"

    def merge_keywords(*payloads: Dict[str, Any]) -> List[str]:
        seen: Set[str] = set()
        merged: List[str] = []
        for payload in payloads:
            keywords = payload.get("keywords")
            if not isinstance(keywords, list):
                continue
            for token in keywords:
                text = str(token or "").strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                merged.append(text)
        return merged

    def merge_errors(*payloads: Dict[str, Any]) -> List[Dict[str, Any]]:
        merged_errors: List[Dict[str, Any]] = []
        seen: Set[str] = set()
        for payload in payloads:
            errors = payload.get("errors")
            if not isinstance(errors, list):
                continue
            for item in errors:
                if not isinstance(item, dict):
                    continue
                channel_id = str(item.get("channel_id", "")).strip()
                channel_name = str(item.get("name", "")).strip()
                message = str(item.get("message", "")).strip()
                if not message:
                    continue
                key = "|".join([channel_id, channel_name, message])
                if key in seen:
                    continue
                seen.add(key)
                merged_errors.append(
                    {
                        "channel_id": channel_id,
                        "name": channel_name,
                        "message": message,
                    }
                )
        return merged_errors

    fixed_candidates = collect_candidates(fixed_payload)
    channel_candidates = collect_candidates(channel_payload)
    merged_candidates: List[Dict[str, Any]] = []
    seen_candidate_keys: Set[str] = set()
    for candidate in fixed_candidates + channel_candidates:
        key = build_candidate_key(candidate)
        if not key or key in seen_candidate_keys:
            continue
        seen_candidate_keys.add(key)
        merged_candidates.append(candidate)

    fixed_stats = fixed_payload.get("stats") if isinstance(fixed_payload.get("stats"), dict) else {}
    channel_stats = channel_payload.get("stats") if isinstance(channel_payload.get("stats"), dict) else {}
    sum_stat_keys = (
        "search_keywords",
        "searched_sources",
        "matched_channels",
        "pages_scanned",
        "raw_items",
        "deduped_items",
        "persisted_items",
        "supported_items",
        "unsupported_items",
        "media_guard_filtered",
        "season_guard_filtered",
        "scored_items",
        "scored_candidates",
        "relaxed_candidates",
        "search_errors",
        "incremental_stop_channels",
        "incremental_channel_watermarks_loaded",
        "incremental_channel_watermarks_observed",
        "incremental_channel_watermarks_error_channels",
        "incremental_channel_watermarks_advanced",
        "channel_support_rows_updated",
    )
    merged_stats: Dict[str, Any] = {}
    for key in sum_stat_keys:
        merged_stats[key] = int(fixed_stats.get(key, 0) or 0) + int(channel_stats.get(key, 0) or 0)

    merged_reasons: Dict[str, int] = {}
    for part in [fixed_stats.get("media_guard_reasons", {}), channel_stats.get("media_guard_reasons", {})]:
        if not isinstance(part, dict):
            continue
        for reason_key, reason_count in part.items():
            reason_text = str(reason_key or "").strip()
            if not reason_text:
                continue
            merged_reasons[reason_text] = int(merged_reasons.get(reason_text, 0) or 0) + int(reason_count or 0)

    merged_stats["media_guard_reasons"] = merged_reasons
    merged_stats["target_season"] = max(
        int(fixed_stats.get("target_season", 0) or 0),
        int(channel_stats.get("target_season", 0) or 0),
    )
    merged_stats["relaxed_score_mode"] = bool(
        fixed_stats.get("relaxed_score_mode", False) or channel_stats.get("relaxed_score_mode", False)
    )
    merged_stats["incremental_search_enabled"] = bool(
        fixed_stats.get("incremental_search_enabled", False) or channel_stats.get("incremental_search_enabled", False)
    )
    merged_stats["best_score"] = max(
        int(fixed_stats.get("best_score", 0) or 0),
        int(channel_stats.get("best_score", 0) or 0),
    )
    merged_stats["fixed_candidate_count"] = len(fixed_candidates)
    merged_stats["channel_candidate_count"] = len(channel_candidates)
    merged_stats["channel_searched_sources"] = int(channel_stats.get("searched_sources", 0) or 0)
    merged_stats["channel_matched_channels"] = int(channel_stats.get("matched_channels", 0) or 0)
    merged_stats["channel_pages_scanned"] = int(channel_stats.get("pages_scanned", 0) or 0)
    merged_stats["channel_raw_items"] = int(channel_stats.get("raw_items", 0) or 0)
    merged_stats["channel_deduped_items"] = int(channel_stats.get("deduped_items", 0) or 0)
    merged_stats["channel_supported_items"] = int(channel_stats.get("supported_items", 0) or 0)
    merged_stats["channel_unsupported_items"] = int(channel_stats.get("unsupported_items", 0) or 0)

    provider = normalize_subscription_provider(
        channel_stats.get("provider", fixed_stats.get("provider", "115")),
        fallback="115",
    )
    candidate_limit = (
        int(SUBSCRIPTION_QUARK_SEARCH_CANDIDATE_LIMIT)
        if provider == "quark"
        else int(SUBSCRIPTION_115_SEARCH_CANDIDATE_LIMIT)
    )

    merged_errors = merge_errors(fixed_payload, channel_payload)
    merged_stats["search_errors"] = len(merged_errors)
    merged_stats["provider"] = provider

    return {
        "candidate": merged_candidates[0] if merged_candidates else {},
        "candidates": merged_candidates[: min(candidate_limit, len(merged_candidates))],
        "keywords": merge_keywords(fixed_payload, channel_payload),
        "errors": merged_errors,
        "stats": merged_stats,
    }


async def _run_subscription_task_quark(
    cfg: Dict[str, Any],
    task: Dict[str, Any],
    task_name: str,
    trigger: str,
    subscription_run_id: str,
    batch_refresh_enabled: bool,
    stage_timer: Optional[Dict[str, Any]] = None,
) -> None:
    await write_subscription_log("网盘提供方：夸克（独立评分与导入链路）", "info")
    await write_subscription_log(
        f"类型: {'电影' if task['media_type'] == 'movie' else '电视剧'} | 标题: {task['title']} | 保存路径: {task['savepath']}",
        "info",
    )
    await write_subscription_log(
        f"执行批次: {subscription_run_id} | 批次收口刷新: {'开启' if batch_refresh_enabled else '关闭（夸克独立链路）'}",
        "info",
    )
    if int(task.get("tmdb_id", 0) or 0) > 0:
        tmdb_label = str(task.get("tmdb_title", "") or task.get("title", "") or "--").strip()
        tmdb_year = normalize_tmdb_year(task.get("tmdb_year", ""))
        tmdb_tail = f" ({tmdb_year})" if tmdb_year else ""
        await write_subscription_log(
            f"TMDB 绑定: {tmdb_label}{tmdb_tail} | ID: {int(task.get('tmdb_id', 0) or 0)}",
            "info",
        )
    if task["media_type"] == "tv":
        configured_total = resolve_subscription_tv_total_episodes(task, state_total=0)
        tv_mode_text = "多季合一" if is_subscription_multi_season_mode(task) else "单季订阅"
        if is_subscription_anime_compatible_task(task):
            tv_mode_text += " / 动漫兼容"
        season_label = "全季" if is_subscription_multi_season_mode(task) else f"S{int(task.get('season', 1) or 1):02d}"
        await write_subscription_log(
            f"季: {season_label} | 总集数: {configured_total or '自动识别'} | 模式: {tv_mode_text}",
            "info",
        )
    check_subscription_cancelled()

    state = load_subscription_task_state(task_name, task.get("media_type", "movie"))
    last_episode = max(0, int(state.get("last_episode", 0) or 0))
    state_stats = state.get("stats", {}) if isinstance(state.get("stats"), dict) else {}
    if task["media_type"] == "tv" and bool(state_stats.get("existing_episode_scan_ready", False)):
        state_existing_max = max(0, int(state_stats.get("existing_episode_max", 0) or 0))
        state_existing_entries = max(0, int(state_stats.get("existing_episode_scanned_entries", 0) or 0))
        if state_existing_max > 0:
            last_episode = state_existing_max
        elif last_episode > 0 and state_existing_entries <= 0:
            last_episode = 0
    known_total = resolve_subscription_tv_total_episodes(
        task,
        state_total=max(0, int(state.get("total_episodes", 0) or 0)),
    )
    single_season_episode_upper_bound = (
        known_total
        if task["media_type"] == "tv" and known_total > 0 and (not is_subscription_multi_season_mode(task))
        else 0
    )
    if single_season_episode_upper_bound > 0 and last_episode > single_season_episode_upper_bound:
        last_episode = single_season_episode_upper_bound

    completed_locked = task["media_type"] == "tv" and known_total > 0 and last_episode >= known_total
    if completed_locked:
        await write_subscription_log(
            f"当前记录为已完结（{last_episode}/{known_total}），本次仍会检查启用频道是否有重发/更优资源",
            "warn",
        )

    upsert_subscription_task_state(task_name, status="running", progress=15, detail="正在主动搜索夸克资源")
    check_subscription_cancelled()
    _subscription_stage_timer_enter(stage_timer, "search")
    search_started_at = time.perf_counter()
    search_result = await find_subscription_task_match_candidate_by_search(
        task,
        last_episode=last_episode,
        trigger=trigger,
    )
    search_duration_seconds = max(0.0, time.perf_counter() - search_started_at)
    search_stats = search_result.get("stats", {}) if isinstance(search_result.get("stats"), dict) else {}
    search_errors = search_result.get("errors", []) if isinstance(search_result.get("errors"), list) else []
    search_keywords = search_result.get("keywords", []) if isinstance(search_result.get("keywords"), list) else []
    searched_sources = int(search_stats.get("searched_sources", 0) or 0)
    matched_channels = int(search_stats.get("matched_channels", 0) or 0)
    pages_scanned = int(search_stats.get("pages_scanned", 0) or 0)
    deduped_items = int(search_stats.get("deduped_items", 0) or 0)
    supported_items = int(search_stats.get("supported_items", 0) or 0)
    unsupported_items = int(search_stats.get("unsupported_items", 0) or 0)
    await write_subscription_log(
        f"夸克搜索关键词: " + " / ".join(search_keywords or [str(task.get("title", "")).strip() or "--"]),
        "info",
    )
    await write_subscription_log(
        (
            f"夸克搜索完成：频道检索 {searched_sources} 次，命中频道 {matched_channels} 个，"
            f"扫描页面 {pages_scanned} 页，候选资源 {deduped_items} 条，可导入资源 {supported_items} 条"
        ),
        "info",
    )
    await write_subscription_log(f"夸克搜索阶段耗时：{_format_elapsed_seconds(search_duration_seconds)}", "info")
    if unsupported_items > 0:
        await write_subscription_log(
            f"已过滤 {unsupported_items} 条非夸克链接（当前 provider=quark，仅支持夸克分享）",
            "warn",
        )
    if int(search_stats.get("title_blocked_candidates", 0) or 0) > 0:
        await write_subscription_log(
            f"已拦截 {int(search_stats.get('title_blocked_candidates', 0) or 0)} 条“仅集数命中/标题不匹配”候选",
            "warn",
        )
    if int(search_stats.get("quark_media_relaxed_pass", 0) or 0) > 0:
        await write_subscription_log(
            f"已放行 {int(search_stats.get('quark_media_relaxed_pass', 0) or 0)} 条“标题命中但无集数标记”候选，待后续精细扫描判定",
            "info",
        )
    if int(search_stats.get("quark_low_score_kept", 0) or 0) > 0:
        await write_subscription_log(
            f"已保留 {int(search_stats.get('quark_low_score_kept', 0) or 0)} 条低于阈值但标题命中的电视剧候选（召回优先）",
            "info",
        )
    if bool(search_stats.get("incremental_search_enabled", False)):
        await write_subscription_log(
            (
                f"频道增量搜索已启用：加载水位 {int(search_stats.get('incremental_channel_watermarks_loaded', 0) or 0)} 个，"
                f"命中增量边界 {int(search_stats.get('incremental_stop_channels', 0) or 0)} 个频道，"
                f"推进水位 {int(search_stats.get('incremental_channel_watermarks_advanced', 0) or 0)} 个频道，"
                f"异常未推进 {int(search_stats.get('incremental_channel_watermarks_error_channels', 0) or 0)} 个频道"
            ),
            "info",
        )
    if int(search_stats.get("channel_support_rows_updated", 0) or 0) > 0:
        await write_subscription_log(
            f"频道支持度统计已更新 {int(search_stats.get('channel_support_rows_updated', 0) or 0)} 个频道",
            "info",
        )
    if search_errors:
        await write_subscription_log(
            f"有 {len(search_errors)} 个频道搜索异常（不影响其余频道）："
            + "；".join(
                [
                    (
                        f"{str(err.get('name', '') or err.get('channel_id', '未知频道')).strip()}:"
                        f"{str(err.get('message', '')).strip()}"
                    )[:120]
                    for err in search_errors[:3]
                ]
            ),
            "warn",
        )

    upsert_subscription_task_state(task_name, status="running", progress=25, detail="候选准备完成，正在匹配评分")
    check_subscription_cancelled()
    ranked_candidates = search_result.get("candidates", []) if isinstance(search_result.get("candidates"), list) else []
    if not ranked_candidates:
        legacy_candidate = search_result.get("candidate", {}) if isinstance(search_result.get("candidate"), dict) else {}
        if legacy_candidate:
            ranked_candidates = [legacy_candidate]
    if not ranked_candidates:
        _subscription_stage_timer_enter(stage_timer, "finalize")
        if completed_locked:
            detail = f"已完结（{last_episode}/{known_total}），未发现可更新资源"
            status = "completed"
        elif searched_sources <= 0:
            detail = "未启用任何 TG 订阅源，请先在参数配置里启用频道后重试"
            status = "waiting"
        elif supported_items <= 0:
            detail = "命中资源均非夸克分享链接，请调整频道或关键词"
            status = "waiting"
        elif int(search_stats.get("title_blocked_candidates", 0) or 0) > 0 and int(search_stats.get("scored_items", 0) or 0) <= 0:
            detail = (
                f"已拦截标题不匹配候选 {int(search_stats.get('title_blocked_candidates', 0) or 0)} 条，"
                "当前暂无可导入资源"
            )
            status = "waiting"
        else:
            detail = (
                f"主动搜索未命中（夸克阈值 {int(SUBSCRIPTION_QUARK_MIN_SCORE or 60)}，"
                f"候选 {int(search_stats.get('deduped_items', 0) or 0)} 条，"
                f"最高分 {int(search_stats.get('best_score', 0) or 0)}）"
            )
            status = "waiting"
        upsert_subscription_task_state(
            task_name,
            media_type=task.get("media_type", "movie"),
            status=status,
            progress=100,
            detail=detail,
            stats={
                "matched": False,
                "provider": "quark",
                "run_id": subscription_run_id,
                "batch_refresh_enabled": batch_refresh_enabled,
                "last_episode": last_episode,
                "total_episodes": known_total,
                **search_stats,
            },
        )
        await write_subscription_log(detail, "warn" if status == "waiting" else "info")
        update_subscription_summary("等待资源" if status == "waiting" else "已完成", detail)
        return

    base_savepath = normalize_relative_path(str(task.get("savepath", "")).strip())
    effective_savepath = base_savepath
    if task["media_type"] == "movie":
        movie_folder = sanitize_115_folder_name(
            f"{task.get('title', '')} {task.get('year', '')}".strip() or "未命名电影",
            fallback="未命名电影",
        )
        effective_savepath = join_relative_path(base_savepath, movie_folder)
    elif task["media_type"] == "tv":
        effective_savepath = resolve_subscription_tv_base_savepath(task, base_savepath) or base_savepath
    check_subscription_cancelled()

    _subscription_stage_timer_enter(stage_timer, "calibrate")
    upsert_subscription_task_state(task_name, status="running", progress=45, detail="正在准备夸克目标目录")
    cookie_quark = str(cfg.get("cookie_quark", "")).strip()
    folder_id = await asyncio.to_thread(
        ensure_quark_folder_id_by_path,
        cookie_quark,
        effective_savepath,
    )

    existing_folder_episodes: Set[int] = set()
    existing_episode_scan_stats: Dict[str, Any] = {}
    existing_episode_scan_ready = False
    if task["media_type"] == "tv":
        upsert_subscription_task_state(task_name, status="running", progress=47, detail="正在读取夸克目标目录已落盘剧集")
        try:
            scan_result = await asyncio.to_thread(
                _scan_quark_existing_tv_episodes,
                cookie_quark,
                folder_id,
                task,
            )
            scan_episodes = scan_result.get("episodes", []) if isinstance(scan_result.get("episodes"), list) else []
            existing_folder_episodes = _clamp_episode_values(
                {max(0, int(item or 0)) for item in scan_episodes if max(0, int(item or 0)) > 0},
                episode_upper_bound=single_season_episode_upper_bound,
            )
            existing_episode_scan_stats = {
                "existing_episode_scan_ready": True,
                "existing_episode_count": len(existing_folder_episodes),
                "existing_episode_max": max(existing_folder_episodes) if existing_folder_episodes else 0,
                "existing_episode_scanned_dirs": int(scan_result.get("scanned_dirs", 0) or 0),
                "existing_episode_scanned_entries": int(scan_result.get("scanned_entries", 0) or 0),
                "existing_episode_failed_dirs": int(scan_result.get("failed_dirs", 0) or 0),
                "existing_episode_scan_truncated": bool(scan_result.get("truncated", False)),
            }
            existing_episode_scan_ready = True
            if existing_folder_episodes:
                await write_subscription_log(
                    (
                        f"夸克目标目录已识别 {len(existing_folder_episodes)} 集（最高 E{max(existing_folder_episodes)}，"
                        f"样例 {_format_episode_preview(existing_folder_episodes)}）"
                    ),
                    "info",
                )
            else:
                await write_subscription_log(
                    (
                        f"夸克目标目录未识别到已落盘剧集（扫描目录 {int(scan_result.get('scanned_dirs', 0) or 0)} 个，"
                        f"条目 {int(scan_result.get('scanned_entries', 0) or 0)} 条）"
                    ),
                    "info",
                )
            if int(scan_result.get("failed_dirs", 0) or 0) > 0:
                await write_subscription_log(
                    f"夸克目录扫描有 {int(scan_result.get('failed_dirs', 0) or 0)} 个子目录读取失败，已自动忽略",
                    "warn",
                )
            if bool(scan_result.get("truncated", False)):
                await write_subscription_log("夸克目录扫描达到上限，已截断后续子目录（避免单次执行过慢）", "warn")
            corrected_last_episode = max(existing_folder_episodes) if existing_folder_episodes else last_episode
            if existing_folder_episodes:
                corrected_last_episode = max(existing_folder_episodes)
            elif int(existing_episode_scan_stats.get("existing_episode_scanned_entries", 0) or 0) <= 0:
                corrected_last_episode = 0
            if corrected_last_episode != last_episode:
                previous_last_episode = last_episode
                last_episode = corrected_last_episode
                completed_locked = task["media_type"] == "tv" and known_total > 0 and last_episode >= known_total
                upsert_subscription_task_state(
                    task_name,
                    media_type=task.get("media_type", "movie"),
                    last_episode=last_episode,
                    total_episodes=known_total,
                )
                await write_subscription_log(
                    f"已按夸克目标目录校准追更进度：E{previous_last_episode} -> E{last_episode}",
                    "info",
                )
        except Exception as exc:
            existing_episode_scan_stats = {"existing_episode_scan_ready": False}
            await write_subscription_log(f"读取夸克目标目录已落盘剧集失败，回退历史进度判断：{exc}", "warn")

    baseline_last_episode = last_episode
    attempt_candidates = ranked_candidates
    ranked_candidate_count = len(ranked_candidates)
    pre_title_hint_candidate_count = ranked_candidate_count
    title_hint_missing_targets: Set[int] = set()
    title_hint_filtered_candidates = 0
    if task["media_type"] == "tv" and existing_episode_scan_ready:
        attempt_candidates = _prioritize_tv_candidates_by_missing_episodes(
            ranked_candidates,
            existing_folder_episodes,
            last_episode,
            prefer_backfill=(str(trigger or "").strip().lower() == "manual"),
            episode_upper_bound=single_season_episode_upper_bound,
        )
        pre_title_hint_candidate_count = len(attempt_candidates)
    if task["media_type"] == "tv":
        attempt_candidates = _prioritize_quark_tv_candidates_for_precise_scan(
            attempt_candidates,
            existing_folder_episodes if existing_episode_scan_ready else set(),
            episode_upper_bound=single_season_episode_upper_bound,
        )
    if task["media_type"] == "tv" and existing_episode_scan_ready:
        title_hint_missing_targets = _compute_quark_tv_title_missing_targets(
            existing_folder_episodes,
            last_episode,
            episode_upper_bound=single_season_episode_upper_bound,
        )
        filtered_candidates, filtered_count = _filter_quark_tv_candidates_by_title_missing_episodes(
            attempt_candidates,
            title_hint_missing_targets,
            episode_upper_bound=single_season_episode_upper_bound,
        )
        attempt_candidates = filtered_candidates
        title_hint_filtered_candidates = filtered_count
        if filtered_count > 0:
            await write_subscription_log(
                (
                    f"已按标题集数缺失集初筛移除 {filtered_count} 条候选"
                    f"（缺失 {_format_episode_preview(title_hint_missing_targets)}）"
                ),
                "info",
            )

    attempt_budget = SUBSCRIPTION_QUARK_MAX_ATTEMPTS if task["media_type"] == "tv" else min(16, SUBSCRIPTION_QUARK_MAX_ATTEMPTS)
    max_attempts = max(1, min(attempt_budget, len(attempt_candidates)))
    if task["media_type"] == "tv":
        await write_subscription_log(
            (
                f"夸克候选统计：初始 {ranked_candidate_count} 条，优先级重排后 {pre_title_hint_candidate_count} 条，"
                f"标题缺失集初筛后 {len(attempt_candidates)} 条，本轮最多尝试 {max_attempts} 条"
            ),
            "info",
        )
    import_timeout_seconds = max(10, int(SUBSCRIPTION_IMPORT_TIMEOUT_SECONDS or 90))
    attempted_candidates = 0
    scanned_candidates = 0
    failed_attempts = 0
    timed_out_attempts = 0
    skipped_existing_candidates = 0
    skipped_episode_candidates = 0
    skipped_precise_mismatch_candidates = 0
    last_failed_detail = ""
    selected_candidate: Dict[str, Any] = {}
    selected_item: Dict[str, Any] = {}
    selected_job_id = 0
    selected_job_savepath = effective_savepath
    imported_episodes: Set[int] = set()
    successful_job_ids: List[int] = []
    max_total_detected = 0
    savepath_folder_id_cache: Dict[str, str] = {effective_savepath: str(folder_id or "").strip()}
    seen_candidate_share_keys: Set[str] = set()
    quark_manifest_cache: Dict[str, Dict[str, Any]] = {}

    def consume_background_task_result(task_obj: asyncio.Task) -> None:
        try:
            task_obj.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    _subscription_stage_timer_enter(stage_timer, "import")
    candidate_queue = list(attempt_candidates)
    queue_index = 0
    while queue_index < len(candidate_queue):
        if attempted_candidates >= max_attempts:
            break
        index = queue_index + 1
        candidate = candidate_queue[queue_index]
        queue_index += 1
        scanned_candidates += 1
        check_subscription_cancelled()
        item = candidate.get("item", {}) if isinstance(candidate.get("item"), dict) else {}
        resource_id = int(item.get("id", 0) or 0)
        if resource_id <= 0:
            continue

        score = int(candidate.get("score", 0) or 0)
        episode = max(0, int(candidate.get("episode", 0) or 0))
        total_detected = max(0, int(candidate.get("total", 0) or 0))
        candidate_season = max(0, int(candidate.get("season", 0) or 0))
        candidate_episode_values = _candidate_episode_values(
            candidate,
            episode_upper_bound=single_season_episode_upper_bound,
        )
        candidate_has_range_hint = (
            max(0, int(candidate.get("range_start", 0) or 0)) > 0
            and max(0, int(candidate.get("range_end", 0) or 0)) > 0
        )
        episode_label = _format_candidate_episode_label(candidate)
        candidate_link_url = _normalize_subscription_candidate_link(item.get("link_url", ""))
        candidate_link_type = resolve_resource_link_type(item.get("link_type", ""), candidate_link_url)
        if candidate_link_type != "quark":
            continue
        item_extra = item.get("extra") if isinstance(item.get("extra"), dict) else safe_json_loads(item.get("extra_json"), {})
        candidate_receive_code = normalize_receive_code(item.get("receive_code", "")) or normalize_receive_code(
            (item_extra or {}).get("receive_code", "")
        )
        candidate_share_key = _build_subscription_quark_share_dedupe_key(
            candidate_link_url,
            item.get("raw_text", ""),
            candidate_receive_code,
        )
        dedupe_key = candidate_share_key or f"url:{candidate_link_url.lower()}"
        if dedupe_key in seen_candidate_share_keys:
            continue
        seen_candidate_share_keys.add(dedupe_key)

        if (
            task["media_type"] == "tv"
            and single_season_episode_upper_bound > 0
            and episode > single_season_episode_upper_bound
            and not candidate_episode_values
        ):
            skipped_episode_candidates += 1
            await write_subscription_log(
                (
                    f"候选资源 #{index}（评分 {score}）集数 {episode_label} 超出单季总集数 "
                    f"E{single_season_episode_upper_bound}，已跳过"
                ),
                "warn",
            )
            continue

        if task["media_type"] == "tv" and candidate_episode_values and existing_episode_scan_ready and candidate_has_range_hint:
            if candidate_episode_values.issubset(existing_folder_episodes):
                skipped_existing_candidates += 1
                await write_subscription_log(
                    f"候选资源 #{index}（评分 {score}）集数 {episode_label} 夸克目录已全覆盖，已跳过",
                    "warn",
                )
                continue
            overlap_existing = any(episode_no in existing_folder_episodes for episode_no in candidate_episode_values)
            if overlap_existing:
                missing_for_candidate = _candidate_missing_episode_values(
                    candidate,
                    existing_folder_episodes,
                    episode_upper_bound=single_season_episode_upper_bound,
                )
                if missing_for_candidate:
                    await write_subscription_log(
                        (
                            f"候选资源 #{index} 与目录部分重叠（缺失 {_format_episode_preview(missing_for_candidate)}），"
                            "按夸克策略继续尝试导入"
                        ),
                        "info",
                    )

        candidate_savepath = effective_savepath
        if task["media_type"] == "tv":
            candidate_savepath = (
                build_subscription_tv_savepath(
                    task,
                    base_savepath,
                    season=candidate_season,
                    episode=episode,
                )
                or effective_savepath
            )

        selected_share_episode_values: Set[int] = set()
        selected_share_file_samples: List[str] = []
        precise_selection: Dict[str, Any] = {}
        if task["media_type"] == "tv":
            if (
                candidate_episode_values
                and last_episode > 0
                and max(candidate_episode_values) <= last_episode
                and (not existing_episode_scan_ready)
            ):
                skipped_existing_candidates += 1
                await write_subscription_log(
                    (
                        f"候选资源 #{index}（评分 {score}）集数 {episode_label} 不高于当前进度 E{last_episode}，"
                        "已跳过避免重复导入"
                    ),
                    "info",
                )
                continue

            precise_missing_episode_values = set(candidate_episode_values)
            if not precise_missing_episode_values and known_total > 0 and last_episode > 0:
                episode_upper = known_total
                if single_season_episode_upper_bound > 0:
                    episode_upper = min(episode_upper, single_season_episode_upper_bound)
                if episode_upper > last_episode:
                    precise_missing_episode_values = set(range(last_episode + 1, episode_upper + 1))

            if existing_episode_scan_ready and precise_missing_episode_values:
                precise_missing_episode_values = {
                    episode_no
                    for episode_no in precise_missing_episode_values
                    if episode_no not in existing_folder_episodes
                }

            if candidate_episode_values and not precise_missing_episode_values:
                skipped_existing_candidates += 1
                await write_subscription_log(
                    (
                        f"候选资源 #{index}（评分 {score}）集数 {episode_label} 与已落盘记录无缺失，"
                        "已跳过避免重复导入"
                    ),
                    "info",
                )
                continue

            if precise_missing_episode_values:
                precise_selection, precise_stats = await _build_tv_share_selection_for_missing_episodes(
                    cookie_quark,
                    task,
                    item,
                    precise_missing_episode_values,
                )
                precise_ids = (
                    precise_selection.get("selected_ids", [])
                    if isinstance(precise_selection.get("selected_ids"), list)
                    else []
                )
                fallback_used = False
                fallback_missing_episode_values: Set[int] = set()
                if not precise_ids:
                    reason = str((precise_stats or {}).get("reason", "") or "no_precise_episode_match").strip()
                    scanned_dirs = int((precise_stats or {}).get("scanned_dirs", 0) or 0)
                    scanned_entries = int((precise_stats or {}).get("scanned_entries", 0) or 0)
                    if reason == "no_precise_episode_match":
                        manifest_cache_key = candidate_share_key or candidate_link_url or f"resource:{resource_id}"
                        manifest_payload = quark_manifest_cache.get(manifest_cache_key)
                        if not manifest_payload:
                            manifest_payload = await _scan_subscription_share_tree_snapshot(
                                cookie_quark,
                                task,
                                item,
                                max_depth=5,
                                max_dirs=140,
                                max_entries=5000,
                                per_request_timeout=max(12, int(SUBSCRIPTION_SHARE_SCAN_REQUEST_TIMEOUT_SECONDS or 12)),
                                force_refresh=False,
                            )
                            quark_manifest_cache[manifest_cache_key] = manifest_payload
                        scanned_dirs = max(scanned_dirs, int((manifest_payload or {}).get("scanned_dirs", 0) or 0))
                        scanned_entries = max(scanned_entries, int((manifest_payload or {}).get("scanned_entries", 0) or 0))
                        manifest_episodes = _clamp_episode_values(
                            {
                                max(0, int(value or 0))
                                for value in (
                                    manifest_payload.get("covered_episodes", [])
                                    if isinstance(manifest_payload.get("covered_episodes"), list)
                                    else []
                                )
                                if max(0, int(value or 0)) > 0
                            },
                            episode_upper_bound=single_season_episode_upper_bound,
                        )
                        fallback_missing_episode_values = {
                            episode_no
                            for episode_no in manifest_episodes
                            if episode_no not in existing_folder_episodes
                        }
                        if fallback_missing_episode_values:
                            fallback_selection, fallback_stats = _build_tv_share_selection_from_manifest(
                                manifest_payload,
                                fallback_missing_episode_values,
                                task=task,
                            )
                            fallback_ids = (
                                fallback_selection.get("selected_ids", [])
                                if isinstance(fallback_selection.get("selected_ids"), list)
                                else []
                            )
                            if fallback_ids:
                                precise_selection = fallback_selection
                                precise_stats = fallback_stats
                                precise_ids = fallback_ids
                                fallback_used = True
                                reason = str((fallback_stats or {}).get("reason", "") or "manifest_fallback").strip()
                            else:
                                fallback_reason = str(
                                    (fallback_stats or {}).get("reason", "") or "manifest_no_precise_episode_match"
                                ).strip()
                                reason = f"{reason}->{fallback_reason}"
                        elif manifest_episodes:
                            reason = f"{reason}->manifest_no_missing"
                        else:
                            manifest_reason = str((manifest_payload or {}).get("reason", "") or "manifest_empty").strip()
                            reason = f"{reason}->{manifest_reason}"
                if not precise_ids:
                    skipped_precise_mismatch_candidates += 1
                    reason_label = _format_subscription_reason_chain(reason)
                    await write_subscription_log(
                        (
                            f"候选资源 #{index} 精细筛选未命中缺失集（目标 {_format_episode_preview(precise_missing_episode_values)}，"
                            f"原因 {reason_label}，扫描目录 {scanned_dirs} 个，条目 {scanned_entries} 条），已跳过整包导入"
                        ),
                        "warn",
                    )
                    continue
                selected_share_episode_values = {
                    max(0, int(value or 0))
                    for value in (
                        precise_stats.get("covered_episodes", [])
                        if isinstance(precise_stats, dict)
                    else []
                    )
                    if max(0, int(value or 0)) > 0
                }
                selected_share_file_samples = (
                    [str(sample or "").strip() for sample in (precise_stats.get("selected_file_samples", []) if isinstance(precise_stats, dict) else [])]
                )
                selected_share_file_samples = [sample for sample in selected_share_file_samples if sample]
                dedupe_hits = int((precise_stats or {}).get("duplicate_bucket_hits", 0) or 0)
                dedupe_tail = f"，同集/同范围已优选 {dedupe_hits} 条重复版本" if dedupe_hits > 0 else ""
                if fallback_used:
                    await write_subscription_log(
                        (
                            f"候选资源 #{index} 原目标 {_format_episode_preview(precise_missing_episode_values)} 未命中，"
                            f"已按清单回退识别 {_format_episode_preview(fallback_missing_episode_values)} 并筛选 "
                            f"{len(precise_ids)} 个文件后转存{dedupe_tail}"
                        ),
                        "info",
                    )
                else:
                    await write_subscription_log(
                        (
                            f"候选资源 #{index} 已按缺失集筛选 {len(precise_ids)} 个文件后转存"
                            f"（目标 {_format_episode_preview(precise_missing_episode_values)}）{dedupe_tail}"
                        ),
                        "info",
                    )

        attempted_candidates += 1
        candidate_folder_id = str(savepath_folder_id_cache.get(candidate_savepath, "") or "").strip()
        if not candidate_folder_id:
            candidate_folder_id = await asyncio.to_thread(
                ensure_quark_folder_id_by_path,
                cookie_quark,
                candidate_savepath,
            )
            savepath_folder_id_cache[candidate_savepath] = str(candidate_folder_id or "").strip()

        job_payload = {
            "folder_id": candidate_folder_id,
            "savepath": candidate_savepath,
            "sharetitle": "",
            "monitor_task_name": "",
            "refresh_delay_seconds": 0,
            "auto_refresh": False,
            "extra": {
                "job_source": "subscription_auto",
            },
        }
        if precise_selection:
            job_payload["share_selection"] = precise_selection

        job_id = create_resource_job(item, job_payload)
        if job_id <= 0:
            failed_attempts += 1
            last_failed_detail = "创建导入任务失败"
            await write_subscription_log(
                f"候选资源 #{index} 导入失败：{last_failed_detail}",
                "warn",
            )
            continue

        await write_subscription_log(
            (
                f"候选资源 #{index}（{episode_label}）已创建夸克导入任务 #{job_id}，开始执行："
                f"{str(item.get('title', '') or f'资源#{resource_id}').strip()[:96]}"
            ),
            "info",
        )

        job_runner = asyncio.create_task(run_resource_job(job_id))
        done, _ = await asyncio.wait({job_runner}, timeout=import_timeout_seconds)
        if not done:
            job_runner.add_done_callback(consume_background_task_result)
            job_runner.cancel()
            timed_out_attempts += 1
            timeout_detail = f"执行超时（>{import_timeout_seconds} 秒）"
            try:
                await cancel_resource_job(job_id, reason="timeout")
            except Exception:
                update_resource_job(
                    job_id,
                    status="failed",
                    status_detail=timeout_detail,
                    finished_at=now_text(),
                )
                if resource_id > 0:
                    conn = open_db()
                    update_resource_item_status(conn, resource_id, "failed")
                    conn.commit()
                    conn.close()
            failed_attempts += 1
            last_failed_detail = timeout_detail
            await write_subscription_log(
                f"候选资源 #{index} 导入超时：{timeout_detail}",
                "warn",
            )
            continue

        await job_runner
        latest_job = get_resource_job(job_id, include_private=True)
        latest_status = str((latest_job or {}).get("status", "") or "").strip().lower()
        if latest_status == "failed":
            failed_attempts += 1
            last_failed_detail = str((latest_job or {}).get("status_detail", "") or "资源导入失败").strip()
            if candidate_link_url and _is_subscription_invalid_link_error(last_failed_detail, candidate_link_type):
                _record_subscription_invalid_link_cache(
                    candidate_link_url,
                    candidate_link_type,
                    last_failed_detail,
                )
            await write_subscription_log(
                f"候选资源 #{index} 导入失败：{last_failed_detail}",
                "warn",
            )
            continue

        if task["media_type"] == "tv":
            try:
                verify_scan_result = await asyncio.to_thread(
                    _scan_quark_existing_tv_episodes,
                    cookie_quark,
                    candidate_folder_id,
                    task,
                )
                verify_scan_episodes = _clamp_episode_values(
                    {
                        max(0, int(value or 0))
                        for value in (
                            verify_scan_result.get("episodes", [])
                            if isinstance(verify_scan_result.get("episodes"), list)
                            else []
                        )
                        if max(0, int(value or 0)) > 0
                    },
                    episode_upper_bound=single_season_episode_upper_bound,
                )
                if verify_scan_episodes:
                    existing_folder_episodes.update(verify_scan_episodes)
                    existing_episode_scan_stats["existing_episode_scan_ready"] = True
                    existing_episode_scan_stats["existing_episode_count"] = len(existing_folder_episodes)
                    existing_episode_scan_stats["existing_episode_max"] = (
                        max(existing_folder_episodes) if existing_folder_episodes else 0
                    )
                    existing_episode_scan_stats["existing_episode_scanned_dirs"] = int(
                        verify_scan_result.get("scanned_dirs", 0) or 0
                    )
                    existing_episode_scan_stats["existing_episode_scanned_entries"] = int(
                        verify_scan_result.get("scanned_entries", 0) or 0
                    )
                    existing_episode_scan_stats["existing_episode_failed_dirs"] = int(
                        verify_scan_result.get("failed_dirs", 0) or 0
                    )
                    existing_episode_scan_stats["existing_episode_scan_truncated"] = bool(
                        verify_scan_result.get("truncated", False)
                    )
                    if selected_share_episode_values:
                        verified_hits = _clamp_episode_values(
                            selected_share_episode_values.intersection(verify_scan_episodes),
                            episode_upper_bound=single_season_episode_upper_bound,
                        )
                        if verified_hits:
                            await write_subscription_log(
                                f"候选资源 #{index} 转存后目录复核命中 {_format_episode_preview(verified_hits)}",
                                "info",
                            )
            except Exception as exc:
                await write_subscription_log(
                    f"候选资源 #{index} 转存后目录复核失败（已忽略，不影响本次任务）：{exc}",
                    "warn",
                )

        create_subscription_match(
            task_name=task_name,
            resource_id=resource_id,
            job_id=job_id,
            media_type=task.get("media_type", "movie"),
            season=candidate_season if candidate_season > 0 else max(1, int(task.get("season", 1) or 1)),
            episode=episode,
            total_episodes=total_detected,
            score=score,
        )
        successful_job_ids.append(job_id)
        if not selected_candidate:
            selected_candidate = candidate
            selected_item = item
            selected_job_id = job_id
            selected_job_savepath = candidate_savepath
        else:
            selected_episode = max(0, int(selected_candidate.get("episode", 0) or 0))
            selected_score = int(selected_candidate.get("score", 0) or 0)
            if episode > selected_episode or (episode == selected_episode and score > selected_score):
                selected_candidate = candidate
                selected_item = item
                selected_job_id = job_id
                selected_job_savepath = candidate_savepath
        max_total_detected = max(max_total_detected, total_detected)
        recorded_episode_values = _resolve_recorded_episode_values(
            candidate,
            selected_share_episode_values,
            episode_upper_bound=single_season_episode_upper_bound,
        )
        if recorded_episode_values:
            imported_episodes.update(recorded_episode_values)
            if existing_episode_scan_ready:
                existing_folder_episodes.update(recorded_episode_values)
                existing_episode_scan_stats["existing_episode_count"] = len(existing_folder_episodes)
                existing_episode_scan_stats["existing_episode_max"] = (
                    max(existing_folder_episodes) if existing_folder_episodes else 0
                )
        await write_subscription_log(
            (
                f"候选资源 #{index} 导入成功：{str(item.get('title', '') or f'资源#{resource_id}').strip()}"
                f"（评分 {score}）"
                f"{'，命中 ' + _format_episode_preview(recorded_episode_values) if recorded_episode_values else ''}"
                f"{'，文件：' + '；'.join(selected_share_file_samples[:8]) if selected_share_file_samples else ''}"
            ),
            "success",
        )
        if task["media_type"] == "tv" and existing_episode_scan_ready:
            remaining_candidates = candidate_queue[queue_index:]
            refreshed_missing_targets = _compute_quark_tv_title_missing_targets(
                existing_folder_episodes,
                last_episode,
                episode_upper_bound=single_season_episode_upper_bound,
            )
            filtered_remaining, filtered_remaining_count = _filter_quark_tv_candidates_by_title_missing_episodes(
                remaining_candidates,
                refreshed_missing_targets,
                episode_upper_bound=single_season_episode_upper_bound,
            )
            remaining_candidates = filtered_remaining
            if filtered_remaining_count > 0:
                candidate_queue = candidate_queue[:queue_index] + remaining_candidates
                await write_subscription_log(
                    (
                        f"候选资源 #{index} 转存后按缺失集继续收敛：移除 {filtered_remaining_count} 条标题不含缺失集候选"
                        f"（剩余缺失 {_format_episode_preview(refreshed_missing_targets)}）"
                    ),
                    "info",
                )
            pruned_remaining, pruned_count = _prune_tv_candidates_without_new_episodes(
                remaining_candidates,
                existing_folder_episodes,
                episode_upper_bound=single_season_episode_upper_bound,
            )
            if pruned_count > 0:
                candidate_queue = candidate_queue[:queue_index] + pruned_remaining
                await write_subscription_log(
                    f"候选资源 #{index} 转存后已移除 {pruned_count} 条无新增集数候选，减少后续精细扫描开销",
                    "info",
                )
            prioritized_remaining = _prioritize_quark_tv_candidates_for_precise_scan(
                candidate_queue[queue_index:],
                existing_folder_episodes,
                episode_upper_bound=single_season_episode_upper_bound,
            )
            candidate_queue = candidate_queue[:queue_index] + prioritized_remaining
        if (
            task["media_type"] == "tv"
            and single_season_episode_upper_bound > 0
            and existing_episode_scan_ready
        ):
            target_episodes = set(range(1, single_season_episode_upper_bound + 1))
            if target_episodes.issubset(existing_folder_episodes):
                await write_subscription_log(
                    f"夸克目录已覆盖单季全部 E1-E{single_season_episode_upper_bound}，结束本轮候选尝试",
                    "info",
                )
                break
        if task["media_type"] != "tv":
            break

    _subscription_stage_timer_enter(stage_timer, "finalize")
    if not selected_candidate:
        if attempted_candidates <= 0:
            skip_reasons: List[str] = []
            if skipped_existing_candidates > 0:
                skip_reasons.append(f"目录已覆盖 {skipped_existing_candidates} 条")
            if skipped_episode_candidates > 0:
                skip_reasons.append(f"超范围旧集 {skipped_episode_candidates} 条")
            if skipped_precise_mismatch_candidates > 0:
                skip_reasons.append(f"精细识别未命中 {skipped_precise_mismatch_candidates} 条")
            if skip_reasons:
                detail = f"候选资源暂不可导入（{'，'.join(skip_reasons)}），等待新集发布"
            else:
                detail = "候选资源暂不可用，等待下次自动重试"
        elif failed_attempts > 0:
            detail = f"已尝试 {attempted_candidates} 个候选资源均失败，等待下次自动重试"
            if last_failed_detail:
                detail += f"（最近失败：{last_failed_detail[:80]}）"
            if timed_out_attempts > 0:
                detail += f"（超时 {timed_out_attempts} 条）"
        else:
            detail = "候选资源暂不可用，等待下次自动重试"
        if skipped_precise_mismatch_candidates > 0 and attempted_candidates > 0:
            detail += f"（精细识别未命中 {skipped_precise_mismatch_candidates} 条）"
        upsert_subscription_task_state(
            task_name,
            media_type=task.get("media_type", "movie"),
            status="waiting",
            progress=100,
            detail=detail,
            stats={
                "matched": False,
                "provider": "quark",
                "run_id": subscription_run_id,
                "batch_refresh_enabled": batch_refresh_enabled,
                "last_episode": last_episode,
                "total_episodes": known_total,
                "attempted_candidates": attempted_candidates,
                "failed_attempts": failed_attempts,
                "timed_out_attempts": timed_out_attempts,
                "skipped_existing_candidates": skipped_existing_candidates,
                "skipped_episode_candidates": skipped_episode_candidates,
                "skipped_precise_mismatch_candidates": skipped_precise_mismatch_candidates,
                "title_hint_filtered_candidates": title_hint_filtered_candidates,
                "title_hint_missing_targets": sorted(title_hint_missing_targets)[:120],
                "scanned_candidates": scanned_candidates,
                "max_attempts": max_attempts,
                **existing_episode_scan_stats,
                **search_stats,
            },
        )
        await write_subscription_log(detail, "warn")
        update_subscription_summary("等待资源", detail)
        return

    candidate = selected_candidate
    item = selected_item
    resource_id = int(item.get("id", 0) or 0)
    score = int(candidate.get("score", 0) or 0)
    episode = max(0, int(candidate.get("episode", 0) or 0))
    total_detected = max(0, int(candidate.get("total", 0) or 0))
    selected_season = max(0, int(candidate.get("season", 0) or 0))
    job_id = int(selected_job_id or 0)
    normalized_successful_job_ids = sorted({max(0, int(value or 0)) for value in successful_job_ids if max(0, int(value or 0)) > 0})
    if job_id <= 0 and normalized_successful_job_ids:
        job_id = normalized_successful_job_ids[0]
    successful_count = len(normalized_successful_job_ids) if normalized_successful_job_ids else (1 if job_id > 0 else 0)
    imported_episode_list = sorted(imported_episodes)
    matched_display_title = pick_subscription_display_title(task, item, fallback=f"资源#{resource_id}")

    next_episode = last_episode
    if task["media_type"] == "tv" and imported_episode_list:
        next_episode = max(last_episode, imported_episode_list[-1])
    elif task["media_type"] == "tv" and episode > 0:
        next_episode = max(last_episode, episode)
    next_total = known_total or max_total_detected or total_detected
    if task["media_type"] == "tv" and (max_total_detected > 0 or total_detected > 0):
        _sync_task_total_episodes(task_name, max_total_detected or total_detected)

    if successful_count > 1:
        detail = (
            f"命中「{matched_display_title}」（评分 {score}），本轮已执行 {successful_count} 个夸克导入任务"
            f"（首个 #{job_id}），保存到 {selected_job_savepath}；夸克链路不触发监控刷新"
        )
    else:
        detail = (
            f"命中「{matched_display_title}」（评分 {score}），已创建并执行夸克导入任务 #{job_id}，"
            f"保存到 {selected_job_savepath}；夸克链路不触发监控刷新"
        )
    upsert_subscription_task_state(
        task_name,
        media_type=task.get("media_type", "movie"),
        status="completed",
        progress=100,
        detail=detail,
        last_success_at=now_text(),
        last_error="",
        last_episode=next_episode,
        total_episodes=next_total,
        matched_resource_id=resource_id,
        matched_resource_title=matched_display_title,
        matched_score=score,
        queued_job_id=job_id,
        stats={
            "matched": True,
            "provider": "quark",
            "run_id": subscription_run_id,
            "batch_refresh_enabled": batch_refresh_enabled,
            "score": score,
            "token_hits": int(candidate.get("token_hits", 0) or 0),
            "token_total": int(candidate.get("token_total", 0) or 0),
            "episode": episode,
            "season": selected_season,
            "total_episodes": next_total,
            "job_id": job_id,
            "job_ids": normalized_successful_job_ids or ([job_id] if job_id > 0 else []),
            "auto_refresh": False,
            "matched_count": max(1, successful_count),
            "imported_episode_count": len(imported_episode_list),
            "imported_episodes": imported_episode_list[:80],
            "attempted_candidates": attempted_candidates,
            "failed_attempts": failed_attempts,
            "timed_out_attempts": timed_out_attempts,
            "skipped_existing_candidates": skipped_existing_candidates,
            "skipped_episode_candidates": skipped_episode_candidates,
            "title_hint_filtered_candidates": title_hint_filtered_candidates,
            "title_hint_missing_targets": sorted(title_hint_missing_targets)[:120],
            "scanned_candidates": scanned_candidates,
            "max_attempts": max_attempts,
            **existing_episode_scan_stats,
            **search_stats,
        },
    )
    await write_subscription_log(detail, "success")
    try:
        notify_result = await push_subscription_success_notification(
            cfg=cfg,
            task=task,
            item=item,
            effective_savepath=selected_job_savepath,
            job_id=job_id,
            successful_count=max(1, successful_count),
            imported_episode_list=imported_episode_list,
            baseline_last_episode=baseline_last_episode,
            next_episode=next_episode,
        )
        if bool(notify_result.get("pushed", False)):
            channel = str(notify_result.get("channel", "") or "").strip().lower()
            channel_label = "企业微信应用 API" if channel == "wecom_app" else "企业微信群机器人"
            notified_episodes = (
                notify_result.get("episodes", [])
                if isinstance(notify_result.get("episodes"), list)
                else []
            )
            if notified_episodes:
                await write_subscription_log(
                    f"更新通知已推送到{channel_label}（新增 {len(notified_episodes)} 集）",
                    "info",
                )
            else:
                await write_subscription_log(f"更新通知已推送到{channel_label}", "info")
    except Exception as notify_exc:
        await write_subscription_log(f"订阅成功通知推送失败：{notify_exc}", "warn")
    update_subscription_summary("执行成功", detail)


async def run_subscription_task(task_name: str, trigger: str = "manual") -> None:
    cfg = get_config()
    task = _load_subscription_task(cfg, task_name)
    if not task:
        await write_subscription_log(f"任务不存在: {task_name}", "error")
        return
    config_error = validate_subscription_runtime_config(cfg, task)
    if config_error:
        await write_subscription_log(f"任务配置错误: {config_error}", "error")
        upsert_subscription_task_state(task_name, status="failed", detail=config_error, last_error=config_error)
        update_subscription_summary("任务失败", config_error)
        return
    provider = normalize_subscription_provider(task.get("provider", "115"), fallback="115")
    subscription_run_id = _build_subscription_run_id(task_name)
    # 批次收口刷新改为固定内置策略，不再由设置项切换。
    batch_refresh_enabled = provider == "115"

    if subscription_status["running"]:
        return

    ensure_db()
    recovered_jobs = {
        "checked": 0,
        "stale": 0,
        "recovered": 0,
        "triggered_groups": 0,
        "triggered_jobs": 0,
        "skipped_no_monitor": 0,
        "skipped_missing_monitor": 0,
    }
    if batch_refresh_enabled:
        recovered_jobs = _recover_subscription_submitted_jobs(limit=160)
        if int(recovered_jobs.get("recovered", 0) or 0) > 0:
            await write_subscription_log(
                (
                    f"已自动收口历史待刷新任务 {int(recovered_jobs.get('recovered', 0) or 0)} 条："
                    f"触发监控 {int(recovered_jobs.get('triggered_groups', 0) or 0)} 组 / "
                    f"跳过（未纳入监控）{int(recovered_jobs.get('skipped_no_monitor', 0) or 0)} 条 / "
                    f"跳过（监控任务不存在）{int(recovered_jobs.get('skipped_missing_monitor', 0) or 0)} 条"
                ),
                "info",
            )
    subscription_status["running"] = True
    subscription_status["current_task"] = task_name
    subscription_control["cancel"] = False
    subscription_last_run[task_name] = time.time()
    update_subscription_summary("准备执行", f"{task_name} ({trigger})")
    schedule_ui_state_push(0)
    run_started_at = now_text()
    upsert_subscription_task_state(
        task_name,
        media_type=task.get("media_type", "movie"),
        status="running",
        progress=5,
        detail=f"开始执行（{format_subscription_trigger(trigger)}）",
        last_run_at=run_started_at,
        last_error="",
        stats={
            "run_id": subscription_run_id,
            "batch_refresh_enabled": batch_refresh_enabled,
        },
    )
    share_runtime_cache_token = _subscription_share_entry_runtime_cache_var.set({})
    share_refreshed_keys_token = _subscription_share_entry_refreshed_keys_var.set(set())
    subscription_log_context_token = set_subscription_log_context(
        {
            "run_id": subscription_run_id,
            "task_name": task_name,
            "provider": provider,
            "media_type": str(task.get("media_type", "movie") or "movie"),
            "trigger": str(trigger or "").strip().lower() or "manual",
        }
    )
    stage_timer = _create_subscription_stage_timer("prepare")

    try:
        await write_subscription_log(
            f"━━━━━━━━━━【订阅开始 | {task_name} | {format_subscription_trigger(trigger)}】━━━━━━━━━━",
            "task-divider",
        )
        await write_subscription_log(
            f"类型: {'电影' if task['media_type'] == 'movie' else '电视剧'} | 标题: {task['title']} | 保存路径: {task['savepath']}",
            "info",
        )
        if provider == "quark":
            await _run_subscription_task_quark(
                cfg=cfg,
                task=task,
                task_name=task_name,
                trigger=trigger,
                subscription_run_id=subscription_run_id,
                batch_refresh_enabled=batch_refresh_enabled,
                stage_timer=stage_timer,
            )
            return
        await write_subscription_log(
            f"网盘提供方：115（频道搜索与导入链路） | 类型: {'电影' if task['media_type'] == 'movie' else '电视剧'}",
            "info",
        )
        task_share_subdir = normalize_relative_path(str(task.get("share_subdir", "") or "").strip())
        task_share_subdir_cid = _normalize_subscription_share_subdir_cid(task.get("share_subdir_cid", ""))
        task_share_link_url = str(task.get("share_link_url", "") or "").strip()
        task_share_link_receive_code = normalize_receive_code(task.get("share_link_receive_code", ""))
        task_share_link_type = resolve_resource_link_type("", task_share_link_url)
        use_fixed_share_link = bool(task_share_link_url) and task_share_link_type == "115share"
        fixed_link_channel_search_enabled = use_fixed_share_link and bool(task.get("fixed_link_channel_search", False))
        if task_share_subdir_cid and (not use_fixed_share_link):
            # CID 仅对固定分享链接稳定有效，频道搜索模式下忽略。
            task_share_subdir_cid = ""
        task_share_scope_enabled = bool(task_share_subdir or task_share_subdir_cid)
        task_share_scope_label = _format_subscription_share_scope_label(task_share_subdir, task_share_subdir_cid)
        if task_share_link_url and (not use_fixed_share_link):
            await write_subscription_log(
                "固定链接已配置但不是 115 分享链接，已自动忽略并回退频道搜索",
                "warn",
            )
        if use_fixed_share_link:
            await write_subscription_log(
                "固定链接模式已启用：将直接使用配置的 115 分享链接，不再依赖频道搜索",
                "info",
            )
            if fixed_link_channel_search_enabled:
                await write_subscription_log(
                    "固定链接补搜已启用：固定链接候选后会再执行一次频道搜索作为兜底",
                    "info",
                )
        if task_share_scope_enabled:
            await write_subscription_log(
                f"115 分享子目录已启用：{task_share_scope_label}（仅在该目录内扫描和转存）",
                "info",
            )
        await write_subscription_log(
            f"执行批次: {subscription_run_id} | 批次收口刷新: 开启（内置固定）",
            "info",
        )
        if int(task.get("tmdb_id", 0) or 0) > 0:
            tmdb_label = str(task.get("tmdb_title", "") or task.get("title", "") or "--").strip()
            tmdb_year = normalize_tmdb_year(task.get("tmdb_year", ""))
            tmdb_tail = f" ({tmdb_year})" if tmdb_year else ""
            await write_subscription_log(
                f"TMDB 绑定: {tmdb_label}{tmdb_tail} | ID: {int(task.get('tmdb_id', 0) or 0)}",
                "info",
            )
        if task["media_type"] == "tv":
            configured_total = resolve_subscription_tv_total_episodes(task, state_total=0)
            tv_mode_text = "多季合一" if is_subscription_multi_season_mode(task) else "单季订阅"
            if is_subscription_anime_compatible_task(task):
                tv_mode_text += " / 动漫兼容"
            season_label = "全季" if is_subscription_multi_season_mode(task) else f"S{int(task.get('season', 1) or 1):02d}"
            await write_subscription_log(
                f"季: {season_label} | 总集数: {configured_total or '自动识别'} | 模式: {tv_mode_text}",
                "info",
            )
        check_subscription_cancelled()

        state = load_subscription_task_state(task_name, task.get("media_type", "movie"))
        last_episode = max(0, int(state.get("last_episode", 0) or 0))
        state_stats = state.get("stats", {}) if isinstance(state.get("stats"), dict) else {}
        if task["media_type"] == "tv" and bool(state_stats.get("existing_episode_scan_ready", False)):
            state_existing_max = max(0, int(state_stats.get("existing_episode_max", 0) or 0))
            state_existing_entries = max(0, int(state_stats.get("existing_episode_scanned_entries", 0) or 0))
            if state_existing_max > 0:
                last_episode = state_existing_max
            elif last_episode > 0 and state_existing_entries <= 0:
                last_episode = 0
        known_total = resolve_subscription_tv_total_episodes(
            task,
            state_total=max(0, int(state.get("total_episodes", 0) or 0)),
        )
        single_season_episode_upper_bound = (
            known_total
            if task["media_type"] == "tv" and known_total > 0 and (not is_subscription_multi_season_mode(task))
            else 0
        )
        if single_season_episode_upper_bound > 0 and last_episode > single_season_episode_upper_bound:
            last_episode = single_season_episode_upper_bound

        completed_locked = task["media_type"] == "tv" and known_total > 0 and last_episode >= known_total

        if completed_locked:
            await write_subscription_log(
                f"当前记录为已完结（{last_episode}/{known_total}），本次仍会检查启用频道是否有重发/更优资源",
                "warn",
            )

        upsert_subscription_task_state(
            task_name,
            status="running",
            progress=15,
            detail=(
                "正在校验固定分享链接并准备频道补搜"
                if (use_fixed_share_link and fixed_link_channel_search_enabled)
                else ("正在校验固定分享链接" if use_fixed_share_link else "正在主动搜索启用频道资源")
            ),
        )
        check_subscription_cancelled()
        _subscription_stage_timer_enter(stage_timer, "search")
        search_started_at = time.perf_counter()
        search_result: Dict[str, Any] = {}
        if use_fixed_share_link:
            fixed_link_url = apply_share_receive_code_to_url(task_share_link_url, task_share_link_receive_code)
            fixed_item = {
                "id": 0,
                "title": str(task.get("title", "") or task_name or "固定分享链接").strip() or "固定分享链接",
                "link_url": fixed_link_url,
                "link_type": "115share",
                "message_url": "",
                "source_post_id": "",
                "raw_text": fixed_link_url,
                "receive_code": task_share_link_receive_code,
                "extra": {
                    "receive_code": task_share_link_receive_code,
                },
            }
            fixed_candidate = {
                "item": fixed_item,
                "score": 100,
                "episode": 0,
                "season": 0,
                "total": 0,
                "range_start": 0,
                "range_end": 0,
                "resolution": 0,
                "token_hits": 0,
            }
            search_result = {
                "candidate": fixed_candidate,
                "candidates": [fixed_candidate],
                "keywords": ["fixed-share-link"],
                "errors": [],
                "stats": {
                    "search_keywords": 0,
                    "searched_sources": 0,
                    "matched_channels": 0,
                    "pages_scanned": 0,
                    "raw_items": 0,
                    "deduped_items": 1,
                    "persisted_items": 0,
                    "supported_items": 1,
                    "unsupported_items": 0,
                    "media_guard_filtered": 0,
                    "media_guard_reasons": {},
                    "season_guard_filtered": 0,
                    "target_season": 0,
                    "scored_items": 1,
                    "scored_candidates": 1,
                    "relaxed_score_mode": False,
                    "relaxed_candidates": 0,
                    "search_errors": 0,
                    "best_score": 100,
                },
            }
            if fixed_link_channel_search_enabled:
                await write_subscription_log(
                    "固定链接候选已生成，正在执行频道补搜",
                    "info",
                )
                channel_search_result = await find_subscription_task_match_candidate_by_search(
                    task,
                    last_episode=last_episode,
                    trigger=trigger,
                )
                search_result = merge_subscription_search_results(search_result, channel_search_result)
        else:
            search_result = await find_subscription_task_match_candidate_by_search(
                task,
                last_episode=last_episode,
                trigger=trigger,
            )
        search_duration_seconds = max(0.0, time.perf_counter() - search_started_at)
        search_stats = search_result.get("stats", {}) if isinstance(search_result.get("stats"), dict) else {}
        search_errors = search_result.get("errors", []) if isinstance(search_result.get("errors"), list) else []
        search_keywords = search_result.get("keywords", []) if isinstance(search_result.get("keywords"), list) else []
        if use_fixed_share_link:
            await write_subscription_log(
                f"固定链接候选已就绪：{task_share_link_url}",
                "info",
            )
            if task_share_link_receive_code:
                await write_subscription_log("固定链接提取码已生效", "info")
        if (not use_fixed_share_link) or fixed_link_channel_search_enabled:
            search_label = "频道补搜" if (use_fixed_share_link and fixed_link_channel_search_enabled) else "主动搜索"
            searched_sources = int(
                (
                    search_stats.get("channel_searched_sources", search_stats.get("searched_sources", 0))
                    if (use_fixed_share_link and fixed_link_channel_search_enabled)
                    else search_stats.get("searched_sources", 0)
                )
                or 0
            )
            matched_channels = int(
                (
                    search_stats.get("channel_matched_channels", search_stats.get("matched_channels", 0))
                    if (use_fixed_share_link and fixed_link_channel_search_enabled)
                    else search_stats.get("matched_channels", 0)
                )
                or 0
            )
            pages_scanned = int(
                (
                    search_stats.get("channel_pages_scanned", search_stats.get("pages_scanned", 0))
                    if (use_fixed_share_link and fixed_link_channel_search_enabled)
                    else search_stats.get("pages_scanned", 0)
                )
                or 0
            )
            deduped_items = int(
                (
                    search_stats.get("channel_deduped_items", search_stats.get("deduped_items", 0))
                    if (use_fixed_share_link and fixed_link_channel_search_enabled)
                    else search_stats.get("deduped_items", 0)
                )
                or 0
            )
            supported_items = int(
                (
                    search_stats.get("channel_supported_items", search_stats.get("supported_items", 0))
                    if (use_fixed_share_link and fixed_link_channel_search_enabled)
                    else search_stats.get("supported_items", 0)
                )
                or 0
            )
            unsupported_items = int(
                (
                    search_stats.get("channel_unsupported_items", search_stats.get("unsupported_items", 0))
                    if (use_fixed_share_link and fixed_link_channel_search_enabled)
                    else search_stats.get("unsupported_items", 0)
                )
                or 0
            )
            await write_subscription_log(
                f"{search_label}关键词: " + " / ".join(search_keywords or [str(task.get("title", "")).strip() or "--"]),
                "info",
            )
            await write_subscription_log(
                (
                    f"{search_label}完成：频道检索 {searched_sources} 次，"
                    f"命中频道 {matched_channels} 个，"
                    f"扫描页面 {pages_scanned} 页，"
                    f"候选资源 {deduped_items} 条，"
                    f"可导入资源 {supported_items} 条"
                ),
                "info",
            )
            await write_subscription_log(
                f"{search_label}阶段耗时：{_format_elapsed_seconds(search_duration_seconds)}",
                "info",
            )
            if unsupported_items > 0:
                await write_subscription_log(
                    f"已过滤 {unsupported_items} 条不支持链接（仅支持 magnet / 115 分享）",
                    "warn",
                )
            if int(search_stats.get("media_guard_filtered", 0) or 0) > 0:
                media_reasons = search_stats.get("media_guard_reasons", {}) if isinstance(search_stats.get("media_guard_reasons"), dict) else {}
                reason_labels = {
                    "episode_like": "电影命中剧集资源",
                    "tv_like": "电影命中电视剧关键词",
                    "movie_like": "电视剧命中电影资源",
                    "missing_episode_meta": "电视剧缺少季集信息",
                }
                reason_text = "，".join(
                    f"{reason_labels.get(str(key), str(key))} {int(value or 0)} 条"
                    for key, value in media_reasons.items()
                    if int(value or 0) > 0
                )
                await write_subscription_log(
                    f"类型强分区已过滤 {int(search_stats.get('media_guard_filtered', 0) or 0)} 条非目标类型资源"
                    + (f"（{reason_text}）" if reason_text else ""),
                    "warn",
                )
            if int(search_stats.get("season_guard_filtered", 0) or 0) > 0:
                await write_subscription_log(
                    (
                        f"单季强过滤：已过滤 {int(search_stats.get('season_guard_filtered', 0) or 0)} 条季号不匹配资源"
                        f"（目标 S{int(search_stats.get('target_season', 0) or 0):02d}）"
                    ),
                    "warn",
                )
            if bool(search_stats.get("relaxed_score_mode", False)):
                await write_subscription_log(
                    (
                        f"评分放宽模式已启用：有 {int(search_stats.get('relaxed_candidates', 0) or 0)} 条电视剧候选因阈值过低未达标，"
                        "已改为先尝试候选再按集数去重判断"
                    ),
                    "warn",
                )
            if bool(search_stats.get("incremental_search_enabled", False)):
                await write_subscription_log(
                    (
                        f"频道增量搜索已启用：加载水位 {int(search_stats.get('incremental_channel_watermarks_loaded', 0) or 0)} 个，"
                        f"命中增量边界 {int(search_stats.get('incremental_stop_channels', 0) or 0)} 个频道，"
                        f"推进水位 {int(search_stats.get('incremental_channel_watermarks_advanced', 0) or 0)} 个频道，"
                        f"异常未推进 {int(search_stats.get('incremental_channel_watermarks_error_channels', 0) or 0)} 个频道"
                    ),
                    "info",
                )
            if int(search_stats.get("channel_support_rows_updated", 0) or 0) > 0:
                await write_subscription_log(
                    f"频道支持度统计已更新 {int(search_stats.get('channel_support_rows_updated', 0) or 0)} 个频道",
                    "info",
                )
            if search_errors:
                await write_subscription_log(
                    f"有 {len(search_errors)} 个频道搜索异常（不影响其余频道，{search_label}阶段）："
                    + "；".join(
                        [
                            (
                                f"{str(err.get('name', '') or err.get('channel_id', '未知频道')).strip()}:"
                                f"{str(err.get('message', '')).strip()}"
                            )[:120]
                            for err in search_errors[:3]
                        ]
                    ),
                    "warn",
                )

        upsert_subscription_task_state(task_name, status="running", progress=25, detail="候选准备完成，正在匹配评分")
        check_subscription_cancelled()
        ranked_candidates = search_result.get("candidates", []) if isinstance(search_result.get("candidates"), list) else []
        if not ranked_candidates:
            legacy_candidate = search_result.get("candidate", {}) if isinstance(search_result.get("candidate"), dict) else {}
            if legacy_candidate:
                ranked_candidates = [legacy_candidate]
        if not ranked_candidates:
            _subscription_stage_timer_enter(stage_timer, "finalize")
            if completed_locked:
                detail = f"已完结（{last_episode}/{known_total}），未发现可更新资源"
                status = "completed"
            elif use_fixed_share_link and fixed_link_channel_search_enabled:
                detail = "固定分享链接当前不可用，且频道补搜也未命中可导入资源，请检查固定链接/提取码或频道配置后重试"
                status = "waiting"
            elif use_fixed_share_link:
                detail = "固定分享链接当前不可用，请检查链接/提取码或稍后重试"
                status = "waiting"
            elif int(search_stats.get("searched_sources", 0) or 0) <= 0:
                detail = "未启用任何 TG 订阅源，请先在参数配置里启用频道后重试"
                status = "waiting"
            elif int(search_stats.get("supported_items", 0) or 0) <= 0:
                detail = "命中资源均非可导入类型（仅支持 magnet / 115 分享），请调整频道或关键词"
                status = "waiting"
            elif int(search_stats.get("media_guard_filtered", 0) or 0) > 0 and int(search_stats.get("scored_items", 0) or 0) <= 0:
                media_label = "电影" if task.get("media_type") == "movie" else "电视剧"
                detail = f"强分区已过滤非{media_label}资源 {int(search_stats.get('media_guard_filtered', 0) or 0)} 条，当前暂无符合类型的可导入资源"
                status = "waiting"
            elif int(search_stats.get("season_guard_filtered", 0) or 0) > 0 and int(search_stats.get("scored_items", 0) or 0) <= 0:
                detail = (
                    f"已过滤季号不匹配资源 {int(search_stats.get('season_guard_filtered', 0) or 0)} 条"
                    f"（目标 S{int(search_stats.get('target_season', 0) or 0):02d}），当前暂无可导入资源"
                )
                status = "waiting"
            else:
                detail = (
                    f"主动搜索未命中（阈值 {int(task.get('min_score', SUBSCRIPTION_MIN_SCORE) or SUBSCRIPTION_MIN_SCORE)}，"
                    f"候选 {int(search_stats.get('deduped_items', 0) or 0)} 条，"
                    f"最高分 {int(search_stats.get('best_score', 0) or 0)}）"
                )
                status = "waiting"
            upsert_subscription_task_state(
                task_name,
                media_type=task.get("media_type", "movie"),
                status=status,
                progress=100,
                detail=detail,
                stats={
                    "matched": False,
                    "run_id": subscription_run_id,
                    "batch_refresh_enabled": batch_refresh_enabled,
                    "last_episode": last_episode,
                    "total_episodes": known_total,
                    **search_stats,
                },
            )
            await write_subscription_log(detail, "warn" if status == "waiting" else "info")
            update_subscription_summary("等待资源" if status == "waiting" else "已完成", detail)
            return

        base_savepath = normalize_relative_path(str(task.get("savepath", "")).strip())
        effective_savepath = base_savepath
        if task["media_type"] == "movie":
            movie_folder = sanitize_115_folder_name(
                f"{task.get('title', '')} {task.get('year', '')}".strip() or "未命名电影",
                fallback="未命名电影",
            )
            effective_savepath = join_relative_path(base_savepath, movie_folder)
        elif task["media_type"] == "tv":
            effective_savepath = resolve_subscription_tv_base_savepath(task, base_savepath) or base_savepath
        check_subscription_cancelled()
        _subscription_stage_timer_enter(stage_timer, "calibrate")
        upsert_subscription_task_state(task_name, status="running", progress=45, detail="正在准备目标目录")
        cookie_115 = str(cfg.get("cookie_115", "")).strip()
        folder_id = await asyncio.to_thread(
            ensure_115_folder_id_by_path,
            cookie_115,
            effective_savepath,
        )
        matched_monitor = match_monitor_task_for_savepath(cfg, effective_savepath, provider=provider)
        monitor_task_name = str(matched_monitor.get("task_name", "") or "").strip()

        existing_folder_episodes: Set[int] = set()
        existing_episode_scan_stats: Dict[str, Any] = {}
        existing_episode_scan_ready = False
        existing_episode_scan_reliable = False
        episode_ledger_rows: Dict[int, Dict[str, Any]] = {}
        if task["media_type"] == "tv":
            upsert_subscription_task_state(task_name, status="running", progress=47, detail="正在读取目标目录已落盘剧集")
            try:
                scan_result = await asyncio.to_thread(
                    _scan_115_existing_tv_episodes,
                    cookie_115,
                    folder_id,
                    task,
                )
                scan_episodes = scan_result.get("episodes", []) if isinstance(scan_result.get("episodes"), list) else []
                existing_folder_episodes = _clamp_episode_values(
                    {max(0, int(item or 0)) for item in scan_episodes if max(0, int(item or 0)) > 0},
                    episode_upper_bound=single_season_episode_upper_bound,
                )
                existing_episode_scan_stats = {
                    "existing_episode_scan_ready": True,
                    "existing_episode_count": len(existing_folder_episodes),
                    "existing_episode_max": max(existing_folder_episodes) if existing_folder_episodes else 0,
                    "existing_episode_scanned_dirs": int(scan_result.get("scanned_dirs", 0) or 0),
                    "existing_episode_scanned_entries": int(scan_result.get("scanned_entries", 0) or 0),
                    "existing_episode_failed_dirs": int(scan_result.get("failed_dirs", 0) or 0),
                    "existing_episode_scan_truncated": bool(scan_result.get("truncated", False)),
                }
                existing_episode_scan_ready = True
                if existing_folder_episodes:
                    await write_subscription_log(
                        (
                            f"目标目录已识别 {len(existing_folder_episodes)} 集（最高 E{max(existing_folder_episodes)}，"
                            f"样例 {_format_episode_preview(existing_folder_episodes)}），本次按缺失集优先导入"
                        ),
                        "info",
                    )
                else:
                    await write_subscription_log(
                        (
                            f"目标目录未识别到已落盘剧集（扫描目录 {int(scan_result.get('scanned_dirs', 0) or 0)} 个，"
                            f"条目 {int(scan_result.get('scanned_entries', 0) or 0)} 条）"
                        ),
                        "info",
                    )
                if int(scan_result.get("failed_dirs", 0) or 0) > 0:
                    await write_subscription_log(
                        f"目标目录扫描有 {int(scan_result.get('failed_dirs', 0) or 0)} 个子目录读取失败，已自动忽略",
                        "warn",
                    )
                if bool(scan_result.get("truncated", False)):
                    await write_subscription_log("目标目录扫描达到上限，已截断后续子目录（避免单次执行过慢）", "warn")
            except Exception as exc:
                existing_episode_scan_stats = {"existing_episode_scan_ready": False}
                await write_subscription_log(f"读取目标目录已落盘剧集失败，回退历史进度判断：{exc}", "warn")
            episode_ledger_rows = load_subscription_episode_ledger(task_name, include_stale=True)
            if existing_episode_scan_ready:
                scan_scanned_dirs = int(existing_episode_scan_stats.get("existing_episode_scanned_dirs", 0) or 0)
                scan_failed_dirs = int(existing_episode_scan_stats.get("existing_episode_failed_dirs", 0) or 0)
                scan_reliable = not (scan_scanned_dirs <= 0 and scan_failed_dirs > 0)
                existing_episode_scan_reliable = scan_reliable
                if scan_reliable:
                    ledger_sync = reconcile_subscription_episode_ledger(task_name, existing_folder_episodes)
                    activated_count = max(0, int(ledger_sync.get("activated", 0) or 0))
                    staled_count = max(0, int(ledger_sync.get("staled", 0) or 0))
                    if activated_count > 0 or staled_count > 0:
                        await write_subscription_log(
                            f"集数账本已对账：恢复 {activated_count} 集 / 标记失效 {staled_count} 集",
                            "info",
                        )
                    episode_ledger_rows = load_subscription_episode_ledger(task_name, include_stale=True)
            active_ledger_count = sum(
                1
                for row in episode_ledger_rows.values()
                if str((row or {}).get("status", "active") or "active").strip().lower() == "active"
            )
            if active_ledger_count > 0:
                await write_subscription_log(f"集数账本已加载：活跃记录 {active_ledger_count} 集", "info")
            if existing_episode_scan_reliable:
                corrected_last_episode = last_episode
                if existing_folder_episodes:
                    corrected_last_episode = max(existing_folder_episodes)
                elif int(existing_episode_scan_stats.get("existing_episode_scanned_entries", 0) or 0) <= 0:
                    corrected_last_episode = 0
                if corrected_last_episode != last_episode:
                    previous_last_episode = last_episode
                    last_episode = corrected_last_episode
                    completed_locked = task["media_type"] == "tv" and known_total > 0 and last_episode >= known_total
                    upsert_subscription_task_state(
                        task_name,
                        media_type=task.get("media_type", "movie"),
                        last_episode=last_episode,
                        total_episodes=known_total,
                    )
                    await write_subscription_log(
                        f"已按目标目录校准追更进度：E{previous_last_episode} -> E{last_episode}",
                        "info",
                    )

        trigger_is_manual = str(trigger or "").strip().lower() == "manual"
        batch_episode_import = (
            task["media_type"] == "tv"
            and trigger_is_manual
        )
        attempt_candidates = ranked_candidates
        if task["media_type"] == "tv" and existing_episode_scan_ready:
            attempt_candidates = _prioritize_tv_candidates_by_missing_episodes(
                ranked_candidates,
                existing_folder_episodes,
                last_episode,
                prefer_backfill=trigger_is_manual,
                episode_upper_bound=single_season_episode_upper_bound,
            )
            if (not existing_folder_episodes) and single_season_episode_upper_bound > 0:
                await write_subscription_log(
                    f"单季首轮优化：已按 E1-E{single_season_episode_upper_bound} 覆盖度优先排序候选资源",
                    "info",
                )
            missing_episode_candidates = 0
            existing_episode_candidates = 0
            for candidate in attempt_candidates:
                episode_values = _candidate_episode_values(
                    candidate,
                    episode_upper_bound=single_season_episode_upper_bound,
                )
                if not episode_values:
                    continue
                missing_episode_values = _candidate_missing_episode_values(
                    candidate,
                    existing_folder_episodes,
                    episode_upper_bound=single_season_episode_upper_bound,
                )
                if not missing_episode_values:
                    existing_episode_candidates += 1
                else:
                    missing_episode_candidates += 1
            await write_subscription_log(
                (
                    f"目录集数匹配: 缺失集候选 {missing_episode_candidates} 条，"
                    f"目录已存在候选 {existing_episode_candidates} 条"
                ),
                "info",
            )
        if batch_episode_import:
            deduped_candidates: List[Dict[str, Any]] = []
            bucket_limit_per_episode = 3
            episode_bucket_counts: Dict[str, int] = {}
            for candidate in attempt_candidates:
                episode = max(0, int(candidate.get("episode", 0) or 0))
                range_start = max(0, int(candidate.get("range_start", 0) or 0))
                range_end = max(0, int(candidate.get("range_end", 0) or 0))
                bucket_key = ""
                if range_start > 0 and range_end > 0:
                    if range_end < range_start:
                        range_start, range_end = range_end, range_start
                    bucket_key = f"r:{range_start}-{range_end}"
                elif episode > 0:
                    bucket_key = f"e:{episode}"
                if bucket_key:
                    current_count = int(episode_bucket_counts.get(bucket_key, 0) or 0)
                    if current_count >= bucket_limit_per_episode:
                        continue
                    episode_bucket_counts[bucket_key] = current_count + 1
                deduped_candidates.append(candidate)
            with_episode_candidates = [item for item in deduped_candidates if int(item.get("episode", 0) or 0) > 0]
            without_episode_candidates = [item for item in deduped_candidates if int(item.get("episode", 0) or 0) <= 0]
            if with_episode_candidates:
                # 保留少量无集数候选兜底，避免合集文案无法标准解析时被整体丢弃。
                fallback_without_episode = without_episode_candidates[: min(3, len(without_episode_candidates))]
                attempt_candidates = with_episode_candidates + fallback_without_episode
            else:
                attempt_candidates = without_episode_candidates
            await write_subscription_log(
                f"手动追更批量模式：同集/同范围最多保留 {bucket_limit_per_episode} 条，候选 {len(attempt_candidates)} 条，本次最多尝试 {min(20, len(attempt_candidates))} 条",
                "info",
            )

        invalid_link_cache = (
            {}
            if (use_fixed_share_link and (not fixed_link_channel_search_enabled))
            else _load_subscription_invalid_link_cache(
                [
                    _normalize_subscription_candidate_link(
                        (candidate.get("item", {}) if isinstance(candidate.get("item"), dict) else {}).get("link_url", "")
                    )
                    for candidate in attempt_candidates
                ]
            )
        )
        if invalid_link_cache:
            await write_subscription_log(
                f"失效链接缓存命中 {len(invalid_link_cache)} 条，本次将自动跳过对应候选资源",
                "info",
            )

        max_attempts = max(1, min(20 if batch_episode_import else 8, len(attempt_candidates)))
        attempt_interval_seconds = max(0.0, float(SUBSCRIPTION_ATTEMPT_INTERVAL_SECONDS or 0))
        import_timeout_seconds = max(10, int(SUBSCRIPTION_IMPORT_TIMEOUT_SECONDS or 90))
        attempted_candidates = 0
        scanned_candidates = 0
        max_scan_candidates = max_attempts if task["media_type"] != "tv" else min(len(attempt_candidates), max_attempts * 8)
        failed_attempts = 0
        timed_out_attempts = 0
        skipped_episode_candidates = 0
        skipped_existing_candidates = 0
        skipped_ledger_candidates = 0
        skipped_invalid_candidates = 0
        skipped_subdir_candidates = 0
        last_failed_detail = ""
        selected_candidate: Dict[str, Any] = {}
        selected_item: Dict[str, Any] = {}
        selected_job_id = 0
        selected_auto_refresh = False
        selected_reused_existing = False
        selected_job_savepath = effective_savepath
        baseline_last_episode = last_episode
        imported_episodes: Set[int] = set()
        successful_count = 0
        max_total_detected = 0
        successful_job_ids: List[int] = []
        batch_created_job_ids: Set[int] = set()
        share_subdir_selection_cache: Dict[str, Dict[str, Any]] = {}
        share_subdir_selection_stats_cache: Dict[str, Dict[str, Any]] = {}
        fixed_share_runtime_initialized = False
        fixed_share_runtime_selection: Dict[str, Any] = {}
        fixed_share_runtime_subdir_stats: Dict[str, Any] = {}
        fixed_share_runtime_manifest: Dict[str, Any] = {}
        savepath_folder_id_cache: Dict[str, str] = {effective_savepath: str(folder_id or "").strip()}
        batch_refresh_result: Dict[str, Any] = {
            "run_id": subscription_run_id,
            "created_jobs": 0,
            "successful_jobs": 0,
            "refresh_eligible_jobs": 0,
            "grouped_targets": 0,
            "triggered_groups": 0,
            "triggered_jobs": 0,
            "missing_monitor_task_groups": 0,
            "missing_monitor_task_jobs": 0,
        }
        existing_episode_count = len(existing_folder_episodes)

        if max_attempts > 1 and (attempt_interval_seconds > 0 or import_timeout_seconds > 0):
            await write_subscription_log(
                (
                    f"候选执行策略：间隔 {attempt_interval_seconds:g} 秒，"
                    f"单候选超时 {import_timeout_seconds} 秒自动跳过"
                ),
                "info",
            )

        async def maybe_wait_between_attempts() -> None:
            if attempt_interval_seconds <= 0:
                return
            if attempted_candidates >= max_attempts:
                return
            if scanned_candidates >= max_scan_candidates:
                return
            check_subscription_cancelled()
            await asyncio.sleep(attempt_interval_seconds)

        async def rescan_existing_tv_episodes() -> Tuple[Dict[str, Any], Set[int]]:
            scan_result = await asyncio.to_thread(
                _scan_115_existing_tv_episodes,
                cookie_115,
                folder_id,
                task,
            )
            scan_episodes = {
                max(0, int(item or 0))
                for item in (
                    scan_result.get("episodes", [])
                    if isinstance(scan_result.get("episodes"), list)
                    else []
                )
                if max(0, int(item or 0)) > 0
            }
            normalized_scan_episodes = _clamp_episode_values(
                scan_episodes,
                episode_upper_bound=single_season_episode_upper_bound,
            )
            return scan_result, normalized_scan_episodes

        def consume_background_task_result(task: asyncio.Task) -> None:
            try:
                task.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        _subscription_stage_timer_enter(stage_timer, "import")
        for index, candidate in enumerate(attempt_candidates, start=1):
            if attempted_candidates >= max_attempts:
                break
            if scanned_candidates >= max_scan_candidates:
                break
            scanned_candidates += 1
            check_subscription_cancelled()
            item = candidate.get("item", {}) if isinstance(candidate.get("item"), dict) else {}
            resource_id = int(item.get("id", 0) or 0)
            if resource_id <= 0 and (not use_fixed_share_link):
                continue
            score = int(candidate.get("score", 0) or 0)
            episode = max(0, int(candidate.get("episode", 0) or 0))
            total_detected = max(0, int(candidate.get("total", 0) or 0))
            candidate_season = max(0, int(candidate.get("season", 0) or 0))
            range_start = max(0, int(candidate.get("range_start", 0) or 0))
            range_end = max(0, int(candidate.get("range_end", 0) or 0))
            candidate_episode_values = _candidate_episode_values(
                candidate,
                episode_upper_bound=single_season_episode_upper_bound,
            )
            episode_label = _format_candidate_episode_label(candidate)
            candidate_link_url = _normalize_subscription_candidate_link(item.get("link_url", ""))
            candidate_link_type = resolve_resource_link_type(item.get("link_type", ""), candidate_link_url)
            candidate_share_subdir_cid = task_share_subdir_cid if use_fixed_share_link else ""
            candidate_share_scope_label = _format_subscription_share_scope_label(
                task_share_subdir,
                candidate_share_subdir_cid,
            )
            candidate_savepath = effective_savepath
            if task["media_type"] == "tv":
                candidate_savepath = build_subscription_tv_savepath(
                    task,
                    base_savepath,
                    season=candidate_season,
                    episode=episode,
                ) or effective_savepath
            candidate_matched_monitor = match_monitor_task_for_savepath(cfg, candidate_savepath, provider=provider)
            candidate_monitor_task_name = str(candidate_matched_monitor.get("task_name", "") or "").strip()

            if (
                task["media_type"] == "tv"
                and single_season_episode_upper_bound > 0
                and (episode > single_season_episode_upper_bound or range_end > single_season_episode_upper_bound)
                and not candidate_episode_values
            ):
                skipped_episode_candidates += 1
                await write_subscription_log(
                    (
                        f"候选资源 #{index}（评分 {score}）集数 {episode_label} 超出单季总集数 "
                        f"E{single_season_episode_upper_bound}，已跳过"
                    ),
                    "warn",
                )
                continue

            cached_invalid_meta = invalid_link_cache.get(candidate_link_url) if candidate_link_url else None
            fixed_share_seed_candidate = (
                use_fixed_share_link
                and resource_id <= 0
                and candidate_link_type == "115share"
            )
            if cached_invalid_meta and (not fixed_share_seed_candidate):
                skipped_invalid_candidates += 1
                cache_reason = str(cached_invalid_meta.get("reason", "") or "").strip()
                expires_at = str(cached_invalid_meta.get("expires_at", "") or "").strip()
                reason_tail = f"（{cache_reason[:60]}）" if cache_reason else ""
                expire_tail = f"，有效期至 {expires_at}" if expires_at else ""
                await write_subscription_log(
                    f"候选资源 #{index} 链接命中失效缓存，已自动跳过{reason_tail}{expire_tail}",
                    "warn",
                )
                continue

            if task["media_type"] == "tv" and episode > 0:
                if candidate_episode_values and candidate_episode_values.issubset(imported_episodes):
                    skipped_episode_candidates += 1
                    await write_subscription_log(
                        f"候选资源 #{index}（评分 {score}）集数 {episode_label} 本轮已导入，继续尝试下一个",
                        "warn",
                    )
                    continue
                if existing_episode_scan_ready and candidate_episode_values and candidate_episode_values.issubset(existing_folder_episodes):
                    skipped_existing_candidates += 1
                    await write_subscription_log(
                        f"候选资源 #{index}（评分 {score}）集数 {episode_label} 目标目录已存在，继续尝试下一个",
                        "warn",
                    )
                    continue
                if existing_episode_scan_ready and candidate_episode_values:
                    overlap_existing = any(episode_no in existing_folder_episodes for episode_no in candidate_episode_values)
                    if overlap_existing:
                        missing_for_candidate = _candidate_missing_episode_values(
                            candidate,
                            existing_folder_episodes,
                            episode_upper_bound=single_season_episode_upper_bound,
                        )
                        if missing_for_candidate:
                            missing_ratio = len(missing_for_candidate) / max(1, len(candidate_episode_values))
                            # 非 115 分享资源无法做精细转存，若只缺很少集数，优先跳过避免整包重复。
                            if candidate_link_type != "115share" and missing_ratio <= 0.35:
                                skipped_existing_candidates += 1
                                await write_subscription_log(
                                    (
                                        f"候选资源 #{index}（评分 {score}）与目录重叠度较高（缺失占比 {missing_ratio:.0%}），"
                                        "当前链接不支持精细转存，已跳过整包避免重复集"
                                    ),
                                    "warn",
                                )
                                continue
                ledger_skip_reason = _candidate_episode_ledger_skip_reason(
                    candidate,
                    candidate_episode_values,
                    episode_ledger_rows,
                )
                if ledger_skip_reason:
                    skipped_ledger_candidates += 1
                    await write_subscription_log(
                        f"候选资源 #{index}（评分 {score}）{ledger_skip_reason}",
                        "warn",
                    )
                    continue
                is_old_episode = episode < baseline_last_episode
                is_same_episode_blocked = episode == baseline_last_episode and not completed_locked
                range_backfill_candidate = range_start > 0 and range_end > 0 and range_start < baseline_last_episode
                if (not existing_episode_scan_ready) and (is_old_episode or is_same_episode_blocked) and not range_backfill_candidate:
                    skipped_episode_candidates += 1
                    await write_subscription_log(
                        f"候选资源 #{index}（评分 {score}）集数重复 {episode_label}，当前进度 E{baseline_last_episode}，继续尝试下一个",
                        "warn",
                    )
                    continue

            attempted_candidates += 1
            upsert_subscription_task_state(
                task_name,
                status="running",
                progress=min(85, 48 + attempted_candidates * 6),
                detail=f"正在尝试候选资源 {attempted_candidates}/{max_attempts}",
            )

            pre_attempt_existing_episodes = set(existing_folder_episodes)
            resolved_subdir_selection: Dict[str, Any] = {}
            subdir_stats: Dict[str, Any] = {}
            if (
                use_fixed_share_link
                and task["media_type"] == "tv"
                and candidate_link_type == "115share"
                and (task_share_subdir or candidate_share_subdir_cid)
                and (not fixed_share_runtime_initialized)
            ):
                fixed_share_runtime_initialized = True
                runtime_subdir_started_at = time.perf_counter()
                fixed_share_runtime_selection, fixed_share_runtime_subdir_stats = await _build_subscription_share_subdir_selection(
                    cookie_115,
                    item,
                    task_share_subdir,
                    share_subdir_cid=candidate_share_subdir_cid,
                    force_refresh=True,
                    allow_fallback=False,
                )
                runtime_subdir_elapsed_seconds = max(0.0, time.perf_counter() - runtime_subdir_started_at)
                fixed_share_runtime_selection = normalize_share_selection_meta(fixed_share_runtime_selection)
                fixed_share_runtime_subdir_stats = dict(fixed_share_runtime_subdir_stats or {})
                runtime_selected_ids = (
                    fixed_share_runtime_selection.get("selected_ids", [])
                    if isinstance(fixed_share_runtime_selection.get("selected_ids"), list)
                    else []
                )
                if runtime_selected_ids:
                    runtime_manifest_started_at = time.perf_counter()
                    fixed_share_runtime_manifest = await _scan_subscription_share_episode_manifest(
                        cookie_115,
                        task,
                        item,
                        fixed_share_runtime_selection,
                        force_refresh=True,
                    )
                    runtime_manifest_elapsed_seconds = max(0.0, time.perf_counter() - runtime_manifest_started_at)
                else:
                    runtime_manifest_elapsed_seconds = 0.0
                runtime_subdir_reason_code = str((fixed_share_runtime_subdir_stats or {}).get("reason", "--") or "--").strip()
                runtime_subdir_reason_label = (
                    _format_subscription_reason_chain(runtime_subdir_reason_code)
                    if runtime_subdir_reason_code and runtime_subdir_reason_code != "--"
                    else "--"
                )
                await write_subscription_log(
                    (
                        f"固定链接运行期缓存已刷新：定位子目录 {_format_elapsed_seconds(runtime_subdir_elapsed_seconds)}，"
                        f"识别目录 {runtime_subdir_reason_label}，"
                        f"扫描目录 {int(fixed_share_runtime_manifest.get('scanned_dirs', 0) or 0)} 个，"
                        f"条目 {int(fixed_share_runtime_manifest.get('scanned_entries', 0) or 0)} 条，"
                        f"可识别剧集文件 {int(fixed_share_runtime_manifest.get('file_count', 0) or 0)} 个，"
                        f"扫描耗时 {_format_elapsed_seconds(runtime_manifest_elapsed_seconds)}，"
                        f"并发 {SUBSCRIPTION_SHARE_SCAN_CONCURRENCY}，"
                        f"限速 {SUBSCRIPTION_SHARE_SCAN_RATE_LIMIT_SECONDS:g}s"
                    ),
                    "info",
                )
            if candidate_link_type == "115share" and (task_share_subdir or candidate_share_subdir_cid):
                if use_fixed_share_link and fixed_share_runtime_initialized:
                    resolved_subdir_selection = fixed_share_runtime_selection
                    subdir_stats = fixed_share_runtime_subdir_stats
                else:
                    subdir_cache_key = f"{candidate_link_url or f'resource:{resource_id}'}|{task_share_subdir}|{candidate_share_subdir_cid}"
                    if subdir_cache_key in share_subdir_selection_cache:
                        resolved_subdir_selection = share_subdir_selection_cache.get(subdir_cache_key, {})
                        subdir_stats = share_subdir_selection_stats_cache.get(subdir_cache_key, {})
                    else:
                        resolved_subdir_selection, subdir_stats = await _build_subscription_share_subdir_selection(
                            cookie_115,
                            item,
                            task_share_subdir,
                            share_subdir_cid=candidate_share_subdir_cid,
                        )
                        share_subdir_selection_cache[subdir_cache_key] = resolved_subdir_selection
                        share_subdir_selection_stats_cache[subdir_cache_key] = subdir_stats

                selected_ids = (
                    resolved_subdir_selection.get("selected_ids", [])
                    if isinstance(resolved_subdir_selection.get("selected_ids"), list)
                    else []
                )
                subdir_reason = str((subdir_stats or {}).get("reason", "") or "").strip()
                if not selected_ids:
                    if subdir_reason == "target_is_share_root":
                        await write_subscription_log(
                            f"候选资源 #{index} 的分享子目录配置等于分享根目录，已回退为根目录导入",
                            "warn",
                        )
                    else:
                        skipped_subdir_candidates += 1
                        failed_segment = str((subdir_stats or {}).get("failed_segment", "") or "").strip()
                        sibling_samples = (
                            (subdir_stats or {}).get("sibling_dir_samples", [])
                            if isinstance((subdir_stats or {}).get("sibling_dir_samples", []), list)
                            else []
                        )
                        fallback_candidate_samples = (
                            (subdir_stats or {}).get("fallback_candidate_samples", [])
                            if isinstance((subdir_stats or {}).get("fallback_candidate_samples", []), list)
                            else []
                        )
                        fallback_reason = str((subdir_stats or {}).get("fallback_reason", "") or "").strip()
                        root_error = str((subdir_stats or {}).get("root_error", "") or "").strip()
                        root_retry_attempts = int((subdir_stats or {}).get("root_retry_attempts", 0) or 0)
                        anchor_error = str((subdir_stats or {}).get("anchor_error", "") or "").strip()
                        anchor_retry_attempts = int((subdir_stats or {}).get("anchor_retry_attempts", 0) or 0)
                        reason_tail = f"（{_format_subscription_reason_chain(subdir_reason)}）" if subdir_reason else ""
                        segment_tail = f"，未命中片段：{failed_segment}" if failed_segment else ""
                        sample_text = " / ".join(
                            [str(name or "").strip()[:80] for name in sibling_samples[:3] if str(name or "").strip()]
                        )
                        sample_tail = f"，同级目录示例：{sample_text}" if sample_text else ""
                        fallback_sample_text = " / ".join(
                            [str(name or "").strip()[:80] for name in fallback_candidate_samples[:3] if str(name or "").strip()]
                        )
                        fallback_tail = ""
                        if fallback_reason:
                            fallback_tail = f"，回溯匹配：{_format_subscription_reason_chain(fallback_reason)}"
                        if fallback_sample_text:
                            fallback_tail += f"，候选示例：{fallback_sample_text}"
                        root_tail = ""
                        if subdir_reason == "share_root_unreachable":
                            retry_tail = f"（已重试 {root_retry_attempts} 次）" if root_retry_attempts > 1 else ""
                            root_tail = f"，分享目录访问失败：{(root_error or '未知原因')[:140]}{retry_tail}"
                        if subdir_reason == "share_anchor_unreachable":
                            retry_tail = f"（已重试 {anchor_retry_attempts} 次）" if anchor_retry_attempts > 1 else ""
                            root_tail = f"，CID 目录访问失败：{(anchor_error or '未知原因')[:140]}{retry_tail}"
                        await write_subscription_log(
                            (
                                f"候选资源 #{index} 未命中订阅子目录「{candidate_share_scope_label}」，"
                                f"已跳过该候选{reason_tail}{segment_tail}{sample_tail}{fallback_tail}{root_tail}"
                            ),
                            "warn",
                        )
                        await maybe_wait_between_attempts()
                        continue
                if (
                    selected_ids
                    and candidate_link_type == "115share"
                    and task.get("media_type") == "tv"
                    and not (use_fixed_share_link and fixed_share_runtime_initialized)
                ):
                    refined_selection, refine_stats = await _refine_subscription_share_selection_for_task(
                        cookie_115,
                        item,
                        task,
                        resolved_subdir_selection,
                    )
                    refined_ids = (
                        refined_selection.get("selected_ids", [])
                        if isinstance(refined_selection.get("selected_ids"), list)
                        else []
                    )
                    refine_reason = str((refine_stats or {}).get("reason", "") or "").strip()
                    if refined_ids and refined_ids != selected_ids:
                        from_path = str((refine_stats or {}).get("from_path", "") or "").strip()
                        to_path = str((refine_stats or {}).get("to_path", "") or "").strip()
                        resolved_subdir_selection = refined_selection
                        selected_ids = refined_ids
                        await write_subscription_log(
                            (
                                f"候选资源 #{index} 订阅子目录已自动收敛："
                                f"{from_path or candidate_share_scope_label} -> {to_path or '--'}"
                            ),
                            "info",
                        )
                    else:
                        current_score = int((refine_stats or {}).get("current_score", 0) or 0)
                        best_score = int((refine_stats or {}).get("best_score", 0) or 0)
                        start_child_dirs = int((refine_stats or {}).get("start_child_dirs", 0) or 0)
                        candidate_samples = (
                            (refine_stats or {}).get("candidate_samples", [])
                            if isinstance((refine_stats or {}).get("candidate_samples", []), list)
                            else []
                        )
                        should_guard_skip = (
                            refine_reason in ("not_found", "ambiguous", "weak_match", "refine_selection_empty")
                            and current_score < 170
                            and start_child_dirs > 1
                        )
                        if should_guard_skip:
                            skipped_subdir_candidates += 1
                            sample_text = " / ".join(
                                [str(name or "").strip()[:80] for name in candidate_samples[:3] if str(name or "").strip()]
                            )
                            sample_tail = f"，候选示例：{sample_text}" if sample_text else ""
                            await write_subscription_log(
                                (
                                    f"候选资源 #{index} 子目录疑似合集目录，且未能安全收敛到剧集目录，"
                                    f"已跳过避免整包导入（{_format_subscription_reason_chain(refine_reason or 'unknown')}，"
                                    f"当前分 {current_score}，最佳候选分 {best_score}）{sample_tail}"
                                ),
                                "warn",
                            )
                            await maybe_wait_between_attempts()
                            continue

            candidate_folder_id = str(savepath_folder_id_cache.get(candidate_savepath, "") or "").strip()
            if not candidate_folder_id:
                candidate_folder_id = await asyncio.to_thread(
                    ensure_115_folder_id_by_path,
                    cookie_115,
                    candidate_savepath,
                )
                savepath_folder_id_cache[candidate_savepath] = str(candidate_folder_id or "").strip()

            existing = find_existing_resource_job(item, candidate_savepath)
            job_id = 0
            auto_refresh = bool(candidate_monitor_task_name)
            reused_existing = False
            selected_share_episode_values: Set[int] = set()
            selected_share_file_samples: List[str] = []
            candidate_success_records: List[Dict[str, Any]] = []
            if existing and use_fixed_share_link and candidate_link_type == "115share":
                existing = {}
                await write_subscription_log(
                    f"候选资源 #{index} 为固定分享链接模式，本次强制重新导入以捕捉目录更新",
                    "info",
                )
            if existing and candidate_link_type == "115share" and (task_share_subdir or candidate_share_subdir_cid):
                existing_extra = existing.get("extra") if isinstance(existing.get("extra"), dict) else {}
                existing_share_subdir = normalize_relative_path(
                    str(existing_extra.get("subscription_share_subdir", "") or "").strip()
                )
                existing_share_subdir_cid = _normalize_subscription_share_subdir_cid(
                    existing_extra.get("subscription_share_subdir_cid", "")
                )
                if existing_share_subdir != task_share_subdir or existing_share_subdir_cid != candidate_share_subdir_cid:
                    existing = {}
                    await write_subscription_log(
                        (
                            f"候选资源 #{index} 历史任务子目录策略不一致（旧: "
                            f"{_format_subscription_share_scope_label(existing_share_subdir, existing_share_subdir_cid)}），"
                            "改为重新导入"
                        ),
                        "info",
                    )
            if existing and task["media_type"] == "tv" and existing_episode_scan_ready:
                # 历史任务复用前先看目录是否仍缺集，避免“手动删文件后仍复用旧任务”。
                missing_for_candidate = _candidate_missing_episode_values(
                    candidate,
                    existing_folder_episodes,
                    episode_upper_bound=single_season_episode_upper_bound,
                )
                needs_reimport = bool(missing_for_candidate)
                if needs_reimport:
                    existing = {}
                    await write_subscription_log(
                        (
                            f"候选资源 #{index} 检测到目录仍缺失 "
                            f"{_format_episode_preview(missing_for_candidate)}，本次不复用历史任务，改为重新导入"
                        ),
                        "info",
                    )
            if existing:
                job_id = int(existing.get("id", 0) or 0)
                existing_status = str(existing.get("status", "") or "").strip().lower()
                if existing_status == "failed":
                    failed_attempts += 1
                    last_failed_detail = str(existing.get("status_detail", "") or f"任务 #{job_id} 失败").strip()
                    if (not use_fixed_share_link) and candidate_link_url and _is_subscription_invalid_link_error(last_failed_detail, candidate_link_type):
                        cache_meta = _record_subscription_invalid_link_cache(candidate_link_url, candidate_link_type, last_failed_detail)
                        if cache_meta:
                            invalid_link_cache[candidate_link_url] = cache_meta
                            await write_subscription_log(
                                f"候选资源 #{index} 链接已标记为失效，后续自动跳过（有效期至 {cache_meta.get('expires_at', '--')}）",
                                "warn",
                            )
                    await write_subscription_log(
                        f"候选资源 #{index} 历史任务 #{job_id} 失败：{last_failed_detail}，继续尝试下一个",
                        "warn",
                    )
                    await maybe_wait_between_attempts()
                    continue
                auto_refresh = bool(existing.get("auto_refresh"))
                reused_existing = True
                await write_subscription_log(f"候选资源 #{index} 命中历史任务 #{job_id}，复用执行记录", "warn")
                candidate_success_records.append(
                    {
                        "job_id": job_id,
                        "savepath": candidate_savepath,
                        "auto_refresh": auto_refresh,
                        "reused_existing": True,
                        "recorded_episode_values": _resolve_recorded_episode_values(
                            candidate,
                            set(),
                            episode_upper_bound=single_season_episode_upper_bound,
                        ),
                        "selected_file_samples": [],
                        "ledger_season": (
                            candidate_season
                            if candidate_season > 0
                            else (max(1, int(task.get("season", 1) or 1)) if not is_subscription_multi_season_mode(task) else 0)
                        ),
                    }
                )
            else:
                job_payload = {
                    "folder_id": candidate_folder_id,
                    "savepath": candidate_savepath,
                    "sharetitle": "",
                    "monitor_task_name": candidate_monitor_task_name,
                    "refresh_delay_seconds": 0,
                    "auto_refresh": bool(candidate_monitor_task_name) and (not batch_refresh_enabled),
                    "extra": {
                        "job_source": "subscription_auto",
                        "subscription_task_name": task_name,
                        "subscription_run_id": subscription_run_id,
                    },
                }
                if task_share_subdir:
                    job_payload["extra"]["subscription_share_subdir"] = task_share_subdir
                if candidate_share_subdir_cid:
                    job_payload["extra"]["subscription_share_subdir_cid"] = candidate_share_subdir_cid
                if use_fixed_share_link and candidate_link_type == "115share":
                    job_payload["extra"]["subscription_share_link_url"] = task_share_link_url
                    if task_share_link_receive_code:
                        job_payload["receive_code"] = task_share_link_receive_code
                if (
                    candidate_link_type == "115share"
                    and (
                        resolved_subdir_selection.get("selected_ids", [])
                        if isinstance(resolved_subdir_selection.get("selected_ids"), list)
                        else []
                    )
                ):
                    job_payload["share_selection"] = resolved_subdir_selection
                forced_precise_selection_applied = False
                if (
                    use_fixed_share_link
                    and candidate_link_type == "115share"
                    and task.get("media_type") == "tv"
                    and (task_share_subdir or candidate_share_subdir_cid)
                ):
                    precise_missing_episode_values: Set[int] = set()
                    if known_total > 0:
                        precise_missing_episode_values = set(range(1, known_total + 1))
                    elif single_season_episode_upper_bound > 0:
                        precise_missing_episode_values = set(range(1, single_season_episode_upper_bound + 1))
                    elif candidate_episode_values:
                        precise_missing_episode_values = set(candidate_episode_values)
                    if existing_episode_scan_ready and precise_missing_episode_values:
                        precise_missing_episode_values = {
                            episode_no
                            for episode_no in precise_missing_episode_values
                            if episode_no not in existing_folder_episodes
                        }
                    if existing_episode_scan_ready and known_total > 0 and not precise_missing_episode_values:
                        skipped_existing_candidates += 1
                        await write_subscription_log(
                            f"候选资源 #{index} 目录已覆盖订阅总集数 E1-E{known_total}，跳过导入",
                            "info",
                        )
                        await maybe_wait_between_attempts()
                        continue
                    if precise_missing_episode_values:
                        if use_fixed_share_link and fixed_share_runtime_manifest:
                            precise_selection, precise_stats = _build_tv_share_selection_from_manifest(
                                fixed_share_runtime_manifest,
                                precise_missing_episode_values,
                                task=task,
                            )
                        else:
                            precise_selection, precise_stats = await _build_tv_share_selection_for_missing_episodes(
                                cookie_115,
                                task,
                                item,
                                precise_missing_episode_values,
                                share_subdir_selection=resolved_subdir_selection,
                            )
                        precise_ids = (
                            precise_selection.get("selected_ids", [])
                            if isinstance(precise_selection.get("selected_ids"), list)
                            else []
                        )
                        if precise_ids:
                            job_payload["share_selection"] = precise_selection
                            forced_precise_selection_applied = True
                            selected_share_episode_values = {
                                max(0, int(value or 0))
                                for value in (
                                    precise_stats.get("covered_episodes", [])
                                    if isinstance(precise_stats, dict)
                                    else []
                                )
                                if max(0, int(value or 0)) > 0
                            }
                            selected_share_file_samples = [
                                str(sample or "").strip()
                                for sample in (
                                    precise_stats.get("selected_file_samples", [])
                                    if isinstance(precise_stats, dict)
                                    else []
                                )
                                if str(sample or "").strip()
                            ]
                            dedupe_hits = int((precise_stats or {}).get("duplicate_bucket_hits", 0) or 0)
                            dedupe_tail = f"，同集/同范围已优选 {dedupe_hits} 条重复版本" if dedupe_hits > 0 else ""
                            await write_subscription_log(
                                (
                                    f"候选资源 #{index} 固定链接模式已启用文件级筛选"
                                    f"{'（运行期缓存）' if bool((precise_stats or {}).get('from_runtime_cache', False)) else ''}，"
                                    f"自动命中 {len(precise_ids)} 个剧集文件后再转存（避免整包导入）{dedupe_tail}"
                                ),
                                "info",
                            )
                        else:
                            skipped_subdir_candidates += 1
                            selection_reason = str((precise_stats or {}).get("reason", "") or "").strip() or "unknown"
                            selection_reason_label = _format_subscription_reason_chain(selection_reason)
                            scanned_dirs = int((precise_stats or {}).get("scanned_dirs", 0) or 0)
                            scanned_entries = int((precise_stats or {}).get("scanned_entries", 0) or 0)
                            covered_preview = _format_episode_preview(precise_missing_episode_values)
                            await write_subscription_log(
                                (
                                    f"候选资源 #{index} 固定链接模式未能在订阅子目录中识别目标剧集文件，"
                                    f"已跳过避免整包导入（目标 {covered_preview}，原因 {selection_reason_label}，"
                                    f"扫描目录 {scanned_dirs} 个，条目 {scanned_entries} 条）"
                                ),
                                "warn",
                            )
                            await maybe_wait_between_attempts()
                            continue
                if (
                    task["media_type"] == "tv"
                    and existing_episode_scan_ready
                    and candidate_link_type == "115share"
                    and candidate_episode_values
                    and (not forced_precise_selection_applied)
                ):
                    overlap_existing = any(episode_no in existing_folder_episodes for episode_no in candidate_episode_values)
                    missing_for_candidate = _candidate_missing_episode_values(
                        candidate,
                        existing_folder_episodes,
                        episode_upper_bound=single_season_episode_upper_bound,
                    )
                    skip_due_overlap_fallback = False
                    if overlap_existing and missing_for_candidate:
                        if use_fixed_share_link and fixed_share_runtime_manifest:
                            share_selection, selection_stats = _build_tv_share_selection_from_manifest(
                                fixed_share_runtime_manifest,
                                missing_for_candidate,
                                task=task,
                            )
                        else:
                            share_selection, selection_stats = await _build_tv_share_selection_for_missing_episodes(
                                cookie_115,
                                task,
                                item,
                                missing_for_candidate,
                                share_subdir_selection=resolved_subdir_selection,
                            )
                        selected_ids = share_selection.get("selected_ids", []) if isinstance(share_selection, dict) else []
                        if selected_ids:
                            job_payload["share_selection"] = share_selection
                            selected_share_episode_values = {
                                max(0, int(value or 0))
                                for value in (selection_stats.get("covered_episodes", []) if isinstance(selection_stats, dict) else [])
                                if max(0, int(value or 0)) > 0
                            }
                            selected_share_file_samples = [
                                str(sample or "").strip()
                                for sample in (
                                    selection_stats.get("selected_file_samples", [])
                                    if isinstance(selection_stats, dict)
                                    else []
                                )
                                if str(sample or "").strip()
                            ]
                            dedupe_hits = int((selection_stats or {}).get("duplicate_bucket_hits", 0) or 0)
                            dedupe_tail = f"，同集/同范围已优选 {dedupe_hits} 条重复版本" if dedupe_hits > 0 else ""
                            await write_subscription_log(
                                (
                                    f"候选资源 #{index} 检测到大包与目录重叠，缺失 {_format_episode_preview(missing_for_candidate)}；"
                                    f"已自动选中 {len(selected_ids)} 个文件精细转存{dedupe_tail}"
                                ),
                                "info",
                            )
                        else:
                            missing_ratio = len(missing_for_candidate) / max(1, len(candidate_episode_values))
                            if missing_ratio <= 0.35:
                                skipped_existing_candidates += 1
                                skip_due_overlap_fallback = True
                                await write_subscription_log(
                                    (
                                        f"候选资源 #{index} 与目录重叠度较高（缺失占比 {missing_ratio:.0%}），"
                                        "精细转存未命中，为避免重复集已跳过该整包候选"
                                    ),
                                    "warn",
                                )
                            else:
                                await write_subscription_log(
                                    (
                                        f"候选资源 #{index} 尝试按缺失集精细转存未命中（扫描目录 {int(selection_stats.get('scanned_dirs', 0) or 0)} 个，"
                                        f"条目 {int(selection_stats.get('scanned_entries', 0) or 0)} 条），回退整包转存"
                                    ),
                                    "warn",
                                )
                    if skip_due_overlap_fallback:
                        continue
                job_plans: List[Dict[str, Any]] = [
                    {
                        "payload": job_payload,
                        "savepath": candidate_savepath,
                        "season": candidate_season,
                        "selected_episode_values": set(selected_share_episode_values),
                    }
                ]
                normalized_job_selection = normalize_share_selection_meta(job_payload.get("share_selection", {}))
                if (
                    task["media_type"] == "tv"
                    and candidate_link_type == "115share"
                    and is_subscription_multi_season_mode(task)
                ):
                    split_groups, split_stats = _split_tv_share_selection_by_season(
                        task,
                        normalized_job_selection,
                        fixed_share_runtime_manifest,
                    )
                    if split_groups:
                        split_labels: List[str] = []
                        rebuilt_job_plans: List[Dict[str, Any]] = []
                        for split_group in split_groups:
                            group_selection = normalize_share_selection_meta(split_group.get("selection", {}))
                            group_ids = (
                                group_selection.get("selected_ids", [])
                                if isinstance(group_selection.get("selected_ids"), list)
                                else []
                            )
                            if not group_ids:
                                continue
                            group_season = max(0, int(split_group.get("season", 0) or 0))
                            group_episode_values = _clamp_episode_values(
                                split_group.get("episodes", set()),
                                episode_upper_bound=single_season_episode_upper_bound,
                            )
                            group_anchor_episode = max(group_episode_values) if group_episode_values else episode
                            group_savepath = build_subscription_tv_savepath(
                                task,
                                base_savepath,
                                season=group_season,
                                episode=group_anchor_episode,
                            ) or candidate_savepath
                            group_folder_id = str(savepath_folder_id_cache.get(group_savepath, "") or "").strip()
                            if not group_folder_id:
                                group_folder_id = await asyncio.to_thread(
                                    ensure_115_folder_id_by_path,
                                    cookie_115,
                                    group_savepath,
                                )
                                savepath_folder_id_cache[group_savepath] = str(group_folder_id or "").strip()
                            group_matched_monitor = match_monitor_task_for_savepath(
                                cfg,
                                group_savepath,
                                provider=provider,
                            )
                            group_monitor_task_name = str(group_matched_monitor.get("task_name", "") or "").strip()

                            group_payload = dict(job_payload)
                            group_payload["folder_id"] = group_folder_id
                            group_payload["savepath"] = group_savepath
                            group_payload["monitor_task_name"] = group_monitor_task_name
                            group_payload["auto_refresh"] = bool(group_monitor_task_name) and (not batch_refresh_enabled)
                            group_payload["extra"] = dict(job_payload.get("extra", {}))
                            group_payload["share_selection"] = group_selection

                            rebuilt_job_plans.append(
                                {
                                    "payload": group_payload,
                                    "savepath": group_savepath,
                                    "season": group_season,
                                    "selected_episode_values": group_episode_values,
                                }
                            )
                            season_label = f"S{group_season:02d}" if group_season > 0 else "未识别季"
                            split_labels.append(f"{season_label} {len(group_ids)} 个文件")

                        if rebuilt_job_plans:
                            job_plans = rebuilt_job_plans
                            split_text = " / ".join(split_labels[:6])
                            await write_subscription_log(
                                f"候选资源 #{index} 多季合一已按季拆分转存：{split_text}",
                                "info",
                            )
                            unresolved_count = int((split_stats or {}).get("unresolved_count", 0) or 0)
                            if unresolved_count > 0:
                                unresolved_samples = (
                                    (split_stats or {}).get("unresolved_samples", [])
                                    if isinstance((split_stats or {}).get("unresolved_samples", []), list)
                                    else []
                                )
                                sample_text = " / ".join(
                                    [str(name or "").strip()[:80] for name in unresolved_samples[:3] if str(name or "").strip()]
                                )
                                sample_tail = f"，示例：{sample_text}" if sample_text else ""
                                await write_subscription_log(
                                    (
                                        f"候选资源 #{index} 仍有 {unresolved_count} 个已选文件未能稳定识别季别，"
                                        "本次仅按已识别文件分季转存"
                                        f"{sample_tail}"
                                    ),
                                    "warn",
                                )

                if not job_plans:
                    failed_attempts += 1
                    last_failed_detail = "未生成可执行导入任务"
                    await write_subscription_log(
                        f"候选资源 #{index} 导入失败：{last_failed_detail}",
                        "warn",
                    )
                    await maybe_wait_between_attempts()
                    continue

                for plan_index, job_plan in enumerate(job_plans, start=1):
                    check_subscription_cancelled()
                    plan_payload = job_plan.get("payload", {}) if isinstance(job_plan.get("payload"), dict) else {}
                    plan_savepath = (
                        normalize_relative_path(str(job_plan.get("savepath", "") or "").strip()) or candidate_savepath
                    )
                    plan_season = max(0, int(job_plan.get("season", 0) or 0))
                    plan_selected_episode_values = _clamp_episode_values(
                        job_plan.get("selected_episode_values", set()),
                        episode_upper_bound=single_season_episode_upper_bound,
                    )
                    pre_attempt_existing_episodes = set(existing_folder_episodes)
                    duplicate_validation_applied = False
                    duplicate_verified_episode_values: Set[int] = set()

                    plan_job_id = create_resource_job(
                        item,
                        plan_payload,
                    )
                    if plan_job_id <= 0:
                        failed_attempts += 1
                        last_failed_detail = "创建导入任务失败"
                        await write_subscription_log(
                            f"候选资源 #{index} 导入失败：{last_failed_detail}",
                            "warn",
                        )
                        continue

                    batch_created_job_ids.add(plan_job_id)
                    plan_scope_label = ""
                    if len(job_plans) > 1:
                        season_tail = f"S{plan_season:02d}" if plan_season > 0 else "分组"
                        plan_scope_label = f"{season_tail} {plan_index}/{len(job_plans)} "
                    await write_subscription_log(
                        (
                            f"候选资源 #{index}（{episode_label}）{plan_scope_label}已创建导入任务 #{plan_job_id}，开始执行："
                            f"{str(item.get('title', '') or f'资源#{resource_id}').strip()[:96]}"
                        ),
                        "info",
                    )

                    job_runner = asyncio.create_task(run_resource_job(plan_job_id))
                    done, _ = await asyncio.wait({job_runner}, timeout=import_timeout_seconds)
                    if not done:
                        job_runner.add_done_callback(consume_background_task_result)
                        job_runner.cancel()
                        timed_out_attempts += 1
                        timeout_detail = f"执行超时（>{import_timeout_seconds} 秒）"
                        try:
                            await cancel_resource_job(plan_job_id, reason="timeout")
                        except Exception:
                            update_resource_job(
                                plan_job_id,
                                status="failed",
                                status_detail=timeout_detail,
                                finished_at=now_text(),
                            )
                            if resource_id > 0:
                                conn = open_db()
                                update_resource_item_status(conn, resource_id, "failed")
                                conn.commit()
                                conn.close()
                        failed_attempts += 1
                        last_failed_detail = timeout_detail
                        await write_subscription_log(
                            f"候选资源 #{index} 导入超时：{timeout_detail}，继续执行该候选的其他季目录",
                            "warn",
                        )
                        continue

                    await job_runner
                    latest_job = get_resource_job(plan_job_id, include_private=True)
                    latest_status = str((latest_job or {}).get("status", "") or "").strip().lower()
                    plan_auto_refresh = bool(
                        (latest_job or {}).get("auto_refresh", bool(str(plan_payload.get("monitor_task_name", "")).strip()))
                    )
                    if latest_status == "failed":
                        failed_attempts += 1
                        last_failed_detail = str((latest_job or {}).get("status_detail", "") or "资源导入失败").strip()
                        if (not use_fixed_share_link) and candidate_link_url and _is_subscription_invalid_link_error(last_failed_detail, candidate_link_type):
                            cache_meta = _record_subscription_invalid_link_cache(
                                candidate_link_url,
                                candidate_link_type,
                                last_failed_detail,
                            )
                            if cache_meta:
                                invalid_link_cache[candidate_link_url] = cache_meta
                                await write_subscription_log(
                                    f"候选资源 #{index} 链接已标记为失效，后续自动跳过（有效期至 {cache_meta.get('expires_at', '--')}）",
                                    "warn",
                                )
                        await write_subscription_log(
                            f"候选资源 #{index} 导入失败：{last_failed_detail}，继续执行该候选的其他季目录",
                            "warn",
                        )
                        continue

                    if (
                        latest_status in ("submitted", "completed")
                        and task["media_type"] == "tv"
                        and existing_episode_scan_ready
                        and candidate_link_type == "115share"
                        and is_115_share_receive_duplicate_response((latest_job or {}).get("response", {}))
                    ):
                        duplicate_validation_applied = True
                        verify_scan_result, verify_scan_episodes = await rescan_existing_tv_episodes()
                        verify_target_episodes = _clamp_episode_values(
                            (plan_selected_episode_values or candidate_episode_values) or set(),
                            episode_upper_bound=single_season_episode_upper_bound,
                        )
                        verification = _evaluate_duplicate_receive_validation(
                            verify_target_episodes=verify_target_episodes,
                            pre_attempt_existing_episodes=pre_attempt_existing_episodes,
                            verify_scan_episodes=verify_scan_episodes,
                            scan_scanned_dirs=int(verify_scan_result.get("scanned_dirs", 0) or 0),
                            scan_scanned_entries=int(verify_scan_result.get("scanned_entries", 0) or 0),
                            scan_failed_dirs=int(verify_scan_result.get("failed_dirs", 0) or 0),
                            scan_truncated=bool(verify_scan_result.get("truncated", False)),
                        )

                        if bool(verification.get("should_fail", False)) and verify_target_episodes:
                            retry_total = max(0, int(SUBSCRIPTION_DUPLICATE_VERIFY_RETRIES or 0))
                            retry_delay_seconds = max(0.0, float(SUBSCRIPTION_DUPLICATE_VERIFY_DELAY_SECONDS or 0))
                            if retry_total > 0:
                                await write_subscription_log(
                                    (
                                        f"候选资源 #{index} 收到 115 重复接收提示，目录暂未识别目标集，"
                                        f"将延迟复核 {retry_total} 次"
                                    ),
                                    "warn",
                                )
                                recovered_from_retry = False
                                for retry_index in range(1, retry_total + 1):
                                    check_subscription_cancelled()
                                    if retry_delay_seconds > 0:
                                        await asyncio.sleep(retry_delay_seconds)
                                    verify_scan_result, verify_scan_episodes = await rescan_existing_tv_episodes()
                                    verification = _evaluate_duplicate_receive_validation(
                                        verify_target_episodes=verify_target_episodes,
                                        pre_attempt_existing_episodes=pre_attempt_existing_episodes,
                                        verify_scan_episodes=verify_scan_episodes,
                                        scan_scanned_dirs=int(verify_scan_result.get("scanned_dirs", 0) or 0),
                                        scan_scanned_entries=int(verify_scan_result.get("scanned_entries", 0) or 0),
                                        scan_failed_dirs=int(verify_scan_result.get("failed_dirs", 0) or 0),
                                        scan_truncated=bool(verify_scan_result.get("truncated", False)),
                                    )
                                    if not bool(verification.get("should_fail", False)):
                                        recovered_from_retry = True
                                        await write_subscription_log(
                                            (
                                                f"候选资源 #{index} 重复接收第 {retry_index} 次复核通过，"
                                                "按幂等结果继续处理"
                                            ),
                                            "info",
                                        )
                                        break
                                if (not recovered_from_retry) and bool(verification.get("should_fail", False)):
                                    await write_subscription_log(
                                        (
                                            f"候选资源 #{index} 重复接收复核 {retry_total} 次仍未识别目标集，"
                                            "将回退为失败并继续尝试其他候选"
                                        ),
                                        "warn",
                                    )

                        verified_hits = {
                            max(0, int(item or 0))
                            for item in (
                                verification.get("verified_new_hits", [])
                                if isinstance(verification.get("verified_new_hits"), list)
                                else []
                            )
                            if max(0, int(item or 0)) > 0
                        }
                        present_hits = {
                            max(0, int(item or 0))
                            for item in (
                                verification.get("present_hits", [])
                                if isinstance(verification.get("present_hits"), list)
                                else []
                            )
                            if max(0, int(item or 0)) > 0
                        }
                        if bool(verification.get("should_fail", False)):
                            latest_status = "failed"
                            failed_attempts += 1
                            last_failed_detail = (
                                "115 提示文件已接收，但目标目录未发现对应剧集，已回退为失败以便继续尝试其他候选"
                            )
                            update_resource_job(
                                plan_job_id,
                                status="failed",
                                status_detail=last_failed_detail,
                                finished_at=now_text(),
                            )
                            if resource_id > 0:
                                conn = open_db()
                                update_resource_item_status(conn, resource_id, "failed")
                                conn.commit()
                                conn.close()
                            await write_subscription_log(
                                f"候选资源 #{index} 导入失败：{last_failed_detail}",
                                "warn",
                            )
                            continue

                        verify_scanned_entries = int(verify_scan_result.get("scanned_entries", 0) or 0)
                        if verify_scan_episodes:
                            existing_folder_episodes = set(verify_scan_episodes)
                        elif verify_scanned_entries <= 0:
                            existing_folder_episodes = set()
                        existing_episode_count = len(existing_folder_episodes)
                        existing_episode_scan_stats.update(
                            {
                                "existing_episode_scan_ready": True,
                                "existing_episode_count": existing_episode_count,
                                "existing_episode_max": max(existing_folder_episodes) if existing_folder_episodes else 0,
                                "existing_episode_scanned_dirs": int(verify_scan_result.get("scanned_dirs", 0) or 0),
                                "existing_episode_scanned_entries": int(verify_scan_result.get("scanned_entries", 0) or 0),
                                "existing_episode_failed_dirs": int(verify_scan_result.get("failed_dirs", 0) or 0),
                                "existing_episode_scan_truncated": bool(verify_scan_result.get("truncated", False)),
                            }
                        )
                        if verified_hits:
                            duplicate_verified_episode_values = set(verified_hits)
                            await write_subscription_log(
                                (
                                    f"候选资源 #{index} 收到 115 重复接收提示后已复核目标目录，"
                                    f"确认新增 {_format_episode_preview(verified_hits)}"
                                ),
                                "info",
                            )
                        elif present_hits:
                            await write_subscription_log(
                                (
                                    f"候选资源 #{index} 收到 115 重复接收提示；复核目录已存在 "
                                    f"{_format_episode_preview(present_hits)}，按幂等结果处理"
                                ),
                                "info",
                            )
                        elif verify_target_episodes:
                            verify_reason = str(verification.get("reason", "") or "").strip()
                            if verify_reason == "scan_not_reliable":
                                await write_subscription_log(
                                    (
                                        f"候选资源 #{index} 收到 115 重复接收提示；目录复核不可靠"
                                        "（扫描失败或截断），已按幂等结果放行"
                                    ),
                                    "warn",
                                )
                            elif verify_reason == "episode_unrecognized":
                                await write_subscription_log(
                                    (
                                        f"候选资源 #{index} 收到 115 重复接收提示；目录文件命名未能稳定识别目标集数，"
                                        "已按幂等结果放行"
                                    ),
                                    "warn",
                                )

                    if duplicate_validation_applied:
                        recorded_episode_values = set(duplicate_verified_episode_values)
                    else:
                        recorded_episode_values = _resolve_recorded_episode_values(
                            candidate,
                            plan_selected_episode_values,
                            episode_upper_bound=single_season_episode_upper_bound,
                        )
                    if recorded_episode_values and existing_episode_scan_ready:
                        existing_folder_episodes.update(recorded_episode_values)
                        existing_episode_count = len(existing_folder_episodes)
                        existing_episode_scan_stats["existing_episode_count"] = existing_episode_count
                        existing_episode_scan_stats["existing_episode_max"] = (
                            max(existing_folder_episodes) if existing_folder_episodes else 0
                        )

                    candidate_success_records.append(
                        {
                            "job_id": plan_job_id,
                            "savepath": plan_savepath,
                            "auto_refresh": plan_auto_refresh,
                            "reused_existing": False,
                            "recorded_episode_values": recorded_episode_values,
                            "selected_file_samples": list(selected_share_file_samples[:8]),
                            "ledger_season": (
                                plan_season
                                if plan_season > 0
                                else (
                                    candidate_season
                                    if candidate_season > 0
                                    else (
                                        max(1, int(task.get("season", 1) or 1))
                                        if not is_subscription_multi_season_mode(task)
                                        else 0
                                    )
                                )
                            ),
                        }
                    )

                if not candidate_success_records:
                    await maybe_wait_between_attempts()
                    continue

            if not candidate_success_records:
                await maybe_wait_between_attempts()
                continue

            job_id = int(candidate_success_records[0].get("job_id", 0) or 0)
            auto_refresh = any(bool(record.get("auto_refresh")) for record in candidate_success_records)
            reused_existing = all(bool(record.get("reused_existing")) for record in candidate_success_records)
            candidate_savepaths = {
                normalize_relative_path(str(record.get("savepath", "") or "").strip())
                for record in candidate_success_records
                if normalize_relative_path(str(record.get("savepath", "") or "").strip())
            }
            candidate_result_savepath = candidate_savepath
            if len(candidate_savepaths) == 1:
                candidate_result_savepath = next(iter(candidate_savepaths))
            elif len(candidate_savepaths) > 1:
                candidate_result_savepath = effective_savepath

            representative_ledger_season = max(
                0,
                int(candidate_success_records[0].get("ledger_season", candidate_season) or candidate_season or 0),
            )
            create_subscription_match(
                task_name=task_name,
                resource_id=resource_id,
                job_id=job_id,
                media_type=task.get("media_type", "movie"),
                season=representative_ledger_season,
                episode=episode,
                total_episodes=total_detected,
                score=score,
            )
            successful_count += 1
            max_total_detected = max(max_total_detected, total_detected)
            ledger_updated = False
            for success_record in candidate_success_records:
                success_job_id = max(0, int(success_record.get("job_id", 0) or 0))
                if success_job_id > 0:
                    successful_job_ids.append(success_job_id)
                recorded_episode_values = _clamp_episode_values(
                    success_record.get("recorded_episode_values", set()),
                    episode_upper_bound=single_season_episode_upper_bound,
                )
                if recorded_episode_values:
                    imported_episodes.update(recorded_episode_values)
                    if existing_episode_scan_ready:
                        existing_folder_episodes.update(recorded_episode_values)
                    if task["media_type"] == "tv":
                        latest_job_meta = get_resource_job(success_job_id, include_private=True)
                        selected_ids = (
                            latest_job_meta.get("selected_ids", [])
                            if isinstance(latest_job_meta, dict) and isinstance(latest_job_meta.get("selected_ids"), list)
                            else []
                        )
                        source_fp, content_fp = _build_subscription_episode_ledger_fingerprints(
                            item,
                            candidate,
                            recorded_episode_values,
                            selected_ids,
                        )
                        ledger_season = max(0, int(success_record.get("ledger_season", 0) or 0))
                        if ledger_season <= 0 and (not is_subscription_multi_season_mode(task)):
                            ledger_season = max(1, int(task.get("season", 1) or 1))
                        upsert_subscription_episode_ledger(
                            task_name=task_name,
                            episodes=recorded_episode_values,
                            media_type=task.get("media_type", "tv"),
                            season=ledger_season,
                            score=score,
                            resolution=max(0, int(candidate.get("resolution", 0) or 0)),
                            source_fp=source_fp,
                            content_fp=content_fp,
                            link_type=candidate_link_type,
                            link_url=candidate_link_url,
                            resource_id=resource_id,
                            job_id=success_job_id,
                        )
                        ledger_updated = True
            if existing_episode_scan_ready:
                existing_episode_count = len(existing_folder_episodes)
                existing_episode_scan_stats["existing_episode_count"] = existing_episode_count
                existing_episode_scan_stats["existing_episode_max"] = (
                    max(existing_folder_episodes) if existing_folder_episodes else 0
                )
            if ledger_updated:
                episode_ledger_rows = load_subscription_episode_ledger(task_name, include_stale=True)

            previous_auto_refresh = selected_auto_refresh
            if not selected_candidate:
                selected_candidate = candidate
                selected_item = item
                selected_job_id = job_id
                selected_auto_refresh = auto_refresh
                selected_reused_existing = reused_existing
                selected_job_savepath = candidate_result_savepath
            else:
                selected_episode = int(selected_candidate.get("episode", 0) or 0)
                selected_score = int(selected_candidate.get("score", 0) or 0)
                if episode > selected_episode or (episode == selected_episode and score > selected_score):
                    selected_candidate = candidate
                    selected_item = item
                    selected_job_id = job_id
                    selected_auto_refresh = auto_refresh
                    selected_reused_existing = reused_existing
                    selected_job_savepath = candidate_result_savepath
            selected_auto_refresh = bool(previous_auto_refresh or selected_auto_refresh or auto_refresh)
            candidate_recorded_episode_values = _clamp_episode_values(
                set().union(
                    *[
                        (
                            _clamp_episode_values(
                                record.get("recorded_episode_values", set()),
                                episode_upper_bound=single_season_episode_upper_bound,
                            )
                            if isinstance(record, dict)
                            else set()
                        )
                        for record in candidate_success_records
                    ]
                ),
                episode_upper_bound=single_season_episode_upper_bound,
            )
            candidate_file_samples = unique_preserve_order(
                [
                    str(sample or "").strip()
                    for record in candidate_success_records
                    if isinstance(record, dict)
                    for sample in (
                        record.get("selected_file_samples", [])
                        if isinstance(record.get("selected_file_samples", []), list)
                        else []
                    )
                    if str(sample or "").strip()
                ]
            )

            await write_subscription_log(
                (
                    f"候选资源 #{index} 导入成功：{str(item.get('title', '') or f'资源#{resource_id}').strip()}"
                    f"（评分 {score}）"
                    f"{'，命中 ' + _format_episode_preview(candidate_recorded_episode_values) if candidate_recorded_episode_values else ''}"
                    f"{'，文件：' + '；'.join(candidate_file_samples[:8]) if candidate_file_samples else ''}"
                ),
                "success",
            )
            if (
                batch_episode_import
                and task["media_type"] == "tv"
                and existing_episode_scan_ready
                and single_season_episode_upper_bound > 0
            ):
                required_episode_values = set(range(1, single_season_episode_upper_bound + 1))
                if required_episode_values.issubset(existing_folder_episodes):
                    await write_subscription_log(
                        f"目标目录已覆盖单季全部 E1-E{single_season_episode_upper_bound}，结束本轮候选尝试",
                        "info",
                    )
                    break
            if not batch_episode_import:
                break
            await maybe_wait_between_attempts()

        _subscription_stage_timer_enter(stage_timer, "finalize")
        if batch_refresh_enabled:
            batch_refresh_result = _finalize_subscription_batch_refresh(
                task_name=task_name,
                run_id=subscription_run_id,
                created_job_ids=batch_created_job_ids,
                cfg=cfg,
            )
            await write_subscription_log(
                (
                    f"批次收口汇总 | run_id={subscription_run_id} | 创建 {int(batch_refresh_result.get('created_jobs', 0) or 0)} 条 | "
                    f"成功入库 {int(batch_refresh_result.get('successful_jobs', 0) or 0)} 条 | "
                    f"可刷新 {int(batch_refresh_result.get('refresh_eligible_jobs', 0) or 0)} 条 | "
                    f"合并目录 {int(batch_refresh_result.get('grouped_targets', 0) or 0)} 组 | "
                    f"触发监控 {int(batch_refresh_result.get('triggered_groups', 0) or 0)} 组"
                ),
                "info",
            )
            if int(batch_refresh_result.get("missing_monitor_task_jobs", 0) or 0) > 0:
                await write_subscription_log(
                    (
                        f"批次收口异常：有 {int(batch_refresh_result.get('missing_monitor_task_jobs', 0) or 0)} 条导入任务未触发监控，"
                        "原因是目标监控任务不存在"
                    ),
                    "warn",
                )

        if not selected_candidate:
            if skipped_invalid_candidates > 0 and attempted_candidates <= 0:
                detail = f"候选资源命中失效链接缓存（已跳过 {skipped_invalid_candidates} 条），等待新资源发布"
            elif skipped_subdir_candidates > 0 and attempted_candidates <= 0:
                detail = f"候选资源未命中订阅子目录「{task_share_scope_label}」（已跳过 {skipped_subdir_candidates} 条），等待新资源发布"
            elif skipped_existing_candidates > 0 and attempted_candidates <= 0:
                detail = f"候选资源均已在目标目录存在（已跳过 {skipped_existing_candidates} 条），等待新集发布"
            elif skipped_ledger_candidates > 0 and attempted_candidates <= 0:
                detail = f"候选资源已被集数账本覆盖（已跳过 {skipped_ledger_candidates} 条），等待新集或更优资源"
            elif skipped_episode_candidates > 0 and attempted_candidates <= 0:
                detail = f"候选资源均为旧集（已跳过 {skipped_episode_candidates} 条），等待新集发布"
            elif failed_attempts > 0:
                detail = f"已尝试 {attempted_candidates} 个候选资源均失败，等待下次自动重试"
                if last_failed_detail:
                    detail += f"（最近失败：{last_failed_detail[:80]}）"
                if timed_out_attempts > 0:
                    detail += f"（超时 {timed_out_attempts} 条）"
            else:
                detail = "候选资源暂不可用，等待下次自动重试"
            if skipped_invalid_candidates > 0 and attempted_candidates > 0:
                detail += f"；失效链接缓存跳过 {skipped_invalid_candidates} 条"
            if skipped_subdir_candidates > 0 and attempted_candidates > 0:
                detail += f"；子目录过滤跳过 {skipped_subdir_candidates} 条"
            if skipped_ledger_candidates > 0 and attempted_candidates > 0:
                detail += f"；集数账本跳过 {skipped_ledger_candidates} 条"
            upsert_subscription_task_state(
                task_name,
                media_type=task.get("media_type", "movie"),
                status="waiting",
                progress=100,
                detail=detail,
                stats={
                    "matched": False,
                    "run_id": subscription_run_id,
                    "batch_refresh_enabled": batch_refresh_enabled,
                    "batch_created_jobs": int(batch_refresh_result.get("created_jobs", 0) or 0),
                    "batch_successful_jobs": int(batch_refresh_result.get("successful_jobs", 0) or 0),
                    "batch_refresh_eligible_jobs": int(batch_refresh_result.get("refresh_eligible_jobs", 0) or 0),
                    "batch_grouped_targets": int(batch_refresh_result.get("grouped_targets", 0) or 0),
                    "batch_triggered_groups": int(batch_refresh_result.get("triggered_groups", 0) or 0),
                    "batch_triggered_jobs": int(batch_refresh_result.get("triggered_jobs", 0) or 0),
                    "batch_missing_monitor_task_jobs": int(batch_refresh_result.get("missing_monitor_task_jobs", 0) or 0),
                    "last_episode": last_episode,
                    "total_episodes": known_total,
                    "attempted_candidates": attempted_candidates,
                    "failed_attempts": failed_attempts,
                    "timed_out_attempts": timed_out_attempts,
                    "skipped_episode_candidates": skipped_episode_candidates,
                    "skipped_existing_candidates": skipped_existing_candidates,
                    "skipped_ledger_candidates": skipped_ledger_candidates,
                    "skipped_invalid_candidates": skipped_invalid_candidates,
                    "skipped_subdir_candidates": skipped_subdir_candidates,
                    "scanned_candidates": scanned_candidates,
                    "max_scan_candidates": max_scan_candidates,
                    "use_fixed_share_link": use_fixed_share_link,
                    "fixed_link_channel_search": fixed_link_channel_search_enabled,
                    "share_link_url": task_share_link_url if use_fixed_share_link else "",
                    "share_subdir": task_share_subdir,
                    "share_subdir_cid": task_share_subdir_cid,
                    **existing_episode_scan_stats,
                    **search_stats,
                },
            )
            await write_subscription_log(detail, "warn")
            update_subscription_summary("等待资源", detail)
            return

        candidate = selected_candidate
        item = selected_item
        resource_id = int(item.get("id", 0) or 0)
        score = int(candidate.get("score", 0) or 0)
        episode = max(0, int(candidate.get("episode", 0) or 0))
        total_detected = max(0, int(candidate.get("total", 0) or 0))
        selected_season = max(0, int(candidate.get("season", 0) or 0))
        job_id = int(selected_job_id or 0)
        auto_refresh = bool(selected_auto_refresh)
        if batch_refresh_enabled and int(batch_refresh_result.get("triggered_groups", 0) or 0) > 0:
            auto_refresh = True
        imported_episode_list = sorted(imported_episodes)
        matched_display_title = pick_subscription_display_title(task, item, fallback=f"资源#{resource_id}")

        next_episode = last_episode
        if task["media_type"] == "tv" and imported_episode_list:
            next_episode = max(last_episode, imported_episode_list[-1])
        elif task["media_type"] == "tv" and episode > 0:
            next_episode = max(last_episode, episode)
        next_total = known_total or max_total_detected or total_detected
        if task["media_type"] == "tv" and (max_total_detected > 0 or total_detected > 0):
            _sync_task_total_episodes(task_name, max_total_detected or total_detected)

        successful_job_count = len(successful_job_ids)
        if selected_reused_existing:
            action_text = "复用导入任务"
        elif successful_job_count > 1:
            action_text = f"已创建并执行 {successful_job_count} 个分季导入任务"
        else:
            action_text = "已创建并执行导入任务"
        if task["media_type"] == "tv" and (successful_count > 1 or successful_job_count > 1):
            if imported_episode_list:
                if len(imported_episode_list) <= 8:
                    episode_summary = "、".join([f"E{episode_no}" for episode_no in imported_episode_list])
                else:
                    episode_summary = f"E{imported_episode_list[0]}-E{imported_episode_list[-1]}"
                batch_tail = f"（新增 {len(imported_episode_list)} 集：{episode_summary}）"
            else:
                batch_tail = ""
            batch_prefix = (
                f"本次分季导入 {successful_job_count} 个任务"
                if successful_count <= 1 and successful_job_count > 1
                else f"本次批量导入 {successful_count} 条候选资源"
            )
            detail = (
                f"{batch_prefix}{batch_tail}；"
                f"最新命中「{matched_display_title}」"
                f"（评分 {score}），{action_text} #{job_id}，保存到 {selected_job_savepath}"
            )
        else:
            detail = (
                f"命中「{matched_display_title}」"
                f"（评分 {score}），{action_text} #{job_id}，保存到 {selected_job_savepath}"
            )
        if selected_auto_refresh:
            if batch_refresh_enabled:
                triggered_groups = int(batch_refresh_result.get("triggered_groups", 0) or 0)
                successful_jobs = int(batch_refresh_result.get("successful_jobs", 0) or 0)
                refresh_eligible_jobs = int(batch_refresh_result.get("refresh_eligible_jobs", 0) or 0)
                missing_jobs = int(batch_refresh_result.get("missing_monitor_task_jobs", 0) or 0)
                if triggered_groups > 0:
                    detail += "；批次收口已统一触发监控任务"
                elif missing_jobs > 0:
                    detail += "；批次收口未触发监控（目标监控任务不存在）"
                elif successful_jobs > 0 and refresh_eligible_jobs <= 0:
                    detail += "；本批次成功入库但未命中监控任务，未触发监控"
                elif successful_jobs > 0:
                    detail += "；批次收口未触发监控"
                elif int(batch_refresh_result.get("created_jobs", 0) or 0) > 0:
                    detail += "；本批次无成功入库任务，未触发监控"
                else:
                    detail += "；未创建新导入任务，沿用历史任务状态"
            else:
                detail += "；自动触发监控任务"
        else:
            detail += "；当前目录未命中文件夹监控任务"

        status = "completed"
        if task["media_type"] == "tv" and next_total > 0 and next_episode >= next_total:
            status = "completed"
        upsert_subscription_task_state(
            task_name,
            media_type=task.get("media_type", "movie"),
            status=status,
            progress=100,
            detail=detail,
            last_success_at=now_text(),
            last_error="",
            last_episode=next_episode,
            total_episodes=next_total,
            matched_resource_id=resource_id,
            matched_resource_title=matched_display_title,
            matched_score=score,
            queued_job_id=job_id,
            stats={
                "matched": True,
                "run_id": subscription_run_id,
                "batch_refresh_enabled": batch_refresh_enabled,
                "batch_created_jobs": int(batch_refresh_result.get("created_jobs", 0) or 0),
                "batch_successful_jobs": int(batch_refresh_result.get("successful_jobs", 0) or 0),
                "batch_refresh_eligible_jobs": int(batch_refresh_result.get("refresh_eligible_jobs", 0) or 0),
                "batch_grouped_targets": int(batch_refresh_result.get("grouped_targets", 0) or 0),
                "batch_triggered_groups": int(batch_refresh_result.get("triggered_groups", 0) or 0),
                "batch_triggered_jobs": int(batch_refresh_result.get("triggered_jobs", 0) or 0),
                "batch_missing_monitor_task_jobs": int(batch_refresh_result.get("missing_monitor_task_jobs", 0) or 0),
                "score": score,
                "token_hits": int(candidate.get("token_hits", 0) or 0),
                "token_total": int(candidate.get("token_total", 0) or 0),
                "episode": episode,
                "season": selected_season,
                "total_episodes": next_total,
                "job_id": job_id,
                "job_ids": successful_job_ids[:40],
                "auto_refresh": auto_refresh,
                "matched_count": successful_count,
                "imported_episode_count": len(imported_episode_list),
                "imported_episodes": imported_episode_list[:80],
                "batch_episode_import": batch_episode_import,
                "attempted_candidates": attempted_candidates,
                "failed_attempts": failed_attempts,
                "timed_out_attempts": timed_out_attempts,
                "skipped_episode_candidates": skipped_episode_candidates,
                "skipped_existing_candidates": skipped_existing_candidates,
                "skipped_ledger_candidates": skipped_ledger_candidates,
                "skipped_invalid_candidates": skipped_invalid_candidates,
                "skipped_subdir_candidates": skipped_subdir_candidates,
                "scanned_candidates": scanned_candidates,
                "max_scan_candidates": max_scan_candidates,
                "existing_episode_count": existing_episode_count,
                "use_fixed_share_link": use_fixed_share_link,
                "fixed_link_channel_search": fixed_link_channel_search_enabled,
                "share_link_url": task_share_link_url if use_fixed_share_link else "",
                "share_subdir": task_share_subdir,
                "share_subdir_cid": task_share_subdir_cid,
                **existing_episode_scan_stats,
                **search_stats,
            },
        )
        await write_subscription_log(detail, "success")
        try:
            notify_result = await push_subscription_success_notification(
                cfg=cfg,
                task=task,
                item=item,
                effective_savepath=selected_job_savepath,
                job_id=job_id,
                successful_count=successful_count,
                imported_episode_list=imported_episode_list,
                baseline_last_episode=baseline_last_episode,
                next_episode=next_episode,
            )
            if bool(notify_result.get("pushed", False)):
                channel = str(notify_result.get("channel", "") or "").strip().lower()
                channel_label = "企业微信应用 API" if channel == "wecom_app" else "企业微信群机器人"
                notified_episodes = (
                    notify_result.get("episodes", [])
                    if isinstance(notify_result.get("episodes"), list)
                    else []
                )
                if notified_episodes:
                    await write_subscription_log(
                        f"更新通知已推送到{channel_label}（新增 {len(notified_episodes)} 集）",
                        "info",
                    )
                else:
                    await write_subscription_log(f"更新通知已推送到{channel_label}", "info")
        except Exception as notify_exc:
            await write_subscription_log(f"订阅成功通知推送失败：{notify_exc}", "warn")
        update_subscription_summary("执行成功", detail)
    except asyncio.CancelledError:
        detail = "任务已中断"
        upsert_subscription_task_state(
            task_name,
            media_type=task.get("media_type", "movie"),
            status="cancelled",
            progress=100,
            detail=detail,
            last_error=detail,
        )
        await write_subscription_log(detail, "warn")
        update_subscription_summary("任务中断", task_name)
    except Exception as exc:
        detail = str(exc)
        upsert_subscription_task_state(
            task_name,
            media_type=task.get("media_type", "movie"),
            status="failed",
            progress=100,
            detail=detail,
            last_error=detail,
        )
        await write_subscription_log(f"失败原因: {detail}", "error")
        update_subscription_summary("任务失败", detail)
    finally:
        _subscription_share_entry_runtime_cache_var.reset(share_runtime_cache_token)
        _subscription_share_entry_refreshed_keys_var.reset(share_refreshed_keys_token)
        tail_status = "idle"
        try:
            tail_state = load_subscription_task_state(task_name, task.get("media_type", "movie"))
            tail_status = str(tail_state.get("status", "idle") or "idle").strip().lower()
            if tail_status == "running":
                fallback_detail = "执行链路已结束但未写入最终状态，已自动回收（可重新运行）"
                upsert_subscription_task_state(
                    task_name,
                    media_type=task.get("media_type", "movie"),
                    status="failed",
                    progress=100,
                    detail=fallback_detail,
                    last_error=fallback_detail,
                )
                try:
                    await write_subscription_log(fallback_detail, "warn")
                except Exception:
                    pass
                tail_status = "failed"
        except Exception:
            pass

        # 优先回收运行态，避免日志写入异常导致 UI 长时间停在“运行中”。
        subscription_status["running"] = False
        subscription_status["current_task"] = ""
        subscription_control["cancel"] = False
        schedule_ui_state_push(0)
        _subscription_stage_timer_enter(stage_timer, "finalize")
        tail_status_label = {
            'completed': '执行成功',
            'cancelled': '已中断',
            'failed': '执行失败',
        }.get(tail_status, "已结束")
        try:
            stage_timing_line, total_timing_line = _build_subscription_stage_timing_log_lines(stage_timer)
            await write_subscription_log(stage_timing_line, "info")
            await write_subscription_log(total_timing_line, "info")
        except Exception:
            pass
        try:
            await write_subscription_log(
                f"━━━━━━━━━━【订阅结束 | {task_name} | {tail_status_label or '已结束'}】━━━━━━━━━━",
                "task-divider",
            )
        except Exception:
            pass
        reset_subscription_log_context(subscription_log_context_token)
        try:
            await start_next_subscription_job()
        except Exception:
            pass


async def start_next_subscription_job() -> None:
    if subscription_status["running"] or not subscription_queue:
        subscription_status["queued"] = [item["task_name"] for item in subscription_queue]
        schedule_ui_state_push(0)
        return
    next_job = subscription_queue.pop(0)
    subscription_status["queued"] = [item["task_name"] for item in subscription_queue]
    schedule_ui_state_push(0)
    asyncio.create_task(
        run_subscription_task(
            next_job["task_name"],
            trigger=next_job.get("trigger", "queued"),
        )
    )


def queue_subscription_job(task_name: str, trigger: str) -> str:
    job_signature = safe_json_dumps({"task_name": task_name, "trigger": trigger})
    if any(item.get("job_signature") == job_signature for item in subscription_queue):
        schedule_ui_state_push(0)
        return "queued"
    subscription_queue.append(
        {
            "task_name": task_name,
            "trigger": trigger,
            "job_signature": job_signature,
        }
    )
    subscription_status["queued"] = [item["task_name"] for item in subscription_queue]
    schedule_ui_state_push(0)
    if subscription_status["running"]:
        return "queued"
    asyncio.create_task(start_next_subscription_job())
    return "started"
