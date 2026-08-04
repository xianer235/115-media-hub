from .core import *  # noqa: F401,F403

RESOURCE_JOB_ACTIVE_STATUSES = ("pending", "running", "submitted")
RESOURCE_JOB_FILTERS = ("all", "active", "submitted", "completed", "failed")


def normalize_resource_job_status_filter(value: Any) -> str:
    normalized = str(value or "all").strip().lower()
    return normalized if normalized in RESOURCE_JOB_FILTERS else "all"


def list_resource_jobs(limit: int = 80) -> List[Dict[str, Any]]:
    ensure_db()
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM resource_jobs ORDER BY id DESC LIMIT ?", (max(1, min(limit, 500)),))
        rows = cursor.fetchall()
    return [serialize_resource_job_row(row) for row in rows]


def _build_resource_job_filter_where(status_filter: str) -> Tuple[str, Tuple[Any, ...]]:
    normalized = normalize_resource_job_status_filter(status_filter)
    if normalized == "active":
        placeholders = ",".join(["?"] * len(RESOURCE_JOB_ACTIVE_STATUSES))
        return f"status IN ({placeholders})", tuple(RESOURCE_JOB_ACTIVE_STATUSES)
    if normalized in ("submitted", "completed", "failed"):
        return "status = ?", (normalized,)
    return "1 = 1", ()


def list_resource_jobs_page(limit: int = 20, offset: int = 0, status_filter: str = "") -> Dict[str, Any]:
    page_limit = max(1, min(int(limit or 20), RESOURCE_JOB_PAGE_MAX_LIMIT))
    page_offset = max(0, int(offset or 0))
    normalized_filter = normalize_resource_job_status_filter(status_filter)
    where_sql, where_params = _build_resource_job_filter_where(normalized_filter)
    ensure_db()
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(1) FROM resource_jobs WHERE {where_sql}", where_params)
        row = cursor.fetchone()
        total = int(row[0] if row else 0)
        cursor.execute(
            f"""
            SELECT *
            FROM resource_jobs
            WHERE {where_sql}
            ORDER BY
                CASE WHEN status IN ('pending', 'running', 'submitted') THEN 0 ELSE 1 END,
                id DESC
            LIMIT ? OFFSET ?
            """,
            (*where_params, page_limit, page_offset),
        )
        rows = cursor.fetchall()
    next_offset = page_offset + len(rows)
    return {
        "jobs": [serialize_resource_job_row(row) for row in rows],
        "pagination": {
            "status": normalized_filter,
            "limit": page_limit,
            "offset": page_offset,
            "next_offset": next_offset,
            "total": total,
            "has_more": next_offset < total,
        },
    }


def count_resource_jobs_by_status() -> Dict[str, int]:
    ensure_db()
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status, COUNT(1) FROM resource_jobs GROUP BY status")
        rows = cursor.fetchall()
    raw_counts = {str(row[0] or "").strip().lower(): int(row[1] or 0) for row in rows}
    active_count = sum(int(raw_counts.get(status, 0) or 0) for status in RESOURCE_JOB_ACTIVE_STATUSES)
    return {
        "total": sum(raw_counts.values()),
        "active": active_count,
        "pending": int(raw_counts.get("pending", 0) or 0),
        "running": int(raw_counts.get("running", 0) or 0),
        "submitted": int(raw_counts.get("submitted", 0) or 0),
        "completed": int(raw_counts.get("completed", 0) or 0),
        "failed": int(raw_counts.get("failed", 0) or 0),
    }

def list_resource_jobs_by_source(job_source: str, limit: int = 80, scan_limit: int = 400) -> List[Dict[str, Any]]:
    source_key = str(job_source or "").strip()
    if not source_key:
        return []
    query_limit = max(1, min(max(int(scan_limit or 0), int(limit or 0), 80), 800))
    jobs = list_resource_jobs(limit=query_limit)
    matched: List[Dict[str, Any]] = []
    target_limit = max(1, int(limit or 1))
    for job in jobs:
        extra = job.get("extra") if isinstance(job.get("extra"), dict) else {}
        if str(extra.get("job_source", "")).strip() != source_key:
            continue
        matched.append(job)
        if len(matched) >= target_limit:
            break
    return matched

