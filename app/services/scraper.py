import os
import re
import unicodedata
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from ..core import *  # noqa: F401,F403
from ..db import db_connection
from ..providers.pan115 import invalidate_115_entries_cache
from ..providers.registry import get_or_none as get_provider_or_none, list_enabled as list_enabled_providers
from ..media_tags import media_tag_labels, parse_media_tags, remove_media_tags
from ..services.subscription_episode import (
    _extract_numeric_episode_from_filename,
    _extract_subscription_season_from_name,
    _extract_task_episodes_from_file_entry,
)


def _prepare_scraper_monitor_sync(
    provider: str,
    operation: str,
    entries: List[Dict[str, Any]],
    *,
    source_action: str,
    dedupe_key: str,
) -> Dict[str, Any]:
    """Create a durable monitor event before a 115 mutation.

    Importing lazily keeps the provider/browser module usable without making the
    monitor service part of its import graph during application bootstrap.
    """
    from .monitor_changes import prepare_monitor_change_events

    return prepare_monitor_change_events(
        provider=provider,
        operation=operation,
        entries=entries,
        source_action=source_action,
        dedupe_key=dedupe_key,
        cfg=get_config(),
    )


def _finish_scraper_monitor_sync(
    prepared: Dict[str, Any],
    *,
    succeeded: bool,
    error: str = "",
) -> Dict[str, Any]:
    from .monitor_changes import confirm_monitor_change_events

    return confirm_monitor_change_events(prepared, succeeded=succeeded, error=error)


def _update_scraper_monitor_sync(
    prepared: Dict[str, Any],
    entries: List[Dict[str, Any]],
) -> Dict[str, Any]:
    from .monitor_changes import update_monitor_change_event_snapshots

    return update_monitor_change_event_snapshots(prepared, entries)


def _direct_monitor_change_key(action: str, request_id: str = "") -> str:
    token = str(request_id or "").strip() or uuid.uuid4().hex
    return f"scraper:direct:{str(action or '').strip()}:{token}"


