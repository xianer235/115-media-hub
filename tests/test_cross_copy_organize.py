"""跨盘补源「入库后整理」的测试。

两层：
1. 打标记：只有「订阅补源 + 单文件 + 复制成功」才标 ``organize_state='pending'``，
   手动复制、文件夹任务、被跳过的任务都不标；重试要清掉旧标记。
2. 定时器整理：成组、防抖、CAS 抢占、按开关跳过、成功/失败写回。

真正的改名交给 `build_scraper_rename_plan`，这里只用桩验证「调用参数对、结果写得对」。
"""

import asyncio
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from app import db
from app.services import cross_copy_jobs as ccj
from app.services import subscription_cross_copy_organize as organize

TASK_NAME = "光阴之外"


class FakeProvider:
    name = "115"
    label = "115网盘"
    supports_delete = True
    # run_cross_copy_job 会先确认目标网盘能上传，缺这个标记会被判「暂不支持上传」
    supports_upload = True

    def __init__(self, entries=None):
        self.entries = list(entries or [])
        self.deleted = []

    def get_cookie(self, _cfg=None):
        return "cookie-115"

    def list_entries(self, cookie, cid="0"):
        return list(self.entries)

    def delete_entries(self, cookie, entry_ids, parent_id=""):
        self.deleted.append((str(parent_id), list(entry_ids)))
        return {"ids": list(entry_ids)}


class FakeCopyResult:
    def __init__(self, status="uploaded", name="S01E42.mp4", message="上传完成"):
        self.status = status
        self.name = name
        self.message = message
        self.file_id = ""
        self.size = 1024

    def to_dict(self):
        return {"status": self.status, "name": self.name}


class OrganizeTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wb_cco_test_")
        self.original_db_path = db.DB_PATH
        self.original_db_ensured = db._DB_ENSURED
        db.DB_PATH = os.path.join(self.tmp, "test.db")
        db._DB_ENSURED = False
        db.ensure_db()
        with db.db_connection() as conn:
            conn.execute("DELETE FROM cross_copy_jobs")
            conn.commit()
        ccj._job_progress.clear()
        ccj._last_db_progress.clear()
        ccj._cancel_requested.clear()
        with ccj._sched_lock:
            ccj._queued.clear()
            ccj._active.clear()
        with ccj._running_lock:
            ccj._running.clear()
        self.cfg = {
            "cross_copy_notify_subscription": False,
            "cross_copy_notify_manual": False,
            "cross_copy_delete_source_after": False,
            "provider_enabled": {"115": True, "quark": True},
        }
        # 后台提交必须桩掉：retry 之类会真的把「跑任务」的协程丢到后台 loop 上，
        # 那条协程活得比用例长，等下一个用例换掉 db.DB_PATH 后它才写状态，
        # 于是把新库里同号（都从 1 开始）的任务改成 running —— 表现为随机失败。
        self._bg_patcher = mock.patch.object(ccj, "submit_background", mock.MagicMock())
        self._bg_patcher.start()

    def tearDown(self):
        self._bg_patcher.stop()
        db.DB_PATH = self.original_db_path
        db._DB_ENSURED = self.original_db_ensured
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _job(self, **overrides):
        params = dict(
            title="光阴之外",
            source_provider="quark",
            target_provider="115",
            source_file_id="staged-f1",
            target_dir_id="season-cid",
            target_savepath="115连载中/光阴之外 (2025)/Season 01",
            filename="S01E42.mp4",
            file_size=1024,
            origin="subscription",
            origin_ref=TASK_NAME,
        )
        params.update(overrides)
        return ccj.create_cross_copy_job(**params)

    def _row(self, job_id):
        return ccj.get_cross_copy_job(job_id)


