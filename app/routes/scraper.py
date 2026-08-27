import asyncio
from typing import Any, Dict

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..core import normalize_relative_path, parse_int
from ..services.scraper import (
    build_scraper_batch_plan,
    build_scraper_providers_payload,
    build_scraper_rename_plan,
    check_scraper_folder_rename_warning,
    clear_scraper_jobs,
    copy_scraper_entries,
    create_scraper_folder,
    create_scraper_job_from_plan,
    delete_scraper_entries,
    get_scraper_batch_preferences,
    get_scraper_jobs_state,
    identify_scraper_batch_items,
    identify_scraper_media,
    list_scraper_entries,
    move_scraper_entries,
    rename_scraper_entry,
    save_scraper_batch_preferences,
    scan_scraper_batch_items,
    submit_scraper_job,
    submit_scraper_rollback,
    resolve_scraper_dest_folder_id,
    resolve_scraper_folder_path,
    resolve_scraper_path_entry,
)

router = APIRouter()


def _error_response(exc: Exception, status_code: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"ok": False, "msg": str(exc)})


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
    offset = max(0, parse_int(request.query_params.get("offset", 0), default=0))
    limit = max(20, min(parse_int(request.query_params.get("limit", 0), default=0), 1000))
    try:
        return await asyncio.to_thread(list_scraper_entries, provider, cid, force_refresh, keyword, offset, limit)
    except Exception as exc:
        return _error_response(exc)


@router.get("/scraper/{provider}/folder-path")
async def get_scraper_folder_path_endpoint(provider: str, request: Request) -> Dict[str, Any]:
    cid = str(request.query_params.get("cid", "0") or "0").strip() or "0"
    try:
        return await asyncio.to_thread(resolve_scraper_folder_path, provider, cid)
    except Exception as exc:
        return _error_response(exc)


@router.post("/scraper/{provider}/folders")
async def create_scraper_folder_endpoint(provider: str, request: Request) -> Dict[str, Any]:
    data = await request.json()
    cid = str(data.get("cid", "0") or "0").strip() or "0"
    name = str(data.get("name", "") or "").strip()
    parent_path = data.get("parent_path") if "parent_path" in data else None
    request_id = str(data.get("request_id", "") or "").strip()
    if not name:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "文件夹名称不能为空"})
    try:
        return await asyncio.to_thread(create_scraper_folder, provider, cid, name, parent_path, request_id)
    except Exception as exc:
        return _error_response(exc)


@router.post("/scraper/{provider}/rename")
async def rename_scraper_entry_endpoint(provider: str, request: Request) -> Dict[str, Any]:
    data = await request.json()
    entry_id = str(data.get("entry_id", "") or "").strip()
    parent_id = str(data.get("parent_id", "") or "").strip()
    name = str(data.get("name", "") or "").strip()
    entry = data.get("entry") if isinstance(data.get("entry"), dict) else None
    request_id = str(data.get("request_id", "") or "").strip()
    if not entry_id:
        path = str(data.get("path", "") or "").strip()
        if not path:
            return JSONResponse(status_code=400, content={"ok": False, "msg": "文件 ID 或路径不能为空"})
        try:
            resolved_entry = await asyncio.to_thread(resolve_scraper_path_entry, provider, path)
        except Exception as exc:
            return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})
        if not resolved_entry:
            return JSONResponse(status_code=400, content={"ok": False, "msg": f"未找到文件/目录: {path}"})
        entry_id = str(resolved_entry.get("id", "") or "").strip()
        parent_id = str(resolved_entry.get("parent_id", "") or parent_id).strip()
        entry = resolved_entry
    if not name:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "新名称不能为空"})
    try:
        return await asyncio.to_thread(rename_scraper_entry, provider, entry_id, parent_id, name, entry, request_id)
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
    target_cid = str(data.get("target_cid", "") or "").strip()
    source_cid = str(data.get("source_cid", "") or "").strip()
    entries = data.get("entries") if isinstance(data.get("entries"), list) else None
    target_parent_path = data.get("target_parent_path") if "target_parent_path" in data else None
    request_id = str(data.get("request_id", "") or "").strip()
    if not isinstance(entry_ids, list) or not entry_ids:
        path = str(data.get("path", "") or "").strip()
        if not path:
            return JSONResponse(status_code=400, content={"ok": False, "msg": "请选择要移动的条目"})
        try:
            resolved_entry = await asyncio.to_thread(resolve_scraper_path_entry, provider, path)
        except Exception as exc:
            return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})
        if not resolved_entry:
            return JSONResponse(status_code=400, content={"ok": False, "msg": f"未找到文件/目录: {path}"})
        entry_ids = [str(resolved_entry.get("id", "") or "").strip()]
        entries = [resolved_entry]
        if not source_cid:
            source_cid = str(resolved_entry.get("parent_id", "") or "").strip()
    dest = str(data.get("dest", "") or "").strip()
    if not target_cid and dest:
        try:
            target_cid = await asyncio.to_thread(resolve_scraper_dest_folder_id, provider, dest)
        except Exception as exc:
            return JSONResponse(status_code=400, content={"ok": False, "msg": f"目标路径解析失败: {exc}"})
        target_parent_path = normalize_relative_path(dest)
    if not target_cid:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "目标目录不能为空"})
    try:
        return await asyncio.to_thread(
            move_scraper_entries,
            provider,
            entry_ids,
            target_cid,
            source_cid,
            entries,
            target_parent_path,
            request_id,
        )
    except Exception as exc:
        return _error_response(exc)


