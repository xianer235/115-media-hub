import hashlib
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from ..core import *  # noqa: F401,F403


def _normalize_subscription_candidate_link(link_url: Any) -> str:
    return str(link_url or "").strip()


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


def _clamp_episode_values(episode_values: Set[int], episode_upper_bound: int = 0) -> Set[int]:
    normalized = {max(0, int(value or 0)) for value in (episode_values or set()) if max(0, int(value or 0)) > 0}
    upper_bound = max(0, int(episode_upper_bound or 0))
    if upper_bound > 0:
        normalized = {value for value in normalized if value <= upper_bound}
    return normalized


def _is_subscription_skipped_archive_file(name: str) -> bool:
    normalized_name = normalize_relative_path(str(name or "").strip())
    if "." not in normalized_name:
        return False
    return normalized_name.rsplit(".", 1)[-1].lower() in {"zip", "rar"}


def _is_subscription_numeric_episode_quality_suffix(suffix: str) -> bool:
    normalized_suffix = str(suffix or "").strip().lower()
    if not normalized_suffix:
        return False

    tokens = re.findall(r"[a-z0-9]+", normalized_suffix)
    if not tokens:
        return False

    quality_tokens = {
        "4k",
        "uhd",
        "2160p",
        "1080p",
        "720p",
        "480p",
        "360p",
        "hdr",
        "hdr10",
        "dv",
        "remux",
        "bluray",
        "bdrip",
        "web",
        "webdl",
        "dl",
        "webrip",
    }
    allowed_tokens = quality_tokens.union(
        {
            "x264",
            "x265",
            "h264",
            "h265",
            "hevc",
            "avc",
            "aac",
            "ddp",
            "dd",
            "atmos",
            "truehd",
            "flac",
            "10bit",
            "8bit",
        }
    )
    has_quality_signal = False
    for token in tokens:
        if token in quality_tokens:
            has_quality_signal = True
            continue
        if token in allowed_tokens:
            continue
        if re.fullmatch(r"\d{3,4}p", token):
            has_quality_signal = True
            continue
        if re.fullmatch(r"\d+k", token):
            has_quality_signal = True
            continue
        if re.fullmatch(r"v\d{1,2}", token):
            continue
        return False
    return has_quality_signal


def _extract_subscription_season_values_from_segment(segment: str) -> Set[int]:
    normalized_segment = str(segment or "").strip()
    if not normalized_segment:
        return set()
    values: Set[int] = set()
    for matched in RESOURCE_SEASON_EPISODE_REGEX.finditer(normalized_segment):
        season_no = max(0, int(str(matched.group(1) or "0").replace("O", "0").replace("o", "0") or 0))
        if season_no > 0:
            values.add(season_no)
    for pattern in (RESOURCE_SEASON_ONLY_REGEX, RESOURCE_SEASON_ENGLISH_REGEX):
        for matched in pattern.finditer(normalized_segment):
            season_no = max(0, int(str(matched.group(1) or "0").replace("O", "0").replace("o", "0") or 0))
            if season_no > 0:
                values.add(season_no)
    for matched in RESOURCE_SEASON_ONLY_CN_REGEX.finditer(normalized_segment):
        meta = parse_resource_episode_meta({"title": matched.group(0), "raw_text": matched.group(0)})
        season_no = max(0, int(meta.get("season", 0) or 0))
        if season_no > 0:
            values.add(season_no)
    return values


def _extract_subscription_season_from_name(name: str) -> int:
    normalized_name = normalize_relative_path(str(name or "").strip())
    if not normalized_name:
        return 0
    for segment in reversed([part for part in normalized_name.split("/") if part]):
        season_values = _extract_subscription_season_values_from_segment(segment)
        if len(season_values) == 1:
            return next(iter(season_values))
        if len(season_values) > 1:
            return 0
    return 0


def _extract_subscription_season_from_contexts(context_paths: Optional[List[str]] = None) -> int:
    for context in context_paths or []:
        context_season = _extract_subscription_season_from_name(str(context or "").strip())
        if context_season > 0:
            return context_season
    return 0


def _convert_parent_season_episode_values(task: Dict[str, Any], parent_season: int, episodes: Set[int]) -> Set[int]:
    normalized_parent_season = max(0, int(parent_season or 0))
    if normalized_parent_season <= 0:
        return episodes
    converted: Set[int] = set()
    for episode in sorted(_clamp_episode_values(episodes or set())):
        absolute_episode = convert_subscription_episode_to_absolute(task, normalized_parent_season, episode)
        if absolute_episode > 0:
            converted.add(absolute_episode)
    return converted or episodes


