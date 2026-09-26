import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from app import db
from app.services import monitor, monitor_changes, monitor_runs, quick_import


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

    def test_list_runs_orders_by_start_time_not_updated_at(self):
        """列表按开始时间排序：后台状态更新（updated_at）不再让条目跳到最前。"""
        older = monitor_runs.create_run(run_kind="scan", task_name="电视剧", source="manual")
        newer = monitor_runs.create_run(run_kind="scan", task_name="电视剧", source="manual")
        with db.db_connection() as conn:
            conn.execute(
                "UPDATE monitor_runs SET queued_at = ?, started_at = ?, updated_at = ? WHERE id = ?",
                ("2026-09-26T19:59:00", "2026-09-26T20:00:00", "2026-09-27T02:58:00", older),
            )
            conn.execute(
                "UPDATE monitor_runs SET queued_at = ?, started_at = ?, updated_at = ? WHERE id = ?",
                ("2026-09-27T02:20:00", "2026-09-27T02:20:05", "2026-09-27T02:20:06", newer),
            )
            conn.commit()

        page = monitor_runs.list_runs()

        self.assertEqual([run["id"] for run in page["runs"]][:2], [newer, older])

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

        self.assertEqual(monitor_runs.reconcile_waiting_runs(), 0)
        self.assertEqual(monitor_runs.get_run_detail(parent)["run"]["status"], "waiting")
        self.assertEqual(monitor_runs.cleanup_runs(scope="all_finished")["deleted"], 0)

        monitor_runs.finish_run(child, status="completed", summary="生成 STRM 1")

        detail = monitor_runs.get_run_detail(parent)["run"]
        self.assertEqual(detail["status"], "partial")
        self.assertTrue(detail["finished_at"])

    def _event_id(self, dedupe_key: str) -> int:
        with db.db_connection() as conn:
            row = conn.execute(
                "SELECT id FROM monitor_change_events WHERE dedupe_key = ?", (dedupe_key,)
            ).fetchone()
        return int(row[0] or 0) if row else 0

    def _add_change_event(self, run_id: str, dedupe_key: str, task_name: str, status: str = "manual_required") -> int:
        with db.db_connection() as conn:
            conn.execute(
                """INSERT INTO monitor_change_events(
                    dedupe_key, operation, old_path, new_path, task_name,
                    source_action, monitor_run_id, status, created_at, updated_at
                ) VALUES (?, 'move', ?, ?, ?, 'scraper-job:1:quick-import', ?, ?, ?, ?)""",
                (
                    dedupe_key,
                    f"最近接收/{dedupe_key}",
                    f"{task_name}/{dedupe_key}",
                    task_name,
                    run_id,
                    status,
                    "2026-09-24 21:23:58",
                    "2026-09-24 21:23:58",
                ),
            )
            conn.commit()
        return self._event_id(dedupe_key)

    def _dispatch_auto_rescan_batch(self, *, items: int = 6, task_name: str = "最近接收"):
        """复现接收夹分发：父运行等待，每条条目派生一条变更同步 + 自动补扫。"""
        parent = monitor_runs.create_run(run_kind="inbox", task_name=task_name, source="manual", subject="识别中")
        monitor_runs.start_run(parent)
        monitor_runs.wait_run(
            parent,
            summary="已分发，等待 STRM 同步",
            result={"moved": items, "left": 0, "monitor_sync_events": items},
        )
        chain = []
        for index in range(items):
            media_task = "电影" if index % 2 else "电视剧"
            event_id = self._add_change_event(parent, f"batch-event-{index}", media_task)
            change_run = monitor_runs.create_run(
                run_kind="change", task_name=media_task, source="change",
                parent_run_id=parent, subject="文件变更", scope={"kind": "events"},
            )
            monitor_runs.start_run(change_run, subject="文件变更", scope={"kind": "events"})
            rescan = monitor_runs.create_run(
                run_kind="scan", task_name=media_task, source="auto_rescan",
                subject=f"影视{index}",
            )
            monitor_runs.link_runs(change_run, rescan, relation="downstream")
            monitor_runs.wait_run(
                change_run,
                summary="已同步 1 条网盘变更，等待自动补扫 1 个目录",
                result={
                    "completed": 1, "failed": 0, "generated": 0, "deleted": 0,
                    "manual_required": 1, "auto_rescan": 1, "waiting_children": 1,
                },
            )
            chain.append({"task_name": media_task, "change": change_run, "rescan": rescan, "event_id": event_id})
        return parent, chain

    def test_inbox_batch_settles_completed_after_auto_rescan_finishes(self):
        parent, chain = self._dispatch_auto_rescan_batch()

        self.assertEqual(monitor_runs.get_run_detail(parent)["run"]["status"], "waiting")
        for item in chain:
            monitor_runs.start_run(item["rescan"])
            # 补扫 runner 的真实顺序是“先清需手动监控事件、再收尾运行”。
            monitor_changes.complete_manual_required_monitor_events(item["task_name"], [item["event_id"]])
            monitor_runs.finish_run(
                item["rescan"], status="completed",
                summary="新增或更新 1 个本地播放文件", result={"generated": 1},
            )

        inbox = monitor_runs.get_run_detail(parent)["run"]
        self.assertEqual(inbox["status"], "completed")
        self.assertIn("成功分发 6 项", inbox["summary"])
        self.assertIn("STRM 同步全部结束", inbox["summary"])
        self.assertNotIn("个任务", inbox["summary"])
        self.assertEqual(
            {monitor_runs.get_run_detail(item["change"])["run"]["status"] for item in chain},
            {"completed"},
        )

    def test_manual_required_cleared_after_rescan_finish_still_settles_completed(self):
        """补扫 runner 先收尾、后清事件（或事件被别的扫描补清）时不能永久停在部分完成。"""
        parent, chain = self._dispatch_auto_rescan_batch(items=2)

        for item in chain:
            monitor_runs.start_run(item["rescan"])
            monitor_runs.finish_run(
                item["rescan"], status="completed",
                summary="新增或更新 1 个本地播放文件", result={"generated": 1},
            )
            monitor_changes.complete_manual_required_monitor_events(item["task_name"], [item["event_id"]])

        self.assertEqual(monitor_runs.get_run_detail(parent)["run"]["status"], "completed")
        self.assertEqual(
            {monitor_runs.get_run_detail(item["change"])["run"]["status"] for item in chain},
            {"completed"},
        )

    def test_inbox_batch_stays_partial_with_reason_when_auto_rescan_fails(self):
        parent, chain = self._dispatch_auto_rescan_batch(items=1)
        item = chain[0]

        monitor_runs.start_run(item["rescan"])
        monitor_runs.finish_run(item["rescan"], status="failed", summary="目录读取失败")

        inbox = monitor_runs.get_run_detail(parent)["run"]
        self.assertEqual(inbox["status"], "partial")
        self.assertIn("仍有未完成内容", inbox["summary"])
        self.assertIn("仍需同步", inbox["summary"])
        self.assertNotIn("个任务", inbox["summary"])
        self.assertIn("未完成", monitor_runs.get_run_detail(item["change"])["run"]["summary"])

    def test_settle_deferred_runs_resettles_legacy_premature_partial(self):
        parent = monitor_runs.create_run(run_kind="inbox", task_name="最近接收", source="manual", subject="历史记录")
        monitor_runs.start_run(parent)
        monitor_runs.wait_run(
            parent,
            summary="已分发，等待 STRM 同步",
            result={"moved": 6, "left": 0, "monitor_sync_events": 6},
        )
        change_run = monitor_runs.create_run(
            run_kind="change", task_name="电影", source="change", parent_run_id=parent, subject="文件变更",
        )
        monitor_runs.start_run(change_run)
        self._add_change_event(parent, "legacy-event", "电影", status="completed")
        monitor_runs.finish_run(
            change_run, status="partial", summary="已同步 1 条网盘变更，1 个目录需要手动监控",
            result={"completed": 1, "failed": 0, "manual_required": 1},
        )
        monitor_runs.finish_run(parent, status="partial", summary="后续同步结束，仍有未完成内容（1 个任务）")

        settled = monitor_runs.settle_deferred_runs()

        self.assertEqual(settled, {"change": 1, "inbox": 1})
        self.assertEqual(monitor_runs.get_run_detail(change_run)["run"]["status"], "completed")
        self.assertEqual(monitor_runs.get_run_detail(parent)["run"]["status"], "completed")
        self.assertEqual(monitor_runs.settle_deferred_runs(), {"change": 0, "inbox": 0})
        self.assertTrue(
            any(event["operation"] == "resettled" for event in monitor_runs.get_run_detail(parent)["events"])
        )

    def test_settle_deferred_runs_keeps_real_failures_untouched(self):
        parent = monitor_runs.create_run(run_kind="inbox", task_name="最近接收", source="manual", subject="真失败")
        monitor_runs.start_run(parent)
        monitor_runs.wait_run(
            parent,
            summary="等待后续同步",
            result={"moved": 1, "left": 0, "monitor_sync_events": 1},
        )
        change_run = monitor_runs.create_run(
            run_kind="change", task_name="电视剧", source="change", parent_run_id=parent, subject="文件变更",
        )
        monitor_runs.finish_run(change_run, status="failed", summary="变更同步失败")
        monitor_runs.finish_run(parent, status="partial", summary="后续同步结束，仍有未完成内容")

        self.assertEqual(monitor_runs.settle_deferred_runs(), {"change": 0, "inbox": 0})
        self.assertEqual(monitor_runs.get_run_detail(parent)["run"]["status"], "partial")
        self.assertEqual(monitor_runs.get_run_detail(change_run)["run"]["status"], "failed")

    def test_run_list_groups_dispatched_runs_under_parent(self):
        """列表按工作单元分组：父任务一行，分发生出来的子任务折叠在 children 里。"""
        parent, chain = self._dispatch_auto_rescan_batch(items=2)
        for item in chain:
            monitor_runs.finish_run(
                item["rescan"], status="completed",
                summary="新增或更新 1 个本地播放文件", result={"generated": 1},
            )
            monitor_changes.complete_manual_required_monitor_events(item["task_name"], [item["event_id"]])

        page = monitor_runs.list_runs()
        listed_ids = [run["id"] for run in page["runs"]]
        listed_by_id = {run["id"]: run for run in page["runs"]}

        # 顶层只有接收夹父任务，子任务（变更同步 + 扫描）都在它的 children 里。
        self.assertEqual(listed_ids, [parent])
        parent_row = listed_by_id[parent]
        self.assertEqual(parent_row["child_count"], 4)
        self.assertEqual(
            {item["id"] for item in parent_row["children"]},
            {item["rescan"] for item in chain} | {item["change"] for item in chain},
        )
        for item in chain:
            child = next(entry for entry in parent_row["children"] if entry["id"] == item["rescan"])
            self.assertEqual(child["source"], "auto_rescan")
            self.assertEqual(child["run_kind"], "scan")
            self.assertEqual(child["depth"], 2)

        flat = monitor_runs.list_runs(run_kind="change")
        self.assertIn(chain[0]["change"], [run["id"] for run in flat["runs"]])

    def test_downstream_activity_keeps_head_updated_at_ahead_of_children(self):
        parent, chain = self._dispatch_auto_rescan_batch(items=1)
        item = chain[0]
        with db.db_connection() as conn:
            conn.execute(
                "UPDATE monitor_runs SET updated_at = '2026-09-01 00:00:00' WHERE id IN (?, ?)",
                (parent, item["change"]),
            )
            conn.commit()

        monitor_changes.complete_manual_required_monitor_events(item["task_name"], [item["event_id"]])
        monitor_runs.finish_run(
            item["rescan"], status="completed",
            summary="新增或更新 1 个本地播放文件", result={"generated": 1},
        )

        with db.db_connection() as conn:
            parent_updated = str(
                conn.execute("SELECT updated_at FROM monitor_runs WHERE id = ?", (parent,)).fetchone()[0]
            )
        rescan_updated = str(monitor_runs.get_run_detail(item["rescan"])["run"]["updated_at"])
        # 同秒内的下游也不能把触发记录挤到后面：祖先的活动时间要严格更新。
        self.assertGreater(parent_updated, rescan_updated)
        page = monitor_runs.list_runs()
        self.assertEqual([run["id"] for run in page["runs"]], [parent])
        self.assertIn(item["rescan"], [entry["id"] for entry in page["runs"][0]["children"]])

    def test_run_detail_exposes_downstream_chain_with_depth(self):
        parent, chain = self._dispatch_auto_rescan_batch(items=1)

        detail = monitor_runs.get_run_detail(parent)

        self.assertEqual(
            [(item["run_kind"], item["depth"]) for item in detail["descendants"]],
            [("change", 1), ("scan", 2)],
        )
        self.assertEqual(detail["children"][0]["id"], chain[0]["change"])

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

    def test_list_runs_supports_grouped_source_and_status_filters(self):
        """筛选只暴露用户视角的几组：手动 / 定时 / 推送 / 导入 / 系统跟进、进行中 / 已完成 / 需处理 / 已中断。"""
        manual = monitor_runs.create_run(run_kind="scan", task_name="电影", source="manual", subject="手动")
        monitor_runs.finish_run(manual, status="completed", summary="完成")
        retry = monitor_runs.create_run(run_kind="scan", task_name="电影", source="retry", subject="重试")
        monitor_runs.finish_run(retry, status="failed", summary="失败")
        cron = monitor_runs.create_run(run_kind="scan", task_name="电影", source="cron", subject="定时")
        monitor_runs.finish_run(cron, status="no_change", summary="无变化")
        dispatch = monitor_runs.create_run(run_kind="scan", task_name="电影", source="inbox_dispatch", subject="分发")
        monitor_runs.finish_run(dispatch, status="partial", summary="部分完成")

        manual_group = {run["id"] for run in monitor_runs.list_runs(source_group="manual")["runs"]}
        self.assertEqual(manual_group, {manual, retry})
        followup_group = {run["id"] for run in monitor_runs.list_runs(source_group="followup")["runs"]}
        self.assertEqual(followup_group, {dispatch})
        attention_group = {run["id"] for run in monitor_runs.list_runs(status_group="attention")["runs"]}
        self.assertEqual(attention_group, {retry, dispatch})
        done_group = {run["id"] for run in monitor_runs.list_runs(status_group="done")["runs"]}
        self.assertEqual(done_group, {manual, cron})
        # 合并进来的其它来源也算在这一组里。
        monitor_runs.add_source(manual, "cron", "")
        scheduled_group = {run["id"] for run in monitor_runs.list_runs(source_group="scheduled")["runs"]}
        self.assertIn(manual, scheduled_group)
        # 未知分组不生效，不能把列表清空。
        self.assertEqual(len(monitor_runs.list_runs(source_group="unknown")["runs"]), 4)

    def test_default_list_groups_link_only_dispatched_run_under_parent(self):
        """只挂 downstream 关联的分发任务也归到父任务下，不再单独占一行。"""
        parent = monitor_runs.create_run(run_kind="inbox", task_name="接收", source="manual")
        dispatched = monitor_runs.create_run(run_kind="scan", task_name="电影", source="auto_rescan")
        monitor_runs.link_runs(parent, dispatched, relation="downstream")
        child = monitor_runs.create_run(run_kind="change", task_name="电影", source="change", parent_run_id=parent)

        page = monitor_runs.list_runs()
        default_ids = {item["id"] for item in page["runs"]}
        children_ids = {item["id"] for item in page["runs"][0]["children"]}
        change_ids = {item["id"] for item in monitor_runs.list_runs(run_kind="change")["runs"]}

        self.assertEqual(default_ids, {parent})
        self.assertIn(dispatched, children_ids)
        self.assertIn(child, children_ids)
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

    def test_dispatch_child_queues_its_own_independent_run(self):
        """分发的每个条目一条独立扫描任务，来源标注接收夹分发、不挂接收夹父运行。"""
        queued = []
        status = {"running": True, "current_task": "其他任务", "queued": []}
        cfg = {
            "mount_points": [{"provider": "115", "prefix": "/115"}],
            "monitor_tasks": [self._scan_task()],
        }
        with patch.object(monitor, "monitor_queue", queued), \
                patch.object(monitor, "monitor_status", status), \
                patch.object(monitor, "get_config", return_value=cfg), \
                patch.object(monitor, "schedule_ui_state_push", Mock()):
            run_id = monitor.queue_inbox_dispatch_scan(cfg, "电视剧/三体 S01")

        self.assertTrue(run_id)
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0]["run_source"], "inbox_dispatch")
        self.assertEqual(queued[0]["trigger"], "manual")
        detail = monitor_runs.get_run_detail(run_id)
        self.assertEqual(detail["run"]["parent_run_id"], "")
        self.assertEqual(detail["run"]["source"], "inbox_dispatch")
        self.assertEqual(detail["run"]["scope"], {"kind": "paths", "paths": ["/电视剧/三体 S01"]})
        self.assertEqual(detail["run"]["subject"], "三体 S01")

    def test_disabled_task_still_accepts_auto_followups(self):
        """停用只拦住自动定时/资源触发；已经分发的条目仍要完成 STRM 同步。"""
        queued = []
        status = {"running": True, "current_task": "其他任务", "queued": []}
        disabled_task = {**self._scan_task(), "enabled": False}
        cfg = {"monitor_tasks": [disabled_task]}
        with patch.object(monitor, "monitor_queue", queued), \
                patch.object(monitor, "monitor_status", status), \
                patch.object(monitor, "get_config", return_value=cfg), \
                patch.object(monitor, "schedule_ui_state_push", Mock()):
            cron_result = monitor.queue_monitor_job("电视剧监控", "cron")
            rescan_result = monitor.queue_monitor_job(
                "电视剧监控",
                "manual",
                {"savepaths": ["电视剧/三体 S01"]},
                run_source="auto_rescan",
                force_new=True,
                return_details=True,
            )

        self.assertEqual(cron_result, "disabled")
        self.assertEqual(rescan_result["status"], "queued")
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0]["run_source"], "auto_rescan")

    def test_change_queue_run_starts_with_event_scope(self):
        """变更同步的范围是“本次文件变更涉及的目录”，入队时不能写成“全部目录”。"""
        queued = []
        status = {"running": True, "current_task": "其他任务", "queued": []}
        cfg = {"monitor_tasks": [self._scan_task()]}
        with patch.object(monitor, "monitor_queue", queued), \
                patch.object(monitor, "monitor_status", status), \
                patch.object(monitor, "get_config", return_value=cfg), \
                patch.object(monitor, "schedule_ui_state_push", Mock()):
            result = monitor.queue_monitor_job(
                "电视剧监控",
                "change",
                {"mode": "change"},
                return_details=True,
            )

        self.assertEqual(result["status"], "queued")
        detail = monitor_runs.get_run_detail(result["run_id"])
        self.assertEqual(detail["run"]["run_kind"], "change")
        self.assertEqual(detail["run"]["scope"], {"kind": "events"})
        queued_event = next(item for item in detail["events"] if item.get("operation") == "queued")
        self.assertEqual(queued_event["detail"]["scope"], {"kind": "events"})

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


