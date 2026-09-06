import hashlib
import re
import urllib.parse
from html import unescape
from typing import Any, Dict, List, Tuple

from .media_tags import format_media_tag_summary


RESOURCE_MAGNET_REGEX = re.compile(r"magnet:\?xt=urn:btih:[A-Za-z0-9]{32,40}[^\s<>'\"]*", re.IGNORECASE)
RESOURCE_MAGNET_HASH_REGEX = re.compile(r"xt=urn:btih:([A-Za-z0-9]{32,40})", re.IGNORECASE)
RESOURCE_ED2K_REGEX = re.compile(
    r"ed2k://\|file\|[^\r\n|<>'\"]+\|\d+\|[a-f0-9]{32}\|"
    r"(?:[^/|\r\n<>'\"][^|\r\n<>'\"]*\|)*/",
    re.IGNORECASE,
)
RESOURCE_ED2K_HASH_REGEX = re.compile(
    r"ed2k://\|file\|[^\r\n|<>'\"]+\|\d+\|([a-f0-9]{32})\|",
    re.IGNORECASE,
)
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
    ("123pan", re.compile(r"https?://(?:www\.)?(?:123pan|123684|123865|123912)\.(?:com|cn)/s/[a-z0-9_-]+(?:\.html?)?", re.IGNORECASE)),
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
    matches = []
    for pattern, priority in (
        (RESOURCE_MAGNET_REGEX, 0),
        (RESOURCE_ED2K_REGEX, 1),
        (RESOURCE_URL_REGEX, 2),
        (RESOURCE_115_SHARE_BARE_URL_REGEX, 3),
    ):
        for match in pattern.finditer(raw):
            matches.append((match.start(), priority, match.group(0)))
    matches.sort(key=lambda item: (item[0], item[1]))

    normalized_links: List[str] = []
    for _, _, link in matches:
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
    return format_media_tag_summary(text, separator=" / ")


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


def extract_ed2k_hash(link_url: str) -> str:
    token = trim_resource_link_token(link_url)
    if not token:
        return ""
    match = RESOURCE_ED2K_HASH_REGEX.search(token)
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


def pick_ed2k_title(link_url: str, index: int = 0) -> str:
    token = trim_resource_link_token(link_url)
    parts = token.split("|")
    if len(parts) >= 3 and parts[0].lower() == "ed2k://" and parts[1].lower() == "file":
        filename = urllib.parse.unquote(str(parts[2] or "").strip())
        if filename:
            normalized = normalize_resource_title(filename)
            if normalized and not is_resource_title_link_like(normalized):
                return normalized
    if index > 0:
        return f"ED2K任务 #{index}"
    return "ED2K任务"


def pick_link_fallback_title(link_type: str, link_url: str, index: int = 0) -> str:
    normalized_type = str(link_type or "").strip().lower()
    if normalized_type == "magnet":
        return pick_magnet_title(link_url, index=index)
    if normalized_type == "115share":
        return f"115分享任务 #{index}" if index > 0 else "115分享任务"
    if normalized_type == "quark":
        return f"夸克分享任务 #{index}" if index > 0 else "夸克分享任务"
    if normalized_type == "ed2k":
        return pick_ed2k_title(link_url, index=index)
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


def normalize_resource_link_record(value: Any, raw_text: str = "") -> Dict[str, str]:
    raw_record = value if isinstance(value, dict) else {}
    raw_link = raw_record.get("link_url", "") if raw_record else value
    link_url = normalize_115_share_url_candidate(str(raw_link or ""))
    link_url = trim_resource_link_token(link_url)
    if not link_url:
        return {}

    link_type = resolve_resource_link_type(str(raw_record.get("link_type", "") or ""), link_url)
    receive_code = normalize_receive_code(raw_record.get("receive_code", ""))
    if link_type == "115share":
        parsed_payload = parse_115_share_payload(link_url, raw_text, receive_code)
        link_url = str(parsed_payload.get("url", "") or link_url).strip() or link_url
        link_type = detect_resource_link_type(link_url)
        receive_code = normalize_receive_code(parsed_payload.get("receive_code", ""))
    elif link_type == "quark":
        parsed_payload = parse_quark_share_payload(link_url, raw_text, receive_code)
        link_url = str(parsed_payload.get("url", "") or link_url).strip() or link_url
        link_type = detect_resource_link_type(link_url)
        receive_code = normalize_receive_code(parsed_payload.get("receive_code", ""))

    return {
        "link_url": link_url,
        "link_type": link_type or "unknown",
        "receive_code": receive_code,
    }


def build_resource_link_records(raw_text: str, links: List[Any] = None) -> List[Dict[str, str]]:
    raw = str(raw_text or "")
    source_links = extract_resource_links(raw) if links is None else list(links or [])
    records: List[Dict[str, str]] = []
    seen = set()
    for value in source_links:
        record = normalize_resource_link_record(value, raw)
        link_url = str(record.get("link_url", "") or "").strip()
        if not link_url:
            continue
        fingerprint = link_url.lower()
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        records.append(record)
    return records


def get_resource_link_records(item: Dict[str, Any]) -> List[Dict[str, str]]:
    payload = item if isinstance(item, dict) else {}
    extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
    raw_text = str(payload.get("raw_text", "") or "")
    structured = extra.get("resource_links") if isinstance(extra, dict) else None
    if isinstance(structured, list) and structured:
        return build_resource_link_records(raw_text, structured)

    legacy_links: List[Any] = []
    primary_link = str(payload.get("link_url", "") or "").strip()
    if primary_link:
        legacy_links.append(
            {
                "link_url": primary_link,
                "link_type": payload.get("link_type", ""),
                "receive_code": payload.get("receive_code", "") or extra.get("receive_code", ""),
            }
        )
    legacy_links.extend(extra.get("all_links", []) if isinstance(extra.get("all_links"), list) else [])
    return build_resource_link_records(raw_text, legacy_links)


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

    link_records = build_resource_link_records(raw)
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

    if not link_records:
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
    multi = len(link_records) > 1
    for idx, link_record in enumerate(link_records, start=1):
        normalized_link = str(link_record.get("link_url", "") or "").strip()
        link_type = str(link_record.get("link_type", "unknown") or "unknown").strip()
        receive_code = normalize_receive_code(link_record.get("receive_code", ""))
        if base_title_link_like:
            title = pick_link_fallback_title(link_type, normalized_link, idx if multi else 0)
        elif multi:
            title = f"{base_title} #{idx}"
        else:
            title = base_title
        extra: Dict[str, Any] = {"resource_links": [link_record]}
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
    "RESOURCE_ED2K_HASH_REGEX",
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
    "extract_ed2k_hash",
    "pick_magnet_title",
    "pick_ed2k_title",
    "pick_link_fallback_title",
    "parse_115_share_payload",
    "parse_quark_share_payload",
    "normalize_resource_link_record",
    "build_resource_link_records",
    "get_resource_link_records",
    "extract_resource_candidates",
    "build_content_fingerprint",
]
