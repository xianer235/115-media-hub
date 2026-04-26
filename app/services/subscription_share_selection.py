import asyncio
import re
import unicodedata
from typing import Any, Dict, List, Optional, Set, Tuple

from ..core import *  # noqa: F401,F403
from .subscription_episode import *  # noqa: F401,F403
from .subscription_share_runtime import *  # noqa: F401,F403


def _build_subscription_share_episode_context_paths(item: Dict[str, Any], share_root_title: str = "") -> List[str]:
    payload = item if isinstance(item, dict) else {}
    candidates: List[str] = []
    for value in (
        share_root_title,
        payload.get("title", ""),
        payload.get("raw_text", ""),
    ):
        normalized = normalize_relative_path(str(value or "").strip())
        if normalized:
            candidates.append(normalized)
    return unique_preserve_order(candidates)


def _normalize_subscription_share_dir_match_key(name: str, drop_digits: bool = False) -> str:
    normalized = normalize_relative_path(name)
    if not normalized:
        return ""
    text = unicodedata.normalize("NFKC", normalized).lower()
    text = text.replace("｜", "|")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[。．…·•~～\-_+=]+$", "", text)
    text = re.sub(r"[^0-9a-z\u4e00-\u9fff{}#:+-]+", "", text)
    if drop_digits:
        text = re.sub(r"\d+", "", text)
    return text


