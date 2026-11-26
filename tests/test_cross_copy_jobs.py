"""跨盘复制任务测试（#9 任务接入与手动入口）。

临时目录用 ``tempfile.mkdtemp()`` 建、tearDown 里清。根目录由
``scripts/run_tests.py`` 指到本轮会话目录（系统临时区），不落进仓库，
所以不用自己拼路径、也不该往项目里写。
"""

import asyncio
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import db
from app.services import cross_cloud_copy as xcc
from app.services import cross_copy_jobs as ccj
from app.routes import cross_copy as cross_copy_routes


class FakeJsonRequest:
    def __init__(self, payload):
        self.payload = payload
        self.query_params = {}

    async def json(self):
        return self.payload


class FakeQueryRequest:
    def __init__(self, params):
        self.payload = {}
        self.query_params = params

    async def json(self):
        return self.payload


class FakeProvider:
    def __init__(self, name, label, cookie="cookie-x", supports_upload=True, supports_delete=True):
        self.name = name
        self.label = label
        self._cookie = cookie
        self.supports_upload = supports_upload
        self.supports_delete = supports_delete
        self.delete_calls = []

    def get_cookie(self, cfg):
        return self._cookie

    def is_configured(self, cfg):
        return bool(self._cookie)

    def delete_entries(self, cookie, entry_ids, parent_id=""):
        self.delete_calls.append(list(entry_ids))
        return {"ok": True}


def _uploaded_result(status="uploaded"):
    return xcc.CopyFileResult(
        status=status,
        source_provider="quark",
        target_provider="115",
        file_id="F-1" if status == "uploaded" else "",
        name="movie.mkv",
        size=1024,
        sha1="ABC",
        message="已完成" if status == "uploaded" else "目标已存在同名同大小文件，跳过",
    )


class CrossCopyJobsTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wb_ccj_test_")
        self.original_db_path = db.DB_PATH
        self.original_db_ensured = db._DB_ENSURED
        db.DB_PATH = os.path.join(self.tmp, "test.db")
        db._DB_ENSURED = False
        db.ensure_db()
        # 清理跨用例残留
        with db.db_connection() as conn:
            conn.execute("DELETE FROM cross_copy_jobs")
            conn.commit()
        # 模块级内存状态也要清：job id 从 1 重新开始，残留会串味（进度节流/取消标记）
        ccj._job_progress.clear()
        ccj._last_db_progress.clear()
        ccj._cancel_requested.clear()
        ccj._pause_requested.clear()
        # 排队状态同样是模块级的：不清会把上一条用例的名额带进来
        with ccj._sched_lock:
            ccj._queued.clear()
            ccj._active.clear()
        with ccj._running_lock:
            ccj._running.clear()

        self.cfg = {
            "cross_copy_notify_subscription": True,
            "cross_copy_notify_manual": True,
            "cross_copy_delete_source_after": True,
            "provider_enabled": {"quark": True, "115": True, "aliyun": True},
        }
        self.source_provider = FakeProvider("quark", "夸克网盘")
        self.target_provider = FakeProvider("115", "115网盘")

        patchers = [
            patch.object(ccj, "get_config", return_value=self.cfg),
            patch.object(ccj, "_get_provider_or_none", side_effect=self._fake_get_provider),
            patch.object(ccj, "_send_notify_content", MagicMock()),
            patch.object(ccj, "notify_channel_ready", return_value=True),
            patch.object(
                ccj,
                "build_notify_runtime_config",
                return_value={"enabled": True, "channel": "wecom_bot", "wecom_webhook": "https://example.invalid/hook"},
            ),
            patch.object(ccj, "submit_background", MagicMock()),
            patch.object(cross_copy_routes, "get_config", return_value=self.cfg),
            patch.object(cross_copy_routes, "_get_provider_or_none", side_effect=self._fake_get_provider),
        ]
        self._patchers = patchers
        for p in patchers:
            p.start()

    def tearDown(self):
        for p in self._patchers:
            p.stop()
        db.DB_PATH = self.original_db_path
        db._DB_ENSURED = self.original_db_ensured
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _fake_get_provider(self, name):
        if name == "quark":
            return self.source_provider
        if name == "115":
            return self.target_provider
        return None

    def _create_job(self, **overrides):
        params = dict(
            title="测试电影",
            source_provider="quark",
            target_provider="115",
            source_file_id="f-quark-1",
            target_dir_id="dir-115",
            filename="movie.mkv",
            file_size=1024,
        )
        params.update(overrides)
        return ccj.create_cross_copy_job(**params)

    def _run(self, job_id):
        return asyncio.run(ccj.run_cross_copy_job(job_id))


class TestJobCrud(CrossCopyJobsTestBase):
    def test_create_and_get(self):
        job_id = self._create_job()
        job = ccj.get_cross_copy_job(job_id)
        self.assertIsNotNone(job)
        self.assertEqual(job["status"], "pending")
        self.assertEqual(job["source_provider"], "quark")
        self.assertEqual(job["target_provider"], "115")
        self.assertEqual(job["file_size"], 1024)
        self.assertEqual(job["origin"], "manual")

    def test_get_missing(self):
        self.assertIsNone(ccj.get_cross_copy_job(9999))

    def test_list_jobs(self):
        self._create_job(title="A")
        self._create_job(title="B")
        jobs = ccj.list_cross_copy_jobs(limit=10)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0]["title"], "B")  # 倒序

    def test_list_filter_status(self):
        self._create_job(title="A")
        jobs = ccj.list_cross_copy_jobs(limit=10, status="completed")
        self.assertEqual(jobs, [])

    def test_update_normalizes_status(self):
        job_id = self._create_job()
        ccj.update_cross_copy_job(job_id, status="COMPLETED", progress_percent=100)
        job = ccj.get_cross_copy_job(job_id)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["progress_percent"], 100)


