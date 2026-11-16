"""极影视（极空间 Emby 兼容层）→ Seerr 的协议桥服务。

把 Jellyseerr 发的标准 Emby 请求翻译成极影视认的形式，再把极影视的返回
翻译回 Jellyseerr 认的形式。**目的只有一个：判重**（让 Seerr 知道库里已有
什么），不代理播放流、不做写操作。

协议偏差已用真实极影视（4.7.0.0）+ Jellyseerr 3.5.2 源码实测钉死，见
``docs/superpowers/specs/2026-11-17-emby-bridge-for-seerr-design.md`` §2。
五个翻译点：

- T1 头改写：Jellyseerr 发 ``Authorization: MediaBrowser ...``，极影视只认
  ``X-Emby-Token`` / ``X-Emby-Authorization``。
- T2 ``/Auth/Keys``：极影视没实现（404），本地伪造稳定伪 key。
- T3 判重改写：Jellyseerr 用 ``/Items?ids=``，极影视忽略 ids → 改写成
  ``/Users/{uid}/Items/{id}``。
- T4 库类型补全：极影视 CollectionType 全 None → 按库名补 movies/tvshows。
- T5 来源白名单：默认只放内网。

只依赖 Python 标准库（urllib / asyncio / hashlib / ipaddress），不新增第三方依赖。
"""

import asyncio
import hashlib
import ipaddress
import json
import logging
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from ..core import get_config, normalize_http_url

logger = logging.getLogger("emby_bridge")

# 上游请求统一打的客户端标识（补 DeviceId 用，极影视要求非空）
_BRIDGE_DEVICE_ID = "115-media-hub-bridge"

# 允许透传给上游的路径前缀（白名单外一律 404，避免暴露极影视管理接口）
_ALLOWED_PREFIXES: Tuple[str, ...] = (
    "/System/",
    "/Users/",
    "/Library/",
    "/Items",
    "/Shows/",
    "/Images/",
    "/DisplayPreferences/",
    "/Branding/",
    "/Sessions/",
    "/Auth/Keys",
)

# 需要补 CollectionType 的端点（媒体库列表）
_LIBRARY_LIST_PATHS: Tuple[str, ...] = (
    "/Library/MediaFolders",
    "/Library/VirtualFolders",
)


def _is_library_list_path(path: str) -> bool:
    """是否是「媒体库列表」请求。

    两条路都要补 ``CollectionType``：标准版是 ``/Library/MediaFolders``，而极影视
    根本没实现它（404），Seerr 会回退到 ``/Users/{uid}/Views``。回退路径的库同样
    全是 ``CollectionType: null``，漏补就会把「电影库」判成剧集库，判重跟着失效。
    """
    if any(path.startswith(prefix) for prefix in _LIBRARY_LIST_PATHS):
        return True
    return path.rstrip("/").endswith("/Views")

# token 缓存：{ (upstream, username) : {"token": str, "uid": str} }
_TOKEN_CACHE: Dict[Tuple[str, str], Dict[str, str]] = {}

# 单飞锁：每个 (upstream, username) 一把，避免并发 401 时重复登录
_RELOGIN_LOCKS: Dict[Tuple[str, str], asyncio.Lock] = {}


# ---------------------------------------------------------------- 工具

def _parse_media_browser_header(value: str) -> Dict[str, str]:
    """解析 ``MediaBrowser Client="x", Device="y", Token="z"`` 成 KV。

    容错：引号可有可无、逗号分隔、等号分隔。解析不出的字段忽略。
    """
    result: Dict[str, str] = {}
    raw = str(value or "").strip()
    if not raw:
        return result
    m = re.match(r"^\s*MediaBrowser\s*(.*)$", raw, flags=re.IGNORECASE)
    body = m.group(1) if m else raw
    # 按逗号切，但值里可能带引号括住的逗号（少见，这里不处理嵌套引号内的逗号）
    for part in body.split(","):
        if "=" not in part:
            continue
        key, _, val = part.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            result[key] = val
    return result


