import asyncio
import contextvars
import hashlib
import json
import os
import re
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

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from .config_store import JsonConfigStore
from .db import (
    DB_PATH,
    ensure_db,
    ensure_parent,
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
    build_resource_search_text,
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
    fetch_telegram_channel_post_samples,
    fetch_telegram_channel_posts,
    fetch_telegram_channel_posts_page,
    format_network_error,
    get_tg_channel_threads,
    is_expected_telegram_channel_url,
    is_retryable_telegram_request_error,
    parse_telegram_posts_page,
    test_telegram_latency,
    unwrap_network_error,
)
from .runtime_files import (
    DEFAULT_EXTENSIONS,
    LOG_DIR,
    LOG_ROTATE_BACKUPS,
    LOG_ROTATE_MAX_BYTES,
    append_log_file,
    basename,
    clear_log_file,
    format_log_time,
    get_user_extensions,
    infer_log_level_from_text,
    is_video_file,
    join_relative_path,
    join_remote_path,
    normalize_relative_path,
    normalize_remote_path,
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

app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key="115-strm-v7-multi",
    https_only=False,
    same_site="lax",
)
app.add_middleware(
    GZipMiddleware,
    minimum_size=1024,
)
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
UI_PUSH_DEBOUNCE_SECONDS = 0.15
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
COOKIE_HEALTH_PROVIDERS: Tuple[str, ...] = ("115", "quark")
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
TMDB_API_BASE_URL = os.environ.get("TMDB_API_BASE_URL", "https://api.themoviedb.org/3").strip().rstrip("/")
TMDB_IMAGE_BASE_URL = os.environ.get("TMDB_IMAGE_BASE_URL", "https://image.tmdb.org/t/p").strip().rstrip("/")
TMDB_REQUEST_TIMEOUT_SECONDS = max(5, int(os.environ.get("TMDB_REQUEST_TIMEOUT_SECONDS", 20) or 20))
TMDB_SEARCH_LIMIT = max(1, min(20, int(os.environ.get("TMDB_SEARCH_LIMIT", 12) or 12)))
STATIC_DIR = os.path.join(BASE_DIR, "static")
FAVICON_PATH = os.path.join(STATIC_DIR, "icons", "favicon.svg")
USERSCRIPT_MAGNET_HELPER_PATH = os.path.join(BASE_DIR, "115-magnet-helper-webhook.user.js")
RESOURCE_SEASON_EPISODE_REGEX = re.compile(r"\bS(?:0|O)?(\d{1,2})\s*[-_. ]?\s*E(?:0|O)?(\d{1,3})\b", re.IGNORECASE)
RESOURCE_EPISODE_ONLY_REGEX = re.compile(r"(?:第\s*)(\d{1,3})\s*(?:集|話|话)\b", re.IGNORECASE)
RESOURCE_EPISODE_ONLY_CN_REGEX = re.compile(r"(?:第\s*)([零〇一二三四五六七八九十两兩]{1,4})\s*(?:集|話|话)\b", re.IGNORECASE)
RESOURCE_EPISODE_CODE_REGEX = re.compile(r"(?<!\d)(?:EP|E)\s*[-_. ]?\s*(\d{1,3})\b", re.IGNORECASE)
RESOURCE_EPISODE_RANGE_REGEXES = [
    re.compile(
        r"(?:第?\s*)([零〇一二三四五六七八九十两兩\d]{1,4})\s*[-~～—–－至到]\s*([零〇一二三四五六七八九十两兩\d]{1,4})\s*(?:集|話|话)?\b",
        re.IGNORECASE,
    ),
    re.compile(r"(?:EP|E)?\s*(\d{1,3})\s*[-~～—–－至到]\s*(?:EP|E)?\s*(\d{1,3})\b", re.IGNORECASE),
    re.compile(
        r"(?:更新至|更至|更新到|更到)\s*([零〇一二三四五六七八九十两兩\d]{1,4})\s*[-~～—–－至到]\s*([零〇一二三四五六七八九十两兩\d]{1,4})\s*(?:集|話|话)?\b",
        re.IGNORECASE,
    ),
]
RESOURCE_EPISODE_PROGRESS_REGEXES = [
    re.compile(r"(?:更新至|更至|更新到|更到|至|到)\s*([零〇一二三四五六七八九十两兩\d]{1,4})\s*(?:集|話|话)\b", re.IGNORECASE),
    re.compile(r"\b(?:EP|E)\s*[-_. ]?(\d{1,3})\s*(?:END|FIN)\b", re.IGNORECASE),
]
RESOURCE_SEASON_ONLY_REGEX = re.compile(r"(?:第\s*)(\d{1,2})\s*季\b", re.IGNORECASE)
RESOURCE_SEASON_ONLY_CN_REGEX = re.compile(r"(?:第\s*)([零〇一二三四五六七八九十两兩\d]{1,4})\s*季\b", re.IGNORECASE)
RESOURCE_SEASON_ENGLISH_REGEX = re.compile(r"\bSeason\s*(?:0|O)?(\d{1,2})\b", re.IGNORECASE)
RESOURCE_TOTAL_EPISODES_REGEXES = [
    re.compile(r"(?:全|共)\s*(\d{1,3})\s*(?:集|話|话)\b", re.IGNORECASE),
    re.compile(r"(\d{1,3})\s*(?:集|話|话)\s*(?:全|完结|完結)\b", re.IGNORECASE),
    re.compile(r"(?:更新至|更至)\s*(\d{1,3})\s*(?:集|話|话)\b", re.IGNORECASE),
]
RESOURCE_COLLECTION_HINT_REGEX = re.compile(
    r"(全集|完结|完結|合集|合輯|全\s*\d{1,3}\s*(?:集|話|话)|\d{1,3}\s*(?:集|話|话)\s*全)",
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
        "tmdb_enabled": False,
        "tmdb_api_key": "",
        "tmdb_language": "zh-CN",
        "tmdb_region": "CN",
        "tmdb_cache_ttl_hours": 24,
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
        "webhook_enabled": normalize_bool(task.get("webhook_enabled", False), default=False),
        "scan_path": normalize_remote_path(task.get("scan_path", "")),
        "target_path": normalize_relative_path(task.get("target_path", "")),
        "skip_by_dir_mtime": normalize_bool(task.get("skip_by_dir_mtime", False), default=False),
        "incremental": normalize_bool(task.get("incremental", False), default=False),
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


def normalize_subscription_provider(value: Any, fallback: str = "115") -> str:
    normalized_fallback = str(fallback or "115").strip().lower()
    normalized = str(value or "").strip().lower()
    if normalized in ("115", "quark"):
        return normalized
    if normalized in ("115share", "magnet", "magnet115"):
        return "115"
    if normalized in ("pan.quark", "quarkshare", "quark_pan"):
        return "quark"
    return "quark" if normalized_fallback == "quark" else "115"


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
    use_115_fixed_link = provider == "115" and share_link_type == "115share"
    if provider != "115":
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
    if provider != "115":
        share_link_receive_code = ""
        share_subdir = ""
        share_subdir_cid = ""
        fixed_link_channel_search = False
    if not share_subdir:
        share_subdir_cid = ""
    return {
        "name": name,
        "provider": provider,
        "media_type": media_type,
        "title": title,
        "aliases": aliases,
        "exclude_keywords": exclude_keywords,
        "year": year,
        "season": max(1, season),
        "total_episodes": max(0, total_episodes),
        "savepath": savepath,
        "share_link_url": share_link_url if use_115_fixed_link else "",
        "share_link_receive_code": share_link_receive_code if use_115_fixed_link else "",
        "share_subdir": share_subdir,
        "share_subdir_cid": share_subdir_cid,
        "fixed_link_channel_search": fixed_link_channel_search if use_115_fixed_link else False,
        "enabled": normalize_bool(task.get("enabled", True), default=True),
        # 兼容旧前端字段：cron_minutes 保留为“时段内查询间隔”镜像值。
        "cron_minutes": schedule_interval_minutes,
        "schedule_weekdays": schedule_weekdays,
        "schedule_start_time": schedule_start_time,
        "schedule_end_time": schedule_end_time,
        "schedule_interval_minutes": schedule_interval_minutes,
        "min_score": max(30, min(100, min_score)),
        "quality_priority": quality_priority,
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
    name = str(source.get("name", "")).strip()
    raw_channel_id = str(source.get("channel_id", "") or source.get("channel", "") or source.get("id", "")).strip()
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
        "enabled": normalize_bool(source.get("enabled", True), default=True),
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
    return merged


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
    build_subscription_candidate_text,
    build_subscription_query_tokens,
    build_subscription_text_tokens,
    compact_subscription_text,
    detect_resource_year,
    detect_subscription_resolution,
    evaluate_subscription_candidate_title_match,
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


def list_enabled_resource_channel_ids(sources: List[Dict[str, Any]]) -> Set[str]:
    channel_ids: Set[str] = set()
    for source in sources or []:
        if not source.get("enabled", True):
            continue
        channel_id = normalize_telegram_channel_id_from_input(source.get("channel_id", ""))
        if channel_id:
            channel_ids.add(channel_id)
    return channel_ids


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


def run_resource_cache_governance(conn: sqlite3.Connection, sources: List[Dict[str, Any]]) -> Dict[str, int]:
    active_channel_ids = list_enabled_resource_channel_ids(sources or [])
    inactive_pruned = prune_resource_inactive_channel_cache(conn, active_channel_ids, RESOURCE_CHANNEL_INACTIVE_CACHE_LIMIT)
    expired_pruned = prune_resource_cache_by_age(conn, RESOURCE_CHANNEL_CACHE_TTL_DAYS)
    global_pruned = prune_resource_cache_global_limit(
        conn,
        RESOURCE_CHANNEL_CACHE_GLOBAL_LIMIT,
        active_channel_ids,
        RESOURCE_CHANNEL_CACHE_ACTIVE_MIN_KEEP,
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
            if isinstance(source, dict)
        ]
        sample_limit = max(per_channel, RESOURCE_CHANNEL_TYPE_SAMPLE_SIZE)
        batch_channel_items, batch_channel_counts = list_resource_channel_items(channel_ids, limit_per_channel=sample_limit)
    for source in sources:
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
                "enabled": bool(source.get("enabled", True)),
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
    fetch_limit = max(target_limit, max(1, int(page_size or TG_SEARCH_PAGE_LIMIT)))

    for _ in range(max(1, int(max_pages or TG_SEARCH_MAX_PAGES))):
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
            if not resource_item_matches_search(post, keyword):
                continue
            identity = build_resource_item_identity_by_mode(post, identity_mode=normalized_identity_mode)
            if identity in seen_keys:
                continue
            seen_keys.add(identity)
            page_matches.append(post)

        remaining = max(0, target_limit - len(items))
        if page_matches and remaining > 0:
            items.extend(page_matches[:remaining])

        if incremental_stop_hit:
            next_before = ""
            has_more = False
            break

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
        "latest_scanned_cursor": latest_scanned_cursor,
        "latest_scanned_published_at": latest_scanned_published_at,
        "incremental_stop_hit": incremental_stop_hit,
    }


async def search_resource_sources(
    keyword: str,
    identity_mode: str = "message",
    incremental_since_cursor_by_channel: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    query = str(keyword or "").strip()
    normalized_identity_mode = normalize_resource_identity_mode(identity_mode, fallback="message")
    normalized_incremental_cursors: Dict[str, int] = {}
    if isinstance(incremental_since_cursor_by_channel, dict):
        for raw_channel_id, raw_cursor in incremental_since_cursor_by_channel.items():
            channel_id = normalize_telegram_channel_id_from_input(raw_channel_id)
            if not channel_id:
                continue
            normalized_incremental_cursors[channel_id] = max(0, int(raw_cursor or 0))
    cfg = get_config()
    sources = [normalize_resource_source(source or {}) for source in cfg.get("resource_sources", []) if source.get("enabled")]
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
            "incremental_stop_channels": 0,
            "channel_watermarks": {},
            "channel_stats": [],
        }

    semaphore = asyncio.Semaphore(tg_channel_threads)

    async def search_one_source(source: Dict[str, Any]) -> Dict[str, Any]:
        channel_id = normalize_telegram_channel_id_from_input(source.get("channel_id", ""))
        stop_cursor = max(0, int(normalized_incremental_cursors.get(channel_id, 0) or 0))
        started_at = time.perf_counter()
        try:
            async with semaphore:
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        search_telegram_channel_resource_items,
                        cfg,
                        source,
                        query,
                        TG_SEARCH_MATCH_LIMIT_PER_CHANNEL,
                        TG_SEARCH_MAX_PAGES,
                        TG_SEARCH_PAGE_LIMIT,
                        "",
                        normalized_identity_mode,
                        stop_cursor,
                        TG_SEARCH_REQUEST_TIMEOUT_SECONDS,
                        TG_SEARCH_RETRY_ATTEMPTS,
                    ),
                    timeout=TG_SEARCH_CHANNEL_TIMEOUT_SECONDS,
                )
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
    results = await asyncio.gather(*tasks, return_exceptions=True)

    items: List[Dict[str, Any]] = []
    sections: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    channel_stats: List[Dict[str, Any]] = []
    matched_channels = 0
    pages_scanned = 0
    incremental_stop_channels = 0
    channel_watermarks: Dict[str, Dict[str, Any]] = {}

    for source, result in zip(sources, results):
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
                    "enabled": True,
                    "items": channel_items,
                    "item_count": len(channel_items),
                    "next_before": str(result.get("next_before", "") or "").strip(),
                    "has_more": bool(result.get("has_more")),
                    "pages_scanned": int(result.get("pages_scanned", 0) or 0),
                }
            )

    deduped_items = dedupe_resource_item_dicts(items, identity_mode=normalized_identity_mode)
    deduped_items.sort(key=get_resource_item_sort_key, reverse=True)
    return {
        "items": deduped_items[: max(1, int(TG_SEARCH_TOTAL_LIMIT or 60))],
        "sections": sections,
        "errors": errors,
        "searched_sources": len(sources),
        "matched_channels": matched_channels,
        "pages_scanned": pages_scanned,
        "thread_limit": tg_channel_threads,
        "incremental_stop_channels": incremental_stop_channels,
        "channel_watermarks": channel_watermarks,
        "channel_stats": channel_stats,
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
    main_lines = read_log_tail(MAIN_LOG_PATH, limit=500)
    if main_lines:
        task_status["logs"] = [
            {"text": line, "level": infer_log_level_from_text(line)}
            for line in main_lines
        ]

    monitor_lines = read_log_tail(MONITOR_LOG_PATH, limit=800)
    if monitor_lines:
        monitor_status["logs"] = [
            {"text": line, "level": infer_log_level_from_text(line)}
            for line in monitor_lines
        ]

    subscription_lines = read_log_tail(SUBSCRIPTION_LOG_PATH, limit=800)
    if subscription_lines:
        subscription_status["logs"] = [
            {"text": line, "level": infer_log_level_from_text(line)}
            for line in subscription_lines
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
    if provider == "quark":
        if not str(cfg.get("cookie_quark", "")).strip():
            return "请先在参数配置中填写 Quark Cookie"
    elif not str(cfg.get("cookie_115", "")).strip():
        return "请先在参数配置中填写 115 Cookie"
    if not str(task.get("name", "")).strip():
        return "任务名未填写"
    if not str(task.get("title", "")).strip():
        return "订阅影视名称未填写"
    if not str(task.get("savepath", "")).strip():
        return "保存路径未填写"
    media_type = str(task.get("media_type", "movie") or "movie").strip().lower()
    if media_type not in ("movie", "tv"):
        return "订阅类型不支持"
    if provider not in ("115", "quark"):
        return "订阅网盘类型不支持"
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
    "summary": {"step": "空闲", "detail": "等待监控任务"},
}
monitor_control = {"cancel": False}
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
subscription_queue: List[Dict[str, Any]] = []
subscription_last_run: Dict[str, float] = {}
subscription_next_run: Dict[str, str] = {}
subscription_log_context_var: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar(
    "subscription_log_context",
    default=None,
)
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
ui_event_loop: Optional[asyncio.AbstractEventLoop] = None
ui_push_pending = False
ui_push_task: Optional[asyncio.Task] = None
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
    "started_at": "",
    "started_ts": 0.0,
    "finished_at": "",
    "finished_ts": 0.0,
    "duration_ms": 0,
    "last_updated_at": "",
    "last_result": {},
    "last_error": "",
}
RESOURCE_JOB_RECOVERY_INTERVAL_SECONDS = max(
    5,
    min(300, int(os.environ.get("RESOURCE_JOB_RECOVERY_INTERVAL_SECONDS", 20) or 20)),
)
resource_job_recovery_lock = threading.Lock()
resource_job_recovery_last_ts = 0.0


