import logging
import re

from ..background import submit_background
from ..core import *  # noqa: F401,F403
from ..db import retry_sqlite_locked
from ..memory import release_process_memory
from .notify import push_monitor_success_notification
from .strm_files import delete_managed_strm_file, managed_strm_file_path, remove_empty_parent_dirs
from .monitor_runs import add_source as add_monitor_run_source
from .monitor_runs import create_run as create_monitor_run
from .monitor_runs import finish_run as finish_monitor_run
from .monitor_runs import get_run_detail as get_monitor_run_detail
from .monitor_runs import link_runs as link_monitor_runs
from .monitor_runs import record_event as record_monitor_run_event
from .monitor_runs import start_run as start_monitor_run
from .monitor_runs import update_run as update_monitor_run
from .monitor_runs import set_parent_run as set_monitor_run_parent


MONITOR_DIR_MISSING_RELEASE_CONFIRMATIONS = 2
MONITOR_SCAN_SAVEPATHS_MAX = 50
_monitor_dispatch_pending = False


def _monitor_run_scope(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """A queue request has one explicit scope regardless of who triggered it."""
    normalized = _normalize_monitor_queue_payload(payload)
    paths = _monitor_savepath_scopes(normalized)
    if paths:
        return {"kind": "paths", "paths": paths}
    sharetitle = normalize_relative_path(str(normalized.get("sharetitle", "") or ""))
    return {"kind": "task", "hint": sharetitle} if sharetitle else {"kind": "task"}


def _monitor_run_subject(task_name: str, start_paths: Optional[List[str]] = None) -> str:
    paths = [normalize_remote_path(path) for path in (start_paths or []) if str(path or "").strip()]
    if not paths:
        return "全部目录"
    labels = [os.path.basename(path.rstrip("/")) or path for path in paths]
    if len(labels) == 1:
        return labels[0]
    return f"{'、'.join(labels[:2])} 等 {len(labels)} 个文件夹"


def _monitor_run_change_detail(detail: Dict[str, Any]) -> Dict[str, Any]:
    """Add stable, human-readable fields when persisting a change event.

    ``monitor_changes`` deliberately keeps its result payload backwards
    compatible for callers that compare it directly.  The run-record view can
    still expose the useful old/new names without changing that lower-level
    contract.
    """
    source = dict(detail) if isinstance(detail, dict) else {}
    kind = str(source.get("kind", "") or "").strip().lower()
    if kind == "folder":
        old_path = str(source.get("old_path", "") or "").strip()
        new_path = str(source.get("new_path", "") or "").strip()
        source.setdefault("step", "网盘目录变更")
        source.setdefault("old_name", os.path.basename(old_path.rstrip("/")) if old_path else "")
        source.setdefault("new_name", os.path.basename(new_path.rstrip("/")) if new_path else "")
        source.setdefault("operation_label", {
            "rename": "网盘重命名",
            "move": "网盘移动",
            "delete": "网盘删除",
            "create": "网盘新增",
        }.get(str(source.get("operation", "") or "").lower(), "网盘目录操作"))
        return source
    if kind == "file":
        changes = source.get("changes") if isinstance(source.get("changes"), list) else []
        deleted = next((item for item in changes if isinstance(item, dict) and item.get("action") == "delete"), {})
        generated = next((item for item in changes if isinstance(item, dict) and item.get("action") in {"generate", "write"}), {})
        old_path = str(deleted.get("path", "") or "").strip()
        new_path = str(generated.get("path", "") or "").strip()
        source.setdefault("step", "STRM 文件变更")
        source.setdefault("old_path", old_path)
        source.setdefault("new_path", new_path)
        source.setdefault("old_name", os.path.basename(old_path) if old_path else "")
        source.setdefault("new_name", os.path.basename(new_path) if new_path else "")
        source.setdefault("operation_label", "STRM 更新" if old_path and new_path else ("STRM 删除" if old_path else "STRM 新增"))
        return source
    return source


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


def _auto_organize_phrase(auto_summary: Any) -> str:
    auto_raw = str(auto_summary or "").strip()
    if not auto_raw or auto_raw == "-":
        return ""
    matched = re.search(r"已自动整理\s*(\d+)\s*项", auto_raw)
    return f"已自动整理 {matched.group(1)} 项" if matched else "已自动整理"


def build_monitor_run_summary(stats: Dict[str, Any], auto_summary: Any = "") -> str:
    """构建运行记录用的中文结论。

    运行记录直接呈现这句话，所以不能再复用文本日志的 `结论: … | …` 行；数值交给
    记录里的统计字段，句子只说明“发生了什么、有没有需要处理的内容”。
    """
    payload = stats if isinstance(stats, dict) else {}
    generated = max(0, int(payload.get("generated", 0) or 0))
    deleted = max(0, int(payload.get("deleted_files", 0) or 0))
    failed_dirs = max(0, int(payload.get("failed_dirs", 0) or 0))
    auto_phrase = _auto_organize_phrase(auto_summary)
    changes = []
    if generated:
        changes.append(f"新增或更新 {generated} 个本地播放文件")
    if deleted:
        changes.append(f"清理 {deleted} 个")
    if auto_phrase:
        changes.append(auto_phrase)
    detail = "，".join(changes)
    if failed_dirs:
        sentence = f"{failed_dirs} 个目录读取失败，本轮未完整检查"
        if detail:
            sentence += f"：{detail}"
        # 扫描到读取失败时，执行器会主动跳过过期清理以避免误删。
        sentence += "。为避免误删，本轮未执行过期清理。"
        return sentence
    if detail:
        return f"检查完成：{detail}。"
    return "检查完成，没有需要更新的内容。"


def build_monitor_change_run_summary(result: Dict[str, Any]) -> str:
    """构建「增量变更同步」运行记录用的中文结论（文本日志仍用汇总行）。"""
    payload = result if isinstance(result, dict) else {}
    completed = max(0, int(payload.get("completed", 0) or 0))
    failed = max(0, int(payload.get("failed", 0) or 0))
    discarded = max(0, int(payload.get("discarded", 0) or 0))
    generated = max(0, int(payload.get("generated", 0) or 0))
    deleted = max(0, int(payload.get("deleted", 0) or 0))
    manual_required = max(0, int(payload.get("manual_required", 0) or 0))
    events = completed + failed + discarded
    if not events and not generated and not deleted:
        return "检查完成，没有待处理的变更。"
    changes = []
    if generated:
        changes.append(f"新增或更新 {generated} 个本地播放文件")
    if deleted:
        changes.append(f"清理 {deleted} 个")
    detail = "，".join(changes)
    if failed:
        head = f"已同步 {completed} 条网盘变更，{failed} 条处理失败并保留重试"
    elif manual_required:
        head = f"已同步 {completed} 条网盘变更，{manual_required} 个目录需要手动监控"
    else:
        head = f"已同步 {completed} 条网盘变更"
    if discarded:
        head += f"，{discarded} 条已结束不再重试"
    return f"{head}：{detail}。" if detail else f"{head}。"


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
        build_scraper_organize_plan,
        create_scraper_job_from_plan,
        get_scraper_jobs_state,
        run_scraper_job,
    )

    if not new_media_items:
        return "没有新增媒体文件"
    cookie = str(cfg.get("cookie_115", "") or "").strip()
    parent_cid_cache: Dict[str, str] = {}
    parent_items: Dict[str, List[Dict[str, Any]]] = {}
    scan_rel = ""
    try:
        _scan_provider, scan_rel = resolve_provider_relative_path(
            cfg,
            normalize_remote_path(task.get("scan_path", "")),
            expected_provider="115",
        )
        scan_rel = normalize_relative_path(scan_rel)
    except Exception:
        scan_rel = ""
    # 直接躺在监控根目录下的散文件：不能把"监控目录本身"当成条目去改名，
    # 而要按文件条目整理（后续按片名归档成文件夹）。
    root_file_items: List[Dict[str, Any]] = []
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
        if scan_rel and parent_rel == scan_rel:
            root_file_items.append({"item": item, "fid": fid, "mount_rel": mount_rel, "parent_rel": parent_rel})
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
    if not parent_items and not root_file_items:
        return f"新增文件无法解析网盘路径，跳过 {len(new_media_items)} 项"
    entries: List[Dict[str, Any]] = []
    for root_item in root_file_items:
        item = root_item["item"] if isinstance(root_item.get("item"), dict) else {}
        parent_rel = str(root_item.get("parent_rel", "") or "")
        parent_cid = parent_cid_cache.get(parent_rel, "")
        if not parent_cid:
            try:
                parent_cid, _exists = _walk_existing_folder("115", cookie, "0", parent_rel)
            except Exception:
                parent_cid = ""
            parent_cid_cache[parent_rel] = parent_cid
        if not parent_cid:
            continue
        mount_rel = str(root_item.get("mount_rel", "") or "")
        entries.append(
            {
                "id": str(root_item.get("fid", "") or ""),
                "cid": str(root_item.get("fid", "") or ""),
                "name": str(item.get("name", "") or "").strip() or os.path.basename(mount_rel),
                "is_dir": False,
                "parent_id": parent_cid,
                "parent_path": parent_rel,
                "path": mount_rel,
            }
        )
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
    raw_auto_options = task.get("auto_scrape_options") if isinstance(task.get("auto_scrape_options"), dict) else {}
    auto_options = {"title_language": "zh", "delete_ad_files": False}
    if raw_auto_options:
        auto_options.update(_normalize_scraper_batch_preferences(raw_auto_options))
    # 散文件（监控根目录下的文件）也要归档进「片名 (年份)/」，与接收夹快捷导入保持一致。
    auto_options["force_media_folder"] = True
    # 与接收夹快捷导入共用同一套整理流程：识别口径、命名选项、置信度门槛完全一致。
    outcome = build_scraper_organize_plan("115", entries, auto_options)
    plan = outcome.get("plan") if isinstance(outcome.get("plan"), dict) else {}
    if not plan:
        return "新增条目无高置信度自动匹配，已跳过（可在刮削页手动整理）"
    ready_count = max(0, int(plan.get("ready_count", 0) or 0))
    if ready_count <= 0:
        return "高置信度条目无可执行动作"
    job = create_scraper_job_from_plan({"plan": plan})
    job_id = max(0, int(job.get("job_id", 0) or 0))
    run_scraper_job(job_id)
    jobs = get_scraper_jobs_state(job_id=job_id).get("jobs", []) if job_id > 0 else []
    actual = jobs[0] if isinstance(jobs, list) and jobs else {}
    status = str(actual.get("status", "") or "").strip()
    succeeded = max(0, int(actual.get("succeeded_actions", 0) or 0))
    failed = max(0, int(actual.get("failed_actions", 0) or 0))
    if status == "completed":
        return f"已自动整理 {succeeded} 项（任务 #{job_id}）"
    if status == "partial":
        return f"自动整理部分完成：成功 {succeeded} 项，失败 {failed} 项（任务 #{job_id}）"
    if status in {"failed", "rollback_failed"}:
        return f"自动整理失败：{str(actual.get('status_detail', '') or '任务执行失败')[:120]}（任务 #{job_id}）"
    # Mocks and older job stores may not expose the just-created job.  The
    # production path always has a durable job row, so retain a useful result.
    return f"已自动整理 {ready_count} 项（任务 #{job_id}）"