class TestJobExecution(CrossCopyJobsTestBase):
    def test_success_uploaded(self):
        job_id = self._create_job()
        with patch.object(xcc, "copy_file_across_clouds", return_value=_uploaded_result("uploaded")):
            self._run(job_id)
        job = ccj.get_cross_copy_job(job_id)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["progress_percent"], 100)
        self.assertEqual(job["result"]["file_id"], "F-1")
        ccj._send_notify_content.assert_called_once()

    def test_notify_shows_display_name_not_internal_code(self):
        """通知文案要给人看的网盘名，不能把内部代号（quark / tianyi）直接拼进去。"""
        job_id = self._create_job()
        with patch.object(xcc, "copy_file_across_clouds", return_value=_uploaded_result("uploaded")):
            self._run(job_id)
        content = ccj._send_notify_content.call_args[0][1]
        self.assertIn("链路：夸克网盘 → 115网盘", content)

    def test_success_rapid(self):
        job_id = self._create_job()
        with patch.object(xcc, "copy_file_across_clouds", return_value=_uploaded_result("rapid")):
            self._run(job_id)
        job = ccj.get_cross_copy_job(job_id)
        self.assertEqual(job["status"], "completed")

    def test_skipped(self):
        job_id = self._create_job()
        with patch.object(xcc, "copy_file_across_clouds", return_value=_uploaded_result("skipped")):
            self._run(job_id)
        job = ccj.get_cross_copy_job(job_id)
        self.assertEqual(job["status"], "skipped")
        ccj._send_notify_content.assert_called_once()

    def test_failure(self):
        job_id = self._create_job()
        with patch.object(xcc, "copy_file_across_clouds", side_effect=xcc.CrossCloudCopyError("115 操作过于频繁")):
            self._run(job_id)
        job = ccj.get_cross_copy_job(job_id)
        self.assertEqual(job["status"], "failed")
        self.assertIn("频繁", job["error_message"])
        ccj._send_notify_content.assert_called_once()

    def test_unexpected_exception_does_not_crash(self):
        job_id = self._create_job()
        with patch.object(xcc, "copy_file_across_clouds", side_effect=ValueError("boom")):
            self._run(job_id)
        job = ccj.get_cross_copy_job(job_id)
        self.assertEqual(job["status"], "failed")

    def test_cancel_pending(self):
        job_id = self._create_job()
        result = ccj.cancel_cross_copy_job(job_id)
        self.assertTrue(result["ok"])
        job = ccj.get_cross_copy_job(job_id)
        self.assertEqual(job["status"], "cancelled")

    def test_cancel_running_at_checkpoint(self):
        job_id = self._create_job()

        def fake_copy(**kwargs):
            # 模拟运行中取消：检查点第一次调用即命中
            raise xcc.CrossCloudCopyCancelled("已取消")

        with patch.object(xcc, "copy_file_across_clouds", side_effect=fake_copy):
            self._run(job_id)
        job = ccj.get_cross_copy_job(job_id)
        self.assertEqual(job["status"], "cancelled")

    def test_cancel_finished_job_rejected(self):
        job_id = self._create_job()
        with patch.object(xcc, "copy_file_across_clouds", return_value=_uploaded_result()):
            self._run(job_id)
        result = ccj.cancel_cross_copy_job(job_id)
        self.assertFalse(result["ok"])
        self.assertIn("已结束", result["msg"])

    def test_pause_running_at_checkpoint(self):
        job_id = self._create_job()

        def fake_copy(**kwargs):
            raise xcc.CrossCloudCopyPaused("已暂停")

        with patch.object(xcc, "copy_file_across_clouds", side_effect=fake_copy):
            self._run(job_id)
        job = ccj.get_cross_copy_job(job_id)
        self.assertEqual(job["status"], "paused")

    def test_pause_pending_marks_paused(self):
        job_id = self._create_job()
        result = ccj.pause_cross_copy_job(job_id)
        self.assertTrue(result["ok"])
        job = ccj.get_cross_copy_job(job_id)
        self.assertEqual(job["status"], "paused")

    def test_pause_finished_job_rejected(self):
        job_id = self._create_job()
        with patch.object(xcc, "copy_file_across_clouds", return_value=_uploaded_result()):
            self._run(job_id)
        result = ccj.pause_cross_copy_job(job_id)
        self.assertFalse(result["ok"])

    def test_resume_requeues_from_paused(self):
        job_id = self._create_job()
        ccj.update_cross_copy_job(job_id, status="paused")
        result = ccj.resume_cross_copy_job(job_id)
        self.assertTrue(result["ok"])
        job = ccj.get_cross_copy_job(job_id)
        self.assertEqual(job["status"], "pending")
        ccj.submit_background.assert_called_once()

    def test_resume_non_paused_rejected(self):
        job_id = self._create_job()
        result = ccj.resume_cross_copy_job(job_id)
        self.assertFalse(result["ok"])

    def test_normalize_status_keeps_paused(self):
        # paused 必须在白名单里，否则读回时回落 pending 自动续跑
        self.assertEqual(ccj._normalize_status("paused"), "paused")

    def test_retry_after_failure(self):
        job_id = self._create_job()
        with patch.object(xcc, "copy_file_across_clouds", side_effect=xcc.CrossCloudCopyError("网络错误")):
            self._run(job_id)
        result = ccj.retry_cross_copy_job(job_id)
        self.assertTrue(result["ok"])
        job = ccj.get_cross_copy_job(job_id)
        self.assertEqual(job["status"], "pending")
        self.assertEqual(job["retry_count"], 1)
        ccj.submit_background.assert_called_once()

    def test_retry_running_rejected(self):
        job_id = self._create_job()
        ccj.update_cross_copy_job(job_id, status="running")
        result = ccj.retry_cross_copy_job(job_id)
        self.assertFalse(result["ok"])

    def test_delete_source_after_success(self):
        # 订阅补源：源文件是本任务自己转存到中转目录的副本，完成后可清理
        job_id = self._create_job(origin="subscription")
        with patch.object(xcc, "copy_file_across_clouds", return_value=_uploaded_result()):
            self._run(job_id)
        self.assertEqual(self.source_provider.delete_calls, [["f-quark-1"]])

    def test_manual_job_never_deletes_source(self):
        # 手动复制的源文件是用户自己网盘里的原片，无论配置如何都不能删
        job_id = self._create_job(origin="manual")
        with patch.object(xcc, "copy_file_across_clouds", return_value=_uploaded_result()):
            self._run(job_id)
        self.assertEqual(self.source_provider.delete_calls, [])

    def test_no_delete_when_disabled(self):
        self.cfg["cross_copy_delete_source_after"] = False
        job_id = self._create_job(origin="subscription")
        with patch.object(xcc, "copy_file_across_clouds", return_value=_uploaded_result()):
            self._run(job_id)
        self.assertEqual(self.source_provider.delete_calls, [])

    def test_no_delete_on_failure(self):
        job_id = self._create_job()
        with patch.object(xcc, "copy_file_across_clouds", side_effect=xcc.CrossCloudCopyError("失败")):
            self._run(job_id)
        self.assertEqual(self.source_provider.delete_calls, [])

    def test_notify_disabled_for_manual_origin(self):
        """手动复制开关关掉后，手动任务不再推送（默认 origin=manual）。"""
        self.cfg["cross_copy_notify_manual"] = False
        job_id = self._create_job()
        with patch.object(xcc, "copy_file_across_clouds", return_value=_uploaded_result()):
            self._run(job_id)
        ccj._send_notify_content.assert_not_called()

    def test_notify_disabled_for_subscription_origin(self):
        """订阅补源开关关掉后，订阅任务不再推送。"""
        self.cfg["cross_copy_notify_subscription"] = False
        job_id = self._create_job(origin="subscription")
        with patch.object(xcc, "copy_file_across_clouds", return_value=_uploaded_result()):
            self._run(job_id)
        ccj._send_notify_content.assert_not_called()

    def test_notify_switches_are_per_origin(self):
        """两个开关互不影响：关一个不影响另一个来源的任务。"""
        self.cfg["cross_copy_notify_subscription"] = False
        self.cfg["cross_copy_notify_manual"] = True
        sub_job = self._create_job(origin="subscription", title="订阅来的")
        with patch.object(xcc, "copy_file_across_clouds", return_value=_uploaded_result()):
            self._run(sub_job)
        ccj._send_notify_content.assert_not_called()

        ccj._send_notify_content.reset_mock()
        manual_job = self._create_job(origin="manual", title="手动来的")
        with patch.object(xcc, "copy_file_across_clouds", return_value=_uploaded_result()):
            self._run(manual_job)
        ccj._send_notify_content.assert_called_once()

    def test_notify_skipped_when_channel_not_ready(self):
        """开关都开着但通知渠道没配好（如 webhook 未填）时静默跳过。"""
        with patch.object(ccj, "notify_channel_ready", return_value=False):
            job_id = self._create_job()
            with patch.object(xcc, "copy_file_across_clouds", return_value=_uploaded_result()):
                self._run(job_id)
        ccj._send_notify_content.assert_not_called()

    def test_notify_independent_of_other_scene_switches(self):
        """跨盘复制通知不依赖订阅成功推送开关（历史 bug：曾被 notify_push_enabled 挡掉）。"""
        self.cfg["notify_push_enabled"] = False
        job_id = self._create_job()
        with patch.object(xcc, "copy_file_across_clouds", return_value=_uploaded_result()):
            self._run(job_id)
        ccj._send_notify_content.assert_called_once()

    def test_failure_notify_respects_origin_switch(self):
        """失败通知同样按来源开关控制。"""
        self.cfg["cross_copy_notify_manual"] = False
        job_id = self._create_job()
        with patch.object(xcc, "copy_file_across_clouds", side_effect=xcc.CrossCloudCopyError("失败")):
            self._run(job_id)
        ccj._send_notify_content.assert_not_called()

    def test_notify_content_marks_trigger_origin(self):
        """通知文案标明触发方式，用户能看出是订阅补源还是手动复制。"""
        sub_job = self._create_job(origin="subscription")
        with patch.object(xcc, "copy_file_across_clouds", return_value=_uploaded_result()):
            self._run(sub_job)
        content = ccj._send_notify_content.call_args[0][1]
        self.assertIn("触发：订阅补源", content)

        ccj._send_notify_content.reset_mock()
        manual_job = self._create_job(origin="manual")
        with patch.object(xcc, "copy_file_across_clouds", return_value=_uploaded_result()):
            self._run(manual_job)
        content = ccj._send_notify_content.call_args[0][1]
        self.assertIn("触发：手动复制", content)

    def test_subscription_success_merged_into_subscription_notify(self):
        """两个开关都开时，补源成功不再逐文件发，由订阅通知统一发一条。"""
        self.cfg["notify_push_enabled"] = True
        job_id = self._create_job(origin="subscription")
        with patch.object(xcc, "copy_file_across_clouds", return_value=_uploaded_result()):
            self._run(job_id)
        ccj._send_notify_content.assert_not_called()

    def test_manual_success_still_sent_when_merge_on(self):
        """合并只针对订阅补源，手动复制照旧逐条发。"""
        self.cfg["notify_push_enabled"] = True
        job_id = self._create_job(origin="manual")
        with patch.object(xcc, "copy_file_across_clouds", return_value=_uploaded_result()):
            self._run(job_id)
        ccj._send_notify_content.assert_called_once()

    def test_subscription_success_sent_when_push_switch_off(self):
        """订阅成功推送关着（只开补源开关）时退回逐条发，消息不能丢。"""
        self.cfg["notify_push_enabled"] = False
        job_id = self._create_job(origin="subscription")
        with patch.object(xcc, "copy_file_across_clouds", return_value=_uploaded_result()):
            self._run(job_id)
        ccj._send_notify_content.assert_called_once()

    def test_subscription_failure_still_sent_when_merge_on(self):
        """失败不合并：得知道是哪一集挂了。"""
        self.cfg["notify_push_enabled"] = True
        job_id = self._create_job(origin="subscription")
        with patch.object(xcc, "copy_file_across_clouds", side_effect=xcc.CrossCloudCopyError("下载失败")):
            self._run(job_id)
        ccj._send_notify_content.assert_called_once()
        self.assertIn("跨盘复制失败", ccj._send_notify_content.call_args[0][1])

    def test_missing_cookie_fails(self):
        self.target_provider._cookie = ""
        job_id = self._create_job()
        with patch.object(xcc, "copy_file_across_clouds") as m_copy:
            self._run(job_id)
        m_copy.assert_not_called()
        job = ccj.get_cross_copy_job(job_id)
        self.assertEqual(job["status"], "failed")
        self.assertIn("认证信息", job["error_message"])

    def test_same_provider_rejected(self):
        job_id = self._create_job(source_provider="115", target_provider="115")
        with patch.object(xcc, "copy_file_across_clouds") as m_copy:
            self._run(job_id)
        m_copy.assert_not_called()
        job = ccj.get_cross_copy_job(job_id)
        self.assertEqual(job["status"], "failed")
        self.assertIn("同一个网盘", job["error_message"])


