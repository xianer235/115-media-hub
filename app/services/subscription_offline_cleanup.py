import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Set, Tuple

from ..core import (
    get_config,
    join_relative_path,
    normalize_relative_path,
)
from ..providers.registry import get_or_none as get_provider_or_none
from .resource import RESOURCE_OFFLINE_POLL_MAX_PAGES
from .subscription_task_runner import (
    SUBSCRIPTION_OFFLINE_RETENTION_DAYS,
    SUBSCRIPTION_OFFLINE_SCAN_MAX_DIRS,
    SUBSCRIPTION_OFFLINE_SCAN_MAX_ENTRIES,
    _get_subscription_offline_staging_root,
    _is_subscription_offline_junk_file,
    _subscription_offline_file_older_than,
)


logger = logging.getLogger(__name__)


def subscription_offline_cleanup_interval_seconds() -> int:
    return max(
        60,
        int(os.environ.get("SUBSCRIPTION_OFFLINE_CLEANUP_INTERVAL_SECONDS", 1800) or 1800),
    )


def _collect_staging_tree(
    provider: Any,
    cookie: str,
    task_cid: str,
    root_parent_cid: str = "",
) -> Dict[str, Any]:
    files: List[Dict[str, Any]] = []
    dirs: List[Dict[str, Any]] = []
    junk_ids: List[str] = []
    scanned_dirs = 0
    scanned_entries = 0
    truncated = False
    pending: List[Tuple[str, str, str]] = [("", str(task_cid or "").strip() or "0", str(root_parent_cid or "").strip() or "")]
    while pending and scanned_dirs < SUBSCRIPTION_OFFLINE_SCAN_MAX_DIRS:
        rel, cid, parent_cid = pending.pop(0)
        try:
            entries = provider.list_entries(cookie, cid)
        except Exception as exc:
            logger.warning("订阅中转清理读取目录失败（%s）：%s", rel or "/", exc)
            continue
        scanned_dirs += 1
        dirs.append({"rel": rel, "cid": cid, "parent_cid": parent_cid})
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
            child_rel = join_relative_path(rel, name)
            if bool(entry.get("is_dir", False)):
                pending.append((child_rel, entry_id, cid))
                continue
            if _is_subscription_offline_junk_file(child_rel):
                junk_ids.append(entry_id)
                continue
            files.append(
                {
                    "id": entry_id,
                    "rel": child_rel,
                    "parent_cid": cid,
                    "size": max(0, int(entry.get("size", 0) or 0)),
                    "modified_at": str(entry.get("modified_at", "") or "").strip(),
                }
            )
        if truncated:
            break
    return {
        "files": files,
        "dirs": dirs,
        "junk_ids": junk_ids,
        "scanned_dirs": scanned_dirs,
        "scanned_entries": scanned_entries,
        "truncated": truncated,
    }


async def _clean_one_staging_task(
    provider: Any,
    cookie: str,
    task_cid: str,
    root_parent_cid: str,
    *,
    has_running_task: bool = False,
) -> Dict[str, Any]:
    stats: Dict[str, Any] = {
        "junk_deleted": 0,
        "expired_deleted": 0,
        "empty_dirs_deleted": 0,
        "kept_files": 0,
        "skipped_running": False,
    }
    if has_running_task:
        stats["skipped_running"] = True
        return stats
    tree = await asyncio.to_thread(
        _collect_staging_tree,
        provider,
        cookie,
        task_cid,
        root_parent_cid,
    )

    if tree["junk_ids"]:
        await asyncio.to_thread(provider.delete_entries, cookie, tree["junk_ids"], task_cid)
        stats["junk_deleted"] += len(tree["junk_ids"])

    expired_ids = {
        str(entry.get("id", "") or "").strip()
        for entry in tree["files"]
        if _subscription_offline_file_older_than(entry, SUBSCRIPTION_OFFLINE_RETENTION_DAYS)
    }
    if expired_ids:
        await asyncio.to_thread(provider.delete_entries, cookie, sorted(expired_ids), task_cid)
        stats["expired_deleted"] += len(expired_ids)
    remaining_files = [
        entry
        for entry in tree["files"]
        if str(entry.get("id", "") or "").strip() not in expired_ids
    ]
    stats["kept_files"] = len(remaining_files)

    if tree["dirs"]:
        file_dirs = {str(entry.get("parent_cid", "") or "").strip() for entry in remaining_files}
        depth_by_cid: Dict[str, int] = {}
        for dir_entry in tree["dirs"]:
            depth_by_cid[str(dir_entry.get("cid", "") or "")] = len(
                [part for part in str(dir_entry.get("rel", "") or "").split("/") if part]
            )
        descendant_has_files: Set[str] = set()
        ordered_dirs = sorted(
            tree["dirs"],
            key=lambda dir_entry: depth_by_cid.get(str(dir_entry.get("cid", "") or ""), 0),
            reverse=True,
        )
        for dir_entry in ordered_dirs:
            dir_cid = str(dir_entry.get("cid", "") or "").strip()
            if dir_cid in file_dirs or dir_cid in descendant_has_files:
                descendant_has_files.add(str(dir_entry.get("parent_cid", "") or "").strip())
        deletable_dirs = [
            dir_entry
            for dir_entry in ordered_dirs
            if str(dir_entry.get("cid", "") or "").strip() not in file_dirs
            and str(dir_entry.get("cid", "") or "").strip() not in descendant_has_files
        ]
        for dir_entry in deletable_dirs:
            dir_cid = str(dir_entry.get("cid", "") or "").strip()
            parent_cid = str(dir_entry.get("parent_cid", "") or task_cid).strip() or task_cid
            try:
                await asyncio.to_thread(provider.delete_entries, cookie, [dir_cid], parent_cid)
                stats["empty_dirs_deleted"] += 1
            except Exception as exc:
                logger.warning(
                    "订阅中转清理空目录失败（%s）：%s",
                    str(dir_entry.get("rel", "") or ""),
                    exc,
                )
    return stats


