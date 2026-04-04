from ..core import *  # noqa: F401,F403
from .monitor import queue_monitor_job

async def trigger_resource_job_refresh(job_id: int, reason: str = "manual") -> Dict[str, Any]:
    job = get_resource_job(job_id, include_private=True)
    if not job:
        raise RuntimeError("资源任务不存在")
    if not job.get("monitor_task_name"):
        raise RuntimeError("未绑定文件夹监控任务")
    if str(job.get("last_triggered_at", "")).strip():
        return {"ok": True, "status": "already"}
    cfg = get_config()
    if not any(task.get("name") == job.get("monitor_task_name") for task in cfg.get("monitor_tasks", [])):
        raise RuntimeError("绑定的文件夹监控任务已不存在")

    payload = {
        "savepath": job.get("savepath", ""),
        "sharetitle": job.get("sharetitle", ""),
        "title": job.get("title", ""),
    }
    refresh_target_type = str(job.get("refresh_target_type", "") or "").strip()
    if refresh_target_type:
        payload["refresh_target_type"] = refresh_target_type
    status = queue_monitor_job(str(job["monitor_task_name"]).strip(), "resource", payload)
    update_resource_job(
        job_id,
        status="completed",
        status_detail=f"已触发监控任务：{job['monitor_task_name']} ({status}) [{reason}]",
        last_triggered_at=now_text(),
        finished_at=now_text(),
    )
    resource_id = int(job.get("resource_id", 0) or 0)
    if resource_id > 0:
        conn = open_db()
        update_resource_item_status(conn, resource_id, "completed")
        conn.commit()
        conn.close()
    return {"ok": True, "status": status}


async def schedule_resource_job_refresh(job_id: int) -> None:
    if job_id in resource_refresh_pending:
        return
    resource_refresh_pending.add(job_id)
    try:
        job = get_resource_job(job_id, include_private=True)
        if not job or not job.get("auto_refresh"):
            return
        delay_seconds = max(0, int(job.get("refresh_delay_seconds", 0) or 0))
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)
        fresh_job = get_resource_job(job_id, include_private=True)
        if not fresh_job or str(fresh_job.get("last_triggered_at", "")).strip():
            return
        try:
            await trigger_resource_job_refresh(job_id, reason="auto")
        except Exception as exc:
            update_resource_job(job_id, status="failed", status_detail=str(exc), finished_at=now_text())
    finally:
        resource_refresh_pending.discard(job_id)


async def run_resource_job(job_id: int) -> None:
    if job_id in resource_job_running:
        return
    resource_job_running.add(job_id)
    try:
        job = get_resource_job(job_id, include_private=True)
        if not job:
            return
        resource_id = int(job.get("resource_id", 0) or 0)
        resource = get_resource_item(resource_id) if resource_id > 0 else {}
        job_snapshot = job.get("_snapshot", {}) if isinstance(job.get("_snapshot"), dict) else {}

        cfg = get_config()
        if not str(cfg.get("cookie_115", "")).strip():
            raise RuntimeError("请先在参数配置中填写 115 Cookie")
        link_type = resolve_resource_link_type(job.get("link_type", ""), job.get("link_url", ""))
        if link_type not in ("magnet", "115share"):
            raise RuntimeError("当前仅支持 magnet 下载和 115 分享链接转存")

        update_resource_job(job_id, status="running", status_detail="正在提交到 115", started_at=now_text())
        if resource_id > 0:
            conn = open_db()
            update_resource_item_status(conn, resource_id, "importing")
            conn.commit()
            conn.close()

        if link_type == "magnet":
            response = await asyncio.to_thread(
                submit_115_offline_task,
                str(cfg.get("cookie_115", "")).strip(),
                str(job.get("link_url", "")).strip(),
                str(job.get("folder_id", "")).strip(),
            )
            detail = str(response.get("error_msg", "")).strip() or "115 已接收离线任务"
            if int(response.get("errcode", 0) or 0) == 10008:
                detail = "115 提示任务已存在，已继续走刷新流程"
        else:
            job_extra = safe_json_loads(job.get("extra_json"), {})
            job_selection = normalize_share_selection_meta(job_extra)
            share_url = apply_share_receive_code_to_url(
                str(job.get("link_url", "")).strip(),
                str(job_snapshot.get("receive_code", "") or "").strip(),
            )
            response_bundle = await asyncio.to_thread(
                submit_115_share_receive,
                str(cfg.get("cookie_115", "")).strip(),
                share_url,
                str(job.get("folder_id", "")).strip(),
                "",
                job_selection.get("selected_ids", []),
                str(job_snapshot.get("receive_code", "") or "").strip(),
            )
            response = response_bundle.get("response", {}) if isinstance(response_bundle, dict) else {}
            resolved_selection = merge_share_selection_meta(job_selection, response_bundle.get("selection", {}))
            detail = str(response.get("error", "")).strip() or str(response.get("msg", "")).strip() or "115 已接收转存任务"

            resource_title_rel = normalize_relative_path(job.get("title", "") or resource.get("title", ""))
            current_sharetitle = normalize_relative_path(job.get("sharetitle", ""))
            auto_sharetitle = normalize_relative_path(resolved_selection.get("auto_sharetitle", ""))
            if auto_sharetitle and (not current_sharetitle or current_sharetitle == resource_title_rel):
                job["sharetitle"] = auto_sharetitle
            if resolved_selection:
                merged_extra = merge_json_object(job_extra, resolved_selection)
                if job_snapshot:
                    merged_extra["snapshot"] = job_snapshot
                job["extra_json"] = safe_json_dumps(merged_extra)

        monitor_task_name = str(job.get("monitor_task_name", "") or "").strip()
        auto_refresh_enabled = bool(job.get("auto_refresh"))
        if monitor_task_name:
            delay_seconds = max(0, int(job.get("refresh_delay_seconds", 0) or 0))
            if auto_refresh_enabled:
                refresh_text = f"等待 {delay_seconds} 秒后自动触发文件夹监控" if delay_seconds > 0 else "提交后自动触发文件夹监控"
            else:
                refresh_text = "已命中文件夹监控任务，等待手动触发生成 strm"
            detail = f"{detail}；{refresh_text}（{monitor_task_name}）"
        else:
            detail = f"{detail}；当前保存路径未纳入文件夹监控，不会自动生成 strm"

        update_fields = {
            "status": "submitted",
            "status_detail": detail,
            "response_json": safe_json_dumps(response),
        }
        if link_type == "115share":
            update_fields["extra_json"] = job.get("extra_json", safe_json_dumps({}))
            if str(job.get("sharetitle", "")).strip():
                update_fields["sharetitle"] = str(job.get("sharetitle", "")).strip()
        update_resource_job(job_id, **update_fields)
        if resource_id > 0:
            conn = open_db()
            update_resource_item_status(conn, resource_id, "submitted")
            conn.commit()
            conn.close()

        if bool(job.get("auto_refresh")) and str(job.get("monitor_task_name", "")).strip():
            asyncio.create_task(schedule_resource_job_refresh(job_id))
    except Exception as exc:
        update_resource_job(job_id, status="failed", status_detail=str(exc), finished_at=now_text())
        failed_job = get_resource_job(job_id, include_private=True)
        if failed_job:
            failed_resource_id = int(failed_job.get("resource_id", 0) or 0)
            if failed_resource_id > 0:
                conn = open_db()
                update_resource_item_status(conn, failed_resource_id, "failed")
                conn.commit()
                conn.close()
    finally:
        resource_job_running.discard(job_id)
