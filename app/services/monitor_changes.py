import asyncio
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


MONITOR_CHANGE_MAX_DIRS = 80
MONITOR_CHANGE_MAX_FILES = 1200
MONITOR_CHANGE_MAX_RETRIES = 5
MONITOR_CHANGE_RETRY_BASE_SECONDS = 5
MONITOR_CHANGE_COMPLETED_RETENTION_DAYS = 30

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


def _capture_indexed_manifest(
    cfg: Dict[str, Any],
    tasks: Sequence[Dict[str, Any]],
    old_path: str,
) -> Tuple[bool, List[Dict[str, Any]]]:
    manifest_by_path: Dict[str, Dict[str, Any]] = {}
    source_states: List[bool] = []
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
                SELECT dir_rel_path, needs_rescan
                FROM monitor_dirs
                WHERE task_name = ?
                """,
                (task_name,),
            )
            dir_states = [
                (normalize_relative_path(str(row[0] or "")), bool(int(row[1] or 0)))
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
                for rel, dirty in dir_states
            )
            has_clean_exact_dir = any(rel == dir_rel_path and not dirty for rel, dirty in dir_states)
            source_states.append(bool(rows or has_clean_exact_dir) and not has_dirty_scope)
    return bool(source_states) and all(source_states), list(manifest_by_path.values())


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
            entry_key = _event_entry_key(dedupe_key, snapshot, index)
            for task in task_matches:
                task_name = str(task.get("name", "") or "").strip()
                if not task_name:
                    continue
                enriched = dict(snapshot)
                if snapshot.get("is_dir") and snapshot.get("old_path"):
                    manifest_known, manifest = _capture_indexed_manifest(
                        active_cfg,
                        [task],
                        str(snapshot.get("old_path", "")),
                    )
                    enriched["manifest_known"] = manifest_known
                    enriched["indexed_files"] = manifest
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
            SELECT id, old_path, entry_snapshot_json, needs_reconcile
            FROM monitor_change_events
            WHERE task_name = ? AND status = 'pending' AND id < ?
            AND operation IN ('rename', 'move') AND new_path = ? AND source_action = ?
            ORDER BY id DESC LIMIT 1
            """,
            (
                str(current[1] or ""),
                int(current[0] or 0),
                str(current[3] or ""),
                str(current[6] or ""),
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
        if isinstance(previous_snapshot, dict):
            if previous_snapshot.get("manifest_known") and not current_snapshot.get("manifest_known"):
                current_snapshot["manifest_known"] = True
                current_snapshot["indexed_files"] = previous_snapshot.get("indexed_files", [])
            for key in ("old_parent_id", "old_cid"):
                if not str(current_snapshot.get(key, "") or "").strip() and str(previous_snapshot.get(key, "") or "").strip():
                    current_snapshot[key] = previous_snapshot[key]
        current_snapshot["old_path"] = str(previous[1] or "")
        reconcile_required = bool(int(current[7] or 0)) or bool(int(previous[3] or 0))
        current_snapshot["needs_reconcile"] = reconcile_required
        cursor.execute(
            """
            UPDATE monitor_change_events
            SET old_path = ?, entry_snapshot_json = ?, needs_reconcile = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                str(previous[1] or ""),
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
            WHERE id = ? AND status = 'pending'
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
            f"SELECT task_name, status, needs_reconcile FROM monitor_change_events WHERE id IN ({placeholders})",
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


def _write_strm_file(local_rel_path: str, content: str) -> bool:
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


def _delete_unreferenced_strm_file(conn: Any, local_rel_path: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM monitor_files WHERE local_rel_path = ? LIMIT 1",
        (local_rel_path,),
    ).fetchone()
    if row:
        return False
    return delete_managed_strm_file(local_rel_path, root=STRM_ROOT)


def _remove_file_path(conn: Any, task: Dict[str, Any], context: Dict[str, str]) -> Dict[str, int]:
    local_rel_path = context["local_rel_path"]
    conn.execute(
        "DELETE FROM monitor_files WHERE task_name = ? AND local_rel_path = ?",
        (str(task.get("name", "") or ""), local_rel_path),
    )
    deleted = 1 if _delete_unreferenced_strm_file(conn, local_rel_path) else 0
    if deleted:
        remove_empty_parent_dirs(
            os.path.dirname(managed_strm_file_path(local_rel_path, root=STRM_ROOT)),
            os.path.join(STRM_ROOT, context["task_root"]),
        )
    return {"deleted": deleted}


def _remove_folder_path(conn: Any, task: Dict[str, Any], context: Dict[str, str]) -> Dict[str, int]:
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
        if _delete_unreferenced_strm_file(conn, local_rel_path)
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
) -> Dict[str, int]:
    context = _task_path_context(cfg, task, provider_path)
    if not context:
        return {"deleted": 0}
    if is_dir:
        return _remove_folder_path(conn, task, context)
    return _remove_file_path(conn, task, context)


def _file_passes_filters(cfg: Dict[str, Any], task: Dict[str, Any], provider_path: str, size: int) -> bool:
    name = basename(provider_path)
    if not is_video_file(name, get_user_extensions(cfg)):
        return False
    min_bytes = int(float(task.get("min_file_size_mb", 0) or 0) * 1024 * 1024)
    return min_bytes <= 0 or _nonnegative_int(size) >= min_bytes


def _add_file_path(
    conn: Any,
    cfg: Dict[str, Any],
    task: Dict[str, Any],
    provider_path: str,
    *,
    size: int = 0,
    modified_at: str = "",
) -> Dict[str, int]:
    context = _task_path_context(cfg, task, provider_path)
    if not context or not _file_passes_filters(cfg, task, provider_path, size):
        return {"generated": 0, "skipped": 1}
    url = build_strm_play_url(cfg, context["remote_path"])
    generated = 1 if _write_strm_file(context["local_rel_path"], url) else 0
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


def _mark_first_level_dirty(
    conn: Any,
    task: Dict[str, Any],
    context: Dict[str, str],
    is_dir: bool,
    *,
    folder_parent_only: bool = False,
) -> None:
    task_name = str(task.get("name", "") or "")
    rel_path = normalize_relative_path(context.get("remote_rel_path", ""))
    affected_dir = rel_path if is_dir else normalize_relative_path(os.path.dirname(rel_path))
    if is_dir and folder_parent_only:
        affected_dir = normalize_relative_path(os.path.dirname(rel_path))
    first_level = affected_dir.split("/", 1)[0] if affected_dir else ""
    if not first_level and is_dir:
        return
    conn.execute(
        """
        INSERT INTO monitor_dirs(
            task_name, dir_rel_path, remote_modified, entry_modified,
            needs_rescan, missing_confirmations
        ) VALUES (?, ?, '', '', 1, 0)
        ON CONFLICT(task_name, dir_rel_path) DO UPDATE SET
            needs_rescan = 1,
            missing_confirmations = 0
        """,
        (task_name, first_level),
    )


def _mark_event_baselines(
    conn: Any,
    cfg: Dict[str, Any],
    task: Dict[str, Any],
    old_path: str,
    new_path: str,
    is_dir: bool,
) -> None:
    old_context = _task_path_context(cfg, task, old_path)
    if old_context:
        _mark_first_level_dirty(
            conn,
            task,
            old_context,
            is_dir,
            folder_parent_only=is_dir,
        )
    new_context = _task_path_context(cfg, task, new_path)
    if new_context:
        _mark_first_level_dirty(conn, task, new_context, is_dir)


def _manifest_target_path(old_root: str, new_root: str, source_path: str) -> str:
    old_normalized = normalize_relative_path(old_root)
    source_normalized = normalize_relative_path(source_path)
    if source_normalized == old_normalized:
        suffix = ""
    elif source_normalized.startswith(old_normalized + "/"):
        suffix = source_normalized[len(old_normalized) + 1 :]
    else:
        return ""
    return join_relative_path(new_root, suffix)


def _add_indexed_folder(
    conn: Any,
    cfg: Dict[str, Any],
    task: Dict[str, Any],
    snapshot: Dict[str, Any],
) -> Dict[str, int]:
    generated = 0
    skipped = 0
    file_count = 0
    for raw_file in snapshot.get("indexed_files", []) if isinstance(snapshot.get("indexed_files"), list) else []:
        item = raw_file if isinstance(raw_file, dict) else {}
        target_path = _manifest_target_path(
            str(snapshot.get("old_path", "") or ""),
            str(snapshot.get("new_path", "") or ""),
            str(item.get("path", "") or ""),
        )
        if not target_path:
            continue
        result = _add_file_path(
            conn,
            cfg,
            task,
            target_path,
            size=_nonnegative_int(item.get("size", 0)),
            modified_at=str(item.get("modified_at", "") or ""),
        )
        generated += int(result.get("generated", 0) or 0)
        skipped += int(result.get("skipped", 0) or 0)
        file_count += 1
    return {"generated": generated, "skipped": skipped, "file_count": file_count, "directory_count": 0}


async def _collect_new_folder_subtree(
    cfg: Dict[str, Any],
    task: Dict[str, Any],
    new_path: str,
    root_cid: str,
) -> Dict[str, Any]:
    root_context = _task_path_context(cfg, task, new_path)
    if not root_context:
        return {"files": [], "file_count": 0, "directory_count": 0}
    if root_context["remote_path"] == root_context["scan_path"]:
        raise RuntimeError("精准同步禁止读取整个监控根目录")
    mount_prefix = get_mount_prefix(cfg, "115")
    list_delay_seconds = max(0, int(task.get("list_delay_ms", 0) or 0)) / 1000
    normalized_root_cid = str(root_cid or "").strip()
    if not normalized_root_cid or normalized_root_cid == "0":
        raise RuntimeError("未知文件夹缺少目标 CID，已拒绝回退扫描监控根目录")
    queue: List[Tuple[str, str]] = [(root_context["remote_path"], normalized_root_cid)]
    visited: Set[str] = set()
    files: List[Dict[str, Any]] = []
    file_count = 0
    while queue:
        remote_dir, folder_cid = queue.pop(0)
        if remote_dir in visited:
            continue
        if len(visited) >= MONITOR_CHANGE_MAX_DIRS:
            raise RuntimeError(f"局部目录数超过上限 {MONITOR_CHANGE_MAX_DIRS}")
        if not is_subpath(remote_dir, root_context["remote_path"]):
            raise RuntimeError("局部读取路径越出目标子树")
        _, items = await _list_change_remote_dir(cfg, remote_dir, task, folder_cid)
        visited.add(remote_dir)
        for raw_item in items:
            item = raw_item if isinstance(raw_item, dict) else {}
            name = str(item.get("name", "") or "").strip()
            if not name:
                continue
            item_remote_path = join_remote_path(remote_dir, name)
            if _snapshot_bool(item.get("is_dir")):
                if len(visited) + len(queue) >= MONITOR_CHANGE_MAX_DIRS:
                    raise RuntimeError(f"局部目录数超过上限 {MONITOR_CHANGE_MAX_DIRS}")
                child_cid = str(item.get("cid", "") or item.get("id", "") or "").strip()
                if not child_cid:
                    raise RuntimeError(f"局部目录缺少 CID: {item_remote_path}")
                queue.append((item_remote_path, child_cid))
                continue
            file_count += 1
            if file_count > MONITOR_CHANGE_MAX_FILES:
                raise RuntimeError(f"局部文件数超过上限 {MONITOR_CHANGE_MAX_FILES}")
            provider_path = normalize_relative_path(item_remote_path[len(mount_prefix) :])
            files.append(
                {
                    "path": provider_path,
                    "size": _nonnegative_int(item.get("size", 0)),
                    "modified_at": str(item.get("modified", "") or item.get("modified_at", "") or ""),
                }
            )
            if list_delay_seconds > 0:
                await asyncio.sleep(list_delay_seconds)
    return {
        "files": files,
        "file_count": file_count,
        "directory_count": len(visited),
    }


def _add_discovered_folder(
    conn: Any,
    cfg: Dict[str, Any],
    task: Dict[str, Any],
    discovery: Dict[str, Any],
) -> Dict[str, int]:
    generated = 0
    skipped = 0
    files = discovery.get("files", []) if isinstance(discovery.get("files"), list) else []
    for raw_file in files:
        item = raw_file if isinstance(raw_file, dict) else {}
        result = _add_file_path(
            conn,
            cfg,
            task,
            str(item.get("path", "") or ""),
            size=_nonnegative_int(item.get("size", 0)),
            modified_at=str(item.get("modified_at", "") or ""),
        )
        generated += int(result.get("generated", 0) or 0)
        skipped += int(result.get("skipped", 0) or 0)
    return {
        "generated": generated,
        "skipped": skipped,
        "file_count": max(0, int(discovery.get("file_count", 0) or 0)),
        "directory_count": max(0, int(discovery.get("directory_count", 0) or 0)),
    }


async def _apply_precise_event(
    conn: Any,
    cfg: Dict[str, Any],
    task: Dict[str, Any],
    event: Dict[str, Any],
) -> Dict[str, int]:
    operation = _normalize_operation(event.get("operation", ""))
    snapshot = safe_json_loads(event.get("entry_snapshot_json", "{}"), {})
    if not isinstance(snapshot, dict):
        snapshot = {}
    old_path = normalize_relative_path(event.get("old_path", ""))
    new_path = normalize_relative_path(event.get("new_path", ""))
    is_dir = bool(snapshot.get("is_dir", False))
    stats = {"generated": 0, "skipped": 0, "deleted": 0, "file_count": 0, "directory_count": 0}
    discovered: Optional[Dict[str, Any]] = None

    if operation in {"create", "copy", "rename", "move"} and new_path and is_dir:
        if operation != "create" and not snapshot.get("manifest_known"):
            discovered = await _collect_new_folder_subtree(
                cfg,
                task,
                new_path,
                str(snapshot.get("new_cid", "") or ""),
            )

    if operation in {"delete", "rename", "move"} and old_path:
        removed = _remove_path(conn, cfg, task, old_path, is_dir)
        stats["deleted"] += int(removed.get("deleted", 0) or 0)

    if operation in {"create", "copy", "rename", "move"} and new_path:
        if is_dir:
            if operation == "create":
                pass
            elif snapshot.get("manifest_known"):
                added = _add_indexed_folder(conn, cfg, task, snapshot)
                for key in ("generated", "skipped", "file_count", "directory_count"):
                    stats[key] += int(added.get(key, 0) or 0)
            else:
                added = _add_discovered_folder(conn, cfg, task, discovered or {})
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
            )
            stats["generated"] += int(added.get("generated", 0) or 0)
            stats["skipped"] += int(added.get("skipped", 0) or 0)
            stats["file_count"] += 1

    _mark_event_baselines(conn, cfg, task, old_path, new_path, is_dir)
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
) -> Dict[str, int]:
    operation = _normalize_operation(event.get("operation", ""))
    snapshot = safe_json_loads(event.get("entry_snapshot_json", "{}"), {})
    if not isinstance(snapshot, dict):
        snapshot = {}
    is_dir = bool(snapshot.get("is_dir", False))
    old_path = normalize_relative_path(event.get("old_path", ""))
    new_path = normalize_relative_path(event.get("new_path", ""))
    candidate_paths: List[Tuple[str, str]] = []
    if operation in {"delete", "rename", "move"} and old_path:
        candidate_paths.append((old_path, str(snapshot.get("old_parent_id", "") or "")))
    if operation in {"create", "copy", "rename", "move"} and new_path and all(
        path != new_path for path, _ in candidate_paths
    ):
        candidate_paths.append((new_path, str(snapshot.get("new_parent_id", "") or "")))
    stats = {"generated": 0, "skipped": 0, "deleted": 0, "file_count": 0, "directory_count": 0}
    entry_id = str(snapshot.get("id", "") or "").strip()
    observations: List[Tuple[str, str, bool, Dict[str, Any], Optional[Dict[str, Any]]]] = []
    for provider_path, parent_cid in candidate_paths:
        if not _task_path_context(cfg, task, provider_path):
            continue
        exists, remote_item = await _list_parent_entry(
            cfg,
            task,
            provider_path,
            parent_cid,
            entry_id=entry_id,
            is_dir=is_dir,
        )
        actual_path = provider_path
        if exists and str(remote_item.get("name", "") or "").strip():
            actual_path = normalize_relative_path(
                join_relative_path(os.path.dirname(provider_path), str(remote_item.get("name", "") or ""))
            )
        discovered = None
        if exists and is_dir:
            folder_cid = str(remote_item.get("cid", "") or remote_item.get("id", "") or "").strip()
            discovered = await _collect_new_folder_subtree(cfg, task, actual_path, folder_cid)
        observations.append((provider_path, actual_path, exists, remote_item, discovered))

    if operation in {"create", "copy"} and new_path and _task_path_context(cfg, task, new_path):
        target_exists = any(
            normalize_relative_path(provider_path) == new_path and exists
            for provider_path, _actual_path, exists, _remote_item, _discovered in observations
        )
        if not target_exists:
            raise RuntimeError(f"局部校正未找到目标条目: {new_path}")

    removed_paths: Set[str] = set()
    for provider_path, actual_path, exists, _remote_item, _discovered in observations:
        for path in (provider_path, actual_path if exists else ""):
            normalized_path = normalize_relative_path(path)
            if not normalized_path or normalized_path in removed_paths:
                continue
            removed_paths.add(normalized_path)
            removed = _remove_path(conn, cfg, task, normalized_path, is_dir)
            stats["deleted"] += int(removed.get("deleted", 0) or 0)

    added_paths: Set[str] = set()
    for _provider_path, actual_path, exists, remote_item, discovered in observations:
        if not exists:
            continue
        normalized_actual_path = normalize_relative_path(actual_path)
        if not normalized_actual_path or normalized_actual_path in added_paths:
            continue
        added_paths.add(normalized_actual_path)
        if is_dir:
            added = _add_discovered_folder(conn, cfg, task, discovered or {})
            for key in ("generated", "skipped", "file_count", "directory_count"):
                stats[key] += int(added.get(key, 0) or 0)
        else:
            added = _add_file_path(
                conn,
                cfg,
                task,
                normalized_actual_path,
                size=_nonnegative_int(remote_item.get("size", snapshot.get("size", 0))),
                modified_at=str(remote_item.get("modified", "") or remote_item.get("modified_at", "") or ""),
            )
            stats["generated"] += int(added.get("generated", 0) or 0)
            stats["skipped"] += int(added.get("skipped", 0) or 0)
            stats["file_count"] += 1
    _mark_event_baselines(conn, cfg, task, old_path, new_path, is_dir)
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
        "errors": [],
    }
    with db_connection() as conn:
        events = _load_ready_events(conn, task_name=task_name, event_ids=event_ids)
        for event in events:
            event_id = int(event.get("id", 0) or 0)
            task = _task_by_name(active_cfg, str(event.get("task_name", "") or ""))
            conn.execute(
                "UPDATE monitor_change_events SET status = 'processing', updated_at = ? WHERE id = ?",
                (now_text(), event_id),
            )
            conn.commit()
            try:
                if not task:
                    raise RuntimeError(f"监控任务不存在: {event.get('task_name', '')}")
                if bool(int(event.get("needs_reconcile", 0) or 0)):
                    stats = await _reconcile_event(conn, active_cfg, task, event)
                else:
                    stats = await _apply_precise_event(conn, active_cfg, task, event)
                completed_at = now_text()
                conn.execute(
                    """
                    UPDATE monitor_change_events
                    SET status = 'completed', updated_at = ?, completed_at = ?,
                        last_error = '', directory_count = ?, file_count = ?
                    WHERE id = ?
                    """,
                    (
                        completed_at,
                        completed_at,
                        max(0, int(stats.get("directory_count", 0) or 0)),
                        max(0, int(stats.get("file_count", 0) or 0)),
                        event_id,
                    ),
                )
                conn.commit()
                result["completed"] += 1
                for key in ("generated", "skipped", "deleted", "directory_count", "file_count"):
                    result[key] += int(stats.get(key, 0) or 0)
            except Exception as exc:
                conn.rollback()
                retry_count = max(0, int(event.get("retry_count", 0) or 0)) + 1
                backoff = min(3600, MONITOR_CHANGE_RETRY_BASE_SECONDS * (2 ** max(0, retry_count - 1)))
                conn.execute(
                    """
                    UPDATE monitor_change_events
                    SET status = 'failed', retry_count = ?, next_retry_at = ?,
                        last_error = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (retry_count, time.time() + backoff, str(exc)[:1000], now_text(), event_id),
                )
                conn.commit()
                result["failed"] += 1
                result["errors"].append({"event_id": event_id, "error": str(exc)})
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
            bucket = counts.setdefault(task_name, {"pending": 0, "failed": 0})
            if status == "failed":
                bucket["failed"] += count
            else:
                bucket["pending"] += count
    return counts


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


def recover_monitor_change_events(*, cfg: Optional[Dict[str, Any]] = None, enqueue: bool = True) -> Dict[str, Any]:
    active_cfg = cfg or get_config()
    ensure_db()
    now = now_text()
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE monitor_change_events
            SET status = 'pending', needs_reconcile = 1, next_retry_at = 0,
                last_error = CASE
                    WHEN status = 'prepared' THEN '启动恢复：远端操作结果未确认'
                    ELSE '启动恢复：上次处理被中断'
                END,
                updated_at = ?
            WHERE status IN ('prepared', 'processing')
            """,
            (now,),
        )
        recovered = max(0, int(cursor.rowcount or 0))
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
