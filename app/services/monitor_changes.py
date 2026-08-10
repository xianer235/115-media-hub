import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from ..core import (
    STRM_ROOT,
    build_strm_play_url,
    get_config,
    get_mount_prefix,
    is_subpath,
    list_remote_dir,
    normalize_task,
    resolve_task_root,
)
from ..db import db_connection, ensure_db, now_text, safe_json_dumps, safe_json_loads, sqlite_row_to_dict
from ..runtime_files import (
    basename,
    get_user_extensions,
    is_video_file,
    join_relative_path,
    join_remote_path,
    normalize_relative_path,
    normalize_remote_path,
)
from .strm_files import delete_managed_strm_file, managed_strm_file_path, remove_empty_parent_dirs


MONITOR_CHANGE_MAX_RETRIES = 5
MONITOR_CHANGE_RETRY_BASE_SECONDS = 5
MONITOR_CHANGE_COMPLETED_RETENTION_DAYS = 30
# Increment when a deployed handler changes how an event is interpreted.  A
# maxed-out event from an older handler gets one fresh attempt after startup.
MONITOR_CHANGE_HANDLER_REVISION = 1

_CHANGE_OPERATIONS = {"create", "copy", "move", "rename", "delete"}
_CHANGE_OPERATION_ALIASES = {
    "add": "create",
    "create_folder": "create",
    "mkdir": "create",
    "remove": "delete",
}


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(float(str(value or 0).strip())))
    except (TypeError, ValueError, OverflowError):
        return 0


def _snapshot_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "on"}


def _normalize_operation(value: Any) -> str:
    operation = str(value or "").strip().lower()
    operation = _CHANGE_OPERATION_ALIASES.get(operation, operation)
    if operation not in _CHANGE_OPERATIONS:
        raise ValueError(f"不支持的监控变更类型: {operation or '--'}")
    return operation


def _normalize_entry_snapshot(raw: Any, operation: str) -> Dict[str, Any]:
    item = raw if isinstance(raw, dict) else {}
    entry_id = str(item.get("id", "") or item.get("entry_id", "") or "").strip()
    is_dir = _snapshot_bool(item.get("is_dir", False))
    old_path = normalize_relative_path(
        str(item.get("old_path", "") or item.get("path", "") or "").strip()
    )
    new_path = normalize_relative_path(str(item.get("new_path", "") or "").strip())
    if operation == "create":
        new_path = new_path or old_path
        old_path = ""
    if operation == "delete":
        new_path = ""
    name = str(item.get("name", "") or basename(new_path or old_path)).strip()
    if not old_path and operation in {"rename", "move", "copy", "delete"}:
        return {}
    if not new_path and operation in {"rename", "move", "copy", "create"}:
        return {}
    parent_path = normalize_relative_path(str(item.get("parent_path", "") or ""))
    if not parent_path:
        parent_path = normalize_relative_path(os.path.dirname(old_path or new_path))
    old_parent_id = str(
        item.get("old_parent_id", "")
        or item.get("parent_id", "")
        or item.get("source_parent_id", "")
        or ""
    ).strip()
    new_parent_id = str(
        item.get("new_parent_id", "")
        or item.get("target_parent_id", "")
        or (old_parent_id if operation in {"rename", "create"} else "")
        or ""
    ).strip()
    raw_entry_cid = str(item.get("cid", "") or "").strip()
    old_cid = str(item.get("old_cid", "") or "").strip()
    new_cid = str(item.get("new_cid", "") or "").strip()
    if is_dir:
        old_cid = old_cid or (raw_entry_cid if operation != "create" else "")
        if operation in {"rename", "move"}:
            new_cid = new_cid or old_cid or entry_id
    return {
        "id": entry_id,
        "name": name,
        "is_dir": is_dir,
        "old_path": old_path,
        "new_path": new_path,
        "parent_path": parent_path,
        "old_parent_id": old_parent_id,
        "new_parent_id": new_parent_id,
        "old_cid": old_cid,
        "new_cid": new_cid,
        "size": _nonnegative_int(item.get("size", 0)),
        "modified_at": str(item.get("modified_at", "") or item.get("modified", "") or "").strip(),
    }


def _task_path_context(cfg: Dict[str, Any], task: Dict[str, Any], provider_path: str) -> Dict[str, str]:
    path = normalize_relative_path(provider_path)
    if not path:
        return {}
    mount_prefix = get_mount_prefix(cfg, "115")
    if not mount_prefix:
        return {}
    remote_path = join_remote_path(mount_prefix, path)
    scan_path = normalize_remote_path(task.get("scan_path", ""))
    if not scan_path or scan_path == "/" or not is_subpath(remote_path, scan_path):
        return {}
    remote_rel_path = normalize_relative_path(remote_path[len(scan_path) :])
    task_root = resolve_task_root(task)
    local_rel_path = join_relative_path(task_root, remote_rel_path)
    return {
        "provider_path": path,
        "remote_path": remote_path,
        "remote_rel_path": remote_rel_path,
        "local_rel_path": local_rel_path,
        "task_root": task_root,
        "scan_path": scan_path,
    }


def match_monitor_tasks_for_paths(
    cfg: Dict[str, Any],
    paths: Iterable[str],
    provider: str = "115",
) -> List[Dict[str, Any]]:
    if str(provider or "").strip().lower() != "115":
        return []
    normalized_paths = [normalize_relative_path(path) for path in paths]
    normalized_paths = [path for path in normalized_paths if path]
    if not normalized_paths:
        return []
    matched: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for raw_task in cfg.get("monitor_tasks", []) or []:
        task = normalize_task(raw_task or {})
        task_name = str(task.get("name", "") or "").strip()
        if not task_name or task_name in seen:
            continue
        if any(_task_path_context(cfg, task, path) for path in normalized_paths):
            matched.append(task)
            seen.add(task_name)
    return matched


