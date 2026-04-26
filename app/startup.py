import asyncio
import os
import time
from datetime import datetime

from .core import *  # noqa: F401,F403
from .background import start_background_runtime, stop_background_runtime, submit_background
from .services.monitor import queue_monitor_job
from .services.resource import schedule_resource_job_refresh
from .services.sign115 import refresh_sign115_status, run_sign115_job
from .services.subscription import queue_subscription_job
from .services.tree import run_sync


@app.on_event("startup")
async def startup() -> None:
    bind_ui_event_loop()
    start_background_runtime()
    ensure_db()
    os.makedirs(LOG_DIR, exist_ok=True)
    restore_runtime_logs_from_files()

    for job in list_resource_jobs(limit=200):
        if job.get("status") == "submitted" and job.get("auto_refresh") and not str(job.get("last_triggered_at", "")).strip():
            submit_background(schedule_resource_job_refresh, int(job["id"]), label="resource-refresh-recover")
    submit_background(refresh_sign115_status, force_remote=False, trigger="startup", label="sign115-startup-status")

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
                    submit_background(run_sync, label="tree-cron-sync")
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

    async def subscription_scheduler() -> None:
        await asyncio.sleep(5)
        while True:
            now_dt = datetime.now()
            now_ts = now_dt.timestamp()
            cfg = get_config()
            prev_next_runs = dict(subscription_next_run)
            tasks = [normalize_subscription_task(task or {}) for task in cfg.get("subscription_tasks", []) or []]
            active_names = {task.get("name", "") for task in tasks if task.get("name")}

            for dead_name in list(subscription_last_run.keys()):
                if dead_name not in active_names:
                    subscription_last_run.pop(dead_name, None)
                    subscription_next_run.pop(dead_name, None)

            for task in tasks:
                name = str(task.get("name", "")).strip()
                if not name:
                    continue
                if not task.get("enabled", True):
                    subscription_next_run.pop(name, None)
                    continue

                window_meta = compute_subscription_schedule_window_meta(
                    weekdays=task.get("schedule_weekdays", []),
                    start_time=task.get("schedule_start_time", "00:00"),
                    end_time=task.get("schedule_end_time", "23:59"),
                    now=now_dt,
                )
                if not bool(window_meta.get("valid", False)):
                    subscription_next_run.pop(name, None)
                    continue

                interval_minutes = normalize_subscription_schedule_interval_minutes(
                    task.get("schedule_interval_minutes", 120),
                    fallback=120,
                )
                interval_seconds = max(60, interval_minutes * 60)

                if name not in subscription_last_run:
                    state = load_subscription_task_state(name, task.get("media_type", "movie"))
                    last_run_at = parse_resource_datetime_to_timestamp(str(state.get("last_run_at", "") or "").strip())
                    subscription_last_run[name] = last_run_at if last_run_at > 0 else 0.0

                if bool(window_meta.get("in_window", False)):
                    previous_run_ts = float(subscription_last_run.get(name, 0.0) or 0.0)
                    next_due_ts = previous_run_ts + interval_seconds if previous_run_ts > 0 else now_ts
                    if now_ts >= next_due_ts:
                        queue_subscription_job(name, "cron")
                        next_due_ts = now_ts + interval_seconds

                    active_end = window_meta.get("active_end")
                    active_end_ts = active_end.timestamp() if isinstance(active_end, datetime) else 0.0
                    if active_end_ts > 0 and next_due_ts < active_end_ts:
                        subscription_next_run[name] = format_subscription_schedule_next_run(
                            datetime.fromtimestamp(next_due_ts)
                        )
                    else:
                        next_window_start = window_meta.get("next_window_start")
                        if isinstance(next_window_start, datetime):
                            subscription_next_run[name] = format_subscription_schedule_next_run(next_window_start)
                        else:
                            subscription_next_run.pop(name, None)
                    continue

                next_window_start = window_meta.get("next_window_start")
                if isinstance(next_window_start, datetime):
                    subscription_next_run[name] = format_subscription_schedule_next_run(next_window_start)
                else:
                    subscription_next_run.pop(name, None)

            if subscription_next_run != prev_next_runs:
                schedule_ui_state_push(0)
            await asyncio.sleep(5)

    async def sign115_scheduler() -> None:
        await asyncio.sleep(8)
        while True:
            cfg = get_config()
            enabled = bool(cfg.get("sign115_enabled", False))
            cron_time = normalize_sign115_cron_time(cfg.get("sign115_cron_time", "09:00"))
            hour, minute = [int(part) for part in cron_time.split(":", 1)]
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")
            scheduled_today = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

            if enabled and str(cfg.get("cookie_115", "")).strip():
                if sign115_runtime.get("last_auto_date", "") != today and now >= scheduled_today:
                    sign115_runtime["last_auto_date"] = today
                    submit_background(run_sign115_job, "cron", label="sign115-cron")
            await asyncio.sleep(20)

    asyncio.create_task(scheduler())
    asyncio.create_task(monitor_scheduler())
    asyncio.create_task(subscription_scheduler())
    asyncio.create_task(sign115_scheduler())


@app.on_event("shutdown")
async def shutdown_background_runtime() -> None:
    stop_background_runtime()
