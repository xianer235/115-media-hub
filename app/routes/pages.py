import os
import re
import threading
import time
from typing import Dict, Optional, Set, Tuple

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

from ..core import *  # noqa: F401,F403

router = APIRouter()
_TEMPLATE_INCLUDE_RE = re.compile(r"{%\s*include\s+[\"']([^\"']+)[\"']\s*%}")
_ASSET_VERSION_CACHE_SECONDS = max(1, int(os.environ.get("ASSET_VERSION_CACHE_SECONDS", 30) or 30))
_TEMPLATE_CACHE_SECONDS = max(0, int(os.environ.get("TEMPLATE_CACHE_SECONDS", 30) or 30))
_CACHE_LOCK = threading.RLock()
_ASSET_VERSION_CACHE: Tuple[float, str] = (0.0, "")
_TEMPLATE_CACHE: Dict[str, Tuple[float, str]] = {}


def _get_asset_version() -> str:
    global _ASSET_VERSION_CACHE
    now = time.monotonic()
    with _CACHE_LOCK:
        cached_at, cached_value = _ASSET_VERSION_CACHE
        if cached_value and (now - cached_at) < _ASSET_VERSION_CACHE_SECONDS:
            return cached_value
    try:
        version_info = load_local_version()
        newest_mtime = 0
        for asset_dir in ("js", "css"):
            for root, _, files in os.walk(os.path.join(STATIC_DIR, asset_dir)):
                for file_name in files:
                    if not file_name.endswith((".js", ".css")):
                        continue
                    try:
                        newest_mtime = max(newest_mtime, int(os.path.getmtime(os.path.join(root, file_name))))
                    except OSError:
                        pass
        raw_asset_version = (
            f"{version_info.get('version', 'dev')}-"
            f"{version_info.get('buildDate', '')}-"
            f"{newest_mtime}"
        )
        asset_version = re.sub(r"[^0-9A-Za-z_.-]+", "-", raw_asset_version).strip("-") or "dev"
    except Exception:
        asset_version = "dev"
    with _CACHE_LOCK:
        _ASSET_VERSION_CACHE = (now, asset_version)
    return asset_version


def _read_template(name: str, seen: Optional[Set[str]] = None) -> str:
    normalized_name = os.path.normpath(str(name or "").strip())
    if not normalized_name or normalized_name.startswith("..") or os.path.isabs(normalized_name):
        raise RuntimeError("模板路径不合法")
    if seen is None and _TEMPLATE_CACHE_SECONDS > 0:
        now = time.monotonic()
        with _CACHE_LOCK:
            cached = _TEMPLATE_CACHE.get(normalized_name)
            if cached and (now - cached[0]) < _TEMPLATE_CACHE_SECONDS:
                return cached[1]

    active_seen = set(seen or set())
    if normalized_name in active_seen:
        raise RuntimeError(f"模板 include 循环：{normalized_name}")
    active_seen.add(normalized_name)
    with open(os.path.join(TEMPLATE_DIR, normalized_name), "r", encoding="utf-8") as f:
        content = f.read()

    def replace_include(match: re.Match[str]) -> str:
        return _read_template(match.group(1), active_seen)

    rendered = _TEMPLATE_INCLUDE_RE.sub(replace_include, content)
    if "{{ asset_version }}" in rendered:
        rendered = rendered.replace("{{ asset_version }}", _get_asset_version())
    if seen is None and _TEMPLATE_CACHE_SECONDS > 0:
        with _CACHE_LOCK:
            _TEMPLATE_CACHE[normalized_name] = (time.monotonic(), rendered)
    return rendered


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> str:
    return _read_template("login.html")


@router.post("/login")
async def do_login(request: Request) -> JSONResponse:
    data = await request.json()
    cfg = get_config()
    if data.get("username") == cfg.get("username") and data.get("password") == cfg.get("password"):
        request.session["logged_in"] = True
        return JSONResponse(content={"ok": True})
    return JSONResponse(status_code=401, content={"ok": False, "msg": "密码错误"})


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    if not request.session.get("logged_in"):
        return RedirectResponse(url="/login")
    return HTMLResponse(_read_template("index.html"))


@router.get("/favicon.ico", include_in_schema=False)
async def favicon_ico() -> FileResponse:
    return FileResponse(FAVICON_PATH, media_type="image/svg+xml")


@router.api_route("/download/userscript/magnet-helper.user.js", methods=["GET", "HEAD"], include_in_schema=False)
async def download_magnet_userscript(request: Request):
    return RedirectResponse(url="/userscript/magnet-helper.user.js", status_code=307)


@router.api_route("/userscript/magnet-helper.user.js", methods=["GET", "HEAD"], include_in_schema=False)
async def install_magnet_userscript(request: Request):
    if not os.path.exists(USERSCRIPT_MAGNET_HELPER_PATH):
        return JSONResponse(status_code=404, content={"ok": False, "msg": "脚本文件不存在"})
    headers = {
        "Cache-Control": "no-store",
    }
    if request.method == "HEAD":
        return Response(status_code=200, media_type="application/javascript; charset=utf-8", headers=headers)
    with open(USERSCRIPT_MAGNET_HELPER_PATH, "r", encoding="utf-8") as f:
        script_text = f.read()
    return Response(
        content=script_text,
        media_type="application/javascript; charset=utf-8",
        headers=headers,
    )


@router.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/login")
