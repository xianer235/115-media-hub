"""接收夹快捷导入：整理（与监控自动刮削共用同一流程）+ 按类型分发到监控目录。

最小改动接入现有工作流：

- 接收夹就是 ``monitor_tasks`` 里的一个 ``task_type='inbox'`` 任务，和扫描任务共用同一套
  任务 / 路径 / webhook 口径（旧版的 ``quick_import_enabled`` / ``quick_import_inbox_path``
  会在 ``normalize_config`` 里迁移成这个任务）；
- 分发目标写在该任务的 ``distribute_targets``（movie / tv → 扫描任务名）；
- 整理选项一律取自目标监控任务的 ``auto_scrape_options``，避免两边规则不一致来回改；
- 搬运带 ``scraper-job:`` 来源标记，复用监控侧既有守卫——搬到监控目录后只生成 STRM，
  不会再被目标监控任务自动刮削一遍，同一条目一生只整理一次。
"""

import logging
import threading
import time
from typing import Any, Dict, List, Optional, Set

from ..core import *  # noqa: F401,F403
from ..db import now_text, retry_sqlite_locked
from . import scraper as scraper_service
from .scraper import (
    _normalize_scraper_batch_preferences,
    build_scraper_plan_for_batch,
    create_scraper_job_from_plan,
    identify_scraper_batch_entries,
    resolve_scraper_dest_folder_id,
    submit_scraper_job,
)
from .monitor_runs import create_run as create_monitor_run
from .monitor_runs import finish_run as finish_monitor_run
from .monitor_runs import latest_run_progress as latest_monitor_run_progress
from .monitor_runs import record_event as record_monitor_run_event
from .monitor_runs import start_run as start_monitor_run
from .monitor_runs import update_run as update_monitor_run


QUICK_IMPORT_PROVIDER = "115"
QUICK_IMPORT_TARGET_KEYS = ("movie", "tv")
QUICK_IMPORT_TARGET_LABELS = {"movie": "电影", "tv": "电视剧"}
QUICK_IMPORT_SOURCE_ACTION_PREFIX = "quick-import"
# 同名文件夹合并的最大层级：媒体文件夹只有 片名 (年份)/ 或 片名 (年份)/Season 01/ 两级，
# 留一点余量防止异常结构把合并请求打成无限递归。
QUICK_IMPORT_MERGE_MAX_DEPTH = 3
# 合并前只列一次目标文件夹：一页最多 1000 条，剧集/电影文件夹远小于这个量级。
QUICK_IMPORT_MERGE_LIST_LIMIT = 1000
QUICK_IMPORT_JOB_WAIT_SECONDS = max(
    30,
    int(os.environ.get("QUICK_IMPORT_JOB_WAIT_SECONDS", 900) or 900),
)
# 并发触发（多个导入同时完成）时排队而不是直接跳过，避免漏整理。
QUICK_IMPORT_LOCK_WAIT_SECONDS = max(
    30,
    int(os.environ.get("QUICK_IMPORT_LOCK_WAIT_SECONDS", 300) or 300),
)

_QUICK_IMPORT_RUN_LOCK = threading.Lock()
# 中断标记：接收夹整理是长任务，用户点「中断」后在下一条目开始前生效（已搬完的不会回滚）。
_QUICK_IMPORT_CANCEL = threading.Event()
# 触发协调：整理正在执行时把后续触发记成「还需再跑一轮」，由工作线程在本轮结束后
# 自动接着跑，任何触发都不会被丢掉。
_INBOX_TRIGGER_LOCK = threading.Lock()
_INBOX_TRIGGER_STATE: Dict[str, Any] = {
    "worker": None,
    "pending": False,
    "trigger": "",
    "source_ref": "",
}
_INBOX_TRIGGER_PRIORITY = {"manual": 5, "cron": 4, "offline": 3, "import": 2, "test": 1}


def request_quick_import_cancel() -> bool:
    """请求中断当前接收夹整理；没有在跑时返回 False。"""
    if not _QUICK_IMPORT_RUN_LOCK.locked():
        return False
    with _INBOX_TRIGGER_LOCK:
        # 中断意味着用户不想再排队了：取消同时清掉「再跑一轮」预约。
        _INBOX_TRIGGER_STATE["pending"] = False
    _QUICK_IMPORT_CANCEL.set()
    return True


def _inbox_trigger_priority(trigger: str) -> int:
    return _INBOX_TRIGGER_PRIORITY.get(str(trigger or "").strip().lower(), 0)


def notify_quick_import(trigger: str = "queued", *, source_ref: str = "") -> Dict[str, Any]:
    """登记一次接收夹整理请求；正在执行时预约下一轮，永不静默跳过。"""
    normalized_trigger = str(trigger or "").strip().lower() or "queued"
    normalized_ref = str(source_ref or "").strip()
    with _INBOX_TRIGGER_LOCK:
        worker = _INBOX_TRIGGER_STATE.get("worker")
        if isinstance(worker, threading.Thread) and worker.is_alive():
            current = str(_INBOX_TRIGGER_STATE.get("trigger", "") or "")
            if _inbox_trigger_priority(normalized_trigger) >= _inbox_trigger_priority(current):
                _INBOX_TRIGGER_STATE["trigger"] = normalized_trigger
                _INBOX_TRIGGER_STATE["source_ref"] = normalized_ref
            _INBOX_TRIGGER_STATE["pending"] = True
            return {
                "ok": True,
                "started": False,
                "queued": True,
                "running": True,
                "summary": "已有接收夹整理在执行，已安排再跑一轮",
            }
        _INBOX_TRIGGER_STATE["pending"] = False
        _INBOX_TRIGGER_STATE["trigger"] = normalized_trigger
        _INBOX_TRIGGER_STATE["source_ref"] = normalized_ref
        worker = threading.Thread(
            target=_inbox_worker_loop,
            args=(normalized_trigger, normalized_ref),
            name="inbox-quick-import",
            daemon=True,
        )
        _INBOX_TRIGGER_STATE["worker"] = worker
        worker.start()
    return {
        "ok": True,
        "started": True,
        "queued": True,
        "running": False,
        "summary": "已开始接收夹整理",
    }


def _inbox_worker_loop(trigger: str, source_ref: str) -> None:
    current_trigger, current_ref = trigger, source_ref
    while True:
        try:
            result = run_quick_import(current_trigger, source_ref=current_ref, wait_for_lock=True)
            if isinstance(result, dict) and result.get("skipped"):
                # 极端情况下锁超时：不丢请求，稍后重试这一轮。
                with _INBOX_TRIGGER_LOCK:
                    _INBOX_TRIGGER_STATE["pending"] = True
                time.sleep(5)
        except Exception:
            logging.exception("接收夹整理执行失败")
        with _INBOX_TRIGGER_LOCK:
            if not _INBOX_TRIGGER_STATE.get("pending"):
                _INBOX_TRIGGER_STATE["worker"] = None
                _INBOX_TRIGGER_STATE["trigger"] = ""
                _INBOX_TRIGGER_STATE["source_ref"] = ""
                return
            _INBOX_TRIGGER_STATE["pending"] = False
            current_trigger = str(_INBOX_TRIGGER_STATE.get("trigger", "") or "queued")
            current_ref = str(_INBOX_TRIGGER_STATE.get("source_ref", "") or "")


