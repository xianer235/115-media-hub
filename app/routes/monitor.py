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
from ..db import retry_sqlite_locked
from ..services.monitor import queue_monitor_dir_scan, queue_monitor_job
from ..services.quick_import import (
    build_quick_import_config,
    is_quick_import_savepath,
    validate_quick_import_config,
)
from ..services.resource import run_resource_job

router = APIRouter()
webhook_router = APIRouter()

USERSCRIPT_WEBHOOK_SOURCE = "userscript_webhook"
WEBHOOK_SIGNATURE_TTL_SECONDS = 10 * 60
webhook_used_nonce_cache: Dict[str, int] = {}


def _error_response(exc: Exception, status_code: int = 400) -> JSONResponse:
    message = str(exc or "") or "未知错误"
    return JSONResponse(status_code=status_code, content={"ok": False, "msg": message})


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


async def _create_userscript_magnet_job(
    cfg: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    savepath: str,
    monitor_task_name: str,
    log_label: str,
    task_delay_seconds: int = 0,
    extra: Optional[Dict[str, Any]] = None,
) -> JSONResponse:
    """按用户脚本 webhook 的入参创建一个磁力离线任务。

    ``/webhook/{task_name}``（绑定监控任务）与 ``/webhook/quick-import``（接收夹快捷导入）
    共用这段逻辑：去重口径、延时、日志与响应结构都保持一致。
    """
    normalized_savepath = normalize_relative_path(savepath)
    if not normalized_savepath:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "磁力任务缺少 savepath"})
    cookie_115 = str(cfg.get("cookie_115", "")).strip()
    if not cookie_115:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "请先在参数配置中填写 115 Cookie"})

    magnet_link = _extract_magnet_link(payload)
    if not magnet_link:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "msg": "该地址只接受磁力链接（magnet:?xt=...）"},
        )

    title = str(payload.get("title", "") or "").strip()
    sharetitle = normalize_relative_path(payload.get("sharetitle", ""))
    refresh_target_type = str(payload.get("refresh_target_type", "") or "").strip() or "file"
    parsed_delay = 0
    try:
        parsed_delay = max(0, int(payload.get("delayTime", 0) or 0))
    except Exception:
        parsed_delay = 0
    refresh_delay_seconds = parsed_delay if parsed_delay > 0 else max(0, int(task_delay_seconds or 0))
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
    existing = find_existing_resource_job(resource, normalized_savepath)
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

    job_extra: Dict[str, Any] = {
        "job_source": USERSCRIPT_WEBHOOK_SOURCE,
        "refresh_target_type": refresh_target_type,
    }
    if extra:
        job_extra.update(extra)
    job_id = create_resource_job(
        resource,
        {
            "folder_id": "",
            "savepath": normalized_savepath,
            "sharetitle": sharetitle,
            "monitor_task_name": monitor_task_name,
            "refresh_delay_seconds": refresh_delay_seconds,
            "auto_refresh": True,
            "extra": job_extra,
        },
    )
    submit_background(run_resource_job, job_id, label="resource-webhook-magnet")
    await write_monitor_log(
        f"Webhook 磁力任务已创建: {log_label} | job=#{job_id} | savepath={normalized_savepath} | delay={refresh_delay_seconds}s",
        "info",
    )
    if title:
        await write_monitor_log(f"Webhook 磁力标题：{title}", "info")
    return JSONResponse(
        content={
            "ok": True,
            "mode": "magnet",
            "job_id": job_id,
            "task_name": monitor_task_name,
            "savepath": normalized_savepath,
            "title": resource_title,
            "auto_refresh": True,
        }
    )


def _delete_monitor_runtime_records(task_name: str) -> None:
    def delete_records() -> None:
        conn = open_db()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM monitor_files WHERE task_name = ?", (task_name,))
            cursor.execute("DELETE FROM monitor_dirs WHERE task_name = ?", (task_name,))
            conn.commit()
        finally:
            conn.close()

    retry_sqlite_locked(delete_records)


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
    compact = request.query_params.get("compact") == "1"
    return build_monitor_status_payload(compact=compact)


@router.get("/monitor/manual-required")
async def get_manual_required_monitor_endpoint(request: Request) -> Dict[str, Any]:
    task_name = str(request.query_params.get("task_name", "") or "").strip()
    if not task_name:
        return {"ok": False, "items": [], "count": 0, "msg": "缺少任务名称"}
    try:
        from ..services.monitor_changes import get_manual_required_monitor_scopes

        items = await asyncio.to_thread(get_manual_required_monitor_scopes, task_name)
        return {"ok": True, "task_name": task_name, "items": items, "count": len(items)}
    except Exception as exc:
        return {"ok": False, "items": [], "count": 0, "msg": str(exc)}


@router.get("/monitor/logs/tasks")
async def get_monitor_log_tasks(request: Request) -> Dict[str, Any]:
    offset = max(0, int(request.query_params.get("offset", 0) or 0))
    limit = max(1, min(10, int(request.query_params.get("limit", MONITOR_UI_RECENT_TASK_LOG_LIMIT) or MONITOR_UI_RECENT_TASK_LOG_LIMIT)))
    page = build_monitor_log_segment_page(offset=offset, limit=limit, source="file")
    return {
        "ok": True,
        "segments": page["segments"],
        "total": page["total"],
        "offset": page["offset"],
        "limit": page["limit"],
        "has_more": page["has_more"],
        "next_offset": page["next_offset"],
    }


