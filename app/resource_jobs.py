from .core import *  # noqa: F401,F403

def list_resource_jobs(limit: int = 80) -> List[Dict[str, Any]]:
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM resource_jobs ORDER BY id DESC LIMIT ?", (max(1, min(limit, 500)),))
    rows = cursor.fetchall()
    conn.close()
    return [serialize_resource_job_row(row) for row in rows]

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
    conn = open_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM resource_jobs WHERE id = ?", (job_id,))
    row = cursor.fetchone()
    conn.close()
    return serialize_resource_job_row(row, include_private=include_private)

def count_resource_jobs(status: str = "") -> int:
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    normalized_status = str(status or "").strip().lower()
    if normalized_status:
        cursor.execute("SELECT COUNT(1) FROM resource_jobs WHERE status = ?", (normalized_status,))
    else:
        cursor.execute("SELECT COUNT(1) FROM resource_jobs")
    row = cursor.fetchone()
    conn.close()
    return int(row[0] if row else 0)

def find_existing_resource_job(resource: Dict[str, Any], savepath: str) -> Dict[str, Any]:
    ensure_db()
    conn = open_db()
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
    conn.close()
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

def clear_resource_jobs(scope: str = "completed") -> Dict[str, int]:
    normalized_scope = normalize_resource_job_clear_scope(scope)
    if normalized_scope == "failed":
        target_statuses = ["failed"]
    elif normalized_scope == "terminal":
        target_statuses = ["completed", "failed"]
    else:
        target_statuses = ["completed"]

    ensure_db()
    conn = open_db()
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

    reset_item_count = 0
    now = now_text()
    for resource_id in affected_resource_ids:
        cursor.execute("SELECT COUNT(1) FROM resource_jobs WHERE resource_id = ?", (resource_id,))
        remain_row = cursor.fetchone()
        remains = int(remain_row[0] if remain_row else 0)
        if remains == 0:
            cursor.execute(
                "UPDATE resource_items SET status = 'new', last_seen_at = ? WHERE id = ?",
                (now, resource_id),
            )
            reset_item_count += int(cursor.rowcount or 0)

    # If the task table has been fully cleared, reset the AUTOINCREMENT counter
    # so the next created task starts from 1 again.
    cursor.execute("SELECT COUNT(1) FROM resource_jobs")
    remaining_jobs_row = cursor.fetchone()
    remaining_jobs = int(remaining_jobs_row[0] if remaining_jobs_row else 0)
    if remaining_jobs == 0:
        cursor.execute("DELETE FROM sqlite_sequence WHERE name = 'resource_jobs'")

    conn.commit()
    conn.close()
    return {
        "scope": normalized_scope,
        "deleted": deleted_count,
        "reset_items": reset_item_count,
    }

def clear_completed_resource_jobs() -> Dict[str, int]:
    # Backward compatibility for existing callers.
    return clear_resource_jobs("completed")

def recover_stale_resource_jobs(max_age_seconds: int = RESOURCE_JOB_STALE_RECOVER_SECONDS) -> Dict[str, int]:
    ensure_db()
    conn = open_db()
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
        conn.close()
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
    conn.close()
    return {"recovered": recovered, "checked": checked}

def recover_submitted_resource_jobs_without_monitor(limit: int = 200) -> Dict[str, int]:
    ensure_db()
    conn = open_db()
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
        conn.close()
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
    conn.close()
    return {"recovered": recovered, "checked": checked}

def create_resource_job(resource: Dict[str, Any], data: Dict[str, Any]) -> int:
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    now = now_text()
    link_type = resolve_resource_link_type(resource.get("link_type", "unknown"), resource.get("link_url", ""))
    folder_id = str(data.get("folder_id", "")).strip()
    savepath = normalize_relative_path(data.get("savepath", ""))
    extra = normalize_share_selection_meta(data.get("share_selection", {})) if link_type in ("115share", "quark") else {}
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
    if link_type in ("115share", "quark") and manual_receive_code:
        extra["receive_code"] = manual_receive_code
    extra["snapshot"] = build_resource_job_snapshot(resource, link_type, manual_receive_code)
    manual_sharetitle = normalize_relative_path(data.get("sharetitle", ""))
    if manual_sharetitle:
        sharetitle = manual_sharetitle
    elif link_type == "115share":
        sharetitle = normalize_relative_path(extra.get("auto_sharetitle", ""))
    elif link_type == "magnet":
        # 磁力任务默认不绑定子目录提示，避免把原始链接文本误当目录。
        sharetitle = ""
    elif link_type == "quark":
        sharetitle = normalize_relative_path(extra.get("auto_sharetitle", ""))
    else:
        sharetitle = normalize_relative_path(resource.get("title", ""))
    monitor_task_name = str(data.get("monitor_task_name", "")).strip()
    refresh_delay_seconds = max(0, int(data.get("refresh_delay_seconds", 0) or 0))
    auto_refresh = bool(data.get("auto_refresh", True))
    provider_label = "夸克" if link_type == "quark" else "115"
    cursor.execute(
        """
        INSERT INTO resource_jobs(
            resource_id, title, link_url, link_type, folder_id, savepath, sharetitle,
            monitor_task_name, refresh_delay_seconds, auto_refresh, status, status_detail,
            created_at, updated_at, extra_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
        """,
        (
            int(resource.get("id", 0) or 0),
            str(resource.get("title", "")).strip(),
            str(resource.get("link_url", "")).strip(),
            link_type,
            folder_id,
            savepath,
            sharetitle,
            monitor_task_name,
            refresh_delay_seconds,
            1 if auto_refresh else 0,
            f"等待提交到 {provider_label}",
            now,
            now,
            safe_json_dumps(extra),
        ),
    )
    job_id = int(cursor.lastrowid)
    resource_id = int(resource.get("id", 0) or 0)
    if resource_id > 0:
        update_resource_item_status(conn, resource_id, "queued")
    conn.commit()
    conn.close()
    return job_id

def update_resource_job(job_id: int, **fields: Any) -> None:
    if not fields:
        return
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    payload = dict(fields)
    payload["updated_at"] = now_text()
    sets = [f"{key} = ?" for key in payload.keys()]
    params = list(payload.values()) + [job_id]
    cursor.execute(f"UPDATE resource_jobs SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()
    conn.close()

def delete_resource_item(resource_id: int) -> None:
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM resource_jobs WHERE resource_id = ?", (resource_id,))
    cursor.execute("DELETE FROM resource_items WHERE id = ?", (resource_id,))
    conn.commit()
    conn.close()