def get_resource_job(job_id: int, include_private: bool = False) -> Dict[str, Any]:
    ensure_db()
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM resource_jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
    return serialize_resource_job_row(row, include_private=include_private)


def get_resource_jobs_by_ids(job_ids: List[int], include_private: bool = False) -> List[Dict[str, Any]]:
    if not job_ids:
        return []
    ensure_db()
    with db_connection() as conn:
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in job_ids)
        cursor.execute(f"SELECT * FROM resource_jobs WHERE id IN ({placeholders})", job_ids)
        rows = cursor.fetchall()
    return [serialize_resource_job_row(row, include_private=include_private) for row in rows]

def count_resource_jobs(status: str = "") -> int:
    ensure_db()
    with db_connection() as conn:
        cursor = conn.cursor()
        normalized_status = str(status or "").strip().lower()
        if normalized_status:
            cursor.execute("SELECT COUNT(1) FROM resource_jobs WHERE status = ?", (normalized_status,))
        else:
            cursor.execute("SELECT COUNT(1) FROM resource_jobs")
        row = cursor.fetchone()
    return int(row[0] if row else 0)

def find_existing_resource_job(resource: Dict[str, Any], savepath: str) -> Dict[str, Any]:
    ensure_db()
    with db_connection() as conn:
        cursor = conn.cursor()
        normalized_savepath = normalize_relative_path(savepath)
        link_url = str(resource.get("link_url", "") or "").strip()
        message_url = str(resource.get("message_url", "") or "").strip()
        source_post_id = str(resource.get("source_post_id", "") or "").strip()
        cursor.execute(
            """
            SELECT * FROM resource_jobs
            WHERE savepath = ?
              AND status IN ('pending', 'running', 'submitted', 'completed')
            ORDER BY id DESC
            LIMIT 40
            """,
            (normalized_savepath,),
        )
        rows = cursor.fetchall()
    for row in rows:
        job = serialize_resource_job_row(row)
        if link_url and str(job.get("link_url", "") or "").strip() == link_url:
            return job
        if message_url and str(job.get("message_url", "") or "").strip() == message_url:
            return job
        if source_post_id and str(job.get("source_post_id", "") or "").strip() == source_post_id:
            return job
    return {}

def normalize_resource_job_clear_scope(scope: Any) -> str:
    normalized = str(scope or "").strip().lower()
    if normalized in ("completed", "done", "success"):
        return "completed"
    if normalized in ("failed", "fail", "error"):
        return "failed"
    if normalized in ("terminal", "finished", "completed_failed", "completed+failed", "all_done"):
        return "terminal"
    return "completed"


def _reset_resource_items_without_jobs(cursor: Any, resource_ids: List[int]) -> int:
    reset_item_count = 0
    now = now_text()
    for resource_id in resource_ids:
        cursor.execute("SELECT COUNT(1) FROM resource_jobs WHERE resource_id = ?", (resource_id,))
        remain_row = cursor.fetchone()
        remains = int(remain_row[0] if remain_row else 0)
        if remains > 0:
            continue
        cursor.execute(
            "UPDATE resource_items SET status = 'new', last_seen_at = ? WHERE id = ?",
            (now, resource_id),
        )
        reset_item_count += int(cursor.rowcount or 0)
    return reset_item_count


def _reset_resource_jobs_sequence_if_empty(cursor: Any) -> None:
    cursor.execute("SELECT COUNT(1) FROM resource_jobs")
    remaining_jobs_row = cursor.fetchone()
    remaining_jobs = int(remaining_jobs_row[0] if remaining_jobs_row else 0)
    if remaining_jobs == 0:
        cursor.execute("DELETE FROM sqlite_sequence WHERE name = 'resource_jobs'")


