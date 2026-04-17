import asyncio
import hashlib
import json
import os
import re
import shutil
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
SUBSCRIPTION_LOG_PATH = os.path.join(LOG_DIR, "subscription.log")
DEFAULT_EXTENSIONS = "mp4,mkv,avi,mov,wmv,flv,webm,vob,mpg,mpeg,ts,m2ts,mts,rmvb,rm,asf,3gp,m4v,f4v,iso"
LEGACY_DEFAULT_EXTENSIONS = "mp4,mkv,avi,mov,ts,iso,rmvb,wmv,m4v,mpg,flac,mp3,ass,srt"
MAX_MONITOR_RETRIES = 5
SUBSCRIPTION_MIN_SCORE = 55
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
VERSION_FILE = os.path.join(BASE_DIR, "version.json")
VERSION_SOURCE_URL = os.environ.get(
    "VERSION_SOURCE_URL",
    "https://raw.githubusercontent.com/xianer235/115-media-hub/main/version.json",
)
VERSION_CACHE_TTL = int(os.environ.get("VERSION_CACHE_TTL", 6 * 3600))
UI_EVENT_RETRY_MS = 3000
UI_HEARTBEAT_SECONDS = 15
UI_PUSH_DEBOUNCE_SECONDS = 0.15
TG_SYNC_TTL_SECONDS = 5 * 60
RESOURCE_CHANNEL_TYPE_SAMPLE_SIZE = max(20, int(os.environ.get("RESOURCE_CHANNEL_TYPE_SAMPLE_SIZE", 50) or 50))
RESOURCE_CHANNEL_TYPE_PAGE_LIMIT = max(10, int(os.environ.get("RESOURCE_CHANNEL_TYPE_PAGE_LIMIT", 20) or 20))
RESOURCE_CHANNEL_TYPE_MAX_PAGES = max(1, int(os.environ.get("RESOURCE_CHANNEL_TYPE_MAX_PAGES", 6) or 6))
RESOURCE_CHANNEL_CACHE_LIMIT = max(RESOURCE_CHANNEL_TYPE_SAMPLE_SIZE, int(os.environ.get("RESOURCE_CHANNEL_CACHE_LIMIT", 60) or 60))
RESOURCE_CHANNEL_CACHE_GLOBAL_LIMIT = max(
    RESOURCE_CHANNEL_CACHE_LIMIT,
    int(os.environ.get("RESOURCE_CHANNEL_CACHE_GLOBAL_LIMIT", 2000) or 2000),
)
SHARE_SNAP_RATE_LIMIT_SECONDS = max(
    0.2,
    min(5.0, float(os.environ.get("SHARE_SNAP_RATE_LIMIT_SECONDS", 1.0) or 1.0)),
)
SHARE_SNAP_CACHE_TTL_SECONDS = max(
    10,
    min(24 * 3600, int(os.environ.get("SHARE_SNAP_CACHE_TTL_SECONDS", 5 * 60) or (5 * 60))),
)
SHARE_SNAP_CACHE_MAX_ROWS = max(
    200,
    int(os.environ.get("SHARE_SNAP_CACHE_MAX_ROWS", 3000) or 3000),
)
_share_snap_rate_limit_lock = threading.Lock()
_share_snap_last_request_monotonic = 0.0
RESOURCE_CHANNEL_CACHE_ACTIVE_MIN_KEEP = max(
    0,
    min(RESOURCE_CHANNEL_CACHE_LIMIT, int(os.environ.get("RESOURCE_CHANNEL_CACHE_ACTIVE_MIN_KEEP", 10) or 10)),
)
RESOURCE_CHANNEL_INACTIVE_CACHE_LIMIT = max(0, int(os.environ.get("RESOURCE_CHANNEL_INACTIVE_CACHE_LIMIT", 5) or 5))
RESOURCE_CHANNEL_CACHE_TTL_DAYS = max(0, int(os.environ.get("RESOURCE_CHANNEL_CACHE_TTL_DAYS", 30) or 30))
TG_SEARCH_PAGE_LIMIT = max(10, int(os.environ.get("TG_SEARCH_PAGE_LIMIT", 20) or 20))
TG_SEARCH_MAX_PAGES = max(1, int(os.environ.get("TG_SEARCH_MAX_PAGES", 6) or 6))
TG_SEARCH_MATCH_LIMIT_PER_CHANNEL = max(1, int(os.environ.get("TG_SEARCH_MATCH_LIMIT_PER_CHANNEL", 12) or 12))
TG_SEARCH_TOTAL_LIMIT = max(TG_SEARCH_MATCH_LIMIT_PER_CHANNEL, int(os.environ.get("TG_SEARCH_TOTAL_LIMIT", 60) or 60))
TG_SEARCH_CHANNEL_TIMEOUT_SECONDS = max(5, int(os.environ.get("TG_SEARCH_CHANNEL_TIMEOUT_SECONDS", 15) or 15))
TG_CHANNEL_THREADS_MAX = 20
TG_CHANNEL_THREADS_DEFAULT = max(1, min(TG_CHANNEL_THREADS_MAX, int(os.environ.get("TG_CHANNEL_THREADS_DEFAULT", 6) or 6)))
TG_FETCH_RETRY_ATTEMPTS = max(1, int(os.environ.get("TG_FETCH_RETRY_ATTEMPTS", 3) or 3))
RESOURCE_QUICK_LINKS_LIMIT = 60
TG_FETCH_RETRY_DELAY_SECONDS = max(0.2, float(os.environ.get("TG_FETCH_RETRY_DELAY_SECONDS", 0.8) or 0.8))
RESOURCE_IMPORT_TIMEOUT_SECONDS = max(10, min(900, int(os.environ.get("RESOURCE_IMPORT_TIMEOUT_SECONDS", 90) or 90)))
RESOURCE_JOB_STALE_RECOVER_SECONDS = max(
    30,
    min(7 * 24 * 3600, int(os.environ.get("RESOURCE_JOB_STALE_RECOVER_SECONDS", 300) or 300)),
)
TMDB_API_BASE_URL = os.environ.get("TMDB_API_BASE_URL", "https://api.themoviedb.org/3").strip().rstrip("/")
TMDB_IMAGE_BASE_URL = os.environ.get("TMDB_IMAGE_BASE_URL", "https://image.tmdb.org/t/p").strip().rstrip("/")
TMDB_REQUEST_TIMEOUT_SECONDS = max(5, int(os.environ.get("TMDB_REQUEST_TIMEOUT_SECONDS", 20) or 20))
TMDB_SEARCH_LIMIT = max(1, min(20, int(os.environ.get("TMDB_SEARCH_LIMIT", 12) or 12)))
STATIC_DIR = os.path.join(BASE_DIR, "static")
FAVICON_PATH = os.path.join(STATIC_DIR, "icons", "favicon.svg")
USERSCRIPT_MAGNET_HELPER_PATH = os.path.join(BASE_DIR, "115-magnet-helper-webhook.user.js")
RESOURCE_MAGNET_REGEX = re.compile(r"magnet:\?xt=urn:btih:[A-Za-z0-9]{32,40}[^\s<>'\"]*", re.IGNORECASE)
RESOURCE_MAGNET_HASH_REGEX = re.compile(r"xt=urn:btih:([A-Za-z0-9]{32,40})", re.IGNORECASE)
RESOURCE_ED2K_REGEX = re.compile(r"ed2k://[^\s<>'\"]+", re.IGNORECASE)
RESOURCE_URL_REGEX = re.compile(r"https?://[^\s<>'\"]+", re.IGNORECASE)
RESOURCE_115_SHARE_URL_REGEX = re.compile(
    r"(?:https?://)?(?:115cdn|115|anxia)\.com/s/[A-Za-z0-9]+(?:\?[^\s<>'\"]*)?",
    re.IGNORECASE,
)
RESOURCE_115_SHARE_BARE_URL_REGEX = re.compile(
    r"(?:115cdn|115|anxia)\.com/s/[A-Za-z0-9]+(?:\?[^\s<>'\"]*)?",
    re.IGNORECASE,
)
RESOURCE_YEAR_REGEX = re.compile(r"\b(19\d{2}|20\d{2})\b")
RESOURCE_LINK_TYPE_PATTERNS: List[Tuple[str, re.Pattern[str]]] = [
    ("115share", re.compile(r"https?://(?:115cdn|115|anxia)\.com/s/[a-z0-9]+", re.IGNORECASE)),
    ("aliyun", re.compile(r"https?://(?:www\.)?(?:aliyundrive|alipan)\.com/s/[a-z0-9]+", re.IGNORECASE)),
    ("quark", re.compile(r"https?://(?:pan|www)\.quark\.cn/s/[a-z0-9]+", re.IGNORECASE)),
    ("baidu", re.compile(r"https?://(?:pan|yun)\.baidu\.com/(?:s/|share/)", re.IGNORECASE)),
    ("xunlei", re.compile(r"https?://(?:pan|xlpan)\.xunlei\.com/s/[a-z0-9]+", re.IGNORECASE)),
    ("uc", re.compile(r"https?://drive\.uc\.cn/s/[a-z0-9]+", re.IGNORECASE)),
    ("123pan", re.compile(r"https?://(?:www\.)?(?:123pan|123684|123865|123912)\.(?:com|cn)/s/[a-z0-9]+", re.IGNORECASE)),
    ("tianyi", re.compile(r"https?://cloud\.189\.cn/(?:t/|web/share)", re.IGNORECASE)),
    ("pikpak", re.compile(r"https?://(?:www\.)?(?:mypikpak|pikpak)\.com/s/[a-z0-9]+", re.IGNORECASE)),
    ("lanzou", re.compile(r"https?://(?:www\.)?lanzou[a-z0-9]*\.[a-z.]+/[a-z0-9]+", re.IGNORECASE)),
    ("google_drive", re.compile(r"https?://drive\.google\.com/", re.IGNORECASE)),
    ("onedrive", re.compile(r"https?://(?:1drv\.ms|onedrive\.live\.com)/", re.IGNORECASE)),
    ("mega", re.compile(r"https?://mega\.nz/", re.IGNORECASE)),
]
TG_WIDGET_POST_REGEX = re.compile(r'<div[^>]+class="tgme_widget_message[^"]*"[^>]+data-post="([^"]+)"[^>]*>', re.IGNORECASE)
TG_LINK_HREF_REGEX = re.compile(r'href="([^"]+)"', re.IGNORECASE)
TG_IMAGE_STYLE_REGEX = re.compile(r"background-image:url\('([^']+)'\)", re.IGNORECASE)
TG_PREV_BEFORE_REGEX = re.compile(r'rel="prev"[^>]+href="[^"]*before=([^"&]+)', re.IGNORECASE)
TG_EXTRACT_CODE_REGEX = re.compile(
    r"(?:提取码|提取碼|访问码|訪問碼|密码|密碼|访问密码|訪問密碼|口令|pwd|pass(?:word|code)?|code)\s*(?:[:：=]|是|为|為)?\s*([A-Za-z0-9]{4,8})\b",
    re.IGNORECASE,
)
RESOURCE_SEASON_EPISODE_REGEX = re.compile(r"\bS(?:0|O)?(\d{1,2})\s*[-_. ]?\s*E(?:0|O)?(\d{1,3})\b", re.IGNORECASE)
RESOURCE_EPISODE_ONLY_REGEX = re.compile(r"(?:第\s*)(\d{1,3})\s*(?:集|話|话)\b", re.IGNORECASE)
RESOURCE_EPISODE_CODE_REGEX = re.compile(r"\b(?:EP|E)\s*[-_. ]?\s*(\d{1,3})\b", re.IGNORECASE)
RESOURCE_EPISODE_RANGE_REGEXES = [
    re.compile(r"(?:第?\s*)(\d{1,3})\s*[-~～—–－至到]\s*(\d{1,3})\s*(?:集|話|话)\b", re.IGNORECASE),
    re.compile(r"(?:EP|E)?\s*(\d{1,3})\s*[-~～—–－至到]\s*(?:EP|E)?\s*(\d{1,3})\b", re.IGNORECASE),
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

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def ensure_parent(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)


def default_config() -> Dict[str, Any]:
    return {
        "username": "admin",
        "password": "admin123",
        "webhook_secret": "",
        "alist_url": "",
        "alist_token": "",
        "cookie_115": "",
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
        "mount_path": "/115",
        "extensions": DEFAULT_EXTENSIONS,
        "trees": [{"url": "", "prefix": "", "exclude": 1}],
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


def normalize_subscription_quality_priority(value: Any) -> str:
    key = str(value or "").strip().lower()
    normalized = SUBSCRIPTION_QUALITY_PRIORITY_ALIASES.get(key, key)
    if normalized not in SUBSCRIPTION_QUALITY_PRIORITY_ORDERS:
        return SUBSCRIPTION_QUALITY_PRIORITY_DEFAULT
    return normalized


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


def normalize_subscription_schedule_interval_minutes(value: Any, fallback: int = 30) -> int:
    try:
        interval = int(value if value is not None else fallback)
    except (TypeError, ValueError):
        interval = int(fallback or 30)
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
    if not is_subscription_multi_season_mode(payload):
        return normalized_base

    parts = [part for part in normalized_base.split("/") if part]
    if len(parts) <= 1:
        return normalized_base
    if not is_subscription_season_folder_name(parts[-1]):
        return normalized_base

    parent_path = "/".join(parts[:-1]).strip("/")
    return parent_path or normalized_base


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


def normalize_subscription_task(task: Dict[str, Any]) -> Dict[str, Any]:
    media_type = str(task.get("media_type", "") or task.get("type", "movie")).strip().lower()
    if media_type not in ("movie", "tv"):
        media_type = "movie"
    title = str(task.get("title", "")).strip()
    name = title
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
        legacy_cron_minutes = int(task.get("cron_minutes", 30) or 30)
    except (TypeError, ValueError):
        legacy_cron_minutes = 30
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
        task.get("schedule_interval_minutes", task.get("interval_minutes", legacy_cron_minutes if legacy_cron_minutes > 0 else 30))
        if has_schedule_interval
        else (legacy_cron_minutes if legacy_cron_minutes > 0 else 30)
    )
    schedule_interval_minutes = normalize_subscription_schedule_interval_minutes(
        schedule_interval_raw,
        fallback=(legacy_cron_minutes if legacy_cron_minutes > 0 else 30),
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
    if not share_subdir:
        share_subdir_cid = ""
    return {
        "name": name,
        "media_type": media_type,
        "title": title,
        "aliases": aliases,
        "year": year,
        "season": max(1, season),
        "total_episodes": max(0, total_episodes),
        "savepath": savepath,
        "share_link_url": share_link_url,
        "share_link_receive_code": share_link_receive_code if share_link_url else "",
        "share_subdir": share_subdir,
        "share_subdir_cid": share_subdir_cid,
        "enabled": bool(task.get("enabled", True)),
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
        "enabled": bool(source.get("enabled", True)),
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


def normalize_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    merged = default_config()
    merged.update(cfg or {})

    if "webhook_secret" not in merged:
        merged["webhook_secret"] = ""
    if "alist_token" not in merged:
        merged["alist_token"] = ""
    if "cookie_115" not in merged:
        merged["cookie_115"] = ""
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
    if "monitor_tasks" not in merged or not isinstance(merged["monitor_tasks"], list):
        merged["monitor_tasks"] = []
    if "subscription_tasks" not in merged or not isinstance(merged["subscription_tasks"], list):
        merged["subscription_tasks"] = []
    if "resource_sources" not in merged or not isinstance(merged["resource_sources"], list):
        merged["resource_sources"] = []
    if "resource_quick_links" not in merged or not isinstance(merged["resource_quick_links"], list):
        merged["resource_quick_links"] = []

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
    merged["mount_path"] = normalize_remote_path(merged.get("mount_path", "/115"))
    merged["alist_url"] = str(merged.get("alist_url", "")).strip().rstrip("/")
    merged["webhook_secret"] = str(merged.get("webhook_secret", "")).strip()
    merged["cookie_115"] = str(merged.get("cookie_115", "")).strip()
    merged["sign115_enabled"] = bool(merged.get("sign115_enabled", False))
    merged["sign115_cron_time"] = normalize_sign115_cron_time(merged.get("sign115_cron_time", "09:00"))
    # 订阅批次收口刷新已固定为内置策略，不再保留配置项。
    merged.pop("subscription_batch_refresh_enabled", None)
    merged["tg_proxy_enabled"] = bool(merged.get("tg_proxy_enabled", False))
    merged["tg_proxy_protocol"] = str(merged.get("tg_proxy_protocol", "http") or "http").strip().lower()
    if merged["tg_proxy_protocol"] not in ("http", "https"):
        merged["tg_proxy_protocol"] = "http"
    merged["tg_proxy_host"] = str(merged.get("tg_proxy_host", "")).strip()
    merged["tg_proxy_port"] = str(merged.get("tg_proxy_port", "")).strip()
    merged["notify_push_enabled"] = bool(merged.get("notify_push_enabled", False))
    merged["notify_monitor_enabled"] = bool(merged.get("notify_monitor_enabled", False))
    notify_channel = str(merged.get("notify_channel", "wecom_bot") or "wecom_bot").strip().lower()
    merged["notify_channel"] = notify_channel if notify_channel in ("wecom_bot", "wecom_app") else "wecom_bot"
    merged["notify_wecom_webhook"] = str(merged.get("notify_wecom_webhook", "")).strip()
    merged["notify_wecom_app_corp_id"] = str(merged.get("notify_wecom_app_corp_id", "")).strip()
    merged["notify_wecom_app_agent_id"] = str(merged.get("notify_wecom_app_agent_id", "")).strip()
    merged["notify_wecom_app_secret"] = str(merged.get("notify_wecom_app_secret", "")).strip()
    merged["notify_wecom_app_touser"] = str(merged.get("notify_wecom_app_touser", "")).strip()
    merged["tmdb_enabled"] = bool(merged.get("tmdb_enabled", False))
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
    conn = sqlite3.connect(DB_PATH, timeout=30)
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
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS subscription_task_state (
            task_name TEXT PRIMARY KEY,
            media_type TEXT NOT NULL DEFAULT 'movie',
            status TEXT NOT NULL DEFAULT 'idle',
            progress INTEGER NOT NULL DEFAULT 0,
            detail TEXT NOT NULL DEFAULT '',
            last_run_at TEXT NOT NULL DEFAULT '',
            last_success_at TEXT NOT NULL DEFAULT '',
            last_error TEXT NOT NULL DEFAULT '',
            last_episode INTEGER NOT NULL DEFAULT 0,
            total_episodes INTEGER NOT NULL DEFAULT 0,
            matched_resource_id INTEGER NOT NULL DEFAULT 0,
            matched_resource_title TEXT NOT NULL DEFAULT '',
            matched_score INTEGER NOT NULL DEFAULT 0,
            queued_job_id INTEGER NOT NULL DEFAULT 0,
            stats_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS subscription_matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_name TEXT NOT NULL,
            resource_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL DEFAULT 0,
            media_type TEXT NOT NULL DEFAULT 'movie',
            season INTEGER NOT NULL DEFAULT 0,
            episode INTEGER NOT NULL DEFAULT 0,
            total_episodes INTEGER NOT NULL DEFAULT 0,
            score INTEGER NOT NULL DEFAULT 0,
            matched_at TEXT NOT NULL,
            UNIQUE(task_name, resource_id)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS subscription_episode_ledger (
            task_name TEXT NOT NULL,
            episode INTEGER NOT NULL,
            season INTEGER NOT NULL DEFAULT 0,
            media_type TEXT NOT NULL DEFAULT 'tv',
            best_score INTEGER NOT NULL DEFAULT 0,
            best_resolution INTEGER NOT NULL DEFAULT 0,
            source_fp TEXT NOT NULL DEFAULT '',
            content_fp TEXT NOT NULL DEFAULT '',
            link_type TEXT NOT NULL DEFAULT '',
            link_url TEXT NOT NULL DEFAULT '',
            resource_id INTEGER NOT NULL DEFAULT 0,
            job_id INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            first_seen_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (task_name, episode)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS share_entries_cache (
            cache_key TEXT PRIMARY KEY,
            share_code TEXT NOT NULL DEFAULT '',
            receive_code TEXT NOT NULL DEFAULT '',
            cid TEXT NOT NULL DEFAULT '0',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT '',
            expires_at TEXT NOT NULL DEFAULT ''
        )
        """
    )
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
    cursor.execute("PRAGMA table_info(resource_jobs)")
    job_columns = {str(row[1]) for row in cursor.fetchall()}
    if "extra_json" not in job_columns:
        cursor.execute("ALTER TABLE resource_jobs ADD COLUMN extra_json TEXT NOT NULL DEFAULT '{}'")
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_resource_items_link ON resource_items(link_url) WHERE link_url <> ''"
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_resource_items_created_at ON resource_items(created_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_resource_items_source_type ON resource_items(source_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_resource_items_channel_name ON resource_items(channel_name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_resource_items_source_channel ON resource_items(source_type, channel_name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_resource_items_status ON resource_items(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_resource_jobs_created_at ON resource_jobs(created_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_resource_jobs_status ON resource_jobs(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_subscription_state_status ON subscription_task_state(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_subscription_matches_task ON subscription_matches(task_name, matched_at DESC)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_subscription_episode_ledger_task_status ON subscription_episode_ledger(task_name, status)"
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_share_entries_cache_expires_at ON share_entries_cache(expires_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_share_entries_cache_share_cid ON share_entries_cache(share_code, cid)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_notification_dedupe_expires_at ON notification_dedupe(expires_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_notification_dedupe_scene ON notification_dedupe(scene, task_name)")
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
    conn = sqlite3.connect(DB_PATH, timeout=30)
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


def normalize_receive_code(value: Any) -> str:
    token = re.sub(r"\s+", "", str(value or "").strip())
    if not token:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9]{1,16}", token):
        return ""
    return token


def normalize_115_cid(value: Any) -> str:
    token = re.sub(r"\s+", "", str(value or "").strip())
    if not token or token == "0":
        return ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", token):
        return ""
    return token


def trim_resource_link_token(url: str) -> str:
    token = str(url or "").strip()
    if not token:
        return ""
    token = token.strip("<>[]{}\"'“”‘’")
    token = token.rstrip("，。；：！？、,.;!?")
    while token and token[-1] in (")", "）") and (token.count("(") + token.count("（")) < (token.count(")") + token.count("）")):
        token = token[:-1].rstrip("，。；：！？、,.;!?")
    return token


def normalize_115_share_url_candidate(url: str) -> str:
    token = trim_resource_link_token(url)
    if re.match(r"^(?:115cdn|115|anxia)\.com/s/[A-Za-z0-9]+", token, flags=re.IGNORECASE):
        return f"https://{token}"
    return token


def extract_resource_links(raw_text: str) -> List[str]:
    raw = str(raw_text or "")
    if not raw.strip():
        return []
    links: List[str] = []
    links.extend(RESOURCE_MAGNET_REGEX.findall(raw))
    links.extend(RESOURCE_ED2K_REGEX.findall(raw))
    links.extend(RESOURCE_URL_REGEX.findall(raw))
    links.extend(RESOURCE_115_SHARE_BARE_URL_REGEX.findall(raw))

    normalized_links: List[str] = []
    for link in links:
        token = normalize_115_share_url_candidate(link)
        token = trim_resource_link_token(token)
        lowered = token.lower()
        if not token or "t.me/" in lowered or "telegram.me/" in lowered:
            continue
        normalized_links.append(token)
    return unique_preserve_order(normalized_links)


def apply_share_receive_code_to_url(url: str, receive_code: str) -> str:
    share_url = str(url or "").strip()
    password = normalize_receive_code(receive_code)
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
    priority = {
        "magnet": 0,
        "115share": 1,
        "quark": 2,
        "aliyun": 3,
        "baidu": 4,
        "xunlei": 5,
        "uc": 6,
        "123pan": 7,
        "tianyi": 8,
        "pikpak": 9,
        "lanzou": 10,
        "ed2k": 11,
        "google_drive": 12,
        "onedrive": 13,
        "mega": 14,
        "link": 15,
        "unknown": 99,
    }
    normalized.sort(key=lambda url: (priority.get(detect_resource_link_type(url), 99), url))
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


def get_tg_channel_threads(cfg: Dict[str, Any]) -> int:
    try:
        raw_value = int(cfg.get("tg_channel_threads", TG_CHANNEL_THREADS_DEFAULT) or TG_CHANNEL_THREADS_DEFAULT)
    except (TypeError, ValueError):
        raw_value = TG_CHANNEL_THREADS_DEFAULT
    return max(1, min(TG_CHANNEL_THREADS_MAX, raw_value))


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
        "User-Agent": "Mozilla/5.0 115-media-hub",
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


RESOURCE_CJK_TEXT_REGEX = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def contains_cjk_text(value: Any) -> bool:
    return bool(RESOURCE_CJK_TEXT_REGEX.search(str(value or "").strip()))


def pick_subscription_display_title(task: Dict[str, Any], item: Dict[str, Any], fallback: str = "未命名资源") -> str:
    payload_task = task if isinstance(task, dict) else {}
    payload_item = item if isinstance(item, dict) else {}

    candidate_values: List[str] = []
    for value in [
        payload_task.get("tmdb_title", ""),
        payload_task.get("title", ""),
        payload_item.get("title", ""),
        payload_task.get("tmdb_original_title", ""),
    ]:
        normalized = str(value or "").strip()
        if normalized:
            candidate_values.append(normalized)

    for field in ("tmdb_aliases", "aliases"):
        raw_values = payload_task.get(field, [])
        if not isinstance(raw_values, list):
            continue
        candidate_values.extend([str(value or "").strip() for value in raw_values if str(value or "").strip()])

    deduped_candidates = unique_preserve_order(candidate_values)
    for candidate in deduped_candidates:
        if contains_cjk_text(candidate):
            return candidate

    if str(payload_item.get("title", "") or "").strip():
        return str(payload_item.get("title", "") or "").strip()
    if deduped_candidates:
        return deduped_candidates[0]
    return str(fallback or "未命名资源").strip() or "未命名资源"


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
    text = str(url or "").strip()
    lowered = text.lower()
    if not lowered:
        return "unknown"
    if lowered.startswith("magnet:?"):
        return "magnet"
    if lowered.startswith("ed2k://"):
        return "ed2k"
    if RESOURCE_115_SHARE_URL_REGEX.search(text):
        return "115share"
    for link_type, pattern in RESOURCE_LINK_TYPE_PATTERNS:
        if pattern.search(text):
            return link_type
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return "link"
    return "unknown"


def resolve_resource_link_type(link_type: str, link_url: str) -> str:
    normalized = str(link_type or "").strip().lower()
    detected = detect_resource_link_type(link_url)
    if detected != "unknown":
        return detected
    return normalized or "unknown"


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


def is_resource_title_link_like(text: str) -> bool:
    normalized = normalize_resource_title(text)
    if not normalized:
        return True
    lowered = normalized.lower()
    if lowered.startswith(("magnet:?", "ed2k://", "http://", "https://")):
        return True
    remainder = normalized
    for pattern in (RESOURCE_MAGNET_REGEX, RESOURCE_ED2K_REGEX, RESOURCE_URL_REGEX, RESOURCE_115_SHARE_BARE_URL_REGEX):
        remainder = pattern.sub(" ", remainder)
    remainder = re.sub(r"[\s\-•#_|，。；：,.;:!?！？、/\\\(\)（）\[\]【】<>《》]+", "", remainder)
    return not remainder


def extract_magnet_hash(link_url: str) -> str:
    token = trim_resource_link_token(link_url)
    if not token:
        return ""
    match = RESOURCE_MAGNET_HASH_REGEX.search(token)
    if not match:
        return ""
    return str(match.group(1) or "").upper()


def pick_magnet_title(link_url: str, index: int = 0) -> str:
    token = trim_resource_link_token(link_url)
    if token:
        try:
            parsed = urllib.parse.urlsplit(token)
            query = urllib.parse.parse_qs(parsed.query, keep_blank_values=False)
            dn_candidates = query.get("dn", [])
            if dn_candidates:
                dn_title = normalize_resource_title(dn_candidates[0])
                if dn_title and not is_resource_title_link_like(dn_title):
                    return dn_title
        except Exception:
            pass
    magnet_hash = extract_magnet_hash(token)
    if magnet_hash:
        return f"磁力任务 {magnet_hash[:12]}"
    if index > 0:
        return f"磁力任务 #{index}"
    return "磁力任务"


def pick_link_fallback_title(link_type: str, link_url: str, index: int = 0) -> str:
    normalized_type = str(link_type or "").strip().lower()
    if normalized_type == "magnet":
        return pick_magnet_title(link_url, index=index)
    if normalized_type == "115share":
        return f"115分享任务 #{index}" if index > 0 else "115分享任务"
    if normalized_type == "ed2k":
        return f"ED2K任务 #{index}" if index > 0 else "ED2K任务"
    if normalized_type == "link":
        return f"链接任务 #{index}" if index > 0 else "链接任务"
    return f"资源任务 #{index}" if index > 0 else "资源任务"


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

    links = extract_resource_links(raw)
    base_title = pick_resource_title(raw)
    base_title_link_like = is_resource_title_link_like(base_title)
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
        normalized_link = str(link or "").strip()
        link_type = detect_resource_link_type(normalized_link)
        receive_code = ""
        if link_type == "115share":
            parsed_payload = parse_115_share_payload(normalized_link, raw)
            normalized_link = str(parsed_payload.get("url", "") or normalized_link).strip() or normalized_link
            link_type = detect_resource_link_type(normalized_link)
            receive_code = normalize_receive_code(parsed_payload.get("receive_code", ""))
        if base_title_link_like:
            title = pick_link_fallback_title(link_type, normalized_link, idx if multi else 0)
        elif multi:
            title = f"{base_title} #{idx}"
        else:
            title = base_title
        extra: Dict[str, Any] = {}
        if receive_code:
            extra["receive_code"] = receive_code
        candidates.append(
            {
                "source_type": source_type,
                "source_name": source_name,
                "channel_name": channel_name or source_name,
                "title": title,
                "normalized_title": title.lower(),
                "raw_text": raw,
                "link_url": normalized_link,
                "link_type": link_type,
                "message_url": tg_link,
                "quality": quality,
                "year": guessed_year,
                "published_at": published_at.strip(),
                "receive_code": receive_code,
                "extra": extra,
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


def build_resource_job_snapshot(resource: Dict[str, Any], link_type: str = "", receive_code: str = "") -> Dict[str, Any]:
    extra = resource.get("extra", {})
    if not isinstance(extra, dict):
        extra = safe_json_loads(resource.get("extra_json"), {})
    manual_receive_code = (
        normalize_receive_code(receive_code)
        or normalize_receive_code(resource.get("receive_code", ""))
        or normalize_receive_code(extra.get("receive_code", ""))
    )
    snapshot = {
        "message_url": str(resource.get("message_url", "") or "").strip(),
        "source_post_id": str((extra or {}).get("source_post_id", "") or "").strip(),
    }
    resolved_link_type = resolve_resource_link_type(link_type or resource.get("link_type", ""), resource.get("link_url", ""))
    if resolved_link_type == "115share":
        payload = parse_115_share_payload(
            str(resource.get("link_url", "") or "").strip(),
            str(resource.get("raw_text", "") or ""),
            manual_receive_code,
        )
        resolved_receive_code = normalize_receive_code(payload.get("receive_code", ""))
        if resolved_receive_code:
            snapshot["receive_code"] = resolved_receive_code
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
    receive_code = normalize_receive_code(raw.get("receive_code", "") or extra.get("receive_code", ""))
    link_type = resolve_resource_link_type(str(raw.get("link_type", "") or "").strip(), link_url) or detect_resource_link_type(link_url)
    if link_type == "115share" and receive_code:
        link_url = apply_share_receive_code_to_url(link_url, receive_code)
    return {
        "id": int(raw.get("id", 0) or 0),
        "source_type": source_type,
        "source_name": source_name,
        "channel_name": channel_name,
        "title": title,
        "normalized_title": str(raw.get("normalized_title", "") or "").strip() or title.lower(),
        "raw_text": raw_text,
        "link_url": link_url,
        "link_type": link_type,
        "message_url": message_url,
        "quality": quality,
        "year": year,
        "published_at": published_at,
        "receive_code": receive_code,
        "extra": {
            "cover_url": str(extra.get("cover_url", "") or "").strip(),
            "source_post_id": str(extra.get("source_post_id", "") or "").strip(),
            "source_url": str(extra.get("source_url", "") or "").strip(),
            "receive_code": receive_code,
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
    data["job_source"] = str(data["extra"].get("job_source", "") or "").strip()
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


def build_subscription_text_tokens(text: str) -> List[str]:
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", " ", str(text or "").lower())
    tokens: List[str] = []
    for token in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", normalized):
        value = token.strip()
        if not value:
            continue
        if value in SUBSCRIPTION_STOP_WORDS:
            continue
        if value.isdigit() and len(value) <= 1:
            continue
        if len(value) <= 1 and not value.isdigit():
            continue
        tokens.append(value)
    return unique_preserve_order(tokens)


def build_subscription_query_tokens(task: Dict[str, Any]) -> List[str]:
    values = [task.get("title", ""), task.get("tmdb_title", ""), task.get("tmdb_original_title", "")]
    aliases = task.get("aliases", [])
    if isinstance(aliases, list):
        values.extend(aliases)
    tmdb_aliases = task.get("tmdb_aliases", [])
    if isinstance(tmdb_aliases, list):
        values.extend(tmdb_aliases)
    return unique_preserve_order(
        [token for value in values for token in build_subscription_text_tokens(str(value or ""))]
    )


def build_subscription_candidate_text(item: Dict[str, Any]) -> str:
    payload = item if isinstance(item, dict) else {}
    parts = [
        payload.get("title", ""),
        payload.get("raw_text", ""),
        payload.get("source_name", ""),
        payload.get("channel_name", ""),
    ]
    return re.sub(r"\s+", " ", " ".join(str(part or "").lower() for part in parts)).strip()


def compact_subscription_text(text: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(text or "").lower())


def strip_subscription_cjk_particles(text: str) -> str:
    return re.sub(r"[的之与和及·・]", "", str(text or ""))


def subscription_token_hit(token: str, text: str, text_compact: str) -> bool:
    normalized_token = str(token or "").strip().lower()
    if not normalized_token:
        return False
    if normalized_token in text:
        return True

    token_compact = compact_subscription_text(normalized_token)
    if not token_compact:
        return False
    if token_compact in text_compact:
        return True

    if re.search(r"[\u4e00-\u9fff]", token_compact):
        compact_without_particles = strip_subscription_cjk_particles(token_compact)
        if len(compact_without_particles) >= 2 and compact_without_particles in text_compact:
            return True
    return False


def detect_subscription_resolution(item: Dict[str, Any]) -> int:
    payload = item if isinstance(item, dict) else {}
    quality = str(payload.get("quality", "") or "").lower()
    text = f"{quality} {payload.get('title', '')} {payload.get('raw_text', '')}".lower()
    if re.search(r"\b(2160p|4k|uhd)\b", text):
        return 2160
    if re.search(r"\b(1080p|fhd)\b", text):
        return 1080
    if re.search(r"\b(720p|hd)\b", text):
        return 720
    if re.search(r"\b(480p|sd)\b", text):
        return 480
    if re.search(r"\b360p\b", text):
        return 360
    return 0


def score_subscription_title_signal(
    title: str,
    text: str,
    text_compact: str,
    exact_bonus: int,
    compact_bonus: int,
    cjk_bonus: int,
) -> int:
    title_norm = str(title or "").strip().lower()
    if not title_norm:
        return 0
    title_compact = compact_subscription_text(title_norm)
    if title_norm and title_norm in text:
        return int(exact_bonus)
    if title_compact and title_compact in text_compact:
        return int(compact_bonus)
    if title_compact:
        compact_without_particles = strip_subscription_cjk_particles(title_compact)
        if len(compact_without_particles) >= 2 and compact_without_particles in text_compact:
            return int(cjk_bonus)
    return 0


def score_subscription_quality_preference(task: Dict[str, Any], item: Dict[str, Any]) -> Tuple[int, int, str]:
    resolution = detect_subscription_resolution(item)
    quality_priority = normalize_subscription_quality_priority(
        task.get("quality_priority", SUBSCRIPTION_QUALITY_PRIORITY_DEFAULT)
    )
    if resolution <= 0:
        return 0, 0, quality_priority

    normalized_resolution = 360
    if resolution >= 2160:
        normalized_resolution = 2160
    elif resolution >= 1080:
        normalized_resolution = 1080
    elif resolution >= 720:
        normalized_resolution = 720
    elif resolution >= 480:
        normalized_resolution = 480

    order = SUBSCRIPTION_QUALITY_PRIORITY_ORDERS.get(
        quality_priority, SUBSCRIPTION_QUALITY_PRIORITY_ORDERS[SUBSCRIPTION_QUALITY_PRIORITY_DEFAULT]
    )
    if normalized_resolution not in order:
        return 0, normalized_resolution, quality_priority
    index = order.index(normalized_resolution)
    bonus_map = {0: 12, 1: 9, 2: 6, 3: 3, 4: 1}
    return int(bonus_map.get(index, 0)), normalized_resolution, quality_priority


def parse_small_cjk_number(value: Any, default: int = 0, max_value: int = 200) -> int:
    text = str(value or "").strip()
    if not text:
        return default
    if re.fullmatch(r"\d{1,4}", text):
        parsed_int = int(text)
        return parsed_int if 0 < parsed_int <= max_value else default
    if not re.fullmatch(r"[零〇一二三四五六七八九十两兩]+", text):
        return default

    parsed = -1
    if "十" in text:
        parts = text.split("十")
        if len(parts) <= 2:
            head = parts[0]
            tail = parts[1] if len(parts) == 2 else ""
            if head:
                tens = CJK_NUMERAL_DIGITS.get(head, -1)
                if tens > 0:
                    ones = 0
                    if tail:
                        ones = CJK_NUMERAL_DIGITS.get(tail, -1)
                    if ones >= 0:
                        parsed = tens * 10 + ones
            else:
                ones = 0
                if tail:
                    ones = CJK_NUMERAL_DIGITS.get(tail, -1)
                if ones >= 0:
                    parsed = 10 + ones
    else:
        parsed = CJK_NUMERAL_DIGITS.get(text, -1)

    return parsed if 0 < parsed <= max_value else default


def parse_resource_episode_meta(item: Dict[str, Any]) -> Dict[str, int]:
    payload = item if isinstance(item, dict) else {}
    text = f"{payload.get('title', '')} {payload.get('raw_text', '')}"
    season = 0
    episode = 0
    total = 0
    range_start = 0
    range_end = 0

    for pattern in RESOURCE_EPISODE_RANGE_REGEXES:
        range_match = pattern.search(text)
        if not range_match:
            continue
        start_episode = max(0, int(range_match.group(1) or 0))
        end_episode = max(0, int(range_match.group(2) or 0))
        if start_episode <= 0 and end_episode <= 0:
            continue
        if end_episode < start_episode:
            start_episode, end_episode = end_episode, start_episode
        range_start = start_episode
        range_end = end_episode
        break

    se_match = RESOURCE_SEASON_EPISODE_REGEX.search(text)
    if se_match:
        season = max(0, int(se_match.group(1) or 0))
        episode = max(0, int(se_match.group(2) or 0))
    else:
        season_match = RESOURCE_SEASON_ONLY_REGEX.search(text)
        if season_match:
            season = max(0, int(season_match.group(1) or 0))
        else:
            season_cn_match = RESOURCE_SEASON_ONLY_CN_REGEX.search(text)
            if season_cn_match:
                season = max(0, parse_small_cjk_number(season_cn_match.group(1), default=0, max_value=99))
            else:
                season_en_match = RESOURCE_SEASON_ENGLISH_REGEX.search(text)
                if season_en_match:
                    season = max(0, int(season_en_match.group(1) or 0))
        episode_match = RESOURCE_EPISODE_ONLY_REGEX.search(text) or RESOURCE_EPISODE_CODE_REGEX.search(text)
        if episode_match:
            episode = max(0, int(episode_match.group(1) or 0))

    if range_end > 0:
        episode = max(episode, range_end)
        if total <= 0 and range_start > 0 and range_start <= 1:
            total = max(total, range_end)

    for pattern in RESOURCE_TOTAL_EPISODES_REGEXES:
        matched = pattern.search(text)
        if matched:
            total = max(0, int(matched.group(1) or 0))
            break

    has_collection_hint = bool(RESOURCE_COLLECTION_HINT_REGEX.search(text))
    if total > 0 and has_collection_hint:
        if range_end <= 0:
            range_start = 1
            range_end = total
        episode = max(episode, total)
    elif episode <= 0 and total > 0 and ("全集" in text or "完结" in text or "完結" in text):
        episode = total
    return {
        "season": season,
        "episode": episode,
        "total": total,
        "range_start": range_start,
        "range_end": range_end,
    }


def match_subscription_media_type(task: Dict[str, Any], item: Dict[str, Any]) -> Tuple[bool, str]:
    media_type = str(task.get("media_type", "movie") or "movie").strip().lower()
    anime_mode = is_subscription_anime_compatible_task(task)
    text = build_subscription_candidate_text(item)
    meta = parse_resource_episode_meta(item)
    has_episode_meta = bool(int(meta.get("season", 0) or 0) > 0 or int(meta.get("episode", 0) or 0) > 0 or int(meta.get("total", 0) or 0) > 0)
    tv_hint = bool(
        re.search(
            r"(电视剧|剧集|番剧|动漫|第\s*[一二三四五六七八九十两兩0-9]+\s*(?:季|集|话|話)|season\s*\d+|s\d{1,2}\s*e?\d{0,3}|ep\s*\d{1,3}|更新至\s*\d+\s*(?:集|話|话)|全\s*\d+\s*(?:集|話|话)|完结|完結)",
            text,
            re.IGNORECASE,
        )
    )
    movie_hint = bool(re.search(r"(电影|movie|film|剧场版|電影)", text, re.IGNORECASE))

    if media_type == "movie":
        if has_episode_meta:
            return False, "episode_like"
        if tv_hint:
            return False, "tv_like"
        return True, "ok"

    # tv 强分区：默认必须具备剧集证据（季/集元信息或电视剧关键词）
    if has_episode_meta or tv_hint:
        return True, "ok"
    if anime_mode and not movie_hint:
        # 连载动漫资源有时不包含标准季集标记，动漫兼容模式下允许放行到后续评分阶段。
        return True, "anime_relaxed"
    if movie_hint:
        return False, "movie_like"
    return False, "missing_episode_meta"


def detect_resource_year(item: Dict[str, Any]) -> str:
    payload = item if isinstance(item, dict) else {}
    known_year = str(payload.get("year", "") or "").strip()
    if re.fullmatch(r"(19|20)\d{2}", known_year):
        return known_year
    combined = f"{payload.get('title', '')} {payload.get('raw_text', '')}"
    matched = RESOURCE_YEAR_REGEX.search(combined)
    return matched.group(1) if matched else ""


def score_subscription_candidate(
    task: Dict[str, Any],
    item: Dict[str, Any],
    query_tokens: List[str],
    last_episode: int,
) -> Dict[str, Any]:
    text = build_subscription_candidate_text(item)
    text_compact = compact_subscription_text(text)
    token_hits = sum(1 for token in query_tokens if subscription_token_hit(token, text, text_compact))
    # 别名过多时 token 总数会显著变大，限制分母避免有效命中被稀释
    token_denominator = max(1, min(8, len(query_tokens)))
    token_score = int((min(token_hits, token_denominator) / token_denominator) * 70)
    score = token_score

    title_signals: List[Tuple[str, int, int, int]] = [
        (str(task.get("title", "") or "").strip(), 14, 12, 10),
        (str(task.get("tmdb_title", "") or "").strip(), 13, 11, 9),
        (str(task.get("tmdb_original_title", "") or "").strip(), 12, 10, 8),
    ]
    aliases = task.get("aliases", [])
    if isinstance(aliases, list):
        title_signals.extend([(str(alias or "").strip(), 10, 8, 6) for alias in aliases[:6]])
    tmdb_aliases = task.get("tmdb_aliases", [])
    if isinstance(tmdb_aliases, list):
        title_signals.extend([(str(alias or "").strip(), 10, 8, 6) for alias in tmdb_aliases[:8]])

    seen_title_tokens: Set[str] = set()
    title_bonus = 0
    for title_value, exact_bonus, compact_bonus, cjk_bonus in title_signals:
        normalized_title = str(title_value or "").strip()
        normalized_key = compact_subscription_text(normalized_title)
        if not normalized_title or not normalized_key or normalized_key in seen_title_tokens:
            continue
        seen_title_tokens.add(normalized_key)
        signal_bonus = score_subscription_title_signal(
            normalized_title,
            text,
            text_compact,
            exact_bonus,
            compact_bonus,
            cjk_bonus,
        )
        title_bonus = max(title_bonus, signal_bonus)
    score += int(title_bonus)

    quality_bonus, resolution, quality_priority = score_subscription_quality_preference(task, item)
    score += int(quality_bonus)

    meta = parse_resource_episode_meta(item)
    media_type = str(task.get("media_type", "movie") or "movie").strip().lower()
    anime_mode_flag = is_subscription_anime_compatible_task(task)
    multi_season_mode = is_subscription_multi_season_mode(task)
    task_year = normalize_tmdb_year(task.get("year", "")) or normalize_tmdb_year(task.get("tmdb_year", ""))
    candidate_year = detect_resource_year(item)
    if task_year:
        if candidate_year == task_year:
            score += 12
        elif candidate_year:
            # 动漫和长连载经常出现不同年份打包（首播年 / 当前年 / 重制年），年份冲突仅做轻惩罚。
            if media_type == "tv" and anime_mode_flag:
                score -= 2
            elif media_type == "tv":
                score -= 8
            else:
                score -= 16

    if media_type == "movie":
        if meta["episode"] > 0:
            score -= 14
        if "电影" in text or "movie" in text or "film" in text:
            score += 6
    else:
        season = max(1, int(task.get("season", 1) or 1))
        anime_mode = anime_mode_flag
        episode_mode = resolve_subscription_tv_episode_mode(task)
        candidate_season = max(0, int(meta.get("season", 0) or 0))
        candidate_episode = max(0, int(meta.get("episode", 0) or 0))
        range_start = max(0, int(meta.get("range_start", 0) or 0))
        range_end = max(0, int(meta.get("range_end", 0) or 0))
        if multi_season_mode and candidate_season > 0:
            absolute_episode = convert_subscription_episode_to_absolute(task, candidate_season, candidate_episode)
            if absolute_episode > 0:
                candidate_episode = absolute_episode
            absolute_range_start, absolute_range_end = convert_subscription_episode_range_to_absolute(
                task, candidate_season, range_start, range_end
            )
            if absolute_range_end > 0:
                range_start = absolute_range_start
                range_end = absolute_range_end
        has_episode_range = range_end > 0 and range_start > 0
        if episode_mode == "absolute":
            if candidate_season > 0:
                score += 4
            elif candidate_season <= 0:
                # 多季合一或绝对集序下，不对任务季数做偏置。
                score += 2
        else:
            if candidate_season > 0:
                if candidate_season == season:
                    score += 10
                else:
                    score -= 6 if anime_mode else 18
            elif season == 1:
                score += 2
            elif anime_mode:
                score += 1

        if candidate_episode <= 0:
            score -= 4 if anime_mode else 8
        else:
            if candidate_episode <= last_episode:
                if has_episode_range and range_start <= max(1, last_episode):
                    # 区间包常用于补档，不能因为末集偏旧被提前淘汰。
                    score -= 1 if anime_mode else 2
                else:
                    # 旧集会在执行阶段被显式跳过，这里仅轻惩罚，避免评分阶段直接整体淘汰
                    score -= 4 if anime_mode else 6
            else:
                gap = candidate_episode - last_episode
                if gap == 1:
                    score += 16
                elif gap <= 4:
                    score += 11
                else:
                    score += 7
        if has_episode_range:
            range_size = max(1, range_end - range_start + 1)
            if range_start <= 1 and range_end >= max(1, last_episode):
                score += 14 if anime_mode else 8
            elif range_end > last_episode:
                score += 10 if anime_mode else 6
            elif range_start <= max(1, last_episode):
                score += 5 if anime_mode else 3
            if range_start <= 1 and range_size >= 24:
                score += 8 if anime_mode else 5
            if range_size >= 12:
                score += 4
        total_episodes = resolve_subscription_tv_total_episodes(task, state_total=0)
        if total_episodes > 0 and candidate_episode > total_episodes:
            score -= 24

    return {
        "item": item,
        "score": int(score),
        "token_hits": token_hits,
        "token_total": len(query_tokens),
        "season": int(meta.get("season", 0) or 0),
        "episode": int(candidate_episode if media_type == "tv" else max(0, int(meta.get("episode", 0) or 0))),
        "total": int(meta["total"] or 0),
        "range_start": int(range_start if media_type == "tv" else max(0, int(meta.get("range_start", 0) or 0))),
        "range_end": int(range_end if media_type == "tv" else max(0, int(meta.get("range_end", 0) or 0))),
        "resolution": int(resolution or 0),
        "quality_bonus": int(quality_bonus or 0),
        "quality_priority": quality_priority,
    }


def has_subscription_match(task_name: str, resource_id: int) -> bool:
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT 1 FROM subscription_matches WHERE task_name = ? AND resource_id = ? LIMIT 1",
        (str(task_name or "").strip(), int(resource_id or 0)),
    )
    row = cursor.fetchone()
    conn.close()
    return bool(row)


def create_subscription_match(
    task_name: str,
    resource_id: int,
    job_id: int,
    media_type: str,
    season: int = 0,
    episode: int = 0,
    total_episodes: int = 0,
    score: int = 0,
) -> None:
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO subscription_matches(
            task_name, resource_id, job_id, media_type, season, episode, total_episodes, score, matched_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(task_name or "").strip(),
            int(resource_id or 0),
            int(job_id or 0),
            str(media_type or "movie").strip().lower() or "movie",
            max(0, int(season or 0)),
            max(0, int(episode or 0)),
            max(0, int(total_episodes or 0)),
            int(score or 0),
            now_text(),
        ),
    )
    conn.commit()
    conn.close()


def load_subscription_episode_ledger(task_name: str, include_stale: bool = False) -> Dict[int, Dict[str, Any]]:
    normalized_task_name = str(task_name or "").strip()
    if not normalized_task_name:
        return {}
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    if include_stale:
        cursor.execute(
            """
            SELECT *
            FROM subscription_episode_ledger
            WHERE task_name = ?
            ORDER BY episode ASC
            """,
            (normalized_task_name,),
        )
    else:
        cursor.execute(
            """
            SELECT *
            FROM subscription_episode_ledger
            WHERE task_name = ? AND status = 'active'
            ORDER BY episode ASC
            """,
            (normalized_task_name,),
        )
    rows = cursor.fetchall()
    conn.close()

    ledger: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        data = sqlite_row_to_dict(row)
        episode_no = max(0, int(data.get("episode", 0) or 0))
        if episode_no <= 0:
            continue
        ledger[episode_no] = {
            "task_name": str(data.get("task_name", "") or "").strip(),
            "episode": episode_no,
            "season": max(0, int(data.get("season", 0) or 0)),
            "media_type": str(data.get("media_type", "tv") or "tv").strip().lower() or "tv",
            "best_score": max(0, int(data.get("best_score", 0) or 0)),
            "best_resolution": max(0, int(data.get("best_resolution", 0) or 0)),
            "source_fp": str(data.get("source_fp", "") or "").strip(),
            "content_fp": str(data.get("content_fp", "") or "").strip(),
            "link_type": str(data.get("link_type", "") or "").strip().lower(),
            "link_url": str(data.get("link_url", "") or "").strip(),
            "resource_id": max(0, int(data.get("resource_id", 0) or 0)),
            "job_id": max(0, int(data.get("job_id", 0) or 0)),
            "status": str(data.get("status", "active") or "active").strip().lower(),
            "first_seen_at": str(data.get("first_seen_at", "") or "").strip(),
            "updated_at": str(data.get("updated_at", "") or "").strip(),
        }
    return ledger


def reconcile_subscription_episode_ledger(task_name: str, existing_episodes: Set[int]) -> Dict[str, int]:
    normalized_task_name = str(task_name or "").strip()
    if not normalized_task_name:
        return {"activated": 0, "staled": 0}
    normalized_existing = {max(0, int(value or 0)) for value in (existing_episodes or set()) if max(0, int(value or 0)) > 0}

    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT episode, status
        FROM subscription_episode_ledger
        WHERE task_name = ?
        """,
        (normalized_task_name,),
    )
    rows = cursor.fetchall()
    if not rows:
        conn.close()
        return {"activated": 0, "staled": 0}

    now_iso = now_text()
    activate_rows: List[Tuple[str, str, int]] = []
    stale_rows: List[Tuple[str, str, int]] = []
    for row in rows:
        episode_no = max(0, int(row["episode"] or 0))
        if episode_no <= 0:
            continue
        current_status = str(row["status"] or "active").strip().lower() or "active"
        target_status = "active" if episode_no in normalized_existing else "stale"
        if current_status == target_status:
            continue
        payload = (target_status, now_iso, normalized_task_name, episode_no)
        if target_status == "active":
            activate_rows.append(payload)
        else:
            stale_rows.append(payload)

    if activate_rows:
        cursor.executemany(
            """
            UPDATE subscription_episode_ledger
            SET status = ?, updated_at = ?
            WHERE task_name = ? AND episode = ?
            """,
            activate_rows,
        )
    if stale_rows:
        cursor.executemany(
            """
            UPDATE subscription_episode_ledger
            SET status = ?, updated_at = ?
            WHERE task_name = ? AND episode = ?
            """,
            stale_rows,
        )
    conn.commit()
    conn.close()
    return {"activated": len(activate_rows), "staled": len(stale_rows)}


def upsert_subscription_episode_ledger(
    task_name: str,
    episodes: Set[int],
    media_type: str = "tv",
    season: int = 0,
    score: int = 0,
    resolution: int = 0,
    source_fp: str = "",
    content_fp: str = "",
    link_type: str = "",
    link_url: str = "",
    resource_id: int = 0,
    job_id: int = 0,
) -> int:
    normalized_task_name = str(task_name or "").strip()
    if not normalized_task_name:
        return 0
    normalized_episodes = sorted({max(0, int(value or 0)) for value in (episodes or set()) if max(0, int(value or 0)) > 0})
    if not normalized_episodes:
        return 0

    normalized_media_type = str(media_type or "tv").strip().lower() or "tv"
    normalized_season = max(0, int(season or 0))
    normalized_score = max(0, int(score or 0))
    normalized_resolution = max(0, int(resolution or 0))
    normalized_source_fp = str(source_fp or "").strip()
    normalized_content_fp = str(content_fp or "").strip()
    normalized_link_type = str(link_type or "").strip().lower()
    normalized_link_url = str(link_url or "").strip()
    normalized_resource_id = max(0, int(resource_id or 0))
    normalized_job_id = max(0, int(job_id or 0))
    now_iso = now_text()

    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    changed = 0
    for episode_no in normalized_episodes:
        cursor.execute(
            """
            SELECT best_score, best_resolution, first_seen_at, status
            FROM subscription_episode_ledger
            WHERE task_name = ? AND episode = ?
            """,
            (normalized_task_name, episode_no),
        )
        row = cursor.fetchone()
        if row:
            existing_score = max(0, int(row["best_score"] or 0))
            existing_resolution = max(0, int(row["best_resolution"] or 0))
            existing_first_seen = str(row["first_seen_at"] or "").strip() or now_iso
            existing_status = str(row["status"] or "active").strip().lower() or "active"

            best_score_value = existing_score
            best_resolution_value = existing_resolution
            if normalized_resolution > existing_resolution:
                best_resolution_value = normalized_resolution
                best_score_value = max(existing_score, normalized_score)
            elif normalized_resolution == existing_resolution:
                best_score_value = max(existing_score, normalized_score)
            elif existing_resolution <= 0:
                best_score_value = max(existing_score, normalized_score)

            status_value = "active"
            cursor.execute(
                """
                UPDATE subscription_episode_ledger
                SET season = ?, media_type = ?, best_score = ?, best_resolution = ?,
                    source_fp = ?, content_fp = ?, link_type = ?, link_url = ?,
                    resource_id = ?, job_id = ?, status = ?, first_seen_at = ?, updated_at = ?
                WHERE task_name = ? AND episode = ?
                """,
                (
                    normalized_season,
                    normalized_media_type,
                    best_score_value,
                    best_resolution_value,
                    normalized_source_fp,
                    normalized_content_fp,
                    normalized_link_type,
                    normalized_link_url,
                    normalized_resource_id,
                    normalized_job_id,
                    status_value,
                    existing_first_seen,
                    now_iso,
                    normalized_task_name,
                    episode_no,
                ),
            )
            if cursor.rowcount > 0 and (
                best_score_value != existing_score
                or best_resolution_value != existing_resolution
                or existing_status != "active"
            ):
                changed += 1
        else:
            cursor.execute(
                """
                INSERT INTO subscription_episode_ledger(
                    task_name, episode, season, media_type, best_score, best_resolution,
                    source_fp, content_fp, link_type, link_url, resource_id, job_id,
                    status, first_seen_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    normalized_task_name,
                    episode_no,
                    normalized_season,
                    normalized_media_type,
                    normalized_score,
                    normalized_resolution,
                    normalized_source_fp,
                    normalized_content_fp,
                    normalized_link_type,
                    normalized_link_url,
                    normalized_resource_id,
                    normalized_job_id,
                    now_iso,
                    now_iso,
                ),
            )
            if cursor.rowcount > 0:
                changed += 1
    conn.commit()
    conn.close()
    return changed


def prune_subscription_state_for_missing_tasks(task_names: List[str]) -> None:
    normalized = {str(name or "").strip() for name in task_names if str(name or "").strip()}
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    if not normalized:
        cursor.execute("DELETE FROM subscription_task_state")
        cursor.execute("DELETE FROM subscription_matches")
        cursor.execute("DELETE FROM subscription_episode_ledger")
        conn.commit()
        conn.close()
        return
    placeholders = ",".join("?" for _ in normalized)
    params = list(normalized)
    cursor.execute(f"DELETE FROM subscription_task_state WHERE task_name NOT IN ({placeholders})", params)
    cursor.execute(f"DELETE FROM subscription_matches WHERE task_name NOT IN ({placeholders})", params)
    cursor.execute(f"DELETE FROM subscription_episode_ledger WHERE task_name NOT IN ({placeholders})", params)
    conn.commit()
    conn.close()


def load_subscription_task_state(task_name: str, media_type: str = "movie") -> Dict[str, Any]:
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM subscription_task_state WHERE task_name = ?", (str(task_name or "").strip(),))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return {
            "task_name": str(task_name or "").strip(),
            "media_type": str(media_type or "movie").strip().lower() or "movie",
            "status": "idle",
            "progress": 0,
            "detail": "",
            "last_run_at": "",
            "last_success_at": "",
            "last_error": "",
            "last_episode": 0,
            "total_episodes": 0,
            "matched_resource_id": 0,
            "matched_resource_title": "",
            "matched_score": 0,
            "queued_job_id": 0,
            "stats": {},
            "updated_at": "",
        }
    data = sqlite_row_to_dict(row)
    data["stats"] = safe_json_loads(data.get("stats_json"), {})
    return {
        "task_name": str(data.get("task_name", "") or "").strip(),
        "media_type": str(data.get("media_type", "movie") or "movie").strip().lower() or "movie",
        "status": str(data.get("status", "idle") or "idle").strip().lower(),
        "progress": max(0, min(100, int(data.get("progress", 0) or 0))),
        "detail": str(data.get("detail", "") or "").strip(),
        "last_run_at": str(data.get("last_run_at", "") or "").strip(),
        "last_success_at": str(data.get("last_success_at", "") or "").strip(),
        "last_error": str(data.get("last_error", "") or "").strip(),
        "last_episode": max(0, int(data.get("last_episode", 0) or 0)),
        "total_episodes": max(0, int(data.get("total_episodes", 0) or 0)),
        "matched_resource_id": max(0, int(data.get("matched_resource_id", 0) or 0)),
        "matched_resource_title": str(data.get("matched_resource_title", "") or "").strip(),
        "matched_score": max(0, int(data.get("matched_score", 0) or 0)),
        "queued_job_id": max(0, int(data.get("queued_job_id", 0) or 0)),
        "stats": data["stats"] if isinstance(data["stats"], dict) else {},
        "updated_at": str(data.get("updated_at", "") or "").strip(),
    }


def upsert_subscription_task_state(task_name: str, **fields: Any) -> None:
    task_key = str(task_name or "").strip()
    if not task_key:
        return
    max_attempts = 4
    for attempt in range(max_attempts):
        conn: Optional[sqlite3.Connection] = None
        try:
            current = load_subscription_task_state(task_key)
            ensure_db()
            conn = open_db()
            cursor = conn.cursor()
            payload = {**current}
            payload.update(fields)
            stats_value = payload.get("stats", {})
            if not isinstance(stats_value, dict):
                stats_value = {}
            now = now_text()
            cursor.execute(
                """
                INSERT OR REPLACE INTO subscription_task_state(
                    task_name, media_type, status, progress, detail, last_run_at, last_success_at, last_error,
                    last_episode, total_episodes, matched_resource_id, matched_resource_title, matched_score,
                    queued_job_id, stats_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_key,
                    str(payload.get("media_type", "movie") or "movie").strip().lower() or "movie",
                    str(payload.get("status", "idle") or "idle").strip().lower(),
                    max(0, min(100, int(payload.get("progress", 0) or 0))),
                    str(payload.get("detail", "") or "").strip(),
                    str(payload.get("last_run_at", "") or "").strip(),
                    str(payload.get("last_success_at", "") or "").strip(),
                    str(payload.get("last_error", "") or "").strip(),
                    max(0, int(payload.get("last_episode", 0) or 0)),
                    max(0, int(payload.get("total_episodes", 0) or 0)),
                    max(0, int(payload.get("matched_resource_id", 0) or 0)),
                    str(payload.get("matched_resource_title", "") or "").strip(),
                    max(0, int(payload.get("matched_score", 0) or 0)),
                    max(0, int(payload.get("queued_job_id", 0) or 0)),
                    safe_json_dumps(stats_value),
                    now,
                ),
            )
            conn.commit()
            return
        except sqlite3.OperationalError as exc:
            message = str(exc or "").lower()
            retryable = "locked" in message
            if (not retryable) or attempt >= max_attempts - 1:
                raise
            time.sleep(0.15 * (attempt + 1))
        finally:
            if conn is not None:
                conn.close()


def list_subscription_task_runtime(cfg: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    cfg = cfg or get_config()
    tasks = cfg.get("subscription_tasks", []) if isinstance(cfg.get("subscription_tasks"), list) else []
    global_running = bool(subscription_status.get("running"))
    current_running_task = str(subscription_status.get("current_task", "") or "").strip()
    result: List[Dict[str, Any]] = []
    for raw_task in tasks:
        task = normalize_subscription_task(raw_task or {})
        if not task.get("name"):
            continue
        state = load_subscription_task_state(task["name"], task.get("media_type", "movie"))
        state_status = str(state.get("status", "idle") or "idle").strip().lower()
        if state_status == "running":
            is_current_active_task = global_running and current_running_task == task["name"]
            if not is_current_active_task:
                stale_detail = "检测到历史运行状态残留，已自动回收（可重新运行）"
                try:
                    upsert_subscription_task_state(
                        task["name"],
                        media_type=task.get("media_type", "movie"),
                        status="failed",
                        progress=100,
                        detail=stale_detail,
                        last_error=stale_detail,
                    )
                    state = load_subscription_task_state(task["name"], task.get("media_type", "movie"))
                except Exception:
                    state = {
                        **state,
                        "status": "failed",
                        "progress": 100,
                        "detail": stale_detail,
                        "last_error": stale_detail,
                    }
        merged = {
            **task,
            "status": state.get("status", "idle"),
            "progress": state.get("progress", 0),
            "detail": state.get("detail", ""),
            "last_run_at": state.get("last_run_at", ""),
            "last_success_at": state.get("last_success_at", ""),
            "last_error": state.get("last_error", ""),
            "last_episode": state.get("last_episode", 0),
            "matched_resource_id": state.get("matched_resource_id", 0),
            "matched_resource_title": state.get("matched_resource_title", ""),
            "matched_score": state.get("matched_score", 0),
            "queued_job_id": state.get("queued_job_id", 0),
            "stats": state.get("stats", {}),
            "next_run": subscription_next_run.get(task["name"], ""),
        }
        if str(task.get("media_type", "movie") or "movie").strip().lower() == "tv":
            merged["total_episodes"] = resolve_subscription_tv_total_episodes(
                task,
                state_total=max(0, int(state.get("total_episodes", 0) or 0)),
            )
        elif merged["total_episodes"] <= 0:
            merged["total_episodes"] = state.get("total_episodes", 0)
        result.append(merged)
    return result


def find_subscription_task_match_candidate(task: Dict[str, Any], last_episode: int = 0, limit: int = 400) -> Dict[str, Any]:
    query_tokens = build_subscription_query_tokens(task)
    if not query_tokens:
        return {}
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT * FROM resource_items
        WHERE link_url <> ''
        ORDER BY CASE WHEN published_at <> '' THEN published_at ELSE created_at END DESC, id DESC
        LIMIT ?
        """,
        (max(80, min(1200, int(limit or 400))),),
    )
    rows = cursor.fetchall()
    conn.close()

    min_score = max(30, min(100, int(task.get("min_score", SUBSCRIPTION_MIN_SCORE) or SUBSCRIPTION_MIN_SCORE)))
    media_type = str(task.get("media_type", "movie") or "movie").strip().lower()
    candidates: List[Dict[str, Any]] = []
    for row in rows:
        item = serialize_resource_item_row(row)
        item_id = int(item.get("id", 0) or 0)
        if item_id <= 0:
            continue
        media_match, _ = match_subscription_media_type(task, item)
        if not media_match:
            continue
        matched_before = has_subscription_match(task.get("name", ""), item_id)
        scored = score_subscription_candidate(task, item, query_tokens, last_episode)
        if matched_before:
            if media_type != "tv":
                continue
            if int(scored.get("episode", 0) or 0) <= 0 and int(scored.get("range_end", 0) or 0) <= 0:
                continue
            scored["matched_before"] = True
        if scored["score"] < min_score:
            continue
        candidates.append(scored)

    if not candidates:
        return {}

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
    return candidates[0]


def list_resource_jobs(limit: int = 80) -> List[Dict[str, Any]]:
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM resource_jobs ORDER BY id DESC LIMIT ?", (max(1, min(limit, 500)),))
    rows = cursor.fetchall()
    conn.close()
    return [serialize_resource_job_row(row) for row in rows]


def list_resource_jobs_by_source(job_source: str, limit: int = 80, scan_limit: int = 400) -> List[Dict[str, Any]]:
    source_key = str(job_source or "").strip()
    if not source_key:
        return []
    query_limit = max(1, min(max(int(scan_limit or 0), int(limit or 0), 80), 800))
    jobs = list_resource_jobs(limit=query_limit)
    matched: List[Dict[str, Any]] = []
    target_limit = max(1, int(limit or 1))
    for job in jobs:
        extra = job.get("extra") if isinstance(job.get("extra"), dict) else {}
        if str(extra.get("job_source", "")).strip() != source_key:
            continue
        matched.append(job)
        if len(matched) >= target_limit:
            break
    return matched


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


def normalize_resource_job_clear_scope(scope: Any) -> str:
    normalized = str(scope or "").strip().lower()
    if normalized in ("completed", "done", "success"):
        return "completed"
    if normalized in ("failed", "fail", "error"):
        return "failed"
    if normalized in ("terminal", "finished", "completed_failed", "completed+failed", "all_done"):
        return "terminal"
    return "completed"


def clear_resource_jobs(scope: str = "completed") -> Dict[str, int]:
    normalized_scope = normalize_resource_job_clear_scope(scope)
    if normalized_scope == "failed":
        target_statuses = ["failed"]
    elif normalized_scope == "terminal":
        target_statuses = ["completed", "failed"]
    else:
        target_statuses = ["completed"]

    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    placeholders = ",".join(["?"] * len(target_statuses))
    cursor.execute(
        f"SELECT DISTINCT resource_id FROM resource_jobs WHERE status IN ({placeholders})",
        tuple(target_statuses),
    )
    affected_resource_ids = [int(row[0]) for row in cursor.fetchall() if row and row[0]]

    cursor.execute(
        f"DELETE FROM resource_jobs WHERE status IN ({placeholders})",
        tuple(target_statuses),
    )
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
    return {
        "scope": normalized_scope,
        "deleted": deleted_count,
        "reset_items": reset_item_count,
    }


def clear_completed_resource_jobs() -> Dict[str, int]:
    # Backward compatibility for existing callers.
    return clear_resource_jobs("completed")


def recover_stale_resource_jobs(max_age_seconds: int = RESOURCE_JOB_STALE_RECOVER_SECONDS) -> Dict[str, int]:
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, resource_id, started_at, updated_at, created_at, status_detail
        FROM resource_jobs
        WHERE status = 'running'
        ORDER BY id DESC
        LIMIT 200
        """
    )
    rows = cursor.fetchall()
    if not rows:
        conn.close()
        return {"recovered": 0, "checked": 0}

    now_ts = time.time()
    limit_seconds = max(30, int(max_age_seconds or RESOURCE_JOB_STALE_RECOVER_SECONDS))
    recovered = 0
    checked = 0
    now_iso = now_text()
    recovered_resource_ids: Set[int] = set()

    for row in rows:
        data = sqlite_row_to_dict(row)
        job_id = max(0, int(data.get("id", 0) or 0))
        if job_id <= 0:
            continue
        if job_id in resource_job_running:
            continue
        checked += 1
        started_at = str(data.get("started_at", "") or "").strip()
        updated_at = str(data.get("updated_at", "") or "").strip()
        created_at = str(data.get("created_at", "") or "").strip()
        anchor_ts = (
            parse_resource_datetime_to_timestamp(started_at)
            or parse_resource_datetime_to_timestamp(updated_at)
            or parse_resource_datetime_to_timestamp(created_at)
        )
        age_seconds = (now_ts - anchor_ts) if anchor_ts > 0 else (limit_seconds + 1)
        if age_seconds < limit_seconds:
            continue
        detail = str(data.get("status_detail", "") or "").strip()
        stale_detail = f"运行超时已自动回收（>{limit_seconds} 秒）"
        if detail:
            stale_detail = f"{stale_detail}；原状态：{detail[:80]}"
        cursor.execute(
            """
            UPDATE resource_jobs
            SET status = 'failed', status_detail = ?, finished_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (stale_detail, now_iso, now_iso, job_id),
        )
        if int(cursor.rowcount or 0) > 0:
            recovered += 1
            recovered_resource_ids.add(max(0, int(data.get("resource_id", 0) or 0)))
            resource_refresh_pending.discard(job_id)
            resource_job_cancel_requested.discard(job_id)

    for resource_id in recovered_resource_ids:
        if resource_id <= 0:
            continue
        cursor.execute("SELECT COUNT(1) FROM resource_jobs WHERE resource_id = ? AND status = 'running'", (resource_id,))
        still_running_row = cursor.fetchone()
        still_running = int(still_running_row[0] if still_running_row else 0)
        if still_running > 0:
            continue
        cursor.execute(
            "UPDATE resource_items SET status = 'failed', last_seen_at = ? WHERE id = ?",
            (now_iso, resource_id),
        )

    conn.commit()
    conn.close()
    return {"recovered": recovered, "checked": checked}


def recover_submitted_resource_jobs_without_monitor(limit: int = 200) -> Dict[str, int]:
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    query_limit = max(20, min(int(limit or 200), 1000))
    cursor.execute(
        """
        SELECT id, resource_id, status_detail
        FROM resource_jobs
        WHERE status = 'submitted' AND trim(monitor_task_name) = ''
        ORDER BY id DESC
        LIMIT ?
        """,
        (query_limit,),
    )
    rows = cursor.fetchall()
    if not rows:
        conn.close()
        return {"recovered": 0, "checked": 0}

    now_iso = now_text()
    recovered = 0
    checked = 0
    recovered_resource_ids: Set[int] = set()
    hint_text = "当前保存路径未纳入文件夹监控，导入成功后不会自动生成 strm"

    for row in rows:
        data = sqlite_row_to_dict(row)
        job_id = max(0, int(data.get("id", 0) or 0))
        if job_id <= 0:
            continue
        checked += 1
        detail = str(data.get("status_detail", "") or "").strip()
        next_detail = detail or hint_text
        if hint_text not in next_detail:
            next_detail = f"{next_detail}；{hint_text}" if next_detail else hint_text
        cursor.execute(
            """
            UPDATE resource_jobs
            SET status = 'completed',
                status_detail = ?,
                finished_at = CASE WHEN trim(finished_at) = '' THEN ? ELSE finished_at END,
                updated_at = ?
            WHERE id = ? AND status = 'submitted'
            """,
            (next_detail, now_iso, now_iso, job_id),
        )
        if int(cursor.rowcount or 0) > 0:
            recovered += 1
            recovered_resource_ids.add(max(0, int(data.get("resource_id", 0) or 0)))
            resource_refresh_pending.discard(job_id)
            resource_job_cancel_requested.discard(job_id)

    for resource_id in recovered_resource_ids:
        if resource_id <= 0:
            continue
        cursor.execute(
            "SELECT COUNT(1) FROM resource_jobs WHERE resource_id = ? AND status IN ('pending', 'running', 'submitted')",
            (resource_id,),
        )
        active_row = cursor.fetchone()
        active_count = int(active_row[0] if active_row else 0)
        if active_count > 0:
            continue
        cursor.execute(
            "SELECT COUNT(1) FROM resource_jobs WHERE resource_id = ? AND status = 'completed'",
            (resource_id,),
        )
        completed_row = cursor.fetchone()
        completed_count = int(completed_row[0] if completed_row else 0)
        if completed_count <= 0:
            continue
        cursor.execute(
            "UPDATE resource_items SET status = 'completed', last_seen_at = ? WHERE id = ?",
            (now_iso, resource_id),
        )

    conn.commit()
    conn.close()
    return {"recovered": recovered, "checked": checked}


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


def resolve_resource_item_published_at(item: Dict[str, Any]) -> str:
    payload = item if isinstance(item, dict) else {}
    return str(payload.get("published_at", "") or payload.get("created_at", "")).strip()


def parse_resource_datetime_to_timestamp(value: str) -> float:
    raw = str(value or "").strip()
    if not raw:
        return 0.0
    normalized = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
    try:
        return datetime.fromisoformat(normalized).timestamp()
    except Exception:
        try:
            return datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S").timestamp()
        except Exception:
            return 0.0


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
            cached_profile = resource_channel_profiles.get(channel_id, {})
            channel_profile = cached_profile if cached_profile else build_resource_channel_profile(channel_id, channel_pool)
        else:
            channel_pool = list_resource_items(
                channel_id=channel_id,
                source_type="tg",
                limit=max(per_channel, RESOURCE_CHANNEL_TYPE_SAMPLE_SIZE),
            )
            channel_items = channel_pool[:per_channel]
            item_count = count_resource_items(channel_id=channel_id, source_type="tg")
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
        }

    semaphore = asyncio.Semaphore(tg_channel_threads)

    async def search_one_source(source: Dict[str, Any]) -> Dict[str, Any]:
        try:
            async with semaphore:
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
        "thread_limit": tg_channel_threads,
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
    custom_extra = data.get("extra", {})
    if isinstance(custom_extra, dict):
        extra = merge_json_object(extra, custom_extra)
    job_source = str(data.get("job_source", "") or "").strip()
    if job_source:
        extra["job_source"] = job_source
    elif not str(extra.get("job_source", "") or "").strip():
        # 默认归类为手动导入。自动化来源（订阅、Webhook 等）应在调用侧显式覆盖。
        extra["job_source"] = "manual_import"
    manual_receive_code = normalize_receive_code(data.get("receive_code", ""))
    if link_type == "115share" and manual_receive_code:
        extra["receive_code"] = manual_receive_code
    extra["snapshot"] = build_resource_job_snapshot(resource, link_type, manual_receive_code)
    manual_sharetitle = normalize_relative_path(data.get("sharetitle", ""))
    if manual_sharetitle:
        sharetitle = manual_sharetitle
    elif link_type == "115share":
        sharetitle = normalize_relative_path(extra.get("auto_sharetitle", ""))
    elif link_type == "magnet":
        # 磁力任务默认不绑定子目录提示，避免把原始链接文本误当目录。
        sharetitle = ""
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


def read_log_tail(path: str, limit: int = 200) -> List[str]:
    normalized_limit = max(1, int(limit or 200))
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = [line.rstrip("\n") for line in f.readlines()]
    except Exception:
        return []
    compact = [line for line in lines if str(line or "").strip()]
    if not compact:
        return []
    return compact[-normalized_limit:]


def infer_log_level_from_text(text: str) -> str:
    normalized = str(text or "")
    if "━━━━━━━━━━" in normalized:
        return "task-divider"
    if "··" in normalized and normalized.count("··") >= 2:
        return "section-divider"
    if "生成汇总:" in normalized or "清理汇总:" in normalized:
        return "info"
    lowered = normalized.lower()
    if "error" in lowered or "fail" in lowered or "失败" in normalized or "❌" in normalized:
        return "error"
    if "warn" in lowered or "警告" in normalized or "⚠" in normalized:
        return "warn"
    if "success" in lowered or "完成" in normalized or "成功" in normalized or "✅" in normalized:
        return "success"
    return "info"


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


def validate_subscription_runtime_config(cfg: Dict[str, Any], task: Dict[str, Any]) -> Optional[str]:
    if not str(cfg.get("cookie_115", "")).strip():
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
version_cache: Dict[str, Any] = {"latest": None, "checked_at": 0.0, "error": ""}
tmdb_cache_entries: Dict[str, Dict[str, Any]] = {}
ui_event_subscribers: Set[asyncio.Queue[str]] = set()
ui_push_pending = False
ui_push_task: Optional[asyncio.Task] = None
resource_job_running: Set[int] = set()
resource_refresh_pending: Set[int] = set()
resource_job_cancel_requested: Set[int] = set()
resource_channel_last_sync: Dict[str, float] = {}
resource_channel_last_error: Dict[str, str] = {}
resource_channel_syncing: Set[str] = set()
resource_channel_profiles: Dict[str, Dict[str, Any]] = {}


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
    return {
        "main": build_main_status_payload(),
        "monitor": build_monitor_status_payload(cfg),
        "subscription": build_subscription_status_payload(cfg),
        "sign115": build_sign115_status_payload(cfg),
    }


async def build_resource_state_payload(search: str = "") -> Dict[str, Any]:
    cfg = get_config()
    recover_stale_resource_jobs()
    recover_submitted_resource_jobs_without_monitor()
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
    failed_job_count = count_resource_jobs(status="failed")
    sources = cfg.get("resource_sources", [])
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
        "monitor_tasks": clone_jsonable(cfg.get("monitor_tasks", [])),
        "cookie_configured": bool(str(cfg.get("cookie_115", "")).strip()),
        "setup_status": {
            "alist_configured": bool(str(cfg.get("alist_url", "")).strip()),
            "cookie_configured": bool(str(cfg.get("cookie_115", "")).strip()),
            "has_sources": bool(enabled_sources),
            "has_monitor": bool(cfg.get("monitor_tasks", [])),
            "has_resource_data": total_item_count > 0,
            "has_jobs": bool(jobs),
        },
        "search": keyword,
        "channel_sections": clone_jsonable(channel_sections),
        "channel_profiles": clone_jsonable(channel_profiles),
        "search_sections": clone_jsonable(search_sections),
        "last_syncs": clone_jsonable(resource_channel_last_sync),
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
            "completed_job_count": completed_job_count,
            "failed_job_count": failed_job_count,
        },
    }


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
    if sharetitle_rel and is_resource_title_link_like(sharetitle_rel):
        sharetitle_rel = ""
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


async def write_log(msg: str, level: Optional[str] = None) -> None:
    line = f"{format_log_time(True)} {msg}"
    task_status["logs"].append({"text": line, "level": level or infer_log_level_from_text(line)})
    if len(task_status["logs"]) > 500:
        task_status["logs"].pop(0)
    schedule_ui_state_push()
    await asyncio.to_thread(append_log_file, MAIN_LOG_PATH, line)
    await asyncio.sleep(0)


async def write_monitor_log(text: str, level: str = "info") -> None:
    line = f"{format_log_time(True)} {text}"
    monitor_status["logs"].append({"text": line, "level": level})
    if len(monitor_status["logs"]) > 800:
        monitor_status["logs"].pop(0)
    schedule_ui_state_push()
    await asyncio.to_thread(append_log_file, MONITOR_LOG_PATH, line)
    await asyncio.sleep(0)


async def write_subscription_log(text: str, level: str = "info") -> None:
    line = f"{format_log_time(True)} {text}"
    subscription_status["logs"].append({"text": line, "level": level})
    if len(subscription_status["logs"]) > 800:
        subscription_status["logs"].pop(0)
    schedule_ui_state_push()
    try:
        await asyncio.to_thread(append_log_file, SUBSCRIPTION_LOG_PATH, line)
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
        "cron": "时段定时触发",
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
    proxy_url: str = "",
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
    opener = urllib.request.build_opener()
    if proxy_url:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        )
    with opener.open(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        body = resp.read().decode(charset, errors="ignore")
    return json.loads(body or "{}")


def get_tmdb_runtime_config(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = cfg or get_config()
    enabled = bool(cfg.get("tmdb_enabled", False))
    api_key = str(cfg.get("tmdb_api_key", "")).strip()
    language = str(cfg.get("tmdb_language", "zh-CN") or "zh-CN").strip()
    if not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", language):
        language = "zh-CN"
    region = str(cfg.get("tmdb_region", "CN") or "CN").strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", region):
        region = "CN"
    try:
        cache_ttl_hours = int(cfg.get("tmdb_cache_ttl_hours", 24) or 24)
    except (TypeError, ValueError):
        cache_ttl_hours = 24
    cache_ttl_hours = max(1, min(24 * 30, cache_ttl_hours))
    return {
        "enabled": enabled,
        "api_key": api_key,
        "language": language,
        "region": region,
        "cache_ttl_hours": cache_ttl_hours,
        "cache_ttl_seconds": cache_ttl_hours * 3600,
    }


def build_tmdb_cache_key(path: str, params: Dict[str, Any]) -> str:
    normalized_params = {
        str(key): str(value)
        for key, value in sorted((params or {}).items(), key=lambda kv: str(kv[0]))
        if str(key).strip()
    }
    return safe_json_dumps(
        {
            "path": str(path or "").strip(),
            "params": normalized_params,
        }
    )


def prune_tmdb_cache(max_entries: int = 900) -> None:
    if len(tmdb_cache_entries) <= max_entries:
        return
    keys = sorted(
        tmdb_cache_entries.keys(),
        key=lambda cache_key: float((tmdb_cache_entries.get(cache_key) or {}).get("saved_at", 0) or 0),
    )
    overflow = max(0, len(keys) - max_entries)
    for key in keys[:overflow]:
        tmdb_cache_entries.pop(key, None)


def parse_tmdb_http_error(exc: Exception) -> str:
    status_code = 0
    if isinstance(exc, urllib.error.HTTPError):
        status_code = int(exc.code or 0)
    base = f"TMDB 请求失败（HTTP {status_code}）" if status_code > 0 else "TMDB 请求失败"
    try:
        body = exc.read().decode("utf-8", errors="ignore") if isinstance(exc, urllib.error.HTTPError) else ""
    except Exception:
        body = ""
    payload = safe_json_loads(body, {})
    if isinstance(payload, dict):
        message = str(payload.get("status_message", "") or payload.get("message", "") or "").strip()
        if message:
            base = f"{base}：{message}"
    if status_code == 401:
        return "TMDB API Key 无效或未授权"
    if status_code == 404:
        return "TMDB 资源不存在"
    if status_code == 429:
        return "TMDB 请求过于频繁，请稍后重试"
    return base


def tmdb_request_json(
    path: str,
    params: Optional[Dict[str, Any]] = None,
    cfg: Optional[Dict[str, Any]] = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    active_cfg = normalize_config(cfg or get_config())
    runtime = get_tmdb_runtime_config(active_cfg)
    if not runtime["enabled"]:
        raise RuntimeError("TMDB 增强未启用，请先在参数配置中开启")
    if not runtime["api_key"]:
        raise RuntimeError("TMDB API Key 未填写")
    proxy_url = build_tg_proxy_url(active_cfg)

    normalized_path = "/" + str(path or "").strip().lstrip("/")
    raw_params = dict(params or {})
    request_params: Dict[str, Any] = {}
    for key, value in raw_params.items():
        token_key = str(key or "").strip()
        if not token_key:
            continue
        token_value = str(value or "").strip()
        if token_value == "":
            continue
        request_params[token_key] = token_value
    request_params.setdefault("language", runtime["language"])
    if runtime["region"] and "region" not in request_params:
        request_params["region"] = runtime["region"]

    cache_key = build_tmdb_cache_key(normalized_path, request_params)
    now = time.time()
    cache_entry = tmdb_cache_entries.get(cache_key)
    ttl_seconds = max(3600, int(runtime.get("cache_ttl_seconds", 24 * 3600) or 24 * 3600))
    if cache_entry and not force_refresh:
        cached_at = float(cache_entry.get("saved_at", 0) or 0)
        if now - cached_at <= ttl_seconds:
            cached_data = cache_entry.get("data")
            if isinstance(cached_data, dict):
                return clone_jsonable(cached_data)
        else:
            tmdb_cache_entries.pop(cache_key, None)

    query_params = {**request_params, "api_key": runtime["api_key"]}
    query = urllib.parse.urlencode(query_params, doseq=True)
    request_url = f"{TMDB_API_BASE_URL}{normalized_path}"
    if query:
        request_url = f"{request_url}?{query}"
    try:
        payload = http_request_json(
            request_url,
            timeout=TMDB_REQUEST_TIMEOUT_SECONDS,
            extra_headers={"Accept": "application/json"},
            proxy_url=proxy_url,
        )
    except urllib.error.HTTPError as exc:
        raise RuntimeError(parse_tmdb_http_error(exc)) from exc
    except urllib.error.URLError as exc:
        reason = format_network_error(exc)
        if proxy_url:
            raise RuntimeError(f"TMDB 网络异常（代理 {proxy_url}）：{reason}") from exc
        raise RuntimeError(f"TMDB 网络异常：{reason}") from exc
    except Exception as exc:
        raise RuntimeError(f"TMDB 请求失败：{exc}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("TMDB 返回格式异常")
    if payload.get("success") is False:
        message = str(payload.get("status_message", "") or payload.get("message", "") or "").strip()
        raise RuntimeError(f"TMDB 返回错误：{message or '未知错误'}")

    tmdb_cache_entries[cache_key] = {"saved_at": now, "data": clone_jsonable(payload)}
    prune_tmdb_cache()
    return payload


def build_tmdb_image_url(path: Any, size: str = "w342") -> str:
    raw_path = str(path or "").strip()
    if not raw_path:
        return ""
    normalized_path = raw_path if raw_path.startswith("/") else f"/{raw_path}"
    normalized_size = str(size or "w342").strip() or "w342"
    if not re.fullmatch(r"(?:w\d+|original)", normalized_size):
        normalized_size = "w342"
    return f"{TMDB_IMAGE_BASE_URL}/{normalized_size}{normalized_path}"


def normalize_tmdb_result_item(item: Dict[str, Any], media_type_hint: str = "") -> Dict[str, Any]:
    payload = item if isinstance(item, dict) else {}
    media_type = normalize_tmdb_media_type(payload.get("media_type", ""), fallback=media_type_hint)
    if not media_type:
        if payload.get("title") is not None or payload.get("release_date") is not None:
            media_type = "movie"
        elif payload.get("name") is not None or payload.get("first_air_date") is not None:
            media_type = "tv"
        else:
            media_type = normalize_tmdb_media_type(media_type_hint, fallback="movie")

    tmdb_id = max(0, parse_int(payload.get("id", 0), 0))
    if tmdb_id <= 0:
        return {}
    if media_type == "movie":
        title = str(payload.get("title", "") or "").strip()
        original_title = str(payload.get("original_title", "") or "").strip()
        date_field = str(payload.get("release_date", "") or "").strip()
    else:
        title = str(payload.get("name", "") or "").strip()
        original_title = str(payload.get("original_name", "") or "").strip()
        date_field = str(payload.get("first_air_date", "") or "").strip()
    if not title:
        return {}

    year = extract_year_from_date(date_field)
    try:
        vote_average = float(payload.get("vote_average", 0) or 0)
    except (TypeError, ValueError):
        vote_average = 0.0
    try:
        popularity = float(payload.get("popularity", 0) or 0)
    except (TypeError, ValueError):
        popularity = 0.0

    return {
        "id": tmdb_id,
        "media_type": media_type,
        "title": title,
        "original_title": original_title,
        "year": year,
        "overview": str(payload.get("overview", "") or "").strip(),
        "poster_url": build_tmdb_image_url(payload.get("poster_path", ""), "w342"),
        "backdrop_url": build_tmdb_image_url(payload.get("backdrop_path", ""), "w780"),
        "vote_average": round(vote_average, 1),
        "popularity": popularity,
    }


def search_tmdb_media(
    query: str,
    media_type: str = "",
    year: str = "",
    cfg: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    keyword = re.sub(r"\s+", " ", str(query or "").strip())
    if not keyword:
        return []

    normalized_year = normalize_tmdb_year(year)
    normalized_media_type = normalize_tmdb_media_type(media_type, fallback="")
    endpoint = f"/search/{normalized_media_type}" if normalized_media_type else "/search/multi"
    params: Dict[str, Any] = {"query": keyword, "include_adult": "false", "page": "1"}
    if normalized_year:
        if normalized_media_type == "movie":
            params["year"] = normalized_year
        elif normalized_media_type == "tv":
            params["first_air_date_year"] = normalized_year
    payload = tmdb_request_json(endpoint, params=params, cfg=cfg)
    raw_results = payload.get("results", []) if isinstance(payload.get("results"), list) else []

    items: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for raw_item in raw_results:
        item = normalize_tmdb_result_item(raw_item if isinstance(raw_item, dict) else {}, normalized_media_type)
        if not item:
            continue
        media = normalize_tmdb_media_type(item.get("media_type", ""), fallback="")
        if media not in ("movie", "tv"):
            continue
        if normalized_media_type and media != normalized_media_type:
            continue
        key = f"{media}:{int(item.get('id', 0) or 0)}"
        if key in seen:
            continue
        seen.add(key)
        items.append(item)

    def sort_key(item: Dict[str, Any]) -> Tuple[int, float, float, int]:
        year_matched = 1 if (normalized_year and str(item.get("year", "")) == normalized_year) else 0
        return (
            year_matched,
            float(item.get("popularity", 0) or 0),
            float(item.get("vote_average", 0) or 0),
            int(item.get("id", 0) or 0),
        )

    items.sort(key=sort_key, reverse=True)
    return items[: TMDB_SEARCH_LIMIT]


def build_tmdb_aliases(detail: Dict[str, Any], media_type: str) -> List[str]:
    aliases: List[str] = []
    alternative_titles = detail.get("alternative_titles", {}) if isinstance(detail.get("alternative_titles"), dict) else {}
    if media_type == "movie":
        records = alternative_titles.get("titles", []) if isinstance(alternative_titles.get("titles"), list) else []
        for item in records:
            title = str((item or {}).get("title", "")).strip() if isinstance(item, dict) else ""
            if title:
                aliases.append(title)
    else:
        records = alternative_titles.get("results", []) if isinstance(alternative_titles.get("results"), list) else []
        for item in records:
            title = str((item or {}).get("title", "")).strip() if isinstance(item, dict) else ""
            if title:
                aliases.append(title)

    translations_root = detail.get("translations", {}) if isinstance(detail.get("translations"), dict) else {}
    translations = translations_root.get("translations", []) if isinstance(translations_root.get("translations"), list) else []
    translation_fields = ("title", "name", "original_title", "original_name")
    for item in translations:
        if not isinstance(item, dict):
            continue
        data = item.get("data", {}) if isinstance(item.get("data"), dict) else {}
        for field in translation_fields:
            title = str(data.get(field, "") or "").strip()
            if title:
                aliases.append(title)
    return unique_preserve_order(aliases)[:24]


def infer_tmdb_episode_mode(detail: Dict[str, Any]) -> str:
    genres = detail.get("genres", []) if isinstance(detail.get("genres"), list) else []
    genre_names = " ".join(str((genre or {}).get("name", "") or "") for genre in genres if isinstance(genre, dict))
    has_animation_genre = any(int((genre or {}).get("id", 0) or 0) == 16 for genre in genres if isinstance(genre, dict))
    has_animation_keyword = bool(re.search(r"(动画|動畫|anime|animation)", genre_names, re.IGNORECASE))
    number_of_seasons = max(0, parse_int(detail.get("number_of_seasons", 0), 0))
    number_of_episodes = max(0, parse_int(detail.get("number_of_episodes", 0), 0))
    if (has_animation_genre or has_animation_keyword) and number_of_seasons >= 2 and number_of_episodes >= 20:
        return "absolute"
    return "seasonal"


def get_tmdb_media_detail(tmdb_id: int, media_type: str, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    normalized_media_type = normalize_tmdb_media_type(media_type, fallback="")
    if normalized_media_type not in ("movie", "tv"):
        raise RuntimeError("TMDB 影视类型仅支持 movie 或 tv")
    normalized_tmdb_id = max(0, int(tmdb_id or 0))
    if normalized_tmdb_id <= 0:
        raise RuntimeError("TMDB ID 无效")

    detail = tmdb_request_json(
        f"/{normalized_media_type}/{normalized_tmdb_id}",
        params={"append_to_response": "alternative_titles,translations"},
        cfg=cfg,
    )
    normalized = normalize_tmdb_result_item(detail, normalized_media_type)
    if not normalized:
        raise RuntimeError("TMDB 详情解析失败")

    aliases = build_tmdb_aliases(detail, normalized_media_type)
    title = str(normalized.get("title", "") or "").strip()
    original_title = str(normalized.get("original_title", "") or "").strip()
    aliases = [alias for alias in aliases if alias not in {title, original_title}]
    payload = {
        **normalized,
        "aliases": aliases,
        "status": str(detail.get("status", "") or "").strip(),
        "total_episodes": 0,
        "total_seasons": 0,
        "season_episode_map": {},
        "episode_mode": "seasonal",
    }
    if normalized_media_type == "tv":
        payload["total_episodes"] = max(0, parse_int(detail.get("number_of_episodes", 0), 0))
        payload["total_seasons"] = max(0, parse_int(detail.get("number_of_seasons", 0), 0))
        season_records = detail.get("seasons", []) if isinstance(detail.get("seasons"), list) else []
        season_episode_map: Dict[str, int] = {}
        for raw_season in season_records:
            if not isinstance(raw_season, dict):
                continue
            season_no = max(0, parse_int(raw_season.get("season_number", 0), 0))
            episode_count = max(0, parse_int(raw_season.get("episode_count", 0), 0))
            if season_no <= 0 or episode_count <= 0:
                continue
            season_episode_map[str(season_no)] = episode_count
        payload["season_episode_map"] = season_episode_map
        payload["episode_mode"] = infer_tmdb_episode_mode(detail)
    return payload


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
        "User-Agent": "Mozilla/5.0 115-media-hub",
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
        "User-Agent": "Mozilla/5.0 115-media-hub",
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
        "User-Agent": "Mozilla/5.0 115-media-hub",
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


def sanitize_115_folder_name(value: str, fallback: str = "未命名") -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", " ", str(value or "")).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip(". ")
    if not cleaned:
        cleaned = fallback
    return cleaned[:120]


def ensure_115_folder_id_by_path(cookie: str, relative_path: str) -> str:
    normalized_path = normalize_relative_path(relative_path)
    if not normalized_path:
        return "0"
    current_cid = "0"
    for raw_part in [segment for segment in normalized_path.split("/") if segment]:
        part = sanitize_115_folder_name(raw_part, fallback="未命名")
        entries = list_115_entries(cookie, current_cid)
        matched = next(
            (
                entry
                for entry in entries
                if entry.get("is_dir") and str(entry.get("name", "")).strip() == part
            ),
            None,
        )
        if matched:
            current_cid = str(matched.get("id", "") or matched.get("cid", "") or "").strip() or "0"
            continue
        created = create_115_folder(cookie, current_cid, part)
        current_cid = str(created.get("id", "")).strip() or current_cid
    return current_cid


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


def parse_115_share_payload(url: str, raw_text: str = "", receive_code: str = "") -> Dict[str, str]:
    source = str(url or "").strip()
    match = RESOURCE_115_SHARE_URL_REGEX.search(source)
    candidate_url = match.group(0) if match else source
    normalized = normalize_115_share_url_candidate(candidate_url)
    share_code = ""
    receive_code_from_url = ""
    parsed_url: Optional[urllib.parse.SplitResult] = None

    if normalized:
        if not normalized.lower().startswith(("http://", "https://")) and re.match(
            r"^(?:115cdn|115|anxia)\.com/",
            normalized,
            flags=re.IGNORECASE,
        ):
            normalized = f"https://{normalized}"
        parsed_url = urllib.parse.urlsplit(normalized)
        path_match = re.search(r"/s/([A-Za-z0-9]+)", parsed_url.path, flags=re.IGNORECASE)
        if path_match:
            share_code = path_match.group(1)
            query_map = {
                str(key or "").lower(): values
                for key, values in urllib.parse.parse_qs(parsed_url.query, keep_blank_values=False).items()
            }
            for key in ("password", "pwd", "receive_code", "access_code", "passcode", "code"):
                values = query_map.get(key) or []
                if not values:
                    continue
                receive_code_from_url = normalize_receive_code(values[0])
                if receive_code_from_url:
                    break
            base_url = f"{parsed_url.scheme or 'https'}://{parsed_url.netloc}/s/{share_code}"
            normalized = f"{base_url}?{parsed_url.query}" if parsed_url.query else base_url

    resolved_receive_code = normalize_receive_code(receive_code) or receive_code_from_url
    if not resolved_receive_code:
        receive_match = TG_EXTRACT_CODE_REGEX.search(str(raw_text or ""))
        if receive_match:
            resolved_receive_code = normalize_receive_code(receive_match.group(1))

    if share_code and resolved_receive_code:
        if parsed_url and parsed_url.netloc:
            normalized = apply_share_receive_code_to_url(
                f"{parsed_url.scheme or 'https'}://{parsed_url.netloc}/s/{share_code}",
                resolved_receive_code,
            )
        else:
            normalized = apply_share_receive_code_to_url(normalized, resolved_receive_code)

    return {
        "share_code": share_code,
        "receive_code": resolved_receive_code,
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


def resolve_115_share_payload(cookie: str, share_url: str, raw_text: str = "", receive_code: str = "") -> Dict[str, str]:
    parsed = parse_115_share_payload(share_url, raw_text, receive_code)
    if parsed.get("share_code"):
        return parsed
    headers = {
        "Cookie": str(cookie or "").strip(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://115.com/",
        "User-Agent": "Mozilla/5.0 115-media-hub",
    }
    resolved = http_resolve_url(share_url, timeout=30, extra_headers=headers)
    parsed = parse_115_share_payload(resolved, raw_text, receive_code)
    if not parsed.get("share_code"):
        raise RuntimeError("未能识别 115 分享链接")
    return parsed


def _build_115_share_snap_cache_key(share_code: str, receive_code: str, cid: str) -> str:
    source = f"{str(share_code or '').strip()}|{str(receive_code or '').strip()}|{str(cid or '0').strip() or '0'}"
    return hashlib.sha1(source.encode("utf-8")).hexdigest()


def _throttle_115_share_snap_requests(rate_limit_seconds: float = 0.0) -> None:
    global _share_snap_last_request_monotonic
    requested_interval = float(rate_limit_seconds or 0.0)
    if requested_interval > 0:
        min_interval = max(0.0, requested_interval)
    else:
        min_interval = max(0.0, float(SHARE_SNAP_RATE_LIMIT_SECONDS or 0.0))
    if min_interval <= 0:
        return
    with _share_snap_rate_limit_lock:
        now_mono = time.monotonic()
        wait_seconds = min_interval - (now_mono - _share_snap_last_request_monotonic)
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        _share_snap_last_request_monotonic = time.monotonic()


def _is_retryable_115_share_snap_error(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return int(getattr(exc, "code", 0) or 0) in (405, 408, 409, 425, 429, 500, 502, 503, 504)
    if isinstance(exc, urllib.error.URLError):
        return True
    message = str(exc or "").strip().lower()
    if not message:
        return False
    if any(token in message for token in ("http error 405", "http error 429", "http error 5")):
        return True
    return any(
        token in message
        for token in (
            "timeout",
            "timed out",
            "temporarily unavailable",
            "connection reset",
            "connection aborted",
            "remote end closed",
            "bad gateway",
            "service unavailable",
            "too many requests",
        )
    )


def load_115_share_snap_cache(
    share_code: str,
    receive_code: str,
    cid: str,
    allow_expired: bool = False,
) -> Dict[str, Any]:
    normalized_share_code = str(share_code or "").strip()
    if not normalized_share_code:
        return {}
    cache_key = _build_115_share_snap_cache_key(normalized_share_code, receive_code, cid)
    ensure_db()
    conn = open_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT payload_json, expires_at FROM share_entries_cache WHERE cache_key = ?", (cache_key,))
        row = cursor.fetchone()
        if not row:
            return {}
        expires_at = str(row["expires_at"] or "").strip()
        now_iso = now_text()
        if (not allow_expired) and expires_at and expires_at <= now_iso:
            return {}
        payload = safe_json_loads(row["payload_json"], {})
        return payload if isinstance(payload, dict) else {}
    finally:
        conn.close()


def save_115_share_snap_cache(
    share_code: str,
    receive_code: str,
    cid: str,
    payload: Dict[str, Any],
    ttl_seconds: int = SHARE_SNAP_CACHE_TTL_SECONDS,
) -> None:
    normalized_share_code = str(share_code or "").strip()
    if not normalized_share_code or not isinstance(payload, dict):
        return
    cache_key = _build_115_share_snap_cache_key(normalized_share_code, receive_code, cid)
    now_iso = now_text()
    expires_at = (datetime.now() + timedelta(seconds=max(1, int(ttl_seconds or SHARE_SNAP_CACHE_TTL_SECONDS)))).isoformat(
        timespec="seconds"
    )
    ensure_db()
    conn = open_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO share_entries_cache(
                cache_key, share_code, receive_code, cid, payload_json, created_at, expires_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cache_key,
                normalized_share_code,
                str(receive_code or "").strip(),
                str(cid or "0").strip() or "0",
                safe_json_dumps(payload),
                now_iso,
                expires_at,
            ),
        )
        cursor.execute("DELETE FROM share_entries_cache WHERE expires_at <> '' AND expires_at <= ?", (now_iso,))
        max_rows = max(200, int(SHARE_SNAP_CACHE_MAX_ROWS or 3000))
        cursor.execute("SELECT COUNT(1) FROM share_entries_cache")
        total_rows = int(cursor.fetchone()[0] or 0)
        if total_rows > max_rows:
            overflow = total_rows - max_rows
            cursor.execute(
                "SELECT cache_key FROM share_entries_cache ORDER BY created_at ASC LIMIT ?",
                (overflow,),
            )
            stale_keys = [str(row["cache_key"] or "").strip() for row in cursor.fetchall() if str(row["cache_key"] or "").strip()]
            if stale_keys:
                placeholders = ",".join(["?"] * len(stale_keys))
                cursor.execute(f"DELETE FROM share_entries_cache WHERE cache_key IN ({placeholders})", tuple(stale_keys))
        conn.commit()
    finally:
        conn.close()


def list_115_share_entries(
    cookie: str,
    share_url: str,
    raw_text: str = "",
    cid: str = "0",
    receive_code: str = "",
    force_refresh: bool = False,
    request_timeout: int = 45,
    rate_limit_seconds: float = 0.0,
    max_request_retries: int = 2,
) -> Dict[str, Any]:
    cookie = str(cookie or "").strip()
    if not cookie:
        raise RuntimeError("115 Cookie 未配置")
    parsed = resolve_115_share_payload(cookie, share_url, raw_text, receive_code)
    share_code = str(parsed.get("share_code", "") or "").strip()
    receive_code = str(parsed.get("receive_code", "") or "").strip()
    current_cid = str(cid or "0").strip() or "0"
    stale_cache = load_115_share_snap_cache(share_code, receive_code, current_cid, allow_expired=True)
    if not force_refresh:
        fresh_cache = load_115_share_snap_cache(share_code, receive_code, current_cid, allow_expired=False)
        if fresh_cache:
            return fresh_cache

    request_timeout_value = max(5, int(request_timeout or 45))
    retry_total = max(0, int(max_request_retries or 0))

    headers = {
        "Cookie": cookie,
        "Accept": "application/json, text/plain, */*",
        "Referer": parsed.get("url", "https://115.com/"),
        "User-Agent": "Mozilla/5.0 115-media-hub",
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
        result: Dict[str, Any] = {}
        last_request_error: Optional[Exception] = None
        for attempt in range(0, retry_total + 1):
            try:
                _throttle_115_share_snap_requests(rate_limit_seconds=rate_limit_seconds)
                result = http_request_json(
                    f"https://webapi.115.com/share/snap?{query}",
                    extra_headers=headers,
                    timeout=request_timeout_value,
                )
                last_request_error = None
                break
            except Exception as exc:
                last_request_error = exc
                if (not _is_retryable_115_share_snap_error(exc)) or attempt >= retry_total:
                    break
                time.sleep(0.6 * (attempt + 1))
        if last_request_error is not None:
            if stale_cache:
                stale_payload = dict(stale_cache)
                stale_payload["cache_stale"] = True
                stale_payload["cache_error"] = str(last_request_error or "").strip()[:180]
                stale_payload["cache_cid"] = current_cid
                return stale_payload
            raise RuntimeError(str(last_request_error or "读取 115 分享内容失败").strip() or "读取 115 分享内容失败")
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
            if stale_cache:
                stale_payload = dict(stale_cache)
                stale_payload["cache_stale"] = True
                stale_payload["cache_error"] = detail[:180]
                stale_payload["cache_cid"] = current_cid
                return stale_payload
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
            result_payload = {
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
            save_115_share_snap_cache(
                share_code,
                receive_code,
                current_cid,
                result_payload,
                ttl_seconds=SHARE_SNAP_CACHE_TTL_SECONDS,
            )
            return result_payload
        offset += len(batch)


def prepare_115_share_receive(
    cookie: str,
    share_url: str,
    raw_text: str = "",
    selected_ids: Optional[List[str]] = None,
    receive_code: str = "",
) -> Dict[str, Any]:
    parsed = resolve_115_share_payload(cookie, share_url, raw_text, receive_code)
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
        snapshot = list_115_share_entries(
            cookie,
            parsed.get("url", share_url),
            raw_text,
            "0",
            str(parsed.get("receive_code", "") or ""),
        )
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


def is_115_share_receive_duplicate_response(response: Any) -> bool:
    payload = response if isinstance(response, dict) else {}
    errno = parse_int(payload.get("errno") or payload.get("errNo") or payload.get("err_no"), default=0)
    if errno == 4100024:
        return True

    message = " ".join(
        [
            str(payload.get("error", "") or "").strip(),
            str(payload.get("msg", "") or "").strip(),
            str(payload.get("message", "") or "").strip(),
            str(payload.get("error_msg", "") or "").strip(),
        ]
    ).strip()
    if not message:
        return False
    normalized_message = message.lower()
    duplicate_hints = (
        "文件已接收",
        "无需重复接收",
        "已接收，无需重复接收",
        "already received",
        "already saved",
        "duplicate receive",
    )
    return any(hint.lower() in normalized_message for hint in duplicate_hints)


def submit_115_share_receive(
    cookie: str,
    share_url: str,
    folder_id: str,
    raw_text: str = "",
    selected_ids: Optional[List[str]] = None,
    receive_code: str = "",
) -> Dict[str, Any]:
    cookie = str(cookie or "").strip()
    if not cookie:
        raise RuntimeError("115 Cookie 未配置")
    prepared = prepare_115_share_receive(cookie, share_url, raw_text, selected_ids, receive_code)

    headers = {
        "Cookie": cookie,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://115.com/",
        "Origin": "https://115.com",
        "User-Agent": "Mozilla/5.0 115-media-hub",
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
    success = bool(response.get("state")) or is_115_share_receive_duplicate_response(response)
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
        "duplicate_receive": is_115_share_receive_duplicate_response(response),
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
        "User-Agent": "Mozilla/5.0 115-media-hub",
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


def fetch_telegram_channel_post_samples(
    cfg: Dict[str, Any],
    source: Dict[str, Any],
    sample_size: int = RESOURCE_CHANNEL_TYPE_SAMPLE_SIZE,
    page_size: int = RESOURCE_CHANNEL_TYPE_PAGE_LIMIT,
    max_pages: int = RESOURCE_CHANNEL_TYPE_MAX_PAGES,
) -> Dict[str, Any]:
    normalized_source = normalize_resource_source(source or {})
    channel_id = normalize_telegram_channel_id_from_input(normalized_source.get("channel_id", ""))
    target = max(1, int(sample_size or RESOURCE_CHANNEL_TYPE_SAMPLE_SIZE))
    fetch_size = max(1, int(page_size or RESOURCE_CHANNEL_TYPE_PAGE_LIMIT))
    pages = max(1, int(max_pages or RESOURCE_CHANNEL_TYPE_MAX_PAGES))
    if not channel_id:
        return {"channel_id": "", "posts": [], "pages_scanned": 0, "next_before": "", "has_more": False}

    before = ""
    collected: List[Dict[str, Any]] = []
    seen_keys: Set[str] = set()
    pages_scanned = 0
    has_more = False

    for _ in range(pages):
        page = fetch_telegram_channel_posts_page(
            cfg,
            normalized_source,
            limit=fetch_size,
            before=before,
            allow_empty=True,
        )
        pages_scanned += 1
        page_posts = page.get("posts", []) if isinstance(page, dict) else []
        for post in page_posts:
            identity = build_resource_item_identity(post)
            if identity in seen_keys:
                continue
            seen_keys.add(identity)
            collected.append(post)
            if len(collected) >= target:
                break
        before = str(page.get("next_before", "") if isinstance(page, dict) else "").strip()
        has_more = bool(page.get("has_more")) if isinstance(page, dict) else False
        if len(collected) >= target or not before or not has_more:
            break

    collected.sort(key=get_resource_item_sort_key, reverse=True)
    return {
        "channel_id": channel_id,
        "posts": collected[:target],
        "pages_scanned": pages_scanned,
        "next_before": before,
        "has_more": bool(before and has_more),
    }


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
