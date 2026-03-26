import asyncio
import hashlib
import json
import os
import re
import shutil
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key="115-strm-v7-multi",
    https_only=False,
    same_site="lax",
)

CONFIG_PATH = "/app/config/settings.json"
DB_PATH = "/app/config/data.db"
TREE_DIR = "/app/config/trees"
STRM_ROOT = "/app/strm"
LOG_DIR = "/app/logs"
MAIN_LOG_PATH = os.path.join(LOG_DIR, "task.log")
MONITOR_LOG_PATH = os.path.join(LOG_DIR, "monitor.log")
DEFAULT_EXTENSIONS = "mp4,mkv,avi,mov,wmv,flv,webm,vob,mpg,mpeg,ts,m2ts,mts,rmvb,rm,asf,3gp,m4v,f4v,iso"
LEGACY_DEFAULT_EXTENSIONS = "mp4,mkv,avi,mov,ts,iso,rmvb,wmv,m4v,mpg,flac,mp3,ass,srt"
MAX_MONITOR_RETRIES = 5
VERSION_FILE = os.path.join(os.path.dirname(__file__), "version.json")
VERSION_SOURCE_URL = os.environ.get(
    "VERSION_SOURCE_URL",
    "https://raw.githubusercontent.com/xianer235/115-strm-web/main/version.json",
)
VERSION_CACHE_TTL = int(os.environ.get("VERSION_CACHE_TTL", 6 * 3600))


def ensure_parent(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)


def default_config() -> Dict[str, Any]:
    return {
        "username": "admin",
        "password": "admin123",
        "alist_url": "",
        "alist_token": "",
        "mount_path": "/115",
        "extensions": DEFAULT_EXTENSIONS,
        "trees": [{"url": "", "prefix": "", "exclude": 1}],
        "sync_mode": "incremental",
        "sync_clean": True,
        "check_hash": True,
        "cron_hour": "",
        "last_hash": "",
        "monitor_tasks": [],
    }


def normalize_task(task: Dict[str, Any]) -> Dict[str, Any]:
    name = str(task.get("name", "")).strip()
    retries = int(task.get("retries", 3) or 3)
    retries = max(1, min(MAX_MONITOR_RETRIES, retries))
    list_delay_ms = int(task.get("list_delay_ms", 0) or 0)
    min_file_size_mb = float(task.get("min_file_size_mb", 0) or 0)
    delay_seconds = int(task.get("delay_seconds", 0) or 0)
    cron_minutes = int(task.get("cron_minutes", 0) or 0)
    return {
        "name": name,
        "webhook_enabled": bool(task.get("webhook_enabled", False)),
        "scan_path": normalize_remote_path(task.get("scan_path", "")),
        "target_path": normalize_relative_path(task.get("target_path", "")),
        "skip_by_dir_mtime": bool(task.get("skip_by_dir_mtime", False)),
        "incremental": bool(task.get("incremental", False)),
        "retries": retries,
        "list_delay_ms": max(0, list_delay_ms),
        "min_file_size_mb": max(0, min_file_size_mb),
        "delay_seconds": max(0, delay_seconds),
        "cron_minutes": max(0, cron_minutes),
    }


def normalize_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    merged = default_config()
    merged.update(cfg or {})

    if "alist_token" not in merged:
        merged["alist_token"] = ""
    if "monitor_tasks" not in merged or not isinstance(merged["monitor_tasks"], list):
        merged["monitor_tasks"] = []

    merged["trees"] = merged.get("trees") or [{"url": "", "prefix": "", "exclude": 1}]
    if not str(merged.get("extensions", "")).strip() or merged.get("extensions") == LEGACY_DEFAULT_EXTENSIONS:
        merged["extensions"] = DEFAULT_EXTENSIONS
    normalized_trees = []
    for raw_tree in merged["trees"]:
        tree = raw_tree or {}
        try:
            exclude_val = int(tree.get("exclude", 1) or 1)
        except (TypeError, ValueError):
            exclude_val = 1
        normalized_trees.append(
            {
                "url": str(tree.get("url", "")).strip(),
                "prefix": str(tree.get("prefix", "")).strip(),
                "exclude": max(1, exclude_val),
            }
        )
    merged["trees"] = normalized_trees
    normalized_tasks = []
    seen_names = set()
    for raw_task in merged["monitor_tasks"]:
        task = normalize_task(raw_task or {})
        if task["name"] and task["name"] not in seen_names:
            normalized_tasks.append(task)
            seen_names.add(task["name"])
    merged["monitor_tasks"] = normalized_tasks
    merged["mount_path"] = normalize_remote_path(merged.get("mount_path", "/115"))
    merged["alist_url"] = str(merged.get("alist_url", "")).strip().rstrip("/")
    return merged


