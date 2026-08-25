import logging

from . import subscription as _subscription
from ..memory import release_process_memory

# The runner keeps the historical helper surface from subscription.py while
# the large task orchestration functions live in this focused module.
globals().update(
    {
        key: value
        for key, value in _subscription.__dict__.items()
        if key not in {"__name__", "__package__", "__loader__", "__spec__", "__file__", "__cached__"}
    }
)

from ..providers.registry import get_or_none as _get_provider_or_none
from .resource import (
    RESOURCE_OFFLINE_POLL_MAX_PAGES,
    _match_115_offline_task,
    _pick_submit_offline_hash,
    build_offline_job_identity,
)
from .subscription_episode import _extract_subscription_season_from_name


SUBSCRIPTION_OFFLINE_LINK_TYPES = frozenset(("magnet", "ed2k"))
SUBSCRIPTION_OFFLINE_STAGING_ROOT = "云下载/磁力中转"
SUBSCRIPTION_OFFLINE_POLL_INTERVAL_SECONDS = 30
SUBSCRIPTION_OFFLINE_POLL_MAX_SECONDS = 43200
SUBSCRIPTION_OFFLINE_RETENTION_DAYS = 7
SUBSCRIPTION_OFFLINE_SCAN_MAX_DIRS = 300
SUBSCRIPTION_OFFLINE_SCAN_MAX_ENTRIES = 3000


def _format_subscription_matched_episode_summary(episodes: Any) -> str:
    normalized: List[int] = []
    seen: Set[int] = set()
    for raw_value in episodes or []:
        try:
            episode_no = max(0, int(raw_value or 0))
        except (TypeError, ValueError):
            continue
        if episode_no <= 0 or episode_no in seen:
            continue
        seen.add(episode_no)
        normalized.append(episode_no)
    ordered = sorted(normalized)
    if not ordered:
        return ""

    ranges: List[Tuple[int, int]] = []
    range_start = ordered[0]
    previous = ordered[0]
    for episode_no in ordered[1:]:
        if episode_no == previous + 1:
            previous = episode_no
            continue
        ranges.append((range_start, previous))
        range_start = episode_no
        previous = episode_no
    ranges.append((range_start, previous))

    parts = [
        f"第{start}集" if start == end else f"第{start}到{end}集"
        for start, end in ranges
    ]
    return "、".join(parts)


def _build_subscription_matched_episode_log_tail(task: Dict[str, Any], episodes: Any) -> str:
    if str((task or {}).get("media_type", "movie") or "movie").strip().lower() != "tv":
        return ""
    episode_summary = _format_subscription_matched_episode_summary(episodes)
    return f"；命中集数：{episode_summary}" if episode_summary else ""


def _format_subscription_episode_range_summary(episodes: Any) -> str:
    normalized: List[int] = []
    seen: Set[int] = set()
    for raw_value in episodes or []:
        try:
            episode_no = max(0, int(raw_value or 0))
        except (TypeError, ValueError):
            continue
        if episode_no <= 0 or episode_no in seen:
            continue
        seen.add(episode_no)
        normalized.append(episode_no)
    ordered = sorted(normalized)
    if not ordered:
        return ""

    ranges: List[Tuple[int, int]] = []
    range_start = ordered[0]
    previous = ordered[0]
    for episode_no in ordered[1:]:
        if episode_no == previous + 1:
            previous = episode_no
            continue
        ranges.append((range_start, previous))
        range_start = episode_no
        previous = episode_no
    ranges.append((range_start, previous))
    return "、".join(
        f"E{start}" if start == end else f"E{start}-E{end}"
        for start, end in ranges
    )


def _build_subscription_import_summary_log(
    task: Dict[str, Any],
    imported_episodes: Any,
    *,
    next_episode: int = 0,
    total_episodes: int = 0,
) -> Tuple[str, str]:
    if str((task or {}).get("media_type", "movie") or "movie").strip().lower() != "tv":
        return "", ""

    episode_summary = _format_subscription_episode_range_summary(imported_episodes)
    imported_episode_set: Set[int] = set()
    for raw_value in imported_episodes or []:
        try:
            episode_no = max(0, int(raw_value or 0))
        except (TypeError, ValueError):
            continue
        if episode_no > 0:
            imported_episode_set.add(episode_no)
    imported_count = len(imported_episode_set)
    normalized_next = max(0, int(next_episode or 0))
    normalized_total = max(0, int(total_episodes or 0))
    progress_text = f"E{normalized_next}" if normalized_next > 0 else "--"
    if normalized_total > 0:
        progress_text = f"{progress_text} / {normalized_total}"

    if episode_summary and imported_count > 0:
        return (
            f"导入汇总：本轮新增 {imported_count} 集：{episode_summary}；当前进度 {progress_text}",
            "success",
        )
    return (
        f"导入汇总：本轮未确认新增集数；当前进度 {progress_text}",
        "info",
    )


def _format_subscription_share_scan_truncated_reason(reason: Any) -> str:
    labels = {
        "max_dirs": "目录数达到上限",
        "max_entries": "条目数达到上限",
        "provider_has_more": "网盘分页仍有更多内容",
        "queue_pending": "仍有待扫目录",
        "page_cap": "分页达到上限",
    }
    parts = [str(part or "").strip() for part in str(reason or "").split(",") if str(part or "").strip()]
    if not parts:
        return "未知原因"
    return "、".join(labels.get(part, part) for part in unique_preserve_order(parts))


def _format_subscription_share_scan_log_tail(stats: Dict[str, Any], *, include_candidates: bool = True) -> str:
    payload = stats if isinstance(stats, dict) else {}
    scanned_dirs = max(0, int(payload.get("scanned_dirs", 0) or 0))
    scanned_entries = max(0, int(payload.get("scanned_entries", 0) or 0))
    returned_entries = max(0, int(payload.get("returned_entries", scanned_entries) or 0))
    provider_reported_entries = max(0, int(payload.get("provider_reported_entries", 0) or 0))
    candidate_count = max(
        0,
        int(
            payload.get(
                "matched_file_count",
                payload.get("file_count", payload.get("selected_count", 0)),
            )
            or 0
        ),
    )
    parts = [
        f"扫描目录 {scanned_dirs} 个",
        f"返回条目 {returned_entries} 条",
    ]
    if provider_reported_entries > returned_entries:
        parts.append(f"提供方统计 {provider_reported_entries} 条")
    if include_candidates:
        parts.append(f"候选文件 {candidate_count} 个")
    skipped_small_files = max(0, int(payload.get("skipped_small_files", 0) or 0))
    if skipped_small_files > 0:
        parts.append(f"小文件过滤 {skipped_small_files} 个")
    if bool(payload.get("truncated", False)):
        parts.append(
            f"已截断：{_format_subscription_share_scan_truncated_reason(payload.get('truncated_reason', ''))}"
        )
    return "，".join(parts)


def _format_subscription_excluded_file_type_tail(stats: Dict[str, Any]) -> str:
    payload = stats if isinstance(stats, dict) else {}
    skipped = max(
        0,
        int(payload.get("skipped_excluded_file_types", payload.get("skipped_archive_files", 0)) or 0),
    )
    if skipped <= 0:
        return ""
    extensions = normalize_subscription_exclude_file_extensions(payload.get("exclude_file_extensions", []))
    extension_text = "/".join(extensions[:5]) if extensions else "已配置类型"
    if len(extensions) > 5:
        extension_text = f"{extension_text}等"
    return f"，已排除文件类型 {extension_text} {skipped} 个"


def _build_subscription_episode_batch_decision(
    task: Dict[str, Any],
    *,
    trigger: str,
    existing_episode_scan_ready: bool,
    existing_episode_scan_reliable: bool,
    existing_folder_episodes: Set[int],
    single_season_episode_upper_bound: int,
    candidates: List[Dict[str, Any]],
) -> Dict[str, Any]:
    if str((task or {}).get("media_type", "movie") or "movie").strip().lower() != "tv":
        return {"enabled": False, "reason": "not_tv", "candidate_missing_episodes": []}

    trigger_mode = str(trigger or "").strip().lower()
    upper_bound = max(0, int(single_season_episode_upper_bound or 0))
    normalized_existing = _clamp_episode_values(
        existing_folder_episodes or set(),
        episode_upper_bound=upper_bound,
    )
    candidate_missing: Set[int] = set()

    if trigger_mode == "manual":
        return {
            "enabled": True,
            "reason": "manual",
            "candidate_missing_episodes": [],
            "target_missing_count": 0,
        }

    if upper_bound <= 0:
        return {"enabled": False, "reason": "unknown_total", "candidate_missing_episodes": []}
    if not existing_episode_scan_ready:
        return {"enabled": False, "reason": "scan_not_ready", "candidate_missing_episodes": []}
    if not existing_episode_scan_reliable:
        return {"enabled": False, "reason": "scan_unreliable", "candidate_missing_episodes": []}

    target_episodes = set(range(1, upper_bound + 1))
    target_missing = target_episodes.difference(normalized_existing)
    if not target_missing:
        return {
            "enabled": False,
            "reason": "target_complete",
            "candidate_missing_episodes": [],
            "target_missing_count": 0,
        }

    if not normalized_existing:
        return {
            "enabled": True,
            "reason": "initial_empty_target",
            "candidate_missing_episodes": [],
            "target_missing_count": len(target_missing),
        }

    candidate_count = 0
    for candidate in (candidates if isinstance(candidates, list) else []):
        candidate_count += 1
        candidate_missing.update(
            _candidate_missing_episode_values(
                candidate,
                normalized_existing,
                episode_upper_bound=upper_bound,
            )
        )
    if candidate_missing:
        return {
            "enabled": True,
            "reason": "candidate_missing_episodes",
            "candidate_missing_episodes": sorted(candidate_missing)[:120],
            "target_missing_count": len(target_missing),
            "candidate_count": candidate_count,
        }

    existing_max = max(normalized_existing) if normalized_existing else 0
    backfill_missing = {episode_no for episode_no in target_missing if existing_max > 0 and episode_no <= existing_max}
    if backfill_missing:
        return {
            "enabled": True,
            "reason": "backfill_gap",
            "candidate_missing_episodes": sorted(backfill_missing)[:120],
            "target_missing_count": len(target_missing),
            "candidate_count": candidate_count,
        }

    if candidate_count > 0:
        return {
            "enabled": True,
            "reason": "manifest_pending_missing_check",
            "candidate_missing_episodes": [],
            "target_missing_count": len(target_missing),
            "candidate_count": candidate_count,
        }

    return {
        "enabled": False,
        "reason": "no_candidates",
        "candidate_missing_episodes": sorted(candidate_missing)[:120],
        "target_missing_count": len(target_missing),
        "candidate_count": candidate_count,
    }


def _build_subscription_candidate_manifest_cache_key(provider: str, candidate: Dict[str, Any]) -> str:
    payload = candidate if isinstance(candidate, dict) else {}
    item = payload.get("item", {}) if isinstance(payload.get("item"), dict) else {}
    link_url = _normalize_subscription_candidate_link(item.get("link_url", ""))
    if not link_url:
        return ""
    item_extra = item.get("extra") if isinstance(item.get("extra"), dict) else safe_json_loads(item.get("extra_json"), {})
    receive_code = normalize_receive_code(item.get("receive_code", "")) or normalize_receive_code(
        (item_extra or {}).get("receive_code", "")
    )
    normalized_provider = normalize_subscription_provider(provider, fallback="115")
    if normalized_provider == "quark":
        share_key = _build_subscription_quark_share_dedupe_key(
            link_url,
            item.get("raw_text", ""),
            receive_code,
        )
        return share_key or f"url:{link_url.lower()}"
    return f"{link_url.lower()}|{receive_code.lower()}"


def _is_115_tv_file_level_selection(selection: Any) -> bool:
    normalized = normalize_share_selection_meta(selection or {})
    selected_entries = (
        normalized.get("selected_entries", [])
        if isinstance(normalized.get("selected_entries"), list)
        else []
    )
    if not selected_entries:
        return False
    return all(isinstance(entry, dict) and not bool(entry.get("is_dir")) for entry in selected_entries)


def _pick_subscription_candidate_manifest_prewarm_rows(
    candidates: List[Dict[str, Any]],
    provider: str,
    max_candidates: int,
    *,
    allow_zero_resource_id: bool = False,
) -> List[Dict[str, Any]]:
    normalized_provider = normalize_subscription_provider(provider, fallback="115")
    provider_meta = _get_provider_or_none(normalized_provider)
    expected_link_type = str(getattr(provider_meta, "link_type", "") or "").strip() or (
        "quark" if normalized_provider == "quark" else "115share"
    )
    limit = max(0, int(max_candidates or 0))
    if limit <= 0:
        return []
    rows: List[Dict[str, Any]] = []
    seen_keys: Set[str] = set()
    for index, candidate in enumerate(candidates if isinstance(candidates, list) else [], start=1):
        payload = candidate if isinstance(candidate, dict) else {}
        item = payload.get("item", {}) if isinstance(payload.get("item"), dict) else {}
        resource_id = max(0, int(item.get("id", 0) or 0))
        if resource_id <= 0 and not allow_zero_resource_id:
            continue
        link_url = _normalize_subscription_candidate_link(item.get("link_url", ""))
        link_type = resolve_resource_link_type(item.get("link_type", ""), link_url)
        if link_type != expected_link_type:
            continue
        cache_key = _build_subscription_candidate_manifest_cache_key(normalized_provider, payload)
        if not cache_key or cache_key in seen_keys:
            continue
        seen_keys.add(cache_key)
        rows.append(
            {
                "index": index,
                "candidate": payload,
                "item": item,
                "cache_key": cache_key,
                "high_priority": index <= 3 or int(payload.get("score", 0) or 0) >= 90 or resource_id <= 0,
            }
        )
        if len(rows) >= limit:
            break
    return rows


