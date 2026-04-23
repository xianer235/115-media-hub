import base64
from http.cookies import SimpleCookie
from typing import Iterator

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response, StreamingResponse

from ..core import *  # noqa: F401,F403

router = APIRouter()

_PICK_CODE_REGEX = re.compile(r"^[A-Za-z0-9]{6,32}$")
_download_url_cache_lock = threading.Lock()
_download_url_cache: Dict[str, Dict[str, Any]] = {}
_relay_token_cache_lock = threading.Lock()
_relay_token_cache: Dict[str, Dict[str, Any]] = {}
_pick_code_path_cache_lock = threading.Lock()
_pick_code_path_cache: Dict[str, Dict[str, Any]] = {}
_folder_cid_path_cache_lock = threading.Lock()
_folder_cid_path_cache: Dict[str, Dict[str, Any]] = {}
_PICK_CODE_PATH_CACHE_TTL_SECONDS = max(
    60,
    min(24 * 60 * 60, int(os.environ.get("API_115_PICKCODE_CACHE_TTL_SECONDS", 2 * 60 * 60) or (2 * 60 * 60))),
)
_FOLDER_CID_PATH_CACHE_TTL_SECONDS = max(
    60,
    min(24 * 60 * 60, int(os.environ.get("API_115_FOLDER_CID_CACHE_TTL_SECONDS", 2 * 60 * 60) or (2 * 60 * 60))),
)
_RELAY_STREAM_CHUNK_SIZE = max(
    32 * 1024,
    min(1024 * 1024, int(os.environ.get("STRM_RELAY_CHUNK_SIZE", 256 * 1024) or (256 * 1024))),
)
_RSA_115_MODULUS = int(
    (
        "8686980c0f5a24c4b9d43020cd2c22703ff3f450756529058b1cf88f09b8602136477198a6e2683149659bd122c33592"
        "fdb5ad47944ad1ea4d36c6b172aad6338c3bb6ac6227502d010993ac967d1aef00f0c8e038de2e4d3bc2ec368af2e9f10a6f"
        "1eda4f7262f136420c07c331b871bf139f74f3010e3c4fe57df3afb71683"
    ),
    16,
)
_RSA_115_EXPONENT = int("10001", 16)
_M115_G_KTS = [
    240,
    229,
    105,
    174,
    191,
    220,
    191,
    138,
    26,
    69,
    232,
    190,
    125,
    166,
    115,
    184,
    222,
    143,
    231,
    196,
    69,
    218,
    134,
    196,
    155,
    100,
    139,
    20,
    106,
    180,
    241,
    170,
    56,
    1,
    53,
    158,
    38,
    105,
    44,
    134,
    0,
    107,
    79,
    165,
    54,
    52,
    98,
    166,
    42,
    150,
    104,
    24,
    242,
    74,
    253,
    189,
    107,
    151,
    143,
    77,
    143,
    137,
    19,
    183,
    108,
    142,
    147,
    237,
    14,
    13,
    72,
    62,
    215,
    47,
    136,
    216,
    254,
    254,
    126,
    134,
    80,
    149,
    79,
    209,
    235,
    131,
    38,
    52,
    219,
    102,
    123,
    156,
    126,
    157,
    122,
    129,
    50,
    234,
    182,
    51,
    222,
    58,
    169,
    89,
    52,
    102,
    59,
    170,
    186,
    129,
    96,
    72,
    185,
    213,
    129,
    156,
    248,
    108,
    132,
    119,
    255,
    84,
    120,
    38,
    95,
    190,
    232,
    30,
    54,
    159,
    52,
    128,
    92,
    69,
    44,
    155,
    118,
    213,
    27,
    143,
    204,
    195,
    184,
    245,
]
_M115_G_KEY_S = [0x29, 0x23, 0x21, 0x5E]
_M115_G_KEY_L = [120, 6, 173, 76, 51, 134, 93, 24, 76, 1, 63, 70]
_DEFAULT_115_USER_AGENT = "Mozilla/5.0 115-media-hub"


def _normalize_115_user_agent(value: Any) -> str:
    ua = str(value or "").strip()
    return ua or _DEFAULT_115_USER_AGENT


def _collect_set_cookie_pairs(response_set_cookies: List[str]) -> str:
    extra_cookie_pairs: List[str] = []
    for raw_cookie in response_set_cookies:
        jar = SimpleCookie()
        try:
            jar.load(str(raw_cookie or ""))
        except Exception:
            continue
        for key, morsel in jar.items():
            token = f"{str(key or '').strip()}={str(morsel.value or '').strip()}"
            if token and token not in extra_cookie_pairs:
                extra_cookie_pairs.append(token)
    return "; ".join(extra_cookie_pairs)


def _extract_115_download_error_detail(payload: Any, fallback: str = "115 下载地址解析失败") -> str:
    result = payload if isinstance(payload, dict) else {}
    return (
        str(result.get("error", "")).strip()
        or str(result.get("msg", "")).strip()
        or str(result.get("message", "")).strip()
        or fallback
    )


def _is_115_large_file_limit_error(payload: Any) -> bool:
    result = payload if isinstance(payload, dict) else {}
    code = str(result.get("msg_code", "") or result.get("errno", "") or "").strip()
    message = _extract_115_download_error_detail(result, fallback="").strip()
    return code == "50028" or ("文件大小超出限制" in message and "电脑端下载" in message)


