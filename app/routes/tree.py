import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..background import submit_background
from ..core import *  # noqa: F401,F403
from ..services.tree import (
    find_tree_task_name_conflict,
    list_tree_export_jobs,
    run_sync,
    run_tree_task,
)

router = APIRouter()


def _tree_busy_response() -> JSONResponse:
    return JSONResponse(status_code=409, content={"ok": False, "msg": "已有目录树任务在运行，请稍后再试", "status": "busy"})


@router.get("/tree/tasks")
async def list_tree_tasks(request: Request) -> Dict[str, Any]:
    cfg = get_config()
    return {"ok": True, "tasks": cfg.get("tree_tasks", [])}


@router.get("/tree/task-defaults")
async def get_tree_task_defaults(request: Request) -> Dict[str, Any]:
    folder_path = normalize_relative_path(str(request.query_params.get("folder_path", "") or "").strip())
    if not folder_path:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "文件夹路径不能为空"})
    cfg = get_config()
    cookie = str(cfg.get("cookie_115", "") or "").strip()
    if not cookie:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "请先在参数配置中填写 115 Cookie"})
    try:
        await asyncio.to_thread(resolve_115_folder_id_by_path, cookie, folder_path)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "msg": f"文件夹不存在或无法访问：{folder_path}（{exc}）"})
    defaults = build_tree_task_defaults(folder_path)
    return {"ok": True, "defaults": defaults, "folder_path": folder_path}


@router.post("/tree/tasks")
async def create_tree_task(request: Request) -> Dict[str, Any]:
    data = await request.json()
    payload = data if isinstance(data, dict) else {}
    folder_path = normalize_relative_path(str(payload.get("folder_path", "") or "").strip())
    if not folder_path:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "文件夹路径不能为空"})
    cfg = get_config()
    cookie = str(cfg.get("cookie_115", "") or "").strip()
    if not cookie:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "请先在参数配置中填写 115 Cookie"})
    try:
        await asyncio.to_thread(resolve_115_folder_id_by_path, cookie, folder_path)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "msg": f"文件夹不存在或无法访问：{folder_path}（{exc}）"})
    defaults = build_tree_task_defaults(folder_path)
    task = {
        "id": hashlib.md5(("tree-task:" + folder_path).encode("utf-8")).hexdigest()[:16],
        "folder_path": folder_path,
        "tree_name": str(payload.get("tree_name", "") or "").strip() or defaults["tree_name"],
        # 前缀与排除层级由文件夹路径按解析规则自动推导，不接受手动覆盖。
        "prefix": defaults["prefix"],
        "exclude": defaults["exclude"],
        "last_remote_sha1": "",
        "last_local_md5": "",
    }
    conflict = find_tree_task_name_conflict(cfg, task["tree_name"], folder_path)
    if conflict:
        return JSONResponse(
            status_code=409,
            content={"ok": False, "msg": f"树文件名 {task['tree_name']} 已被其它任务使用，请改名"},
        )
    cfg.setdefault("tree_tasks", []).append(task)
    save_config(cfg)
    return {"ok": True, "task": task}


@router.delete("/tree/tasks/{task_id}")
async def delete_tree_task(task_id: str) -> Dict[str, Any]:
    cfg = get_config()
    normalized_id = str(task_id or "").strip()
    tasks = [t for t in cfg.get("tree_tasks", []) if str((t or {}).get("id", "") or "").strip() != normalized_id]
    if len(tasks) == len(cfg.get("tree_tasks", [])):
        return JSONResponse(status_code=404, content={"ok": False, "msg": "目录树任务不存在"})
    cfg["tree_tasks"] = tasks
    save_config(cfg)
    return {"ok": True}