async def _prewarm_subscription_candidate_share_manifests(
    *,
    cookie: str,
    task: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    provider: str,
    manifest_cache: Dict[str, Dict[str, Any]],
    label: str,
    share_subdir: str = "",
    share_subdir_cid: str = "",
    subdir_selection_cache: Optional[Dict[str, Dict[str, Any]]] = None,
    subdir_selection_stats_cache: Optional[Dict[str, Dict[str, Any]]] = None,
    allow_zero_resource_id: bool = False,
    max_candidates: int = 0,
) -> Dict[str, Any]:
    if str((task or {}).get("media_type", "movie") or "movie").strip().lower() != "tv":
        return {"enabled": False, "reason": "media_type_not_tv"}
    normalized_cookie = str(cookie or "").strip()
    if not normalized_cookie:
        return {"enabled": False, "reason": "cookie_missing"}
    normalized_provider = normalize_subscription_provider(provider, fallback="115")
    configured_prefetch_limit = get_subscription_candidate_scan_prefetch_limit(task, normalized_provider)
    if configured_prefetch_limit <= 0:
        return {"enabled": False, "reason": "prefetch_disabled"}
    requested_prefetch_limit = max(0, int(max_candidates or 0))
    prefetch_limit = (
        min(configured_prefetch_limit, requested_prefetch_limit)
        if requested_prefetch_limit > 0
        else configured_prefetch_limit
    )
    rows = _pick_subscription_candidate_manifest_prewarm_rows(
        candidates,
        normalized_provider,
        prefetch_limit,
        allow_zero_resource_id=allow_zero_resource_id,
    )
    rows = [row for row in rows if str(row.get("cache_key", "") or "") not in manifest_cache]
    if not rows:
        return {"enabled": False, "reason": "no_candidates"}

    concurrency = get_subscription_candidate_scan_concurrency(task, normalized_provider)
    normal_max_entries = max(0, int(SUBSCRIPTION_SHARE_SCAN_NORMAL_MAX_ENTRIES or 0))
    high_max_entries = max(normal_max_entries, int(SUBSCRIPTION_SHARE_SCAN_HIGH_PRIORITY_MAX_ENTRIES or 0))
    started_at = time.perf_counter()
    await write_subscription_log(
        (
            f"{label}候选精查预热：准备并发读取 {len(rows)} 个分享清单，"
            f"并发 {concurrency}，普通上限 {normal_max_entries or '不限制'} 条，"
            f"高优先上限 {high_max_entries or '不限制'} 条"
        ),
        "info",
        compact=f"候选精查 | {len(rows)} 个分享清单 · 并发 {concurrency}"
                + (f" · 上限 {normal_max_entries}" if normal_max_entries > 0 else ""),
    )

    semaphore = asyncio.Semaphore(concurrency)
    requested_subdir = normalize_relative_path(str(share_subdir or "").strip())
    requested_subdir_cid = _normalize_subscription_share_subdir_cid(share_subdir_cid)

    async def scan_one(row: Dict[str, Any]) -> Dict[str, Any]:
        async with semaphore:
            check_subscription_cancelled()
            item = row.get("item", {}) if isinstance(row.get("item"), dict) else {}
            max_entries = high_max_entries if bool(row.get("high_priority", False)) else normal_max_entries
            try:
                snapshot = await _scan_subscription_share_tree_snapshot(
                    normalized_cookie,
                    task,
                    item,
                    max_depth=5,
                    max_entries=max_entries,
                    per_request_timeout=max(12, int(SUBSCRIPTION_SHARE_SCAN_REQUEST_TIMEOUT_SECONDS or 12)),
                    force_refresh=False,
                )
            except Exception as exc:
                return {
                    "cache_key": str(row.get("cache_key", "") or ""),
                    "index": max(0, int(row.get("index", 0) or 0)),
                    "failed": True,
                    "reason": str(exc or "").strip() or exc.__class__.__name__,
                }

            manifest = snapshot
            subdir_selection: Dict[str, Any] = {}
            subdir_stats: Dict[str, Any] = {}
            cache_subdir = False
            if normalized_provider == "115" and (requested_subdir or requested_subdir_cid):
                subdir_selection, subdir_stats = _build_subscription_share_selection_from_snapshot(
                    snapshot,
                    requested_subdir,
                    requested_subdir_cid,
                )
                selected_ids = (
                    subdir_selection.get("selected_ids", [])
                    if isinstance(subdir_selection.get("selected_ids"), list)
                    else []
                )
                reason = str((subdir_stats or {}).get("reason", "") or "").strip()
                if selected_ids:
                    manifest = _build_subscription_share_manifest_from_snapshot(snapshot, subdir_selection, task)
                    cache_subdir = True
                elif reason == "target_is_share_root":
                    cache_subdir = True
                else:
                    manifest = {}

            return {
                "cache_key": str(row.get("cache_key", "") or ""),
                "index": max(0, int(row.get("index", 0) or 0)),
                "link_url": _normalize_subscription_candidate_link(item.get("link_url", "")),
                "failed": False,
                "manifest": manifest,
                "subdir_selection": subdir_selection,
                "subdir_stats": subdir_stats,
                "cache_subdir": cache_subdir,
                "scanned_dirs": int((manifest or snapshot).get("scanned_dirs", 0) or 0),
                "scanned_entries": int((manifest or snapshot).get("scanned_entries", 0) or 0),
                "returned_entries": int((manifest or snapshot).get("returned_entries", 0) or 0),
                "file_count": int((manifest or snapshot).get("file_count", 0) or 0),
                "truncated": bool((manifest or snapshot).get("truncated", False)),
            }

    results = await asyncio.gather(*(scan_one(row) for row in rows), return_exceptions=True)
    cached_count = 0
    failed_count = 0
    truncated_count = 0
    scanned_dirs = 0
    scanned_entries = 0
    returned_entries = 0
    file_count = 0
    for result in results:
        if isinstance(result, Exception):
            failed_count += 1
            continue
        payload = result if isinstance(result, dict) else {}
        if bool(payload.get("failed", False)):
            failed_count += 1
            continue
        cache_key = str(payload.get("cache_key", "") or "").strip()
        manifest = payload.get("manifest") if isinstance(payload.get("manifest"), dict) else {}
        if cache_key and manifest:
            manifest_cache[cache_key] = manifest
            cached_count += 1
        if (
            normalized_provider == "115"
            and bool(payload.get("cache_subdir", False))
            and cache_key
            and isinstance(subdir_selection_cache, dict)
            and isinstance(subdir_selection_stats_cache, dict)
        ):
            selection_payload = (
                payload.get("subdir_selection", {})
                if isinstance(payload.get("subdir_selection"), dict)
                else {}
            )
            stats_payload = (
                payload.get("subdir_stats", {})
                if isinstance(payload.get("subdir_stats"), dict)
                else {}
            )
            link_url = _normalize_subscription_candidate_link(payload.get("link_url", ""))
            for subdir_cache_key in unique_preserve_order(
                [
                    f"{cache_key}|{requested_subdir}|{requested_subdir_cid}",
                    f"{link_url}|{requested_subdir}|{requested_subdir_cid}" if link_url else "",
                ]
            ):
                if not subdir_cache_key:
                    continue
                subdir_selection_cache[subdir_cache_key] = selection_payload
                subdir_selection_stats_cache[subdir_cache_key] = stats_payload
        truncated_count += 1 if bool(payload.get("truncated", False)) else 0
        scanned_dirs += max(0, int(payload.get("scanned_dirs", 0) or 0))
        scanned_entries += max(0, int(payload.get("scanned_entries", 0) or 0))
        returned_entries += max(0, int(payload.get("returned_entries", 0) or 0))
        file_count += max(0, int(payload.get("file_count", 0) or 0))

    elapsed = max(0.0, time.perf_counter() - started_at)
    await write_subscription_log(
        (
            f"{label}候选精查预热完成：清单缓存 {cached_count}/{len(rows)} 个，"
            f"扫描目录 {scanned_dirs} 个，返回条目 {returned_entries or scanned_entries} 条，"
            f"候选文件 {file_count} 个，截断 {truncated_count} 个，异常 {failed_count} 个，"
            f"用时 {_format_elapsed_seconds(elapsed)}"
        ),
        "info" if failed_count <= 0 else "warn",
    )
    return {
        "enabled": True,
        "requested": len(rows),
        "cached": cached_count,
        "failed": failed_count,
        "truncated": truncated_count,
        "scanned_dirs": scanned_dirs,
        "scanned_entries": scanned_entries,
        "returned_entries": returned_entries,
        "file_count": file_count,
        "elapsed_seconds": elapsed,
        "concurrency": concurrency,
    }


def _build_manual_subscription_search_result(
    task: Dict[str, Any],
    task_name: str,
    manual_candidate: Dict[str, Any],
    provider: str,
) -> Dict[str, Any]:
    normalized_provider = normalize_subscription_provider(provider, fallback="115")
    provider_meta = _get_provider_or_none(normalized_provider)
    manual_link_type = str(manual_candidate.get("link_type", "") or "").strip().lower()
    link_type = manual_link_type or str(getattr(provider_meta, "link_type", "") or "").strip() or (
        "quark" if normalized_provider == "quark" else "115share"
    )
    provider_label = str(getattr(provider_meta, "label", "") or normalized_provider).strip()
    keyword_label = f"manual-{normalized_provider}-link"
    link_url = str(manual_candidate.get("link_url", "") or "").strip()
    raw_text = str(manual_candidate.get("raw_text", "") or link_url).strip()
    receive_code = normalize_receive_code(manual_candidate.get("receive_code", ""))
    title = str(task.get("title", "") or task_name or "扫描链接").strip() or "扫描链接"
    resource_item = {
        "source_type": "subscription_manual_link",
        "source_name": f"订阅扫描链接({provider_label})",
        "channel_name": "",
        "title": title,
        "normalized_title": title.lower(),
        "raw_text": raw_text or link_url,
        "link_url": link_url,
        "link_type": link_type,
        "message_url": "",
        "quality": "",
        "year": str(task.get("year", "") or "").strip(),
        "published_at": now_text(),
        "receive_code": receive_code,
        "extra": {
            "receive_code": receive_code,
            "subscription_task_name": task_name,
            "manual_subscription_link": True,
            "manual_link_provider": normalized_provider,
            "manual_link_type": link_type,
        },
    }
    blocked_keyword = match_subscription_exclude_keyword(task, resource_item)
    if blocked_keyword:
        return {
            "candidate": {},
            "candidates": [],
            "keywords": [keyword_label],
            "errors": [],
            "stats": {
                "search_keywords": 0,
                "searched_sources": 0,
                "matched_channels": 0,
                "pages_scanned": 0,
                "raw_items": 1,
                "deduped_items": 1,
                "persisted_items": 0,
                "supported_items": 0,
                "unsupported_items": 0,
                "exclude_keyword_filtered": 1,
                "exclude_keyword_hits": {blocked_keyword: 1},
                "exclude_keywords": normalize_subscription_exclude_keywords(task.get("exclude_keywords", [])),
                "manual_link_candidate_count": 0,
                "scored_items": 0,
                "scored_candidates": 0,
                "relaxed_score_mode": False,
                "relaxed_candidates": 0,
                "search_errors": 0,
                "best_score": 0,
                "provider": normalized_provider,
            },
        }
    ensure_db()
    conn = open_db()
    try:
        resource_id, _ = upsert_resource_item(conn, resource_item, identity_mode="link")
        conn.commit()
    finally:
        conn.close()
    persisted_item = {**resource_item, "id": resource_id}
    fixed_candidate = {
        "item": persisted_item,
        "score": 100,
        "episode": 0,
        "season": 0,
        "total": 0,
        "range_start": 0,
        "range_end": 0,
        "resolution": 0,
        "token_hits": 0,
        "title_match_forced": True,
    }
    return {
        "candidate": fixed_candidate,
        "candidates": [fixed_candidate],
        "keywords": [keyword_label],
        "errors": [],
        "stats": {
            "search_keywords": 0,
            "searched_sources": 0,
            "matched_channels": 0,
            "pages_scanned": 0,
            "raw_items": 1,
            "deduped_items": 1,
            "persisted_items": 1,
            "supported_items": 1,
            "unsupported_items": 0,
            "exclude_keyword_filtered": 0,
            "exclude_keyword_hits": {},
            "exclude_keywords": normalize_subscription_exclude_keywords(task.get("exclude_keywords", [])),
            "manual_link_candidate_count": 1,
            "scored_items": 1,
            "scored_candidates": 1,
            "relaxed_score_mode": False,
            "relaxed_candidates": 0,
            "search_errors": 0,
            "best_score": 100,
            "provider": normalized_provider,
        },
    }


def _subscription_offline_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """仅放行手动扫描链接里的 magnet/ed2k 候选；搜索自动发现的磁力继续不路由。"""
    if not isinstance(candidate, dict):
        return {}
    item = candidate.get("item") if isinstance(candidate.get("item"), dict) else {}
    extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
    if not bool(extra.get("manual_subscription_link", False)):
        return {}
    link_type = resolve_resource_link_type(
        item.get("link_type", ""),
        str(item.get("link_url", "") or "").strip(),
    )
    if link_type not in SUBSCRIPTION_OFFLINE_LINK_TYPES:
        return {}
    return {
        "candidate": candidate,
        "item": item,
        "link_type": link_type,
    }


def _get_subscription_offline_staging_root(cfg: Dict[str, Any]) -> str:
    raw = str((cfg or {}).get("magnet_staging_root", "") or "").strip()
    return normalize_relative_path(raw or SUBSCRIPTION_OFFLINE_STAGING_ROOT)


_SUBSCRIPTION_OFFLINE_JUNK_EXTENSIONS = frozenset(
    (
        "nfo",
        "jpg",
        "jpeg",
        "png",
        "gif",
        "bmp",
        "webp",
        "txt",
        "htm",
        "html",
        "url",
        "lnk",
        "torrent",
        "db",
    )
)
_SUBSCRIPTION_OFFLINE_JUNK_NAME_TOKENS = (
    "sample",
    "样板",
    "trailer",
    "预告",
    "advert",
    "广告",
    "cover",
    "poster",
    "海报",
)


def _is_subscription_offline_junk_file(name: str) -> bool:
    normalized = normalize_relative_path(str(name or "").strip())
    if not normalized:
        return True
    leaf = normalized.replace("\\", "/").split("/")[-1].strip()
    if not leaf:
        return True
    ext = os.path.splitext(leaf)[1].lstrip(".").lower()
    if ext in _SUBSCRIPTION_OFFLINE_JUNK_EXTENSIONS:
        return True
    stem = os.path.splitext(leaf)[0].lower()
    for token in _SUBSCRIPTION_OFFLINE_JUNK_NAME_TOKENS:
        if token in stem:
            return True
    return False


def _subscription_offline_title_tokens(task: Dict[str, Any]) -> Set[str]:
    title = str(task.get("title", "") or "").strip().lower()
    tokens = set(re.findall(r"[a-z0-9\u4e00-\u9fff]+", title))
    aliases = task.get("aliases", []) if isinstance(task.get("aliases"), list) else []
    for alias in aliases:
        tokens.update(re.findall(r"[a-z0-9\u4e00-\u9fff]+", str(alias or "").lower()))
    return tokens


def _subscription_offline_file_matches_title(task: Dict[str, Any], name: str) -> bool:
    tokens = _subscription_offline_title_tokens(task)
    if not tokens:
        return True
    name_tokens = set(re.findall(r"[a-z0-9\u4e00-\u9fff]+", str(name or "").lower()))
    return bool(tokens.issubset(name_tokens))


def _subscription_offline_file_older_than(entry: Dict[str, Any], days: int) -> bool:
    raw_ts = str((entry or {}).get("modified_at", "") or "").strip()
    if not raw_ts:
        return False
    try:
        timestamp = parse_resource_datetime_to_timestamp(raw_ts)
    except Exception:
        return False
    if not timestamp:
        return False
    return (time.time() - timestamp) >= max(1, int(days or 0)) * 86400


def _list_subscription_offline_staging_entries(
    provider: Any,
    cookie: str,
    root_cid: str,
    task: Dict[str, Any],
    min_size_bytes: int = 0,
) -> Dict[str, Any]:
    """递归列出中转目录媒体文件；垃圾文件直接标记删除，不参与挑选。"""
    files: List[Dict[str, Any]] = []
    junk_ids: List[str] = []
    scanned_dirs = 0
    scanned_entries = 0
    truncated = False
    pending: List[Tuple[str, str]] = [("", str(root_cid or "0").strip() or "0")]
    while pending and scanned_dirs < SUBSCRIPTION_OFFLINE_SCAN_MAX_DIRS:
        parent_rel, cid = pending.pop(0)
        try:
            entries = provider.list_entries(cookie, cid)
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "订阅中转目录读取失败（%s）：%s",
                parent_rel or "/",
                exc,
            )
            continue
        scanned_dirs += 1
        for entry in entries if isinstance(entries, list) else []:
            scanned_entries += 1
            if scanned_entries > SUBSCRIPTION_OFFLINE_SCAN_MAX_ENTRIES:
                truncated = True
                break
            if not isinstance(entry, dict):
                continue
            entry_id = str(entry.get("id", "") or "").strip()
            name = str(entry.get("name", "") or "").strip()
            if not entry_id or not name:
                continue
            rel_path = join_relative_path(parent_rel, name)
            if bool(entry.get("is_dir", False)):
                pending.append((rel_path, entry_id))
                continue
            if _is_subscription_offline_junk_file(rel_path):
                junk_ids.append(entry_id)
                continue
            if min_size_bytes > 0 and max(0, int(entry.get("size", 0) or 0)) < min_size_bytes:
                continue
            if _is_subscription_excluded_file_type(task, rel_path):
                continue
            episodes: Set[int] = set()
            if str((task or {}).get("media_type", "movie") or "movie").strip().lower() == "tv":
                episodes = _extract_task_episodes_from_file_entry(task, rel_path)
                episodes = _clamp_episode_values(episodes)
            files.append(
                {
                    "id": entry_id,
                    "fid": str(entry.get("fid", "") or entry_id).strip(),
                    "name": name,
                    "rel_path": rel_path,
                    "size": max(0, int(entry.get("size", 0) or 0)),
                    "is_dir": False,
                    "parent_id": cid,
                    "episodes": sorted(episodes),
                    "modified_at": str(entry.get("modified_at", "") or "").strip(),
                }
            )
        if truncated:
            break
    return {
        "files": files,
        "junk_ids": junk_ids,
        "scanned_dirs": scanned_dirs,
        "scanned_entries": scanned_entries,
        "truncated": truncated,
    }


