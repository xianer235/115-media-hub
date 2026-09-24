"""Structured lifecycle records for folder-monitor work."""

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from ..db import db_connection, now_text, safe_json_dumps, safe_json_loads, sqlite_row_to_dict


ACTIVE_RUN_STATUSES = {"queued", "running", "waiting"}
INCOMPLETE_CHILD_STATUSES = {"failed", "partial", "cancelled"}
ACTIVE_CHANGE_STATUSES = {"prepared", "pending", "processing"}
UNRESOLVED_CHANGE_STATUSES = {"failed", "manual_required", "rollback_failed"}
# 一次整理会派生「增量变更同步 → 自动补扫」两层下游，链路本身很浅；把向上/向下的
# 遍历限制在这个深度，既覆盖真实链路，也避免异常数据把查询拖成全库递归。
MAX_RUN_LINK_DEPTH = 5
GROUP_RUNS_PREVIEW_LIMIT = 10
SOURCE_LABELS = {
    "manual": "手动触发", "cron": "定时触发", "resource": "资源导入",
    "subscription": "订阅任务", "webhook": "外部通知", "change": "检测到网盘变更",
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


def _run_parent_ids(conn: Any, run_ids: List[str]) -> Dict[str, List[str]]:
    """批量解析直接父运行（直接字段 + 关联表），避免列表页出现 N+1 查询。"""
    parents: Dict[str, List[str]] = {run_id: [] for run_id in run_ids if run_id}
    if not parents:
        return parents
    marks = ",".join("?" for _ in parents)
    values = tuple(parents)
    for row in conn.execute(
        f"""SELECT id, parent_run_id FROM monitor_runs
             WHERE id IN ({marks}) AND parent_run_id <> ''""",
        values,
    ).fetchall():
        run_id, parent_id = _text(row[0]), _text(row[1])
        if run_id in parents and parent_id and parent_id not in parents[run_id]:
            parents[run_id].append(parent_id)
    for row in conn.execute(
        f"""SELECT related_run_id, run_id FROM monitor_run_links
             WHERE related_run_id IN ({marks}) AND relation IN ('child', 'downstream')""",
        values,
    ).fetchall():
        run_id, parent_id = _text(row[0]), _text(row[1])
        if run_id in parents and parent_id and parent_id not in parents[run_id]:
            parents[run_id].append(parent_id)
    return parents


def _ancestor_ids(conn: Any, run_id: str, *, max_depth: int = MAX_RUN_LINK_DEPTH) -> List[str]:
    """祖先运行 ID，由近到远（最近的一层在前），按深度上限收敛。"""
    origin = _text(run_id)
    if not origin:
        return []
    seen: List[str] = []
    pending = [origin]
    cache: Dict[str, List[str]] = {}
    for _ in range(max(1, int(max_depth or 1))):
        level: List[str] = []
        for value in pending:
            if value not in cache:
                cache.update(_run_parent_ids(conn, [value]))
            for parent_id in cache.get(value, []):
                if parent_id == origin or parent_id in seen or parent_id in level:
                    continue
                level.append(parent_id)
        if not level:
            break
        seen.extend(level)
        pending = level
    return seen


def _touch_ancestors(conn: Any, run_id: str, now: str) -> None:
    """把“最近活动”上溯到祖先运行。

    运行记录按 `updated_at` 倒序，触发记录（祖先）的活动时间跟着下游一起走，它才会
    排在自己派生出来的任务之前，而不是夹在它们中间。分页游标仍然是 `updated_at`，
    不需要为排序写递归查询。

    时间戳只有秒精度，同秒内的下游会把祖先 `updated_at` 撑到完全相同的值；这里给
    祖先加一个毫秒后缀，保证“触发记录先于它派生的记录”在同秒内也成立（`MAX` 保证
    祖先自己后续写入的整秒时间不会把它拉回去）。
    """
    ancestors = _ancestor_ids(conn, run_id)
    if not ancestors:
        return
    stamp = _ancestor_activity_time(now)
    marks = ",".join("?" for _ in ancestors)
    conn.execute(
        f"UPDATE monitor_runs SET updated_at = MAX(updated_at, ?) WHERE id IN ({marks})",
        (stamp, *ancestors),
    )


def _ancestor_activity_time(now: str) -> str:
    text = _text(now)
    if not text:
        return text
    return text if "." in text else f"{text}.999999"


def _descendant_entries(conn: Any, run_id: str, *, max_depth: int = MAX_RUN_LINK_DEPTH) -> List[Dict[str, Any]]:
    """一条运行的全部下游（含下游的下游），带 `depth`，按触发时间升序。"""
    origin = _text(run_id)
    if not origin:
        return []
    depths: Dict[str, int] = {}
    pending = [origin]
    for depth in range(1, max(1, int(max_depth or 1)) + 1):
        if not pending:
            break
        marks = ",".join("?" for _ in pending)
        values = tuple([*pending, *pending])
        level: List[str] = []
        for row in conn.execute(
            f"""SELECT * FROM monitor_runs WHERE parent_run_id IN ({marks})
                UNION
                SELECT run.* FROM monitor_run_links AS link
                  JOIN monitor_runs AS run ON run.id = link.related_run_id
                 WHERE link.run_id IN ({marks}) AND link.relation IN ('child', 'downstream')""",
            values,
        ).fetchall():
            child_id = _text(sqlite_row_to_dict(row).get("id"))
            if not child_id or child_id == origin or child_id in depths:
                continue
            depths[child_id] = depth
            level.append(child_id)
        pending = level
    if not depths:
        return []
    marks = ",".join("?" for _ in depths)
    rows = {
        _text(sqlite_row_to_dict(row).get("id")): row
        for row in conn.execute(f"SELECT * FROM monitor_runs WHERE id IN ({marks})", tuple(depths)).fetchall()
    }
    items: List[Dict[str, Any]] = []
    for child_id, depth in depths.items():
        item = _serialize_run(rows.get(child_id))
        if not item:
            continue
        item["depth"] = depth
        item["group_id"] = origin
        item["group_depth"] = depth
        items.append(item)
    # 只通过关联表挂上来的下游（例如接收夹分发出来的自动补扫）没有 parent_run_id，
    # 但它在链路里的上一级是明确的：用它来排前序，别把两层压成同一层。
    for child_id, parent_ids in _run_parent_ids(conn, list(depths)).items():
        parent_id = next(
            (value for value in parent_ids if value == origin or value in depths),
            "",
        )
        if not parent_id:
            continue
        for item in items:
            if _text(item.get("id")) == child_id:
                item["link_parent_id"] = parent_id
                break
    child_counts = _child_counts(conn, list(depths))
    for item in items:
        item["child_count"] = child_counts.get(_text(item.get("id")), 0)
    return _order_group_entries(items, origin)


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
            _touch_ancestors(conn, run_id, now)
        conn.commit()
    return run_id


def link_runs(run_id: str, related_run_id: str, relation: str = "related") -> None:
    left, right = _text(run_id), _text(related_run_id)
    if not left or not right or left == right:
        return
    now = now_text()
    with db_connection() as conn:
        conn.execute("INSERT OR IGNORE INTO monitor_run_links (run_id, related_run_id, relation, created_at) VALUES (?, ?, ?, ?)", (left, right, _text(relation) or "related", now))
        _touch_ancestors(conn, left, now)
        conn.commit()


def set_parent_run(run_id: str, parent_run_id: str) -> None:
    """Attach a just-created downstream run when its persisted event reveals a parent."""
    run_id, parent = _text(run_id), _text(parent_run_id)
    if not run_id or not parent or run_id == parent:
        return
    now = now_text()
    with db_connection() as conn:
        conn.execute("UPDATE monitor_runs SET parent_run_id = ?, updated_at = MAX(updated_at, ?) WHERE id = ?", (parent, now, run_id))
        conn.execute("INSERT OR IGNORE INTO monitor_run_links (run_id, related_run_id, relation, created_at) VALUES (?, ?, 'child', ?)", (parent, run_id, now))
        _touch_ancestors(conn, run_id, now)
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
        conn.execute("UPDATE monitor_runs SET sources_json = ?, updated_at = MAX(updated_at, ?) WHERE id = ?", (safe_json_dumps(sources), now, run_id))
        _insert_event(conn, run_id, "process", "merged", "queued", source_label(source), {"source_ref": item["ref"]}, now)
        _touch_ancestors(conn, run_id, now)
        conn.commit()


def start_run(run_id: str, *, subject: str = "", scope: Optional[Dict[str, Any]] = None) -> None:
    run_id, now = _text(run_id), now_text()
    if not run_id:
        return
    assignments, values = ["status = 'running'", "started_at = CASE WHEN started_at = '' THEN ? ELSE started_at END", "updated_at = MAX(updated_at, ?)"], [now, now]
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
        _touch_ancestors(conn, run_id, now)
        conn.commit()


def update_run(run_id: str, *, subject: Optional[str] = None, status: Optional[str] = None, summary: Optional[str] = None, result: Optional[Dict[str, Any]] = None) -> None:
    run_id, now = _text(run_id), now_text()
    if not run_id:
        return
    assignments, values = ["updated_at = MAX(updated_at, ?)"], [now]
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
        _touch_ancestors(conn, run_id, now)
        conn.commit()


def wait_run(run_id: str, *, summary: str, result: Optional[Dict[str, Any]] = None) -> None:
    run_id, now = _text(run_id), now_text()
    if not run_id:
        return
    with db_connection() as conn:
        normalized_result = normalize_result(result)
        conn.execute("UPDATE monitor_runs SET status = 'waiting', summary = ?, result_json = ?, updated_at = MAX(updated_at, ?) WHERE id = ?", (_text(summary), safe_json_dumps(normalized_result), now, run_id))
        _insert_event(conn, run_id, "process", "waiting", "waiting", _text(summary), normalized_result, now)
        _touch_ancestors(conn, run_id, now)
        conn.commit()
    reconcile_waiting_run(run_id)


def _change_event_state(conn: Any, run_id: str) -> Dict[str, Any]:
    """运行名下变更事件的处理状态：`blocked` 表示仍在处理中，其余计入未完成。"""
    state: Dict[str, Any] = {"blocked": False, "counts": {status: 0 for status in UNRESOLVED_CHANGE_STATUSES}, "total": 0}
    rows = conn.execute(
        "SELECT status, next_retry_at FROM monitor_change_events WHERE monitor_run_id = ?",
        (run_id,),
    ).fetchall()
    for row in rows:
        status = _text(row[0])
        state["total"] += 1
        if status in ACTIVE_CHANGE_STATUSES:
            state["blocked"] = True
        elif status == "failed" and float(row[1] or 0) > 0:
            # 还有退避重试在排队，属于“进行中”，不能提前结算。
            state["blocked"] = True
        elif status in UNRESOLVED_CHANGE_STATUSES:
            state["counts"][status] += 1
    return state


def _run_unfinished_state(conn: Any, run_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """判断一条运行的后续工作是否真的没做完。

    返回 `blocked`（还有进行中的工作，必须继续等待）与 `reasons`（已经确定未完成
    的内容）。自动补扫是同一批工作的后续步骤，只有它真的失败、或条目仍留在接收夹、
    或变更事件仍未解决，才算“未完成”。
    """
    descendants = _descendant_entries(conn, run_id)
    active = [item for item in descendants if _text(item.get("status")) in ACTIVE_RUN_STATUSES]
    if active:
        return {"blocked": True, "reasons": [], "descendants": descendants}

    change_state = _change_event_state(conn, run_id)
    if change_state["blocked"]:
        return {"blocked": True, "reasons": [], "descendants": descendants}

    reasons: List[str] = []
    left = _count_result(result.get("left"))
    if left:
        reasons.append(f"仍留在接收夹 {left} 项")
    for status, label in (("manual_required", "仍需同步"), ("failed", "处理失败"), ("rollback_failed", "回滚失败")):
        count = int((change_state["counts"] or {}).get(status, 0) or 0)
        if count:
            reasons.append(f"{count} 个目录{label}")
    for item in descendants:
        if _text(item.get("status")) in INCOMPLETE_CHILD_STATUSES:
            subject = _text(item.get("subject")) or _text(item.get("task_name")) or "后续任务"
            reasons.append(f"后续任务未完成：{subject}")
    # 事件处理可能刚结束、下游运行还没建好关联：执行期继续等，启动恢复才允许收尾。
    expected_downstream = _count_result(result.get("monitor_sync_events")) > 0 or _count_result(result.get("waiting_children")) > 0
    return {
        "blocked": False,
        "reasons": reasons,
        "descendants": descendants,
        "expected_downstream": expected_downstream,
        "no_descendants": not descendants,
    }


def _waiting_settle_summary(run_kind: str, result: Dict[str, Any], reasons: List[str], descendant_total: int) -> str:
    if reasons:
        return f"后续同步结束，仍有未完成内容：{'；'.join(reasons[:2])}。"
    if run_kind == "change":
        completed = _count_result(result.get("completed"))
        rescans = _count_result(result.get("auto_rescan"))
        head = f"已同步 {completed} 条网盘变更" if completed else "本次变更同步已结束"
        return f"{head}，{rescans} 个目录的自动补扫已完成。" if rescans else f"{head}。"
    moved = _count_result(result.get("moved"))
    head = f"已分发 {moved} 项" if moved else "本次整理已结束"
    return f"{head}，后续同步全部完成（含自动补扫）。" if descendant_total else f"{head}，后续同步全部完成。"


def _reconcile_waiting_run(
    conn: Any,
    run_id: str,
    now: str,
    *,
    finalize_orphaned: bool = False,
    depth: int = 0,
) -> bool:
    """结算一条 `waiting` 运行：下游（含下游的下游）全部进入终态后才定稿。"""
    row = conn.execute(
        "SELECT run_kind, status, result_json FROM monitor_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    if not row or _text(row[1]) != "waiting":
        return False
    run_kind = _text(row[0]) or "scan"
    result = normalize_result(safe_json_loads(row[2], {}))
    state = _run_unfinished_state(conn, run_id, result)
    if state.get("blocked"):
        return False
    reasons = list(state.get("reasons") or [])
    descendants = state.get("descendants") or []
    if not descendants and state.get("expected_downstream"):
        if not finalize_orphaned:
            return False
        reasons.append("没有找到对应的后续同步记录")
    final = "partial" if reasons else "completed"
    summary = _waiting_settle_summary(run_kind, result, reasons, len(descendants))
    updated = conn.execute(
        """UPDATE monitor_runs
           SET status = ?, summary = ?, finished_at = ?, updated_at = MAX(updated_at, ?)
           WHERE id = ? AND status = 'waiting'""",
        (final, summary, now, now, run_id),
    ).rowcount
    if not updated:
        return False
    _insert_event(
        conn,
        run_id,
        "process",
        "downstream_finished",
        final,
        summary,
        {"children": len(descendants), "left": _count_result(result.get("left")), "reasons": reasons},
        now,
    )
    _touch_ancestors(conn, run_id, now)
    if depth < MAX_RUN_LINK_DEPTH:
        # 结算一条等待中的运行后，它的来源运行可能也可以收尾了。
        for parent_id in _run_parent_ids(conn, [run_id]).get(run_id, []):
            _reconcile_waiting_run(conn, parent_id, now, finalize_orphaned=finalize_orphaned, depth=depth + 1)
    return True


# 兼容旧调用点：接收夹是最早引入两阶段状态机的运行类型。
_reconcile_inbox_run = _reconcile_waiting_run


def reconcile_waiting_run(run_id: str) -> bool:
    normalized_run_id = _text(run_id)
    if not normalized_run_id:
        return False
    with db_connection() as conn:
        reconciled = _reconcile_waiting_run(conn, normalized_run_id, now_text())
        conn.commit()
    return reconciled


def reconcile_waiting_runs() -> int:
    """启动恢复：结算所有下游都已结束的 `waiting` 运行（含断链的历史等待）。"""
    reconciled = 0
    with db_connection() as conn:
        rows = conn.execute("SELECT id FROM monitor_runs WHERE status = 'waiting'").fetchall()
        for row in rows:
            run_id = _text(row[0])
            if run_id and _reconcile_waiting_run(conn, run_id, now_text(), finalize_orphaned=True):
                reconciled += 1
        conn.commit()
    return reconciled


# 兼容旧调用点（早期名为“只处理接收夹”）：现在任何 `waiting` 运行都走同一套结算。
reconcile_waiting_inbox_runs = reconcile_waiting_runs


def recover_interrupted_runs() -> Dict[str, int]:
    """Close in-memory work left active by the previous service process."""
    now = now_text()
    counts = {"running": 0, "queued": 0}
    parent_ids = set()
    with db_connection() as conn:
        rows = conn.execute(
            "SELECT id, status, parent_run_id FROM monitor_runs WHERE status IN ('queued', 'running')"
        ).fetchall()
        for row in rows:
            run_id, previous, parent_id = _text(row[0]), _text(row[1]), _text(row[2])
            if not run_id:
                continue
            final = "failed" if previous == "running" else "cancelled"
            summary = "服务重启，上次运行已中断" if previous == "running" else "服务重启，上次排队任务未开始"
            conn.execute(
                "UPDATE monitor_runs SET status = ?, summary = ?, finished_at = ?, updated_at = MAX(updated_at, ?) WHERE id = ?",
                (final, summary, now, now, run_id),
            )
            _insert_event(conn, run_id, "process", "interrupted", final, summary, {"previous_status": previous}, now)
            counts[previous] += 1
            if parent_id:
                parent_ids.add(parent_id)
        for parent_id in parent_ids:
            _reconcile_waiting_run(conn, parent_id, now)
        conn.commit()
    return counts


def repair_change_event_owners() -> int:
    """一次性补齐历史变更事件的运行归属，让旧记录的「网盘操作」也能列出改动。

    只处理三方都明确的事件：事件未归属任何运行、任务名相同、完成时间落在**唯一**
    一条变更同步运行的执行区间内。存在多种可能的运行时不猜测，保留现状交给文本日志
    排查，避免把改动记到错误的运行上。返回修复条数。
    """
    repaired = 0
    with db_connection() as conn:
        pending = conn.execute(
            """SELECT id, task_name, completed_at FROM monitor_change_events
                WHERE monitor_run_id = '' AND completed_at <> ''
                  AND status IN ('completed', 'manual_required')"""
        ).fetchall()
        if not pending:
            return 0
        windows: Dict[str, List[tuple]] = {}
        for row in conn.execute(
            """SELECT id, task_name, started_at, finished_at FROM monitor_runs
                WHERE run_kind = 'change' AND started_at <> '' AND finished_at <> ''
                ORDER BY started_at"""
        ).fetchall():
            windows.setdefault(_text(row[1]), []).append((_text(row[2]), _text(row[3]), _text(row[0])))
        for event_id, task_name, completed_at in pending:
            completed = _text(completed_at)
            candidates = [
                run_id
                for started_at, finished_at, run_id in windows.get(_text(task_name), [])
                if started_at <= completed <= finished_at
            ]
            if len(candidates) != 1:
                continue
            conn.execute(
                "UPDATE monitor_change_events SET monitor_run_id = ? WHERE id = ? AND monitor_run_id = ''",
                (candidates[0], event_id),
            )
            repaired += 1
        if repaired:
            conn.commit()
    return repaired


def _unit_change_events_pending(conn: Any, run_id: str) -> bool:
    """这条运行所属工作单元是否还有没走完的变更事件（处理中或仍等补扫）。

    只看本工作单元（自身 + 祖先 + 下游）名下的变更事件：同一个监控任务上其他工作单元
    的滞留事件不该影响这条记录的结算，否则一条卡住的事件会让整个任务的记录都无法重算。
    """
    normalized_run_id = _text(run_id)
    if not normalized_run_id:
        return False
    unit = {normalized_run_id, *_ancestor_ids(conn, normalized_run_id)}
    unit.update(_text(item.get("id")) for item in _descendant_entries(conn, normalized_run_id))
    unit.discard("")
    if not unit:
        return False
    marks = ",".join("?" for _ in unit)
    row = conn.execute(
        f"""SELECT COUNT(*) FROM monitor_change_events
            WHERE monitor_run_id IN ({marks})
              AND (status IN ('prepared', 'pending', 'processing', 'manual_required')
                   OR (status = 'failed' AND next_retry_at > 0))""",
        tuple(unit),
    ).fetchone()
    return bool(row and int(row[0] or 0) > 0)


def _resettle_run(
    conn: Any,
    run_id: str,
    summary: str,
    detail: Dict[str, Any],
    now: str,
    *,
    run_kind: str = "",
    depth: int = 0,
    settled: Optional[List[str]] = None,
) -> None:
    conn.execute(
        "UPDATE monitor_runs SET status = 'completed', summary = ?, updated_at = MAX(updated_at, ?) WHERE id = ?",
        (_text(summary), now, run_id),
    )
    _insert_event(conn, run_id, "process", "resettled", "completed", summary, detail, now)
    _touch_ancestors(conn, run_id, now)
    if settled is not None and run_kind:
        settled.append(run_kind)
    if depth < MAX_RUN_LINK_DEPTH:
        for parent_id in _run_parent_ids(conn, [run_id]).get(run_id, []):
            _resettle_stale_run(conn, parent_id, now, depth=depth + 1, settled=settled)


def _resettle_stale_run(
    conn: Any,
    run_id: str,
    now: str,
    *,
    depth: int = 0,
    settled: Optional[List[str]] = None,
) -> bool:
    """把“只因为等自动补扫而写成部分完成、但现在证据已清”的运行改回已完成。

    旧版本在补扫清掉 `manual_required` 事件后不回写运行状态；即使是新版本，事件清理
    与运行收尾也可能差一步（补扫 runner 先收尾、再清事件），所以这里按证据重新结算，
    而不是在流程里补一个调用点。真实失败、仍有条目留在接收夹的记录不会被改动。
    """
    row = conn.execute(
        "SELECT run_kind, task_name, status, result_json FROM monitor_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    if not row:
        return False
    run_kind, task_name, status = _text(row[0]), _text(row[1]), _text(row[2])
    if status != "partial" or run_kind not in {"inbox", "change"}:
        return False
    result = normalize_result(safe_json_loads(row[3], {}))
    if run_kind == "change":
        # 变更同步写成部分完成的原因只能是“等补扫”；失败或没有补扫记录都不动。
        if _count_result(result.get("failed")) or not _count_result(result.get("manual_required")):
            return False
        if _unit_change_events_pending(conn, run_id):
            return False
    elif _count_result(result.get("left")):
        return False
    state = _run_unfinished_state(conn, run_id, result)
    if state.get("blocked") or state.get("reasons"):
        return False
    if run_kind == "inbox" and not state.get("descendants") and not state.get("expected_downstream"):
        # 没有任何下游与事件的接收记录不能凭猜测改判（变更同步上面已有明确证据要求）。
        return False
    _resettle_run(
        conn,
        run_id,
        "后续同步与自动补扫都已完成，重新结算为已完成。",
        {
            "reason": "downstream_completed",
            "children": len(state.get("descendants") or []),
            **({"task_name": task_name} if run_kind == "change" else {}),
        },
        now,
        run_kind=run_kind,
        depth=depth,
        settled=settled,
    )
    return True


def settle_deferred_runs() -> Dict[str, int]:
    """重算历史上“等到自动补扫开始前就先写成部分完成”的运行。

    接收夹分发文件夹后，变更同步会先把目录交给自动补扫，再在补扫成功后清掉
    `manual_required` 事件；旧版本没有回写运行状态，于是“明明全部完成”的记录一直停在
    部分完成。这里按证据重新结算，统计字段原样保留，只改状态与结论并补一条事件留痕。
    返回修复条数（启动时执行一次，幂等）。
    """
    now = now_text()
    settled = {"change": 0, "inbox": 0}
    with db_connection() as conn:
        resettled_kinds: List[str] = []
        for row in conn.execute(
            """SELECT id, run_kind FROM monitor_runs
                WHERE status = 'partial' AND run_kind IN ('inbox', 'change')
                ORDER BY queued_at, id"""
        ).fetchall():
            run_id = _text(row[0])
            if run_id:
                _resettle_stale_run(conn, run_id, now, settled=resettled_kinds)
        for run_kind in resettled_kinds:
            settled[run_kind] = settled.get(run_kind, 0) + 1
        if any(settled.values()):
            conn.commit()
    return settled


def resettle_settled_run(run_id: str) -> bool:
    """后续补扫补清了事件后，把已经定稿的父运行按证据重新结算。"""
    normalized = _text(run_id)
    if not normalized:
        return False
    settled = False
    with db_connection() as conn:
        now = now_text()
        for candidate in [normalized, *_ancestor_ids(conn, normalized)]:
            if _resettle_stale_run(conn, candidate, now):
                settled = True
        conn.commit()
    return settled


def finish_run(run_id: str, *, status: str, summary: str, result: Optional[Dict[str, Any]] = None) -> None:
    run_id, now, final = _text(run_id), now_text(), _text(status) or "completed"
    if not run_id:
        return
    with db_connection() as conn:
        normalized_result = normalize_result(result)
        conn.execute("UPDATE monitor_runs SET status = ?, summary = ?, result_json = ?, finished_at = ?, updated_at = MAX(updated_at, ?) WHERE id = ?", (final, _text(summary), safe_json_dumps(normalized_result), now, now, run_id))
        _insert_event(conn, run_id, "process", "finished", final, _text(summary), normalized_result, now)
        _touch_ancestors(conn, run_id, now)
        for parent in _run_parent_ids(conn, [run_id]).get(run_id, []):
            _reconcile_waiting_run(conn, parent, now)
        conn.commit()


def record_event(run_id: str, *, category: str, operation: str, status: str, title: str, detail: Optional[Dict[str, Any]] = None) -> None:
    run_id, now = _text(run_id), now_text()
    if not run_id:
        return
    with db_connection() as conn:
        _insert_event(conn, run_id, category, operation, status, title, detail, now)
        conn.execute("UPDATE monitor_runs SET updated_at = MAX(updated_at, ?) WHERE id = ?", (now, run_id))
        conn.commit()


_CHILD_IDS_SQL = """SELECT id FROM monitor_runs WHERE parent_run_id = ?
    UNION SELECT related_run_id FROM monitor_run_links
    WHERE run_id = ? AND relation = 'downstream'"""


def _add_parent_contexts(conn: Any, runs: List[Dict[str, Any]]) -> None:
    """把“来自接收夹整理”的上下文补到单独列出的下游运行上。

    列表每页都会渲染这一列，所以父运行只做固定两次批量查询；逐条查询会在
    列表页产生 N+1，且同样落在状态推送的热路径上。只有父运行本身是接收夹整理
    时才展示：接收夹二次分发出来的扫描/补扫是独立任务，不该显示成
    “来自接收夹整理：电影 · 文件变更”这种内部步骤名。
    """
    run_ids = [_text(run.get("id")) for run in runs]
    parent_ids: Dict[str, str] = {
        run_id: _text(run.get("parent_run_id"))
        for run_id, run in zip(run_ids, runs)
        if run_id
    }
    missing = [run_id for run_id, parent_id in parent_ids.items() if not parent_id]
    if missing:
        marks = ",".join("?" for _ in missing)
        linked = {
            _text(row[0]): _text(row[1])
            for row in conn.execute(
                f"""SELECT related_run_id, run_id FROM monitor_run_links
                     WHERE related_run_id IN ({marks}) AND relation IN ('child', 'downstream')
                     ORDER BY CASE relation WHEN 'child' THEN 0 ELSE 1 END, created_at, run_id""",
                tuple(missing),
            ).fetchall()
        }
        for run_id in missing:
            parent_ids[run_id] = linked.get(run_id, "")

    wanted = sorted({parent_id for parent_id in parent_ids.values() if parent_id})
    if not wanted:
        return
    marks = ",".join("?" for _ in wanted)
    parents = {
        _text(row[0]): (_text(row[1]), _text(row[2]), _text(row[3]))
        for row in conn.execute(
            f"SELECT id, task_name, subject, run_kind FROM monitor_runs WHERE id IN ({marks})",
            tuple(wanted),
        ).fetchall()
    }
    for run, run_id in zip(runs, run_ids):
        parent = parents.get(parent_ids.get(run_id, ""))
        if parent and parent[2] == "inbox":
            run["parent_task_name"], run["parent_subject"] = parent[0], parent[1]


def _child_counts(conn: Any, run_ids: List[str]) -> Dict[str, int]:
    """统计每页运行记录的后续步骤数量，固定一次查询完成。"""
    if not run_ids:
        return {}
    marks = ",".join("?" for _ in run_ids)
    counts = {run_id: 0 for run_id in run_ids}
    for row in conn.execute(
        f"""SELECT relation.run_id, COUNT(DISTINCT relation.child_id) FROM (
                SELECT parent_run_id AS run_id, id AS child_id
                  FROM monitor_runs WHERE parent_run_id IN ({marks})
                UNION ALL
                SELECT link.run_id AS run_id, link.related_run_id AS child_id
                  FROM monitor_run_links AS link
                  JOIN monitor_runs AS child ON child.id = link.related_run_id
                 WHERE link.run_id IN ({marks})
                   AND link.relation IN ('child', 'downstream')
            ) AS relation GROUP BY relation.run_id""",
        tuple([*run_ids, *run_ids]),
    ).fetchall():
        counts[_text(row[0])] = int(row[1] or 0)
    return counts


def _order_group_entries(entries: List[Dict[str, Any]], head_id: str) -> List[Dict[str, Any]]:
    """按“先触发在前”的前序遍历下游（详情里的链路展示用）。

    单纯按时间排序会让“自动补扫”排在它所属的“变更同步”之前，看起来像并列任务；
    前序遍历能让链路一眼可读：变更同步 → 它自己的自动补扫。
    """
    children_of: Dict[str, List[Dict[str, Any]]] = {}
    for entry in entries:
        parent_id = _text(entry.get("parent_run_id")) or _text(entry.get("link_parent_id"))
        children_of.setdefault(parent_id or head_id, []).append(entry)
    for values in children_of.values():
        values.sort(key=lambda item: (str(item.get("queued_at") or ""), str(item.get("id") or "")))

    ordered: List[Dict[str, Any]] = []
    visited: set = set()

    def walk(parent_id: str) -> None:
        for entry in children_of.get(parent_id, []):
            run_id = _text(entry.get("id"))
            if not run_id or run_id in visited:
                continue
            visited.add(run_id)
            ordered.append(entry)
            walk(run_id)

    walk(head_id)
    for entry in entries:  # 兜底：上游不在本页时也要展示，不能丢记录。
        run_id = _text(entry.get("id"))
        if run_id and run_id not in visited:
            visited.add(run_id)
            ordered.append(entry)
    return ordered


def list_runs(*, limit: int = 10, cursor: str = "", task_name: str = "", source: str = "", status: str = "", run_kind: str = "", include_children: bool = False) -> Dict[str, Any]:
    limit = max(1, min(100, int(limit or 10)))
    normalized_kind = _text(run_kind).lower()
    if normalized_kind not in {"scan", "inbox", "change"}:
        normalized_kind = ""
    include_downstream = bool(include_children or normalized_kind == "change")
    # 列表里每一条运行都是它自己的任务，只有“某条触发记录的直接子运行”不单独占一行
    # （它就是触发记录详情里的“后续同步”，避免一次分发在列表里出现两遍）。
    # 二次分发出来的扫描/自动补扫只挂在关联表上（没有 parent_run_id），照常各自成行。
    clauses, values = ([] if include_downstream else [
        "parent_run_id = ''",
    ], [])
    for column, value in (("task_name", task_name), ("status", status)):
        if _text(value):
            clauses.append(f"{column} = ?"); values.append(_text(value))
    if normalized_kind:
        clauses.append("run_kind = ?"); values.append(normalized_kind)
    if _text(source):
        normalized_source = _text(source).lower()
        clauses.append("(source = ? OR sources_json LIKE ?)")
        values.extend([normalized_source, f'%"source": "{normalized_source}"%'])

    def fetch(start_cursor: str, size: int) -> List[Any]:
        local_clauses, local_values = list(clauses), list(values)
        raw_cursor = _text(start_cursor)
        if raw_cursor:
            cursor_time, separator, cursor_id = raw_cursor.rpartition("|")
            if separator and cursor_time and cursor_id:
                local_clauses.append("(updated_at < ? OR (updated_at = ? AND id < ?))")
                local_values.extend([cursor_time, cursor_time, cursor_id])
            else:
                local_clauses.append("updated_at < ?"); local_values.append(raw_cursor)
        where = f"WHERE {' AND '.join(local_clauses)}" if local_clauses else ""
        return conn.execute(
            f"SELECT * FROM monitor_runs {where} ORDER BY updated_at DESC, id DESC LIMIT ?",
            tuple([*local_values, size]),
        ).fetchall()

    with db_connection() as conn:
        if include_downstream:
            # 显式查看下游（流程 = 增量变更同步 / include_children）时保持扁平列表，
            # 便于按流程排查；默认视图才按工作单元分组。
            rows = fetch(cursor, limit + 1)
            has_more, rows = len(rows) > limit, rows[:limit]
            runs = [_serialize_run(row) for row in rows]
            _add_parent_contexts(conn, runs)
            child_counts = _child_counts(conn, [run["id"] for run in runs if run.get("id")])
            for run in runs:
                run["child_count"] = child_counts.get(run["id"], 0)
            return {
                "runs": runs,
                "has_more": has_more,
                "next_cursor": f"{runs[-1]['updated_at']}|{runs[-1]['id']}" if has_more and runs else "",
            }

        # 默认视图就是一条运行一行：接收夹整理排在最前（它的活动时间跟着下游上溯），
        # 它派生出来的扫描/自动补扫紧接在后，各自是独立任务。
        rows = fetch(cursor, limit + 1)
        has_more, rows = len(rows) > limit, rows[:limit]
        runs = [_serialize_run(row) for row in rows]
        _add_parent_contexts(conn, runs)
        child_counts = _child_counts(conn, [run["id"] for run in runs if run.get("id")])
        for run in runs:
            run_id = run.get("id")
            run["child_count"] = child_counts.get(run_id, 0)
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
      FROM monitor_change_events AS change_event
     WHERE change_event.monitor_run_id = :run_id
       -- 接收夹已写入“接收夹分发”动作；这里的变更事件是其下游
       -- STRM 同步输入，改由关联子运行展示，不能重复为一次网盘移动。
       AND NOT EXISTS (
           SELECT 1 FROM monitor_runs AS parent
            WHERE parent.id = change_event.monitor_run_id
              AND parent.run_kind = 'inbox'
       )
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
        # 下游可能再派生一层（增量变更同步 → 自动补扫），详情要能看到完整链路。
        descendants = _descendant_entries(conn, run_id) if children else []
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
        "run": run, "events": events, "children": children, "descendants": descendants, "parents": parents,
        "links": links, "related": related, "counts": counts, "total": total,
        "has_more": offset + len(events) < total, "next_offset": offset + len(events),
    }


def cleanup_runs(*, scope: str, days: int = 0, preview: bool = False, task_name: str = "") -> Dict[str, Any]:
    """Remove terminal runs within an explicit cleanup scope.

    ``expired`` is retention-driven and requires a positive day count;
    ``all_finished`` is the separately confirmed manual purge action.
    ``task_name`` 可把范围收窄到某一个监控任务（运行记录页的“清空该任务记录”）。
    """
    normalized_scope = _text(scope).lower()
    if normalized_scope not in {"expired", "all_finished"}:
        raise ValueError("不支持的运行记录清理范围")
    retention_days = max(0, int(days or 0))
    if normalized_scope == "expired" and retention_days < 1:
        raise ValueError("清理过期记录时必须指定保留天数")
    normalized_task = _text(task_name)
    clauses, values = [
        "status NOT IN ('queued', 'running', 'waiting')",
        "NOT EXISTS (SELECT 1 FROM monitor_runs child WHERE child.parent_run_id = monitor_runs.id AND child.status IN ('queued', 'running', 'waiting'))",
        "NOT EXISTS (SELECT 1 FROM monitor_run_links link JOIN monitor_runs child ON child.id = link.related_run_id WHERE link.run_id = monitor_runs.id AND link.relation = 'downstream' AND child.status IN ('queued', 'running', 'waiting'))",
    ], []
    if normalized_task:
        clauses.append("task_name = ?")
        values.append(normalized_task)
    if normalized_scope == "expired":
        clauses.append("finished_at != '' AND finished_at < ?")
        values.append((datetime.now() - timedelta(days=retention_days)).isoformat(timespec="seconds"))
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
