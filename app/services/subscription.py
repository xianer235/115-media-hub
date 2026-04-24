import asyncio
import contextvars
import os
import time
import unicodedata

from ..core import *  # noqa: F401,F403
from .monitor import queue_monitor_job
from .notify import push_subscription_success_notification
from .resource import cancel_resource_job, run_resource_job
from .subscription_share_runtime import *  # noqa: F401,F403
from .subscription_episode import *  # noqa: F401,F403
from .subscription_share_selection import *  # noqa: F401,F403
from .subscription_runner import *  # noqa: F401,F403


def _load_subscription_task(cfg: Dict[str, Any], task_name: str) -> Dict[str, Any]:
    for raw_task in cfg.get("subscription_tasks", []) or []:
        task = normalize_subscription_task(raw_task or {})
        if task.get("name") == task_name:
            return task
    return {}


def _build_subscription_run_id(task_name: str) -> str:
    normalized_name = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(task_name or "").strip()).strip("-").lower()
    if not normalized_name:
        normalized_name = "task"
    return f"sub-{normalized_name[:36]}-{int(time.time() * 1000)}"


def _format_elapsed_seconds(seconds: float) -> str:
    normalized = max(0.0, float(seconds or 0.0))
    return f"{normalized:.2f}秒"


SUBSCRIPTION_STAGE_TIMING_ORDER: Tuple[Tuple[str, str], ...] = (
    ("prepare", "准备"),
    ("search", "搜索"),
    ("calibrate", "目录校准"),
    ("import", "候选导入"),
    ("finalize", "收口"),
)


SUBSCRIPTION_REASON_CODE_LABELS: Dict[str, str] = {
    "ok": "正常",
    "unknown": "未知原因",
    "no_precise_episode_match": "未匹配到缺失剧集文件",
    "manifest_no_precise_episode_match": "清单回退后仍未匹配到缺失剧集",
    "manifest_no_missing": "清单中未发现缺失剧集",
    "manifest_empty": "分享清单为空",
    "manifest_fallback": "按清单回退匹配",
    "no_episode_files": "未识别到剧集文件",
    "missing_episodes_empty": "缺失集为空",
    "cookie_missing": "未配置网盘 Cookie",
    "share_url_missing": "分享链接为空",
    "subdir_not_found": "未命中订阅子目录",
    "subdir_ambiguous": "订阅子目录匹配不唯一",
    "subdir_selection_empty": "子目录筛选结果为空",
    "target_is_share_root": "目标子目录等于分享根目录",
    "share_root_unreachable": "分享根目录不可访问",
    "share_anchor_unreachable": "锚点目录不可访问",
    "share_root_wrapper_unreachable": "分享根目录包装层不可访问",
    "subdir_entry_invalid": "子目录条目无效",
    "subdir_cid_missing": "子目录 CID 缺失",
    "subdir_branch_unreachable": "子目录分支不可访问",
    "subdir_target_invalid": "子目录目标无效",
    "not_found": "未找到匹配目录",
    "ambiguous": "匹配结果不唯一",
    "weak_match": "匹配度不足",
    "refine_selection_empty": "目录收敛后为空",
}


def _format_subscription_reason_code(reason_code: Any) -> str:
    normalized = str(reason_code or "").strip()
    if not normalized:
        return "未知原因"
    share_subdir_prefix = "share_subdir_"
    if normalized.startswith(share_subdir_prefix) and len(normalized) > len(share_subdir_prefix):
        nested = _format_subscription_reason_code(normalized[len(share_subdir_prefix):])
        return f"子目录解析：{nested}"
    return SUBSCRIPTION_REASON_CODE_LABELS.get(normalized, normalized)


def _format_subscription_reason_chain(reason_chain: Any) -> str:
    raw = str(reason_chain or "").strip()
    if not raw:
        return "未知原因"
    parts = [segment.strip() for segment in raw.split("->") if segment and segment.strip()]
    if not parts:
        return "未知原因"
    return " -> ".join([_format_subscription_reason_code(part) for part in parts])


def _create_subscription_stage_timer(initial_stage: str = "prepare") -> Dict[str, Any]:
    now = time.perf_counter()
    stage_name = str(initial_stage or "").strip().lower()
    return {
        "run_started_at": now,
        "current_stage": stage_name,
        "stage_started_at": now if stage_name else 0.0,
        "stages": {},
    }


def _subscription_stage_timer_enter(timer: Optional[Dict[str, Any]], stage_name: str) -> None:
    if not isinstance(timer, dict):
        return
    now = time.perf_counter()
    active_stage = str(timer.get("current_stage", "") or "").strip().lower()
    stage_started_at = float(timer.get("stage_started_at", 0.0) or 0.0)
    stage_durations = timer.get("stages")
    if not isinstance(stage_durations, dict):
        stage_durations = {}
        timer["stages"] = stage_durations
    if active_stage and stage_started_at > 0:
        stage_durations[active_stage] = float(stage_durations.get(active_stage, 0.0) or 0.0) + max(0.0, now - stage_started_at)
    next_stage = str(stage_name or "").strip().lower()
    timer["current_stage"] = next_stage
    timer["stage_started_at"] = now if next_stage else 0.0