def _rsa_115_encrypt_block(block: bytes) -> str:
    block_size = 128
    if len(block) + 11 > block_size:
        raise RuntimeError("115 downurl 加密块过长")
    padded = b"\x00\x02" + (b"\xff" * (block_size - len(block) - 3)) + b"\x00" + block
    number = int.from_bytes(padded, byteorder="big", signed=False)
    encrypted = pow(number, _RSA_115_EXPONENT, _RSA_115_MODULUS)
    return f"{encrypted:0256x}"


def _rsa_115_public_decrypt_block(raw_block: bytes) -> bytes:
    number = int.from_bytes(bytes(raw_block), byteorder="big", signed=False)
    decoded = pow(number, _RSA_115_EXPONENT, _RSA_115_MODULUS)
    hex_text = f"{decoded:x}"
    if len(hex_text) % 2:
        hex_text = "0" + hex_text
    payload = bytes.fromhex(hex_text)
    idx = 1
    while idx < len(payload) and payload[idx] != 0:
        idx += 1
    if idx + 1 >= len(payload):
        return b""
    return payload[idx + 1 :]


def _m115_getkey(length: int, key: Optional[List[int]] = None) -> List[int]:
    if key is not None:
        return [
            ((int(key[i]) + _M115_G_KTS[length * i]) & 0xFF) ^ _M115_G_KTS[length * (length - 1 - i)]
            for i in range(length)
        ]
    return _M115_G_KEY_L[:] if length == 12 else _M115_G_KEY_S[:]


def _m115_xor(src: List[int], key: List[int]) -> List[int]:
    src_len = len(src)
    key_len = len(key)
    mod4 = src_len % 4
    result: List[int] = []
    if mod4:
        for i in range(mod4):
            result.append(int(src[i]) ^ int(key[i % key_len]))
    for i in range(mod4, src_len):
        result.append(int(src[i]) ^ int(key[(i - mod4) % key_len]))
    return result


def _m115_sym_encode(src: List[int], key1: List[int], key2: Optional[List[int]]) -> List[int]:
    k1 = _m115_getkey(4, key1)
    k2 = _m115_getkey(12, key2)
    result = _m115_xor(src, k1)
    result.reverse()
    return _m115_xor(result, k2)


def _m115_sym_decode(src: List[int], key1: List[int], key2: List[int]) -> List[int]:
    k1 = _m115_getkey(4, key1)
    k2 = _m115_getkey(12, key2)
    result = _m115_xor(src, k2)
    result.reverse()
    return _m115_xor(result, k1)


def _m115_asym_encode(src: List[int]) -> str:
    chunk_size = 128 - 11
    encrypted_hex_chunks: List[str] = []
    for offset in range(0, len(src), chunk_size):
        encrypted_hex_chunks.append(_rsa_115_encrypt_block(bytes(src[offset : offset + chunk_size])))
    all_hex = "".join(encrypted_hex_chunks)
    return base64.b64encode(bytes.fromhex(all_hex)).decode("ascii")


def _m115_asym_decode(src: List[int]) -> List[int]:
    block_size = 128
    raw = bytes(src)
    result: List[int] = []
    for offset in range(0, len(raw), block_size):
        result.extend(_rsa_115_public_decrypt_block(raw[offset : offset + block_size]))
    return result


def _m115_encode_downurl_payload(payload_text: str, timestamp: int) -> Tuple[str, List[int]]:
    key = list(hashlib.md5(f"!@###@#{timestamp}DFDR@#@#".encode("utf-8")).digest())
    src = list(payload_text.encode("latin1"))
    encrypted = _m115_sym_encode(src, key1=key, key2=None)
    mixed = key[:16] + encrypted
    return _m115_asym_encode(mixed), key


def _m115_decode_downurl_payload(encoded_text: str, key: List[int]) -> str:
    raw = list(base64.b64decode(str(encoded_text or "").strip()))
    decoded = _m115_asym_decode(raw)
    if len(decoded) < 16:
        raise RuntimeError("115 downurl 返回数据异常")
    payload_bytes = bytes(_m115_sym_decode(decoded[16:], key1=key, key2=decoded[:16]))
    try:
        return payload_bytes.decode("utf-8")
    except Exception:
        return payload_bytes.decode("latin1", errors="ignore")