def _scraper_snapshot_is_dir(entry: Dict[str, Any]) -> bool:
    value = entry.get("is_dir", False)
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _select_requested_monitor_snapshots(
    entries: Optional[List[Dict[str, Any]]],
    entry_ids: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Bind client snapshots to explicit mutation IDs without positional guesses."""
    requested_ids: List[str] = []
    requested_id_set: Set[str] = set()
    for value in entry_ids or []:
        entry_id = str(value or "").strip()
        if not entry_id or entry_id in requested_id_set:
            continue
        requested_ids.append(entry_id)
        requested_id_set.add(entry_id)

    snapshots_by_id: Dict[str, Dict[str, Any]] = {}
    for raw_entry in entries or []:
        if not isinstance(raw_entry, dict):
            continue
        is_dir = _scraper_snapshot_is_dir(raw_entry)
        entry_id = str(
            raw_entry.get("id", "")
            or (raw_entry.get("cid", "") if is_dir else raw_entry.get("fid", ""))
            or ""
        ).strip()
        if not entry_id or entry_id in snapshots_by_id:
            continue
        if requested_id_set and entry_id not in requested_id_set:
            continue
        snapshots_by_id[entry_id] = {
            **raw_entry,
            "id": entry_id,
            "is_dir": is_dir,
        }

    if requested_ids:
        return [snapshots_by_id[entry_id] for entry_id in requested_ids if entry_id in snapshots_by_id]
    return list(snapshots_by_id.values())


def _build_transfer_monitor_snapshots(
    provider: str,
    entries: Optional[List[Dict[str, Any]]],
    target_parent_path: Optional[str],
    target_parent_id: str = "",
    *,
    operation: str = "move",
    entry_ids: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    if str(provider or "").strip().lower() != "115" or not isinstance(entries, list) or target_parent_path is None:
        return []
    target_path = normalize_relative_path(target_parent_path)
    snapshots: List[Dict[str, Any]] = []
    selected_entries = _select_requested_monitor_snapshots(entries, entry_ids)
    for source in selected_entries:
        old_path = normalize_relative_path(str(source.get("path", "") or ""))
        name = str(source.get("name", "") or basename(old_path)).strip()
        if not old_path or not name:
            continue
        is_dir = bool(source.get("is_dir"))
        entry_id = str(source.get("id", "") or "").strip()
        source_id = str(source.get("cid", "") or (source.get("id", "") if is_dir else "") or "").strip()
        if is_dir and not source_id:
            source_id = entry_id
        normalized_operation = str(operation or "").strip().lower()
        snapshots.append(
            {
                **source,
                "id": entry_id,
                "old_path": old_path,
                "new_path": join_relative_path(target_path, name),
                "old_parent_id": str(source.get("parent_id", "") or "").strip(),
                "new_parent_id": str(target_parent_id or "").strip(),
                "old_cid": source_id,
                "new_cid": source_id if is_dir and provider == "115" and normalized_operation == "move" else "",
            }
        )
    return snapshots


def _extract_copy_destination_cids(
    result: Dict[str, Any],
    snapshots: List[Dict[str, Any]],
    *,
    target_parent_id: str = "",
    request_id: str = "",
) -> List[Dict[str, Any]]:
    """Read only explicit destination IDs returned by the copy operation.

    115 response shapes vary between endpoints.  This accepts explicit copied
    entry records and single-folder destination IDs, while rejecting source
    IDs and parent CIDs.  If the response does not identify the new folder, the
    event remains without ``new_cid`` and the bounded worker retains it as a
    failed event instead of traversing by path.
    """
    directory_snapshots = [item for item in snapshots if isinstance(item, dict) and bool(item.get("is_dir"))]
    if not directory_snapshots or not isinstance(result, dict):
        return []
    globally_rejected_ids = {
        str(target_parent_id or "").strip(),
        str(request_id or "").strip(),
        "",
        "0",
    }

    explicit_list_keys = {
        "new_cids",
        "copied_cids",
        "destination_cids",
        "new_folder_cids",
        "new_folder_ids",
    }

    def build_explicit_list_updates(value: Any) -> List[Dict[str, Any]]:
        if not isinstance(value, list) or len(value) != len(directory_snapshots):
            return []
        normalized_cids = [str(item or "").strip() for item in value]
        if not normalized_cids or any(not cid or cid == "0" for cid in normalized_cids):
            return []
        if len(set(normalized_cids)) != len(normalized_cids):
            return []
        updates: List[Dict[str, Any]] = []
        for snapshot, destination_cid in zip(directory_snapshots, normalized_cids):
            rejected_ids = {
                str(snapshot.get("id", "") or "").strip(),
                str(snapshot.get("old_cid", "") or "").strip(),
                str(snapshot.get("old_parent_id", "") or "").strip(),
                str(snapshot.get("new_parent_id", "") or "").strip(),
                *globally_rejected_ids,
            }
            if destination_cid in rejected_ids:
                return []
            updates.append(
                {
                    "id": str(snapshot.get("id", "") or "").strip(),
                    "old_path": str(snapshot.get("old_path", "") or ""),
                    "new_path": str(snapshot.get("new_path", "") or ""),
                    "new_cid": destination_cid,
                }
            )
        return updates

    def find_explicit_destination_list(value: Any) -> List[Dict[str, Any]]:
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key or "").strip().lower() in explicit_list_keys:
                    updates = build_explicit_list_updates(child)
                    if updates:
                        return updates
                nested = find_explicit_destination_list(child)
                if nested:
                    return nested
        elif isinstance(value, list):
            for child in value:
                nested = find_explicit_destination_list(child)
                if nested:
                    return nested
        return []

    explicit_updates = find_explicit_destination_list(result)
    if explicit_updates:
        return explicit_updates

    roots: List[Any] = []
    root_keys = (
        "copied_entries",
        "new_entries",
        "copied_entry_ids",
        "new_entry_ids",
        "data",
    )
    for key in root_keys:
        if key in result:
            roots.append(result.get(key))
    response = result.get("response")
    if isinstance(response, dict):
        for key in root_keys:
            if key in response:
                roots.append(response.get(key))

    source_keys = ("source_id", "source_cid", "old_id", "old_cid", "origin_id", "from_id")
    destination_keys = (
        "new_cid",
        "destination_cid",
        "dest_cid",
        "copied_cid",
        "new_folder_id",
        "folder_id",
        "new_id",
        "destination_id",
        "dest_id",
        "cid",
        "file_id",
        "id",
    )
    candidates: List[Dict[str, str]] = []

    def collect(value: Any, source_hint: str = "") -> None:
        if isinstance(value, list):
            for child in value:
                collect(child, source_hint)
            return
        if not isinstance(value, dict):
            scalar = str(value or "").strip()
            if source_hint and scalar:
                candidates.append({"source_id": source_hint, "name": "", "cid": scalar})
            return

        source_id = next(
            (str(value.get(key, "") or "").strip() for key in source_keys if str(value.get(key, "") or "").strip()),
            source_hint,
        )
        name = str(value.get("name", "") or value.get("file_name", "") or "").strip()
        destination_id = next(
            (
                str(value.get(key, "") or "").strip()
                for key in destination_keys
                if str(value.get(key, "") or "").strip() and str(value.get(key, "") or "").strip() != "0"
            ),
            "",
        )
        if destination_id:
            candidates.append({"source_id": source_id, "name": name, "cid": destination_id})
        for key, child in value.items():
            key_text = str(key or "").strip()
            next_source_hint = key_text if key_text and any(
                key_text == str(item.get("id", "") or "").strip() for item in directory_snapshots
            ) else source_id
            if isinstance(child, (dict, list)) or next_source_hint:
                collect(child, next_source_hint)

    for root in roots:
        collect(root)

    updates: List[Dict[str, Any]] = []
    used_cids: Set[str] = set()
    for snapshot in directory_snapshots:
        source_id = str(snapshot.get("id", "") or snapshot.get("old_cid", "") or "").strip()
        source_name = str(snapshot.get("name", "") or "").strip()
        rejected_ids = {
            source_id,
            str(snapshot.get("old_cid", "") or "").strip(),
            str(snapshot.get("old_parent_id", "") or "").strip(),
            str(snapshot.get("new_parent_id", "") or "").strip(),
            *globally_rejected_ids,
        }
        matching = [
            candidate
            for candidate in candidates
            if (
                (source_id and candidate.get("source_id") == source_id)
                or (source_name and candidate.get("name") == source_name)
            )
            and candidate.get("cid") not in rejected_ids
            and candidate.get("cid") not in used_cids
        ]
        if not matching and len(directory_snapshots) == 1:
            matching = [
                candidate
                for candidate in candidates
                if candidate.get("cid") not in rejected_ids and candidate.get("cid") not in used_cids
            ]
        unique_cids = sorted({str(candidate.get("cid", "") or "").strip() for candidate in matching if str(candidate.get("cid", "") or "").strip()})
        if len(unique_cids) != 1:
            continue
        destination_cid = unique_cids[0]
        used_cids.add(destination_cid)
        updates.append(
            {
                "id": source_id,
                "old_path": str(snapshot.get("old_path", "") or ""),
                "new_path": str(snapshot.get("new_path", "") or ""),
                "new_cid": destination_cid,
            }
        )
    return updates


SCRAPER_JOB_LIMIT_DEFAULT = 20
SCRAPER_SCAN_MAX_DIRS = 80
SCRAPER_SCAN_MAX_ENTRIES = 1200
SCRAPER_JOB_ACTIVE_STATUSES = ("pending", "running", "rollback_running")
SCRAPER_GENERIC_CATEGORY_KEYS = {
    "movie",
    "movies",
    "film",
    "films",
    "tv",
    "tvshow",
    "tvshows",
    "series",
    "show",
    "shows",
    "anime",
    "animation",
    "animations",
    "cartoon",
    "cartoons",
    "documentary",
    "documentaries",
    "variety",
    "media",
    "video",
    "videos",
    "resource",
    "resources",
    "download",
    "downloads",
    "sorted",
    "scraped",
    "collection",
    "collections",
    "4k",
    "8k",
    "1080p",
    "2160p",
    "720p",
    "480p",
    "电影",
    "影片",
    "影视",
    "影視",
    "电影小库",
    "电影库",
    "影视库",
    "影視庫",
    "媒体库",
    "媒體庫",
    "剧库",
    "劇庫",
    "资源库",
    "資源庫",
    "动漫库",
    "動漫庫",
    "电影大全",
    "影视大全",
    "影視大全",
    "剧集库",
    "劇集庫",
    "电视剧",
    "剧集",
    "剧",
    "美剧",
    "日剧",
    "韩剧",
    "国剧",
    "港剧",
    "动漫",
    "动画",
    "動畫",
    "番剧",
    "新番",
    "综艺",
    "紀錄片",
    "纪录片",
    "纪录",
    "紀錄",
    "资源",
    "資源",
    "下载",
    "下載",
    "媒体",
    "视频",
    "影片库",
    "片库",
    "已整理",
    "已刮削",
    "已命名",
    "整理",
    "刮削",
    "高清",
    "蓝光",
    "藍光",
}
SCRAPER_TRAILING_RELEASE_TOKENS = {
    "nf",
    "netflix",
    "amzn",
    "amazon",
    "dsnp",
    "disney",
    "hulu",
    "atvp",
    "apple",
    "max",
    "hbo",
    "paramount",
    "peacock",
}




def normalize_scraper_provider(value: Any) -> str:
    name = str(value or "").strip().lower()
    if not name:
        return ""
    p = get_provider_or_none(name)
    if p and p.supports_folder_browse:
        return p.name
    return ""


def get_scraper_provider_label(provider: str) -> str:
    normalized = normalize_scraper_provider(provider)
    p = get_provider_or_none(normalized) if normalized else None
    return str(getattr(p, "label", "") or normalized or provider or "网盘")


def normalize_scraper_job_clear_scope(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in ("failed", "fail", "error"):
        return "failed"
    if normalized in ("rollback", "rolled_back", "rollback_only"):
        return "rollback"
    return "completed"


def _get_provider_cookie(provider: str, cfg: Optional[Dict[str, Any]] = None) -> str:
    active_cfg = cfg or get_config()
    p = get_provider_or_none(normalize_scraper_provider(provider))
    if not p:
        return ""
    return p.get_cookie(active_cfg)


def _build_scraper_operations(provider: str) -> Dict[str, bool]:
    normalized = normalize_scraper_provider(provider)
    p = get_provider_or_none(normalized)
    browse_supported = bool(p and p.supports_folder_browse)
    rename_supported = bool(p and p.supports_rename)
    move_supported = bool(p and p.supports_move)
    copy_supported = bool(p and p.supports_copy)
    delete_supported = bool(p and p.supports_delete)
    scrape_supported = bool(browse_supported and rename_supported and move_supported)
    return {
        "browse": browse_supported,
        "create_folder": browse_supported,
        "rename": rename_supported,
        "copy": copy_supported,
        "move": move_supported,
        "delete": delete_supported,
        "scrape": scrape_supported,
        "rollback": scrape_supported,
    }


def build_scraper_providers_payload(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    active_cfg = cfg or get_config()
    providers = []
    for p in list_enabled_providers(active_cfg):
        if not p.supports_folder_browse:
            continue
        provider = normalize_scraper_provider(p.name)
        if not provider:
            continue
        providers.append(
            {
                "provider": provider,
                "label": p.label,
                "configured": bool(p.is_configured(active_cfg)),
                "operations": _build_scraper_operations(provider),
            }
        )
    return {"ok": True, "providers": providers}


def _require_scraper_operation(provider: str, operation: str, label: str = "") -> None:
    normalized = normalize_scraper_provider(provider)
    operations = _build_scraper_operations(normalized)
    if not operations.get(operation):
        provider_label = get_scraper_provider_label(normalized)
        operation_label = label or operation
        raise RuntimeError(f"{provider_label} 暂不支持刮削{operation_label}")


def _require_provider_cookie(provider: str) -> str:
    normalized = normalize_scraper_provider(provider)
    if not normalized:
        raise RuntimeError("网盘类型无效")
    cookie = _get_provider_cookie(normalized)
    if not cookie:
        raise RuntimeError(f"请先配置 {get_scraper_provider_label(normalized)} 认证信息")
    return cookie


def _list_provider_entries_payload(
    provider: str,
    cookie: str,
    cid: str = "0",
    *,
    folders_only: bool = False,
) -> Dict[str, Any]:
    target_id = str(cid or "0").strip() or "0"
    p = get_provider_or_none(provider)
    if not p:
        raise RuntimeError("网盘类型无效")
    return p.list_entries_payload(cookie, target_id, folders_only=folders_only)


def _create_provider_folder(provider: str, cookie: str, cid: str, name: str) -> Dict[str, Any]:
    p = get_provider_or_none(provider)
    if not p:
        raise RuntimeError("网盘类型无效")
    return p.create_folder(cookie, cid, name)


def _rename_provider_entry(provider: str, cookie: str, entry_id: str, new_name: str, parent_id: str = "") -> Dict[str, Any]:
    _require_scraper_operation(provider, "rename", "重命名")
    p = get_provider_or_none(provider)
    return p.rename_entry(cookie, entry_id, new_name, parent_id)


def _move_provider_entries(provider: str, cookie: str, entry_ids: List[str], target_id: str, source_id: str = "") -> Dict[str, Any]:
    _require_scraper_operation(provider, "move", "移动")
    p = get_provider_or_none(provider)
    return p.move_entries(cookie, entry_ids, target_id, source_id)


def _copy_provider_entries(provider: str, cookie: str, entry_ids: List[str], target_id: str, source_id: str = "") -> Dict[str, Any]:
    _require_scraper_operation(provider, "copy", "复制")
    p = get_provider_or_none(provider)
    return p.copy_entries(cookie, entry_ids, target_id, source_id)


def _delete_provider_entries(provider: str, cookie: str, entry_ids: List[str], parent_id: str = "") -> Dict[str, Any]:
    _require_scraper_operation(provider, "delete", "删除")
    p = get_provider_or_none(provider)
    return p.delete_entries(cookie, entry_ids, parent_id)


def _invalidate_provider_parent(provider: str, parent_id: str = "") -> None:
    if provider == "115":
        invalidate_115_entries_cache(parent_id)


def _compact_scraper_entry(entry: Dict[str, Any], parent_id: str = "", parent_path: str = "") -> Dict[str, Any]:
    item = entry if isinstance(entry, dict) else {}
    is_dir = bool(item.get("is_dir"))
    entry_id = str(item.get("id", "") or "").strip()
    name = str(item.get("name", "") or "").strip()
    if not entry_id or not name:
        return {}
    effective_parent = str(item.get("parent_id", "") or parent_id or "0").strip() or "0"
    effective_parent_path = normalize_relative_path(str(item.get("parent_path", "") or parent_path or "").strip())
    path = normalize_relative_path(str(item.get("path", "") or "").strip()) or normalize_relative_path(join_relative_path(effective_parent_path, name))
    payload: Dict[str, Any] = {
        "id": entry_id,
        "name": name,
        "is_dir": is_dir,
        "size": parse_int(item.get("size") or 0),
        "parent_id": effective_parent,
        "parent_path": effective_parent_path,
        "path": path,
        "modified_at": str(item.get("modified_at", "") or "").strip(),
    }
    if is_dir:
        payload["cid"] = str(item.get("cid", "") or entry_id).strip() or entry_id
    else:
        payload["fid"] = str(item.get("fid", "") or entry_id).strip() or entry_id
    return payload


def _scraper_entry_path(entry: Dict[str, Any]) -> str:
    item = entry if isinstance(entry, dict) else {}
    path = normalize_relative_path(str(item.get("path", "") or "").strip())
    if path:
        return path
    parent_path = normalize_relative_path(str(item.get("parent_path", "") or "").strip())
    name = str(item.get("name", "") or "").strip()
    return normalize_relative_path(join_relative_path(parent_path, name))


def _scraper_path_depth(path: str) -> int:
    normalized = normalize_relative_path(str(path or "").strip())
    return len([part for part in normalized.split("/") if part])


def _is_scraper_path_descendant(path: str, ancestor_path: str) -> bool:
    normalized_path = normalize_relative_path(str(path or "").strip())
    normalized_ancestor = normalize_relative_path(str(ancestor_path or "").strip())
    if not normalized_path or not normalized_ancestor:
        return False
    return normalized_path == normalized_ancestor or normalized_path.startswith(f"{normalized_ancestor}/")


def _normalize_scraper_selected_entries(selected: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for raw in selected or []:
        item = raw if isinstance(raw, dict) else {}
        entry = _compact_scraper_entry(
            item,
            str(item.get("parent_id", "") or "0"),
            normalize_relative_path(str(item.get("parent_path", "") or "")),
        )
        if not entry:
            continue
        entry["path"] = _scraper_entry_path(entry)
        candidates.append(entry)

    if not candidates:
        return []

    candidates.sort(
        key=lambda item: (
            _scraper_path_depth(str(item.get("path", "") or "")),
            0 if item.get("is_dir") else 1,
            str(item.get("path", "") or "").lower(),
            str(item.get("id", "") or ""),
        )
    )
    normalized: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()
    seen_paths: Set[str] = set()
    for entry in candidates:
        entry_id = str(entry.get("id", "") or "").strip()
        entry_path = _scraper_entry_path(entry)
        if not entry_id or not entry_path:
            continue
        if entry_id in seen_ids or entry_path in seen_paths:
            continue
        if any(existing.get("is_dir") and _is_scraper_path_descendant(entry_path, str(existing.get("path", "") or "")) for existing in normalized):
            continue
        normalized.append(entry)
        seen_ids.add(entry_id)
        seen_paths.add(entry_path)
    return normalized


def list_scraper_entries(provider: str, cid: str = "0", force_refresh: bool = False, search: str = "") -> Dict[str, Any]:
    normalized = normalize_scraper_provider(provider)
    cookie = _require_provider_cookie(normalized)
    target_id = str(cid or "0").strip() or "0"
    if force_refresh:
        _invalidate_provider_parent(normalized, target_id)
    payload = _list_provider_entries_payload(normalized, cookie, target_id, folders_only=False)
    entries = [
        compact
        for compact in (_compact_scraper_entry(item, target_id) for item in (payload.get("entries", []) if isinstance(payload, dict) else []))
        if compact
    ]
    keyword = str(search or "").strip().lower()
    if keyword:
        entries = [item for item in entries if keyword in str(item.get("name", "")).lower()]
    summary = payload.get("summary", {}) if isinstance(payload, dict) and isinstance(payload.get("summary"), dict) else {}
    return {
        "ok": True,
        "provider": normalized,
        "cid": target_id,
        "entries": entries,
        "summary": {
            "folder_count": max(0, parse_int(summary.get("folder_count", 0), 0)),
            "file_count": max(0, parse_int(summary.get("file_count", 0), 0)),
        },
    }


def create_scraper_folder(
    provider: str,
    cid: str,
    name: str,
    parent_path: Optional[str] = None,
    request_id: str = "",
) -> Dict[str, Any]:
    normalized = normalize_scraper_provider(provider)
    cookie = _require_provider_cookie(normalized)
    parent_id = str(cid or "0").strip() or "0"
    folder_name = str(name or "").strip()
    normalized_parent_path = normalize_relative_path(str(parent_path or "").strip())
    prepared = _prepare_scraper_monitor_sync(
        normalized,
        "create",
        [
            {
                "id": "",
                "name": folder_name,
                "path": join_relative_path(normalized_parent_path, folder_name),
                "new_path": join_relative_path(normalized_parent_path, folder_name),
                "new_parent_id": parent_id,
                "is_dir": True,
            }
        ]
        if normalized == "115" and parent_path is not None
        else [],
        source_action="scraper:folder:create",
        dedupe_key=_direct_monitor_change_key("folder-create", request_id),
    )
    try:
        folder = _create_provider_folder(normalized, cookie, parent_id, folder_name)
    except Exception as exc:
        _finish_scraper_monitor_sync(prepared, succeeded=False, error=str(exc))
        raise
    _invalidate_provider_parent(normalized, parent_id)
    if normalized == "115" and isinstance(folder, dict):
        folder_id = str(
            folder.get("id", "")
            or folder.get("cid", "")
            or folder.get("folder_id", "")
            or ""
        ).strip()
        if folder_id and folder_id != parent_id:
            _update_scraper_monitor_sync(
                prepared,
                [
                    {
                        "new_path": join_relative_path(normalized_parent_path, folder_name),
                        "new_parent_id": parent_id,
                        "new_cid": folder_id,
                    }
                ],
            )
    monitor_sync = _finish_scraper_monitor_sync(prepared, succeeded=True)
    return {"ok": True, "provider": normalized, "cid": parent_id, "folder": folder, "monitor_sync": monitor_sync}


def rename_scraper_entry(
    provider: str,
    entry_id: str,
    parent_id: str,
    name: str,
    entry: Optional[Dict[str, Any]] = None,
    request_id: str = "",
) -> Dict[str, Any]:
    normalized = normalize_scraper_provider(provider)
    cookie = _require_provider_cookie(normalized)
    matched_entries = _select_requested_monitor_snapshots(
        [entry] if isinstance(entry, dict) else [],
        [entry_id],
    )
    source_entry = matched_entries[0] if matched_entries else {}
    old_path = normalize_relative_path(str(source_entry.get("path", "") or ""))
    new_path = normalize_relative_path(join_relative_path(os.path.dirname(old_path), str(name or "").strip())) if old_path else ""
    prepared = _prepare_scraper_monitor_sync(
        normalized,
        "rename",
        [
            {
                **source_entry,
                "id": str(source_entry.get("id", "") or entry_id),
                "path": old_path,
                "old_path": old_path,
                "new_path": new_path,
                "old_parent_id": str(source_entry.get("parent_id", "") or parent_id).strip(),
                "new_parent_id": str(source_entry.get("parent_id", "") or parent_id).strip(),
                "old_cid": str(source_entry.get("cid", "") or (entry_id if bool(source_entry.get("is_dir")) else "")).strip(),
                "new_cid": str(source_entry.get("cid", "") or (entry_id if bool(source_entry.get("is_dir")) else "")).strip(),
                "name": str(source_entry.get("name", "") or ""),
            }
        ]
        if normalized == "115" and old_path and new_path
        else [],
        source_action="scraper:entry:rename",
        dedupe_key=_direct_monitor_change_key("rename", request_id),
    )
    try:
        result = _rename_provider_entry(normalized, cookie, entry_id, name, parent_id)
    except Exception as exc:
        _finish_scraper_monitor_sync(prepared, succeeded=False, error=str(exc))
        raise
    _invalidate_provider_parent(normalized, parent_id)
    monitor_sync = _finish_scraper_monitor_sync(prepared, succeeded=True)
    return {"ok": True, "provider": normalized, "entry": result, "monitor_sync": monitor_sync}


def check_scraper_folder_rename_warning(provider: str, old_path: str, new_path: str) -> Dict[str, Any]:
    normalized = normalize_scraper_provider(provider) or "115"
    normalized_old_path = normalize_relative_path(str(old_path or "").strip())
    normalized_new_path = normalize_relative_path(str(new_path or "").strip())
    if not normalized_old_path or not normalized_new_path:
        raise RuntimeError("文件夹路径无效")
    warning = _collect_scraper_subscription_rename_warning(normalized, normalized_old_path, normalized_new_path)
    return {
        "ok": True,
        "provider": normalized,
        "old_path": normalized_old_path,
        "new_path": normalized_new_path,
        "warning": warning,
    }


def move_scraper_entries(
    provider: str,
    entry_ids: List[str],
    target_cid: str,
    source_cid: str = "",
    entries: Optional[List[Dict[str, Any]]] = None,
    target_parent_path: Optional[str] = None,
    request_id: str = "",
) -> Dict[str, Any]:
    normalized = normalize_scraper_provider(provider)
    cookie = _require_provider_cookie(normalized)
    snapshots = _build_transfer_monitor_snapshots(
        normalized,
        entries,
        target_parent_path,
        target_parent_id=target_cid,
        operation="move",
        entry_ids=entry_ids,
    )
    prepared = _prepare_scraper_monitor_sync(
        normalized,
        "move",
        snapshots,
        source_action="scraper:entry:move",
        dedupe_key=_direct_monitor_change_key("move", request_id),
    )
    try:
        result = _move_provider_entries(normalized, cookie, entry_ids, target_cid, source_cid)
    except Exception as exc:
        _finish_scraper_monitor_sync(prepared, succeeded=False, error=str(exc))
        raise
    _invalidate_provider_parent(normalized, source_cid)
    _invalidate_provider_parent(normalized, target_cid)
    monitor_sync = _finish_scraper_monitor_sync(prepared, succeeded=True)
    return {"ok": True, "provider": normalized, "result": result, "monitor_sync": monitor_sync}


def copy_scraper_entries(
    provider: str,
    entry_ids: List[str],
    target_cid: str,
    source_cid: str = "",
    entries: Optional[List[Dict[str, Any]]] = None,
    target_parent_path: Optional[str] = None,
    request_id: str = "",
) -> Dict[str, Any]:
    normalized = normalize_scraper_provider(provider)
    cookie = _require_provider_cookie(normalized)
    snapshots = _build_transfer_monitor_snapshots(
        normalized,
        entries,
        target_parent_path,
        target_parent_id=target_cid,
        operation="copy",
        entry_ids=entry_ids,
    )
    prepared = _prepare_scraper_monitor_sync(
        normalized,
        "copy",
        snapshots,
        source_action="scraper:entry:copy",
        dedupe_key=_direct_monitor_change_key("copy", request_id),
    )
    try:
        result = _copy_provider_entries(normalized, cookie, entry_ids, target_cid, source_cid)
    except Exception as exc:
        _finish_scraper_monitor_sync(prepared, succeeded=False, error=str(exc))
        raise
    _invalidate_provider_parent(normalized, target_cid)
    if normalized == "115":
        copy_updates = _extract_copy_destination_cids(
            result,
            snapshots,
            target_parent_id=target_cid,
            request_id=request_id,
        )
        if copy_updates:
            _update_scraper_monitor_sync(prepared, copy_updates)
    monitor_sync = _finish_scraper_monitor_sync(prepared, succeeded=True)
    return {"ok": True, "provider": normalized, "result": result, "monitor_sync": monitor_sync}


def delete_scraper_entries(
    provider: str,
    entry_ids: List[str],
    parent_id: str = "",
    entries: Optional[List[Dict[str, Any]]] = None,
    request_id: str = "",
) -> Dict[str, Any]:
    normalized = normalize_scraper_provider(provider)
    cookie = _require_provider_cookie(normalized)
    selected_entries = _select_requested_monitor_snapshots(entries, entry_ids)
    snapshots = (
        [
            {
                **item,
                "old_parent_id": str(item.get("parent_id", "") or parent_id).strip(),
            }
            for item in selected_entries
            if isinstance(item, dict) and str(item.get("path", "") or "").strip()
        ]
        if normalized == "115"
        else []
    )
    prepared = _prepare_scraper_monitor_sync(
        normalized,
        "delete",
        snapshots,
        source_action="scraper:entry:delete",
        dedupe_key=_direct_monitor_change_key("delete", request_id),
    )
    try:
        result = _delete_provider_entries(normalized, cookie, entry_ids, parent_id)
    except Exception as exc:
        _finish_scraper_monitor_sync(prepared, succeeded=False, error=str(exc))
        raise
    _invalidate_provider_parent(normalized, parent_id)
    monitor_sync = _finish_scraper_monitor_sync(prepared, succeeded=True)
    return {"ok": True, "provider": normalized, "result": result, "monitor_sync": monitor_sync}


def _strip_extension(name: str) -> str:
    text = str(name or "").strip()
    stem, ext = os.path.splitext(text)
    suffix = str(ext or "").lstrip(".")
    # 只有像真实扩展名的后缀（纯字母数字、长度 1-5）才裁剪；
    # 文件夹名/发布组括号里的 ".BZ]"、".GG" 等不能被误判为扩展名。
    if suffix and suffix.isalnum() and 1 <= len(suffix) <= 5 and stem:
        return stem
    return text


def _is_scraper_excluded_archive(name: str) -> bool:
    return os.path.splitext(str(name or "").strip())[1].lower() in {".zip", ".rar"}


def _normalize_scraper_keyword_compact(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "").strip()).lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


def _trim_scraper_trailing_noise_tokens(value: str) -> str:
    tokens = str(value or "").strip().split()
    while len(tokens) >= 3 and tokens[-1].lower() in (
        SCRAPER_TRAILING_RELEASE_TOKENS | {"h", "x", "片源", "原盘", "全集", "完结", "连载"}
    ):
        tokens.pop()
    while tokens and any(fragment == tokens[-1] for fragment in _scraper_cn_ad_site_matches(tokens[-1])):
        tokens.pop()
    return " ".join(tokens)


def _is_scraper_release_group_token(value: str) -> bool:
    """判断 token 是否像发布组名：全大写可含数字（ADDICTION/YTS.MX/D-Z0N3），
    或小写后跟大写（NORDiC/ADDiCTiON/XviD）。"""
    token = str(value or "").strip()
    if not token or len(token) > 24:
        return False
    compact = re.sub(r"[._\s-]+", "", token)
    if len(compact) < 2 or len(compact) > 24 or not re.search(r"[A-Za-z]", compact):
        return False
    if re.fullmatch(r"[A-Z0-9]+", compact):
        return True
    return bool(re.search(r"[a-z][A-Z]", token))


def _trim_scraper_trailing_release_group(value: str) -> str:
    tokens = str(value or "").strip().split()
    while len(tokens) >= 2 and _is_scraper_release_group_token(tokens[-1]):
        tokens.pop()
    return " ".join(tokens).strip(" -_.")


SCRAPER_SITE_TLD_PATTERN = r"(?:com|org|net|tv|me|cc|xyz|site|top|club|io|co|info|biz)"

# 常见中文发布站点词条（不依赖具体网址）：网址不同也能命中。
SCRAPER_CN_AD_SITE_PHRASES = (
    "高清剧集网", "高清电影网", "高清影视网", "免费影视网", "免费电影网",
    "免费高清网", "电影天堂", "影视天堂", "剧集天堂", "电视剧天堂",
    "影视资源网", "资源分享网", "电影首发站", "首发电影网", "最新影视",
    "天天影视", "极速影视", "飞速影视", "星辰影视", "樱花影视", "在线影视",
)

_SCRAPER_CN_AD_PHRASE_ALT = "|".join(re.escape(phrase) for phrase in SCRAPER_CN_AD_SITE_PHRASES)

_SCRAPER_CN_AD_PHRASE_RE = re.compile(
    rf"(?i)(?:{_SCRAPER_CN_AD_PHRASE_ALT})"
    rf"\s*(?:www[\s.]*[a-z0-9.-]+)?"
    rf"\s*(?:发布|首发|分享|出品|压制|制作|整理|更新)?"
)

_SCRAPER_CN_AD_SITE_ACTION_RE = re.compile(
    rf"(?i)[一-龥A-Za-z0-9]{{2,12}}?(?:网|站|论坛|社区|吧|组)"
    rf"\s*(?:www[\s.]*[a-z0-9.-]+)?"
    rf"\s*(?:发布|首发|分享|出品|压制|制作|整理|更新)"
)

# 常见附属信息短语（不是片名的一部分）：字幕/水印/版本/音轨/资源渠道等。
SCRAPER_COMMON_NOISE_PHRASES = (
    "无字片源", "无字幕版", "无字幕", "无水印", "无广告", "无删减", "未删减", "未删节",
    "完整版", "加长版", "剧场版", "导演剪辑版", "重制版", "修复版", "高清修复版", "4k修复版",
    "国配版", "国语版", "国语配音", "粤语版", "双音轨", "多音轨", "中英双语", "国粤双语",
    "特效中字", "内嵌中字", "外挂字幕", "简体中字", "繁体中字",
    "中文字幕", "中文配音", "中文音轨", "中文版",
    "提取码", "磁力链接", "种子下载", "网盘下载", "百度网盘", "夸克网盘", "阿里云盘", "天翼云盘", "城通网盘",
    "全网首发", "独家首发", "地址发布页", "发布地址", "永久地址", "备用地址",
    "最新地址", "官网地址", "防走丢", "收藏本站", "最新网址", "发布页",
)

_SCRAPER_COMMON_NOISE_RE = re.compile(
    "|".join(re.escape(phrase) for phrase in SCRAPER_COMMON_NOISE_PHRASES),
    re.IGNORECASE,
)

# 只在词边界出现的独立噪声词：不能按子串全局替换（会误伤“我的中文老师”这类真实片名），
# 只清理作为独立 token 出现的“中文/国语”（如 片名.中文.1080p、片名[国语]）。
SCRAPER_STANDALONE_NOISE_WORDS = ("中文", "国语")
_SCRAPER_STANDALONE_NOISE_KEYS = frozenset(
    _normalize_scraper_keyword_compact(word) for word in SCRAPER_STANDALONE_NOISE_WORDS
)
_SCRAPER_STANDALONE_NOISE_RE = re.compile(
    "(?<![\u4e00-\u9fff])(?:"
    + "|".join(re.escape(word) for word in SCRAPER_STANDALONE_NOISE_WORDS)
    + ")(?![\u4e00-\u9fff])"
)


def _scraper_cn_ad_site_matches(value: str) -> List[str]:
    text = str(value or "")
    if not text:
        return []
    matches: List[str] = []
    seen: Set[str] = set()
    for pattern in (_SCRAPER_CN_AD_PHRASE_RE, _SCRAPER_CN_AD_SITE_ACTION_RE):
        for matched in pattern.finditer(text):
            fragment = str(matched.group(0) or "").strip()
            if fragment and fragment not in seen:
                seen.add(fragment)
                matches.append(fragment)
    return matches


def _strip_scraper_cn_ad_phrases(value: str, *, leading_only: bool = False) -> str:
    text = str(value or "")
    matches = _scraper_cn_ad_site_matches(text)
    if leading_only:
        stripped = text.lstrip()
        for fragment in matches:
            if stripped.startswith(fragment):
                return stripped[len(fragment):].lstrip()
        return text
    for fragment in matches:
        text = text.replace(fragment, " ")
    return re.sub(r"\s+", " ", text).strip(" -_.")


def _strip_scraper_site_prefix(text: str) -> str:
    """去除开头的发布站点前缀：高清剧集网发布 / www.UIndex.org - / www UIndex org - / UIndex.org -"""
    text = _strip_scraper_cn_ad_phrases(text, leading_only=True)
    text = re.sub(r"(?i)^\s*www[\s.]*[a-z0-9][a-z0-9.-]*[\s.]+[a-z0-9][a-z0-9.-]*\s*[-–—]?\s*", " ", text)
    text = re.sub(
        r"(?i)^\s*(?:[a-z0-9][a-z0-9.-]*\.)+" + SCRAPER_SITE_TLD_PATTERN + r"\b\s*[-–—]?\s*",
        " ",
        text,
    )
    return text


_SCRAPER_ANCHOR_YEAR_RE = re.compile(r"(?<![0-9])(?:19|20)\d{2}(?![0-9])")
_SCRAPER_ANCHOR_EPISODE_RE = re.compile(
    r"(?i)(?:\bs\d{1,2}\s*e\d{1,4}\b|\bep?\s*\d{1,4}\b|\be\d{1,4}\b|\bseason\s*\d{1,2}\b|"
    r"第\s*[0-9零〇一二三四五六七八九十两兩]{1,4}\s*(?:季|集|话|話))"
)


def _scraper_anchor_positions(raw_text: str) -> List[int]:
    """技术标记位置：媒体标签、年份、季集标记。标题在这些标记之前（或首个标记之后）。"""
    positions: List[int] = []
    spans = parse_media_tags(raw_text).get("spans", []) if isinstance(raw_text, str) else []
    for start, _end in spans if isinstance(spans, list) else []:
        positions.append(max(0, int(start)))
    for match in _SCRAPER_ANCHOR_YEAR_RE.finditer(raw_text):
        positions.append(match.start())
    for match in _SCRAPER_ANCHOR_EPISODE_RE.finditer(raw_text):
        positions.append(match.start())
    return sorted(set(positions))


def _load_guessit():
    """延迟加载 guessit 解析器；未安装时返回 None，由手写解析兜底。"""
    if getattr(_load_guessit, "_cached", None) is None:
        try:
            from guessit import guessit as _guessit_parse
        except Exception:  # pragma: no cover - 依赖可选
            _guessit_parse = None
        _load_guessit._cached = _guessit_parse
    return _load_guessit._cached


_GUESSIT_RELEASE_FIELDS = (
    "title",
    "alternative_title",
    "year",
    "season",
    "episode",
    "part",
    "type",
    "release_group",
    "screen_size",
    "source",
    "video_codec",
    "audio_codec",
    "language",
)


def _guessit_scraper_release(raw: str) -> Dict[str, Any]:
    """用 guessit 把发布名解析为结构化字段；解析失败或未安装时返回空字典。"""
    parser = _load_guessit()
    text = unicodedata.normalize("NFKC", str(raw or "")).strip()
    if parser is None or not text:
        return {}
    try:
        parsed = parser(text)
    except Exception:
        return {}
    if not isinstance(parsed, dict):
        return {}
    result: Dict[str, Any] = {}
    for field in _GUESSIT_RELEASE_FIELDS:
        value = parsed.get(field)
        if value is not None:
            result[field] = value
    return result


_SCRAPER_PART_WORDS = {
    1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six",
    7: "Seven", 8: "Eight", 9: "Nine", 10: "Ten", 11: "Eleven", 12: "Twelve",
    13: "Thirteen", 14: "Fourteen", 15: "Fifteen", 16: "Sixteen", 17: "Seventeen",
    18: "Eighteen", 19: "Nineteen", 20: "Twenty",
}


def _split_scraper_mixed_language_title(title: str) -> List[str]:
    """把中英混排标题拆成独立候选：中文部分优先，再英文部分。"""
    text = str(title or "").strip()
    if not text:
        return []
    latin = re.sub(r"[\u4e00-\u9fff]+", " ", text)
    latin = re.sub(r"^[\d\s._-]+", "", latin)
    latin = re.sub(r"^[\s:：,，;；|/\\·•]+|[\s:：,，;；|/\\·•]+$", "", latin)
    latin = re.sub(r"\s+", " ", latin).strip(" -_.")
    cjk = re.sub(r"[^\u4e00-\u9fff]+", " ", text)
    cjk = re.sub(r"\s+", " ", cjk).strip(" -_.")
    parts: List[str] = []
    for part in (cjk, latin):
        key_len = len(_scraper_keyword_key(part))
        if (
            part
            and part != text
            and key_len >= 2
            and ((not _contains_cjk(part) and key_len >= 3) or _contains_cjk(part))
        ):
            parts.append(part)
    return parts


def _scraper_guessit_candidates(raw: str) -> List[str]:
    """基于 guessit 结构化字段构造查询候选：多部曲拼回、中英混排拆分。"""
    text = re.sub(r"^\s*(?:[\[\(（【][^\]\)）】]{1,80}[\]\)）】]\s*)+", " ", str(raw or ""))
    parsed = _guessit_scraper_release(text)
    title = str(parsed.get("title") or "").strip()
    if not title:
        return []
    candidates: List[str] = []
    part = parsed.get("part")
    try:
        part_number = int(part or 0)
    except (TypeError, ValueError):
        part_number = 0
    if part_number > 0:
        candidates.append(f"{title} Part {part_number}")
        word = _SCRAPER_PART_WORDS.get(part_number)
        if word:
            candidates.append(f"{title} Part {word}")
    candidates.append(title)
    candidates.extend(_split_scraper_mixed_language_title(title))
    return _merge_scraper_title_candidates(candidates)


def _merge_scraper_title_candidates(candidates: List[str]) -> List[str]:
    """过滤通用噪声、按关键字去重、截断，保持候选顺序稳定。"""
    merged: List[str] = []
    seen: Set[str] = set()
    for candidate in candidates:
        cleaned = _clean_search_title(candidate)
        if not cleaned or _is_scraper_noise_keyword(cleaned) or len(_scraper_keyword_key(cleaned)) < 2:
            continue
        if len(cleaned) > 80:
            cleaned = cleaned[:80].strip(" -_.")
        key = _scraper_keyword_key(cleaned)
        if key in seen:
            continue
        seen.add(key)
        merged.append(cleaned)
        if len(merged) >= 8:
            break
    return merged


def _legacy_candidates_from_text(raw: str) -> List[str]:
    text = unicodedata.normalize("NFKC", str(raw or "")).strip()
    if not text:
        return []
    text = _strip_extension(text)
    text = re.sub(r"^\s*(?:[\[\(（【][^\]\)）】]{1,80}[\]\)）】]\s*)+", " ", text)
    text = _strip_scraper_site_prefix(text)
    text = re.sub(r"\s+", " ", text).strip(" -_.")
    anchors = _scraper_anchor_positions(text)
    raw_segments: List[str] = []
    if anchors:
        before = text[: anchors[0]]
        if before.strip():
            raw_segments.append(before)
        if anchors[0] == 0:
            # 首个技术标记位于开头（如 S01E01 开头）：取标记之后的标题段。
            for index, anchor in enumerate(anchors):
                segment = text[anchor : (anchors[index + 1] if index + 1 < len(anchors) else len(text))]
                if segment.strip():
                    raw_segments.append(segment)
    else:
        raw_segments.append(text)

    candidates: List[str] = []
    seen: Set[str] = set()
    for segment in raw_segments:
        cleaned = _clean_search_title(segment)
        if not cleaned or _is_scraper_noise_keyword(cleaned) or len(_scraper_keyword_key(cleaned)) < 2:
            continue
        key = _scraper_keyword_key(cleaned)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(cleaned)
    return candidates


def _legacy_extract_scraper_title_candidates(raw: str) -> List[str]:
    """手写结构解析兜底：路径优先取最后一段，最后一段为通用噪声时再往前取。"""
    text = unicodedata.normalize("NFKC", str(raw or "")).strip()
    if not text:
        return []
    sources = [part for part in re.split(r"[\\/]+", text) if part.strip()]
    if len(sources) <= 1:
        return _legacy_candidates_from_text(text)
    candidates: List[str] = []
    for source in reversed(sources):
        for candidate in _legacy_candidates_from_text(source):
            if not _is_scraper_noise_keyword(candidate):
                candidates.append(candidate)
        if candidates:
            break
    if not candidates:
        candidates = _legacy_candidates_from_text(text)
    return candidates


def _extract_scraper_title_candidates(raw: str) -> List[str]:
    """按发布名结构提取候选标题（guessit 主解析 + 手写解析兜底合并）。

    guessit 擅长处理站点前缀、父目录路径、季集结构与发布组；手写解析补充多部曲
    与中英混排等场景。两者按关键字去重合并，保证查询顺序稳定；
    中英混排候选拆成独立关键词，避免把两个名称合并成一条搜不出结果。
    """
    text = unicodedata.normalize("NFKC", str(raw or "")).strip()
    if not text:
        return []
    candidates = _scraper_guessit_candidates(text)
    candidates = _merge_scraper_title_candidates(candidates + _legacy_extract_scraper_title_candidates(text))
    split_candidates: List[str] = []
    for candidate in candidates:
        split_candidates.extend(_split_scraper_mixed_language_title(candidate))
    candidates = _merge_scraper_title_candidates(split_candidates + candidates)
    return candidates


def _scraper_query_degradations(query: str) -> List[str]:
    """主查询无结果时的降级查询：只去掉尾部仍残留的发布组 token，避免生成无意义查询。"""
    tokens = str(query or "").strip().split()
    variants: List[str] = []
    while len(tokens) >= 2 and _is_scraper_release_group_token(tokens[-1]):
        tokens.pop()
        joined = " ".join(tokens).strip(" -_.")
        if joined and len(_scraper_keyword_key(joined)) >= 2:
            variants.append(joined)
    return variants


def _is_scraper_generic_keyword(value: str) -> bool:
    key = _normalize_scraper_keyword_compact(value)
    if not key:
        return True
    if key in SCRAPER_GENERIC_CATEGORY_KEYS:
        return True
    if not _normalize_scraper_keyword_compact(_SCRAPER_COMMON_NOISE_RE.sub(" ", str(value or ""))):
        return True
    if key in _SCRAPER_STANDALONE_NOISE_KEYS:
        return True
    for fragment in _scraper_cn_ad_site_matches(value):
        if _normalize_scraper_keyword_compact(fragment) == key:
            return True
    return bool(
        re.fullmatch(
            r"(?:电影|影片|影视|影視|电视剧|剧集|动漫|动画|動畫|番剧|新番|综艺|纪录片|紀錄片|纪录|紀錄|资源|資源|下载|下載|媒体|视频|高清|蓝光|藍光)"
            r"(?:资源|資源|下载|下載|合集|合輯|整理|已整理|已刮削|已命名|小库|大全|库|庫)?",
            key,
        )
    )


def _is_scraper_noise_keyword(value: str) -> bool:
    cleaned = str(value or "").strip()
    key = _scraper_keyword_key(cleaned)
    if not key:
        return True
    if _is_scraper_generic_keyword(cleaned):
        return True
    if re.fullmatch(r"(?:s\d{1,2}|season\d{1,2}|e\d{1,4}|ep\d{1,4}|\d{1,4})", key, re.I):
        return True
    if re.fullmatch(r"第[零〇一二三四五六七八九十两兩0-9]{1,4}(?:季|集|话|話)", cleaned):
        return True
    return False


def _clean_search_title(value: str) -> str:
    text = unicodedata.normalize("NFKC", _strip_extension(value))
    text = remove_media_tags(text)
    text = _strip_scraper_site_prefix(text)
    text = _strip_scraper_cn_ad_phrases(text)
    text = re.sub(
        r"(?i)\b(?:www[\s.]*)?(?:[a-z0-9][a-z0-9.-]*[\s.]+)+(?:com|org|net|tv|me|cc|xyz|site|top|club|io|co|info|biz)\b",
        " ",
        text,
    )
    text = re.sub(r"(?:简繁英|简中|繁中|中英|国英|国粤|中法|双语|内嵌|外挂|特效|简繁|繁简)?(?:字幕|双字)(?!组|站|网)", " ", text)
    text = _SCRAPER_COMMON_NOISE_RE.sub(" ", text)
    text = _SCRAPER_STANDALONE_NOISE_RE.sub(" ", text)
    text = re.sub(r"[\[\(（【][^\]\)）】]{0,90}?(?:第.+?季|s\d{1,2}e\d{1,4})[^\]\)）】]{0,90}?[\]\)）】]", " ", text, flags=re.I)
    text = re.sub(r"^[\[\(（【][A-Za-z0-9][A-Za-z0-9._ +&-]{0,40}[\]\)）】]\s*", " ", text)
    text = re.sub(r"[\[\(（【][A-Za-z0-9][A-Za-z0-9._ +&-]{0,60}[\]\)）】]", " ", text)
    text = re.sub(r"\b(19|20)\d{2}\b", " ", text)
    text = re.sub(r"\bS\d{1,2}\s*E\d{1,4}\b|\bEP?\s*\d{1,4}\b|\bE\d{1,4}\b", " ", text, flags=re.I)
    text = re.sub(r"\bS\d{1,2}\b|\bSeason\s*\d{1,2}\b", " ", text, flags=re.I)
    text = re.sub(r"第\s*[零〇一二三四五六七八九十两兩0-9]{1,4}\s*(?:季|集|话|話)", " ", text)
    text = re.sub(r"(?:全|共)\s*\d{1,4}\s*(?:集|话|話)", " ", text)
    text = re.sub(
        r"\b(?:complete|proper|repack|extended|uncut|internal|multi|chs|cht|gb|big5|"
        r"简繁英|简中|繁中|中英|国英|国粤|双语|内嵌|外挂|特效|简繁|中字|字幕|电影)\b",
        " ",
        text,
        flags=re.I,
    )
    if _contains_cjk(text):
        text = re.sub(r"(?:^|[\s._-]+)\d{1,4}(?=\s*$)", " ", text)
    text = re.sub(r"[\[\]{}()<>【】（）「」『』]+", " ", text)
    text = re.sub(r"[\._\-]+", " ", text)
    text = re.sub(r"\s*(?:\||/|／|·|•)\s*", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -_.")
    text = _trim_scraper_trailing_noise_tokens(text)
    text = _trim_scraper_trailing_release_group(text)
    return text or _strip_extension(value)


def _scraper_keyword_key(value: str) -> str:
    return re.sub(r"[\W_]+", "", str(value or "").lower())


def _split_scraper_title_parts(value: str) -> List[str]:
    text = _strip_extension(value)
    text = re.sub(r"^[\[\(（【][^\]\)）】]{1,40}[\]\)）】]\s*", " ", text)
    text = re.sub(r"[\[\(（【][0-9a-f]{8}[\]\)）】]", " ", text, flags=re.I)
    parts = []
    for segment in re.split(r"[\\/]+", text):
        segment = segment.strip()
        if not segment:
            continue
        parts.append(segment)
        for part in re.split(r"\s+(?:-|–|—|\||/|／|·|•)\s+", segment):
            part = part.strip()
            if part and part != segment:
                parts.append(part)
    return parts


def _common_scraper_prefix(names: List[str]) -> str:
    cleaned = [_clean_search_title(name) for name in names if str(name or "").strip()]
    cleaned = [item for item in cleaned if len(_scraper_keyword_key(item)) >= 2 and not _is_scraper_noise_keyword(item)]
    if len(cleaned) < 2:
        return ""
    prefix = os.path.commonprefix(cleaned).strip(" -_.")
    candidate = _clean_search_title(prefix)
    return candidate if len(_scraper_keyword_key(candidate)) >= 2 and not _is_scraper_noise_keyword(candidate) else ""


def build_scraper_keyword_suggestions(selected: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    weighted: Dict[str, Dict[str, Any]] = {}

    def add_candidate(raw: str, score: int, source: str = "") -> None:
        cleaned = _clean_search_title(raw)
        key = _scraper_keyword_key(cleaned)
        if len(key) < 2 or _is_scraper_noise_keyword(cleaned):
            return
        if len(cleaned) > 80:
            cleaned = cleaned[:80].strip()
        item = weighted.get(key)
        if not item:
            weighted[key] = {"keyword": cleaned, "score": 0, "sources": set()}
            item = weighted[key]
        item["score"] += score
        if source:
            item["sources"].add(source)

    selected_names: List[str] = []
    parent_names: List[str] = []
    for raw in selected:
        item = raw if isinstance(raw, dict) else {}
        name = str(item.get("name", "") or "").strip()
        path = normalize_relative_path(str(item.get("path", "") or ""))
        parent_path = normalize_relative_path(str(item.get("parent_path", "") or ""))
        if name:
            selected_names.append(name)
            add_candidate(name, 32 if item.get("is_dir") else 18, "选中项")
        if path:
            path_parts = [part for part in path.split("/") if part]
            if len(path_parts) > 1:
                parent_names.extend(path_parts[:-1])
            for part in path_parts[-3:]:
                add_candidate(part, 22 if part != name else 8, "路径")
        if parent_path:
            parts = [part for part in parent_path.split("/") if part]
            parent_names.extend(parts[-2:])
            for part in parts[-2:]:
                add_candidate(part, 26, "父文件夹")
        for part in _split_scraper_title_parts(name or path):
            add_candidate(part, 10, "拆分")

    common_prefix = _common_scraper_prefix(selected_names)
    if common_prefix:
        add_candidate(common_prefix, 34, "公共前缀")

    year = _extract_year_from_names(selected_names + parent_names)
    enriched: List[Dict[str, Any]] = []
    for item in weighted.values():
        keyword = str(item.get("keyword", "") or "").strip()
        if not keyword:
            continue
        score = int(item.get("score", 0) or 0)
        sources = item.get("sources", set()) if isinstance(item.get("sources"), set) else set()
        if _is_scraper_noise_keyword(keyword):
            continue
        if _contains_cjk(keyword):
            score += 25
        if "父文件夹" in sources:
            score += 10
        if re.search(r"\b(?:ddp|aac|dts|hevc|webdl|bluray|remux|hdr|2160p|1080p)\b", keyword, re.I):
            score -= 18
        if year and year not in keyword:
            score += 4
        enriched.append(
            {
                "keyword": keyword,
                "score": max(0, score),
                "source": "、".join(sorted(item.get("sources", set()))) if isinstance(item.get("sources"), set) else "",
            }
        )
        if year and keyword and year not in keyword:
            enriched.append({"keyword": f"{keyword} {year}", "score": max(0, score - 3), "source": "标题+年份"})

    seen: Set[str] = set()
    suggestions: List[Dict[str, Any]] = []
    for item in sorted(enriched, key=lambda payload: int(payload.get("score", 0) or 0), reverse=True):
        key = _scraper_keyword_key(str(item.get("keyword", "") or ""))
        if not key or key in seen:
            continue
        seen.add(key)
        suggestions.append(item)
        if len(suggestions) >= 5:
            break
    return suggestions


def _extract_year_from_names(names: List[str]) -> str:
    for name in names:
        matched = re.search(r"\b(19|20)\d{2}\b", str(name or ""))
        if matched:
            return matched.group(0)
    return ""


def _looks_like_tv(names: List[str]) -> bool:
    text = " ".join(str(name or "") for name in names)
    if re.search(r"\bS\d{1,2}\s*E\d{1,4}\b|\bEP?\s*\d{1,4}\b", text, re.I):
        return True
    if re.search(r"\bS\d{1,2}\b|\bSeason\s*\d{1,2}\b", text, re.I):
        return True
    if re.search(r"第\s*[零〇一二三四五六七八九十两兩0-9]{1,4}\s*(?:季|集|话|話)|(?:全|共)\s*\d{1,4}\s*(?:集|话|話)|完结|完結", text):
        return True
    for name in (names or [])[:10]:
        parsed = _guessit_scraper_release(name)
        if parsed.get("season") is not None or parsed.get("episode") is not None:
            return True
    # 纯数字序号文件（01.mkv / 02.mkv）：文件夹内 ≥2 个按剧集处理，
    # 年份（1900-2099）不参与计数，避免把按年份命名的电影目录误判为剧集。
    numeric_episode_count = 0
    for name in (names or [])[:40]:
        episode = _extract_numeric_episode_from_filename(name)
        if episode > 0 and not (1900 <= episode <= 2099):
            numeric_episode_count += 1
            if numeric_episode_count >= 2:
                return True
    return False


def _build_task_from_tmdb(tmdb: Dict[str, Any], options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = tmdb if isinstance(tmdb, dict) else {}
    opts = options if isinstance(options, dict) else {}
    media_type = normalize_tmdb_media_type(payload.get("tmdb_media_type") or payload.get("media_type"), "movie")
    season = max(1, parse_int(opts.get("season") or payload.get("season") or 1, 1))
    episode_mode = normalize_tmdb_episode_mode(payload.get("tmdb_episode_mode") or payload.get("episode_mode") or "seasonal")
    return {
        "media_type": media_type,
        "season": season,
        "multi_season_mode": media_type == "tv" and episode_mode == "absolute",
        "anime_mode": media_type == "tv" and episode_mode == "absolute",
        "tmdb_id": max(0, parse_int(payload.get("tmdb_id") or payload.get("id") or 0, 0)),
        "tmdb_media_type": media_type,
        "tmdb_total_episodes": max(0, parse_int(payload.get("tmdb_total_episodes") or payload.get("total_episodes") or 0, 0)),
        "tmdb_total_seasons": max(0, parse_int(payload.get("tmdb_total_seasons") or payload.get("total_seasons") or 0, 0)),
        "tmdb_season_episode_map": normalize_tmdb_season_episode_map(payload.get("tmdb_season_episode_map") or payload.get("season_episode_map") or {}),
        "tmdb_episode_mode": episode_mode,
    }


def _scraper_match_key(value: Any) -> str:
    return re.sub(r"[\W_]+", "", str(value or "").lower())


def _score_tmdb_candidate(
    query: str,
    year: str,
    item: Dict[str, Any],
    aliases: Optional[List[str]] = None,
) -> int:
    """对单个 TMDB 候选打分：标题精确命中 > 包含 > 别名/译名 > 年份 > 人气。

    年份是硬约束：已知年份与候选年份冲突时重罚，避免 Robocop(2014) 配到 1987
    这类同名异年错配；人气只做极小加分，最终同分时由排序兜底。
    """
    query_key = _scraper_match_key(query)
    title_key = _scraper_match_key(item.get("title", ""))
    original_key = _scraper_match_key(item.get("original_title", ""))
    if not query_key:
        return 0
    score = 35
    if query_key in {title_key, original_key}:
        score += 35
    elif query_key in title_key or title_key in query_key or query_key in original_key or original_key in query_key:
        score += 22
    for alias in aliases or ():
        alias_key = _scraper_match_key(alias)
        if not alias_key:
            continue
        if alias_key == query_key:
            score += 25
            break
        if query_key in alias_key or alias_key in query_key:
            score += 12
    item_year = str(item.get("year", "") or "").strip()
    if year and item_year == year:
        score += 25
    elif year and item_year:
        score -= 45
    if float(item.get("popularity", 0) or 0) > 10:
        score += 3
    return max(0, min(100, score))


def identify_scraper_media(payload: Dict[str, Any]) -> Dict[str, Any]:
    provider = normalize_scraper_provider(payload.get("provider", "115")) or "115"
    selected = _normalize_scraper_selected_entries(payload.get("entries", []) if isinstance(payload.get("entries"), list) else [])
    names = [str(item.get("path") or item.get("name") or "").strip() for item in selected if isinstance(item, dict)]
    if not names:
        return {"ok": True, "provider": provider, "query": "", "media_type": "movie", "year": "", "keywords": [], "items": [], "candidates": []}
    keywords = build_scraper_keyword_suggestions([item for item in selected if isinstance(item, dict)])
    query = str(keywords[0].get("keyword", "") if keywords else _clean_search_title(names[0])).strip()
    media_type = "tv" if _looks_like_tv(names) else "movie"
    year = _extract_year_from_names(names)
    binding = {}
    return {
        "ok": True,
        "provider": provider,
        "tmdb_configured": not bool(validate_tmdb_runtime_config(get_config())),
        "query": query,
        "media_type": media_type,
        "year": year,
        "keywords": keywords,
        "items": [],
        "candidates": [],
        "binding": binding,
    }


def sanitize_scraper_name(value: str, fallback: str = "Untitled") -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", " ", str(value or "")).strip()
    text = re.sub(r"\s+", " ", text).strip(" .")
    return (text or fallback)[:180]


def _contains_cjk(value: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", str(value or "")))


def choose_scraper_title(tmdb: Dict[str, Any], language: str = "zh", fallback: str = "") -> str:
    payload = tmdb if isinstance(tmdb, dict) else {}
    normalized_language = str(language or "zh").strip().lower()
    if normalized_language in ("", "auto", "default", "config"):
        cfg_language = str((get_config() or {}).get("tmdb_language", "zh-CN") or "zh-CN").strip().lower()
        normalized_language = "en" if cfg_language.startswith("en") else "zh"
    localized = str(payload.get("tmdb_localized_title") or payload.get("tmdb_title") or payload.get("title") or "").strip()
    english = str(payload.get("tmdb_english_title") or "").strip()
    original = str(payload.get("tmdb_original_title") or payload.get("original_title") or "").strip()
    aliases = payload.get("tmdb_aliases") or payload.get("aliases") or []
    alias_values = [str(item or "").strip() for item in aliases if str(item or "").strip()] if isinstance(aliases, list) else []
    if normalized_language in ("en", "english"):
        return sanitize_scraper_name(english or (original if original and not _contains_cjk(original) else "") or localized or fallback)
    if localized and _contains_cjk(localized):
        return sanitize_scraper_name(localized)
    cjk_alias = next((item for item in alias_values if _contains_cjk(item)), "")
    return sanitize_scraper_name(cjk_alias or localized or fallback)


def _build_tag_suffix(tags: List[str]) -> str:
    cleaned = [sanitize_scraper_name(tag, "") for tag in tags if sanitize_scraper_name(tag, "")]
    return f" [{' '.join(cleaned)}]" if cleaned else ""


def _build_scraper_folder_title(title: str, year: str, tmdb: Dict[str, Any], options: Dict[str, Any]) -> str:
    year_suffix = f" ({year})" if year else ""
    folder_title = sanitize_scraper_name(f"{title}{year_suffix}")
    if bool(options.get("include_tmdb_id", False)):
        tmdb_id = max(0, parse_int(tmdb.get("tmdb_id") or tmdb.get("id") or 0, 0))
        if tmdb_id > 0:
            folder_title = sanitize_scraper_name(f"{folder_title} [tmdbid-{tmdb_id}]")
    return folder_title


def _build_scraper_media_titles(tmdb: Dict[str, Any], options: Dict[str, Any], fallback: str = "") -> Tuple[str, str, str]:
    language = str(options.get("title_language", "auto") or "auto")
    title = choose_scraper_title(tmdb, language, fallback=_clean_search_title(fallback))
    year = normalize_tmdb_year(tmdb.get("tmdb_year") or tmdb.get("year") or "") or _extract_year_from_names([fallback])
    file_title = sanitize_scraper_name(f"{title}{f' ({year})' if year else ''}")
    folder_title = _build_scraper_folder_title(title, year, tmdb, options)
    return title, file_title, folder_title


def _resolve_scraper_selection_mode(selected: List[Dict[str, Any]], options: Dict[str, Any]) -> str:
    items = _normalize_scraper_selected_entries(selected)
    single_folder_selection = len(items) == 1 and bool(items[0].get("is_dir"))
    requested = str((options if isinstance(options, dict) else {}).get("selection_mode", "") or "").strip().lower()
    if requested == "folder" and single_folder_selection:
        return "folder"
    if requested == "contents":
        return "contents"
    return "folder" if single_folder_selection else "contents"


def _relative_parent_path_from_base(parent_path: str, base_path: str) -> str:
    source = normalize_relative_path(str(parent_path or "").strip())
    base = normalize_relative_path(str(base_path or "").strip())
    if not source:
        return ""
    if not base:
        return source
    if source == base:
        return ""
    prefix = f"{base}/"
    if source.startswith(prefix):
        return source[len(prefix):]
    return source


def _canonical_scraper_mount_path(path: str, base_path: str) -> str:
    normalized_path = normalize_relative_path(str(path or "").strip())
    normalized_base = normalize_relative_path(str(base_path or "").strip())
    if not normalized_path or not normalized_base:
        return normalized_path
    if normalized_path == normalized_base or normalized_path.startswith(f"{normalized_base}/"):
        return normalized_path
    return normalize_relative_path(join_relative_path(normalized_base, normalized_path))


def _resolve_scraper_tv_episode_info(task: Dict[str, Any], episodes: Set[int], default_season: int) -> Tuple[Dict[str, Any], str]:
    normalized_values = sorted({max(0, int(value or 0)) for value in episodes if max(0, int(value or 0)) > 0})
    if not normalized_values:
        return {}, "无法识别集数"
    season_map = normalize_tmdb_season_episode_map(task.get("tmdb_season_episode_map", {}))
    if is_subscription_multi_season_mode(task) and season_map:
        mapped = [convert_subscription_absolute_to_season_episode(task, value) for value in normalized_values]
        mapped = [(season, episode) for season, episode in mapped if season > 0 and episode > 0]
        if not mapped:
            return {}, "连续编号无法映射到 TMDB 季集"
        seasons = {season for season, _ in mapped}
        if len(seasons) > 1:
            return {}, "单个文件跨季，暂不自动命名"
        season_no = next(iter(seasons))
        episode_values = sorted({episode for _, episode in mapped})
    else:
        season_no = max(1, int(default_season or task.get("season", 1) or 1))
        episode_values = normalized_values
    return {"season": season_no, "episodes": episode_values}, ""


def _normalize_scraper_manual_episode(value: Any) -> int:
    try:
        episode = int(value)
    except (TypeError, ValueError):
        return 0
    return episode if episode > 0 else 0


def _normalize_scraper_manual_episode_overrides(raw_overrides: Any) -> Dict[str, int]:
    if not isinstance(raw_overrides, dict):
        return {}
    episode_values: Dict[str, int] = {}
    for raw_entry_id, raw_episode in raw_overrides.items():
        entry_id = str(raw_entry_id or "").strip()
        episode = _normalize_scraper_manual_episode(raw_episode)
        if not entry_id or episode <= 0:
            continue
        episode_values[entry_id] = episode
    return episode_values


def _resolve_scraper_manual_episode_info(
    task: Dict[str, Any],
    entry: Dict[str, Any],
    episode: int,
    default_season: int,
) -> Tuple[Dict[str, Any], str]:
    item = entry if isinstance(entry, dict) else {}
    parent_path = normalize_relative_path(str(item.get("parent_path", "") or ""))
    source_path = normalize_relative_path(str(item.get("path", "") or item.get("name", "")))
    source_season = _extract_subscription_season_from_name(parent_path) or _extract_subscription_season_from_name(source_path)
    normalized_episode = _normalize_scraper_manual_episode(episode)
    if normalized_episode <= 0:
        return {}, "手动集数无效"
    if is_subscription_multi_season_mode(task) and source_season > 0:
        absolute_episode = convert_subscription_episode_to_absolute(task, source_season, normalized_episode)
        if absolute_episode <= 0:
            return {}, "手动集数无法映射到 TMDB 季集"
        return _resolve_scraper_tv_episode_info(task, {absolute_episode}, default_season)
    return _resolve_scraper_tv_episode_info(task, {normalized_episode}, source_season or default_season)


def _resolve_scraper_auto_episode_info(
    task: Dict[str, Any],
    entry: Dict[str, Any],
    default_season: int,
) -> Tuple[Dict[str, Any], str]:
    """自动识别刮削文件的季集信息。

    文件或父路径带明确季号时优先使用该季号（与手动集数覆盖保持一致），
    完全没有季号时才用“未识别时默认季号”兜底。避免 S03E07 这类标准文件名
    因页面默认季号为 1 而被单季模式以 season_mismatch 拒绝。
    """
    item = entry if isinstance(entry, dict) else {}
    parent_path = normalize_relative_path(str(item.get("parent_path", "") or ""))
    source_path = normalize_relative_path(str(item.get("path", "") or item.get("name", "")))
    source_season = _extract_subscription_season_from_name(parent_path) or _extract_subscription_season_from_name(source_path)
    effective_season = max(1, int(source_season or default_season or task.get("season", 1) or 1))
    effective_task = dict(task)
    effective_task["season"] = effective_season
    episodes = _extract_task_episodes_from_file_entry(
        effective_task,
        str(item.get("path") or item.get("name") or ""),
        parent_path=parent_path,
    )
    return _resolve_scraper_tv_episode_info(effective_task, episodes, effective_season)


def _scraper_episode_width_from_value(value: int) -> int:
    return max(2, len(str(max(0, int(value or 0)))))


def _scraper_tmdb_episode_total_for_season(task: Dict[str, Any], season_no: int) -> int:
    target_season = max(1, int(season_no or 1))
    season_map = normalize_tmdb_season_episode_map(task.get("tmdb_season_episode_map", {}))
    if season_map:
        return max(0, int(season_map.get(str(target_season), 0) or 0))
    tmdb_total_seasons = max(0, int(task.get("tmdb_total_seasons", 0) or 0))
    tmdb_total_episodes = max(0, int(task.get("tmdb_total_episodes", 0) or 0))
    task_season = max(1, int(task.get("season", 1) or 1))
    if tmdb_total_episodes > 0 and (tmdb_total_seasons <= 1 or target_season == task_season):
        return tmdb_total_episodes
    return 0


def _build_scraper_episode_widths_by_season(
    task: Dict[str, Any],
    episode_infos: List[Dict[str, Any]],
) -> Dict[int, int]:
    season_max_episodes: Dict[int, int] = {}
    for info in episode_infos:
        season_no = max(1, int((info or {}).get("season", 1) or 1))
        episodes = [
            max(0, int(value or 0))
            for value in ((info or {}).get("episodes", []) if isinstance((info or {}).get("episodes", []), list) else [])
            if max(0, int(value or 0)) > 0
        ]
        file_max = max(episodes) if episodes else 0
        tmdb_max = _scraper_tmdb_episode_total_for_season(task, season_no)
        season_max_episodes[season_no] = max(season_max_episodes.get(season_no, 0), file_max, tmdb_max)
    return {season_no: _scraper_episode_width_from_value(max_episode) for season_no, max_episode in season_max_episodes.items()}


def _format_tv_episode_code(episode_info: Dict[str, Any], episode_width: int = 2) -> Tuple[str, str]:
    season_no = max(1, int((episode_info or {}).get("season", 1) or 1))
    episode_values = sorted(
        {
            max(0, int(value or 0))
            for value in ((episode_info or {}).get("episodes", []) if isinstance((episode_info or {}).get("episodes", []), list) else [])
            if max(0, int(value or 0)) > 0
        }
    )
    if not episode_values:
        return "", "无法识别集数"
    width = max(2, int(episode_width or 2))

    def _episode_label(value: int) -> str:
        return f"E{max(0, int(value or 0)):0{width}d}"

    if len(episode_values) == 1:
        return f"S{season_no:02d}{_episode_label(episode_values[0])}", ""
    return f"S{season_no:02d}{_episode_label(episode_values[0])}-{_episode_label(episode_values[-1])}", ""


def _build_scraper_target_path(
    entry: Dict[str, Any],
    tmdb: Dict[str, Any],
    options: Dict[str, Any],
    episode_info: Optional[Dict[str, Any]] = None,
    episode_widths_by_season: Optional[Dict[int, int]] = None,
    subtitle_suffix: str = "",
    subtitle_index: int = 0,
) -> Tuple[str, str]:
    media_type = normalize_tmdb_media_type(tmdb.get("tmdb_media_type") or tmdb.get("media_type"), "movie")
    organize_into_media_folder = bool(options.get("organize_into_media_folder", True))
    use_season_subfolder = bool(options.get("use_season_subfolder", True))
    preserve_source_parent_path = bool(options.get("preserve_source_parent_path", False))
    organize_inside_source_folder = bool(options.get("organize_inside_source_folder", False))
    source_relative_parent_path = _relative_parent_path_from_base(
        str(entry.get("parent_path", "") or ""),
        str(options.get("base_path", "") or ""),
    )
    _, ext = os.path.splitext(str(entry.get("name", "") or ""))
    tags = media_tag_labels(str(entry.get("name", "") or ""), options.get("preserve_tags", {})) if bool(options.get("preserve_file_info", False)) else []
    tag_suffix = _build_tag_suffix(tags)
    subtitle_part = f" ({subtitle_index})" if subtitle_index > 1 else ""
    _, file_title, folder_title = _build_scraper_media_titles(tmdb, options, str(entry.get("name", "") or ""))
    if media_type == "tv":
        task = _build_task_from_tmdb(tmdb, options)
        resolved_episode_info = episode_info if isinstance(episode_info, dict) else {}
        if not resolved_episode_info:
            resolved_episode_info, issue = _resolve_scraper_auto_episode_info(
                task,
                entry,
                max(1, parse_int(options.get("season") or task.get("season") or 1, 1)),
            )
            if issue:
                return "", issue
        season_no = max(1, int(resolved_episode_info.get("season") or options.get("season") or 1))
        episode_width = (
            episode_widths_by_season.get(season_no, 2)
            if isinstance(episode_widths_by_season, dict)
            else 2
        )
        if episode_width <= 2 and not (isinstance(episode_widths_by_season, dict) and season_no in episode_widths_by_season):
            fallback_widths = _build_scraper_episode_widths_by_season(task, [resolved_episode_info])
            episode_width = fallback_widths.get(season_no, episode_width)
        episode_code, issue = _format_tv_episode_code(resolved_episode_info, episode_width)
        if issue:
            return "", issue
        file_name = sanitize_scraper_name(
            f"{file_title} - {episode_code}{tag_suffix}{subtitle_part}{subtitle_suffix}"
        ) + ext
        if preserve_source_parent_path:
            return normalize_relative_path(join_relative_path(source_relative_parent_path, file_name)), ""
        if not organize_into_media_folder:
            return file_name, ""
        organize_root = source_relative_parent_path if organize_inside_source_folder else folder_title
        if not use_season_subfolder:
            return normalize_relative_path(join_relative_path(organize_root, file_name)), ""
        return normalize_relative_path(join_relative_path(organize_root, f"Season {season_no:02d}", file_name)), ""
    file_name = sanitize_scraper_name(f"{file_title}{tag_suffix}{subtitle_part}{subtitle_suffix}") + ext
    if preserve_source_parent_path:
        return normalize_relative_path(join_relative_path(source_relative_parent_path, file_name)), ""
    if not organize_into_media_folder:
        return file_name, ""
    organize_root = source_relative_parent_path if organize_inside_source_folder else folder_title
    return normalize_relative_path(join_relative_path(organize_root, file_name)), ""


def _get_scraper_cached_entries_payload(
    provider: str,
    cookie: str,
    cid: str,
    folders_only: bool,
    cache: Optional[Dict[Tuple[str, bool], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    target_id = str(cid or "0").strip() or "0"
    cache_key = (target_id, bool(folders_only))
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    payload = _list_provider_entries_payload(provider, cookie, target_id, folders_only=folders_only)
    if cache is not None:
        cache[cache_key] = payload
    return payload


def _walk_existing_folder(
    provider: str,
    cookie: str,
    base_cid: str,
    folder_path: str,
    *,
    entries_cache: Optional[Dict[Tuple[str, bool], Dict[str, Any]]] = None,
    path_cache: Optional[Dict[Tuple[str, str], Tuple[str, bool]]] = None,
) -> Tuple[str, bool]:
    current = str(base_cid or "0").strip() or "0"
    normalized_folder_path = normalize_relative_path(folder_path)
    path_cache_key = (current, normalized_folder_path)
    if path_cache is not None and path_cache_key in path_cache:
        return path_cache[path_cache_key]
    parts = [part for part in normalize_relative_path(folder_path).split("/") if part]
    for part in parts:
        payload = _get_scraper_cached_entries_payload(provider, cookie, current, True, entries_cache)
        entries = payload.get("entries", []) if isinstance(payload, dict) and isinstance(payload.get("entries"), list) else []
        matched = next((item for item in entries if item.get("is_dir") and str(item.get("name", "") or "").strip() == part), None)
        if not matched:
            if path_cache is not None:
                path_cache[path_cache_key] = ("", False)
            return "", False
        current = str(matched.get("id") or matched.get("cid") or "").strip() or "0"
    result = (current, True)
    if path_cache is not None:
        path_cache[path_cache_key] = result
    return result


def _ensure_folder_from_base(provider: str, cookie: str, base_cid: str, folder_path: str) -> str:
    current = str(base_cid or "0").strip() or "0"
    for part in [part for part in normalize_relative_path(folder_path).split("/") if part]:
        payload = _list_provider_entries_payload(provider, cookie, current, folders_only=True)
        entries = payload.get("entries", []) if isinstance(payload, dict) and isinstance(payload.get("entries"), list) else []
        matched = next((item for item in entries if item.get("is_dir") and str(item.get("name", "") or "").strip() == part), None)
        if matched:
            current = str(matched.get("id") or matched.get("cid") or "").strip() or current
            continue
        created = _create_provider_folder(provider, cookie, current, part)
        current = str(created.get("id", "") or "").strip() or current
    return current


def _target_name_exists(
    provider: str,
    cookie: str,
    parent_id: str,
    target_name: str,
    same_entry_id: str = "",
    *,
    entries_cache: Optional[Dict[Tuple[str, bool], Dict[str, Any]]] = None,
) -> bool:
    if not parent_id:
        return False
    payload = _get_scraper_cached_entries_payload(provider, cookie, parent_id, False, entries_cache)
    entries = payload.get("entries", []) if isinstance(payload, dict) and isinstance(payload.get("entries"), list) else []
    for item in entries:
        if str(item.get("name", "") or "").strip() != target_name:
            continue
        if same_entry_id and str(item.get("id", "") or "").strip() == same_entry_id:
            continue
        return True
    return False


def _is_scraper_folder_rename_affecting_path(folder_path: str, target_path: str) -> bool:
    normalized_folder = normalize_relative_path(str(folder_path or "").strip())
    normalized_target = normalize_relative_path(str(target_path or "").strip())
    if not normalized_folder or not normalized_target:
        return False
    if normalized_folder == normalized_target:
        return True
    return normalized_target.startswith(f"{normalized_folder}/")


def _collect_scraper_subscription_path_warning(
    provider: str,
    candidate_paths: List[str],
    *,
    kind: str = "generic",
) -> str:
    normalized_provider = normalize_scraper_provider(provider) or "115"
    normalized_paths = unique_preserve_order(
        [normalize_relative_path(str(item or "").strip()) for item in (candidate_paths or []) if normalize_relative_path(str(item or "").strip())]
    )
    if not normalized_paths:
        return ""

    cfg = get_config()
    tasks = cfg.get("subscription_tasks", []) if isinstance(cfg.get("subscription_tasks"), list) else []
    for raw_task in tasks:
        task = normalize_subscription_task(raw_task or {})
        if not task.get("name"):
            continue
        if normalize_subscription_provider(task.get("provider", "115"), fallback="115") != normalized_provider:
            continue
        task_savepath = normalize_relative_path(str(task.get("savepath", "") or "").strip())
        if not task_savepath:
            continue
        label = str(task.get("title", "") or task.get("name", "") or "").strip() or "未命名任务"
        affected_folder_path = ""
        for candidate_path in normalized_paths:
            if _is_scraper_folder_rename_affecting_path(candidate_path, task_savepath):
                affected_folder_path = candidate_path
                break
        if not affected_folder_path:
            continue
        if affected_folder_path == task_savepath:
            return f"文件夹【{affected_folder_path}】是订阅任务【{label}】的保存路径；重命名后可能导致保存路径失效。"
        return f"文件夹【{affected_folder_path}】是订阅任务【{label}】保存路径【{task_savepath}】的上级目录；重命名后可能导致保存路径失效。"

    return ""


def _collect_scraper_subscription_rename_warning(provider: str, old_path: str, new_path: str) -> str:
    return _collect_scraper_subscription_path_warning(provider, [old_path], kind="folder_rename")


def _collect_scraper_action_warning(provider: str, action: Dict[str, Any]) -> str:
    if not bool(action.get("is_dir")):
        return ""
    folder_path = str(action.get("old_path", "") or "").strip()
    if not folder_path:
        old_path = normalize_relative_path(str(action.get("old_path", "") or "").strip())
        folder_path = os.path.dirname(old_path).replace("\\", "/") if old_path else ""
    return _collect_scraper_subscription_path_warning(provider, [folder_path], kind="folder_rename")


def _expand_selected_scraper_entries(provider: str, cookie: str, selected: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    files: List[Dict[str, Any]] = []
    issues: List[str] = []
    dirs_seen = 0
    for raw in selected:
        item = raw if isinstance(raw, dict) else {}
        entry = _compact_scraper_entry(item, str(item.get("parent_id", "") or "0"), normalize_relative_path(str(item.get("parent_path", "") or "")))
        if not entry:
            continue
        if not entry.get("is_dir"):
            if _is_scraper_excluded_archive(str(entry.get("name", "") or "")):
                continue
            files.append(entry)
            continue
        queue: List[Tuple[str, str, int]] = [(str(entry.get("id", "") or entry.get("cid", "") or "0"), normalize_relative_path(str(entry.get("path", "") or entry.get("name", ""))), 0)]
        while queue and len(files) < SCRAPER_SCAN_MAX_ENTRIES and dirs_seen < SCRAPER_SCAN_MAX_DIRS:
            dir_id, dir_path, depth = queue.pop(0)
            dirs_seen += 1
            try:
                payload = _list_provider_entries_payload(provider, cookie, dir_id, folders_only=False)
            except Exception as exc:
                issues.append(f"读取目录 {dir_path or dir_id} 失败：{exc}")
                continue
            for child in payload.get("entries", []) if isinstance(payload, dict) else []:
                child_entry = _compact_scraper_entry(child, dir_id, dir_path)
                if not child_entry:
                    continue
                if child_entry.get("is_dir"):
                    if depth < 6:
                        queue.append((str(child_entry.get("id") or child_entry.get("cid") or "0"), normalize_relative_path(str(child_entry.get("path", ""))), depth + 1))
                else:
                    if _is_scraper_excluded_archive(str(child_entry.get("name", "") or "")):
                        continue
                    child_entry["parent_path"] = dir_path
                    files.append(child_entry)
                    if len(files) >= SCRAPER_SCAN_MAX_ENTRIES:
                        issues.append(f"已达到首版扫描上限 {SCRAPER_SCAN_MAX_ENTRIES} 个文件，超出部分未纳入计划")
                        break
    return files, issues


def build_scraper_rename_plan(payload: Dict[str, Any]) -> Dict[str, Any]:
    provider = normalize_scraper_provider(payload.get("provider", "115")) or "115"
    _require_scraper_operation(provider, "scrape", "执行")
    cookie = _require_provider_cookie(provider)
    tmdb = payload.get("tmdb") if isinstance(payload.get("tmdb"), dict) else {}
    if max(0, parse_int(tmdb.get("tmdb_id") or tmdb.get("id") or 0, 0)) <= 0:
        raise RuntimeError("请先选择 TMDB 条目")
    options = payload.get("options") if isinstance(payload.get("options"), dict) else {}
    base_cid = str(payload.get("base_cid", "0") or "0").strip() or "0"
    base_path = normalize_relative_path(str(payload.get("base_path", "") or ""))
    selected = _normalize_scraper_selected_entries(payload.get("entries", []) if isinstance(payload.get("entries"), list) else [])
    if not base_path and selected:
        selected_parent_paths = {
            normalize_relative_path(str(item.get("parent_path", "") or "").strip())
            for item in selected
            if isinstance(item, dict) and str(item.get("parent_path", "") or "").strip()
        }
        if len(selected_parent_paths) == 1:
            base_path = next(iter(selected_parent_paths))
    plan_options = dict(options)
    selection_mode = _resolve_scraper_selection_mode(selected, plan_options)
    folder_mode = selection_mode == "folder"
    plan_options["selection_mode"] = selection_mode
    plan_options["base_path"] = base_path
    plan_options["organize_into_media_folder"] = folder_mode
    plan_options["preserve_source_parent_path"] = not folder_mode
    # 文件夹条目不重命名文件夹时，文件仍整理在源文件夹内部，避免留下空的旧文件夹。
    plan_options["organize_inside_source_folder"] = bool(
        folder_mode and not bool(plan_options.get("rename_selected_folders", True))
    )
    if not folder_mode:
        plan_options["include_tmdb_id"] = False
        plan_options["use_season_subfolder"] = False
        plan_options["rename_selected_folders"] = False
    expanded_files, scan_issues = _expand_selected_scraper_entries(provider, cookie, selected)
    media_type = normalize_tmdb_media_type(tmdb.get("tmdb_media_type") or tmdb.get("media_type"), "movie")
    task = _build_task_from_tmdb(tmdb, plan_options) if media_type == "tv" else {}
    default_season = max(1, parse_int(plan_options.get("season") or task.get("season") or 1, 1)) if media_type == "tv" else 1
    file_episode_infos: List[Dict[str, Any]] = []
    episode_widths_by_season: Dict[int, int] = {}
    manual_episode_values: Dict[str, int] = {}
    if media_type == "tv":
        manual_episode_values = _normalize_scraper_manual_episode_overrides(payload.get("episode_overrides"))
        for entry in expanded_files:
            entry_id = str(entry.get("id", "") or "").strip()
            if _scraper_file_category(str(entry.get("name", "") or "")) in ("ad", "other"):
                file_episode_infos.append(None)
                continue
            manual_episode = manual_episode_values.get(entry_id, 0)
            if manual_episode > 0:
                manual_episode_info, _ = _resolve_scraper_manual_episode_info(
                    task,
                    entry,
                    manual_episode,
                    default_season,
                )
                file_episode_infos.append(manual_episode_info)
                continue
            episode_info, _ = _resolve_scraper_auto_episode_info(task, entry, default_season)
            file_episode_infos.append(episode_info)
        episode_widths_by_season = _build_scraper_episode_widths_by_season(
            task,
            [info for info in file_episode_infos if info],
        )
    actions: List[Dict[str, Any]] = []
    issues: List[str] = list(scan_issues)
    warnings: List[str] = []
    target_paths: Set[str] = set()
    target_folder_names: Set[str] = set()
    preview_entries_cache: Dict[Tuple[str, bool], Dict[str, Any]] = {}
    preview_folder_path_cache: Dict[Tuple[str, str], Tuple[str, bool]] = {}
    action_index = 1
    unchanged_count = 0
    ignored_names: List[str] = []
    unchanged_rows: List[Dict[str, Any]] = []
    delete_actions: List[Dict[str, Any]] = []
    subtitle_seen: Dict[Tuple[str, str], int] = {}
    if folder_mode and bool(plan_options.get("rename_selected_folders", True)):
        _, _, target_folder_name = _build_scraper_media_titles(tmdb, plan_options, "")
        for raw in selected:
            item = raw if isinstance(raw, dict) else {}
            if not item.get("is_dir"):
                continue
            entry = _compact_scraper_entry(item, str(item.get("parent_id", "") or base_cid), normalize_relative_path(str(item.get("parent_path", "") or "")))
            if not entry:
                continue
            old_parent_id = str(entry.get("parent_id", "") or base_cid).strip() or "0"
            old_name = str(entry.get("name", "") or "")
            old_path = _canonical_scraper_mount_path(
                str(entry.get("path", "") or old_name),
                base_path,
            )
            new_name = target_folder_name
            if not new_name or new_name == old_name:
                if new_name and new_name == old_name:
                    unchanged_count += 1
                    unchanged_rows.append(
                        {
                            "old_name": old_name,
                            "old_path": old_path,
                            "new_name": old_name,
                            "new_path": old_path,
                            "is_dir": True,
                        }
                    )
                continue
            action_issue = ""
            if new_name in target_folder_names:
                action_issue = "本批次内目标文件夹重复"
            target_folder_names.add(new_name)
            if _target_name_exists(
                provider,
                cookie,
                old_parent_id,
                new_name,
                same_entry_id=str(entry.get("id", "") or ""),
                entries_cache=preview_entries_cache,
            ):
                action_issue = "当前目录中已有同名文件夹"
            action = {
                "action_index": action_index,
                "entry_id": str(entry.get("id", "") or ""),
                "is_dir": True,
                "old_parent_id": old_parent_id,
                "old_name": old_name,
                "old_path": old_path,
                "new_parent_id": old_parent_id,
                "new_name": new_name,
                "new_path": _canonical_scraper_mount_path(
                    join_relative_path(normalize_relative_path(str(item.get("parent_path", "") or "")), new_name),
                    base_path,
                ),
                "target_parent_path": "",
                "file_size": max(0, parse_int(entry.get("size", 0), 0)),
                "remote_modified": str(entry.get("modified_at", "") or ""),
                "issue": action_issue,
                "warning": "",
                "ready": bool(new_name and not action_issue),
            }
            if not action_issue:
                action_warning = _collect_scraper_action_warning(provider, action)
                if action_warning:
                    action["warning"] = action_warning
                    warnings.append(action_warning)
            if action_issue:
                issues.append(f"{old_name or '--'}：{action_issue}")
            actions.append(action)
            action_index += 1
    for file_index, entry in enumerate(expanded_files):
        entry_name = str(entry.get("name", "") or "")
        category = _scraper_file_category(entry_name)
        file_size = max(0, parse_int(entry.get("size", 0), 0))
        if _is_scraper_ad_file(entry_name, file_size):
            if bool(plan_options.get("delete_ad_files", False)):
                delete_actions.append(entry)
            else:
                ignored_names.append(entry_name)
            continue
        if category == "other" or (category == "image" and _is_scraper_standard_image(entry_name)):
            ignored_names.append(entry_name)
            continue
        episode_info = file_episode_infos[file_index] if file_index < len(file_episode_infos) else None
        if media_type == "tv" and category in ("subtitle", "image") and not episode_info:
            # 剧集字幕/封面解析不到集数时保留原名，不生成改名动作。
            ignored_names.append(entry_name)
            continue
        subtitle_suffix = _scraper_subtitle_suffix(entry_name) if category == "subtitle" else ""
        execution_target_path, issue = _build_scraper_target_path(
            entry,
            tmdb,
            plan_options,
            episode_info=episode_info,
            episode_widths_by_season=episode_widths_by_season,
            subtitle_suffix=subtitle_suffix,
        )
        if category == "subtitle" and not issue:
            subtitle_dir = (
                normalize_relative_path(os.path.dirname(execution_target_path).replace("\\", "/"))
                if execution_target_path
                else ""
            )
            subtitle_key = (subtitle_dir, subtitle_suffix)
            subtitle_seen[subtitle_key] = subtitle_seen.get(subtitle_key, 0) + 1
            subtitle_index = subtitle_seen[subtitle_key]
            if subtitle_index > 1:
                execution_target_path, issue = _build_scraper_target_path(
                    entry,
                    tmdb,
                    plan_options,
                    episode_info=episode_info,
                    episode_widths_by_season=episode_widths_by_season,
                    subtitle_suffix=subtitle_suffix,
                    subtitle_index=subtitle_index,
                )
        target_path = _canonical_scraper_mount_path(execution_target_path, base_path)
        old_parent_id = str(entry.get("parent_id", "") or base_cid).strip() or "0"
        old_path = _canonical_scraper_mount_path(
            str(entry.get("path", "") or entry.get("name", "")),
            base_path,
        )
        action_issue = issue
        if target_path and target_path == old_path:
            unchanged_count += 1
            unchanged_rows.append(
                {
                    "old_name": entry_name,
                    "old_path": old_path,
                    "new_name": entry_name,
                    "new_path": target_path,
                    "is_dir": False,
                }
            )
            continue
        target_parent_path = (
            normalize_relative_path(os.path.dirname(execution_target_path).replace("\\", "/"))
            if execution_target_path
            else ""
        )
        new_name = os.path.basename(execution_target_path) if execution_target_path else ""
        existing_parent_id = ""
        if target_path:
            if target_path in target_paths:
                action_issue = action_issue or "本批次内目标路径重复"
            target_paths.add(target_path)
            existing_parent_id, exists = _walk_existing_folder(
                provider,
                cookie,
                base_cid,
                target_parent_path,
                entries_cache=preview_entries_cache,
                path_cache=preview_folder_path_cache,
            )
            if exists and _target_name_exists(
                provider,
                cookie,
                existing_parent_id,
                new_name,
                same_entry_id=str(entry.get("id", "") or ""),
                entries_cache=preview_entries_cache,
            ):
                action_issue = action_issue or "目标目录中已有同名文件"
        action = {
            "action_index": action_index,
            "entry_id": str(entry.get("id", "") or ""),
            "is_dir": False,
            "old_parent_id": old_parent_id,
            "old_name": str(entry.get("name", "") or ""),
            "old_path": old_path,
            "new_parent_id": existing_parent_id,
            "new_name": new_name,
            "new_path": target_path,
            "target_parent_path": target_parent_path,
            "file_size": max(0, parse_int(entry.get("size", 0), 0)),
            "remote_modified": str(entry.get("modified_at", "") or ""),
            "issue": action_issue,
            "warning": "",
            "ready": bool(target_path and not action_issue),
        }
        manual_episode = manual_episode_values.get(str(entry.get("id", "") or "").strip(), 0)
        if media_type == "tv" and (manual_episode > 0 or action_issue == "无法识别集数"):
            action["manual_episode_allowed"] = True
        if manual_episode > 0:
            action["manual_episode"] = manual_episode
        action_warning = _collect_scraper_action_warning(provider, action)
        if action_warning:
            action["warning"] = action_warning
            warnings.append(action_warning)
        if action_issue:
            issues.append(f"{entry.get('name', '--')}：{action_issue}")
        actions.append(action)
        action_index += 1
    for entry in delete_actions:
        entry_name = str(entry.get("name", "") or "")
        old_parent_id = str(entry.get("parent_id", "") or base_cid).strip() or "0"
        old_path = _canonical_scraper_mount_path(
            str(entry.get("path", "") or entry_name),
            base_path,
        )
        actions.append(
            {
                "action_index": action_index,
                "entry_id": str(entry.get("id", "") or ""),
                "is_dir": False,
                "old_parent_id": old_parent_id,
                "old_name": entry_name,
                "old_path": old_path,
                "new_name": "",
                "new_path": "",
                "target_parent_path": "",
                "file_size": max(0, parse_int(entry.get("size", 0), 0)),
                "remote_modified": str(entry.get("modified_at", "") or ""),
                "issue": "",
                "warning": "广告文件，整理时删除",
                "delete": True,
                "ready": True,
            }
        )
        action_index += 1
    if delete_actions:
        warnings.append(f"将删除 {len(delete_actions)} 个广告文件（进入网盘回收站）")
    if ignored_names:
        ignored_preview = "、".join(ignored_names[:5])
        warnings.append(
            f"已保留 {len(ignored_names)} 个非影视文件不改名（广告/说明/标准封面等）：{ignored_preview}"
            + (" 等" if len(ignored_names) > 5 else "")
        )
    ready_count = sum(1 for item in actions if item.get("ready"))
    return {
        "ok": True,
        "provider": provider,
        "base_cid": base_cid,
        "base_path": base_path,
        "actions": actions,
        "issues": issues,
        "warnings": unique_preserve_order(warnings),
        "ready": bool(actions) and ready_count == len(actions) and not issues,
        "ready_count": ready_count,
        "total_count": len(actions),
        "unchanged_count": unchanged_count,
        "unchanged_rows": unchanged_rows,
        "ignored_count": len(ignored_names),
        "tmdb": tmdb,
        "options": plan_options,
    }


def _insert_scraper_job(provider: str, plan: Dict[str, Any], options: Dict[str, Any], tmdb: Dict[str, Any]) -> int:
    ensure_db()
    now = now_text()
    actions = [item for item in plan.get("actions", []) if isinstance(item, dict)]
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO scraper_jobs(
                provider, status, status_detail, total_actions, created_at, updated_at,
                options_json, tmdb_json, plan_json
            ) VALUES (?, 'pending', '等待执行', ?, ?, ?, ?, ?, ?)
            """,
            (
                provider,
                len(actions),
                now,
                now,
                safe_json_dumps(options),
                safe_json_dumps(tmdb),
                safe_json_dumps(
                    {
                        "base_cid": plan.get("base_cid", "0"),
                        "base_path": plan.get("base_path", "") or options.get("base_path", ""),
                        "actions": actions,
                    }
                ),
            ),
        )
        job_id = int(cursor.lastrowid or 0)
        for action in actions:
            cursor.execute(
                """
                INSERT INTO scraper_job_actions(
                    job_id, action_index, provider, entry_id, is_dir, old_parent_id, old_name, old_path,
                    new_parent_id, new_name, new_path, target_parent_path, file_size, remote_modified,
                    status, status_detail,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', '', ?, ?)
                """,
                (
                    job_id,
                    max(0, parse_int(action.get("action_index"), 0)),
                    provider,
                    str(action.get("entry_id", "") or ""),
                    1 if action.get("is_dir") else 0,
                    str(action.get("old_parent_id", "") or "0"),
                    str(action.get("old_name", "") or ""),
                    str(action.get("old_path", "") or ""),
                    str(action.get("new_parent_id", "") or ""),
                    str(action.get("new_name", "") or ""),
                    str(action.get("new_path", "") or ""),
                    str(action.get("target_parent_path", "") or ""),
                    max(0, parse_int(action.get("file_size", 0), 0)),
                    str(action.get("remote_modified", "") or ""),
                    now,
                    now,
                ),
            )
        conn.commit()
    return job_id


