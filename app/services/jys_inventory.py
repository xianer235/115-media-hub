"""极影视库存索引：把极影视（Emby 兼容层）的媒体库索引拉进本地表 ``jys_inventory``。

用途只有一个：给「资源推荐」页提供「这部片库里已经有没有」的判重依据。极影视
识别比本面板强，所以这里**只借它的库存与 TMDB ID**，不做任何识别、不写回极影视。

范围（刻意收窄，见 docs/superpowers/modules.md）：
- 电影只记「有没有」（两态）；剧集额外记「有哪几季、每季几集」到
  ``jys_inventory_season``，**不记单集**（集的追更由订阅任务管）。
- 精确匹配只靠极影视条目自带的 ``ProviderIds.Tmdb``；没有 ID 的条目（BoxSet /
  Folder 聚合节点、以及刮削未出 ID 的单体）**一律跳过**，宁可漏标也不误标。
- 只读极影视：登录 + 拉库，不写任何东西。

为什么季级能拿到：极影视把「一季」渲染成一个独立的 Series 条目，多季共用同一个
剧级 TMDB ID（实测《美国恐怖故事》12 季 = 12 条 Series，tmdb 全是 1413）。它下面
恰好挂一条 Season，``IndexNumber`` 是季号、``ChildCount`` 是该季集数。所以拉一遍
``IncludeItemTypes=Season`` 再按 ``SeriesId → Series.Id`` 回连即可，不需要逐剧发
N+1 请求（实测 7139 季 100% 都能回连）。

实现复用 ``app/services/emby_bridge`` 的登录与分页聚合，不新增第三方依赖。
"""

import asyncio
import logging
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

from ..core import get_config
from ..db import ensure_db, open_db
from .emby_bridge import (
    _aggregate_items,
    _bridge_settings,
    _build_emby_authorization,
    _get_token,
    looks_like_tls_error,
)

logger = logging.getLogger("jys_inventory")

# 后台刷新间隔（秒）：每天一次，覆盖「用户手动存了片却不想等第二天」用设置页手动刷新。
REFRESH_INTERVAL_SECONDS = 24 * 60 * 60

# 明确不参与判重的条目类型（聚合节点，不是单体）。
_SKIP_ITEM_TYPES = {"BoxSet", "Folder", "CollectionFolder", "Playlist", "MusicArtist", "MusicAlbum", "Audio", "Person"}

# 季号合理上限。极影视的 Season.IndexNumber 100% 有值，但实测 6.6% 是乱码级
# （番剧/综艺把集数写进季号，最大到 452）。超过这个值不写库，前端会退化成
# 「已有（未识别到季）」，总比把 S452 当成一季显示强。
MAX_TRUSTED_SEASON_NUMBER = 30

# 刷新状态（供设置页 / 日志展示）。
_refresh_state: Dict[str, Any] = {
    "running": False,
    "last_run_at": "",
    "last_error": "",
    "last_total": 0,
    "last_indexed": 0,
    "last_season_indexed": 0,
}


def _extract_inventory_rows(items: List[Any]) -> List[Dict[str, Any]]:
    """从极影视条目里抽取要入库的行，过滤掉无 TMDB ID 与聚合节点类型。

    返回的行保留 ``item_id``：季条目只带 ``SeriesId``，要靠它回到剧的 TMDB ID。
    """
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
        rows.append({
            "tmdb_id": tmdb_id,
            "name": name,
            "year": year,
            "media_type": media_type,
            "item_id": str(item.get("Id", "") or ""),
        })
    return rows


def _series_tmdb_map(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    """剧条目 Id → TMDB ID。季条目只有 SeriesId，靠这张表回到剧。"""
    mapping: Dict[str, int] = {}
    for row in rows:
        if row.get("media_type") != "tv":
            continue
        item_id = str(row.get("item_id") or "")
        if item_id:
            mapping[item_id] = row["tmdb_id"]
    return mapping


def _extract_season_rows(
    items: List[Any], tmdb_by_series_id: Dict[str, int]
) -> List[Dict[str, Any]]:
    """把季条目映射成 ``(tmdb_id, season_number, episode_count)`` 行。

    极影视的季条目：``SeriesId`` 指向那条「一季一个」的 Series，``IndexNumber``
    是季号，``ChildCount`` 是该季集数（``RecursiveItemCount`` 恒为 null，别用）。
    回连不上剧、季号缺失/越界、集数不合理的条目直接跳过——宁可少标一季。
    """
    rows: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("Type", "") or "") != "Season":
            continue
        series_id = str(item.get("SeriesId") or item.get("ParentId") or "")
        tmdb_id = tmdb_by_series_id.get(series_id)
        if not tmdb_id:
            continue
        try:
            season_number = int(item.get("IndexNumber"))
        except (TypeError, ValueError):
            continue
        if season_number <= 0 or season_number > MAX_TRUSTED_SEASON_NUMBER:
            continue
        episodes_raw = item.get("ChildCount")
        try:
            episode_count: Optional[int] = int(episodes_raw) if episodes_raw not in (None, "") else None
        except (TypeError, ValueError):
            episode_count = None
        if episode_count is not None and episode_count <= 0:
            episode_count = None
        rows.append({
            "tmdb_id": tmdb_id,
            "season_number": season_number,
            "episode_count": episode_count,
        })
    return rows


