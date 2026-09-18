"""接收夹快捷导入：整理（与监控自动刮削共用同一流程）+ 按类型分发到监控目录。

最小改动接入现有工作流：

- 全局只多两项配置：``quick_import_enabled`` / ``quick_import_inbox_path``；
- 分发目标由监控任务自己声明（``monitor_tasks[].quick_import_target`` = movie / tv）；
- 整理选项一律取自目标监控任务的 ``auto_scrape_options``，避免两边规则不一致来回改；
- 搬运带 ``scraper-job:`` 来源标记，复用监控侧既有守卫——搬到监控目录后只生成 STRM，
  不会再被目标监控任务自动刮削一遍，同一条目一生只整理一次。
"""

import threading
from typing import Any, Dict, List, Optional, Set

from ..core import *  # noqa: F401,F403
from ..db import now_text, retry_sqlite_locked
from . import scraper as scraper_service
from .scraper import (
    _normalize_scraper_batch_preferences,
    build_scraper_plan_for_batch,
    create_scraper_job_from_plan,
    identify_scraper_batch_entries,
    resolve_scraper_dest_folder_id,
    submit_scraper_job,
)


QUICK_IMPORT_PROVIDER = "115"
QUICK_IMPORT_TARGET_KEYS = ("movie", "tv")
QUICK_IMPORT_TARGET_LABELS = {"movie": "电影", "tv": "电视剧"}
QUICK_IMPORT_SOURCE_ACTION_PREFIX = "quick-import"
QUICK_IMPORT_JOB_WAIT_SECONDS = max(
    30,
    int(os.environ.get("QUICK_IMPORT_JOB_WAIT_SECONDS", 900) or 900),
)
# 并发触发（多个导入同时完成）时排队而不是直接跳过，避免漏整理。
QUICK_IMPORT_LOCK_WAIT_SECONDS = max(
    30,
    int(os.environ.get("QUICK_IMPORT_LOCK_WAIT_SECONDS", 300) or 300),
)

_QUICK_IMPORT_RUN_LOCK = threading.Lock()


def _inbox_remote_path(cfg: Dict[str, Any]) -> str:
    return normalize_remote_path(str(cfg.get("quick_import_inbox_path", "") or "").strip())


def _inbox_rel_path(cfg: Dict[str, Any]) -> str:
    remote = _inbox_remote_path(cfg)
    if not remote:
        return ""
    try:
        _provider, relative = resolve_provider_relative_path(
            cfg,
            remote,
            expected_provider=QUICK_IMPORT_PROVIDER,
        )
    except Exception:
        return ""
    return normalize_relative_path(relative)


def _task_rel_path(cfg: Dict[str, Any], scan_path: Any) -> str:
    remote = normalize_remote_path(str(scan_path or "").strip())
    if not remote:
        return ""
    try:
        _provider, relative = resolve_provider_relative_path(
            cfg,
            remote,
            expected_provider=QUICK_IMPORT_PROVIDER,
        )
    except Exception:
        return normalize_relative_path(remote.lstrip("/"))
    return normalize_relative_path(relative)