class MonitorRunDispatchPairTest(unittest.TestCase):
    """一次分发产生的「变更同步 + 独立目录同步」在默认列表里合并成一行。"""

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

    def _make_run(
        self,
        *,
        run_kind: str,
        source: str,
        paths,
        subject: str,
        queued_at: str,
        task_name: str = "电视剧",
        status: str = "completed",
        summary: str = "",
    ) -> str:
        run_id = monitor_runs.create_run(
            run_kind=run_kind,
            task_name=task_name,
            source=source,
            scope={"kind": "paths", "paths": list(paths)},
            subject=subject,
        )
        monitor_runs.start_run(run_id)
        monitor_runs.finish_run(run_id, status=status, summary=summary, result={})
        with db.db_connection() as conn:
            conn.execute(
                "UPDATE monitor_runs SET queued_at = ?, started_at = ? WHERE id = ?",
                (queued_at, queued_at, run_id),
            )
            conn.commit()
        return run_id

    def test_default_list_merges_change_and_dispatched_scan(self):
        change = self._make_run(
            run_kind="change", source="change",
            paths=["115自存电视剧/示例剧"], subject="示例剧",
            queued_at="2026-09-27T05:54:43", summary="已同步 1 条网盘变更。",
        )
        scan = self._make_run(
            run_kind="scan", source="inbox_dispatch",
            paths=["/115自存电视剧/示例剧"], subject="示例剧",
            queued_at="2026-09-27T05:54:43", summary="检查完成：新增或更新 6 个本地播放文件。",
        )

        page = monitor_runs.list_runs()

        # 主行是目录同步；前导斜杠不同的范围也能配对，变更同步不再单独成行。
        self.assertEqual([run["id"] for run in page["runs"]], [scan])
        merged = page["runs"][0]
        self.assertEqual(merged["run_kind"], "scan")
        self.assertEqual(merged["upstream_change"]["id"], change)
        self.assertIn("已同步 1 条网盘变更", merged["upstream_change"]["summary"])

        # 详情同样能拿到上游；变更同步看自己没有“上游”。
        self.assertEqual(monitor_runs.get_run_detail(scan)["upstream_change"]["id"], change)
        self.assertFalse(monitor_runs.get_run_detail(change).get("upstream_change"))

    def test_pairing_requires_same_task_scope_and_time_window(self):
        change = self._make_run(
            run_kind="change", source="change",
            paths=["115自存电视剧/A"], subject="A", queued_at="2026-09-27T05:00:00",
        )
        far_scan = self._make_run(
            run_kind="scan", source="inbox_dispatch",
            paths=["/115自存电视剧/A"], subject="A", queued_at="2026-09-27T05:05:00",
        )
        other_scope = self._make_run(
            run_kind="scan", source="inbox_dispatch",
            paths=["/115自存电视剧/B"], subject="B", queued_at="2026-09-27T05:00:00",
        )
        other_task = self._make_run(
            run_kind="scan", source="inbox_dispatch",
            paths=["/115自存电视剧/A"], subject="A", queued_at="2026-09-27T05:00:00",
            task_name="电影",
        )

        page = monitor_runs.list_runs()

        self.assertEqual(
            {run["id"] for run in page["runs"]},
            {change, far_scan, other_scope, other_task},
        )
        self.assertFalse(any(run.get("upstream_change") for run in page["runs"]))

    def test_each_change_pairs_at_most_once(self):
        change = self._make_run(
            run_kind="change", source="change",
            paths=["115自存电视剧/A"], subject="A", queued_at="2026-09-27T05:00:00",
        )
        first = self._make_run(
            run_kind="scan", source="inbox_dispatch",
            paths=["/115自存电视剧/A"], subject="A", queued_at="2026-09-27T05:00:01",
        )
        second = self._make_run(
            run_kind="scan", source="inbox_dispatch",
            paths=["/115自存电视剧/A"], subject="A", queued_at="2026-09-27T05:00:02",
        )

        page = monitor_runs.list_runs()

        self.assertEqual({run["id"] for run in page["runs"]}, {first, second})
        merged = [run for run in page["runs"] if run.get("upstream_change")]
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["upstream_change"]["id"], change)

    def test_filters_keep_flat_list_without_merging(self):
        change = self._make_run(
            run_kind="change", source="change",
            paths=["115自存电视剧/A"], subject="A", queued_at="2026-09-27T05:00:00",
        )
        scan = self._make_run(
            run_kind="scan", source="inbox_dispatch",
            paths=["/115自存电视剧/A"], subject="A", queued_at="2026-09-27T05:00:01",
        )

        scan_only = monitor_runs.list_runs(run_kind="scan")
        self.assertEqual([run["id"] for run in scan_only["runs"]], [scan])
        self.assertFalse(scan_only["runs"][0].get("upstream_change"))

        change_only = monitor_runs.list_runs(run_kind="change")
        self.assertEqual([run["id"] for run in change_only["runs"]], [change])

    def test_merged_pair_cursor_keeps_pagination_stable(self):
        older = self._make_run(
            run_kind="scan", source="manual",
            paths=["115自存电视剧/C"], subject="C", queued_at="2026-09-27T04:00:00",
        )
        change = self._make_run(
            run_kind="change", source="change",
            paths=["115自存电视剧/A"], subject="A", queued_at="2026-09-27T05:00:00",
        )
        scan = self._make_run(
            run_kind="scan", source="inbox_dispatch",
            paths=["/115自存电视剧/A"], subject="A", queued_at="2026-09-27T05:00:01",
        )

        first = monitor_runs.list_runs(limit=2)
        self.assertEqual([run["id"] for run in first["runs"]], [scan])
        self.assertEqual(first["runs"][0]["upstream_change"]["id"], change)
        self.assertTrue(first["has_more"])

        second = monitor_runs.list_runs(limit=2, cursor=first["next_cursor"])
        # 合并行按两个成员里更小的 id 收口，翻页既不跳过也不重复。
        self.assertEqual([run["id"] for run in second["runs"]], [older])
        self.assertFalse(second["has_more"])
