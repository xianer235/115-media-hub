from typing import Any


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value or default).strip()))
    except Exception:
        return default
