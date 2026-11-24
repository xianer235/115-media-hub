"""极影视库存索引：把极影视（Emby 兼容层）的媒体库索引拉进本地表 ``jys_inventory``。

用途只有一个：给「资源推荐」页提供「这部片库里已经有没有」的判重依据。极影视
识别比本面板强，所以这里**只借它的库存与 TMDB ID**，不做任何识别、不写回极影视。

范围（刻意收窄，见 docs/superpowers/modules.md）：
- 电影 / 剧集都只记「有没有」（两态），不存集数、不做「全有 / 部分有」。
- 精确匹配只靠极影视条目自带的 ``ProviderIds.Tmdb``；没有 ID 的条目（BoxSet /
  Folder 聚合节点、以及刮削未出 ID 的单体）**一律跳过**，宁可漏标也不误标。
- 只读极影视：登录 + 拉库，不写任何东西。

实现复用 ``app/services/emby_bridge`` 的登录与分页聚合，不新增第三方依赖。
"""

import asyncio
import logging
import urllib.parse
from typing import Any, Dict, List, Tuple

from ..core import get_config
from ..db import ensure_db, open_db
from .emby_bridge import (
    _aggregate_items,
    _bridge_settings,
    _build_emby_authorization,
    _get_token,
)

logger = logging.getLogger("jys_inventory")

# 后台刷新间隔（秒）：每天一次，覆盖「用户手动存了片却不想等第二天」用设置页手动刷新。
REFRESH_INTERVAL_SECONDS = 24 * 60 * 60

# 明确不参与判重的条目类型（聚合节点，不是单体）。
_SKIP_ITEM_TYPES = {"BoxSet", "Folder", "CollectionFolder", "Playlist", "MusicArtist", "MusicAlbum", "Audio", "Person"}

# 刷新状态（供设置页 / 日志展示）。
_refresh_state: Dict[str, Any] = {
    "running": False,
    "last_run_at": "",
    "last_error": "",
    "last_total": 0,
    "last_indexed": 0,
}


def _extract_inventory_rows(items: List[Any]) -> List[Dict[str, Any]]:
    """从极影视条目里抽取要入库的行，过滤掉无 TMDB ID 与聚合节点类型。"""
    rows: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("Type", "") or "")
        if item_type in _SKIP_ITEM_TYPES:
            continue
        provider_ids = item.get("ProviderIds")
        tmdb = ""
        if isinstance(provider_ids, dict):
            tmdb = str(provider_ids.get("Tmdb", "") or "").strip()
        if not tmdb:
            continue
        try:
            tmdb_id = int(tmdb)
        except (TypeError, ValueError):
            continue
        name = str(item.get("Name", "") or "").strip()
        if not name:
            continue
        media_type = "tv" if item_type == "Series" else "movie"
        year_raw = item.get("ProductionYear")
        year: Any = None
        try:
            year = int(year_raw) if year_raw not in (None, "", 0) else None
        except (TypeError, ValueError):
            year = None
        rows.append({"tmdb_id": tmdb_id, "name": name, "year": year, "media_type": media_type})
    return rows