def normalize_cookie_health_provider(value: Any) -> str:
    token = str(value or "").strip().lower()
    if token in {"115", "cookie_115"}:
        return "115"
    if token in {"quark", "cookie_quark"}:
        return "quark"
    return ""


def is_cookie_health_share_trigger(trigger: Any) -> bool:
    token = str(trigger or "").strip().lower()
    return any(token.startswith(prefix) for prefix in COOKIE_HEALTH_SHARE_TRIGGER_PREFIXES)


def _cookie_health_provider_label(provider: str) -> str:
    return "Quark" if normalize_cookie_health_provider(provider) == "quark" else "115"


def _cookie_health_cookie_value(cfg: Dict[str, Any], provider: str) -> str:
    key = "cookie_quark" if normalize_cookie_health_provider(provider) == "quark" else "cookie_115"
    return str((cfg or {}).get(key, "") or "").strip()


def _cookie_health_missing_message(provider: str) -> str:
    return f"未配置 {_cookie_health_provider_label(provider)} Cookie"


def _cookie_health_unknown_message(provider: str) -> str:
    return f"已配置 {_cookie_health_provider_label(provider)} Cookie，等待检测"


def _cookie_health_valid_message(provider: str) -> str:
    return f"{_cookie_health_provider_label(provider)} Cookie 可用"


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
        return "error", detail
    return "error", detail


