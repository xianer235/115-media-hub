import asyncio
import os
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack
from typing import List, Optional
from unittest.mock import AsyncMock, Mock, patch

from app import db
from app.services import monitor, monitor_changes, strm_files


TASK_NAME = "Monitor"


class AutoRescanQueueTest(unittest.TestCase):
    def test_auto_rescan_helper_dedupes_and_counts(self):
        with patch.object(
            monitor,
            "queue_monitor_dir_scan",
            return_value={"ok": True, "tasks": [{"task_name": TASK_NAME, "run_id": "run-1"}]},
        ) as queue_scan:
            queued = monitor._queue_auto_rescan_for_manual_required({}, ["Media/Copied", "Media/Copied"])
        self.assertEqual(queued, {"count": 1, "run_ids": ["run-1"]})
        queue_scan.assert_called_once_with(
            {},
            "115",
            ["Media/Copied"],
            run_source="auto_rescan",
            force_new=True,
            parent_run_id="",
        )

    def test_auto_rescan_helper_returns_zero_on_failure(self):
        with patch.object(
            monitor,
            "queue_monitor_dir_scan",
            side_effect=ValueError("所选目录未匹配到任何监控任务"),
        ):
            self.assertEqual(
                monitor._queue_auto_rescan_for_manual_required({}, ["Media/Copied"]),
                {"count": 0, "run_ids": []},
            )

    def test_auto_rescan_helper_ignores_empty_paths(self):
        with patch.object(monitor, "queue_monitor_dir_scan") as queue_scan:
            self.assertEqual(
                monitor._queue_auto_rescan_for_manual_required({}, []),
                {"count": 0, "run_ids": []},
            )
        queue_scan.assert_not_called()

    def test_auto_rescan_queues_each_directory_as_its_own_task(self):
        with patch.object(
            monitor,
            "queue_monitor_dir_scan",
            side_effect=[
                {"ok": True, "tasks": [{"task_name": TASK_NAME, "run_id": "run-a"}]},
                {"ok": True, "tasks": [{"task_name": TASK_NAME, "run_id": "run-b"}]},
            ],
        ) as queue_scan:
            queued = monitor._queue_auto_rescan_for_manual_required(
                {}, ["Media/A", "Media/B"], parent_run_id="change-run-1"
            )

        self.assertEqual(queued, {"count": 2, "run_ids": ["run-a", "run-b"]})
        self.assertEqual(queue_scan.call_count, 2)
        queue_scan.assert_any_call(
            {}, "115", ["Media/A"],
            run_source="auto_rescan", force_new=True, parent_run_id="change-run-1",
        )
        queue_scan.assert_any_call(
            {}, "115", ["Media/B"],
            run_source="auto_rescan", force_new=True, parent_run_id="change-run-1",
        )

    def test_retry_pending_manual_rescans_skips_already_queued_directories(self):
        task = {"name": TASK_NAME, "scan_path": "/115/Library", "task_type": "scan"}
        cfg = {"monitor_tasks": [task]}
        scopes = [
            {"provider_path": "Library/SeriesA", "monitor_run_id": "change-1"},
            {"provider_path": "Library/SeriesB", "monitor_run_id": "change-1"},
        ]
        monitor._manual_rescan_retry_state["last_ts"] = 0.0
        with patch(
            "app.services.monitor_changes.get_manual_required_monitor_scopes",
            return_value=scopes,
        ), patch.object(
            monitor,
            "list_active_scan_scopes",
            return_value={"covers_task": False, "paths": ["/115/Library/SeriesA"]},
        ), patch.object(
            monitor,
            "queue_monitor_dir_scan",
            return_value={"ok": True, "tasks": [{"task_name": TASK_NAME, "run_id": "run-b"}]},
        ) as queue_scan:
            queued = monitor.retry_pending_manual_rescans(cfg)

        self.assertEqual(queued, {"queued": 1})
        queue_scan.assert_called_once_with(
            cfg, "115", ["Library/SeriesB"],
            run_source="auto_rescan", force_new=True, parent_run_id="change-1",
        )

    def test_retry_pending_manual_rescans_stops_after_one_failed_attempt(self):
        """自动补扫只尝试一次：已经失败过的目录不再自动重排，交给人工处理。"""
        task = {"name": TASK_NAME, "scan_path": "/115/Library", "task_type": "scan"}
        cfg = {"monitor_tasks": [task]}
        scopes = [{"provider_path": "Library/SeriesA", "monitor_run_id": "change-1"}]
        monitor._manual_rescan_retry_state["last_ts"] = 0.0
        with patch(
            "app.services.monitor_changes.get_manual_required_monitor_scopes",
            return_value=scopes,
        ), patch.object(
            monitor,
            "list_active_scan_scopes",
            return_value={"covers_task": False, "paths": []},
        ), patch.object(
            monitor,
            "list_recent_failed_scan_runs",
            return_value=[{"id": "failed-1", "paths": ["/Library/SeriesA"], "covers_task": False}],
        ) as failed_runs, patch.object(monitor, "queue_monitor_dir_scan") as queue_scan:
            queued = monitor.retry_pending_manual_rescans(cfg)

        self.assertEqual(queued, {"queued": 0})
        queue_scan.assert_not_called()
        # 不再带时间窗：只要补扫尝试过并且失败，就永久停止自动重排。
        self.assertEqual(failed_runs.call_args.args, (TASK_NAME,))