def _select_subscription_offline_entries(
    task: Dict[str, Any],
    files: List[Dict[str, Any]],
    existing_folder_episodes: Set[int],
    single_season_episode_upper_bound: int = 0,
) -> Dict[str, Any]:
    """按订阅条件从中转文件里挑选入库条目，返回 selected_entries/ids/recorded_episodes。"""
    if not files:
        return {
            "selected_entries": [],
            "selected_ids": [],
            "recorded_episodes": set(),
            "selected_file_samples": [],
            "detail": "中转目录没有可入库媒体文件",
        }
    if str((task or {}).get("media_type", "movie") or "movie").strip().lower() == "tv":
        with_episodes = [entry for entry in files if entry.get("episodes")]
        if with_episodes:
            all_episodes = _clamp_episode_values(
                set().union(*[set(entry.get("episodes", set())) for entry in with_episodes]),
                episode_upper_bound=single_season_episode_upper_bound,
            )
            missing_episodes = {
                episode_no
                for episode_no in all_episodes
                if episode_no not in existing_folder_episodes
            }
            picked = _pick_best_tv_share_files_by_episode_bucket(
                task,
                with_episodes,
                missing_episodes,
            )
            picked_ids = {
                str(entry_id or "").strip()
                for entry_id in (picked.get("selected_ids", []) if isinstance(picked.get("selected_ids"), list) else [])
                if str(entry_id or "").strip()
            }
            if picked_ids:
                selected_entries = [entry for entry in files if str(entry.get("id", "") or "").strip() in picked_ids]
                recorded_episodes = _clamp_episode_values(
                    set().union(
                        *[
                            set(entry.get("episodes", set()))
                            for entry in selected_entries
                            if entry.get("episodes")
                        ]
                    ),
                    episode_upper_bound=single_season_episode_upper_bound,
                )
                return {
                    "selected_entries": selected_entries,
                    "selected_ids": [str(entry.get("id", "") or "").strip() for entry in selected_entries],
                    "recorded_episodes": recorded_episodes,
                    "selected_file_samples": [
                        str(entry.get("rel_path", "") or entry.get("name", "") or "").strip()
                        for entry in selected_entries[:8]
                    ],
                    "detail": f"按缺失集命中 {len(recorded_episodes)} 集",
                }
    best = None
    best_rank: Tuple[int, int, int, str] = (-1, -1, -1, "")
    for entry in files:
        if not _subscription_offline_file_matches_title(task, entry.get("rel_path", "") or entry.get("name", "")):
            continue
        rank = _build_subscription_share_file_quality_rank(task, entry)
        if rank > best_rank:
            best_rank = rank
            best = entry
    if best is None and len(files) == 1:
        best = files[0]
    if best is None:
        return {
            "selected_entries": [],
            "selected_ids": [],
            "recorded_episodes": set(),
            "selected_file_samples": [],
            "detail": "中转文件未命中订阅标题/剧集条件",
        }
    recorded = _clamp_episode_values(
        set(best.get("episodes", set())),
        episode_upper_bound=single_season_episode_upper_bound,
    )
    return {
        "selected_entries": [best],
        "selected_ids": [str(best.get("id", "") or "").strip()],
        "recorded_episodes": recorded,
        "selected_file_samples": [str(best.get("rel_path", "") or best.get("name", "") or "").strip()],
        "detail": "按标题与质量挑选最佳文件",
    }


async def _run_subscription_manual_offline_import(
    *,
    task: Dict[str, Any],
    task_name: str,
    cfg: Dict[str, Any],
    provider_meta: Any,
    cookie: str,
    candidate: Dict[str, Any],
    item: Dict[str, Any],
    link_type: str,
    staging_root: str,
    effective_savepath: str,
    base_savepath: str,
    folder_id: str,
    monitor_task_name: str,
    last_episode: int,
    known_total: int,
    single_season_episode_upper_bound: int,
    existing_folder_episodes: Set[int],
    existing_episode_scan_ready: bool,
    subscription_run_id: str,
    batch_refresh_enabled: bool,
    import_timeout_seconds: int = 90,
) -> Dict[str, Any]:
    """单次磁力/电驴离线入库：提交 115 离线 → 轮询完成 → 挑选 → 移动 → 刷新 → 清理。"""
    result_base: Dict[str, Any] = {
        "handled": True,
        "ok": False,
        "job_id": 0,
        "selected_savepath": effective_savepath,
        "successful_count": 0,
        "imported_episodes": [],
        "max_total_detected": 0,
        "auto_refresh": False,
        "reused_existing": False,
        "last_failed_detail": "",
        "failed_attempts": 0,
        "timed_out_attempts": 0,
    }
    if not provider_meta or not cookie:
        result_base["last_failed_detail"] = "115 认证信息未配置，无法离线下载"
        return result_base
    link_url = str(item.get("link_url", "") or "").strip()
    if not link_url:
        result_base["last_failed_detail"] = "磁力/电驴链接为空"
        return result_base
    media_type = str(task.get("media_type", "movie") or "movie").strip().lower()
    title = str(item.get("title", "") or task.get("title", "") or task_name or "磁力资源").strip()
    staging_rel = join_relative_path(staging_root, sanitize_115_folder_name(task_name, fallback="订阅任务"))
    job_id = 0
    submitted_hash = ""
    try:
        await write_subscription_log(
            f"磁力/电驴扫描链接已提交：{link_url[:120]}",
            "info",
        )
        staging_cid = await asyncio.wait_for(
            asyncio.to_thread(provider_meta.ensure_folder_id_by_path, cookie, staging_rel),
            timeout=min(import_timeout_seconds, 60),
        )
        staging_cid = str(staging_cid or "").strip() or "0"
        await write_subscription_log(f"中转目录已就绪：{staging_rel}", "info")
        upsert_subscription_task_state(
            task_name,
            media_type=media_type,
            status="running",
            progress=50,
            detail="正在提交 115 离线下载",
        )

        job_id = create_resource_job(
            item,
            {
                "folder_id": staging_cid,
                "savepath": staging_rel,
                "sharetitle": "",
                "monitor_task_name": "",
                "refresh_delay_seconds": 0,
                "auto_refresh": False,
                "extra": {
                    "job_source": "subscription_manual_link",
                    "subscription_run_id": subscription_run_id,
                    "subscription_task_name": task_name,
                    "offline_provider": "115",
                    "offline_provider_label": provider_meta.label,
                    "magnet_provider": "115",
                    "final_savepath": effective_savepath,
                    "staging_path": staging_rel,
                },
            },
        )
        update_resource_job(
            job_id,
            status="running",
            status_detail="正在提交 115 离线下载",
            started_at=now_text(),
            folder_id=staging_cid,
        )

        response = await asyncio.wait_for(
            asyncio.to_thread(
                provider_meta.submit_offline_task,
                cookie,
                link_url,
                staging_cid,
            ),
            timeout=import_timeout_seconds,
        )
        duplicate_submit = int((response or {}).get("errcode", 0) or 0) == 10008
        submitted_hash = _pick_submit_offline_hash(response)
        offline_extra = {
            "offline_task_hash": submitted_hash,
            "offline_url": link_url,
            "offline_poll_started_at": now_text(),
            "offline_poll_started_ts": time.time(),
            "offline_skip_wait": 1 if duplicate_submit else 0,
        }
        update_resource_job(job_id, extra_json=safe_json_dumps(offline_extra))
        await write_subscription_log(
            "115 已接收离线任务" + ("（该磁力此前已提交，等待已有任务完成）" if duplicate_submit else ""),
            "info",
        )

        pseudo_job = {
            "link_type": link_type,
            "link_url": link_url,
            "folder_id": staging_cid,
            "extra": dict(offline_extra),
        }
        identity = build_offline_job_identity(pseudo_job)
        if not submitted_hash:
            submitted_hash = str(identity.get("hash", "") or "").strip()
        pseudo_job["extra"]["offline_task_hash"] = submitted_hash

        deadline = time.time() + SUBSCRIPTION_OFFLINE_POLL_MAX_SECONDS
        last_percent = -1.0
        last_progress_log_ts = 0.0
        matched_task: Dict[str, Any] = {}
        while True:
            check_subscription_cancelled()
            if time.time() >= deadline:
                result_base["last_failed_detail"] = f"等待 115 离线下载超时（>{SUBSCRIPTION_OFFLINE_POLL_MAX_SECONDS} 秒）"
                result_base["timed_out_attempts"] = 1
                break
            found_task: Dict[str, Any] = {}
            folder_mismatch = False
            page_count = 1
            page = 1
            while page <= page_count and page <= RESOURCE_OFFLINE_POLL_MAX_PAGES:
                try:
                    query_result = await asyncio.wait_for(
                        asyncio.to_thread(provider_meta.query_offline_tasks, cookie, page),
                        timeout=60,
                    )
                except Exception:
                    break
                query_result = query_result if isinstance(query_result, dict) else {}
                tasks = query_result.get("tasks") or []
                page_count = max(1, min(20, int(query_result.get("page_count", page_count) or 1)))
                for raw_task in tasks:
                    if not isinstance(raw_task, dict):
                        continue
                    match = _match_115_offline_task(raw_task, pseudo_job)
                    if match == "folder_mismatch":
                        folder_mismatch = True
                        continue
                    if match == "exact":
                        found_task = raw_task
                        break
                if found_task:
                    break
                page += 1
            if found_task:
                status = int(found_task.get("status", 0) or 0)
                percent = max(0.0, min(100.0, float(found_task.get("percent", 0) or 0)))
                if status == 2:
                    matched_task = found_task
                    break
                if status == -1:
                    result_base["last_failed_detail"] = f"115 离线任务失败（{str(found_task.get('name', '未知任务')).strip()}）"
                    break
                now_ts = time.time()
                percent_changed = abs(percent - last_percent) >= 5.0
                interval_elapsed = now_ts - last_progress_log_ts >= 60
                if percent_changed or interval_elapsed:
                    last_percent = percent
                    last_progress_log_ts = now_ts
                    upsert_subscription_task_state(
                        task_name,
                        media_type=media_type,
                        status="running",
                        progress=min(88, 50 + int(percent / 3)),
                        detail=f"115 离线下载中 {percent:.0f}%",
                    )
                    await write_subscription_log(
                        f"115 离线下载中 {percent:.0f}%（{str(found_task.get('name', '')).strip()[:80]}）",
                        "info",
                    )
            else:
                if folder_mismatch:
                    result_base["last_failed_detail"] = "在 115 找到同链接任务，但目标目录与中转目录不一致"
                    break
                if last_percent < 0:
                    last_percent = 0
            check_subscription_cancelled()
            await asyncio.sleep(SUBSCRIPTION_OFFLINE_POLL_INTERVAL_SECONDS)

        if not matched_task:
            if not result_base.get("last_failed_detail"):
                result_base["last_failed_detail"] = "未在 115 离线任务列表中找到对应任务"
            raise RuntimeError(str(result_base.get("last_failed_detail", "") or "115 离线导入失败"))

        await write_subscription_log("115 离线下载完成，正在识别中转目录文件", "success")
        upsert_subscription_task_state(
            task_name,
            media_type=media_type,
            status="running",
            progress=88,
            detail="正在识别并挑选中转文件",
        )
        min_size_bytes = max(0, int(float(task.get("min_file_size_mb", 0) or 0) * 1024 * 1024))
        staging_meta = await asyncio.to_thread(
            _list_subscription_offline_staging_entries,
            provider_meta,
            cookie,
            staging_cid,
            task,
            min_size_bytes,
        )
        files = staging_meta.get("files") if isinstance(staging_meta.get("files"), list) else []
        junk_ids = staging_meta.get("junk_ids") if isinstance(staging_meta.get("junk_ids"), list) else []
        if junk_ids:
            await asyncio.to_thread(
                provider_meta.delete_entries,
                cookie,
                junk_ids,
                staging_cid,
            )
            await write_subscription_log(f"已清理中转目录垃圾文件 {len(junk_ids)} 个", "info")
        if bool(staging_meta.get("truncated", False)):
            await write_subscription_log("中转目录文件较多，本次扫描已截断，可能遗漏部分文件", "warn")
        if not files:
            result_base["last_failed_detail"] = "115 离线下载完成，但中转目录未发现可入库媒体文件"
            raise RuntimeError(str(result_base.get("last_failed_detail", "")))

        selection = _select_subscription_offline_entries(
            task,
            files,
            existing_folder_episodes,
            single_season_episode_upper_bound=single_season_episode_upper_bound,
        )
        selected_entries = selection.get("selected_entries") if isinstance(selection.get("selected_entries"), list) else []
        selected_ids = {
            str(entry_id or "").strip()
            for entry_id in (selection.get("selected_ids", []) if isinstance(selection.get("selected_ids"), list) else [])
            if str(entry_id or "").strip()
        }
        if not selected_ids:
            detail = str(selection.get("detail", "") or "中转文件未命中订阅条件") or "中转文件未命中订阅条件"
            await write_subscription_log(f"未命中订阅条件：{detail}；文件保留在中转目录", "warn")
            result_base["last_failed_detail"] = f"115 离线下载完成但未命中订阅条件（{detail}），文件保留在中转目录"
            update_resource_job(
                job_id,
                status="completed",
                status_detail=result_base["last_failed_detail"],
                finished_at=now_text(),
            )
            return result_base

        moved_savepaths: List[str] = []
        moved_count = 0
        skipped_duplicates = 0
        selected_savepath = effective_savepath
        for entry in selected_entries:
            entry_episodes = _clamp_episode_values(
                set(entry.get("episodes", set())),
                episode_upper_bound=single_season_episode_upper_bound,
            )
            target_savepath = effective_savepath
            if media_type == "tv":
                entry_season = 0
                if entry_episodes:
                    entry_season = _extract_subscription_season_from_name(
                        str(entry.get("rel_path", "") or entry.get("name", "") or "").strip()
                    )
                target_savepath = (
                    build_subscription_tv_savepath(
                        task,
                        base_savepath,
                        season=entry_season,
                        episode=min(entry_episodes) if entry_episodes else 0,
                    )
                    or effective_savepath
                )
            target_cid = await asyncio.wait_for(
                asyncio.to_thread(provider_meta.ensure_folder_id_by_path, cookie, target_savepath),
                timeout=min(import_timeout_seconds, 60),
            )
            target_cid = str(target_cid or "").strip() or "0"
            target_entries = await asyncio.to_thread(provider_meta.list_entries, cookie, target_cid)
            entry_size = max(0, int(entry.get("size", 0) or 0))
            duplicate = any(
                isinstance(target, dict)
                and not bool(target.get("is_dir", False))
                and str(target.get("name", "") or "").strip() == str(entry.get("name", "") or "").strip()
                and max(0, int(target.get("size", 0) or 0)) == entry_size
                for target in (target_entries if isinstance(target_entries, list) else [])
            )
            if duplicate:
                await asyncio.to_thread(
                    provider_meta.delete_entries,
                    cookie,
                    [str(entry.get("id", "") or "").strip()],
                    str(entry.get("parent_id", "") or staging_cid).strip() or staging_cid,
                )
                skipped_duplicates += 1
                continue
            await asyncio.wait_for(
                asyncio.to_thread(
                    provider_meta.move_entries,
                    cookie,
                    [str(entry.get("id", "") or "").strip()],
                    target_cid,
                    str(entry.get("parent_id", "") or staging_cid).strip() or staging_cid,
                ),
                timeout=min(import_timeout_seconds, 90),
            )
            moved_count += 1
            if target_savepath not in moved_savepaths:
                moved_savepaths.append(target_savepath)
            selected_savepath = target_savepath
            await write_subscription_log(
                f"已移动命中文件：{str(entry.get('rel_path', '') or entry.get('name', '') or '').strip()} → {target_savepath}",
                "success",
            )
        if skipped_duplicates > 0:
            await write_subscription_log(f"目标目录已有同名同大小文件，已跳过并清理中转副本 {skipped_duplicates} 个", "info")
        if moved_count <= 0:
            result_base["last_failed_detail"] = "选中文件均已在目标目录存在（同名同大小），无需移动"
            await write_subscription_log(str(result_base["last_failed_detail"]), "info")
            update_resource_job(
                job_id,
                status="completed",
                status_detail=result_base["last_failed_detail"],
                finished_at=now_text(),
            )
            return result_base

        auto_refresh = False
        for savepath in moved_savepaths:
            matched_monitor = match_monitor_task_for_savepath(cfg, savepath, provider="115")
            matched_name = str(matched_monitor.get("task_name", "") or "").strip()
            if matched_name:
                queue_monitor_job(
                    matched_name,
                    "resource",
                    {
                        "savepath": savepath,
                        "sharetitle": "",
                        "title": title,
                    },
                )
                auto_refresh = True
                await write_subscription_log(f"已触发监控精准刷新：{savepath}", "info")
        if not auto_refresh:
            await write_subscription_log("命中目录未纳入文件夹监控，入库后不会自动生成 STRM", "warn")

        selected_ids_list = sorted(selected_ids)
        retained = [entry for entry in files if str(entry.get("id", "") or "").strip() not in selected_ids]
        removed_old = 0
        for entry in retained:
            if _subscription_offline_file_older_than(entry, SUBSCRIPTION_OFFLINE_RETENTION_DAYS):
                await asyncio.to_thread(
                    provider_meta.delete_entries,
                    cookie,
                    [str(entry.get("id", "") or "").strip()],
                    str(entry.get("parent_id", "") or staging_cid).strip() or staging_cid,
                )
                removed_old += 1
        if removed_old > 0:
            await write_subscription_log(
                f"已清理中转目录过期未命中文件 {removed_old} 个（保留 {SUBSCRIPTION_OFFLINE_RETENTION_DAYS} 天）",
                "info",
            )
        if retained:
            await write_subscription_log(
                f"未命中文件保留在中转目录：{len(retained)} 个（{SUBSCRIPTION_OFFLINE_RETENTION_DAYS} 天后自动清理）",
                "info",
            )

        recorded_episodes = _clamp_episode_values(
            set(selection.get("recorded_episodes", set())),
            episode_upper_bound=single_season_episode_upper_bound,
        )
        candidate_episode = min(recorded_episodes) if recorded_episodes else max(0, int(candidate.get("episode", 0) or 0))
        candidate_season = max(0, int(candidate.get("season", 0) or 0))
        if media_type == "tv" and candidate_season <= 0:
            candidate_season = max(1, int(task.get("season", 1) or 1))
        resource_id = max(0, int(item.get("id", 0) or 0))
        create_subscription_match(
            task_name=task_name,
            resource_id=resource_id,
            job_id=job_id,
            media_type=media_type,
            season=candidate_season,
            episode=candidate_episode,
            total_episodes=known_total,
            score=100,
        )
        if media_type == "tv" and recorded_episodes:
            source_fp, content_fp = _build_subscription_episode_ledger_fingerprints(
                item,
                candidate,
                recorded_episodes,
                selected_ids_list,
            )
            upsert_subscription_episode_ledger(
                task_name=task_name,
                episodes=recorded_episodes,
                media_type="tv",
                season=candidate_season,
                score=100,
                resolution=0,
                source_fp=source_fp,
                content_fp=content_fp,
                link_type=link_type,
                link_url=link_url,
                resource_id=resource_id,
                job_id=job_id,
            )

        update_resource_job(
            job_id,
            status="completed",
            status_detail=f"115 离线入库完成：移动 {moved_count} 个文件到 {selected_savepath}",
            finished_at=now_text(),
        )
        result_base.update(
            {
                "ok": True,
                "job_id": job_id,
                "selected_savepath": selected_savepath,
                "successful_count": 1,
                "imported_episodes": sorted(recorded_episodes),
                "max_total_detected": known_total or len(recorded_episodes),
                "auto_refresh": auto_refresh,
                "reused_existing": False,
            }
        )
        return result_base
    except Exception as exc:
        last_detail = str(exc) or "115 离线导入失败"
        result_base["last_failed_detail"] = last_detail
        result_base["failed_attempts"] = 1
        await write_subscription_log(f"磁力/电驴离线入库失败：{last_detail}", "error")
        if job_id > 0:
            try:
                update_resource_job(
                    job_id,
                    status="failed",
                    status_detail=last_detail,
                    finished_at=now_text(),
                )
            except Exception:
                pass
        return result_base


