from typing import Any, Dict, Iterable, Tuple


SENSITIVE_SETTING_KEYS: Tuple[str, ...] = (
    "password",
    "cookie_115",
    "cookie_quark",
    "notify_wecom_webhook",
    "notify_wecom_app_secret",
    "tmdb_api_key",
)


def _is_blank_secret_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return str(value).strip() == ""
    return False


def merge_settings_preserve_sensitive(
    existing: Dict[str, Any],
    incoming: Dict[str, Any],
    sensitive_keys: Iterable[str] = SENSITIVE_SETTING_KEYS,
) -> Dict[str, Any]:
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
    sensitive_keys: Iterable[str] = SENSITIVE_SETTING_KEYS,
) -> Dict[str, Any]:
    source = cfg if isinstance(cfg, dict) else {}
    safe_payload = {**source}
    meta: Dict[str, bool] = {}
    for key in sensitive_keys:
        value = str(source.get(key, "") or "").strip()
        meta[key] = bool(value)
        if key in safe_payload:
            safe_payload[key] = ""
    safe_payload["sensitive_configured"] = meta
    return safe_payload
