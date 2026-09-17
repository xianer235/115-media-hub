"""OpenAI 兼容大模型辅助刮削识别。

对确定性识别未自动匹配的条目，先让模型产出「关键词 + 年份 + 媒体类型」用于 TMDB 搜索，
再对 TMDB 候选做二次选择。所有失败都返回结构化错误，由调用方决定是否回退到现有规则结果。
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple

import requests

from ..core import get_config, normalize_tmdb_media_type, normalize_tmdb_year


AI_MATCH_DEFAULT_TIMEOUT_SECONDS = 20
AI_MATCH_MIN_TIMEOUT_SECONDS = 3
AI_MATCH_MAX_TIMEOUT_SECONDS = 120
AI_MATCH_DEFAULT_CONCURRENCY = 3
AI_MATCH_MIN_CONCURRENCY = 1
AI_MATCH_MAX_CONCURRENCY = 8
AI_MATCH_MAX_CANDIDATES = 5
AI_MATCH_MAX_KEYWORD_CHARS = 120
AI_MATCH_MAX_REASON_CHARS = 200
AI_MATCH_SAMPLE_FILE_LIMIT = 10
AI_MATCH_OVERVIEW_CHARS = 200


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


def build_ai_match_runtime_config(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    active_cfg = cfg if isinstance(cfg, dict) else get_config()
    return {
        "enabled": bool(active_cfg.get("ai_match_enabled", False)),
        "base_url": str(active_cfg.get("ai_match_base_url", "") or "").strip().rstrip("/"),
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
        "disable_thinking": bool(active_cfg.get("ai_match_disable_thinking", True)),
        "max_candidates": AI_MATCH_MAX_CANDIDATES,
    }


def validate_ai_match_runtime_config(cfg: Optional[Dict[str, Any]] = None) -> Optional[str]:
    runtime = build_ai_match_runtime_config(cfg)
    if not runtime["enabled"]:
        return "AI 刮削辅助未启用"
    if not runtime["base_url"]:
        return "AI 接口地址（base_url）未填写"
    if not runtime["api_key"]:
        return "AI API Key 未填写"
    if not runtime["model"]:
        return "AI 模型名称未填写"
    return None


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
    Ollama / Qwen 等）不识别该字段，可能直接返回 400，因此只在识别为 DeepSeek 时下发。
    """
    base_url = str(runtime.get("base_url") or "").lower()
    model = str(runtime.get("model") or "").lower()
    return "deepseek" in base_url or model.startswith("deepseek")


def _ai_chat_json(runtime: Dict[str, Any], messages: List[Dict[str, str]]) -> Tuple[Optional[Dict[str, Any]], str]:
    url = f"{runtime['base_url']}/chat/completions"
    headers = {
        "Authorization": f"Bearer {runtime['api_key']}",
        "Content-Type": "application/json",
    }
    last_error = "AI 接口调用失败"
    # DeepSeek 思考模式默认开启（effort 默认 high），结构化抽取不需要，关掉省时省钱。
    disable_thinking = bool(runtime.get("disable_thinking", True)) and _supports_thinking_control(runtime)
    # 部分 OpenAI 兼容端点不支持 response_format，先带 JSON 模式请求，被拒后去掉重试一次。
    for use_json_mode in (True, False):
        payload: Dict[str, Any] = {
            "model": runtime["model"],
            "messages": messages,
            "temperature": runtime["temperature"],
        }
        if use_json_mode:
            payload["response_format"] = {"type": "json_object"}
        if disable_thinking:
            payload["thinking"] = {"type": "disabled"}
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=runtime["timeout_seconds"])
        except requests.RequestException as exc:
            return None, f"AI 请求失败：{exc}"
        if response.status_code >= 400:
            if use_json_mode and response.status_code in (400, 404, 422):
                continue
            detail = _safe_response_text(response)
            return None, f"AI 接口返回 HTTP {response.status_code}{f'：{detail}' if detail else ''}"
        try:
            data = response.json()
        except ValueError:
            return None, "AI 返回内容不是有效 JSON"
        content = _extract_message_content(data)
        parsed = _parse_json_object(content)
        if parsed is None:
            return None, "AI 返回内容不是有效 JSON"
        return parsed, ""
    return None, last_error


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
    messages = [
        {"role": "system", "content": _QUERY_SYSTEM_PROMPT},
        {"role": "user", "content": _build_query_user_content(item)},
    ]
    data, error = _ai_chat_json(active_runtime, messages)
    if error:
        return {"ok": False, "keyword": "", "year": "", "media_type": "", "error": error}
    payload = data or {}
    keyword = str(payload.get("keyword") or "").strip()[:AI_MATCH_MAX_KEYWORD_CHARS]
    year = normalize_tmdb_year(payload.get("year"))
    media_type = normalize_tmdb_media_type(payload.get("media_type"), "")
    if not keyword:
        return {"ok": False, "keyword": "", "year": "", "media_type": "", "error": "AI 未给出有效关键词"}
    return {"ok": True, "keyword": keyword, "year": year, "media_type": media_type, "error": ""}


def ai_match_select_candidate(
    item: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    runtime: Optional[Dict[str, Any]] = None,
    cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    active_runtime = runtime if isinstance(runtime, dict) else build_ai_match_runtime_config(cfg)
    valid_candidates = [candidate for candidate in (candidates or []) if isinstance(candidate, dict)]
    if not valid_candidates:
        return {"ok": False, "candidate": {}, "tmdb_id": 0, "media_type": "", "confidence": 0, "reason": "", "error": "没有可选的 TMDB 候选"}
    messages = [
        {"role": "system", "content": _SELECT_SYSTEM_PROMPT},
        {"role": "user", "content": _build_select_user_content(item, valid_candidates)},
    ]
    data, error = _ai_chat_json(active_runtime, messages)
    if error:
        return {"ok": False, "candidate": {}, "tmdb_id": 0, "media_type": "", "confidence": 0, "reason": "", "error": error}
    payload = data or {}
    try:
        tmdb_id = int(payload.get("tmdb_id") or 0)
    except (TypeError, ValueError):
        tmdb_id = 0
    if tmdb_id <= 0:
        return {"ok": False, "candidate": {}, "tmdb_id": 0, "media_type": "", "confidence": 0, "reason": "", "error": "AI 未返回有效的 tmdb_id"}
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
        return {"ok": False, "candidate": {}, "tmdb_id": tmdb_id, "media_type": "", "confidence": 0, "reason": "", "error": "AI 选择的条目不在候选列表中"}
    confidence = _clamp_int(payload.get("confidence", 0), 0, 0, 100)
    reason = str(payload.get("reason") or "").strip()[:AI_MATCH_MAX_REASON_CHARS]
    return {
        "ok": True,
        "candidate": matched,
        "tmdb_id": tmdb_id,
        "media_type": normalize_tmdb_media_type(matched.get("media_type"), wanted_type),
        "confidence": confidence,
        "reason": reason,
        "error": "",
    }
