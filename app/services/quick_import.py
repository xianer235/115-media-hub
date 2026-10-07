"""接收夹快捷导入：整理（与监控自动刮削共用同一流程）+ 按类型分发到监控目录。

最小改动接入现有工作流：

- 接收夹就是 ``monitor_tasks`` 里的一个 ``task_type='inbox'`` 任务，和扫描任务共用同一套
  任务 / 路径 / webhook 口径（旧版的 ``quick_import_enabled`` / ``quick_import_inbox_path``
  会在 ``normalize_config`` 里迁移成这个任务）；
- 分发目标写在该任务的 ``distribute_targets``（movie / tv → 远程文件夹路径，带网盘挂载前缀）；
- 接收夹可以挂在任意网盘（任务上的 ``provider``，默认 115），整理选项取自任务自己的
  ``auto_scrape_options``；
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
    _scraper_season_pack_seasons,
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


QUICK_IMPORT_DEFAULT_PROVIDER = "115"
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
QUICK_IMPORT_DEFAULT_IDLE_SECONDS = 120
QUICK_IMPORT_MAX_IDLE_SECONDS = 3600
QUICK_IMPORT_DEFAULT_MAX_ITEMS = 100
QUICK_IMPORT_MAX_ITEMS = 500
QUICK_IMPORT_DEFAULT_BATCH_PAUSE_SECONDS = 5
QUICK_IMPORT_MAX_BATCH_PAUSE_SECONDS = 300
QUICK_IMPORT_SCAN_SCOPE_CHUNK = 50

_QUICK_IMPORT_RUN_LOCK = threading.Lock()
# 中断标记：接收夹整理是长任务，用户点「中断」后在下一条目开始前生效（已搬完的不会回滚）。
_QUICK_IMPORT_CANCEL = threading.Event()
# 触发协调：整理正在执行时把后续触发记成「还需再跑一轮」，由工作线程在本轮结束后
# 自动接着跑，任何触发都不会被丢掉。
_INBOX_TRIGGER_LOCK = threading.Lock()
_INBOX_TRIGGER_EVENT = threading.Event()
_INBOX_TRIGGER_STATE: Dict[str, Any] = {
    "worker": None,
    "pending": False,
    "trigger": "",
    "source_ref": "",
    "last_arrival_at": 0.0,
}
_INBOX_TRIGGER_PRIORITY = {"manual": 5, "cron": 4, "offline": 3, "import": 2, "test": 1}


def request_quick_import_cancel() -> bool:
    """请求中断当前接收夹整理；没有在跑时返回 False。"""
    if not _QUICK_IMPORT_RUN_LOCK.locked():
        return False
    with _INBOX_TRIGGER_LOCK:
        # 中断意味着用户不想再排队了：取消同时清掉「再跑一轮」预约。
        _INBOX_TRIGGER_STATE["pending"] = False
    _INBOX_TRIGGER_EVENT.set()
    _QUICK_IMPORT_CANCEL.set()
    return True


def _inbox_trigger_priority(trigger: str) -> int:
    return _INBOX_TRIGGER_PRIORITY.get(str(trigger or "").strip().lower(), 0)


def notify_quick_import(trigger: str = "queued", *, source_ref: str = "") -> Dict[str, Any]:
    """登记一次接收夹整理请求；正在执行时预约下一轮，永不静默跳过。"""
    normalized_trigger = str(trigger or "").strip().lower() or "queued"
    normalized_ref = str(source_ref or "").strip()
    started_worker: Optional[threading.Thread] = None
    with _INBOX_TRIGGER_LOCK:
        _INBOX_TRIGGER_STATE["last_arrival_at"] = time.monotonic()
        worker = _INBOX_TRIGGER_STATE.get("worker")
        if isinstance(worker, threading.Thread) and worker.is_alive():
            current = str(_INBOX_TRIGGER_STATE.get("trigger", "") or "")
            if _inbox_trigger_priority(normalized_trigger) >= _inbox_trigger_priority(current):
                _INBOX_TRIGGER_STATE["trigger"] = normalized_trigger
                _INBOX_TRIGGER_STATE["source_ref"] = normalized_ref
            _INBOX_TRIGGER_STATE["pending"] = True
            started = False
            running = True
        else:
            _INBOX_TRIGGER_STATE["pending"] = False
            _INBOX_TRIGGER_STATE["trigger"] = normalized_trigger
            _INBOX_TRIGGER_STATE["source_ref"] = normalized_ref
            started_worker = threading.Thread(
                target=_inbox_worker_loop,
                args=(normalized_trigger, normalized_ref),
                name="inbox-quick-import",
                daemon=True,
            )
            _INBOX_TRIGGER_STATE["worker"] = started_worker
            started = True
            running = False
    if started_worker is not None:
        started_worker.start()
    _INBOX_TRIGGER_EVENT.set()
    return {
        "ok": True,
        "started": started,
        "queued": True,
        "running": running,
        "summary": "已有接收夹整理在执行，已安排再跑一轮" if running else "已开始接收夹整理",
    }


def _inbox_delay_seconds() -> int:
    try:
        conf = build_quick_import_config(get_config())
    except Exception:
        conf = {}
    return max(0, int(conf.get("inbox_idle_seconds", QUICK_IMPORT_DEFAULT_IDLE_SECONDS) or 0))


def _wait_for_inbox_next_run() -> None:
    """等待下一次接收夹整理：新保存按静默窗口；手动触发立即放行。"""
    idle_seconds = _inbox_delay_seconds()
    while True:
        with _INBOX_TRIGGER_LOCK:
            if not _INBOX_TRIGGER_STATE.get("pending"):
                return
            if str(_INBOX_TRIGGER_STATE.get("trigger", "") or "").strip() == "manual":
                return
            if idle_seconds <= 0:
                return
            deadline = float(_INBOX_TRIGGER_STATE.get("last_arrival_at", 0.0) or 0.0) + idle_seconds
            now = time.monotonic()
            remaining = deadline - now
        if remaining <= 0:
            return
        _INBOX_TRIGGER_EVENT.wait(min(0.5, remaining))


def _inbox_worker_loop(trigger: str, source_ref: str) -> None:
    current_trigger, current_ref = trigger, source_ref
    while True:
        try:
            result = run_quick_import(current_trigger, source_ref=current_ref, wait_for_lock=True)
            if isinstance(result, dict) and result.get("skipped"):
                # 极端情况下锁超时：不丢请求，稍后重试这一轮。
                with _INBOX_TRIGGER_LOCK:
                    _INBOX_TRIGGER_STATE["pending"] = True
                _INBOX_TRIGGER_EVENT.set()
                time.sleep(5)
                continue
        except Exception:
            logging.exception("接收夹整理执行失败")
        with _INBOX_TRIGGER_LOCK:
            if not _INBOX_TRIGGER_STATE.get("pending"):
                _INBOX_TRIGGER_STATE["worker"] = None
                _INBOX_TRIGGER_STATE["trigger"] = ""
                _INBOX_TRIGGER_STATE["source_ref"] = ""
                _INBOX_TRIGGER_EVENT.clear()
                return
            current_trigger = str(_INBOX_TRIGGER_STATE.get("trigger", "") or "queued")
            current_ref = str(_INBOX_TRIGGER_STATE.get("source_ref", "") or "")
        _wait_for_inbox_next_run()
        with _INBOX_TRIGGER_LOCK:
            if not _INBOX_TRIGGER_STATE.get("pending"):
                _INBOX_TRIGGER_STATE["worker"] = None
                _INBOX_TRIGGER_STATE["trigger"] = ""
                _INBOX_TRIGGER_STATE["source_ref"] = ""
                _INBOX_TRIGGER_EVENT.clear()
                return
            current_trigger = str(_INBOX_TRIGGER_STATE.get("trigger", "") or current_trigger)
            current_ref = str(_INBOX_TRIGGER_STATE.get("source_ref", "") or current_ref)
            _INBOX_TRIGGER_STATE["pending"] = False
            _INBOX_TRIGGER_EVENT.clear()


def pending_quick_import_rerun() -> bool:
    """是否已经预约了下一轮整理（接收夹卡片展示用）。"""
    with _INBOX_TRIGGER_LOCK:
        return bool(_INBOX_TRIGGER_STATE.get("pending"))


def _inbox_remote_path(cfg: Dict[str, Any]) -> str:
    task = get_inbox_task(cfg)
    remote = normalize_remote_path(str(task.get("scan_path", "") or "").strip())
    return "" if remote == "/" else remote


def _inbox_provider(cfg: Dict[str, Any]) -> str:
    """接收夹所在网盘：任务上的 ``provider``，缺省回退 115。"""
    task = get_inbox_task(cfg)
    provider = normalize_mount_provider(task.get("provider", "")) if isinstance(task, dict) else ""
    return provider or QUICK_IMPORT_DEFAULT_PROVIDER


def _inbox_scrape_options(inbox: Dict[str, Any]) -> Dict[str, Any]:
    """接收夹整理选项：取自接收夹任务自己，缺省按中文标题 + 不删广告文件起步。"""
    options: Dict[str, Any] = {"title_language": "zh", "delete_ad_files": False}
    raw_options = inbox.get("auto_scrape_options") if isinstance(inbox, dict) else None
    if isinstance(raw_options, dict) and raw_options:
        options.update(_normalize_scraper_batch_preferences(raw_options))
    return options


def _inbox_rel_path(cfg: Dict[str, Any]) -> str:
    remote = _inbox_remote_path(cfg)
    if not remote:
        return ""
    try:
        _provider, relative = resolve_provider_relative_path(
            cfg,
            remote,
            expected_provider=_inbox_provider(cfg),
        )
    except Exception:
        return ""
    return normalize_relative_path(relative)


def _task_rel_path(cfg: Dict[str, Any], scan_path: Any, provider: str = "") -> str:
    remote = normalize_remote_path(str(scan_path or "").strip())
    if not remote:
        return ""
    try:
        _provider, relative = resolve_provider_relative_path(
            cfg,
            remote,
            expected_provider=provider or _inbox_provider(cfg),
        )
    except Exception:
        return normalize_relative_path(remote.lstrip("/"))
    return normalize_relative_path(relative)


def build_quick_import_config(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """接收夹配置：接收夹本身是 ``monitor_tasks`` 里的一个 inbox 任务，分发目标写在它的
    ``distribute_targets`` 上（同盘远程文件夹路径），整理选项也取自它自己。"""
    active_cfg = cfg if isinstance(cfg, dict) else get_config()
    inbox = get_inbox_task(active_cfg)
    provider = _inbox_provider(active_cfg)
    inbox_options = _inbox_scrape_options(inbox)
    targets: Dict[str, Dict[str, Any]] = {key: {} for key in QUICK_IMPORT_TARGET_KEYS}
    distribute_targets = (
        inbox.get("distribute_targets") if isinstance(inbox.get("distribute_targets"), dict) else {}
    )
    for key in QUICK_IMPORT_TARGET_KEYS:
        remote = normalize_remote_path(str(distribute_targets.get(key, "") or "").strip())
        if not remote or remote == "/":
            continue
        rel_path = _task_rel_path(active_cfg, remote, provider)
        if not rel_path:
            continue
        targets[key] = {
            "scan_path": remote,
            "scan_rel": rel_path,
            "auto_scrape_options": dict(inbox_options),
        }
    raw_inbox_max_items = inbox.get("inbox_max_items_per_run", 100)
    inbox_max_items_per_run = (
        int(raw_inbox_max_items)
        if raw_inbox_max_items is not None and str(raw_inbox_max_items).strip() != ""
        else 100
    )
    return {
        "task_name": str(inbox.get("name", "") or "").strip(),
        "enabled": bool(inbox.get("enabled")) if inbox else False,
        "provider": provider,
        "inbox_path": _inbox_remote_path(active_cfg),
        "inbox_rel": _inbox_rel_path(active_cfg),
        "targets": targets,
        "inbox_idle_seconds": max(0, int(inbox.get("inbox_idle_seconds", 120) or 120)),
        "inbox_max_items_per_run": max(1, min(500, inbox_max_items_per_run)),
        "inbox_batch_pause_seconds": max(0, int(inbox.get("inbox_batch_pause_seconds", 5) or 5)),
    }


def is_quick_import_savepath(cfg: Dict[str, Any], savepath: Any) -> bool:
    """导入落点是否落在接收夹内（savepath 是网盘相对路径，如 ``接收/xxx``）。

    网盘从接收夹任务内部推导（``build_quick_import_config`` 已有 inbox provider），
    调用方不需要传：savepath 是相对路径、本身不带 provider 信息。
    """
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


def _cross_provider_target_hint(
    cfg: Dict[str, Any],
    provider: str,
) -> str:
    """分发目标落在别的网盘时给出明确提示。

    跨盘目标解析不到接收夹网盘的相对路径，会退化成「去掉挂载前缀的相对路径」
    （``/115/电影`` → ``115/电影``），分发时被当成接收夹网盘根目录下的子目录；这里
    直接拦下并说清「必须和接收夹同盘」。
    """
    inbox = get_inbox_task(cfg)
    raw_targets = normalize_distribute_targets(
        inbox.get("distribute_targets") if isinstance(inbox, dict) else None
    )
    provider_key = normalize_mount_provider(provider)
    for key in QUICK_IMPORT_TARGET_KEYS:
        raw_value = str(raw_targets.get(key, "") or "").strip()
        if not raw_value:
            continue
        try:
            target_provider, _target_rel = resolve_provider_relative_path(
                cfg,
                normalize_remote_path(raw_value),
            )
        except Exception:
            continue
        if normalize_mount_provider(target_provider) == provider_key:
            continue
        label = QUICK_IMPORT_TARGET_LABELS.get(key, key)
        return f"「{label}」分发目标必须和接收夹在同一网盘（接收夹当前在 {provider} 网盘）"
    return ""


def validate_quick_import_config(cfg: Optional[Dict[str, Any]] = None) -> Optional[str]:
    active_cfg = cfg if isinstance(cfg, dict) else get_config()
    conf = build_quick_import_config(active_cfg)
    provider = str(conf.get("provider", "") or "") or QUICK_IMPORT_DEFAULT_PROVIDER
    if not conf["task_name"]:
        return "没有找到内置的接收夹任务，请重启服务或检查配置（接收夹是内置固定任务，不需要新增）"
    if not conf["enabled"]:
        return f"接收夹任务「{conf['task_name']}」未启用"
    if not conf["inbox_path"]:
        return f"请先给接收夹任务「{conf['task_name']}」选择文件夹"
    inbox_rel = str(conf.get("inbox_rel", "") or "").strip()
    if not inbox_rel:
        return f"接收文件夹必须位于 {provider} 网盘前缀下"
    cross_provider = _cross_provider_target_hint(active_cfg, provider)
    if cross_provider:
        return cross_provider
    if not any(conf["targets"].get(key) for key in QUICK_IMPORT_TARGET_KEYS):
        return "还没有在接收夹任务里指定「电影 / 电视剧」分发目标"
    for task in active_cfg.get("monitor_tasks", []) or []:
        if not isinstance(task, dict):
            continue
        if normalize_task_type(task.get("task_type")) != MONITOR_TASK_TYPE_SCAN:
            continue
        # 只比较同 provider 的扫描任务：跨盘路径本来就不该判重叠。
        try:
            task_provider, _task_rel = resolve_provider_relative_path(
                active_cfg,
                normalize_remote_path(str(task.get("scan_path", "") or "").strip()),
            )
        except Exception:
            continue
        if normalize_mount_provider(task_provider) != provider:
            continue
        scan_rel = _task_rel_path(active_cfg, task.get("scan_path", ""), provider)
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


def _list_inbox_children(base_cid: str, provider: str = QUICK_IMPORT_DEFAULT_PROVIDER) -> List[Dict[str, Any]]:
    payload = scraper_service.list_scraper_entries(provider, base_cid, True)
    entries = payload.get("entries") if isinstance(payload, dict) else []
    return [entry for entry in (entries or []) if isinstance(entry, dict)]


def _resolve_entry_after_organize(
    base_cid: str,
    plan_summary: Dict[str, Any],
    original_entry: Dict[str, Any],
    provider: str = QUICK_IMPORT_DEFAULT_PROVIDER,
) -> Dict[str, Any]:
    """整理后重新定位条目：文件夹按 ID 找；散文件按计划生成的片名文件夹兜底。"""
    try:
        children = _list_inbox_children(base_cid, provider)
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


def _plan_issue_item_index(text: str) -> int:
    """从 ``条目 #2 片名：原因`` 这类问题文案里取条目序号（取不到返回 0）。"""
    prefix = "条目 #"
    value = str(text or "").strip()
    if not value.startswith(prefix):
        return 0
    digits = ""
    for char in value[len(prefix):]:
        if not char.isdigit():
            break
        digits += char
    return max(0, parse_int(digits, 0)) if digits else 0


