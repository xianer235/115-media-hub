"""OpenAI 兼容大模型辅助刮削识别。

对确定性识别未自动匹配的条目，先让模型产出「关键词 + 年份 + 媒体类型」用于 TMDB 搜索，
再对 TMDB 候选做二次选择。所有失败都返回结构化错误，由调用方决定是否回退到现有规则结果。

内置的可选能力：

- 结果缓存：按「条目身份 + TMDB 候选集合 + 模型配置」缓存成功结果，重复识别不再重复调用；
- DeepSeek 思考模式控制：识别到 DeepSeek 端点时默认关闭思考，避免结构化抽取浪费输出 token；
- 有限重试：对超时/连接错误与 429/5xx 做退避重试，提升批量可靠性；
- 用量透传：把响应里的 token 用量返回给调用方，便于统计成本。
"""

import hashlib
import json
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from ..core import get_config, normalize_bool, normalize_tmdb_media_type, normalize_tmdb_year


AI_MATCH_DEFAULT_TIMEOUT_SECONDS = 20
AI_MATCH_MIN_TIMEOUT_SECONDS = 3
AI_MATCH_MAX_TIMEOUT_SECONDS = 120
AI_MATCH_DEFAULT_CONCURRENCY = 3
AI_MATCH_MIN_CONCURRENCY = 1
AI_MATCH_MAX_CONCURRENCY = 8
AI_MATCH_DEFAULT_CACHE_TTL_HOURS = 24
AI_MATCH_MAX_CACHE_TTL_HOURS = 24 * 30
AI_MATCH_CACHE_MAX_ENTRIES = 2000
AI_MATCH_MAX_ATTEMPTS = 3
AI_MATCH_RETRY_BASE_SLEEP_SECONDS = 1.0
AI_MATCH_RETRY_MAX_SLEEP_SECONDS = 8.0
AI_MATCH_RETRY_STATUSES = (429, 500, 502, 503, 504)
AI_MATCH_MAX_CANDIDATES = 5
AI_MATCH_MAX_KEYWORD_CHARS = 120
AI_MATCH_MAX_REASON_CHARS = 200
AI_MATCH_SAMPLE_FILE_LIMIT = 10
AI_MATCH_OVERVIEW_CHARS = 200
AI_MATCH_THINKING_MODES = ("auto", "disabled", "enabled")

AI_MATCH_USAGE_KEYS = (
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "prompt_cache_hit_tokens",
    "calls",
    "cache_hits",
)

_AI_MATCH_CACHE_LOCK = threading.Lock()
_AI_MATCH_CACHE: Dict[str, Dict[str, Any]] = {}


