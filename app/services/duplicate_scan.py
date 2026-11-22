"""媒体库查重：把「同一集/同一部电影存了两份以上」找出来，并给出建议保留项。

为什么放在文件管理而不是订阅任务里：
重复是库里既成的事实，跟哪一次任务产生的无关。订阅任务只扫自己那条任务的落点目录，
也只在自己运行时看，看不见手动导入、改名前后残留、别的任务留下的副本，更看不见
两个不同命名的剧集目录。这里按目录扫描，跨来源都能覆盖。

三档判定（判据强弱差别很大，绝不能一律自动删）：

- ``exact``  ：组内存在 SHA1 完全相同的文件 —— 同一份文件换了名字。115/阿里的目录
  列表自带 sha1，不用下载、不花流量。删除零风险。
- ``episode``：同一个剧集目录、同一季、同一集，但 SHA1 不同 —— 同一集的不同版本
  （1080p / 4K / 不同压制组）。**必须人工确认**：不同音轨、不同字幕组的版本可能
  都是用户要留的，所以这里不自动勾选任何一个。
- ``series`` ：同一部剧被存进两个不同命名的目录（``片名 (2024)`` 与
  ``片名.2024.1080p``）。只提示，不提供批量删除——删整目录的一次误操作代价太大。

安全边界（都在服务端再校验一遍，不依赖前端）：
- 只认视频扩展名，字幕 / nfo / 图片 / 压缩包一律不碰；
- 每组至少保留一份；
- 单次删除上限 ``MAX_DELETE_FILES``，超了要求分批；
- 删除复用 ``delete_scraper_entries``，115 走 ``/rb/delete`` 进回收站，可恢复。

扫描范围限定在「当前所在目录」：115 列目录有 0.35 秒节流，全库扫是十几分钟量级，
按目录扫才能做到点了就有反馈。
"""

import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from ..media_tags import parse_media_tags, remove_media_tags
from ..providers.registry import get_or_none as _provider_or_none
from .scraper import (
    SCRAPER_BATCH_MEDIA_EXTENSIONS,
    _require_provider_cookie,
    delete_scraper_entries,
    normalize_scraper_provider,
    resolve_scraper_folder_path,
)

logger = logging.getLogger(__name__)

SCAN_MAX_DEPTH_DEFAULT = 4
SCAN_MAX_DEPTH_LIMIT = 8
SCAN_MAX_DIRS_DEFAULT = 400
SCAN_MAX_DIRS_LIMIT = 2000
SCAN_MAX_ENTRIES_DEFAULT = 20000
SCAN_MAX_ENTRIES_LIMIT = 60000
# 单次删除上限：超过就要求分批，避免一次点下去删掉几百个文件后才发现删错。
MAX_DELETE_FILES = 200
# 一次删除请求的批大小：网盘接口对单请求 fid 数量不敏感，但失败时批量回滚更细。
_DELETE_CHUNK_SIZE = 100


# ============================================================
# 季集解析
#
# 只认「明确的季集标记」，不猜剧情标题：认不出来就归到电影（按目录分组），
# 宁可漏判，也不要因为把第 2 部电影当成 E02 而误合并。
# 即便纯数字文件名被误当成集号，也不会导致误删——重复组的键里带集号，
# 不同集永远不会落进同一组。
# ============================================================

_SEASON_DIR_RE = re.compile(
    r"^(?:s(?:eason)?[\s._-]*0*(\d{1,2})|第\s*([0-9]{1,3})\s*季|第\s*([一二三四五六七八九十]{1,3})\s*季)$",
    re.IGNORECASE,
)
_SXXEXX_RE = re.compile(r"(?i)(?<![a-z0-9])s(\d{1,2})[\s._-]*e(\d{1,4})(?![0-9])")
_CN_EPISODE_RE = re.compile(r"第\s*0*(\d{1,4})\s*(?:集|话|話)")
_EPISODE_RE = re.compile(r"(?i)(?<![a-z0-9])(?:ep|e)[\s._-]*0*(\d{1,4})(?![0-9])")
_YEAR_IN_NAME_RE = re.compile(r"(?<![0-9])(?:19|20)\d{2}(?![0-9])")

_CN_DIGITS = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9,
}

# 画质排序只用于「建议保留哪一份」，不参与是否重复的判定。
_RESOLUTION_RANK = {
    "8K": 6, "2160p": 5, "1440p": 4, "1080p": 3, "1080i": 2,
    "720p": 2, "576p": 1, "480p": 1,
}


