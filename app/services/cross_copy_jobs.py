"""跨盘复制任务（#9 任务接入）。

独立任务表 cross_copy_jobs（与 resource_jobs / scraper_jobs 同模式），
复用任务中心的展示 / 取消 / 重试框架，不破坏资源导入链路。

生命周期：pending → running → completed / failed / cancelled / skipped
- 排队：全局同时只跑 MAX_CONCURRENT_JOBS 个任务，其余 pending 排 FIFO 队列
- 取消：内存取消集合 + DB 状态双保险；取消后不自动重试（显式 retry 才重来）
- 重试：整任务重来；失败/取消/服务重启后保留本地断点（暂存数据 + 115 上传
  会话，见 cross_copy_resume），重试与 requeue 走同一入口自动继承
- 启动恢复：把残留的 running/pending 任务重新入队（防重启丢任务）
"""

import asyncio
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

from ..background import submit_background
from ..core import get_config, safe_json_dumps, safe_json_loads
from ..db import db_connection, ensure_db, now_text, sqlite_row_to_dict
from ..providers.registry import get_or_none as _get_provider_or_none
from ..providers.registry import label_for as _provider_label
from . import cross_cloud_copy as xcc
from . import cross_cloud_copy_folder as xccf
from .cross_copy_resume import (
    build_resume_state,
    clear_resume_state,
    new_resume_skeleton,
    prune_resume_for_missing_files,
    resume_state_for_db,
    resume_state_is_inheritable,
)
from .notify import (
    _send_notify_content,
    build_notify_runtime_config,
    notify_channel_ready,
)

logger = logging.getLogger(__name__)

# 取消请求集合（与 resource_jobs 的取消机制同模式）
_cancel_requested: set = set()
_cancel_lock = threading.Lock()

# 单个任务的文件级进度（内存，任务结束即弃）
_job_progress: Dict[int, Dict[str, Any]] = {}
_progress_lock = threading.Lock()
# 文件夹任务当前处理到第几个文件（「文件 3/12」），随进度一起写进 status_detail
_job_detail: Dict[int, str] = {}
# 进度写库节流：内存每块都更新，DB 最多 ~1 秒一次（2.6GB 会有数千次回调）
_PROGRESS_DB_MIN_INTERVAL = 0.8
_last_db_progress: Dict[int, float] = {}

# 断点续传状态写库节流：引擎每完成一段下载 / 一个上传分片就地更新 resume 并
# 触发 on_resume_update，DB 最多 ~1 秒一次（与进度节流同思路）；终态由失败 /
# 取消分支无条件保底写一次（_persist_final_resume）。
_RESUME_DB_MIN_INTERVAL = 1.0
_last_resume_persist: Dict[int, float] = {}

# 失败/取消且本次保留了断点时追加的文案（设计文档 §3.2）
_RESUME_KEPT_SUFFIX = "（已保留断点，重试可续传）"

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
STATUS_SKIPPED = "skipped"

ACTIVE_STATUSES = {STATUS_PENDING, STATUS_RUNNING}

# 已结束的状态：这些任务不会再被调度，记录可以删。
# 注意和 resource_jobs 的「结束」不同——跨盘复制多了「已取消」「已跳过」两种
# 收口，它们同样是终态，清记录时必须一起收，否则用户会觉得"清不干净"。
TERMINAL_STATUSES = {STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED, STATUS_SKIPPED}

# 自动清理：每种收口最多留多少条。手动清空才是主入口，这里只防无限增长。
# 数字偏大是有意的——任务记录占的空间很小，而用户回查"上周那个文件到底复制成功没"
# 往往要翻很久。
HISTORY_KEEP_COMPLETED = 500
HISTORY_KEEP_FAILED = 500

# 全局并发上限：同时执行的跨盘复制任务数。
# 单个任务内部已经按 Range 分段并发下载，2 个并行基本能跑满带宽；
# 再多只会互相抢带宽，还会把 115 秒传 / 夸克取链打出 405 与风控。
DEFAULT_MAX_CONCURRENT = 2
MAX_CONCURRENT_HARD_LIMIT = 8


def _resolve_max_concurrent() -> int:
    """读 CROSS_COPY_MAX_CONCURRENT（1~8），没填或填了非法值都回落默认 2。"""
    raw = str(os.environ.get("CROSS_COPY_MAX_CONCURRENT", "") or "").strip()
    if not raw:
        return DEFAULT_MAX_CONCURRENT
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_MAX_CONCURRENT
    if value < 1 or value > MAX_CONCURRENT_HARD_LIMIT:
        return DEFAULT_MAX_CONCURRENT
    return value


MAX_CONCURRENT_JOBS = _resolve_max_concurrent()

# 排队状态（进程内）：_queued 是按入队顺序等待的任务，_active 是已经占住名额的。
# 用 threading.Lock 而不是 asyncio 原语：submit 可能从线程池里调用
# （订阅补源走 asyncio.to_thread），锁必须能跨线程用。
_queued: List[int] = []
_active: set = set()
_sched_lock = threading.Lock()

# 防重复执行（同一个 job 不会被两个协程同时跑）
_running: set = set()
_running_lock = threading.Lock()


def _normalize_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    return status if status in {
        STATUS_PENDING,
        STATUS_RUNNING,
        STATUS_COMPLETED,
        STATUS_FAILED,
        STATUS_CANCELLED,
        STATUS_SKIPPED,
    } else STATUS_PENDING


def create_cross_copy_job(
    *,
    title: str,
    source_provider: str,
    target_provider: str,
    source_file_id: str,
    target_dir_id: str = "",
    target_savepath: str = "",
    source_path: str = "",
    target_path: str = "",
    filename: str = "",
    file_size: int = 0,
    source_mode: str = "direct",
    source_share_url: str = "",
    origin: str = "manual",
    origin_ref: str = "",
    source_is_dir: bool = False,
) -> int:
    """创建跨盘复制任务，返回 job_id。

    source_path / target_path 是「网盘内路径」（不带网盘名），用于任务卡片展示
    "源文件在哪、会被放到哪"；传空则由 target_savepath + filename 兜底拼。

    source_is_dir 为真表示 source_file_id 指向一个文件夹：任务内部会列出
    整个文件夹再逐个文件复制（一个任务 = 一个文件夹）。
    """
    ensure_db()
    now = now_text()
    resolved_target_path = str(target_path or "").strip() or _join_pan_path(target_savepath, filename)
    params = (
        str(title or "").strip()[:200],
        str(source_provider or "").strip(),
        str(target_provider or "").strip(),
        str(source_file_id or "").strip(),
        str(source_mode or "direct").strip() or "direct",
        str(target_dir_id or "").strip(),
        str(target_savepath or "").strip()[:500],
        str(source_path or "").strip()[:1000],
        resolved_target_path[:1000],
        str(filename or "").strip()[:300],
        int(file_size or 0),
        STATUS_PENDING,
        "排队中",
        str(origin or "manual").strip(),
        str(origin_ref or "").strip()[:200],
        str(source_share_url or "").strip()[:1000],
        1 if source_is_dir else 0,
        now,
        now,
    )
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO cross_copy_jobs(
                title, source_provider, target_provider, source_file_id, source_mode,
                target_dir_id, target_savepath, source_path, target_path, filename, file_size,
                status, status_detail, origin, origin_ref, source_share_url, source_is_dir,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            params,
        )
        job_id = int(cursor.lastrowid)
        conn.commit()
    return job_id


