import asyncio
import os
import time
from datetime import datetime

from .core import *  # noqa: F401,F403
from .background import start_background_runtime, stop_background_runtime, submit_background
from .memory import release_process_memory
from .services.monitor import queue_monitor_job
from .services.monitor_changes import (
    cleanup_completed_monitor_change_events,
    recover_monitor_change_events,
    queue_ready_monitor_change_tasks,
)
from .services.resource import (
    is_resource_offline_link_type,
    offline_completion_watcher,
    pending_offline_job_counts_by_monitor,
    poll_offline_resource_jobs_once,
    schedule_resource_job_refresh,
)
from .services.sign115 import refresh_sign115_status, run_sign115_job
from .services.subscription import queue_subscription_job


MEMORY_HOUSEKEEPING_INTERVAL_SECONDS = max(
    60,
    min(3600, int(os.environ.get("MEMORY_HOUSEKEEPING_INTERVAL_SECONDS", 300) or 300)),
)


def _run_prune_step(callback) -> Dict[str, Any]:
    try:
        result = callback()
        return result if isinstance(result, dict) else {"removed": int(result or 0)}
    except Exception as exc:
        return {"error": str(exc)[:180]}


def prune_runtime_memory_caches() -> Dict[str, Any]:
    cfg = get_config()
    detail: Dict[str, Any] = {
        "core": _run_prune_step(lambda: prune_core_runtime_memory_caches(cfg)),
    }

    from .providers.pan115 import prune_115_list_cache
    from .providers.quark import prune_quark_share_memory_caches
    from .providers.tmdb import prune_tmdb_runtime_cache
    from .routes.pages import prune_page_runtime_caches
    from .routes.resource import prune_resource_image_cache
    from .routes.strm import prune_strm_runtime_caches
    from .services.notify import prune_notify_runtime_caches

    detail["pan115"] = _run_prune_step(prune_115_list_cache)
    detail["quark"] = _run_prune_step(prune_quark_share_memory_caches)
    detail["tmdb"] = _run_prune_step(lambda: prune_tmdb_runtime_cache(cfg))
    detail["pages"] = _run_prune_step(prune_page_runtime_caches)
    detail["resource_image"] = _run_prune_step(prune_resource_image_cache)
    detail["strm"] = _run_prune_step(prune_strm_runtime_caches)
    detail["notify"] = _run_prune_step(prune_notify_runtime_caches)
    return detail


@app.on_event("startup")
async def startup() -> None:
    bind_ui_event_loop()
    start_background_runtime()
    ensure_db()
    try:
        if cleanup_legacy_tree_config_file():
            await write_log("已清理 settings.json 中的旧目录树配置字段（trees/sync_mode/check_hash/cron_hour/last_hash）", "info")
    except Exception:
        pass
    # Reconcile mutations left between the remote operation and local STRM
    # processing before normal schedulers start issuing scans.
    recover_monitor_change_events(cfg=get_config())
    os.makedirs(LOG_DIR, exist_ok=True)
    restore_runtime_logs_from_files()

    for job in list_resource_jobs(limit=200):
        if job.get("status") == "submitted" and job.get("auto_refresh") and not str(job.get("last_triggered_at", "")).strip():
            if is_resource_offline_link_type(job.get("link_type", "")):
                submit_background(poll_offline_resource_jobs_once, label="offline-watch-recover")
            else:
                submit_background(schedule_resource_job_refresh, int(job["id"]), label="resource-refresh-recover")
    submit_background(refresh_sign115_status, force_remote=False, trigger="startup", label="sign115-startup-status")

    async def monitor_scheduler() -> None:
        await asyncio.sleep(5)
        while True:
            now = time.time()
            cfg = get_config()
            prev_next_runs = dict(monitor_next_run)
            tasks = cfg.get("monitor_tasks", [])
            active_names = {task.get("name", "") for task in tasks if task.get("name")}
            has_cron_task = any(
                int(task.get("cron_minutes", 0) or 0) > 0 for task in tasks if task.get("name")
            )
            pending_offline_counts = (
                pending_offline_job_counts_by_monitor() if has_cron_task else {}
            )

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
                    if pending_offline_counts.get(name, 0) > 0:
                        monitor_last_run[name] = now
                        monitor_next_run[name] = datetime.fromtimestamp(
                            now + (cron_minutes * 60)
                        ).strftime("%H:%M:%S")
                        await write_monitor_log(
                            f"存在 {pending_offline_counts[name]} 个未完成的 115 离线导入任务，"
                            "本次定时扫描顺延至下载完成后自动触发",
                            "warn",
                        )
                    else:
                        queue_monitor_job(name, "cron")
            queue_ready_monitor_change_tasks(cfg=cfg)
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

    async def memory_housekeeper() -> None:
        await asyncio.sleep(MEMORY_HOUSEKEEPING_INTERVAL_SECONDS)
        while True:
            await asyncio.to_thread(prune_runtime_memory_caches)
            await asyncio.to_thread(cleanup_completed_monitor_change_events)
            await asyncio.to_thread(release_process_memory, "runtime-housekeeping")
            await asyncio.sleep(MEMORY_HOUSEKEEPING_INTERVAL_SECONDS)

    async def resource_jobs_housekeeper() -> None:
        await asyncio.sleep(5)
        while True:
            await asyncio.to_thread(_run_prune_step, prune_resource_jobs_if_due)
            await asyncio.sleep(RESOURCE_JOB_PRUNE_INTERVAL_SECONDS)

    asyncio.create_task(monitor_scheduler())
    asyncio.create_task(offline_completion_watcher())
    asyncio.create_task(subscription_scheduler())
    asyncio.create_task(sign115_scheduler())
    asyncio.create_task(memory_housekeeper())
    asyncio.create_task(resource_jobs_housekeeper())


@app.on_event("shutdown")
async def shutdown_background_runtime() -> None:
    stop_background_runtime()