def _cn_number_to_int(text: str) -> int:
    """中文季号转换，只覆盖 1~99（``第一季``/``第十季``/``第二十季``）。"""
    raw = str(text or "").strip()
    if not raw:
        return 0
    if "十" not in raw:
        if len(raw) == 1:
            return _CN_DIGITS.get(raw, 0)
        return 0
    head, _, tail = raw.partition("十")
    tens = _CN_DIGITS.get(head, 1) if head else 1
    ones = _CN_DIGITS.get(tail, 0) if tail else 0
    return max(0, tens * 10 + ones)


def _parse_season_dir(name: str) -> int:
    matched = _SEASON_DIR_RE.match(str(name or "").strip())
    if not matched:
        return 0
    if matched.group(1):
        return max(0, int(matched.group(1) or 0))
    if matched.group(2):
        return max(0, int(matched.group(2) or 0))
    return _cn_number_to_int(matched.group(3) or "")


def _find_season_dir(dir_parts: Sequence[str]) -> Tuple[int, int]:
    """从右往左找最近的季目录，返回 (季号, 该段下标)。没找到返回 (0, -1)。"""
    for index in range(len(dir_parts) - 1, -1, -1):
        season = _parse_season_dir(dir_parts[index])
        if season > 0:
            return season, index
    return 0, -1


def _numeric_stem_episode(stem: str) -> int:
    """``03.mkv`` / ``第03集.mkv`` 这类纯数字集号；排除年份与分片后缀。"""
    text = re.sub(r"\s*[\(\[（【]\s*\d{1,2}\s*[\)\]）】]\s*$", "", str(stem or "").strip())
    compact = re.sub(r"[\s._\-(){}\[\]<>【】（）「」《》]+", "", text)
    if not compact or not compact.isdigit():
        return 0
    if len(compact) > 4:
        return 0
    value = int(compact)
    if value <= 0 or value > 5000 or 1900 <= value <= 2099:
        return 0
    return value


def _media_extension(name: str) -> str:
    return os.path.splitext(str(name or "").strip())[1].lower()


def is_media_file(name: str) -> bool:
    return _media_extension(name) in SCRAPER_BATCH_MEDIA_EXTENSIONS


def _resolution_label(name: str) -> str:
    parsed = parse_media_tags(str(name or ""))
    groups = parsed.get("groups") if isinstance(parsed, dict) else {}
    resolutions = groups.get("resolution") if isinstance(groups, dict) else None
    if isinstance(resolutions, list) and resolutions:
        return str(resolutions[0] or "")
    return ""


def _classify_media_file(rel_dir: str, name: str) -> Dict[str, Any]:
    """把单个文件归到「某部剧的第几季第几集」或「某个电影目录」。

    ``series_dir`` 用相对扫描根目录的路径，跨目录的同名剧不会互相污染。
    """
    stem = os.path.splitext(str(name or "").strip())[0]
    normalized_dir = "/".join([part for part in str(rel_dir or "").split("/") if part])
    dir_parts = [part for part in normalized_dir.split("/") if part]

    season = 0
    episode = 0
    sxxexx = _SXXEXX_RE.search(stem)
    if sxxexx:
        season = max(0, int(sxxexx.group(1) or 0))
        episode = max(0, int(sxxexx.group(2) or 0))
    if episode <= 0:
        for pattern in (_CN_EPISODE_RE, _EPISODE_RE):
            matched = pattern.search(stem)
            if matched:
                episode = max(0, int(matched.group(1) or 0))
                break
    if episode <= 0:
        episode = _numeric_stem_episode(stem)

    dir_season, dir_season_index = _find_season_dir(dir_parts)
    if season <= 0 and dir_season > 0:
        season = dir_season

    # 解析不出集号：当电影处理，按所在目录分组。同一部电影的两个版本会落进同一组。
    if episode <= 0:
        return {
            "kind": "movie",
            "series_dir": normalized_dir,
            "season": 0,
            "episode": 0,
        }

    if season <= 0:
        season = 1
    series_parts = dir_parts[:dir_season_index] if dir_season_index >= 0 else dir_parts
    return {
        "kind": "tv",
        "series_dir": "/".join(series_parts),
        "season": season,
        "episode": episode,
    }


def _leaf_name(path: str) -> str:
    return str(path or "").rstrip("/").split("/")[-1]


def _modified_sort_value(value: Any) -> int:
    try:
        return max(0, int(float(str(value or "").strip())))
    except Exception:
        return 0