def _attach_progress(job: Dict[str, Any]) -> Dict[str, Any]:
    """把内存里的实时进度（含已下载字节与速度）挂到任务字典上。"""
    try:
        job_id = int(job.get("id") or 0)
    except (TypeError, ValueError):
        job_id = 0
    with _progress_lock:
        job["progress"] = dict(_job_progress.get(job_id, {})) if job_id else {}
    return job


def _decode_resume_json(raw: Any) -> Dict[str, Any]:
    """把 resume_json 列解析成断点续传状态字典。

    损坏 / 非对象 JSON（老库默认 '{}'、手改坏的值）一律按「无断点」处理，
    宁可重传也不能拿着错状态续传。
    """
    value = safe_json_loads(raw, {})
    return value if isinstance(value, dict) else {}


def get_cross_copy_job(job_id: int) -> Optional[Dict[str, Any]]:
    ensure_db()
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM cross_copy_jobs WHERE id = ?", (int(job_id),))
        row = cursor.fetchone()
    if not row:
        return None
    job = sqlite_row_to_dict(row)
    job["result"] = safe_json_loads(job.get("result_json"), {})
    job["resume"] = _decode_resume_json(job.get("resume_json"))
    return _attach_progress(job)


def list_cross_copy_jobs(limit: int = 50, status: str = "") -> List[Dict[str, Any]]:
    ensure_db()
    clauses = []
    params: List[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(_normalize_status(status))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(int(limit))
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT * FROM cross_copy_jobs {where} ORDER BY id DESC LIMIT ?",
            params,
        )
        rows = cursor.fetchall()
    jobs = []
    for row in rows:
        job = sqlite_row_to_dict(row)
        job["result"] = safe_json_loads(job.get("result_json"), {})
        job["resume"] = _decode_resume_json(job.get("resume_json"))
        jobs.append(_attach_progress(job))
    return jobs


def get_cross_copy_job_counts() -> Dict[str, int]:
    """按状态统计任务数（任务中心「清空」菜单的角标与可用性都靠它）。

    列表接口只返回最近 N 条，而清空要清的是整表，两个数字对不上用户会以为
    "明明还有记录却清不掉"，所以计数单独查一次全表。
    """
    ensure_db()
    counts: Dict[str, int] = {
        STATUS_PENDING: 0,
        STATUS_RUNNING: 0,
        STATUS_COMPLETED: 0,
        STATUS_FAILED: 0,
        STATUS_CANCELLED: 0,
        STATUS_SKIPPED: 0,
    }
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status, COUNT(*) FROM cross_copy_jobs GROUP BY status")
        rows = cursor.fetchall()
    total = 0
    for row in rows:
        status = _normalize_status(row[0])
        count = int(row[1] or 0)
        counts[status] = counts.get(status, 0) + count
        total += count
    counts["total"] = total
    counts["active"] = counts[STATUS_PENDING] + counts[STATUS_RUNNING]
    counts["terminal"] = sum(counts[status] for status in TERMINAL_STATUSES)
    return counts


def _clear_scope_statuses(scope: str) -> List[str]:
    """把前端传来的清理范围翻译成状态列表。

    - ``completed`` 只清成功的
    - ``failed`` 只清失败的
    - ``terminal``（默认）清所有已结束的：成功 + 失败 + 已取消 + 已跳过
    """
    normalized = str(scope or "").strip().lower()
    if normalized == "completed":
        return [STATUS_COMPLETED]
    if normalized == "failed":
        return [STATUS_FAILED]
    return [STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED, STATUS_SKIPPED]


def clear_cross_copy_jobs(scope: str = "terminal") -> Dict[str, Any]:
    """批量清除已结束的任务记录（只删记录，不碰网盘文件、不中断在跑的任务）。"""
    target_statuses = _clear_scope_statuses(scope)
    ensure_db()
    placeholders = ",".join(["?"] * len(target_statuses))
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT id, resume_json FROM cross_copy_jobs WHERE status IN ({placeholders})",
            tuple(target_statuses),
        )
        removed = cursor.fetchall()
        removed_ids = [int(row[0]) for row in removed if row and row[0] is not None]
        cursor.execute(
            f"DELETE FROM cross_copy_jobs WHERE status IN ({placeholders})",
            tuple(target_statuses),
        )
        deleted = int(cursor.rowcount or 0)
        conn.commit()
    for job_id in removed_ids:
        _clear_job_progress(job_id)
    # 断点临时文件没人再认领，顺手删掉（失败仅日志，不阻塞清记录）
    for row in removed:
        _remove_resume_temp_file(row[1] if len(row) > 1 else "")
    return {
        "scope": "completed" if target_statuses == [STATUS_COMPLETED] else (
            "failed" if target_statuses == [STATUS_FAILED] else "terminal"
        ),
        "statuses": target_statuses,
        "deleted": deleted,
    }


def _remove_resume_temp_file(raw_resume: Any) -> None:
    """尽力删掉断点状态里的本地临时文件（删任务记录时联动；失败仅日志）。

    红线不变：只删自己暂存的 xcopy-*.part，绝不碰任何网盘文件。
    """
    state = _decode_resume_json(raw_resume)
    temp_path = str(state.get("temp_path") or "").strip()
    if not temp_path:
        return
    try:
        os.remove(temp_path)
    except OSError as exc:
        logger.info("cross-copy resume temp file removal skipped: %s (%s)", temp_path, exc)


