import threading
import logging

import requests

from .common import parse_int
from .base import CloudProvider
from .registry import register
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

_pan115_http_local = threading.local()
_CLOUD115_WEBAPI_REFERER = "https://servicewechat.com/wx2c744c010a61b0fa/94/page-frame.html"
_CLOUD115_WEBAPI_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36 "
    "MicroMessenger/6.8.0(0x16080000) NetType/WIFI MiniProgramEnv/Mac "
    "MacWechat/WMPF MacWechat/3.8.9(0x13080910) XWEB/1227"
)


def _build_115_timing_mark(last_mono: float) -> Tuple[int, float]:
    now_mono = time.monotonic()
    return int((now_mono - last_mono) * 1000), now_mono


def _log_115_share_timing(share_code: str, cid: str, timings: List[Dict[str, Any]], total_ms: int) -> None:
    safe_share_code = str(share_code or "").strip()
    safe_cid = str(cid or "0").strip() or "0"
    stage_text = " / ".join(
        f"{str(item.get('label', '') or item.get('stage', '')).strip()}: {int(item.get('ms', 0) or 0)}ms"
        for item in (timings or [])
        if int(item.get("ms", 0) or 0) >= 0
    )
    logging.info(
        "115 share timing share_code=%s cid=%s total=%sms%s",
        f"{safe_share_code[:6]}***" if len(safe_share_code) > 6 else safe_share_code,
        safe_cid,
        total_ms,
        f" stages=[{stage_text}]" if stage_text else "",
    )


def _get_115_webapi_session() -> requests.Session:
    session = getattr(_pan115_http_local, "webapi_session", None)
    if session is None:
        session = requests.Session()
        _pan115_http_local.webapi_session = session
    return session


def _build_115_webapi_headers(cookie: str, referer: str = "") -> Dict[str, str]:
    return {
        "Cookie": str(cookie or "").strip(),
        "Accept": "application/json, text/plain, */*",
        "Connection": "keep-alive",
        "xweb_xhr": "1",
        "Referer": str(referer or "").strip() or _CLOUD115_WEBAPI_REFERER,
        "User-Agent": _CLOUD115_WEBAPI_USER_AGENT,
        "Accept-Language": "zh-CN,zh;q=0.9",
    }


