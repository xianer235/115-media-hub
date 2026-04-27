import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
from typing import Any, Dict, List, Optional

from ..http_utils import http_request_json
from ..resource_identity import dedupe_resource_item_dicts
from ..resource_linking import (
    apply_share_receive_code_to_url,
    detect_resource_link_type,
    guess_resource_quality,
    normalize_receive_code,
    parse_115_share_payload,
    parse_quark_share_payload,
    pick_resource_title,
)


PANSOU_SEARCH_TIMEOUT_SECONDS = max(
    3,
    min(60, int(os.environ.get("PANSOU_SEARCH_TIMEOUT_SECONDS", 15) or 15)),
)
PANSOU_SEARCH_TOTAL_LIMIT = max(
    10,
    min(200, int(os.environ.get("PANSOU_SEARCH_TOTAL_LIMIT", 80) or 80)),
)

SUPPORTED_PANSOU_CLOUD_TYPES = ("115", "magnet", "quark")
PANSOU_TOKEN_REFRESH_SKEW_SECONDS = 60
_PANSOU_JWT_CACHE: Dict[str, Dict[str, Any]] = {}


def normalize_pansou_base_url(value: Any) -> str:
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        return ""
    if not raw.lower().startswith(("http://", "https://")):
        raw = f"http://{raw}"
    return raw.rstrip("/")


def normalize_pansou_src(value: Any) -> str:
    normalized = str(value or "all").strip().lower()
    if normalized in ("all", "tg", "plugin"):
        return normalized
    return "all"