def _extract_subscription_tmdbid_token(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    matched = re.search(r"tmdbid[-_:\s]*([0-9]{3,})", normalized, re.IGNORECASE)
    return str(matched.group(1) if matched else "").strip()


def _pick_unique_subscription_share_entry(candidates: List[Tuple[int, Dict[str, Any]]]) -> Dict[str, Any]:
    if not candidates:
        return {}
    ranked = sorted(candidates, key=lambda item: int(item[0] or 0), reverse=True)
    if len(ranked) > 1 and int(ranked[0][0] or 0) == int(ranked[1][0] or 0):
        return {}
    return ranked[0][1] if isinstance(ranked[0][1], dict) else {}


def _sample_subscription_share_dir_names(entries: List[Dict[str, Any]], limit: int = 6) -> List[str]:
    samples: List[str] = []
    for entry in entries if isinstance(entries, list) else []:
        if not bool(entry.get("is_dir")):
            continue
        name = normalize_relative_path(str(entry.get("name", "") or "").strip())
        if not name or name in samples:
            continue
        samples.append(name)
        if len(samples) >= max(1, int(limit or 6)):
            break
    return samples


def _collect_subscription_task_share_dir_name_candidates(task: Dict[str, Any]) -> List[str]:
    candidates: List[str] = []
    for value in (
        task.get("title", ""),
        task.get("tmdb_title", ""),
        task.get("tmdb_original_title", ""),
    ):
        text = normalize_relative_path(str(value or "").strip())
        if text:
            candidates.append(text)
    for field in ("aliases", "tmdb_aliases"):
        raw_values = task.get(field, [])
        if not isinstance(raw_values, list):
            continue
        for raw in raw_values:
            text = normalize_relative_path(str(raw or "").strip())
            if text:
                candidates.append(text)
    return unique_preserve_order(candidates)


def _score_subscription_share_dir_for_task(
    entry_name: str,
    task_name_candidates: List[str],
    task_tmdbid: str = "",
) -> int:
    normalized_entry = normalize_relative_path(entry_name)
    if not normalized_entry:
        return 0
    best_score = 0
    for expected_name in task_name_candidates if isinstance(task_name_candidates, list) else []:
        score = _score_subscription_share_dir_candidate_name(
            normalized_entry,
            expected_name,
            expected_tmdbid=task_tmdbid,
        )
        if score > best_score:
            best_score = score
    entry_key = _normalize_subscription_share_dir_match_key(normalized_entry)
    if task_tmdbid and entry_key and task_tmdbid in entry_key:
        best_score = max(best_score, 260)
    return best_score


async def _refine_subscription_share_selection_for_task(
    cookie: str,
    item: Dict[str, Any],
    task: Dict[str, Any],
    selection: Dict[str, Any],
    per_request_timeout: int = 25,
    max_depth: int = 3,
    max_dirs: int = 140,
    force_refresh: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    stats: Dict[str, Any] = {
        "reason": "",
        "scanned_dirs": 0,
        "candidate_count": 0,
        "best_score": 0,
        "ambiguous_count": 0,
        "start_child_dirs": 0,
        "current_score": 0,
        "from_path": "",
        "to_path": "",
        "candidate_samples": [],
    }
    normalized_cookie = str(cookie or "").strip()
    share_url = str(item.get("link_url", "") or "").strip()
    raw_text = str(item.get("raw_text", "") or "")
    if not normalized_cookie or not share_url:
        stats["reason"] = "missing_context"
        return {}, stats

    base_selection = normalize_share_selection_meta(selection or {})
    selected_entries = (
        base_selection.get("selected_entries", [])
        if isinstance(base_selection.get("selected_entries"), list)
        else []
    )
    start_entry = selected_entries[0] if selected_entries else {}
    if not start_entry or not bool(start_entry.get("is_dir")):
        stats["reason"] = "selection_invalid"
        return {}, stats

    start_cid = str(start_entry.get("cid", "") or start_entry.get("id", "") or "").strip()
    start_path = normalize_relative_path(str(start_entry.get("name", "") or "").strip())
    if not start_cid or not start_path:
        stats["reason"] = "selection_invalid"
        return {}, stats
    task_anchor_cid = _normalize_subscription_share_subdir_cid(task.get("share_subdir_cid", ""))
    if task_anchor_cid and task_anchor_cid == start_cid:
        stats["reason"] = "cid_anchor_locked"
        stats["current_score"] = 999
        return base_selection, stats
    stats["from_path"] = start_path

    task_tmdbid = str(max(0, int(task.get("tmdb_id", 0) or 0)))
    if task_tmdbid == "0":
        task_tmdbid = ""
    task_name_candidates = _collect_subscription_task_share_dir_name_candidates(task)
    if not task_name_candidates and not task_tmdbid:
        stats["reason"] = "task_clues_empty"
        return {}, stats

    current_leaf_name = start_path.split("/")[-1] if start_path else ""
    current_score = _score_subscription_share_dir_for_task(
        current_leaf_name,
        task_name_candidates,
        task_tmdbid=task_tmdbid,
    )
    stats["current_score"] = current_score
    if current_score >= 170:
        stats["reason"] = "current_match_strong"
        return base_selection, stats

    item_extra = item.get("extra") if isinstance(item.get("extra"), dict) else safe_json_loads(item.get("extra_json"), {})
    receive_code = (
        normalize_receive_code(item.get("receive_code", ""))
        or normalize_receive_code((item_extra or {}).get("receive_code", ""))
    )
    timeout_seconds = max(10, int(per_request_timeout or 25))
    queue: List[Tuple[str, int, str]] = [(start_cid, 0, start_path)]
    visited: Set[str] = set()
    scored_candidates: List[Tuple[int, Dict[str, Any]]] = []

    while queue and int(stats.get("scanned_dirs", 0) or 0) < max(20, int(max_dirs or 140)):
        cid, depth, parent_path = queue.pop(0)
        normalized_cid = str(cid or "").strip()
        if not normalized_cid or normalized_cid in visited:
            continue
        visited.add(normalized_cid)
        try:
            branch = await asyncio.wait_for(
                _fetch_subscription_share_entries(
                    normalized_cookie,
                    share_url,
                    raw_text,
                    normalized_cid,
                    receive_code,
                    force_refresh,
                ),
                timeout=timeout_seconds,
            )
        except Exception:
            continue

        stats["scanned_dirs"] = int(stats.get("scanned_dirs", 0) or 0) + 1
        entries = branch.get("entries", []) if isinstance(branch.get("entries"), list) else []
        if depth == 0:
            stats["start_child_dirs"] = sum(1 for entry in entries if bool(entry.get("is_dir")))
        for entry in entries:
            if not bool(entry.get("is_dir")):
                continue
            entry_name = normalize_relative_path(str(entry.get("name", "") or "").strip())
            if not entry_name:
                continue
            full_path = normalize_relative_path(join_relative_path(parent_path, entry_name))
            score = _score_subscription_share_dir_for_task(
                entry_name,
                task_name_candidates,
                task_tmdbid=task_tmdbid,
            )
            if score > 0:
                candidate = {
                    "id": str(entry.get("id", "") or entry.get("cid", "") or "").strip(),
                    "cid": str(entry.get("cid", "") or entry.get("id", "") or "").strip(),
                    "parent_id": str(entry.get("parent_id", "0") or "0").strip() or "0",
                    "name": full_path,
                    "is_dir": True,
                }
                if candidate["id"] and candidate["cid"] and candidate["name"]:
                    scored_candidates.append((score, candidate))
            if depth < max(1, int(max_depth or 3)):
                child_cid = str(entry.get("cid", "") or entry.get("id", "") or "").strip()
                if child_cid and child_cid not in visited:
                    queue.append((child_cid, depth + 1, full_path))

    stats["candidate_count"] = len(scored_candidates)
    if not scored_candidates:
        stats["reason"] = "not_found"
        return {}, stats

    scored_candidates.sort(key=lambda item: (int(item[0] or 0), len(str(item[1].get("name", "")))), reverse=True)
    best_score = int(scored_candidates[0][0] or 0)
    stats["best_score"] = best_score
    best_candidates = [item[1] for item in scored_candidates if int(item[0] or 0) == best_score]
    stats["ambiguous_count"] = len(best_candidates)
    if len(best_candidates) != 1:
        stats["reason"] = "ambiguous"
        stats["candidate_samples"] = [
            str(item.get("name", "") or "").strip()
            for item in best_candidates[:5]
            if str(item.get("name", "") or "").strip()
        ]
        return {}, stats

    best_candidate = best_candidates[0]
    if best_score < 130:
        stats["reason"] = "weak_match"
        stats["candidate_samples"] = [str(best_candidate.get("name", "") or "").strip()]
        return {}, stats
    if str(best_candidate.get("id", "") or "").strip() == str(start_entry.get("id", "") or "").strip():
        stats["reason"] = "same_as_current"
        return base_selection, stats

    refined_selection = normalize_share_selection_meta(
        {
            "selected_ids": [str(best_candidate.get("id", "") or "").strip()],
            "selected_entries": [best_candidate],
            "refresh_target_type": "folder",
            "share_root_title": str(base_selection.get("share_root_title", "") or "").strip(),
            "auto_sharetitle": str(best_candidate.get("name", "") or "").strip(),
        }
    )
    if not (
        refined_selection.get("selected_ids", [])
        if isinstance(refined_selection.get("selected_ids"), list)
        else []
    ):
        stats["reason"] = "refine_selection_empty"
        return {}, stats
    stats["reason"] = "ok_refined"
    stats["to_path"] = str(best_candidate.get("name", "") or "").strip()
    return refined_selection, stats


def _score_subscription_share_dir_candidate_name(
    entry_name: str,
    expected_name: str,
    expected_tmdbid: str = "",
) -> int:
    normalized_entry_name = normalize_relative_path(entry_name)
    normalized_expected_name = normalize_relative_path(expected_name)
    if not normalized_entry_name:
        return 0
    if normalized_entry_name == normalized_expected_name:
        return 200
    entry_key = _normalize_subscription_share_dir_match_key(normalized_entry_name)
    expected_key = _normalize_subscription_share_dir_match_key(normalized_expected_name)
    if not entry_key or not expected_key:
        return 0
    if entry_key == expected_key:
        return 180
    score = 0
    if expected_tmdbid and expected_tmdbid in entry_key:
        score = max(score, 170)
    expected_key_no_digits = _normalize_subscription_share_dir_match_key(normalized_expected_name, drop_digits=True)
    entry_key_no_digits = _normalize_subscription_share_dir_match_key(normalized_entry_name, drop_digits=True)
    if expected_key_no_digits and entry_key_no_digits and expected_key_no_digits == entry_key_no_digits and len(expected_key_no_digits) >= 6:
        score = max(score, 150)
    short_len = min(len(expected_key), len(entry_key))
    if short_len >= 6 and (expected_key in entry_key or entry_key in expected_key):
        score = max(score, 120 - abs(len(expected_key) - len(entry_key)))
    return max(0, int(score))


async def _find_subscription_share_dir_by_leaf_fallback(
    cookie: str,
    share_url: str,
    raw_text: str,
    receive_code: str,
    expected_leaf_name: str,
    expected_tmdbid: str = "",
    start_cid: str = "0",
    start_parent_path: str = "",
    per_request_timeout: int = 25,
    max_depth: int = 4,
    max_dirs: int = 120,
    force_refresh: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    stats: Dict[str, Any] = {
        "reason": "not_found",
        "scanned_dirs": 0,
        "candidate_count": 0,
        "best_score": 0,
        "ambiguous_count": 0,
    }
    normalized_cookie = str(cookie or "").strip()
    normalized_share_url = str(share_url or "").strip()
    leaf_name = normalize_relative_path(expected_leaf_name)
    if (not normalized_cookie) or (not normalized_share_url) or (not leaf_name):
        stats["reason"] = "invalid_args"
        return {}, stats

    timeout_seconds = max(10, int(per_request_timeout or 25))
    queue: List[Tuple[str, int, str]] = [(
        str(start_cid or "0").strip() or "0",
        0,
        normalize_relative_path(start_parent_path),
    )]
    visited: Set[str] = set()
    scored_candidates: List[Tuple[int, Dict[str, Any]]] = []

    while queue and int(stats.get("scanned_dirs", 0) or 0) < max(10, int(max_dirs or 120)):
        cid, depth, parent_path = queue.pop(0)
        normalized_cid = str(cid or "0").strip() or "0"
        if normalized_cid in visited:
            continue
        visited.add(normalized_cid)
        try:
            branch = await asyncio.wait_for(
                _fetch_subscription_share_entries(
                    normalized_cookie,
                    normalized_share_url,
                    raw_text,
                    normalized_cid,
                    receive_code,
                    force_refresh,
                ),
                timeout=timeout_seconds,
            )
        except Exception:
            continue

        stats["scanned_dirs"] = int(stats.get("scanned_dirs", 0) or 0) + 1
        entries = branch.get("entries", []) if isinstance(branch.get("entries"), list) else []
        for entry in entries:
            if not bool(entry.get("is_dir")):
                continue
            entry_name = normalize_relative_path(str(entry.get("name", "") or "").strip())
            if not entry_name:
                continue
            resolved_path = normalize_relative_path(f"{parent_path}/{entry_name}" if parent_path else entry_name)
            score = _score_subscription_share_dir_candidate_name(
                entry_name=entry_name,
                expected_name=leaf_name,
                expected_tmdbid=expected_tmdbid,
            )
            if score > 0:
                candidate = {
                    "id": str(entry.get("id", "") or entry.get("cid", "") or "").strip(),
                    "cid": str(entry.get("cid", "") or entry.get("id", "") or "").strip(),
                    "parent_id": str(entry.get("parent_id", "0") or "0").strip() or "0",
                    "name": entry_name,
                    "resolved_path": resolved_path,
                }
                if candidate["id"] and candidate["cid"] and candidate["resolved_path"]:
                    scored_candidates.append((score, candidate))
            if depth < max(1, int(max_depth or 4)):
                next_cid = str(entry.get("cid", "") or entry.get("id", "") or "").strip()
                if next_cid and next_cid not in visited:
                    queue.append((next_cid, depth + 1, resolved_path))

    stats["candidate_count"] = len(scored_candidates)
    if not scored_candidates:
        stats["reason"] = "not_found"
        return {}, stats

    scored_candidates.sort(key=lambda item: int(item[0] or 0), reverse=True)
    best_score = int(scored_candidates[0][0] or 0)
    best_candidates = [item[1] for item in scored_candidates if int(item[0] or 0) == best_score]
    stats["best_score"] = best_score
    stats["ambiguous_count"] = len(best_candidates)
    if len(best_candidates) != 1:
        stats["reason"] = "ambiguous"
        stats["candidate_samples"] = [
            str(item.get("resolved_path", "") or "").strip()
            for item in best_candidates[:5]
            if str(item.get("resolved_path", "") or "").strip()
        ]
        return {}, stats
    stats["reason"] = "ok"
    return best_candidates[0], stats


def _match_subscription_share_dir_entry(entries: List[Dict[str, Any]], expected_name: str) -> Dict[str, Any]:
    target_name = normalize_relative_path(expected_name)
    if not target_name:
        return {}
    target_lower = target_name.lower()
    target_key = _normalize_subscription_share_dir_match_key(target_name)
    target_key_no_digits = _normalize_subscription_share_dir_match_key(target_name, drop_digits=True)
    target_tmdbid = _extract_subscription_tmdbid_token(target_name)
    fallback: Dict[str, Any] = {}
    tmdb_hits: List[Tuple[int, Dict[str, Any]]] = []
    no_digit_hits: List[Tuple[int, Dict[str, Any]]] = []
    contains_hits: List[Tuple[int, Dict[str, Any]]] = []
    for entry in entries if isinstance(entries, list) else []:
        if not bool(entry.get("is_dir")):
            continue
        entry_name = normalize_relative_path(str(entry.get("name", "") or "").strip())
        if not entry_name:
            continue
        if entry_name == target_name:
            return entry
        if (not fallback) and entry_name.lower() == target_lower:
            fallback = entry
        entry_key = _normalize_subscription_share_dir_match_key(entry_name)
        if target_key and entry_key:
            if entry_key == target_key:
                return entry
            short_len = min(len(target_key), len(entry_key))
            if short_len >= 6 and (target_key in entry_key or entry_key in target_key):
                contains_hits.append((short_len * 10 - abs(len(target_key) - len(entry_key)), entry))
        if target_tmdbid and entry_key:
            if target_tmdbid in entry_key:
                tmdb_hits.append((len(entry_key), entry))
        if target_key_no_digits:
            entry_key_no_digits = _normalize_subscription_share_dir_match_key(entry_name, drop_digits=True)
            if entry_key_no_digits and entry_key_no_digits == target_key_no_digits and len(entry_key_no_digits) >= 6:
                no_digit_hits.append((len(entry_key_no_digits), entry))

    unique_tmdb = _pick_unique_subscription_share_entry(tmdb_hits)
    if unique_tmdb:
        return unique_tmdb
    unique_no_digits = _pick_unique_subscription_share_entry(no_digit_hits)
    if unique_no_digits:
        return unique_no_digits
    unique_contains = _pick_unique_subscription_share_entry(contains_hits)
    if unique_contains:
        return unique_contains
    return fallback


def _normalize_subscription_share_subdir_parts(share_subdir: str, share_root_title: str = "") -> List[str]:
    requested_parts = [part for part in normalize_relative_path(share_subdir).split("/") if part]
    root_parts = [part for part in normalize_relative_path(share_root_title).split("/") if part]
    if root_parts and len(requested_parts) >= len(root_parts):
        if [part.lower() for part in requested_parts[: len(root_parts)]] == [part.lower() for part in root_parts]:
            requested_parts = requested_parts[len(root_parts) :]
    return requested_parts


def _normalize_subscription_share_subdir_cid(value: Any) -> str:
    return normalize_115_cid(value)


def _format_subscription_share_scope_label(share_subdir: str, share_subdir_cid: str = "") -> str:
    normalized_subdir = normalize_relative_path(share_subdir)
    normalized_cid = _normalize_subscription_share_subdir_cid(share_subdir_cid)
    if normalized_subdir and normalized_cid:
        return f"{normalized_subdir} [CID:{normalized_cid}]"
    if normalized_subdir:
        return normalized_subdir
    if normalized_cid:
        return f"CID:{normalized_cid}"
    return "--"


async def _build_subscription_share_subdir_selection(
    cookie: str,
    item: Dict[str, Any],
    share_subdir: str,
    share_subdir_cid: str = "",
    per_request_timeout: int = 25,
    force_refresh: bool = False,
    allow_fallback: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    normalized_cookie = str(cookie or "").strip()
    share_url = str(item.get("link_url", "") or "").strip()
    raw_text = str(item.get("raw_text", "") or "")
    requested_subdir = normalize_relative_path(share_subdir)
    requested_subdir_cid = _normalize_subscription_share_subdir_cid(share_subdir_cid)
    stats: Dict[str, Any] = {
        "reason": "",
        "requested_subdir": requested_subdir,
        "requested_subdir_cid": requested_subdir_cid,
        "share_root_title": "",
        "resolved_subdir": "",
        "resolved_subdir_cid": "",
        "scanned_dirs": 0,
        "failed_segment": "",
        "matched_depth": 0,
    }
    if not requested_subdir and not requested_subdir_cid:
        stats["reason"] = "share_subdir_empty"
        return {}, stats
    if not normalized_cookie:
        stats["reason"] = "cookie_missing"
        return {}, stats
    if not share_url:
        stats["reason"] = "share_url_missing"
        return {}, stats

    item_extra = item.get("extra") if isinstance(item.get("extra"), dict) else safe_json_loads(item.get("extra_json"), {})
    receive_code = (
        normalize_receive_code(item.get("receive_code", ""))
        or normalize_receive_code((item_extra or {}).get("receive_code", ""))
    )
    request_timeout = max(10, int(per_request_timeout or 25))

    if requested_subdir_cid:
        anchor_branch: Dict[str, Any] = {}
        anchor_error = ""
        anchor_attempts = 0
        max_anchor_retries = 2
        for attempt in range(0, max_anchor_retries + 1):
            anchor_attempts = attempt + 1
            try:
                anchor_branch = await asyncio.wait_for(
                    _fetch_subscription_share_entries(
                        normalized_cookie,
                        share_url,
                        raw_text,
                        requested_subdir_cid,
                        receive_code,
                        force_refresh,
                    ),
                    timeout=request_timeout,
                )
                anchor_error = ""
                break
            except Exception as exc:
                anchor_error = str(exc or "").strip() or exc.__class__.__name__
                if attempt >= max_anchor_retries:
                    stats["anchor_error"] = anchor_error[:180]
                    stats["anchor_retry_attempts"] = anchor_attempts
                    break
                await asyncio.sleep(0.6 * (attempt + 1))

        if anchor_branch:
            stats["scanned_dirs"] = int(stats.get("scanned_dirs", 0) or 0) + 1
            share_root_title = normalize_relative_path(str(anchor_branch.get("share_title", "") or ""))
            stats["share_root_title"] = share_root_title
            resolved_subdir = requested_subdir or normalize_relative_path(f"cid-{requested_subdir_cid}")
            stats["resolved_subdir"] = resolved_subdir
            stats["resolved_subdir_cid"] = requested_subdir_cid
            stats["matched_depth"] = len([part for part in resolved_subdir.split("/") if part]) if resolved_subdir else 0
            stats["reason"] = "ok_cid_anchor"
            selection = normalize_share_selection_meta(
                {
                    "selected_ids": [requested_subdir_cid],
                    "selected_entries": [
                        {
                            "id": requested_subdir_cid,
                            "name": resolved_subdir,
                            "is_dir": True,
                            "parent_id": "0",
                            "cid": requested_subdir_cid,
                            "fid": "",
                        }
                    ],
                    "refresh_target_type": "folder",
                    "share_root_title": share_root_title,
                    "auto_sharetitle": resolved_subdir,
                }
            )
            if not (selection.get("selected_ids", []) if isinstance(selection.get("selected_ids"), list) else []):
                stats["reason"] = "subdir_selection_empty"
                return {}, stats
            return selection, stats

        if not requested_subdir:
            stats["reason"] = "share_anchor_unreachable"
            return {}, stats

    root_branch: Dict[str, Any] = {}
    root_error = ""
    root_attempts = 0
    max_root_retries = 2
    for attempt in range(0, max_root_retries + 1):
        root_attempts = attempt + 1
        try:
            root_branch = await asyncio.wait_for(
                _fetch_subscription_share_entries(
                    normalized_cookie,
                    share_url,
                    raw_text,
                    "0",
                    receive_code,
                    force_refresh,
                ),
                timeout=request_timeout,
            )
            root_error = ""
            break
        except Exception as exc:
            root_error = str(exc or "").strip() or exc.__class__.__name__
            if attempt >= max_root_retries:
                stats["reason"] = "share_root_unreachable"
                stats["root_error"] = root_error[:180]
                stats["root_retry_attempts"] = root_attempts
                return {}, stats
            await asyncio.sleep(0.6 * (attempt + 1))
    stats["scanned_dirs"] = 1
    share_root_title = normalize_relative_path(str(root_branch.get("share_title", "") or ""))
    stats["share_root_title"] = share_root_title

    requested_parts_full = [part for part in requested_subdir.split("/") if part]
    path_parts = _normalize_subscription_share_subdir_parts(requested_subdir, share_root_title)
    if not path_parts:
        stats["reason"] = "target_is_share_root"
        return {}, stats

    current_entries = root_branch.get("entries", []) if isinstance(root_branch.get("entries"), list) else []
    current_cid = "0"
    matched_entry: Dict[str, Any] = {}
    matched_parts: List[str] = []
    fallback_used = False
    root_title_stripped = bool(requested_parts_full and len(path_parts) < len(requested_parts_full))
    if root_title_stripped and share_root_title:
        root_wrapper_entry = _match_subscription_share_dir_entry(current_entries, share_root_title)
        root_wrapper_cid = str((root_wrapper_entry or {}).get("cid", "") or (root_wrapper_entry or {}).get("id", "") or "").strip()
        if root_wrapper_cid:
            try:
                branch = await asyncio.wait_for(
                    _fetch_subscription_share_entries(
                        normalized_cookie,
                        share_url,
                        raw_text,
                        root_wrapper_cid,
                        receive_code,
                        force_refresh,
                    ),
                    timeout=request_timeout,
                )
            except Exception:
                stats["reason"] = "share_root_wrapper_unreachable"
                stats["failed_segment"] = str(path_parts[0] if path_parts else "").strip()
                return {}, stats
            stats["scanned_dirs"] = int(stats.get("scanned_dirs", 0) or 0) + 1
            current_entries = branch.get("entries", []) if isinstance(branch.get("entries"), list) else []
            current_cid = root_wrapper_cid
    for idx, segment in enumerate(path_parts):
        matched_entry = _match_subscription_share_dir_entry(current_entries, segment)
        if not matched_entry:
            if not allow_fallback:
                stats["reason"] = "subdir_not_found"
                stats["failed_segment"] = str(segment or "").strip()
                stats["matched_depth"] = idx
                stats["sibling_dir_samples"] = _sample_subscription_share_dir_names(current_entries, limit=6)
                return {}, stats
            fallback_entry, fallback_stats = await _find_subscription_share_dir_by_leaf_fallback(
                normalized_cookie,
                share_url,
                raw_text,
                receive_code,
                expected_leaf_name=path_parts[-1] if path_parts else str(segment or "").strip(),
                expected_tmdbid=_extract_subscription_tmdbid_token(requested_subdir),
                start_cid=current_cid,
                start_parent_path="/".join(matched_parts),
                per_request_timeout=request_timeout,
                max_depth=max(3, len(path_parts) - idx + 1),
                max_dirs=180,
                force_refresh=force_refresh,
            )
            stats["fallback_reason"] = str((fallback_stats or {}).get("reason", "") or "").strip()
            stats["fallback_scanned_dirs"] = int((fallback_stats or {}).get("scanned_dirs", 0) or 0)
            stats["fallback_candidate_count"] = int((fallback_stats or {}).get("candidate_count", 0) or 0)
            stats["scanned_dirs"] = int(stats.get("scanned_dirs", 0) or 0) + int(
                (fallback_stats or {}).get("scanned_dirs", 0) or 0
            )
            if fallback_entry:
                matched_entry = fallback_entry
                fallback_used = True
                fallback_path = normalize_relative_path(str(fallback_entry.get("resolved_path", "") or "").strip())
                if fallback_path:
                    matched_parts = [part for part in fallback_path.split("/") if part]
                    stats["matched_depth"] = len(matched_parts)
                break
            stats["reason"] = "subdir_not_found"
            stats["failed_segment"] = str(segment or "").strip()
            stats["matched_depth"] = idx
            stats["sibling_dir_samples"] = _sample_subscription_share_dir_names(current_entries, limit=6)
            stats["fallback_candidate_samples"] = (
                (fallback_stats or {}).get("candidate_samples", [])
                if isinstance((fallback_stats or {}).get("candidate_samples", []), list)
                else []
            )
            return {}, stats

        entry_name = normalize_relative_path(str(matched_entry.get("name", "") or "").strip())
        if not entry_name:
            stats["reason"] = "subdir_entry_invalid"
            stats["failed_segment"] = str(segment or "").strip()
            stats["matched_depth"] = idx
            return {}, stats

        matched_parts.append(entry_name)
        stats["matched_depth"] = idx + 1

        if idx >= len(path_parts) - 1:
            break
        child_cid = str(matched_entry.get("cid", "") or matched_entry.get("id", "") or "").strip()
        if not child_cid:
            stats["reason"] = "subdir_cid_missing"
            stats["failed_segment"] = str(segment or "").strip()
            return {}, stats
        try:
            branch = await asyncio.wait_for(
                _fetch_subscription_share_entries(
                    normalized_cookie,
                    share_url,
                    raw_text,
                    child_cid,
                    receive_code,
                    force_refresh,
                ),
                timeout=request_timeout,
            )
        except Exception:
            stats["reason"] = "subdir_branch_unreachable"
            stats["failed_segment"] = str(segment or "").strip()
            return {}, stats
        stats["scanned_dirs"] = int(stats.get("scanned_dirs", 0) or 0) + 1
        current_entries = branch.get("entries", []) if isinstance(branch.get("entries"), list) else []
        current_cid = child_cid

    target_id = str(matched_entry.get("id", "") or matched_entry.get("cid", "") or "").strip()
    target_cid = str(matched_entry.get("cid", "") or target_id).strip()
    target_parent_id = str(matched_entry.get("parent_id", "0") or "0").strip() or "0"
    fallback_resolved_subdir = normalize_relative_path(str(matched_entry.get("resolved_path", "") or "").strip())
    resolved_subdir = fallback_resolved_subdir if fallback_used and fallback_resolved_subdir else normalize_relative_path("/".join(matched_parts))
    stats["resolved_subdir"] = resolved_subdir
    stats["resolved_subdir_cid"] = target_cid

    if not target_id or not target_cid or not resolved_subdir:
        stats["reason"] = "subdir_target_invalid"
        return {}, stats
    if fallback_used:
        stats["reason"] = "ok_fallback_leaf"
    else:
        stats["reason"] = "ok"

    selection = normalize_share_selection_meta(
        {
            "selected_ids": [target_id],
            "selected_entries": [
                {
                    "id": target_id,
                    "name": resolved_subdir,
                    "is_dir": True,
                    "parent_id": target_parent_id,
                    "cid": target_cid,
                    "fid": "",
                }
            ],
            "refresh_target_type": "folder",
            "share_root_title": share_root_title,
            "auto_sharetitle": resolved_subdir,
        }
    )
    if not (selection.get("selected_ids", []) if isinstance(selection.get("selected_ids"), list) else []):
        stats["reason"] = "subdir_selection_empty"
        return {}, stats
    return selection, stats


async def _build_tv_share_selection_for_missing_episodes(
    cookie: str,
    task: Dict[str, Any],
    item: Dict[str, Any],
    missing_episodes: Set[int],
    share_subdir_selection: Optional[Dict[str, Any]] = None,
    max_depth: int = 4,
    max_dirs: int = 80,
    max_entries: int = 3000,
    per_request_timeout: int = 25,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    normalized_cookie = str(cookie or "").strip()
    share_url = str(item.get("link_url", "") or "").strip()
    raw_text = str(item.get("raw_text", "") or "")
    target_missing = {max(0, int(value or 0)) for value in missing_episodes if max(0, int(value or 0)) > 0}
    if not normalized_cookie:
        return {}, {"reason": "cookie_missing"}
    if not share_url:
        return {}, {"reason": "share_url_missing"}
    if not target_missing:
        return {}, {"reason": "missing_episodes_empty"}

    item_extra = item.get("extra") if isinstance(item.get("extra"), dict) else safe_json_loads(item.get("extra_json"), {})
    receive_code = (
        normalize_receive_code(item.get("receive_code", ""))
        or normalize_receive_code((item_extra or {}).get("receive_code", ""))
    )

    share_subdir = normalize_relative_path(str(task.get("share_subdir", "") or "").strip())
    share_subdir_cid = _normalize_subscription_share_subdir_cid(task.get("share_subdir_cid", ""))
    subdir_selection = normalize_share_selection_meta(share_subdir_selection or {})
    subdir_stats: Dict[str, Any] = {}
    start_cid = "0"
    start_parent_path = ""
    if share_subdir or share_subdir_cid:
        if not (
            subdir_selection.get("selected_ids", [])
            if isinstance(subdir_selection.get("selected_ids"), list)
            else []
        ):
            subdir_selection, subdir_stats = await _build_subscription_share_subdir_selection(
                normalized_cookie,
                item,
                share_subdir,
                share_subdir_cid=share_subdir_cid,
                per_request_timeout=per_request_timeout,
            )
        subdir_entries = (
            subdir_selection.get("selected_entries", [])
            if isinstance(subdir_selection.get("selected_entries"), list)
            else []
        )
        subdir_entry = subdir_entries[0] if subdir_entries else {}
        if not subdir_entry or not bool(subdir_entry.get("is_dir")):
            reason = str((subdir_stats or {}).get("reason", "") or "share_subdir_unresolved").strip() or "share_subdir_unresolved"
            return {}, {
                "reason": f"share_subdir_{reason}",
                "share_subdir": share_subdir,
                "share_subdir_cid": share_subdir_cid,
                "share_subdir_stats": subdir_stats,
            }
        start_cid = str(subdir_entry.get("cid", "") or subdir_entry.get("id", "") or "").strip() or "0"
        start_parent_path = normalize_relative_path(str(subdir_entry.get("name", "") or "").strip())

    queue: List[Tuple[str, int, str]] = [(start_cid, 0, start_parent_path)]
    visited: Set[str] = set()
    matched_file_entries: List[Dict[str, Any]] = []
    covered_missing: Set[int] = set()
    share_root_title = ""
    scanned_dirs = 0
    scanned_entries = 0
    failed_dirs = 0
    skipped_archive_files = 0

    request_timeout = max(10, int(per_request_timeout or 25))
    concurrency = max(1, int(SUBSCRIPTION_SHARE_SCAN_CONCURRENCY or 1))
    while queue and scanned_dirs < max_dirs and scanned_entries < max_entries and covered_missing != target_missing:
        batch: List[Tuple[str, int, str]] = []
        while queue and len(batch) < concurrency and (scanned_dirs + len(batch)) < max_dirs:
            cid, depth, parent_path = queue.pop(0)
            normalized_cid = str(cid or "0").strip() or "0"
            if normalized_cid in visited:
                continue
            visited.add(normalized_cid)
            batch.append((normalized_cid, depth, parent_path))
        if not batch:
            break

        check_subscription_cancelled()
        fetch_tasks = [
            asyncio.wait_for(
                _fetch_subscription_share_entries(
                    normalized_cookie,
                    share_url,
                    raw_text,
                    normalized_cid,
                    receive_code,
                ),
                timeout=request_timeout,
            )
            for normalized_cid, _, _ in batch
        ]
        batch_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        for (normalized_cid, depth, parent_path), branch in zip(batch, batch_results):
            if isinstance(branch, Exception):
                failed_dirs += 1
                continue

            scanned_dirs += 1
            if not share_root_title:
                share_root_title = normalize_relative_path(str(branch.get("share_title", "") or ""))
            episode_contexts = _build_subscription_share_episode_context_paths(item, share_root_title)
            entries = branch.get("entries", []) if isinstance(branch.get("entries"), list) else []
            for entry in entries:
                if scanned_entries >= max_entries:
                    break
                scanned_entries += 1
                entry_name = str(entry.get("name", "") or "").strip()
                if not entry_name:
                    continue

                is_dir = bool(entry.get("is_dir"))
                child_cid = str(entry.get("cid", "") or entry.get("id", "") or "").strip()
                rel_name = normalize_relative_path(entry_name)
                full_name = normalize_relative_path(join_relative_path(parent_path, rel_name))

                if is_dir and depth < max_depth and child_cid and child_cid not in visited:
                    queue.append((child_cid, depth + 1, full_name or rel_name))
                if is_dir:
                    continue

                if _is_subscription_skipped_archive_file(rel_name or entry_name):
                    skipped_archive_files += 1
                    continue
                matched_episodes = _extract_task_episodes_from_file_entry(
                    task,
                    rel_name or entry_name,
                    parent_path,
                    context_paths=episode_contexts,
                )
                if not matched_episodes:
                    continue
                episode_hit = matched_episodes.intersection(target_missing)
                if not episode_hit:
                    continue

                entry_id = str(entry.get("id", "") or entry.get("fid", "") or "").strip()
                if not entry_id:
                    continue
                matched_file_entries.append(
                    {
                        "id": entry_id,
                        "name": full_name or rel_name,
                        "is_dir": False,
                        "parent_id": str(entry.get("parent_id", normalized_cid) or normalized_cid).strip() or "0",
                        "cid": "",
                        "fid": str(entry.get("fid", "") or entry_id).strip(),
                        "fid_token": str(entry.get("fid_token", "") or "").strip(),
                        "size": max(0, int(entry.get("size", 0) or 0)),
                        "modified_at": str(entry.get("modified_at", "") or "").strip(),
                        "episodes": sorted(matched_episodes),
                    }
                )
                covered_missing.update(episode_hit)
            if covered_missing == target_missing:
                break

    stats = {
        "reason": "",
        "scanned_dirs": scanned_dirs,
        "scanned_entries": scanned_entries,
        "failed_dirs": failed_dirs,
        "truncated": bool(queue) or scanned_dirs >= max_dirs or scanned_entries >= max_entries,
        "missing_total": len(target_missing),
        "covered_total": len(covered_missing),
        "covered_episodes": sorted(covered_missing)[:300],
        "covered_preview": _format_episode_preview(covered_missing) if covered_missing else "--",
        "selected_count": 0,
        "share_subdir": share_subdir,
        "share_subdir_cid": share_subdir_cid,
        "share_scope_cid": start_cid,
        "share_scope_path": start_parent_path,
        "skipped_archive_files": skipped_archive_files,
    }

    best_selection = _pick_best_tv_share_files_by_episode_bucket(task, matched_file_entries, target_missing)
    selected_entries = (
        best_selection.get("selected_entries", [])
        if isinstance(best_selection.get("selected_entries"), list)
        else []
    )
    selected_ids = (
        best_selection.get("selected_ids", [])
        if isinstance(best_selection.get("selected_ids"), list)
        else []
    )
    covered_missing = _clamp_episode_values(best_selection.get("covered_missing", set()))
    stats["covered_total"] = len(covered_missing)
    stats["covered_episodes"] = sorted(covered_missing)[:300]
    stats["covered_preview"] = _format_episode_preview(covered_missing) if covered_missing else "--"
    stats["selected_count"] = len(selected_ids)
    stats["bucket_count"] = max(0, int(best_selection.get("bucket_count", 0) or 0))
    stats["duplicate_bucket_hits"] = max(0, int(best_selection.get("duplicate_bucket_hits", 0) or 0))
    stats["selected_file_samples"] = _build_subscription_selected_file_samples(
        matched_file_entries,
        selected_ids,
        target_missing,
        sample_limit=8,
    )

    if not selected_ids:
        stats["reason"] = "no_precise_episode_match"
        return {}, stats

    selection = normalize_share_selection_meta(
        {
            "selected_ids": selected_ids,
            "selected_entries": selected_entries,
            "refresh_target_type": "file" if len(selected_ids) == 1 else "mixed",
            "share_root_title": share_root_title,
            "auto_sharetitle": "",
        }
    )
    return selection, stats


async def _scan_subscription_share_tree_snapshot(
    cookie: str,
    task: Dict[str, Any],
    item: Dict[str, Any],
    start_cid: str = "0",
    start_parent_path: str = "",
    max_depth: int = 5,
    max_dirs: int = 180,
    max_entries: int = 5000,
    per_request_timeout: int = 25,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    normalized_cookie = str(cookie or "").strip()
    share_url = str(item.get("link_url", "") or "").strip()
    raw_text = str(item.get("raw_text", "") or "")
    normalized_start_cid = str(start_cid or "0").strip() or "0"
    normalized_start_parent_path = normalize_relative_path(str(start_parent_path or "").strip())
    if not normalized_cookie:
        return {"reason": "cookie_missing", "dirs": [], "files": []}
    if not share_url:
        return {"reason": "share_url_missing", "dirs": [], "files": []}

    item_extra = item.get("extra") if isinstance(item.get("extra"), dict) else safe_json_loads(item.get("extra_json"), {})
    receive_code = (
        normalize_receive_code(item.get("receive_code", ""))
        or normalize_receive_code((item_extra or {}).get("receive_code", ""))
    )

    queue: List[Tuple[str, int, str]] = [(normalized_start_cid, 0, normalized_start_parent_path)]
    visited: Set[str] = set()
    dirs: List[Dict[str, Any]] = []
    files: List[Dict[str, Any]] = []
    seen_dir_ids: Set[str] = set()
    seen_file_ids: Set[str] = set()
    covered_episodes: Set[int] = set()
    scanned_dirs = 0
    scanned_entries = 0
    failed_dirs = 0
    share_root_title = ""
    skipped_archive_files = 0
    request_timeout = max(10, int(per_request_timeout or 25))
    concurrency = max(1, int(SUBSCRIPTION_SHARE_SCAN_CONCURRENCY or 1))

    if normalized_start_parent_path and normalized_start_cid not in ("", "0"):
        dirs.append(
            {
                "id": normalized_start_cid,
                "cid": normalized_start_cid,
                "parent_id": "0",
                "name": normalized_start_parent_path,
                "is_dir": True,
                "depth": 0,
            }
        )
        seen_dir_ids.add(normalized_start_cid)

    while queue and scanned_dirs < max_dirs and scanned_entries < max_entries:
        batch: List[Tuple[str, int, str]] = []
        while queue and len(batch) < concurrency and (scanned_dirs + len(batch)) < max_dirs:
            cid, depth, parent_path = queue.pop(0)
            normalized_cid = str(cid or "0").strip() or "0"
            if normalized_cid in visited:
                continue
            visited.add(normalized_cid)
            batch.append((normalized_cid, depth, normalize_relative_path(parent_path)))
        if not batch:
            break

        check_subscription_cancelled()
        fetch_tasks = [
            asyncio.wait_for(
                _fetch_subscription_share_entries(
                    normalized_cookie,
                    share_url,
                    raw_text,
                    normalized_cid,
                    receive_code,
                    force_refresh,
                ),
                timeout=request_timeout,
            )
            for normalized_cid, _, _ in batch
        ]
        batch_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        for (normalized_cid, depth, parent_path), branch in zip(batch, batch_results):
            if isinstance(branch, Exception):
                failed_dirs += 1
                continue

            scanned_dirs += 1
            if not share_root_title:
                share_root_title = normalize_relative_path(str(branch.get("share_title", "") or "").strip())
            episode_contexts = _build_subscription_share_episode_context_paths(item, share_root_title)
            entries = branch.get("entries", []) if isinstance(branch.get("entries"), list) else []
            for entry in entries:
                if scanned_entries >= max_entries:
                    break
                scanned_entries += 1
                entry_name = str(entry.get("name", "") or "").strip()
                if not entry_name:
                    continue

                rel_name = normalize_relative_path(entry_name)
                full_name = normalize_relative_path(join_relative_path(parent_path, rel_name))
                is_dir = bool(entry.get("is_dir"))
                entry_id = str(entry.get("id", "") or entry.get("cid", "") or entry.get("fid", "") or "").strip()
                child_cid = str(entry.get("cid", "") or entry.get("id", "") or "").strip()
                if is_dir:
                    if entry_id and entry_id not in seen_dir_ids:
                        dirs.append(
                            {
                                "id": entry_id,
                                "cid": child_cid or entry_id,
                                "parent_id": str(entry.get("parent_id", normalized_cid) or normalized_cid).strip() or "0",
                                "name": full_name or rel_name,
                                "is_dir": True,
                                "depth": depth + 1,
                            }
                        )
                        seen_dir_ids.add(entry_id)
                    if depth < max_depth and child_cid and child_cid not in visited:
                        queue.append((child_cid, depth + 1, full_name or rel_name))
                    continue

                if not entry_id or entry_id in seen_file_ids:
                    continue
                if _is_subscription_skipped_archive_file(rel_name or entry_name):
                    skipped_archive_files += 1
                    continue
                matched_episodes = sorted(
                    _extract_task_episodes_from_file_entry(
                        task,
                        rel_name or entry_name,
                        parent_path,
                        context_paths=episode_contexts,
                    )
                )
                files.append(
                    {
                        "id": entry_id,
                        "name": full_name or rel_name,
                        "is_dir": False,
                        "parent_id": str(entry.get("parent_id", normalized_cid) or normalized_cid).strip() or "0",
                        "cid": "",
                        "fid": str(entry.get("fid", "") or entry_id).strip(),
                        "fid_token": str(entry.get("fid_token", "") or "").strip(),
                        "size": max(0, int(entry.get("size", 0) or 0)),
                        "modified_at": str(entry.get("modified_at", "") or "").strip(),
                        "episodes": matched_episodes,
                    }
                )
                seen_file_ids.add(entry_id)
                if matched_episodes:
                    covered_episodes.update(matched_episodes)

    return {
        "reason": "ok",
        "share_root_title": share_root_title,
        "share_scope_cid": normalized_start_cid,
        "share_scope_path": normalized_start_parent_path,
        "dirs": dirs,
        "files": files,
        "covered_episodes": sorted(covered_episodes),
        "covered_preview": _format_episode_preview(covered_episodes) if covered_episodes else "--",
        "file_count": len(files),
        "dir_count": len(dirs),
        "scanned_dirs": scanned_dirs,
        "scanned_entries": scanned_entries,
        "failed_dirs": failed_dirs,
        "truncated": bool(queue) or scanned_dirs >= max_dirs or scanned_entries >= max_entries,
        "force_refresh": bool(force_refresh),
        "skipped_archive_files": skipped_archive_files,
    }


def _build_subscription_share_selection_from_snapshot(
    snapshot: Dict[str, Any],
    share_subdir: str,
    share_subdir_cid: str = "",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    payload = snapshot if isinstance(snapshot, dict) else {}
    requested_subdir = normalize_relative_path(str(share_subdir or "").strip())
    requested_cid = _normalize_subscription_share_subdir_cid(share_subdir_cid)
    share_root_title = normalize_relative_path(str(payload.get("share_root_title", "") or "").strip())
    stats: Dict[str, Any] = {
        "reason": "",
        "requested_subdir": requested_subdir,
        "requested_subdir_cid": requested_cid,
        "share_root_title": share_root_title,
        "resolved_subdir": "",
        "resolved_subdir_cid": "",
        "scanned_dirs": int(payload.get("scanned_dirs", 0) or 0),
        "scanned_entries": int(payload.get("scanned_entries", 0) or 0),
        "failed_dirs": int(payload.get("failed_dirs", 0) or 0),
    }

    if requested_cid:
        resolved_cid = str(payload.get("share_scope_cid", "") or requested_cid).strip() or requested_cid
        resolved_subdir = requested_subdir or normalize_relative_path(str(payload.get("share_scope_path", "") or "").strip())
        resolved_subdir = resolved_subdir or normalize_relative_path(f"cid-{resolved_cid}")
        stats["reason"] = "ok_cid_anchor"
        stats["resolved_subdir"] = resolved_subdir
        stats["resolved_subdir_cid"] = resolved_cid
        return (
            normalize_share_selection_meta(
                {
                    "selected_ids": [resolved_cid],
                    "selected_entries": [
                        {
                            "id": resolved_cid,
                            "name": resolved_subdir,
                            "is_dir": True,
                            "parent_id": "0",
                            "cid": resolved_cid,
                            "fid": "",
                        }
                    ],
                    "refresh_target_type": "folder",
                    "share_root_title": share_root_title,
                    "auto_sharetitle": resolved_subdir,
                }
            ),
            stats,
        )

    if not requested_subdir:
        stats["reason"] = "share_subdir_empty"
        return {}, stats

    requested_parts = _normalize_subscription_share_subdir_parts(requested_subdir, share_root_title)
    if not requested_parts:
        stats["reason"] = "target_is_share_root"
        return {}, stats
    target_path = normalize_relative_path("/".join(requested_parts))
    target_parts_lower = [part.lower() for part in requested_parts]
    dirs = payload.get("dirs", []) if isinstance(payload.get("dirs"), list) else []

    exact_candidates: List[Dict[str, Any]] = []
    suffix_candidates: List[Dict[str, Any]] = []
    leaf_candidates: List[Tuple[int, Dict[str, Any]]] = []
    for entry in dirs:
        if not isinstance(entry, dict) or not bool(entry.get("is_dir")):
            continue
        entry_path = normalize_relative_path(str(entry.get("name", "") or "").strip())
        if not entry_path:
            continue
        entry_parts = [part for part in entry_path.split("/") if part]
        entry_parts_lower = [part.lower() for part in entry_parts]
        if entry_path.lower() == target_path.lower():
            exact_candidates.append(entry)
            continue
        if len(entry_parts_lower) >= len(target_parts_lower) and entry_parts_lower[-len(target_parts_lower) :] == target_parts_lower:
            suffix_candidates.append(entry)
        leaf_score = _score_subscription_share_dir_candidate_name(
            entry_name=entry_parts[-1] if entry_parts else entry_path,
            expected_name=requested_parts[-1],
            expected_tmdbid=_extract_subscription_tmdbid_token(requested_subdir),
        )
        if leaf_score > 0:
            leaf_candidates.append((leaf_score, entry))

    matched_entry: Dict[str, Any] = {}
    if len(exact_candidates) == 1:
        matched_entry = exact_candidates[0]
        stats["reason"] = "ok_exact_path"
    elif len(exact_candidates) > 1:
        exact_candidates.sort(key=lambda item: len(str(item.get("name", "") or "").split("/")))
        matched_entry = exact_candidates[0]
        stats["reason"] = "ok_exact_path_ambiguous"
    elif len(suffix_candidates) == 1:
        matched_entry = suffix_candidates[0]
        stats["reason"] = "ok_suffix_path"
    elif len(suffix_candidates) > 1:
        suffix_candidates.sort(key=lambda item: len(str(item.get("name", "") or "").split("/")))
        matched_entry = suffix_candidates[0]
        stats["reason"] = "ok_suffix_path_ambiguous"
    elif leaf_candidates:
        leaf_candidates.sort(key=lambda item: (int(item[0] or 0), len(str(item[1].get("name", "") or "").split("/"))), reverse=True)
        best_score = int(leaf_candidates[0][0] or 0)
        best_matches = [entry for score, entry in leaf_candidates if int(score or 0) == best_score]
        if len(best_matches) == 1 and best_score >= 130:
            matched_entry = best_matches[0]
            stats["reason"] = "ok_leaf_match"
        else:
            stats["reason"] = "subdir_ambiguous" if len(best_matches) > 1 else "subdir_not_found"
            stats["candidate_samples"] = [
                str(entry.get("name", "") or "").strip()
                for entry in best_matches[:5]
                if str(entry.get("name", "") or "").strip()
            ]
            return {}, stats
    else:
        stats["reason"] = "subdir_not_found"
        stats["candidate_samples"] = [
            str(entry.get("name", "") or "").strip()
            for entry in dirs[:8]
            if isinstance(entry, dict) and str(entry.get("name", "") or "").strip()
        ]
        return {}, stats

    target_id = str(matched_entry.get("id", "") or matched_entry.get("cid", "") or "").strip()
    target_cid = str(matched_entry.get("cid", "") or target_id).strip()
    resolved_subdir = normalize_relative_path(str(matched_entry.get("name", "") or "").strip())
    if not target_id or not target_cid or not resolved_subdir:
        stats["reason"] = "subdir_target_invalid"
        return {}, stats
    stats["resolved_subdir"] = resolved_subdir
    stats["resolved_subdir_cid"] = target_cid
    selection = normalize_share_selection_meta(
        {
            "selected_ids": [target_id],
            "selected_entries": [
                {
                    "id": target_id,
                    "name": resolved_subdir,
                    "is_dir": True,
                    "parent_id": str(matched_entry.get("parent_id", "0") or "0").strip() or "0",
                    "cid": target_cid,
                    "fid": "",
                }
            ],
            "refresh_target_type": "folder",
            "share_root_title": share_root_title,
            "auto_sharetitle": resolved_subdir,
        }
    )
    return selection, stats


def _build_subscription_share_manifest_from_snapshot(
    snapshot: Dict[str, Any],
    selection: Dict[str, Any],
) -> Dict[str, Any]:
    payload = snapshot if isinstance(snapshot, dict) else {}
    normalized_selection = normalize_share_selection_meta(selection or {})
    selected_entries = (
        normalized_selection.get("selected_entries", [])
        if isinstance(normalized_selection.get("selected_entries"), list)
        else []
    )
    start_entry = selected_entries[0] if selected_entries else {}
    if not start_entry or not bool(start_entry.get("is_dir")):
        return {"reason": "selection_invalid", "files": [], "covered_episodes": []}

    raw_scope_path = normalize_relative_path(str(payload.get("share_scope_path", "") or "").strip())
    scope_cid = str(start_entry.get("cid", "") or start_entry.get("id", "") or payload.get("share_scope_cid", "") or "").strip()
    scope_path = normalize_relative_path(str(start_entry.get("name", "") or raw_scope_path or "").strip())
    if scope_cid and scope_cid == str(payload.get("share_scope_cid", "") or "").strip() and not raw_scope_path:
        scope_path = ""
    file_entries = payload.get("files", []) if isinstance(payload.get("files"), list) else []
    scoped_files: List[Dict[str, Any]] = []
    covered_episodes: Set[int] = set()
    for raw_entry in file_entries:
        if not isinstance(raw_entry, dict):
            continue
        entry_name = normalize_relative_path(str(raw_entry.get("name", "") or "").strip())
        if not entry_name:
            continue
        if scope_path and entry_name.lower() != scope_path.lower() and not entry_name.lower().startswith(f"{scope_path.lower()}/"):
            continue
        scoped_files.append(raw_entry)
        entry_episodes = raw_entry.get("episodes", []) if isinstance(raw_entry.get("episodes"), list) else []
        covered_episodes.update(
            max(0, int(value or 0))
            for value in entry_episodes
            if max(0, int(value or 0)) > 0
        )

    return {
        "reason": "ok" if scoped_files else "no_episode_files",
        "share_root_title": str(payload.get("share_root_title", "") or "").strip(),
        "share_scope_cid": scope_cid,
        "share_scope_path": scope_path,
        "files": scoped_files,
        "covered_episodes": sorted(covered_episodes),
        "covered_preview": _format_episode_preview(covered_episodes) if covered_episodes else "--",
        "file_count": len(scoped_files),
        "scanned_dirs": int(payload.get("scanned_dirs", 0) or 0),
        "scanned_entries": int(payload.get("scanned_entries", 0) or 0),
        "failed_dirs": int(payload.get("failed_dirs", 0) or 0),
        "truncated": bool(payload.get("truncated", False)),
        "force_refresh": bool(payload.get("force_refresh", False)),
    }


async def _scan_subscription_share_episode_manifest(
    cookie: str,
    task: Dict[str, Any],
    item: Dict[str, Any],
    selection: Dict[str, Any],
    max_depth: int = 4,
    max_dirs: int = 80,
    max_entries: int = 3000,
    per_request_timeout: int = 25,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    normalized_cookie = str(cookie or "").strip()
    share_url = str(item.get("link_url", "") or "").strip()
    raw_text = str(item.get("raw_text", "") or "")
    if not normalized_cookie:
        return {"reason": "cookie_missing", "files": [], "covered_episodes": []}
    if not share_url:
        return {"reason": "share_url_missing", "files": [], "covered_episodes": []}

    normalized_selection = normalize_share_selection_meta(selection or {})
    selected_entries = (
        normalized_selection.get("selected_entries", [])
        if isinstance(normalized_selection.get("selected_entries"), list)
        else []
    )
    start_entry = selected_entries[0] if selected_entries else {}
    if not start_entry or not bool(start_entry.get("is_dir")):
        return {"reason": "selection_invalid", "files": [], "covered_episodes": []}

    start_cid = str(start_entry.get("cid", "") or start_entry.get("id", "") or "").strip()
    start_parent_path = normalize_relative_path(str(start_entry.get("name", "") or "").strip())
    if not start_cid:
        return {"reason": "selection_invalid", "files": [], "covered_episodes": []}

    item_extra = item.get("extra") if isinstance(item.get("extra"), dict) else safe_json_loads(item.get("extra_json"), {})
    receive_code = (
        normalize_receive_code(item.get("receive_code", ""))
        or normalize_receive_code((item_extra or {}).get("receive_code", ""))
    )
    queue: List[Tuple[str, int, str]] = [(start_cid, 0, start_parent_path)]
    visited: Set[str] = {start_cid}
    files: List[Dict[str, Any]] = []
    seen_file_ids: Set[str] = set()
    covered_episodes: Set[int] = set()
    scanned_dirs = 0
    scanned_entries = 0
    failed_dirs = 0
    share_root_title = normalize_relative_path(str(normalized_selection.get("share_root_title", "") or "").strip())
    concurrency = max(1, int(SUBSCRIPTION_SHARE_SCAN_CONCURRENCY or 1))
    skipped_archive_files = 0

    while queue and scanned_dirs < max_dirs and scanned_entries < max_entries:
        batch: List[Tuple[str, int, str]] = []
        while queue and len(batch) < concurrency and (scanned_dirs + len(batch)) < max_dirs:
            batch.append(queue.pop(0))
        if not batch:
            break

        check_subscription_cancelled()
        fetch_tasks = [
            asyncio.wait_for(
                _fetch_subscription_share_entries(
                    normalized_cookie,
                    share_url,
                    raw_text,
                    str(cid or "0").strip() or "0",
                    receive_code,
                    force_refresh,
                ),
                timeout=max(10, int(per_request_timeout or 25)),
            )
            for cid, _, _ in batch
        ]
        batch_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        for (cid, depth, parent_path), branch in zip(batch, batch_results):
            normalized_cid = str(cid or "0").strip() or "0"
            if isinstance(branch, Exception):
                failed_dirs += 1
                continue

            scanned_dirs += 1
            if not share_root_title:
                share_root_title = normalize_relative_path(str(branch.get("share_title", "") or "").strip())
            episode_contexts = _build_subscription_share_episode_context_paths(item, share_root_title)
            entries = branch.get("entries", []) if isinstance(branch.get("entries"), list) else []
            for entry in entries:
                if scanned_entries >= max_entries:
                    break
                scanned_entries += 1
                entry_name = str(entry.get("name", "") or "").strip()
                if not entry_name:
                    continue

                is_dir = bool(entry.get("is_dir"))
                child_cid = str(entry.get("cid", "") or entry.get("id", "") or "").strip()
                rel_name = normalize_relative_path(entry_name)
                full_name = normalize_relative_path(join_relative_path(parent_path, rel_name))
                if is_dir:
                    if depth < max_depth and child_cid and child_cid not in visited:
                        visited.add(child_cid)
                        queue.append((child_cid, depth + 1, full_name or rel_name))
                    continue

                if _is_subscription_skipped_archive_file(rel_name or entry_name):
                    skipped_archive_files += 1
                    continue
                matched_episodes = sorted(
                    _extract_task_episodes_from_file_entry(
                        task,
                        rel_name or entry_name,
                        parent_path,
                        context_paths=episode_contexts,
                    )
                )
                if not matched_episodes:
                    continue
                entry_id = str(entry.get("id", "") or entry.get("fid", "") or "").strip()
                if (not entry_id) or entry_id in seen_file_ids:
                    continue
                seen_file_ids.add(entry_id)
                files.append(
                    {
                        "id": entry_id,
                        "name": full_name or rel_name,
                        "is_dir": False,
                        "parent_id": str(entry.get("parent_id", normalized_cid) or normalized_cid).strip() or "0",
                        "cid": "",
                        "fid": str(entry.get("fid", "") or entry_id).strip(),
                        "size": max(0, int(entry.get("size", 0) or 0)),
                        "modified_at": str(entry.get("modified_at", "") or "").strip(),
                        "episodes": matched_episodes,
                    }
                )
                covered_episodes.update(matched_episodes)

    return {
        "reason": "ok" if files else "no_episode_files",
        "share_root_title": share_root_title,
        "share_scope_cid": start_cid,
        "share_scope_path": start_parent_path,
        "files": files,
        "covered_episodes": sorted(covered_episodes),
        "covered_preview": _format_episode_preview(covered_episodes) if covered_episodes else "--",
        "file_count": len(files),
        "scanned_dirs": scanned_dirs,
        "scanned_entries": scanned_entries,
        "failed_dirs": failed_dirs,
        "truncated": bool(queue) or scanned_dirs >= max_dirs or scanned_entries >= max_entries,
        "force_refresh": bool(force_refresh),
        "skipped_archive_files": skipped_archive_files,
    }


def _build_tv_share_selection_from_manifest(
    manifest: Dict[str, Any],
    missing_episodes: Set[int],
    task: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    payload = manifest if isinstance(manifest, dict) else {}
    target_missing = {max(0, int(value or 0)) for value in (missing_episodes or set()) if max(0, int(value or 0)) > 0}
    if not target_missing:
        return {}, {"reason": "missing_episodes_empty", "from_runtime_cache": True}

    file_entries = payload.get("files", []) if isinstance(payload.get("files"), list) else []
    best_selection = _pick_best_tv_share_files_by_episode_bucket(task or {}, file_entries, target_missing)
    selected_entries = (
        best_selection.get("selected_entries", [])
        if isinstance(best_selection.get("selected_entries"), list)
        else []
    )
    selected_ids = (
        best_selection.get("selected_ids", [])
        if isinstance(best_selection.get("selected_ids"), list)
        else []
    )
    covered_missing = _clamp_episode_values(best_selection.get("covered_missing", set()))

    stats = {
        "reason": "",
        "from_runtime_cache": True,
        "missing_total": len(target_missing),
        "covered_total": len(covered_missing),
        "covered_episodes": sorted(covered_missing)[:300],
        "covered_preview": _format_episode_preview(covered_missing) if covered_missing else "--",
        "selected_count": len(selected_entries),
        "file_count": max(0, int(payload.get("file_count", 0) or len(file_entries))),
        "scanned_dirs": max(0, int(payload.get("scanned_dirs", 0) or 0)),
        "scanned_entries": max(0, int(payload.get("scanned_entries", 0) or 0)),
        "failed_dirs": max(0, int(payload.get("failed_dirs", 0) or 0)),
        "truncated": bool(payload.get("truncated", False)),
        "skipped_archive_files": max(0, int(payload.get("skipped_archive_files", 0) or 0)),
        "share_scope_cid": str(payload.get("share_scope_cid", "") or "").strip(),
        "share_scope_path": normalize_relative_path(str(payload.get("share_scope_path", "") or "").strip()),
        "bucket_count": max(0, int(best_selection.get("bucket_count", 0) or 0)),
        "duplicate_bucket_hits": max(0, int(best_selection.get("duplicate_bucket_hits", 0) or 0)),
        "selected_file_samples": _build_subscription_selected_file_samples(
            file_entries,
            selected_ids,
            target_missing,
            sample_limit=8,
        ),
    }
    if not selected_entries:
        stats["reason"] = "no_precise_episode_match"
        return {}, stats

    selection = normalize_share_selection_meta(
        {
            "selected_ids": selected_ids,
            "selected_entries": selected_entries,
            "refresh_target_type": "file" if len(selected_entries) == 1 else "mixed",
            "share_root_title": str(payload.get("share_root_title", "") or "").strip(),
            "auto_sharetitle": "",
        }
    )
    stats["reason"] = "ok"
    return selection, stats


def _split_tv_share_selection_by_season(
    task: Dict[str, Any],
    selection: Dict[str, Any],
    manifest: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    normalized_selection = normalize_share_selection_meta(selection or {})
    selected_entries = (
        normalized_selection.get("selected_entries", [])
        if isinstance(normalized_selection.get("selected_entries"), list)
        else []
    )
    stats: Dict[str, Any] = {
        "reason": "",
        "selected_count": len(selected_entries),
        "season_count": 0,
        "resolved_count": 0,
        "unresolved_count": 0,
        "cross_season_entry_count": 0,
        "unresolved_samples": [],
    }

    if not is_subscription_multi_season_mode(task):
        stats["reason"] = "single_season_mode"
        return [], stats
    if not selected_entries:
        stats["reason"] = "selection_empty"
        return [], stats

    file_entries = [entry for entry in selected_entries if isinstance(entry, dict) and not bool(entry.get("is_dir"))]
    if not file_entries:
        stats["reason"] = "selection_has_no_files"
        return [], stats
    if len(file_entries) != len(selected_entries):
        stats["reason"] = "selection_contains_dirs"
        return [], stats

    manifest_lookup: Dict[str, Set[int]] = {}
    manifest_payload = manifest if isinstance(manifest, dict) else {}
    manifest_files = manifest_payload.get("files", []) if isinstance(manifest_payload.get("files"), list) else []
    for raw_entry in manifest_files:
        if not isinstance(raw_entry, dict):
            continue
        entry_id = str(raw_entry.get("id", "") or raw_entry.get("fid", "") or "").strip()
        if not entry_id:
            continue
        entry_episodes = _clamp_episode_values(
            {
                max(0, int(value or 0))
                for value in (raw_entry.get("episodes", []) if isinstance(raw_entry.get("episodes"), list) else [])
                if max(0, int(value or 0)) > 0
            }
        )
        if entry_episodes:
            manifest_lookup[entry_id] = entry_episodes

    grouped_entries: Dict[int, List[Dict[str, Any]]] = {}
    grouped_ids: Dict[int, List[str]] = {}
    grouped_episodes: Dict[int, Set[int]] = {}
    unresolved_samples: List[str] = []
    cross_season_entry_count = 0

    for entry in file_entries:
        entry_id = str(entry.get("id", "") or entry.get("fid", "") or "").strip()
        entry_name = normalize_relative_path(str(entry.get("name", "") or "").strip())
        if not entry_id or not entry_name:
            continue

        entry_episodes = set(manifest_lookup.get(entry_id, set()))
        if not entry_episodes:
            entry_parts = [part for part in entry_name.split("/") if part]
            file_name = entry_parts[-1] if entry_parts else entry_name
            parent_path = normalize_relative_path("/".join(entry_parts[:-1]))
            entry_episodes = _clamp_episode_values(
                _extract_task_episodes_from_file_entry(
                    task,
                    file_name,
                    parent_path,
                    context_paths=[str(normalized_selection.get("share_root_title", "") or "").strip()],
                )
            )

        mapped_seasons: List[int] = []
        for absolute_episode in sorted(entry_episodes):
            season_no, _ = convert_subscription_absolute_to_season_episode(task, absolute_episode)
            if season_no > 0:
                mapped_seasons.append(season_no)

        if not mapped_seasons:
            if len(unresolved_samples) < 3:
                unresolved_samples.append(entry_name[:96])
            continue

        unique_seasons = sorted(set(mapped_seasons))
        target_season = unique_seasons[0]
        if len(unique_seasons) > 1:
            cross_season_entry_count += 1

        grouped_entries.setdefault(target_season, []).append(entry)
        grouped_ids.setdefault(target_season, []).append(entry_id)
        grouped_episodes.setdefault(target_season, set()).update(entry_episodes)

    if not grouped_entries:
        stats["reason"] = "season_unresolved"
        stats["unresolved_count"] = len(file_entries)
        stats["unresolved_samples"] = unresolved_samples
        return [], stats

    groups: List[Dict[str, Any]] = []
    for season_no in sorted(grouped_entries):
        group_selection = normalize_share_selection_meta(
            {
                "selected_ids": grouped_ids.get(season_no, []),
                "selected_entries": grouped_entries.get(season_no, []),
                "refresh_target_type": "file" if len(grouped_entries.get(season_no, [])) == 1 else "mixed",
                "share_root_title": normalized_selection.get("share_root_title", ""),
                "auto_sharetitle": "",
            }
        )
        group_episodes = _clamp_episode_values(grouped_episodes.get(season_no, set()))
        groups.append(
            {
                "season": season_no,
                "selection": group_selection,
                "episodes": group_episodes,
                "selected_count": len(group_selection.get("selected_ids", [])),
            }
        )

    stats["reason"] = "partial" if unresolved_samples else "ok"
    stats["season_count"] = len(groups)
    stats["resolved_count"] = sum(len(group.get("selection", {}).get("selected_ids", [])) for group in groups)
    stats["unresolved_count"] = max(0, len(file_entries) - int(stats["resolved_count"] or 0))
    stats["cross_season_entry_count"] = cross_season_entry_count
    stats["unresolved_samples"] = unresolved_samples
    return groups, stats


__all__ = [
    "_normalize_subscription_share_dir_match_key",
    "_extract_subscription_tmdbid_token",
    "_pick_unique_subscription_share_entry",
    "_sample_subscription_share_dir_names",
    "_build_subscription_share_episode_context_paths",
    "_collect_subscription_task_share_dir_name_candidates",
    "_score_subscription_share_dir_for_task",
    "_refine_subscription_share_selection_for_task",
    "_score_subscription_share_dir_candidate_name",
    "_find_subscription_share_dir_by_leaf_fallback",
    "_match_subscription_share_dir_entry",
    "_normalize_subscription_share_subdir_parts",
    "_normalize_subscription_share_subdir_cid",
    "_format_subscription_share_scope_label",
    "_build_subscription_share_subdir_selection",
    "_build_tv_share_selection_for_missing_episodes",
    "_scan_subscription_share_tree_snapshot",
    "_build_subscription_share_selection_from_snapshot",
    "_build_subscription_share_manifest_from_snapshot",
    "_scan_subscription_share_episode_manifest",
    "_build_tv_share_selection_from_manifest",
    "_split_tv_share_selection_by_season",
]