def _request_115_webapi_json(url: str, headers: Dict[str, str], timeout: int = 30) -> Dict[str, Any]:
    response = _get_115_webapi_session().get(
        normalize_http_url(url),
        headers=headers,
        timeout=max(3, int(timeout or 30)),
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("115 返回内容不是有效 JSON") from exc
    return payload if isinstance(payload, dict) else {}


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


def _normalize_115_offline_task(item: Any) -> Dict[str, Any]:
    source = item if isinstance(item, dict) else {}
    status = parse_int(source.get("status", 0), default=0)
    percent = 0.0
    try:
        percent = float(source.get("percentDone", 0) or 0)
    except (TypeError, ValueError):
        percent = 0.0
    return {
        "info_hash": str(source.get("info_hash", "") or "").strip(),
        "url": str(source.get("url", "") or "").strip(),
        "name": str(source.get("name", "") or "").strip(),
        "size": parse_int(source.get("size", 0), default=0),
        "status": status,
        "percent": max(0.0, min(100.0, percent)),
        "file_id": str(source.get("file_id", "") or "").strip(),
        "delete_file_id": str(source.get("delete_file_id", "") or "").strip(),
        "wp_path_id": str(source.get("wp_path_id", "") or "").strip(),
        "add_time": parse_int(source.get("add_time", 0), default=0),
    }


def list_115_offline_tasks(cookie: str, page: int = 1) -> Dict[str, Any]:
    """读取 115 官方离线任务列表；返回 {tasks, page, page_count, count, total}。"""
    cookie = str(cookie or "").strip()
    if not cookie:
        raise RuntimeError("115 Cookie 未配置")
    normalized_page = max(1, int(page or 1))
    headers = {
        "Cookie": cookie,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://115.com/",
        "User-Agent": "Mozilla/5.0 115-media-hub",
    }
    url = f"https://lixian.115.com/lixian/?ct=lixian&ac=task_lists&page={normalized_page}"
    try:
        throttle_115_api_requests()
        response = http_request_json(url, extra_headers=headers, timeout=45)
        if not bool((response or {}).get("state", False)):
            detail = (
                str((response or {}).get("error", "")).strip()
                or str((response or {}).get("msg", "")).strip()
                or str((response or {}).get("message", "")).strip()
                or "115 离线任务列表读取失败"
            )
            raise RuntimeError(detail)
        raw_tasks = (response or {}).get("tasks") or []
        tasks = [
            normalized
            for normalized in (
                _normalize_115_offline_task(item) for item in raw_tasks if isinstance(item, dict)
            )
            if normalized.get("info_hash") or normalized.get("url")
        ]
        page_count = max(1, parse_int((response or {}).get("page_count", 1), default=1))
        mark_cookie_health_success("115", trigger="runtime:list_115_offline_tasks")
        return {
            "tasks": tasks,
            "page": parse_int((response or {}).get("page", normalized_page), default=normalized_page),
            "page_count": page_count,
            "count": parse_int((response or {}).get("count", len(tasks)), default=len(tasks)),
            "total": parse_int((response or {}).get("total", len(tasks)), default=len(tasks)),
        }
    except Exception as exc:
        mark_cookie_health_failure("115", exc, trigger="runtime:list_115_offline_tasks")
        raise


def submit_115_export_dir(
    cookie: str,
    file_ids: Any,
    target: str = "U_1_0",
    layer_limit: int = 0,
) -> str:
    """提交官方“导出目录树”异步任务，返回任务 id。"""
    cookie = str(cookie or "").strip()
    if not cookie:
        raise RuntimeError("115 Cookie 未配置")
    normalized_ids = str(file_ids or "").strip()
    if not normalized_ids:
        raise RuntimeError("导出目录不能为空")
    payload = {"file_ids": normalized_ids, "target": str(target or "U_1_0").strip() or "U_1_0"}
    try:
        layer_limit = max(0, min(25, int(layer_limit or 0)))
    except (TypeError, ValueError):
        layer_limit = 0
    if layer_limit > 0:
        payload["layer_limit"] = layer_limit
    headers = {
        "Cookie": cookie,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://115.com/",
        "Origin": "https://115.com",
        "User-Agent": "Mozilla/5.0 115-media-hub",
    }
    try:
        response = http_request_form_json(
            "https://webapi.115.com/files/export_dir",
            payload,
            timeout=45,
            extra_headers=headers,
        )
        if not bool((response or {}).get("state", False)):
            detail = (
                str((response or {}).get("error", "")).strip()
                or str((response or {}).get("msg", "")).strip()
                or str((response or {}).get("message", "")).strip()
                or "115 导出目录树提交失败"
            )
            raise RuntimeError(detail)
        data = (response or {}).get("data") or {}
        export_id = str((data or {}).get("export_id", "") or "").strip()
        if not export_id:
            raise RuntimeError("115 导出目录树未返回任务 ID")
        mark_cookie_health_success("115", trigger="runtime:submit_115_export_dir")
        return export_id
    except Exception as exc:
        mark_cookie_health_failure("115", exc, trigger="runtime:submit_115_export_dir")
        raise


def query_115_export_dir_status(cookie: str, export_id: str) -> Dict[str, Any]:
    """查询导出目录树任务状态；完成时返回 {export_id,file_id,file_name,pick_code}，否则返回空字典。"""
    cookie = str(cookie or "").strip()
    if not cookie:
        raise RuntimeError("115 Cookie 未配置")
    normalized_id = str(export_id or "").strip()
    if not normalized_id:
        raise RuntimeError("导出任务 ID 不能为空")
    url = "https://webapi.115.com/files/export_dir?export_id=" + urllib.parse.quote(normalized_id)
    result = _request_115_webapi_json(url, headers=_build_115_webapi_headers(cookie))
    if not bool((result or {}).get("state", False)):
        detail = (
            str((result or {}).get("error", "")).strip()
            or str((result or {}).get("msg", "")).strip()
            or "115 导出目录树状态查询失败"
        )
        raise RuntimeError(detail)
    data = (result or {}).get("data") or {}
    if not isinstance(data, dict) or not data:
        return {}
    return {
        key: str(data.get(key, "") or "").strip()
        for key in ("export_id", "file_id", "file_name", "pick_code")
        if str(data.get(key, "") or "").strip()
    }


def wait_115_export_dir(
    cookie: str,
    export_id: str,
    timeout_seconds: int = 600,
    check_interval: float = 2.0,
) -> Dict[str, Any]:
    """轮询导出目录树直到完成；超时抛错（任务仍在服务端执行）。"""
    started = time.monotonic()
    interval = max(0.5, float(check_interval or 2.0))
    timeout = max(0, int(timeout_seconds or 600))
    while True:
        throttle_115_api_requests()
        data = query_115_export_dir_status(cookie, export_id)
        if data:
            return data
        if timeout > 0 and time.monotonic() - started >= timeout:
            raise RuntimeError(
                f"115 导出目录树超时（{timeout} 秒，export_id={export_id}），任务可能仍在服务端执行"
            )
        time.sleep(interval)


def get_115_file_sha1_by_id(cookie: str, file_id: str, attempts: int = 3) -> str:
    """按 file_id 取新导出文件的 sha1（优先 get_info 直查）；拿不到时返回空字符串。"""
    cookie = str(cookie or "").strip()
    normalized_id = str(file_id or "").strip()
    if not cookie or not normalized_id:
        return ""
    for _ in range(max(1, int(attempts or 3))):
        try:
            info = get_115_file_info(cookie, normalized_id)
            if info:
                sha1 = str(info.get("sha1", "") or "").strip()
                if sha1:
                    return sha1
        except Exception:
            pass
        try:
            entries = list_115_entries(cookie, "0", force_refresh=True)
            matched = next(
                (item for item in entries if str(item.get("id", "") or "").strip() == normalized_id),
                None,
            )
            if matched:
                sha1 = str(matched.get("sha1", "") or "").strip()
                if sha1:
                    return sha1
        except Exception:
            pass
        time.sleep(1.0)
    return ""


def get_115_file_info(cookie: str, file_id: str) -> Dict[str, Any]:
    """按 file_id 直查 115 文件信息（即时，不受目录列表缓存延迟影响）。"""
    cookie = str(cookie or "").strip()
    normalized_id = str(file_id or "").strip()
    if not cookie:
        raise RuntimeError("115 Cookie 未配置")
    if not normalized_id:
        raise RuntimeError("文件 ID 不能为空")
    url = "https://webapi.115.com/files/get_info?file_id=" + urllib.parse.quote(normalized_id)
    result = _request_115_webapi_json(url, headers=_build_115_webapi_headers(cookie))
    if not bool((result or {}).get("state", False)):
        detail = (
            str((result or {}).get("error", "")).strip()
            or str((result or {}).get("msg", "")).strip()
            or "115 文件信息查询失败"
        )
        raise RuntimeError(detail)
    raw_items = (result or {}).get("data") or []
    items = raw_items if isinstance(raw_items, list) else ([raw_items] if isinstance(raw_items, dict) else [])
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("fid") or item.get("file_id") or item.get("id") or "").strip()
        if item_id and item_id != normalized_id:
            continue
        return {
            "id": item_id or normalized_id,
            "name": str(item.get("n") or item.get("name") or "").strip(),
            "sha1": str(item.get("sha") or item.get("sha1") or "").strip(),
            "pick_code": str(item.get("pc") or item.get("pick_code") or "").strip(),
            "size": parse_int(item.get("s") or item.get("size") or 0),
        }
    raise RuntimeError(f"115 文件不存在或已删除：{normalized_id}")


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


