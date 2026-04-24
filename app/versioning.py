import asyncio
import json
import os
import re
import time
from typing import Any, Dict, Tuple

from .http_utils import http_request_json


BASE_DIR = os.path.dirname(os.path.dirname(__file__))
VERSION_FILE = os.path.join(BASE_DIR, "version.json")
VERSION_SOURCE_URL = os.environ.get(
    "VERSION_SOURCE_URL",
    "https://raw.githubusercontent.com/xianer235/115-media-hub/main/version.json",
)
VERSION_CACHE_TTL = int(os.environ.get("VERSION_CACHE_TTL", 6 * 3600))

version_cache: Dict[str, Any] = {"latest": None, "checked_at": 0.0, "error": ""}


def load_local_version() -> Dict[str, Any]:
    try:
        with open(VERSION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            data["version"] = str(data.get("version", "dev")).strip() or "dev"
            return data
    except Exception:
        return {"version": "dev", "notes": [], "changelogUrl": "", "buildDate": ""}


def version_key(value: str) -> Tuple[int, ...]:
    tokens = [token for token in re.split(r"[^\d]+", str(value or "")) if token.isdigit()]
    if not tokens:
        return (0,)
    return tuple(int(token) for token in tokens)


def is_remote_version_newer(local_version: str, remote_version: str) -> bool:
    return version_key(remote_version) > version_key(local_version)


async def get_version_state(force_refresh: bool = False) -> Dict[str, Any]:
    local = load_local_version()
    now = time.time()
    latest = version_cache.get("latest")
    error = version_cache.get("error", "")
    should_refresh = force_refresh or (now - version_cache.get("checked_at", 0)) > VERSION_CACHE_TTL

    if should_refresh:
        try:
            latest = await asyncio.to_thread(http_request_json, VERSION_SOURCE_URL)
            version_cache["latest"] = latest
            version_cache["checked_at"] = now
            version_cache["error"] = ""
            error = ""
        except Exception as exc:
            error = str(exc)
            version_cache["error"] = error
            version_cache["checked_at"] = now

    latest_version = (latest or {}).get("version", "")
    has_update = bool(latest_version and is_remote_version_newer(local.get("version", ""), latest_version))
    return {
        "local": local,
        "latest": latest or {},
        "checked_at": version_cache.get("checked_at", 0),
        "has_update": has_update,
        "error": error,
        "source": VERSION_SOURCE_URL,
    }
