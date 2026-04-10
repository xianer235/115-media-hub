from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

from ..core import *  # noqa: F401,F403

router = APIRouter()


def _read_template(name: str) -> str:
    with open(os.path.join(TEMPLATE_DIR, name), "r", encoding="utf-8") as f:
        return f.read()


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