def pending_quick_import_rerun() -> bool:
    """是否已经预约了下一轮整理（接收夹卡片展示用）。"""
    with _INBOX_TRIGGER_LOCK:
        return bool(_INBOX_TRIGGER_STATE.get("pending"))


def _inbox_remote_path(cfg: Dict[str, Any]) -> str:
    task = get_inbox_task(cfg)
    remote = normalize_remote_path(str(task.get("scan_path", "") or "").strip())
    return "" if remote == "/" else remote


def _inbox_rel_path(cfg: Dict[str, Any]) -> str:
    remote = _inbox_remote_path(cfg)
    if not remote:
        return ""
    try:
        _provider, relative = resolve_provider_relative_path(
            cfg,
            remote,
            expected_provider=QUICK_IMPORT_PROVIDER,
        )
    except Exception:
        return ""
    return normalize_relative_path(relative)


def _task_rel_path(cfg: Dict[str, Any], scan_path: Any) -> str:
    remote = normalize_remote_path(str(scan_path or "").strip())
    if not remote:
        return ""
    try:
        _provider, relative = resolve_provider_relative_path(
            cfg,
            remote,
            expected_provider=QUICK_IMPORT_PROVIDER,
        )
    except Exception:
        return normalize_relative_path(remote.lstrip("/"))
    return normalize_relative_path(relative)


def build_quick_import_config(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """接收夹配置：接收夹本身是 ``monitor_tasks`` 里的一个 inbox 任务，分发目标写在它的
    ``distribute_targets`` 上，和扫描任务共用同一套任务/路径/webhook 口径。"""
    active_cfg = cfg if isinstance(cfg, dict) else get_config()
    inbox = get_inbox_task(active_cfg)
    targets: Dict[str, Dict[str, Any]] = {key: {} for key in QUICK_IMPORT_TARGET_KEYS}
    tasks_by_name = {
        str(task.get("name", "") or "").strip(): task
        for task in active_cfg.get("monitor_tasks", []) or []
        if isinstance(task, dict) and str(task.get("name", "") or "").strip()
    }
    distribute_targets = (
        inbox.get("distribute_targets") if isinstance(inbox.get("distribute_targets"), dict) else {}
    )
    for key in QUICK_IMPORT_TARGET_KEYS:
        task = tasks_by_name.get(str(distribute_targets.get(key, "") or "").strip())
        if not task:
            continue
        scan_path = normalize_remote_path(str(task.get("scan_path", "") or "").strip())
        rel_path = _task_rel_path(active_cfg, scan_path)
        if not scan_path or not rel_path:
            continue
        targets[key] = {
            "task_name": str(task.get("name", "") or "").strip(),
            "scan_path": scan_path,
            "scan_rel": rel_path,
            "auto_scrape_options": (
                task.get("auto_scrape_options") if isinstance(task.get("auto_scrape_options"), dict) else {}
            ),
        }
    return {
        "task_name": str(inbox.get("name", "") or "").strip(),
        "enabled": bool(inbox.get("enabled")) if inbox else False,
        "inbox_path": _inbox_remote_path(active_cfg),
        "inbox_rel": _inbox_rel_path(active_cfg),
        "targets": targets,
    }


def is_quick_import_savepath(cfg: Dict[str, Any], savepath: Any) -> bool:
    """导入落点是否落在接收夹内（savepath 是网盘相对路径，如 ``接收/xxx``）。"""
    conf = build_quick_import_config(cfg)
    if not conf["enabled"]:
        return False
    inbox_rel = str(conf.get("inbox_rel", "") or "").strip()
    if not inbox_rel:
        return False
    relative = normalize_relative_path(str(savepath or "").strip())
    if not relative:
        return False
    return relative == inbox_rel or relative.startswith(inbox_rel + "/")


def validate_quick_import_config(cfg: Optional[Dict[str, Any]] = None) -> Optional[str]:
    active_cfg = cfg if isinstance(cfg, dict) else get_config()
    conf = build_quick_import_config(active_cfg)
    if not conf["task_name"]:
        return "没有找到内置的接收夹任务，请重启服务或检查配置（接收夹是内置固定任务，不需要新增）"
    if not conf["enabled"]:
        return f"接收夹任务「{conf['task_name']}」未启用"
    if not conf["inbox_path"]:
        return f"请先给接收夹任务「{conf['task_name']}」选择文件夹"
    inbox_rel = str(conf.get("inbox_rel", "") or "").strip()
    if not inbox_rel:
        return "接收文件夹必须位于 115 网盘前缀下"
    if not any(conf["targets"].get(key) for key in QUICK_IMPORT_TARGET_KEYS):
        return "还没有在接收夹任务里指定「电影 / 电视剧」分发目标"
    for task in active_cfg.get("monitor_tasks", []) or []:
        if not isinstance(task, dict):
            continue
        if normalize_task_type(task.get("task_type")) != MONITOR_TASK_TYPE_SCAN:
            continue
        scan_rel = _task_rel_path(active_cfg, task.get("scan_path", ""))
        if not scan_rel:
            continue
        overlap = (
            scan_rel == inbox_rel
            or scan_rel.startswith(inbox_rel + "/")
            or inbox_rel.startswith(scan_rel + "/")
        )
        if overlap:
            name = str(task.get("name", "") or "").strip() or "--"
            return f"接收文件夹不能与监控任务「{name}」的扫描路径（{scan_rel}）重叠"
    return None


def _target_scrape_options(target: Dict[str, Any]) -> Dict[str, Any]:
    options: Dict[str, Any] = {"title_language": "zh", "delete_ad_files": False}
    raw_options = target.get("auto_scrape_options") if isinstance(target, dict) else {}
    if isinstance(raw_options, dict) and raw_options:
        options.update(_normalize_scraper_batch_preferences(raw_options))
    return options


def _list_inbox_children(base_cid: str) -> List[Dict[str, Any]]:
    payload = scraper_service.list_scraper_entries(QUICK_IMPORT_PROVIDER, base_cid, True)
    entries = payload.get("entries") if isinstance(payload, dict) else []
    return [entry for entry in (entries or []) if isinstance(entry, dict)]


def _resolve_entry_after_organize(
    base_cid: str,
    plan_summary: Dict[str, Any],
    original_entry: Dict[str, Any],
) -> Dict[str, Any]:
    """整理后重新定位条目：文件夹按 ID 找；散文件按计划生成的片名文件夹兜底。"""
    try:
        children = _list_inbox_children(base_cid)
    except Exception:
        return {}
    original_id = str(original_entry.get("id", "") or "").strip()
    if original_id:
        for entry in children:
            if str(entry.get("id", "") or "").strip() == original_id:
                return entry
    title = str((plan_summary or {}).get("title", "") or "").strip()
    year = str((plan_summary or {}).get("year", "") or "").strip()
    if title:
        for entry in children:
            if not bool(entry.get("is_dir", False)):
                continue
            name = str(entry.get("name", "") or "").strip()
            if not name:
                continue
            if name == title or name.startswith(f"{title} (") or name.startswith(f"{title} ["):
                return entry
    return {}


def _insert_quick_import_run(trigger: str, inbox_path: str, started_at: str) -> int:
    ensure_db()

    def write() -> int:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO quick_import_runs (trigger, status, inbox_path, started_at)
                VALUES (?, ?, ?, ?)
                """,
                (str(trigger or "")[:40], "running", str(inbox_path or ""), str(started_at or "")),
            )
            conn.commit()
            return int(cursor.lastrowid or 0)

    return retry_sqlite_locked(write)


def _finish_quick_import_run(
    run_id: int,
    status: str,
    moved_count: int,
    left_count: int,
    summary: str,
    detail: Dict[str, Any],
) -> None:
    if run_id <= 0:
        return
    ensure_db()

    def write() -> None:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE quick_import_runs
                SET status = ?, finished_at = ?, moved_count = ?, left_count = ?, summary = ?, detail_json = ?
                WHERE id = ?
                """,
                (
                    str(status or ""),
                    now_text(),
                    max(0, int(moved_count or 0)),
                    max(0, int(left_count or 0)),
                    str(summary or "")[:500],
                    safe_json_dumps(detail or {}),
                    int(run_id),
                ),
            )
            conn.commit()

    retry_sqlite_locked(write)


