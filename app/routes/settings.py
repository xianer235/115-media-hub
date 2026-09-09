import asyncio
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from ..background import submit_background
from ..config_runtime import build_public_settings_payload, merge_settings_preserve_sensitive
from ..core import *  # noqa: F401,F403
from ..http_utils import http_request_bytes
from ..providers.registry import get_or_none as _get_provider_or_none
from ..providers.aliyun_oauth import create_aliyun_oauth_session, exchange_aliyun_code
from ..providers.pan115_qr import (
    build_115_qrcode_image_url,
    get_115_qr_apps,
    get_115_qr_default_app,
    get_115_qrcode_status,
    get_115_qrcode_token,
    normalize_115_qr_app,
    post_115_qrcode_result,
)
from ..services.notify import send_notify_test_message
from ..services.sign115 import refresh_sign115_status, run_sign115_job

router = APIRouter()


async def _run_postsave_health_checks() -> None:
    try:
        await refresh_cookie_health_status(
            providers=list(get_enabled_cookie_health_providers()),
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
    for provider_name in get_enabled_cookie_health_providers(saved_cfg):
        p = _get_provider_or_none(provider_name)
        if p and p.is_configured(saved_cfg):
            mark_cookie_health_checking(provider_name, trigger="settings_save")
    cookie_health = build_cookie_health_payload(saved_cfg)
    schedule_ui_state_push(0)
    submit_background(_run_postsave_health_checks, label="postsave-health-checks")
    return {"ok": True, "cookie_health": cookie_health, "checks_queued": True}


@router.get("/settings/cookies/status")
async def get_cookies_status(request: Request) -> Dict[str, Any]:
    force = request.query_params.get("refresh") == "1"
    payload = await refresh_cookie_health_status(
        providers=list(get_enabled_cookie_health_providers()),
        trigger="status_poll",
        force=force,
    )
    return {"ok": True, "cookie_health": payload}


@router.post("/settings/cookies/check")
async def check_cookies_status(request: Request) -> Dict[str, Any]:
    incoming = await request.json()
    payload = incoming if isinstance(incoming, dict) else {}
    providers = payload.get("providers", list(get_enabled_cookie_health_providers()))
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


@router.post("/settings/pansou/test")
async def test_pansou(request: Request) -> JSONResponse:
    incoming = await request.json()
    incoming_payload = incoming if isinstance(incoming, dict) else {}
    cfg = normalize_config(merge_settings_preserve_sensitive(get_config(), incoming_payload))
    try:
        result = await asyncio.to_thread(test_pansou_health, cfg)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})
    status_code = 200 if result.get("ok") else 400
    return JSONResponse(status_code=status_code, content=result)


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


@router.get("/api/providers")
async def get_providers(request: Request) -> JSONResponse:
    cfg = get_config()
    return JSONResponse(get_all_capabilities(cfg))


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
    cfg = get_config()
    if not str(cfg.get("cookie_115", "")).strip():
        state = build_sign115_status_payload(cfg)
        return JSONResponse(status_code=400, content={"ok": False, "msg": "请先配置 115 Cookie", "state": state})
    if sign115_runtime.get("running"):
        return JSONResponse(content={"ok": True, "queued": True, "state": build_sign115_status_payload(cfg)})
    set_sign115_status(state="checking", message="签到任务已提交，正在后台执行...", last_trigger="manual")
    submit_background(run_sign115_job, "manual", label="sign115-manual")
    return JSONResponse(content={"ok": True, "queued": True, "state": build_sign115_status_payload(cfg)})