def _sql_like_descendant_pattern(path: str) -> str:
    escaped = str(path or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"{escaped}/%"


def _provider_path_from_index(
    cfg: Dict[str, Any],
    task: Dict[str, Any],
    remote_rel_path: str,
) -> str:
    mount_prefix = get_mount_prefix(cfg, "115")
    full_path = join_remote_path(task.get("scan_path", ""), remote_rel_path)
    if full_path == mount_prefix:
        return ""
    if not is_subpath(full_path, mount_prefix):
        return ""
    return normalize_relative_path(full_path[len(mount_prefix) :])


def _task_min_file_size_bytes(task: Dict[str, Any]) -> int:
    try:
        return max(0, int(float(task.get("min_file_size_mb", 0) or 0) * 1024 * 1024))
    except (TypeError, ValueError, OverflowError):
        return 0


def _capture_indexed_manifest(
    cfg: Dict[str, Any],
    tasks: Sequence[Dict[str, Any]],
    old_path: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    manifest_by_path: Dict[str, Dict[str, Any]] = {}
    dir_manifest_by_path: Dict[str, Dict[str, Any]] = {}
    source_evidence: List[Dict[str, Any]] = []
    with db_connection() as conn:
        cursor = conn.cursor()
        for task in tasks:
            context = _task_path_context(cfg, task, old_path)
            if not context:
                continue
            task_name = str(task.get("name", "") or "")
            local_prefix = context["local_rel_path"]
            scope_like = _sql_like_descendant_pattern(local_prefix)
            cursor.execute(
                """
                SELECT remote_rel_path, remote_modified, file_size
                FROM monitor_files
                WHERE task_name = ?
                AND (local_rel_path = ? OR local_rel_path LIKE ? ESCAPE '\\')
                ORDER BY local_rel_path
                """,
                (task_name, local_prefix, scope_like),
            )
            rows = cursor.fetchall()
            for row in rows:
                provider_path = _provider_path_from_index(cfg, task, str(row[0] or ""))
                if not provider_path:
                    continue
                manifest_by_path.setdefault(
                    provider_path,
                    {
                        "path": provider_path,
                        "size": max(0, int(row[2] or 0)),
                        "modified_at": str(row[1] or ""),
                    },
                )

            dir_rel_path = normalize_relative_path(context["remote_rel_path"])
            cursor.execute(
                """
                SELECT dir_rel_path, remote_modified, entry_modified, needs_rescan
                FROM monitor_dirs
                WHERE task_name = ?
                """,
                (task_name,),
            )
            dir_states = [
                (
                    normalize_relative_path(str(row[0] or "")),
                    str(row[1] or ""),
                    str(row[2] or ""),
                    bool(int(row[3] or 0)),
                )
                for row in cursor.fetchall()
            ]
            has_dirty_scope = any(
                dirty
                and (
                    not rel
                    or not dir_rel_path
                    or rel == dir_rel_path
                    or rel.startswith(f"{dir_rel_path}/")
                    or dir_rel_path.startswith(f"{rel}/")
                )
                for rel, _remote_modified, _entry_modified, dirty in dir_states
            )
            has_clean_exact_dir = any(
                rel == dir_rel_path and not dirty
                for rel, _remote_modified, _entry_modified, dirty in dir_states
            )
            for rel, remote_modified, entry_modified, _dirty in dir_states:
                if rel != dir_rel_path and not rel.startswith(f"{dir_rel_path}/"):
                    continue
                provider_path = _provider_path_from_index(cfg, task, rel)
                if not provider_path:
                    continue
                dir_manifest_by_path.setdefault(
                    provider_path,
                    {
                        "path": provider_path,
                        "remote_modified": remote_modified,
                        "entry_modified": entry_modified,
                    },
                )
            source_evidence.append(
                {
                    "task_name": task_name,
                    "complete": bool(rows or has_clean_exact_dir) and not has_dirty_scope,
                    "min_file_size_bytes": _task_min_file_size_bytes(task),
                }
            )
    return (
        list(manifest_by_path.values()),
        list(dir_manifest_by_path.values()),
        source_evidence,
    )


def _manifest_is_complete_for_task(
    task: Dict[str, Any],
    source_evidence: Sequence[Dict[str, Any]],
) -> bool:
    target_min_bytes = _task_min_file_size_bytes(task)
    return any(
        bool(item.get("complete"))
        and _nonnegative_int(item.get("min_file_size_bytes", 0)) <= target_min_bytes
        for item in source_evidence
        if isinstance(item, dict)
    )


def _load_scraper_job_path_rewrites(
    conn: Any,
    task_name: str,
    source_action: str,
    *,
    statuses: Sequence[str],
    before_event_id: int = 0,
    directories_only: bool = False,
) -> List[Tuple[str, str]]:
    normalized_source = str(source_action or "").strip()
    normalized_statuses = [str(status or "").strip() for status in statuses if str(status or "").strip()]
    if not normalized_source.startswith("scraper-job:") or not normalized_statuses:
        return []
    placeholders = ",".join("?" for _ in normalized_statuses)
    clauses = [
        "task_name = ?",
        "source_action = ?",
        f"status IN ({placeholders})",
        "needs_reconcile = 0",
        "operation IN ('rename', 'move')",
    ]
    values: List[Any] = [str(task_name or ""), normalized_source, *normalized_statuses]
    if before_event_id > 0:
        clauses.append("id < ?")
        values.append(int(before_event_id))
    rows = conn.execute(
        f"""
        SELECT old_path, new_path, entry_snapshot_json
        FROM monitor_change_events
        WHERE {' AND '.join(clauses)}
        ORDER BY id
        """,
        tuple(values),
    ).fetchall()
    rewrites: List[Tuple[str, str]] = []
    for row in rows:
        if directories_only:
            snapshot = safe_json_loads(row[2], {})
            if not isinstance(snapshot, dict) or not _snapshot_bool(snapshot.get("is_dir")):
                continue
        old_root = normalize_relative_path(str(row[0] or ""))
        new_root = normalize_relative_path(str(row[1] or ""))
        if not old_root or not new_root or old_root == new_root:
            continue
        rewrites.append((old_root, new_root))
    return rewrites


def _project_scraper_job_manifest(
    conn: Any,
    task_name: str,
    source_action: str,
    items: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    projected = [dict(item) for item in items if isinstance(item, dict)]
    if not projected:
        return projected
    rewrites = _load_scraper_job_path_rewrites(
        conn,
        task_name,
        source_action,
        statuses=("pending", "processing", "completed", "manual_required"),
    )
    for old_root, new_root in rewrites:
        for item in projected:
            source_path = normalize_relative_path(str(item.get("path", "") or ""))
            target_path = _manifest_target_path(old_root, new_root, source_path)
            if target_path:
                item["path"] = target_path
    return projected


def _event_entry_key(base_key: str, entry: Dict[str, Any], index: int) -> str:
    identity = str(entry.get("id", "") or entry.get("old_path", "") or entry.get("new_path", "") or index)
    return f"{str(base_key or 'monitor-change').strip()}:{identity}"[:500]


def prepare_monitor_change_events(
    *,
    provider: str,
    operation: str,
    entries: Sequence[Dict[str, Any]],
    source_action: str = "",
    dedupe_key: str = "",
    cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    normalized_provider = str(provider or "").strip().lower()
    if normalized_provider != "115":
        return {
            "status": "not_applicable",
            "matched_tasks": [],
            "event_ids": [],
            "event_count": 0,
        }
    normalized_operation = _normalize_operation(operation)
    snapshots = [
        snapshot
        for snapshot in (
            _normalize_entry_snapshot(raw, normalized_operation)
            for raw in (entries if isinstance(entries, (list, tuple)) else [])
        )
        if snapshot
    ]
    if not snapshots:
        return {
            "status": "unavailable",
            "matched_tasks": [],
            "event_ids": [],
            "event_count": 0,
        }

    active_cfg = cfg or get_config()
    ensure_db()
    now = now_text()
    event_ids: List[int] = []
    matched_names: Set[str] = set()
    with db_connection() as conn:
        cursor = conn.cursor()
        for index, snapshot in enumerate(snapshots):
            task_matches = match_monitor_tasks_for_paths(
                active_cfg,
                [snapshot.get("old_path", ""), snapshot.get("new_path", "")],
                provider="115",
            )
            if not task_matches:
                continue
            manifest: List[Dict[str, Any]] = []
            indexed_dirs: List[Dict[str, Any]] = []
            source_evidence: List[Dict[str, Any]] = []
            if snapshot.get("is_dir") and snapshot.get("old_path"):
                manifest, indexed_dirs, source_evidence = _capture_indexed_manifest(
                    active_cfg,
                    task_matches,
                    str(snapshot.get("old_path", "")),
                )
            entry_key = _event_entry_key(dedupe_key, snapshot, index)
            for task in task_matches:
                task_name = str(task.get("name", "") or "").strip()
                if not task_name:
                    continue
                enriched = dict(snapshot)
                if snapshot.get("is_dir") and snapshot.get("old_path"):
                    manifest_known = _manifest_is_complete_for_task(task, source_evidence)
                    enriched["manifest_known"] = manifest_known
                    enriched["indexed_files"] = _project_scraper_job_manifest(
                        conn,
                        task_name,
                        source_action,
                        manifest,
                    )
                    enriched["indexed_dirs"] = _project_scraper_job_manifest(
                        conn,
                        task_name,
                        source_action,
                        indexed_dirs,
                    )
                enriched["manual_required"] = bool(
                    enriched.get("is_dir")
                    and normalized_operation in {"copy", "rename", "move"}
                    and enriched.get("new_path")
                    and _task_path_context(active_cfg, task, str(enriched.get("new_path", "")))
                    and not enriched.get("manifest_known")
                )
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO monitor_change_events(
                        dedupe_key, provider, operation, old_path, new_path,
                        entry_snapshot_json, task_name, source_action, status,
                        created_at, updated_at
                    ) VALUES (?, '115', ?, ?, ?, ?, ?, ?, 'prepared', ?, ?)
                    """,
                    (
                        entry_key,
                        normalized_operation,
                        str(snapshot.get("old_path", "") or ""),
                        str(snapshot.get("new_path", "") or ""),
                        safe_json_dumps(enriched),
                        task_name,
                        str(source_action or "")[:200],
                        now,
                        now,
                    ),
                )
                cursor.execute(
                    """
                    SELECT id FROM monitor_change_events
                    WHERE dedupe_key = ? AND task_name = ? AND old_path = ? AND new_path = ?
                    """,
                    (
                        entry_key,
                        task_name,
                        str(snapshot.get("old_path", "") or ""),
                        str(snapshot.get("new_path", "") or ""),
                    ),
                )
                row = cursor.fetchone()
                if row:
                    event_ids.append(int(row[0] or 0))
                    matched_names.add(task_name)
        conn.commit()

    unique_event_ids = sorted({event_id for event_id in event_ids if event_id > 0})
    if not unique_event_ids:
        status = "not_matched"
    else:
        status = "prepared"
    return {
        "status": status,
        "matched_tasks": sorted(matched_names),
        "event_ids": unique_event_ids,
        "event_count": len(unique_event_ids),
    }


def update_monitor_change_event_snapshots(
    prepared: Dict[str, Any],
    updates: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Persist post-operation directory IDs before an event is confirmed.

    A copy response can expose the newly-created folder CID only after the
    remote mutation succeeds.  Updating the prepared snapshot in its own
    transaction keeps that locator available to a later change worker without
    ever substituting the source folder CID or walking a parent path.
    """
    event_ids = sorted(
        {
            int(value or 0)
            for value in (prepared.get("event_ids", []) if isinstance(prepared, dict) else [])
            if int(value or 0) > 0
        }
    )
    normalized_updates = [item for item in (updates or []) if isinstance(item, dict)]
    if not event_ids or not normalized_updates:
        return {"updated": 0, "event_ids": event_ids}

    allowed_keys = {
        "name",
        "old_parent_id",
        "new_parent_id",
        "old_cid",
        "new_cid",
        "size",
        "modified_at",
    }
    placeholders = ",".join("?" for _ in event_ids)
    updated = 0
    now = now_text()
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT id, old_path, new_path, entry_snapshot_json
            FROM monitor_change_events
            WHERE id IN ({placeholders}) AND status = 'prepared'
            """,
            tuple(event_ids),
        )
        for row in cursor.fetchall():
            event_id = int(row[0] or 0)
            old_path = str(row[1] or "")
            new_path = str(row[2] or "")
            snapshot = safe_json_loads(row[3], {})
            if not isinstance(snapshot, dict):
                snapshot = {}
            snapshot_id = str(snapshot.get("id", "") or "").strip()
            matching_update = None
            for candidate in normalized_updates:
                candidate_id = str(candidate.get("id", "") or "").strip()
                candidate_old = normalize_relative_path(str(candidate.get("old_path", "") or ""))
                candidate_new = normalize_relative_path(str(candidate.get("new_path", "") or ""))
                if candidate_id and snapshot_id and candidate_id == snapshot_id:
                    matching_update = candidate
                    break
                if (candidate_old or candidate_new) and candidate_old == old_path and candidate_new == new_path:
                    matching_update = candidate
                    break
                if not candidate_id and not candidate_old and not candidate_new and len(normalized_updates) == 1:
                    matching_update = candidate
                    break
            if matching_update is None:
                continue
            changed = False
            for key in allowed_keys:
                if key not in matching_update:
                    continue
                value = matching_update.get(key)
                if key in {"old_parent_id", "new_parent_id", "old_cid", "new_cid", "name", "modified_at"}:
                    value = str(value or "").strip()
                elif key == "size":
                    value = _nonnegative_int(value)
                if snapshot.get(key) != value:
                    snapshot[key] = value
                    changed = True
            if not changed:
                continue
            cursor.execute(
                """
                UPDATE monitor_change_events
                SET entry_snapshot_json = ?, updated_at = ?
                WHERE id = ? AND status = 'prepared'
                """,
                (safe_json_dumps(snapshot), now, event_id),
            )
            updated += max(0, int(cursor.rowcount or 0))
        conn.commit()
    return {"updated": updated, "event_ids": event_ids}


def _merge_continuous_path_events(conn: Any, event_ids: Sequence[int]) -> None:
    now = now_text()
    cursor = conn.cursor()
    for event_id in event_ids:
        cursor.execute(
            """
            SELECT id, task_name, operation, old_path, new_path, entry_snapshot_json, source_action,
                   needs_reconcile
            FROM monitor_change_events
            WHERE id = ? AND status = 'pending' AND operation IN ('rename', 'move')
            """,
            (int(event_id),),
        )
        current = cursor.fetchone()
        if not current:
            continue
        cursor.execute(
            """
            SELECT id, old_path, entry_snapshot_json, needs_reconcile, status
            FROM monitor_change_events
            WHERE task_name = ? AND status IN ('pending', 'manual_required') AND id < ?
            AND operation IN ('rename', 'move') AND new_path = ?
            ORDER BY id DESC LIMIT 1
            """,
            (
                str(current[1] or ""),
                int(current[0] or 0),
                str(current[3] or ""),
            ),
        )
        previous = cursor.fetchone()
        if not previous:
            continue
        current_snapshot = safe_json_loads(current[5], {})
        previous_snapshot = safe_json_loads(previous[2], {})
        if not isinstance(current_snapshot, dict):
            current_snapshot = {}
        current_entry_id = str(current_snapshot.get("id", "") or "").strip()
        previous_entry_id = (
            str(previous_snapshot.get("id", "") or "").strip()
            if isinstance(previous_snapshot, dict)
            else ""
        )
        if not current_entry_id or not previous_entry_id or current_entry_id != previous_entry_id:
            continue
        previous_status = str(previous[4] or "").strip()
        # A worker may have changed STRM files before its transaction was
        # committed.  Recovery leaves a marker on that event so a later
        # reverse action cannot hide the uncertain local state as a no-op.
        if (
            bool(current_snapshot.get("local_sync_uncertain"))
            or bool(previous_snapshot.get("local_sync_uncertain"))
        ):
            continue
        if isinstance(previous_snapshot, dict):
            if previous_snapshot.get("manifest_known") and not current_snapshot.get("manifest_known"):
                current_snapshot["manifest_known"] = True
                current_snapshot["indexed_files"] = previous_snapshot.get("indexed_files", [])
                current_snapshot["indexed_dirs"] = previous_snapshot.get("indexed_dirs", [])
                current_snapshot["manual_required"] = False
            elif previous_snapshot.get("manual_required") and not current_snapshot.get("manifest_known"):
                current_snapshot["manual_required"] = True
            if previous_status == "manual_required" and previous_snapshot.get("manual_required"):
                current_snapshot["manifest_known"] = False
                current_snapshot["manual_required"] = True
            for key in ("old_parent_id", "old_cid"):
                previous_value = str(previous_snapshot.get(key, "") or "").strip()
                if previous_value and (
                    previous_status == "pending"
                    or not str(current_snapshot.get(key, "") or "").strip()
                ):
                    current_snapshot[key] = previous_value
        effective_old_path = str(current[3] or "")
        if previous_status == "pending":
            effective_old_path = str(previous[1] or "")
        current_snapshot["old_path"] = effective_old_path
        reconcile_required = bool(int(current[7] or 0)) or bool(int(previous[3] or 0))
        current_snapshot["needs_reconcile"] = reconcile_required
        if (
            previous_status == "pending"
            and not reconcile_required
            and effective_old_path == str(current[4] or "")
        ):
            cursor.execute(
                """
                UPDATE monitor_change_events
                SET status = 'completed', completed_at = ?, updated_at = ?,
                    last_error = ?, needs_reconcile = 0
                WHERE id = ? AND status = 'pending'
                """,
                (now, now, "continuous_chain_noop", int(current[0] or 0)),
            )
            cursor.execute(
                """
                UPDATE monitor_change_events
                SET status = 'completed', completed_at = ?, updated_at = ?,
                    last_error = ?
                WHERE id = ? AND status = 'pending'
                """,
                (now, now, f"merged_into:{int(current[0] or 0)}", int(previous[0] or 0)),
            )
            continue
        effective_operation = str(current[2] or "")
        if normalize_relative_path(os.path.dirname(effective_old_path)) != normalize_relative_path(
            os.path.dirname(str(current[4] or ""))
        ):
            effective_operation = "move"
        cursor.execute(
            """
            UPDATE monitor_change_events
            SET operation = ?, old_path = ?, entry_snapshot_json = ?, needs_reconcile = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                effective_operation,
                effective_old_path,
                safe_json_dumps(current_snapshot),
                1 if reconcile_required else 0,
                now,
                int(current[0] or 0),
            ),
        )
        cursor.execute(
            """
            UPDATE monitor_change_events
            SET status = 'completed', completed_at = ?, updated_at = ?,
                last_error = ?
            WHERE id = ? AND status IN ('pending', 'manual_required')
            """,
            (now, now, f"merged_into:{int(current[0] or 0)}", int(previous[0] or 0)),
        )


def _enqueue_task_names(task_names: Iterable[str]) -> None:
    from .monitor import queue_monitor_job

    for task_name in sorted({str(name or "").strip() for name in task_names if str(name or "").strip()}):
        queue_monitor_job(task_name, "change", payload={"mode": "change"})


async def _list_change_remote_dir(
    cfg: Dict[str, Any],
    remote_path: str,
    task: Dict[str, Any],
    folder_cid: str,
) -> Tuple[str, List[Dict[str, Any]]]:
    normalized_cid = str(folder_cid or "").strip()
    if not normalized_cid or normalized_cid == "0":
        raise RuntimeError("精准同步缺少受影响目录 CID，拒绝按路径遍历监控根目录")
    return await list_remote_dir(
        cfg,
        remote_path,
        True,
        task,
        folder_cid=normalized_cid,
    )


def _summarize_confirmed_event_status(rows: Sequence[Any], fallback: str) -> str:
    statuses = {str(row[1] or "").strip() for row in rows if str(row[1] or "").strip()}
    if "pending" in statuses:
        needs_reconcile = any(
            str(row[1] or "").strip() == "pending" and bool(int(row[2] or 0))
            for row in rows
        )
        return "reconcile_queued" if needs_reconcile else "queued"
    if "processing" in statuses:
        return "processing"
    if "failed" in statuses:
        return "failed"
    if "manual_required" in statuses:
        return "manual_required"
    if statuses and statuses == {"completed"}:
        return "completed"
    if "prepared" in statuses:
        return "prepared"
    return str(fallback or "unavailable")


def confirm_monitor_change_events(
    prepared: Dict[str, Any],
    *,
    succeeded: bool,
    enqueue: bool = True,
    error: str = "",
) -> Dict[str, Any]:
    event_ids = sorted(
        {
            int(value or 0)
            for value in (prepared.get("event_ids", []) if isinstance(prepared, dict) else [])
            if int(value or 0) > 0
        }
    )
    if not event_ids:
        return {
            "status": str((prepared or {}).get("status", "unavailable") or "unavailable"),
            "matched_tasks": list((prepared or {}).get("matched_tasks", []) or []),
            "event_count": 0,
            "event_ids": [],
        }
    now = now_text()
    placeholders = ",".join("?" for _ in event_ids)
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            UPDATE monitor_change_events
            SET status = ?, needs_reconcile = ?, confirmed_at = ?, updated_at = ?,
                next_retry_at = 0, last_error = ?
            WHERE id IN ({placeholders}) AND status = 'prepared'
            """,
            (
                "pending",
                0 if succeeded else 1,
                now,
                now,
                "" if succeeded else str(error or "远端操作结果未确认")[:1000],
                *event_ids,
            ),
        )
        if succeeded:
            _merge_continuous_path_events(conn, event_ids)
        cursor.execute(
            f"SELECT task_name, status, needs_reconcile, entry_snapshot_json FROM monitor_change_events WHERE id IN ({placeholders})",
            tuple(event_ids),
        )
        rows = cursor.fetchall()
        task_names = [
            str(row[0] or "")
            for row in rows
            if str(row[0] or "").strip() and str(row[1] or "").strip() == "pending"
        ]
        matched_names = [str(row[0] or "") for row in rows if str(row[0] or "").strip()]
        response_status = _summarize_confirmed_event_status(
            rows,
            "queued" if succeeded else "reconcile_queued",
        )
        if succeeded and any(
            str(row[1] or "").strip() == "pending"
            and not bool(int(row[2] or 0))
            and bool(safe_json_loads(row[3], {}).get("manual_required"))
            for row in rows
        ):
            response_status = "manual_required"
        conn.commit()
    if enqueue and task_names:
        _enqueue_task_names(task_names)
    return {
        "status": response_status,
        "matched_tasks": sorted(set(matched_names) or set((prepared or {}).get("matched_tasks", []) or [])),
        "event_count": len(event_ids),
        "event_ids": event_ids,
    }


def _task_by_name(cfg: Dict[str, Any], task_name: str) -> Dict[str, Any]:
    for raw_task in cfg.get("monitor_tasks", []) or []:
        task = normalize_task(raw_task or {})
        if str(task.get("name", "") or "").strip() == str(task_name or "").strip():
            return task
    return {}


def _provider_path_is_safe(path: str) -> bool:
    normalized = normalize_relative_path(path)
    return bool(normalized) and all(part not in {".", ".."} for part in normalized.split("/"))


def _build_event_change_plan(
    cfg: Dict[str, Any],
    task: Dict[str, Any],
    event: Dict[str, Any],
    snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    operation = _normalize_operation(event.get("operation", ""))
    old_path = normalize_relative_path(event.get("old_path", ""))
    new_path = normalize_relative_path(event.get("new_path", ""))
    required_old = operation in {"copy", "move", "rename", "delete"}
    required_new = operation in {"create", "copy", "move", "rename"}
    if required_old and not _provider_path_is_safe(old_path):
        raise RuntimeError(f"精准同步旧路径无效或不完整: {old_path or '--'}")
    if required_new and not _provider_path_is_safe(new_path):
        raise RuntimeError(f"精准同步新路径无效或不完整: {new_path or '--'}")

    old_context = _task_path_context(cfg, task, old_path) if old_path else {}
    new_context = _task_path_context(cfg, task, new_path) if new_path else {}
    if operation == "rename":
        if not old_context or not new_context:
            raise RuntimeError("精准同步重命名路径不完整，已保留旧 STRM")
        if normalize_relative_path(os.path.dirname(old_path)) != normalize_relative_path(os.path.dirname(new_path)):
            raise RuntimeError("精准同步重命名父目录不一致，已保留旧 STRM")
    if operation == "move":
        old_parent_id = str(snapshot.get("old_parent_id", "") or "").strip()
        new_parent_id = str(snapshot.get("new_parent_id", "") or "").strip()
        old_parent_path = normalize_relative_path(os.path.dirname(old_path))
        new_parent_path = normalize_relative_path(os.path.dirname(new_path))
        same_parent_path = old_parent_path == new_parent_path
        if not same_parent_path:
            if not old_parent_id or not new_parent_id:
                raise RuntimeError("精准同步跨目录移动缺少父目录 ID，已保留旧 STRM")
            if old_parent_id == new_parent_id:
                raise RuntimeError("精准同步移动父目录路径与目录 ID 不一致，已保留旧 STRM")
        elif old_parent_id and new_parent_id and old_parent_id != new_parent_id:
            raise RuntimeError("精准同步移动父目录路径与目录 ID 不一致，已保留旧 STRM")

    remove_old = operation in {"delete", "rename", "move"} and bool(old_context)
    add_new = operation in {"create", "copy", "rename", "move"} and bool(new_context)
    if remove_old and add_new:
        action = "replace"
    elif remove_old:
        action = "delete"
    elif add_new:
        action = "add"
    else:
        action = "noop"
    plan = {
        "operation": operation,
        "action": action,
        "old_path": old_path,
        "new_path": new_path,
        "old_context": old_context,
        "new_context": new_context,
        "remove_old": remove_old,
        "add_new": add_new,
        "is_dir": bool(snapshot.get("is_dir", False)),
        "size": _nonnegative_int(snapshot.get("size", 0)),
    }
    if plan["is_dir"]:
        indexed_files, indexed_dirs = _build_folder_manifest_plan(
            cfg,
            task,
            old_path,
            new_path,
            snapshot,
            add_new=add_new,
        )
        plan["indexed_files"] = indexed_files
        plan["indexed_dirs"] = indexed_dirs
    return plan


def _capture_strm_file_state(
    journal: Optional[Dict[str, Optional[bytes]]],
    local_rel_path: str,
) -> None:
    if journal is None or local_rel_path in journal:
        return
    target = managed_strm_file_path(local_rel_path, root=STRM_ROOT)
    if not os.path.exists(target):
        journal[local_rel_path] = None
        return
    with open(target, "rb") as handle:
        journal[local_rel_path] = handle.read()


def _restore_strm_file_states(journal: Dict[str, Optional[bytes]]) -> List[str]:
    errors: List[str] = []
    for local_rel_path, original_content in journal.items():
        try:
            target = managed_strm_file_path(local_rel_path, root=STRM_ROOT)
            if original_content is None:
                if os.path.exists(target):
                    os.remove(target)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as handle:
                handle.write(original_content)
        except Exception as exc:
            errors.append(f"{local_rel_path}: {exc}")
    return errors


def _write_strm_file(
    local_rel_path: str,
    content: str,
    *,
    journal: Optional[Dict[str, Optional[bytes]]] = None,
) -> bool:
    _capture_strm_file_state(journal, local_rel_path)
    target = managed_strm_file_path(local_rel_path, root=STRM_ROOT)
    old_content = ""
    if os.path.exists(target):
        with open(target, "r", encoding="utf-8", errors="ignore") as handle:
            old_content = str(handle.read() or "").strip()
    next_content = str(content or "").strip()
    if old_content == next_content:
        return False
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(next_content)
    return True


def _delete_unreferenced_strm_file(
    conn: Any,
    local_rel_path: str,
    *,
    journal: Optional[Dict[str, Optional[bytes]]] = None,
) -> bool:
    row = conn.execute(
        "SELECT 1 FROM monitor_files WHERE local_rel_path = ? LIMIT 1",
        (local_rel_path,),
    ).fetchone()
    if row:
        return False
    _capture_strm_file_state(journal, local_rel_path)
    return delete_managed_strm_file(local_rel_path, root=STRM_ROOT)


def _remove_file_path(
    conn: Any,
    task: Dict[str, Any],
    context: Dict[str, str],
    *,
    journal: Optional[Dict[str, Optional[bytes]]] = None,
) -> Dict[str, int]:
    local_rel_path = context["local_rel_path"]
    conn.execute(
        "DELETE FROM monitor_files WHERE task_name = ? AND local_rel_path = ?",
        (str(task.get("name", "") or ""), local_rel_path),
    )
    deleted = 1 if _delete_unreferenced_strm_file(conn, local_rel_path, journal=journal) else 0
    return {"deleted": deleted}


def _remove_folder_path(
    conn: Any,
    task: Dict[str, Any],
    context: Dict[str, str],
    *,
    journal: Optional[Dict[str, Optional[bytes]]] = None,
) -> Dict[str, int]:
    task_name = str(task.get("name", "") or "")
    local_prefix = context["local_rel_path"]
    scope_like = _sql_like_descendant_pattern(local_prefix)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT local_rel_path FROM monitor_files
        WHERE task_name = ? AND (local_rel_path = ? OR local_rel_path LIKE ? ESCAPE '\\')
        ORDER BY local_rel_path DESC
        """,
        (task_name, local_prefix, scope_like),
    )
    local_rel_paths = [str(row[0] or "") for row in cursor.fetchall() if str(row[0] or "")]
    cursor.execute(
        """
        DELETE FROM monitor_files
        WHERE task_name = ? AND (local_rel_path = ? OR local_rel_path LIKE ? ESCAPE '\\')
        """,
        (task_name, local_prefix, scope_like),
    )
    deleted = sum(
        1
        for local_rel_path in local_rel_paths
        if _delete_unreferenced_strm_file(conn, local_rel_path, journal=journal)
    )
    dir_rel = context["remote_rel_path"]
    dir_like = _sql_like_descendant_pattern(dir_rel)
    cursor.execute(
        """
        DELETE FROM monitor_dirs
        WHERE task_name = ? AND (dir_rel_path = ? OR dir_rel_path LIKE ? ESCAPE '\\')
        """,
        (task_name, dir_rel, dir_like),
    )
    remove_empty_parent_dirs(
        os.path.join(STRM_ROOT, local_prefix),
        os.path.join(STRM_ROOT, context["task_root"]),
    )
    return {"deleted": deleted}


def _remove_path(
    conn: Any,
    cfg: Dict[str, Any],
    task: Dict[str, Any],
    provider_path: str,
    is_dir: bool,
    *,
    journal: Optional[Dict[str, Optional[bytes]]] = None,
) -> Dict[str, int]:
    context = _task_path_context(cfg, task, provider_path)
    if not context:
        return {"deleted": 0}
    if is_dir:
        return _remove_folder_path(conn, task, context, journal=journal)
    return _remove_file_path(conn, task, context, journal=journal)


def _file_passes_filters(cfg: Dict[str, Any], task: Dict[str, Any], provider_path: str, size: int) -> bool:
    name = basename(provider_path)
    if not is_video_file(name, get_user_extensions(cfg)):
        return False
    min_bytes = _task_min_file_size_bytes(task)
    return min_bytes <= 0 or _nonnegative_int(size) >= min_bytes


def _add_file_path(
    conn: Any,
    cfg: Dict[str, Any],
    task: Dict[str, Any],
    provider_path: str,
    *,
    size: int = 0,
    modified_at: str = "",
    journal: Optional[Dict[str, Optional[bytes]]] = None,
) -> Dict[str, int]:
    context = _task_path_context(cfg, task, provider_path)
    if not context or not _file_passes_filters(cfg, task, provider_path, size):
        return {"generated": 0, "skipped": 1}
    _validate_shared_output_conflicts(conn, cfg, task, [provider_path])
    url = build_strm_play_url(cfg, context["remote_path"])
    generated = 1 if _write_strm_file(context["local_rel_path"], url, journal=journal) else 0
    conn.execute(
        """
        INSERT OR REPLACE INTO monitor_files(
            task_name, local_rel_path, remote_rel_path, remote_modified, file_size
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            str(task.get("name", "") or ""),
            context["local_rel_path"],
            context["remote_rel_path"],
            str(modified_at or ""),
            _nonnegative_int(size),
        ),
    )
    return {"generated": generated, "skipped": 0 if generated else 1}


def _upsert_clean_monitor_dir(
    conn: Any,
    task: Dict[str, Any],
    dir_rel_path: str,
    remote_modified: str = "",
    entry_modified: str = "",
) -> None:
    task_name = str(task.get("name", "") or "")
    normalized_rel = normalize_relative_path(dir_rel_path)
    conn.execute(
        """
        INSERT INTO monitor_dirs(
            task_name, dir_rel_path, remote_modified, entry_modified,
            needs_rescan, missing_confirmations
        ) VALUES (?, ?, ?, ?, 0, 0)
        ON CONFLICT(task_name, dir_rel_path) DO UPDATE SET
            remote_modified = CASE
                WHEN excluded.remote_modified <> '' THEN excluded.remote_modified
                ELSE monitor_dirs.remote_modified
            END,
            entry_modified = CASE
                WHEN excluded.entry_modified <> '' THEN excluded.entry_modified
                ELSE monitor_dirs.entry_modified
            END,
            needs_rescan = 0,
            missing_confirmations = 0
        """,
        (task_name, normalized_rel, str(remote_modified or ""), str(entry_modified or "")),
    )


def _sync_event_baselines(
    conn: Any,
    cfg: Dict[str, Any],
    task: Dict[str, Any],
    plan: Dict[str, Any],
) -> None:
    if not plan.get("is_dir") or not plan.get("add_new"):
        return
    for item in plan.get("indexed_dirs", []):
        target_path = str(item.get("target_path", "") or "")
        context = _task_path_context(cfg, task, target_path)
        if not context:
            raise RuntimeError(f"精准同步索引清单目标目录越界: {target_path or '--'}")
        _upsert_clean_monitor_dir(
            conn,
            task,
            context["remote_rel_path"],
            str(item.get("remote_modified", "") or ""),
            str(item.get("entry_modified", "") or ""),
        )
    new_context = plan.get("new_context") if isinstance(plan.get("new_context"), dict) else {}
    if new_context:
        _upsert_clean_monitor_dir(conn, task, str(new_context.get("remote_rel_path", "") or ""))


def _manifest_target_path(old_root: str, new_root: str, source_path: str) -> str:
    old_normalized = normalize_relative_path(old_root)
    new_normalized = normalize_relative_path(new_root)
    source_normalized = normalize_relative_path(source_path)
    if source_normalized == old_normalized:
        suffix = ""
    elif source_normalized.startswith(old_normalized + "/"):
        suffix = source_normalized[len(old_normalized) + 1 :]
    else:
        return ""
    return join_relative_path(new_normalized, suffix)


def _normalize_scraper_job_event_for_processing(
    conn: Any,
    event: Dict[str, Any],
    snapshot: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    source_action = str(event.get("source_action", "") or "").strip()
    operation = str(event.get("operation", "") or "").strip()
    if not source_action.startswith("scraper-job:") or operation not in {"rename", "move"}:
        return event, snapshot

    effective_event = dict(event)
    effective_snapshot = dict(snapshot)
    rewrites = _load_scraper_job_path_rewrites(
        conn,
        str(event.get("task_name", "") or ""),
        source_action,
        statuses=("completed", "manual_required"),
        before_event_id=max(0, int(event.get("id", 0) or 0)),
        directories_only=True,
    )
    for key in ("old_path", "new_path"):
        effective_path = normalize_relative_path(str(effective_event.get(key, "") or ""))
        for old_root, new_root in rewrites:
            projected_path = _manifest_target_path(old_root, new_root, effective_path)
            if projected_path:
                effective_path = projected_path
        effective_event[key] = effective_path
        effective_snapshot[key] = effective_path

    old_parent_id = str(effective_snapshot.get("old_parent_id", "") or "").strip()
    new_parent_id = str(effective_snapshot.get("new_parent_id", "") or "").strip()
    if old_parent_id and new_parent_id:
        effective_event["operation"] = "rename" if old_parent_id == new_parent_id else "move"
    effective_snapshot["parent_path"] = normalize_relative_path(
        os.path.dirname(str(effective_event.get("old_path", "") or ""))
    )
    return effective_event, effective_snapshot


def _build_folder_manifest_plan(
    cfg: Dict[str, Any],
    task: Dict[str, Any],
    old_root: str,
    new_root: str,
    snapshot: Dict[str, Any],
    *,
    add_new: bool,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    old_normalized = normalize_relative_path(old_root)
    new_normalized = normalize_relative_path(new_root)
    planned: Dict[str, List[Dict[str, Any]]] = {"indexed_files": [], "indexed_dirs": []}
    for key in ("indexed_files", "indexed_dirs"):
        raw_items = snapshot.get(key, [])
        if raw_items is None:
            raw_items = []
        if not isinstance(raw_items, list):
            raise RuntimeError(f"精准同步索引清单格式无效: {key}")
        seen_paths: Set[str] = set()
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                raise RuntimeError(f"精准同步索引清单条目无效: {key}")
            source_path = normalize_relative_path(str(raw_item.get("path", "") or ""))
            is_root = bool(old_normalized and source_path == old_normalized)
            is_descendant = bool(
                old_normalized and source_path.startswith(f"{old_normalized}/")
            )
            if (
                not _provider_path_is_safe(source_path)
                or not (is_root or is_descendant)
                or (key == "indexed_files" and is_root)
                or source_path in seen_paths
            ):
                raise RuntimeError(
                    f"精准同步索引清单路径无效或越界: {source_path or '--'}"
                )
            seen_paths.add(source_path)
            target_path = ""
            if add_new:
                target_path = _manifest_target_path(
                    old_normalized,
                    new_normalized,
                    source_path,
                )
                target_is_root = bool(new_normalized and target_path == new_normalized)
                target_is_descendant = bool(
                    new_normalized and target_path.startswith(f"{new_normalized}/")
                )
                if (
                    not _provider_path_is_safe(target_path)
                    or not (target_is_root or target_is_descendant)
                    or (key == "indexed_files" and target_is_root)
                    or not _task_path_context(cfg, task, target_path)
                ):
                    raise RuntimeError(
                        f"精准同步索引清单目标路径无效或越界: {target_path or '--'}"
                    )
            item = dict(raw_item)
            item["source_path"] = source_path
            item["target_path"] = target_path
            planned[key].append(item)
    return planned["indexed_files"], planned["indexed_dirs"]


def _add_indexed_folder(
    conn: Any,
    cfg: Dict[str, Any],
    task: Dict[str, Any],
    plan: Dict[str, Any],
    *,
    journal: Optional[Dict[str, Optional[bytes]]] = None,
) -> Dict[str, int]:
    generated = 0
    skipped = 0
    file_count = 0
    for item in plan.get("indexed_files", []):
        target_path = str(item.get("target_path", "") or "")
        result = _add_file_path(
            conn,
            cfg,
            task,
            target_path,
            size=_nonnegative_int(item.get("size", 0)),
            modified_at=str(item.get("modified_at", "") or ""),
            journal=journal,
        )
        generated += int(result.get("generated", 0) or 0)
        skipped += int(result.get("skipped", 0) or 0)
        file_count += 1
    return {"generated": generated, "skipped": skipped, "file_count": file_count, "directory_count": 0}


def _validate_shared_output_conflicts(
    conn: Any,
    cfg: Dict[str, Any],
    task: Dict[str, Any],
    provider_paths: Iterable[str],
) -> None:
    task_name = str(task.get("name", "") or "").strip()
    for provider_path in sorted({normalize_relative_path(path) for path in provider_paths if path}):
        context = _task_path_context(cfg, task, provider_path)
        if not context:
            continue
        rows = conn.execute(
            """
            SELECT task_name, remote_rel_path
            FROM monitor_files
            WHERE local_rel_path = ? AND task_name <> ?
            ORDER BY task_name
            """,
            (context["local_rel_path"], task_name),
        ).fetchall()
        for row in rows:
            other_name = str(row[0] or "").strip()
            other_task = _task_by_name(cfg, other_name)
            other_provider_path = _provider_path_from_index(
                cfg,
                other_task,
                str(row[1] or ""),
            ) if other_task else ""
            other_context = (
                _task_path_context(cfg, other_task, other_provider_path)
                if other_provider_path
                else {}
            )
            if not other_context or other_context["remote_path"] != context["remote_path"]:
                raise RuntimeError(
                    f"精准同步共享 STRM 输出冲突: {context['local_rel_path']} 已被监控任务 {other_name or '--'} 指向其他路径"
                )


def _event_output_provider_paths(
    cfg: Dict[str, Any],
    task: Dict[str, Any],
    plan: Dict[str, Any],
) -> List[str]:
    if not plan.get("add_new"):
        return []
    if not plan.get("is_dir"):
        provider_path = str(plan.get("new_path", "") or "")
        return [provider_path] if _file_passes_filters(
            cfg,
            task,
            provider_path,
            _nonnegative_int(plan.get("size", 0)),
        ) else []
    paths: List[str] = []
    for item in plan.get("indexed_files", []):
        provider_path = str(item.get("target_path", "") or "")
        if _file_passes_filters(cfg, task, provider_path, _nonnegative_int(item.get("size", 0))):
            paths.append(provider_path)
    return paths


def _validate_event_outputs(
    conn: Any,
    cfg: Dict[str, Any],
    task: Dict[str, Any],
    plan: Dict[str, Any],
) -> None:
    _validate_shared_output_conflicts(
        conn,
        cfg,
        task,
        _event_output_provider_paths(cfg, task, plan),
    )


def _build_committed_change_detail(
    plan: Dict[str, Any],
    stats: Dict[str, Any],
    *,
    effective_new_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    old_context = plan.get("old_context") if isinstance(plan.get("old_context"), dict) else {}
    if effective_new_context is None:
        new_context = plan.get("new_context") if isinstance(plan.get("new_context"), dict) else {}
    else:
        new_context = effective_new_context
    deleted = _nonnegative_int(stats.get("deleted", 0))
    generated = _nonnegative_int(stats.get("generated", 0))

    if plan.get("is_dir"):
        return {
            "kind": "folder",
            "operation": str(plan.get("operation", "") or ""),
            "old_path": str(old_context.get("local_rel_path", "") or ""),
            "new_path": str(new_context.get("local_rel_path", "") or ""),
            "deleted": deleted,
            "generated": generated,
        }

    changes: List[Dict[str, str]] = []
    old_local_path = str(old_context.get("local_rel_path", "") or "")
    new_local_path = str(new_context.get("local_rel_path", "") or "")
    if deleted > 0 and old_local_path:
        changes.append({"action": "delete", "path": f"{old_local_path}.strm"})
    if generated > 0 and new_local_path:
        changes.append({"action": "generate", "path": f"{new_local_path}.strm"})
    return {"kind": "file", "changes": changes} if changes else {}


async def _apply_precise_event(
    conn: Any,
    cfg: Dict[str, Any],
    task: Dict[str, Any],
    event: Dict[str, Any],
    *,
    journal: Optional[Dict[str, Optional[bytes]]] = None,
) -> Dict[str, Any]:
    snapshot = safe_json_loads(event.get("entry_snapshot_json", "{}"), {})
    if not isinstance(snapshot, dict):
        snapshot = {}
    event, snapshot = _normalize_scraper_job_event_for_processing(conn, event, snapshot)
    plan = _build_event_change_plan(cfg, task, event, snapshot)
    _validate_event_outputs(conn, cfg, task, plan)
    operation = str(plan["operation"])
    old_path = str(plan["old_path"])
    new_path = str(plan["new_path"])
    is_dir = bool(plan["is_dir"])
    stats = {
        "generated": 0,
        "skipped": 0,
        "deleted": 0,
        "file_count": 0,
        "directory_count": 0,
        "manual_required": 1 if snapshot.get("manual_required") and plan["add_new"] else 0,
    }

    if plan["remove_old"]:
        removed = _remove_path(conn, cfg, task, old_path, is_dir, journal=journal)
        stats["deleted"] += int(removed.get("deleted", 0) or 0)

    if plan["add_new"]:
        if is_dir:
            if operation == "create":
                pass
            else:
                added = _add_indexed_folder(conn, cfg, task, plan, journal=journal)
                for key in ("generated", "skipped", "file_count", "directory_count"):
                    stats[key] += int(added.get(key, 0) or 0)
        else:
            added = _add_file_path(
                conn,
                cfg,
                task,
                new_path,
                size=_nonnegative_int(snapshot.get("size", 0)),
                modified_at=str(snapshot.get("modified_at", "") or ""),
                journal=journal,
            )
            stats["generated"] += int(added.get("generated", 0) or 0)
            stats["skipped"] += int(added.get("skipped", 0) or 0)
            stats["file_count"] += 1

    _sync_event_baselines(conn, cfg, task, plan)
    stats["change_detail"] = _build_committed_change_detail(plan, stats)
    return stats


async def _list_parent_entry(
    cfg: Dict[str, Any],
    task: Dict[str, Any],
    provider_path: str,
    parent_cid: str,
    *,
    entry_id: str = "",
    is_dir: bool = False,
) -> Tuple[bool, Dict[str, Any]]:
    context = _task_path_context(cfg, task, provider_path)
    if not context:
        return False, {}
    parent_remote = normalize_remote_path(os.path.dirname(context["remote_path"]))
    if parent_remote == context["scan_path"]:
        raise RuntimeError("局部校正禁止读取整个监控根目录")
    if not is_subpath(parent_remote, context["scan_path"]):
        return False, {}
    _, items = await _list_change_remote_dir(cfg, parent_remote, task, parent_cid)
    target_name = basename(provider_path)
    normalized_entry_id = str(entry_id or "").strip()
    name_match: Dict[str, Any] = {}
    for raw_item in items:
        item = raw_item if isinstance(raw_item, dict) else {}
        if _snapshot_bool(item.get("is_dir")) != bool(is_dir):
            continue
        item_id = str(item.get("id", "") or item.get("cid", "") or item.get("fid", "") or "").strip()
        if normalized_entry_id and item_id == normalized_entry_id:
            return True, item
        if not normalized_entry_id and str(item.get("name", "") or "").strip() == target_name:
            name_match = item
    return (True, name_match) if name_match else (False, {})


async def _reconcile_event(
    conn: Any,
    cfg: Dict[str, Any],
    task: Dict[str, Any],
    event: Dict[str, Any],
    *,
    journal: Optional[Dict[str, Optional[bytes]]] = None,
) -> Dict[str, Any]:
    snapshot = safe_json_loads(event.get("entry_snapshot_json", "{}"), {})
    if not isinstance(snapshot, dict):
        snapshot = {}
    event, snapshot = _normalize_scraper_job_event_for_processing(conn, event, snapshot)
    plan = _build_event_change_plan(cfg, task, event, snapshot)
    operation = str(plan["operation"])
    is_dir = bool(plan["is_dir"])
    old_path = str(plan["old_path"])
    new_path = str(plan["new_path"])
    stats = {
        "generated": 0,
        "skipped": 0,
        "deleted": 0,
        "file_count": 0,
        "directory_count": 0,
        "manual_required": 0,
    }
    entry_id = str(snapshot.get("id", "") or "").strip()
    if operation in {"create", "copy"} and is_dir:
        entry_id = str(snapshot.get("new_cid", "") or entry_id).strip()
    if not entry_id:
        raise RuntimeError("局部校正缺少显式条目 ID，已保留旧 STRM")

    probe_path = ""
    parent_cid = ""
    probe_is_old = False
    if operation == "delete" and plan["old_context"]:
        probe_path = old_path
        parent_cid = str(snapshot.get("old_parent_id", "") or "")
        probe_is_old = True
    elif operation in {"create", "copy"} and plan["new_context"]:
        probe_path = new_path
        parent_cid = str(snapshot.get("new_parent_id", "") or "")
    elif operation in {"rename", "move"}:
        if plan["new_context"]:
            probe_path = new_path
            parent_cid = str(snapshot.get("new_parent_id", "") or "")
        elif plan["old_context"]:
            probe_path = old_path
            parent_cid = str(snapshot.get("old_parent_id", "") or "")
            probe_is_old = True
    if not probe_path:
        return stats

    exists, remote_item = await _list_parent_entry(
        cfg,
        task,
        probe_path,
        parent_cid,
        entry_id=entry_id,
        is_dir=is_dir,
    )
    actual_path = ""
    if exists:
        actual_name = str(remote_item.get("name", "") or "").strip()
        if not actual_name:
            raise RuntimeError(f"局部校正条目缺少名称: {entry_id}")
        actual_path = normalize_relative_path(join_relative_path(os.path.dirname(probe_path), actual_name))

    remove_old = False
    add_path = ""
    if operation == "delete":
        remove_old = not exists and bool(plan["old_context"])
        if exists and actual_path != old_path:
            remove_old = bool(plan["old_context"])
            add_path = actual_path
    elif operation in {"create", "copy"}:
        if not exists:
            raise RuntimeError(f"局部校正未找到目标条目: {new_path}")
        add_path = actual_path
    elif operation in {"rename", "move"}:
        if exists:
            remove_old = bool(plan["old_context"] and actual_path != old_path)
            add_path = actual_path
        elif probe_is_old and plan["old_context"] and not plan["new_context"]:
            remove_old = True
        else:
            raise RuntimeError(f"局部校正未找到目标条目: {new_path or old_path}")

    add_context = _task_path_context(cfg, task, add_path) if add_path else {}
    effective_plan: Dict[str, Any] = {}
    if add_context:
        effective_plan = dict(plan)
        effective_plan["new_path"] = add_path
        effective_plan["new_context"] = add_context
        effective_plan["add_new"] = True
        effective_plan["size"] = _nonnegative_int(
            remote_item.get("size", snapshot.get("size", 0))
        )
        if is_dir:
            indexed_files, indexed_dirs = _build_folder_manifest_plan(
                cfg,
                task,
                old_path,
                add_path,
                snapshot,
                add_new=True,
            )
            effective_plan["indexed_files"] = indexed_files
            effective_plan["indexed_dirs"] = indexed_dirs
        _validate_event_outputs(conn, cfg, task, effective_plan)

    if remove_old:
        removed = _remove_path(conn, cfg, task, old_path, is_dir, journal=journal)
        stats["deleted"] += int(removed.get("deleted", 0) or 0)

    if add_context:
        if is_dir:
            if operation != "create":
                added = _add_indexed_folder(conn, cfg, task, effective_plan, journal=journal)
                for key in ("generated", "skipped", "file_count", "directory_count"):
                    stats[key] += int(added.get(key, 0) or 0)
            # A failed delete can resolve to the same folder ID under a new
            # name.  Delete events do not carry manual_required at prepare
            # time, so preserve the warning whenever the captured source
            # manifest was incomplete or unknown.
            stats["manual_required"] = 1 if (
                snapshot.get("manual_required")
                or snapshot.get("manifest_known") is not True
            ) else 0
            _sync_event_baselines(conn, cfg, task, effective_plan)
        else:
            added = _add_file_path(
                conn,
                cfg,
                task,
                add_path,
                size=_nonnegative_int(remote_item.get("size", snapshot.get("size", 0))),
                modified_at=str(remote_item.get("modified", "") or remote_item.get("modified_at", "") or ""),
                journal=journal,
            )
            stats["generated"] += int(added.get("generated", 0) or 0)
            stats["skipped"] += int(added.get("skipped", 0) or 0)
            stats["file_count"] += 1
    stats["change_detail"] = _build_committed_change_detail(
        plan,
        stats,
        effective_new_context=add_context,
    )
    return stats


def _load_ready_events(
    conn: Any,
    *,
    task_name: str = "",
    event_ids: Optional[Sequence[int]] = None,
) -> List[Dict[str, Any]]:
    clauses = ["(status = 'pending' OR (status = 'failed' AND retry_count < ? AND next_retry_at <= ?))"]
    values: List[Any] = [MONITOR_CHANGE_MAX_RETRIES, time.time()]
    normalized_task_name = str(task_name or "").strip()
    if normalized_task_name:
        clauses.append("task_name = ?")
        values.append(normalized_task_name)
    normalized_ids = sorted({int(value or 0) for value in (event_ids or []) if int(value or 0) > 0})
    if normalized_ids:
        placeholders = ",".join("?" for _ in normalized_ids)
        clauses.append(f"id IN ({placeholders})")
        values.extend(normalized_ids)
    cursor = conn.execute(
        f"SELECT * FROM monitor_change_events WHERE {' AND '.join(clauses)} ORDER BY id",
        tuple(values),
    )
    return [sqlite_row_to_dict(row) for row in cursor.fetchall()]


async def process_monitor_change_events(
    task_name: str = "",
    *,
    cfg: Optional[Dict[str, Any]] = None,
    event_ids: Optional[Sequence[int]] = None,
) -> Dict[str, Any]:
    active_cfg = cfg or get_config()
    ensure_db()
    result: Dict[str, Any] = {
        "completed": 0,
        "failed": 0,
        "generated": 0,
        "skipped": 0,
        "deleted": 0,
        "directory_count": 0,
        "file_count": 0,
        "manual_required": 0,
        "errors": [],
        "change_details": [],
    }
    with db_connection() as conn:
        events = _load_ready_events(conn, task_name=task_name, event_ids=event_ids)
        for event in events:
            event_id = int(event.get("id", 0) or 0)
            task = _task_by_name(active_cfg, str(event.get("task_name", "") or ""))
            file_journal: Dict[str, Optional[bytes]] = {}
            conn.execute(
                """
                UPDATE monitor_change_events
                SET status = 'processing', processor_revision = ?, updated_at = ?
                WHERE id = ?
                """,
                (MONITOR_CHANGE_HANDLER_REVISION, now_text(), event_id),
            )
            conn.commit()
            try:
                if not task:
                    raise RuntimeError(f"监控任务不存在: {event.get('task_name', '')}")
                if bool(int(event.get("needs_reconcile", 0) or 0)):
                    stats = await _reconcile_event(
                        conn,
                        active_cfg,
                        task,
                        event,
                        journal=file_journal,
                    )
                else:
                    stats = await _apply_precise_event(
                        conn,
                        active_cfg,
                        task,
                        event,
                        journal=file_journal,
                    )
                completed_at = now_text()
                manual_required = bool(int(stats.get("manual_required", 0) or 0))
                conn.execute(
                    """
                    UPDATE monitor_change_events
                    SET status = ?, updated_at = ?, completed_at = ?,
                        last_error = ?, needs_reconcile = 0,
                        directory_count = ?, file_count = ?
                    WHERE id = ?
                    """,
                    (
                        "manual_required" if manual_required else "completed",
                        completed_at,
                        "" if manual_required else completed_at,
                        "需手动监控" if manual_required else "",
                        max(0, int(stats.get("directory_count", 0) or 0)),
                        max(0, int(stats.get("file_count", 0) or 0)),
                        event_id,
                    ),
                )
                conn.commit()
                result["completed"] += 1
                change_detail = stats.get("change_detail")
                if isinstance(change_detail, dict) and change_detail:
                    result["change_details"].append(change_detail)
                for key in ("generated", "skipped", "deleted", "directory_count", "file_count", "manual_required"):
                    result[key] += int(stats.get(key, 0) or 0)
            except Exception as exc:
                conn.rollback()
                restore_errors = _restore_strm_file_states(file_journal)
                error_text = str(exc)
                if restore_errors:
                    error_text = f"{error_text}; STRM 回滚失败: {'; '.join(restore_errors)}"
                retry_count = max(0, int(event.get("retry_count", 0) or 0)) + 1
                backoff = min(3600, MONITOR_CHANGE_RETRY_BASE_SECONDS * (2 ** max(0, retry_count - 1)))
                conn.execute(
                    """
                    UPDATE monitor_change_events
                    SET status = 'failed', retry_count = ?, next_retry_at = ?,
                        last_error = ?, processor_revision = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        retry_count,
                        time.time() + backoff,
                        error_text[:1000],
                        MONITOR_CHANGE_HANDLER_REVISION,
                        now_text(),
                        event_id,
                    ),
                )
                conn.commit()
                result["failed"] += 1
                result["errors"].append({"event_id": event_id, "error": error_text})
    return result


