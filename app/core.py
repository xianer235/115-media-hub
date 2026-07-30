import asyncio
import contextvars
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sqlite3
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from html import unescape
from typing import Any, AsyncIterator, Dict, List, Optional, Set, Tuple

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from .config_store import JsonConfigStore
from .db import (
    DB_PATH,
    db_connection,
    ensure_db,
    ensure_parent,
    is_sqlite_locked_error,
    retry_sqlite_locked,
    merge_json_object,
    now_text,
    open_db,
    safe_json_dumps,
    safe_json_loads,
    sqlite_row_to_dict,
)
from .http_utils import (
    http_request_binary,
    http_request_form_json,
    http_request_json,
    http_request_text,
    http_request_text_with_final_url,
    http_resolve_url,
    normalize_http_url,
)
from .resource_identity import (
    build_resource_item_identity,
    build_resource_item_identity_by_mode,
    build_resource_search_match_info,
    build_telegram_channel_page_url,
    build_telegram_channel_url,
    dedupe_resource_item_dicts,
    extract_telegram_post_cursor,
    get_resource_item_post_cursor,
    get_resource_item_sort_key,
    normalize_resource_identity_mode,
    normalize_telegram_channel_id_from_input,
    parse_resource_datetime_to_timestamp,
    resolve_resource_item_published_at,
    resource_item_matches_search,
    sort_resource_search_items,
)
from .resource_linking import (
    RESOURCE_115_SHARE_BARE_URL_REGEX,
    RESOURCE_115_SHARE_URL_REGEX,
    RESOURCE_CJK_TEXT_REGEX,
    RESOURCE_ED2K_REGEX,
    RESOURCE_LINK_TYPE_PATTERNS,
    RESOURCE_MAGNET_HASH_REGEX,
    RESOURCE_MAGNET_REGEX,
    RESOURCE_QUARK_SHARE_URL_REGEX,
    RESOURCE_URL_REGEX,
    RESOURCE_YEAR_REGEX,
    TG_EXTRACT_CODE_REGEX,
    apply_share_receive_code_to_url,
    choose_resource_link,
    contains_cjk_text,
    detect_resource_link_type,
    extract_magnet_hash,
    extract_resource_candidates,
    extract_resource_links,
    guess_resource_quality,
    is_resource_title_link_like,
    normalize_115_share_url_candidate,
    normalize_receive_code,
    normalize_resource_title,
    parse_115_share_payload,
    parse_quark_share_payload,
    pick_link_fallback_title,
    pick_magnet_title,
    pick_resource_title,
    resolve_resource_link_type,
    strip_html_to_text,
    trim_resource_link_token,
)
from .resource_store import (
    build_resource_job_snapshot,
    count_resource_items,
    get_resource_item,
    get_resource_job_snapshot,
    list_resource_channel_items,
    list_resource_items,
    sanitize_resource_job_input,
    serialize_resource_item_row,
    serialize_resource_job_row,
    update_resource_item_status,
    upsert_resource_item,
)
from .resource_tg import (
    RESOURCE_CHANNEL_TYPE_MAX_PAGES,
    RESOURCE_CHANNEL_TYPE_PAGE_LIMIT,
    RESOURCE_CHANNEL_TYPE_SAMPLE_SIZE,
    TG_CHANNEL_THREADS_DEFAULT,
    TG_CHANNEL_THREADS_MAX,
    TG_CHANNEL_SYNC_LIMIT_DEFAULT,
    TG_FETCH_RETRY_ATTEMPTS,
    TG_FETCH_RETRY_DELAY_SECONDS,
    TG_IMAGE_STYLE_REGEX,
    TG_LINK_HREF_REGEX,
    TG_PREV_BEFORE_REGEX,
    TG_SEARCH_CHANNEL_TIMEOUT_SECONDS,
    TG_SEARCH_MATCH_LIMIT_PER_CHANNEL,
    TG_SEARCH_MAX_PAGES,
    TG_SEARCH_PAGE_LIMIT,
    TG_SEARCH_REQUEST_TIMEOUT_SECONDS,
    TG_SEARCH_RETRY_ATTEMPTS,
    TG_SEARCH_TOTAL_LIMIT,
    TG_WIDGET_POST_REGEX,
    build_tg_proxy_url,
    fetch_telegram_channel_info,
    fetch_telegram_channel_post_samples,
    fetch_telegram_channel_posts,
    fetch_telegram_channel_posts_page,
    format_network_error,
    get_tg_channel_sync_limit,
    get_tg_channel_threads,
    is_expected_telegram_channel_url,
    is_retryable_telegram_request_error,
    normalize_tg_channel_sync_limit,
    parse_telegram_posts_page,
    test_telegram_latency,
    unwrap_network_error,
)
from .runtime_files import (
    DEFAULT_EXTENSIONS,
    LOG_DIR,
    LOG_ROTATE_BACKUPS,
    LOG_ROTATE_MAX_BYTES,
    AUDIO_EXTENSIONS,
    append_log_file,
    basename,
    clear_log_file,
    format_log_time,
    get_user_extensions,
    infer_log_level_from_text,
    is_audio_file,
    is_video_file,
    join_relative_path,
    join_remote_path,
    normalize_relative_path,
    normalize_remote_path,
    read_log_lines,
    read_log_tail,
    rotate_log_file_if_needed,
)
from .versioning import (
    VERSION_CACHE_TTL,
    VERSION_FILE,
    VERSION_SOURCE_URL,
    get_version_state,
    is_remote_version_newer,
    load_local_version,
    version_key,
)


RESOURCE_SEARCH_CANCEL_TTL_SECONDS = max(
    60,
    min(3600, int(os.environ.get("RESOURCE_SEARCH_CANCEL_TTL_SECONDS", 900) or 900)),
)
RESOURCE_SEARCH_CANCEL_LOCK = threading.Lock()
RESOURCE_SEARCH_CANCELLED_IDS: Dict[str, float] = {}


class ResourceSearchCancelled(RuntimeError):
    pass


def normalize_resource_search_id(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", raw).strip("-")
    return normalized[:80]


def _prune_resource_search_cancelled_locked(now_mono: Optional[float] = None) -> int:
    now_value = time.monotonic() if now_mono is None else float(now_mono or 0.0)
    expired_ids = [
        search_id
        for search_id, expires_at in RESOURCE_SEARCH_CANCELLED_IDS.items()
        if float(expires_at or 0.0) <= now_value
    ]
    for search_id in expired_ids:
        RESOURCE_SEARCH_CANCELLED_IDS.pop(search_id, None)
    return len(expired_ids)


def prune_resource_search_cancelled() -> int:
    with RESOURCE_SEARCH_CANCEL_LOCK:
        return _prune_resource_search_cancelled_locked()


def cancel_resource_search(search_id: Any) -> bool:
    normalized = normalize_resource_search_id(search_id)
    if not normalized:
        return False
    with RESOURCE_SEARCH_CANCEL_LOCK:
        now_mono = time.monotonic()
        _prune_resource_search_cancelled_locked(now_mono)
        RESOURCE_SEARCH_CANCELLED_IDS[normalized] = now_mono + RESOURCE_SEARCH_CANCEL_TTL_SECONDS
    return True


def clear_resource_search_cancel(search_id: Any) -> None:
    normalized = normalize_resource_search_id(search_id)
    if not normalized:
        return
    with RESOURCE_SEARCH_CANCEL_LOCK:
        RESOURCE_SEARCH_CANCELLED_IDS.pop(normalized, None)


def is_resource_search_cancelled(search_id: Any) -> bool:
    normalized = normalize_resource_search_id(search_id)
    if not normalized:
        return False
    with RESOURCE_SEARCH_CANCEL_LOCK:
        _prune_resource_search_cancelled_locked()
        return normalized in RESOURCE_SEARCH_CANCELLED_IDS


def check_resource_search_cancelled(search_id: Any) -> None:
    if is_resource_search_cancelled(search_id):
        raise ResourceSearchCancelled("搜索已中断")


def _resolve_session_secret() -> str:
    secret_path = "/app/config/.session_secret"
    try:
        if os.path.exists(secret_path):
            with open(secret_path, "r") as f:
                secret = f.read().strip()
            if len(secret) >= 32:
                return secret
        secret = secrets.token_hex(32)
        os.makedirs(os.path.dirname(secret_path), exist_ok=True)
        with open(secret_path, "w") as f:
            f.write(secret)
        return secret
    except Exception:
        return secrets.token_hex(32)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = str(os.environ.get(name, "1" if default else "0") or "").strip().lower()
    return raw in {"1", "true", "yes", "on", "enable", "enabled"}


def _split_env_list(value: str) -> List[str]:
    return [item.strip() for item in re.split(r"[\s,]+", value or "") if item.strip()]


app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key=_resolve_session_secret(),
    https_only=_env_flag("SESSION_HTTPS_ONLY", False),
    same_site="lax",
)

def hash_password(plain: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return f"$pbkdf2${salt}${dk.hex()}"


def verify_password(plain: str, stored: str) -> bool:
    try:
        if not stored.startswith("$pbkdf2$"):
            return hmac.compare_digest(plain, stored)
        parts = stored.split("$")
        salt = parts[2]
        expected_hex = parts[3]
        dk = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt.encode("utf-8"), 200_000)
        return hmac.compare_digest(dk.hex(), expected_hex)
    except Exception:
        return False


def is_password_hashed(stored: str) -> bool:
    return bool(stored) and stored.startswith("$pbkdf2$")


async def require_auth(request: Request) -> None:
    if not request.session.get("logged_in"):
        raise HTTPException(status_code=401, detail="未登录")


app.add_middleware(
    GZipMiddleware,
    minimum_size=1024,
)


cors_allow_origins = _split_env_list(os.environ.get("CORS_ALLOW_ORIGINS", "*"))
cors_allow_origin_regex = str(os.environ.get("CORS_ALLOW_ORIGIN_REGEX", "") or "").strip() or None
cors_allow_credentials = _env_flag("CORS_ALLOW_CREDENTIALS", False)
if cors_allow_credentials and "*" in cors_allow_origins:
    cors_allow_origins = [origin for origin in cors_allow_origins if origin != "*"]
    if not cors_allow_origins and not cors_allow_origin_regex:
        cors_allow_credentials = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allow_origins,
    allow_origin_regex=cors_allow_origin_regex,
    allow_credentials=cors_allow_credentials,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Accept",
        "Authorization",
        "Content-Type",
        "X-Requested-With",
        "X-Webhook-Token",
        "X-Webhook-Ts",
        "X-Webhook-Nonce",
        "X-Webhook-Sign",
    ],
    expose_headers=["Server-Timing", "X-Server-Time-Ms"],
    max_age=600,
)


class _StaticCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        path = request.url.path.lower()
        if path.startswith("/static/") and any(
            path.endswith(ext) for ext in (".js", ".css", ".svg", ".ico", ".png", ".woff2")
        ):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


app.add_middleware(_StaticCacheMiddleware)
HTTP_TIMING_HEADER_ENABLED = str(os.environ.get("HTTP_TIMING_HEADER_ENABLED", "0") or "0").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
    "disable",
    "disabled",
}


if HTTP_TIMING_HEADER_ENABLED:
    @app.middleware("http")
    async def add_server_timing_header(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
        rounded_ms = f"{duration_ms:.1f}"
        response.headers["Server-Timing"] = f"app;dur={rounded_ms}"
        response.headers["X-Server-Time-Ms"] = rounded_ms
        return response

CONFIG_PATH = "/app/config/settings.json"
TREE_DIR = "/app/config/trees"
STRM_ROOT = "/app/strm"
MAIN_LOG_PATH = os.path.join(LOG_DIR, "task.log")
MONITOR_LOG_PATH = os.path.join(LOG_DIR, "monitor.log")
SUBSCRIPTION_LOG_PATH = os.path.join(LOG_DIR, "subscription.log")
SUBSCRIPTION_EVENT_LOG_PATH = os.path.join(LOG_DIR, "subscription.events.jsonl")
LEGACY_DEFAULT_EXTENSIONS = "mp4,mkv,avi,mov,ts,iso,rmvb,wmv,m4v,mpg,flac,mp3,ass,srt"
MAX_MONITOR_RETRIES = 5
SUBSCRIPTION_MIN_SCORE = 55
SUBSCRIPTION_QUARK_MIN_SCORE = max(
    30,
    min(100, int(os.environ.get("SUBSCRIPTION_QUARK_MIN_SCORE", 60) or 60)),
)
SUBSCRIPTION_115_SEARCH_CANDIDATE_LIMIT = max(
    20,
    min(200, int(os.environ.get("SUBSCRIPTION_115_SEARCH_CANDIDATE_LIMIT", 80) or 80)),
)
SUBSCRIPTION_QUARK_SEARCH_CANDIDATE_LIMIT = max(
    20,
    min(200, int(os.environ.get("SUBSCRIPTION_QUARK_SEARCH_CANDIDATE_LIMIT", 120) or 120)),
)
SUBSCRIPTION_SEARCH_KEYWORD_LIMIT = max(
    1,
    min(6, int(os.environ.get("SUBSCRIPTION_SEARCH_KEYWORD_LIMIT", 2) or 2)),
)
SUBSCRIPTION_SEARCH_KEYWORD_CONCURRENCY = max(
    1,
    min(
        SUBSCRIPTION_SEARCH_KEYWORD_LIMIT,
        int(os.environ.get("SUBSCRIPTION_SEARCH_KEYWORD_CONCURRENCY", SUBSCRIPTION_SEARCH_KEYWORD_LIMIT) or SUBSCRIPTION_SEARCH_KEYWORD_LIMIT),
    ),
)
SUBSCRIPTION_SEARCH_CHANNEL_MAX_PAGES = max(
    1,
    min(20, int(os.environ.get("SUBSCRIPTION_SEARCH_CHANNEL_MAX_PAGES", 6) or 6)),
)
SUBSCRIPTION_CHANNEL_WATERMARK_OVERLAP_POSTS = max(
    0,
    min(500, int(os.environ.get("SUBSCRIPTION_CHANNEL_WATERMARK_OVERLAP_POSTS", 30) or 30)),
)
SUBSCRIPTION_MAX_CRON_MINUTES = 24 * 60
SUBSCRIPTION_MAX_SCHEDULE_INTERVAL_MINUTES = SUBSCRIPTION_MAX_CRON_MINUTES
SUBSCRIPTION_ATTEMPT_INTERVAL_SECONDS = max(
    0.0,
    min(5.0, float(os.environ.get("SUBSCRIPTION_ATTEMPT_INTERVAL_SECONDS", 2) or 2)),
)
SUBSCRIPTION_IMPORT_TIMEOUT_SECONDS = max(
    10,
    min(600, int(os.environ.get("SUBSCRIPTION_IMPORT_TIMEOUT_SECONDS", 90) or 90)),
)
SUBSCRIPTION_QUALITY_PRIORITY_DEFAULT = "balanced"
SUBSCRIPTION_QUALITY_PRIORITY_ORDERS: Dict[str, List[int]] = {
    "balanced": [1080, 720, 2160, 480, 360],
    "ultra": [2160, 1080, 720, 480, 360],
    "fhd": [1080, 2160, 720, 480, 360],
    "hd": [720, 1080, 2160, 480, 360],
    "sd": [480, 720, 1080, 2160, 360],
}
SUBSCRIPTION_QUALITY_PRIORITY_ALIASES: Dict[str, str] = {
    "auto": "balanced",
    "balanced": "balanced",
    "ultra": "ultra",
    "4k": "ultra",
    "fhd": "fhd",
    "1080p": "fhd",
    "hd": "hd",
    "720p": "hd",
    "sd": "sd",
    "480p": "sd",
}
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
UI_EVENT_RETRY_MS = 3000
UI_HEARTBEAT_SECONDS = 15
UI_PUSH_DEBOUNCE_SECONDS = max(
    0.05,
    min(2.0, float(os.environ.get("UI_PUSH_DEBOUNCE_SECONDS", 0.35) or 0.35)),
)
UI_STATUS_LOG_TAIL_LIMIT = max(
    40,
    min(300, int(os.environ.get("UI_STATUS_LOG_TAIL_LIMIT", 160) or 160)),
)
UI_STATUS_STREAM_LOG_TAIL_LIMIT = max(
    20,
    min(UI_STATUS_LOG_TAIL_LIMIT, int(os.environ.get("UI_STATUS_STREAM_LOG_TAIL_LIMIT", 40) or 40)),
)
UI_STATUS_LOG_MEMORY_LIMIT = max(
    UI_STATUS_LOG_TAIL_LIMIT,
    min(500, int(os.environ.get("UI_STATUS_LOG_MEMORY_LIMIT", 220) or 220)),
)
MONITOR_UI_RECENT_TASK_LOG_LIMIT = max(
    1,
    min(10, int(os.environ.get("MONITOR_UI_RECENT_TASK_LOG_LIMIT", 3) or 3)),
)
MONITOR_UI_TASK_LOG_MEMORY_LIMIT = max(
    MONITOR_UI_RECENT_TASK_LOG_LIMIT,
    min(30, int(os.environ.get("MONITOR_UI_TASK_LOG_MEMORY_LIMIT", 12) or 12)),
)
SUBSCRIPTION_UI_RECENT_TASK_LOG_LIMIT = max(
    1,
    min(
        20,
        int(
            os.environ.get(
                "SUBSCRIPTION_UI_RECENT_TASK_LOG_LIMIT",
                os.environ.get("SUBSCRIPTION_UI_RECENT_LOG_LIMIT", 1),
            )
            or 1
        ),
    ),
)
SUBSCRIPTION_LOG_TASK_PAGE_LIMIT = max(
    1,
    min(
        20,
        int(
            os.environ.get(
                "SUBSCRIPTION_LOG_TASK_PAGE_LIMIT",
                os.environ.get("SUBSCRIPTION_LOG_PAGE_LIMIT", 1),
            )
            or 1
        ),
    ),
)
SUBSCRIPTION_UI_RECENT_LOG_LIMIT = SUBSCRIPTION_UI_RECENT_TASK_LOG_LIMIT
SUBSCRIPTION_LOG_PAGE_LIMIT = SUBSCRIPTION_LOG_TASK_PAGE_LIMIT
TG_SYNC_TTL_SECONDS = 5 * 60
RESOURCE_CHANNEL_CACHE_LIMIT = max(1, int(os.environ.get("RESOURCE_CHANNEL_CACHE_LIMIT", 10) or 10))
RESOURCE_CHANNEL_CACHE_GLOBAL_LIMIT = max(
    RESOURCE_CHANNEL_CACHE_LIMIT,
    int(os.environ.get("RESOURCE_CHANNEL_CACHE_GLOBAL_LIMIT", 2000) or 2000),
)
SHARE_SNAP_RATE_LIMIT_SECONDS = max(
    0.05,
    min(5.0, float(os.environ.get("SHARE_SNAP_RATE_LIMIT_SECONDS", 0.2) or 0.2)),
)
SHARE_SNAP_CACHE_TTL_SECONDS = max(
    10,
    min(24 * 3600, int(os.environ.get("SHARE_SNAP_CACHE_TTL_SECONDS", 5 * 60) or (5 * 60))),
)
SHARE_SNAP_CACHE_MAX_ROWS = max(
    200,
    int(os.environ.get("SHARE_SNAP_CACHE_MAX_ROWS", 3000) or 3000),
)
API_115_RATE_LIMIT_SECONDS = max(
    0.05,
    min(2.0, float(os.environ.get("API_115_RATE_LIMIT_SECONDS", 0.35) or 0.35)),
)
API_115_LIST_CACHE_TTL_SECONDS = max(
    0,
    min(3600, int(os.environ.get("API_115_LIST_CACHE_TTL_SECONDS", 60) or 60)),
)
API_115_DOWNLOAD_URL_CACHE_TTL_SECONDS = max(
    0,
    min(600, int(os.environ.get("API_115_DOWNLOAD_URL_CACHE_TTL_SECONDS", 20) or 20)),
)
API_115_LIST_CACHE_MAX_ROWS = max(
    200,
    int(os.environ.get("API_115_LIST_CACHE_MAX_ROWS", 2000) or 2000),
)
COOKIE_HEALTH_PROVIDERS: Tuple[str, ...] = ("115", "quark")  # Will be dynamically built after providers load

def get_cookie_health_providers() -> Tuple[str, ...]:
    try:
        return tuple(p.name for p in list_all() if p.config_keys)
    except Exception:
        return ("115", "quark")


def is_cookie_health_provider_enabled(cfg: Optional[Dict[str, Any]], provider: str) -> bool:
    provider_key = normalize_cookie_health_provider(provider)
    if not provider_key:
        return False
    enabled_map = cfg.get("provider_enabled", {}) if isinstance(cfg, dict) else {}
    if not isinstance(enabled_map, dict):
        enabled_map = {}
    return bool(enabled_map.get(provider_key, provider_key in ("115", "quark")))


def get_enabled_cookie_health_providers(cfg: Optional[Dict[str, Any]] = None) -> Tuple[str, ...]:
    active_cfg = cfg or get_config()
    return tuple(
        provider
        for provider in get_cookie_health_providers()
        if is_cookie_health_provider_enabled(active_cfg, provider)
    )
COOKIE_HEALTH_MIN_REFRESH_INTERVAL_SECONDS = max(
    5,
    min(600, int(os.environ.get("COOKIE_HEALTH_MIN_REFRESH_INTERVAL_SECONDS", 20) or 20)),
)
COOKIE_HEALTH_SUCCESS_UPDATE_INTERVAL_SECONDS = max(
    10,
    min(3600, int(os.environ.get("COOKIE_HEALTH_SUCCESS_UPDATE_INTERVAL_SECONDS", 90) or 90)),
)
COOKIE_HEALTH_SHARE_TRIGGER_PREFIXES: Tuple[str, ...] = (
    "runtime:list_115_share_entries",
    "runtime:submit_115_share_receive",
    "runtime:list_quark_share_entries",
    "runtime:submit_quark_share_save",
)
COOKIE_HEALTH_INVALID_MESSAGE_HINTS: Tuple[str, ...] = (
    "cookie invalid",
    "invalid cookie",
    "no cookie",
    "not login",
    "need login",
    "login expired",
    "session expired",
    "invalid token",
    "unauthorized",
    "auth failed",
    "未登录",
    "未登入",
    "登录失效",
    "登入失效",
    "cookie失效",
    "cookie 无效",
    "登录态失效",
    "请先登录",
    "驗證失敗",
    "验证失败",
    "认证失败",
    "授權失敗",
    "授权失败",
)
COOKIE_HEALTH_TRANSIENT_MESSAGE_HINTS: Tuple[str, ...] = (
    "timeout",
    "timed out",
    "connection reset",
    "connection aborted",
    "connection refused",
    "temporary",
    "temporarily",
    "bad gateway",
    "service unavailable",
    "too many requests",
    "dns",
    "network",
    "ssl",
    "proxy",
    "连接超时",
    "连接失败",
    "网络异常",
    "网络错误",
    "请求超时",
    "服务不可用",
    "网关错误",
    "429",
    "502",
    "503",
    "504",
)
_share_snap_rate_limit_lock = threading.Lock()
_share_snap_last_request_monotonic = 0.0
_api_115_rate_limit_lock = threading.Lock()
_api_115_last_request_monotonic = 0.0
_api_115_list_cache_lock = threading.Lock()
_api_115_list_cache: Dict[str, Dict[str, Any]] = {}
_api_115_runtime_tuning_lock = threading.Lock()
_api_115_runtime_tuning: Dict[str, Any] = {
    "rate_limit_seconds": API_115_RATE_LIMIT_SECONDS,
    "list_cache_ttl_seconds": API_115_LIST_CACHE_TTL_SECONDS,
    "download_url_cache_ttl_seconds": API_115_DOWNLOAD_URL_CACHE_TTL_SECONDS,
}
DEFAULT_MOUNT_POINTS: List[Dict[str, str]] = [
    {"provider": "115", "prefix": "/115"},
    {"provider": "quark", "prefix": "/quark"},
]
_STRM_PICK_CODE_REGEX = re.compile(r"^[A-Za-z0-9]{6,32}$")
RESOURCE_CHANNEL_CACHE_ACTIVE_MIN_KEEP = max(
    0,
    min(RESOURCE_CHANNEL_CACHE_LIMIT, int(os.environ.get("RESOURCE_CHANNEL_CACHE_ACTIVE_MIN_KEEP", 10) or 10)),
)
RESOURCE_CHANNEL_INACTIVE_CACHE_LIMIT = max(0, int(os.environ.get("RESOURCE_CHANNEL_INACTIVE_CACHE_LIMIT", 5) or 5))
RESOURCE_CHANNEL_CACHE_TTL_DAYS = max(0, int(os.environ.get("RESOURCE_CHANNEL_CACHE_TTL_DAYS", 30) or 30))
RESOURCE_QUICK_LINKS_LIMIT = 60
RESOURCE_IMPORT_TIMEOUT_SECONDS = max(10, min(900, int(os.environ.get("RESOURCE_IMPORT_TIMEOUT_SECONDS", 90) or 90)))
RESOURCE_JOB_STALE_RECOVER_SECONDS = max(
    30,
    min(7 * 24 * 3600, int(os.environ.get("RESOURCE_JOB_STALE_RECOVER_SECONDS", 300) or 300)),
)
RESOURCE_JOB_COMPLETED_KEEP = max(100, min(10000, int(os.environ.get("RESOURCE_JOB_COMPLETED_KEEP", 1000) or 1000)))
RESOURCE_JOB_FAILED_KEEP = max(100, min(10000, int(os.environ.get("RESOURCE_JOB_FAILED_KEEP", 500) or 500)))
RESOURCE_JOBS_STATE_SNAPSHOT_TTL_SECONDS = max(
    0.0,
    min(5.0, float(os.environ.get("RESOURCE_JOBS_STATE_SNAPSHOT_TTL_SECONDS", 1.5) or 1.5)),
)
RESOURCE_COMPACT_STATE_SNAPSHOT_TTL_SECONDS = max(
    0.0,
    min(5.0, float(os.environ.get("RESOURCE_COMPACT_STATE_SNAPSHOT_TTL_SECONDS", 2.0) or 2.0)),
)
RESOURCE_STATE_SNAPSHOT_CACHE_MAX_ENTRIES = max(
    8,
    min(512, int(os.environ.get("RESOURCE_STATE_SNAPSHOT_CACHE_MAX_ENTRIES", 128) or 128)),
)
TMDB_API_BASE_URL = os.environ.get("TMDB_API_BASE_URL", "https://api.themoviedb.org/3").strip().rstrip("/")
TMDB_IMAGE_BASE_URL = os.environ.get("TMDB_IMAGE_BASE_URL", "https://image.tmdb.org/t/p").strip().rstrip("/")
TMDB_REQUEST_TIMEOUT_SECONDS = max(5, int(os.environ.get("TMDB_REQUEST_TIMEOUT_SECONDS", 20) or 20))
TMDB_SEARCH_LIMIT = max(1, min(20, int(os.environ.get("TMDB_SEARCH_LIMIT", 20) or 20)))
STATIC_DIR = os.path.join(BASE_DIR, "static")
FAVICON_PATH = os.path.join(STATIC_DIR, "icons", "favicon.svg")
USERSCRIPT_MAGNET_HELPER_PATH = os.path.join(BASE_DIR, "115-magnet-helper-webhook.user.js")
RESOURCE_SEASON_EPISODE_REGEX = re.compile(r"\bS(?:0|O)?(\d{1,2})\s*[-_. ]?\s*E(?:0|O)?(\d{1,4})\b", re.IGNORECASE)
RESOURCE_EPISODE_ONLY_REGEX = re.compile(r"(?:第\s*)(\d{1,4})\s*(?:集|話|话)\b", re.IGNORECASE)
RESOURCE_EPISODE_ONLY_CN_REGEX = re.compile(r"(?:第\s*)([零〇一二三四五六七八九十两兩]{1,4})\s*(?:集|話|话)\b", re.IGNORECASE)
RESOURCE_EPISODE_CODE_REGEX = re.compile(r"(?<!\d)(?:EP|E)\s*[-_. ]?\s*(\d{1,4})\b", re.IGNORECASE)
RESOURCE_EPISODE_RANGE_REGEXES = [
    re.compile(
        r"(?:第?\s*)([零〇一二三四五六七八九十两兩\d]{1,4})\s*[-~～—–－至到]\s*([零〇一二三四五六七八九十两兩\d]{1,4})\s*(?:集|話|话)?\b",
        re.IGNORECASE,
    ),
    re.compile(r"(?:EP|E)?\s*(\d{1,4})\s*[-~～—–－至到]\s*(?:EP|E)?\s*(\d{1,4})\b", re.IGNORECASE),
    re.compile(
        r"(?:更新至|更至|更新到|更到)\s*([零〇一二三四五六七八九十两兩\d]{1,4})\s*[-~～—–－至到]\s*([零〇一二三四五六七八九十两兩\d]{1,4})\s*(?:集|話|话)?\b",
        re.IGNORECASE,
    ),
]
RESOURCE_EPISODE_PROGRESS_REGEXES = [
    re.compile(r"(?:更新至|更至|更新到|更到|至|到)\s*([零〇一二三四五六七八九十两兩\d]{1,4})\s*(?:集|話|话)\b", re.IGNORECASE),
    re.compile(r"\b(?:EP|E)\s*[-_. ]?(\d{1,4})\s*(?:END|FIN)\b", re.IGNORECASE),
]
RESOURCE_SEASON_ONLY_REGEX = re.compile(r"(?:第\s*)(\d{1,2})\s*季\b", re.IGNORECASE)
RESOURCE_SEASON_ONLY_CN_REGEX = re.compile(r"(?:第\s*)([零〇一二三四五六七八九十两兩\d]{1,4})\s*季\b", re.IGNORECASE)
RESOURCE_SEASON_ENGLISH_REGEX = re.compile(r"\bSeason\s*(?:0|O)?(\d{1,2})\b", re.IGNORECASE)
RESOURCE_TOTAL_EPISODES_REGEXES = [
    re.compile(r"(?:全|共)\s*(\d{1,4})\s*(?:集|話|话)\b", re.IGNORECASE),
    re.compile(r"(\d{1,4})\s*(?:集|話|话)\s*(?:全|完结|完結)\b", re.IGNORECASE),
    re.compile(r"(?:更新至|更至)\s*(\d{1,4})\s*(?:集|話|话)\b", re.IGNORECASE),
]
RESOURCE_COLLECTION_HINT_REGEX = re.compile(
    r"(全集|完结|完結|合集|合輯|全\s*\d{1,4}\s*(?:集|話|话)|\d{1,4}\s*(?:集|話|话)\s*全)",
    re.IGNORECASE,
)
CJK_NUMERAL_DIGITS: Dict[str, int] = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "两": 2,
    "兩": 2,
}
SUBSCRIPTION_STOP_WORDS = {
    "movie",
    "movies",
    "电视剧",
    "电影",
    "tv",
    "web",
    "webrip",
    "webdl",
    "bluray",
    "x264",
    "x265",
    "h264",
    "h265",
    "hdr",
    "4k",
    "1080p",
    "2160p",
    "720p",
    "中字",
    "双语",
    "国语",
    "粤语",
}
SUBSCRIPTION_ANIME_TASK_HINT_REGEX = re.compile(r"(动漫|動畫|动画|番剧|新番|anime|animation)", re.IGNORECASE)