def split_pansou_list(value: Any) -> List[str]:
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = str(value or "").replace("，", ",").replace("\n", ",").split(",")
    result: List[str] = []
    seen = set()
    for item in raw_items:
        token = str(item or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        result.append(token)
    return result


def normalize_pansou_auth_header(jwt_token: Any) -> str:
    raw = str(jwt_token or "").strip()
    if not raw:
        return ""
    if raw.lower().startswith("bearer "):
        return raw
    return f"Bearer {raw}"


def _pansou_credentials_configured(cfg: Dict[str, Any]) -> bool:
    return bool(str(cfg.get("pansou_username", "") or "").strip() and str(cfg.get("pansou_password", "") or "").strip())


def _pansou_auth_cache_key(base_url: str, cfg: Dict[str, Any]) -> str:
    username = str(cfg.get("pansou_username", "") or "").strip()
    password = str(cfg.get("pansou_password", "") or "").strip()
    password_fingerprint = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return f"{base_url}|{username}|{password_fingerprint}"


def _extract_pansou_http_error_message(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", errors="ignore")
        payload = json.loads(body or "{}")
        if isinstance(payload, dict):
            message = str(payload.get("error", "") or payload.get("message", "") or payload.get("msg", "") or "").strip()
            if message:
                return message
    except Exception:
        pass
    return ""


def _extract_pansou_login_data(payload: Dict[str, Any]) -> Dict[str, Any]:
    data = _unwrap_pansou_data(payload)
    return data if isinstance(data, dict) else {}


def request_pansou_login(
    cfg: Dict[str, Any],
    timeout_seconds: int = 10,
    *,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    base_url = normalize_pansou_base_url(cfg.get("pansou_base_url", ""))
    if not base_url:
        raise RuntimeError("请先在参数配置中填写 PanSou 地址")
    username = str(cfg.get("pansou_username", "") or "").strip()
    password = str(cfg.get("pansou_password", "") or "").strip()
    if not username or not password:
        raise RuntimeError("PanSou 服务已开启认证，请填写账号和密码")

    cache_key = _pansou_auth_cache_key(base_url, cfg)
    now = time.time()
    cached = _PANSOU_JWT_CACHE.get(cache_key, {}) if not force_refresh else {}
    cached_token = str(cached.get("token", "") or "").strip()
    cached_expires_at = float(cached.get("expires_at", 0) or 0)
    if cached_token and cached_expires_at > now + PANSOU_TOKEN_REFRESH_SKEW_SECONDS:
        return {
            "token": cached_token,
            "expires_at": cached_expires_at,
            "username": username,
            "cached": True,
        }

    try:
        raw = http_request_json(
            f"{base_url}/api/auth/login",
            method="POST",
            payload={"username": username, "password": password},
            timeout=max(3, int(timeout_seconds or 10)),
            extra_headers={
                "Accept": "application/json",
                "User-Agent": "115-media-hub PanSou client",
            },
        )
    except Exception as exc:
        if isinstance(exc, urllib.error.HTTPError):
            detail = _extract_pansou_http_error_message(exc)
            if int(exc.code or 0) in (401, 403):
                raise RuntimeError(f"PanSou 登录失败：{detail or '账号或密码错误'}") from exc
            raise RuntimeError(f"PanSou 登录失败：HTTP {exc.code}") from exc
        if isinstance(exc, urllib.error.URLError):
            raise RuntimeError(f"PanSou 连接失败：{exc.reason or exc}") from exc
        raise RuntimeError(f"PanSou 登录失败：{exc}") from exc

    data = _extract_pansou_login_data(raw)
    token = str(data.get("token", "") or data.get("access_token", "") or "").strip()
    if not token:
        raise RuntimeError("PanSou 登录响应缺少 token，请检查服务版本")
    try:
        expires_at = float(data.get("expires_at", 0) or 0)
    except (TypeError, ValueError):
        expires_at = 0
    if expires_at <= now:
        expires_at = now + 3600
    _PANSOU_JWT_CACHE[cache_key] = {
        "token": token,
        "expires_at": expires_at,
        "username": str(data.get("username", "") or username).strip() or username,
    }
    return {
        "token": token,
        "expires_at": expires_at,
        "username": str(data.get("username", "") or username).strip() or username,
        "cached": False,
    }


def _get_cached_pansou_auth_header(cfg: Dict[str, Any]) -> str:
    base_url = normalize_pansou_base_url(cfg.get("pansou_base_url", ""))
    if not base_url or not _pansou_credentials_configured(cfg):
        return ""
    cache_key = _pansou_auth_cache_key(base_url, cfg)
    cached = _PANSOU_JWT_CACHE.get(cache_key, {})
    token = str(cached.get("token", "") or "").strip()
    expires_at = float(cached.get("expires_at", 0) or 0)
    if token and expires_at > time.time() + PANSOU_TOKEN_REFRESH_SKEW_SECONDS:
        return normalize_pansou_auth_header(token)
    return ""


def _login_pansou_auth_header(
    cfg: Dict[str, Any],
    timeout_seconds: int = 10,
    *,
    force_refresh: bool = False,
) -> str:
    login_result = request_pansou_login(cfg, timeout_seconds=timeout_seconds, force_refresh=force_refresh)
    return normalize_pansou_auth_header(login_result.get("token", ""))


def pansou_cloud_types_for_provider_filter(
    provider_filter: Any,
    *,
    include_magnet_for_115: bool = False,
) -> List[str]:
    normalized = str(provider_filter or "all").strip().lower()
    if normalized in ("115", "115share"):
        if not include_magnet_for_115:
            return ["115"]
        return ["115", "magnet"]
    if normalized in ("magnet", "magnet115"):
        return ["magnet"]
    if normalized == "quark":
        return ["quark"]
    return list(SUPPORTED_PANSOU_CLOUD_TYPES)


def build_pansou_search_payload(
    keyword: str,
    cfg: Dict[str, Any],
    provider_filter: str = "all",
    *,
    include_magnet_for_115: bool = False,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "kw": str(keyword or "").strip(),
        "res": "merge",
        "refresh": False,
        "src": normalize_pansou_src(cfg.get("pansou_src", "all")),
        "cloud_types": pansou_cloud_types_for_provider_filter(
            provider_filter,
            include_magnet_for_115=include_magnet_for_115,
        ),
    }
    channels = split_pansou_list(cfg.get("pansou_channels", ""))
    plugins = split_pansou_list(cfg.get("pansou_plugins", ""))
    if channels:
        payload["channels"] = channels
    if plugins:
        payload["plugins"] = plugins
    return payload


def _format_pansou_http_error(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        if int(exc.code or 0) in (401, 403):
            return "PanSou 认证失败，请检查账号密码"
        return f"PanSou 请求失败：HTTP {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        return f"PanSou 连接失败：{exc.reason or exc}"
    return str(exc or "PanSou 请求失败")


def _unwrap_pansou_data(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    return payload


def _collect_pansou_rows_by_type(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    data = _unwrap_pansou_data(payload)
    rows: List[Dict[str, Any]] = []
    merged = data.get("merged_by_type")
    if isinstance(merged, dict):
        for cloud_type, items in merged.items():
            for raw_item in items if isinstance(items, list) else []:
                if isinstance(raw_item, dict):
                    rows.append({**raw_item, "_cloud_type": str(cloud_type or "").strip().lower()})
        return rows

    results = data.get("results")
    if isinstance(results, list):
        for raw_item in results:
            if not isinstance(raw_item, dict):
                continue
            cloud_type = str(raw_item.get("type", "") or raw_item.get("cloud_type", "") or "").strip().lower()
            if raw_item.get("url"):
                rows.append({**raw_item, "_cloud_type": cloud_type})
                continue
            links = raw_item.get("links")
            if isinstance(links, list):
                for link in links:
                    if isinstance(link, dict):
                        rows.append({**raw_item, **link, "_cloud_type": cloud_type or str(link.get("type", "") or "").strip().lower()})
    return rows


def _resolve_pansou_link_type(cloud_type: str, url: str) -> str:
    normalized_cloud = str(cloud_type or "").strip().lower()
    if normalized_cloud in ("115", "115share"):
        return "115share"
    if normalized_cloud in ("quark", "夸克"):
        return "quark"
    if normalized_cloud == "magnet":
        return "magnet"
    return detect_resource_link_type(url)


def _normalize_pansou_item(row: Dict[str, Any], keyword: str) -> Optional[Dict[str, Any]]:
    raw = row if isinstance(row, dict) else {}
    cloud_type = str(raw.get("_cloud_type", "") or raw.get("type", "") or raw.get("cloud_type", "") or "").strip().lower()
    link_url = str(raw.get("url", "") or raw.get("link", "") or raw.get("share_url", "") or "").strip()
    if not link_url:
        return None

    link_type = _resolve_pansou_link_type(cloud_type, link_url)
    if link_type not in {"115share", "quark", "magnet"}:
        return None

    password = normalize_receive_code(
        raw.get("password", "")
        or raw.get("pwd", "")
        or raw.get("code", "")
        or raw.get("receive_code", "")
    )
    note = str(
        raw.get("note", "")
        or raw.get("title", "")
        or raw.get("name", "")
        or raw.get("content", "")
        or ""
    ).strip()
    raw_text_parts = [part for part in [note, link_url, f"提取码: {password}" if password else ""] if part]
    raw_text = "\n".join(raw_text_parts).strip() or link_url

    if link_type == "115share":
        parsed = parse_115_share_payload(link_url, raw_text, password)
        link_url = str(parsed.get("url", "") or link_url).strip()
        password = normalize_receive_code(parsed.get("receive_code", "")) or password
    elif link_type == "quark":
        parsed = parse_quark_share_payload(link_url, raw_text, password)
        link_url = str(parsed.get("url", "") or link_url).strip()
        password = normalize_receive_code(parsed.get("receive_code", "")) or password
    if link_type == "115share" and password:
        link_url = apply_share_receive_code_to_url(link_url, password)

    source_name = str(raw.get("source", "") or raw.get("channel", "") or raw.get("plugin", "") or "PanSou").strip()
    title = pick_resource_title(raw_text, fallback_title=note or str(raw.get("title", "") or "").strip())
    published_at = str(raw.get("datetime", "") or raw.get("time", "") or raw.get("created_at", "") or "").strip()
    images = raw.get("images") if isinstance(raw.get("images"), list) else []
    cover_url = str(images[0] if images else raw.get("image", "") or raw.get("cover", "") or "").strip()
    extra: Dict[str, Any] = {
        "source_url": str(raw.get("source_url", "") or raw.get("detail_url", "") or "").strip(),
        "source_post_id": str(raw.get("message_id", "") or raw.get("id", "") or "").strip(),
        "pansou_cloud_type": cloud_type,
        "pansou_keyword": str(keyword or "").strip(),
    }
    if password:
        extra["receive_code"] = password
    if cover_url:
        extra["cover_url"] = cover_url

    return {
        "source_type": "pansou",
        "source_name": source_name or "PanSou",
        "channel_name": "",
        "title": title,
        "normalized_title": title.lower(),
        "raw_text": raw_text,
        "link_url": link_url,
        "link_type": link_type,
        "message_url": "",
        "quality": guess_resource_quality(raw_text),
        "year": "",
        "published_at": published_at,
        "receive_code": password,
        "extra": extra,
    }


def normalize_pansou_search_results(payload: Dict[str, Any], keyword: str, limit: int = PANSOU_SEARCH_TOTAL_LIMIT) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for row in _collect_pansou_rows_by_type(payload):
        item = _normalize_pansou_item(row, keyword)
        if item:
            items.append(item)
    deduped = dedupe_resource_item_dicts(items, identity_mode="link")
    return deduped[: max(1, min(int(limit or PANSOU_SEARCH_TOTAL_LIMIT), PANSOU_SEARCH_TOTAL_LIMIT))]


def request_pansou_search(
    cfg: Dict[str, Any],
    keyword: str,
    provider_filter: str = "all",
    timeout_seconds: int = PANSOU_SEARCH_TIMEOUT_SECONDS,
    *,
    include_magnet_for_115: bool = False,
) -> Dict[str, Any]:
    base_url = normalize_pansou_base_url(cfg.get("pansou_base_url", ""))
    query = str(keyword or "").strip()
    if not base_url:
        raise RuntimeError("请先在参数配置中填写 PanSou 地址")
    if not query:
        return {"items": [], "raw": {}, "elapsed_ms": 0, "payload": {}}
    payload = build_pansou_search_payload(
        query,
        cfg,
        provider_filter=provider_filter,
        include_magnet_for_115=include_magnet_for_115,
    )
    headers = {
        "Accept": "application/json",
        "User-Agent": "115-media-hub PanSou client",
    }
    token = _get_cached_pansou_auth_header(cfg)
    started = time.perf_counter()
    try:
        raw = http_request_json(
            f"{base_url}/api/search",
            method="POST",
            payload=payload,
            token=token,
            timeout=max(3, int(timeout_seconds or PANSOU_SEARCH_TIMEOUT_SECONDS)),
            extra_headers=headers,
        )
    except Exception as exc:
        if isinstance(exc, urllib.error.HTTPError) and int(exc.code or 0) in (401, 403):
            if not _pansou_credentials_configured(cfg):
                raise RuntimeError("PanSou 服务已开启认证，请在参数配置中填写账号和密码") from exc
            try:
                token = _login_pansou_auth_header(cfg, timeout_seconds=timeout_seconds, force_refresh=True)
                raw = http_request_json(
                    f"{base_url}/api/search",
                    method="POST",
                    payload=payload,
                    token=token,
                    timeout=max(3, int(timeout_seconds or PANSOU_SEARCH_TIMEOUT_SECONDS)),
                    extra_headers=headers,
                )
            except Exception as retry_exc:
                raise RuntimeError(_format_pansou_http_error(retry_exc)) from retry_exc
        else:
            raise RuntimeError(_format_pansou_http_error(exc)) from exc
    elapsed_ms = max(1, int(round((time.perf_counter() - started) * 1000)))
    return {
        "items": normalize_pansou_search_results(raw, query),
        "raw": raw,
        "elapsed_ms": elapsed_ms,
        "payload": payload,
    }


def test_pansou_health(cfg: Dict[str, Any], timeout_seconds: int = 10) -> Dict[str, Any]:
    base_url = normalize_pansou_base_url(cfg.get("pansou_base_url", ""))
    if not base_url:
        raise RuntimeError("请先填写 PanSou 地址")
    started = time.perf_counter()
    authenticated = False
    try:
        raw = http_request_json(
            f"{base_url}/api/health",
            method="GET",
            timeout=max(3, int(timeout_seconds or 10)),
            extra_headers={
                "Accept": "application/json",
                "User-Agent": "115-media-hub PanSou client",
            },
        )
    except Exception as exc:
        if isinstance(exc, urllib.error.HTTPError) and int(exc.code or 0) in (401, 403):
            if not _pansou_credentials_configured(cfg):
                raise RuntimeError("PanSou 服务已开启认证，请填写账号和密码后再测试") from exc
            token = _login_pansou_auth_header(cfg, timeout_seconds=timeout_seconds, force_refresh=True)
            raw = http_request_json(
                f"{base_url}/api/health",
                method="GET",
                token=token,
                timeout=max(3, int(timeout_seconds or 10)),
                extra_headers={
                    "Accept": "application/json",
                    "User-Agent": "115-media-hub PanSou client",
                },
            )
            authenticated = True
        else:
            raise RuntimeError(_format_pansou_http_error(exc)) from exc
    elapsed_ms = max(1, int(round((time.perf_counter() - started) * 1000)))
    data = _unwrap_pansou_data(raw)
    auth_enabled = bool(data.get("auth_enabled", raw.get("auth_enabled", False)) if isinstance(data, dict) else False)
    plugins = data.get("plugins") if isinstance(data.get("plugins"), list) else raw.get("plugins", [])
    channels = data.get("channels") if isinstance(data.get("channels"), list) else raw.get("channels", [])
    credentials_configured = _pansou_credentials_configured(cfg)
    if auth_enabled and not credentials_configured:
        return {
            "ok": False,
            "reachable": True,
            "auth_enabled": True,
            "auth_configured": False,
            "auth_logged_in": False,
            "latency_ms": elapsed_ms,
            "plugins_enabled": bool(data.get("plugins_enabled", raw.get("plugins_enabled", False))),
            "plugin_count": len(plugins) if isinstance(plugins, list) else 0,
            "channels_count": len(channels) if isinstance(channels, list) else 0,
            "msg": "PanSou 可达，但服务已开启认证，请填写账号和密码后再搜索",
        }
    if auth_enabled and credentials_configured and not authenticated:
        request_pansou_login(cfg, timeout_seconds=timeout_seconds, force_refresh=True)
        authenticated = True
    return {
        "ok": True,
        "reachable": True,
        "auth_enabled": auth_enabled,
        "auth_configured": credentials_configured,
        "auth_logged_in": authenticated,
        "latency_ms": elapsed_ms,
        "plugins_enabled": bool(data.get("plugins_enabled", raw.get("plugins_enabled", False))),
        "plugin_count": len(plugins) if isinstance(plugins, list) else 0,
        "channels_count": len(channels) if isinstance(channels, list) else 0,
        "msg": f"PanSou 可达，延迟约 {elapsed_ms} ms" + ("，账号密码已验证" if authenticated else ""),
    }
