import asyncio
import contextvars
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set

from ..core import *  # noqa: F401,F403


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
SUBSCRIPTION_CANDIDATE_SCAN_PREFETCH_LIMIT = max(
    0,
    min(80, int(os.getenv("SUBSCRIPTION_CANDIDATE_SCAN_PREFETCH_LIMIT", "24") or 24)),
)
SUBSCRIPTION_QUARK_CANDIDATE_SCAN_CONCURRENCY = max(
    1,
    min(6, int(os.getenv("SUBSCRIPTION_QUARK_CANDIDATE_SCAN_CONCURRENCY", "3") or 3)),
)
SUBSCRIPTION_115_CANDIDATE_SCAN_CONCURRENCY = max(
    1,
    min(6, int(os.getenv("SUBSCRIPTION_115_CANDIDATE_SCAN_CONCURRENCY", "2") or 2)),
)
SUBSCRIPTION_SHARE_SCAN_NORMAL_MAX_ENTRIES = max(
    0,
    min(50000, int(os.getenv("SUBSCRIPTION_SHARE_SCAN_NORMAL_MAX_ENTRIES", "5000") or 5000)),
)
SUBSCRIPTION_SHARE_SCAN_HIGH_PRIORITY_MAX_ENTRIES = max(
    SUBSCRIPTION_SHARE_SCAN_NORMAL_MAX_ENTRIES,
    min(100000, int(os.getenv("SUBSCRIPTION_SHARE_SCAN_HIGH_PRIORITY_MAX_ENTRIES", "15000") or 15000)),
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


def _expand_subscription_115_item_variants(item: Dict[str, Any]) -> List[Dict[str, Any]]:
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
        link_type = detect_resource_link_type(normalized_link)
        if link_type not in {"115share", "magnet"}:
            continue
        normalized_url = normalized_link
        resolved_receive_code = ""
        variant_extra = extra_payload.copy() if isinstance(extra_payload, dict) else {}
        if link_type == "115share":
            parsed = parse_115_share_payload(normalized_link, raw_text, default_receive_code)
            normalized_url = _normalize_subscription_candidate_link(parsed.get("url", "") or normalized_link)
            resolved_receive_code = normalize_receive_code(parsed.get("receive_code", "")) or default_receive_code
            share_code = str(parsed.get("share_code", "") or "").strip()
            if share_code:
                variant_extra["share_code"] = share_code
            if resolved_receive_code:
                variant_extra["receive_code"] = resolved_receive_code
        dedupe_key = f"{link_type}:{normalized_url.lower()}|{resolved_receive_code.lower()}"
        if dedupe_key in seen_variant_keys:
            continue
        seen_variant_keys.add(dedupe_key)
        variants.append(
            {
                **payload,
                "link_url": normalized_url,
                "link_type": link_type,
                "receive_code": resolved_receive_code,
                "extra": variant_extra,
            }
        )
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


__all__ = [
    "_normalize_subscription_candidate_link",
    "_build_subscription_quark_share_dedupe_key",
    "_collect_subscription_item_all_links",
    "_expand_subscription_quark_item_variants",
    "_expand_subscription_115_item_variants",
    "_build_subscription_share_entry_runtime_key",
    "_fetch_subscription_share_entries",
    "_ensure_subscription_invalid_link_cache_table",
    "_prune_subscription_invalid_link_cache",
    "_load_subscription_invalid_link_cache",
    "_record_subscription_invalid_link_cache",
    "_is_subscription_invalid_link_error",
    "SUBSCRIPTION_INVALID_LINK_CACHE_TTL_SECONDS",
    "SUBSCRIPTION_DUPLICATE_VERIFY_RETRIES",
    "SUBSCRIPTION_DUPLICATE_VERIFY_DELAY_SECONDS",
    "SUBSCRIPTION_SHARE_SCAN_CONCURRENCY",
    "SUBSCRIPTION_SHARE_SCAN_REQUEST_TIMEOUT_SECONDS",
    "SUBSCRIPTION_SHARE_SCAN_RATE_LIMIT_SECONDS",
    "SUBSCRIPTION_SHARE_SCAN_MAX_RETRIES",
    "SUBSCRIPTION_CANDIDATE_SCAN_PREFETCH_LIMIT",
    "SUBSCRIPTION_QUARK_CANDIDATE_SCAN_CONCURRENCY",
    "SUBSCRIPTION_115_CANDIDATE_SCAN_CONCURRENCY",
    "SUBSCRIPTION_SHARE_SCAN_NORMAL_MAX_ENTRIES",
    "SUBSCRIPTION_SHARE_SCAN_HIGH_PRIORITY_MAX_ENTRIES",
    "SUBSCRIPTION_QUARK_MAX_ATTEMPTS",
    "SUBSCRIPTION_INVALID_LINK_STRONG_HINTS",
    "SUBSCRIPTION_INVALID_LINK_TRANSIENT_HINTS",
    "_subscription_share_entry_runtime_cache_var",
    "_subscription_share_entry_refreshed_keys_var",
]