async def run_subscription_offline_staging_cleanup_once() -> Dict[str, Any]:
    cfg = get_config()
    provider = get_provider_or_none("115")
    if not provider or not provider.supports_offline:
        return {"skipped": "offline_unsupported"}
    cookie = provider.get_cookie(cfg)
    if not cookie:
        return {"skipped": "no_cookie"}
    staging_root = _get_subscription_offline_staging_root(cfg)
    try:
        root_cid = str(
            await asyncio.to_thread(provider.resolve_folder_id_by_path, cookie, staging_root) or ""
        ).strip()
    except Exception:
        return {"skipped": "staging_root_missing"}
    if not root_cid or root_cid == "0":
        return {"skipped": "staging_root_missing"}

    running_folder_ids: Set[str] = set()
    try:
        page_count = 1
        page = 1
        while page <= page_count and page <= RESOURCE_OFFLINE_POLL_MAX_PAGES:
            query_result = await asyncio.wait_for(
                asyncio.to_thread(provider.query_offline_tasks, cookie, page),
                timeout=60,
            )
            query_result = query_result if isinstance(query_result, dict) else {}
            raw_tasks = query_result.get("tasks") or []
            page_count = max(1, min(20, int(query_result.get("page_count", page_count) or 1)))
            for raw_task in raw_tasks:
                if not isinstance(raw_task, dict):
                    continue
                status = int(raw_task.get("status", 0) or 0)
                if status in (2, -1):
                    continue
                wp_path_id = str(raw_task.get("wp_path_id", "") or "").strip()
                if wp_path_id:
                    running_folder_ids.add(wp_path_id)
            page += 1
    except Exception as exc:
        logger.warning("订阅中转清理读取离线任务状态失败，按无运行任务处理：%s", exc)

    entries = await asyncio.to_thread(provider.list_entries, cookie, root_cid)
    stats: Dict[str, Any] = {
        "tasks_scanned": 0,
        "junk_deleted": 0,
        "expired_deleted": 0,
        "empty_dirs_deleted": 0,
        "kept_files": 0,
        "skipped_running": 0,
    }
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or not bool(entry.get("is_dir", False)):
            continue
        task_cid = str(entry.get("id", "") or "").strip()
        if not task_cid:
            continue
        stats["tasks_scanned"] += 1
        task_result = await _clean_one_staging_task(
            provider,
            cookie,
            task_cid,
            root_cid,
            has_running_task=task_cid in running_folder_ids,
        )
        for key in ("junk_deleted", "expired_deleted", "empty_dirs_deleted", "kept_files"):
            stats[key] += int(task_result.get(key, 0) or 0)
        if bool(task_result.get("skipped_running", False)):
            stats["skipped_running"] += 1
    if (
        int(stats.get("junk_deleted", 0) or 0) > 0
        or int(stats.get("expired_deleted", 0) or 0) > 0
        or int(stats.get("empty_dirs_deleted", 0) or 0) > 0
    ):
        logger.info("订阅磁力中转定期清理完成：%s", stats)
    return stats


async def subscription_offline_staging_cleanup_watcher() -> None:
    await asyncio.sleep(30)
    while True:
        try:
            await run_subscription_offline_staging_cleanup_once()
        except Exception as exc:
            logger.warning("订阅磁力中转定期清理失败：%s", exc)
        await asyncio.sleep(subscription_offline_cleanup_interval_seconds())
