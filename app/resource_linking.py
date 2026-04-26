import hashlib
import re
import urllib.parse
from html import unescape
from typing import Any, Dict, List, Tuple


RESOURCE_MAGNET_REGEX = re.compile(r"magnet:\?xt=urn:btih:[A-Za-z0-9]{32,40}[^\s<>'\"]*", re.IGNORECASE)
RESOURCE_MAGNET_HASH_REGEX = re.compile(r"xt=urn:btih:([A-Za-z0-9]{32,40})", re.IGNORECASE)
RESOURCE_ED2K_REGEX = re.compile(r"ed2k://[^\s<>'\"]+", re.IGNORECASE)
RESOURCE_URL_REGEX = re.compile(r"https?://[^\s<>'\"]+", re.IGNORECASE)
RESOURCE_115_SHARE_URL_REGEX = re.compile(
    r"(?:https?://)?(?:115cdn|115|anxia)\.com/s/[A-Za-z0-9]+(?:\?[^\s<>'\"#]*)?(?:#[A-Za-z0-9]{1,16})?",
    re.IGNORECASE,
)
RESOURCE_115_SHARE_BARE_URL_REGEX = re.compile(
    r"(?:115cdn|115|anxia)\.com/s/[A-Za-z0-9]+(?:\?[^\s<>'\"#]*)?(?:#[A-Za-z0-9]{1,16})?",
    re.IGNORECASE,
)
RESOURCE_QUARK_SHARE_URL_REGEX = re.compile(
    r"(?:https?://)?(?:pan|www)\.quark\.cn/s/[A-Za-z0-9]+(?:\?[^\s<>'\"]*)?",
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
TG_EXTRACT_CODE_REGEX = re.compile(
    r"(?:提取码|提取碼|访问码|訪問碼|密码|密碼|访问密码|訪問密碼|口令|pwd|pass(?:word|code)?|code)\s*(?:[:：=]|是|为|為)?\s*([A-Za-z0-9]{4,8})\b",
    re.IGNORECASE,
)
RESOURCE_CJK_TEXT_REGEX = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def unique_preserve_order(values: List[str]) -> List[str]:
    seen = set()
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


def normalize_resource_title(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    return cleaned[:200]


def contains_cjk_text(value: Any) -> bool:
    return bool(RESOURCE_CJK_TEXT_REGEX.search(str(value or "").strip()))


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
    if normalized_type == "quark":
        return f"夸克分享任务 #{index}" if index > 0 else "夸克分享任务"
    if normalized_type == "ed2k":
        return f"ED2K任务 #{index}" if index > 0 else "ED2K任务"
    if normalized_type == "link":
        return f"链接任务 #{index}" if index > 0 else "链接任务"
    return f"资源任务 #{index}" if index > 0 else "资源任务"


def parse_115_share_payload(url: str, raw_text: str = "", receive_code: str = "") -> Dict[str, str]:
    source = str(url or "").strip()
    match = RESOURCE_115_SHARE_URL_REGEX.search(source)
    candidate_url = match.group(0) if match else source
    normalized = normalize_115_share_url_candidate(candidate_url)
    share_code = ""
    receive_code_from_url = ""
    parsed_url = None

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
            if not receive_code_from_url:
                receive_code_from_url = normalize_receive_code(urllib.parse.unquote(parsed_url.fragment or ""))
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


def parse_quark_share_payload(url: str, raw_text: str = "", receive_code: str = "") -> Dict[str, str]:
    source = str(url or "").strip()
    match = RESOURCE_QUARK_SHARE_URL_REGEX.search(source)
    candidate_url = match.group(0) if match else source
    normalized = str(candidate_url or "").strip()
    if normalized and not normalized.lower().startswith(("http://", "https://")):
        normalized = f"https://{normalized.lstrip('/')}"

    pwd_id = ""
    receive_code_from_url = ""
    parsed_url = None
    if normalized:
        parsed_url = urllib.parse.urlsplit(normalized)
        path_match = re.search(r"/s/([A-Za-z0-9]+)", parsed_url.path, flags=re.IGNORECASE)
        if path_match:
            pwd_id = str(path_match.group(1) or "").strip()
            query_map = {
                str(key or "").lower(): values
                for key, values in urllib.parse.parse_qs(parsed_url.query, keep_blank_values=False).items()
            }
            for key in ("password", "pwd", "receive_code", "passcode", "access_code", "code"):
                values = query_map.get(key) or []
                if not values:
                    continue
                receive_code_from_url = normalize_receive_code(values[0])
                if receive_code_from_url:
                    break
            base_url = f"{parsed_url.scheme or 'https'}://{parsed_url.netloc}/s/{pwd_id}" if pwd_id else normalized
            normalized = f"{base_url}?{parsed_url.query}" if parsed_url.query else base_url

    resolved_receive_code = normalize_receive_code(receive_code) or receive_code_from_url
    if not resolved_receive_code:
        receive_match = TG_EXTRACT_CODE_REGEX.search(str(raw_text or ""))
        if receive_match:
            resolved_receive_code = normalize_receive_code(receive_match.group(1))

    return {
        "share_code": pwd_id,
        "pwd_id": pwd_id,
        "receive_code": resolved_receive_code,
        "url": normalized,
    }


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
        elif link_type == "quark":
            parsed_payload = parse_quark_share_payload(normalized_link, raw)
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


def build_content_fingerprint(*parts: Any) -> str:
    seed = "||".join(str(part or "") for part in parts)
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()


__all__ = [
    "RESOURCE_MAGNET_REGEX",
    "RESOURCE_MAGNET_HASH_REGEX",
    "RESOURCE_ED2K_REGEX",
    "RESOURCE_URL_REGEX",
    "RESOURCE_115_SHARE_URL_REGEX",
    "RESOURCE_115_SHARE_BARE_URL_REGEX",
    "RESOURCE_QUARK_SHARE_URL_REGEX",
    "RESOURCE_YEAR_REGEX",
    "RESOURCE_LINK_TYPE_PATTERNS",
    "TG_EXTRACT_CODE_REGEX",
    "RESOURCE_CJK_TEXT_REGEX",
    "normalize_receive_code",
    "trim_resource_link_token",
    "normalize_115_share_url_candidate",
    "extract_resource_links",
    "apply_share_receive_code_to_url",
    "strip_html_to_text",
    "choose_resource_link",
    "normalize_resource_title",
    "contains_cjk_text",
    "guess_resource_quality",
    "detect_resource_link_type",
    "resolve_resource_link_type",
    "pick_resource_title",
    "is_resource_title_link_like",
    "extract_magnet_hash",
    "pick_magnet_title",
    "pick_link_fallback_title",
    "parse_115_share_payload",
    "parse_quark_share_payload",
    "extract_resource_candidates",
    "build_content_fingerprint",
]