def _clone_115_entries_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    return {
        "entries": _clone_115_entries(source.get("entries", [])),
        "summary": dict(source.get("summary", {}) if isinstance(source.get("summary"), dict) else {}),
        "entries_complete": bool(source.get("entries_complete", True)),
    }


def _build_115_list_cache_key(cid: str, folders_only: bool = False) -> str:
    target_cid = str(cid or "0").strip() or "0"
    return f"{target_cid}|{'folders' if folders_only else 'full'}"


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


def prune_115_list_cache() -> Dict[str, int]:
    now_ts = time.time()
    with _api_115_list_cache_lock:
        before = len(_api_115_list_cache)
        _prune_115_list_cache_locked(now_ts)
        return {"removed": max(0, before - len(_api_115_list_cache))}


def invalidate_115_entries_cache(cid: str = "") -> None:
    target_cid = str(cid or "").strip()
    with _api_115_list_cache_lock:
        if not target_cid:
            _api_115_list_cache.clear()
            return
        _api_115_list_cache.pop(target_cid, None)
        _api_115_list_cache.pop(_build_115_list_cache_key(target_cid, False), None)
        _api_115_list_cache.pop(_build_115_list_cache_key(target_cid, True), None)


def _normalize_115_file_entry(item: Dict[str, Any]) -> Dict[str, Any]:
    source = item if isinstance(item, dict) else {}
    name = str(source.get("n") or source.get("name") or "").strip()
    folder_id = str(source.get("cid") or "").strip()
    file_id = str(source.get("fid") or source.get("file_id") or source.get("id") or "").strip()
    sha1 = str(source.get("sha1") or source.get("sha") or "").strip()
    is_dir = bool(folder_id) and not file_id and not sha1
    entry_id = folder_id if is_dir else (file_id or str(source.get("pick_code") or source.get("pc") or sha1).strip())
    if not name or not entry_id:
        return {}
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


