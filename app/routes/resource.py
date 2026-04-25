import asyncio
import functools
import os
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from ..core import *  # noqa: F401,F403
from ..services.resource import cancel_resource_job, retry_resource_job, run_resource_job, trigger_resource_job_refresh

router = APIRouter()
resource_job_create_lock = asyncio.Lock()
RESOURCE_SHARE_BROWSE_TIMEOUT_SECONDS = 30
RESOURCE_SHARE_BROWSE_RATE_LIMIT_SECONDS = 0.25
RESOURCE_SHARE_BROWSE_MAX_RETRIES = 1
RESOURCE_BROWSE_WORKERS = max(2, min(8, int(os.environ.get("RESOURCE_BROWSE_WORKERS", 4) or 4)))
resource_browse_executor = ThreadPoolExecutor(
    max_workers=RESOURCE_BROWSE_WORKERS,
    thread_name_prefix="resource-browse",
)


def _compact_resource_browser_entry(entry: Dict[str, Any], *, include_share_fields: bool = False) -> Dict[str, Any]:
    item = entry if isinstance(entry, dict) else {}
    is_dir = bool(item.get("is_dir"))
    payload: Dict[str, Any] = {
        "id": str(item.get("id", "") or "").strip(),
        "name": str(item.get("name", "") or "").strip(),
        "is_dir": is_dir,
    }
    if is_dir:
        cid = str(item.get("cid", "") or item.get("id", "") or "").strip()
        if cid:
            payload["cid"] = cid
    else:
        payload["size"] = parse_int(item.get("size") or 0)
    if include_share_fields:
        payload["parent_id"] = str(item.get("parent_id", "") or "0").strip() or "0"
        cid = str(item.get("cid", "") or "").strip()
        fid = str(item.get("fid", "") or "").strip()
        if cid:
            payload["cid"] = cid
        if fid:
            payload["fid"] = fid
    return payload


def _compact_resource_browser_entries(
    entries: List[Dict[str, Any]],
    *,
    include_share_fields: bool = False,
) -> List[Dict[str, Any]]:
    return [
        compact
        for compact in (
            _compact_resource_browser_entry(entry, include_share_fields=include_share_fields)
            for entry in (entries or [])
        )
        if compact.get("id") and compact.get("name")
    ]


def _build_resource_share_entries_response(
    cid: str,
    result: Dict[str, Any],
    *,
    offset: int,
    paged: bool,
    folders_only: bool,
) -> Dict[str, Any]:
    entries = result.get("entries", []) if isinstance(result, dict) else []
    compact_entries = _compact_resource_browser_entries(entries, include_share_fields=True)
    return {
        "ok": True,
        "cid": cid,
        "entries": compact_entries,
        "summary": (
            result.get("summary", {"folder_count": 0, "file_count": 0})
            if isinstance(result, dict)
            else {"folder_count": 0, "file_count": 0}
        ),
        "share": {
            "title": result.get("share_title", "") if isinstance(result, dict) else "",
            "share_code": result.get("share_code", "") if isinstance(result, dict) else "",
            "receive_code": result.get("receive_code", "") if isinstance(result, dict) else "",
            "count": result.get("count", 0) if isinstance(result, dict) else 0,
        },
        "paging": {
            "offset": result.get("offset", offset) if isinstance(result, dict) else offset,
            "next_offset": (
                result.get("next_offset", offset + len(compact_entries))
                if isinstance(result, dict)
                else offset + len(compact_entries)
            ),
            "has_more": bool(result.get("has_more", False)) if isinstance(result, dict) else False,
            "paged": paged,
            "folders_only": folders_only,
        },
    }