@router.post("/tree/tasks/{task_id}")
async def update_tree_task(task_id: str, request: Request) -> Dict[str, Any]:
    data = await request.json()
    payload = data if isinstance(data, dict) else {}
    cfg = get_config()
    tasks = cfg.get("tree_tasks", [])
    task_index = next(
        (index for index, task in enumerate(tasks) if str((task or {}).get("id", "") or "").strip() == task_id),
        None,
    )
    if task_index is None:
        return JSONResponse(status_code=404, content={"ok": False, "msg": "目录树任务不存在"})
    current = dict(tasks[task_index] or {})
    folder_path = normalize_relative_path(
        str(payload.get("folder_path", "") or current.get("folder_path", "") or "").strip()
    )
    if not folder_path:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "文件夹路径不能为空"})
    cookie = str(cfg.get("cookie_115", "") or "").strip()
    if not cookie:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "请先在参数配置中填写 115 Cookie"})
    try:
        await asyncio.to_thread(resolve_115_folder_id_by_path, cookie, folder_path)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "msg": f"文件夹不存在或无法访问：{folder_path}（{exc}）"})
    defaults = build_tree_task_defaults(folder_path)
    updated = dict(current)
    updated["folder_path"] = folder_path
    raw_name = str(payload.get("tree_name", "") or "").strip()
    updated["tree_name"] = raw_name or defaults["tree_name"]
    # 前缀与排除层级由文件夹路径自动推导，不接受手动覆盖。
    updated["prefix"] = defaults["prefix"]
    updated["exclude"] = defaults["exclude"]
    conflict = find_tree_task_name_conflict(cfg, updated["tree_name"], folder_path)
    if conflict and str(conflict.get("id", "") or "").strip() != str(task_id or "").strip():
        return JSONResponse(
            status_code=409,
            content={"ok": False, "msg": f"树文件名 {updated['tree_name']} 已被其它任务使用，请改名"},
        )
    tasks[task_index] = updated
    cfg["tree_tasks"] = tasks
    save_config(cfg)
    return {"ok": True, "task": updated}


@router.post("/tree/tasks/{task_id}/run")
async def run_tree_task_endpoint(task_id: str) -> Dict[str, Any]:
    if task_status["running"]:
        return _tree_busy_response()
    submit_background(run_tree_task, str(task_id or "").strip(), False, label="tree-task-run")
    return {"ok": True, "status": "started"}


@router.post("/tree/tasks/{task_id}/full")
async def run_tree_task_full_endpoint(task_id: str) -> Dict[str, Any]:
    if task_status["running"]:
        return _tree_busy_response()
    submit_background(run_tree_task, str(task_id or "").strip(), True, label="tree-task-full")
    return {"ok": True, "status": "started"}


@router.post("/tree/sync-all")
async def sync_all_tree_tasks_endpoint(request: Request) -> Dict[str, Any]:
    if task_status["running"]:
        return _tree_busy_response()
    submit_background(run_sync, False, False, label="tree-sync-all")
    return {"ok": True, "status": "started"}


@router.get("/tree/jobs")
async def get_tree_jobs(request: Request) -> Dict[str, Any]:
    try:
        limit = max(1, min(200, int(request.query_params.get("limit", "30") or "30")))
    except (TypeError, ValueError):
        limit = 30
    jobs = await asyncio.to_thread(list_tree_export_jobs, limit)
    return {"ok": True, "jobs": jobs}


@router.get("/tree/logs")
async def get_logs(request: Request) -> Dict[str, Any]:
    compact = request.query_params.get("compact") == "1"
    return build_main_status_payload(log_limit=UI_STATUS_STREAM_LOG_TAIL_LIMIT if compact else UI_STATUS_LOG_TAIL_LIMIT)


@router.post("/tree/logs/clear")
async def clear_logs(request: Request) -> Dict[str, Any]:
    line = f"{format_log_time(True)} 系统日志已清空"
    task_status["logs"] = [{"text": line, "level": "info"}]
    await asyncio.to_thread(clear_log_file, MAIN_LOG_PATH, line)
    schedule_ui_state_push(0)
    return {"ok": True}
