"""跨盘补源「回写订阅任务进度」的测试。

两层：
1. 打标记：只有「订阅补源 + 复制成功」才标 ``progress_state='pending'``；
   手动复制、被跳过的任务都不标；重试清掉旧标记。
2. 定时器回写：按订阅任务成组、过防抖窗口、CAS 抢占、集数取 max、
   整包（解析不出集数）不动进度、任务正在跑时放回 pending 等下一轮。

补源此前完全不回写 ``subscription_task_state``，界面「最近命中 / 追更进度」
会一直停在上一次同盘导入的旧值——这里把行为钉住。
"""

import asyncio
import os
import shutil
import tempfile
import unittest
from unittest import mock

from app import db
from app.services import cross_copy_jobs as ccj
from app.services import subscription_cross_copy_progress as progress

TASK_NAME = "光阴之外"

TV_TASK = {
    "name": TASK_NAME,
    "title": "光阴之外",
    "media_type": "tv",
    "season": 1,
    "provider": "115",
    "savepath": "115连载中",
    "cross_copy_mode": "fallback",
    "cross_copy_sources": ["quark"],
}


class FakeCopyResult:
    def __init__(self, status="uploaded", name="S01E42.mp4", message="上传完成"):
        self.status = status
        self.name = name
        self.message = message
        self.file_id = ""
        self.size = 1024

    def to_dict(self):
        return {"status": self.status, "name": self.name}


class FakeProvider:
    name = "115"
    label = "115网盘"
    supports_delete = False
    supports_upload = True

    def get_cookie(self, _cfg=None):
        return "cookie-115"

    def list_entries(self, cookie, cid="0"):
        return []


class FakeFolderResult:
    def __init__(self, status="completed", folder_name="光阴之外 全季 4K", message="复制完成"):
        self.status = status
        self.folder_name = folder_name
        self.message = message
        self.total_bytes = 1024

    def to_dict(self):
        return {"status": self.status, "folder_name": self.folder_name}


class ProgressTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wb_ccp_test_")
        self.original_db_path = db.DB_PATH
        self.original_db_ensured = db._DB_ENSURED
        db.DB_PATH = os.path.join(self.tmp, "test.db")
        db._DB_ENSURED = False
        db.ensure_db()
        with db.db_connection() as conn:
            conn.execute("DELETE FROM cross_copy_jobs")
            conn.execute("DELETE FROM subscription_task_state")
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
            "subscription_tasks": [dict(TV_TASK)],
        }
        # 后台提交必须桩掉：retry 会真的把「跑任务」的协程丢到后台 loop 上，那条
        # 协程活得比用例长，等下一个用例换掉 db.DB_PATH 后才写状态，把新库里同号
        # （都从 1 开始）的任务改成 running —— 表现为随机失败。
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

    def _pending(self, **overrides):
        job_id = self._job(**overrides)
        ccj.update_cross_copy_job(
            job_id,
            status="completed",
            finished_at="2026-10-22T10:00:00",
            progress_state="pending",
        )
        return job_id

    def _state(self):
        return db_mod_state(TASK_NAME)


def db_mod_state(task_name):
    from app.services.subscription_state import load_subscription_task_state

    return load_subscription_task_state(task_name, "tv")