def build_quick_import_config(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    active_cfg = cfg if isinstance(cfg, dict) else get_config()
    targets: Dict[str, Dict[str, Any]] = {key: {} for key in QUICK_IMPORT_TARGET_KEYS}
    for task in active_cfg.get("monitor_tasks", []) or []:
        if not isinstance(task, dict):
            continue
        key = str(task.get("quick_import_target", "") or "").strip().lower()
        if key not in QUICK_IMPORT_TARGET_KEYS or targets[key]:
            continue
        scan_path = normalize_remote_path(str(task.get("scan_path", "") or "").strip())
        rel_path = _task_rel_path(active_cfg, scan_path)
        if not scan_path or not rel_path:
            continue
        targets[key] = {
            "task_name": str(task.get("name", "") or "").strip(),
            "scan_path": scan_path,
            "scan_rel": rel_path,
            "auto_scrape_options": (
                task.get("auto_scrape_options") if isinstance(task.get("auto_scrape_options"), dict) else {}
            ),
        }
    return {
        "enabled": normalize_bool(active_cfg.get("quick_import_enabled", False), default=False),
        "inbox_path": _inbox_remote_path(active_cfg),
        "inbox_rel": _inbox_rel_path(active_cfg),
        "targets": targets,
    }


def is_quick_import_savepath(cfg: Dict[str, Any], savepath: Any) -> bool:
    """导入落点是否落在接收夹内（savepath 是网盘相对路径，如 ``接收/xxx``）。"""
    conf = build_quick_import_config(cfg)
    if not conf["enabled"]:
        return False
    inbox_rel = str(conf.get("inbox_rel", "") or "").strip()
    if not inbox_rel:
        return False
    relative = normalize_relative_path(str(savepath or "").strip())
    if not relative:
        return False
    return relative == inbox_rel or relative.startswith(inbox_rel + "/")


def validate_quick_import_config(cfg: Optional[Dict[str, Any]] = None) -> Optional[str]:
    active_cfg = cfg if isinstance(cfg, dict) else get_config()
    conf = build_quick_import_config(active_cfg)
    if not conf["enabled"]:
        return "快捷导入未启用"
    if not conf["inbox_path"]:
        return "请先选择接收文件夹"
    inbox_rel = str(conf.get("inbox_rel", "") or "").strip()
    if not inbox_rel:
        return "接收文件夹必须位于 115 网盘前缀下"
    if not any(conf["targets"].get(key) for key in QUICK_IMPORT_TARGET_KEYS):
        return "还没有监控任务标注为「电影 / 电视剧」快捷导入目标"
    for task in active_cfg.get("monitor_tasks", []) or []:
        if not isinstance(task, dict):
            continue
        scan_rel = _task_rel_path(active_cfg, task.get("scan_path", ""))
        if not scan_rel:
            continue
        overlap = (
            scan_rel == inbox_rel
            or scan_rel.startswith(inbox_rel + "/")
            or inbox_rel.startswith(scan_rel + "/")
        )
        if overlap:
            name = str(task.get("name", "") or "").strip() or "--"
            return f"接收文件夹不能与监控任务「{name}」的扫描路径（{scan_rel}）重叠"
    return None


def _target_scrape_options(target: Dict[str, Any]) -> Dict[str, Any]:
    options: Dict[str, Any] = {"title_language": "zh", "delete_ad_files": False}
    raw_options = target.get("auto_scrape_options") if isinstance(target, dict) else {}
    if isinstance(raw_options, dict) and raw_options:
        options.update(_normalize_scraper_batch_preferences(raw_options))
    return options


def _list_inbox_children(base_cid: str) -> List[Dict[str, Any]]:
    payload = scraper_service.list_scraper_entries(QUICK_IMPORT_PROVIDER, base_cid, True)
    entries = payload.get("entries") if isinstance(payload, dict) else []
    return [entry for entry in (entries or []) if isinstance(entry, dict)]


def _resolve_entry_after_organize(
    base_cid: str,
    plan_summary: Dict[str, Any],
    original_entry: Dict[str, Any],
) -> Dict[str, Any]:
    """整理后重新定位条目：文件夹按 ID 找；散文件按计划生成的片名文件夹兜底。"""
    try:
        children = _list_inbox_children(base_cid)
    except Exception:
        return {}
    original_id = str(original_entry.get("id", "") or "").strip()
    if original_id:
        for entry in children:
            if str(entry.get("id", "") or "").strip() == original_id:
                return entry
    title = str((plan_summary or {}).get("title", "") or "").strip()
    year = str((plan_summary or {}).get("year", "") or "").strip()
    if title:
        for entry in children:
            if not bool(entry.get("is_dir", False)):
                continue
            name = str(entry.get("name", "") or "").strip()
            if not name:
                continue
            if name == title or name.startswith(f"{title} (") or name.startswith(f"{title} ["):
                return entry
    return {}


def _insert_quick_import_run(trigger: str, inbox_path: str, started_at: str) -> int:
    ensure_db()

    def write() -> int:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO quick_import_runs (trigger, status, inbox_path, started_at)
                VALUES (?, ?, ?, ?)
                """,
                (str(trigger or "")[:40], "running", str(inbox_path or ""), str(started_at or "")),
            )
            conn.commit()
            return int(cursor.lastrowid or 0)

    return retry_sqlite_locked(write)


def _finish_quick_import_run(
    run_id: int,
    status: str,
    moved_count: int,
    left_count: int,
    summary: str,
    detail: Dict[str, Any],
) -> None:
    if run_id <= 0:
        return
    ensure_db()

    def write() -> None:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE quick_import_runs
                SET status = ?, finished_at = ?, moved_count = ?, left_count = ?, summary = ?, detail_json = ?
                WHERE id = ?
                """,
                (
                    str(status or ""),
                    now_text(),
                    max(0, int(moved_count or 0)),
                    max(0, int(left_count or 0)),
                    str(summary or "")[:500],
                    safe_json_dumps(detail or {}),
                    int(run_id),
                ),
            )
            conn.commit()

    retry_sqlite_locked(write)


