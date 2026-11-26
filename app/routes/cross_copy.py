"""跨盘复制路由（#9 手动入口 + 任务管理）。

端点：
- GET  /cross_copy/capabilities   源×目标可用组合矩阵（UI 置灰依据）
- GET  /cross_copy/jobs           任务列表
- GET  /cross_copy/jobs/{id}      任务详情
- POST /cross_copy/jobs           手动创建（复制到目标网盘）
- POST /cross_copy/jobs/clear     批量清除已结束的任务记录
- POST /cross_copy/jobs/{id}/cancel   取消
- POST /cross_copy/jobs/{id}/retry    重试
- POST /cross_copy/jobs/{id}/delete   删除单条已结束记录
"""

from typing import Any, Dict, List

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..core import *  # noqa: F401,F403
from ..providers.registry import get_or_none as _get_provider_or_none
from ..services import cross_copy_jobs as ccj

router = APIRouter()

# 复制源需要下载直链能力（resolve_download_url）。
# 能力矩阵按这个常量算：三家都已实现取直链；新增源网盘时先确认 provider
# 里 resolve_download_url 真的实现了（基类默认是抛 NotImplementedError），再补进来。
SOURCE_CAPABLE = {"quark", "115", "aliyun"}
# 复制目标需要上传能力（supports_upload）
TARGET_CAPABLE = {"115", "quark", "aliyun"}


def _provider_label(name: str) -> str:
    provider = _get_provider_or_none(name)
    if provider is None:
        return name
    return str(getattr(provider, "label", "") or name)