def delete_cross_copy_job(job_id: int) -> Dict[str, Any]:
    """删除单条任务记录（只允许已结束的任务）。"""
    job_id = int(job_id)
    ensure_db()
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT status, resume_json FROM cross_copy_jobs WHERE id = ?", (job_id,)
        )
        row = cursor.fetchone()
        if not row:
            return {"ok": False, "msg": "任务不存在"}
        status = _normalize_status(row[0])
        if status not in TERMINAL_STATUSES:
            return {"ok": False, "msg": "任务还在进行中，请先取消再删除记录"}
        cursor.execute(
            "DELETE FROM cross_copy_jobs WHERE id = ? AND status = ?",
            (job_id, status),
        )
        deleted = int(cursor.rowcount or 0)
        conn.commit()
    if deleted:
        _clear_job_progress(job_id)
        # 断点临时文件没人再认领，顺手删掉（失败仅日志，不阻塞删记录）
        _remove_resume_temp_file(row[1] if len(row) > 1 else "")
    return {"ok": bool(deleted), "job_id": job_id, "deleted": deleted, "msg": "已删除" if deleted else "任务状态已变化，请刷新后重试"}


def prune_cross_copy_job_history(
    completed_keep: int = HISTORY_KEEP_COMPLETED,
    failed_keep: int = HISTORY_KEEP_FAILED,
) -> Dict[str, int]:
    """自动清理老记录：每组只保留最近 N 条（手动清空之外的最后一道闸）。

    分组口径和「清空」菜单一致：成功一组，失败 + 已取消 + 已跳过一组。
    跑在启动与定时任务里，删除量通常是 0，失败也只记日志不影响主流程。
    """
    completed_keep = max(50, min(10000, int(completed_keep or HISTORY_KEEP_COMPLETED)))
    failed_keep = max(50, min(10000, int(failed_keep or HISTORY_KEEP_FAILED)))
    groups = {
        "completed": ([STATUS_COMPLETED], completed_keep),
        "failed": ([STATUS_FAILED, STATUS_CANCELLED, STATUS_SKIPPED], failed_keep),
    }
    ensure_db()
    deleted: Dict[str, int] = {}
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            for label, (statuses, keep) in groups.items():
                placeholders = ",".join(["?"] * len(statuses))
                cursor.execute(
                    f"""
                    DELETE FROM cross_copy_jobs
                    WHERE status IN ({placeholders})
                      AND id NOT IN (
                        SELECT id FROM cross_copy_jobs
                        WHERE status IN ({placeholders})
                        ORDER BY id DESC
                        LIMIT ?
                      )
                    """,
                    tuple(statuses) + tuple(statuses) + (keep,),
                )
                deleted[label] = int(cursor.rowcount or 0)
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - 清理失败不影响任务执行
        logger.warning("cross-copy job history prune skipped: %s", exc)
        return {"completed": 0, "failed": 0, "deleted": 0}
    return {
        "completed": deleted.get("completed", 0),
        "failed": deleted.get("failed", 0),
        "deleted": sum(deleted.values()),
    }


def update_cross_copy_job(job_id: int, **fields: Any) -> None:
    if not fields:
        return
    ensure_db()
    payload = dict(fields)
    if "result" in payload and isinstance(payload["result"], dict):
        payload["result_json"] = safe_json_dumps(payload.pop("result"))
    if "resume" in payload:
        # 断点续传状态：调用方传 dict，落库 json；非 dict（None 等）按「清空断点」处理。
        # 先过 resume_state_for_db：引擎挂进上传会话的 on_part_done 是闭包，
        # 不过滤会让 json.dumps 抛 TypeError 被本函数上层的 try/except 吞掉，
        # 断点状态静默停在旧值（重启后续传全丢）。
        resume_value = payload.pop("resume")
        payload["resume_json"] = safe_json_dumps(
            resume_state_for_db(resume_value) if isinstance(resume_value, dict) else {}
        )
    if "status" in payload:
        payload["status"] = _normalize_status(payload["status"])
    payload["updated_at"] = now_text()
    sets = ", ".join(f"{key} = ?" for key in payload.keys())
    values = list(payload.values()) + [int(job_id)]
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"UPDATE cross_copy_jobs SET {sets} WHERE id = ?", values)
        conn.commit()


def cancel_cross_copy_job(job_id: int) -> Dict[str, Any]:
    """请求取消；已在运行的任务在下个检查点退出，未开始的直接标记 cancelled。"""
    job_id = int(job_id)
    job = get_cross_copy_job(job_id)
    if not job:
        return {"ok": False, "msg": "任务不存在"}
    status = _normalize_status(job.get("status"))
    if status not in ACTIVE_STATUSES:
        return {"ok": False, "msg": f"任务已结束（{status}），无需取消"}
    with _cancel_lock:
        _cancel_requested.add(job_id)
    if status == STATUS_PENDING:
        # 还在排队：直接从队列摘掉，别让空出来的名额把它捡起来
        _discard_from_queue(job_id)
        _finalize_cancelled(job_id, "已取消（尚未开始）")
    return {"ok": True, "msg": "已请求取消"}


def _finalize_cancelled(job_id: int, detail: str, resume_state: Optional[Dict[str, Any]] = None) -> None:
    if resume_state_is_inheritable(resume_state):
        # 本次运行确有断点被保留：保底落库 + 文案告诉用户可以重试续传
        _persist_final_resume(job_id, resume_state)
        detail = f"{detail}{_RESUME_KEPT_SUFFIX}"
    update_cross_copy_job(
        job_id,
        status=STATUS_CANCELLED,
        status_detail=detail,
        finished_at=now_text(),
    )
    _clear_job_progress(job_id)


def retry_cross_copy_job(job_id: int) -> Dict[str, Any]:
    """重试：整任务重来（清空结果与错误，回到 pending）。"""
    job_id = int(job_id)
    job = get_cross_copy_job(job_id)
    if not job:
        return {"ok": False, "msg": "任务不存在"}
    status = _normalize_status(job.get("status"))
    if status in ACTIVE_STATUSES:
        return {"ok": False, "msg": "任务进行中，无法重试"}
    with _cancel_lock:
        _cancel_requested.discard(job_id)
    update_cross_copy_job(
        job_id,
        status=STATUS_PENDING,
        status_detail="等待重试",
        error_message="",
        result={},
        progress_percent=0,
        phase="",
        retry_count=int(job.get("retry_count", 0) or 0) + 1,
        started_at="",
        finished_at="",
        # 重试会按原名重新上传，之前那次整理的结果作废，成功后重新标记
        organize_state="",
        organize_detail="",
        # 进度回写同理：上次的回写结果作废，这次成功后重新算一遍
        progress_state="",
        progress_detail="",
    )
    submit_cross_copy_job(job_id)
    return {"ok": True, "msg": "已重新入队"}


def submit_cross_copy_job(job_id: int) -> None:
    """把任务放进等待队列并触发调度。

    这里只负责「排队 + 叫一声调度器」，真正能不能开跑由全局并发上限决定；
    队列里的任务不占名额，所以粘 20 个文件不会同时起 20 个下载线程。
    """
    job_id = int(job_id)
    with _sched_lock:
        if job_id in _active or job_id in _queued:
            return
        _queued.append(job_id)
    _schedule()


