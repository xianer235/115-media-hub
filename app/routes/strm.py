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


def _resolve_pick_code_by_path(cfg: Dict[str, Any], cookie: str, raw_path: str) -> str:
    _, relative_path = resolve_provider_relative_path(cfg, raw_path, expected_provider="115")
    if not relative_path:
        return ""
    parent_rel = normalize_relative_path(os.path.dirname(relative_path))
    file_name = str(os.path.basename(relative_path) or "").strip()
    if not file_name:
        return ""

    try:
        parent_cid = _resolve_115_folder_id_by_path_paginated(cookie, parent_rel) if parent_rel else "0"
    except Exception:
        return ""
    matched = _find_115_file_entry_by_name(cookie, parent_cid, file_name)
    return _normalize_pick_code((matched or {}).get("pick_code", ""))


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
    for part in [segment for segment in str(normalized_path).split("/") if segment]:
        matched = _find_115_folder_entry_by_name(cookie, current_cid, part)
        next_cid = str((matched or {}).get("id") or (matched or {}).get("cid") or "").strip()
        if not next_cid:
            raise RuntimeError(f"115 网盘目录不存在：{normalized_path}")
        current_cid = next_cid
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
    return download_url, download_cookie


def _register_relay_token(download_url: str, cookie_header: str, ttl_seconds: int = 120) -> str:
    normalized_ttl = max(30, min(600, int(ttl_seconds or 120)))
    token = hashlib.md5(f"{time.time()}-{os.urandom(8).hex()}".encode("utf-8")).hexdigest()
    now_ts = time.time()
    with _relay_token_cache_lock:
        _relay_token_cache[token] = {
            "url": str(download_url or "").strip(),
            "cookie": str(cookie_header or "").strip(),
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
        return {
            "url": str((payload or {}).get("url", "")).strip(),
            "cookie": str((payload or {}).get("cookie", "")).strip(),
        }


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
        download_url, _ = await asyncio.to_thread(_resolve_115_download_payload, cookie, pick_code, client_user_agent)
    except Exception as exc:
        return JSONResponse(status_code=502, content={"ok": False, "msg": f"115 下载地址解析失败: {exc}"})

    # 按用户要求仅执行 302 直连：成功即跳转，失败即返回错误，不做中继回退。
    return RedirectResponse(url=download_url, status_code=302)


@router.api_route("/strm/relay", methods=["GET", "HEAD"], include_in_schema=False)
async def relay_strm_play(request: Request) -> Response:
    token = str(request.query_params.get("token", "") or "").strip()
    payload = _resolve_relay_payload(token)
    relay_url = str(payload.get("url", "")).strip()
    relay_cookie = str(payload.get("cookie", "")).strip()
    if not relay_url:
        return JSONResponse(status_code=410, content={"ok": False, "msg": "播放中继令牌已失效，请重试"})

    upstream_headers = {
        "Accept": "*/*",
        "Referer": "https://115.com/",
        "Origin": "https://115.com",
        "User-Agent": "Mozilla/5.0 115-media-hub",
    }
    if relay_cookie:
        upstream_headers["Cookie"] = relay_cookie
    range_header = str(request.headers.get("range", "") or "").strip()
    if range_header:
        upstream_headers["Range"] = range_header

    method = "HEAD" if request.method == "HEAD" else "GET"
    upstream_request = urllib.request.Request(relay_url, headers=upstream_headers, method=method)
    try:
        upstream_response = urllib.request.urlopen(upstream_request, timeout=120)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="ignore").strip()
        except Exception:
            detail = ""
        message = detail or f"115 中继下载失败: HTTP {exc.code}"
        return JSONResponse(status_code=502, content={"ok": False, "msg": message})
    except Exception as exc:
        return JSONResponse(status_code=502, content={"ok": False, "msg": f"115 中继下载失败: {exc}"})

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
        value = str(upstream_response.headers.get(key, "") or "").strip()
        if value:
            response_headers[key] = value
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
                chunk = upstream_response.read(1024 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            try:
                upstream_response.close()
            except Exception:
                pass

    return StreamingResponse(_stream_upstream_body(), status_code=status_code, headers=response_headers)