class CacheControlStaticFiles(StaticFiles):
    def __init__(
        self,
        *args: Any,
        asset_max_age: int = 24 * 60 * 60,
        fallback_max_age: int = 60 * 60,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.asset_max_age = max(60, int(asset_max_age or (24 * 60 * 60)))
        self.fallback_max_age = max(60, int(fallback_max_age or (60 * 60)))

    async def get_response(self, path: str, scope: Dict[str, Any]) -> Response:
        response = await super().get_response(path, scope)
        if int(getattr(response, "status_code", 500) or 500) != 200:
            return response
        if "cache-control" in response.headers:
            return response
        ext = os.path.splitext(str(path or ""))[1].lower()
        if ext in {
            ".js",
            ".css",
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".svg",
            ".webp",
            ".ico",
            ".woff",
            ".woff2",
            ".ttf",
        }:
            response.headers["Cache-Control"] = f"public, max-age={self.asset_max_age}"
        else:
            response.headers["Cache-Control"] = f"public, max-age={self.fallback_max_age}"
        return response


app.mount("/static", CacheControlStaticFiles(directory=STATIC_DIR), name="static")


def _clamp_api_115_rate_limit_seconds(value: Any, fallback: float = API_115_RATE_LIMIT_SECONDS) -> float:
    try:
        raw = float(value if value is not None else fallback)
    except Exception:
        raw = float(fallback)
    return max(0.05, min(2.0, raw))


def _clamp_api_115_list_cache_ttl_seconds(value: Any, fallback: int = API_115_LIST_CACHE_TTL_SECONDS) -> int:
    try:
        raw = int(float(value if value is not None else fallback))
    except Exception:
        raw = int(fallback)
    return max(0, min(3600, raw))


def _clamp_api_115_download_url_cache_ttl_seconds(
    value: Any,
    fallback: int = API_115_DOWNLOAD_URL_CACHE_TTL_SECONDS,
) -> int:
    try:
        raw = int(float(value if value is not None else fallback))
    except Exception:
        raw = int(fallback)
    return max(0, min(600, raw))


def apply_api_115_runtime_tuning(cfg: Optional[Dict[str, Any]] = None) -> None:
    payload = cfg or {}
    rate_limit_seconds = _clamp_api_115_rate_limit_seconds(
        payload.get("api_115_rate_limit_seconds", API_115_RATE_LIMIT_SECONDS),
        fallback=API_115_RATE_LIMIT_SECONDS,
    )
    list_cache_ttl_seconds = _clamp_api_115_list_cache_ttl_seconds(
        payload.get("api_115_list_cache_ttl_seconds", API_115_LIST_CACHE_TTL_SECONDS),
        fallback=API_115_LIST_CACHE_TTL_SECONDS,
    )
    download_url_cache_ttl_seconds = _clamp_api_115_download_url_cache_ttl_seconds(
        payload.get("api_115_download_url_cache_ttl_seconds", API_115_DOWNLOAD_URL_CACHE_TTL_SECONDS),
        fallback=API_115_DOWNLOAD_URL_CACHE_TTL_SECONDS,
    )
    with _api_115_runtime_tuning_lock:
        _api_115_runtime_tuning["rate_limit_seconds"] = rate_limit_seconds
        _api_115_runtime_tuning["list_cache_ttl_seconds"] = list_cache_ttl_seconds
        _api_115_runtime_tuning["download_url_cache_ttl_seconds"] = download_url_cache_ttl_seconds


def get_api_115_runtime_tuning() -> Dict[str, Any]:
    with _api_115_runtime_tuning_lock:
        return dict(_api_115_runtime_tuning)


_FALLBACK_PROVIDER_CONFIG_KEYS: Tuple[str, ...] = (
    "cookie_115",
    "cookie_quark",
    "cookie_tianyi",
    "tianyi_username",
    "tianyi_password",
    "123pan_username",
    "123pan_password",
    "aliyun_refresh_token",
)


_SETTINGS_CONFIG_KEY_ORDER_AFTER_AUTH: Tuple[str, ...] = (
    # 1. 网盘认证与签到
    "cookie_123pan",
    "provider_enabled",
    "default_magnet_provider",
    "resource_favorite_dirs",
    "sign115_enabled",
    "sign115_cron_time",
    # 2. 115 STRM 播放基础配置
    "strm_proxy_base_url",
    "api_115_rate_limit_seconds",
    "api_115_list_cache_ttl_seconds",
    "api_115_download_url_cache_ttl_seconds",
    "extensions",
    "strm_play_mode",
    # 3. 目录树源配置
    "trees",
    # 4. 目录树同步策略与执行模式
    "sync_mode",
    "cron_hour",
    "check_hash",
    "sync_clean",
    "last_hash",
    # 5. TG 订阅源管理
    "tg_channel_threads",
    "tg_channel_sync_limit",
    "resource_sources",
    "resource_quick_links",
    # 6. PanSou 盘搜
    "pansou_enabled",
    "pansou_base_url",
    "pansou_username",
    "pansou_password",
    "pansou_token",
    "pansou_src",
    "pansou_channels",
    "pansou_plugins",
    # 7. 网络代理
    "tg_proxy_enabled",
    "tg_proxy_protocol",
    "tg_proxy_host",
    "tg_proxy_port",
    # 8. TMDB 元数据增强
    "tmdb_enabled",
    "tmdb_api_key",
    "tmdb_cache_ttl_hours",
    "tmdb_language",
    "tmdb_region",
    # 9. 通知推送
    "notify_push_enabled",
    "notify_monitor_enabled",
    "notify_channel",
    "notify_wecom_webhook",
    "notify_wecom_app_corp_id",
    "notify_wecom_app_agent_id",
    "notify_wecom_app_secret",
    "notify_wecom_app_touser",
    # 10. 后台安全管理
    "username",
    "password",
    "webhook_secret",
    # 其他页面维护的数据
    "mount_points",
    "monitor_tasks",
    "subscription_tasks",
)


def _provider_config_key_order() -> List[str]:
    keys: List[str] = []
    seen: Set[str] = set()

    def add(key: Any) -> None:
        token = str(key or "").strip()
        if token and token not in seen:
            keys.append(token)
            seen.add(token)

    try:
        from .providers.registry import list_all as _list_all_p
        for provider in _list_all_p():
            for config_key in getattr(provider, "config_keys", []) or []:
                add(config_key)
    except Exception:
        pass

    for config_key in _FALLBACK_PROVIDER_CONFIG_KEYS:
        add(config_key)
    return keys


def order_config_for_save(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Keep settings.json readable by matching the settings page order."""
    source = cfg if isinstance(cfg, dict) else {}
    ordered: Dict[str, Any] = {}

    def add(key: Any) -> None:
        token = str(key or "").strip()
        if token and token in source and token not in ordered:
            ordered[token] = source[token]

    for key in _provider_config_key_order():
        add(key)
    for key in _SETTINGS_CONFIG_KEY_ORDER_AFTER_AUTH:
        add(key)
    for key in sorted(str(key) for key in source.keys()):
        add(key)
    return ordered


def default_config() -> Dict[str, Any]:
    return {
        "username": "admin",
        "password": "admin123",
        "webhook_secret": "",
        "strm_proxy_base_url": "",
        "api_115_rate_limit_seconds": API_115_RATE_LIMIT_SECONDS,
        "api_115_list_cache_ttl_seconds": API_115_LIST_CACHE_TTL_SECONDS,
        "api_115_download_url_cache_ttl_seconds": API_115_DOWNLOAD_URL_CACHE_TTL_SECONDS,
        "cookie_115": "",
        "cookie_quark": "",
        "cookie_tianyi": "",
        "tianyi_username": "",
        "tianyi_password": "",
        "123pan_username": "",
        "123pan_password": "",
        "aliyun_refresh_token": "",
        "provider_enabled": _build_provider_enabled_defaults(),
        "default_magnet_provider": "115",
        "sign115_enabled": False,
        "sign115_cron_time": "09:00",
        "tg_proxy_enabled": False,
        "tg_proxy_protocol": "http",
        "tg_proxy_host": "",
        "tg_proxy_port": "",
        "notify_push_enabled": False,
        "notify_monitor_enabled": False,
        "notify_channel": "wecom_bot",
        "notify_wecom_webhook": "",
        "notify_wecom_app_corp_id": "",
        "notify_wecom_app_agent_id": "",
        "notify_wecom_app_secret": "",
        "notify_wecom_app_touser": "",
        "tg_channel_threads": TG_CHANNEL_THREADS_DEFAULT,
        "tg_channel_sync_limit": TG_CHANNEL_SYNC_LIMIT_DEFAULT,
        "tmdb_enabled": False,
        "tmdb_api_key": "",
        "tmdb_language": "zh-CN",
        "tmdb_region": "CN",
        "tmdb_cache_ttl_hours": 24,
        "pansou_enabled": False,
        "pansou_base_url": "",
        "pansou_username": "",
        "pansou_password": "",
        "pansou_src": "all",
        "pansou_channels": "",
        "pansou_plugins": "",
        "mount_points": [dict(item) for item in DEFAULT_MOUNT_POINTS],
        "extensions": DEFAULT_EXTENSIONS,
        "trees": [{"source_type": "tree_file", "path": "", "prefix": "", "exclude": 1}],
        "sync_mode": "incremental",
        "sync_clean": True,
        "check_hash": True,
        "cron_hour": "",
        "last_hash": "",
        "monitor_tasks": [],
        "subscription_tasks": [],
        "resource_sources": [],
        "resource_quick_links": [],
        "resource_favorite_dirs": {"115": [], "quark": []},
    }


def normalize_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized:
            return bool(default)
        if normalized in {"1", "true", "yes", "y", "on", "enabled", "enable", "checked"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", "disabled", "disable", "unchecked", "null", "none"}:
            return False
        return bool(default)
    return bool(value)


RESOURCE_SOURCE_USAGE_OFF = "off"
RESOURCE_SOURCE_USAGE_SEARCH_ONLY = "search_only"
RESOURCE_SOURCE_USAGE_SYNC_SEARCH = "sync_search"
RESOURCE_SOURCE_USAGE_VALUES = {
    RESOURCE_SOURCE_USAGE_OFF,
    RESOURCE_SOURCE_USAGE_SEARCH_ONLY,
    RESOURCE_SOURCE_USAGE_SYNC_SEARCH,
}


def normalize_resource_source_usage(source: Dict[str, Any]) -> str:
    payload = source if isinstance(source, dict) else {}
    raw_usage = str(payload.get("usage", "") or "").strip().lower().replace("-", "_")
    if raw_usage in {"off", "disabled", "disable", "closed", "close", "none", "false", "0"}:
        return RESOURCE_SOURCE_USAGE_OFF
    if raw_usage in {"search", "search_only", "only_search", "searchonly"}:
        return RESOURCE_SOURCE_USAGE_SEARCH_ONLY
    if raw_usage in {"sync_search", "sync_and_search", "search_sync", "sync", "enabled", "enable", "on", "true", "1", "all"}:
        return RESOURCE_SOURCE_USAGE_SYNC_SEARCH

    if "sync_enabled" in payload or "search_enabled" in payload:
        sync_enabled = normalize_bool(payload.get("sync_enabled", False), default=False)
        search_enabled = normalize_bool(payload.get("search_enabled", sync_enabled), default=sync_enabled)
        if sync_enabled:
            return RESOURCE_SOURCE_USAGE_SYNC_SEARCH
        if search_enabled:
            return RESOURCE_SOURCE_USAGE_SEARCH_ONLY
        return RESOURCE_SOURCE_USAGE_OFF

    if "enabled" in payload:
        return (
            RESOURCE_SOURCE_USAGE_SYNC_SEARCH
            if normalize_bool(payload.get("enabled", True), default=True)
            else RESOURCE_SOURCE_USAGE_OFF
        )

    return RESOURCE_SOURCE_USAGE_SYNC_SEARCH


def is_resource_source_sync_enabled(source: Dict[str, Any]) -> bool:
    return normalize_resource_source_usage(source or {}) == RESOURCE_SOURCE_USAGE_SYNC_SEARCH


def is_resource_source_search_enabled(source: Dict[str, Any]) -> bool:
    return normalize_resource_source_usage(source or {}) in {
        RESOURCE_SOURCE_USAGE_SEARCH_ONLY,
        RESOURCE_SOURCE_USAGE_SYNC_SEARCH,
    }


def normalize_task(task: Dict[str, Any]) -> Dict[str, Any]:
    name = str(task.get("name", "")).strip()
    retries = int(task.get("retries", 3) or 3)
    retries = max(1, min(MAX_MONITOR_RETRIES, retries))
    raw_list_delay_ms = task.get("list_delay_ms", 250)
    if raw_list_delay_ms is None or str(raw_list_delay_ms).strip() == "":
        raw_list_delay_ms = 250
    list_delay_ms = int(raw_list_delay_ms)
    min_file_size_mb = float(task.get("min_file_size_mb", 0) or 0)
    delay_seconds = int(task.get("delay_seconds", 0) or 0)
    cron_minutes = int(task.get("cron_minutes", 0) or 0)
    if "sync_clean" in task:
        sync_clean = normalize_bool(task.get("sync_clean"), default=True)
    else:
        sync_clean = not normalize_bool(task.get("incremental", False), default=False)
    strm_write_mode = str(task.get("strm_write_mode", "incremental") or "incremental").strip().lower()
    if strm_write_mode not in {"incremental", "full"}:
        strm_write_mode = "incremental"
    return {
        "name": name,
        "webhook_enabled": normalize_bool(task.get("webhook_enabled", False), default=False),
        "scan_path": normalize_remote_path(task.get("scan_path", "")),
        "target_path": normalize_relative_path(task.get("target_path", "")),
        "skip_by_dir_mtime": normalize_bool(task.get("skip_by_dir_mtime", False), default=False),
        "strm_write_mode": strm_write_mode,
        "sync_clean": sync_clean,
        "incremental": not sync_clean,
        "retries": retries,
        "list_delay_ms": max(0, list_delay_ms),
        "min_file_size_mb": max(0, min_file_size_mb),
        "delay_seconds": max(0, delay_seconds),
        "cron_minutes": max(0, cron_minutes),
    }


def normalize_subscription_quality_priority(value: Any) -> str:
    key = str(value or "").strip().lower()
    normalized = SUBSCRIPTION_QUALITY_PRIORITY_ALIASES.get(key, key)
    if normalized not in SUBSCRIPTION_QUALITY_PRIORITY_ORDERS:
        return SUBSCRIPTION_QUALITY_PRIORITY_DEFAULT
    return normalized


def _build_provider_enabled_defaults() -> Dict[str, bool]:
    try:
        from .providers.registry import list_all as _list_all_p
        result = {}
        for p in _list_all_p():
            result[p.name] = p.name in ("115", "quark")
        return result
    except Exception:
        return {"115": True, "quark": True}


def normalize_provider_enabled_config(cfg: Dict[str, Any]) -> Dict[str, bool]:
    enabled = cfg.get("provider_enabled")
    if not isinstance(enabled, dict):
        enabled = {}
    defaults = _build_provider_enabled_defaults()
    result = {}
    for name in defaults:
        result[name] = bool(enabled.get(name, defaults[name]))
    for name in enabled:
        if name not in result:
            result[name] = bool(enabled[name])
    return result


def normalize_magnet_provider(value="115"):
    """标准化磁力默认导入网盘；当前仅 115 支持 magnet 离线下载。"""
    normalized = str(value or "").strip().lower()
    p = _get_provider_or_none(normalized)
    if p and p.supports_offline:
        return p.name
    return "115"


def normalize_subscription_provider(value: Any, fallback: str = "115") -> str:
    normalized = str(value or "").strip().lower()
    # First try exact match in registry
    p = _get_provider_or_none(normalized)
    if p:
        return p.name
    # Try by link_type
    p = get_by_link_type(normalized)
    if p:
        return p.name
    # Backward compat aliases
    if normalized in ("115share", "magnet", "magnet115"):
        return "115"
    if normalized in ("pan.quark", "quarkshare", "quark_pan"):
        return "quark"
    normalized_fallback = str(fallback or "115").strip().lower()
    return normalized_fallback if _get_provider_or_none(normalized_fallback) else "115"


def normalize_subscription_min_file_size_mb(value: Any, fallback: float = 0.0) -> float:
    raw = str(value if value is not None else fallback).strip().lower()
    if not raw:
        raw = str(fallback or 0)
    normalized = re.sub(r"\s+", "", raw)
    multiplier = 1.0
    if normalized.endswith("gb"):
        multiplier = 1024.0
        normalized = normalized[:-2]
    elif normalized.endswith("g"):
        multiplier = 1024.0
        normalized = normalized[:-1]
    elif normalized.endswith("mb"):
        normalized = normalized[:-2]
    elif normalized.endswith("m"):
        normalized = normalized[:-1]
    elif normalized.endswith("kb"):
        multiplier = 1.0 / 1024.0
        normalized = normalized[:-2]
    elif normalized.endswith("k"):
        multiplier = 1.0 / 1024.0
        normalized = normalized[:-1]
    try:
        parsed = float(normalized or fallback or 0) * multiplier
    except (TypeError, ValueError, OverflowError):
        parsed = float(fallback or 0)
    if not math.isfinite(parsed):
        parsed = float(fallback or 0)
    return round(max(0.0, parsed), 3)


def normalize_subscription_schedule_weekdays(value: Any) -> List[int]:
    if isinstance(value, str):
        payload: Any = [token.strip() for token in re.split(r"[,\s，|/]+", value) if token and token.strip()]
    elif isinstance(value, list):
        payload = value
    else:
        payload = []

    weekdays: Set[int] = set()
    for item in payload:
        try:
            weekday = int(item or 0)
        except (TypeError, ValueError):
            weekday = 0
        if 1 <= weekday <= 7:
            weekdays.add(weekday)
    return sorted(weekdays)


def normalize_subscription_schedule_time(value: Any, fallback: str = "00:00") -> str:
    text = str(value or "").strip()
    if not text:
        text = str(fallback or "00:00").strip() or "00:00"
    matched = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", text)
    if not matched:
        fallback_matched = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", str(fallback or "00:00").strip())
        if not fallback_matched:
            return "00:00"
        return f"{int(fallback_matched.group(1)):02d}:{int(fallback_matched.group(2)):02d}"
    return f"{int(matched.group(1)):02d}:{int(matched.group(2)):02d}"


def parse_subscription_schedule_time_minutes(value: Any, fallback: int = 0) -> int:
    normalized = normalize_subscription_schedule_time(value, fallback="00:00")
    try:
        hour, minute = [int(part) for part in normalized.split(":", 1)]
    except Exception:
        return max(0, min(23 * 60 + 59, int(fallback or 0)))
    return max(0, min(23 * 60 + 59, hour * 60 + minute))


def normalize_subscription_schedule_interval_minutes(value: Any, fallback: int = 120) -> int:
    try:
        interval = int(value if value is not None else fallback)
    except (TypeError, ValueError):
        interval = int(fallback or 120)
    return max(1, min(SUBSCRIPTION_MAX_SCHEDULE_INTERVAL_MINUTES, int(interval or 1)))


def compute_subscription_schedule_window_meta(
    weekdays: List[int],
    start_time: str,
    end_time: str,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    normalized_weekdays = normalize_subscription_schedule_weekdays(weekdays or [])
    normalized_start = normalize_subscription_schedule_time(start_time, fallback="00:00")
    normalized_end = normalize_subscription_schedule_time(end_time, fallback="23:59")
    if not normalized_weekdays:
        return {
            "valid": False,
            "weekdays": normalized_weekdays,
            "start_time": normalized_start,
            "end_time": normalized_end,
            "in_window": False,
            "active_start": None,
            "active_end": None,
            "next_window_start": None,
        }

    start_minutes = parse_subscription_schedule_time_minutes(normalized_start, fallback=0)
    end_minutes = parse_subscription_schedule_time_minutes(normalized_end, fallback=(23 * 60 + 59))
    if start_minutes == end_minutes:
        return {
            "valid": False,
            "weekdays": normalized_weekdays,
            "start_time": normalized_start,
            "end_time": normalized_end,
            "in_window": False,
            "active_start": None,
            "active_end": None,
            "next_window_start": None,
        }

    reference_now = now or datetime.now()
    monday_date = (reference_now - timedelta(days=reference_now.isoweekday() - 1)).date()
    crosses_day = start_minutes > end_minutes
    windows: List[Tuple[datetime, datetime]] = []

    for weekday in normalized_weekdays:
        base_start_date = monday_date + timedelta(days=weekday - 1)
        for day_offset in (-7, 0, 7):
            start_date = base_start_date + timedelta(days=day_offset)
            start_dt = datetime(
                start_date.year,
                start_date.month,
                start_date.day,
                int(start_minutes / 60),
                int(start_minutes % 60),
                0,
            )
            if crosses_day:
                end_date = start_date + timedelta(days=1)
            else:
                end_date = start_date
            end_dt = datetime(
                end_date.year,
                end_date.month,
                end_date.day,
                int(end_minutes / 60),
                int(end_minutes % 60),
                59,
            )
            windows.append((start_dt, end_dt))

    active_window: Optional[Tuple[datetime, datetime]] = None
    future_start_times: List[datetime] = []
    for start_dt, end_dt in windows:
        if start_dt <= reference_now < end_dt:
            if active_window is None or start_dt > active_window[0]:
                active_window = (start_dt, end_dt)
            continue
        if start_dt > reference_now:
            future_start_times.append(start_dt)

    future_start_times.sort()
    next_window_start = future_start_times[0] if future_start_times else None
    return {
        "valid": True,
        "weekdays": normalized_weekdays,
        "start_time": normalized_start,
        "end_time": normalized_end,
        "crosses_day": crosses_day,
        "in_window": bool(active_window),
        "active_start": active_window[0] if active_window else None,
        "active_end": active_window[1] if active_window else None,
        "next_window_start": next_window_start,
    }


def format_subscription_schedule_next_run(value: Optional[datetime]) -> str:
    if not isinstance(value, datetime):
        return ""
    weekday_labels = {
        1: "周一",
        2: "周二",
        3: "周三",
        4: "周四",
        5: "周五",
        6: "周六",
        7: "周日",
    }
    weekday = weekday_labels.get(value.isoweekday(), "")
    return f"{value.strftime('%m-%d %H:%M:%S')} {weekday}".strip()


def normalize_tmdb_media_type(value: Any, fallback: str = "") -> str:
    media_type = str(value or "").strip().lower()
    if media_type in ("movie", "tv"):
        return media_type
    if str(fallback or "").strip().lower() in ("movie", "tv"):
        return str(fallback).strip().lower()
    return ""


def normalize_tmdb_episode_mode(value: Any) -> str:
    mode = str(value or "").strip().lower()
    return "absolute" if mode == "absolute" else "seasonal"


def normalize_tmdb_season_episode_map(value: Any) -> Dict[str, int]:
    payload = value
    if isinstance(payload, str):
        text = payload.strip()
        if not text:
            payload = {}
        else:
            try:
                payload = json.loads(text)
            except Exception:
                payload = {}
    normalized: Dict[str, int] = {}

    def _assign(season_value: Any, episode_value: Any) -> None:
        try:
            season_no = int(season_value or 0)
        except (TypeError, ValueError):
            season_no = 0
        try:
            episode_count = int(episode_value or 0)
        except (TypeError, ValueError):
            episode_count = 0
        if season_no <= 0 or episode_count <= 0:
            return
        normalized[str(season_no)] = max(0, episode_count)

    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            _assign(
                item.get("season_number", item.get("season", item.get("number", 0))),
                item.get("episode_count", item.get("episodes", item.get("total_episodes", 0))),
            )
    elif isinstance(payload, dict):
        for season_key, episode_value in payload.items():
            _assign(season_key, episode_value)

    return normalized


def is_subscription_multi_season_mode(task: Dict[str, Any]) -> bool:
    payload = task if isinstance(task, dict) else {}
    return bool(payload.get("multi_season_mode", payload.get("anime_mode", False)))


def resolve_subscription_tv_episode_mode(task: Dict[str, Any]) -> str:
    media_type = str((task or {}).get("media_type", "movie") or "movie").strip().lower()
    if media_type != "tv":
        return "seasonal"
    return "absolute" if is_subscription_multi_season_mode(task) else "seasonal"


def get_subscription_tmdb_season_total_episodes(task: Dict[str, Any], season: int = 0) -> int:
    payload = task if isinstance(task, dict) else {}
    season_map = normalize_tmdb_season_episode_map(payload.get("tmdb_season_episode_map", {}))
    if not season_map:
        return 0
    target_season = max(1, int(season or payload.get("season", 1) or 1))
    return max(0, int(season_map.get(str(target_season), 0) or 0))


def resolve_subscription_tmdb_expected_total(task: Dict[str, Any]) -> int:
    payload = task if isinstance(task, dict) else {}
    media_type = str(payload.get("media_type", "movie") or "movie").strip().lower()
    if media_type != "tv" or max(0, int(payload.get("tmdb_id", 0) or 0)) <= 0:
        return 0

    season_total = get_subscription_tmdb_season_total_episodes(payload)
    tmdb_total = max(0, int(payload.get("tmdb_total_episodes", 0) or 0))
    tmdb_total_seasons = max(0, int(payload.get("tmdb_total_seasons", 0) or 0))

    if is_subscription_multi_season_mode(payload):
        return tmdb_total
    if season_total > 0:
        return season_total
    if tmdb_total_seasons <= 1:
        return tmdb_total
    return 0


def resolve_subscription_tv_total_episodes(task: Dict[str, Any], state_total: int = 0) -> int:
    payload = task if isinstance(task, dict) else {}
    media_type = str(payload.get("media_type", "movie") or "movie").strip().lower()
    if media_type != "tv":
        return 0

    multi_season_mode = is_subscription_multi_season_mode(payload)
    configured_total = max(0, int(payload.get("total_episodes", 0) or 0))
    tmdb_total = max(0, int(payload.get("tmdb_total_episodes", 0) or 0))
    tmdb_total_seasons = max(0, int(payload.get("tmdb_total_seasons", 0) or 0))
    season_total = get_subscription_tmdb_season_total_episodes(payload)
    state_total_value = max(0, int(state_total or 0))

    # 历史任务兼容：单季任务但季映射缺失时，旧数据可能把全剧总集数写入 total/state。
    if (not multi_season_mode) and season_total <= 0 and tmdb_total > 0 and tmdb_total_seasons > 1:
        if configured_total == tmdb_total:
            configured_total = 0
        if state_total_value == tmdb_total:
            state_total_value = 0

    if (not multi_season_mode) and season_total > 0:
        if configured_total <= 0:
            return season_total
        # 单季模式下，若任务总集数被历史流程写成“全剧总集数”，应回落到当前季集数。
        if tmdb_total > 0:
            if configured_total == tmdb_total and season_total != tmdb_total:
                return season_total
            if configured_total > season_total and configured_total <= tmdb_total:
                return season_total
        return configured_total

    if configured_total > 0:
        return configured_total

    if multi_season_mode:
        if tmdb_total > 0:
            return tmdb_total
    else:
        if season_total > 0:
            return season_total

    return state_total_value


def convert_subscription_episode_to_absolute(task: Dict[str, Any], season: int, episode: int) -> int:
    target_season = max(0, int(season or 0))
    target_episode = max(0, int(episode or 0))
    if target_season <= 0 or target_episode <= 0:
        return 0

    season_map = normalize_tmdb_season_episode_map((task or {}).get("tmdb_season_episode_map", {}))
    if not season_map:
        return 0

    absolute_offset = 0
    for season_no in range(1, target_season):
        season_total = max(0, int(season_map.get(str(season_no), 0) or 0))
        if season_total <= 0:
            return 0
        absolute_offset += season_total
    return absolute_offset + target_episode


def convert_subscription_episode_range_to_absolute(
    task: Dict[str, Any], season: int, range_start: int, range_end: int
) -> Tuple[int, int]:
    start = max(0, int(range_start or 0))
    end = max(0, int(range_end or 0))
    if end > 0 and start > end:
        start, end = end, start

    absolute_start = convert_subscription_episode_to_absolute(task, season, start) if start > 0 else 0
    absolute_end = convert_subscription_episode_to_absolute(task, season, end) if end > 0 else 0
    if absolute_start <= 0 and absolute_end > 0:
        absolute_start = absolute_end
    if absolute_end <= 0 and absolute_start > 0:
        absolute_end = absolute_start
    if absolute_end > 0 and absolute_start > absolute_end:
        absolute_start, absolute_end = absolute_end, absolute_start
    return absolute_start, absolute_end


def convert_subscription_absolute_to_season_episode(task: Dict[str, Any], absolute_episode: int) -> Tuple[int, int]:
    absolute_value = max(0, int(absolute_episode or 0))
    if absolute_value <= 0:
        return 0, 0

    season_map = normalize_tmdb_season_episode_map((task or {}).get("tmdb_season_episode_map", {}))
    if not season_map:
        return 0, absolute_value

    remaining = absolute_value
    season_no = 0
    while True:
        season_no += 1
        season_total = max(0, int(season_map.get(str(season_no), 0) or 0))
        if season_total <= 0:
            return 0, absolute_value
        if remaining <= season_total:
            return season_no, remaining
        remaining -= season_total


def build_subscription_tv_savepath(task: Dict[str, Any], base_savepath: str, season: int = 0, episode: int = 0) -> str:
    normalized_base = resolve_subscription_tv_base_savepath(task, base_savepath)
    if not normalized_base:
        return ""
    if str((task or {}).get("media_type", "movie") or "movie").strip().lower() != "tv":
        return normalized_base

    resolved_season = max(0, int(season or 0))
    resolved_episode = max(0, int(episode or 0))
    if resolved_season <= 0 and resolved_episode > 0 and is_subscription_multi_season_mode(task):
        mapped_season, _ = convert_subscription_absolute_to_season_episode(task, resolved_episode)
        resolved_season = mapped_season
    if resolved_season <= 0:
        resolved_season = max(1, int((task or {}).get("season", 1) or 1))

    season_folder = f"Season {resolved_season:02d}"
    return join_relative_path(normalized_base, season_folder)


def is_subscription_season_folder_name(value: Any) -> bool:
    folder_name = str(value or "").strip()
    if not folder_name:
        return False
    if re.fullmatch(r"(?i)season\s*(?:0|o)?\d{1,2}", folder_name):
        return True
    if re.fullmatch(r"(?i)s(?:0|o)?\d{1,2}", folder_name):
        return True
    if re.fullmatch(r"第\s*[零〇一二三四五六七八九十两兩\d]{1,4}\s*季", folder_name):
        return True
    return False


def resolve_subscription_tv_base_savepath(task: Dict[str, Any], base_savepath: str) -> str:
    normalized_base = normalize_relative_path(base_savepath)
    if not normalized_base:
        return ""
    payload = task if isinstance(task, dict) else {}
    if str(payload.get("media_type", "movie") or "movie").strip().lower() != "tv":
        return normalized_base

    parts = [part for part in normalized_base.split("/") if part]
    if len(parts) <= 1:
        return normalized_base
    if not is_subscription_season_folder_name(parts[-1]):
        return normalized_base

    parent_path = "/".join(parts[:-1]).strip("/")
    return parent_path or normalized_base


def resolve_subscription_tv_scan_savepath(task: Dict[str, Any], base_savepath: str) -> str:
    normalized_base = normalize_relative_path(base_savepath)
    if not normalized_base:
        return ""
    payload = task if isinstance(task, dict) else {}
    if str(payload.get("media_type", "movie") or "movie").strip().lower() != "tv":
        return normalized_base
    if is_subscription_multi_season_mode(payload):
        return resolve_subscription_tv_base_savepath(payload, normalized_base) or normalized_base
    return normalized_base


def is_subscription_anime_compatible_task(task: Dict[str, Any]) -> bool:
    payload = task if isinstance(task, dict) else {}
    media_type = str(payload.get("media_type", "movie") or "movie").strip().lower()
    if media_type != "tv":
        return False

    if normalize_tmdb_episode_mode(payload.get("tmdb_episode_mode", "seasonal")) == "absolute":
        return True

    title_values: List[str] = [
        str(payload.get("title", "") or "").strip(),
        str(payload.get("tmdb_title", "") or "").strip(),
        str(payload.get("tmdb_original_title", "") or "").strip(),
    ]
    aliases = payload.get("aliases", [])
    if isinstance(aliases, list):
        title_values.extend([str(alias or "").strip() for alias in aliases])
    tmdb_aliases = payload.get("tmdb_aliases", [])
    if isinstance(tmdb_aliases, list):
        title_values.extend([str(alias or "").strip() for alias in tmdb_aliases])

    return any(SUBSCRIPTION_ANIME_TASK_HINT_REGEX.search(value) for value in title_values if value)


def normalize_tmdb_year(value: Any) -> str:
    year = str(value or "").strip()
    return year if re.fullmatch(r"(19|20)\d{2}", year) else ""


def extract_year_from_date(value: Any) -> str:
    text = str(value or "").strip()
    matched = re.match(r"((?:19|20)\d{2})", text)
    return matched.group(1) if matched else ""


def normalize_subscription_exclude_keywords(value: Any) -> List[str]:
    if isinstance(value, list):
        joined = ",".join(str(item or "").strip() for item in value)
    else:
        joined = str(value or "")
    tokens = []
    for token in re.split(r"[,\n，]+", joined):
        normalized = re.sub(r"\s+", " ", str(token or "").strip())
        if not normalized:
            continue
        tokens.append(normalized[:60])
    return unique_preserve_order(tokens)[:50]


SUBSCRIPTION_DEFAULT_EXCLUDE_FILE_EXTENSIONS = ["zip", "rar"]


def normalize_subscription_exclude_file_extensions(value: Any) -> List[str]:
    if isinstance(value, list):
        joined = ",".join(str(item or "").strip() for item in value)
    else:
        joined = str(value or "")
    tokens = []
    for token in re.split(r"[,\n，]+", joined):
        normalized = str(token or "").strip().lower()
        normalized = normalized.lstrip(".").strip()
        normalized = re.sub(r"\s+", "", normalized)
        if not normalized:
            continue
        if not re.fullmatch(r"[a-z0-9][a-z0-9_+-]{0,29}", normalized):
            continue
        tokens.append(normalized[:30])
    return unique_preserve_order(tokens)[:50]


def resolve_subscription_exclude_file_extensions(task: Dict[str, Any]) -> List[str]:
    payload = task if isinstance(task, dict) else {}
    if "exclude_file_extensions" in payload:
        return normalize_subscription_exclude_file_extensions(payload.get("exclude_file_extensions", []))
    return list(SUBSCRIPTION_DEFAULT_EXCLUDE_FILE_EXTENSIONS)


SUBSCRIPTION_SCAN_RECOMMENDED_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "115": {
        "candidate_scan_prefetch_limit": 3,
        "candidate_scan_concurrency": 1,
        "share_scan_concurrency": 1,
        "share_scan_rate_limit_seconds": 1.0,
    },
    "quark": {
        "candidate_scan_prefetch_limit": 8,
        "candidate_scan_concurrency": 2,
        "share_scan_concurrency": 2,
        "share_scan_rate_limit_seconds": 0.35,
    },
    "tianyi": {
        "candidate_scan_prefetch_limit": 3,
        "candidate_scan_concurrency": 1,
        "share_scan_concurrency": 1,
        "share_scan_rate_limit_seconds": 1.0,
    },
    "123pan": {
        "candidate_scan_prefetch_limit": 3,
        "candidate_scan_concurrency": 1,
        "share_scan_concurrency": 1,
        "share_scan_rate_limit_seconds": 1.0,
    },
    "aliyun": {
        "candidate_scan_prefetch_limit": 3,
        "candidate_scan_concurrency": 1,
        "share_scan_concurrency": 1,
        "share_scan_rate_limit_seconds": 1.0,
    },
}


def _normalize_subscription_scan_int(value: Any, fallback: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(min_value, min(max_value, parsed))


def _normalize_subscription_scan_float(value: Any, fallback: float, min_value: float, max_value: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = fallback
    normalized = max(min_value, min(max_value, parsed))
    return round(normalized, 2)


def get_subscription_scan_recommended_defaults(provider: Any = "115") -> Dict[str, Any]:
    normalized_provider = normalize_subscription_provider(provider, fallback="115")
    defaults = SUBSCRIPTION_SCAN_RECOMMENDED_DEFAULTS.get(
        normalized_provider,
        SUBSCRIPTION_SCAN_RECOMMENDED_DEFAULTS["115"],
    )
    return dict(defaults)


def normalize_subscription_scan_settings(task: Dict[str, Any], provider: Any = "") -> Dict[str, Any]:
    payload = task if isinstance(task, dict) else {}
    normalized_provider = normalize_subscription_provider(provider or payload.get("provider", "115"), fallback="115")
    defaults = get_subscription_scan_recommended_defaults(normalized_provider)
    candidate_scan_prefetch_limit = _normalize_subscription_scan_int(
        payload.get(
            "candidate_scan_prefetch_limit",
            payload.get("candidate_scan_prewarm_limit", payload.get("scan_prewarm_limit", defaults["candidate_scan_prefetch_limit"])),
        ),
        defaults["candidate_scan_prefetch_limit"],
        0,
        80,
    )
    candidate_scan_concurrency = _normalize_subscription_scan_int(
        payload.get(
            "candidate_scan_concurrency",
            payload.get("candidate_prewarm_concurrency", defaults["candidate_scan_concurrency"]),
        ),
        defaults["candidate_scan_concurrency"],
        1,
        6,
    )
    share_scan_concurrency = _normalize_subscription_scan_int(
        payload.get(
            "share_scan_concurrency",
            payload.get("scan_concurrency", defaults["share_scan_concurrency"]),
        ),
        defaults["share_scan_concurrency"],
        1,
        6,
    )
    share_scan_rate_limit_seconds = _normalize_subscription_scan_float(
        payload.get(
            "share_scan_rate_limit_seconds",
            payload.get("scan_rate_limit_seconds", defaults["share_scan_rate_limit_seconds"]),
        ),
        float(defaults["share_scan_rate_limit_seconds"]),
        0.05,
        5.0,
    )
    return {
        "candidate_scan_prefetch_limit": candidate_scan_prefetch_limit,
        "candidate_scan_concurrency": candidate_scan_concurrency,
        "share_scan_concurrency": share_scan_concurrency,
        "share_scan_rate_limit_seconds": share_scan_rate_limit_seconds,
    }


def normalize_subscription_task(task: Dict[str, Any]) -> Dict[str, Any]:
    media_type = str(task.get("media_type", "") or task.get("type", "movie")).strip().lower()
    if media_type not in ("movie", "tv"):
        media_type = "movie"
    provider_raw = task.get("provider", task.get("disk_provider", "115"))
    if (not provider_raw) and str(task.get("share_link_url", "") or "").strip():
        provider_raw = "115"
    provider = normalize_subscription_provider(provider_raw, fallback="115")
    title = str(task.get("title", "")).strip()
    name = str(task.get("name", "") or "").strip() or title
    aliases_raw = task.get("aliases", "")
    if isinstance(aliases_raw, list):
        aliases_joined = ",".join(str(item or "").strip() for item in aliases_raw)
    else:
        aliases_joined = str(aliases_raw or "")
    aliases = unique_preserve_order(
        [
            token.strip()
            for token in re.split(r"[,\n，|/]+", aliases_joined)
            if token and token.strip()
        ]
    )
    exclude_keywords = normalize_subscription_exclude_keywords(
        task.get(
            "exclude_keywords",
            task.get("exclude_words", task.get("excluded_keywords", "")),
        )
    )
    exclude_file_extensions = resolve_subscription_exclude_file_extensions(task)
    year = str(task.get("year", "")).strip()
    if year and not re.fullmatch(r"(19|20)\d{2}", year):
        year = ""
    try:
        season = int(task.get("season", 1) or 1)
    except (TypeError, ValueError):
        season = 1
    try:
        total_episodes = int(task.get("total_episodes", 0) or 0)
    except (TypeError, ValueError):
        total_episodes = 0
    try:
        legacy_cron_minutes = int(task.get("cron_minutes", 120) or 120)
    except (TypeError, ValueError):
        legacy_cron_minutes = 120
    has_schedule_weekdays = ("schedule_weekdays" in task) or ("weekdays" in task)
    has_schedule_start = ("schedule_start_time" in task) or ("start_time" in task)
    has_schedule_end = ("schedule_end_time" in task) or ("end_time" in task)
    has_schedule_interval = ("schedule_interval_minutes" in task) or ("interval_minutes" in task)
    if has_schedule_weekdays:
        schedule_weekdays = normalize_subscription_schedule_weekdays(
            task.get("schedule_weekdays", task.get("weekdays", []))
        )
    else:
        # 旧版 cron_minutes 迁移：有定时则默认全周生效，无定时则保持“仅手动”。
        schedule_weekdays = list(range(1, 8)) if legacy_cron_minutes > 0 else []
    schedule_start_time = normalize_subscription_schedule_time(
        task.get("schedule_start_time", task.get("start_time", "00:00")) if has_schedule_start else "00:00",
        fallback="00:00",
    )
    schedule_end_time = normalize_subscription_schedule_time(
        task.get("schedule_end_time", task.get("end_time", "23:59")) if has_schedule_end else "23:59",
        fallback="23:59",
    )
    schedule_interval_raw = (
        task.get("schedule_interval_minutes", task.get("interval_minutes", legacy_cron_minutes if legacy_cron_minutes > 0 else 120))
        if has_schedule_interval
        else (legacy_cron_minutes if legacy_cron_minutes > 0 else 120)
    )
    schedule_interval_minutes = normalize_subscription_schedule_interval_minutes(
        schedule_interval_raw,
        fallback=(legacy_cron_minutes if legacy_cron_minutes > 0 else 120),
    )
    try:
        min_score = int(task.get("min_score", SUBSCRIPTION_MIN_SCORE) or SUBSCRIPTION_MIN_SCORE)
    except (TypeError, ValueError):
        min_score = SUBSCRIPTION_MIN_SCORE
    quality_priority = normalize_subscription_quality_priority(
        task.get("quality_priority", SUBSCRIPTION_QUALITY_PRIORITY_DEFAULT)
    )
    min_file_size_mb = normalize_subscription_min_file_size_mb(task.get("min_file_size_mb", 0))
    strict_title_match = normalize_bool(task.get("strict_title_match", False), default=False)
    anime_mode = bool(task.get("anime_mode", False))
    multi_season_mode = bool(task.get("multi_season_mode", anime_mode))
    tmdb_media_type = normalize_tmdb_media_type(task.get("tmdb_media_type", ""), fallback=media_type)
    try:
        tmdb_id = max(0, int(task.get("tmdb_id", 0) or 0))
    except (TypeError, ValueError):
        tmdb_id = 0
    tmdb_title = str(task.get("tmdb_title", "") or "").strip()
    tmdb_original_title = str(task.get("tmdb_original_title", "") or "").strip()
    tmdb_year = normalize_tmdb_year(task.get("tmdb_year", ""))
    tmdb_aliases_raw = task.get("tmdb_aliases", [])
    if isinstance(tmdb_aliases_raw, list):
        tmdb_aliases = unique_preserve_order([str(item or "").strip() for item in tmdb_aliases_raw if str(item or "").strip()])
    else:
        tmdb_aliases = unique_preserve_order(
            [token.strip() for token in re.split(r"[,\n，|/]+", str(tmdb_aliases_raw or "")) if token and token.strip()]
        )
    try:
        tmdb_total_episodes = max(0, int(task.get("tmdb_total_episodes", 0) or 0))
    except (TypeError, ValueError):
        tmdb_total_episodes = 0
    try:
        tmdb_total_seasons = max(0, int(task.get("tmdb_total_seasons", 0) or 0))
    except (TypeError, ValueError):
        tmdb_total_seasons = 0
    tmdb_season_episode_map = normalize_tmdb_season_episode_map(task.get("tmdb_season_episode_map", {}))
    tmdb_episode_mode = normalize_tmdb_episode_mode(task.get("tmdb_episode_mode", "seasonal"))
    if media_type != "tv":
        multi_season_mode = False
        tmdb_episode_mode = "seasonal"
    savepath = normalize_relative_path(task.get("savepath", ""))
    share_link_url = str(
        task.get(
            "share_link_url",
            task.get("fixed_share_url", task.get("subscription_share_url", "")),
        )
        or ""
    ).strip()
    share_link_type = resolve_resource_link_type("", share_link_url)
    _p = _get_provider_or_none(provider)
    _supports_fixed = bool(_p and _p.supports_fixed_share_link)
    _provider_link_type = str(getattr(_p, "link_type", "") or "").strip().lower() if _p else ""
    use_fixed_share_link = _supports_fixed and bool(_provider_link_type) and share_link_type == _provider_link_type
    if not _supports_fixed:
        share_link_url = ""
    share_link_receive_code = normalize_receive_code(
        task.get(
            "share_link_receive_code",
            task.get("fixed_share_receive_code", task.get("subscription_share_receive_code", "")),
        )
    )
    share_subdir = normalize_relative_path(
        task.get(
            "share_subdir",
            task.get("share_subdir_path", task.get("share_subfolder", "")),
        )
    )
    share_subdir_cid = normalize_115_cid(
        task.get(
            "share_subdir_cid",
            task.get("share_subdir_id", task.get("share_subfolder_cid", "")),
        )
    )
    fixed_link_channel_search = normalize_bool(
        task.get(
            "fixed_link_channel_search",
            task.get("fixed_link_followup_channel_search", False),
        ),
        default=False,
    )
    if not use_fixed_share_link:
        share_link_receive_code = ""
        share_subdir = ""
        share_subdir_cid = ""
        fixed_link_channel_search = False
    if not share_subdir:
        share_subdir_cid = ""
    scan_settings = normalize_subscription_scan_settings(task, provider)
    return {
        "name": name,
        "provider": provider,
        "media_type": media_type,
        "title": title,
        "aliases": aliases,
        "exclude_keywords": exclude_keywords,
        "exclude_file_extensions": exclude_file_extensions,
        "year": year,
        "season": max(1, season),
        "total_episodes": max(0, total_episodes),
        "savepath": savepath,
        "share_link_url": share_link_url if use_fixed_share_link else "",
        "share_link_receive_code": share_link_receive_code if use_fixed_share_link else "",
        "share_subdir": share_subdir,
        "share_subdir_cid": share_subdir_cid,
        "fixed_link_channel_search": fixed_link_channel_search if use_fixed_share_link else False,
        "enabled": normalize_bool(task.get("enabled", True), default=True),
        # 兼容旧前端字段：cron_minutes 保留为“时段内查询间隔”镜像值。
        "cron_minutes": schedule_interval_minutes,
        "schedule_weekdays": schedule_weekdays,
        "schedule_start_time": schedule_start_time,
        "schedule_end_time": schedule_end_time,
        "schedule_interval_minutes": schedule_interval_minutes,
        "min_score": max(30, min(100, min_score)),
        "quality_priority": quality_priority,
        "min_file_size_mb": min_file_size_mb,
        "strict_title_match": strict_title_match,
        "candidate_scan_prefetch_limit": scan_settings["candidate_scan_prefetch_limit"],
        "candidate_scan_concurrency": scan_settings["candidate_scan_concurrency"],
        "share_scan_concurrency": scan_settings["share_scan_concurrency"],
        "share_scan_rate_limit_seconds": scan_settings["share_scan_rate_limit_seconds"],
        # 向后兼容：anime_mode 为旧字段，语义已等同于 multi_season_mode。
        "anime_mode": multi_season_mode,
        "multi_season_mode": multi_season_mode,
        "tmdb_id": tmdb_id,
        "tmdb_media_type": tmdb_media_type if tmdb_id > 0 else "",
        "tmdb_title": tmdb_title if tmdb_id > 0 else "",
        "tmdb_original_title": tmdb_original_title if tmdb_id > 0 else "",
        "tmdb_year": tmdb_year if tmdb_id > 0 else "",
        "tmdb_aliases": tmdb_aliases if tmdb_id > 0 else [],
        "tmdb_total_episodes": tmdb_total_episodes if tmdb_id > 0 else 0,
        "tmdb_total_seasons": tmdb_total_seasons if tmdb_id > 0 else 0,
        "tmdb_season_episode_map": tmdb_season_episode_map if tmdb_id > 0 else {},
        "tmdb_episode_mode": tmdb_episode_mode if tmdb_id > 0 else "seasonal",
    }


def normalize_resource_source(source: Dict[str, Any]) -> Dict[str, Any]:
    payload = source if isinstance(source, dict) else {}
    name = str(payload.get("name", "")).strip()
    raw_channel_id = str(payload.get("channel_id", "") or payload.get("channel", "") or payload.get("id", "")).strip()
    url = str(payload.get("url", "")).strip()
    notes = str(payload.get("notes", "")).strip()
    channel_id = raw_channel_id.lstrip("@")
    if not channel_id and url:
        channel_id = normalize_telegram_channel_id_from_input(url)
    usage = normalize_resource_source_usage(payload)
    sync_enabled = usage == RESOURCE_SOURCE_USAGE_SYNC_SEARCH
    search_enabled = usage in {RESOURCE_SOURCE_USAGE_SEARCH_ONLY, RESOURCE_SOURCE_USAGE_SYNC_SEARCH}
    return {
        "name": name or channel_id or url or "未命名频道",
        "channel_id": channel_id,
        "url": build_telegram_channel_url(channel_id) if channel_id else url,
        "notes": notes,
        "usage": usage,
        "enabled": search_enabled,
        "sync_enabled": sync_enabled,
        "search_enabled": search_enabled,
    }


def create_resource_quick_link_id() -> str:
    seed = f"{time.time_ns()}-{os.urandom(8).hex()}"
    return f"rql_{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:12]}"


def normalize_resource_quick_link_name(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def normalize_resource_quick_link_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    candidate = raw if re.match(r"^[a-z][a-z0-9+.-]*://", raw, re.I) else f"https://{raw}"
    try:
        parsed = urllib.parse.urlparse(candidate)
    except Exception:
        return ""
    scheme = str(parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return ""
    netloc = str(parsed.netloc or "").strip()
    if not netloc:
        return ""
    normalized = parsed._replace(scheme=scheme, fragment="")
    return urllib.parse.urlunparse(normalized)


def build_resource_quick_link_fingerprint(url: Any) -> str:
    normalized_url = normalize_resource_quick_link_url(url)
    if not normalized_url:
        return ""
    try:
        parsed = urllib.parse.urlparse(normalized_url)
    except Exception:
        return normalized_url.lower()
    normalized = parsed._replace(
        scheme=str(parsed.scheme or "").lower(),
        netloc=str(parsed.netloc or "").lower(),
        fragment="",
    )
    return urllib.parse.urlunparse(normalized)


def suggest_resource_quick_link_name(url: Any) -> str:
    normalized_url = normalize_resource_quick_link_url(url)
    if not normalized_url:
        return "网盘分享"
    try:
        host = str(urllib.parse.urlparse(normalized_url).hostname or "").strip().lower()
    except Exception:
        host = ""
    return host or "网盘分享"


def normalize_resource_quick_link(item: Dict[str, Any]) -> Dict[str, Any]:
    payload = item if isinstance(item, dict) else {}
    normalized_url = normalize_resource_quick_link_url(
        payload.get("url", "") or payload.get("link_url", "") or payload.get("href", "")
    )
    if not normalized_url:
        return {}
    fingerprint = build_resource_quick_link_fingerprint(normalized_url)
    now_ms = int(time.time() * 1000)
    created_at_raw = int(payload.get("created_at", now_ms) or now_ms)
    updated_at_raw = int(payload.get("updated_at", created_at_raw) or created_at_raw)
    last_used_at_raw = int(payload.get("last_used_at", 0) or 0)
    return {
        "id": str(payload.get("id", "") or "").strip() or create_resource_quick_link_id(),
        "name": normalize_resource_quick_link_name(payload.get("name", "") or payload.get("title", ""))
        or suggest_resource_quick_link_name(normalized_url),
        "url": normalized_url,
        "fingerprint": fingerprint,
        "created_at": max(0, created_at_raw),
        "updated_at": max(0, updated_at_raw),
        "last_used_at": max(0, last_used_at_raw),
    }


def normalize_resource_quick_links(items: Any) -> List[Dict[str, Any]]:
    source_list = items if isinstance(items, list) else []
    normalized_links: List[Dict[str, Any]] = []
    seen_fingerprints: Set[str] = set()
    seen_ids: Set[str] = set()
    for raw_item in source_list:
        item = normalize_resource_quick_link(raw_item or {})
        if not item:
            continue
        fingerprint = str(item.get("fingerprint", "") or "").strip()
        if not fingerprint or fingerprint in seen_fingerprints:
            continue
        link_id = str(item.get("id", "") or "").strip() or create_resource_quick_link_id()
        if link_id in seen_ids:
            link_id = create_resource_quick_link_id()
        item["id"] = link_id
        seen_fingerprints.add(fingerprint)
        seen_ids.add(link_id)
        normalized_links.append(item)
        if len(normalized_links) >= RESOURCE_QUICK_LINKS_LIMIT:
            break
    return normalized_links


def normalize_resource_favorite_dir(item: Dict[str, Any]) -> Dict[str, str]:
    payload = item if isinstance(item, dict) else {}
    raw_path = payload.get("path", "") or payload.get("savepath", "") or payload.get("display_path", "")
    path = "/".join(
        part.strip()
        for part in str(raw_path or "").replace("\\", "/").split("/")
        if part.strip()
    )
    if not path:
        return {}
    name = str(payload.get("name", "") or payload.get("title", "")).strip()
    if not name:
        name = path.split("/")[-1] if path else ""
    return {
        "name": name[:32] or path,
        "path": path,
    }


def normalize_resource_favorite_dirs(value: Any) -> Dict[str, List[Dict[str, str]]]:
    source = value if isinstance(value, dict) else {}
    try:
        provider_names = [p.name for p in list_all() if p.supports_folder_browse]
    except Exception:
        provider_names = ["115", "quark"]
    result: Dict[str, List[Dict[str, str]]] = {provider: [] for provider in provider_names}
    for provider in provider_names:
        raw_items = source.get(provider, [])
        if not isinstance(raw_items, list):
            raw_items = []
        seen_paths: Set[str] = set()
        for raw_item in raw_items:
            item = normalize_resource_favorite_dir(raw_item or {})
            if not item:
                continue
            path = str(item.get("path", "") or "").strip()
            if not path or path in seen_paths:
                continue
            seen_paths.add(path)
            result[provider].append(item)
            if len(result[provider]) >= 12:
                break
    return result


def normalize_sign115_cron_time(value: Any, fallback: str = "09:00") -> str:
    text = str(value or "").strip()
    if not text:
        text = str(fallback or "09:00").strip() or "09:00"
    match = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", text)
    if not match:
        return "09:00"
    hour = int(match.group(1))
    minute = int(match.group(2))
    return f"{hour:02d}:{minute:02d}"


def normalize_http_base_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        return ""
    path = parsed.path.rstrip("/")
    return urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc, path, "", ""))


def normalize_mount_provider(value: Any) -> str:
    token = str(value or "").strip().lower()
    if not token:
        return ""
    aliases = {
        "115share": "115",
        "magnet115": "115",
        "pan.quark": "quark",
        "quarkshare": "quark",
        "quark_pan": "quark",
    }
    normalized = aliases.get(token, token)
    normalized = re.sub(r"[^a-z0-9_.-]+", "", normalized)
    if not normalized:
        return ""
    return normalized


def normalize_tree_source_type(value: Any, fallback: str = "tree_file") -> str:
    aliases = {
        "": "",
        "tree_file": "tree_file",
        "tree_txt": "tree_file",
        "tree": "tree_file",
        "txt": "tree_file",
        "file": "tree_file",
        "directory_tree": "tree_file",
    }
    raw = str(value or "").strip().lower()
    normalized = aliases.get(raw, "")
    if normalized:
        return normalized
    fallback_raw = str(fallback or "tree_file").strip().lower()
    return aliases.get(fallback_raw, "tree_file") or "tree_file"


def normalize_mount_points(value: Any) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    seen_providers: Set[str] = set()

    def push(provider_value: Any, prefix_value: Any) -> None:
        provider = normalize_mount_provider(provider_value)
        prefix = normalize_remote_path(prefix_value)
        if (not provider) or (not prefix) or prefix == "/":
            return
        if provider in seen_providers:
            return
        seen_providers.add(provider)
        normalized.append({"provider": provider, "prefix": prefix})

    raw_items: List[Dict[str, Any]] = []
    if isinstance(value, list):
        raw_items = [item for item in value if isinstance(item, dict)]
    elif isinstance(value, dict):
        raw_items = [value]

    for item in raw_items:
        push(item.get("provider", ""), item.get("prefix", ""))

    # 保底注入内置前缀，避免配置缺失导致运行时无法定位网盘根路径。
    for item in DEFAULT_MOUNT_POINTS:
        push(item.get("provider", ""), item.get("prefix", ""))

    return normalized


def get_mount_prefix(cfg: Dict[str, Any], provider: str) -> str:
    provider_key = normalize_mount_provider(provider)
    if not provider_key:
        return ""
    mount_points = normalize_mount_points(cfg.get("mount_points", []))
    for item in mount_points:
        if normalize_mount_provider(item.get("provider", "")) == provider_key:
            return normalize_remote_path(item.get("prefix", ""))
    return ""


def build_provider_remote_path(cfg: Dict[str, Any], provider: str, relative_path: str) -> str:
    prefix = get_mount_prefix(cfg, provider)
    if not prefix:
        provider_key = normalize_mount_provider(provider) or str(provider or "").strip() or "unknown"
        raise RuntimeError(f"未配置网盘前缀: {provider_key}")
    rel = normalize_relative_path(relative_path)
    return join_remote_path(prefix, rel)


def match_mount_point_by_remote_path(cfg: Dict[str, Any], remote_path: str) -> Dict[str, str]:
    normalized_remote = normalize_remote_path(remote_path)
    mount_points = normalize_mount_points(cfg.get("mount_points", []))
    ordered = sorted(
        mount_points,
        key=lambda item: len(normalize_remote_path(item.get("prefix", ""))),
        reverse=True,
    )
    for item in ordered:
        provider = normalize_mount_provider(item.get("provider", ""))
        prefix = normalize_remote_path(item.get("prefix", ""))
        if (not provider) or (not prefix) or prefix == "/":
            continue
        if normalized_remote == prefix or normalized_remote.startswith(prefix + "/"):
            relative_part = normalize_relative_path(normalized_remote[len(prefix) :])
            return {
                "provider": provider,
                "prefix": prefix,
                "remote_path": normalized_remote,
                "relative_path": relative_part,
            }
    return {}


def resolve_provider_relative_path(
    cfg: Dict[str, Any],
    remote_path: str,
    expected_provider: str = "",
) -> Tuple[str, str]:
    matched = match_mount_point_by_remote_path(cfg, remote_path)
    if not matched:
        raise RuntimeError("路径未命中任何网盘前缀，请检查网盘路径前缀映射配置")
    provider = normalize_mount_provider(matched.get("provider", ""))
    relative_path = normalize_relative_path(matched.get("relative_path", ""))
    expected_key = normalize_mount_provider(expected_provider)
    if expected_key and provider != expected_key:
        raise RuntimeError(f"路径前缀匹配到 {provider}，当前仅支持 {expected_key}")
    return provider, relative_path


def normalize_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    merged = default_config()
    merged.update(cfg or {})

    if "webhook_secret" not in merged:
        merged["webhook_secret"] = ""
    if "strm_proxy_base_url" not in merged:
        merged["strm_proxy_base_url"] = ""
    if "api_115_rate_limit_seconds" not in merged:
        merged["api_115_rate_limit_seconds"] = API_115_RATE_LIMIT_SECONDS
    if "api_115_list_cache_ttl_seconds" not in merged:
        merged["api_115_list_cache_ttl_seconds"] = API_115_LIST_CACHE_TTL_SECONDS
    if "api_115_download_url_cache_ttl_seconds" not in merged:
        merged["api_115_download_url_cache_ttl_seconds"] = API_115_DOWNLOAD_URL_CACHE_TTL_SECONDS
    if "cookie_115" not in merged:
        merged["cookie_115"] = ""
    if "cookie_quark" not in merged:
        merged["cookie_quark"] = ""
    if "cookie_tianyi" not in merged:
        merged["cookie_tianyi"] = ""
    if "tianyi_username" not in merged:
        merged["tianyi_username"] = ""
    if "tianyi_password" not in merged:
        merged["tianyi_password"] = ""
    if "provider_enabled" not in merged:
        merged["provider_enabled"] = _build_provider_enabled_defaults()
    if "default_magnet_provider" not in merged:
        merged["default_magnet_provider"] = "115"
    if "sign115_enabled" not in merged:
        merged["sign115_enabled"] = False
    if "sign115_cron_time" not in merged:
        merged["sign115_cron_time"] = "09:00"
    if "tg_proxy_enabled" not in merged:
        merged["tg_proxy_enabled"] = False
    if "tg_proxy_protocol" not in merged:
        merged["tg_proxy_protocol"] = "http"
    if "tg_proxy_host" not in merged:
        merged["tg_proxy_host"] = ""
    if "tg_proxy_port" not in merged:
        merged["tg_proxy_port"] = ""
    if "notify_push_enabled" not in merged:
        merged["notify_push_enabled"] = False
    if "notify_monitor_enabled" not in merged:
        merged["notify_monitor_enabled"] = False
    if "notify_channel" not in merged:
        merged["notify_channel"] = "wecom_bot"
    if "notify_wecom_webhook" not in merged:
        merged["notify_wecom_webhook"] = ""
    if "notify_wecom_app_corp_id" not in merged:
        merged["notify_wecom_app_corp_id"] = ""
    if "notify_wecom_app_agent_id" not in merged:
        merged["notify_wecom_app_agent_id"] = ""
    if "notify_wecom_app_secret" not in merged:
        merged["notify_wecom_app_secret"] = ""
    if "notify_wecom_app_touser" not in merged:
        merged["notify_wecom_app_touser"] = ""
    if "tg_channel_threads" not in merged:
        merged["tg_channel_threads"] = TG_CHANNEL_THREADS_DEFAULT
    if "tg_channel_sync_limit" not in merged:
        merged["tg_channel_sync_limit"] = TG_CHANNEL_SYNC_LIMIT_DEFAULT
    if "tmdb_enabled" not in merged:
        merged["tmdb_enabled"] = False
    if "tmdb_api_key" not in merged:
        merged["tmdb_api_key"] = ""
    if "tmdb_language" not in merged:
        merged["tmdb_language"] = "zh-CN"
    if "tmdb_region" not in merged:
        merged["tmdb_region"] = "CN"
    if "tmdb_cache_ttl_hours" not in merged:
        merged["tmdb_cache_ttl_hours"] = 24
    if "pansou_enabled" not in merged:
        merged["pansou_enabled"] = False
    if "pansou_base_url" not in merged:
        merged["pansou_base_url"] = ""
    if "pansou_username" not in merged:
        merged["pansou_username"] = ""
    if "pansou_password" not in merged:
        merged["pansou_password"] = ""
    if "pansou_src" not in merged:
        merged["pansou_src"] = "all"
    if "pansou_channels" not in merged:
        merged["pansou_channels"] = ""
    if "pansou_plugins" not in merged:
        merged["pansou_plugins"] = ""
    if "mount_points" not in merged or not isinstance(merged["mount_points"], list):
        merged["mount_points"] = [dict(item) for item in DEFAULT_MOUNT_POINTS]
    if "monitor_tasks" not in merged or not isinstance(merged["monitor_tasks"], list):
        merged["monitor_tasks"] = []
    if "subscription_tasks" not in merged or not isinstance(merged["subscription_tasks"], list):
        merged["subscription_tasks"] = []
    if "resource_sources" not in merged or not isinstance(merged["resource_sources"], list):
        merged["resource_sources"] = []
    if "resource_quick_links" not in merged or not isinstance(merged["resource_quick_links"], list):
        merged["resource_quick_links"] = []
    if "resource_favorite_dirs" not in merged or not isinstance(merged["resource_favorite_dirs"], dict):
        merged["resource_favorite_dirs"] = {"115": [], "quark": []}

    merged["trees"] = merged.get("trees") or [{"source_type": "tree_file", "path": "", "prefix": "", "exclude": 1}]
    if not str(merged.get("extensions", "")).strip() or merged.get("extensions") == LEGACY_DEFAULT_EXTENSIONS:
        merged["extensions"] = DEFAULT_EXTENSIONS
    normalized_trees = []
    for raw_tree in merged["trees"]:
        tree = raw_tree or {}
        source_type = normalize_tree_source_type(tree.get("source_type", "tree_file"), fallback="tree_file")
        tree_path = str(tree.get("path", "")).strip()
        try:
            exclude_val = int(tree.get("exclude", 1) or 1)
        except (TypeError, ValueError):
            exclude_val = 1
        normalized_trees.append(
            {
                "source_type": source_type,
                "path": tree_path,
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
    normalized_subscription_tasks = []
    seen_subscription_names = set()
    for raw_task in merged["subscription_tasks"]:
        task = normalize_subscription_task(raw_task or {})
        if task["name"] and task["title"] and task["savepath"] and task["name"] not in seen_subscription_names:
            normalized_subscription_tasks.append(task)
            seen_subscription_names.add(task["name"])
    merged["subscription_tasks"] = normalized_subscription_tasks
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
    merged["resource_quick_links"] = normalize_resource_quick_links(merged.get("resource_quick_links", []))
    merged["resource_favorite_dirs"] = normalize_resource_favorite_dirs(merged.get("resource_favorite_dirs", {}))
    merged["mount_points"] = normalize_mount_points(merged.get("mount_points", []))
    merged["strm_proxy_base_url"] = normalize_http_base_url(merged.get("strm_proxy_base_url", ""))
    merged["api_115_rate_limit_seconds"] = _clamp_api_115_rate_limit_seconds(
        merged.get("api_115_rate_limit_seconds", API_115_RATE_LIMIT_SECONDS),
        fallback=API_115_RATE_LIMIT_SECONDS,
    )
    merged["api_115_list_cache_ttl_seconds"] = _clamp_api_115_list_cache_ttl_seconds(
        merged.get("api_115_list_cache_ttl_seconds", API_115_LIST_CACHE_TTL_SECONDS),
        fallback=API_115_LIST_CACHE_TTL_SECONDS,
    )
    merged["api_115_download_url_cache_ttl_seconds"] = _clamp_api_115_download_url_cache_ttl_seconds(
        merged.get("api_115_download_url_cache_ttl_seconds", API_115_DOWNLOAD_URL_CACHE_TTL_SECONDS),
        fallback=API_115_DOWNLOAD_URL_CACHE_TTL_SECONDS,
    )
    merged["webhook_secret"] = str(merged.get("webhook_secret", "")).strip()
    merged["cookie_115"] = str(merged.get("cookie_115", "")).strip()
    merged["cookie_quark"] = str(merged.get("cookie_quark", "")).strip()
    merged["default_magnet_provider"] = normalize_magnet_provider(merged.get("default_magnet_provider", "115"))
    merged["pansou_enabled"] = normalize_bool(merged.get("pansou_enabled", False), default=False)
    merged["pansou_base_url"] = str(merged.get("pansou_base_url", "")).strip().rstrip("/")
    merged["pansou_username"] = str(merged.get("pansou_username", "") or "").strip()
    merged["pansou_password"] = str(merged.get("pansou_password", "") or "").strip()
    merged["pansou_src"] = str(merged.get("pansou_src", "all") or "all").strip().lower()
    if merged["pansou_src"] not in ("all", "tg", "plugin"):
        merged["pansou_src"] = "all"
    merged["pansou_channels"] = str(merged.get("pansou_channels", "") or "").strip()
    merged["pansou_plugins"] = str(merged.get("pansou_plugins", "") or "").strip()
    merged["sign115_enabled"] = normalize_bool(merged.get("sign115_enabled", False), default=False)
    merged["sign115_cron_time"] = normalize_sign115_cron_time(merged.get("sign115_cron_time", "09:00"))
    # 订阅批次收口刷新已固定为内置策略，不再保留配置项。
    merged.pop("subscription_batch_refresh_enabled", None)
    merged.pop("alist_url", None)
    merged.pop("alist_token", None)
    merged.pop("mount_path", None)
    merged["tg_proxy_enabled"] = normalize_bool(merged.get("tg_proxy_enabled", False), default=False)
    merged["tg_proxy_protocol"] = str(merged.get("tg_proxy_protocol", "http") or "http").strip().lower()
    if merged["tg_proxy_protocol"] not in ("http", "https"):
        merged["tg_proxy_protocol"] = "http"
    merged["tg_proxy_host"] = str(merged.get("tg_proxy_host", "")).strip()
    merged["tg_proxy_port"] = str(merged.get("tg_proxy_port", "")).strip()
    merged["notify_push_enabled"] = normalize_bool(merged.get("notify_push_enabled", False), default=False)
    merged["notify_monitor_enabled"] = normalize_bool(merged.get("notify_monitor_enabled", False), default=False)
    notify_channel = str(merged.get("notify_channel", "wecom_bot") or "wecom_bot").strip().lower()
    merged["notify_channel"] = notify_channel if notify_channel in ("wecom_bot", "wecom_app") else "wecom_bot"
    merged["notify_wecom_webhook"] = str(merged.get("notify_wecom_webhook", "")).strip()
    merged["notify_wecom_app_corp_id"] = str(merged.get("notify_wecom_app_corp_id", "")).strip()
    merged["notify_wecom_app_agent_id"] = str(merged.get("notify_wecom_app_agent_id", "")).strip()
    merged["notify_wecom_app_secret"] = str(merged.get("notify_wecom_app_secret", "")).strip()
    merged["notify_wecom_app_touser"] = str(merged.get("notify_wecom_app_touser", "")).strip()
    merged["tmdb_enabled"] = normalize_bool(merged.get("tmdb_enabled", False), default=False)
    merged["tmdb_api_key"] = str(merged.get("tmdb_api_key", "")).strip()
    tmdb_lang = str(merged.get("tmdb_language", "zh-CN") or "zh-CN").strip()
    merged["tmdb_language"] = tmdb_lang if re.fullmatch(r"[a-z]{2}-[A-Z]{2}", tmdb_lang) else "zh-CN"
    tmdb_region = str(merged.get("tmdb_region", "CN") or "CN").strip().upper()
    merged["tmdb_region"] = tmdb_region if re.fullmatch(r"[A-Z]{2}", tmdb_region) else "CN"
    try:
        tmdb_cache_ttl_hours = int(merged.get("tmdb_cache_ttl_hours", 24) or 24)
    except (TypeError, ValueError):
        tmdb_cache_ttl_hours = 24
    merged["tmdb_cache_ttl_hours"] = max(1, min(24 * 30, tmdb_cache_ttl_hours))
    try:
        tg_channel_threads = int(merged.get("tg_channel_threads", TG_CHANNEL_THREADS_DEFAULT) or TG_CHANNEL_THREADS_DEFAULT)
    except (TypeError, ValueError):
        tg_channel_threads = TG_CHANNEL_THREADS_DEFAULT
    merged["tg_channel_threads"] = max(1, min(TG_CHANNEL_THREADS_MAX, tg_channel_threads))
    merged["tg_channel_sync_limit"] = normalize_tg_channel_sync_limit(
        merged.get("tg_channel_sync_limit", TG_CHANNEL_SYNC_LIMIT_DEFAULT),
        fallback=TG_CHANNEL_SYNC_LIMIT_DEFAULT,
    )
    merged["provider_enabled"] = normalize_provider_enabled_config(merged)
    stored_pw = str(merged.get("password", "") or "")
    if stored_pw and not is_password_hashed(stored_pw):
        merged["password"] = hash_password(stored_pw)
    return order_config_for_save(merged)


_config_store_lock = threading.Lock()
_config_store: Optional[JsonConfigStore] = None


def _get_config_store() -> JsonConfigStore:
    global _config_store
    with _config_store_lock:
        if _config_store is None:
            _config_store = JsonConfigStore(
                path=CONFIG_PATH,
                default_factory=default_config,
                normalize=normalize_config,
                post_load=apply_api_115_runtime_tuning,
                post_save=apply_api_115_runtime_tuning,
            )
        return _config_store


def get_config() -> Dict[str, Any]:
    return _get_config_store().get()


def save_config(cfg: Dict[str, Any]) -> None:
    _get_config_store().save(cfg)


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


def normalize_115_cid(value: Any) -> str:
    token = re.sub(r"\s+", "", str(value or "").strip())
    if not token or token == "0":
        return ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", token):
        return ""
    return token


def normalize_115_pick_code(value: Any) -> str:
    token = str(value or "").strip()
    if not token:
        return ""
    if not _STRM_PICK_CODE_REGEX.fullmatch(token):
        return ""
    return token


from .subscription_scoring import (
    build_subscription_candidate_identity_text,
    build_subscription_candidate_text,
    build_subscription_query_tokens,
    build_subscription_text_tokens,
    compact_subscription_text,
    detect_resource_year,
    detect_subscription_resolution,
    evaluate_subscription_candidate_title_match,
    extract_subscription_candidate_tmdb_ids,
    extract_subscription_tmdb_ids_from_text,
    filter_subscription_manifest_files_by_strict_identity,
    is_subscription_strict_title_match,
    match_subscription_exclude_keyword,
    match_subscription_media_type,
    parse_resource_episode_meta,
    parse_small_cjk_number,
    pick_subscription_display_title,
    score_subscription_candidate,
    score_subscription_candidate_quark,
    score_subscription_quality_preference,
    score_subscription_title_signal,
    strip_subscription_cjk_particles,
    subscription_token_hit,
)





















































































def prune_resource_channel_cache(conn: sqlite3.Connection, channel_id: str, keep: int = RESOURCE_CHANNEL_CACHE_LIMIT) -> int:
    normalized_channel = normalize_telegram_channel_id_from_input(channel_id)
    keep_limit = max(0, int(keep if keep is not None else RESOURCE_CHANNEL_CACHE_LIMIT))
    if not normalized_channel:
        return 0
    cursor = conn.cursor()
    if keep_limit == 0:
        cursor.execute(
            "DELETE FROM resource_items WHERE source_type = 'tg' AND channel_name = ?",
            (normalized_channel,),
        )
        return int(cursor.rowcount or 0)
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


def delete_resource_items_by_ids(conn: sqlite3.Connection, item_ids: List[int], chunk_size: int = 300) -> int:
    normalized_ids = [int(item_id) for item_id in (item_ids or []) if int(item_id or 0) > 0]
    if not normalized_ids:
        return 0
    cursor = conn.cursor()
    deleted = 0
    size = max(50, min(int(chunk_size or 300), 600))
    for start in range(0, len(normalized_ids), size):
        batch = normalized_ids[start:start + size]
        placeholders = ",".join(["?"] * len(batch))
        cursor.execute(f"DELETE FROM resource_items WHERE id IN ({placeholders})", batch)
        deleted += int(cursor.rowcount or 0)
    return deleted


def list_sync_resource_channel_ids(sources: List[Dict[str, Any]]) -> Set[str]:
    channel_ids: Set[str] = set()
    for source in sources or []:
        if not is_resource_source_sync_enabled(source or {}):
            continue
        channel_id = normalize_telegram_channel_id_from_input(source.get("channel_id", ""))
        if channel_id:
            channel_ids.add(channel_id)
    return channel_ids


def list_search_resource_channel_ids(sources: List[Dict[str, Any]]) -> Set[str]:
    channel_ids: Set[str] = set()
    for source in sources or []:
        if not is_resource_source_search_enabled(source or {}):
            continue
        channel_id = normalize_telegram_channel_id_from_input(source.get("channel_id", ""))
        if channel_id:
            channel_ids.add(channel_id)
    return channel_ids


def list_enabled_resource_channel_ids(sources: List[Dict[str, Any]]) -> Set[str]:
    return list_sync_resource_channel_ids(sources)


def prune_resource_inactive_channel_cache(
    conn: sqlite3.Connection,
    active_channel_ids: Set[str],
    keep: int = RESOURCE_CHANNEL_INACTIVE_CACHE_LIMIT,
) -> int:
    keep_limit = max(0, int(keep or 0))
    active = set(active_channel_ids or set())
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT channel_name FROM resource_items WHERE source_type = 'tg' AND channel_name <> ''")
    deleted = 0
    for row in cursor.fetchall():
        channel_id = normalize_telegram_channel_id_from_input(row[0] if row else "")
        if not channel_id or channel_id in active:
            continue
        deleted += prune_resource_channel_cache(conn, channel_id, keep=keep_limit)
    return deleted


def prune_resource_cache_by_age(conn: sqlite3.Connection, max_age_days: int = RESOURCE_CHANNEL_CACHE_TTL_DAYS) -> int:
    days = max(0, int(max_age_days or 0))
    if days <= 0:
        return 0
    cutoff_ts = time.time() - (days * 86400)
    cursor = conn.cursor()
    cursor.execute("SELECT id, published_at, created_at FROM resource_items WHERE source_type = 'tg'")
    stale_ids: List[int] = []
    for row in cursor.fetchall():
        item_id = int(row[0] or 0)
        if item_id <= 0:
            continue
        published_at = str(row[1] or "").strip()
        created_at = str(row[2] or "").strip()
        ts = parse_resource_datetime_to_timestamp(published_at) or parse_resource_datetime_to_timestamp(created_at)
        if ts > 0 and ts < cutoff_ts:
            stale_ids.append(item_id)
    return delete_resource_items_by_ids(conn, stale_ids)


def prune_resource_cache_global_limit(
    conn: sqlite3.Connection,
    total_limit: int = RESOURCE_CHANNEL_CACHE_GLOBAL_LIMIT,
    active_channel_ids: Optional[Set[str]] = None,
    min_keep_per_active: int = RESOURCE_CHANNEL_CACHE_ACTIVE_MIN_KEEP,
) -> int:
    hard_limit = max(1, int(total_limit or RESOURCE_CHANNEL_CACHE_GLOBAL_LIMIT))
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(1) FROM resource_items WHERE source_type = 'tg'")
    total_count = int((cursor.fetchone() or [0])[0] or 0)
    overflow = total_count - hard_limit
    if overflow <= 0:
        return 0

    deleted = 0
    keep_per_active = max(0, int(min_keep_per_active or 0))
    active = set(active_channel_ids or set())
    if active and keep_per_active > 0:
        active_token = "|" + "|".join(sorted(active)) + "|"
        try:
            cursor.execute(
                """
                WITH ranked AS (
                    SELECT
                        id,
                        channel_name,
                        CASE WHEN published_at <> '' THEN published_at ELSE created_at END AS sort_at,
                        ROW_NUMBER() OVER (
                            PARTITION BY channel_name
                            ORDER BY CASE WHEN published_at <> '' THEN published_at ELSE created_at END DESC, id DESC
                        ) AS channel_rank,
                        CASE WHEN instr(?, '|' || channel_name || '|') > 0 THEN 1 ELSE 0 END AS is_active
                    FROM resource_items
                    WHERE source_type = 'tg'
                )
                SELECT id
                FROM ranked
                WHERE NOT (is_active = 1 AND channel_rank <= ?)
                ORDER BY sort_at ASC, id ASC
                LIMIT ?
                """,
                (active_token, keep_per_active, overflow),
            )
            protected_candidates = [int(row[0]) for row in cursor.fetchall() if row and row[0]]
            deleted += delete_resource_items_by_ids(conn, protected_candidates)
        except sqlite3.OperationalError:
            deleted = 0

    remaining = max(0, overflow - deleted)
    if remaining > 0:
        cursor.execute(
            """
            SELECT id
            FROM resource_items
            WHERE source_type = 'tg'
            ORDER BY CASE WHEN published_at <> '' THEN published_at ELSE created_at END ASC, id ASC
            LIMIT ?
            """,
            (remaining,),
        )
        fallback_ids = [int(row[0]) for row in cursor.fetchall() if row and row[0]]
        deleted += delete_resource_items_by_ids(conn, fallback_ids)
    return deleted


def run_resource_cache_governance(
    conn: sqlite3.Connection,
    sources: List[Dict[str, Any]],
    active_min_keep: int = RESOURCE_CHANNEL_CACHE_ACTIVE_MIN_KEEP,
) -> Dict[str, int]:
    active_channel_ids = list_sync_resource_channel_ids(sources or [])
    inactive_pruned = prune_resource_inactive_channel_cache(conn, active_channel_ids, RESOURCE_CHANNEL_INACTIVE_CACHE_LIMIT)
    expired_pruned = prune_resource_cache_by_age(conn, RESOURCE_CHANNEL_CACHE_TTL_DAYS)
    protected_keep = max(0, int(active_min_keep or RESOURCE_CHANNEL_CACHE_ACTIVE_MIN_KEEP))
    global_pruned = prune_resource_cache_global_limit(
        conn,
        RESOURCE_CHANNEL_CACHE_GLOBAL_LIMIT,
        active_channel_ids,
        protected_keep,
    )
    return {
        "inactive": inactive_pruned,
        "expired": expired_pruned,
        "global": global_pruned,
        "active_channels": len(active_channel_ids),
    }


def build_resource_channel_profile(
    channel_id: str,
    items: List[Dict[str, Any]],
    sample_size: int = RESOURCE_CHANNEL_TYPE_SAMPLE_SIZE,
) -> Dict[str, Any]:
    normalized_channel = normalize_telegram_channel_id_from_input(channel_id)
    sorted_items = dedupe_resource_item_dicts(items or [])
    sorted_items.sort(key=get_resource_item_sort_key, reverse=True)
    sample = sorted_items[: max(1, int(sample_size or RESOURCE_CHANNEL_TYPE_SAMPLE_SIZE))]
    link_type_counts: Dict[str, int] = {}
    latest_published_at = ""
    latest_timestamp = 0.0

    for item in sample:
        resolved_type = resolve_resource_link_type(item.get("link_type", ""), item.get("link_url", ""))
        normalized_type = str(resolved_type or "unknown").strip().lower() or "unknown"
        link_type_counts[normalized_type] = int(link_type_counts.get(normalized_type, 0) or 0) + 1

        published_at = resolve_resource_item_published_at(item)
        ts = parse_resource_datetime_to_timestamp(published_at)
        if ts > latest_timestamp and published_at:
            latest_timestamp = ts
            latest_published_at = published_at

    sorted_types = sorted(link_type_counts.items(), key=lambda pair: (-int(pair[1] or 0), pair[0]))
    dominant_types = [name for name, _ in sorted_types[:3]]
    primary_type = dominant_types[0] if dominant_types else "unknown"
    top_count = int(sorted_types[0][1] if sorted_types else 0)
    sample_count = len(sample)
    confidence = round(top_count / max(1, sample_count), 3)
    return {
        "channel_id": normalized_channel,
        "sample_size": sample_count,
        "analyzed_at": now_text(),
        "latest_published_at": latest_published_at,
        "latest_published_ts": latest_timestamp,
        "primary_link_type": primary_type,
        "dominant_link_types": dominant_types,
        "link_type_counts": link_type_counts,
        "confidence": confidence,
    }


def normalize_resource_provider_filter(value: Any) -> str:
    normalized = str(value or "all").strip().lower()
    if normalized == "all":
        return "all"
    if normalized == "magnet":
        return "magnet"
    p = _get_provider_or_none(normalized)
    if p:
        return p.name
    p = get_by_link_type(normalized)
    if p:
        return p.name
    # Backward compat
    if normalized == "115share":
        return "115"
    if normalized in ("quarkshare", "pan.quark"):
        return "quark"
    return "all"


def normalize_resource_search_source(value: Any) -> str:
    normalized = str(value or "tg").strip().lower()
    if normalized in ("pansou", "pan", "盘搜"):
        return "pansou"
    return "tg"


def resource_item_matches_provider_filter(item: Dict[str, Any], provider_filter: str = "all") -> bool:
    normalized_filter = normalize_resource_provider_filter(provider_filter)
    if normalized_filter == "all":
        return True
    payload = item if isinstance(item, dict) else {}
    link_type = resolve_resource_link_type(payload.get("link_type", ""), payload.get("link_url", ""))
    if normalized_filter == "magnet":
        return link_type in ("magnet", "ed2k")
    p = _get_provider_or_none(normalized_filter)
    if p:
        return link_type == p.link_type
    return False


def filter_resource_items_by_provider(
    items: List[Dict[str, Any]],
    provider_filter: str = "all",
) -> List[Dict[str, Any]]:
    normalized_filter = normalize_resource_provider_filter(provider_filter)
    if normalized_filter == "all":
        return list(items or [])
    return [item for item in (items or []) if resource_item_matches_provider_filter(item, normalized_filter)]


def filter_resource_sections_by_provider(
    sections: List[Dict[str, Any]],
    provider_filter: str = "all",
    *,
    drop_empty: bool = True,
) -> List[Dict[str, Any]]:
    normalized_filter = normalize_resource_provider_filter(provider_filter)
    if normalized_filter == "all":
        return list(sections or [])
    filtered_sections: List[Dict[str, Any]] = []
    for raw_section in sections or []:
        section = raw_section if isinstance(raw_section, dict) else {}
        filtered_items = filter_resource_items_by_provider(section.get("items", []), normalized_filter)
        if drop_empty and not filtered_items:
            continue
        filtered_sections.append(
            {
                **section,
                "items": filtered_items,
                "item_count": len(filtered_items),
                "has_more": bool(section.get("has_more", False)) and not drop_empty,
                "next_before": str(section.get("next_before", "") or "") if not drop_empty else "",
            }
        )
    return filtered_sections


def build_resource_channel_sections(
    sources: List[Dict[str, Any]],
    items: Optional[List[Dict[str, Any]]] = None,
    per_channel: int = 10,
) -> List[Dict[str, Any]]:
    sections: List[Dict[str, Any]] = []
    indexed_items: Dict[str, List[Dict[str, Any]]] = {}
    batch_channel_items: Dict[str, List[Dict[str, Any]]] = {}
    batch_channel_counts: Dict[str, int] = {}
    if items is not None:
        for item in items:
            item_channel_id = normalize_telegram_channel_id_from_input(item.get("channel_name", ""))
            if not item_channel_id:
                continue
            indexed_items.setdefault(item_channel_id, []).append(item)
    else:
        channel_ids = [
            normalize_telegram_channel_id_from_input((source or {}).get("channel_id", ""))
            for source in (sources or [])
            if isinstance(source, dict) and is_resource_source_sync_enabled(source)
        ]
        sample_limit = max(per_channel, RESOURCE_CHANNEL_TYPE_SAMPLE_SIZE)
        batch_channel_items, batch_channel_counts = list_resource_channel_items(channel_ids, limit_per_channel=sample_limit)
    for raw_source in sources:
        source = normalize_resource_source(raw_source or {})
        if not is_resource_source_sync_enabled(source):
            continue
        channel_id = normalize_telegram_channel_id_from_input(source.get("channel_id", ""))
        if not channel_id:
            continue
        if items is not None:
            channel_pool = indexed_items.get(channel_id, [])
            channel_items = channel_pool[:per_channel]
            item_count = len(channel_pool)
            cached_profile = resource_channel_profiles.get(channel_id, {})
            channel_profile = cached_profile if cached_profile else build_resource_channel_profile(channel_id, channel_pool)
        else:
            channel_pool = batch_channel_items.get(channel_id, [])
            channel_items = channel_pool[:per_channel]
            item_count = int(batch_channel_counts.get(channel_id, len(channel_pool)) or 0)
            cached_profile = resource_channel_profiles.get(channel_id, {})
            if cached_profile:
                channel_profile = cached_profile
            elif channel_pool:
                channel_profile = build_resource_channel_profile(channel_id, channel_pool)
            else:
                channel_profile = {}
        if channel_profile:
            resource_channel_profiles[channel_id] = clone_jsonable(channel_profile)
        else:
            channel_profile = {}
        fallback_next_before = get_resource_item_post_cursor(channel_items[-1]) if channel_items else ""
        has_more = item_count > len(channel_items)
        if not has_more and fallback_next_before and len(channel_items) >= max(1, int(per_channel or 10)):
            # Channel sync intentionally keeps only the first page in cache; allow on-demand TG paging.
            has_more = True
        next_before = fallback_next_before if has_more else ""
        sections.append(
            {
                "name": source.get("name", channel_id),
                "channel_id": channel_id,
                "url": build_telegram_channel_url(channel_id),
                "usage": source.get("usage", RESOURCE_SOURCE_USAGE_SYNC_SEARCH),
                "enabled": bool(source.get("search_enabled", True)),
                "sync_enabled": bool(source.get("sync_enabled", True)),
                "search_enabled": bool(source.get("search_enabled", True)),
                "last_sync_at": resource_channel_last_sync.get(channel_id, 0.0),
                "last_error": resource_channel_last_error.get(channel_id, ""),
                "item_count": item_count,
                "items": channel_items[:per_channel],
                "next_before": next_before,
                "has_more": bool(has_more and next_before),
                "channel_profile": clone_jsonable(channel_profile),
                "latest_published_at": str(channel_profile.get("latest_published_at", "")).strip(),
                "primary_link_type": str(channel_profile.get("primary_link_type", "unknown")).strip() or "unknown",
                "dominant_link_types": clone_jsonable(channel_profile.get("dominant_link_types", [])),
                "link_type_counts": clone_jsonable(channel_profile.get("link_type_counts", {})),
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
    identity_mode: str = "message",
    stop_cursor: int = 0,
    request_timeout_seconds: int = 45,
    retry_attempts: int = TG_FETCH_RETRY_ATTEMPTS,
    provider_filter: str = "all",
    search_id: str = "",
) -> Dict[str, Any]:
    normalized_source = normalize_resource_source(source or {})
    channel_id = normalize_telegram_channel_id_from_input(normalized_source.get("channel_id", ""))
    if not channel_id:
        return {"channel_id": "", "items": [], "pages_scanned": 0, "next_before": "", "has_more": False}

    normalized_identity_mode = normalize_resource_identity_mode(identity_mode, fallback="message")
    items: List[Dict[str, Any]] = []
    before = extract_telegram_post_cursor(start_before)
    pages_scanned = 0
    seen_keys: Set[str] = set()
    next_before = ""
    has_more = False
    incremental_stop_hit = False
    latest_scanned_cursor = 0
    latest_scanned_published_at = ""
    latest_scanned_published_ts = 0.0
    normalized_stop_cursor = max(0, int(stop_cursor or 0))
    target_limit = max(1, int(limit_per_channel or TG_SEARCH_MATCH_LIMIT_PER_CHANNEL))
    fetch_limit = max(1, int(page_size or TG_SEARCH_PAGE_LIMIT))
    page_budget = max(1, int(max_pages or TG_SEARCH_MAX_PAGES))
    candidate_limit = max(target_limit, min(fetch_limit * page_budget, target_limit * 3))

    for _ in range(page_budget):
        check_resource_search_cancelled(search_id)
        page = fetch_telegram_channel_posts_page(
            cfg,
            normalized_source,
            limit=fetch_limit,
            before=before,
            query=keyword,
            allow_empty=True,
            timeout_seconds=request_timeout_seconds,
            retry_attempts=retry_attempts,
        )
        pages_scanned += 1
        page_matches: List[Dict[str, Any]] = []
        page_posts = page.get("posts", []) if isinstance(page.get("posts"), list) else []
        page_posts.sort(key=get_resource_item_sort_key, reverse=True)
        for post in page_posts:
            post_cursor = parse_int(get_resource_item_post_cursor(post), default=0)
            if post_cursor > latest_scanned_cursor:
                latest_scanned_cursor = post_cursor
            published_at = resolve_resource_item_published_at(post)
            published_ts = parse_resource_datetime_to_timestamp(published_at)
            if published_ts > latest_scanned_published_ts and published_at:
                latest_scanned_published_ts = published_ts
                latest_scanned_published_at = published_at

            if normalized_stop_cursor > 0 and post_cursor > 0 and post_cursor <= normalized_stop_cursor:
                incremental_stop_hit = True
                break
            check_resource_search_cancelled(search_id)
            match_info = build_resource_search_match_info(post, keyword)
            if not match_info.get("matched"):
                continue
            if not resource_item_matches_provider_filter(post, provider_filter):
                continue
            identity = build_resource_item_identity_by_mode(post, identity_mode=normalized_identity_mode)
            if identity in seen_keys:
                continue
            seen_keys.add(identity)
            page_matches.append({**post, "search_match": match_info})

        remaining_candidates = max(0, candidate_limit - len(items))
        if page_matches and remaining_candidates > 0:
            items.extend(page_matches[:remaining_candidates])

        if incremental_stop_hit:
            next_before = ""
            has_more = False
            break

        page_before = str(page.get("next_before", "") or "").strip()
        more_in_current_page = len(page_matches) > remaining_candidates if remaining_candidates > 0 else bool(page_matches)
        has_more = bool((more_in_current_page or page.get("has_more")) and (page_before or items))
        if items and has_more:
            next_before = get_resource_item_post_cursor(items[-1]) or page_before
        elif not has_more:
            next_before = ""

        best_rank = min(
            (
                parse_int(item.get("search_match", {}).get("rank", 99), default=99)
                for item in items
                if isinstance(item.get("search_match"), dict)
            ),
            default=99,
        )
        if len(items) >= target_limit and best_rank <= 1:
            break
        if len(items) >= candidate_limit:
            break
        before = page_before
        if not before or not page.get("has_more"):
            break

    items = sort_resource_search_items(items, keyword)
    return {
        "channel_id": channel_id,
        "items": items[:target_limit],
        "pages_scanned": pages_scanned,
        "next_before": next_before,
        "has_more": bool(next_before and has_more),
        "latest_scanned_cursor": latest_scanned_cursor,
        "latest_scanned_published_at": latest_scanned_published_at,
        "incremental_stop_hit": incremental_stop_hit,
    }


async def search_resource_sources(
    keyword: str,
    identity_mode: str = "message",
    incremental_since_cursor_by_channel: Optional[Dict[str, int]] = None,
    provider_filter: str = "all",
    search_id: str = "",
    limit_per_channel: Optional[int] = None,
    max_pages: Optional[int] = None,
    page_size: Optional[int] = None,
    total_limit: Optional[int] = None,
) -> Dict[str, Any]:
    query = str(keyword or "").strip()
    normalized_identity_mode = normalize_resource_identity_mode(identity_mode, fallback="message")
    normalized_provider_filter = normalize_resource_provider_filter(provider_filter)
    channel_match_limit = max(
        1,
        int(limit_per_channel if limit_per_channel is not None else TG_SEARCH_MATCH_LIMIT_PER_CHANNEL),
    )
    channel_max_pages = max(
        1,
        int(max_pages if max_pages is not None else TG_SEARCH_MAX_PAGES),
    )
    channel_page_size = max(
        1,
        int(page_size if page_size is not None else TG_SEARCH_PAGE_LIMIT),
    )
    global_total_limit = (
        int(total_limit)
        if total_limit is not None
        else int(TG_SEARCH_TOTAL_LIMIT or 60)
    )
    normalized_incremental_cursors: Dict[str, int] = {}
    if isinstance(incremental_since_cursor_by_channel, dict):
        for raw_channel_id, raw_cursor in incremental_since_cursor_by_channel.items():
            channel_id = normalize_telegram_channel_id_from_input(raw_channel_id)
            if not channel_id:
                continue
            normalized_incremental_cursors[channel_id] = max(0, int(raw_cursor or 0))
    cfg = get_config()
    sources = [
        source
        for source in (normalize_resource_source(raw_source or {}) for raw_source in cfg.get("resource_sources", []))
        if is_resource_source_search_enabled(source)
    ]
    tg_channel_threads = get_tg_channel_threads(cfg)
    if not query or not sources:
        return {
            "items": [],
            "sections": [],
            "errors": [],
            "searched_sources": len(sources),
            "matched_channels": 0,
            "pages_scanned": 0,
            "thread_limit": tg_channel_threads,
            "provider_filter": normalized_provider_filter,
            "incremental_stop_channels": 0,
            "channel_watermarks": {},
            "channel_stats": [],
            "limit_per_channel": channel_match_limit,
            "max_pages": channel_max_pages,
            "page_size": channel_page_size,
            "total_limit": global_total_limit,
        }

    semaphore = asyncio.Semaphore(tg_channel_threads)

    async def search_one_source(source: Dict[str, Any]) -> Dict[str, Any]:
        check_resource_search_cancelled(search_id)
        channel_id = normalize_telegram_channel_id_from_input(source.get("channel_id", ""))
        stop_cursor = max(0, int(normalized_incremental_cursors.get(channel_id, 0) or 0))
        started_at = time.perf_counter()
        try:
            async with semaphore:
                check_resource_search_cancelled(search_id)
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        search_telegram_channel_resource_items,
                        cfg,
                        source,
                        query,
                        channel_match_limit,
                        channel_max_pages,
                        channel_page_size,
                        "",
                        normalized_identity_mode,
                        stop_cursor,
                        TG_SEARCH_REQUEST_TIMEOUT_SECONDS,
                        TG_SEARCH_RETRY_ATTEMPTS,
                        normalized_provider_filter,
                        search_id,
                    ),
                    timeout=TG_SEARCH_CHANNEL_TIMEOUT_SECONDS,
                )
                check_resource_search_cancelled(search_id)
                if isinstance(result, dict):
                    result["elapsed_seconds"] = max(0.0, time.perf_counter() - started_at)
                return result
        except asyncio.TimeoutError as exc:
            channel_id = normalize_telegram_channel_id_from_input(source.get("channel_id", ""))
            elapsed_seconds = max(0.0, time.perf_counter() - started_at)
            raise RuntimeError(f"频道搜索超时（{channel_id}，{elapsed_seconds:.1f}秒）") from exc
        except Exception as exc:
            elapsed_seconds = max(0.0, time.perf_counter() - started_at)
            raise RuntimeError(f"{exc}（{elapsed_seconds:.1f}秒）") from exc

    tasks = [search_one_source(source) for source in sources]
    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
    except ResourceSearchCancelled:
        raise

    items: List[Dict[str, Any]] = []
    sections: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    channel_stats: List[Dict[str, Any]] = []
    matched_channels = 0
    pages_scanned = 0
    incremental_stop_channels = 0
    channel_watermarks: Dict[str, Dict[str, Any]] = {}

    for source, result in zip(sources, results):
        check_resource_search_cancelled(search_id)
        channel_id = normalize_telegram_channel_id_from_input(source.get("channel_id", ""))
        source_name = str(source.get("name", "") or channel_id).strip()
        if isinstance(result, Exception):
            channel_stats.append(
                {
                    "channel_id": channel_id,
                    "name": source_name,
                    "matched": False,
                    "item_count": 0,
                    "pages_scanned": 0,
                    "incremental_stop_hit": False,
                    "latest_scanned_cursor": 0,
                    "latest_scanned_published_at": "",
                    "elapsed_seconds": 0.0,
                    "error": str(result),
                }
            )
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
        latest_scanned_cursor = max(0, int(result.get("latest_scanned_cursor", 0) or 0)) if isinstance(result, dict) else 0
        latest_scanned_published_at = str(result.get("latest_scanned_published_at", "") or "").strip() if isinstance(result, dict) else ""
        elapsed_seconds = max(0.0, float(result.get("elapsed_seconds", 0.0) or 0.0)) if isinstance(result, dict) else 0.0
        channel_stats.append(
            {
                "channel_id": channel_id,
                "name": source_name,
                "matched": bool(channel_items),
                "item_count": len(channel_items),
                "pages_scanned": int(result.get("pages_scanned", 0) or 0) if isinstance(result, dict) else 0,
                "incremental_stop_hit": bool(result.get("incremental_stop_hit", False)) if isinstance(result, dict) else False,
                "latest_scanned_cursor": latest_scanned_cursor,
                "latest_scanned_published_at": latest_scanned_published_at,
                "elapsed_seconds": elapsed_seconds,
                "error": "",
            }
        )
        if latest_scanned_cursor > 0 or latest_scanned_published_at:
            channel_watermarks[channel_id] = {
                "channel_id": channel_id,
                "last_post_cursor": latest_scanned_cursor,
                "last_published_at": latest_scanned_published_at,
            }
        if bool(result.get("incremental_stop_hit", False)) if isinstance(result, dict) else False:
            incremental_stop_channels += 1
        if channel_items:
            matched_channels += 1
            items.extend(channel_items)
            sections.append(
                {
                    "name": source_name,
                    "channel_id": channel_id,
                    "url": build_telegram_channel_url(channel_id),
                    "usage": source.get("usage", RESOURCE_SOURCE_USAGE_SYNC_SEARCH),
                    "enabled": True,
                    "sync_enabled": bool(source.get("sync_enabled", False)),
                    "search_enabled": True,
                    "items": channel_items,
                    "item_count": len(channel_items),
                    "next_before": str(result.get("next_before", "") or "").strip(),
                    "has_more": bool(result.get("has_more")),
                    "pages_scanned": int(result.get("pages_scanned", 0) or 0),
                }
            )

    deduped_items = dedupe_resource_item_dicts(items, identity_mode=normalized_identity_mode)
    deduped_items = sort_resource_search_items(deduped_items, query)
    returned_items = deduped_items
    if global_total_limit > 0:
        returned_items = deduped_items[: max(1, global_total_limit)]
    return {
        "items": returned_items,
        "sections": sections,
        "errors": errors,
        "searched_sources": len(sources),
        "matched_channels": matched_channels,
        "pages_scanned": pages_scanned,
        "thread_limit": tg_channel_threads,
        "provider_filter": normalized_provider_filter,
        "incremental_stop_channels": incremental_stop_channels,
        "channel_watermarks": channel_watermarks,
        "channel_stats": channel_stats,
        "limit_per_channel": channel_match_limit,
        "max_pages": channel_max_pages,
        "page_size": channel_page_size,
        "total_limit": global_total_limit,
    }


async def search_pansou_resource_sources(
    keyword: str,
    provider_filter: str = "all",
    *,
    include_magnet_for_115: bool = False,
    search_id: str = "",
    total_limit: Optional[int] = None,
) -> Dict[str, Any]:
    query = str(keyword or "").strip()
    normalized_provider_filter = normalize_resource_provider_filter(provider_filter)
    resolved_total_limit = (
        int(total_limit)
        if total_limit is not None
        else int(PANSOU_SEARCH_TOTAL_LIMIT or 80)
    )
    cfg = get_config()
    enabled = bool(cfg.get("pansou_enabled", False))
    base_url = str(cfg.get("pansou_base_url", "") or "").strip()
    if not query:
        return {
            "items": [],
            "sections": [],
            "errors": [],
            "searched_sources": 0,
            "matched_channels": 0,
            "pages_scanned": 0,
            "thread_limit": 1,
            "provider_filter": normalized_provider_filter,
            "pansou_enabled": enabled,
            "pansou_items": 0,
            "pansou_elapsed_ms": 0,
            "pansou_total_limit": resolved_total_limit,
        }
    if not enabled:
        return {
            "items": [],
            "sections": [],
            "errors": [{"channel_id": "pansou", "name": "盘搜", "message": "盘搜未启用，请先在参数配置中开启"}],
            "searched_sources": 0,
            "matched_channels": 0,
            "pages_scanned": 0,
            "thread_limit": 1,
            "provider_filter": normalized_provider_filter,
            "pansou_enabled": False,
            "pansou_items": 0,
            "pansou_elapsed_ms": 0,
            "pansou_total_limit": resolved_total_limit,
        }
    if not base_url:
        return {
            "items": [],
            "sections": [],
            "errors": [{"channel_id": "pansou", "name": "盘搜", "message": "请先在参数配置中填写 PanSou 地址"}],
            "searched_sources": 0,
            "matched_channels": 0,
            "pages_scanned": 0,
            "thread_limit": 1,
            "provider_filter": normalized_provider_filter,
            "pansou_enabled": True,
            "pansou_items": 0,
            "pansou_elapsed_ms": 0,
            "pansou_total_limit": resolved_total_limit,
        }

    check_resource_search_cancelled(search_id)
    try:
        result = await asyncio.to_thread(
            request_pansou_search,
            cfg,
            query,
            normalized_provider_filter,
            include_magnet_for_115=include_magnet_for_115,
            limit=resolved_total_limit,
        )
        check_resource_search_cancelled(search_id)
    except Exception as exc:
        if isinstance(exc, ResourceSearchCancelled):
            raise
        return {
            "items": [],
            "sections": [],
            "errors": [{"channel_id": "pansou", "name": "盘搜", "message": str(exc)}],
            "searched_sources": 1,
            "matched_channels": 0,
            "pages_scanned": 0,
            "thread_limit": 1,
            "provider_filter": normalized_provider_filter,
            "pansou_enabled": True,
            "pansou_items": 0,
            "pansou_elapsed_ms": 0,
            "pansou_total_limit": resolved_total_limit,
        }

    items = filter_resource_items_by_provider(
        result.get("items", []) if isinstance(result, dict) else [],
        normalized_provider_filter,
    )
    if normalized_provider_filter == "115" and not include_magnet_for_115:
        items = [
            item
            for item in items
            if resolve_resource_link_type(item.get("link_type", ""), item.get("link_url", "")) == "115share"
        ]
    items = dedupe_resource_item_dicts(items, identity_mode="link")
    items.sort(key=get_resource_item_sort_key, reverse=True)
    section = {
        "name": "盘搜结果",
        "channel_id": "pansou",
        "section_type": "pansou",
        "url": str(cfg.get("pansou_base_url", "") or "").strip(),
        "enabled": True,
        "last_sync_at": time.time(),
        "last_error": "",
        "item_count": len(items),
        "items": items if resolved_total_limit <= 0 else items[: max(1, resolved_total_limit)],
        "next_before": "",
        "has_more": False,
        "channel_profile": {
            "primary_link_type": normalized_provider_filter if normalized_provider_filter != "all" else "unknown",
            "dominant_link_types": [],
            "link_type_counts": {},
        },
        "latest_published_at": "",
        "primary_link_type": normalized_provider_filter if normalized_provider_filter != "all" else "unknown",
        "dominant_link_types": [],
        "link_type_counts": {},
    }
    sections = [section] if items else []
    return {
        "items": items,
        "sections": sections,
        "errors": [],
        "searched_sources": 1,
        "matched_channels": 1 if items else 0,
        "pages_scanned": 1,
        "thread_limit": 1,
        "provider_filter": normalized_provider_filter,
        "pansou_enabled": True,
        "pansou_items": len(items),
        "pansou_elapsed_ms": max(0, int(result.get("elapsed_ms", 0) or 0)) if isinstance(result, dict) else 0,
        "pansou_total_limit": resolved_total_limit,
    }








def resolve_task_root(task: Dict[str, Any]) -> str:
    root_name = basename(task.get("scan_path", ""))
    target_path = normalize_relative_path(task.get("target_path", ""))
    if not target_path:
        return root_name
    target_parts = [p for p in target_path.split("/") if p]
    if root_name and target_parts and target_parts[-1] == root_name:
        return target_path
    return join_relative_path(target_path, root_name)


def match_monitor_task_for_savepath(cfg: Dict[str, Any], savepath: str, provider: str = "115") -> Dict[str, str]:
    savepath_rel = normalize_relative_path(savepath)
    mount_prefix = get_mount_prefix(cfg, provider)
    if not mount_prefix:
        return {
            "task_name": "",
            "scan_path": "",
            "full_path": "",
        }
    full_path = join_remote_path(mount_prefix, savepath_rel)
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


def restore_runtime_logs_from_files() -> None:
    global subscription_log_seq, subscription_log_task_total

    def build_subscription_restore_entry(line: str, seq: int) -> Dict[str, Any]:
        raw_text = re.sub(r"^\d{2}-\d{2} \d{2}:\d{2}:\d{2}\s+", "", line, count=1).strip()
        display_text = _build_subscription_log_display_text(raw_text, {})
        full_text = str(line or "").strip() or raw_text or display_text
        return {
            "seq": seq,
            "text": full_text,
            "display_text": display_text,
            "raw_text": raw_text,
            "level": infer_log_level_from_text(line),
            "signature": hashlib.sha1(line.encode("utf-8")).hexdigest()[:12],
        }

    main_lines = read_log_tail(MAIN_LOG_PATH, limit=UI_STATUS_LOG_MEMORY_LIMIT)
    if main_lines:
        task_status["logs"] = [
            {"text": line, "level": infer_log_level_from_text(line)}
            for line in main_lines
        ]

    monitor_lines = read_log_tail(MONITOR_LOG_PATH, limit=UI_STATUS_LOG_MEMORY_LIMIT)
    if monitor_lines:
        monitor_status["logs"] = [
            {"text": line, "level": infer_log_level_from_text(line)}
            for line in monitor_lines
        ]
    monitor_segments = build_monitor_log_segments_from_entries(_read_monitor_log_entries_from_files())
    if monitor_segments:
        monitor_status["log_segments"] = monitor_segments[-MONITOR_UI_TASK_LOG_MEMORY_LIMIT:]
        monitor_status["log_segment_total"] = sum(
            1 for segment in monitor_segments if str(segment.get("kind", "") or "") == "task"
        )

    subscription_lines = read_log_lines(SUBSCRIPTION_LOG_PATH)
    if subscription_lines:
        subscription_log_seq = len(subscription_lines)
        subscription_log_task_total = sum(1 for line in subscription_lines if "订阅开始" in str(line or ""))
        tail_start_seq = max(0, len(subscription_lines) - UI_STATUS_LOG_MEMORY_LIMIT)
        subscription_status["logs"] = [
            build_subscription_restore_entry(line, tail_start_seq + index + 1)
            for index, line in enumerate(subscription_lines[tail_start_seq:])
        ]


def validate_tree_runtime_config(cfg: Dict[str, Any], use_local: bool) -> Optional[str]:
    if use_local:
        return None
    if not str(cfg.get("cookie_115", "")).strip():
        return "请先在参数配置中填写 115 Cookie"
    if not str(get_mount_prefix(cfg, "115")).strip():
        return "请先在参数配置中填写 115 网盘路径前缀"
    trees = [
        t
        for t in cfg.get("trees", [])
        if str((t or {}).get("path", "")).strip()
    ]
    if not trees:
        return "未配置任何有效的目录树文件路径"
    strm_play_error = validate_strm_play_runtime_config(cfg)
    if strm_play_error:
        return strm_play_error
    return None


def validate_monitor_runtime_config(cfg: Dict[str, Any], task: Dict[str, Any]) -> Optional[str]:
    if not str(cfg.get("cookie_115", "")).strip():
        return "请先在参数配置中填写 115 Cookie"
    mount_prefix_115 = get_mount_prefix(cfg, "115")
    if not mount_prefix_115:
        return "请先在参数配置中填写 115 网盘路径前缀"
    if not str(task.get("scan_path", "")).strip():
        return "扫描路径未填写"
    scan_path = normalize_remote_path(task.get("scan_path", ""))
    if scan_path != mount_prefix_115 and not scan_path.startswith(mount_prefix_115 + "/"):
        return f"扫描路径必须位于 115 前缀 {mount_prefix_115} 下"
    if not str(task.get("target_path", "")).strip():
        return "目标路径未填写"
    strm_play_error = validate_strm_play_runtime_config(cfg)
    if strm_play_error:
        return strm_play_error
    return None


def validate_strm_play_runtime_config(cfg: Dict[str, Any]) -> Optional[str]:
    if not str(cfg.get("cookie_115", "")).strip():
        return "STRM 代理模式已启用，但 115 Cookie 未填写"
    if not str(cfg.get("strm_proxy_base_url", "")).strip():
        return "STRM 代理模式已启用，但 STRM 对外访问地址未填写"
    return None


def validate_subscription_runtime_config(cfg: Dict[str, Any], task: Dict[str, Any]) -> Optional[str]:
    provider = normalize_subscription_provider(task.get("provider", "115"), fallback="115")
    p = _get_provider_or_none(provider)
    if not p:
        return "订阅网盘类型不支持"
    enabled_map = cfg.get("provider_enabled", {}) if isinstance(cfg.get("provider_enabled", {}), dict) else {}
    if not bool(enabled_map.get(provider, provider in ("115", "quark"))):
        return f"{p.label} 未启用，请先在参数配置中启用该网盘"
    if not bool(getattr(p, "supports_subscription", False)):
        return f"{p.label} 暂不支持订阅"
    if not p.is_configured(cfg):
        return f"请先在参数配置中填写 {p.label} 认证信息"
    if not str(task.get("name", "")).strip():
        return "任务名未填写"
    if not str(task.get("title", "")).strip():
        return "订阅影视名称未填写"
    if not str(task.get("savepath", "")).strip():
        return "保存路径未填写"
    media_type = str(task.get("media_type", "movie") or "movie").strip().lower()
    if media_type not in ("movie", "tv"):
        return "订阅类型不支持"
    return None


def validate_tmdb_runtime_config(cfg: Optional[Dict[str, Any]] = None) -> Optional[str]:
    cfg = cfg or get_config()
    if not bool(cfg.get("tmdb_enabled", False)):
        return "TMDB 增强未启用，请先在参数配置中开启"
    if not str(cfg.get("tmdb_api_key", "")).strip():
        return "TMDB API Key 未填写"
    return None


task_status = {
    "running": False,
    "next_run": None,
    "logs": [{"text": "系统已就绪", "level": "info"}],
    "progress": {"step": "空闲", "percent": 0, "detail": "等待指令"},
}

monitor_status = {
    "running": False,
    "current_task": "",
    "queued": [],
    "logs": [{"text": "系统已就绪", "level": "info"}],
    "log_segment_total": 0,
    "log_segments": [
        {
            "id": "system-ready",
            "kind": "system",
            "title": "系统日志",
            "task_name": "",
            "trigger": "",
            "status": "",
            "started_at": "",
            "ended_at": "",
            "complete": False,
            "entries": [{"text": "系统已就绪", "level": "info"}],
            "entry_count": 1,
        }
    ],
    "summary": {"step": "空闲", "detail": "等待监控任务"},
}
monitor_control = {"cancel": False}
monitor_queue_lock = threading.Lock()
monitor_queue: List[Dict[str, Any]] = []
monitor_last_run: Dict[str, float] = {}
monitor_next_run: Dict[str, str] = {}
subscription_status = {
    "running": False,
    "current_task": "",
    "queued": [],
    "logs": [{"text": "系统已就绪", "level": "info"}],
    "summary": {"step": "空闲", "detail": "等待订阅任务"},
}
subscription_control = {"cancel": False}
subscription_queue_lock = threading.Lock()
subscription_queue: List[Dict[str, Any]] = []
subscription_last_run: Dict[str, float] = {}
subscription_next_run: Dict[str, str] = {}
subscription_log_context_var: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar(
    "subscription_log_context",
    default=None,
)
subscription_log_seq_lock = threading.Lock()
subscription_log_seq = 0
subscription_log_task_total = 0
sign115_status = {
    "state": "idle",
    "message": "尚未检查签到状态",
    "signed_today": None,
    "reward_leaf": 0,
    "balance_leaf": None,
    "last_checked_at": "",
    "last_sign_at": "",
    "last_trigger": "",
}
sign115_lock = threading.Lock()
sign115_runtime = {
    "running": False,
    "last_auto_date": "",
    "last_checked_ts": 0.0,
}
cookie_health_lock = threading.Lock()
cookie_health_status: Dict[str, Dict[str, Any]] = {
    "115": {
        "configured": False,
        "state": "missing",
        "message": "未配置 115 Cookie",
        "last_checked_at": "",
        "last_success_at": "",
        "trigger": "",
        "fail_count": 0,
    },
    "quark": {
        "configured": False,
        "state": "missing",
        "message": "未配置 Quark Cookie",
        "last_checked_at": "",
        "last_success_at": "",
        "trigger": "",
        "fail_count": 0,
    },
}
cookie_health_runtime: Dict[str, Dict[str, float]] = {
    "115": {"last_checked_ts": 0.0, "last_success_ts": 0.0},
    "quark": {"last_checked_ts": 0.0, "last_success_ts": 0.0},
}
tmdb_cache_entries: Dict[str, Dict[str, Any]] = {}
ui_event_subscribers: Set[asyncio.Queue[str]] = set()
# SSE incremental broadcast state
_last_broadcast_hashes: Dict[str, str] = {}
_last_full_broadcast_ts: float = 0.0
UI_FULL_BROADCAST_INTERVAL_SECONDS = 30.0
ui_event_loop: Optional[asyncio.AbstractEventLoop] = None
ui_push_pending = False
ui_push_task: Optional[asyncio.Task] = None
resource_job_lock = threading.Lock()
resource_job_running: Set[int] = set()
resource_refresh_pending: Set[int] = set()
resource_job_cancel_requested: Set[int] = set()
resource_channel_last_sync: Dict[str, float] = {}
resource_channel_last_error: Dict[str, str] = {}
resource_channel_syncing: Set[str] = set()
resource_channel_profiles: Dict[str, Dict[str, Any]] = {}
resource_channel_sync_status_lock = threading.Lock()
resource_channel_sync_status: Dict[str, Any] = {
    "submitted": False,
    "running": False,
    "cancel_requested": False,
    "cancelled": False,
    "started_at": "",
    "started_ts": 0.0,
    "finished_at": "",
    "finished_ts": 0.0,
    "duration_ms": 0,
    "last_updated_at": "",
    "last_result": {},
    "last_error": "",
}
resource_channel_sync_control_lock = threading.Lock()
resource_channel_sync_control = {"cancel": False}
RESOURCE_JOB_RECOVERY_INTERVAL_SECONDS = max(
    5,
    min(300, int(os.environ.get("RESOURCE_JOB_RECOVERY_INTERVAL_SECONDS", 20) or 20)),
)
resource_job_recovery_lock = threading.Lock()
resource_job_recovery_last_ts = 0.0
resource_state_snapshot_lock = threading.Lock()
resource_state_snapshot_epoch = 0
resource_jobs_state_snapshot_cache: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
resource_compact_state_snapshot_cache: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
resource_jobs_signal_lock = threading.Lock()
resource_jobs_signal_state: Dict[str, Any] = {
    "revision": 0,
    "updated_at": "",
    "reason": "",
    "latest_job": {},
}


def invalidate_resource_state_snapshot(reason: str = "") -> None:
    global resource_state_snapshot_epoch
    with resource_state_snapshot_lock:
        resource_state_snapshot_epoch += 1
        resource_jobs_state_snapshot_cache.clear()
        resource_compact_state_snapshot_cache.clear()


def touch_resource_jobs_state_signal(reason: str = "", latest_job: Optional[Dict[str, Any]] = None) -> None:
    with resource_jobs_signal_lock:
        resource_jobs_signal_state["revision"] = int(resource_jobs_signal_state.get("revision", 0) or 0) + 1
        resource_jobs_signal_state["updated_at"] = now_text()
        resource_jobs_signal_state["reason"] = str(reason or "").strip()[:120]
        resource_jobs_signal_state["latest_job"] = latest_job if isinstance(latest_job, dict) else {}
    schedule_ui_state_push(0)


def build_resource_jobs_signal_payload() -> Dict[str, Any]:
    with resource_jobs_signal_lock:
        return {
            "revision": int(resource_jobs_signal_state.get("revision", 0) or 0),
            "updated_at": str(resource_jobs_signal_state.get("updated_at", "") or ""),
            "reason": str(resource_jobs_signal_state.get("reason", "") or ""),
            "latest_job": dict(resource_jobs_signal_state.get("latest_job") or {}),
        }


def _get_resource_state_snapshot(
    cache: Dict[Tuple[Any, ...], Dict[str, Any]],
    key: Tuple[Any, ...],
    ttl_seconds: float,
) -> Optional[Dict[str, Any]]:
    if ttl_seconds <= 0:
        return None
    now_ts = time.monotonic()
    with resource_state_snapshot_lock:
        entry = cache.get(key)
        if not entry:
            return None
        if int(entry.get("epoch", -1) or -1) != resource_state_snapshot_epoch:
            cache.pop(key, None)
            return None
        if float(entry.get("expires_at", 0.0) or 0.0) <= now_ts:
            cache.pop(key, None)
            return None
        payload = entry.get("payload")
    return clone_jsonable(payload) if isinstance(payload, dict) else None


def _set_resource_state_snapshot(
    cache: Dict[Tuple[Any, ...], Dict[str, Any]],
    key: Tuple[Any, ...],
    payload: Dict[str, Any],
    ttl_seconds: float,
) -> None:
    if ttl_seconds <= 0:
        return
    now_ts = time.monotonic()
    with resource_state_snapshot_lock:
        _prune_resource_state_snapshot_cache_locked(cache, now_ts)
        cache[key] = {
            "epoch": resource_state_snapshot_epoch,
            "expires_at": now_ts + ttl_seconds,
            "payload": clone_jsonable(payload),
        }
        _prune_resource_state_snapshot_cache_locked(cache, now_ts)


def _prune_resource_state_snapshot_cache_locked(
    cache: Dict[Tuple[Any, ...], Dict[str, Any]],
    now_ts: Optional[float] = None,
) -> int:
    now_value = time.monotonic() if now_ts is None else float(now_ts or 0.0)
    removed = 0
    for key, entry in list(cache.items()):
        if int(entry.get("epoch", -1) or -1) != resource_state_snapshot_epoch:
            cache.pop(key, None)
            removed += 1
            continue
        if float(entry.get("expires_at", 0.0) or 0.0) <= now_value:
            cache.pop(key, None)
            removed += 1
    max_entries = max(1, int(RESOURCE_STATE_SNAPSHOT_CACHE_MAX_ENTRIES or 128))
    overflow = len(cache) - max_entries
    if overflow > 0:
        ordered = sorted(
            cache.items(),
            key=lambda item: float((item[1] or {}).get("expires_at", 0.0) or 0.0),
        )
        for key, _entry in ordered[:overflow]:
            cache.pop(key, None)
            removed += 1
    return removed


def prune_resource_state_snapshot_caches() -> Dict[str, int]:
    with resource_state_snapshot_lock:
        return {
            "jobs": _prune_resource_state_snapshot_cache_locked(resource_jobs_state_snapshot_cache),
            "compact": _prune_resource_state_snapshot_cache_locked(resource_compact_state_snapshot_cache),
        }


def _active_resource_channel_ids_from_config(cfg: Optional[Dict[str, Any]] = None) -> Set[str]:
    active_cfg = cfg or get_config()
    sources = active_cfg.get("resource_sources", [])
    if not isinstance(sources, list):
        return set()
    return {
        channel_id
        for channel_id in (
            normalize_telegram_channel_id_from_input((source or {}).get("channel_id", ""))
            for source in sources
            if isinstance(source, dict)
        )
        if channel_id
    }


def prune_resource_channel_runtime_state(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, int]:
    active_channel_ids = _active_resource_channel_ids_from_config(cfg)
    detail: Dict[str, int] = {}
    for name, mapping in (
        ("last_sync", resource_channel_last_sync),
        ("last_error", resource_channel_last_error),
        ("profiles", resource_channel_profiles),
    ):
        removed = 0
        for channel_id in list(mapping.keys()):
            if str(channel_id or "").strip() in active_channel_ids:
                continue
            mapping.pop(channel_id, None)
            removed += 1
        detail[name] = removed
    return detail


def prune_core_runtime_memory_caches(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "resource_search_cancelled": prune_resource_search_cancelled(),
        "resource_state_snapshots": prune_resource_state_snapshot_caches(),
        "resource_channel_runtime": prune_resource_channel_runtime_state(cfg),
    }


def normalize_cookie_health_provider(value: Any) -> str:
    token = str(value or "").strip().lower()
    if token in {"115", "cookie_115"}:
        return "115"
    if token in {"quark", "cookie_quark"}:
        return "quark"
    try:
        p = _get_provider_or_none(token)
        if p:
            return p.name
    except Exception:
        pass
    return ""


def is_cookie_health_share_trigger(trigger: Any) -> bool:
    token = str(trigger or "").strip().lower()
    return any(token.startswith(prefix) for prefix in COOKIE_HEALTH_SHARE_TRIGGER_PREFIXES)


def _cookie_health_provider_label(provider: str) -> str:
    provider_key = normalize_cookie_health_provider(provider)
    try:
        p = _get_provider_or_none(provider_key)
        if p:
            return str(p.label or provider_key)
    except Exception:
        pass
    return "Quark" if provider_key == "quark" else ("115" if provider_key == "115" else provider_key)


def _cookie_health_auth_label(provider: str) -> str:
    provider_key = normalize_cookie_health_provider(provider)
    try:
        p = _get_provider_or_none(provider_key)
        if p and hasattr(p, "auth_label"):
            return str(p.auth_label() or "认证信息")
    except Exception:
        pass
    return "Cookie"


def _cookie_health_is_configured(cfg: Dict[str, Any], provider: str) -> bool:
    provider_key = normalize_cookie_health_provider(provider)
    try:
        p = _get_provider_or_none(provider_key)
        if p and hasattr(p, "is_configured"):
            return bool(p.is_configured(cfg or {}))
    except Exception:
        return False
    if provider_key == "quark":
        return bool(str((cfg or {}).get("cookie_quark", "") or "").strip())
    if provider_key == "115":
        return bool(str((cfg or {}).get("cookie_115", "") or "").strip())
    return False


def _cookie_health_cookie_value(cfg: Dict[str, Any], provider: str) -> str:
    provider_key = normalize_cookie_health_provider(provider)
    try:
        p = _get_provider_or_none(provider_key)
        if p and _cookie_health_is_configured(cfg, provider_key):
            return p.get_cookie(cfg or {})
    except Exception:
        raise
    if provider_key == "quark":
        return str((cfg or {}).get("cookie_quark", "") or "").strip()
    if provider_key == "115":
        return str((cfg or {}).get("cookie_115", "") or "").strip()
    return ""


def _cookie_health_missing_message(provider: str) -> str:
    return f"未配置 {_cookie_health_provider_label(provider)} {_cookie_health_auth_label(provider)}"


def _cookie_health_disabled_message(provider: str) -> str:
    return f"{_cookie_health_provider_label(provider)} 未启用"


def _cookie_health_unknown_message(provider: str) -> str:
    return f"已配置 {_cookie_health_provider_label(provider)} {_cookie_health_auth_label(provider)}，等待检测"


def _cookie_health_valid_message(provider: str) -> str:
    return f"{_cookie_health_provider_label(provider)} {_cookie_health_auth_label(provider)} 可用"


def _ensure_cookie_health_entry_locked(provider: str) -> Dict[str, Any]:
    provider_key = normalize_cookie_health_provider(provider)
    if not provider_key:
        return {}
    if provider_key not in cookie_health_status:
        cookie_health_status[provider_key] = {
            "configured": False,
            "state": "missing",
            "message": _cookie_health_missing_message(provider_key),
            "last_checked_at": "",
            "last_success_at": "",
            "trigger": "",
            "fail_count": 0,
        }
    if provider_key not in cookie_health_runtime:
        cookie_health_runtime[provider_key] = {"last_checked_ts": 0.0, "last_success_ts": 0.0}
    return cookie_health_status[provider_key]


def _set_cookie_health_entry_locked(provider: str, **fields: Any) -> bool:
    entry = _ensure_cookie_health_entry_locked(provider)
    if not entry:
        return False
    changed = False
    for key, value in fields.items():
        if entry.get(key) == value:
            continue
        entry[key] = value
        changed = True
    return changed


def _normalize_cookie_health_error_detail(error: Any) -> str:
    detail = str(error or "").strip()
    if not detail:
        return "Cookie 检测失败"
    return detail


def _classify_cookie_health_error(error: Any) -> Tuple[str, str]:
    detail = _normalize_cookie_health_error_detail(error)
    lowered = detail.lower()
    if isinstance(error, urllib.error.HTTPError):
        status_code = int(getattr(error, "code", 0) or 0)
        if status_code in (401, 403):
            return "invalid", f"Cookie 可能已失效（HTTP {status_code}）"
        if status_code in (408, 409, 425, 429, 500, 502, 503, 504):
            return "error", f"网络或服务异常（HTTP {status_code}）"
    if any(hint in lowered for hint in COOKIE_HEALTH_INVALID_MESSAGE_HINTS):
        return "invalid", detail
    if any(hint in lowered for hint in COOKIE_HEALTH_TRANSIENT_MESSAGE_HINTS):
        return "error", f"Cookie 检测遇到网络或 SSL 异常，不代表 Cookie 已失效：{detail}"
    return "error", detail


def sync_cookie_health_configured(cfg: Optional[Dict[str, Any]] = None, trigger: str = "sync") -> None:
    active_cfg = cfg or get_config()
    changed = False
    with cookie_health_lock:
        for provider in get_cookie_health_providers():
            entry = _ensure_cookie_health_entry_locked(provider)
            if not entry:
                continue
            enabled = is_cookie_health_provider_enabled(active_cfg, provider)
            if not enabled:
                changed = _set_cookie_health_entry_locked(
                    provider,
                    enabled=False,
                    configured=False,
                    state="disabled",
                    message=_cookie_health_disabled_message(provider),
                    trigger=str(trigger or "").strip(),
                    fail_count=0,
                ) or changed
                continue
            configured = _cookie_health_is_configured(active_cfg, provider)
            if not configured:
                changed = _set_cookie_health_entry_locked(
                    provider,
                    enabled=True,
                    configured=False,
                    state="missing",
                    message=_cookie_health_missing_message(provider),
                    trigger=str(trigger or "").strip(),
                    fail_count=0,
                ) or changed
                continue
            if not entry.get("configured", False):
                changed = _set_cookie_health_entry_locked(provider, enabled=True, configured=True) or changed
            state = str(entry.get("state", "") or "").strip().lower()
            if state in {"", "missing", "disabled"}:
                changed = _set_cookie_health_entry_locked(
                    provider,
                    enabled=True,
                    configured=True,
                    state="unknown",
                    message=_cookie_health_unknown_message(provider),
                    trigger=str(trigger or "").strip(),
                ) or changed
            elif not entry.get("configured", False):
                changed = _set_cookie_health_entry_locked(provider, enabled=True, configured=True) or changed
    if changed:
        schedule_ui_state_push(0)


def mark_cookie_health_checking(provider: str, trigger: str = "manual_check") -> None:
    provider_key = normalize_cookie_health_provider(provider)
    if not provider_key:
        return
    if is_cookie_health_share_trigger(trigger):
        return
    cfg = get_config()
    if not is_cookie_health_provider_enabled(cfg, provider_key):
        sync_cookie_health_configured(cfg, trigger=trigger)
        return
    configured = _cookie_health_is_configured(cfg, provider_key)
    changed = False
    with cookie_health_lock:
        _ensure_cookie_health_entry_locked(provider_key)
        if not configured:
            changed = _set_cookie_health_entry_locked(
                provider_key,
                configured=False,
                state="missing",
                message=_cookie_health_missing_message(provider_key),
                trigger=str(trigger or "").strip(),
                fail_count=0,
            ) or changed
        else:
            changed = _set_cookie_health_entry_locked(
                provider_key,
                configured=True,
                state="checking",
                message=f"正在检测 {_cookie_health_provider_label(provider_key)} Cookie...",
                trigger=str(trigger or "").strip(),
            ) or changed
    if changed:
        schedule_ui_state_push(0)


def mark_cookie_health_success(
    provider: str,
    trigger: str = "runtime",
    force: bool = False,
    message: str = "",
) -> None:
    provider_key = normalize_cookie_health_provider(provider)
    if not provider_key:
        return
    if is_cookie_health_share_trigger(trigger):
        return
    cfg = get_config()
    if not is_cookie_health_provider_enabled(cfg, provider_key):
        sync_cookie_health_configured(cfg, trigger=trigger)
        return
    configured = _cookie_health_is_configured(cfg, provider_key)
    now_ts = time.time()
    now_iso = now_text()
    changed = False
    with cookie_health_lock:
        entry = _ensure_cookie_health_entry_locked(provider_key)
        runtime_payload = cookie_health_runtime.get(provider_key, {"last_checked_ts": 0.0, "last_success_ts": 0.0})
        last_checked_ts = float(runtime_payload.get("last_checked_ts", 0.0) or 0.0)
        if not configured:
            changed = _set_cookie_health_entry_locked(
                provider_key,
                configured=False,
                state="missing",
                message=_cookie_health_missing_message(provider_key),
                trigger=str(trigger or "").strip(),
                fail_count=0,
            ) or changed
            runtime_payload["last_checked_ts"] = now_ts
            cookie_health_runtime[provider_key] = runtime_payload
        else:
            should_skip = (
                (not force)
                and str(trigger or "").strip().lower().startswith("runtime")
                and str(entry.get("state", "")).strip().lower() == "valid"
                and (now_ts - last_checked_ts) < COOKIE_HEALTH_SUCCESS_UPDATE_INTERVAL_SECONDS
            )
            if should_skip:
                return
            changed = _set_cookie_health_entry_locked(
                provider_key,
                configured=True,
                state="valid",
                message=str(message or "").strip() or _cookie_health_valid_message(provider_key),
                last_checked_at=now_iso,
                last_success_at=now_iso,
                trigger=str(trigger or "").strip(),
                fail_count=0,
            ) or changed
            runtime_payload["last_checked_ts"] = now_ts
            runtime_payload["last_success_ts"] = now_ts
            cookie_health_runtime[provider_key] = runtime_payload
    if changed:
        schedule_ui_state_push(0)


def mark_cookie_health_failure(
    provider: str,
    error: Any,
    trigger: str = "runtime",
    force: bool = False,
) -> None:
    provider_key = normalize_cookie_health_provider(provider)
    if not provider_key:
        return
    if is_cookie_health_share_trigger(trigger):
        return
    cfg = get_config()
    if not is_cookie_health_provider_enabled(cfg, provider_key):
        sync_cookie_health_configured(cfg, trigger=trigger)
        return
    configured = _cookie_health_is_configured(cfg, provider_key)
    now_ts = time.time()
    now_iso = now_text()
    changed = False
    with cookie_health_lock:
        entry = _ensure_cookie_health_entry_locked(provider_key)
        runtime_payload = cookie_health_runtime.get(provider_key, {"last_checked_ts": 0.0, "last_success_ts": 0.0})
        if not configured:
            changed = _set_cookie_health_entry_locked(
                provider_key,
                configured=False,
                state="missing",
                message=_cookie_health_missing_message(provider_key),
                trigger=str(trigger or "").strip(),
                fail_count=0,
            ) or changed
            runtime_payload["last_checked_ts"] = now_ts
            cookie_health_runtime[provider_key] = runtime_payload
        else:
            state, detail = _classify_cookie_health_error(error)
            fail_count = max(0, int(entry.get("fail_count", 0) or 0)) + 1
            if (not force) and str(trigger or "").strip().lower().startswith("runtime"):
                last_checked_ts = float(runtime_payload.get("last_checked_ts", 0.0) or 0.0)
                if (
                    str(entry.get("state", "")).strip().lower() == state
                    and str(entry.get("message", "")).strip() == detail
                    and (now_ts - last_checked_ts) < COOKIE_HEALTH_MIN_REFRESH_INTERVAL_SECONDS
                ):
                    return
            changed = _set_cookie_health_entry_locked(
                provider_key,
                configured=True,
                state=state,
                message=detail,
                last_checked_at=now_iso,
                trigger=str(trigger or "").strip(),
                fail_count=fail_count,
            ) or changed
            runtime_payload["last_checked_ts"] = now_ts
            cookie_health_runtime[provider_key] = runtime_payload
    if changed:
        schedule_ui_state_push(0)


def build_cookie_health_payload(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    active_cfg = cfg or get_config()
    sync_cookie_health_configured(active_cfg, trigger="payload")
    with cookie_health_lock:
        payload: Dict[str, Any] = {}
        for provider in get_cookie_health_providers():
            entry = _ensure_cookie_health_entry_locked(provider)
            payload[provider] = {
                "enabled": is_cookie_health_provider_enabled(active_cfg, provider),
                "configured": bool(entry.get("configured", False)),
                "state": str(entry.get("state", "unknown") or "unknown"),
                "message": str(entry.get("message", "") or ""),
                "last_checked_at": str(entry.get("last_checked_at", "") or ""),
                "last_success_at": str(entry.get("last_success_at", "") or ""),
                "trigger": str(entry.get("trigger", "") or ""),
                "fail_count": max(0, int(entry.get("fail_count", 0) or 0)),
            }
    return payload


def _probe_115_cookie(cookie: str) -> None:
    normalized_cookie = str(cookie or "").strip()
    if not normalized_cookie:
        raise RuntimeError("115 Cookie 未配置")
    throttle_115_api_requests()
    probes: List[Tuple[str, str, Dict[str, str]]] = [
        (
            "webapi",
            "https://webapi.115.com/files?aid=1&cid=0&o=user_ptime&asc=1&offset=0&show_dir=1&limit=1&type=0&format=json&star=0&suffix=&natsort=0&snap=0&record_open_time=1&fc_mix=0",
            {
                "Cookie": normalized_cookie,
                "Accept": "application/json, text/plain, */*",
                "Connection": "keep-alive",
                "xweb_xhr": "1",
                "Referer": "https://servicewechat.com/wx2c744c010a61b0fa/94/page-frame.html",
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36 "
                    "MicroMessenger/6.8.0(0x16080000) NetType/WIFI MiniProgramEnv/Mac "
                    "MacWechat/WMPF MacWechat/3.8.9(0x13080910) XWEB/1227"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        ),
        (
            "aps",
            "https://aps.115.com/natsort/files.php?aid=1&cid=0&offset=0&limit=1&show_dir=1&natsort=1&format=json",
            {
                "Cookie": normalized_cookie,
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://115.com/",
                "User-Agent": "Mozilla/5.0 115-media-hub",
            },
        ),
    ]
    failures: List[str] = []
    invalid_details: List[str] = []
    for probe_name, url, headers in probes:
        try:
            result = http_request_json(url, extra_headers=headers, timeout=20)
        except Exception as exc:
            failures.append(f"{probe_name}: {exc}")
            continue
        if bool((result or {}).get("state", False)):
            return
        detail = (
            str((result or {}).get("error", "")).strip()
            or str((result or {}).get("msg", "")).strip()
            or str((result or {}).get("message", "")).strip()
            or "115 Cookie 检测失败"
        )
        state, _ = _classify_cookie_health_error(detail)
        if state == "invalid":
            invalid_details.append(f"{probe_name}: {detail}")
        else:
            failures.append(f"{probe_name}: {detail}")
    if invalid_details:
        raise RuntimeError("；".join(invalid_details))
    if failures:
        raise RuntimeError("；".join(failures))
    raise RuntimeError("115 Cookie 检测失败")


def _probe_quark_cookie(cookie: str) -> None:
    normalized_cookie = str(cookie or "").strip()
    if not normalized_cookie:
        raise RuntimeError("Quark Cookie 未配置")
    headers = {
        "Cookie": normalized_cookie,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://pan.quark.cn/",
        "Origin": "https://pan.quark.cn",
        "User-Agent": "Mozilla/5.0 115-media-hub",
    }
    url = (
        "https://drive-pc.quark.cn/1/clouddrive/file/sort"
        "?pr=ucpro&fr=pc&pdir_fid=0&_page=1&_size=1&_fetch_total=1&_fetch_sub_dirs=1&_sort=file_type:asc,file_name:asc"
    )
    result = http_request_json(url, extra_headers=headers, timeout=20)
    code = parse_int((result or {}).get("code"), default=0)
    status = parse_int((result or {}).get("status"), default=0)
    success = any(
        (
            bool((result or {}).get("success", False)),
            bool((result or {}).get("state", False)),
            code == 0,
            status in (0, 200),
        )
    )
    if not success:
        detail = (
            str((result or {}).get("message", "")).strip()
            or str((result or {}).get("msg", "")).strip()
            or str((result or {}).get("error", "")).strip()
            or str((result or {}).get("error_msg", "")).strip()
            or "Quark Cookie 检测失败"
        )
        raise RuntimeError(detail)


def _normalize_cookie_health_providers(providers: Any = None) -> List[str]:
    raw_items = providers if isinstance(providers, list) else get_enabled_cookie_health_providers()
    if providers is None:
        raw_items = list(get_enabled_cookie_health_providers())
    normalized: List[str] = []
    for item in raw_items:
        provider = normalize_cookie_health_provider(item)
        if (not provider) or provider in normalized:
            continue
        normalized.append(provider)
    return normalized or list(get_enabled_cookie_health_providers())


async def refresh_cookie_health_status(
    providers: Any = None,
    trigger: str = "manual_check",
    force: bool = False,
) -> Dict[str, Any]:
    cfg = get_config()
    sync_cookie_health_configured(cfg, trigger=trigger or "refresh")
    provider_list = _normalize_cookie_health_providers(providers)
    now_ts = time.time()

    for provider in provider_list:
        if not is_cookie_health_provider_enabled(cfg, provider):
            sync_cookie_health_configured(cfg, trigger=trigger)
            continue
        if not _cookie_health_is_configured(cfg, provider):
            mark_cookie_health_failure(provider, _cookie_health_missing_message(provider), trigger=trigger, force=True)
            continue

        with cookie_health_lock:
            runtime_payload = cookie_health_runtime.get(provider, {"last_checked_ts": 0.0, "last_success_ts": 0.0})
            last_checked_ts = float(runtime_payload.get("last_checked_ts", 0.0) or 0.0)
        if (not force) and last_checked_ts > 0 and (now_ts - last_checked_ts) < COOKIE_HEALTH_MIN_REFRESH_INTERVAL_SECONDS:
            continue

        mark_cookie_health_checking(provider, trigger=trigger)
        try:
            cookie_value = _cookie_health_cookie_value(cfg, provider)
            if not cookie_value:
                raise RuntimeError(_cookie_health_missing_message(provider))
            p = _get_provider_or_none(provider)
            if p:
                ok = await asyncio.to_thread(p.probe_connectivity, cookie_value)
                if not ok:
                    raise RuntimeError(f"{p.label} 连接检测失败")
            elif provider == "quark":
                await asyncio.to_thread(_probe_quark_cookie, cookie_value)
            else:
                await asyncio.to_thread(_probe_115_cookie, cookie_value)
            mark_cookie_health_success(provider, trigger=trigger, force=True)
        except Exception as exc:
            mark_cookie_health_failure(provider, exc, trigger=trigger, force=True)

    return build_cookie_health_payload(cfg)


def clone_jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _append_status_log_entry(logs: List[Dict[str, Any]], entry: Dict[str, Any], limit: int = UI_STATUS_LOG_MEMORY_LIMIT) -> None:
    logs.append(entry)
    overflow = len(logs) - max(1, int(limit or 0))
    if overflow > 0:
        del logs[:overflow]


def _tail_jsonable_logs(logs: Any, limit: int = UI_STATUS_LOG_TAIL_LIMIT) -> List[Dict[str, Any]]:
    if not isinstance(logs, list):
        return []
    tail = logs[-max(0, int(limit or 0)) :] if limit else logs
    return clone_jsonable(tail)


def _serialize_monitor_log_entry(entry: Any) -> Dict[str, str]:
    payload = entry if isinstance(entry, dict) else {}
    text = str(payload.get("text", "") or "")
    level = str(payload.get("level", "info") or "info").strip().lower() or "info"
    return {"text": text, "level": level}


def _extract_monitor_log_timestamp(text: str) -> str:
    match = re.match(r"^(\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+", str(text or ""))
    return match.group(1) if match else ""


def _extract_monitor_task_divider_label(text: str) -> str:
    normalized = str(text or "").strip()
    match = re.search(r"【([^】]+)】", normalized)
    return str(match.group(1) or "").strip() if match else ""


def _parse_monitor_task_label(label: str) -> Dict[str, str]:
    parts = [part.strip() for part in str(label or "").split("|")]
    kind = parts[0] if parts else ""
    task_name = parts[1] if len(parts) >= 2 else ""
    extra = parts[2] if len(parts) >= 3 else ""
    return {"kind": kind, "task_name": task_name, "extra": extra}


def _new_monitor_log_segment(kind: str = "system") -> Dict[str, Any]:
    return {
        "id": "",
        "kind": kind,
        "title": "系统日志" if kind == "system" else "监控任务",
        "task_name": "",
        "trigger": "",
        "status": "",
        "started_at": "",
        "ended_at": "",
        "complete": False,
        "entries": [],
        "entry_count": 0,
    }


def _finalize_monitor_log_segment(segment: Dict[str, Any], index: int) -> Dict[str, Any]:
    entries = [
        _serialize_monitor_log_entry(entry)
        for entry in (segment.get("entries", []) if isinstance(segment, dict) else [])
    ]
    first_text = str(entries[0].get("text", "") if entries else "")
    segment_id = str(segment.get("id", "") or "").strip()
    if not segment_id:
        digest = hashlib.sha1(f"{index}:{first_text}".encode("utf-8")).hexdigest()[:12]
        segment_id = f"monitor-log-{digest}"
    task_name = str(segment.get("task_name", "") or "").strip()
    title = str(segment.get("title", "") or "").strip()
    if not title:
        title = task_name or "系统日志"
    return {
        "id": segment_id,
        "kind": str(segment.get("kind", "system") or "system"),
        "title": title,
        "task_name": task_name,
        "trigger": str(segment.get("trigger", "") or "").strip(),
        "status": str(segment.get("status", "") or "").strip(),
        "started_at": str(segment.get("started_at", "") or "").strip(),
        "ended_at": str(segment.get("ended_at", "") or "").strip(),
        "complete": bool(segment.get("complete", False)),
        "entries": entries,
        "entry_count": len(entries),
    }


def build_monitor_log_segments_from_entries(entries: Any) -> List[Dict[str, Any]]:
    if not isinstance(entries, list):
        return []

    segments: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None

    for raw_entry in entries:
        entry = _serialize_monitor_log_entry(raw_entry)
        text = entry.get("text", "")
        label = _extract_monitor_task_divider_label(text) if entry.get("level") == "task-divider" else ""
        label_info = _parse_monitor_task_label(label) if label else {}
        is_start = label_info.get("kind") == "任务开始"
        is_end = label_info.get("kind") == "任务结束"

        if is_start:
            if current and current.get("entries"):
                segments.append(current)
            current = _new_monitor_log_segment("task")
            current["task_name"] = label_info.get("task_name", "")
            current["trigger"] = label_info.get("extra", "")
            current["title"] = current["task_name"] or "监控任务"
            current["started_at"] = _extract_monitor_log_timestamp(text)
        elif current is None:
            current = _new_monitor_log_segment("system")
            current["started_at"] = _extract_monitor_log_timestamp(text)

        current.setdefault("entries", []).append(entry)

        if is_end:
            current["kind"] = "task"
            current["task_name"] = current.get("task_name") or label_info.get("task_name", "")
            current["status"] = label_info.get("extra", "")
            current["ended_at"] = _extract_monitor_log_timestamp(text)
            current["complete"] = True
            segments.append(current)
            current = None

    if current and current.get("entries"):
        segments.append(current)

    return [
        _finalize_monitor_log_segment(segment, index)
        for index, segment in enumerate(segments)
    ]


def _read_monitor_log_entries_from_files() -> List[Dict[str, str]]:
    lines: List[str] = []
    for index in range(LOG_ROTATE_BACKUPS, 0, -1):
        lines.extend(read_log_lines(f"{MONITOR_LOG_PATH}.{index}"))
    lines.extend(read_log_lines(MONITOR_LOG_PATH))
    return [
        {"text": line, "level": infer_log_level_from_text(line)}
        for line in lines
    ]


def _append_monitor_log_segment_entry(entry: Dict[str, str]) -> None:
    segments = monitor_status.setdefault("log_segments", [])
    if not isinstance(segments, list):
        segments = []
        monitor_status["log_segments"] = segments

    serialized_entry = _serialize_monitor_log_entry(entry)
    text = serialized_entry.get("text", "")
    label = (
        _extract_monitor_task_divider_label(text)
        if serialized_entry.get("level") == "task-divider"
        else ""
    )
    label_info = _parse_monitor_task_label(label) if label else {}
    is_start = label_info.get("kind") == "任务开始"
    is_end = label_info.get("kind") == "任务结束"

    if is_start:
        segment = _new_monitor_log_segment("task")
        segment["task_name"] = label_info.get("task_name", "")
        segment["trigger"] = label_info.get("extra", "")
        segment["title"] = segment["task_name"] or "监控任务"
        segment["started_at"] = _extract_monitor_log_timestamp(text)
        segments.append(segment)
        monitor_status["log_segment_total"] = max(
            0,
            int(monitor_status.get("log_segment_total", 0) or 0),
        ) + 1
    elif not segments or bool(segments[-1].get("complete")):
        segment = _new_monitor_log_segment("system")
        segment["started_at"] = _extract_monitor_log_timestamp(text)
        segments.append(segment)
    else:
        segment = segments[-1]

    segment.setdefault("entries", []).append(serialized_entry)

    if is_end:
        segment["kind"] = "task"
        segment["task_name"] = segment.get("task_name") or label_info.get("task_name", "")
        segment["status"] = label_info.get("extra", "")
        segment["ended_at"] = _extract_monitor_log_timestamp(text)
        segment["complete"] = True

    overflow = len(segments) - MONITOR_UI_TASK_LOG_MEMORY_LIMIT
    if overflow > 0:
        del segments[:overflow]
    for index, segment in enumerate(segments):
        segments[index] = _finalize_monitor_log_segment(segment, index)


def build_monitor_log_segment_page(
    *,
    offset: int = 0,
    limit: int = MONITOR_UI_RECENT_TASK_LOG_LIMIT,
    source: str = "memory",
) -> Dict[str, Any]:
    normalized_limit = max(1, min(20, int(limit or MONITOR_UI_RECENT_TASK_LOG_LIMIT)))
    normalized_offset = max(0, int(offset or 0))
    if source == "file":
        segments = build_monitor_log_segments_from_entries(_read_monitor_log_entries_from_files())
        task_segments = [segment for segment in segments if str(segment.get("kind", "") or "") == "task"]
        visible_segments = task_segments if task_segments else segments
        total = len(visible_segments)
        end = max(0, total - normalized_offset)
        start = max(0, end - normalized_limit)
        page_segments = visible_segments[start:end] if end > start else []
        has_more = start > 0
        next_offset = total - start
    else:
        raw_segments = monitor_status.get("log_segments", [])
        if not isinstance(raw_segments, list) or not raw_segments:
            raw_segments = build_monitor_log_segments_from_entries(monitor_status.get("logs", []))
        segments = [
            _finalize_monitor_log_segment(segment, index)
            for index, segment in enumerate(raw_segments if isinstance(raw_segments, list) else [])
        ]
        task_segments = [segment for segment in segments if str(segment.get("kind", "") or "") == "task"]
        visible_segments = task_segments if task_segments else segments
        memory_total = len(visible_segments)
        end = max(0, memory_total - normalized_offset)
        start = max(0, end - normalized_limit)
        page_segments = visible_segments[start:end] if end > start else []
        stored_task_total = max(
            int(monitor_status.get("log_segment_total", 0) or 0),
            len(task_segments),
        )
        total = stored_task_total if task_segments else memory_total
        has_more = (stored_task_total > normalized_offset + len(page_segments)) if task_segments else start > 0
        next_offset = normalized_offset + len(page_segments)
    return {
        "segments": clone_jsonable(page_segments),
        "total": total,
        "offset": normalized_offset,
        "limit": normalized_limit,
        "has_more": has_more,
        "next_offset": next_offset,
    }


def _serialize_subscription_ui_log(entry: Any) -> Dict[str, str]:
    payload = entry if isinstance(entry, dict) else {}
    seq = max(0, int(payload.get("seq", 0) or 0))
    full_text = str(payload.get("text") or payload.get("raw_text") or payload.get("display_text") or "").strip()
    level = str(payload.get("level", "info") or "info").strip().lower() or "info"
    signature = str(payload.get("signature", "") or "").strip()
    if not signature:
        signature = hashlib.sha1(f"{level}:{full_text}".encode("utf-8")).hexdigest()[:12]
    return {
        "seq": seq,
        "text": full_text,
        "display_text": str(payload.get("display_text") or "").strip(),
        "raw_text": str(payload.get("raw_text") or "").strip(),
        "level": level,
        "signature": signature,
    }


def _extract_subscription_candidate_episode_preview(text: str) -> str:
    values = re.findall(r"E\s*0*(\d{1,4})", str(text or ""), flags=re.IGNORECASE)
    if not values:
        return ""
    normalized: List[int] = []
    seen: Set[int] = set()
    for value in values:
        episode = int(value or "0")
        if episode <= 0 or episode in seen:
            continue
        seen.add(episode)
        normalized.append(episode)
    if not normalized:
        return ""
    if len(normalized) == 1:
        return f"E{normalized[0]}"
    if len(normalized) == 2:
        return f"E{normalized[0]}、E{normalized[1]}"
    return f"E{normalized[0]}-E{normalized[-1]}"


def _extract_subscription_candidate_title_preview(text: str) -> str:
    raw_text = str(text or "").strip()
    title = ""
    for pattern in (
        r"导入成功：(.+?)(?:（评分|，命中|，文件|$)",
        r"开始执行：(.+)$",
    ):
        match = re.search(pattern, raw_text)
        if match:
            title = str(match.group(1) or "").strip()
            break
    if not title:
        return ""
    title = re.sub(r"\s+", " ", title).strip(" ｜|，,。；;")
    if len(title) > 48:
        title = f"{title[:45]}..."
    return title


def _parse_subscription_candidate_ui_log(entry: Any) -> Optional[Dict[str, Any]]:
    payload = entry if isinstance(entry, dict) else {}
    raw_text = str(payload.get("raw_text") or payload.get("text") or "").strip()
    match = re.search(r"候选资源\s*#?(\d+)", raw_text)
    if not match:
        return None
    index = int(match.group(1) or "0")
    if index <= 0:
        return None

    miss_tokens = (
        "未命中",
        "未能",
        "已跳过",
        "跳过",
        "失败",
        "超时",
        "超出",
        "不高于当前进度",
        "无缺失",
        "目标目录已存在",
        "目录已覆盖",
        "集数重复",
        "链接命中失效缓存",
        "继续尝试下一个",
    )
    hit_tokens = (
        "导入成功",
        "已创建",
        "命中历史任务",
    )
    is_miss = any(token in raw_text for token in miss_tokens)
    is_hit = any(token in raw_text for token in hit_tokens) and not is_miss
    status = "hit" if is_hit else ("miss" if is_miss else "neutral")
    return {
        "seq": max(0, int(payload.get("seq", 0) or 0)),
        "index": index,
        "status": status,
        "episode": _extract_subscription_candidate_episode_preview(raw_text),
        "title": _extract_subscription_candidate_title_preview(raw_text),
        "level": str(payload.get("level", "info") or "info").strip().lower() or "info",
        "signature": str(payload.get("signature", "") or "").strip(),
    }


def _format_subscription_candidate_miss_log(
    start: int,
    end: int,
    count: int,
    first_signature: str,
    last_signature: str,
    first_seq: int = 0,
    last_seq: int = 0,
) -> Dict[str, Any]:
    if start == end:
        text = f"候选资源 {start} 未命中"
    else:
        text = f"候选资源 {start}-{end} 未命中"
    if count > 0 and count != max(1, end - start + 1):
        text = f"{text}（{count} 条）"
    signature = hashlib.sha1(f"candidate-miss:{start}:{end}:{count}:{first_signature}:{last_signature}".encode("utf-8")).hexdigest()[:12]
    seq = max(0, int(last_seq or first_seq or 0))
    return {"seq": seq, "text": text, "level": "info", "signature": signature}


def _format_subscription_candidate_hit_log(candidate: Dict[str, Any]) -> Dict[str, Any]:
    index = max(1, int(candidate.get("index", 0) or 0))
    episode = str(candidate.get("episode", "") or "").strip()
    title = str(candidate.get("title", "") or "").strip()
    text = f"候选资源 {index} 命中"
    detail_parts = []
    if title:
        detail_parts.append(f"资源：{title}")
    if episode:
        detail_parts.append(f"集数：{episode}")
    if detail_parts:
        text = f"{text} | {' | '.join(detail_parts)}"
    signature = str(candidate.get("signature", "") or "").strip()
    if not signature:
        signature = hashlib.sha1(f"candidate-hit:{index}:{title}:{episode}".encode("utf-8")).hexdigest()[:12]
    level = str(candidate.get("level", "success") or "success").strip().lower() or "success"
    seq = max(0, int(candidate.get("seq", 0) or 0))
    return {"seq": seq, "text": text, "level": level, "signature": signature}


def _compact_subscription_candidate_ui_logs(logs: Any) -> List[Dict[str, str]]:
    if not isinstance(logs, list):
        return []
    compacted: List[Dict[str, str]] = []
    pending_start = 0
    pending_end = 0
    pending_count = 0
    pending_first_signature = ""
    pending_last_signature = ""
    pending_first_seq = 0
    pending_last_seq = 0
    shown_hit_indexes: Set[int] = set()

    def flush_pending_misses() -> None:
        nonlocal pending_start, pending_end, pending_count, pending_first_signature, pending_last_signature
        nonlocal pending_first_seq, pending_last_seq
        if pending_count <= 0:
            return
        compacted.append(
            _format_subscription_candidate_miss_log(
                pending_start,
                pending_end,
                pending_count,
                pending_first_signature,
                pending_last_signature,
                pending_first_seq,
                pending_last_seq,
            )
        )
        pending_start = 0
        pending_end = 0
        pending_count = 0
        pending_first_signature = ""
        pending_last_signature = ""
        pending_first_seq = 0
        pending_last_seq = 0

    for entry in logs:
        candidate = _parse_subscription_candidate_ui_log(entry)
        if not candidate:
            flush_pending_misses()
            compacted.append(_serialize_subscription_ui_log(entry))
            continue
        status = str(candidate.get("status", "") or "").strip()
        if status == "neutral":
            continue
        if status == "hit":
            index = max(1, int(candidate.get("index", 0) or 0))
            if index in shown_hit_indexes:
                continue
            shown_hit_indexes.add(index)
            flush_pending_misses()
            compacted.append(_format_subscription_candidate_hit_log(candidate))
            continue
        index = max(1, int(candidate.get("index", 0) or 0))
        signature = str(candidate.get("signature", "") or "").strip()
        seq = max(0, int(candidate.get("seq", 0) or 0))
        if pending_count <= 0:
            pending_start = index
            pending_first_signature = signature
            pending_first_seq = seq
        pending_end = index
        pending_last_signature = signature
        pending_last_seq = seq
        pending_count += 1
    flush_pending_misses()
    return compacted


def _subscription_log_text_for_boundary(entry: Any) -> str:
    payload = entry if isinstance(entry, dict) else {}
    return str(payload.get("raw_text") or payload.get("display_text") or payload.get("text") or "").strip()


def _is_subscription_task_log_start(entry: Any) -> bool:
    text = _subscription_log_text_for_boundary(entry)
    return "订阅开始" in text


def _is_subscription_task_log_end(entry: Any) -> bool:
    text = _subscription_log_text_for_boundary(entry)
    return "订阅结束" in text


def _build_subscription_log_blocks(entries: Any) -> List[Dict[str, Any]]:
    if not isinstance(entries, list):
        return []
    blocks: List[Dict[str, Any]] = []
    active_task_block: Optional[Dict[str, Any]] = None

    def append_entry_to_block(block: Dict[str, Any], entry: Dict[str, Any]) -> None:
        block_entries = block.setdefault("entries", [])
        block_entries.append(entry)
        seq = max(0, int(entry.get("seq", 0) or 0))
        if seq <= 0:
            return
        if int(block.get("start_seq", 0) or 0) <= 0:
            block["start_seq"] = seq
        block["end_seq"] = seq

    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            continue
        entry = raw_entry
        if _is_subscription_task_log_start(entry):
            active_task_block = {
                "task": True,
                "start_seq": 0,
                "end_seq": 0,
                "entries": [],
            }
            blocks.append(active_task_block)
            append_entry_to_block(active_task_block, entry)
            if _is_subscription_task_log_end(entry):
                active_task_block = None
            continue

        if active_task_block is not None:
            append_entry_to_block(active_task_block, entry)
            if _is_subscription_task_log_end(entry):
                active_task_block = None
            continue

        if not blocks or bool(blocks[-1].get("task")):
            blocks.append(
                {
                    "task": False,
                    "start_seq": 0,
                    "end_seq": 0,
                    "entries": [],
                }
            )
        append_entry_to_block(blocks[-1], entry)

    return [
        block
        for block in blocks
        if isinstance(block.get("entries"), list) and block.get("entries")
    ]


def _flatten_subscription_log_blocks(blocks: Any) -> List[Dict[str, Any]]:
    flattened: List[Dict[str, Any]] = []
    if not isinstance(blocks, list):
        return flattened
    for block in blocks:
        entries = block.get("entries", []) if isinstance(block, dict) else []
        if isinstance(entries, list):
            flattened.extend(entry for entry in entries if isinstance(entry, dict))
    return flattened


def _tail_subscription_log_blocks_by_task_count(
    blocks: List[Dict[str, Any]],
    limit: int,
) -> Tuple[List[Dict[str, Any]], int, int]:
    normalized_limit = max(1, int(limit or 1))
    if not blocks:
        return [], 0, 0
    task_count = sum(1 for block in blocks if bool(block.get("task")))
    if task_count <= 0:
        start_index = max(0, len(blocks) - normalized_limit)
        return blocks[start_index:], start_index, len(blocks)
    remaining_tasks = normalized_limit
    start_index = 0
    for index in range(len(blocks) - 1, -1, -1):
        if bool(blocks[index].get("task")):
            remaining_tasks -= 1
        if remaining_tasks <= 0:
            start_index = index
            break
    return blocks[start_index:], start_index, len(blocks)


def _head_subscription_log_blocks_by_task_count(
    blocks: List[Dict[str, Any]],
    limit: int,
) -> Tuple[List[Dict[str, Any]], int, int]:
    normalized_limit = max(1, int(limit or 1))
    if not blocks:
        return [], 0, 0
    task_count = sum(1 for block in blocks if bool(block.get("task")))
    if task_count <= 0:
        end_index = min(len(blocks), normalized_limit)
        return blocks[:end_index], 0, end_index
    seen_tasks = 0
    end_index = len(blocks)
    for index, block in enumerate(blocks):
        if bool(block.get("task")):
            seen_tasks += 1
        if seen_tasks >= normalized_limit:
            end_index = index + 1
            break
    return blocks[:end_index], 0, end_index


def _tail_subscription_ui_logs(logs: Any, limit: int = SUBSCRIPTION_UI_RECENT_LOG_LIMIT) -> List[Dict[str, str]]:
    blocks = _build_subscription_log_blocks(logs)
    selected_blocks, _, _ = _tail_subscription_log_blocks_by_task_count(blocks, max(1, int(limit or 1)))
    return [_serialize_subscription_ui_log(entry) for entry in _flatten_subscription_log_blocks(selected_blocks)]


def _next_subscription_log_seq() -> int:
    global subscription_log_seq
    with subscription_log_seq_lock:
        subscription_log_seq += 1
        return subscription_log_seq


def build_subscription_log_preview(logs: Any = None) -> Dict[str, Any]:
    source = logs if isinstance(logs, list) else subscription_status.get("logs", [])
    if not isinstance(source, list) or not source:
        return {
            "seq": int(subscription_log_seq or 0),
            "text": "",
            "level": "info",
            "signature": "",
        }
    entry = source[-1] if isinstance(source[-1], dict) else {}
    return {
        "seq": max(0, int(entry.get("seq", subscription_log_seq) or subscription_log_seq or 0)),
        "text": str(entry.get("text") or entry.get("raw_text") or entry.get("display_text") or "").strip(),
        "display_text": str(entry.get("display_text") or "").strip(),
        "level": str(entry.get("level", "info") or "info").strip().lower() or "info",
        "signature": str(entry.get("signature", "") or "").strip(),
    }


def build_subscription_log_meta(logs: Any = None) -> Dict[str, Any]:
    source = logs if isinstance(logs, list) else subscription_status.get("logs", [])
    latest_seq = int(subscription_log_seq or 0)
    if isinstance(source, list) and source:
        latest_entry = source[-1] if isinstance(source[-1], dict) else {}
        latest_seq = max(latest_seq, int(latest_entry.get("seq", 0) or 0))
    return {
        "latest_seq": latest_seq,
        "total": latest_seq,
        "task_block_total": max(0, int(subscription_log_task_total or 0)),
        "recent_log_limit": SUBSCRIPTION_UI_RECENT_LOG_LIMIT,
        "page_log_limit": SUBSCRIPTION_LOG_PAGE_LIMIT,
        "recent_task_limit": SUBSCRIPTION_UI_RECENT_LOG_LIMIT,
        "page_task_limit": SUBSCRIPTION_LOG_PAGE_LIMIT,
        "latest": build_subscription_log_preview(source),
    }


def parse_int_param(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _read_subscription_event_payloads() -> List[Dict[str, Any]]:
    payloads: List[Dict[str, Any]] = []
    for line in read_log_lines(SUBSCRIPTION_EVENT_LOG_PATH):
        parsed = safe_json_loads(line, {})
        payloads.append(parsed if isinstance(parsed, dict) else {})
    return payloads


def build_subscription_log_entry_from_line(
    line: str,
    seq: int,
    event_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = event_payload if isinstance(event_payload, dict) else {}
    raw_text = str(payload.get("text") or "").strip()
    if not raw_text:
        raw_text = re.sub(r"^\d{2}-\d{2} \d{2}:\d{2}:\d{2}\s+", "", str(line or ""), count=1).strip()
    display_text = _build_subscription_log_display_text(raw_text, payload)
    full_text = str(line or "").strip() or display_text
    entry = {
        "seq": max(0, int(seq or 0)),
        "text": full_text,
        "display_text": display_text,
        "raw_text": raw_text,
        "level": str(payload.get("level") or infer_log_level_from_text(line)).strip().lower() or "info",
        "signature": hashlib.sha1(str(line or "").encode("utf-8")).hexdigest()[:12],
    }
    if payload:
        entry["event"] = {
            key: value
            for key, value in payload.items()
            if key != "text"
        }
    return entry


def build_subscription_log_page_payload(
    *,
    after: int = 0,
    before: int = 0,
    limit: int = SUBSCRIPTION_LOG_PAGE_LIMIT,
) -> Dict[str, Any]:
    normalized_limit = max(1, min(20, int(limit or SUBSCRIPTION_LOG_PAGE_LIMIT)))
    normalized_after = max(0, int(after or 0))
    normalized_before = max(0, int(before or 0))
    if normalized_after <= 0 and normalized_before <= 0:
        memory_payload = build_subscription_memory_log_page_payload(limit=normalized_limit)
        if memory_payload:
            return memory_payload
    lines = read_log_lines(SUBSCRIPTION_LOG_PATH)
    total = len(lines)
    latest_seq = max(total, int(subscription_log_seq or 0))
    base_seq = max(0, latest_seq - total)
    event_payloads = _read_subscription_event_payloads()
    event_start_index = max(0, len(event_payloads) - total)

    entries = []
    for index, line in enumerate(lines):
        event_index = event_start_index + index
        event_payload = event_payloads[event_index] if 0 <= event_index < len(event_payloads) else {}
        event_text = str(event_payload.get("text") or "").strip() if isinstance(event_payload, dict) else ""
        if event_text and event_text not in str(line or ""):
            event_payload = {}
        entries.append(build_subscription_log_entry_from_line(line, base_seq + index + 1, event_payload))

    blocks = _build_subscription_log_blocks(entries)
    task_block_total = sum(1 for block in blocks if bool(block.get("task")))
    oldest_available_seq = int(entries[0].get("seq", 0) or 0) if entries else 0
    if normalized_after > 0:
        eligible_blocks = [
            block
            for block in blocks
            if int(block.get("end_seq", 0) or 0) > normalized_after
        ]
        selected_blocks, _, selected_end = _head_subscription_log_blocks_by_task_count(eligible_blocks, normalized_limit)
        has_more_before = bool(selected_blocks) and int(selected_blocks[0].get("start_seq", 0) or 0) > oldest_available_seq
        has_more_after = selected_end < len(eligible_blocks)
    elif normalized_before > 0:
        eligible_blocks = [
            block
            for block in blocks
            if int(block.get("end_seq", 0) or 0) < normalized_before
        ]
        selected_blocks, selected_start, _ = _tail_subscription_log_blocks_by_task_count(eligible_blocks, normalized_limit)
        has_more_before = selected_start > 0
        has_more_after = bool(selected_blocks) and int(selected_blocks[-1].get("end_seq", 0) or 0) < latest_seq
    else:
        selected_blocks, selected_start, _ = _tail_subscription_log_blocks_by_task_count(blocks, normalized_limit)
        has_more_before = selected_start > 0
        has_more_after = False

    page_entries = _flatten_subscription_log_blocks(selected_blocks)
    return {
        "ok": True,
        "logs": page_entries,
        "total": total,
        "latest_seq": latest_seq,
        "oldest_available_seq": oldest_available_seq,
        "oldest_seq": page_entries[0]["seq"] if page_entries else 0,
        "newest_seq": page_entries[-1]["seq"] if page_entries else 0,
        "has_more_before": has_more_before,
        "has_more_after": has_more_after,
        "page_log_limit": normalized_limit,
        "line_count": len(page_entries),
        "available_total": total,
        "page_task_limit": normalized_limit,
        "task_block_count": sum(1 for block in selected_blocks if bool(block.get("task"))),
        "task_block_total": task_block_total,
    }


def build_subscription_memory_log_page_payload(
    *,
    limit: int = SUBSCRIPTION_LOG_PAGE_LIMIT,
) -> Dict[str, Any]:
    normalized_limit = max(1, min(20, int(limit or SUBSCRIPTION_LOG_PAGE_LIMIT)))
    source = subscription_status.get("logs", [])
    if not isinstance(source, list) or not source:
        return {}
    entries = [
        _serialize_subscription_ui_log(entry)
        for entry in source
        if isinstance(entry, dict) and max(0, int(entry.get("seq", 0) or 0)) > 0
    ]
    if not entries:
        return {}
    blocks = _build_subscription_log_blocks(entries)
    selected_blocks, selected_start, _ = _tail_subscription_log_blocks_by_task_count(blocks, normalized_limit)
    page_entries = _flatten_subscription_log_blocks(selected_blocks)
    latest_seq = max(
        int(subscription_log_seq or 0),
        max((int(entry.get("seq", 0) or 0) for entry in entries), default=0),
    )
    oldest_available_seq = int(entries[0].get("seq", 0) or 0)
    selected_task_count = sum(1 for block in selected_blocks if bool(block.get("task")))
    stored_task_total = max(0, int(subscription_log_task_total or 0))
    has_older_memory = selected_start > 0
    has_older_file = oldest_available_seq > 1 or (stored_task_total > 0 and stored_task_total > selected_task_count)
    return {
        "ok": True,
        "logs": page_entries,
        "total": latest_seq,
        "latest_seq": latest_seq,
        "oldest_available_seq": oldest_available_seq,
        "oldest_seq": page_entries[0]["seq"] if page_entries else 0,
        "newest_seq": page_entries[-1]["seq"] if page_entries else 0,
        "has_more_before": bool(has_older_memory or has_older_file),
        "has_more_after": False,
        "page_log_limit": normalized_limit,
        "line_count": len(page_entries),
        "available_total": len(entries),
        "page_task_limit": normalized_limit,
        "task_block_count": selected_task_count,
        "task_block_total": max(stored_task_total, selected_task_count),
        "source": "memory",
    }


async def clear_subscription_log_history() -> None:
    global subscription_log_seq, subscription_log_task_total
    clear_text = f"{format_log_time(True)} 订阅日志已清空"
    clear_display_text = _build_subscription_log_display_text("订阅日志已清空", {"event": "subscription.log", "stage": "runtime"})
    subscription_log_seq = 1
    subscription_log_task_total = 0
    subscription_status["logs"] = [
        {
            "seq": 1,
            "text": clear_text,
            "display_text": clear_display_text,
            "raw_text": "订阅日志已清空",
            "level": "info",
            "signature": hashlib.sha1(clear_text.encode("utf-8")).hexdigest()[:12],
        }
    ]
    await asyncio.to_thread(clear_log_file, SUBSCRIPTION_LOG_PATH, clear_text)
    await asyncio.to_thread(
        clear_log_file,
        SUBSCRIPTION_EVENT_LOG_PATH,
        safe_json_dumps(
            {
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "level": "info",
                "event": "subscription.log",
                "stage": "runtime",
                "reason_code": "",
                "text": "订阅日志已清空",
            }
        ),
    )
    schedule_ui_state_push(0)


def build_main_status_payload(log_limit: int = UI_STATUS_LOG_TAIL_LIMIT) -> Dict[str, Any]:
    return {
        "running": bool(task_status["running"]),
        "next_run": task_status.get("next_run"),
        "logs": _tail_jsonable_logs(task_status.get("logs", []), log_limit),
        "log_total": len(task_status.get("logs", [])) if isinstance(task_status.get("logs", []), list) else 0,
        "log_tail_limit": max(0, int(log_limit or 0)),
        "progress": clone_jsonable(task_status.get("progress", {})),
    }


def build_monitor_status_payload(
    cfg: Optional[Dict[str, Any]] = None,
    log_limit: int = UI_STATUS_LOG_TAIL_LIMIT,
    compact: bool = False,
) -> Dict[str, Any]:
    cfg = cfg or get_config()
    logs = monitor_status.get("logs", [])
    tail_limit = min(log_limit, UI_STATUS_STREAM_LOG_TAIL_LIMIT) if compact else log_limit
    segment_page = build_monitor_log_segment_page(limit=MONITOR_UI_RECENT_TASK_LOG_LIMIT)
    payload = {
        "running": bool(monitor_status["running"]),
        "current_task": str(monitor_status.get("current_task", "")),
        "queued": clone_jsonable(monitor_status.get("queued", [])),
        "logs": _tail_jsonable_logs(logs, tail_limit),
        "log_total": len(logs) if isinstance(logs, list) else 0,
        "log_tail_limit": max(0, int(tail_limit or 0)),
        "log_segments": segment_page["segments"],
        "log_segment_total": segment_page["total"],
        "log_segment_limit": segment_page["limit"],
        "log_segment_has_more": segment_page["has_more"],
        "summary": clone_jsonable(monitor_status.get("summary", {})),
        "webhook_base": "/webhook/",
    }
    if not compact:
        payload["tasks"] = clone_jsonable(cfg.get("monitor_tasks", []))
        payload["next_runs"] = clone_jsonable(monitor_next_run)
    return payload


def build_subscription_status_payload(
    cfg: Optional[Dict[str, Any]] = None,
    log_limit: int = UI_STATUS_LOG_TAIL_LIMIT,
    compact: bool = False,
    include_logs: bool = True,
) -> Dict[str, Any]:
    cfg = cfg or get_config()
    logs = subscription_status.get("logs", [])
    tail_limit = min(log_limit, UI_STATUS_STREAM_LOG_TAIL_LIMIT) if compact else log_limit
    payload = {
        "running": bool(subscription_status["running"]),
        "current_task": str(subscription_status.get("current_task", "")),
        "queued": clone_jsonable(subscription_status.get("queued", [])),
        "log_total": int(subscription_log_seq or 0),
        "log_tail_limit": max(0, int(tail_limit or 0)),
        "log_meta": build_subscription_log_meta(logs),
        "summary": clone_jsonable(subscription_status.get("summary", {})),
    }
    if include_logs:
        payload["logs"] = _tail_subscription_ui_logs(logs, SUBSCRIPTION_UI_RECENT_LOG_LIMIT)
    if compact:
        payload["task_updates"] = build_subscription_task_update_payload(cfg)
    if not compact:
        payload["tasks"] = clone_jsonable(list_subscription_task_runtime(cfg))
        payload["next_runs"] = clone_jsonable(subscription_next_run)
    return payload


def build_subscription_task_update_payload(cfg: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    update_keys = (
        "name",
        "status",
        "progress",
        "detail",
        "last_run_at",
        "last_success_at",
        "last_error",
        "last_episode",
        "total_episodes",
        "matched_resource_id",
        "matched_resource_title",
        "matched_score",
        "queued_job_id",
        "updated_at",
    )
    updates: List[Dict[str, Any]] = []
    for task in list_subscription_task_runtime(cfg):
        task_update = {key: task.get(key) for key in update_keys if key in task}
        if task_update.get("name"):
            updates.append(task_update)
    return clone_jsonable(updates)


def compute_sign115_next_run_text(cron_time: str, now: Optional[datetime] = None) -> str:
    normalized_time = normalize_sign115_cron_time(cron_time)
    now_dt = now or datetime.now()
    hour, minute = [int(part) for part in normalized_time.split(":", 1)]
    next_dt = now_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if next_dt <= now_dt:
        next_dt = next_dt + timedelta(days=1)
    return next_dt.strftime("%Y-%m-%d %H:%M:%S")


def set_sign115_status(**fields: Any) -> None:
    changed = False
    for key, value in fields.items():
        if sign115_status.get(key) == value:
            continue
        sign115_status[key] = value
        changed = True
    if changed:
        schedule_ui_state_push(0)


def build_sign115_status_payload(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = cfg or get_config()
    enabled = bool(cfg.get("sign115_enabled", False))
    cron_time = normalize_sign115_cron_time(cfg.get("sign115_cron_time", "09:00"))
    return {
        "enabled": enabled,
        "cron_time": cron_time,
        "next_run": compute_sign115_next_run_text(cron_time) if enabled else "",
        "running": bool(sign115_runtime.get("running", False)),
        "state": str(sign115_status.get("state", "idle") or "idle"),
        "message": str(sign115_status.get("message", "") or ""),
        "signed_today": sign115_status.get("signed_today", None),
        "reward_leaf": max(0, int(sign115_status.get("reward_leaf", 0) or 0)),
        "balance_leaf": (
            None
            if sign115_status.get("balance_leaf", None) is None
            else max(0, int(sign115_status.get("balance_leaf", 0) or 0))
        ),
        "last_checked_at": str(sign115_status.get("last_checked_at", "") or ""),
        "last_sign_at": str(sign115_status.get("last_sign_at", "") or ""),
        "last_trigger": str(sign115_status.get("last_trigger", "") or ""),
    }


def build_ui_state_payload(
    cfg: Optional[Dict[str, Any]] = None,
    log_limit: int = UI_STATUS_STREAM_LOG_TAIL_LIMIT,
    incremental: bool = False,
) -> Dict[str, Any]:
    active_cfg = cfg or get_config()
    full = {
        "main": build_main_status_payload(log_limit=log_limit),
        "monitor": build_monitor_status_payload(active_cfg, log_limit=log_limit, compact=incremental),
        "subscription": build_subscription_status_payload(
            active_cfg,
            log_limit=log_limit,
            compact=incremental,
            include_logs=False,
        ),
        "sign115": build_sign115_status_payload(active_cfg),
        "cookie_health": build_cookie_health_payload(active_cfg),
        "resource_channel_sync": build_resource_channel_sync_payload(),
        "resource_jobs": build_resource_jobs_signal_payload(),
    }
    if not incremental:
        return full

    changed = []
    delta: Dict[str, Any] = {}
    for key, value in full.items():
        module_hash = hashlib.md5(
            json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        if module_hash != _last_broadcast_hashes.get(key, ""):
            changed.append(key)
            delta[key] = value
            _last_broadcast_hashes[key] = module_hash

    delta["_changed"] = changed
    return delta


def set_resource_channel_sync_status(**fields: Any) -> None:
    changed = False
    with resource_channel_sync_status_lock:
        for key, value in fields.items():
            if resource_channel_sync_status.get(key) == value:
                continue
            resource_channel_sync_status[key] = clone_jsonable(value)
            changed = True
        if changed and "last_updated_at" not in fields:
            resource_channel_sync_status["last_updated_at"] = now_text()
    if changed:
        invalidate_resource_state_snapshot("resource-channel-sync")
        schedule_ui_state_push(0)


def build_resource_channel_sync_payload() -> Dict[str, Any]:
    with resource_channel_sync_status_lock:
        return clone_jsonable(resource_channel_sync_status)


class ResourceChannelSyncCancelled(asyncio.CancelledError):
    def __init__(self, message: str = "频道同步已中断", result: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = str(message or "频道同步已中断")
        self.result = clone_jsonable(result) if isinstance(result, dict) else {}


def reset_resource_channel_sync_cancel_request() -> None:
    with resource_channel_sync_control_lock:
        resource_channel_sync_control["cancel"] = False


def is_resource_channel_sync_cancel_requested() -> bool:
    with resource_channel_sync_control_lock:
        return bool(resource_channel_sync_control.get("cancel"))


def request_resource_channel_sync_cancel() -> bool:
    with resource_channel_sync_status_lock:
        active = bool(resource_channel_sync_status.get("submitted")) or bool(resource_channel_sync_status.get("running"))
    if not active:
        return False
    with resource_channel_sync_control_lock:
        resource_channel_sync_control["cancel"] = True
    set_resource_channel_sync_status(cancel_requested=True, cancelled=False)
    return True


def check_resource_channel_sync_cancelled(result: Optional[Dict[str, Any]] = None) -> None:
    if is_resource_channel_sync_cancel_requested():
        raise ResourceChannelSyncCancelled(result=result)


def build_resource_jobs_state_payload(
    limit: int = 20,
    cfg: Optional[Dict[str, Any]] = None,
    offset: int = 0,
    status_filter: str = "",
    include_monitor_tasks: bool = True,
    active_job_limit: int = 80,
) -> Dict[str, Any]:
    normalized_limit = max(1, min(int(limit or 20), 200))
    normalized_offset = max(0, int(offset or 0))
    normalized_filter = normalize_resource_job_status_filter(status_filter)
    normalized_active_job_limit = max(1, min(int(active_job_limit or 80), 200))
    cache_key = (
        "resource-jobs",
        normalized_limit,
        normalized_offset,
        normalized_filter,
        bool(include_monitor_tasks),
        normalized_active_job_limit,
    )
    cached_payload = _get_resource_state_snapshot(
        resource_jobs_state_snapshot_cache,
        cache_key,
        RESOURCE_JOBS_STATE_SNAPSHOT_TTL_SECONDS,
    )
    if cached_payload:
        return cached_payload

    active_cfg = cfg or get_config()
    jobs_page = list_resource_jobs_page(limit=normalized_limit, offset=normalized_offset, status_filter=normalized_filter)
    jobs = jobs_page.get("jobs", [])
    counts = count_resource_jobs_by_status()
    active_count = max(0, int(counts.get("active", 0) or 0))
    active_jobs: List[Dict[str, Any]] = []
    if active_count > 0:
        page_limit = int((jobs_page.get("pagination", {}) or {}).get("limit", 0) or normalized_limit)
        if normalized_filter == "active" and normalized_offset == 0 and page_limit >= min(active_count, normalized_active_job_limit):
            active_jobs = jobs
        else:
            active_jobs_page = list_resource_jobs_page(
                limit=normalized_active_job_limit,
                offset=0,
                status_filter="active",
            )
            active_jobs = active_jobs_page.get("jobs", [])
    payload = {
        "jobs": clone_jsonable(jobs),
        "active_jobs": clone_jsonable(active_jobs),
        "pagination": clone_jsonable(jobs_page.get("pagination", {})),
        "job_counts": clone_jsonable(counts),
        "stats": {
            "total_job_count": int(counts.get("total", 0) or 0),
            "active_job_count": active_count,
            "completed_job_count": int(counts.get("completed", 0) or 0),
            "failed_job_count": int(counts.get("failed", 0) or 0),
        },
    }
    if include_monitor_tasks:
        payload["monitor_tasks"] = clone_jsonable(active_cfg.get("monitor_tasks", []))
    _set_resource_state_snapshot(
        resource_jobs_state_snapshot_cache,
        cache_key,
        payload,
        RESOURCE_JOBS_STATE_SNAPSHOT_TTL_SECONDS,
    )
    return payload


def recover_resource_jobs_if_due(force: bool = False) -> Dict[str, Any]:
    global resource_job_recovery_last_ts
    now_ts = time.time()
    if (
        not force
        and resource_job_recovery_last_ts > 0
        and (now_ts - resource_job_recovery_last_ts) < RESOURCE_JOB_RECOVERY_INTERVAL_SECONDS
    ):
        return {"skipped": True}

    with resource_job_recovery_lock:
        now_ts = time.time()
        if (
            not force
            and resource_job_recovery_last_ts > 0
            and (now_ts - resource_job_recovery_last_ts) < RESOURCE_JOB_RECOVERY_INTERVAL_SECONDS
        ):
            return {"skipped": True}
        resource_job_recovery_last_ts = now_ts

    def run_recovery() -> Dict[str, Any]:
        return {
            "skipped": False,
            "stale": recover_stale_resource_jobs(),
            "submitted_without_monitor": recover_submitted_resource_jobs_without_monitor(),
            "history_pruned": prune_resource_job_history(),
        }

    try:
        return retry_sqlite_locked(run_recovery)
    except sqlite3.OperationalError as exc:
        if force or not is_sqlite_locked_error(exc):
            raise
        return {"skipped": True, "reason": "database_locked"}


def _build_resource_state_payload_snapshot(
    cfg: Dict[str, Any],
    keyword: str,
    search_meta: Dict[str, Any],
    search_source: str = "tg",
    provider_filter: str = "all",
    job_limit: int = 20,
    job_offset: int = 0,
    job_status_filter: str = "",
    compact: bool = False,
) -> Dict[str, Any]:
    keyword = str(keyword or "").strip()
    normalized_search_source = normalize_resource_search_source(search_source)
    normalized_provider_filter = normalize_resource_provider_filter(provider_filter)
    items = search_meta.get("items", []) if keyword else []
    search_sections = search_meta.get("sections", []) if keyword else []
    jobs_state = build_resource_jobs_state_payload(
        limit=job_limit,
        cfg=cfg,
        offset=job_offset,
        status_filter=job_status_filter,
        include_monitor_tasks=False,
    )
    jobs = jobs_state.get("jobs", [])
    active_jobs = jobs_state.get("active_jobs", [])
    job_counts = jobs_state.get("job_counts", {})
    job_pagination = jobs_state.get("pagination", {})
    total_item_count = count_resource_items(source_type="tg")
    filtered_item_count = 0
    stats_payload = jobs_state.get("stats", {})
    total_job_count = int(stats_payload.get("total_job_count", 0) or 0)
    active_job_count = int(stats_payload.get("active_job_count", 0) or 0)
    completed_job_count = int(stats_payload.get("completed_job_count", 0) or 0)
    failed_job_count = int(stats_payload.get("failed_job_count", 0) or 0)
    sources = [normalize_resource_source(source or {}) for source in cfg.get("resource_sources", [])]
    sync_sources = [source for source in sources if is_resource_source_sync_enabled(source)]
    search_sources = [source for source in sources if is_resource_source_search_enabled(source)]
    off_sources = [source for source in sources if not is_resource_source_search_enabled(source)]
    provider_auth_configured: Dict[str, bool] = {}
    try:
        for p in list_all():
            provider_auth_configured[p.name] = bool(p.is_configured(cfg))
    except Exception:
        provider_auth_configured = {
            "115": bool(str(cfg.get("cookie_115", "")).strip()),
            "quark": bool(str(cfg.get("cookie_quark", "")).strip()),
        }
    provider_cookie_flags = {
        f"cookie_configured_{provider_name}": bool(configured)
        for provider_name, configured in provider_auth_configured.items()
    }
    if compact and not keyword:
        return {
            "jobs": clone_jsonable(jobs),
            "active_jobs": clone_jsonable(active_jobs),
            "job_counts": clone_jsonable(job_counts),
            "pagination": clone_jsonable(job_pagination),
            "channel_sync": build_resource_channel_sync_payload(),
            "stats": {
                "source_count": len(sync_sources),
                "total_source_count": len(sources),
                "sync_source_count": len(sync_sources),
                "search_source_count": len(search_sources),
                "disabled_source_count": len(off_sources),
                "item_count": total_item_count,
                "total_job_count": total_job_count,
                "active_job_count": active_job_count,
                "completed_job_count": completed_job_count,
                "failed_job_count": failed_job_count,
            },
            "setup_status": {
                "strm_ready": bool(
                    str(cfg.get("cookie_115", "")).strip() and str(cfg.get("strm_proxy_base_url", "")).strip()
                ),
                "cookie_configured": bool(str(cfg.get("cookie_115", "")).strip()),
                "quark_cookie_configured": bool(str(cfg.get("cookie_quark", "")).strip()),
                "has_sources": bool(sync_sources),
                "has_monitor": bool(cfg.get("monitor_tasks", [])),
                "has_resource_data": total_item_count > 0,
                "has_jobs": total_job_count > 0,
            },
            "provider_auth": clone_jsonable(provider_auth_configured),
            **provider_cookie_flags,
            "default_magnet_provider": normalize_magnet_provider(cfg.get("default_magnet_provider", "115")),
            "cookie_health": build_cookie_health_payload(cfg),
        }
    tg_channel_sync_limit = get_tg_channel_sync_limit(cfg)
    channel_ids = [
        normalize_telegram_channel_id_from_input((source or {}).get("channel_id", ""))
        for source in (sources if isinstance(sources, list) else [])
        if isinstance(source, dict)
    ]
    channel_ids = [channel_id for channel_id in channel_ids if channel_id]
    subscription_channel_support = load_subscription_channel_support_stats(channel_ids)
    channel_sections = build_resource_channel_sections(sync_sources, per_channel=tg_channel_sync_limit)
    channel_sections = filter_resource_sections_by_provider(channel_sections, normalized_provider_filter, drop_empty=normalized_provider_filter != "all")
    search_sections = filter_resource_sections_by_provider(search_sections, normalized_provider_filter, drop_empty=True)
    items = filter_resource_items_by_provider(items, normalized_provider_filter)
    filtered_item_count = len(items)
    channel_profiles = {
        str(section.get("channel_id", "")).strip(): section.get("channel_profile", {})
        for section in channel_sections
        if str(section.get("channel_id", "")).strip()
    }
    return {
        "sources": clone_jsonable(sources),
        "quick_links": clone_jsonable(cfg.get("resource_quick_links", [])),
        "favorite_dirs": clone_jsonable(cfg.get("resource_favorite_dirs", {"115": [], "quark": []})),
        "items": clone_jsonable(items),
        "jobs": clone_jsonable(jobs),
        "active_jobs": clone_jsonable(active_jobs),
        "job_counts": clone_jsonable(job_counts),
        "pagination": clone_jsonable(job_pagination),
        "monitor_tasks": clone_jsonable(cfg.get("monitor_tasks", [])),
        "cookie_configured": bool(str(cfg.get("cookie_115", "")).strip()),
        "quark_cookie_configured": bool(str(cfg.get("cookie_quark", "")).strip()),
        "provider_auth": clone_jsonable(provider_auth_configured),
        **provider_cookie_flags,
        "default_magnet_provider": normalize_magnet_provider(cfg.get("default_magnet_provider", "115")),
        "cookie_health": build_cookie_health_payload(cfg),
        "setup_status": {
            "strm_ready": bool(
                str(cfg.get("cookie_115", "")).strip() and str(cfg.get("strm_proxy_base_url", "")).strip()
            ),
            "cookie_configured": bool(str(cfg.get("cookie_115", "")).strip()),
            "quark_cookie_configured": bool(str(cfg.get("cookie_quark", "")).strip()),
            "has_sources": bool(sync_sources),
            "has_monitor": bool(cfg.get("monitor_tasks", [])),
            "has_resource_data": total_item_count > 0,
            "has_jobs": total_job_count > 0,
        },
        "search": keyword,
        "search_source": normalized_search_source,
        "provider_filter": normalized_provider_filter,
        "channel_sections": clone_jsonable(channel_sections),
        "channel_profiles": clone_jsonable(channel_profiles),
        "subscription_channel_support": clone_jsonable(subscription_channel_support),
        "search_sections": clone_jsonable(search_sections),
        "last_syncs": clone_jsonable(resource_channel_last_sync),
        "channel_sync": build_resource_channel_sync_payload(),
        "search_meta": clone_jsonable(
            {
                "errors": search_meta.get("errors", []),
                "searched_sources": search_meta.get("searched_sources", 0),
                "matched_channels": search_meta.get("matched_channels", 0),
                "pages_scanned": search_meta.get("pages_scanned", 0),
                "thread_limit": search_meta.get("thread_limit", get_tg_channel_threads(cfg)),
                "sync_limit_per_channel": tg_channel_sync_limit,
                "search_source": normalized_search_source,
                "provider_filter": normalized_provider_filter,
                "pansou_enabled": search_meta.get("pansou_enabled", bool(cfg.get("pansou_enabled", False))),
                "pansou_items": search_meta.get("pansou_items", 0),
                "pansou_elapsed_ms": search_meta.get("pansou_elapsed_ms", 0),
            }
        ),
        "stats": {
            "source_count": len(sync_sources),
            "total_source_count": len(sources),
            "sync_source_count": len(sync_sources),
            "search_source_count": len(search_sources),
            "disabled_source_count": len(off_sources),
            "item_count": total_item_count,
            "filtered_item_count": filtered_item_count,
            "total_job_count": total_job_count,
            "active_job_count": active_job_count,
            "completed_job_count": completed_job_count,
            "failed_job_count": failed_job_count,
        },
    }


async def build_resource_state_payload(
    search: str = "",
    search_source: str = "tg",
    provider_filter: str = "all",
    search_id: str = "",
    job_limit: int = 20,
    job_offset: int = 0,
    job_status_filter: str = "",
    compact: bool = False,
) -> Dict[str, Any]:
    cfg = get_config()
    await asyncio.to_thread(recover_resource_jobs_if_due)
    keyword = str(search or "").strip()
    normalized_search_source = normalize_resource_search_source(search_source)
    normalized_provider_filter = normalize_resource_provider_filter(provider_filter)
    normalized_search_id = normalize_resource_search_id(search_id)
    normalized_job_limit = max(1, min(int(job_limit or 20), 200))
    normalized_job_offset = max(0, int(job_offset or 0))
    normalized_job_status_filter = normalize_resource_job_status_filter(job_status_filter)
    compact_snapshot_key = (
        "resource-compact",
        normalized_provider_filter,
        normalized_job_limit,
        normalized_job_offset,
        normalized_job_status_filter,
    )
    if compact and not keyword:
        cached_payload = _get_resource_state_snapshot(
            resource_compact_state_snapshot_cache,
            compact_snapshot_key,
            RESOURCE_COMPACT_STATE_SNAPSHOT_TTL_SECONDS,
        )
        if cached_payload:
            return cached_payload
    try:
        check_resource_search_cancelled(normalized_search_id)
        if keyword and normalized_search_source == "pansou":
            search_meta = await search_pansou_resource_sources(
                keyword,
                provider_filter=normalized_provider_filter,
                search_id=normalized_search_id,
            )
        elif keyword:
            search_meta = await search_resource_sources(
                keyword,
                provider_filter=normalized_provider_filter,
                search_id=normalized_search_id,
            )
        else:
            search_meta = {
                "items": [],
                "sections": [],
                "errors": [],
                "searched_sources": len([
                    source
                    for source in (normalize_resource_source(raw_source or {}) for raw_source in cfg.get("resource_sources", []))
                    if is_resource_source_search_enabled(source)
                ]),
                "matched_channels": 0,
                "pages_scanned": 0,
            }
    except ResourceSearchCancelled:
        search_meta = {
            "items": [],
            "sections": [],
            "errors": [{"channel_id": "resource-search", "name": "资源搜索", "message": "搜索已中断"}],
            "searched_sources": 0,
            "matched_channels": 0,
            "pages_scanned": 0,
            "cancelled": True,
        }
    payload = await asyncio.to_thread(
        _build_resource_state_payload_snapshot,
        cfg,
        keyword,
        search_meta,
        normalized_search_source,
        normalized_provider_filter,
        normalized_job_limit,
        normalized_job_offset,
        normalized_job_status_filter,
        compact,
    )
    if compact and not keyword:
        _set_resource_state_snapshot(
            resource_compact_state_snapshot_cache,
            compact_snapshot_key,
            payload,
            RESOURCE_COMPACT_STATE_SNAPSHOT_TTL_SECONDS,
        )
    return payload


async def sync_telegram_channels(force: bool = False, limit_per_channel: Optional[int] = None) -> Dict[str, Any]:
    cfg = get_config()
    tg_channel_sync_limit = normalize_tg_channel_sync_limit(
        limit_per_channel,
        fallback=get_tg_channel_sync_limit(cfg),
    )
    synced_channels = 0
    upserted_items = 0
    skipped_channels = 0
    per_channel_pruned = 0
    errors: List[Dict[str, str]] = []
    cache_prune_detail = {
        "per_channel": 0,
        "inactive": 0,
        "expired": 0,
        "global": 0,
        "active_channels": 0,
    }
    cache_pruned = 0
    claimed_channel_ids: Set[str] = set()

    def build_sync_result(*, cancelled: bool = False) -> Dict[str, Any]:
        payload = {
            "ok": not errors and not cancelled,
            "synced": synced_channels,
            "items": upserted_items,
            "skipped": skipped_channels,
            "errors": clone_jsonable(errors),
            "cache_pruned": cache_pruned,
            "cache_prune_detail": clone_jsonable(cache_prune_detail),
            "limit_per_channel": tg_channel_sync_limit,
        }
        if cancelled:
            payload["cancelled"] = True
        return payload

    sources = [
        source
        for source in (normalize_resource_source(raw_source or {}) for raw_source in cfg.get("resource_sources", []))
        if is_resource_source_sync_enabled(source)
    ]
    try:
        check_resource_channel_sync_cancelled(build_sync_result(cancelled=True))
        if not sources:
            ensure_db()
            conn = open_db()
            try:
                governance_detail = run_resource_cache_governance(conn, [])
                cache_prune_detail = {
                    "per_channel": 0,
                    "inactive": int(governance_detail.get("inactive", 0) or 0),
                    "expired": int(governance_detail.get("expired", 0) or 0),
                    "global": int(governance_detail.get("global", 0) or 0),
                    "active_channels": 0,
                }
                cache_pruned = (
                    cache_prune_detail["inactive"]
                    + cache_prune_detail["expired"]
                    + cache_prune_detail["global"]
                )
                if cache_pruned > 0:
                    conn.commit()
            finally:
                conn.close()
            check_resource_channel_sync_cancelled(build_sync_result(cancelled=True))
            return build_sync_result()

        ensure_db()
        tg_channel_threads = get_tg_channel_threads(cfg)
        semaphore = asyncio.Semaphore(tg_channel_threads)
        targets: List[Tuple[Dict[str, Any], str]] = []
        for source in sources:
            check_resource_channel_sync_cancelled(build_sync_result(cancelled=True))
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
            claimed_channel_ids.add(channel_id)
            targets.append((source, channel_id))

        async def fetch_one_source(source: Dict[str, Any], channel_id: str) -> Dict[str, Any]:
            source_name = str(source.get("name", "") or channel_id).strip()
            check_resource_channel_sync_cancelled(build_sync_result(cancelled=True))
            try:
                async with semaphore:
                    check_resource_channel_sync_cancelled(build_sync_result(cancelled=True))
                    sample_bundle = await asyncio.to_thread(
                        fetch_telegram_channel_post_samples,
                        cfg,
                        source,
                        max(tg_channel_sync_limit, RESOURCE_CHANNEL_TYPE_SAMPLE_SIZE),
                        max(tg_channel_sync_limit, RESOURCE_CHANNEL_TYPE_PAGE_LIMIT),
                        RESOURCE_CHANNEL_TYPE_MAX_PAGES,
                    )
                    check_resource_channel_sync_cancelled(build_sync_result(cancelled=True))
                    posts = sample_bundle.get("posts", []) if isinstance(sample_bundle, dict) else []
                    if not posts:
                        posts = await asyncio.to_thread(fetch_telegram_channel_posts, cfg, source, tg_channel_sync_limit)
                    check_resource_channel_sync_cancelled(build_sync_result(cancelled=True))
                return {"channel_id": channel_id, "name": source_name, "posts": posts}
            except ResourceChannelSyncCancelled:
                raise
            except Exception as exc:
                return {"channel_id": channel_id, "name": source_name, "error": str(exc)}
            finally:
                resource_channel_syncing.discard(channel_id)
                claimed_channel_ids.discard(channel_id)

        results = await asyncio.gather(*(fetch_one_source(source, channel_id) for source, channel_id in targets))
        check_resource_channel_sync_cancelled(build_sync_result(cancelled=True))

        conn = open_db()
        try:
            for result in results:
                check_resource_channel_sync_cancelled(build_sync_result(cancelled=True))
                channel_id = str(result.get("channel_id", "")).strip()
                if not channel_id:
                    continue
                error_message = str(result.get("error", "")).strip()
                if error_message:
                    resource_channel_last_error[channel_id] = error_message
                    errors.append(
                        {
                            "channel_id": channel_id,
                            "name": str(result.get("name", "") or channel_id).strip(),
                            "message": error_message,
                        }
                    )
                    continue

                posts = result.get("posts", []) if isinstance(result.get("posts"), list) else []
                for post in posts:
                    _, created = upsert_resource_item(conn, post)
                    upserted_items += 1 if created else 0
                resource_channel_profiles[channel_id] = build_resource_channel_profile(channel_id, posts)
                per_channel_pruned += prune_resource_channel_cache(conn, channel_id, keep=tg_channel_sync_limit)
                conn.commit()
                resource_channel_last_sync[channel_id] = time.time()
                resource_channel_last_error.pop(channel_id, None)
                synced_channels += 1

            check_resource_channel_sync_cancelled(build_sync_result(cancelled=True))
            governance_detail = run_resource_cache_governance(
                conn,
                sources,
                active_min_keep=max(RESOURCE_CHANNEL_CACHE_ACTIVE_MIN_KEEP, tg_channel_sync_limit),
            )
            cache_prune_detail = {
                "per_channel": per_channel_pruned,
                "inactive": int(governance_detail.get("inactive", 0) or 0),
                "expired": int(governance_detail.get("expired", 0) or 0),
                "global": int(governance_detail.get("global", 0) or 0),
                "active_channels": int(governance_detail.get("active_channels", 0) or 0),
            }
            cache_pruned = (
                cache_prune_detail["per_channel"]
                + cache_prune_detail["inactive"]
                + cache_prune_detail["expired"]
                + cache_prune_detail["global"]
            )
            if cache_pruned > 0:
                conn.commit()
            check_resource_channel_sync_cancelled(build_sync_result(cancelled=True))
        finally:
            conn.close()

        if synced_channels > 0 or cache_pruned > 0:
            invalidate_resource_state_snapshot("resource-channel-sync-result")
        return build_sync_result()
    finally:
        for channel_id in list(claimed_channel_ids):
            resource_channel_syncing.discard(channel_id)


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
    global ui_push_pending, ui_push_task, _last_full_broadcast_ts
    try:
        await asyncio.sleep(max(0.0, delay))
        while ui_push_pending:
            ui_push_pending = False
            now_ts = time.time()
            force_full = (now_ts - _last_full_broadcast_ts) >= UI_FULL_BROADCAST_INTERVAL_SECONDS
            cfg = get_config()
            payload_dict = build_ui_state_payload(
                cfg,
                incremental=not force_full,
            )
            if force_full:
                _last_full_broadcast_ts = now_ts
            payload = json.dumps(payload_dict, ensure_ascii=False)
            await broadcast_ui_state(payload)
            if ui_push_pending:
                await asyncio.sleep(UI_PUSH_DEBOUNCE_SECONDS)
    finally:
        ui_push_task = None


def bind_ui_event_loop(loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
    global ui_event_loop
    try:
        ui_event_loop = loop or asyncio.get_running_loop()
    except RuntimeError:
        ui_event_loop = None


def schedule_ui_state_push(delay: float = UI_PUSH_DEBOUNCE_SECONDS) -> None:
    global ui_push_pending, ui_push_task
    ui_push_pending = True
    target_loop = ui_event_loop
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None
    if target_loop is None:
        if threading.current_thread().name == "media-hub-background":
            return
        target_loop = current_loop
    if target_loop is None or target_loop.is_closed():
        return

    def ensure_push_task() -> None:
        global ui_push_task
        if ui_push_task is not None and not ui_push_task.done():
            return
        ui_push_task = target_loop.create_task(flush_ui_state_updates(delay))

    if current_loop is target_loop:
        ensure_push_task()
        return
    target_loop.call_soon_threadsafe(ensure_push_task)


def is_subpath(path: str, root: str) -> bool:
    path = normalize_remote_path(path)
    root = normalize_remote_path(root)
    return path == root or path.startswith(root + "/")


def extract_webhook_refresh_path(task: Dict[str, Any], payload: Dict[str, Any], cfg: Dict[str, Any]) -> Optional[str]:
    scan_path = normalize_remote_path(task.get("scan_path", ""))
    mount_prefix = get_mount_prefix(cfg, "115")
    if not mount_prefix:
        return None
    candidates: List[str] = []
    savepath_raw = str(payload.get("savepath", "") or "").strip()
    savepath_rel = normalize_relative_path(savepath_raw)
    sharetitle_raw = str(payload.get("sharetitle", "") or "").strip()
    sharetitle_rel = normalize_relative_path(sharetitle_raw)
    if sharetitle_rel and is_resource_title_link_like(sharetitle_rel):
        sharetitle_rel = ""
    refresh_target_type = str(payload.get("refresh_target_type", "") or "").strip().lower()
    allow_subdir_hint = refresh_target_type not in ("file", "mixed")

    if savepath_rel and sharetitle_rel and allow_subdir_hint:
        # 优先定位本次转存子目录：savepath/sharetitle
        detailed_rel = join_relative_path(savepath_rel, sharetitle_rel)
        detailed_norm = normalize_remote_path("/" + detailed_rel)
        candidates.append(join_remote_path(mount_prefix, detailed_norm))

    if savepath_rel:
        # savepath 支持 "连载中/xxx" 和 "/连载中/xxx" 两种写法
        save_norm = normalize_remote_path("/" + savepath_rel)
        candidates.append(join_remote_path(mount_prefix, save_norm))

    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if is_subpath(candidate, scan_path):
            return candidate

    if savepath_rel:
        scan_tail = (
            normalize_relative_path(scan_path[len(mount_prefix) :])
            if scan_path.startswith(mount_prefix)
            else normalize_relative_path(scan_path)
        )
        save_tail = savepath_rel
        if scan_tail and (scan_tail == save_tail or scan_tail.endswith("/" + save_tail) or save_tail.endswith("/" + scan_tail)):
            return scan_path
    return None


async def update_progress(step: str, percent: float, detail: str) -> None:
    task_status["progress"].update({"step": step, "percent": int(percent), "detail": detail})
    schedule_ui_state_push()
    await asyncio.sleep(0)


async def write_log(msg: str, level: Optional[str] = None) -> None:
    resolved_level = str(level or infer_log_level_from_text(msg)).strip().lower() or "info"
    line = f"{format_log_time(True)} {msg}"
    _append_status_log_entry(task_status["logs"], {"text": line, "level": resolved_level})
    schedule_ui_state_push()
    await asyncio.to_thread(append_log_file, MAIN_LOG_PATH, line)
    await asyncio.sleep(0)


async def write_monitor_log(text: str, level: str = "info") -> None:
    resolved_level = str(level or infer_log_level_from_text(text)).strip().lower() or "info"
    line = f"{format_log_time(True)} {text}"
    entry = {"text": line, "level": resolved_level}
    _append_status_log_entry(monitor_status["logs"], entry)
    _append_monitor_log_segment_entry(entry)
    schedule_ui_state_push()
    await asyncio.to_thread(append_log_file, MONITOR_LOG_PATH, line)
    await asyncio.sleep(0)


def set_subscription_log_context(context: Optional[Dict[str, Any]]) -> contextvars.Token:
    normalized = clone_jsonable(context if isinstance(context, dict) else {})
    return subscription_log_context_var.set(normalized)


def reset_subscription_log_context(token: contextvars.Token) -> None:
    try:
        subscription_log_context_var.reset(token)
    except Exception:
        pass


def _infer_subscription_log_event(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    if "订阅开始" in normalized:
        return "subscription.run.start"
    if "订阅结束" in normalized:
        return "subscription.run.finish"
    if "搜索完成" in normalized:
        return "subscription.search.summary"
    if "增量搜索已启用" in normalized:
        return "subscription.search.incremental"
    if "导入成功" in normalized:
        return "subscription.import.success"
    if "导入失败" in normalized:
        return "subscription.import.failed"
    if "导入超时" in normalized:
        return "subscription.import.timeout"
    if "导入汇总" in normalized:
        return "subscription.import.summary"
    if "批次收口汇总" in normalized:
        return "subscription.batch.refresh.summary"
    if "失败原因" in normalized:
        return "subscription.run.failed"
    return "subscription.log"


def _infer_subscription_log_stage(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    if "搜索" in normalized or "频道" in normalized:
        return "search"
    if "候选资源" in normalized:
        return "candidate"
    if "导入" in normalized or "转存" in normalized:
        return "import"
    if "批次收口" in normalized:
        return "batch_refresh"
    if "订阅开始" in normalized or "订阅结束" in normalized:
        return "lifecycle"
    return "runtime"


def _infer_subscription_log_reason_code(text: str) -> str:
    normalized = str(text or "")
    if "no_precise_episode_match" in normalized:
        return "no_precise_episode_match"
    if "manifest_no_missing" in normalized:
        return "manifest_no_missing"
    if "subdir_not_found" in normalized or "未命中订阅子目录" in normalized:
        return "subdir_not_found"
    if "命中失效缓存" in normalized or "链接已标记为失效" in normalized:
        return "invalid_link_cached"
    if "导入超时" in normalized:
        return "import_timeout"
    if "导入失败" in normalized:
        return "import_failed"
    if "导入成功" in normalized:
        return "import_success"
    if "搜索异常" in normalized or "频道搜索超时" in normalized:
        return "search_error"
    if "目标目录已存在" in normalized:
        return "already_exists"
    if "等待新集发布" in normalized or "等待新资源发布" in normalized:
        return "waiting_new_resource"
    return ""


def _build_subscription_log_display_text(text: str, event_payload: Dict[str, Any]) -> str:
    return re.sub(r"^\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+", "", str(text or ""), count=1).strip()


async def write_subscription_log(text: str, level: str = "info", compact: Optional[str] = None) -> None:
    global subscription_log_task_total
    resolved_level = str(level or infer_log_level_from_text(text)).strip().lower() or "info"
    timestamp = format_log_time(True)
    line = f"{timestamp} {text}"
    seq = _next_subscription_log_seq()
    if "订阅开始" in str(text or ""):
        subscription_log_task_total += 1
    context = subscription_log_context_var.get() or {}
    event = _infer_subscription_log_event(text)
    stage = _infer_subscription_log_stage(text)
    reason_code = _infer_subscription_log_reason_code(text)
    event_payload = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "level": resolved_level,
        "event": event,
        "stage": stage,
        "reason_code": reason_code,
        "text": str(text or ""),
        "run_id": str(context.get("run_id", "") or "").strip(),
        "task_name": str(context.get("task_name", "") or "").strip(),
        "provider": str(context.get("provider", "") or "").strip(),
        "media_type": str(context.get("media_type", "") or "").strip(),
        "trigger": str(context.get("trigger", "") or "").strip(),
    }
    display_text = _build_subscription_log_display_text(text, event_payload)
    ui_event_payload = {
        key: value
        for key, value in event_payload.items()
        if key != "text"
    }
    ui_log_entry = {
        "seq": seq,
        "text": line,
        "display_text": display_text,
        "raw_text": event_payload["text"],
        "level": resolved_level,
        "event": ui_event_payload,
        "signature": hashlib.sha1(line.encode("utf-8")).hexdigest()[:12],
    }
    _append_status_log_entry(subscription_status["logs"], ui_log_entry)
    schedule_ui_state_push()
    try:
        await asyncio.to_thread(append_log_file, SUBSCRIPTION_LOG_PATH, line)
        await asyncio.to_thread(append_log_file, SUBSCRIPTION_EVENT_LOG_PATH, safe_json_dumps(event_payload))
    except Exception as exc:
        # 日志写盘失败不应中断主流程，保留内存日志并继续执行任务。
        fallback_line = f"{format_log_time(True)} [WARN] 订阅日志写盘失败：{str(exc)[:180]}"
        _append_status_log_entry(
            subscription_status["logs"],
            {
                "seq": _next_subscription_log_seq(),
                "text": "日志写盘失败",
                "level": "warn",
                "signature": hashlib.sha1(fallback_line.encode("utf-8")).hexdigest()[:12],
            },
        )
        schedule_ui_state_push()
    await asyncio.sleep(0)


def update_monitor_summary(step: str, detail: str) -> None:
    monitor_status["summary"] = {"step": step, "detail": detail}
    schedule_ui_state_push()


def update_subscription_summary(step: str, detail: str) -> None:
    subscription_status["summary"] = {"step": step, "detail": detail}
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


def format_subscription_trigger(trigger: str) -> str:
    labels = {
        "manual": "手动触发",
        "manual_link": "指定链接触发",
        "cron": "时段定时触发",
        "queued": "队列触发",
    }
    return labels.get(trigger, trigger or "未知触发")


def format_subscription_media_type_label(media_type: Any) -> str:
    normalized = str(media_type or "movie").strip().lower()
    return "电视剧" if normalized == "tv" else "电影"


def format_subscription_provider_label(provider: Any) -> str:
    normalized = normalize_subscription_provider(provider, fallback="115")
    p = _get_provider_or_none(normalized)
    return str(getattr(p, "label", "") or normalized).strip() if p else normalized


def format_resource_link_type_label(link_type: Any, link_url: Any = "") -> str:
    normalized = resolve_resource_link_type(str(link_type or "").strip(), str(link_url or "").strip())
    labels = {
        "115share": "115 分享",
        "quark": "夸克分享",
        "magnet": "磁力",
        "aliyun": "阿里云盘",
        "baidu": "百度网盘",
        "xunlei": "迅雷网盘",
        "uc": "UC 网盘",
        "123pan": "123 网盘",
        "tianyi": "天翼云盘",
        "pikpak": "PikPak",
        "lanzou": "蓝奏云",
        "google_drive": "Google Drive",
        "onedrive": "OneDrive",
        "mega": "MEGA",
    }
    if normalized:
        return labels.get(normalized, normalized)
    return "未知链接"


def format_monitor_bool(enabled: bool) -> str:
    return "开启" if enabled else "关闭"


async def write_monitor_section(title: str) -> None:
    await write_monitor_log(f"·· {title} ··", "section-divider")


async def write_subscription_section(title: str) -> None:
    await write_subscription_log(f"·· {title} ··", "section-divider")


async def write_monitor_task_header(task: Dict[str, Any], trigger: str, payload: Optional[Dict[str, Any]] = None) -> None:
    write_mode_label = "全量重写 STRM" if task.get("strm_write_mode") == "full" else "增量生成/更新 STRM"
    await write_monitor_log(
        f"━━━━━━━━━━【任务开始 | {task['name']} | {format_monitor_trigger(trigger)}】━━━━━━━━━━",
        "task-divider",
    )
    await write_monitor_log(
        f"扫描: {task['scan_path']} | 输出: /strm/{resolve_task_root(task)}",
        "info",
    )
    await write_monitor_log(
        (
            f"写入: {write_mode_label} | "
            f"清理过期 STRM: {format_monitor_bool(task.get('sync_clean', not task.get('incremental', False)))} | "
            f"目录时间检查: {format_monitor_bool(task['skip_by_dir_mtime'])}"
        ),
        "info",
    )
    if payload and trigger in ("webhook", "resource"):
        title = str(payload.get("title", "") or "").strip()
        sharetitle = normalize_relative_path(payload.get("sharetitle", ""))
        if sharetitle and is_resource_title_link_like(sharetitle):
            sharetitle = ""
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


async def write_monitor_task_summary(stats: Dict[str, int], cleanup_enabled: Optional[bool] = None) -> None:
    await write_monitor_log(
        f"生成汇总: 新增/更新 {stats['generated']} | 跳过文件 {stats['skipped']} | 跳过目录 {stats['skipped_dirs']} | 失败目录 {stats['failed_dirs']}",
        "info",
    )
    cleanup_label = "未配置" if cleanup_enabled is None else format_monitor_bool(bool(cleanup_enabled))
    await write_monitor_log(
        f"清理汇总: 清理过期 STRM {cleanup_label} | 删除 STRM {stats['deleted_files']} | 删除空目录 {stats['deleted_dirs']}",
        "info",
    )


def check_monitor_cancelled() -> None:
    if monitor_control["cancel"]:
        raise asyncio.CancelledError()


def check_subscription_cancelled() -> None:
    if subscription_control["cancel"]:
        raise asyncio.CancelledError()


async def sleep_interruptible(seconds: float) -> None:
    end_at = time.time() + max(0, seconds)
    while time.time() < end_at:
        check_monitor_cancelled()
        await asyncio.sleep(min(0.5, end_at - time.time()))


from .providers.registry import get_all_capabilities, get_by_link_type, get_or_none as _get_provider_or_none, list_all, list_enabled

from .providers.common import parse_int
from .share_selection import (
    merge_share_selection_meta,
    normalize_share_selection_entry,
    normalize_share_selection_meta,
)
from .services.subscription_state import (
    create_subscription_match,
    find_subscription_task_match_candidate,
    has_subscription_match,
    list_subscription_task_runtime,
    load_subscription_channel_search_watermarks,
    load_subscription_channel_support_stats,
    load_subscription_episode_ledger,
    load_subscription_task_state,
    prune_subscription_state_for_missing_tasks,
    reconcile_subscription_episode_ledger,
    upsert_subscription_channel_search_watermarks,
    upsert_subscription_channel_support_stats,
    upsert_subscription_episode_ledger,
    upsert_subscription_task_state,
)
from .resource_jobs import (
    clear_completed_resource_jobs,
    clear_resource_jobs,
    count_resource_jobs,
    count_resource_jobs_by_status,
    create_resource_job,
    create_resource_jobs,
    delete_resource_item,
    find_existing_resource_job,
    get_resource_job,
    get_resource_jobs_by_ids,
    list_resource_jobs,
    list_resource_jobs_page,
    list_resource_jobs_by_source,
    normalize_resource_job_clear_scope,
    normalize_resource_job_status_filter,
    prune_resource_job_history,
    recover_stale_resource_jobs,
    recover_submitted_resource_jobs_without_monitor,
    update_resource_job,
)
from .providers.tmdb import (
    build_tmdb_task_binding,
    build_tmdb_aliases,
    build_tmdb_cache_key,
    build_tmdb_image_url,
    discover_tmdb_media,
    get_tmdb_genre_list,
    get_tmdb_media_detail,
    get_tmdb_popular,
    get_tmdb_runtime_config,
    get_tmdb_trending,
    infer_tmdb_episode_mode,
    normalize_tmdb_result_item,
    parse_tmdb_http_error,
    prune_tmdb_cache,
    search_tmdb_media,
    tmdb_request_json,
)
from .providers.pan115 import (
    create_115_folder,
    ensure_115_folder_id_by_path,
    invalidate_115_entries_cache,
    is_115_share_receive_duplicate_response,
    list_115_entries,
    list_115_entries_payload,
    list_115_folders,
    list_115_share_entries,
    load_115_share_page_cache,
    load_115_share_snap_cache,
    prepare_115_share_receive,
    resolve_115_folder_id_by_path,
    resolve_115_share_payload,
    sanitize_115_folder_name,
    save_115_share_page_cache,
    save_115_share_snap_cache,
    submit_115_offline_task,
    submit_115_share_receive,
    throttle_115_api_requests,
)
from .providers.quark import (
    create_quark_folder,
    ensure_quark_folder_id_by_path,
    http_request_json_payload,
    list_quark_entries,
    list_quark_entries_payload,
    list_quark_share_entries,
    list_quark_share_entries_fast,
    prepare_quark_share_save,
    probe_quark_connectivity,
    resolve_quark_folder_id_by_path,
    resolve_quark_share_payload,
    submit_quark_share_save,
)
from .providers.pansou import (
    PANSOU_SEARCH_TOTAL_LIMIT,
    request_pansou_search,
    test_pansou_health,
)
# 新网盘提供者 —— import 触发 register() 自注册
from .providers import tianyi  # noqa: F401
from .providers import pan123  # noqa: F401
from .providers import aliyun  # noqa: F401

































def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value or default).strip()))
    except Exception:
        return default
































































































def build_strm_play_url(cfg: Dict[str, Any], remote_path: str, pick_code: str = "") -> str:
    normalized_remote_path = normalize_remote_path(remote_path)
    query_payload: Dict[str, str] = {"path": normalized_remote_path}
    query = urllib.parse.urlencode(query_payload)
    proxy_base_url = str(cfg.get("strm_proxy_base_url", "")).strip().rstrip("/")
    if proxy_base_url:
        return f"{proxy_base_url}/strm/proxy?{query}"
    return f"/strm/proxy?{query}"


async def list_remote_dir(
    cfg: Dict[str, Any],
    remote_path: str,
    refresh: bool,
    task: Dict[str, Any],
) -> Tuple[str, List[Dict[str, Any]]]:
    cookie = str(cfg.get("cookie_115", "")).strip()
    if not cookie:
        raise RuntimeError("请先在参数配置中填写 115 Cookie")
    _, normalized_rel = resolve_provider_relative_path(cfg, remote_path, expected_provider="115")
    retries = task["retries"]
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            def load_entries() -> List[Dict[str, Any]]:
                cid = resolve_115_folder_id_by_path(cookie, normalized_rel) if normalized_rel else "0"
                return list_115_entries(cookie, cid, bool(refresh))

            entries = await asyncio.to_thread(load_entries)
            items: List[Dict[str, Any]] = []
            modified = ""
            for entry in entries:
                name = str(entry.get("name", "")).strip()
                if not name:
                    continue
                modified_at = str(entry.get("modified_at", "")).strip()
                if modified_at and (not modified or modified_at > modified):
                    modified = modified_at
                items.append(
                    {
                        "name": name,
                        "is_dir": bool(entry.get("is_dir")),
                        "modified": modified_at,
                        "size": int(entry.get("size", 0) or 0),
                        "pick_code": str(entry.get("pick_code", "")).strip(),
                    }
                )
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
    tree_source = str(tree.get("path", "")).strip()
    payload = {
        "source_type": normalize_tree_source_type(tree.get("source_type", "tree_file"), fallback="tree_file"),
        "path": tree_source,
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