def _build_emby_authorization(fields: Dict[str, str]) -> str:
    """把 KV 拼回 ``MediaBrowser Client=..., Device=..., ...``。"""
    parts = ["MediaBrowser"]
    for key in ("Client", "Device", "DeviceId", "Version"):
        value = fields.get(key, "")
        if value:
            parts.append(f'{key}="{value}"')
    return ", ".join(parts)


def _mask(value: str) -> str:
    value = str(value or "")
    if len(value) <= 8:
        return "****"
    return value[:4] + "****" + value[-4:]


def _is_private_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


def _path_allowed(path: str) -> bool:
    """白名单判定。

    前缀表里大多带尾斜杠（``/Users/``），但 Emby/Jellyfin 协议里有一批**裸路径**
    端点，例如 Seerr 的 ``getUsers()`` 调的是 ``GET /Users``（没有尾斜杠）。
    只按前缀比会把它们判成 404，Seerr 保存媒体服务器、同步用户时直接报失败。
    所以额外放行「去掉尾斜杠后完全相等」这一种情况，其余仍按前缀匹配。
    """
    for prefix in _ALLOWED_PREFIXES:
        if path == prefix or path.startswith(prefix):
            return True
        if prefix.endswith("/") and path == prefix.rstrip("/"):
            return True
    return False


def _normalize_upstream(upstream: str) -> str:
    """补协议与去尾斜杠，供拼接 URL。"""
    value = str(upstream or "").strip().rstrip("/")
    if not value:
        return ""
    if not re.match(r"^https?://", value, flags=re.IGNORECASE):
        value = "http://" + value
    return value


# ---------------------------------------------------------------- 配置读取

def _bridge_settings() -> Dict[str, Any]:
    cfg = get_config()
    return {
        "enabled": bool(cfg.get("emby_bridge_enabled")),
        "upstream": _normalize_upstream(cfg.get("emby_bridge_upstream", "")),
        "username": str(cfg.get("emby_bridge_username", "") or "").strip(),
        "password": str(cfg.get("emby_bridge_password", "") or "").strip(),
        "allow_public": bool(cfg.get("emby_bridge_allow_public")),
    }


def bridge_configured(settings: Optional[Dict[str, Any]] = None) -> bool:
    s = settings if settings is not None else _bridge_settings()
    return bool(s["upstream"] and s["username"] and s["password"])


# ---------------------------------------------------------------- 登录与 token

def _cache_key(upstream: str, username: str) -> Tuple[str, str]:
    return (upstream, username)


def _do_login(upstream: str, username: str, password: str) -> Dict[str, str]:
    """调极影视 AuthenticateByName 换 token，返回 {token, uid, server_id}。"""
    url = f"{upstream}/Users/AuthenticateByName"
    body = json.dumps({"Username": username, "Pw": password}).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Emby-Authorization": _build_emby_authorization(
            {"Client": "115-media-hub", "Device": "bridge", "DeviceId": _BRIDGE_DEVICE_ID, "Version": "1.0.0"}
        ),
    }
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.loads(resp.read().decode("utf-8") or "{}")
    user = payload.get("User") if isinstance(payload, dict) else {}
    token = str(payload.get("AccessToken", "") or "").strip()
    uid = str(user.get("Id", "") or "").strip() if isinstance(user, dict) else ""
    server_id = str(payload.get("ServerId", "") or "").strip()
    if not token:
        raise RuntimeError("极影视登录成功但未返回 AccessToken")
    return {"token": token, "uid": uid, "server_id": server_id}


def _get_token(settings: Dict[str, Any]) -> Dict[str, str]:
    """取缓存 token；没有就登录一次。返回 {token, uid, server_id}。"""
    upstream = settings["upstream"]
    username = settings["username"]
    key = _cache_key(upstream, username)
    cached = _TOKEN_CACHE.get(key)
    if cached and cached.get("token"):
        return cached
    fresh = _do_login(upstream, username, settings["password"])
    _TOKEN_CACHE[key] = fresh
    return fresh


