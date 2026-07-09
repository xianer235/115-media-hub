import asyncio
import os
from typing import Any, Dict, List

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..background import submit_background
from ..core import (
    get_config,
    _get_provider_or_none,
    http_request_json,
    normalize_relative_path,
    parse_int,
    throttle_115_api_requests,
)
from ..services.scraper import (
    build_scraper_providers_payload,
    build_scraper_rename_plan,
    check_scraper_folder_rename_warning,
    clear_scraper_jobs,
    copy_scraper_entries,
    create_scraper_folder,
    create_scraper_job_from_plan,
    delete_scraper_entries,
    get_scraper_jobs_state,
    identify_scraper_media,
    list_scraper_entries,
    move_scraper_entries,
    rename_scraper_entry,
    rollback_scraper_job,
    run_scraper_job,
)

router = APIRouter()


def _error_response(exc: Exception, status_code: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"ok": False, "msg": str(exc)})


def _resolve_path_to_entry_ids(provider: str, path: str) -> List[str]:
    """Resolve a human-readable path to entry_ids for 115 operations.

    Traverses the 115 directory tree to find the file/directory matching
    the given path, and returns a list containing its entry_id (fid or cid).
    """
    normalized_path = normalize_relative_path(path)
    if not normalized_path:
        raise RuntimeError("路径无效")
    cfg = get_config()
    cookie = str(cfg.get("cookie_115", "")).strip()
    if not cookie:
        raise RuntimeError("115 Cookie 未配置")
    provider_obj = _get_provider_or_none(provider or "115")
    if not provider_obj:
        raise RuntimeError(f"提供商 {provider} 不存在")

    parent_rel = normalize_relative_path(os.path.dirname(normalized_path))
    file_name = str(os.path.basename(normalized_path) or "").strip()
    if not file_name:
        raise RuntimeError("路径必须包含文件名或目录名")

    # Resolve parent CID by traversing path components
    parent_cid = "0"
    if parent_rel:
        parts = [p for p in parent_rel.split("/") if p]
        for part in parts:
            throttle_115_api_requests()
            url = (
                "https://aps.115.com/natsort/files.php"
                f"?aid=1&cid={parent_cid}&offset=0&limit=300&show_dir=1&natsort=1&format=json"
            )
            headers = {"Cookie": cookie, "Accept": "application/json", "Referer": "https://115.com/"}
            result = http_request_json(url, extra_headers=headers, timeout=30)
            if not isinstance(result, dict) or not result.get("state"):
                raise RuntimeError(f"目录 {part} 不存在或无权限访问")
            raw_items = result.get("data") or []
            found = False
            for raw in raw_items:
                name = str(raw.get("n", "") or raw.get("name", "") or "").strip()
                cid = str(raw.get("cid", "") or "").strip()
                if name == part and cid:
                    parent_cid = cid
                    found = True
                    break
            if not found:
                raise RuntimeError(f"未找到子目录: {part}")

    # Find the target file/directory in parent
    throttle_115_api_requests()
    url = (
        "https://aps.115.com/natsort/files.php"
        f"?aid=1&cid={parent_cid}&offset=0&limit=300&show_dir=1&natsort=1&format=json"
    )
    headers = {"Cookie": cookie, "Accept": "application/json", "Referer": "https://115.com/"}
    result = http_request_json(url, extra_headers=headers, timeout=30)
    if not isinstance(result, dict) or not result.get("state"):
        raise RuntimeError("无法读取目录内容")
    raw_items = result.get("data") or []
    entry_id = ""
    for raw in raw_items:
        name = str(raw.get("n", "") or raw.get("name", "") or "").strip()
        if name == file_name:
            fid = str(raw.get("fid", "") or raw.get("id", "") or "").strip()
            cid = str(raw.get("cid", "") or "").strip()
            if fid:
                entry_id = fid
            elif cid:
                entry_id = cid
            break
    if not entry_id:
        raise RuntimeError(f"未找到文件/目录: {normalized_path}")
    return [entry_id]


@router.get("/scraper/providers")
async def get_scraper_providers_endpoint() -> Dict[str, Any]:
    try:
        return await asyncio.to_thread(build_scraper_providers_payload)
    except Exception as exc:
        return _error_response(exc)