async def run_resource_browse_io(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(resource_browse_executor, functools.partial(func, *args, **kwargs))


def _build_resource_jobs_state_snapshot(limit: int = 20, offset: int = 0, status_filter: str = "") -> Dict[str, Any]:
    cfg = get_config()
    payload = build_resource_jobs_state_payload(limit=limit, cfg=cfg)
    normalized_filter = normalize_resource_job_status_filter(status_filter)
    normalized_offset = max(0, int(offset or 0))
    if normalized_filter != "all" or normalized_offset > 0:
        jobs_page = list_resource_jobs_page(limit=limit, offset=normalized_offset, status_filter=normalized_filter)
        payload["jobs"] = jobs_page.get("jobs", [])
        payload["pagination"] = jobs_page.get("pagination", {})
    return payload


def _import_resource_candidates_to_db(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    ensure_db()
    conn = open_db()
    inserted = 0
    updated = 0
    item_ids: List[int] = []
    for item in candidates:
        item_id, created = upsert_resource_item(conn, item)
        item_ids.append(item_id)
        if created:
            inserted += 1
        else:
            updated += 1
    conn.commit()
    conn.close()
    items = [get_resource_item(item_id) for item_id in item_ids]
    return {"inserted": inserted, "updated": updated, "items": items}


@router.get("/resource/state")
async def get_resource_state(request: Request) -> Dict[str, Any]:
    search = str(request.query_params.get("q", "") or "").strip()
    sync_channels = request.query_params.get("sync") == "1"
    if sync_channels:
        await sync_telegram_channels(force=False, limit_per_channel=10)
    return await build_resource_state_payload(search=search)


@router.get("/resource/jobs/state")
async def get_resource_jobs_state(request: Request) -> Dict[str, Any]:
    limit = max(1, min(int(request.query_params.get("limit", 20) or 20), 200))
    offset = max(0, int(request.query_params.get("offset", 0) or 0))
    status_filter = str(request.query_params.get("status", "all") or "all").strip().lower()
    return await asyncio.to_thread(_build_resource_jobs_state_snapshot, limit, offset, status_filter)


@router.post("/resource/sources/save")
async def save_resource_sources(request: Request) -> Dict[str, Any]:
    data = await request.json()
    cfg = get_config()
    incoming = data.get("sources", [])
    normalized = []
    seen = set()
    for raw_source in incoming if isinstance(incoming, list) else []:
        source = normalize_resource_source(raw_source or {})
        key = "|".join([source.get("channel_id", ""), source.get("url", ""), source.get("name", "")])
        if key in seen:
            continue
        seen.add(key)
        normalized.append(source)
    cfg["resource_sources"] = normalized
    save_config(cfg)
    return {"ok": True, "sources": normalized}


@router.post("/resource/quick_links/save")
async def save_resource_quick_links_endpoint(request: Request) -> Dict[str, Any]:
    data = await request.json()
    normalized = normalize_resource_quick_links(data.get("quick_links", []))
    cfg = get_config()
    cfg["resource_quick_links"] = normalized
    save_config(cfg)
    return {"ok": True, "quick_links": clone_jsonable(normalized)}


@router.post("/resource/channels/sync")
async def sync_resource_channels_endpoint(request: Request) -> Dict[str, Any]:
    data = await request.json()
    force = bool(data.get("force", False))
    limit_per_channel = max(1, min(int(data.get("limit", 10) or 10), 30))
    return await sync_telegram_channels(force=force, limit_per_channel=limit_per_channel)


@router.post("/resource/channels/classify")
async def classify_resource_channel_endpoint(request: Request) -> Dict[str, Any]:
    data = await request.json()
    channel_id = normalize_telegram_channel_id_from_input(data.get("channel_id", "") or "")
    if not channel_id:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "频道 ID 无效"})

    sample_size = max(20, min(int(data.get("sample_size", 20) or 20), 100))
    cfg = get_config()
    source = next(
        (item for item in cfg.get("resource_sources", []) if normalize_telegram_channel_id_from_input(item.get("channel_id", "")) == channel_id),
        None,
    )
    source = normalize_resource_source(source or {"channel_id": channel_id, "name": channel_id, "enabled": True})

    if channel_id in resource_channel_syncing:
        return JSONResponse(status_code=409, content={"ok": False, "msg": "当前频道正在同步，请稍后再试"})

    try:
        resource_channel_syncing.add(channel_id)
        sample = await asyncio.to_thread(
            fetch_telegram_channel_post_samples,
            cfg,
            source,
            sample_size,
            max(20, min(sample_size, 50)),
            RESOURCE_CHANNEL_TYPE_MAX_PAGES,
        )
    except Exception as exc:
        resource_channel_last_error[channel_id] = str(exc)
        return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})
    finally:
        resource_channel_syncing.discard(channel_id)

    posts = sample.get("posts", []) if isinstance(sample, dict) else []
    profile = build_resource_channel_profile(channel_id, posts, sample_size=sample_size)
    resource_channel_profiles[channel_id] = clone_jsonable(profile)
    resource_channel_last_error.pop(channel_id, None)
    return {
        "ok": True,
        "channel_id": channel_id,
        "name": str(source.get("name", "") or channel_id).strip(),
        "profile": profile,
        "pages_scanned": int(sample.get("pages_scanned", 0) or 0) if isinstance(sample, dict) else 0,
        "sample_count": len(posts),
    }