def _request_115_entries_payload_fast(
    cookie: str,
    target_cid: str,
    folders_only: bool,
    timeout: int = 30,
) -> Dict[str, Any]:
    page_limit = 300
    params = {
        "aid": 1,
        "cid": target_cid,
        "o": "user_ptime",
        "asc": 1,
        "offset": 0,
        "show_dir": 1,
        "limit": page_limit,
        "type": 0,
        "format": "json",
        "star": 0,
        "suffix": "",
        "natsort": 0,
        "snap": 0,
        "record_open_time": 1,
        "fc_mix": 0,
    }
    url = f"https://webapi.115.com/files?{urllib.parse.urlencode(params)}"
    result = _request_115_webapi_json(
        url,
        headers=_build_115_webapi_headers(cookie),
        timeout=timeout,
    )
    if not result.get("state", False):
        detail = str(result.get("error", "") or result.get("msg", "") or "读取 115 文件夹失败").strip()
        raise RuntimeError(detail)
    raw_entries = result.get("data") or []
    entries = [
        entry
        for entry in (_normalize_115_file_entry(item) for item in raw_entries)
        if entry.get("id") and entry.get("name") and ((not folders_only) or entry.get("is_dir"))
    ]
    entries.sort(key=lambda item: (0 if item["is_dir"] else 1, str(item["name"]).lower()))
    folder_count = sum(1 for item in entries if item.get("is_dir"))
    total_count = max(0, parse_int(result.get("count") or result.get("total") or 0))
    if folders_only:
        file_count = max(0, total_count - folder_count) if total_count > folder_count else 0
    else:
        file_count = sum(1 for item in entries if not item.get("is_dir"))
    return {
        "entries": entries,
        "summary": {
            "folder_count": folder_count,
            "file_count": file_count,
        },
        "entries_complete": not folders_only,
    }


def _request_115_entries_payload_legacy(
    cookie: str,
    target_cid: str,
    folders_only: bool,
    timeout: int = 45,
) -> Dict[str, Any]:
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
    result = http_request_json(url, extra_headers=headers, timeout=timeout)
    if not result.get("state", False):
        detail = str(result.get("error", "") or result.get("msg", "") or "读取 115 文件夹失败").strip()
        raise RuntimeError(detail)

    all_entries = [
        entry
        for entry in (_normalize_115_file_entry(item) for item in (result.get("data") or []))
        if entry.get("id") and entry.get("name")
    ]
    entries = [entry for entry in all_entries if (not folders_only) or entry.get("is_dir")]
    entries.sort(key=lambda item: (0 if item["is_dir"] else 1, str(item["name"]).lower()))
    folder_count = sum(1 for item in entries if item.get("is_dir"))
    file_count = max(0, len(all_entries) - sum(1 for item in all_entries if item.get("is_dir")))
    return {
        "entries": entries,
        "summary": {
            "folder_count": folder_count,
            "file_count": file_count,
        },
        "entries_complete": not folders_only,
    }


def list_115_entries_payload(
    cookie: str,
    cid: str = "0",
    force_refresh: bool = False,
    folders_only: bool = False,
) -> Dict[str, Any]:
    cookie = str(cookie or "").strip()
    if not cookie:
        raise RuntimeError("115 Cookie 未配置")
    target_cid = str(cid or "0").strip() or "0"
    folder_only_mode = bool(folders_only)
    runtime_tuning = get_api_115_runtime_tuning()
    cache_ttl_seconds = max(0, int(runtime_tuning.get("list_cache_ttl_seconds", API_115_LIST_CACHE_TTL_SECONDS) or 0))
    cache_key = _build_115_list_cache_key(target_cid, folder_only_mode)

    if (not force_refresh) and cache_ttl_seconds > 0:
        now_ts = time.time()
        with _api_115_list_cache_lock:
            cached = _api_115_list_cache.get(cache_key)
            if (not folder_only_mode) and not cached:
                cached = _api_115_list_cache.get(target_cid)
            if cached and now_ts < float(cached.get("expires_at", 0.0) or 0.0):
                return _clone_115_entries_payload(cached)

    try:
        throttle_115_api_requests()
        if folder_only_mode:
            try:
                payload = _request_115_entries_payload_fast(cookie, target_cid, folder_only_mode, timeout=30)
            except Exception:
                payload = _request_115_entries_payload_legacy(cookie, target_cid, folder_only_mode, timeout=45)
        else:
            payload = _request_115_entries_payload_legacy(cookie, target_cid, folder_only_mode, timeout=45)
        if cache_ttl_seconds > 0:
            now_ts = time.time()
            with _api_115_list_cache_lock:
                _api_115_list_cache[cache_key] = {
                    "entries": _clone_115_entries(payload.get("entries", [])),
                    "summary": dict(payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}),
                    "entries_complete": bool(payload.get("entries_complete", True)),
                    "updated_at": now_ts,
                    "expires_at": now_ts + cache_ttl_seconds,
                }
                _prune_115_list_cache_locked(now_ts)
        mark_cookie_health_success("115", trigger="runtime:list_115_entries")
        return _clone_115_entries_payload(payload)
    except Exception as exc:
        mark_cookie_health_failure("115", exc, trigger="runtime:list_115_entries")
        raise


def list_115_entries(
    cookie: str,
    cid: str = "0",
    force_refresh: bool = False,
    folders_only: bool = False,
) -> List[Dict[str, Any]]:
    payload = list_115_entries_payload(cookie, cid, force_refresh=force_refresh, folders_only=folders_only)
    return _clone_115_entries(payload.get("entries", []))

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
            entries = list_115_entries(cookie, parent_cid, True, folders_only=True)
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