def create_scraper_job_from_plan(payload: Dict[str, Any]) -> Dict[str, Any]:
    plan = payload.get("plan") if isinstance(payload.get("plan"), dict) else {}
    provider = normalize_scraper_provider(plan.get("provider") or payload.get("provider", "115")) or "115"
    _require_scraper_operation(provider, "scrape", "执行")
    actions = [item for item in plan.get("actions", []) if isinstance(item, dict)]
    if not actions:
        raise RuntimeError("没有可执行的改名计划")
    blocked = [item for item in actions if item.get("issue") or not item.get("ready")]
    if blocked:
        raise RuntimeError("改名计划仍存在冲突或未识别项，请先处理后再执行")
    options = plan.get("options") if isinstance(plan.get("options"), dict) else {}
    tmdb = plan.get("tmdb") if isinstance(plan.get("tmdb"), dict) else {}
    tmdb = _derive_scraper_batch_job_title(plan, actions, tmdb)
    job_id = _insert_scraper_job(provider, plan, options, tmdb)
    return {"ok": True, "job_id": job_id}


def _derive_scraper_batch_job_title(
    plan: Dict[str, Any],
    actions: List[Dict[str, Any]],
    tmdb: Dict[str, Any],
) -> Dict[str, Any]:
    """批量任务的任务名按实际执行的条目展示 TMDB 标题：
    单条用“标题 (年份)”，多条用“首部标题 等 N 项”；无条目信息时维持原任务名。"""
    if not tmdb.get("batch"):
        return tmdb
    items = [
        item
        for item in plan.get("items", [])
        if isinstance(item, dict) and str(item.get("title") or item.get("name") or "").strip()
    ]
    if not items:
        return tmdb
    selected_indexes = {max(0, int(item.get("item_index", 0) or 0)) for item in actions}
    if selected_indexes:
        matched = [
            item
            for item in items
            if max(0, int(item.get("item_index", 0) or 0)) in selected_indexes
        ]
        if matched:
            items = matched
    first_title = str(items[0].get("title") or items[0].get("name") or "").strip()
    if not first_title:
        return tmdb
    if len(items) == 1:
        year = str(items[0].get("year") or "").strip()
        job_title = f"{first_title} ({year})" if year else first_title
    else:
        job_title = f"{first_title} 等 {len(items)} 项"
    return {**tmdb, "title": job_title}


