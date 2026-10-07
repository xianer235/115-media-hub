import asyncio
from typing import Any, Dict, List

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..core import *  # noqa: F401,F403
from ..services.subscription import (
    get_subscription_task_episode_view,
    queue_subscription_job,
    queue_subscription_jobs,
    rebuild_subscription_task_progress,
)

router = APIRouter()

SUBSCRIPTION_OFFLINE_LINK_TYPES = {"magnet", "ed2k"}


def _collect_subscription_link_entries(
    data: Dict[str, Any],
    fallback_link_url: str = "",
    fallback_raw_text: str = "",
    fallback_receive_code: str = "",
) -> List[Dict[str, str]]:
    """把请求体归一成 [{link_url, raw_text, receive_code}, ...]，兼容旧的单链接字段。

    新前端会传 `links`（每行一条，raw_text 为这条链接所在的文本片段）；
    旧前端 / CLI 只传 `link_url` / `raw_text`，这里退化成单元素列表。
    """
    entries: List[Dict[str, str]] = []
    raw_links = data.get("links")
    if isinstance(raw_links, list):
        for raw_entry in raw_links:
            if isinstance(raw_entry, dict):
                link = str(raw_entry.get("link_url") or raw_entry.get("url") or "").strip()
                text = str(raw_entry.get("raw_text") or "").strip()
                code = normalize_receive_code(raw_entry.get("receive_code", ""))
            else:
                link = str(raw_entry or "").strip()
                text = ""
                code = ""
            if not link and not text:
                continue
            entries.append({"link_url": link, "raw_text": text or link, "receive_code": code})
    if not entries and (fallback_link_url or fallback_raw_text):
        entries.append(
            {
                "link_url": fallback_link_url,
                "raw_text": fallback_raw_text or fallback_link_url,
                "receive_code": fallback_receive_code,
            }
        )
    return entries


def _resolve_subscription_manual_candidate(
    provider: str,
    provider_meta: Any,
    link_url: str,
    raw_text: str,
    receive_code: str,
    fallback_raw_text: str = "",
) -> Dict[str, Any]:
    """把一条原始链接解析成订阅手工候选；无法识别时抛 ValueError（消息可直接展示）。"""
    source_text = str(link_url or raw_text or "").strip()
    candidate_links: List[str] = []
    if link_url:
        candidate_links.append(link_url)
    candidate_links.extend(extract_resource_links(source_text))
    offline_link_types = SUBSCRIPTION_OFFLINE_LINK_TYPES if bool(provider_meta.supports_offline) else set()
    normalized_link = ""
    for candidate_link in candidate_links:
        candidate = str(candidate_link or "").strip()
        if not candidate:
            continue
        candidate_link_type = resolve_resource_link_type("", candidate)
        if candidate_link_type == provider_meta.link_type or candidate_link_type in offline_link_types:
            normalized_link = candidate
            break
    normalized_link_type = resolve_resource_link_type("", normalized_link)
    resolved_receive_code = normalize_receive_code(receive_code)
    if provider == "quark":
        link_match = RESOURCE_QUARK_SHARE_URL_REGEX.search(source_text)
        normalized_link = str(link_match.group(0) if link_match else normalized_link).strip()
        if normalized_link and not normalized_link.lower().startswith(("http://", "https://")):
            normalized_link = f"https://{normalized_link.lstrip('/')}"
        if resolve_resource_link_type("", normalized_link) != "quark":
            raise ValueError("请填写夸克分享链接")
        payload = parse_quark_share_payload(normalized_link, raw_text, resolved_receive_code)
        if not str(payload.get("pwd_id", "") or "").strip():
            raise ValueError("未能识别夸克分享链接")
        payload_link = str(payload.get("url", "") or normalized_link).strip()
        payload_receive_code = normalize_receive_code(payload.get("receive_code", ""))
    elif provider == "115":
        if normalized_link_type in offline_link_types:
            payload_link = str(normalized_link or "").strip()
            if not payload_link:
                raise ValueError("请填写 115 磁力/电驴链接")
            payload_receive_code = ""
        else:
            link_match = RESOURCE_115_SHARE_URL_REGEX.search(source_text)
            normalized_link = str(link_match.group(0) if link_match else normalized_link).strip()
            payload = parse_115_share_payload(normalized_link, raw_text, resolved_receive_code)
            # 多行粘贴时 raw_text 只是这一条链接所在片段，提取码可能落在片段外（例如单链接整段文本）。
            if (
                not str(payload.get("share_code", "") or "").strip()
                and fallback_raw_text
                and fallback_raw_text != raw_text
            ):
                payload = parse_115_share_payload(normalized_link, fallback_raw_text, resolved_receive_code)
            if not str(payload.get("share_code", "") or "").strip():
                raise ValueError("请填写 115 分享链接")
            payload_link = str(payload.get("url", "") or normalized_link).strip()
            payload_receive_code = normalize_receive_code(payload.get("receive_code", ""))
    else:
        if not normalized_link or resolve_resource_link_type("", normalized_link) != provider_meta.link_type:
            raise ValueError(f"请填写 {provider_meta.label} 分享链接")
        payload_link = normalized_link
        payload_receive_code = resolved_receive_code
    return {
        "provider": provider,
        "link_url": payload_link,
        "raw_text": raw_text or payload_link,
        "receive_code": payload_receive_code,
        "link_type": normalized_link_type,
    }