class ProgressMarkingTest(ProgressTestBase):
    """复制收口时的标记。"""

    def _run_job(self, job_id, result):
        provider = FakeProvider()
        patchers = [
            mock.patch.object(ccj, "get_config", return_value=self.cfg),
            mock.patch.object(ccj, "_get_provider_or_none", return_value=provider),
            mock.patch.object(ccj, "_send_notify_content", mock.MagicMock()),
            mock.patch.object(ccj, "build_resume_state", return_value=None),
            mock.patch.object(ccj.xcc, "resolve_temp_dir", return_value=self.tmp),
            mock.patch.object(ccj.xcc, "copy_file_across_clouds", return_value=result),
            mock.patch.object(ccj.xccf, "copy_folder_across_clouds", return_value=result),
            mock.patch.object(ccj, "submit_background", mock.MagicMock()),
        ]
        for patcher in patchers:
            patcher.start()
        try:
            asyncio.run(ccj.run_cross_copy_job(job_id))
        finally:
            for patcher in patchers:
                patcher.stop()

    def test_subscription_success_is_marked_pending(self):
        job_id = self._job()
        self._run_job(job_id, FakeCopyResult())

        row = self._row(job_id)
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["progress_state"], "pending")

    def test_folder_job_is_also_marked(self):
        # 整包补源也要回写「最近命中」，只是集数解析不出来、不动进度
        job_id = self._job(source_is_dir=True, filename="光阴之外 全季 4K")
        self._run_job(job_id, FakeFolderResult())

        self.assertEqual(self._row(job_id)["progress_state"], "pending")

    def test_manual_job_is_not_marked(self):
        job_id = self._job(origin="manual", origin_ref="")
        self._run_job(job_id, FakeCopyResult())

        self.assertEqual(self._row(job_id)["progress_state"], "")

    def test_skipped_result_is_not_marked(self):
        job_id = self._job()
        self._run_job(job_id, FakeCopyResult(status="skipped", message="目标已存在同文件"))

        row = self._row(job_id)
        self.assertEqual(row["status"], "skipped")
        self.assertEqual(row["progress_state"], "")

    def test_retry_clears_marking(self):
        job_id = self._job()
        ccj.update_cross_copy_job(job_id, status="completed", progress_state="done", progress_detail="已回写")
        ccj.retry_cross_copy_job(job_id)

        row = self._row(job_id)
        self.assertEqual(row["progress_state"], "")
        self.assertEqual(row["progress_detail"], "")


class ProgressFailureTest(ProgressTestBase):
    """补源失败也要回写订阅侧。

    以前失败任务根本不进「待回写」队列：卡片上的「跨盘补源中」消失后直接退回
    「尚未命中」，订阅日志里一个字都没有，看起来像兜底连资源都没找到，实际是
    找到了、复制挂了。
    """

    def _failed_pending(self, **overrides):
        finished_at = overrides.pop("finished_at", "2026-10-22T10:00:00")
        error_message = overrides.pop("error_message", "115 直链 403")
        job_id = self._job(**overrides)
        ccj.update_cross_copy_job(
            job_id,
            status="failed",
            finished_at=finished_at,
            error_message=error_message,
            progress_state="pending",
        )
        return job_id

    def _run_once(self):
        log_mock = mock.AsyncMock()
        with mock.patch.object(progress, "write_subscription_log", log_mock), mock.patch.object(
            progress, "get_config", return_value=self.cfg
        ):
            stats = asyncio.run(progress.run_pending_progress_once())
        return stats, log_mock

    def test_subscription_failure_is_marked_pending(self):
        job_id = self._job()
        with mock.patch.object(ccj, "get_config", return_value=self.cfg):
            ccj._fail_job(job_id, "下载失败：115 直链 403")

        row = self._row(job_id)
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["progress_state"], "pending")

    def test_manual_failure_is_not_marked(self):
        job_id = self._job(origin="manual", origin_ref="")
        with mock.patch.object(ccj, "get_config", return_value=self.cfg):
            ccj._fail_job(job_id, "下载失败")

        self.assertEqual(self._row(job_id)["progress_state"], "")

    def test_failed_group_writes_one_warn_log(self):
        job_id = self._failed_pending()
        stats, log_mock = self._run_once()

        self.assertEqual(stats["copy_failed"], 1)
        self.assertEqual(stats["done"], 0)
        log_mock.assert_awaited()
        args = log_mock.await_args.args
        self.assertIn("跨盘补源失败", args[0])
        self.assertIn("E42", args[0])
        self.assertIn("115 直链 403", args[0])
        self.assertEqual(args[1], "warn")
        # 失败不该改写成功语义的字段
        self.assertNotEqual(self._state().get("status"), "completed")
        self.assertEqual(self._state().get("last_success_at", ""), "")
        self.assertEqual(self._row(job_id)["progress_state"], "done")

    def test_mixed_group_splits_success_and_failure(self):
        # 同一批里既有成功的也有失败的：成功的照常推进度，失败的只写日志
        self._failed_pending(filename="S01E42.mp4")
        self._pending(filename="S01E43.mp4")
        stats, _ = self._run_once()

        self.assertEqual(stats["copy_failed"], 1)
        self.assertEqual(stats["done"], 1)
        self.assertEqual(self._state().get("last_episode"), 43)