def _serialize_scraper_action_row(row: Any) -> Dict[str, Any]:
    item = sqlite_row_to_dict(row)
    if not item:
        return {}
    return {
        "id": int(item.get("id", 0) or 0),
        "job_id": int(item.get("job_id", 0) or 0),
        "action_index": int(item.get("action_index", 0) or 0),
        "provider": str(item.get("provider", "") or ""),
        "entry_id": str(item.get("entry_id", "") or ""),
        "is_dir": bool(item.get("is_dir", 0)),
        "old_parent_id": str(item.get("old_parent_id", "") or ""),
        "old_name": str(item.get("old_name", "") or ""),
        "old_path": str(item.get("old_path", "") or ""),
        "new_parent_id": str(item.get("new_parent_id", "") or ""),
        "new_name": str(item.get("new_name", "") or ""),
        "new_path": str(item.get("new_path", "") or ""),
        "target_parent_path": str(item.get("target_parent_path", "") or ""),
        "file_size": max(0, int(item.get("file_size", 0) or 0)),
        "remote_modified": str(item.get("remote_modified", "") or ""),
        "status": str(item.get("status", "") or ""),
        "status_detail": str(item.get("status_detail", "") or ""),
        "rollback_status": str(item.get("rollback_status", "") or ""),
        "rollback_detail": str(item.get("rollback_detail", "") or ""),
        "updated_at": str(item.get("updated_at", "") or ""),
    }


