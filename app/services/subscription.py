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


def _subscription_supported_link_types(provider: str) -> Set[str]:
    if normalize_subscription_provider(provider, fallback="115") == "quark":
        return {"quark"}
    return {"115share"}


def _filter_subscription_supported_items(items: List[Dict[str, Any]], provider: str) -> List[Dict[str, Any]]:
    supported_link_types = _subscription_supported_link_types(provider)
    result: List[Dict[str, Any]] = []
    for raw_item in items:
        item = raw_item if isinstance(raw_item, dict) else {}
        link_type = resolve_resource_link_type(item.get("link_type", ""), item.get("link_url", ""))
        if link_type in supported_link_types:
            result.append(item)
    return result


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
    "share_anchor_empty": "锚点目录为空",
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

    scan_savepath = resolve_subscription_tv_scan_savepath(task, base_savepath) or base_savepath
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


def refresh_subscription_task_tmdb_binding(
    task_name: str,
    task: Optional[Dict[str, Any]] = None,
    cfg: Optional[Dict[str, Any]] = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    active_cfg = normalize_config(cfg or get_config())
    normalized_task = normalize_subscription_task(task or _load_subscription_task(active_cfg, task_name))
    if not normalized_task:
        return {
            "task": {},
            "cfg": active_cfg,
            "changed": False,
            "reason": "task_not_found",
        }

    if str(normalized_task.get("media_type", "movie") or "movie").strip().lower() != "tv":
        return {
            "task": normalized_task,
            "cfg": active_cfg,
            "changed": False,
            "reason": "non_tv_task",
        }

    tmdb_id = max(0, int(normalized_task.get("tmdb_id", 0) or 0))
    if tmdb_id <= 0:
        return {
            "task": normalized_task,
            "cfg": active_cfg,
            "changed": False,
            "reason": "no_tmdb_binding",
        }

    tmdb_media_type = normalize_tmdb_media_type(
        normalized_task.get("tmdb_media_type", ""),
        fallback=normalized_task.get("media_type", "tv"),
    )
    detail = get_tmdb_media_detail(
        tmdb_id,
        tmdb_media_type,
        active_cfg,
        force_refresh=force_refresh,
    )
    task_binding = build_tmdb_task_binding(detail, media_type=tmdb_media_type)
    previous_expected_total = resolve_subscription_tmdb_expected_total(normalized_task)

    merged_task = normalize_subscription_task(
        {
            **normalized_task,
            **task_binding,
        }
    )
    current_expected_total = resolve_subscription_tmdb_expected_total(merged_task)
    current_total = max(0, int(normalized_task.get("total_episodes", 0) or 0))
    total_synced = False
    total_override_preserved = False
    if current_total > 0 and current_expected_total > 0:
        previous_expected_candidates = {
            previous_expected_total,
            max(0, int(normalized_task.get("tmdb_total_episodes", 0) or 0)),
            get_subscription_tmdb_season_total_episodes(normalized_task),
        }
        previous_expected_candidates.discard(0)
        if current_total in previous_expected_candidates:
            if current_total != current_expected_total:
                merged_task["total_episodes"] = current_expected_total
                total_synced = True
        else:
            total_override_preserved = True
    merged_task = normalize_subscription_task(merged_task)

    changed = merged_task != normalized_task
    updated_cfg = active_cfg
    if changed:
        tasks = active_cfg.get("subscription_tasks", []) if isinstance(active_cfg.get("subscription_tasks"), list) else []
        updated_tasks: List[Dict[str, Any]] = []
        updated_row = False
        for raw_task in tasks:
            current_task = normalize_subscription_task(raw_task or {})
            if current_task.get("name") == normalized_task.get("name"):
                updated_tasks.append(dict(merged_task))
                updated_row = True
            else:
                updated_tasks.append(current_task)
        if updated_row:
            updated_cfg = dict(active_cfg)
            updated_cfg["subscription_tasks"] = updated_tasks
            save_config(updated_cfg)
            updated_cfg = get_config()
            merged_task = _load_subscription_task(updated_cfg, normalized_task.get("name", ""))

    return {
        "task": merged_task,
        "cfg": updated_cfg,
        "changed": changed,
        "reason": "ok",
        "detail": detail,
        "task_binding": task_binding,
        "previous_expected_total": previous_expected_total,
        "current_expected_total": current_expected_total,
        "total_synced": total_synced,
        "total_override_preserved": total_override_preserved,
    }


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


def _resolve_subscription_search_episode_total(task: Dict[str, Any], total_episodes: int = 0) -> int:
    payload = task if isinstance(task, dict) else {}
    if str(payload.get("media_type", "movie") or "movie").strip().lower() != "tv":
        return 0
    explicit_total = max(0, int(total_episodes or 0))
    if explicit_total > 0:
        return explicit_total
    return max(0, int(resolve_subscription_tv_total_episodes(payload, state_total=0) or 0))


def _build_subscription_search_limits(task: Dict[str, Any], total_episodes: int = 0) -> Dict[str, int]:
    episode_total = _resolve_subscription_search_episode_total(task, total_episodes=total_episodes)
    page_size = max(1, int(TG_SEARCH_PAGE_LIMIT or 20))
    configured_max_pages = max(1, int(SUBSCRIPTION_SEARCH_CHANNEL_MAX_PAGES or TG_SEARCH_MAX_PAGES or 3))
    if episode_total > 0:
        channel_limit = max(1, episode_total * 5)
        pansou_limit = max(1, episode_total * 10)
        max_pages = min(configured_max_pages, max(1, (channel_limit + page_size - 1) // page_size))
        return {
            "episode_total": episode_total,
            "channel_limit_per_keyword": channel_limit,
            "channel_max_pages": max_pages,
            "channel_page_size": page_size,
            "channel_total_limit": 0,
            "pansou_limit_per_keyword": pansou_limit,
        }
    return {
        "episode_total": 0,
        "channel_limit_per_keyword": max(1, int(TG_SEARCH_MATCH_LIMIT_PER_CHANNEL or 12)),
        "channel_max_pages": min(configured_max_pages, max(1, int(TG_SEARCH_MAX_PAGES or 3))),
        "channel_page_size": page_size,
        "channel_total_limit": 0,
        "pansou_limit_per_keyword": max(1, int(PANSOU_SEARCH_TOTAL_LIMIT or 80)),
    }


def _classify_subscription_search_source(item: Dict[str, Any]) -> str:
    payload = item if isinstance(item, dict) else {}
    source_type = str(payload.get("source_type", "") or "").strip().lower()
    if source_type == "pansou":
        return "pansou"
    if source_type == "tg":
        return "channel"
    return "other"


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


def _load_subscription_cached_search_items(
    task: Dict[str, Any],
    keywords: List[str],
    identity_mode: str,
    limit_per_query: int = 0,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    provider = normalize_subscription_provider(task.get("provider", "115"), fallback="115")
    if provider not in {"115", "quark"}:
        return [], {"cached_items": 0, "cache_queries": 0, "cache_errors": 0}

    cfg = get_config()
    sources = [normalize_resource_source(source or {}) for source in cfg.get("resource_sources", []) if source.get("enabled")]
    enabled_channel_ids = list_enabled_resource_channel_ids(sources)
    search_terms: List[str] = []
    search_terms.extend([str(keyword or "").strip() for keyword in keywords if str(keyword or "").strip()])
    for value in [
        task.get("title", ""),
        task.get("tmdb_title", ""),
        task.get("tmdb_original_title", ""),
    ]:
        text = re.sub(r"\s+", " ", str(value or "").strip())
        if text:
            search_terms.append(text)
    for field in ("tmdb_aliases", "aliases"):
        raw_values = task.get(field, [])
        if not isinstance(raw_values, list):
            continue
        for value in raw_values[:8]:
            text = re.sub(r"\s+", " ", str(value or "").strip())
            if text:
                search_terms.append(text)
    search_terms = unique_preserve_order(search_terms)

    normalized_identity_mode = normalize_resource_identity_mode(identity_mode, fallback="message")
    per_keyword_limit = max(0, int(limit_per_query or 0))
    cached_items: List[Dict[str, Any]] = []
    seen_keys: Set[str] = set()
    cache_errors = 0

    for term in search_terms:
        try:
            rows = list_resource_items(search=term, limit=per_keyword_limit)
        except Exception:
            cache_errors += 1
            continue
        for row in rows:
            item = row if isinstance(row, dict) else {}
            if not item:
                continue
            source_type = str(item.get("source_type", "") or "").strip().lower()
            if source_type == "tg":
                channel_id = normalize_telegram_channel_id_from_input(
                    item.get("channel_name", "") or item.get("source_name", "")
                )
                if not channel_id or channel_id not in enabled_channel_ids:
                    continue
            if not resource_item_matches_search(item, term):
                continue
            item_id = max(0, int(item.get("id", 0) or 0))
            identity = build_resource_item_identity_by_mode(item, identity_mode=normalized_identity_mode)
            cache_key = f"id:{item_id}" if item_id > 0 else identity
            if not cache_key or cache_key in seen_keys:
                continue
            seen_keys.add(cache_key)
            cached_items.append(item)

    return cached_items, {
        "cached_items": len(cached_items),
        "cache_queries": len(search_terms),
        "cache_errors": cache_errors,
        "cache_limit_per_query": per_keyword_limit,
    }




async def find_subscription_task_match_candidate_by_search(
    task: Dict[str, Any],
    last_episode: int = 0,
    trigger: str = "",
    total_episodes: int = 0,
) -> Dict[str, Any]:
    provider = normalize_subscription_provider(task.get("provider", "115"), fallback="115")
    title_first_search_enabled = provider in {"115", "quark"}
    search_identity_mode = "link" if title_first_search_enabled else "message"
    trigger_mode = str(trigger or "").strip().lower()
    incremental_search_enabled = trigger_mode == "cron"
    task_name = str(task.get("name", "") or task.get("title", "") or "").strip()
    baseline_channel_watermarks = (
        load_subscription_channel_search_watermarks(task_name)
        if (incremental_search_enabled and task_name)
        else {}
    )
    incremental_watermark_overlap_posts = (
        max(0, int(SUBSCRIPTION_CHANNEL_WATERMARK_OVERLAP_POSTS or 0))
        if incremental_search_enabled
        else 0
    )
    incremental_since_cursor_by_channel: Dict[str, int] = {}
    if isinstance(baseline_channel_watermarks, dict):
        for raw_channel_id, payload in baseline_channel_watermarks.items():
            channel_id = normalize_telegram_channel_id_from_input(raw_channel_id)
            if not channel_id or not isinstance(payload, dict):
                continue
            last_cursor = max(0, int(payload.get("last_post_cursor", 0) or 0))
            if last_cursor <= 0:
                continue
            # 定时任务用软水位提速，但保留一小段回看窗口，避免频道乱序/补发/解析抖动造成漏候选。
            incremental_since_cursor_by_channel[channel_id] = max(
                0,
                last_cursor - incremental_watermark_overlap_posts,
            )
    observed_channel_watermarks: Dict[str, Dict[str, Any]] = {}
    incremental_error_channels: Set[str] = set()
    incremental_stop_channels = 0
    channel_support_stats_deltas: Dict[str, Dict[str, Any]] = {}
    query_tokens = build_subscription_query_tokens(task)
    if not query_tokens:
        return {"candidate": {}, "keywords": [], "stats": {}, "errors": []}

    keywords = _build_subscription_search_keywords(task, limit=SUBSCRIPTION_SEARCH_KEYWORD_LIMIT)
    search_limits = _build_subscription_search_limits(task, total_episodes=total_episodes)
    all_items: List[Dict[str, Any]] = []
    all_errors: List[Dict[str, Any]] = []
    searched_sources = 0
    matched_channels = 0
    pages_scanned = 0
    search_thread_limit = 0
    channel_returned_items = 0
    pansou_items = 0
    pansou_errors = 0
    pansou_elapsed_seconds = 0.0
    slow_channel_rows: List[Dict[str, Any]] = []
    keyword_search_started_at = time.perf_counter()
    keyword_semaphore = asyncio.Semaphore(SUBSCRIPTION_SEARCH_KEYWORD_CONCURRENCY)

    async def search_one_keyword(keyword: str) -> Tuple[str, Dict[str, Any]]:
        check_subscription_cancelled()
        async with keyword_semaphore:
            check_subscription_cancelled()
            search_started_at = time.perf_counter()
            search_meta = await search_resource_sources(
                keyword,
                identity_mode=search_identity_mode,
                incremental_since_cursor_by_channel=(
                    incremental_since_cursor_by_channel if incremental_search_enabled else None
                ),
                provider_filter=provider,
                limit_per_channel=int(search_limits.get("channel_limit_per_keyword", 0) or 0),
                max_pages=int(search_limits.get("channel_max_pages", 0) or 0),
                page_size=int(search_limits.get("channel_page_size", 0) or 0),
                total_limit=int(search_limits.get("channel_total_limit", 0) or 0),
            )
            if isinstance(search_meta, dict):
                search_meta["keyword"] = keyword
                search_meta["elapsed_seconds"] = max(0.0, time.perf_counter() - search_started_at)
            return keyword, search_meta

    keyword_results = await asyncio.gather(
        *(search_one_keyword(keyword) for keyword in keywords),
        return_exceptions=True,
    )

    for keyword, raw_search_meta in zip(keywords, keyword_results):
        check_subscription_cancelled()
        if isinstance(raw_search_meta, Exception):
            all_errors.append({"channel_id": "", "name": keyword, "message": str(raw_search_meta)})
            continue
        _, search_meta = raw_search_meta
        search_items = search_meta.get("items", []) if isinstance(search_meta.get("items"), list) else []
        channel_returned_items += len(search_items)
        all_items.extend(search_items)
        all_errors.extend(search_meta.get("errors", []) if isinstance(search_meta.get("errors"), list) else [])
        searched_sources += max(0, int(search_meta.get("searched_sources", 0) or 0))
        matched_channels += max(0, int(search_meta.get("matched_channels", 0) or 0))
        pages_scanned += max(0, int(search_meta.get("pages_scanned", 0) or 0))
        search_thread_limit = max(search_thread_limit, max(0, int(search_meta.get("thread_limit", 0) or 0)))
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
            elapsed_seconds = max(0.0, float(raw_row.get("elapsed_seconds", 0.0) or 0.0))
            if elapsed_seconds > 0:
                slow_channel_rows.append(
                    {
                        "channel_id": channel_id,
                        "name": str(raw_row.get("name", "") or channel_id).strip() or channel_id,
                        "keyword": keyword,
                        "elapsed_seconds": elapsed_seconds,
                        "matched": matched,
                        "pages_scanned": max(0, int(raw_row.get("pages_scanned", 0) or 0)),
                        "error": str(raw_row.get("error", "") or "").strip(),
                    }
                )
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

    cfg = get_config()
    if bool(cfg.get("pansou_enabled", False)):
        pansou_started_at = time.perf_counter()

        async def search_one_pansou_keyword(keyword: str) -> Tuple[str, Dict[str, Any]]:
            check_subscription_cancelled()
            async with keyword_semaphore:
                check_subscription_cancelled()
                search_meta = await search_pansou_resource_sources(
                    keyword,
                    provider_filter=provider,
                    include_magnet_for_115=False,
                    total_limit=int(search_limits.get("pansou_limit_per_keyword", 0) or 0),
                )
                if isinstance(search_meta, dict):
                    search_meta["keyword"] = keyword
                return keyword, search_meta

        pansou_results = await asyncio.gather(
            *(search_one_pansou_keyword(keyword) for keyword in keywords),
            return_exceptions=True,
        )
        pansou_elapsed_seconds = max(0.0, time.perf_counter() - pansou_started_at)
        for keyword, raw_pansou_meta in zip(keywords, pansou_results):
            check_subscription_cancelled()
            if isinstance(raw_pansou_meta, Exception):
                pansou_errors += 1
                all_errors.append({"channel_id": "pansou", "name": keyword, "message": str(raw_pansou_meta)})
                continue
            _, pansou_meta = raw_pansou_meta
            meta_items = pansou_meta.get("items", []) if isinstance(pansou_meta.get("items"), list) else []
            pansou_items += len(meta_items)
            all_items.extend(meta_items)
            pansou_meta_errors = pansou_meta.get("errors", []) if isinstance(pansou_meta.get("errors"), list) else []
            pansou_errors += len(pansou_meta_errors)
            all_errors.extend(pansou_meta_errors)
            searched_sources += max(0, int(pansou_meta.get("searched_sources", 0) or 0))
            matched_channels += max(0, int(pansou_meta.get("matched_channels", 0) or 0))
            pages_scanned += max(0, int(pansou_meta.get("pages_scanned", 0) or 0))
            search_thread_limit = max(search_thread_limit, max(0, int(pansou_meta.get("thread_limit", 0) or 0)))
    keyword_search_elapsed_seconds = max(0.0, time.perf_counter() - keyword_search_started_at)

    live_raw_items = len(all_items)
    cached_items, cache_stats = _load_subscription_cached_search_items(
        task,
        keywords,
        search_identity_mode,
    )
    if cached_items:
        all_items.extend(cached_items)

    deduped_items = dedupe_resource_item_dicts(all_items, identity_mode=search_identity_mode)
    deduped_items.sort(key=get_resource_item_sort_key, reverse=True)
    if provider == "quark":
        expanded_quark_items: List[Dict[str, Any]] = []
        for raw_item in deduped_items:
            expanded_quark_items.extend(_expand_subscription_quark_item_variants(raw_item))
        deduped_items = dedupe_resource_item_dicts(expanded_quark_items, identity_mode="link")
        deduped_items.sort(key=get_resource_item_sort_key, reverse=True)
    elif provider == "115":
        expanded_115_items: List[Dict[str, Any]] = []
        for raw_item in deduped_items:
            expanded_115_items.extend(_expand_subscription_115_item_variants(raw_item))
        deduped_items = dedupe_resource_item_dicts(expanded_115_items, identity_mode="link")
        deduped_items.sort(key=get_resource_item_sort_key, reverse=True)
    deduped_items = _filter_subscription_supported_items(deduped_items, provider)
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
    slow_channel_rows.sort(key=lambda row: float(row.get("elapsed_seconds", 0.0) or 0.0), reverse=True)
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
    exclude_keyword_filtered = 0
    exclude_keyword_hits: Dict[str, int] = {}
    supported_link_types = _subscription_supported_link_types(provider)
    media_type = str(task.get("media_type", "movie") or "movie").strip().lower()
    single_season_tv = media_type == "tv" and (not is_subscription_multi_season_mode(task))
    target_season = max(1, int(task.get("season", 1) or 1))
    title_blocked_candidates = 0
    title_match_low_score_kept = 0
    title_match_media_relaxed_pass = 0
    season_guard_deferred = 0
    seen_quark_scored_keys: Set[str] = set()
    for item in persisted_items:
        link_url = str(item.get("link_url", "") or "").strip()
        link_type = resolve_resource_link_type(item.get("link_type", ""), link_url)
        if link_type not in supported_link_types:
            unsupported_items += 1
            continue
        blocked_keyword = match_subscription_exclude_keyword(task, item)
        if blocked_keyword:
            exclude_keyword_filtered += 1
            exclude_keyword_hits[blocked_keyword] = int(exclude_keyword_hits.get(blocked_keyword, 0) or 0) + 1
            continue
        media_match, media_reason = match_subscription_media_type(task, item)
        if not media_match:
            if (
                title_first_search_enabled
                and media_type == "tv"
                and str(media_reason or "").strip() == "missing_episode_meta"
            ):
                # 115/夸克频道标题经常只保留剧名，不带标准季集字段；此类候选交给后续标题/精细扫描再判定。
                title_match_media_relaxed_pass += 1
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
            if title_first_search_enabled
            else score_subscription_candidate(task, item, query_tokens, last_episode)
        )
        if title_first_search_enabled and not bool(scored.get("title_match", False)):
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
                if title_first_search_enabled:
                    # 标题优先召回阶段只确认剧名命中；显式季号差异交给执行阶段的文件级精选再判定。
                    season_guard_deferred += 1
                    scored["season_mismatch_deferred"] = True
                    scored["target_season"] = target_season
                else:
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
        if (
            (not keep_candidate)
            and title_first_search_enabled
            and media_type == "tv"
            and bool(scored.get("title_match", False))
        ):
            # 115/夸克电视剧场景优先保证召回：标题命中即可入队，低分放在队尾处理。
            keep_candidate = True
            title_match_low_score_kept += 1
            scored["low_score_fallback"] = True
        if not keep_candidate:
            if (not title_first_search_enabled) and media_type == "tv":
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
    if (not title_first_search_enabled) and not candidates and media_type == "tv" and relaxed_candidates:
        relaxed_candidates.sort(
            key=lambda candidate: (
                int(candidate.get("episode", 0) or 0),
                int(candidate.get("score", 0) or 0),
                get_resource_item_sort_key(candidate.get("item", {})),
            ),
            reverse=True,
        )
        candidates = relaxed_candidates
        relaxed_score_mode = True

    candidate_source_counts = {
        "channel": 0,
        "pansou": 0,
        "other": 0,
    }
    scored_source_counts = {
        "channel": 0,
        "pansou": 0,
        "other": 0,
    }
    for candidate in candidates:
        item = candidate.get("item", {}) if isinstance(candidate.get("item"), dict) else {}
        source_key = _classify_subscription_search_source(item)
        candidate_source_counts[source_key] = int(candidate_source_counts.get(source_key, 0) or 0) + 1
    for candidate in scored_candidates:
        item = candidate.get("item", {}) if isinstance(candidate.get("item"), dict) else {}
        source_key = _classify_subscription_search_source(item)
        scored_source_counts[source_key] = int(scored_source_counts.get(source_key, 0) or 0) + 1

    return {
        "candidate": candidates[0] if candidates else {},
        "candidates": candidates,
        "keywords": keywords,
        "errors": merged_errors,
        "stats": {
            "search_keywords": len(keywords),
            "search_keyword_limit": int(SUBSCRIPTION_SEARCH_KEYWORD_LIMIT),
            "search_keyword_concurrency": int(SUBSCRIPTION_SEARCH_KEYWORD_CONCURRENCY),
            "search_keyword_elapsed_seconds": keyword_search_elapsed_seconds,
            "search_episode_total": int(search_limits.get("episode_total", 0) or 0),
            "search_limit_per_channel": int(search_limits.get("channel_limit_per_keyword", 0) or 0),
            "search_total_limit": int(search_limits.get("channel_total_limit", 0) or 0),
            "search_max_pages": int(search_limits.get("channel_max_pages", 0) or 0),
            "search_page_limit": int(search_limits.get("channel_page_size", 0) or 0),
            "search_channel_timeout_seconds": int(TG_SEARCH_CHANNEL_TIMEOUT_SECONDS),
            "search_request_timeout_seconds": int(TG_SEARCH_REQUEST_TIMEOUT_SECONDS),
            "search_thread_limit": search_thread_limit,
            "searched_sources": searched_sources,
            "matched_channels": matched_channels,
            "pages_scanned": pages_scanned,
            "channel_returned_items": channel_returned_items,
            "raw_items": len(all_items),
            "live_raw_items": live_raw_items,
            "cached_items": int(cache_stats.get("cached_items", 0) or 0),
            "cache_queries": int(cache_stats.get("cache_queries", 0) or 0),
            "cache_errors": int(cache_stats.get("cache_errors", 0) or 0),
            "deduped_items": len(deduped_items),
            "persisted_items": len(persisted_items),
            "supported_items": supported_items,
            "unsupported_items": unsupported_items,
            "exclude_keyword_filtered": exclude_keyword_filtered,
            "exclude_keyword_hits": exclude_keyword_hits,
            "exclude_keywords": normalize_subscription_exclude_keywords(task.get("exclude_keywords", [])),
            "media_guard_filtered": media_guard_filtered,
            "media_guard_reasons": media_guard_reasons,
            "season_guard_filtered": season_guard_filtered,
            "season_guard_deferred": season_guard_deferred,
            "target_season": target_season if single_season_tv else 0,
            "scored_items": len(scored_candidates),
            "scored_candidates": len(candidates),
            "channel_scored_items": int(scored_source_counts.get("channel", 0) or 0),
            "pansou_scored_items": int(scored_source_counts.get("pansou", 0) or 0),
            "other_scored_items": int(scored_source_counts.get("other", 0) or 0),
            "channel_candidate_count": int(candidate_source_counts.get("channel", 0) or 0),
            "pansou_candidate_count": int(candidate_source_counts.get("pansou", 0) or 0),
            "other_candidate_count": int(candidate_source_counts.get("other", 0) or 0),
            "relaxed_score_mode": relaxed_score_mode,
            "relaxed_candidates": len(relaxed_candidates),
            "search_errors": len(merged_errors),
            "best_score": int(scored_candidates[0].get("score", 0) or 0) if scored_candidates else 0,
            "provider": provider,
            "min_score": min_score,
            "title_blocked_candidates": title_blocked_candidates,
            "title_match_low_score_kept": title_match_low_score_kept,
            "title_match_media_relaxed_pass": title_match_media_relaxed_pass,
            "quark_low_score_kept": title_match_low_score_kept if provider == "quark" else 0,
            "quark_media_relaxed_pass": title_match_media_relaxed_pass if provider == "quark" else 0,
            "incremental_search_enabled": incremental_search_enabled,
            "incremental_watermark_overlap_posts": incremental_watermark_overlap_posts,
            "incremental_stop_channels": incremental_stop_channels,
            "incremental_channel_watermarks_loaded": len(incremental_since_cursor_by_channel),
            "incremental_channel_watermarks_observed": len(observed_channel_watermarks),
            "incremental_channel_watermarks_error_channels": len(incremental_error_channels),
            "incremental_channel_watermarks_advanced": int(incremental_channels_advanced or 0),
            "channel_support_rows_updated": int(channel_support_rows_updated or 0),
            "slow_channels": slow_channel_rows[:5],
            "pansou_enabled": bool(cfg.get("pansou_enabled", False)),
            "pansou_total_limit": int(search_limits.get("pansou_limit_per_keyword", 0) or 0),
            "pansou_returned_items": pansou_items,
            "pansou_items": pansou_items,
            "pansou_errors": pansou_errors,
            "pansou_elapsed_seconds": pansou_elapsed_seconds,
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
        "live_raw_items",
        "channel_returned_items",
        "cached_items",
        "cache_queries",
        "cache_errors",
        "deduped_items",
        "persisted_items",
        "supported_items",
        "unsupported_items",
        "exclude_keyword_filtered",
        "media_guard_filtered",
        "season_guard_filtered",
        "season_guard_deferred",
        "scored_items",
        "scored_candidates",
        "channel_scored_items",
        "pansou_scored_items",
        "other_scored_items",
        "channel_candidate_count",
        "pansou_candidate_count",
        "other_candidate_count",
        "relaxed_candidates",
        "search_errors",
        "title_blocked_candidates",
        "title_match_low_score_kept",
        "title_match_media_relaxed_pass",
        "quark_low_score_kept",
        "quark_media_relaxed_pass",
        "search_episode_total",
        "incremental_stop_channels",
        "incremental_channel_watermarks_loaded",
        "incremental_channel_watermarks_observed",
        "incremental_channel_watermarks_error_channels",
        "incremental_channel_watermarks_advanced",
        "channel_support_rows_updated",
        "pansou_returned_items",
        "pansou_items",
        "pansou_errors",
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
    merged_exclude_hits: Dict[str, int] = {}
    for part in [fixed_stats.get("exclude_keyword_hits", {}), channel_stats.get("exclude_keyword_hits", {})]:
        if not isinstance(part, dict):
            continue
        for keyword, count in part.items():
            keyword_text = str(keyword or "").strip()
            if not keyword_text:
                continue
            merged_exclude_hits[keyword_text] = int(merged_exclude_hits.get(keyword_text, 0) or 0) + int(count or 0)
    merged_stats["exclude_keyword_hits"] = merged_exclude_hits
    merged_stats["exclude_keywords"] = unique_preserve_order(
        [
            str(keyword or "").strip()
            for keyword in (
                (fixed_stats.get("exclude_keywords", []) if isinstance(fixed_stats.get("exclude_keywords", []), list) else [])
                + (channel_stats.get("exclude_keywords", []) if isinstance(channel_stats.get("exclude_keywords", []), list) else [])
            )
            if str(keyword or "").strip()
        ]
    )
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
    merged_stats["pansou_enabled"] = bool(
        fixed_stats.get("pansou_enabled", False) or channel_stats.get("pansou_enabled", False)
    )
    merged_stats["pansou_elapsed_seconds"] = max(
        float(fixed_stats.get("pansou_elapsed_seconds", 0.0) or 0.0),
        float(channel_stats.get("pansou_elapsed_seconds", 0.0) or 0.0),
    )
    merged_stats["pansou_total_limit"] = max(
        int(fixed_stats.get("pansou_total_limit", 0) or 0),
        int(channel_stats.get("pansou_total_limit", 0) or 0),
    )
    merged_stats["incremental_watermark_overlap_posts"] = max(
        int(fixed_stats.get("incremental_watermark_overlap_posts", 0) or 0),
        int(channel_stats.get("incremental_watermark_overlap_posts", 0) or 0),
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
    merged_stats["channel_live_raw_items"] = int(channel_stats.get("live_raw_items", 0) or 0)
    merged_stats["channel_returned_items"] = int(channel_stats.get("channel_returned_items", 0) or 0)
    merged_stats["channel_cached_items"] = int(channel_stats.get("cached_items", 0) or 0)
    merged_stats["channel_cache_queries"] = int(channel_stats.get("cache_queries", 0) or 0)
    merged_stats["channel_cache_errors"] = int(channel_stats.get("cache_errors", 0) or 0)
    merged_stats["channel_deduped_items"] = int(channel_stats.get("deduped_items", 0) or 0)
    merged_stats["channel_supported_items"] = int(channel_stats.get("supported_items", 0) or 0)
    merged_stats["channel_unsupported_items"] = int(channel_stats.get("unsupported_items", 0) or 0)
    for key in (
        "search_keyword_limit",
        "search_limit_per_channel",
        "search_total_limit",
        "search_max_pages",
        "search_page_limit",
        "search_channel_timeout_seconds",
        "search_request_timeout_seconds",
        "search_keyword_concurrency",
        "search_keyword_elapsed_seconds",
        "search_thread_limit",
    ):
        if key == "search_keyword_elapsed_seconds":
            merged_stats[key] = max(
                float(channel_stats.get(key, 0.0) or 0.0),
                float(fixed_stats.get(key, 0.0) or 0.0),
            )
        else:
            merged_stats[key] = int(channel_stats.get(key, fixed_stats.get(key, 0)) or 0)
    merged_slow_channels: List[Dict[str, Any]] = []
    for part in [fixed_stats.get("slow_channels", []), channel_stats.get("slow_channels", [])]:
        if isinstance(part, list):
            merged_slow_channels.extend([row for row in part if isinstance(row, dict)])
    merged_slow_channels.sort(key=lambda row: float(row.get("elapsed_seconds", 0.0) or 0.0), reverse=True)
    merged_stats["slow_channels"] = merged_slow_channels[:5]

    provider = normalize_subscription_provider(
        channel_stats.get("provider", fixed_stats.get("provider", "115")),
        fallback="115",
    )
    merged_errors = merge_errors(fixed_payload, channel_payload)
    merged_stats["search_errors"] = len(merged_errors)
    merged_stats["provider"] = provider

    return {
        "candidate": merged_candidates[0] if merged_candidates else {},
        "candidates": merged_candidates,
        "keywords": merge_keywords(fixed_payload, channel_payload),
        "errors": merged_errors,
        "stats": merged_stats,
    }


from .subscription_task_runner import (
    _run_subscription_task_quark,
    run_subscription_task,
)
