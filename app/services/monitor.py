import re

from ..background import submit_background
from ..core import *  # noqa: F401,F403
from ..db import retry_sqlite_locked
from ..memory import release_process_memory
from .notify import push_monitor_success_notification
from .strm_files import delete_managed_strm_file, managed_strm_file_path, remove_empty_parent_dirs


MONITOR_DIR_MISSING_RELEASE_CONFIRMATIONS = 2
MONITOR_SCAN_SAVEPATHS_MAX = 50
_monitor_dispatch_pending = False


def build_monitor_scope_line(
    task: Dict[str, Any],
    trigger: str,
    *,
    hinted_path: str = "",
    resolved_paths: Optional[List[str]] = None,
    manual_scope_count: int = 0,
    manual_force_all: bool = False,
) -> str:
    """构建任务开始后的扫描范围摘要行。"""
    scan_path = normalize_remote_path(str((task or {}).get("scan_path", "") or ""))
    if manual_force_all:
        return "范围: 需补扫全任务（首层强制扫描）"
    if manual_scope_count > 0:
        return f"范围: 需补扫首层分支 {max(0, int(manual_scope_count or 0))} 条"
    normalized_trigger = str(trigger or "").strip().lower()
    if normalized_trigger in ("webhook", "resource"):
        raw_hint = str(hinted_path or "").strip()
        path = normalize_remote_path(raw_hint) if raw_hint else ""
        return f"范围: {path}" if raw_hint and path else f"范围: 全任务 {scan_path}"
    if normalized_trigger == "manual":
        paths: List[str] = []
        for raw_path in resolved_paths if isinstance(resolved_paths, list) else []:
            path = normalize_remote_path(str(raw_path or "").strip())
            if path and path not in paths:
                paths.append(path)
        if paths:
            preview = ", ".join(paths[:5])
            if len(paths) > 5:
                preview += "..."
            return f"范围: {preview}"
        return f"范围: 全任务 {scan_path}"
    return f"范围: 全任务 {scan_path}"


def build_monitor_conclusion_line(stats: Dict[str, Any], auto_summary: Any = "") -> str:
    """构建执行成功前的结论摘要行。"""
    auto_text = "-"
    auto_raw = str(auto_summary or "").strip()
    if auto_raw:
        matched = re.search(r"已自动整理\s*(\d+)\s*项", auto_raw)
        auto_text = f"{matched.group(1)} 项" if matched else "已执行"
    return (
        f"结论: 新增/更新 {max(0, int((stats or {}).get('generated', 0) or 0))} | "
        f"跳过 {max(0, int((stats or {}).get('skipped', 0) or 0))} | "
        f"自动整理 {auto_text} | "
        f"清理 {max(0, int((stats or {}).get('deleted_files', 0) or 0))}"
    )


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


