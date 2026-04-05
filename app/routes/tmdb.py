import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..core import *  # noqa: F401,F403

router = APIRouter()


@router.get("/tmdb/search")
async def search_tmdb_endpoint(request: Request) -> Dict[str, Any]:
    cfg = get_config()
    config_error = validate_tmdb_runtime_config(cfg)
    if config_error:
        return JSONResponse(status_code=400, content={"ok": False, "msg": config_error})

    query = str(request.query_params.get("q", "") or "").strip()
    if not query:
        return {"ok": True, "items": [], "query": "", "media_type": "multi"}

    media_type = normalize_tmdb_media_type(request.query_params.get("media_type", ""), fallback="")
    year = normalize_tmdb_year(request.query_params.get("year", "") or "")
    try:
        items = await asyncio.to_thread(search_tmdb_media, query, media_type, year, cfg)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})
    return {
        "ok": True,
        "items": items,
        "query": query,
        "media_type": media_type or "multi",
        "year": year,
    }


@router.get("/tmdb/detail")
async def get_tmdb_detail_endpoint(request: Request) -> Dict[str, Any]:
    cfg = get_config()
    config_error = validate_tmdb_runtime_config(cfg)
    if config_error:
        return JSONResponse(status_code=400, content={"ok": False, "msg": config_error})

    tmdb_id = max(0, parse_int(request.query_params.get("tmdb_id", "0") or "0", 0))
    media_type = normalize_tmdb_media_type(request.query_params.get("media_type", ""), fallback="")
    if tmdb_id <= 0:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "TMDB ID 无效"})
    if media_type not in ("movie", "tv"):
        return JSONResponse(status_code=400, content={"ok": False, "msg": "TMDB 类型仅支持 movie / tv"})

    try:
        detail = await asyncio.to_thread(get_tmdb_media_detail, tmdb_id, media_type, cfg)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "msg": str(exc)})

    task_binding = {
        "tmdb_id": int(detail.get("id", 0) or 0),
        "tmdb_media_type": normalize_tmdb_media_type(detail.get("media_type", ""), fallback=media_type),
        "tmdb_title": str(detail.get("title", "") or "").strip(),
        "tmdb_original_title": str(detail.get("original_title", "") or "").strip(),
        "tmdb_year": normalize_tmdb_year(detail.get("year", "")),
        "tmdb_aliases": detail.get("aliases", []) if isinstance(detail.get("aliases"), list) else [],
        "tmdb_total_episodes": max(0, parse_int(detail.get("total_episodes", 0) or 0, 0)),
        "tmdb_total_seasons": max(0, parse_int(detail.get("total_seasons", 0) or 0, 0)),
        "tmdb_episode_mode": normalize_tmdb_episode_mode(detail.get("episode_mode", "seasonal")),
    }
    if media_type != "tv":
        task_binding["tmdb_total_episodes"] = 0
        task_binding["tmdb_total_seasons"] = 0
        task_binding["tmdb_episode_mode"] = "seasonal"

    return {"ok": True, "detail": detail, "task_binding": task_binding}