def _validate_115_entry_name(value: str) -> str:
    normalized_name = str(value or "").strip()
    if not normalized_name:
        raise RuntimeError("文件名称不能为空")
    if any(ch in normalized_name for ch in ("/", "\\")):
        raise RuntimeError("文件名称不能包含 / 或 \\")
    if normalized_name in (".", ".."):
        raise RuntimeError("文件名称不合法")
    if len(normalized_name) > 240:
        raise RuntimeError("文件名称过长")
    return normalized_name


def _build_115_indexed_fid_payload(ids: List[str]) -> Dict[str, str]:
    return {
        f"fid[{index}]": str(entry_id).strip()
        for index, entry_id in enumerate(ids)
        if str(entry_id or "").strip()
    }


def rename_115_entry(cookie: str, entry_id: str, new_name: str, parent_cid: str = "") -> Dict[str, Any]:
    normalized_cookie = str(cookie or "").strip()
    if not normalized_cookie:
        raise RuntimeError("115 Cookie 未配置")
    normalized_id = str(entry_id or "").strip()
    if not normalized_id:
        raise RuntimeError("文件 ID 不能为空")
    normalized_name = _validate_115_entry_name(new_name)
    try:
        headers = {
            "Cookie": normalized_cookie,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://115.com/",
            "Origin": "https://115.com",
            "User-Agent": "Mozilla/5.0 115-media-hub",
        }
        response = http_request_form_json(
            "https://webapi.115.com/files/batch_rename",
            {f"files_new_name[{normalized_id}]": normalized_name},
            timeout=45,
            extra_headers=headers,
        )
        success = bool((response or {}).get("state")) or int((response or {}).get("errno", 0) or 0) == 0
        if not success:
            detail = (
                str((response or {}).get("error", "")).strip()
                or str((response or {}).get("msg", "")).strip()
                or str((response or {}).get("message", "")).strip()
                or "115 重命名失败"
            )
            raise RuntimeError(detail)
        invalidate_115_entries_cache(parent_cid)
        mark_cookie_health_success("115", trigger="runtime:rename_115_entry")
        return {"id": normalized_id, "name": normalized_name, "response": response}
    except Exception as exc:
        mark_cookie_health_failure("115", exc, trigger="runtime:rename_115_entry")
        raise


def move_115_entries(cookie: str, entry_ids: List[str], target_cid: str, source_cid: str = "") -> Dict[str, Any]:
    normalized_cookie = str(cookie or "").strip()
    if not normalized_cookie:
        raise RuntimeError("115 Cookie 未配置")
    ids = [str(item or "").strip() for item in (entry_ids or []) if str(item or "").strip()]
    if not ids:
        raise RuntimeError("请选择要移动的文件")
    target_id = str(target_cid or "0").strip() or "0"
    try:
        headers = {
            "Cookie": normalized_cookie,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://115.com/",
            "Origin": "https://115.com",
            "User-Agent": "Mozilla/5.0 115-media-hub",
        }
        payload = {"pid": target_id}
        payload.update(_build_115_indexed_fid_payload(ids))
        response = http_request_form_json(
            "https://webapi.115.com/files/move",
            payload,
            timeout=60,
            extra_headers=headers,
        )
        success = bool((response or {}).get("state")) or int((response or {}).get("errno", 0) or 0) == 0
        if not success:
            detail = (
                str((response or {}).get("error", "")).strip()
                or str((response or {}).get("msg", "")).strip()
                or str((response or {}).get("message", "")).strip()
                or "115 移动失败"
            )
            raise RuntimeError(detail)
        invalidate_115_entries_cache(source_cid)
        invalidate_115_entries_cache(target_id)
        mark_cookie_health_success("115", trigger="runtime:move_115_entries")
        return {"ids": ids, "target_cid": target_id, "response": response}
    except Exception as exc:
        mark_cookie_health_failure("115", exc, trigger="runtime:move_115_entries")
        raise


def copy_115_entries(cookie: str, entry_ids: List[str], target_cid: str, source_cid: str = "") -> Dict[str, Any]:
    normalized_cookie = str(cookie or "").strip()
    if not normalized_cookie:
        raise RuntimeError("115 Cookie 未配置")
    ids = [str(item or "").strip() for item in (entry_ids or []) if str(item or "").strip()]
    if not ids:
        raise RuntimeError("请选择要复制的文件")
    target_id = str(target_cid or "0").strip() or "0"
    try:
        headers = {
            "Cookie": normalized_cookie,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://115.com/",
            "Origin": "https://115.com",
            "User-Agent": "Mozilla/5.0 115-media-hub",
        }
        payload = {"pid": target_id}
        payload.update(_build_115_indexed_fid_payload(ids))
        response = http_request_form_json(
            "https://webapi.115.com/files/copy",
            payload,
            timeout=60,
            extra_headers=headers,
        )
        success = bool((response or {}).get("state")) or int((response or {}).get("errno", 0) or 0) == 0
        if not success:
            detail = (
                str((response or {}).get("error", "")).strip()
                or str((response or {}).get("msg", "")).strip()
                or str((response or {}).get("message", "")).strip()
                or "115 复制失败"
            )
            raise RuntimeError(detail)
        invalidate_115_entries_cache(target_id)
        mark_cookie_health_success("115", trigger="runtime:copy_115_entries")
        return {"ids": ids, "target_cid": target_id, "response": response}
    except Exception as exc:
        mark_cookie_health_failure("115", exc, trigger="runtime:copy_115_entries")
        raise