class ProgressSelectionTest(ProgressTestBase):
    """待回写任务的筛选、成组与抢占。"""

    def test_group_merges_by_task_name(self):
        a = self._pending(filename="S01E42.mp4")
        b = self._pending(filename="S01E43.mp4", target_dir_id="season2-cid")
        c = self._pending(filename="S02E01.mp4", origin_ref="别的任务")

        groups = progress.group_jobs([self._row(a), self._row(b), self._row(c)])

        self.assertEqual(len(groups), 2)
        self.assertEqual(len(groups[TASK_NAME]), 2)

    def test_debounce_window_excludes_fresh_jobs(self):
        fresh = self._pending()
        ccj.update_cross_copy_job(fresh, finished_at="2999-01-01T00:00:00")

        jobs = progress.list_progress_jobs(progress._cutoff_text())

        self.assertEqual([int(job["id"]) for job in jobs], [])

    def test_jobs_without_finished_at_are_ignored(self):
        job_id = self._pending()
        ccj.update_cross_copy_job(job_id, finished_at="")

        self.assertEqual(progress.list_progress_jobs(progress._cutoff_text()), [])

    def test_claim_is_cas(self):
        job_id = self._pending()

        self.assertEqual(progress._claim_jobs([job_id]), [job_id])
        self.assertEqual(progress._claim_jobs([job_id]), [])
        self.assertEqual(self._row(job_id)["progress_state"], "running")

    def test_stale_running_is_reset(self):
        job_id = self._pending()
        progress._claim_jobs([job_id])
        with db.db_connection() as conn:
            conn.execute(
                "UPDATE cross_copy_jobs SET updated_at = ? WHERE id = ?",
                ("2000-01-01T00:00:00", job_id),
            )
            conn.commit()

        self.assertEqual(progress._reset_stale_running(), 1)
        self.assertEqual(self._row(job_id)["progress_state"], "pending")


class ProgressApplyTest(ProgressTestBase):
    """真正的状态回写。"""

    def _apply(self, jobs, task=None):
        cfg = dict(self.cfg)
        if task is not None:
            cfg["subscription_tasks"] = [task]
        with mock.patch.object(progress, "get_config", return_value=cfg):
            return progress.apply_progress_for_task(TASK_NAME, jobs, cfg)

    def test_episode_progress_and_last_hit_are_written(self):
        from app.services.subscription_state import upsert_subscription_task_state

        upsert_subscription_task_state(
            TASK_NAME,
            media_type="tv",
            status="waiting",
            last_episode=41,
            total_episodes=44,
            matched_resource_title="旧的同盘资源",
            last_success_at="2026-10-20T10:00:00",
        )
        a = self._pending(filename="S01E42.mp4")
        b = self._pending(filename="S01E43.mp4")

        result = self._apply([self._row(a), self._row(b)])

        self.assertTrue(result["ok"])
        state = self._state()
        self.assertEqual(state["last_episode"], 43)
        self.assertEqual(state["total_episodes"], 44)
        self.assertEqual(state["status"], "completed")
        self.assertIn("夸克补源", state["matched_resource_title"])
        self.assertIn("E42~E43", state["detail"])
        self.assertNotEqual(state["last_success_at"], "2026-10-20T10:00:00")
        self.assertTrue(state["stats"].get("cross_copy"))
        self.assertEqual(state["stats"].get("cross_copy_episodes"), [42, 43])

    def test_progress_never_moves_backwards(self):
        from app.services.subscription_state import upsert_subscription_task_state

        upsert_subscription_task_state(TASK_NAME, media_type="tv", last_episode=44, total_episodes=44)
        job = self._pending(filename="S01E42.mp4")

        self._apply([self._row(job)])

        self.assertEqual(self._state()["last_episode"], 44)

    def test_folder_job_keeps_progress_but_records_hit(self):
        from app.services.subscription_state import upsert_subscription_task_state

        upsert_subscription_task_state(TASK_NAME, media_type="tv", last_episode=0, total_episodes=44)
        job = self._pending(source_is_dir=True, filename="光阴之外 全季 4K")

        self._apply([self._row(job)])

        state = self._state()
        self.assertEqual(state["last_episode"], 0)
        self.assertIn("整包复制", state["detail"])
        self.assertIn("夸克补源", state["matched_resource_title"])

    def test_saved_episode_max_follows_cross_copy(self):
        # 界面上「已到 E几」读 stats.existing_episode_max，补源落地就得跟着抬，
        # 否则要等下一次运行扫目录才追上
        from app.services.subscription_state import upsert_subscription_task_state

        upsert_subscription_task_state(
            TASK_NAME,
            media_type="tv",
            last_episode=41,
            total_episodes=44,
            stats={"existing_episode_max": 40, "existing_episode_scan_ready": True},
        )
        job = self._pending(filename="S01E43.mp4")

        self._apply([self._row(job)])

        stats = self._state()["stats"]
        self.assertEqual(stats["existing_episode_max"], 43)
        # 只补了单个文件，不能顺手编一个「目录里共有几集」出来
        self.assertNotIn("existing_episode_count", stats)

    def test_saved_episode_max_never_moves_backwards(self):
        from app.services.subscription_state import upsert_subscription_task_state

        upsert_subscription_task_state(
            TASK_NAME,
            media_type="tv",
            last_episode=44,
            total_episodes=44,
            stats={"existing_episode_max": 44},
        )
        job = self._pending(filename="S01E42.mp4")

        self._apply([self._row(job)])

        self.assertEqual(self._state()["stats"]["existing_episode_max"], 44)

    def test_missing_task_is_reported_without_retry(self):
        job = self._pending()

        result = self._apply([self._row(job)], task={})

        self.assertFalse(result["ok"])
        self.assertFalse(result["retry"])

    def test_running_task_defers_write(self):
        job = self._pending()
        running = {"running": True, "current_task": TASK_NAME}
        with mock.patch.object(progress, "subscription_status", running):
            result = self._apply([self._row(job)])

        self.assertFalse(result["ok"])
        self.assertTrue(result["retry"])


