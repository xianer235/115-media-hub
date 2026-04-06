import asyncio
import hashlib
import time

from ..core import *  # noqa: F401,F403

SIGNED_HINT_WORDS = (
    "已签到",
    "已经签到",
    "今日已签",
    "今天已签",
    "已签过",
    "签到成功",
    "重复签到",
    "already sign",
    "already signed",
    "signed today",
    "sign success",
)
UNSIGNED_HINT_WORDS = (
    "未签到",
    "尚未签到",
    "今日未签",
    "可签到",
    "需要签到",
    "need sign",
    "not sign",
    "unsigned",
)
SIGN_FLAG_KEYS = {
    "sign",
    "is_sign",
    "is_signed",
    "signed",
    "today_signed",
    "today_sign",
    "sign_today",
    "has_sign",
    "has_signed",
    "sign_state",
    "sign_status",
}
NEED_SIGN_KEYS = {
    "need_sign",
    "is_need_sign",
    "need_signin",
    "sign_required",
    "require_sign",
}
SIGN_FLAG_KEYS_COMPACT = {re.sub(r"[^a-z0-9]", "", item.lower()) for item in SIGN_FLAG_KEYS}.union(
    {
        "issign",
        "issigned",
        "todayissign",
        "ispointsign",
        "pointsign",
        "pointsigned",
        "hassigned",
        "hassign",
        "signtoday",
        "todaysign",
        "todaysigned",
    }
)
NEED_SIGN_KEYS_COMPACT = {re.sub(r"[^a-z0-9]", "", item.lower()) for item in NEED_SIGN_KEYS}
REWARD_KEY_PRIORITY = [
    "add_points",
    "today_points",
    "reward_points",
    "bonus_points",
    "gain_points",
    "award_points",
    "points",
    "point",
    "score",
]
BALANCE_KEY_PRIORITY = [
    "balance",
    "points_balance",
    "point_balance",
    "points",
    "point",
    "remain_points",
    "remain",
    "surplus",
    "usable",
    "available",
]