@router.post("/test_provider_cookie")
async def test_provider_cookie(request: Request) -> JSONResponse:
    try:
        data = await request.json()
        provider_name = str(data.get("provider", "")).strip()
        cookie = str(data.get("cookie", "")).strip()
        credentials = data.get("credentials", {})
        credentials_payload = credentials if isinstance(credentials, dict) else {}

        if not provider_name:
            return JSONResponse(content={"ok": False, "error": "缺少provider"})

        provider = _get_provider_or_none(provider_name)
        if not provider:
            return JSONResponse(content={"ok": False, "error": f"未知的网盘: {provider_name}"})

        try:
            credential_value = cookie
            if credentials_payload:
                probe_cfg = {
                    key: str(credentials_payload.get(key, "") or "").strip()
                    for key in getattr(provider, "config_keys", [])
                }
                if not provider.is_configured(probe_cfg):
                    return JSONResponse(content={"ok": False, "error": f"缺少 {provider.label} 认证信息"})
                credential_value = await asyncio.to_thread(provider.get_cookie, probe_cfg)

            if not credential_value:
                return JSONResponse(content={"ok": False, "error": f"缺少 {provider.label} 认证信息"})

            ok = await asyncio.to_thread(provider.probe_connectivity, credential_value)
            if ok:
                return JSONResponse(content={"ok": True, "message": f"{provider.label} 认证信息可用"})
            else:
                return JSONResponse(content={"ok": False, "error": f"{provider.label} 连接检测失败，请检查认证信息是否有效"})
        except Exception as e:
            error_msg = str(e).strip()
            return JSONResponse(content={"ok": False, "error": error_msg or "认证失败"})
    except Exception as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})


@router.get("/settings/providers/115/qrcode/apps")
async def get_115_qrcode_apps_endpoint(request: Request) -> Dict[str, Any]:
    """返回 115 扫码可选的客户端列表（含推荐/默认标记）。"""
    return {"ok": True, "apps": get_115_qr_apps(), "default": get_115_qr_default_app()}


@router.get("/settings/providers/115/qrcode/token")
async def get_115_qrcode_token_endpoint(request: Request) -> JSONResponse:
    """第一步：获取 115 扫码二维码 token 及透传用的图片地址。"""
    try:
        data = await asyncio.to_thread(get_115_qrcode_token)
        uid = str(data.get("uid", "") or "").strip()
        return JSONResponse(content={
            "ok": True,
            "uid": uid,
            "time": data.get("time", ""),
            "sign": data.get("sign", ""),
            "image_url": build_115_qrcode_image_url(uid),
        })
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})


@router.get("/settings/providers/115/qrcode/image")
async def get_115_qrcode_image_endpoint(request: Request) -> Response:
    """透传 115 官方二维码图片（避免前端直连 115 被 CORS 拦）。"""
    uid = request.query_params.get("uid", "").strip()
    if not uid:
        return JSONResponse(status_code=400, content={"ok": False, "error": "缺少 uid"})
    try:
        content = await asyncio.to_thread(
            http_request_bytes,
            build_115_qrcode_image_url(uid),
            20,
            {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
        )
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})
    return Response(content=content, media_type="image/png")


@router.get("/settings/providers/115/qrcode/status")
async def get_115_qrcode_status_endpoint(request: Request) -> JSONResponse:
    """第二步：轮询扫码状态。status: 0等待 1已扫 2已登录 -1过期 -2取消。"""
    uid = request.query_params.get("uid", "").strip()
    time = request.query_params.get("time", "")
    sign = request.query_params.get("sign", "")
    if not uid or not time or not sign:
        return JSONResponse(content={"ok": False, "error": "缺少二维码参数"})
    try:
        status = await asyncio.to_thread(get_115_qrcode_status, uid, time, sign)
        return JSONResponse(content={"ok": True, "status": status})
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})


@router.post("/settings/providers/115/qrcode/result")
async def post_115_qrcode_result_endpoint(request: Request) -> JSONResponse:
    """第三步：扫码成功后绑定设备、写入 cookie_115 并触发健康检查。"""
    try:
        incoming = await request.json()
    except Exception:
        incoming = {}
    payload = incoming if isinstance(incoming, dict) else {}
    uid = str(payload.get("uid", "") or "").strip()
    app = str(payload.get("app", "") or "").strip()
    if not uid:
        return JSONResponse(content={"ok": False, "error": "缺少 uid"})
    try:
        cookie = await asyncio.to_thread(post_115_qrcode_result, uid, app)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})

    cfg = get_config()
    cfg["cookie_115"] = cookie
    save_config(cfg)
    mark_cookie_health_checking("115", trigger="qrcode_login")
    submit_background(_run_postsave_health_checks, label="postsave-health-checks")
    return JSONResponse(content={
        "ok": True,
        "app": normalize_115_qr_app(app),
        "message": "扫码成功，已绑定并保存 Cookie",
    })