class ProgressNotifyTest(ProgressTestBase):
    """补源成功也算订阅成功：一批补源只发一条「订阅更新成功」。"""

    def _run_once(self, push_mock):
        with mock.patch.object(progress, "get_config", return_value=self.cfg), mock.patch.object(
            progress, "push_cross_copy_subscription_notification", push_mock
        ), mock.patch.object(progress, "write_subscription_log", mock.AsyncMock()):
            return asyncio.run(progress.run_pending_progress_once())

    def _enable_merge(self):
        from app.services.subscription_state import upsert_subscription_task_state

        self.cfg["notify_push_enabled"] = True
        self.cfg["cross_copy_notify_subscription"] = True
        # 预置游标：跳过「首次上线只回溯 24 小时」的窗口（用例里的 finished_at 是固定值）
        upsert_subscription_task_state(
            TASK_NAME,
            media_type="tv",
            stats={
                "cross_copy_notified_at": "2000-01-01T00:00:00",
                "cross_copy_notified_job_id": 0,
            },
        )

    def test_one_notification_per_group(self):
        self._enable_merge()
        self._pending(filename="S01E42.mp4")
        last = self._pending(filename="S01E43.mp4")
        push = mock.AsyncMock(return_value={"pushed": True})

        stats = self._run_once(push)

        self.assertEqual(push.await_count, 1)
        kwargs = push.await_args.kwargs
        self.assertEqual(kwargs["episodes"], [42, 43])
        self.assertEqual(kwargs["file_count"], 2)
        self.assertEqual(kwargs["next_episode"], 43)
        self.assertTrue(kwargs["source_label"])
        self.assertTrue(kwargs["target_label"])
        self.assertEqual(stats["notified"], 1)
        # 游标要推进，下一轮不能把同一批再报一遍
        self.assertEqual(self._state()["stats"]["cross_copy_notified_at"], "2026-10-22T10:00:00")
        self.assertEqual(self._state()["stats"]["cross_copy_notified_job_id"], last)

    def test_retried_job_is_notified_again(self):
        """重试成功 id 不变、完成时间变晚：只按 id 的游标会把它跳过。"""
        self._enable_merge()
        job = self._pending(filename="S01E42.mp4")
        push = mock.AsyncMock(return_value={"pushed": True})
        self._run_once(push)
        self.assertEqual(push.await_count, 1)

        ccj.update_cross_copy_job(
            job,
            status="completed",
            finished_at="2026-10-22T11:00:00",
            progress_state="pending",
        )
        self._run_once(push)

        self.assertEqual(push.await_count, 2)
        self.assertEqual(push.await_args.kwargs["episodes"], [42])

    def test_waits_while_sibling_jobs_still_running(self):
        """还有兄弟任务没跑完就先不发，否则补 5 集又会分成好几条。"""
        self._enable_merge()
        self._pending(filename="S01E42.mp4")
        self._job(filename="S01E43.mp4")  # 仍是 pending，没完成
        push = mock.AsyncMock(return_value={"pushed": True})

        stats = self._run_once(push)

        push.assert_not_awaited()
        self.assertEqual(stats["notified"], 0)
        # 进度照常写回，只是通知再等等
        self.assertEqual(self._state()["last_episode"], 42)

    def test_batches_across_rounds(self):
        """上一轮没发出去的集数，这一轮要一起报，不能漏。"""
        self._enable_merge()
        self._pending(filename="S01E42.mp4")
        sibling = self._job(filename="S01E43.mp4")
        push = mock.AsyncMock(return_value={"pushed": True})
        self._run_once(push)
        push.assert_not_awaited()

        ccj.update_cross_copy_job(
            sibling,
            status="completed",
            finished_at="2026-10-22T10:05:00",
            progress_state="pending",
        )
        self._run_once(push)

        self.assertEqual(push.await_count, 1)
        self.assertEqual(push.await_args.kwargs["episodes"], [42, 43])
        self.assertEqual(push.await_args.kwargs["file_count"], 2)

    def test_no_notification_when_merge_switches_off(self):
        push = mock.AsyncMock(return_value={"pushed": True})

        self._run_once(push)

        push.assert_not_awaited()

    def test_notification_failure_keeps_progress_done(self):
        self._enable_merge()
        job = self._pending(filename="S01E42.mp4")
        push = mock.AsyncMock(side_effect=RuntimeError("webhook 挂了"))

        stats = self._run_once(push)

        self.assertEqual(stats["done"], 1)
        self.assertEqual(stats["notify_failed"], 1)
        self.assertEqual(self._row(job)["progress_state"], "done")
        self.assertEqual(self._state()["last_episode"], 42)


