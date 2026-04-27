import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..core import *  # noqa: F401,F403
from ..services.subscription import (
    get_subscription_task_episode_view,
    queue_subscription_job,
    rebuild_subscription_task_progress,
)

router = APIRouter()


@router.get("/subscription/status")
async def get_subscription_status(request: Request) -> Dict[str, Any]:
    return build_subscription_status_payload()


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
    subscription_status["logs"] = [{"text": f"{format_log_time(True)} 订阅日志已清空", "level": "info"}]
    await asyncio.to_thread(clear_log_file, SUBSCRIPTION_LOG_PATH, f"{format_log_time(True)} 订阅日志已清空")
    schedule_ui_state_push(0)
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
    if not raw_text and not link_url:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "请填写夸克分享链接"})
    link_match = RESOURCE_QUARK_SHARE_URL_REGEX.search(link_url or raw_text)
    normalized_link = str(link_match.group(0) if link_match else link_url).strip()
    if normalized_link and not normalized_link.lower().startswith(("http://", "https://")):
        normalized_link = f"https://{normalized_link.lstrip('/')}"
    if resolve_resource_link_type("", normalized_link) != "quark":
        return JSONResponse(status_code=400, content={"ok": False, "msg": "指定链接仅支持夸克分享链接"})

    cfg = get_config()
    task = None
    for raw_task in cfg.get("subscription_tasks", []) or []:
        normalized = normalize_subscription_task(raw_task or {})
        if normalized.get("name") == task_name:
            task = normalized
            break
    if not task:
        return JSONResponse(status_code=404, content={"ok": False, "msg": "任务不存在"})
    if normalize_subscription_provider(task.get("provider", "115"), fallback="115") != "quark":
        return JSONResponse(status_code=400, content={"ok": False, "msg": "只有夸克订阅任务支持指定夸克链接扫描"})

    payload = parse_quark_share_payload(normalized_link, raw_text, receive_code)
    if not str(payload.get("pwd_id", "") or "").strip():
        return JSONResponse(status_code=400, content={"ok": False, "msg": "未能识别夸克分享链接"})
    status = queue_subscription_job(
        task_name,
        "manual_link",
        manual_candidate={
            "link_url": str(payload.get("url", "") or normalized_link).strip(),
            "raw_text": raw_text or normalized_link,
            "receive_code": normalize_receive_code(payload.get("receive_code", "")),
        },
    )
    return {"ok": True, "status": status}


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
    subscription_queue[:] = [item for item in subscription_queue if item.get("task_name") != task_name]
    subscription_status["queued"] = [item["task_name"] for item in subscription_queue]
    subscription_last_run.pop(task_name, None)
    subscription_next_run.pop(task_name, None)
    prune_subscription_state_for_missing_tasks([task.get("name", "") for task in cfg.get("subscription_tasks", [])])
    schedule_ui_state_push(0)
    return {"ok": True}