class TestStartupRequeue(CrossCopyJobsTestBase):
    def test_requeue_running_and_pending(self):
        self._create_job(title="A")
        running_id = self._create_job(title="B")
        ccj.update_cross_copy_job(running_id, status="running")
        done_id = self._create_job(title="C")
        ccj.update_cross_copy_job(done_id, status="completed")
        result = ccj.requeue_cross_copy_jobs_on_startup()
        self.assertEqual(result["requeued"], 2)
        ccj.submit_background.assert_called()

    def test_requeue_skips_paused(self):
        """暂停的任务重启后保持暂停，不自动续跑。"""
        paused_id = self._create_job(title="已暂停")
        ccj.update_cross_copy_job(paused_id, status="paused")
        result = ccj.requeue_cross_copy_jobs_on_startup()
        self.assertEqual(result["requeued"], 0)
        job = ccj.get_cross_copy_job(paused_id)
        self.assertEqual(job["status"], "paused")


class TestRoutes(CrossCopyJobsTestBase):
    def test_capabilities(self):
        result = asyncio.run(cross_copy_routes.get_cross_copy_capabilities(FakeQueryRequest({})))
        self.assertTrue(result["ok"])
        names = {p["name"] for p in result["providers"]}
        self.assertIn("quark", names)
        self.assertIn("115", names)
        combos = {(c["source"], c["target"]) for c in result["combinations"]}
        self.assertIn(("quark", "115"), combos)
        self.assertNotIn(("115", "115"), combos)

    def test_create_job_endpoint(self):
        with patch.object(ccj, "submit_cross_copy_job") as m_submit:
            result = asyncio.run(
                cross_copy_routes.create_cross_copy_job_endpoint(
                    FakeJsonRequest(
                        {
                            "source_provider": "quark",
                            "target_provider": "115",
                            "source_file_id": "f-1",
                            "filename": "movie.mkv",
                        }
                    )
                )
            )
        self.assertTrue(result["ok"])
        self.assertGreater(result["job_id"], 0)
        m_submit.assert_called_once_with(result["job_id"])

    def test_create_job_same_provider_rejected(self):
        result = asyncio.run(
            cross_copy_routes.create_cross_copy_job_endpoint(
                FakeJsonRequest({"source_provider": "115", "target_provider": "115", "source_file_id": "f-1"})
            )
        )
        self.assertEqual(result.status_code, 400)

    def test_create_job_unsupported_source_rejected(self):
        # 115 / 阿里都已能作为源；这里用一个不在能力清单里的网盘验证拦截
        result = asyncio.run(
            cross_copy_routes.create_cross_copy_job_endpoint(
                FakeJsonRequest({"source_provider": "baidu", "target_provider": "115", "source_file_id": "f-1"})
            )
        )
        self.assertEqual(result.status_code, 400)

    def test_create_job_empty_file_id_rejected(self):
        result = asyncio.run(
            cross_copy_routes.create_cross_copy_job_endpoint(
                FakeJsonRequest({"source_provider": "quark", "target_provider": "115"})
            )
        )
        self.assertEqual(result.status_code, 400)

    def test_job_detail_endpoint(self):
        job_id = self._create_job()
        result = asyncio.run(cross_copy_routes.get_cross_copy_job_endpoint(FakeQueryRequest({}), job_id))
        self.assertTrue(result["ok"])
        self.assertEqual(result["job"]["id"], job_id)

    def test_job_detail_missing(self):
        result = asyncio.run(cross_copy_routes.get_cross_copy_job_endpoint(FakeQueryRequest({}), 9999))
        self.assertEqual(result.status_code, 404)

    def test_list_endpoint(self):
        self._create_job()
        result = asyncio.run(cross_copy_routes.list_cross_copy_jobs_endpoint(FakeQueryRequest({})))
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["jobs"]), 1)

    def test_pause_endpoint(self):
        job_id = self._create_job()
        result = asyncio.run(cross_copy_routes.pause_cross_copy_job_endpoint(FakeJsonRequest({}), job_id))
        self.assertEqual(result.status_code, 200)
        job = ccj.get_cross_copy_job(job_id)
        self.assertEqual(job["status"], "paused")

    def test_resume_endpoint(self):
        job_id = self._create_job()
        ccj.update_cross_copy_job(job_id, status="paused")
        with patch.object(ccj, "submit_cross_copy_job"):
            result = asyncio.run(cross_copy_routes.resume_cross_copy_job_endpoint(FakeJsonRequest({}), job_id))
        self.assertEqual(result.status_code, 200)
        job = ccj.get_cross_copy_job(job_id)
        self.assertEqual(job["status"], "pending")


class TestJobPaths(CrossCopyJobsTestBase):
    """任务卡片要显示"源文件在哪、会放到哪"，所以路径必须随任务落库。"""

    def test_paths_persisted(self):
        job_id = self._create_job(
            source_path="/电影/沙丘2.mkv",
            target_path="/云下载/电影/沙丘2.mkv",
        )
        job = ccj.get_cross_copy_job(job_id)
        self.assertEqual(job["source_path"], "/电影/沙丘2.mkv")
        self.assertEqual(job["target_path"], "/云下载/电影/沙丘2.mkv")

    def test_target_path_falls_back_to_savepath_plus_filename(self):
        job_id = self._create_job(target_savepath="云下载/电影")
        job = ccj.get_cross_copy_job(job_id)
        self.assertEqual(job["target_path"], "/云下载/电影/movie.mkv")

    def test_completion_rewrites_target_path_with_final_name(self):
        job_id = self._create_job(target_savepath="云下载/电影", filename="")
        with patch.object(xcc, "copy_file_across_clouds", return_value=_uploaded_result("uploaded")):
            self._run(job_id)
        job = ccj.get_cross_copy_job(job_id)
        self.assertEqual(job["filename"], "movie.mkv")
        self.assertEqual(job["target_path"], "/云下载/电影/movie.mkv")

    def test_create_endpoint_accepts_paths(self):
        with patch.object(ccj, "submit_cross_copy_job"):
            result = asyncio.run(
                cross_copy_routes.create_cross_copy_job_endpoint(
                    FakeJsonRequest(
                        {
                            "source_provider": "quark",
                            "target_provider": "115",
                            "source_file_id": "f-1",
                            "filename": "movie.mkv",
                            "source_path": "/电影/movie.mkv",
                            "target_path": "/云下载/电影/movie.mkv",
                        }
                    )
                )
            )
        job = ccj.get_cross_copy_job(result["job_id"])
        self.assertEqual(job["source_path"], "/电影/movie.mkv")
        self.assertEqual(job["target_path"], "/云下载/电影/movie.mkv")


