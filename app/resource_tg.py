import os
import re
import ssl
import time
import urllib.error
import urllib.parse
from html import unescape
from typing import Any, Dict, List, Set

from .http_utils import http_request_text_with_final_url, normalize_http_url
from .resource_identity import (
    build_resource_item_identity,
    build_telegram_channel_page_url,
    build_telegram_channel_url,
    extract_telegram_post_cursor,
    get_resource_item_sort_key,
    normalize_telegram_channel_id_from_input,
)
from .resource_linking import (
    RESOURCE_MAGNET_REGEX,
    RESOURCE_URL_REGEX,
    RESOURCE_YEAR_REGEX,
    choose_resource_link,
    detect_resource_link_type,
    guess_resource_quality,
    pick_resource_title,
    strip_html_to_text,
)


RESOURCE_CHANNEL_TYPE_SAMPLE_SIZE = max(5, int(os.environ.get("RESOURCE_CHANNEL_TYPE_SAMPLE_SIZE", 10) or 10))
RESOURCE_CHANNEL_TYPE_PAGE_LIMIT = max(10, int(os.environ.get("RESOURCE_CHANNEL_TYPE_PAGE_LIMIT", 20) or 20))
RESOURCE_CHANNEL_TYPE_MAX_PAGES = max(1, int(os.environ.get("RESOURCE_CHANNEL_TYPE_MAX_PAGES", 6) or 6))
TG_SEARCH_PAGE_LIMIT = max(10, int(os.environ.get("TG_SEARCH_PAGE_LIMIT", 20) or 20))
TG_SEARCH_MAX_PAGES = max(1, int(os.environ.get("TG_SEARCH_MAX_PAGES", 3) or 3))
TG_SEARCH_MATCH_LIMIT_PER_CHANNEL = max(1, int(os.environ.get("TG_SEARCH_MATCH_LIMIT_PER_CHANNEL", 12) or 12))
TG_SEARCH_TOTAL_LIMIT = max(TG_SEARCH_MATCH_LIMIT_PER_CHANNEL, int(os.environ.get("TG_SEARCH_TOTAL_LIMIT", 60) or 60))
TG_SEARCH_CHANNEL_TIMEOUT_SECONDS = max(
    5,
    min(60, int(os.environ.get("TG_SEARCH_CHANNEL_TIMEOUT_SECONDS", 10) or 10)),
)
TG_SEARCH_REQUEST_TIMEOUT_SECONDS = max(
    3,
    min(45, int(os.environ.get("TG_SEARCH_REQUEST_TIMEOUT_SECONDS", 8) or 8)),
)
TG_SEARCH_RETRY_ATTEMPTS = max(
    1,
    min(3, int(os.environ.get("TG_SEARCH_RETRY_ATTEMPTS", 1) or 1)),
)
TG_CHANNEL_THREADS_MAX = 20
TG_CHANNEL_THREADS_DEFAULT = max(1, min(TG_CHANNEL_THREADS_MAX, int(os.environ.get("TG_CHANNEL_THREADS_DEFAULT", 6) or 6)))
TG_FETCH_RETRY_ATTEMPTS = max(1, int(os.environ.get("TG_FETCH_RETRY_ATTEMPTS", 3) or 3))
TG_FETCH_RETRY_DELAY_SECONDS = max(0.2, float(os.environ.get("TG_FETCH_RETRY_DELAY_SECONDS", 0.8) or 0.8))

TG_WIDGET_POST_REGEX = re.compile(r'<div[^>]+class="tgme_widget_message[^"]*"[^>]+data-post="([^"]+)"[^>]*>', re.IGNORECASE)
TG_LINK_HREF_REGEX = re.compile(r'href="([^"]+)"', re.IGNORECASE)
TG_IMAGE_STYLE_REGEX = re.compile(r"background-image:url\('([^']+)'\)", re.IGNORECASE)
TG_PREV_BEFORE_REGEX = re.compile(r'rel="prev"[^>]+href="[^"]*before=([^"&]+)', re.IGNORECASE)


