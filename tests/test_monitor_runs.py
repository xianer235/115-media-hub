import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from app import db
from app.services import monitor, monitor_runs, quick_import


class MonitorRunStoreTest(unittest.TestCase):
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

    def test_records_detail_and_keeps_active_runs_during_cleanup(self):
        completed = monitor_runs.create_run(
            run_kind="scan",
            task_name="电视剧",
            source="manual",
            scope={"kind": "paths", "paths": ["电视剧/三体 S01"]},
            subject="三体 S01",
        )
        monitor_runs.start_run(completed)
        monitor_runs.record_event(
            completed,
            category="strm",
            operation="write",
            status="completed",
            title="S01E01.strm",
            detail={"path": "电视剧/三体 S01/S01E01.strm"},
        )
        monitor_runs.finish_run(completed, status="completed", summary="新增 STRM 1", result={"generated": 1})
        active = monitor_runs.create_run(run_kind="scan", task_name="电影", source="cron", subject="全部目录")

        page = monitor_runs.list_runs()
        self.assertEqual({item["subject"] for item in page["runs"]}, {"三体 S01", "全部目录"})
        detail = monitor_runs.get_run_detail(completed)
        self.assertEqual(detail["run"]["subject"], "三体 S01")
        self.assertTrue(any(item["category"] == "strm" for item in detail["events"]))

        cleanup = monitor_runs.cleanup_runs()
        self.assertEqual(cleanup["deleted"], 1)
        self.assertTrue(monitor_runs.get_run_detail(active))

    def test_waiting_inbox_parent_closes_after_child_and_keeps_partial_result(self):
        parent = monitor_runs.create_run(run_kind="inbox", task_name="接收", source="manual", subject="三体（2023）")
        monitor_runs.wait_run(parent, summary="已分发，等待 STRM 同步", result={"moved": 1, "left": 1})
        child = monitor_runs.create_run(run_kind="change", task_name="电视剧", source="change", parent_run_id=parent, subject="文件变更")
        monitor_runs.start_run(child)
        monitor_runs.finish_run(child, status="completed", summary="生成 STRM 2", result={"generated": 2})

        self.assertEqual(monitor_runs.get_run_detail(parent)["run"]["status"], "partial")

    def test_cleanup_keeps_completed_parent_needed_by_active_child(self):
        parent = monitor_runs.create_run(run_kind="inbox", task_name="接收", source="manual", subject="三体（2023）")
        monitor_runs.finish_run(parent, status="completed", summary="已分发")
        monitor_runs.create_run(
            run_kind="change",
            task_name="电视剧",
            source="change",
            parent_run_id=parent,
            subject="文件变更",
        )

        self.assertEqual(monitor_runs.cleanup_runs()["deleted"], 0)
        self.assertTrue(monitor_runs.get_run_detail(parent))

    def test_list_runs_paginates_by_ten_and_returns_cursor(self):
        for index in range(11):
            run_id = monitor_runs.create_run(
                run_kind="scan",
                task_name="电影",
                source="manual",
                subject=f"目录 {index}",
            )
            monitor_runs.finish_run(run_id, status="completed", summary="完成")

        first = monitor_runs.list_runs(limit=10)
        self.assertEqual(len(first["runs"]), 10)
        self.assertTrue(first["has_more"])
        second = monitor_runs.list_runs(limit=10, cursor=first["next_cursor"])
        self.assertEqual(len(second["runs"]), 1)
        self.assertFalse(second["has_more"])

    def test_detail_includes_remote_change_paths(self):
        run_id = monitor_runs.create_run(run_kind="change", task_name="电视剧", source="change")
        with db.db_connection() as conn:
            conn.execute(
                """INSERT INTO monitor_change_events
                   (dedupe_key, provider, operation, old_path, new_path,
                    entry_snapshot_json, task_name, monitor_run_id, status,
                    created_at, updated_at, completed_at)
                   VALUES (?, '115', 'rename', ?, ?, '{}', ?, ?, 'completed', ?, ?, ?)""",
                ("test-detail", "电视剧/旧名", "电视剧/新名", "电视剧", run_id, "2026-09-23 10:00:00", "2026-09-23 10:00:00", "2026-09-23 10:00:01"),
            )
            conn.commit()

        detail = monitor_runs.get_run_detail(run_id, category="remote")
        self.assertEqual(len(detail["events"]), 1)
        self.assertEqual(detail["events"][0]["detail"]["old_path"], "电视剧/旧名")
        self.assertEqual(detail["events"][0]["detail"]["new_path"], "电视剧/新名")
        self.assertEqual(detail["events"][0]["detail"]["old_name"], "旧名")
        self.assertEqual(detail["events"][0]["detail"]["new_name"], "新名")
        self.assertEqual(monitor_runs.get_run_detail(run_id, category="strm")["events"], [])

    def test_one_change_run_closes_every_linked_inbox_parent(self):
        first = monitor_runs.create_run(run_kind="inbox", task_name="接收", source="manual", subject="三体（2023）")
        second = monitor_runs.create_run(run_kind="inbox", task_name="接收", source="manual", subject="流浪地球（2019）")
        monitor_runs.wait_run(first, summary="等待 STRM 同步", result={"moved": 1})
        monitor_runs.wait_run(second, summary="等待 STRM 同步", result={"moved": 1})
        child = monitor_runs.create_run(run_kind="change", task_name="电影", source="change", subject="文件变更")
        monitor_runs.set_parent_run(child, first)
        monitor_runs.link_runs(first, child, relation="downstream")
        monitor_runs.link_runs(second, child, relation="downstream")
        monitor_runs.start_run(child)
        monitor_runs.finish_run(child, status="completed", summary="生成 STRM 2", result={"generated": 2})

        self.assertEqual(monitor_runs.get_run_detail(first)["run"]["status"], "completed")
        self.assertEqual(monitor_runs.get_run_detail(second)["run"]["status"], "completed")

    def test_detail_pages_one_combined_event_stream_without_hiding_finish(self):
        run_id = monitor_runs.create_run(run_kind="scan", task_name="电影", source="manual")
        for index in range(62):
            monitor_runs.record_event(
                run_id,
                category="strm",
                operation="write",
                status="completed",
                title=f"{index}.strm",
            )
        monitor_runs.finish_run(run_id, status="completed", summary="完成")

        first = monitor_runs.get_run_detail(run_id, limit=50)
        second = monitor_runs.get_run_detail(run_id, offset=first["next_offset"], limit=50)

        self.assertTrue(first["has_more"])
        self.assertEqual(len(first["events"]), 50)
        self.assertEqual(len(first["events"]) + len(second["events"]), 64)
        self.assertEqual(second["events"][-1]["operation"], "finished")
        self.assertEqual(monitor_runs.get_run_detail(run_id, category="process")["counts"]["strm"], 62)

    def test_problem_filter_pages_failed_remote_events(self):
        run_id = monitor_runs.create_run(run_kind="change", task_name="电影", source="change")
        with db.db_connection() as conn:
            for index in range(12):
                conn.execute(
                    """INSERT INTO monitor_change_events
                    (dedupe_key, provider, operation, old_path, new_path, task_name,
                     monitor_run_id, status, last_error, created_at, updated_at)
                    VALUES (?, '115', 'move', ?, ?, '电影', ?, 'failed', '读取目录失败',
                            '2026-09-23 10:00:00', '2026-09-23 10:00:00')""",
                    (f"problem-page-{index}", f"旧/{index}", f"新/{index}", run_id),
                )
            conn.commit()

        detail = monitor_runs.get_run_detail(run_id, category="problem", limit=5)

        self.assertEqual(detail["total"], 12)
        self.assertEqual(len(detail["events"]), 5)
        self.assertTrue(detail["has_more"])
        self.assertEqual(detail["events"][0]["detail"]["error"], "读取目录失败")

    def test_shared_downstream_appears_once_for_every_parent(self):
        first = monitor_runs.create_run(run_kind="inbox", task_name="接收", source="manual")
        second = monitor_runs.create_run(run_kind="inbox", task_name="接收", source="manual")
        child = monitor_runs.create_run(run_kind="change", task_name="电影", source="change")
        monitor_runs.set_parent_run(child, first)
        monitor_runs.link_runs(first, child, relation="downstream")
        monitor_runs.link_runs(second, child, relation="downstream")

        first_detail = monitor_runs.get_run_detail(first)
        second_detail = monitor_runs.get_run_detail(second)
        listed = {item["id"]: item for item in monitor_runs.list_runs()["runs"]}

        self.assertEqual([item["id"] for item in first_detail["children"]], [child])
        self.assertEqual([item["id"] for item in second_detail["children"]], [child])
        self.assertEqual(listed[first]["child_count"], 1)
        self.assertEqual(listed[second]["child_count"], 1)

    def test_legacy_inbox_item_lists_remain_readable_and_close_parent(self):
        parent = monitor_runs.create_run(run_kind="inbox", task_name="接收", source="manual")
        monitor_runs.wait_run(
            parent,
            summary="等待后续同步",
            result={
                "moved": [{"name": "Movie.mkv"}],
                "left": [{"name": "未识别.mkv", "reason": "待确认"}],
            },
        )
        child = monitor_runs.create_run(run_kind="change", task_name="电影", source="change", parent_run_id=parent)
        monitor_runs.finish_run(child, status="completed", summary="同步完成")

        result = monitor_runs.get_run_detail(parent)["run"]["result"]

        self.assertEqual(result["moved"], 1)
        self.assertEqual(result["left"], 1)
        self.assertEqual(result["left_items"][0]["name"], "未识别.mkv")
        self.assertEqual(monitor_runs.get_run_detail(parent)["run"]["status"], "partial")