def sync_cookie_health_configured(cfg: Optional[Dict[str, Any]] = None, trigger: str = "sync") -> None:
    active_cfg = cfg or get_config()
    changed = False
    with cookie_health_lock:
        for provider in COOKIE_HEALTH_PROVIDERS:
            entry = _ensure_cookie_health_entry_locked(provider)
            if not entry:
                continue
            configured = bool(_cookie_health_cookie_value(active_cfg, provider))
            if not configured:
                changed = _set_cookie_health_entry_locked(
                    provider,
                    configured=False,
                    state="missing",
                    message=_cookie_health_missing_message(provider),
                    trigger=str(trigger or "").strip(),
                    fail_count=0,
                ) or changed
                continue
            if not entry.get("configured", False):
                changed = _set_cookie_health_entry_locked(provider, configured=True) or changed
            state = str(entry.get("state", "") or "").strip().lower()
            if state in {"", "missing"}:
                changed = _set_cookie_health_entry_locked(
                    provider,
                    configured=True,
                    state="unknown",
                    message=_cookie_health_unknown_message(provider),
                    trigger=str(trigger or "").strip(),
                ) or changed
            elif not entry.get("configured", False):
                changed = _set_cookie_health_entry_locked(provider, configured=True) or changed
    if changed:
        schedule_ui_state_push(0)