def _serialize_scraper_job_row(row: Any, actions: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    item = sqlite_row_to_dict(row)
    if not item:
        return {}
    return {
        "id": int(item.get("id", 0) or 0),
        "provider": str(item.get("provider", "") or ""),
        "status": str(item.get("status", "") or ""),
        "status_detail": str(item.get("status_detail", "") or ""),
        "total_actions": int(item.get("total_actions", 0) or 0),
        "succeeded_actions": int(item.get("succeeded_actions", 0) or 0),
        "failed_actions": int(item.get("failed_actions", 0) or 0),
        "rollback_succeeded_actions": int(item.get("rollback_succeeded_actions", 0) or 0),
        "rollback_failed_actions": int(item.get("rollback_failed_actions", 0) or 0),
        "created_at": str(item.get("created_at", "") or ""),
        "updated_at": str(item.get("updated_at", "") or ""),
        "started_at": str(item.get("started_at", "") or ""),
        "finished_at": str(item.get("finished_at", "") or ""),
        "options": safe_json_loads(item.get("options_json", "{}"), {}),
        "tmdb": safe_json_loads(item.get("tmdb_json", "{}"), {}),
        "can_rollback": int(item.get("succeeded_actions", 0) or 0) > 0 and str(item.get("status", "") or "") in {"completed", "partial", "rollback_failed"},
        "actions": actions or [],
    }


def get_scraper_jobs_state(limit: int = SCRAPER_JOB_LIMIT_DEFAULT, job_id: int = 0) -> Dict[str, Any]:
    ensure_db()
    with db_connection() as conn:
        cursor = conn.cursor()
        if job_id > 0:
            cursor.execute("SELECT * FROM scraper_jobs WHERE id = ?", (int(job_id),))
            rows = cursor.fetchall()
        else:
            cursor.execute(
                "SELECT * FROM scraper_jobs ORDER BY id DESC LIMIT ?",
                (max(1, min(100, int(limit or SCRAPER_JOB_LIMIT_DEFAULT))),),
            )
            rows = cursor.fetchall()
        job_ids = [int(row["id"] or 0) for row in rows]
        actions_by_job: Dict[int, List[Dict[str, Any]]] = {jid: [] for jid in job_ids}
        if job_ids:
            placeholders = ",".join("?" for _ in job_ids)
            cursor.execute(
                f"SELECT * FROM scraper_job_actions WHERE job_id IN ({placeholders}) ORDER BY action_index ASC",
                job_ids,
            )
            for action_row in cursor.fetchall():
                action = _serialize_scraper_action_row(action_row)
                jid = int(action.get("job_id", 0) or 0)
                actions_by_job.setdefault(jid, []).append(action)
        jobs: List[Dict[str, Any]] = []
        for row in rows:
            row_id = int(row["id"] or 0)
            jobs.append(_serialize_scraper_job_row(row, actions_by_job.get(row_id, [])))
        cursor.execute("SELECT status, COUNT(1) AS count FROM scraper_jobs GROUP BY status")
        status_counts = {str(row["status"] or ""): int(row["count"] or 0) for row in cursor.fetchall()}
    counts = {
        "total": sum(status_counts.values()),
        "active": sum(status_counts.get(status, 0) for status in ("pending", "running", "rollback_running")),
        "completed": int(status_counts.get("completed", 0) or 0),
        "failed": sum(status_counts.get(status, 0) for status in ("failed", "partial", "rollback_failed")),
        "rollback": int(status_counts.get("rolled_back", 0) or 0),
    }
    return {
        "ok": True,
        "jobs": jobs,
        "active_jobs": [item for item in jobs if str(item.get("status", "") or "") in SCRAPER_JOB_ACTIVE_STATUSES],
        "job_counts": counts,
    }


def clear_scraper_jobs(scope: str = "completed") -> Dict[str, int]:
    normalized_scope = normalize_scraper_job_clear_scope(scope)
    if normalized_scope == "failed":
        target_statuses = ["failed", "partial", "rollback_failed"]
    elif normalized_scope == "rollback":
        target_statuses = ["rolled_back"]
    else:
        target_statuses = ["completed"]

    ensure_db()
    with db_connection() as conn:
        cursor = conn.cursor()
        placeholders = ",".join(["?"] * len(target_statuses))
        cursor.execute(
            f"SELECT COUNT(1) FROM scraper_job_actions WHERE job_id IN (SELECT id FROM scraper_jobs WHERE status IN ({placeholders}))",
            tuple(target_statuses),
        )
        action_row = cursor.fetchone()
        deleted_actions = int(action_row[0] if action_row else 0)
        cursor.execute(
            f"DELETE FROM scraper_job_actions WHERE job_id IN (SELECT id FROM scraper_jobs WHERE status IN ({placeholders}))",
            tuple(target_statuses),
        )
        cursor.execute(
            f"DELETE FROM scraper_jobs WHERE status IN ({placeholders})",
            tuple(target_statuses),
        )
        deleted_jobs = int(cursor.rowcount or 0)

        cursor.execute("SELECT COUNT(1) FROM scraper_jobs")
        remaining_jobs_row = cursor.fetchone()
        remaining_jobs = int(remaining_jobs_row[0] if remaining_jobs_row else 0)
        if remaining_jobs == 0:
            cursor.execute("DELETE FROM sqlite_sequence WHERE name = 'scraper_jobs'")
        cursor.execute("SELECT COUNT(1) FROM scraper_job_actions")
        remaining_actions_row = cursor.fetchone()
        remaining_actions = int(remaining_actions_row[0] if remaining_actions_row else 0)
        if remaining_actions == 0:
            cursor.execute("DELETE FROM sqlite_sequence WHERE name = 'scraper_job_actions'")

        conn.commit()
    return {
        "scope": normalized_scope,
        "deleted": deleted_jobs,
        "deleted_actions": deleted_actions,
    }


def _load_scraper_job(job_id: int) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    ensure_db()
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM scraper_jobs WHERE id = ?", (int(job_id),))
        job = sqlite_row_to_dict(cursor.fetchone())
        if not job:
            raise RuntimeError("刮削任务不存在")
        cursor.execute("SELECT * FROM scraper_job_actions WHERE job_id = ? ORDER BY action_index ASC", (int(job_id),))
        actions = [sqlite_row_to_dict(row) for row in cursor.fetchall()]
    plan = safe_json_loads(job.get("plan_json", "{}"), {})
    plan_actions = plan.get("actions", []) if isinstance(plan, dict) else []
    plan_by_index = {
        max(0, int((item or {}).get("action_index", 0) or 0)): item
        for item in plan_actions
        if isinstance(item, dict)
    }
    merged_actions: List[Dict[str, Any]] = []
    for action in actions:
        merged = dict(action)
        plan_action = plan_by_index.get(max(0, int(action.get("action_index", 0) or 0)))
        if isinstance(plan_action, dict):
            for key, value in plan_action.items():
                if key not in merged or not merged.get(key) and value not in (None, ""):
                    merged[key] = value
        merged_actions.append(merged)
    return job, merged_actions


def _scraper_job_base_path(job: Dict[str, Any], plan: Dict[str, Any]) -> str:
    options = safe_json_loads(job.get("options_json", "{}"), {})
    if not isinstance(options, dict):
        options = {}
    return normalize_relative_path(
        str(plan.get("base_path", "") or options.get("base_path", "") or "")
    )


def _normalize_scraper_job_action_paths(action: Dict[str, Any], base_path: str) -> Dict[str, Any]:
    normalized = dict(action or {})
    normalized["old_path"] = _canonical_scraper_mount_path(
        str(normalized.get("old_path", "") or ""),
        base_path,
    )
    normalized["new_path"] = _canonical_scraper_mount_path(
        str(normalized.get("new_path", "") or ""),
        base_path,
    )
    return normalized


def _apply_scraper_path_rewrites(path: str, rewrites: List[Tuple[str, str]]) -> str:
    current = normalize_relative_path(str(path or ""))
    for raw_old_root, raw_new_root in rewrites:
        old_root = normalize_relative_path(str(raw_old_root or ""))
        new_root = normalize_relative_path(str(raw_new_root or ""))
        if not current or not old_root or not new_root:
            continue
        if current == old_root:
            current = new_root
        elif current.startswith(f"{old_root}/"):
            current = join_relative_path(new_root, current[len(old_root) + 1 :])
    return current


def _rebase_scraper_job_action_paths(
    action: Dict[str, Any],
    rewrites: List[Tuple[str, str]],
) -> Dict[str, Any]:
    rebased = dict(action or {})
    rebased["old_path"] = _apply_scraper_path_rewrites(
        str(rebased.get("old_path", "") or ""),
        rewrites,
    )
    rebased["new_path"] = _apply_scraper_path_rewrites(
        str(rebased.get("new_path", "") or ""),
        rewrites,
    )
    return rebased


def _build_scraper_forward_action_paths(
    actions: List[Dict[str, Any]],
) -> Tuple[Dict[str, Dict[str, Any]], List[Tuple[str, str]]]:
    effective_by_id: Dict[str, Dict[str, Any]] = {}
    rewrites: List[Tuple[str, str]] = []
    ordered_actions = sorted(
        (item for item in actions if isinstance(item, dict)),
        key=lambda item: max(0, parse_int(item.get("action_index", 0), 0)),
    )
    for action in ordered_actions:
        effective = _rebase_scraper_job_action_paths(action, rewrites)
        action_id = str(action.get("id", "") or "").strip()
        if action_id:
            effective_by_id[action_id] = effective
        if (
            bool(action.get("is_dir"))
            and str(action.get("status", "") or "").strip() == "completed"
            and effective.get("old_path")
            and effective.get("new_path")
            and effective.get("old_path") != effective.get("new_path")
        ):
            rewrites.append(
                (
                    str(effective.get("old_path", "") or ""),
                    str(effective.get("new_path", "") or ""),
                )
            )
    return effective_by_id, rewrites


def _remove_scraper_path_rewrite(
    rewrites: List[Tuple[str, str]],
    target: Tuple[str, str],
) -> List[Tuple[str, str]]:
    removed = False
    remaining: List[Tuple[str, str]] = []
    for rewrite in rewrites:
        if not removed and rewrite == target:
            removed = True
            continue
        remaining.append(rewrite)
    return remaining


def _scraper_job_action_monitor_operation(action: Dict[str, Any], *, reverse: bool = False) -> str:
    old_parent_id = str(
        action.get("new_parent_id" if reverse else "old_parent_id", "") or ""
    ).strip()
    new_parent_id = str(
        action.get("old_parent_id" if reverse else "new_parent_id", "") or ""
    ).strip()
    return "rename" if old_parent_id and old_parent_id == new_parent_id else "move"


def _update_scraper_job(job_id: int, _conn: Optional[Any] = None, **fields: Any) -> None:
    if not fields:
        return
    ensure_db()
    allowed = {
        "status",
        "status_detail",
        "succeeded_actions",
        "failed_actions",
        "rollback_succeeded_actions",
        "rollback_failed_actions",
        "started_at",
        "finished_at",
    }
    payload = {key: value for key, value in fields.items() if key in allowed}
    if not payload:
        return
    payload["updated_at"] = now_text()
    sets = ", ".join(f"{key} = ?" for key in payload.keys())
    values = list(payload.values()) + [int(job_id)]
    if _conn is not None:
        _conn.execute(f"UPDATE scraper_jobs SET {sets} WHERE id = ?", values)
    else:
        with db_connection() as conn:
            conn.execute(f"UPDATE scraper_jobs SET {sets} WHERE id = ?", values)
            conn.commit()


def _update_scraper_action(action_id: int, _conn: Optional[Any] = None, **fields: Any) -> None:
    if not fields:
        return
    allowed = {"new_parent_id", "status", "status_detail", "rollback_status", "rollback_detail", "response_json"}
    payload = {key: value for key, value in fields.items() if key in allowed}
    if not payload:
        return
    payload["updated_at"] = now_text()
    sets = ", ".join(f"{key} = ?" for key in payload.keys())
    values = list(payload.values()) + [int(action_id)]
    if _conn is not None:
        _conn.execute(f"UPDATE scraper_job_actions SET {sets} WHERE id = ?", values)
    else:
        with db_connection() as conn:
            conn.execute(f"UPDATE scraper_job_actions SET {sets} WHERE id = ?", values)
            conn.commit()


def _build_temp_name(action_id: int, entry_id: str, original_name: str) -> str:
    _, ext = os.path.splitext(str(original_name or ""))
    token = re.sub(r"[^A-Za-z0-9]+", "", str(entry_id or ""))[:12] or str(action_id)
    return f".mediahub-tmp-{int(action_id)}-{token}{ext}"


def _execute_move_rename(
    provider: str,
    cookie: str,
    action: Dict[str, Any],
    target_parent_id: str,
    *,
    reverse: bool = False,
) -> Dict[str, Any]:
    entry_id = str(action.get("entry_id", "") or "").strip()
    if not entry_id:
        raise RuntimeError("文件 ID 不能为空")
    if reverse:
        source_parent = str(action.get("new_parent_id", "") or "").strip() or "0"
        source_name = str(action.get("new_name", "") or "")
        target_parent = str(action.get("old_parent_id", "") or "0").strip() or "0"
        target_name = str(action.get("old_name", "") or "")
    else:
        source_parent = str(action.get("old_parent_id", "") or "0").strip() or "0"
        source_name = str(action.get("old_name", "") or "")
        target_parent = target_parent_id
        target_name = str(action.get("new_name", "") or "")
    if not target_name:
        raise RuntimeError("目标文件名为空")
    need_move = source_parent != target_parent
    need_rename = source_name != target_name
    responses: List[Dict[str, Any]] = []
    if not need_move and not need_rename:
        return {"skipped": True, "detail": "文件名和目录未变化"}
    if _target_name_exists(provider, cookie, target_parent, target_name, same_entry_id=entry_id):
        raise RuntimeError("目标目录中已有同名文件")
    if need_move and need_rename:
        temp_name = _build_temp_name(int(action.get("id", 0) or 0), entry_id, source_name)
        responses.append(_rename_provider_entry(provider, cookie, entry_id, temp_name, source_parent))
        responses.append(_move_provider_entries(provider, cookie, [entry_id], target_parent, source_parent))
        responses.append(_rename_provider_entry(provider, cookie, entry_id, target_name, target_parent))
    elif need_rename:
        responses.append(_rename_provider_entry(provider, cookie, entry_id, target_name, source_parent))
    elif need_move:
        responses.append(_move_provider_entries(provider, cookie, [entry_id], target_parent, source_parent))
    _invalidate_provider_parent(provider, source_parent)
    _invalidate_provider_parent(provider, target_parent)
    return {"skipped": False, "responses": responses, "target_parent_id": target_parent}


def _prepare_scraper_job_action_monitor_sync(
    provider: str,
    job_id: int,
    action: Dict[str, Any],
    *,
    reverse: bool = False,
    base_path: str = "",
) -> Dict[str, Any]:
    action = _normalize_scraper_job_action_paths(action, base_path)
    is_delete = bool(action.get("delete"))
    if is_delete:
        old_path = normalize_relative_path(str(action.get("old_path", "") or ""))
        new_path = ""
        old_parent_id = str(action.get("old_parent_id", "") or "").strip()
        new_parent_id = old_parent_id
    else:
        old_path = normalize_relative_path(str(action.get("new_path" if reverse else "old_path", "") or ""))
        new_path = normalize_relative_path(str(action.get("old_path" if reverse else "new_path", "") or ""))
        old_parent_id = str(action.get("new_parent_id" if reverse else "old_parent_id", "") or "").strip()
        new_parent_id = str(action.get("old_parent_id" if reverse else "new_parent_id", "") or "").strip()
    is_dir = bool(action.get("is_dir"))
    entry_id = str(action.get("entry_id", "") or "").strip()
    direction = "rollback" if reverse else "forward"
    event_entries = [] if not old_path or (not is_delete and (not new_path or old_path == new_path)) else [
        {
            "id": entry_id,
            "name": str(action.get("new_name" if reverse else "old_name", "") or ""),
            "old_path": old_path,
            "new_path": new_path,
            "old_parent_id": old_parent_id,
            "new_parent_id": new_parent_id,
            "old_cid": entry_id if is_dir else "",
            "new_cid": entry_id if is_dir else "",
            "is_dir": is_dir,
            "size": max(0, parse_int(action.get("file_size", 0), 0)),
            "modified_at": str(action.get("remote_modified", "") or ""),
        }
    ]
    return _prepare_scraper_monitor_sync(
        provider,
        "delete" if is_delete else _scraper_job_action_monitor_operation(action, reverse=reverse),
        event_entries,
        source_action=f"scraper-job:{int(job_id)}:{direction}",
        dedupe_key=(
            f"scraper-job:{int(job_id)}:action:{int(action.get('id', 0) or 0)}:{direction}"
        ),
    )


def run_scraper_job(job_id: int) -> None:
    try:
        job, actions = _load_scraper_job(job_id)
        provider = normalize_scraper_provider(job.get("provider", "115")) or "115"
        _require_scraper_operation(provider, "scrape", "执行")
        cookie = _require_provider_cookie(provider)
        plan = safe_json_loads(job.get("plan_json", "{}"), {})
        base_cid = str(plan.get("base_cid", "0") or "0").strip() or "0"
        base_path = _scraper_job_base_path(job, plan)
        actions = [_normalize_scraper_job_action_paths(action, base_path) for action in actions]
    except Exception as exc:
        _update_scraper_job(job_id, status="failed", status_detail=str(exc), failed_actions=1, finished_at=now_text())
        return
    ensure_db()
    with db_connection() as conn:
        _update_scraper_job(job_id, _conn=conn, status="running", status_detail="正在执行刮削改名", started_at=now_text(), finished_at="")
        conn.commit()
        succeeded = 0
        failed = 0
        path_rewrites: List[Tuple[str, str]] = []
        for action in actions:
            action_id = int(action.get("id", 0) or 0)
            _update_scraper_action(action_id, _conn=conn, status="running", status_detail="正在处理")
            conn.commit()
            prepared_sync: Optional[Dict[str, Any]] = None
            try:
                if bool(action.get("delete")):
                    entry_id = str(action.get("entry_id", "") or "").strip()
                    old_parent_id = str(action.get("old_parent_id", "") or "0").strip() or "0"
                    event_action = _rebase_scraper_job_action_paths(action, path_rewrites)
                    prepared_sync = _prepare_scraper_job_action_monitor_sync(
                        provider,
                        job_id,
                        event_action,
                        base_path=base_path,
                    )
                    result = _delete_provider_entries(provider, cookie, [entry_id], old_parent_id)
                    _invalidate_provider_parent(provider, old_parent_id)
                    result["monitor_sync"] = _finish_scraper_monitor_sync(prepared_sync, succeeded=True)
                    _update_scraper_action(
                        action_id,
                        _conn=conn,
                        status="completed",
                        status_detail="广告文件已删除",
                        response_json=safe_json_dumps(result),
                    )
                    succeeded += 1
                    _update_scraper_job(
                        job_id,
                        _conn=conn,
                        status_detail=f"正在执行刮削整理：成功 {succeeded}，失败 {failed}",
                        succeeded_actions=succeeded,
                        failed_actions=failed,
                    )
                    conn.commit()
                    continue
                old_path_norm = normalize_relative_path(str(action.get("old_path", "") or ""))
                new_path_norm = normalize_relative_path(str(action.get("new_path", "") or ""))
                if old_path_norm and new_path_norm and old_path_norm == new_path_norm:
                    # 文件名与路径均未变化：直接跳过，不做任何远程调用，避免限速等待。
                    _update_scraper_action(
                        action_id,
                        _conn=conn,
                        status="skipped",
                        status_detail="文件名与路径未变化",
                    )
                    succeeded += 1
                    _update_scraper_job(
                        job_id,
                        _conn=conn,
                        status_detail=f"正在执行刮削整理：成功 {succeeded}，失败 {failed}",
                        succeeded_actions=succeeded,
                        failed_actions=failed,
                    )
                    conn.commit()
                    continue
                target_parent_path = str(action.get("target_parent_path", "") or "")
                target_parent_id = str(action.get("new_parent_id", "") or "").strip()
                if not target_parent_id:
                    target_parent_id = _ensure_folder_from_base(provider, cookie, base_cid, target_parent_path)
                    _update_scraper_action(action_id, _conn=conn, new_parent_id=target_parent_id)
                    action["new_parent_id"] = target_parent_id
                    conn.commit()
                event_action = _rebase_scraper_job_action_paths(action, path_rewrites)
                prepared_sync = _prepare_scraper_job_action_monitor_sync(
                    provider,
                    job_id,
                    event_action,
                    base_path=base_path,
                )
                result = _execute_move_rename(provider, cookie, action, target_parent_id)
                if bool(action.get("is_dir")) and not result.get("skipped"):
                    path_rewrites.append(
                        (
                            str(event_action.get("old_path", "") or ""),
                            str(event_action.get("new_path", "") or ""),
                        )
                    )
                result["monitor_sync"] = _finish_scraper_monitor_sync(prepared_sync, succeeded=True)
                action_status = "skipped" if result.get("skipped") else "completed"
                detail = str(result.get("detail") or "已完成")
                _update_scraper_action(action_id, _conn=conn, status=action_status, status_detail=detail, response_json=safe_json_dumps(result))
                succeeded += 1
                _update_scraper_job(
                    job_id,
                    _conn=conn,
                    status_detail=f"正在执行刮削改名：成功 {succeeded}，失败 {failed}",
                    succeeded_actions=succeeded,
                    failed_actions=failed,
                )
            except Exception as exc:
                if prepared_sync:
                    _finish_scraper_monitor_sync(prepared_sync, succeeded=False, error=str(exc))
                failed += 1
                _update_scraper_action(action_id, _conn=conn, status="failed", status_detail=str(exc))
                _update_scraper_job(
                    job_id,
                    _conn=conn,
                    status_detail=f"正在执行刮削改名：成功 {succeeded}，失败 {failed}",
                    succeeded_actions=succeeded,
                    failed_actions=failed,
                )
            conn.commit()
        if failed > 0 and succeeded > 0:
            status = "partial"
            detail = f"部分完成：成功 {succeeded}，失败 {failed}"
        elif failed > 0:
            status = "failed"
            detail = f"执行失败：失败 {failed}"
        else:
            status = "completed"
            detail = f"执行完成：{succeeded} 项"
        _update_scraper_job(
            job_id,
            _conn=conn,
            status=status,
            status_detail=detail,
            succeeded_actions=succeeded,
            failed_actions=failed,
            finished_at=now_text(),
        )
        conn.commit()


def rollback_scraper_job(job_id: int) -> None:
    try:
        job, actions = _load_scraper_job(job_id)
        provider = normalize_scraper_provider(job.get("provider", "115")) or "115"
        _require_scraper_operation(provider, "rollback", "回退")
        cookie = _require_provider_cookie(provider)
        plan = safe_json_loads(job.get("plan_json", "{}"), {})
        base_path = _scraper_job_base_path(job, plan)
        actions = [_normalize_scraper_job_action_paths(action, base_path) for action in actions]
    except Exception as exc:
        _update_scraper_job(job_id, status="rollback_failed", status_detail=str(exc), rollback_failed_actions=1, finished_at=now_text())
        return
    successful_actions = [item for item in actions if str(item.get("status", "") or "") in {"completed", "skipped"}]
    forward_action_paths, active_path_rewrites = _build_scraper_forward_action_paths(successful_actions)
    ensure_db()
    with db_connection() as conn:
        _update_scraper_job(job_id, _conn=conn, status="rollback_running", status_detail="正在回退刮削任务", finished_at="")
        conn.commit()


# ---------------------------------------------------------------------------
        succeeded = 0
        failed = 0
        for action in reversed(successful_actions):
            action_id = int(action.get("id", 0) or 0)
            prepared_sync: Optional[Dict[str, Any]] = None
            try:
                if str(action.get("status", "") or "") == "skipped" or bool(action.get("delete")):
                    rollback_status = "skipped"
                    rollback_detail = "广告删除不回退（可在网盘回收站手动恢复）" if bool(action.get("delete")) else "原动作未产生变化"
                    _update_scraper_action(
                        action_id,
                        _conn=conn,
                        rollback_status=rollback_status,
                        rollback_detail=rollback_detail,
                    )
                    succeeded += 1
                    _update_scraper_job(
                        job_id,
                        _conn=conn,
                        status_detail=f"正在回退刮削任务：成功 {succeeded}，失败 {failed}",
                        rollback_succeeded_actions=succeeded,
                        rollback_failed_actions=failed,
                    )
                    conn.commit()
                    continue
                forward_action = forward_action_paths.get(str(action_id), action)
                own_rewrite = (
                    str(forward_action.get("old_path", "") or ""),
                    str(forward_action.get("new_path", "") or ""),
                )
                target_rewrites = active_path_rewrites
                if bool(action.get("is_dir")):
                    target_rewrites = _remove_scraper_path_rewrite(active_path_rewrites, own_rewrite)
                rollback_event_action = dict(action)
                rollback_event_action["old_path"] = _apply_scraper_path_rewrites(
                    str(forward_action.get("old_path", "") or ""),
                    target_rewrites,
                )
                rollback_event_action["new_path"] = _apply_scraper_path_rewrites(
                    str(forward_action.get("new_path", "") or ""),
                    active_path_rewrites,
                )
                prepared_sync = _prepare_scraper_job_action_monitor_sync(
                    provider,
                    job_id,
                    rollback_event_action,
                    reverse=True,
                    base_path=base_path,
                )
                result = _execute_move_rename(
                    provider,
                    cookie,
                    action,
                    str(action.get("old_parent_id", "") or "0"),
                    reverse=True,
                )
                if bool(action.get("is_dir")) and not result.get("skipped"):
                    active_path_rewrites = _remove_scraper_path_rewrite(
                        active_path_rewrites,
                        own_rewrite,
                    )
                result["monitor_sync"] = _finish_scraper_monitor_sync(prepared_sync, succeeded=True)
                _update_scraper_action(action_id, _conn=conn, rollback_status="completed", rollback_detail="已回退", response_json=safe_json_dumps(result))
                succeeded += 1
                _update_scraper_job(
                    job_id,
                    _conn=conn,
                    status_detail=f"正在回退刮削任务：成功 {succeeded}，失败 {failed}",
                    rollback_succeeded_actions=succeeded,
                    rollback_failed_actions=failed,
                )
            except Exception as exc:
                if prepared_sync:
                    _finish_scraper_monitor_sync(prepared_sync, succeeded=False, error=str(exc))
                failed += 1
                _update_scraper_action(action_id, _conn=conn, rollback_status="failed", rollback_detail=str(exc))
                _update_scraper_job(
                    job_id,
                    _conn=conn,
                    status_detail=f"正在回退刮削任务：成功 {succeeded}，失败 {failed}",
                    rollback_succeeded_actions=succeeded,
                    rollback_failed_actions=failed,
                )
            conn.commit()
        status = "rolled_back" if failed <= 0 else "rollback_failed"
        detail = f"回退完成：成功 {succeeded}" if failed <= 0 else f"回退部分失败：成功 {succeeded}，失败 {failed}"
        _update_scraper_job(
            job_id,
            _conn=conn,
            status=status,
            status_detail=detail,
            rollback_succeeded_actions=succeeded,
            rollback_failed_actions=failed,
            finished_at=now_text(),
        )
        conn.commit()
# 批量整理：扫描分组、自动识别、批量计划
# ---------------------------------------------------------------------------

SCRAPER_BATCH_MAX_ITEMS = 200
SCRAPER_LIBRARY_SPLIT_MAX_DEPTH = 4
SCRAPER_LIBRARY_CONTAINER_KEYS = {
    "电影", "电视剧", "剧集", "动漫", "动画", "番剧", "新番", "综艺", "纪录片", "紀錄片", "纪录", "紀錄",
    "影视", "资源", "資源", "视频", "視頻", "电影库", "影视库", "电视剧库", "剧集库", "动漫库", "动画库",
    "资源库", "合集", "合輯", "系列", "美剧", "英剧", "日剧", "韩剧", "国产剧", "港剧", "台剧",
    "欧美", "日韩", "国产", "港台", "华语",
}
SCRAPER_BATCH_MEDIA_EXTENSIONS = {
    ".mkv", ".mp4", ".avi", ".ts", ".m2ts", ".wmv", ".mov", ".flv", ".webm",
    ".rmvb", ".rm", ".mpg", ".mpeg", ".vob", ".iso", ".m4v", ".3gp", ".m2v",
    ".mts", ".tp", ".divx", ".asf", ".ogm",
}
SCRAPER_BATCH_SUBTITLE_EXTENSIONS = {".srt", ".ass", ".ssa", ".sub", ".vtt", ".idx", ".smi", ".sup"}
SCRAPER_BATCH_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
SCRAPER_BATCH_AD_EXTENSIONS = {".txt", ".url", ".html", ".htm", ".nfo", ".lnk", ".torrent", ".torrent!"}
SCRAPER_STANDARD_IMAGE_STEMS = {
    "poster", "folder", "cover", "backdrop", "fanart", "banner", "clearart",
    "logo", "landscape", "thumb",
}
SCRAPER_AD_IMAGE_MARKERS = (
    "official site", "visit", "logo", "banner", "广告", "水印", "推广", "推荐",
    "watch now", "download now",
)
SCRAPER_SUBTITLE_LANGUAGE_MAP = {
    "dan": "dan", "danish": "dan", "da": "dan",
    "eng": "eng", "en": "eng", "english": "eng",
    "zh": "zh", "zho": "zh", "chi": "zh", "中文": "zh", "国语": "zh",
    "zh-hans": "zh-Hans", "zh-cn": "zh-Hans", "zh-sg": "zh-Hans",
    "chs": "zh-Hans", "sc": "zh-Hans", "简体": "zh-Hans", "简体中文": "zh-Hans",
    "zh-hant": "zh-Hant", "zh-tw": "zh-Hant", "zh-hk": "zh-Hant",
    "cht": "zh-Hant", "tc": "zh-Hant", "big5": "zh-Hant", "繁体": "zh-Hant",
    "繁體": "zh-Hant", "繁体中文": "zh-Hant", "繁體中文": "zh-Hant",
    "jpn": "jpn", "ja": "jpn", "jap": "jpn", "日语": "jpn",
    "kor": "kor", "ko": "kor", "韩语": "kor",
    "fre": "fre", "fr": "fre", "fra": "fre", "法语": "fre",
    "ger": "ger", "de": "ger", "deu": "ger", "德语": "ger",
    "spa": "spa", "es": "spa", "西班牙语": "spa",
    "ita": "ita", "it": "ita", "意大利语": "ita",
    "rus": "rus", "ru": "rus", "俄语": "rus",
    "por": "por", "pt": "por", "葡萄牙语": "por",
    "nld": "nld", "nl": "nld", "dut": "nld", "荷兰语": "nld",
    "swe": "swe", "sv": "swe", "瑞典语": "swe",
    "nor": "nor", "no": "nor", "挪威语": "nor",
    "fin": "fin", "fi": "fin", "芬兰语": "fin",
    "pol": "pol", "pl": "pol", "波兰语": "pol",
    "tur": "tur", "tr": "tur", "土耳其语": "tur",
    "tha": "tha", "th": "tha", "泰语": "tha",
    "vie": "vie", "vi": "vie", "越南语": "vie",
    "ara": "ara", "ar": "ara", "阿拉伯语": "ara",
    "heb": "heb", "he": "heb", "希伯来语": "heb",
    "gre": "gre", "el": "gre", "希腊语": "gre",
    "ces": "ces", "cs": "ces", "捷克语": "ces",
    "hun": "hun", "hu": "hun", "匈牙利语": "hun",
    "ukr": "ukr", "uk": "ukr", "乌克兰语": "ukr",
    "srp": "srp", "sr": "srp", "塞尔维亚语": "srp",
    "hrv": "hrv", "hr": "hrv", "克罗地亚语": "hrv",
    "ron": "ron", "ro": "ron", "罗马尼亚语": "ron",
    "bul": "bul", "bg": "bul", "保加利亚语": "bul",
    "slk": "slk", "sk": "slk", "斯洛伐克语": "slk",
    "cat": "cat", "ca": "cat", "加泰罗尼亚语": "cat",
    "epo": "epo", "eo": "epo", "世界语": "epo",
    "lat": "lat", "la": "lat", "拉丁语": "lat",
    "forced": "forced", "sdh": "sdh", "hi": "hi", "cc": "cc", "default": "default",
    "utf8": "utf8", "utf-8": "utf8", "gb": "gb", "gbk": "gbk", "shift-jis": "sjis",
}
_SCRAPER_SUBTITLE_MARKER_VALUES = {"forced", "sdh", "hi", "cc", "default", "utf8", "gb", "gbk", "sjis"}


def _scraper_file_category(name: str) -> str:
    """按扩展名分类：video / subtitle / image / ad / other。"""
    ext = os.path.splitext(str(name or "").strip())[1].lower()
    if not ext:
        return "other"
    if ext in SCRAPER_BATCH_MEDIA_EXTENSIONS:
        return "video"
    if ext in SCRAPER_BATCH_SUBTITLE_EXTENSIONS:
        return "subtitle"
    if ext in SCRAPER_BATCH_IMAGE_EXTENSIONS:
        return "image"
    if ext in SCRAPER_BATCH_AD_EXTENSIONS:
        return "ad"
    return "other"


def _scraper_subtitle_suffix(name: str) -> str:
    """从字幕文件名尾部提取语言/编码/特殊标记，如 Denmark.dan.srt → '.dan'。"""
    stem = os.path.splitext(str(name or "").strip())[0]
    tokens = [token for token in re.split(r"[._\s]+", stem) if token]
    suffix_parts: List[str] = []
    language_taken = False
    for token in reversed(tokens):
        canonical = SCRAPER_SUBTITLE_LANGUAGE_MAP.get(token.lower())
        if canonical is None:
            break
        if canonical not in _SCRAPER_SUBTITLE_MARKER_VALUES:
            if language_taken:
                break
            language_taken = True
        suffix_parts.append(canonical)
        if len(suffix_parts) >= 3:
            break
    suffix_parts.reverse()
    return f".{'.'.join(suffix_parts)}" if suffix_parts else ""


def _is_scraper_ad_image(name: str, size: int = 0) -> bool:
    """判断图片是否像站点广告图（Official site / logo / 网站域名水印等）。"""
    text = str(name or "").lower()
    if any(marker in text for marker in SCRAPER_AD_IMAGE_MARKERS):
        return True
    if re.search(r"www\s*[.\s]", text):
        return True
    if re.search(r"(?:^|[\s._-])(?:[a-z0-9][a-z0-9.-]*\.)+[a-z]{2,6}\b", text):
        if size and 0 < int(size or 0) < 60 * 1024:
            return True
        if re.search(r"(?:official|site|visit|watch|download|tor)", text):
            return True
    return False


def _is_scraper_ad_file(name: str, size: int = 0) -> bool:
    """判断是否广告类文件：广告扩展名（txt/url/html/nfo 等）或广告图片。"""
    category = _scraper_file_category(name)
    if category == "ad":
        return True
    if category == "image":
        return _is_scraper_ad_image(name, size)
    return False


def _is_scraper_standard_image(name: str) -> bool:
    stem = os.path.splitext(str(name or "").strip())[0].strip().lower()
    return stem in SCRAPER_STANDARD_IMAGE_STEMS


def _is_scraper_media_file(name: str) -> bool:
    ext = os.path.splitext(str(name or "").strip())[1].lower()
    if not ext or _is_scraper_excluded_archive(name):
        return False
    return ext in SCRAPER_BATCH_MEDIA_EXTENSIONS


def _is_scraper_library_container_folder(name: str) -> bool:
    """判断文件夹名是否为通用库分类容器（电影/电视剧/动漫等），用于库根拆分时递归下探。"""
    key = _normalize_scraper_keyword_compact(name)
    if not key:
        return False
    if key in SCRAPER_LIBRARY_CONTAINER_KEYS:
        return True
    return _is_scraper_generic_keyword(name)


def _group_scraper_loose_tv_files(
    entries: List[Dict[str, Any]],
) -> Tuple[List[List[Dict[str, Any]]], List[Dict[str, Any]]]:
    """把散落的同一剧集单集文件合并成一个识别条目；电影/独立文件保持单条目。

    仅当同目录内 ≥2 个文件提取出相同标题且带集数特征时才合并，
    预览/计划阶段仍按文件逐个生成动作，显示与原来一致。
    """
    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    singles: List[Dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "") or "")
        if not _is_scraper_media_file(name):
            continue
        candidates = _extract_scraper_title_candidates(name)
        title_key = _scraper_keyword_key(candidates[0]) if candidates else ""
        if title_key and _looks_like_tv([name]):
            parent_key = normalize_relative_path(str(entry.get("parent_path", "") or ""))
            groups.setdefault((parent_key, title_key), []).append(entry)
        else:
            singles.append(entry)
    merged_groups = [group for group in groups.values() if len(group) >= 2]
    for group in groups.values():
        if len(group) < 2:
            singles.extend(group)
    return merged_groups, singles


