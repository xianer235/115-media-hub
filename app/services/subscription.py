import asyncio

from ..core import *  # noqa: F401,F403
from .resource import run_resource_job


def _load_subscription_task(cfg: Dict[str, Any], task_name: str) -> Dict[str, Any]:
    for raw_task in cfg.get("subscription_tasks", []) or []:
        task = normalize_subscription_task(raw_task or {})
        if task.get("name") == task_name:
            return task
    return {}


def get_subscription_task_episode_view(task_name: str) -> Dict[str, Any]:
    normalized_task_name = str(task_name or "").strip()
    if not normalized_task_name:
        raise RuntimeError("任务名称不能为空")

    cfg = get_config()
    task = _load_subscription_task(cfg, normalized_task_name)
    if not task:
        raise KeyError(normalized_task_name)

    if str(task.get("media_type", "movie") or "movie").strip().lower() != "tv":
        raise ValueError("仅电视剧任务支持集数视图")

    cookie_115 = str(cfg.get("cookie_115", "")).strip()
    if not cookie_115:
        raise RuntimeError("请先在参数配置页填写 115 Cookie")

    base_savepath = normalize_relative_path(str(task.get("savepath", "")).strip())
    if not base_savepath:
        raise RuntimeError("任务未配置保存路径")

    folder_id = ensure_115_folder_id_by_path(cookie_115, base_savepath)
    scan_result = _scan_115_existing_tv_episodes(cookie_115, folder_id, task)
    scan_episodes = scan_result.get("episodes", []) if isinstance(scan_result.get("episodes"), list) else []
    existing_episodes = sorted(
        {
            max(0, int(item or 0))
            for item in scan_episodes
            if 0 < max(0, int(item or 0)) <= 5000
        }
    )

    state = load_subscription_task_state(normalized_task_name, "tv")
    known_total = max(
        max(0, int(task.get("total_episodes", 0) or 0)),
        max(0, int(task.get("tmdb_total_episodes", 0) or 0)),
        max(0, int(state.get("total_episodes", 0) or 0)),
    )
    last_episode = max(0, int(state.get("last_episode", 0) or 0))
    max_episode = existing_episodes[-1] if existing_episodes else 0

    display_total = max(known_total, last_episode, max_episode)
    if display_total <= 0:
        display_total = 60
    elif known_total <= 0 and display_total < 24:
        display_total = 24
    display_total = max(1, min(1200, display_total))

    present_in_display = sum(1 for episode_no in existing_episodes if 1 <= episode_no <= display_total)
    missing_count = max(0, display_total - present_in_display)

    return {
        "task_name": normalized_task_name,
        "media_type": "tv",
        "savepath": base_savepath,
        "folder_id": str(folder_id or "").strip(),
        "existing_episodes": existing_episodes,
        "existing_count": len(existing_episodes),
        "max_episode": max_episode,
        "last_episode": last_episode,
        "total_episodes": known_total,
        "display_total_episodes": display_total,
        "missing_count": missing_count,
        "scan_stats": {
            "scanned_dirs": int(scan_result.get("scanned_dirs", 0) or 0),
            "scanned_entries": int(scan_result.get("scanned_entries", 0) or 0),
            "failed_dirs": int(scan_result.get("failed_dirs", 0) or 0),
            "truncated": bool(scan_result.get("truncated", False)),
        },
    }


def _sync_task_total_episodes(task_name: str, total_episodes: int) -> None:
    normalized_total = max(0, int(total_episodes or 0))
    if normalized_total <= 0:
        return
    cfg = get_config()
    tasks = cfg.get("subscription_tasks", []) if isinstance(cfg.get("subscription_tasks"), list) else []
    changed = False
    updated = []
    for raw_task in tasks:
        task = normalize_subscription_task(raw_task or {})
        if task.get("name") == task_name and int(task.get("total_episodes", 0) or 0) <= 0:
            task["total_episodes"] = normalized_total
            changed = True
        updated.append(task)
    if changed:
        cfg["subscription_tasks"] = updated
        save_config(cfg)


