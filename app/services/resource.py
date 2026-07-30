from ..background import submit_background
from ..core import *  # noqa: F401,F403
from ..db import db_connection
from ..memory import release_process_memory
from ..providers.registry import get_or_none as get_provider_or_none
from .monitor import queue_monitor_job


class ResourceJobCancelledError(RuntimeError):
    pass


RESOURCE_OFFLINE_LINK_TYPES = frozenset(("magnet", "ed2k"))


def is_resource_offline_link_type(link_type: Any) -> bool:
    return str(link_type or "").strip().lower() in RESOURCE_OFFLINE_LINK_TYPES


def _get_resource_offline_provider(job: Dict[str, Any], cfg: Dict[str, Any]):
    extra = job.get("extra") if isinstance(job.get("extra"), dict) else safe_json_loads(job.get("extra_json"), {})
    provider_name = str(
        extra.get("offline_provider", "")
        or extra.get("magnet_provider", "")
        or normalize_magnet_provider((cfg or {}).get("default_magnet_provider", "115"))
    ).strip().lower()
    provider = get_provider_or_none(provider_name)
    if not provider:
        raise RuntimeError("离线下载网盘配置无效")
    if not provider.supports_offline:
        raise RuntimeError(f"{provider.label} 暂不支持离线下载")
    return provider


def _mark_resource_job_failed(job_id: int, resource_id: int, detail: str) -> None:
    fail_detail = str(detail or "资源导入失败").strip() or "资源导入失败"
    update_resource_job(job_id, status="failed", status_detail=fail_detail, finished_at=now_text())
    if resource_id > 0:
        with db_connection() as conn:
            update_resource_item_status(conn, resource_id, "failed")
            conn.commit()


def _build_retry_resource_from_job(job: Dict[str, Any]) -> Dict[str, Any]:
    payload = job if isinstance(job, dict) else {}
    resource_id = max(0, int(payload.get("resource_id", 0) or 0))
    resource = get_resource_item(resource_id) if resource_id > 0 else {}
    if resource and str(resource.get("link_url", "")).strip():
        return resource
    extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
    snapshot = payload.get("_snapshot") if isinstance(payload.get("_snapshot"), dict) else {}
    source_extra = {}
    for key in ("source_url", "source_resource_title", "source_page_title"):
        value = str(snapshot.get(key, "") or extra.get(key, "") or "").strip()
        if value:
            source_extra[key] = value
    return {
        "id": resource_id,
        "title": str(payload.get("title", "") or "").strip() or f"资源#{resource_id or '--'}",
        "link_url": str(payload.get("link_url", "") or "").strip(),
        "link_type": str(payload.get("link_type", "") or "").strip(),
        "message_url": str(
            payload.get("message_url", "")
            or snapshot.get("message_url", "")
            or snapshot.get("source_url", "")
            or ""
        ).strip(),
        "source_post_id": str(payload.get("source_post_id", "") or "").strip(),
        "extra": {
            "source_post_id": str(payload.get("source_post_id", "") or "").strip(),
            "receive_code": str(extra.get("receive_code", "") or "").strip(),
            **source_extra,
        },
    }


def _get_share_receive_provider_by_link_type(link_type: str):
    try:
        from ..providers.registry import get_by_link_type as _registry_get_by_link_type

        provider = _registry_get_by_link_type(link_type)
        if provider and provider.supports_share_receive:
            return provider
    except Exception:
        return None
    return None


def _build_resource_job_selected_entries(selection: Dict[str, Any]) -> List[Dict[str, Any]]:
    normalized = normalize_share_selection_meta(selection or {})
    entries = normalized.get("selected_entries", []) if isinstance(normalized.get("selected_entries"), list) else []
    if entries:
        return [entry for entry in entries if isinstance(entry, dict)]
    selected_ids = normalized.get("selected_ids", []) if isinstance(normalized.get("selected_ids"), list) else []
    return [{"id": str(entry_id).strip()} for entry_id in selected_ids if str(entry_id or "").strip()]


