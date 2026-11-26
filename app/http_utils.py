import gzip
import http.client
import json
import logging
import socket
import ssl
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("http_utils")

# 所有可打印 ASCII（0x21~0x7E）。作为 quote 的 safe 集合，等于「一个 ASCII 字节都别动」。
_ASCII_PRINTABLE_SAFE = "".join(chr(code) for code in range(0x21, 0x7F))


def normalize_http_url(url: str) -> str:
    """把 URL 里的非 ASCII 字符编码成百分号转义（urllib 只接受 ASCII 请求 URL）。

    **绝不能碰 URL 里已有的转义序列。** 早先的实现是 unquote 再 quote，会把
    ``%3D`` 还原成 ``=``、``%2B`` 还原成 ``+``；而阿里云盘 / OSS 这类按原始
    query 串校验签名的直链，改动任意一个字节都会签名失配，服务端直接 403
    （2026-10-20 真机复现：阿里作源的 3MB 文件复制必失败，归一化前后长度
    2307 → 2281）。

    所以这里只编码「不在 ASCII 可打印区间」的字符，ASCII 一律原样保留，
    对已经编码好的直链是恒等变换。
    """
    text = str(url or "").strip()
    if not text:
        return ""
    parts = urllib.parse.urlsplit(text)
    path = urllib.parse.quote(parts.path, safe=_ASCII_PRINTABLE_SAFE)
    query = urllib.parse.quote(parts.query, safe=_ASCII_PRINTABLE_SAFE)
    fragment = urllib.parse.quote(parts.fragment, safe=_ASCII_PRINTABLE_SAFE)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, query, fragment))


def build_http_opener(proxy_url: str = ""):
    if proxy_url:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        )
    return urllib.request.build_opener()


# ---------------------------------------------------------------- 多地址 HTTPS
#
# 2026-11-26 真机：面板在局域网里用「公网 HTTPS 域名」访问自己家的极影视，刷新库存
# 报 ``[SSL: UNEXPECTED_EOF_WHILE_READING]``，同一个域名在浏览器里却正常，直连内网
# 地址也正常。根因是**域名同时有 A 与 AAAA 记录**，容器按系统顺序先连上了一个
# 「TCP 能通、TLS 立刻被掐断」的地址（回环 / 旧 AAAA 的典型表现），而标准
# ``http.client`` 只在「连不上」时换下一个地址，TLS 阶段失败就直接抛给调用方，
# 不会回退到 A 记录。
#
# 这里把 connect 改成「逐个解析地址试，TLS 失败也换下一个」，对调用方透明。


