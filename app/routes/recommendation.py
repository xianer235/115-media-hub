import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..core import *  # noqa: F401,F403
from ..services.jys_inventory import inventory_status, query_inventory, refresh_jys_inventory

router = APIRouter()


@router.post("/recommendation/inventory")
async def check_recommendation_inventory(request: Request) -> Dict[str, Any]:
    """批量判断「这些片是否已在极影视库里」。

    入参：{"items": [{"id": <tmdb_id>, "title": ..., "year": ..., "media_type": ...}, ...]}
    返回：{"ok": true, "owned": {<tmdb_id>: true}}，只回「已有」的集合（精确匹配，两态）。
    极影视桥未启用 / 未配置 / 索引为空时，返回空 owned，前端表现为「都不标已有」。
    """
    body = await request.json()
    items = body.get("items") or []
    if not isinstance(items, list):
        return {"ok": True, "owned": {}}
    owned = query_inventory(items)
    return {"ok": True, "owned": owned}


@router.post("/recommendation/inventory/refresh")
async def refresh_recommendation_inventory(request: Request) -> Dict[str, Any]:
    """手动刷新极影视库存索引（放线程里跑，避免阻塞事件循环）。"""
    result = await asyncio.to_thread(refresh_jys_inventory)
    return result


@router.get("/recommendation/inventory/status")
async def get_recommendation_inventory_status(request: Request) -> Dict[str, Any]:
    return inventory_status()


@router.get("/recommendation/state")
async def get_recommendation_state(request: Request) -> Dict[str, Any]:
    ensure_db()
    conn = open_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, tmdb_id, media_type, title, original_title, year,
                   poster_url, overview, vote_average, tmdb_detail_json,
                   status, created_at, updated_at
            FROM recommendation_watchlist
            ORDER BY created_at DESC
            """
        )
        rows = cursor.fetchall()
        items: List[Dict[str, Any]] = []
        for row in rows:
            data = sqlite_row_to_dict(row)
            data["tmdb_detail"] = safe_json_loads(data.pop("tmdb_detail_json", "{}"), {})
            items.append(data)
    finally:
        conn.close()
    return {"ok": True, "items": items}


@router.post("/recommendation/watchlist/add")
async def add_to_watchlist(request: Request) -> JSONResponse:
    body = await request.json()
    tmdb_id = max(0, parse_int(body.get("tmdb_id", 0), 0))
    media_type = str(body.get("media_type", "movie") or "movie").strip()
    title = str(body.get("title", "") or "").strip()
    if tmdb_id <= 0:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "TMDB ID 无效"})
    if media_type not in ("movie", "tv"):
        return JSONResponse(status_code=400, content={"ok": False, "msg": "类型仅支持 movie / tv"})
    if not title:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "标题不能为空"})

    original_title = str(body.get("original_title", "") or "").strip()
    year = str(body.get("year", "") or "").strip()
    poster_url = str(body.get("poster_url", "") or "").strip()
    overview = str(body.get("overview", "") or "").strip()
    vote_average = float(body.get("vote_average", 0) or 0)
    tmdb_detail = body.get("tmdb_detail") or {}

    now = now_text()
    ensure_db()
    conn = open_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO recommendation_watchlist
                (tmdb_id, media_type, title, original_title, year, poster_url,
                 overview, vote_average, tmdb_detail_json, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'want', ?, ?)
            ON CONFLICT(tmdb_id, media_type) DO UPDATE SET
                title = excluded.title,
                original_title = excluded.original_title,
                year = excluded.year,
                poster_url = excluded.poster_url,
                overview = excluded.overview,
                vote_average = excluded.vote_average,
                tmdb_detail_json = excluded.tmdb_detail_json,
                updated_at = excluded.updated_at
            """,
            (
                tmdb_id, media_type, title, original_title, year, poster_url,
                overview, vote_average, safe_json_dumps(tmdb_detail), now, now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "msg": "已添加到想看清单"}


@router.post("/recommendation/watchlist/remove")
async def remove_from_watchlist(request: Request) -> JSONResponse:
    body = await request.json()
    item_id = max(0, parse_int(body.get("id", 0), 0))
    if item_id <= 0:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "记录 ID 无效"})

    ensure_db()
    conn = open_db()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM recommendation_watchlist WHERE id = ?", (item_id,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "msg": "已从想看清单移除"}


@router.post("/recommendation/watchlist/update_status")
async def update_watchlist_status(request: Request) -> JSONResponse:
    body = await request.json()
    item_id = max(0, parse_int(body.get("id", 0), 0))
    status = str(body.get("status", "") or "").strip()
    if item_id <= 0:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "记录 ID 无效"})
    if status not in ("want", "subscribed", "done"):
        return JSONResponse(status_code=400, content={"ok": False, "msg": "状态值无效，支持 want / subscribed / done"})

    ensure_db()
    conn = open_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE recommendation_watchlist SET status = ?, updated_at = ? WHERE id = ?",
            (status, now_text(), item_id),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "msg": "状态已更新"}