@router.post("/resource/channels/more")
async def load_more_resource_channel_items_endpoint(request: Request) -> Dict[str, Any]:
    data = await request.json()
    channel_id = normalize_telegram_channel_id_from_input(data.get("channel_id", "") or "")
    if not channel_id:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "频道 ID 无效"})

    limit = max(1, min(int(data.get("limit", 10) or 10), 20))
    before = extract_telegram_post_cursor(data.get("before", "") or "")
    query = str(data.get("query", "") or "").strip()
    cfg = get_config()
    source = next(
        (item for item in cfg.get("resource_sources", []) if normalize_telegram_channel_id_from_input(item.get("channel_id", "")) == channel_id),
        None,
    )
    source = normalize_resource_source(source or {"channel_id": channel_id, "name": channel_id, "enabled": True})

    if channel_id in resource_channel_syncing:
        return JSONResponse(status_code=409, content={"ok": False, "msg": "当前频道正在同步，请稍后再试"})

    page: Dict[str, Any] = {}
    try:
        resource_channel_syncing.add(channel_id)
        try:
            if query:
                page = await asyncio.to_thread(
                    search_telegram_channel_resource_items,
                    cfg,
                    source,
                    query,
                    limit,
                    TG_SEARCH_MAX_PAGES,
                    max(limit, TG_SEARCH_PAGE_LIMIT),
                    before,
                )
            else:
                page = await asyncio.to_thread(fetch_telegram_channel_posts_page, cfg, source, limit, before)
        except Exception as exc:
            resource_channel_last_error[channel_id] = str(exc)
            return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})
        resource_channel_last_error.pop(channel_id, None)
    finally:
        resource_channel_syncing.discard(channel_id)
    items = page.get("posts", []) if isinstance(page, dict) else []
    if query and isinstance(page, dict):
        items = page.get("items", []) or []
    import_result = await asyncio.to_thread(_import_resource_candidates_to_db, items) if items else {
        "inserted": 0,
        "updated": 0,
        "items": [],
    }
    response_items = import_result.get("items", []) if isinstance(import_result, dict) else []
    return {
        "ok": True,
        "channel_id": channel_id,
        "query": query,
        "before": before,
        "items": response_items if response_items else items,
        "inserted": int(import_result.get("inserted", 0) or 0),
        "updated": int(import_result.get("updated", 0) or 0),
        "next_before": str(page.get("next_before", "") or "").strip(),
        "has_more": bool(page.get("has_more")),
        "matched_count": int(page.get("matched_count", 0) or len(items)),
        "total_count": count_resource_items(channel_id=channel_id, source_type="tg"),
    }


@router.post("/resource/items/import_text")
async def import_resource_text(request: Request) -> Dict[str, Any]:
    data = await request.json()
    raw_text = str(data.get("raw_text", "") or "").strip()
    if not raw_text:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "请先粘贴 TG 消息或资源文本"})

    source_name = str(data.get("source_name", "") or "").strip()
    source_type = str(data.get("source_type", "") or "manual").strip() or "manual"
    channel_name = str(data.get("channel_name", "") or "").strip()
    published_at = str(data.get("published_at", "") or "").strip()
    message_url = str(data.get("message_url", "") or "").strip()
    candidates = extract_resource_candidates(
        raw_text,
        source_name=source_name,
        source_type=source_type,
        channel_name=channel_name,
        published_at=published_at,
        message_url=message_url,
    )
    if not candidates:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "未识别到可入库内容"})

    result = await asyncio.to_thread(_import_resource_candidates_to_db, candidates)
    return {"ok": True, **result}