def get_monitor_change_counts() -> Dict[str, Dict[str, int]]:
    ensure_db()
    counts: Dict[str, Dict[str, int]] = {}
    with db_connection() as conn:
        cursor = conn.execute(
            """
            SELECT task_name, status, COUNT(1)
            FROM monitor_change_events
            WHERE status <> 'completed'
            GROUP BY task_name, status
            """
        )
        for row in cursor.fetchall():
            task_name = str(row[0] or "")
            status = str(row[1] or "")
            count = max(0, int(row[2] or 0))
            bucket = counts.setdefault(task_name, {"pending": 0, "failed": 0, "manual_required": 0})
            if status == "failed":
                bucket["failed"] += count
            elif status == "manual_required":
                bucket["manual_required"] += count
            else:
                bucket["pending"] += count
    return counts


def get_manual_required_monitor_scopes(
    task_name: str,
    *,
    cfg: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    active_cfg = cfg or get_config()
    normalized_task_name = str(task_name or "").strip()
    task = _task_by_name(active_cfg, normalized_task_name)
    if not normalized_task_name or not task:
        return []

    scopes: List[Dict[str, Any]] = []
    with db_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, new_path
            FROM monitor_change_events
            WHERE task_name = ? AND status = 'manual_required'
            ORDER BY id
            """,
            (normalized_task_name,),
        )
        for row in cursor.fetchall():
            provider_path = normalize_relative_path(str(row[1] or ""))
            context = _task_path_context(active_cfg, task, provider_path)
            if not context:
                continue
            remote_rel_path = normalize_relative_path(context["remote_rel_path"])
            scopes.append(
                {
                    "event_id": int(row[0] or 0),
                    "provider_path": provider_path,
                    "remote_path": context["remote_path"],
                    "first_level_dir_rel": remote_rel_path.split("/", 1)[0] if remote_rel_path else "",
                }
            )
    return scopes


def complete_manual_required_monitor_events(
    task_name: str,
    event_ids: Sequence[int],
) -> int:
    normalized_task_name = str(task_name or "").strip()
    normalized_event_ids = sorted(
        {int(value or 0) for value in (event_ids or []) if int(value or 0) > 0}
    )
    if not normalized_task_name or not normalized_event_ids:
        return 0
    placeholders = ",".join("?" for _ in normalized_event_ids)
    with db_connection() as conn:
        completed_at = now_text()
        cursor = conn.execute(
            f"""
            UPDATE monitor_change_events
            SET status = 'completed', completed_at = ?, updated_at = ?,
                last_error = '', needs_reconcile = 0
            WHERE task_name = ? AND id IN ({placeholders}) AND status = 'manual_required'
            """,
            (completed_at, completed_at, normalized_task_name, *normalized_event_ids),
        )
        completed = max(0, int(cursor.rowcount or 0))
        conn.commit()
    return completed


def cleanup_completed_monitor_change_events(days: int = MONITOR_CHANGE_COMPLETED_RETENTION_DAYS) -> int:
    cutoff = (datetime.now() - timedelta(days=max(1, int(days or MONITOR_CHANGE_COMPLETED_RETENTION_DAYS)))).isoformat(
        timespec="seconds"
    )
    with db_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM monitor_change_events WHERE status = 'completed' AND completed_at <> '' AND completed_at < ?",
            (cutoff,),
        )
        deleted = max(0, int(cursor.rowcount or 0))
        conn.commit()
    return deleted


def _has_persisted_destination_cid(operation: str, snapshot: Dict[str, Any]) -> bool:
    if operation not in {"create", "copy"} or not bool(snapshot.get("is_dir")):
        return False
    new_cid = str(snapshot.get("new_cid", "") or "").strip()
    if not new_cid or new_cid == "0" or not _provider_path_is_safe(str(snapshot.get("new_path", "") or "")):
        return False
    rejected_ids = {
        str(snapshot.get("id", "") or "").strip(),
        str(snapshot.get("old_cid", "") or "").strip(),
        str(snapshot.get("old_parent_id", "") or "").strip(),
        str(snapshot.get("new_parent_id", "") or "").strip(),
        "",
        "0",
    }
    return new_cid not in rejected_ids


def recover_monitor_change_events(*, cfg: Optional[Dict[str, Any]] = None, enqueue: bool = True) -> Dict[str, Any]:
    active_cfg = cfg or get_config()
    ensure_db()
    now = now_text()
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, status, operation, needs_reconcile, entry_snapshot_json
            FROM monitor_change_events
            WHERE status IN ('prepared', 'processing')
            ORDER BY id
            """
        )
        recovery_rows = cursor.fetchall()
        recovered = 0
        for row in recovery_rows:
            event_id = int(row[0] or 0)
            previous_status = str(row[1] or "").strip()
            operation = str(row[2] or "").strip()
            previous_needs_reconcile = bool(int(row[3] or 0))
            snapshot = safe_json_loads(row[4], {})
            if not isinstance(snapshot, dict):
                snapshot = {}
            if previous_status == "prepared":
                needs_reconcile = not _has_persisted_destination_cid(operation, snapshot)
                error_text = (
                    "启动恢复：已保存目标目录 CID，继续精准同步"
                    if not needs_reconcile
                    else "启动恢复：远端操作结果未确认"
                )
            else:
                needs_reconcile = previous_needs_reconcile
                snapshot["local_sync_uncertain"] = True
                error_text = (
                    "启动恢复：上次局部校正被中断"
                    if needs_reconcile
                    else "启动恢复：上次精准同步被中断"
                )
            cursor.execute(
                """
                UPDATE monitor_change_events
                SET status = 'pending', needs_reconcile = ?, next_retry_at = 0,
                    entry_snapshot_json = ?,
                    last_error = ?, updated_at = ?
                WHERE id = ? AND status IN ('prepared', 'processing')
                """,
                (
                    1 if needs_reconcile else 0,
                    safe_json_dumps(snapshot),
                    error_text,
                    now,
                    event_id,
                ),
            )
            recovered += max(0, int(cursor.rowcount or 0))
        cursor.execute(
            """
            UPDATE monitor_change_events
            SET status = 'pending', retry_count = 0, next_retry_at = 0,
                processor_revision = ?, last_error = ?, completed_at = '', updated_at = ?
            WHERE status = 'failed'
              AND retry_count >= ?
              AND COALESCE(processor_revision, 0) < ?
            """,
            (
                MONITOR_CHANGE_HANDLER_REVISION,
                "处理器升级后重新排队",
                now,
                MONITOR_CHANGE_MAX_RETRIES,
                MONITOR_CHANGE_HANDLER_REVISION,
            ),
        )
        recovered += max(0, int(cursor.rowcount or 0))
        cursor.execute(
            """
            SELECT DISTINCT task_name
            FROM monitor_change_events
            WHERE status = 'pending'
               OR (status = 'failed' AND retry_count < ? AND next_retry_at <= ?)
            """,
            (MONITOR_CHANGE_MAX_RETRIES, time.time()),
        )
        configured_names = {
            str(normalize_task(task or {}).get("name", "") or "").strip()
            for task in active_cfg.get("monitor_tasks", []) or []
        }
        task_names = [
            str(row[0] or "")
            for row in cursor.fetchall()
            if str(row[0] or "").strip() in configured_names
        ]
        conn.commit()
    deleted = cleanup_completed_monitor_change_events()
    if enqueue and task_names:
        _enqueue_task_names(task_names)
    return {"recovered": recovered, "queued_tasks": sorted(set(task_names)), "deleted_completed": deleted}


def queue_ready_monitor_change_tasks(*, cfg: Optional[Dict[str, Any]] = None) -> List[str]:
    active_cfg = cfg or get_config()
    configured_names = {
        str(normalize_task(task or {}).get("name", "") or "").strip()
        for task in active_cfg.get("monitor_tasks", []) or []
    }
    with db_connection() as conn:
        cursor = conn.execute(
            """
            SELECT DISTINCT task_name
            FROM monitor_change_events
            WHERE status = 'pending'
               OR (status = 'failed' AND retry_count < ? AND next_retry_at <= ?)
            """,
            (MONITOR_CHANGE_MAX_RETRIES, time.time()),
        )
        task_names = [
            str(row[0] or "")
            for row in cursor.fetchall()
            if str(row[0] or "").strip() in configured_names
        ]
    if task_names:
        _enqueue_task_names(task_names)
    return sorted(set(task_names))