def _is_115_mutation_success(response: Dict[str, Any]) -> bool:
    payload = response if isinstance(response, dict) else {}
    if bool(payload.get("state")) or bool(payload.get("success")):
        return True
    errno_value = None
    for key in ("errno", "errNo", "err_no", "errcode"):
        raw_value = payload.get(key)
        if raw_value is None:
            continue
        text = str(raw_value).strip()
        if not text:
            continue
        try:
            errno_value = int(float(text))
            break
        except Exception:
            continue
    return errno_value == 0


def _request_115_delete_payload(
    cookie: str,
    ids: List[str],
    *,
    parent_cid: str = "",
    use_app_endpoint: bool = False,
) -> Dict[str, Any]:
    headers = {
        "Cookie": cookie,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://115.com/",
        "Origin": "https://115.com",
        "User-Agent": "Mozilla/5.0 115-media-hub",
    }
    if use_app_endpoint:
        payload = {"file_ids": ",".join(ids), "user_id": ""}
        if parent_cid:
            payload["pid"] = parent_cid
        return http_request_form_json(
            "https://proapi.115.com/android/rb/delete",
            payload,
            timeout=60,
            extra_headers=headers,
        )
    payload = _build_115_indexed_fid_payload(ids)
    payload["ignore_warn"] = "1"
    if parent_cid:
        payload["pid"] = parent_cid
    return http_request_form_json(
        "https://webapi.115.com/rb/delete",
        payload,
        timeout=60,
        extra_headers=headers,
    )


def delete_115_entries(cookie: str, entry_ids: List[str], parent_cid: str = "") -> Dict[str, Any]:
    normalized_cookie = str(cookie or "").strip()
    if not normalized_cookie:
        raise RuntimeError("115 Cookie 未配置")
    ids = [str(item or "").strip() for item in (entry_ids or []) if str(item or "").strip()]
    if not ids:
        raise RuntimeError("请选择要删除的文件")
    try:
        responses = []
        last_error = ""
        last_exc = None
        for use_app_endpoint in (False, True):
            try:
                response = _request_115_delete_payload(
                    normalized_cookie,
                    ids,
                    parent_cid=parent_cid,
                    use_app_endpoint=use_app_endpoint,
                )
            except Exception as exc:
                last_exc = exc
                last_error = str(exc).strip() or "115 删除失败"
                continue
            responses.append(response)
            if _is_115_mutation_success(response):
                invalidate_115_entries_cache(parent_cid)
                mark_cookie_health_success("115", trigger="runtime:delete_115_entries")
                return {"ids": ids, "response": response}
            last_error = (
                str((response or {}).get("error", "")).strip()
                or str((response or {}).get("msg", "")).strip()
                or str((response or {}).get("message", "")).strip()
                or str((response or {}).get("err_msg", "")).strip()
                or "115 删除失败"
            )
        detail = last_error or "115 删除失败"
        if len(responses) > 1:
            detail = f"{detail}（webapi/proapi 均未成功）"
        raise RuntimeError(detail) from last_exc
    except Exception as exc:
        mark_cookie_health_failure("115", exc, trigger="runtime:delete_115_entries")
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
        entries = list_115_entries(cookie, current_cid, folders_only=True)
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
        entries = list_115_entries(cookie, current_cid, folders_only=True)
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

def resolve_115_entry_by_name(cookie: str, parent_cid: str, entry_name: str) -> Dict[str, Any]:
    """按名称在 115 目录中查找文件或文件夹（自动分页，最多 80 页）。

    返回与 ``list_115_entries`` 一致的规范化条目；未找到时返回空字典。
    供按路径操作（刮削 rename/move/copy/delete 等）复用，避免大目录漏匹配。
    """
    target_name = str(entry_name or "").strip()
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
        "User-Agent": "Mozilla/5.0 115-media-hub",
    }

    def matches(entry: Dict[str, Any]) -> bool:
        return bool(entry) and str(entry.get("name", "") or "").strip() == target_name

    first_page_loaded = False
    try:
        first_page = list_115_entries(cookie, normalized_cid)
        first_page_loaded = True
    except Exception:
        first_page = []
    for entry in first_page:
        if matches(entry):
            return dict(entry)
    offset = max(len(first_page), page_size) if first_page_loaded else 0

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
            raw = raw_item if isinstance(raw_item, dict) else {}
            entry = _normalize_115_file_entry(raw)
            if matches(entry):
                return entry
        if len(raw_items) < page_size:
            break
        offset += len(raw_items)
    return {}