def delete_resource_job(job_id: int) -> Dict[str, int]:
    try:
        normalized_job_id = int(job_id or 0)
    except (TypeError, ValueError):
        normalized_job_id = 0
    if normalized_job_id <= 0:
        raise ValueError("任务 ID 无效")

    ensure_db()
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "SELECT resource_id, status FROM resource_jobs WHERE id = ?",
            (normalized_job_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise LookupError("任务不存在")

        resource_id = max(0, int(row[0] or 0))
        status = str(row[1] or "").strip().lower()
        if status not in ("completed", "failed"):
            raise RuntimeError("仅支持删除已完成或失败的导入任务")

        cursor.execute(
            "DELETE FROM resource_jobs WHERE id = ? AND status IN ('completed', 'failed')",
            (normalized_job_id,),
        )
        deleted_count = int(cursor.rowcount or 0)
        if deleted_count != 1:
            raise RuntimeError("任务状态已变化，请刷新后重试")

        reset_item_count = _reset_resource_items_without_jobs(
            cursor,
            [resource_id] if resource_id > 0 else [],
        )
        _reset_resource_jobs_sequence_if_empty(cursor)
        conn.commit()

    invalidate_resource_state_snapshot("resource-job-delete")
    touch_resource_jobs_state_signal("resource-job-delete")
    return {
        "job_id": normalized_job_id,
        "deleted": deleted_count,
        "reset_items": reset_item_count,
    }


def clear_resource_jobs(scope: str = "completed") -> Dict[str, int]:
    normalized_scope = normalize_resource_job_clear_scope(scope)
    if normalized_scope == "failed":
        target_statuses = ["failed"]
    elif normalized_scope == "terminal":
        target_statuses = ["completed", "failed"]
    else:
        target_statuses = ["completed"]

    ensure_db()
    with db_connection() as conn:
        cursor = conn.cursor()
        placeholders = ",".join(["?"] * len(target_statuses))
        cursor.execute(
            f"SELECT DISTINCT resource_id FROM resource_jobs WHERE status IN ({placeholders})",
            tuple(target_statuses),
        )
        affected_resource_ids = [int(row[0]) for row in cursor.fetchall() if row and row[0]]

        cursor.execute(
            f"DELETE FROM resource_jobs WHERE status IN ({placeholders})",
            tuple(target_statuses),
        )
        deleted_count = int(cursor.rowcount or 0)

        reset_item_count = _reset_resource_items_without_jobs(cursor, affected_resource_ids)
        _reset_resource_jobs_sequence_if_empty(cursor)

        conn.commit()
    if deleted_count > 0 or reset_item_count > 0:
        invalidate_resource_state_snapshot("resource-jobs-clear")
        touch_resource_jobs_state_signal("resource-jobs-clear")
    return {
        "scope": normalized_scope,
        "deleted": deleted_count,
        "reset_items": reset_item_count,
    }

def clear_completed_resource_jobs() -> Dict[str, int]:
    # Backward compatibility for existing callers.
    return clear_resource_jobs("completed")


def prune_resource_job_history(
    completed_keep: int = RESOURCE_JOB_COMPLETED_KEEP,
    failed_keep: int = RESOURCE_JOB_FAILED_KEEP,
) -> Dict[str, int]:
    keep_by_status = {
        "completed": max(100, min(10000, int(completed_keep or RESOURCE_JOB_COMPLETED_KEEP))),
        "failed": max(100, min(10000, int(failed_keep or RESOURCE_JOB_FAILED_KEEP))),
    }
    ensure_db()
    def prune_history() -> Dict[str, int]:
        with db_connection() as conn:
            cursor = conn.cursor()
            deleted: Dict[str, int] = {}
            for status, keep_count in keep_by_status.items():
                cursor.execute(
                    """
                    DELETE FROM resource_jobs
                    WHERE status = ?
                      AND id NOT IN (
                        SELECT id FROM resource_jobs
                        WHERE status = ?
                        ORDER BY id DESC
                        LIMIT ?
                      )
                    """,
                    (status, status, keep_count),
                )
                deleted[status] = int(cursor.rowcount or 0)
            conn.commit()
            return deleted

    deleted = retry_sqlite_locked(prune_history)
    if sum(deleted.values()) > 0:
        invalidate_resource_state_snapshot("resource-jobs-prune")
        touch_resource_jobs_state_signal("resource-jobs-prune")
    return {
        "completed": deleted.get("completed", 0),
        "failed": deleted.get("failed", 0),
        "deleted": sum(deleted.values()),
        "completed_keep": keep_by_status["completed"],
        "failed_keep": keep_by_status["failed"],
    }


def recover_stale_resource_jobs(max_age_seconds: int = RESOURCE_JOB_STALE_RECOVER_SECONDS) -> Dict[str, int]:
    ensure_db()
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, resource_id, started_at, updated_at, created_at, status_detail
            FROM resource_jobs
            WHERE status = 'running'
            ORDER BY id DESC
            LIMIT 200
            """
        )
        rows = cursor.fetchall()
        if not rows:
            return {"recovered": 0, "checked": 0}

        now_ts = time.time()
        limit_seconds = max(30, int(max_age_seconds or RESOURCE_JOB_STALE_RECOVER_SECONDS))
        recovered = 0
        checked = 0
        now_iso = now_text()
        recovered_resource_ids: Set[int] = set()

        for row in rows:
            data = sqlite_row_to_dict(row)
            job_id = max(0, int(data.get("id", 0) or 0))
            if job_id <= 0:
                continue
            if job_id in resource_job_running:
                continue
            checked += 1
            started_at = str(data.get("started_at", "") or "").strip()
            updated_at = str(data.get("updated_at", "") or "").strip()
            created_at = str(data.get("created_at", "") or "").strip()
            anchor_ts = (
                parse_resource_datetime_to_timestamp(started_at)
                or parse_resource_datetime_to_timestamp(updated_at)
                or parse_resource_datetime_to_timestamp(created_at)
            )
            age_seconds = (now_ts - anchor_ts) if anchor_ts > 0 else (limit_seconds + 1)
            if age_seconds < limit_seconds:
                continue
            detail = str(data.get("status_detail", "") or "").strip()
            stale_detail = f"运行超时已自动回收（>{limit_seconds} 秒）"
            if detail:
                stale_detail = f"{stale_detail}；原状态：{detail[:80]}"
            cursor.execute(
                """
                UPDATE resource_jobs
                SET status = 'failed', status_detail = ?, finished_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (stale_detail, now_iso, now_iso, job_id),
            )
            if int(cursor.rowcount or 0) > 0:
                recovered += 1
                recovered_resource_ids.add(max(0, int(data.get("resource_id", 0) or 0)))
                resource_refresh_pending.discard(job_id)
                resource_job_cancel_requested.discard(job_id)

        for resource_id in recovered_resource_ids:
            if resource_id <= 0:
                continue
            cursor.execute("SELECT COUNT(1) FROM resource_jobs WHERE resource_id = ? AND status = 'running'", (resource_id,))
            still_running_row = cursor.fetchone()
            still_running = int(still_running_row[0] if still_running_row else 0)
            if still_running > 0:
                continue
            cursor.execute(
                "UPDATE resource_items SET status = 'failed', last_seen_at = ? WHERE id = ?",
                (now_iso, resource_id),
            )

        conn.commit()
    if recovered > 0:
        invalidate_resource_state_snapshot("resource-jobs-recover-stale")
        touch_resource_jobs_state_signal("resource-jobs-recover-stale")
    return {"recovered": recovered, "checked": checked}

