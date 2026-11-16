"""极影视 → Seerr 的 Emby 兼容桥路由。

挂载在 ``/emby-bridge`` 前缀下，**不走面板登录会话**（与 servarr 层同款），
对 Seerr 侧完全透明。所有请求收进一个兜底路由，交给
``app/services/emby_bridge.handle`` 翻译后转发极影视。
"""

import json
from typing import Any, Dict

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from ..services import emby_bridge

router = APIRouter(prefix="/emby-bridge", tags=["emby-bridge"])

_METHODS = ["GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "PATCH"]


@router.api_route("/{path:path}", methods=_METHODS)
async def emby_bridge_forward(request: Request, path: str) -> Response:
    """兜底路由：收下所有 /emby-bridge/* 请求并转发。"""
    method = request.method
    query = request.url.query
    headers: Dict[str, str] = {}
    for key, value in request.headers.items():
        headers[key] = value

    client_host = request.client.host if request.client else ""
    headers["X-Bridge-Client-Host"] = client_host

    body = b""
    if method in ("POST", "PUT", "PATCH"):
        body = await request.body()

    status, resp_headers, payload = await emby_bridge.handle(method, path, query, headers, body)

    # HEAD 请求不带 body
    if method == "HEAD":
        return Response(status_code=status, headers=resp_headers)

    if isinstance(payload, (dict, list)):
        return JSONResponse(
            status_code=status,
            content=payload,
            headers={k: v for k, v in resp_headers.items() if k.lower() != "content-type"},
        )
    if isinstance(payload, str):
        return Response(
            status_code=status,
            content=payload,
            headers=resp_headers,
            media_type="application/json",
        )
    # 纯透传（理论上 handle 返回的都是 JSON，此处兜底）
    return Response(status_code=status, headers=resp_headers)