@router.post("/monitor/logs/clear")
async def clear_monitor_logs(request: Request) -> Dict[str, Any]:
    line = f"{format_log_time(True)} 监控日志已清空"
    entry = {"text": line, "level": "info"}
    monitor_status["logs"] = [entry]
    monitor_status["log_segment_total"] = 0
    monitor_status["log_segments"] = build_monitor_log_segments_from_entries([entry])
    await asyncio.to_thread(clear_log_file, MONITOR_LOG_PATH, line)
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


@router.post("/monitor/scan")
async def scan_monitor_dir(request: Request) -> Dict[str, Any]:
    data = await request.json()
    provider = str(data.get("provider", "115") or "115").strip()
    raw_paths = data.get("paths")
    if not isinstance(raw_paths, list) or not raw_paths:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "缺少扫描目录列表 paths"})
    try:
        result = await asyncio.to_thread(queue_monitor_dir_scan, get_config(), provider, raw_paths)
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"ok": False, "msg": str(exc)})
    except Exception as exc:
        return _error_response(exc)
    return result


@router.post("/monitor/stop")
async def stop_monitor(request: Request) -> Dict[str, Any]:
    data = await request.json()
    task_name = str(data.get("name", "")).strip()
    with monitor_queue_lock:
        queued_before = len(monitor_queue)
        monitor_queue[:] = [item for item in monitor_queue if item.get("task_name") != task_name]
        cleared_queued = max(0, queued_before - len(monitor_queue))
        if cleared_queued > 0:
            monitor_status["queued"] = [item["task_name"] for item in monitor_queue]
    if cleared_queued > 0:
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
    with monitor_queue_lock:
        monitor_queue[:] = [item for item in monitor_queue if item["task_name"] != task_name]
        monitor_status["queued"] = [item["task_name"] for item in monitor_queue]
    monitor_last_run.pop(task_name, None)
    monitor_next_run.pop(task_name, None)

    await asyncio.to_thread(_delete_monitor_runtime_records, task_name)
    schedule_ui_state_push(0)
    return {"ok": True}


@webhook_router.post("/webhook/quick-import")
async def webhook_quick_import(request: Request) -> JSONResponse:
    """面向「接收夹快捷导入」的独立 webhook：磁力直接投进接收夹。

    与 ``/webhook/{task_name}`` 完全独立——不需要监控任务、不改动按任务推送的既有行为。
    用户在油猴脚本里把请求地址填成本端点即可（保存路径由服务端配置的接收夹决定，
    脚本里那栏填接收夹路径或留空都行）。
    """
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
    quick_import_error = validate_quick_import_config(cfg)
    if quick_import_error:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "msg": f"接收夹快捷导入不可用：{quick_import_error}"},
        )

    verify_error = _verify_webhook_auth(request, cfg, body_text)
    if verify_error:
        await write_monitor_log(f"Webhook 校验失败: 接收夹快捷导入 | {verify_error}", "warn")
        return JSONResponse(status_code=401, content={"ok": False, "msg": verify_error})

    conf = build_quick_import_config(cfg)
    inbox_rel = str(conf.get("inbox_rel", "") or "").strip()
    requested_savepath = normalize_relative_path(payload.get("savepath", ""))
    if requested_savepath:
        # 脚本里可以填接收夹路径（含其子目录）；填了别的目录直接报错，避免"以为推到了 A 其实进了 B"。
        if not is_quick_import_savepath(cfg, requested_savepath):
            return JSONResponse(
                status_code=400,
                content={
                    "ok": False,
                    "msg": f"savepath 必须落在接收夹 {inbox_rel or '(未配置)'} 内，当前为 {requested_savepath}",
                },
            )
        savepath = requested_savepath
    else:
        savepath = inbox_rel

    return await _create_userscript_magnet_job(
        cfg,
        payload,
        savepath=savepath,
        monitor_task_name="",
        log_label="接收夹快捷导入",
        extra={
            "webhook_target": "quick-import",
            "quick_import_inbox": 1,
        },
    )


@webhook_router.post("/webhook/{task_name}")
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
        return await _create_userscript_magnet_job(
            cfg,
            payload,
            savepath=savepath,
            monitor_task_name=task_name,
            log_label=task_name,
            task_delay_seconds=max(0, int(task.get("delay_seconds", 0) or 0)),
            extra={"webhook_task_name": task_name},
        )

    queue_monitor_job(task_name, "webhook", payload)
    await write_monitor_log(
        f"Webhook 入队: {task_name} | savepath={savepath or '(未传)'} | sharetitle={sharetitle or '(空)'} | type={refresh_target_type or '(未传)'} | delayTime={payload.get('delayTime', 0)}",
        "info",
    )
    if title:
        await write_monitor_log(f"转存内容：{title}", "info")
    return JSONResponse(content=payload)