def _iter_key_values(payload: Any) -> List[Tuple[str, Any]]:
    pairs: List[Tuple[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for raw_key, item in value.items():
                key = str(raw_key or "").strip()
                if key:
                    pairs.append((key, item))
                walk(item)
            return
        if isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
    return pairs


def _to_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return int(value)
        except Exception:
            return None
    text = str(value or "").strip()
    if not text:
        return None
    if re.fullmatch(r"-?\d+", text):
        try:
            return int(text)
        except Exception:
            return None
    return None


def _extract_message(payload: Any) -> str:
    if isinstance(payload, str):
        return payload.strip()
    for key, value in _iter_key_values(payload):
        if str(key or "").strip().lower() not in {"msg", "message", "error", "error_msg", "errmsg", "detail"}:
            continue
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _is_signed_message(text: str) -> Optional[bool]:
    message = str(text or "").strip().lower()
    if not message:
        return None
    if any(word in message for word in SIGNED_HINT_WORDS):
        return True
    if any(word in message for word in UNSIGNED_HINT_WORDS):
        return False
    return None


def _extract_sign_flag(payload: Any) -> Optional[bool]:
    def parse_flag_value(value: Any, allow_any_number: bool = False) -> Optional[bool]:
        if isinstance(value, bool):
            return bool(value)
        parsed = _to_int(value)
        if parsed is not None:
            if allow_any_number:
                return parsed > 0
            if parsed in (0, 1):
                return parsed > 0
            return None
        text = str(value or "").strip().lower()
        if text in {"true", "yes", "signed", "sign", "done", "ok", "1", "y"}:
            return True
        if text in {"false", "no", "unsigned", "unsign", "0", "n"}:
            return False
        return None

    for key, value in _iter_key_values(payload):
        normalized_key = str(key or "").strip().lower()
        compact_key = re.sub(r"[^a-z0-9]", "", normalized_key)

        if normalized_key in SIGN_FLAG_KEYS or compact_key in SIGN_FLAG_KEYS_COMPACT:
            parsed = parse_flag_value(value, allow_any_number=True)
            if parsed is not None:
                return parsed

        if normalized_key in NEED_SIGN_KEYS or compact_key in NEED_SIGN_KEYS_COMPACT:
            parsed = parse_flag_value(value, allow_any_number=True)
            if parsed is not None:
                return not parsed

        # 兜底识别：避免把“奖励积分”这类字段误判，限制只接收布尔/0/1 语义。
        if "sign" in compact_key and (
            "today" in compact_key
            or compact_key.startswith("is")
            or compact_key.startswith("has")
            or compact_key.endswith("status")
            or compact_key.endswith("state")
        ):
            parsed = parse_flag_value(value, allow_any_number=False)
            if parsed is not None:
                return parsed

        if "need" in compact_key and "sign" in compact_key:
            parsed = parse_flag_value(value, allow_any_number=False)
            if parsed is not None:
                return not parsed
    return _is_signed_message(_extract_message(payload))


def _extract_int_by_priority(payload: Any, key_priority: List[str]) -> Optional[int]:
    candidates: Dict[str, List[int]] = {}
    for key, value in _iter_key_values(payload):
        parsed = _to_int(value)
        if parsed is None:
            continue
        normalized_key = str(key or "").strip().lower()
        if not normalized_key:
            continue
        candidates.setdefault(normalized_key, []).append(parsed)
    for key in key_priority:
        values = candidates.get(key, [])
        if not values:
            continue
        return max(values)
    return None


def _extract_uid_from_cookie(cookie: str) -> int:
    raw_cookie = str(cookie or "").strip()
    match = re.search(r"(?:^|;\s*)UID=([^;]+)", raw_cookie, flags=re.IGNORECASE)
    if not match:
        return 0
    raw_uid = str(match.group(1) or "").strip()
    digit_match = re.match(r"(\d+)", raw_uid)
    if not digit_match:
        return 0
    try:
        return int(digit_match.group(1))
    except Exception:
        return 0


def _build_115_headers(cookie: str, referer: str = "https://115.com/") -> Dict[str, str]:
    return {
        "Cookie": str(cookie or "").strip(),
        "Accept": "application/json, text/plain, */*",
        "Referer": referer,
        "Origin": "https://115.com",
        "User-Agent": "Mozilla/5.0 115-media-hub",
    }


def _request_sign_info(cookie: str) -> Dict[str, Any]:
    return http_request_json(
        "https://proapi.115.com/android/2.0/user/points_sign",
        extra_headers=_build_115_headers(cookie),
        timeout=30,
    )


def _request_sign_post(cookie: str, user_id: int) -> Dict[str, Any]:
    if user_id <= 0:
        raise RuntimeError("115 Cookie 缺少 UID，无法生成签到 token")
    token_time = int(time.time())
    token = hashlib.sha1(f"{user_id}-Points_Sign@#115-{token_time}".encode("utf-8")).hexdigest()
    return http_request_form_json(
        "https://proapi.115.com/android/2.0/user/points_sign",
        {
            "token": token,
            "token_time": token_time,
        },
        timeout=30,
        extra_headers=_build_115_headers(cookie),
    )


def _request_points_balance(cookie: str) -> Dict[str, Any]:
    return http_request_json(
        "https://points.115.com/api/1.0/web/1.0/user/balance",
        extra_headers=_build_115_headers(cookie),
        timeout=30,
    )


def _is_success_response(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    state = payload.get("state")
    if isinstance(state, bool):
        return state
    state_number = _to_int(state)
    if state_number is not None:
        return state_number > 0
    code = _to_int(payload.get("code"))
    if code is not None:
        return code in (0, 200)
    errno = _to_int(payload.get("errno"))
    if errno is not None:
        return errno == 0
    errcode = _to_int(payload.get("errcode"))
    if errcode is not None:
        return errcode == 0
    return not bool(_extract_message(payload))


def _build_signed_message(reward_leaf: int, balance_leaf: Optional[int], fallback: str = "") -> str:
    message = "今天已签到"
    if reward_leaf > 0:
        message = f"今天已签到，获得 {reward_leaf} 枫叶"
    if balance_leaf is not None and balance_leaf >= 0:
        message = f"{message}（当前 {balance_leaf} 枫叶）"
    if fallback:
        return f"{message}；{fallback}"
    return message


def _is_same_local_day(time_text: str, now_text_value: str = "") -> bool:
    source_text = str(time_text or "").strip()
    if not source_text:
        return False
    today = str(now_text_value or now_text()).strip()[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", today):
        today = datetime.now().strftime("%Y-%m-%d")
    return source_text[:10] == today


async def refresh_sign115_status(force_remote: bool = False, trigger: str = "manual_status") -> Dict[str, Any]:
    cfg = get_config()
    enabled = bool(cfg.get("sign115_enabled", False))
    cookie = str(cfg.get("cookie_115", "")).strip()

    if not cookie:
        set_sign115_status(
            state="error",
            message="未配置 115 Cookie，无法读取签到状态",
            signed_today=None,
            last_trigger=trigger,
        )
        return {"ok": False, **build_sign115_status_payload(cfg)}

    if sign115_runtime.get("running"):
        return {"ok": False, "message": "签到任务正在执行中", **build_sign115_status_payload(cfg)}

    now_ts = time.time()
    if (
        not force_remote
        and float(sign115_runtime.get("last_checked_ts", 0.0) or 0.0) > 0
        and (now_ts - float(sign115_runtime.get("last_checked_ts", 0.0) or 0.0)) < 45
    ):
        return {"ok": True, **build_sign115_status_payload(cfg)}

    sign115_runtime["running"] = True
    set_sign115_status(state="checking", message="正在读取签到状态...", last_trigger=trigger)
    try:
        info = await asyncio.to_thread(_request_sign_info, cookie)
        signed_today = _extract_sign_flag(info)
        info_message = _extract_message(info)
        stored_reward_leaf = max(0, int(sign115_status.get("reward_leaf", 0) or 0))
        if not _is_same_local_day(str(sign115_status.get("last_sign_at", "") or "")):
            stored_reward_leaf = 0
        balance_leaf: Optional[int] = None
        try:
            balance_payload = await asyncio.to_thread(_request_points_balance, cookie)
            balance_leaf = _extract_int_by_priority(balance_payload, BALANCE_KEY_PRIORITY)
        except Exception:
            balance_leaf = None

        if signed_today is True:
            message = _build_signed_message(
                reward_leaf=stored_reward_leaf,
                balance_leaf=balance_leaf,
                fallback=info_message,
            )
            if not enabled:
                message = f"{message}；定时签到未启用"
            state = "signed"
        elif signed_today is False:
            message = "今天未签到，可手动签到"
            if info_message:
                message = f"{message}；{info_message}"
            if not enabled:
                message = f"{message}；定时签到未启用"
            state = "unsigned"
        else:
            # 远端未明确返回签到标记时，优先复用“今天已签到”的本地记录。
            if _is_same_local_day(str(sign115_status.get("last_sign_at", "") or "")):
                signed_today = True
                message = _build_signed_message(
                    reward_leaf=stored_reward_leaf,
                    balance_leaf=balance_leaf,
                    fallback=info_message or "远端未返回明确签到标记，已沿用今日签到记录",
                )
                if not enabled:
                    message = f"{message}；定时签到未启用"
                state = "signed"
            else:
                message = info_message or "签到状态读取成功，但未识别到是否已签到"
                if not enabled:
                    message = f"{message}；定时签到未启用"
                state = "idle"

        set_sign115_status(
            state=state,
            message=message,
            signed_today=signed_today,
            reward_leaf=stored_reward_leaf if signed_today is True else 0,
            balance_leaf=balance_leaf,
            last_checked_at=now_text(),
            last_trigger=trigger,
        )
        sign115_runtime["last_checked_ts"] = time.time()
        return {"ok": True, **build_sign115_status_payload(cfg)}
    except Exception as exc:
        set_sign115_status(
            state="error",
            message=f"读取签到状态失败：{str(exc)}",
            last_checked_at=now_text(),
            last_trigger=trigger,
        )
        sign115_runtime["last_checked_ts"] = time.time()
        return {"ok": False, **build_sign115_status_payload(cfg)}
    finally:
        sign115_runtime["running"] = False


async def run_sign115_job(trigger: str = "manual") -> Dict[str, Any]:
    cfg = get_config()
    cookie = str(cfg.get("cookie_115", "")).strip()

    if not cookie:
        set_sign115_status(
            state="error",
            message="未配置 115 Cookie，无法执行签到",
            last_trigger=trigger,
        )
        return {"ok": False, **build_sign115_status_payload(cfg)}
    if sign115_runtime.get("running"):
        return {"ok": False, "message": "签到任务正在执行中", **build_sign115_status_payload(cfg)}

    sign115_runtime["running"] = True
    set_sign115_status(state="checking", message="正在执行签到...", last_trigger=trigger)
    try:
        info = await asyncio.to_thread(_request_sign_info, cookie)
        signed_today = _extract_sign_flag(info)
        info_message = _extract_message(info)
        reward_leaf = 0
        sign_message = ""

        if signed_today is not True:
            uid = _extract_uid_from_cookie(cookie)
            sign_resp = await asyncio.to_thread(_request_sign_post, cookie, uid)
            sign_message = _extract_message(sign_resp)
            if _is_success_response(sign_resp):
                reward_leaf = max(0, int(_extract_int_by_priority(sign_resp, REWARD_KEY_PRIORITY) or 0))
                signed_today = True
            else:
                already_signed = _is_signed_message(sign_message)
                if already_signed is True:
                    signed_today = True
                    reward_leaf = 0
                else:
                    raise RuntimeError(sign_message or "签到失败")

        balance_leaf: Optional[int] = None
        try:
            balance_payload = await asyncio.to_thread(_request_points_balance, cookie)
            balance_leaf = _extract_int_by_priority(balance_payload, BALANCE_KEY_PRIORITY)
        except Exception:
            balance_leaf = None

        if signed_today is True:
            message = _build_signed_message(reward_leaf=reward_leaf, balance_leaf=balance_leaf, fallback=sign_message or info_message)
            state = "signed"
            last_sign_at = now_text()
        else:
            message = sign_message or info_message or "签到未成功"
            state = "unsigned"
            last_sign_at = str(sign115_status.get("last_sign_at", "") or "")

        set_sign115_status(
            state=state,
            message=message,
            signed_today=signed_today,
            reward_leaf=reward_leaf,
            balance_leaf=balance_leaf,
            last_checked_at=now_text(),
            last_sign_at=last_sign_at,
            last_trigger=trigger,
        )
        sign115_runtime["last_checked_ts"] = time.time()
        return {"ok": signed_today is True, **build_sign115_status_payload(cfg)}
    except Exception as exc:
        set_sign115_status(
            state="error",
            message=f"签到失败：{str(exc)}",
            last_checked_at=now_text(),
            last_trigger=trigger,
        )
        sign115_runtime["last_checked_ts"] = time.time()
        return {"ok": False, **build_sign115_status_payload(cfg)}
    finally:
        sign115_runtime["running"] = False