def _extract_task_episodes_from_name(task: Dict[str, Any], name: str, max_expand: int = 400) -> Set[int]:
    normalized_name = str(name or "").strip()
    if not normalized_name:
        return set()
    meta = parse_resource_episode_meta({"title": normalized_name, "raw_text": normalized_name})
    episode = max(0, int(meta.get("episode", 0) or 0))
    range_start = max(0, int(meta.get("range_start", 0) or 0))
    range_end = max(0, int(meta.get("range_end", 0) or 0))
    season = max(0, int(meta.get("season", 0) or 0))
    if is_subscription_multi_season_mode(task):
        if season > 0:
            absolute_episode = convert_subscription_episode_to_absolute(task, season, episode)
            if absolute_episode > 0:
                episode = absolute_episode
            absolute_range_start, absolute_range_end = convert_subscription_episode_range_to_absolute(
                task, season, range_start, range_end
            )
            if absolute_range_end > 0:
                range_start = absolute_range_start
                range_end = absolute_range_end
        if range_end > 0:
            expanded = _expand_episode_values(range_start, range_end, max_expand=max_expand)
            if expanded:
                return expanded
        return {episode} if 0 < episode <= 5000 else set()

    target_season = max(1, int(task.get("season", 1) or 1))
    if season > 0 and season != target_season:
        return set()
    if range_end > 0:
        expanded = _expand_episode_values(range_start, range_end, max_expand=max_expand)
        if expanded:
            return expanded
        return {range_end} if 0 < range_end <= 5000 else set()
    return {episode} if 0 < episode <= 5000 else set()


def _extract_numeric_episode_from_filename(file_name: str) -> int:
    normalized_name = str(file_name or "").strip()
    if not normalized_name:
        return 0
    stem = os.path.splitext(normalized_name)[0]
    stem_tail = str(stem or "").replace("\\", "/").split("/")[-1].strip()
    if not stem_tail:
        return 0

    # 兼容类似 "04(1).mkv" 的分段命名：括号中的分段号不应并入剧集号。
    stem_tail_numeric = re.sub(r"\s*[\(\[（【]\s*\d{1,2}\s*[\)\]）】]\s*$", "", stem_tail)
    compact = re.sub(r"[\s._\-(){}\[\]<>【】（）「」《》]+", "", stem_tail_numeric or stem_tail)
    if not compact:
        return 0

    for pattern in (
        re.compile(r"^0*(\d{1,3})$"),
        re.compile(r"^第?0*(\d{1,3})(?:集|话|話)?$", re.IGNORECASE),
    ):
        matched = pattern.fullmatch(compact)
        if not matched:
            continue
        value = max(0, int(matched.group(1) or 0))
        if 0 < value <= 5000:
            return value

    quality_tail_match = re.match(
        r"^(?:第\s*)?0*(\d{1,3})(?:\s*(?:集|话|話))?(?P<suffix>[\s._\-+(){}\[\]<>【】（）「」《》]+.+)$",
        stem_tail_numeric,
        re.IGNORECASE,
    )
    if quality_tail_match and _is_subscription_numeric_episode_quality_suffix(quality_tail_match.group("suffix")):
        value = max(0, int(quality_tail_match.group(1) or 0))
        if 0 < value <= 5000:
            return value
    return 0