class OrganizeMarkingTest(OrganizeTestBase):
    """复制成功收口时的标记：一条 UPDATE 里带上，不多写一次库。"""

    def _run_job(self, job_id, result):
        provider = FakeProvider()
        patchers = [
            mock.patch.object(ccj, "get_config", return_value=self.cfg),
            mock.patch.object(ccj, "_get_provider_or_none", return_value=provider),
            mock.patch.object(ccj, "_send_notify_content", mock.MagicMock()),
            mock.patch.object(ccj, "build_resume_state", return_value=None),
            mock.patch.object(ccj.xcc, "resolve_temp_dir", return_value=self.tmp),
            mock.patch.object(ccj.xcc, "copy_file_across_clouds", return_value=result),
            mock.patch.object(ccj, "submit_background", mock.MagicMock()),
        ]
        for patcher in patchers:
            patcher.start()
        try:
            asyncio.run(ccj.run_cross_copy_job(job_id))
        finally:
            for patcher in patchers:
                patcher.stop()

    def test_subscription_single_file_success_is_marked_pending(self):
        job_id = self._job()
        self._run_job(job_id, FakeCopyResult())

        row = self._row(job_id)
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["organize_state"], "pending")

    def test_manual_job_is_not_marked(self):
        job_id = self._job(origin="manual", origin_ref="")
        self._run_job(job_id, FakeCopyResult())

        self.assertEqual(self._row(job_id)["organize_state"], "")

    def test_folder_job_is_not_marked(self):
        job_id = self._job(source_is_dir=True)
        self._run_job(job_id, FakeCopyResult())

        self.assertEqual(self._row(job_id)["organize_state"], "")

    def test_skipped_result_is_not_marked(self):
        job_id = self._job()
        self._run_job(job_id, FakeCopyResult(status="skipped", message="目标已存在同文件"))

        row = self._row(job_id)
        self.assertEqual(row["status"], "skipped", row)
        self.assertEqual(row["organize_state"], "", row)

    def test_retry_clears_marking(self):
        job_id = self._job()
        ccj.update_cross_copy_job(
            job_id,
            status="completed",
            organize_state="done",
            organize_detail="已原地改名 1 个文件",
        )
        ccj.retry_cross_copy_job(job_id)

        row = self._row(job_id)
        self.assertEqual(row["organize_state"], "")
        self.assertEqual(row["organize_detail"], "")


class OrganizeSelectionTest(OrganizeTestBase):
    """待整理任务的筛选与成组。"""

    def _pending(self, **overrides):
        job_id = self._job(**overrides)
        ccj.update_cross_copy_job(
            job_id,
            status="completed",
            finished_at="2026-10-22T10:00:00",
            organize_state="pending",
        )
        return job_id

    def test_group_merges_same_dir_and_splits_others(self):
        a = self._pending(filename="S01E42.mp4")
        b = self._pending(filename="S01E43.mp4")
        c = self._pending(filename="S02E01.mp4", target_dir_id="season2-cid")
        jobs = [self._row(a), self._row(b), self._row(c)]

        groups = organize.group_jobs(jobs)

        self.assertEqual(len(groups), 2)
        self.assertEqual(len(groups[("115", "season-cid", TASK_NAME)]), 2)
        self.assertEqual(len(groups[("115", "season2-cid", TASK_NAME)]), 1)

    def test_debounce_window_excludes_fresh_jobs(self):
        fresh = self._pending()
        ccj.update_cross_copy_job(fresh, finished_at="2999-01-01T00:00:00")

        jobs = organize.list_organize_jobs(organize._organize_cutoff_text())

        self.assertEqual([int(job["id"]) for job in jobs], [])

    def test_jobs_without_finished_at_are_ignored(self):
        job_id = self._pending()
        ccj.update_cross_copy_job(job_id, finished_at="")

        self.assertEqual(organize.list_organize_jobs(organize._organize_cutoff_text()), [])

    def test_claim_is_cas(self):
        job_id = self._pending()

        self.assertEqual(organize._claim_jobs([job_id]), [job_id])
        self.assertEqual(organize._claim_jobs([job_id]), [])
        self.assertEqual(self._row(job_id)["organize_state"], "running")

    def test_stale_running_is_reset(self):
        job_id = self._pending()
        organize._claim_jobs([job_id])
        # update_cross_copy_job 会强制把 updated_at 写成当前时间，回拨不了；
        # 这里直接改库，模拟「进程重启后留下的旧 running」。
        with db.db_connection() as conn:
            conn.execute(
                "UPDATE cross_copy_jobs SET updated_at = ? WHERE id = ?",
                ("2000-01-01T00:00:00", job_id),
            )
            conn.commit()

        self.assertEqual(organize._reset_stale_running(), 1)
        self.assertEqual(self._row(job_id)["organize_state"], "pending")