def _submit_provider_share_receive_job(
    provider: Any,
    cookie: str,
    link_url: str,
    raw_text: str,
    folder_id: str,
    receive_code: str,
    selection: Dict[str, Any],
) -> Dict[str, Any]:
    selected_entries = _build_resource_job_selected_entries(selection)
    selected_ids = [
        str(entry.get("id", "")).strip()
        for entry in selected_entries
        if isinstance(entry, dict) and str(entry.get("id", "")).strip()
    ]
    share_payload = provider.resolve_share_payload(cookie, link_url, raw_text, receive_code)
    receive_payload = provider.prepare_share_receive(cookie, share_payload, folder_id)
    receive_payload["url"] = str(share_payload.get("url", "") or link_url).strip()
    receive_payload["raw_text"] = raw_text
    receive_payload["receive_code"] = str(share_payload.get("receive_code", "") or receive_code).strip()
    receive_payload["target_cid"] = folder_id
    receive_payload["selected_ids"] = selected_ids
    receive_payload["selected_entries"] = selected_entries

    if not selected_entries:
        snapshot = provider.list_share_entries(cookie, share_payload, "0", 0, 200)
        snapshot_entries = snapshot.get("entries", []) if isinstance(snapshot.get("entries"), list) else []
        selected_entries = [entry for entry in snapshot_entries if isinstance(entry, dict)]
        selected_ids = [
            str(entry.get("id", "")).strip()
            for entry in selected_entries
            if str(entry.get("id", "")).strip()
        ]
        receive_payload["selected_ids"] = selected_ids
        receive_payload["selected_entries"] = selected_entries
        if selected_ids:
            receive_payload["selection"] = merge_share_selection_meta(
                receive_payload.get("selection", {}),
                {
                    "selected_ids": selected_ids,
                    "selected_entries": selected_entries,
                    "share_root_title": str(snapshot.get("share_title", "") or "").strip(),
                },
            )

    return provider.submit_share_receive(cookie, receive_payload, selected_entries)


async def cancel_resource_job(job_id: int, reason: str = "manual") -> Dict[str, Any]:
    job = get_resource_job(job_id, include_private=True)
    if not job:
        raise RuntimeError("资源任务不存在")
    status = str(job.get("status", "") or "").strip().lower()
    if status == "completed":
        raise RuntimeError("任务已完成，无需取消")

    with resource_job_lock:
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
        if job_id in resource_job_running:  # GIL protects single set membership check
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
    for key in (
        "job_source",
        "webhook_task_name",
        "refresh_target_type",
        "offline_provider",
        "offline_provider_label",
        "magnet_provider",
        "magnet_provider_label",
        "source_url",
        "source_resource_title",
        "source_page_title",
    ):
        value = str(job_extra.get(key, "") or "").strip()
        if value:
            payload["extra"][key] = value
    if not payload["extra"]:
        payload.pop("extra", None)
    if not payload["savepath"]:
        raise RuntimeError("原任务保存路径为空，无法重试")
    if _get_share_receive_provider_by_link_type(link_type):
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
    submit_background(run_resource_job, new_job_id, label="resource-job-retry")
    return {"ok": True, "job_id": new_job_id}


async def run_offline_resource_job_batch(
    job_ids: List[int],
    *,
    provider_name: str,
    savepath: str,
    create_folder: bool,
    folder_id: str = "",
) -> None:
    normalized_job_ids = [max(0, int(job_id or 0)) for job_id in (job_ids or [])]
    normalized_job_ids = [job_id for job_id in normalized_job_ids if job_id > 0]
    if not normalized_job_ids:
        return
    try:
        cfg = get_config()
        provider = get_provider_or_none(str(provider_name or "").strip().lower())
        if not provider or not provider.supports_offline:
            raise RuntimeError("离线下载网盘配置无效")
        cookie = provider.get_cookie(cfg)
        if not cookie:
            raise RuntimeError(f"请先在参数配置中填写 {provider.label} 认证信息")

        target_folder_id = str(folder_id or "").strip()
        if not target_folder_id:
            prepare_folder = provider.ensure_folder_id_by_path if create_folder else provider.resolve_folder_id_by_path
            target_folder_id = await asyncio.wait_for(
                asyncio.to_thread(prepare_folder, cookie, normalize_relative_path(savepath)),
                timeout=min(max(10, int(RESOURCE_IMPORT_TIMEOUT_SECONDS or 90)), 60),
            )
            target_folder_id = str(target_folder_id or "").strip()
        if not target_folder_id:
            raise RuntimeError("未获取到目标文件夹 ID")

        for job_id in normalized_job_ids:
            update_resource_job(
                job_id,
                folder_id=target_folder_id,
                status="pending",
                status_detail=f"目标目录已准备，等待提交到 {provider.label}",
            )
        for job_id in normalized_job_ids:
            await run_resource_job(job_id)
    except Exception as exc:
        detail = f"批量目标目录准备失败：{exc}"
        for job_id in normalized_job_ids:
            job = get_resource_job(job_id, include_private=True)
            resource_id = max(0, int((job or {}).get("resource_id", 0) or 0))
            _mark_resource_job_failed(job_id, resource_id, detail)


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
    job_extra = job.get("extra") if isinstance(job.get("extra"), dict) else safe_json_loads(job.get("extra_json"), {})
    if (
        str(reason or "").strip().lower() == "auto"
        and str(job.get("job_source", "") or job_extra.get("job_source", "") or "").strip() == "subscription_auto"
    ):
        subscription_run_id = str(job_extra.get("subscription_run_id", "") or "").strip()
        if subscription_run_id:
            payload["subscription_run_id"] = subscription_run_id
            subscription_task_name = str(job_extra.get("subscription_task_name", "") or "").strip()
            if subscription_task_name:
                payload["subscription_task_name"] = subscription_task_name
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
        with db_connection() as conn:
            update_resource_item_status(conn, resource_id, "completed")
            conn.commit()
    return {"ok": True, "status": status}