class TestTransferProgress(CrossCopyJobsTestBase):
    """进度除了百分比，还要有「已完成 / 总大小 · 速度」，下载与上传都要。"""

    def _age_progress(self, job_id, seconds):
        """把上一次回调的时间往前拨，模拟真实间隔（否则算不出速度/会被写库节流）。"""
        with ccj._progress_lock:
            entry = ccj._job_progress.get(job_id)
            if entry:
                entry["updated_ts"] -= seconds
            last_persist = ccj._last_db_progress.get(job_id)
            if last_persist is not None:
                ccj._last_db_progress[job_id] = last_persist - seconds

    def test_progress_exposes_bytes_and_percent_in_list(self):
        job_id = self._create_job(file_size=200 * 1024 * 1024)
        ccj._report_progress(job_id, 100 * 1024 * 1024, 200 * 1024 * 1024, "download")
        jobs = ccj.list_cross_copy_jobs(limit=10)
        progress = jobs[0]["progress"]
        self.assertEqual(progress["sent"], 100 * 1024 * 1024)
        self.assertEqual(progress["total"], 200 * 1024 * 1024)
        self.assertEqual(progress["percent"], 50)
        self.assertEqual(jobs[0]["progress_percent"], 50)

    def test_download_detail_contains_size_and_speed(self):
        job_id = self._create_job(file_size=1024 * 1024)
        ccj._report_progress(job_id, 256 * 1024, 1024 * 1024, "download")
        self._age_progress(job_id, 2.0)
        ccj._report_progress(job_id, 1024 * 1024, 1024 * 1024, "download")
        job = ccj.get_cross_copy_job(job_id)
        self.assertIn("下载", job["status_detail"])
        self.assertIn("1.00MB", job["status_detail"])
        self.assertIn("/s", job["status_detail"])
        self.assertGreater(job["progress"]["speed"], 0)

    def test_upload_detail_uses_upload_wording(self):
        job_id = self._create_job(file_size=8 * 1024 * 1024)
        ccj._report_progress(job_id, 1024 * 1024, 8 * 1024 * 1024, "upload")
        self._age_progress(job_id, 1.0)
        ccj._report_progress(job_id, 4 * 1024 * 1024, 8 * 1024 * 1024, "upload")
        job = ccj.get_cross_copy_job(job_id)
        self.assertIn("上传", job["status_detail"])
        self.assertIn("4.00MB / 8.00MB", job["status_detail"])

    def test_speed_uses_previous_frame_even_with_nonpositive_timestamp(self):
        """判断「有没有上一帧」只看有没有记录，不看时间戳是否大于 0。

        沙箱/容器的 monotonic 可能从 0 附近起步，把上一帧往前拨就落到 0 以下；
        拿 0 当哨兵会把这一帧当成不存在，速度静默变成 0、界面看不到速率。
        """
        job_id = self._create_job(file_size=1024 * 1024)
        with patch.object(ccj.time, "monotonic", return_value=1.0):
            ccj._report_progress(job_id, 512 * 1024, 1024 * 1024, "download")
            with ccj._progress_lock:
                ccj._job_progress[job_id]["updated_ts"] = -0.5
            ccj._report_progress(job_id, 1024 * 1024, 1024 * 1024, "download")
        progress = ccj.get_cross_copy_job(job_id)["progress"]
        self.assertGreater(progress["speed"], 0)

    def test_speed_resets_when_phase_changes(self):
        job_id = self._create_job(file_size=1024 * 1024)
        ccj._report_progress(job_id, 512 * 1024, 1024 * 1024, "download")
        self._age_progress(job_id, 1.0)
        ccj._report_progress(job_id, 1024 * 1024, 1024 * 1024, "download")
        self.assertGreater(ccj.get_cross_copy_job(job_id)["progress"]["speed"], 0)
        self._age_progress(job_id, 1.0)
        ccj._report_progress(job_id, 128 * 1024, 1024 * 1024, "upload")
        progress = ccj.get_cross_copy_job(job_id)["progress"]
        self.assertEqual(progress["phase"], "upload")
        self.assertEqual(progress["speed"], 0)

    def test_progress_write_is_throttled_but_never_drops_final_chunk(self):
        job_id = self._create_job(file_size=4 * 1024 * 1024)
        ccj._report_progress(job_id, 1024 * 1024, 4 * 1024 * 1024, "download")
        ccj._report_progress(job_id, 2 * 1024 * 1024, 4 * 1024 * 1024, "download")
        # 中间块被节流：DB 里还是第一次的 25%
        self.assertEqual(ccj.get_cross_copy_job(job_id)["progress_percent"], 25)
        # 最后一块必须落库
        ccj._report_progress(job_id, 4 * 1024 * 1024, 4 * 1024 * 1024, "download")
        self.assertEqual(ccj.get_cross_copy_job(job_id)["progress_percent"], 100)

    def test_format_transfer_size(self):
        self.assertEqual(ccj.format_transfer_size(0), "0B")
        self.assertEqual(ccj.format_transfer_size(1024), "1.00KB")
        self.assertEqual(ccj.format_transfer_size(2797571732), "2.61GB")


class BackgroundLoopRunner:
    """测试用后台事件循环：真的把 submit 出去的协程跑起来（替代 background_runtime）。

    线上 submit_background 会把协程丢到后台线程的 loop 上；这里起一个同样的
    loop，才能验证「同时只跑 N 个」这类行为，而不是只验证调用次数。
    """

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.submitted = []
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="ccj-test-loop", daemon=True)
        self._thread.start()
        self._ready.wait(5)

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self._ready.set()
        self.loop.run_forever()

    def __call__(self, job_factory, *args, label="", **kwargs):
        with self._lock:
            self.submitted.append(args[0] if args else 0)
        return asyncio.run_coroutine_threadsafe(job_factory(*args, **kwargs), self.loop)

    def close(self):
        if self.loop.is_closed():
            return
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(5)
        self.loop.close()


class QueueTestBase(CrossCopyJobsTestBase):
    """排队/并发用例基类：后台任务真跑，复制引擎卡在闸门上由用例逐个放行。"""

    max_concurrent = 2
    env_max_concurrent = None

    def setUp(self):
        super().setUp()
        self._env_patch = None
        if self.env_max_concurrent is not None:
            self._env_patch = patch.dict(
                os.environ, {"CROSS_COPY_MAX_CONCURRENT": self.env_max_concurrent}
            )
            self._env_patch.start()
            effective = ccj._resolve_max_concurrent()
        else:
            effective = self.max_concurrent
        self.runner = BackgroundLoopRunner()
        self.gate = threading.Semaphore(0)
        self.engine_calls = []
        self._engine_lock = threading.Lock()
        self._queue_patchers = [
            patch.object(ccj, "submit_background", self.runner),
            patch.object(ccj, "MAX_CONCURRENT_JOBS", effective),
            patch.object(xcc, "copy_file_across_clouds", side_effect=self._blocking_engine),
        ]
        for p in self._queue_patchers:
            p.start()

    def tearDown(self):
        # 先放行所有卡住的任务，等后台 loop 收尾，再恢复 DB 路径，避免写回真实库
        self.gate.release(100)
        self._wait_for(lambda: not ccj._queued and not ccj._active, timeout=15)
        for p in self._queue_patchers:
            p.stop()
        self.runner.close()
        if self._env_patch is not None:
            self._env_patch.stop()
        super().tearDown()

    def _blocking_engine(self, **kwargs):
        with self._engine_lock:
            self.engine_calls.append(str(kwargs.get("filename", "") or ""))
        self.gate.acquire(timeout=15)
        return _uploaded_result()

    def _wait_for(self, predicate, timeout=8.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.02)
        return bool(predicate())

    def _status(self, job_id):
        return ccj.get_cross_copy_job(job_id)["status"]

    def _detail(self, job_id):
        return str(ccj.get_cross_copy_job(job_id)["status_detail"] or "")

    def _submit_all(self, job_ids):
        for job_id in job_ids:
            ccj.submit_cross_copy_job(job_id)