def _relogin(settings: Dict[str, Any]) -> Dict[str, str]:
    """强制重新登录并覆盖缓存。"""
    upstream = settings["upstream"]
    username = settings["username"]
    key = _cache_key(upstream, username)
    fresh = _do_login(upstream, username, settings["password"])
    _TOKEN_CACHE[key] = fresh
    return fresh


def _stable_pseudo_key(settings: Dict[str, Any]) -> str:
    """派生稳定的伪 API Key（重启不变），只用来糊弄 Jellyseerr 的 createApiToken。"""
    token_info = _get_token(settings)
    seed = f"{token_info.get('server_id', '')}:{settings['username']}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 头改写（T1）

def _rewrite_headers(seerr_headers: Dict[str, str], token: str) -> Dict[str, str]:
    """把 Seerr 的 Authorization 头改写为极影视认的 X-Emby-* 头。"""
    out: Dict[str, str] = {}
    auth_value = ""
    for name, value in seerr_headers.items():
        if name.lower() == "authorization":
            auth_value = value
        elif name.lower() in ("host", "content-length", "connection"):
            # 这些由 urllib 自行计算/处理，不手动透传
            continue
        else:
            out[name] = value

    fields = _parse_media_browser_header(auth_value)
    if not fields.get("DeviceId"):
        fields["DeviceId"] = _BRIDGE_DEVICE_ID
    # 抽 Token（若 Seerr 已带）；否则用桥自己缓存的真实 token
    effective_token = fields.pop("Token", "") or token
    out["X-Emby-Authorization"] = _build_emby_authorization(fields)
    if effective_token:
        out["X-Emby-Token"] = effective_token
    out.pop("Authorization", None)
    return out


# ---------------------------------------------------------------- 转发

def _http_status(exc: Exception) -> int:
    if isinstance(exc, urllib.error.HTTPError):
        return int(exc.code or 500)
    if isinstance(exc, urllib.error.URLError):
        return 502
    return 500


def _forward_raw(
    upstream: str,
    method: str,
    path: str,
    query: str,
    body: bytes,
    headers: Dict[str, str],
    read_timeout: int,
) -> Tuple[int, Dict[str, str], bytes]:
    """用标准库 urllib 转发一个请求，返回 (status, headers, body)。"""
    url = f"{upstream}{path}"
    if query:
        url += f"?{query}"
    url = normalize_http_url(url)
    req = urllib.request.Request(url, data=body if method in ("POST", "PUT", "PATCH") else None, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=read_timeout) as resp:
            resp_headers = dict(resp.headers.items())
            data = resp.read()
            return int(resp.status or 200), resp_headers, data
    except urllib.error.HTTPError as exc:
        resp_headers = dict(exc.headers.items()) if exc.headers else {}
        data = exc.read() if hasattr(exc, "read") else b""
        return int(exc.code or 500), resp_headers, data


def _forward_json(
    upstream: str,
    method: str,
    path: str,
    query: str,
    body: bytes,
    headers: Dict[str, str],
    read_timeout: int,
) -> Tuple[int, Dict[str, str], Any]:
    status, resp_headers, data = _forward_raw(upstream, method, path, query, body, headers, read_timeout)
    parsed: Any = None
    text = data.decode("utf-8", errors="ignore")
    if text.strip():
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = text
    return status, resp_headers, parsed


# ---------------------------------------------------------------- 分派

def _fill_collection_types(payload: Any) -> Any:
    """T4：把媒体库列表里每个库的 CollectionType 补上 movies / tvshows。"""
    if not isinstance(payload, dict):
        return payload
    items = payload.get("Items")
    if not isinstance(items, list):
        return payload
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("CollectionType"):
            continue
        name = str(item.get("Name", "") or "")
        if "电影" in name:
            item["CollectionType"] = "movies"
        else:
            item["CollectionType"] = "tvshows"
    return payload