def list_quick_import_runs(limit: int = 20) -> List[Dict[str, Any]]:
    normalized_limit = max(1, min(200, int(limit or 20)))
    ensure_db()

    def load() -> List[Dict[str, Any]]:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM quick_import_runs ORDER BY id DESC LIMIT ?",
                (normalized_limit,),
            )
            columns = [item[0] for item in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    return retry_sqlite_locked(load)


def get_quick_import_status() -> Dict[str, Any]:
    cfg = get_config()
    runs = list_quick_import_runs(1)
    latest = runs[0] if runs else {}
    detail = safe_json_loads(latest.get("detail_json", "{}"), {}) if latest else {}
    return {
        "enabled": build_quick_import_config(cfg)["enabled"],
        "inbox_path": str(cfg.get("quick_import_inbox_path", "") or ""),
        "config_error": validate_quick_import_config(cfg) or "",
        "targets": {
            key: {
                "task_name": (build_quick_import_config(cfg)["targets"].get(key) or {}).get("task_name", ""),
                "scan_path": (build_quick_import_config(cfg)["targets"].get(key) or {}).get("scan_path", ""),
            }
            for key in QUICK_IMPORT_TARGET_KEYS
        },
        "running": _QUICK_IMPORT_RUN_LOCK.locked(),
        "latest": latest,
        "latest_detail": detail,
    }


def _left_reason_from_result(result: Dict[str, Any]) -> str:
    if not isinstance(result, dict) or not result:
        return "未形成可识别条目"
    if str(result.get("ai_error") or "").strip():
        return f"AI 识别失败：{str(result.get('ai_error')).strip()[:120]}"
    low_confidence = max(0, parse_int(result.get("ai_low_confidence", 0), 0))
    if low_confidence > 0:
        return f"AI 置信度不足（{low_confidence}）"
    status = str(result.get("status") or "").strip()
    if status == "suggest":
        return "TMDB 建议但未达自动匹配阈值"
    if status == "manual":
        return "未匹配到 TMDB 条目"
    return "未达到自动整理条件"


def run_quick_import(trigger: str = "manual", *, sub_path: str = "") -> Dict[str, Any]:
    """扫描接收夹，整理高置信度条目并按类型分发到标注过的监控目录。

    低置信度 / 识别失败 / 计划冲突 / 搬运失败的条目都会留在接收夹，并记录具体原因。
    """
    if not _QUICK_IMPORT_RUN_LOCK.acquire(timeout=QUICK_IMPORT_LOCK_WAIT_SECONDS):
        return {"ok": True, "skipped": True, "summary": "已有快捷导入在执行，等待超时，本次跳过"}
    try:
        cfg = get_config()
        config_error = validate_quick_import_config(cfg)
        if config_error:
            raise RuntimeError(config_error)
        conf = build_quick_import_config(cfg)
        inbox_rel = conf["inbox_rel"]
        normalized_sub = normalize_relative_path(str(sub_path or "").strip())
        base_rel = normalize_relative_path(
            "/".join(part for part in (inbox_rel, normalized_sub) if part)
        )
        started_at = now_text()
        run_id = _insert_quick_import_run(trigger, conf["inbox_path"], started_at)
        moved: List[Dict[str, Any]] = []
        left: List[Dict[str, Any]] = []
        try:
            base_cid = resolve_scraper_dest_folder_id(QUICK_IMPORT_PROVIDER, base_rel)
            identified = identify_scraper_batch_entries(
                QUICK_IMPORT_PROVIDER,
                None,
                base_cid=base_cid,
                base_path=base_rel,
            )
            items = identified.get("items") or []
            results = identified.get("results") or []
            picked = identified.get("picked") or {}
            items_by_index = {
                max(0, parse_int(item.get("item_index", 0), 0)): item
                for item in items
                if isinstance(item, dict)
            }
            results_by_index = {
                max(0, parse_int(result.get("item_index", 0), 0)): result
                for result in results
                if isinstance(result, dict)
            }
            if not items:
                summary = "接收夹没有可整理的内容"
                _finish_quick_import_run(run_id, "completed", 0, 0, summary, {"moved": [], "left": []})
                return {"ok": True, "moved": [], "left": [], "summary": summary, "run_id": run_id}

            for index in sorted(picked):
                item = items_by_index.get(index)
                candidate = picked.get(index) if isinstance(picked.get(index), dict) else {}
                if not item or not candidate:
                    continue
                media_type = normalize_tmdb_media_type(candidate.get("media_type"), "")
                if media_type not in QUICK_IMPORT_TARGET_KEYS:
                    left.append(
                        {
                            "name": str(item.get("name", "") or ""),
                            "reason": "无法判断是电影还是电视剧",
                        }
                    )
                    continue
                target = conf["targets"].get(media_type) or {}
                if not target:
                    left.append(
                        {
                            "name": str(item.get("name", "") or ""),
                            "reason": f"没有监控任务标注为「{QUICK_IMPORT_TARGET_LABELS[media_type]}」快捷导入目标",
                        }
                    )
                    continue
                options = _target_scrape_options(target)
                # 接收夹里常常是"散文件"（没有独立文件夹），必须强制整理进 片名 (年份)/ 再搬运，
                # 否则只会原地改名、搬过去还是散文件。
                options["force_media_folder"] = True
                plan = build_scraper_plan_for_batch(
                    QUICK_IMPORT_PROVIDER,
                    [item],
                    {index: candidate},
                    options,
                    base_cid=base_cid,
                    base_path=base_rel,
                )
                plan_summaries = plan.get("items") if isinstance(plan, dict) else []
                plan_summary = plan_summaries[0] if isinstance(plan_summaries, list) and plan_summaries else {}
                issues = [
                    str(value).strip()
                    for value in ((plan.get("issues") if isinstance(plan, dict) else None) or [])
                    if str(value or "").strip()
                ]
                if not plan or issues:
                    left.append(
                        {
                            "name": str(item.get("name", "") or ""),
                            "reason": f"整理计划有冲突：{issues[0][:120]}" if issues else "无法生成整理计划",
                        }
                    )
                    continue
                ready_count = max(0, parse_int(plan.get("ready_count", 0), 0))
                job_id = 0
                if ready_count > 0:
                    try:
                        job = create_scraper_job_from_plan({"plan": plan})
                        job_id = max(0, parse_int(job.get("job_id", 0), 0))
                        if job_id > 0:
                            submit_scraper_job(job_id).result(timeout=QUICK_IMPORT_JOB_WAIT_SECONDS)
                    except Exception as exc:
                        left.append(
                            {
                                "name": str(item.get("name", "") or ""),
                                "reason": f"整理失败：{str(exc)[:120]}",
                            }
                        )
                        continue

                original_entry = item.get("entry") if isinstance(item.get("entry"), dict) else {}
                entry = _resolve_entry_after_organize(base_cid, plan_summary, original_entry)
                entry_id = str(entry.get("id", "") or "").strip()
                if not entry_id:
                    left.append(
                        {
                            "name": str(item.get("name", "") or ""),
                            "reason": "整理后未能在接收夹内定位到条目，请人工确认",
                        }
                    )
                    continue
                try:
                    target_cid = resolve_scraper_dest_folder_id(
                        QUICK_IMPORT_PROVIDER,
                        target["scan_rel"],
                    )
                    scraper_service.move_scraper_entries(
                        QUICK_IMPORT_PROVIDER,
                        [entry_id],
                        target_cid,
                        source_cid=base_cid,
                        entries=[entry],
                        target_parent_path=target["scan_rel"],
                        source_action=f"scraper-job:{job_id}:{QUICK_IMPORT_SOURCE_ACTION_PREFIX}",
                    )
                except Exception as exc:
                    left.append(
                        {
                            "name": str(item.get("name", "") or ""),
                            "reason": f"搬运失败：{str(exc)[:120]}",
                        }
                    )
                    continue
                moved.append(
                    {
                        "name": str(item.get("name", "") or ""),
                        "target": QUICK_IMPORT_TARGET_LABELS[media_type],
                        "task_name": str(target.get("task_name", "") or ""),
                        "job_id": job_id,
                    }
                )

            handled_indexes = set(picked.keys())
            for index, item in items_by_index.items():
                if index in handled_indexes:
                    continue
                left.append(
                    {
                        "name": str(item.get("name", "") or ""),
                        "reason": _left_reason_from_result(results_by_index.get(index) or {}),
                    }
                )

            summary = f"已整理分发 {len(moved)} 项，留在接收夹 {len(left)} 项"
            _finish_quick_import_run(
                run_id,
                "completed",
                len(moved),
                len(left),
                summary,
                {"moved": moved, "left": left},
            )
            return {
                "ok": True,
                "run_id": run_id,
                "moved": moved,
                "left": left,
                "summary": summary,
            }
        except Exception as exc:
            _finish_quick_import_run(
                run_id,
                "failed",
                len(moved),
                len(left),
                f"快捷导入失败：{str(exc)[:200]}",
                {"moved": moved, "left": left, "error": str(exc)[:300]},
            )
            raise
    finally:
        _QUICK_IMPORT_RUN_LOCK.release()
