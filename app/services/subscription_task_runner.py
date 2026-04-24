from . import subscription as _subscription

# The runner keeps the historical helper surface from subscription.py while
# the large task orchestration functions live in this focused module.
globals().update(
    {
        key: value
        for key, value in _subscription.__dict__.items()
        if key not in {"__name__", "__package__", "__loader__", "__spec__", "__file__", "__cached__"}
    }
)

async def _run_subscription_task_quark(
    cfg: Dict[str, Any],
    task: Dict[str, Any],
    task_name: str,
    trigger: str,
    subscription_run_id: str,
    batch_refresh_enabled: bool,
    stage_timer: Optional[Dict[str, Any]] = None,
) -> None:
    await write_subscription_log("网盘提供方：夸克（独立评分与导入链路）", "info")
    await write_subscription_log(
        f"类型: {'电影' if task['media_type'] == 'movie' else '电视剧'} | 标题: {task['title']} | 保存路径: {task['savepath']}",
        "info",
    )
    await write_subscription_log(
        f"执行批次: {subscription_run_id} | 批次收口刷新: {'开启' if batch_refresh_enabled else '关闭（夸克独立链路）'}",
        "info",
    )
    if int(task.get("tmdb_id", 0) or 0) > 0:
        tmdb_label = str(task.get("tmdb_title", "") or task.get("title", "") or "--").strip()
        tmdb_year = normalize_tmdb_year(task.get("tmdb_year", ""))
        tmdb_tail = f" ({tmdb_year})" if tmdb_year else ""
        await write_subscription_log(
            f"TMDB 绑定: {tmdb_label}{tmdb_tail} | ID: {int(task.get('tmdb_id', 0) or 0)}",
            "info",
        )
    if task["media_type"] == "tv":
        configured_total = resolve_subscription_tv_total_episodes(task, state_total=0)
        tv_mode_text = "多季合一" if is_subscription_multi_season_mode(task) else "单季订阅"
        if is_subscription_anime_compatible_task(task):
            tv_mode_text += " / 动漫兼容"
        season_label = "全季" if is_subscription_multi_season_mode(task) else f"S{int(task.get('season', 1) or 1):02d}"
        await write_subscription_log(
            f"季: {season_label} | 总集数: {configured_total or '自动识别'} | 模式: {tv_mode_text}",
            "info",
        )
    check_subscription_cancelled()

    state = load_subscription_task_state(task_name, task.get("media_type", "movie"))
    last_episode = max(0, int(state.get("last_episode", 0) or 0))
    state_stats = state.get("stats", {}) if isinstance(state.get("stats"), dict) else {}
    if task["media_type"] == "tv" and bool(state_stats.get("existing_episode_scan_ready", False)):
        state_existing_max = max(0, int(state_stats.get("existing_episode_max", 0) or 0))
        state_existing_entries = max(0, int(state_stats.get("existing_episode_scanned_entries", 0) or 0))
        if state_existing_max > 0:
            last_episode = state_existing_max
        elif last_episode > 0 and state_existing_entries <= 0:
            last_episode = 0
    known_total = resolve_subscription_tv_total_episodes(
        task,
        state_total=max(0, int(state.get("total_episodes", 0) or 0)),
    )
    single_season_episode_upper_bound = (
        known_total
        if task["media_type"] == "tv" and known_total > 0 and (not is_subscription_multi_season_mode(task))
        else 0
    )
    if single_season_episode_upper_bound > 0 and last_episode > single_season_episode_upper_bound:
        last_episode = single_season_episode_upper_bound

    completed_locked = task["media_type"] == "tv" and known_total > 0 and last_episode >= known_total
    if completed_locked:
        await write_subscription_log(
            f"当前记录为已完结（{last_episode}/{known_total}），本次仍会检查启用频道是否有重发/更优资源",
            "warn",
        )

    upsert_subscription_task_state(task_name, status="running", progress=15, detail="正在主动搜索夸克资源")
    check_subscription_cancelled()
    _subscription_stage_timer_enter(stage_timer, "search")
    search_started_at = time.perf_counter()
    search_result = await find_subscription_task_match_candidate_by_search(
        task,
        last_episode=last_episode,
        trigger=trigger,
    )
    search_duration_seconds = max(0.0, time.perf_counter() - search_started_at)
    search_stats = search_result.get("stats", {}) if isinstance(search_result.get("stats"), dict) else {}
    search_errors = search_result.get("errors", []) if isinstance(search_result.get("errors"), list) else []
    search_keywords = search_result.get("keywords", []) if isinstance(search_result.get("keywords"), list) else []
    searched_sources = int(search_stats.get("searched_sources", 0) or 0)
    matched_channels = int(search_stats.get("matched_channels", 0) or 0)
    pages_scanned = int(search_stats.get("pages_scanned", 0) or 0)
    deduped_items = int(search_stats.get("deduped_items", 0) or 0)
    supported_items = int(search_stats.get("supported_items", 0) or 0)
    unsupported_items = int(search_stats.get("unsupported_items", 0) or 0)
    await write_subscription_log(
        f"夸克搜索关键词: " + " / ".join(search_keywords or [str(task.get("title", "")).strip() or "--"]),
        "info",
    )
    await write_subscription_log(
        (
            f"夸克搜索完成：频道检索 {searched_sources} 次，命中频道 {matched_channels} 个，"
            f"扫描页面 {pages_scanned} 页，候选资源 {deduped_items} 条，可导入资源 {supported_items} 条"
        ),
        "info",
    )
    await write_subscription_log(f"夸克搜索阶段耗时：{_format_elapsed_seconds(search_duration_seconds)}", "info")
    if unsupported_items > 0:
        await write_subscription_log(
            f"已过滤 {unsupported_items} 条非夸克链接（当前 provider=quark，仅支持夸克分享）",
            "warn",
        )
    if int(search_stats.get("title_blocked_candidates", 0) or 0) > 0:
        await write_subscription_log(
            f"已拦截 {int(search_stats.get('title_blocked_candidates', 0) or 0)} 条“仅集数命中/标题不匹配”候选",
            "warn",
        )
    if int(search_stats.get("quark_media_relaxed_pass", 0) or 0) > 0:
        await write_subscription_log(
            f"已放行 {int(search_stats.get('quark_media_relaxed_pass', 0) or 0)} 条“标题命中但无集数标记”候选，待后续精细扫描判定",
            "info",
        )
    if int(search_stats.get("quark_low_score_kept", 0) or 0) > 0:
        await write_subscription_log(
            f"已保留 {int(search_stats.get('quark_low_score_kept', 0) or 0)} 条低于阈值但标题命中的电视剧候选（召回优先）",
            "info",
        )
    if bool(search_stats.get("incremental_search_enabled", False)):
        await write_subscription_log(
            (
                f"频道增量搜索已启用：加载水位 {int(search_stats.get('incremental_channel_watermarks_loaded', 0) or 0)} 个，"
                f"命中增量边界 {int(search_stats.get('incremental_stop_channels', 0) or 0)} 个频道，"
                f"推进水位 {int(search_stats.get('incremental_channel_watermarks_advanced', 0) or 0)} 个频道，"
                f"异常未推进 {int(search_stats.get('incremental_channel_watermarks_error_channels', 0) or 0)} 个频道"
            ),
            "info",
        )
    if int(search_stats.get("channel_support_rows_updated", 0) or 0) > 0:
        await write_subscription_log(
            f"频道支持度统计已更新 {int(search_stats.get('channel_support_rows_updated', 0) or 0)} 个频道",
            "info",
        )
    if search_errors:
        await write_subscription_log(
            f"有 {len(search_errors)} 个频道搜索异常（不影响其余频道）："
            + "；".join(
                [
                    (
                        f"{str(err.get('name', '') or err.get('channel_id', '未知频道')).strip()}:"
                        f"{str(err.get('message', '')).strip()}"
                    )[:120]
                    for err in search_errors[:3]
                ]
            ),
            "warn",
        )

    upsert_subscription_task_state(task_name, status="running", progress=25, detail="候选准备完成，正在匹配评分")
    check_subscription_cancelled()
    ranked_candidates = search_result.get("candidates", []) if isinstance(search_result.get("candidates"), list) else []
    if not ranked_candidates:
        legacy_candidate = search_result.get("candidate", {}) if isinstance(search_result.get("candidate"), dict) else {}
        if legacy_candidate:
            ranked_candidates = [legacy_candidate]
    if not ranked_candidates:
        _subscription_stage_timer_enter(stage_timer, "finalize")
        if completed_locked:
            detail = f"已完结（{last_episode}/{known_total}），未发现可更新资源"
            status = "completed"
        elif searched_sources <= 0:
            detail = "未启用任何 TG 订阅源，请先在参数配置里启用频道后重试"
            status = "waiting"
        elif supported_items <= 0:
            detail = "命中资源均非夸克分享链接，请调整频道或关键词"
            status = "waiting"
        elif int(search_stats.get("title_blocked_candidates", 0) or 0) > 0 and int(search_stats.get("scored_items", 0) or 0) <= 0:
            detail = (
                f"已拦截标题不匹配候选 {int(search_stats.get('title_blocked_candidates', 0) or 0)} 条，"
                "当前暂无可导入资源"
            )
            status = "waiting"
        else:
            detail = (
                f"主动搜索未命中（夸克阈值 {int(SUBSCRIPTION_QUARK_MIN_SCORE or 60)}，"
                f"候选 {int(search_stats.get('deduped_items', 0) or 0)} 条，"
                f"最高分 {int(search_stats.get('best_score', 0) or 0)}）"
            )
            status = "waiting"
        upsert_subscription_task_state(
            task_name,
            media_type=task.get("media_type", "movie"),
            status=status,
            progress=100,
            detail=detail,
            stats={
                "matched": False,
                "provider": "quark",
                "run_id": subscription_run_id,
                "batch_refresh_enabled": batch_refresh_enabled,
                "last_episode": last_episode,
                "total_episodes": known_total,
                **search_stats,
            },
        )
        await write_subscription_log(detail, "warn" if status == "waiting" else "info")
        update_subscription_summary("等待资源" if status == "waiting" else "已完成", detail)
        return

    base_savepath = normalize_relative_path(str(task.get("savepath", "")).strip())
    effective_savepath = base_savepath
    if task["media_type"] == "movie":
        movie_folder = sanitize_115_folder_name(
            f"{task.get('title', '')} {task.get('year', '')}".strip() or "未命名电影",
            fallback="未命名电影",
        )
        effective_savepath = join_relative_path(base_savepath, movie_folder)
    elif task["media_type"] == "tv":
        effective_savepath = resolve_subscription_tv_base_savepath(task, base_savepath) or base_savepath
    check_subscription_cancelled()

    _subscription_stage_timer_enter(stage_timer, "calibrate")
    upsert_subscription_task_state(task_name, status="running", progress=45, detail="正在准备夸克目标目录")
    cookie_quark = str(cfg.get("cookie_quark", "")).strip()
    folder_id = await asyncio.to_thread(
        ensure_quark_folder_id_by_path,
        cookie_quark,
        effective_savepath,
    )

    existing_folder_episodes: Set[int] = set()
    existing_episode_scan_stats: Dict[str, Any] = {}
    existing_episode_scan_ready = False
    if task["media_type"] == "tv":
        upsert_subscription_task_state(task_name, status="running", progress=47, detail="正在读取夸克目标目录已落盘剧集")
        try:
            scan_result = await asyncio.to_thread(
                _scan_quark_existing_tv_episodes,
                cookie_quark,
                folder_id,
                task,
            )
            scan_episodes = scan_result.get("episodes", []) if isinstance(scan_result.get("episodes"), list) else []
            existing_folder_episodes = _clamp_episode_values(
                {max(0, int(item or 0)) for item in scan_episodes if max(0, int(item or 0)) > 0},
                episode_upper_bound=single_season_episode_upper_bound,
            )
            existing_episode_scan_stats = {
                "existing_episode_scan_ready": True,
                "existing_episode_count": len(existing_folder_episodes),
                "existing_episode_max": max(existing_folder_episodes) if existing_folder_episodes else 0,
                "existing_episode_scanned_dirs": int(scan_result.get("scanned_dirs", 0) or 0),
                "existing_episode_scanned_entries": int(scan_result.get("scanned_entries", 0) or 0),
                "existing_episode_failed_dirs": int(scan_result.get("failed_dirs", 0) or 0),
                "existing_episode_scan_truncated": bool(scan_result.get("truncated", False)),
            }
            existing_episode_scan_ready = True
            if existing_folder_episodes:
                await write_subscription_log(
                    (
                        f"夸克目标目录已识别 {len(existing_folder_episodes)} 集（最高 E{max(existing_folder_episodes)}，"
                        f"样例 {_format_episode_preview(existing_folder_episodes)}）"
                    ),
                    "info",
                )
            else:
                await write_subscription_log(
                    (
                        f"夸克目标目录未识别到已落盘剧集（扫描目录 {int(scan_result.get('scanned_dirs', 0) or 0)} 个，"
                        f"条目 {int(scan_result.get('scanned_entries', 0) or 0)} 条）"
                    ),
                    "info",
                )
            if int(scan_result.get("failed_dirs", 0) or 0) > 0:
                await write_subscription_log(
                    f"夸克目录扫描有 {int(scan_result.get('failed_dirs', 0) or 0)} 个子目录读取失败，已自动忽略",
                    "warn",
                )
            if bool(scan_result.get("truncated", False)):
                await write_subscription_log("夸克目录扫描达到上限，已截断后续子目录（避免单次执行过慢）", "warn")
            corrected_last_episode = max(existing_folder_episodes) if existing_folder_episodes else last_episode
            if existing_folder_episodes:
                corrected_last_episode = max(existing_folder_episodes)
            elif int(existing_episode_scan_stats.get("existing_episode_scanned_entries", 0) or 0) <= 0:
                corrected_last_episode = 0
            if corrected_last_episode != last_episode:
                previous_last_episode = last_episode
                last_episode = corrected_last_episode
                completed_locked = task["media_type"] == "tv" and known_total > 0 and last_episode >= known_total
                upsert_subscription_task_state(
                    task_name,
                    media_type=task.get("media_type", "movie"),
                    last_episode=last_episode,
                    total_episodes=known_total,
                )
                await write_subscription_log(
                    f"已按夸克目标目录校准追更进度：E{previous_last_episode} -> E{last_episode}",
                    "info",
                )
        except Exception as exc:
            existing_episode_scan_stats = {"existing_episode_scan_ready": False}
            await write_subscription_log(f"读取夸克目标目录已落盘剧集失败，回退历史进度判断：{exc}", "warn")

    baseline_last_episode = last_episode
    attempt_candidates = ranked_candidates
    ranked_candidate_count = len(ranked_candidates)
    pre_title_hint_candidate_count = ranked_candidate_count
    title_hint_missing_targets: Set[int] = set()
    title_hint_filtered_candidates = 0
    if task["media_type"] == "tv" and existing_episode_scan_ready:
        attempt_candidates = _prioritize_tv_candidates_by_missing_episodes(
            ranked_candidates,
            existing_folder_episodes,
            last_episode,
            prefer_backfill=(str(trigger or "").strip().lower() == "manual"),
            episode_upper_bound=single_season_episode_upper_bound,
        )
        pre_title_hint_candidate_count = len(attempt_candidates)
    if task["media_type"] == "tv":
        attempt_candidates = _prioritize_quark_tv_candidates_for_precise_scan(
            attempt_candidates,
            existing_folder_episodes if existing_episode_scan_ready else set(),
            episode_upper_bound=single_season_episode_upper_bound,
        )
    if task["media_type"] == "tv" and existing_episode_scan_ready:
        title_hint_missing_targets = _compute_quark_tv_title_missing_targets(
            existing_folder_episodes,
            last_episode,
            episode_upper_bound=single_season_episode_upper_bound,
        )
        filtered_candidates, filtered_count = _filter_quark_tv_candidates_by_title_missing_episodes(
            attempt_candidates,
            title_hint_missing_targets,
            episode_upper_bound=single_season_episode_upper_bound,
        )
        attempt_candidates = filtered_candidates
        title_hint_filtered_candidates = filtered_count
        if filtered_count > 0:
            await write_subscription_log(
                (
                    f"已按标题集数缺失集初筛移除 {filtered_count} 条候选"
                    f"（缺失 {_format_episode_preview(title_hint_missing_targets)}）"
                ),
                "info",
            )

    attempt_budget = SUBSCRIPTION_QUARK_MAX_ATTEMPTS if task["media_type"] == "tv" else min(16, SUBSCRIPTION_QUARK_MAX_ATTEMPTS)
    max_attempts = max(1, min(attempt_budget, len(attempt_candidates)))
    if task["media_type"] == "tv":
        await write_subscription_log(
            (
                f"夸克候选统计：初始 {ranked_candidate_count} 条，优先级重排后 {pre_title_hint_candidate_count} 条，"
                f"标题缺失集初筛后 {len(attempt_candidates)} 条，本轮最多尝试 {max_attempts} 条"
            ),
            "info",
        )
    import_timeout_seconds = max(10, int(SUBSCRIPTION_IMPORT_TIMEOUT_SECONDS or 90))
    attempted_candidates = 0
    scanned_candidates = 0
    failed_attempts = 0
    timed_out_attempts = 0
    skipped_existing_candidates = 0
    skipped_episode_candidates = 0
    skipped_precise_mismatch_candidates = 0
    last_failed_detail = ""
    selected_candidate: Dict[str, Any] = {}
    selected_item: Dict[str, Any] = {}
    selected_job_id = 0
    selected_job_savepath = effective_savepath
    imported_episodes: Set[int] = set()
    successful_job_ids: List[int] = []
    max_total_detected = 0
    savepath_folder_id_cache: Dict[str, str] = {effective_savepath: str(folder_id or "").strip()}
    seen_candidate_share_keys: Set[str] = set()
    quark_manifest_cache: Dict[str, Dict[str, Any]] = {}

    def consume_background_task_result(task_obj: asyncio.Task) -> None:
        try:
            task_obj.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    _subscription_stage_timer_enter(stage_timer, "import")
    candidate_queue = list(attempt_candidates)
    queue_index = 0
    while queue_index < len(candidate_queue):
        if attempted_candidates >= max_attempts:
            break
        index = queue_index + 1
        candidate = candidate_queue[queue_index]
        queue_index += 1
        scanned_candidates += 1
        check_subscription_cancelled()
        item = candidate.get("item", {}) if isinstance(candidate.get("item"), dict) else {}
        resource_id = int(item.get("id", 0) or 0)
        if resource_id <= 0:
            continue

        score = int(candidate.get("score", 0) or 0)
        episode = max(0, int(candidate.get("episode", 0) or 0))
        total_detected = max(0, int(candidate.get("total", 0) or 0))
        candidate_season = max(0, int(candidate.get("season", 0) or 0))
        candidate_episode_values = _candidate_episode_values(
            candidate,
            episode_upper_bound=single_season_episode_upper_bound,
        )
        candidate_has_range_hint = (
            max(0, int(candidate.get("range_start", 0) or 0)) > 0
            and max(0, int(candidate.get("range_end", 0) or 0)) > 0
        )
        episode_label = _format_candidate_episode_label(candidate)
        candidate_link_url = _normalize_subscription_candidate_link(item.get("link_url", ""))
        candidate_link_type = resolve_resource_link_type(item.get("link_type", ""), candidate_link_url)
        if candidate_link_type != "quark":
            continue
        item_extra = item.get("extra") if isinstance(item.get("extra"), dict) else safe_json_loads(item.get("extra_json"), {})
        candidate_receive_code = normalize_receive_code(item.get("receive_code", "")) or normalize_receive_code(
            (item_extra or {}).get("receive_code", "")
        )
        candidate_share_key = _build_subscription_quark_share_dedupe_key(
            candidate_link_url,
            item.get("raw_text", ""),
            candidate_receive_code,
        )
        dedupe_key = candidate_share_key or f"url:{candidate_link_url.lower()}"
        if dedupe_key in seen_candidate_share_keys:
            continue
        seen_candidate_share_keys.add(dedupe_key)

        if (
            task["media_type"] == "tv"
            and single_season_episode_upper_bound > 0
            and episode > single_season_episode_upper_bound
            and not candidate_episode_values
        ):
            skipped_episode_candidates += 1
            await write_subscription_log(
                (
                    f"候选资源 #{index}（评分 {score}）集数 {episode_label} 超出单季总集数 "
                    f"E{single_season_episode_upper_bound}，已跳过"
                ),
                "warn",
            )
            continue

        if task["media_type"] == "tv" and candidate_episode_values and existing_episode_scan_ready and candidate_has_range_hint:
            if candidate_episode_values.issubset(existing_folder_episodes):
                skipped_existing_candidates += 1
                await write_subscription_log(
                    f"候选资源 #{index}（评分 {score}）集数 {episode_label} 夸克目录已全覆盖，已跳过",
                    "warn",
                )
                continue
            overlap_existing = any(episode_no in existing_folder_episodes for episode_no in candidate_episode_values)
            if overlap_existing:
                missing_for_candidate = _candidate_missing_episode_values(
                    candidate,
                    existing_folder_episodes,
                    episode_upper_bound=single_season_episode_upper_bound,
                )
                if missing_for_candidate:
                    await write_subscription_log(
                        (
                            f"候选资源 #{index} 与目录部分重叠（缺失 {_format_episode_preview(missing_for_candidate)}），"
                            "按夸克策略继续尝试导入"
                        ),
                        "info",
                    )

        candidate_savepath = effective_savepath
        if task["media_type"] == "tv":
            candidate_savepath = (
                build_subscription_tv_savepath(
                    task,
                    base_savepath,
                    season=candidate_season,
                    episode=episode,
                )
                or effective_savepath
            )

        selected_share_episode_values: Set[int] = set()
        selected_share_file_samples: List[str] = []
        precise_selection: Dict[str, Any] = {}
        if task["media_type"] == "tv":
            if (
                candidate_episode_values
                and last_episode > 0
                and max(candidate_episode_values) <= last_episode
                and (not existing_episode_scan_ready)
            ):
                skipped_existing_candidates += 1
                await write_subscription_log(
                    (
                        f"候选资源 #{index}（评分 {score}）集数 {episode_label} 不高于当前进度 E{last_episode}，"
                        "已跳过避免重复导入"
                    ),
                    "info",
                )
                continue

            precise_missing_episode_values = set(candidate_episode_values)
            if not precise_missing_episode_values and known_total > 0 and last_episode > 0:
                episode_upper = known_total
                if single_season_episode_upper_bound > 0:
                    episode_upper = min(episode_upper, single_season_episode_upper_bound)
                if episode_upper > last_episode:
                    precise_missing_episode_values = set(range(last_episode + 1, episode_upper + 1))

            if existing_episode_scan_ready and precise_missing_episode_values:
                precise_missing_episode_values = {
                    episode_no
                    for episode_no in precise_missing_episode_values
                    if episode_no not in existing_folder_episodes
                }

            if candidate_episode_values and not precise_missing_episode_values:
                skipped_existing_candidates += 1
                await write_subscription_log(
                    (
                        f"候选资源 #{index}（评分 {score}）集数 {episode_label} 与已落盘记录无缺失，"
                        "已跳过避免重复导入"
                    ),
                    "info",
                )
                continue

            if precise_missing_episode_values:
                precise_selection, precise_stats = await _build_tv_share_selection_for_missing_episodes(
                    cookie_quark,
                    task,
                    item,
                    precise_missing_episode_values,
                )
                precise_ids = (
                    precise_selection.get("selected_ids", [])
                    if isinstance(precise_selection.get("selected_ids"), list)
                    else []
                )
                fallback_used = False
                fallback_missing_episode_values: Set[int] = set()
                if not precise_ids:
                    reason = str((precise_stats or {}).get("reason", "") or "no_precise_episode_match").strip()
                    scanned_dirs = int((precise_stats or {}).get("scanned_dirs", 0) or 0)
                    scanned_entries = int((precise_stats or {}).get("scanned_entries", 0) or 0)
                    if reason == "no_precise_episode_match":
                        manifest_cache_key = candidate_share_key or candidate_link_url or f"resource:{resource_id}"
                        manifest_payload = quark_manifest_cache.get(manifest_cache_key)
                        if not manifest_payload:
                            manifest_payload = await _scan_subscription_share_tree_snapshot(
                                cookie_quark,
                                task,
                                item,
                                max_depth=5,
                                max_dirs=140,
                                max_entries=5000,
                                per_request_timeout=max(12, int(SUBSCRIPTION_SHARE_SCAN_REQUEST_TIMEOUT_SECONDS or 12)),
                                force_refresh=False,
                            )
                            quark_manifest_cache[manifest_cache_key] = manifest_payload
                        scanned_dirs = max(scanned_dirs, int((manifest_payload or {}).get("scanned_dirs", 0) or 0))
                        scanned_entries = max(scanned_entries, int((manifest_payload or {}).get("scanned_entries", 0) or 0))
                        manifest_episodes = _clamp_episode_values(
                            {
                                max(0, int(value or 0))
                                for value in (
                                    manifest_payload.get("covered_episodes", [])
                                    if isinstance(manifest_payload.get("covered_episodes"), list)
                                    else []
                                )
                                if max(0, int(value or 0)) > 0
                            },
                            episode_upper_bound=single_season_episode_upper_bound,
                        )
                        fallback_missing_episode_values = {
                            episode_no
                            for episode_no in manifest_episodes
                            if episode_no not in existing_folder_episodes
                        }
                        if fallback_missing_episode_values:
                            fallback_selection, fallback_stats = _build_tv_share_selection_from_manifest(
                                manifest_payload,
                                fallback_missing_episode_values,
                                task=task,
                            )
                            fallback_ids = (
                                fallback_selection.get("selected_ids", [])
                                if isinstance(fallback_selection.get("selected_ids"), list)
                                else []
                            )
                            if fallback_ids:
                                precise_selection = fallback_selection
                                precise_stats = fallback_stats
                                precise_ids = fallback_ids
                                fallback_used = True
                                reason = str((fallback_stats or {}).get("reason", "") or "manifest_fallback").strip()
                            else:
                                fallback_reason = str(
                                    (fallback_stats or {}).get("reason", "") or "manifest_no_precise_episode_match"
                                ).strip()
                                reason = f"{reason}->{fallback_reason}"
                        elif manifest_episodes:
                            reason = f"{reason}->manifest_no_missing"
                        else:
                            manifest_reason = str((manifest_payload or {}).get("reason", "") or "manifest_empty").strip()
                            reason = f"{reason}->{manifest_reason}"
                if not precise_ids:
                    skipped_precise_mismatch_candidates += 1
                    reason_label = _format_subscription_reason_chain(reason)
                    await write_subscription_log(
                        (
                            f"候选资源 #{index} 精细筛选未命中缺失集（目标 {_format_episode_preview(precise_missing_episode_values)}，"
                            f"原因 {reason_label}，扫描目录 {scanned_dirs} 个，条目 {scanned_entries} 条），已跳过整包导入"
                        ),
                        "warn",
                    )
                    continue
                selected_share_episode_values = {
                    max(0, int(value or 0))
                    for value in (
                        precise_stats.get("covered_episodes", [])
                        if isinstance(precise_stats, dict)
                    else []
                    )
                    if max(0, int(value or 0)) > 0
                }
                selected_share_file_samples = (
                    [str(sample or "").strip() for sample in (precise_stats.get("selected_file_samples", []) if isinstance(precise_stats, dict) else [])]
                )
                selected_share_file_samples = [sample for sample in selected_share_file_samples if sample]
                dedupe_hits = int((precise_stats or {}).get("duplicate_bucket_hits", 0) or 0)
                dedupe_tail = f"，同集/同范围已优选 {dedupe_hits} 条重复版本" if dedupe_hits > 0 else ""
                if fallback_used:
                    await write_subscription_log(
                        (
                            f"候选资源 #{index} 原目标 {_format_episode_preview(precise_missing_episode_values)} 未命中，"
                            f"已按清单回退识别 {_format_episode_preview(fallback_missing_episode_values)} 并筛选 "
                            f"{len(precise_ids)} 个文件后转存{dedupe_tail}"
                        ),
                        "info",
                    )
                else:
                    await write_subscription_log(
                        (
                            f"候选资源 #{index} 已按缺失集筛选 {len(precise_ids)} 个文件后转存"
                            f"（目标 {_format_episode_preview(precise_missing_episode_values)}）{dedupe_tail}"
                        ),
                        "info",
                    )

        attempted_candidates += 1
        candidate_folder_id = str(savepath_folder_id_cache.get(candidate_savepath, "") or "").strip()
        if not candidate_folder_id:
            candidate_folder_id = await asyncio.to_thread(
                ensure_quark_folder_id_by_path,
                cookie_quark,
                candidate_savepath,
            )
            savepath_folder_id_cache[candidate_savepath] = str(candidate_folder_id or "").strip()

        job_payload = {
            "folder_id": candidate_folder_id,
            "savepath": candidate_savepath,
            "sharetitle": "",
            "monitor_task_name": "",
            "refresh_delay_seconds": 0,
            "auto_refresh": False,
            "extra": {
                "job_source": "subscription_auto",
            },
        }
        if precise_selection:
            job_payload["share_selection"] = precise_selection

        job_id = create_resource_job(item, job_payload)
        if job_id <= 0:
            failed_attempts += 1
            last_failed_detail = "创建导入任务失败"
            await write_subscription_log(
                f"候选资源 #{index} 导入失败：{last_failed_detail}",
                "warn",
            )
            continue

        await write_subscription_log(
            (
                f"候选资源 #{index}（{episode_label}）已创建夸克导入任务 #{job_id}，开始执行："
                f"{str(item.get('title', '') or f'资源#{resource_id}').strip()[:96]}"
            ),
            "info",
        )

        job_runner = asyncio.create_task(run_resource_job(job_id))
        done, _ = await asyncio.wait({job_runner}, timeout=import_timeout_seconds)
        if not done:
            job_runner.add_done_callback(consume_background_task_result)
            job_runner.cancel()
            timed_out_attempts += 1
            timeout_detail = f"执行超时（>{import_timeout_seconds} 秒）"
            try:
                await cancel_resource_job(job_id, reason="timeout")
            except Exception:
                update_resource_job(
                    job_id,
                    status="failed",
                    status_detail=timeout_detail,
                    finished_at=now_text(),
                )
                if resource_id > 0:
                    conn = open_db()
                    update_resource_item_status(conn, resource_id, "failed")
                    conn.commit()
                    conn.close()
            failed_attempts += 1
            last_failed_detail = timeout_detail
            await write_subscription_log(
                f"候选资源 #{index} 导入超时：{timeout_detail}",
                "warn",
            )
            continue

        await job_runner
        latest_job = get_resource_job(job_id, include_private=True)
        latest_status = str((latest_job or {}).get("status", "") or "").strip().lower()
        if latest_status == "failed":
            failed_attempts += 1
            last_failed_detail = str((latest_job or {}).get("status_detail", "") or "资源导入失败").strip()
            if candidate_link_url and _is_subscription_invalid_link_error(last_failed_detail, candidate_link_type):
                _record_subscription_invalid_link_cache(
                    candidate_link_url,
                    candidate_link_type,
                    last_failed_detail,
                )
            await write_subscription_log(
                f"候选资源 #{index} 导入失败：{last_failed_detail}",
                "warn",
            )
            continue

        if task["media_type"] == "tv":
            try:
                verify_scan_result = await asyncio.to_thread(
                    _scan_quark_existing_tv_episodes,
                    cookie_quark,
                    candidate_folder_id,
                    task,
                )
                verify_scan_episodes = _clamp_episode_values(
                    {
                        max(0, int(value or 0))
                        for value in (
                            verify_scan_result.get("episodes", [])
                            if isinstance(verify_scan_result.get("episodes"), list)
                            else []
                        )
                        if max(0, int(value or 0)) > 0
                    },
                    episode_upper_bound=single_season_episode_upper_bound,
                )
                if verify_scan_episodes:
                    existing_folder_episodes.update(verify_scan_episodes)
                    existing_episode_scan_stats["existing_episode_scan_ready"] = True
                    existing_episode_scan_stats["existing_episode_count"] = len(existing_folder_episodes)
                    existing_episode_scan_stats["existing_episode_max"] = (
                        max(existing_folder_episodes) if existing_folder_episodes else 0
                    )
                    existing_episode_scan_stats["existing_episode_scanned_dirs"] = int(
                        verify_scan_result.get("scanned_dirs", 0) or 0
                    )
                    existing_episode_scan_stats["existing_episode_scanned_entries"] = int(
                        verify_scan_result.get("scanned_entries", 0) or 0
                    )
                    existing_episode_scan_stats["existing_episode_failed_dirs"] = int(
                        verify_scan_result.get("failed_dirs", 0) or 0
                    )
                    existing_episode_scan_stats["existing_episode_scan_truncated"] = bool(
                        verify_scan_result.get("truncated", False)
                    )
                    if selected_share_episode_values:
                        verified_hits = _clamp_episode_values(
                            selected_share_episode_values.intersection(verify_scan_episodes),
                            episode_upper_bound=single_season_episode_upper_bound,
                        )
                        if verified_hits:
                            await write_subscription_log(
                                f"候选资源 #{index} 转存后目录复核命中 {_format_episode_preview(verified_hits)}",
                                "info",
                            )
            except Exception as exc:
                await write_subscription_log(
                    f"候选资源 #{index} 转存后目录复核失败（已忽略，不影响本次任务）：{exc}",
                    "warn",
                )

        create_subscription_match(
            task_name=task_name,
            resource_id=resource_id,
            job_id=job_id,
            media_type=task.get("media_type", "movie"),
            season=candidate_season if candidate_season > 0 else max(1, int(task.get("season", 1) or 1)),
            episode=episode,
            total_episodes=total_detected,
            score=score,
        )
        successful_job_ids.append(job_id)
        if not selected_candidate:
            selected_candidate = candidate
            selected_item = item
            selected_job_id = job_id
            selected_job_savepath = candidate_savepath
        else:
            selected_episode = max(0, int(selected_candidate.get("episode", 0) or 0))
            selected_score = int(selected_candidate.get("score", 0) or 0)
            if episode > selected_episode or (episode == selected_episode and score > selected_score):
                selected_candidate = candidate
                selected_item = item
                selected_job_id = job_id
                selected_job_savepath = candidate_savepath
        max_total_detected = max(max_total_detected, total_detected)
        recorded_episode_values = _resolve_recorded_episode_values(
            candidate,
            selected_share_episode_values,
            episode_upper_bound=single_season_episode_upper_bound,
        )
        if recorded_episode_values:
            imported_episodes.update(recorded_episode_values)
            if existing_episode_scan_ready:
                existing_folder_episodes.update(recorded_episode_values)
                existing_episode_scan_stats["existing_episode_count"] = len(existing_folder_episodes)
                existing_episode_scan_stats["existing_episode_max"] = (
                    max(existing_folder_episodes) if existing_folder_episodes else 0
                )
        await write_subscription_log(
            (
                f"候选资源 #{index} 导入成功：{str(item.get('title', '') or f'资源#{resource_id}').strip()}"
                f"（评分 {score}）"
                f"{'，命中 ' + _format_episode_preview(recorded_episode_values) if recorded_episode_values else ''}"
                f"{'，文件：' + '；'.join(selected_share_file_samples[:8]) if selected_share_file_samples else ''}"
            ),
            "success",
        )
        if task["media_type"] == "tv" and existing_episode_scan_ready:
            remaining_candidates = candidate_queue[queue_index:]
            refreshed_missing_targets = _compute_quark_tv_title_missing_targets(
                existing_folder_episodes,
                last_episode,
                episode_upper_bound=single_season_episode_upper_bound,
            )
            filtered_remaining, filtered_remaining_count = _filter_quark_tv_candidates_by_title_missing_episodes(
                remaining_candidates,
                refreshed_missing_targets,
                episode_upper_bound=single_season_episode_upper_bound,
            )
            remaining_candidates = filtered_remaining
            if filtered_remaining_count > 0:
                candidate_queue = candidate_queue[:queue_index] + remaining_candidates
                await write_subscription_log(
                    (
                        f"候选资源 #{index} 转存后按缺失集继续收敛：移除 {filtered_remaining_count} 条标题不含缺失集候选"
                        f"（剩余缺失 {_format_episode_preview(refreshed_missing_targets)}）"
                    ),
                    "info",
                )
            pruned_remaining, pruned_count = _prune_tv_candidates_without_new_episodes(
                remaining_candidates,
                existing_folder_episodes,
                episode_upper_bound=single_season_episode_upper_bound,
            )
            if pruned_count > 0:
                candidate_queue = candidate_queue[:queue_index] + pruned_remaining
                await write_subscription_log(
                    f"候选资源 #{index} 转存后已移除 {pruned_count} 条无新增集数候选，减少后续精细扫描开销",
                    "info",
                )
            prioritized_remaining = _prioritize_quark_tv_candidates_for_precise_scan(
                candidate_queue[queue_index:],
                existing_folder_episodes,
                episode_upper_bound=single_season_episode_upper_bound,
            )
            candidate_queue = candidate_queue[:queue_index] + prioritized_remaining
        if (
            task["media_type"] == "tv"
            and single_season_episode_upper_bound > 0
            and existing_episode_scan_ready
        ):
            target_episodes = set(range(1, single_season_episode_upper_bound + 1))
            if target_episodes.issubset(existing_folder_episodes):
                await write_subscription_log(
                    f"夸克目录已覆盖单季全部 E1-E{single_season_episode_upper_bound}，结束本轮候选尝试",
                    "info",
                )
                break
        if task["media_type"] != "tv":
            break

    _subscription_stage_timer_enter(stage_timer, "finalize")
    if not selected_candidate:
        if attempted_candidates <= 0:
            skip_reasons: List[str] = []
            if skipped_existing_candidates > 0:
                skip_reasons.append(f"目录已覆盖 {skipped_existing_candidates} 条")
            if skipped_episode_candidates > 0:
                skip_reasons.append(f"超范围旧集 {skipped_episode_candidates} 条")
            if skipped_precise_mismatch_candidates > 0:
                skip_reasons.append(f"精细识别未命中 {skipped_precise_mismatch_candidates} 条")
            if skip_reasons:
                detail = f"候选资源暂不可导入（{'，'.join(skip_reasons)}），等待新集发布"
            else:
                detail = "候选资源暂不可用，等待下次自动重试"
        elif failed_attempts > 0:
            detail = f"已尝试 {attempted_candidates} 个候选资源均失败，等待下次自动重试"
            if last_failed_detail:
                detail += f"（最近失败：{last_failed_detail[:80]}）"
            if timed_out_attempts > 0:
                detail += f"（超时 {timed_out_attempts} 条）"
        else:
            detail = "候选资源暂不可用，等待下次自动重试"
        if skipped_precise_mismatch_candidates > 0 and attempted_candidates > 0:
            detail += f"（精细识别未命中 {skipped_precise_mismatch_candidates} 条）"
        upsert_subscription_task_state(
            task_name,
            media_type=task.get("media_type", "movie"),
            status="waiting",
            progress=100,
            detail=detail,
            stats={
                "matched": False,
                "provider": "quark",
                "run_id": subscription_run_id,
                "batch_refresh_enabled": batch_refresh_enabled,
                "last_episode": last_episode,
                "total_episodes": known_total,
                "attempted_candidates": attempted_candidates,
                "failed_attempts": failed_attempts,
                "timed_out_attempts": timed_out_attempts,
                "skipped_existing_candidates": skipped_existing_candidates,
                "skipped_episode_candidates": skipped_episode_candidates,
                "skipped_precise_mismatch_candidates": skipped_precise_mismatch_candidates,
                "title_hint_filtered_candidates": title_hint_filtered_candidates,
                "title_hint_missing_targets": sorted(title_hint_missing_targets)[:120],
                "scanned_candidates": scanned_candidates,
                "max_attempts": max_attempts,
                **existing_episode_scan_stats,
                **search_stats,
            },
        )
        await write_subscription_log(detail, "warn")
        update_subscription_summary("等待资源", detail)
        return

    candidate = selected_candidate
    item = selected_item
    resource_id = int(item.get("id", 0) or 0)
    score = int(candidate.get("score", 0) or 0)
    episode = max(0, int(candidate.get("episode", 0) or 0))
    total_detected = max(0, int(candidate.get("total", 0) or 0))
    selected_season = max(0, int(candidate.get("season", 0) or 0))
    job_id = int(selected_job_id or 0)
    normalized_successful_job_ids = sorted({max(0, int(value or 0)) for value in successful_job_ids if max(0, int(value or 0)) > 0})
    if job_id <= 0 and normalized_successful_job_ids:
        job_id = normalized_successful_job_ids[0]
    successful_count = len(normalized_successful_job_ids) if normalized_successful_job_ids else (1 if job_id > 0 else 0)
    imported_episode_list = sorted(imported_episodes)
    matched_display_title = pick_subscription_display_title(task, item, fallback=f"资源#{resource_id}")

    next_episode = last_episode
    if task["media_type"] == "tv" and imported_episode_list:
        next_episode = max(last_episode, imported_episode_list[-1])
    elif task["media_type"] == "tv" and episode > 0:
        next_episode = max(last_episode, episode)
    next_total = known_total or max_total_detected or total_detected
    if task["media_type"] == "tv" and (max_total_detected > 0 or total_detected > 0):
        _sync_task_total_episodes(task_name, max_total_detected or total_detected)

    if successful_count > 1:
        detail = (
            f"命中「{matched_display_title}」（评分 {score}），本轮已执行 {successful_count} 个夸克导入任务"
            f"（首个 #{job_id}），保存到 {selected_job_savepath}；夸克链路不触发监控刷新"
        )
    else:
        detail = (
            f"命中「{matched_display_title}」（评分 {score}），已创建并执行夸克导入任务 #{job_id}，"
            f"保存到 {selected_job_savepath}；夸克链路不触发监控刷新"
        )
    upsert_subscription_task_state(
        task_name,
        media_type=task.get("media_type", "movie"),
        status="completed",
        progress=100,
        detail=detail,
        last_success_at=now_text(),
        last_error="",
        last_episode=next_episode,
        total_episodes=next_total,
        matched_resource_id=resource_id,
        matched_resource_title=matched_display_title,
        matched_score=score,
        queued_job_id=job_id,
        stats={
            "matched": True,
            "provider": "quark",
            "run_id": subscription_run_id,
            "batch_refresh_enabled": batch_refresh_enabled,
            "score": score,
            "token_hits": int(candidate.get("token_hits", 0) or 0),
            "token_total": int(candidate.get("token_total", 0) or 0),
            "episode": episode,
            "season": selected_season,
            "total_episodes": next_total,
            "job_id": job_id,
            "job_ids": normalized_successful_job_ids or ([job_id] if job_id > 0 else []),
            "auto_refresh": False,
            "matched_count": max(1, successful_count),
            "imported_episode_count": len(imported_episode_list),
            "imported_episodes": imported_episode_list[:80],
            "attempted_candidates": attempted_candidates,
            "failed_attempts": failed_attempts,
            "timed_out_attempts": timed_out_attempts,
            "skipped_existing_candidates": skipped_existing_candidates,
            "skipped_episode_candidates": skipped_episode_candidates,
            "title_hint_filtered_candidates": title_hint_filtered_candidates,
            "title_hint_missing_targets": sorted(title_hint_missing_targets)[:120],
            "scanned_candidates": scanned_candidates,
            "max_attempts": max_attempts,
            **existing_episode_scan_stats,
            **search_stats,
        },
    )
    await write_subscription_log(detail, "success")
    try:
        notify_result = await push_subscription_success_notification(
            cfg=cfg,
            task=task,
            item=item,
            effective_savepath=selected_job_savepath,
            job_id=job_id,
            successful_count=max(1, successful_count),
            imported_episode_list=imported_episode_list,
            baseline_last_episode=baseline_last_episode,
            next_episode=next_episode,
        )
        if bool(notify_result.get("pushed", False)):
            channel = str(notify_result.get("channel", "") or "").strip().lower()
            channel_label = "企业微信应用 API" if channel == "wecom_app" else "企业微信群机器人"
            notified_episodes = (
                notify_result.get("episodes", [])
                if isinstance(notify_result.get("episodes"), list)
                else []
            )
            if notified_episodes:
                await write_subscription_log(
                    f"更新通知已推送到{channel_label}（新增 {len(notified_episodes)} 集）",
                    "info",
                )
            else:
                await write_subscription_log(f"更新通知已推送到{channel_label}", "info")
    except Exception as notify_exc:
        await write_subscription_log(f"订阅成功通知推送失败：{notify_exc}", "warn")
    update_subscription_summary("执行成功", detail)

