from ..core import *  # noqa: F401,F403

def has_subscription_match(task_name: str, resource_id: int) -> bool:
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT 1 FROM subscription_matches WHERE task_name = ? AND resource_id = ? LIMIT 1",
        (str(task_name or "").strip(), int(resource_id or 0)),
    )
    row = cursor.fetchone()
    conn.close()
    return bool(row)

def create_subscription_match(
    task_name: str,
    resource_id: int,
    job_id: int,
    media_type: str,
    season: int = 0,
    episode: int = 0,
    total_episodes: int = 0,
    score: int = 0,
) -> None:
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO subscription_matches(
            task_name, resource_id, job_id, media_type, season, episode, total_episodes, score, matched_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(task_name or "").strip(),
            int(resource_id or 0),
            int(job_id or 0),
            str(media_type or "movie").strip().lower() or "movie",
            max(0, int(season or 0)),
            max(0, int(episode or 0)),
            max(0, int(total_episodes or 0)),
            int(score or 0),
            now_text(),
        ),
    )
    conn.commit()
    conn.close()

def load_subscription_episode_ledger(task_name: str, include_stale: bool = False) -> Dict[int, Dict[str, Any]]:
    normalized_task_name = str(task_name or "").strip()
    if not normalized_task_name:
        return {}
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    if include_stale:
        cursor.execute(
            """
            SELECT *
            FROM subscription_episode_ledger
            WHERE task_name = ?
            ORDER BY episode ASC
            """,
            (normalized_task_name,),
        )
    else:
        cursor.execute(
            """
            SELECT *
            FROM subscription_episode_ledger
            WHERE task_name = ? AND status = 'active'
            ORDER BY episode ASC
            """,
            (normalized_task_name,),
        )
    rows = cursor.fetchall()
    conn.close()

    ledger: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        data = sqlite_row_to_dict(row)
        episode_no = max(0, int(data.get("episode", 0) or 0))
        if episode_no <= 0:
            continue
        ledger[episode_no] = {
            "task_name": str(data.get("task_name", "") or "").strip(),
            "episode": episode_no,
            "season": max(0, int(data.get("season", 0) or 0)),
            "media_type": str(data.get("media_type", "tv") or "tv").strip().lower() or "tv",
            "best_score": max(0, int(data.get("best_score", 0) or 0)),
            "best_resolution": max(0, int(data.get("best_resolution", 0) or 0)),
            "source_fp": str(data.get("source_fp", "") or "").strip(),
            "content_fp": str(data.get("content_fp", "") or "").strip(),
            "link_type": str(data.get("link_type", "") or "").strip().lower(),
            "link_url": str(data.get("link_url", "") or "").strip(),
            "resource_id": max(0, int(data.get("resource_id", 0) or 0)),
            "job_id": max(0, int(data.get("job_id", 0) or 0)),
            "status": str(data.get("status", "active") or "active").strip().lower(),
            "first_seen_at": str(data.get("first_seen_at", "") or "").strip(),
            "updated_at": str(data.get("updated_at", "") or "").strip(),
        }
    return ledger