class DispatchScanDedupTest(unittest.TestCase):
    """分发条目已经有自己的同步子任务时，变更同步不能再排一次重复扫描。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        self.original_ensured = db._DB_ENSURED
        db.DB_PATH = os.path.join(self.tmpdir.name, "data.db")
        db._DB_ENSURED = False
        db.ensure_db()

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        db._DB_ENSURED = self.original_ensured
        self.tmpdir.cleanup()

    def _cfg(self) -> dict:
        return {
            "mount_points": [{"provider": "115", "prefix": "/115"}],
            "monitor_tasks": [{"name": TASK_NAME, "scan_path": "/115/Library", "task_type": "scan"}],
        }

    def test_existing_dispatch_scan_skips_duplicate_queueing(self):
        """已有的接收夹分发扫描（独立记录、无父运行）按任务 + 来源去重。"""
        from app.services import monitor_runs

        child = monitor_runs.create_run(
            run_kind="scan",
            task_name=TASK_NAME,
            source="inbox_dispatch",
            scope={"kind": "paths", "paths": ["/115/Library/Copied"]},
        )
        monitor_runs.finish_run(child, status="completed", summary="已同步", result={"generated": 1})

        with patch.object(monitor, "queue_monitor_dir_scan") as queue_scan:
            run_ids = monitor._queue_dispatch_item_scans(self._cfg(), ["Library/Copied"])

        self.assertEqual(run_ids, [])
        queue_scan.assert_not_called()

    def test_new_scope_still_queues_its_own_scan(self):
        from app.services import monitor_runs

        cfg = self._cfg()
        monitor_runs.finish_run(
            monitor_runs.create_run(
                run_kind="scan",
                task_name=TASK_NAME,
                source="inbox_dispatch",
                scope={"kind": "paths", "paths": ["/115/Library/Other"]},
            ),
            status="completed",
            summary="已同步",
            result={"generated": 1},
        )

        with patch.object(
            monitor,
            "queue_monitor_dir_scan",
            return_value={"ok": True, "tasks": [{"task_name": TASK_NAME, "run_id": "run-new"}]},
        ) as queue_scan:
            run_ids = monitor._queue_dispatch_item_scans(cfg, ["Library/Copied"])

        self.assertEqual(run_ids, ["run-new"])
        queue_scan.assert_called_once_with(
            cfg, "115", ["Library/Copied"],
            run_source="inbox_dispatch", force_new=True,
        )

    def test_failed_rescan_marks_scope_and_splits_card_counts(self):
        """补扫失败过一次的目录标记为需人工处理，卡片计数与待补扫分开。"""
        from app.services import monitor_changes, monitor_runs

        cfg = self._cfg()
        with db.db_connection() as conn:
            conn.execute(
                """INSERT INTO monitor_change_events(
                    dedupe_key, operation, old_path, new_path, task_name,
                    source_action, monitor_run_id, status, created_at, updated_at
                ) VALUES (?, 'move', ?, ?, ?, 'scraper-job:1:quick-import', '', 'manual_required', ?, ?)""",
                (
                    "failed-rescan-event",
                    "最近接收/魔方小姐",
                    "Library/魔方小姐",
                    TASK_NAME,
                    "2026-09-26T15:00:00",
                    "2026-09-26T15:00:00",
                ),
            )
            conn.commit()
        failed_run = monitor_runs.create_run(
            run_kind="scan",
            task_name=TASK_NAME,
            source="auto_rescan",
            scope={"kind": "paths", "paths": ["/Library/魔方小姐"]},
            subject="魔方小姐",
        )
        monitor_runs.finish_run(
            failed_run, status="failed", summary="读取目录失败，本轮未完整检查", result={"failed_dirs": 1}
        )

        scopes = monitor_changes.get_manual_required_monitor_scopes(TASK_NAME, cfg=cfg)
        self.assertEqual(len(scopes), 1)
        self.assertTrue(scopes[0]["retry_blocked"])
        self.assertIn("读取目录失败", scopes[0]["failed_summary"])

        counts = monitor_changes.get_monitor_change_counts(cfg=cfg)
        self.assertEqual(counts[TASK_NAME]["manual_required"], 0)
        self.assertEqual(counts[TASK_NAME]["manual_required_failed"], 1)


class ChangeRunWaitsForAutoRescanTest(unittest.TestCase):
    """变更同步把目录交给自动补扫后，必须等补扫结束再结算整条链路。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        self.original_ensured = db._DB_ENSURED
        db.DB_PATH = os.path.join(self.tmpdir.name, "data.db")
        db._DB_ENSURED = False
        db.ensure_db()
        self.cfg = {
            "monitor_tasks": [
                {
                    "name": TASK_NAME,
                    "task_type": "scan",
                    "enabled": True,
                    "scan_path": "/115/Media",
                    "target_path": "Media",
                }
            ]
        }

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        db._DB_ENSURED = self.original_ensured
        self.tmpdir.cleanup()

    def _run_change_task(
        self,
        inbox_run: str,
        *,
        dispatched_item_paths: Optional[List[str]] = None,
        manual_required: int = 1,
        manual_required_paths: Optional[List[str]] = None,
    ) -> str:
        from app.services import monitor_runs

        change_run = monitor_runs.create_run(
            run_kind="change", task_name=TASK_NAME, source="change", subject="文件变更"
        )
        change_result = {
            "completed": 1,
            "failed": 0,
            "discarded": 0,
            "generated": 0,
            "deleted": 0,
            "manual_required": manual_required,
            "manual_required_paths": ["Media/Copied"] if manual_required_paths is None else manual_required_paths,
            "dispatched_item_paths": list(dispatched_item_paths or []),
            "errors": [],
            "change_details": [],
            "source_actions": [],
            "monitor_run_ids": [inbox_run] if inbox_run else [],
        }
        with patch.object(monitor, "_claim_monitor_job", return_value=True), \
                patch.object(monitor, "get_config", return_value=self.cfg), \
                patch.object(monitor, "_finish_monitor_job", new=AsyncMock()), \
                patch.object(monitor, "write_monitor_task_header", new=AsyncMock()), \
                patch.object(monitor, "write_monitor_task_footer", new=AsyncMock()), \
                patch.object(monitor, "write_monitor_section", new=AsyncMock()), \
                patch.object(monitor, "write_monitor_log", new=AsyncMock()), \
                patch.object(monitor, "_write_monitor_change_details", new=AsyncMock()), \
                patch.object(monitor, "schedule_ui_state_push", lambda *args, **kwargs: None), \
                patch.object(monitor, "submit_background", lambda *args, **kwargs: None), \
                patch.object(monitor_changes, "process_monitor_change_events", new=AsyncMock(return_value=change_result)):
            asyncio.run(monitor.run_monitor_change_task(TASK_NAME, "change", {"mode": "change"}, change_run))
        return change_run

    def test_change_run_waits_for_auto_rescan_only(self):
        """变更同步只等自己的自动补扫；不再改写接收夹记录、也不再挂到它下面。"""
        from app.services import monitor_runs

        inbox = monitor_runs.create_run(
            run_kind="inbox", task_name="最近接收", source="manual", subject="六部影视"
        )
        monitor_runs.start_run(inbox)
        monitor_runs.wait_run(
            inbox,
            summary="已分发，等待 STRM 同步",
            result={"moved": 1, "left": 0, "monitor_sync_events": 1},
        )

        change_run = self._run_change_task(inbox)
        detail = monitor_runs.get_run_detail(change_run)
        rescan_runs = [item for item in detail["descendants"] if item["run_kind"] == "scan"]

        self.assertEqual(detail["run"]["status"], "waiting")
        self.assertIn("等待 1 个目录的自动补扫", detail["run"]["summary"])
        self.assertEqual(len(rescan_runs), 1)
        self.assertEqual(rescan_runs[0]["source"], "auto_rescan")
        # 解耦后变更同步不再挂到接收夹运行下：历史 waiting 记录由启动收敛处理，
        # 不会被这条变更链路改写。
        self.assertEqual(detail["run"]["parent_run_id"], "")
        self.assertEqual(monitor_runs.get_run_detail(inbox)["run"]["status"], "waiting")

        monitor_runs.finish_run(
            rescan_runs[0]["id"], status="completed",
            summary="新增或更新 1 个本地播放文件", result={"generated": 1},
        )

        self.assertEqual(monitor_runs.get_run_detail(change_run)["run"]["status"], "completed")
        self.assertEqual(monitor_runs.get_run_detail(inbox)["run"]["status"], "waiting")

    def test_dispatched_item_gets_its_own_run_record(self):
        """接收夹分发的每个条目都要有一条独立记录（清单已知时也要有）。"""
        from app.services import monitor_runs

        inbox = monitor_runs.create_run(
            run_kind="inbox", task_name="最近接收", source="manual", subject="六部影视"
        )
        monitor_runs.start_run(inbox)
        monitor_runs.finish_run(
            inbox,
            status="completed",
            summary="已分发 1 项。",
            result={"moved": 1, "left": 0},
        )

        change_run = self._run_change_task(
            inbox,
            dispatched_item_paths=["Media/Copied"],
            manual_required=0,
            manual_required_paths=[],
        )
        detail = monitor_runs.get_run_detail(change_run)
        # 分发扫描是独立运行记录：变更同步只是补排它们，不再挂成下游等待。
        item_runs = [item for item in detail["children"] if item["source"] == "inbox_dispatch"]
        if not item_runs:
            item_runs = [
                run for run in monitor_runs.list_runs(limit=20)["runs"]
                if run["source"] == "inbox_dispatch"
            ]

        self.assertEqual(len(item_runs), 1)
        item = item_runs[0]
        self.assertEqual(item["run_kind"], "scan")
        self.assertEqual(item["task_name"], TASK_NAME)
        self.assertEqual(item["subject"], "Copied")
        self.assertEqual(item["parent_run_id"], "")
        self.assertEqual(item["scope"]["kind"], "paths")
        self.assertEqual([path.lstrip("/") for path in item["scope"]["paths"]], ["Media/Copied"])
        # 变更同步确实同步了网盘移动（STRM 交给独立任务生成），按“已完成”定稿，
        # 不再让「无变化」徽标和「已同步 1 条网盘变更」结论文案互相矛盾。
        self.assertEqual(detail["run"]["status"], "completed")
        self.assertIn("已同步 1 条网盘变更", detail["run"]["summary"])
        delegated = next(
            event for event in detail["events"] if event.get("operation") == "delegated"
        )
        self.assertEqual(delegated["status"], "completed")
        self.assertEqual(delegated["detail"]["independent_children"], 1)

        # 列表里接收夹与分发出的目录同步各占一行，互不为父子。
        page = monitor_runs.list_runs()
        top_ids = {run["id"] for run in page["runs"]}
        self.assertIn(inbox, top_ids)
        self.assertIn(item["id"], top_ids)
        self.assertEqual(monitor_runs.get_run_detail(inbox)["run"]["status"], "completed")

        monitor_runs.finish_run(
            item["id"], status="completed",
            summary="检查完成：新增或更新 1 个本地播放文件。", result={"generated": 1},
        )

        # 独立任务结束后不会回头改写变更同步的既定结论。
        self.assertEqual(monitor_runs.get_run_detail(change_run)["run"]["status"], "completed")
        self.assertEqual(monitor_runs.get_run_detail(inbox)["run"]["status"], "completed")


def _dir_item(name: str, modified: str) -> dict:
    return {
        "name": name,
        "is_dir": True,
        "modified": modified,
        "size": 0,
        "pick_code": "",
    }


def _file_item(name: str, modified: str, size: int = 2 * 1024 * 1024) -> dict:
    return {
        "name": name,
        "is_dir": False,
        "modified": modified,
        "size": size,
        "pick_code": "",
    }


class MonitorDirRescanTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "data.db")
        self.strm_root = os.path.join(self.tmpdir.name, "strm")
        os.makedirs(self.strm_root, exist_ok=True)

        self.original_db_path = db.DB_PATH
        self.original_db_ensured = db._DB_ENSURED
        db.DB_PATH = self.db_path
        db._DB_ENSURED = False
        db.ensure_db()

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        db._DB_ENSURED = self.original_db_ensured
        self.tmpdir.cleanup()

    def _task(self, *, sync_clean: bool = True, skip_by_dir_mtime: bool = True) -> dict:
        return {
            "name": TASK_NAME,
            "webhook_enabled": False,
            "scan_path": "/115/Library",
            "target_path": "Library",
            "skip_by_dir_mtime": skip_by_dir_mtime,
            "strm_write_mode": "incremental",
            "sync_clean": sync_clean,
            "incremental": not sync_clean,
            "retries": 1,
            "list_delay_ms": 0,
            "min_file_size_mb": 0,
            "delay_seconds": 0,
            "cron_minutes": 0,
        }

    def _cfg(self, task: dict) -> dict:
        return {
            "monitor_tasks": [task],
            "cookie_115": "cookie",
            "strm_proxy_base_url": "http://localhost:18080",
        }

    def _insert_monitor_dir(
        self,
        dir_rel_path: str,
        *,
        remote_modified: str,
        entry_modified: str = "",
        needs_rescan: int = 0,
        missing_confirmations: int = 0,
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO monitor_dirs(
                    task_name,
                    dir_rel_path,
                    remote_modified,
                    entry_modified,
                    needs_rescan,
                    missing_confirmations
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    TASK_NAME,
                    dir_rel_path,
                    remote_modified,
                    entry_modified,
                    needs_rescan,
                    missing_confirmations,
                ),
            )
            conn.commit()

    def _insert_monitor_file(
        self,
        local_rel_path: str,
        *,
        remote_rel_path: str,
        remote_modified: str,
        file_size: int = 2 * 1024 * 1024,
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO monitor_files(
                    task_name,
                    local_rel_path,
                    remote_rel_path,
                    remote_modified,
                    file_size
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (TASK_NAME, local_rel_path, remote_rel_path, remote_modified, file_size),
            )
            conn.commit()

    def _fetch_monitor_dir(self, dir_rel_path: str):
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT remote_modified, entry_modified, needs_rescan, missing_confirmations
                FROM monitor_dirs
                WHERE task_name = ? AND dir_rel_path = ?
                """,
                (TASK_NAME, dir_rel_path),
            ).fetchone()
        return row

    def _list_monitor_files(self):
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT local_rel_path
                FROM monitor_files
                WHERE task_name = ?
                ORDER BY local_rel_path
                """,
                (TASK_NAME,),
            ).fetchall()
        return [row[0] for row in rows]

    def _create_strm(self, local_rel_path: str, content: str = "cached") -> str:
        target = strm_files.managed_strm_file_path(local_rel_path, root=self.strm_root)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(content)
        return target

    def _run_monitor(
        self,
        path_results: dict,
        *,
        task: dict,
        trigger: str = "manual",
        payload: Optional[dict] = None,
        refresh_path: Optional[str] = None,
    ):
        call_log = []

        async def fake_list_remote_dir(_cfg, remote_path, _refresh, _task):
            call_log.append(remote_path)
            result = path_results[remote_path]
            if isinstance(result, Exception):
                raise result
            return result

        with ExitStack() as stack:
            stack.enter_context(patch.object(monitor, "DB_PATH", self.db_path))
            stack.enter_context(patch.object(monitor, "STRM_ROOT", self.strm_root))
            stack.enter_context(patch.object(monitor, "monitor_status", {"running": False, "current_task": "", "queued": []}))
            stack.enter_context(patch.object(monitor, "monitor_control", {"cancel": False}))
            stack.enter_context(patch.object(monitor, "monitor_last_run", {}))
            stack.enter_context(patch.object(monitor, "monitor_next_run", {}))
            stack.enter_context(patch.object(monitor, "get_config", return_value=self._cfg(task)))
            stack.enter_context(patch.object(monitor, "validate_monitor_runtime_config", return_value=None))
            stack.enter_context(patch.object(monitor, "get_user_extensions", return_value={"mkv"}))
            stack.enter_context(
                patch.object(
                    monitor,
                    "build_strm_play_url",
                    side_effect=lambda _cfg, remote_path, pick_code="": f"strm://{remote_path}",
                )
            )
            stack.enter_context(patch.object(monitor, "list_remote_dir", side_effect=fake_list_remote_dir))
            stack.enter_context(patch.object(monitor, "write_monitor_task_header", AsyncMock()))
            stack.enter_context(patch.object(monitor, "write_monitor_task_footer", AsyncMock()))
            stack.enter_context(patch.object(monitor, "write_monitor_task_summary", AsyncMock()))
            stack.enter_context(patch.object(monitor, "write_monitor_section", AsyncMock()))
            stack.enter_context(patch.object(monitor, "write_monitor_log", AsyncMock()))
            stack.enter_context(patch.object(monitor, "update_monitor_summary", Mock()))
            stack.enter_context(patch.object(monitor, "schedule_ui_state_push", Mock()))
            stack.enter_context(patch.object(monitor, "push_monitor_success_notification", AsyncMock(return_value={})))
            stack.enter_context(patch.object(monitor, "release_process_memory", Mock()))
            stack.enter_context(patch.object(monitor, "start_next_monitor_job", AsyncMock()))
            stack.enter_context(patch.object(monitor, "sleep_interruptible", AsyncMock()))
            stack.enter_context(patch.object(monitor, "check_monitor_cancelled", Mock()))
            stack.enter_context(
                patch.object(
                    monitor,
                    "managed_strm_file_path",
                    side_effect=lambda local_rel_path: strm_files.managed_strm_file_path(local_rel_path, root=self.strm_root),
                )
            )
            stack.enter_context(
                patch.object(
                    monitor,
                    "delete_managed_strm_file",
                    side_effect=lambda local_rel_path: strm_files.delete_managed_strm_file(local_rel_path, root=self.strm_root),
                )
            )
            if refresh_path is not None:
                stack.enter_context(patch.object(monitor, "extract_webhook_refresh_path", return_value=refresh_path))
            asyncio.run(monitor.run_monitor_task(TASK_NAME, trigger=trigger, payload=payload))

        return call_log

    def _create_manual_required_folder_event(self, task: dict, *, suffix: str) -> int:
        cfg = self._cfg(task)
        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="copy",
            entries=[
                {
                    "id": f"manual-{suffix}",
                    "path": f"Outside/{suffix}",
                    "new_path": f"Library/{suffix}/Imported",
                    "is_dir": True,
                }
            ],
            dedupe_key=f"manual-{suffix}",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(prepared, succeeded=True, enqueue=False)
        with patch.object(monitor_changes, "STRM_ROOT", self.strm_root):
            result = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))
        self.assertEqual(result["manual_required"], 1)
        return prepared["event_ids"][0]

    def _create_pending_folder_event(self, task: dict, *, suffix: str, old_path: str = "") -> int:
        cfg = self._cfg(task)
        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="copy",
            entries=[
                {
                    "id": f"pending-{suffix}",
                    "path": old_path or f"Outside/{suffix}",
                    "new_path": f"Library/{suffix}/Imported",
                    "is_dir": True,
                }
            ],
            dedupe_key=f"pending-{suffix}",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(prepared, succeeded=True, enqueue=False)
        return prepared["event_ids"][0]

    def test_scan_verification_completes_pending_event_with_outside_old_path(self):
        """接收夹分发这类“旧路径在监控范围外”的待处理事件，被扫描核实后直接收尾。"""
        task = self._task(sync_clean=True, skip_by_dir_mtime=True)
        event_id = self._create_pending_folder_event(task, suffix="SeriesA")

        self._run_monitor(
            {
                "/115/Library": (
                    "2026-08-09 10:00:00",
                    [_dir_item("SeriesA", "2026-08-09 10:00:00")],
                ),
                "/115/Library/SeriesA": ("2026-08-09 10:00:00", []),
            },
            task=task,
        )

        with sqlite3.connect(self.db_path) as conn:
            status = conn.execute(
                "SELECT status FROM monitor_change_events WHERE id = ?",
                (event_id,),
            ).fetchone()[0]
        self.assertEqual(status, "completed")

    def test_scan_verification_keeps_pending_event_with_inside_old_path(self):
        """旧路径也在监控范围内时，必须让变更同步先做删除/迁移，扫描不能替它收尾。"""
        task = self._task(sync_clean=True, skip_by_dir_mtime=True)
        event_id = self._create_pending_folder_event(
            task, suffix="SeriesA", old_path="Library/SeriesA/Old"
        )

        self._run_monitor(
            {
                "/115/Library": (
                    "2026-08-09 10:00:00",
                    [_dir_item("SeriesA", "2026-08-09 10:00:00")],
                ),
                "/115/Library/SeriesA": ("2026-08-09 10:00:00", []),
            },
            task=task,
        )

        with sqlite3.connect(self.db_path) as conn:
            status = conn.execute(
                "SELECT status FROM monitor_change_events WHERE id = ?",
                (event_id,),
            ).fetchone()[0]
        self.assertEqual(status, "pending")

    def test_monitor_dir_migration_adds_rescan_columns(self):
        legacy_db_path = os.path.join(self.tmpdir.name, "legacy.db")
        conn = sqlite3.connect(legacy_db_path)
        try:
            conn.execute(
                """
                CREATE TABLE monitor_dirs (
                    task_name TEXT NOT NULL,
                    dir_rel_path TEXT NOT NULL,
                    remote_modified TEXT,
                    PRIMARY KEY (task_name, dir_rel_path)
                )
                """
            )
            conn.execute(
                """
                INSERT INTO monitor_dirs(task_name, dir_rel_path, remote_modified)
                VALUES (?, ?, ?)
                """,
                (TASK_NAME, "Legacy", "2026-05-23 01:00:00"),
            )
            conn.commit()
        finally:
            conn.close()

        original_db_path = db.DB_PATH
        original_db_ensured = db._DB_ENSURED
        db.DB_PATH = legacy_db_path
        db._DB_ENSURED = False
        try:
            db.ensure_db()
            with sqlite3.connect(legacy_db_path) as conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(monitor_dirs)").fetchall()}
                legacy_entry_modified = (
                    conn.execute(
                        "SELECT entry_modified FROM monitor_dirs WHERE dir_rel_path = ?",
                        ("Legacy",),
                    ).fetchone()
                    if "entry_modified" in columns
                    else None
                )
        finally:
            db.DB_PATH = original_db_path
            db._DB_ENSURED = original_db_ensured

        self.assertIn("needs_rescan", columns)
        self.assertIn("missing_confirmations", columns)
        self.assertIn("entry_modified", columns)
        self.assertEqual(legacy_entry_modified, ("",))

    def test_marking_directory_dirty_preserves_first_level_entry_modified(self):
        self._insert_monitor_dir(
            "SeriesA",
            remote_modified="2026-07-31 10:00:00",
            entry_modified="2026-07-31 09:00:00",
        )

        with sqlite3.connect(self.db_path) as conn:
            monitor._mark_monitor_dir_dirty(conn.cursor(), TASK_NAME, "SeriesA")
            conn.commit()

        self.assertEqual(
            self._fetch_monitor_dir("SeriesA"),
            ("2026-07-31 10:00:00", "2026-07-31 09:00:00", 1, 0),
        )

    def test_cached_subtree_prefix_treats_sql_wildcards_as_literals(self):
        self._insert_monitor_file(
            "Library/Show_1/E01.mkv",
            remote_rel_path="Show_1/E01.mkv",
            remote_modified="2026-07-31 10:00:00",
        )
        self._insert_monitor_file(
            "Library/ShowA1/Stale.mkv",
            remote_rel_path="ShowA1/Stale.mkv",
            remote_modified="2026-07-31 10:00:00",
        )

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TEMP TABLE current_scan (
                    local_rel_path TEXT PRIMARY KEY,
                    remote_rel_path TEXT,
                    remote_modified TEXT,
                    file_size INTEGER
                )
                """
            )
            asyncio.run(
                monitor.mark_cached_dir_as_seen(
                    conn,
                    TASK_NAME,
                    "Library/Show_1",
                )
            )
            seen_paths = [
                row[0]
                for row in conn.execute(
                    "SELECT local_rel_path FROM current_scan ORDER BY local_rel_path"
                ).fetchall()
            ]

        self.assertEqual(seen_paths, ["Library/Show_1/E01.mkv"])

    def test_cached_subtree_prefix_escapes_percent_and_backslash(self):
        self._insert_monitor_file(
            "Library/Show%1/E01.mkv",
            remote_rel_path="Show%1/E01.mkv",
            remote_modified="2026-07-31 10:00:00",
        )
        self._insert_monitor_file(
            "Library/Show\\1/E01.mkv",
            remote_rel_path="Show\\1/E01.mkv",
            remote_modified="2026-07-31 10:00:00",
        )
        self._insert_monitor_file(
            "Library/ShowA1/Stale.mkv",
            remote_rel_path="ShowA1/Stale.mkv",
            remote_modified="2026-07-31 10:00:00",
        )

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TEMP TABLE current_scan (
                    local_rel_path TEXT PRIMARY KEY,
                    remote_rel_path TEXT,
                    remote_modified TEXT,
                    file_size INTEGER
                )
                """
            )
            asyncio.run(monitor.mark_cached_dir_as_seen(conn, TASK_NAME, "Library/Show%1"))
            asyncio.run(monitor.mark_cached_dir_as_seen(conn, TASK_NAME, "Library/Show\\1"))
            seen_paths = [
                row[0]
                for row in conn.execute(
                    "SELECT local_rel_path FROM current_scan ORDER BY local_rel_path"
                ).fetchall()
            ]

        self.assertEqual(
            seen_paths,
            ["Library/Show%1/E01.mkv", "Library/Show\\1/E01.mkv"],
        )

    def test_dirty_subtree_prefix_treats_sql_wildcards_as_literals(self):
        self._insert_monitor_dir(
            "ShowA1/Season01",
            remote_modified="2026-07-31 10:00:00",
            needs_rescan=1,
        )

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            self.assertFalse(
                monitor._monitor_dir_has_dirty_subtree(cursor, TASK_NAME, "Show_1")
            )
            self.assertEqual(
                monitor._list_dirty_direct_children(cursor, TASK_NAME, "Show_1"),
                [],
            )

    def test_delete_subtree_prefix_treats_sql_wildcards_as_literals(self):
        self._insert_monitor_dir(
            "Show_1/Season01",
            remote_modified="2026-07-31 10:00:00",
        )
        self._insert_monitor_dir(
            "ShowA1/Season01",
            remote_modified="2026-07-31 10:00:00",
        )

        with sqlite3.connect(self.db_path) as conn:
            monitor._delete_monitor_dir_subtree(conn.cursor(), TASK_NAME, "Show_1")
            conn.commit()

        self.assertIsNone(self._fetch_monitor_dir("Show_1/Season01"))
        self.assertIsNotNone(self._fetch_monitor_dir("ShowA1/Season01"))

    def test_first_level_change_is_scanned_when_parent_max_time_is_unchanged(self):
        task = self._task(sync_clean=True, skip_by_dir_mtime=True)
        self._insert_monitor_dir("", remote_modified="2026-07-31 12:00:00")
        self._insert_monitor_dir(
            "SeasonA",
            remote_modified="2026-07-31 12:00:00",
            entry_modified="2026-07-31 12:00:00",
        )
        self._insert_monitor_dir(
            "SeasonB",
            remote_modified="2026-07-31 09:00:00",
            entry_modified="2026-07-31 09:00:00",
        )

        call_log = self._run_monitor(
            {
                "/115/Library": (
                    "2026-07-31 12:00:00",
                    [
                        _dir_item("SeasonA", "2026-07-31 12:00:00"),
                        _dir_item("SeasonB", "2026-07-31 11:00:00"),
                    ],
                ),
                "/115/Library/SeasonB": (
                    "2026-07-31 11:00:00",
                    [_file_item("B01.mkv", "2026-07-31 11:00:00")],
                ),
            },
            task=task,
        )

        self.assertEqual(call_log, ["/115/Library", "/115/Library/SeasonB"])

    def test_manual_required_branch_bypasses_unchanged_entry_time_and_clears_after_scan(self):
        task = self._task(sync_clean=True, skip_by_dir_mtime=True)
        self._insert_monitor_dir(
            "SeriesA",
            remote_modified="2026-08-09 10:00:00",
            entry_modified="2026-08-09 10:00:00",
        )
        event_id = self._create_manual_required_folder_event(task, suffix="SeriesA")

        call_log = self._run_monitor(
            {
                "/115/Library": (
                    "2026-08-09 10:00:00",
                    [_dir_item("SeriesA", "2026-08-09 10:00:00")],
                ),
                "/115/Library/SeriesA": (
                    "2026-08-09 10:00:00",
                    [_dir_item("Imported", "2026-08-09 10:00:00")],
                ),
                "/115/Library/SeriesA/Imported": (
                    "2026-08-09 10:00:00",
                    [_file_item("Episode.mkv", "2026-08-09 10:00:00")],
                ),
            },
            task=task,
        )

        self.assertEqual(
            call_log,
            [
                "/115/Library",
                "/115/Library/SeriesA",
                "/115/Library/SeriesA/Imported",
            ],
        )
        self.assertTrue(
            os.path.exists(
                strm_files.managed_strm_file_path(
                    "Library/SeriesA/Imported/Episode.mkv",
                    root=self.strm_root,
                )
            )
        )
        with sqlite3.connect(self.db_path) as conn:
            status = conn.execute(
                "SELECT status FROM monitor_change_events WHERE id = ?",
                (event_id,),
            ).fetchone()[0]
        self.assertEqual(status, "completed")

    def test_manual_scan_only_clears_successfully_covered_manual_required_branch(self):
        task = self._task(sync_clean=True, skip_by_dir_mtime=True)
        for branch in ("SeriesA", "SeriesB"):
            self._insert_monitor_dir(
                branch,
                remote_modified="2026-08-09 10:00:00",
                entry_modified="2026-08-09 10:00:00",
            )
        series_a_event = self._create_manual_required_folder_event(task, suffix="SeriesA")
        series_b_event = self._create_manual_required_folder_event(task, suffix="SeriesB")

        call_log = self._run_monitor(
            {
                "/115/Library": (
                    "2026-08-09 10:00:00",
                    [
                        _dir_item("SeriesA", "2026-08-09 10:00:00"),
                        _dir_item("SeriesB", "2026-08-09 10:00:00"),
                    ],
                ),
                "/115/Library/SeriesA": (
                    "2026-08-09 10:00:00",
                    [_dir_item("Imported", "2026-08-09 10:00:00")],
                ),
                "/115/Library/SeriesA/Imported": ("2026-08-09 10:00:00", []),
                "/115/Library/SeriesB": RuntimeError("temporary 115 error"),
            },
            task=task,
        )

        self.assertEqual(
            call_log,
            [
                "/115/Library",
                "/115/Library/SeriesA",
                "/115/Library/SeriesB",
                "/115/Library/SeriesA/Imported",
            ],
        )
        with sqlite3.connect(self.db_path) as conn:
            statuses = dict(
                conn.execute(
                    "SELECT id, status FROM monitor_change_events WHERE id IN (?, ?)",
                    (series_a_event, series_b_event),
                ).fetchall()
            )
        self.assertEqual(statuses[series_a_event], "completed")
        self.assertEqual(statuses[series_b_event], "manual_required")

    def test_changed_first_level_branch_does_not_prune_deeper_directories(self):
        task = self._task(sync_clean=True, skip_by_dir_mtime=True)
        self._insert_monitor_dir(
            "SeriesA",
            remote_modified="2026-07-30 10:00:00",
            entry_modified="2026-07-30 10:00:00",
        )
        self._insert_monitor_dir(
            "SeriesA/Season01",
            remote_modified="2026-07-31 10:00:00",
        )

        call_log = self._run_monitor(
            {
                "/115/Library": (
                    "2026-07-31 11:00:00",
                    [_dir_item("SeriesA", "2026-07-31 11:00:00")],
                ),
                "/115/Library/SeriesA": (
                    "2026-07-31 10:00:00",
                    [_dir_item("Season01", "2026-07-31 10:00:00")],
                ),
                "/115/Library/SeriesA/Season01": (
                    "2026-07-31 10:00:00",
                    [_file_item("E01.mkv", "2026-07-31 10:00:00")],
                ),
            },
            task=task,
        )

        self.assertEqual(
            call_log,
            [
                "/115/Library",
                "/115/Library/SeriesA",
                "/115/Library/SeriesA/Season01",
            ],
        )

    def test_legacy_directory_time_without_entry_baseline_forces_one_scan(self):
        task = self._task(sync_clean=True, skip_by_dir_mtime=True)
        self._insert_monitor_dir(
            "SeriesA",
            remote_modified="2026-07-31 10:00:00",
        )

        call_log = self._run_monitor(
            {
                "/115/Library": (
                    "2026-07-31 10:00:00",
                    [_dir_item("SeriesA", "2026-07-31 10:00:00")],
                ),
                "/115/Library/SeriesA": (
                    "2026-07-31 10:00:00",
                    [_file_item("E01.mkv", "2026-07-31 10:00:00")],
                ),
            },
            task=task,
        )

        self.assertEqual(call_log, ["/115/Library", "/115/Library/SeriesA"])
        self.assertEqual(
            self._fetch_monitor_dir("SeriesA"),
            ("2026-07-31 10:00:00", "2026-07-31 10:00:00", 0, 0),
        )

    def test_first_level_entry_time_rollback_forces_scan(self):
        task = self._task(sync_clean=True, skip_by_dir_mtime=True)
        self._insert_monitor_dir(
            "SeriesA",
            remote_modified="2026-07-31 12:00:00",
            entry_modified="2026-07-31 12:00:00",
        )

        call_log = self._run_monitor(
            {
                "/115/Library": (
                    "2026-07-31 11:00:00",
                    [_dir_item("SeriesA", "2026-07-31 11:00:00")],
                ),
                "/115/Library/SeriesA": (
                    "2026-07-31 11:00:00",
                    [_file_item("E01.mkv", "2026-07-31 11:00:00")],
                ),
            },
            task=task,
        )

        self.assertEqual(call_log, ["/115/Library", "/115/Library/SeriesA"])

    def test_first_level_directory_without_modified_time_is_scanned(self):
        task = self._task(sync_clean=True, skip_by_dir_mtime=True)
        self._insert_monitor_dir(
            "SeriesA",
            remote_modified="2026-07-31 10:00:00",
            entry_modified="2026-07-31 10:00:00",
        )

        call_log = self._run_monitor(
            {
                "/115/Library": ("", [_dir_item("SeriesA", "")]),
                "/115/Library/SeriesA": (
                    "2026-07-31 10:00:00",
                    [_file_item("E01.mkv", "2026-07-31 10:00:00")],
                ),
            },
            task=task,
        )

        self.assertEqual(call_log, ["/115/Library", "/115/Library/SeriesA"])

    def test_first_level_video_is_processed_when_parent_max_time_is_unchanged(self):
        task = self._task(sync_clean=True, skip_by_dir_mtime=True)
        self._insert_monitor_dir("", remote_modified="2026-07-31 12:00:00")

        call_log = self._run_monitor(
            {
                "/115/Library": (
                    "2026-07-31 12:00:00",
                    [_file_item("Movie.mkv", "2026-07-31 11:00:00")],
                ),
            },
            task=task,
        )

        self.assertEqual(call_log, ["/115/Library"])
        self.assertEqual(self._list_monitor_files(), ["Library/Movie.mkv"])
        self.assertTrue(
            os.path.exists(
                strm_files.managed_strm_file_path("Library/Movie.mkv", root=self.strm_root)
            )
        )

    def test_disabling_mtime_skip_scans_unchanged_branch_completely(self):
        task = self._task(sync_clean=True, skip_by_dir_mtime=False)
        self._insert_monitor_dir(
            "SeriesA",
            remote_modified="2026-07-31 10:00:00",
            entry_modified="2026-07-31 10:00:00",
        )

        call_log = self._run_monitor(
            {
                "/115/Library": (
                    "2026-07-31 10:00:00",
                    [_dir_item("SeriesA", "2026-07-31 10:00:00")],
                ),
                "/115/Library/SeriesA": (
                    "2026-07-31 10:00:00",
                    [_dir_item("Season01", "2026-07-31 10:00:00")],
                ),
                "/115/Library/SeriesA/Season01": (
                    "2026-07-31 10:00:00",
                    [_file_item("E01.mkv", "2026-07-31 10:00:00")],
                ),
            },
            task=task,
        )

        self.assertEqual(
            call_log,
            [
                "/115/Library",
                "/115/Library/SeriesA",
                "/115/Library/SeriesA/Season01",
            ],
        )

    def test_resource_refresh_ignores_equal_first_level_baseline(self):
        task = self._task(sync_clean=False, skip_by_dir_mtime=True)
        self._insert_monitor_dir(
            "SeriesA",
            remote_modified="2026-07-31 10:00:00",
            entry_modified="2026-07-31 10:00:00",
        )

        call_log = self._run_monitor(
            {
                "/115/Library": (
                    "2026-07-31 10:00:00",
                    [_dir_item("SeriesA", "2026-07-31 10:00:00")],
                ),
                "/115/Library/SeriesA": (
                    "2026-07-31 10:00:00",
                    [_file_item("E01.mkv", "2026-07-31 10:00:00")],
                ),
            },
            task=task,
            trigger="resource",
            payload={"savepath": "Library"},
            refresh_path="/115/Library",
        )

        self.assertEqual(call_log, ["/115/Library", "/115/Library/SeriesA"])

    def test_dirty_root_forces_all_first_level_branches_to_rescan(self):
        task = self._task(sync_clean=False, skip_by_dir_mtime=True)
        self._insert_monitor_dir(
            "",
            remote_modified="2026-07-31 10:00:00",
            needs_rescan=1,
        )
        self._insert_monitor_dir(
            "SeriesA",
            remote_modified="2026-07-31 10:00:00",
            entry_modified="2026-07-31 10:00:00",
        )

        call_log = self._run_monitor(
            {
                "/115/Library": (
                    "2026-07-31 10:00:00",
                    [_dir_item("SeriesA", "2026-07-31 10:00:00")],
                ),
                "/115/Library/SeriesA": (
                    "2026-07-31 10:00:00",
                    [_file_item("E01.mkv", "2026-07-31 10:00:00")],
                ),
            },
            task=task,
        )

        self.assertEqual(call_log, ["/115/Library", "/115/Library/SeriesA"])

    def test_tracked_first_level_dir_is_released_after_two_missing_confirmations(self):
        task = self._task(sync_clean=False, skip_by_dir_mtime=True)
        self._insert_monitor_dir(
            "SeriesGone",
            remote_modified="2026-07-31 10:00:00",
            entry_modified="2026-07-31 10:00:00",
        )
        root_listing = {"/115/Library": ("", [])}

        self._run_monitor(root_listing, task=task)

        self.assertEqual(
            self._fetch_monitor_dir("SeriesGone"),
            ("2026-07-31 10:00:00", "2026-07-31 10:00:00", 1, 1),
        )

        self._run_monitor(root_listing, task=task)

        self.assertIsNone(self._fetch_monitor_dir("SeriesGone"))

    def test_queue_merge_keeps_resource_trigger_when_manual_run_joins(self):
        with ExitStack() as stack:
            queued = []
            stack.enter_context(patch.object(monitor, "monitor_queue", queued))
            stack.enter_context(
                patch.object(
                    monitor,
                    "monitor_status",
                    {"running": True, "current_task": "Other", "queued": []},
                )
            )
            stack.enter_context(patch.object(monitor, "schedule_ui_state_push", Mock()))

            monitor.queue_monitor_job(
                TASK_NAME,
                "resource",
                {"savepath": "Library", "sharetitle": "SeriesA"},
            )
            monitor.queue_monitor_job(TASK_NAME, "manual")

        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0]["trigger"], "resource")
        self.assertEqual(queued[0]["payload"], {})

    def test_queue_merge_keeps_webhook_trigger_when_cron_run_joins(self):
        with ExitStack() as stack:
            queued = []
            stack.enter_context(patch.object(monitor, "monitor_queue", queued))
            stack.enter_context(
                patch.object(
                    monitor,
                    "monitor_status",
                    {"running": True, "current_task": "Other", "queued": []},
                )
            )
            stack.enter_context(patch.object(monitor, "schedule_ui_state_push", Mock()))

            monitor.queue_monitor_job(
                TASK_NAME,
                "webhook",
                {"savepath": "Library", "sharetitle": "SeriesA"},
            )
            monitor.queue_monitor_job(TASK_NAME, "cron")

        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0]["trigger"], "webhook")
        self.assertEqual(queued[0]["payload"], {})

    def test_manual_run_only_deep_scans_changed_or_dirty_children_and_preserves_skipped_cache(self):
        task = self._task(sync_clean=True, skip_by_dir_mtime=True)
        self._insert_monitor_dir("", remote_modified="2026-05-23 01:00:00")
        self._insert_monitor_dir(
            "SeasonA",
            remote_modified="2026-05-23 01:00:00",
            entry_modified="2026-05-23 01:00:00",
        )
        self._insert_monitor_dir(
            "SeasonB",
            remote_modified="2026-05-22 01:00:00",
            entry_modified="2026-05-22 01:00:00",
        )
        self._insert_monitor_dir(
            "SeasonC",
            remote_modified="2026-05-23 01:00:00",
            entry_modified="2026-05-23 01:00:00",
            needs_rescan=1,
        )
        self._insert_monitor_file(
            "Library/SeasonA/A01.mkv",
            remote_rel_path="SeasonA/A01.mkv",
            remote_modified="2026-05-23 01:00:00",
        )
        season_a_strm = self._create_strm("Library/SeasonA/A01.mkv", content="cached-a")

        call_log = self._run_monitor(
            {
                "/115/Library": (
                    "2026-05-23 10:00:00",
                    [
                        _dir_item("SeasonA", "2026-05-23 01:00:00"),
                        _dir_item("SeasonB", "2026-05-23 10:00:00"),
                        _dir_item("SeasonC", "2026-05-23 01:00:00"),
                    ],
                ),
                "/115/Library/SeasonB": (
                    "2026-05-23 10:00:00",
                    [_file_item("B01.mkv", "2026-05-23 10:00:00")],
                ),
                "/115/Library/SeasonC": (
                    "2026-05-23 01:00:00",
                    [_file_item("C01.mkv", "2026-05-23 01:00:00")],
                ),
            },
            task=task,
        )

        self.assertEqual(
            call_log,
            [
                "/115/Library",
                "/115/Library/SeasonB",
                "/115/Library/SeasonC",
            ],
        )
        self.assertTrue(os.path.exists(season_a_strm))
        self.assertEqual(
            self._list_monitor_files(),
            [
                "Library/SeasonA/A01.mkv",
                "Library/SeasonB/B01.mkv",
                "Library/SeasonC/C01.mkv",
            ],
        )
        self.assertEqual(
            self._fetch_monitor_dir("SeasonC"),
            ("2026-05-23 01:00:00", "2026-05-23 01:00:00", 0, 0),
        )

    def test_targeted_missing_dir_is_marked_dirty_and_later_success_clears_it(self):
        task = self._task(sync_clean=False, skip_by_dir_mtime=True)
        target_path = "/115/Library/SeasonD"

        self._run_monitor(
            {
                "/115/Library": (
                    "2026-05-23 10:00:00",
                    [_dir_item("SeasonE", "2026-05-23 10:00:00")],
                ),
                target_path: RuntimeError("not ready"),
            },
            task=task,
            trigger="resource",
            payload={"savepath": "Library", "sharetitle": "SeasonD"},
            refresh_path=target_path,
        )

        self.assertEqual(self._fetch_monitor_dir("SeasonD"), ("", "", 1, 1))

        call_log = self._run_monitor(
            {
                "/115/Library": (
                    "2026-05-23 10:30:00",
                    [_dir_item("SeasonD", "2026-05-23 10:30:00")],
                ),
                target_path: (
                    "2026-05-23 10:30:00",
                    [_file_item("D01.mkv", "2026-05-23 10:30:00")],
                ),
            },
            task=task,
        )

        self.assertEqual(call_log, ["/115/Library", target_path])
        self.assertEqual(
            self._fetch_monitor_dir("SeasonD"),
            ("2026-05-23 10:30:00", "2026-05-23 10:30:00", 0, 0),
        )

    def test_missing_dirty_dir_is_cleaned_and_released_after_two_confirmations(self):
        task = self._task(sync_clean=True, skip_by_dir_mtime=True)
        self._insert_monitor_dir("", remote_modified="2026-05-23 01:00:00")
        self._insert_monitor_dir(
            "SeasonGone",
            remote_modified="2026-05-23 01:00:00",
            entry_modified="2026-05-23 01:00:00",
            needs_rescan=1,
        )
        self._insert_monitor_file(
            "Library/SeasonGone/Gone01.mkv",
            remote_rel_path="SeasonGone/Gone01.mkv",
            remote_modified="2026-05-23 01:00:00",
        )
        gone_strm = self._create_strm("Library/SeasonGone/Gone01.mkv", content="gone")

        root_listing = {
            "/115/Library": (
                "2026-05-23 11:00:00",
                [_dir_item("SeasonKeep", "2026-05-23 11:00:00")],
            ),
            "/115/Library/SeasonKeep": (
                "2026-05-23 11:00:00",
                [_file_item("Keep01.mkv", "2026-05-23 11:00:00")],
            ),
        }

        self._run_monitor(root_listing, task=task)

        self.assertFalse(os.path.exists(gone_strm))
        self.assertNotIn("Library/SeasonGone/Gone01.mkv", self._list_monitor_files())
        self.assertEqual(
            self._fetch_monitor_dir("SeasonGone"),
            ("2026-05-23 01:00:00", "2026-05-23 01:00:00", 1, 1),
        )

        self._run_monitor(root_listing, task=task)

        self.assertIsNone(self._fetch_monitor_dir("SeasonGone"))

    def test_abrupt_exit_keeps_changed_first_level_dirty_until_index_commit(self):
        task = self._task(sync_clean=True, skip_by_dir_mtime=True)
        self._insert_monitor_dir(
            "SeriesA",
            remote_modified="2026-07-30 10:00:00",
            entry_modified="2026-07-30 10:00:00",
            needs_rescan=0,
        )
        self._insert_monitor_file(
            "Library/SeriesA/Old.mkv",
            remote_rel_path="SeriesA/Old.mkv",
            remote_modified="2026-07-30 10:00:00",
        )

        original_progress = monitor._record_monitor_dir_scan_progress

        def fail_after_progress(
            cursor,
            task_name,
            dir_rel_path,
            remote_modified,
        ):
            original_progress(
                cursor,
                task_name,
                dir_rel_path,
                remote_modified,
            )
            if dir_rel_path == "SeriesA":
                raise SystemExit("simulated process exit")

        with patch.object(monitor, "_record_monitor_dir_scan_progress", side_effect=fail_after_progress):
            with self.assertRaises(SystemExit):
                self._run_monitor(
                    {
                        "/115/Library": (
                            "2026-07-31 11:00:00",
                            [_dir_item("SeriesA", "2026-07-31 11:00:00")],
                        ),
                        "/115/Library/SeriesA": (
                            "2026-07-31 11:00:00",
                            [_file_item("New.mkv", "2026-07-31 11:00:00")],
                        ),
                    },
                    task=task,
                )

        state = self._fetch_monitor_dir("SeriesA")
        self.assertEqual(state[1:], ("2026-07-30 10:00:00", 1, 0))
        self.assertEqual(self._list_monitor_files(), ["Library/SeriesA/Old.mkv"])

        call_log = self._run_monitor(
            {
                "/115/Library": (
                    "2026-07-31 11:00:00",
                    [_dir_item("SeriesA", "2026-07-31 11:00:00")],
                ),
                "/115/Library/SeriesA": (
                    "2026-07-31 11:00:00",
                    [_file_item("New.mkv", "2026-07-31 11:00:00")],
                ),
            },
            task=task,
        )
        self.assertEqual(call_log, ["/115/Library", "/115/Library/SeriesA"])
        self.assertEqual(self._list_monitor_files(), ["Library/SeriesA/New.mkv"])


