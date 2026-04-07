from ..core import *  # noqa: F401,F403
from .monitor import queue_monitor_job


class ResourceJobCancelledError(RuntimeError):
    pass


def _mark_resource_job_failed(job_id: int, resource_id: int, detail: str) -> None:
    fail_detail = str(detail or "资源导入失败").strip() or "资源导入失败"
    update_resource_job(job_id, status="failed", status_detail=fail_detail, finished_at=now_text())
    if resource_id > 0:
        conn = open_db()
        update_resource_item_status(conn, resource_id, "failed")
        conn.commit()
        conn.close()


def _build_retry_resource_from_job(job: Dict[str, Any]) -> Dict[str, Any]:
    payload = job if isinstance(job, dict) else {}
    resource_id = max(0, int(payload.get("resource_id", 0) or 0))
    resource = get_resource_item(resource_id) if resource_id > 0 else {}
    if resource and str(resource.get("link_url", "")).strip():
        return resource
    extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
    return {
        "id": resource_id,
        "title": str(payload.get("title", "") or "").strip() or f"资源#{resource_id or '--'}",
        "link_url": str(payload.get("link_url", "") or "").strip(),
        "link_type": str(payload.get("link_type", "") or "").strip(),
        "message_url": str(payload.get("message_url", "") or "").strip(),
        "source_post_id": str(payload.get("source_post_id", "") or "").strip(),
        "extra": {
            "source_post_id": str(payload.get("source_post_id", "") or "").strip(),
            "receive_code": str(extra.get("receive_code", "") or "").strip(),
        },
    }


async def cancel_resource_job(job_id: int, reason: str = "manual") -> Dict[str, Any]:
    job = get_resource_job(job_id, include_private=True)
    if not job:
        raise RuntimeError("资源任务不存在")
    status = str(job.get("status", "") or "").strip().lower()
    if status == "completed":
        raise RuntimeError("任务已完成，无需取消")

    resource_job_cancel_requested.add(job_id)
    resource_refresh_pending.discard(job_id)
    resource_id = max(0, int(job.get("resource_id", 0) or 0))
    running_now = job_id in resource_job_running
    if status == "failed":
        return {"ok": True, "status": "already_failed", "running": running_now}

    detail = "已手动取消导入任务"
    if running_now:
        detail = "已手动取消导入任务，等待当前步骤结束"
    if str(reason or "").strip() and str(reason).strip().lower() != "manual":
        detail += f"（{reason}）"
    _mark_resource_job_failed(job_id, resource_id, detail)
    return {"ok": True, "status": "cancelled", "running": running_now}