async def schedule_resource_job_refresh(job_id: int) -> None:
    with resource_job_lock:
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
        with resource_job_lock:
            resource_refresh_pending.discard(job_id)


async def run_resource_job(job_id: int) -> None:
    with resource_job_lock:
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

        link_type = resolve_resource_link_type(job.get("link_type", ""), job.get("link_url", ""))
        share_provider = _get_share_receive_provider_by_link_type(link_type)
        is_share_receive_link = bool(share_provider)
        is_offline_link = is_resource_offline_link_type(link_type)
        if not is_offline_link and not is_share_receive_link:
            raise RuntimeError("当前仅支持离线下载和已启用网盘的分享转存")
        cfg = get_config()
        provider_cookie = ""
        provider_label = "115"
        mp = None  # provider instance for offline tasks
        if is_share_receive_link:
            provider_label = str(getattr(share_provider, "label", "") or share_provider.name).strip()
            enabled_map = cfg.get("provider_enabled", {}) if isinstance(cfg.get("provider_enabled", {}), dict) else {}
            if not bool(enabled_map.get(share_provider.name, share_provider.name in ("115", "quark"))):
                raise RuntimeError(f"{provider_label} 未启用")
            provider_cookie = share_provider.get_cookie(cfg)
        elif is_offline_link:
            mp = _get_resource_offline_provider(job, cfg)
            provider_cookie = mp.get_cookie(cfg)
            provider_label = mp.label
            if not provider_cookie:
                raise RuntimeError(f"请先在参数配置中填写 {provider_label} 认证信息")
        if not provider_cookie and not is_share_receive_link:
            raise RuntimeError(f"请先在参数配置中填写 {provider_label} 认证信息")

        folder_id = str(job.get("folder_id", "") or "").strip()
        if not folder_id or folder_id == "0":
            update_resource_job(
                job_id,
                status="running",
                status_detail=f"正在解析{provider_label}保存路径",
                started_at=now_text(),
            )
            try:
                if is_offline_link:
                    folder_id = await asyncio.wait_for(
                        asyncio.to_thread(
                            mp.resolve_folder_id_by_path,
                            provider_cookie,
                            str(job.get("savepath", "") or "").strip(),
                        ),
                        timeout=min(import_timeout_seconds, 60),
                    )
                else:
                    folder_id = await asyncio.wait_for(
                        asyncio.to_thread(
                            share_provider.resolve_folder_id_by_path,
                            provider_cookie,
                            str(job.get("savepath", "") or "").strip(),
                        ),
                        timeout=min(import_timeout_seconds, 60),
                    )
            except asyncio.TimeoutError as exc:
                raise RuntimeError(f"保存路径解析超时（>{min(import_timeout_seconds, 60)} 秒）") from exc
            except Exception as exc:
                raise RuntimeError(f"保存路径无效：{exc}") from exc
            folder_id = str(folder_id or "").strip() or "0"
            job["folder_id"] = folder_id
            update_resource_job(job_id, folder_id=folder_id)

        update_resource_job(
            job_id,
            status="running",
            status_detail=f"正在提交到 {provider_label}",
            started_at=now_text(),
        )
        if resource_id > 0:
            with db_connection() as conn:
                update_resource_item_status(conn, resource_id, "importing")
                conn.commit()
        ensure_not_cancelled("提交前")

        if is_offline_link:
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        mp.submit_offline_task,
                        provider_cookie,
                        str(job.get("link_url", "")).strip(),
                        str(job.get("folder_id", "")).strip(),
                    ),
                    timeout=import_timeout_seconds,
                )
            except asyncio.TimeoutError as exc:
                raise RuntimeError(f"提交到 {provider_label} 超时（>{import_timeout_seconds} 秒）") from exc
            detail = str(response.get("error_msg", "") or response.get("message", "")).strip() or f"{provider_label} 已接收离线任务"
        else:
            job_extra = safe_json_loads(job.get("extra_json"), {})
            job_selection = normalize_share_selection_meta(job_extra)
            receive_code = normalize_receive_code(
                str(job_snapshot.get("receive_code", "") or job_extra.get("receive_code", "")).strip()
            )
            share_url = apply_share_receive_code_to_url(
                str(job.get("link_url", "")).strip(),
                receive_code,
            )
            try:
                response_bundle = await asyncio.wait_for(
                    asyncio.to_thread(
                        _submit_provider_share_receive_job,
                        share_provider,
                        provider_cookie,
                        share_url,
                        str((resource or {}).get("raw_text", "") or ""),
                        str(job.get("folder_id", "")).strip(),
                        receive_code,
                        job_selection,
                    ),
                    timeout=import_timeout_seconds,
                )
            except asyncio.TimeoutError as exc:
                raise RuntimeError(f"提交到 {provider_label} 超时（>{import_timeout_seconds} 秒）") from exc
            response = response_bundle.get("response", response_bundle) if isinstance(response_bundle, dict) else {}
            resolved_selection = merge_share_selection_meta(job_selection, response_bundle.get("selection", {}))
            detail = (
                str(response.get("error", "")).strip()
                or str(response.get("message", "")).strip()
                or str(response.get("msg", "")).strip()
                or f"{provider_label} 已接收转存任务"
            )
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

        if is_share_receive_link and not bool(getattr(share_provider, "supports_monitor", False)):
            detail = f"{detail}；{provider_label} 链路不联动文件夹监控，导入成功后不会自动刷新"
            next_status = "completed"
        else:
            monitor_task_name = str(job.get("monitor_task_name", "") or "").strip()
            auto_refresh_enabled = bool(job.get("auto_refresh"))
            if monitor_task_name:
                delay_seconds = max(0, int(job.get("refresh_delay_seconds", 0) or 0))
                if auto_refresh_enabled:
                    refresh_text = (
                        f"等待 {delay_seconds} 秒后自动触发文件夹监控"
                        if delay_seconds > 0
                        else "提交后自动触发文件夹监控"
                    )
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
        if is_share_receive_link:
            update_fields["extra_json"] = job.get("extra_json", safe_json_dumps({}))
            if str(job.get("sharetitle", "")).strip():
                update_fields["sharetitle"] = str(job.get("sharetitle", "")).strip()
        ensure_not_cancelled("状态写回前")
        update_resource_job(job_id, **update_fields)
        if resource_id > 0:
            with db_connection() as conn:
                update_resource_item_status(conn, resource_id, next_status)
                conn.commit()

        if (
            (not is_share_receive_link or bool(getattr(share_provider, "supports_monitor", False)))
            and bool(job.get("auto_refresh"))
            and str(job.get("monitor_task_name", "")).strip()
        ):
            submit_background(schedule_resource_job_refresh, job_id, label="resource-auto-refresh")
    except ResourceJobCancelledError:
        pass
    except Exception as exc:
        failed_job = get_resource_job(job_id, include_private=True)
        failed_resource_id = int((failed_job or {}).get("resource_id", 0) or 0)
        _mark_resource_job_failed(job_id, failed_resource_id, str(exc))
    finally:
        with resource_job_lock:
            resource_job_running.discard(job_id)
            resource_job_cancel_requested.discard(job_id)
        release_process_memory(f"resource-job:{job_id}", force=True)
