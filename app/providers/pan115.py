from .common import parse_int
from ..share_selection import normalize_share_selection_meta
from ..core import *  # noqa: F401,F403
from ..core import (
    _api_115_last_request_monotonic,
    _api_115_list_cache,
    _api_115_list_cache_lock,
    _api_115_rate_limit_lock,
    _share_snap_last_request_monotonic,
    _share_snap_rate_limit_lock,
)

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
    try:
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
        mark_cookie_health_success("115", trigger="runtime:submit_115_offline_task")
        return response
    except Exception as exc:
        mark_cookie_health_failure("115", exc, trigger="runtime:submit_115_offline_task")
        raise

def throttle_115_api_requests(rate_limit_seconds: float = 0.0) -> None:
    global _api_115_last_request_monotonic
    min_interval = float(rate_limit_seconds or 0.0)
    if min_interval <= 0:
        min_interval = float(get_api_115_runtime_tuning().get("rate_limit_seconds", API_115_RATE_LIMIT_SECONDS) or 0.0)
    if min_interval <= 0:
        return
    with _api_115_rate_limit_lock:
        now_mono = time.monotonic()
        wait_seconds = min_interval - (now_mono - _api_115_last_request_monotonic)
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        _api_115_last_request_monotonic = time.monotonic()

def _clone_115_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [dict(item or {}) for item in (entries or [])]

def _prune_115_list_cache_locked(now_ts: float) -> None:
    if not _api_115_list_cache:
        return
    expired_keys = [
        key
        for key, payload in _api_115_list_cache.items()
        if now_ts >= float(payload.get("expires_at", 0.0) or 0.0)
    ]
    for key in expired_keys:
        _api_115_list_cache.pop(key, None)
    max_rows = max(200, int(API_115_LIST_CACHE_MAX_ROWS or 2000))
    if len(_api_115_list_cache) <= max_rows:
        return
    ordered = sorted(
        _api_115_list_cache.items(),
        key=lambda item: float((item[1] or {}).get("updated_at", 0.0) or 0.0),
    )
    overflow = len(_api_115_list_cache) - max_rows
    for key, _ in ordered[:overflow]:
        _api_115_list_cache.pop(key, None)

def invalidate_115_entries_cache(cid: str = "") -> None:
    target_cid = str(cid or "").strip()
    with _api_115_list_cache_lock:
        if not target_cid:
            _api_115_list_cache.clear()
            return
        _api_115_list_cache.pop(target_cid, None)

