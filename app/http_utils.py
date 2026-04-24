import json
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple


def normalize_http_url(url: str) -> str:
    """
    urllib requires ASCII request URLs, so encode non-ASCII path/query/fragment safely.
    """
    parts = urllib.parse.urlsplit(str(url or "").strip())
    path = urllib.parse.quote(urllib.parse.unquote(parts.path), safe="/%:@+")
    query = urllib.parse.quote(urllib.parse.unquote(parts.query), safe="=&%:@,+")
    fragment = urllib.parse.quote(urllib.parse.unquote(parts.fragment), safe="%:@,+")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, query, fragment))


def build_http_opener(proxy_url: str = ""):
    if proxy_url:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        )
    return urllib.request.build_opener()


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
        charset = resp.headers.get_content_charset() or "utf-8"
        body = resp.read().decode(charset, errors="ignore")
    return json.loads(body or "{}")


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
        charset = resp.headers.get_content_charset() or "utf-8"
        body = resp.read().decode(charset, errors="ignore")
    return json.loads(body or "{}")


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
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="ignore")


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
        charset = resp.headers.get_content_charset() or "utf-8"
        body = resp.read().decode(charset, errors="ignore")
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
