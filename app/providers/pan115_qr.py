"""115 网盘扫码登录（客户端/设备选择）的实现。

扫码流程为三步（与 AList / 115driver 等成熟项目一致的第三方反向接口）：
    1. GET  qrcodeapi.115.com/api/1.0/web/1.0/token/           -> uid/time/sign + 二维码内容
    2. GET  qrcodeapi.115.com/get/status/?uid=&time=&sign=     -> 轮询扫码状态
    3. POST passportapi.115.com/app/1.0/{app}/1.0/login/qrcode/ -> 换取对应设备 cookie

接口属于非官方，可能被 115 调整或被风控拦截；扫码失败时应回退到手动粘贴 Cookie。
"""
from typing import Any, Dict, List
from urllib.parse import quote, urlencode

from ..http_utils import http_request_form_json, http_request_json


# 可选的扫码客户端（app/device）。剔除已被官方下架的 linux/mac/windows。
# 默认与推荐使用冷门设备（微信/支付宝小程序、电视端），避免把用户现有登录挤下线。
_115_QR_APPS: List[Dict[str, Any]] = [
    {"value": "wechatmini", "label": "微信小程序", "default": True, "rec": True},
    {"value": "alipaymini", "label": "支付宝小程序", "default": False, "rec": True},
    {"value": "tv", "label": "电视端 TV", "default": False, "rec": True},
    {"value": "qandroid", "label": "安卓 Q 版", "default": False, "rec": False},
    {"value": "android", "label": "安卓 App", "default": False, "rec": False},
    {"value": "ios", "label": "iOS App", "default": False, "rec": False},
    {"value": "web", "label": "网页端 Web", "default": False, "rec": False},
]

_115_QR_APP_VALUES: set = {item["value"] for item in _115_QR_APPS}
_115_QR_DEFAULT_APP: str = "wechatmini"

_115_QR_UA: str = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_QR_TOKEN_URL: str = "https://qrcodeapi.115.com/api/1.0/web/1.0/token/"
_QR_STATUS_URL: str = "https://qrcodeapi.115.com/get/status/"
_QR_RESULT_URL_TMPL: str = "https://passportapi.115.com/app/1.0/{app}/1.0/login/qrcode/"
_QR_IMAGE_URL_TMPL: str = "https://qrcodeapi.115.com/api/1.0/mac/1.0/qrcode?uid={uid}"


def get_115_qr_apps() -> List[Dict[str, Any]]:
    """返回可选的客户端列表（含推荐/默认标记）。"""
    return [dict(item) for item in _115_QR_APPS]


def get_115_qr_default_app() -> str:
    return _115_QR_DEFAULT_APP


def normalize_115_qr_app(value: Any) -> str:
    """归一化 app 值，非法输入落到默认冷门设备，避免误选常用于挤下线。"""
    token = str(value or "").strip().lower()
    if token in _115_QR_APP_VALUES:
        return token
    return _115_QR_DEFAULT_APP


def get_115_qrcode_token() -> Dict[str, Any]:
    """第一步：获取二维码 token（含 uid/time/sign）。"""
    resp = http_request_json(
        _QR_TOKEN_URL,
        extra_headers={"User-Agent": _115_QR_UA, "Accept": "application/json"},
    )
    data = resp.get("data") if isinstance(resp, dict) else None
    if not isinstance(data, dict) or not str(data.get("uid", "")).strip():
        raise RuntimeError("获取 115 二维码失败，接口可能被调整或被风控拦截")
    return data


def get_115_qrcode_status(uid: str, time: Any, sign: str) -> int:
    """第二步：轮询扫码状态。status: 0等待 1已扫 2已登录 -1过期 -2取消。"""
    params = {
        "uid": str(uid or "").strip(),
        "time": str(time or "").strip(),
        "sign": str(sign or "").strip(),
    }
    resp = http_request_json(
        _QR_STATUS_URL + "?" + urlencode(params),
        extra_headers={"User-Agent": _115_QR_UA, "Accept": "application/json"},
    )
    data = resp.get("data") if isinstance(resp, dict) else {}
    if not isinstance(data, dict):
        raise RuntimeError("115 扫码状态接口返回异常")
    try:
        return int(data.get("status"))
    except (TypeError, ValueError):
        raise RuntimeError("115 扫码状态接口返回异常: %r" % (data,))


def _build_cookie_header(cookie_payload: Any) -> str:
    """把 115 返回的 cookie dict 拼成 Cookie 请求头字符串。"""
    items = cookie_payload if isinstance(cookie_payload, dict) else {}
    pairs = []
    for key, value in items.items():
        k = str(key or "").strip()
        v = str(value or "").strip()
        if k and v:
            pairs.append(f"{k}={v}")
    return "; ".join(pairs)


def post_115_qrcode_result(uid: str, app: Any) -> str:
    """第三步：用 uid + app 换取对应设备的 cookie 字符串。"""
    device = normalize_115_qr_app(app)
    url = _QR_RESULT_URL_TMPL.format(app=device)
    resp = http_request_form_json(
        url,
        {"app": device, "account": str(uid or "").strip()},
        extra_headers={"User-Agent": _115_QR_UA, "Accept": "application/json"},
    )
    data = resp.get("data") if isinstance(resp, dict) else None
    if not isinstance(data, dict):
        raise RuntimeError("115 扫码登录失败，接口返回异常")
    cookie_payload = data.get("cookie") if isinstance(data.get("cookie"), dict) else {}
    cookie = _build_cookie_header(cookie_payload)
    if not cookie:
        raise RuntimeError("115 扫码成功但未返回 Cookie，请重试或改用手动粘贴")
    return cookie


def build_115_qrcode_image_url(uid: str) -> str:
    """二维码图片接口（仅供后端透传，避免前端直连 115 被 CORS 拦）。"""
    return _QR_IMAGE_URL_TMPL.format(uid=quote(str(uid or "").strip(), safe=""))