async def run_subscription_task(task_name: str, trigger: str = "manual") -> None:
    cfg = get_config()
    task = _load_subscription_task(cfg, task_name)
    if not task:
        await write_subscription_log(f"任务不存在: {task_name}", "error")
        return
    config_error = validate_subscription_runtime_config(cfg, task)
    if config_error:
        await write_subscription_log(f"任务配置错误: {config_error}", "error")
        upsert_subscription_task_state(task_name, status="failed", detail=config_error, last_error=config_error)
        update_subscription_summary("任务失败", config_error)
        return
    provider = normalize_subscription_provider(task.get("provider", "115"), fallback="115")
    subscription_run_id = _build_subscription_run_id(task_name)
    # 批次收口刷新改为固定内置策略，不再由设置项切换。
    batch_refresh_enabled = provider == "115"

    if subscription_status["running"]:
        return

    ensure_db()
    recovered_jobs = {
        "checked": 0,
        "stale": 0,
        "recovered": 0,
        "triggered_groups": 0,
        "triggered_jobs": 0,
        "skipped_no_monitor": 0,
        "skipped_missing_monitor": 0,
    }
    if batch_refresh_enabled:
        recovered_jobs = _recover_subscription_submitted_jobs(limit=160)
        if int(recovered_jobs.get("recovered", 0) or 0) > 0:
            await write_subscription_log(
                (
                    f"已自动收口历史待刷新任务 {int(recovered_jobs.get('recovered', 0) or 0)} 条："
                    f"触发监控 {int(recovered_jobs.get('triggered_groups', 0) or 0)} 组 / "
                    f"跳过（未纳入监控）{int(recovered_jobs.get('skipped_no_monitor', 0) or 0)} 条 / "
                    f"跳过（监控任务不存在）{int(recovered_jobs.get('skipped_missing_monitor', 0) or 0)} 条"
                ),
                "info",
            )
    subscription_status["running"] = True
    subscription_status["current_task"] = task_name
    subscription_control["cancel"] = False
    subscription_last_run[task_name] = time.time()
    update_subscription_summary("准备执行", f"{task_name} ({trigger})")
    schedule_ui_state_push(0)
    run_started_at = now_text()
    upsert_subscription_task_state(
        task_name,
        media_type=task.get("media_type", "movie"),
        status="running",
        progress=5,
        detail=f"开始执行（{format_subscription_trigger(trigger)}）",
        last_run_at=run_started_at,
        last_error="",
        stats={
            "run_id": subscription_run_id,
            "batch_refresh_enabled": batch_refresh_enabled,
        },
    )
    share_runtime_cache_token = _subscription_share_entry_runtime_cache_var.set({})
    share_refreshed_keys_token = _subscription_share_entry_refreshed_keys_var.set(set())
    subscription_log_context_token = set_subscription_log_context(
        {
            "run_id": subscription_run_id,
            "task_name": task_name,
            "provider": provider,
            "media_type": str(task.get("media_type", "movie") or "movie"),
            "trigger": str(trigger or "").strip().lower() or "manual",
        }
    )
    stage_timer = _create_subscription_stage_timer("prepare")

    try:
        await write_subscription_log(
            f"━━━━━━━━━━【订阅开始 | {task_name} | {format_subscription_trigger(trigger)}】━━━━━━━━━━",
            "task-divider",
        )
        await write_subscription_log(
            f"类型: {'电影' if task['media_type'] == 'movie' else '电视剧'} | 标题: {task['title']} | 保存路径: {task['savepath']}",
            "info",
        )
        if provider == "quark":
            await _run_subscription_task_quark(
                cfg=cfg,
                task=task,
                task_name=task_name,
                trigger=trigger,
                subscription_run_id=subscription_run_id,
                batch_refresh_enabled=batch_refresh_enabled,
                stage_timer=stage_timer,
            )
            return
        await write_subscription_log(
            f"网盘提供方：115（频道搜索与导入链路） | 类型: {'电影' if task['media_type'] == 'movie' else '电视剧'}",
            "info",
        )
        task_share_subdir = normalize_relative_path(str(task.get("share_subdir", "") or "").strip())
        task_share_subdir_cid = _normalize_subscription_share_subdir_cid(task.get("share_subdir_cid", ""))
        task_share_link_url = str(task.get("share_link_url", "") or "").strip()
        task_share_link_receive_code = normalize_receive_code(task.get("share_link_receive_code", ""))
        task_share_link_type = resolve_resource_link_type("", task_share_link_url)
        use_fixed_share_link = bool(task_share_link_url) and task_share_link_type == "115share"
        fixed_link_channel_search_enabled = use_fixed_share_link and bool(task.get("fixed_link_channel_search", False))
        if task_share_subdir_cid and (not use_fixed_share_link):
            # CID 仅对固定分享链接稳定有效，频道搜索模式下忽略。
            task_share_subdir_cid = ""
        task_share_scope_enabled = bool(task_share_subdir or task_share_subdir_cid)
        task_share_scope_label = _format_subscription_share_scope_label(task_share_subdir, task_share_subdir_cid)
        if task_share_link_url and (not use_fixed_share_link):
            await write_subscription_log(
                "固定链接已配置但不是 115 分享链接，已自动忽略并回退频道搜索",
                "warn",
            )
        if use_fixed_share_link:
            await write_subscription_log(
                "固定链接模式已启用：将直接使用配置的 115 分享链接，不再依赖频道搜索",
                "info",
            )
            if fixed_link_channel_search_enabled:
                await write_subscription_log(
                    "固定链接补搜已启用：固定链接候选后会再执行一次频道搜索作为兜底",
                    "info",
                )
        if task_share_scope_enabled:
            await write_subscription_log(
                f"115 分享子目录已启用：{task_share_scope_label}（仅在该目录内扫描和转存）",
                "info",
            )
        await write_subscription_log(
            f"执行批次: {subscription_run_id} | 批次收口刷新: 开启（内置固定）",
            "info",
        )
        if int(task.get("tmdb_id", 0) or 0) > 0:
            tmdb_label = str(task.get("tmdb_title", "") or task.get("title", "") or "--").strip()
            tmdb_year = normalize_tmdb_year(task.get("tmdb_year", ""))
            tmdb_tail = f" ({tmdb_year})" if tmdb_year else ""
            await write_subscription_log(
                f"TMDB 绑定: {tmdb_label}{tmdb_tail} | ID: {int(task.get('tmdb_id', 0) or 0)}",
                "info",
            )
        if task["media_type"] == "tv":
            configured_total = resolve_subscription_tv_total_episodes(task, state_total=0)
            tv_mode_text = "多季合一" if is_subscription_multi_season_mode(task) else "单季订阅"
            if is_subscription_anime_compatible_task(task):
                tv_mode_text += " / 动漫兼容"
            season_label = "全季" if is_subscription_multi_season_mode(task) else f"S{int(task.get('season', 1) or 1):02d}"
            await write_subscription_log(
                f"季: {season_label} | 总集数: {configured_total or '自动识别'} | 模式: {tv_mode_text}",
                "info",
            )
        check_subscription_cancelled()

        state = load_subscription_task_state(task_name, task.get("media_type", "movie"))
        last_episode = max(0, int(state.get("last_episode", 0) or 0))
        state_stats = state.get("stats", {}) if isinstance(state.get("stats"), dict) else {}
        if task["media_type"] == "tv" and bool(state_stats.get("existing_episode_scan_ready", False)):
            state_existing_max = max(0, int(state_stats.get("existing_episode_max", 0) or 0))
            state_existing_entries = max(0, int(state_stats.get("existing_episode_scanned_entries", 0) or 0))
            if state_existing_max > 0:
                last_episode = state_existing_max
            elif last_episode > 0 and state_existing_entries <= 0:
                last_episode = 0
        known_total = resolve_subscription_tv_total_episodes(
            task,
            state_total=max(0, int(state.get("total_episodes", 0) or 0)),
        )
        single_season_episode_upper_bound = (
            known_total
            if task["media_type"] == "tv" and known_total > 0 and (not is_subscription_multi_season_mode(task))
            else 0
        )
        if single_season_episode_upper_bound > 0 and last_episode > single_season_episode_upper_bound:
            last_episode = single_season_episode_upper_bound

        completed_locked = task["media_type"] == "tv" and known_total > 0 and last_episode >= known_total

        if completed_locked:
            await write_subscription_log(
                f"当前记录为已完结（{last_episode}/{known_total}），本次仍会检查启用频道是否有重发/更优资源",
                "warn",
            )

        upsert_subscription_task_state(
            task_name,
            status="running",
            progress=15,
            detail=(
                "正在校验固定分享链接并准备频道补搜"
                if (use_fixed_share_link and fixed_link_channel_search_enabled)
                else ("正在校验固定分享链接" if use_fixed_share_link else "正在主动搜索启用频道资源")
            ),
        )
        check_subscription_cancelled()
        _subscription_stage_timer_enter(stage_timer, "search")
        search_started_at = time.perf_counter()
        search_result: Dict[str, Any] = {}
        if use_fixed_share_link:
            fixed_link_url = apply_share_receive_code_to_url(task_share_link_url, task_share_link_receive_code)
            fixed_item = {
                "id": 0,
                "title": str(task.get("title", "") or task_name or "固定分享链接").strip() or "固定分享链接",
                "link_url": fixed_link_url,
                "link_type": "115share",
                "message_url": "",
                "source_post_id": "",
                "raw_text": fixed_link_url,
                "receive_code": task_share_link_receive_code,
                "extra": {
                    "receive_code": task_share_link_receive_code,
                },
            }
            fixed_candidate = {
                "item": fixed_item,
                "score": 100,
                "episode": 0,
                "season": 0,
                "total": 0,
                "range_start": 0,
                "range_end": 0,
                "resolution": 0,
                "token_hits": 0,
            }
            search_result = {
                "candidate": fixed_candidate,
                "candidates": [fixed_candidate],
                "keywords": ["fixed-share-link"],
                "errors": [],
                "stats": {
                    "search_keywords": 0,
                    "searched_sources": 0,
                    "matched_channels": 0,
                    "pages_scanned": 0,
                    "raw_items": 0,
                    "deduped_items": 1,
                    "persisted_items": 0,
                    "supported_items": 1,
                    "unsupported_items": 0,
                    "media_guard_filtered": 0,
                    "media_guard_reasons": {},
                    "season_guard_filtered": 0,
                    "target_season": 0,
                    "scored_items": 1,
                    "scored_candidates": 1,
                    "relaxed_score_mode": False,
                    "relaxed_candidates": 0,
                    "search_errors": 0,
                    "best_score": 100,
                },
            }
            if fixed_link_channel_search_enabled:
                await write_subscription_log(
                    "固定链接候选已生成，正在执行频道补搜",
                    "info",
                )
                channel_search_result = await find_subscription_task_match_candidate_by_search(
                    task,
                    last_episode=last_episode,
                    trigger=trigger,
                )
                search_result = merge_subscription_search_results(search_result, channel_search_result)
        else:
            search_result = await find_subscription_task_match_candidate_by_search(
                task,
                last_episode=last_episode,
                trigger=trigger,
            )
        search_duration_seconds = max(0.0, time.perf_counter() - search_started_at)
        search_stats = search_result.get("stats", {}) if isinstance(search_result.get("stats"), dict) else {}
        search_errors = search_result.get("errors", []) if isinstance(search_result.get("errors"), list) else []
        search_keywords = search_result.get("keywords", []) if isinstance(search_result.get("keywords"), list) else []
        if use_fixed_share_link:
            await write_subscription_log(
                f"固定链接候选已就绪：{task_share_link_url}",
                "info",
            )
            if task_share_link_receive_code:
                await write_subscription_log("固定链接提取码已生效", "info")
        if (not use_fixed_share_link) or fixed_link_channel_search_enabled:
            search_label = "频道补搜" if (use_fixed_share_link and fixed_link_channel_search_enabled) else "主动搜索"
            searched_sources = int(
                (
                    search_stats.get("channel_searched_sources", search_stats.get("searched_sources", 0))
                    if (use_fixed_share_link and fixed_link_channel_search_enabled)
                    else search_stats.get("searched_sources", 0)
                )
                or 0
            )
            matched_channels = int(
                (
                    search_stats.get("channel_matched_channels", search_stats.get("matched_channels", 0))
                    if (use_fixed_share_link and fixed_link_channel_search_enabled)
                    else search_stats.get("matched_channels", 0)
                )
                or 0
            )
            pages_scanned = int(
                (
                    search_stats.get("channel_pages_scanned", search_stats.get("pages_scanned", 0))
                    if (use_fixed_share_link and fixed_link_channel_search_enabled)
                    else search_stats.get("pages_scanned", 0)
                )
                or 0
            )
            deduped_items = int(
                (
                    search_stats.get("channel_deduped_items", search_stats.get("deduped_items", 0))
                    if (use_fixed_share_link and fixed_link_channel_search_enabled)
                    else search_stats.get("deduped_items", 0)
                )
                or 0
            )
            supported_items = int(
                (
                    search_stats.get("channel_supported_items", search_stats.get("supported_items", 0))
                    if (use_fixed_share_link and fixed_link_channel_search_enabled)
                    else search_stats.get("supported_items", 0)
                )
                or 0
            )
            unsupported_items = int(
                (
                    search_stats.get("channel_unsupported_items", search_stats.get("unsupported_items", 0))
                    if (use_fixed_share_link and fixed_link_channel_search_enabled)
                    else search_stats.get("unsupported_items", 0)
                )
                or 0
            )
            await write_subscription_log(
                f"{search_label}关键词: " + " / ".join(search_keywords or [str(task.get("title", "")).strip() or "--"]),
                "info",
            )
            await write_subscription_log(
                (
                    f"{search_label}完成：频道检索 {searched_sources} 次，"
                    f"命中频道 {matched_channels} 个，"
                    f"扫描页面 {pages_scanned} 页，"
                    f"候选资源 {deduped_items} 条，"
                    f"可导入资源 {supported_items} 条"
                ),
                "info",
            )
            await write_subscription_log(
                f"{search_label}阶段耗时：{_format_elapsed_seconds(search_duration_seconds)}",
                "info",
            )
            if unsupported_items > 0:
                await write_subscription_log(
                    f"已过滤 {unsupported_items} 条不支持链接（仅支持 magnet / 115 分享）",
                    "warn",
                )
            if int(search_stats.get("media_guard_filtered", 0) or 0) > 0:
                media_reasons = search_stats.get("media_guard_reasons", {}) if isinstance(search_stats.get("media_guard_reasons"), dict) else {}
                reason_labels = {
                    "episode_like": "电影命中剧集资源",
                    "tv_like": "电影命中电视剧关键词",
                    "movie_like": "电视剧命中电影资源",
                    "missing_episode_meta": "电视剧缺少季集信息",
                }
                reason_text = "，".join(
                    f"{reason_labels.get(str(key), str(key))} {int(value or 0)} 条"
                    for key, value in media_reasons.items()
                    if int(value or 0) > 0
                )
                await write_subscription_log(
                    f"类型强分区已过滤 {int(search_stats.get('media_guard_filtered', 0) or 0)} 条非目标类型资源"
                    + (f"（{reason_text}）" if reason_text else ""),
                    "warn",
                )
            if int(search_stats.get("season_guard_filtered", 0) or 0) > 0:
                await write_subscription_log(
                    (
                        f"单季强过滤：已过滤 {int(search_stats.get('season_guard_filtered', 0) or 0)} 条季号不匹配资源"
                        f"（目标 S{int(search_stats.get('target_season', 0) or 0):02d}）"
                    ),
                    "warn",
                )
            if bool(search_stats.get("relaxed_score_mode", False)):
                await write_subscription_log(
                    (
                        f"评分放宽模式已启用：有 {int(search_stats.get('relaxed_candidates', 0) or 0)} 条电视剧候选因阈值过低未达标，"
                        "已改为先尝试候选再按集数去重判断"
                    ),
                    "warn",
                )
            if bool(search_stats.get("incremental_search_enabled", False)):
                await write_subscription_log(
                    (
                        f"频道增量搜索已启用：加载水位 {int(search_stats.get('incremental_channel_watermarks_loaded', 0) or 0)} 个，"
                        f"命中增量边界 {int(search_stats.get('incremental_stop_channels', 0) or 0)} 个频道，"
                        f"推进水位 {int(search_stats.get('incremental_channel_watermarks_advanced', 0) or 0)} 个频道，"
                        f"异常未推进 {int(search_stats.get('incremental_channel_watermarks_error_channels', 0) or 0)} 个频道"
                    ),
                    "info",
                )
            if int(search_stats.get("channel_support_rows_updated", 0) or 0) > 0:
                await write_subscription_log(
                    f"频道支持度统计已更新 {int(search_stats.get('channel_support_rows_updated', 0) or 0)} 个频道",
                    "info",
                )
            if search_errors:
                await write_subscription_log(
                    f"有 {len(search_errors)} 个频道搜索异常（不影响其余频道，{search_label}阶段）："
                    + "；".join(
                        [
                            (
                                f"{str(err.get('name', '') or err.get('channel_id', '未知频道')).strip()}:"
                                f"{str(err.get('message', '')).strip()}"
                            )[:120]
                            for err in search_errors[:3]
                        ]
                    ),
                    "warn",
                )

        upsert_subscription_task_state(task_name, status="running", progress=25, detail="候选准备完成，正在匹配评分")
        check_subscription_cancelled()
        ranked_candidates = search_result.get("candidates", []) if isinstance(search_result.get("candidates"), list) else []
        if not ranked_candidates:
            legacy_candidate = search_result.get("candidate", {}) if isinstance(search_result.get("candidate"), dict) else {}
            if legacy_candidate:
                ranked_candidates = [legacy_candidate]
        if not ranked_candidates:
            _subscription_stage_timer_enter(stage_timer, "finalize")
            if completed_locked:
                detail = f"已完结（{last_episode}/{known_total}），未发现可更新资源"
                status = "completed"
            elif use_fixed_share_link and fixed_link_channel_search_enabled:
                detail = "固定分享链接当前不可用，且频道补搜也未命中可导入资源，请检查固定链接/提取码或频道配置后重试"
                status = "waiting"
            elif use_fixed_share_link:
                detail = "固定分享链接当前不可用，请检查链接/提取码或稍后重试"
                status = "waiting"
            elif int(search_stats.get("searched_sources", 0) or 0) <= 0:
                detail = "未启用任何 TG 订阅源，请先在参数配置里启用频道后重试"
                status = "waiting"
            elif int(search_stats.get("supported_items", 0) or 0) <= 0:
                detail = "命中资源均非可导入类型（仅支持 magnet / 115 分享），请调整频道或关键词"
                status = "waiting"
            elif int(search_stats.get("media_guard_filtered", 0) or 0) > 0 and int(search_stats.get("scored_items", 0) or 0) <= 0:
                media_label = "电影" if task.get("media_type") == "movie" else "电视剧"
                detail = f"强分区已过滤非{media_label}资源 {int(search_stats.get('media_guard_filtered', 0) or 0)} 条，当前暂无符合类型的可导入资源"
                status = "waiting"
            elif int(search_stats.get("season_guard_filtered", 0) or 0) > 0 and int(search_stats.get("scored_items", 0) or 0) <= 0:
                detail = (
                    f"已过滤季号不匹配资源 {int(search_stats.get('season_guard_filtered', 0) or 0)} 条"
                    f"（目标 S{int(search_stats.get('target_season', 0) or 0):02d}），当前暂无可导入资源"
                )
                status = "waiting"
            else:
                detail = (
                    f"主动搜索未命中（阈值 {int(task.get('min_score', SUBSCRIPTION_MIN_SCORE) or SUBSCRIPTION_MIN_SCORE)}，"
                    f"候选 {int(search_stats.get('deduped_items', 0) or 0)} 条，"
                    f"最高分 {int(search_stats.get('best_score', 0) or 0)}）"
                )
                status = "waiting"
            upsert_subscription_task_state(
                task_name,
                media_type=task.get("media_type", "movie"),
                status=status,
                progress=100,
                detail=detail,
                stats={
                    "matched": False,
                    "run_id": subscription_run_id,
                    "batch_refresh_enabled": batch_refresh_enabled,
                    "last_episode": last_episode,
                    "total_episodes": known_total,
                    **search_stats,
                },
            )
            await write_subscription_log(detail, "warn" if status == "waiting" else "info")
            update_subscription_summary("等待资源" if status == "waiting" else "已完成", detail)
            return

        base_savepath = normalize_relative_path(str(task.get("savepath", "")).strip())
        effective_savepath = base_savepath
        if task["media_type"] == "movie":
            movie_folder = sanitize_115_folder_name(
                f"{task.get('title', '')} {task.get('year', '')}".strip() or "未命名电影",
                fallback="未命名电影",
            )
            effective_savepath = join_relative_path(base_savepath, movie_folder)
        elif task["media_type"] == "tv":
            effective_savepath = resolve_subscription_tv_base_savepath(task, base_savepath) or base_savepath
        check_subscription_cancelled()
        _subscription_stage_timer_enter(stage_timer, "calibrate")
        upsert_subscription_task_state(task_name, status="running", progress=45, detail="正在准备目标目录")
        cookie_115 = str(cfg.get("cookie_115", "")).strip()
        folder_id = await asyncio.to_thread(
            ensure_115_folder_id_by_path,
            cookie_115,
            effective_savepath,
        )
        matched_monitor = match_monitor_task_for_savepath(cfg, effective_savepath, provider=provider)
        monitor_task_name = str(matched_monitor.get("task_name", "") or "").strip()

        existing_folder_episodes: Set[int] = set()
        existing_episode_scan_stats: Dict[str, Any] = {}
        existing_episode_scan_ready = False
        existing_episode_scan_reliable = False
        episode_ledger_rows: Dict[int, Dict[str, Any]] = {}
        if task["media_type"] == "tv":
            upsert_subscription_task_state(task_name, status="running", progress=47, detail="正在读取目标目录已落盘剧集")
            try:
                scan_result = await asyncio.to_thread(
                    _scan_115_existing_tv_episodes,
                    cookie_115,
                    folder_id,
                    task,
                )
                scan_episodes = scan_result.get("episodes", []) if isinstance(scan_result.get("episodes"), list) else []
                existing_folder_episodes = _clamp_episode_values(
                    {max(0, int(item or 0)) for item in scan_episodes if max(0, int(item or 0)) > 0},
                    episode_upper_bound=single_season_episode_upper_bound,
                )
                existing_episode_scan_stats = {
                    "existing_episode_scan_ready": True,
                    "existing_episode_count": len(existing_folder_episodes),
                    "existing_episode_max": max(existing_folder_episodes) if existing_folder_episodes else 0,
                    "existing_episode_scanned_dirs": int(scan_result.get("scanned_dirs", 0) or 0),
                    "existing_episode_scanned_entries": int(scan_result.get("scanned_entries", 0) or 0),
                    "existing_episode_failed_dirs": int(scan_result.get("failed_dirs", 0) or 0),
                    "existing_episode_scan_truncated": bool(scan_result.get("truncated", False)),
                }
                existing_episode_scan_ready = True
                if existing_folder_episodes:
                    await write_subscription_log(
                        (
                            f"目标目录已识别 {len(existing_folder_episodes)} 集（最高 E{max(existing_folder_episodes)}，"
                            f"样例 {_format_episode_preview(existing_folder_episodes)}），本次按缺失集优先导入"
                        ),
                        "info",
                    )
                else:
                    await write_subscription_log(
                        (
                            f"目标目录未识别到已落盘剧集（扫描目录 {int(scan_result.get('scanned_dirs', 0) or 0)} 个，"
                            f"条目 {int(scan_result.get('scanned_entries', 0) or 0)} 条）"
                        ),
                        "info",
                    )
                if int(scan_result.get("failed_dirs", 0) or 0) > 0:
                    await write_subscription_log(
                        f"目标目录扫描有 {int(scan_result.get('failed_dirs', 0) or 0)} 个子目录读取失败，已自动忽略",
                        "warn",
                    )
                if bool(scan_result.get("truncated", False)):
                    await write_subscription_log("目标目录扫描达到上限，已截断后续子目录（避免单次执行过慢）", "warn")
            except Exception as exc:
                existing_episode_scan_stats = {"existing_episode_scan_ready": False}
                await write_subscription_log(f"读取目标目录已落盘剧集失败，回退历史进度判断：{exc}", "warn")
            episode_ledger_rows = load_subscription_episode_ledger(task_name, include_stale=True)
            if existing_episode_scan_ready:
                scan_scanned_dirs = int(existing_episode_scan_stats.get("existing_episode_scanned_dirs", 0) or 0)
                scan_failed_dirs = int(existing_episode_scan_stats.get("existing_episode_failed_dirs", 0) or 0)
                scan_reliable = not (scan_scanned_dirs <= 0 and scan_failed_dirs > 0)
                existing_episode_scan_reliable = scan_reliable
                if scan_reliable:
                    ledger_sync = reconcile_subscription_episode_ledger(task_name, existing_folder_episodes)
                    activated_count = max(0, int(ledger_sync.get("activated", 0) or 0))
                    staled_count = max(0, int(ledger_sync.get("staled", 0) or 0))
                    if activated_count > 0 or staled_count > 0:
                        await write_subscription_log(
                            f"集数账本已对账：恢复 {activated_count} 集 / 标记失效 {staled_count} 集",
                            "info",
                        )
                    episode_ledger_rows = load_subscription_episode_ledger(task_name, include_stale=True)
            active_ledger_count = sum(
                1
                for row in episode_ledger_rows.values()
                if str((row or {}).get("status", "active") or "active").strip().lower() == "active"
            )
            if active_ledger_count > 0:
                await write_subscription_log(f"集数账本已加载：活跃记录 {active_ledger_count} 集", "info")
            if existing_episode_scan_reliable:
                corrected_last_episode = last_episode
                if existing_folder_episodes:
                    corrected_last_episode = max(existing_folder_episodes)
                elif int(existing_episode_scan_stats.get("existing_episode_scanned_entries", 0) or 0) <= 0:
                    corrected_last_episode = 0
                if corrected_last_episode != last_episode:
                    previous_last_episode = last_episode
                    last_episode = corrected_last_episode
                    completed_locked = task["media_type"] == "tv" and known_total > 0 and last_episode >= known_total
                    upsert_subscription_task_state(
                        task_name,
                        media_type=task.get("media_type", "movie"),
                        last_episode=last_episode,
                        total_episodes=known_total,
                    )
                    await write_subscription_log(
                        f"已按目标目录校准追更进度：E{previous_last_episode} -> E{last_episode}",
                        "info",
                    )

        trigger_is_manual = str(trigger or "").strip().lower() == "manual"
        batch_episode_import = (
            task["media_type"] == "tv"
            and trigger_is_manual
        )
        attempt_candidates = ranked_candidates
        if task["media_type"] == "tv" and existing_episode_scan_ready:
            attempt_candidates = _prioritize_tv_candidates_by_missing_episodes(
                ranked_candidates,
                existing_folder_episodes,
                last_episode,
                prefer_backfill=trigger_is_manual,
                episode_upper_bound=single_season_episode_upper_bound,
            )
            if (not existing_folder_episodes) and single_season_episode_upper_bound > 0:
                await write_subscription_log(
                    f"单季首轮优化：已按 E1-E{single_season_episode_upper_bound} 覆盖度优先排序候选资源",
                    "info",
                )
            missing_episode_candidates = 0
            existing_episode_candidates = 0
            for candidate in attempt_candidates:
                episode_values = _candidate_episode_values(
                    candidate,
                    episode_upper_bound=single_season_episode_upper_bound,
                )
                if not episode_values:
                    continue
                missing_episode_values = _candidate_missing_episode_values(
                    candidate,
                    existing_folder_episodes,
                    episode_upper_bound=single_season_episode_upper_bound,
                )
                if not missing_episode_values:
                    existing_episode_candidates += 1
                else:
                    missing_episode_candidates += 1
            await write_subscription_log(
                (
                    f"目录集数匹配: 缺失集候选 {missing_episode_candidates} 条，"
                    f"目录已存在候选 {existing_episode_candidates} 条"
                ),
                "info",
            )
        if batch_episode_import:
            deduped_candidates: List[Dict[str, Any]] = []
            bucket_limit_per_episode = 3
            episode_bucket_counts: Dict[str, int] = {}
            for candidate in attempt_candidates:
                episode = max(0, int(candidate.get("episode", 0) or 0))
                range_start = max(0, int(candidate.get("range_start", 0) or 0))
                range_end = max(0, int(candidate.get("range_end", 0) or 0))
                bucket_key = ""
                if range_start > 0 and range_end > 0:
                    if range_end < range_start:
                        range_start, range_end = range_end, range_start
                    bucket_key = f"r:{range_start}-{range_end}"
                elif episode > 0:
                    bucket_key = f"e:{episode}"
                if bucket_key:
                    current_count = int(episode_bucket_counts.get(bucket_key, 0) or 0)
                    if current_count >= bucket_limit_per_episode:
                        continue
                    episode_bucket_counts[bucket_key] = current_count + 1
                deduped_candidates.append(candidate)
            with_episode_candidates = [item for item in deduped_candidates if int(item.get("episode", 0) or 0) > 0]
            without_episode_candidates = [item for item in deduped_candidates if int(item.get("episode", 0) or 0) <= 0]
            if with_episode_candidates:
                # 保留少量无集数候选兜底，避免合集文案无法标准解析时被整体丢弃。
                fallback_without_episode = without_episode_candidates[: min(3, len(without_episode_candidates))]
                attempt_candidates = with_episode_candidates + fallback_without_episode
            else:
                attempt_candidates = without_episode_candidates
            await write_subscription_log(
                f"手动追更批量模式：同集/同范围最多保留 {bucket_limit_per_episode} 条，候选 {len(attempt_candidates)} 条，本次最多尝试 {min(20, len(attempt_candidates))} 条",
                "info",
            )

        invalid_link_cache = (
            {}
            if (use_fixed_share_link and (not fixed_link_channel_search_enabled))
            else _load_subscription_invalid_link_cache(
                [
                    _normalize_subscription_candidate_link(
                        (candidate.get("item", {}) if isinstance(candidate.get("item"), dict) else {}).get("link_url", "")
                    )
                    for candidate in attempt_candidates
                ]
            )
        )
        if invalid_link_cache:
            await write_subscription_log(
                f"失效链接缓存命中 {len(invalid_link_cache)} 条，本次将自动跳过对应候选资源",
                "info",
            )

        max_attempts = max(1, min(20 if batch_episode_import else 8, len(attempt_candidates)))
        attempt_interval_seconds = max(0.0, float(SUBSCRIPTION_ATTEMPT_INTERVAL_SECONDS or 0))
        import_timeout_seconds = max(10, int(SUBSCRIPTION_IMPORT_TIMEOUT_SECONDS or 90))
        attempted_candidates = 0
        scanned_candidates = 0
        max_scan_candidates = max_attempts if task["media_type"] != "tv" else min(len(attempt_candidates), max_attempts * 8)
        failed_attempts = 0
        timed_out_attempts = 0
        skipped_episode_candidates = 0
        skipped_existing_candidates = 0
        skipped_ledger_candidates = 0
        skipped_invalid_candidates = 0
        skipped_subdir_candidates = 0
        last_failed_detail = ""
        selected_candidate: Dict[str, Any] = {}
        selected_item: Dict[str, Any] = {}
        selected_job_id = 0
        selected_auto_refresh = False
        selected_reused_existing = False
        selected_job_savepath = effective_savepath
        baseline_last_episode = last_episode
        imported_episodes: Set[int] = set()
        successful_count = 0
        max_total_detected = 0
        successful_job_ids: List[int] = []
        batch_created_job_ids: Set[int] = set()
        share_subdir_selection_cache: Dict[str, Dict[str, Any]] = {}
        share_subdir_selection_stats_cache: Dict[str, Dict[str, Any]] = {}
        fixed_share_runtime_initialized = False
        fixed_share_runtime_selection: Dict[str, Any] = {}
        fixed_share_runtime_subdir_stats: Dict[str, Any] = {}
        fixed_share_runtime_manifest: Dict[str, Any] = {}
        savepath_folder_id_cache: Dict[str, str] = {effective_savepath: str(folder_id or "").strip()}
        batch_refresh_result: Dict[str, Any] = {
            "run_id": subscription_run_id,
            "created_jobs": 0,
            "successful_jobs": 0,
            "refresh_eligible_jobs": 0,
            "grouped_targets": 0,
            "triggered_groups": 0,
            "triggered_jobs": 0,
            "missing_monitor_task_groups": 0,
            "missing_monitor_task_jobs": 0,
        }
        existing_episode_count = len(existing_folder_episodes)

        if max_attempts > 1 and (attempt_interval_seconds > 0 or import_timeout_seconds > 0):
            await write_subscription_log(
                (
                    f"候选执行策略：间隔 {attempt_interval_seconds:g} 秒，"
                    f"单候选超时 {import_timeout_seconds} 秒自动跳过"
                ),
                "info",
            )

        async def maybe_wait_between_attempts() -> None:
            if attempt_interval_seconds <= 0:
                return
            if attempted_candidates >= max_attempts:
                return
            if scanned_candidates >= max_scan_candidates:
                return
            check_subscription_cancelled()
            await asyncio.sleep(attempt_interval_seconds)

        async def rescan_existing_tv_episodes() -> Tuple[Dict[str, Any], Set[int]]:
            scan_result = await asyncio.to_thread(
                _scan_115_existing_tv_episodes,
                cookie_115,
                folder_id,
                task,
            )
            scan_episodes = {
                max(0, int(item or 0))
                for item in (
                    scan_result.get("episodes", [])
                    if isinstance(scan_result.get("episodes"), list)
                    else []
                )
                if max(0, int(item or 0)) > 0
            }
            normalized_scan_episodes = _clamp_episode_values(
                scan_episodes,
                episode_upper_bound=single_season_episode_upper_bound,
            )
            return scan_result, normalized_scan_episodes

        def consume_background_task_result(task: asyncio.Task) -> None:
            try:
                task.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        _subscription_stage_timer_enter(stage_timer, "import")
        for index, candidate in enumerate(attempt_candidates, start=1):
            if attempted_candidates >= max_attempts:
                break
            if scanned_candidates >= max_scan_candidates:
                break
            scanned_candidates += 1
            check_subscription_cancelled()
            item = candidate.get("item", {}) if isinstance(candidate.get("item"), dict) else {}
            resource_id = int(item.get("id", 0) or 0)
            if resource_id <= 0 and (not use_fixed_share_link):
                continue
            score = int(candidate.get("score", 0) or 0)
            episode = max(0, int(candidate.get("episode", 0) or 0))
            total_detected = max(0, int(candidate.get("total", 0) or 0))
            candidate_season = max(0, int(candidate.get("season", 0) or 0))
            range_start = max(0, int(candidate.get("range_start", 0) or 0))
            range_end = max(0, int(candidate.get("range_end", 0) or 0))
            candidate_episode_values = _candidate_episode_values(
                candidate,
                episode_upper_bound=single_season_episode_upper_bound,
            )
            episode_label = _format_candidate_episode_label(candidate)
            candidate_link_url = _normalize_subscription_candidate_link(item.get("link_url", ""))
            candidate_link_type = resolve_resource_link_type(item.get("link_type", ""), candidate_link_url)
            candidate_share_subdir_cid = task_share_subdir_cid if use_fixed_share_link else ""
            candidate_share_scope_label = _format_subscription_share_scope_label(
                task_share_subdir,
                candidate_share_subdir_cid,
            )
            candidate_savepath = effective_savepath
            if task["media_type"] == "tv":
                candidate_savepath = build_subscription_tv_savepath(
                    task,
                    base_savepath,
                    season=candidate_season,
                    episode=episode,
                ) or effective_savepath
            candidate_matched_monitor = match_monitor_task_for_savepath(cfg, candidate_savepath, provider=provider)
            candidate_monitor_task_name = str(candidate_matched_monitor.get("task_name", "") or "").strip()

            if (
                task["media_type"] == "tv"
                and single_season_episode_upper_bound > 0
                and (episode > single_season_episode_upper_bound or range_end > single_season_episode_upper_bound)
                and not candidate_episode_values
            ):
                skipped_episode_candidates += 1
                await write_subscription_log(
                    (
                        f"候选资源 #{index}（评分 {score}）集数 {episode_label} 超出单季总集数 "
                        f"E{single_season_episode_upper_bound}，已跳过"
                    ),
                    "warn",
                )
                continue

            cached_invalid_meta = invalid_link_cache.get(candidate_link_url) if candidate_link_url else None
            fixed_share_seed_candidate = (
                use_fixed_share_link
                and resource_id <= 0
                and candidate_link_type == "115share"
            )
            if cached_invalid_meta and (not fixed_share_seed_candidate):
                skipped_invalid_candidates += 1
                cache_reason = str(cached_invalid_meta.get("reason", "") or "").strip()
                expires_at = str(cached_invalid_meta.get("expires_at", "") or "").strip()
                reason_tail = f"（{cache_reason[:60]}）" if cache_reason else ""
                expire_tail = f"，有效期至 {expires_at}" if expires_at else ""
                await write_subscription_log(
                    f"候选资源 #{index} 链接命中失效缓存，已自动跳过{reason_tail}{expire_tail}",
                    "warn",
                )
                continue

            if task["media_type"] == "tv" and episode > 0:
                if candidate_episode_values and candidate_episode_values.issubset(imported_episodes):
                    skipped_episode_candidates += 1
                    await write_subscription_log(
                        f"候选资源 #{index}（评分 {score}）集数 {episode_label} 本轮已导入，继续尝试下一个",
                        "warn",
                    )
                    continue
                if existing_episode_scan_ready and candidate_episode_values and candidate_episode_values.issubset(existing_folder_episodes):
                    skipped_existing_candidates += 1
                    await write_subscription_log(
                        f"候选资源 #{index}（评分 {score}）集数 {episode_label} 目标目录已存在，继续尝试下一个",
                        "warn",
                    )
                    continue
                if existing_episode_scan_ready and candidate_episode_values:
                    overlap_existing = any(episode_no in existing_folder_episodes for episode_no in candidate_episode_values)
                    if overlap_existing:
                        missing_for_candidate = _candidate_missing_episode_values(
                            candidate,
                            existing_folder_episodes,
                            episode_upper_bound=single_season_episode_upper_bound,
                        )
                        if missing_for_candidate:
                            missing_ratio = len(missing_for_candidate) / max(1, len(candidate_episode_values))
                            # 非 115 分享资源无法做精细转存，若只缺很少集数，优先跳过避免整包重复。
                            if candidate_link_type != "115share" and missing_ratio <= 0.35:
                                skipped_existing_candidates += 1
                                await write_subscription_log(
                                    (
                                        f"候选资源 #{index}（评分 {score}）与目录重叠度较高（缺失占比 {missing_ratio:.0%}），"
                                        "当前链接不支持精细转存，已跳过整包避免重复集"
                                    ),
                                    "warn",
                                )
                                continue
                ledger_skip_reason = _candidate_episode_ledger_skip_reason(
                    candidate,
                    candidate_episode_values,
                    episode_ledger_rows,
                )
                if ledger_skip_reason:
                    skipped_ledger_candidates += 1
                    await write_subscription_log(
                        f"候选资源 #{index}（评分 {score}）{ledger_skip_reason}",
                        "warn",
                    )
                    continue
                is_old_episode = episode < baseline_last_episode
                is_same_episode_blocked = episode == baseline_last_episode and not completed_locked
                range_backfill_candidate = range_start > 0 and range_end > 0 and range_start < baseline_last_episode
                if (not existing_episode_scan_ready) and (is_old_episode or is_same_episode_blocked) and not range_backfill_candidate:
                    skipped_episode_candidates += 1
                    await write_subscription_log(
                        f"候选资源 #{index}（评分 {score}）集数重复 {episode_label}，当前进度 E{baseline_last_episode}，继续尝试下一个",
                        "warn",
                    )
                    continue

            attempted_candidates += 1
            upsert_subscription_task_state(
                task_name,
                status="running",
                progress=min(85, 48 + attempted_candidates * 6),
                detail=f"正在尝试候选资源 {attempted_candidates}/{max_attempts}",
            )

            pre_attempt_existing_episodes = set(existing_folder_episodes)
            resolved_subdir_selection: Dict[str, Any] = {}
            subdir_stats: Dict[str, Any] = {}
            if (
                use_fixed_share_link
                and task["media_type"] == "tv"
                and candidate_link_type == "115share"
                and (task_share_subdir or candidate_share_subdir_cid)
                and (not fixed_share_runtime_initialized)
            ):
                fixed_share_runtime_initialized = True
                runtime_subdir_started_at = time.perf_counter()
                fixed_share_runtime_selection, fixed_share_runtime_subdir_stats = await _build_subscription_share_subdir_selection(
                    cookie_115,
                    item,
                    task_share_subdir,
                    share_subdir_cid=candidate_share_subdir_cid,
                    force_refresh=True,
                    allow_fallback=False,
                )
                runtime_subdir_elapsed_seconds = max(0.0, time.perf_counter() - runtime_subdir_started_at)
                fixed_share_runtime_selection = normalize_share_selection_meta(fixed_share_runtime_selection)
                fixed_share_runtime_subdir_stats = dict(fixed_share_runtime_subdir_stats or {})
                runtime_selected_ids = (
                    fixed_share_runtime_selection.get("selected_ids", [])
                    if isinstance(fixed_share_runtime_selection.get("selected_ids"), list)
                    else []
                )
                if runtime_selected_ids:
                    runtime_manifest_started_at = time.perf_counter()
                    fixed_share_runtime_manifest = await _scan_subscription_share_episode_manifest(
                        cookie_115,
                        task,
                        item,
                        fixed_share_runtime_selection,
                        force_refresh=True,
                    )
                    runtime_manifest_elapsed_seconds = max(0.0, time.perf_counter() - runtime_manifest_started_at)
                else:
                    runtime_manifest_elapsed_seconds = 0.0
                runtime_subdir_reason_code = str((fixed_share_runtime_subdir_stats or {}).get("reason", "--") or "--").strip()
                runtime_subdir_reason_label = (
                    _format_subscription_reason_chain(runtime_subdir_reason_code)
                    if runtime_subdir_reason_code and runtime_subdir_reason_code != "--"
                    else "--"
                )
                await write_subscription_log(
                    (
                        f"固定链接运行期缓存已刷新：定位子目录 {_format_elapsed_seconds(runtime_subdir_elapsed_seconds)}，"
                        f"识别目录 {runtime_subdir_reason_label}，"
                        f"扫描目录 {int(fixed_share_runtime_manifest.get('scanned_dirs', 0) or 0)} 个，"
                        f"条目 {int(fixed_share_runtime_manifest.get('scanned_entries', 0) or 0)} 条，"
                        f"可识别剧集文件 {int(fixed_share_runtime_manifest.get('file_count', 0) or 0)} 个，"
                        f"扫描耗时 {_format_elapsed_seconds(runtime_manifest_elapsed_seconds)}，"
                        f"并发 {SUBSCRIPTION_SHARE_SCAN_CONCURRENCY}，"
                        f"限速 {SUBSCRIPTION_SHARE_SCAN_RATE_LIMIT_SECONDS:g}s"
                    ),
                    "info",
                )
            if candidate_link_type == "115share" and (task_share_subdir or candidate_share_subdir_cid):
                if use_fixed_share_link and fixed_share_runtime_initialized:
                    resolved_subdir_selection = fixed_share_runtime_selection
                    subdir_stats = fixed_share_runtime_subdir_stats
                else:
                    subdir_cache_key = f"{candidate_link_url or f'resource:{resource_id}'}|{task_share_subdir}|{candidate_share_subdir_cid}"
                    if subdir_cache_key in share_subdir_selection_cache:
                        resolved_subdir_selection = share_subdir_selection_cache.get(subdir_cache_key, {})
                        subdir_stats = share_subdir_selection_stats_cache.get(subdir_cache_key, {})
                    else:
                        resolved_subdir_selection, subdir_stats = await _build_subscription_share_subdir_selection(
                            cookie_115,
                            item,
                            task_share_subdir,
                            share_subdir_cid=candidate_share_subdir_cid,
                        )
                        share_subdir_selection_cache[subdir_cache_key] = resolved_subdir_selection
                        share_subdir_selection_stats_cache[subdir_cache_key] = subdir_stats

                selected_ids = (
                    resolved_subdir_selection.get("selected_ids", [])
                    if isinstance(resolved_subdir_selection.get("selected_ids"), list)
                    else []
                )
                subdir_reason = str((subdir_stats or {}).get("reason", "") or "").strip()
                if not selected_ids:
                    if subdir_reason == "target_is_share_root":
                        await write_subscription_log(
                            f"候选资源 #{index} 的分享子目录配置等于分享根目录，已回退为根目录导入",
                            "warn",
                        )
                    else:
                        skipped_subdir_candidates += 1
                        failed_segment = str((subdir_stats or {}).get("failed_segment", "") or "").strip()
                        sibling_samples = (
                            (subdir_stats or {}).get("sibling_dir_samples", [])
                            if isinstance((subdir_stats or {}).get("sibling_dir_samples", []), list)
                            else []
                        )
                        fallback_candidate_samples = (
                            (subdir_stats or {}).get("fallback_candidate_samples", [])
                            if isinstance((subdir_stats or {}).get("fallback_candidate_samples", []), list)
                            else []
                        )
                        fallback_reason = str((subdir_stats or {}).get("fallback_reason", "") or "").strip()
                        root_error = str((subdir_stats or {}).get("root_error", "") or "").strip()
                        root_retry_attempts = int((subdir_stats or {}).get("root_retry_attempts", 0) or 0)
                        anchor_error = str((subdir_stats or {}).get("anchor_error", "") or "").strip()
                        anchor_retry_attempts = int((subdir_stats or {}).get("anchor_retry_attempts", 0) or 0)
                        reason_tail = f"（{_format_subscription_reason_chain(subdir_reason)}）" if subdir_reason else ""
                        segment_tail = f"，未命中片段：{failed_segment}" if failed_segment else ""
                        sample_text = " / ".join(
                            [str(name or "").strip()[:80] for name in sibling_samples[:3] if str(name or "").strip()]
                        )
                        sample_tail = f"，同级目录示例：{sample_text}" if sample_text else ""
                        fallback_sample_text = " / ".join(
                            [str(name or "").strip()[:80] for name in fallback_candidate_samples[:3] if str(name or "").strip()]
                        )
                        fallback_tail = ""
                        if fallback_reason:
                            fallback_tail = f"，回溯匹配：{_format_subscription_reason_chain(fallback_reason)}"
                        if fallback_sample_text:
                            fallback_tail += f"，候选示例：{fallback_sample_text}"
                        root_tail = ""
                        if subdir_reason == "share_root_unreachable":
                            retry_tail = f"（已重试 {root_retry_attempts} 次）" if root_retry_attempts > 1 else ""
                            root_tail = f"，分享目录访问失败：{(root_error or '未知原因')[:140]}{retry_tail}"
                        if subdir_reason == "share_anchor_unreachable":
                            retry_tail = f"（已重试 {anchor_retry_attempts} 次）" if anchor_retry_attempts > 1 else ""
                            root_tail = f"，CID 目录访问失败：{(anchor_error or '未知原因')[:140]}{retry_tail}"
                        await write_subscription_log(
                            (
                                f"候选资源 #{index} 未命中订阅子目录「{candidate_share_scope_label}」，"
                                f"已跳过该候选{reason_tail}{segment_tail}{sample_tail}{fallback_tail}{root_tail}"
                            ),
                            "warn",
                        )
                        await maybe_wait_between_attempts()
                        continue
                if (
                    selected_ids
                    and candidate_link_type == "115share"
                    and task.get("media_type") == "tv"
                    and not (use_fixed_share_link and fixed_share_runtime_initialized)
                ):
                    refined_selection, refine_stats = await _refine_subscription_share_selection_for_task(
                        cookie_115,
                        item,
                        task,
                        resolved_subdir_selection,
                    )
                    refined_ids = (
                        refined_selection.get("selected_ids", [])
                        if isinstance(refined_selection.get("selected_ids"), list)
                        else []
                    )
                    refine_reason = str((refine_stats or {}).get("reason", "") or "").strip()
                    if refined_ids and refined_ids != selected_ids:
                        from_path = str((refine_stats or {}).get("from_path", "") or "").strip()
                        to_path = str((refine_stats or {}).get("to_path", "") or "").strip()
                        resolved_subdir_selection = refined_selection
                        selected_ids = refined_ids
                        await write_subscription_log(
                            (
                                f"候选资源 #{index} 订阅子目录已自动收敛："
                                f"{from_path or candidate_share_scope_label} -> {to_path or '--'}"
                            ),
                            "info",
                        )
                    else:
                        current_score = int((refine_stats or {}).get("current_score", 0) or 0)
                        best_score = int((refine_stats or {}).get("best_score", 0) or 0)
                        start_child_dirs = int((refine_stats or {}).get("start_child_dirs", 0) or 0)
                        candidate_samples = (
                            (refine_stats or {}).get("candidate_samples", [])
                            if isinstance((refine_stats or {}).get("candidate_samples", []), list)
                            else []
                        )
                        should_guard_skip = (
                            refine_reason in ("not_found", "ambiguous", "weak_match", "refine_selection_empty")
                            and current_score < 170
                            and start_child_dirs > 1
                        )
                        if should_guard_skip:
                            skipped_subdir_candidates += 1
                            sample_text = " / ".join(
                                [str(name or "").strip()[:80] for name in candidate_samples[:3] if str(name or "").strip()]
                            )
                            sample_tail = f"，候选示例：{sample_text}" if sample_text else ""
                            await write_subscription_log(
                                (
                                    f"候选资源 #{index} 子目录疑似合集目录，且未能安全收敛到剧集目录，"
                                    f"已跳过避免整包导入（{_format_subscription_reason_chain(refine_reason or 'unknown')}，"
                                    f"当前分 {current_score}，最佳候选分 {best_score}）{sample_tail}"
                                ),
                                "warn",
                            )
                            await maybe_wait_between_attempts()
                            continue

            candidate_folder_id = str(savepath_folder_id_cache.get(candidate_savepath, "") or "").strip()
            if not candidate_folder_id:
                candidate_folder_id = await asyncio.to_thread(
                    ensure_115_folder_id_by_path,
                    cookie_115,
                    candidate_savepath,
                )
                savepath_folder_id_cache[candidate_savepath] = str(candidate_folder_id or "").strip()

            existing = find_existing_resource_job(item, candidate_savepath)
            job_id = 0
            auto_refresh = bool(candidate_monitor_task_name)
            reused_existing = False
            selected_share_episode_values: Set[int] = set()
            selected_share_file_samples: List[str] = []
            candidate_success_records: List[Dict[str, Any]] = []
            if existing and use_fixed_share_link and candidate_link_type == "115share":
                existing = {}
                await write_subscription_log(
                    f"候选资源 #{index} 为固定分享链接模式，本次强制重新导入以捕捉目录更新",
                    "info",
                )
            if existing and candidate_link_type == "115share" and (task_share_subdir or candidate_share_subdir_cid):
                existing_extra = existing.get("extra") if isinstance(existing.get("extra"), dict) else {}
                existing_share_subdir = normalize_relative_path(
                    str(existing_extra.get("subscription_share_subdir", "") or "").strip()
                )
                existing_share_subdir_cid = _normalize_subscription_share_subdir_cid(
                    existing_extra.get("subscription_share_subdir_cid", "")
                )
                if existing_share_subdir != task_share_subdir or existing_share_subdir_cid != candidate_share_subdir_cid:
                    existing = {}
                    await write_subscription_log(
                        (
                            f"候选资源 #{index} 历史任务子目录策略不一致（旧: "
                            f"{_format_subscription_share_scope_label(existing_share_subdir, existing_share_subdir_cid)}），"
                            "改为重新导入"
                        ),
                        "info",
                    )
            if existing and task["media_type"] == "tv" and existing_episode_scan_ready:
                # 历史任务复用前先看目录是否仍缺集，避免“手动删文件后仍复用旧任务”。
                missing_for_candidate = _candidate_missing_episode_values(
                    candidate,
                    existing_folder_episodes,
                    episode_upper_bound=single_season_episode_upper_bound,
                )
                needs_reimport = bool(missing_for_candidate)
                if needs_reimport:
                    existing = {}
                    await write_subscription_log(
                        (
                            f"候选资源 #{index} 检测到目录仍缺失 "
                            f"{_format_episode_preview(missing_for_candidate)}，本次不复用历史任务，改为重新导入"
                        ),
                        "info",
                    )
            if existing:
                job_id = int(existing.get("id", 0) or 0)
                existing_status = str(existing.get("status", "") or "").strip().lower()
                if existing_status == "failed":
                    failed_attempts += 1
                    last_failed_detail = str(existing.get("status_detail", "") or f"任务 #{job_id} 失败").strip()
                    if (not use_fixed_share_link) and candidate_link_url and _is_subscription_invalid_link_error(last_failed_detail, candidate_link_type):
                        cache_meta = _record_subscription_invalid_link_cache(candidate_link_url, candidate_link_type, last_failed_detail)
                        if cache_meta:
                            invalid_link_cache[candidate_link_url] = cache_meta
                            await write_subscription_log(
                                f"候选资源 #{index} 链接已标记为失效，后续自动跳过（有效期至 {cache_meta.get('expires_at', '--')}）",
                                "warn",
                            )
                    await write_subscription_log(
                        f"候选资源 #{index} 历史任务 #{job_id} 失败：{last_failed_detail}，继续尝试下一个",
                        "warn",
                    )
                    await maybe_wait_between_attempts()
                    continue
                auto_refresh = bool(existing.get("auto_refresh"))
                reused_existing = True
                await write_subscription_log(f"候选资源 #{index} 命中历史任务 #{job_id}，复用执行记录", "warn")
                candidate_success_records.append(
                    {
                        "job_id": job_id,
                        "savepath": candidate_savepath,
                        "auto_refresh": auto_refresh,
                        "reused_existing": True,
                        "recorded_episode_values": _resolve_recorded_episode_values(
                            candidate,
                            set(),
                            episode_upper_bound=single_season_episode_upper_bound,
                        ),
                        "selected_file_samples": [],
                        "ledger_season": (
                            candidate_season
                            if candidate_season > 0
                            else (max(1, int(task.get("season", 1) or 1)) if not is_subscription_multi_season_mode(task) else 0)
                        ),
                    }
                )
            else:
                job_payload = {
                    "folder_id": candidate_folder_id,
                    "savepath": candidate_savepath,
                    "sharetitle": "",
                    "monitor_task_name": candidate_monitor_task_name,
                    "refresh_delay_seconds": 0,
                    "auto_refresh": bool(candidate_monitor_task_name) and (not batch_refresh_enabled),
                    "extra": {
                        "job_source": "subscription_auto",
                        "subscription_task_name": task_name,
                        "subscription_run_id": subscription_run_id,
                    },
                }
                if task_share_subdir:
                    job_payload["extra"]["subscription_share_subdir"] = task_share_subdir
                if candidate_share_subdir_cid:
                    job_payload["extra"]["subscription_share_subdir_cid"] = candidate_share_subdir_cid
                if use_fixed_share_link and candidate_link_type == "115share":
                    job_payload["extra"]["subscription_share_link_url"] = task_share_link_url
                    if task_share_link_receive_code:
                        job_payload["receive_code"] = task_share_link_receive_code
                if (
                    candidate_link_type == "115share"
                    and (
                        resolved_subdir_selection.get("selected_ids", [])
                        if isinstance(resolved_subdir_selection.get("selected_ids"), list)
                        else []
                    )
                ):
                    job_payload["share_selection"] = resolved_subdir_selection
                forced_precise_selection_applied = False
                if (
                    use_fixed_share_link
                    and candidate_link_type == "115share"
                    and task.get("media_type") == "tv"
                    and (task_share_subdir or candidate_share_subdir_cid)
                ):
                    precise_missing_episode_values: Set[int] = set()
                    if known_total > 0:
                        precise_missing_episode_values = set(range(1, known_total + 1))
                    elif single_season_episode_upper_bound > 0:
                        precise_missing_episode_values = set(range(1, single_season_episode_upper_bound + 1))
                    elif candidate_episode_values:
                        precise_missing_episode_values = set(candidate_episode_values)
                    if existing_episode_scan_ready and precise_missing_episode_values:
                        precise_missing_episode_values = {
                            episode_no
                            for episode_no in precise_missing_episode_values
                            if episode_no not in existing_folder_episodes
                        }
                    if existing_episode_scan_ready and known_total > 0 and not precise_missing_episode_values:
                        skipped_existing_candidates += 1
                        await write_subscription_log(
                            f"候选资源 #{index} 目录已覆盖订阅总集数 E1-E{known_total}，跳过导入",
                            "info",
                        )
                        await maybe_wait_between_attempts()
                        continue
                    if precise_missing_episode_values:
                        if use_fixed_share_link and fixed_share_runtime_manifest:
                            precise_selection, precise_stats = _build_tv_share_selection_from_manifest(
                                fixed_share_runtime_manifest,
                                precise_missing_episode_values,
                                task=task,
                            )
                        else:
                            precise_selection, precise_stats = await _build_tv_share_selection_for_missing_episodes(
                                cookie_115,
                                task,
                                item,
                                precise_missing_episode_values,
                                share_subdir_selection=resolved_subdir_selection,
                            )
                        precise_ids = (
                            precise_selection.get("selected_ids", [])
                            if isinstance(precise_selection.get("selected_ids"), list)
                            else []
                        )
                        if precise_ids:
                            job_payload["share_selection"] = precise_selection
                            forced_precise_selection_applied = True
                            selected_share_episode_values = {
                                max(0, int(value or 0))
                                for value in (
                                    precise_stats.get("covered_episodes", [])
                                    if isinstance(precise_stats, dict)
                                    else []
                                )
                                if max(0, int(value or 0)) > 0
                            }
                            selected_share_file_samples = [
                                str(sample or "").strip()
                                for sample in (
                                    precise_stats.get("selected_file_samples", [])
                                    if isinstance(precise_stats, dict)
                                    else []
                                )
                                if str(sample or "").strip()
                            ]
                            dedupe_hits = int((precise_stats or {}).get("duplicate_bucket_hits", 0) or 0)
                            dedupe_tail = f"，同集/同范围已优选 {dedupe_hits} 条重复版本" if dedupe_hits > 0 else ""
                            await write_subscription_log(
                                (
                                    f"候选资源 #{index} 固定链接模式已启用文件级筛选"
                                    f"{'（运行期缓存）' if bool((precise_stats or {}).get('from_runtime_cache', False)) else ''}，"
                                    f"自动命中 {len(precise_ids)} 个剧集文件后再转存（避免整包导入）{dedupe_tail}"
                                ),
                                "info",
                            )
                        else:
                            skipped_subdir_candidates += 1
                            selection_reason = str((precise_stats or {}).get("reason", "") or "").strip() or "unknown"
                            selection_reason_label = _format_subscription_reason_chain(selection_reason)
                            scanned_dirs = int((precise_stats or {}).get("scanned_dirs", 0) or 0)
                            scanned_entries = int((precise_stats or {}).get("scanned_entries", 0) or 0)
                            covered_preview = _format_episode_preview(precise_missing_episode_values)
                            await write_subscription_log(
                                (
                                    f"候选资源 #{index} 固定链接模式未能在订阅子目录中识别目标剧集文件，"
                                    f"已跳过避免整包导入（目标 {covered_preview}，原因 {selection_reason_label}，"
                                    f"扫描目录 {scanned_dirs} 个，条目 {scanned_entries} 条）"
                                ),
                                "warn",
                            )
                            await maybe_wait_between_attempts()
                            continue
                if (
                    task["media_type"] == "tv"
                    and existing_episode_scan_ready
                    and candidate_link_type == "115share"
                    and candidate_episode_values
                    and (not forced_precise_selection_applied)
                ):
                    overlap_existing = any(episode_no in existing_folder_episodes for episode_no in candidate_episode_values)
                    missing_for_candidate = _candidate_missing_episode_values(
                        candidate,
                        existing_folder_episodes,
                        episode_upper_bound=single_season_episode_upper_bound,
                    )
                    skip_due_overlap_fallback = False
                    if overlap_existing and missing_for_candidate:
                        if use_fixed_share_link and fixed_share_runtime_manifest:
                            share_selection, selection_stats = _build_tv_share_selection_from_manifest(
                                fixed_share_runtime_manifest,
                                missing_for_candidate,
                                task=task,
                            )
                        else:
                            share_selection, selection_stats = await _build_tv_share_selection_for_missing_episodes(
                                cookie_115,
                                task,
                                item,
                                missing_for_candidate,
                                share_subdir_selection=resolved_subdir_selection,
                            )
                        selected_ids = share_selection.get("selected_ids", []) if isinstance(share_selection, dict) else []
                        if selected_ids:
                            job_payload["share_selection"] = share_selection
                            selected_share_episode_values = {
                                max(0, int(value or 0))
                                for value in (selection_stats.get("covered_episodes", []) if isinstance(selection_stats, dict) else [])
                                if max(0, int(value or 0)) > 0
                            }
                            selected_share_file_samples = [
                                str(sample or "").strip()
                                for sample in (
                                    selection_stats.get("selected_file_samples", [])
                                    if isinstance(selection_stats, dict)
                                    else []
                                )
                                if str(sample or "").strip()
                            ]
                            dedupe_hits = int((selection_stats or {}).get("duplicate_bucket_hits", 0) or 0)
                            dedupe_tail = f"，同集/同范围已优选 {dedupe_hits} 条重复版本" if dedupe_hits > 0 else ""
                            await write_subscription_log(
                                (
                                    f"候选资源 #{index} 检测到大包与目录重叠，缺失 {_format_episode_preview(missing_for_candidate)}；"
                                    f"已自动选中 {len(selected_ids)} 个文件精细转存{dedupe_tail}"
                                ),
                                "info",
                            )
                        else:
                            missing_ratio = len(missing_for_candidate) / max(1, len(candidate_episode_values))
                            if missing_ratio <= 0.35:
                                skipped_existing_candidates += 1
                                skip_due_overlap_fallback = True
                                await write_subscription_log(
                                    (
                                        f"候选资源 #{index} 与目录重叠度较高（缺失占比 {missing_ratio:.0%}），"
                                        "精细转存未命中，为避免重复集已跳过该整包候选"
                                    ),
                                    "warn",
                                )
                            else:
                                await write_subscription_log(
                                    (
                                        f"候选资源 #{index} 尝试按缺失集精细转存未命中（扫描目录 {int(selection_stats.get('scanned_dirs', 0) or 0)} 个，"
                                        f"条目 {int(selection_stats.get('scanned_entries', 0) or 0)} 条），回退整包转存"
                                    ),
                                    "warn",
                                )
                    if skip_due_overlap_fallback:
                        continue
                job_plans: List[Dict[str, Any]] = [
                    {
                        "payload": job_payload,
                        "savepath": candidate_savepath,
                        "season": candidate_season,
                        "selected_episode_values": set(selected_share_episode_values),
                    }
                ]
                normalized_job_selection = normalize_share_selection_meta(job_payload.get("share_selection", {}))
                if (
                    task["media_type"] == "tv"
                    and candidate_link_type == "115share"
                    and is_subscription_multi_season_mode(task)
                ):
                    split_groups, split_stats = _split_tv_share_selection_by_season(
                        task,
                        normalized_job_selection,
                        fixed_share_runtime_manifest,
                    )
                    if split_groups:
                        split_labels: List[str] = []
                        rebuilt_job_plans: List[Dict[str, Any]] = []
                        for split_group in split_groups:
                            group_selection = normalize_share_selection_meta(split_group.get("selection", {}))
                            group_ids = (
                                group_selection.get("selected_ids", [])
                                if isinstance(group_selection.get("selected_ids"), list)
                                else []
                            )
                            if not group_ids:
                                continue
                            group_season = max(0, int(split_group.get("season", 0) or 0))
                            group_episode_values = _clamp_episode_values(
                                split_group.get("episodes", set()),
                                episode_upper_bound=single_season_episode_upper_bound,
                            )
                            group_anchor_episode = max(group_episode_values) if group_episode_values else episode
                            group_savepath = build_subscription_tv_savepath(
                                task,
                                base_savepath,
                                season=group_season,
                                episode=group_anchor_episode,
                            ) or candidate_savepath
                            group_folder_id = str(savepath_folder_id_cache.get(group_savepath, "") or "").strip()
                            if not group_folder_id:
                                group_folder_id = await asyncio.to_thread(
                                    ensure_115_folder_id_by_path,
                                    cookie_115,
                                    group_savepath,
                                )
                                savepath_folder_id_cache[group_savepath] = str(group_folder_id or "").strip()
                            group_matched_monitor = match_monitor_task_for_savepath(
                                cfg,
                                group_savepath,
                                provider=provider,
                            )
                            group_monitor_task_name = str(group_matched_monitor.get("task_name", "") or "").strip()

                            group_payload = dict(job_payload)
                            group_payload["folder_id"] = group_folder_id
                            group_payload["savepath"] = group_savepath
                            group_payload["monitor_task_name"] = group_monitor_task_name
                            group_payload["auto_refresh"] = bool(group_monitor_task_name) and (not batch_refresh_enabled)
                            group_payload["extra"] = dict(job_payload.get("extra", {}))
                            group_payload["share_selection"] = group_selection

                            rebuilt_job_plans.append(
                                {
                                    "payload": group_payload,
                                    "savepath": group_savepath,
                                    "season": group_season,
                                    "selected_episode_values": group_episode_values,
                                }
                            )
                            season_label = f"S{group_season:02d}" if group_season > 0 else "未识别季"
                            split_labels.append(f"{season_label} {len(group_ids)} 个文件")

                        if rebuilt_job_plans:
                            job_plans = rebuilt_job_plans
                            split_text = " / ".join(split_labels[:6])
                            await write_subscription_log(
                                f"候选资源 #{index} 多季合一已按季拆分转存：{split_text}",
                                "info",
                            )
                            unresolved_count = int((split_stats or {}).get("unresolved_count", 0) or 0)
                            if unresolved_count > 0:
                                unresolved_samples = (
                                    (split_stats or {}).get("unresolved_samples", [])
                                    if isinstance((split_stats or {}).get("unresolved_samples", []), list)
                                    else []
                                )
                                sample_text = " / ".join(
                                    [str(name or "").strip()[:80] for name in unresolved_samples[:3] if str(name or "").strip()]
                                )
                                sample_tail = f"，示例：{sample_text}" if sample_text else ""
                                await write_subscription_log(
                                    (
                                        f"候选资源 #{index} 仍有 {unresolved_count} 个已选文件未能稳定识别季别，"
                                        "本次仅按已识别文件分季转存"
                                        f"{sample_tail}"
                                    ),
                                    "warn",
                                )

                if not job_plans:
                    failed_attempts += 1
                    last_failed_detail = "未生成可执行导入任务"
                    await write_subscription_log(
                        f"候选资源 #{index} 导入失败：{last_failed_detail}",
                        "warn",
                    )
                    await maybe_wait_between_attempts()
                    continue

                for plan_index, job_plan in enumerate(job_plans, start=1):
                    check_subscription_cancelled()
                    plan_payload = job_plan.get("payload", {}) if isinstance(job_plan.get("payload"), dict) else {}
                    plan_savepath = (
                        normalize_relative_path(str(job_plan.get("savepath", "") or "").strip()) or candidate_savepath
                    )
                    plan_season = max(0, int(job_plan.get("season", 0) or 0))
                    plan_selected_episode_values = _clamp_episode_values(
                        job_plan.get("selected_episode_values", set()),
                        episode_upper_bound=single_season_episode_upper_bound,
                    )
                    pre_attempt_existing_episodes = set(existing_folder_episodes)
                    duplicate_validation_applied = False
                    duplicate_verified_episode_values: Set[int] = set()

                    plan_job_id = create_resource_job(
                        item,
                        plan_payload,
                    )
                    if plan_job_id <= 0:
                        failed_attempts += 1
                        last_failed_detail = "创建导入任务失败"
                        await write_subscription_log(
                            f"候选资源 #{index} 导入失败：{last_failed_detail}",
                            "warn",
                        )
                        continue

                    batch_created_job_ids.add(plan_job_id)
                    plan_scope_label = ""
                    if len(job_plans) > 1:
                        season_tail = f"S{plan_season:02d}" if plan_season > 0 else "分组"
                        plan_scope_label = f"{season_tail} {plan_index}/{len(job_plans)} "
                    await write_subscription_log(
                        (
                            f"候选资源 #{index}（{episode_label}）{plan_scope_label}已创建导入任务 #{plan_job_id}，开始执行："
                            f"{str(item.get('title', '') or f'资源#{resource_id}').strip()[:96]}"
                        ),
                        "info",
                    )

                    job_runner = asyncio.create_task(run_resource_job(plan_job_id))
                    done, _ = await asyncio.wait({job_runner}, timeout=import_timeout_seconds)
                    if not done:
                        job_runner.add_done_callback(consume_background_task_result)
                        job_runner.cancel()
                        timed_out_attempts += 1
                        timeout_detail = f"执行超时（>{import_timeout_seconds} 秒）"
                        try:
                            await cancel_resource_job(plan_job_id, reason="timeout")
                        except Exception:
                            update_resource_job(
                                plan_job_id,
                                status="failed",
                                status_detail=timeout_detail,
                                finished_at=now_text(),
                            )
                            if resource_id > 0:
                                conn = open_db()
                                update_resource_item_status(conn, resource_id, "failed")
                                conn.commit()
                                conn.close()
                        failed_attempts += 1
                        last_failed_detail = timeout_detail
                        await write_subscription_log(
                            f"候选资源 #{index} 导入超时：{timeout_detail}，继续执行该候选的其他季目录",
                            "warn",
                        )
                        continue

                    await job_runner
                    latest_job = get_resource_job(plan_job_id, include_private=True)
                    latest_status = str((latest_job or {}).get("status", "") or "").strip().lower()
                    plan_auto_refresh = bool(
                        (latest_job or {}).get("auto_refresh", bool(str(plan_payload.get("monitor_task_name", "")).strip()))
                    )
                    if latest_status == "failed":
                        failed_attempts += 1
                        last_failed_detail = str((latest_job or {}).get("status_detail", "") or "资源导入失败").strip()
                        if (not use_fixed_share_link) and candidate_link_url and _is_subscription_invalid_link_error(last_failed_detail, candidate_link_type):
                            cache_meta = _record_subscription_invalid_link_cache(
                                candidate_link_url,
                                candidate_link_type,
                                last_failed_detail,
                            )
                            if cache_meta:
                                invalid_link_cache[candidate_link_url] = cache_meta
                                await write_subscription_log(
                                    f"候选资源 #{index} 链接已标记为失效，后续自动跳过（有效期至 {cache_meta.get('expires_at', '--')}）",
                                    "warn",
                                )
                        await write_subscription_log(
                            f"候选资源 #{index} 导入失败：{last_failed_detail}，继续执行该候选的其他季目录",
                            "warn",
                        )
                        continue

                    if (
                        latest_status in ("submitted", "completed")
                        and task["media_type"] == "tv"
                        and existing_episode_scan_ready
                        and candidate_link_type == "115share"
                        and is_115_share_receive_duplicate_response((latest_job or {}).get("response", {}))
                    ):
                        duplicate_validation_applied = True
                        verify_scan_result, verify_scan_episodes = await rescan_existing_tv_episodes()
                        verify_target_episodes = _clamp_episode_values(
                            (plan_selected_episode_values or candidate_episode_values) or set(),
                            episode_upper_bound=single_season_episode_upper_bound,
                        )
                        verification = _evaluate_duplicate_receive_validation(
                            verify_target_episodes=verify_target_episodes,
                            pre_attempt_existing_episodes=pre_attempt_existing_episodes,
                            verify_scan_episodes=verify_scan_episodes,
                            scan_scanned_dirs=int(verify_scan_result.get("scanned_dirs", 0) or 0),
                            scan_scanned_entries=int(verify_scan_result.get("scanned_entries", 0) or 0),
                            scan_failed_dirs=int(verify_scan_result.get("failed_dirs", 0) or 0),
                            scan_truncated=bool(verify_scan_result.get("truncated", False)),
                        )

                        if bool(verification.get("should_fail", False)) and verify_target_episodes:
                            retry_total = max(0, int(SUBSCRIPTION_DUPLICATE_VERIFY_RETRIES or 0))
                            retry_delay_seconds = max(0.0, float(SUBSCRIPTION_DUPLICATE_VERIFY_DELAY_SECONDS or 0))
                            if retry_total > 0:
                                await write_subscription_log(
                                    (
                                        f"候选资源 #{index} 收到 115 重复接收提示，目录暂未识别目标集，"
                                        f"将延迟复核 {retry_total} 次"
                                    ),
                                    "warn",
                                )
                                recovered_from_retry = False
                                for retry_index in range(1, retry_total + 1):
                                    check_subscription_cancelled()
                                    if retry_delay_seconds > 0:
                                        await asyncio.sleep(retry_delay_seconds)
                                    verify_scan_result, verify_scan_episodes = await rescan_existing_tv_episodes()
                                    verification = _evaluate_duplicate_receive_validation(
                                        verify_target_episodes=verify_target_episodes,
                                        pre_attempt_existing_episodes=pre_attempt_existing_episodes,
                                        verify_scan_episodes=verify_scan_episodes,
                                        scan_scanned_dirs=int(verify_scan_result.get("scanned_dirs", 0) or 0),
                                        scan_scanned_entries=int(verify_scan_result.get("scanned_entries", 0) or 0),
                                        scan_failed_dirs=int(verify_scan_result.get("failed_dirs", 0) or 0),
                                        scan_truncated=bool(verify_scan_result.get("truncated", False)),
                                    )
                                    if not bool(verification.get("should_fail", False)):
                                        recovered_from_retry = True
                                        await write_subscription_log(
                                            (
                                                f"候选资源 #{index} 重复接收第 {retry_index} 次复核通过，"
                                                "按幂等结果继续处理"
                                            ),
                                            "info",
                                        )
                                        break
                                if (not recovered_from_retry) and bool(verification.get("should_fail", False)):
                                    await write_subscription_log(
                                        (
                                            f"候选资源 #{index} 重复接收复核 {retry_total} 次仍未识别目标集，"
                                            "将回退为失败并继续尝试其他候选"
                                        ),
                                        "warn",
                                    )

                        verified_hits = {
                            max(0, int(item or 0))
                            for item in (
                                verification.get("verified_new_hits", [])
                                if isinstance(verification.get("verified_new_hits"), list)
                                else []
                            )
                            if max(0, int(item or 0)) > 0
                        }
                        present_hits = {
                            max(0, int(item or 0))
                            for item in (
                                verification.get("present_hits", [])
                                if isinstance(verification.get("present_hits"), list)
                                else []
                            )
                            if max(0, int(item or 0)) > 0
                        }
                        if bool(verification.get("should_fail", False)):
                            latest_status = "failed"
                            failed_attempts += 1
                            last_failed_detail = (
                                "115 提示文件已接收，但目标目录未发现对应剧集，已回退为失败以便继续尝试其他候选"
                            )
                            update_resource_job(
                                plan_job_id,
                                status="failed",
                                status_detail=last_failed_detail,
                                finished_at=now_text(),
                            )
                            if resource_id > 0:
                                conn = open_db()
                                update_resource_item_status(conn, resource_id, "failed")
                                conn.commit()
                                conn.close()
                            await write_subscription_log(
                                f"候选资源 #{index} 导入失败：{last_failed_detail}",
                                "warn",
                            )
                            continue

                        verify_scanned_entries = int(verify_scan_result.get("scanned_entries", 0) or 0)
                        if verify_scan_episodes:
                            existing_folder_episodes = set(verify_scan_episodes)
                        elif verify_scanned_entries <= 0:
                            existing_folder_episodes = set()
                        existing_episode_count = len(existing_folder_episodes)
                        existing_episode_scan_stats.update(
                            {
                                "existing_episode_scan_ready": True,
                                "existing_episode_count": existing_episode_count,
                                "existing_episode_max": max(existing_folder_episodes) if existing_folder_episodes else 0,
                                "existing_episode_scanned_dirs": int(verify_scan_result.get("scanned_dirs", 0) or 0),
                                "existing_episode_scanned_entries": int(verify_scan_result.get("scanned_entries", 0) or 0),
                                "existing_episode_failed_dirs": int(verify_scan_result.get("failed_dirs", 0) or 0),
                                "existing_episode_scan_truncated": bool(verify_scan_result.get("truncated", False)),
                            }
                        )
                        if verified_hits:
                            duplicate_verified_episode_values = set(verified_hits)
                            await write_subscription_log(
                                (
                                    f"候选资源 #{index} 收到 115 重复接收提示后已复核目标目录，"
                                    f"确认新增 {_format_episode_preview(verified_hits)}"
                                ),
                                "info",
                            )
                        elif present_hits:
                            await write_subscription_log(
                                (
                                    f"候选资源 #{index} 收到 115 重复接收提示；复核目录已存在 "
                                    f"{_format_episode_preview(present_hits)}，按幂等结果处理"
                                ),
                                "info",
                            )
                        elif verify_target_episodes:
                            verify_reason = str(verification.get("reason", "") or "").strip()
                            if verify_reason == "scan_not_reliable":
                                await write_subscription_log(
                                    (
                                        f"候选资源 #{index} 收到 115 重复接收提示；目录复核不可靠"
                                        "（扫描失败或截断），已按幂等结果放行"
                                    ),
                                    "warn",
                                )
                            elif verify_reason == "episode_unrecognized":
                                await write_subscription_log(
                                    (
                                        f"候选资源 #{index} 收到 115 重复接收提示；目录文件命名未能稳定识别目标集数，"
                                        "已按幂等结果放行"
                                    ),
                                    "warn",
                                )

                    if duplicate_validation_applied:
                        recorded_episode_values = set(duplicate_verified_episode_values)
                    else:
                        recorded_episode_values = _resolve_recorded_episode_values(
                            candidate,
                            plan_selected_episode_values,
                            episode_upper_bound=single_season_episode_upper_bound,
                        )
                    if recorded_episode_values and existing_episode_scan_ready:
                        existing_folder_episodes.update(recorded_episode_values)
                        existing_episode_count = len(existing_folder_episodes)
                        existing_episode_scan_stats["existing_episode_count"] = existing_episode_count
                        existing_episode_scan_stats["existing_episode_max"] = (
                            max(existing_folder_episodes) if existing_folder_episodes else 0
                        )

                    candidate_success_records.append(
                        {
                            "job_id": plan_job_id,
                            "savepath": plan_savepath,
                            "auto_refresh": plan_auto_refresh,
                            "reused_existing": False,
                            "recorded_episode_values": recorded_episode_values,
                            "selected_file_samples": list(selected_share_file_samples[:8]),
                            "ledger_season": (
                                plan_season
                                if plan_season > 0
                                else (
                                    candidate_season
                                    if candidate_season > 0
                                    else (
                                        max(1, int(task.get("season", 1) or 1))
                                        if not is_subscription_multi_season_mode(task)
                                        else 0
                                    )
                                )
                            ),
                        }
                    )

                if not candidate_success_records:
                    await maybe_wait_between_attempts()
                    continue

            if not candidate_success_records:
                await maybe_wait_between_attempts()
                continue

            job_id = int(candidate_success_records[0].get("job_id", 0) or 0)
            auto_refresh = any(bool(record.get("auto_refresh")) for record in candidate_success_records)
            reused_existing = all(bool(record.get("reused_existing")) for record in candidate_success_records)
            candidate_savepaths = {
                normalize_relative_path(str(record.get("savepath", "") or "").strip())
                for record in candidate_success_records
                if normalize_relative_path(str(record.get("savepath", "") or "").strip())
            }
            candidate_result_savepath = candidate_savepath
            if len(candidate_savepaths) == 1:
                candidate_result_savepath = next(iter(candidate_savepaths))
            elif len(candidate_savepaths) > 1:
                candidate_result_savepath = effective_savepath

            representative_ledger_season = max(
                0,
                int(candidate_success_records[0].get("ledger_season", candidate_season) or candidate_season or 0),
            )
            create_subscription_match(
                task_name=task_name,
                resource_id=resource_id,
                job_id=job_id,
                media_type=task.get("media_type", "movie"),
                season=representative_ledger_season,
                episode=episode,
                total_episodes=total_detected,
                score=score,
            )
            successful_count += 1
            max_total_detected = max(max_total_detected, total_detected)
            ledger_updated = False
            for success_record in candidate_success_records:
                success_job_id = max(0, int(success_record.get("job_id", 0) or 0))
                if success_job_id > 0:
                    successful_job_ids.append(success_job_id)
                recorded_episode_values = _clamp_episode_values(
                    success_record.get("recorded_episode_values", set()),
                    episode_upper_bound=single_season_episode_upper_bound,
                )
                if recorded_episode_values:
                    imported_episodes.update(recorded_episode_values)
                    if existing_episode_scan_ready:
                        existing_folder_episodes.update(recorded_episode_values)
                    if task["media_type"] == "tv":
                        latest_job_meta = get_resource_job(success_job_id, include_private=True)
                        selected_ids = (
                            latest_job_meta.get("selected_ids", [])
                            if isinstance(latest_job_meta, dict) and isinstance(latest_job_meta.get("selected_ids"), list)
                            else []
                        )
                        source_fp, content_fp = _build_subscription_episode_ledger_fingerprints(
                            item,
                            candidate,
                            recorded_episode_values,
                            selected_ids,
                        )
                        ledger_season = max(0, int(success_record.get("ledger_season", 0) or 0))
                        if ledger_season <= 0 and (not is_subscription_multi_season_mode(task)):
                            ledger_season = max(1, int(task.get("season", 1) or 1))
                        upsert_subscription_episode_ledger(
                            task_name=task_name,
                            episodes=recorded_episode_values,
                            media_type=task.get("media_type", "tv"),
                            season=ledger_season,
                            score=score,
                            resolution=max(0, int(candidate.get("resolution", 0) or 0)),
                            source_fp=source_fp,
                            content_fp=content_fp,
                            link_type=candidate_link_type,
                            link_url=candidate_link_url,
                            resource_id=resource_id,
                            job_id=success_job_id,
                        )
                        ledger_updated = True
            if existing_episode_scan_ready:
                existing_episode_count = len(existing_folder_episodes)
                existing_episode_scan_stats["existing_episode_count"] = existing_episode_count
                existing_episode_scan_stats["existing_episode_max"] = (
                    max(existing_folder_episodes) if existing_folder_episodes else 0
                )
            if ledger_updated:
                episode_ledger_rows = load_subscription_episode_ledger(task_name, include_stale=True)

            previous_auto_refresh = selected_auto_refresh
            if not selected_candidate:
                selected_candidate = candidate
                selected_item = item
                selected_job_id = job_id
                selected_auto_refresh = auto_refresh
                selected_reused_existing = reused_existing
                selected_job_savepath = candidate_result_savepath
            else:
                selected_episode = int(selected_candidate.get("episode", 0) or 0)
                selected_score = int(selected_candidate.get("score", 0) or 0)
                if episode > selected_episode or (episode == selected_episode and score > selected_score):
                    selected_candidate = candidate
                    selected_item = item
                    selected_job_id = job_id
                    selected_auto_refresh = auto_refresh
                    selected_reused_existing = reused_existing
                    selected_job_savepath = candidate_result_savepath
            selected_auto_refresh = bool(previous_auto_refresh or selected_auto_refresh or auto_refresh)
            candidate_recorded_episode_values = _clamp_episode_values(
                set().union(
                    *[
                        (
                            _clamp_episode_values(
                                record.get("recorded_episode_values", set()),
                                episode_upper_bound=single_season_episode_upper_bound,
                            )
                            if isinstance(record, dict)
                            else set()
                        )
                        for record in candidate_success_records
                    ]
                ),
                episode_upper_bound=single_season_episode_upper_bound,
            )
            candidate_file_samples = unique_preserve_order(
                [
                    str(sample or "").strip()
                    for record in candidate_success_records
                    if isinstance(record, dict)
                    for sample in (
                        record.get("selected_file_samples", [])
                        if isinstance(record.get("selected_file_samples", []), list)
                        else []
                    )
                    if str(sample or "").strip()
                ]
            )

            await write_subscription_log(
                (
                    f"候选资源 #{index} 导入成功：{str(item.get('title', '') or f'资源#{resource_id}').strip()}"
                    f"（评分 {score}）"
                    f"{'，命中 ' + _format_episode_preview(candidate_recorded_episode_values) if candidate_recorded_episode_values else ''}"
                    f"{'，文件：' + '；'.join(candidate_file_samples[:8]) if candidate_file_samples else ''}"
                ),
                "success",
            )
            if (
                batch_episode_import
                and task["media_type"] == "tv"
                and existing_episode_scan_ready
                and single_season_episode_upper_bound > 0
            ):
                required_episode_values = set(range(1, single_season_episode_upper_bound + 1))
                if required_episode_values.issubset(existing_folder_episodes):
                    await write_subscription_log(
                        f"目标目录已覆盖单季全部 E1-E{single_season_episode_upper_bound}，结束本轮候选尝试",
                        "info",
                    )
                    break
            if not batch_episode_import:
                break
            await maybe_wait_between_attempts()

        _subscription_stage_timer_enter(stage_timer, "finalize")
        if batch_refresh_enabled:
            batch_refresh_result = _finalize_subscription_batch_refresh(
                task_name=task_name,
                run_id=subscription_run_id,
                created_job_ids=batch_created_job_ids,
                cfg=cfg,
            )
            await write_subscription_log(
                (
                    f"批次收口汇总 | run_id={subscription_run_id} | 创建 {int(batch_refresh_result.get('created_jobs', 0) or 0)} 条 | "
                    f"成功入库 {int(batch_refresh_result.get('successful_jobs', 0) or 0)} 条 | "
                    f"可刷新 {int(batch_refresh_result.get('refresh_eligible_jobs', 0) or 0)} 条 | "
                    f"合并目录 {int(batch_refresh_result.get('grouped_targets', 0) or 0)} 组 | "
                    f"触发监控 {int(batch_refresh_result.get('triggered_groups', 0) or 0)} 组"
                ),
                "info",
            )
            if int(batch_refresh_result.get("missing_monitor_task_jobs", 0) or 0) > 0:
                await write_subscription_log(
                    (
                        f"批次收口异常：有 {int(batch_refresh_result.get('missing_monitor_task_jobs', 0) or 0)} 条导入任务未触发监控，"
                        "原因是目标监控任务不存在"
                    ),
                    "warn",
                )

        if not selected_candidate:
            if skipped_invalid_candidates > 0 and attempted_candidates <= 0:
                detail = f"候选资源命中失效链接缓存（已跳过 {skipped_invalid_candidates} 条），等待新资源发布"
            elif skipped_subdir_candidates > 0 and attempted_candidates <= 0:
                detail = f"候选资源未命中订阅子目录「{task_share_scope_label}」（已跳过 {skipped_subdir_candidates} 条），等待新资源发布"
            elif skipped_existing_candidates > 0 and attempted_candidates <= 0:
                detail = f"候选资源均已在目标目录存在（已跳过 {skipped_existing_candidates} 条），等待新集发布"
            elif skipped_ledger_candidates > 0 and attempted_candidates <= 0:
                detail = f"候选资源已被集数账本覆盖（已跳过 {skipped_ledger_candidates} 条），等待新集或更优资源"
            elif skipped_episode_candidates > 0 and attempted_candidates <= 0:
                detail = f"候选资源均为旧集（已跳过 {skipped_episode_candidates} 条），等待新集发布"
            elif failed_attempts > 0:
                detail = f"已尝试 {attempted_candidates} 个候选资源均失败，等待下次自动重试"
                if last_failed_detail:
                    detail += f"（最近失败：{last_failed_detail[:80]}）"
                if timed_out_attempts > 0:
                    detail += f"（超时 {timed_out_attempts} 条）"
            else:
                detail = "候选资源暂不可用，等待下次自动重试"
            if skipped_invalid_candidates > 0 and attempted_candidates > 0:
                detail += f"；失效链接缓存跳过 {skipped_invalid_candidates} 条"
            if skipped_subdir_candidates > 0 and attempted_candidates > 0:
                detail += f"；子目录过滤跳过 {skipped_subdir_candidates} 条"
            if skipped_ledger_candidates > 0 and attempted_candidates > 0:
                detail += f"；集数账本跳过 {skipped_ledger_candidates} 条"
            upsert_subscription_task_state(
                task_name,
                media_type=task.get("media_type", "movie"),
                status="waiting",
                progress=100,
                detail=detail,
                stats={
                    "matched": False,
                    "run_id": subscription_run_id,
                    "batch_refresh_enabled": batch_refresh_enabled,
                    "batch_created_jobs": int(batch_refresh_result.get("created_jobs", 0) or 0),
                    "batch_successful_jobs": int(batch_refresh_result.get("successful_jobs", 0) or 0),
                    "batch_refresh_eligible_jobs": int(batch_refresh_result.get("refresh_eligible_jobs", 0) or 0),
                    "batch_grouped_targets": int(batch_refresh_result.get("grouped_targets", 0) or 0),
                    "batch_triggered_groups": int(batch_refresh_result.get("triggered_groups", 0) or 0),
                    "batch_triggered_jobs": int(batch_refresh_result.get("triggered_jobs", 0) or 0),
                    "batch_missing_monitor_task_jobs": int(batch_refresh_result.get("missing_monitor_task_jobs", 0) or 0),
                    "last_episode": last_episode,
                    "total_episodes": known_total,
                    "attempted_candidates": attempted_candidates,
                    "failed_attempts": failed_attempts,
                    "timed_out_attempts": timed_out_attempts,
                    "skipped_episode_candidates": skipped_episode_candidates,
                    "skipped_existing_candidates": skipped_existing_candidates,
                    "skipped_ledger_candidates": skipped_ledger_candidates,
                    "skipped_invalid_candidates": skipped_invalid_candidates,
                    "skipped_subdir_candidates": skipped_subdir_candidates,
                    "scanned_candidates": scanned_candidates,
                    "max_scan_candidates": max_scan_candidates,
                    "use_fixed_share_link": use_fixed_share_link,
                    "fixed_link_channel_search": fixed_link_channel_search_enabled,
                    "share_link_url": task_share_link_url if use_fixed_share_link else "",
                    "share_subdir": task_share_subdir,
                    "share_subdir_cid": task_share_subdir_cid,
                    **existing_episode_scan_stats,
                    **search_stats,
                },
            )
            await write_subscription_log(detail, "warn")
            update_subscription_summary("等待资源", detail)
            return

        candidate = selected_candidate
        item = selected_item
        resource_id = int(item.get("id", 0) or 0)
        score = int(candidate.get("score", 0) or 0)
        episode = max(0, int(candidate.get("episode", 0) or 0))
        total_detected = max(0, int(candidate.get("total", 0) or 0))
        selected_season = max(0, int(candidate.get("season", 0) or 0))
        job_id = int(selected_job_id or 0)
        auto_refresh = bool(selected_auto_refresh)
        if batch_refresh_enabled and int(batch_refresh_result.get("triggered_groups", 0) or 0) > 0:
            auto_refresh = True
        imported_episode_list = sorted(imported_episodes)
        matched_display_title = pick_subscription_display_title(task, item, fallback=f"资源#{resource_id}")

        next_episode = last_episode
        if task["media_type"] == "tv" and imported_episode_list:
            next_episode = max(last_episode, imported_episode_list[-1])
        elif task["media_type"] == "tv" and episode > 0:
            next_episode = max(last_episode, episode)
        next_total = known_total or max_total_detected or total_detected
        if task["media_type"] == "tv" and (max_total_detected > 0 or total_detected > 0):
            _sync_task_total_episodes(task_name, max_total_detected or total_detected)

        successful_job_count = len(successful_job_ids)
        if selected_reused_existing:
            action_text = "复用导入任务"
        elif successful_job_count > 1:
            action_text = f"已创建并执行 {successful_job_count} 个分季导入任务"
        else:
            action_text = "已创建并执行导入任务"
        if task["media_type"] == "tv" and (successful_count > 1 or successful_job_count > 1):
            if imported_episode_list:
                if len(imported_episode_list) <= 8:
                    episode_summary = "、".join([f"E{episode_no}" for episode_no in imported_episode_list])
                else:
                    episode_summary = f"E{imported_episode_list[0]}-E{imported_episode_list[-1]}"
                batch_tail = f"（新增 {len(imported_episode_list)} 集：{episode_summary}）"
            else:
                batch_tail = ""
            batch_prefix = (
                f"本次分季导入 {successful_job_count} 个任务"
                if successful_count <= 1 and successful_job_count > 1
                else f"本次批量导入 {successful_count} 条候选资源"
            )
            detail = (
                f"{batch_prefix}{batch_tail}；"
                f"最新命中「{matched_display_title}」"
                f"（评分 {score}），{action_text} #{job_id}，保存到 {selected_job_savepath}"
            )
        else:
            detail = (
                f"命中「{matched_display_title}」"
                f"（评分 {score}），{action_text} #{job_id}，保存到 {selected_job_savepath}"
            )
        if selected_auto_refresh:
            if batch_refresh_enabled:
                triggered_groups = int(batch_refresh_result.get("triggered_groups", 0) or 0)
                successful_jobs = int(batch_refresh_result.get("successful_jobs", 0) or 0)
                refresh_eligible_jobs = int(batch_refresh_result.get("refresh_eligible_jobs", 0) or 0)
                missing_jobs = int(batch_refresh_result.get("missing_monitor_task_jobs", 0) or 0)
                if triggered_groups > 0:
                    detail += "；批次收口已统一触发监控任务"
                elif missing_jobs > 0:
                    detail += "；批次收口未触发监控（目标监控任务不存在）"
                elif successful_jobs > 0 and refresh_eligible_jobs <= 0:
                    detail += "；本批次成功入库但未命中监控任务，未触发监控"
                elif successful_jobs > 0:
                    detail += "；批次收口未触发监控"
                elif int(batch_refresh_result.get("created_jobs", 0) or 0) > 0:
                    detail += "；本批次无成功入库任务，未触发监控"
                else:
                    detail += "；未创建新导入任务，沿用历史任务状态"
            else:
                detail += "；自动触发监控任务"
        else:
            detail += "；当前目录未命中文件夹监控任务"

        status = "completed"
        if task["media_type"] == "tv" and next_total > 0 and next_episode >= next_total:
            status = "completed"
        upsert_subscription_task_state(
            task_name,
            media_type=task.get("media_type", "movie"),
            status=status,
            progress=100,
            detail=detail,
            last_success_at=now_text(),
            last_error="",
            last_episode=next_episode,
            total_episodes=next_total,
            matched_resource_id=resource_id,
            matched_resource_title=matched_display_title,
            matched_score=score,
            queued_job_id=job_id,
            stats={
                "matched": True,
                "run_id": subscription_run_id,
                "batch_refresh_enabled": batch_refresh_enabled,
                "batch_created_jobs": int(batch_refresh_result.get("created_jobs", 0) or 0),
                "batch_successful_jobs": int(batch_refresh_result.get("successful_jobs", 0) or 0),
                "batch_refresh_eligible_jobs": int(batch_refresh_result.get("refresh_eligible_jobs", 0) or 0),
                "batch_grouped_targets": int(batch_refresh_result.get("grouped_targets", 0) or 0),
                "batch_triggered_groups": int(batch_refresh_result.get("triggered_groups", 0) or 0),
                "batch_triggered_jobs": int(batch_refresh_result.get("triggered_jobs", 0) or 0),
                "batch_missing_monitor_task_jobs": int(batch_refresh_result.get("missing_monitor_task_jobs", 0) or 0),
                "score": score,
                "token_hits": int(candidate.get("token_hits", 0) or 0),
                "token_total": int(candidate.get("token_total", 0) or 0),
                "episode": episode,
                "season": selected_season,
                "total_episodes": next_total,
                "job_id": job_id,
                "job_ids": successful_job_ids[:40],
                "auto_refresh": auto_refresh,
                "matched_count": successful_count,
                "imported_episode_count": len(imported_episode_list),
                "imported_episodes": imported_episode_list[:80],
                "batch_episode_import": batch_episode_import,
                "attempted_candidates": attempted_candidates,
                "failed_attempts": failed_attempts,
                "timed_out_attempts": timed_out_attempts,
                "skipped_episode_candidates": skipped_episode_candidates,
                "skipped_existing_candidates": skipped_existing_candidates,
                "skipped_ledger_candidates": skipped_ledger_candidates,
                "skipped_invalid_candidates": skipped_invalid_candidates,
                "skipped_subdir_candidates": skipped_subdir_candidates,
                "scanned_candidates": scanned_candidates,
                "max_scan_candidates": max_scan_candidates,
                "existing_episode_count": existing_episode_count,
                "use_fixed_share_link": use_fixed_share_link,
                "fixed_link_channel_search": fixed_link_channel_search_enabled,
                "share_link_url": task_share_link_url if use_fixed_share_link else "",
                "share_subdir": task_share_subdir,
                "share_subdir_cid": task_share_subdir_cid,
                **existing_episode_scan_stats,
                **search_stats,
            },
        )
        await write_subscription_log(detail, "success")
        try:
            notify_result = await push_subscription_success_notification(
                cfg=cfg,
                task=task,
                item=item,
                effective_savepath=selected_job_savepath,
                job_id=job_id,
                successful_count=successful_count,
                imported_episode_list=imported_episode_list,
                baseline_last_episode=baseline_last_episode,
                next_episode=next_episode,
            )
            if bool(notify_result.get("pushed", False)):
                channel = str(notify_result.get("channel", "") or "").strip().lower()
                channel_label = "企业微信应用 API" if channel == "wecom_app" else "企业微信群机器人"
                notified_episodes = (
                    notify_result.get("episodes", [])
                    if isinstance(notify_result.get("episodes"), list)
                    else []
                )
                if notified_episodes:
                    await write_subscription_log(
                        f"更新通知已推送到{channel_label}（新增 {len(notified_episodes)} 集）",
                        "info",
                    )
                else:
                    await write_subscription_log(f"更新通知已推送到{channel_label}", "info")
        except Exception as notify_exc:
            await write_subscription_log(f"订阅成功通知推送失败：{notify_exc}", "warn")
        update_subscription_summary("执行成功", detail)
    except asyncio.CancelledError:
        detail = "任务已中断"
        upsert_subscription_task_state(
            task_name,
            media_type=task.get("media_type", "movie"),
            status="cancelled",
            progress=100,
            detail=detail,
            last_error=detail,
        )
        await write_subscription_log(detail, "warn")
        update_subscription_summary("任务中断", task_name)
    except Exception as exc:
        detail = str(exc)
        upsert_subscription_task_state(
            task_name,
            media_type=task.get("media_type", "movie"),
            status="failed",
            progress=100,
            detail=detail,
            last_error=detail,
        )
        await write_subscription_log(f"失败原因: {detail}", "error")
        update_subscription_summary("任务失败", detail)
    finally:
        _subscription_share_entry_runtime_cache_var.reset(share_runtime_cache_token)
        _subscription_share_entry_refreshed_keys_var.reset(share_refreshed_keys_token)
        tail_status = "idle"
        try:
            tail_state = load_subscription_task_state(task_name, task.get("media_type", "movie"))
            tail_status = str(tail_state.get("status", "idle") or "idle").strip().lower()
            if tail_status == "running":
                fallback_detail = "执行链路已结束但未写入最终状态，已自动回收（可重新运行）"
                upsert_subscription_task_state(
                    task_name,
                    media_type=task.get("media_type", "movie"),
                    status="failed",
                    progress=100,
                    detail=fallback_detail,
                    last_error=fallback_detail,
                )
                try:
                    await write_subscription_log(fallback_detail, "warn")
                except Exception:
                    pass
                tail_status = "failed"
        except Exception:
            pass

        # 优先回收运行态，避免日志写入异常导致 UI 长时间停在“运行中”。
        subscription_status["running"] = False
        subscription_status["current_task"] = ""
        subscription_control["cancel"] = False
        schedule_ui_state_push(0)
        _subscription_stage_timer_enter(stage_timer, "finalize")
        tail_status_label = {
            'completed': '执行成功',
            'cancelled': '已中断',
            'failed': '执行失败',
        }.get(tail_status, "已结束")
        try:
            stage_timing_line, total_timing_line = _build_subscription_stage_timing_log_lines(stage_timer)
            await write_subscription_log(stage_timing_line, "info")
            await write_subscription_log(total_timing_line, "info")
        except Exception:
            pass
        try:
            await write_subscription_log(
                f"━━━━━━━━━━【订阅结束 | {task_name} | {tail_status_label or '已结束'}】━━━━━━━━━━",
                "task-divider",
            )
        except Exception:
            pass
        reset_subscription_log_context(subscription_log_context_token)
        try:
            await start_next_subscription_job()
        except Exception:
            pass