def _subscription_stage_timer_snapshot(timer: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    now = time.perf_counter()
    if not isinstance(timer, dict):
        return {
            "total_seconds": 0.0,
            "stages": {},
        }
    run_started_at = float(timer.get("run_started_at", 0.0) or 0.0)
    if run_started_at <= 0:
        run_started_at = now
    stage_durations = timer.get("stages")
    normalized_stage_durations: Dict[str, float] = {}
    if isinstance(stage_durations, dict):
        normalized_stage_durations = {
            str(key or "").strip().lower(): max(0.0, float(value or 0.0))
            for key, value in stage_durations.items()
            if str(key or "").strip()
        }
    active_stage = str(timer.get("current_stage", "") or "").strip().lower()
    stage_started_at = float(timer.get("stage_started_at", 0.0) or 0.0)
    if active_stage and stage_started_at > 0:
        normalized_stage_durations[active_stage] = float(normalized_stage_durations.get(active_stage, 0.0) or 0.0) + max(
            0.0,
            now - stage_started_at,
        )
    return {
        "total_seconds": max(0.0, now - run_started_at),
        "stages": normalized_stage_durations,
    }


def _build_subscription_stage_timing_log_lines(timer: Optional[Dict[str, Any]]) -> Tuple[str, str]:
    snapshot = _subscription_stage_timer_snapshot(timer)
    stage_durations = snapshot.get("stages", {}) if isinstance(snapshot.get("stages"), dict) else {}
    parts = [
        f"{label} {_format_elapsed_seconds(float(stage_durations.get(stage_key, 0.0) or 0.0))}"
        for stage_key, label in SUBSCRIPTION_STAGE_TIMING_ORDER
    ]
    return (
        f"步骤耗时：{'｜'.join(parts)}",
        f"总用时：{_format_elapsed_seconds(float(snapshot.get('total_seconds', 0.0) or 0.0))}",
    )


def _collect_subscription_batch_success_jobs(created_job_ids: Set[int]) -> List[Dict[str, Any]]:
    success_jobs: List[Dict[str, Any]] = []
    unique_job_ids = sorted({max(0, int(job_id or 0)) for job_id in created_job_ids if int(job_id or 0) > 0})
    for job_id in unique_job_ids:
        job = get_resource_job(job_id, include_private=True)
        if not job:
            continue
        status = str(job.get("status", "") or "").strip().lower()
        if status not in ("submitted", "completed"):
            continue
        success_jobs.append(job)
    return success_jobs


def _recover_subscription_submitted_jobs(limit: int = 160) -> Dict[str, int]:
    jobs = list_resource_jobs_by_source("subscription_auto", limit=max(20, int(limit or 160)), scan_limit=1200)
    stale_jobs = [
        job
        for job in jobs
        if str(job.get("status", "") or "").strip().lower() == "submitted"
        and not str(job.get("last_triggered_at", "") or "").strip()
    ]
    if not stale_jobs:
        return {
            "checked": len(jobs),
            "stale": 0,
            "recovered": 0,
            "triggered_groups": 0,
            "triggered_jobs": 0,
            "skipped_no_monitor": 0,
            "skipped_missing_monitor": 0,
        }

    live_cfg = get_config()
    live_monitor_tasks = live_cfg.get("monitor_tasks", []) if isinstance(live_cfg.get("monitor_tasks"), list) else []
    active_monitor_tasks = {
        str(task.get("name", "") or "").strip()
        for task in live_monitor_tasks
        if str(task.get("name", "") or "").strip()
    }

    grouped_jobs: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    no_monitor_jobs: List[Dict[str, Any]] = []
    missing_monitor_jobs: List[Dict[str, Any]] = []
    for job in stale_jobs:
        monitor_task_name = str(job.get("monitor_task_name", "") or "").strip()
        savepath = normalize_relative_path(job.get("savepath", ""))
        if not monitor_task_name or not savepath:
            no_monitor_jobs.append(job)
            continue
        if monitor_task_name not in active_monitor_tasks:
            missing_monitor_jobs.append(job)
            continue
        grouped_jobs.setdefault((monitor_task_name, savepath), []).append(job)

    now_iso = now_text()
    completed_resource_ids: Set[int] = set()
    recovered = 0
    triggered_groups = 0
    triggered_jobs = 0
    skipped_no_monitor = 0
    skipped_missing_monitor = 0

    for job in no_monitor_jobs:
        job_id = max(0, int(job.get("id", 0) or 0))
        if job_id <= 0:
            continue
        base_detail = str(job.get("status_detail", "") or "").strip()
        detail = (
            f"{base_detail}；历史待刷新收口：当前保存路径未纳入文件夹监控，本次不触发 strm 刷新"
            if base_detail
            else "历史待刷新收口：当前保存路径未纳入文件夹监控，本次不触发 strm 刷新"
        )
        update_resource_job(
            job_id,
            status="completed",
            status_detail=detail,
            finished_at=now_iso,
        )
        recovered += 1
        skipped_no_monitor += 1
        resource_id = max(0, int(job.get("resource_id", 0) or 0))
        if resource_id > 0:
            completed_resource_ids.add(resource_id)

    for job in missing_monitor_jobs:
        job_id = max(0, int(job.get("id", 0) or 0))
        if job_id <= 0:
            continue
        monitor_task_name = str(job.get("monitor_task_name", "") or "").strip()
        base_detail = str(job.get("status_detail", "") or "").strip()
        detail = (
            f"{base_detail}；历史待刷新收口：监控任务「{monitor_task_name or '--'}」已不存在，跳过刷新"
            if base_detail
            else f"历史待刷新收口：监控任务「{monitor_task_name or '--'}」已不存在，跳过刷新"
        )
        update_resource_job(
            job_id,
            status="completed",
            status_detail=detail,
            finished_at=now_iso,
        )
        recovered += 1
        skipped_missing_monitor += 1
        resource_id = max(0, int(job.get("resource_id", 0) or 0))
        if resource_id > 0:
            completed_resource_ids.add(resource_id)

    for (monitor_task_name, savepath), grouped in grouped_jobs.items():
        queue_status = queue_monitor_job(
            monitor_task_name,
            "resource",
            {
                "savepath": savepath,
                "title": "历史待刷新收口",
            },
        )
        triggered_groups += 1
        for job in grouped:
            job_id = max(0, int(job.get("id", 0) or 0))
            if job_id <= 0:
                continue
            base_detail = str(job.get("status_detail", "") or "").strip()
            detail = (
                f"{base_detail}；历史待刷新收口：已统一触发监控「{monitor_task_name}」({queue_status})"
                if base_detail
                else f"历史待刷新收口：已统一触发监控「{monitor_task_name}」({queue_status})"
            )
            update_resource_job(
                job_id,
                status="completed",
                status_detail=detail,
                last_triggered_at=now_iso,
                finished_at=now_iso,
            )
            recovered += 1
            triggered_jobs += 1
            resource_id = max(0, int(job.get("resource_id", 0) or 0))
            if resource_id > 0:
                completed_resource_ids.add(resource_id)

    if completed_resource_ids:
        conn = open_db()
        try:
            for resource_id in sorted(completed_resource_ids):
                update_resource_item_status(conn, resource_id, "completed")
            conn.commit()
        finally:
            conn.close()

    return {
        "checked": len(jobs),
        "stale": len(stale_jobs),
        "recovered": recovered,
        "triggered_groups": triggered_groups,
        "triggered_jobs": triggered_jobs,
        "skipped_no_monitor": skipped_no_monitor,
        "skipped_missing_monitor": skipped_missing_monitor,
    }


def _finalize_subscription_batch_refresh(
    task_name: str,
    run_id: str,
    created_job_ids: Set[int],
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    result = {
        "run_id": str(run_id or "").strip(),
        "created_jobs": len({max(0, int(job_id or 0)) for job_id in created_job_ids if int(job_id or 0) > 0}),
        "successful_jobs": 0,
        "refresh_eligible_jobs": 0,
        "grouped_targets": 0,
        "triggered_groups": 0,
        "triggered_jobs": 0,
        "missing_monitor_task_groups": 0,
        "missing_monitor_task_jobs": 0,
    }
    if not result["run_id"] or result["created_jobs"] <= 0:
        return result

    success_jobs = _collect_subscription_batch_success_jobs(created_job_ids)
    result["successful_jobs"] = len(success_jobs)
    if not success_jobs:
        return result

    grouped_jobs: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    non_refresh_jobs: List[Dict[str, Any]] = []
    for job in success_jobs:
        monitor_task_name = str(job.get("monitor_task_name", "") or "").strip()
        savepath = normalize_relative_path(job.get("savepath", ""))
        if not monitor_task_name or not savepath:
            non_refresh_jobs.append(job)
            continue
        grouped_jobs.setdefault((monitor_task_name, savepath), []).append(job)
    result["refresh_eligible_jobs"] = sum(len(jobs) for jobs in grouped_jobs.values())
    result["grouped_targets"] = len(grouped_jobs)

    live_cfg = get_config()
    live_monitor_tasks = live_cfg.get("monitor_tasks", []) if isinstance(live_cfg.get("monitor_tasks"), list) else []
    fallback_monitor_tasks = cfg.get("monitor_tasks", []) if isinstance(cfg.get("monitor_tasks"), list) else []
    source_monitor_tasks = live_monitor_tasks or fallback_monitor_tasks
    active_monitor_tasks = {
        str(task.get("name", "") or "").strip()
        for task in source_monitor_tasks
        if str(task.get("name", "") or "").strip()
    }
    now_iso = now_text()
    completed_resource_ids: Set[int] = set()

    for job in non_refresh_jobs:
        job_id = max(0, int(job.get("id", 0) or 0))
        if job_id <= 0:
            continue
        base_detail = str(job.get("status_detail", "") or "").strip()
        detail = (
            f"{base_detail}；当前保存路径未纳入文件夹监控，本次不触发 strm 刷新"
            if base_detail
            else "当前保存路径未纳入文件夹监控，本次不触发 strm 刷新"
        )
        update_resource_job(
            job_id,
            status="completed",
            status_detail=detail,
            finished_at=now_iso,
        )
        resource_id = max(0, int(job.get("resource_id", 0) or 0))
        if resource_id > 0:
            completed_resource_ids.add(resource_id)

    if not grouped_jobs:
        if completed_resource_ids:
            conn = open_db()
            try:
                for resource_id in sorted(completed_resource_ids):
                    update_resource_item_status(conn, resource_id, "completed")
                conn.commit()
            finally:
                conn.close()
        return result

    for (monitor_task_name, savepath), jobs in grouped_jobs.items():
        if monitor_task_name not in active_monitor_tasks:
            result["missing_monitor_task_groups"] += 1
            result["missing_monitor_task_jobs"] += len(jobs)
            for job in jobs:
                job_id = max(0, int(job.get("id", 0) or 0))
                if job_id <= 0:
                    continue
                base_detail = str(job.get("status_detail", "") or "").strip()
                detail = (
                    f"{base_detail}；订阅批次 {result['run_id']} 跳过刷新：监控任务「{monitor_task_name}」已不存在"
                    if base_detail
                    else f"订阅批次 {result['run_id']} 跳过刷新：监控任务「{monitor_task_name}」已不存在"
                )
                update_resource_job(
                    job_id,
                    status="completed",
                    status_detail=detail,
                    finished_at=now_iso,
                )
                resource_id = max(0, int(job.get("resource_id", 0) or 0))
                if resource_id > 0:
                    completed_resource_ids.add(resource_id)
            continue

        queue_status = queue_monitor_job(
            monitor_task_name,
            "resource",
            {
                "savepath": savepath,
                "title": f"订阅批次收口：{task_name}",
            },
        )
        result["triggered_groups"] += 1
        for job in jobs:
            job_id = max(0, int(job.get("id", 0) or 0))
            if job_id <= 0:
                continue
            base_detail = str(job.get("status_detail", "") or "").strip()
            detail = (
                f"{base_detail}；订阅批次 {result['run_id']} 已统一触发监控：{monitor_task_name} ({queue_status})"
                if base_detail
                else f"订阅批次 {result['run_id']} 已统一触发监控：{monitor_task_name} ({queue_status})"
            )
            update_resource_job(
                job_id,
                status="completed",
                status_detail=detail,
                last_triggered_at=now_iso,
                finished_at=now_iso,
            )
            result["triggered_jobs"] += 1
            resource_id = max(0, int(job.get("resource_id", 0) or 0))
            if resource_id > 0:
                completed_resource_ids.add(resource_id)

    if completed_resource_ids:
        conn = open_db()
        try:
            for resource_id in sorted(completed_resource_ids):
                update_resource_item_status(conn, resource_id, "completed")
            conn.commit()
        finally:
            conn.close()

    return result


def get_subscription_task_episode_view(task_name: str) -> Dict[str, Any]:
    payload = _scan_subscription_task_episode_view_payload(task_name)
    return payload


def _scan_subscription_task_episode_view_payload(task_name: str) -> Dict[str, Any]:
    normalized_task_name = str(task_name or "").strip()
    if not normalized_task_name:
        raise RuntimeError("任务名称不能为空")

    cfg = get_config()
    task = _load_subscription_task(cfg, normalized_task_name)
    if not task:
        raise KeyError(normalized_task_name)

    if str(task.get("media_type", "movie") or "movie").strip().lower() != "tv":
        raise ValueError("仅电视剧任务支持集数视图")

    provider = normalize_subscription_provider(task.get("provider", "115"), fallback="115")

    base_savepath = normalize_relative_path(str(task.get("savepath", "")).strip())
    if not base_savepath:
        raise RuntimeError("任务未配置保存路径")

    scan_savepath = resolve_subscription_tv_base_savepath(task, base_savepath) or base_savepath
    folder_id = ""
    scan_result: Dict[str, Any] = {}
    if provider == "quark":
        cookie_quark = str(cfg.get("cookie_quark", "")).strip()
        if not cookie_quark:
            raise RuntimeError("请先在参数配置页填写 Quark Cookie")
        folder_id = ensure_quark_folder_id_by_path(cookie_quark, scan_savepath)
        scan_result = _scan_quark_existing_tv_episodes(cookie_quark, folder_id, task)
    else:
        cookie_115 = str(cfg.get("cookie_115", "")).strip()
        if not cookie_115:
            raise RuntimeError("请先在参数配置页填写 115 Cookie")
        folder_id = ensure_115_folder_id_by_path(cookie_115, scan_savepath)
        scan_result = _scan_115_existing_tv_episodes(cookie_115, folder_id, task)

    scan_episodes = scan_result.get("episodes", []) if isinstance(scan_result.get("episodes"), list) else []
    existing_episodes = sorted(
        {
            max(0, int(item or 0))
            for item in scan_episodes
            if 0 < max(0, int(item or 0)) <= 5000
        }
    )

    state = load_subscription_task_state(normalized_task_name, "tv")
    known_total = resolve_subscription_tv_total_episodes(
        task,
        state_total=max(0, int(state.get("total_episodes", 0) or 0)),
    )
    last_episode = max(0, int(state.get("last_episode", 0) or 0))
    max_episode = existing_episodes[-1] if existing_episodes else 0

    display_total = _compute_subscription_episode_display_total(
        known_total=known_total,
        last_episode=last_episode,
        max_episode=max_episode,
        multi_season_mode=is_subscription_multi_season_mode(task),
    )

    present_in_display = sum(1 for episode_no in existing_episodes if 1 <= episode_no <= display_total)
    missing_count = max(0, display_total - present_in_display)

    return {
        "task_name": normalized_task_name,
        "provider": provider,
        "media_type": "tv",
        "savepath": scan_savepath,
        "folder_id": str(folder_id or "").strip(),
        "existing_episodes": existing_episodes,
        "existing_count": len(existing_episodes),
        "max_episode": max_episode,
        "last_episode": last_episode,
        "total_episodes": known_total,
        "display_total_episodes": display_total,
        "missing_count": missing_count,
        "scan_stats": {
            "scanned_dirs": int(scan_result.get("scanned_dirs", 0) or 0),
            "scanned_entries": int(scan_result.get("scanned_entries", 0) or 0),
            "failed_dirs": int(scan_result.get("failed_dirs", 0) or 0),
            "truncated": bool(scan_result.get("truncated", False)),
        },
    }


def _compute_subscription_episode_display_total(
    known_total: int,
    last_episode: int,
    max_episode: int,
    multi_season_mode: bool,
) -> int:
    normalized_known_total = max(0, int(known_total or 0))
    normalized_last_episode = max(0, int(last_episode or 0))
    normalized_max_episode = max(0, int(max_episode or 0))

    # 单季模式下优先展示当前季总集数，避免历史多季进度把视图总格子抬高。
    if (not bool(multi_season_mode)) and normalized_known_total > 0:
        display_total = max(normalized_known_total, normalized_max_episode)
    else:
        display_total = max(normalized_known_total, normalized_last_episode, normalized_max_episode)

    if display_total <= 0:
        display_total = 60
    elif normalized_known_total <= 0 and display_total < 24:
        display_total = 24
    return max(1, min(1200, int(display_total)))


def rebuild_subscription_task_progress(task_name: str) -> Dict[str, Any]:
    normalized_task_name = str(task_name or "").strip()
    if not normalized_task_name:
        raise RuntimeError("任务名称不能为空")
    if subscription_status.get("running") and str(subscription_status.get("current_task", "") or "").strip() == normalized_task_name:
        raise RuntimeError("任务正在运行，请先中断后再重建")

    payload = _scan_subscription_task_episode_view_payload(normalized_task_name)
    scan_stats = payload.get("scan_stats", {}) if isinstance(payload.get("scan_stats"), dict) else {}
    scan_scanned_dirs = max(0, int(scan_stats.get("scanned_dirs", 0) or 0))
    scan_failed_dirs = max(0, int(scan_stats.get("failed_dirs", 0) or 0))
    scan_scanned_entries = max(0, int(scan_stats.get("scanned_entries", 0) or 0))
    scan_reliable = not (scan_scanned_dirs <= 0 and scan_failed_dirs > 0)
    if not scan_reliable:
        raise RuntimeError("目标目录扫描结果不可靠，请稍后重试")

    cfg = get_config()
    task = _load_subscription_task(cfg, normalized_task_name)
    if not task:
        raise KeyError(normalized_task_name)

    existing_episodes = {
        max(0, int(item or 0))
        for item in (payload.get("existing_episodes", []) if isinstance(payload.get("existing_episodes"), list) else [])
        if max(0, int(item or 0)) > 0
    }
    existing_count = len(existing_episodes)
    rebuilt_last_episode = max(existing_episodes) if existing_episodes else 0

    state = load_subscription_task_state(normalized_task_name, "tv")
    previous_last_episode = max(0, int(state.get("last_episode", 0) or 0))
    previous_status = str(state.get("status", "idle") or "idle").strip().lower() or "idle"
    previous_stats = state.get("stats", {}) if isinstance(state.get("stats"), dict) else {}
    known_total = resolve_subscription_tv_total_episodes(
        task,
        state_total=max(0, int(state.get("total_episodes", 0) or 0)),
    )

    ledger_sync = reconcile_subscription_episode_ledger(normalized_task_name, existing_episodes)
    activated_count = max(0, int(ledger_sync.get("activated", 0) or 0))
    staled_count = max(0, int(ledger_sync.get("staled", 0) or 0))
    active_ledger_count = sum(
        1
        for row in load_subscription_episode_ledger(normalized_task_name, include_stale=False).values()
        if str((row or {}).get("status", "active") or "active").strip().lower() == "active"
    )

    rebuilt_status = "completed" if known_total > 0 and rebuilt_last_episode >= known_total else "waiting"
    progress_label = f"E{rebuilt_last_episode}" if rebuilt_last_episode > 0 else "E0"
    total_label = f" / E{known_total}" if known_total > 0 else ""
    if existing_count > 0:
        detail = f"已按目标目录重建追更进度：{progress_label}{total_label}（识别 {existing_count} 集）"
    elif scan_scanned_entries <= 0:
        detail = f"已按目标目录重建追更进度：{progress_label}{total_label}（目录未识别到剧集文件）"
    else:
        detail = f"已按目标目录重建追更进度：{progress_label}{total_label}"
    if activated_count > 0 or staled_count > 0:
        detail += f"；账本恢复 {activated_count} 集 / 标记失效 {staled_count} 集"
    if rebuilt_status == "completed":
        detail += "；当前已与总集数对齐"
    else:
        detail += "；等待后续追更"

    merged_stats = {
        **previous_stats,
        "existing_episode_scan_ready": True,
        "existing_episode_count": existing_count,
        "existing_episode_max": rebuilt_last_episode,
        "existing_episode_scanned_dirs": scan_scanned_dirs,
        "existing_episode_scanned_entries": scan_scanned_entries,
        "existing_episode_failed_dirs": scan_failed_dirs,
        "existing_episode_scan_truncated": bool(scan_stats.get("truncated", False)),
        "episode_ledger_activated": activated_count,
        "episode_ledger_staled": staled_count,
        "episode_ledger_active_count": active_ledger_count,
        "rebuild_from_directory": True,
        "rebuild_previous_last_episode": previous_last_episode,
        "rebuild_previous_status": previous_status,
        "rebuild_at": now_text(),
    }
    upsert_subscription_task_state(
        normalized_task_name,
        media_type="tv",
        status=rebuilt_status,
        progress=100,
        detail=detail,
        last_error="",
        last_episode=rebuilt_last_episode,
        total_episodes=known_total,
        stats=merged_stats,
    )

    updated_payload = _scan_subscription_task_episode_view_payload(normalized_task_name)
    return {
        "task_name": normalized_task_name,
        "status": rebuilt_status,
        "detail": detail,
        "last_episode": rebuilt_last_episode,
        "previous_last_episode": previous_last_episode,
        "total_episodes": known_total,
        "existing_count": existing_count,
        "episode_view": updated_payload,
        "ledger": {
            "activated": activated_count,
            "staled": staled_count,
            "active_count": active_ledger_count,
        },
    }


def _sync_task_total_episodes(task_name: str, total_episodes: int) -> None:
    normalized_total = max(0, int(total_episodes or 0))
    if normalized_total <= 0:
        return
    cfg = get_config()
    tasks = cfg.get("subscription_tasks", []) if isinstance(cfg.get("subscription_tasks"), list) else []
    changed = False
    updated = []
    for raw_task in tasks:
        task = normalize_subscription_task(raw_task or {})
        if task.get("name") == task_name and int(task.get("total_episodes", 0) or 0) <= 0:
            if not is_subscription_multi_season_mode(task):
                tmdb_season_total = get_subscription_tmdb_season_total_episodes(task)
                if tmdb_season_total > 0:
                    updated.append(task)
                    continue
            task["total_episodes"] = normalized_total
            changed = True
        updated.append(task)
    if changed:
        cfg["subscription_tasks"] = updated
        save_config(cfg)


def _build_subscription_search_keywords(task: Dict[str, Any], limit: int = 4) -> List[str]:
    title = re.sub(r"\s+", " ", str(task.get("title", "") or "").strip())
    aliases = task.get("aliases", []) if isinstance(task.get("aliases"), list) else []
    tmdb_title = re.sub(r"\s+", " ", str(task.get("tmdb_title", "") or "").strip())
    tmdb_original_title = re.sub(r"\s+", " ", str(task.get("tmdb_original_title", "") or "").strip())
    tmdb_aliases = task.get("tmdb_aliases", []) if isinstance(task.get("tmdb_aliases"), list) else []
    media_type = str(task.get("media_type", "movie") or "movie").strip().lower()
    anime_mode = is_subscription_anime_compatible_task(task)
    multi_season_mode = is_subscription_multi_season_mode(task)
    year = normalize_tmdb_year(task.get("year", "")) or normalize_tmdb_year(task.get("tmdb_year", ""))
    season = max(1, int(task.get("season", 1) or 1))

    keywords: List[str] = []
    if title:
        keywords.append(title)
        if media_type == "movie" and year and re.fullmatch(r"(19|20)\d{2}", year):
            keywords.append(f"{title} {year}")
        if media_type == "tv" and season > 1 and not multi_season_mode:
            keywords.append(f"{title} S{season:02d}")
            keywords.append(f"{title} 第{season}季")
        if media_type == "tv" and anime_mode:
            keywords.append(f"{title} 动漫")
    if tmdb_title:
        keywords.append(tmdb_title)
        if media_type == "movie" and year:
            keywords.append(f"{tmdb_title} {year}")
        if media_type == "tv" and season > 1 and not multi_season_mode:
            keywords.append(f"{tmdb_title} S{season:02d}")
    if tmdb_original_title:
        keywords.append(tmdb_original_title)
    for alias in tmdb_aliases:
        alias_keyword = re.sub(r"\s+", " ", str(alias or "").strip())
        if alias_keyword:
            keywords.append(alias_keyword)
    for alias in aliases:
        alias_keyword = re.sub(r"\s+", " ", str(alias or "").strip())
        if alias_keyword:
            keywords.append(alias_keyword)

    seen: Set[str] = set()
    normalized_keywords: List[str] = []
    for keyword in keywords:
        marker = keyword.lower()
        if marker in seen:
            continue
        seen.add(marker)
        normalized_keywords.append(keyword)
    return normalized_keywords[: max(1, int(limit or 6))]


def _merge_subscription_search_errors(errors: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    merged: List[Dict[str, str]] = []
    seen: Set[str] = set()
    for raw in errors:
        payload = raw if isinstance(raw, dict) else {}
        channel_id = str(payload.get("channel_id", "") or "").strip()
        message = str(payload.get("message", "") or "").strip()
        if not channel_id and not message:
            continue
        key = f"{channel_id}|{message}"
        if key in seen:
            continue
        seen.add(key)
        merged.append(
            {
                "channel_id": channel_id,
                "name": str(payload.get("name", "") or channel_id).strip(),
                "message": message,
            }
        )
    return merged




async def find_subscription_task_match_candidate_by_search(
    task: Dict[str, Any],
    last_episode: int = 0,
    trigger: str = "",
) -> Dict[str, Any]:
    provider = normalize_subscription_provider(task.get("provider", "115"), fallback="115")
    search_identity_mode = "link" if provider == "quark" else "message"
    trigger_mode = str(trigger or "").strip().lower()
    incremental_search_enabled = trigger_mode == "cron"
    task_name = str(task.get("name", "") or task.get("title", "") or "").strip()
    baseline_channel_watermarks = (
        load_subscription_channel_search_watermarks(task_name)
        if (incremental_search_enabled and task_name)
        else {}
    )
    incremental_since_cursor_by_channel: Dict[str, int] = {
        normalize_telegram_channel_id_from_input(channel_id): max(0, int((payload or {}).get("last_post_cursor", 0) or 0))
        for channel_id, payload in (baseline_channel_watermarks.items() if isinstance(baseline_channel_watermarks, dict) else [])
        if normalize_telegram_channel_id_from_input(channel_id)
    }
    observed_channel_watermarks: Dict[str, Dict[str, Any]] = {}
    incremental_error_channels: Set[str] = set()
    incremental_stop_channels = 0
    channel_support_stats_deltas: Dict[str, Dict[str, Any]] = {}
    query_tokens = build_subscription_query_tokens(task)
    if not query_tokens:
        return {"candidate": {}, "keywords": [], "stats": {}, "errors": []}

    keywords = _build_subscription_search_keywords(task, limit=6)
    all_items: List[Dict[str, Any]] = []
    all_errors: List[Dict[str, Any]] = []
    searched_sources = 0
    matched_channels = 0
    pages_scanned = 0

    for keyword in keywords:
        check_subscription_cancelled()
        search_meta = await search_resource_sources(
            keyword,
            identity_mode=search_identity_mode,
            incremental_since_cursor_by_channel=(
                incremental_since_cursor_by_channel if incremental_search_enabled else None
            ),
        )
        all_items.extend(search_meta.get("items", []) if isinstance(search_meta.get("items"), list) else [])
        all_errors.extend(search_meta.get("errors", []) if isinstance(search_meta.get("errors"), list) else [])
        searched_sources += max(0, int(search_meta.get("searched_sources", 0) or 0))
        matched_channels += max(0, int(search_meta.get("matched_channels", 0) or 0))
        pages_scanned += max(0, int(search_meta.get("pages_scanned", 0) or 0))
        channel_stats = search_meta.get("channel_stats", []) if isinstance(search_meta.get("channel_stats"), list) else []
        for raw_row in channel_stats:
            if not isinstance(raw_row, dict):
                continue
            channel_id = normalize_telegram_channel_id_from_input(raw_row.get("channel_id", ""))
            if not channel_id:
                continue
            row = channel_support_stats_deltas.setdefault(
                channel_id,
                {
                    "channel_id": channel_id,
                    "channel_name": str(raw_row.get("name", "") or channel_id).strip() or channel_id,
                    "searched_runs": 0,
                    "matched_runs": 0,
                    "matched_items": 0,
                    "error_runs": 0,
                    "incremental_stop_hits": 0,
                    "pages_scanned": 0,
                    "last_error": "",
                },
            )
            row["searched_runs"] = int(row.get("searched_runs", 0) or 0) + 1
            matched = bool(raw_row.get("matched", False))
            item_count = max(0, int(raw_row.get("item_count", 0) or 0))
            row["matched_runs"] = int(row.get("matched_runs", 0) or 0) + (1 if matched else 0)
            row["matched_items"] = int(row.get("matched_items", 0) or 0) + item_count
            row["pages_scanned"] = int(row.get("pages_scanned", 0) or 0) + max(
                0,
                int(raw_row.get("pages_scanned", 0) or 0),
            )
            if bool(raw_row.get("incremental_stop_hit", False)):
                row["incremental_stop_hits"] = int(row.get("incremental_stop_hits", 0) or 0) + 1
            error_text = str(raw_row.get("error", "") or "").strip()
            if error_text:
                row["error_runs"] = int(row.get("error_runs", 0) or 0) + 1
                row["last_error"] = error_text[:300]
        if incremental_search_enabled:
            incremental_stop_channels += max(0, int(search_meta.get("incremental_stop_channels", 0) or 0))
            channel_watermarks = (
                search_meta.get("channel_watermarks", {})
                if isinstance(search_meta.get("channel_watermarks"), dict)
                else {}
            )
            for raw_channel_id, raw_payload in channel_watermarks.items():
                channel_id = normalize_telegram_channel_id_from_input(raw_channel_id)
                if not channel_id or not isinstance(raw_payload, dict):
                    continue
                candidate_cursor = max(0, int(raw_payload.get("last_post_cursor", 0) or 0))
                candidate_published_at = str(raw_payload.get("last_published_at", "") or "").strip()
                existing_payload = observed_channel_watermarks.get(channel_id, {})
                existing_cursor = max(0, int(existing_payload.get("last_post_cursor", 0) or 0))
                existing_published_at = str(existing_payload.get("last_published_at", "") or "").strip()
                existing_published_ts = parse_resource_datetime_to_timestamp(existing_published_at)
                candidate_published_ts = parse_resource_datetime_to_timestamp(candidate_published_at)
                if candidate_cursor > existing_cursor:
                    observed_channel_watermarks[channel_id] = {
                        "channel_id": channel_id,
                        "last_post_cursor": candidate_cursor,
                        "last_published_at": candidate_published_at,
                    }
                    continue
                if candidate_cursor == existing_cursor and candidate_published_ts > existing_published_ts:
                    observed_channel_watermarks[channel_id] = {
                        "channel_id": channel_id,
                        "last_post_cursor": candidate_cursor,
                        "last_published_at": candidate_published_at,
                    }
            channel_errors = search_meta.get("errors", []) if isinstance(search_meta.get("errors"), list) else []
            for err in channel_errors:
                if not isinstance(err, dict):
                    continue
                channel_id = normalize_telegram_channel_id_from_input(err.get("channel_id", ""))
                if channel_id:
                    incremental_error_channels.add(channel_id)

    deduped_items = dedupe_resource_item_dicts(all_items, identity_mode=search_identity_mode)
    deduped_items.sort(key=get_resource_item_sort_key, reverse=True)
    if provider == "quark":
        expanded_quark_items: List[Dict[str, Any]] = []
        for raw_item in deduped_items:
            expanded_quark_items.extend(_expand_subscription_quark_item_variants(raw_item))
        deduped_items = dedupe_resource_item_dicts(expanded_quark_items, identity_mode="link")
        deduped_items.sort(key=get_resource_item_sort_key, reverse=True)
    merged_errors = _merge_subscription_search_errors(all_errors)
    incremental_channels_advanced = 0
    channel_support_rows_updated = 0
    if incremental_search_enabled and task_name and observed_channel_watermarks:
        writable_channel_watermarks: Dict[str, Dict[str, Any]] = {}
        for channel_id, payload in observed_channel_watermarks.items():
            normalized_channel_id = normalize_telegram_channel_id_from_input(channel_id)
            if not normalized_channel_id or normalized_channel_id in incremental_error_channels:
                continue
            if not isinstance(payload, dict):
                continue
            writable_channel_watermarks[normalized_channel_id] = {
                "last_post_cursor": max(0, int(payload.get("last_post_cursor", 0) or 0)),
                "last_published_at": str(payload.get("last_published_at", "") or "").strip(),
                "last_run_at": now_text(),
            }
        incremental_channels_advanced = upsert_subscription_channel_search_watermarks(
            task_name,
            writable_channel_watermarks,
            only_increase=True,
        )
    if task_name and channel_support_stats_deltas:
        now_iso = now_text()
        writable_support_stats: Dict[str, Dict[str, Any]] = {}
        for channel_id, payload in channel_support_stats_deltas.items():
            normalized_channel_id = normalize_telegram_channel_id_from_input(channel_id)
            if not normalized_channel_id or not isinstance(payload, dict):
                continue
            writable_support_stats[normalized_channel_id] = {
                **payload,
                "last_searched_at": now_iso,
                "last_matched_at": now_iso if int(payload.get("matched_runs", 0) or 0) > 0 else "",
            }
        channel_support_rows_updated = upsert_subscription_channel_support_stats(
            writable_support_stats,
            task_name=task_name,
            provider=provider,
            trigger=trigger_mode,
        )
    min_score = (
        max(30, min(100, int(SUBSCRIPTION_QUARK_MIN_SCORE or 60)))
        if provider == "quark"
        else max(30, min(100, int(task.get("min_score", SUBSCRIPTION_MIN_SCORE) or SUBSCRIPTION_MIN_SCORE)))
    )
    persisted_items: List[Dict[str, Any]] = []
    ensure_db()
    conn = open_db()
    try:
        for raw_item in deduped_items:
            item = raw_item if isinstance(raw_item, dict) else {}
            item_id, _ = upsert_resource_item(conn, item, identity_mode=search_identity_mode)
            if item_id <= 0:
                continue
            normalized_item = {**item, "id": item_id}
            extra = normalized_item.get("extra") if isinstance(normalized_item.get("extra"), dict) else {}
            source_post_id = str(
                normalized_item.get("source_post_id", "") or extra.get("source_post_id", "")
            ).strip()
            if source_post_id:
                normalized_item["source_post_id"] = source_post_id
            persisted_items.append(normalized_item)
        conn.commit()
    finally:
        conn.close()

    # 频道聚合时同一资源可能被多次命中；这里按资源主键/链接去重，避免后续重复候选。
    deduped_persisted_items: List[Dict[str, Any]] = []
    seen_persisted_keys: Set[str] = set()
    for item in persisted_items:
        item_id = int(item.get("id", 0) or 0)
        link_key = _normalize_subscription_candidate_link(item.get("link_url", ""))
        if provider == "quark":
            item_extra = item.get("extra") if isinstance(item.get("extra"), dict) else safe_json_loads(item.get("extra_json"), {})
            receive_code = normalize_receive_code(item.get("receive_code", "")) or normalize_receive_code(
                (item_extra or {}).get("receive_code", "")
            )
            share_key = _build_subscription_quark_share_dedupe_key(
                link_key,
                item.get("raw_text", ""),
                receive_code,
            )
            unique_key = f"share:{share_key}" if share_key else (f"id:{item_id}" if item_id > 0 else f"url:{link_key}")
        else:
            unique_key = f"id:{item_id}" if item_id > 0 else f"url:{link_key}"
        if unique_key in seen_persisted_keys:
            continue
        seen_persisted_keys.add(unique_key)
        deduped_persisted_items.append(item)
    persisted_items = deduped_persisted_items

    candidates: List[Dict[str, Any]] = []
    relaxed_candidates: List[Dict[str, Any]] = []
    scored_candidates: List[Dict[str, Any]] = []
    supported_items = 0
    unsupported_items = 0
    media_guard_filtered = 0
    media_guard_reasons: Dict[str, int] = {}
    season_guard_filtered = 0
    supported_link_types = {"quark"} if provider == "quark" else {"magnet", "115share"}
    media_type = str(task.get("media_type", "movie") or "movie").strip().lower()
    single_season_tv = media_type == "tv" and (not is_subscription_multi_season_mode(task))
    target_season = max(1, int(task.get("season", 1) or 1))
    title_blocked_candidates = 0
    quark_low_score_kept = 0
    quark_media_relaxed_pass = 0
    seen_quark_scored_keys: Set[str] = set()
    for item in persisted_items:
        link_url = str(item.get("link_url", "") or "").strip()
        link_type = resolve_resource_link_type(item.get("link_type", ""), link_url)
        if link_type not in supported_link_types:
            unsupported_items += 1
            continue
        media_match, media_reason = match_subscription_media_type(task, item)
        if not media_match:
            if provider == "quark" and media_type == "tv" and str(media_reason or "").strip() == "missing_episode_meta":
                # 夸克剧集标题经常只保留剧名，不带标准季集字段；此类候选交给后续标题/精细扫描再判定。
                quark_media_relaxed_pass += 1
            else:
                media_guard_filtered += 1
                reason_key = str(media_reason or "unknown").strip() or "unknown"
                media_guard_reasons[reason_key] = int(media_guard_reasons.get(reason_key, 0) or 0) + 1
                continue
        supported_items += 1
        item_id = int(item.get("id", 0) or 0)
        matched_before = has_subscription_match(task.get("name", ""), item_id)
        scored = (
            score_subscription_candidate_quark(task, item, query_tokens, last_episode)
            if provider == "quark"
            else score_subscription_candidate(task, item, query_tokens, last_episode)
        )
        if provider == "quark" and not bool(scored.get("title_match", False)):
            media_guard_filtered += 1
            title_blocked_candidates += 1
            reason_key = "title_mismatch"
            media_guard_reasons[reason_key] = int(media_guard_reasons.get(reason_key, 0) or 0) + 1
            continue
        if provider == "quark":
            item_extra = item.get("extra") if isinstance(item.get("extra"), dict) else safe_json_loads(item.get("extra_json"), {})
            receive_code = normalize_receive_code(item.get("receive_code", "")) or normalize_receive_code(
                (item_extra or {}).get("receive_code", "")
            )
            scored_share_key = _build_subscription_quark_share_dedupe_key(link_url, item.get("raw_text", ""), receive_code)
            if scored_share_key:
                if scored_share_key in seen_quark_scored_keys:
                    continue
                seen_quark_scored_keys.add(scored_share_key)
        if single_season_tv:
            candidate_season = max(0, int(scored.get("season", 0) or 0))
            if candidate_season > 0 and candidate_season != target_season:
                season_guard_filtered += 1
                continue
        if matched_before:
            # 电影保持“同资源仅命中一次”；电视剧允许历史命中资源再次进入候选，
            # 后续由目录缺失判定决定是否需要重导（覆盖手动删档、补档场景）。
            if media_type != "tv":
                continue
            if int(scored.get("episode", 0) or 0) <= 0 and int(scored.get("range_end", 0) or 0) <= 0:
                continue
            scored["matched_before"] = True
        scored_candidates.append(scored)
        keep_candidate = int(scored.get("score", 0) or 0) >= min_score
        if (not keep_candidate) and provider == "quark" and media_type == "tv" and bool(scored.get("title_match", False)):
            # quark 电视剧场景优先保证召回：标题命中即可入队，低分放在队尾处理。
            keep_candidate = True
            quark_low_score_kept += 1
            scored["low_score_fallback"] = True
        if not keep_candidate:
            if provider != "quark" and media_type == "tv":
                episode_no = int(scored.get("episode", 0) or 0)
                token_hits = int(scored.get("token_hits", 0) or 0)
                if episode_no > 0 and token_hits > 0:
                    relaxed_candidates.append(scored)
            continue
        candidates.append(scored)

    if media_type == "tv":
        candidates.sort(
            key=lambda candidate: (
                int(candidate.get("episode", 0) or 0),
                int(candidate.get("score", 0) or 0),
                get_resource_item_sort_key(candidate.get("item", {})),
            ),
            reverse=True,
        )
    else:
        candidates.sort(
            key=lambda candidate: (
                int(candidate.get("score", 0) or 0),
                get_resource_item_sort_key(candidate.get("item", {})),
            ),
            reverse=True,
        )
    scored_candidates.sort(
        key=lambda candidate: (
            int(candidate.get("score", 0) or 0),
            get_resource_item_sort_key(candidate.get("item", {})),
        ),
        reverse=True,
    )

    relaxed_score_mode = False
    if provider != "quark" and not candidates and media_type == "tv" and relaxed_candidates:
        relaxed_candidates.sort(
            key=lambda candidate: (
                int(candidate.get("episode", 0) or 0),
                int(candidate.get("score", 0) or 0),
                get_resource_item_sort_key(candidate.get("item", {})),
            ),
            reverse=True,
        )
        candidates = relaxed_candidates[: min(int(SUBSCRIPTION_115_SEARCH_CANDIDATE_LIMIT), len(relaxed_candidates))]
        relaxed_score_mode = True

    candidate_limit = (
        int(SUBSCRIPTION_QUARK_SEARCH_CANDIDATE_LIMIT)
        if provider == "quark"
        else int(SUBSCRIPTION_115_SEARCH_CANDIDATE_LIMIT)
    )
    return {
        "candidate": candidates[0] if candidates else {},
        "candidates": candidates[: min(candidate_limit, len(candidates))],
        "keywords": keywords,
        "errors": merged_errors,
        "stats": {
            "search_keywords": len(keywords),
            "searched_sources": searched_sources,
            "matched_channels": matched_channels,
            "pages_scanned": pages_scanned,
            "raw_items": len(all_items),
            "deduped_items": len(deduped_items),
            "persisted_items": len(persisted_items),
            "supported_items": supported_items,
            "unsupported_items": unsupported_items,
            "media_guard_filtered": media_guard_filtered,
            "media_guard_reasons": media_guard_reasons,
            "season_guard_filtered": season_guard_filtered,
            "target_season": target_season if single_season_tv else 0,
            "scored_items": len(scored_candidates),
            "scored_candidates": len(candidates),
            "relaxed_score_mode": relaxed_score_mode,
            "relaxed_candidates": len(relaxed_candidates),
            "search_errors": len(merged_errors),
            "best_score": int(scored_candidates[0].get("score", 0) or 0) if scored_candidates else 0,
            "provider": provider,
            "min_score": min_score,
            "title_blocked_candidates": title_blocked_candidates,
            "quark_low_score_kept": quark_low_score_kept,
            "quark_media_relaxed_pass": quark_media_relaxed_pass,
            "incremental_search_enabled": incremental_search_enabled,
            "incremental_stop_channels": incremental_stop_channels,
            "incremental_channel_watermarks_loaded": len(incremental_since_cursor_by_channel),
            "incremental_channel_watermarks_observed": len(observed_channel_watermarks),
            "incremental_channel_watermarks_error_channels": len(incremental_error_channels),
            "incremental_channel_watermarks_advanced": int(incremental_channels_advanced or 0),
            "channel_support_rows_updated": int(channel_support_rows_updated or 0),
        },
    }


def merge_subscription_search_results(
    fixed_result: Dict[str, Any],
    channel_result: Dict[str, Any],
) -> Dict[str, Any]:
    fixed_payload = fixed_result if isinstance(fixed_result, dict) else {}
    channel_payload = channel_result if isinstance(channel_result, dict) else {}

    def collect_candidates(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        candidate = payload.get("candidate")
        if isinstance(candidate, dict) and candidate:
            result.append(candidate)
        raw_candidates = payload.get("candidates")
        if isinstance(raw_candidates, list):
            for item in raw_candidates:
                if isinstance(item, dict) and item:
                    result.append(item)
        return result

    def build_candidate_key(candidate: Dict[str, Any]) -> str:
        item = candidate.get("item") if isinstance(candidate.get("item"), dict) else {}
        extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
        source_post_id = str(item.get("source_post_id", "") or extra.get("source_post_id", "")).strip()
        if source_post_id:
            return f"post:{source_post_id}"
        message_url = str(item.get("message_url", "")).strip()
        if message_url:
            return f"msg:{message_url}"
        link_url = str(item.get("link_url", "")).strip()
        if link_url:
            return f"link:{link_url}"
        title = str(item.get("title", "")).strip()
        raw_text = str(item.get("raw_text", "")).strip()
        return f"title:{title}|raw:{raw_text[:120]}"

    def merge_keywords(*payloads: Dict[str, Any]) -> List[str]:
        seen: Set[str] = set()
        merged: List[str] = []
        for payload in payloads:
            keywords = payload.get("keywords")
            if not isinstance(keywords, list):
                continue
            for token in keywords:
                text = str(token or "").strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                merged.append(text)
        return merged

    def merge_errors(*payloads: Dict[str, Any]) -> List[Dict[str, Any]]:
        merged_errors: List[Dict[str, Any]] = []
        seen: Set[str] = set()
        for payload in payloads:
            errors = payload.get("errors")
            if not isinstance(errors, list):
                continue
            for item in errors:
                if not isinstance(item, dict):
                    continue
                channel_id = str(item.get("channel_id", "")).strip()
                channel_name = str(item.get("name", "")).strip()
                message = str(item.get("message", "")).strip()
                if not message:
                    continue
                key = "|".join([channel_id, channel_name, message])
                if key in seen:
                    continue
                seen.add(key)
                merged_errors.append(
                    {
                        "channel_id": channel_id,
                        "name": channel_name,
                        "message": message,
                    }
                )
        return merged_errors

    fixed_candidates = collect_candidates(fixed_payload)
    channel_candidates = collect_candidates(channel_payload)
    merged_candidates: List[Dict[str, Any]] = []
    seen_candidate_keys: Set[str] = set()
    for candidate in fixed_candidates + channel_candidates:
        key = build_candidate_key(candidate)
        if not key or key in seen_candidate_keys:
            continue
        seen_candidate_keys.add(key)
        merged_candidates.append(candidate)

    fixed_stats = fixed_payload.get("stats") if isinstance(fixed_payload.get("stats"), dict) else {}
    channel_stats = channel_payload.get("stats") if isinstance(channel_payload.get("stats"), dict) else {}
    sum_stat_keys = (
        "search_keywords",
        "searched_sources",
        "matched_channels",
        "pages_scanned",
        "raw_items",
        "deduped_items",
        "persisted_items",
        "supported_items",
        "unsupported_items",
        "media_guard_filtered",
        "season_guard_filtered",
        "scored_items",
        "scored_candidates",
        "relaxed_candidates",
        "search_errors",
        "incremental_stop_channels",
        "incremental_channel_watermarks_loaded",
        "incremental_channel_watermarks_observed",
        "incremental_channel_watermarks_error_channels",
        "incremental_channel_watermarks_advanced",
        "channel_support_rows_updated",
    )
    merged_stats: Dict[str, Any] = {}
    for key in sum_stat_keys:
        merged_stats[key] = int(fixed_stats.get(key, 0) or 0) + int(channel_stats.get(key, 0) or 0)

    merged_reasons: Dict[str, int] = {}
    for part in [fixed_stats.get("media_guard_reasons", {}), channel_stats.get("media_guard_reasons", {})]:
        if not isinstance(part, dict):
            continue
        for reason_key, reason_count in part.items():
            reason_text = str(reason_key or "").strip()
            if not reason_text:
                continue
            merged_reasons[reason_text] = int(merged_reasons.get(reason_text, 0) or 0) + int(reason_count or 0)

    merged_stats["media_guard_reasons"] = merged_reasons
    merged_stats["target_season"] = max(
        int(fixed_stats.get("target_season", 0) or 0),
        int(channel_stats.get("target_season", 0) or 0),
    )
    merged_stats["relaxed_score_mode"] = bool(
        fixed_stats.get("relaxed_score_mode", False) or channel_stats.get("relaxed_score_mode", False)
    )
    merged_stats["incremental_search_enabled"] = bool(
        fixed_stats.get("incremental_search_enabled", False) or channel_stats.get("incremental_search_enabled", False)
    )
    merged_stats["best_score"] = max(
        int(fixed_stats.get("best_score", 0) or 0),
        int(channel_stats.get("best_score", 0) or 0),
    )
    merged_stats["fixed_candidate_count"] = len(fixed_candidates)
    merged_stats["channel_candidate_count"] = len(channel_candidates)
    merged_stats["channel_searched_sources"] = int(channel_stats.get("searched_sources", 0) or 0)
    merged_stats["channel_matched_channels"] = int(channel_stats.get("matched_channels", 0) or 0)
    merged_stats["channel_pages_scanned"] = int(channel_stats.get("pages_scanned", 0) or 0)
    merged_stats["channel_raw_items"] = int(channel_stats.get("raw_items", 0) or 0)
    merged_stats["channel_deduped_items"] = int(channel_stats.get("deduped_items", 0) or 0)
    merged_stats["channel_supported_items"] = int(channel_stats.get("supported_items", 0) or 0)
    merged_stats["channel_unsupported_items"] = int(channel_stats.get("unsupported_items", 0) or 0)

    provider = normalize_subscription_provider(
        channel_stats.get("provider", fixed_stats.get("provider", "115")),
        fallback="115",
    )
    candidate_limit = (
        int(SUBSCRIPTION_QUARK_SEARCH_CANDIDATE_LIMIT)
        if provider == "quark"
        else int(SUBSCRIPTION_115_SEARCH_CANDIDATE_LIMIT)
    )

    merged_errors = merge_errors(fixed_payload, channel_payload)
    merged_stats["search_errors"] = len(merged_errors)
    merged_stats["provider"] = provider

    return {
        "candidate": merged_candidates[0] if merged_candidates else {},
        "candidates": merged_candidates[: min(candidate_limit, len(merged_candidates))],
        "keywords": merge_keywords(fixed_payload, channel_payload),
        "errors": merged_errors,
        "stats": merged_stats,
    }


from .subscription_task_runner import (
    _run_subscription_task_quark,
    run_subscription_task,
)