@router.get("/scraper/{provider}/entries")
async def get_scraper_entries_endpoint(provider: str, request: Request) -> Dict[str, Any]:
    cid = str(request.query_params.get("cid", "0") or "0").strip() or "0"
    force_refresh = request.query_params.get("force_refresh") == "1"
    keyword = str(request.query_params.get("q", "") or "").strip()
    try:
        return await asyncio.to_thread(list_scraper_entries, provider, cid, force_refresh, keyword)
    except Exception as exc:
        return _error_response(exc)


@router.post("/scraper/{provider}/folders")
async def create_scraper_folder_endpoint(provider: str, request: Request) -> Dict[str, Any]:
    data = await request.json()
    cid = str(data.get("cid", "0") or "0").strip() or "0"
    name = str(data.get("name", "") or "").strip()
    if not name:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "文件夹名称不能为空"})
    try:
        return await asyncio.to_thread(create_scraper_folder, provider, cid, name)
    except Exception as exc:
        return _error_response(exc)


@router.post("/scraper/{provider}/rename")
async def rename_scraper_entry_endpoint(provider: str, request: Request) -> Dict[str, Any]:
    data = await request.json()
    entry_id = str(data.get("entry_id", "") or "").strip()
    parent_id = str(data.get("parent_id", "") or "").strip()
    name = str(data.get("name", "") or "").strip()
    # Support path-based input for CLI
    path = str(data.get("path", "") or "").strip()
    if not entry_id:
        if path:
            try:
                entry_ids = await asyncio.to_thread(_resolve_path_to_entry_ids, provider, path)
                if entry_ids:
                    entry_id = entry_ids[0]
            except Exception as exc:
                return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})
        else:
            return JSONResponse(status_code=400, content={"ok": False, "msg": "文件 ID 或路径不能为空"})
    if not name:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "新名称不能为空"})
    try:
        return await asyncio.to_thread(rename_scraper_entry, provider, entry_id, parent_id, name)
    except Exception as exc:
        return _error_response(exc)


@router.post("/scraper/{provider}/rename-warning")
async def check_scraper_folder_rename_warning_endpoint(provider: str, request: Request) -> Dict[str, Any]:
    data = await request.json()
    old_path = str(data.get("old_path", "") or "").strip()
    new_path = str(data.get("new_path", "") or "").strip()
    if not old_path or not new_path:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "文件夹路径无效"})
    try:
        return await asyncio.to_thread(check_scraper_folder_rename_warning, provider, old_path, new_path)
    except Exception as exc:
        return _error_response(exc)


@router.post("/scraper/{provider}/move")
async def move_scraper_entries_endpoint(provider: str, request: Request) -> Dict[str, Any]:
    data = await request.json()
    entry_ids = data.get("entry_ids", [])
    # Support path-based input for CLI
    path = str(data.get("path", "") or "").strip()
    if not isinstance(entry_ids, list) or not entry_ids:
        if path:
            try:
                entry_ids = await asyncio.to_thread(_resolve_path_to_entry_ids, provider, path)
            except Exception as exc:
                return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})
        else:
            return JSONResponse(status_code=400, content={"ok": False, "msg": "请选择要移动的条目"})
    target_cid = str(data.get("target_cid", "") or "").strip()
    dest = str(data.get("dest", "") or "").strip()
    if not target_cid and dest:
        # Resolve destination path to CID
        try:
            dest_ids = await asyncio.to_thread(_resolve_path_to_entry_ids, provider, dest)
            if dest_ids:
                target_cid = dest_ids[0]
        except Exception:
            pass
    if not target_cid:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "目标目录不能为空"})
    source_cid = str(data.get("source_cid", "") or "").strip()
    try:
        return await asyncio.to_thread(move_scraper_entries, provider, entry_ids, target_cid, source_cid)
    except Exception as exc:
        return _error_response(exc)