async def retry_resource_job(job_id: int, reason: str = "manual") -> Dict[str, Any]:
    job = get_resource_job(job_id, include_private=True)
    if not job:
        raise RuntimeError("资源任务不存在")
    status = str(job.get("status", "") or "").strip().lower()
    if status in ("pending", "running", "submitted"):
        if job_id in resource_job_running:
            raise RuntimeError("任务仍在执行，请先取消后再重试")
        await cancel_resource_job(job_id, reason="retry")

    resource = _build_retry_resource_from_job(job)
    if not str(resource.get("link_url", "")).strip():
        raise RuntimeError("原任务缺少可导入链接，无法重试")

    link_type = resolve_resource_link_type(resource.get("link_type", ""), resource.get("link_url", ""))
    job_extra = job.get("extra") if isinstance(job.get("extra"), dict) else {}
    payload = {
        "folder_id": str(job.get("folder_id", "") or "").strip(),
        "savepath": normalize_relative_path(job.get("savepath", "")),
        "sharetitle": normalize_relative_path(job.get("sharetitle", "")),
        "monitor_task_name": str(job.get("monitor_task_name", "") or "").strip(),
        "refresh_delay_seconds": max(0, int(job.get("refresh_delay_seconds", 0) or 0)),
        "auto_refresh": bool(job.get("auto_refresh")),
        "extra": {},
    }
    for key in ("job_source", "webhook_task_name", "refresh_target_type"):
        value = str(job_extra.get(key, "") or "").strip()
        if value:
            payload["extra"][key] = value
    if not payload["extra"]:
        payload.pop("extra", None)
    if not payload["savepath"]:
        raise RuntimeError("原任务保存路径为空，无法重试")
    if link_type == "115share":
        payload["share_selection"] = normalize_share_selection_meta(job_extra)
        snapshot = job.get("_snapshot", {}) if isinstance(job.get("_snapshot"), dict) else {}
        receive_code = normalize_receive_code(
            str(snapshot.get("receive_code", "") or job_extra.get("receive_code", "")).strip()
        )
        if receive_code:
            payload["receive_code"] = receive_code

    new_job_id = create_resource_job(resource, payload)
    if status == "failed":
        update_resource_job(job_id, status_detail=f"已创建重试任务 #{new_job_id}（{reason}）")
    resource_job_cancel_requested.discard(new_job_id)
    asyncio.create_task(run_resource_job(new_job_id))
    return {"ok": True, "job_id": new_job_id}


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
        import_timeout_seconds = max(10, int(RESOURCE_IMPORT_TIMEOUT_SECONDS or 90))

        def ensure_not_cancelled(stage: str = "") -> None:
            if job_id not in resource_job_cancel_requested:
                return
            detail = "导入任务已取消"
            if stage:
                detail = f"{detail}（{stage}）"
            _mark_resource_job_failed(job_id, resource_id, detail)
            raise ResourceJobCancelledError(detail)

        ensure_not_cancelled("启动前")

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
        ensure_not_cancelled("提交前")

        if link_type == "magnet":
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        submit_115_offline_task,
                        str(cfg.get("cookie_115", "")).strip(),
                        str(job.get("link_url", "")).strip(),
                        str(job.get("folder_id", "")).strip(),
                    ),
                    timeout=import_timeout_seconds,
                )
            except asyncio.TimeoutError as exc:
                raise RuntimeError(f"提交到 115 超时（>{import_timeout_seconds} 秒）") from exc
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
            try:
                response_bundle = await asyncio.wait_for(
                    asyncio.to_thread(
                        submit_115_share_receive,
                        str(cfg.get("cookie_115", "")).strip(),
                        share_url,
                        str(job.get("folder_id", "")).strip(),
                        "",
                        job_selection.get("selected_ids", []),
                        str(job_snapshot.get("receive_code", "") or "").strip(),
                    ),
                    timeout=import_timeout_seconds,
                )
            except asyncio.TimeoutError as exc:
                raise RuntimeError(f"提交到 115 超时（>{import_timeout_seconds} 秒）") from exc
            response = response_bundle.get("response", {}) if isinstance(response_bundle, dict) else {}
            resolved_selection = merge_share_selection_meta(job_selection, response_bundle.get("selection", {}))
            detail = str(response.get("error", "")).strip() or str(response.get("msg", "")).strip() or "115 已接收转存任务"
            if bool(response_bundle.get("duplicate_receive", False)):
                detail = f"{detail}（已按幂等结果处理）"

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
        ensure_not_cancelled("提交后")

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
            detail = f"{detail}；当前保存路径未纳入文件夹监控，导入成功后不会自动生成 strm"

        next_status = "submitted" if monitor_task_name else "completed"

        update_fields = {
            "status": next_status,
            "status_detail": detail,
            "response_json": safe_json_dumps(response),
        }
        if next_status == "completed":
            update_fields["finished_at"] = now_text()
        if link_type == "115share":
            update_fields["extra_json"] = job.get("extra_json", safe_json_dumps({}))
            if str(job.get("sharetitle", "")).strip():
                update_fields["sharetitle"] = str(job.get("sharetitle", "")).strip()
        ensure_not_cancelled("状态写回前")
        update_resource_job(job_id, **update_fields)
        if resource_id > 0:
            conn = open_db()
            update_resource_item_status(conn, resource_id, next_status)
            conn.commit()
            conn.close()

        if bool(job.get("auto_refresh")) and str(job.get("monitor_task_name", "")).strip():
            asyncio.create_task(schedule_resource_job_refresh(job_id))
    except ResourceJobCancelledError:
        pass
    except Exception as exc:
        failed_job = get_resource_job(job_id, include_private=True)
        failed_resource_id = int((failed_job or {}).get("resource_id", 0) or 0)
        _mark_resource_job_failed(job_id, failed_resource_id, str(exc))
    finally:
        resource_job_running.discard(job_id)
        resource_job_cancel_requested.discard(job_id)