@router.post("/resource/items/preview_text")
async def preview_resource_text(request: Request) -> Dict[str, Any]:
    data = await request.json()
    raw_text = str(data.get("raw_text", "") or "").strip()
    if not raw_text:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "请先粘贴 magnet、网盘分享链接或资源文本"})

    source_name = str(data.get("source_name", "") or "").strip()
    source_type = str(data.get("source_type", "") or "manual").strip() or "manual"
    channel_name = str(data.get("channel_name", "") or "").strip()
    published_at = str(data.get("published_at", "") or "").strip()
    message_url = str(data.get("message_url", "") or "").strip()
    candidates = extract_resource_candidates(
        raw_text,
        source_name=source_name,
        source_type=source_type,
        channel_name=channel_name,
        published_at=published_at,
        message_url=message_url,
    )
    if not candidates:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "未识别到可导入内容"})
    return {"ok": True, "items": candidates}


@router.post("/resource/items/delete")
async def delete_resource_item_endpoint(request: Request) -> Dict[str, Any]:
    data = await request.json()
    resource_id = int(data.get("id", 0) or 0)
    if resource_id <= 0:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "资源 ID 无效"})
    resource = await asyncio.to_thread(get_resource_item, resource_id)
    if not resource:
        return JSONResponse(status_code=404, content={"ok": False, "msg": "资源不存在"})
    await asyncio.to_thread(delete_resource_item, resource_id)
    return {"ok": True}


@router.post("/resource/jobs/create")
async def create_resource_job_endpoint(request: Request) -> Dict[str, Any]:
    data = await request.json()
    resource_id = int(data.get("resource_id", 0) or 0)
    if resource_id > 0:
        resource = get_resource_item(resource_id)
        if not resource:
            return JSONResponse(status_code=404, content={"ok": False, "msg": "资源不存在"})
    else:
        raw_resource = data.get("resource", {})
        if not isinstance(raw_resource, dict):
            return JSONResponse(status_code=400, content={"ok": False, "msg": "资源信息无效"})
        resource = sanitize_resource_job_input(raw_resource)
        if not str(resource.get("link_url", "")).strip():
            return JSONResponse(status_code=400, content={"ok": False, "msg": "当前资源没有可导入链接"})
    link_type = resolve_resource_link_type(resource.get("link_type", ""), resource.get("link_url", ""))
    if link_type not in ("magnet", "115share", "quark"):
        return JSONResponse(status_code=400, content={"ok": False, "msg": "当前仅支持 magnet 下载、115 分享转存和夸克分享转存"})
    receive_code_raw = str(data.get("receive_code", "") or "").strip()
    receive_code = normalize_receive_code(receive_code_raw)
    if link_type in ("115share", "quark") and receive_code_raw and not receive_code:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "提取码格式不正确，请输入 1-16 位字母或数字"})

    cfg = get_config()
    if link_type in ("magnet", "115share"):
        if not str(cfg.get("cookie_115", "")).strip():
            return JSONResponse(status_code=400, content={"ok": False, "msg": "请先在参数配置中填写 115 Cookie"})
    elif not str(cfg.get("cookie_quark", "")).strip():
        return JSONResponse(status_code=400, content={"ok": False, "msg": "请先在参数配置中填写 Quark Cookie"})

    savepath = normalize_relative_path(data.get("savepath", ""))
    if not savepath:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "请填写网盘保存路径"})
    auto_refresh_requested = bool(data.get("auto_refresh", True))
    provided_folder_id = str(data.get("folder_id", "") or "").strip()
    if provided_folder_id and not provided_folder_id.isdigit():
        provided_folder_id = ""

    async with resource_job_create_lock:
        existing = find_existing_resource_job(resource, savepath)
        if existing:
            existing_status = str(existing.get("status", "")).strip().lower()
            if existing_status == "completed":
                msg = "该资源已添加过。若需重新导入，请先清空“已完成导入记录”后再试。"
            else:
                msg = "该资源已在处理中，请勿重复提交。"
            return JSONResponse(
                status_code=409,
                content={
                    "ok": False,
                    "msg": msg,
                    "job_id": existing.get("id", 0),
                    "status": existing_status,
                },
            )

        matched_monitor: Dict[str, Any] = {}
        monitor_task_name = ""
        if link_type != "quark":
            matched_monitor = match_monitor_task_for_savepath(cfg, savepath, provider="115")
            monitor_task_name = matched_monitor.get("task_name", "")
        folder_id = provided_folder_id
        if not folder_id or folder_id == "0":
            try:
                if link_type == "quark":
                    folder_id = await asyncio.to_thread(
                        resolve_quark_folder_id_by_path,
                        str(cfg.get("cookie_quark", "")).strip(),
                        savepath,
                    )
                else:
                    folder_id = await asyncio.to_thread(
                        resolve_115_folder_id_by_path,
                        str(cfg.get("cookie_115", "")).strip(),
                        savepath,
                    )
            except Exception as exc:
                return JSONResponse(status_code=400, content={"ok": False, "msg": f"保存路径无效：{exc}"})

        payload = {
            "folder_id": folder_id,
            "savepath": savepath,
            "sharetitle": str(data.get("sharetitle", "") or "").strip(),
            "monitor_task_name": monitor_task_name,
            "refresh_delay_seconds": max(0, int(data.get("refresh_delay_seconds", 0) or 0)),
            "auto_refresh": (auto_refresh_requested and bool(monitor_task_name)) if link_type != "quark" else False,
            "extra": {
                "job_source": "manual_import",
            },
        }
        if link_type in ("115share", "quark"):
            payload["share_selection"] = data.get("share_selection", {})
            if receive_code:
                payload["receive_code"] = receive_code
        job_id = create_resource_job(resource, payload)

    asyncio.create_task(run_resource_job(job_id))
    return {
        "ok": True,
        "job_id": job_id,
        "monitor_task_name": monitor_task_name if link_type != "quark" else "",
        "auto_refresh": payload["auto_refresh"],
        "monitor_scan_path": matched_monitor.get("full_path", "") if link_type != "quark" else "",
    }


