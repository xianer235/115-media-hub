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
import http.client
import ipaddress
import json
import logging
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from ..core import get_config, normalize_http_url
from ..http_utils import build_resilient_https_opener

logger = logging.getLogger("emby_bridge")

# 上游请求统一打的客户端标识（补 DeviceId 用，极影视要求非空）
_BRIDGE_DEVICE_ID = "115-media-hub-bridge"

# 上游连接中断（IncompleteRead / RemoteDisconnected 等瞬时错误）的重试次数与退避。
# 拉全库时极影视走 nginx 反代，大响应体偶发断连，重试 2~3 次通常能成功。
_FORWARD_RETRIES = 3
_FORWARD_RETRY_DELAY = 0.5  # 秒，随重试次数线性放大

# 上游连接中断的判定：除了「读响应体时被掐断」，还要认 TLS 层错误。
# 2026-11-26 真机：走公网 HTTPS 反代时对端不发 close_notify 就关连接，Python 抛的是
# ``SSLEOFError: UNEXPECTED_EOF_WHILE_READING``（既不是 IncompleteRead，也不包在
# URLError 里），原先没被识别成瞬时错误，整次拉库直接失败。
_TRANSIENT_ERRORS: Tuple[type, ...] = (
    http.client.IncompleteRead,
    http.client.RemoteDisconnected,
    ConnectionResetError,
    ConnectionAbortedError,
    BrokenPipeError,
    ssl.SSLEOFError,
    ssl.SSLZeroReturnError,
)


def looks_like_tls_error(exc: BaseException) -> bool:
    """判断是不是 TLS 层问题（握手/证书/断连），设置页与库存刷新共用。"""
    if isinstance(exc, (ssl.SSLError, ssl.SSLCertVerificationError)):
        return True
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, BaseException):
            return looks_like_tls_error(reason)
    text = str(exc or "").lower()
    return "ssl" in text or "unexpected_eof" in text or "eof occurred in violation of protocol" in text


def _is_transient_network_error(exc: BaseException) -> bool:
    """判断是不是「重发一次大概率能好」的连接类错误。

    证书错误（SSLCertVerificationError）**不算**——那是配置问题，重试多少次都一样。
    """
    if isinstance(exc, _TRANSIENT_ERRORS):
        return True
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, BaseException) and reason is not exc:
            return _is_transient_network_error(reason)
        return False
    if isinstance(exc, ssl.SSLError):
        # 老版本 / 不同 OpenSSL 会把同类断连报成 SSLError("EOF occurred in violation of protocol")
        message = str(exc)
        return "EOF occurred in violation of protocol" in message or "UNEXPECTED_EOF" in message
    return False


_opener = None


def _get_opener():
    """进程内复用的 opener：带「多地址 TLS 回退」，避免 IPv6 回环把整次请求打死。"""
    global _opener
    if _opener is None:
        _opener = build_resilient_https_opener()
    return _opener


def _urlopen(req: urllib.request.Request, timeout: float):
    return _get_opener().open(req, timeout=timeout)

# T6 全库扫描分页：Seerr 拉库内容只发一次 /Items（StartIndex=0，从不翻页，也不看
# TotalRecordCount），极影视单次返回有条数上限 → 每个库只能扫到前一批，其余条目不进
# Seerr 索引（真机表现为「手动扫描几秒就跑完」，且只有前一批片子显示「可获得」）。
# 桥对带 ParentId 的递归查询代为翻页，聚合后再一次性返回。
_SCAN_PAGE_SIZE = 1000
_SCAN_MAX_PAGES = 200

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

# T7 Recently Added Scan 顶替：Jellyseerr 的「最近添加扫描」（每 5 分钟一次）在 Emby
# 模式下调的是 ``/Users/{uid}/Items/Latest?Limit=12&ParentId={库}``，只取「最近添加」
# 的前 12 条。用户手动往极影视存片后，只有挤进这 12 条的会被判重变绿，其余新片要等
# 每 24 小时的全量扫描（Full Scan）才轮到 → 表现为「有的电影绿、有的不绿」。
# 桥顶替该端点：改成按 DateCreated 降序拉最近 ``_LATEST_ITEMS_LIMIT`` 条，覆盖手动
# 新存的片，又不至于像全量扫描那样把整个库拉一遍（Seerr 侧限速 5 条/秒，全量很慢）。
_LATEST_ITEMS_LIMIT = 500