class TestGlobalConcurrencyLimit(QueueTestBase):
    """一次粘一堆文件：同时只跑上限那么多，其余排队。"""

    max_concurrent = 2

    def test_five_jobs_only_two_run_rest_wait(self):
        job_ids = [self._create_job(title=f"J{i}", filename=f"m{i}.mkv") for i in range(5)]
        self._submit_all(job_ids)

        self.assertTrue(self._wait_for(lambda: self._status(job_ids[0]) == "running"))
        self.assertTrue(self._wait_for(lambda: self._status(job_ids[1]) == "running"))
        # 只有两个任务真的在下载
        self.assertTrue(self._wait_for(lambda: len(self.engine_calls) == 2))
        time.sleep(0.2)  # 给可能多派发的任务一点时间露头
        self.assertEqual(self._status(job_ids[0]), "running")
        self.assertEqual(self._status(job_ids[1]), "running")
        for job_id in job_ids[2:]:
            self.assertEqual(self._status(job_id), "pending")
        self.assertEqual(len(self.engine_calls), 2)
        self.assertEqual(sorted(ccj._active), job_ids[:2])
        self.assertEqual(ccj._queued, job_ids[2:])

    def test_queue_position_counts_down(self):
        job_ids = [self._create_job(title=f"J{i}", filename=f"m{i}.mkv") for i in range(5)]
        self._submit_all(job_ids)

        # 排队的 3 个：前面有 2 个在跑 + 自己前面排了几个
        self.assertTrue(self._wait_for(lambda: "前面还有 2 个任务" in self._detail(job_ids[2])))
        self.assertIn("前面还有 3 个任务", self._detail(job_ids[3]))
        self.assertIn("前面还有 4 个任务", self._detail(job_ids[4]))
        self.assertIn("排队中", self._detail(job_ids[2]))

        # 放行一个：第 3 个开跑，后面的位置往前挪
        self.gate.release()
        self.assertTrue(self._wait_for(lambda: self._status(job_ids[2]) == "running"))
        self.assertTrue(self._wait_for(lambda: "前面还有 2 个任务" in self._detail(job_ids[3])))
        self.assertIn("前面还有 3 个任务", self._detail(job_ids[4]))


class TestQueueAdvance(QueueTestBase):
    max_concurrent = 1

    def test_next_job_starts_after_previous_finishes(self):
        job_ids = [self._create_job(title=f"J{i}", filename=f"m{i}.mkv") for i in range(3)]
        self._submit_all(job_ids)

        self.assertTrue(self._wait_for(lambda: len(self.engine_calls) == 1))
        self.assertEqual(self._status(job_ids[0]), "running")
        self.assertEqual(self._status(job_ids[1]), "pending")
        self.assertEqual(self._status(job_ids[2]), "pending")

        self.gate.release()
        self.assertTrue(self._wait_for(lambda: self._status(job_ids[0]) == "completed"))
        self.assertTrue(self._wait_for(lambda: self._status(job_ids[1]) == "running"))
        self.assertTrue(self._wait_for(lambda: self.engine_calls == ["m0.mkv", "m1.mkv"]))

    def test_cancel_queued_job_never_runs(self):
        job_ids = [self._create_job(title=f"J{i}", filename=f"m{i}.mkv") for i in range(3)]
        self._submit_all(job_ids)
        self.assertTrue(self._wait_for(lambda: len(self.engine_calls) == 1))

        result = ccj.cancel_cross_copy_job(job_ids[1])
        self.assertTrue(result["ok"])
        self.assertEqual(self._status(job_ids[1]), "cancelled")
        self.assertNotIn(job_ids[1], ccj._queued)

        # 放行后面所有任务：被取消的那个不能借空闲名额复活
        self.gate.release(10)
        self.assertTrue(self._wait_for(lambda: self._status(job_ids[2]) == "completed"))
        self.assertEqual(self._status(job_ids[1]), "cancelled")
        self.assertEqual(self.engine_calls, ["m0.mkv", "m2.mkv"])

    def test_exception_releases_slot(self):
        """任务抛异常也必须还名额，否则后面的任务永远排不上（名额泄漏）。"""
        job_ids = [self._create_job(title=f"J{i}", filename=f"m{i}.mkv") for i in range(2)]

        def flaky_engine(**kwargs):
            with self._engine_lock:
                self.engine_calls.append(str(kwargs.get("filename", "") or ""))
            if len(self.engine_calls) == 1:
                raise ValueError("boom")
            return _uploaded_result()

        with patch.object(xcc, "copy_file_across_clouds", side_effect=flaky_engine):
            self._submit_all(job_ids)
            self.assertTrue(self._wait_for(lambda: self._status(job_ids[1]) == "completed"))
        self.assertEqual(self._status(job_ids[0]), "failed")
        self.assertEqual(self.engine_calls, ["m0.mkv", "m1.mkv"])
        self.assertTrue(self._wait_for(lambda: not ccj._active))


class TestEnvMaxConcurrent(QueueTestBase):
    """CROSS_COPY_MAX_CONCURRENT=1：串行执行。"""

    env_max_concurrent = "1"

    def test_env_one_runs_serially(self):
        self.assertEqual(ccj._resolve_max_concurrent(), 1)
        job_ids = [self._create_job(title=f"J{i}", filename=f"m{i}.mkv") for i in range(3)]
        self._submit_all(job_ids)

        self.assertTrue(self._wait_for(lambda: len(self.engine_calls) == 1))
        time.sleep(0.2)
        self.assertEqual(len(self.engine_calls), 1)
        self.assertEqual(self._status(job_ids[1]), "pending")
        self.assertEqual(self._status(job_ids[2]), "pending")

    def test_invalid_values_fall_back_to_default(self):
        for raw in ("0", "abc", "99", "-3", ""):
            with patch.dict(os.environ, {"CROSS_COPY_MAX_CONCURRENT": raw}):
                self.assertEqual(ccj._resolve_max_concurrent(), ccj.DEFAULT_MAX_CONCURRENT, raw)

    def test_valid_values_are_used(self):
        for raw, expected in (("1", 1), ("3", 3), ("8", 8)):
            with patch.dict(os.environ, {"CROSS_COPY_MAX_CONCURRENT": raw}):
                self.assertEqual(ccj._resolve_max_concurrent(), expected)

    def test_missing_env_uses_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CROSS_COPY_MAX_CONCURRENT", None)
            self.assertEqual(ccj._resolve_max_concurrent(), 2)


class TestStartupRequeueQueue(QueueTestBase):
    """启动恢复同样走排队路径，重启后不会一次全起跑。"""

    max_concurrent = 1

    def test_requeue_only_starts_one(self):
        job_ids = [self._create_job(title=f"J{i}", filename=f"m{i}.mkv") for i in range(3)]
        result = ccj.requeue_cross_copy_jobs_on_startup()
        self.assertEqual(result["requeued"], 3)

        self.assertTrue(self._wait_for(lambda: len(self.engine_calls) == 1))
        self.assertEqual(self.engine_calls, ["m0.mkv"])
        self.assertEqual(ccj._queued, job_ids[1:])
        self.assertEqual(self._status(job_ids[1]), "pending")
        self.assertIn("排队中", self._detail(job_ids[1]))