def _file_score(item: Dict[str, Any]) -> Tuple[int, int, int]:
    """建议保留项的排序键：画质高 → 体积大 → 修改时间新。"""
    return (
        _RESOLUTION_RANK.get(str(item.get("resolution", "") or ""), 0),
        max(0, int(item.get("size", 0) or 0)),
        _modified_sort_value(item.get("modified_at")),
    )


# ============================================================
# 目录遍历
# ============================================================


def _walk_media_tree(
    provider_obj: Any,
    cookie: str,
    root_cid: str,
    *,
    max_depth: int,
    max_dirs: int,
    max_entries: int,
) -> Dict[str, Any]:
    """BFS 遍历，返回所有文件的 (所在目录相对路径, 条目)。

    只往下走 ``max_depth`` 层：媒体库结构是 ``剧名/Season 01/文件``，4 层足够覆盖
    少见的 ``剧名/特典/Season 01/文件``，再深基本是误建的多余嵌套。
    """
    queue: List[Tuple[str, int, str]] = [(root_cid, 0, "")]
    visited: Set[str] = set()
    files: List[Dict[str, Any]] = []
    scanned_dirs = 0
    scanned_entries = 0
    failed_dirs = 0
    truncated = False

    while queue:
        if scanned_dirs >= max_dirs or scanned_entries >= max_entries:
            truncated = True
            break
        cid, depth, rel_dir = queue.pop(0)
        if cid in visited:
            continue
        visited.add(cid)
        try:
            entries = provider_obj.list_entries(cookie, cid)
        except Exception as exc:
            failed_dirs += 1
            logger.info("查重扫描：读取目录 %s 失败（%s），已跳过", cid, exc)
            continue
        scanned_dirs += 1
        for entry in entries or []:
            if not isinstance(entry, dict):
                continue
            if scanned_entries >= max_entries:
                truncated = True
                break
            scanned_entries += 1
            name = str(entry.get("name", "") or "").strip()
            entry_id = str(entry.get("id", "") or "").strip()
            if not name or not entry_id:
                continue
            if bool(entry.get("is_dir")):
                if depth < max_depth:
                    queue.append((entry_id, depth + 1, _join_rel(rel_dir, name)))
                continue
            if not is_media_file(name):
                continue
            files.append(
                {
                    "id": entry_id,
                    "name": name,
                    "parent_id": cid,
                    "rel_dir": rel_dir,
                    "path": _join_rel(rel_dir, name),
                    "size": max(0, int(entry.get("size", 0) or 0)),
                    "sha1": str(entry.get("sha1", "") or "").strip().upper(),
                    "modified_at": str(entry.get("modified_at", "") or "").strip(),
                }
            )

    return {
        "files": files,
        "scanned_dirs": scanned_dirs,
        "scanned_entries": scanned_entries,
        "failed_dirs": failed_dirs,
        "truncated": truncated or bool(queue),
    }


def _join_rel(left: str, right: str) -> str:
    parts = [part for part in str(left or "").split("/") if part]
    parts.extend([part for part in str(right or "").split("/") if part])
    return "/".join(parts)


# ============================================================
# 分组与档位判定
# ============================================================


def _build_group(key: Tuple[Any, ...], items: List[Dict[str, Any]], root_path: str) -> Optional[Dict[str, Any]]:
    if len(items) < 2:
        return None
    kind = str(key[0])
    for item in items:
        item.pop("_identity", None)
        item["resolution"] = _resolution_label(item.get("name", ""))
    ranked = sorted(items, key=_file_score, reverse=True)
    keep_id = str(ranked[0].get("id", "") or "")
    for item in items:
        item["recommended_keep"] = item.get("id") == keep_id

    sha1_counter: Dict[str, int] = {}
    for item in items:
        sha1 = str(item.get("sha1", "") or "")
        if sha1:
            sha1_counter[sha1] = sha1_counter.get(sha1, 0) + 1
    exact_pairs = sum(1 for count in sha1_counter.values() if count >= 2)
    tier = "exact" if exact_pairs else "episode"

    if kind == "tv":
        series_dir = str(key[1] or "")
        season = int(key[2] or 0)
        episode = int(key[3] or 0)
        label = f"{_leaf_name(series_dir) or '（根目录）'} · S{season:02d}E{episode:02d}"
        series_name = _leaf_name(series_dir)
        group_id = f"tv|{series_dir}|{season}|{episode}"
    else:
        series_dir = str(key[1] or "")
        label = _leaf_name(series_dir) or "（根目录）"
        series_name = _leaf_name(series_dir)
        group_id = f"movie|{series_dir}"

    keep_size = 0
    reclaimable = 0
    for item in items:
        size = max(0, int(item.get("size", 0) or 0))
        if item.get("recommended_keep"):
            keep_size = size
        elif tier == "exact":
            # 只有确认是同一份文件时，「删掉多余副本能省多少」才是确定的。
            reclaimable += size

    for item in items:
        item["path"] = _join_rel(root_path, str(item.get("path", "") or ""))
        item["sha1_short"] = str(item.get("sha1", "") or "")[:8]

    return {
        "group_id": group_id,
        "kind": kind,
        "tier": tier,
        "label": label,
        "series": series_name,
        "series_dir": series_dir,
        "season": int(key[2] or 0) if kind == "tv" else 0,
        "episode": int(key[3] or 0) if kind == "tv" else 0,
        "files": sorted(items, key=_file_score, reverse=True),
        "exact_sha1_count": exact_pairs,
        "reclaimable_bytes": reclaimable,
        "keep_bytes": keep_size,
    }


