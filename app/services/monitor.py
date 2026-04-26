from ..background import submit_background
from ..core import *  # noqa: F401,F403
from .notify import push_monitor_success_notification

def write_strm_file(target_file: str, url: str) -> bool:
    old_content = None
    if os.path.exists(target_file):
        with open(target_file, "r", encoding="utf-8", errors="ignore") as f:
            old_content = f.read()
    if old_content == url:
        return False
    os.makedirs(os.path.dirname(target_file), exist_ok=True)
    with open(target_file, "w", encoding="utf-8") as f:
        f.write(url)
    return True


def remove_empty_parent_dirs(start_dir: str, stop_dir: str) -> int:
    removed = 0
    current = start_dir
    while current.startswith(stop_dir) and current != stop_dir:
        if os.path.isdir(current) and not os.listdir(current):
            os.rmdir(current)
            removed += 1
            current = os.path.dirname(current)
            continue
        break
    return removed


async def mark_cached_dir_as_seen(
    conn: sqlite3.Connection,
    task_name: str,
    local_prefix: str,
) -> None:
    cursor = conn.cursor()
    like_prefix = f"{local_prefix}/%" if local_prefix else "%"
    cursor.execute(
        """
        INSERT OR REPLACE INTO current_scan (local_rel_path, remote_rel_path, remote_modified, file_size)
        SELECT local_rel_path, remote_rel_path, remote_modified, file_size
        FROM monitor_files
        WHERE task_name = ? AND (local_rel_path = ? OR local_rel_path LIKE ?)
        """,
        (task_name, local_prefix, like_prefix),
    )
    await asyncio.sleep(0)