def _extract_task_episodes_from_file_entry(
    task: Dict[str, Any],
    file_name: str,
    parent_path: str = "",
    context_paths: Optional[List[str]] = None,
) -> Set[int]:
    normalized_file_name = normalize_relative_path(str(file_name or "").strip())
    if not normalized_file_name:
        return set()
    if _is_subscription_skipped_archive_file(normalized_file_name):
        return set()

    file_parts = [part for part in normalized_file_name.split("/") if part]
    file_leaf = file_parts[-1] if file_parts else normalized_file_name
    inline_parent = normalize_relative_path("/".join(file_parts[:-1]))
    normalized_parent = normalize_relative_path(join_relative_path(str(parent_path or "").strip(), inline_parent))
    parent_season = _extract_subscription_season_from_name(normalized_parent)
    context_season = _extract_subscription_season_from_contexts(context_paths)
    effective_parent_season = parent_season or context_season
    multi_season_mode = is_subscription_multi_season_mode(task)
    if not multi_season_mode:
        target_season = max(1, int(task.get("season", 1) or 1))
        if parent_season > 0 and parent_season != target_season:
            return set()

    for probe in (file_leaf, os.path.splitext(file_leaf)[0]):
        parsed = _extract_task_episodes_from_name(task, probe)
        if parsed:
            probe_season = _extract_subscription_season_from_name(probe)
            if probe_season <= 0 and effective_parent_season > 0:
                if multi_season_mode:
                    return _convert_parent_season_episode_values(task, effective_parent_season, parsed)
                target_season = max(1, int(task.get("season", 1) or 1))
                if effective_parent_season != target_season:
                    return set()
            return parsed

    numeric_episode = _extract_numeric_episode_from_filename(file_leaf)
    if numeric_episode > 0:
        if multi_season_mode:
            if effective_parent_season > 0:
                absolute_episode = convert_subscription_episode_to_absolute(task, effective_parent_season, numeric_episode)
                if absolute_episode > 0:
                    return {absolute_episode}
            return {numeric_episode}
        target_season = max(1, int(task.get("season", 1) or 1))
        if effective_parent_season > 0 and effective_parent_season != target_season:
            return set()
        return {numeric_episode}

    if normalized_parent:
        full_name = normalize_relative_path(join_relative_path(normalized_parent, file_leaf))
        full_path_values = _extract_task_episodes_from_name(task, full_name)
        # 父目录区间（如 E01-E24）会让每个子文件都命中整段范围，容易造成整包误选。
        # 仅在全路径能明确到单集时才回退使用。
        if len(full_path_values) == 1:
            return full_path_values
    for context_path in context_paths or []:
        normalized_context = normalize_relative_path(str(context_path or "").strip())
        if not normalized_context:
            continue
        full_context_name = normalize_relative_path(join_relative_path(normalized_context, normalized_file_name))
        context_values = _extract_task_episodes_from_name(task, full_context_name)
        if len(context_values) == 1:
            return context_values
    return set()


def _candidate_episode_values(
    candidate: Dict[str, Any],
    max_expand: int = 400,
    episode_upper_bound: int = 0,
) -> Set[int]:
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
    return _clamp_episode_values(values, episode_upper_bound=episode_upper_bound)


def _candidate_anchor_episode(candidate: Dict[str, Any], episode_upper_bound: int = 0) -> int:
    values = _candidate_episode_values(candidate, max_expand=200, episode_upper_bound=episode_upper_bound)
    if values:
        return max(values)
    anchor = max(0, int((candidate or {}).get("episode", 0) or 0))
    upper_bound = max(0, int(episode_upper_bound or 0))
    if upper_bound > 0 and anchor > upper_bound:
        anchor = upper_bound
    return anchor


def _candidate_confident_episode_values(candidate: Dict[str, Any], episode_upper_bound: int = 0) -> Set[int]:
    """
    候选命名中的大范围区间（如 E1-E26）并不总能代表目录里每一集都完整可用。
    为避免“先命中一个大包后把后续补档候选全部跳过”，超大区间仅保留锚点集做本轮去重。
    中小范围（如 E1-E15）按完整范围记账，减少同轮重复整包导入。
    """
    values = _candidate_episode_values(candidate, episode_upper_bound=episode_upper_bound)
    if not values:
        return set()
    range_start = max(0, int((candidate or {}).get("range_start", 0) or 0))
    range_end = max(0, int((candidate or {}).get("range_end", 0) or 0))
    if range_start > 0 and range_end > 0:
        if range_end < range_start:
            range_start, range_end = range_end, range_start
        range_size = max(1, range_end - range_start + 1)
        if range_size > 20:
            return {max(values)}
    return values


def _candidate_missing_episode_values(
    candidate: Dict[str, Any],
    existing_episodes: Set[int],
    episode_upper_bound: int = 0,
) -> Set[int]:
    episode_values = _candidate_episode_values(candidate, episode_upper_bound=episode_upper_bound)
    if not episode_values:
        return set()
    normalized_existing = _clamp_episode_values(existing_episodes or set(), episode_upper_bound=episode_upper_bound)
    return {episode_no for episode_no in episode_values if episode_no not in normalized_existing}


