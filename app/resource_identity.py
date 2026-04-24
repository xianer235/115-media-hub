import re
import urllib.parse
from datetime import datetime
from typing import Any, Dict, List, Set, Tuple


def _parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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


def normalize_resource_identity_mode(value: Any, fallback: str = "message") -> str:
    normalized_fallback = str(fallback or "message").strip().lower()
    normalized = str(value or "").strip().lower()
    if normalized in ("message", "link"):
        return normalized
    return "link" if normalized_fallback == "link" else "message"


def build_resource_item_identity_by_mode(item: Dict[str, Any], identity_mode: str = "message") -> str:
    payload = item if isinstance(item, dict) else {}
    normalized_identity_mode = normalize_resource_identity_mode(identity_mode, fallback="message")
    if normalized_identity_mode == "link":
        link_url = str(payload.get("link_url", "")).strip()
        if link_url:
            return f"link:{link_url}"
    return build_resource_item_identity(payload)


def dedupe_resource_item_dicts(items: List[Dict[str, Any]], identity_mode: str = "message") -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for item in items:
        key = build_resource_item_identity_by_mode(item, identity_mode=identity_mode)
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
    cursor = _parse_int(
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


__all__ = [
    "normalize_telegram_channel_id_from_input",
    "build_telegram_channel_url",
    "build_telegram_channel_page_url",
    "extract_telegram_post_cursor",
    "resolve_resource_item_published_at",
    "parse_resource_datetime_to_timestamp",
    "build_resource_item_identity",
    "normalize_resource_identity_mode",
    "build_resource_item_identity_by_mode",
    "dedupe_resource_item_dicts",
    "build_resource_search_text",
    "resource_item_matches_search",
    "get_resource_item_sort_key",
    "get_resource_item_post_cursor",
]