@router.post("/resource/jobs/clear_completed")
async def clear_completed_resource_jobs_endpoint(request: Request) -> Dict[str, Any]:
    result = clear_resource_jobs("completed")
    return {"ok": True, **result}


@router.post("/resource/jobs/clear")
async def clear_resource_jobs_endpoint(request: Request) -> Dict[str, Any]:
    data = await request.json()
    scope = normalize_resource_job_clear_scope(data.get("scope", "completed"))
    if scope not in ("completed", "failed", "terminal"):
        return JSONResponse(status_code=400, content={"ok": False, "msg": "清理范围不支持"})
    result = clear_resource_jobs(scope)
    return {"ok": True, **result}


@router.get("/resource/115/folders")
async def get_115_folders_endpoint(request: Request) -> Dict[str, Any]:
    cfg = get_config()
    cookie = str(cfg.get("cookie_115", "")).strip()
    if not cookie:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "请先配置 115 Cookie"})
    cid = str(request.query_params.get("cid", "0") or "0").strip() or "0"
    folders_only = request.query_params.get("folders_only") == "1"
    compact = request.query_params.get("compact") == "1"
    force_refresh = request.query_params.get("force_refresh") == "1"
    try:
        entries_all = await run_resource_browse_io(list_115_entries, cookie, cid, force_refresh)
        folder_entries = [entry for entry in entries_all if entry.get("is_dir")]
        file_count = max(0, len(entries_all) - len(folder_entries))
        entries = folder_entries if folders_only else entries_all
        summary = {
            "folder_count": len(folder_entries),
            "file_count": file_count,
        }
        if compact:
            return {
                "ok": True,
                "cid": cid,
                "entries": _compact_resource_browser_entries(entries),
                "summary": summary,
            }
        files = [] if folders_only else [entry for entry in entries_all if not entry.get("is_dir")]
        folders = [
            {"id": str(entry.get("id", "")).strip(), "name": str(entry.get("name", "")).strip()}
            for entry in folder_entries
        ]
        return {
            "ok": True,
            "cid": cid,
            "folders": folders,
            "files": files,
            "entries": entries,
            "summary": summary,
        }
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})