def _resolve_recorded_episode_values(
    candidate: Dict[str, Any],
    selected_share_episode_values: Set[int],
    episode_upper_bound: int = 0,
) -> Set[int]:
    selected_values = _clamp_episode_values(selected_share_episode_values or set(), episode_upper_bound=episode_upper_bound)
    if selected_values:
        # 精细转存时，selected_share_episode_values 才是实际入库结果，应优先作为记账依据。
        return selected_values

    confident_episode_values = _candidate_confident_episode_values(candidate, episode_upper_bound=episode_upper_bound)
    if confident_episode_values:
        return confident_episode_values

    episode = max(0, int((candidate or {}).get("episode", 0) or 0))
    upper_bound = max(0, int(episode_upper_bound or 0))
    if upper_bound > 0 and episode > upper_bound:
        return set()
    if episode > 0:
        return {episode}
    return set()


def _evaluate_duplicate_receive_validation(
    verify_target_episodes: Set[int],
    pre_attempt_existing_episodes: Set[int],
    verify_scan_episodes: Set[int],
    scan_scanned_dirs: int,
    scan_scanned_entries: int,
    scan_failed_dirs: int,
    scan_truncated: bool,
) -> Dict[str, Any]:
    normalized_target = {
        max(0, int(value or 0))
        for value in (verify_target_episodes or set())
        if max(0, int(value or 0)) > 0
    }
    normalized_pre_attempt = {
        max(0, int(value or 0))
        for value in (pre_attempt_existing_episodes or set())
        if max(0, int(value or 0)) > 0
    }
    normalized_scan = {
        max(0, int(value or 0))
        for value in (verify_scan_episodes or set())
        if max(0, int(value or 0)) > 0
    }

    newly_detected = normalized_scan.difference(normalized_pre_attempt)
    verified_new_hits = normalized_target.intersection(newly_detected)
    present_hits = normalized_target.intersection(normalized_scan)

    scanned_dirs_value = max(0, int(scan_scanned_dirs or 0))
    scanned_entries_value = max(0, int(scan_scanned_entries or 0))
    failed_dirs_value = max(0, int(scan_failed_dirs or 0))
    truncated_flag = bool(scan_truncated)

    # 扫描可靠性分级：
    # 1) basic_reliable: 至少不是“完全没扫到目录且全是失败”。
    # 2) strict_reliable: 可用于“反证不存在”的严格判断（未截断且扫描无失败且有条目）。
    basic_reliable = not (scanned_dirs_value <= 0 and failed_dirs_value > 0)
    strict_reliable = bool(
        basic_reliable
        and scanned_entries_value > 0
        and failed_dirs_value <= 0
        and (not truncated_flag)
    )

    should_fail = False
    reason = ""
    if normalized_target:
        if verified_new_hits:
            reason = "verified_new_hits"
        elif present_hits:
            reason = "already_present_hits"
        elif basic_reliable and (not truncated_flag) and scanned_entries_value <= 0:
            should_fail = True
            reason = "empty_scan_miss"
        elif strict_reliable and normalized_scan:
            should_fail = True
            reason = "strict_scan_miss"
        elif (not basic_reliable) or truncated_flag:
            reason = "scan_not_reliable"
        else:
            reason = "episode_unrecognized"

    return {
        "should_fail": should_fail,
        "reason": reason,
        "verified_new_hits": sorted(verified_new_hits),
        "present_hits": sorted(present_hits),
        "newly_detected": sorted(newly_detected),
        "basic_reliable": basic_reliable,
        "strict_reliable": strict_reliable,
    }


def _candidate_episode_ledger_skip_reason(
    candidate: Dict[str, Any],
    episode_values: Set[int],
    ledger_rows: Dict[int, Dict[str, Any]],
) -> str:
    normalized_values = sorted({max(0, int(value or 0)) for value in (episode_values or set()) if max(0, int(value or 0)) > 0})
    if not normalized_values:
        return ""

    covered_rows: List[Dict[str, Any]] = []
    for episode_no in normalized_values:
        row = ledger_rows.get(episode_no)
        if not row:
            return ""
        if str(row.get("status", "active") or "active").strip().lower() != "active":
            return ""
        covered_rows.append(row)

    candidate_resolution = max(0, int((candidate or {}).get("resolution", 0) or 0))
    candidate_score = max(0, int((candidate or {}).get("score", 0) or 0))
    for row in covered_rows:
        row_resolution = max(0, int(row.get("best_resolution", 0) or 0))
        row_score = max(0, int(row.get("best_score", 0) or 0))
        if candidate_resolution > 0:
            if row_resolution <= 0 or candidate_resolution > row_resolution:
                return ""
            if candidate_resolution == row_resolution and candidate_score >= row_score + 4:
                return ""
        else:
            if candidate_score >= row_score + 8:
                return ""

    return (
        f"候选集数已被集数账本覆盖（{_format_episode_preview(set(normalized_values))}）且未达到更优质量，已跳过"
    )