@router.post("/scraper/{provider}/copy")
async def copy_scraper_entries_endpoint(provider: str, request: Request) -> Dict[str, Any]:
    data = await request.json()
    entry_ids = data.get("entry_ids", [])
    target_cid = str(data.get("target_cid", "") or "").strip()
    source_cid = str(data.get("source_cid", "") or "").strip()
    entries = data.get("entries") if isinstance(data.get("entries"), list) else None
    target_parent_path = data.get("target_parent_path") if "target_parent_path" in data else None
    request_id = str(data.get("request_id", "") or "").strip()
    if not isinstance(entry_ids, list) or not entry_ids:
        path = str(data.get("path", "") or "").strip()
        if not path:
            return JSONResponse(status_code=400, content={"ok": False, "msg": "请选择要复制的条目"})
        try:
            resolved_entry = await asyncio.to_thread(resolve_scraper_path_entry, provider, path)
        except Exception as exc:
            return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})
        if not resolved_entry:
            return JSONResponse(status_code=400, content={"ok": False, "msg": f"未找到文件/目录: {path}"})
        entry_ids = [str(resolved_entry.get("id", "") or "").strip()]
        entries = [resolved_entry]
        if not source_cid:
            source_cid = str(resolved_entry.get("parent_id", "") or "").strip()
    dest = str(data.get("dest", "") or "").strip()
    if not target_cid and dest:
        try:
            target_cid = await asyncio.to_thread(resolve_scraper_dest_folder_id, provider, dest)
        except Exception as exc:
            return JSONResponse(status_code=400, content={"ok": False, "msg": f"目标路径解析失败: {exc}"})
        target_parent_path = normalize_relative_path(dest)
    if not target_cid:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "目标目录不能为空"})
    try:
        return await asyncio.to_thread(
            copy_scraper_entries,
            provider,
            entry_ids,
            target_cid,
            source_cid,
            entries,
            target_parent_path,
            request_id,
        )
    except Exception as exc:
        return _error_response(exc)