async def run_monitor_task(
    task_name: str,
    trigger: str = "manual",
    payload: Optional[Dict[str, Any]] = None,
    merged_count: int = 0,
) -> None:
    cfg = get_config()
    task = next((t for t in cfg["monitor_tasks"] if t["name"] == task_name), None)
    if not task:
        await write_monitor_log(f"任务不存在: {task_name}", "error")
        return
    config_error = validate_monitor_runtime_config(cfg, task)
    if config_error:
        await write_monitor_log(f"任务配置错误: {config_error}", "error")
        update_monitor_summary("任务失败", config_error)
        return

    if monitor_status["running"]:
        return

    ensure_db()
    monitor_status["running"] = True
    monitor_status["current_task"] = task_name
    monitor_control["cancel"] = False
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
    }
    generated_strm_paths: List[str] = []

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

        conn = sqlite3.connect(DB_PATH)
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
        queue: List[Tuple[str, str]] = [(start_remote_path, start_local_rel)]
        scanned_dirs = set()
        fallback_guard_expected_path = ""
        fallback_guard_parent_path = ""

        await write_monitor_section("扫描生成")

        while queue:
            remote_dir, local_dir_rel = queue.pop(0)
            check_monitor_cancelled()
            if remote_dir in scanned_dirs:
                continue

            update_monitor_summary("扫描目录", remote_dir)
            await write_monitor_log(f"读取目录: {remote_dir}", "info")

            try:
                # Always reload each visited directory so moved/new files inside
                # existing folders are visible during recursive scans.
                modified, items = await list_remote_dir(cfg, remote_dir, True, task)
                stats["success_dirs"] += 1
            except Exception as exc:
                stats["failed_dirs"] += 1
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
                            queue.insert(0, (start_remote_path, start_local_rel))
                        await write_monitor_log(
                            f"{refresh_source_label} 起始目录暂不可见，回退父目录重试: {start_remote_path}",
                            "warn",
                        )
                        await write_monitor_log(
                            f"{refresh_source_label} 回退后将仅扫描目标子树: {fallback_guard_expected_path}",
                            "warn",
                        )
                continue
            scanned_dirs.add(remote_dir)

            dir_rel = normalize_relative_path(os.path.relpath(local_dir_rel, task_root)) if local_dir_rel != task_root else ""
            if task["skip_by_dir_mtime"] and modified:
                cursor.execute(
                    "SELECT remote_modified FROM monitor_dirs WHERE task_name = ? AND dir_rel_path = ?",
                    (task_name, dir_rel),
                )
                row = cursor.fetchone()
                if row and row[0] and row[0] >= modified:
                    stats["skipped_dirs"] += 1
                    await mark_cached_dir_as_seen(conn, task_name, local_dir_rel)
                    await write_monitor_log(f"跳过目录: {remote_dir}", "warn")
                    if task["list_delay_ms"] > 0:
                        await sleep_interruptible(task["list_delay_ms"] / 1000)
                    continue

            cursor.execute(
                "INSERT OR REPLACE INTO monitor_dirs(task_name, dir_rel_path, remote_modified) VALUES (?, ?, ?)",
                (task_name, dir_rel, modified),
            )

            fallback_target_branch_found = False
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
                    queue.append((item_remote_path, item_local_rel))
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

                target_file = os.path.join(STRM_ROOT, item_local_rel + ".strm")
                strm_url = build_strm_play_url(cfg, item_remote_path, pick_code=item.get("pick_code", ""))
                changed = await asyncio.to_thread(write_strm_file, target_file, strm_url)
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

            if (
                fallback_guard_expected_path
                and remote_dir == fallback_guard_parent_path
                and not fallback_target_branch_found
            ):
                await write_monitor_log(
                    f"{refresh_source_label} 回退父目录未发现目标子目录，已跳过同级目录避免误扫",
                    "warn",
                )

            if task["list_delay_ms"] > 0:
                await sleep_interruptible(task["list_delay_ms"] / 1000)

        await write_monitor_section("清理校正")
        await write_monitor_log(f"清理范围: {start_remote_path}", "info")
        if stats["success_dirs"] == 0:
            raise RuntimeError("未成功读取任何目录，已停止并跳过清理（避免误删本地文件）")

        if not task["incremental"] and stats["failed_dirs"] == 0:
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
                scope_like = f"{start_local_rel}/%"
                cursor.execute(
                    """
                    SELECT local_rel_path FROM monitor_files
                    WHERE task_name = ?
                    AND (local_rel_path = ? OR local_rel_path LIKE ?)
                    AND local_rel_path NOT IN (SELECT local_rel_path FROM current_scan)
                    """,
                    (task_name, start_local_rel, scope_like),
                )
            stale_files = [row[0] for row in cursor.fetchall()]
            for local_rel_path in stale_files:
                check_monitor_cancelled()
                target_file = os.path.join(STRM_ROOT, local_rel_path + ".strm")
                if os.path.exists(target_file):
                    os.remove(target_file)
                    stats["deleted_files"] += 1
                    stats["deleted_dirs"] += remove_empty_parent_dirs(
                        os.path.dirname(target_file), os.path.join(STRM_ROOT, task_root)
                    )

            if start_local_rel == task_root:
                cursor.execute("DELETE FROM monitor_files WHERE task_name = ?", (task_name,))
            else:
                scope_like = f"{start_local_rel}/%"
                cursor.execute(
                    """
                    DELETE FROM monitor_files
                    WHERE task_name = ? AND (local_rel_path = ? OR local_rel_path LIKE ?)
                    """,
                    (task_name, start_local_rel, scope_like),
                )

        else:
            if not task["incremental"] and stats["failed_dirs"] > 0:
                await write_monitor_log("检测到目录读取失败，已自动跳过清理阶段以防误删", "warn")
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
        conn.commit()
        conn.close()
        conn = None

        await write_monitor_section("执行结果")
        await write_monitor_task_summary(stats)
        try:
            notify_result = await push_monitor_success_notification(
                cfg=cfg,
                task=task,
                trigger=trigger,
                stats=stats,
                generated_strm_paths=generated_strm_paths,
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
        except Exception as notify_exc:
            await write_monitor_log(f"通知推送失败: {notify_exc}", "warn")
        await write_monitor_task_footer(task_name, "执行成功")
        update_monitor_summary("任务完成", f"{task_name} 执行结束")
    except asyncio.CancelledError:
        await write_monitor_section("执行结果")
        await write_monitor_task_summary(stats)
        await write_monitor_task_footer(task_name, "已中断")
        update_monitor_summary("任务中断", task_name)
    except Exception as exc:
        await write_monitor_section("执行结果")
        await write_monitor_task_summary(stats)
        await write_monitor_log(f"失败原因: {exc}", "error")
        await write_monitor_task_footer(task_name, "执行失败")
        update_monitor_summary("任务失败", str(exc))
    finally:
        try:
            if "conn" in locals() and conn is not None:
                conn.close()
        except Exception:
            pass
        monitor_status["running"] = False
        monitor_status["current_task"] = ""
        monitor_control["cancel"] = False
        schedule_ui_state_push(0)
        await start_next_monitor_job()


async def start_next_monitor_job() -> None:
    if monitor_status["running"] or not monitor_queue:
        monitor_status["queued"] = [item["task_name"] for item in monitor_queue]
        schedule_ui_state_push(0)
        return
    next_job = monitor_queue.pop(0)
    monitor_status["queued"] = [item["task_name"] for item in monitor_queue]
    schedule_ui_state_push(0)
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

    return normalized


def _monitor_queue_scope(payload: Optional[Dict[str, Any]]) -> str:
    normalized_payload = _normalize_monitor_queue_payload(payload)
    savepath = normalize_relative_path(normalized_payload.get("savepath", ""))
    if not savepath:
        return ""
    return normalize_remote_path("/" + savepath)


def _merge_monitor_queue_payload(existing: Optional[Dict[str, Any]], incoming: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    existing_payload = _normalize_monitor_queue_payload(existing)
    incoming_payload = _normalize_monitor_queue_payload(incoming)
    if not existing_payload:
        return incoming_payload
    if not incoming_payload:
        return existing_payload

    existing_scope = _monitor_queue_scope(existing_payload)
    incoming_scope = _monitor_queue_scope(incoming_payload)
    merged_delay = max(
        int(existing_payload.get("delayTime", 0) or 0),
        int(incoming_payload.get("delayTime", 0) or 0),
    )

    merged_payload: Dict[str, Any]
    if not existing_scope or not incoming_scope:
        merged_payload = {}
    elif existing_scope == incoming_scope:
        # 同目录短时间多次触发时，统一提升为父目录刷新，避免因 sharetitle 不同造成风暴排队。
        merged_payload = {"savepath": normalize_relative_path(existing_scope.lstrip("/"))}
    elif is_subpath(existing_scope, incoming_scope):
        merged_payload = {"savepath": normalize_relative_path(incoming_scope.lstrip("/"))}
    elif is_subpath(incoming_scope, existing_scope):
        merged_payload = {"savepath": normalize_relative_path(existing_scope.lstrip("/"))}
    else:
        # 不同分支目录并发触发时，回退全任务刷新，保证不漏刷。
        merged_payload = {}

    if merged_delay > 0:
        merged_payload["delayTime"] = merged_delay
    return merged_payload


def _pick_monitor_trigger(existing_trigger: str, new_trigger: str) -> str:
    trigger_priority = {
        "queued": 0,
        "resource": 1,
        "webhook": 2,
        "cron": 3,
        "manual": 4,
    }
    existing = str(existing_trigger or "").strip().lower() or "queued"
    incoming = str(new_trigger or "").strip().lower() or "queued"
    if trigger_priority.get(incoming, 0) >= trigger_priority.get(existing, 0):
        return incoming
    return existing


def queue_monitor_job(task_name: str, trigger: str, payload: Optional[Dict[str, Any]] = None) -> str:
    normalized_task_name = str(task_name or "").strip()
    if not normalized_task_name:
        schedule_ui_state_push(0)
        return "queued"

    normalized_trigger = str(trigger or "").strip().lower() or "manual"
    normalized_payload = _normalize_monitor_queue_payload(payload)

    for queued_item in monitor_queue:
        if str(queued_item.get("task_name", "")).strip() != normalized_task_name:
            continue
        queued_item["payload"] = _merge_monitor_queue_payload(queued_item.get("payload"), normalized_payload)
        queued_item["trigger"] = _pick_monitor_trigger(queued_item.get("trigger", "queued"), normalized_trigger)
        queued_item["merge_count"] = max(0, int(queued_item.get("merge_count", 0) or 0)) + 1
        monitor_status["queued"] = [item["task_name"] for item in monitor_queue]
        schedule_ui_state_push(0)
        return "queued"

    monitor_queue.append(
        {
            "task_name": normalized_task_name,
            "trigger": normalized_trigger,
            "payload": normalized_payload,
            "merge_count": 0,
        }
    )
    monitor_status["queued"] = [item["task_name"] for item in monitor_queue]
    schedule_ui_state_push(0)
    if monitor_status["running"]:
        return "queued"
    submit_background(start_next_monitor_job, label="monitor-next")
    return "started"