def _build_subscription_episode_ledger_fingerprints(
    item: Dict[str, Any],
    candidate: Dict[str, Any],
    episode_values: Set[int],
    selected_ids: List[str],
) -> Tuple[str, str]:
    normalized_item = item if isinstance(item, dict) else {}
    normalized_candidate = candidate if isinstance(candidate, dict) else {}
    normalized_selected_ids = sorted({str(value or "").strip() for value in (selected_ids or []) if str(value or "").strip()})[:200]
    episode_marker = ",".join([str(value) for value in sorted({max(0, int(ep or 0)) for ep in (episode_values or set()) if max(0, int(ep or 0)) > 0})])

    link_type = resolve_resource_link_type(
        normalized_item.get("link_type", ""),
        str(normalized_item.get("link_url", "")).strip(),
    )
    link_url = _normalize_subscription_candidate_link(normalized_item.get("link_url", ""))
    source_parts = [
        link_type,
        link_url,
        "|".join(normalized_selected_ids),
    ]
    source_seed = "||".join(source_parts)
    source_fp = hashlib.sha1(source_seed.encode("utf-8")).hexdigest()

    content_parts = [
        source_fp,
        f"s:{max(0, int(normalized_candidate.get('season', 0) or 0))}",
        f"e:{max(0, int(normalized_candidate.get('episode', 0) or 0))}",
        f"r:{max(0, int(normalized_candidate.get('range_start', 0) or 0))}-{max(0, int(normalized_candidate.get('range_end', 0) or 0))}",
        f"res:{max(0, int(normalized_candidate.get('resolution', 0) or 0))}",
        f"score:{max(0, int(normalized_candidate.get('score', 0) or 0))}",
        f"episodes:{episode_marker}",
    ]
    content_seed = "||".join(content_parts)
    content_fp = hashlib.sha1(content_seed.encode("utf-8")).hexdigest()
    return source_fp, content_fp


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


def _build_subscription_episode_bucket_key(episode_values: Set[int]) -> str:
    normalized = sorted({max(0, int(value or 0)) for value in (episode_values or set()) if max(0, int(value or 0)) > 0})
    if not normalized:
        return ""
    if len(normalized) == 1:
        return f"e:{normalized[0]}"
    start = normalized[0]
    end = normalized[-1]
    expected = list(range(start, end + 1))
    if normalized == expected:
        return f"r:{start}-{end}"
    return f"m:{','.join([str(value) for value in normalized[:24]])}"


def _build_subscription_share_file_quality_rank(task: Dict[str, Any], entry: Dict[str, Any]) -> Tuple[int, int, int, str]:
    entry_name = normalize_relative_path(str((entry or {}).get("name", "") or "").strip())
    pseudo_item = {
        "title": entry_name,
        "raw_text": entry_name,
        "quality": entry_name,
    }
    quality_bonus, resolution, _ = score_subscription_quality_preference(task, pseudo_item)
    size_value = max(0, int((entry or {}).get("size", 0) or 0))
    return (
        max(0, int(quality_bonus or 0)),
        max(0, int(resolution or 0)),
        size_value,
        entry_name.lower(),
    )