def recover_submitted_resource_jobs_without_monitor(limit: int = 200) -> Dict[str, int]:
    ensure_db()
    with db_connection() as conn:
        cursor = conn.cursor()
        query_limit = max(20, min(int(limit or 200), 1000))
        cursor.execute(
            """
            SELECT id, resource_id, status_detail
            FROM resource_jobs
            WHERE status = 'submitted' AND trim(monitor_task_name) = ''
            ORDER BY id DESC
            LIMIT ?
            """,
            (query_limit,),
        )
        rows = cursor.fetchall()
        if not rows:
            return {"recovered": 0, "checked": 0}

        now_iso = now_text()
        recovered = 0
        checked = 0
        recovered_resource_ids: Set[int] = set()
        hint_text = "当前保存路径未纳入文件夹监控，导入成功后不会自动生成 strm"

        for row in rows:
            data = sqlite_row_to_dict(row)
            job_id = max(0, int(data.get("id", 0) or 0))
            if job_id <= 0:
                continue
            checked += 1
            detail = str(data.get("status_detail", "") or "").strip()
            next_detail = detail or hint_text
            if hint_text not in next_detail:
                next_detail = f"{next_detail}；{hint_text}" if next_detail else hint_text
            cursor.execute(
                """
                UPDATE resource_jobs
                SET status = 'completed',
                    status_detail = ?,
                    finished_at = CASE WHEN trim(finished_at) = '' THEN ? ELSE finished_at END,
                    updated_at = ?
                WHERE id = ? AND status = 'submitted'
                """,
                (next_detail, now_iso, now_iso, job_id),
            )
            if int(cursor.rowcount or 0) > 0:
                recovered += 1
                recovered_resource_ids.add(max(0, int(data.get("resource_id", 0) or 0)))
                resource_refresh_pending.discard(job_id)
                resource_job_cancel_requested.discard(job_id)

        for resource_id in recovered_resource_ids:
            if resource_id <= 0:
                continue
            cursor.execute(
                "SELECT COUNT(1) FROM resource_jobs WHERE resource_id = ? AND status IN ('pending', 'running', 'submitted')",
                (resource_id,),
            )
            active_row = cursor.fetchone()
            active_count = int(active_row[0] if active_row else 0)
            if active_count > 0:
                continue
            cursor.execute(
                "SELECT COUNT(1) FROM resource_jobs WHERE resource_id = ? AND status = 'completed'",
                (resource_id,),
            )
            completed_row = cursor.fetchone()
            completed_count = int(completed_row[0] if completed_row else 0)
            if completed_count <= 0:
                continue
            cursor.execute(
                "UPDATE resource_items SET status = 'completed', last_seen_at = ? WHERE id = ?",
                (now_iso, resource_id),
            )

        conn.commit()
    if recovered > 0:
        invalidate_resource_state_snapshot("resource-jobs-recover-submitted")
        touch_resource_jobs_state_signal("resource-jobs-recover-submitted")
    return {"recovered": recovered, "checked": checked}