@router.post("/resource/115/folders/create")
async def create_115_folder_endpoint(request: Request) -> Dict[str, Any]:
    cfg = get_config()
    cookie = str(cfg.get("cookie_115", "")).strip()
    if not cookie:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "请先配置 115 Cookie"})
    data = await request.json()
    cid = str(data.get("cid", "0") or "0").strip() or "0"
    name = str(data.get("name", "") or "").strip()
    if not name:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "文件夹名称不能为空"})
    try:
        folder = await run_resource_browse_io(create_115_folder, cookie, cid, name)
        return {"ok": True, "cid": cid, "folder": folder}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})


@router.get("/resource/115/share_entries")
async def get_115_share_entries_endpoint(request: Request) -> Dict[str, Any]:
    cfg = get_config()
    cookie = str(cfg.get("cookie_115", "")).strip()
    if not cookie:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "请先配置 115 Cookie"})

    resource_id = int(request.query_params.get("resource_id", 0) or 0)
    if resource_id <= 0:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "资源 ID 无效"})
    resource = get_resource_item(resource_id)
    if not resource:
        return JSONResponse(status_code=404, content={"ok": False, "msg": "资源不存在"})
    if resolve_resource_link_type(resource.get("link_type", ""), resource.get("link_url", "")) != "115share":
        return JSONResponse(status_code=400, content={"ok": False, "msg": "当前资源不是 115 分享链接"})

    cid = str(request.query_params.get("cid", "0") or "0").strip() or "0"
    receive_code_raw = str(request.query_params.get("receive_code", "") or "").strip()
    receive_code = normalize_receive_code(receive_code_raw)
    if receive_code_raw and not receive_code:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "提取码格式不正确，请输入 1-16 位字母或数字"})
    paged = request.query_params.get("paged") == "1"
    folders_only = request.query_params.get("folders_only") == "1"
    offset = max(0, parse_int(request.query_params.get("offset", 0), default=0))
    limit = max(20, min(parse_int(request.query_params.get("limit", 200), default=200), 400))
    try:
        result = await run_resource_browse_io(
            list_115_share_entries,
            cookie,
            str(resource.get("link_url", "")).strip(),
            str(resource.get("raw_text", "") or ""),
            cid,
            receive_code,
            False,
            RESOURCE_SHARE_BROWSE_TIMEOUT_SECONDS,
            RESOURCE_SHARE_BROWSE_RATE_LIMIT_SECONDS,
            RESOURCE_SHARE_BROWSE_MAX_RETRIES,
            offset,
            limit,
            1 if paged else 0,
            folders_only,
        )
        return _build_resource_share_entries_response(
            cid,
            result,
            offset=offset,
            paged=paged,
            folders_only=folders_only,
        )
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})


@router.post("/resource/115/share_entries_preview")
async def preview_115_share_entries_endpoint(request: Request) -> Dict[str, Any]:
    cfg = get_config()
    cookie = str(cfg.get("cookie_115", "")).strip()
    if not cookie:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "请先配置 115 Cookie"})
    data = await request.json()
    link_url = str(data.get("link_url", "") or "").strip()
    raw_text = str(data.get("raw_text", "") or "").strip()
    receive_code_raw = str(data.get("receive_code", "") or "").strip()
    receive_code = normalize_receive_code(receive_code_raw)
    if receive_code_raw and not receive_code:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "提取码格式不正确，请输入 1-16 位字母或数字"})
    if not link_url:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "资源链接为空"})
    cid = str(data.get("cid", "0") or "0").strip() or "0"
    paged = bool(data.get("paged", False))
    folders_only = bool(data.get("folders_only", False))
    offset = max(0, parse_int(data.get("offset", 0), default=0))
    limit = max(20, min(parse_int(data.get("limit", 200), default=200), 400))
    try:
        result = await run_resource_browse_io(
            list_115_share_entries,
            cookie,
            link_url,
            raw_text,
            cid,
            receive_code,
            False,
            RESOURCE_SHARE_BROWSE_TIMEOUT_SECONDS,
            RESOURCE_SHARE_BROWSE_RATE_LIMIT_SECONDS,
            RESOURCE_SHARE_BROWSE_MAX_RETRIES,
            offset,
            limit,
            1 if paged else 0,
            folders_only,
        )
        return _build_resource_share_entries_response(
            cid,
            result,
            offset=offset,
            paged=paged,
            folders_only=folders_only,
        )
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})


