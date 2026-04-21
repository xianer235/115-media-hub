from ..core import *  # noqa: F401,F403


def _format_tree_elapsed_seconds(seconds: float) -> str:
    return f"{max(0.0, float(seconds or 0.0)):.2f}秒"


async def run_sync(use_local: bool = False, force_full: bool = False) -> None:
    if task_status["running"]:
        return
    task_status["running"] = True
    schedule_ui_state_push(0)
    cfg = get_config()
    os.makedirs(TREE_DIR, exist_ok=True)
    ensure_db()
    run_started_at = time.perf_counter()
    prefetch_elapsed_seconds = 0.0
    generate_elapsed_seconds = 0.0
    cleanup_elapsed_seconds = 0.0
    generated_file_count = 0
    unchanged_file_count = 0
    stale_file_candidates = 0
    deleted_file_count = 0
    delete_failed_file_count = 0
    stale_index_count = 0

    try:
        config_error = validate_tree_runtime_config(cfg, use_local)
        if config_error:
            raise RuntimeError(config_error)

        trees = [t for t in cfg.get("trees", []) if t.get("url")]
        downloaded_tree_count = 0

        scan_results: List[str] = []
        user_exts = get_user_extensions(cfg)
        check_hash_enabled = bool(cfg.get("check_hash", False))
        can_skip_by_hash = check_hash_enabled and cfg.get("sync_mode") != "full" and not force_full
        last_hash_state = parse_last_hash_state(cfg.get("last_hash", ""))
        last_tree_hashes = last_hash_state.get("trees", {}) if isinstance(last_hash_state.get("trees", {}), dict) else {}
        last_tree_keys = last_hash_state.get("tree_keys", []) if isinstance(last_hash_state.get("tree_keys", []), list) else []
        current_tree_hashes: Dict[str, Dict[str, str]] = {}
        current_tree_keys: List[str] = []
        skipped_tree_count = 0
        parsed_tree_count = 0
        if check_hash_enabled and not can_skip_by_hash:
            await write_log("ℹ 已开启 MD5 校验，但当前为全量模式，跳过策略不生效")
        await write_log(
            f"━━━━━━━━━━【任务开始 | 目录树 | 源 {len(trees)} 个 | 模式 {cfg.get('sync_mode', 'incremental')} | MD5校验 {'开' if check_hash_enabled else '关'}】━━━━━━━━━━",
            "task-divider",
        )

        for idx, tree in enumerate(trees):
            raw_path = f"{TREE_DIR}/tree_{idx}.raw"
            txt_path = f"{TREE_DIR}/tree_{idx}.txt"
            tree_key = build_tree_cache_key(tree)
            current_tree_keys.append(tree_key)
            tree_cache_path = os.path.join(TREE_DIR, f"cache_{tree_key}.json")
            tree_scan_results: List[str] = []
            parse_signature = ""

            if not use_local:
                await refresh_tree_file(tree["url"], cfg)
                await update_progress("正在下载", (idx / max(len(trees), 1) * 15), f"获取第 {idx + 1} 个目录树...")
                await download_tree(tree["url"], raw_path, cfg)
                downloaded_tree_count += 1

            if os.path.exists(raw_path):
                file_hash = await asyncio.to_thread(calculate_file_md5, raw_path)
                parse_signature = build_tree_parse_signature(file_hash, user_exts)
                if can_skip_by_hash:
                    old_state = last_tree_hashes.get(tree_key, {})
                    old_signature = old_state.get("parse_signature", "") if isinstance(old_state, dict) else ""
                    if old_signature and old_signature == parse_signature:
                        cached_paths = await asyncio.to_thread(load_tree_cache, tree_cache_path)
                        if cached_paths is not None:
                            skipped_tree_count += 1
                            scan_results.extend(cached_paths)
                            current_tree_hashes[tree_key] = {"parse_signature": parse_signature}
                            await write_log(f"第 {idx + 1} 个目录树 MD5 无变化，复用缓存 {len(cached_paths)} 条")
                            continue

            if os.path.exists(raw_path):
                await update_progress("正在转码", 15 + (idx / max(len(trees), 1) * 5), f"转码目录树 {idx + 1}...")
                proc = await asyncio.create_subprocess_exec(
                    "iconv",
                    "-f",
                    "UTF-16LE",
                    "-t",
                    "UTF-8//IGNORE",
                    raw_path,
                    "-o",
                    txt_path,
                )
                code = await proc.wait()
                if code != 0:
                    raise RuntimeError(f"目录树 {idx + 1} 转码失败，退出码: {code}")

            parsed_this_tree = False
            if os.path.exists(txt_path):
                await update_progress("解析中", 20 + (idx / max(len(trees), 1) * 20), f"处理第 {idx + 1} 个结构...")
                path_stack: Dict[int, str] = {}
                prefix = normalize_relative_path(tree.get("prefix", ""))
                exclude = int(tree.get("exclude", 1) or 1)
                parsed_this_tree = True
                with open(txt_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        level = line.count("|")
                        clean_name = re.sub(r"^[|\s—-]+", "", line).strip()
                        if not clean_name:
                            continue
                        path_stack[level] = clean_name
                        if is_video_file(clean_name, user_exts):
                            full_parts = [path_stack[l] for l in range(level + 1) if l in path_stack]
                            rel_parts = full_parts[exclude:]
                            final_rel_path = join_relative_path(prefix, "/".join(rel_parts))
                            if final_rel_path:
                                tree_scan_results.append(final_rel_path)
                                scan_results.append(final_rel_path)

            if parse_signature:
                current_tree_hashes[tree_key] = {"parse_signature": parse_signature}
            if parsed_this_tree:
                parsed_tree_count += 1
                await asyncio.to_thread(save_tree_cache, tree_cache_path, tree_scan_results)

        if check_hash_enabled:
            cfg["last_hash"] = json.dumps(
                {"version": 2, "tree_keys": current_tree_keys, "trees": current_tree_hashes},
                ensure_ascii=False,
                sort_keys=True,
            )
            save_config(cfg)

        tree_layout_changed = sorted(last_tree_keys) != sorted(current_tree_keys)
        if can_skip_by_hash and trees and skipped_tree_count == len(trees) and tree_layout_changed:
            await write_log("ℹ 目录树源配置有变更，继续执行同步以校正结果")
        if can_skip_by_hash and trees and skipped_tree_count == len(trees) and not tree_layout_changed:
            prefetch_elapsed_seconds = max(0.0, time.perf_counter() - run_started_at)
            await write_log(f"本轮概况：下载 {downloaded_tree_count} 个，缓存复用 {skipped_tree_count} 个，解析 {parsed_tree_count} 个")
            await write_log("✅ MD5 校验命中：全部目录树无变动，跳过解析与同步")
            await write_log(
                f"任务耗时：前置处理 {_format_tree_elapsed_seconds(prefetch_elapsed_seconds)} | 总 {_format_tree_elapsed_seconds(prefetch_elapsed_seconds)}"
            )
            await write_log("━━━━━━━━━━【任务结束 | 目录树 | MD5 校验命中】━━━━━━━━━━", "task-divider")
            await update_progress("任务完成", 100, "MD5 校验命中：无变动")
            return

        total_files = len(scan_results)
        prefetch_elapsed_seconds = max(0.0, time.perf_counter() - run_started_at)
        await write_log(f"本轮概况：下载 {downloaded_tree_count} 个，缓存复用 {skipped_tree_count} 个，解析 {parsed_tree_count} 个")
        await write_log(f"解析完成，共发现 {total_files} 个有效文件")
        if total_files == 0:
            if downloaded_tree_count > 0 or use_local:
                await write_log("⚠ 目录树下载成功，但未匹配到可生成文件；本次按成功结束并跳过清理")
                total_elapsed_seconds = max(0.0, time.perf_counter() - run_started_at)
                await write_log(
                    f"任务耗时：前置处理 {_format_tree_elapsed_seconds(prefetch_elapsed_seconds)} | 总 {_format_tree_elapsed_seconds(total_elapsed_seconds)}"
                )
                await write_log("━━━━━━━━━━【任务结束 | 目录树 | 执行成功】━━━━━━━━━━", "task-divider")
                await update_progress("任务完成", 100, "目录树下载成功，但未匹配可生成文件")
                return
            raise RuntimeError("扫描结果为空，且未成功下载目录树")

        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.cursor()
            cursor.execute("CREATE TEMP TABLE current_scan (path_hash TEXT PRIMARY KEY, relative_path TEXT)")

            alist_base = cfg["alist_url"].rstrip("/")
            mount_path = cfg["mount_path"].strip("/")
            generate_started_at = time.perf_counter()

            for i, rel_path in enumerate(scan_results):
                target = os.path.join(STRM_ROOT, rel_path + ".strm")
                needs_regenerate = (not os.path.exists(target)) or cfg["sync_mode"] == "full" or force_full
                if needs_regenerate:
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    encoded_path = urllib.parse.quote(f"/{mount_path}/{rel_path}")
                    with open(target, "w", encoding="utf-8") as sf:
                        sf.write(f"{alist_base}/d{encoded_path}")
                    generated_file_count += 1
                else:
                    unchanged_file_count += 1

                path_hash = hashlib.md5(rel_path.encode("utf-8")).hexdigest()
                cursor.execute("INSERT OR IGNORE INTO current_scan VALUES (?, ?)", (path_hash, rel_path))
                if total_files and i % 1000 == 0:
                    await update_progress("生成STRM", 40 + (i / total_files * 50), f"进度: {i}/{total_files}")

            generate_elapsed_seconds = max(0.0, time.perf_counter() - generate_started_at)
            cleanup_started_at = time.perf_counter()

            cursor.execute(
                "SELECT relative_path FROM local_files WHERE path_hash NOT IN (SELECT path_hash FROM current_scan)"
            )
            stale_rows = cursor.fetchall()
            stale_file_candidates = len(stale_rows)
            if cfg.get("sync_clean", True):
                for (dead_path,) in stale_rows:
                    target = os.path.join(STRM_ROOT, dead_path + ".strm")
                    if not os.path.exists(target):
                        continue
                    try:
                        os.remove(target)
                        deleted_file_count += 1
                    except Exception:
                        delete_failed_file_count += 1

            # 无论是否启用物理清理，数据库都应只保留本轮扫描结果，避免陈旧数据长期累积
            stale_index_count = stale_file_candidates
            cursor.execute("DELETE FROM local_files WHERE path_hash NOT IN (SELECT path_hash FROM current_scan)")
            cursor.execute("INSERT OR REPLACE INTO local_files SELECT * FROM current_scan")
            conn.commit()
            cleanup_elapsed_seconds = max(0.0, time.perf_counter() - cleanup_started_at)
        finally:
            conn.close()

        cleanup_mode_label = "开启" if cfg.get("sync_clean", True) else "关闭"
        await update_progress("任务完成", 100, f"同步成功: {total_files} 文件")
        await write_log(
            f"生成汇总: 新增/更新 {generated_file_count} | 保持不变 {unchanged_file_count} | 总扫描 {total_files}"
        )
        await write_log(
            (
                f"清理汇总: 模式 {cleanup_mode_label} | 过期记录 {stale_file_candidates} | 删除文件 {deleted_file_count} | "
                f"删除失败 {delete_failed_file_count} | 索引清理 {stale_index_count}"
            )
        )
        total_elapsed_seconds = max(0.0, time.perf_counter() - run_started_at)
        await write_log(
            (
                f"任务耗时: 前置处理 {_format_tree_elapsed_seconds(prefetch_elapsed_seconds)} | "
                f"生成写入 {_format_tree_elapsed_seconds(generate_elapsed_seconds)} | "
                f"清理落库 {_format_tree_elapsed_seconds(cleanup_elapsed_seconds)} | "
                f"总 {_format_tree_elapsed_seconds(total_elapsed_seconds)}"
            )
        )
        await write_log("━━━━━━━━━━【任务结束 | 目录树 | 执行成功】━━━━━━━━━━", "task-divider")
    except Exception as exc:
        await write_log(f"❌ 运行故障: {exc}")
        failed_elapsed_seconds = max(0.0, time.perf_counter() - run_started_at)
        await write_log(f"任务耗时: 总 {_format_tree_elapsed_seconds(failed_elapsed_seconds)}", "warn")
        await write_log("━━━━━━━━━━【任务结束 | 目录树 | 执行失败】━━━━━━━━━━", "task-divider")
        await update_progress("任务中止", 0, str(exc))
    finally:
        task_status["running"] = False
        schedule_ui_state_push(0)
