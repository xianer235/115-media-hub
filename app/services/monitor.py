from ..background import submit_background
from ..core import *  # noqa: F401,F403
from ..db import retry_sqlite_locked
from ..memory import release_process_memory
from .notify import push_monitor_success_notification
from .strm_files import delete_managed_strm_file, managed_strm_file_path, remove_empty_parent_dirs


MONITOR_DIR_MISSING_RELEASE_CONFIRMATIONS = 2
_monitor_dispatch_pending = False


def _claim_monitor_job(task_name: str) -> bool:
    global _monitor_dispatch_pending
    with monitor_queue_lock:
        if monitor_status["running"]:
            return False
        _monitor_dispatch_pending = False
        monitor_status["running"] = True
        monitor_status["current_task"] = str(task_name or "")
        monitor_status["queued"] = [item["task_name"] for item in monitor_queue]
    monitor_control["cancel"] = False
    return True


def _release_monitor_job() -> bool:
    global _monitor_dispatch_pending
    with monitor_queue_lock:
        monitor_status["running"] = False
        monitor_status["current_task"] = ""
        should_dispatch = bool(monitor_queue) and not _monitor_dispatch_pending
        if should_dispatch:
            _monitor_dispatch_pending = True
        monitor_status["queued"] = [item["task_name"] for item in monitor_queue]
    monitor_control["cancel"] = False
    return should_dispatch


async def _finish_monitor_job(task_name: str, memory_label: str) -> None:
    should_dispatch = _release_monitor_job()
    schedule_ui_state_push(0)
    release_process_memory(f"{memory_label}:{task_name}", force=True)
    if should_dispatch:
        await start_next_monitor_job()


