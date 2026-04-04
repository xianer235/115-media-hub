import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from ..core import *  # noqa: F401,F403
from ..services.resource import run_resource_job, trigger_resource_job_refresh

router = APIRouter()


@router.get("/resource/state")
async def get_resource_state(request: Request) -> Dict[str, Any]:
    search = str(request.query_params.get("q", "") or "").strip()
    sync_channels = request.query_params.get("sync") == "1"
    if sync_channels:
        await sync_telegram_channels(force=False, limit_per_channel=10)
    return await build_resource_state_payload(search=search)


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


@router.post("/resource/channels/sync")
async def sync_resource_channels_endpoint(request: Request) -> Dict[str, Any]:
    data = await request.json()
    force = bool(data.get("force", False))
    limit_per_channel = max(1, min(int(data.get("limit", 10) or 10), 30))
    return await sync_telegram_channels(force=force, limit_per_channel=limit_per_channel)


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
    return {
        "ok": True,
        "channel_id": channel_id,
        "query": query,
        "before": before,
        "items": items,
        "inserted": 0,
        "updated": 0,
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
    return {"ok": True, "inserted": inserted, "updated": updated, "items": items}


@router.post("/resource/items/preview_text")
async def preview_resource_text(request: Request) -> Dict[str, Any]:
    data = await request.json()
    raw_text = str(data.get("raw_text", "") or "").strip()
    if not raw_text:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "请先粘贴 magnet、115 分享链接或资源文本"})

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
    resource = get_resource_item(resource_id)
    if not resource:
        return JSONResponse(status_code=404, content={"ok": False, "msg": "资源不存在"})
    delete_resource_item(resource_id)
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
    if link_type not in ("magnet", "115share"):
        return JSONResponse(status_code=400, content={"ok": False, "msg": "当前仅支持 magnet 下载和 115 分享转存"})

    cfg = get_config()
    if not str(cfg.get("cookie_115", "")).strip():
        return JSONResponse(status_code=400, content={"ok": False, "msg": "请先在参数配置中填写 115 Cookie"})

    savepath = normalize_relative_path(data.get("savepath", ""))
    if not savepath:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "请填写网盘保存路径"})

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

    matched_monitor = match_monitor_task_for_savepath(cfg, savepath)
    monitor_task_name = matched_monitor.get("task_name", "")

    try:
        folder_id = await asyncio.to_thread(resolve_115_folder_id_by_path, str(cfg.get("cookie_115", "")).strip(), savepath)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "msg": f"保存路径无效：{exc}"})

    auto_refresh_requested = bool(data.get("auto_refresh", True))
    payload = {
        "folder_id": folder_id,
        "savepath": savepath,
        "sharetitle": str(data.get("sharetitle", "") or "").strip(),
        "monitor_task_name": monitor_task_name,
        "refresh_delay_seconds": max(0, int(data.get("refresh_delay_seconds", 0) or 0)),
        "auto_refresh": auto_refresh_requested and bool(monitor_task_name),
    }
    if link_type == "115share":
        payload["share_selection"] = data.get("share_selection", {})
    job_id = create_resource_job(resource, payload)
    asyncio.create_task(run_resource_job(job_id))
    return {
        "ok": True,
        "job_id": job_id,
        "monitor_task_name": monitor_task_name,
        "auto_refresh": payload["auto_refresh"],
        "openlist_path": matched_monitor.get("full_path", ""),
    }


@router.post("/resource/jobs/clear_completed")
async def clear_completed_resource_jobs_endpoint(request: Request) -> Dict[str, Any]:
    result = clear_completed_resource_jobs()
    return {"ok": True, **result}


@router.get("/resource/115/folders")
async def get_115_folders_endpoint(request: Request) -> Dict[str, Any]:
    cfg = get_config()
    cookie = str(cfg.get("cookie_115", "")).strip()
    if not cookie:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "请先配置 115 Cookie"})
    cid = str(request.query_params.get("cid", "0") or "0").strip() or "0"
    try:
        entries = await asyncio.to_thread(list_115_entries, cookie, cid)
        folders = [{"id": str(entry.get("id", "")).strip(), "name": str(entry.get("name", "")).strip()} for entry in entries if entry.get("is_dir")]
        files = [entry for entry in entries if not entry.get("is_dir")]
        return {
            "ok": True,
            "cid": cid,
            "folders": folders,
            "files": files,
            "entries": entries,
            "summary": {
                "folder_count": len(folders),
                "file_count": len(files),
            },
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
        folder = await asyncio.to_thread(create_115_folder, cookie, cid, name)
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
    try:
        result = await asyncio.to_thread(
            list_115_share_entries,
            cookie,
            str(resource.get("link_url", "")).strip(),
            str(resource.get("raw_text", "") or ""),
            cid,
        )
        return {
            "ok": True,
            "cid": cid,
            "entries": result.get("entries", []),
            "summary": result.get("summary", {"folder_count": 0, "file_count": 0}),
            "share": {
                "title": result.get("share_title", ""),
                "share_code": result.get("share_code", ""),
                "receive_code": result.get("receive_code", ""),
                "count": result.get("count", 0),
            },
        }
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
    if not link_url:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "资源链接为空"})
    cid = str(data.get("cid", "0") or "0").strip() or "0"
    try:
        result = await asyncio.to_thread(
            list_115_share_entries,
            cookie,
            link_url,
            raw_text,
            cid,
        )
        return {
            "ok": True,
            "cid": cid,
            "entries": result.get("entries", []),
            "summary": result.get("summary", {"folder_count": 0, "file_count": 0}),
            "share": {
                "title": result.get("share_title", ""),
                "share_code": result.get("share_code", ""),
                "receive_code": result.get("receive_code", ""),
                "count": result.get("count", 0),
            },
        }
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})


@router.get("/resource/image")
async def proxy_resource_image(request: Request) -> Response:
    image_url = str(request.query_params.get("url", "") or "").strip()
    if not image_url:
        return Response(status_code=400)
    cfg = get_config()
    headers = {
        "User-Agent": "Mozilla/5.0 115-strm-web",
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
