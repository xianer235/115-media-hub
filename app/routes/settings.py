import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..config_runtime import build_public_settings_payload, merge_settings_preserve_sensitive
from ..core import *  # noqa: F401,F403
from ..services.notify import send_notify_test_message
from ..services.sign115 import refresh_sign115_status, run_sign115_job

router = APIRouter()


async def _run_postsave_health_checks() -> None:
    try:
        await refresh_cookie_health_status(
            providers=list(COOKIE_HEALTH_PROVIDERS),
            trigger="settings_save",
            force=True,
        )
    except Exception:
        pass
    try:
        await refresh_sign115_status(force_remote=False, trigger="settings_save")
    except Exception:
        pass
    schedule_ui_state_push(0)


@router.get("/get_settings")
async def get_settings_endpoint(request: Request) -> Dict[str, Any]:
    cfg = get_config()
    return build_public_settings_payload(cfg)


@router.get("/version")
async def get_version_endpoint(request: Request) -> Dict[str, Any]:
    force = request.query_params.get("refresh") == "1"
    return await get_version_state(force_refresh=force)


@router.post("/save_settings")
async def save_settings_endpoint(request: Request) -> Dict[str, Any]:
    incoming = await request.json()
    incoming_payload = incoming if isinstance(incoming, dict) else {}
    current_cfg = get_config()
    merged_cfg = merge_settings_preserve_sensitive(current_cfg, incoming_payload)
    raw_monitor_tasks = incoming_payload.get("monitor_tasks")
    raw_subscription_tasks = incoming_payload.get("subscription_tasks")
    monitor_tasks_payload = raw_monitor_tasks if isinstance(raw_monitor_tasks, list) else current_cfg.get("monitor_tasks", [])
    subscription_tasks_payload = (
        raw_subscription_tasks if isinstance(raw_subscription_tasks, list) else current_cfg.get("subscription_tasks", [])
    )
    merged_cfg["monitor_tasks"] = [
        normalize_task(task) for task in monitor_tasks_payload
    ]
    merged_cfg["subscription_tasks"] = [
        normalize_subscription_task(task)
        for task in subscription_tasks_payload
    ]
    save_config(merged_cfg)
    saved_cfg = get_config()
    if str(saved_cfg.get("cookie_115", "")).strip():
        mark_cookie_health_checking("115", trigger="settings_save")
    if str(saved_cfg.get("cookie_quark", "")).strip():
        mark_cookie_health_checking("quark", trigger="settings_save")
    cookie_health = build_cookie_health_payload(saved_cfg)
    schedule_ui_state_push(0)
    asyncio.create_task(_run_postsave_health_checks())
    return {"ok": True, "cookie_health": cookie_health, "checks_queued": True}


@router.get("/settings/cookies/status")
async def get_cookies_status(request: Request) -> Dict[str, Any]:
    force = request.query_params.get("refresh") == "1"
    payload = await refresh_cookie_health_status(
        providers=list(COOKIE_HEALTH_PROVIDERS),
        trigger="status_poll",
        force=force,
    )
    return {"ok": True, "cookie_health": payload}


@router.post("/settings/cookies/check")
async def check_cookies_status(request: Request) -> Dict[str, Any]:
    incoming = await request.json()
    payload = incoming if isinstance(incoming, dict) else {}
    providers = payload.get("providers", list(COOKIE_HEALTH_PROVIDERS))
    force = bool(payload.get("force", True))
    result = await refresh_cookie_health_status(
        providers=providers,
        trigger="manual_check",
        force=force,
    )
    return {"ok": True, "cookie_health": result}


@router.post("/settings/tg_proxy/test")
async def test_tg_proxy(request: Request) -> JSONResponse:
    incoming = await request.json()
    cfg = normalize_config(
        {
            **get_config(),
            "tg_proxy_enabled": incoming.get("tg_proxy_enabled", False),
            "tg_proxy_protocol": incoming.get("tg_proxy_protocol", "http"),
            "tg_proxy_host": incoming.get("tg_proxy_host", ""),
            "tg_proxy_port": incoming.get("tg_proxy_port", ""),
        }
    )
    try:
        result = await asyncio.to_thread(test_telegram_latency, cfg)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})
    return JSONResponse(content=result)


@router.post("/settings/notify/test")
async def test_notify_push(request: Request) -> JSONResponse:
    incoming = await request.json()
    incoming_payload = incoming if isinstance(incoming, dict) else {}
    merged_cfg = merge_settings_preserve_sensitive(
        get_config(),
        {
            "notify_push_enabled": incoming_payload.get("notify_push_enabled", False),
            "notify_monitor_enabled": incoming_payload.get("notify_monitor_enabled", False),
            "notify_channel": incoming_payload.get("notify_channel", "wecom_bot"),
            "notify_wecom_webhook": incoming_payload.get("notify_wecom_webhook", ""),
            "notify_wecom_app_corp_id": incoming_payload.get("notify_wecom_app_corp_id", ""),
            "notify_wecom_app_agent_id": incoming_payload.get("notify_wecom_app_agent_id", ""),
            "notify_wecom_app_secret": incoming_payload.get("notify_wecom_app_secret", ""),
            "notify_wecom_app_touser": incoming_payload.get("notify_wecom_app_touser", ""),
        },
    )
    cfg = normalize_config(merged_cfg)
    try:
        result = await asyncio.to_thread(send_notify_test_message, cfg)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})
    return JSONResponse(content=result)


@router.get("/settings/115/sign/status")
async def get_sign115_status(request: Request) -> Dict[str, Any]:
    refresh = request.query_params.get("refresh") == "1"
    await refresh_sign115_status(
        force_remote=refresh,
        trigger="manual_refresh" if refresh else "status_poll",
    )
    return {"ok": True, **build_sign115_status_payload()}


@router.post("/settings/115/sign/run")
async def run_sign115(request: Request) -> JSONResponse:
    result = await run_sign115_job("manual")
    if not result.get("ok", False):
        message = str(result.get("message", "") or result.get("msg", "") or "签到失败").strip() or "签到失败"
        return JSONResponse(status_code=400, content={"ok": False, "msg": message, "state": result})
    return JSONResponse(content={"ok": True, "state": result})