class OrganizeGuardTest(unittest.TestCase):
    def test_requires_switch_and_tmdb(self):
        base = {"media_type": "tv", "organize_on_import": True, "tmdb_id": 281233}
        self.assertTrue(organize.organize_enabled(base))
        # 电影也整理：改成「片名 (年份).ext」，否则同名多资源进库后文件名各是各的
        self.assertTrue(organize.organize_enabled({**base, "media_type": "movie"}))
        self.assertFalse(organize.organize_enabled({**base, "organize_on_import": False}))
        self.assertFalse(organize.organize_enabled({**base, "tmdb_id": 0}))
        self.assertFalse(organize.organize_enabled({}))

    def test_find_task_by_name(self):
        cfg = {"subscription_tasks": [{"name": "别的"}, {"name": TASK_NAME, "tmdb_id": 1}]}
        self.assertEqual(organize.find_subscription_task(cfg, TASK_NAME)["tmdb_id"], 1)
        self.assertEqual(organize.find_subscription_task(cfg, "没有这个"), {})


class OrganizeLocateTest(unittest.IsolatedAsyncioTestCase):
    async def test_matches_by_name_and_size(self):
        provider = FakeProvider(
            entries=[
                {"fid": "wrong", "name": "S01E42.mp4", "size": 999, "is_dir": False},
                {"fid": "right", "name": "S01E42.mp4", "size": 1024, "is_dir": False},
            ]
        )
        located = await organize.locate_subscription_imported_files(
            provider,
            "cookie",
            "season-cid",
            "115连载中/光阴之外 (2025)/Season 01",
            [{"name": "S01E42.mp4", "size": 1024, "is_dir": False}],
        )

        self.assertEqual([item["id"] for item in located], ["right"])
        self.assertEqual(located[0]["parent_path"], "115连载中/光阴之外 (2025)/Season 01")

    async def test_missing_file_returns_empty(self):
        provider = FakeProvider(entries=[])
        located = await organize.locate_subscription_imported_files(
            provider, "cookie", "season-cid", "dir", [{"name": "S01E42.mp4", "size": 1024}]
        )
        self.assertEqual(located, [])


