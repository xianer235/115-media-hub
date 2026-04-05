import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..core import *  # noqa: F401,F403

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