def _pick_best_tv_share_files_by_episode_bucket(
    task: Dict[str, Any],
    file_entries: List[Dict[str, Any]],
    missing_episodes: Set[int],
) -> Dict[str, Any]:
    target_missing = _clamp_episode_values(missing_episodes or set())
    picked_by_bucket: Dict[str, Dict[str, Any]] = {}
    duplicate_bucket_hits = 0

    for raw_entry in file_entries if isinstance(file_entries, list) else []:
        if not isinstance(raw_entry, dict):
            continue
        entry_id = str(raw_entry.get("id", "") or raw_entry.get("fid", "") or "").strip()
        entry_name = normalize_relative_path(str(raw_entry.get("name", "") or "").strip())
        if not entry_id or not entry_name:
            continue
        if _is_subscription_skipped_archive_file(entry_name):
            continue

        entry_episodes = _clamp_episode_values(
            {
                max(0, int(value or 0))
                for value in (raw_entry.get("episodes", []) if isinstance(raw_entry.get("episodes"), list) else [])
                if max(0, int(value or 0)) > 0
            }
        )
        if not entry_episodes:
            continue
        episode_hit = entry_episodes.intersection(target_missing) if target_missing else set(entry_episodes)
        if not episode_hit:
            continue

        bucket_key = _build_subscription_episode_bucket_key(entry_episodes) or f"id:{entry_id}"
        rank = _build_subscription_share_file_quality_rank(task, raw_entry)
        current = picked_by_bucket.get(bucket_key)
        if current:
            duplicate_bucket_hits += 1
            if rank <= current.get("rank", (0, 0, 0, "")):
                continue

        picked_by_bucket[bucket_key] = {
            "entry": {
                "id": entry_id,
                "name": entry_name,
                "is_dir": False,
                "parent_id": str(raw_entry.get("parent_id", "0") or "0").strip() or "0",
                "cid": "",
                "fid": str(raw_entry.get("fid", "") or entry_id).strip(),
                "fid_token": str(raw_entry.get("fid_token", "") or "").strip(),
            },
            "episodes": entry_episodes,
            "episode_hit": episode_hit,
            "rank": rank,
        }

    ordered_entries = sorted(
        picked_by_bucket.values(),
        key=lambda item: (
            min(item.get("episodes", {999999})) if item.get("episodes") else 999999,
            normalize_relative_path(str((item.get("entry", {}) or {}).get("name", "") or "")).lower(),
        ),
    )
    covered_missing: Set[int] = set()
    selected_entries: List[Dict[str, Any]] = []
    for payload in ordered_entries:
        entry = payload.get("entry", {}) if isinstance(payload.get("entry"), dict) else {}
        if not entry:
            continue
        selected_entries.append(entry)
        covered_missing.update(payload.get("episode_hit", set()))

    return {
        "selected_entries": selected_entries,
        "selected_ids": [str(entry.get("id", "")).strip() for entry in selected_entries if str(entry.get("id", "")).strip()],
        "covered_missing": covered_missing,
        "bucket_count": len(selected_entries),
        "duplicate_bucket_hits": duplicate_bucket_hits,
    }


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
    queue: List[Tuple[str, int, str]] = [(start_cid, 0, "")]
    visited: Set[str] = set()
    episodes: Set[int] = set()
    scanned_dirs = 0
    scanned_entries = 0
    failed_dirs = 0

    while queue and scanned_dirs < max_dirs and scanned_entries < max_entries:
        cid, depth, parent_path = queue.pop(0)
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
            rel_name = normalize_relative_path(name)
            is_dir = bool(entry.get("is_dir"))
            if is_dir and depth < max_depth:
                child_cid = str(entry.get("id", "") or entry.get("cid", "") or "").strip()
                if child_cid and child_cid not in visited:
                    child_path = normalize_relative_path(join_relative_path(parent_path, rel_name))
                    queue.append((child_cid, depth + 1, child_path or rel_name))
            if is_dir:
                continue
            parsed_episodes = _extract_task_episodes_from_file_entry(task, rel_name or name, parent_path)
            if parsed_episodes:
                episodes.update(parsed_episodes)

    sorted_episodes = sorted(episodes)
    return {
        "episodes": sorted_episodes,
        "max_episode": sorted_episodes[-1] if sorted_episodes else 0,
        "scanned_dirs": scanned_dirs,
        "scanned_entries": scanned_entries,
        "failed_dirs": failed_dirs,
        "truncated": bool(queue) or scanned_dirs >= max_dirs or scanned_entries >= max_entries,
    }


def _scan_quark_existing_tv_episodes(
    cookie: str,
    root_folder_id: str,
    task: Dict[str, Any],
    max_depth: int = 3,
    max_dirs: int = 120,
    max_entries: int = 3000,
) -> Dict[str, Any]:
    normalized_cookie = str(cookie or "").strip()
    if not normalized_cookie:
        raise RuntimeError("Quark Cookie 未配置")

    start_cid = str(root_folder_id or "0").strip() or "0"
    queue: List[Tuple[str, int, str]] = [(start_cid, 0, "")]
    visited: Set[str] = set()
    episodes: Set[int] = set()
    scanned_dirs = 0
    scanned_entries = 0
    failed_dirs = 0

    while queue and scanned_dirs < max_dirs and scanned_entries < max_entries:
        cid, depth, parent_path = queue.pop(0)
        if cid in visited:
            continue
        visited.add(cid)
        try:
            entries = list_quark_entries(normalized_cookie, cid)
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
            rel_name = normalize_relative_path(name)
            is_dir = bool(entry.get("is_dir"))
            if is_dir and depth < max_depth:
                child_cid = str(entry.get("id", "") or entry.get("cid", "") or "").strip()
                if child_cid and child_cid not in visited:
                    child_path = normalize_relative_path(join_relative_path(parent_path, rel_name))
                    queue.append((child_cid, depth + 1, child_path or rel_name))
            if is_dir:
                continue
            parsed_episodes = _extract_task_episodes_from_file_entry(task, rel_name or name, parent_path)
            if parsed_episodes:
                episodes.update(parsed_episodes)

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