def list_quick_import_runs(limit: int = 20) -> List[Dict[str, Any]]:
    normalized_limit = max(1, min(200, int(limit or 20)))
    ensure_db()

    def load() -> List[Dict[str, Any]]:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM quick_import_runs ORDER BY id DESC LIMIT ?",
                (normalized_limit,),
            )
            columns = [item[0] for item in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    return retry_sqlite_locked(load)


def list_inbox_recent_jobs(inbox_rel: str, limit: int = 3) -> List[Dict[str, Any]]:
    """接收夹里最近落进来的离线导入任务（磁力 / 分享导入 finish 前都算“最近接收”）。"""
    prefix = normalize_relative_path(str(inbox_rel or "").strip())
    if not prefix:
        return []
    page_limit = max(1, min(int(limit or 3), 20))
    ensure_db()

    def load() -> List[Dict[str, Any]]:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM resource_jobs
                WHERE savepath = ? OR savepath LIKE ?
                ORDER BY id DESC LIMIT ?
                """,
                (prefix, f"{prefix}/%", page_limit),
            )
            return [serialize_resource_job_row(row) for row in cursor.fetchall()]

    return retry_sqlite_locked(load)


def count_inbox_recent_jobs(inbox_rel: str, hours: int = 24) -> int:
    prefix = normalize_relative_path(str(inbox_rel or "").strip())
    if not prefix:
        return 0
    window_hours = max(1, min(int(hours or 24), 24 * 30))
    cutoff = (datetime.now() - timedelta(hours=window_hours)).isoformat(timespec="seconds")
    ensure_db()

    def load() -> int:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) FROM resource_jobs
                WHERE (savepath = ? OR savepath LIKE ?) AND created_at >= ?
                """,
                (prefix, f"{prefix}/%", cutoff),
            )
            row = cursor.fetchone()
            return int(row[0] or 0) if row else 0

    return int(retry_sqlite_locked(load) or 0)


def get_quick_import_status() -> Dict[str, Any]:
    cfg = get_config()
    conf = build_quick_import_config(cfg)
    inbox_rel = str(conf.get("inbox_rel", "") or "").strip()
    runs = list_quick_import_runs(1)
    latest = runs[0] if runs else {}
    detail = safe_json_loads(latest.get("detail_json", "{}"), {}) if latest else {}
    active_run: Dict[str, Any] = {}
    if str(conf.get("task_name", "") or "").strip():
        try:
            active_run = latest_monitor_run_progress(run_kind="inbox", task_name=str(conf["task_name"]))
        except Exception:
            active_run = {}
    return {
        "task_name": conf["task_name"],
        "task_path": conf["inbox_path"],
        "enabled": conf["enabled"],
        "inbox_path": conf["inbox_path"],
        "config_error": validate_quick_import_config(cfg) or "",
        "targets": {
            key: {
                "task_name": (conf["targets"].get(key) or {}).get("task_name", ""),
                "scan_path": (conf["targets"].get(key) or {}).get("scan_path", ""),
            }
            for key in QUICK_IMPORT_TARGET_KEYS
        },
        "running": _QUICK_IMPORT_RUN_LOCK.locked(),
        "cancelling": _QUICK_IMPORT_RUN_LOCK.locked() and _QUICK_IMPORT_CANCEL.is_set(),
        "pending_rerun": pending_quick_import_rerun(),
        "active_run": active_run,
        "latest": latest,
        "latest_detail": detail,
        "recent_jobs": list_inbox_recent_jobs(inbox_rel, 3),
        "recent_job_count_24h": count_inbox_recent_jobs(inbox_rel, 24),
    }


def _left_reason_from_result(result: Dict[str, Any]) -> str:
    if not isinstance(result, dict) or not result:
        return "未形成可识别条目"
    if str(result.get("ai_error") or "").strip():
        return f"AI 识别失败：{str(result.get('ai_error')).strip()[:120]}"
    low_confidence = max(0, parse_int(result.get("ai_low_confidence", 0), 0))
    if low_confidence > 0:
        return f"AI 置信度不足（{low_confidence}）"
    status = str(result.get("status") or "").strip()
    if status == "suggest":
        return "TMDB 建议但未达自动匹配阈值"
    if status == "manual":
        return "未匹配到 TMDB 条目"
    return "未达到自动整理条件"


def _quick_import_source_action(job_id: int, monitor_run_id: str = "") -> str:
    # The existing reconciliation pipeline consumes this value.  Keep it
    # stable and persist the lifecycle relation in monitor_run_id instead.
    return f"scraper-job:{max(0, int(job_id or 0))}:{QUICK_IMPORT_SOURCE_ACTION_PREFIX}"


def _folder_children_payload(folder_id: str, folder_rel: str) -> List[Dict[str, Any]]:
    """列出整理结果文件夹的直接子项，并补上完整挂载路径（监控同步事件要用）。"""
    payload = scraper_service.list_scraper_entries(QUICK_IMPORT_PROVIDER, folder_id, True)
    children = payload.get("entries") if isinstance(payload, dict) else []
    result: List[Dict[str, Any]] = []
    for child in children or []:
        if not isinstance(child, dict):
            continue
        name = str(child.get("name", "") or "").strip()
        entry_id = str(child.get("id", "") or "").strip()
        if not name or not entry_id:
            continue
        item = dict(child)
        item["parent_id"] = folder_id
        item["parent_path"] = folder_rel
        item["path"] = normalize_relative_path(join_relative_path(folder_rel, name))
        result.append(item)
    return result