def reconcile_subscription_episode_ledger(task_name: str, existing_episodes: Set[int]) -> Dict[str, int]:
    normalized_task_name = str(task_name or "").strip()
    if not normalized_task_name:
        return {"activated": 0, "staled": 0}
    normalized_existing = {max(0, int(value or 0)) for value in (existing_episodes or set()) if max(0, int(value or 0)) > 0}

    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT episode, status
        FROM subscription_episode_ledger
        WHERE task_name = ?
        """,
        (normalized_task_name,),
    )
    rows = cursor.fetchall()
    if not rows:
        conn.close()
        return {"activated": 0, "staled": 0}

    now_iso = now_text()
    activate_rows: List[Tuple[str, str, int]] = []
    stale_rows: List[Tuple[str, str, int]] = []
    for row in rows:
        episode_no = max(0, int(row["episode"] or 0))
        if episode_no <= 0:
            continue
        current_status = str(row["status"] or "active").strip().lower() or "active"
        target_status = "active" if episode_no in normalized_existing else "stale"
        if current_status == target_status:
            continue
        payload = (target_status, now_iso, normalized_task_name, episode_no)
        if target_status == "active":
            activate_rows.append(payload)
        else:
            stale_rows.append(payload)

    if activate_rows:
        cursor.executemany(
            """
            UPDATE subscription_episode_ledger
            SET status = ?, updated_at = ?
            WHERE task_name = ? AND episode = ?
            """,
            activate_rows,
        )
    if stale_rows:
        cursor.executemany(
            """
            UPDATE subscription_episode_ledger
            SET status = ?, updated_at = ?
            WHERE task_name = ? AND episode = ?
            """,
            stale_rows,
        )
    conn.commit()
    conn.close()
    return {"activated": len(activate_rows), "staled": len(stale_rows)}

def upsert_subscription_episode_ledger(
    task_name: str,
    episodes: Set[int],
    media_type: str = "tv",
    season: int = 0,
    score: int = 0,
    resolution: int = 0,
    source_fp: str = "",
    content_fp: str = "",
    link_type: str = "",
    link_url: str = "",
    resource_id: int = 0,
    job_id: int = 0,
) -> int:
    normalized_task_name = str(task_name or "").strip()
    if not normalized_task_name:
        return 0
    normalized_episodes = sorted({max(0, int(value or 0)) for value in (episodes or set()) if max(0, int(value or 0)) > 0})
    if not normalized_episodes:
        return 0

    normalized_media_type = str(media_type or "tv").strip().lower() or "tv"
    normalized_season = max(0, int(season or 0))
    normalized_score = max(0, int(score or 0))
    normalized_resolution = max(0, int(resolution or 0))
    normalized_source_fp = str(source_fp or "").strip()
    normalized_content_fp = str(content_fp or "").strip()
    normalized_link_type = str(link_type or "").strip().lower()
    normalized_link_url = str(link_url or "").strip()
    normalized_resource_id = max(0, int(resource_id or 0))
    normalized_job_id = max(0, int(job_id or 0))
    now_iso = now_text()

    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    changed = 0
    for episode_no in normalized_episodes:
        cursor.execute(
            """
            SELECT best_score, best_resolution, first_seen_at, status
            FROM subscription_episode_ledger
            WHERE task_name = ? AND episode = ?
            """,
            (normalized_task_name, episode_no),
        )
        row = cursor.fetchone()
        if row:
            existing_score = max(0, int(row["best_score"] or 0))
            existing_resolution = max(0, int(row["best_resolution"] or 0))
            existing_first_seen = str(row["first_seen_at"] or "").strip() or now_iso
            existing_status = str(row["status"] or "active").strip().lower() or "active"

            best_score_value = existing_score
            best_resolution_value = existing_resolution
            if normalized_resolution > existing_resolution:
                best_resolution_value = normalized_resolution
                best_score_value = max(existing_score, normalized_score)
            elif normalized_resolution == existing_resolution:
                best_score_value = max(existing_score, normalized_score)
            elif existing_resolution <= 0:
                best_score_value = max(existing_score, normalized_score)

            status_value = "active"
            cursor.execute(
                """
                UPDATE subscription_episode_ledger
                SET season = ?, media_type = ?, best_score = ?, best_resolution = ?,
                    source_fp = ?, content_fp = ?, link_type = ?, link_url = ?,
                    resource_id = ?, job_id = ?, status = ?, first_seen_at = ?, updated_at = ?
                WHERE task_name = ? AND episode = ?
                """,
                (
                    normalized_season,
                    normalized_media_type,
                    best_score_value,
                    best_resolution_value,
                    normalized_source_fp,
                    normalized_content_fp,
                    normalized_link_type,
                    normalized_link_url,
                    normalized_resource_id,
                    normalized_job_id,
                    status_value,
                    existing_first_seen,
                    now_iso,
                    normalized_task_name,
                    episode_no,
                ),
            )
            if cursor.rowcount > 0 and (
                best_score_value != existing_score
                or best_resolution_value != existing_resolution
                or existing_status != "active"
            ):
                changed += 1
        else:
            cursor.execute(
                """
                INSERT INTO subscription_episode_ledger(
                    task_name, episode, season, media_type, best_score, best_resolution,
                    source_fp, content_fp, link_type, link_url, resource_id, job_id,
                    status, first_seen_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    normalized_task_name,
                    episode_no,
                    normalized_season,
                    normalized_media_type,
                    normalized_score,
                    normalized_resolution,
                    normalized_source_fp,
                    normalized_content_fp,
                    normalized_link_type,
                    normalized_link_url,
                    normalized_resource_id,
                    normalized_job_id,
                    now_iso,
                    now_iso,
                ),
            )
            if cursor.rowcount > 0:
                changed += 1
    conn.commit()
    conn.close()
    return changed