def _schedule() -> None:
    """有空闲名额就按 FIFO 拉起排队任务。

    名额在「派发」这一刻就记进 _active，任务结束时由 run_cross_copy_job 的
    finally 归还。派发本身失败（后台运行器起不来）也必须把名额还回去，
    否则一个卡住的派发就能把整个队列永久堵死。
    """
    while True:
        with _sched_lock:
            if not _queued or len(_active) >= MAX_CONCURRENT_JOBS:
                break
            job_id = _queued.pop(0)
            _active.add(job_id)
        try:
            submit_background(run_cross_copy_job, job_id, label=f"cross-copy-job-{job_id}")
        except Exception as exc:  # noqa: BLE001 - 起不来也要还名额，别拖死队列
            logger.exception("cross-copy job %s submit failed", job_id)
            _release_slot(job_id)
            _fail_job(job_id, f"任务启动失败：{exc}")
    _refresh_queue_details()


def _release_slot(job_id: int) -> None:
    """归还并发名额。必须在 finally 里调用，漏一次就少一个坑位。"""
    with _sched_lock:
        _active.discard(int(job_id))


def _refresh_queue_details() -> None:
    """把「前面还有几个任务」写回排队中的任务，让用户看到真实位置。"""
    with _sched_lock:
        waiting = list(_queued)
        ahead_base = len(_active)
    try:
        for index, job_id in enumerate(waiting):
            update_cross_copy_job(job_id, status_detail=_queue_waiting_detail(ahead_base + index))
    except Exception as exc:  # noqa: BLE001 - 文案写不进去不影响调度
        logger.info("cross-copy queue detail refresh skipped: %s", exc)


def _queue_waiting_detail(ahead: int) -> str:
    return f"排队中：前面还有 {max(0, int(ahead))} 个任务"


def _discard_from_queue(job_id: int) -> None:
    """把任务从等待队列里摘掉（取消用），别让后面的空闲名额把它捡起来跑。"""
    job_id = int(job_id)
    with _sched_lock:
        try:
            _queued.remove(job_id)
        except ValueError:
            pass


def _clear_job_progress(job_id: int) -> None:
    with _progress_lock:
        _job_progress.pop(int(job_id), None)
        _last_db_progress.pop(int(job_id), None)
        _last_resume_persist.pop(int(job_id), None)
        _job_detail.pop(int(job_id), None)


def _make_resume_persister(job_id: int, state: Dict[str, Any]):
    """构造 on_resume_update 回调：把引擎就地更新的断点状态节流落库。

    引擎传回的 snapshot 与闭包持有的 state 是同一个对象（就地更新契约），
    优先用传入的快照。写库失败只记日志——后续回调还会把最新状态带过来。
    """
    job_id = int(job_id)

    def _persist(snapshot: Any = None) -> None:
        current = snapshot if isinstance(snapshot, dict) else state
        if not isinstance(current, dict) or not current:
            return
        now = time.monotonic()
        with _progress_lock:
            # 「从未写过」必须用 None 哨兵，不能图省事用 0：monotonic 时钟
            # 在刚启动的环境里可能小于节流阈值（实测 0.8s < 1.0s），用 0
            # 会把首次写库误吞——断点状态迟迟不落库，重启后续传全丢。
            last_persist = _last_resume_persist.get(job_id)
            if last_persist is not None and now - last_persist < _RESUME_DB_MIN_INTERVAL:
                return
            _last_resume_persist[job_id] = now
        try:
            update_cross_copy_job(job_id, resume=current)
        except Exception as exc:  # noqa: BLE001 - 落库失败不影响复制主流程
            logger.info("cross-copy resume persist skipped (job=%s): %s", job_id, exc)

    return _persist


def _persist_final_resume(job_id: int, resume_state: Optional[Dict[str, Any]]) -> None:
    """终态保底：把已知的最新断点状态无条件写库（on_resume_update 是节流的）。"""
    if not isinstance(resume_state, dict) or not resume_state:
        return
    try:
        update_cross_copy_job(job_id, resume=resume_state)
    except Exception as exc:  # noqa: BLE001 - 保底写失败只记日志
        # warning 级别：这是失败/取消路径上最后一次写库机会，吞了就意味着
        # 本次的断点白留了，用户侧不该毫无痕迹
        logger.warning("cross-copy final resume persist skipped (job=%s): %s", job_id, exc)


def format_transfer_size(value: Any) -> str:
    """字节数转人话（1.24GB / 860MB），任务卡片与状态明细共用。"""
    try:
        size = float(value or 0)
    except (TypeError, ValueError):
        size = 0.0
    if size <= 0:
        return "0B"
    units = ["B", "KB", "MB", "GB", "TB"]
    unit = 0
    while size >= 1024 and unit < len(units) - 1:
        size /= 1024.0
        unit += 1
    if unit == 0:
        return f"{int(size)}B"
    return f"{size:.2f}{units[unit]}" if size < 100 else f"{size:.1f}{units[unit]}"


def _join_pan_path(*parts: Any) -> str:
    """把网盘目录与文件名拼成「/目录/文件」形式的展示路径。"""
    segments: List[str] = []
    for part in parts:
        text = str(part or "").strip().strip("/")
        if text:
            segments.append(text)
    return "/" + "/".join(segments) if segments else ""


