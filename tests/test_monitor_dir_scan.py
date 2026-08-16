import asyncio
import os
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, Mock, patch

from app import db
from app.services import monitor, strm_files


TASK_NAME = "影视监控"
TASK_NAME_2 = "电影监控"


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


class MonitorDirScanTest(unittest.TestCase):
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

    def _task(
        self,
        *,
        name: str = TASK_NAME,
        scan_path: str = "/115/Library",
        sync_clean: bool = True,
        skip_by_dir_mtime: bool = True,
    ) -> dict:
        return {
            "name": name,
            "webhook_enabled": False,
            "scan_path": scan_path,
            "target_path": "Library" if scan_path == "/115/Library" else "Movies",
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

    def _cfg(self, tasks: List[dict]) -> dict:
        return {
            "monitor_tasks": tasks,
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
                ) VALUES (?, ?, ?, ?, ?, 0)
                """,
                (TASK_NAME, dir_rel_path, remote_modified, entry_modified, needs_rescan),
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

    def _list_monitor_files(self) -> List[str]:
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
        path_results: Dict[str, Any],
        *,
        task: dict,
        trigger: str = "manual",
        payload: Optional[dict] = None,
    ) -> List[str]:
        call_log: List[str] = []

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
            stack.enter_context(patch.object(monitor, "get_config", return_value=self._cfg([task])))
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
            asyncio.run(monitor.run_monitor_task(TASK_NAME, trigger=trigger, payload=payload))

        return call_log

    def test_manual_savepaths_scans_only_selected_subtrees_and_forces_deep_dirs(self):
        task = self._task(skip_by_dir_mtime=True)
        self._insert_monitor_dir("SeriesA", remote_modified="t1", entry_modified="t1")
        self._insert_monitor_dir("SeriesA/SubA", remote_modified="t1", entry_modified="t1")
        self._insert_monitor_dir("SeriesB", remote_modified="t1", entry_modified="t1")
        path_results = {
            "/115/Library": ("", []),
            "/115/Library/SeriesA": ("t1", [_dir_item("SubA", "t1")]),
            "/115/Library/SeriesA/SubA": ("t1", [_file_item("E01.mkv", "t1")]),
            "/115/Library/SeriesB": ("t1", [_file_item("B01.mkv", "t1")]),
        }

        call_log = self._run_monitor(
            path_results,
            task=task,
            trigger="manual",
            payload={"provider": "115", "savepaths": ["Library/SeriesA", "Library/SeriesB"]},
        )

        self.assertIn("/115/Library/SeriesA", call_log)
        self.assertIn("/115/Library/SeriesA/SubA", call_log)
        self.assertIn("/115/Library/SeriesB", call_log)
        self.assertNotIn("/115/Library/SeriesC", call_log)
        self.assertTrue(
            os.path.exists(
                strm_files.managed_strm_file_path("Library/SeriesA/SubA/E01.mkv", root=self.strm_root)
            )
        )
        self.assertTrue(
            os.path.exists(
                strm_files.managed_strm_file_path("Library/SeriesB/B01.mkv", root=self.strm_root)
            )
        )

    def test_savepaths_cleanup_and_index_bounded_to_union(self):
        task = self._task(sync_clean=True, skip_by_dir_mtime=True)
        self._insert_monitor_file(
            "Library/SeriesA/E01.mkv",
            remote_rel_path="SeriesA/E01.mkv",
            remote_modified="t1",
        )
        self._insert_monitor_file(
            "Library/SeriesA/Gone.mkv",
            remote_rel_path="SeriesA/Gone.mkv",
            remote_modified="t0",
        )
        self._insert_monitor_file(
            "Library/SeriesB/B01.mkv",
            remote_rel_path="SeriesB/B01.mkv",
            remote_modified="t1",
        )
        self._insert_monitor_file(
            "Library/SeriesC/Unrelated.mkv",
            remote_rel_path="SeriesC/Unrelated.mkv",
            remote_modified="t0",
        )
        gone_strm = self._create_strm("Library/SeriesA/Gone.mkv")
        unrelated_strm = self._create_strm("Library/SeriesC/Unrelated.mkv")
        path_results = {
            "/115/Library": ("", []),
            "/115/Library/SeriesA": ("t1", [_file_item("E01.mkv", "t1")]),
            "/115/Library/SeriesB": ("t1", [_file_item("B01.mkv", "t1")]),
        }

        self._run_monitor(
            path_results,
            task=task,
            trigger="manual",
            payload={"provider": "115", "savepaths": ["Library/SeriesA", "Library/SeriesB"]},
        )

        self.assertFalse(os.path.exists(gone_strm))
        self.assertTrue(os.path.exists(unrelated_strm))
        files = self._list_monitor_files()
        self.assertIn("Library/SeriesA/E01.mkv", files)
        self.assertNotIn("Library/SeriesA/Gone.mkv", files)
        self.assertIn("Library/SeriesB/B01.mkv", files)
        self.assertIn("Library/SeriesC/Unrelated.mkv", files)

    def test_queue_monitor_dir_scan_groups_by_task_and_dedupes(self):
        cfg = self._cfg([self._task(), self._task(name=TASK_NAME_2, scan_path="/115/Movies")])
        with patch.object(monitor, "queue_monitor_job", return_value="queued") as queue_mock:
            result = monitor.queue_monitor_dir_scan(
                cfg,
                "115",
                ["Library/SeriesA", "Library/SeriesA", "Movies/SomeMovie", "Outside/Whatever"],
            )

        calls = {
            (call.args[0], call.args[1], tuple(call.args[2]["savepaths"]))
            for call in queue_mock.call_args_list
        }
        self.assertEqual(
            calls,
            {
                (TASK_NAME, "manual", ("Library/SeriesA",)),
                (TASK_NAME_2, "manual", ("Movies/SomeMovie",)),
            },
        )
        self.assertEqual(result["unmatched"], ["Outside/Whatever"])
        self.assertEqual(
            {(item["task_name"], item["matched"]) for item in result["tasks"]},
            {(TASK_NAME, 1), (TASK_NAME_2, 1)},
        )

    def test_queue_monitor_dir_scan_no_match_raises(self):
        cfg = self._cfg([self._task()])
        with self.assertRaises(ValueError):
            monitor.queue_monitor_dir_scan(cfg, "115", ["Outside/Whatever"])

    def test_queue_monitor_dir_scan_over_cap_raises(self):
        cfg = self._cfg([self._task()])
        paths = [f"Library/Dir{i}" for i in range(51)]
        with self.assertRaises(ValueError):
            monitor.queue_monitor_dir_scan(cfg, "115", paths)

    def test_queue_merge_savepaths_union_without_full_escalation(self):
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
                "manual",
                {"provider": "115", "savepaths": ["Library/SeriesA"]},
            )
            monitor.queue_monitor_job(
                TASK_NAME,
                "manual",
                {"provider": "115", "savepaths": ["Library/SeriesB"]},
            )

        self.assertEqual(len(queued), 1)
        self.assertEqual(
            queued[0]["payload"]["savepaths"],
            ["Library/SeriesA", "Library/SeriesB"],
        )
        self.assertEqual(queued[0]["payload"]["provider"], "115")

    def test_queue_merge_savepaths_over_cap_falls_back_full_scan(self):
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
                "manual",
                {"provider": "115", "savepaths": [f"Library/A{i}" for i in range(40)]},
            )
            monitor.queue_monitor_job(
                TASK_NAME,
                "manual",
                {"provider": "115", "savepaths": [f"Library/B{i}" for i in range(20)]},
            )

        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0]["payload"], {})

    def test_webhook_single_savepath_merge_regression(self):
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
                {"savepath": "Library/SeriesA", "sharetitle": "X"},
            )
            monitor.queue_monitor_job(
                TASK_NAME,
                "webhook",
                {"savepath": "Library/SeriesB", "sharetitle": "Y"},
            )

        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0]["payload"], {})


if __name__ == "__main__":
    unittest.main()