def _classify_files(files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """给每个文件补上分类结果，返回能归类的条目。

    分组（找重复）和「同一部剧两个目录」的提示都吃这一份结果：后者要看到**所有**
    剧集目录里的集，不能只看有重复的组——整部剧被存两遍时，每一集都只有一份，
    根本不会成组。
    """
    classified: List[Dict[str, Any]] = []
    for item in files:
        identity = _classify_media_file(str(item.get("rel_dir", "") or ""), str(item.get("name", "") or ""))
        if str(identity.get("kind", "") or "") not in ("tv", "movie"):
            continue
        classified.append(dict(item, _identity=identity))
    return classified


def _build_groups(classified: List[Dict[str, Any]], root_path: str) -> List[Dict[str, Any]]:
    buckets: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
    for item in classified:
        identity = item.get("_identity") if isinstance(item.get("_identity"), dict) else {}
        kind = str(identity.get("kind", "") or "")
        if kind == "tv":
            key: Tuple[Any, ...] = (
                "tv",
                str(identity.get("series_dir", "") or ""),
                int(identity.get("season", 0) or 0),
                int(identity.get("episode", 0) or 0),
            )
        elif kind == "movie":
            key = ("movie", str(identity.get("series_dir", "") or ""))
        else:
            continue
        buckets.setdefault(key, []).append(dict(item))

    groups: List[Dict[str, Any]] = []
    for key, items in buckets.items():
        group = _build_group(key, items, root_path)
        if group:
            groups.append(group)
    # 确定性重复排前面，同集不同版本随后；组内按名称排序保证结果稳定。
    groups.sort(key=lambda group: (0 if group.get("tier") == "exact" else 1, str(group.get("label", ""))))
    return groups


def _normalize_series_key(name: str) -> Tuple[str, str]:
    """剧名归一化：去掉画质/编码等标签、年份、括号和所有分隔符，只留主标题。

    用来识别「同一部剧被存进了两个不同命名的目录」，例如
    ``片名 (2024)`` 与 ``片名.2024.1080p.WEB-DL``。
    """
    raw = str(name or "").strip()
    if not raw:
        return "", ""
    year_match = _YEAR_IN_NAME_RE.search(raw)
    year = year_match.group(0) if year_match else ""
    stripped = remove_media_tags(raw)
    stripped = _YEAR_IN_NAME_RE.sub(" ", stripped)
    stripped = re.sub(r"[\(\)\[\]【】（）「」《》{}<>]+", " ", stripped)
    compact = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", stripped.lower())
    return compact, year


def _build_series_hints(classified: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """同一部剧出现在多个不同命名的目录 → 提示（不给批量删除）。"""
    buckets: Dict[Tuple[str, str], Dict[str, Set[int]]] = {}
    for item in classified:
        identity = item.get("_identity") if isinstance(item.get("_identity"), dict) else {}
        if str(identity.get("kind", "") or "") != "tv":
            continue
        series_dir = str(identity.get("series_dir", "") or "")
        key = _normalize_series_key(_leaf_name(series_dir))
        if not key[0] or len(key[0]) < 2:
            continue
        episodes = buckets.setdefault(key, {})
        episodes.setdefault(series_dir, set()).add(int(identity.get("episode", 0) or 0))

    hints: List[Dict[str, Any]] = []
    for (name, year), per_dir in buckets.items():
        if len(per_dir) < 2:
            continue
        episode_sets = [sorted(values) for values in per_dir.values()]
        common: Set[int] = set(episode_sets[0])
        for values in episode_sets[1:]:
            common &= set(values)
        hints.append(
            {
                "name": name,
                "year": year,
                "paths": sorted(per_dir.keys()),
                "episode_counts": {path: len(values) for path, values in per_dir.items()},
                "shared_episodes": len(common),
            }
        )
    hints.sort(key=lambda item: int(item.get("shared_episodes", 0) or 0), reverse=True)
    return hints


def _clamp_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(float(str(value).strip()))
    except Exception:
        number = default
    return max(low, min(number, high))


# ============================================================
# 对外接口
# ============================================================


def scan_duplicate_media(provider: str, cid: str = "0", options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """扫描指定目录下的重复媒体文件。

    只做只读扫描，不产生任何写操作。
    """
    opts = options if isinstance(options, dict) else {}
    normalized = normalize_scraper_provider(provider)
    cookie = _require_provider_cookie(normalized)
    provider_obj = _provider_or_none(normalized)
    if provider_obj is None:
        raise RuntimeError("网盘类型无效")
    root_cid = str(cid or "0").strip() or "0"
    max_depth = _clamp_int(opts.get("max_depth"), SCAN_MAX_DEPTH_DEFAULT, 1, SCAN_MAX_DEPTH_LIMIT)
    max_dirs = _clamp_int(opts.get("max_dirs"), SCAN_MAX_DIRS_DEFAULT, 1, SCAN_MAX_DIRS_LIMIT)
    max_entries = _clamp_int(opts.get("max_entries"), SCAN_MAX_ENTRIES_DEFAULT, 1, SCAN_MAX_ENTRIES_LIMIT)

    root_path = ""
    try:
        root_path = str(resolve_scraper_folder_path(normalized, root_cid).get("path", "") or "").strip()
    except Exception:
        root_path = ""

    walk = _walk_media_tree(
        provider_obj,
        cookie,
        root_cid,
        max_depth=max_depth,
        max_dirs=max_dirs,
        max_entries=max_entries,
    )
    classified = _classify_files(walk["files"])
    groups = _build_groups(classified, root_path)
    hints = _build_series_hints(classified)

    exact_groups = [group for group in groups if group.get("tier") == "exact"]
    episode_groups = [group for group in groups if group.get("tier") != "exact"]
    return {
        "ok": True,
        "provider": normalized,
        "root_cid": root_cid,
        "root_path": root_path,
        "groups": groups,
        "series_hints": hints,
        "scanned": {
            "dirs": int(walk.get("scanned_dirs", 0) or 0),
            "entries": int(walk.get("scanned_entries", 0) or 0),
            "media_files": len(walk["files"]),
            "failed_dirs": int(walk.get("failed_dirs", 0) or 0),
            "truncated": bool(walk.get("truncated", False)),
        },
        "summary": {
            "group_count": len(groups),
            "exact_groups": len(exact_groups),
            "episode_groups": len(episode_groups),
            "duplicate_files": sum(len(group.get("files", [])) for group in groups),
            "reclaimable_bytes": sum(int(group.get("reclaimable_bytes", 0) or 0) for group in exact_groups),
            "series_hint_count": len(hints),
        },
    }


def plan_duplicate_deletion(
    provider: str,
    groups: Sequence[Dict[str, Any]],
    delete_ids: Sequence[str],
) -> Dict[str, Any]:
    """把前端的勾选结果变成可执行的删除清单，并做服务端二次校验。

    三条硬约束在这里执行（前端勾选不可信）：
    1. 只能删扫描结果里出现过的文件（防伪造 id）；
    2. 每组至少保留一份；
    3. 只删视频扩展名。
    """
    normalized = normalize_scraper_provider(provider)
    wanted = {str(item or "").strip() for item in (delete_ids or []) if str(item or "").strip()}
    if not wanted:
        raise RuntimeError("没有选中要删除的文件")
    if len(wanted) > MAX_DELETE_FILES:
        raise RuntimeError(
            f"一次最多删除 {MAX_DELETE_FILES} 个文件（当前选中 {len(wanted)} 个），请分批清理"
        )

    known: Dict[str, Dict[str, Any]] = {}
    for group in groups or []:
        if not isinstance(group, dict):
            continue
        for item in group.get("files", []) or []:
            if not isinstance(item, dict):
                continue
            entry_id = str(item.get("id", "") or "").strip()
            if entry_id:
                known[entry_id] = dict(item, _group_id=str(group.get("group_id", "") or ""))

    unknown = sorted(wanted - set(known.keys()))
    if unknown:
        raise RuntimeError(f"有 {len(unknown)} 个文件不在本次扫描结果里，请重新扫描后再试")

    for group in groups or []:
        if not isinstance(group, dict):
            continue
        members = [
            str(item.get("id", "") or "").strip()
            for item in (group.get("files", []) or [])
            if isinstance(item, dict)
        ]
        members = [entry_id for entry_id in members if entry_id]
        remaining = [entry_id for entry_id in members if entry_id not in wanted]
        if members and not remaining:
            label = str(group.get("label", "") or group.get("group_id", "") or "某一组")
            raise RuntimeError(f"「{label}」会被整组删空，每组必须至少保留一份")

    items: List[Dict[str, Any]] = []
    total_size = 0
    for entry_id in sorted(wanted):
        item = known[entry_id]
        name = str(item.get("name", "") or "")
        if not is_media_file(name):
            raise RuntimeError(f"「{name}」不是视频文件，已拒绝删除")
        size = max(0, int(item.get("size", 0) or 0))
        total_size += size
        items.append(
            {
                "id": entry_id,
                "name": name,
                "path": str(item.get("path", "") or ""),
                "parent_id": str(item.get("parent_id", "") or ""),
                "size": size,
                "group_id": str(item.get("_group_id", "") or ""),
            }
        )

    return {
        "ok": True,
        "provider": normalized,
        "items": items,
        "file_count": len(items),
        "total_size": total_size,
    }


def delete_duplicate_files(
    provider: str,
    items: Sequence[Dict[str, Any]],
    request_id: str = "",
) -> Dict[str, Any]:
    """按 parent 分批删除，单批失败不影响其它批，返回成功/失败明细。

    走的是文件管理页同一个删除通道（``delete_scraper_entries``）：115 进回收站、
    带监控同步快照、带幂等 request_id，不另开一条删除路径。
    """
    normalized = normalize_scraper_provider(provider)
    normalized_items = [item for item in (items or []) if isinstance(item, dict)]
    if not normalized_items:
        raise RuntimeError("没有要删除的文件")
    if len(normalized_items) > MAX_DELETE_FILES:
        raise RuntimeError(f"一次最多删除 {MAX_DELETE_FILES} 个文件，请分批清理")

    base_request = str(request_id or "").strip() or f"dup-{uuid.uuid4().hex[:12]}"
    by_parent: Dict[str, List[Dict[str, Any]]] = {}
    for item in normalized_items:
        entry_id = str(item.get("id", "") or "").strip()
        if not entry_id:
            continue
        parent_id = str(item.get("parent_id", "") or "").strip()
        by_parent.setdefault(parent_id, []).append(item)

    deleted: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    for parent_id, group_items in by_parent.items():
        for start in range(0, len(group_items), _DELETE_CHUNK_SIZE):
            chunk = group_items[start : start + _DELETE_CHUNK_SIZE]
            entry_ids = [str(item.get("id", "") or "").strip() for item in chunk]
            snapshots = [
                {
                    "id": str(item.get("id", "") or "").strip(),
                    "name": str(item.get("name", "") or ""),
                    "path": str(item.get("path", "") or ""),
                    "parent_id": parent_id,
                    "is_dir": False,
                    "size": max(0, int(item.get("size", 0) or 0)),
                }
                for item in chunk
            ]
            chunk_request_id = f"{base_request}:{parent_id or '0'}:{start}"
            try:
                delete_scraper_entries(normalized, entry_ids, parent_id, snapshots, chunk_request_id)
                deleted.extend(chunk)
            except Exception as exc:
                logger.warning("查重清理：删除 %d 个文件失败（%s）", len(chunk), exc)
                failed.extend([dict(item, error=str(exc)) for item in chunk])

    return {
        "ok": True,
        "provider": normalized,
        "deleted_count": len(deleted),
        "deleted_size": sum(max(0, int(item.get("size", 0) or 0)) for item in deleted),
        "failed_count": len(failed),
        "failed": [
            {
                "name": str(item.get("name", "") or ""),
                "path": str(item.get("path", "") or ""),
                "error": str(item.get("error", "") or ""),
            }
            for item in failed
        ],
        "request_id": base_request,
    }
