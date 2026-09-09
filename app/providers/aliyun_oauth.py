"""阿里云盘 Open API OAuth 2.0 + PKCE 扫码授权（内置，无需第三方站点）。

官方文档：
    - https://www.yuque.com/aliyundrive/zpfszx/eam8ls1lmawwwksv （公开客户端 + PKCE）
    - https://www.yuque.com/aliyundrive/zpfszx/efabcs          （access_token / refresh_token）

公开客户端模式（无 AppSecret），配合 redirect_uri=oob 可免公网回调服务器：
    1. 后端生成 PKCE verifier/challenge 并返回 authorize URL 与 code_verifier
    2. 前端打开 authorize URL（页面含二维码），用户用阿里云盘 App 扫码授权
    3. 页面跳转到 oob 并展示授权码 code（10 分钟、一次性）
    4. 前端把 code + 同一 code_verifier 回传，后端换取 refresh_token 并保存

注意：本模块使用的是社区公开的"阿里云盘网页版" client_id，code/refresh_token 只在本机
后端流转，不经过任何第三方。code_verifier 按 PKCE 公开客户端模式由调用方（本机前端）持有。
"""
import json
import secrets
import urllib.error
from typing import Any, Dict
from urllib.parse import parse_qs, quote, urlparse

from ..http_utils import http_request_form_json


ALIYUN_OPEN_AUTHORIZE_URL = "https://openapi.alipan.com/oauth/authorize"
ALIYUN_OPEN_TOKEN_URL = "https://openapi.alipan.com/oauth/access_token"
ALIYUN_OPEN_SCOPE = "user:base"
ALIYUN_OPEN_REDIRECT_URI = "oob"
# 阿里云盘"网页版"公开客户端 ID（无后端公开客户端 + PKCE，无需 secret）
ALIYUN_OPEN_CLIENT_ID = "55091393987b4cc090b090ee17e85e0a"

def _generate_pkce_pair() -> Dict[str, str]:
    """生成 PKCE code_verifier / code_challenge。

    阿里云盘公开客户端文档将 code_challenge 描述为"43-128 的随机字符串"，
    code_verifier 为其原始值而非摘要值，即使用 **plain** 模式（challenge=verifier）。
    """
    verifier = secrets.token_urlsafe(48)  # 64 字符，落在 43-128 合法区间
    return {"code_verifier": verifier, "code_challenge": verifier}


def _normalize_authorization_code(code: str) -> str:
    """把用户粘贴的内容规整成真正的授权码。

    授权回调（redirect_uri=oob）成功后，页面地址形如 `oob?code=xxxx`。
    用户容易整段复制地址而不是只复制 code 值，这里做一次宽容解析：
    仅当确实包含 code= 查询参数时才从中抽取，否则原样返回（去掉首尾空白）。
    """
    raw = str(code or "").strip()
    if "code=" not in raw:
        return raw
    # 用占位协议避免 urlparse 对裸 `oob?code=...` 解析成路径带 query 的情况
    parsed = urlparse("https://alipan.local/" + raw.lstrip("/"))
    values = parse_qs(parsed.query).get("code")
    if values and values[0].strip():
        return values[0].strip()
    # 解析不到就退回原来的值，避免误判
    return raw


def _is_code_not_found_detail(detail: str) -> bool:
    lowered = str(detail or "").lower()
    return "code not found" in lowered or "invalidcode" in lowered.replace("_", "")

def create_aliyun_oauth_session() -> Dict[str, str]:
    """生成一次授权，返回 state、官方授权地址（含二维码）与随行的 code_verifier。"""
    pkce = _generate_pkce_pair()
    state = secrets.token_urlsafe(16)
    authorize_url = (
        f"{ALIYUN_OPEN_AUTHORIZE_URL}"
        f"?client_id={quote(ALIYUN_OPEN_CLIENT_ID)}"
        f"&redirect_uri={quote(ALIYUN_OPEN_REDIRECT_URI)}"
        f"&scope={quote(ALIYUN_OPEN_SCOPE)}"
        f"&response_type=code"
        f"&code_challenge={quote(pkce['code_challenge'])}"
        f"&code_challenge_method=plain"
        f"&state={quote(state)}"
    )
    return {"state": state, "authorize_url": authorize_url, "code_verifier": pkce["code_verifier"]}