@router.post("/scraper/{provider}/delete")
async def delete_scraper_entries_endpoint(provider: str, request: Request) -> Dict[str, Any]:
    data = await request.json()
    entry_ids = data.get("entry_ids", [])
    parent_id = str(data.get("parent_id", "") or "").strip()
    entries = data.get("entries") if isinstance(data.get("entries"), list) else None
    request_id = str(data.get("request_id", "") or "").strip()
    if not isinstance(entry_ids, list) or not entry_ids:
        path = str(data.get("path", "") or "").strip()
        if not path:
            return JSONResponse(status_code=400, content={"ok": False, "msg": "请选择要删除的条目"})
        try:
            resolved_entry = await asyncio.to_thread(resolve_scraper_path_entry, provider, path)
        except Exception as exc:
            return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})
        if not resolved_entry:
            return JSONResponse(status_code=400, content={"ok": False, "msg": f"未找到文件/目录: {path}"})
        entry_ids = [str(resolved_entry.get("id", "") or "").strip()]
        entries = [resolved_entry]
        if not parent_id:
            parent_id = str(resolved_entry.get("parent_id", "") or "").strip()
    try:
        return await asyncio.to_thread(delete_scraper_entries, provider, entry_ids, parent_id, entries, request_id)
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


@router.post("/scraper/batch/scan")
async def scan_scraper_batch_endpoint(request: Request) -> Dict[str, Any]:
    data = await request.json()
    payload = data if isinstance(data, dict) else {}
    provider = str(payload.get("provider", "115") or "115").strip()
    cid = str(payload.get("cid", "0") or "0").strip() or "0"
    base_path = str(payload.get("base_path", "") or "").strip()
    selected = payload.get("selected") if isinstance(payload.get("selected"), list) else None
    split_folders = bool(payload.get("split_folders", False))
    split_mode = str(payload.get("split_mode", "auto") or "auto").strip()
    try:
        return await asyncio.to_thread(
            scan_scraper_batch_items,
            provider,
            cid,
            base_path,
            selected,
            split_folders,
            split_mode,
        )
    except Exception as exc:
        return _error_response(exc)


@router.post("/scraper/batch/identify")
async def identify_scraper_batch_endpoint(request: Request) -> Dict[str, Any]:
    data = await request.json()
    payload = data if isinstance(data, dict) else {}
    try:
        return await asyncio.to_thread(identify_scraper_batch_items, payload)
    except Exception as exc:
        return _error_response(exc)


@router.get("/scraper/{provider}/batch/preferences")
async def get_scraper_batch_preferences_endpoint(provider: str) -> Dict[str, Any]:
    try:
        return await asyncio.to_thread(get_scraper_batch_preferences, provider)
    except Exception as exc:
        return _error_response(exc)


@router.post("/scraper/{provider}/batch/preferences")
async def save_scraper_batch_preferences_endpoint(provider: str, request: Request) -> Dict[str, Any]:
    data = await request.json()
    options = data.get("options") if isinstance(data.get("options"), dict) else {}
    try:
        return await asyncio.to_thread(save_scraper_batch_preferences, provider, options)
    except Exception as exc:
        return _error_response(exc)


@router.post("/scraper/batch/plan")
async def build_scraper_batch_plan_endpoint(request: Request) -> Dict[str, Any]:
    data = await request.json()
    payload = data if isinstance(data, dict) else {}
    try:
        return await asyncio.to_thread(build_scraper_batch_plan, payload)
    except Exception as exc:
        return _error_response(exc)


@router.post("/scraper/jobs/create")
async def create_scraper_job_endpoint(request: Request) -> Dict[str, Any]:
    data = await request.json()
    payload = data if isinstance(data, dict) else {}
    try:
        result = await asyncio.to_thread(create_scraper_job_from_plan, payload)
        job_id = int(result.get("job_id", 0) or 0)
        submit_scraper_job(job_id)
        return result
    except Exception as exc:
        return _error_response(exc)


@router.get("/scraper/jobs/state")
async def get_scraper_jobs_state_endpoint(request: Request) -> Dict[str, Any]:
    limit = 10
    page = max(1, parse_int(request.query_params.get("page", 1), default=1))
    status_filter = str(request.query_params.get("status", "all") or "all").strip().lower()
    job_id = max(0, parse_int(request.query_params.get("job_id", 0), default=0))
    try:
        return await asyncio.to_thread(get_scraper_jobs_state, limit, job_id, page, status_filter)
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
        submit_scraper_rollback(normalized_job_id)
        return {"ok": True, "job_id": normalized_job_id}
    except Exception as exc:
        return _error_response(exc)
