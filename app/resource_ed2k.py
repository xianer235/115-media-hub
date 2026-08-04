import hashlib
import ipaddress
import re
import socket
import urllib.parse
from html.parser import HTMLParser
from typing import Any, Callable, Dict, List, Optional

import requests

from .resource_linking import RESOURCE_ED2K_REGEX, trim_resource_link_token
from .resource_tg import build_tg_proxy_url


ED2K_HASH_REGEX = re.compile(r"^[a-f0-9]{32}$", re.IGNORECASE)
ED2K_PAGE_MAX_BODY_BYTES = 2 * 1024 * 1024
ED2K_PAGE_MAX_REDIRECTS = 4
ED2K_PAGE_ALLOWED_CONTENT_TYPES = (
    "text/html",
    "text/plain",
    "application/xhtml+xml",
)
ED2K_PAGE_ALLOWED_HOST = "telegra.ph"
ED2K_FOLDER_CHARACTER_REPLACEMENTS = str.maketrans(
    {
        "*": "＊",
        "?": "？",
        '"': "＂",
        "<": "＜",
        ">": "＞",
        "|": "｜",
    }
)


def _clean_ed2k_folder_name(value: Any) -> str:
    cleaned = re.sub(r"[\x00-\x1f\x7f]+", "", str(value or ""))
    cleaned = re.sub(r"[\\/]+", " ", cleaned)
    cleaned = cleaned.translate(ED2K_FOLDER_CHARACTER_REPLACEMENTS)
    return re.sub(r"\s+", " ", cleaned).strip()


def normalize_ed2k_folder_name(value: Any, fallback: Any = "") -> str:
    cleaned = _clean_ed2k_folder_name(value)
    if not cleaned or cleaned in (".", ".."):
        cleaned = _clean_ed2k_folder_name(fallback)
    if not cleaned or cleaned in (".", ".."):
        return ""
    return cleaned[:120]


def parse_ed2k_link(value: Any) -> Dict[str, Any]:
    link_url = trim_resource_link_token(str(value or ""))
    parts = link_url.split("|")
    if len(parts) < 6 or parts[0].lower() != "ed2k://" or parts[1].lower() != "file":
        raise ValueError("不是有效的 ED2K 文件链接")
    filename = urllib.parse.unquote(str(parts[2] or "").strip())
    if not filename:
        raise ValueError("ED2K 文件名为空")
    try:
        size_bytes = int(parts[3])
    except (TypeError, ValueError) as exc:
        raise ValueError("ED2K 文件大小无效") from exc
    if size_bytes <= 0:
        raise ValueError("ED2K 文件大小无效")
    file_hash = str(parts[4] or "").strip().lower()
    if not ED2K_HASH_REGEX.fullmatch(file_hash):
        raise ValueError("ED2K 文件哈希无效")
    if parts[-1] != "/":
        raise ValueError("ED2K 文件链接结尾无效")
    identity = hashlib.sha1(f"{file_hash}:{size_bytes}".encode("ascii")).hexdigest()[:20]
    return {
        "id": identity,
        "filename": filename,
        "title": filename,
        "size_bytes": size_bytes,
        "file_hash": file_hash,
        "link_url": link_url,
        "link_type": "ed2k",
    }


def extract_ed2k_items(content: Any) -> List[Dict[str, Any]]:
    seen = set()
    items: List[Dict[str, Any]] = []
    for raw_link in RESOURCE_ED2K_REGEX.findall(str(content or "")):
        try:
            item = parse_ed2k_link(raw_link)
        except ValueError:
            continue
        identity = (item["file_hash"], item["size_bytes"])
        if identity in seen:
            continue
        seen.add(identity)
        items.append(item)
    return items


class _PageTitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._capture = ""
        self._buffers = {"h1": [], "title": []}
        self.og_title = ""

    def handle_starttag(self, tag: str, attrs) -> None:
        normalized = str(tag or "").lower()
        if normalized in self._buffers:
            self._capture = normalized
        if normalized != "meta":
            return
        values = {str(key or "").lower(): str(value or "") for key, value in attrs}
        if values.get("property", "").lower() == "og:title" or values.get("name", "").lower() == "og:title":
            self.og_title = values.get("content", "").strip()

    def handle_endtag(self, tag: str) -> None:
        if str(tag or "").lower() == self._capture:
            self._capture = ""

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buffers[self._capture].append(str(data or ""))

    def value(self, key: str) -> str:
        return " ".join("".join(self._buffers.get(key, [])).split())


def extract_ed2k_page_title(html: Any, fallback: Any = "") -> str:
    parser = _PageTitleParser()
    try:
        parser.feed(str(html or ""))
    except Exception:
        pass
    for candidate in (parser.value("h1"), parser.og_title, parser.value("title"), str(fallback or "")):
        normalized = " ".join(str(candidate or "").split()).strip()
        if normalized:
            return normalized[:300]
    return "ED2K 资源"


def _is_public_ip(value: Any) -> bool:
    try:
        return bool(ipaddress.ip_address(str(value or "").strip()).is_global)
    except ValueError:
        return False