def _report_progress(job_id: int, sent: int, total: int, phase: str, detail: str = "") -> None:
    """记录传输进度：已完成字节、总字节、实时速度（滑动平均）。

    速度只在同一阶段内累计；阶段切换（下载 → 上传）或进度回退时重新起算，
    避免把下载速度带进上传阶段。

    detail 用于文件夹任务的「文件 3/12」这类过程文案，会一起写进 status_detail。
    """
    job_id = int(job_id)
    now = time.monotonic()
    sent = max(0, int(sent or 0))
    total = int(total or 0)
    phase = str(phase or "").strip() or "download"
    percent = 0
    if total > 0:
        percent = max(0, min(100, int(sent * 100 / total)))
    phase_label = {
        "download": "下载",
        "upload": "上传",
    }.get(phase, phase)

    with _progress_lock:
        if detail:
            _job_detail[job_id] = str(detail or "").strip()
        detail_text = str(_job_detail.get(job_id, "") or "").strip()
        prev = _job_progress.get(job_id) or {}
        try:
            prev_ts = float(prev.get("updated_ts") or 0)
            prev_sent = int(prev.get("sent") or 0)
            prev_speed = float(prev.get("speed") or 0)
        except (TypeError, ValueError):
            prev_ts, prev_sent, prev_speed = 0.0, 0, 0.0
        speed = 0.0
        # 用「有没有上一帧」判断，而不是 prev_ts > 0：monotonic 的原点不固定
        # （容器/短命进程里可能从 0 附近开始），拿 0 当哨兵会把合法的时间戳判成缺失。
        if prev and now > prev_ts and str(prev.get("phase") or "") == phase and sent >= prev_sent:
            instant = (sent - prev_sent) / (now - prev_ts)
            speed = prev_speed * 0.6 + instant * 0.4 if prev_speed > 0 else instant
        _job_progress[job_id] = {
            "phase": phase,
            "sent": sent,
            "total": total,
            "percent": percent,
            "speed": int(round(speed)),
            "updated_ts": now,
        }
        last_persist = float(_last_db_progress.get(job_id) or 0)
        finished_transfer = total > 0 and sent >= total
        should_persist = finished_transfer or (now - last_persist) >= _PROGRESS_DB_MIN_INTERVAL
        if should_persist:
            _last_db_progress[job_id] = now

    if not should_persist:
        return

    parts = [f"{phase_label} {percent}%"]
    if detail_text:
        parts.insert(0, detail_text)
    if total > 0:
        parts.append(f"{format_transfer_size(sent)} / {format_transfer_size(total)}")
    if speed > 0:
        parts.append(f"{format_transfer_size(speed)}/s")
    update_cross_copy_job(
        job_id,
        progress_percent=percent,
        phase=phase,
        status_detail=" · ".join(parts),
    )


def _report_file_detail(job_id: int, detail: str) -> None:
    """记录文件夹任务的过程文案（「文件 3/12」），并（受节流）立刻写进任务状态。

    文件夹任务每个文件只产生几次字节进度回调，若只靠进度回调带出文案，
    小文件会一直看不到「第几个」；这里单独落一次状态，写库频率与进度同节流。
    """
    job_id = int(job_id)
    text = str(detail or "").strip()
    if not text:
        return
    now = time.monotonic()
    with _progress_lock:
        _job_detail[job_id] = text
        entry = _job_progress.get(job_id)
        if isinstance(entry, dict):
            entry["detail"] = text
        last_persist = float(_last_db_progress.get(job_id) or 0)
        should_persist = (now - last_persist) >= _PROGRESS_DB_MIN_INTERVAL
        if should_persist:
            _last_db_progress[job_id] = now
    if should_persist:
        update_cross_copy_job(job_id, status_detail=text)


def _is_cancel_requested(job_id: int) -> bool:
    with _cancel_lock:
        return int(job_id) in _cancel_requested