class OrganizeRunOnceTest(OrganizeTestBase):
    """定时器一轮：按开关跳过 / 成功写 done / 失败写 failed。"""

    def _seed(self):
        job_id = self._job()
        ccj.update_cross_copy_job(
            job_id, status="completed", finished_at="2026-10-22T10:00:00", organize_state="pending"
        )
        return job_id

    def _run(self, task, result, job_id):
        provider = FakeProvider()
        logs = []

        async def fake_log(text, level="info", compact=None):
            logs.append((text, level))

        with mock.patch.object(
            organize,
            "get_config",
            return_value={
                "provider_enabled": {"115": True},
                "subscription_tasks": [task] if task else [],
            },
        ), mock.patch.object(organize, "_get_provider_or_none", return_value=provider), \
                mock.patch.object(organize, "write_subscription_log", side_effect=fake_log), \
                mock.patch.object(
                    organize,
                    "organize_files_for_subscription_task",
                    new=mock.AsyncMock(return_value=result),
                ) as runner:
            stats = asyncio.run(organize.run_pending_organize_once())
        return stats, logs, runner, job_id

    def _task(self, **overrides):
        task = {
            "name": TASK_NAME,
            "media_type": "tv",
            "organize_on_import": True,
            "tmdb_id": 281233,
            "organize_options": {"file_name_mode": "standard"},
        }
        task.update(overrides)
        return task

    def test_success_marks_done(self):
        job_id = self._seed()
        stats, logs, runner, _ = self._run(
            self._task(),
            {"ok": True, "job_id": 77, "succeeded": 1, "failed": 0, "status": "completed"},
            job_id,
        )

        self.assertEqual(stats["done"], 1)
        row = self._row(job_id)
        self.assertEqual(row["organize_state"], "done")
        self.assertIn("已原地改名 1 个文件", row["organize_detail"])
        self.assertTrue(any("跨盘补源" in text for text, _level in logs))
        # 传给整理器的是成组的文件清单，不是单条
        kwargs = runner.await_args.kwargs
        self.assertEqual(kwargs["target_cid"], "season-cid")
        self.assertEqual(kwargs["target_savepath"], "115连载中/光阴之外 (2025)/Season 01")
        self.assertEqual([item["name"] for item in kwargs["imported_entries"]], ["S01E42.mp4"])

    def test_switch_off_marks_skipped_without_calling_scraper(self):
        job_id = self._seed()
        stats, _logs, runner, _ = self._run(
            self._task(organize_on_import=False),
            {"ok": True, "job_id": 1, "succeeded": 1, "failed": 0, "status": "completed"},
            job_id,
        )

        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(self._row(job_id)["organize_state"], "skipped")
        runner.assert_not_awaited()

    def test_missing_task_marks_skipped(self):
        job_id = self._seed()
        stats, _logs, runner, _ = self._run(None, {}, job_id)

        self.assertEqual(stats["skipped"], 1)
        row = self._row(job_id)
        self.assertEqual(row["organize_state"], "skipped")
        self.assertIn("订阅任务已不存在", row["organize_detail"])
        runner.assert_not_awaited()

    def test_failure_marks_failed_and_keeps_detail(self):
        job_id = self._seed()
        stats, logs, _runner, _ = self._run(
            self._task(),
            {"ok": False, "reason": "未在目标目录找到本次新入库的文件，保留原名", "level": "info"},
            job_id,
        )

        self.assertEqual(stats["failed"], 1)
        row = self._row(job_id)
        self.assertEqual(row["organize_state"], "failed")
        self.assertIn("未在目标目录找到", row["organize_detail"])
        self.assertTrue(any("保留原名" in text for text, _level in logs))

    def test_json_extra_is_not_touched(self):
        # organize_detail 是独立字段，不要塞进 result_json 破坏既有展示
        job_id = self._seed()
        self._run(self._task(), {"ok": True, "job_id": 9, "succeeded": 1, "status": "completed"}, job_id)

        row = self._row(job_id)
        self.assertEqual(json.loads(row["result_json"] or "{}"), {})