class MonitorRunQueueContractTest(unittest.TestCase):
    def test_task_scope_is_not_narrowed_by_later_directory_request(self):
        merged = monitor._merge_monitor_queue_payload({}, {"savepaths": ["电视剧/三体 S01"]})
        self.assertEqual(merged, {})

    def test_two_different_partial_scopes_remain_explicit(self):
        merged = monitor._merge_monitor_queue_payload(
            {"savepath": "电视剧/A"}, {"savepath": "电视剧/B"}
        )
        self.assertEqual(merged["savepaths"], ["电视剧/A", "电视剧/B"])

    def test_quick_import_sync_source_keeps_monitor_run_reference(self):
        action = quick_import._quick_import_source_action(12, "run-abc")
        self.assertEqual(action, "scraper-job:12:quick-import")


class MonitorRunQueueOperationTest(MonitorRunStoreTest):
    def _scan_task(self):
        return {
            "name": "电视剧监控",
            "task_type": "scan",
            "enabled": True,
            "scan_path": "/115/电视剧",
            "target_path": "电视剧",
        }

    def test_retry_creates_a_separate_run_with_the_original_path_scope(self):
        original = monitor_runs.create_run(
            run_kind="scan",
            task_name="电视剧监控",
            source="webhook",
            scope={"kind": "paths", "paths": ["/电视剧/三体 S01"]},
            subject="三体 S01",
        )
        monitor_runs.finish_run(original, status="failed", summary="读取目录失败")
        queued = []
        status = {"running": True, "current_task": "其他任务", "queued": []}
        with patch.object(monitor, "monitor_queue", queued), \
                patch.object(monitor, "monitor_status", status), \
                patch.object(monitor, "get_config", return_value={"monitor_tasks": [self._scan_task()]}), \
                patch.object(monitor, "schedule_ui_state_push", Mock()):
            result = monitor.retry_monitor_run(original)

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "queued")
        self.assertEqual(len(queued), 1)
        retry_id = result["run_id"]
        self.assertNotEqual(retry_id, original)
        self.assertEqual(queued[0]["run_id"], retry_id)
        self.assertEqual(queued[0]["payload"]["savepaths"], ["电视剧/三体 S01"])
        retry = monitor_runs.get_run_detail(retry_id)
        self.assertEqual(retry["run"]["source"], "retry")
        self.assertEqual(retry["run"]["scope"], {"kind": "paths", "paths": ["/电视剧/三体 S01"]})
        self.assertTrue(any(link["related_run_id"] == original and link["relation"] == "retry_of" for link in retry["links"]))

    def test_cancel_removes_only_the_matching_queued_run(self):
        first = monitor_runs.create_run(run_kind="scan", task_name="电影监控", source="manual", subject="全部目录")
        second = monitor_runs.create_run(run_kind="scan", task_name="电视剧监控", source="manual", subject="全部目录")
        queued = [
            {"task_name": "电影监控", "run_id": first},
            {"task_name": "电视剧监控", "run_id": second},
        ]
        status = {"running": True, "current_task": "其他任务", "queued": ["电影监控", "电视剧监控"]}
        with patch.object(monitor, "monitor_queue", queued), \
                patch.object(monitor, "monitor_status", status), \
                patch.object(monitor, "schedule_ui_state_push", Mock()):
            result = monitor.cancel_queued_monitor_run(first)

        self.assertTrue(result["ok"])
        self.assertEqual([item["run_id"] for item in queued], [second])
        cancelled = monitor_runs.get_run_detail(first)["run"]
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertTrue(cancelled["result"]["cancelled_before_start"])

    def test_retry_rejects_change_run_without_persisted_event_scope(self):
        original = monitor_runs.create_run(
            run_kind="change",
            task_name="电视剧监控",
            source="change",
            scope={"kind": "events"},
            subject="文件变更",
        )
        monitor_runs.finish_run(original, status="failed", summary="同步失败")

        result = monitor.retry_monitor_run(original)

        self.assertFalse(result["ok"])
        self.assertIn("没有可重试的失败范围", result["msg"])