def _rebuild_inventory(rows: List[Dict[str, Any]]) -> int:
    """全量重建 jys_inventory（先删后插，同一事务提交）。返回写入条数。"""
    ensure_db()
    conn = open_db()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM jys_inventory")
        cursor.executemany(
            "INSERT OR REPLACE INTO jys_inventory (tmdb_id, name, year, media_type) VALUES (?, ?, ?, ?)",
            [(r["tmdb_id"], r["name"], r["year"], r["media_type"]) for r in rows],
        )
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def refresh_jys_inventory(settings: Dict[str, Any] = None) -> Dict[str, Any]:
    """拉一次极影视全库并重建本地索引。同步函数（调用方自行决定放不放线程）。"""
    s = settings if settings is not None else _bridge_settings()
    if not (s.get("enabled") and s.get("upstream") and s.get("username") and s.get("password")):
        _refresh_state["running"] = False
        _refresh_state["last_error"] = "极影视桥未启用或未配置（地址 / 媒体库账号）"
        return {"ok": False, "msg": _refresh_state["last_error"]}

    _refresh_state["running"] = True
    _refresh_state["last_error"] = ""
    try:
        token_info = _get_token(s)
        uid = str(token_info.get("uid", "") or "")
        token = str(token_info.get("token", "") or "")
        upstream = s["upstream"]
        if not uid or not token:
            raise RuntimeError("极影视登录未返回用户 ID / token")

        headers = {
            "X-Emby-Token": token,
            "X-Emby-Authorization": _build_emby_authorization(
                {"Client": "115-media-hub", "Device": "inventory", "DeviceId": "115-media-hub-inventory", "Version": "1.0.0"}
            ),
            "Accept": "application/json",
        }

        # 列媒体库
        from .emby_bridge import _forward_json
        status, _, views_payload = _forward_json(
            upstream, "GET", f"/Users/{uid}/Views", "", b"", headers, read_timeout=60
        )
        if status != 200 or not isinstance(views_payload, dict):
            raise RuntimeError(f"读取极影视媒体库失败（HTTP {status}）")
        libraries = [item for item in (views_payload.get("Items") or []) if isinstance(item, dict) and item.get("Id")]

        all_rows: List[Dict[str, Any]] = []
        for lib in libraries:
            lib_id = str(lib.get("Id", "") or "")
            if not lib_id:
                continue
            query = urllib.parse.urlencode({
                "Recursive": "true",
                "ParentId": lib_id,
                "IncludeItemTypes": "Movie,Series",
            })
            status, _, payload = _aggregate_items(upstream, "/Users/%s/Items" % uid, query, headers)
            if status != 200 or not isinstance(payload, dict):
                logger.warning("jys_inventory 拉库 %s 失败（HTTP %s），跳过", lib.get("Name"), status)
                continue
            all_rows.extend(_extract_inventory_rows(payload.get("Items") or []))

        # 去重（同一 tmdb_id 可能出现在多个库），保留第一条
        seen: set = set()
        deduped: List[Dict[str, Any]] = []
        for row in all_rows:
            if row["tmdb_id"] in seen:
                continue
            seen.add(row["tmdb_id"])
            deduped.append(row)

        indexed = _rebuild_inventory(deduped)
        from ..db import now_text
        _refresh_state.update({
            "running": False,
            "last_run_at": now_text(),
            "last_error": "",
            "last_total": len(all_rows),
            "last_indexed": indexed,
        })
        logger.info("jys_inventory 刷新完成：拉取 %s 条，去重后索引 %s 条", len(all_rows), indexed)
        return {"ok": True, "msg": f"已索引 {indexed} 条", "total": len(all_rows), "indexed": indexed}
    except Exception as exc:  # noqa: BLE001 - 后台刷新不能把进程打死
        _refresh_state["running"] = False
        _refresh_state["last_error"] = str(exc)[:200]
        logger.warning("jys_inventory 刷新失败：%s", exc)
        return {"ok": False, "msg": str(exc)[:200]}


def inventory_status() -> Dict[str, Any]:
    """返回刷新状态与当前索引条数。"""
    result = dict(_refresh_state)
    result["indexed_count"] = 0
    try:
        ensure_db()
        conn = open_db()
        try:
            result["indexed_count"] = conn.execute("SELECT COUNT(*) FROM jys_inventory").fetchone()[0]
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("jys_inventory 读取计数失败：%s", exc)
    return result


def query_inventory(items: List[Dict[str, Any]]) -> Dict[int, bool]:
    """批量判断「已有」：入参每项含 id（tmdb_id），返回 {tmdb_id: True} 命中集合。"""
    if not items:
        return {}
    ids: List[int] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            tmdb_id = int(item.get("id") or item.get("tmdb_id") or 0)
        except (TypeError, ValueError):
            continue
        if tmdb_id > 0:
            ids.append(tmdb_id)
    if not ids:
        return {}
    result: Dict[int, bool] = {}
    ensure_db()
    conn = open_db()
    try:
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT tmdb_id FROM jys_inventory WHERE tmdb_id IN ({placeholders})",
            ids,
        ).fetchall()
        for (tmdb_id,) in rows:
            result[int(tmdb_id)] = True
    finally:
        conn.close()
    return result


async def jys_inventory_watcher() -> None:
    """后台定时刷新（每天一次）。"""
    await asyncio.sleep(60)
    while True:
        try:
            refresh_jys_inventory()
        except Exception as exc:  # noqa: BLE001 - 定时任务不能把循环打死
            logger.warning("jys_inventory 定时刷新失败：%s", exc)
        await asyncio.sleep(REFRESH_INTERVAL_SECONDS)