def _folder_contains_files(
    folder_id: str,
    folder_rel: str,
    *,
    depth: int = 0,
    max_depth: int = 3,
) -> bool:
    """目录子树里是否还有文件；用来识别整理后残留的空壳目录。

    读不到或层级过深时返回 True（保守：宁可留着也不误删有内容的目录）。
    """
    normalized_id = str(folder_id or "").strip()
    if not normalized_id or depth > max_depth:
        return True
    try:
        children = _folder_children_payload(normalized_id, folder_rel)
    except Exception:
        return True
    for child in children:
        if bool(child.get("is_dir")):
            if _folder_contains_files(
                str(child.get("id", "") or ""),
                str(child.get("path", "") or ""),
                depth=depth + 1,
                max_depth=max_depth,
            ):
                return True
        else:
            return True
    return False


def _retry_inbox_cleanup(
    leftovers: List[Dict[str, Any]],
    *,
    monitor_run_id: str,
) -> List[Dict[str, Any]]:
    """全部搬运结束后再清一次接收夹残留：清掉的记过程事件，仍残留的返回给调用方。

    只自动清空壳目录；目录里还有内容时保留，交给下一轮识别。
    """
    remaining: List[Dict[str, Any]] = []
    for leftover in leftovers if isinstance(leftovers, list) else []:
        if not isinstance(leftover, dict):
            continue
        entry_id = str(leftover.get("id", "") or "").strip()
        parent_id = str(leftover.get("parent_id", "") or "").strip()
        path = str(leftover.get("path", "") or "")
        name = str(leftover.get("name", "") or "")
        if not entry_id:
            remaining.append({**leftover, "reason": "缺少目录 ID，无法自动清理"})
            continue
        if _folder_contains_files(entry_id, path):
            remaining.append({**leftover, "reason": "目录内仍有内容，未自动清理"})
            continue
        try:
            scraper_service.delete_scraper_entries(
                QUICK_IMPORT_PROVIDER,
                [entry_id],
                parent_id=parent_id,
                entries=[{"id": entry_id, "name": name, "is_dir": True, "path": path, "parent_id": parent_id}],
            )
        except Exception as exc:
            remaining.append({**leftover, "reason": str(exc)[:120]})
            continue
        record_monitor_run_event(
            monitor_run_id,
            category="process",
            operation="cleanup",
            status="completed",
            title=name or path or entry_id,
            detail={"path": path, "reason": "接收夹空目录已清理"},
        )
    return remaining


def _folder_entry_names(folder_id: str, cache: Dict[str, Set[str]]) -> Set[str]:
    """目标文件夹里已有的条目名（一个文件夹只列一次，合并时用来挡同名文件）。"""
    normalized_id = str(folder_id or "").strip()
    if not normalized_id:
        return set()
    if normalized_id not in cache:
        payload = scraper_service.list_scraper_entries(
            QUICK_IMPORT_PROVIDER,
            normalized_id,
            True,
            limit=QUICK_IMPORT_MERGE_LIST_LIMIT,
        )
        entries = payload.get("entries") if isinstance(payload, dict) else []
        cache[normalized_id] = {
            str(entry.get("name", "") or "").strip()
            for entry in (entries or [])
            if isinstance(entry, dict) and str(entry.get("name", "") or "").strip()
        }
    return cache[normalized_id]


def _move_entries_into_folder(
    entries: List[Dict[str, Any]],
    *,
    source_cid: str,
    target_cid: str,
    target_rel: str,
    job_id: int,
    monitor_run_id: str = "",
) -> Dict[str, Any]:
    entry_ids = [str(item.get("id", "") or "").strip() for item in entries if str(item.get("id", "") or "").strip()]
    if not entry_ids:
        return {"monitor_sync": {"event_count": 0}}
    return scraper_service.move_scraper_entries(
        QUICK_IMPORT_PROVIDER,
        entry_ids,
        target_cid,
        source_cid=source_cid,
        entries=entries,
        target_parent_path=target_rel,
        source_action=_quick_import_source_action(job_id, monitor_run_id),
        monitor_run_id=monitor_run_id,
    )


def _merge_organized_folder_into_existing(
    source_folder: Dict[str, Any],
    source_rel: str,
    target_folder: Dict[str, Any],
    target_rel: str,
    *,
    job_id: int,
    monitor_run_id: str = "",
    name_cache: Dict[str, Set[str]],
    depth: int = 0,
) -> Dict[str, Any]:
    """把整理结果文件夹的内容并入目标监控目录里已有的同名文件夹。

    媒体文件夹层级很浅（``片名 (年份)/`` 或 ``片名 (年份)/Season 01/``），按同层递归合并：
    子文件夹在目标里已有同名目录就继续并入那个目录，否则整体搬过去；文件直接搬进目标文件夹。
    目标里已经存在同名文件时跳过并记录，避免 115 自动改出 ``xxx(1).mkv`` 这类重复文件。
    """
    if depth > QUICK_IMPORT_MERGE_MAX_DEPTH:
        raise RuntimeError("目标文件夹层级过深，已停止合并")
    source_id = str(source_folder.get("id", "") or "").strip()
    target_id = str(target_folder.get("id", "") or "").strip()
    if not source_id or not target_id:
        raise RuntimeError("合并文件夹缺少目录 ID")
    moved_count = 0
    monitor_sync_events = 0
    skipped: List[str] = []
    cleanup_pending: List[Dict[str, str]] = []
    pending_moves: List[Dict[str, Any]] = []
    target_names = _folder_entry_names(target_id, name_cache)
    for child in _folder_children_payload(source_id, source_rel):
        child_id = str(child.get("id", "") or "").strip()
        child_name = str(child.get("name", "") or "").strip()
        if bool(child.get("is_dir")):
            matched = scraper_service.find_scraper_media_folder(
                QUICK_IMPORT_PROVIDER,
                target_id,
                child_name,
            )
            matched_id = str((matched or {}).get("id", "") or "").strip()
            if matched_id and matched_id != child_id:
                matched_name = str((matched or {}).get("name", "") or child_name).strip() or child_name
                nested = _merge_organized_folder_into_existing(
                    child,
                    str(child.get("path", "") or ""),
                    matched,
                    normalize_relative_path(join_relative_path(target_rel, matched_name)),
                    job_id=job_id,
                    monitor_run_id=monitor_run_id,
                    name_cache=name_cache,
                    depth=depth + 1,
                )
                moved_count += int(nested.get("moved_count", 0) or 0)
                monitor_sync_events += int(nested.get("monitor_sync_events", 0) or 0)
                skipped.extend(nested.get("skipped") or [])
                cleanup_pending.extend(nested.get("cleanup_pending") or [])
                if not nested.get("skipped"):
                    # 内容已经并过去了，删空目录只是收尾：失败不能连累搬运结果。
                    try:
                        scraper_service.delete_scraper_entries(
                            QUICK_IMPORT_PROVIDER,
                            [child_id],
                            parent_id=source_id,
                            entries=[child],
                        )
                    except Exception as exc:
                        cleanup_pending.append(
                            {
                                "id": child_id,
                                "name": child_name,
                                "path": str(child.get("path", "") or ""),
                                "parent_id": source_id,
                                "reason": str(exc)[:120],
                            }
                        )
                continue
        if child_name in target_names:
            skipped.append(child_name)
            continue
        target_names.add(child_name)
        pending_moves.append(child)
    if pending_moves:
        move_result = _move_entries_into_folder(
            pending_moves,
            source_cid=source_id,
            target_cid=target_id,
            target_rel=target_rel,
            job_id=job_id,
            monitor_run_id=monitor_run_id,
        )
        moved_count += len(pending_moves)
        monitor_sync_events += max(0, int(((move_result.get("monitor_sync") or {}).get("event_count", 0) or 0)))
    return {
        "moved_count": moved_count,
        "monitor_sync_events": monitor_sync_events,
        "skipped": skipped,
        "cleanup_pending": cleanup_pending,
    }