class ChangeStrmDetailTest(unittest.TestCase):
    """变更同步的本地文件明细：逐条记录写入/删除的 STRM 路径，超限用汇总兜底。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "data.db")
        self.original_db_path = db.DB_PATH
        self.original_db_ensured = db._DB_ENSURED
        db.DB_PATH = self.db_path
        db._DB_ENSURED = False
        db.ensure_db()

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        db._DB_ENSURED = self.original_db_ensured
        self.tmpdir.cleanup()

    def _create_run(self) -> str:
        from app.services import monitor_runs

        run_id = monitor_runs.create_run(run_kind="change", task_name="电视剧", source="change")
        monitor_runs.start_run(run_id)
        return run_id

    def test_folder_change_records_per_file_strm_events(self):
        from app.services import monitor, monitor_runs

        run_id = self._create_run()
        monitor._record_change_strm_events(
            run_id,
            {
                "kind": "folder",
                "old_path": "电视剧/示例剧",
                "new_path": "电视剧/示例剧 (2023)",
                "generated": 2,
                "deleted": 1,
                "generated_files": [
                    {
                        "local": "电视剧/示例剧 (2023)/S01E01.mkv.strm",
                        "remote": "电视剧/示例剧 (2023)/S01E01.mkv",
                        "name": "S01E01.mkv",
                    },
                    {
                        "local": "电视剧/示例剧 (2023)/S01E02.mkv.strm",
                        "remote": "电视剧/示例剧 (2023)/S01E02.mkv",
                        "name": "S01E02.mkv",
                    },
                ],
                "deleted_files": [
                    {
                        "local": "电视剧/示例剧/S01E01.mkv.strm",
                        "remote": "电视剧/示例剧/S01E01.mkv",
                        "name": "S01E01.mkv",
                    }
                ],
            },
        )

        strm_events = [e for e in monitor_runs.get_run_detail(run_id)["events"] if e["category"] == "strm"]
        self.assertEqual(len(strm_events), 3)
        self.assertEqual(len([e for e in strm_events if e["operation"] == "generate"]), 2)
        self.assertEqual(len([e for e in strm_events if e["operation"] == "delete"]), 1)
        for event in strm_events:
            self.assertTrue(event["title"].endswith(".strm"))
            self.assertTrue(event["detail"]["strm_path"].endswith(event["title"]))
            # 每条明细同时给出对应网盘路径（不含 .strm 后缀）与本地 STRM 路径。
            self.assertTrue(event["detail"]["remote_path"].endswith(event["title"][:-5]))
            self.assertNotIn(".strm", event["detail"]["remote_path"])
            self.assertEqual(event["detail"]["scope"], "电视剧/示例剧 (2023)")

    def test_folder_change_without_paths_keeps_aggregate_row(self):
        from app.services import monitor, monitor_runs

        run_id = self._create_run()
        monitor._record_change_strm_events(
            run_id,
            {"kind": "folder", "new_path": "电影/示例", "generated": 3, "deleted": 2},
        )

        strm_events = [e for e in monitor_runs.get_run_detail(run_id)["events"] if e["category"] == "strm"]
        self.assertEqual(len(strm_events), 1)
        self.assertEqual(strm_events[0]["operation"], "sync")
        self.assertEqual(strm_events[0]["detail"]["generated"], 3)
        self.assertEqual(strm_events[0]["detail"]["deleted"], 2)

    def test_folder_change_over_limit_adds_summary_row(self):
        from app.services import monitor, monitor_runs

        run_id = self._create_run()
        with patch.object(monitor, "CHANGE_STRM_DETAIL_LIMIT", 1):
            monitor._record_change_strm_events(
                run_id,
                {
                    "kind": "folder",
                    "new_path": "电影/示例",
                    "generated": 2,
                    "generated_files": [
                        {"local": "电影/示例/A.strm", "remote": "电影/示例/A.mkv", "name": "A"},
                        {"local": "电影/示例/B.strm", "remote": "电影/示例/B.mkv", "name": "B"},
                    ],
                },
            )

        strm_events = [e for e in monitor_runs.get_run_detail(run_id)["events"] if e["category"] == "strm"]
        self.assertEqual(len(strm_events), 2)
        self.assertEqual(len([e for e in strm_events if e["operation"] == "generate"]), 1)
        summary = next(e for e in strm_events if e["operation"] == "sync")
        self.assertIn("另有 1 个本地播放文件未逐条列出", summary["title"])
        self.assertEqual(summary["detail"]["generated"], 1)

    def test_folder_change_detail_gets_strm_effect_paths(self):
        from app.services import monitor_changes

        detail = {"kind": "folder", "old_path": "电视剧/示例剧", "new_path": "电视剧/示例剧 (2023)"}
        monitor_changes._attach_strm_effect_paths(
            detail,
            [{"local": "电视剧/示例剧/S01E01.mkv", "remote": "电视剧/示例剧/S01E01.mkv"}],
            [{"local": "电视剧/示例剧 (2023)/S01E01.mkv", "remote": "电视剧/示例剧 (2023)/S01E01.mkv"}],
        )
        self.assertEqual(
            detail["deleted_files"],
            [{
                "local": "电视剧/示例剧/S01E01.mkv.strm",
                "remote": "电视剧/示例剧/S01E01.mkv",
                "name": "S01E01.mkv",
            }],
        )
        self.assertEqual(
            detail["generated_files"],
            [{
                "local": "电视剧/示例剧 (2023)/S01E01.mkv.strm",
                "remote": "电视剧/示例剧 (2023)/S01E01.mkv",
                "name": "S01E01.mkv",
            }],
        )
        # 文件级明细本来就有逐条 changes，不重复挂路径列表。
        file_detail = {"kind": "file", "changes": []}
        monitor_changes._attach_strm_effect_paths(file_detail, [{"local": "a"}], [{"local": "b"}])
        self.assertNotIn("deleted_files", file_detail)

    def test_file_change_detail_carries_cloud_and_local_paths(self):
        """文件级变更明细要能让「本地文件」页签同时显示网盘与本地路径。"""
        from app.services import monitor

        detail = monitor._monitor_run_change_detail(
            {
                "kind": "file",
                "changes": [
                    {
                        "action": "generate",
                        "path": "115自存电视剧/交锋 (2026) [tmdbid-294486]/Season 01/交锋 (2026) - S01E36.mkv.strm",
                        "remote_path": "115自存电视剧/交锋 (2026) [tmdbid-294486]/Season 01/交锋 (2026) - S01E36.mkv",
                    }
                ],
            }
        )

        self.assertEqual(
            detail["strm_path"],
            "115自存电视剧/交锋 (2026) [tmdbid-294486]/Season 01/交锋 (2026) - S01E36.mkv.strm",
        )
        self.assertEqual(
            detail["remote_path"],
            "115自存电视剧/交锋 (2026) [tmdbid-294486]/Season 01/交锋 (2026) - S01E36.mkv",
        )


class InboxDispatchLifecycleTest(unittest.TestCase):
    """接收夹分发一个条目的真实链路：子任务扫描与变更同步必须一起收尾。

    回归用户实测问题：分发「魔方小姐」后，子任务（目录扫描）已完成、本地已有 STRM，
    但变更同步仍停在「部分完成 / 等待系统补扫」。
    """

    TARGET_NAME = "魔方小姐 (2026) [tmdbid-1257942]"
    TARGET_FILE = "魔方小姐.Dog.Day.Evening.2026.2160p.mkv"

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "data.db")
        self.strm_root = os.path.join(self.tmpdir.name, "strm")
        self.original_db_path = db.DB_PATH
        self.original_db_ensured = db._DB_ENSURED
        db.DB_PATH = self.db_path
        db._DB_ENSURED = False
        db.ensure_db()

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        db._DB_ENSURED = self.original_db_ensured
        self.tmpdir.cleanup()

    def _task(self) -> dict:
        return {
            "name": TASK_NAME,
            "webhook_enabled": False,
            "scan_path": "/115/Library",
            "target_path": "Library",
            "skip_by_dir_mtime": True,
            "strm_write_mode": "incremental",
            "sync_clean": True,
            "incremental": False,
            "retries": 1,
            "list_delay_ms": 0,
            "min_file_size_mb": 0,
            "delay_seconds": 0,
            "cron_minutes": 0,
        }

    def _cfg(self) -> dict:
        return {
            "monitor_tasks": [self._task()],
            "mount_points": [{"provider": "115", "prefix": "/115"}],
            "extensions": "mkv",
            "cookie_115": "cookie",
            "strm_proxy_base_url": "http://localhost:18080",
        }

    def _listing(self) -> dict:
        target_remote = f"/115/Library/{self.TARGET_NAME}"
        return {
            "/115/Library": (
                "2026-09-26 15:41:00",
                [_dir_item(self.TARGET_NAME, "2026-09-26 15:41:00")],
            ),
            target_remote: (
                "2026-09-26 15:41:00",
                [_file_item(self.TARGET_FILE, "2026-09-26 15:41:00")],
            ),
        }

    def _create_dispatch_event(self, *, monitor_run_id: str) -> int:
        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="move",
            entries=[
                {
                    "id": "movie-1257942",
                    "name": self.TARGET_NAME,
                    "path": f"最近接收/{self.TARGET_NAME}",
                    "new_path": f"Library/{self.TARGET_NAME}",
                    "is_dir": True,
                }
            ],
            dedupe_key="inbox-dispatch-movie",
            source_action="scraper-job:7:quick-import",
            monitor_run_id=monitor_run_id,
            cfg=self._cfg(),
        )
        monitor_changes.confirm_monitor_change_events(prepared, succeeded=True, enqueue=False)
        return prepared["event_ids"][0]

    def _event_status(self, event_id: int) -> str:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT status FROM monitor_change_events WHERE id = ?",
                (event_id,),
            ).fetchone()
        return str(row[0] if row else "")

    def _run_child_scan(self, *, run_id: str) -> None:
        path_results = self._listing()

        async def fake_list_remote_dir(_cfg, remote_path, _refresh, _task):
            result = path_results[remote_path]
            if isinstance(result, Exception):
                raise result
            return result

        with ExitStack() as stack:
            stack.enter_context(patch.object(monitor, "DB_PATH", self.db_path))
            stack.enter_context(patch.object(monitor, "STRM_ROOT", self.strm_root))
            stack.enter_context(patch.object(monitor, "monitor_status", {"running": False, "current_task": "", "queued": []}))
            stack.enter_context(patch.object(monitor, "monitor_control", {"cancel": False}))
            stack.enter_context(patch.object(monitor, "monitor_last_run", {}))
            stack.enter_context(patch.object(monitor, "monitor_next_run", {}))
            stack.enter_context(patch.object(monitor, "get_config", return_value=self._cfg()))
            stack.enter_context(patch.object(monitor, "validate_monitor_runtime_config", return_value=None))
            stack.enter_context(patch.object(monitor, "get_user_extensions", return_value={"mkv"}))
            stack.enter_context(
                patch.object(
                    monitor,
                    "build_strm_play_url",
                    side_effect=lambda _cfg, remote_path, pick_code="": f"strm://{remote_path}",
                )
            )
            stack.enter_context(patch.object(monitor, "list_remote_dir", side_effect=fake_list_remote_dir))
            stack.enter_context(patch.object(monitor, "write_monitor_task_header", AsyncMock()))
            stack.enter_context(patch.object(monitor, "write_monitor_task_footer", AsyncMock()))
            stack.enter_context(patch.object(monitor, "write_monitor_task_summary", AsyncMock()))
            stack.enter_context(patch.object(monitor, "write_monitor_section", AsyncMock()))
            stack.enter_context(patch.object(monitor, "write_monitor_log", AsyncMock()))
            stack.enter_context(patch.object(monitor, "update_monitor_summary", Mock()))
            stack.enter_context(patch.object(monitor, "schedule_ui_state_push", Mock()))
            stack.enter_context(patch.object(monitor, "push_monitor_success_notification", AsyncMock(return_value={})))
            stack.enter_context(patch.object(monitor, "release_process_memory", Mock()))
            stack.enter_context(patch.object(monitor, "start_next_monitor_job", AsyncMock()))
            stack.enter_context(patch.object(monitor, "sleep_interruptible", AsyncMock()))
            stack.enter_context(patch.object(monitor, "check_monitor_cancelled", Mock()))
            stack.enter_context(
                patch.object(
                    monitor,
                    "managed_strm_file_path",
                    side_effect=lambda local_rel_path: strm_files.managed_strm_file_path(local_rel_path, root=self.strm_root),
                )
            )
            stack.enter_context(
                patch.object(
                    monitor,
                    "delete_managed_strm_file",
                    side_effect=lambda local_rel_path: strm_files.delete_managed_strm_file(local_rel_path, root=self.strm_root),
                )
            )
            asyncio.run(
                monitor.run_monitor_task(
                    TASK_NAME,
                    trigger="manual",
                    payload={"savepaths": [f"Library/{self.TARGET_NAME}"]},
                    run_id=run_id,
                    run_source="inbox_dispatch",
                )
            )

    def _run_change_task(self, *, run_id: str) -> None:
        with ExitStack() as stack:
            stack.enter_context(patch.object(monitor, "DB_PATH", self.db_path))
            stack.enter_context(patch.object(monitor, "STRM_ROOT", self.strm_root))
            stack.enter_context(patch.object(monitor, "_claim_monitor_job", return_value=True))
            stack.enter_context(patch.object(monitor, "get_config", return_value=self._cfg()))
            stack.enter_context(patch.object(monitor, "_finish_monitor_job", new=AsyncMock()))
            stack.enter_context(patch.object(monitor, "write_monitor_task_header", new=AsyncMock()))
            stack.enter_context(patch.object(monitor, "write_monitor_task_footer", new=AsyncMock()))
            stack.enter_context(patch.object(monitor, "write_monitor_section", new=AsyncMock()))
            stack.enter_context(patch.object(monitor, "write_monitor_log", new=AsyncMock()))
            stack.enter_context(patch.object(monitor, "_write_monitor_change_details", new=AsyncMock()))
            stack.enter_context(patch.object(monitor, "schedule_ui_state_push", lambda *args, **kwargs: None))
            stack.enter_context(patch.object(monitor, "submit_background", lambda *args, **kwargs: None))
            stack.enter_context(patch.object(monitor_changes, "STRM_ROOT", self.strm_root))
            asyncio.run(
                monitor.run_monitor_change_task(
                    TASK_NAME,
                    "change",
                    {"mode": "change"},
                    run_id=run_id,
                )
            )

    def test_precise_sync_does_not_requeue_dispatch_scan(self):
        """文件级移动已经精准生成过 STRM 时，不再补排一次目录扫描。"""
        from app.services import monitor_changes, monitor_runs

        inbox_run = monitor_runs.create_run(run_kind="inbox", task_name="最近接收", source="manual")
        monitor_runs.start_run(inbox_run)
        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="move",
            entries=[
                {
                    "id": "file-1257942",
                    "name": self.TARGET_FILE,
                    "path": f"最近接收/{self.TARGET_NAME}/Season 01/{self.TARGET_FILE}",
                    "new_path": f"Library/{self.TARGET_NAME}/Season 01/{self.TARGET_FILE}",
                    "is_dir": False,
                }
            ],
            dedupe_key="inbox-dispatch-file",
            source_action="scraper-job:8:quick-import",
            monitor_run_id=inbox_run,
            cfg=self._cfg(),
        )
        monitor_changes.confirm_monitor_change_events(prepared, succeeded=True, enqueue=False)

        with ExitStack() as stack:
            stack.enter_context(patch.object(monitor_changes, "STRM_ROOT", self.strm_root))
            stack.enter_context(patch.object(monitor_changes, "get_config", return_value=self._cfg()))
            stack.enter_context(patch.object(monitor_changes, "_enqueue_task_names", lambda *args, **kwargs: None))
            result = asyncio.run(
                monitor_changes.process_monitor_change_events(
                    TASK_NAME,
                    cfg=self._cfg(),
                    event_ids=prepared["event_ids"],
                    monitor_run_id=inbox_run,
                )
            )

        self.assertGreaterEqual(int(result.get("generated", 0) or 0), 1)
        # 已经精准同步过就不该再排目录扫描，否则会多出一条“无变化”记录。
        self.assertEqual(result.get("dispatched_item_paths"), [])

    def test_child_scan_first_completes_pending_dispatch_event(self):
        from app.services import monitor_runs

        cfg = self._cfg()
        inbox_run = monitor_runs.create_run(run_kind="inbox", task_name="最近接收", source="manual")
        monitor_runs.start_run(inbox_run)
        event_id = self._create_dispatch_event(monitor_run_id=inbox_run)
        self.assertEqual(self._event_status(event_id), "pending")
        child_run = monitor_runs.create_run(
            run_kind="scan",
            task_name=TASK_NAME,
            source="inbox_dispatch",
            scope={"kind": "paths", "paths": [f"/Library/{self.TARGET_NAME}"]},
        )

        self._run_child_scan(run_id=child_run)

        self.assertEqual(self._event_status(event_id), "completed")
        self.assertTrue(
            os.path.exists(
                strm_files.managed_strm_file_path(
                    f"Library/{self.TARGET_NAME}/{self.TARGET_FILE}",
                    root=self.strm_root,
                )
            )
        )

    def test_change_run_delegates_to_independent_scan_without_waiting(self):
        """分发扫描是独立记录：变更同步只补排/说明，不挂下游、不等待，也不改写接收夹记录。"""
        from app.services import monitor_runs

        inbox_run = monitor_runs.create_run(run_kind="inbox", task_name="最近接收", source="manual")
        monitor_runs.start_run(inbox_run)
        event_id = self._create_dispatch_event(monitor_run_id=inbox_run)
        # 接收夹记录在分发完成即定稿：只覆盖识别与整理移动。
        monitor_runs.finish_run(
            inbox_run,
            status="completed",
            summary="已分发 1 项。",
            result={"moved": 1, "left": 0},
        )
        # 真实顺序：分发当下独立扫描已经建好，变更同步随后处理移动事件。
        child_run = monitor_runs.create_run(
            run_kind="scan",
            task_name=TASK_NAME,
            source="inbox_dispatch",
            scope={"kind": "paths", "paths": [f"/Library/{self.TARGET_NAME}"]},
        )
        change_run = monitor_runs.create_run(
            run_kind="change",
            task_name=TASK_NAME,
            source="change",
            subject="文件变更",
            scope={"kind": "events"},
        )

        self._run_change_task(run_id=change_run)
        self.assertEqual(self._event_status(event_id), "manual_required")
        # 独立扫描已经覆盖该目录：变更同步不再等它，也不因它停在“部分完成”。
        change_detail = monitor_runs.get_run_detail(change_run)
        self.assertEqual(change_detail["run"]["parent_run_id"], "")
        # 变更同步确实同步了网盘移动（STRM 交给独立任务生成），按“已完成”定稿。
        self.assertEqual(change_detail["run"]["status"], "completed")
        self.assertIn("已同步 1 条网盘变更", change_detail["run"]["summary"])
        # 执行明细要显示真实内容：标题/范围是这次变更的目录，入队步骤不再写“全部目录”。
        self.assertEqual(change_detail["run"]["subject"], self.TARGET_NAME)
        self.assertEqual(
            change_detail["run"]["scope"],
            {"kind": "paths", "paths": [f"Library/{self.TARGET_NAME}"]},
        )
        queued_event = next(
            item for item in change_detail["events"] if item.get("operation") == "queued"
        )
        self.assertEqual(queued_event["detail"]["scope"], {"kind": "events"})
        # 本地播放文件由独立任务生成：变更同步要显式记一笔，不能看起来什么都没做。
        delegated_event = next(
            item for item in change_detail["events"] if item.get("operation") == "delegated"
        )
        self.assertEqual(delegated_event["status"], "completed")
        self.assertEqual(delegated_event["detail"]["children"], 0)
        self.assertEqual(delegated_event["detail"]["independent_children"], 1)

        self._run_child_scan(run_id=child_run)

        self.assertEqual(self._event_status(event_id), "completed")
        # 独立任务结束后不会回头改写变更同步的既定结论。
        self.assertEqual(monitor_runs.get_run_detail(change_run)["run"]["status"], "completed")
        self.assertEqual(monitor_runs.get_run_detail(inbox_run)["run"]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
