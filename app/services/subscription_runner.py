from typing import Any, Dict, List, Optional

from ..background import submit_background

from ..core import safe_json_dumps, schedule_ui_state_push, subscription_queue, subscription_queue_lock, subscription_status


async def start_next_subscription_job() -> None:
    with subscription_queue_lock:
        if subscription_status["running"] or not subscription_queue:
            subscription_status["queued"] = [item["task_name"] for item in subscription_queue]
            schedule_ui_state_push(0)
            return
        next_job = subscription_queue.pop(0)
        subscription_status["queued"] = [item["task_name"] for item in subscription_queue]
    schedule_ui_state_push(0)

    from .subscription import run_subscription_task

    submit_background(
        run_subscription_task,
        next_job["task_name"],
        trigger=next_job.get("trigger", "queued"),
        manual_candidate=next_job.get("manual_candidate"),
        label="subscription-job",
    )


def queue_subscription_job(task_name: str, trigger: str, manual_candidate: Optional[Dict[str, Any]] = None) -> str:
    return queue_subscription_jobs(task_name, trigger, [manual_candidate or {}])


def queue_subscription_jobs(
    task_name: str,
    trigger: str,
    manual_candidates: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """一次追加同一订阅任务的多条手动候选（例如一次粘贴多条链接）。

    和逐条调用 `queue_subscription_job` 的区别：整批只在末尾触发一次队列调度，
    避免多条链接同时抢跑（`running` 还没置位时会重复启动 `start_next_subscription_job`）。
    """
    candidates = [item if isinstance(item, dict) else {} for item in (manual_candidates or [])]
    if not candidates:
        return "queued"
    appended = 0
    with subscription_queue_lock:
        signatures = {item.get("job_signature") for item in subscription_queue}
        for manual_candidate in candidates:
            job_signature = safe_json_dumps(
                {"task_name": task_name, "trigger": trigger, "manual_candidate": manual_candidate or {}}
            )
            if job_signature in signatures:
                continue
            signatures.add(job_signature)
            subscription_queue.append(
                {
                    "task_name": task_name,
                    "trigger": trigger,
                    "manual_candidate": manual_candidate or {},
                    "job_signature": job_signature,
                }
            )
            appended += 1
        subscription_status["queued"] = [item["task_name"] for item in subscription_queue]
        should_start = bool(appended) and not subscription_status["running"]
    schedule_ui_state_push(0)
    if should_start:
        submit_background(start_next_subscription_job, label="subscription-next")
        return "started"
    return "queued"


__all__ = [
    "start_next_subscription_job",
    "queue_subscription_job",
    "queue_subscription_jobs",
]
