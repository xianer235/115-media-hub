import asyncio
import inspect
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app import db
from app import core
from app.services import monitor_changes
from app.services import monitor
from app.services import scraper


ROOT = Path(__file__).resolve().parents[1]
SCRAPER_CORE_PATH = ROOT / "static/js/modules/scraper/core.js"
INDEX_JS_PATH = ROOT / "static/js/index.js"


class ScraperMonitorSyncTest(unittest.TestCase):
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

    @staticmethod
    def _task(name="影视监控", scan_path="/115/Media", target_path="媒体库", **overrides):
        task = {
            "name": name,
            "scan_path": scan_path,
            "target_path": target_path,
            "skip_by_dir_mtime": True,
            "strm_write_mode": "incremental",
            "sync_clean": False,
            "incremental": True,
            "retries": 1,
            "list_delay_ms": 0,
            "min_file_size_mb": 0,
            "delay_seconds": 0,
            "cron_minutes": 0,
            "webhook_enabled": False,
        }
        task.update(overrides)
        return task

    def _cfg(self, *tasks):
        return {
            "monitor_tasks": list(tasks or (self._task(),)),
            "mount_points": [{"provider": "115", "prefix": "/115"}],
            "extensions": "mkv,mp4",
            "strm_proxy_base_url": "http://localhost:18080",
            "cookie_115": "cookie",
        }

    def _strm_path(self, local_rel_path):
        return os.path.join(self.strm_root, local_rel_path + ".strm")

    def _insert_monitor_file(
        self,
        task_name,
        local_rel_path,
        remote_rel_path,
        *,
        modified="2026-08-09 10:00:00",
        size=1024,
    ):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO monitor_files(
                    task_name, local_rel_path, remote_rel_path, remote_modified, file_size
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (task_name, local_rel_path, remote_rel_path, modified, size),
            )

    def _write_strm(self, local_rel_path, content="old"):
        path = self._strm_path(local_rel_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        return path

    def _run_confirmed(self, cfg, operation, entries, *, source_action="direct", dedupe_key="case"):
        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation=operation,
            entries=entries,
            source_action=source_action,
            dedupe_key=dedupe_key,
            cfg=cfg,
        )
        confirmed = monitor_changes.confirm_monitor_change_events(prepared, succeeded=True, enqueue=False)
        with patch.object(monitor_changes, "STRM_ROOT", self.strm_root):
            result = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))
        return prepared, confirmed, result

    def test_schema_persists_prepared_event_before_confirmation(self):
        cfg = self._cfg()
        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="rename",
            entries=[
                {
                    "id": "f1",
                    "name": "Old.mkv",
                    "path": "Media/Old.mkv",
                    "new_path": "Media/New.mkv",
                    "is_dir": False,
                    "size": 1024,
                    "modified_at": "2026-08-09 10:00:00",
                }
            ],
            source_action="direct:rename",
            dedupe_key="rename:f1:old-new",
            cfg=cfg,
        )

        self.assertEqual(prepared["status"], "prepared")
        self.assertEqual(prepared["matched_tasks"], ["影视监控"])
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT operation, old_path, new_path, task_name, status, source_action "
                "FROM monitor_change_events"
            ).fetchone()
        self.assertEqual(
            row,
            ("rename", "Media/Old.mkv", "Media/New.mkv", "影视监控", "prepared", "direct:rename"),
        )

    def test_schema_migration_adds_processor_revision_without_losing_events(self):
        cfg = self._cfg()
        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="delete",
            entries=[{"id": "legacy-event", "path": "Media/Legacy.mkv", "is_dir": False}],
            dedupe_key="legacy-event",
            cfg=cfg,
        )
        event_id = prepared["event_ids"][0]
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("ALTER TABLE monitor_change_events DROP COLUMN processor_revision")
            columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(monitor_change_events)").fetchall()
            }
        self.assertNotIn("processor_revision", columns)

        db._DB_ENSURED = False
        db.ensure_db()

        with sqlite3.connect(self.db_path) as conn:
            columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(monitor_change_events)").fetchall()
            }
            row = conn.execute(
                "SELECT id, status, processor_revision FROM monitor_change_events WHERE id = ?",
                (event_id,),
            ).fetchone()
        self.assertIn("processor_revision", columns)
        self.assertEqual(row, (event_id, "prepared", 0))

    def test_snapshot_normalizes_size_and_fills_parent_path(self):
        cfg = self._cfg()
        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="rename",
            entries=[
                {
                    "id": "snapshot-normalize",
                    "name": "Old.mkv",
                    "path": "Media/Old.mkv",
                    "new_path": "Media/New.mkv",
                    "is_dir": False,
                    "size": "4096",
                    "modified_at": "2026-08-09 10:00:00",
                }
            ],
            dedupe_key="snapshot-normalize",
            cfg=cfg,
        )

        with sqlite3.connect(self.db_path) as conn:
            raw_snapshot = conn.execute(
                "SELECT entry_snapshot_json FROM monitor_change_events WHERE id = ?",
                (prepared["event_ids"][0],),
            ).fetchone()[0]
        snapshot = json.loads(raw_snapshot)
        self.assertEqual(snapshot["size"], 4096)
        self.assertEqual(snapshot["parent_path"], "Media")

    def test_snapshot_parses_string_false_as_file(self):
        cfg = self._cfg()
        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="delete",
            entries=[
                {
                    "id": "snapshot-bool",
                    "path": "Media/File.mkv",
                    "is_dir": "false",
                }
            ],
            dedupe_key="snapshot-bool",
            cfg=cfg,
        )

        with sqlite3.connect(self.db_path) as conn:
            raw_snapshot = conn.execute(
                "SELECT entry_snapshot_json FROM monitor_change_events WHERE id = ?",
                (prepared["event_ids"][0],),
            ).fetchone()[0]
        self.assertFalse(json.loads(raw_snapshot)["is_dir"])

    def test_completed_event_confirmation_reports_completed(self):
        cfg = self._cfg()
        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="delete",
            entries=[{"id": "already-done", "path": "Media/Done.mkv", "is_dir": False}],
            dedupe_key="already-done",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(prepared, succeeded=True, enqueue=False)
        with patch.object(monitor_changes, "STRM_ROOT", self.strm_root):
            result = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))
        self.assertEqual(result["completed"], 1)

        repeated = monitor_changes.confirm_monitor_change_events(prepared, succeeded=True, enqueue=False)

        self.assertEqual(repeated["status"], "completed")
        self.assertEqual(repeated["event_count"], 1)

    def test_file_rename_updates_strm_and_index_without_remote_listing(self):
        cfg = self._cfg()
        old_local = "媒体库/Media/Old.mkv"
        new_local = "媒体库/Media/New.mkv"
        self._insert_monitor_file("影视监控", old_local, "Old.mkv")
        old_strm = self._write_strm(old_local)

        with patch.object(
            monitor_changes,
            "list_remote_dir",
            AsyncMock(side_effect=AssertionError("known file changes must not list 115 directories")),
        ):
            prepared, confirmed, result = self._run_confirmed(
                cfg,
                "rename",
                [
                    {
                        "id": "f1",
                        "name": "Old.mkv",
                        "path": "Media/Old.mkv",
                        "new_path": "Media/New.mkv",
                        "is_dir": False,
                        "size": 1024,
                        "modified_at": "2026-08-09 10:00:00",
                    }
                ],
                dedupe_key="rename-known-file",
            )

        self.assertEqual(confirmed["status"], "queued")
        self.assertEqual(result["completed"], 1)
        self.assertFalse(os.path.exists(old_strm))
        new_strm = self._strm_path(new_local)
        self.assertTrue(os.path.isfile(new_strm))
        with open(new_strm, "r", encoding="utf-8") as handle:
            self.assertEqual(
                handle.read(),
                "http://localhost:18080/strm/proxy?path=%2F115%2FMedia%2FNew.mkv",
            )
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT local_rel_path, remote_rel_path FROM monitor_files ORDER BY local_rel_path"
            ).fetchall()
        self.assertEqual(rows, [(new_local, "New.mkv")])

    def test_confirmed_scraper_move_outside_monitor_removes_old_strm(self):
        cfg = self._cfg(self._task(scan_path="/115/一级", target_path="媒体库"))
        old_local = "媒体库/一级/二级/Old.mkv"
        self._insert_monitor_file("影视监控", old_local, "二级/Old.mkv")
        old_strm = self._write_strm(old_local, "old")
        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="rename",
            entries=[
                {
                    "id": "incomplete-path",
                    "old_path": "一级/二级/Old.mkv",
                    "new_path": "New.mkv",
                    "old_parent_id": "second-level-cid",
                    "new_parent_id": "second-level-cid",
                    "is_dir": False,
                    "size": 4096,
                }
            ],
            source_action="scraper-job:legacy:forward",
            dedupe_key="incomplete-rename",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(prepared, succeeded=True, enqueue=False)

        with (
            patch.object(monitor_changes, "STRM_ROOT", self.strm_root),
            patch.object(
                monitor_changes,
                "list_remote_dir",
                AsyncMock(side_effect=AssertionError("confirmed invalid paths must not read 115")),
            ),
        ):
            result = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))

        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["deleted"], 1)
        self.assertFalse(os.path.isfile(old_strm))
        with sqlite3.connect(self.db_path) as conn:
            index_rows = conn.execute(
                "SELECT local_rel_path, remote_rel_path FROM monitor_files"
            ).fetchall()
            event_row = conn.execute(
                "SELECT status, last_error FROM monitor_change_events WHERE id = ?",
                (prepared["event_ids"][0],),
            ).fetchone()
        self.assertEqual(index_rows, [])
        self.assertEqual(event_row[0], "completed")

    def test_confirmed_scraper_change_uses_paths_when_parent_ids_disagree(self):
        cfg = self._cfg(self._task(scan_path="/115/一级", target_path="媒体库"))
        old_local = "媒体库/一级/二级/Old.mkv"
        self._insert_monitor_file("影视监控", old_local, "二级/Old.mkv")
        old_strm = self._write_strm(old_local, "old")
        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="move",
            entries=[
                {
                    "id": "contradictory-parent",
                    "old_path": "一级/二级/Old.mkv",
                    "new_path": "一级/New.mkv",
                    "old_parent_id": "second-level-cid",
                    "new_parent_id": "second-level-cid",
                    "is_dir": False,
                    "size": 4096,
                }
            ],
            source_action="scraper-job:legacy:forward",
            dedupe_key="contradictory-parent",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(prepared, succeeded=True, enqueue=False)

        with (
            patch.object(monitor_changes, "STRM_ROOT", self.strm_root),
            patch.object(
                monitor_changes,
                "list_remote_dir",
                AsyncMock(side_effect=AssertionError("confirmed invalid paths must not read 115")),
            ),
        ):
            result = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))

        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["deleted"], 1)
        self.assertFalse(os.path.isfile(old_strm))
        self.assertTrue(os.path.isfile(self._strm_path("媒体库/一级/New.mkv")))
        with sqlite3.connect(self.db_path) as conn:
            index_rows = conn.execute(
                "SELECT local_rel_path, remote_rel_path FROM monitor_files"
            ).fetchall()
            event_status = conn.execute(
                "SELECT status FROM monitor_change_events WHERE id = ?",
                (prepared["event_ids"][0],),
            ).fetchone()[0]
        self.assertEqual(index_rows, [("媒体库/一级/New.mkv", "New.mkv")])
        self.assertEqual(event_status, "completed")

    def test_delete_is_explicit_even_when_sync_clean_is_false(self):
        cfg = self._cfg(self._task(sync_clean=False, incremental=True))
        local_rel = "媒体库/Media/Delete.mkv"
        self._insert_monitor_file("影视监控", local_rel, "Delete.mkv")
        target = self._write_strm(local_rel)

        _, _, result = self._run_confirmed(
            cfg,
            "delete",
            [
                {
                    "id": "f2",
                    "name": "Delete.mkv",
                    "path": "Media/Delete.mkv",
                    "is_dir": False,
                    "size": 1024,
                }
            ],
            dedupe_key="delete-sync-clean-false",
        )

        self.assertEqual(result["completed"], 1)
        self.assertFalse(os.path.exists(target))
        with sqlite3.connect(self.db_path) as conn:
            count = conn.execute("SELECT COUNT(1) FROM monitor_files").fetchone()[0]
        self.assertEqual(count, 0)

    def test_file_delete_keeps_empty_parent_directory(self):
        cfg = self._cfg()
        local_rel = "媒体库/Media/Folder/Delete.mkv"
        self._insert_monitor_file("影视监控", local_rel, "Folder/Delete.mkv")
        target = self._write_strm(local_rel)
        parent_dir = os.path.dirname(target)

        _, _, result = self._run_confirmed(
            cfg,
            "delete",
            [{"id": "keep-parent", "path": "Media/Folder/Delete.mkv", "is_dir": False}],
            dedupe_key="delete-keep-parent",
        )

        self.assertEqual(result["completed"], 1)
        self.assertFalse(os.path.exists(target))
        self.assertTrue(os.path.isdir(parent_dir))

    def test_delete_keeps_shared_strm_referenced_by_another_monitor_task(self):
        task_a = self._task(name="任务 A", target_path="共享库")
        task_b = self._task(name="任务 B", target_path="共享库")
        cfg = self._cfg(task_a, task_b)
        local_rel = "共享库/Media/Shared.mkv"
        self._insert_monitor_file("任务 A", local_rel, "Shared.mkv")
        self._insert_monitor_file("任务 B", local_rel, "Shared.mkv")
        target = self._write_strm(local_rel, "shared")

        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="delete",
            entries=[{"id": "shared", "path": "Media/Shared.mkv", "is_dir": False}],
            dedupe_key="shared-delete",
            cfg=cfg,
        )
        with sqlite3.connect(self.db_path) as conn:
            task_a_event_id = conn.execute(
                "SELECT id FROM monitor_change_events WHERE task_name = '任务 A'"
            ).fetchone()[0]
        monitor_changes.confirm_monitor_change_events(prepared, succeeded=True, enqueue=False)
        with patch.object(monitor_changes, "STRM_ROOT", self.strm_root):
            result = asyncio.run(
                monitor_changes.process_monitor_change_events(
                    "任务 A",
                    cfg=cfg,
                    event_ids=[task_a_event_id],
                )
            )

        self.assertEqual(result["completed"], 1)
        self.assertTrue(os.path.isfile(target))
        self.assertEqual(result.get("change_details"), [])
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT task_name FROM monitor_files WHERE local_rel_path = ? ORDER BY task_name",
                (local_rel,),
            ).fetchall()
        self.assertEqual(rows, [("任务 B",)])

    def test_path_matches_every_covering_monitor_task(self):
        cfg = self._cfg(
            self._task(name="Media", scan_path="/115/Media", target_path="A"),
            self._task(name="Shows", scan_path="/115/Media/Shows", target_path="B"),
        )

        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="copy",
            entries=[
                {
                    "id": "f3",
                    "name": "Episode.mkv",
                    "path": "Media/Source/Episode.mkv",
                    "new_path": "Media/Shows/Episode.mkv",
                    "is_dir": False,
                    "size": 2048,
                }
            ],
            dedupe_key="copy-multi-task",
            cfg=cfg,
        )

        self.assertEqual(prepared["matched_tasks"], ["Media", "Shows"])
        with sqlite3.connect(self.db_path) as conn:
            task_names = [
                row[0]
                for row in conn.execute(
                    "SELECT task_name FROM monitor_change_events ORDER BY task_name"
                ).fetchall()
            ]
        self.assertEqual(task_names, ["Media", "Shows"])

    def test_folder_manifest_is_shared_across_covering_monitor_tasks(self):
        broad = self._task(name="Broad", scan_path="/115/Media", target_path="Broad")
        nested = self._task(name="Nested", scan_path="/115/Media/Shows", target_path="Nested")
        cfg = self._cfg(broad, nested)
        self._insert_monitor_file(
            "Broad",
            "Broad/Media/Shows/Source/Episode.mkv",
            "Shows/Source/Episode.mkv",
            size=4096,
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO monitor_dirs(task_name, dir_rel_path, remote_modified, entry_modified, needs_rescan, missing_confirmations) VALUES (?, ?, ?, ?, 0, 0)",
                ("Broad", "Shows/Source", "source-modified", "source-entry-modified"),
            )
            conn.commit()
        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="copy",
            entries=[
                {
                    "id": "folder-per-task",
                    "name": "Source",
                    "path": "Media/Shows/Source",
                    "new_path": "Media/Shows/Copied",
                    "is_dir": True,
                }
            ],
            dedupe_key="folder-manifest-per-task",
            cfg=cfg,
        )

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT task_name, entry_snapshot_json FROM monitor_change_events ORDER BY task_name"
            ).fetchall()
        self.assertEqual([row[0] for row in rows], ["Broad", "Nested"])
        snapshots = {task_name: json.loads(raw) for task_name, raw in rows}
        self.assertTrue(snapshots["Broad"]["manifest_known"])
        self.assertTrue(snapshots["Nested"]["manifest_known"])
        self.assertEqual(
            snapshots["Broad"]["indexed_files"],
            [{"modified_at": "2026-08-09 10:00:00", "path": "Media/Shows/Source/Episode.mkv", "size": 4096}],
        )
        self.assertEqual(snapshots["Nested"]["indexed_files"], snapshots["Broad"]["indexed_files"])
        self.assertEqual(
            snapshots["Broad"]["indexed_dirs"],
            [
                {
                    "entry_modified": "source-entry-modified",
                    "path": "Media/Shows/Source",
                    "remote_modified": "source-modified",
                }
            ],
        )
        self.assertEqual(snapshots["Nested"]["indexed_dirs"], snapshots["Broad"]["indexed_dirs"])

    def test_indexed_folder_copy_clones_manifest_and_preserves_metadata(self):
        cfg = self._cfg()
        old_local = "媒体库/Media/Source/Episode.mkv"
        self._insert_monitor_file("影视监控", old_local, "Source/Episode.mkv", size=4096)
        self._write_strm(old_local, "source")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO monitor_dirs(task_name, dir_rel_path, remote_modified, entry_modified, needs_rescan, missing_confirmations) VALUES (?, ?, ?, ?, 0, 0)",
                ("影视监控", "Source", "source-modified", "source-entry-modified"),
            )
            conn.commit()
        metadata = os.path.join(self.strm_root, "媒体库/Media/Source/poster.jpg")
        os.makedirs(os.path.dirname(metadata), exist_ok=True)
        with open(metadata, "w", encoding="utf-8") as handle:
            handle.write("poster")

        with patch.object(
            monitor_changes,
            "list_remote_dir",
            AsyncMock(side_effect=AssertionError("indexed folder copies must not list remote directories")),
        ):
            _, _, result = self._run_confirmed(
                cfg,
                "copy",
                [
                    {
                        "id": "d1",
                        "name": "Source",
                        "path": "Media/Source",
                        "new_path": "Media/Copied",
                        "is_dir": True,
                    }
                ],
                dedupe_key="copy-indexed-folder",
            )

        self.assertEqual(result["completed"], 1)
        copied = self._strm_path("媒体库/Media/Copied/Episode.mkv")
        self.assertTrue(os.path.isfile(copied))
        self.assertTrue(os.path.isfile(metadata))
        with open(copied, "r", encoding="utf-8") as handle:
            self.assertIn("%2F115%2FMedia%2FCopied%2FEpisode.mkv", handle.read())
        with sqlite3.connect(self.db_path) as conn:
            dir_rows = conn.execute(
                "SELECT dir_rel_path, remote_modified, entry_modified, needs_rescan FROM monitor_dirs ORDER BY dir_rel_path"
            ).fetchall()
        self.assertEqual(
            dir_rows,
            [
                ("Copied", "source-modified", "source-entry-modified", 0),
                ("Source", "source-modified", "source-entry-modified", 0),
            ],
        )

    def test_dirty_indexed_folder_copy_syncs_known_index_and_requires_manual_monitor(self):
        cfg = self._cfg()
        old_local = "媒体库/Media/Source/Episode.mkv"
        self._insert_monitor_file("影视监控", old_local, "Source/Episode.mkv", size=4096)
        self._write_strm(old_local, "source")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO monitor_dirs(task_name, dir_rel_path, remote_modified, entry_modified, needs_rescan, missing_confirmations) VALUES (?, ?, '', '', 1, 0)",
                ("影视监控", "Source"),
            )
            conn.commit()

        with patch.object(
            monitor_changes,
            "list_remote_dir",
            AsyncMock(side_effect=AssertionError("unknown folders must wait for a manual monitor scan")),
        ):
            _, confirmed, result = self._run_confirmed(
                cfg,
                "copy",
                [
                    {
                        "id": "dirty-source",
                        "name": "Source",
                        "path": "Media/Source",
                        "new_path": "Media/Copied",
                        "new_cid": "copied-folder-cid",
                        "is_dir": True,
                    }
                ],
                dedupe_key="dirty-index-copy",
            )

        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["manual_required"], 1)
        self.assertEqual(confirmed["status"], "manual_required")
        self.assertTrue(os.path.isfile(self._strm_path("媒体库/Media/Copied/Episode.mkv")))
        with sqlite3.connect(self.db_path) as conn:
            status = conn.execute("SELECT status FROM monitor_change_events").fetchone()[0]
        self.assertEqual(status, "manual_required")

    def test_unknown_folder_copy_requires_manual_monitor_without_remote_listing(self):
        cfg = self._cfg()
        with patch.object(
            monitor_changes,
            "list_remote_dir",
            AsyncMock(side_effect=AssertionError("unknown folders must not list the target subtree")),
        ):
            _, confirmed, result = self._run_confirmed(
                cfg,
                "copy",
                [
                    {
                        "id": "d2",
                        "name": "Source",
                        "path": "Outside/Source",
                        "new_path": "Media/Copied",
                        "new_cid": "copied-cid",
                        "is_dir": True,
                    }
                ],
                dedupe_key="copy-unknown-folder",
            )

        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["manual_required"], 1)
        self.assertEqual(confirmed["status"], "manual_required")
        self.assertFalse(os.path.exists(self._strm_path("媒体库/Media/Copied/Season 1/Episode.mkv")))
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT status, retry_count FROM monitor_change_events").fetchone()
        self.assertEqual(row, ("manual_required", 0))

    def test_successful_manual_scan_clears_manual_required_event_for_covered_scope(self):
        cfg = self._cfg()
        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="copy",
            entries=[
                {
                    "id": "manual-clear",
                    "path": "Outside/Source",
                    "new_path": "Media/ManualFolder",
                    "is_dir": True,
                }
            ],
            dedupe_key="manual-clear",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(prepared, succeeded=True, enqueue=False)
        with patch.object(monitor_changes, "STRM_ROOT", self.strm_root):
            result = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))
        self.assertEqual(result["manual_required"], 1)
        self.assertEqual(monitor_changes.get_monitor_change_counts(), {"影视监控": {"pending": 0, "failed": 0, "manual_required": 1}})

        scopes = monitor_changes.get_manual_required_monitor_scopes("影视监控", cfg=cfg)
        self.assertEqual(len(scopes), 1)
        scope = scopes[0]
        self.assertEqual(scope["event_id"], prepared["event_ids"][0])
        self.assertEqual(scope["operation"], "copy")
        self.assertEqual(scope["provider_path"], "Media/ManualFolder")
        self.assertEqual(scope["new_path"], "Media/ManualFolder")
        self.assertEqual(scope["old_path"], "Outside/Source")
        self.assertEqual(scope["remote_path"], "/115/Media/ManualFolder")
        self.assertEqual(scope["first_level_dir_rel"], "ManualFolder")
        self.assertTrue(scope["created_at"])

        self.assertEqual(
            monitor_changes.complete_manual_required_monitor_events(
                "影视监控",
                [prepared["event_ids"][0]],
            ),
            1,
        )
        with sqlite3.connect(self.db_path) as conn:
            status = conn.execute("SELECT status FROM monitor_change_events").fetchone()[0]
        self.assertEqual(status, "completed")
        self.assertEqual(monitor_changes.get_monitor_change_counts(), {})

    def test_cid_scoped_listing_does_not_resolve_through_monitor_root(self):
        cfg = self._cfg()
        task = cfg["monitor_tasks"][0]
        listed = []

        def fake_list_entries(_cookie, cid, _refresh):
            listed.append(str(cid))
            return [
                {
                    "id": "child-dir",
                    "cid": "child-dir",
                    "name": "Season 1",
                    "is_dir": True,
                    "size": 0,
                    "modified_at": "",
                },
                {
                    "id": "child-file",
                    "fid": "child-file",
                    "name": "Episode.mkv",
                    "is_dir": False,
                    "size": 4096,
                    "modified_at": "2026-08-09 12:00:00",
                },
            ]

        with (
            patch.object(core, "resolve_115_folder_id_by_path", side_effect=AssertionError("path resolution must not walk the root")),
            patch.object(core, "list_115_entries", side_effect=fake_list_entries),
        ):
            modified, items = asyncio.run(
                core.list_remote_dir(
                    cfg,
                    "/115/Media/Copied",
                    True,
                    task,
                    folder_cid="copied-cid",
                )
            )

        self.assertEqual(listed, ["copied-cid"])
        self.assertEqual(modified, "2026-08-09 12:00:00")
        self.assertEqual(items[0]["id"], "child-dir")
        self.assertEqual(items[0]["cid"], "child-dir")
        self.assertEqual(items[1]["id"], "child-file")

    def test_frontend_sends_entry_snapshots_for_every_115_mutation(self):
        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")

        self.assertIn("function buildMonitorEntrySnapshot", source)
        self.assertIn("parent_id: normalizeCid", source)
        self.assertIn("cid: item.is_dir", source)
        self.assertIn("function buildMutationRequestId", source)
        self.assertIn("entry: buildMonitorEntrySnapshot(target", source)
        self.assertGreaterEqual(source.count("entries: buffer.entries.map(buildMonitorEntrySnapshot)"), 2)
        self.assertIn("entries: selected.map(buildMonitorEntrySnapshot)", source)
        self.assertIn("target_parent_path: currentParentPath()", source)
        self.assertIn("parent_path: currentParentPath()", source)
        self.assertIn("monitor_sync", source)
        self.assertIn("STRM 同步已完成", source)
        self.assertIn("STRM 同步失败，已保留重试", source)

    def test_transfer_snapshot_distinguishes_move_and_copy_directory_ids(self):
        parameters = inspect.signature(scraper._build_transfer_monitor_snapshots).parameters
        self.assertIn("target_parent_id", parameters)
        self.assertIn("operation", parameters)

        entries = [
            {
                "id": "source-folder-cid",
                "cid": "source-folder-cid",
                "parent_id": "source-parent-cid",
                "name": "Source",
                "path": "Outside/Source",
                "is_dir": True,
            }
        ]
        moved = scraper._build_transfer_monitor_snapshots(
            "115",
            entries,
            "Media/Target",
            target_parent_id="target-parent-cid",
            operation="move",
        )
        copied = scraper._build_transfer_monitor_snapshots(
            "115",
            entries,
            "Media/Target",
            target_parent_id="target-parent-cid",
            operation="copy",
        )

        self.assertEqual(len(moved), 1)
        self.assertEqual(moved[0]["old_parent_id"], "source-parent-cid")
        self.assertEqual(moved[0]["new_parent_id"], "target-parent-cid")
        self.assertEqual(moved[0]["old_cid"], "source-folder-cid")
        self.assertEqual(moved[0]["new_cid"], "source-folder-cid")
        self.assertEqual(copied[0]["old_cid"], "source-folder-cid")
        self.assertEqual(copied[0]["new_cid"], "")

    def test_transfer_snapshots_filter_and_order_by_requested_entry_ids(self):
        entries = [
            {
                "id": "stale-entry",
                "name": "Stale.mkv",
                "path": "Outside/Stale.mkv",
                "is_dir": False,
            },
            {
                "id": "selected-b",
                "name": "B.mkv",
                "path": "Outside/B.mkv",
                "is_dir": False,
            },
            {
                "id": "selected-a",
                "name": "A.mkv",
                "path": "Outside/A.mkv",
                "is_dir": False,
            },
        ]

        snapshots = scraper._build_transfer_monitor_snapshots(
            "115",
            entries,
            "Media/Target",
            target_parent_id="target-parent-cid",
            operation="move",
            entry_ids=["selected-a", "selected-b"],
        )

        self.assertEqual([item["id"] for item in snapshots], ["selected-a", "selected-b"])
        self.assertEqual(
            [item["old_path"] for item in snapshots],
            ["Outside/A.mkv", "Outside/B.mkv"],
        )

    def test_transfer_snapshots_do_not_guess_missing_entry_ids_by_position(self):
        snapshots = scraper._build_transfer_monitor_snapshots(
            "115",
            [
                {
                    "name": "A.mkv",
                    "path": "Outside/A.mkv",
                    "is_dir": False,
                }
            ],
            "Media/Target",
            target_parent_id="target-parent-cid",
            operation="move",
            entry_ids=["requested-id"],
        )

        self.assertEqual(snapshots, [])

    def test_delete_snapshot_filters_entries_to_requested_ids(self):
        cfg = self._cfg()
        with (
            patch.object(scraper, "get_config", return_value=cfg),
            patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
            patch.object(scraper, "_delete_provider_entries", return_value={"state": True}),
            patch.object(scraper, "_invalidate_provider_parent"),
            patch.object(monitor_changes, "_enqueue_task_names"),
        ):
            response = scraper.delete_scraper_entries(
                "115",
                ["selected-id"],
                "parent-cid",
                [
                    {"id": "selected-id", "path": "Media/Selected.mkv", "is_dir": False},
                    {"id": "stale-id", "path": "Media/Stale.mkv", "is_dir": False},
                ],
                "delete-filter",
            )

        self.assertEqual(response["monitor_sync"]["event_count"], 1)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT old_path FROM monitor_change_events ORDER BY id").fetchall()
        self.assertEqual(rows, [("Media/Selected.mkv",)])

    def test_rename_snapshot_with_different_id_is_not_used_for_monitor_sync(self):
        cfg = self._cfg()
        with (
            patch.object(scraper, "get_config", return_value=cfg),
            patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
            patch.object(scraper, "_rename_provider_entry", return_value={"state": True}),
            patch.object(scraper, "_invalidate_provider_parent"),
            patch.object(monitor_changes, "_enqueue_task_names"),
        ):
            response = scraper.rename_scraper_entry(
                "115",
                "requested-id",
                "parent-cid",
                "New.mkv",
                {
                    "id": "stale-id",
                    "name": "Stale.mkv",
                    "path": "Media/Stale.mkv",
                    "is_dir": False,
                },
                "rename-id-filter",
            )

        self.assertEqual(response["monitor_sync"]["status"], "unavailable")
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(1) FROM monitor_change_events").fetchone()[0], 0)

    def test_copy_response_updates_prepared_event_with_destination_cid(self):
        cfg = self._cfg()
        with (
            patch.object(scraper, "get_config", return_value=cfg),
            patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
            patch.object(
                scraper,
                "_copy_provider_entries",
                return_value={
                    "response": {
                        "data": {
                            "source_id": "source-folder-cid",
                            "new_cid": "copied-folder-cid",
                        }
                    }
                },
            ),
            patch.object(scraper, "_invalidate_provider_parent"),
            patch.object(monitor_changes, "_enqueue_task_names"),
        ):
            response = scraper.copy_scraper_entries(
                "115",
                ["source-folder-cid"],
                "target-parent-cid",
                "source-parent-cid",
                [
                    {
                        "id": "source-folder-cid",
                        "cid": "source-folder-cid",
                        "parent_id": "source-parent-cid",
                        "name": "Source",
                        "path": "Outside/Source",
                        "is_dir": True,
                    }
                ],
                "Media",
                "copy-with-cid",
            )

        self.assertEqual(response["monitor_sync"]["status"], "manual_required")
        with sqlite3.connect(self.db_path) as conn:
            snapshot = json.loads(
                conn.execute("SELECT entry_snapshot_json FROM monitor_change_events").fetchone()[0]
            )
        self.assertEqual(snapshot["old_cid"], "source-folder-cid")
        self.assertEqual(snapshot["new_cid"], "copied-folder-cid")

    def test_copy_response_maps_explicit_destination_cid_list_in_snapshot_order(self):
        snapshots = [
            {
                "id": "source-a",
                "old_cid": "source-a",
                "old_parent_id": "source-parent",
                "new_parent_id": "target-parent",
                "name": "A",
                "old_path": "Outside/A",
                "new_path": "Media/A",
                "is_dir": True,
            },
            {
                "id": "source-b",
                "old_cid": "source-b",
                "old_parent_id": "source-parent",
                "new_parent_id": "target-parent",
                "name": "B",
                "old_path": "Outside/B",
                "new_path": "Media/B",
                "is_dir": True,
            },
        ]

        updates = scraper._extract_copy_destination_cids(
            {"response": {"data": {"new_cids": ["copied-a", "copied-b"]}}},
            snapshots,
        )

        self.assertEqual(
            [(item["id"], item["new_cid"]) for item in updates],
            [("source-a", "copied-a"), ("source-b", "copied-b")],
        )

    def test_copy_response_does_not_use_request_id_as_destination_cid(self):
        cfg = self._cfg()
        with (
            patch.object(scraper, "get_config", return_value=cfg),
            patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
            patch.object(
                scraper,
                "_copy_provider_entries",
                return_value={"response": {"data": {"id": "copy-request-id"}}},
            ),
            patch.object(scraper, "_invalidate_provider_parent"),
            patch.object(monitor_changes, "_enqueue_task_names"),
        ):
            scraper.copy_scraper_entries(
                "115",
                ["source-folder-cid"],
                "target-parent-cid",
                "source-parent-cid",
                [
                    {
                        "id": "source-folder-cid",
                        "cid": "source-folder-cid",
                        "parent_id": "source-parent-cid",
                        "name": "Source",
                        "path": "Outside/Source",
                        "is_dir": True,
                    }
                ],
                "Media",
                "copy-request-id",
            )

        with sqlite3.connect(self.db_path) as conn:
            snapshot = json.loads(
                conn.execute("SELECT entry_snapshot_json FROM monitor_change_events").fetchone()[0]
            )
        self.assertEqual(snapshot["new_cid"], "")

    def test_copy_without_destination_cid_requires_manual_monitor_without_listing(self):
        cfg = self._cfg()
        with (
            patch.object(scraper, "get_config", return_value=cfg),
            patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
            patch.object(scraper, "_copy_provider_entries", return_value={"response": {"data": {}}}),
            patch.object(scraper, "_invalidate_provider_parent"),
            patch.object(monitor_changes, "_enqueue_task_names"),
        ):
            scraper.copy_scraper_entries(
                "115",
                ["source-folder-cid"],
                "target-parent-cid",
                "source-parent-cid",
                [
                    {
                        "id": "source-folder-cid",
                        "cid": "source-folder-cid",
                        "parent_id": "source-parent-cid",
                        "name": "Source",
                        "path": "Outside/Source",
                        "is_dir": True,
                    }
                ],
                "Media",
                "copy-without-cid",
            )

        with (
            patch.object(monitor_changes, "STRM_ROOT", self.strm_root),
            patch.object(
                monitor_changes,
                "list_remote_dir",
                AsyncMock(side_effect=AssertionError("missing destination CID must not list source or root")),
            ),
        ):
            processed = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))

        self.assertEqual(processed["completed"], 1)
        self.assertEqual(processed["manual_required"], 1)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT status, entry_snapshot_json, last_error FROM monitor_change_events"
            ).fetchone()
        self.assertEqual(row[0], "manual_required")
        self.assertEqual(json.loads(row[1])["new_cid"], "")
        self.assertEqual(row[2], "需手动监控")

    def test_zero_destination_cid_requires_manual_monitor_without_listing_root(self):
        cfg = self._cfg()
        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="copy",
            entries=[
                {
                    "id": "zero-cid-folder",
                    "path": "Outside/Source",
                    "new_path": "Media/ZeroCid",
                    "new_cid": "0",
                    "is_dir": True,
                }
            ],
            dedupe_key="zero-destination-cid",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(prepared, succeeded=True, enqueue=False)
        calls = []

        async def should_not_list(*_args, **_kwargs):
            calls.append(True)
            raise AssertionError("zero CID must not access any remote directory")

        with (
            patch.object(monitor_changes, "STRM_ROOT", self.strm_root),
            patch.object(monitor_changes, "list_remote_dir", side_effect=should_not_list),
        ):
            result = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))

        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["manual_required"], 1)
        self.assertEqual(calls, [])

    def test_direct_rename_persists_event_before_provider_call(self):
        cfg = self._cfg()
        call_order = []

        def fake_prepare(*args, **kwargs):
            call_order.append("prepare")
            return monitor_changes.prepare_monitor_change_events(
                provider=args[0],
                operation=args[1],
                entries=args[2],
                cfg=cfg,
                **kwargs,
            )

        def fake_rename(*args, **kwargs):
            call_order.append("remote")
            return {"state": True}

        with (
            patch.object(scraper, "get_config", return_value=cfg),
            patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
            patch.object(scraper, "_rename_provider_entry", side_effect=fake_rename),
            patch.object(scraper, "_prepare_scraper_monitor_sync", side_effect=fake_prepare),
            patch.object(scraper, "_invalidate_provider_parent"),
            patch.object(monitor_changes, "_enqueue_task_names"),
        ):
            result = scraper.rename_scraper_entry(
                "115",
                "f-direct",
                "parent",
                "New.mkv",
                {
                    "id": "f-direct",
                    "name": "Old.mkv",
                    "path": "Media/Old.mkv",
                    "parent_path": "Media",
                    "is_dir": False,
                    "size": 4096,
                    "modified_at": "2026-08-09 10:00:00",
                },
                "direct-test",
            )

        self.assertEqual(call_order, ["prepare", "remote"])
        self.assertEqual(result["monitor_sync"]["status"], "queued")
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT status, old_path, new_path FROM monitor_change_events"
            ).fetchone()
        self.assertEqual(row, ("pending", "Media/Old.mkv", "Media/New.mkv"))

    def test_provider_failure_keeps_reconcile_event(self):
        cfg = self._cfg()
        with (
            patch.object(scraper, "get_config", return_value=cfg),
            patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
            patch.object(scraper, "_rename_provider_entry", side_effect=RuntimeError("remote timeout")),
            patch.object(scraper, "_invalidate_provider_parent"),
            patch.object(monitor_changes, "_enqueue_task_names"),
        ):
            with self.assertRaisesRegex(RuntimeError, "remote timeout"):
                scraper.rename_scraper_entry(
                    "115",
                    "f-fail",
                    "parent",
                    "New.mkv",
                    {
                        "id": "f-fail",
                        "name": "Old.mkv",
                        "path": "Media/Old.mkv",
                        "is_dir": False,
                    },
                    "failure-test",
                )

        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT status, needs_reconcile, last_error FROM monitor_change_events"
            ).fetchone()
        self.assertEqual(row[0], "pending")
        self.assertEqual(row[1], 1)
        self.assertIn("remote timeout", row[2])

    def test_old_client_without_snapshot_keeps_remote_operation_compatible(self):
        cfg = self._cfg()
        with (
            patch.object(scraper, "get_config", return_value=cfg),
            patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
            patch.object(scraper, "_rename_provider_entry", return_value={"state": True}),
            patch.object(scraper, "_invalidate_provider_parent"),
            patch.object(monitor_changes, "_enqueue_task_names"),
        ):
            result = scraper.rename_scraper_entry("115", "legacy", "parent", "New.mkv")

        self.assertEqual(result["monitor_sync"]["status"], "unavailable")
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(1) FROM monitor_change_events").fetchone()[0], 0)

    def test_non_115_scraper_operation_does_not_create_monitor_event(self):
        cfg = self._cfg()
        with (
            patch.object(scraper, "get_config", return_value=cfg),
            patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
            patch.object(scraper, "_rename_provider_entry", return_value={"state": True}),
            patch.object(scraper, "_invalidate_provider_parent"),
        ):
            result = scraper.rename_scraper_entry(
                "quark",
                "quark-file",
                "parent",
                "New.mkv",
                {
                    "id": "quark-file",
                    "name": "Old.mkv",
                    "path": "Media/Old.mkv",
                    "is_dir": False,
                },
                "quark-operation",
            )

        self.assertEqual(result["monitor_sync"]["status"], "not_applicable")
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(1) FROM monitor_change_events").fetchone()[0], 0)

    def test_change_queue_mode_stays_separate_from_normal_scan(self):
        queue = []
        status = {"running": True, "current_task": "Other", "queued": []}
        with (
            patch.object(monitor, "monitor_queue", queue),
            patch.object(monitor, "monitor_status", status),
            patch.object(monitor, "schedule_ui_state_push"),
            patch.object(monitor, "submit_background"),
        ):
            monitor.queue_monitor_job("影视监控", "manual")
            monitor.queue_monitor_job("影视监控", "change", payload={"mode": "change"})

        self.assertEqual(len(queue), 2)
        self.assertEqual([item.get("mode") for item in queue], ["scan", "change"])

    def test_change_queue_dispatches_change_executor(self):
        queue = [
            {
                "task_name": "影视监控",
                "trigger": "change",
                "payload": {"mode": "change"},
                "mode": "change",
                "merge_count": 0,
            }
        ]
        status = {"running": False, "current_task": "", "queued": []}
        with (
            patch.object(monitor, "monitor_queue", queue),
            patch.object(monitor, "monitor_status", status),
            patch.object(monitor, "_monitor_dispatch_pending", False),
            patch.object(monitor, "schedule_ui_state_push"),
            patch.object(monitor, "submit_background") as submit,
        ):
            asyncio.run(monitor.start_next_monitor_job())

        self.assertEqual(submit.call_args.args[0], monitor.run_monitor_change_task)
        self.assertEqual(submit.call_args.kwargs["label"], "monitor-change-job")

    def test_idle_queue_schedules_only_one_dispatcher_for_back_to_back_jobs(self):
        queue = []
        status = {"running": False, "current_task": "", "queued": []}
        with (
            patch.object(monitor, "monitor_queue", queue),
            patch.object(monitor, "monitor_status", status),
            patch.object(monitor, "_monitor_dispatch_pending", False),
            patch.object(monitor, "schedule_ui_state_push"),
            patch.object(monitor, "submit_background") as submit,
        ):
            monitor.queue_monitor_job("任务 A", "change", payload={"mode": "change"})
            monitor.queue_monitor_job("任务 B", "change", payload={"mode": "change"})

        self.assertEqual([item["task_name"] for item in queue], ["任务 A", "任务 B"])
        self.assertEqual(submit.call_count, 1)
        self.assertEqual(submit.call_args.args[0], monitor.start_next_monitor_job)

    def test_missing_scan_task_releases_dispatcher_and_continues_queue(self):
        queue = [
            {
                "task_name": "任务 B",
                "trigger": "change",
                "payload": {"mode": "change"},
                "mode": "change",
                "merge_count": 0,
            }
        ]
        status = {"running": False, "current_task": "", "queued": ["任务 B"]}
        with (
            patch.object(monitor, "monitor_queue", queue),
            patch.object(monitor, "monitor_status", status),
            patch.object(monitor, "_monitor_dispatch_pending", True),
            patch.object(monitor, "get_config", return_value={"monitor_tasks": []}),
            patch.object(monitor, "write_monitor_log", AsyncMock()),
            patch.object(monitor, "schedule_ui_state_push"),
            patch.object(monitor, "release_process_memory"),
            patch.object(monitor, "start_next_monitor_job", AsyncMock()) as start_next,
        ):
            asyncio.run(monitor.run_monitor_task("任务 A"))

        self.assertFalse(status["running"])
        start_next.assert_awaited_once()

    def test_invalid_scan_task_releases_dispatcher_and_continues_queue(self):
        task = self._task(name="任务 A")
        queue = [
            {
                "task_name": "任务 B",
                "trigger": "change",
                "payload": {"mode": "change"},
                "mode": "change",
                "merge_count": 0,
            }
        ]
        status = {"running": False, "current_task": "", "queued": ["任务 B"]}
        with (
            patch.object(monitor, "monitor_queue", queue),
            patch.object(monitor, "monitor_status", status),
            patch.object(monitor, "_monitor_dispatch_pending", True),
            patch.object(monitor, "get_config", return_value={"monitor_tasks": [task]}),
            patch.object(monitor, "validate_monitor_runtime_config", return_value="测试配置错误"),
            patch.object(monitor, "write_monitor_log", AsyncMock()),
            patch.object(monitor, "update_monitor_summary"),
            patch.object(monitor, "schedule_ui_state_push"),
            patch.object(monitor, "release_process_memory"),
            patch.object(monitor, "start_next_monitor_job", AsyncMock()) as start_next,
        ):
            asyncio.run(monitor.run_monitor_task("任务 A"))

        self.assertFalse(status["running"])
        start_next.assert_awaited_once()

    def test_legacy_scraper_action_table_migrates_snapshot_columns(self):
        legacy_path = os.path.join(self.tmpdir.name, "legacy.db")
        with sqlite3.connect(legacy_path) as conn:
            conn.execute(
                """
                CREATE TABLE scraper_job_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL,
                    action_index INTEGER NOT NULL DEFAULT 0,
                    provider TEXT NOT NULL DEFAULT '',
                    entry_id TEXT NOT NULL DEFAULT '',
                    is_dir INTEGER NOT NULL DEFAULT 0,
                    old_parent_id TEXT NOT NULL DEFAULT '',
                    old_name TEXT NOT NULL DEFAULT '',
                    old_path TEXT NOT NULL DEFAULT '',
                    new_parent_id TEXT NOT NULL DEFAULT '',
                    new_name TEXT NOT NULL DEFAULT '',
                    new_path TEXT NOT NULL DEFAULT '',
                    target_parent_path TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    status_detail TEXT NOT NULL DEFAULT '',
                    rollback_status TEXT NOT NULL DEFAULT '',
                    rollback_detail TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    response_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.commit()

        original_path = db.DB_PATH
        original_ensured = db._DB_ENSURED
        try:
            db.DB_PATH = legacy_path
            db._DB_ENSURED = False
            db.ensure_db()
            with sqlite3.connect(legacy_path) as conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(scraper_job_actions)")}
                event_tables = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'monitor_change_events'"
                ).fetchall()
            self.assertIn("file_size", columns)
            self.assertIn("remote_modified", columns)
            self.assertEqual(event_tables, [("monitor_change_events",)])
        finally:
            db.DB_PATH = original_path
            db._DB_ENSURED = False
            db.ensure_db()
            db._DB_ENSURED = original_ensured

    def test_startup_recovery_marks_unconfirmed_event_for_local_reconcile(self):
        cfg = self._cfg()
        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="rename",
            entries=[
                {
                    "id": "recover",
                    "path": "Media/Old.mkv",
                    "new_path": "Media/New.mkv",
                    "is_dir": False,
                    "size": 1024,
                }
            ],
            dedupe_key="startup-recovery",
            cfg=cfg,
        )

        recovery = monitor_changes.recover_monitor_change_events(cfg=cfg, enqueue=False)

        self.assertEqual(recovery["recovered"], 1)
        self.assertEqual(recovery["queued_tasks"], ["影视监控"])
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT status, needs_reconcile FROM monitor_change_events WHERE id = ?",
                (prepared["event_ids"][0],),
            ).fetchone()
        self.assertEqual(row, ("pending", 1))

    def test_monitor_change_counts_separate_pending_and_failed(self):
        cfg = self._cfg()
        first = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="delete",
            entries=[{"id": "pending", "path": "Media/Pending.mkv", "is_dir": False}],
            dedupe_key="count-pending",
            cfg=cfg,
        )
        second = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="delete",
            entries=[{"id": "failed", "path": "Media/Failed.mkv", "is_dir": False}],
            dedupe_key="count-failed",
            cfg=cfg,
        )
        third = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="copy",
            entries=[
                {
                    "id": "manual",
                    "path": "Outside/Unknown",
                    "new_path": "Media/Unknown",
                    "is_dir": True,
                }
            ],
            dedupe_key="count-manual",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(first, succeeded=True, enqueue=False)
        monitor_changes.confirm_monitor_change_events(second, succeeded=True, enqueue=False)
        monitor_changes.confirm_monitor_change_events(third, succeeded=True, enqueue=False)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE monitor_change_events SET status = 'failed' WHERE id = ?",
                (second["event_ids"][0],),
            )
            conn.execute(
                "UPDATE monitor_change_events SET status = 'manual_required' WHERE id = ?",
                (third["event_ids"][0],),
            )
            conn.commit()

        self.assertEqual(
            monitor_changes.get_monitor_change_counts(),
            {"影视监控": {"pending": 1, "failed": 1, "manual_required": 1}},
        )

    def test_cleanup_removes_only_expired_completed_events(self):
        cfg = self._cfg()
        completed = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="delete",
            entries=[{"id": "cleanup-completed", "path": "Media/Done.mkv", "is_dir": False}],
            dedupe_key="cleanup-completed",
            cfg=cfg,
        )
        pending = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="delete",
            entries=[{"id": "cleanup-pending", "path": "Media/Pending.mkv", "is_dir": False}],
            dedupe_key="cleanup-pending",
            cfg=cfg,
        )
        failed = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="delete",
            entries=[{"id": "cleanup-failed", "path": "Media/Failed.mkv", "is_dir": False}],
            dedupe_key="cleanup-failed",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(completed, succeeded=True, enqueue=False)
        monitor_changes.confirm_monitor_change_events(pending, succeeded=True, enqueue=False)
        monitor_changes.confirm_monitor_change_events(failed, succeeded=False, enqueue=False, error="remote")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE monitor_change_events SET status = 'completed', completed_at = ? WHERE id = ?",
                (monitor_changes.now_text(), completed["event_ids"][0]),
            )
            conn.execute(
                "UPDATE monitor_change_events SET status = 'failed', retry_count = 5, next_retry_at = 0, completed_at = '2000-01-01T00:00:00' WHERE id = ?",
                (failed["event_ids"][0],),
            )
            conn.commit()

        self.assertEqual(monitor_changes.cleanup_completed_monitor_change_events(days=30), 0)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE monitor_change_events SET completed_at = '2000-01-01T00:00:00' WHERE id = ?",
                (completed["event_ids"][0],),
            )
            conn.commit()
        # Only completed rows are eligible; pending and failed rows remain.
        self.assertEqual(monitor_changes.cleanup_completed_monitor_change_events(days=30), 1)
        with sqlite3.connect(self.db_path) as conn:
            statuses = conn.execute(
                "SELECT status FROM monitor_change_events ORDER BY id"
            ).fetchall()
        self.assertEqual(statuses, [("pending",), ("failed",)])

    def test_failed_event_at_retry_limit_is_not_requeued(self):
        cfg = self._cfg()
        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="delete",
            entries=[{"id": "retry-limit", "path": "Media/RetryLimit.mkv", "is_dir": False}],
            dedupe_key="retry-limit",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(prepared, succeeded=True, enqueue=False)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE monitor_change_events SET status = 'failed', retry_count = ?, next_retry_at = 0 WHERE id = ?",
                (monitor_changes.MONITOR_CHANGE_MAX_RETRIES, prepared["event_ids"][0]),
            )
            conn.commit()

        with patch.object(monitor_changes, "_enqueue_task_names") as enqueue:
            queued = monitor_changes.queue_ready_monitor_change_tasks(cfg=cfg)
        result = asyncio.run(
            monitor_changes.process_monitor_change_events(cfg=cfg, event_ids=prepared["event_ids"])
        )

        self.assertEqual(queued, [])
        enqueue.assert_not_called()
        self.assertEqual(result["completed"], 0)
        self.assertEqual(result["failed"], 0)

    def test_startup_removes_historical_scraper_sync_failures_only(self):
        cfg = self._cfg()
        scraper_event = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="rename",
            entries=[
                {
                    "id": "historical-scraper",
                    "old_path": "Media/Old.mkv",
                    "new_path": "Media/New.mkv",
                    "is_dir": False,
                }
            ],
            source_action="scraper-job:historical:forward",
            dedupe_key="historical-scraper-failure",
            cfg=cfg,
        )
        ordinary_event = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="delete",
            entries=[{"id": "ordinary", "old_path": "Media/Ordinary.mkv", "is_dir": False}],
            source_action="direct:delete",
            dedupe_key="ordinary-failure",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(scraper_event, succeeded=True, enqueue=False)
        monitor_changes.confirm_monitor_change_events(ordinary_event, succeeded=True, enqueue=False)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE monitor_change_events
                SET status = 'failed', retry_count = 1, next_retry_at = ?,
                    processor_revision = ?
                """,
                (9999999999, monitor_changes.MONITOR_CHANGE_HANDLER_REVISION),
            )
            conn.commit()

        recovery = monitor_changes.recover_monitor_change_events(cfg=cfg, enqueue=False)

        self.assertEqual(recovery["recovered"], 0)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT source_action, status, retry_count FROM monitor_change_events ORDER BY id"
            ).fetchall()
        self.assertEqual(rows, [("direct:delete", "failed", 1)])

    def test_failed_event_at_retry_limit_is_requeued_after_handler_upgrade(self):
        cfg = self._cfg()
        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="delete",
            entries=[{"id": "retry-upgrade", "path": "Media/RetryUpgrade.mkv", "is_dir": False}],
            dedupe_key="retry-upgrade",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(prepared, succeeded=True, enqueue=False)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE monitor_change_events SET status = 'failed', retry_count = ?, next_retry_at = 0 WHERE id = ?",
                (monitor_changes.MONITOR_CHANGE_MAX_RETRIES, prepared["event_ids"][0]),
            )
            conn.commit()

        recovery = monitor_changes.recover_monitor_change_events(cfg=cfg, enqueue=False)

        self.assertEqual(recovery["recovered"], 1)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT status, retry_count, processor_revision FROM monitor_change_events WHERE id = ?",
                (prepared["event_ids"][0],),
            ).fetchone()
        self.assertEqual(
            row,
            ("pending", 0, monitor_changes.MONITOR_CHANGE_HANDLER_REVISION),
        )

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE monitor_change_events SET status = 'failed', retry_count = ? WHERE id = ?",
                (monitor_changes.MONITOR_CHANGE_MAX_RETRIES, prepared["event_ids"][0]),
            )
            conn.commit()

        second_recovery = monitor_changes.recover_monitor_change_events(cfg=cfg, enqueue=False)

        self.assertEqual(second_recovery["recovered"], 0)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT status, retry_count, processor_revision FROM monitor_change_events WHERE id = ?",
                (prepared["event_ids"][0],),
            ).fetchone()
        self.assertEqual(
            row,
            (
                "failed",
                monitor_changes.MONITOR_CHANGE_MAX_RETRIES,
                monitor_changes.MONITOR_CHANGE_HANDLER_REVISION,
            ),
        )

    def test_startup_discards_legacy_scraper_failure_instead_of_replaying(self):
        cfg = self._cfg(self._task(scan_path="/115/Media", target_path="媒体库"))
        old_local = "媒体库/Media/OldFolder/Old.mkv"
        intermediate_local = "媒体库/Media/NewFolder/Old.mkv"
        new_local = "媒体库/Media/NewFolder/New.mkv"
        self._insert_monitor_file("影视监控", old_local, "OldFolder/Old.mkv", size=4096)
        self._write_strm(old_local, "old")
        source_action = "scraper-job:legacy-parent-child:forward"
        parent = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="move",
            entries=[
                {
                    "id": "legacy-folder",
                    "old_path": "Media/OldFolder",
                    "new_path": "Media/NewFolder",
                    "old_parent_id": "media-root",
                    "new_parent_id": "media-root",
                    "is_dir": True,
                }
            ],
            source_action=source_action,
            dedupe_key="legacy-parent",
            cfg=cfg,
        )
        child = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="move",
            entries=[
                {
                    "id": "legacy-file",
                    "old_path": "Media/OldFolder/Old.mkv",
                    "new_path": "Media/NewFolder/New.mkv",
                    "old_parent_id": "legacy-folder",
                    "new_parent_id": "legacy-folder",
                    "is_dir": False,
                    "size": 4096,
                }
            ],
            source_action=source_action,
            dedupe_key="legacy-child",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(parent, succeeded=True, enqueue=False)
        monitor_changes.confirm_monitor_change_events(child, succeeded=True, enqueue=False)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE monitor_files
                SET local_rel_path = ?, remote_rel_path = ?
                WHERE task_name = ? AND local_rel_path = ?
                """,
                (intermediate_local, "NewFolder/Old.mkv", "影视监控", old_local),
            )
            conn.execute(
                "UPDATE monitor_change_events SET status = 'completed' WHERE id = ?",
                (parent["event_ids"][0],),
            )
            conn.execute(
                """
                UPDATE monitor_change_events
                SET status = 'failed', retry_count = ?, next_retry_at = 0, processor_revision = 0
                WHERE id = ?
                """,
                (monitor_changes.MONITOR_CHANGE_MAX_RETRIES, child["event_ids"][0]),
            )
            conn.commit()
        os.makedirs(os.path.dirname(self._strm_path(intermediate_local)), exist_ok=True)
        os.replace(self._strm_path(old_local), self._strm_path(intermediate_local))
        self.assertTrue(os.path.exists(self._strm_path(intermediate_local)))

        recovery = monitor_changes.recover_monitor_change_events(cfg=cfg, enqueue=False)
        self.assertEqual(recovery["recovered"], 0)
        with patch.object(monitor_changes, "STRM_ROOT", self.strm_root):
            second = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))

        self.assertEqual(second["completed"], 0)
        self.assertEqual(second["failed"], 0)
        self.assertTrue(os.path.exists(self._strm_path(intermediate_local)))
        self.assertFalse(os.path.exists(self._strm_path(new_local)))
        with sqlite3.connect(self.db_path) as conn:
            child_row = conn.execute(
                "SELECT status FROM monitor_change_events WHERE id = ?",
                (child["event_ids"][0],),
            ).fetchone()
        self.assertIsNone(child_row)

    def test_monitor_task_cards_render_pending_and_failed_change_counts(self):
        source = INDEX_JS_PATH.read_text(encoding="utf-8")

        self.assertIn("change_counts: state?.change_counts", source)
        self.assertIn("monitorState.change_counts", source)
        self.assertIn("待同步", source)
        self.assertIn("同步失败", source)
        self.assertIn("需手动监控", source)

    def test_scraper_frontend_explains_manual_required_sync_status(self):
        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")

        self.assertIn("sync.status === 'manual_required'", source)
        self.assertIn("需手动监控", source)

    def test_monitor_change_task_summary_reports_manual_required_count(self):
        cfg = self._cfg()
        logs = AsyncMock()
        with (
            patch.object(monitor, "_claim_monitor_job", return_value=True),
            patch.object(monitor, "get_config", return_value=cfg),
            patch.object(monitor, "write_monitor_task_header", AsyncMock()),
            patch.object(monitor, "write_monitor_section", AsyncMock()),
            patch.object(monitor, "write_monitor_log", logs),
            patch.object(monitor, "write_monitor_task_footer", AsyncMock()),
            patch.object(monitor, "update_monitor_summary"),
            patch.object(monitor, "schedule_ui_state_push"),
            patch.object(monitor, "_finish_monitor_job", AsyncMock()),
            patch.object(
                monitor_changes,
                "process_monitor_change_events",
                AsyncMock(
                    return_value={
                        "completed": 2,
                        "failed": 0,
                        "generated": 1,
                        "deleted": 0,
                        "directory_count": 0,
                        "file_count": 1,
                        "manual_required": 2,
                        "errors": [],
                        "change_details": [
                            {
                                "kind": "file",
                                "changes": [
                                    {
                                        "action": "delete",
                                        "path": "媒体库/旧\r\n名称.mkv.strm",
                                    },
                                    {
                                        "action": "generate",
                                        "path": "媒体库/新名称.mkv.strm",
                                    },
                                ],
                            },
                            {
                                "kind": "folder",
                                "operation": "move",
                                "old_path": "媒体库/旧目录",
                                "new_path": "媒体库/新目录",
                                "deleted": 2,
                                "generated": 2,
                            },
                        ],
                    }
                ),
            ),
        ):
            asyncio.run(monitor.run_monitor_change_task("影视监控", payload={"event_ids": [1, 2]}))

        self.assertEqual(
            [(str(call.args[0]), str(call.args[1])) for call in logs.await_args_list],
            [
                ("删除 STRM: 媒体库/旧 名称.mkv.strm", "info"),
                ("生成 STRM: 媒体库/新名称.mkv.strm", "success"),
                ("文件夹变更: 媒体库/旧目录 -> 媒体库/新目录（删除 2，生成 2）", "info"),
                (
                    "变更同步汇总: 完成 2，失败 0，生成 1，删除 0，"
                    "局部读取目录 0，文件 1，需手动监控 2",
                    "warn",
                ),
            ],
        )

    def test_monitor_change_task_logs_one_shot_failure_without_retry_claim(self):
        cfg = self._cfg()
        logs = AsyncMock()
        with (
            patch.object(monitor, "_claim_monitor_job", return_value=True),
            patch.object(monitor, "get_config", return_value=cfg),
            patch.object(monitor, "write_monitor_task_header", AsyncMock()),
            patch.object(monitor, "write_monitor_section", AsyncMock()),
            patch.object(monitor, "write_monitor_log", logs),
            patch.object(monitor, "write_monitor_task_footer", AsyncMock()),
            patch.object(monitor, "update_monitor_summary"),
            patch.object(monitor, "schedule_ui_state_push"),
            patch.object(monitor, "_finish_monitor_job", AsyncMock()),
            patch.object(
                monitor_changes,
                "process_monitor_change_events",
                AsyncMock(
                    return_value={
                        "completed": 0,
                        "failed": 1,
                        "generated": 0,
                        "deleted": 0,
                        "directory_count": 0,
                        "file_count": 0,
                        "manual_required": 0,
                        "errors": [
                            {
                                "event_id": 42,
                                "error": "local write failed",
                                "retryable": False,
                            }
                        ],
                        "change_details": [],
                    }
                ),
            ),
        ):
            asyncio.run(monitor.run_monitor_change_task("影视监控", payload={"event_ids": [42]}))

        messages = [(str(call.args[0]), str(call.args[1])) for call in logs.await_args_list]
        self.assertIn(("变更事件 #42 失败: local write failed", "error"), messages)
        self.assertFalse(any("已保留重试" in message for message, _level in messages))

    def test_real_batch_plan_canonicalizes_relative_paths_and_renames_three_nested_files_without_remote_listing(self):
        task = self._task(scan_path="/115/一级", target_path="媒体库")
        cfg = self._cfg(task)
        entries = [
            {
                "id": f"batch-{episode}",
                "name": f"Example.S01E{episode:02d}.mkv",
                "is_dir": False,
                "parent_id": "second-level-cid",
                "parent_path": "一级/二级",
                "path": f"Example.S01E{episode:02d}.mkv",
                "size": 8192,
                "modified_at": "2026-08-09 10:00:00",
            }
            for episode in range(1, 4)
        ]
        payload = {
            "provider": "115",
            "base_cid": "second-level-cid",
            "base_path": "一级/二级",
            "entries": entries,
            "tmdb": {
                "id": 42,
                "media_type": "tv",
                "title": "示例剧",
                "year": "2024",
                "total_episodes": 3,
                "total_seasons": 1,
            },
            "options": {
                "selection_mode": "contents",
                "season": 1,
                "title_language": "zh",
            },
        }
        with (
            patch.object(scraper, "_require_scraper_operation"),
            patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
            patch.object(scraper, "_walk_existing_folder", return_value=("second-level-cid", True)),
            patch.object(scraper, "_target_name_exists", return_value=False),
        ):
            plan = scraper.build_scraper_rename_plan(payload)

        self.assertTrue(plan["ready"])
        self.assertEqual(len(plan["actions"]), 3)
        for action in plan["actions"]:
            old_local = f"媒体库/一级/二级/{action['old_name']}"
            self._insert_monitor_file(
                "影视监控",
                old_local,
                f"二级/{action['old_name']}",
                size=action["file_size"],
            )
            self._write_strm(old_local, "old")

        job_id = scraper._insert_scraper_job("115", plan, plan["options"], plan["tmdb"])
        with (
            patch.object(scraper, "get_config", return_value=cfg),
            patch.object(scraper, "_require_scraper_operation"),
            patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
            patch.object(scraper, "_target_name_exists", return_value=False),
            patch.object(scraper, "_rename_provider_entry", return_value={"state": True}),
            patch.object(scraper, "_invalidate_provider_parent"),
            patch.object(monitor_changes, "_enqueue_task_names"),
        ):
            scraper.run_scraper_job(job_id)

        with (
            patch.object(monitor_changes, "STRM_ROOT", self.strm_root),
            patch.object(
                monitor_changes,
                "list_remote_dir",
                AsyncMock(side_effect=AssertionError("known batch file renames must not list 115 directories")),
            ),
        ):
            result = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))

        self.assertEqual(result["completed"], 3)
        self.assertEqual(result["deleted"], 3)
        self.assertEqual(result["generated"], 3)
        self.assertTrue(os.path.isdir(os.path.join(self.strm_root, "媒体库/一级/二级")))
        with sqlite3.connect(self.db_path) as conn:
            event_paths = conn.execute(
                "SELECT old_path, new_path FROM monitor_change_events ORDER BY id"
            ).fetchall()
            indexed = conn.execute(
                "SELECT local_rel_path, remote_rel_path FROM monitor_files ORDER BY local_rel_path"
            ).fetchall()

        expected_index = []
        for action in plan["actions"]:
            self.assertEqual(action["old_path"], f"一级/二级/{action['old_name']}")
            self.assertEqual(action["new_path"], f"一级/二级/{action['new_name']}")
            old_local = f"媒体库/一级/二级/{action['old_name']}"
            new_local = f"媒体库/一级/二级/{action['new_name']}"
            self.assertFalse(os.path.exists(self._strm_path(old_local)))
            with open(self._strm_path(new_local), "r", encoding="utf-8") as handle:
                self.assertEqual(
                    handle.read(),
                    core.build_strm_play_url(cfg, f"/115/{action['new_path']}"),
                )
            expected_index.append((new_local, f"二级/{action['new_name']}"))

        self.assertEqual(
            event_paths,
            [(action["old_path"], action["new_path"]) for action in plan["actions"]],
        )
        self.assertEqual(indexed, sorted(expected_index))
        self.assertEqual(
            result.get("change_details"),
            [
                {
                    "kind": "file",
                    "changes": [
                        {
                            "action": "delete",
                            "path": f"媒体库/一级/二级/{action['old_name']}.strm",
                        },
                        {
                            "action": "generate",
                            "path": f"媒体库/一级/二级/{action['new_name']}.strm",
                        },
                    ],
                }
                for action in plan["actions"]
            ],
        )

    def test_batch_folder_rename_rebases_child_event_and_keeps_rename_semantics(self):
        cfg = self._cfg(self._task(scan_path="/115/Media", target_path="媒体库"))
        old_local = "媒体库/Media/OldFolder/Old.mkv"
        new_local = "媒体库/Media/NewFolder/New.mkv"
        self._insert_monitor_file("影视监控", old_local, "OldFolder/Old.mkv", size=4096)
        self._write_strm(old_local, "old")
        plan = {
            "base_cid": "media-root",
            "base_path": "Media",
            "actions": [
                {
                    "action_index": 1,
                    "entry_id": "folder-entry",
                    "is_dir": True,
                    "old_parent_id": "media-root",
                    "old_name": "OldFolder",
                    "old_path": "Media/OldFolder",
                    "new_parent_id": "media-root",
                    "new_name": "NewFolder",
                    "new_path": "Media/NewFolder",
                    "target_parent_path": "Media",
                    "file_size": 0,
                    "remote_modified": "2026-08-10 10:00:00",
                    "ready": True,
                },
                {
                    "action_index": 2,
                    "entry_id": "file-entry",
                    "is_dir": False,
                    "old_parent_id": "folder-entry",
                    "old_name": "Old.mkv",
                    "old_path": "Media/OldFolder/Old.mkv",
                    "new_parent_id": "",
                    "new_name": "New.mkv",
                    "new_path": "Media/NewFolder/New.mkv",
                    "target_parent_path": "NewFolder",
                    "file_size": 4096,
                    "remote_modified": "2026-08-10 10:00:00",
                    "ready": True,
                },
            ],
        }
        job_id = scraper._insert_scraper_job("115", plan, {"base_path": "Media"}, {})

        with (
            patch.object(scraper, "get_config", return_value=cfg),
            patch.object(scraper, "_require_scraper_operation"),
            patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
            patch.object(scraper, "_target_name_exists", return_value=False),
            patch.object(scraper, "_ensure_folder_from_base", return_value="folder-entry"),
            patch.object(scraper, "_rename_provider_entry", return_value={"state": True}),
            patch.object(scraper, "_invalidate_provider_parent"),
            patch.object(monitor_changes, "_enqueue_task_names"),
        ):
            scraper.run_scraper_job(job_id)

        with sqlite3.connect(self.db_path) as conn:
            events = conn.execute(
                "SELECT operation, old_path, new_path FROM monitor_change_events ORDER BY id"
            ).fetchall()

        self.assertEqual(
            events,
            [
                ("rename", "Media/OldFolder", "Media/NewFolder"),
                ("rename", "Media/NewFolder/Old.mkv", "Media/NewFolder/New.mkv"),
            ],
        )
        with patch.object(monitor_changes, "STRM_ROOT", self.strm_root):
            result = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))
        self.assertEqual(result["completed"], 2)
        self.assertFalse(os.path.exists(self._strm_path(old_local)))
        self.assertTrue(os.path.exists(self._strm_path(new_local)))

    def test_batch_folder_rename_rollback_rebases_child_event_before_folder(self):
        cfg = self._cfg(self._task(scan_path="/115/Media", target_path="媒体库"))
        old_local = "媒体库/Media/OldFolder/Old.mkv"
        new_local = "媒体库/Media/NewFolder/New.mkv"
        self._insert_monitor_file("影视监控", old_local, "OldFolder/Old.mkv", size=4096)
        self._write_strm(old_local, "old")
        plan = {
            "base_cid": "media-root",
            "base_path": "Media",
            "actions": [
                {
                    "action_index": 1,
                    "entry_id": "folder-entry",
                    "is_dir": True,
                    "old_parent_id": "media-root",
                    "old_name": "OldFolder",
                    "old_path": "Media/OldFolder",
                    "new_parent_id": "media-root",
                    "new_name": "NewFolder",
                    "new_path": "Media/NewFolder",
                    "target_parent_path": "Media",
                    "file_size": 0,
                    "remote_modified": "2026-08-10 10:00:00",
                    "ready": True,
                },
                {
                    "action_index": 2,
                    "entry_id": "file-entry",
                    "is_dir": False,
                    "old_parent_id": "folder-entry",
                    "old_name": "Old.mkv",
                    "old_path": "Media/OldFolder/Old.mkv",
                    "new_parent_id": "",
                    "new_name": "New.mkv",
                    "new_path": "Media/NewFolder/New.mkv",
                    "target_parent_path": "NewFolder",
                    "file_size": 4096,
                    "remote_modified": "2026-08-10 10:00:00",
                    "ready": True,
                },
            ],
        }
        job_id = scraper._insert_scraper_job("115", plan, {"base_path": "Media"}, {})

        common_patches = (
            patch.object(scraper, "get_config", return_value=cfg),
            patch.object(scraper, "_require_scraper_operation"),
            patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
            patch.object(scraper, "_target_name_exists", return_value=False),
            patch.object(scraper, "_ensure_folder_from_base", return_value="folder-entry"),
            patch.object(scraper, "_rename_provider_entry", return_value={"state": True}),
            patch.object(scraper, "_invalidate_provider_parent"),
            patch.object(monitor_changes, "_enqueue_task_names"),
        )
        with ExitStack() as stack:
            for context in common_patches:
                stack.enter_context(context)
            scraper.run_scraper_job(job_id)
        with patch.object(monitor_changes, "STRM_ROOT", self.strm_root):
            forward_result = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))
        self.assertEqual(forward_result["completed"], 2)

        with ExitStack() as stack:
            for context in common_patches:
                stack.enter_context(context)
            scraper.rollback_scraper_job(job_id)

        with sqlite3.connect(self.db_path) as conn:
            rollback_events = conn.execute(
                """
                SELECT operation, old_path, new_path
                FROM monitor_change_events
                WHERE source_action = ?
                ORDER BY id
                """,
                (f"scraper-job:{job_id}:rollback",),
            ).fetchall()
        self.assertEqual(
            rollback_events,
            [
                ("rename", "Media/NewFolder/New.mkv", "Media/NewFolder/Old.mkv"),
                ("rename", "Media/NewFolder", "Media/OldFolder"),
            ],
        )
        with patch.object(monitor_changes, "STRM_ROOT", self.strm_root):
            rollback_result = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))
        self.assertEqual(rollback_result["completed"], 2)
        self.assertTrue(os.path.exists(self._strm_path(old_local)))
        self.assertFalse(os.path.exists(self._strm_path(new_local)))

    def test_batch_scraper_forward_and_rollback_use_stable_event_keys(self):
        cfg = self._cfg()
        payload = {
            "provider": "115",
            "base_cid": "parent",
            "base_path": "Media",
            "entries": [
                {
                    "id": "batch-file",
                    "name": "Example.S01E01.mkv",
                    "is_dir": False,
                    "parent_id": "parent",
                    "parent_path": "Media",
                    "path": "Media/Example.S01E01.mkv",
                    "size": 8192,
                    "modified_at": "2026-08-09 10:00:00",
                }
            ],
            "tmdb": {
                "id": 42,
                "media_type": "tv",
                "title": "示例剧",
                "year": "2024",
                "total_episodes": 1,
                "total_seasons": 1,
            },
            "options": {
                "selection_mode": "contents",
                "season": 1,
                "title_language": "zh",
            },
        }
        with (
            patch.object(scraper, "_require_scraper_operation"),
            patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
            patch.object(scraper, "_walk_existing_folder", return_value=("parent", True)),
            patch.object(scraper, "_target_name_exists", return_value=False),
        ):
            plan = scraper.build_scraper_rename_plan(payload)
        self.assertTrue(plan["ready"])
        action = plan["actions"][0]
        job_id = scraper._insert_scraper_job("115", plan, plan["options"], plan["tmdb"])

        with (
            patch.object(scraper, "get_config", return_value=cfg),
            patch.object(scraper, "_require_scraper_operation"),
            patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
            patch.object(scraper, "_target_name_exists", return_value=False),
            patch.object(scraper, "_rename_provider_entry", return_value={"state": True}),
            patch.object(scraper, "_invalidate_provider_parent"),
            patch.object(monitor_changes, "_enqueue_task_names"),
        ):
            scraper.run_scraper_job(job_id)
            scraper.rollback_scraper_job(job_id)

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT dedupe_key, old_path, new_path, status
                FROM monitor_change_events
                ORDER BY id
                """
            ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertIn(f"scraper-job:{job_id}:action:", rows[0][0])
        self.assertTrue(rows[0][0].endswith(f":forward:{action['old_path']}"))
        self.assertNotIn("batch-file", rows[0][0])
        self.assertEqual(rows[0][1:3], (action["old_path"], action["new_path"]))
        self.assertTrue(rows[1][0].endswith(f":rollback:{action['new_path']}"))
        self.assertNotIn("batch-file", rows[1][0])
        self.assertEqual(rows[1][1:3], (action["new_path"], action["old_path"]))

    def test_legacy_pending_batch_action_uses_saved_base_path_for_monitor_event(self):
        cfg = self._cfg(self._task(scan_path="/115/一级", target_path="媒体库"))
        plan = {
            "base_cid": "second-level-cid",
            "actions": [
                {
                    "action_index": 1,
                    "entry_id": "legacy-file",
                    "is_dir": False,
                    "old_parent_id": "second-level-cid",
                    "old_name": "Old.mkv",
                    "old_path": "一级/二级/Old.mkv",
                    "new_parent_id": "second-level-cid",
                    "new_name": "New.mkv",
                    "new_path": "New.mkv",
                    "target_parent_path": "",
                    "file_size": 8192,
                    "remote_modified": "2026-08-09 10:00:00",
                    "ready": True,
                }
            ],
        }
        job_id = scraper._insert_scraper_job(
            "115",
            plan,
            {"base_path": "一级/二级"},
            {},
        )

        with (
            patch.object(scraper, "get_config", return_value=cfg),
            patch.object(scraper, "_require_scraper_operation"),
            patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
            patch.object(scraper, "_target_name_exists", return_value=False),
            patch.object(scraper, "_rename_provider_entry", return_value={"state": True}),
            patch.object(scraper, "_invalidate_provider_parent"),
            patch.object(monitor_changes, "_enqueue_task_names"),
        ):
            scraper.run_scraper_job(job_id)

        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT old_path, new_path FROM monitor_change_events WHERE source_action = ?",
                (f"scraper-job:{job_id}:forward",),
            ).fetchone()
        self.assertEqual(row, ("一级/二级/Old.mkv", "一级/二级/New.mkv"))

    def test_batch_noop_action_does_not_create_monitor_event(self):
        cfg = self._cfg()
        plan = {
            "base_cid": "parent",
            "actions": [
                {
                    "action_index": 1,
                    "entry_id": "noop-file",
                    "is_dir": False,
                    "old_parent_id": "parent",
                    "old_name": "Same.mkv",
                    "old_path": "Media/Same.mkv",
                    "new_parent_id": "parent",
                    "new_name": "Same.mkv",
                    "new_path": "Media/Same.mkv",
                    "target_parent_path": "Media",
                    "ready": True,
                }
            ],
        }
        job_id = scraper._insert_scraper_job("115", plan, {}, {})

        with (
            patch.object(scraper, "get_config", return_value=cfg),
            patch.object(scraper, "_require_scraper_operation"),
            patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
            patch.object(scraper, "_target_name_exists", side_effect=AssertionError("no-op must not query target")),
            patch.object(scraper, "_rename_provider_entry", side_effect=AssertionError("no-op must not rename")),
            patch.object(scraper, "_move_provider_entries", side_effect=AssertionError("no-op must not move")),
            patch.object(scraper, "_invalidate_provider_parent"),
            patch.object(monitor_changes, "_enqueue_task_names"),
        ):
            scraper.run_scraper_job(job_id)

        with sqlite3.connect(self.db_path) as conn:
            event_count = conn.execute("SELECT COUNT(1) FROM monitor_change_events").fetchone()[0]
            action_status = conn.execute(
                "SELECT status FROM scraper_job_actions WHERE job_id = ?",
                (job_id,),
            ).fetchone()[0]
        self.assertEqual(event_count, 0)
        self.assertEqual(action_status, "skipped")

    def test_batch_folder_events_keep_paths_without_ids_in_both_directions(self):
        cfg = self._cfg()
        action = {
            "id": 88,
            "entry_id": "batch-folder-cid",
            "is_dir": True,
            "old_parent_id": "old-parent-cid",
            "old_name": "Old",
            "old_path": "Media/Old",
            "new_parent_id": "new-parent-cid",
            "new_name": "New",
            "new_path": "Media/New",
            "file_size": 0,
            "remote_modified": "2026-08-09 10:00:00",
        }
        with patch.object(scraper, "get_config", return_value=cfg):
            forward = scraper._prepare_scraper_job_action_monitor_sync("115", 41, action)
            rollback = scraper._prepare_scraper_job_action_monitor_sync("115", 41, action, reverse=True)

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT old_path, new_path, entry_snapshot_json FROM monitor_change_events ORDER BY id"
            ).fetchall()
        self.assertEqual(rows[0][0:2], ("Media/Old", "Media/New"))
        self.assertEqual(rows[1][0:2], ("Media/New", "Media/Old"))
        forward_snapshot = json.loads(rows[0][2])
        rollback_snapshot = json.loads(rows[1][2])
        self.assertEqual(
            (forward_snapshot["old_path"], forward_snapshot["new_path"], forward_snapshot["name"]),
            ("Media/Old", "Media/New", "Old"),
        )
        self.assertEqual(
            (rollback_snapshot["old_path"], rollback_snapshot["new_path"], rollback_snapshot["name"]),
            ("Media/New", "Media/Old", "New"),
        )
        for snapshot in (forward_snapshot, rollback_snapshot):
            self.assertNotIn("id", snapshot)
            self.assertNotIn("old_parent_id", snapshot)
            self.assertNotIn("new_parent_id", snapshot)
            self.assertNotIn("old_cid", snapshot)
            self.assertNotIn("new_cid", snapshot)
        self.assertEqual(forward["event_count"], 1)
        self.assertEqual(rollback["event_count"], 1)

    def test_continuous_renames_merge_and_confirmation_is_idempotent(self):
        cfg = self._cfg()
        first = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="rename",
            entries=[
                {"id": "chain", "path": "Media/A.mkv", "new_path": "Media/B.mkv", "is_dir": False}
            ],
            source_action="direct:chain",
            dedupe_key="chain-one",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(first, succeeded=True, enqueue=False)
        second = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="rename",
            entries=[
                {"id": "chain", "path": "Media/B.mkv", "new_path": "Media/C.mkv", "is_dir": False}
            ],
            source_action="direct:chain",
            dedupe_key="chain-two",
            cfg=cfg,
        )
        confirmed = monitor_changes.confirm_monitor_change_events(second, succeeded=True, enqueue=False)
        monitor_changes.confirm_monitor_change_events(second, succeeded=True, enqueue=False)

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT old_path, new_path, status, last_error FROM monitor_change_events ORDER BY id"
            ).fetchall()
        self.assertEqual(rows[0][0:3], ("Media/A.mkv", "Media/B.mkv", "completed"))
        self.assertEqual(rows[1][0:3], ("Media/A.mkv", "Media/C.mkv", "pending"))
        self.assertIn("merged_into", rows[0][3])
        self.assertEqual(confirmed["event_count"], 1)

    def test_pending_forward_and_rollback_chain_collapses_without_local_change(self):
        cfg = self._cfg()
        old_local = "媒体库/Media/A.mkv"
        self._insert_monitor_file("影视监控", old_local, "A.mkv", size=4096)
        target = self._write_strm(old_local, "original")
        forward = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="move",
            entries=[
                {
                    "id": "forward-rollback",
                    "old_path": "Media/A.mkv",
                    "new_path": "Media/B.mkv",
                    "old_parent_id": "media-parent",
                    "new_parent_id": "media-parent",
                    "is_dir": False,
                    "size": 4096,
                }
            ],
            source_action="scraper-job:1:forward",
            dedupe_key="forward-chain",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(forward, succeeded=True, enqueue=False)
        rollback = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="move",
            entries=[
                {
                    "id": "forward-rollback",
                    "old_path": "Media/B.mkv",
                    "new_path": "Media/A.mkv",
                    "old_parent_id": "media-parent",
                    "new_parent_id": "media-parent",
                    "is_dir": False,
                    "size": 4096,
                }
            ],
            source_action="scraper-job:1:rollback",
            dedupe_key="rollback-chain",
            cfg=cfg,
        )
        confirmed = monitor_changes.confirm_monitor_change_events(
            rollback,
            succeeded=True,
            enqueue=False,
        )

        self.assertEqual(confirmed["status"], "completed")
        with sqlite3.connect(self.db_path) as conn:
            statuses = conn.execute(
                "SELECT status FROM monitor_change_events ORDER BY id"
            ).fetchall()
            rows = conn.execute(
                "SELECT local_rel_path, remote_rel_path FROM monitor_files"
            ).fetchall()
        self.assertEqual(statuses, [("completed",), ("completed",)])
        self.assertEqual(rows, [(old_local, "A.mkv")])
        with open(target, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "original")

    def test_recovered_processing_event_is_not_collapsed_with_rollback_chain(self):
        cfg = self._cfg()
        old_local = "媒体库/Media/A.mkv"
        new_local = "媒体库/Media/B.mkv"
        self._insert_monitor_file("影视监控", old_local, "A.mkv", size=4096)
        self._write_strm(old_local, "original")
        forward = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="move",
            entries=[
                {
                    "id": "crashed-forward",
                    "old_path": "Media/A.mkv",
                    "new_path": "Media/B.mkv",
                    "old_parent_id": "media-parent",
                    "new_parent_id": "media-parent",
                    "is_dir": False,
                    "size": 4096,
                }
            ],
            source_action="scraper-job:crashed:forward",
            dedupe_key="crashed-forward",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(forward, succeeded=True, enqueue=False)
        self._write_strm(new_local, "partially-written")
        os.remove(self._strm_path(old_local))
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE monitor_change_events SET status = 'processing' WHERE id = ?",
                (forward["event_ids"][0],),
            )
            conn.commit()

        monitor_changes.recover_monitor_change_events(cfg=cfg, enqueue=False)
        rollback = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="move",
            entries=[
                {
                    "id": "crashed-forward",
                    "old_path": "Media/B.mkv",
                    "new_path": "Media/A.mkv",
                    "old_parent_id": "media-parent",
                    "new_parent_id": "media-parent",
                    "is_dir": False,
                    "size": 4096,
                }
            ],
            source_action="scraper-job:crashed:rollback",
            dedupe_key="crashed-rollback",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(rollback, succeeded=True, enqueue=False)

        with sqlite3.connect(self.db_path) as conn:
            statuses = conn.execute(
                "SELECT status FROM monitor_change_events ORDER BY id"
            ).fetchall()
        self.assertEqual(statuses, [("pending",), ("pending",)])
        with patch.object(monitor_changes, "STRM_ROOT", self.strm_root):
            result = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))
        self.assertEqual(result["completed"], 2)
        self.assertTrue(os.path.exists(self._strm_path(old_local)))
        self.assertFalse(os.path.exists(self._strm_path(new_local)))
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT local_rel_path, remote_rel_path FROM monitor_files"
            ).fetchall()
        self.assertEqual(rows, [(old_local, "A.mkv")])

    def test_pending_cross_directory_move_then_rename_keeps_original_parent_id(self):
        cfg = self._cfg()
        old_local = "媒体库/Media/A/Episode.mkv"
        new_local = "媒体库/Media/B/Renamed.mkv"
        self._insert_monitor_file("影视监控", old_local, "A/Episode.mkv", size=4096)
        self._write_strm(old_local, "old")
        first = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="move",
            entries=[
                {
                    "id": "move-rename-chain",
                    "old_path": "Media/A/Episode.mkv",
                    "new_path": "Media/B/Episode.mkv",
                    "old_parent_id": "parent-a",
                    "new_parent_id": "parent-b",
                    "is_dir": False,
                    "size": 4096,
                }
            ],
            source_action="scraper:entry:move",
            dedupe_key="move-rename-chain-one",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(first, succeeded=True, enqueue=False)
        second = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="rename",
            entries=[
                {
                    "id": "move-rename-chain",
                    "old_path": "Media/B/Episode.mkv",
                    "new_path": "Media/B/Renamed.mkv",
                    "old_parent_id": "parent-b",
                    "new_parent_id": "parent-b",
                    "is_dir": False,
                    "size": 4096,
                }
            ],
            source_action="scraper:entry:rename",
            dedupe_key="move-rename-chain-two",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(second, succeeded=True, enqueue=False)

        with sqlite3.connect(self.db_path) as conn:
            raw_snapshot = conn.execute(
                "SELECT entry_snapshot_json FROM monitor_change_events WHERE id = ?",
                (second["event_ids"][0],),
            ).fetchone()[0]
        snapshot = json.loads(raw_snapshot)
        self.assertEqual(snapshot["old_path"], "Media/A/Episode.mkv")
        self.assertEqual(snapshot["old_parent_id"], "parent-a")
        self.assertEqual(snapshot["new_parent_id"], "parent-b")
        with patch.object(monitor_changes, "STRM_ROOT", self.strm_root):
            result = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))
        self.assertEqual(result["completed"], 1)
        self.assertFalse(os.path.exists(self._strm_path(old_local)))
        self.assertTrue(os.path.exists(self._strm_path(new_local)))

    def test_continuous_folder_moves_merge_indexed_dirs_without_manual_required(self):
        cfg = self._cfg()
        old_local = "媒体库/Media/Source/Episode.mkv"
        self._insert_monitor_file(
            "影视监控",
            old_local,
            "Source/Episode.mkv",
            modified="source-modified",
            size=4096,
        )
        self._write_strm(old_local, "source")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO monitor_dirs(
                    task_name, dir_rel_path, remote_modified, entry_modified, needs_rescan, missing_confirmations
                ) VALUES (?, ?, ?, ?, 0, 0)
                """,
                ("影视监控", "Source", "source-modified", "source-entry"),
            )
            conn.commit()

        first = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="rename",
            entries=[
                {
                    "id": "folder-chain",
                    "path": "Media/Source",
                    "new_path": "Media/Mid",
                    "is_dir": True,
                    "old_parent_id": "media-parent",
                    "new_parent_id": "media-parent",
                }
            ],
            source_action="direct:folder-chain",
            dedupe_key="folder-chain-one",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(first, succeeded=True, enqueue=False)

        second = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="rename",
            entries=[
                {
                    "id": "folder-chain",
                    "path": "Media/Mid",
                    "new_path": "Media/Dest",
                    "is_dir": True,
                    "old_parent_id": "media-parent",
                    "new_parent_id": "media-parent",
                }
            ],
            source_action="direct:folder-chain",
            dedupe_key="folder-chain-two",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(second, succeeded=True, enqueue=False)

        with sqlite3.connect(self.db_path) as conn:
            raw_snapshot, status = conn.execute(
                "SELECT entry_snapshot_json, status FROM monitor_change_events WHERE id = ?",
                (second["event_ids"][0],),
            ).fetchone()
        snapshot = json.loads(raw_snapshot)
        self.assertEqual(status, "pending")
        self.assertEqual(snapshot["old_path"], "Media/Source")
        self.assertTrue(snapshot["manifest_known"])
        self.assertFalse(snapshot["manual_required"])
        self.assertEqual(snapshot["indexed_files"], [{"modified_at": "source-modified", "path": "Media/Source/Episode.mkv", "size": 4096}])
        self.assertEqual(
            snapshot["indexed_dirs"],
            [{"entry_modified": "source-entry", "path": "Media/Source", "remote_modified": "source-modified"}],
        )

    def test_processed_manual_required_folder_move_transfers_prompt_to_final_path(self):
        cfg = self._cfg()
        source_local = "媒体库/Media/Source/Episode.mkv"
        self._insert_monitor_file("影视监控", source_local, "Source/Episode.mkv", size=4096)
        self._write_strm(source_local, "source")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO monitor_dirs(
                    task_name, dir_rel_path, remote_modified, entry_modified, needs_rescan, missing_confirmations
                ) VALUES (?, ?, '', '', 1, 0)
                """,
                ("影视监控", "Source"),
            )
            conn.commit()

        first = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="move",
            entries=[
                {
                    "id": "manual-folder-chain",
                    "path": "Media/Source",
                    "new_path": "Media/Mid",
                    "is_dir": True,
                    "old_parent_id": "media-parent",
                    "new_parent_id": "media-parent",
                }
            ],
            source_action="scraper:entry:move",
            dedupe_key="manual-folder-chain-one",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(first, succeeded=True, enqueue=False)
        with patch.object(monitor_changes, "STRM_ROOT", self.strm_root):
            first_result = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))
        self.assertEqual(first_result["manual_required"], 1)
        self.assertTrue(os.path.exists(self._strm_path("媒体库/Media/Mid/Episode.mkv")))

        second = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="rename",
            entries=[
                {
                    "id": "manual-folder-chain",
                    "path": "Media/Mid",
                    "new_path": "Media/Dest",
                    "is_dir": True,
                    "old_parent_id": "media-parent",
                    "new_parent_id": "media-parent",
                }
            ],
            source_action="scraper:entry:rename",
            dedupe_key="manual-folder-chain-two",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(second, succeeded=True, enqueue=False)

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT old_path, new_path, status, entry_snapshot_json FROM monitor_change_events ORDER BY id"
            ).fetchall()
        final_snapshot = json.loads(rows[1][3])
        self.assertEqual(rows[0][2], "completed")
        self.assertEqual(rows[1][0:3], ("Media/Mid", "Media/Dest", "pending"))
        self.assertTrue(final_snapshot["manual_required"])
        self.assertFalse(final_snapshot["manifest_known"])
        self.assertEqual(final_snapshot["indexed_files"][0]["path"], "Media/Mid/Episode.mkv")

        with patch.object(monitor_changes, "STRM_ROOT", self.strm_root):
            second_result = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))
        self.assertEqual(second_result["manual_required"], 1)
        self.assertFalse(os.path.exists(self._strm_path("媒体库/Media/Mid/Episode.mkv")))
        self.assertTrue(os.path.exists(self._strm_path("媒体库/Media/Dest/Episode.mkv")))
        with sqlite3.connect(self.db_path) as conn:
            current_status = conn.execute(
                "SELECT status FROM monitor_change_events WHERE id = ?",
                (second["event_ids"][0],),
            ).fetchone()[0]
        self.assertEqual(current_status, "manual_required")

    def test_continuous_renames_with_different_entry_ids_do_not_merge(self):
        cfg = self._cfg()
        first = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="rename",
            entries=[{"id": "chain-a", "path": "Media/A.mkv", "new_path": "Media/B.mkv", "is_dir": False}],
            source_action="direct:chain-different-id",
            dedupe_key="chain-different-one",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(first, succeeded=True, enqueue=False)
        second = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="rename",
            entries=[{"id": "chain-b", "path": "Media/B.mkv", "new_path": "Media/C.mkv", "is_dir": False}],
            source_action="direct:chain-different-id",
            dedupe_key="chain-different-two",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(second, succeeded=True, enqueue=False)

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT old_path, new_path, status FROM monitor_change_events ORDER BY id"
            ).fetchall()
        self.assertEqual(
            rows,
            [("Media/A.mkv", "Media/B.mkv", "pending"), ("Media/B.mkv", "Media/C.mkv", "pending")],
        )

    def test_continuous_renames_without_entry_ids_do_not_merge(self):
        cfg = self._cfg()
        first = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="rename",
            entries=[{"path": "Media/A.mkv", "new_path": "Media/B.mkv", "is_dir": False}],
            source_action="direct:chain-no-id",
            dedupe_key="chain-no-id-one",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(first, succeeded=True, enqueue=False)
        second = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="rename",
            entries=[{"path": "Media/B.mkv", "new_path": "Media/C.mkv", "is_dir": False}],
            source_action="direct:chain-no-id",
            dedupe_key="chain-no-id-two",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(second, succeeded=True, enqueue=False)

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT old_path, new_path, status FROM monitor_change_events ORDER BY id"
            ).fetchall()
        self.assertEqual(
            rows,
            [("Media/A.mkv", "Media/B.mkv", "pending"), ("Media/B.mkv", "Media/C.mkv", "pending")],
        )

    def test_continuous_merge_preserves_reconcile_requirement_from_previous_event(self):
        cfg = self._cfg()
        first = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="rename",
            entries=[{"id": "chain-reconcile", "path": "Media/A.mkv", "new_path": "Media/B.mkv", "is_dir": False}],
            source_action="direct:chain-reconcile",
            dedupe_key="chain-reconcile-one",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(first, succeeded=False, enqueue=False, error="interrupted")
        second = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="rename",
            entries=[{"id": "chain-reconcile", "path": "Media/B.mkv", "new_path": "Media/C.mkv", "is_dir": False}],
            source_action="direct:chain-reconcile",
            dedupe_key="chain-reconcile-two",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(second, succeeded=True, enqueue=False)

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT old_path, new_path, status, needs_reconcile FROM monitor_change_events ORDER BY id"
            ).fetchall()
        self.assertEqual(rows[0][0:3], ("Media/A.mkv", "Media/B.mkv", "completed"))
        self.assertEqual(rows[1][0:3], ("Media/A.mkv", "Media/C.mkv", "pending"))
        self.assertEqual(rows[1][3], 1)

    def test_cross_monitor_move_removes_source_and_adds_destination(self):
        source_task = self._task(name="来源", scan_path="/115/Media", target_path="来源库")
        target_task = self._task(name="目标", scan_path="/115/Other", target_path="目标库")
        cfg = self._cfg(source_task, target_task)
        self._insert_monitor_file("来源", "来源库/Media/Movie.mkv", "Movie.mkv", size=4096)
        self._write_strm("来源库/Media/Movie.mkv", "source")

        with patch.object(
            monitor_changes,
            "list_remote_dir",
            AsyncMock(side_effect=AssertionError("cross-task file move must stay precise")),
        ):
            _, _, result = self._run_confirmed(
                cfg,
                "move",
                [
                    {
                        "id": "cross-file",
                        "name": "Movie.mkv",
                        "path": "Media/Movie.mkv",
                        "new_path": "Other/Movie.mkv",
                        "old_parent_id": "source-parent",
                        "new_parent_id": "target-parent",
                        "is_dir": False,
                        "size": 4096,
                    }
                ],
                dedupe_key="cross-task-file-move",
            )

        self.assertEqual(result["completed"], 2)
        self.assertFalse(os.path.exists(self._strm_path("来源库/Media/Movie.mkv")))
        self.assertTrue(os.path.exists(self._strm_path("目标库/Other/Movie.mkv")))
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT task_name, local_rel_path FROM monitor_files ORDER BY task_name"
            ).fetchall()
        self.assertEqual(rows, [("目标", "目标库/Other/Movie.mkv")])

    def test_cross_monitor_folder_move_reuses_source_manifest_and_baseline_without_listing(self):
        source_task = self._task(name="Source", scan_path="/115/Media/SourceRoot", target_path="源库")
        destination_task = self._task(
            name="Destination",
            scan_path="/115/Media/DestinationRoot",
            target_path="目标库",
        )
        cfg = self._cfg(source_task, destination_task)
        old_local = "源库/SourceRoot/Folder/Episode.mkv"
        new_local = "目标库/DestinationRoot/Folder/Episode.mkv"
        self._insert_monitor_file("Source", old_local, "Folder/Episode.mkv", size=4096)
        self._write_strm(old_local, "source")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO monitor_dirs(task_name, dir_rel_path, remote_modified, entry_modified, needs_rescan, missing_confirmations) VALUES (?, ?, ?, ?, 0, 0)",
                ("Source", "Folder", "folder-modified", "folder-entry-modified"),
            )
            conn.commit()

        with patch.object(
            monitor_changes,
            "list_remote_dir",
            AsyncMock(side_effect=AssertionError("indexed cross-monitor folders must not list 115")),
        ):
            _, _, result = self._run_confirmed(
                cfg,
                "move",
                [
                    {
                        "id": "cross-folder",
                        "name": "Folder",
                        "old_path": "Media/SourceRoot/Folder",
                        "new_path": "Media/DestinationRoot/Folder",
                        "old_parent_id": "source-parent",
                        "new_parent_id": "destination-parent",
                        "old_cid": "cross-folder",
                        "new_cid": "cross-folder",
                        "is_dir": True,
                    }
                ],
                dedupe_key="cross-monitor-folder-move",
            )

        self.assertEqual(result["completed"], 2)
        self.assertEqual(result["deleted"], 1)
        self.assertEqual(result["generated"], 1)
        self.assertFalse(os.path.exists(self._strm_path(old_local)))
        self.assertTrue(os.path.isfile(self._strm_path(new_local)))
        with sqlite3.connect(self.db_path) as conn:
            file_rows = conn.execute(
                "SELECT task_name, local_rel_path, remote_rel_path FROM monitor_files ORDER BY task_name"
            ).fetchall()
            dir_rows = conn.execute(
                "SELECT task_name, dir_rel_path, remote_modified, entry_modified, needs_rescan FROM monitor_dirs ORDER BY task_name, dir_rel_path"
            ).fetchall()
        self.assertEqual(file_rows, [("Destination", new_local, "Folder/Episode.mkv")])
        self.assertEqual(
            dir_rows,
            [("Destination", "Folder", "folder-modified", "folder-entry-modified", 0)],
        )

    def test_folder_rename_removes_only_indexed_strm_and_keeps_metadata(self):
        cfg = self._cfg()
        old_local = "媒体库/Media/OldFolder/Episode.mkv"
        self._insert_monitor_file("影视监控", old_local, "OldFolder/Episode.mkv", size=4096)
        self._write_strm(old_local, "old")
        metadata = os.path.join(self.strm_root, "媒体库/Media/OldFolder/subtitle.srt")
        os.makedirs(os.path.dirname(metadata), exist_ok=True)
        with open(metadata, "w", encoding="utf-8") as handle:
            handle.write("subtitle")

        _, _, result = self._run_confirmed(
            cfg,
            "rename",
            [
                {
                    "id": "folder-rename",
                    "name": "OldFolder",
                    "path": "Media/OldFolder",
                    "new_path": "Media/NewFolder",
                    "is_dir": True,
                }
            ],
            dedupe_key="folder-rename-indexed",
        )

        self.assertEqual(result["completed"], 1)
        self.assertFalse(os.path.exists(self._strm_path(old_local)))
        self.assertTrue(os.path.isfile(metadata))
        new_local = "媒体库/Media/NewFolder/Episode.mkv"
        self.assertTrue(os.path.isfile(self._strm_path(new_local)))
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT local_rel_path FROM monitor_files").fetchall()
        self.assertEqual(rows, [(new_local,)])
        self.assertEqual(
            result.get("change_details"),
            [
                {
                    "kind": "folder",
                    "operation": "rename",
                    "old_path": "媒体库/Media/OldFolder",
                    "new_path": "媒体库/Media/NewFolder",
                    "deleted": 1,
                    "generated": 1,
                }
            ],
        )

    def test_folder_rename_migrates_clean_directory_baseline(self):
        cfg = self._cfg()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO monitor_dirs(task_name, dir_rel_path, remote_modified, entry_modified, needs_rescan, missing_confirmations) VALUES (?, ?, ?, ?, ?, ?)",
                ("影视监控", "Shows", "old", "old", 0, 0),
            )
            conn.execute(
                "INSERT INTO monitor_dirs(task_name, dir_rel_path, remote_modified, entry_modified, needs_rescan, missing_confirmations) VALUES (?, ?, ?, ?, ?, ?)",
                ("影视监控", "Shows/Old", "old", "old", 0, 0),
            )
            conn.commit()

        _, _, result = self._run_confirmed(
            cfg,
            "rename",
            [
                {
                    "id": "folder-state",
                    "name": "Old",
                    "path": "Media/Shows/Old",
                    "new_path": "Media/Shows/New",
                    "is_dir": True,
                }
            ],
            dedupe_key="folder-state",
        )

        self.assertEqual(result["completed"], 1)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT dir_rel_path, remote_modified, entry_modified, needs_rescan FROM monitor_dirs WHERE task_name = ? ORDER BY dir_rel_path",
                ("影视监控",),
            ).fetchall()
        self.assertEqual(
            rows,
            [
                ("Shows", "old", "old", 0),
                ("Shows/New", "old", "old", 0),
            ],
        )

    def test_top_level_folder_change_does_not_mark_empty_root_branch(self):
        cfg = self._cfg()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO monitor_dirs(task_name, dir_rel_path, remote_modified, entry_modified, needs_rescan, missing_confirmations) VALUES (?, ?, '', '', 0, 0)",
                ("影视监控", "Old"),
            )
            conn.commit()
        _, _, result = self._run_confirmed(
            cfg,
            "rename",
            [
                {
                    "id": "top-level-folder",
                    "name": "Old",
                    "path": "Media/Old",
                    "new_path": "Media/New",
                    "is_dir": True,
                }
            ],
            dedupe_key="top-level-folder",
        )

        self.assertEqual(result["completed"], 1)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT dir_rel_path, needs_rescan FROM monitor_dirs WHERE task_name = ?",
                ("影视监控",),
            ).fetchall()
        self.assertEqual(rows, [("New", 0)])

    def test_root_level_file_change_does_not_force_monitor_rescan(self):
        cfg = self._cfg()
        _, _, result = self._run_confirmed(
            cfg,
            "copy",
            [
                {
                    "id": "root-file",
                    "path": "Outside/Root.mkv",
                    "new_path": "Media/Root.mkv",
                    "is_dir": False,
                    "size": 4096,
                }
            ],
            dedupe_key="root-file-baseline",
        )

        self.assertEqual(result["completed"], 1)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT dir_rel_path, needs_rescan FROM monitor_dirs WHERE task_name = ?",
                ("影视监控",),
            ).fetchall()
        self.assertEqual(rows, [])

    def test_new_file_and_filter_rules_are_applied_without_full_write_mode(self):
        cfg = self._cfg(self._task(min_file_size_mb=1, strm_write_mode="full", sync_clean=False))
        _, _, result = self._run_confirmed(
            cfg,
            "copy",
            [
                {
                    "id": "small",
                    "name": "small.txt",
                    "path": "Outside/small.txt",
                    "new_path": "Media/small.txt",
                    "is_dir": False,
                    "size": 2 * 1024 * 1024,
                },
                {
                    "id": "video",
                    "name": "video.mkv",
                    "path": "Outside/video.mkv",
                    "new_path": "Media/video.mkv",
                    "is_dir": False,
                    "size": 2 * 1024 * 1024,
                },
            ],
            dedupe_key="filter-rules",
        )

        self.assertEqual(result["completed"], 2)
        self.assertFalse(os.path.exists(self._strm_path("媒体库/Media/small.txt")))
        self.assertTrue(os.path.exists(self._strm_path("媒体库/Media/video.mkv")))

    def test_folder_delete_clears_index_prefix_but_not_non_strm_files(self):
        cfg = self._cfg()
        old_local = "媒体库/Media/DeleteFolder/Episode.mkv"
        self._insert_monitor_file("影视监控", old_local, "DeleteFolder/Episode.mkv")
        self._write_strm(old_local, "old")
        poster = os.path.join(self.strm_root, "媒体库/Media/DeleteFolder/poster.nfo")
        os.makedirs(os.path.dirname(poster), exist_ok=True)
        with open(poster, "w", encoding="utf-8") as handle:
            handle.write("nfo")

        _, _, result = self._run_confirmed(
            cfg,
            "delete",
            [{"id": "delete-folder", "name": "DeleteFolder", "path": "Media/DeleteFolder", "is_dir": True}],
            dedupe_key="folder-delete",
        )

        self.assertEqual(result["completed"], 1)
        self.assertFalse(os.path.exists(self._strm_path(old_local)))
        self.assertTrue(os.path.isfile(poster))
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(1) FROM monitor_files").fetchone()[0], 0)

    def test_create_folder_records_clean_baseline_without_listing(self):
        cfg = self._cfg()
        with patch.object(
            monitor_changes,
            "list_remote_dir",
            AsyncMock(side_effect=AssertionError("creating a folder has no file subtree to list")),
        ):
            _, _, result = self._run_confirmed(
                cfg,
                "create",
                [{"id": "new-folder", "name": "NewFolder", "new_path": "Media/NewFolder", "is_dir": True}],
                dedupe_key="folder-create",
            )

        self.assertEqual(result["completed"], 1)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT dir_rel_path, needs_rescan FROM monitor_dirs WHERE task_name = ?",
                ("影视监控",),
            ).fetchone()
        self.assertEqual(row, ("NewFolder", 0))

    def test_reconcile_reads_minimal_parent_and_rebuilds_actual_new_name(self):
        cfg = self._cfg()
        old_local = "媒体库/Media/Folder/Old.mkv"
        self._insert_monitor_file("影视监控", old_local, "Folder/Old.mkv")
        self._write_strm(old_local, "old")
        calls = []

        async def fake_list(_cfg, remote_path, _refresh, _task, *, folder_cid=""):
            calls.append((remote_path, folder_cid))
            self.assertEqual(remote_path, "/115/Media/Folder")
            self.assertEqual(folder_cid, "folder-parent-cid")
            return "", [
                {
                    "id": "reconcile",
                    "name": "New.mkv",
                    "is_dir": False,
                    "size": 4096,
                    "modified": "2026-08-09 11:00:00",
                }
            ]

        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="rename",
            entries=[
                {
                    "id": "reconcile",
                    "path": "Media/Folder/Old.mkv",
                    "new_path": "Media/Folder/New.mkv",
                    "parent_id": "folder-parent-cid",
                    "is_dir": False,
                    "size": 4096,
                }
            ],
            dedupe_key="reconcile-parent",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(prepared, succeeded=False, enqueue=False, error="interrupted")
        with (
            patch.object(monitor_changes, "STRM_ROOT", self.strm_root),
            patch.object(monitor_changes, "list_remote_dir", side_effect=fake_list),
        ):
            result = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))

        self.assertEqual(result["completed"], 1)
        self.assertEqual(calls, [("/115/Media/Folder", "folder-parent-cid")])
        self.assertFalse(os.path.exists(self._strm_path(old_local)))
        self.assertTrue(os.path.exists(self._strm_path("媒体库/Media/Folder/New.mkv")))

    def test_reconcile_uses_snapshot_id_when_remote_name_differs(self):
        cfg = self._cfg()
        old_local = "媒体库/Media/Folder/Old.mkv"
        self._insert_monitor_file("影视监控", old_local, "Folder/Old.mkv")
        self._write_strm(old_local, "old")

        async def fake_list(_cfg, remote_path, _refresh, _task, *, folder_cid=""):
            self.assertEqual(remote_path, "/115/Media/Folder")
            self.assertEqual(folder_cid, "folder-parent-cid")
            return "", [
                {
                    "id": "reconcile-id",
                    "name": "Actual.mkv",
                    "is_dir": False,
                    "size": 4096,
                    "modified": "2026-08-09 11:00:00",
                }
            ]

        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="rename",
            entries=[
                {
                    "id": "reconcile-id",
                    "path": "Media/Folder/Old.mkv",
                    "new_path": "Media/Folder/Expected.mkv",
                    "parent_id": "folder-parent-cid",
                    "is_dir": False,
                    "size": 4096,
                }
            ],
            dedupe_key="reconcile-by-id",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(prepared, succeeded=False, enqueue=False, error="interrupted")
        with (
            patch.object(monitor_changes, "STRM_ROOT", self.strm_root),
            patch.object(monitor_changes, "list_remote_dir", side_effect=fake_list),
        ):
            result = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))

        self.assertEqual(result["completed"], 1)
        self.assertFalse(os.path.exists(self._strm_path(old_local)))
        self.assertTrue(os.path.exists(self._strm_path("媒体库/Media/Folder/Actual.mkv")))

    def test_reconcile_does_not_accept_same_name_entry_with_different_id(self):
        cfg = self._cfg()

        async def fake_list(_cfg, remote_path, _refresh, _task, *, folder_cid=""):
            self.assertEqual(remote_path, "/115/Media/Folder")
            self.assertEqual(folder_cid, "folder-parent-cid")
            return "", [
                {
                    "id": "different-id",
                    "name": "Copied.mkv",
                    "is_dir": False,
                    "size": 4096,
                    "modified": "2026-08-09 11:00:00",
                }
            ]

        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="copy",
            entries=[
                {
                    "id": "expected-id",
                    "path": "Outside/Source.mkv",
                    "new_path": "Media/Folder/Copied.mkv",
                    "new_parent_id": "folder-parent-cid",
                    "is_dir": False,
                    "size": 4096,
                }
            ],
            dedupe_key="reconcile-copy-id",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(
            prepared,
            succeeded=False,
            enqueue=False,
            error="interrupted",
        )
        with (
            patch.object(monitor_changes, "STRM_ROOT", self.strm_root),
            patch.object(monitor_changes, "list_remote_dir", side_effect=fake_list),
        ):
            result = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))

        self.assertEqual(result["failed"], 1)
        self.assertFalse(os.path.exists(self._strm_path("媒体库/Media/Folder/Copied.mkv")))
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT status, last_error FROM monitor_change_events WHERE id = ?",
                (prepared["event_ids"][0],),
            ).fetchone()
        self.assertEqual(row[0], "failed")
        self.assertIn("未找到", row[1])

    def test_local_write_failure_is_retained_and_retried_with_backoff(self):
        cfg = self._cfg()
        old_local = "媒体库/Media/Retry/Old.mkv"
        new_local = "媒体库/Media/Retry/New.mkv"
        self._insert_monitor_file("影视监控", old_local, "Retry/Old.mkv", size=4096)
        self._write_strm(old_local, "old")
        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="rename",
            entries=[
                {
                    "id": "retry-file",
                    "path": "Media/Retry/Old.mkv",
                    "new_path": "Media/Retry/New.mkv",
                    "old_parent_id": "retry-parent",
                    "new_parent_id": "retry-parent",
                    "is_dir": False,
                    "size": 4096,
                }
            ],
            dedupe_key="local-write-retry",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(prepared, succeeded=True, enqueue=False)
        with (
            patch.object(monitor_changes, "STRM_ROOT", self.strm_root),
            patch.object(monitor_changes, "_write_strm_file", side_effect=RuntimeError("temporary local write error")),
            patch.object(
                monitor_changes,
                "list_remote_dir",
                AsyncMock(side_effect=AssertionError("confirmed file changes must not list 115")),
            ),
        ):
            first = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))
        self.assertEqual(first["failed"], 1)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT status, retry_count, next_retry_at, last_error FROM monitor_change_events"
            ).fetchone()
            conn.execute("UPDATE monitor_change_events SET next_retry_at = 0")
            conn.commit()
        self.assertEqual(row[0], "failed")
        self.assertEqual(row[1], 1)
        self.assertGreater(row[2], 0)
        self.assertIn("temporary local write error", row[3])
        self.assertTrue(os.path.exists(self._strm_path(old_local)))
        self.assertFalse(os.path.exists(self._strm_path(new_local)))
        with sqlite3.connect(self.db_path) as conn:
            index_rows = conn.execute(
                "SELECT local_rel_path, remote_rel_path FROM monitor_files"
            ).fetchall()
        self.assertEqual(index_rows, [(old_local, "Retry/Old.mkv")])

        with (
            patch.object(monitor_changes, "STRM_ROOT", self.strm_root),
            patch.object(
                monitor_changes,
                "list_remote_dir",
                AsyncMock(side_effect=AssertionError("local retries must not list 115")),
            ),
        ):
            second = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))
        self.assertEqual(second["completed"], 1)
        self.assertTrue(os.path.exists(self._strm_path(new_local)))
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT local_rel_path, remote_rel_path FROM monitor_files"
            ).fetchall()
        self.assertEqual(rows, [(new_local, "Retry/New.mkv")])

    def test_confirmed_scraper_sync_failure_is_logged_and_deleted(self):
        cfg = self._cfg()
        old_local = "媒体库/Media/OneShot/Old.mkv"
        new_local = "媒体库/Media/OneShot/New.mkv"
        self._insert_monitor_file("影视监控", old_local, "OneShot/Old.mkv", size=4096)
        old_strm = self._write_strm(old_local, "old")
        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="rename",
            entries=[
                {
                    "id": "one-shot-file",
                    "old_path": "Media/OneShot/Old.mkv",
                    "new_path": "Media/OneShot/New.mkv",
                    "is_dir": False,
                    "size": 4096,
                }
            ],
            source_action="scraper-job:one-shot:forward",
            dedupe_key="one-shot-local-failure",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(prepared, succeeded=True, enqueue=False)

        with (
            patch.object(monitor_changes, "STRM_ROOT", self.strm_root),
            patch.object(
                monitor_changes,
                "_write_strm_file",
                side_effect=RuntimeError("local write failed"),
            ),
            patch.object(
                monitor_changes,
                "list_remote_dir",
                AsyncMock(side_effect=AssertionError("confirmed path sync must not read 115")),
            ),
        ):
            result = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))

        self.assertEqual(result["failed"], 1)
        self.assertEqual(
            result["errors"],
            [
                {
                    "event_id": prepared["event_ids"][0],
                    "error": "local write failed",
                    "retryable": False,
                }
            ],
        )
        self.assertTrue(os.path.isfile(old_strm))
        self.assertFalse(os.path.exists(self._strm_path(new_local)))
        with sqlite3.connect(self.db_path) as conn:
            event_row = conn.execute(
                "SELECT status, retry_count FROM monitor_change_events WHERE id = ?",
                (prepared["event_ids"][0],),
            ).fetchone()
            index_rows = conn.execute(
                "SELECT local_rel_path, remote_rel_path FROM monitor_files"
            ).fetchall()
        self.assertIsNone(event_row)
        self.assertEqual(index_rows, [(old_local, "OneShot/Old.mkv")])
        self.assertEqual(monitor_changes.get_monitor_change_counts(), {})

    def test_indexed_folder_write_failure_restores_old_strms_and_removes_partial_new_files(self):
        cfg = self._cfg()
        old_locals = [
            "媒体库/Media/Source/Episode01.mkv",
            "媒体库/Media/Source/Episode02.mkv",
        ]
        new_locals = [
            "媒体库/Media/Renamed/Episode01.mkv",
            "媒体库/Media/Renamed/Episode02.mkv",
        ]
        for index, old_local in enumerate(old_locals, start=1):
            self._insert_monitor_file(
                "影视监控",
                old_local,
                f"Source/Episode{index:02d}.mkv",
                size=4096,
            )
            self._write_strm(old_local, f"old-{index}")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO monitor_dirs(task_name, dir_rel_path, remote_modified, entry_modified, needs_rescan, missing_confirmations) VALUES (?, ?, '', '', 0, 0)",
                ("影视监控", "Source"),
            )
            conn.commit()

        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="move",
            entries=[
                {
                    "id": "folder-write-retry",
                    "old_path": "Media/Source",
                    "new_path": "Media/Renamed",
                    "old_parent_id": "media-parent",
                    "new_parent_id": "media-parent",
                    "is_dir": True,
                }
            ],
            dedupe_key="folder-write-retry",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(prepared, succeeded=True, enqueue=False)
        original_write = monitor_changes._write_strm_file
        write_count = 0

        def flaky_write(*args, **kwargs):
            nonlocal write_count
            write_count += 1
            if write_count == 2:
                raise RuntimeError("second folder STRM write failed")
            return original_write(*args, **kwargs)

        with (
            patch.object(monitor_changes, "STRM_ROOT", self.strm_root),
            patch.object(monitor_changes, "_write_strm_file", side_effect=flaky_write),
            patch.object(
                monitor_changes,
                "list_remote_dir",
                AsyncMock(side_effect=AssertionError("confirmed indexed folders must not read 115")),
            ),
        ):
            result = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))

        self.assertEqual(result["failed"], 1)
        self.assertEqual(write_count, 2)
        self.assertEqual(result.get("change_details"), [])
        for old_local in old_locals:
            self.assertTrue(os.path.exists(self._strm_path(old_local)))
        for new_local in new_locals:
            self.assertFalse(os.path.exists(self._strm_path(new_local)))
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT local_rel_path, remote_rel_path FROM monitor_files ORDER BY local_rel_path"
            ).fetchall()
        self.assertEqual(
            rows,
            [
                (old_locals[0], "Source/Episode01.mkv"),
                (old_locals[1], "Source/Episode02.mkv"),
            ],
        )

    def test_manual_required_event_is_not_cleared_without_explicit_coverage(self):
        cfg = self._cfg()
        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="copy",
            entries=[
                {
                    "id": "scoped-manual-folder",
                    "path": "Outside/Source",
                    "new_path": "Media/ScopedManual",
                    "is_dir": True,
                }
            ],
            dedupe_key="scoped-manual",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(prepared, succeeded=True, enqueue=False)
        with patch.object(monitor_changes, "STRM_ROOT", self.strm_root):
            result = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))
        self.assertEqual(result["manual_required"], 1)
        self.assertEqual(
            monitor_changes.complete_manual_required_monitor_events(
                "影视监控",
                [],
            ),
            0,
        )
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(
                conn.execute("SELECT status FROM monitor_change_events").fetchone()[0],
                "manual_required",
            )

    def test_cross_directory_move_uses_paths_without_parent_ids(self):
        cfg = self._cfg()
        old_local = "媒体库/Media/A/Episode.mkv"
        new_local = "媒体库/Media/B/Episode.mkv"
        self._insert_monitor_file("影视监控", old_local, "A/Episode.mkv", size=4096)
        self._write_strm(old_local, "old")

        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="move",
            entries=[
                {
                    "id": "missing-parent-ids",
                    "old_path": "Media/A/Episode.mkv",
                    "new_path": "Media/B/Episode.mkv",
                    "is_dir": False,
                    "size": 4096,
                }
            ],
            dedupe_key="missing-parent-ids",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(prepared, succeeded=True, enqueue=False)
        with (
            patch.object(monitor_changes, "STRM_ROOT", self.strm_root),
            patch.object(
                monitor_changes,
                "list_remote_dir",
                AsyncMock(side_effect=AssertionError("confirmed move must not list 115")),
            ),
        ):
            result = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))

        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertFalse(os.path.exists(self._strm_path(old_local)))
        self.assertTrue(os.path.exists(self._strm_path(new_local)))
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT local_rel_path, remote_rel_path FROM monitor_files"
            ).fetchall()
            event_status = conn.execute(
                "SELECT status FROM monitor_change_events WHERE id = ?",
                (prepared["event_ids"][0],),
            ).fetchone()[0]
        self.assertEqual(rows, [(new_local, "B/Episode.mkv")])
        self.assertEqual(event_status, "completed")

    def test_invalid_folder_manifest_path_fails_before_deleting_old_strm(self):
        cfg = self._cfg()
        old_local = "媒体库/Media/Source/Episode.mkv"
        escaped_local = "媒体库/Media/Escape.mkv"
        self._insert_monitor_file(
            "影视监控",
            old_local,
            "Source/../Escape.mkv",
            size=4096,
        )
        self._write_strm(old_local, "old")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO monitor_dirs(task_name, dir_rel_path, remote_modified, entry_modified, needs_rescan, missing_confirmations) VALUES (?, ?, '', '', 0, 0)",
                ("影视监控", "Source"),
            )
            conn.commit()

        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="move",
            entries=[
                {
                    "id": "invalid-manifest-folder",
                    "old_path": "Media/Source",
                    "new_path": "Media/Dest",
                    "old_parent_id": "media-parent",
                    "new_parent_id": "media-parent",
                    "is_dir": True,
                }
            ],
            dedupe_key="invalid-folder-manifest",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(prepared, succeeded=True, enqueue=False)
        with patch.object(monitor_changes, "STRM_ROOT", self.strm_root):
            result = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))

        self.assertEqual(result["failed"], 1)
        self.assertTrue(os.path.exists(self._strm_path(old_local)))
        self.assertFalse(os.path.exists(self._strm_path(escaped_local)))
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT local_rel_path, remote_rel_path FROM monitor_files"
            ).fetchall()
            event_status, error = conn.execute(
                "SELECT status, last_error FROM monitor_change_events WHERE id = ?",
                (prepared["event_ids"][0],),
            ).fetchone()
        self.assertEqual(rows, [(old_local, "Source/../Escape.mkv")])
        self.assertEqual(event_status, "failed")
        self.assertIn("索引清单", error)

    def test_cross_task_manifest_respects_destination_size_filter_completeness(self):
        source_task = self._task(
            name="来源",
            scan_path="/115/Media/Source",
            target_path="来源库",
            min_file_size_mb=1024,
        )
        target_task = self._task(
            name="目标",
            scan_path="/115/Media/Dest",
            target_path="目标库",
            min_file_size_mb=0,
        )
        cfg = self._cfg(source_task, target_task)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO monitor_dirs(task_name, dir_rel_path, remote_modified, entry_modified, needs_rescan, missing_confirmations) VALUES (?, ?, '', '', 0, 0)",
                ("来源", "Folder"),
            )
            conn.commit()

        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="move",
            entries=[
                {
                    "id": "filtered-folder",
                    "old_path": "Media/Source/Folder",
                    "new_path": "Media/Dest/Folder",
                    "old_parent_id": "source-parent",
                    "new_parent_id": "dest-parent",
                    "is_dir": True,
                }
            ],
            dedupe_key="cross-task-filter-completeness",
            cfg=cfg,
        )

        with sqlite3.connect(self.db_path) as conn:
            raw_snapshot = conn.execute(
                "SELECT entry_snapshot_json FROM monitor_change_events WHERE task_name = ?",
                ("目标",),
            ).fetchone()[0]
        snapshot = json.loads(raw_snapshot)
        self.assertFalse(snapshot["manifest_known"])
        self.assertTrue(snapshot["manual_required"])
        monitor_changes.confirm_monitor_change_events(prepared, succeeded=True, enqueue=False)
        with patch.object(monitor_changes, "STRM_ROOT", self.strm_root):
            result = asyncio.run(
                monitor_changes.process_monitor_change_events(
                    "目标",
                    cfg=cfg,
                )
            )
        self.assertEqual(result["manual_required"], 1)

    def test_conflicting_shared_output_is_not_overwritten(self):
        task_a = self._task(name="任务 A", scan_path="/115/A/Media", target_path="共享库")
        task_b = self._task(name="任务 B", scan_path="/115/B/Media", target_path="共享库")
        cfg = self._cfg(task_a, task_b)
        local_rel = "共享库/Media/Episode.mkv"
        self._insert_monitor_file("任务 B", local_rel, "Episode.mkv", size=4096)
        target = self._write_strm(local_rel, "task-b-original")

        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="copy",
            entries=[
                {
                    "id": "shared-output-source",
                    "old_path": "Outside/Source.mkv",
                    "new_path": "A/Media/Episode.mkv",
                    "new_parent_id": "task-a-parent",
                    "is_dir": False,
                    "size": 4096,
                }
            ],
            dedupe_key="shared-output-conflict",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(prepared, succeeded=True, enqueue=False)
        with patch.object(monitor_changes, "STRM_ROOT", self.strm_root):
            result = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))

        self.assertEqual(result["failed"], 1)
        with open(target, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "task-b-original")
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT task_name, remote_rel_path FROM monitor_files WHERE local_rel_path = ?",
                (local_rel,),
            ).fetchall()
        self.assertEqual(rows, [("任务 B", "Episode.mkv")])

    def test_startup_recovery_uses_persisted_create_folder_cid_without_listing(self):
        cfg = self._cfg()
        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="create",
            entries=[
                {
                    "id": "",
                    "new_path": "Media/NewFolder",
                    "new_parent_id": "media-parent",
                    "is_dir": True,
                }
            ],
            dedupe_key="recover-create-folder-cid",
            cfg=cfg,
        )
        monitor_changes.update_monitor_change_event_snapshots(
            prepared,
            [{"new_path": "Media/NewFolder", "new_cid": "new-folder-cid"}],
        )

        recovery = monitor_changes.recover_monitor_change_events(cfg=cfg, enqueue=False)

        self.assertEqual(recovery["recovered"], 1)
        with sqlite3.connect(self.db_path) as conn:
            status_row = conn.execute(
                "SELECT status, needs_reconcile FROM monitor_change_events WHERE id = ?",
                (prepared["event_ids"][0],),
            ).fetchone()
        self.assertEqual(status_row, ("pending", 0))
        with (
            patch.object(monitor_changes, "STRM_ROOT", self.strm_root),
            patch.object(
                monitor_changes,
                "list_remote_dir",
                AsyncMock(side_effect=AssertionError("persisted destination CID confirms the create")),
            ),
        ):
            result = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))
        self.assertEqual(result["completed"], 1)

    def test_startup_recovery_uses_persisted_copy_folder_cid_without_listing(self):
        cfg = self._cfg()
        old_local = "媒体库/Media/Source/Episode.mkv"
        new_local = "媒体库/Media/Copied/Episode.mkv"
        self._insert_monitor_file("影视监控", old_local, "Source/Episode.mkv", size=4096)
        self._write_strm(old_local, "source")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO monitor_dirs(task_name, dir_rel_path, remote_modified, entry_modified, needs_rescan, missing_confirmations) VALUES (?, ?, '', '', 0, 0)",
                ("影视监控", "Source"),
            )
            conn.commit()
        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="copy",
            entries=[
                {
                    "id": "source-folder-cid",
                    "old_path": "Media/Source",
                    "new_path": "Media/Copied",
                    "new_parent_id": "media-parent",
                    "old_cid": "source-folder-cid",
                    "is_dir": True,
                }
            ],
            dedupe_key="recover-copy-folder-cid",
            cfg=cfg,
        )
        monitor_changes.update_monitor_change_event_snapshots(
            prepared,
            [
                {
                    "id": "source-folder-cid",
                    "new_path": "Media/Copied",
                    "new_cid": "copied-folder-cid",
                }
            ],
        )

        monitor_changes.recover_monitor_change_events(cfg=cfg, enqueue=False)
        with sqlite3.connect(self.db_path) as conn:
            needs_reconcile = conn.execute(
                "SELECT needs_reconcile FROM monitor_change_events WHERE id = ?",
                (prepared["event_ids"][0],),
            ).fetchone()[0]
        self.assertEqual(needs_reconcile, 0)
        with (
            patch.object(monitor_changes, "STRM_ROOT", self.strm_root),
            patch.object(
                monitor_changes,
                "list_remote_dir",
                AsyncMock(side_effect=AssertionError("persisted destination CID confirms the copy")),
            ),
        ):
            result = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))
        self.assertEqual(result["completed"], 1)
        self.assertTrue(os.path.exists(self._strm_path(old_local)))
        self.assertTrue(os.path.exists(self._strm_path(new_local)))

    def test_startup_recovery_does_not_trust_source_cid_as_copy_destination(self):
        cfg = self._cfg()
        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="copy",
            entries=[
                {
                    "id": "source-folder-cid",
                    "old_path": "Outside/Source",
                    "new_path": "Media/Copied",
                    "old_parent_id": "source-parent",
                    "new_parent_id": "media-parent",
                    "old_cid": "source-folder-cid",
                    "new_cid": "source-folder-cid",
                    "is_dir": True,
                }
            ],
            dedupe_key="recover-reject-source-cid",
            cfg=cfg,
        )

        monitor_changes.recover_monitor_change_events(cfg=cfg, enqueue=False)

        with sqlite3.connect(self.db_path) as conn:
            needs_reconcile = conn.execute(
                "SELECT needs_reconcile FROM monitor_change_events WHERE id = ?",
                (prepared["event_ids"][0],),
            ).fetchone()[0]
        self.assertEqual(needs_reconcile, 1)

    def test_startup_recovery_preserves_confirmed_processing_mode(self):
        cfg = self._cfg()
        old_local = "媒体库/Media/Folder/Old.mkv"
        new_local = "媒体库/Media/Folder/New.mkv"
        self._insert_monitor_file("影视监控", old_local, "Folder/Old.mkv", size=4096)
        self._write_strm(old_local, "old")
        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="rename",
            entries=[
                {
                    "id": "processing-recovery",
                    "old_path": "Media/Folder/Old.mkv",
                    "new_path": "Media/Folder/New.mkv",
                    "old_parent_id": "folder-parent",
                    "new_parent_id": "folder-parent",
                    "is_dir": False,
                    "size": 4096,
                }
            ],
            dedupe_key="recover-confirmed-processing",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(prepared, succeeded=True, enqueue=False)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE monitor_change_events SET status = 'processing' WHERE id = ?",
                (prepared["event_ids"][0],),
            )
            conn.commit()

        monitor_changes.recover_monitor_change_events(cfg=cfg, enqueue=False)
        with sqlite3.connect(self.db_path) as conn:
            needs_reconcile = conn.execute(
                "SELECT needs_reconcile FROM monitor_change_events WHERE id = ?",
                (prepared["event_ids"][0],),
            ).fetchone()[0]
        self.assertEqual(needs_reconcile, 0)
        with (
            patch.object(monitor_changes, "STRM_ROOT", self.strm_root),
            patch.object(
                monitor_changes,
                "list_remote_dir",
                AsyncMock(side_effect=AssertionError("confirmed processing recovery stays precise")),
            ),
        ):
            result = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))
        self.assertEqual(result["completed"], 1)
        self.assertFalse(os.path.exists(self._strm_path(old_local)))
        self.assertTrue(os.path.exists(self._strm_path(new_local)))

    def test_reconcile_delete_with_same_id_renamed_replaces_old_index(self):
        cfg = self._cfg()
        old_local = "媒体库/Media/Folder/Old.mkv"
        new_local = "媒体库/Media/Folder/Renamed.mkv"
        self._insert_monitor_file("影视监控", old_local, "Folder/Old.mkv", size=4096)
        self._write_strm(old_local, "old")

        async def fake_list(_cfg, remote_path, _refresh, _task, *, folder_cid=""):
            self.assertEqual(remote_path, "/115/Media/Folder")
            self.assertEqual(folder_cid, "folder-parent")
            return "", [
                {
                    "id": "delete-then-renamed",
                    "name": "Renamed.mkv",
                    "is_dir": False,
                    "size": 4096,
                    "modified": "2026-08-10 10:00:00",
                }
            ]

        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="delete",
            entries=[
                {
                    "id": "delete-then-renamed",
                    "old_path": "Media/Folder/Old.mkv",
                    "old_parent_id": "folder-parent",
                    "is_dir": False,
                    "size": 4096,
                }
            ],
            dedupe_key="reconcile-delete-renamed",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(
            prepared,
            succeeded=False,
            enqueue=False,
            error="remote result unknown",
        )
        with (
            patch.object(monitor_changes, "STRM_ROOT", self.strm_root),
            patch.object(monitor_changes, "list_remote_dir", side_effect=fake_list),
        ):
            result = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))

        self.assertEqual(result["completed"], 1)
        self.assertFalse(os.path.exists(self._strm_path(old_local)))
        self.assertTrue(os.path.exists(self._strm_path(new_local)))
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT local_rel_path, remote_rel_path FROM monitor_files"
            ).fetchall()
        self.assertEqual(rows, [(new_local, "Folder/Renamed.mkv")])

    def test_reconcile_dirty_folder_delete_with_same_id_renamed_keeps_manual_required(self):
        cfg = self._cfg()
        old_local = "媒体库/Media/Parent/Source/Known.mkv"
        new_local = "媒体库/Media/Parent/Renamed/Known.mkv"
        self._insert_monitor_file("影视监控", old_local, "Parent/Source/Known.mkv", size=4096)
        self._write_strm(old_local, "old")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO monitor_dirs(
                    task_name, dir_rel_path, remote_modified, entry_modified,
                    needs_rescan, missing_confirmations
                ) VALUES (?, ?, '', '', 1, 0)
                """,
                ("影视监控", "Parent/Source"),
            )
            conn.commit()

        async def fake_list(_cfg, remote_path, _refresh, _task, *, folder_cid=""):
            self.assertEqual(remote_path, "/115/Media/Parent")
            self.assertEqual(folder_cid, "parent-cid")
            return "", [
                {
                    "id": "dirty-folder-delete",
                    "name": "Renamed",
                    "is_dir": True,
                    "size": 0,
                }
            ]

        prepared = monitor_changes.prepare_monitor_change_events(
            provider="115",
            operation="delete",
            entries=[
                {
                    "id": "dirty-folder-delete",
                    "old_path": "Media/Parent/Source",
                    "old_parent_id": "parent-cid",
                    "is_dir": True,
                }
            ],
            dedupe_key="dirty-folder-delete-rename",
            cfg=cfg,
        )
        monitor_changes.confirm_monitor_change_events(
            prepared,
            succeeded=False,
            enqueue=False,
            error="remote result unknown",
        )
        with (
            patch.object(monitor_changes, "STRM_ROOT", self.strm_root),
            patch.object(monitor_changes, "list_remote_dir", side_effect=fake_list),
        ):
            result = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))

        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["manual_required"], 1)
        self.assertFalse(os.path.exists(self._strm_path(old_local)))
        self.assertTrue(os.path.exists(self._strm_path(new_local)))
        with sqlite3.connect(self.db_path) as conn:
            status = conn.execute(
                "SELECT status FROM monitor_change_events WHERE id = ?",
                (prepared["event_ids"][0],),
            ).fetchone()[0]
        self.assertEqual(status, "manual_required")


if __name__ == "__main__":
    unittest.main()