def _build_subscription_search_keywords(task: Dict[str, Any], limit: int = 4) -> List[str]:
    title = re.sub(r"\s+", " ", str(task.get("title", "") or "").strip())
    aliases = task.get("aliases", []) if isinstance(task.get("aliases"), list) else []
    tmdb_title = re.sub(r"\s+", " ", str(task.get("tmdb_title", "") or "").strip())
    tmdb_original_title = re.sub(r"\s+", " ", str(task.get("tmdb_original_title", "") or "").strip())
    tmdb_aliases = task.get("tmdb_aliases", []) if isinstance(task.get("tmdb_aliases"), list) else []
    media_type = str(task.get("media_type", "movie") or "movie").strip().lower()
    anime_mode = bool(task.get("anime_mode", False))
    year = normalize_tmdb_year(task.get("year", "")) or normalize_tmdb_year(task.get("tmdb_year", ""))
    season = max(1, int(task.get("season", 1) or 1))

    keywords: List[str] = []
    if title:
        keywords.append(title)
        if media_type == "movie" and year and re.fullmatch(r"(19|20)\d{2}", year):
            keywords.append(f"{title} {year}")
        if media_type == "tv" and season > 1:
            keywords.append(f"{title} S{season:02d}")
            keywords.append(f"{title} 第{season}季")
        if media_type == "tv" and anime_mode:
            keywords.append(f"{title} 动漫")
    if tmdb_title:
        keywords.append(tmdb_title)
        if media_type == "movie" and year:
            keywords.append(f"{tmdb_title} {year}")
        if media_type == "tv" and season > 1:
            keywords.append(f"{tmdb_title} S{season:02d}")
    if tmdb_original_title:
        keywords.append(tmdb_original_title)
    for alias in tmdb_aliases:
        alias_keyword = re.sub(r"\s+", " ", str(alias or "").strip())
        if alias_keyword:
            keywords.append(alias_keyword)
    for alias in aliases:
        alias_keyword = re.sub(r"\s+", " ", str(alias or "").strip())
        if alias_keyword:
            keywords.append(alias_keyword)

    seen: Set[str] = set()
    normalized_keywords: List[str] = []
    for keyword in keywords:
        marker = keyword.lower()
        if marker in seen:
            continue
        seen.add(marker)
        normalized_keywords.append(keyword)
    return normalized_keywords[: max(1, int(limit or 6))]