def load_local_version() -> Dict[str, Any]:
    try:
        with open(VERSION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            data["version"] = str(data.get("version", "dev")).strip() or "dev"
            return data
    except Exception:
        return {"version": "dev", "notes": [], "changelogUrl": "", "buildDate": ""}


def version_key(value: str) -> Tuple[int, ...]:
    tokens = [token for token in re.split(r"[^\d]+", str(value or "")) if token.isdigit()]
    if not tokens:
        return (0,)
    return tuple(int(token) for token in tokens)


def is_remote_version_newer(local_version: str, remote_version: str) -> bool:
    return version_key(remote_version) > version_key(local_version)


async def get_version_state(force_refresh: bool = False) -> Dict[str, Any]:
    local = load_local_version()
    now = time.time()
    latest = version_cache.get("latest")
    error = version_cache.get("error", "")
    should_refresh = force_refresh or (now - version_cache.get("checked_at", 0)) > VERSION_CACHE_TTL

    if should_refresh:
        try:
            latest = await asyncio.to_thread(http_request_json, VERSION_SOURCE_URL)
            version_cache["latest"] = latest
            version_cache["checked_at"] = now
            version_cache["error"] = ""
            error = ""
        except Exception as exc:
            error = str(exc)
            version_cache["error"] = error
            version_cache["checked_at"] = now

    latest_version = (latest or {}).get("version", "")
    has_update = bool(latest_version and is_remote_version_newer(local.get("version", ""), latest_version))
    return {
        "local": local,
        "latest": latest or {},
        "checked_at": version_cache.get("checked_at", 0),
        "has_update": has_update,
        "error": error,
        "source": VERSION_SOURCE_URL,
    }


def get_config() -> Dict[str, Any]:
    if not os.path.exists(CONFIG_PATH):
        ensure_parent(CONFIG_PATH)
        save_config(default_config())
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        raw_cfg = json.load(f)
    cfg = normalize_config(raw_cfg)
    if cfg != raw_cfg:
        save_config(cfg)
    return cfg


def save_config(cfg: Dict[str, Any]) -> None:
    ensure_parent(CONFIG_PATH)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(normalize_config(cfg), f, ensure_ascii=False, indent=2)


def ensure_db() -> None:
    ensure_parent(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS local_files (path_hash TEXT PRIMARY KEY, relative_path TEXT)"
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS monitor_files (
            task_name TEXT NOT NULL,
            local_rel_path TEXT NOT NULL,
            remote_rel_path TEXT NOT NULL,
            remote_modified TEXT,
            file_size INTEGER DEFAULT 0,
            PRIMARY KEY (task_name, local_rel_path)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS monitor_dirs (
            task_name TEXT NOT NULL,
            dir_rel_path TEXT NOT NULL,
            remote_modified TEXT,
            PRIMARY KEY (task_name, dir_rel_path)
        )
        """
    )
    conn.commit()
    conn.close()


def normalize_remote_path(path: str) -> str:
    path = "/" + "/".join([part for part in str(path or "").replace("\\", "/").split("/") if part])
    return path if path != "/" else "/"


def normalize_relative_path(path: str) -> str:
    return "/".join([part for part in str(path or "").replace("\\", "/").split("/") if part])


def join_remote_path(*parts: str) -> str:
    tokens: List[str] = []
    for part in parts:
        tokens.extend([p for p in str(part or "").replace("\\", "/").split("/") if p])
    return "/" + "/".join(tokens) if tokens else "/"


def join_relative_path(*parts: str) -> str:
    tokens: List[str] = []
    for part in parts:
        tokens.extend([p for p in str(part or "").replace("\\", "/").split("/") if p])
    return "/".join(tokens)


def basename(path: str) -> str:
    path = normalize_remote_path(path)
    if path == "/":
        return ""
    return path.rstrip("/").split("/")[-1]


def get_user_extensions(cfg: Dict[str, Any]) -> set:
    return {
        e.strip().lower()
        for e in str(cfg.get("extensions", DEFAULT_EXTENSIONS)).replace("，", ",").split(",")
        if e.strip()
    }


def is_video_file(name: str, extensions: set) -> bool:
    if "." not in name:
        return False
    return name.rsplit(".", 1)[-1].lower() in extensions


def format_log_time(with_year: bool = False) -> str:
    return datetime.now().strftime("%m-%d %H:%M:%S" if with_year else "%H:%M:%S")


def append_log_file(path: str, line: str) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def clear_log_file(path: str, first_line: str) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(first_line + "\n")


def validate_tree_runtime_config(cfg: Dict[str, Any], use_local: bool) -> Optional[str]:
    if use_local:
        return None
    if not str(cfg.get("alist_url", "")).strip():
        return "AList/OpenList 访问链接未填写"
    if not str(cfg.get("alist_token", "")).strip():
        return "AList/OpenList Token 未填写"
    if not str(cfg.get("mount_path", "")).strip():
        return "挂载根路径未填写"
    trees = [t for t in cfg.get("trees", []) if str((t or {}).get("url", "")).strip()]
    if not trees:
        return "未配置任何有效的目录树 URL"
    return None


def validate_monitor_runtime_config(cfg: Dict[str, Any], task: Dict[str, Any]) -> Optional[str]:
    if not str(cfg.get("alist_url", "")).strip():
        return "AList/OpenList 访问链接未填写"
    if not str(cfg.get("alist_token", "")).strip():
        return "AList/OpenList Token 未填写"
    if not str(task.get("scan_path", "")).strip():
        return "扫描路径未填写"
    if not str(task.get("target_path", "")).strip():
        return "目标路径未填写"
    return None


task_status = {
    "running": False,
    "next_run": None,
    "logs": ["系统已就绪"],
    "progress": {"step": "空闲", "percent": 0, "detail": "等待指令"},
}

monitor_status = {
    "running": False,
    "current_task": "",
    "queued": [],
    "logs": [{"text": "系统已就绪", "level": "info"}],
    "summary": {"step": "空闲", "detail": "等待监控任务"},
}
monitor_control = {"cancel": False}
monitor_queue: List[Dict[str, Any]] = []
monitor_last_run: Dict[str, float] = {}
monitor_next_run: Dict[str, str] = {}
version_cache: Dict[str, Any] = {"latest": None, "checked_at": 0.0, "error": ""}


def is_subpath(path: str, root: str) -> bool:
    path = normalize_remote_path(path)
    root = normalize_remote_path(root)
    return path == root or path.startswith(root + "/")


def extract_webhook_refresh_path(task: Dict[str, Any], payload: Dict[str, Any], cfg: Dict[str, Any]) -> Optional[str]:
    scan_path = normalize_remote_path(task.get("scan_path", ""))
    mount_path = normalize_remote_path(cfg.get("mount_path", "/115"))
    candidates: List[str] = []
    savepath_raw = str(payload.get("savepath", "") or "").strip()
    savepath_rel = normalize_relative_path(savepath_raw)
    sharetitle_raw = str(payload.get("sharetitle", "") or "").strip()
    sharetitle_rel = normalize_relative_path(sharetitle_raw)

    if savepath_rel and sharetitle_rel:
        # 优先定位本次转存子目录：savepath/sharetitle
        detailed_rel = join_relative_path(savepath_rel, sharetitle_rel)
        detailed_norm = normalize_remote_path("/" + detailed_rel)
        candidates.append(detailed_norm)
        candidates.append(join_remote_path(mount_path, detailed_norm))

    if savepath_rel:
        # savepath 支持 "连载中/xxx" 和 "/连载中/xxx" 两种写法
        save_norm = normalize_remote_path("/" + savepath_rel)
        candidates.append(save_norm)
        candidates.append(join_remote_path(mount_path, save_norm))

    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if is_subpath(candidate, scan_path):
            return candidate

    # 兼容常见格式：savepath 通常是去掉挂载根后的路径
    if savepath_rel:
        scan_tail = normalize_relative_path(scan_path[len(mount_path) :]) if scan_path.startswith(mount_path) else normalize_relative_path(scan_path)
        save_tail = savepath_rel
        if scan_tail and (scan_tail == save_tail or scan_tail.endswith("/" + save_tail) or save_tail.endswith("/" + scan_tail)):
            return scan_path
    return None


async def update_progress(step: str, percent: float, detail: str) -> None:
    task_status["progress"].update({"step": step, "percent": int(percent), "detail": detail})
    await asyncio.sleep(0)


async def write_log(msg: str) -> None:
    line = f"[{format_log_time()}] {msg}"
    task_status["logs"].append(line)
    if len(task_status["logs"]) > 500:
        task_status["logs"].pop(0)
    await asyncio.to_thread(append_log_file, MAIN_LOG_PATH, f"{format_log_time(True)} {msg}")
    await asyncio.sleep(0)


async def write_monitor_log(text: str, level: str = "info") -> None:
    line = f"{format_log_time(True)} {text}"
    monitor_status["logs"].append({"text": line, "level": level})
    if len(monitor_status["logs"]) > 800:
        monitor_status["logs"].pop(0)
    await asyncio.to_thread(append_log_file, MONITOR_LOG_PATH, line)
    await asyncio.sleep(0)


def update_monitor_summary(step: str, detail: str) -> None:
    monitor_status["summary"] = {"step": step, "detail": detail}


def check_monitor_cancelled() -> None:
    if monitor_control["cancel"]:
        raise asyncio.CancelledError()


async def sleep_interruptible(seconds: float) -> None:
    end_at = time.time() + max(0, seconds)
    while time.time() < end_at:
        check_monitor_cancelled()
        await asyncio.sleep(min(0.5, end_at - time.time()))


def normalize_http_url(url: str) -> str:
    """
    urllib 在请求行中要求 URL 为 ASCII；这里把包含中文等非 ASCII 的路径和查询参数安全编码。
    """
    parts = urllib.parse.urlsplit(str(url or "").strip())
    path = urllib.parse.quote(urllib.parse.unquote(parts.path), safe="/%:@+")
    query = urllib.parse.quote(urllib.parse.unquote(parts.query), safe="=&%:@,+")
    fragment = urllib.parse.quote(urllib.parse.unquote(parts.fragment), safe="%:@,+")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, query, fragment))


def http_request_json(
    url: str,
    method: str = "GET",
    payload: Optional[Dict[str, Any]] = None,
    token: str = "",
    timeout: int = 30,
) -> Dict[str, Any]:
    url = normalize_http_url(url)
    headers = {}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    if token:
        headers["Authorization"] = token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        body = resp.read().decode(charset, errors="ignore")
    return json.loads(body or "{}")


def http_download(url: str, target_path: str, token: str = "", timeout: int = 60) -> None:
    url = normalize_http_url(url)
    headers = {"Authorization": token} if token else {}
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(target_path, "wb") as f:
        shutil.copyfileobj(resp, f)


def extract_tree_remote_path(tree_url: str, base_url: str) -> Optional[str]:
    cleaned_url = str(tree_url or "").strip()
    base_url = str(base_url or "").strip().rstrip("/")
    if not cleaned_url or not base_url:
        return None

    if "://" not in cleaned_url:
        prefix = "" if cleaned_url.startswith("/") else "/"
        cleaned_url = f"{base_url}{prefix}{cleaned_url}"

    try:
        base_parts = urllib.parse.urlsplit(base_url)
        tree_parts = urllib.parse.urlsplit(cleaned_url)
    except Exception:
        return None

    if base_parts.netloc and tree_parts.netloc:
        if tree_parts.netloc.lower() != base_parts.netloc.lower():
            return None
    elif not cleaned_url.startswith(base_url):
        return None

    path = tree_parts.path or ""
    marker_idx = path.lower().find("/d")
    if marker_idx == -1:
        return None
    encoded = path[marker_idx + 2 :].lstrip("/")
    if not encoded:
        return None
    remote_path = urllib.parse.unquote(encoded)
    if not remote_path.startswith("/"):
        remote_path = "/" + remote_path.lstrip("/")
    return remote_path


async def refresh_tree_file(tree_url: str, cfg: Dict[str, Any]) -> None:
    remote_path = extract_tree_remote_path(tree_url, cfg.get("alist_url", ""))
    if not remote_path:
        return
    parent_dir = os.path.dirname(remote_path) or "/"
    try:
        await api_post(
            cfg,
            "/api/fs/list",
            {
                "path": parent_dir,
                "password": "",
                "page": 1,
                "per_page": 0,
                "refresh": True,
            },
        )
        await write_log(f"已刷新目录树所在目录: {parent_dir}")
    except Exception as exc:
        await write_log(f"⚠ 目录树刷新失败（{parent_dir}）: {exc}")


async def api_post(cfg: Dict[str, Any], path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = cfg["alist_url"].rstrip("/") + path
    token = str(cfg.get("alist_token", "")).strip()
    result = await asyncio.to_thread(http_request_json, url, "POST", payload, token, 45)
    if result.get("code") not in (200, None):
        raise RuntimeError(result.get("message") or result.get("msg") or "AList API 请求失败")
    return result


async def list_remote_dir(
    cfg: Dict[str, Any],
    remote_path: str,
    refresh: bool,
    task: Dict[str, Any],
) -> Tuple[str, List[Dict[str, Any]]]:
    retries = task["retries"]
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            result = await api_post(
                cfg,
                "/api/fs/list",
                {
                    "path": remote_path,
                    "password": "",
                    "page": 1,
                    "per_page": 0,
                    "refresh": refresh,
                },
            )
            content = result.get("data") or {}
            items = content.get("content") or []
            modified = str(content.get("modified") or "")
            return modified, items
        except Exception as exc:
            last_error = exc
            if attempt >= retries:
                break
            await write_monitor_log(
                f"读取失败，准备第 {attempt + 1} 次重试: {remote_path} ({exc})",
                "warn",
            )
            await asyncio.sleep(min(2, attempt))
    raise RuntimeError(str(last_error) if last_error else "目录读取失败")


async def download_tree(url: str, raw_path: str, cfg: Dict[str, Any]) -> None:
    token = str(cfg.get("alist_token", "")).strip()
    await asyncio.to_thread(http_download, url, raw_path, token, 120)


def parse_last_hash_state(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        return {}
    return {}


def build_tree_cache_key(tree: Dict[str, Any]) -> str:
    exclude_val = 1
    try:
        exclude_val = max(1, int(tree.get("exclude", 1) or 1))
    except (TypeError, ValueError):
        exclude_val = 1
    payload = {
        "url": str(tree.get("url", "")).strip(),
        "prefix": normalize_relative_path(tree.get("prefix", "")),
        "exclude": exclude_val,
    }
    return hashlib.md5(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def build_tree_parse_signature(content_hash: str, extensions: set) -> str:
    payload = {
        "content_hash": content_hash,
        "extensions": sorted(extensions),
    }
    return hashlib.md5(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def calculate_file_md5(path: str) -> str:
    digest = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def load_tree_cache(cache_path: str) -> Optional[List[str]]:
    if not os.path.exists(cache_path):
        return None
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    if not isinstance(data, list):
        return None
    results: List[str] = []
    for item in data:
        rel = normalize_relative_path(item)
        if rel:
            results.append(rel)
    return results


def save_tree_cache(cache_path: str, rel_paths: List[str]) -> None:
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(rel_paths, f, ensure_ascii=False)


async def run_sync(use_local: bool = False, force_full: bool = False) -> None:
    if task_status["running"]:
        return
    task_status["running"] = True
    cfg = get_config()
    os.makedirs(TREE_DIR, exist_ok=True)
    ensure_db()

    try:
        config_error = validate_tree_runtime_config(cfg, use_local)
        if config_error:
            raise RuntimeError(config_error)

        trees = [t for t in cfg.get("trees", []) if t.get("url")]
        downloaded_tree_count = 0

        scan_results: List[str] = []
        user_exts = get_user_extensions(cfg)
        check_hash_enabled = bool(cfg.get("check_hash", False))
        can_skip_by_hash = check_hash_enabled and cfg.get("sync_mode") != "full" and not force_full
        last_hash_state = parse_last_hash_state(cfg.get("last_hash", ""))
        last_tree_hashes = last_hash_state.get("trees", {}) if isinstance(last_hash_state.get("trees", {}), dict) else {}
        last_tree_keys = last_hash_state.get("tree_keys", []) if isinstance(last_hash_state.get("tree_keys", []), list) else []
        current_tree_hashes: Dict[str, Dict[str, str]] = {}
        current_tree_keys: List[str] = []
        skipped_tree_count = 0
        parsed_tree_count = 0
        if check_hash_enabled and not can_skip_by_hash:
            await write_log("ℹ 已开启 MD5 校验，但当前为全量模式，跳过策略不生效")
        await write_log(
            f"开始目录树任务：源 {len(trees)} 个，模式 {cfg.get('sync_mode', 'incremental')}，MD5校验 {'开' if check_hash_enabled else '关'}"
        )

        for idx, tree in enumerate(trees):
            raw_path = f"{TREE_DIR}/tree_{idx}.raw"
            txt_path = f"{TREE_DIR}/tree_{idx}.txt"
            tree_key = build_tree_cache_key(tree)
            current_tree_keys.append(tree_key)
            tree_cache_path = os.path.join(TREE_DIR, f"cache_{tree_key}.json")
            tree_scan_results: List[str] = []
            parse_signature = ""

            if not use_local:
                await refresh_tree_file(tree["url"], cfg)
                await update_progress("正在下载", (idx / max(len(trees), 1) * 15), f"获取第 {idx + 1} 个目录树...")
                await download_tree(tree["url"], raw_path, cfg)
                downloaded_tree_count += 1

            if os.path.exists(raw_path):
                file_hash = await asyncio.to_thread(calculate_file_md5, raw_path)
                parse_signature = build_tree_parse_signature(file_hash, user_exts)
                if can_skip_by_hash:
                    old_state = last_tree_hashes.get(tree_key, {})
                    old_signature = old_state.get("parse_signature", "") if isinstance(old_state, dict) else ""
                    if old_signature and old_signature == parse_signature:
                        cached_paths = await asyncio.to_thread(load_tree_cache, tree_cache_path)
                        if cached_paths is not None:
                            skipped_tree_count += 1
                            scan_results.extend(cached_paths)
                            current_tree_hashes[tree_key] = {"parse_signature": parse_signature}
                            await write_log(f"第 {idx + 1} 个目录树 MD5 无变化，复用缓存 {len(cached_paths)} 条")
                            continue

            if os.path.exists(raw_path):
                await update_progress("正在转码", 15 + (idx / max(len(trees), 1) * 5), f"转码目录树 {idx + 1}...")
                proc = await asyncio.create_subprocess_exec(
                    "iconv",
                    "-f",
                    "UTF-16LE",
                    "-t",
                    "UTF-8//IGNORE",
                    raw_path,
                    "-o",
                    txt_path,
                )
                code = await proc.wait()
                if code != 0:
                    raise RuntimeError(f"目录树 {idx + 1} 转码失败，退出码: {code}")

            parsed_this_tree = False
            if os.path.exists(txt_path):
                await update_progress("解析中", 20 + (idx / max(len(trees), 1) * 20), f"处理第 {idx + 1} 个结构...")
                path_stack: Dict[int, str] = {}
                prefix = normalize_relative_path(tree.get("prefix", ""))
                exclude = int(tree.get("exclude", 1) or 1)
                parsed_this_tree = True
                with open(txt_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        level = line.count("|")
                        clean_name = re.sub(r"^[|\s—-]+", "", line).strip()
                        if not clean_name:
                            continue
                        path_stack[level] = clean_name
                        if is_video_file(clean_name, user_exts):
                            full_parts = [path_stack[l] for l in range(level + 1) if l in path_stack]
                            rel_parts = full_parts[exclude:]
                            final_rel_path = join_relative_path(prefix, "/".join(rel_parts))
                            if final_rel_path:
                                tree_scan_results.append(final_rel_path)
                                scan_results.append(final_rel_path)

            if parse_signature:
                current_tree_hashes[tree_key] = {"parse_signature": parse_signature}
            if parsed_this_tree:
                parsed_tree_count += 1
                await asyncio.to_thread(save_tree_cache, tree_cache_path, tree_scan_results)

        if check_hash_enabled:
            cfg["last_hash"] = json.dumps(
                {"version": 2, "tree_keys": current_tree_keys, "trees": current_tree_hashes},
                ensure_ascii=False,
                sort_keys=True,
            )
            save_config(cfg)

        tree_layout_changed = sorted(last_tree_keys) != sorted(current_tree_keys)
        if can_skip_by_hash and trees and skipped_tree_count == len(trees) and tree_layout_changed:
            await write_log("ℹ 目录树源配置有变更，继续执行同步以校正结果")
        if can_skip_by_hash and trees and skipped_tree_count == len(trees) and not tree_layout_changed:
            await write_log(f"本轮概况：下载 {downloaded_tree_count} 个，缓存复用 {skipped_tree_count} 个，解析 {parsed_tree_count} 个")
            await write_log("✅ MD5 校验命中：全部目录树无变动，跳过解析与同步")
            await update_progress("任务完成", 100, "MD5 校验命中：无变动")
            return

        total_files = len(scan_results)
        await write_log(f"本轮概况：下载 {downloaded_tree_count} 个，缓存复用 {skipped_tree_count} 个，解析 {parsed_tree_count} 个")
        await write_log(f"解析完成，共发现 {total_files} 个有效文件")
        if total_files == 0:
            if downloaded_tree_count > 0 or use_local:
                await write_log("⚠ 目录树下载成功，但未匹配到可生成文件；本次按成功结束并跳过清理")
                await update_progress("任务完成", 100, "目录树下载成功，但未匹配可生成文件")
                return
            raise RuntimeError("扫描结果为空，且未成功下载目录树")

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("CREATE TEMP TABLE current_scan (path_hash TEXT PRIMARY KEY, relative_path TEXT)")

        alist_base = cfg["alist_url"].rstrip("/")
        mount_path = cfg["mount_path"].strip("/")

        for i, rel_path in enumerate(scan_results):
            target = os.path.join(STRM_ROOT, rel_path + ".strm")
            if not os.path.exists(target) or cfg["sync_mode"] == "full" or force_full:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                encoded_path = urllib.parse.quote(f"/{mount_path}/{rel_path}")
                with open(target, "w", encoding="utf-8") as sf:
                    sf.write(f"{alist_base}/d{encoded_path}")

            path_hash = hashlib.md5(rel_path.encode("utf-8")).hexdigest()
            cursor.execute("INSERT OR IGNORE INTO current_scan VALUES (?, ?)", (path_hash, rel_path))
            if total_files and i % 1000 == 0:
                await update_progress("生成STRM", 40 + (i / total_files * 50), f"进度: {i}/{total_files}")

        if cfg.get("sync_clean", True):
            cursor.execute(
                "SELECT relative_path FROM local_files WHERE path_hash NOT IN (SELECT path_hash FROM current_scan)"
            )
            for (dead_path,) in cursor.fetchall():
                target = os.path.join(STRM_ROOT, dead_path + ".strm")
                if os.path.exists(target):
                    os.remove(target)

        # 无论是否启用物理清理，数据库都应只保留本轮扫描结果，避免陈旧数据长期累积
        cursor.execute("DELETE FROM local_files WHERE path_hash NOT IN (SELECT path_hash FROM current_scan)")

        cursor.execute("INSERT OR REPLACE INTO local_files SELECT * FROM current_scan")
        conn.commit()
        conn.close()
        await update_progress("任务完成", 100, f"同步成功: {total_files} 文件")
        await write_log("✅ 任务结束")
    except Exception as exc:
        await write_log(f"❌ 运行故障: {exc}")
        await update_progress("任务中止", 0, str(exc))
    finally:
        task_status["running"] = False


def resolve_task_root(task: Dict[str, Any]) -> str:
    root_name = basename(task["scan_path"])
    target_path = normalize_relative_path(task.get("target_path", ""))
    if not target_path:
        return root_name
    target_parts = [p for p in target_path.split("/") if p]
    if root_name and target_parts and target_parts[-1] == root_name:
        return target_path
    return join_relative_path(target_path, root_name)


def write_strm_file(target_file: str, url: str) -> bool:
    old_content = None
    if os.path.exists(target_file):
        with open(target_file, "r", encoding="utf-8", errors="ignore") as f:
            old_content = f.read()
    if old_content == url:
        return False
    os.makedirs(os.path.dirname(target_file), exist_ok=True)
    with open(target_file, "w", encoding="utf-8") as f:
        f.write(url)
    return True


def remove_empty_parent_dirs(start_dir: str, stop_dir: str) -> int:
    removed = 0
    current = start_dir
    while current.startswith(stop_dir) and current != stop_dir:
        if os.path.isdir(current) and not os.listdir(current):
            os.rmdir(current)
            removed += 1
            current = os.path.dirname(current)
            continue
        break
    return removed


async def mark_cached_dir_as_seen(
    conn: sqlite3.Connection,
    task_name: str,
    local_prefix: str,
) -> None:
    cursor = conn.cursor()
    like_prefix = f"{local_prefix}/%" if local_prefix else "%"
    cursor.execute(
        """
        INSERT OR REPLACE INTO current_scan (local_rel_path, remote_rel_path, remote_modified, file_size)
        SELECT local_rel_path, remote_rel_path, remote_modified, file_size
        FROM monitor_files
        WHERE task_name = ? AND (local_rel_path = ? OR local_rel_path LIKE ?)
        """,
        (task_name, local_prefix, like_prefix),
    )
    await asyncio.sleep(0)


async def run_monitor_task(task_name: str, trigger: str = "manual", payload: Optional[Dict[str, Any]] = None) -> None:
    cfg = get_config()
    task = next((t for t in cfg["monitor_tasks"] if t["name"] == task_name), None)
    if not task:
        await write_monitor_log(f"任务不存在: {task_name}", "error")
        return
    config_error = validate_monitor_runtime_config(cfg, task)
    if config_error:
        await write_monitor_log(f"任务配置错误: {config_error}", "error")
        update_monitor_summary("任务失败", config_error)
        return

    if monitor_status["running"]:
        return

    ensure_db()
    monitor_status["running"] = True
    monitor_status["current_task"] = task_name
    monitor_control["cancel"] = False
    monitor_last_run[task_name] = time.time()
    update_monitor_summary("准备执行", f"{task_name} ({trigger})")
    run_delay = task["delay_seconds"]
    webhook_delay = 0
    if payload:
        webhook_delay = int(payload.get("delayTime", 0) or 0)
    if webhook_delay > 0:
        run_delay = webhook_delay

    stats = {
        "generated": 0,
        "updated": 0,
        "skipped": 0,
        "skipped_dirs": 0,
        "failed_dirs": 0,
        "deleted_files": 0,
        "deleted_dirs": 0,
        "success_dirs": 0,
    }

    await write_monitor_log(f"开始任务: {task_name}", "info")
    await write_monitor_log(f"━━━━━━━━━━【任务开始 | {task_name} | {trigger}】━━━━━━━━━━", "divider")
    await write_monitor_log("任务类型: 生成 STRM", "info")
    await write_monitor_log(f"远端路径: {task['scan_path']}", "info")
    if trigger == "webhook" and payload:
        title = str(payload.get("title", "") or "").strip()
        sharetitle = str(payload.get("sharetitle", "") or "").strip()
        if title:
            await write_monitor_log(f"转存内容：{title}", "info")
        if sharetitle:
            await write_monitor_log(f"转存目录名：{sharetitle}", "info")
    await write_monitor_log(f"增量同步: {str(task['incremental'])}", "info")
    await write_monitor_log(f"目录时间检查: {str(task['skip_by_dir_mtime'])}", "info")
    await write_monitor_log(f"保存目录: /strm/{resolve_task_root(task)}", "info")
    await write_monitor_log("=" * 50, "divider")

    try:
        if run_delay > 0:
            update_monitor_summary("等待延时", f"{run_delay} 秒后执行")
            await write_monitor_log(f"任务执行延时: {run_delay} 秒", "warn")
            await sleep_interruptible(run_delay)
        check_monitor_cancelled()

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "CREATE TEMP TABLE current_scan (local_rel_path TEXT PRIMARY KEY, remote_rel_path TEXT, remote_modified TEXT, file_size INTEGER)"
        )

        task_root = resolve_task_root(task)
        alist_base = cfg["alist_url"].rstrip("/")
        extensions = get_user_extensions(cfg)
        min_bytes = int(task["min_file_size_mb"] * 1024 * 1024)
        start_remote_path = normalize_remote_path(task["scan_path"])
        if trigger == "webhook" and payload:
            hinted_path = extract_webhook_refresh_path(task, payload, cfg)
            if hinted_path:
                start_remote_path = hinted_path
                await write_monitor_log(f"Webhook 定位刷新目录: {start_remote_path}", "info")
            else:
                await write_monitor_log("Webhook 未识别到有效子目录，回退全任务路径刷新", "warn")

        local_sub_rel = normalize_relative_path(
            os.path.relpath(start_remote_path, task["scan_path"])
        ) if start_remote_path != task["scan_path"] else ""
        start_local_rel = join_relative_path(task_root, local_sub_rel)
        queue: List[Tuple[str, str, bool]] = [(start_remote_path, start_local_rel, True)]
        seen_dirs = set()

        await write_monitor_log(">>> 开始生成", "info")

        while queue:
            remote_dir, local_dir_rel, do_refresh = queue.pop(0)
            check_monitor_cancelled()
            if remote_dir in seen_dirs:
                continue
            seen_dirs.add(remote_dir)

            update_monitor_summary("扫描目录", remote_dir)
            await write_monitor_log(f"读取目录: {remote_dir}", "info")

            try:
                modified, items = await list_remote_dir(cfg, remote_dir, do_refresh, task)
                stats["success_dirs"] += 1
            except Exception as exc:
                stats["failed_dirs"] += 1
                await write_monitor_log(f"读取目录失败: {remote_dir} ({exc})", "error")
                continue

            dir_rel = normalize_relative_path(os.path.relpath(local_dir_rel, task_root)) if local_dir_rel != task_root else ""
            if task["skip_by_dir_mtime"] and modified:
                cursor.execute(
                    "SELECT remote_modified FROM monitor_dirs WHERE task_name = ? AND dir_rel_path = ?",
                    (task_name, dir_rel),
                )
                row = cursor.fetchone()
                if row and row[0] and row[0] >= modified:
                    stats["skipped_dirs"] += 1
                    await mark_cached_dir_as_seen(conn, task_name, local_dir_rel)
                    await write_monitor_log(f"跳过目录: {remote_dir}", "warn")
                    if task["list_delay_ms"] > 0:
                        await sleep_interruptible(task["list_delay_ms"] / 1000)
                    continue

            cursor.execute(
                "INSERT OR REPLACE INTO monitor_dirs(task_name, dir_rel_path, remote_modified) VALUES (?, ?, ?)",
                (task_name, dir_rel, modified),
            )

            for item in items:
                check_monitor_cancelled()
                name = item.get("name") or ""
                if not name:
                    continue

                item_remote_path = join_remote_path(remote_dir, name)
                item_local_rel = join_relative_path(local_dir_rel, name)
                is_dir = bool(item.get("is_dir"))
                modified_at = str(item.get("modified") or "")
                size = int(item.get("size") or 0)

                if is_dir:
                    queue.append((item_remote_path, item_local_rel, False))
                    continue

                if not is_video_file(name, extensions):
                    stats["skipped"] += 1
                    continue
                if min_bytes > 0 and size < min_bytes:
                    stats["skipped"] += 1
                    continue

                target_file = os.path.join(STRM_ROOT, item_local_rel + ".strm")
                encoded_path = urllib.parse.quote(item_remote_path)
                strm_url = f"{alist_base}/d{encoded_path}"
                changed = await asyncio.to_thread(write_strm_file, target_file, strm_url)
                if changed:
                    stats["generated"] += 1
                    await write_monitor_log(f"生成: {target_file}", "success")
                else:
                    stats["skipped"] += 1

                remote_rel = normalize_relative_path(os.path.relpath(item_remote_path, task["scan_path"]))
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO current_scan(local_rel_path, remote_rel_path, remote_modified, file_size)
                    VALUES (?, ?, ?, ?)
                    """,
                    (item_local_rel, remote_rel, modified_at, size),
                )

            if task["list_delay_ms"] > 0:
                await sleep_interruptible(task["list_delay_ms"] / 1000)

        await write_monitor_log(">>> 开始清理", "info")
        await write_monitor_log(f"检查目录: {task['scan_path']}", "info")
        if stats["success_dirs"] == 0:
            raise RuntimeError("未成功读取任何目录，已停止并跳过清理（避免误删本地文件）")

        if not task["incremental"] and stats["failed_dirs"] == 0:
            if start_local_rel == task_root:
                cursor.execute(
                    """
                    SELECT local_rel_path FROM monitor_files
                    WHERE task_name = ?
                    AND local_rel_path NOT IN (SELECT local_rel_path FROM current_scan)
                    """,
                    (task_name,),
                )
            else:
                scope_like = f"{start_local_rel}/%"
                cursor.execute(
                    """
                    SELECT local_rel_path FROM monitor_files
                    WHERE task_name = ?
                    AND (local_rel_path = ? OR local_rel_path LIKE ?)
                    AND local_rel_path NOT IN (SELECT local_rel_path FROM current_scan)
                    """,
                    (task_name, start_local_rel, scope_like),
                )
            stale_files = [row[0] for row in cursor.fetchall()]
            for local_rel_path in stale_files:
                check_monitor_cancelled()
                target_file = os.path.join(STRM_ROOT, local_rel_path + ".strm")
                if os.path.exists(target_file):
                    os.remove(target_file)
                    stats["deleted_files"] += 1
                    stats["deleted_dirs"] += remove_empty_parent_dirs(
                        os.path.dirname(target_file), os.path.join(STRM_ROOT, task_root)
                    )

            if start_local_rel == task_root:
                cursor.execute("DELETE FROM monitor_files WHERE task_name = ?", (task_name,))
            else:
                scope_like = f"{start_local_rel}/%"
                cursor.execute(
                    """
                    DELETE FROM monitor_files
                    WHERE task_name = ? AND (local_rel_path = ? OR local_rel_path LIKE ?)
                    """,
                    (task_name, start_local_rel, scope_like),
                )

        else:
            if not task["incremental"] and stats["failed_dirs"] > 0:
                await write_monitor_log("检测到目录读取失败，已自动跳过清理阶段以防误删", "warn")
            cursor.execute(
                """
                DELETE FROM monitor_files
                WHERE task_name = ? AND local_rel_path IN (SELECT local_rel_path FROM current_scan)
                """,
                (task_name,),
            )

        cursor.execute(
            """
            INSERT OR REPLACE INTO monitor_files(task_name, local_rel_path, remote_rel_path, remote_modified, file_size)
            SELECT ?, local_rel_path, remote_rel_path, remote_modified, file_size FROM current_scan
            """,
            (task_name,),
        )
        conn.commit()
        conn.close()
        conn = None

        await write_monitor_log(
            f"【生成文件完成】 生成 {stats['generated']} 个，复制 0 个，跳过 {stats['skipped']} 个，跳过目录 {stats['skipped_dirs']} 个，读取目录失败 {stats['failed_dirs']} 个",
            "info",
        )
        await write_monitor_log(
            f"【清理文件完成】 清理目录 {stats['deleted_dirs']} 个，清理文件 {stats['deleted_files']} 个，跳过目录 0 个",
            "info",
        )
        await write_monitor_log("任务完成", "success")
        await write_monitor_log(f"━━━━━━━━━━【任务结束 | {task_name} | 成功】━━━━━━━━━━", "divider")
        update_monitor_summary("任务完成", f"{task_name} 执行结束")
    except asyncio.CancelledError:
        await write_monitor_log("任务已中断", "error")
        await write_monitor_log(f"━━━━━━━━━━【任务结束 | {task_name} | 中断】━━━━━━━━━━", "divider")
        update_monitor_summary("任务中断", task_name)
    except Exception as exc:
        await write_monitor_log(f"任务失败: {exc}", "error")
        await write_monitor_log(f"━━━━━━━━━━【任务结束 | {task_name} | 失败】━━━━━━━━━━", "divider")
        update_monitor_summary("任务失败", str(exc))
    finally:
        try:
            if "conn" in locals() and conn is not None:
                conn.close()
        except Exception:
            pass
        monitor_status["running"] = False
        monitor_status["current_task"] = ""
        monitor_control["cancel"] = False
        await start_next_monitor_job()


async def start_next_monitor_job() -> None:
    if monitor_status["running"] or not monitor_queue:
        monitor_status["queued"] = [item["task_name"] for item in monitor_queue]
        return
    next_job = monitor_queue.pop(0)
    monitor_status["queued"] = [item["task_name"] for item in monitor_queue]
    asyncio.create_task(
        run_monitor_task(
            next_job["task_name"],
            trigger=next_job.get("trigger", "queued"),
            payload=next_job.get("payload"),
        )
    )


def queue_monitor_job(task_name: str, trigger: str, payload: Optional[Dict[str, Any]] = None) -> str:
    if any(item["task_name"] == task_name for item in monitor_queue):
        return "queued"
    monitor_queue.append({"task_name": task_name, "trigger": trigger, "payload": payload or {}})
    monitor_status["queued"] = [item["task_name"] for item in monitor_queue]
    if monitor_status["running"]:
        return "queued"
    asyncio.create_task(start_next_monitor_job())
    return "started"


@app.on_event("startup")
async def startup() -> None:
    ensure_db()
    os.makedirs(LOG_DIR, exist_ok=True)

    async def scheduler() -> None:
        await asyncio.sleep(5)
        last_run = time.time()
        while True:
            cfg = get_config()
            interval = cfg.get("cron_hour")
            if interval and str(interval).isdigit():
                interval_min = int(interval)
                next_ts = last_run + (interval_min * 60)
                task_status["next_run"] = datetime.fromtimestamp(next_ts).strftime("%H:%M:%S")
                if time.time() >= next_ts and not task_status["running"]:
                    last_run = time.time()
                    asyncio.create_task(run_sync())
            else:
                task_status["next_run"] = None
            await asyncio.sleep(5)

    async def monitor_scheduler() -> None:
        await asyncio.sleep(5)
        while True:
            now = time.time()
            cfg = get_config()
            tasks = cfg.get("monitor_tasks", [])
            active_names = {task.get("name", "") for task in tasks if task.get("name")}

            for dead_name in list(monitor_last_run.keys()):
                if dead_name not in active_names:
                    monitor_last_run.pop(dead_name, None)
                    monitor_next_run.pop(dead_name, None)

            for task in tasks:
                name = task.get("name", "")
                cron_minutes = int(task.get("cron_minutes", 0) or 0)
                if not name:
                    continue
                if cron_minutes <= 0:
                    monitor_next_run.pop(name, None)
                    continue

                if name not in monitor_last_run:
                    monitor_last_run[name] = now
                next_ts = monitor_last_run[name] + (cron_minutes * 60)
                monitor_next_run[name] = datetime.fromtimestamp(next_ts).strftime("%H:%M:%S")
                if now >= next_ts:
                    queue_monitor_job(name, "cron")
            await asyncio.sleep(5)

    asyncio.create_task(scheduler())
    asyncio.create_task(monitor_scheduler())


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> str:
    with open("templates/login.html", "r", encoding="utf-8") as f:
        return f.read()


@app.post("/login")
async def do_login(request: Request) -> JSONResponse:
    data = await request.json()
    cfg = get_config()
    if data.get("username") == cfg.get("username") and data.get("password") == cfg.get("password"):
        request.session["logged_in"] = True
        return JSONResponse(content={"ok": True})
    return JSONResponse(status_code=401, content={"ok": False, "msg": "密码错误"})


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    if not request.session.get("logged_in"):
        return RedirectResponse(url="/login")
    with open("templates/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/get_settings")
async def get_settings(request: Request) -> Dict[str, Any]:
    return get_config()


@app.get("/version")
async def get_version_endpoint(request: Request) -> Dict[str, Any]:
    force = request.query_params.get("refresh") == "1"
    return await get_version_state(force_refresh=force)


@app.post("/save_settings")
async def save_settings(request: Request) -> Dict[str, Any]:
    incoming = await request.json()
    cfg = get_config()
    cfg.update(incoming)
    cfg["monitor_tasks"] = [normalize_task(task) for task in incoming.get("monitor_tasks", cfg.get("monitor_tasks", []))]
    save_config(cfg)
    return {"ok": True}


@app.post("/start")
async def start_sync(request: Request, bt: BackgroundTasks) -> Dict[str, str]:
    data = await request.json()
    if not task_status["running"]:
        bt.add_task(run_sync, use_local=data.get("use_local", False), force_full=data.get("force_full", False))
        return {"status": "started"}
    return {"status": "busy"}


@app.get("/logs")
async def get_logs(request: Request) -> Dict[str, Any]:
    return task_status


@app.post("/logs/clear")
async def clear_logs(request: Request) -> Dict[str, Any]:
    task_status["logs"] = ["系统日志已清空"]
    await asyncio.to_thread(clear_log_file, MAIN_LOG_PATH, f"{format_log_time(True)} 系统日志已清空")
    return {"ok": True}


@app.get("/monitor/status")
async def get_monitor_status(request: Request) -> Dict[str, Any]:
    cfg = get_config()
    return {
        **monitor_status,
        "tasks": cfg.get("monitor_tasks", []),
        "webhook_base": "/webhook/",
        "next_runs": monitor_next_run,
    }


@app.post("/monitor/logs/clear")
async def clear_monitor_logs(request: Request) -> Dict[str, Any]:
    monitor_status["logs"] = [{"text": f"{format_log_time(True)} 监控日志已清空", "level": "info"}]
    await asyncio.to_thread(clear_log_file, MONITOR_LOG_PATH, f"{format_log_time(True)} 监控日志已清空")
    return {"ok": True}


@app.post("/monitor/save")
async def save_monitor_tasks(request: Request) -> Dict[str, Any]:
    data = await request.json()
    cfg = get_config()
    tasks = data.get("tasks", [])
    normalized = []
    names = set()
    for raw_task in tasks:
        task = normalize_task(raw_task)
        if not task["name"]:
            continue
        if task["name"] in names:
            return JSONResponse(status_code=400, content={"ok": False, "msg": f"任务名重复: {task['name']}"})
        names.add(task["name"])
        normalized.append(task)
    cfg["monitor_tasks"] = normalized
    save_config(cfg)
    alive = {task["name"] for task in normalized}
    for dead_name in list(monitor_last_run.keys()):
        if dead_name not in alive:
            monitor_last_run.pop(dead_name, None)
            monitor_next_run.pop(dead_name, None)
    return {"ok": True, "tasks": normalized}


@app.post("/monitor/start")
async def start_monitor(request: Request) -> Dict[str, Any]:
    data = await request.json()
    task_name = str(data.get("name", "")).strip()
    cfg = get_config()
    if not any(task["name"] == task_name for task in cfg["monitor_tasks"]):
        return JSONResponse(status_code=404, content={"ok": False, "msg": "任务不存在"})
    status = queue_monitor_job(task_name, "manual")
    return {"ok": True, "status": status}


@app.post("/monitor/stop")
async def stop_monitor(request: Request) -> Dict[str, Any]:
    data = await request.json()
    task_name = str(data.get("name", "")).strip()
    if monitor_status["running"] and monitor_status["current_task"] == task_name:
        monitor_control["cancel"] = True
        return {"ok": True, "status": "stopping"}
    return {"ok": False, "status": "idle"}


@app.post("/monitor/delete")
async def delete_monitor(request: Request) -> Dict[str, Any]:
    data = await request.json()
    task_name = str(data.get("name", "")).strip()
    cfg = get_config()
    before = len(cfg["monitor_tasks"])
    cfg["monitor_tasks"] = [task for task in cfg["monitor_tasks"] if task["name"] != task_name]
    if len(cfg["monitor_tasks"]) == before:
        return JSONResponse(status_code=404, content={"ok": False, "msg": "任务不存在"})
    save_config(cfg)
    monitor_queue[:] = [item for item in monitor_queue if item["task_name"] != task_name]
    monitor_status["queued"] = [item["task_name"] for item in monitor_queue]
    monitor_last_run.pop(task_name, None)
    monitor_next_run.pop(task_name, None)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM monitor_files WHERE task_name = ?", (task_name,))
    cursor.execute("DELETE FROM monitor_dirs WHERE task_name = ?", (task_name,))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.post("/webhook/{task_name}")
async def webhook(task_name: str, request: Request) -> JSONResponse:
    payload = await request.json()
    cfg = get_config()
    task = next((task for task in cfg["monitor_tasks"] if task["name"] == task_name), None)
    if not task:
        return JSONResponse(status_code=404, content={"ok": False, "msg": "未找到对应监控任务"})
    if not task.get("webhook_enabled"):
        return JSONResponse(status_code=400, content={"ok": False, "msg": "该任务未开启 webhook"})
    title = str(payload.get("title", "") or "").strip()
    savepath = str(payload.get("savepath", "") or "").strip()
    sharetitle = str(payload.get("sharetitle", "") or "").strip()

    queue_monitor_job(task_name, "webhook", payload)
    await write_monitor_log(
        f"收到 webhook: {task_name} savepath={savepath or '(未传)'} sharetitle={sharetitle or '(空)'} delayTime={payload.get('delayTime', 0)}",
        "info",
    )
    if title:
        await write_monitor_log(f"转存内容：{title}", "info")
    return JSONResponse(content=payload)


@app.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/login")
