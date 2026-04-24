import os
from datetime import datetime
from typing import Any, Dict, List, Set


LOG_DIR = "/app/logs"
LOG_ROTATE_MAX_BYTES = max(
    1024 * 1024,
    int(os.environ.get("LOG_ROTATE_MAX_BYTES", 5 * 1024 * 1024) or (5 * 1024 * 1024)),
)
LOG_ROTATE_BACKUPS = max(1, min(10, int(os.environ.get("LOG_ROTATE_BACKUPS", 2) or 2)))
DEFAULT_EXTENSIONS = "mp4,mkv,avi,mov,wmv,flv,webm,vob,mpg,mpeg,ts,m2ts,mts,rmvb,rm,asf,3gp,m4v,f4v,iso"


def normalize_remote_path(path: str) -> str:
    path = "/" + "/".join([part for part in str(path or "").replace("\\", "/").split("/") if part])
    return path if path != "/" else "/"


def normalize_relative_path(path: str) -> str:
    return "/".join([part for part in str(path or "").replace("\\", "/").split("/") if part])


def join_remote_path(*parts: str) -> str:
    tokens: List[str] = []
    for part in parts:
        tokens.extend([p for p in str(part or "").replace("\\", "/").split("/") if p])
    return "/" + "/".join(tokens) if tokens else "/"


def join_relative_path(*parts: str) -> str:
    tokens: List[str] = []
    for part in parts:
        tokens.extend([p for p in str(part or "").replace("\\", "/").split("/") if p])
    return "/".join(tokens)


def basename(path: str) -> str:
    path = normalize_remote_path(path)
    if path == "/":
        return ""
    return path.rstrip("/").split("/")[-1]


def get_user_extensions(cfg: Dict[str, Any]) -> Set[str]:
    return {
        e.strip().lower()
        for e in str((cfg or {}).get("extensions", DEFAULT_EXTENSIONS)).replace("，", ",").split(",")
        if e.strip()
    }


def is_video_file(name: str, extensions: Set[str]) -> bool:
    if "." not in name:
        return False
    return name.rsplit(".", 1)[-1].lower() in extensions


def format_log_time(with_year: bool = False) -> str:
    return datetime.now().strftime("%m-%d %H:%M:%S" if with_year else "%H:%M:%S")


def rotate_log_file_if_needed(path: str, max_bytes: int = LOG_ROTATE_MAX_BYTES, backups: int = LOG_ROTATE_BACKUPS) -> None:
    if not path or max_bytes <= 0 or backups <= 0:
        return
    try:
        if (not os.path.exists(path)) or os.path.getsize(path) < max_bytes:
            return
    except Exception:
        return
    try:
        oldest = f"{path}.{backups}"
        if os.path.exists(oldest):
            os.remove(oldest)
        for index in range(backups - 1, 0, -1):
            src = f"{path}.{index}"
            dst = f"{path}.{index + 1}"
            if os.path.exists(src):
                os.replace(src, dst)
        os.replace(path, f"{path}.1")
    except Exception:
        # Log rotation must never interrupt the main task flow.
        return


def append_log_file(path: str, line: str) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    rotate_log_file_if_needed(path)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def clear_log_file(path: str, first_line: str) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(first_line + "\n")


def read_log_tail(path: str, limit: int = 200) -> List[str]:
    normalized_limit = max(1, int(limit or 200))
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = [line.rstrip("\n") for line in f.readlines()]
    except Exception:
        return []
    compact = [line for line in lines if str(line or "").strip()]
    if not compact:
        return []
    return compact[-normalized_limit:]


def infer_log_level_from_text(text: str) -> str:
    normalized = str(text or "")
    if "━━━━━━━━━━" in normalized:
        return "task-divider"
    if "··" in normalized and normalized.count("··") >= 2:
        return "section-divider"
    if "生成汇总:" in normalized or "清理汇总:" in normalized:
        return "info"
    lowered = normalized.lower()
    if "error" in lowered or "fail" in lowered or "失败" in normalized or "❌" in normalized:
        return "error"
    if "warn" in lowered or "警告" in normalized or "⚠" in normalized:
        return "warn"
    if "success" in lowered or "完成" in normalized or "成功" in normalized or "✅" in normalized:
        return "success"
    return "info"