class OrganizeMonitorRefreshTest(OrganizeTestBase):
    """分组结束后触发监控扫描：先改名后扫描、口径与订阅导入一致。"""

    def _seed(self, **overrides):
        job_id = self._job(**overrides)
        ccj.update_cross_copy_job(
            job_id, status="completed", finished_at="2026-10-22T10:00:00", organize_state="pending"
        )
        return job_id

    def _run(self, task, result, monitor_tasks=None, queue_return="queued", provider="default"):
        fake_provider = FakeProvider() if provider == "default" else provider
        cfg = {
            "provider_enabled": {"115": True},
            "subscription_tasks": [task] if task else [],
            "mount_points": [{"provider": "115", "prefix": "/115"}],
            "monitor_tasks": (
                [{"name": "影视库监控", "scan_path": "/115/115连载中"}]
                if monitor_tasks is None
                else monitor_tasks
            ),
        }
        logs = []

        async def fake_log(text, level="info", compact=None):
            logs.append((text, level))

        with mock.patch.object(organize, "get_config", return_value=cfg), \
             mock.patch.object(organize, "_get_provider_or_none", return_value=fake_provider), \
             mock.patch.object(organize, "write_subscription_log", side_effect=fake_log), \
             mock.patch.object(
                 organize,
                 "organize_files_for_subscription_task",
                 new=mock.AsyncMock(return_value=result),
             ), \
             mock.patch("app.services.monitor.queue_monitor_job", return_value=queue_return) as queue_mock:
            stats = asyncio.run(organize.run_pending_organize_once())
        return stats, logs, queue_mock

    def _task(self, **overrides):
        task = {
            "name": TASK_NAME,
            "media_type": "tv",
            "organize_on_import": True,
            "tmdb_id": 281233,
            "organize_options": {"file_name_mode": "standard"},
        }
        task.update(overrides)
        return task

    def test_triggers_monitor_after_rename(self):
        self._seed()
        stats, logs, queue_mock = self._run(
            self._task(),
            {"ok": True, "job_id": 77, "succeeded": 1, "failed": 0, "status": "completed"},
        )

        self.assertEqual(stats["done"], 1)
        queue_mock.assert_called_once_with(
            "影视库监控",
            "subscription",
            {"savepath": "115连载中/光阴之外 (2025)/Season 01", "title": "跨盘补源：光阴之外"},
        )
        self.assertTrue(any("已触发监控精准刷新" in text for text, _level in logs), logs)

    def test_no_monitor_match_logs_warning_and_skips_queue(self):
        self._seed()
        stats, logs, queue_mock = self._run(
            self._task(),
            {"ok": True, "job_id": 77, "succeeded": 1, "failed": 0, "status": "completed"},
            monitor_tasks=[],
        )

        self.assertEqual(stats["done"], 1)
        queue_mock.assert_not_called()
        self.assertTrue(any("未纳入文件夹监控" in text for text, _level in logs), logs)

    def test_rename_failure_still_triggers_monitor(self):
        self._seed()
        stats, _logs, queue_mock = self._run(
            self._task(),
            {"ok": False, "reason": "未在目标目录找到本次新入库的文件，保留原名", "level": "info"},
        )

        self.assertEqual(stats["failed"], 1)
        queue_mock.assert_called_once()

    def test_missing_task_still_triggers_monitor(self):
        self._seed()
        stats, _logs, queue_mock = self._run(None, {})

        self.assertEqual(stats["skipped"], 1)
        queue_mock.assert_called_once()

    def test_non_115_target_does_not_trigger(self):
        self._seed(target_provider="quark", target_dir_id="quark-dir")
        stats, logs, queue_mock = self._run(
            self._task(),
            {"ok": True, "job_id": 5, "succeeded": 1, "failed": 0, "status": "completed"},
        )

        self.assertEqual(stats["done"], 1)
        queue_mock.assert_not_called()
        self.assertFalse(any("刷新" in text for text, _level in logs), logs)

    def test_helper_short_circuits_non_115(self):
        result = organize.trigger_cross_copy_monitor_refresh(
            {"mount_points": [{"provider": "115", "prefix": "/115"}]},
            "quark",
            "某目录",
            TASK_NAME,
        )

        self.assertEqual(result, {"triggered": False, "reason": "not_115"})

    def test_disabled_monitor_task_does_not_claim_triggered(self):
        """监控任务停用：入队返回 disabled，日志不能谎报「已触发」。"""
        self._seed()
        stats, logs, queue_mock = self._run(
            self._task(),
            {"ok": True, "job_id": 77, "succeeded": 1, "failed": 0, "status": "completed"},
            queue_return="disabled",
        )

        self.assertEqual(stats["done"], 1)
        queue_mock.assert_called_once()
        self.assertTrue(any("已停用" in text for text, _level in logs), logs)
        self.assertFalse(any("已触发监控精准刷新" in text for text, _level in logs), logs)

    def test_unconfigured_provider_skips_monitor_trigger(self):
        """目标网盘未配置：整组放弃，不排必然失败的扫描，也不再叠一条归因错误的警告。"""
        self._seed()
        stats, logs, queue_mock = self._run(
            self._task(),
            {"ok": True, "job_id": 77, "succeeded": 1, "failed": 0, "status": "completed"},
            provider=None,
        )

        self.assertEqual(stats["skipped"], 1)
        queue_mock.assert_not_called()
        self.assertTrue(any("未配置" in text for text, _level in logs), logs)
        self.assertFalse(any("刷新" in text for text, _level in logs), logs)
        self.assertFalse(any("未纳入文件夹监控" in text for text, _level in logs), logs)

    def test_helper_marks_disabled_monitor_as_not_triggered(self):
        cfg = {
            "mount_points": [{"provider": "115", "prefix": "/115"}],
            "monitor_tasks": [{"name": "影视库监控", "scan_path": "/115/115连载中"}],
        }
        with mock.patch("app.services.monitor.queue_monitor_job", return_value="disabled"):
            result = organize.trigger_cross_copy_monitor_refresh(
                cfg, "115", "115连载中/光阴之外 (2025)", TASK_NAME
            )

        self.assertEqual(
            result,
            {
                "triggered": False,
                "reason": "monitor_disabled",
                "task_name": "影视库监控",
                "savepath": "115连载中/光阴之外 (2025)",
            },
        )


if __name__ == "__main__":
    unittest.main()