def _resolve_115_download_payload_by_chrome_api(cookie: str, pick_code: str, user_agent: str) -> Tuple[str, str]:
    throttle_115_api_requests()
    timestamp = int(time.time())
    payload_text = json.dumps({"pickcode": pick_code}, ensure_ascii=False, separators=(",", ":"))
    encoded_data, decode_key = _m115_encode_downurl_payload(payload_text, timestamp)
    headers = {
        "Cookie": cookie,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://115.com/",
        "Origin": "https://115.com",
        "User-Agent": _normalize_115_user_agent(user_agent),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    body = urllib.parse.urlencode({"data": encoded_data}).encode("utf-8")
    request = urllib.request.Request(
        "https://proapi.115.com/app/chrome/downurl?t=" + str(timestamp),
        headers=headers,
        method="POST",
        data=body,
    )
    with urllib.request.urlopen(request, timeout=45) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        body_text = resp.read().decode(charset, errors="ignore")
        result = safe_json_loads(body_text, {})
        response_set_cookies = resp.headers.get_all("Set-Cookie") or []
    if not isinstance(result, dict):
        raise RuntimeError("115 downurl 返回异常")
    if not bool(result.get("state", False)):
        raise RuntimeError(_extract_115_download_error_detail(result, fallback="115 downurl 解析失败"))
    encrypted_payload = str(result.get("data", "")).strip()
    if not encrypted_payload:
        raise RuntimeError("115 downurl 返回为空")
    decoded_payload_text = _m115_decode_downurl_payload(encrypted_payload, decode_key)
    decoded_payload = safe_json_loads(decoded_payload_text, {})
    download_urls = _collect_115_download_urls(decoded_payload)
    download_url = str(download_urls[0] if download_urls else "").strip()
    if not download_url:
        raise RuntimeError("115 downurl 未解析到下载链接")
    download_cookie = _collect_set_cookie_pairs(response_set_cookies)
    return download_url, download_cookie


def _normalize_pick_code(value: Any) -> str:
    code = str(value or "").strip()
    if not code:
        return ""
    if not _PICK_CODE_REGEX.fullmatch(code):
        return ""
    return code


def _build_pick_code_path_cache_key(cfg: Dict[str, Any], raw_path: str) -> str:
    _, relative_path = resolve_provider_relative_path(cfg, raw_path, expected_provider="115")
    normalized_relative_path = normalize_relative_path(relative_path)
    if not normalized_relative_path:
        return ""
    return f"115:{normalized_relative_path}"


def _get_cached_pick_code(cache_key: str) -> str:
    normalized_key = str(cache_key or "").strip()
    if not normalized_key:
        return ""
    now_ts = time.time()
    with _pick_code_path_cache_lock:
        payload = _pick_code_path_cache.get(normalized_key)
        if not payload:
            return ""
        expires_at = float((payload or {}).get("expires_at", 0.0) or 0.0)
        if now_ts >= expires_at:
            _pick_code_path_cache.pop(normalized_key, None)
            return ""
        ttl_seconds = max(
            60,
            min(24 * 60 * 60, int((payload or {}).get("ttl_seconds", _PICK_CODE_PATH_CACHE_TTL_SECONDS) or _PICK_CODE_PATH_CACHE_TTL_SECONDS)),
        )
        payload["expires_at"] = now_ts + ttl_seconds
        payload["updated_at"] = now_ts
        return _normalize_pick_code((payload or {}).get("pick_code", ""))


def _set_cached_pick_code(cache_key: str, pick_code: str, ttl_seconds: int = _PICK_CODE_PATH_CACHE_TTL_SECONDS) -> None:
    normalized_key = str(cache_key or "").strip()
    normalized_pick_code = _normalize_pick_code(pick_code)
    if (not normalized_key) or (not normalized_pick_code):
        return
    normalized_ttl = max(60, min(24 * 60 * 60, int(ttl_seconds or _PICK_CODE_PATH_CACHE_TTL_SECONDS)))
    now_ts = time.time()
    with _pick_code_path_cache_lock:
        _pick_code_path_cache[normalized_key] = {
            "pick_code": normalized_pick_code,
            "ttl_seconds": normalized_ttl,
            "expires_at": now_ts + normalized_ttl,
            "updated_at": now_ts,
        }
        expired_keys = [
            key
            for key, payload in _pick_code_path_cache.items()
            if now_ts >= float((payload or {}).get("expires_at", 0.0) or 0.0)
        ]
        for key in expired_keys:
            _pick_code_path_cache.pop(key, None)
        if len(_pick_code_path_cache) > 10000:
            ordered = sorted(
                _pick_code_path_cache.items(),
                key=lambda item: float((item[1] or {}).get("updated_at", 0.0) or 0.0),
            )
            for key, _ in ordered[: len(_pick_code_path_cache) - 10000]:
                _pick_code_path_cache.pop(key, None)


def _build_folder_cid_cache_key(relative_path: str) -> str:
    normalized_relative_path = normalize_relative_path(relative_path)
    if not normalized_relative_path:
        return ""
    return f"115-folder:{normalized_relative_path}"


def _get_cached_folder_cid(cache_key: str) -> str:
    normalized_key = str(cache_key or "").strip()
    if not normalized_key:
        return ""
    now_ts = time.time()
    with _folder_cid_path_cache_lock:
        payload = _folder_cid_path_cache.get(normalized_key)
        if not payload:
            return ""
        expires_at = float((payload or {}).get("expires_at", 0.0) or 0.0)
        if now_ts >= expires_at:
            _folder_cid_path_cache.pop(normalized_key, None)
            return ""
        ttl_seconds = max(
            60,
            min(
                24 * 60 * 60,
                int(
                    (payload or {}).get("ttl_seconds", _FOLDER_CID_PATH_CACHE_TTL_SECONDS)
                    or _FOLDER_CID_PATH_CACHE_TTL_SECONDS
                ),
            ),
        )
        payload["expires_at"] = now_ts + ttl_seconds
        payload["updated_at"] = now_ts
        return normalize_115_cid((payload or {}).get("cid", ""))


def _set_cached_folder_cid(
    cache_key: str,
    cid: str,
    ttl_seconds: int = _FOLDER_CID_PATH_CACHE_TTL_SECONDS,
) -> None:
    normalized_key = str(cache_key or "").strip()
    normalized_cid = normalize_115_cid(cid)
    if (not normalized_key) or (not normalized_cid):
        return
    normalized_ttl = max(60, min(24 * 60 * 60, int(ttl_seconds or _FOLDER_CID_PATH_CACHE_TTL_SECONDS)))
    now_ts = time.time()
    with _folder_cid_path_cache_lock:
        _folder_cid_path_cache[normalized_key] = {
            "cid": normalized_cid,
            "ttl_seconds": normalized_ttl,
            "expires_at": now_ts + normalized_ttl,
            "updated_at": now_ts,
        }
        expired_keys = [
            key
            for key, payload in _folder_cid_path_cache.items()
            if now_ts >= float((payload or {}).get("expires_at", 0.0) or 0.0)
        ]
        for key in expired_keys:
            _folder_cid_path_cache.pop(key, None)
        if len(_folder_cid_path_cache) > 10000:
            ordered = sorted(
                _folder_cid_path_cache.items(),
                key=lambda item: float((item[1] or {}).get("updated_at", 0.0) or 0.0),
            )
            for key, _ in ordered[: len(_folder_cid_path_cache) - 10000]:
                _folder_cid_path_cache.pop(key, None)


def _delete_cached_folder_cid(cache_key: str) -> None:
    normalized_key = str(cache_key or "").strip()
    if not normalized_key:
        return
    with _folder_cid_path_cache_lock:
        _folder_cid_path_cache.pop(normalized_key, None)


def _resolve_pick_code_by_path(cfg: Dict[str, Any], cookie: str, raw_path: str) -> str:
    cache_key = _build_pick_code_path_cache_key(cfg, raw_path)
    cached_pick_code = _get_cached_pick_code(cache_key)
    if cached_pick_code:
        return cached_pick_code

    _, relative_path = resolve_provider_relative_path(cfg, raw_path, expected_provider="115")
    if not relative_path:
        return ""
    parent_rel = normalize_relative_path(os.path.dirname(relative_path))
    file_name = str(os.path.basename(relative_path) or "").strip()
    if not file_name:
        return ""

    parent_cache_key = _build_folder_cid_cache_key(parent_rel)
    cached_parent_cid = _get_cached_folder_cid(parent_cache_key) if parent_cache_key else ""
    try:
        parent_cid = cached_parent_cid or (_resolve_115_folder_id_by_path_paginated(cookie, parent_rel) if parent_rel else "0")
    except Exception:
        return ""
    if parent_cache_key and parent_cid:
        _set_cached_folder_cid(parent_cache_key, parent_cid)
    matched = _find_115_file_entry_by_name(cookie, parent_cid, file_name)
    if (not matched) and parent_cache_key and cached_parent_cid:
        _delete_cached_folder_cid(parent_cache_key)
        try:
            parent_cid = _resolve_115_folder_id_by_path_paginated(cookie, parent_rel) if parent_rel else "0"
        except Exception:
            parent_cid = ""
        if parent_cache_key and parent_cid:
            _set_cached_folder_cid(parent_cache_key, parent_cid)
        if parent_cid:
            matched = _find_115_file_entry_by_name(cookie, parent_cid, file_name)
    resolved_pick_code = _normalize_pick_code((matched or {}).get("pick_code", ""))
    if resolved_pick_code:
        _set_cached_pick_code(cache_key, resolved_pick_code)
    return resolved_pick_code


def _normalize_115_entry_from_list_item(item: Dict[str, Any]) -> Dict[str, Any]:
    source = item if isinstance(item, dict) else {}
    name = str(source.get("n") or source.get("name") or "").strip()
    folder_id = str(source.get("cid") or "").strip()
    file_id = str(source.get("fid") or source.get("id") or "").strip()
    sha1 = str(source.get("sha1") or source.get("sha") or "").strip()
    is_dir = bool(source.get("is_dir")) if "is_dir" in source else (not file_id and not sha1)
    entry_id = folder_id if is_dir else (file_id or str(source.get("pick_code") or source.get("pc") or sha1).strip())
    return {
        "id": entry_id,
        "cid": folder_id if is_dir else "",
        "name": name,
        "is_dir": is_dir,
        "size": parse_int(source.get("s") or source.get("size") or 0),
        "pick_code": str(source.get("pick_code") or source.get("pc") or "").strip(),
        "sha1": sha1,
        "modified_at": str(source.get("te") or source.get("t") or source.get("tp") or source.get("tu") or "").strip(),
    }


def _find_115_file_entry_by_name(cookie: str, parent_cid: str, file_name: str) -> Dict[str, Any]:
    target_name = str(file_name or "").strip()
    if not target_name:
        return {}
    normalized_cid = str(parent_cid or "0").strip() or "0"
    page_size = 300
    max_pages = 80
    offset = 0
    headers = {
        "Cookie": str(cookie or "").strip(),
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://115.com/",
        "User-Agent": _DEFAULT_115_USER_AGENT,
    }

    # 优先尝试已存在的缓存接口（首屏 300 条）；未命中再继续翻页查找。
    try:
        first_page = list_115_entries(cookie, normalized_cid)
    except Exception:
        first_page = []
    for entry in first_page:
        if (not bool(entry.get("is_dir"))) and str(entry.get("name", "")).strip() == target_name:
            return dict(entry)
    offset = max(len(first_page), page_size)

    pages_scanned = 0
    while pages_scanned < max_pages:
        pages_scanned += 1
        throttle_115_api_requests()
        url = (
            "https://aps.115.com/natsort/files.php"
            f"?aid=1&cid={urllib.parse.quote(normalized_cid)}"
            f"&offset={max(0, int(offset))}&limit={page_size}&show_dir=1&natsort=1&format=json"
        )
        result = http_request_json(url, extra_headers=headers, timeout=45)
        if not bool(result.get("state", False)):
            break
        raw_items = result.get("data") or []
        if not raw_items:
            break
        for raw_item in raw_items:
            entry = _normalize_115_entry_from_list_item(raw_item if isinstance(raw_item, dict) else {})
            if (not bool(entry.get("is_dir"))) and str(entry.get("name", "")).strip() == target_name:
                return entry
        if len(raw_items) < page_size:
            break
        offset += len(raw_items)
    return {}


def _find_115_folder_entry_by_name(cookie: str, parent_cid: str, folder_name: str) -> Dict[str, Any]:
    target_name = str(folder_name or "").strip()
    if not target_name:
        return {}
    normalized_cid = str(parent_cid or "0").strip() or "0"
    page_size = 300
    max_pages = 80
    offset = 0
    headers = {
        "Cookie": str(cookie or "").strip(),
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://115.com/",
        "User-Agent": _DEFAULT_115_USER_AGENT,
    }

    try:
        first_page = list_115_entries(cookie, normalized_cid)
    except Exception:
        first_page = []
    for entry in first_page:
        if bool(entry.get("is_dir")) and str(entry.get("name", "")).strip() == target_name:
            return dict(entry)
    offset = max(len(first_page), page_size)

    pages_scanned = 0
    while pages_scanned < max_pages:
        pages_scanned += 1
        throttle_115_api_requests()
        url = (
            "https://aps.115.com/natsort/files.php"
            f"?aid=1&cid={urllib.parse.quote(normalized_cid)}"
            f"&offset={max(0, int(offset))}&limit={page_size}&show_dir=1&natsort=1&format=json"
        )
        result = http_request_json(url, extra_headers=headers, timeout=45)
        if not bool(result.get("state", False)):
            break
        raw_items = result.get("data") or []
        if not raw_items:
            break
        for raw_item in raw_items:
            entry = _normalize_115_entry_from_list_item(raw_item if isinstance(raw_item, dict) else {})
            if bool(entry.get("is_dir")) and str(entry.get("name", "")).strip() == target_name:
                return entry
        if len(raw_items) < page_size:
            break
        offset += len(raw_items)
    return {}


def _resolve_115_folder_id_by_path_paginated(cookie: str, relative_path: str) -> str:
    normalized_path = normalize_relative_path(relative_path)
    if not normalized_path:
        return "0"
    current_cid = "0"
    walked_parts: List[str] = []
    for part in [segment for segment in str(normalized_path).split("/") if segment]:
        walked_parts.append(part)
        walked_rel = normalize_relative_path("/".join(walked_parts))
        walked_cache_key = _build_folder_cid_cache_key(walked_rel)
        cached_cid = _get_cached_folder_cid(walked_cache_key) if walked_cache_key else ""
        if cached_cid:
            current_cid = cached_cid
            continue
        matched = _find_115_folder_entry_by_name(cookie, current_cid, part)
        next_cid = str((matched or {}).get("id") or (matched or {}).get("cid") or "").strip()
        if not next_cid:
            raise RuntimeError(f"115 网盘目录不存在：{normalized_path}")
        current_cid = next_cid
        if walked_cache_key and current_cid:
            _set_cached_folder_cid(walked_cache_key, current_cid)
    return current_cid


def _collect_115_download_urls(payload: Any) -> List[str]:
    urls: List[str] = []
    seen: Set[str] = set()

    def push(url_value: Any) -> None:
        token = str(url_value or "").strip()
        if (not token) or (not token.lower().startswith(("http://", "https://"))) or token in seen:
            return
        seen.add(token)
        urls.append(token)

    def walk(node: Any) -> None:
        if isinstance(node, str):
            push(node)
            return
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        for key in ("url", "download_url", "file_url", "download_url_web", "download_url_web2"):
            walk(node.get(key))
        for key in ("data", "urls", "result", "info"):
            walk(node.get(key))
        # 兼容 downurl 返回的 { "<file_id>": { url: { url: "..." } } } 结构。
        for value in node.values():
            walk(value)

    walk(payload)
    return urls


def _resolve_115_download_payload(cookie: str, pick_code: str, user_agent: str = "") -> Tuple[str, str]:
    normalized_user_agent = _normalize_115_user_agent(user_agent)
    cache_key = f"{pick_code}::ua::{normalized_user_agent}"
    runtime_tuning = get_api_115_runtime_tuning()
    cache_ttl_seconds = max(
        0,
        int(runtime_tuning.get("download_url_cache_ttl_seconds", API_115_DOWNLOAD_URL_CACHE_TTL_SECONDS) or 0),
    )
    if cache_ttl_seconds > 0:
        now_ts = time.time()
        with _download_url_cache_lock:
            cached = _download_url_cache.get(cache_key)
            if cached and now_ts < float(cached.get("expires_at", 0.0) or 0.0):
                cached_url = str(cached.get("url", "")).strip()
                cached_cookie = str(cached.get("download_cookie", "")).strip()
                if cached_url:
                    return cached_url, cached_cookie

    try:
        throttle_115_api_requests()
        headers = {
            "Cookie": cookie,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://115.com/",
            "Origin": "https://115.com",
            "User-Agent": normalized_user_agent,
        }
        url = "https://webapi.115.com/files/download?pickcode=" + urllib.parse.quote(pick_code)
        request = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(request, timeout=45) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            body = resp.read().decode(charset, errors="ignore")
            result = safe_json_loads(body, {})
            response_set_cookies = resp.headers.get_all("Set-Cookie") or []
        if not isinstance(result, dict):
            raise RuntimeError("115 下载地址解析返回异常")
        if not bool(result.get("state", False)):
            detail = _extract_115_download_error_detail(result)
            if _is_115_large_file_limit_error(result):
                try:
                    download_url, download_cookie = _resolve_115_download_payload_by_chrome_api(
                        cookie,
                        pick_code,
                        normalized_user_agent,
                    )
                except Exception as exc:
                    raise RuntimeError(f"{detail}；downurl 回退失败: {exc}") from exc
                if download_url:
                    if cache_ttl_seconds > 0:
                        now_ts = time.time()
                        with _download_url_cache_lock:
                            _download_url_cache[cache_key] = {
                                "url": download_url,
                                "download_cookie": download_cookie,
                                "expires_at": now_ts + cache_ttl_seconds,
                                "updated_at": now_ts,
                            }
                            if len(_download_url_cache) > 1000:
                                ordered = sorted(
                                    _download_url_cache.items(),
                                    key=lambda item: float((item[1] or {}).get("updated_at", 0.0) or 0.0),
                                )
                                for key, _ in ordered[: len(_download_url_cache) - 1000]:
                                    _download_url_cache.pop(key, None)
                    mark_cookie_health_success("115", trigger="runtime:strm_resolve_download")
                    return download_url, download_cookie
            raise RuntimeError(detail)

        download_urls = _collect_115_download_urls(result)
        download_url = str(download_urls[0] if download_urls else "").strip()
        if not download_url:
            try:
                download_url, download_cookie = _resolve_115_download_payload_by_chrome_api(
                    cookie,
                    pick_code,
                    normalized_user_agent,
                )
            except Exception as exc:
                raise RuntimeError(f"115 返回成功，但未解析到下载链接；downurl 回退失败: {exc}") from exc
            if download_url:
                if cache_ttl_seconds > 0:
                    now_ts = time.time()
                    with _download_url_cache_lock:
                        _download_url_cache[cache_key] = {
                            "url": download_url,
                            "download_cookie": download_cookie,
                            "expires_at": now_ts + cache_ttl_seconds,
                            "updated_at": now_ts,
                        }
                        if len(_download_url_cache) > 1000:
                            ordered = sorted(
                                _download_url_cache.items(),
                                key=lambda item: float((item[1] or {}).get("updated_at", 0.0) or 0.0),
                            )
                            for key, _ in ordered[: len(_download_url_cache) - 1000]:
                                _download_url_cache.pop(key, None)
                mark_cookie_health_success("115", trigger="runtime:strm_resolve_download")
                return download_url, download_cookie
            raise RuntimeError("115 返回成功，但未解析到下载链接")

        download_cookie = _collect_set_cookie_pairs(response_set_cookies)

        if cache_ttl_seconds > 0:
            now_ts = time.time()
            with _download_url_cache_lock:
                _download_url_cache[cache_key] = {
                    "url": download_url,
                    "download_cookie": download_cookie,
                    "expires_at": now_ts + cache_ttl_seconds,
                    "updated_at": now_ts,
                }
                if len(_download_url_cache) > 1000:
                    ordered = sorted(
                        _download_url_cache.items(),
                        key=lambda item: float((item[1] or {}).get("updated_at", 0.0) or 0.0),
                    )
                    for key, _ in ordered[: len(_download_url_cache) - 1000]:
                        _download_url_cache.pop(key, None)
        mark_cookie_health_success("115", trigger="runtime:strm_resolve_download")
        return download_url, download_cookie
    except Exception as exc:
        mark_cookie_health_failure("115", exc, trigger="runtime:strm_resolve_download")
        raise


def _register_relay_token(
    download_url: str,
    cookie_header: str,
    user_agent: str = "",
    pick_code: str = "",
    ttl_seconds: int = 2 * 60 * 60,
) -> str:
    normalized_ttl = max(60, min(24 * 60 * 60, int(ttl_seconds or (2 * 60 * 60))))
    token = hashlib.md5(f"{time.time()}-{os.urandom(8).hex()}".encode("utf-8")).hexdigest()
    now_ts = time.time()
    with _relay_token_cache_lock:
        _relay_token_cache[token] = {
            "url": str(download_url or "").strip(),
            "cookie": str(cookie_header or "").strip(),
            "user_agent": _normalize_115_user_agent(user_agent),
            "pick_code": _normalize_pick_code(pick_code),
            "ttl_seconds": normalized_ttl,
            "expires_at": now_ts + normalized_ttl,
            "updated_at": now_ts,
        }
        expired_keys = [
            key
            for key, payload in _relay_token_cache.items()
            if now_ts >= float((payload or {}).get("expires_at", 0.0) or 0.0)
        ]
        for key in expired_keys:
            _relay_token_cache.pop(key, None)
        if len(_relay_token_cache) > 2000:
            ordered = sorted(
                _relay_token_cache.items(),
                key=lambda item: float((item[1] or {}).get("updated_at", 0.0) or 0.0),
            )
            for key, _ in ordered[: len(_relay_token_cache) - 2000]:
                _relay_token_cache.pop(key, None)
    return token


def _resolve_relay_payload(token: str) -> Dict[str, str]:
    now_ts = time.time()
    normalized_token = str(token or "").strip()
    if not normalized_token:
        return {}
    with _relay_token_cache_lock:
        payload = _relay_token_cache.get(normalized_token)
        if not payload:
            return {}
        if now_ts >= float((payload or {}).get("expires_at", 0.0) or 0.0):
            _relay_token_cache.pop(normalized_token, None)
            return {}
        # 滑动续期：播放中持续拖动/跳转时刷新有效期，避免中途 seek 因令牌过期失败。
        payload_ttl = max(60, min(24 * 60 * 60, int((payload or {}).get("ttl_seconds", 2 * 60 * 60) or (2 * 60 * 60))))
        payload["expires_at"] = now_ts + payload_ttl
        payload["updated_at"] = now_ts
        return {
            "url": str((payload or {}).get("url", "")).strip(),
            "cookie": str((payload or {}).get("cookie", "")).strip(),
            "user_agent": _normalize_115_user_agent((payload or {}).get("user_agent", "")),
            "pick_code": _normalize_pick_code((payload or {}).get("pick_code", "")),
        }


def _build_proxy_upstream_headers(cookie_header: str, user_agent: str, range_header: str = "") -> Dict[str, str]:
    headers = {
        "Accept": "*/*",
        "Referer": "https://115.com/",
        "Origin": "https://115.com",
        "User-Agent": _normalize_115_user_agent(user_agent),
    }
    merged_cookie = str(cookie_header or "").strip()
    if merged_cookie:
        headers["Cookie"] = merged_cookie
    normalized_range = str(range_header or "").strip()
    if normalized_range:
        headers["Range"] = normalized_range
    return headers


def _extract_proxy_response_headers(headers_obj: Any) -> Dict[str, str]:
    response_headers: Dict[str, str] = {}
    for key in (
        "Content-Type",
        "Content-Length",
        "Content-Range",
        "Accept-Ranges",
        "Last-Modified",
        "ETag",
        "Cache-Control",
        "Content-Disposition",
    ):
        try:
            value = str(headers_obj.get(key, "") or "").strip() if headers_obj is not None else ""
        except Exception:
            value = ""
        if value:
            response_headers[key] = value
    return response_headers


def _open_proxy_upstream(
    target_url: str,
    headers: Dict[str, str],
    method: str,
    timeout: int = 120,
) -> Dict[str, Any]:
    request = urllib.request.Request(str(target_url or "").strip(), headers=dict(headers or {}), method=method)
    try:
        response = urllib.request.urlopen(request, timeout=max(10, int(timeout or 120)))
        return {"ok": True, "response": response}
    except urllib.error.HTTPError as exc:
        try:
            error_body = exc.read()
        except Exception:
            error_body = b""
        return {
            "ok": False,
            "http_error": True,
            "status_code": int(getattr(exc, "code", 502) or 502),
            "headers": _extract_proxy_response_headers(getattr(exc, "headers", None)),
            "body": error_body,
        }
    except Exception as exc:
        return {
            "ok": False,
            "http_error": False,
            "error": str(exc),
        }


def _update_relay_token_payload(
    token: str,
    download_url: str,
    cookie_header: str,
    user_agent: str,
    pick_code: str = "",
) -> bool:
    normalized_token = str(token or "").strip()
    normalized_download_url = str(download_url or "").strip()
    normalized_cookie = str(cookie_header or "").strip()
    normalized_user_agent = _normalize_115_user_agent(user_agent)
    normalized_pick_code = _normalize_pick_code(pick_code)
    if (not normalized_token) or (not normalized_download_url):
        return False
    now_ts = time.time()
    with _relay_token_cache_lock:
        payload = _relay_token_cache.get(normalized_token)
        if not payload:
            return False
        payload_ttl = max(60, min(24 * 60 * 60, int((payload or {}).get("ttl_seconds", 2 * 60 * 60) or (2 * 60 * 60))))
        payload["url"] = normalized_download_url
        payload["cookie"] = normalized_cookie
        payload["pick_code"] = normalized_pick_code
        payload["user_agent"] = normalized_user_agent
        payload["expires_at"] = now_ts + payload_ttl
        payload["updated_at"] = now_ts
    return True


def _refresh_115_download_target_by_pick_code(
    cookie_115: str,
    pick_code: str,
    user_agent: str,
) -> Tuple[str, str]:
    normalized_cookie_115 = str(cookie_115 or "").strip()
    normalized_pick_code = _normalize_pick_code(pick_code)
    normalized_user_agent = _normalize_115_user_agent(user_agent)
    if (not normalized_cookie_115) or (not normalized_pick_code):
        return "", ""
    refreshed_url, refreshed_download_cookie = _resolve_115_download_payload(
        normalized_cookie_115,
        normalized_pick_code,
        normalized_user_agent,
    )
    if not str(refreshed_url or "").strip():
        return "", ""
    refreshed_cookie = "; ".join(
        [part for part in [normalized_cookie_115, str(refreshed_download_cookie or "").strip()] if part]
    )
    return str(refreshed_url or "").strip(), refreshed_cookie


async def _stream_115_response(
    request: Request,
    upstream_url: str,
    upstream_cookie: str,
    upstream_user_agent: str,
    upstream_pick_code: str = "",
    refresh_cookie_115: str = "",
    relay_token: str = "",
) -> Response:
    current_url = str(upstream_url or "").strip()
    current_cookie = str(upstream_cookie or "").strip()
    current_user_agent = _normalize_115_user_agent(upstream_user_agent)
    current_pick_code = _normalize_pick_code(upstream_pick_code)
    normalized_refresh_cookie_115 = str(refresh_cookie_115 or "").strip()
    normalized_relay_token = str(relay_token or "").strip()
    if not current_url:
        return JSONResponse(status_code=410, content={"ok": False, "msg": "播放中继令牌已失效，请重试"})

    range_header = str(request.headers.get("range", "") or "").strip()
    method = "HEAD" if request.method == "HEAD" else "GET"
    upstream_response = None
    refresh_attempted = False
    while True:
        request_headers = _build_proxy_upstream_headers(current_cookie, current_user_agent, range_header)
        open_result = await asyncio.to_thread(
            _open_proxy_upstream,
            current_url,
            request_headers,
            method,
            120,
        )
        if bool(open_result.get("ok", False)):
            upstream_response = open_result.get("response")
            break
        if bool(open_result.get("http_error", False)):
            status_code = int(open_result.get("status_code", 502) or 502)
            should_retry_with_refresh = (
                (not refresh_attempted)
                and bool(current_pick_code)
                and bool(normalized_refresh_cookie_115)
                and status_code in (401, 403, 410)
            )
            if should_retry_with_refresh:
                try:
                    refreshed_url, refreshed_cookie = await asyncio.to_thread(
                        _refresh_115_download_target_by_pick_code,
                        normalized_refresh_cookie_115,
                        current_pick_code,
                        current_user_agent,
                    )
                except Exception:
                    refreshed_url, refreshed_cookie = "", ""
                if refreshed_url:
                    refresh_attempted = True
                    current_url = refreshed_url
                    current_cookie = refreshed_cookie
                    if normalized_relay_token:
                        _update_relay_token_payload(
                            normalized_relay_token,
                            current_url,
                            current_cookie,
                            current_user_agent,
                            pick_code=current_pick_code,
                        )
                    continue
            error_body = open_result.get("body", b"")
            response_headers = open_result.get("headers", {})
            if request.method == "HEAD":
                return Response(status_code=status_code, headers=response_headers)
            if error_body:
                return Response(content=error_body, status_code=status_code, headers=response_headers)
            return Response(content=f"115 中继下载失败: HTTP {status_code}", status_code=status_code, headers=response_headers)
        return JSONResponse(
            status_code=502,
            content={"ok": False, "msg": f"115 中继下载失败: {str(open_result.get('error', '') or 'unknown error')}"},
        )

    response_headers = _extract_proxy_response_headers(getattr(upstream_response, "headers", None))
    status_code = int(getattr(upstream_response, "status", 200) or 200)

    if request.method == "HEAD":
        try:
            upstream_response.close()
        except Exception:
            pass
        return Response(status_code=status_code, headers=response_headers)

    def _stream_upstream_body() -> Iterator[bytes]:
        try:
            while True:
                chunk = upstream_response.read(_RELAY_STREAM_CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk
        finally:
            try:
                upstream_response.close()
            except Exception:
                pass

    return StreamingResponse(_stream_upstream_body(), status_code=status_code, headers=response_headers)

@router.api_route("/strm/proxy", methods=["GET", "HEAD"], include_in_schema=False)
async def proxy_strm_play(request: Request) -> Response:
    cfg = get_config()
    cookie = str(cfg.get("cookie_115", "")).strip()
    if not cookie:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "请先在参数配置中填写 115 Cookie"})

    raw_path = str(request.query_params.get("path", "") or "").strip()
    pick_code = _normalize_pick_code(
        request.query_params.get("pickcode", "") or request.query_params.get("pick_code", "")
    )
    if (not pick_code) and raw_path:
        try:
            pick_code = await asyncio.to_thread(_resolve_pick_code_by_path, cfg, cookie, raw_path)
        except Exception as exc:
            return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})
    if not pick_code:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "缺少可用的 pickcode 或 path 参数"})

    client_user_agent = _normalize_115_user_agent(request.headers.get("user-agent", ""))
    try:
        download_url, download_cookie = await asyncio.to_thread(
            _resolve_115_download_payload,
            cookie,
            pick_code,
            client_user_agent,
        )
    except Exception as exc:
        return JSONResponse(status_code=502, content={"ok": False, "msg": f"115 下载地址解析失败: {exc}"})

    relay_cookie = "; ".join(
        [part for part in [str(cookie or "").strip(), str(download_cookie or "").strip()] if part]
    )

    mode_param = str(request.query_params.get("mode", "") or "").strip().lower()
    default_mode = str(cfg.get("strm_proxy_mode", os.environ.get("STRM_PROXY_MODE", "redirect_direct")) or "").strip().lower()
    resolved_mode = mode_param or default_mode
    use_relay_redirect = resolved_mode in {"relay", "relay_redirect", "relay307", "307"}
    use_direct_proxy = resolved_mode in {"proxy", "direct_proxy", "stream"}

    if use_relay_redirect:
        relay_token = _register_relay_token(download_url, relay_cookie, client_user_agent, pick_code=pick_code)
        relay_base = str(request.url_for("relay_strm_play"))
        relay_url = relay_base + "?" + urllib.parse.urlencode({"token": relay_token})
        # 307 比 302 更稳定：避免播放器在重定向后错误改写请求方法。
        return RedirectResponse(url=relay_url, status_code=307)
    if use_direct_proxy:
        return await _stream_115_response(
            request=request,
            upstream_url=download_url,
            upstream_cookie=relay_cookie,
            upstream_user_agent=client_user_agent,
            upstream_pick_code=pick_code,
            refresh_cookie_115=cookie,
        )
    # 默认策略：302 直跳 115 上游下载地址，最大化播放速度并避免服务端中继流量。
    return RedirectResponse(url=download_url, status_code=302)


@router.api_route("/strm/relay", methods=["GET", "HEAD"], include_in_schema=False)
async def relay_strm_play(request: Request) -> Response:
    token = str(request.query_params.get("token", "") or "").strip()
    payload = _resolve_relay_payload(token)
    relay_url = str(payload.get("url", "")).strip()
    relay_cookie = str(payload.get("cookie", "")).strip()
    relay_user_agent = _normalize_115_user_agent(payload.get("user_agent", ""))
    relay_pick_code = _normalize_pick_code(payload.get("pick_code", ""))
    if not relay_url:
        return JSONResponse(status_code=410, content={"ok": False, "msg": "播放中继令牌已失效，请重试"})
    cfg = get_config()
    cookie_115 = str(cfg.get("cookie_115", "")).strip()
    return await _stream_115_response(
        request=request,
        upstream_url=relay_url,
        upstream_cookie=relay_cookie,
        upstream_user_agent=relay_user_agent,
        upstream_pick_code=relay_pick_code,
        refresh_cookie_115=cookie_115,
        relay_token=token,
    )
