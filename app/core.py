import asyncio
import hashlib
import json
import os
import re
import shutil
import sqlite3
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from html import unescape
from typing import Any, AsyncIterator, Dict, List, Optional, Set, Tuple

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
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
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
VERSION_FILE = os.path.join(BASE_DIR, "version.json")
VERSION_SOURCE_URL = os.environ.get(
    "VERSION_SOURCE_URL",
    "https://raw.githubusercontent.com/xianer235/115-strm-web/main/version.json",
)
VERSION_CACHE_TTL = int(os.environ.get("VERSION_CACHE_TTL", 6 * 3600))
UI_EVENT_RETRY_MS = 3000
UI_HEARTBEAT_SECONDS = 15
UI_PUSH_DEBOUNCE_SECONDS = 0.15
TG_SYNC_TTL_SECONDS = 5 * 60
RESOURCE_CHANNEL_CACHE_LIMIT = max(10, int(os.environ.get("RESOURCE_CHANNEL_CACHE_LIMIT", 40) or 40))
TG_SEARCH_PAGE_LIMIT = max(10, int(os.environ.get("TG_SEARCH_PAGE_LIMIT", 20) or 20))
TG_SEARCH_MAX_PAGES = max(1, int(os.environ.get("TG_SEARCH_MAX_PAGES", 6) or 6))
TG_SEARCH_MATCH_LIMIT_PER_CHANNEL = max(1, int(os.environ.get("TG_SEARCH_MATCH_LIMIT_PER_CHANNEL", 12) or 12))
TG_SEARCH_TOTAL_LIMIT = max(TG_SEARCH_MATCH_LIMIT_PER_CHANNEL, int(os.environ.get("TG_SEARCH_TOTAL_LIMIT", 60) or 60))
TG_SEARCH_CHANNEL_TIMEOUT_SECONDS = max(5, int(os.environ.get("TG_SEARCH_CHANNEL_TIMEOUT_SECONDS", 15) or 15))
TG_FETCH_RETRY_ATTEMPTS = max(1, int(os.environ.get("TG_FETCH_RETRY_ATTEMPTS", 3) or 3))
TG_FETCH_RETRY_DELAY_SECONDS = max(0.2, float(os.environ.get("TG_FETCH_RETRY_DELAY_SECONDS", 0.8) or 0.8))
STATIC_DIR = os.path.join(BASE_DIR, "static")
FAVICON_PATH = os.path.join(STATIC_DIR, "icons", "favicon.svg")
RESOURCE_MAGNET_REGEX = re.compile(r"magnet:\?xt=urn:btih:[A-Za-z0-9]{32,40}[^\s<>'\"]*", re.IGNORECASE)
RESOURCE_URL_REGEX = re.compile(r"https?://[^\s<>'\"]+", re.IGNORECASE)
RESOURCE_YEAR_REGEX = re.compile(r"\b(19\d{2}|20\d{2})\b")
TG_WIDGET_POST_REGEX = re.compile(r'<div[^>]+class="tgme_widget_message[^"]*"[^>]+data-post="([^"]+)"[^>]*>', re.IGNORECASE)
TG_LINK_HREF_REGEX = re.compile(r'href="([^"]+)"', re.IGNORECASE)
TG_IMAGE_STYLE_REGEX = re.compile(r"background-image:url\('([^']+)'\)", re.IGNORECASE)
TG_PREV_BEFORE_REGEX = re.compile(r'rel="prev"[^>]+href="[^"]*before=([^"&]+)', re.IGNORECASE)
TG_EXTRACT_CODE_REGEX = re.compile(r"(?:提取码|访问码|密码)[:：\s]*([A-Za-z0-9]{4,8})", re.IGNORECASE)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def ensure_parent(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)