def list_115_entries(cookie: str, cid: str = "0", force_refresh: bool = False) -> List[Dict[str, Any]]:
    cookie = str(cookie or "").strip()
    if not cookie:
        raise RuntimeError("115 Cookie 未配置")
    target_cid = str(cid or "0").strip() or "0"
    runtime_tuning = get_api_115_runtime_tuning()
    cache_ttl_seconds = max(0, int(runtime_tuning.get("list_cache_ttl_seconds", API_115_LIST_CACHE_TTL_SECONDS) or 0))

    if (not force_refresh) and cache_ttl_seconds > 0:
        now_ts = time.time()
        with _api_115_list_cache_lock:
            cached = _api_115_list_cache.get(target_cid)
            if cached and now_ts < float(cached.get("expires_at", 0.0) or 0.0):
                return _clone_115_entries(cached.get("entries", []))

    try:
        throttle_115_api_requests()
        headers = {
            "Cookie": cookie,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://115.com/",
            "User-Agent": "Mozilla/5.0 115-media-hub",
        }
        url = (
            "https://aps.115.com/natsort/files.php"
            f"?aid=1&cid={urllib.parse.quote(target_cid)}&offset=0&limit=300&show_dir=1&natsort=1&format=json"
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
        if cache_ttl_seconds > 0:
            now_ts = time.time()
            with _api_115_list_cache_lock:
                _api_115_list_cache[target_cid] = {
                    "entries": _clone_115_entries(entries),
                    "updated_at": now_ts,
                    "expires_at": now_ts + cache_ttl_seconds,
                }
                _prune_115_list_cache_locked(now_ts)
        mark_cookie_health_success("115", trigger="runtime:list_115_entries")
        return entries
    except Exception as exc:
        mark_cookie_health_failure("115", exc, trigger="runtime:list_115_entries")
        raise

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

    try:
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
            entries = list_115_entries(cookie, parent_cid, True)
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
        invalidate_115_entries_cache(parent_cid)
        mark_cookie_health_success("115", trigger="runtime:create_115_folder")

        return {
            "id": folder_id,
            "name": normalized_name,
            "cid": parent_cid,
            "created": success,
        }
    except Exception as exc:
        mark_cookie_health_failure("115", exc, trigger="runtime:create_115_folder")
        raise

def sanitize_115_folder_name(value: str, fallback: str = "未命名") -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", " ", str(value or "")).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned or cleaned in (".", ".."):
        cleaned = fallback
    return cleaned[:120]

def ensure_115_folder_id_by_path(cookie: str, relative_path: str) -> str:
    normalized_path = normalize_relative_path(relative_path)
    if not normalized_path:
        return "0"
    current_cid = "0"
    for raw_part in [segment for segment in normalized_path.split("/") if segment]:
        part = str(raw_part or "").strip()
        if not part:
            continue
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

def _build_115_share_cache_key(
    cache_kind: str,
    share_code: str,
    receive_code: str,
    cid: str,
    extra: str = "",
) -> str:
    source = (
        f"{str(cache_kind or 'snap').strip()}|"
        f"{str(share_code or '').strip()}|"
        f"{str(receive_code or '').strip()}|"
        f"{str(cid or '0').strip() or '0'}|"
        f"{str(extra or '').strip()}"
    )
    return hashlib.sha1(source.encode("utf-8")).hexdigest()

def _build_115_share_snap_cache_key(share_code: str, receive_code: str, cid: str) -> str:
    return _build_115_share_cache_key("snap", share_code, receive_code, cid)

def _build_115_share_page_cache_key(
    share_code: str,
    receive_code: str,
    cid: str,
    offset: int,
    limit: int,
    folders_only: bool,
) -> str:
    return _build_115_share_cache_key(
        "page",
        share_code,
        receive_code,
        cid,
        extra=f"{max(0, int(offset or 0))}|{max(20, min(400, int(limit or 200)))}|{1 if folders_only else 0}",
    )

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

def _load_share_entries_cache_payload(cache_key: str, allow_expired: bool = False) -> Dict[str, Any]:
    normalized_cache_key = str(cache_key or "").strip()
    if not normalized_cache_key:
        return {}
    ensure_db()
    conn = open_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT payload_json, expires_at FROM share_entries_cache WHERE cache_key = ?", (normalized_cache_key,))
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
    return _load_share_entries_cache_payload(cache_key, allow_expired=allow_expired)

def load_115_share_page_cache(
    share_code: str,
    receive_code: str,
    cid: str,
    offset: int,
    limit: int,
    folders_only: bool = False,
    allow_expired: bool = False,
) -> Dict[str, Any]:
    normalized_share_code = str(share_code or "").strip()
    if not normalized_share_code:
        return {}
    cache_key = _build_115_share_page_cache_key(normalized_share_code, receive_code, cid, offset, limit, folders_only)
    return _load_share_entries_cache_payload(cache_key, allow_expired=allow_expired)

def _save_share_entries_cache_payload(
    cache_key: str,
    share_code: str,
    receive_code: str,
    cid: str,
    payload: Dict[str, Any],
    ttl_seconds: int = SHARE_SNAP_CACHE_TTL_SECONDS,
) -> None:
    normalized_cache_key = str(cache_key or "").strip()
    normalized_share_code = str(share_code or "").strip()
    if not normalized_cache_key or not normalized_share_code or not isinstance(payload, dict):
        return
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
                normalized_cache_key,
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
    _save_share_entries_cache_payload(cache_key, normalized_share_code, receive_code, cid, payload, ttl_seconds=ttl_seconds)

def save_115_share_page_cache(
    share_code: str,
    receive_code: str,
    cid: str,
    offset: int,
    limit: int,
    folders_only: bool,
    payload: Dict[str, Any],
    ttl_seconds: int = SHARE_SNAP_CACHE_TTL_SECONDS,
) -> None:
    normalized_share_code = str(share_code or "").strip()
    if not normalized_share_code or not isinstance(payload, dict):
        return
    cache_key = _build_115_share_page_cache_key(normalized_share_code, receive_code, cid, offset, limit, folders_only)
    _save_share_entries_cache_payload(cache_key, normalized_share_code, receive_code, cid, payload, ttl_seconds=ttl_seconds)

def _slice_115_share_cache_payload(
    payload: Dict[str, Any],
    offset: int = 0,
    limit: int = 200,
    folders_only: bool = False,
) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    source_entries = payload.get("entries", [])
    if not isinstance(source_entries, list):
        return {}
    start_offset = max(0, int(offset or 0))
    page_limit = max(20, min(400, int(limit or 200)))
    filtered_entries = [entry for entry in source_entries if (not folders_only) or bool((entry or {}).get("is_dir"))]
    page_entries = filtered_entries[start_offset:start_offset + page_limit]
    filtered_total = len(filtered_entries)
    next_offset = start_offset + len(page_entries)
    return {
        "entries": page_entries,
        "summary": {
            "folder_count": sum(1 for item in page_entries if (item or {}).get("is_dir")),
            "file_count": sum(1 for item in page_entries if not (item or {}).get("is_dir")),
        },
        "share_code": str(payload.get("share_code", "") or "").strip(),
        "receive_code": str(payload.get("receive_code", "") or "").strip(),
        "share_title": str(payload.get("share_title", "") or "").strip(),
        "current_cid": str(payload.get("current_cid", "") or "0").strip() or "0",
        "count": filtered_total if folders_only else max(filtered_total, int(payload.get("count", filtered_total) or filtered_total)),
        "offset": start_offset,
        "next_offset": next_offset,
        "has_more": next_offset < filtered_total,
        "pages_scanned": int(payload.get("pages_scanned", 0) or 0),
        "cache_derived": True,
    }

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
    offset: int = 0,
    limit: int = 200,
    max_pages: int = 0,
    folders_only: bool = False,
) -> Dict[str, Any]:
    cookie = str(cookie or "").strip()
    if not cookie:
        raise RuntimeError("115 Cookie 未配置")
    try:
        parsed = resolve_115_share_payload(cookie, share_url, raw_text, receive_code)
        share_code = str(parsed.get("share_code", "") or "").strip()
        receive_code = str(parsed.get("receive_code", "") or "").strip()
        current_cid = str(cid or "0").strip() or "0"
        start_offset = max(0, int(offset or 0))
        page_limit = max(20, min(400, int(limit or 200)))
        max_pages_limit = max(0, int(max_pages or 0))
        folder_only_mode = bool(folders_only)
        use_full_cache = start_offset == 0 and max_pages_limit <= 0 and not folder_only_mode
        stale_full_cache: Dict[str, Any] = load_115_share_snap_cache(share_code, receive_code, current_cid, allow_expired=True)
        stale_page_cache: Dict[str, Any] = load_115_share_page_cache(
            share_code,
            receive_code,
            current_cid,
            start_offset,
            page_limit,
            folder_only_mode,
            allow_expired=True,
        )
        if not force_refresh:
            fresh_full_cache = load_115_share_snap_cache(share_code, receive_code, current_cid, allow_expired=False)
            if use_full_cache and fresh_full_cache:
                return fresh_full_cache
            if fresh_full_cache:
                sliced_payload = _slice_115_share_cache_payload(
                    fresh_full_cache,
                    offset=start_offset,
                    limit=page_limit,
                    folders_only=folder_only_mode,
                )
                if sliced_payload:
                    return sliced_payload
            fresh_page_cache = load_115_share_page_cache(
                share_code,
                receive_code,
                current_cid,
                start_offset,
                page_limit,
                folder_only_mode,
                allow_expired=False,
            )
            if fresh_page_cache:
                return fresh_page_cache

        request_timeout_value = max(5, int(request_timeout or 45))
        retry_total = max(0, int(max_request_retries or 0))

        headers = {
            "Cookie": cookie,
            "Accept": "application/json, text/plain, */*",
            "Referer": parsed.get("url", "https://115.com/"),
            "User-Agent": "Mozilla/5.0 115-media-hub",
        }
        entries: List[Dict[str, Any]] = []
        offset_cursor = start_offset
        total_count = 0
        pages_scanned = 0

        while True:
            query = urllib.parse.urlencode(
                {
                    "share_code": share_code,
                    "receive_code": receive_code,
                    "cid": current_cid,
                    "offset": offset_cursor,
                    "limit": page_limit,
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
                stale_payload = {}
                if use_full_cache and stale_full_cache:
                    stale_payload = dict(stale_full_cache)
                elif stale_page_cache:
                    stale_payload = dict(stale_page_cache)
                elif stale_full_cache:
                    stale_payload = _slice_115_share_cache_payload(
                        stale_full_cache,
                        offset=start_offset,
                        limit=page_limit,
                        folders_only=folder_only_mode,
                    )
                if stale_payload:
                    mark_cookie_health_failure("115", last_request_error, trigger="runtime:list_115_share_entries")
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
                stale_payload = {}
                if use_full_cache and stale_full_cache:
                    stale_payload = dict(stale_full_cache)
                elif stale_page_cache:
                    stale_payload = dict(stale_page_cache)
                elif stale_full_cache:
                    stale_payload = _slice_115_share_cache_payload(
                        stale_full_cache,
                        offset=start_offset,
                        limit=page_limit,
                        folders_only=folder_only_mode,
                    )
                if stale_payload:
                    mark_cookie_health_failure("115", detail, trigger="runtime:list_115_share_entries")
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
                if folder_only_mode and not is_dir:
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

            pages_scanned += 1
            next_offset = offset_cursor + len(batch)
            reached_end = not batch or len(batch) < page_limit or (total_count and next_offset >= total_count)
            reached_page_cap = max_pages_limit > 0 and pages_scanned >= max_pages_limit

            if reached_end or reached_page_cap:
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
                    "offset": start_offset,
                    "next_offset": next_offset,
                    "has_more": not reached_end,
                    "pages_scanned": pages_scanned,
                }
                if use_full_cache:
                    save_115_share_snap_cache(
                        share_code,
                        receive_code,
                        current_cid,
                        result_payload,
                        ttl_seconds=SHARE_SNAP_CACHE_TTL_SECONDS,
                    )
                else:
                    save_115_share_page_cache(
                        share_code,
                        receive_code,
                        current_cid,
                        start_offset,
                        page_limit,
                        folder_only_mode,
                        result_payload,
                        ttl_seconds=SHARE_SNAP_CACHE_TTL_SECONDS,
                    )
                mark_cookie_health_success("115", trigger="runtime:list_115_share_entries")
                return result_payload
            offset_cursor = next_offset
    except Exception as exc:
        mark_cookie_health_failure("115", exc, trigger="runtime:list_115_share_entries")
        raise

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
    try:
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
        mark_cookie_health_success("115", trigger="runtime:submit_115_share_receive")
        return {
            "response": response,
            "selection": prepared.get("selection", {}),
            "duplicate_receive": is_115_share_receive_duplicate_response(response),
        }
    except Exception as exc:
        mark_cookie_health_failure("115", exc, trigger="runtime:submit_115_share_receive")
        raise