class TestTargetDirIdResolution(CrossCopyJobsTestBase):
    """只给「保存到哪个路径」的任务，执行前必须先把路径换成目录 id。

    订阅补源走的是这条入口：它只知道 savepath，不知道目录 id。如果不补这一步，
    文件会被传到根目录——任务显示成功，东西却存错了地方。
    """

    def _create_savepath_job(self, **overrides):
        params = dict(
            title="补源任务",
            source_provider="quark",
            target_provider="115",
            source_file_id="f-quark-9",
            target_savepath="/云下载/电影",
            filename="movie.mkv",
            file_size=1024,
        )
        params.update(overrides)
        return ccj.create_cross_copy_job(**params)

    def test_resolves_target_dir_id_from_savepath(self):
        calls = []

        def fake_ensure(cookie, path):
            calls.append((cookie, path))
            return "dir-resolved"

        self.target_provider.ensure_folder_id_by_path = fake_ensure
        job_id = self._create_savepath_job()
        captured = {}

        def fake_copy(**kwargs):
            captured.update(kwargs)
            return _uploaded_result("uploaded")

        with patch.object(xcc, "copy_file_across_clouds", side_effect=fake_copy):
            self._run(job_id)

        self.assertEqual(calls, [("cookie-x", "/云下载/电影")])
        self.assertEqual(captured.get("target_dir_id"), "dir-resolved")
        # 解析结果要落库，避免重试时再解析一次
        self.assertEqual(ccj.get_cross_copy_job(job_id)["target_dir_id"], "dir-resolved")

    def test_explicit_target_dir_id_is_kept(self):
        """已经给了目录 id 的任务不能被路径解析覆盖。"""
        self.target_provider.ensure_folder_id_by_path = MagicMock(return_value="dir-other")
        job_id = self._create_job()  # 默认 target_dir_id="dir-115"
        captured = {}

        def fake_copy(**kwargs):
            captured.update(kwargs)
            return _uploaded_result("uploaded")

        with patch.object(xcc, "copy_file_across_clouds", side_effect=fake_copy):
            self._run(job_id)

        self.target_provider.ensure_folder_id_by_path.assert_not_called()
        self.assertEqual(captured.get("target_dir_id"), "dir-115")

    def test_resolve_failure_fails_job_instead_of_root_upload(self):
        """解析失败要明确失败，绝不能悄悄传到根目录。"""
        self.target_provider.ensure_folder_id_by_path = MagicMock(side_effect=RuntimeError("目录不可写"))
        job_id = self._create_savepath_job()

        def fake_copy(**kwargs):
            raise AssertionError("解析失败时不应该开始复制")

        with patch.object(xcc, "copy_file_across_clouds", side_effect=fake_copy):
            self._run(job_id)

        job = ccj.get_cross_copy_job(job_id)
        self.assertEqual(job["status"], "failed")
        self.assertIn("保存目录", job["status_detail"])

    def test_empty_resolve_result_fails_job(self):
        self.target_provider.ensure_folder_id_by_path = MagicMock(return_value="")
        job_id = self._create_savepath_job()

        def fake_copy(**kwargs):
            raise AssertionError("解析失败时不应该开始复制")

        with patch.object(xcc, "copy_file_across_clouds", side_effect=fake_copy):
            self._run(job_id)

        job = ccj.get_cross_copy_job(job_id)
        self.assertEqual(job["status"], "failed")
        self.assertIn("/云下载/电影", job["status_detail"])


class TestStartupTempCleanup(CrossCopyJobsTestBase):
    """启动时要扫掉上次硬中断留下的半截临时文件（此前只测过函数，没人调它）。"""

    def test_cleans_orphan_files_in_resolved_temp_dir(self):
        temp_root = tempfile.mkdtemp(prefix="xcopy-start-", dir=self.tmp)
        old = os.path.join(temp_root, "xcopy-crashed.part")
        with open(old, "w") as fh:
            fh.write("x")
        os.utime(old, (0, 0))

        with patch.object(xcc, "resolve_temp_dir", return_value=temp_root):
            result = ccj.cleanup_temp_files_on_startup()

        self.assertEqual(result["removed"], 1)
        self.assertFalse(os.path.exists(old))

    def test_cleanup_failure_does_not_raise(self):
        """清理出错不能把启动拉不起来。"""
        with patch.object(xcc, "resolve_temp_dir", side_effect=RuntimeError("配置坏了")):
            result = ccj.cleanup_temp_files_on_startup()
        self.assertEqual(result["removed"], 0)

    def test_no_temp_dir_is_noop(self):
        with patch.object(xcc, "resolve_temp_dir", return_value=""):
            result = ccj.cleanup_temp_files_on_startup()
        self.assertEqual(result["removed"], 0)


class TestNon115TargetDetail(CrossCopyJobsTestBase):
    """非 115 目标完成文案必须说明「不会自动处理」。

    监控任务只绑在 115 上，复制到夸克/阿里/天翼后既不生成 STRM 也不整理文件名。
    2026-10-20 决策是「不自动猜用户意图去刮削」，那就必须把这件事讲明白，
    否则用户会以为系统坏了（复制成功但库里看不到）。
    """

    def _run_to_completion(self, target_name):
        target = FakeProvider(target_name, "阿里云盘" if target_name == "aliyun" else "115网盘")
        mapping = {"quark": self.source_provider, "115": self.target_provider, target_name: target}
        job_id = self._create_job(target_provider=target_name, target_dir_id="dir-t")
        with patch.object(
            ccj, "_get_provider_or_none", side_effect=lambda name: mapping.get(name)
        ), patch.object(xcc, "copy_file_across_clouds", return_value=_uploaded_result("uploaded")):
            self._run(job_id)
        return ccj.get_cross_copy_job(job_id)

    def test_non_115_target_tells_user_no_auto_processing(self):
        job = self._run_to_completion("aliyun")
        self.assertEqual(job["status"], "completed")
        self.assertIn("非 115", job["status_detail"])
        self.assertIn("STRM", job["status_detail"])
        # 必须给出可操作去处，不能只说「不行」
        self.assertIn("文件管理", job["status_detail"])
        # 前端只渲染 resultHint，所以必须同时给结构化字段，否则卡片上看不到
        self.assertIn("非 115", job["result"]["no_monitor_note"])

    def test_115_target_keeps_plain_detail(self):
        job = self._run_to_completion("115")
        self.assertEqual(job["status"], "completed")
        self.assertNotIn("非 115", job["status_detail"])
        self.assertNotIn("no_monitor_note", job["result"])

    def test_folder_job_also_tells_user(self):
        """文件夹任务走另一条收口函数，文案不能漏。"""
        result = SimpleNamespace(
            status="completed",
            folder_name="片子",
            target_path="/云下载/片子",
            total_bytes=2048,
            message="3 个文件已复制",
        )
        job_id = self._create_job(
            target_provider="aliyun", target_dir_id="dir-t", source_is_dir=1, filename="片子"
        )
        job = ccj.get_cross_copy_job(job_id)
        ccj._finish_folder_job(job_id, job, self.cfg, result)
        detail = ccj.get_cross_copy_job(job_id)["status_detail"]
        self.assertIn("非 115", detail)
        self.assertIn("3 个文件已复制", detail)


