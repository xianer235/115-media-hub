"""Structured lifecycle records for folder-monitor work."""

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from ..db import db_connection, now_text, safe_json_dumps, safe_json_loads, sqlite_row_to_dict


ACTIVE_RUN_STATUSES = {"queued", "running", "waiting"}
SOURCE_LABELS = {
    "manual": "手动触发", "cron": "定时触发", "resource": "资源导入",
    "subscription": "订阅任务", "webhook": "外部通知", "change": "文件变更同步",
    "auto_rescan": "系统补扫", "recovery": "恢复任务", "import": "资源导入",
    "offline": "离线下载完成", "retry": "重新运行", "system": "系统触发",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _object(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def normalize_result(value: Any) -> Dict[str, Any]:
    """Keep summary counters distinct from per-item detail in new and old runs."""
    result = dict(_object(value))
    for key in ("moved", "left"):
        if isinstance(result.get(key), list):
            result.setdefault(f"{key}_items", result[key])
            result[key] = len(result[key])
    return result


def _count_result(value: Any) -> int:
    return max(0, int(value or 0)) if isinstance(value, (int, float, str)) else 0


def source_label(value: Any) -> str:
    source = _text(value).lower()
    return SOURCE_LABELS.get(source, "系统触发" if not source else "其他来源")


def _serialize_run(row: Any) -> Dict[str, Any]:
    item = sqlite_row_to_dict(row)
    if not item:
        return {}
    item["sources"] = safe_json_loads(item.pop("sources_json", "[]"), [])
    item["scope"] = safe_json_loads(item.pop("scope_json", "{}"), {})
    item["result"] = normalize_result(safe_json_loads(item.pop("result_json", "{}"), {}))
    item["task_snapshot"] = safe_json_loads(item.pop("task_snapshot_json", "{}"), {})
    item["source_label"] = source_label(item.get("source"))
    return item


def _insert_event(conn: Any, run_id: str, category: str, operation: str, status: str, title: str, detail: Optional[Dict[str, Any]], now: str) -> None:
    conn.execute(
        """INSERT INTO monitor_run_events
        (run_id, category, operation, status, title, detail_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (run_id, _text(category) or "process", _text(operation), _text(status), _text(title), safe_json_dumps(_object(detail)), now),
    )


def create_run(*, run_kind: str, task_name: str, source: str, scope: Optional[Dict[str, Any]] = None, subject: str = "", parent_run_id: str = "", source_ref: str = "", task_snapshot: Optional[Dict[str, Any]] = None) -> str:
    run_id, now = uuid.uuid4().hex, now_text()
    item = {"source": _text(source).lower() or "system", "ref": _text(source_ref), "at": now}
    parent = _text(parent_run_id)
    with db_connection() as conn:
        conn.execute(
            """INSERT INTO monitor_runs
            (id, parent_run_id, run_kind, task_name, task_snapshot_json, source, sources_json, scope_json, subject, status, queued_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)""",
            (run_id, parent, _text(run_kind) or "scan", _text(task_name), safe_json_dumps(_object(task_snapshot)), item["source"], safe_json_dumps([item]), safe_json_dumps(_object(scope)), _text(subject), now, now),
        )
        _insert_event(conn, run_id, "process", "queued", "queued", source_label(source), {"scope": _object(scope), "source_ref": item["ref"]}, now)
        if parent:
            conn.execute("INSERT OR IGNORE INTO monitor_run_links (run_id, related_run_id, relation, created_at) VALUES (?, ?, 'child', ?)", (parent, run_id, now))
        conn.commit()
    return run_id


def link_runs(run_id: str, related_run_id: str, relation: str = "related") -> None:
    left, right = _text(run_id), _text(related_run_id)
    if not left or not right or left == right:
        return
    with db_connection() as conn:
        conn.execute("INSERT OR IGNORE INTO monitor_run_links (run_id, related_run_id, relation, created_at) VALUES (?, ?, ?, ?)", (left, right, _text(relation) or "related", now_text()))
        conn.commit()


def set_parent_run(run_id: str, parent_run_id: str) -> None:
    """Attach a just-created downstream run when its persisted event reveals a parent."""
    run_id, parent = _text(run_id), _text(parent_run_id)
    if not run_id or not parent or run_id == parent:
        return
    now = now_text()
    with db_connection() as conn:
        conn.execute("UPDATE monitor_runs SET parent_run_id = ?, updated_at = ? WHERE id = ?", (parent, now, run_id))
        conn.execute("INSERT OR IGNORE INTO monitor_run_links (run_id, related_run_id, relation, created_at) VALUES (?, ?, 'child', ?)", (parent, run_id, now))
        conn.commit()


def add_source(run_id: str, source: str, source_ref: str = "") -> None:
    run_id, now = _text(run_id), now_text()
    if not run_id:
        return
    with db_connection() as conn:
        row = conn.execute("SELECT sources_json FROM monitor_runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            return
        sources = safe_json_loads(row[0], [])
        sources = sources if isinstance(sources, list) else []
        item = {"source": _text(source).lower() or "system", "ref": _text(source_ref), "at": now}
        if any(isinstance(entry, dict) and entry.get("source") == item["source"] and entry.get("ref") == item["ref"] for entry in sources):
            return
        sources.append(item)
        conn.execute("UPDATE monitor_runs SET sources_json = ?, updated_at = ? WHERE id = ?", (safe_json_dumps(sources), now, run_id))
        _insert_event(conn, run_id, "process", "merged", "queued", source_label(source), {"source_ref": item["ref"]}, now)
        conn.commit()


def start_run(run_id: str, *, subject: str = "", scope: Optional[Dict[str, Any]] = None) -> None:
    run_id, now = _text(run_id), now_text()
    if not run_id:
        return
    assignments, values = ["status = 'running'", "started_at = CASE WHEN started_at = '' THEN ? ELSE started_at END", "updated_at = ?"], [now, now]
    if _text(subject):
        assignments.append("subject = ?")
        values.append(_text(subject))
    if isinstance(scope, dict):
        assignments.append("scope_json = ?")
        values.append(safe_json_dumps(scope))
    values.append(run_id)
    with db_connection() as conn:
        conn.execute(f"UPDATE monitor_runs SET {', '.join(assignments)} WHERE id = ?", tuple(values))
        _insert_event(conn, run_id, "process", "started", "running", "开始执行", {"scope": _object(scope)}, now)
        conn.commit()


def update_run(run_id: str, *, subject: Optional[str] = None, status: Optional[str] = None, summary: Optional[str] = None, result: Optional[Dict[str, Any]] = None) -> None:
    run_id = _text(run_id)
    if not run_id:
        return
    assignments, values = ["updated_at = ?"], [now_text()]
    if subject is not None:
        assignments.append("subject = ?"); values.append(_text(subject))
    if status is not None:
        assignments.append("status = ?"); values.append(_text(status))
    if summary is not None:
        assignments.append("summary = ?"); values.append(_text(summary))
    if result is not None:
        assignments.append("result_json = ?"); values.append(safe_json_dumps(normalize_result(result)))
    values.append(run_id)
    with db_connection() as conn:
        conn.execute(f"UPDATE monitor_runs SET {', '.join(assignments)} WHERE id = ?", tuple(values))
        conn.commit()


def wait_run(run_id: str, *, summary: str, result: Optional[Dict[str, Any]] = None) -> None:
    run_id, now = _text(run_id), now_text()
    if not run_id:
        return
    with db_connection() as conn:
        normalized_result = normalize_result(result)
        conn.execute("UPDATE monitor_runs SET status = 'waiting', summary = ?, result_json = ?, updated_at = ? WHERE id = ?", (_text(summary), safe_json_dumps(normalized_result), now, run_id))
        _insert_event(conn, run_id, "process", "waiting", "waiting", _text(summary), normalized_result, now)
        conn.commit()


def finish_run(run_id: str, *, status: str, summary: str, result: Optional[Dict[str, Any]] = None) -> None:
    run_id, now, final = _text(run_id), now_text(), _text(status) or "completed"
    if not run_id:
        return
    with db_connection() as conn:
        normalized_result = normalize_result(result)
        conn.execute("UPDATE monitor_runs SET status = ?, summary = ?, result_json = ?, finished_at = ?, updated_at = ? WHERE id = ?", (final, _text(summary), safe_json_dumps(normalized_result), now, now, run_id))
        _insert_event(conn, run_id, "process", "finished", final, _text(summary), normalized_result, now)
        parent_row = conn.execute("SELECT parent_run_id FROM monitor_runs WHERE id = ?", (run_id,)).fetchone()
        direct_parent = str(parent_row[0] or "") if parent_row else ""
        parent_ids = {direct_parent} if direct_parent else set()
        parent_ids.update(
            str(row[0] or "")
            for row in conn.execute(
                "SELECT run_id FROM monitor_run_links WHERE related_run_id = ? AND relation = 'downstream'",
                (run_id,),
            ).fetchall()
            if str(row[0] or "")
        )
        for parent in parent_ids:
            parent_state = conn.execute("SELECT status FROM monitor_runs WHERE id = ?", (parent,)).fetchone()
            linked_children = {
                str(row[0] or "")
                for row in conn.execute("SELECT id FROM monitor_runs WHERE parent_run_id = ?", (parent,)).fetchall()
                if str(row[0] or "")
            }
            linked_children.update(
                str(row[0] or "")
                for row in conn.execute(
                    "SELECT related_run_id FROM monitor_run_links WHERE run_id = ? AND relation = 'downstream'",
                    (parent,),
                ).fetchall()
                if str(row[0] or "")
            )
            if not parent_state or str(parent_state[0] or "") != "waiting" or not linked_children:
                continue
            marks = ",".join("?" for _ in linked_children)
            child_statuses = [
                str(row[0] or "")
                for row in conn.execute(f"SELECT status FROM monitor_runs WHERE id IN ({marks})", tuple(linked_children)).fetchall()
            ]
            if any(value in ACTIVE_RUN_STATUSES for value in child_statuses):
                continue
            parent_result_row = conn.execute("SELECT result_json FROM monitor_runs WHERE id = ?", (parent,)).fetchone()
            parent_result = normalize_result(safe_json_loads(parent_result_row[0] if parent_result_row else "{}", {}))
            has_left = _count_result(parent_result.get("left")) > 0
            aggregate = "partial" if has_left or any(value in {"failed", "partial", "cancelled"} for value in child_statuses) else "completed"
            aggregate_summary = (
                f"后续同步结束，但仍有未完成内容（{len(child_statuses)} 个任务）"
                if aggregate == "partial" else f"后续本地播放文件同步完成（{len(child_statuses)} 个任务）"
            )
            conn.execute("UPDATE monitor_runs SET status = ?, summary = ?, finished_at = ?, updated_at = ? WHERE id = ?", (aggregate, aggregate_summary, now, now, parent))
            _insert_event(conn, parent, "process", "downstream_finished", aggregate, aggregate_summary, {"children": len(child_statuses)}, now)
        conn.commit()


def record_event(run_id: str, *, category: str, operation: str, status: str, title: str, detail: Optional[Dict[str, Any]] = None) -> None:
    run_id, now = _text(run_id), now_text()
    if not run_id:
        return
    with db_connection() as conn:
        _insert_event(conn, run_id, category, operation, status, title, detail, now)
        conn.execute("UPDATE monitor_runs SET updated_at = ? WHERE id = ?", (now, run_id))
        conn.commit()


_CHILD_IDS_SQL = """SELECT id FROM monitor_runs WHERE parent_run_id = ?
    UNION SELECT related_run_id FROM monitor_run_links
    WHERE run_id = ? AND relation = 'downstream'"""


def list_runs(*, limit: int = 10, cursor: str = "", task_name: str = "", source: str = "", status: str = "", include_children: bool = False) -> Dict[str, Any]:
    limit = max(1, min(100, int(limit or 10)))
    clauses, values = ([] if include_children else ["parent_run_id = ''"], [])
    for column, value in (("task_name", task_name), ("status", status)):
        if _text(value):
            clauses.append(f"{column} = ?"); values.append(_text(value))
    if _text(source):
        normalized_source = _text(source).lower()
        clauses.append("(source = ? OR sources_json LIKE ?)")
        values.extend([normalized_source, f'%"source": "{normalized_source}"%'])
    if _text(cursor):
        cursor_time, separator, cursor_id = _text(cursor).rpartition("|")
        if separator and cursor_time and cursor_id:
            clauses.append("(updated_at < ? OR (updated_at = ? AND id < ?))")
            values.extend([cursor_time, cursor_time, cursor_id])
        else:
            clauses.append("updated_at < ?"); values.append(_text(cursor))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with db_connection() as conn:
        rows = conn.execute(f"SELECT * FROM monitor_runs {where} ORDER BY updated_at DESC, id DESC LIMIT ?", tuple([*values, limit + 1])).fetchall()
        has_more, rows = len(rows) > limit, rows[:limit]
        runs = [_serialize_run(row) for row in rows]
        for run in runs:
            run["child_count"] = int(conn.execute(
                f"SELECT COUNT(*) FROM monitor_runs WHERE id IN ({_CHILD_IDS_SQL})",
                (run["id"], run["id"]),
            ).fetchone()[0] or 0)
    return {
        "runs": runs,
        "has_more": has_more,
        "next_cursor": f"{runs[-1]['updated_at']}|{runs[-1]['id']}" if has_more and runs else "",
    }


_RUN_EVENTS_SQL = """WITH events AS (
    SELECT 'run-' || id AS id, run_id, category, operation, status, title,
           detail_json, created_at, 0 AS origin, id AS sequence
      FROM monitor_run_events WHERE run_id = :run_id
    UNION ALL
    SELECT 'change-' || id, monitor_run_id, 'remote', operation, status,
           COALESCE(NULLIF(new_path, ''), NULLIF(old_path, ''), '检测到网盘变更'),
           json_object('old_path', old_path, 'new_path', new_path,
                       'error', last_error, 'completed_at', completed_at),
           created_at, 1, id
      FROM monitor_change_events WHERE monitor_run_id = :run_id
)"""
_PROBLEM_SQL = """(category = 'problem' OR
    (category IN ('remote', 'strm') AND status IN
     ('failed', 'partial', 'pending', 'manual_required', 'rollback_failed')))"""


def get_run_detail(run_id: str, *, category: str = "", offset: int = 0, limit: int = 50) -> Dict[str, Any]:
    run_id, limit = _text(run_id), max(1, min(100, int(limit or 50)))
    offset, category = max(0, int(offset or 0)), _text(category)
    with db_connection() as conn:
        run = _serialize_run(conn.execute("SELECT * FROM monitor_runs WHERE id = ?", (run_id,)).fetchone())
        if not run:
            return {}
        parameters = {"run_id": run_id, "category": category, "limit": limit, "offset": offset}
        grouped = conn.execute(_RUN_EVENTS_SQL + " SELECT category, COUNT(*) FROM events GROUP BY category", parameters).fetchall()
        counts = {key: 0 for key in ("process", "remote", "strm", "problem")}
        counts.update({str(row[0]): int(row[1]) for row in grouped})
        counts["problem"] = int(conn.execute(
            _RUN_EVENTS_SQL + f" SELECT COUNT(*) FROM events WHERE {_PROBLEM_SQL}", parameters,
        ).fetchone()[0] or 0)
        condition = _PROBLEM_SQL if category == "problem" else ("category = :category" if category else "1 = 1")
        total = int(conn.execute(_RUN_EVENTS_SQL + f" SELECT COUNT(*) FROM events WHERE {condition}", parameters).fetchone()[0] or 0)
        rows = conn.execute(
            _RUN_EVENTS_SQL + f""" SELECT * FROM events WHERE {condition}
                ORDER BY replace(created_at, 'T', ' '), origin, sequence
                LIMIT :limit OFFSET :offset""", parameters,
        ).fetchall()
        events = []
        for row in rows:
            item = sqlite_row_to_dict(row)
            item["detail"] = safe_json_loads(item.pop("detail_json", "{}"), {})
            item.pop("origin", None)
            item.pop("sequence", None)
            if str(item["id"]).startswith("change-"):
                detail = _object(item["detail"])
                old_path, new_path = _text(detail.get("old_path")), _text(detail.get("new_path"))
                operation = _text(item.get("operation")).lower()
                detail.update(
                    step="网盘目录变更",
                    operation_label={
                        "rename": "网盘重命名", "move": "网盘移动", "merge": "网盘合并",
                        "delete": "网盘删除", "create": "网盘新增",
                    }.get(operation, "网盘操作"),
                    old_name=old_path.rstrip("/").rsplit("/", 1)[-1] if old_path else "",
                    new_name=new_path.rstrip("/").rsplit("/", 1)[-1] if new_path else "",
                )
                item["detail"] = detail
            events.append(item)
        children = [_serialize_run(row) for row in conn.execute(
            f"SELECT * FROM monitor_runs WHERE id IN ({_CHILD_IDS_SQL}) ORDER BY queued_at, id",
            (run_id, run_id),
        ).fetchall()]
        links = [sqlite_row_to_dict(row) for row in conn.execute(
            "SELECT related_run_id, relation FROM monitor_run_links WHERE run_id = ?", (run_id,),
        ).fetchall()]
        parents = [_serialize_run(row) for row in conn.execute(
            """SELECT * FROM monitor_runs WHERE id = ? OR id IN (
                SELECT run_id FROM monitor_run_links WHERE related_run_id = ? AND relation = 'downstream'
            ) ORDER BY queued_at, id""", (run.get("parent_run_id", ""), run_id),
        ).fetchall()]
        related = []
        for link in links:
            if link["relation"] == "retry_of":
                original = _serialize_run(conn.execute("SELECT * FROM monitor_runs WHERE id = ?", (link["related_run_id"],)).fetchone())
                if original:
                    related.append({**original, "relation": "retry_of"})
    return {
        "run": run, "events": events, "children": children, "parents": parents,
        "links": links, "related": related, "counts": counts, "total": total,
        "has_more": offset + len(events) < total, "next_offset": offset + len(events),
    }


def cleanup_runs(*, days: int = 0, preview: bool = False) -> Dict[str, Any]:
    clauses, values = [
        "status NOT IN ('queued', 'running', 'waiting')",
        "NOT EXISTS (SELECT 1 FROM monitor_runs child WHERE child.parent_run_id = monitor_runs.id AND child.status IN ('queued', 'running', 'waiting'))",
        "NOT EXISTS (SELECT 1 FROM monitor_run_links link JOIN monitor_runs child ON child.id = link.related_run_id WHERE link.run_id = monitor_runs.id AND link.relation = 'downstream' AND child.status IN ('queued', 'running', 'waiting'))",
    ], []
    if int(days or 0) > 0:
        clauses.append("finished_at != '' AND finished_at < ?")
        values.append((datetime.now() - timedelta(days=max(1, int(days)))).isoformat(timespec="seconds"))
    with db_connection() as conn:
        run_ids = [str(row[0] or "") for row in conn.execute(f"SELECT id FROM monitor_runs WHERE {' AND '.join(clauses)}", tuple(values)).fetchall()]
        if preview or not run_ids:
            return {"count": len(run_ids), "deleted": 0}
        marks = ",".join("?" for _ in run_ids)
        conn.execute(f"DELETE FROM monitor_run_events WHERE run_id IN ({marks})", tuple(run_ids))
        conn.execute(f"DELETE FROM monitor_run_links WHERE run_id IN ({marks}) OR related_run_id IN ({marks})", tuple([*run_ids, *run_ids]))
        conn.execute(f"DELETE FROM monitor_runs WHERE id IN ({marks})", tuple(run_ids))
        conn.commit()
    return {"count": len(run_ids), "deleted": len(run_ids)}