def _folder_has_any_media(
    provider: str,
    cookie: str,
    dir_entry: Dict[str, Any],
    *,
    depth: int = 0,
    max_depth: int = 3,
) -> bool:
    """轻量判断目录子树是否包含媒体文件（命中即返回，避免全量收集）。"""
    if depth > max_depth:
        return False
    dir_id = str(dir_entry.get("id") or dir_entry.get("cid") or "0")
    dir_path = normalize_relative_path(str(dir_entry.get("path", "") or dir_entry.get("name", "") or ""))
    try:
        payload = _list_provider_entries_payload(provider, cookie, dir_id, folders_only=False)
    except Exception:
        return False
    for raw in (payload.get("entries", []) if isinstance(payload, dict) else []):
        child = _compact_scraper_entry(raw, dir_id, dir_path)
        if not child:
            continue
        if child.get("is_dir"):
            if _folder_has_any_media(provider, cookie, child, depth=depth + 1, max_depth=max_depth):
                return True
        elif _is_scraper_media_file(str(child.get("name", "") or "")):
            return True
    return False


def _looks_like_scraper_library_root(provider: str, cookie: str, dir_entry: Dict[str, Any]) -> bool:
    """自动判断选中的文件夹是否像“媒体库根目录”，决定是否按子目录拆分识别。"""
    if _is_scraper_library_container_folder(str(dir_entry.get("name", "") or "")):
        return True
    dir_id = str(dir_entry.get("id") or dir_entry.get("cid") or "0")
    dir_path = normalize_relative_path(str(dir_entry.get("path", "") or dir_entry.get("name", "") or ""))
    try:
        payload = _list_provider_entries_payload(provider, cookie, dir_id, folders_only=False)
    except Exception:
        return False
    subfolders: List[Dict[str, Any]] = []
    has_direct_media = False
    for raw in (payload.get("entries", []) if isinstance(payload, dict) else []):
        child = _compact_scraper_entry(raw, dir_id, dir_path)
        if not child:
            continue
        if child.get("is_dir"):
            subfolders.append(child)
        elif _is_scraper_media_file(str(child.get("name", "") or "")):
            has_direct_media = True
    if not subfolders:
        return False
    if any(_is_scraper_library_container_folder(str(item.get("name", "") or "")) for item in subfolders):
        return True
    if has_direct_media:
        # 直接含媒体文件 → 更像单个作品文件夹（文件 + 花絮/Season 子目录）。
        return False
    media_subfolders = [item for item in subfolders if _folder_has_any_media(provider, cookie, item)]
    if not media_subfolders:
        return False
    if all(_extract_subscription_season_from_name(str(item.get("name", "") or "")) > 0 for item in media_subfolders):
        # 全部是 Season/Sxx/第x季 → 单个多季剧集文件夹。
        return False
    return len(media_subfolders) >= 2


