import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..core import *  # noqa: F401,F403
from ..services.monitor import queue_monitor_job

router = APIRouter()


@router.get("/monitor/status")
async def get_monitor_status(request: Request) -> Dict[str, Any]:
    return build_monitor_status_payload()


@router.post("/monitor/logs/clear")
async def clear_monitor_logs(request: Request) -> Dict[str, Any]:
    monitor_status["logs"] = [{"text": f"{format_log_time(True)} 监控日志已清空", "level": "info"}]
    await asyncio.to_thread(clear_log_file, MONITOR_LOG_PATH, f"{format_log_time(True)} 监控日志已清空")
    schedule_ui_state_push(0)
    return {"ok": True}


@router.post("/monitor/save")
async def save_monitor_tasks(request: Request) -> Dict[str, Any]:
    data = await request.json()
    cfg = get_config()
    tasks = data.get("tasks", [])
    normalized = []
    names = set()
    for raw_task in tasks:
        task = normalize_task(raw_task)
        if not task["name"]:
            continue
        if task["name"] in names:
            return JSONResponse(status_code=400, content={"ok": False, "msg": f"任务名重复: {task['name']}"})
        names.add(task["name"])
        normalized.append(task)
    cfg["monitor_tasks"] = normalized
    save_config(cfg)
    alive = {task["name"] for task in normalized}
    for dead_name in list(monitor_last_run.keys()):
        if dead_name not in alive:
            monitor_last_run.pop(dead_name, None)
            monitor_next_run.pop(dead_name, None)
    schedule_ui_state_push(0)
    return {"ok": True, "tasks": normalized}


@router.post("/monitor/start")
async def start_monitor(request: Request) -> Dict[str, Any]:
    data = await request.json()
    task_name = str(data.get("name", "")).strip()
    cfg = get_config()
    if not any(task["name"] == task_name for task in cfg["monitor_tasks"]):
        return JSONResponse(status_code=404, content={"ok": False, "msg": "任务不存在"})
    status = queue_monitor_job(task_name, "manual")
    return {"ok": True, "status": status}


@router.post("/monitor/stop")
async def stop_monitor(request: Request) -> Dict[str, Any]:
    data = await request.json()
    task_name = str(data.get("name", "")).strip()
    if monitor_status["running"] and monitor_status["current_task"] == task_name:
        monitor_control["cancel"] = True
        return {"ok": True, "status": "stopping"}
    return {"ok": False, "status": "idle"}


@router.post("/monitor/delete")
async def delete_monitor(request: Request) -> Dict[str, Any]:
    data = await request.json()
    task_name = str(data.get("name", "")).strip()
    cfg = get_config()
    before = len(cfg["monitor_tasks"])
    cfg["monitor_tasks"] = [task for task in cfg["monitor_tasks"] if task["name"] != task_name]
    if len(cfg["monitor_tasks"]) == before:
        return JSONResponse(status_code=404, content={"ok": False, "msg": "任务不存在"})
    save_config(cfg)
    monitor_queue[:] = [item for item in monitor_queue if item["task_name"] != task_name]
    monitor_status["queued"] = [item["task_name"] for item in monitor_queue]
    monitor_last_run.pop(task_name, None)
    monitor_next_run.pop(task_name, None)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM monitor_files WHERE task_name = ?", (task_name,))
    cursor.execute("DELETE FROM monitor_dirs WHERE task_name = ?", (task_name,))
    conn.commit()
    conn.close()
    schedule_ui_state_push(0)
    return {"ok": True}


@router.post("/webhook/{task_name}")
async def webhook(task_name: str, request: Request) -> JSONResponse:
    payload = await request.json()
    cfg = get_config()
    task = next((task for task in cfg["monitor_tasks"] if task["name"] == task_name), None)
    if not task:
        return JSONResponse(status_code=404, content={"ok": False, "msg": "未找到对应监控任务"})
    if not task.get("webhook_enabled"):
        return JSONResponse(status_code=400, content={"ok": False, "msg": "该任务未开启 webhook"})
    title = str(payload.get("title", "") or "").strip()
    savepath = str(payload.get("savepath", "") or "").strip()
    sharetitle = str(payload.get("sharetitle", "") or "").strip()
    refresh_target_type = str(payload.get("refresh_target_type", "") or "").strip()

    queue_monitor_job(task_name, "webhook", payload)
    await write_monitor_log(
        f"Webhook 入队: {task_name} | savepath={savepath or '(未传)'} | sharetitle={sharetitle or '(空)'} | type={refresh_target_type or '(未传)'} | delayTime={payload.get('delayTime', 0)}",
        "info",
    )
    if title:
        await write_monitor_log(f"转存内容：{title}", "info")
    return JSONResponse(content=payload)