def _dispatch_organized_entry(
    entry: Dict[str, Any],
    *,
    source_cid: str,
    source_rel: str,
    target_cid: str,
    target_rel: str,
    job_id: int,
    monitor_run_id: str = "",
    name_cache: Optional[Dict[str, Set[str]]] = None,
) -> Dict[str, Any]:
    """把整理好的条目分发到监控目录：目标已有同名文件夹时并进去。

    以前是无条件把接收夹里整理出来的"片名 (年份)"文件夹整个搬过去，目标目录里已经存在
    同一部剧的文件夹时，115 会把新搬来的文件夹自动改名成"片名 (年份)(1)"，于是一次导入
    多个单集文件就散成好几个文件夹。现在先找目标目录里的现成文件夹，找到就把内容并进去。
    """
    entry_id = str(entry.get("id", "") or "").strip()
    entry_name = str(entry.get("name", "") or "").strip()
    is_dir = bool(entry.get("is_dir"))
    if not entry_id or not entry_name:
        raise RuntimeError("整理后的条目缺少 ID 或名称")
    cache = name_cache if isinstance(name_cache, dict) else {}
    lookup_name = entry_name if is_dir else os.path.splitext(entry_name)[0]
    existing = scraper_service.find_scraper_media_folder(QUICK_IMPORT_PROVIDER, target_cid, lookup_name)
    existing_id = str((existing or {}).get("id", "") or "").strip()
    if not existing_id or existing_id == entry_id:
        move_result = _move_entries_into_folder(
            [entry],
            source_cid=source_cid,
            target_cid=target_cid,
            target_rel=target_rel,
            job_id=job_id,
            monitor_run_id=monitor_run_id,
        )
        return {"merged": False, "skipped": [], "monitor_sync_events": max(0, int(((move_result.get("monitor_sync") or {}).get("event_count", 0) or 0)))}

    existing_name = str((existing or {}).get("name", "") or entry_name).strip() or entry_name
    merged_target_rel = normalize_relative_path(join_relative_path(target_rel, existing_name))
    if not is_dir:
        # 散文件（例如已经标准命名的电影）：直接放进已有文件夹，而不是再复制一份到目录里。
        if entry_name in _folder_entry_names(existing_id, cache):
            return {"merged": False, "skipped": [entry_name], "target_folder": existing_name}
        move_result = _move_entries_into_folder(
            [entry],
            source_cid=source_cid,
            target_cid=existing_id,
            target_rel=merged_target_rel,
            job_id=job_id,
            monitor_run_id=monitor_run_id,
        )
        return {"merged": True, "skipped": [], "target_folder": existing_name, "moved_count": 1, "monitor_sync_events": max(0, int(((move_result.get("monitor_sync") or {}).get("event_count", 0) or 0)))}

    outcome = _merge_organized_folder_into_existing(
        entry,
        normalize_relative_path(str(entry.get("path", "") or ""))
        or normalize_relative_path(join_relative_path(source_rel, entry_name)),
        existing,
        merged_target_rel,
        job_id=job_id,
        monitor_run_id=monitor_run_id,
        name_cache=cache,
    )
    skipped = list(outcome.get("skipped") or [])
    cleanup_pending = list(outcome.get("cleanup_pending") or [])
    if not skipped:
        # 内容已经全部并进目标文件夹，接收夹里那个空文件夹要清掉；清理失败只记
        # “待清理”，不能把已经成功的搬运判成失败。
        try:
            scraper_service.delete_scraper_entries(
                QUICK_IMPORT_PROVIDER,
                [entry_id],
                parent_id=source_cid,
                entries=[entry],
            )
        except Exception as exc:
            cleanup_pending.append(
                {
                    "id": entry_id,
                    "name": entry_name,
                    "path": str(entry.get("path", "") or ""),
                    "parent_id": source_cid,
                    "reason": str(exc)[:120],
                }
            )
    return {
        "merged": True,
        "skipped": skipped,
        "cleanup_pending": cleanup_pending,
        "target_folder": existing_name,
        "moved_count": int(outcome.get("moved_count", 0) or 0),
        "monitor_sync_events": int(outcome.get("monitor_sync_events", 0) or 0),
    }


def _dispatch_scan_scope_rel(
    target_rel: str,
    entry_name: str,
    is_dir: bool,
    dispatch: Dict[str, Any],
) -> str:
    """分发后要刷新 STRM 的范围：优先该条目的媒体文件夹，散文件退回父目录。"""
    folder_name = str(dispatch.get("target_folder", "") or "").strip()
    if not folder_name and is_dir and not dispatch.get("merged"):
        folder_name = str(entry_name or "").strip()
    if folder_name:
        return normalize_relative_path(join_relative_path(target_rel, folder_name))
    return normalize_relative_path(target_rel)


def _queue_dispatch_child_run(
    cfg: Dict[str, Any],
    target_rel: str,
    entry_name: str,
    is_dir: bool,
    dispatch: Dict[str, Any],
) -> str:
    """为一条分发成功的条目单独排一条目录同步任务（独立记录，不挂接收夹父运行）。

    接收夹整理只负责识别与移动；搬进监控目录后的 STRM 生成是独立的文件夹监控任务，
    各自留下自己的运行记录，来源统一标注「接收夹分发」。
    """
    scope_rel = _dispatch_scan_scope_rel(target_rel, entry_name, is_dir, dispatch)
    if not scope_rel:
        return ""
    try:
        from .monitor import queue_inbox_dispatch_scan

        return queue_inbox_dispatch_scan(cfg, scope_rel)
    except Exception:
        logging.exception("接收夹分发子任务排队失败: %s", scope_rel)
        return ""