def _split_scraper_library_item_sources(
    provider: str,
    cookie: str,
    dir_entry: Dict[str, Any],
    issues: List[str],
    *,
    depth: int = 0,
    max_depth: int = SCRAPER_LIBRARY_SPLIT_MAX_DEPTH,
) -> List[Dict[str, Any]]:
    """把库文件夹按子目录拆成识别条目；分层失败或没有媒体的文件夹跳过不处理。

    规则：直接含媒体的子文件夹=一个条目；散落媒体文件=单条目；
    通用分类容器文件夹（电影/电视剧/动漫等）递归下探；
    其他只有子文件夹、没有直接媒体的文件夹按作品条目处理（含 Season 子目录）；
    拆不出条目的容器或空文件夹跳过并提示。
    """
    entry_name = str(dir_entry.get("name", "") or "")
    if depth > max_depth:
        issues.append(f"文件夹 {entry_name or '--'} 嵌套过深，已跳过")
        return []
    dir_id = str(dir_entry.get("id") or dir_entry.get("cid") or "0")
    dir_path = normalize_relative_path(str(dir_entry.get("path", "") or dir_entry.get("name", "") or ""))
    try:
        payload = _list_provider_entries_payload(provider, cookie, dir_id, folders_only=False)
    except Exception as exc:
        issues.append(f"读取目录 {entry_name or dir_id} 失败：{exc}")
        return []
    children = [
        child
        for raw in (payload.get("entries", []) if isinstance(payload, dict) else [])
        for child in [_compact_scraper_entry(raw, dir_id, dir_path)]
        if child
    ]
    items: List[Dict[str, Any]] = []
    for child in children:
        if not child.get("is_dir"):
            if not _is_scraper_media_file(str(child.get("name", "") or "")):
                continue
            items.append(
                {
                    "entry": child,
                    "name": str(child.get("name", "") or ""),
                    "path": _scraper_entry_path(child),
                    "parent_path": str(child.get("parent_path", "") or ""),
                    "parent_id": str(child.get("parent_id", "") or ""),
                    "is_dir": False,
                    "files": [child],
                    "no_media": False,
                }
            )
            continue
        child_files, file_issues = _collect_batch_item_files(provider, cookie, child)
        issues.extend(file_issues)
        child_path = normalize_relative_path(str(child.get("path", "") or child.get("name", "") or ""))
        has_direct_media = any(
            normalize_relative_path(str(file_item.get("parent_path", "") or "")) == child_path
            for file_item in child_files
        )
        if has_direct_media:
            items.append(
                {
                    "entry": child,
                    "name": str(child.get("name", "") or ""),
                    "path": _scraper_entry_path(child),
                    "parent_path": str(child.get("parent_path", "") or ""),
                    "parent_id": str(child.get("parent_id", "") or ""),
                    "is_dir": True,
                    "files": child_files,
                    "no_media": False,
                }
            )
            continue
        if _is_scraper_library_container_folder(str(child.get("name", "") or "")):
            sub_items = _split_scraper_library_item_sources(
                provider,
                cookie,
                child,
                issues,
                depth=depth + 1,
                max_depth=max_depth,
            )
            if not sub_items:
                issues.append(f"分类文件夹 {child.get('name', '--')} 内未发现可识别条目，已跳过")
            items.extend(sub_items)
            continue
        if child_files:
            items.append(
                {
                    "entry": child,
                    "name": str(child.get("name", "") or ""),
                    "path": _scraper_entry_path(child),
                    "parent_path": str(child.get("parent_path", "") or ""),
                    "parent_id": str(child.get("parent_id", "") or ""),
                    "is_dir": True,
                    "files": child_files,
                    "no_media": False,
                }
            )
        else:
            issues.append(f"文件夹 {child.get('name', '--')} 未发现媒体文件，已跳过")
    return items