def _build_subscription_selected_file_samples(
    file_entries: List[Dict[str, Any]],
    selected_ids: List[str],
    target_episodes: Set[int],
    sample_limit: int = 6,
) -> List[str]:
    normalized_selected_ids = [str(value or "").strip() for value in (selected_ids or []) if str(value or "").strip()]
    if not normalized_selected_ids:
        return []
    target = _clamp_episode_values(target_episodes or set())
    entry_by_id: Dict[str, Dict[str, Any]] = {}
    for raw_entry in file_entries if isinstance(file_entries, list) else []:
        if not isinstance(raw_entry, dict):
            continue
        entry_id = str(raw_entry.get("id", "") or raw_entry.get("fid", "") or "").strip()
        if not entry_id:
            continue
        entry_by_id[entry_id] = raw_entry

    samples: List[str] = []
    for selected_id in normalized_selected_ids:
        entry = entry_by_id.get(selected_id, {})
        if not isinstance(entry, dict):
            continue
        entry_name = normalize_relative_path(str(entry.get("name", "") or "").strip())
        if not entry_name:
            continue
        entry_episodes = _clamp_episode_values(
            {
                max(0, int(value or 0))
                for value in (entry.get("episodes", []) if isinstance(entry.get("episodes"), list) else [])
                if max(0, int(value or 0)) > 0
            }
        )
        episode_hit = entry_episodes.intersection(target) if target else set(entry_episodes)
        episode_label = _format_episode_preview(episode_hit or entry_episodes, max_items=4) if (episode_hit or entry_episodes) else "--"
        samples.append(f"{episode_label} <- {entry_name[:96]}")
        if len(samples) >= max(1, int(sample_limit or 6)):
            break
    return samples