def mark_cookie_health_checking(provider: str, trigger: str = "manual_check") -> None:
    provider_key = normalize_cookie_health_provider(provider)
    if not provider_key:
        return
    if is_cookie_health_share_trigger(trigger):
        return
    cfg = get_config()
    configured = bool(_cookie_health_cookie_value(cfg, provider_key))
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
    configured = bool(_cookie_health_cookie_value(cfg, provider_key))
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
    configured = bool(_cookie_health_cookie_value(cfg, provider_key))
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
        for provider in COOKIE_HEALTH_PROVIDERS:
            entry = _ensure_cookie_health_entry_locked(provider)
            payload[provider] = {
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
    headers = {
        "Cookie": normalized_cookie,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://115.com/",
        "User-Agent": "Mozilla/5.0 115-media-hub",
    }
    url = "https://aps.115.com/natsort/files.php?aid=1&cid=0&offset=0&limit=1&show_dir=1&natsort=1&format=json"
    result = http_request_json(url, extra_headers=headers, timeout=20)
    if not bool((result or {}).get("state", False)):
        detail = (
            str((result or {}).get("error", "")).strip()
            or str((result or {}).get("msg", "")).strip()
            or str((result or {}).get("message", "")).strip()
            or "115 Cookie 检测失败"
        )
        raise RuntimeError(detail)


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
    raw_items = providers if isinstance(providers, list) else COOKIE_HEALTH_PROVIDERS
    if providers is None:
        raw_items = list(COOKIE_HEALTH_PROVIDERS)
    normalized: List[str] = []
    for item in raw_items:
        provider = normalize_cookie_health_provider(item)
        if (not provider) or provider in normalized:
            continue
        normalized.append(provider)
    return normalized or list(COOKIE_HEALTH_PROVIDERS)


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
        cookie_value = _cookie_health_cookie_value(cfg, provider)
        if not cookie_value:
            mark_cookie_health_failure(provider, _cookie_health_missing_message(provider), trigger=trigger, force=True)
            continue

        with cookie_health_lock:
            runtime_payload = cookie_health_runtime.get(provider, {"last_checked_ts": 0.0, "last_success_ts": 0.0})
            last_checked_ts = float(runtime_payload.get("last_checked_ts", 0.0) or 0.0)
        if (not force) and last_checked_ts > 0 and (now_ts - last_checked_ts) < COOKIE_HEALTH_MIN_REFRESH_INTERVAL_SECONDS:
            continue

        mark_cookie_health_checking(provider, trigger=trigger)
        try:
            if provider == "quark":
                await asyncio.to_thread(_probe_quark_cookie, cookie_value)
            else:
                await asyncio.to_thread(_probe_115_cookie, cookie_value)
            mark_cookie_health_success(provider, trigger=trigger, force=True)
        except Exception as exc:
            mark_cookie_health_failure(provider, exc, trigger=trigger, force=True)

    return build_cookie_health_payload(cfg)


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


def build_subscription_status_payload(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = cfg or get_config()
    return {
        "running": bool(subscription_status["running"]),
        "current_task": str(subscription_status.get("current_task", "")),
        "queued": clone_jsonable(subscription_status.get("queued", [])),
        "logs": clone_jsonable(subscription_status.get("logs", [])),
        "summary": clone_jsonable(subscription_status.get("summary", {})),
        "tasks": clone_jsonable(list_subscription_task_runtime(cfg)),
        "next_runs": clone_jsonable(subscription_next_run),
    }


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


def build_ui_state_payload(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    active_cfg = cfg or get_config()
    return {
        "main": build_main_status_payload(),
        "monitor": build_monitor_status_payload(active_cfg),
        "subscription": build_subscription_status_payload(active_cfg),
        "sign115": build_sign115_status_payload(active_cfg),
        "cookie_health": build_cookie_health_payload(active_cfg),
        "resource_channel_sync": build_resource_channel_sync_payload(),
    }


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
        schedule_ui_state_push(0)


def build_resource_channel_sync_payload() -> Dict[str, Any]:
    with resource_channel_sync_status_lock:
        return clone_jsonable(resource_channel_sync_status)


def build_resource_jobs_state_payload(limit: int = 20, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    active_cfg = cfg or get_config()
    jobs_page = list_resource_jobs_page(limit=limit, offset=0, status_filter="")
    jobs = jobs_page.get("jobs", [])
    counts = count_resource_jobs_by_status()
    active_jobs_page = list_resource_jobs_page(limit=80, offset=0, status_filter="active")
    return {
        "jobs": clone_jsonable(jobs),
        "active_jobs": clone_jsonable(active_jobs_page.get("jobs", [])),
        "monitor_tasks": clone_jsonable(active_cfg.get("monitor_tasks", [])),
        "pagination": clone_jsonable(jobs_page.get("pagination", {})),
        "job_counts": clone_jsonable(counts),
        "stats": {
            "total_job_count": int(counts.get("total", 0) or 0),
            "active_job_count": int(counts.get("active", 0) or 0),
            "completed_job_count": int(counts.get("completed", 0) or 0),
            "failed_job_count": int(counts.get("failed", 0) or 0),
        },
    }


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

    return {
        "skipped": False,
        "stale": recover_stale_resource_jobs(),
        "submitted_without_monitor": recover_submitted_resource_jobs_without_monitor(),
        "history_pruned": prune_resource_job_history(),
    }


def _build_resource_state_payload_snapshot(
    cfg: Dict[str, Any],
    keyword: str,
    search_meta: Dict[str, Any],
) -> Dict[str, Any]:
    keyword = str(keyword or "").strip()
    items = search_meta.get("items", []) if keyword else []
    search_sections = search_meta.get("sections", []) if keyword else []
    jobs_state = build_resource_jobs_state_payload(limit=20, cfg=cfg)
    jobs = jobs_state.get("jobs", [])
    active_jobs = jobs_state.get("active_jobs", [])
    job_counts = jobs_state.get("job_counts", {})
    job_pagination = jobs_state.get("pagination", {})
    total_item_count = count_resource_items(source_type="tg")
    filtered_item_count = len(items)
    stats_payload = jobs_state.get("stats", {})
    total_job_count = int(stats_payload.get("total_job_count", 0) or 0)
    active_job_count = int(stats_payload.get("active_job_count", 0) or 0)
    completed_job_count = int(stats_payload.get("completed_job_count", 0) or 0)
    failed_job_count = int(stats_payload.get("failed_job_count", 0) or 0)
    sources = cfg.get("resource_sources", [])
    channel_ids = [
        normalize_telegram_channel_id_from_input((source or {}).get("channel_id", ""))
        for source in (sources if isinstance(sources, list) else [])
        if isinstance(source, dict)
    ]
    channel_ids = [channel_id for channel_id in channel_ids if channel_id]
    subscription_channel_support = load_subscription_channel_support_stats(channel_ids)
    enabled_sources = [source for source in sources if source.get("enabled")]
    channel_sections = build_resource_channel_sections(sources, per_channel=10)
    channel_profiles = {
        str(section.get("channel_id", "")).strip(): section.get("channel_profile", {})
        for section in channel_sections
        if str(section.get("channel_id", "")).strip()
    }
    return {
        "sources": clone_jsonable(sources),
        "quick_links": clone_jsonable(cfg.get("resource_quick_links", [])),
        "items": clone_jsonable(items),
        "jobs": clone_jsonable(jobs),
        "active_jobs": clone_jsonable(active_jobs),
        "job_counts": clone_jsonable(job_counts),
        "pagination": clone_jsonable(job_pagination),
        "monitor_tasks": clone_jsonable(cfg.get("monitor_tasks", [])),
        "cookie_configured": bool(str(cfg.get("cookie_115", "")).strip()),
        "quark_cookie_configured": bool(str(cfg.get("cookie_quark", "")).strip()),
        "cookie_health": build_cookie_health_payload(cfg),
        "setup_status": {
            "strm_ready": bool(
                str(cfg.get("cookie_115", "")).strip() and str(cfg.get("strm_proxy_base_url", "")).strip()
            ),
            "cookie_configured": bool(str(cfg.get("cookie_115", "")).strip()),
            "quark_cookie_configured": bool(str(cfg.get("cookie_quark", "")).strip()),
            "has_sources": bool(enabled_sources),
            "has_monitor": bool(cfg.get("monitor_tasks", [])),
            "has_resource_data": total_item_count > 0,
            "has_jobs": bool(jobs),
        },
        "search": keyword,
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
            }
        ),
        "stats": {
            "source_count": len(enabled_sources),
            "item_count": total_item_count,
            "filtered_item_count": filtered_item_count,
            "total_job_count": total_job_count,
            "active_job_count": active_job_count,
            "completed_job_count": completed_job_count,
            "failed_job_count": failed_job_count,
        },
    }


async def build_resource_state_payload(search: str = "") -> Dict[str, Any]:
    cfg = get_config()
    await asyncio.to_thread(recover_resource_jobs_if_due)
    keyword = str(search or "").strip()
    search_meta = await search_resource_sources(keyword) if keyword else {
        "items": [],
        "sections": [],
        "errors": [],
        "searched_sources": len([source for source in cfg.get("resource_sources", []) if source.get("enabled")]),
        "matched_channels": 0,
        "pages_scanned": 0,
    }
    return await asyncio.to_thread(_build_resource_state_payload_snapshot, cfg, keyword, search_meta)


async def sync_telegram_channels(force: bool = False, limit_per_channel: int = 10) -> Dict[str, Any]:
    cfg = get_config()
    sources = [source for source in cfg.get("resource_sources", []) if source.get("enabled")]
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
        return {
            "ok": True,
            "synced": 0,
            "items": 0,
            "skipped": 0,
            "errors": [],
            "cache_pruned": cache_pruned,
            "cache_prune_detail": cache_prune_detail,
        }

    ensure_db()
    tg_channel_threads = get_tg_channel_threads(cfg)
    semaphore = asyncio.Semaphore(tg_channel_threads)
    synced_channels = 0
    upserted_items = 0
    skipped_channels = 0
    per_channel_pruned = 0
    errors: List[Dict[str, str]] = []
    targets: List[Tuple[Dict[str, Any], str]] = []
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
        targets.append((source, channel_id))

    async def fetch_one_source(source: Dict[str, Any], channel_id: str) -> Dict[str, Any]:
        source_name = str(source.get("name", "") or channel_id).strip()
        try:
            async with semaphore:
                sample_bundle = await asyncio.to_thread(
                    fetch_telegram_channel_post_samples,
                    cfg,
                    source,
                    max(limit_per_channel, RESOURCE_CHANNEL_TYPE_SAMPLE_SIZE),
                    max(limit_per_channel, RESOURCE_CHANNEL_TYPE_PAGE_LIMIT),
                    RESOURCE_CHANNEL_TYPE_MAX_PAGES,
                )
                posts = sample_bundle.get("posts", []) if isinstance(sample_bundle, dict) else []
                if not posts:
                    posts = await asyncio.to_thread(fetch_telegram_channel_posts, cfg, source, limit_per_channel)
            return {"channel_id": channel_id, "name": source_name, "posts": posts}
        except Exception as exc:
            return {"channel_id": channel_id, "name": source_name, "error": str(exc)}
        finally:
            resource_channel_syncing.discard(channel_id)

    results = await asyncio.gather(*(fetch_one_source(source, channel_id) for source, channel_id in targets))

    conn = open_db()
    try:
        for result in results:
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
            per_channel_pruned += prune_resource_channel_cache(conn, channel_id)
            conn.commit()
            resource_channel_last_sync[channel_id] = time.time()
            resource_channel_last_error.pop(channel_id, None)
            synced_channels += 1
        governance_detail = run_resource_cache_governance(conn, sources)
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
    finally:
        conn.close()

    return {
        "ok": not errors,
        "synced": synced_channels,
        "items": upserted_items,
        "skipped": skipped_channels,
        "errors": errors,
        "cache_pruned": cache_pruned,
        "cache_prune_detail": cache_prune_detail,
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
            cfg = get_config()
            payload = json.dumps(build_ui_state_payload(cfg), ensure_ascii=False)
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
    task_status["logs"].append({"text": line, "level": resolved_level})
    if len(task_status["logs"]) > 500:
        task_status["logs"].pop(0)
    schedule_ui_state_push()
    await asyncio.to_thread(append_log_file, MAIN_LOG_PATH, line)
    await asyncio.sleep(0)


async def write_monitor_log(text: str, level: str = "info") -> None:
    resolved_level = str(level or infer_log_level_from_text(text)).strip().lower() or "info"
    line = f"{format_log_time(True)} {text}"
    monitor_status["logs"].append({"text": line, "level": resolved_level})
    if len(monitor_status["logs"]) > 800:
        monitor_status["logs"].pop(0)
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


async def write_subscription_log(text: str, level: str = "info") -> None:
    resolved_level = str(level or infer_log_level_from_text(text)).strip().lower() or "info"
    timestamp = format_log_time(True)
    line = f"{timestamp} {text}"
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
    subscription_status["logs"].append({"text": line, "level": resolved_level, "event": event_payload})
    if len(subscription_status["logs"]) > 800:
        subscription_status["logs"].pop(0)
    schedule_ui_state_push()
    try:
        await asyncio.to_thread(append_log_file, SUBSCRIPTION_LOG_PATH, line)
        await asyncio.to_thread(append_log_file, SUBSCRIPTION_EVENT_LOG_PATH, safe_json_dumps(event_payload))
    except Exception as exc:
        # 日志写盘失败不应中断主流程，保留内存日志并继续执行任务。
        fallback_line = f"{format_log_time(True)} [WARN] 订阅日志写盘失败：{str(exc)[:180]}"
        subscription_status["logs"].append({"text": fallback_line, "level": "warn"})
        if len(subscription_status["logs"]) > 800:
            subscription_status["logs"].pop(0)
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
    return "夸克" if normalized == "quark" else "115"


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


def check_subscription_cancelled() -> None:
    if subscription_control["cancel"]:
        raise asyncio.CancelledError()


async def sleep_interruptible(seconds: float) -> None:
    end_at = time.time() + max(0, seconds)
    while time.time() < end_at:
        check_monitor_cancelled()
        await asyncio.sleep(min(0.5, end_at - time.time()))


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
    delete_resource_item,
    find_existing_resource_job,
    get_resource_job,
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
    get_tmdb_media_detail,
    get_tmdb_runtime_config,
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

































def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value or default).strip()))
    except Exception:
        return default
































































































def build_strm_play_url(cfg: Dict[str, Any], remote_path: str, pick_code: str = "") -> str:
    normalized_remote_path = normalize_remote_path(remote_path)
    query_payload: Dict[str, str] = {"path": normalized_remote_path}
    normalized_pick_code = normalize_115_pick_code(pick_code)
    if normalized_pick_code:
        query_payload["pickcode"] = normalized_pick_code
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