def _is_library_list_path(path: str) -> bool:
    """是否是「媒体库列表」请求。

    两条路都要补 ``CollectionType``：标准版是 ``/Library/MediaFolders``，而极影视
    根本没实现它（404），Seerr 会回退到 ``/Users/{uid}/Views``。回退路径的库同样
    全是 ``CollectionType: null``，漏补就会把「电影库」判成剧集库，判重跟着失效。
    """
    if any(path.startswith(prefix) for prefix in _LIBRARY_LIST_PATHS):
        return True
    return path.rstrip("/").endswith("/Views")


def _is_latest_items_path(path: str) -> bool:
    """是否是「最近添加」列表请求（Seerr 的 Recently Added Scan）。"""
    return path.rstrip("/").endswith("/Items/Latest")


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


def test_connection(upstream: str, username: str, password: str) -> Dict[str, Any]:
    """设置页「测试连通性」：用给定地址与媒体库账号登录一次极影视，再读一次媒体库列表。

    只做只读探测（登录 + 列库），不写配置、不进 token 缓存 —— 测试用的密码可能是
    用户刚敲还没保存的，缓存住反而会和保存后的配置打架。
    返回 {"ok", "msg", "latency_ms", "library_count", "libraries", "server_id"}。
    """
    started = time.monotonic()
    base = _normalize_upstream(upstream)
    user = str(username or "").strip()
    pwd = str(password or "")

    def done(ok: bool, msg: str, **extra: Any) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "ok": ok,
            "msg": msg,
            "latency_ms": max(0, int((time.monotonic() - started) * 1000)),
            "library_count": 0,
            "libraries": [],
            "server_id": "",
        }
        payload.update(extra)
        return payload

    if not base:
        return done(False, "请先填写极影视地址，例如 http://192.168.0.2:8021")
    if not user:
        return done(False, "请先填写媒体库账号（极影视里的媒体库账号，不是极空间登录号）")
    if not pwd:
        return done(False, "请先填写媒体库密码")

    try:
        info = _do_login(base, user, pwd)
    except urllib.error.HTTPError as exc:
        if int(exc.code or 0) in (401, 403):
            return done(False, "登录被拒绝：媒体库账号或密码不对。这里要填极影视的媒体库账号，不是极空间登录号")
        return done(False, f"极影视返回 HTTP {exc.code}，地址可能不对")
    except urllib.error.URLError as exc:
        if looks_like_tls_error(exc):
            return done(False, f"TLS 连接被中断：{getattr(exc, 'reason', exc)}。若是公网 HTTPS 域名，检查该域名在面板所在网络是否可访问（IPv6 / NAT 回环），或改用局域网地址")
        return done(False, f"连不上极影视地址：{getattr(exc, 'reason', exc)}")
    except Exception as exc:  # noqa: BLE001 - 设置页只关心「能不能用」
        if looks_like_tls_error(exc):
            return done(False, f"TLS 连接被中断：{exc}。若是公网 HTTPS 域名，检查该域名在面板所在网络是否可访问（IPv6 / NAT 回环），或改用局域网地址")
        return done(False, f"登录极影视失败：{exc}")

    token = str(info.get("token", "") or "")
    uid = str(info.get("uid", "") or "")
    if not uid:
        return done(False, "登录成功但极影视没返回用户 ID，无法继续读媒体库")
    status, _, payload = _forward_json(
        base,
        "GET",
        f"/Users/{uid}/Views",
        "",
        b"",
        {"X-Emby-Token": token, "Accept": "application/json"},
        15,
    )
    if status != 200 or not isinstance(payload, dict):
        return done(False, f"已登录，但读取媒体库失败（HTTP {status}）")
    names = [
        str(item.get("Name", "") or "").strip()
        for item in (payload.get("Items") or [])
        if isinstance(item, dict) and str(item.get("Name", "") or "").strip()
    ]
    if not names:
        return done(False, "已登录，但极影视没有返回任何媒体库（检查该账号有没有媒体库查看权限）", server_id=str(info.get("server_id", "") or ""))
    return done(
        True,
        f"已连上极影视，读到 {len(names)} 个媒体库",
        library_count=len(names),
        libraries=names,
        server_id=str(info.get("server_id", "") or ""),
    )


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
    # 登录同样要扛 TLS 抖动：反代侧关连接时这里也会抛 SSLEOFError。
    last_error: Optional[BaseException] = None
    payload: Any = {}
    for attempt in range(_FORWARD_RETRIES):
        try:
            with _urlopen(req, timeout=15) as resp:
                payload = json.loads(resp.read().decode("utf-8") or "{}")
            break
        except Exception as exc:  # noqa: BLE001 - 只对瞬时错误重试，其余原样抛出
            if not _is_transient_network_error(exc) or attempt + 1 >= _FORWARD_RETRIES:
                raise
            last_error = exc
            logger.warning(
                "极影视登录连接中断（%s），第 %s/%s 次重试：%s",
                type(exc).__name__, attempt + 1, _FORWARD_RETRIES, url,
            )
            time.sleep(_FORWARD_RETRY_DELAY * (attempt + 1))
    else:  # pragma: no cover - 只有循环被耗尽才会走到
        if last_error is not None:
            raise last_error
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
    # Seerr 头上的 Token 是**桥自己发的伪 key**（/Auth/Keys 本地伪造的那把），
    # 极影视根本不认，透传过去只会 401（2026-11-17 真机日志：
    # "getting libraries from the Jellyfin server: 401" 刷屏）。
    # 所以一律用桥缓存的真实 token；只有桥还没拿到 token 时才退回去用 Seerr 的。
    seerr_token = fields.pop("Token", "")
    effective_token = token or seerr_token
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
    """用标准库 urllib 转发一个请求，返回 (status, headers, body)。

    极影视走反向代理（nginx）时，对较大的响应体（拉全库单页上千条）会偶发中途
    断连，表现为 ``http.client.IncompleteRead(0 bytes read)`` / ``RemoteDisconnected``。
    这类错误是瞬时网络抖动，重试同一请求通常能成功，故对「读响应体时连接中断」做
    有限重试；HTTP 4xx/5xx 业务错误不重试（重试无意义）。
    """
    url = f"{upstream}{path}"
    if query:
        url += f"?{query}"
    url = normalize_http_url(url)
    # 只重试连接类瞬时错误（含 TLS 层断连）；用同一份请求原样重发（GET 幂等）。
    last_exc: Optional[BaseException] = None
    for attempt in range(_FORWARD_RETRIES):
        req = urllib.request.Request(
            url,
            data=body if method in ("POST", "PUT", "PATCH") else None,
            headers=headers,
            method=method,
        )
        try:
            with _urlopen(req, timeout=read_timeout) as resp:
                resp_headers = dict(resp.headers.items())
                data = resp.read()
                return int(resp.status or 200), resp_headers, data
        except urllib.error.HTTPError as exc:
            # 业务错误（4xx/5xx）直接返回，不重试
            resp_headers = dict(exc.headers.items()) if exc.headers else {}
            data = exc.read() if hasattr(exc, "read") else b""
            return int(exc.code or 500), resp_headers, data
        except Exception as exc:  # noqa: BLE001 - 下面只挑瞬时错误重试，其余原样抛
            if not _is_transient_network_error(exc):
                raise
            last_exc = exc
            logger.warning(
                "emby-bridge 上游连接中断（%s），第 %s/%s 次重试：%s %s%s",
                type(exc).__name__,
                attempt + 1,
                _FORWARD_RETRIES,
                method,
                upstream,
                path,
            )
            if attempt + 1 < _FORWARD_RETRIES:
                time.sleep(_FORWARD_RETRY_DELAY * (attempt + 1))
            continue
    # 重试耗尽仍失败：按连接错误返回 502，让调用方按「失败」处理
    logger.warning("emby-bridge 上游连接反复中断，放弃：%s %s（%s）", method, path, last_exc)
    return 502, {}, b""


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