def _clamp_int(value: Any, fallback: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(min_value, min(max_value, parsed))


def _clamp_float(value: Any, fallback: float, min_value: float, max_value: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(min_value, min(max_value, parsed))


def _normalize_thinking_mode(cfg: Dict[str, Any]) -> str:
    """三种取值：auto=仅识别到 DeepSeek 时关闭；disabled=所有端点都关闭；enabled=不干预。"""
    mode = str(cfg.get("ai_match_thinking_mode", "") or "").strip().lower()
    if mode in AI_MATCH_THINKING_MODES:
        return mode
    legacy = cfg.get("ai_match_disable_thinking")
    if legacy is None:
        return "auto"
    return "auto" if normalize_bool(legacy, default=True) else "enabled"


def _normalize_base_url(value: Any) -> str:
    """把用户填的接口地址规范成 base_url。

    官方文档的 base_url 不带路径（如 https://api.deepseek.com），代码会自行拼 /chat/completions；
    但用户常直接粘贴完整地址，这里把多余的 /chat/completions、/completions 去掉，避免拼成
    .../chat/completions/chat/completions 这种 404。
    """
    base = str(value or "").strip().rstrip("/")
    for suffix in ("/chat/completions", "/completions"):
        if base.lower().endswith(suffix):
            base = base[: -len(suffix)].rstrip("/")
    return base


def build_ai_match_runtime_config(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    active_cfg = cfg if isinstance(cfg, dict) else get_config()
    cache_ttl_hours = _clamp_int(
        active_cfg.get("ai_match_cache_ttl_hours", AI_MATCH_DEFAULT_CACHE_TTL_HOURS),
        AI_MATCH_DEFAULT_CACHE_TTL_HOURS,
        0,
        AI_MATCH_MAX_CACHE_TTL_HOURS,
    )
    return {
        "enabled": bool(active_cfg.get("ai_match_enabled", False)),
        "base_url": _normalize_base_url(active_cfg.get("ai_match_base_url", "")),
        "api_key": str(active_cfg.get("ai_match_api_key", "") or "").strip(),
        "model": str(active_cfg.get("ai_match_model", "") or "").strip(),
        "timeout_seconds": _clamp_int(
            active_cfg.get("ai_match_timeout_seconds", AI_MATCH_DEFAULT_TIMEOUT_SECONDS),
            AI_MATCH_DEFAULT_TIMEOUT_SECONDS,
            AI_MATCH_MIN_TIMEOUT_SECONDS,
            AI_MATCH_MAX_TIMEOUT_SECONDS,
        ),
        "temperature": _clamp_float(active_cfg.get("ai_match_temperature", 0), 0.0, 0.0, 2.0),
        "max_concurrency": _clamp_int(
            active_cfg.get("ai_match_max_concurrency", AI_MATCH_DEFAULT_CONCURRENCY),
            AI_MATCH_DEFAULT_CONCURRENCY,
            AI_MATCH_MIN_CONCURRENCY,
            AI_MATCH_MAX_CONCURRENCY,
        ),
        "thinking_mode": _normalize_thinking_mode(active_cfg),
        "min_confidence": _clamp_int(active_cfg.get("ai_match_min_confidence", 0), 0, 0, 100),
        "cache_ttl_hours": cache_ttl_hours,
        "cache_ttl_seconds": cache_ttl_hours * 3600,
        "max_candidates": AI_MATCH_MAX_CANDIDATES,
    }


def validate_ai_match_runtime_config(cfg: Optional[Dict[str, Any]] = None) -> Optional[str]:
    runtime = build_ai_match_runtime_config(cfg)
    if not runtime["enabled"]:
        return "AI 刮削辅助未启用"
    if not runtime["base_url"]:
        return "AI 接口地址（base_url）未填写"
    if not runtime["base_url"].lower().startswith(("http://", "https://")):
        return "AI 接口地址需要以 http:// 或 https:// 开头"
    if "/anthropic" in runtime["base_url"].lower():
        return "AI 接口地址填的是 Anthropic 端点（/anthropic）；本项目只支持 OpenAI 兼容端点，请改用 base_url (OpenAI)"
    if not runtime["api_key"]:
        return "AI API Key 未填写"
    if not runtime["model"]:
        return "AI 模型名称未填写"
    return None


def empty_ai_usage() -> Dict[str, int]:
    return {key: 0 for key in AI_MATCH_USAGE_KEYS}


def merge_ai_usage(target: Dict[str, int], source: Any) -> Dict[str, int]:
    data = source if isinstance(source, dict) else {}
    for key in AI_MATCH_USAGE_KEYS:
        try:
            target[key] = max(0, int(target.get(key, 0) or 0)) + max(0, int(data.get(key, 0) or 0))
        except (TypeError, ValueError):
            continue
    return target


def _normalize_usage(raw: Any) -> Dict[str, int]:
    source = raw if isinstance(raw, dict) else {}
    usage: Dict[str, int] = {}
    for key in AI_MATCH_USAGE_KEYS:
        try:
            usage[key] = max(0, int(source.get(key, 0) or 0))
        except (TypeError, ValueError):
            usage[key] = 0
    if not usage["total_tokens"]:
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
    return usage


def _usage_with(raw_usage: Any, *, calls: int = 0, cache_hits: int = 0) -> Dict[str, int]:
    usage = _normalize_usage(raw_usage)
    usage["calls"] = max(0, int(calls))
    usage["cache_hits"] = max(0, int(cache_hits))
    return usage


def clear_ai_match_cache() -> int:
    with _AI_MATCH_CACHE_LOCK:
        size = len(_AI_MATCH_CACHE)
        _AI_MATCH_CACHE.clear()
    return size


def _item_cache_identity(item: Dict[str, Any]) -> str:
    data = item if isinstance(item, dict) else {}
    entry = data.get("entry") if isinstance(data.get("entry"), dict) else {}
    return json.dumps(
        {
            "name": str(data.get("name") or entry.get("name") or "").strip(),
            "parent": str(entry.get("parent_path") or data.get("parent_path") or "").strip(),
            "files": _sample_file_names(data),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _candidate_cache_signature(candidates: List[Dict[str, Any]]) -> str:
    tokens: List[str] = []
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue
        media_type = normalize_tmdb_media_type(candidate.get("media_type"), "")
        try:
            tmdb_id = int(candidate.get("id", 0) or 0)
        except (TypeError, ValueError):
            tmdb_id = 0
        if tmdb_id > 0:
            tokens.append(f"{media_type}:{tmdb_id}")
    return "|".join(sorted(tokens))


def _cache_key(kind: str, identity: str, runtime: Dict[str, Any], extra: str = "") -> str:
    raw = json.dumps(
        {
            "kind": kind,
            "identity": identity,
            "extra": extra,
            "base_url": runtime.get("base_url", ""),
            "model": runtime.get("model", ""),
            "temperature": runtime.get("temperature", 0),
            "thinking_mode": runtime.get("thinking_mode", "auto"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _cache_get(key: str, ttl_seconds: int) -> Optional[Dict[str, Any]]:
    if ttl_seconds <= 0:
        return None
    now = time.time()
    with _AI_MATCH_CACHE_LOCK:
        entry = _AI_MATCH_CACHE.get(key)
        if not entry:
            return None
        if now - float(entry.get("saved_at", 0) or 0) > ttl_seconds:
            _AI_MATCH_CACHE.pop(key, None)
            return None
        data = entry.get("data")
    return dict(data) if isinstance(data, dict) else None


def _cache_set(key: str, data: Dict[str, Any]) -> None:
    if not isinstance(data, dict):
        return
    with _AI_MATCH_CACHE_LOCK:
        _AI_MATCH_CACHE[key] = {"saved_at": time.time(), "data": dict(data)}
        overflow = len(_AI_MATCH_CACHE) - AI_MATCH_CACHE_MAX_ENTRIES
        if overflow > 0:
            oldest = sorted(
                _AI_MATCH_CACHE.keys(),
                key=lambda item_key: float((_AI_MATCH_CACHE.get(item_key) or {}).get("saved_at", 0) or 0),
            )
            for item_key in oldest[:overflow]:
                _AI_MATCH_CACHE.pop(item_key, None)


def _parse_json_object(text: Any) -> Optional[Dict[str, Any]]:
    raw = str(text or "").strip()
    if not raw:
        return None
    fence = re.match(r"^```[A-Za-z0-9_-]*\s*(.*?)\s*```$", raw, re.S)
    if fence:
        raw = str(fence.group(1) or "").strip()
    payload: Any = None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                payload = json.loads(raw[start : end + 1])
            except (TypeError, ValueError):
                payload = None
    return payload if isinstance(payload, dict) else None


def _extract_message_content(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for part in content:
            if isinstance(part, dict):
                text_value = part.get("text")
                if isinstance(text_value, str):
                    parts.append(text_value)
        return "".join(parts)
    return str(content or "")


def _safe_response_text(response: requests.Response) -> str:
    try:
        text = str(response.text or "").strip()
    except Exception:
        text = ""
    return text[:200]


def _supports_thinking_control(runtime: Dict[str, Any]) -> bool:
    """是否对 DeepSeek 风格的 thinking 参数做控制。

    `thinking: {type: disabled}` 是 DeepSeek 的请求字段；其它 OpenAI 兼容端点（OpenAI /
    Ollama / Qwen 等）不识别该字段，可能直接返回 400，因此 auto 模式只在识别为 DeepSeek 时下发。
    """
    base_url = str(runtime.get("base_url") or "").lower()
    model = str(runtime.get("model") or "").lower()
    return "deepseek" in base_url or model.startswith("deepseek")


def _should_send_thinking_disabled(runtime: Dict[str, Any]) -> bool:
    mode = str(runtime.get("thinking_mode") or "auto").strip().lower()
    if mode == "enabled":
        return False
    if mode == "disabled":
        return True
    return _supports_thinking_control(runtime)


def _parse_retry_after(response: requests.Response) -> float:
    try:
        raw = str(response.headers.get("Retry-After", "") or "").strip()
    except Exception:
        raw = ""
    if not raw:
        return 0.0
    try:
        value = float(raw)
    except ValueError:
        return 0.0
    return max(0.0, min(AI_MATCH_RETRY_MAX_SLEEP_SECONDS, value))


def _ai_chat_json(
    runtime: Dict[str, Any],
    messages: List[Dict[str, str]],
) -> Tuple[Optional[Dict[str, Any]], str, Dict[str, int]]:
    """调用 /chat/completions 并解析 JSON，返回 (parsed, error, usage)。

    对超时/连接错误与 429/5xx 做有限次退避重试；对不支持 response_format 的端点自动去掉该字段重试一次。
    """
    url = f"{runtime['base_url']}/chat/completions"
    headers = {
        "Authorization": f"Bearer {runtime['api_key']}",
        "Content-Type": "application/json",
    }
    send_thinking_disabled = _should_send_thinking_disabled(runtime)
    last_error = "AI 接口调用失败"
    for attempt in range(AI_MATCH_MAX_ATTEMPTS):
        retry_after = 0.0
        transient = False
        for use_json_mode in (True, False):
            payload: Dict[str, Any] = {
                "model": runtime["model"],
                "messages": messages,
                "temperature": runtime["temperature"],
            }
            if use_json_mode:
                payload["response_format"] = {"type": "json_object"}
            if send_thinking_disabled:
                # DeepSeek 思考模式默认开启（effort 默认 high），结构化抽取不需要，关掉省时省钱。
                payload["thinking"] = {"type": "disabled"}
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=runtime["timeout_seconds"])
            except requests.RequestException as exc:
                last_error = f"AI 请求失败：{exc}"
                transient = True
                break
            if response.status_code >= 400:
                if use_json_mode and response.status_code in (400, 404, 422):
                    # 端点不支持 response_format：同一个 attempt 内去掉该字段重试。
                    continue
                detail = _safe_response_text(response)
                last_error = f"AI 接口返回 HTTP {response.status_code}{f'：{detail}' if detail else ''}"
                if response.status_code in AI_MATCH_RETRY_STATUSES:
                    transient = True
                    retry_after = _parse_retry_after(response)
                break
            try:
                data = response.json()
            except ValueError:
                last_error = "AI 返回内容不是有效 JSON"
                transient = True
                break
            content = _extract_message_content(data)
            parsed = _parse_json_object(content)
            if parsed is None:
                # 模型输出不是 JSON：属于内容问题，重试相同输入意义不大，直接返回。
                return None, "AI 返回内容不是有效 JSON", {}
            return parsed, "", _normalize_usage(data.get("usage") if isinstance(data, dict) else {})
        if not transient:
            return None, last_error, {}
        if attempt < AI_MATCH_MAX_ATTEMPTS - 1:
            delay = retry_after if retry_after > 0 else AI_MATCH_RETRY_BASE_SLEEP_SECONDS * (2**attempt)
            time.sleep(min(AI_MATCH_RETRY_MAX_SLEEP_SECONDS, delay))
    return None, last_error, {}


_QUERY_SYSTEM_PROMPT = (
    "你是影视刮削助手。用户会给你网盘里的文件夹名和文件名，可能包含广告、站点后缀、分辨率、"
    "编码等噪声，或中英混排。请判断它最可能对应的影视作品，并给出适合在 TMDB 搜索的关键词。"
    "只返回一个 json 对象，不要任何解释，形如 "
    '{"keyword": "黑客帝国", "year": "1999", "media_type": "movie"}。'
    "json 字段：keyword（字符串，作品名称，中文或原文名均可）、"
    "year（字符串，四位年份，无法确定留空）、media_type（movie 或 tv，无法确定留空）。"
)

_SELECT_SYSTEM_PROMPT = (
    "你是影视刮削助手。用户会给出网盘条目信息和若干 TMDB 候选，请从中选出与之最匹配的一个。"
    "若没有明显匹配，请给较低的 confidence。只返回一个 json 对象，不要任何解释，形如 "
    '{"tmdb_id": 603, "media_type": "movie", "confidence": 90, "reason": "片名与年份一致"}。'
    "json 字段："
    "tmdb_id（整数，必须是候选中的 tmdb_id）、media_type（movie 或 tv）、"
    "confidence（0-100 的整数）、reason（简短中文理由）。"
)


def _sample_file_names(item: Dict[str, Any]) -> List[str]:
    files = item.get("files") if isinstance(item.get("files"), list) else []
    names: List[str] = []
    for entry in files[:AI_MATCH_SAMPLE_FILE_LIMIT]:
        if isinstance(entry, dict):
            value = str(entry.get("name") or "").strip()
            if value:
                names.append(value)
    return names


def _build_query_user_content(item: Dict[str, Any]) -> str:
    data = item if isinstance(item, dict) else {}
    entry = data.get("entry") if isinstance(data.get("entry"), dict) else {}
    name = str(data.get("name") or entry.get("name") or "").strip()
    parent_path = str(entry.get("parent_path") or data.get("parent_path") or "").strip()
    payload = {
        "网盘条目名": name,
        "父目录": parent_path,
        "样例文件名": _sample_file_names(data),
    }
    return json.dumps(payload, ensure_ascii=False)


def _compact_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    overview = str(candidate.get("overview") or "").strip()
    return {
        "tmdb_id": int(candidate.get("id", 0) or 0),
        "media_type": normalize_tmdb_media_type(candidate.get("media_type"), ""),
        "title": str(candidate.get("tmdb_title") or candidate.get("title") or "").strip(),
        "original_title": str(candidate.get("tmdb_original_title") or candidate.get("original_title") or "").strip(),
        "year": str(candidate.get("tmdb_year") or candidate.get("year") or "").strip(),
        "overview": overview[:AI_MATCH_OVERVIEW_CHARS],
        "popularity": candidate.get("popularity", 0),
        "vote_average": candidate.get("vote_average", 0),
    }


def _build_select_user_content(item: Dict[str, Any], candidates: List[Dict[str, Any]]) -> str:
    data = item if isinstance(item, dict) else {}
    entry = data.get("entry") if isinstance(data.get("entry"), dict) else {}
    payload = {
        "网盘条目名": str(data.get("name") or entry.get("name") or "").strip(),
        "父目录": str(entry.get("parent_path") or data.get("parent_path") or "").strip(),
        "样例文件名": _sample_file_names(data),
        "TMDB候选": [_compact_candidate(candidate) for candidate in candidates if isinstance(candidate, dict)],
    }
    return json.dumps(payload, ensure_ascii=False)


def ai_match_generate_query(
    item: Dict[str, Any],
    runtime: Optional[Dict[str, Any]] = None,
    cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    active_runtime = runtime if isinstance(runtime, dict) else build_ai_match_runtime_config(cfg)
    ttl_seconds = max(0, int(active_runtime.get("cache_ttl_seconds", 0) or 0))
    cache_key = _cache_key("query", _item_cache_identity(item), active_runtime)
    if ttl_seconds > 0:
        cached = _cache_get(cache_key, ttl_seconds)
        if cached is not None:
            return {**cached, "cached": True, "usage": _usage_with({}, cache_hits=1)}
    messages = [
        {"role": "system", "content": _QUERY_SYSTEM_PROMPT},
        {"role": "user", "content": _build_query_user_content(item)},
    ]
    data, error, usage = _ai_chat_json(active_runtime, messages)
    if error:
        return {
            "ok": False,
            "keyword": "",
            "year": "",
            "media_type": "",
            "error": error,
            "cached": False,
            "usage": _usage_with(usage, calls=1),
        }
    payload = data or {}
    keyword = str(payload.get("keyword") or "").strip()[:AI_MATCH_MAX_KEYWORD_CHARS]
    year = normalize_tmdb_year(payload.get("year"))
    media_type = normalize_tmdb_media_type(payload.get("media_type"), "")
    if not keyword:
        return {
            "ok": False,
            "keyword": "",
            "year": "",
            "media_type": "",
            "error": "AI 未给出有效关键词",
            "cached": False,
            "usage": _usage_with(usage, calls=1),
        }
    result = {"ok": True, "keyword": keyword, "year": year, "media_type": media_type, "error": ""}
    if ttl_seconds > 0:
        _cache_set(cache_key, result)
    return {**result, "cached": False, "usage": _usage_with(usage, calls=1)}


def ai_match_select_candidate(
    item: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    runtime: Optional[Dict[str, Any]] = None,
    cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    active_runtime = runtime if isinstance(runtime, dict) else build_ai_match_runtime_config(cfg)
    valid_candidates = [candidate for candidate in (candidates or []) if isinstance(candidate, dict)]
    empty_result = {"ok": False, "candidate": {}, "tmdb_id": 0, "media_type": "", "confidence": 0, "reason": ""}
    if not valid_candidates:
        return {**empty_result, "error": "没有可选的 TMDB 候选", "cached": False, "usage": _usage_with({})}
    ttl_seconds = max(0, int(active_runtime.get("cache_ttl_seconds", 0) or 0))
    cache_key = _cache_key(
        "select",
        _item_cache_identity(item),
        active_runtime,
        extra=_candidate_cache_signature(valid_candidates),
    )
    if ttl_seconds > 0:
        cached = _cache_get(cache_key, ttl_seconds)
        if cached is not None:
            return {**cached, "cached": True, "usage": _usage_with({}, cache_hits=1)}
    messages = [
        {"role": "system", "content": _SELECT_SYSTEM_PROMPT},
        {"role": "user", "content": _build_select_user_content(item, valid_candidates)},
    ]
    data, error, usage = _ai_chat_json(active_runtime, messages)
    if error:
        return {**empty_result, "error": error, "cached": False, "usage": _usage_with(usage, calls=1)}
    payload = data or {}
    try:
        tmdb_id = int(payload.get("tmdb_id") or 0)
    except (TypeError, ValueError):
        tmdb_id = 0
    if tmdb_id <= 0:
        return {
            **empty_result,
            "error": "AI 未返回有效的 tmdb_id",
            "cached": False,
            "usage": _usage_with(usage, calls=1),
        }
    wanted_type = normalize_tmdb_media_type(payload.get("media_type"), "")
    matched: Dict[str, Any] = {}
    for candidate in valid_candidates:
        if int(candidate.get("id", 0) or 0) != tmdb_id:
            continue
        if not wanted_type or normalize_tmdb_media_type(candidate.get("media_type"), "") == wanted_type:
            matched = candidate
            break
    if not matched:
        for candidate in valid_candidates:
            if int(candidate.get("id", 0) or 0) == tmdb_id:
                matched = candidate
                break
    if not matched:
        return {
            **empty_result,
            "tmdb_id": tmdb_id,
            "error": "AI 选择的条目不在候选列表中",
            "cached": False,
            "usage": _usage_with(usage, calls=1),
        }
    confidence = _clamp_int(payload.get("confidence", 0), 0, 0, 100)
    reason = str(payload.get("reason") or "").strip()[:AI_MATCH_MAX_REASON_CHARS]
    result = {
        "ok": True,
        "candidate": matched,
        "tmdb_id": tmdb_id,
        "media_type": normalize_tmdb_media_type(matched.get("media_type"), wanted_type),
        "confidence": confidence,
        "reason": reason,
        "error": "",
    }
    if ttl_seconds > 0:
        _cache_set(cache_key, result)
    return {**result, "cached": False, "usage": _usage_with(usage, calls=1)}
