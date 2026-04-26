import asyncio
import hashlib
import hmac
import json
import time
import urllib.parse

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..background import submit_background
from ..core import *  # noqa: F401,F403
from ..services.monitor import queue_monitor_job
from ..services.resource import run_resource_job

router = APIRouter()

USERSCRIPT_WEBHOOK_SOURCE = "userscript_webhook"
WEBHOOK_SIGNATURE_TTL_SECONDS = 10 * 60
webhook_used_nonce_cache: Dict[str, int] = {}


def _cleanup_webhook_nonce_cache(now_ts: int) -> None:
    expire_before = now_ts - WEBHOOK_SIGNATURE_TTL_SECONDS
    for key in list(webhook_used_nonce_cache.keys()):
        if int(webhook_used_nonce_cache.get(key, 0) or 0) < expire_before:
            webhook_used_nonce_cache.pop(key, None)


def _verify_webhook_auth(request: Request, cfg: Dict[str, Any], body_text: str) -> str:
    secret = str(cfg.get("webhook_secret", "")).strip()
    if not secret:
        return ""

    token_header = str(request.headers.get("X-Webhook-Token", "") or "").strip()
    if token_header:
        if hmac.compare_digest(token_header, secret):
            return ""
        return "X-Webhook-Token 校验失败"

    ts_text = str(request.headers.get("X-Webhook-Ts", "") or "").strip()
    nonce = str(request.headers.get("X-Webhook-Nonce", "") or "").strip()
    sign = str(request.headers.get("X-Webhook-Sign", "") or "").strip().lower()
    if not ts_text or not nonce or not sign:
        return "缺少签名头（X-Webhook-Ts / X-Webhook-Nonce / X-Webhook-Sign）"
    if not re.fullmatch(r"\d{10,13}", ts_text):
        return "X-Webhook-Ts 格式不正确"
    if not re.fullmatch(r"[0-9a-f]{64}", sign):
        return "X-Webhook-Sign 格式不正确"

    ts_value = int(ts_text)
    ts_seconds = ts_value // 1000 if ts_value > 10**11 else ts_value
    now_ts = int(time.time())
    if abs(now_ts - ts_seconds) > WEBHOOK_SIGNATURE_TTL_SECONDS:
        return "Webhook 签名已过期"

    nonce_key = f"{ts_text}:{nonce}"
    _cleanup_webhook_nonce_cache(now_ts)
    if nonce_key in webhook_used_nonce_cache:
        return "Webhook 签名已被使用"

    signature_base = f"{ts_text}.{nonce}.{body_text}"
    expected_sign = hmac.new(secret.encode("utf-8"), signature_base.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_sign, sign):
        return "Webhook 签名校验失败"

    webhook_used_nonce_cache[nonce_key] = now_ts
    return ""


def _extract_magnet_link(payload: Dict[str, Any]) -> str:
    for key in ("magnet", "link_url", "url", "link"):
        link = str(payload.get(key, "") or "").strip()
        if link and detect_resource_link_type(link) == "magnet":
            return link
    return ""


