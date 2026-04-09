import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..core import *  # noqa: F401,F403
from ..services.notify import send_notify_test_message
from ..services.sign115 import refresh_sign115_status, run_sign115_job

router = APIRouter()


@router.get("/get_settings")
async def get_settings_endpoint(request: Request) -> Dict[str, Any]:
    return get_config()


@router.get("/version")
async def get_version_endpoint(request: Request) -> Dict[str, Any]:
    force = request.query_params.get("refresh") == "1"
    return await get_version_state(force_refresh=force)


@router.post("/save_settings")
async def save_settings_endpoint(request: Request) -> Dict[str, Any]:
    incoming = await request.json()
    cfg = get_config()
    cfg.update(incoming)
    cfg["monitor_tasks"] = [normalize_task(task) for task in incoming.get("monitor_tasks", cfg.get("monitor_tasks", []))]
    cfg["subscription_tasks"] = [
        normalize_subscription_task(task) for task in incoming.get("subscription_tasks", cfg.get("subscription_tasks", []))
    ]
    save_config(cfg)
    await refresh_sign115_status(force_remote=False, trigger="settings_save")
    schedule_ui_state_push(0)
    return {"ok": True}


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
    cfg = normalize_config(
        {
            **get_config(),
            "notify_push_enabled": incoming.get("notify_push_enabled", False),
            "notify_monitor_enabled": incoming.get("notify_monitor_enabled", False),
            "notify_channel": incoming.get("notify_channel", "wecom_bot"),
            "notify_wecom_webhook": incoming.get("notify_wecom_webhook", ""),
            "notify_wecom_app_corp_id": incoming.get("notify_wecom_app_corp_id", ""),
            "notify_wecom_app_agent_id": incoming.get("notify_wecom_app_agent_id", ""),
            "notify_wecom_app_secret": incoming.get("notify_wecom_app_secret", ""),
            "notify_wecom_app_touser": incoming.get("notify_wecom_app_touser", ""),
        }
    )
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