@router.post("/scraper/{provider}/copy")
async def copy_scraper_entries_endpoint(provider: str, request: Request) -> Dict[str, Any]:
    data = await request.json()
    entry_ids = data.get("entry_ids", [])
    # Support path-based input for CLI
    path = str(data.get("path", "") or "").strip()
    if not isinstance(entry_ids, list) or not entry_ids:
        if path:
            try:
                entry_ids = await asyncio.to_thread(_resolve_path_to_entry_ids, provider, path)
            except Exception as exc:
                return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})
        else:
            return JSONResponse(status_code=400, content={"ok": False, "msg": "请选择要复制的条目"})
    target_cid = str(data.get("target_cid", "") or "").strip()
    dest = str(data.get("dest", "") or "").strip()
    if not target_cid and dest:
        try:
            dest_ids = await asyncio.to_thread(_resolve_path_to_entry_ids, provider, dest)
            if dest_ids:
                target_cid = dest_ids[0]
        except Exception:
            pass
    if not target_cid:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "目标目录不能为空"})
    source_cid = str(data.get("source_cid", "") or "").strip()
    try:
        return await asyncio.to_thread(copy_scraper_entries, provider, entry_ids, target_cid, source_cid)
    except Exception as exc:
        return _error_response(exc)


@router.post("/scraper/{provider}/delete")
async def delete_scraper_entries_endpoint(provider: str, request: Request) -> Dict[str, Any]:
    data = await request.json()
    entry_ids = data.get("entry_ids", [])
    # Support path-based input for CLI
    path = str(data.get("path", "") or "").strip()
    if not isinstance(entry_ids, list) or not entry_ids:
        if path:
            try:
                entry_ids = await asyncio.to_thread(_resolve_path_to_entry_ids, provider, path)
            except Exception as exc:
                return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})
        else:
            return JSONResponse(status_code=400, content={"ok": False, "msg": "请选择要删除的条目"})
    parent_id = str(data.get("parent_id", "") or "").strip()
    try:
        return await asyncio.to_thread(delete_scraper_entries, provider, entry_ids, parent_id)
    except Exception as exc:
        return _error_response(exc)


@router.post("/scraper/identify")
async def identify_scraper_endpoint(request: Request) -> Dict[str, Any]:
    data = await request.json()
    payload = data if isinstance(data, dict) else {}
    try:
        return await asyncio.to_thread(identify_scraper_media, payload)
    except Exception as exc:
        return _error_response(exc)


@router.post("/scraper/rename-plan")
async def build_scraper_rename_plan_endpoint(request: Request) -> Dict[str, Any]:
    data = await request.json()
    payload = data if isinstance(data, dict) else {}
    try:
        return await asyncio.to_thread(build_scraper_rename_plan, payload)
    except Exception as exc:
        return _error_response(exc)


@router.post("/scraper/jobs/create")
async def create_scraper_job_endpoint(request: Request) -> Dict[str, Any]:
    data = await request.json()
    payload = data if isinstance(data, dict) else {}
    try:
        result = await asyncio.to_thread(create_scraper_job_from_plan, payload)
        job_id = int(result.get("job_id", 0) or 0)
        submit_background(run_scraper_job, job_id, label="scraper-job")
        return result
    except Exception as exc:
        return _error_response(exc)


@router.get("/scraper/jobs/state")
async def get_scraper_jobs_state_endpoint(request: Request) -> Dict[str, Any]:
    limit = max(1, min(parse_int(request.query_params.get("limit", 20), default=20), 100))
    job_id = max(0, parse_int(request.query_params.get("job_id", 0), default=0))
    try:
        return await asyncio.to_thread(get_scraper_jobs_state, limit, job_id)
    except Exception as exc:
        return _error_response(exc)


@router.post("/scraper/jobs/clear")
async def clear_scraper_jobs_endpoint(request: Request) -> Dict[str, Any]:
    data = await request.json()
    scope = str((data or {}).get("scope", "completed") or "completed").strip().lower()
    if scope not in ("completed", "failed", "rollback"):
        return JSONResponse(status_code=400, content={"ok": False, "msg": "清理范围不支持"})
    try:
        result = await asyncio.to_thread(clear_scraper_jobs, scope)
        return {"ok": True, **result}
    except Exception as exc:
        return _error_response(exc)


@router.post("/scraper/jobs/{job_id}/rollback")
async def rollback_scraper_job_endpoint(job_id: int) -> Dict[str, Any]:
    normalized_job_id = max(0, int(job_id or 0))
    if normalized_job_id <= 0:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "任务 ID 无效"})
    try:
        submit_background(rollback_scraper_job, normalized_job_id, label="scraper-rollback")
        return {"ok": True, "job_id": normalized_job_id}
    except Exception as exc:
        return _error_response(exc)