def _build_resource_job_insert(resource: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    now = now_text()
    link_type = resolve_resource_link_type(resource.get("link_type", "unknown"), resource.get("link_url", ""))
    try:
        from .providers.registry import get_by_link_type as _registry_get_by_link_type

        share_provider = _registry_get_by_link_type(link_type)
    except Exception:
        share_provider = None
    is_share_receive_link = bool(share_provider and share_provider.supports_share_receive)
    folder_id = str(data.get("folder_id", "")).strip()
    savepath = normalize_relative_path(data.get("savepath", ""))
    extra = normalize_share_selection_meta(data.get("share_selection", {})) if is_share_receive_link else {}
    custom_extra = data.get("extra", {})
    if isinstance(custom_extra, dict):
        extra = merge_json_object(extra, custom_extra)
    job_source = str(data.get("job_source", "") or "").strip()
    if job_source:
        extra["job_source"] = job_source
    elif not str(extra.get("job_source", "") or "").strip():
        # 默认归类为手动导入。自动化来源（订阅、Webhook 等）应在调用侧显式覆盖。
        extra["job_source"] = "manual_import"
    manual_receive_code = normalize_receive_code(data.get("receive_code", ""))
    if is_share_receive_link and manual_receive_code:
        extra["receive_code"] = manual_receive_code
    extra["snapshot"] = build_resource_job_snapshot(resource, link_type, manual_receive_code)
    manual_sharetitle = normalize_relative_path(data.get("sharetitle", ""))
    if manual_sharetitle:
        sharetitle = manual_sharetitle
    elif is_share_receive_link:
        sharetitle = normalize_relative_path(extra.get("auto_sharetitle", ""))
    elif link_type in ("magnet", "ed2k"):
        # 离线任务的目标目录已经体现在 savepath 中，不再追加文件名。
        sharetitle = ""
    else:
        sharetitle = normalize_relative_path(resource.get("title", ""))
    monitor_task_name = str(data.get("monitor_task_name", "")).strip()
    refresh_delay_seconds = max(0, int(data.get("refresh_delay_seconds", 0) or 0))
    auto_refresh = bool(data.get("auto_refresh", True))
    provider_label = (
        str(getattr(share_provider, "label", "") or share_provider.name).strip()
        if is_share_receive_link
        else str(
            extra.get("offline_provider_label", "")
            or extra.get("magnet_provider_label", "")
            or "115"
        ).strip()
    )
    resource_id = int(resource.get("id", 0) or 0)
    status_detail = f"等待提交到 {provider_label}"
    return {
        "resource_id": resource_id,
        "now": now,
        "status_detail": status_detail,
        "params": (
            resource_id,
            str(resource.get("title", "")).strip(),
            str(resource.get("link_url", "")).strip(),
            link_type,
            folder_id,
            savepath,
            sharetitle,
            monitor_task_name,
            refresh_delay_seconds,
            1 if auto_refresh else 0,
            status_detail,
            now,
            now,
            safe_json_dumps(extra),
        ),
    }


def create_resource_jobs(entries: List[Tuple[Dict[str, Any], Dict[str, Any]]]) -> List[int]:
    prepared = [_build_resource_job_insert(resource, data) for resource, data in (entries or [])]
    if not prepared:
        return []
    ensure_db()
    created: List[Dict[str, Any]] = []
    with db_connection() as conn:
        cursor = conn.cursor()
        for record in prepared:
            cursor.execute(
                """
                INSERT INTO resource_jobs(
                    resource_id, title, link_url, link_type, folder_id, savepath, sharetitle,
                    monitor_task_name, refresh_delay_seconds, auto_refresh, status, status_detail,
                    created_at, updated_at, extra_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
                """,
                record["params"],
            )
            job_id = int(cursor.lastrowid)
            resource_id = int(record["resource_id"])
            if resource_id > 0:
                update_resource_item_status(conn, resource_id, "queued")
            created.append({**record, "id": job_id})
        conn.commit()
    invalidate_resource_state_snapshot("resource-job-create")
    for record in created:
        touch_resource_jobs_state_signal(
            "resource-job-create",
            {
                "id": record["id"],
                "resource_id": record["resource_id"],
                "status": "pending",
                "status_detail": record["status_detail"],
                "updated_at": record["now"],
            },
        )
    return [int(record["id"]) for record in created]


def create_resource_job(resource: Dict[str, Any], data: Dict[str, Any]) -> int:
    return create_resource_jobs([(resource, data)])[0]


def update_resource_job(job_id: int, **fields: Any) -> None:
    if not fields:
        return
    ensure_db()
    with db_connection() as conn:
        cursor = conn.cursor()
        payload = dict(fields)
        payload["updated_at"] = now_text()
        sets = [f"{key} = ?" for key in payload.keys()]
        params = list(payload.values()) + [job_id]
        cursor.execute(f"UPDATE resource_jobs SET {', '.join(sets)} WHERE id = ?", params)
        updated = int(cursor.rowcount or 0)
        latest_job: Dict[str, Any] = {}
        if updated > 0:
            cursor.execute(
                "SELECT id, resource_id, status, status_detail, updated_at FROM resource_jobs WHERE id = ?",
                (job_id,),
            )
            row = cursor.fetchone()
            if row:
                data = sqlite_row_to_dict(row)
                latest_job = {
                    "id": max(0, int(data.get("id", 0) or 0)),
                    "resource_id": max(0, int(data.get("resource_id", 0) or 0)),
                    "status": str(data.get("status", "") or "").strip().lower(),
                    "status_detail": str(data.get("status_detail", "") or "").strip(),
                    "updated_at": str(data.get("updated_at", "") or "").strip(),
                }
        conn.commit()
    if updated > 0:
        invalidate_resource_state_snapshot("resource-job-update")
        touch_resource_jobs_state_signal("resource-job-update", latest_job)

def delete_resource_item(resource_id: int) -> None:
    ensure_db()
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM resource_jobs WHERE resource_id = ?", (resource_id,))
        cursor.execute("DELETE FROM resource_items WHERE id = ?", (resource_id,))
        conn.commit()
    invalidate_resource_state_snapshot("resource-item-delete")
    touch_resource_jobs_state_signal("resource-item-delete")