async def run_cross_copy_job(job_id: int) -> None:
    """执行单个跨盘复制任务（进度/取消/通知/状态收口）。"""
    job_id = int(job_id)
    # 断点续传状态（单文件分支赋值）：失败/取消的 except 要靠它决定是否保底落库
    resume_state: Optional[Dict[str, Any]] = None
    with _running_lock:
        if job_id in _running:
            return
        _running.add(job_id)
    try:
        job = get_cross_copy_job(job_id)
        if not job:
            return
        status = _normalize_status(job.get("status"))
        if status not in ACTIVE_STATUSES:
            return
        if _is_cancel_requested(job_id):
            _finalize_cancelled(job_id, "已取消（尚未开始）")
            return

        update_cross_copy_job(job_id, status=STATUS_RUNNING, status_detail="准备中", started_at=now_text())
        cfg = get_config()
        source_name = str(job.get("source_provider", "") or "").strip()
        target_name = str(job.get("target_provider", "") or "").strip()
        source_provider = _get_provider_or_none(source_name)
        target_provider = _get_provider_or_none(target_name)
        if source_provider is None or target_provider is None:
            raise xcc.CrossCloudCopyError("复制源或目标网盘未注册")
        if not getattr(target_provider, "supports_upload", False):
            raise xcc.CrossCloudCopyError(
                f"{getattr(target_provider, 'label', target_name) or '目标网盘'} 暂不支持上传"
            )
        if source_name == target_name:
            raise xcc.CrossCloudCopyError("复制源与目标不能是同一个网盘")

        source_cookie = source_provider.get_cookie(cfg)
        target_cookie = target_provider.get_cookie(cfg)
        if not source_cookie:
            raise xcc.CrossCloudCopyError(f"请先在参数配置中填写{source_provider.label}认证信息")
        if not target_cookie:
            raise xcc.CrossCloudCopyError(f"请先在参数配置中填写{target_provider.label}认证信息")

        # 订阅补源这类调用只给了「保存到哪个路径」，没给目录 id。这里必须先把路径
        # 换成真实目录 id，否则上传会落到根目录（看起来成功，其实存错地方）。
        job = _ensure_target_dir_id(job, target_provider, target_cookie)

        update_cross_copy_job(job_id, status_detail="开始复制")
        if not str(job.get("target_path", "") or "").strip():
            early_target_path = _join_pan_path(job.get("target_savepath"), job.get("filename"))
            if early_target_path:
                job["target_path"] = early_target_path
                update_cross_copy_job(job_id, target_path=early_target_path)

        # 源是文件夹：整个文件夹一个任务，内部逐个文件复制。
        # 文件夹分支显式不传 resume：check_existing 已跳过目标端已存在的文件，
        # 进行中的那个文件重新下载，不做 per-file 断点（设计文档 §5.3）。
        if _job_source_is_dir(job):
            folder_result = await asyncio.to_thread(
                xccf.copy_folder_across_clouds,
                source_provider=source_provider,
                source_cookie=source_cookie,
                source_folder_id=str(job.get("source_file_id", "") or ""),
                target_provider=target_provider,
                target_cookie=target_cookie,
                target_dir_id=str(job.get("target_dir_id", "") or ""),
                target_folder_name=str(job.get("filename", "") or ""),
                temp_dir=xcc.resolve_temp_dir(cfg, create=True),
                progress_cb=lambda sent, total, phase: _report_progress(job_id, sent, total, phase),
                cancel_check=lambda: _is_cancel_requested(job_id),
                check_existing=True,
                cfg=cfg,
                status_cb=lambda detail: _report_file_detail(job_id, detail),
            )
            _finish_folder_job(job_id, job, cfg, folder_result)
            return

        # 断点续传：先尝试继承上次失败/取消/服务重启留下的本地已下载数据与
        # 115 上传会话（校验在 build_resume_state：临时文件还在、前缀完整、
        # 源端哈希没变）。没有可继承断点时也必须传一个空骨架——否则本次运行
        # 失败时留下的临时文件没有任何状态指向它，重试接不上，续传链永远
        # 走不到第二步。骨架由引擎边下边填，任务层落库。
        resume_state = await asyncio.to_thread(build_resume_state, job, cfg)
        if resume_state is None:
            resume_state = new_resume_skeleton(job)
        resume_persister = _make_resume_persister(job_id, resume_state)
        result = await asyncio.to_thread(
            xcc.copy_file_across_clouds,
            source_provider=source_provider,
            source_cookie=source_cookie,
            source_file_id=str(job.get("source_file_id", "") or ""),
            target_provider=target_provider,
            target_cookie=target_cookie,
            target_dir_id=str(job.get("target_dir_id", "") or ""),
            filename=str(job.get("filename", "") or ""),
            size=int(job.get("file_size", 0) or 0),
            temp_dir=xcc.resolve_temp_dir(cfg, create=True),
            progress_cb=lambda sent, total, phase: _report_progress(job_id, sent, total, phase),
            cancel_check=lambda: _is_cancel_requested(job_id),
            check_existing=True,
            cfg=cfg,
            resume=resume_state,
            on_resume_update=resume_persister,
        )
        result_status = str(getattr(result, "status", "") or "uploaded")

        # 复制成功后按配置清理「订阅补源自己转存的中转副本」。
        # 只认 origin=subscription：手动复制的源文件是用户自己网盘里的原片，
        # 绝不能删（删了就是数据丢失）。文件夹任务一律不删源（这次只做复制）。
        job_origin = str(job.get("origin", "") or "").strip().lower()
        delete_source_after = bool(cfg.get("cross_copy_delete_source_after", True))
        if (
            job_origin == "subscription"
            and not _job_source_is_dir(job)
            and result_status in ("rapid", "uploaded")
            and delete_source_after
        ):
            try:
                _delete_source_file(source_provider, source_cookie, str(job.get("source_file_id", "") or ""))
            except Exception as exc:
                logger.info("cross-copy source cleanup failed (job=%s): %s", job_id, exc)

        final_status = STATUS_COMPLETED
        if result_status == "skipped":
            final_status = STATUS_SKIPPED
        # 终态干净：临时文件引擎已在成功路径删掉，断点状态一并清掉
        clear_resume_state(job_id)
        final_name = str(getattr(result, "name", "") or "").strip() or str(job.get("filename", "") or "").strip()
        final_target_path = _join_pan_path(job.get("target_savepath"), final_name) or str(
            job.get("target_path", "") or ""
        )
        base_detail = str(getattr(result, "message", "") or ("已完成" if final_status == STATUS_COMPLETED else "已跳过"))
        result_payload = result.to_dict() if hasattr(result, "to_dict") else {"status": result_status}
        note = _no_monitor_note(job.get("target_provider", ""))
        if note:
            # 结构化字段：前端只渲染 resultHint，光写 status_detail 用户看不到
            result_payload["no_monitor_note"] = note
        # 订阅补源的单文件任务成功后，文件还是分享里的原名（S01E42.mp4），跟订阅
        # 导入的「片名 (年份) - S01E42.mp4」不一致。这里只打一个「待整理」标记：
        # 改名要跑刮削任务（阻塞，最长几分钟），不能塞在这个收口里占死并发名额，
        # 由 subscription_cross_copy_organize 的定时器成组处理。
        finalize_fields: Dict[str, Any] = {}
        if (
            job_origin == "subscription"
            and not _job_source_is_dir(job)
            and final_status == STATUS_COMPLETED
        ):
            finalize_fields["organize_state"] = "pending"
        # 补源是旁路：订阅主流程注册完任务就结束了，复制跑完没人回写
        # subscription_task_state，界面上的「最近命中 / 追更进度」会一直停在上一次
        # 同盘导入的旧值。这里只打一个「待回写」标记，真正的写回交给
        # subscription_cross_copy_progress 的定时器成组做（一轮常补 3~5 集，
        # 逐条写会互相覆盖，也会把「这一轮补了哪些集」写散）。
        if job_origin == "subscription" and final_status == STATUS_COMPLETED:
            finalize_fields["progress_state"] = "pending"
        update_cross_copy_job(
            job_id,
            status=final_status,
            status_detail=base_detail + note,
            progress_percent=100,
            phase="done",
            finished_at=now_text(),
            filename=final_name or str(job.get("filename", "") or ""),
            target_path=final_target_path,
            result=result_payload,
            **finalize_fields,
        )
        _clear_job_progress(job_id)
        _push_cross_copy_notification(cfg, job, ok=True, message=str(getattr(result, "message", "") or ""))
    except xcc.CrossCloudCopyCancelled:
        _finalize_cancelled(job_id, "已取消", resume_state=resume_state)
    except xcc.CrossCloudCopyError as exc:
        _fail_job(job_id, str(exc), resume_state=resume_state)
    except Exception as exc:  # noqa: BLE001 - 兜底：任何异常都不能杀死任务循环
        logger.exception("cross-copy job %s crashed", job_id)
        _fail_job(job_id, f"复制失败：{exc}", resume_state=resume_state)
    finally:
        with _cancel_lock:
            _cancel_requested.discard(job_id)
        with _running_lock:
            _running.discard(job_id)
        # 无论成功/失败/取消/异常，都必须还名额并拉起下一个排队的任务
        _release_slot(job_id)
        _schedule()


def _ensure_target_dir_id(
    job: Dict[str, Any],
    target_provider,
    target_cookie: str,
) -> Dict[str, Any]:
    """补齐目标目录 id。

    两条入口给的字段不一样：界面上建任务的是「目录 id」，订阅补源给的是
    「保存到哪个路径」。后者如果不换成目录 id，上传会落到根目录——文件确实
    传上去了，但存错地方，用户很难发现。这里就地补一次并写回任务记录。

    解析失败不阻断：抛明确错误比悄悄传到根目录好。
    """
    existing = str(job.get("target_dir_id", "") or "").strip()
    if existing:
        return job
    savepath = str(job.get("target_savepath", "") or "").strip()
    if not savepath:
        return job
    resolver = getattr(target_provider, "ensure_folder_id_by_path", None)
    if not callable(resolver):
        raise xcc.CrossCloudCopyError(
            f"{getattr(target_provider, 'label', '目标网盘') or '目标网盘'} 无法按路径定位保存目录"
        )
    try:
        resolved = str(resolver(target_cookie, savepath) or "").strip()
    except Exception as exc:  # noqa: BLE001 - 统一翻成人话
        raise xcc.CrossCloudCopyError(f"在目标网盘创建保存目录失败：{exc}") from exc
    if not resolved:
        raise xcc.CrossCloudCopyError(f"在目标网盘找不到保存目录：{savepath}")
    job["target_dir_id"] = resolved
    try:
        job_id = int(job.get("id") or 0)
    except (TypeError, ValueError):
        job_id = 0
    if job_id:
        update_cross_copy_job(job_id, target_dir_id=resolved)
    return job