@router.get("/resource/quark/folders")
async def get_quark_folders_endpoint(request: Request) -> Dict[str, Any]:
    cfg = get_config()
    cookie = str(cfg.get("cookie_quark", "")).strip()
    if not cookie:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "请先配置 Quark Cookie"})
    cid = str(request.query_params.get("cid", "0") or "0").strip() or "0"
    folders_only = request.query_params.get("folders_only") == "1"
    compact = request.query_params.get("compact") == "1"
    try:
        payload = await run_resource_browse_io(list_quark_entries_payload, cookie, cid, folders_only)
        entries_all = payload.get("entries", []) if isinstance(payload.get("entries"), list) else []
        folder_entries = [entry for entry in entries_all if entry.get("is_dir")]
        entries = folder_entries if folders_only else entries_all
        summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
        if not summary:
            summary = {
                "folder_count": len(folder_entries),
                "file_count": max(0, len(entries_all) - len(folder_entries)),
            }
        if compact:
            return {
                "ok": True,
                "cid": cid,
                "entries": _compact_resource_browser_entries(entries),
                "summary": summary,
            }
        files = [] if folders_only else [entry for entry in entries_all if not entry.get("is_dir")]
        folders = [
            {"id": str(entry.get("id", "")).strip(), "name": str(entry.get("name", "")).strip()}
            for entry in folder_entries
        ]
        return {
            "ok": True,
            "cid": cid,
            "folders": folders,
            "files": files,
            "entries": entries,
            "summary": summary,
        }
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})


@router.post("/resource/quark/folders/create")
async def create_quark_folder_endpoint(request: Request) -> Dict[str, Any]:
    cfg = get_config()
    cookie = str(cfg.get("cookie_quark", "")).strip()
    if not cookie:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "请先配置 Quark Cookie"})
    data = await request.json()
    cid = str(data.get("cid", "0") or "0").strip() or "0"
    name = str(data.get("name", "") or "").strip()
    if not name:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "文件夹名称不能为空"})
    try:
        folder = await run_resource_browse_io(create_quark_folder, cookie, cid, name)
        return {"ok": True, "cid": cid, "folder": folder}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})


@router.get("/resource/quark/share_entries")
async def get_quark_share_entries_endpoint(request: Request) -> Dict[str, Any]:
    cfg = get_config()
    cookie = str(cfg.get("cookie_quark", "")).strip()
    if not cookie:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "请先配置 Quark Cookie"})

    resource_id = int(request.query_params.get("resource_id", 0) or 0)
    if resource_id <= 0:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "资源 ID 无效"})
    resource = get_resource_item(resource_id)
    if not resource:
        return JSONResponse(status_code=404, content={"ok": False, "msg": "资源不存在"})
    if resolve_resource_link_type(resource.get("link_type", ""), resource.get("link_url", "")) != "quark":
        return JSONResponse(status_code=400, content={"ok": False, "msg": "当前资源不是夸克分享链接"})

    cid = str(request.query_params.get("cid", "0") or "0").strip() or "0"
    receive_code_raw = str(request.query_params.get("receive_code", "") or "").strip()
    receive_code = normalize_receive_code(receive_code_raw)
    if receive_code_raw and not receive_code:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "提取码格式不正确，请输入 1-16 位字母或数字"})
    paged = request.query_params.get("paged") == "1"
    folders_only = request.query_params.get("folders_only") == "1"
    offset = max(0, parse_int(request.query_params.get("offset", 0), default=0))
    limit = max(20, min(parse_int(request.query_params.get("limit", 200), default=200), 400))
    max_pages = 1 if paged else 0
    try:
        result = await run_resource_browse_io(
            list_quark_share_entries,
            cookie,
            str(resource.get("link_url", "")).strip(),
            str(resource.get("raw_text", "") or ""),
            cid,
            receive_code,
            False,
            45,
            offset,
            limit,
            max_pages,
            folders_only,
        )
        return _build_resource_share_entries_response(
            cid,
            result,
            offset=offset,
            paged=paged,
            folders_only=folders_only,
        )
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})