def _query_with_page(query: str, start: int, limit: int) -> str:
    """替换 query 里的 StartIndex / Limit，其余参数原样保留。"""
    pairs = urllib.parse.parse_qsl(query, keep_blank_values=True)
    kept = [(k, v) for k, v in pairs if k.lower() not in ("startindex", "limit", "take")]
    kept.append(("StartIndex", str(start)))
    kept.append(("Limit", str(limit)))
    return urllib.parse.urlencode(kept)


def _is_full_scan_items(method: str, path: str, query: str) -> bool:
    """只有「递归列某个库的全部条目」才需要代翻页；判重(ids=)、搜索等一律不动。"""
    if method.upper() != "GET" or path.rstrip("/") != "/Items":
        return False
    qs = {k.lower(): v for k, v in urllib.parse.parse_qs(query).items()}
    if qs.get("ids", [""])[0].strip():
        return False
    if not qs.get("parentid", [""])[0].strip():
        return False
    return str(qs.get("recursive", [""])[0]).lower() == "true"


def _aggregate_items(
    upstream: str,
    path: str,
    query: str,
    headers: Dict[str, str],
    page_size: int = _SCAN_PAGE_SIZE,
) -> Tuple[int, Dict[str, str], Any]:
    """按 StartIndex/Limit 翻页拉全 Items。

    游标按**上游实际返回的条数**推进（``cursor += len(items)``），而不是按请求的
    ``Limit`` 推进：极影视等实现可能把单页压到比 Limit 更小（比如只给 200 条），
    若按 1000 步进会直接跳过中间那批，库越大漏得越多。

    三重护栏，任何一个不满足就停手，绝不死循环：
    1. 上游反复返回同一页（忽略 StartIndex）→ 没有新条目即停；
    2. 已取回条数达到上游声明的 TotalRecordCount；
    3. 页数上限 ``_SCAN_MAX_PAGES``（1000 条/页 × 200 页 = 20 万条封顶）。

    中途某页失败时，前面已经聚合到的条目照常返回（宁可少几条，也别让整库白扫）。

    ``page_size`` 可调小：走公网 HTTPS 反代时单页响应体越大越容易被对端掐断，
    拉库存这种「少几条也无所谓」的场景宁可用小页多跑几次。
    """
    merged: List[Any] = []
    seen: set = set()
    total = 0
    cursor = 0
    effective_page_size = max(1, int(page_size or _SCAN_PAGE_SIZE))
    status, resp_headers, parsed = 200, {}, {}
    pages = 0
    while pages < _SCAN_MAX_PAGES:
        page_query = _query_with_page(query, cursor, effective_page_size)
        status, resp_headers, parsed = _forward_json(
            upstream, "GET", path, page_query, b"", headers, read_timeout=120
        )
        if status != 200 or not isinstance(parsed, dict):
            if merged:
                break
            return status, resp_headers, parsed
        items = parsed.get("Items")
        if not isinstance(items, list):
            if merged:
                break
            return status, resp_headers, parsed
        if pages == 0:
            try:
                total = max(0, int(parsed.get("TotalRecordCount") or 0))
            except (TypeError, ValueError):
                total = 0
        fresh = [item for item in items if str(item.get("Id")) not in seen]
        if not fresh:
            break
        merged.extend(fresh)
        seen.update(str(item.get("Id")) for item in fresh)
        pages += 1
        cursor += len(items)
        if total and len(merged) >= total:
            break
    logger.info(
        "emby-bridge 聚合库条目：%s 上游 total=%s 实际取回=%s 分页=%s",
        path,
        total,
        len(merged),
        pages,
    )
    return 200, resp_headers, {
        "Items": merged,
        "TotalRecordCount": len(merged),
        "StartIndex": 0,
    }


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

    # T4a：极影视没实现 /Library/MediaFolders（实测 404，VirtualFolders 同理），
    # Seerr 拉库列表会直接报「Something went wrong while syncing libraries」。
    # 用标准的 /Users/{uid}/Views 顶替，返回结构同为 {Items:[...]}，Id 也是 class_* 一致。
    if path.rstrip("/") in ("/Library/MediaFolders", "/Library/VirtualFolders"):
        uid = token_info.get("uid", "")
        if uid:
            upstream_path = f"/Users/{uid}/Views"

    # T7：Recently Added Scan 顶替 /Users/{uid}/Items/Latest?Limit=12 → 按 DateCreated
    # 降序拉最近 _LATEST_ITEMS_LIMIT 条，覆盖手动新存的片（否则只判重最近 12 条）。
    # 改写后路径是 /Users/{uid}/Items，不等于 /Items，不会触发 _is_full_scan_items 的
    # 全库翻页，只拉一页，保持增量扫描的轻量。
    if _is_latest_items_path(path):
        qs = urllib.parse.parse_qs(query)
        parent_id = qs.get("ParentId", [""])[0].strip()
        if parent_id:
            upstream_path = re.sub(r"/Items/Latest$", "/Items", path)
            query = (
                f"ParentId={urllib.parse.quote(parent_id, safe='')}"
                "&Recursive=true"
                "&IncludeItemTypes=Series,Movie,Others"
                "&SortBy=DateCreated"
                "&SortOrder=Descending"
                f"&Limit={_LATEST_ITEMS_LIMIT}"
            )

    token = token_info.get("token", "")
    upstream_headers = _rewrite_headers(headers, token)

    aggregate_scan = _is_full_scan_items(method, path, query)

    async def fetch_upstream(hdrs: Dict[str, str]):
        if aggregate_scan:
            # 全库翻页可能持续几十秒到几分钟（1 万条 / 每页 1000），放线程里跑，
            # 不能堵住事件循环，否则面板界面在扫描期间会整体卡住。
            return await asyncio.to_thread(
                _aggregate_items, upstream, upstream_path, query, hdrs
            )
        return _forward_json(
            upstream, method, upstream_path, query, body, hdrs, read_timeout=120
        )

    status, resp_headers, parsed = await fetch_upstream(upstream_headers)

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
            status, resp_headers, parsed = await fetch_upstream(retry_headers)

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