def _delete_monitor_runtime_records(task_name: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM monitor_files WHERE task_name = ?", (task_name,))
    cursor.execute("DELETE FROM monitor_dirs WHERE task_name = ?", (task_name,))
    conn.commit()
    conn.close()


def _resolve_magnet_title(payload: Dict[str, Any], magnet_link: str) -> str:
    title = normalize_resource_title(str(payload.get("title", "") or "").strip())
    if title:
        return title
    try:
        parsed = urllib.parse.urlparse(magnet_link)
        name = urllib.parse.parse_qs(parsed.query).get("dn", [""])[0]
        parsed_title = normalize_resource_title(urllib.parse.unquote_plus(str(name or "")))
        if parsed_title:
            return parsed_title
    except Exception:
        pass
    return "磁力离线任务"


def _build_userscript_job_counts(jobs: List[Dict[str, Any]]) -> Dict[str, int]:
    statuses = [str(job.get("status", "") or "").strip().lower() for job in jobs]
    return {
        "total": len(jobs),
        "active": sum(1 for status in statuses if status in ("pending", "running", "submitted")),
        "submitted": sum(1 for status in statuses if status == "submitted"),
        "completed": sum(1 for status in statuses if status == "completed"),
        "failed": sum(1 for status in statuses if status == "failed"),
    }


@router.get("/monitor/userscript/jobs")
async def list_monitor_userscript_jobs(request: Request) -> Dict[str, Any]:
    limit = max(1, min(int(request.query_params.get("limit", 60) or 60), 120))
    jobs = list_resource_jobs_by_source(
        USERSCRIPT_WEBHOOK_SOURCE,
        limit=limit,
        scan_limit=max(200, limit * 5),
    )
    return {
        "ok": True,
        "jobs": jobs,
        "counts": _build_userscript_job_counts(jobs),
    }


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
    queued_before = len(monitor_queue)
    monitor_queue[:] = [item for item in monitor_queue if item.get("task_name") != task_name]
    cleared_queued = max(0, queued_before - len(monitor_queue))
    if cleared_queued > 0:
        monitor_status["queued"] = [item["task_name"] for item in monitor_queue]
        schedule_ui_state_push(0)

    if monitor_status["running"] and monitor_status["current_task"] == task_name:
        monitor_control["cancel"] = True
        status = "stopping_and_cleared" if cleared_queued > 0 else "stopping"
        return {"ok": True, "status": status, "cleared": cleared_queued}

    if cleared_queued > 0:
        return {"ok": True, "status": "cleared", "cleared": cleared_queued}
    return {"ok": False, "status": "idle", "cleared": 0}


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

    await asyncio.to_thread(_delete_monitor_runtime_records, task_name)
    schedule_ui_state_push(0)
    return {"ok": True}


@router.post("/webhook/{task_name}")
async def webhook(task_name: str, request: Request) -> JSONResponse:
    body_bytes = await request.body()
    body_text = body_bytes.decode("utf-8", errors="replace")
    if not body_text.strip():
        return JSONResponse(status_code=400, content={"ok": False, "msg": "请求体不能为空"})
    try:
        payload = json.loads(body_text)
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "请求体必须是 JSON"})
    if not isinstance(payload, dict):
        return JSONResponse(status_code=400, content={"ok": False, "msg": "请求体必须是 JSON 对象"})

    cfg = get_config()
    task = next((task for task in cfg["monitor_tasks"] if task["name"] == task_name), None)
    if not task:
        return JSONResponse(status_code=404, content={"ok": False, "msg": "未找到对应监控任务"})
    if not task.get("webhook_enabled"):
        return JSONResponse(status_code=400, content={"ok": False, "msg": "该任务未开启 webhook"})

    verify_error = _verify_webhook_auth(request, cfg, body_text)
    if verify_error:
        await write_monitor_log(f"Webhook 校验失败: {task_name} | {verify_error}", "warn")
        return JSONResponse(status_code=401, content={"ok": False, "msg": verify_error})

    title = str(payload.get("title", "") or "").strip()
    savepath = normalize_relative_path(payload.get("savepath", ""))
    sharetitle = normalize_relative_path(payload.get("sharetitle", ""))
    refresh_target_type = str(payload.get("refresh_target_type", "") or "").strip()
    magnet_link = _extract_magnet_link(payload)

    if magnet_link:
        if not refresh_target_type:
            refresh_target_type = "file"
        cookie_115 = str(cfg.get("cookie_115", "")).strip()
        if not cookie_115:
            return JSONResponse(status_code=400, content={"ok": False, "msg": "请先在参数配置中填写 115 Cookie"})
        if not savepath:
            return JSONResponse(status_code=400, content={"ok": False, "msg": "磁力任务缺少 savepath"})

        parsed_delay = 0
        try:
            parsed_delay = max(0, int(payload.get("delayTime", 0) or 0))
        except Exception:
            parsed_delay = 0
        refresh_delay_seconds = parsed_delay if parsed_delay > 0 else max(0, int(task.get("delay_seconds", 0) or 0))
        resource_title = _resolve_magnet_title(payload, magnet_link)
        resource = sanitize_resource_job_input(
            {
                "source_type": "webhook",
                "source_name": "userscript",
                "channel_name": "",
                "title": resource_title,
                "raw_text": f"{resource_title}\n{magnet_link}",
                "link_url": magnet_link,
                "link_type": "magnet",
                "message_url": "",
                "extra": {},
            }
        )
        existing = find_existing_resource_job(resource, savepath)
        if existing:
            existing_status = str(existing.get("status", "")).strip().lower()
            if existing_status == "completed":
                msg = "该磁力已添加过。若需重新导入，请先清空“已完成导入记录”后再试。"
            else:
                msg = "该磁力已在处理中，请勿重复提交。"
            return JSONResponse(
                status_code=409,
                content={
                    "ok": False,
                    "msg": msg,
                    "job_id": existing.get("id", 0),
                    "status": existing_status,
                },
            )

        job_id = create_resource_job(
            resource,
            {
                "folder_id": "",
                "savepath": savepath,
                "sharetitle": sharetitle,
                "monitor_task_name": task_name,
                "refresh_delay_seconds": refresh_delay_seconds,
                "auto_refresh": True,
                "extra": {
                    "job_source": USERSCRIPT_WEBHOOK_SOURCE,
                    "webhook_task_name": task_name,
                    "refresh_target_type": refresh_target_type,
                },
            },
        )
        submit_background(run_resource_job, job_id, label="resource-webhook-magnet")
        await write_monitor_log(
            f"Webhook 磁力任务已创建: {task_name} | job=#{job_id} | savepath={savepath} | delay={refresh_delay_seconds}s",
            "info",
        )
        if title:
            await write_monitor_log(f"Webhook 磁力标题：{title}", "info")
        return JSONResponse(
            content={
                "ok": True,
                "mode": "magnet",
                "job_id": job_id,
                "task_name": task_name,
                "savepath": savepath,
                "title": resource_title,
                "auto_refresh": True,
            }
        )

    queue_monitor_job(task_name, "webhook", payload)
    await write_monitor_log(
        f"Webhook 入队: {task_name} | savepath={savepath or '(未传)'} | sharetitle={sharetitle or '(空)'} | type={refresh_target_type or '(未传)'} | delayTime={payload.get('delayTime', 0)}",
        "info",
    )
    if title:
        await write_monitor_log(f"转存内容：{title}", "info")
    return JSONResponse(content=payload)