def list_115_folders(cookie: str, cid: str = "0") -> List[Dict[str, str]]:
    return [
        {"id": str(entry.get("id", "")).strip(), "name": str(entry.get("name", "")).strip()}
        for entry in list_115_entries(cookie, cid, folders_only=True)
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
    if isinstance(exc, requests.HTTPError):
        response = getattr(exc, "response", None)
        status_code = int(getattr(response, "status_code", 0) or 0)
        return status_code in (405, 408, 409, 425, 429, 500, 502, 503, 504)
    if isinstance(exc, requests.RequestException):
        return True
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
        "elapsed_ms": int(payload.get("elapsed_ms", 0) or 0),
        "timings": payload.get("timings", []) if isinstance(payload.get("timings"), list) else [],
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
        started_mono = time.monotonic()
        last_mono = started_mono
        timings: List[Dict[str, Any]] = []
        parsed = resolve_115_share_payload(cookie, share_url, raw_text, receive_code)
        elapsed_ms, last_mono = _build_115_timing_mark(last_mono)
        timings.append({"stage": "parse", "label": "链接", "ms": elapsed_ms})
        share_code = str(parsed.get("share_code", "") or "").strip()
        receive_code = str(parsed.get("receive_code", "") or "").strip()
        current_cid = str(cid or "0").strip() or "0"
        start_offset = max(0, int(offset or 0))
        page_limit = max(20, min(400, int(limit or 200)))
        max_pages_limit = max(0, int(max_pages or 0))
        folder_only_mode = bool(folders_only)
        use_full_cache = start_offset == 0 and max_pages_limit <= 0 and not folder_only_mode

        def load_stale_cache_payload() -> Dict[str, Any]:
            if use_full_cache:
                stale_full_cache = load_115_share_snap_cache(share_code, receive_code, current_cid, allow_expired=True)
                if stale_full_cache:
                    return dict(stale_full_cache)
            stale_page_cache = load_115_share_page_cache(
                share_code,
                receive_code,
                current_cid,
                start_offset,
                page_limit,
                folder_only_mode,
                allow_expired=True,
            )
            if stale_page_cache:
                return dict(stale_page_cache)
            stale_full_cache = load_115_share_snap_cache(share_code, receive_code, current_cid, allow_expired=True)
            if stale_full_cache:
                return _slice_115_share_cache_payload(
                    stale_full_cache,
                    offset=start_offset,
                    limit=page_limit,
                    folders_only=folder_only_mode,
                )
            return {}

        if not force_refresh:
            if use_full_cache:
                fresh_full_cache = load_115_share_snap_cache(share_code, receive_code, current_cid, allow_expired=False)
                if fresh_full_cache:
                    return fresh_full_cache
            else:
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
                fresh_full_cache = load_115_share_snap_cache(share_code, receive_code, current_cid, allow_expired=False)
                if fresh_full_cache:
                    sliced_payload = _slice_115_share_cache_payload(
                        fresh_full_cache,
                        offset=start_offset,
                        limit=page_limit,
                        folders_only=folder_only_mode,
                    )
                    if sliced_payload:
                        return sliced_payload

        request_timeout_value = max(5, int(request_timeout or 45))
        retry_total = max(0, int(max_request_retries or 0))

        headers = _build_115_webapi_headers(cookie)
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
                    request_started_mono = time.monotonic()
                    _throttle_115_share_snap_requests(rate_limit_seconds=rate_limit_seconds)
                    result = _request_115_webapi_json(
                        f"https://webapi.115.com/share/snap?{query}",
                        headers=headers,
                        timeout=request_timeout_value,
                    )
                    elapsed_ms = int((time.monotonic() - request_started_mono) * 1000)
                    last_mono = time.monotonic()
                    timings.append({"stage": f"snap_page_{pages_scanned + 1}", "label": f"目录P{pages_scanned + 1}", "ms": elapsed_ms})
                    last_request_error = None
                    break
                except Exception as exc:
                    last_request_error = exc
                    if (not _is_retryable_115_share_snap_error(exc)) or attempt >= retry_total:
                        break
                    time.sleep(0.6 * (attempt + 1))
            if last_request_error is not None:
                stale_payload = load_stale_cache_payload()
                if stale_payload:
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
                stale_payload = load_stale_cache_payload()
                if stale_payload:
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
                    "elapsed_ms": int((time.monotonic() - started_mono) * 1000),
                    "timings": timings,
                }
                _log_115_share_timing(share_code, current_cid, timings, int(result_payload.get("elapsed_ms", 0) or 0))
                if use_full_cache or (start_offset == 0 and reached_end and not folder_only_mode):
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
                return result_payload
            offset_cursor = next_offset
    except Exception:
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
        return {
            "response": response,
            "selection": prepared.get("selection", {}),
            "duplicate_receive": is_115_share_receive_duplicate_response(response),
        }
    except Exception:
        raise