def _build_fixed_115_subscription_search_result(
    task: Dict[str, Any],
    task_name: str,
    link_url: str,
    receive_code: str = "",
) -> Dict[str, Any]:
    normalized_link = str(link_url or "").strip()
    normalized_receive_code = normalize_receive_code(receive_code)
    provider = normalize_subscription_provider(task.get("provider", "115"), fallback="115")
    provider_meta = _get_provider_or_none(provider)
    provider_link_type = str(getattr(provider_meta, "link_type", "") or "").strip() or "115share"
    fixed_item = {
        "id": 0,
        "source_type": "subscription_fixed_link_fallback",
        "source_name": "固定分享链接兜底",
        "channel_name": "",
        "title": str(task.get("title", "") or task_name or "固定分享链接").strip() or "固定分享链接",
        "link_url": normalized_link,
        "link_type": provider_link_type,
        "message_url": "",
        "source_post_id": "",
        "raw_text": normalized_link,
        "receive_code": normalized_receive_code,
        "extra": {
            "receive_code": normalized_receive_code,
            "subscription_task_name": task_name,
            "subscription_fixed_link_fallback": True,
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
    return {
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
            "exclude_keyword_filtered": 0,
            "exclude_keyword_hits": {},
            "exclude_keywords": normalize_subscription_exclude_keywords(task.get("exclude_keywords", [])),
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
            "provider": provider,
        },
    }


async def _write_subscription_search_diagnostics(search_stats: Dict[str, Any], label: str) -> None:
    payload = search_stats if isinstance(search_stats, dict) else {}
    keyword_limit = int(payload.get("search_keyword_limit", 0) or 0)
    keyword_concurrency = int(payload.get("search_keyword_concurrency", 0) or 0)
    episode_total = int(payload.get("search_episode_total", 0) or 0)
    per_channel_limit = int(payload.get("search_limit_per_channel", 0) or 0)
    total_limit = int(payload.get("search_total_limit", 0) or 0)
    max_pages = int(payload.get("search_max_pages", 0) or 0)
    request_timeout = int(payload.get("search_request_timeout_seconds", 0) or 0)
    channel_timeout = int(payload.get("search_channel_timeout_seconds", 0) or 0)
    thread_limit = int(payload.get("search_thread_limit", 0) or 0)
    if keyword_limit > 0 or max_pages > 0 or request_timeout > 0 or channel_timeout > 0 or thread_limit > 0:
        total_limit_label = str(total_limit) if total_limit > 0 else "不截断"
        episode_total_label = str(episode_total) if episode_total > 0 else "--"
        await write_subscription_log(
            (
                f"{label}限速参数：关键词 {keyword_limit or '--'} 个，"
                f"关键词并发 {keyword_concurrency or '--'}，"
                f"频道并发 {thread_limit or '--'}，"
                f"任务集数 {episode_total_label}，"
                f"每频道候选 {per_channel_limit or '--'} 条，"
                f"全频道候选 {total_limit_label}，"
                f"每频道最多 {max_pages or '--'} 页，"
                f"单请求 {request_timeout or '--'} 秒，"
                f"单频道 {channel_timeout or '--'} 秒"
            ),
            "info",
            compact=f"搜索参数 | {keyword_limit or '--'} 关键词 · 并发 {keyword_concurrency or '--'} · "
                    f"每频道 {per_channel_limit or '--'} 条" + (
                    f" · 总上限 {total_limit_label}" if total_limit > 0 else ""),
        )
    cached_items = int(payload.get("channel_cached_items", payload.get("cached_items", 0)) or 0)
    cache_queries = int(payload.get("channel_cache_queries", payload.get("cache_queries", 0)) or 0)
    cache_errors = int(payload.get("channel_cache_errors", payload.get("cache_errors", 0)) or 0)
    channel_returned_items = int(payload.get("channel_returned_items", 0) or 0)
    channel_candidate_count = int(payload.get("channel_candidate_count", 0) or 0)
    channel_scored_items = int(payload.get("channel_scored_items", 0) or 0)
    pansou_items = int(payload.get("pansou_items", 0) or 0)
    pansou_returned_items = int(payload.get("pansou_returned_items", pansou_items) or 0)
    pansou_candidate_count = int(payload.get("pansou_candidate_count", 0) or 0)
    pansou_scored_items = int(payload.get("pansou_scored_items", 0) or 0)
    pansou_errors = int(payload.get("pansou_errors", 0) or 0)
    # 召回统计：文件日志保留详情，前端 SSE 合并为一条汇总
    recall_msg = f"{label}频道召回：返回 {channel_returned_items} 条，评分 {channel_scored_items} 条，入选候选 {channel_candidate_count} 条"
    if cached_items > 0:
        recall_msg += f"；缓存命中 {cached_items} 条（查询 {cache_queries or '--'} 组关键词）"
    if bool(payload.get("pansou_enabled", False)):
        recall_msg += f"；盘搜返回 {pansou_returned_items} 条，评分 {pansou_scored_items} 条，入选候选 {pansou_candidate_count} 条"
    compact_parts = [f"频道 {channel_candidate_count} 候选"]
    if cached_items > 0:
        compact_parts.append(f"缓存 {cached_items}")
    if bool(payload.get("pansou_enabled", False)):
        compact_parts.append(f"盘搜 {pansou_candidate_count} 候选")
    if channel_returned_items > 0 or cached_items > 0 or pansou_returned_items > 0:
        total_raw = channel_returned_items + cached_items + pansou_returned_items
        compact_parts.insert(0, f"原始 {total_raw}")
    await write_subscription_log(
        recall_msg, "info",
        compact=f"召回汇总 | {' · '.join(compact_parts)}",
    )
    if cache_errors > 0:
        await write_subscription_log(
            f"{label}本地缓存召回有 {cache_errors} 次查询异常，已忽略并继续执行",
            "warn",
        )
    if bool(payload.get("pansou_enabled", False)) and pansou_errors > 0:
        pansou_total_limit = int(payload.get("pansou_total_limit", 0) or 0)
        elapsed = max(0.0, float(payload.get("pansou_elapsed_seconds", 0.0) or 0.0))
        await write_subscription_log(
            (
                f"{label}盘搜召回：返回 {pansou_returned_items} 条，评分 {pansou_scored_items} 条，"
                f"入选候选 {pansou_candidate_count} 条，上限 {pansou_total_limit or '不截断'} 条，"
                f"异常 {pansou_errors} 次，用时 {elapsed:.1f} 秒"
            ),
            "warn",
        )
    slow_channels = payload.get("slow_channels", [])
    if not isinstance(slow_channels, list) or not slow_channels:
        return
    fragments: List[str] = []
    for row in slow_channels[:3]:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name", "") or row.get("channel_id", "") or "未知频道").strip()
        keyword = str(row.get("keyword", "") or "").strip()
        elapsed = max(0.0, float(row.get("elapsed_seconds", 0.0) or 0.0))
        pages = max(0, int(row.get("pages_scanned", 0) or 0))
        suffix = f"/{keyword}" if keyword else ""
        fragments.append(f"{name}{suffix} {elapsed:.1f}秒 {pages}页")
    if fragments:
        await write_subscription_log(f"{label}慢频道 Top：{'；'.join(fragments)}", "info")


async def _write_subscription_task_overview(
    task: Dict[str, Any],
    trigger: str,
    subscription_run_id: str,
    batch_refresh_enabled: bool,
) -> None:
    provider_label = format_subscription_provider_label(task.get("provider", "115"))
    media_label = format_subscription_media_type_label(task.get("media_type", "movie"))
    batch_refresh_label = "开启（内置固定）"
    if normalize_subscription_provider(task.get("provider", "115"), fallback="115") == "quark":
        batch_refresh_label = "关闭（夸克独立链路）"
    elif not batch_refresh_enabled:
        batch_refresh_label = "关闭"

    exclude_keywords = normalize_subscription_exclude_keywords(task.get("exclude_keywords", []))
    min_file_size_mb = normalize_subscription_min_file_size_mb(task.get("min_file_size_mb", 0))
    file_size_filter_tail = f" | 最小文件: {min_file_size_mb:g}MB" if min_file_size_mb > 0 else ""
    strict_title_tail = " | 匹配模式: 精准（简介命中不算同剧）" if is_subscription_strict_title_match(task) else ""
    await write_subscription_section("任务信息")
    await write_subscription_log(
        (
            f"订阅: {str(task.get('title', '') or task.get('name', '') or '--').strip()} | "
            f"类型: {media_label} | 网盘: {provider_label} | 触发: {format_subscription_trigger(trigger)}"
        ),
        "info",
        compact=f"任务 | {str(task.get('title', '') or task.get('name', '') or '--').strip()} | "
                f"{media_label} | {provider_label} | {format_subscription_trigger(trigger)}",
    )
    await write_subscription_log(
        f"保存路径: {str(task.get('savepath', '') or '--').strip()} | 执行批次: {subscription_run_id} | "
        f"批次收口刷新: {batch_refresh_label}"
        + file_size_filter_tail
        + strict_title_tail
        + (f" | 排除词: {', '.join(exclude_keywords[:5])}" if exclude_keywords else ""),
        "info",
        compact=f"配置 | 保存路径: {str(task.get('savepath', '') or '--').strip()} | "
                f"批次收口: {batch_refresh_label}"
                + (f" | 最小文件 {min_file_size_mb:g}MB" if min_file_size_mb > 0 else "")
                + (" | 精准匹配" if is_subscription_strict_title_match(task) else "")
                + (f" | 排除词: {len(exclude_keywords)}个" if exclude_keywords else ""),
    )
    scan_settings = normalize_subscription_scan_settings(task, task.get("provider", "115"))
    await write_subscription_log(
        (
            f"访问策略: 候选精查上限 {int(scan_settings.get('candidate_scan_prefetch_limit', 0) or 0)} | "
            f"候选并发 {int(scan_settings.get('candidate_scan_concurrency', 1) or 1)} | "
            f"目录并发 {int(scan_settings.get('share_scan_concurrency', 1) or 1)} | "
            f"分享请求间隔 {float(scan_settings.get('share_scan_rate_limit_seconds', 0) or 0):g}s"
        ),
        "info",
        compact=(
            f"配置 | 访问策略 | 候选上限 {int(scan_settings.get('candidate_scan_prefetch_limit', 0) or 0)} · "
            f"候选并发 {int(scan_settings.get('candidate_scan_concurrency', 1) or 1)} · "
            f"目录并发 {int(scan_settings.get('share_scan_concurrency', 1) or 1)} · "
            f"间隔 {float(scan_settings.get('share_scan_rate_limit_seconds', 0) or 0):g}s"
        ),
    )

    if int(task.get("tmdb_id", 0) or 0) > 0:
        tmdb_label = str(task.get("tmdb_title", "") or task.get("title", "") or "--").strip()
        tmdb_year = normalize_tmdb_year(task.get("tmdb_year", ""))
        tmdb_tail = f" ({tmdb_year})" if tmdb_year else ""
        await write_subscription_log(
            f"TMDB 绑定: {tmdb_label}{tmdb_tail} | ID: {int(task.get('tmdb_id', 0) or 0)}",
            "info",
        )

    if str(task.get("media_type", "movie") or "movie").strip().lower() == "tv":
        configured_total = resolve_subscription_tv_total_episodes(task, state_total=0)
        tv_mode_text = "多季合一" if is_subscription_multi_season_mode(task) else "单季订阅"
        if is_subscription_anime_compatible_task(task):
            tv_mode_text += " / 动漫兼容"
        season_label = "全季" if is_subscription_multi_season_mode(task) else f"S{int(task.get('season', 1) or 1):02d}"
        await write_subscription_log(
            f"追更设置: {season_label} | 总集数: {configured_total or '自动识别'} | 模式: {tv_mode_text}",
            "info",
        )


async def _write_subscription_notify_result_log(
    notify_result: Dict[str, Any],
    task: Dict[str, Any],
    item: Dict[str, Any],
) -> None:
    channel = str(notify_result.get("channel", "") or "").strip().lower()
    channel_label = "企业微信应用 API" if channel == "wecom_app" else "企业微信群机器人"
    provider_label = str(notify_result.get("provider_label", "") or "").strip() or format_subscription_provider_label(
        task.get("provider", "115")
    )
    link_type_label = str(notify_result.get("link_type_label", "") or "").strip() or format_resource_link_type_label(
        item.get("link_type", ""),
        item.get("link_url", ""),
    )
    episode_summary = str(notify_result.get("episode_summary", "") or "").strip()
    if episode_summary:
        await write_subscription_log(
            f"更新通知已推送到{channel_label} | 网盘: {provider_label} | 方式: {link_type_label} | 新增: {episode_summary}",
            "info",
        )
    else:
        await write_subscription_log(
            f"更新通知已推送到{channel_label} | 网盘: {provider_label} | 方式: {link_type_label}",
            "info",
        )
    if bool(notify_result.get("monitor_merged", False)):
        await write_subscription_log(
            (
                "文件夹监控通知已并入本次订阅通知"
                f" | 触发 {max(0, int(notify_result.get('monitor_triggered_groups', 0) or 0))} 组"
                f" / 覆盖 {max(0, int(notify_result.get('monitor_triggered_jobs', 0) or 0))} 个导入任务"
            ),
            "info",
        )


async def _refresh_subscription_task_tmdb_before_run(
    cfg: Dict[str, Any],
    task: Dict[str, Any],
    task_name: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    normalized_task = normalize_subscription_task(task or {})
    if str(normalized_task.get("media_type", "movie") or "movie").strip().lower() != "tv":
        return cfg, normalized_task
    if max(0, int(normalized_task.get("tmdb_id", 0) or 0)) <= 0:
        return cfg, normalized_task

    tmdb_config_error = validate_tmdb_runtime_config(cfg)
    if tmdb_config_error:
        await write_subscription_log(f"TMDB 绑定已配置，但本次无法刷新最新集数：{tmdb_config_error}", "warn")
        return cfg, normalized_task

    upsert_subscription_task_state(task_name, status="running", progress=8, detail="正在刷新 TMDB 最新集数")
    try:
        refresh_result = await asyncio.to_thread(
            refresh_subscription_task_tmdb_binding,
            task_name,
            normalized_task,
            cfg,
            True,
        )
    except Exception as exc:
        await write_subscription_log(f"刷新 TMDB 最新集数失败，将继续使用本地缓存配置：{exc}", "warn")
        return cfg, normalized_task

    refreshed_task = normalize_subscription_task(refresh_result.get("task", normalized_task))
    refreshed_cfg = normalize_config(refresh_result.get("cfg", cfg))
    if not refreshed_task:
        return cfg, normalized_task

    previous_total = max(0, int(refresh_result.get("previous_expected_total", 0) or 0))
    current_total = max(0, int(refresh_result.get("current_expected_total", 0) or 0))
    if bool(refresh_result.get("changed", False)):
        detail_parts: List[str] = []
        if previous_total != current_total and current_total > 0:
            detail_parts.append(f"集数 {previous_total or '--'} -> {current_total}")
        if bool(refresh_result.get("total_synced", False)):
            detail_parts.append("任务总集数已跟随 TMDB 同步")
        elif bool(refresh_result.get("total_override_preserved", False)):
            detail_parts.append("保留了任务里手动覆盖的总集数")
        detail_text = "；".join(detail_parts) if detail_parts else "任务绑定信息已更新"
        await write_subscription_log(f"TMDB 最新信息已刷新：{detail_text}", "info")
    else:
        stable_total = current_total or previous_total
        if stable_total > 0:
            await write_subscription_log(f"TMDB 最新集数已确认：当前任务按 {stable_total} 集计算", "info")
        else:
            await write_subscription_log("TMDB 最新信息已确认：当前任务绑定未变化", "info")
    return refreshed_cfg, refreshed_task


async def _run_subscription_task_quark(
    cfg: Dict[str, Any],
    task: Dict[str, Any],
    task_name: str,
    trigger: str,
    subscription_run_id: str,
    batch_refresh_enabled: bool,
    stage_timer: Optional[Dict[str, Any]] = None,
    manual_candidate: Optional[Dict[str, Any]] = None,
) -> None:
    await write_subscription_section("执行链路")
    await write_subscription_log("网盘链路: 夸克分享（独立评分与导入链路）", "info")
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

    manual_link_enabled = isinstance(manual_candidate, dict) and bool(str(manual_candidate.get("link_url", "") or "").strip())
    upsert_subscription_task_state(
        task_name,
        status="running",
        progress=15,
        detail="正在准备扫描链接候选" if manual_link_enabled else "正在主动搜索夸克资源",
    )
    check_subscription_cancelled()
    _subscription_stage_timer_enter(stage_timer, "search")
    search_started_at = time.perf_counter()
    if manual_link_enabled:
        search_result = _build_manual_subscription_search_result(task, task_name, manual_candidate or {}, "quark")
        await write_subscription_log("扫描链接模式已启用：跳过资源搜索，直接作为高优先级候选进入订阅扫描", "info")
    else:
        search_result = await find_subscription_task_match_candidate_by_search(
            task,
            last_episode=last_episode,
            trigger=trigger,
            total_episodes=known_total,
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
    await write_subscription_section("搜索结果")
    await write_subscription_log(
        f"夸克搜索关键词: " + " / ".join(search_keywords or [str(task.get("title", "")).strip() or "--"]),
        "info",
    )
    await write_subscription_log(
        (
            f"夸克搜索完成：资源检索 {searched_sources} 次，命中来源 {matched_channels} 个，"
            f"扫描页面 {pages_scanned} 页，候选资源 {deduped_items} 条，可导入资源 {supported_items} 条"
        ),
        "info",
    )
    await write_subscription_log(f"夸克搜索阶段耗时：{_format_elapsed_seconds(search_duration_seconds)}", "info")
    await _write_subscription_search_diagnostics(search_stats, "夸克搜索")
    if unsupported_items > 0:
        await write_subscription_log(
            f"已过滤 {unsupported_items} 条非夸克链接（当前 provider=quark，仅支持夸克分享）",
            "warn",
        )
    if int(search_stats.get("exclude_keyword_filtered", 0) or 0) > 0:
        exclude_hits = search_stats.get("exclude_keyword_hits", {}) if isinstance(search_stats.get("exclude_keyword_hits"), dict) else {}
        exclude_text = "，".join(
            f"{str(keyword)} {int(count or 0)} 条"
            for keyword, count in list(exclude_hits.items())[:5]
            if int(count or 0) > 0
        )
        await write_subscription_log(
            f"自定义排除词已过滤 {int(search_stats.get('exclude_keyword_filtered', 0) or 0)} 条候选"
            + (f"（{exclude_text}）" if exclude_text else ""),
            "warn",
        )
    if int(search_stats.get("title_blocked_candidates", 0) or 0) > 0:
        await write_subscription_log(
            f"已拦截 {int(search_stats.get('title_blocked_candidates', 0) or 0)} 条“仅集数命中/标题不匹配”候选",
            "warn",
        )
    if int(search_stats.get("strict_title_filtered", 0) or 0) > 0:
        strict_reasons = search_stats.get("strict_title_reasons", {}) if isinstance(search_stats.get("strict_title_reasons"), dict) else {}
        strict_reason_labels = {
            "strict_raw_text_only": "仅正文/简介命中",
            "raw_text_only_match": "仅正文/简介命中",
            "tmdb_id_conflict": "TMDB ID 不一致",
            "identity_title_mismatch": "片名身份不匹配",
            "strict_title_mismatch": "精准片名不匹配",
        }
        strict_reason_text = "，".join(
            f"{strict_reason_labels.get(str(key), str(key))} {int(value or 0)} 条"
            for key, value in strict_reasons.items()
            if int(value or 0) > 0
        )
        await write_subscription_log(
            f"精准匹配已过滤 {int(search_stats.get('strict_title_filtered', 0) or 0)} 条候选"
            + (f"（{strict_reason_text}）" if strict_reason_text else "（简介命中不算同剧证据）"),
            "warn",
        )
    if int(search_stats.get("title_match_media_relaxed_pass", search_stats.get("quark_media_relaxed_pass", 0)) or 0) > 0:
        await write_subscription_log(
            f"已放行 {int(search_stats.get('title_match_media_relaxed_pass', search_stats.get('quark_media_relaxed_pass', 0)) or 0)} 条“标题命中但无集数标记”候选，待后续精细扫描判定",
            "info",
        )
    if int(search_stats.get("title_match_low_score_kept", search_stats.get("quark_low_score_kept", 0)) or 0) > 0:
        await write_subscription_log(
            f"已保留 {int(search_stats.get('title_match_low_score_kept', search_stats.get('quark_low_score_kept', 0)) or 0)} 条低于阈值但标题命中的电视剧候选（召回优先）",
            "info",
        )
    if int(search_stats.get("season_guard_deferred", 0) or 0) > 0:
        await write_subscription_log(
            f"已延后 {int(search_stats.get('season_guard_deferred', 0) or 0)} 条标题季号不一致候选，后续按分享内容文件级筛选判定",
            "info",
        )
    if bool(search_stats.get("incremental_search_enabled", False)):
        watermark_overlap_posts = int(search_stats.get("incremental_watermark_overlap_posts", 0) or 0)
        watermark_overlap_tail = f"，软回看 {watermark_overlap_posts} 个消息位" if watermark_overlap_posts > 0 else ""
        await write_subscription_log(
            (
                f"频道增量搜索已启用：加载水位 {int(search_stats.get('incremental_channel_watermarks_loaded', 0) or 0)} 个，"
                f"命中增量边界 {int(search_stats.get('incremental_stop_channels', 0) or 0)} 个频道，"
                f"推进水位 {int(search_stats.get('incremental_channel_watermarks_advanced', 0) or 0)} 个频道，"
                f"异常未推进 {int(search_stats.get('incremental_channel_watermarks_error_channels', 0) or 0)} 个频道"
                f"{watermark_overlap_tail}"
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
            f"有 {len(search_errors)} 个资源搜索异常（不影响其余来源）："
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
        elif int(search_stats.get("exclude_keyword_filtered", 0) or 0) > 0 and int(search_stats.get("scored_items", 0) or 0) <= 0:
            detail = f"自定义排除词已过滤候选 {int(search_stats.get('exclude_keyword_filtered', 0) or 0)} 条，当前暂无可导入资源"
            status = "waiting"
        elif searched_sources <= 0:
            detail = "未启用任何 TG 订阅源，请先在参数配置里启用频道后重试"
            status = "waiting"
        elif supported_items <= 0:
            detail = "命中资源均非夸克分享链接，请调整频道或关键词"
            status = "waiting"
        elif int(search_stats.get("strict_title_filtered", 0) or 0) > 0 and int(search_stats.get("scored_items", 0) or 0) <= 0:
            detail = (
                f"精准匹配已过滤候选 {int(search_stats.get('strict_title_filtered', 0) or 0)} 条，"
                "当前暂无可导入资源"
            )
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
        effective_savepath = resolve_subscription_tv_scan_savepath(task, base_savepath) or base_savepath
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
    candidate_scan_prewarm_stats: Dict[str, Any] = {}

    def consume_background_task_result(task_obj: asyncio.Task) -> None:
        try:
            task_obj.result()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("后台任务异常: %s", exc, exc_info=True)

    _subscription_stage_timer_enter(stage_timer, "import")
    candidate_queue = list(attempt_candidates)
    if task["media_type"] == "tv" and candidate_queue:
        candidate_scan_prewarm_stats = await _prewarm_subscription_candidate_share_manifests(
            cookie=cookie_quark,
            task=task,
            candidates=candidate_queue,
            provider="quark",
            manifest_cache=quark_manifest_cache,
            label="夸克",
            max_candidates=min(len(candidate_queue), max_attempts),
        )
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
        candidate_season_mismatch_deferred = bool(candidate.get("season_mismatch_deferred", False))
        if candidate_season_mismatch_deferred:
            candidate_episode_values = set()
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
            savepath_season = max(1, int(task.get("season", 1) or 1)) if candidate_season_mismatch_deferred else candidate_season
            candidate_savepath = (
                build_subscription_tv_savepath(
                    task,
                    base_savepath,
                    season=savepath_season,
                    episode=episode,
                )
                or effective_savepath
            )

        selected_share_episode_values: Set[int] = set()
        selected_share_file_samples: List[str] = []
        precise_selection: Dict[str, Any] = {}
        precise_stats: Dict[str, Any] = {}
        if task["media_type"] == "tv":
            if (
                candidate_episode_values
                and last_episode > 0
                and max(candidate_episode_values) <= last_episode
                and (not existing_episode_scan_ready)
                and (not completed_locked)
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
            if not precise_missing_episode_values:
                episode_upper = known_total
                if single_season_episode_upper_bound > 0:
                    episode_upper = min(episode_upper, single_season_episode_upper_bound) if episode_upper > 0 else single_season_episode_upper_bound
                start_episode = 1 if existing_episode_scan_ready or last_episode <= 0 else max(1, last_episode + 1)
                if episode_upper >= start_episode:
                    precise_missing_episode_values = set(range(start_episode, episode_upper + 1))

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
            if (
                (not precise_missing_episode_values)
                and existing_episode_scan_ready
                and (known_total > 0 or single_season_episode_upper_bound > 0)
            ):
                skipped_existing_candidates += 1
                target_upper = single_season_episode_upper_bound or known_total
                await write_subscription_log(
                    f"候选资源 #{index} 目标季目录已覆盖 E1-E{target_upper}，已跳过避免整包导入",
                    "info",
                )
                continue

            if precise_missing_episode_values:
                manifest_cache_key = candidate_share_key or candidate_link_url or f"resource:{resource_id}"
                manifest_payload = quark_manifest_cache.get(manifest_cache_key)
                if manifest_payload:
                    precise_selection, precise_stats = _build_tv_share_selection_from_manifest(
                        manifest_payload,
                        precise_missing_episode_values,
                        task=task,
                    )
                else:
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
                if (not precise_ids) and manifest_payload and bool(manifest_payload.get("truncated", False)):
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
                        manifest_payload = quark_manifest_cache.get(manifest_cache_key)
                        if not manifest_payload:
                            manifest_payload = await _scan_subscription_share_tree_snapshot(
                                cookie_quark,
                                task,
                                item,
                                max_depth=5,
                                per_request_timeout=max(12, int(SUBSCRIPTION_SHARE_SCAN_REQUEST_TIMEOUT_SECONDS or 12)),
                                force_refresh=False,
                            )
                            quark_manifest_cache[manifest_cache_key] = manifest_payload
                        scanned_dirs = max(scanned_dirs, int((manifest_payload or {}).get("scanned_dirs", 0) or 0))
                        scanned_entries = max(scanned_entries, int((manifest_payload or {}).get("scanned_entries", 0) or 0))
                        if isinstance(precise_stats, dict):
                            precise_stats = dict(precise_stats)
                            precise_stats["scanned_dirs"] = scanned_dirs
                            precise_stats["scanned_entries"] = scanned_entries
                            for scan_key in (
                                "returned_entries",
                                "provider_reported_entries",
                                "provider_pages_scanned",
                                "file_count",
                                "provider_truncated_dirs",
                                "truncated_reason",
                            ):
                                if scan_key in (manifest_payload or {}):
                                    precise_stats[scan_key] = (manifest_payload or {}).get(scan_key)
                            precise_stats["truncated"] = bool(
                                precise_stats.get("truncated", False) or (manifest_payload or {}).get("truncated", False)
                            )
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
                    scan_tail = _format_subscription_share_scan_log_tail(precise_stats)
                    excluded_type_tail = _format_subscription_excluded_file_type_tail(precise_stats)
                    await write_subscription_log(
                        (
                            f"候选资源 #{index} 精细筛选未命中缺失集（目标 {_format_episode_preview(precise_missing_episode_values)}，"
                            f"原因 {reason_label}，{scan_tail}{excluded_type_tail}），"
                            "已跳过整包导入"
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
                scan_tail = _format_subscription_share_scan_log_tail(precise_stats)
                if fallback_used:
                    await write_subscription_log(
                        (
                            f"候选资源 #{index} 原目标 {_format_episode_preview(precise_missing_episode_values)} 未命中，"
                            f"已按清单回退识别 {_format_episode_preview(fallback_missing_episode_values)} 并筛选 "
                            f"{len(precise_ids)} 个文件后转存（{scan_tail}）{dedupe_tail}"
                        ),
                        "info",
                    )
                else:
                    await write_subscription_log(
                        (
                            f"候选资源 #{index} 已按缺失集筛选 {len(precise_ids)} 个文件后转存"
                            f"（目标 {_format_episode_preview(precise_missing_episode_values)}，{scan_tail}）{dedupe_tail}"
                        ),
                        "info",
                    )

            if not precise_selection:
                manifest_cache_key = candidate_share_key or candidate_link_url or f"resource:{resource_id}"
                manifest_payload = quark_manifest_cache.get(manifest_cache_key)
                if not manifest_payload:
                    manifest_payload = await _scan_subscription_share_tree_snapshot(
                        cookie_quark,
                        task,
                        item,
                        max_depth=5,
                        per_request_timeout=max(12, int(SUBSCRIPTION_SHARE_SCAN_REQUEST_TIMEOUT_SECONDS or 12)),
                        force_refresh=False,
                    )
                    quark_manifest_cache[manifest_cache_key] = manifest_payload
                elif bool(manifest_payload.get("truncated", False)):
                    refreshed_manifest_payload = await _scan_subscription_share_tree_snapshot(
                        cookie_quark,
                        task,
                        item,
                        max_depth=5,
                        per_request_timeout=max(12, int(SUBSCRIPTION_SHARE_SCAN_REQUEST_TIMEOUT_SECONDS or 12)),
                        force_refresh=False,
                    )
                    if refreshed_manifest_payload:
                        manifest_payload = refreshed_manifest_payload
                        quark_manifest_cache[manifest_cache_key] = manifest_payload
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
                manifest_missing_episode_values = {
                    episode_no
                    for episode_no in manifest_episodes
                    if episode_no not in existing_folder_episodes
                }
                if manifest_missing_episode_values:
                    precise_selection, precise_stats = _build_tv_share_selection_from_manifest(
                        manifest_payload,
                        manifest_missing_episode_values,
                        task=task,
                    )
                else:
                    precise_stats = {
                        "reason": (
                            "manifest_no_missing"
                            if manifest_episodes
                            else str((manifest_payload or {}).get("reason", "") or "manifest_empty").strip()
                        ),
                        "scanned_dirs": max(0, int((manifest_payload or {}).get("scanned_dirs", 0) or 0)),
                        "scanned_entries": max(0, int((manifest_payload or {}).get("scanned_entries", 0) or 0)),
                        "exclude_file_extensions": normalize_subscription_exclude_file_extensions(
                            (manifest_payload or {}).get("exclude_file_extensions", [])
                        ),
                        "skipped_excluded_file_types": max(
                            0,
                            int(
                                (manifest_payload or {}).get(
                                    "skipped_excluded_file_types",
                                    (manifest_payload or {}).get("skipped_archive_files", 0),
                                )
                                or 0
                            ),
                        ),
                        "skipped_archive_files": max(
                            0,
                            int(
                                (manifest_payload or {}).get(
                                    "skipped_excluded_file_types",
                                    (manifest_payload or {}).get("skipped_archive_files", 0),
                                )
                                or 0
                            ),
                        ),
                    }
                precise_ids = (
                    precise_selection.get("selected_ids", [])
                    if isinstance(precise_selection.get("selected_ids"), list)
                    else []
                )
                if not precise_ids:
                    skipped_precise_mismatch_candidates += 1
                    reason = str((precise_stats or {}).get("reason", "") or "no_precise_episode_match").strip()
                    reason_label = _format_subscription_reason_chain(reason)
                    scan_tail = _format_subscription_share_scan_log_tail(precise_stats)
                    excluded_type_tail = _format_subscription_excluded_file_type_tail(precise_stats)
                    await write_subscription_log(
                        (
                            f"候选资源 #{index} 清单精查未能定位目标季剧集文件"
                            f"（原因 {reason_label}，{scan_tail}{excluded_type_tail}），"
                            "已跳过整包导入"
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
                excluded_type_tail = _format_subscription_excluded_file_type_tail(manifest_payload)
                await write_subscription_log(
                    (
                        f"候选资源 #{index} 标题未给出明确集数，已按分享清单识别 "
                        f"{_format_episode_preview(selected_share_episode_values)} 并筛选 {len(precise_ids)} 个文件后转存"
                        f"{dedupe_tail}{excluded_type_tail}"
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
                "candidate_scan_prewarm": candidate_scan_prewarm_stats,
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
    episode_log_tail = _build_subscription_matched_episode_log_tail(task, imported_episode_list)
    matched_display_title = pick_subscription_display_title(task, item, fallback=f"资源#{resource_id}")
    import_type_label = format_resource_link_type_label(item.get("link_type", ""), item.get("link_url", ""))

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
            f"命中「{matched_display_title}」（评分 {score}，方式 {import_type_label}），本轮已执行 {successful_count} 个夸克导入任务"
            f"（首个 #{job_id}），保存到 {selected_job_savepath}；夸克链路不触发监控刷新{episode_log_tail}"
        )
    else:
        detail = (
            f"命中「{matched_display_title}」（评分 {score}，方式 {import_type_label}），已创建并执行夸克导入任务 #{job_id}，"
            f"保存到 {selected_job_savepath}；夸克链路不触发监控刷新{episode_log_tail}"
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
            "candidate_scan_prewarm": candidate_scan_prewarm_stats,
            **existing_episode_scan_stats,
            **search_stats,
        },
    )
    import_summary_text, import_summary_level = _build_subscription_import_summary_log(
        task,
        imported_episode_list,
        next_episode=next_episode,
        total_episodes=next_total,
    )
    if import_summary_text:
        await write_subscription_log(import_summary_text, import_summary_level)
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
            await _write_subscription_notify_result_log(notify_result, task, item)
    except Exception as notify_exc:
        await write_subscription_log(f"订阅成功通知推送失败：{notify_exc}", "warn")
    update_subscription_summary("执行成功", detail)

async def run_subscription_task(
    task_name: str,
    trigger: str = "manual",
    manual_candidate: Optional[Dict[str, Any]] = None,
) -> None:
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
    provider_meta = _get_provider_or_none(provider)
    provider_link_type = str(getattr(provider_meta, "link_type", "") or "").strip() or ("quark" if provider == "quark" else "115share")
    provider_label = str(getattr(provider_meta, "label", "") or provider).strip()
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
    scan_runtime_settings = normalize_subscription_scan_settings(task, provider)
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
            "scan_settings": scan_runtime_settings,
        },
    )
    share_runtime_cache_token = _subscription_share_entry_runtime_cache_var.set({})
    share_refreshed_keys_token = _subscription_share_entry_refreshed_keys_var.set(set())
    share_scan_settings_token = set_subscription_share_scan_runtime_settings(task, provider)
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
        cfg, task = await _refresh_subscription_task_tmdb_before_run(cfg, task, task_name)
        await _write_subscription_task_overview(
            task=task,
            trigger=trigger,
            subscription_run_id=subscription_run_id,
            batch_refresh_enabled=batch_refresh_enabled,
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
                manual_candidate=manual_candidate,
            )
            return
        await write_subscription_section("执行链路")
        await write_subscription_log(f"网盘链路: {provider_label}（资源搜索与导入链路）", "info")
        task_share_subdir = normalize_relative_path(str(task.get("share_subdir", "") or "").strip())
        task_share_subdir_cid = _normalize_subscription_share_subdir_cid(task.get("share_subdir_cid", ""))
        task_share_link_url = str(task.get("share_link_url", "") or "").strip()
        task_share_link_receive_code = normalize_receive_code(task.get("share_link_receive_code", ""))
        task_share_link_type = resolve_resource_link_type("", task_share_link_url)
        use_fixed_share_link = bool(task_share_link_url) and task_share_link_type == provider_link_type
        manual_link_enabled = isinstance(manual_candidate, dict) and bool(str(manual_candidate.get("link_url", "") or "").strip())
        fixed_link_fallback_enabled = (
            (not manual_link_enabled)
            and use_fixed_share_link
            and bool(task.get("fixed_link_channel_search", False))
        )
        fixed_link_channel_search_enabled = fixed_link_fallback_enabled
        if task_share_subdir_cid and (not fixed_link_fallback_enabled):
            # CID 仅对固定分享链接兜底候选稳定有效，资源搜索候选不套用该锚点。
            task_share_subdir_cid = ""
        task_share_scope_enabled = fixed_link_fallback_enabled and bool(task_share_subdir or task_share_subdir_cid)
        task_share_scope_label = _format_subscription_share_scope_label(task_share_subdir, task_share_subdir_cid)
        if task_share_link_url and (not use_fixed_share_link):
            await write_subscription_log(
                f"固定链接已配置但不是 {provider_label} 分享链接，已自动忽略并继续资源搜索",
                "warn",
            )
        if manual_link_enabled:
            await write_subscription_log(
                "扫描链接模式已启用：跳过资源搜索，直接作为高优先级候选进入订阅扫描",
                "info",
            )
        elif fixed_link_fallback_enabled:
            await write_subscription_log(
                f"固定链接兜底已启用：将先执行资源搜索，再把固定 {provider_label} 分享链接追加为备选候选",
                "info",
            )
        elif use_fixed_share_link:
            await write_subscription_log(
                "固定链接已填写但未启用兜底，本次仍以资源搜索为主",
                "info",
            )
        if task_share_scope_enabled:
            await write_subscription_log(
                f"固定链接兜底子目录已启用：{task_share_scope_label}（仅对固定链接候选生效）",
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
                "正在准备扫描链接候选"
                if manual_link_enabled
                else (
                    "正在执行资源搜索，固定链接将作为备选"
                    if fixed_link_fallback_enabled
                    else "正在主动搜索资源"
                )
            ),
        )
        check_subscription_cancelled()
        _subscription_stage_timer_enter(stage_timer, "search")
        search_started_at = time.perf_counter()
        search_result: Dict[str, Any] = {}
        resource_search_result: Dict[str, Any] = {}
        if manual_link_enabled:
            search_result = _build_manual_subscription_search_result(task, task_name, manual_candidate or {}, provider)
        else:
            resource_search_result = await find_subscription_task_match_candidate_by_search(
                task,
                last_episode=last_episode,
                trigger=trigger,
                total_episodes=known_total,
            )
            search_result = resource_search_result
            if fixed_link_fallback_enabled:
                fixed_link_url = apply_share_receive_code_to_url(task_share_link_url, task_share_link_receive_code)
                fixed_search_result = _build_fixed_115_subscription_search_result(
                    task,
                    task_name,
                    fixed_link_url,
                    task_share_link_receive_code,
                )
                await write_subscription_log(
                    "固定链接兜底候选已生成，将排在资源搜索候选之后",
                    "info",
                )
                search_result = merge_subscription_search_results(
                    fixed_search_result,
                    resource_search_result,
                    fixed_candidates_last=True,
                )
        search_duration_seconds = max(0.0, time.perf_counter() - search_started_at)
        search_stats = search_result.get("stats", {}) if isinstance(search_result.get("stats"), dict) else {}
        search_errors = search_result.get("errors", []) if isinstance(search_result.get("errors"), list) else []
        search_keywords = search_result.get("keywords", []) if isinstance(search_result.get("keywords"), list) else []
        if fixed_link_fallback_enabled:
            await write_subscription_log(
                f"固定链接兜底候选已就绪：{task_share_link_url}",
                "info",
            )
            if task_share_link_receive_code:
                await write_subscription_log("固定链接提取码已生效", "info")
        if not manual_link_enabled:
            search_label = "资源搜索"
            resource_log_keywords = (
                resource_search_result.get("keywords", [])
                if isinstance(resource_search_result.get("keywords", []), list)
                else search_keywords
            )
            await write_subscription_section("搜索结果")
            searched_sources = int(
                (
                    search_stats.get("channel_searched_sources", search_stats.get("searched_sources", 0))
                    if fixed_link_fallback_enabled
                    else search_stats.get("searched_sources", 0)
                )
                or 0
            )
            matched_channels = int(
                (
                    search_stats.get("channel_matched_channels", search_stats.get("matched_channels", 0))
                    if fixed_link_fallback_enabled
                    else search_stats.get("matched_channels", 0)
                )
                or 0
            )
            pages_scanned = int(
                (
                    search_stats.get("channel_pages_scanned", search_stats.get("pages_scanned", 0))
                    if fixed_link_fallback_enabled
                    else search_stats.get("pages_scanned", 0)
                )
                or 0
            )
            deduped_items = int(
                (
                    search_stats.get("channel_deduped_items", search_stats.get("deduped_items", 0))
                    if fixed_link_fallback_enabled
                    else search_stats.get("deduped_items", 0)
                )
                or 0
            )
            supported_items = int(
                (
                    search_stats.get("channel_supported_items", search_stats.get("supported_items", 0))
                    if fixed_link_fallback_enabled
                    else search_stats.get("supported_items", 0)
                )
                or 0
            )
            unsupported_items = int(
                (
                    search_stats.get("channel_unsupported_items", search_stats.get("unsupported_items", 0))
                    if fixed_link_fallback_enabled
                    else search_stats.get("unsupported_items", 0)
                )
                or 0
            )
            await write_subscription_log(
                f"{search_label}关键词: " + " / ".join(resource_log_keywords or [str(task.get("title", "")).strip() or "--"]),
                "info",
            )
            await write_subscription_log(
                (
                    f"{search_label}完成：资源检索 {searched_sources} 次，"
                    f"命中来源 {matched_channels} 个，"
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
            await _write_subscription_search_diagnostics(search_stats, search_label)
            if unsupported_items > 0:
                supported_link_label = f"{provider_label} 分享"
                await write_subscription_log(
                    f"已过滤 {unsupported_items} 条不支持链接（仅支持 {supported_link_label}）",
                    "warn",
                )
            if int(search_stats.get("exclude_keyword_filtered", 0) or 0) > 0:
                exclude_hits = search_stats.get("exclude_keyword_hits", {}) if isinstance(search_stats.get("exclude_keyword_hits"), dict) else {}
                exclude_text = "，".join(
                    f"{str(keyword)} {int(count or 0)} 条"
                    for keyword, count in list(exclude_hits.items())[:5]
                    if int(count or 0) > 0
                )
                await write_subscription_log(
                    f"自定义排除词已过滤 {int(search_stats.get('exclude_keyword_filtered', 0) or 0)} 条候选"
                    + (f"（{exclude_text}）" if exclude_text else ""),
                    "warn",
                )
            if int(search_stats.get("strict_title_filtered", 0) or 0) > 0:
                strict_reasons = search_stats.get("strict_title_reasons", {}) if isinstance(search_stats.get("strict_title_reasons"), dict) else {}
                strict_reason_labels = {
                    "strict_raw_text_only": "仅正文/简介命中",
                    "raw_text_only_match": "仅正文/简介命中",
                    "tmdb_id_conflict": "TMDB ID 不一致",
                    "identity_title_mismatch": "片名身份不匹配",
                    "strict_title_mismatch": "精准片名不匹配",
                }
                strict_reason_text = "，".join(
                    f"{strict_reason_labels.get(str(key), str(key))} {int(value or 0)} 条"
                    for key, value in strict_reasons.items()
                    if int(value or 0) > 0
                )
                await write_subscription_log(
                    f"精准匹配已过滤 {int(search_stats.get('strict_title_filtered', 0) or 0)} 条候选"
                    + (f"（{strict_reason_text}）" if strict_reason_text else "（简介命中不算同剧证据）"),
                    "warn",
                )
            if int(search_stats.get("media_guard_filtered", 0) or 0) > 0:
                media_reasons = search_stats.get("media_guard_reasons", {}) if isinstance(search_stats.get("media_guard_reasons"), dict) else {}
                reason_labels = {
                    "episode_like": "电影命中剧集资源",
                    "tv_like": "电影命中电视剧关键词",
                    "movie_like": "电视剧命中电影资源",
                    "missing_episode_meta": "电视剧缺少季集信息",
                    "title_mismatch": "标题不匹配",
                    "strict_raw_text_only": "仅正文/简介命中",
                    "raw_text_only_match": "仅正文/简介命中",
                    "tmdb_id_conflict": "TMDB ID 不一致",
                    "identity_title_mismatch": "片名身份不匹配",
                    "strict_title_mismatch": "精准片名不匹配",
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
            if int(search_stats.get("season_guard_deferred", 0) or 0) > 0:
                await write_subscription_log(
                    f"已延后 {int(search_stats.get('season_guard_deferred', 0) or 0)} 条标题季号不一致候选，后续按分享内容文件级筛选判定",
                    "info",
                )
            if int(search_stats.get("title_match_media_relaxed_pass", 0) or 0) > 0:
                await write_subscription_log(
                    f"已放行 {int(search_stats.get('title_match_media_relaxed_pass', 0) or 0)} 条“标题命中但无集数标记”候选，待后续精细扫描判定",
                    "info",
                )
            if int(search_stats.get("title_match_low_score_kept", 0) or 0) > 0:
                await write_subscription_log(
                    f"已保留 {int(search_stats.get('title_match_low_score_kept', 0) or 0)} 条低于阈值但标题命中的电视剧候选（召回优先）",
                    "info",
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
                watermark_overlap_posts = int(search_stats.get("incremental_watermark_overlap_posts", 0) or 0)
                watermark_overlap_tail = f"，软回看 {watermark_overlap_posts} 个消息位" if watermark_overlap_posts > 0 else ""
                await write_subscription_log(
                    (
                        f"频道增量搜索已启用：加载水位 {int(search_stats.get('incremental_channel_watermarks_loaded', 0) or 0)} 个，"
                        f"命中增量边界 {int(search_stats.get('incremental_stop_channels', 0) or 0)} 个频道，"
                        f"推进水位 {int(search_stats.get('incremental_channel_watermarks_advanced', 0) or 0)} 个频道，"
                        f"异常未推进 {int(search_stats.get('incremental_channel_watermarks_error_channels', 0) or 0)} 个频道"
                        f"{watermark_overlap_tail}"
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
                    f"有 {len(search_errors)} 个资源搜索异常（不影响其余来源，{search_label}阶段）："
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
            elif fixed_link_fallback_enabled:
                detail = "资源搜索与固定分享链接兜底均未命中可导入资源，请检查固定链接/提取码或资源搜索配置后重试"
                status = "waiting"
            elif manual_link_enabled:
                detail = "扫描链接当前不可用，请检查链接/提取码或稍后重试"
                status = "waiting"
            elif int(search_stats.get("searched_sources", 0) or 0) <= 0:
                detail = "未启用任何 TG 订阅源，请先在参数配置里启用频道后重试"
                status = "waiting"
            elif int(search_stats.get("exclude_keyword_filtered", 0) or 0) > 0 and int(search_stats.get("scored_items", 0) or 0) <= 0:
                detail = f"自定义排除词已过滤候选 {int(search_stats.get('exclude_keyword_filtered', 0) or 0)} 条，当前暂无可导入资源"
                status = "waiting"
            elif int(search_stats.get("supported_items", 0) or 0) <= 0:
                supported_link_label = f"{provider_label} 分享"
                detail = f"命中资源均非可导入类型（仅支持 {supported_link_label}），请调整频道或关键词"
                status = "waiting"
            elif int(search_stats.get("strict_title_filtered", 0) or 0) > 0 and int(search_stats.get("scored_items", 0) or 0) <= 0:
                detail = (
                    f"精准匹配已过滤候选 {int(search_stats.get('strict_title_filtered', 0) or 0)} 条，"
                    "当前暂无可导入资源"
                )
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
            effective_savepath = resolve_subscription_tv_scan_savepath(task, base_savepath) or base_savepath
        check_subscription_cancelled()
        _subscription_stage_timer_enter(stage_timer, "calibrate")
        upsert_subscription_task_state(task_name, status="running", progress=45, detail="正在准备目标目录")
        if not provider_meta:
            raise RuntimeError("订阅网盘类型不支持")
        cookie_115 = provider_meta.get_cookie(cfg)
        folder_id = await asyncio.to_thread(
            provider_meta.ensure_folder_id_by_path,
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
                    _scan_provider_existing_tv_episodes,
                    provider_meta,
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
        batch_episode_decision = _build_subscription_episode_batch_decision(
            task,
            trigger=trigger,
            existing_episode_scan_ready=existing_episode_scan_ready,
            existing_episode_scan_reliable=existing_episode_scan_reliable,
            existing_folder_episodes=existing_folder_episodes,
            single_season_episode_upper_bound=single_season_episode_upper_bound,
            candidates=attempt_candidates,
        )
        batch_episode_import = bool(batch_episode_decision.get("enabled", False))
        batch_episode_import_reason = str(batch_episode_decision.get("reason", "") or "").strip()
        if batch_episode_import and task["media_type"] == "tv" and existing_episode_scan_ready and not trigger_is_manual:
            attempt_candidates = _prioritize_tv_candidates_by_missing_episodes(
                attempt_candidates,
                existing_folder_episodes,
                last_episode,
                prefer_backfill=True,
                episode_upper_bound=single_season_episode_upper_bound,
            )
            target_missing_count = max(0, int(batch_episode_decision.get("target_missing_count", 0) or 0))
            candidate_missing_values = {
                max(0, int(value or 0))
                for value in (
                    batch_episode_decision.get("candidate_missing_episodes", [])
                    if isinstance(batch_episode_decision.get("candidate_missing_episodes", []), list)
                    else []
                )
                if max(0, int(value or 0)) > 0
            }
            reason_labels = {
                "initial_empty_target": "目标目录为空，需补齐首轮已发布剧集",
                "candidate_missing_episodes": "候选集数命中本地缺失集",
                "backfill_gap": "目标目录存在中间缺集",
                "manifest_pending_missing_check": "候选标题未稳定给出集数，需逐个按分享清单精查",
            }
            reason_label = reason_labels.get(batch_episode_import_reason, batch_episode_import_reason or "缺集补齐")
            candidate_tail = (
                f"，候选缺失 {_format_episode_preview(candidate_missing_values)}"
                if candidate_missing_values
                else ""
            )
            await write_subscription_log(
                (
                    f"自动缺集补齐模式已启用：{reason_label}"
                    f"{'，目标缺失 ' + str(target_missing_count) + ' 集' if target_missing_count > 0 else ''}"
                    f"{candidate_tail}"
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
            batch_mode_label = "手动追更批量模式" if trigger_is_manual else "自动缺集补齐模式"
            await write_subscription_log(
                f"{batch_mode_label}：同集/同范围最多保留 {bucket_limit_per_episode} 条，补齐候选 {len(attempt_candidates)} 条，本轮全部纳入尝试队列",
                "info",
            )

        invalid_link_cache = (
            {}
            if manual_link_enabled
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

        max_attempts = max(1, len(attempt_candidates) if batch_episode_import else min(8, len(attempt_candidates)))
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
        skipped_precise_mismatch_candidates = 0
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
        share_manifest_cache: Dict[str, Dict[str, Any]] = {}
        fixed_share_runtime_initialized = False
        fixed_share_runtime_selection: Dict[str, Any] = {}
        fixed_share_runtime_subdir_stats: Dict[str, Any] = {}
        fixed_share_runtime_manifest: Dict[str, Any] = {}
        savepath_folder_id_cache: Dict[str, str] = {effective_savepath: str(folder_id or "").strip()}
        candidate_scan_prewarm_stats: Dict[str, Any] = {}
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
                _scan_provider_existing_tv_episodes,
                provider_meta,
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
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning("后台任务异常: %s", exc, exc_info=True)

        _subscription_stage_timer_enter(stage_timer, "import")
        offline_import_handled = False
        if manual_link_enabled and attempt_candidates:
            offline_meta = _subscription_offline_candidate(attempt_candidates[0])
            if offline_meta:
                offline_import_result = await _run_subscription_manual_offline_import(
                    task=task,
                    task_name=task_name,
                    cfg=cfg,
                    provider_meta=provider_meta,
                    cookie=cookie_115,
                    candidate=offline_meta["candidate"],
                    item=offline_meta["item"],
                    link_type=offline_meta["link_type"],
                    staging_root=_get_subscription_offline_staging_root(cfg),
                    effective_savepath=effective_savepath,
                    base_savepath=base_savepath,
                    folder_id=folder_id,
                    monitor_task_name=monitor_task_name,
                    last_episode=last_episode,
                    known_total=known_total,
                    single_season_episode_upper_bound=single_season_episode_upper_bound,
                    existing_folder_episodes=existing_folder_episodes,
                    existing_episode_scan_ready=existing_episode_scan_ready,
                    subscription_run_id=subscription_run_id,
                    batch_refresh_enabled=batch_refresh_enabled,
                    import_timeout_seconds=import_timeout_seconds,
                )
                offline_import_handled = True
                attempted_candidates = 1
                scanned_candidates = 1
                if offline_import_result.get("ok"):
                    selected_candidate = attempt_candidates[0]
                    selected_item = offline_meta["item"]
                    selected_job_id = max(0, int(offline_import_result.get("job_id", 0) or 0))
                    selected_auto_refresh = bool(offline_import_result.get("auto_refresh", False))
                    selected_reused_existing = False
                    selected_job_savepath = str(
                        offline_import_result.get("selected_savepath", "") or effective_savepath
                    )
                    successful_count = 1
                    if selected_job_id > 0:
                        successful_job_ids.append(selected_job_id)
                    offline_imported = {
                        max(0, int(ep or 0))
                        for ep in (
                            offline_import_result.get("imported_episodes", [])
                            if isinstance(offline_import_result.get("imported_episodes"), list)
                            else []
                        )
                        if max(0, int(ep or 0)) > 0
                    }
                    imported_episodes.update(offline_imported)
                    if existing_episode_scan_ready:
                        existing_folder_episodes.update(offline_imported)
                        existing_episode_count = len(existing_folder_episodes)
                    max_total_detected = max(0, int(offline_import_result.get("max_total_detected", 0) or 0))
                    attempt_candidates[0]["episode"] = (
                        min(offline_imported) if offline_imported else max(0, int(attempt_candidates[0].get("episode", 0) or 0))
                    )
                    attempt_candidates[0]["season"] = (
                        max(1, int(task.get("season", 1) or 1))
                        if task["media_type"] == "tv"
                        else 0
                    )
                    attempt_candidates[0]["total"] = max_total_detected or known_total
                else:
                    failed_attempts = 1
                    last_failed_detail = str(
                        offline_import_result.get("last_failed_detail", "") or "115 离线导入失败"
                    )
                    if int(offline_import_result.get("timed_out_attempts", 0) or 0) > 0:
                        timed_out_attempts = 1
        if task["media_type"] == "tv" and attempt_candidates and not offline_import_handled:
            candidate_scan_prewarm_stats = await _prewarm_subscription_candidate_share_manifests(
                cookie=cookie_115,
                task=task,
                candidates=attempt_candidates,
                provider=provider,
                manifest_cache=share_manifest_cache,
                label=provider_label,
                share_subdir="",
                share_subdir_cid="",
                subdir_selection_cache=share_subdir_selection_cache,
                subdir_selection_stats_cache=share_subdir_selection_stats_cache,
                max_candidates=min(len(attempt_candidates), max_scan_candidates),
            )
        for index, candidate in enumerate(attempt_candidates, start=1) if not offline_import_handled else ():
            if attempted_candidates >= max_attempts:
                break
            if scanned_candidates >= max_scan_candidates:
                break
            scanned_candidates += 1
            check_subscription_cancelled()
            item = candidate.get("item", {}) if isinstance(candidate.get("item"), dict) else {}
            resource_id = int(item.get("id", 0) or 0)
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
            candidate_season_mismatch_deferred = bool(candidate.get("season_mismatch_deferred", False))
            if candidate_season_mismatch_deferred:
                candidate_episode_values = set()
            episode_label = _format_candidate_episode_label(candidate)
            candidate_link_url = _normalize_subscription_candidate_link(item.get("link_url", ""))
            candidate_link_type = resolve_resource_link_type(item.get("link_type", ""), candidate_link_url)
            candidate_manifest_cache_key = _build_subscription_candidate_manifest_cache_key(provider, candidate)
            candidate_manifest_payload = share_manifest_cache.get(candidate_manifest_cache_key)
            fixed_share_seed_candidate = (
                fixed_link_fallback_enabled
                and resource_id <= 0
                and candidate_link_type == provider_link_type
            )
            if resource_id <= 0 and not fixed_share_seed_candidate:
                continue
            candidate_share_subdir = task_share_subdir if fixed_share_seed_candidate else ""
            candidate_share_subdir_cid = task_share_subdir_cid if fixed_share_seed_candidate else ""
            candidate_share_scope_enabled = bool(candidate_share_subdir or candidate_share_subdir_cid)
            candidate_share_scope_label = _format_subscription_share_scope_label(
                candidate_share_subdir,
                candidate_share_subdir_cid,
            )
            candidate_share_task = task
            if not fixed_share_seed_candidate:
                candidate_share_task = {
                    **task,
                    "share_subdir": "",
                    "share_subdir_cid": "",
                    "share_link_url": "",
                    "share_link_receive_code": "",
                }
            candidate_savepath = effective_savepath
            if task["media_type"] == "tv":
                savepath_season = max(1, int(task.get("season", 1) or 1)) if candidate_season_mismatch_deferred else candidate_season
                candidate_savepath = build_subscription_tv_savepath(
                    task,
                    base_savepath,
                    season=savepath_season,
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
                            # 非当前订阅网盘分享资源无法做精细转存，若只缺很少集数，优先跳过避免整包重复。
                            if candidate_link_type != provider_link_type and missing_ratio <= 0.35:
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
                fixed_share_seed_candidate
                and task["media_type"] == "tv"
                and candidate_share_scope_enabled
                and (not fixed_share_runtime_initialized)
            ):
                fixed_share_runtime_initialized = True
                runtime_subdir_started_at = time.perf_counter()
                fixed_share_runtime_selection, fixed_share_runtime_subdir_stats = await _build_subscription_share_subdir_selection(
                    cookie_115,
                    item,
                    candidate_share_subdir,
                    share_subdir_cid=candidate_share_subdir_cid,
                    force_refresh=True,
                    allow_fallback=True,
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
                runtime_subdir_fallback_tail = (
                    "（CID 空目录已回退路径匹配）"
                    if bool((fixed_share_runtime_subdir_stats or {}).get("anchor_empty_fallback", False))
                    else ""
                )
                runtime_scan_tail = _format_subscription_share_scan_log_tail(fixed_share_runtime_manifest)
                scan_settings = normalize_subscription_scan_settings(task, provider)
                await write_subscription_log(
                    (
                        f"固定链接运行期缓存已刷新：定位子目录 {_format_elapsed_seconds(runtime_subdir_elapsed_seconds)}，"
                        f"识别目录 {runtime_subdir_reason_label}{runtime_subdir_fallback_tail}，"
                        f"{runtime_scan_tail}，"
                        f"扫描耗时 {_format_elapsed_seconds(runtime_manifest_elapsed_seconds)}，"
                        f"并发 {int(scan_settings.get('share_scan_concurrency', 1) or 1)}，"
                        f"限速 {float(scan_settings.get('share_scan_rate_limit_seconds', 0) or 0):g}s"
                    ),
                    "info",
                )
            if candidate_link_type == provider_link_type and candidate_share_scope_enabled:
                if fixed_share_seed_candidate and fixed_share_runtime_initialized:
                    resolved_subdir_selection = fixed_share_runtime_selection
                    subdir_stats = fixed_share_runtime_subdir_stats
                else:
                    subdir_cache_key = f"{candidate_link_url or f'resource:{resource_id}'}|{candidate_share_subdir}|{candidate_share_subdir_cid}"
                    if subdir_cache_key in share_subdir_selection_cache:
                        resolved_subdir_selection = share_subdir_selection_cache.get(subdir_cache_key, {})
                        subdir_stats = share_subdir_selection_stats_cache.get(subdir_cache_key, {})
                    else:
                        resolved_subdir_selection, subdir_stats = await _build_subscription_share_subdir_selection(
                            cookie_115,
                            item,
                            candidate_share_subdir,
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
                    and candidate_link_type == provider_link_type
                    and task.get("media_type") == "tv"
                    and not (fixed_share_seed_candidate and fixed_share_runtime_initialized)
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
                    provider_meta.ensure_folder_id_by_path,
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
            if existing and fixed_share_seed_candidate:
                existing = {}
                await write_subscription_log(
                    f"候选资源 #{index} 为固定分享链接兜底候选，本次强制重新导入以捕捉目录更新",
                    "info",
                )
            if existing and candidate_link_type == provider_link_type and candidate_share_scope_enabled:
                existing_extra = existing.get("extra") if isinstance(existing.get("extra"), dict) else {}
                existing_share_subdir = normalize_relative_path(
                    str(existing_extra.get("subscription_share_subdir", "") or "").strip()
                )
                existing_share_subdir_cid = _normalize_subscription_share_subdir_cid(
                    existing_extra.get("subscription_share_subdir_cid", "")
                )
                if existing_share_subdir != candidate_share_subdir or existing_share_subdir_cid != candidate_share_subdir_cid:
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
                    if (not fixed_share_seed_candidate) and candidate_link_url and _is_subscription_invalid_link_error(last_failed_detail, candidate_link_type):
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
                if candidate_share_subdir:
                    job_payload["extra"]["subscription_share_subdir"] = candidate_share_subdir
                if candidate_share_subdir_cid:
                    job_payload["extra"]["subscription_share_subdir_cid"] = candidate_share_subdir_cid
                if fixed_share_seed_candidate:
                    job_payload["extra"]["subscription_share_link_url"] = task_share_link_url
                    if task_share_link_receive_code:
                        job_payload["receive_code"] = task_share_link_receive_code
                if (
                    candidate_link_type == provider_link_type
                    and (
                        resolved_subdir_selection.get("selected_ids", [])
                        if isinstance(resolved_subdir_selection.get("selected_ids"), list)
                        else []
                    )
                ):
                    job_payload["share_selection"] = resolved_subdir_selection
                forced_precise_selection_applied = False
                if (
                    fixed_share_seed_candidate
                    and task.get("media_type") == "tv"
                    and candidate_share_scope_enabled
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
                        if fixed_share_seed_candidate and fixed_share_runtime_manifest:
                            precise_selection, precise_stats = _build_tv_share_selection_from_manifest(
                                fixed_share_runtime_manifest,
                                precise_missing_episode_values,
                                task=candidate_share_task,
                            )
                        else:
                            precise_selection, precise_stats = await _build_tv_share_selection_for_missing_episodes(
                                cookie_115,
                                candidate_share_task,
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
                            scan_tail = _format_subscription_share_scan_log_tail(precise_stats)
                            await write_subscription_log(
                                (
                                    f"候选资源 #{index} 固定链接兜底已启用文件级筛选"
                                    f"{'（运行期缓存）' if bool((precise_stats or {}).get('from_runtime_cache', False)) else ''}，"
                                    f"自动命中 {len(precise_ids)} 个剧集文件后再转存（{scan_tail}，避免整包导入）{dedupe_tail}"
                                ),
                                "info",
                            )
                        else:
                            skipped_subdir_candidates += 1
                            selection_reason = str((precise_stats or {}).get("reason", "") or "").strip() or "unknown"
                            selection_reason_label = _format_subscription_reason_chain(selection_reason)
                            scan_tail = _format_subscription_share_scan_log_tail(precise_stats)
                            covered_preview = _format_episode_preview(precise_missing_episode_values)
                            await write_subscription_log(
                                (
                                    f"候选资源 #{index} 固定链接兜底未能在订阅子目录中识别目标剧集文件，"
                                    f"已跳过避免整包导入（目标 {covered_preview}，原因 {selection_reason_label}，"
                                    f"{scan_tail}）"
                                ),
                                "warn",
                            )
                            await maybe_wait_between_attempts()
                            continue
                if (
                    task["media_type"] == "tv"
                    and candidate_link_type == provider_link_type
                    and (candidate_episode_values or candidate_season_mismatch_deferred)
                    and (not forced_precise_selection_applied)
                ):
                    title_precise_episode_values: Set[int] = set(candidate_episode_values)
                    if candidate_season_mismatch_deferred:
                        target_upper = single_season_episode_upper_bound or known_total
                        if target_upper > 0:
                            title_precise_episode_values = set(range(1, target_upper + 1))
                    if existing_episode_scan_ready and title_precise_episode_values:
                        title_precise_episode_values = {
                            episode_no
                            for episode_no in title_precise_episode_values
                            if episode_no not in existing_folder_episodes
                        }
                    if not title_precise_episode_values:
                        if candidate_season_mismatch_deferred:
                            skipped_precise_mismatch_candidates += 1
                            await write_subscription_log(
                                (
                                    f"候选资源 #{index} 标题季号 S{candidate_season:02d} 与订阅季 "
                                    f"S{int(task.get('season', 1) or 1):02d} 不一致，且无法确定目标季缺失集，"
                                    "已跳过避免跨季整包导入"
                                ),
                                "warn",
                            )
                            await maybe_wait_between_attempts()
                            continue
                    else:
                        if fixed_share_seed_candidate and fixed_share_runtime_manifest:
                            title_precise_selection, title_precise_stats = _build_tv_share_selection_from_manifest(
                                fixed_share_runtime_manifest,
                                title_precise_episode_values,
                                task=candidate_share_task,
                            )
                        elif candidate_manifest_payload:
                            title_precise_selection, title_precise_stats = _build_tv_share_selection_from_manifest(
                                candidate_manifest_payload,
                                title_precise_episode_values,
                                task=candidate_share_task,
                            )
                        else:
                            title_precise_selection, title_precise_stats = await _build_tv_share_selection_for_missing_episodes(
                                cookie_115,
                                candidate_share_task,
                                item,
                                title_precise_episode_values,
                                share_subdir_selection=resolved_subdir_selection,
                            )
                        title_precise_ids = (
                            title_precise_selection.get("selected_ids", [])
                            if isinstance(title_precise_selection.get("selected_ids"), list)
                            else []
                        )
                        if (
                            (not title_precise_ids)
                            and candidate_manifest_payload
                            and bool(candidate_manifest_payload.get("truncated", False))
                        ):
                            title_precise_selection, title_precise_stats = await _build_tv_share_selection_for_missing_episodes(
                                cookie_115,
                                candidate_share_task,
                                item,
                                title_precise_episode_values,
                                share_subdir_selection=resolved_subdir_selection,
                            )
                            title_precise_ids = (
                                title_precise_selection.get("selected_ids", [])
                                if isinstance(title_precise_selection.get("selected_ids"), list)
                                else []
                            )
                        if title_precise_ids:
                            job_payload["share_selection"] = title_precise_selection
                            forced_precise_selection_applied = True
                            selected_share_episode_values = {
                                max(0, int(value or 0))
                                for value in (
                                    title_precise_stats.get("covered_episodes", [])
                                    if isinstance(title_precise_stats, dict)
                                    else []
                                )
                                if max(0, int(value or 0)) > 0
                            }
                            selected_share_file_samples = [
                                str(sample or "").strip()
                                for sample in (
                                    title_precise_stats.get("selected_file_samples", [])
                                    if isinstance(title_precise_stats, dict)
                                    else []
                                )
                                if str(sample or "").strip()
                            ]
                            dedupe_hits = int((title_precise_stats or {}).get("duplicate_bucket_hits", 0) or 0)
                            dedupe_tail = f"，同集/同范围已优选 {dedupe_hits} 条重复版本" if dedupe_hits > 0 else ""
                            scan_tail = _format_subscription_share_scan_log_tail(title_precise_stats)
                            if candidate_season_mismatch_deferred:
                                await write_subscription_log(
                                    (
                                        f"候选资源 #{index} 标题季号与订阅季不同，已改按目标季内容精细筛选 "
                                        f"{len(title_precise_ids)} 个文件后转存（{scan_tail}）{dedupe_tail}"
                                    ),
                                    "info",
                                )
                            else:
                                await write_subscription_log(
                                    (
                                        f"候选资源 #{index} 已按候选标题集数精细筛选 "
                                        f"{len(title_precise_ids)} 个文件后转存（目标 {_format_episode_preview(title_precise_episode_values)}）"
                                        f"（{scan_tail}）{dedupe_tail}"
                                    ),
                                    "info",
                                )
                        else:
                            skipped_precise_mismatch_candidates += 1
                            selection_reason = str((title_precise_stats or {}).get("reason", "") or "").strip() or "unknown"
                            selection_reason_label = _format_subscription_reason_chain(selection_reason)
                            scan_tail = _format_subscription_share_scan_log_tail(title_precise_stats)
                            excluded_type_tail = _format_subscription_excluded_file_type_tail(title_precise_stats)
                            await write_subscription_log(
                                (
                                    f"候选资源 #{index} 未能在分享内容中精细识别目标剧集文件，"
                                    f"已跳过避免整包导入（目标 {_format_episode_preview(title_precise_episode_values)}，"
                                    f"原因 {selection_reason_label}，{scan_tail}{excluded_type_tail}）"
                                ),
                                "warn",
                            )
                            await maybe_wait_between_attempts()
                            continue
                if (
                    task["media_type"] == "tv"
                    and candidate_link_type == provider_link_type
                    and (not candidate_episode_values)
                    and (not forced_precise_selection_applied)
                    and candidate_manifest_payload
                ):
                    manifest_episode_values = _clamp_episode_values(
                        {
                            max(0, int(value or 0))
                            for value in (
                                candidate_manifest_payload.get("covered_episodes", [])
                                if isinstance(candidate_manifest_payload.get("covered_episodes"), list)
                                else []
                            )
                            if max(0, int(value or 0)) > 0
                        },
                        episode_upper_bound=single_season_episode_upper_bound,
                    )
                    manifest_missing_episode_values = set(manifest_episode_values)
                    if existing_episode_scan_ready and manifest_missing_episode_values:
                        manifest_missing_episode_values = {
                            episode_no
                            for episode_no in manifest_missing_episode_values
                            if episode_no not in existing_folder_episodes
                        }
                    elif last_episode > 0 and not completed_locked:
                        manifest_missing_episode_values = {
                            episode_no
                            for episode_no in manifest_missing_episode_values
                            if episode_no > baseline_last_episode
                        }
                    if manifest_missing_episode_values:
                        manifest_selection, manifest_stats = _build_tv_share_selection_from_manifest(
                            candidate_manifest_payload,
                            manifest_missing_episode_values,
                            task=candidate_share_task,
                        )
                        manifest_ids = (
                            manifest_selection.get("selected_ids", [])
                            if isinstance(manifest_selection.get("selected_ids"), list)
                            else []
                        )
                        if (not manifest_ids) and bool(candidate_manifest_payload.get("truncated", False)):
                            manifest_selection, manifest_stats = await _build_tv_share_selection_for_missing_episodes(
                                cookie_115,
                                candidate_share_task,
                                item,
                                manifest_missing_episode_values,
                                share_subdir_selection=resolved_subdir_selection,
                            )
                            manifest_ids = (
                                manifest_selection.get("selected_ids", [])
                                if isinstance(manifest_selection.get("selected_ids"), list)
                                else []
                            )
                        if manifest_ids:
                            job_payload["share_selection"] = manifest_selection
                            forced_precise_selection_applied = True
                            selected_share_episode_values = {
                                max(0, int(value or 0))
                                for value in (
                                    manifest_stats.get("covered_episodes", [])
                                    if isinstance(manifest_stats, dict)
                                    else []
                                )
                                if max(0, int(value or 0)) > 0
                            }
                            selected_share_file_samples = [
                                str(sample or "").strip()
                                for sample in (
                                    manifest_stats.get("selected_file_samples", [])
                                    if isinstance(manifest_stats, dict)
                                    else []
                                )
                                if str(sample or "").strip()
                            ]
                            dedupe_hits = int((manifest_stats or {}).get("duplicate_bucket_hits", 0) or 0)
                            dedupe_tail = f"，同集/同范围已优选 {dedupe_hits} 条重复版本" if dedupe_hits > 0 else ""
                            scan_tail = _format_subscription_share_scan_log_tail(manifest_stats)
                            await write_subscription_log(
                                (
                                    f"候选资源 #{index} 标题未给出明确集数，已按分享清单识别 "
                                    f"{_format_episode_preview(selected_share_episode_values)} 并筛选 "
                                    f"{len(manifest_ids)} 个文件后转存（{scan_tail}）{dedupe_tail}"
                                ),
                                "info",
                            )
                        elif not bool(candidate_manifest_payload.get("truncated", False)):
                            skipped_precise_mismatch_candidates += 1
                            reason = str((manifest_stats or {}).get("reason", "") or "no_precise_episode_match").strip()
                            await write_subscription_log(
                                (
                                    f"候选资源 #{index} 分享清单识别到剧集但未能定位可转存文件"
                                    f"（目标 {_format_episode_preview(manifest_missing_episode_values)}，"
                                    f"原因 {_format_subscription_reason_chain(reason)}），已跳过整包导入"
                                ),
                                "warn",
                            )
                            await maybe_wait_between_attempts()
                            continue
                    elif manifest_episode_values and existing_episode_scan_ready:
                        skipped_existing_candidates += 1
                        await write_subscription_log(
                            (
                                f"候选资源 #{index} 分享清单识别到 "
                                f"{_format_episode_preview(manifest_episode_values)}，目标目录已覆盖，已跳过"
                            ),
                            "info",
                        )
                        await maybe_wait_between_attempts()
                        continue
                if (
                    task["media_type"] == "tv"
                    and existing_episode_scan_ready
                    and candidate_link_type == provider_link_type
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
                        if fixed_share_seed_candidate and fixed_share_runtime_manifest:
                            share_selection, selection_stats = _build_tv_share_selection_from_manifest(
                                fixed_share_runtime_manifest,
                                missing_for_candidate,
                                task=candidate_share_task,
                            )
                        elif candidate_manifest_payload:
                            share_selection, selection_stats = _build_tv_share_selection_from_manifest(
                                candidate_manifest_payload,
                                missing_for_candidate,
                                task=candidate_share_task,
                            )
                        else:
                            share_selection, selection_stats = await _build_tv_share_selection_for_missing_episodes(
                                cookie_115,
                                candidate_share_task,
                                item,
                                missing_for_candidate,
                                share_subdir_selection=resolved_subdir_selection,
                            )
                        selected_ids = share_selection.get("selected_ids", []) if isinstance(share_selection, dict) else []
                        if (
                            (not selected_ids)
                            and candidate_manifest_payload
                            and bool(candidate_manifest_payload.get("truncated", False))
                        ):
                            share_selection, selection_stats = await _build_tv_share_selection_for_missing_episodes(
                                cookie_115,
                                candidate_share_task,
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
                            scan_tail = _format_subscription_share_scan_log_tail(selection_stats)
                            await write_subscription_log(
                                (
                                    f"候选资源 #{index} 检测到大包与目录重叠，缺失 {_format_episode_preview(missing_for_candidate)}；"
                                    f"已自动选中 {len(selected_ids)} 个文件精细转存（{scan_tail}）{dedupe_tail}"
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
                                scan_tail = _format_subscription_share_scan_log_tail(selection_stats)
                                if is_subscription_multi_season_mode(task):
                                    await write_subscription_log(
                                        (
                                            f"候选资源 #{index} 尝试按缺失集精细转存未命中（{scan_tail}），回退整包转存"
                                        ),
                                        "warn",
                                    )
                                else:
                                    skipped_precise_mismatch_candidates += 1
                                    skip_due_overlap_fallback = True
                                    await write_subscription_log(
                                        (
                                            f"候选资源 #{index} 尝试按缺失集精细转存未命中（{scan_tail}），"
                                            "单季订阅已跳过整包导入"
                                        ),
                                        "warn",
                                    )
                    if skip_due_overlap_fallback:
                        continue
                if (
                    task["media_type"] == "tv"
                    and candidate_link_type == provider_link_type
                    and not is_subscription_multi_season_mode(task)
                    and not _is_115_tv_file_level_selection(job_payload.get("share_selection", {}))
                ):
                    skipped_precise_mismatch_candidates += 1
                    if candidate_manifest_payload:
                        scan_tail = _format_subscription_share_scan_log_tail(candidate_manifest_payload)
                        covered_preview = str(candidate_manifest_payload.get("covered_preview", "") or "--").strip()
                        await write_subscription_log(
                            (
                                f"候选资源 #{index} 分享清单未识别到订阅季 "
                                f"S{int(task.get('season', 1) or 1):02d} 的可转存剧集文件"
                                f"（清单命中 {covered_preview}，{scan_tail}），已跳过整包导入"
                            ),
                            "warn",
                        )
                    else:
                        await write_subscription_log(
                            (
                                f"候选资源 #{index} 未完成分享清单精细识别，"
                                "单季订阅已跳过整包导入，避免把整季/全剧合集转存到目标季目录"
                            ),
                            "warn",
                        )
                    await maybe_wait_between_attempts()
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
                    and candidate_link_type == provider_link_type
                    and is_subscription_multi_season_mode(task)
                ):
                    split_groups, split_stats = _split_tv_share_selection_by_season(
                        task,
                        normalized_job_selection,
                        fixed_share_runtime_manifest if fixed_share_seed_candidate else {},
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
                                    provider_meta.ensure_folder_id_by_path,
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
                        if (not fixed_share_seed_candidate) and candidate_link_url and _is_subscription_invalid_link_error(last_failed_detail, candidate_link_type):
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
                        and provider == "115"
                        and existing_episode_scan_ready
                        and candidate_link_type == provider_link_type
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
            elif skipped_precise_mismatch_candidates > 0 and attempted_candidates <= 0:
                detail = f"候选资源未能精细识别目标季剧集文件（已跳过 {skipped_precise_mismatch_candidates} 条），等待新资源发布"
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
            if skipped_precise_mismatch_candidates > 0 and attempted_candidates > 0:
                detail += f"；精细识别未命中 {skipped_precise_mismatch_candidates} 条"
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
                    "batch_episode_import": batch_episode_import,
                    "batch_episode_import_reason": batch_episode_import_reason,
                    "batch_episode_decision": batch_episode_decision,
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
                    "skipped_precise_mismatch_candidates": skipped_precise_mismatch_candidates,
                    "scanned_candidates": scanned_candidates,
                    "max_scan_candidates": max_scan_candidates,
                    "use_fixed_share_link": fixed_link_fallback_enabled,
                    "fixed_link_channel_search": fixed_link_fallback_enabled,
                    "share_link_url": task_share_link_url if fixed_link_fallback_enabled else "",
                    "share_subdir": task_share_subdir,
                    "share_subdir_cid": task_share_subdir_cid,
                    "candidate_scan_prewarm": candidate_scan_prewarm_stats,
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
        batch_triggered_groups = int(batch_refresh_result.get("triggered_groups", 0) or 0)
        auto_refresh = bool(selected_auto_refresh or (batch_refresh_enabled and batch_triggered_groups > 0))
        imported_episode_list = sorted(imported_episodes)
        episode_log_tail = _build_subscription_matched_episode_log_tail(task, imported_episode_list)
        matched_display_title = pick_subscription_display_title(task, item, fallback=f"资源#{resource_id}")
        import_type_label = format_resource_link_type_label(item.get("link_type", ""), item.get("link_url", ""))

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
                batch_tail = f"（命中 {len(imported_episode_list)} 集）"
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
                f"（评分 {score}，方式 {import_type_label}），{action_text} #{job_id}，保存到 {selected_job_savepath}{episode_log_tail}"
            )
        else:
            detail = (
                f"命中「{matched_display_title}」"
                f"（评分 {score}，方式 {import_type_label}），{action_text} #{job_id}，保存到 {selected_job_savepath}{episode_log_tail}"
            )
        if batch_refresh_enabled:
            successful_jobs = int(batch_refresh_result.get("successful_jobs", 0) or 0)
            refresh_eligible_jobs = int(batch_refresh_result.get("refresh_eligible_jobs", 0) or 0)
            missing_jobs = int(batch_refresh_result.get("missing_monitor_task_jobs", 0) or 0)
            if batch_triggered_groups > 0:
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
        elif selected_auto_refresh:
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
                "batch_episode_import_reason": batch_episode_import_reason,
                "batch_episode_decision": batch_episode_decision,
                "attempted_candidates": attempted_candidates,
                "failed_attempts": failed_attempts,
                "timed_out_attempts": timed_out_attempts,
                "skipped_episode_candidates": skipped_episode_candidates,
                "skipped_existing_candidates": skipped_existing_candidates,
                "skipped_ledger_candidates": skipped_ledger_candidates,
                "skipped_invalid_candidates": skipped_invalid_candidates,
                "skipped_subdir_candidates": skipped_subdir_candidates,
                "skipped_precise_mismatch_candidates": skipped_precise_mismatch_candidates,
                "scanned_candidates": scanned_candidates,
                "max_scan_candidates": max_scan_candidates,
                "existing_episode_count": existing_episode_count,
                "use_fixed_share_link": fixed_link_fallback_enabled,
                "fixed_link_channel_search": fixed_link_fallback_enabled,
                "share_link_url": task_share_link_url if fixed_link_fallback_enabled else "",
                "share_subdir": task_share_subdir,
                "share_subdir_cid": task_share_subdir_cid,
                "candidate_scan_prewarm": candidate_scan_prewarm_stats,
                **existing_episode_scan_stats,
                **search_stats,
            },
        )
        import_summary_text, import_summary_level = _build_subscription_import_summary_log(
            task,
            imported_episode_list,
            next_episode=next_episode,
            total_episodes=next_total,
        )
        if import_summary_text:
            await write_subscription_log(import_summary_text, import_summary_level)
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
                monitor_context=batch_refresh_result if batch_refresh_enabled else {},
            )
            if bool(notify_result.get("pushed", False)):
                await _write_subscription_notify_result_log(notify_result, task, item)
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
        reset_subscription_share_scan_runtime_settings(share_scan_settings_token)
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
                except Exception as exc:
                    import logging
                    logging.getLogger(__name__).warning("订阅日志写入失败: %s", exc)
                tail_status = "failed"
        except Exception as outer_exc:
            import logging
            logging.getLogger(__name__).error("订阅任务异常退出: %s", outer_exc, exc_info=True)

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
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("阶段计时日志写入失败: %s", exc)
        try:
            await write_subscription_log(
                f"━━━━━━━━━━【订阅结束 | {task_name} | {tail_status_label or '已结束'}】━━━━━━━━━━",
                "task-divider",
            )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("订阅结束日志写入失败: %s", exc)
        reset_subscription_log_context(subscription_log_context_token)
        try:
            await start_next_subscription_job()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error("启动下一个订阅任务失败: %s", exc, exc_info=True)
        release_process_memory(f"subscription:{task_name}", force=True)
