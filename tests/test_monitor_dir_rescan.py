import asyncio
import os
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack
from typing import Optional
from unittest.mock import AsyncMock, Mock, patch

from app import db
from app.services import monitor, monitor_changes, strm_files


TASK_NAME = "Monitor"


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


if __name__ == "__main__":
    unittest.main()