def _no_monitor_note(target_provider: str) -> str:
    """非 115 目标补一句说明：那边没有监控任务接手，不会自动处理。

    监控任务只绑在 115 上（`monitor.queue_inbox_dispatch_scan` 对非 115 直接返回），
    所以复制到夸克/阿里/天翼后既不会生成 STRM，也不会自动整理文件名。
    这里不替用户猜意图，只把这件事讲明白，要整理自己去「文件管理」页点。
    """
    name = str(target_provider or "").strip().lower()
    if not name or name == "115":
        return ""
    return "（非 115 目标：不会自动生成 STRM，也不整理文件名；要整理请在「文件管理」页手动执行）"


def _job_source_is_dir(job: Dict[str, Any]) -> bool:
    """任务源是文件夹？（老任务没有这列时为 0，走单文件逻辑）"""
    try:
        return bool(int(job.get("source_is_dir", 0) or 0))
    except (TypeError, ValueError):
        return False


def _finish_folder_job(job_id: int, job: Dict[str, Any], cfg: Dict[str, Any], result) -> None:
    """文件夹任务收口：写结果明细、按「全部失败/部分失败」定状态。

    文件夹任务一律不删源：这次只做复制，源文件夹里的东西不能动。
    """
    result_status = str(getattr(result, "status", "") or "completed")
    folder_name = str(getattr(result, "folder_name", "") or "").strip() or str(
        job.get("filename", "") or ""
    ).strip()
    total_bytes = int(getattr(result, "total_bytes", 0) or 0)
    message = str(getattr(result, "message", "") or "")
    target_path = _join_pan_path(job.get("target_savepath"), folder_name) or str(
        job.get("target_path", "") or ""
    )
    payload = result.to_dict() if hasattr(result, "to_dict") else {"status": result_status}
    note = _no_monitor_note(job.get("target_provider", ""))
    if note:
        payload["no_monitor_note"] = note
    fields: Dict[str, Any] = {
        "result": payload,
        "filename": folder_name or str(job.get("filename", "") or ""),
        "target_path": target_path,
    }
    if total_bytes > 0:
        fields["file_size"] = total_bytes
    update_cross_copy_job(job_id, **fields)

    if result_status == "failed":
        _fail_job(job_id, message or "整个文件夹都没复制成功")
        return

    finalize_fields: Dict[str, Any] = {}
    # 整包补源也要回写「最近命中」——只是文件名解析不出集数，进度那一项不动。
    if str(job.get("origin", "") or "").strip().lower() == "subscription":
        finalize_fields["progress_state"] = "pending"
    update_cross_copy_job(
        job_id,
        status=STATUS_COMPLETED,
        status_detail=(message or "复制完成") + _no_monitor_note(job.get("target_provider", "")),
        progress_percent=100,
        phase="done",
        error_message="",
        finished_at=now_text(),
        **finalize_fields,
    )
    _clear_job_progress(job_id)
    _push_cross_copy_notification(cfg, job, ok=True, message=message)
    _trigger_folder_monitor_refresh(job, cfg)


def _trigger_folder_monitor_refresh(job: Dict[str, Any], cfg: Dict[str, Any]) -> None:
    """订阅补源整包文件夹落地后触发监控扫描。

    单文件补源走整理定时器（先改名再扫描，顺序不能反）；文件夹不逐文件改名，
    没有顺序问题，落地即扫。与订阅导入收口同一口径：用落点目录匹配监控任务，
    匹配上才入队。手动复制与非 115 目标不触发——前者没有「落地即入库」的
    意图依据，后者没有监控目录。
    """
    if str(job.get("origin", "") or "").strip().lower() != "subscription":
        return
    try:
        # 延迟 import：organize 不依赖本模块，但 startup 两边都会拉，函数内 import 最稳
        from .subscription_cross_copy_organize import trigger_cross_copy_monitor_refresh

        result = trigger_cross_copy_monitor_refresh(
            cfg,
            str(job.get("target_provider", "") or ""),
            str(job.get("target_savepath", "") or ""),
            str(job.get("origin_ref", "") or ""),
        )
    except Exception as exc:  # noqa: BLE001 - 监控触发失败不影响复制收口
        logger.info("cross-copy folder monitor refresh skipped (job=%s): %s", job.get("id"), exc)
        return
    if result.get("triggered"):
        logger.info(
            "cross-copy folder monitor refresh queued (job=%s, monitor_task=%s)",
            job.get("id"),
            result.get("task_name"),
        )
    elif result.get("reason") == "monitor_disabled":
        logger.info(
            "cross-copy folder monitor refresh skipped: task disabled (job=%s, monitor_task=%s)",
            job.get("id"),
            result.get("task_name"),
        )


def _delete_source_file(source_provider, source_cookie: str, source_file_id: str) -> None:
    """删除源网盘中本任务转存的文件（仅按 file_id 精确删，不碰其他文件）。"""
    fid = str(source_file_id or "").strip()
    if not fid or not getattr(source_provider, "supports_delete", False):
        return
    source_provider.delete_entries(source_cookie, [fid])


def _fail_job(job_id: int, message: str, resume_state: Optional[Dict[str, Any]] = None) -> None:
    detail = message[:200]
    if resume_state_is_inheritable(resume_state):
        # 失败也保底落一次最新断点：on_resume_update 是节流的，最后一次可能没写。
        # 文案与取消分支一致——用户看到「已保留断点」才知道重试能续传
        _persist_final_resume(job_id, resume_state)
        detail = f"{detail}{_RESUME_KEPT_SUFFIX}"
    job = get_cross_copy_job(job_id) or {}
    fields: Dict[str, Any] = {
        "status": STATUS_FAILED,
        "status_detail": detail,
        "error_message": message[:2000],
        "finished_at": now_text(),
    }
    if str(job.get("origin", "") or "").strip().lower() == "subscription":
        # 失败也要进「待回写」队列，和成功一样。不进队列的话订阅日志里一个字都
        # 没有，卡片上的「跨盘补源中」消失后又退回「尚未命中」——用户会以为兜底
        # 根本没找到资源，实际是找到了、复制挂了。真正的日志由
        # subscription_cross_copy_progress 的定时器成组写一条（一轮失败好几集，
        # 逐条写会把日志刷满）。
        fields["progress_state"] = "pending"
    update_cross_copy_job(job_id, **fields)
    _clear_job_progress(job_id)
    try:
        cfg = get_config()
        _push_cross_copy_notification(cfg, job, ok=False, message=message)
    except Exception:  # noqa: BLE001 - 通知失败不影响任务收口
        logger.info("cross-copy failure notify skipped (job=%s)", job_id)


