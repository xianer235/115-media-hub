from typing import Any, Dict, Optional

from ..background import submit_background

from ..core import safe_json_dumps, schedule_ui_state_push, subscription_queue, subscription_status


async def start_next_subscription_job() -> None:
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
    job_signature = safe_json_dumps({"task_name": task_name, "trigger": trigger, "manual_candidate": manual_candidate or {}})
    if any(item.get("job_signature") == job_signature for item in subscription_queue):
        schedule_ui_state_push(0)
        return "queued"
    subscription_queue.append(
        {
            "task_name": task_name,
            "trigger": trigger,
            "manual_candidate": manual_candidate or {},
            "job_signature": job_signature,
        }
    )
    subscription_status["queued"] = [item["task_name"] for item in subscription_queue]
    schedule_ui_state_push(0)
    if subscription_status["running"]:
        return "queued"
    submit_background(start_next_subscription_job, label="subscription-next")
    return "started"


__all__ = [
    "start_next_subscription_job",
    "queue_subscription_job",
]