def _as_bool(value: Any) -> bool:
    """前端可能传 true / "true" / 1 / "1"，统一成 bool。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


@router.get("/cross_copy/capabilities")
async def get_cross_copy_capabilities(request: Request) -> Dict[str, Any]:
    """返回源×目标组合矩阵与各 provider 能力（前端动态启用/禁用）。"""
    cfg = get_config()
    enabled_map = cfg.get("provider_enabled", {}) if isinstance(cfg.get("provider_enabled", {}), dict) else {}

    def provider_state(name: str) -> Dict[str, Any]:
        provider = _get_provider_or_none(name)
        enabled = bool(enabled_map.get(name, name in ("115", "quark")))
        configured = bool(provider.is_configured(cfg)) if provider else False
        return {
            "name": name,
            "label": _provider_label(name),
            "enabled": enabled,
            "configured": configured,
            "can_be_source": name in SOURCE_CAPABLE and enabled and configured,
            "can_be_target": name in TARGET_CAPABLE and enabled and configured,
        }

    providers: List[Dict[str, Any]] = []
    for name in sorted(SOURCE_CAPABLE | TARGET_CAPABLE):
        providers.append(provider_state(name))

    combinations = []
    for source in SOURCE_CAPABLE:
        for target in TARGET_CAPABLE:
            if source == target:
                continue
            source_state = next((p for p in providers if p["name"] == source), {})
            target_state = next((p for p in providers if p["name"] == target), {})
            combinations.append(
                {
                    "source": source,
                    "source_label": _provider_label(source),
                    "target": target,
                    "target_label": _provider_label(target),
                    "available": bool(source_state.get("can_be_source") and target_state.get("can_be_target")),
                }
            )
    return {"ok": True, "providers": providers, "combinations": combinations}


@router.get("/cross_copy/jobs")
async def list_cross_copy_jobs_endpoint(request: Request) -> Dict[str, Any]:
    limit = request.query_params.get("limit", "50")
    status = request.query_params.get("status", "")
    try:
        parsed_limit = max(1, min(200, int(limit)))
    except (TypeError, ValueError):
        parsed_limit = 50
    jobs = ccj.list_cross_copy_jobs(limit=parsed_limit, status=status)
    # counts 是整表统计：列表只给最近 N 条，而「清空」要清整表，
    # 两者数字必须能对上，否则用户会看到"还有记录但清不掉"。
    return {"ok": True, "jobs": jobs, "counts": ccj.get_cross_copy_job_counts()}


@router.post("/cross_copy/jobs/clear")
async def clear_cross_copy_jobs_endpoint(request: Request) -> Dict[str, Any]:
    """批量清除已结束的任务记录（scope: completed / failed / terminal）。

    只删记录：不删网盘上的文件、不影响正在跑的任务。
    """
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - 允许空 body，默认清全部已结束
        payload = {}
    scope = str((payload or {}).get("scope", "terminal") or "terminal").strip().lower()
    if scope not in {"completed", "failed", "terminal"}:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "不支持清理范围"})
    result = ccj.clear_cross_copy_jobs(scope)
    return {"ok": True, **result}


@router.get("/cross_copy/jobs/{job_id}")
async def get_cross_copy_job_endpoint(request: Request, job_id: int) -> Dict[str, Any]:
    job = ccj.get_cross_copy_job(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"ok": False, "msg": "任务不存在"})
    return {"ok": True, "job": job}


@router.post("/cross_copy/jobs")
async def create_cross_copy_job_endpoint(request: Request) -> Dict[str, Any]:
    """手动创建跨盘复制任务（源网盘文件/文件夹 → 目标网盘目录）。"""
    incoming = await request.json()
    payload = incoming if isinstance(incoming, dict) else {}
    source = str(payload.get("source_provider", "") or "").strip()
    target = str(payload.get("target_provider", "") or "").strip()
    source_file_id = str(payload.get("source_file_id", "") or "").strip()
    source_is_dir = _as_bool(payload.get("source_is_dir", False))

    if source not in SOURCE_CAPABLE:
        return JSONResponse(status_code=400, content={"ok": False, "msg": f"{_provider_label(source) or '该网盘'} 暂不支持作为复制源"})
    if target not in TARGET_CAPABLE:
        return JSONResponse(status_code=400, content={"ok": False, "msg": f"{_provider_label(target) or '该网盘'} 暂不支持作为复制目标"})
    if source == target:
        return JSONResponse(status_code=400, content={"ok": False, "msg": "复制源与目标不能是同一个网盘"})
    if not source_file_id:
        # 文件夹也走这个字段（指向文件夹 id），不因为「指向文件夹」而拒绝
        return JSONResponse(status_code=400, content={"ok": False, "msg": "源文件 ID 不能为空"})

    cfg = get_config()
    enabled_map = cfg.get("provider_enabled", {}) if isinstance(cfg.get("provider_enabled", {}), dict) else {}
    for name in (source, target):
        provider = _get_provider_or_none(name)
        if provider is None:
            return JSONResponse(status_code=400, content={"ok": False, "msg": f"网盘未注册：{name}"})
        if not bool(enabled_map.get(name, name in ("115", "quark"))):
            return JSONResponse(status_code=400, content={"ok": False, "msg": f"{provider.label} 未启用"})
        if not provider.is_configured(cfg):
            return JSONResponse(status_code=400, content={"ok": False, "msg": f"请先在参数配置中填写{provider.label}认证信息"})

    title = str(payload.get("title", "") or payload.get("filename", "") or "跨盘复制").strip()
    try:
        file_size = int(payload.get("file_size", 0) or 0)
    except (TypeError, ValueError):
        file_size = 0
    job_id = ccj.create_cross_copy_job(
        title=title,
        source_provider=source,
        target_provider=target,
        source_file_id=source_file_id,
        target_dir_id=str(payload.get("target_dir_id", "") or ""),
        target_savepath=str(payload.get("target_savepath", "") or ""),
        source_path=str(payload.get("source_path", "") or ""),
        target_path=str(payload.get("target_path", "") or ""),
        filename=str(payload.get("filename", "") or ""),
        file_size=file_size,
        origin="manual",
        origin_ref=str(payload.get("origin_ref", "") or ""),
        source_is_dir=source_is_dir,
    )
    ccj.submit_cross_copy_job(job_id)
    return {"ok": True, "job_id": job_id}


@router.post("/cross_copy/jobs/{job_id}/cancel")
async def cancel_cross_copy_job_endpoint(request: Request, job_id: int) -> Dict[str, Any]:
    result = ccj.cancel_cross_copy_job(job_id)
    status_code = 200 if result.get("ok") else 400
    return JSONResponse(status_code=status_code, content=result)


@router.post("/cross_copy/jobs/{job_id}/pause")
async def pause_cross_copy_job_endpoint(request: Request, job_id: int) -> Dict[str, Any]:
    result = ccj.pause_cross_copy_job(job_id)
    status_code = 200 if result.get("ok") else 400
    return JSONResponse(status_code=status_code, content=result)


@router.post("/cross_copy/jobs/{job_id}/resume")
async def resume_cross_copy_job_endpoint(request: Request, job_id: int) -> Dict[str, Any]:
    result = ccj.resume_cross_copy_job(job_id)
    status_code = 200 if result.get("ok") else 400
    return JSONResponse(status_code=status_code, content=result)


@router.post("/cross_copy/jobs/{job_id}/retry")
async def retry_cross_copy_job_endpoint(request: Request, job_id: int) -> Dict[str, Any]:
    result = ccj.retry_cross_copy_job(job_id)
    status_code = 200 if result.get("ok") else 400
    return JSONResponse(status_code=status_code, content=result)


@router.post("/cross_copy/jobs/{job_id}/delete")
async def delete_cross_copy_job_endpoint(request: Request, job_id: int) -> Dict[str, Any]:
    """删除单条任务记录（仅已结束的任务；只删记录，不删网盘文件）。"""
    result = ccj.delete_cross_copy_job(job_id)
    status_code = 200 if result.get("ok") else 400
    return JSONResponse(status_code=status_code, content=result)