class MultiAddressHTTPSConnection(http.client.HTTPSConnection):
    """TLS 握手失败时回退到下一个解析地址的 HTTPS 连接。

    ``http.client`` 原生行为是：``socket.create_connection`` 按顺序试地址，但只覆盖
    「TCP 连不上」；TCP 通了而 TLS 被对端掐断时直接冒泡（本项目踩到的就是这条）。
    这里对每个地址完整走一遍 TCP + TLS，任一失败就换下一个，全部失败才抛出最后一个
    异常。``connected_address`` 记录实际用上的 IP，便于日志定位。
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.connected_address = ""

    def connect(self) -> None:  # noqa: D102 - 覆盖标准实现，语义见类注释
        # 走代理（CONNECT 隧道）时地址列表是代理的，交给标准实现。
        if self._tunnel_host:
            super().connect()
            return
        last_error: Optional[BaseException] = None
        try:
            addresses = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)
        except OSError:
            raise
        for family, socktype, proto, _canon, sockaddr in addresses:
            sock = None
            try:
                sock = socket.socket(family, socktype, proto)
                if self.timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                    sock.settimeout(self.timeout)
                if self.source_address:
                    sock.bind(self.source_address)
                sock.connect(sockaddr)
                self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
                self.connected_address = str(sockaddr[0])
                return
            except OSError as exc:  # 含 ssl.SSLError（SSLError 是 OSError 子类）
                last_error = exc
                logger.warning(
                    "HTTPS 连接 %s:%s 经 %s 失败（%s），尝试下一个地址",
                    self.host, self.port, sockaddr[0], type(exc).__name__,
                )
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass
        if last_error is not None:
            raise last_error
        raise OSError("无法解析或连接 %s:%s" % (self.host, self.port))


class _MultiAddressHTTPSHandler(urllib.request.HTTPSHandler):
    """把 MultiAddressHTTPSConnection 接进 urllib 的 opener。"""

    def https_open(self, req):
        return self.do_open(
            MultiAddressHTTPSConnection,
            req,
            context=self._context,
            check_hostname=self._check_hostname,
        )


def build_resilient_https_opener():
    """带「多地址 TLS 回退」的 opener，用于访问自家反代（极影视等）。"""
    return urllib.request.build_opener(
        _MultiAddressHTTPSHandler(context=ssl.create_default_context())
    )



def decode_response_body(resp) -> str:
    """Read HTTP response body, handling gzip compression transparently."""
    raw = resp.read()
    content_encoding = (resp.headers.get("Content-Encoding") or "").strip().lower()
    if content_encoding == "gzip" or (len(raw) >= 2 and raw[:2] == b'\x1f\x8b'):
        try:
            raw = gzip.decompress(raw)
        except Exception:
            pass
    charset = resp.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="ignore")


def http_request_json(
    url: str,
    method: str = "GET",
    payload: Optional[Dict[str, Any]] = None,
    token: str = "",
    timeout: int = 30,
    extra_headers: Optional[Dict[str, str]] = None,
    proxy_url: str = "",
) -> Dict[str, Any]:
    normalized_url = normalize_http_url(url)
    headers = {}
    if extra_headers:
        headers.update(extra_headers)
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    if token:
        headers["Authorization"] = token
    req = urllib.request.Request(normalized_url, data=data, headers=headers, method=method)
    with build_http_opener(proxy_url).open(req, timeout=timeout) as resp:
        body = decode_response_body(resp)
    stripped = (body or "").strip()
    if not stripped:
        return {}
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        preview = stripped[:200].replace('\n', ' ').replace('\r', '')
        raise json.JSONDecodeError(
            f"响应不是 JSON（前 200 字符）: {preview}",
            doc=stripped, pos=0,
        )


def http_request_form_json(
    url: str,
    form_data: Dict[str, Any],
    timeout: int = 30,
    extra_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    normalized_url = normalize_http_url(url)
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
    }
    if extra_headers:
        headers.update(extra_headers)
    encoded = urllib.parse.urlencode({k: "" if v is None else str(v) for k, v in form_data.items()}).encode("utf-8")
    req = urllib.request.Request(normalized_url, data=encoded, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = decode_response_body(resp)
    stripped = (body or "").strip()
    if not stripped:
        return {}
    return json.loads(stripped)


def http_request_text(
    url: str,
    timeout: int = 30,
    extra_headers: Optional[Dict[str, str]] = None,
    proxy_url: str = "",
) -> str:
    normalized_url = normalize_http_url(url)
    headers = dict(extra_headers or {})
    req = urllib.request.Request(normalized_url, headers=headers, method="GET")
    with build_http_opener(proxy_url).open(req, timeout=timeout) as resp:
        return decode_response_body(resp)


def http_request_bytes(
    url: str,
    timeout: int = 30,
    extra_headers: Optional[Dict[str, str]] = None,
    proxy_url: str = "",
) -> bytes:
    """读取响应原始字节，用于透传图片等二进制内容。"""
    normalized_url = normalize_http_url(url)
    headers = dict(extra_headers or {})
    req = urllib.request.Request(normalized_url, headers=headers, method="GET")
    with build_http_opener(proxy_url).open(req, timeout=timeout) as resp:
        return resp.read()


def http_request_text_with_final_url(
    url: str,
    timeout: int = 30,
    extra_headers: Optional[Dict[str, str]] = None,
    proxy_url: str = "",
) -> Tuple[str, str]:
    normalized_url = normalize_http_url(url)
    headers = dict(extra_headers or {})
    req = urllib.request.Request(normalized_url, headers=headers, method="GET")
    with build_http_opener(proxy_url).open(req, timeout=timeout) as resp:
        body = decode_response_body(resp)
        return body, str(resp.geturl() or normalized_url)


def http_request_binary(
    url: str,
    timeout: int = 30,
    extra_headers: Optional[Dict[str, str]] = None,
    proxy_url: str = "",
) -> Tuple[bytes, str]:
    normalized_url = normalize_http_url(url)
    headers = dict(extra_headers or {})
    req = urllib.request.Request(normalized_url, headers=headers, method="GET")
    with build_http_opener(proxy_url).open(req, timeout=timeout) as resp:
        content_type = resp.headers.get_content_type() or "application/octet-stream"
        return resp.read(), content_type


def http_resolve_url(
    url: str,
    timeout: int = 30,
    extra_headers: Optional[Dict[str, str]] = None,
    proxy_url: str = "",
) -> str:
    normalized_url = normalize_http_url(url)
    headers = dict(extra_headers or {})
    req = urllib.request.Request(normalized_url, headers=headers, method="GET")
    with build_http_opener(proxy_url).open(req, timeout=timeout) as resp:
        return str(resp.geturl() or normalized_url)
