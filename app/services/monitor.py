from ..core import *  # noqa: F401,F403

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


async def run_monitor_task(task_name: str, trigger: str = "manual", payload: Optional[Dict[str, Any]] = None) -> None:
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

    try:
        await write_monitor_task_header(task, trigger, payload)
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
        alist_base = cfg["alist_url"].rstrip("/")
        extensions = get_user_extensions(cfg)
        min_bytes = int(task["min_file_size_mb"] * 1024 * 1024)
        start_remote_path = normalize_remote_path(task["scan_path"])
        if trigger in ("webhook", "resource") and payload:
            hinted_path = extract_webhook_refresh_path(task, payload, cfg)
            source_label = "Webhook" if trigger == "webhook" else "资源导入"
            if hinted_path:
                start_remote_path = hinted_path
                await write_monitor_log(f"{source_label} 定位刷新目录: {start_remote_path}", "info")
            else:
                await write_monitor_log(f"{source_label} 未识别到有效子目录，回退全任务路径刷新", "warn")

        local_sub_rel = normalize_relative_path(
            os.path.relpath(start_remote_path, task["scan_path"])
        ) if start_remote_path != task["scan_path"] else ""
        start_local_rel = join_relative_path(task_root, local_sub_rel)
        queue: List[Tuple[str, str]] = [(start_remote_path, start_local_rel)]
        seen_dirs = set()

        await write_monitor_section("扫描生成")

        while queue:
            remote_dir, local_dir_rel = queue.pop(0)
            check_monitor_cancelled()
            if remote_dir in seen_dirs:
                continue
            seen_dirs.add(remote_dir)

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
                continue

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
                    queue.append((item_remote_path, item_local_rel))
                    continue

                if not is_video_file(name, extensions):
                    stats["skipped"] += 1
                    continue
                if min_bytes > 0 and size < min_bytes:
                    stats["skipped"] += 1
                    continue

                target_file = os.path.join(STRM_ROOT, item_local_rel + ".strm")
                encoded_path = urllib.parse.quote(item_remote_path)
                strm_url = f"{alist_base}/d{encoded_path}"
                changed = await asyncio.to_thread(write_strm_file, target_file, strm_url)
                if changed:
                    stats["generated"] += 1
                    await write_monitor_log(f"生成: {target_file}", "success")
                else:
                    stats["skipped"] += 1

                remote_rel = normalize_relative_path(os.path.relpath(item_remote_path, task["scan_path"]))
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO current_scan(local_rel_path, remote_rel_path, remote_modified, file_size)
                    VALUES (?, ?, ?, ?)
                    """,
                    (item_local_rel, remote_rel, modified_at, size),
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
    asyncio.create_task(
        run_monitor_task(
            next_job["task_name"],
            trigger=next_job.get("trigger", "queued"),
            payload=next_job.get("payload"),
        )
    )


def queue_monitor_job(task_name: str, trigger: str, payload: Optional[Dict[str, Any]] = None) -> str:
    normalized_payload = payload or {}
    job_signature = safe_json_dumps({"task_name": task_name, "trigger": trigger, "payload": normalized_payload})
    if any(item.get("job_signature") == job_signature for item in monitor_queue):
        schedule_ui_state_push(0)
        return "queued"
    monitor_queue.append(
        {
            "task_name": task_name,
            "trigger": trigger,
            "payload": normalized_payload,
            "job_signature": job_signature,
        }
    )
    monitor_status["queued"] = [item["task_name"] for item in monitor_queue]
    schedule_ui_state_push(0)
    if monitor_status["running"]:
        return "queued"
    asyncio.create_task(start_next_monitor_job())
    return "started"