def run_quick_import(
    trigger: str = "manual",
    *,
    sub_path: str = "",
    parent_run_id: str = "",
    source_ref: str = "",
    wait_for_lock: bool = False,
) -> Dict[str, Any]:
    """扫描接收夹，整理高置信度条目并按类型分发到标注过的监控目录。

    低置信度 / 识别失败 / 计划冲突 / 搬运失败的条目都会留在接收夹，并记录具体原因。
    """
    # 手动点击时不卡住请求：已有整理在跑就直接返回（卡片上会显示黄色的「中断」按钮）。
    if wait_for_lock:
        lock_wait_seconds = max(QUICK_IMPORT_LOCK_WAIT_SECONDS, 60)
    else:
        lock_wait_seconds = 0 if str(trigger or "").strip().lower() == "manual" else QUICK_IMPORT_LOCK_WAIT_SECONDS
    if not _QUICK_IMPORT_RUN_LOCK.acquire(timeout=lock_wait_seconds):
        return {
            "ok": True,
            "skipped": True,
            "summary": "已有接收夹整理在执行，可在任务卡片上点「中断」后重试",
        }
    _QUICK_IMPORT_CANCEL.clear()
    try:
        cfg = get_config()
        config_error = validate_quick_import_config(cfg)
        if config_error:
            raise RuntimeError(config_error)
        conf = build_quick_import_config(cfg)
        inbox_rel = conf["inbox_rel"]
        normalized_sub = normalize_relative_path(str(sub_path or "").strip())
        base_rel = normalize_relative_path(
            "/".join(part for part in (inbox_rel, normalized_sub) if part)
        )
        started_at = now_text()
        run_id = _insert_quick_import_run(trigger, conf["inbox_path"], started_at)
        task_label = str(conf.get("task_name") or "接收夹").strip() or "接收夹"
        monitor_run_id = create_monitor_run(
            run_kind="inbox",
            task_name=task_label,
            source=trigger,
            scope={"kind": "paths", "paths": [base_rel] if base_rel else []},
            subject="识别中",
            parent_run_id=parent_run_id,
            source_ref=source_ref,
            task_snapshot=get_inbox_task(cfg),
        )
        start_monitor_run(monitor_run_id, subject="识别中", scope={"kind": "paths", "paths": [base_rel] if base_rel else []})
        moved: List[Dict[str, Any]] = []
        left: List[Dict[str, Any]] = []
        cleanup_leftovers: List[Dict[str, Any]] = []

        def write_inbox_divider(kind: str, extra: str) -> None:
            # 和扫描任务用同一套分隔行，这样接收夹整理在「监控日志」里也是独立的一个任务分段。
            try:
                write_monitor_log_sync(
                    f"━━━━━━━━━━【{kind} | {task_label} | {extra}】━━━━━━━━━━",
                    "task-divider",
                )
            except Exception:
                pass

        def finish_run(
            status: str,
            moved_count: int,
            left_count: int,
            summary: str,
            detail: Dict[str, Any],
        ) -> None:
            """收尾时同时写运行记录和监控日志——接收夹日志要和扫描任务在同一个列表里。"""
            _finish_quick_import_run(run_id, status, moved_count, left_count, summary, detail)
            run_status = "failed" if status == "failed" else ("cancelled" if status == "cancelled" else ("partial" if left_count else ("no_change" if not moved_count else "completed")))
            run_result = {
                "moved": moved_count,
                "left": left_count,
                **(detail if isinstance(detail, dict) else {}),
            }
            # 接收夹记录只覆盖「识别 + 整理移动」：分发完成即定稿，STRM 生成由
            # 后续独立的目录同步任务各自记录，不再让接收夹父运行等待。
            finish_monitor_run(monitor_run_id, status=run_status, summary=summary, result=run_result)
            if status == "failed":
                level = "error"
            elif status == "cancelled":
                level = "warn"
            else:
                level = "success" if moved_count else "info"
            try:
                write_monitor_log_sync(f"{task_label} · {summary}", level)
            except Exception:
                # 日志落盘失败（例如非容器环境没有 /app/logs）不能影响整理结果。
                pass
            write_inbox_divider("任务结束", {"completed": "完成", "cancelled": "中断"}.get(status, "失败"))

        # 同一次导入里多个条目可能进同一个目标文件夹，文件夹列表列一次够用（避免重复请求）。
        dispatch_name_cache: Dict[str, Set[str]] = {}
        write_inbox_divider("任务开始", format_monitor_trigger(trigger))
        try:
            base_cid = resolve_scraper_dest_folder_id(QUICK_IMPORT_PROVIDER, base_rel)
            identified = identify_scraper_batch_entries(
                QUICK_IMPORT_PROVIDER,
                None,
                base_cid=base_cid,
                base_path=base_rel,
            )
            items = identified.get("items") or []
            results = identified.get("results") or []
            picked = identified.get("picked") or {}
            subjects: List[str] = []
            for candidate in picked.values() if isinstance(picked, dict) else []:
                if not isinstance(candidate, dict):
                    continue
                title = str(candidate.get("title", "") or candidate.get("name", "") or "").strip()
                year = str(candidate.get("year", "") or "").strip()
                label = f"{title}（{year}）" if title and year else title
                if label and label not in subjects:
                    subjects.append(label)
            if subjects:
                display_subject = subjects[0] if len(subjects) == 1 else f"{'、'.join(subjects[:2])} 等 {len(subjects)} 部影视"
                update_monitor_run(monitor_run_id, subject=display_subject)
                record_monitor_run_event(monitor_run_id, category="process", operation="identified", status="completed", title="识别完成", detail={"subjects": subjects})
            items_by_index = {
                max(0, parse_int(item.get("item_index", 0), 0)): item
                for item in items
                if isinstance(item, dict)
            }
            results_by_index = {
                max(0, parse_int(result.get("item_index", 0), 0)): result
                for result in results
                if isinstance(result, dict)
            }
            if not items:
                summary = "接收夹没有可整理的内容"
                finish_run("completed", 0, 0, summary, {"moved": [], "left": []})
                return {"ok": True, "moved": [], "left": [], "summary": summary, "run_id": run_id}

            processed_indexes: List[int] = []
            cancelled = False
            for index in sorted(picked):
                if _QUICK_IMPORT_CANCEL.is_set():
                    cancelled = True
                    break
                processed_indexes.append(index)
                item = items_by_index.get(index)
                candidate = picked.get(index) if isinstance(picked.get(index), dict) else {}
                if not item or not candidate:
                    continue
                media_type = normalize_tmdb_media_type(candidate.get("media_type"), "")
                if media_type not in QUICK_IMPORT_TARGET_KEYS:
                    left.append(
                        {
                            "name": str(item.get("name", "") or ""),
                            "reason_code": "unrecognized",
                            "reason": "无法判断是电影还是电视剧",
                        }
                    )
                    continue
                target = conf["targets"].get(media_type) or {}
                if not target:
                    left.append(
                        {
                            "name": str(item.get("name", "") or ""),
                            "reason_code": "target_unavailable",
                            "reason": f"没有监控任务标注为「{QUICK_IMPORT_TARGET_LABELS[media_type]}」快捷导入目标",
                        }
                    )
                    continue
                options = _target_scrape_options(target)
                # 接收夹里常常是"散文件"（没有独立文件夹），必须强制整理进 片名 (年份)/ 再搬运，
                # 否则只会原地改名、搬过去还是散文件。
                options["force_media_folder"] = True
                try:
                    target_cid = resolve_scraper_dest_folder_id(
                        QUICK_IMPORT_PROVIDER,
                        target["scan_rel"],
                    )
                except Exception as exc:
                    left.append(
                        {
                            "name": str(item.get("name", "") or ""),
                            "reason_code": "target_unavailable",
                            "reason": f"目标监控目录不可用：{str(exc)[:120]}",
                        }
                    )
                    continue
                # 接收夹里的文件夹只是中转：目标监控目录里已经有这部剧/这部电影的文件夹时，
                # 直接把内容并进去即可，不必先把接收夹文件夹改成规范名——同批多个同名文件夹
                # 会互相撞成"当前目录中已有同名文件夹"，最后一个只能留在接收夹里。
                source_entry = item.get("entry") if isinstance(item.get("entry"), dict) else {}
                source_entry_name = str(source_entry.get("name", "") or "").strip()
                if bool(source_entry.get("is_dir")) and source_entry_name:
                    try:
                        existing_target_folder = scraper_service.find_scraper_media_folder(
                            QUICK_IMPORT_PROVIDER,
                            target_cid,
                            source_entry_name,
                        )
                    except Exception:
                        # 查一下目标目录只是"能不能直接合并"的优化，失败就按老流程（改规范名再搬）走。
                        existing_target_folder = {}
                    if existing_target_folder:
                        options["rename_selected_folders"] = False
                plan = build_scraper_plan_for_batch(
                    QUICK_IMPORT_PROVIDER,
                    [item],
                    {index: candidate},
                    options,
                    base_cid=base_cid,
                    base_path=base_rel,
                )
                plan_summaries = plan.get("items") if isinstance(plan, dict) else []
                plan_summary = plan_summaries[0] if isinstance(plan_summaries, list) and plan_summaries else {}
                issues = [
                    str(value).strip()
                    for value in ((plan.get("issues") if isinstance(plan, dict) else None) or [])
                    if str(value or "").strip()
                ]
                if not plan or issues:
                    left.append(
                        {
                            "name": str(item.get("name", "") or ""),
                            "reason_code": "plan_conflict",
                            "reason": f"整理计划有冲突：{issues[0][:120]}" if issues else "无法生成整理计划",
                        }
                    )
                    continue
                ready_count = max(0, parse_int(plan.get("ready_count", 0), 0))
                job_id = 0
                if ready_count > 0:
                    try:
                        job = create_scraper_job_from_plan({"plan": plan})
                        job_id = max(0, parse_int(job.get("job_id", 0), 0))
                        if job_id > 0:
                            submit_scraper_job(job_id).result(timeout=QUICK_IMPORT_JOB_WAIT_SECONDS)
                            state = scraper_service.get_scraper_jobs_state(job_id=job_id)
                            jobs = state.get("jobs") if isinstance(state, dict) else []
                            actual = jobs[0] if isinstance(jobs, list) and jobs else {}
                            actual_status = str(actual.get("status", "") or "").strip()
                            if actual_status in {"failed", "partial", "rollback_failed"}:
                                detail = str(actual.get("status_detail", "") or "整理动作未全部完成")
                                left.append(
                                    {
                                        "name": str(item.get("name", "") or ""),
                                        "reason_code": "organize_failed",
                                        "reason": f"整理{('部分完成' if actual_status == 'partial' else '失败')}：{detail[:120]}",
                                    }
                                )
                                record_monitor_run_event(
                                    monitor_run_id,
                                    category="problem",
                                    operation="organize",
                                    status=actual_status,
                                    title=str(item.get("name", "") or ""),
                                    detail={"scraper_job_id": job_id, "status": actual_status, "detail": detail},
                                )
                                continue
                            if actual_status == "completed":
                                record_monitor_run_event(
                                    monitor_run_id,
                                    category="remote",
                                    operation="organize",
                                    status="completed",
                                    title=str(item.get("name", "") or ""),
                                    detail={
                                        "scraper_job_id": job_id,
                                        "succeeded_actions": int(actual.get("succeeded_actions", 0) or 0),
                                        "failed_actions": int(actual.get("failed_actions", 0) or 0),
                                    },
                                )
                    except Exception as exc:
                        left.append(
                            {
                                "name": str(item.get("name", "") or ""),
                                "reason_code": "organize_failed",
                                "reason": f"整理失败：{str(exc)[:120]}",
                            }
                        )
                        continue

                original_entry = item.get("entry") if isinstance(item.get("entry"), dict) else {}
                entry = _resolve_entry_after_organize(base_cid, plan_summary, original_entry)
                entry_id = str(entry.get("id", "") or "").strip()
                if not entry_id:
                    left.append(
                        {
                            "name": str(item.get("name", "") or ""),
                            "reason_code": "organize_failed",
                            "reason": "整理后未能在接收夹内定位到条目，请人工确认",
                        }
                    )
                    continue
                # 条目本身在接收夹里，补上接收夹下的完整路径：搬运/合并的监控同步事件要靠它算新旧路径。
                entry_name = str(entry.get("name", "") or "").strip()
                entry["parent_id"] = str(entry.get("parent_id", "") or base_cid).strip() or base_cid
                entry["parent_path"] = base_rel
                entry["path"] = normalize_relative_path(join_relative_path(base_rel, entry_name))
                try:
                    dispatch = _dispatch_organized_entry(
                        entry,
                        source_cid=base_cid,
                        source_rel=base_rel,
                        target_cid=target_cid,
                        target_rel=target["scan_rel"],
                        job_id=job_id,
                        name_cache=dispatch_name_cache,
                        monitor_run_id=monitor_run_id,
                    )
                except Exception as exc:
                    left.append(
                        {
                            "name": str(item.get("name", "") or ""),
                            "reason_code": "dispatch_failed",
                            "reason": f"搬运失败：{str(exc)[:120]}",
                        }
                    )
                    continue
                if dispatch.get("skipped"):
                    left.append(
                        {
                            "name": str(item.get("name", "") or ""),
                            "reason_code": "plan_conflict",
                            "reason": (
                                f"目标文件夹「{dispatch.get('target_folder', '')}」中已存在同名文件："
                                f"{'、'.join(str(value) for value in dispatch.get('skipped') or [])[:120]}"
                            ),
                        }
                    )
                    continue
                # 搬运已经成功，只是接收夹里的空壳目录没删掉：先收集，等本轮全部搬完再统一重试，
                # 只有确实还残留的才写进运行记录（避免“已清掉却还显示删除失败”）。
                cleanup_leftovers.extend(dispatch.get("cleanup_pending") or [])
                # 每个成功分发的条目立刻建一条独立的目录同步任务（自己的运行记录），
                # 接收夹父运行不等它结束。
                child_run_id = _queue_dispatch_child_run(
                    cfg,
                    str(target.get("scan_rel", "") or ""),
                    entry_name,
                    bool(entry.get("is_dir")),
                    dispatch,
                )
                moved.append(
                    {
                        "name": str(item.get("name", "") or ""),
                        "target": QUICK_IMPORT_TARGET_LABELS[media_type],
                        "task_name": str(target.get("task_name", "") or ""),
                        "job_id": job_id,
                        "run_id": child_run_id,
                        "monitor_sync_events": int(dispatch.get("monitor_sync_events", 0) or 0),
                    }
                )
                is_ai = str(candidate.get("source") or "").strip() == "ai"
                match_source = "AI 识别" if is_ai else "规则匹配"
                confidence = max(0, int(candidate.get("ai_confidence") if is_ai else candidate.get("score") or 0))
                match_reason = str(candidate.get("ai_reason") or "").strip() if is_ai else ""
                tmdb_id = max(0, parse_int(candidate.get("id") or 0, 0))
                identified_year = str(candidate.get("year") or "").strip()
                record_monitor_run_event(
                    monitor_run_id,
                    category="remote",
                    operation="merge" if dispatch.get("merged") else "move",
                    status="completed",
                    title=str(item.get("name", "") or ""),
                    detail={
                        "step": "接收夹分发",
                        "operation_label": "网盘合并" if dispatch.get("merged") else "网盘移动",
                        "original_name": source_entry_name,
                        "match_source": match_source,
                        "confidence": confidence,
                        "match_reason": match_reason,
                        "tmdb_id": tmdb_id,
                        "identified_year": identified_year,
                        "old_name": entry_name,
                        "new_name": str(dispatch.get("target_folder", "") or entry_name),
                        "old_path": normalize_relative_path(str(entry.get("path", "") or join_relative_path(base_rel, entry_name))),
                        "new_path": normalize_relative_path(join_relative_path(
                            str(target.get("scan_rel", "") or ""),
                            str(dispatch.get("target_folder", "") or entry_name),
                        )),
                        "target": target.get("scan_rel", ""),
                        "task_name": target.get("task_name", ""),
                        "scraper_job_id": job_id,
                        "child_run_id": child_run_id,
                        "monitor_sync_events": int(dispatch.get("monitor_sync_events", 0) or 0),
                    },
                )

            handled_indexes = set(picked.keys())
            for index, item in items_by_index.items():
                if index in handled_indexes:
                    continue
                entry = item.get("entry") if isinstance(item.get("entry"), dict) else {}
                if bool(entry.get("is_dir")) and str(entry.get("id", "") or "").strip():
                    if not _folder_contains_files(
                        str(entry.get("id", "") or ""),
                        str(entry.get("path", "") or ""),
                    ):
                        # 整理残留的空壳目录（内容已经搬走）：直接清掉，不再报“识别失败、留在接收夹”。
                        try:
                            scraper_service.delete_scraper_entries(
                                QUICK_IMPORT_PROVIDER,
                                [str(entry.get("id", "") or "")],
                                parent_id=str(entry.get("parent_id", "") or base_cid),
                                entries=[entry],
                            )
                            record_monitor_run_event(
                                monitor_run_id,
                                category="process",
                                operation="cleanup",
                                status="completed",
                                title=str(item.get("name", "") or "空目录"),
                                detail={
                                    "path": str(entry.get("path", "") or ""),
                                    "reason": "接收夹空目录已清理",
                                },
                            )
                            try:
                                write_monitor_log_sync(
                                    f"{task_label} · 已清理接收夹空目录：{entry.get('path') or item.get('name')}",
                                    "info",
                                )
                            except Exception:
                                pass
                            continue
                        except Exception as exc:
                            left.append(
                                {
                                    "name": str(item.get("name", "") or ""),
                                    "reason_code": "cleanup_failed",
                                    "reason": f"空目录待清理：{str(exc)[:100]}",
                                }
                            )
                            continue
                left.append(
                    {
                        "name": str(item.get("name", "") or ""),
                        "reason_code": "unrecognized",
                        "reason": _left_reason_from_result(results_by_index.get(index) or {}),
                    }
                )

            for item in left:
                if isinstance(item, dict):
                    record_monitor_run_event(
                        monitor_run_id,
                        category="problem",
                        operation="leave_in_inbox",
                        status="skipped",
                        title=str(item.get("name", "") or "未处理项目"),
                        detail={
                            "reason_code": str(item.get("reason_code", "") or ""),
                            "reason": str(item.get("reason", "") or ""),
                        },
                    )

            if cleanup_leftovers:
                # 搬运全部结束，再统一重试一次接收夹残留清理：清掉的只记过程事件，
                # 仍然残留的才写“待清理”，不再把已经清掉的目录显示成删除失败。
                for leftover in _retry_inbox_cleanup(cleanup_leftovers, monitor_run_id=monitor_run_id):
                    name = str(leftover.get("name", "") or leftover.get("path", "") or "接收夹残留")
                    record_monitor_run_event(
                        monitor_run_id,
                        category="problem",
                        operation="cleanup",
                        status="pending",
                        title=f"接收夹残留待清理：{name}",
                        detail={
                            "path": str(leftover.get("path", "") or ""),
                            "reason": str(leftover.get("reason", "") or ""),
                        },
                    )
                    try:
                        write_monitor_log_sync(
                            f"{task_label} · 接收夹残留待清理：{leftover.get('path') or name}",
                            "warn",
                        )
                    except Exception:
                        pass

            if cancelled:
                processed_set = set(processed_indexes)
                for index in sorted(picked):
                    if index in processed_set:
                        continue
                    pending_item = items_by_index.get(index) or {}
                    left.append(
                        {
                            "name": str(pending_item.get("name", "") or ""),
                            "reason_code": "cancelled",
                            "reason": "已中断，未整理",
                        }
                    )
                summary = f"已中断：已分发 {len(moved)} 项，留在接收夹 {len(left)} 项"
                finish_run(
                    "cancelled",
                    len(moved),
                    len(left),
                    summary,
                    {
                        "moved": moved,
                        "left": left,
                        "monitor_sync_events": sum(int(item.get("monitor_sync_events", 0) or 0) for item in moved),
                        "cancelled": True,
                    },
                )
                return {
                    "ok": True,
                    "cancelled": True,
                    "run_id": run_id,
                    "moved": moved,
                    "left": left,
                    "summary": summary,
                }

            summary = f"已整理分发 {len(moved)} 项，留在接收夹 {len(left)} 项"
            finish_run(
                "completed",
                len(moved),
                len(left),
                summary,
                {
                    "moved": moved,
                    "left": left,
                    "monitor_sync_events": sum(int(item.get("monitor_sync_events", 0) or 0) for item in moved),
                },
            )
            return {
                "ok": True,
                "run_id": run_id,
                "moved": moved,
                "left": left,
                "summary": summary,
            }
        except Exception as exc:
            finish_run(
                "failed",
                len(moved),
                len(left),
                f"快捷导入失败：{str(exc)[:200]}",
                {"moved": moved, "left": left, "error": str(exc)[:300]},
            )
            raise
    finally:
        _QUICK_IMPORT_CANCEL.clear()
        _QUICK_IMPORT_RUN_LOCK.release()