def _auto_scrape_new_media_items(
    cfg: Dict[str, Any],
    task: Dict[str, Any],
    new_media_items: List[Dict[str, Any]],
) -> str:
    """新增媒体文件自动刮削整理：只对高置信度自动匹配条目执行一次，失败仅记录。"""
    from .scraper import (
        _normalize_scraper_batch_preferences,
        _walk_existing_folder,
        build_scraper_batch_plan,
        create_scraper_job_from_plan,
        identify_scraper_batch_items,
        run_scraper_job,
        scan_scraper_batch_items,
    )

    if not new_media_items:
        return "没有新增媒体文件"
    cookie = str(cfg.get("cookie_115", "") or "").strip()
    parent_cid_cache: Dict[str, str] = {}
    parent_items: Dict[str, List[Dict[str, Any]]] = {}
    for item in new_media_items:
        fid = str(item.get("fid") or item.get("id") or "").strip()
        rel_path = normalize_relative_path(str(item.get("remote_rel", "") or ""))
        if not fid or not rel_path:
            continue
        try:
            full_remote_path = join_remote_path(
                normalize_remote_path(task.get("scan_path", "")),
                rel_path,
            )
            _provider, mount_rel = resolve_provider_relative_path(cfg, full_remote_path, expected_provider="115")
        except Exception:
            continue
        if not mount_rel:
            continue
        parent_rel = normalize_relative_path(os.path.dirname(mount_rel))
        if not parent_rel:
            continue
        parent_cid = parent_cid_cache.get(parent_rel, "")
        if not parent_cid:
            try:
                parent_cid, _exists = _walk_existing_folder("115", cookie, "0", parent_rel)
            except Exception:
                parent_cid = ""
            parent_cid_cache[parent_rel] = parent_cid
        if not parent_cid:
            continue
        parent_items.setdefault(parent_rel, []).append(item)
    if not parent_items:
        return f"新增文件无法解析网盘路径，跳过 {len(new_media_items)} 项"
    entries: List[Dict[str, Any]] = []
    for parent_rel in sorted(parent_items):
        folder_name = os.path.basename(parent_rel)
        grandparent_rel = normalize_relative_path(os.path.dirname(parent_rel))
        grandparent_cid = parent_cid_cache.get(grandparent_rel, "")
        if grandparent_rel and not grandparent_cid:
            try:
                grandparent_cid, _exists = _walk_existing_folder("115", cookie, "0", grandparent_rel)
            except Exception:
                grandparent_cid = ""
            parent_cid_cache[grandparent_rel] = grandparent_cid
        if grandparent_rel and not grandparent_cid:
            continue
        entries.append(
            {
                "id": parent_cid_cache[parent_rel],
                "cid": parent_cid_cache[parent_rel],
                "name": folder_name,
                "is_dir": True,
                "parent_id": grandparent_cid or "0",
                "parent_path": grandparent_rel,
                "path": parent_rel,
            }
        )
    scan = scan_scraper_batch_items("115", "0", "", entries)
    scan_items = scan.get("items", []) if isinstance(scan, dict) else []
    if not scan_items:
        return "新增文件未形成可识别条目"
    identify_payload = {
        "provider": "115",
        "items": [
            {
                "item_index": max(0, int(item.get("item_index", 0) or 0)),
                "name": item.get("name", ""),
                "entry": item.get("entry", {}),
                "files": (item.get("files") or [])[:40],
            }
            for item in scan_items
        ],
    }
    identify = identify_scraper_batch_items(identify_payload)
    results = identify.get("results", []) if isinstance(identify, dict) else []
    auto_results = [
        result
        for result in results
        if isinstance(result, dict) and result.get("status") == "auto" and result.get("auto_pick")
    ]
    if not auto_results:
        return "新增条目无高置信度自动匹配，已跳过（可在刮削页手动整理）"
    auto_indexes = {max(0, int(result.get("item_index", 0) or 0)) for result in auto_results}
    auto_by_index = {
        max(0, int(result.get("item_index", 0) or 0)): result.get("auto_pick")
        for result in auto_results
    }
    plan_items = [
        {
            "item_index": max(0, int(item.get("item_index", 0) or 0)),
            "name": item.get("name", ""),
            "entry": item.get("entry", {}),
            "tmdb": auto_by_index.get(max(0, int(item.get("item_index", 0) or 0)), {}),
        }
        for item in scan_items
        if max(0, int(item.get("item_index", 0) or 0)) in auto_indexes
    ]
    raw_auto_options = task.get("auto_scrape_options") if isinstance(task.get("auto_scrape_options"), dict) else {}
    auto_options = {"title_language": "zh", "delete_ad_files": False}
    if raw_auto_options:
        auto_options.update(_normalize_scraper_batch_preferences(raw_auto_options))
    plan = build_scraper_batch_plan(
        {
            "provider": "115",
            "base_cid": "0",
            "base_path": "",
            "options": auto_options,
            "items": plan_items,
        }
    )
    ready_count = max(0, int(plan.get("ready_count", 0) or 0))
    if ready_count <= 0:
        return "高置信度条目无可执行动作"
    job = create_scraper_job_from_plan({"plan": plan})
    job_id = max(0, int(job.get("job_id", 0) or 0))
    run_scraper_job(job_id)
    return f"已自动整理 {ready_count} 项（任务 #{job_id}）"


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
    new_media_items: List[Dict[str, Any]] = []
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
        previous_file_keys: Set[str] = set()
        try:
            cursor.execute("SELECT local_rel_path FROM monitor_files WHERE task_name = ?", (task_name,))
            previous_file_keys = {str(row[0] or "") for row in cursor.fetchall()}
        except Exception:
            previous_file_keys = set()

        task_root = resolve_task_root(task)
        task_scan_path = normalize_remote_path(task["scan_path"])
        extensions = get_user_extensions(cfg)
        min_bytes = int(task["min_file_size_mb"] * 1024 * 1024)
        start_remote_paths: List[str] = [task_scan_path]
        refresh_source_label = ""
        hinted_path = ""
        resolved_paths: List[str] = []
        if trigger in ("webhook", "resource") and payload:
            hinted_path = extract_webhook_refresh_path(task, payload, cfg)
            source_label = "Webhook" if trigger == "webhook" else "资源导入"
            refresh_source_label = source_label
            if hinted_path:
                start_remote_paths = [hinted_path]
                await write_monitor_log(f"{source_label} 定位刷新目录: {hinted_path}", "info")
            else:
                await write_monitor_log(f"{source_label} 未识别到有效子目录，回退全任务路径刷新", "warn")
        elif trigger == "manual" and payload:
            raw_savepaths = payload.get("savepaths")
            if isinstance(raw_savepaths, list) and raw_savepaths:
                scan_provider = str(payload.get("provider", "115") or "115").strip()
                resolved_paths: List[str] = []
                dropped_paths: List[str] = []
                for raw_path in raw_savepaths:
                    savepath = normalize_relative_path(str(raw_path or "").strip())
                    if not savepath:
                        continue
                    matched = match_monitor_task_for_savepath(cfg, savepath, provider=scan_provider)
                    matched_task = str(matched.get("task_name", "") or "").strip()
                    full_path = normalize_remote_path(matched.get("full_path", "") or "")
                    if matched_task == task_name and full_path and is_subpath(full_path, task_scan_path):
                        if full_path not in resolved_paths:
                            resolved_paths.append(full_path)
                    else:
                        dropped_paths.append(savepath)
                if resolved_paths:
                    refresh_source_label = "指定目录扫描"
                    start_remote_paths = resolved_paths
                    path_preview = ", ".join(resolved_paths[:5])
                    if len(resolved_paths) > 5:
                        path_preview += "..."
                    await write_monitor_log(
                        f"指定目录扫描定位 {len(resolved_paths)} 个目录: {path_preview}",
                        "info",
                    )
                    if dropped_paths:
                        drop_preview = ", ".join(dropped_paths[:5])
                        if len(dropped_paths) > 5:
                            drop_preview += "..."
                        await write_monitor_log(
                            f"指定目录扫描忽略任务外路径 {len(dropped_paths)} 条: {drop_preview}",
                            "warn",
                        )
                else:
                    await write_monitor_log("指定目录扫描未匹配到任务内目录，回退全任务路径刷新", "warn")

        manual_required_scopes: List[Dict[str, Any]] = []
        manual_required_first_level_dirs: Set[str] = set()
        manual_required_force_all_first_level = False
        if str(trigger or "").strip().lower() == "manual":
            from .monitor_changes import get_manual_required_monitor_scopes

            manual_required_scopes = await asyncio.to_thread(
                get_manual_required_monitor_scopes,
                task_name,
                cfg=cfg,
            )
            manual_required_first_level_dirs = {
                str(scope.get("first_level_dir_rel", "") or "")
                for scope in manual_required_scopes
                if str(scope.get("first_level_dir_rel", "") or "")
            }
            manual_required_force_all_first_level = any(
                not str(scope.get("first_level_dir_rel", "") or "")
                for scope in manual_required_scopes
            )
            if manual_required_scopes:
                await write_monitor_log(
                    f"需手动监控范围: {len(manual_required_scopes)} 条，本轮将强制扫描对应首层分支",
                    "warn",
                )
        await write_monitor_log(
            build_monitor_scope_line(
                task,
                trigger,
                hinted_path=hinted_path,
                resolved_paths=resolved_paths,
                manual_scope_count=len(manual_required_scopes),
                manual_force_all=manual_required_force_all_first_level,
            ),
            "info",
        )

        if refresh_source_label:
            parent_refresh_paths: List[str] = []
            for start_remote_path in start_remote_paths:
                if start_remote_path == task_scan_path:
                    continue
                # 115 目录在新建后偶发短暂不可见，先刷新父目录再进入目标目录更稳妥。
                parent_remote_path = normalize_remote_path(os.path.dirname(start_remote_path))
                if (
                    parent_remote_path != start_remote_path
                    and is_subpath(parent_remote_path, task_scan_path)
                    and parent_remote_path not in parent_refresh_paths
                ):
                    parent_refresh_paths.append(parent_remote_path)
            for parent_remote_path in parent_refresh_paths:
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

        scan_scope_rels: List[str] = [build_local_dir_rel(path_item) for path_item in start_remote_paths]
        queue: List[Tuple[str, str, Optional[str]]] = [
            (path_item, local_rel, None)
            for path_item, local_rel in zip(start_remote_paths, scan_scope_rels)
        ]
        scanned_dirs = set()
        fallback_guard_expected_path = ""
        fallback_guard_parent_path = ""
        active_dir_rel = ""
        active_dir_active = False
        visited_dir_rels: Set[str] = set()
        pending_first_level_success: Dict[str, Tuple[str, Optional[str]]] = {}
        manual_required_root_scanned = False
        manual_required_seen_first_level_dirs: Set[str] = set()
        manual_required_failed_first_level_dirs: Set[str] = set()
        monitor_file_index_replaced = False

        for scope_local_rel in scan_scope_rels:
            if scope_local_rel == task_root:
                continue
            start_dir_rel = _dir_rel_from_local(task_root, scope_local_rel)
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
                if manual_required_scopes and remote_dir == task_scan_path:
                    manual_required_root_scanned = True
            except Exception as exc:
                stats["failed_dirs"] += 1
                _mark_monitor_dir_dirty(cursor, task_name, dir_rel)
                failed_first_level_dir = dir_rel.split("/", 1)[0] if dir_rel else ""
                if (
                    manual_required_force_all_first_level
                    or failed_first_level_dir in manual_required_first_level_dirs
                ):
                    manual_required_failed_first_level_dirs.add(failed_first_level_dir)
                await write_monitor_log(f"读取目录失败: {remote_dir} ({exc})", "error")
                if (
                    refresh_source_label
                    and remote_dir in start_remote_paths
                    and remote_dir != task_scan_path
                ):
                    fallback_remote_path = normalize_remote_path(os.path.dirname(remote_dir))
                    if fallback_remote_path != remote_dir and is_subpath(fallback_remote_path, task_scan_path):
                        fallback_guard_expected_path = remote_dir
                        fallback_guard_parent_path = fallback_remote_path
                        fallback_start_local_rel = build_local_dir_rel(fallback_remote_path)
                        if not any(item[0] == fallback_remote_path for item in queue):
                            queue.insert(0, (fallback_remote_path, fallback_start_local_rel, None))
                        await write_monitor_log(
                            f"{refresh_source_label} 起始目录暂不可见，回退父目录重试: {fallback_remote_path}",
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
                    if is_task_root and child_dir_rel in manual_required_first_level_dirs:
                        manual_required_seen_first_level_dirs.add(child_dir_rel)
                    if (
                        is_task_root
                        and task["skip_by_dir_mtime"]
                        and not refresh_source_label
                        and modified_at
                        and child_state["entry_modified"]
                        and child_state["entry_modified"] == modified_at
                        and not child_has_dirty
                        and not force_first_level_rescan
                        and not manual_required_force_all_first_level
                        and child_dir_rel not in manual_required_first_level_dirs
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
                if item_local_rel not in previous_file_keys:
                    new_media_items.append(
                        {
                            "id": str(item.get("id", "") or "").strip(),
                            "fid": str(item.get("fid", "") or "").strip(),
                            "name": name,
                            "size": size,
                            "remote_rel": remote_rel,
                            "local_rel": item_local_rel,
                        }
                    )
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
        scope_preview = ", ".join(start_remote_paths[:5])
        if len(start_remote_paths) > 5:
            scope_preview += "..."
        await write_monitor_log(f"清理范围: {scope_preview}", "info")
        if stats["success_dirs"] == 0:
            raise RuntimeError("未成功读取任何目录，已停止并跳过过期 STRM 清理（避免误删）")

        cleanup_enabled = bool(task.get("sync_clean", not task.get("incremental", False)))
        if cleanup_enabled and stats["failed_dirs"] == 0:
            if task_root in scan_scope_rels:
                cursor.execute(
                    """
                    SELECT local_rel_path FROM monitor_files
                    WHERE task_name = ?
                    AND local_rel_path NOT IN (SELECT local_rel_path FROM current_scan)
                    """,
                    (task_name,),
                )
            else:
                scope_sql, scope_params = _monitor_scope_sql(scan_scope_rels)
                cursor.execute(
                    f"""
                    SELECT local_rel_path FROM monitor_files
                    WHERE task_name = ? AND ({scope_sql})
                    AND local_rel_path NOT IN (SELECT local_rel_path FROM current_scan)
                    """,
                    [task_name, *scope_params],
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
                    if task_root in scan_scope_rels:
                        cursor.execute("DELETE FROM monitor_files WHERE task_name = ?", (task_name,))
                    else:
                        scope_sql, scope_params = _monitor_scope_sql(scan_scope_rels)
                        cursor.execute(
                            f"""
                            DELETE FROM monitor_files
                            WHERE task_name = ? AND ({scope_sql})
                            """,
                            [task_name, *scope_params],
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
        if manual_required_scopes:
            from .monitor_changes import complete_manual_required_monitor_events

            covered_first_level_dirs = (
                set(pending_first_level_success)
                & manual_required_first_level_dirs
            ) - manual_required_failed_first_level_dirs
            if manual_required_root_scanned:
                covered_first_level_dirs.update(
                    manual_required_first_level_dirs - manual_required_seen_first_level_dirs
                )
            completed_event_ids = [
                int(scope.get("event_id", 0) or 0)
                for scope in manual_required_scopes
                if (
                    str(scope.get("first_level_dir_rel", "") or "") in covered_first_level_dirs
                    or (
                        not str(scope.get("first_level_dir_rel", "") or "")
                        and manual_required_root_scanned
                        and stats["failed_dirs"] == 0
                        and stats["skipped_first_level_dirs"] == 0
                    )
                )
            ]
            completed_manual_events = await asyncio.to_thread(
                complete_manual_required_monitor_events,
                task_name,
                completed_event_ids,
            )
            if completed_manual_events > 0:
                await write_monitor_log(
                    f"已清除需手动监控提示: {completed_manual_events} 条",
                    "success",
                )

        auto_summary = "-"
        if bool(task.get("auto_scrape_on_new")) and new_media_items:
            try:
                auto_message = await asyncio.to_thread(
                    _auto_scrape_new_media_items,
                    cfg,
                    task,
                    list(new_media_items),
                )
                auto_summary = auto_message
                await write_monitor_log(f"自动整理: {auto_message}", "success")
            except Exception as exc:
                await write_monitor_log(f"自动整理失败: {exc}", "error")

        await write_monitor_section("执行结果")
        await write_monitor_task_summary(stats, cleanup_enabled=cleanup_enabled)
        await write_monitor_log(build_monitor_conclusion_line(stats, auto_summary), "success")
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


def _single_line_monitor_change_path(value: Any) -> str:
    normalized = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    return " ".join(part.strip() for part in normalized.split("\n") if part.strip())


def _monitor_change_count(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


async def _write_monitor_change_details(details: Any) -> None:
    raw_details = details if isinstance(details, list) else []
    for detail in raw_details:
        if not isinstance(detail, dict):
            continue
        if detail.get("kind") == "file":
            changes = detail.get("changes", [])
            for change in changes if isinstance(changes, list) else []:
                if not isinstance(change, dict):
                    continue
                action = str(change.get("action", "") or "")
                label = {"delete": "删除 STRM", "generate": "生成 STRM"}.get(action, "")
                path = _single_line_monitor_change_path(change.get("path"))
                if not label or not path:
                    continue
                await write_monitor_log(
                    f"{label}: {path}",
                    "info" if action == "delete" else "success",
                )
            continue
        if detail.get("kind") != "folder":
            continue

        operation = str(detail.get("operation", "") or "").strip().lower()
        old_path = _single_line_monitor_change_path(detail.get("old_path"))
        new_path = _single_line_monitor_change_path(detail.get("new_path"))
        deleted = _monitor_change_count(detail.get("deleted", 0))
        generated = _monitor_change_count(detail.get("generated", 0))
        if old_path and new_path:
            label = "文件夹复制" if operation == "copy" else "文件夹变更"
            subject = f"{old_path} -> {new_path}"
            counts = f"生成 {generated}" if operation == "copy" else f"删除 {deleted}，生成 {generated}"
        elif old_path:
            label = "文件夹删除"
            subject = old_path
            counts = f"删除 {deleted}"
        elif new_path:
            label = "文件夹新增"
            subject = new_path
            counts = f"生成 {generated}"
        else:
            continue
        await write_monitor_log(f"{label}: {subject}（{counts}）", "info")


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
        await _write_monitor_change_details(result.get("change_details"))
        completed = max(0, int(result.get("completed", 0) or 0))
        failed = max(0, int(result.get("failed", 0) or 0))
        discarded = max(0, int(result.get("discarded", 0) or 0))
        generated = max(0, int(result.get("generated", 0) or 0))
        deleted = max(0, int(result.get("deleted", 0) or 0))
        directory_count = max(0, int(result.get("directory_count", 0) or 0))
        manual_required = max(0, int(result.get("manual_required", 0) or 0))
        summary_text = (
            f"变更同步汇总: 事件 {completed + failed + discarded}"
            f"（完成 {completed} / 失败 {failed} / 丢弃 {discarded}） | "
            f"生成 STRM {generated} | 删除 STRM {deleted} | 局部读取目录 {directory_count}"
        )
        if manual_required > 0:
            summary_text += f" | 需补扫 {manual_required}"
        await write_monitor_log(
            summary_text,
            "success"
            if failed == 0 and manual_required == 0
            else "warn",
        )
        new_media_items = result.get("new_media_items", [])
        if bool(task.get("auto_scrape_on_new")) and isinstance(new_media_items, list) and new_media_items:
            try:
                auto_message = await asyncio.to_thread(
                    _auto_scrape_new_media_items,
                    cfg,
                    task,
                    list(new_media_items),
                )
                await write_monitor_log(f"自动整理: {auto_message}", "success")
            except Exception as exc:
                await write_monitor_log(f"自动整理失败: {exc}", "error")
        auto_rescan_queued = 0
        manual_paths = result.get("manual_required_paths", [])
        if int(result.get("manual_required", 0) or 0) > 0 and isinstance(manual_paths, list) and manual_paths:
            auto_rescan_queued = _queue_auto_rescan_for_manual_required(cfg, manual_paths)
            if auto_rescan_queued > 0:
                path_preview = "、".join([str(path) for path in manual_paths[:5]])
                await write_monitor_log(f"已自动安排补扫目录：{path_preview}（无需手动操作）", "info")
            else:
                await write_monitor_log("自动补扫排队失败，请手动触发扫描确认", "warn")
        for error_item in (result.get("errors", []) if isinstance(result.get("errors"), list) else [])[:10]:
            if not isinstance(error_item, dict):
                continue
            retryable = bool(error_item.get("retryable", True))
            await write_monitor_log(
                (
                    "变更事件 #{event_id} 失败，已保留重试: {error}"
                    if retryable
                    else "变更事件 #{event_id} 已结束，不再重试: {error}"
                ).format(
                    event_id=max(0, int(error_item.get("event_id", 0) or 0)),
                    error=str(error_item.get("error", "") or "未知错误"),
                ),
                "error",
            )
        if int(result.get("failed", 0) or 0) > 0:
            status_text = "变更同步部分失败"
        elif int(result.get("manual_required", 0) or 0) > 0:
            status_text = "变更同步待自动补扫" if auto_rescan_queued > 0 else "变更同步待手动监控"
        else:
            status_text = "变更同步完成"
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

    raw_savepaths = raw_payload.get("savepaths")
    if not isinstance(raw_savepaths, list):
        raw_savepaths = []
    savepaths: List[str] = []
    for raw_path in raw_savepaths:
        savepath_item = normalize_relative_path(str(raw_path or "").strip())
        if savepath_item and savepath_item not in savepaths:
            savepaths.append(savepath_item)
    if savepaths:
        normalized["savepaths"] = savepaths[:MONITOR_SCAN_SAVEPATHS_MAX]

    provider = str(raw_payload.get("provider", "") or "").strip()
    if provider:
        normalized["provider"] = provider

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


def _monitor_savepath_scopes(payload: Optional[Dict[str, Any]]) -> List[str]:
    normalized_payload = _normalize_monitor_queue_payload(payload)
    scopes: List[str] = []
    single_scope = _monitor_queue_scope(normalized_payload)
    if single_scope:
        scopes.append(single_scope)
    for raw_path in normalized_payload.get("savepaths", []) or []:
        scope = normalize_remote_path("/" + normalize_relative_path(raw_path))
        if scope and scope not in scopes:
            scopes.append(scope)
    return scopes


def _monitor_scope_sql(scope_rels: List[str]) -> Tuple[str, List[Any]]:
    fragments: List[str] = []
    params: List[Any] = []
    for scope_rel in scope_rels:
        fragments.append("(local_rel_path = ? OR local_rel_path LIKE ? ESCAPE '\\')")
        params.append(scope_rel)
        params.append(_sql_like_descendant_pattern(scope_rel))
    return " OR ".join(fragments), params


def _merge_monitor_queue_payload(existing: Optional[Dict[str, Any]], incoming: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    existing_payload = _normalize_monitor_queue_payload(existing)
    incoming_payload = _normalize_monitor_queue_payload(incoming)

    existing_scope = _monitor_queue_scope(existing_payload)
    incoming_scope = _monitor_queue_scope(incoming_payload)
    existing_has_multi = bool(existing_payload.get("savepaths"))
    incoming_has_multi = bool(incoming_payload.get("savepaths"))
    merged_delay = max(
        int(existing_payload.get("delayTime", 0) or 0),
        int(incoming_payload.get("delayTime", 0) or 0),
    )

    merged_mode = "change" if (
        str(existing_payload.get("mode", "") or "").strip().lower() == "change"
        or str(incoming_payload.get("mode", "") or "").strip().lower() == "change"
    ) else "scan"
    if existing_has_multi or incoming_has_multi:
        merged_savepaths: List[str] = []
        for scope in _monitor_savepath_scopes(existing_payload) + _monitor_savepath_scopes(incoming_payload):
            scope_rel = normalize_relative_path(scope.lstrip("/"))
            if scope_rel and scope_rel not in merged_savepaths:
                merged_savepaths.append(scope_rel)
        merged_payload: Dict[str, Any] = {"mode": "change"} if merged_mode == "change" else {}
        if merged_savepaths and len(merged_savepaths) <= MONITOR_SCAN_SAVEPATHS_MAX:
            merged_payload["savepaths"] = merged_savepaths
            provider = str(
                existing_payload.get("provider", "") or incoming_payload.get("provider", "") or ""
            ).strip()
            if provider:
                merged_payload["provider"] = provider
        if merged_delay > 0:
            merged_payload["delayTime"] = merged_delay
        merged_payload.update(_merge_monitor_subscription_context(existing_payload, incoming_payload))
        return merged_payload

    merged_payload = {"mode": "change"} if merged_mode == "change" else {}
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


def queue_monitor_dir_scan(cfg: Dict[str, Any], provider: str, paths: List[str]) -> Dict[str, Any]:
    scan_provider = normalize_mount_provider(provider) or "115"
    scopes: List[str] = []
    for raw_path in paths or []:
        scope = normalize_relative_path(str(raw_path or "").strip())
        if scope and scope not in scopes:
            scopes.append(scope)
    if not scopes:
        raise ValueError("未提供有效的扫描目录")
    if len(scopes) > MONITOR_SCAN_SAVEPATHS_MAX:
        raise ValueError(f"扫描目录数量超过上限 {MONITOR_SCAN_SAVEPATHS_MAX} 个，请缩小勾选范围")

    tasks: Dict[str, Dict[str, Any]] = {}
    unmatched: List[str] = []
    for scope in scopes:
        matched = match_monitor_task_for_savepath(cfg, scope, provider=scan_provider)
        task_name = str(matched.get("task_name", "") or "").strip()
        if not task_name:
            unmatched.append(scope)
            continue
        tasks.setdefault(task_name, {"savepaths": []})["savepaths"].append(scope)

    if not tasks:
        raise ValueError("所选目录未匹配到任何监控任务")

    result_tasks: List[Dict[str, Any]] = []
    for task_name, entry in tasks.items():
        status = queue_monitor_job(
            task_name,
            "manual",
            {"provider": scan_provider, "savepaths": entry["savepaths"]},
        )
        result_tasks.append(
            {"task_name": task_name, "status": status, "matched": len(entry["savepaths"])}
        )
    return {"ok": True, "tasks": result_tasks, "unmatched": unmatched}


def _queue_auto_rescan_for_manual_required(cfg: Dict[str, Any], paths: Any) -> int:
    """为变更同步未知清单的文件夹自动排队补扫；返回成功排队的任务数。"""
    normalized_paths: List[str] = []
    for raw_path in paths if isinstance(paths, list) else []:
        path = normalize_relative_path(str(raw_path or "").strip())
        if path and path not in normalized_paths:
            normalized_paths.append(path)
    if not normalized_paths:
        return 0
    try:
        result = queue_monitor_dir_scan(cfg, "115", normalized_paths)
    except Exception:
        return 0
    tasks = result.get("tasks") if isinstance(result, dict) and isinstance(result.get("tasks"), list) else []
    return len(tasks)