@router.get("/settings/providers/aliyun/oauth/start")
async def get_aliyun_oauth_start(request: Request) -> JSONResponse:
    """生成阿里云盘官方授权会话，返回 state 与授权地址（页面含扫码二维码）。"""
    try:
        session = create_aliyun_oauth_session()
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})
    return JSONResponse(content={
        "ok": True,
        "state": session["state"],
        "authorize_url": session["authorize_url"],
        "code_verifier": session["code_verifier"],
    })


@router.post("/settings/providers/aliyun/oauth/complete")
async def post_aliyun_oauth_complete(request: Request) -> JSONResponse:
    """用授权码换取访问凭证（公开客户端返回长期 access_token），写入配置并做一次连接检测。"""
    try:
        incoming = await request.json()
    except Exception:
        incoming = {}
    payload = incoming if isinstance(incoming, dict) else {}
    state = str(payload.get("state", "") or "").strip()
    code = str(payload.get("code", "") or "").strip()
    code_verifier = str(payload.get("code_verifier", "") or "").strip()
    if not state or not code or not code_verifier:
        return JSONResponse(content={"ok": False, "error": "缺少 state/code/code_verifier"})
    try:
        token_bundle = await asyncio.to_thread(exchange_aliyun_code, code, code_verifier)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(exc), "message": str(exc)})

    access_token = str(token_bundle.get("access_token", "") or "").strip()
    refresh_token = str(token_bundle.get("refresh_token", "") or "").strip()
    if not access_token and not refresh_token:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "error": "授权成功但响应缺少 access_token（公开客户端不返回 refresh_token）",
                "message": "授权成功但响应缺少 access_token（公开客户端不返回 refresh_token）",
            },
        )

    cfg = get_config()
    if access_token:
        # 公开客户端：30 天有效期、不支持刷新，直接存为令牌并按 access_token 模式使用
        expires_in = int(token_bundle.get("expires_in", 2592000) or 2592000)
        cfg["aliyun_refresh_token"] = access_token
        cfg["aliyun_token_is_access"] = True
        cfg["aliyun_access_expires_at"] = time.time() + expires_in
    else:
        cfg["aliyun_refresh_token"] = refresh_token
        cfg["aliyun_token_is_access"] = False
        cfg["aliyun_access_expires_at"] = 0
    save_config(cfg)

    provider = _get_provider_or_none("aliyun")
    probe_ok = False
    if provider is not None:
        try:
            probe_ok = await asyncio.to_thread(
                provider.probe_connectivity, access_token or refresh_token
            )
        except Exception:
            probe_ok = False

    submit_background(_run_postsave_health_checks, label="postsave-health-checks")
    return JSONResponse(content={
        "ok": True,
        "probe_ok": probe_ok,
        "message": "阿里云盘授权成功，已保存访问凭证" + ("，连接检测成功" if probe_ok else "，连接检测失败，请检查"),
    })


@router.get("/settings/providers/{provider}/credential")
async def get_provider_credential(provider: str) -> JSONResponse:
    """回显某网盘已保存的凭证（Cookie / access_token），便于复制到其它应用。

    仅返回该 provider 的 config_keys 中非空值；主凭证取第一个非空 config_key
    （按 get_cookie 的约定）。该路由挂载在 settings_router 下，受 require_auth 保护。
    """
    prov = _get_provider_or_none(provider)
    if prov is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": "未知网盘"})

    cfg = get_config()
    keys = list(prov.config_keys or []) or [f"cookie_{prov.name}"]
    credentials: Dict[str, str] = {}
    for key in keys:
        value = str(cfg.get(key, "") or "").strip()
        if value:
            credentials[key] = value

    primary_key = ""
    primary_value = ""
    for key in keys:
        if key in credentials:
            primary_key = key
            primary_value = credentials[key]
            break

    return JSONResponse(content={
        "ok": True,
        "provider": provider,
        "label": prov.label,
        "configured": bool(credentials),
        "credential_key": primary_key,
        "credential": primary_value,
        "credentials": credentials,
    })