def _cross_copy_notify_enabled(cfg: Dict[str, Any], job: Dict[str, Any]) -> bool:
    """按任务来源取对应的通知开关。

    订阅补源（origin=subscription，自动发起）与手动复制（其余）是两条
    独立开关，在设置页「通知推送」分区维护；来源未知时按手动处理。
    """
    origin = str(job.get("origin", "") or "").strip().lower()
    key = "cross_copy_notify_subscription" if origin == "subscription" else "cross_copy_notify_manual"
    return bool(cfg.get(key, True))


def subscription_cross_copy_notify_merged(cfg: Dict[str, Any]) -> bool:
    """订阅补源的成功通知是否并入「订阅更新成功」那一条。

    两个开关都开着才合并：订阅成功推送负责这条消息的内容，补源开关负责
    「要不要收补源相关消息」。只开订阅推送、关掉补源时什么都不发（用户就是
    不想收补源消息）；只开补源时退回逐条「跨盘复制完成」，不至于把消息吞掉。
    """
    return bool(cfg.get("notify_push_enabled", False)) and bool(
        cfg.get("cross_copy_notify_subscription", True)
    )


def _push_cross_copy_notification(cfg: Dict[str, Any], job: Dict[str, Any], *, ok: bool, message: str) -> None:
    """跨盘复制完成/失败通知。

    开关按任务来源区分（订阅补源 / 手动复制），渠道是否可用只看通知渠道
    配置，不依赖其他场景的开关。

    订阅补源**成功**时不在这里发：补 5 集就是 5 条长得一样的消息（正文的
    「文件」取的是片名，不是集名），用户看不出补了哪几集。改由
    ``subscription_cross_copy_progress`` 成组回写时发一条「订阅更新成功」。
    失败仍然逐条发——得知道是哪一集挂了。
    """
    if not _cross_copy_notify_enabled(cfg, job):
        return
    if (
        ok
        and str(job.get("origin", "") or "").strip().lower() == "subscription"
        and subscription_cross_copy_notify_merged(cfg)
    ):
        return
    if not notify_channel_ready(cfg):
        return
    # 通知里要给人看的网盘名，不能直接拼内部代号（否则会显示 tianyi 这种英文）
    source_label = _provider_label(str(job.get("source_provider", "") or ""), default="源网盘")
    target_label = _provider_label(str(job.get("target_provider", "") or ""), default="目标网盘")
    title = str(job.get("title", "") or job.get("filename", "") or "文件")
    trigger_label = "订阅补源" if str(job.get("origin", "") or "").strip().lower() == "subscription" else "手动复制"
    if ok:
        content = "\n".join(
            [
                "### 跨盘复制完成",
                f"> 文件：{title}",
                f"> 链路：{source_label} → {target_label}",
                f"> 触发：{trigger_label}",
                f"> 结果：{message or '成功'}",
            ]
        )
    else:
        content = "\n".join(
            [
                "### 跨盘复制失败",
                f"> 文件：{title}",
                f"> 链路：{source_label} → {target_label}",
                f"> 触发：{trigger_label}",
                f"> 原因：{message or '未知错误'}",
                "> 建议：到任务中心查看详情并重试",
            ]
        )
    try:
        _send_notify_content(build_notify_runtime_config(cfg), content, timeout=15)
    except Exception as exc:  # noqa: BLE001 - 通知失败只记录
        logger.info("cross-copy notify failed (job=%s): %s", job.get("id"), exc)


def requeue_cross_copy_jobs_on_startup() -> Dict[str, int]:
    """启动恢复：重启前残留的 pending/running 任务重新入队。

    走的是和新建任务同一条排队路径（submit → _schedule），
    重启后一次涌入几十个任务也不会同时开跑。
    """
    ensure_db()
    requeued = 0
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM cross_copy_jobs WHERE status IN (?, ?)",
            (STATUS_PENDING, STATUS_RUNNING),
        )
        rows = cursor.fetchall()
        for row in rows:
            job_id = int(row[0])
            update_cross_copy_job(
                job_id,
                status=STATUS_PENDING,
                status_detail="服务重启，等待重新执行",
            )
            requeued += 1
        conn.commit()
    for job_id in _stale_job_ids():
        submit_cross_copy_job(job_id)
    return {"requeued": requeued}


def cleanup_temp_files_on_startup() -> Dict[str, int]:
    """扫掉异常退出留下的半截临时文件，返回清掉的数量。

    正常完成/失败的任务都在 ``finally`` 里自己删临时文件，只有容器被杀、进程
    崩溃这类硬中断才会留下 ``xcopy-*.part``。这些文件没人认领，不清理就会一直
    占着磁盘，所以启动时扫一遍、长期运行时再按间隔扫一遍。

    清理失败不影响主流程：临时文件占的是磁盘，不该把服务拉不起来。
    """
    removed = 0
    try:
        cfg = get_config()
        temp_dir = xcc.resolve_temp_dir(cfg)
        if temp_dir:
            removed = int(xcc.cleanup_orphan_temp_files(temp_dir) or 0)
            if removed:
                logger.info("cross-copy orphan temp files cleaned: %s in %s", removed, temp_dir)
            # 孤儿临时文件删掉后，指向它们的断点状态一并作废（空头支票清掉）
            prune_resume_for_missing_files()
    except Exception as exc:  # noqa: BLE001 - 清理失败不阻断启动
        logger.warning("cross-copy orphan temp cleanup skipped: %s", exc)
    return {"removed": removed}


# 容器长期运行时的兜底扫描间隔。孤儿文件本来就不多，30 分钟一次足够，
# 又不会把磁盘 IO 花在空扫描上。
TEMP_CLEANUP_INTERVAL_SECONDS = 30 * 60


async def cross_copy_temp_cleanup_watcher() -> None:
    """定时清理半截临时文件 + 兜底裁剪任务记录（容器长期运行、没有重启机会时）。"""
    await asyncio.sleep(60)
    while True:
        try:
            await asyncio.to_thread(cleanup_temp_files_on_startup)
            await asyncio.to_thread(prune_cross_copy_job_history)
        except Exception as exc:  # noqa: BLE001 - 定时任务不能把循环打死
            logger.warning("跨盘复制临时文件定期清理失败：%s", exc)
        await asyncio.sleep(TEMP_CLEANUP_INTERVAL_SECONDS)


def _stale_job_ids() -> List[int]:
    """待恢复的任务按 job id 升序排队（先建的先跑）。"""
    jobs = list_cross_copy_jobs(limit=100, status=STATUS_PENDING)
    return sorted(int(job["id"]) for job in jobs)
