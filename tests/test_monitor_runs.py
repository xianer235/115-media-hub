import os
import tempfile
import unittest
from datetime import datetime, timedelta
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

        cleanup = monitor_runs.cleanup_runs(scope="all_finished")
        self.assertEqual(cleanup["deleted"], 1)
        self.assertTrue(monitor_runs.get_run_detail(active))

    def test_waiting_inbox_parent_closes_after_child_and_keeps_partial_result(self):
        parent = monitor_runs.create_run(run_kind="inbox", task_name="接收", source="manual", subject="三体（2023）")
        monitor_runs.wait_run(
            parent,
            summary="已分发，等待 STRM 同步",
            result={"moved": 1, "left": 1, "monitor_sync_events": 1},
        )
        child = monitor_runs.create_run(run_kind="change", task_name="电视剧", source="change", parent_run_id=parent, subject="文件变更")
        monitor_runs.start_run(child)
        monitor_runs.finish_run(child, status="completed", summary="生成 STRM 2", result={"generated": 2})

        self.assertEqual(monitor_runs.get_run_detail(parent)["run"]["status"], "partial")

    def test_inbox_detail_keeps_dispatch_record_and_hides_duplicate_change_event(self):
        parent = monitor_runs.create_run(run_kind="inbox", task_name="接收", source="manual", subject="示例剧")
        monitor_runs.record_event(
            parent,
            category="remote",
            operation="move",
            status="completed",
            title="示例剧 24 集",
            detail={"step": "接收夹分发", "old_path": "最近接收/示例剧", "new_path": "电视剧/示例剧"},
        )
        with db.db_connection() as conn:
            conn.execute(
                """INSERT INTO monitor_change_events(
                    dedupe_key, operation, old_path, new_path, task_name,
                    source_action, monitor_run_id, status, created_at, updated_at
                ) VALUES (?, 'move', ?, ?, ?, ?, ?, 'completed', ?, ?)""",
                (
                    "inbox-dispatch-event",
                    "最近接收/示例剧",
                    "电视剧/示例剧",
                    "电视剧",
                    "scraper-job:1:quick-import",
                    parent,
                    "2026-09-24 05:00:00",
                    "2026-09-24 05:00:00",
                ),
            )
            conn.commit()

        detail = monitor_runs.get_run_detail(parent, category="remote")

        self.assertEqual(detail["counts"]["remote"], 1)
        self.assertEqual([event["title"] for event in detail["events"]], ["示例剧 24 集"])

    def test_waiting_inbox_parent_with_left_items_stays_active_until_child_finishes(self):
        parent = monitor_runs.create_run(run_kind="inbox", task_name="接收", source="manual", subject="混合结果")
        monitor_runs.wait_run(
            parent,
            summary="已分发，等待 STRM 同步",
            result={
                "moved": [{"name": "已分发"}],
                "left": [{"name": "未识别"}],
                "monitor_sync_events": 1,
            },
        )
        child = monitor_runs.create_run(
            run_kind="change",
            task_name="电影",
            source="change",
            parent_run_id=parent,
            subject="文件变更",
        )
        monitor_runs.start_run(child)

        self.assertEqual(monitor_runs.reconcile_waiting_inbox_runs(), 0)
        self.assertEqual(monitor_runs.get_run_detail(parent)["run"]["status"], "waiting")
        self.assertEqual(monitor_runs.cleanup_runs(scope="all_finished")["deleted"], 0)

        monitor_runs.finish_run(child, status="completed", summary="生成 STRM 1")

        detail = monitor_runs.get_run_detail(parent)["run"]
        self.assertEqual(detail["status"], "partial")
        self.assertTrue(detail["finished_at"])

    def test_wait_run_reconciles_child_that_finished_before_parent_started_waiting(self):
        parent = monitor_runs.create_run(run_kind="inbox", task_name="接收", source="manual", subject="电影A")
        monitor_runs.start_run(parent)
        child = monitor_runs.create_run(
            run_kind="change",
            task_name="电影",
            source="change",
            parent_run_id=parent,
            subject="文件变更",
        )
        monitor_runs.start_run(child)
        monitor_runs.finish_run(child, status="completed", summary="生成 STRM 1")

        monitor_runs.wait_run(
            parent,
            summary="已分发，等待 STRM 同步",
            result={"moved": 1, "left": 0, "monitor_sync_events": 1},
        )

        detail = monitor_runs.get_run_detail(parent)["run"]
        self.assertEqual(detail["status"], "completed")
        self.assertTrue(detail["finished_at"])

    def test_waiting_inbox_parent_waits_for_every_child_and_keeps_downstream_failure(self):
        parent = monitor_runs.create_run(run_kind="inbox", task_name="接收", source="manual")
        child_one = monitor_runs.create_run(
            run_kind="change",
            task_name="电影",
            source="change",
            parent_run_id=parent,
        )
        child_two = monitor_runs.create_run(
            run_kind="change",
            task_name="电视剧",
            source="change",
            parent_run_id=parent,
        )
        monitor_runs.start_run(child_one)
        monitor_runs.start_run(child_two)
        monitor_runs.wait_run(
            parent,
            summary="已分发，等待 STRM 同步",
            result={"moved": 2, "left": 0, "monitor_sync_events": 2},
        )

        monitor_runs.finish_run(child_one, status="completed", summary="生成 STRM 1")
        self.assertEqual(monitor_runs.get_run_detail(parent)["run"]["status"], "waiting")

        monitor_runs.finish_run(child_two, status="failed", summary="同步失败")
        detail = monitor_runs.get_run_detail(parent)["run"]
        self.assertEqual(detail["status"], "partial")
        self.assertIn("未完成内容", detail["summary"])

    def test_startup_recovery_closes_interrupted_runs_and_unblocks_terminal_parent(self):
        parent = monitor_runs.create_run(run_kind="inbox", task_name="接收", source="manual")
        monitor_runs.finish_run(parent, status="partial", summary="留在接收夹 1 项", result={"left": 1})
        child = monitor_runs.create_run(
            run_kind="change",
            task_name="电影",
            source="change",
            parent_run_id=parent,
        )
        monitor_runs.start_run(child)
        queued = monitor_runs.create_run(run_kind="scan", task_name="电视剧", source="cron")

        recovered = monitor_runs.recover_interrupted_runs()

        self.assertEqual(recovered, {"running": 1, "queued": 1})
        self.assertEqual(monitor_runs.get_run_detail(child)["run"]["status"], "failed")
        self.assertEqual(monitor_runs.get_run_detail(queued)["run"]["status"], "cancelled")
        self.assertEqual(monitor_runs.cleanup_runs(scope="all_finished")["deleted"], 3)

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

        self.assertEqual(monitor_runs.cleanup_runs(scope="all_finished")["deleted"], 0)
        self.assertTrue(monitor_runs.get_run_detail(parent))

    def test_cleanup_all_finished_deletes_terminal_runs_but_keeps_active_chain(self):
        completed = monitor_runs.create_run(run_kind="scan", task_name="电影", source="manual")
        failed = monitor_runs.create_run(run_kind="scan", task_name="电视剧", source="manual")
        parent = monitor_runs.create_run(run_kind="inbox", task_name="接收", source="manual")
        active = monitor_runs.create_run(run_kind="scan", task_name="电影", source="cron")
        child = monitor_runs.create_run(run_kind="change", task_name="电视剧", source="change", parent_run_id=parent)
        monitor_runs.finish_run(completed, status="completed", summary="完成")
        monitor_runs.finish_run(failed, status="failed", summary="失败")
        monitor_runs.finish_run(parent, status="completed", summary="等待后续同步")
        monitor_runs.start_run(child)

        preview = monitor_runs.cleanup_runs(scope="all_finished", preview=True)
        self.assertEqual(preview, {"count": 2, "deleted": 0})
        self.assertEqual(monitor_runs.cleanup_runs(scope="all_finished")["deleted"], 2)
        self.assertFalse(monitor_runs.get_run_detail(completed))
        self.assertFalse(monitor_runs.get_run_detail(failed))
        self.assertTrue(monitor_runs.get_run_detail(parent))
        self.assertTrue(monitor_runs.get_run_detail(active))
        self.assertTrue(monitor_runs.get_run_detail(child))

    def test_cleanup_expired_only_deletes_runs_older_than_retention_days(self):
        expired = monitor_runs.create_run(run_kind="scan", task_name="电影", source="manual")
        recent = monitor_runs.create_run(run_kind="scan", task_name="电视剧", source="manual")
        monitor_runs.finish_run(expired, status="completed", summary="旧记录")
        monitor_runs.finish_run(recent, status="failed", summary="新记录")
        with db.db_connection() as conn:
            conn.execute(
                "UPDATE monitor_runs SET finished_at = ? WHERE id = ?",
                ((datetime.now() - timedelta(days=31)).isoformat(timespec="seconds"), expired),
            )
            conn.commit()

        preview = monitor_runs.cleanup_runs(scope="expired", days=30, preview=True)
        self.assertEqual(preview, {"count": 1, "deleted": 0})
        self.assertEqual(monitor_runs.cleanup_runs(scope="expired", days=30)["deleted"], 1)
        self.assertFalse(monitor_runs.get_run_detail(expired))
        self.assertTrue(monitor_runs.get_run_detail(recent))

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

    def test_list_runs_filters_by_workflow_and_exposes_downstream_context(self):
        inbox = monitor_runs.create_run(
            run_kind="inbox", task_name="接收", source="manual", subject="示例电影"
        )
        monitor_runs.finish_run(inbox, status="completed", summary="分发完成")
        change = monitor_runs.create_run(
            run_kind="change",
            task_name="电影",
            source="change",
            parent_run_id=inbox,
            subject="示例电影",
        )
        monitor_runs.finish_run(change, status="completed", summary="同步完成")

        default_ids = {item["id"] for item in monitor_runs.list_runs()["runs"]}
        change_page = monitor_runs.list_runs(run_kind="change")

        self.assertIn(inbox, default_ids)
        self.assertNotIn(change, default_ids)
        self.assertEqual([item["id"] for item in change_page["runs"]], [change])
        self.assertEqual(change_page["runs"][0]["parent_task_name"], "接收")
        self.assertEqual(change_page["runs"][0]["parent_subject"], "示例电影")

    def test_list_runs_ignores_unknown_workflow_filter(self):
        run_id = monitor_runs.create_run(run_kind="scan", task_name="电影", source="manual")

        page = monitor_runs.list_runs(run_kind="unexpected")

        self.assertEqual([item["id"] for item in page["runs"]], [run_id])

    def test_default_list_hides_downstream_run_linked_without_parent_id(self):
        parent = monitor_runs.create_run(run_kind="inbox", task_name="接收", source="manual")
        child = monitor_runs.create_run(run_kind="change", task_name="电影", source="change")
        monitor_runs.link_runs(parent, child, relation="downstream")

        default_ids = {item["id"] for item in monitor_runs.list_runs()["runs"]}
        change_ids = {item["id"] for item in monitor_runs.list_runs(run_kind="change")["runs"]}

        self.assertIn(parent, default_ids)
        self.assertNotIn(child, default_ids)
        self.assertIn(child, change_ids)

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

    def _insert_change_event(self, *, run_id: str, operation: str, old_path: str, new_path: str, status: str = "completed") -> None:
        with db.db_connection() as conn:
            conn.execute(
                """INSERT INTO monitor_change_events(
                    dedupe_key, operation, old_path, new_path, task_name,
                    source_action, monitor_run_id, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    f"{operation}:{old_path}->{new_path}",
                    operation,
                    old_path,
                    new_path,
                    "电视剧",
                    "scraper",
                    run_id,
                    status,
                    "2026-09-24 05:54:05",
                    "2026-09-24 05:54:05",
                ),
            )
            conn.commit()

    def test_change_run_detail_lists_claimed_network_changes(self):
        """变更同步运行要能看到它实际改动的网盘内容，而不是只显示 STRM 明细。"""
        run_id = monitor_runs.create_run(
            run_kind="change",
            task_name="电视剧",
            source="change",
            scope={"kind": "events"},
            subject="文件变更",
        )
        monitor_runs.start_run(run_id, subject="文件变更", scope={"kind": "events"})
        self._insert_change_event(
            run_id=run_id,
            operation="rename",
            old_path="电视剧/飞到我心上/S01E01 [2160p].mkv",
            new_path="电视剧/飞到我心上/S01E01.mkv",
        )
        monitor_runs.finish_run(run_id, status="completed", summary="已同步 1 条网盘变更", result={"completed": 1})

        detail = monitor_runs.get_run_detail(run_id, category="remote")

        self.assertEqual(detail["counts"]["remote"], 1)
        self.assertEqual(detail["events"][0]["detail"]["operation_label"], "网盘重命名")
        self.assertEqual(detail["events"][0]["detail"]["new_name"], "S01E01.mkv")

    def test_manual_required_change_event_counts_as_problem(self):
        """需补扫的网盘变更要出现在“问题”里，否则“部分完成”没有任何解释。"""
        run_id = monitor_runs.create_run(
            run_kind="change",
            task_name="电视剧",
            source="change",
            scope={"kind": "events"},
            subject="文件变更",
        )
        self._insert_change_event(
            run_id=run_id,
            operation="rename",
            old_path="电视剧/飞到我心上 24集全",
            new_path="电视剧/飞到我心上 (2026)",
            status="manual_required",
        )
        monitor_runs.finish_run(
            run_id,
            status="partial",
            summary="已同步 1 条网盘变更，1 个目录需要手动监控",
            result={"completed": 1, "manual_required": 1},
        )

        detail = monitor_runs.get_run_detail(run_id, category="problem")

        self.assertEqual(detail["counts"]["problem"], 1)
        self.assertEqual(len(detail["events"]), 1)

    def test_list_runs_counts_children_once_and_keeps_link_index(self):
        parent = monitor_runs.create_run(run_kind="inbox", task_name="接收", source="manual", subject="示例剧")
        direct_child = monitor_runs.create_run(
            run_kind="change", task_name="电视剧", source="change", parent_run_id=parent, subject="文件变更"
        )
        linked_child = monitor_runs.create_run(
            run_kind="change", task_name="电视剧", source="change", subject="文件变更"
        )
        monitor_runs.link_runs(parent, linked_child, relation="downstream")
        for run_id in (direct_child, linked_child):
            monitor_runs.finish_run(run_id, status="completed", summary="完成", result={})

        page = monitor_runs.list_runs(include_children=True)
        parent_row = next(run for run in page["runs"] if run["id"] == parent)

        self.assertEqual(parent_row["child_count"], 2)
        with db.db_connection() as conn:
            indexes = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'monitor_run_links'"
                ).fetchall()
            }
        self.assertIn("idx_monitor_run_links_related", indexes)

    def test_repair_change_event_owners_only_attributes_unambiguous_events(self):
        run_one = monitor_runs.create_run(run_kind="change", task_name="电视剧", source="change", subject="文件变更")
        monitor_runs.start_run(run_one, subject="文件变更", scope={"kind": "events"})
        run_two = monitor_runs.create_run(run_kind="change", task_name="电影", source="change", subject="文件变更")
        monitor_runs.start_run(run_two, subject="文件变更", scope={"kind": "events"})
        with db.db_connection() as conn:
            started = conn.execute("SELECT started_at FROM monitor_runs WHERE id = ?", (run_one,)).fetchone()[0]
        monitor_runs.finish_run(run_one, status="completed", summary="完成", result={"completed": 2})
        monitor_runs.finish_run(run_two, status="completed", summary="完成", result={})
        with db.db_connection() as conn:
            finished = conn.execute("SELECT finished_at FROM monitor_runs WHERE id = ?", (run_one,)).fetchone()[0]
            for index in range(2):
                conn.execute(
                    """INSERT INTO monitor_change_events(
                        dedupe_key, operation, old_path, new_path, task_name,
                        source_action, monitor_run_id, status, created_at, updated_at, completed_at
                    ) VALUES (?, 'rename', ?, ?, '电视剧', 'scraper', '', 'completed', ?, ?, ?)""",
                    (f"repair-{index}", f"电视剧/old{index}.mkv", f"电视剧/new{index}.mkv", started, finished, finished),
                )
            # 完成时间不在任何变更运行区间内：不能猜。
            conn.execute(
                """INSERT INTO monitor_change_events(
                    dedupe_key, operation, old_path, new_path, task_name,
                    source_action, monitor_run_id, status, created_at, updated_at, completed_at
                ) VALUES ('repair-outside', 'rename', '电视剧/a.mkv', '电视剧/b.mkv', '电视剧',
                          'scraper', '', 'completed', '2020-01-01 00:00:00', '2020-01-01 00:00:00', '2020-01-01 00:00:00')""",
            )
            conn.commit()

        repaired = monitor_runs.repair_change_event_owners()

        self.assertEqual(repaired, 2)
        detail = monitor_runs.get_run_detail(run_one, category="remote")
        self.assertEqual(detail["counts"]["remote"], 2)
        with db.db_connection() as conn:
            outside = conn.execute(
                "SELECT monitor_run_id FROM monitor_change_events WHERE dedupe_key = 'repair-outside'"
            ).fetchone()[0]
            again = monitor_runs.repair_change_event_owners()
        self.assertEqual(outside, "")
        self.assertEqual(again, 0)

    def test_cleanup_can_be_limited_to_the_selected_task(self):
        """运行记录页的“清空该任务记录”只影响该任务的已结束记录。"""
        other_task = monitor_runs.create_run(run_kind="scan", task_name="电影", source="cron", subject="全部目录")
        monitor_runs.finish_run(other_task, status="completed", summary="完成", result={})
        target_task = monitor_runs.create_run(run_kind="scan", task_name="电视剧", source="cron", subject="全部目录")
        monitor_runs.finish_run(target_task, status="completed", summary="完成", result={})
        active_task = monitor_runs.create_run(run_kind="scan", task_name="电视剧", source="manual", subject="全部目录")

        preview = monitor_runs.cleanup_runs(scope="all_finished", task_name="电视剧", preview=True)
        result = monitor_runs.cleanup_runs(scope="all_finished", task_name="电视剧")

        self.assertEqual(preview["count"], 1)
        self.assertEqual(result["deleted"], 1)
        self.assertTrue(monitor_runs.get_run_detail(other_task))
        self.assertTrue(monitor_runs.get_run_detail(active_task))
        self.assertFalse(monitor_runs.get_run_detail(target_task))
