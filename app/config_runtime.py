from typing import Any, Dict, Iterable, List, Tuple


# 非 provider 相关的敏感 key
_STATIC_SENSITIVE_KEYS: Tuple[str, ...] = (
    "password",
    "notify_wecom_webhook",
    "notify_wecom_app_secret",
    "tmdb_api_key",
    "ai_match_api_key",
    "pansou_password",
    "pansou_token",
    "webhook_secret",
)


def _build_sensitive_setting_keys() -> List[str]:
    keys: List[str] = list(_STATIC_SENSITIVE_KEYS)
    try:
        from .providers.registry import list_all as _list_all_providers
        for p in _list_all_providers():
            for ck in p.config_keys:
                if ck and ck not in keys:
                    keys.append(ck)
    except Exception:
        keys.extend(["cookie_115", "cookie_quark"])
    return keys


def _get_sensitive_keys() -> List[str]:
    return _build_sensitive_setting_keys()


def _is_blank_secret_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return str(value).strip() == ""
    return False


def merge_settings_preserve_sensitive(
    existing: Dict[str, Any],
    incoming: Dict[str, Any],
    sensitive_keys: Iterable[str] = None,
) -> Dict[str, Any]:
    if sensitive_keys is None:
        sensitive_keys = _get_sensitive_keys()
    current = existing if isinstance(existing, dict) else {}
    payload = incoming if isinstance(incoming, dict) else {}
    sensitive_key_set = set(sensitive_keys)

    merged = {**current}
    for key, value in payload.items():
        if key in sensitive_key_set and _is_blank_secret_value(value):
            continue
        merged[key] = value
    return merged


def build_public_settings_payload(
    cfg: Dict[str, Any],
    sensitive_keys: Iterable[str] = None,
) -> Dict[str, Any]:
    if sensitive_keys is None:
        sensitive_keys = _get_sensitive_keys()
    from .core import build_cookie_health_payload

    source = cfg if isinstance(cfg, dict) else {}
    safe_payload = {**source}
    meta: Dict[str, bool] = {}
    for key in sensitive_keys:
        value = str(source.get(key, "") or "").strip()
        meta[key] = bool(value)
        if key in safe_payload:
            safe_payload[key] = ""
    safe_payload["sensitive_configured"] = meta
    safe_payload["cookie_health"] = build_cookie_health_payload(source)
    return safe_payload