def _prioritize_tv_candidates_by_missing_episodes(
    candidates: List[Dict[str, Any]],
    existing_episodes: Set[int],
    baseline_last_episode: int,
    prefer_backfill: bool,
    episode_upper_bound: int = 0,
) -> List[Dict[str, Any]]:
    normalized_existing = _clamp_episode_values(existing_episodes, episode_upper_bound=episode_upper_bound)
    if not normalized_existing:
        if episode_upper_bound > 0:
            # 首轮目录为空时，优先尝试“在单季目标集数范围内覆盖更多集数”的候选。
            prioritized = list(candidates)
            prioritized.sort(
                key=lambda item: (
                    len(_candidate_episode_values(item, episode_upper_bound=episode_upper_bound)),
                    _candidate_anchor_episode(item, episode_upper_bound=episode_upper_bound),
                    int(item.get("score", 0) or 0),
                    get_resource_item_sort_key(item.get("item", {})),
                ),
                reverse=True,
            )
            return prioritized
        return list(candidates)

    without_episode: List[Dict[str, Any]] = []
    backfill_candidates: List[Dict[str, Any]] = []
    fresh_candidates: List[Dict[str, Any]] = []
    existing_candidates: List[Dict[str, Any]] = []
    for candidate in candidates:
        episode_values = _candidate_episode_values(candidate, episode_upper_bound=episode_upper_bound)
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
            _candidate_anchor_episode(item, episode_upper_bound=episode_upper_bound),
            -int(item.get("score", 0) or 0),
            get_resource_item_sort_key(item.get("item", {})),
        )
    )
    fresh_candidates.sort(
        key=lambda item: (
            _candidate_anchor_episode(item, episode_upper_bound=episode_upper_bound),
            int(item.get("score", 0) or 0),
            get_resource_item_sort_key(item.get("item", {})),
        ),
        reverse=True,
    )
    existing_candidates.sort(
        key=lambda item: (
            _candidate_anchor_episode(item, episode_upper_bound=episode_upper_bound),
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


def _prioritize_quark_tv_candidates_for_precise_scan(
    candidates: List[Dict[str, Any]],
    existing_episodes: Set[int],
    episode_upper_bound: int = 0,
) -> List[Dict[str, Any]]:
    normalized_existing = _clamp_episode_values(existing_episodes, episode_upper_bound=episode_upper_bound)
    prioritized = list(candidates or [])
    prioritized.sort(
        key=lambda item: (
            int(item.get("title_match_score", 0) or 0),
            len(_candidate_missing_episode_values(item, normalized_existing, episode_upper_bound=episode_upper_bound)),
            int(item.get("resolution", 0) or 0),
            int(item.get("score", 0) or 0),
            get_resource_item_sort_key(item.get("item", {})),
        ),
        reverse=True,
    )
    return prioritized


def _compute_quark_tv_title_missing_targets(
    existing_episodes: Set[int],
    baseline_last_episode: int,
    episode_upper_bound: int = 0,
) -> Set[int]:
    normalized_existing = _clamp_episode_values(existing_episodes or set(), episode_upper_bound=episode_upper_bound)
    upper_bound = max(0, int(episode_upper_bound or 0))
    if upper_bound > 0:
        return {episode_no for episode_no in range(1, upper_bound + 1) if episode_no not in normalized_existing}
    progress_upper = max(max(normalized_existing) if normalized_existing else 0, max(0, int(baseline_last_episode or 0)))
    if progress_upper <= 0:
        return set()
    return {episode_no for episode_no in range(1, progress_upper + 1) if episode_no not in normalized_existing}


def _filter_quark_tv_candidates_by_title_missing_episodes(
    candidates: List[Dict[str, Any]],
    missing_targets: Set[int],
    episode_upper_bound: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    normalized_missing = _clamp_episode_values(missing_targets or set(), episode_upper_bound=episode_upper_bound)
    if not normalized_missing:
        return list(candidates or []), 0
    kept: List[Dict[str, Any]] = []
    dropped = 0
    for candidate in candidates or []:
        episode_values = _candidate_episode_values(candidate, episode_upper_bound=episode_upper_bound)
        if not episode_values:
            # 标题集数无法识别时保留到精细扫描，避免漏掉命名不规范但实际可用的资源。
            kept.append(candidate)
            continue
        if episode_values.intersection(normalized_missing):
            kept.append(candidate)
            continue
        dropped += 1
    return kept, dropped


def _prune_tv_candidates_without_new_episodes(
    candidates: List[Dict[str, Any]],
    existing_episodes: Set[int],
    episode_upper_bound: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    normalized_existing = _clamp_episode_values(existing_episodes, episode_upper_bound=episode_upper_bound)
    if not normalized_existing:
        return list(candidates or []), 0
    kept: List[Dict[str, Any]] = []
    pruned = 0
    for candidate in candidates or []:
        episode_values = _candidate_episode_values(candidate, episode_upper_bound=episode_upper_bound)
        has_range_hint = (
            max(0, int((candidate or {}).get("range_start", 0) or 0)) > 0
            and max(0, int((candidate or {}).get("range_end", 0) or 0)) > 0
        )
        if has_range_hint and episode_values and episode_values.issubset(normalized_existing):
            pruned += 1
            continue
        kept.append(candidate)
    return kept, pruned


__all__ = [
    "_expand_episode_values",
    "_clamp_episode_values",
    "_is_subscription_skipped_archive_file",
    "_extract_task_episodes_from_name",
    "_extract_numeric_episode_from_filename",
    "_extract_subscription_season_from_contexts",
    "_extract_task_episodes_from_file_entry",
    "_candidate_episode_values",
    "_candidate_anchor_episode",
    "_candidate_confident_episode_values",
    "_candidate_missing_episode_values",
    "_resolve_recorded_episode_values",
    "_evaluate_duplicate_receive_validation",
    "_candidate_episode_ledger_skip_reason",
    "_build_subscription_episode_ledger_fingerprints",
    "_format_candidate_episode_label",
    "_build_subscription_episode_bucket_key",
    "_build_subscription_share_file_quality_rank",
    "_pick_best_tv_share_files_by_episode_bucket",
    "_scan_115_existing_tv_episodes",
    "_scan_quark_existing_tv_episodes",
    "_format_episode_preview",
    "_build_subscription_selected_file_samples",
    "_prioritize_tv_candidates_by_missing_episodes",
    "_prioritize_quark_tv_candidates_for_precise_scan",
    "_compute_quark_tv_title_missing_targets",
    "_filter_quark_tv_candidates_by_title_missing_episodes",
    "_prune_tv_candidates_without_new_episodes",
]