def _sql_like_descendant_pattern(path: str) -> str:
    escaped = str(path or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"{escaped}/%"


def write_strm_file(target_file: str, url: str, force: bool = False) -> bool:
    next_url = str(url or "").strip()
    old_content = None
    if os.path.exists(target_file):
        with open(target_file, "r", encoding="utf-8", errors="ignore") as f:
            old_content = str(f.read() or "").strip()
    if old_content == next_url and not force:
        return False
    os.makedirs(os.path.dirname(target_file), exist_ok=True)
    with open(target_file, "w", encoding="utf-8") as f:
        f.write(next_url)
    return True


async def mark_cached_dir_as_seen(
    conn: sqlite3.Connection,
    task_name: str,
    local_prefix: str,
) -> None:
    cursor = conn.cursor()
    like_prefix = _sql_like_descendant_pattern(local_prefix) if local_prefix else "%"
    retry_sqlite_locked(
        lambda: cursor.execute(
            """
            INSERT OR REPLACE INTO current_scan (local_rel_path, remote_rel_path, remote_modified, file_size)
            SELECT local_rel_path, remote_rel_path, remote_modified, file_size
            FROM monitor_files
            WHERE task_name = ? AND (local_rel_path = ? OR local_rel_path LIKE ? ESCAPE '\\')
            """,
            (task_name, local_prefix, like_prefix),
        )
    )
    await asyncio.sleep(0)


def _dir_rel_from_local(task_root: str, local_dir_rel: str) -> str:
    if local_dir_rel == task_root:
        return ""
    return normalize_relative_path(os.path.relpath(local_dir_rel, task_root))


def _remote_dir_from_rel(task_scan_path: str, dir_rel_path: str) -> str:
    if not dir_rel_path:
        return normalize_remote_path(task_scan_path)
    return join_remote_path(task_scan_path, dir_rel_path)


def _load_monitor_dir_state(cursor: sqlite3.Cursor, task_name: str, dir_rel_path: str) -> Dict[str, Any]:
    cursor.execute(
        """
        SELECT remote_modified, entry_modified, needs_rescan, missing_confirmations
        FROM monitor_dirs
        WHERE task_name = ? AND dir_rel_path = ?
        """,
        (task_name, dir_rel_path),
    )
    row = cursor.fetchone()
    if not row:
        return {
            "exists": False,
            "remote_modified": "",
            "entry_modified": "",
            "needs_rescan": False,
            "missing_confirmations": 0,
        }
    return {
        "exists": True,
        "remote_modified": str(row[0] or ""),
        "entry_modified": str(row[1] or ""),
        "needs_rescan": bool(int(row[2] or 0)),
        "missing_confirmations": max(0, int(row[3] or 0)),
    }


def _mark_monitor_dir_success(
    cursor: sqlite3.Cursor,
    task_name: str,
    dir_rel_path: str,
    remote_modified: str,
    entry_modified: Optional[str] = None,
) -> None:
    state = _load_monitor_dir_state(cursor, task_name, dir_rel_path)
    next_entry_modified = (
        state["entry_modified"]
        if entry_modified is None
        else str(entry_modified or "")
    )
    retry_sqlite_locked(
        lambda: cursor.execute(
            """
            INSERT OR REPLACE INTO monitor_dirs(
                task_name,
                dir_rel_path,
                remote_modified,
                entry_modified,
                needs_rescan,
                missing_confirmations
            ) VALUES (?, ?, ?, ?, 0, 0)
            """,
            (
                task_name,
                dir_rel_path,
                str(remote_modified or ""),
                next_entry_modified,
            ),
        )
    )


def _mark_monitor_dir_dirty(cursor: sqlite3.Cursor, task_name: str, dir_rel_path: str) -> None:
    def write_dirty() -> None:
        state = _load_monitor_dir_state(cursor, task_name, dir_rel_path)
        cursor.execute(
            """
            INSERT OR REPLACE INTO monitor_dirs(
                task_name,
                dir_rel_path,
                remote_modified,
                entry_modified,
                needs_rescan,
                missing_confirmations
            ) VALUES (?, ?, ?, ?, 1, ?)
            """,
            (
                task_name,
                dir_rel_path,
                state["remote_modified"],
                state["entry_modified"],
                state["missing_confirmations"],
            ),
        )

    retry_sqlite_locked(write_dirty)


def _record_monitor_dir_scan_progress(
    cursor: sqlite3.Cursor,
    task_name: str,
    dir_rel_path: str,
    remote_modified: str,
) -> None:
    state = _load_monitor_dir_state(cursor, task_name, dir_rel_path)
    retry_sqlite_locked(
        lambda: cursor.execute(
            """
            INSERT OR REPLACE INTO monitor_dirs(
                task_name,
                dir_rel_path,
                remote_modified,
                entry_modified,
                needs_rescan,
                missing_confirmations
            ) VALUES (?, ?, ?, ?, 1, ?)
            """,
            (
                task_name,
                dir_rel_path,
                str(remote_modified or ""),
                state["entry_modified"],
                state["missing_confirmations"],
            ),
        )
    )


def _reset_monitor_dir_missing_confirmations(cursor: sqlite3.Cursor, task_name: str, dir_rel_path: str) -> None:
    retry_sqlite_locked(
        lambda: cursor.execute(
            """
            UPDATE monitor_dirs
            SET missing_confirmations = 0
            WHERE task_name = ? AND dir_rel_path = ? AND missing_confirmations <> 0
            """,
            (task_name, dir_rel_path),
        )
    )


def _monitor_dir_has_dirty_subtree(cursor: sqlite3.Cursor, task_name: str, dir_rel_path: str) -> bool:
    if dir_rel_path:
        scope_like = _sql_like_descendant_pattern(dir_rel_path)
        cursor.execute(
            """
            SELECT 1
            FROM monitor_dirs
            WHERE task_name = ?
            AND needs_rescan = 1
            AND (dir_rel_path = ? OR dir_rel_path LIKE ? ESCAPE '\\')
            LIMIT 1
            """,
            (task_name, dir_rel_path, scope_like),
        )
    else:
        cursor.execute(
            """
            SELECT 1
            FROM monitor_dirs
            WHERE task_name = ?
            AND needs_rescan = 1
            LIMIT 1
            """,
            (task_name,),
        )
    return cursor.fetchone() is not None


def _list_dirty_direct_children(cursor: sqlite3.Cursor, task_name: str, parent_dir_rel: str) -> List[str]:
    if parent_dir_rel:
        prefix = f"{parent_dir_rel}/"
        scope_like = _sql_like_descendant_pattern(parent_dir_rel)
        cursor.execute(
            """
            SELECT dir_rel_path
            FROM monitor_dirs
            WHERE task_name = ?
            AND needs_rescan = 1
            AND dir_rel_path LIKE ? ESCAPE '\\'
            """,
            (task_name, scope_like),
        )
    else:
        prefix = ""
        cursor.execute(
            """
            SELECT dir_rel_path
            FROM monitor_dirs
            WHERE task_name = ?
            AND needs_rescan = 1
            AND dir_rel_path <> ''
            """,
            (task_name,),
        )

    direct_children = set()
    prefix_len = len(prefix)
    for row in cursor.fetchall():
        rel_path = normalize_relative_path(str(row[0] or ""))
        if not rel_path:
            continue
        suffix = rel_path[prefix_len:] if prefix else rel_path
        if not suffix:
            continue
        first_segment = suffix.split("/", 1)[0]
        direct_children.add(join_relative_path(parent_dir_rel, first_segment) if parent_dir_rel else first_segment)
    return sorted(direct_children)


def _list_tracked_first_level_dirs(cursor: sqlite3.Cursor, task_name: str) -> List[str]:
    cursor.execute(
        """
        SELECT dir_rel_path
        FROM monitor_dirs
        WHERE task_name = ? AND COALESCE(entry_modified, '') <> ''
        """,
        (task_name,),
    )
    first_level_dirs = set()
    for row in cursor.fetchall():
        rel_path = normalize_relative_path(str(row[0] or ""))
        if rel_path:
            first_level_dirs.add(rel_path.split("/", 1)[0])
    return sorted(first_level_dirs)


def _delete_monitor_dir_subtree(cursor: sqlite3.Cursor, task_name: str, dir_rel_path: str) -> None:
    scope_like = _sql_like_descendant_pattern(dir_rel_path)
    retry_sqlite_locked(
        lambda: cursor.execute(
            """
            DELETE FROM monitor_dirs
            WHERE task_name = ?
            AND (dir_rel_path = ? OR dir_rel_path LIKE ? ESCAPE '\\')
            """,
            (task_name, dir_rel_path, scope_like),
        )
    )


def _bump_missing_monitor_dir(cursor: sqlite3.Cursor, task_name: str, dir_rel_path: str) -> int:
    next_missing = 0

    def write_missing() -> None:
        nonlocal next_missing
        state = _load_monitor_dir_state(cursor, task_name, dir_rel_path)
        next_missing = max(0, int(state["missing_confirmations"] or 0)) + 1
        cursor.execute(
            """
            INSERT OR REPLACE INTO monitor_dirs(
                task_name,
                dir_rel_path,
                remote_modified,
                entry_modified,
                needs_rescan,
                missing_confirmations
            ) VALUES (?, ?, ?, ?, 1, ?)
            """,
            (
                task_name,
                dir_rel_path,
                state["remote_modified"],
                state["entry_modified"],
                next_missing,
            ),
        )

    retry_sqlite_locked(write_missing)
    return next_missing


async def run_monitor_task(
    task_name: str,
    trigger: str = "manual",
    payload: Optional[Dict[str, Any]] = None,
    merged_count: int = 0,
) -> None:
    if not _claim_monitor_job(task_name):
        return
    cfg = get_config()
    task = next((t for t in cfg["monitor_tasks"] if t["name"] == task_name), None)
    if not task:
        await write_monitor_log(f"任务不存在: {task_name}", "error")
        await _finish_monitor_job(task_name, "monitor")
        return
    config_error = validate_monitor_runtime_config(cfg, task)
    if config_error:
        await write_monitor_log(f"任务配置错误: {config_error}", "error")
        update_monitor_summary("任务失败", config_error)
        await _finish_monitor_job(task_name, "monitor")
        return

    ensure_db()
    monitor_last_run[task_name] = time.time()
    update_monitor_summary("准备执行", f"{task_name} ({trigger})")
    schedule_ui_state_push(0)
    run_delay = task["delay_seconds"]
    webhook_delay = 0
    if payload:
        webhook_delay = int(payload.get("delayTime", 0) or 0)
    if webhook_delay > 0:
        run_delay = webhook_delay

    stats = {
        "generated": 0,
        "updated": 0,
        "skipped": 0,
        "skipped_dirs": 0,
        "failed_dirs": 0,
        "deleted_files": 0,
        "deleted_dirs": 0,
        "success_dirs": 0,
        "scanned_branches": 0,
        "skipped_first_level_dirs": 0,
        "rescan_branches": 0,
    }
    generated_strm_paths: List[str] = []
    force_strm_rewrite = str(task.get("strm_write_mode", "incremental") or "incremental").strip().lower() == "full"

    try:
        await write_monitor_task_header(task, trigger, payload)
        if int(merged_count or 0) > 0:
            merge_times = max(1, int(merged_count or 0))
            await write_monitor_log(
                f"本次为合并触发：合并次数 {merge_times}（累计触发 {merge_times + 1} 次）",
                "info",
            )
        if run_delay > 0:
            update_monitor_summary("等待延时", f"{run_delay} 秒后执行")
            await write_monitor_log(f"任务执行延时: {run_delay} 秒", "warn")
            await sleep_interruptible(run_delay)
        check_monitor_cancelled()

        conn = open_db()
        conn.isolation_level = None
        cursor = conn.cursor()
        cursor.execute(
            "CREATE TEMP TABLE current_scan (local_rel_path TEXT PRIMARY KEY, remote_rel_path TEXT, remote_modified TEXT, file_size INTEGER)"
        )

        task_root = resolve_task_root(task)
        task_scan_path = normalize_remote_path(task["scan_path"])
        extensions = get_user_extensions(cfg)
        min_bytes = int(task["min_file_size_mb"] * 1024 * 1024)
        start_remote_path = task_scan_path
        refresh_source_label = ""
        if trigger in ("webhook", "resource") and payload:
            hinted_path = extract_webhook_refresh_path(task, payload, cfg)
            source_label = "Webhook" if trigger == "webhook" else "资源导入"
            refresh_source_label = source_label
            if hinted_path:
                start_remote_path = hinted_path
                await write_monitor_log(f"{source_label} 定位刷新目录: {start_remote_path}", "info")
            else:
                await write_monitor_log(f"{source_label} 未识别到有效子目录，回退全任务路径刷新", "warn")

        if refresh_source_label and start_remote_path != task_scan_path:
            # 115 目录在新建后偶发短暂不可见，先刷新父目录再进入目标目录更稳妥。
            parent_remote_path = normalize_remote_path(os.path.dirname(start_remote_path))
            if parent_remote_path != start_remote_path and is_subpath(parent_remote_path, task_scan_path):
                try:
                    await write_monitor_log(f"{refresh_source_label} 预刷新父目录: {parent_remote_path}", "info")
                    await list_remote_dir(cfg, parent_remote_path, True, task)
                except Exception as exc:
                    await write_monitor_log(
                        f"{refresh_source_label} 预刷新父目录失败: {parent_remote_path} ({exc})",
                        "warn",
                    )

        def build_local_dir_rel(remote_path: str) -> str:
            if remote_path == task_scan_path:
                return task_root
            local_sub_path = normalize_relative_path(os.path.relpath(remote_path, task_scan_path))
            return join_relative_path(task_root, local_sub_path)

        start_local_rel = build_local_dir_rel(start_remote_path)
        queue: List[Tuple[str, str, Optional[str]]] = [(start_remote_path, start_local_rel, None)]
        scanned_dirs = set()
        fallback_guard_expected_path = ""
        fallback_guard_parent_path = ""
        active_dir_rel = ""
        active_dir_active = False
        visited_dir_rels: Set[str] = set()
        pending_first_level_success: Dict[str, Tuple[str, Optional[str]]] = {}
        monitor_file_index_replaced = False

        if start_local_rel != task_root:
            start_dir_rel = _dir_rel_from_local(task_root, start_local_rel)
            first_level_dir_rel = start_dir_rel.split("/", 1)[0] if start_dir_rel else ""
            if first_level_dir_rel:
                _mark_monitor_dir_dirty(cursor, task_name, first_level_dir_rel)

        await write_monitor_section("扫描生成")

        while queue:
            remote_dir, local_dir_rel, first_level_entry_modified = queue.pop(0)
            check_monitor_cancelled()
            if remote_dir in scanned_dirs:
                continue

            dir_rel = _dir_rel_from_local(task_root, local_dir_rel)
            active_dir_rel = dir_rel
            active_dir_active = True
            update_monitor_summary("扫描目录", remote_dir)
            await write_monitor_log(f"读取目录: {remote_dir}", "info")

            try:
                # Always reload each visited directory so moved/new files inside
                # existing folders are visible during recursive scans.
                modified, items = await list_remote_dir(cfg, remote_dir, True, task)
                stats["success_dirs"] += 1
            except Exception as exc:
                stats["failed_dirs"] += 1
                _mark_monitor_dir_dirty(cursor, task_name, dir_rel)
                await write_monitor_log(f"读取目录失败: {remote_dir} ({exc})", "error")
                if (
                    refresh_source_label
                    and remote_dir == start_remote_path
                    and remote_dir != task_scan_path
                ):
                    fallback_remote_path = normalize_remote_path(os.path.dirname(remote_dir))
                    if fallback_remote_path != remote_dir and is_subpath(fallback_remote_path, task_scan_path):
                        fallback_guard_expected_path = remote_dir
                        fallback_guard_parent_path = fallback_remote_path
                        start_remote_path = fallback_remote_path
                        start_local_rel = build_local_dir_rel(start_remote_path)
                        if not any(item[0] == start_remote_path for item in queue):
                            queue.insert(0, (start_remote_path, start_local_rel, None))
                        await write_monitor_log(
                            f"{refresh_source_label} 起始目录暂不可见，回退父目录重试: {start_remote_path}",
                            "warn",
                        )
                        await write_monitor_log(
                            f"{refresh_source_label} 回退后将仅扫描目标子树: {fallback_guard_expected_path}",
                            "warn",
                        )
                active_dir_rel = ""
                active_dir_active = False
                continue
            scanned_dirs.add(remote_dir)

            fallback_target_branch_found = False
            present_child_dir_rels = set()
            is_task_root = remote_dir == task_scan_path
            force_first_level_rescan = (
                is_task_root
                and _load_monitor_dir_state(cursor, task_name, dir_rel)["needs_rescan"]
            )
            for item in items:
                check_monitor_cancelled()
                name = item.get("name") or ""
                if not name:
                    continue

                item_remote_path = join_remote_path(remote_dir, name)
                item_local_rel = join_relative_path(local_dir_rel, name)
                is_dir = bool(item.get("is_dir"))
                modified_at = str(item.get("modified") or "")
                size = int(item.get("size") or 0)

                if is_dir:
                    if fallback_guard_expected_path:
                        in_target_tree = is_subpath(item_remote_path, fallback_guard_expected_path)
                        is_target_ancestor = is_subpath(fallback_guard_expected_path, item_remote_path)
                        if not in_target_tree and not is_target_ancestor:
                            stats["skipped_dirs"] += 1
                            continue
                        if remote_dir == fallback_guard_parent_path:
                            fallback_target_branch_found = True
                    child_dir_rel = _dir_rel_from_local(task_root, item_local_rel)
                    present_child_dir_rels.add(child_dir_rel)
                    _reset_monitor_dir_missing_confirmations(cursor, task_name, child_dir_rel)

                    child_state = _load_monitor_dir_state(cursor, task_name, child_dir_rel)
                    child_has_dirty = _monitor_dir_has_dirty_subtree(cursor, task_name, child_dir_rel)
                    if (
                        is_task_root
                        and task["skip_by_dir_mtime"]
                        and not refresh_source_label
                        and modified_at
                        and child_state["entry_modified"]
                        and child_state["entry_modified"] == modified_at
                        and not child_has_dirty
                        and not force_first_level_rescan
                    ):
                        stats["skipped_dirs"] += 1
                        stats["skipped_first_level_dirs"] += 1
                        await mark_cached_dir_as_seen(conn, task_name, item_local_rel)
                        await write_monitor_log(f"跳过目录: {item_remote_path}", "warn")
                        continue

                    if is_task_root:
                        stats["scanned_branches"] += 1
                        if child_has_dirty or force_first_level_rescan:
                            stats["rescan_branches"] += 1
                        _mark_monitor_dir_dirty(cursor, task_name, child_dir_rel)
                    queue.append(
                        (
                            item_remote_path,
                            item_local_rel,
                            modified_at if is_task_root else None,
                        )
                    )
                    continue

                if fallback_guard_expected_path and not is_subpath(item_remote_path, fallback_guard_expected_path):
                    stats["skipped"] += 1
                    continue
                if not is_video_file(name, extensions):
                    stats["skipped"] += 1
                    continue
                if min_bytes > 0 and size < min_bytes:
                    stats["skipped"] += 1
                    continue

                target_file = managed_strm_file_path(item_local_rel)
                strm_url = build_strm_play_url(cfg, item_remote_path, pick_code=item.get("pick_code", ""))
                changed = await asyncio.to_thread(write_strm_file, target_file, strm_url, force=force_strm_rewrite)
                if changed:
                    stats["generated"] += 1
                    generated_rel_path = normalize_relative_path(item_local_rel + ".strm")
                    if generated_rel_path:
                        generated_strm_paths.append(generated_rel_path)
                    await write_monitor_log(f"生成: {target_file}", "success")
                else:
                    stats["skipped"] += 1

                remote_rel = normalize_relative_path(os.path.relpath(item_remote_path, task_scan_path))
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO current_scan(local_rel_path, remote_rel_path, remote_modified, file_size)
                    VALUES (?, ?, ?, ?)
                    """,
                    (item_local_rel, remote_rel, modified_at, size),
                )

            tracked_child_rels = set(_list_dirty_direct_children(cursor, task_name, dir_rel))
            if is_task_root:
                tracked_child_rels.update(_list_tracked_first_level_dirs(cursor, task_name))
            for child_dir_rel in sorted(tracked_child_rels):
                child_remote_path = _remote_dir_from_rel(task_scan_path, child_dir_rel)
                if fallback_guard_expected_path:
                    in_target_tree = is_subpath(child_remote_path, fallback_guard_expected_path)
                    is_target_ancestor = is_subpath(fallback_guard_expected_path, child_remote_path)
                    if not in_target_tree and not is_target_ancestor:
                        continue
                if child_dir_rel in present_child_dir_rels:
                    _reset_monitor_dir_missing_confirmations(cursor, task_name, child_dir_rel)
                    continue

                missing_count = _bump_missing_monitor_dir(cursor, task_name, child_dir_rel)
                if missing_count >= MONITOR_DIR_MISSING_RELEASE_CONFIRMATIONS:
                    _delete_monitor_dir_subtree(cursor, task_name, child_dir_rel)
                    await write_monitor_log(
                        f"待补扫目录已连续 {MONITOR_DIR_MISSING_RELEASE_CONFIRMATIONS} 次确认不存在，已释放记录: {_remote_dir_from_rel(task_scan_path, child_dir_rel)}",
                        "info",
                    )
                else:
                    await write_monitor_log(
                        f"待补扫目录本轮未出现，保留补扫记录 ({missing_count}/{MONITOR_DIR_MISSING_RELEASE_CONFIRMATIONS}): {_remote_dir_from_rel(task_scan_path, child_dir_rel)}",
                        "warn",
                    )

            if (
                fallback_guard_expected_path
                and remote_dir == fallback_guard_parent_path
                and not fallback_target_branch_found
            ):
                await write_monitor_log(
                    f"{refresh_source_label} 回退父目录未发现目标子目录，已跳过同级目录避免误扫",
                    "warn",
                )

            is_first_level_dir = bool(dir_rel) and "/" not in dir_rel
            if is_first_level_dir:
                _record_monitor_dir_scan_progress(
                    cursor,
                    task_name,
                    dir_rel,
                    modified,
                )
                pending_first_level_success[dir_rel] = (modified, first_level_entry_modified)
            else:
                _mark_monitor_dir_success(
                    cursor,
                    task_name,
                    dir_rel,
                    modified,
                    entry_modified=first_level_entry_modified,
                )
            visited_dir_rels.add(dir_rel)
            active_dir_rel = ""
            active_dir_active = False
            if task["list_delay_ms"] > 0:
                await sleep_interruptible(task["list_delay_ms"] / 1000)

        await write_monitor_section("清理校正")
        await write_monitor_log(f"清理范围: {start_remote_path}", "info")
        if stats["success_dirs"] == 0:
            raise RuntimeError("未成功读取任何目录，已停止并跳过过期 STRM 清理（避免误删）")

        cleanup_enabled = bool(task.get("sync_clean", not task.get("incremental", False)))
        if cleanup_enabled and stats["failed_dirs"] == 0:
            if start_local_rel == task_root:
                cursor.execute(
                    """
                    SELECT local_rel_path FROM monitor_files
                    WHERE task_name = ?
                    AND local_rel_path NOT IN (SELECT local_rel_path FROM current_scan)
                    """,
                    (task_name,),
                )
            else:
                scope_like = _sql_like_descendant_pattern(start_local_rel)
                cursor.execute(
                    """
                    SELECT local_rel_path FROM monitor_files
                    WHERE task_name = ?
                    AND (local_rel_path = ? OR local_rel_path LIKE ? ESCAPE '\\')
                    AND local_rel_path NOT IN (SELECT local_rel_path FROM current_scan)
                    """,
                    (task_name, start_local_rel, scope_like),
                )
            stale_files = [row[0] for row in cursor.fetchall()]
            for local_rel_path in stale_files:
                check_monitor_cancelled()
                target_file = managed_strm_file_path(local_rel_path)
                if delete_managed_strm_file(local_rel_path):
                    stats["deleted_files"] += 1
                    stats["deleted_dirs"] += remove_empty_parent_dirs(
                        os.path.dirname(target_file), os.path.join(STRM_ROOT, task_root)
                    )

        def replace_monitor_file_index() -> None:
            cursor.execute("BEGIN IMMEDIATE")
            try:
                if cleanup_enabled and stats["failed_dirs"] == 0:
                    if start_local_rel == task_root:
                        cursor.execute("DELETE FROM monitor_files WHERE task_name = ?", (task_name,))
                    else:
                        scope_like = _sql_like_descendant_pattern(start_local_rel)
                        cursor.execute(
                            """
                            DELETE FROM monitor_files
                            WHERE task_name = ? AND (local_rel_path = ? OR local_rel_path LIKE ? ESCAPE '\\')
                            """,
                            (task_name, start_local_rel, scope_like),
                        )
                else:
                    cursor.execute(
                        """
                        DELETE FROM monitor_files
                        WHERE task_name = ? AND local_rel_path IN (SELECT local_rel_path FROM current_scan)
                        """,
                        (task_name,),
                    )
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO monitor_files(task_name, local_rel_path, remote_rel_path, remote_modified, file_size)
                    SELECT ?, local_rel_path, remote_rel_path, remote_modified, file_size FROM current_scan
                    """,
                    (task_name,),
                )
                # Only publish first-level baselines with the file index they describe.
                for dir_rel, (remote_modified, entry_modified) in pending_first_level_success.items():
                    _mark_monitor_dir_success(
                        cursor,
                        task_name,
                        dir_rel,
                        remote_modified,
                        entry_modified=entry_modified,
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        if not (cleanup_enabled and stats["failed_dirs"] == 0):
            if cleanup_enabled and stats["failed_dirs"] > 0:
                await write_monitor_log("检测到目录读取失败，已自动跳过过期 STRM 清理以防误删", "warn")

        retry_sqlite_locked(replace_monitor_file_index)
        monitor_file_index_replaced = True
        conn.close()
        conn = None

        await write_monitor_section("执行结果")
        await write_monitor_task_summary(stats, cleanup_enabled=cleanup_enabled)
        try:
            notify_result = await push_monitor_success_notification(
                cfg=cfg,
                task=task,
                trigger=trigger,
                stats=stats,
                generated_strm_paths=generated_strm_paths,
                source_context=payload if isinstance(payload, dict) else {},
            )
            if notify_result.get("pushed"):
                await write_monitor_log(
                    "通知推送成功: 生成 {generated} 条，匹配 {matched} 条，未识别 {unmatched} 条".format(
                        generated=max(0, int(notify_result.get("generated", 0) or 0)),
                        matched=max(0, int(notify_result.get("matched", 0) or 0)),
                        unmatched=max(0, int(notify_result.get("unmatched", 0) or 0)),
                    ),
                    "success",
                )
            elif str(notify_result.get("reason", "") or "").strip() == "merged_with_subscription":
                await write_monitor_log(
                    (
                        "通知已合并到订阅任务更新通知"
                        f" | run_id={str(notify_result.get('subscription_run_id', '') or '').strip() or '--'}"
                    ),
                    "info",
                )
        except Exception as notify_exc:
            await write_monitor_log(f"通知推送失败: {notify_exc}", "warn")
        await write_monitor_task_footer(task_name, "执行成功")
        update_monitor_summary("任务完成", f"{task_name} 执行结束")
    except asyncio.CancelledError:
        try:
            if "conn" in locals() and conn is not None and "active_dir_active" in locals() and active_dir_active:
                _mark_monitor_dir_dirty(conn.cursor(), task_name, active_dir_rel)
            if "conn" in locals() and conn is not None and not locals().get("monitor_file_index_replaced", False):
                dirty_cursor = conn.cursor()
                for visited_dir_rel in locals().get("visited_dir_rels", set()):
                    _mark_monitor_dir_dirty(dirty_cursor, task_name, visited_dir_rel)
        except Exception:
            pass
        await write_monitor_section("执行结果")
        await write_monitor_task_summary(
            stats,
            cleanup_enabled=bool(task.get("sync_clean", not task.get("incremental", False))) if "task" in locals() else None,
        )
        await write_monitor_task_footer(task_name, "已中断")
        update_monitor_summary("任务中断", task_name)
    except Exception as exc:
        try:
            if "conn" in locals() and conn is not None and "active_dir_active" in locals() and active_dir_active:
                _mark_monitor_dir_dirty(conn.cursor(), task_name, active_dir_rel)
            if "conn" in locals() and conn is not None and not locals().get("monitor_file_index_replaced", False):
                dirty_cursor = conn.cursor()
                for visited_dir_rel in locals().get("visited_dir_rels", set()):
                    _mark_monitor_dir_dirty(dirty_cursor, task_name, visited_dir_rel)
        except Exception:
            pass
        await write_monitor_section("执行结果")
        await write_monitor_task_summary(
            stats,
            cleanup_enabled=bool(task.get("sync_clean", not task.get("incremental", False))) if "task" in locals() else None,
        )
        await write_monitor_log(f"失败原因: {exc}", "error")
        await write_monitor_task_footer(task_name, "执行失败")
        update_monitor_summary("任务失败", str(exc))
    finally:
        try:
            if "conn" in locals() and conn is not None:
                conn.close()
        except Exception:
            pass
        await _finish_monitor_job(task_name, "monitor")


async def run_monitor_change_task(
    task_name: str,
    trigger: str = "change",
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    """Consume persisted scraper mutations without entering the scan walker."""
    if not _claim_monitor_job(task_name):
        return
    cfg = get_config()
    task = next(
        (
            normalize_task(item)
            for item in cfg.get("monitor_tasks", []) or []
            if isinstance(item, dict) and str(item.get("name", "") or "") == str(task_name or "")
        ),
        None,
    )
    if not task:
        await write_monitor_log(f"变更同步任务不存在: {task_name}", "error")
        await _finish_monitor_job(task_name, "monitor-change")
        return
    update_monitor_summary("准备同步变更", task_name)
    schedule_ui_state_push(0)
    try:
        await write_monitor_task_header(task, "change", payload)
        await write_monitor_section("处理刮削变更")
        from .monitor_changes import process_monitor_change_events

        raw_event_ids = payload.get("event_ids", []) if isinstance(payload, dict) else []
        event_ids = raw_event_ids if isinstance(raw_event_ids, list) else None
        result = await process_monitor_change_events(task_name, cfg=cfg, event_ids=event_ids)
        summary_values = {
            key: int(result.get(key, 0) or 0)
            for key in ("completed", "failed", "generated", "deleted", "directory_count", "file_count")
        }
        await write_monitor_log(
            (
                "变更同步汇总: 完成 {completed}，失败 {failed}，生成 {generated}，"
                "删除 {deleted}，局部读取目录 {directory_count}，文件 {file_count}"
            ).format(**summary_values),
            "success" if int(result.get("failed", 0) or 0) == 0 else "warn",
        )
        for error_item in (result.get("errors", []) if isinstance(result.get("errors"), list) else [])[:10]:
            if not isinstance(error_item, dict):
                continue
            await write_monitor_log(
                "变更事件 #{event_id} 失败，已保留重试: {error}".format(
                    event_id=max(0, int(error_item.get("event_id", 0) or 0)),
                    error=str(error_item.get("error", "") or "未知错误"),
                ),
                "error",
            )
        status_text = "变更同步完成" if int(result.get("failed", 0) or 0) == 0 else "变更同步部分失败"
        await write_monitor_task_footer(task_name, status_text)
        update_monitor_summary(status_text, task_name)
    except asyncio.CancelledError:
        await write_monitor_task_footer(task_name, "变更同步已中断")
        update_monitor_summary("变更同步中断", task_name)
    except Exception as exc:
        await write_monitor_log(f"变更同步失败: {exc}", "error")
        await write_monitor_task_footer(task_name, "变更同步失败")
        update_monitor_summary("变更同步失败", str(exc))
    finally:
        await _finish_monitor_job(task_name, "monitor-change")


async def start_next_monitor_job() -> None:
    global _monitor_dispatch_pending
    with monitor_queue_lock:
        if monitor_status["running"] or not monitor_queue:
            _monitor_dispatch_pending = False
            monitor_status["queued"] = [item["task_name"] for item in monitor_queue]
            schedule_ui_state_push(0)
            return
        _monitor_dispatch_pending = True
        next_job = monitor_queue.pop(0)
        monitor_status["queued"] = [item["task_name"] for item in monitor_queue]
    schedule_ui_state_push(0)
    if str(next_job.get("mode", "scan") or "scan") == "change":
        submit_background(
            run_monitor_change_task,
            next_job["task_name"],
            trigger=next_job.get("trigger", "change"),
            payload=next_job.get("payload"),
            label="monitor-change-job",
        )
    else:
        submit_background(
            run_monitor_task,
            next_job["task_name"],
            trigger=next_job.get("trigger", "queued"),
            payload=next_job.get("payload"),
            merged_count=max(0, int(next_job.get("merge_count", 0) or 0)),
            label="monitor-job",
        )


def _normalize_monitor_queue_payload(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    raw_payload = payload if isinstance(payload, dict) else {}
    normalized: Dict[str, Any] = {}

    mode = str(raw_payload.get("mode", "scan") or "scan").strip().lower()
    if mode == "change":
        normalized["mode"] = "change"

    savepath = normalize_relative_path(raw_payload.get("savepath", ""))
    if savepath:
        normalized["savepath"] = savepath

    sharetitle = normalize_relative_path(raw_payload.get("sharetitle", ""))
    if sharetitle:
        normalized["sharetitle"] = sharetitle

    title = str(raw_payload.get("title", "") or "").strip()
    if title:
        normalized["title"] = title[:200]

    refresh_target_type = str(raw_payload.get("refresh_target_type", "") or "").strip().lower()
    if refresh_target_type:
        normalized["refresh_target_type"] = refresh_target_type

    try:
        delay_seconds = max(0, int(raw_payload.get("delayTime", 0) or 0))
    except Exception:
        delay_seconds = 0
    if delay_seconds > 0:
        normalized["delayTime"] = delay_seconds

    subscription_run_id = str(raw_payload.get("subscription_run_id", "") or "").strip()
    if subscription_run_id:
        normalized["source"] = "subscription"
        normalized["subscription_run_id"] = subscription_run_id[:160]
        subscription_task_name = str(raw_payload.get("subscription_task_name", "") or "").strip()
        if subscription_task_name:
            normalized["subscription_task_name"] = subscription_task_name[:200]

    return normalized


def _extract_monitor_subscription_context(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    normalized_payload = _normalize_monitor_queue_payload(payload)
    subscription_run_id = str(normalized_payload.get("subscription_run_id", "") or "").strip()
    if not subscription_run_id:
        return {}
    context = {
        "source": "subscription",
        "subscription_run_id": subscription_run_id,
    }
    subscription_task_name = str(normalized_payload.get("subscription_task_name", "") or "").strip()
    if subscription_task_name:
        context["subscription_task_name"] = subscription_task_name
    return context


def _merge_monitor_subscription_context(
    existing: Optional[Dict[str, Any]],
    incoming: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    existing_context = _extract_monitor_subscription_context(existing)
    incoming_context = _extract_monitor_subscription_context(incoming)
    existing_run_id = str(existing_context.get("subscription_run_id", "") or "").strip()
    incoming_run_id = str(incoming_context.get("subscription_run_id", "") or "").strip()
    if not existing_run_id and not incoming_run_id:
        return {}
    if existing_run_id and incoming_run_id and existing_run_id == incoming_run_id:
        return {
            **existing_context,
            **{key: value for key, value in incoming_context.items() if str(value or "").strip()},
        }
    return {}


def _monitor_queue_scope(payload: Optional[Dict[str, Any]]) -> str:
    normalized_payload = _normalize_monitor_queue_payload(payload)
    savepath = normalize_relative_path(normalized_payload.get("savepath", ""))
    if not savepath:
        return ""
    return normalize_remote_path("/" + savepath)


def _merge_monitor_queue_payload(existing: Optional[Dict[str, Any]], incoming: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    existing_payload = _normalize_monitor_queue_payload(existing)
    incoming_payload = _normalize_monitor_queue_payload(incoming)

    existing_scope = _monitor_queue_scope(existing_payload)
    incoming_scope = _monitor_queue_scope(incoming_payload)
    merged_delay = max(
        int(existing_payload.get("delayTime", 0) or 0),
        int(incoming_payload.get("delayTime", 0) or 0),
    )

    merged_mode = "change" if (
        str(existing_payload.get("mode", "") or "").strip().lower() == "change"
        or str(incoming_payload.get("mode", "") or "").strip().lower() == "change"
    ) else "scan"
    merged_payload: Dict[str, Any] = {"mode": "change"} if merged_mode == "change" else {}
    if not existing_scope or not incoming_scope:
        merged_payload = {"mode": "change"} if merged_mode == "change" else {}
    elif existing_scope == incoming_scope:
        # 同目录短时间多次触发时，统一提升为父目录刷新，避免因 sharetitle 不同造成风暴排队。
        merged_payload["savepath"] = normalize_relative_path(existing_scope.lstrip("/"))
    elif is_subpath(existing_scope, incoming_scope):
        merged_payload["savepath"] = normalize_relative_path(incoming_scope.lstrip("/"))
    elif is_subpath(incoming_scope, existing_scope):
        merged_payload["savepath"] = normalize_relative_path(existing_scope.lstrip("/"))
    else:
        # 不同分支目录并发触发时，回退全任务刷新，保证不漏刷。
        merged_payload = {"mode": "change"} if merged_mode == "change" else {}

    if merged_delay > 0:
        merged_payload["delayTime"] = merged_delay
    merged_payload.update(_merge_monitor_subscription_context(existing_payload, incoming_payload))
    return merged_payload


def _pick_monitor_trigger(existing_trigger: str, new_trigger: str) -> str:
    trigger_priority = {
        "queued": 0,
        "cron": 1,
        "manual": 2,
        "resource": 3,
        "webhook": 4,
        "change": 5,
    }
    existing = str(existing_trigger or "").strip().lower() or "queued"
    incoming = str(new_trigger or "").strip().lower() or "queued"
    if trigger_priority.get(incoming, 0) >= trigger_priority.get(existing, 0):
        return incoming
    return existing


def queue_monitor_job(task_name: str, trigger: str, payload: Optional[Dict[str, Any]] = None) -> str:
    global _monitor_dispatch_pending
    normalized_task_name = str(task_name or "").strip()
    if not normalized_task_name:
        schedule_ui_state_push(0)
        return "queued"

    normalized_trigger = str(trigger or "").strip().lower() or "manual"
    normalized_payload = _normalize_monitor_queue_payload(payload)
    mode = str(normalized_payload.get("mode", "scan") or "scan")

    should_dispatch = False
    with monitor_queue_lock:
        matched_item: Optional[Dict[str, Any]] = None
        for queued_item in monitor_queue:
            if str(queued_item.get("task_name", "")).strip() != normalized_task_name:
                continue
            if str(queued_item.get("mode", "scan") or "scan") != mode:
                continue
            matched_item = queued_item
            break
        if matched_item is not None:
            matched_item["payload"] = _merge_monitor_queue_payload(matched_item.get("payload"), normalized_payload)
            matched_item["mode"] = mode
            matched_item["trigger"] = _pick_monitor_trigger(matched_item.get("trigger", "queued"), normalized_trigger)
            matched_item["merge_count"] = max(0, int(matched_item.get("merge_count", 0) or 0)) + 1
        else:
            monitor_queue.append(
                {
                    "task_name": normalized_task_name,
                    "trigger": normalized_trigger,
                    "payload": normalized_payload,
                    "mode": mode,
                    "merge_count": 0,
                }
            )
        if not monitor_status["running"] and not _monitor_dispatch_pending:
            _monitor_dispatch_pending = True
            should_dispatch = True
        monitor_status["queued"] = [item["task_name"] for item in monitor_queue]
    schedule_ui_state_push(0)
    if should_dispatch:
        submit_background(start_next_monitor_job, label="monitor-next")
        return "started"
    return "queued"