class ProgressWatcherTest(ProgressTestBase):
    """定时器一轮的收口：回写成功后标记 done，任务在跑则保持 pending。"""

    def test_run_once_writes_state_and_marks_done(self):
        a = self._pending(filename="S01E42.mp4")
        b = self._pending(filename="S01E43.mp4", target_dir_id="season-cid")

        with mock.patch.object(progress, "get_config", return_value=self.cfg), mock.patch.object(
            progress, "write_subscription_log", mock.AsyncMock()
        ):
            stats = asyncio.run(progress.run_pending_progress_once())

        self.assertEqual(stats["groups"], 1)
        self.assertEqual(stats["done"], 2)
        self.assertEqual(self._row(a)["progress_state"], "done")
        self.assertEqual(self._row(b)["progress_state"], "done")
        self.assertEqual(self._state()["last_episode"], 43)

    def test_run_once_keeps_pending_while_task_running(self):
        job = self._pending()
        running = {"running": True, "current_task": TASK_NAME}

        with mock.patch.object(progress, "get_config", return_value=self.cfg), mock.patch.object(
            progress, "subscription_status", running
        ), mock.patch.object(progress, "write_subscription_log", mock.AsyncMock()):
            asyncio.run(progress.run_pending_progress_once())

        self.assertEqual(self._row(job)["progress_state"], "pending")

    def test_second_run_does_not_touch_done_jobs(self):
        job = self._pending()
        with mock.patch.object(progress, "get_config", return_value=self.cfg), mock.patch.object(
            progress, "write_subscription_log", mock.AsyncMock()
        ):
            asyncio.run(progress.run_pending_progress_once())
            second = asyncio.run(progress.run_pending_progress_once())

        self.assertEqual(second["groups"], 0)
        self.assertEqual(self._row(job)["progress_state"], "done")


if __name__ == "__main__":
    unittest.main()