class TestJobRecordCleanup(CrossCopyJobsTestBase):
    """任务记录管理：和导入/刮削任务一样，成功的、失败的都能清掉。

    规矩只有一条——**只删记录**：网盘上的文件不动，正在跑的任务也不动。
    """

    def _make(self, status, **overrides):
        job_id = self._create_job(**overrides)
        ccj.update_cross_copy_job(job_id, status=status, finished_at="2026-10-20T10:00:00")
        return job_id

    def test_counts_group_by_status(self):
        self._make("completed")
        self._make("failed")
        self._make("cancelled")
        self._make("skipped")
        active_id = self._create_job(source_file_id="f-active")
        counts = ccj.get_cross_copy_job_counts()
        self.assertEqual(counts["completed"], 1)
        self.assertEqual(counts["failed"], 1)
        self.assertEqual(counts["cancelled"], 1)
        self.assertEqual(counts["skipped"], 1)
        self.assertEqual(counts["pending"], 1)
        self.assertEqual(counts["total"], 5)
        self.assertEqual(counts["active"], 1)
        # 「已结束」= 成功 + 失败 + 已取消 + 已跳过
        self.assertEqual(counts["terminal"], 4)
        self.assertTrue(active_id > 0)

    def test_clear_completed_only(self):
        completed_id = self._make("completed")
        failed_id = self._make("failed")
        cancelled_id = self._make("cancelled")
        result = ccj.clear_cross_copy_jobs("completed")
        self.assertEqual(result["deleted"], 1)
        self.assertEqual(result["scope"], "completed")
        self.assertIsNone(ccj.get_cross_copy_job(completed_id))
        self.assertIsNotNone(ccj.get_cross_copy_job(failed_id))
        self.assertIsNotNone(ccj.get_cross_copy_job(cancelled_id))

    def test_clear_failed_only(self):
        self._make("completed")
        failed_id = self._make("failed")
        result = ccj.clear_cross_copy_jobs("failed")
        self.assertEqual(result["deleted"], 1)
        self.assertIsNone(ccj.get_cross_copy_job(failed_id))
        self.assertEqual(ccj.get_cross_copy_job_counts()["completed"], 1)

    def test_clear_terminal_includes_cancelled_and_skipped(self):
        """「清空已结束」必须把取消/跳过也收走，否则用户会觉得清不干净。"""
        for status in ("completed", "failed", "cancelled", "skipped"):
            self._make(status)
        running_id = self._create_job(source_file_id="f-running")
        ccj.update_cross_copy_job(running_id, status="running")
        result = ccj.clear_cross_copy_jobs("terminal")
        self.assertEqual(result["deleted"], 4)
        counts = ccj.get_cross_copy_job_counts()
        self.assertEqual(counts["total"], 1)
        self.assertEqual(counts["running"], 1)

    def test_clear_never_touches_active_jobs(self):
        pending_id = self._create_job(source_file_id="f-pending")
        ccj.clear_cross_copy_jobs("terminal")
        self.assertIsNotNone(ccj.get_cross_copy_job(pending_id))

    def test_delete_single_terminal_record(self):
        job_id = self._make("failed")
        result = ccj.delete_cross_copy_job(job_id)
        self.assertTrue(result["ok"])
        self.assertEqual(result["deleted"], 1)
        self.assertIsNone(ccj.get_cross_copy_job(job_id))

    def test_delete_rejects_active_job(self):
        job_id = self._create_job(source_file_id="f-active-2")
        result = ccj.delete_cross_copy_job(job_id)
        self.assertFalse(result["ok"])
        self.assertIn("进行中", result["msg"])
        self.assertIsNotNone(ccj.get_cross_copy_job(job_id))

    def test_delete_missing_job(self):
        result = ccj.delete_cross_copy_job(999999)
        self.assertFalse(result["ok"])
        self.assertIn("不存在", result["msg"])

    def test_prune_keeps_recent_records(self):
        for index in range(5):
            self._make("completed", source_file_id=f"f-c-{index}")
        for index in range(3):
            self._make("failed", source_file_id=f"f-x-{index}")
        ccj.prune_cross_copy_job_history(completed_keep=50, failed_keep=50)
        # keep 有下限 50，5 条不会被裁
        self.assertEqual(ccj.get_cross_copy_job_counts()["total"], 8)

    def test_prune_removes_overflow(self):
        for index in range(60):
            self._make("completed", source_file_id=f"f-overflow-{index}")
        result = ccj.prune_cross_copy_job_history(completed_keep=50, failed_keep=50)
        self.assertEqual(result["completed"], 10)
        self.assertEqual(ccj.get_cross_copy_job_counts()["completed"], 50)

    def test_clear_route(self):
        self._make("completed")
        self._make("failed")
        result = asyncio.run(
            cross_copy_routes.clear_cross_copy_jobs_endpoint(FakeJsonRequest({"scope": "terminal"}))
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["deleted"], 2)
        self.assertEqual(ccj.get_cross_copy_job_counts()["total"], 0)

    def test_clear_route_rejects_unknown_scope(self):
        result = asyncio.run(
            cross_copy_routes.clear_cross_copy_jobs_endpoint(FakeJsonRequest({"scope": "everything"}))
        )
        self.assertEqual(result.status_code, 400)

    def test_clear_route_without_body_defaults_to_terminal(self):
        self._make("cancelled")
        result = asyncio.run(cross_copy_routes.clear_cross_copy_jobs_endpoint(FakeJsonRequest({})))
        self.assertTrue(result["ok"])
        self.assertEqual(result["deleted"], 1)

    def test_delete_route(self):
        job_id = self._make("completed")
        result = asyncio.run(
            cross_copy_routes.delete_cross_copy_job_endpoint(FakeJsonRequest({}), job_id)
        )
        # 路由统一用 JSONResponse 回包（和 cancel / retry 一致），body 里才是结果
        self.assertEqual(result.status_code, 200)
        self.assertTrue(json.loads(result.body)["ok"])
        self.assertIsNone(ccj.get_cross_copy_job(job_id))

    def test_delete_route_rejects_running(self):
        job_id = self._create_job(source_file_id="f-running-route")
        ccj.update_cross_copy_job(job_id, status="running")
        result = asyncio.run(
            cross_copy_routes.delete_cross_copy_job_endpoint(FakeJsonRequest({}), job_id)
        )
        self.assertEqual(result.status_code, 400)

    def test_list_endpoint_returns_table_wide_counts(self):
        """列表只回最近 N 条，但 counts 必须是整表数字，否则「清空」按钮的角标会骗人。"""
        self._make("completed")
        self._make("failed")
        result = asyncio.run(
            cross_copy_routes.list_cross_copy_jobs_endpoint(FakeQueryRequest({"limit": "1"}))
        )
        self.assertEqual(len(result["jobs"]), 1)
        self.assertEqual(result["counts"]["total"], 2)
        self.assertEqual(result["counts"]["terminal"], 2)


class TestResumeTaskLayer(CrossCopyJobsTestBase):
    """任务层断点续传（F2）：引擎契约参数、终态清/留、删记录联动删临时文件。

    引擎 copy_file_across_clouds 由并行实施的另一方负责，这里一律 monkeypatch
    记录 kwargs；build_resume_state 也 patch 掉，隔离源端哈希复探。
    """

    def _resume_state(self, temp_path=None):
        path = temp_path or os.path.join(self.tmp, "xcopy-resume.part")
        # 落一个真实文件：可继承性判断要求 temp_path 在磁盘上存在
        with open(path, "wb") as fh:
            fh.write(b"x" * 512)
        return {
            "temp_path": path,
            "size": 1024,
            "sha1": "",
            "md5": "",
            "downloaded_bytes": 512,
            "upload": {},
        }

    def test_single_file_job_passes_resume_to_engine(self):
        job_id = self._create_job()
        state = self._resume_state()
        captured = {}

        def fake_engine(**kwargs):
            captured.update(kwargs)
            return _uploaded_result()

        with patch.object(ccj, "build_resume_state", return_value=state), \
             patch.object(xcc, "copy_file_across_clouds", side_effect=fake_engine):
            self._run(job_id)
        self.assertIs(captured.get("resume"), state)
        self.assertTrue(callable(captured.get("on_resume_update")))

    def test_no_resume_state_passes_skeleton(self):
        """没有可继承断点时也传空骨架 + 落库回调（bootstrap 续传链）。"""
        job_id = self._create_job()
        captured = {}

        def fake_engine(**kwargs):
            captured.update(kwargs)
            return _uploaded_result()

        with patch.object(ccj, "build_resume_state", return_value=None), \
             patch.object(xcc, "copy_file_across_clouds", side_effect=fake_engine):
            self._run(job_id)
        resume = captured.get("resume")
        self.assertIsInstance(resume, dict)
        self.assertEqual(resume.get("temp_path"), "")
        self.assertTrue(callable(captured.get("on_resume_update")))

    def test_success_clears_resume_state(self):
        job_id = self._create_job()
        ccj.update_cross_copy_job(job_id, resume=self._resume_state())
        with patch.object(ccj, "build_resume_state", return_value=self._resume_state()), \
             patch.object(xcc, "copy_file_across_clouds", return_value=_uploaded_result()):
            self._run(job_id)
        job = ccj.get_cross_copy_job(job_id)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["resume"], {})

    def test_cancel_keeps_resume_state_with_hint(self):
        job_id = self._create_job()
        ccj.update_cross_copy_job(job_id, resume=self._resume_state())

        def cancelled_engine(**kwargs):
            raise xcc.CrossCloudCopyCancelled("已取消")

        with patch.object(ccj, "build_resume_state", return_value=self._resume_state()), \
             patch.object(xcc, "copy_file_across_clouds", side_effect=cancelled_engine):
            self._run(job_id)
        job = ccj.get_cross_copy_job(job_id)
        self.assertEqual(job["status"], "cancelled")
        # 断点被保留（终态保底落库），文案告诉用户可以重试续传
        self.assertEqual(job["resume"]["downloaded_bytes"], 512)
        self.assertIn("已保留断点，重试可续传", job["status_detail"])

    def test_failure_keeps_resume_state(self):
        job_id = self._create_job()
        ccj.update_cross_copy_job(job_id, resume=self._resume_state())
        with patch.object(ccj, "build_resume_state", return_value=self._resume_state()), \
             patch.object(
                 xcc, "copy_file_across_clouds", side_effect=xcc.CrossCloudCopyError("网络错误")
             ):
            self._run(job_id)
        job = ccj.get_cross_copy_job(job_id)
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["resume"]["downloaded_bytes"], 512)

    def test_folder_job_passes_no_resume(self):
        """文件夹任务不继承断点：check_existing 跳过已完成文件，进行中的重下。"""
        from app.services import cross_cloud_copy_folder as xccf
        from types import SimpleNamespace

        job_id = self._create_job(source_is_dir=True, filename="剧集文件夹")
        captured = {}

        def fake_folder(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                status="completed",
                folder_name="剧集文件夹",
                total_bytes=10,
                message="ok",
                to_dict=lambda: {"status": "completed"},
            )

        with patch.object(xccf, "copy_folder_across_clouds", side_effect=fake_folder):
            self._run(job_id)
        self.assertNotIn("resume", captured)
        self.assertNotIn("on_resume_update", captured)

    def test_delete_job_removes_resume_temp_file(self):
        temp_path = os.path.join(self.tmp, "xcopy-del.part")
        with open(temp_path, "wb") as fh:
            fh.write(b"x")
        job_id = self._create_job()
        ccj.update_cross_copy_job(job_id, resume=self._resume_state(temp_path))
        ccj.update_cross_copy_job(job_id, status="failed", finished_at=ccj.now_text())
        with patch("os.remove") as m_remove:
            result = ccj.delete_cross_copy_job(job_id)
        self.assertTrue(result["ok"])
        m_remove.assert_called_once_with(temp_path)

    def test_clear_jobs_removes_resume_temp_files(self):
        paths = []
        for index in range(2):
            temp_path = os.path.join(self.tmp, f"xcopy-clear-{index}.part")
            with open(temp_path, "wb") as fh:
                fh.write(b"x")
            paths.append(temp_path)
            job_id = self._create_job(title=f"J{index}")
            ccj.update_cross_copy_job(job_id, resume=self._resume_state(temp_path))
            ccj.update_cross_copy_job(job_id, status="failed", finished_at=ccj.now_text())
        with patch("os.remove") as m_remove:
            result = ccj.clear_cross_copy_jobs("failed")
        self.assertEqual(result["deleted"], 2)
        removed = [call.args[0] for call in m_remove.call_args_list]
        self.assertEqual(sorted(removed), sorted(paths))