def _read_http_error_detail(exc: urllib.error.HTTPError) -> str:
    """从 HTTPError 响应体中尽量提取阿里云盘返回的错误详情。"""
    try:
        raw = exc.read()
    except Exception:
        return str(exc)
    try:
        body = json.loads(raw.decode("utf-8", errors="ignore"))
    except Exception:
        body = None
    if isinstance(body, dict):
        message = (
            body.get("message")
            or body.get("error_description")
            or body.get("error")
            or body.get("msg")
        )
        if message:
            return str(message)
    return (raw or b"").decode("utf-8", errors="ignore")[:300] or str(exc)


def exchange_aliyun_code(code: str, code_verifier: str) -> Dict[str, Any]:
    """用授权码 + 同一 code_verifier 换取访问凭证，返回完整 token 包。

    阿里云盘“公开客户端（无 AppSecret）”模式返回的是 30 天有效期的 access_token，
    且**不支持刷新**（授权码换取的响应不含 refresh_token）。因此本函数返回整个 token
    响应字典，由调用方提取 access_token；若个别客户端确实返回了 refresh_token，也会带上。

    成功返回形如 {"access_token": ..., "expires_in": ..., "refresh_token": "", ...} 的字典；
    失败抛出 RuntimeError（含官方错误消息）。
    """
    normalized_code = _normalize_authorization_code(code)
    if not normalized_code:
        raise RuntimeError("缺少授权码")
    verifier = str(code_verifier or "").strip()
    if not verifier:
        raise RuntimeError("缺少 code_verifier")
    form_data = {
        "client_id": ALIYUN_OPEN_CLIENT_ID,
        "grant_type": "authorization_code",
        "code": normalized_code,
        "redirect_uri": ALIYUN_OPEN_REDIRECT_URI,
        "code_verifier": verifier,
    }
    try:
        resp = http_request_form_json(ALIYUN_OPEN_TOKEN_URL, form_data, timeout=20)
    except urllib.error.HTTPError as exc:
        detail = _read_http_error_detail(exc)
        message = f"阿里云盘换取 refresh_token 失败（HTTP {exc.code}）：{detail}"
        if _is_code_not_found_detail(detail):
            message += (
                "——授权码 10 分钟内有效且只能用一次，可能已过期或被前面的请求占用。"
                "请重新点击“获取授权码”，扫码后立即复制新授权码粘贴。"
            )
        raise RuntimeError(message) from None
    except Exception as exc:
        raise RuntimeError(f"阿里云盘换取 refresh_token 请求失败：{exc}") from None
    token_bundle = resp if isinstance(resp, dict) else {}
    access_token = str(token_bundle.get("access_token", "") or "").strip()
    refresh_token = str(token_bundle.get("refresh_token", "") or "").strip()
    if not access_token and not refresh_token:
        message = str(
            token_bundle.get("message", "")
            or token_bundle.get("error_description", "")
            or token_bundle.get("error", "")
            or (
                "响应缺少 access_token（公开客户端授权不返回 refresh_token，请检查授权码是否有效）"
            )
        ).strip()
        raise RuntimeError(f"阿里云盘换取 refresh_token 失败: {message}")
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": int(token_bundle.get("expires_in", 2592000) or 2592000),
        "token_type": str(token_bundle.get("token_type", "") or "Bearer"),
        "user_id": str(token_bundle.get("user_id", "") or "").strip(),
        "default_drive_id": str(token_bundle.get("default_drive_id", "") or "").strip(),
    }


def build_aliyun_refresh_payload(refresh_token: str) -> Dict[str, Any]:
    """构造官方便携端点使用的 refresh_token 刷新载荷。"""
    return {
        "client_id": ALIYUN_OPEN_CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": str(refresh_token or "").strip(),
    }
