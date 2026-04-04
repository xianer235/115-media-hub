import asyncio
import os
import time
from datetime import datetime

from .core import *  # noqa: F401,F403
from .services.monitor import queue_monitor_job
from .services.resource import schedule_resource_job_refresh
from .services.tree import run_sync


@app.on_event("startup")
async def startup() -> None:
    ensure_db()
    os.makedirs(LOG_DIR, exist_ok=True)

    for job in list_resource_jobs(limit=200):
        if job.get("status") == "submitted" and job.get("auto_refresh") and not str(job.get("last_triggered_at", "")).strip():
            asyncio.create_task(schedule_resource_job_refresh(int(job["id"])))

    async def scheduler() -> None:
        await asyncio.sleep(5)
        last_run = time.time()
        while True:
            cfg = get_config()
            prev_next_run = task_status.get("next_run")
            raw_interval = cfg.get("cron_hour")
            try:
                interval_min = int(str(raw_interval).strip() or 0)
            except (TypeError, ValueError):
                interval_min = 0

            # 目录树定时频率 <= 0 表示关闭定时任务
            if interval_min > 0:
                next_ts = last_run + (interval_min * 60)
                task_status["next_run"] = datetime.fromtimestamp(next_ts).strftime("%H:%M:%S")
                if time.time() >= next_ts and not task_status["running"]:
                    last_run = time.time()
                    asyncio.create_task(run_sync())
            else:
                task_status["next_run"] = None
                # 关闭期间重置参考时间，避免重新启用后立刻连发
                last_run = time.time()
            if task_status.get("next_run") != prev_next_run:
                schedule_ui_state_push(0)
            await asyncio.sleep(5)

    async def monitor_scheduler() -> None:
        await asyncio.sleep(5)
        while True:
            now = time.time()
            cfg = get_config()
            prev_next_runs = dict(monitor_next_run)
            tasks = cfg.get("monitor_tasks", [])
            active_names = {task.get("name", "") for task in tasks if task.get("name")}

            for dead_name in list(monitor_last_run.keys()):
                if dead_name not in active_names:
                    monitor_last_run.pop(dead_name, None)
                    monitor_next_run.pop(dead_name, None)

            for task in tasks:
                name = task.get("name", "")
                cron_minutes = int(task.get("cron_minutes", 0) or 0)
                if not name:
                    continue
                if cron_minutes <= 0:
                    monitor_next_run.pop(name, None)
                    continue

                if name not in monitor_last_run:
                    monitor_last_run[name] = now
                next_ts = monitor_last_run[name] + (cron_minutes * 60)
                monitor_next_run[name] = datetime.fromtimestamp(next_ts).strftime("%H:%M:%S")
                if now >= next_ts:
                    queue_monitor_job(name, "cron")
            if monitor_next_run != prev_next_runs:
                schedule_ui_state_push(0)
            await asyncio.sleep(5)

    asyncio.create_task(scheduler())
    asyncio.create_task(monitor_scheduler())