class TestFolderMonitorTrigger(CrossCopyJobsTestBase):
    """订阅补源整包文件夹落地后触发监控扫描（单文件走整理定时器，先改名再扫描）。"""

    def _folder_result(self):
        from types import SimpleNamespace

        return SimpleNamespace(
            status="completed",
            folder_name="光阴之外 (2025)",
            total_bytes=10,
            message="ok",
            to_dict=lambda: {"status": "completed"},
        )

    def test_subscription_folder_job_triggers_monitor(self):
        from app.services import cross_cloud_copy_folder as xccf

        self.cfg["mount_points"] = [{"provider": "115", "prefix": "/115"}]
        self.cfg["monitor_tasks"] = [{"name": "影视库监控", "scan_path": "/115/115连载中"}]
        job_id = self._create_job(
            source_is_dir=True,
            filename="光阴之外 (2025)",
            origin="subscription",
            origin_ref="光阴之外",
            target_savepath="115连载中/光阴之外 (2025)",
        )

        with patch.object(xccf, "copy_folder_across_clouds", return_value=self._folder_result()), \
             patch("app.services.monitor.queue_monitor_job", return_value="queued") as queue_mock:
            self._run(job_id)

        queue_mock.assert_called_once_with(
            "影视库监控",
            "subscription",
            {"savepath": "115连载中/光阴之外 (2025)", "title": "跨盘补源：光阴之外"},
        )

    def test_manual_folder_job_triggers_monitor(self):
        """手动复制的文件夹落在 115 监控目录内时同样触发监控扫描。"""
        from app.services import cross_cloud_copy_folder as xccf

        self.cfg["mount_points"] = [{"provider": "115", "prefix": "/115"}]
        self.cfg["monitor_tasks"] = [{"name": "影视库监控", "scan_path": "/115/115连载中"}]
        job_id = self._create_job(
            source_is_dir=True,
            filename="某文件夹",
            target_savepath="115连载中/某文件夹",
        )

        with patch.object(xccf, "copy_folder_across_clouds", return_value=self._folder_result()), \
             patch("app.services.monitor.queue_monitor_job", return_value="queued") as queue_mock:
            self._run(job_id)

        queue_mock.assert_called_once_with(
            "影视库监控",
            "subscription",
            {"savepath": "115连载中/某文件夹", "title": "跨盘补源：115连载中/某文件夹"},
        )


class TestCrossCopyNotifyConfig(unittest.TestCase):
    """core 的配置归一化：跨盘复制通知按任务来源分两个开关，旧字段一次性迁移。"""

    def _normalize(self, cfg):
        from app import core

        merged = dict(cfg)
        core._normalize_cross_copy_notify_config(merged)
        return merged

    def test_defaults_on(self):
        """新安装默认两个开关都开（与旧版 cross_copy_notify 默认行为一致）。"""
        merged = self._normalize({})
        self.assertIs(merged["cross_copy_notify_subscription"], True)
        self.assertIs(merged["cross_copy_notify_manual"], True)

    def test_legacy_true_migrates_to_both(self):
        merged = self._normalize({"cross_copy_notify": True})
        self.assertIs(merged["cross_copy_notify_subscription"], True)
        self.assertIs(merged["cross_copy_notify_manual"], True)
        self.assertNotIn("cross_copy_notify", merged)

    def test_legacy_false_migrates_to_both(self):
        merged = self._normalize({"cross_copy_notify": False})
        self.assertIs(merged["cross_copy_notify_subscription"], False)
        self.assertIs(merged["cross_copy_notify_manual"], False)
        self.assertNotIn("cross_copy_notify", merged)

    def test_explicit_values_win_over_legacy(self):
        """新旧字段同时存在时以新字段为准，旧字段只补缺省的那一个。"""
        merged = self._normalize({
            "cross_copy_notify": False,
            "cross_copy_notify_subscription": True,
        })
        self.assertIs(merged["cross_copy_notify_subscription"], True)
        self.assertIs(merged["cross_copy_notify_manual"], False)

    def test_string_values_coerced(self):
        merged = self._normalize({
            "cross_copy_notify_subscription": "true",
            "cross_copy_notify_manual": "off",
        })
        self.assertIs(merged["cross_copy_notify_subscription"], True)
        self.assertIs(merged["cross_copy_notify_manual"], False)


class TestNotifyChannelReady(unittest.TestCase):
    """notify_channel_ready：只看渠道配置，与场景开关无关。"""

    def test_webhook_configured(self):
        from app.services.notify import notify_channel_ready

        self.assertTrue(notify_channel_ready({
            "notify_channel": "wecom_bot",
            "notify_wecom_webhook": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc",
        }))

    def test_webhook_missing(self):
        from app.services.notify import notify_channel_ready

        self.assertFalse(notify_channel_ready({"notify_channel": "wecom_bot", "notify_wecom_webhook": ""}))

    def test_wecom_app_complete(self):
        from app.services.notify import notify_channel_ready

        self.assertTrue(notify_channel_ready({
            "notify_channel": "wecom_app",
            "notify_wecom_app_corp_id": "ww123",
            "notify_wecom_app_agent_id": "1000002",
            "notify_wecom_app_secret": "secret",
            "notify_wecom_app_touser": "zhangsan",
        }))

    def test_wecom_app_missing_secret(self):
        from app.services.notify import notify_channel_ready

        self.assertFalse(notify_channel_ready({
            "notify_channel": "wecom_app",
            "notify_wecom_app_corp_id": "ww123",
            "notify_wecom_app_agent_id": "1000002",
            "notify_wecom_app_secret": "",
            "notify_wecom_app_touser": "zhangsan",
        }))

    def test_ignores_scene_switches(self):
        """场景开关全关也不影响渠道就绪判断（开关在各自场景里检查）。"""
        from app.services.notify import notify_channel_ready

        self.assertTrue(notify_channel_ready({
            "notify_push_enabled": False,
            "notify_monitor_enabled": False,
            "cross_copy_notify_subscription": False,
            "cross_copy_notify_manual": False,
            "notify_channel": "wecom_bot",
            "notify_wecom_webhook": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc",
        }))


if __name__ == "__main__":
    unittest.main()
