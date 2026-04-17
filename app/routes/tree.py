import asyncio

from fastapi import APIRouter, BackgroundTasks, Request

from ..core import *  # noqa: F401,F403
from ..services.tree import run_sync

router = APIRouter()


@router.post("/start")
async def start_sync(request: Request, bt: BackgroundTasks) -> Dict[str, str]:
    data = await request.json()
    if not task_status["running"]:
        bt.add_task(run_sync, use_local=data.get("use_local", False), force_full=data.get("force_full", False))
        return {"status": "started"}
    return {"status": "busy"}


@router.get("/logs")
async def get_logs(request: Request) -> Dict[str, Any]:
    return build_main_status_payload()


@router.post("/logs/clear")
async def clear_logs(request: Request) -> Dict[str, Any]:
    line = f"{format_log_time(True)} 系统日志已清空"
    task_status["logs"] = [{"text": line, "level": "info"}]
    await asyncio.to_thread(clear_log_file, MAIN_LOG_PATH, line)
    schedule_ui_state_push(0)
    return {"ok": True}
