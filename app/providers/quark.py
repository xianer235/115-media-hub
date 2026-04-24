from .common import parse_int
from ..share_selection import normalize_share_selection_entry, normalize_share_selection_meta
from ..core import *  # noqa: F401,F403

def http_request_json_payload(
    url: str,
    payload: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
    extra_headers: Optional[Dict[str, str]] = None,
    method: str = "POST",
    proxy_url: str = "",
) -> Dict[str, Any]:
    url = normalize_http_url(url)
    headers = {"Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    body_payload = payload if isinstance(payload, dict) else {}
    body_bytes = json.dumps(body_payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body_bytes,
        headers=headers,
        method=str(method or "POST").strip().upper() or "POST",
    )
    opener = urllib.request.build_opener()
    if proxy_url:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        )
    with opener.open(request, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        raw = resp.read().decode(charset, errors="ignore")
    payload_json = safe_json_loads(raw, {})
    return payload_json if isinstance(payload_json, dict) else {}

def _build_quark_headers(cookie: str, referer: str = "https://pan.quark.cn/") -> Dict[str, str]:
    return {
        "Cookie": str(cookie or "").strip(),
        "Accept": "application/json, text/plain, */*",
        "Referer": str(referer or "https://pan.quark.cn/").strip() or "https://pan.quark.cn/",
        "Origin": "https://pan.quark.cn",
        "User-Agent": "Mozilla/5.0 115-media-hub",
    }

def _extract_quark_error(payload: Any, fallback: str = "夸克网盘请求失败") -> str:
    data = payload if isinstance(payload, dict) else {}
    parts = [
        str(data.get("message", "")).strip(),
        str(data.get("msg", "")).strip(),
        str(data.get("error", "")).strip(),
        str(data.get("error_msg", "")).strip(),
    ]
    nested = data.get("data")
    if isinstance(nested, dict):
        parts.extend(
            [
                str(nested.get("message", "")).strip(),
                str(nested.get("msg", "")).strip(),
                str(nested.get("error", "")).strip(),
            ]
        )
    detail = next((part for part in parts if part), "")
    return detail or str(fallback or "夸克网盘请求失败")

def _raise_quark_http_error(exc: Exception, fallback: str = "夸克网盘请求失败") -> None:
    status_code = 0
    payload: Dict[str, Any] = {}
    if isinstance(exc, urllib.error.HTTPError):
        status_code = int(exc.code or 0)
        try:
            raw_body = exc.read().decode("utf-8", errors="ignore")
        except Exception:
            raw_body = ""
        payload_obj = safe_json_loads(raw_body, {})
        if isinstance(payload_obj, dict):
            payload = payload_obj
    detail = _extract_quark_error(payload, "")
    if status_code > 0:
        message = f"HTTP {status_code}"
        if detail:
            message = f"{message}: {detail}"
        raise RuntimeError(message) from exc
    if detail:
        raise RuntimeError(detail) from exc
    raise RuntimeError(str(fallback or "夸克网盘请求失败")) from exc

def _request_quark_json(url: str, headers: Dict[str, str], timeout: int = 45, fallback: str = "夸克网盘请求失败") -> Dict[str, Any]:
    try:
        return http_request_json(url, extra_headers=headers, timeout=timeout)
    except Exception as exc:
        _raise_quark_http_error(exc, fallback=fallback)
        return {}

def _request_quark_json_payload(
    url: str,
    payload: Dict[str, Any],
    headers: Dict[str, str],
    timeout: int = 45,
    method: str = "POST",
    fallback: str = "夸克网盘请求失败",
) -> Dict[str, Any]:
    try:
        return http_request_json_payload(
            url,
            payload,
            timeout=timeout,
            extra_headers=headers,
            method=method,
        )
    except Exception as exc:
        _raise_quark_http_error(exc, fallback=fallback)
        return {}

def _is_quark_success(payload: Any) -> bool:
    data = payload if isinstance(payload, dict) else {}
    code = parse_int(data.get("code"), default=0)
    status = parse_int(data.get("status"), default=0)
    success_hints = (
        bool(data.get("success", False)),
        bool(data.get("state", False)),
        code == 0,
        status in (0, 200),
    )
    return any(success_hints)

def resolve_quark_share_payload(cookie: str, share_url: str, raw_text: str = "", receive_code: str = "") -> Dict[str, str]:
    parsed = parse_quark_share_payload(share_url, raw_text, receive_code)
    if parsed.get("pwd_id"):
        return parsed
    headers = _build_quark_headers(cookie, referer="https://pan.quark.cn/")
    resolved_url = http_resolve_url(
        share_url,
        timeout=30,
        extra_headers=headers,
    )
    parsed = parse_quark_share_payload(resolved_url, raw_text, receive_code)
    if not parsed.get("pwd_id"):
        raise RuntimeError("未能识别夸克分享链接")
    return parsed

def _build_quark_api_url(path: str, query: Optional[Dict[str, Any]] = None, host: str = "https://drive-pc.quark.cn") -> str:
    normalized_path = str(path or "").strip()
    if not normalized_path.startswith("/"):
        normalized_path = f"/{normalized_path}"
    params = {"pr": "ucpro", "fr": "pc"}
    if isinstance(query, dict):
        for key, value in query.items():
            if value is None:
                continue
            params[str(key)] = str(value)
    query_string = urllib.parse.urlencode(params)
    return f"{host.rstrip('/')}{normalized_path}?{query_string}"

def _parse_quark_entry(item: Dict[str, Any], parent_id: str = "0") -> Dict[str, Any]:
    payload = item if isinstance(item, dict) else {}
    name = str(payload.get("file_name", "") or payload.get("name", "") or payload.get("title", "")).strip()
    entry_id = str(payload.get("fid", "") or payload.get("id", "") or payload.get("file_id", "")).strip()
    if not name or not entry_id:
        return {}
    is_dir = bool(payload.get("dir")) or str(payload.get("obj_category", "")).strip().lower() in ("dir", "folder")
    file_type = parse_int(payload.get("file_type"), default=-1)
    if file_type == 0:
        is_dir = True
    parent_fid = str(payload.get("pdir_fid", "") or parent_id or "0").strip() or "0"
    fid_token = str(
        payload.get("share_fid_token", "")
        or payload.get("fid_token", "")
        or payload.get("share_token", "")
        or payload.get("file_token", "")
        or ""
    ).strip()
    return {
        "id": entry_id,
        "cid": entry_id if is_dir else "",
        "name": name,
        "is_dir": bool(is_dir),
        "size": parse_int(payload.get("size"), default=0),
        "parent_id": parent_fid,
        "fid": entry_id if not is_dir else "",
        "fid_token": fid_token,
        "modified_at": str(payload.get("updated_at", "") or payload.get("last_update_at", "") or payload.get("create_time", "")).strip(),
    }

def _list_quark_folder_page(cookie: str, pdir_fid: str = "0", page: int = 1, page_size: int = 200) -> Dict[str, Any]:
    headers = _build_quark_headers(cookie, referer="https://pan.quark.cn/")
    url = _build_quark_api_url(
        "/1/clouddrive/file/sort",
        {
            "pdir_fid": str(pdir_fid or "0").strip() or "0",
            "_page": max(1, int(page or 1)),
            "_size": max(20, min(200, int(page_size or 200))),
            "_fetch_total": 1,
            "_fetch_sub_dirs": 1,
            "_sort": "file_type:asc,file_name:asc",
        },
    )
    result = _request_quark_json(url, headers, timeout=45, fallback="读取夸克目录失败")
    if not _is_quark_success(result):
        raise RuntimeError(_extract_quark_error(result, "读取夸克目录失败"))
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    raw_list = data.get("list") if isinstance(data.get("list"), list) else []
    entries = []
    parent_id = str(pdir_fid or "0").strip() or "0"
    for raw_item in raw_list:
        parsed_entry = _parse_quark_entry(raw_item if isinstance(raw_item, dict) else {}, parent_id=parent_id)
        if parsed_entry:
            entries.append(parsed_entry)
    has_more = bool(data.get("has_more", False))
    if not has_more:
        next_page = parse_int(data.get("next_page"), default=0)
        if next_page > max(1, int(page or 1)):
            has_more = True
    total = parse_int(data.get("total"), default=len(entries))
    return {
        "entries": entries,
        "has_more": has_more,
        "total": total,
        "page": max(1, int(page or 1)),
        "size": max(20, min(200, int(page_size or 200))),
    }

def list_quark_entries(cookie: str, cid: str = "0") -> List[Dict[str, Any]]:
    normalized_cookie = str(cookie or "").strip()
    if not normalized_cookie:
        raise RuntimeError("Quark Cookie 未配置")
    try:
        parent_id = str(cid or "0").strip() or "0"
        page = 1
        page_size = 200
        entries: List[Dict[str, Any]] = []
        while True:
            page_payload = _list_quark_folder_page(normalized_cookie, pdir_fid=parent_id, page=page, page_size=page_size)
            current_entries = page_payload.get("entries", []) if isinstance(page_payload.get("entries"), list) else []
            entries.extend(current_entries)
            if not bool(page_payload.get("has_more", False)):
                break
            if len(entries) >= 5000:
                break
            page += 1
        entries.sort(key=lambda item: (0 if item.get("is_dir") else 1, str(item.get("name", "")).lower()))
        mark_cookie_health_success("quark", trigger="runtime:list_quark_entries")
        return entries
    except Exception as exc:
        mark_cookie_health_failure("quark", exc, trigger="runtime:list_quark_entries")
        raise

def create_quark_folder(cookie: str, cid: str = "0", folder_name: str = "") -> Dict[str, Any]:
    normalized_cookie = str(cookie or "").strip()
    if not normalized_cookie:
        raise RuntimeError("Quark Cookie 未配置")
    parent_id = str(cid or "0").strip() or "0"
    normalized_name = sanitize_115_folder_name(folder_name, fallback="")
    if not normalized_name:
        raise RuntimeError("文件夹名称不能为空")

    try:
        headers = _build_quark_headers(normalized_cookie, referer="https://pan.quark.cn/")
        url = _build_quark_api_url("/1/clouddrive/file")
        payload = {
            "pdir_fid": parent_id,
            "file_name": normalized_name,
            "dir_path": "",
            "dir_init_lock": False,
        }
        response = _request_quark_json_payload(
            url,
            payload,
            headers,
            timeout=45,
            method="POST",
            fallback="新建夸克目录失败",
        )
        data = response.get("data") if isinstance(response.get("data"), dict) else {}
        folder_id = str(data.get("fid", "") or data.get("id", "") or "").strip()
        success = _is_quark_success(response)
        if (not success) or (not folder_id):
            entries = list_quark_entries(normalized_cookie, parent_id)
            matched = next(
                (
                    entry
                    for entry in entries
                    if entry.get("is_dir") and str(entry.get("name", "")).strip() == normalized_name
                ),
                None,
            )
            folder_id = str((matched or {}).get("id", "") or "").strip()
        if not folder_id:
            raise RuntimeError(_extract_quark_error(response, "新建夸克目录失败"))
        mark_cookie_health_success("quark", trigger="runtime:create_quark_folder")
        return {
            "id": folder_id,
            "name": normalized_name,
            "cid": parent_id,
            "created": success,
        }
    except Exception as exc:
        mark_cookie_health_failure("quark", exc, trigger="runtime:create_quark_folder")
        raise

def ensure_quark_folder_id_by_path(cookie: str, relative_path: str) -> str:
    normalized_path = normalize_relative_path(relative_path)
    if not normalized_path:
        return "0"
    current_id = "0"
    for raw_part in [segment for segment in normalized_path.split("/") if segment]:
        part = sanitize_115_folder_name(raw_part, fallback="未命名")
        entries = list_quark_entries(cookie, current_id)
        matched = next(
            (
                entry
                for entry in entries
                if entry.get("is_dir") and str(entry.get("name", "")).strip() == part
            ),
            None,
        )
        if matched:
            current_id = str(matched.get("id", "") or "").strip() or current_id
            continue
        created = create_quark_folder(cookie, current_id, part)
        current_id = str(created.get("id", "")).strip() or current_id
    return current_id

def resolve_quark_folder_id_by_path(cookie: str, relative_path: str) -> str:
    normalized_path = normalize_relative_path(relative_path)
    if not normalized_path:
        return "0"
    current_id = "0"
    walked_parts: List[str] = []
    for part in [segment for segment in normalized_path.split("/") if segment]:
        walked_parts.append(part)
        entries = list_quark_entries(cookie, current_id)
        matched = next(
            (
                entry
                for entry in entries
                if entry.get("is_dir") and str(entry.get("name", "")).strip() == part
            ),
            None,
        )
        if not matched:
            raise RuntimeError(f"夸克网盘目录不存在：{join_relative_path(*walked_parts)}")
        current_id = str(matched.get("id", "")).strip() or "0"
    return current_id

def _request_quark_share_token(cookie: str, pwd_id: str, passcode: str = "") -> str:
    headers = _build_quark_headers(cookie, referer=f"https://pan.quark.cn/s/{pwd_id}")
    url = _build_quark_api_url("/1/clouddrive/share/sharepage/token", host="https://drive-h.quark.cn")
    payload = {
        "pwd_id": str(pwd_id or "").strip(),
        "passcode": normalize_receive_code(passcode),
    }
    response = _request_quark_json_payload(
        url,
        payload,
        headers,
        timeout=45,
        method="POST",
        fallback="夸克分享访问失败",
    )
    if not _is_quark_success(response):
        raise RuntimeError(_extract_quark_error(response, "夸克分享访问失败"))
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    stoken = str(data.get("stoken", "") or data.get("token", "")).strip()
    if not stoken:
        raise RuntimeError("夸克分享令牌获取失败")
    return stoken

def _list_quark_share_page(
    cookie: str,
    pwd_id: str,
    stoken: str,
    pdir_fid: str = "0",
    page: int = 1,
    page_size: int = 200,
) -> Dict[str, Any]:
    headers = _build_quark_headers(cookie, referer=f"https://pan.quark.cn/s/{pwd_id}")
    # Quark share detail 接口对 stoken 的解析存在双重 decode 行为；
    # 这里先手动 quote，再交给 urlencode，等价于双编码，避免返回“非法token”。
    stoken_query_value = urllib.parse.quote(str(stoken or "").strip(), safe="")
    url = _build_quark_api_url(
        "/1/clouddrive/share/sharepage/detail",
        {
            "pwd_id": str(pwd_id or "").strip(),
            "stoken": stoken_query_value,
            "pdir_fid": str(pdir_fid or "0").strip() or "0",
            "_page": max(1, int(page or 1)),
            "_size": max(20, min(200, int(page_size or 200))),
            "_fetch_total": 1,
            "_sort": "file_type:asc,file_name:asc",
        },
        host="https://drive-h.quark.cn",
    )
    result = _request_quark_json(url, headers, timeout=45, fallback="读取夸克分享目录失败")
    if not _is_quark_success(result):
        raise RuntimeError(_extract_quark_error(result, "读取夸克分享目录失败"))
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    raw_list = data.get("list") if isinstance(data.get("list"), list) else []
    entries = []
    parent_id = str(pdir_fid or "0").strip() or "0"
    for raw_item in raw_list:
        parsed_entry = _parse_quark_entry(raw_item if isinstance(raw_item, dict) else {}, parent_id=parent_id)
        if parsed_entry:
            entries.append(parsed_entry)
    share_info = data.get("share") if isinstance(data.get("share"), dict) else {}
    if not share_info:
        share_info = data.get("share_info") if isinstance(data.get("share_info"), dict) else {}
    has_more = bool(data.get("has_more", False))
    next_page = parse_int(data.get("next_page"), default=0)
    if not has_more and next_page > max(1, int(page or 1)):
        has_more = True
    total = parse_int(data.get("total"), default=len(entries))
    return {
        "entries": entries,
        "share": share_info,
        "has_more": has_more,
        "total": total,
        "next_page": next_page,
        "page": max(1, int(page or 1)),
        "size": max(20, min(200, int(page_size or 200))),
    }

def _collect_quark_share_entries_with_stoken(
    cookie: str,
    pwd_id: str,
    stoken: str,
    cid: str = "0",
    page_size: int = 200,
    max_pages: int = 20,
    folders_only: bool = False,
) -> Dict[str, Any]:
    current_cid = str(cid or "0").strip() or "0"
    page_limit = max(20, min(200, int(page_size or 200)))
    max_pages_limit = max(1, int(max_pages or 20))
    folder_only_mode = bool(folders_only)
    entries: List[Dict[str, Any]] = []
    pages_scanned = 0
    total_count = 0
    share_title = ""

    page_no = 1
    while True:
        page_payload = _list_quark_share_page(
            cookie,
            pwd_id,
            stoken,
            current_cid,
            page=page_no,
            page_size=page_limit,
        )
        page_entries = page_payload.get("entries", []) if isinstance(page_payload.get("entries"), list) else []
        if folder_only_mode:
            page_entries = [entry for entry in page_entries if entry.get("is_dir")]
        entries.extend(page_entries)
        total_count = max(total_count, int(page_payload.get("total", 0) or 0))
        pages_scanned += 1
        share_info = page_payload.get("share", {}) if isinstance(page_payload.get("share"), dict) else {}
        if share_info and not share_title:
            share_title = str(share_info.get("title", "") or share_info.get("share_name", "") or "").strip()
        if not bool(page_payload.get("has_more", False)):
            break
        if pages_scanned >= max_pages_limit:
            break
        page_no += 1

    entries.sort(key=lambda item: (0 if item.get("is_dir") else 1, str(item.get("name", "")).lower()))
    return {
        "entries": entries,
        "share_title": share_title,
        "count": total_count or len(entries),
        "pages_scanned": pages_scanned,
    }

def list_quark_share_entries(
    cookie: str,
    share_url: str,
    raw_text: str = "",
    cid: str = "0",
    receive_code: str = "",
    force_refresh: bool = False,
    request_timeout: int = 45,
    offset: int = 0,
    limit: int = 200,
    max_pages: int = 0,
    folders_only: bool = False,
) -> Dict[str, Any]:
    del force_refresh
    del request_timeout
    normalized_cookie = str(cookie or "").strip()
    if not normalized_cookie:
        raise RuntimeError("Quark Cookie 未配置")
    try:
        parsed = resolve_quark_share_payload(normalized_cookie, share_url, raw_text, receive_code)
        pwd_id = str(parsed.get("pwd_id", "") or parsed.get("share_code", "")).strip()
        if not pwd_id:
            raise RuntimeError("未能识别夸克分享链接")
        receive_code_value = normalize_receive_code(parsed.get("receive_code", ""))
        current_cid = str(cid or "0").strip() or "0"
        page_limit = max(20, min(200, int(limit or 200)))
        start_offset = max(0, int(offset or 0))
        max_pages_limit = max(0, int(max_pages or 0))
        folder_only_mode = bool(folders_only)

        stoken = _request_quark_share_token(normalized_cookie, pwd_id, receive_code_value)
        entries: List[Dict[str, Any]] = []
        total_count = 0
        pages_scanned = 0
        share_title = ""

        if start_offset <= 0 and max_pages_limit <= 0 and (not folder_only_mode):
            page_no = 1
            while True:
                page_payload = _list_quark_share_page(
                    normalized_cookie,
                    pwd_id,
                    stoken,
                    current_cid,
                    page=page_no,
                    page_size=page_limit,
                )
                page_entries = page_payload.get("entries", []) if isinstance(page_payload.get("entries"), list) else []
                if folder_only_mode:
                    page_entries = [entry for entry in page_entries if entry.get("is_dir")]
                entries.extend(page_entries)
                total_count = max(total_count, int(page_payload.get("total", 0) or 0))
                pages_scanned += 1
                share_info = page_payload.get("share", {}) if isinstance(page_payload.get("share"), dict) else {}
                if share_info and not share_title:
                    share_title = str(share_info.get("title", "") or share_info.get("share_name", "") or "").strip()
                if not bool(page_payload.get("has_more", False)):
                    break
                if pages_scanned >= 20:
                    break
                page_no += 1
            has_more = False
            next_offset = len(entries)
        else:
            page_no = max(1, (start_offset // page_limit) + 1)
            skip_in_page = start_offset % page_limit
            page_payload = _list_quark_share_page(
                normalized_cookie,
                pwd_id,
                stoken,
                current_cid,
                page=page_no,
                page_size=page_limit,
            )
            page_entries = page_payload.get("entries", []) if isinstance(page_payload.get("entries"), list) else []
            if skip_in_page > 0:
                page_entries = page_entries[skip_in_page:]
            if folder_only_mode:
                page_entries = [entry for entry in page_entries if entry.get("is_dir")]
            entries = page_entries
            total_count = max(0, int(page_payload.get("total", 0) or 0))
            pages_scanned = 1
            has_more = bool(page_payload.get("has_more", False))
            next_offset = start_offset + len(entries)
            share_info = page_payload.get("share", {}) if isinstance(page_payload.get("share"), dict) else {}
            share_title = str(share_info.get("title", "") or share_info.get("share_name", "") or "").strip()
            if max_pages_limit > 0 and max_pages_limit <= pages_scanned:
                has_more = False

        entries.sort(key=lambda item: (0 if item.get("is_dir") else 1, str(item.get("name", "")).lower()))
        result_payload = {
            "entries": entries,
            "summary": {
                "folder_count": sum(1 for item in entries if item.get("is_dir")),
                "file_count": sum(1 for item in entries if not item.get("is_dir")),
            },
            "share_code": pwd_id,
            "receive_code": receive_code_value,
            "share_title": share_title,
            "current_cid": current_cid,
            "count": total_count or len(entries),
            "offset": start_offset,
            "next_offset": next_offset,
            "has_more": bool(has_more),
            "pages_scanned": pages_scanned,
            "stoken": stoken,
        }
        mark_cookie_health_success("quark", trigger="runtime:list_quark_share_entries")
        return result_payload
    except Exception as exc:
        mark_cookie_health_failure("quark", exc, trigger="runtime:list_quark_share_entries")
        raise

def prepare_quark_share_save(
    cookie: str,
    share_url: str,
    raw_text: str = "",
    selected_ids: Optional[List[str]] = None,
    receive_code: str = "",
    selected_entries: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    parsed = resolve_quark_share_payload(cookie, share_url, raw_text, receive_code)
    pwd_id = str(parsed.get("pwd_id", "") or parsed.get("share_code", "")).strip()
    receive_code_value = normalize_receive_code(parsed.get("receive_code", ""))
    stoken = _request_quark_share_token(cookie, pwd_id, receive_code_value)

    normalized_ids: List[str] = []
    seen_ids: Set[str] = set()
    selected_entry_token_map: Dict[str, str] = {}
    for entry in selected_entries or []:
        normalized_entry = normalize_share_selection_entry(entry)
        entry_id = str(normalized_entry.get("id", "")).strip()
        if not entry_id:
            continue
        token = str(normalized_entry.get("fid_token", "") or "").strip()
        if token:
            selected_entry_token_map[entry_id] = token

    for raw_id in selected_ids or []:
        entry_id = str(raw_id or "").strip()
        if not entry_id or entry_id in seen_ids:
            continue
        seen_ids.add(entry_id)
        normalized_ids.append(entry_id)

    selection: Dict[str, Any] = {}
    fid_token_list: List[str] = []
    if not normalized_ids:
        snapshot = _collect_quark_share_entries_with_stoken(
            cookie,
            pwd_id,
            stoken,
            cid="0",
            page_size=200,
            max_pages=20,
        )
        snapshot_entries = snapshot.get("entries", []) if isinstance(snapshot.get("entries"), list) else []
        normalized_ids = [str(entry.get("id", "")).strip() for entry in snapshot_entries if str(entry.get("id", "")).strip()]
        fid_token_list = [str(entry.get("fid_token", "") or "").strip() for entry in snapshot_entries if str(entry.get("id", "")).strip()]
        selection = normalize_share_selection_meta(
            {
                "selected_ids": normalized_ids,
                "selected_entries": snapshot_entries,
                "share_root_title": snapshot.get("share_title", ""),
            }
        )
    else:
        snapshot_token_map: Dict[str, str] = {}
        scan_cids: List[str] = ["0"]
        seen_scan_cids: Set[str] = {"0"}
        for entry in selected_entries or []:
            normalized_entry = normalize_share_selection_entry(entry)
            parent_id = str(normalized_entry.get("parent_id", "") or "").strip()
            if parent_id and parent_id not in seen_scan_cids:
                seen_scan_cids.add(parent_id)
                scan_cids.append(parent_id)
            if bool(normalized_entry.get("is_dir")):
                child_cid = str(normalized_entry.get("cid", "") or normalized_entry.get("id", "") or "").strip()
                if child_cid and child_cid not in seen_scan_cids:
                    seen_scan_cids.add(child_cid)
                    scan_cids.append(child_cid)

        for scan_cid in scan_cids:
            try:
                snapshot = _collect_quark_share_entries_with_stoken(
                    cookie,
                    pwd_id,
                    stoken,
                    cid=scan_cid,
                    page_size=200,
                    max_pages=20,
                )
            except Exception:
                continue
            snapshot_entries = snapshot.get("entries", []) if isinstance(snapshot.get("entries"), list) else []
            for entry in snapshot_entries:
                entry_id = str(entry.get("id", "")).strip()
                if not entry_id or entry_id in snapshot_token_map:
                    continue
                fid_token = str(entry.get("fid_token", "") or "").strip()
                if fid_token:
                    snapshot_token_map[entry_id] = fid_token

        fid_token_list = [str(snapshot_token_map.get(entry_id, "") or "").strip() for entry_id in normalized_ids]
        missing_token_ids = [entry_id for index, entry_id in enumerate(normalized_ids) if not fid_token_list[index]]
        if missing_token_ids:
            raise RuntimeError(
                f"夸克分享条目 token 刷新失败，缺失 {len(missing_token_ids)} 项（示例: {missing_token_ids[0]}）"
            )

    if len(fid_token_list) != len(normalized_ids):
        fid_token_list = []
    elif normalized_ids and not any(token for token in fid_token_list):
        fid_token_list = []

    if not normalized_ids:
        raise RuntimeError("分享内容为空，无法转存")
    return {
        "pwd_id": pwd_id,
        "stoken": stoken,
        "receive_code": receive_code_value,
        "fid_list": normalized_ids,
        "fid_token_list": fid_token_list,
        "selection": selection,
        "pdir_fid": "0",
    }

def submit_quark_share_save(
    cookie: str,
    share_url: str,
    folder_id: str,
    raw_text: str = "",
    selected_ids: Optional[List[str]] = None,
    receive_code: str = "",
    selected_entries: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    normalized_cookie = str(cookie or "").strip()
    if not normalized_cookie:
        raise RuntimeError("Quark Cookie 未配置")
    try:
        prepared = prepare_quark_share_save(
            normalized_cookie,
            share_url,
            raw_text,
            selected_ids,
            receive_code,
            selected_entries=selected_entries,
        )

        headers = _build_quark_headers(
            normalized_cookie,
            referer=f"https://pan.quark.cn/s/{str(prepared.get('pwd_id', '')).strip()}",
        )
        payload = {
            "pwd_id": str(prepared.get("pwd_id", "")).strip(),
            "stoken": str(prepared.get("stoken", "")).strip(),
            "pdir_fid": str(prepared.get("pdir_fid", "0")).strip() or "0",
            "to_pdir_fid": str(folder_id or "0").strip() or "0",
            "fid_list": prepared.get("fid_list", []),
            "fid_token_list": prepared.get("fid_token_list", []),
            "scene": "link",
        }

        hosts = ("https://drive-h.quark.cn", "https://drive-pc.quark.cn")
        last_error = ""
        response: Dict[str, Any] = {}
        for host in hosts:
            url = _build_quark_api_url("/1/clouddrive/share/sharepage/save", host=host)
            try:
                response = _request_quark_json_payload(
                    url,
                    payload,
                    headers,
                    timeout=45,
                    method="POST",
                    fallback="夸克网盘转存失败",
                )
            except RuntimeError as exc:
                last_error = str(exc or "夸克网盘转存失败").strip() or "夸克网盘转存失败"
                continue

            if _is_quark_success(response):
                last_error = ""
                break
            last_error = _extract_quark_error(response, "夸克网盘转存失败")

        if last_error:
            raise RuntimeError(last_error)

        mark_cookie_health_success("quark", trigger="runtime:submit_quark_share_save")
        return {
            "response": response,
            "selection": prepared.get("selection", {}),
        }
    except Exception as exc:
        mark_cookie_health_failure("quark", exc, trigger="runtime:submit_quark_share_save")
        raise