def _rebuild_inventory(
    rows: List[Dict[str, Any]], season_rows: Optional[List[Dict[str, Any]]] = None
) -> int:
    """全量重建 jys_inventory（先删后插，同一事务提交）。返回写入条数。

    ``season_rows=None`` 表示「这次没拿到季数据」——此时**不动季表**，保留上次的
    季标记，避免一次网络抖动把「已有哪几季」全部抹掉。
    """
    ensure_db()
    conn = open_db()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM jys_inventory")
        cursor.executemany(
            "INSERT OR REPLACE INTO jys_inventory (tmdb_id, name, year, media_type) VALUES (?, ?, ?, ?)",
            [(r["tmdb_id"], r["name"], r["year"], r["media_type"]) for r in rows],
        )
        if season_rows is not None:
            cursor.execute("DELETE FROM jys_inventory_season")
            cursor.executemany(
                "INSERT OR REPLACE INTO jys_inventory_season (tmdb_id, season_number, episode_count) VALUES (?, ?, ?)",
                [(r["tmdb_id"], r["season_number"], r["episode_count"]) for r in season_rows],
            )
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def _explain_refresh_error(exc: BaseException) -> str:
    """把底层的 TLS / 连接错误翻译成能直接照着排查的提示。

    2026-11-26 真机：面板用公网 HTTPS 域名访问自家极影视时刷新失败，报
    ``[SSL: UNEXPECTED_EOF_WHILE_READING]``；同一域名在电脑浏览器里正常、局域网
    地址也正常。对端在 TLS 阶段就掐断连接（域名同时有 AAAA 记录时，容器先连上的
    IPv6 地址是死路最常见），用户只看到一行 SSL 错误根本不知道下一步做什么。
    """
    text = str(exc or "")
    lowered = text.lower()
    if looks_like_tls_error(exc):
        return (
            "连接极影视时 TLS 被中断（%s）。若地址填的是公网 HTTPS 域名，"
            "多半是面板所在网络到该域名不通：可改用局域网地址（如 http://192.168.x.x:8021），"
            "或确认域名没有失效的 IPv6（AAAA）记录、路由器支持 NAT 回环。" % text
        )[:200]
    if "timed out" in lowered or "timeout" in lowered:
        return ("连接极影视超时（%s）：检查地址、端口与容器到该地址的网络连通性。" % text)[:200]
    return text or "刷新失败"


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
        failed_libs: List[str] = []
        for lib in libraries:
            lib_id = str(lib.get("Id", "") or "")
            if not lib_id:
                continue
            query = urllib.parse.urlencode({
                "Recursive": "true",
                "ParentId": lib_id,
                "IncludeItemTypes": "Movie,Series",
            })
            # 页大小压到 300：公网 HTTPS 反代对大响应体更容易断连，库存少几条无所谓。
            status, _, payload = _aggregate_items(
                upstream, "/Users/%s/Items" % uid, query, headers, page_size=300
            )
            if status != 200 or not isinstance(payload, dict):
                logger.warning("jys_inventory 拉库 %s 失败（HTTP %s），跳过", lib.get("Name"), status)
                failed_libs.append(str(lib.get("Name", "") or lib_id))
                continue
            all_rows.extend(_extract_inventory_rows(payload.get("Items") or []))

        # 一个库都没拉到就别重建：`_rebuild_inventory` 是先删后插，空结果会把整张
        # 索引清空（表现是推荐页「已有」角标全消失），比留着上次的旧数据糟得多。
        if not all_rows and failed_libs:
            raise RuntimeError(
                "所有媒体库都没拉到内容（%s），已保留上次索引；请检查极影视地址与网络"
                % "、".join(failed_libs[:3])
            )

        # 去重（同一 tmdb_id 可能出现在多个库），保留第一条
        seen: set = set()
        deduped: List[Dict[str, Any]] = []
        for row in all_rows:
            if row["tmdb_id"] in seen:
                continue
            seen.add(row["tmdb_id"])
            deduped.append(row)

        # 第二趟只拉季：极影视一季一个 Series 条目，靠 SeriesId 回连剧的 tmdb_id。
        # 全部库都失败时 season_rows 保持 None，让 _rebuild_inventory 不动季表。
        tmdb_by_series_id = _series_tmdb_map(all_rows)
        season_rows: List[Dict[str, Any]] = []
        season_failed_libs: List[str] = []
        if tmdb_by_series_id:
            for lib in libraries:
                lib_id = str(lib.get("Id", "") or "")
                if not lib_id:
                    continue
                query = urllib.parse.urlencode({
                    "Recursive": "true",
                    "ParentId": lib_id,
                    "IncludeItemTypes": "Season",
                })
                status, _, payload = _aggregate_items(
                    upstream, "/Users/%s/Items" % uid, query, headers, page_size=300
                )
                if status != 200 or not isinstance(payload, dict):
                    logger.warning("jys_inventory 拉季 %s 失败（HTTP %s），跳过", lib.get("Name"), status)
                    season_failed_libs.append(str(lib.get("Name", "") or lib_id))
                    continue
                season_rows.extend(_extract_season_rows(payload.get("Items") or [], tmdb_by_series_id))

        deduped_seasons: Optional[List[Dict[str, Any]]] = None
        if season_rows or not season_failed_libs:
            seen_seasons: set = set()
            deduped_seasons = []
            for row in season_rows:
                key = (row["tmdb_id"], row["season_number"])
                if key in seen_seasons:
                    continue
                seen_seasons.add(key)
                deduped_seasons.append(row)

        indexed = _rebuild_inventory(deduped, deduped_seasons)
        from ..db import now_text
        _refresh_state.update({
            "running": False,
            "last_run_at": now_text(),
            "last_error": "",
            "last_total": len(all_rows),
            "last_indexed": indexed,
            "last_season_indexed": len(deduped_seasons or []),
        })
        logger.info(
            "jys_inventory 刷新完成：拉取 %s 条，去重后索引 %s 条，季 %s 条",
            len(all_rows), indexed, len(deduped_seasons or []),
        )
        return {"ok": True, "msg": f"已索引 {indexed} 条", "total": len(all_rows), "indexed": indexed}
    except Exception as exc:  # noqa: BLE001 - 后台刷新不能把进程打死
        message = _explain_refresh_error(exc)
        _refresh_state["running"] = False
        _refresh_state["last_error"] = message[:200]
        logger.warning("jys_inventory 刷新失败：%s（原始错误：%s）", message, exc)
        return {"ok": False, "msg": message[:200]}