async def handle(method: str, path: str, query: str, headers: Dict[str, str], body: bytes) -> Tuple[int, Dict[str, str], Any]:
    """桥的统一入口。返回 (status, response_headers, payload)。"""
    settings = _bridge_settings()
    if not settings["enabled"]:
        return 404, {}, {"error": "emby-bridge 未启用"}

    # T5：来源白名单（由路由层把 client host 传进 headers 的 X-Bridge-Client-Host）
    client_host = headers.get("X-Bridge-Client-Host", "")
    if not settings["allow_public"] and client_host and not _is_private_ip(client_host):
        return 403, {}, {"error": "emby-bridge 仅允许内网来源访问"}

    if not bridge_configured(settings):
        return 503, {}, {"error": "emby-bridge 未配置：请先在参数配置页填写极影视地址与媒体库账号"}

    # 白名单校验
    if not _path_allowed(path):
        return 404, {}, {"error": "emby-bridge 不转发该路径"}

    upstream = settings["upstream"]
    upstream_path = path
    rewritten_ids = False

    # T2：/Auth/Keys 本地实现
    if path.startswith("/Auth/Keys"):
        if method == "POST":
            return 200, {"Content-Type": "application/json"}, {}
        if method == "GET":
            pseudo = _stable_pseudo_key(settings)
            return 200, {"Content-Type": "application/json"}, {
                "Items": [{"AppName": "Seerr", "AccessToken": pseudo}],
                "TotalRecordCount": 1,
            }
        return 405, {}, {"error": "method not allowed"}

    # T3：判重请求改写 /Items?ids= → /Users/{uid}/Items/{id}
    if path.rstrip("/") == "/Items":
        qs = urllib.parse.parse_qs(query)
        ids_value = qs.get("ids", [""])[0].strip()
        if ids_value:
            token_info = _get_token(settings)
            uid = token_info.get("uid", "")
            if uid:
                upstream_path = f"/Users/{uid}/Items/{urllib.parse.quote(ids_value, safe='')}"
                rewritten_ids = True

    # 登录换 token（若上面 T3 已经取过则复用缓存）
    try:
        token_info = _get_token(settings)
    except Exception as exc:
        logger.warning("emby-bridge 登录极影视失败：%s", exc)
        return 502, {}, {"error": "emby-bridge 无法登录极影视"}

    token = token_info.get("token", "")
    upstream_headers = _rewrite_headers(headers, token)

    status, resp_headers, parsed = _forward_json(
        upstream, method, upstream_path, query, body, upstream_headers, read_timeout=120
    )

    # 401 单飞重登一次后重试
    if status == 401:
        key = _cache_key(upstream, settings["username"])
        lock = _RELOGIN_LOCKS.setdefault(key, asyncio.Lock())
        async with lock:
            try:
                token_info = _relogin(settings)
            except Exception as exc:
                logger.warning("emby-bridge 重登失败：%s", exc)
                return status, resp_headers, parsed
            token = token_info.get("token", "")
            retry_headers = _rewrite_headers(headers, token)
            status, resp_headers, parsed = _forward_json(
                upstream, method, upstream_path, query, body, retry_headers, read_timeout=120
            )

    # T4：媒体库列表补 CollectionType（含 Seerr 回退的 /Users/{uid}/Views）
    if status == 200 and _is_library_list_path(path):
        parsed = _fill_collection_types(parsed)

    # T3：判重改写后，把单条响应包装成 Jellyseerr 期望的 {Items:[单条]} 结构
    if status == 200 and rewritten_ids and isinstance(parsed, dict) and "Items" not in parsed:
        parsed = {"Items": [parsed], "TotalRecordCount": 1}

    # 透传上游关键头（X-Emby-* 等）
    pass_headers = {
        k: v for k, v in resp_headers.items()
        if k.lower().startswith("x-emby") or k.lower() == "content-type"
    }
    return status, pass_headers, parsed


def get_client_host(host: str) -> str:
    return str(host or "").strip()