def _plan_blocked_item_reasons(plan: Dict[str, Any]) -> Dict[int, str]:
    """取出整理计划里"被冲突挡住的条目"和它自己的原因。

    同一批里的条目是互相独立的：某个条目冲突（同标题但不同作品、目标文件重名等）
    只该留它自己，不能让整批都留在接收夹——旧行为正是后者，实测会把已经识别好的
    条目一起扣下。
    """
    blocked: Dict[int, str] = {}
    plan_items = plan.get("items") if isinstance(plan.get("items"), list) else []
    for summary in plan_items:
        if not isinstance(summary, dict):
            continue
        index = max(0, parse_int(summary.get("item_index", 0), 0))
        if index <= 0:
            continue
        issue_count = max(0, parse_int(summary.get("issue_count", 0), 0))
        total = max(0, parse_int(summary.get("total", 0), 0))
        ready = max(0, parse_int(summary.get("ready", 0), 0))
        if issue_count <= 0 and total <= ready:
            continue
        blocked.setdefault(index, "")
    raw_issues = plan.get("issues") if isinstance(plan.get("issues"), list) else []
    item_reasons: Dict[int, str] = {}
    for value in raw_issues:
        text = str(value or "").strip()
        if not text:
            continue
        index = _plan_issue_item_index(text)
        if index <= 0:
            # 读目录失败这类不属于任何条目的问题：保守处理，整批先不动。
            return {key: text for key in blocked}
        item_reasons.setdefault(index, text)
        blocked.setdefault(index, "")
    for index in list(blocked):
        blocked[index] = item_reasons.get(index) or "整理计划有冲突"
    return blocked