def _unique_preserve_order(values: List[str]) -> List[str]:
    seen: Set[str] = set()
    result: List[str] = []
    for value in values:
        token = str(value or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        result.append(token)
    return result


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
        all_links = _unique_preserve_order(external_links + inline_links)
        link_url = choose_resource_link(all_links)
        if not raw_text and not link_url:
            continue
        image_match = TG_IMAGE_STYLE_REGEX.search(chunk)
        post_url = unescape(message_url_match.group(1)) if message_url_match else ""
        item_title = pick_resource_title(raw_text)
        year_match = RESOURCE_YEAR_REGEX.search(raw_text)
        item = {
            "source_type": "tg",
            "source_name": str(source.get("name", "")).strip() or channel_id,
            "channel_name": channel_id,
            "title": item_title,
            "normalized_title": item_title.lower(),
            "raw_text": raw_text,
            "link_url": link_url,
            "link_type": detect_resource_link_type(link_url),
            "message_url": post_url,
            "quality": guess_resource_quality(raw_text),
            "year": (year_match.group(1) if year_match else ""),
            "published_at": datetime_match.group(1) if datetime_match else "",
            "extra": {
                "cover_url": unescape(image_match.group(1)) if image_match else "",
                "source_post_id": match.group(1),
                "source_url": build_telegram_channel_url(channel_id),
                "all_links": all_links[:40],
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
    timeout_seconds: int = 45,
    retry_attempts: int = TG_FETCH_RETRY_ATTEMPTS,
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
    request_timeout = max(3, min(60, int(timeout_seconds or 45)))
    attempts = max(1, min(5, int(retry_attempts or TG_FETCH_RETRY_ATTEMPTS)))
    for attempt in range(1, attempts + 1):
        try:
            html, final_url = http_request_text_with_final_url(
                request_url,
                timeout=request_timeout,
                extra_headers=headers,
                proxy_url=proxy_url,
            )
            break
        except Exception as exc:
            is_retryable = is_retryable_telegram_request_error(exc)
            if attempt >= attempts or not is_retryable:
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
    normalized_source = source if isinstance(source, dict) else {}
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


__all__ = [
    "RESOURCE_CHANNEL_TYPE_SAMPLE_SIZE",
    "RESOURCE_CHANNEL_TYPE_PAGE_LIMIT",
    "RESOURCE_CHANNEL_TYPE_MAX_PAGES",
    "TG_SEARCH_PAGE_LIMIT",
    "TG_SEARCH_MAX_PAGES",
    "TG_SEARCH_MATCH_LIMIT_PER_CHANNEL",
    "TG_SEARCH_TOTAL_LIMIT",
    "TG_SEARCH_CHANNEL_TIMEOUT_SECONDS",
    "TG_SEARCH_REQUEST_TIMEOUT_SECONDS",
    "TG_SEARCH_RETRY_ATTEMPTS",
    "TG_CHANNEL_THREADS_MAX",
    "TG_CHANNEL_THREADS_DEFAULT",
    "TG_FETCH_RETRY_ATTEMPTS",
    "TG_FETCH_RETRY_DELAY_SECONDS",
    "TG_WIDGET_POST_REGEX",
    "TG_LINK_HREF_REGEX",
    "TG_IMAGE_STYLE_REGEX",
    "TG_PREV_BEFORE_REGEX",
    "build_tg_proxy_url",
    "get_tg_channel_threads",
    "format_network_error",
    "unwrap_network_error",
    "is_retryable_telegram_request_error",
    "is_expected_telegram_channel_url",
    "test_telegram_latency",
    "parse_telegram_posts_page",
    "fetch_telegram_channel_posts_page",
    "fetch_telegram_channel_posts",
    "fetch_telegram_channel_post_samples",
]