@router.post("/resource/quark/share_entries_preview")
async def preview_quark_share_entries_endpoint(request: Request) -> Dict[str, Any]:
    cfg = get_config()
    cookie = str(cfg.get("cookie_quark", "")).strip()
    if not cookie:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "请先配置 Quark Cookie"})
    data = await request.json()
    link_url = str(data.get("link_url", "") or "").strip()
    raw_text = str(data.get("raw_text", "") or "").strip()
    receive_code_raw = str(data.get("receive_code", "") or "").strip()
    receive_code = normalize_receive_code(receive_code_raw)
    if receive_code_raw and not receive_code:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "提取码格式不正确，请输入 1-16 位字母或数字"})
    if not link_url:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "资源链接为空"})
    cid = str(data.get("cid", "0") or "0").strip() or "0"
    paged = bool(data.get("paged", False))
    folders_only = bool(data.get("folders_only", False))
    offset = max(0, parse_int(data.get("offset", 0), default=0))
    limit = max(20, min(parse_int(data.get("limit", 200), default=200), 400))
    max_pages = 1 if paged else 0
    try:
        result = await run_resource_browse_io(
            list_quark_share_entries,
            cookie,
            link_url,
            raw_text,
            cid,
            receive_code,
            False,
            45,
            offset,
            limit,
            max_pages,
            folders_only,
        )
        return _build_resource_share_entries_response(
            cid,
            result,
            offset=offset,
            paged=paged,
            folders_only=folders_only,
        )
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})


@router.get("/resource/image")
async def proxy_resource_image(request: Request) -> Response:
    image_url = str(request.query_params.get("url", "") or "").strip()
    if not image_url:
        return Response(status_code=400)
    cfg = get_config()
    headers = {
        "User-Agent": "Mozilla/5.0 115-media-hub",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Referer": "https://t.me/",
        "Origin": "https://t.me",
    }
    attempts: List[str] = []
    proxy_url = build_tg_proxy_url(cfg)
    if proxy_url:
        attempts.append(proxy_url)
    attempts.append("")
    for current_proxy in attempts:
        try:
            body, content_type = await asyncio.to_thread(
                http_request_binary,
                image_url,
                45,
                headers,
                current_proxy,
            )
            if not body or str(content_type or "").startswith("text/html"):
                continue
            return Response(content=body, media_type=content_type, headers={"Cache-Control": "public, max-age=3600"})
        except Exception:
            continue
    return Response(status_code=404)


@router.post("/resource/jobs/refresh")
async def refresh_resource_job_endpoint(request: Request) -> Dict[str, Any]:
    data = await request.json()
    job_id = int(data.get("job_id", 0) or 0)
    if job_id <= 0:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "任务 ID 无效"})
    try:
        result = await trigger_resource_job_refresh(job_id, reason="manual")
        return {"ok": True, **result}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})


@router.post("/resource/jobs/cancel")
async def cancel_resource_job_endpoint(request: Request) -> Dict[str, Any]:
    data = await request.json()
    job_id = int(data.get("job_id", 0) or 0)
    if job_id <= 0:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "任务 ID 无效"})
    try:
        result = await cancel_resource_job(job_id, reason="manual")
        return {"ok": True, **result}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})


@router.post("/resource/jobs/retry")
async def retry_resource_job_endpoint(request: Request) -> Dict[str, Any]:
    data = await request.json()
    job_id = int(data.get("job_id", 0) or 0)
    if job_id <= 0:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "任务 ID 无效"})
    try:
        result = await retry_resource_job(job_id, reason="manual")
        return {"ok": True, **result}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})
