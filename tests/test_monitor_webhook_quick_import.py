"""接收夹快捷导入的独立 webhook：把磁力直接投进接收夹，不影响原有按任务推送。"""

import json
import os
import tempfile
import unittest
from unittest import mock

from app import db
from app import resource_jobs
from app.routes import monitor as monitor_routes


MAGNET = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567&dn=Demo"


class FakeHeaders(dict):
    """大小写不敏感的 headers（Starlette Headers 的行为）。"""

    def __init__(self, raw=None):
        super().__init__({str(key).lower(): value for key, value in (raw or {}).items()})

    def get(self, key, default=None):
        return super().get(str(key).lower(), default)


class FakeWebhookRequest:
    def __init__(self, payload, headers=None):
        self._body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.headers = FakeHeaders(headers)

    async def body(self):
        return self._body


def _magnet_payload(savepath="接收", **extra):
    payload = {"title": "示例磁力", "magnet": MAGNET, "savepath": savepath}
    payload.update(extra)
    return payload


def _scan_task(name="电视剧", scan_path="/115/电视剧", **extra):
    task = {
        "name": name,
        "task_type": "scan",
        "enabled": True,
        "scan_path": scan_path,
        "target_path": name,
        "auto_scrape_options": {},
        "webhook_enabled": True,
        "delay_seconds": 0,
    }
    task.update(extra)
    return task


def _inbox_task(name="接收", path="/115/接收", enabled=True, targets=None, **extra):
    task = {
        "name": name,
        "task_type": "inbox",
        "enabled": enabled,
        "scan_path": path,
        "distribute_targets": dict(targets) if isinstance(targets, dict) else {"movie": "电影", "tv": "电视剧"},
        "webhook_enabled": True,
    }
    task.update(extra)
    return task


def _cfg(tasks=None, inbox=None, **overrides):
    scan_tasks = list(tasks) if tasks is not None else [
        _scan_task("电影", "/115/电影"),
        _scan_task("电视剧", "/115/电视剧"),
    ]
    inbox_task = _inbox_task() if inbox is None else inbox
    monitor_tasks = list(scan_tasks)
    if isinstance(inbox_task, dict):
        monitor_tasks.append(dict(inbox_task))
    cfg = {
        "mount_points": [{"provider": "115", "prefix": "/115"}],
        "cookie_115": "cookie",
        "webhook_secret": "",
        "monitor_tasks": monitor_tasks,
    }
    cfg.update(overrides)
    return cfg


class QuickImportWebhookTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        self.original_db_ensured = db._DB_ENSURED
        db.DB_PATH = os.path.join(self.tmpdir.name, "data.db")
        db._DB_ENSURED = False
        db.ensure_db()
        self.logged = []
        # 任务创建会 touch 前端状态推送信号，测试里静音（与 test_resource_job_management 一致）。
        self.patchers = [
            mock.patch.object(resource_jobs, "invalidate_resource_state_snapshot"),
            mock.patch.object(resource_jobs, "touch_resource_jobs_state_signal"),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        for patcher in self.patchers:
            patcher.stop()
        db.DB_PATH = self.original_db_path
        db._DB_ENSURED = self.original_db_ensured
        self.tmpdir.cleanup()

    async def _call(self, payload, *, cfg=None, headers=None, task_name="接收"):
        async def fake_log(message, level="info", *args, **kwargs):
            self.logged.append(str(message))

        with mock.patch.object(monitor_routes, "get_config", return_value=cfg or _cfg()), \
                mock.patch.object(monitor_routes, "write_monitor_log", side_effect=fake_log), \
                mock.patch.object(monitor_routes, "submit_background") as submit:
            response = await monitor_routes.webhook(task_name, FakeWebhookRequest(payload, headers))
        return response, submit

    def _json(self, response):
        return json.loads(response.body.decode("utf-8"))

    async def test_rejects_when_quick_import_disabled(self):
        response, submit = await self._call(_magnet_payload(), cfg=_cfg(inbox=_inbox_task(enabled=False)))

        self.assertEqual(response.status_code, 400)
        self.assertIn("接收夹", self._json(response)["msg"])
        submit.assert_not_called()

    async def test_rejects_when_no_target_task(self):
        cfg = _cfg(tasks=[_scan_task("电影", "/115/电影")], inbox=_inbox_task(targets={}))
        response, submit = await self._call(_magnet_payload(), cfg=cfg)

        self.assertEqual(response.status_code, 400)
        self.assertIn("分发目标", self._json(response)["msg"])
        submit.assert_not_called()

    async def test_rejects_savepath_outside_inbox(self):
        response, submit = await self._call(_magnet_payload(savepath="电视剧"))

        self.assertEqual(response.status_code, 400)
        message = self._json(response)["msg"]
        self.assertIn("接收夹", message)
        self.assertIn("留空则默认落到接收夹", message)
        submit.assert_not_called()

    async def test_rejects_non_magnet_payload(self):
        response, submit = await self._call({"title": "分享", "savepath": "接收", "link_url": "https://115.com/s/abc"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("磁力", self._json(response)["msg"])
        submit.assert_not_called()

    async def test_requires_signature_when_secret_configured(self):
        response, submit = await self._call(_magnet_payload(), cfg=_cfg(webhook_secret="s3cret"))

        self.assertEqual(response.status_code, 401)
        self.assertIn("签名", self._json(response)["msg"])
        submit.assert_not_called()

    async def test_accepts_token_header(self):
        response, submit = await self._call(
            _magnet_payload(),
            cfg=_cfg(webhook_secret="s3cret"),
            headers={"X-Webhook-Token": "s3cret"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(self._json(response)["ok"])

    async def test_creates_job_into_inbox_with_quick_import_flag(self):
        response, submit = await self._call(_magnet_payload(savepath="接收"))
        body = self._json(response)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["savepath"], "接收")
        self.assertEqual(body["auto_refresh"], True)
        job = resource_jobs.get_resource_job(body["job_id"])
        self.assertEqual(job["savepath"], "接收")
        self.assertEqual(job["monitor_task_name"], "")
        self.assertTrue(job["auto_refresh"])
        extra = job.get("extra") or {}
        self.assertEqual(extra.get("quick_import_inbox"), 1)
        self.assertEqual(extra.get("webhook_target"), "inbox")
        self.assertEqual(extra.get("webhook_task_name"), "接收")
        self.assertEqual(extra.get("job_source"), monitor_routes.USERSCRIPT_WEBHOOK_SOURCE)
        submit.assert_called_once()
        self.assertTrue(any("接收" in line for line in self.logged))

    async def test_mount_prefixed_savepath_is_normalized(self):
        """脚本照抄面板的 /115/接收 也能对上接收夹（统一按根目录相对路径解析）。"""
        response, _submit = await self._call(_magnet_payload(savepath="115/接收"))
        body = self._json(response)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["savepath"], "接收")

    async def test_scan_task_rejects_savepath_outside_its_dir(self):
        """扫描任务的 savepath 必须落在任务目录内，避免静默下到别的目录。"""
        response, submit = await self._call(
            _magnet_payload(savepath="电影"),
            task_name="电视剧",
        )

        self.assertEqual(response.status_code, 400)
        message = self._json(response)["msg"]
        self.assertIn("电视剧", message)
        self.assertIn("磁力必须指定保存路径", message)
        submit.assert_not_called()

    async def test_scan_task_share_refresh_hint_when_savepath_outside(self):
        """非磁力（分享转存刷新）越界时提示可以留空 savepath。"""
        response, submit = await self._call(
            {"title": "分享", "link_url": "https://115.com/s/abc", "savepath": "电影"},
            task_name="电视剧",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("可以不传 savepath", self._json(response)["msg"])
        submit.assert_not_called()

    async def test_scan_task_normalizes_prefixed_savepath(self):
        response, _submit = await self._call(
            _magnet_payload(savepath="115/电视剧/新片"),
            task_name="电视剧",
        )
        body = self._json(response)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["savepath"], "电视剧/新片")

    async def test_empty_savepath_falls_back_to_configured_inbox(self):
        response, _submit = await self._call(_magnet_payload(savepath=""))
        body = self._json(response)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["savepath"], "接收")

    async def test_duplicate_magnet_into_inbox_returns_conflict(self):
        first, _submit = await self._call(_magnet_payload())
        second, submit = await self._call(_magnet_payload())

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)
        self.assertFalse(self._json(second)["ok"])
        submit.assert_not_called()

    async def test_task_webhook_still_creates_task_scoped_job(self):
        """扫描任务 webhook 行为不变（仍按监控任务绑定 + 任务级延时）。"""
        async def fake_log(message, level="info", *args, **kwargs):
            self.logged.append(str(message))

        cfg = _cfg(tasks=[_scan_task("电视剧", "/115/电视剧", delay_seconds=7)])
        with mock.patch.object(monitor_routes, "get_config", return_value=cfg), \
                mock.patch.object(monitor_routes, "write_monitor_log", side_effect=fake_log), \
                mock.patch.object(monitor_routes, "submit_background") as submit:
            response = await monitor_routes.webhook(
                "电视剧",
                FakeWebhookRequest(_magnet_payload(savepath="电视剧")),
            )
        body = self._json(response)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["task_name"], "电视剧")
        job = resource_jobs.get_resource_job(body["job_id"])
        self.assertEqual(job["monitor_task_name"], "电视剧")
        self.assertEqual(int(job["refresh_delay_seconds"]), 7)
        extra = job.get("extra") or {}
        self.assertEqual(extra.get("webhook_task_name"), "电视剧")
        self.assertIsNone(extra.get("quick_import_inbox"))
        submit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