def _collect_batch_item_files(
    provider: str,
    cookie: str,
    dir_entry: Dict[str, Any],
    *,
    max_files: int = SCRAPER_SCAN_MAX_ENTRIES,
    max_dirs: int = SCRAPER_SCAN_MAX_DIRS,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """递归收集一个文件夹条目内的媒体文件，用于批量整理识别。"""
    files: List[Dict[str, Any]] = []
    issues: List[str] = []
    queue: List[Tuple[str, str, int]] = [
        (
            str(dir_entry.get("id") or dir_entry.get("cid") or "0"),
            normalize_relative_path(str(dir_entry.get("path", "") or dir_entry.get("name", ""))),
            0,
        )
    ]
    dirs_seen = 0
    while queue and len(files) < max_files and dirs_seen < max_dirs:
        dir_id, dir_path, depth = queue.pop(0)
        dirs_seen += 1
        try:
            payload = _list_provider_entries_payload(provider, cookie, dir_id, folders_only=False)
        except Exception as exc:
            issues.append(f"读取目录 {dir_path or dir_id} 失败：{exc}")
            continue
        entries = payload.get("entries", []) if isinstance(payload, dict) and isinstance(payload.get("entries"), list) else []
        for raw in entries:
            child = _compact_scraper_entry(raw, dir_id, dir_path)
            if not child:
                continue
            if child.get("is_dir"):
                if depth < 6:
                    queue.append(
                        (
                            str(child.get("id") or child.get("cid") or "0"),
                            normalize_relative_path(str(child.get("path", ""))),
                            depth + 1,
                        )
                    )
                continue
            if not _is_scraper_media_file(str(child.get("name", "") or "")):
                continue
            files.append(child)
            if len(files) >= max_files:
                issues.append(f"已达到单条目扫描上限 {max_files} 个文件，超出部分未纳入计划")
                break
    return files, issues


def scan_scraper_batch_items(
    provider: str,
    base_cid: str = "0",
    base_path: str = "",
    selected: Optional[List[Dict[str, Any]]] = None,
    split_folders: bool = False,
    split_mode: str = "auto",
) -> Dict[str, Any]:
    """按用户勾选的条目分组为批量整理候选；未勾选时回退为扫描根目录直接子条目。

    split_mode: auto=自动判断（库根拆分，作品文件夹保持单条目）；
    single=整个文件夹当一个条目；split=强制按子目录拆分。
    split_folders=True 等价于 split_mode=split（兼容旧调用）。
    """
    provider = normalize_scraper_provider(provider) or "115"
    _require_scraper_operation(provider, "scrape", "批量整理")
    cookie = _require_provider_cookie(provider)
    normalized_base_cid = str(base_cid or "0").strip() or "0"
    normalized_base_path = normalize_relative_path(str(base_path or "").strip())
    normalized_split_mode = str(split_mode or "").strip().lower()
    if normalized_split_mode not in ("auto", "single", "split"):
        normalized_split_mode = "auto"
    if split_folders:
        normalized_split_mode = "split"
    if selected:
        entries = _normalize_scraper_selected_entries(selected)
    else:
        payload = _list_provider_entries_payload(provider, cookie, normalized_base_cid, folders_only=False)
        raw_entries = (
            payload.get("entries", [])
            if isinstance(payload, dict) and isinstance(payload.get("entries"), list)
            else []
        )
        entries = []
        for raw in raw_entries:
            entry = _compact_scraper_entry(raw, normalized_base_cid, normalized_base_path)
            if entry:
                entries.append(entry)
    items: List[Dict[str, Any]] = []
    issues: List[str] = []
    item_index = 1
    file_groups, single_files = _group_scraper_loose_tv_files(
        [item for item in entries if not item.get("is_dir")]
    )
    for entry in entries:
        if len(items) >= SCRAPER_BATCH_MAX_ITEMS:
            issues.append(f"已达到批量整理上限 {SCRAPER_BATCH_MAX_ITEMS} 个条目，超出部分未纳入")
            break
        if not entry.get("is_dir"):
            # 散落文件统一在循环后处理（同剧集单集合并、电影保持单条目）。
            continue
        if normalized_split_mode == "single":
            effective_split = False
        elif normalized_split_mode == "split":
            effective_split = True
        else:
            effective_split = _looks_like_scraper_library_root(provider, cookie, entry)
        if effective_split:
            sub_items = _split_scraper_library_item_sources(provider, cookie, entry, issues)
            for sub_item in sub_items:
                if len(items) >= SCRAPER_BATCH_MAX_ITEMS:
                    issues.append(f"已达到批量整理上限 {SCRAPER_BATCH_MAX_ITEMS} 个条目，超出部分未纳入")
                    break
                sub_item["item_index"] = item_index
                item_index += 1
                items.append(sub_item)
            continue
        files, file_issues = _collect_batch_item_files(provider, cookie, entry)
        issues.extend(file_issues)
        items.append(
            {
                "item_index": item_index,
                "entry": entry,
                "name": str(entry.get("name", "") or ""),
                "path": _scraper_entry_path(entry),
                "parent_path": str(entry.get("parent_path", "") or ""),
                "parent_id": str(entry.get("parent_id", "") or ""),
                "is_dir": True,
                "files": files,
                "no_media": not files,
            }
        )
        item_index += 1
    for single in single_files:
        if len(items) >= SCRAPER_BATCH_MAX_ITEMS:
            issues.append(f"已达到批量整理上限 {SCRAPER_BATCH_MAX_ITEMS} 个条目，超出部分未纳入")
            break
        items.append(
            {
                "item_index": item_index,
                "entry": single,
                "name": str(single.get("name", "") or ""),
                "path": _scraper_entry_path(single),
                "parent_path": str(single.get("parent_path", "") or ""),
                "parent_id": str(single.get("parent_id", "") or ""),
                "is_dir": False,
                "files": [single],
                "no_media": False,
            }
        )
        item_index += 1
    for group in file_groups:
        if len(items) >= SCRAPER_BATCH_MAX_ITEMS:
            issues.append(f"已达到批量整理上限 {SCRAPER_BATCH_MAX_ITEMS} 个条目，超出部分未纳入")
            break
        first = group[0]
        title_candidates = _extract_scraper_title_candidates(str(first.get("name", "") or ""))
        group_title = title_candidates[0] if title_candidates else str(first.get("name", "") or "")
        items.append(
            {
                "item_index": item_index,
                "entry": first,
                "name": group_title,
                "path": _scraper_entry_path(first),
                "parent_path": str(first.get("parent_path", "") or ""),
                "parent_id": str(first.get("parent_id", "") or ""),
                "is_dir": False,
                "entries": group,
                "files": group,
                "no_media": False,
            }
        )
        item_index += 1
    return {
        "ok": True,
        "provider": provider,
        "base_cid": normalized_base_cid,
        "base_path": normalized_base_path,
        "items": items,
        "issues": issues,
    }


def _batch_item_query_payload(
    entry: Dict[str, Any],
    files: List[Dict[str, Any]],
) -> Tuple[str, str, str, List[str]]:
    names = [str(entry.get("name", "") or "")]
    names.extend(str(item.get("name", "") or "") for item in (files or [])[:40])
    # 主查询优先用条目自身名称按发布名结构提取的标题；父目录名（如“电影小库”）只作为噪声被过滤。
    # 条目名不可用时回退到内部媒体文件名，最后用文件公共前缀兜底。
    candidates = _extract_scraper_title_candidates(str(entry.get("name", "") or ""))
    if not candidates:
        for item in (files or [])[:40]:
            candidates.extend(_extract_scraper_title_candidates(str(item.get("name", "") or "")))
        if not candidates:
            cleaned_files = [
                _clean_search_title(str(item.get("name", "") or ""))
                for item in (files or [])[:40]
            ]
            cleaned_files = [
                item
                for item in cleaned_files
                if item and not _is_scraper_noise_keyword(item) and len(_scraper_keyword_key(item)) >= 2
            ]
            common_prefix = _common_scraper_prefix(cleaned_files)
            if common_prefix:
                candidates.append(common_prefix)
    unique_candidates: List[str] = []
    seen_queries: Set[str] = set()
    for candidate in candidates:
        key = _scraper_keyword_key(candidate)
        if not key or key in seen_queries:
            continue
        seen_queries.add(key)
        unique_candidates.append(candidate)
    query = unique_candidates[0] if unique_candidates else ""
    media_type = "tv" if _looks_like_tv(names) else "movie"
    year = _extract_year_from_names(names)
    return query, media_type, year, unique_candidates


def _search_batch_tmdb_candidates(
    query: str,
    media_type: str,
    year: str,
    cfg: Dict[str, Any],
) -> List[Dict[str, Any]]:
    normalized_type = normalize_tmdb_media_type(media_type, fallback="")
    types = [normalized_type] if normalized_type in ("movie", "tv") else ["movie", "tv"]
    # 优先按识别到的类型精确搜索；无结果时去掉年份，再回退到另一类型。
    for current_type in types + [""]:
        for current_year in ([year, ""] if year else [""]):
            data = search_tmdb_media(query, current_type, current_year, 1, cfg)
            items = data.get("items", []) if isinstance(data, dict) and isinstance(data.get("items"), list) else []
            if items:
                return items
    return []


def _score_batch_tmdb_candidate(
    query: str,
    year: str,
    preferred_type: str,
    item: Dict[str, Any],
    aliases: Optional[List[str]] = None,
) -> int:
    score = _score_tmdb_candidate(query, year, item, aliases=aliases)
    if normalize_tmdb_media_type(item.get("media_type"), "") == normalize_tmdb_media_type(preferred_type, ""):
        score += 8
    return min(100, score)


def _enrich_batch_candidates_with_aliases(
    scored: List[Dict[str, Any]],
    query: str,
    year: str,
    preferred_type: str,
    cfg: Dict[str, Any],
    penalty: int = 0,
) -> List[Dict[str, Any]]:
    """得分接近时补拉 TMDB 详情，用别名/译名打破僵局，避免热门同名片霸榜。"""
    if len(scored) < 2:
        return scored
    top_score = max(0, int(scored[0].get("score", 0) or 0))
    second_score = max(0, int(scored[1].get("score", 0) or 0))
    if top_score - second_score > 12 or top_score >= 90:
        return scored
    enriched: List[Dict[str, Any]] = []
    for candidate in scored[:3]:
        aliases: List[str] = []
        detail: Dict[str, Any] = {}
        try:
            detail = get_tmdb_media_detail(
                int(candidate.get("id", 0) or 0),
                str(candidate.get("media_type", "") or ""),
                cfg,
            )
        except Exception:
            detail = {}
        if isinstance(detail, dict):
            raw_aliases = detail.get("aliases", [])
            if isinstance(raw_aliases, list):
                aliases = [str(item or "").strip() for item in raw_aliases if str(item or "").strip()]
        candidate_score = max(
            0,
            _score_batch_tmdb_candidate(query, year, preferred_type, candidate, aliases=aliases) - penalty,
        )
        enriched.append({**candidate, "score": candidate_score})
    return enriched + scored[3:]


def _identify_scraper_batch_item(
    item: Dict[str, Any],
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    entry = item.get("entry") if isinstance(item.get("entry"), dict) else {}
    item_index = max(0, parse_int(item.get("item_index", 0), 0))
    name = str(item.get("name") or entry.get("name") or "")
    if not entry:
        return {"item_index": item_index, "ok": False, "name": name, "msg": "缺少网盘条目信息"}
    files = item.get("files") if isinstance(item.get("files"), list) else []
    query, media_type, year, query_variants = _batch_item_query_payload(entry, files)
    candidates: List[Dict[str, Any]] = []
    auto_pick: Optional[Dict[str, Any]] = None
    status = "manual"
    confidence = 0
    if query:
        search_queries: List[str] = []
        seen_queries: Set[str] = set()
        for candidate in query_variants + _scraper_query_degradations(query):
            key = _scraper_keyword_key(candidate)
            if not key or key in seen_queries:
                continue
            seen_queries.add(key)
            search_queries.append(candidate)
        raw_candidates: List[Dict[str, Any]] = []
        query_index = 0
        for index, candidate_query in enumerate(search_queries):
            found = _search_batch_tmdb_candidates(candidate_query, media_type, year, cfg)
            if found:
                raw_candidates = found
                query_index = index
                break
        # 只有主查询命中的候选才可能自动匹配；降级查询命中一律扣分，避免误自动选片。
        degradation_penalty = 25 * query_index
        scored: List[Dict[str, Any]] = []
        for candidate in raw_candidates:
            candidate_score = _score_batch_tmdb_candidate(
                search_queries[query_index],
                year,
                media_type,
                candidate,
            ) - degradation_penalty
            scored.append({**candidate, "score": candidate_score})
        scored.sort(
            key=lambda payload: (max(0, int(payload.get("score", 0) or 0)), float(payload.get("popularity", 0) or 0)),
            reverse=True,
        )
        candidates = scored[:5]
        if candidates:
            candidates = _enrich_batch_candidates_with_aliases(
                candidates,
                search_queries[query_index],
                year,
                media_type,
                cfg,
                penalty=degradation_penalty,
            )
            candidates.sort(
                key=lambda payload: (max(0, int(payload.get("score", 0) or 0)), float(payload.get("popularity", 0) or 0)),
                reverse=True,
            )
            candidates = candidates[:5]
            confidence = max(0, int(candidates[0].get("score", 0) or 0))
            top_year = str(candidates[0].get("year", "") or "").strip()
            year_conflict = bool(year) and bool(top_year) and top_year != year
            if confidence >= 80 and not year_conflict:
                status = "auto"
                auto_pick = candidates[0]
            elif confidence >= 55:
                status = "suggest"
    return {
        "item_index": item_index,
        "ok": True,
        "name": name,
        "query": query,
        "media_type": media_type,
        "year": year,
        "candidates": candidates,
        "auto_pick": auto_pick or None,
        "status": status,
        "confidence": confidence,
    }


def identify_scraper_batch_items(payload: Dict[str, Any]) -> Dict[str, Any]:
    provider = normalize_scraper_provider(payload.get("provider", "115")) or "115"
    raw_items = payload.get("items", []) if isinstance(payload.get("items"), list) else []
    if not raw_items:
        return {"ok": True, "provider": provider, "results": []}
    cfg = get_config()
    config_error = validate_tmdb_runtime_config(cfg)
    if config_error:
        raise RuntimeError(config_error)
    results = [_identify_scraper_batch_item(item, cfg) for item in raw_items]
    return {"ok": True, "provider": provider, "results": results}


def _resolve_batch_tmdb_binding(tmdb: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """候选条目只带轻量字段；这里补拉 TMDB 详情生成完整任务绑定。"""
    tmdb_id = max(0, parse_int(tmdb.get("tmdb_id") or tmdb.get("id") or 0, 0))
    media_type = normalize_tmdb_media_type(tmdb.get("tmdb_media_type") or tmdb.get("media_type"), "")
    if tmdb_id <= 0 or media_type not in ("movie", "tv"):
        return {}
    if str(tmdb.get("tmdb_media_type") or tmdb.get("media_type") or "").strip() and tmdb.get("tmdb_season_episode_map") is not None:
        return dict(tmdb)
    try:
        detail = get_tmdb_media_detail(tmdb_id, media_type, cfg)
    except Exception:
        return {}
    if not isinstance(detail, dict) or not detail:
        return {}
    return build_tmdb_task_binding(detail, media_type=media_type)


def build_scraper_batch_plan(payload: Dict[str, Any]) -> Dict[str, Any]:
    provider = normalize_scraper_provider(payload.get("provider", "115")) or "115"
    _require_scraper_operation(provider, "scrape", "执行")
    base_cid = str(payload.get("base_cid", "0") or "0").strip() or "0"
    base_path = normalize_relative_path(str(payload.get("base_path", "") or ""))
    options = payload.get("options") if isinstance(payload.get("options"), dict) else {}
    raw_items = payload.get("items", []) if isinstance(payload.get("items"), list) else []
    if not raw_items:
        raise RuntimeError("没有选择要整理的条目")
    cfg = get_config()
    config_error = validate_tmdb_runtime_config(cfg)
    if config_error:
        raise RuntimeError(config_error)

    actions: List[Dict[str, Any]] = []
    issues: List[str] = []
    warnings: List[str] = []
    item_summaries: List[Dict[str, Any]] = []
    action_index = 1
    unchanged_count = 0
    ignored_count = 0
    unchanged_rows: List[Dict[str, Any]] = []
    for raw_item in raw_items:
        item = raw_item if isinstance(raw_item, dict) else {}
        item_index = max(0, parse_int(item.get("item_index", 0), 0))
        entry = item.get("entry") if isinstance(item.get("entry"), dict) else {}
        tmdb = item.get("tmdb") if isinstance(item.get("tmdb"), dict) else {}
        item_name = str(item.get("name") or entry.get("name") or "")
        if not entry.get("id"):
            issues.append(f"条目 #{item_index} {item_name or '--'}：缺少网盘条目信息")
            continue
        binding = _resolve_batch_tmdb_binding(tmdb, cfg)
        if not binding:
            issues.append(f"条目 #{item_index} {item_name or '--'}：未绑定 TMDB 或详情获取失败")
            continue
        item_options = dict(options)
        item_overrides = item.get("options") if isinstance(item.get("options"), dict) else {}
        item_options.update(item_overrides)
        if bool(entry.get("is_dir")):
            item_options["selection_mode"] = "folder"
        else:
            item_options["selection_mode"] = "contents"
        item_options["base_path"] = base_path
        plan_entries = item.get("entries") if isinstance(item.get("entries"), list) and item.get("entries") else [entry]
        item_payload: Dict[str, Any] = {
            "provider": provider,
            "base_cid": base_cid,
            "base_path": base_path,
            "entries": plan_entries,
            "tmdb": binding,
            "options": item_options,
        }
        episode_overrides = item.get("episode_overrides")
        if isinstance(episode_overrides, dict) and episode_overrides:
            item_payload["episode_overrides"] = episode_overrides
        try:
            plan = build_scraper_rename_plan(item_payload)
        except Exception as exc:
            issues.append(f"条目 #{item_index} {item_name or '--'}：{exc}")
            continue
        plan_actions = [action for action in plan.get("actions", []) if isinstance(action, dict)]
        item_issues = [str(value) for value in plan.get("issues", []) if str(value or "").strip()]
        item_warnings = [str(value) for value in plan.get("warnings", []) if str(value or "").strip()]
        item_ignored = max(0, int(plan.get("ignored_count", 0) or 0))
        issues.extend(f"条目 #{item_index} {item_name or '--'}：{text}" for text in item_issues)
        warnings.extend(f"条目 #{item_index} {item_name or '--'}：{text}" for text in item_warnings)
        unchanged_count += max(0, int(plan.get("unchanged_count", 0) or 0))
        ignored_count += item_ignored
        item_unchanged = plan.get("unchanged_rows", []) if isinstance(plan.get("unchanged_rows"), list) else []
        for row in item_unchanged:
            unchanged_rows.append(
                {
                    **row,
                    "item_index": item_index,
                    "item_name": item_name,
                }
            )
        for action in plan_actions:
            merged = dict(action)
            merged["action_index"] = action_index
            merged["item_index"] = item_index
            merged["item_name"] = item_name
            action_index += 1
            actions.append(merged)
        display_title = choose_scraper_title(binding, options.get("title_language", "auto"), fallback=item_name)
        item_summaries.append(
            {
                "item_index": item_index,
                "name": item_name,
                "title": display_title,
                "year": str(binding.get("tmdb_year") or binding.get("year") or ""),
                "media_type": normalize_tmdb_media_type(
                    binding.get("tmdb_media_type") or binding.get("media_type"),
                    "movie",
                ),
                "total": len(plan_actions),
                "ready": sum(1 for action in plan_actions if action.get("ready") and not action.get("issue")),
                "issue_count": len(item_issues),
                "unchanged": max(0, int(plan.get("unchanged_count", 0) or 0)),
                "ignored": item_ignored,
            }
        )

    # 跨条目目标冲突检测：同一批内不同条目不能落到同一个目标路径。
    seen_targets: Dict[str, str] = {}
    for action in actions:
        if action.get("issue"):
            continue
        target = normalize_relative_path(str(action.get("new_path", "") or ""))
        if not target:
            continue
        entry_id = str(action.get("entry_id", "") or "")
        previous_entry = seen_targets.get(target, "")
        if previous_entry and previous_entry != entry_id:
            action["issue"] = "目标路径与本批次其他条目重复"
            action["ready"] = False
            issues.append(
                f"条目 #{action.get('item_index', 0)} {action.get('item_name') or '--'}："
                f"目标路径 {target} 与本批次其他条目重复"
            )
        elif not previous_entry:
            seen_targets[target] = entry_id

    # 冲突标记后重算每个条目的可执行数，避免汇总与最终 ready_count 不一致。
    item_ready_counts: Dict[int, int] = {}
    for action in actions:
        if action.get("ready") and not action.get("issue"):
            item_index = max(0, int(action.get("item_index", 0) or 0))
            item_ready_counts[item_index] = item_ready_counts.get(item_index, 0) + 1
    for summary in item_summaries:
        summary["ready"] = item_ready_counts.get(max(0, int(summary.get("item_index", 0) or 0)), 0)

    ready_count = sum(1 for action in actions if action.get("ready") and not action.get("issue"))
    return {
        "ok": True,
        "provider": provider,
        "base_cid": base_cid,
        "base_path": base_path,
        "options": options,
        "tmdb": {
            "batch": True,
            "title": "批量整理",
            "tmdb_id": 0,
            "media_type": "movie",
        },
        "items": item_summaries,
        "actions": actions,
        "issues": issues,
        "warnings": warnings,
        "total_count": len(actions),
        "ready_count": ready_count,
        "unchanged_count": unchanged_count,
        "unchanged_rows": unchanged_rows,
        "ignored_count": ignored_count,
    }