def default_config() -> Dict[str, Any]:
    return {
        "username": "admin",
        "password": "admin123",
        "alist_url": "",
        "alist_token": "",
        "cookie_115": "",
        "tg_proxy_enabled": False,
        "tg_proxy_protocol": "http",
        "tg_proxy_host": "",
        "tg_proxy_port": "",
        "mount_path": "/115",
        "extensions": DEFAULT_EXTENSIONS,
        "trees": [{"url": "", "prefix": "", "exclude": 1}],
        "sync_mode": "incremental",
        "sync_clean": True,
        "check_hash": True,
        "cron_hour": "",
        "last_hash": "",
        "monitor_tasks": [],
        "resource_sources": [],
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


def normalize_resource_source(source: Dict[str, Any]) -> Dict[str, Any]:
    name = str(source.get("name", "")).strip()
    raw_channel_id = str(source.get("channel_id", "") or source.get("channel", "")).strip()
    url = str(source.get("url", "")).strip()
    notes = str(source.get("notes", "")).strip()
    channel_id = raw_channel_id.lstrip("@")
    if not channel_id and url:
        channel_id = normalize_telegram_channel_id_from_input(url)
    return {
        "name": name or channel_id or url or "未命名频道",
        "channel_id": channel_id,
        "url": build_telegram_channel_url(channel_id) if channel_id else url,
        "notes": notes,
        "enabled": bool(source.get("enabled", True)),
    }


def normalize_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    merged = default_config()
    merged.update(cfg or {})

    if "alist_token" not in merged:
        merged["alist_token"] = ""
    if "cookie_115" not in merged:
        merged["cookie_115"] = ""
    if "tg_proxy_enabled" not in merged:
        merged["tg_proxy_enabled"] = False
    if "tg_proxy_protocol" not in merged:
        merged["tg_proxy_protocol"] = "http"
    if "tg_proxy_host" not in merged:
        merged["tg_proxy_host"] = ""
    if "tg_proxy_port" not in merged:
        merged["tg_proxy_port"] = ""
    if "monitor_tasks" not in merged or not isinstance(merged["monitor_tasks"], list):
        merged["monitor_tasks"] = []
    if "resource_sources" not in merged or not isinstance(merged["resource_sources"], list):
        merged["resource_sources"] = []

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
    normalized_sources = []
    seen_sources = set()
    for raw_source in merged["resource_sources"]:
        source = normalize_resource_source(raw_source or {})
        source_key = "|".join(
            [
                source.get("channel_id", ""),
                source.get("url", ""),
            ]
        )
        if source_key in seen_sources:
            continue
        seen_sources.add(source_key)
        normalized_sources.append(source)
    merged["resource_sources"] = normalized_sources
    merged["mount_path"] = normalize_remote_path(merged.get("mount_path", "/115"))
    merged["alist_url"] = str(merged.get("alist_url", "")).strip().rstrip("/")
    merged["cookie_115"] = str(merged.get("cookie_115", "")).strip()
    merged["tg_proxy_enabled"] = bool(merged.get("tg_proxy_enabled", False))
    merged["tg_proxy_protocol"] = str(merged.get("tg_proxy_protocol", "http") or "http").strip().lower()
    if merged["tg_proxy_protocol"] not in ("http", "https"):
        merged["tg_proxy_protocol"] = "http"
    merged["tg_proxy_host"] = str(merged.get("tg_proxy_host", "")).strip()
    merged["tg_proxy_port"] = str(merged.get("tg_proxy_port", "")).strip()
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
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS resource_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL DEFAULT 'manual',
            source_name TEXT NOT NULL DEFAULT '',
            channel_name TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL,
            normalized_title TEXT NOT NULL DEFAULT '',
            raw_text TEXT NOT NULL DEFAULT '',
            link_url TEXT NOT NULL DEFAULT '',
            link_type TEXT NOT NULL DEFAULT 'unknown',
            message_url TEXT NOT NULL DEFAULT '',
            quality TEXT NOT NULL DEFAULT '',
            year TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'new',
            created_at TEXT NOT NULL,
            published_at TEXT NOT NULL DEFAULT '',
            last_seen_at TEXT NOT NULL DEFAULT '',
            extra_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS resource_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resource_id INTEGER NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            link_url TEXT NOT NULL DEFAULT '',
            link_type TEXT NOT NULL DEFAULT '',
            folder_id TEXT NOT NULL DEFAULT '',
            savepath TEXT NOT NULL DEFAULT '',
            sharetitle TEXT NOT NULL DEFAULT '',
            monitor_task_name TEXT NOT NULL DEFAULT '',
            refresh_delay_seconds INTEGER NOT NULL DEFAULT 0,
            auto_refresh INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'pending',
            status_detail TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT NOT NULL DEFAULT '',
            finished_at TEXT NOT NULL DEFAULT '',
            last_triggered_at TEXT NOT NULL DEFAULT '',
            response_json TEXT NOT NULL DEFAULT '{}',
            extra_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    cursor.execute("PRAGMA table_info(resource_jobs)")
    job_columns = {str(row[1]) for row in cursor.fetchall()}
    if "extra_json" not in job_columns:
        cursor.execute("ALTER TABLE resource_jobs ADD COLUMN extra_json TEXT NOT NULL DEFAULT '{}'")
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_resource_items_link ON resource_items(link_url) WHERE link_url <> ''"
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_resource_items_created_at ON resource_items(created_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_resource_items_status ON resource_items(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_resource_jobs_created_at ON resource_jobs(created_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_resource_jobs_status ON resource_jobs(status)")
    cursor.execute(
        """
        SELECT id, last_seen_at, extra_json
        FROM resource_items
        WHERE last_seen_at LIKE '{%' AND extra_json NOT LIKE '{%'
        """
    )
    for row in cursor.fetchall():
        row_id = int(row[0] or 0)
        legacy_extra_raw = str(row[1] or "").strip()
        last_seen_raw = str(row[2] or "").strip()
        legacy_extra = safe_json_loads(legacy_extra_raw, {})
        if not isinstance(legacy_extra, dict):
            continue
        if not any(str(legacy_extra.get(key, "") or "").strip() for key in ("cover_url", "source_post_id", "source_url")):
            continue
        cursor.execute(
            "UPDATE resource_items SET last_seen_at = ?, extra_json = ? WHERE id = ?",
            (last_seen_raw or now_text(), legacy_extra_raw, row_id),
        )
    conn.commit()
    conn.close()


def open_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def safe_json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def safe_json_loads(raw: Any, fallback: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    text = str(raw or "").strip()
    if not text:
        return fallback
    try:
        return json.loads(text)
    except Exception:
        return fallback


def merge_json_object(base: Any, patch: Any) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    if isinstance(base, dict):
        merged.update(base)
    if isinstance(patch, dict):
        merged.update(patch)
    return merged


def sqlite_row_to_dict(row: Optional[sqlite3.Row]) -> Dict[str, Any]:
    if row is None:
        return {}
    return {key: row[key] for key in row.keys()}


def unique_preserve_order(values: List[str]) -> List[str]:
    seen: Set[str] = set()
    result: List[str] = []
    for value in values:
        token = str(value or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        result.append(token)
    return result


def apply_share_receive_code_to_url(url: str, receive_code: str) -> str:
    share_url = str(url or "").strip()
    password = str(receive_code or "").strip()
    if not share_url or not password or "password=" in share_url.lower():
        return share_url
    separator = "&" if "?" in share_url else "?"
    return f"{share_url}{separator}password={urllib.parse.quote(password)}"


def strip_html_to_text(fragment: str) -> str:
    text = str(fragment or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def choose_resource_link(candidates: List[str]) -> str:
    normalized = unique_preserve_order(candidates)
    priority = {"magnet": 0, "115share": 1, "ed2k": 2, "link": 3, "unknown": 9}
    normalized.sort(key=lambda url: (priority.get(detect_resource_link_type(url), 9), url))
    return normalized[0] if normalized else ""


def build_tg_proxy_url(cfg: Dict[str, Any], ignore_enabled: bool = False) -> str:
    if not ignore_enabled and not bool(cfg.get("tg_proxy_enabled")):
        return ""
    protocol = str(cfg.get("tg_proxy_protocol", "http") or "http").strip().lower()
    host = str(cfg.get("tg_proxy_host", "") or "").strip()
    port = str(cfg.get("tg_proxy_port", "") or "").strip()
    if not host or not port:
        return ""
    return f"{protocol}://{host}:{port}"


def format_network_error(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}: {exc.reason or '请求失败'}"
    if isinstance(exc, ssl.SSLError):
        return str(exc.reason or exc)
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, TimeoutError):
            return "连接超时"
        if isinstance(reason, ssl.SSLError):
            return str(reason.reason or reason)
        if isinstance(reason, OSError):
            return str(reason.strerror or reason)
        return str(reason or exc)
    return str(exc or "未知网络错误")


def unwrap_network_error(exc: Exception) -> Exception:
    current: Exception = exc
    seen: Set[int] = set()
    while current and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, urllib.error.URLError) and isinstance(getattr(current, "reason", None), Exception):
            current = current.reason
            continue
        nested = getattr(current, "__cause__", None) or getattr(current, "__context__", None)
        if isinstance(nested, Exception):
            current = nested
            continue
        break
    return current


def is_retryable_telegram_request_error(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return int(exc.code or 0) in {408, 425, 429, 500, 502, 503, 504}

    root = unwrap_network_error(exc)
    if isinstance(root, (TimeoutError, ConnectionResetError, EOFError, ssl.SSLError)):
        return True

    message = " ".join(
        str(part or "")
        for part in [exc, root, getattr(root, "strerror", "")]
    ).lower()
    retry_fragments = (
        "unexpected_eof_while_reading",
        "eof occurred in violation of protocol",
        "remote end closed connection",
        "connection reset",
        "connection aborted",
        "temporarily unavailable",
        "temporary failure",
        "timed out",
        "tlsv1 alert",
        "ssl",
    )
    return any(fragment in message for fragment in retry_fragments)


def test_telegram_latency(cfg: Dict[str, Any], channel_id: str = "telegram", timeout: int = 20) -> Dict[str, Any]:
    target_channel_id = normalize_telegram_channel_id_from_input(channel_id) or "telegram"
    target_url = build_telegram_channel_url(target_channel_id)
    proxy_url = build_tg_proxy_url(cfg, ignore_enabled=True)
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "User-Agent": "Mozilla/5.0 115-strm-web",
    }
    started_at = time.perf_counter()
    try:
        html, final_url = http_request_text_with_final_url(
            target_url,
            timeout=timeout,
            extra_headers=headers,
            proxy_url=proxy_url,
        )
    except Exception as exc:
        mode_label = "代理" if proxy_url else "直连"
        raise RuntimeError(f"{mode_label}请求 TG 失败：{format_network_error(exc)}") from exc

    if not is_expected_telegram_channel_url(final_url, target_channel_id):
        raise RuntimeError(f"TG 页面发生跳转，当前落到了 {final_url}")
    latency_ms = max(1, int(round((time.perf_counter() - started_at) * 1000)))
    post_count = len(TG_WIDGET_POST_REGEX.findall(html))
    if post_count <= 0:
        raise RuntimeError("已连接到 TG，但未识别到频道内容")
    return {
        "ok": True,
        "latency_ms": latency_ms,
        "mode": "proxy" if proxy_url else "direct",
        "proxy_url": proxy_url,
        "target_url": final_url or target_url,
        "channel_id": target_channel_id,
        "post_count": post_count,
        "msg": f"TG 连通，延迟约 {latency_ms} ms",
    }


def normalize_resource_title(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    return cleaned[:200]


def guess_resource_quality(text: str) -> str:
    raw = str(text or "").lower()
    tokens: List[str] = []
    for pattern, label in [
        ("2160p", "2160p"),
        ("4k", "4K"),
        ("1080p", "1080p"),
        ("720p", "720p"),
        ("bluray", "BluRay"),
        ("web-dl", "WEB-DL"),
        ("webrip", "WEBRip"),
        ("remux", "Remux"),
        ("hdr", "HDR"),
        ("dv", "DV"),
        ("x265", "x265"),
        ("x264", "x264"),
    ]:
        if pattern in raw and label not in tokens:
            tokens.append(label)
    return " / ".join(tokens[:4])


def detect_resource_link_type(url: str) -> str:
    lowered = str(url or "").strip().lower()
    if not lowered:
        return "unknown"
    if lowered.startswith("magnet:?"):
        return "magnet"
    if lowered.startswith("ed2k://"):
        return "ed2k"
    if "115cdn.com/s/" in lowered or "115.com/s/" in lowered or "anxia.com/s/" in lowered:
        return "115share"
    return "link"


def resolve_resource_link_type(link_type: str, link_url: str) -> str:
    normalized = str(link_type or "").strip().lower()
    if normalized in ("magnet", "115share"):
        return normalized
    detected = detect_resource_link_type(link_url)
    return detected if detected in ("magnet", "115share") else normalized


def pick_resource_title(raw_text: str, fallback_title: str = "") -> str:
    preferred = normalize_resource_title(fallback_title)
    if preferred:
        return preferred
    for raw_line in str(raw_text or "").splitlines():
        line = normalize_resource_title(raw_line.lstrip("-•# "))
        if not line:
            continue
        lowered = line.lower()
        if lowered.startswith("magnet:?") or lowered.startswith("http://") or lowered.startswith("https://"):
            continue
        if lowered.startswith("@") or lowered.startswith("tg://"):
            continue
        return line
    lines = [normalize_resource_title(line) for line in str(raw_text or "").splitlines() if normalize_resource_title(line)]
    return lines[0] if lines else "未命名资源"


def extract_resource_candidates(
    raw_text: str,
    source_name: str = "",
    source_type: str = "manual",
    channel_name: str = "",
    published_at: str = "",
    message_url: str = "",
) -> List[Dict[str, Any]]:
    raw = str(raw_text or "").strip()
    if not raw:
        return []

    links = RESOURCE_MAGNET_REGEX.findall(raw)
    if not links:
        links = [url for url in RESOURCE_URL_REGEX.findall(raw) if "t.me/" not in url and "telegram.me/" not in url]
    links = unique_preserve_order(links)
    base_title = pick_resource_title(raw)
    guessed_year = ""
    year_match = RESOURCE_YEAR_REGEX.search(raw)
    if year_match:
        guessed_year = year_match.group(1)
    quality = guess_resource_quality(raw)
    tg_link = message_url.strip()
    if not tg_link:
        tg_candidates = [url for url in RESOURCE_URL_REGEX.findall(raw) if "t.me/" in url or "telegram.me/" in url]
        tg_link = tg_candidates[0] if tg_candidates else ""

    if not links:
        return [
            {
                "source_type": source_type,
                "source_name": source_name,
                "channel_name": channel_name or source_name,
                "title": base_title,
                "normalized_title": base_title.lower(),
                "raw_text": raw,
                "link_url": "",
                "link_type": "unknown",
                "message_url": tg_link,
                "quality": quality,
                "year": guessed_year,
                "published_at": published_at.strip(),
                "extra": {},
            }
        ]

    candidates: List[Dict[str, Any]] = []
    multi = len(links) > 1
    for idx, link in enumerate(links, start=1):
        title = base_title
        if multi:
            title = f"{base_title} #{idx}"
        candidates.append(
            {
                "source_type": source_type,
                "source_name": source_name,
                "channel_name": channel_name or source_name,
                "title": title,
                "normalized_title": title.lower(),
                "raw_text": raw,
                "link_url": link,
                "link_type": detect_resource_link_type(link),
                "message_url": tg_link,
                "quality": quality,
                "year": guessed_year,
                "published_at": published_at.strip(),
                "extra": {},
            }
        )
    return candidates


def upsert_resource_item(conn: sqlite3.Connection, item: Dict[str, Any]) -> Tuple[int, bool]:
    cursor = conn.cursor()
    link_url = str(item.get("link_url", "")).strip()
    message_url = str(item.get("message_url", "")).strip()
    now = now_text()
    existing: Optional[sqlite3.Row] = None
    if link_url:
        cursor.execute("SELECT * FROM resource_items WHERE link_url = ?", (link_url,))
        existing = cursor.fetchone()
    if not existing and message_url:
        cursor.execute("SELECT * FROM resource_items WHERE message_url = ?", (message_url,))
        existing = cursor.fetchone()
    if not existing:
        cursor.execute(
            """
            SELECT * FROM resource_items
            WHERE title = ? AND source_name = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (str(item.get("title", "")).strip(), str(item.get("source_name", "")).strip()),
        )
        existing = cursor.fetchone()

    payload = (
        str(item.get("source_type", "manual")).strip() or "manual",
        str(item.get("source_name", "")).strip(),
        str(item.get("channel_name", "")).strip(),
        str(item.get("title", "")).strip() or "未命名资源",
        str(item.get("normalized_title", "")).strip(),
        str(item.get("raw_text", "")).strip(),
        link_url,
        str(item.get("link_type", "unknown")).strip() or "unknown",
        message_url,
        str(item.get("quality", "")).strip(),
        str(item.get("year", "")).strip(),
        str(item.get("published_at", "")).strip(),
        safe_json_dumps(item.get("extra", {})),
    )
    if existing:
        cursor.execute(
            """
            UPDATE resource_items
            SET source_type = ?, source_name = ?, channel_name = ?, title = ?, normalized_title = ?,
                raw_text = ?, link_url = ?, link_type = ?, message_url = ?, quality = ?, year = ?,
                published_at = ?, last_seen_at = ?, extra_json = ?
            WHERE id = ?
            """,
            payload[:12] + (now, payload[12], existing["id"]),
        )
        return int(existing["id"]), False

    cursor.execute(
        """
        INSERT INTO resource_items(
            source_type, source_name, channel_name, title, normalized_title, raw_text,
            link_url, link_type, message_url, quality, year, status,
            created_at, published_at, last_seen_at, extra_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?, ?, ?)
        """,
        payload[:11] + (now, payload[11], now, payload[12]),
    )
    return int(cursor.lastrowid), True


def update_resource_item_status(conn: sqlite3.Connection, resource_id: int, status: str) -> None:
    cursor = conn.cursor()
    cursor.execute("UPDATE resource_items SET status = ?, last_seen_at = ? WHERE id = ?", (status, now_text(), resource_id))


def serialize_resource_item_row(row: sqlite3.Row) -> Dict[str, Any]:
    data = sqlite_row_to_dict(row)
    extra = safe_json_loads(data.get("extra_json"), {})
    legacy_extra = safe_json_loads(data.get("last_seen_at"), {})
    if not isinstance(extra, dict) or not extra:
        extra = legacy_extra if isinstance(legacy_extra, dict) else {}
    elif isinstance(legacy_extra, dict):
        for key in ("cover_url", "source_post_id", "source_url"):
            if not str(extra.get(key, "") or "").strip() and str(legacy_extra.get(key, "") or "").strip():
                extra[key] = legacy_extra[key]
    data["extra"] = extra
    data["cover_url"] = str(extra.get("cover_url", "") or "").strip()
    data["source_post_id"] = str(extra.get("source_post_id", "") or "").strip()
    return data


def build_resource_job_snapshot(resource: Dict[str, Any], link_type: str = "") -> Dict[str, Any]:
    extra = resource.get("extra", {})
    if not isinstance(extra, dict):
        extra = safe_json_loads(resource.get("extra_json"), {})
    snapshot = {
        "message_url": str(resource.get("message_url", "") or "").strip(),
        "source_post_id": str((extra or {}).get("source_post_id", "") or "").strip(),
    }
    resolved_link_type = resolve_resource_link_type(link_type or resource.get("link_type", ""), resource.get("link_url", ""))
    if resolved_link_type == "115share":
        payload = parse_115_share_payload(str(resource.get("link_url", "") or "").strip(), str(resource.get("raw_text", "") or ""))
        receive_code = str(payload.get("receive_code", "") or "").strip()
        if receive_code:
            snapshot["receive_code"] = receive_code
    return {key: value for key, value in snapshot.items() if str(value or "").strip()}


def sanitize_resource_job_input(raw: Dict[str, Any]) -> Dict[str, Any]:
    source_type = str(raw.get("source_type", "manual") or "manual").strip() or "manual"
    source_name = str(raw.get("source_name", "") or "").strip()
    channel_name = str(raw.get("channel_name", "") or "").strip()
    title = str(raw.get("title", "") or "").strip() or "未命名资源"
    raw_text = str(raw.get("raw_text", "") or "").strip()
    link_url = str(raw.get("link_url", "") or "").strip()
    message_url = str(raw.get("message_url", "") or "").strip()
    quality = str(raw.get("quality", "") or "").strip()
    year = str(raw.get("year", "") or "").strip()
    published_at = str(raw.get("published_at", "") or "").strip()
    extra = raw.get("extra", {})
    if not isinstance(extra, dict):
        extra = {}
    return {
        "id": int(raw.get("id", 0) or 0),
        "source_type": source_type,
        "source_name": source_name,
        "channel_name": channel_name,
        "title": title,
        "normalized_title": str(raw.get("normalized_title", "") or "").strip() or title.lower(),
        "raw_text": raw_text,
        "link_url": link_url,
        "link_type": resolve_resource_link_type(str(raw.get("link_type", "") or "").strip(), link_url) or detect_resource_link_type(link_url),
        "message_url": message_url,
        "quality": quality,
        "year": year,
        "published_at": published_at,
        "extra": {
            "cover_url": str(extra.get("cover_url", "") or "").strip(),
            "source_post_id": str(extra.get("source_post_id", "") or "").strip(),
            "source_url": str(extra.get("source_url", "") or "").strip(),
        },
    }


def get_resource_job_snapshot(raw_extra: Any) -> Dict[str, Any]:
    extra = safe_json_loads(raw_extra, {})
    snapshot = extra.get("snapshot") if isinstance(extra, dict) else {}
    return snapshot if isinstance(snapshot, dict) else {}


def get_resource_item(resource_id: int) -> Dict[str, Any]:
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM resource_items WHERE id = ?", (resource_id,))
    row = cursor.fetchone()
    conn.close()
    return serialize_resource_item_row(row) if row else {}


def serialize_resource_job_row(row: Optional[sqlite3.Row], include_private: bool = False) -> Dict[str, Any]:
    if not row:
        return {}
    data = sqlite_row_to_dict(row)
    extra = safe_json_loads(data.get("extra_json"), {})
    snapshot = get_resource_job_snapshot(extra)
    data["response"] = safe_json_loads(data.get("response_json"), {})
    data["extra"] = extra if isinstance(extra, dict) else {}
    data["snapshot"] = {
        "message_url": str(snapshot.get("message_url", "") or "").strip(),
        "source_post_id": str(snapshot.get("source_post_id", "") or "").strip(),
    }
    if include_private:
        data["_snapshot"] = snapshot
    data["auto_refresh"] = bool(data.get("auto_refresh"))
    data["refresh_target_type"] = str(data["extra"].get("refresh_target_type", "") or "").strip()
    data["share_root_title"] = str(data["extra"].get("share_root_title", "") or "").strip()
    data["message_url"] = str(snapshot.get("message_url", "") or "").strip()
    data["source_post_id"] = str(snapshot.get("source_post_id", "") or "").strip()
    data["selected_ids"] = [
        str(item).strip()
        for item in (data["extra"].get("selected_ids") or [])
        if str(item).strip()
    ]
    data["selected_entries"] = data["extra"].get("selected_entries") if isinstance(data["extra"].get("selected_entries"), list) else []
    return data


def list_resource_items(search: str = "", status: str = "", channel_id: str = "", source_type: str = "", limit: int = 120) -> List[Dict[str, Any]]:
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    where_parts = []
    params: List[Any] = []
    keyword = str(search or "").strip().lower()
    if keyword:
        like = f"%{keyword}%"
        where_parts.append(
            "(lower(title) LIKE ? OR lower(source_name) LIKE ? OR lower(channel_name) LIKE ? OR lower(link_url) LIKE ? OR lower(raw_text) LIKE ?)"
        )
        params.extend([like, like, like, like, like])
    normalized_status = str(status or "").strip().lower()
    if normalized_status:
        where_parts.append("status = ?")
        params.append(normalized_status)
    normalized_channel = normalize_telegram_channel_id_from_input(channel_id)
    if normalized_channel:
        where_parts.append("channel_name = ?")
        params.append(normalized_channel)
    normalized_source_type = str(source_type or "").strip().lower()
    if normalized_source_type:
        where_parts.append("source_type = ?")
        params.append(normalized_source_type)

    sql = "SELECT * FROM resource_items"
    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)
    sql += " ORDER BY CASE WHEN published_at <> '' THEN published_at ELSE created_at END DESC, id DESC LIMIT ?"
    params.append(max(1, min(limit, 500)))
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    conn.close()
    return [serialize_resource_item_row(row) for row in rows]


def count_resource_items(search: str = "", status: str = "", channel_id: str = "", source_type: str = "") -> int:
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    where_parts = []
    params: List[Any] = []
    keyword = str(search or "").strip().lower()
    if keyword:
        like = f"%{keyword}%"
        where_parts.append(
            "(lower(title) LIKE ? OR lower(source_name) LIKE ? OR lower(channel_name) LIKE ? OR lower(link_url) LIKE ? OR lower(raw_text) LIKE ?)"
        )
        params.extend([like, like, like, like, like])
    normalized_status = str(status or "").strip().lower()
    if normalized_status:
        where_parts.append("status = ?")
        params.append(normalized_status)
    normalized_channel = normalize_telegram_channel_id_from_input(channel_id)
    if normalized_channel:
        where_parts.append("channel_name = ?")
        params.append(normalized_channel)
    normalized_source_type = str(source_type or "").strip().lower()
    if normalized_source_type:
        where_parts.append("source_type = ?")
        params.append(normalized_source_type)

    sql = "SELECT COUNT(1) FROM resource_items"
    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)
    cursor.execute(sql, params)
    row = cursor.fetchone()
    conn.close()
    return int(row[0] if row else 0)


def build_resource_item_identity(item: Dict[str, Any]) -> str:
    payload = item if isinstance(item, dict) else {}
    extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
    source_post_id = str(payload.get("source_post_id", "") or extra.get("source_post_id", "")).strip()
    if source_post_id:
        return f"post:{source_post_id}"
    message_url = str(payload.get("message_url", "")).strip()
    if message_url:
        return f"msg:{message_url}"
    link_url = str(payload.get("link_url", "")).strip()
    if link_url:
        return f"link:{link_url}"
    title = str(payload.get("title", "")).strip()
    raw_text = str(payload.get("raw_text", "")).strip()
    return f"title:{title}|raw:{raw_text[:120]}"


def dedupe_resource_item_dicts(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for item in items:
        key = build_resource_item_identity(item)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def build_resource_search_text(item: Dict[str, Any]) -> str:
    payload = item if isinstance(item, dict) else {}
    extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
    parts = [
        payload.get("title", ""),
        payload.get("normalized_title", ""),
        payload.get("raw_text", ""),
        payload.get("source_name", ""),
        payload.get("channel_name", ""),
        payload.get("link_url", ""),
        payload.get("message_url", ""),
        extra.get("source_post_id", ""),
    ]
    return " ".join(str(part or "").strip().lower() for part in parts if str(part or "").strip())


def resource_item_matches_search(item: Dict[str, Any], keyword: str) -> bool:
    tokens = [token for token in re.split(r"\s+", str(keyword or "").strip().lower()) if token]
    if not tokens:
        return True
    haystack = build_resource_search_text(item)
    return all(token in haystack for token in tokens)


def get_resource_item_sort_key(item: Dict[str, Any]) -> Tuple[str, int, str]:
    payload = item if isinstance(item, dict) else {}
    extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
    published_at = str(payload.get("published_at", "") or payload.get("created_at", "")).strip()
    cursor = parse_int(
        extract_telegram_post_cursor(
            str(payload.get("message_url", "")).strip()
            or str(payload.get("source_post_id", "") or extra.get("source_post_id", "")).strip()
        )
    )
    return (published_at, cursor, build_resource_item_identity(payload))


def get_resource_item_post_cursor(item: Dict[str, Any]) -> str:
    payload = item if isinstance(item, dict) else {}
    extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
    return extract_telegram_post_cursor(
        str(payload.get("message_url", "")).strip()
        or str(payload.get("source_post_id", "") or extra.get("source_post_id", "")).strip()
    )


def list_resource_jobs(limit: int = 80) -> List[Dict[str, Any]]:
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM resource_jobs ORDER BY id DESC LIMIT ?", (max(1, min(limit, 200)),))
    rows = cursor.fetchall()
    conn.close()
    return [serialize_resource_job_row(row) for row in rows]


def get_resource_job(job_id: int, include_private: bool = False) -> Dict[str, Any]:
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM resource_jobs WHERE id = ?", (job_id,))
    row = cursor.fetchone()
    conn.close()
    return serialize_resource_job_row(row, include_private=include_private)


def count_resource_jobs(status: str = "") -> int:
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    normalized_status = str(status or "").strip().lower()
    if normalized_status:
        cursor.execute("SELECT COUNT(1) FROM resource_jobs WHERE status = ?", (normalized_status,))
    else:
        cursor.execute("SELECT COUNT(1) FROM resource_jobs")
    row = cursor.fetchone()
    conn.close()
    return int(row[0] if row else 0)


def find_existing_resource_job(resource: Dict[str, Any], savepath: str) -> Dict[str, Any]:
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    normalized_savepath = normalize_relative_path(savepath)
    link_url = str(resource.get("link_url", "") or "").strip()
    message_url = str(resource.get("message_url", "") or "").strip()
    source_post_id = str(resource.get("source_post_id", "") or "").strip()
    cursor.execute(
        """
        SELECT * FROM resource_jobs
        WHERE savepath = ?
          AND status IN ('pending', 'running', 'submitted', 'completed')
        ORDER BY id DESC
        LIMIT 40
        """,
        (normalized_savepath,),
    )
    rows = cursor.fetchall()
    conn.close()
    for row in rows:
        job = serialize_resource_job_row(row)
        if link_url and str(job.get("link_url", "") or "").strip() == link_url:
            return job
        if message_url and str(job.get("message_url", "") or "").strip() == message_url:
            return job
        if source_post_id and str(job.get("source_post_id", "") or "").strip() == source_post_id:
            return job
    return {}


def clear_completed_resource_jobs() -> Dict[str, int]:
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT resource_id FROM resource_jobs WHERE status = 'completed'")
    affected_resource_ids = [int(row[0]) for row in cursor.fetchall() if row and row[0]]

    cursor.execute("DELETE FROM resource_jobs WHERE status = 'completed'")
    deleted_count = int(cursor.rowcount or 0)

    reset_item_count = 0
    now = now_text()
    for resource_id in affected_resource_ids:
        cursor.execute("SELECT COUNT(1) FROM resource_jobs WHERE resource_id = ?", (resource_id,))
        remain_row = cursor.fetchone()
        remains = int(remain_row[0] if remain_row else 0)
        if remains == 0:
            cursor.execute(
                "UPDATE resource_items SET status = 'new', last_seen_at = ? WHERE id = ?",
                (now, resource_id),
            )
            reset_item_count += int(cursor.rowcount or 0)

    # If the task table has been fully cleared, reset the AUTOINCREMENT counter
    # so the next created task starts from 1 again.
    cursor.execute("SELECT COUNT(1) FROM resource_jobs")
    remaining_jobs_row = cursor.fetchone()
    remaining_jobs = int(remaining_jobs_row[0] if remaining_jobs_row else 0)
    if remaining_jobs == 0:
        cursor.execute("DELETE FROM sqlite_sequence WHERE name = 'resource_jobs'")

    conn.commit()
    conn.close()
    return {"deleted": deleted_count, "reset_items": reset_item_count}


def prune_resource_channel_cache(conn: sqlite3.Connection, channel_id: str, keep: int = RESOURCE_CHANNEL_CACHE_LIMIT) -> int:
    normalized_channel = normalize_telegram_channel_id_from_input(channel_id)
    keep_limit = max(1, int(keep or RESOURCE_CHANNEL_CACHE_LIMIT))
    if not normalized_channel:
        return 0
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id
        FROM resource_items
        WHERE source_type = 'tg' AND channel_name = ?
        ORDER BY CASE WHEN published_at <> '' THEN published_at ELSE created_at END DESC, id DESC
        LIMIT -1 OFFSET ?
        """,
        (normalized_channel, keep_limit),
    )
    stale_ids = [int(row[0]) for row in cursor.fetchall() if row and row[0]]
    if not stale_ids:
        return 0
    placeholders = ",".join(["?"] * len(stale_ids))
    cursor.execute(f"DELETE FROM resource_items WHERE id IN ({placeholders})", stale_ids)
    return int(cursor.rowcount or 0)


def build_resource_channel_sections(
    sources: List[Dict[str, Any]],
    items: Optional[List[Dict[str, Any]]] = None,
    per_channel: int = 10,
) -> List[Dict[str, Any]]:
    sections: List[Dict[str, Any]] = []
    indexed_items: Dict[str, List[Dict[str, Any]]] = {}
    if items is not None:
        for item in items:
            item_channel_id = normalize_telegram_channel_id_from_input(item.get("channel_name", ""))
            if not item_channel_id:
                continue
            indexed_items.setdefault(item_channel_id, []).append(item)
    for source in sources:
        channel_id = normalize_telegram_channel_id_from_input(source.get("channel_id", ""))
        if not channel_id:
            continue
        if items is not None:
            channel_pool = indexed_items.get(channel_id, [])
            channel_items = channel_pool[:per_channel]
            item_count = len(channel_pool)
        else:
            channel_items = list_resource_items(channel_id=channel_id, source_type="tg", limit=per_channel)
            item_count = count_resource_items(channel_id=channel_id, source_type="tg")
        has_more = item_count > len(channel_items)
        next_before = get_resource_item_post_cursor(channel_items[-1]) if (has_more and channel_items) else ""
        sections.append(
            {
                "name": source.get("name", channel_id),
                "channel_id": channel_id,
                "url": build_telegram_channel_url(channel_id),
                "enabled": bool(source.get("enabled", True)),
                "last_sync_at": resource_channel_last_sync.get(channel_id, 0.0),
                "last_error": resource_channel_last_error.get(channel_id, ""),
                "item_count": item_count,
                "items": channel_items[:per_channel],
                "next_before": next_before,
                "has_more": bool(has_more and next_before),
            }
        )
    return sections


def search_telegram_channel_resource_items(
    cfg: Dict[str, Any],
    source: Dict[str, Any],
    keyword: str,
    limit_per_channel: int = TG_SEARCH_MATCH_LIMIT_PER_CHANNEL,
    max_pages: int = TG_SEARCH_MAX_PAGES,
    page_size: int = TG_SEARCH_PAGE_LIMIT,
    start_before: str = "",
) -> Dict[str, Any]:
    normalized_source = normalize_resource_source(source or {})
    channel_id = normalize_telegram_channel_id_from_input(normalized_source.get("channel_id", ""))
    if not channel_id:
        return {"channel_id": "", "items": [], "pages_scanned": 0, "next_before": "", "has_more": False}

    items: List[Dict[str, Any]] = []
    before = extract_telegram_post_cursor(start_before)
    pages_scanned = 0
    seen_keys: Set[str] = set()
    next_before = ""
    has_more = False
    target_limit = max(1, int(limit_per_channel or TG_SEARCH_MATCH_LIMIT_PER_CHANNEL))
    fetch_limit = max(target_limit, max(1, int(page_size or TG_SEARCH_PAGE_LIMIT)))

    for _ in range(max(1, int(max_pages or TG_SEARCH_MAX_PAGES))):
        page = fetch_telegram_channel_posts_page(
            cfg,
            normalized_source,
            limit=fetch_limit,
            before=before,
            query=keyword,
            allow_empty=True,
        )
        pages_scanned += 1
        page_matches: List[Dict[str, Any]] = []
        for post in page.get("posts", []) or []:
            if not resource_item_matches_search(post, keyword):
                continue
            identity = build_resource_item_identity(post)
            if identity in seen_keys:
                continue
            seen_keys.add(identity)
            page_matches.append(post)

        remaining = max(0, target_limit - len(items))
        if page_matches and remaining > 0:
            items.extend(page_matches[:remaining])

        page_before = str(page.get("next_before", "") or "").strip()
        more_in_current_page = len(page_matches) > remaining if remaining > 0 else bool(page_matches)
        has_more = bool((more_in_current_page or page.get("has_more")) and (page_before or items))
        if items and has_more:
            next_before = get_resource_item_post_cursor(items[-1]) or page_before
        elif not has_more:
            next_before = ""

        if len(items) >= target_limit:
            break
        before = page_before
        if not before or not page.get("has_more"):
            break

    items.sort(key=get_resource_item_sort_key, reverse=True)
    return {
        "channel_id": channel_id,
        "items": items,
        "pages_scanned": pages_scanned,
        "next_before": next_before,
        "has_more": bool(next_before and has_more),
    }


async def search_resource_sources(keyword: str) -> Dict[str, Any]:
    query = str(keyword or "").strip()
    cfg = get_config()
    sources = [normalize_resource_source(source or {}) for source in cfg.get("resource_sources", []) if source.get("enabled")]
    if not query or not sources:
        return {
            "items": [],
            "sections": [],
            "errors": [],
            "searched_sources": len(sources),
            "matched_channels": 0,
            "pages_scanned": 0,
        }

    async def search_one_source(source: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    search_telegram_channel_resource_items,
                    cfg,
                    source,
                    query,
                    TG_SEARCH_MATCH_LIMIT_PER_CHANNEL,
                    TG_SEARCH_MAX_PAGES,
                    TG_SEARCH_PAGE_LIMIT,
                    "",
                ),
                timeout=TG_SEARCH_CHANNEL_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            channel_id = normalize_telegram_channel_id_from_input(source.get("channel_id", ""))
            raise RuntimeError(f"频道搜索超时（{channel_id}）") from exc

    tasks = [search_one_source(source) for source in sources]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    items: List[Dict[str, Any]] = []
    sections: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    matched_channels = 0
    pages_scanned = 0

    for source, result in zip(sources, results):
        channel_id = normalize_telegram_channel_id_from_input(source.get("channel_id", ""))
        source_name = str(source.get("name", "") or channel_id).strip()
        if isinstance(result, Exception):
            errors.append(
                {
                    "channel_id": channel_id,
                    "name": source_name,
                    "message": str(result),
                }
            )
            continue
        channel_items = result.get("items", []) if isinstance(result, dict) else []
        pages_scanned += int(result.get("pages_scanned", 0) or 0) if isinstance(result, dict) else 0
        if channel_items:
            matched_channels += 1
            items.extend(channel_items)
            sections.append(
                {
                    "name": source_name,
                    "channel_id": channel_id,
                    "url": build_telegram_channel_url(channel_id),
                    "enabled": True,
                    "items": channel_items,
                    "item_count": len(channel_items),
                    "next_before": str(result.get("next_before", "") or "").strip(),
                    "has_more": bool(result.get("has_more")),
                    "pages_scanned": int(result.get("pages_scanned", 0) or 0),
                }
            )

    deduped_items = dedupe_resource_item_dicts(items)
    deduped_items.sort(key=get_resource_item_sort_key, reverse=True)
    return {
        "items": deduped_items[: max(1, int(TG_SEARCH_TOTAL_LIMIT or 60))],
        "sections": sections,
        "errors": errors,
        "searched_sources": len(sources),
        "matched_channels": matched_channels,
        "pages_scanned": pages_scanned,
    }


def create_resource_job(resource: Dict[str, Any], data: Dict[str, Any]) -> int:
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    now = now_text()
    link_type = resolve_resource_link_type(resource.get("link_type", "unknown"), resource.get("link_url", ""))
    folder_id = str(data.get("folder_id", "")).strip()
    savepath = normalize_relative_path(data.get("savepath", ""))
    extra = normalize_share_selection_meta(data.get("share_selection", {})) if link_type == "115share" else {}
    extra["snapshot"] = build_resource_job_snapshot(resource, link_type)
    manual_sharetitle = normalize_relative_path(data.get("sharetitle", ""))
    if manual_sharetitle:
        sharetitle = manual_sharetitle
    elif link_type == "115share":
        sharetitle = normalize_relative_path(extra.get("auto_sharetitle", ""))
    else:
        sharetitle = normalize_relative_path(resource.get("title", ""))
    monitor_task_name = str(data.get("monitor_task_name", "")).strip()
    refresh_delay_seconds = max(0, int(data.get("refresh_delay_seconds", 0) or 0))
    auto_refresh = bool(data.get("auto_refresh", True))
    cursor.execute(
        """
        INSERT INTO resource_jobs(
            resource_id, title, link_url, link_type, folder_id, savepath, sharetitle,
            monitor_task_name, refresh_delay_seconds, auto_refresh, status, status_detail,
            created_at, updated_at, extra_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', '等待提交到 115', ?, ?, ?)
        """,
        (
            int(resource.get("id", 0) or 0),
            str(resource.get("title", "")).strip(),
            str(resource.get("link_url", "")).strip(),
            link_type,
            folder_id,
            savepath,
            sharetitle,
            monitor_task_name,
            refresh_delay_seconds,
            1 if auto_refresh else 0,
            now,
            now,
            safe_json_dumps(extra),
        ),
    )
    job_id = int(cursor.lastrowid)
    resource_id = int(resource.get("id", 0) or 0)
    if resource_id > 0:
        update_resource_item_status(conn, resource_id, "queued")
    conn.commit()
    conn.close()
    return job_id


def update_resource_job(job_id: int, **fields: Any) -> None:
    if not fields:
        return
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    payload = dict(fields)
    payload["updated_at"] = now_text()
    sets = [f"{key} = ?" for key in payload.keys()]
    params = list(payload.values()) + [job_id]
    cursor.execute(f"UPDATE resource_jobs SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()
    conn.close()


def delete_resource_item(resource_id: int) -> None:
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM resource_jobs WHERE resource_id = ?", (resource_id,))
    cursor.execute("DELETE FROM resource_items WHERE id = ?", (resource_id,))
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


def resolve_task_root(task: Dict[str, Any]) -> str:
    root_name = basename(task.get("scan_path", ""))
    target_path = normalize_relative_path(task.get("target_path", ""))
    if not target_path:
        return root_name
    target_parts = [p for p in target_path.split("/") if p]
    if root_name and target_parts and target_parts[-1] == root_name:
        return target_path
    return join_relative_path(target_path, root_name)


def match_monitor_task_for_savepath(cfg: Dict[str, Any], savepath: str) -> Dict[str, str]:
    savepath_rel = normalize_relative_path(savepath)
    mount_path = normalize_remote_path(cfg.get("mount_path", "/115"))
    full_path = join_remote_path(mount_path, savepath_rel)
    best_task: Optional[Dict[str, Any]] = None
    best_depth = -1

    for raw_task in cfg.get("monitor_tasks", []) or []:
        task = normalize_task(raw_task or {})
        task_name = str(task.get("name", "") or "").strip()
        scan_path = normalize_remote_path(task.get("scan_path", ""))
        if not task_name or not scan_path or scan_path == "/":
            continue
        if full_path != scan_path and not full_path.startswith(scan_path + "/"):
            continue
        depth = len([part for part in scan_path.split("/") if part])
        if depth > best_depth:
            best_depth = depth
            best_task = task

    return {
        "task_name": str(best_task.get("name", "") if best_task else "").strip(),
        "scan_path": normalize_remote_path(best_task.get("scan_path", "") if best_task else ""),
        "full_path": full_path,
    }


def normalize_telegram_channel_id_from_input(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    raw = raw.replace("https://t.me/s/", "").replace("http://t.me/s/", "")
    raw = raw.replace("https://t.me/", "").replace("http://t.me/", "")
    raw = raw.replace("telegram.me/s/", "").replace("telegram.me/", "")
    raw = raw.lstrip("@").strip("/")
    return raw


def build_telegram_channel_url(channel_id: str) -> str:
    normalized = normalize_telegram_channel_id_from_input(channel_id)
    return f"https://t.me/s/{normalized}" if normalized else ""


def build_telegram_channel_page_url(channel_id: str, before: str = "", query: str = "") -> str:
    base_url = build_telegram_channel_url(channel_id)
    cursor = str(before or "").strip()
    keyword = str(query or "").strip()
    if not base_url:
        return base_url
    params: List[Tuple[str, str]] = []
    if keyword:
        params.append(("q", keyword))
    if cursor:
        params.append(("before", cursor))
    if not params:
        return base_url
    return f"{base_url}?{urllib.parse.urlencode(params)}"


def extract_telegram_post_cursor(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    match = re.search(r"/(\d+)$", raw)
    if match:
        return match.group(1)
    match = re.search(r"/(\d+)(?:\?.*)?$", raw)
    if match:
        return match.group(1)
    return raw


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
ui_event_subscribers: Set[asyncio.Queue[str]] = set()
ui_push_pending = False
ui_push_task: Optional[asyncio.Task] = None
resource_job_running: Set[int] = set()
resource_refresh_pending: Set[int] = set()
resource_channel_last_sync: Dict[str, float] = {}
resource_channel_last_error: Dict[str, str] = {}
resource_channel_syncing: Set[str] = set()


def clone_jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def build_main_status_payload() -> Dict[str, Any]:
    return {
        "running": bool(task_status["running"]),
        "next_run": task_status.get("next_run"),
        "logs": clone_jsonable(task_status.get("logs", [])),
        "progress": clone_jsonable(task_status.get("progress", {})),
    }


def build_monitor_status_payload(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = cfg or get_config()
    return {
        "running": bool(monitor_status["running"]),
        "current_task": str(monitor_status.get("current_task", "")),
        "queued": clone_jsonable(monitor_status.get("queued", [])),
        "logs": clone_jsonable(monitor_status.get("logs", [])),
        "summary": clone_jsonable(monitor_status.get("summary", {})),
        "tasks": clone_jsonable(cfg.get("monitor_tasks", [])),
        "webhook_base": "/webhook/",
        "next_runs": clone_jsonable(monitor_next_run),
    }


def build_ui_state_payload(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "main": build_main_status_payload(),
        "monitor": build_monitor_status_payload(cfg),
    }


async def build_resource_state_payload(search: str = "") -> Dict[str, Any]:
    cfg = get_config()
    keyword = str(search or "").strip()
    search_meta = await search_resource_sources(keyword) if keyword else {
        "items": [],
        "sections": [],
        "errors": [],
        "searched_sources": len([source for source in cfg.get("resource_sources", []) if source.get("enabled")]),
        "matched_channels": 0,
        "pages_scanned": 0,
    }
    items = search_meta.get("items", []) if keyword else []
    search_sections = search_meta.get("sections", []) if keyword else []
    jobs = list_resource_jobs(limit=40)
    total_item_count = count_resource_items(source_type="tg")
    filtered_item_count = len(items)
    completed_job_count = count_resource_jobs(status="completed")
    sources = cfg.get("resource_sources", [])
    channel_sections = build_resource_channel_sections(sources, per_channel=10)
    return {
        "sources": clone_jsonable(sources),
        "items": clone_jsonable(items),
        "jobs": clone_jsonable(jobs),
        "monitor_tasks": clone_jsonable(cfg.get("monitor_tasks", [])),
        "cookie_configured": bool(str(cfg.get("cookie_115", "")).strip()),
        "search": keyword,
        "channel_sections": clone_jsonable(channel_sections),
        "search_sections": clone_jsonable(search_sections),
        "last_syncs": clone_jsonable(resource_channel_last_sync),
        "search_meta": clone_jsonable(
            {
                "errors": search_meta.get("errors", []),
                "searched_sources": search_meta.get("searched_sources", 0),
                "matched_channels": search_meta.get("matched_channels", 0),
                "pages_scanned": search_meta.get("pages_scanned", 0),
            }
        ),
        "stats": {
            "source_count": len([source for source in sources if source.get("enabled")]),
            "item_count": total_item_count,
            "filtered_item_count": filtered_item_count,
            "completed_job_count": completed_job_count,
        },
    }


async def sync_telegram_channels(force: bool = False, limit_per_channel: int = 10) -> Dict[str, Any]:
    cfg = get_config()
    sources = [source for source in cfg.get("resource_sources", []) if source.get("enabled")]
    if not sources:
        return {"ok": True, "synced": 0, "items": 0, "skipped": 0, "errors": []}

    ensure_db()
    synced_channels = 0
    upserted_items = 0
    skipped_channels = 0
    errors: List[Dict[str, str]] = []
    conn = open_db()
    try:
        for source in sources:
            channel_id = normalize_telegram_channel_id_from_input(source.get("channel_id", ""))
            if not channel_id:
                continue
            if not force and channel_id in resource_channel_last_sync and (time.time() - resource_channel_last_sync[channel_id]) < TG_SYNC_TTL_SECONDS:
                skipped_channels += 1
                continue
            if channel_id in resource_channel_syncing:
                skipped_channels += 1
                continue
            resource_channel_syncing.add(channel_id)
            try:
                posts = await asyncio.to_thread(fetch_telegram_channel_posts, cfg, source, limit_per_channel)
                for post in posts:
                    _, created = upsert_resource_item(conn, post)
                    upserted_items += 1 if created else 0
                prune_resource_channel_cache(conn, channel_id)
                conn.commit()
                resource_channel_last_sync[channel_id] = time.time()
                resource_channel_last_error.pop(channel_id, None)
                synced_channels += 1
            except Exception as exc:
                resource_channel_last_error[channel_id] = str(exc)
                errors.append(
                    {
                        "channel_id": channel_id,
                        "name": str(source.get("name", "") or channel_id).strip(),
                        "message": str(exc),
                    }
                )
            finally:
                resource_channel_syncing.discard(channel_id)
    finally:
        conn.close()
    return {
        "ok": not errors,
        "synced": synced_channels,
        "items": upserted_items,
        "skipped": skipped_channels,
        "errors": errors,
    }


async def broadcast_ui_state(payload: str) -> None:
    for queue in list(ui_event_subscribers):
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            continue


async def flush_ui_state_updates(delay: float) -> None:
    global ui_push_pending, ui_push_task
    try:
        await asyncio.sleep(max(0.0, delay))
        while ui_push_pending:
            ui_push_pending = False
            payload = json.dumps(build_ui_state_payload(), ensure_ascii=False)
            await broadcast_ui_state(payload)
            if ui_push_pending:
                await asyncio.sleep(UI_PUSH_DEBOUNCE_SECONDS)
    finally:
        ui_push_task = None


def schedule_ui_state_push(delay: float = UI_PUSH_DEBOUNCE_SECONDS) -> None:
    global ui_push_pending, ui_push_task
    ui_push_pending = True
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if ui_push_task is not None and not ui_push_task.done():
        return
    ui_push_task = loop.create_task(flush_ui_state_updates(delay))


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
    refresh_target_type = str(payload.get("refresh_target_type", "") or "").strip().lower()
    allow_subdir_hint = refresh_target_type not in ("file", "mixed")

    if savepath_rel and sharetitle_rel and allow_subdir_hint:
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
    schedule_ui_state_push()
    await asyncio.sleep(0)


async def write_log(msg: str) -> None:
    line = f"[{format_log_time()}] {msg}"
    task_status["logs"].append(line)
    if len(task_status["logs"]) > 500:
        task_status["logs"].pop(0)
    schedule_ui_state_push()
    await asyncio.to_thread(append_log_file, MAIN_LOG_PATH, f"{format_log_time(True)} {msg}")
    await asyncio.sleep(0)


async def write_monitor_log(text: str, level: str = "info") -> None:
    line = f"{format_log_time(True)} {text}"
    monitor_status["logs"].append({"text": line, "level": level})
    if len(monitor_status["logs"]) > 800:
        monitor_status["logs"].pop(0)
    schedule_ui_state_push()
    await asyncio.to_thread(append_log_file, MONITOR_LOG_PATH, line)
    await asyncio.sleep(0)


def update_monitor_summary(step: str, detail: str) -> None:
    monitor_status["summary"] = {"step": step, "detail": detail}
    schedule_ui_state_push()


def format_monitor_trigger(trigger: str) -> str:
    labels = {
        "manual": "手动触发",
        "webhook": "Webhook 触发",
        "resource": "资源中心触发",
        "cron": "定时触发",
        "queued": "队列触发",
    }
    return labels.get(trigger, trigger or "未知触发")


def format_monitor_bool(enabled: bool) -> str:
    return "开启" if enabled else "关闭"


async def write_monitor_section(title: str) -> None:
    await write_monitor_log(f"·· {title} ··", "section-divider")


async def write_monitor_task_header(task: Dict[str, Any], trigger: str, payload: Optional[Dict[str, Any]] = None) -> None:
    await write_monitor_log(
        f"━━━━━━━━━━【任务开始 | {task['name']} | {format_monitor_trigger(trigger)}】━━━━━━━━━━",
        "task-divider",
    )
    await write_monitor_log(
        f"扫描: {task['scan_path']} | 输出: /strm/{resolve_task_root(task)}",
        "info",
    )
    await write_monitor_log(
        f"模式: {'增量' if task['incremental'] else '全量'} | 目录时间检查: {format_monitor_bool(task['skip_by_dir_mtime'])}",
        "info",
    )
    if payload and trigger in ("webhook", "resource"):
        title = str(payload.get("title", "") or "").strip()
        sharetitle = str(payload.get("sharetitle", "") or "").strip()
        refresh_target_type = str(payload.get("refresh_target_type", "") or "").strip()
        webhook_bits = []
        if title:
            webhook_bits.append(f"内容: {title}")
        if sharetitle:
            webhook_bits.append(f"目录: {sharetitle}")
        if refresh_target_type:
            webhook_bits.append(f"类型: {refresh_target_type}")
        if webhook_bits:
            prefix = "Webhook" if trigger == "webhook" else "资源导入"
            await write_monitor_log(f"{prefix}: {' | '.join(webhook_bits)}", "info")


async def write_monitor_task_footer(task_name: str, status: str, level: str = "task-divider") -> None:
    await write_monitor_log(
        f"━━━━━━━━━━【任务结束 | {task_name} | {status}】━━━━━━━━━━",
        level,
    )


async def write_monitor_task_summary(stats: Dict[str, int]) -> None:
    await write_monitor_log(
        f"生成汇总: 新增/更新 {stats['generated']} | 跳过文件 {stats['skipped']} | 跳过目录 {stats['skipped_dirs']} | 失败目录 {stats['failed_dirs']}",
        "info",
    )
    await write_monitor_log(
        f"清理汇总: 删除文件 {stats['deleted_files']} | 删除目录 {stats['deleted_dirs']}",
        "info",
    )


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
    extra_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    url = normalize_http_url(url)
    headers = {}
    if extra_headers:
        headers.update(extra_headers)
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


def http_request_form_json(
    url: str,
    form_data: Dict[str, Any],
    timeout: int = 30,
    extra_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    url = normalize_http_url(url)
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
    }
    if extra_headers:
        headers.update(extra_headers)
    encoded = urllib.parse.urlencode({k: "" if v is None else str(v) for k, v in form_data.items()}).encode("utf-8")
    req = urllib.request.Request(url, data=encoded, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        body = resp.read().decode(charset, errors="ignore")
    return json.loads(body or "{}")


def http_request_text(
    url: str,
    timeout: int = 30,
    extra_headers: Optional[Dict[str, str]] = None,
    proxy_url: str = "",
) -> str:
    url = normalize_http_url(url)
    headers = dict(extra_headers or {})
    req = urllib.request.Request(url, headers=headers, method="GET")
    opener = urllib.request.build_opener()
    if proxy_url:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        )
    with opener.open(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="ignore")


def http_request_text_with_final_url(
    url: str,
    timeout: int = 30,
    extra_headers: Optional[Dict[str, str]] = None,
    proxy_url: str = "",
) -> Tuple[str, str]:
    url = normalize_http_url(url)
    headers = dict(extra_headers or {})
    req = urllib.request.Request(url, headers=headers, method="GET")
    opener = urllib.request.build_opener()
    if proxy_url:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        )
    with opener.open(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        body = resp.read().decode(charset, errors="ignore")
        return body, str(resp.geturl() or url)


def http_request_binary(
    url: str,
    timeout: int = 30,
    extra_headers: Optional[Dict[str, str]] = None,
    proxy_url: str = "",
) -> Tuple[bytes, str]:
    url = normalize_http_url(url)
    headers = dict(extra_headers or {})
    req = urllib.request.Request(url, headers=headers, method="GET")
    opener = urllib.request.build_opener()
    if proxy_url:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        )
    with opener.open(req, timeout=timeout) as resp:
        content_type = resp.headers.get_content_type() or "application/octet-stream"
        return resp.read(), content_type


def http_resolve_url(
    url: str,
    timeout: int = 30,
    extra_headers: Optional[Dict[str, str]] = None,
    proxy_url: str = "",
) -> str:
    url = normalize_http_url(url)
    headers = dict(extra_headers or {})
    req = urllib.request.Request(url, headers=headers, method="GET")
    opener = urllib.request.build_opener()
    if proxy_url:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        )
    with opener.open(req, timeout=timeout) as resp:
        return str(resp.geturl() or url)


def is_expected_telegram_channel_url(final_url: str, channel_id: str) -> bool:
    normalized_channel = normalize_telegram_channel_id_from_input(channel_id)
    if not normalized_channel:
        return False
    parsed = urllib.parse.urlparse(normalize_http_url(final_url))
    hostname = (parsed.hostname or "").lower()
    if hostname not in ("t.me", "telegram.me"):
        return False
    path = parsed.path.strip("/").lower()
    expected = normalized_channel.lower()
    return path in (expected, f"s/{expected}")


def submit_115_offline_task(cookie: str, resource_url: str, folder_id: str) -> Dict[str, Any]:
    cookie = str(cookie or "").strip()
    if not cookie:
        raise RuntimeError("115 Cookie 未配置")
    resource_url = str(resource_url or "").strip()
    if not resource_url:
        raise RuntimeError("资源链接为空")

    headers = {
        "Cookie": cookie,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://115.com/",
        "Origin": "https://115.com",
        "User-Agent": "Mozilla/5.0 115-strm-web",
    }
    response = http_request_form_json(
        "https://115.com/web/lixian/?ct=lixian&ac=add_task_url",
        {"url": resource_url, "wp_path_id": folder_id or "0"},
        timeout=45,
        extra_headers=headers,
    )
    accepted = bool(response.get("state")) or int(response.get("errcode", 0) or 0) == 10008
    if not accepted:
        detail = (
            str(response.get("error_msg", "")).strip()
            or str(response.get("message", "")).strip()
            or str(response.get("msg", "")).strip()
            or "115 离线任务提交失败"
        )
        raise RuntimeError(detail)
    return response


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value or default).strip()))
    except Exception:
        return default


def list_115_entries(cookie: str, cid: str = "0") -> List[Dict[str, Any]]:
    cookie = str(cookie or "").strip()
    if not cookie:
        raise RuntimeError("115 Cookie 未配置")
    headers = {
        "Cookie": cookie,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://115.com/",
        "User-Agent": "Mozilla/5.0 115-strm-web",
    }
    url = (
        "https://aps.115.com/natsort/files.php"
        f"?aid=1&cid={urllib.parse.quote(str(cid or '0'))}&offset=0&limit=300&show_dir=1&natsort=1&format=json"
    )
    result = http_request_json(url, extra_headers=headers, timeout=45)
    if not result.get("state", False):
        detail = str(result.get("error", "") or result.get("msg", "") or "读取 115 文件夹失败").strip()
        raise RuntimeError(detail)

    entries: List[Dict[str, Any]] = []
    for item in result.get("data") or []:
        name = str(item.get("n") or "").strip()
        folder_id = str(item.get("cid") or "").strip()
        file_id = str(item.get("fid") or "").strip()
        sha1 = str(item.get("sha1") or item.get("sha") or "").strip()
        is_dir = not file_id and not sha1
        entry_id = folder_id if is_dir else (file_id or str(item.get("pick_code") or item.get("pc") or sha1).strip())
        if not name or not entry_id:
            continue
        entries.append(
            {
                "id": entry_id,
                "cid": folder_id if is_dir else "",
                "name": name,
                "is_dir": is_dir,
                "size": parse_int(item.get("s") or item.get("size") or 0),
                "pick_code": str(item.get("pick_code") or item.get("pc") or "").strip(),
                "sha1": sha1,
                "modified_at": str(item.get("te") or item.get("t") or item.get("tp") or item.get("tu") or "").strip(),
            }
        )
    entries.sort(key=lambda item: (0 if item["is_dir"] else 1, str(item["name"]).lower()))
    return entries


def create_115_folder(cookie: str, cid: str = "0", folder_name: str = "") -> Dict[str, Any]:
    cookie = str(cookie or "").strip()
    if not cookie:
        raise RuntimeError("115 Cookie 未配置")

    parent_cid = str(cid or "0").strip() or "0"
    normalized_name = str(folder_name or "").strip()
    if not normalized_name:
        raise RuntimeError("文件夹名称不能为空")
    if any(ch in normalized_name for ch in ("/", "\\")):
        raise RuntimeError("文件夹名称不能包含 / 或 \\")
    if normalized_name in (".", ".."):
        raise RuntimeError("文件夹名称不合法")
    if len(normalized_name) > 120:
        raise RuntimeError("文件夹名称过长")

    headers = {
        "Cookie": cookie,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://115.com/",
        "Origin": "https://115.com",
        "User-Agent": "Mozilla/5.0 115-strm-web",
    }
    response = http_request_form_json(
        "https://webapi.115.com/files/add",
        {"pid": parent_cid, "cname": normalized_name},
        timeout=45,
        extra_headers=headers,
    )

    def resolve_folder_id_from_response(payload: Dict[str, Any]) -> str:
        candidates: List[str] = []
        for key in ("cid", "id", "folder_id", "file_id"):
            candidates.append(str(payload.get(key, "")).strip())
        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("cid", "id", "folder_id", "file_id"):
                candidates.append(str(data.get(key, "")).strip())
        return next((item for item in candidates if item and item != "0"), "")

    def find_existing_folder_id() -> str:
        entries = list_115_entries(cookie, parent_cid)
        matched = next(
            (
                entry
                for entry in entries
                if entry.get("is_dir") and str(entry.get("name", "")).strip() == normalized_name
            ),
            None,
        )
        return str((matched or {}).get("id", "")).strip()

    folder_id = resolve_folder_id_from_response(response if isinstance(response, dict) else {})
    success = bool((response or {}).get("state"))
    if not success and not folder_id:
        folder_id = find_existing_folder_id()

    if not success and not folder_id:
        detail = (
            str((response or {}).get("error", "")).strip()
            or str((response or {}).get("msg", "")).strip()
            or str((response or {}).get("message", "")).strip()
            or "新建 115 文件夹失败"
        )
        raise RuntimeError(detail)

    if not folder_id:
        folder_id = find_existing_folder_id()
    if not folder_id:
        raise RuntimeError("文件夹已创建，但未获取到目录 ID")

    return {
        "id": folder_id,
        "name": normalized_name,
        "cid": parent_cid,
        "created": success,
    }


def resolve_115_folder_id_by_path(cookie: str, relative_path: str) -> str:
    normalized_path = normalize_relative_path(relative_path)
    if not normalized_path:
        return "0"

    current_cid = "0"
    walked_parts: List[str] = []
    for part in [segment for segment in normalized_path.split("/") if segment]:
        walked_parts.append(part)
        entries = list_115_entries(cookie, current_cid)
        matched = next(
            (
                entry
                for entry in entries
                if entry.get("is_dir") and str(entry.get("name", "")).strip() == part
            ),
            None,
        )
        if not matched:
            raise RuntimeError(f"115 网盘目录不存在：{join_relative_path(*walked_parts)}")
        current_cid = str(matched.get("id", "") or matched.get("cid", "") or "").strip() or "0"
    return current_cid


def list_115_folders(cookie: str, cid: str = "0") -> List[Dict[str, str]]:
    return [
        {"id": str(entry.get("id", "")).strip(), "name": str(entry.get("name", "")).strip()}
        for entry in list_115_entries(cookie, cid)
        if entry.get("is_dir")
    ]


def parse_115_share_payload(url: str, raw_text: str = "") -> Dict[str, str]:
    source = str(url or "").strip()
    normalized = source
    match = re.search(
        r"https?://(?:115cdn|115|anxia)\.com/s/([A-Za-z0-9]+)(?:\?password=([A-Za-z0-9]+))?",
        source,
        flags=re.IGNORECASE,
    )
    share_code = ""
    receive_code = ""
    if match:
        share_code = match.group(1)
        receive_code = str(match.group(2) or "").strip()
        normalized = match.group(0)
    if not receive_code:
        receive_match = TG_EXTRACT_CODE_REGEX.search(str(raw_text or ""))
        if receive_match:
            receive_code = receive_match.group(1)
    return {
        "share_code": share_code,
        "receive_code": receive_code,
        "url": normalized,
    }


def normalize_share_selection_entry(item: Any) -> Dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    entry_id = str(item.get("id", "") or item.get("select_id", "")).strip()
    name = normalize_relative_path(item.get("name", ""))
    if not entry_id or not name:
        return {}
    is_dir = bool(item.get("is_dir"))
    parent_id = str(item.get("parent_id", "0") or "0").strip() or "0"
    return {
        "id": entry_id,
        "name": name,
        "is_dir": is_dir,
        "parent_id": parent_id,
        "cid": str(item.get("cid", "") or "").strip() if is_dir else "",
        "fid": str(item.get("fid", "") or "").strip() if not is_dir else "",
    }


def normalize_share_selection_meta(raw: Any) -> Dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    selected_entries: List[Dict[str, Any]] = []
    selected_ids: List[str] = []
    seen_ids: Set[str] = set()

    for item in data.get("selected_entries") or []:
        entry = normalize_share_selection_entry(item)
        entry_id = str(entry.get("id", "")).strip()
        if not entry_id or entry_id in seen_ids:
            continue
        seen_ids.add(entry_id)
        selected_entries.append(entry)
        selected_ids.append(entry_id)

    for raw_id in data.get("selected_ids") or []:
        entry_id = str(raw_id or "").strip()
        if not entry_id or entry_id in seen_ids:
            continue
        seen_ids.add(entry_id)
        selected_ids.append(entry_id)

    refresh_target_type = str(data.get("refresh_target_type", "") or "").strip().lower()
    if refresh_target_type not in ("folder", "file", "mixed"):
        if len(selected_entries) == 1:
            refresh_target_type = "folder" if selected_entries[0].get("is_dir") else "file"
        elif len(selected_ids) > 1:
            refresh_target_type = "mixed"
        else:
            refresh_target_type = ""

    auto_sharetitle = normalize_relative_path(data.get("auto_sharetitle", ""))
    if not auto_sharetitle and len(selected_entries) == 1:
        auto_sharetitle = normalize_relative_path(selected_entries[0].get("name", ""))

    return {
        "selected_ids": selected_ids,
        "selected_entries": selected_entries,
        "refresh_target_type": refresh_target_type,
        "share_root_title": normalize_relative_path(data.get("share_root_title", "")),
        "auto_sharetitle": auto_sharetitle,
        "selected_count": len(selected_ids),
    }


def merge_share_selection_meta(primary: Any, fallback: Any) -> Dict[str, Any]:
    left = normalize_share_selection_meta(primary)
    right = normalize_share_selection_meta(fallback)
    merged = {
        "selected_ids": left.get("selected_ids") or right.get("selected_ids") or [],
        "selected_entries": left.get("selected_entries") or right.get("selected_entries") or [],
        "refresh_target_type": left.get("refresh_target_type") or right.get("refresh_target_type") or "",
        "share_root_title": left.get("share_root_title") or right.get("share_root_title") or "",
        "auto_sharetitle": left.get("auto_sharetitle") or right.get("auto_sharetitle") or "",
    }
    return normalize_share_selection_meta(merged)


def resolve_115_share_payload(cookie: str, share_url: str, raw_text: str = "") -> Dict[str, str]:
    parsed = parse_115_share_payload(share_url, raw_text)
    if parsed.get("share_code"):
        return parsed
    headers = {
        "Cookie": str(cookie or "").strip(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://115.com/",
        "User-Agent": "Mozilla/5.0 115-strm-web",
    }
    resolved = http_resolve_url(share_url, timeout=30, extra_headers=headers)
    parsed = parse_115_share_payload(resolved, raw_text)
    if not parsed.get("share_code"):
        raise RuntimeError("未能识别 115 分享链接")
    return parsed


def list_115_share_entries(cookie: str, share_url: str, raw_text: str = "", cid: str = "0") -> Dict[str, Any]:
    cookie = str(cookie or "").strip()
    if not cookie:
        raise RuntimeError("115 Cookie 未配置")
    parsed = resolve_115_share_payload(cookie, share_url, raw_text)
    share_code = str(parsed.get("share_code", "") or "").strip()
    receive_code = str(parsed.get("receive_code", "") or "").strip()
    current_cid = str(cid or "0").strip() or "0"

    headers = {
        "Cookie": cookie,
        "Accept": "application/json, text/plain, */*",
        "Referer": parsed.get("url", "https://115.com/"),
        "User-Agent": "Mozilla/5.0 115-strm-web",
    }
    entries: List[Dict[str, Any]] = []
    offset = 0
    limit = 200
    total_count = 0

    while True:
        query = urllib.parse.urlencode(
            {
                "share_code": share_code,
                "receive_code": receive_code,
                "cid": current_cid,
                "offset": offset,
                "limit": limit,
                "asc": 1,
                "o": "file_name",
                "format": "json",
            }
        )
        result = http_request_json(
            f"https://webapi.115.com/share/snap?{query}",
            extra_headers=headers,
            timeout=45,
        )
        payload = result.get("data") if isinstance(result, dict) else {}
        if payload is None:
            payload = {}
        batch = payload.get("list") or []
        if not batch and not payload.get("shareinfo") and not bool(result.get("state", False)):
            detail = (
                str(result.get("error", "")).strip()
                or str(result.get("msg", "")).strip()
                or str(result.get("message", "")).strip()
                or "读取 115 分享内容失败"
            )
            raise RuntimeError(detail)

        total_count = parse_int(payload.get("count") or total_count)
        for item in batch:
            fid = str(item.get("fid") or "").strip()
            dir_cid = str(item.get("cid") or "").strip()
            is_dir = not fid
            entry_id = dir_cid if is_dir else fid
            name = str(item.get("n") or item.get("name") or "").strip()
            if not entry_id or not name:
                continue
            entries.append(
                {
                    "id": entry_id,
                    "name": name,
                    "is_dir": is_dir,
                    "parent_id": current_cid,
                    "cid": dir_cid if is_dir else "",
                    "fid": fid if not is_dir else "",
                    "size": parse_int(item.get("s") or item.get("size") or 0),
                    "pick_code": str(item.get("pick_code") or item.get("pc") or "").strip(),
                    "sha1": str(item.get("sha1") or item.get("sha") or "").strip(),
                    "icon": str(item.get("ico") or "").strip(),
                    "modified_at": str(item.get("t") or item.get("te") or item.get("tp") or "").strip(),
                }
            )

        if not batch or len(batch) < limit or (total_count and len(entries) >= total_count):
            shareinfo = payload.get("shareinfo") or {}
            entries.sort(key=lambda item: (0 if item.get("is_dir") else 1, str(item.get("name", "")).lower()))
            return {
                "entries": entries,
                "summary": {
                    "folder_count": sum(1 for item in entries if item.get("is_dir")),
                    "file_count": sum(1 for item in entries if not item.get("is_dir")),
                },
                "share_code": share_code,
                "receive_code": receive_code,
                "share_title": str(shareinfo.get("share_title") or "").strip(),
                "current_cid": current_cid,
                "count": total_count or len(entries),
            }
        offset += len(batch)


def prepare_115_share_receive(
    cookie: str,
    share_url: str,
    raw_text: str = "",
    selected_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    parsed = resolve_115_share_payload(cookie, share_url, raw_text)
    normalized_ids: List[str] = []
    seen_ids: Set[str] = set()
    for raw_id in selected_ids or []:
        entry_id = str(raw_id or "").strip()
        if not entry_id or entry_id in seen_ids:
            continue
        seen_ids.add(entry_id)
        normalized_ids.append(entry_id)

    selection: Dict[str, Any] = {}
    if not normalized_ids:
        snapshot = list_115_share_entries(cookie, parsed.get("url", share_url), raw_text, "0")
        normalized_ids = [str(entry.get("id", "")).strip() for entry in snapshot.get("entries", []) if str(entry.get("id", "")).strip()]
        selection = normalize_share_selection_meta(
            {
                "selected_ids": normalized_ids,
                "selected_entries": snapshot.get("entries", []),
                "share_root_title": snapshot.get("share_title", ""),
            }
        )
    if not normalized_ids:
        raise RuntimeError("分享内容为空，无法转存")
    return {
        "share_code": str(parsed.get("share_code", "")).strip(),
        "receive_code": str(parsed.get("receive_code", "")).strip(),
        "file_id": ",".join(normalized_ids),
        "selection": selection,
    }


def submit_115_share_receive(
    cookie: str,
    share_url: str,
    folder_id: str,
    raw_text: str = "",
    selected_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    cookie = str(cookie or "").strip()
    if not cookie:
        raise RuntimeError("115 Cookie 未配置")
    prepared = prepare_115_share_receive(cookie, share_url, raw_text, selected_ids)

    headers = {
        "Cookie": cookie,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://115.com/",
        "Origin": "https://115.com",
        "User-Agent": "Mozilla/5.0 115-strm-web",
    }
    payload = {
        "share_code": prepared.get("share_code", ""),
        "receive_code": prepared.get("receive_code", ""),
        "file_id": prepared.get("file_id", ""),
        "cid": folder_id or "0",
        "is_check": 0,
    }
    response = http_request_form_json(
        "https://115cdn.com/webapi/share/receive",
        payload,
        timeout=45,
        extra_headers=headers,
    )
    success = bool(response.get("state")) or int(response.get("errno", 0) or 0) == 4100024
    if not success:
        detail = (
            str(response.get("error", "")).strip()
            or str(response.get("msg", "")).strip()
            or str(response.get("message", "")).strip()
            or "115 网盘转存失败"
        )
        raise RuntimeError(detail)
    return {
        "response": response,
        "selection": prepared.get("selection", {}),
    }


def parse_telegram_posts_page(html: str, source: Dict[str, Any], limit: int = 10) -> Dict[str, Any]:
    channel_id = normalize_telegram_channel_id_from_input(source.get("channel_id", ""))
    if not channel_id:
        return {"posts": [], "next_before": "", "has_more": False, "matched_count": 0}
    matches = list(TG_WIDGET_POST_REGEX.finditer(html))
    if not matches:
        return {"posts": [], "next_before": "", "has_more": False, "matched_count": 0}
    normalized_limit = max(1, limit)
    start_index = max(0, len(matches) - normalized_limit)
    posts: List[Dict[str, Any]] = []
    for idx in range(start_index, len(matches)):
        match = matches[idx]
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(html)
        chunk = html[start:end]
        message_url_match = re.search(r'class="tgme_widget_message_date"[^>]+href="([^"]+)"', chunk, re.IGNORECASE)
        datetime_match = re.search(r"<time[^>]+datetime=\"([^\"]+)\"", chunk, re.IGNORECASE)
        text_match = re.search(r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', chunk, re.IGNORECASE | re.DOTALL)
        if not text_match:
            text_match = re.search(r'class="tgme_widget_message_caption[^"]*"[^>]*>(.*?)</div>', chunk, re.IGNORECASE | re.DOTALL)
        text_html = text_match.group(1) if text_match else ""
        raw_text = strip_html_to_text(text_html)
        hrefs = [unescape(link) for link in TG_LINK_HREF_REGEX.findall(chunk)]
        external_links = [
            link for link in hrefs
            if link.startswith(("http://", "https://", "magnet:?"))
            and "t.me/" not in link
            and "telegram.me/" not in link
            and "telegram.org/" not in link
        ]
        inline_links = RESOURCE_MAGNET_REGEX.findall(raw_text) + [
            url for url in RESOURCE_URL_REGEX.findall(raw_text)
            if "t.me/" not in url and "telegram.me/" not in url
        ]
        link_url = choose_resource_link(external_links + inline_links)
        if not raw_text and not link_url:
            continue
        image_match = TG_IMAGE_STYLE_REGEX.search(chunk)
        post_url = unescape(message_url_match.group(1)) if message_url_match else ""
        item = {
            "source_type": "tg",
            "source_name": str(source.get("name", "")).strip() or channel_id,
            "channel_name": channel_id,
            "title": pick_resource_title(raw_text),
            "normalized_title": pick_resource_title(raw_text).lower(),
            "raw_text": raw_text,
            "link_url": link_url,
            "link_type": detect_resource_link_type(link_url),
            "message_url": post_url,
            "quality": guess_resource_quality(raw_text),
            "year": (RESOURCE_YEAR_REGEX.search(raw_text).group(1) if RESOURCE_YEAR_REGEX.search(raw_text) else ""),
            "published_at": datetime_match.group(1) if datetime_match else "",
            "extra": {
                "cover_url": unescape(image_match.group(1)) if image_match else "",
                "source_post_id": match.group(1),
                "source_url": build_telegram_channel_url(channel_id),
            },
        }
        posts.append(item)
    has_more = start_index > 0 or bool(TG_PREV_BEFORE_REGEX.search(html))
    next_before = extract_telegram_post_cursor(posts[0].get("extra", {}).get("source_post_id", "")) if posts and has_more else ""
    return {
        "posts": posts,
        "next_before": next_before,
        "has_more": bool(next_before),
        "matched_count": len(matches),
    }


def fetch_telegram_channel_posts_page(
    cfg: Dict[str, Any],
    source: Dict[str, Any],
    limit: int = 10,
    before: str = "",
    query: str = "",
    allow_empty: bool = False,
) -> Dict[str, Any]:
    channel_id = normalize_telegram_channel_id_from_input(source.get("channel_id", ""))
    if not channel_id:
        return {"posts": [], "next_before": "", "has_more": False, "matched_count": 0}
    proxy_url = build_tg_proxy_url(cfg)
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "User-Agent": "Mozilla/5.0 115-strm-web",
    }
    request_url = build_telegram_channel_page_url(channel_id, before, query)
    html = ""
    final_url = request_url
    for attempt in range(1, TG_FETCH_RETRY_ATTEMPTS + 1):
        try:
            html, final_url = http_request_text_with_final_url(
                request_url,
                timeout=45,
                extra_headers=headers,
                proxy_url=proxy_url,
            )
            break
        except Exception as exc:
            is_retryable = is_retryable_telegram_request_error(exc)
            if attempt >= TG_FETCH_RETRY_ATTEMPTS or not is_retryable:
                detail = format_network_error(exc)
                if is_retryable and attempt > 1:
                    if not proxy_url:
                        raise RuntimeError(f"TG 直连不稳定，已重试 {attempt} 次仍失败：{detail}。请在参数配置中启用 TG 代理后重试") from exc
                    raise RuntimeError(f"TG 代理连接不稳定，已重试 {attempt} 次仍失败：{detail}。请检查 TG 代理配置或代理服务状态") from exc
                raise RuntimeError(f"TG 页面抓取失败：{detail}") from exc
            time.sleep(TG_FETCH_RETRY_DELAY_SECONDS * attempt)
    if not is_expected_telegram_channel_url(final_url, channel_id):
        raise RuntimeError(f"频道 ID 无效、频道未公开，或地址已跳转：{final_url}")
    if not TG_WIDGET_POST_REGEX.search(html):
        if allow_empty:
            return {"posts": [], "next_before": "", "has_more": False, "matched_count": 0}
        raise RuntimeError("未识别到 TG 频道帖子，请稍后重试或更换频道")
    return parse_telegram_posts_page(html, source, limit=limit)


def fetch_telegram_channel_posts(cfg: Dict[str, Any], source: Dict[str, Any], limit: int = 10) -> List[Dict[str, Any]]:
    return fetch_telegram_channel_posts_page(cfg, source, limit=limit).get("posts", [])


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