class Pan115Provider(CloudProvider):
    name = "115"
    label = "115网盘"
    link_type = "115share"
    auth_type = "cookie"
    config_keys = ["cookie_115"]
    supports_subscription = True
    supports_offline = True
    supports_fixed_share_link = True
    supports_strm = True
    supports_monitor = True
    supports_rename = True
    supports_move = True
    supports_copy = True
    supports_delete = True
    rate_limit_seconds = 0.35

    def list_entries_payload(self, cookie, cid="0", folders_only=False):
        return list_115_entries_payload(cookie, cid, False, folders_only)

    def list_entries(self, cookie, cid="0"):
        return list_115_entries(cookie, cid)

    def create_folder(self, cookie, cid="0", folder_name=""):
        return create_115_folder(cookie, cid, folder_name)

    def resolve_folder_id_by_path(self, cookie, relative_path):
        return resolve_115_folder_id_by_path(cookie, relative_path)

    def ensure_folder_id_by_path(self, cookie, relative_path):
        return ensure_115_folder_id_by_path(cookie, relative_path)

    def resolve_share_payload(self, cookie, share_url, raw_text="", receive_code=""):
        payload = resolve_115_share_payload(cookie, share_url, raw_text, receive_code)
        payload["raw_text"] = str(raw_text or "")
        return payload

    def list_share_entries(self, cookie, share_payload, cid="0", offset=0, limit=200):
        payload = share_payload if isinstance(share_payload, dict) else {}
        return list_115_share_entries(
            cookie,
            str(payload.get("url", "") or payload.get("share_url", "") or "").strip(),
            str(payload.get("raw_text", "") or ""),
            cid,
            str(payload.get("receive_code", "") or "").strip(),
            False,
            45,
            0,
            1,
            max(0, int(offset or 0)),
            max(20, min(int(limit or 200), 400)),
            1,
            False,
        )

    def prepare_share_receive(self, cookie, share_payload, cid="0"):
        payload = share_payload if isinstance(share_payload, dict) else {}
        selected_ids = payload.get("selected_ids", []) if isinstance(payload.get("selected_ids"), list) else []
        prepared = prepare_115_share_receive(
            cookie,
            str(payload.get("url", "") or payload.get("share_url", "") or "").strip(),
            str(payload.get("raw_text", "") or ""),
            selected_ids,
            str(payload.get("receive_code", "") or "").strip(),
        )
        return {**payload, **prepared, "target_cid": str(cid or "0").strip() or "0"}

    def submit_share_receive(self, cookie, receive_payload, files):
        payload = receive_payload if isinstance(receive_payload, dict) else {}
        selected_ids = payload.get("selected_ids", []) if isinstance(payload.get("selected_ids"), list) else []
        if not selected_ids:
            selected_ids = [
                str(item.get("id", "")).strip()
                for item in (files or [])
                if isinstance(item, dict) and str(item.get("id", "")).strip()
            ]
        return submit_115_share_receive(
            cookie,
            str(payload.get("url", "") or payload.get("share_url", "") or "").strip(),
            str(payload.get("target_cid", "") or payload.get("folder_id", "") or "0").strip() or "0",
            str(payload.get("raw_text", "") or ""),
            selected_ids,
            str(payload.get("receive_code", "") or "").strip(),
        )

    def submit_offline_task(self, cookie, resource_url, folder_id="0"):
        return submit_115_offline_task(cookie, resource_url, folder_id)

    def query_offline_tasks(self, cookie, page=1):
        return list_115_offline_tasks(cookie, page)

    def probe_connectivity(self, cookie):
        try:
            list_115_entries_payload(cookie, "0", folders_only=True)
            return True
        except Exception:
            return False

    def resolve_download_url(self, cookie, file_id):
        raise NotImplementedError  # STRM 后续实现

    def rename_entry(self, cookie, entry_id, new_name, parent_id=""):
        return rename_115_entry(cookie, entry_id, new_name, parent_id)

    def move_entries(self, cookie, entry_ids, target_id, source_id=""):
        return move_115_entries(cookie, entry_ids, target_id, source_id)

    def copy_entries(self, cookie, entry_ids, target_id, source_id=""):
        return copy_115_entries(cookie, entry_ids, target_id, source_id)

    def delete_entries(self, cookie, entry_ids, parent_id=""):
        return delete_115_entries(cookie, entry_ids, parent_id)


register(Pan115Provider())