def prune_subscription_state_for_missing_tasks(task_names: List[str]) -> None:
    normalized = {str(name or "").strip() for name in task_names if str(name or "").strip()}
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    if not normalized:
        cursor.execute("DELETE FROM subscription_task_state")
        cursor.execute("DELETE FROM subscription_matches")
        cursor.execute("DELETE FROM subscription_episode_ledger")
        cursor.execute("DELETE FROM subscription_channel_search_watermarks")
        conn.commit()
        conn.close()
        return
    placeholders = ",".join("?" for _ in normalized)
    params = list(normalized)
    cursor.execute(f"DELETE FROM subscription_task_state WHERE task_name NOT IN ({placeholders})", params)
    cursor.execute(f"DELETE FROM subscription_matches WHERE task_name NOT IN ({placeholders})", params)
    cursor.execute(f"DELETE FROM subscription_episode_ledger WHERE task_name NOT IN ({placeholders})", params)
    cursor.execute(f"DELETE FROM subscription_channel_search_watermarks WHERE task_name NOT IN ({placeholders})", params)
    conn.commit()
    conn.close()

def load_subscription_channel_search_watermarks(
    task_name: str,
    channel_ids: Optional[List[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    normalized_task_name = str(task_name or "").strip()
    if not normalized_task_name:
        return {}
    normalized_channels = [
        normalize_telegram_channel_id_from_input(channel_id)
        for channel_id in (channel_ids or [])
    ]
    normalized_channels = [channel_id for channel_id in normalized_channels if channel_id]

    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    if normalized_channels:
        placeholders = ",".join("?" for _ in normalized_channels)
        cursor.execute(
            f"""
            SELECT task_name, channel_id, last_post_cursor, last_published_at, last_run_at, updated_at
            FROM subscription_channel_search_watermarks
            WHERE task_name = ? AND channel_id IN ({placeholders})
            """,
            [normalized_task_name] + normalized_channels,
        )
    else:
        cursor.execute(
            """
            SELECT task_name, channel_id, last_post_cursor, last_published_at, last_run_at, updated_at
            FROM subscription_channel_search_watermarks
            WHERE task_name = ?
            """,
            (normalized_task_name,),
        )
    rows = cursor.fetchall()
    conn.close()

    result: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, sqlite3.Row):
            channel_id = normalize_telegram_channel_id_from_input(row["channel_id"])
            if not channel_id:
                continue
            result[channel_id] = {
                "task_name": str(row["task_name"] or "").strip(),
                "channel_id": channel_id,
                "last_post_cursor": max(0, int(row["last_post_cursor"] or 0)),
                "last_published_at": str(row["last_published_at"] or "").strip(),
                "last_run_at": str(row["last_run_at"] or "").strip(),
                "updated_at": str(row["updated_at"] or "").strip(),
            }
            continue
        values = list(row or [])
        if len(values) < 6:
            continue
        channel_id = normalize_telegram_channel_id_from_input(values[1])
        if not channel_id:
            continue
        result[channel_id] = {
            "task_name": str(values[0] or "").strip(),
            "channel_id": channel_id,
            "last_post_cursor": max(0, int(values[2] or 0)),
            "last_published_at": str(values[3] or "").strip(),
            "last_run_at": str(values[4] or "").strip(),
            "updated_at": str(values[5] or "").strip(),
        }
    return result

def upsert_subscription_channel_search_watermarks(
    task_name: str,
    channel_watermarks: Dict[str, Dict[str, Any]],
    only_increase: bool = True,
) -> int:
    normalized_task_name = str(task_name or "").strip()
    if not normalized_task_name:
        return 0
    if not isinstance(channel_watermarks, dict) or not channel_watermarks:
        return 0

    normalized_payload: Dict[str, Dict[str, Any]] = {}
    for raw_channel_id, raw_meta in channel_watermarks.items():
        channel_id = normalize_telegram_channel_id_from_input(raw_channel_id)
        if not channel_id or not isinstance(raw_meta, dict):
            continue
        last_post_cursor = max(
            0,
            int(raw_meta.get("last_post_cursor", raw_meta.get("cursor", 0)) or 0),
        )
        last_published_at = str(raw_meta.get("last_published_at", raw_meta.get("published_at", "")) or "").strip()
        last_run_at = str(raw_meta.get("last_run_at", "") or "").strip()
        normalized_payload[channel_id] = {
            "last_post_cursor": last_post_cursor,
            "last_published_at": last_published_at,
            "last_run_at": last_run_at,
        }
    if not normalized_payload:
        return 0

    existing_rows = load_subscription_channel_search_watermarks(
        normalized_task_name,
        list(normalized_payload.keys()),
    )
    now_iso = now_text()

    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    written = 0
    for channel_id, payload in normalized_payload.items():
        target_cursor = max(0, int(payload.get("last_post_cursor", 0) or 0))
        target_published_at = str(payload.get("last_published_at", "") or "").strip()
        target_run_at = str(payload.get("last_run_at", "") or "").strip() or now_iso

        if only_increase:
            existing = existing_rows.get(channel_id, {})
            existing_cursor = max(0, int(existing.get("last_post_cursor", 0) or 0))
            existing_published_at = str(existing.get("last_published_at", "") or "").strip()
            existing_published_ts = parse_resource_datetime_to_timestamp(existing_published_at)
            target_published_ts = parse_resource_datetime_to_timestamp(target_published_at)
            if target_cursor < existing_cursor:
                continue
            if target_cursor == existing_cursor:
                if target_published_ts > 0 and existing_published_ts > 0 and target_published_ts <= existing_published_ts:
                    continue
                if target_published_ts <= 0 and not target_published_at and not target_run_at:
                    continue

        cursor.execute(
            """
            INSERT INTO subscription_channel_search_watermarks(
                task_name, channel_id, last_post_cursor, last_published_at, last_run_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_name, channel_id)
            DO UPDATE SET
                last_post_cursor = excluded.last_post_cursor,
                last_published_at = excluded.last_published_at,
                last_run_at = excluded.last_run_at,
                updated_at = excluded.updated_at
            """,
            (
                normalized_task_name,
                channel_id,
                target_cursor,
                target_published_at,
                target_run_at,
                now_iso,
            ),
        )
        written += 1
    conn.commit()
    conn.close()
    return written

def load_subscription_channel_support_stats(
    channel_ids: Optional[List[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    normalized_channels = [
        normalize_telegram_channel_id_from_input(channel_id)
        for channel_id in (channel_ids or [])
    ]
    normalized_channels = [channel_id for channel_id in normalized_channels if channel_id]

    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    if normalized_channels:
        placeholders = ",".join("?" for _ in normalized_channels)
        cursor.execute(
            f"""
            SELECT
                channel_id, channel_name, searched_runs, matched_runs, matched_items,
                error_runs, incremental_stop_hits, pages_scanned, last_task_name,
                last_provider, last_trigger, last_error, last_searched_at,
                last_matched_at, updated_at
            FROM subscription_channel_support_stats
            WHERE channel_id IN ({placeholders})
            """,
            normalized_channels,
        )
    else:
        cursor.execute(
            """
            SELECT
                channel_id, channel_name, searched_runs, matched_runs, matched_items,
                error_runs, incremental_stop_hits, pages_scanned, last_task_name,
                last_provider, last_trigger, last_error, last_searched_at,
                last_matched_at, updated_at
            FROM subscription_channel_support_stats
            """
        )
    rows = cursor.fetchall()
    conn.close()

    result: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        data = sqlite_row_to_dict(row)
        channel_id = normalize_telegram_channel_id_from_input(data.get("channel_id", ""))
        if not channel_id:
            continue
        result[channel_id] = {
            "channel_id": channel_id,
            "channel_name": str(data.get("channel_name", "") or "").strip(),
            "searched_runs": max(0, int(data.get("searched_runs", 0) or 0)),
            "matched_runs": max(0, int(data.get("matched_runs", 0) or 0)),
            "matched_items": max(0, int(data.get("matched_items", 0) or 0)),
            "error_runs": max(0, int(data.get("error_runs", 0) or 0)),
            "incremental_stop_hits": max(0, int(data.get("incremental_stop_hits", 0) or 0)),
            "pages_scanned": max(0, int(data.get("pages_scanned", 0) or 0)),
            "last_task_name": str(data.get("last_task_name", "") or "").strip(),
            "last_provider": str(data.get("last_provider", "") or "").strip(),
            "last_trigger": str(data.get("last_trigger", "") or "").strip(),
            "last_error": str(data.get("last_error", "") or "").strip(),
            "last_searched_at": str(data.get("last_searched_at", "") or "").strip(),
            "last_matched_at": str(data.get("last_matched_at", "") or "").strip(),
            "updated_at": str(data.get("updated_at", "") or "").strip(),
        }
    return result

def upsert_subscription_channel_support_stats(
    channel_stats: Dict[str, Dict[str, Any]],
    task_name: str = "",
    provider: str = "",
    trigger: str = "",
) -> int:
    if not isinstance(channel_stats, dict) or not channel_stats:
        return 0
    normalized_task_name = str(task_name or "").strip()
    normalized_provider = normalize_subscription_provider(provider, fallback=str(provider or "").strip() or "unknown")
    normalized_trigger = str(trigger or "").strip().lower() or "manual"
    now_iso = now_text()

    normalized_payload: Dict[str, Dict[str, Any]] = {}
    for raw_channel_id, raw_payload in channel_stats.items():
        channel_id = normalize_telegram_channel_id_from_input(raw_channel_id)
        if not channel_id or not isinstance(raw_payload, dict):
            continue
        normalized_payload[channel_id] = {
            "channel_name": str(raw_payload.get("channel_name", raw_payload.get("name", "")) or "").strip(),
            "searched_runs": max(0, int(raw_payload.get("searched_runs", raw_payload.get("searched_count", 0)) or 0)),
            "matched_runs": max(0, int(raw_payload.get("matched_runs", raw_payload.get("matched_count", 0)) or 0)),
            "matched_items": max(0, int(raw_payload.get("matched_items", raw_payload.get("item_count", 0)) or 0)),
            "error_runs": max(0, int(raw_payload.get("error_runs", raw_payload.get("error_count", 0)) or 0)),
            "incremental_stop_hits": max(
                0,
                int(raw_payload.get("incremental_stop_hits", raw_payload.get("incremental_stop_count", 0)) or 0),
            ),
            "pages_scanned": max(0, int(raw_payload.get("pages_scanned", 0) or 0)),
            "last_error": str(raw_payload.get("last_error", raw_payload.get("error", "")) or "").strip(),
            "last_searched_at": str(raw_payload.get("last_searched_at", "") or "").strip(),
            "last_matched_at": str(raw_payload.get("last_matched_at", "") or "").strip(),
        }
    if not normalized_payload:
        return 0

    existing_rows = load_subscription_channel_support_stats(list(normalized_payload.keys()))
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    written = 0
    for channel_id, payload in normalized_payload.items():
        existing = existing_rows.get(channel_id, {})
        searched_runs = max(0, int(existing.get("searched_runs", 0) or 0)) + max(0, int(payload.get("searched_runs", 0) or 0))
        matched_runs = max(0, int(existing.get("matched_runs", 0) or 0)) + max(0, int(payload.get("matched_runs", 0) or 0))
        matched_items = max(0, int(existing.get("matched_items", 0) or 0)) + max(0, int(payload.get("matched_items", 0) or 0))
        error_runs = max(0, int(existing.get("error_runs", 0) or 0)) + max(0, int(payload.get("error_runs", 0) or 0))
        incremental_stop_hits = max(0, int(existing.get("incremental_stop_hits", 0) or 0)) + max(
            0,
            int(payload.get("incremental_stop_hits", 0) or 0),
        )
        pages_scanned = max(0, int(existing.get("pages_scanned", 0) or 0)) + max(0, int(payload.get("pages_scanned", 0) or 0))
        channel_name = str(payload.get("channel_name", "") or "").strip() or str(existing.get("channel_name", "") or "").strip() or channel_id
        last_error = str(payload.get("last_error", "") or "").strip() or str(existing.get("last_error", "") or "").strip()
        last_searched_at = (
            str(payload.get("last_searched_at", "") or "").strip()
            or now_iso
        )
        last_matched_at = (
            str(payload.get("last_matched_at", "") or "").strip()
            or (now_iso if int(payload.get("matched_runs", 0) or 0) > 0 else str(existing.get("last_matched_at", "") or "").strip())
        )
        cursor.execute(
            """
            INSERT INTO subscription_channel_support_stats(
                channel_id, channel_name, searched_runs, matched_runs, matched_items,
                error_runs, incremental_stop_hits, pages_scanned, last_task_name,
                last_provider, last_trigger, last_error, last_searched_at,
                last_matched_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(channel_id)
            DO UPDATE SET
                channel_name = excluded.channel_name,
                searched_runs = excluded.searched_runs,
                matched_runs = excluded.matched_runs,
                matched_items = excluded.matched_items,
                error_runs = excluded.error_runs,
                incremental_stop_hits = excluded.incremental_stop_hits,
                pages_scanned = excluded.pages_scanned,
                last_task_name = excluded.last_task_name,
                last_provider = excluded.last_provider,
                last_trigger = excluded.last_trigger,
                last_error = excluded.last_error,
                last_searched_at = excluded.last_searched_at,
                last_matched_at = excluded.last_matched_at,
                updated_at = excluded.updated_at
            """,
            (
                channel_id,
                channel_name,
                searched_runs,
                matched_runs,
                matched_items,
                error_runs,
                incremental_stop_hits,
                pages_scanned,
                normalized_task_name,
                normalized_provider,
                normalized_trigger,
                last_error,
                last_searched_at,
                last_matched_at,
                now_iso,
            ),
        )
        written += 1
    conn.commit()
    conn.close()
    return written

def load_subscription_task_state(task_name: str, media_type: str = "movie") -> Dict[str, Any]:
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM subscription_task_state WHERE task_name = ?", (str(task_name or "").strip(),))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return {
            "task_name": str(task_name or "").strip(),
            "media_type": str(media_type or "movie").strip().lower() or "movie",
            "status": "idle",
            "progress": 0,
            "detail": "",
            "last_run_at": "",
            "last_success_at": "",
            "last_error": "",
            "last_episode": 0,
            "total_episodes": 0,
            "matched_resource_id": 0,
            "matched_resource_title": "",
            "matched_score": 0,
            "queued_job_id": 0,
            "stats": {},
            "updated_at": "",
        }
    data = sqlite_row_to_dict(row)
    data["stats"] = safe_json_loads(data.get("stats_json"), {})
    return {
        "task_name": str(data.get("task_name", "") or "").strip(),
        "media_type": str(data.get("media_type", "movie") or "movie").strip().lower() or "movie",
        "status": str(data.get("status", "idle") or "idle").strip().lower(),
        "progress": max(0, min(100, int(data.get("progress", 0) or 0))),
        "detail": str(data.get("detail", "") or "").strip(),
        "last_run_at": str(data.get("last_run_at", "") or "").strip(),
        "last_success_at": str(data.get("last_success_at", "") or "").strip(),
        "last_error": str(data.get("last_error", "") or "").strip(),
        "last_episode": max(0, int(data.get("last_episode", 0) or 0)),
        "total_episodes": max(0, int(data.get("total_episodes", 0) or 0)),
        "matched_resource_id": max(0, int(data.get("matched_resource_id", 0) or 0)),
        "matched_resource_title": str(data.get("matched_resource_title", "") or "").strip(),
        "matched_score": max(0, int(data.get("matched_score", 0) or 0)),
        "queued_job_id": max(0, int(data.get("queued_job_id", 0) or 0)),
        "stats": data["stats"] if isinstance(data["stats"], dict) else {},
        "updated_at": str(data.get("updated_at", "") or "").strip(),
    }

def upsert_subscription_task_state(task_name: str, **fields: Any) -> None:
    task_key = str(task_name or "").strip()
    if not task_key:
        return
    max_attempts = 4
    for attempt in range(max_attempts):
        conn: Optional[sqlite3.Connection] = None
        try:
            current = load_subscription_task_state(task_key)
            ensure_db()
            conn = open_db()
            cursor = conn.cursor()
            payload = {**current}
            payload.update(fields)
            stats_value = payload.get("stats", {})
            if not isinstance(stats_value, dict):
                stats_value = {}
            now = now_text()
            cursor.execute(
                """
                INSERT OR REPLACE INTO subscription_task_state(
                    task_name, media_type, status, progress, detail, last_run_at, last_success_at, last_error,
                    last_episode, total_episodes, matched_resource_id, matched_resource_title, matched_score,
                    queued_job_id, stats_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_key,
                    str(payload.get("media_type", "movie") or "movie").strip().lower() or "movie",
                    str(payload.get("status", "idle") or "idle").strip().lower(),
                    max(0, min(100, int(payload.get("progress", 0) or 0))),
                    str(payload.get("detail", "") or "").strip(),
                    str(payload.get("last_run_at", "") or "").strip(),
                    str(payload.get("last_success_at", "") or "").strip(),
                    str(payload.get("last_error", "") or "").strip(),
                    max(0, int(payload.get("last_episode", 0) or 0)),
                    max(0, int(payload.get("total_episodes", 0) or 0)),
                    max(0, int(payload.get("matched_resource_id", 0) or 0)),
                    str(payload.get("matched_resource_title", "") or "").strip(),
                    max(0, int(payload.get("matched_score", 0) or 0)),
                    max(0, int(payload.get("queued_job_id", 0) or 0)),
                    safe_json_dumps(stats_value),
                    now,
                ),
            )
            conn.commit()
            return
        except sqlite3.OperationalError as exc:
            message = str(exc or "").lower()
            retryable = "locked" in message
            if (not retryable) or attempt >= max_attempts - 1:
                raise
            time.sleep(0.15 * (attempt + 1))
        finally:
            if conn is not None:
                conn.close()

def list_subscription_task_runtime(cfg: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    cfg = cfg or get_config()
    tasks = cfg.get("subscription_tasks", []) if isinstance(cfg.get("subscription_tasks"), list) else []
    global_running = bool(subscription_status.get("running"))
    current_running_task = str(subscription_status.get("current_task", "") or "").strip()
    result: List[Dict[str, Any]] = []
    for raw_task in tasks:
        task = normalize_subscription_task(raw_task or {})
        if not task.get("name"):
            continue
        state = load_subscription_task_state(task["name"], task.get("media_type", "movie"))
        state_status = str(state.get("status", "idle") or "idle").strip().lower()
        if state_status == "running":
            is_current_active_task = global_running and current_running_task == task["name"]
            if not is_current_active_task:
                stale_detail = "检测到历史运行状态残留，已自动回收（可重新运行）"
                try:
                    upsert_subscription_task_state(
                        task["name"],
                        media_type=task.get("media_type", "movie"),
                        status="failed",
                        progress=100,
                        detail=stale_detail,
                        last_error=stale_detail,
                    )
                    state = load_subscription_task_state(task["name"], task.get("media_type", "movie"))
                except Exception:
                    state = {
                        **state,
                        "status": "failed",
                        "progress": 100,
                        "detail": stale_detail,
                        "last_error": stale_detail,
                    }
        merged = {
            **task,
            "status": state.get("status", "idle"),
            "progress": state.get("progress", 0),
            "detail": state.get("detail", ""),
            "last_run_at": state.get("last_run_at", ""),
            "last_success_at": state.get("last_success_at", ""),
            "last_error": state.get("last_error", ""),
            "last_episode": state.get("last_episode", 0),
            "matched_resource_id": state.get("matched_resource_id", 0),
            "matched_resource_title": state.get("matched_resource_title", ""),
            "matched_score": state.get("matched_score", 0),
            "queued_job_id": state.get("queued_job_id", 0),
            "stats": state.get("stats", {}),
            "next_run": subscription_next_run.get(task["name"], ""),
        }
        if str(task.get("media_type", "movie") or "movie").strip().lower() == "tv":
            merged["total_episodes"] = resolve_subscription_tv_total_episodes(
                task,
                state_total=max(0, int(state.get("total_episodes", 0) or 0)),
            )
        elif merged["total_episodes"] <= 0:
            merged["total_episodes"] = state.get("total_episodes", 0)
        result.append(merged)
    return result

def find_subscription_task_match_candidate(task: Dict[str, Any], last_episode: int = 0, limit: int = 400) -> Dict[str, Any]:
    query_tokens = build_subscription_query_tokens(task)
    if not query_tokens:
        return {}
    ensure_db()
    conn = open_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT * FROM resource_items
        WHERE link_url <> ''
        ORDER BY CASE WHEN published_at <> '' THEN published_at ELSE created_at END DESC, id DESC
        LIMIT ?
        """,
        (max(80, min(1200, int(limit or 400))),),
    )
    rows = cursor.fetchall()
    conn.close()

    provider = normalize_subscription_provider(task.get("provider", "115"), fallback="115")
    min_score = (
        int(SUBSCRIPTION_QUARK_MIN_SCORE)
        if provider == "quark"
        else max(30, min(100, int(task.get("min_score", SUBSCRIPTION_MIN_SCORE) or SUBSCRIPTION_MIN_SCORE)))
    )
    media_type = str(task.get("media_type", "movie") or "movie").strip().lower()
    supported_link_types = {"quark"} if provider == "quark" else {"magnet", "115share"}
    candidates: List[Dict[str, Any]] = []
    for row in rows:
        item = serialize_resource_item_row(row)
        item_id = int(item.get("id", 0) or 0)
        if item_id <= 0:
            continue
        link_type = resolve_resource_link_type(item.get("link_type", ""), item.get("link_url", ""))
        if link_type not in supported_link_types:
            continue
        media_match, _ = match_subscription_media_type(task, item)
        if not media_match:
            continue
        matched_before = has_subscription_match(task.get("name", ""), item_id)
        scored = (
            score_subscription_candidate_quark(task, item, query_tokens, last_episode)
            if provider == "quark"
            else score_subscription_candidate(task, item, query_tokens, last_episode)
        )
        if provider == "quark" and not bool(scored.get("title_match", False)):
            continue
        if matched_before:
            if media_type != "tv":
                continue
            if int(scored.get("episode", 0) or 0) <= 0 and int(scored.get("range_end", 0) or 0) <= 0:
                continue
            scored["matched_before"] = True
        if scored["score"] < min_score:
            continue
        candidates.append(scored)

    if not candidates:
        return {}

    if media_type == "tv":
        candidates.sort(
            key=lambda candidate: (
                int(candidate.get("episode", 0) or 0),
                int(candidate.get("score", 0) or 0),
                get_resource_item_sort_key(candidate.get("item", {})),
            ),
            reverse=True,
        )
    else:
        candidates.sort(
            key=lambda candidate: (
                int(candidate.get("score", 0) or 0),
                get_resource_item_sort_key(candidate.get("item", {})),
            ),
            reverse=True,
        )
    return candidates[0]