@router.get("/subscription/status")
async def get_subscription_status(request: Request) -> Dict[str, Any]:
    compact = request.query_params.get("compact") == "1"
    return build_subscription_status_payload(compact=compact)


@router.get("/subscription/logs")
async def get_subscription_logs(request: Request) -> Dict[str, Any]:
    after = parse_int_param(request.query_params.get("after"), 0)
    before = parse_int_param(request.query_params.get("before"), 0)
    limit = parse_int_param(request.query_params.get("limit"), SUBSCRIPTION_LOG_PAGE_LIMIT)
    return build_subscription_log_page_payload(after=after, before=before, limit=limit)


@router.get("/subscription/episodes")
async def get_subscription_task_episodes(request: Request) -> Dict[str, Any]:
    task_name = str(request.query_params.get("name", "") or "").strip()
    if not task_name:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "任务名称不能为空"})
    try:
        payload = await asyncio.to_thread(get_subscription_task_episode_view, task_name)
        return {"ok": True, **payload}
    except KeyError:
        return JSONResponse(status_code=404, content={"ok": False, "msg": "任务不存在"})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})


@router.post("/subscription/logs/clear")
async def clear_subscription_logs(request: Request) -> Dict[str, Any]:
    await clear_subscription_log_history()
    return {"ok": True}


@router.post("/subscription/save")
async def save_subscription_tasks(request: Request) -> Dict[str, Any]:
    data = await request.json()
    cfg = get_config()
    incoming = data.get("tasks", [])
    normalized = []
    names = set()
    for raw_task in incoming if isinstance(incoming, list) else []:
        task = normalize_subscription_task(raw_task or {})
        if not task["name"]:
            continue
        if task["name"] in names:
            return JSONResponse(status_code=400, content={"ok": False, "msg": f"影视名称重复: {task['name']}"})
        if not task["title"]:
            return JSONResponse(status_code=400, content={"ok": False, "msg": f"任务未填写订阅名称: {task['name']}"})
        if not task["savepath"]:
            return JSONResponse(status_code=400, content={"ok": False, "msg": f"任务未填写保存路径: {task['name']}"})
        names.add(task["name"])
        normalized.append(task)
    cfg["subscription_tasks"] = normalized
    save_config(cfg)

    alive = {task["name"] for task in normalized}
    for dead_name in list(subscription_last_run.keys()):
        if dead_name not in alive:
            subscription_last_run.pop(dead_name, None)
            subscription_next_run.pop(dead_name, None)
    with subscription_queue_lock:
        subscription_queue[:] = [item for item in subscription_queue if item.get("task_name") in alive]
        subscription_status["queued"] = [item["task_name"] for item in subscription_queue]
    prune_subscription_state_for_missing_tasks(list(alive))
    schedule_ui_state_push(0)
    return {"ok": True, "tasks": list_subscription_task_runtime(cfg)}


@router.post("/subscription/start")
async def start_subscription_task(request: Request) -> Dict[str, Any]:
    data = await request.json()
    task_name = str(data.get("name", "")).strip()
    cfg = get_config()
    task = None
    for raw_task in cfg.get("subscription_tasks", []) or []:
        normalized = normalize_subscription_task(raw_task or {})
        if normalized.get("name") == task_name:
            task = normalized
            break
    if not task:
        return JSONResponse(status_code=404, content={"ok": False, "msg": "任务不存在"})
    status = queue_subscription_job(task_name, "manual")
    return {"ok": True, "status": status}