def _merge_subscription_search_errors(errors: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    merged: List[Dict[str, str]] = []
    seen: Set[str] = set()
    for raw in errors:
        payload = raw if isinstance(raw, dict) else {}
        channel_id = str(payload.get("channel_id", "") or "").strip()
        message = str(payload.get("message", "") or "").strip()
        if not channel_id and not message:
            continue
        key = f"{channel_id}|{message}"
        if key in seen:
            continue
        seen.add(key)
        merged.append(
            {
                "channel_id": channel_id,
                "name": str(payload.get("name", "") or channel_id).strip(),
                "message": message,
            }
        )
    return merged


def _expand_episode_values(start_episode: int, end_episode: int, max_expand: int = 400) -> Set[int]:
    start = max(0, int(start_episode or 0))
    end = max(0, int(end_episode or 0))
    if start <= 0 and end <= 0:
        return set()
    if start <= 0:
        start = end
    if end <= 0:
        end = start
    if end < start:
        start, end = end, start
    total_count = end - start + 1
    if total_count <= 0:
        return set()
    if total_count > max(1, int(max_expand or 400)):
        return {start, end}
    return {episode for episode in range(start, end + 1) if 0 < episode <= 5000}


def _extract_task_episodes_from_name(task: Dict[str, Any], name: str, max_expand: int = 400) -> Set[int]:
    normalized_name = str(name or "").strip()
    if not normalized_name:
        return set()
    meta = parse_resource_episode_meta({"title": normalized_name, "raw_text": normalized_name})
    episode = max(0, int(meta.get("episode", 0) or 0))
    range_start = max(0, int(meta.get("range_start", 0) or 0))
    range_end = max(0, int(meta.get("range_end", 0) or 0))
    if normalize_tmdb_episode_mode(task.get("tmdb_episode_mode", "seasonal")) == "absolute":
        if range_end > 0:
            expanded = _expand_episode_values(range_start, range_end, max_expand=max_expand)
            if expanded:
                return expanded
        return {episode} if 0 < episode <= 5000 else set()

    season = max(0, int(meta.get("season", 0) or 0))
    target_season = max(1, int(task.get("season", 1) or 1))
    if season > 0 and season != target_season:
        return set()
    if range_end > 0:
        expanded = _expand_episode_values(range_start, range_end, max_expand=max_expand)
        if expanded:
            return expanded
        return {range_end} if 0 < range_end <= 5000 else set()
    return {episode} if 0 < episode <= 5000 else set()


def _candidate_episode_values(candidate: Dict[str, Any], max_expand: int = 400) -> Set[int]:
    payload = candidate if isinstance(candidate, dict) else {}
    episode = max(0, int(payload.get("episode", 0) or 0))
    range_start = max(0, int(payload.get("range_start", 0) or 0))
    range_end = max(0, int(payload.get("range_end", 0) or 0))
    values: Set[int] = set()
    if range_end > 0:
        values.update(_expand_episode_values(range_start, range_end, max_expand=max_expand))
        if not values and range_end > 0:
            values.add(range_end)
    if episode > 0:
        values.add(episode)
    return {item for item in values if 0 < item <= 5000}


def _candidate_anchor_episode(candidate: Dict[str, Any]) -> int:
    values = _candidate_episode_values(candidate, max_expand=200)
    if values:
        return max(values)
    return max(0, int((candidate or {}).get("episode", 0) or 0))


def _format_candidate_episode_label(candidate: Dict[str, Any]) -> str:
    payload = candidate if isinstance(candidate, dict) else {}
    range_start = max(0, int(payload.get("range_start", 0) or 0))
    range_end = max(0, int(payload.get("range_end", 0) or 0))
    episode = max(0, int(payload.get("episode", 0) or 0))
    if range_start > 0 and range_end > 0:
        if range_end < range_start:
            range_start, range_end = range_end, range_start
        if range_start == range_end:
            return f"E{range_start}"
        return f"E{range_start}-E{range_end}"
    if episode > 0:
        return f"E{episode}"
    return "未知集数"


def _scan_115_existing_tv_episodes(
    cookie: str,
    root_folder_id: str,
    task: Dict[str, Any],
    max_depth: int = 3,
    max_dirs: int = 120,
    max_entries: int = 3000,
) -> Dict[str, Any]:
    normalized_cookie = str(cookie or "").strip()
    if not normalized_cookie:
        raise RuntimeError("115 Cookie 未配置")

    start_cid = str(root_folder_id or "0").strip() or "0"
    queue: List[Tuple[str, int]] = [(start_cid, 0)]
    visited: Set[str] = set()
    episodes: Set[int] = set()
    scanned_dirs = 0
    scanned_entries = 0
    failed_dirs = 0

    while queue and scanned_dirs < max_dirs and scanned_entries < max_entries:
        cid, depth = queue.pop(0)
        if cid in visited:
            continue
        visited.add(cid)
        try:
            entries = list_115_entries(normalized_cookie, cid)
        except Exception:
            failed_dirs += 1
            continue

        scanned_dirs += 1
        for entry in entries:
            if scanned_entries >= max_entries:
                break
            scanned_entries += 1
            name = str(entry.get("name", "") or "").strip()
            if not name:
                continue
            parsed_episodes = _extract_task_episodes_from_name(task, name)
            if parsed_episodes:
                episodes.update(parsed_episodes)

            if bool(entry.get("is_dir")) and depth < max_depth:
                child_cid = str(entry.get("id", "") or entry.get("cid", "") or "").strip()
                if child_cid and child_cid not in visited:
                    queue.append((child_cid, depth + 1))

    sorted_episodes = sorted(episodes)
    return {
        "episodes": sorted_episodes,
        "max_episode": sorted_episodes[-1] if sorted_episodes else 0,
        "scanned_dirs": scanned_dirs,
        "scanned_entries": scanned_entries,
        "failed_dirs": failed_dirs,
        "truncated": bool(queue) or scanned_dirs >= max_dirs or scanned_entries >= max_entries,
    }


def _format_episode_preview(episodes: Set[int], max_items: int = 8) -> str:
    ordered = sorted(max(0, int(item or 0)) for item in episodes if int(item or 0) > 0)
    if not ordered:
        return "--"
    if len(ordered) <= max_items:
        return "、".join([f"E{episode}" for episode in ordered])
    head = "、".join([f"E{episode}" for episode in ordered[:3]])
    tail = "、".join([f"E{episode}" for episode in ordered[-2:]])
    return f"{head} ... {tail}"


def _prioritize_tv_candidates_by_missing_episodes(
    candidates: List[Dict[str, Any]],
    existing_episodes: Set[int],
    baseline_last_episode: int,
    prefer_backfill: bool,
) -> List[Dict[str, Any]]:
    normalized_existing = {max(0, int(item or 0)) for item in existing_episodes if int(item or 0) > 0}
    if not normalized_existing:
        return list(candidates)

    without_episode: List[Dict[str, Any]] = []
    backfill_candidates: List[Dict[str, Any]] = []
    fresh_candidates: List[Dict[str, Any]] = []
    existing_candidates: List[Dict[str, Any]] = []
    for candidate in candidates:
        episode_values = _candidate_episode_values(candidate)
        if not episode_values:
            without_episode.append(candidate)
            continue
        anchor_episode = max(episode_values)
        has_missing_coverage = any(episode_no not in normalized_existing for episode_no in episode_values)
        if not has_missing_coverage:
            existing_candidates.append(candidate)
            continue
        if baseline_last_episode > 0 and anchor_episode <= baseline_last_episode:
            backfill_candidates.append(candidate)
            continue
        fresh_candidates.append(candidate)

    backfill_candidates.sort(
        key=lambda item: (
            _candidate_anchor_episode(item),
            -int(item.get("score", 0) or 0),
            get_resource_item_sort_key(item.get("item", {})),
        )
    )
    fresh_candidates.sort(
        key=lambda item: (
            _candidate_anchor_episode(item),
            int(item.get("score", 0) or 0),
            get_resource_item_sort_key(item.get("item", {})),
        ),
        reverse=True,
    )
    existing_candidates.sort(
        key=lambda item: (
            _candidate_anchor_episode(item),
            int(item.get("score", 0) or 0),
            get_resource_item_sort_key(item.get("item", {})),
        ),
        reverse=True,
    )

    prioritized_with_episode = (
        (backfill_candidates + fresh_candidates)
        if prefer_backfill
        else (fresh_candidates + backfill_candidates)
    )
    return prioritized_with_episode + without_episode + existing_candidates


async def find_subscription_task_match_candidate_by_search(
    task: Dict[str, Any], last_episode: int = 0
) -> Dict[str, Any]:
    query_tokens = build_subscription_query_tokens(task)
    if not query_tokens:
        return {"candidate": {}, "keywords": [], "stats": {}, "errors": []}

    keywords = _build_subscription_search_keywords(task, limit=6)
    all_items: List[Dict[str, Any]] = []
    all_errors: List[Dict[str, Any]] = []
    searched_sources = 0
    matched_channels = 0
    pages_scanned = 0

    for keyword in keywords:
        check_subscription_cancelled()
        search_meta = await search_resource_sources(keyword)
        all_items.extend(search_meta.get("items", []) if isinstance(search_meta.get("items"), list) else [])
        all_errors.extend(search_meta.get("errors", []) if isinstance(search_meta.get("errors"), list) else [])
        searched_sources += max(0, int(search_meta.get("searched_sources", 0) or 0))
        matched_channels += max(0, int(search_meta.get("matched_channels", 0) or 0))
        pages_scanned += max(0, int(search_meta.get("pages_scanned", 0) or 0))

    deduped_items = dedupe_resource_item_dicts(all_items)
    deduped_items.sort(key=get_resource_item_sort_key, reverse=True)
    merged_errors = _merge_subscription_search_errors(all_errors)
    min_score = max(30, min(100, int(task.get("min_score", SUBSCRIPTION_MIN_SCORE) or SUBSCRIPTION_MIN_SCORE)))
    persisted_items: List[Dict[str, Any]] = []
    ensure_db()
    conn = open_db()
    try:
        for raw_item in deduped_items:
            item = raw_item if isinstance(raw_item, dict) else {}
            item_id, _ = upsert_resource_item(conn, item)
            if item_id <= 0:
                continue
            normalized_item = {**item, "id": item_id}
            extra = normalized_item.get("extra") if isinstance(normalized_item.get("extra"), dict) else {}
            source_post_id = str(
                normalized_item.get("source_post_id", "") or extra.get("source_post_id", "")
            ).strip()
            if source_post_id:
                normalized_item["source_post_id"] = source_post_id
            persisted_items.append(normalized_item)
        conn.commit()
    finally:
        conn.close()

    candidates: List[Dict[str, Any]] = []
    relaxed_candidates: List[Dict[str, Any]] = []
    scored_candidates: List[Dict[str, Any]] = []
    supported_items = 0
    unsupported_items = 0
    media_guard_filtered = 0
    media_guard_reasons: Dict[str, int] = {}
    supported_link_types = {"magnet", "115share"}
    for item in persisted_items:
        link_url = str(item.get("link_url", "") or "").strip()
        link_type = resolve_resource_link_type(item.get("link_type", ""), link_url)
        if link_type not in supported_link_types:
            unsupported_items += 1
            continue
        media_match, media_reason = match_subscription_media_type(task, item)
        if not media_match:
            media_guard_filtered += 1
            reason_key = str(media_reason or "unknown").strip() or "unknown"
            media_guard_reasons[reason_key] = int(media_guard_reasons.get(reason_key, 0) or 0) + 1
            continue
        supported_items += 1
        item_id = int(item.get("id", 0) or 0)
        if has_subscription_match(task.get("name", ""), item_id):
            continue
        scored = score_subscription_candidate(task, item, query_tokens, last_episode)
        scored_candidates.append(scored)
        if scored["score"] < min_score:
            media_type = str(task.get("media_type", "movie") or "movie").strip().lower()
            if media_type == "tv":
                episode_no = int(scored.get("episode", 0) or 0)
                token_hits = int(scored.get("token_hits", 0) or 0)
                if episode_no > 0 and token_hits > 0:
                    relaxed_candidates.append(scored)
            continue
        candidates.append(scored)

    media_type = str(task.get("media_type", "movie") or "movie").strip().lower()
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
    scored_candidates.sort(
        key=lambda candidate: (
            int(candidate.get("score", 0) or 0),
            get_resource_item_sort_key(candidate.get("item", {})),
        ),
        reverse=True,
    )

    relaxed_score_mode = False
    if not candidates and media_type == "tv" and relaxed_candidates:
        relaxed_candidates.sort(
            key=lambda candidate: (
                int(candidate.get("episode", 0) or 0),
                int(candidate.get("score", 0) or 0),
                get_resource_item_sort_key(candidate.get("item", {})),
            ),
            reverse=True,
        )
        candidates = relaxed_candidates[: min(20, len(relaxed_candidates))]
        relaxed_score_mode = True

    return {
        "candidate": candidates[0] if candidates else {},
        "candidates": candidates[: min(20, len(candidates))],
        "keywords": keywords,
        "errors": merged_errors,
        "stats": {
            "search_keywords": len(keywords),
            "searched_sources": searched_sources,
            "matched_channels": matched_channels,
            "pages_scanned": pages_scanned,
            "raw_items": len(all_items),
            "deduped_items": len(deduped_items),
            "persisted_items": len(persisted_items),
            "supported_items": supported_items,
            "unsupported_items": unsupported_items,
            "media_guard_filtered": media_guard_filtered,
            "media_guard_reasons": media_guard_reasons,
            "scored_items": len(scored_candidates),
            "scored_candidates": len(candidates),
            "relaxed_score_mode": relaxed_score_mode,
            "relaxed_candidates": len(relaxed_candidates),
            "search_errors": len(merged_errors),
            "best_score": int(scored_candidates[0].get("score", 0) or 0) if scored_candidates else 0,
        },
    }


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

    if subscription_status["running"]:
        return

    ensure_db()
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
    )

    try:
        await write_subscription_log(
            f"━━━━━━━━━━【订阅开始 | {task_name} | {format_subscription_trigger(trigger)}】━━━━━━━━━━",
            "task-divider",
        )
        await write_subscription_log(
            f"类型: {'电影' if task['media_type'] == 'movie' else '电视剧'} | 标题: {task['title']} | 保存路径: {task['savepath']}",
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
            configured_total = max(
                0,
                int(
                    task.get("total_episodes", 0)
                    or task.get("tmdb_total_episodes", 0)
                    or 0
                ),
            )
            tv_mode_text = "动漫兼容" if bool(task.get("anime_mode", False)) else "标准剧集"
            if normalize_tmdb_episode_mode(task.get("tmdb_episode_mode", "seasonal")) == "absolute":
                tv_mode_text += " / 绝对集序"
            await write_subscription_log(
                f"季: S{int(task.get('season', 1) or 1):02d} | 总集数: {configured_total or '自动识别'} | 模式: {tv_mode_text}",
                "info",
            )
        check_subscription_cancelled()

        state = load_subscription_task_state(task_name, task.get("media_type", "movie"))
        last_episode = max(0, int(state.get("last_episode", 0) or 0))
        known_total = max(
            0,
            int(
                task.get("total_episodes", 0)
                or task.get("tmdb_total_episodes", 0)
                or state.get("total_episodes", 0)
                or 0
            ),
        )
        completed_locked = task["media_type"] == "tv" and known_total > 0 and last_episode >= known_total

        if completed_locked:
            await write_subscription_log(
                f"当前记录为已完结（{last_episode}/{known_total}），本次仍会检查启用频道是否有重发/更优资源",
                "warn",
            )

        upsert_subscription_task_state(task_name, status="running", progress=15, detail="正在主动搜索启用频道资源")
        check_subscription_cancelled()
        search_result = await find_subscription_task_match_candidate_by_search(task, last_episode=last_episode)
        search_stats = search_result.get("stats", {}) if isinstance(search_result.get("stats"), dict) else {}
        search_errors = search_result.get("errors", []) if isinstance(search_result.get("errors"), list) else []
        search_keywords = search_result.get("keywords", []) if isinstance(search_result.get("keywords"), list) else []
        await write_subscription_log(
            "主动搜索关键词: " + " / ".join(search_keywords or [str(task.get("title", "")).strip() or "--"]),
            "info",
        )
        await write_subscription_log(
            (
                f"主动搜索完成：频道检索 {int(search_stats.get('searched_sources', 0) or 0)} 次，"
                f"命中频道 {int(search_stats.get('matched_channels', 0) or 0)} 个，"
                f"扫描页面 {int(search_stats.get('pages_scanned', 0) or 0)} 页，"
                f"候选资源 {int(search_stats.get('deduped_items', 0) or 0)} 条，"
                f"可导入资源 {int(search_stats.get('supported_items', 0) or 0)} 条"
            ),
            "info",
        )
        if int(search_stats.get("unsupported_items", 0) or 0) > 0:
            await write_subscription_log(
                f"已过滤 {int(search_stats.get('unsupported_items', 0) or 0)} 条不支持链接（仅支持 magnet / 115 分享）",
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
        if bool(search_stats.get("relaxed_score_mode", False)):
            await write_subscription_log(
                (
                    f"评分放宽模式已启用：有 {int(search_stats.get('relaxed_candidates', 0) or 0)} 条电视剧候选因阈值过低未达标，"
                    "已改为先尝试候选再按集数去重判断"
                ),
                "warn",
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

        upsert_subscription_task_state(task_name, status="running", progress=25, detail="频道搜索完成，正在匹配评分")
        check_subscription_cancelled()
        ranked_candidates = search_result.get("candidates", []) if isinstance(search_result.get("candidates"), list) else []
        if not ranked_candidates:
            legacy_candidate = search_result.get("candidate", {}) if isinstance(search_result.get("candidate"), dict) else {}
            if legacy_candidate:
                ranked_candidates = [legacy_candidate]
        if not ranked_candidates:
            if completed_locked:
                detail = f"已完结（{last_episode}/{known_total}），未发现可更新资源"
                status = "completed"
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
        check_subscription_cancelled()
        upsert_subscription_task_state(task_name, status="running", progress=45, detail="正在准备目标目录")
        cookie_115 = str(cfg.get("cookie_115", "")).strip()
        folder_id = await asyncio.to_thread(
            ensure_115_folder_id_by_path,
            cookie_115,
            effective_savepath,
        )
        matched_monitor = match_monitor_task_for_savepath(cfg, effective_savepath)
        monitor_task_name = str(matched_monitor.get("task_name", "") or "").strip()

        existing_folder_episodes: Set[int] = set()
        existing_episode_scan_stats: Dict[str, Any] = {}
        existing_episode_scan_ready = False
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
                existing_folder_episodes = {
                    max(0, int(item or 0))
                    for item in scan_episodes
                    if max(0, int(item or 0)) > 0
                }
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
            )
            missing_episode_candidates = 0
            existing_episode_candidates = 0
            for candidate in attempt_candidates:
                episode_values = _candidate_episode_values(candidate)
                if not episode_values:
                    continue
                if episode_values.issubset(existing_folder_episodes):
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
        last_failed_detail = ""
        selected_candidate: Dict[str, Any] = {}
        selected_item: Dict[str, Any] = {}
        selected_job_id = 0
        selected_auto_refresh = False
        selected_reused_existing = False
        baseline_last_episode = last_episode
        imported_episodes: Set[int] = set()
        successful_count = 0
        max_total_detected = 0
        successful_job_ids: List[int] = []
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

        for index, candidate in enumerate(attempt_candidates, start=1):
            if attempted_candidates >= max_attempts:
                break
            if scanned_candidates >= max_scan_candidates:
                break
            scanned_candidates += 1
            check_subscription_cancelled()
            item = candidate.get("item", {}) if isinstance(candidate.get("item"), dict) else {}
            resource_id = int(item.get("id", 0) or 0)
            if resource_id <= 0:
                continue
            score = int(candidate.get("score", 0) or 0)
            episode = max(0, int(candidate.get("episode", 0) or 0))
            total_detected = max(0, int(candidate.get("total", 0) or 0))
            candidate_episode_values = _candidate_episode_values(candidate)
            episode_label = _format_candidate_episode_label(candidate)

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
                is_old_episode = episode < baseline_last_episode
                is_same_episode_blocked = episode == baseline_last_episode and not completed_locked
                range_start = max(0, int(candidate.get("range_start", 0) or 0))
                range_end = max(0, int(candidate.get("range_end", 0) or 0))
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

            existing = find_existing_resource_job(item, effective_savepath)
            job_id = 0
            auto_refresh = bool(monitor_task_name)
            reused_existing = False
            if existing:
                job_id = int(existing.get("id", 0) or 0)
                existing_status = str(existing.get("status", "") or "").strip().lower()
                if existing_status == "failed":
                    failed_attempts += 1
                    last_failed_detail = str(existing.get("status_detail", "") or f"任务 #{job_id} 失败").strip()
                    await write_subscription_log(
                        f"候选资源 #{index} 历史任务 #{job_id} 失败：{last_failed_detail}，继续尝试下一个",
                        "warn",
                    )
                    await maybe_wait_between_attempts()
                    continue
                auto_refresh = bool(existing.get("auto_refresh"))
                reused_existing = True
                await write_subscription_log(f"候选资源 #{index} 命中历史任务 #{job_id}，复用执行记录", "warn")
            else:
                job_id = create_resource_job(
                    item,
                    {
                        "folder_id": folder_id,
                        "savepath": effective_savepath,
                        "sharetitle": "",
                        "monitor_task_name": monitor_task_name,
                        "refresh_delay_seconds": 4,
                        "auto_refresh": bool(monitor_task_name),
                    },
                )
                await write_subscription_log(
                    (
                        f"候选资源 #{index}（{episode_label}）已创建导入任务 #{job_id}，开始执行："
                        f"{str(item.get('title', '') or f'资源#{resource_id}').strip()[:96]}"
                    ),
                    "info",
                )
                try:
                    await asyncio.wait_for(run_resource_job(job_id), timeout=import_timeout_seconds)
                except asyncio.TimeoutError:
                    timed_out_attempts += 1
                    timeout_detail = f"执行超时（>{import_timeout_seconds} 秒）"
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
                        f"候选资源 #{index} 导入超时：{timeout_detail}，继续尝试下一个",
                        "warn",
                    )
                    await maybe_wait_between_attempts()
                    continue
                latest_job = get_resource_job(job_id, include_private=True)
                latest_status = str((latest_job or {}).get("status", "") or "").strip().lower()
                auto_refresh = bool((latest_job or {}).get("auto_refresh", bool(monitor_task_name)))
                if latest_status == "failed":
                    failed_attempts += 1
                    last_failed_detail = str((latest_job or {}).get("status_detail", "") or "资源导入失败").strip()
                    await write_subscription_log(
                        f"候选资源 #{index} 导入失败：{last_failed_detail}，继续尝试下一个",
                        "warn",
                    )
                    await maybe_wait_between_attempts()
                    continue

            create_subscription_match(
                task_name=task_name,
                resource_id=resource_id,
                job_id=job_id,
                media_type=task.get("media_type", "movie"),
                season=max(0, int(candidate.get("season", 0) or 0)),
                episode=episode,
                total_episodes=total_detected,
                score=score,
            )
            successful_count += 1
            max_total_detected = max(max_total_detected, total_detected)
            successful_job_ids.append(job_id)
            if candidate_episode_values:
                imported_episodes.update(candidate_episode_values)
                if existing_episode_scan_ready:
                    existing_folder_episodes.update(candidate_episode_values)
            elif episode > 0:
                imported_episodes.add(episode)
                if existing_episode_scan_ready:
                    existing_folder_episodes.add(episode)

            previous_auto_refresh = selected_auto_refresh
            if not selected_candidate:
                selected_candidate = candidate
                selected_item = item
                selected_job_id = job_id
                selected_auto_refresh = auto_refresh
                selected_reused_existing = reused_existing
            else:
                selected_episode = int(selected_candidate.get("episode", 0) or 0)
                selected_score = int(selected_candidate.get("score", 0) or 0)
                if episode > selected_episode or (episode == selected_episode and score > selected_score):
                    selected_candidate = candidate
                    selected_item = item
                    selected_job_id = job_id
                    selected_auto_refresh = auto_refresh
                    selected_reused_existing = reused_existing
            selected_auto_refresh = bool(previous_auto_refresh or selected_auto_refresh or auto_refresh)

            await write_subscription_log(
                f"候选资源 #{index} 导入成功：{str(item.get('title', '') or f'资源#{resource_id}').strip()}（评分 {score}）",
                "success",
            )
            if not batch_episode_import:
                break
            await maybe_wait_between_attempts()

        if not selected_candidate:
            if skipped_existing_candidates > 0 and attempted_candidates <= 0:
                detail = f"候选资源均已在目标目录存在（已跳过 {skipped_existing_candidates} 条），等待新集发布"
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
            upsert_subscription_task_state(
                task_name,
                media_type=task.get("media_type", "movie"),
                status="waiting",
                progress=100,
                detail=detail,
                stats={
                    "matched": False,
                    "last_episode": last_episode,
                    "total_episodes": known_total,
                    "attempted_candidates": attempted_candidates,
                    "failed_attempts": failed_attempts,
                    "timed_out_attempts": timed_out_attempts,
                    "skipped_episode_candidates": skipped_episode_candidates,
                    "skipped_existing_candidates": skipped_existing_candidates,
                    "scanned_candidates": scanned_candidates,
                    "max_scan_candidates": max_scan_candidates,
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
        season = max(0, int(candidate.get("season", 0) or 0))
        job_id = int(selected_job_id or 0)
        auto_refresh = bool(selected_auto_refresh)
        imported_episode_list = sorted(imported_episodes)

        next_episode = last_episode
        if task["media_type"] == "tv" and imported_episode_list:
            next_episode = max(last_episode, imported_episode_list[-1])
        elif task["media_type"] == "tv" and episode > 0:
            next_episode = max(last_episode, episode)
        next_total = known_total or max_total_detected or total_detected
        if task["media_type"] == "tv" and (max_total_detected > 0 or total_detected > 0):
            _sync_task_total_episodes(task_name, max_total_detected or total_detected)

        action_text = "复用导入任务" if selected_reused_existing else "已创建并执行导入任务"
        if task["media_type"] == "tv" and successful_count > 1:
            if imported_episode_list:
                if len(imported_episode_list) <= 8:
                    episode_summary = "、".join([f"E{episode_no}" for episode_no in imported_episode_list])
                else:
                    episode_summary = f"E{imported_episode_list[0]}-E{imported_episode_list[-1]}"
                batch_tail = f"（新增 {len(imported_episode_list)} 集：{episode_summary}）"
            else:
                batch_tail = ""
            detail = (
                f"本次批量导入 {successful_count} 条候选资源{batch_tail}；"
                f"最新命中「{str(item.get('title', '') or f'资源#{resource_id}').strip()}」"
                f"（评分 {score}），{action_text} #{job_id}，保存到 {effective_savepath}"
            )
        else:
            detail = (
                f"命中「{str(item.get('title', '') or f'资源#{resource_id}').strip()}」"
                f"（评分 {score}），{action_text} #{job_id}，保存到 {effective_savepath}"
            )
        if monitor_task_name:
            detail += f"；自动触发监控「{monitor_task_name}」"
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
            matched_resource_title=str(item.get("title", "") or "").strip(),
            matched_score=score,
            queued_job_id=job_id,
            stats={
                "matched": True,
                "score": score,
                "token_hits": int(candidate.get("token_hits", 0) or 0),
                "token_total": int(candidate.get("token_total", 0) or 0),
                "episode": episode,
                "season": season,
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
                "scanned_candidates": scanned_candidates,
                "max_scan_candidates": max_scan_candidates,
                "existing_episode_count": existing_episode_count,
                **existing_episode_scan_stats,
                **search_stats,
            },
        )
        await write_subscription_log(detail, "success")
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
                await write_subscription_log(fallback_detail, "warn")
        except Exception:
            pass
        await write_subscription_log(f"━━━━━━━━━━【订阅结束 | {task_name}】━━━━━━━━━━", "task-divider")
        subscription_status["running"] = False
        subscription_status["current_task"] = ""
        subscription_control["cancel"] = False
        schedule_ui_state_push(0)
        await start_next_subscription_job()


async def start_next_subscription_job() -> None:
    if subscription_status["running"] or not subscription_queue:
        subscription_status["queued"] = [item["task_name"] for item in subscription_queue]
        schedule_ui_state_push(0)
        return
    next_job = subscription_queue.pop(0)
    subscription_status["queued"] = [item["task_name"] for item in subscription_queue]
    schedule_ui_state_push(0)
    asyncio.create_task(
        run_subscription_task(
            next_job["task_name"],
            trigger=next_job.get("trigger", "queued"),
        )
    )


def queue_subscription_job(task_name: str, trigger: str) -> str:
    job_signature = safe_json_dumps({"task_name": task_name, "trigger": trigger})
    if any(item.get("job_signature") == job_signature for item in subscription_queue):
        schedule_ui_state_push(0)
        return "queued"
    subscription_queue.append(
        {
            "task_name": task_name,
            "trigger": trigger,
            "job_signature": job_signature,
        }
    )
    subscription_status["queued"] = [item["task_name"] for item in subscription_queue]
    schedule_ui_state_push(0)
    if subscription_status["running"]:
        return "queued"
    asyncio.create_task(start_next_subscription_job())
    return "started"
