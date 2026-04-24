import asyncio

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

    asyncio.create_task(
        run_subscription_task(
            next_job["task_name"],
            trigger=next_job.get("trigger", "queued"),
        )
    )


def queue_subscription_job(task_name: str, trigger: str) -> str:
    job_signature = safe_json_dumps({"task_name": task_name, "trigger": trigger})
    if any(item.get("job_signature") == job_signature for item in subscription_queue):
        schedule_ui_state_push(0)
        return "queued"
    subscription_queue.append(
        {
            "task_name": task_name,
            "trigger": trigger,
            "job_signature": job_signature,
        }
    )
    subscription_status["queued"] = [item["task_name"] for item in subscription_queue]
    schedule_ui_state_push(0)
    if subscription_status["running"]:
        return "queued"
    asyncio.create_task(start_next_subscription_job())
    return "started"


__all__ = [
    "start_next_subscription_job",
    "queue_subscription_job",
]