@router.post("/subscription/start_with_link")
async def start_subscription_task_with_link(request: Request) -> Dict[str, Any]:
    data = await request.json()
    task_name = str(data.get("name", "") or "").strip()
    raw_text = str(data.get("raw_text", "") or data.get("link_url", "") or "").strip()
    link_url = str(data.get("link_url", "") or "").strip()
    receive_code = normalize_receive_code(data.get("receive_code", ""))
    if not task_name:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "任务名称不能为空"})
    entries = _collect_subscription_link_entries(
        data,
        fallback_link_url=link_url,
        fallback_raw_text=raw_text,
        fallback_receive_code=receive_code,
    )
    if not entries:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "请填写分享链接"})

    cfg = get_config()
    task = None
    for raw_task in cfg.get("subscription_tasks", []) or []:
        normalized = normalize_subscription_task(raw_task or {})
        if normalized.get("name") == task_name:
            task = normalized
            break
    if not task:
        return JSONResponse(status_code=404, content={"ok": False, "msg": "任务不存在"})
    provider = normalize_subscription_provider(task.get("provider", "115"), fallback="115")
    from app.providers.registry import get_or_none as _registry_get_provider_or_none

    provider_meta = _registry_get_provider_or_none(provider)
    if not provider_meta or not provider_meta.supports_subscription or not provider_meta.link_type:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "当前订阅任务不支持扫描链接"})
    # 只有单条链接时才允许用整段文本兜底找提取码，避免多条粘贴时把别人的提取码串到这条上。
    fallback_raw_text = raw_text if len(entries) == 1 else ""
    candidates: List[Dict[str, Any]] = []
    skipped: List[Dict[str, str]] = []
    seen_links: set = set()
    for entry in entries:
        entry_raw_text = str(entry.get("raw_text", "") or "")
        try:
            candidate = _resolve_subscription_manual_candidate(
                provider,
                provider_meta,
                str(entry.get("link_url", "") or ""),
                entry_raw_text,
                str(entry.get("receive_code", "") or "") or receive_code,
                fallback_raw_text=fallback_raw_text,
            )
        except ValueError as exc:
            skipped.append({"link": str(entry.get("link_url", "") or entry_raw_text), "msg": str(exc)})
            continue
        dedupe_key = str(candidate.get("link_url", "") or "").lower()
        if dedupe_key and dedupe_key in seen_links:
            continue
        if dedupe_key:
            seen_links.add(dedupe_key)
        candidates.append(candidate)

    if not candidates:
        first_error = skipped[0]["msg"] if skipped else "请填写分享链接"
        return JSONResponse(
            status_code=400,
            content={"ok": False, "msg": first_error, "skipped": skipped},
        )

    status = queue_subscription_jobs(task_name, "manual_link", candidates)
    return {"ok": True, "status": status, "submitted": len(candidates), "skipped": skipped}


@router.post("/subscription/stop")
async def stop_subscription_task(request: Request) -> Dict[str, Any]:
    data = await request.json()
    task_name = str(data.get("name", "")).strip()
    if subscription_status["running"] and subscription_status["current_task"] == task_name:
        subscription_control["cancel"] = True
        return {"ok": True, "status": "stopping"}
    return {"ok": False, "status": "idle"}


@router.post("/subscription/rebuild")
async def rebuild_subscription_task(request: Request) -> Dict[str, Any]:
    data = await request.json()
    task_name = str(data.get("name", "") or "").strip()
    if not task_name:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "任务名称不能为空"})
    try:
        payload = await asyncio.to_thread(rebuild_subscription_task_progress, task_name)
        schedule_ui_state_push(0)
        await write_subscription_log(
            f"手动重建完成 | {task_name} | {str(payload.get('detail', '') or '').strip()}",
            "info",
        )
        return {"ok": True, "msg": str(payload.get("detail", "") or "已完成重建"), **payload}
    except KeyError:
        return JSONResponse(status_code=404, content={"ok": False, "msg": "任务不存在"})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})
    except RuntimeError as exc:
        return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})


@router.post("/subscription/delete")
async def delete_subscription_task(request: Request) -> Dict[str, Any]:
    data = await request.json()
    task_name = str(data.get("name", "")).strip()
    cfg = get_config()
    before = len(cfg.get("subscription_tasks", []))
    normalized_tasks = []
    for raw_task in cfg.get("subscription_tasks", []) or []:
        task = normalize_subscription_task(raw_task or {})
        if task.get("name") == task_name:
            continue
        normalized_tasks.append(task)
    cfg["subscription_tasks"] = normalized_tasks
    if len(cfg["subscription_tasks"]) == before:
        return JSONResponse(status_code=404, content={"ok": False, "msg": "任务不存在"})
    save_config(cfg)
    with subscription_queue_lock:
        subscription_queue[:] = [item for item in subscription_queue if item.get("task_name") != task_name]
        subscription_status["queued"] = [item["task_name"] for item in subscription_queue]
    subscription_last_run.pop(task_name, None)
    subscription_next_run.pop(task_name, None)
    prune_subscription_state_for_missing_tasks([task.get("name", "") for task in cfg.get("subscription_tasks", [])])
    schedule_ui_state_push(0)
    return {"ok": True}
