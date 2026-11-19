"""跨盘补源落地后，把订阅任务的「最近命中 / 追更进度」补齐。

为什么需要单独一步：

- 补源是**旁路**。订阅主流程把补源注册成独立的跨盘复制任务后自己就结束了，
  复制在 ``cross_copy_jobs`` 里排队跑，跑完没有任何代码回写
  ``subscription_task_state``；
- 结果就是界面上的「最近命中」「上次命中时间」「追更进度 E42」全部停在
  上一次同盘导入的旧值。**目录里识别到的集数是对的**（那走的是实时扫描），
  只有这份持久化状态没跟上。

做法和「入库后整理」同款：复制收口只在 ``cross_copy_jobs`` 打一个
``progress_state='pending'`` 标记（同一条 UPDATE，零额外开销），本模块的定时器
按订阅任务成组、过防抖窗口后**一次写回**——一轮补源常注册 3~5 条任务，逐条写
会互相覆盖，也说不清「这一轮到底补了哪些集」。

集数口径：直接从补源任务落地的文件名解析（``S01E42.mp4`` /
``片名 (年份) - S01E42.mp4`` 都认），取本组最大值与已有进度求 max。
整包文件夹补源解析不出集数，只写命中记录不动进度（那种场景只在「本盘一集都
没有」时发生，进度本来就是 0）。
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from ..core import (
    get_config,
    reset_subscription_log_context,
    resolve_subscription_tv_total_episodes,
    set_subscription_log_context,
    subscription_status,
    write_subscription_log,
)
from ..db import db_connection, ensure_db, now_text, sqlite_row_to_dict
from ..providers.registry import label_for as _provider_label
from .cross_copy_jobs import subscription_cross_copy_notify_merged
from .notify import push_cross_copy_subscription_notification
from .subscription_episode import _extract_task_episodes_from_file_entry
from .subscription_state import load_subscription_task_state, upsert_subscription_task_state

logger = logging.getLogger(__name__)

PROGRESS_STATE_PENDING = "pending"
PROGRESS_STATE_RUNNING = "running"
PROGRESS_STATE_DONE = "done"
PROGRESS_STATE_SKIPPED = "skipped"
PROGRESS_STATE_FAILED = "failed"

# 防抖：一轮补源会连续完成好几条任务，等它们都落库再一次性写回进度
PROGRESS_DEBOUNCE_SECONDS = max(0, int(os.environ.get("CROSS_COPY_PROGRESS_DEBOUNCE_SECONDS", 30) or 30))
PROGRESS_INTERVAL_SECONDS = max(20, int(os.environ.get("CROSS_COPY_PROGRESS_INTERVAL_SECONDS", 60) or 60))
PROGRESS_MAX_GROUPS_PER_TICK = max(1, int(os.environ.get("CROSS_COPY_PROGRESS_MAX_GROUPS", 20) or 20))
PROGRESS_PENDING_LIMIT = 200
# running 超过这个时间视为进程中断，放回 pending 重试
PROGRESS_RUNNING_TIMEOUT_SECONDS = 15 * 60
# 「上次通知到哪个任务」的游标，存在订阅状态 stats 里。
# 用「完成时间 + id」复合游标而不是只用 id：重试的任务 id 不变、完成时间会变，
# 只按 id 会比大小把它跳过，重试成功的集数就永远进不了通知。
PROGRESS_NOTIFY_CURSOR_TIME_KEY = "cross_copy_notified_at"
PROGRESS_NOTIFY_CURSOR_ID_KEY = "cross_copy_notified_job_id"
# 游标缺失（功能刚上线）时只回溯这么久，避免把历史补源任务全补发一遍
PROGRESS_NOTIFY_BOOTSTRAP_HOURS = 24


def _cutoff_text() -> str:
    """防抖窗口的截止时间：``finished_at`` 是 ISO 秒级字符串，直接字符串比较即可。"""
    cutoff = datetime.now() - timedelta(seconds=PROGRESS_DEBOUNCE_SECONDS)
    return cutoff.isoformat(timespec="seconds")


def list_progress_jobs(cutoff_text: str, limit: int = PROGRESS_PENDING_LIMIT) -> List[Dict[str, Any]]:
    ensure_db()
    try:
        with db_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM cross_copy_jobs
                WHERE progress_state = ?
                  AND finished_at != ''
                  AND finished_at <= ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (PROGRESS_STATE_PENDING, str(cutoff_text or ""), int(limit)),
            )
            return [sqlite_row_to_dict(row) for row in cursor.fetchall()]
    except Exception as exc:  # noqa: BLE001 - 定时任务不能因为一次查询失败就死掉
        logger.warning("跨盘补源进度回写：读取待回写任务失败：%s", exc)
        return []


def group_jobs(jobs: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """按订阅任务名成组（``origin_ref`` 就存的任务名）。"""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for job in jobs if isinstance(jobs, list) else []:
        if not isinstance(job, dict):
            continue
        task_name = str(job.get("origin_ref", "") or "").strip()
        if not task_name:
            continue
        groups.setdefault(task_name, []).append(job)
    return groups


def _reset_stale_running() -> int:
    """把卡在 running 的任务放回 pending（进程重启/线程被打断会留下）。"""
    ensure_db()
    cutoff = (datetime.now() - timedelta(seconds=PROGRESS_RUNNING_TIMEOUT_SECONDS)).isoformat(
        timespec="seconds"
    )
    try:
        with db_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE cross_copy_jobs
                SET progress_state = ?, progress_detail = ?, updated_at = ?
                WHERE progress_state = ? AND updated_at <= ?
                """,
                (PROGRESS_STATE_PENDING, "上次回写被中断，重新排队", now_text(), PROGRESS_STATE_RUNNING, cutoff),
            )
            conn.commit()
            return int(cursor.rowcount or 0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("跨盘补源进度回写：重置中断任务失败：%s", exc)
        return 0


def _claim_jobs(job_ids: List[int]) -> List[int]:
    """CAS 抢占：只有仍是 pending 的才能改成 running，避免两轮重复写回。"""
    ensure_db()
    claimed: List[int] = []
    try:
        with db_connection() as conn:
            for job_id in job_ids:
                cursor = conn.execute(
                    """
                    UPDATE cross_copy_jobs
                    SET progress_state = ?, updated_at = ?
                    WHERE id = ? AND progress_state = ?
                    """,
                    (PROGRESS_STATE_RUNNING, now_text(), int(job_id), PROGRESS_STATE_PENDING),
                )
                if int(cursor.rowcount or 0) > 0:
                    claimed.append(int(job_id))
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("跨盘补源进度回写：抢占任务失败：%s", exc)
    return claimed


def _release_jobs(job_ids: List[int]) -> None:
    """写回没做成（任务在跑 / 取不到任务）时放回 pending，下一轮再试。

    不直接标 failed：这些都是「等一会儿就好」的情况，标 failed 会让这批任务
    永远不再回写，进度就又停在旧值了。
    """
    if not job_ids:
        return
    ensure_db()
    placeholders = ",".join(["?"] * len(job_ids))
    try:
        with db_connection() as conn:
            conn.execute(
                f"""
                UPDATE cross_copy_jobs
                SET progress_state = ?, updated_at = ?
                WHERE id IN ({placeholders}) AND progress_state = ?
                """,
                (
                    PROGRESS_STATE_PENDING,
                    now_text(),
                    *[int(item) for item in job_ids],
                    PROGRESS_STATE_RUNNING,
                ),
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("跨盘补源进度回写：放回待回写失败：%s", exc)


def _finish_jobs(job_ids: List[int], state: str, detail: str) -> None:
    if not job_ids:
        return
    ensure_db()
    normalized_detail = str(detail or "").strip()[:200]
    placeholders = ",".join(["?"] * len(job_ids))
    try:
        with db_connection() as conn:
            conn.execute(
                f"""
                UPDATE cross_copy_jobs
                SET progress_state = ?, progress_detail = ?, updated_at = ?
                WHERE id IN ({placeholders}) AND progress_state = ?
                """,
                (
                    str(state),
                    normalized_detail,
                    now_text(),
                    *[int(item) for item in job_ids],
                    PROGRESS_STATE_RUNNING,
                ),
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("跨盘补源进度回写：写回结果失败：%s", exc)


def find_subscription_task(cfg: Dict[str, Any], task_name: str) -> Dict[str, Any]:
    """按任务名反查订阅任务（补源任务里只存了 ``origin_ref`` = 任务名）。"""
    wanted = str(task_name or "").strip()
    if not wanted:
        return {}
    tasks = cfg.get("subscription_tasks") if isinstance(cfg.get("subscription_tasks"), list) else []
    for task in tasks:
        if isinstance(task, dict) and str(task.get("name", "") or "").strip() == wanted:
            return task
    return {}


def _collect_episodes(task: Dict[str, Any], jobs: List[Dict[str, Any]]) -> Set[int]:
    """从补源任务落地后的文件名里解析集数。

    复用订阅侧的识别器（认得 ``SxxEyy`` / ``Exx`` / 「第 N 集」，也会过滤字幕、
    音频、非视频），和补源「按集挑缺」用的是同一套逻辑，口径不会打架。
    认不出来（整包文件夹补源就是这种）返回空集合，调用方只写命中记录不动进度。
    """
    episodes: Set[int] = set()
    for job in jobs if isinstance(jobs, list) else []:
        name = str(job.get("filename", "") or "").strip()
        if not name:
            continue
        try:
            found = _extract_task_episodes_from_file_entry(task, name)
        except Exception:  # noqa: BLE001 - 单条解析失败不影响整组回写
            found = set()
        for value in found or ():
            try:
                episode = max(0, int(value or 0))
            except (TypeError, ValueError):
                continue
            if episode > 0:
                episodes.add(episode)
    return episodes


def _format_episode_brief(episodes: Set[int]) -> str:
    """把集集合压成「E42」「E42~E44」「E41、E43、E45」这种短文案。"""
    ordered = sorted(int(item) for item in episodes if int(item) > 0)
    if not ordered:
        return ""
    if len(ordered) == 1:
        return f"E{ordered[0]}"
    if ordered[-1] - ordered[0] + 1 == len(ordered):
        return f"E{ordered[0]}~E{ordered[-1]}"
    if len(ordered) <= 6:
        return "、".join(f"E{item}" for item in ordered)
    return f"E{ordered[0]}~E{ordered[-1]} 等 {len(ordered)} 集"


def _subscription_task_is_running(task_name: str) -> bool:
    """该订阅任务此刻正在跑就别写状态，免得踩掉运行中的「运行中」标记。

    补源完成后，订阅往往已经在跑下一轮；这一轮写进去会被下一轮的 upsert 覆盖，
    而且中间的 running/等待状态会被改成 completed，界面看着像跑完了。
    """
    if not bool(subscription_status.get("running")):
        return False
    return str(subscription_status.get("current_task", "") or "").strip() == str(task_name or "").strip()


def apply_progress_for_task(
    task_name: str,
    jobs: List[Dict[str, Any]],
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """把一组补源任务的结果汇总写回订阅任务状态（同步函数，供线程调用）。

    返回 ``{"ok": bool, "retry": bool, "detail": str}``：
    ``retry=True`` 表示这次没写成但等会儿可以再试（任务在跑 / 任务暂时取不到），
    调用方应保持 pending。
    """
    task = find_subscription_task(cfg, task_name)
    if not task:
        return {"ok": False, "retry": False, "detail": "订阅任务已不存在"}
    if _subscription_task_is_running(task_name):
        return {"ok": False, "retry": True, "detail": "订阅任务正在运行，稍后再回写"}

    media_type = str(task.get("media_type", "movie") or "movie").strip().lower() or "movie"
    previous = load_subscription_task_state(task_name, media_type)
    previous_episode = max(0, int(previous.get("last_episode", 0) or 0))
    previous_total = max(0, int(previous.get("total_episodes", 0) or 0))
    previous_stats = previous.get("stats") if isinstance(previous.get("stats"), dict) else {}

    job_list = [job for job in (jobs or []) if isinstance(job, dict)]
    job_ids = sorted({int(job.get("id", 0) or 0) for job in job_list if int(job.get("id", 0) or 0) > 0})
    file_count = len(job_list)
    episodes = _collect_episodes(task, job_list) if media_type == "tv" else set()
    next_episode = max(previous_episode, max(episodes) if episodes else 0)

    if media_type == "tv":
        total_episodes = resolve_subscription_tv_total_episodes(task, state_total=previous_total)
    else:
        total_episodes = previous_total

    savepath = ""
    for job in reversed(job_list):
        savepath = str(job.get("target_savepath", "") or "").strip()
        if savepath:
            break
    title = ""
    for job in job_list:
        title = str(job.get("title", "") or "").strip()
        if title:
            break
    title = title or str(task.get("title", "") or task.get("name", "") or task_name).strip()

    episode_brief = _format_episode_brief(episodes)
    if episode_brief:
        detail = f"跨盘补源完成：从夸克补入 {file_count} 个文件（{episode_brief}）"
    else:
        detail = f"跨盘补源完成：从夸克补入 {file_count} 个条目（整包复制，进度以目标目录扫描为准）"
    if savepath:
        detail += f"，已保存到 {savepath}"

    status = "completed"
    stats = {
        **previous_stats,
        "matched": True,
        "cross_copy": True,
        "cross_copy_job_ids": job_ids[:40],
        "cross_copy_file_count": file_count,
        "cross_copy_episodes": sorted(episodes)[:80],
        "cross_copy_target_savepath": savepath,
        "cross_copy_progress_at": now_text(),
    }
    if media_type == "tv" and episodes:
        # 复制成功的文件确实落进了目标目录，顺手把「资源库里已保存到第几集」
        # 一起抬高。否则界面上的「已到 E42」会停在补源前，要等下一次运行
        # 扫目录才追上——那正是这个补源旁路最容易让人误会的时刻。
        stats["existing_episode_max"] = max(
            max(0, int(previous_stats.get("existing_episode_max", 0) or 0)),
            max(episodes),
        )

    fields: Dict[str, Any] = {
        "media_type": media_type,
        "status": status,
        "progress": 100,
        "detail": detail,
        "last_success_at": now_text(),
        "last_error": "",
        "matched_resource_title": f"{title}（夸克补源）",
        "stats": stats,
    }
    if media_type == "tv":
        fields["last_episode"] = next_episode
        fields["total_episodes"] = total_episodes
    elif total_episodes > 0:
        fields["total_episodes"] = total_episodes

    upsert_subscription_task_state(task_name, **fields)

    # 通知不在这个同步函数里发（发送是 IO，会占住这个线程）：把任务带回去，
    # 由 _apply_group 调 collect_notify_batch 攒齐整批后再发。
    return {"ok": True, "retry": False, "detail": detail, "task": task}


def collect_notify_batch(task_name: str, task: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """把「同一批补源」攒齐再发通知，返回通知参数；还不到时候就返回 ``None``。

    跨盘补源是「下载 → 上传」，一集要几分钟，全局并发默认 2，所以兄弟任务不会
    同时完成。如果一组完成就发一条，补 5 集照样会收到 2~3 条消息。两道闸：

    1. 该订阅任务还有 pending/running 的补源任务 → 先不发，等最后一批；
    2. 发的时候按游标（``stats.cross_copy_notified_job_id``）把「上次通知之后
       完成的所有补源任务」聚合起来，前面几批的集数不会漏。

    游标缺失（功能刚上线）时只回溯 ``PROGRESS_NOTIFY_BOOTSTRAP_HOURS`` 小时，
    否则会把历史补源任务全部补发一遍。
    """
    normalized_name = str(task_name or "").strip()
    if not normalized_name:
        return None
    media_type = str(task.get("media_type", "movie") or "movie").strip().lower() or "movie"
    state = load_subscription_task_state(normalized_name, media_type)
    state_stats = state.get("stats") if isinstance(state.get("stats"), dict) else {}
    cursor_time = str(state_stats.get(PROGRESS_NOTIFY_CURSOR_TIME_KEY, "") or "").strip()
    cursor_id = max(0, int(state_stats.get(PROGRESS_NOTIFY_CURSOR_ID_KEY, 0) or 0))

    ensure_db()
    try:
        with db_connection() as conn:
            unfinished_row = conn.execute(
                """
                SELECT COUNT(*) FROM cross_copy_jobs
                WHERE origin = ? AND origin_ref = ? AND status IN (?, ?)
                """,
                ("subscription", normalized_name, "pending", "running"),
            ).fetchone()
            if int((unfinished_row[0] if unfinished_row else 0) or 0) > 0:
                return None
            if cursor_time:
                rows = conn.execute(
                    """
                    SELECT * FROM cross_copy_jobs
                    WHERE origin = ? AND origin_ref = ? AND status = ? AND finished_at <> ''
                      AND (finished_at > ? OR (finished_at = ? AND id > ?))
                    ORDER BY finished_at ASC, id ASC
                    LIMIT 200
                    """,
                    (
                        "subscription",
                        normalized_name,
                        "completed",
                        cursor_time,
                        cursor_time,
                        cursor_id,
                    ),
                ).fetchall()
            else:
                cutoff_text = (datetime.now() - timedelta(hours=PROGRESS_NOTIFY_BOOTSTRAP_HOURS)).isoformat(
                    timespec="seconds"
                )
                rows = conn.execute(
                    """
                    SELECT * FROM cross_copy_jobs
                    WHERE origin = ? AND origin_ref = ? AND status = ? AND finished_at >= ?
                    ORDER BY finished_at ASC, id ASC
                    LIMIT 200
                    """,
                    ("subscription", normalized_name, "completed", cutoff_text),
                ).fetchall()
    except Exception as exc:  # noqa: BLE001 - 通知批次查不出来不该影响进度回写
        logger.warning("跨盘补源通知：读取待通知批次失败（%s）：%s", normalized_name, exc)
        return None

    if not rows:
        return None

    episodes: Set[int] = set()
    job_ids: List[int] = []
    savepath = ""
    source_provider = ""
    target_provider = ""
    last_finished_at = ""
    for row in rows:
        job = sqlite_row_to_dict(row)
        job_id = int(job.get("id", 0) or 0)
        if job_id <= 0:
            continue
        job_ids.append(job_id)
        savepath = str(job.get("target_savepath", "") or "").strip() or savepath
        source_provider = source_provider or str(job.get("source_provider", "") or "").strip()
        target_provider = target_provider or str(job.get("target_provider", "") or "").strip()
        last_finished_at = str(job.get("finished_at", "") or "").strip() or last_finished_at
        file_name = str(job.get("filename", "") or "").strip()
        if media_type == "tv" and file_name:
            try:
                episodes |= {
                    max(0, int(item or 0))
                    for item in (_extract_task_episodes_from_file_entry(task, file_name) or ())
                    if max(0, int(item or 0)) > 0
                }
            except Exception:  # noqa: BLE001 - 单条解析失败不影响整批
                continue
    if not job_ids:
        return None

    return {
        "episodes": sorted(episodes),
        "savepath": savepath,
        "job_ids": job_ids,
        "file_count": len(job_ids),
        "source_label": _provider_label(source_provider, default="源网盘") if source_provider else "源网盘",
        "target_label": _provider_label(target_provider, default="目标网盘") if target_provider else "目标网盘",
        "next_episode": max(0, int(state.get("last_episode", 0) or 0)),
        "total_episodes": max(0, int(state.get("total_episodes", 0) or 0)),
        # 内部字段：发送成功后用它推进游标，不传给通知函数
        "cursor_time": last_finished_at,
        "cursor_id": max(job_ids),
    }


def advance_notify_cursor(task_name: str, cursor_time: str, cursor_id: int, media_type: str) -> None:
    """记住「已经通知到哪个时刻的哪条任务」，避免下一轮把同一批再报一遍。"""
    normalized_time = str(cursor_time or "").strip()
    if not normalized_time:
        return
    state = load_subscription_task_state(task_name, media_type)
    current_stats = state.get("stats") if isinstance(state.get("stats"), dict) else {}
    upsert_subscription_task_state(
        task_name,
        media_type=media_type,
        stats={
            **current_stats,
            PROGRESS_NOTIFY_CURSOR_TIME_KEY: normalized_time,
            PROGRESS_NOTIFY_CURSOR_ID_KEY: max(0, int(cursor_id or 0)),
        },
    )


def _log_context(task_name: str) -> Any:
    """订阅日志靠 contextvar 补任务名，定时器里得手动包一层。"""
    return set_subscription_log_context(
        {
            "task_name": str(task_name or "").strip(),
            "provider": "",
            "media_type": "tv",
            "trigger": "cross_copy",
        }
    )


async def _push_merged_success_notification(
    cfg: Dict[str, Any],
    task: Any,
    stats: Dict[str, Any],
) -> None:
    """补源成功的那一条「订阅更新成功」。

    只在一批补源全部跑完之后发一次；通知失败不影响已写回的进度（那条已经
    落库了，重发通知没有意义，也不该把整组标成失败）。
    """
    if not isinstance(task, dict):
        return
    if not subscription_cross_copy_notify_merged(cfg):
        return
    task_name = str(task.get("name", "") or task.get("title", "") or "").strip()
    if not task_name:
        return
    media_type = str(task.get("media_type", "movie") or "movie").strip().lower() or "movie"
    try:
        payload = await asyncio.to_thread(collect_notify_batch, task_name, task)
    except Exception as exc:  # noqa: BLE001 - 通知失败只记日志
        logger.warning("跨盘补源订阅通知：准备批次失败（%s）：%s", task_name, exc)
        stats["notify_failed"] = int(stats.get("notify_failed", 0) or 0) + 1
        return
    if not isinstance(payload, dict):
        # 还有兄弟任务在跑，等它们结束那一轮再发
        return
    cursor_time = str(payload.pop("cursor_time", "") or "")
    cursor_id = int(payload.pop("cursor_id", 0) or 0)
    notify_episodes = payload.get("episodes") if isinstance(payload.get("episodes"), list) else []
    try:
        result = await push_cross_copy_subscription_notification(cfg=cfg, task=task, **payload)
    except Exception as exc:  # noqa: BLE001 - 通知失败只记日志
        logger.warning("跨盘补源订阅通知发送失败（%s）：%s", task_name, exc)
        stats["notify_failed"] = int(stats.get("notify_failed", 0) or 0) + 1
        return
    if bool(result.get("pushed", False)):
        stats["notified"] = int(stats.get("notified", 0) or 0) + 1
        episode_note = f"（{len(notify_episodes)} 集）" if notify_episodes else ""
        await write_subscription_log(f"订阅成功通知已推送{episode_note}", "info")
        try:
            await asyncio.to_thread(
                advance_notify_cursor, task_name, cursor_time, cursor_id, media_type
            )
        except Exception as exc:  # noqa: BLE001 - 游标没推进最多重复一次，去重表会挡
            logger.warning("跨盘补源通知：推进游标失败（%s）：%s", task_name, exc)


def _shorten_reason(text: str, limit: int = 80) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else f"{value[: limit - 1]}…"


def build_failure_detail(task: Dict[str, Any], jobs: List[Dict[str, Any]]) -> str:
    """把一组失败的补源任务压成一条订阅日志。

    为什么成组而不是逐条：一轮可能失败 10 集，逐条写会把订阅日志刷满；但也不能
    只写「失败」两个字——用户需要知道是哪几集、为什么挂的。集数认得出来用
    ``E03``，认不出来（整包文件夹补源）就说文件数。
    """
    job_list = [job for job in (jobs or []) if isinstance(job, dict)]
    episodes = _collect_episodes(task, job_list)
    if episodes:
        head = f"跨盘补源失败 {len(job_list)} 集（{_format_episode_brief(episodes)}）"
    else:
        head = f"跨盘补源失败 {len(job_list)} 个文件"
    reasons: List[str] = []
    for job in job_list:
        reason = str(job.get("error_message", "") or job.get("status_detail", "") or "").strip()
        reason = _shorten_reason(reason)
        if reason and reason not in reasons:
            reasons.append(reason)
    detail = head
    if reasons:
        detail += "：" + "；".join(reasons[:2])
    return detail + "，下一轮订阅会自动重试"


async def _apply_failed_group(task_name: str, jobs: List[Dict[str, Any]], stats: Dict[str, Any]) -> None:
    """失败组的收尾：写一条 warn 日志，不动订阅状态。

    不动 ``subscription_task_state`` 的原因：失败不该改写「最近命中 / 追更进度」
    这些成功语义的字段；卡片上的「补源失败 · N 集」由
    ``subscription_state.cross_copy_failure_counts()`` 实时查作业表得出。
    """
    job_ids = [int(job.get("id", 0) or 0) for job in jobs if int(job.get("id", 0) or 0) > 0]
    if not job_ids:
        return
    try:
        task = find_subscription_task(get_config(), task_name)
    except Exception:  # noqa: BLE001 - 取不到任务只影响文案里的集数解析
        task = {}
    detail = build_failure_detail(task or {}, jobs)
    _finish_jobs(job_ids, PROGRESS_STATE_DONE, detail)
    stats["copy_failed"] = int(stats.get("copy_failed", 0) or 0) + len(job_ids)
    # 订阅任务正在运行时也照写：这条描述的是已经结束的补源任务，不碰主流程状态
    await write_subscription_log(detail, "warn")


async def _apply_group(task_name: str, jobs: List[Dict[str, Any]], stats: Dict[str, Any]) -> None:
    job_ids = [int(job.get("id", 0) or 0) for job in jobs if int(job.get("id", 0) or 0) > 0]
    claimed = _claim_jobs(job_ids)
    if not claimed:
        return
    stats["groups"] += 1
    claimed_set = set(claimed)
    claimed_jobs = [job for job in jobs if int(job.get("id", 0) or 0) in claimed_set]
    # 同一批里成功和失败要分开处理：``apply_progress_for_task`` 是「这批补进来了
    # 什么」的语义，把失败的任务混进去会把 file_count / 集数算多。
    failed_jobs = [
        job for job in claimed_jobs if str(job.get("status", "") or "").strip().lower() == "failed"
    ]
    ok_jobs = [job for job in claimed_jobs if job not in failed_jobs]
    token = _log_context(task_name)
    try:
        if failed_jobs:
            await _apply_failed_group(task_name, failed_jobs, stats)
        if not ok_jobs:
            return
        cfg = get_config()
        result = await asyncio.to_thread(apply_progress_for_task, task_name, ok_jobs, cfg)
        if result.get("retry"):
            _release_jobs([int(job.get("id", 0) or 0) for job in ok_jobs])
            return
        if result.get("ok"):
            claimed_ok = [int(job.get("id", 0) or 0) for job in ok_jobs]
            _finish_jobs(claimed_ok, PROGRESS_STATE_DONE, str(result.get("detail", "") or "已回写订阅进度"))
            stats["done"] += len(claimed_ok)
            await write_subscription_log(str(result.get("detail", "") or ""), "success")
            # 补源成功也算订阅成功：这里发那一条「订阅更新成功」，
            # 逐文件的「跨盘复制完成」已在成功收口处按开关跳过。
            await _push_merged_success_notification(cfg, result.get("task"), stats)
            return
        reason = str(result.get("detail", "") or "回写未完成").strip()
        claimed_ok = [int(job.get("id", 0) or 0) for job in ok_jobs]
        _finish_jobs(claimed_ok, PROGRESS_STATE_SKIPPED, reason)
        stats["skipped"] += len(claimed_ok)
    except Exception as exc:  # noqa: BLE001 - 一组出错不能把整个定时器打死
        logger.exception("跨盘补源进度回写失败（%s）", task_name)
        _finish_jobs(claimed, PROGRESS_STATE_FAILED, f"回写异常：{str(exc)[:120]}")
        stats["failed"] += len(claimed)
    finally:
        reset_subscription_log_context(token)


async def run_pending_progress_once() -> Dict[str, Any]:
    """跑一轮「待回写」。返回统计，方便排查与测试。"""
    stats: Dict[str, Any] = {
        "groups": 0,
        "done": 0,
        "skipped": 0,
        "failed": 0,
        # 补源任务本身失败的条数（区别于 failed = 回写异常）
        "copy_failed": 0,
        "reset": 0,
        "notified": 0,
        "notify_failed": 0,
    }
    stats["reset"] = _reset_stale_running()
    jobs = list_progress_jobs(_cutoff_text())
    if not jobs:
        return stats
    groups = group_jobs(jobs)
    for task_name, group in list(groups.items())[:PROGRESS_MAX_GROUPS_PER_TICK]:
        await _apply_group(task_name, group, stats)
    if stats["done"] or stats["failed"] or stats["copy_failed"]:
        logger.info("跨盘补源进度回写：%s", stats)
    return stats


async def cross_copy_progress_watcher() -> None:
    """定时把补源落地的结果写回订阅任务（最近命中 / 追更进度）。"""
    await asyncio.sleep(30)
    while True:
        try:
            await run_pending_progress_once()
        except Exception as exc:  # noqa: BLE001 - 定时任务不能把循环打死
            logger.warning("跨盘补源进度回写失败：%s", exc)
        await asyncio.sleep(PROGRESS_INTERVAL_SECONDS)