async def run_monitor_task(
    task_name: str,
    trigger: str = "manual",
    payload: Optional[Dict[str, Any]] = None,
    merged_count: int = 0,
    run_id: str = "",
) -> None:
    run_id = str(run_id or "").strip()
    if not _claim_monitor_job(task_name):
        return
    cfg = get_config()
    task = next((t for t in cfg["monitor_tasks"] if t["name"] == task_name), None)
    if not task:
        await write_monitor_log(f"任务不存在: {task_name}", "error")
        finish_monitor_run(run_id, status="failed", summary="监控任务不存在", result={"task_name": task_name})
        await _finish_monitor_job(task_name, "monitor")
        return
    if normalize_task_type(task.get("task_type")) == MONITOR_TASK_TYPE_INBOX:
        # 兜底：接收夹任务不接受目录扫描触发（正常路径不会走到这里）。
        await write_monitor_log(f"接收夹任务「{task_name}」不参与目录扫描，已忽略本次扫描触发", "warn")
        finish_monitor_run(run_id, status="cancelled", summary="接收夹不参与目录扫描")
        await _finish_monitor_job(task_name, "monitor")
        return
    config_error = validate_monitor_runtime_config(cfg, task)
    if config_error:
        await write_monitor_log(f"任务配置错误: {config_error}", "error")
        finish_monitor_run(run_id, status="failed", summary=config_error)
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
        start_monitor_run(run_id, subject=_monitor_run_subject(task_name, _monitor_run_scope(payload).get("paths")))
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
        update_monitor_run(
            run_id,
            subject=_monitor_run_subject(task_name, start_remote_paths),
            result={"scope": {"kind": "paths" if start_remote_paths != [task_scan_path] else "task", "paths": start_remote_paths}},
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
                record_monitor_run_event(
                    run_id,
                    category="problem",
                    operation="read_dir",
                    status="failed",
                    title=os.path.basename(remote_dir.rstrip("/")) or remote_dir,
                    detail={"path": remote_dir, "error": str(exc)},
                )
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
                    record_monitor_run_event(
                        run_id,
                        category="strm",
                        operation="write",
                        status="completed",
                        title=os.path.basename(target_file),
                        detail={
                            "step": "生成 STRM",
                            "operation_label": "STRM 更新" if force_strm_rewrite else "STRM 新增",
                            "path": target_file,
                            "strm_path": target_file,
                            "remote_path": item_remote_path,
                            "rewrite": force_strm_rewrite,
                        },
                    )
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
                    record_monitor_run_event(
                        run_id,
                        category="strm",
                        operation="delete",
                        status="completed",
                        title=os.path.basename(target_file),
                        detail={
                            "step": "删除 STRM",
                            "operation_label": "STRM 删除",
                            "path": target_file,
                            "strm_path": target_file,
                        },
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
        final_result = {
            "generated": stats["generated"], "skipped": stats["skipped"],
            "deleted": stats["deleted_files"], "failed_dirs": stats["failed_dirs"],
            "auto_summary": auto_summary,
        }
        final_status = "partial" if stats["failed_dirs"] else ("no_change" if not stats["generated"] and not stats["deleted_files"] else "completed")
        finish_monitor_run(run_id, status=final_status, summary=build_monitor_run_summary(stats, auto_summary), result=final_result)
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
        finish_monitor_run(run_id, status="cancelled", summary="监控扫描已中断", result=stats)
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
        record_monitor_run_event(run_id, category="problem", operation="scan", status="failed", title="扫描失败", detail={"error": str(exc)})
        finish_monitor_run(run_id, status="failed", summary=str(exc), result=stats)
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


def _best_effort_monitor_change_call(label: str, callback: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return callback(*args, **kwargs)
    except Exception:
        logging.exception(label)
        return None


async def _best_effort_monitor_change_await(label: str, callback: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return await callback(*args, **kwargs)
    except Exception:
        logging.exception(label)
        return None


async def run_monitor_change_task(
    task_name: str,
    trigger: str = "change",
    payload: Optional[Dict[str, Any]] = None,
    run_id: str = "",
) -> None:
    """Consume persisted scraper mutations without entering the scan walker."""
    run_id = str(run_id or "").strip()
    if not _claim_monitor_job(task_name):
        _best_effort_monitor_change_call(
            "Failed to close unclaimed monitor change run",
            finish_monitor_run,
            run_id,
            status="cancelled",
            summary="任务未能开始，已退出本次排队",
        )
        return
    try:
        cfg = get_config()
        task = next(
            (
                normalize_task(item)
                for item in cfg.get("monitor_tasks", []) or []
                if isinstance(item, dict) and str(item.get("name", "") or "") == str(task_name or "")
            ),
            None,
        )
    except Exception as exc:
        _best_effort_monitor_change_call(
            "Failed to close monitor change run after setup error",
            finish_monitor_run,
            run_id,
            status="failed",
            summary=str(exc),
        )
        await _best_effort_monitor_change_await(
            "Failed to release monitor change job after setup error",
            _finish_monitor_job,
            task_name,
            "monitor-change",
        )
        return
    if not task:
        _best_effort_monitor_change_call(
            "Failed to close missing monitor change run",
            finish_monitor_run,
            run_id,
            status="failed",
            summary="变更同步任务不存在",
        )
        await _best_effort_monitor_change_await(
            "Failed to write missing monitor task log",
            write_monitor_log,
            f"变更同步任务不存在: {task_name}",
            "error",
        )
        await _best_effort_monitor_change_await(
            "Failed to release missing monitor change job",
            _finish_monitor_job,
            task_name,
            "monitor-change",
        )
        return
    if normalize_task_type(task.get("task_type")) == MONITOR_TASK_TYPE_INBOX:
        # 兜底：接收夹任务不参与变更同步（正常路径不会走到这里）。
        _best_effort_monitor_change_call(
            "Failed to close inbox monitor change run",
            finish_monitor_run,
            run_id,
            status="cancelled",
            summary="接收夹不参与变更同步",
        )
        await _best_effort_monitor_change_await(
            "Failed to write inbox change rejection log",
            write_monitor_log,
            f"接收夹任务「{task_name}」不参与变更同步，已忽略",
            "warn",
        )
        await _best_effort_monitor_change_await(
            "Failed to release inbox monitor change job",
            _finish_monitor_job,
            task_name,
            "monitor-change",
        )
        return
    update_monitor_summary("准备同步变更", task_name)
    schedule_ui_state_push(0)
    try:
        await write_monitor_task_header(task, "change", payload)
        start_monitor_run(run_id, subject="文件变更", scope={"kind": "events"})
        await write_monitor_section("处理刮削变更")
        from .monitor_changes import normalize_monitor_event_ids, process_monitor_change_events

        raw_event_ids = payload.get("event_ids", []) if isinstance(payload, dict) else []
        event_ids = normalize_monitor_event_ids(raw_event_ids)
        result = await process_monitor_change_events(
            task_name,
            cfg=cfg,
            event_ids=event_ids,
            monitor_run_id=run_id,
        )
        parent_run_ids = [
            str(value or "").strip()
            for value in (result.get("monitor_run_ids", []) if isinstance(result.get("monitor_run_ids"), list) else [])
            if str(value or "").strip()
        ]
        if parent_run_ids:
            set_monitor_run_parent(run_id, parent_run_ids[0])
            for parent_run_id in parent_run_ids:
                link_monitor_runs(parent_run_id, run_id, relation="downstream")
        if (
            max(0, int(result.get("completed", 0) or 0))
            + max(0, int(result.get("failed", 0) or 0))
            + max(0, int(result.get("discarded", 0) or 0))
        ) <= 0:
            await write_monitor_log("无待处理变更，本轮跳过", "info")
            status_text = "变更同步完成"
            finish_monitor_run(run_id, status="no_change", summary="没有待处理变更")
            await _best_effort_monitor_change_await(
                "Failed to write empty monitor change footer",
                write_monitor_task_footer,
                task_name,
                status_text,
            )
            _best_effort_monitor_change_call(
                "Failed to update empty monitor change summary",
                update_monitor_summary,
                status_text,
                task_name,
            )
            return
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
        for detail in result.get("change_details", []) if isinstance(result.get("change_details"), list) else []:
            if not isinstance(detail, dict):
                continue
            normalized_detail = _monitor_run_change_detail(detail)
            if detail.get("kind") == "folder":
                record_monitor_run_event(
                    run_id,
                    category="remote",
                    operation=str(detail.get("operation", "change") or "change"),
                    status="completed",
                    title=str(detail.get("new_path") or detail.get("old_path") or "文件夹变更"),
                    detail=normalized_detail,
                )
                if int(detail.get("deleted", 0) or 0) or int(detail.get("generated", 0) or 0):
                    record_monitor_run_event(
                        run_id,
                        category="strm",
                        operation="sync",
                        status="completed",
                        title="STRM 同步",
                        detail={
                            "step": "STRM 同步",
                            "scope": str(detail.get("new_path") or detail.get("old_path") or ""),
                            "deleted": int(detail.get("deleted", 0) or 0),
                            "generated": int(detail.get("generated", 0) or 0),
                        },
                    )
            else:
                for item in detail.get("changes", []) if isinstance(detail.get("changes"), list) else []:
                    if isinstance(item, dict):
                        item_detail = _monitor_run_change_detail({"kind": "file", "changes": [item]})
                        record_monitor_run_event(
                            run_id,
                            category="strm",
                            operation=str(item.get("action", "change") or "change"),
                            status="completed",
                            title=os.path.basename(str(item.get("path", "") or "")),
                            detail=item_detail,
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
                record_monitor_run_event(
                    run_id,
                    category="remote",
                    operation="auto_organize",
                    status="failed" if "失败" in auto_message else ("partial" if "部分完成" in auto_message else "completed"),
                    title="自动整理",
                    detail={"summary": auto_message},
                )
            except Exception as exc:
                await write_monitor_log(f"自动整理失败: {exc}", "error")
                record_monitor_run_event(
                    run_id,
                    category="problem",
                    operation="auto_organize",
                    status="failed",
                    title="自动整理失败",
                    detail={"error": str(exc)},
                )
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
        if failed > 0:
            error_preview = [
                f"#{max(0, int(item.get('event_id', 0) or 0))}: {str(item.get('error', '') or '未知错误')}"
                for item in (result.get("errors", []) if isinstance(result.get("errors"), list) else [])[:3]
                if isinstance(item, dict)
            ]
            record_monitor_run_event(
                run_id,
                category="problem",
                operation="change_failed",
                status="failed",
                title=f"{failed} 条网盘变更处理失败",
                detail={
                    "failed": failed,
                    "error": "；".join(error_preview) or "详情见文本日志",
                },
            )
        if int(result.get("failed", 0) or 0) > 0:
            status_text = "变更同步部分失败"
        elif int(result.get("manual_required", 0) or 0) > 0:
            status_text = "变更同步待自动补扫" if auto_rescan_queued > 0 else "变更同步待手动监控"
        else:
            status_text = "变更同步完成"
        final_status = "partial" if failed or manual_required else ("no_change" if not generated and not deleted else "completed")
        finish_monitor_run(
            run_id,
            status=final_status,
            summary=build_monitor_change_run_summary(result),
            result={"completed": completed, "failed": failed, "discarded": discarded, "generated": generated, "deleted": deleted, "manual_required": manual_required},
        )
        await _best_effort_monitor_change_await(
            "Failed to write completed monitor change footer",
            write_monitor_task_footer,
            task_name,
            status_text,
        )
        _best_effort_monitor_change_call(
            "Failed to update completed monitor change summary",
            update_monitor_summary,
            status_text,
            task_name,
        )
    except asyncio.CancelledError:
        _best_effort_monitor_change_call(
            "Failed to close cancelled monitor change run",
            finish_monitor_run,
            run_id,
            status="cancelled",
            summary="变更同步已中断",
        )
        await _best_effort_monitor_change_await(
            "Failed to write cancelled monitor change footer",
            write_monitor_task_footer,
            task_name,
            "变更同步已中断",
        )
        _best_effort_monitor_change_call(
            "Failed to update cancelled monitor change summary",
            update_monitor_summary,
            "变更同步中断",
            task_name,
        )
    except Exception as exc:
        _best_effort_monitor_change_call(
            "Failed to close failed monitor change run",
            finish_monitor_run,
            run_id,
            status="failed",
            summary=str(exc),
        )
        _best_effort_monitor_change_call(
            "Failed to record monitor change error event",
            record_monitor_run_event,
            run_id,
            category="problem",
            operation="change",
            status="failed",
            title="变更同步失败",
            detail={"error": str(exc)},
        )
        await _best_effort_monitor_change_await(
            "Failed to write monitor change error log",
            write_monitor_log,
            f"变更同步失败: {exc}",
            "error",
        )
        await _best_effort_monitor_change_await(
            "Failed to write monitor change error footer",
            write_monitor_task_footer,
            task_name,
            "变更同步失败",
        )
        _best_effort_monitor_change_call(
            "Failed to update failed monitor change summary",
            update_monitor_summary,
            "变更同步失败",
            str(exc),
        )
    finally:
        try:
            detail = get_monitor_run_detail(run_id)
            current_status = str((detail.get("run") or {}).get("status", "") or "")
            if current_status in {"queued", "running", "waiting"}:
                finish_monitor_run(run_id, status="failed", summary="变更同步异常结束")
        except Exception:
            logging.exception("Failed to finalize active monitor change run")
        await _best_effort_monitor_change_await(
            "Failed to release monitor change job",
            _finish_monitor_job,
            task_name,
            "monitor-change",
        )


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
            run_id=str(next_job.get("run_id", "") or ""),
            label="monitor-change-job",
        )
    else:
        submit_background(
            run_monitor_task,
            next_job["task_name"],
            trigger=next_job.get("trigger", "queued"),
            payload=next_job.get("payload"),
            merged_count=max(0, int(next_job.get("merge_count", 0) or 0)),
            run_id=str(next_job.get("run_id", "") or ""),
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
        # Do not silently truncate a user-selected scope.  The worker already
        # handles multiple roots and the run record makes the full range visible.
        normalized["savepaths"] = savepaths

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
    # A request with no concrete path means the whole task.  It must never be
    # narrowed by a later partial refresh while the task is waiting in queue.
    existing_is_task_scope = not _monitor_savepath_scopes(existing_payload)
    incoming_is_task_scope = not _monitor_savepath_scopes(incoming_payload)
    if existing_is_task_scope or incoming_is_task_scope:
        merged_payload: Dict[str, Any] = {"mode": "change"} if merged_mode == "change" else {}
    elif existing_has_multi or incoming_has_multi:
        merged_savepaths: List[str] = []
        for scope in _monitor_savepath_scopes(existing_payload) + _monitor_savepath_scopes(incoming_payload):
            scope_rel = normalize_relative_path(scope.lstrip("/"))
            if scope_rel and scope_rel not in merged_savepaths:
                merged_savepaths.append(scope_rel)
        merged_payload: Dict[str, Any] = {"mode": "change"} if merged_mode == "change" else {}
        if merged_savepaths:
            merged_payload["savepaths"] = merged_savepaths
            provider = str(
                existing_payload.get("provider", "") or incoming_payload.get("provider", "") or ""
            ).strip()
            if provider:
                merged_payload["provider"] = provider
    else:
        merged_payload = {"mode": "change"} if merged_mode == "change" else {}
        if existing_scope == incoming_scope:
            merged_payload["savepath"] = normalize_relative_path(existing_scope.lstrip("/"))
        elif is_subpath(existing_scope, incoming_scope):
            merged_payload["savepath"] = normalize_relative_path(incoming_scope.lstrip("/"))
        elif is_subpath(incoming_scope, existing_scope):
            merged_payload["savepath"] = normalize_relative_path(existing_scope.lstrip("/"))
        else:
            # Different roots remain different roots.  Falling back to a full
            # scan hides what happened and was the original range-loss bug.
            merged_payload["savepaths"] = [
                normalize_relative_path(existing_scope.lstrip("/")),
                normalize_relative_path(incoming_scope.lstrip("/")),
            ]

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


def queue_monitor_job(
    task_name: str,
    trigger: str,
    payload: Optional[Dict[str, Any]] = None,
    *,
    force_new: bool = False,
    return_details: bool = False,
) -> Any:
    """Queue a monitor run, optionally keeping a retry separate from merged work."""
    global _monitor_dispatch_pending
    normalized_task_name = str(task_name or "").strip()
    if not normalized_task_name:
        schedule_ui_state_push(0)
        return "queued"

    normalized_trigger = str(trigger or "").strip().lower() or "manual"
    try:
        active_cfg = get_config()
        matched_task = next(
            (task for task in active_cfg.get("monitor_tasks", []) or [] if task.get("name") == normalized_task_name),
            None,
        )
    except Exception:
        matched_task = None
    if matched_task:
        if normalize_task_type(matched_task.get("task_type")) == MONITOR_TASK_TYPE_INBOX:
            # 接收夹不是扫描目标：整理由接收夹流程负责，任何扫描触发都直接忽略。
            schedule_ui_state_push(0)
            return "inbox"
        if normalized_trigger != "manual" and matched_task.get("enabled") is False:
            # 「停用」= 不自动跑：定时 / 变更同步 / 资源导入完成 / webhook 都不入队，手动 start 仍可用。
            schedule_ui_state_push(0)
            return "disabled"
    normalized_payload = _normalize_monitor_queue_payload(payload)
    mode = str(normalized_payload.get("mode", "scan") or "scan")
    source_ref = str(
        (payload or {}).get("source_ref", "")
        or (payload or {}).get("resource_job_id", "")
        or (payload or {}).get("subscription_run_id", "")
    ).strip()
    parent_run_id = str((payload or {}).get("parent_run_id", "") or "").strip()
    retry_of_run_id = str((payload or {}).get("retry_of_run_id", "") or "").strip()
    initial_scope = _monitor_run_scope(normalized_payload)

    should_dispatch = False
    queued_run_id = ""
    with monitor_queue_lock:
        matched_item: Optional[Dict[str, Any]] = None
        if not force_new:
            for queued_item in monitor_queue:
                if str(queued_item.get("task_name", "")).strip() != normalized_task_name:
                    continue
                if str(queued_item.get("mode", "scan") or "scan") != mode:
                    continue
                matched_item = queued_item
                break
        if matched_item is not None:
            matched_item["payload"] = _merge_monitor_queue_payload(matched_item.get("payload"), normalized_payload)
            matched_run_id = str(matched_item.get("run_id", "") or "").strip()
            if matched_run_id:
                add_monitor_run_source(matched_run_id, normalized_trigger, source_ref)
                merged_scope = _monitor_run_scope(matched_item["payload"])
                update_monitor_run(
                    matched_run_id,
                    subject=_monitor_run_subject(normalized_task_name, merged_scope.get("paths")),
                    result={"scope": merged_scope},
                )
            queued_run_id = matched_run_id
            matched_item["mode"] = mode
            matched_item["trigger"] = _pick_monitor_trigger(matched_item.get("trigger", "queued"), normalized_trigger)
            matched_item["merge_count"] = max(0, int(matched_item.get("merge_count", 0) or 0)) + 1
        else:
            queued_run_id = create_monitor_run(
                run_kind="change" if mode == "change" else "scan",
                task_name=normalized_task_name,
                source="retry" if retry_of_run_id else normalized_trigger,
                scope=initial_scope,
                subject=_monitor_run_subject(normalized_task_name, initial_scope.get("paths")),
                parent_run_id=parent_run_id,
                source_ref=source_ref,
                task_snapshot=matched_task if isinstance(matched_task, dict) else {},
            )
            if retry_of_run_id:
                link_monitor_runs(queued_run_id, retry_of_run_id, relation="retry_of")
                record_monitor_run_event(
                    queued_run_id,
                    category="process",
                    operation="retry",
                    status="queued",
                    title="重试失败范围",
                    detail={"retry_of_run_id": retry_of_run_id},
                )
            monitor_queue.append(
                {
                    "task_name": normalized_task_name,
                    "trigger": normalized_trigger,
                    "payload": normalized_payload,
                    "mode": mode,
                    "run_id": queued_run_id,
                    "merge_count": 0,
                }
            )
        if not monitor_status["running"] and not _monitor_dispatch_pending:
            _monitor_dispatch_pending = True
            should_dispatch = True
        monitor_status["queued"] = [item["task_name"] for item in monitor_queue]
    schedule_ui_state_push(0)
    status = "queued"
    if should_dispatch:
        submit_background(start_next_monitor_job, label="monitor-next")
        status = "started"
    if return_details:
        return {"status": status, "run_id": queued_run_id}
    return status


def cancel_queued_monitor_run(run_id: str) -> Dict[str, Any]:
    """Cancel only a run that is still present in the monitor queue."""
    target_run_id = str(run_id or "").strip()
    if not target_run_id:
        return {"ok": False, "msg": "缺少运行记录 ID"}

    removed: Optional[Dict[str, Any]] = None
    with monitor_queue_lock:
        for index, item in enumerate(monitor_queue):
            if str(item.get("run_id", "") or "").strip() == target_run_id:
                removed = monitor_queue.pop(index)
                break
        monitor_status["queued"] = [item["task_name"] for item in monitor_queue]

    if removed is None:
        detail = get_monitor_run_detail(target_run_id)
        if not detail:
            return {"ok": False, "msg": "运行记录不存在"}
        status = str((detail.get("run") or {}).get("status", "") or "")
        if status != "queued":
            return {"ok": False, "msg": "该运行已经开始或已结束，不能取消未开始步骤"}
        return {"ok": False, "msg": "该运行正在派发，不能取消未开始步骤"}

    detail = get_monitor_run_detail(target_run_id)
    previous_result = dict((detail.get("run") or {}).get("result") or {}) if detail else {}
    previous_result["cancelled_before_start"] = True
    finish_monitor_run(
        target_run_id,
        status="cancelled",
        summary="已取消未开始的监控步骤",
        result=previous_result,
    )
    schedule_ui_state_push(0)
    return {
        "ok": True,
        "status": "cancelled",
        "task_name": str(removed.get("task_name", "") or ""),
        "run_id": target_run_id,
    }


def retry_monitor_run(run_id: str) -> Dict[str, Any]:
    """Retry the persisted range of a failed or partially completed scan."""
    target_run_id = str(run_id or "").strip()
    detail = get_monitor_run_detail(target_run_id)
    run = detail.get("run") if isinstance(detail, dict) else None
    if not isinstance(run, dict):
        return {"ok": False, "msg": "运行记录不存在"}
    if str(run.get("status", "") or "") not in {"failed", "partial"}:
        return {"ok": False, "msg": "只有失败或部分完成的运行可以重试"}
    if str(run.get("run_kind", "") or "") != "scan":
        return {"ok": False, "msg": "此记录没有可重试的失败范围"}

    task_name = str(run.get("task_name", "") or "").strip()
    cfg = get_config()
    task = next(
        (
            item
            for item in cfg.get("monitor_tasks", []) or []
            if isinstance(item, dict) and str(item.get("name", "") or "").strip() == task_name
        ),
        None,
    )
    if not task or normalize_task_type(task.get("task_type")) == MONITOR_TASK_TYPE_INBOX:
        return {"ok": False, "msg": "原监控任务已不存在或不支持重试"}

    scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    payload: Dict[str, Any] = {"source_ref": target_run_id, "retry_of_run_id": target_run_id}
    if str(scope.get("kind", "") or "") == "paths":
        paths = []
        for value in scope.get("paths", []) if isinstance(scope.get("paths"), list) else []:
            path = normalize_relative_path(str(value or "").strip())
            if path and path not in paths:
                paths.append(path)
        if not paths:
            return {"ok": False, "msg": "此记录没有可重试的失败范围"}
        payload["savepaths"] = paths
    elif str(scope.get("kind", "") or "") != "task":
        return {"ok": False, "msg": "此记录没有可重试的失败范围"}

    queued = queue_monitor_job(
        task_name,
        "manual",
        payload,
        force_new=True,
        return_details=True,
    )
    if not isinstance(queued, dict) or not str(queued.get("run_id", "") or "").strip():
        return {"ok": False, "msg": "重试任务未能加入队列"}
    return {"ok": True, **queued, "retry_of_run_id": target_run_id}


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