def _record_merged_inbox_item(
    *,
    pending_moved: List[Dict[str, Any]],
    cleanup_leftovers: List[Dict[str, Any]],
    prepared_item: Dict[str, Any],
    original_entry: Dict[str, Any],
    merged_into_folder: str,
    job_id: int,
    base_cid: str,
    base_rel: str,
) -> None:
    """同一部影视的多个版本/多个条目已经并进同一个媒体文件夹时的收尾登记。

    内容跟着那个条目的文件夹一起搬运（搬运由那一条负责），这里只登记合并结果；
    自己留下的空壳目录交给统一的残留清理，避免被当成"整理后定位失败"再捡一遍。
    """
    item = prepared_item.get("item") if isinstance(prepared_item.get("item"), dict) else {}
    target = prepared_item.get("target") if isinstance(prepared_item.get("target"), dict) else {}
    candidate = prepared_item.get("candidate") if isinstance(prepared_item.get("candidate"), dict) else {}
    media_type = str(prepared_item.get("media_type", "") or "")
    name = str(item.get("name", "") or "")
    entry_name = str(original_entry.get("name", "") or name)
    entry_path = normalize_relative_path(
        str(original_entry.get("path", "") or join_relative_path(base_rel, entry_name))
    )
    is_folder_entry = bool(original_entry.get("is_dir")) or bool(item.get("is_dir"))
    if is_folder_entry and str(original_entry.get("id", "") or "").strip():
        cleanup_leftovers.append(
            {
                "id": str(original_entry.get("id", "") or ""),
                "name": entry_name,
                "path": entry_path,
                "parent_id": str(original_entry.get("parent_id", "") or base_cid),
            }
        )
    is_ai = str(candidate.get("source") or "").strip() == "ai"
    target_rel = str(target.get("scan_rel", "") or "")
    target_path = str(target.get("scan_path", "") or "")
    pending_moved.append(
        {
            "name": name,
            "target_label": QUICK_IMPORT_TARGET_LABELS.get(media_type, ""),
            "target_path": target_path,
            # 内容跟着拥有该媒体文件夹的条目一起搬运：同一个 STRM 范围在这里去重即可。
            "scope_rel": normalize_relative_path(join_relative_path(target_rel, merged_into_folder)),
            "target": target_path,
            "job_id": job_id,
            "monitor_sync_events": 0,
            "title": name,
            "operation": "merge",
            "detail": {
                "step": "接收夹分发",
                "operation_label": "并入同部影视文件夹",
                "original_name": entry_name,
                "match_source": "AI 识别" if is_ai else "规则匹配",
                "confidence": max(
                    0,
                    int(candidate.get("ai_confidence") if is_ai else candidate.get("score") or 0),
                ),
                "match_reason": str(candidate.get("ai_reason") or "").strip() if is_ai else "",
                "tmdb_id": max(0, parse_int(candidate.get("id") or 0, 0)),
                "identified_year": str(candidate.get("year") or "").strip(),
                "entry_type": "folder" if is_folder_entry else "file",
                "old_name": entry_name,
                "new_name": merged_into_folder,
                "old_path": entry_path,
                "new_path": normalize_relative_path(join_relative_path(target_rel, merged_into_folder)),
                "target": target_rel,
                "task_name": target_path,
                "scraper_job_id": job_id,
                "monitor_sync_events": 0,
                "merged_into_folder": merged_into_folder,
            },
        }
    )


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
                "target_path": (conf["targets"].get(key) or {}).get("scan_path", ""),
                "scan_rel": (conf["targets"].get(key) or {}).get("scan_rel", ""),
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