def inventory_status() -> Dict[str, Any]:
    """返回刷新状态与当前索引条数（条目数 + 季数）。"""
    result = dict(_refresh_state)
    result["indexed_count"] = 0
    result["season_count"] = 0
    try:
        ensure_db()
        conn = open_db()
        try:
            result["indexed_count"] = conn.execute("SELECT COUNT(*) FROM jys_inventory").fetchone()[0]
            result["season_count"] = conn.execute("SELECT COUNT(*) FROM jys_inventory_season").fetchone()[0]
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("jys_inventory 读取计数失败：%s", exc)
    return result


def query_inventory(items: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    """批量判断「已有」：入参每项含 id（tmdb_id）。

    返回 ``{tmdb_id: {"seasons": {"1": 12, "2": 13}}}``，只含命中的条目。
    电影命中时 ``seasons`` 是空字典。季号用字符串键，和前端拿到的 JSON 一致。

    返回结构故意是**对象**而不是 ``True``：前端 ``recommendationOwned[id]`` 的
    truthy 判断保持可用（空字典是 falsy，会把电影角标弄丢）。
    """
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
    result: Dict[int, Dict[str, Any]] = {}
    ensure_db()
    conn = open_db()
    try:
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT tmdb_id FROM jys_inventory WHERE tmdb_id IN ({placeholders})",
            ids,
        ).fetchall()
        for (tmdb_id,) in rows:
            result[int(tmdb_id)] = {"seasons": {}}
        if result:
            found = list(result.keys())
            placeholders = ",".join("?" for _ in found)
            season_rows = conn.execute(
                "SELECT tmdb_id, season_number, episode_count FROM jys_inventory_season "
                f"WHERE tmdb_id IN ({placeholders})",
                found,
            ).fetchall()
            for tmdb_id, season_number, episode_count in season_rows:
                entry = result.get(int(tmdb_id))
                if entry is not None:
                    entry["seasons"][str(int(season_number))] = episode_count
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