def validate_public_http_url(
    value: Any,
    dns_resolver: Optional[Callable[..., Any]] = None,
) -> str:
    raw_url = str(value or "").strip()
    parsed = urllib.parse.urlsplit(raw_url)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        raise ValueError("只支持公开的 HTTP/HTTPS 外链")
    if parsed.username or parsed.password:
        raise ValueError("外链不能包含账号或密码")
    try:
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    except ValueError as exc:
        raise ValueError("外链端口无效") from exc
    host = str(parsed.hostname or "").strip().rstrip(".")
    if not host:
        raise ValueError("外链域名无效")

    addresses: List[str] = []
    try:
        addresses.append(str(ipaddress.ip_address(host)))
    except ValueError:
        resolver = dns_resolver or socket.getaddrinfo
        try:
            records = resolver(host, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise ValueError("外链域名解析失败") from exc
        for record in records or []:
            sockaddr = record[4] if len(record) > 4 else ()
            if sockaddr:
                addresses.append(str(sockaddr[0] or "").strip())
    if not addresses or any(not _is_public_ip(address) for address in addresses):
        raise ValueError("外链必须指向公网地址")
    return urllib.parse.urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc,
            parsed.path or "/",
            parsed.query,
            "",
        )
    )


def is_allowed_ed2k_page_url(value: Any) -> bool:
    parsed = urllib.parse.urlsplit(str(value or "").strip())
    host = str(parsed.hostname or "").strip().rstrip(".").lower()
    return parsed.scheme.lower() in ("http", "https") and host == ED2K_PAGE_ALLOWED_HOST


def validate_ed2k_page_url(
    value: Any,
    dns_resolver: Optional[Callable[..., Any]] = None,
) -> str:
    if not is_allowed_ed2k_page_url(value):
        raise ValueError("当前仅支持 telegra.ph 电驴页面")
    return validate_public_http_url(value, dns_resolver=dns_resolver)


def _read_limited_text_response(response: Any) -> str:
    content_type = str(response.headers.get("Content-Type", "") or "").split(";", 1)[0].strip().lower()
    if content_type not in ED2K_PAGE_ALLOWED_CONTENT_TYPES:
        raise RuntimeError("外链返回的不是可解析文本页面")
    content_length = str(response.headers.get("Content-Length", "") or "").strip()
    if content_length:
        try:
            if int(content_length) > ED2K_PAGE_MAX_BODY_BYTES:
                raise RuntimeError("外链页面内容超过 2 MiB 限制")
        except ValueError:
            pass
    chunks: List[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > ED2K_PAGE_MAX_BODY_BYTES:
            raise RuntimeError("外链页面内容超过 2 MiB 限制")
        chunks.append(bytes(chunk))
    encoding = str(getattr(response, "encoding", "") or "utf-8").strip() or "utf-8"
    try:
        return b"".join(chunks).decode(encoding, errors="replace")
    except LookupError:
        return b"".join(chunks).decode("utf-8", errors="replace")


def resolve_ed2k_page(
    url: Any,
    cfg: Optional[Dict[str, Any]] = None,
    fallback_title: Any = "",
    session: Optional[requests.Session] = None,
    dns_resolver: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    source_url = validate_ed2k_page_url(url, dns_resolver=dns_resolver)
    active_cfg = cfg if isinstance(cfg, dict) else {}
    proxy_url = build_tg_proxy_url(active_cfg)
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else {}
    http = session or requests.Session()
    http.trust_env = False
    current_url = source_url

    for redirect_count in range(ED2K_PAGE_MAX_REDIRECTS + 1):
        response = http.get(
            current_url,
            headers={
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
                "User-Agent": "Mozilla/5.0 115-media-hub ED2K resolver",
            },
            allow_redirects=False,
            proxies=proxies,
            stream=True,
            timeout=(6, 20),
        )
        try:
            status_code = int(getattr(response, "status_code", 0) or 0)
            if status_code in (301, 302, 303, 307, 308):
                location = str(response.headers.get("Location", "") or "").strip()
                if not location:
                    raise RuntimeError("外链跳转响应缺少目标地址")
                if redirect_count >= ED2K_PAGE_MAX_REDIRECTS:
                    raise RuntimeError("外链跳转次数过多")
                current_url = validate_ed2k_page_url(
                    urllib.parse.urljoin(current_url, location),
                    dns_resolver=dns_resolver,
                )
                continue
            if status_code < 200 or status_code >= 300:
                raise RuntimeError(f"外链请求失败（HTTP {status_code or '未知'}）")
            html = _read_limited_text_response(response)
        finally:
            response.close()
        items = extract_ed2k_items(html)
        if not items:
            raise RuntimeError("外链页面中未识别到有效 ED2K 文件链接")
        return {
            "source_url": source_url,
            "final_url": current_url,
            "title": extract_ed2k_page_title(html, fallback=fallback_title),
            "items": items,
            "item_count": len(items),
            "proxy_used": bool(proxy_url),
        }
    raise RuntimeError("外链跳转次数过多")


__all__ = [
    "extract_ed2k_items",
    "extract_ed2k_page_title",
    "normalize_ed2k_folder_name",
    "parse_ed2k_link",
    "resolve_ed2k_page",
    "is_allowed_ed2k_page_url",
    "validate_ed2k_page_url",
    "validate_public_http_url",
]