def _folder_children_payload(
    folder_id: str,
    folder_rel: str,
    provider: str = QUICK_IMPORT_DEFAULT_PROVIDER,
) -> List[Dict[str, Any]]:
    """列出整理结果文件夹的直接子项，并补上完整挂载路径（监控同步事件要用）。"""
    payload = scraper_service.list_scraper_entries(provider, folder_id, True)
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
    provider: str = QUICK_IMPORT_DEFAULT_PROVIDER,
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
        children = _folder_children_payload(normalized_id, folder_rel, provider)
    except Exception:
        return True
    for child in children:
        if bool(child.get("is_dir")):
            if _folder_contains_files(
                str(child.get("id", "") or ""),
                str(child.get("path", "") or ""),
                provider=provider,
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
    provider: str = QUICK_IMPORT_DEFAULT_PROVIDER,
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
        if _folder_contains_files(entry_id, path, provider=provider):
            remaining.append({**leftover, "reason": "目录内仍有内容，未自动清理"})
            continue
        try:
            scraper_service.delete_scraper_entries(
                provider,
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


def _folder_entry_names(
    folder_id: str,
    cache: Dict[str, Set[str]],
    provider: str = QUICK_IMPORT_DEFAULT_PROVIDER,
) -> Set[str]:
    """目标文件夹里已有的条目名（一个文件夹只列一次，合并时用来挡同名文件）。"""
    normalized_id = str(folder_id or "").strip()
    if not normalized_id:
        return set()
    if normalized_id not in cache:
        payload = scraper_service.list_scraper_entries(
            provider,
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
    provider: str = QUICK_IMPORT_DEFAULT_PROVIDER,
) -> Dict[str, Any]:
    entry_ids = [str(item.get("id", "") or "").strip() for item in entries if str(item.get("id", "") or "").strip()]
    if not entry_ids:
        return {"monitor_sync": {"event_count": 0}}
    return scraper_service.move_scraper_entries(
        provider,
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
    provider: str = QUICK_IMPORT_DEFAULT_PROVIDER,
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
    target_names = _folder_entry_names(target_id, name_cache, provider)
    for child in _folder_children_payload(source_id, source_rel, provider):
        child_id = str(child.get("id", "") or "").strip()
        child_name = str(child.get("name", "") or "").strip()
        if bool(child.get("is_dir")):
            matched = scraper_service.find_scraper_media_folder(
                provider,
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
                    provider=provider,
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
                            provider,
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
            provider=provider,
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
    provider: str = QUICK_IMPORT_DEFAULT_PROVIDER,
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
    existing = scraper_service.find_scraper_media_folder(provider, target_cid, lookup_name)
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
            provider=provider,
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
        provider=provider,
    )
    skipped = list(outcome.get("skipped") or [])
    cleanup_pending = list(outcome.get("cleanup_pending") or [])
    if not skipped:
        # 内容已经全部并进目标文件夹，接收夹里那个空文件夹要清掉；清理失败只记
        # “待清理”，不能把已经成功的搬运判成失败。
        try:
            scraper_service.delete_scraper_entries(
                provider,
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
    provider: str,
    target_rel: str,
    entry_name: str,
    is_dir: bool,
    dispatch: Dict[str, Any],
) -> str:
    """为一条分发成功的条目单独排一条目录同步任务（独立记录，不挂接收夹父运行）。

    接收夹整理只负责识别与移动；搬进监控目录后的 STRM 生成是独立的文件夹监控任务，
    各自留下自己的运行记录，来源统一标注「接收夹分发」。

    只有接收夹在 115 上、且目标落在某个监控任务扫描范围内时才有 STRM 可言；
    其他网盘只搬运、不生成 STRM（v1 明确不做跨盘 STRM）。
    """
    if normalize_mount_provider(provider) != QUICK_IMPORT_DEFAULT_PROVIDER:
        return ""
    scope_rel = _dispatch_scan_scope_rel(target_rel, entry_name, is_dir, dispatch)
    if not scope_rel:
        return ""
    try:
        from .monitor import queue_inbox_dispatch_scan

        return queue_inbox_dispatch_scan(cfg, scope_rel, provider)
    except Exception:
        logging.exception("接收夹分发子任务排队失败: %s", scope_rel)
        return ""


def _queue_dispatch_child_runs(
    cfg: Dict[str, Any],
    provider: str,
    scopes: List[str],
) -> Dict[str, str]:
    """把本轮所有分发范围按监控任务合并入队，返回 scope_rel -> run_id。"""
    if normalize_mount_provider(provider) != QUICK_IMPORT_DEFAULT_PROVIDER:
        return {}
    unique_scopes: List[str] = []
    for raw_scope in scopes if isinstance(scopes, list) else []:
        scope = normalize_relative_path(str(raw_scope or "").strip())
        if scope and scope not in unique_scopes:
            unique_scopes.append(scope)
    if not unique_scopes:
        return {}
    task_by_scope: Dict[str, str] = {}
    for scope in unique_scopes:
        try:
            matched = match_monitor_task_for_savepath(cfg, scope, provider=provider)
        except Exception:
            matched = {}
        task_name = str((matched or {}).get("task_name", "") or "").strip()
        if task_name:
            task_by_scope[scope] = task_name
    if not task_by_scope:
        return {}
    queue_scopes = [scope for scope in unique_scopes if scope in task_by_scope]
    try:
        from .monitor import queue_monitor_dir_scan
    except Exception:
        logging.exception("加载监控扫描队列失败")
        return {}
    run_ids: Dict[str, str] = {}
    for index in range(0, len(queue_scopes), QUICK_IMPORT_SCAN_SCOPE_CHUNK):
        chunk = queue_scopes[index : index + QUICK_IMPORT_SCAN_SCOPE_CHUNK]
        try:
            result = queue_monitor_dir_scan(
                cfg,
                provider,
                chunk,
                run_source="inbox_dispatch",
                force_new=False,
            )
        except Exception:
            logging.exception("接收夹分发扫描合并入队失败：%s", "、".join(chunk[:3]))
            continue
        task_run_ids: Dict[str, str] = {}
        for task in result.get("tasks") if isinstance(result.get("tasks"), list) else []:
            task_name = str((task or {}).get("task_name", "") or "").strip()
            run_id = str((task or {}).get("run_id", "") or "").strip()
            if task_name and run_id:
                task_run_ids[task_name] = run_id
        for scope in chunk:
            run_id = task_run_ids.get(task_by_scope.get(scope, ""), "")
            if run_id:
                run_ids[scope] = run_id
    return run_ids


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
        provider = str(conf.get("provider", "") or "") or QUICK_IMPORT_DEFAULT_PROVIDER
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
            base_cid = resolve_scraper_dest_folder_id(provider, base_rel)
            identified = identify_scraper_batch_entries(
                provider,
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
            max_items_per_run = max(1, int(conf.get("inbox_max_items_per_run", 100) or 100))
            batch_pause_seconds = max(0, int(conf.get("inbox_batch_pause_seconds", QUICK_IMPORT_DEFAULT_BATCH_PAUSE_SECONDS) or 0))
            ordered_indexes = sorted(picked)
            pending_moved: List[Dict[str, Any]] = []
            dispatch_scan_scopes: List[str] = []

            for batch_start in range(0, len(ordered_indexes), max_items_per_run):
                if cancelled:
                    break
                batch_indexes = ordered_indexes[batch_start : batch_start + max_items_per_run]
                prepared: List[Dict[str, Any]] = []
                for index in batch_indexes:
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
                    options["force_media_folder"] = True
                    try:
                        target_cid = resolve_scraper_dest_folder_id(
                            provider,
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
                    source_entry = item.get("entry") if isinstance(item.get("entry"), dict) else {}
                    source_entry_name = str(source_entry.get("name", "") or "").strip()
                    season_pack = 0
                    if media_type == "tv" and bool(source_entry.get("is_dir")) and source_entry_name:
                        seasons = _scraper_season_pack_seasons(source_entry_name)
                        if len(seasons) > 1:
                            # 多季合集（S01-S03）暂不自动拆分，明确留在接收夹等人工处理，
                            # 避免继续走“整包 = 一个作品文件夹”的老逻辑反复报冲突。
                            left.append(
                                {
                                    "name": str(item.get("name", "") or ""),
                                    "reason_code": "multi_season_pack",
                                    "reason": (
                                        f"检测到多季合集（第{'、'.join(str(value) for value in seasons)}季），"
                                        "暂不支持自动拆分，请在刮削页手动整理"
                                    ),
                                }
                            )
                            continue
                        if seasons:
                            season_pack = seasons[0]
                    if bool(source_entry.get("is_dir")) and source_entry_name and not season_pack:
                        try:
                            existing_target_folder = scraper_service.find_scraper_media_folder(
                                provider,
                                target_cid,
                                source_entry_name,
                            )
                        except Exception:
                            existing_target_folder = {}
                        if existing_target_folder:
                            options["rename_selected_folders"] = False
                    prepared.append(
                        {
                            "index": index,
                            "item": item,
                            "candidate": candidate,
                            "media_type": media_type,
                            "target": target,
                            "target_cid": target_cid,
                            "options": options,
                            "source_entry_name": source_entry_name,
                            "season_pack": season_pack,
                        }
                    )
                if not prepared:
                    if cancelled:
                        break
                    if batch_start + max_items_per_run < len(ordered_indexes) and batch_pause_seconds > 0:
                        if _QUICK_IMPORT_CANCEL.wait(batch_pause_seconds):
                            cancelled = True
                            break
                    continue
                groups: Dict[Any, List[Dict[str, Any]]] = {}
                for prepared_item in prepared:
                    key = (
                        str(prepared_item["media_type"]),
                        str(prepared_item["target"].get("scan_path", "") or ""),
                        bool(prepared_item["options"].get("rename_selected_folders", True)),
                    )
                    groups.setdefault(key, []).append(prepared_item)
                for group in groups.values():
                    if cancelled:
                        break
                    group_indexes = [int(item["index"]) for item in group]
                    group_items = [items_by_index[index] for index in group_indexes if index in items_by_index]
                    group_picked = {index: picked[index] for index in group_indexes if index in picked}
                    if not group_items or not group_picked:
                        continue
                    group_options = dict(group[0]["options"])
                    plan = build_scraper_plan_for_batch(
                        provider,
                        group_items,
                        group_picked,
                        group_options,
                        base_cid=base_cid,
                        base_path=base_rel,
                        item_indexes=set(group_indexes),
                    )
                    plan_items = plan.get("items") if isinstance(plan, dict) else []
                    plan_items = plan_items if isinstance(plan_items, list) else []
                    if not plan:
                        for prepared_item in group:
                            left.append(
                                {
                                    "name": str(prepared_item["item"].get("name", "") or ""),
                                    "reason_code": "plan_conflict",
                                    "reason": "无法生成整理计划",
                                }
                            )
                        continue
                    summary_by_index = {
                        max(0, parse_int(summary.get("item_index", 0), 0)): summary
                        for summary in plan_items
                        if isinstance(summary, dict)
                    }
                    # 同一批里某个条目冲突时只留它自己：它的动作不提交，其他条目照常整理分发。
                    blocked_reasons = _plan_blocked_item_reasons(plan)
                    for prepared_item in group:
                        reason = blocked_reasons.get(int(prepared_item["index"]))
                        if reason is None:
                            continue
                        left.append(
                            {
                                "name": str(prepared_item["item"].get("name", "") or ""),
                                "reason_code": "plan_conflict",
                                "reason": f"整理计划有冲突：{str(reason)[:120]}",
                            }
                        )
                    executable_actions = [
                        action
                        for action in (plan.get("actions") if isinstance(plan.get("actions"), list) else [])
                        if isinstance(action, dict)
                        and max(0, parse_int(action.get("item_index", 0), 0)) not in blocked_reasons
                    ]
                    group_plan = {**plan, "actions": executable_actions}
                    ready_count = sum(
                        1 for action in executable_actions if action.get("ready") and not action.get("issue")
                    )
                    group_plan["ready_count"] = ready_count
                    job_id = 0
                    if ready_count > 0:
                        try:
                            job = create_scraper_job_from_plan({"plan": group_plan})
                            job_id = max(0, parse_int(job.get("job_id", 0), 0))
                            if job_id > 0:
                                submit_scraper_job(job_id).result(timeout=QUICK_IMPORT_JOB_WAIT_SECONDS)
                                state = scraper_service.get_scraper_jobs_state(job_id=job_id)
                                jobs = state.get("jobs") if isinstance(state, dict) else []
                                actual = jobs[0] if isinstance(jobs, list) and jobs else {}
                                actual_status = str(actual.get("status", "") or "").strip()
                                if actual_status in {"failed", "partial", "rollback_failed"}:
                                    detail = str(actual.get("status_detail", "") or "整理动作未全部完成")
                                    for prepared_item in group:
                                        if int(prepared_item["index"]) in blocked_reasons:
                                            continue
                                        left.append(
                                            {
                                                "name": str(prepared_item["item"].get("name", "") or ""),
                                                "reason_code": "organize_failed",
                                                "reason": f"整理{('部分完成' if actual_status == 'partial' else '失败')}：{detail[:120]}",
                                            }
                                        )
                                    record_monitor_run_event(
                                        monitor_run_id,
                                        category="problem",
                                        operation="organize",
                                        status=actual_status or "failed",
                                        title=f"{len(group)} 个条目",
                                        detail={"scraper_job_id": job_id, "status": actual_status or "failed", "detail": detail},
                                    )
                                    continue
                                if actual_status == "completed":
                                    record_monitor_run_event(
                                        monitor_run_id,
                                        category="remote",
                                        operation="organize",
                                        status="completed",
                                        title=f"{max(0, len(group) - len(blocked_reasons))} 个条目",
                                        detail={
                                            "scraper_job_id": job_id,
                                            "succeeded_actions": int(actual.get("succeeded_actions", 0) or 0),
                                            "failed_actions": int(actual.get("failed_actions", 0) or 0),
                                        },
                                    )
                        except Exception as exc:
                            for prepared_item in group:
                                if int(prepared_item["index"]) in blocked_reasons:
                                    continue
                                left.append(
                                    {
                                        "name": str(prepared_item["item"].get("name", "") or ""),
                                        "reason_code": "organize_failed",
                                        "reason": f"整理失败：{str(exc)[:120]}",
                                    }
                                )
                            continue
                    # 先解析“整理后要搬运的文件夹”，再按文件夹 ID 去重搬运：
                    # 多个整季包会整理进同一个「片名 (年份)」文件夹，整包只搬一次；
                    # 重复搬运会把已经移走的空壳当成新条目再搬一遍。
                    resolved_items: List[Dict[str, Any]] = []
                    for prepared_item in group:
                        if _QUICK_IMPORT_CANCEL.is_set():
                            cancelled = True
                            break
                        index = int(prepared_item["index"])
                        if index in blocked_reasons:
                            # 这条自己冲突，已经记进「留在接收夹」；不要跟着本批一起整理分发。
                            continue
                        item = prepared_item["item"]
                        target = prepared_item["target"]
                        original_entry = item.get("entry") if isinstance(item.get("entry"), dict) else {}
                        summary = summary_by_index.get(index) or (plan_items[0] if len(plan_items) == 1 else {})
                        if not summary:
                            left.append(
                                {
                                    "name": str(item.get("name", "") or ""),
                                    "reason_code": "organize_failed",
                                    "reason": "整理计划缺少该条目，请人工确认",
                                }
                            )
                            continue
                        merged_into_folder = str(summary.get("merged_into_folder", "") or "").strip()
                        if merged_into_folder:
                            # 内容已经并进同一部影视的媒体文件夹、跟着那一条一起搬运：
                            # 这里不参与定位/分发，只把它留在列表里等分发阶段按顺序登记结果。
                            resolved_items.append(
                                {
                                    **prepared_item,
                                    "original_entry": original_entry,
                                    "merged_into_folder": merged_into_folder,
                                }
                            )
                            continue
                        season_pack = max(0, parse_int(prepared_item.get("season_pack", 0), 0))
                        # 整季包整理后生成的是新的「片名 (年份)」文件夹，不是原来的季包目录；
                        # 传空 entry 让定位逻辑按计划标题去找新文件夹。
                        entry = _resolve_entry_after_organize(
                            base_cid,
                            summary,
                            {} if season_pack else original_entry,
                            provider,
                        )
                        entry_id = str(entry.get("id", "") or "").strip()
                        if not entry_id:
                            left.append(
                                {
                                    "name": str(item.get("name", "") or ""),
                                    "reason_code": "organize_failed",
                                    "reason": (
                                        "整理后未能在接收夹内定位到剧集文件夹，请人工确认"
                                        if season_pack
                                        else "整理后未能在接收夹内定位到条目，请人工确认"
                                    ),
                                }
                            )
                            continue
                        entry_name = str(entry.get("name", "") or "").strip()
                        entry["parent_id"] = str(entry.get("parent_id", "") or base_cid).strip() or base_cid
                        entry["parent_path"] = base_rel
                        entry["path"] = normalize_relative_path(join_relative_path(base_rel, entry_name))
                        resolved_items.append(
                            {
                                **prepared_item,
                                "entry": entry,
                                "entry_id": entry_id,
                                "entry_name": entry_name,
                                "original_entry": original_entry,
                                "season_pack": season_pack,
                            }
                        )
                    if cancelled:
                        break
                    dispatch_results: Dict[str, Dict[str, Any]] = {}
                    for resolved in resolved_items:
                        if resolved.get("merged_into_folder"):
                            continue
                        entry_id = str(resolved["entry_id"])
                        if entry_id in dispatch_results:
                            continue
                        try:
                            dispatch_results[entry_id] = _dispatch_organized_entry(
                                resolved["entry"],
                                source_cid=base_cid,
                                source_rel=base_rel,
                                target_cid=str(resolved["target_cid"] or ""),
                                target_rel=resolved["target"]["scan_rel"],
                                job_id=job_id,
                                name_cache=dispatch_name_cache,
                                monitor_run_id=monitor_run_id,
                                provider=provider,
                            )
                        except Exception as exc:
                            dispatch_results[entry_id] = {"__dispatch_error__": str(exc)[:120]}
                    for resolved in resolved_items:
                        if _QUICK_IMPORT_CANCEL.is_set():
                            cancelled = True
                            break
                        if resolved.get("merged_into_folder"):
                            _record_merged_inbox_item(
                                pending_moved=pending_moved,
                                cleanup_leftovers=cleanup_leftovers,
                                prepared_item=resolved,
                                original_entry=resolved.get("original_entry")
                                if isinstance(resolved.get("original_entry"), dict)
                                else {},
                                merged_into_folder=str(resolved.get("merged_into_folder", "") or ""),
                                job_id=job_id,
                                base_cid=base_cid,
                                base_rel=base_rel,
                            )
                            continue
                        item = resolved["item"]
                        target = resolved["target"]
                        entry = resolved["entry"]
                        entry_name = str(resolved["entry_name"])
                        dispatch = dispatch_results.get(str(resolved["entry_id"])) or {}
                        if dispatch.get("__dispatch_error__"):
                            left.append(
                                {
                                    "name": str(item.get("name", "") or ""),
                                    "reason_code": "dispatch_failed",
                                    "reason": f"搬运失败：{str(dispatch.get('__dispatch_error__'))[:120]}",
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
                        cleanup_leftovers.extend(dispatch.get("cleanup_pending") or [])
                        if resolved["season_pack"]:
                            # 整季包目录里的内容已经按集搬进新剧集文件夹，源目录只剩空壳；
                            # 交给统一的残留清理，只有确实空了才删除。
                            original_entry = resolved["original_entry"]
                            source_entry_name = str(resolved.get("source_entry_name", "") or "")
                            cleanup_leftovers.append(
                                {
                                    "id": str(original_entry.get("id", "") or ""),
                                    "name": source_entry_name,
                                    "path": normalize_relative_path(
                                        str(original_entry.get("path", "") or join_relative_path(base_rel, source_entry_name))
                                    ),
                                    "parent_id": str(original_entry.get("parent_id", "") or base_cid),
                                }
                            )
                        scope_rel = _dispatch_scan_scope_rel(
                            str(target.get("scan_rel", "") or ""),
                            entry_name,
                            bool(entry.get("is_dir")),
                            dispatch,
                        )
                        if scope_rel and scope_rel not in dispatch_scan_scopes:
                            dispatch_scan_scopes.append(scope_rel)
                        candidate = resolved["candidate"]
                        source_entry_name = str(resolved.get("source_entry_name", "") or "")
                        is_ai = str(candidate.get("source") or "").strip() == "ai"
                        match_source = "AI 识别" if is_ai else "规则匹配"
                        confidence = max(0, int(candidate.get("ai_confidence") if is_ai else candidate.get("score") or 0))
                        match_reason = str(candidate.get("ai_reason") or "").strip() if is_ai else ""
                        tmdb_id = max(0, parse_int(candidate.get("id") or 0, 0))
                        identified_year = str(candidate.get("year") or "").strip()
                        source_entry_for_type = item.get("entry") if isinstance(item.get("entry"), dict) else {}
                        entry_type = "folder" if (
                            bool(source_entry_for_type.get("is_dir")) or bool(item.get("is_dir"))
                        ) else "file"
                        pending_moved.append(
                            {
                                "name": str(item.get("name", "") or ""),
                                "target_label": QUICK_IMPORT_TARGET_LABELS[resolved["media_type"]],
                                "target_path": str(target.get("scan_path", "") or ""),
                                "scope_rel": scope_rel,
                                "job_id": job_id,
                                "monitor_sync_events": int(dispatch.get("monitor_sync_events", 0) or 0),
                                "title": str(item.get("name", "") or ""),
                                "operation": "merge" if dispatch.get("merged") else "move",
                                "detail": {
                                    "step": "接收夹分发",
                                    "operation_label": "网盘合并" if dispatch.get("merged") else "网盘移动",
                                    "original_name": source_entry_name,
                                    "match_source": match_source,
                                    "confidence": confidence,
                                    "match_reason": match_reason,
                                    "tmdb_id": tmdb_id,
                                    "identified_year": identified_year,
                                    "entry_type": entry_type,
                                    "old_name": entry_name,
                                    "new_name": str(dispatch.get("target_folder", "") or entry_name),
                                    "old_path": normalize_relative_path(str(entry.get("path", "") or join_relative_path(base_rel, entry_name))),
                                    "new_path": normalize_relative_path(join_relative_path(
                                        str(target.get("scan_rel", "") or ""),
                                        str(dispatch.get("target_folder", "") or entry_name),
                                    )),
                                    "target": target.get("scan_rel", ""),
                                    "task_name": str(target.get("scan_path", "") or ""),
                                    "scraper_job_id": job_id,
                                    "monitor_sync_events": int(dispatch.get("monitor_sync_events", 0) or 0),
                                },
                            }
                        )
                if cancelled:
                    break
                if batch_start + max_items_per_run < len(ordered_indexes) and batch_pause_seconds > 0:
                    if _QUICK_IMPORT_CANCEL.wait(batch_pause_seconds):
                        cancelled = True
                        break

            run_id_by_scope = _queue_dispatch_child_runs(cfg, provider, dispatch_scan_scopes)
            for pending in pending_moved:
                child_run_id = run_id_by_scope.get(str(pending.get("scope_rel", "") or ""), "")
                detail = {**pending["detail"], "child_run_id": child_run_id}
                moved.append(
                    {
                        "name": pending["name"],
                        "target": pending["target_label"],
                        "task_name": pending["target_path"],
                        "job_id": pending["job_id"],
                        "run_id": child_run_id,
                        "monitor_sync_events": pending["monitor_sync_events"],
                    }
                )
                record_monitor_run_event(
                    monitor_run_id,
                    category="remote",
                    operation=pending["operation"],
                    status="completed",
                    title=pending["title"],
                    detail=detail,
                )

            handled_indexes = set(picked.keys()) if cancelled else set(processed_indexes)
            for index, item in items_by_index.items():
                if index in handled_indexes:
                    continue
                entry = item.get("entry") if isinstance(item.get("entry"), dict) else {}
                if bool(entry.get("is_dir")) and str(entry.get("id", "") or "").strip():
                    if not _folder_contains_files(
                        str(entry.get("id", "") or ""),
                        str(entry.get("path", "") or ""),
                        provider=provider,
                    ):
                        # 整理残留的空壳目录（内容已经搬走）：直接清掉，不再报“识别失败、留在接收夹”。
                        try:
                            scraper_service.delete_scraper_entries(
                                provider,
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
                for leftover in _retry_inbox_cleanup(
                    cleanup_leftovers,
                    monitor_run_id=monitor_run_id,
                    provider=provider,
                ):
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
