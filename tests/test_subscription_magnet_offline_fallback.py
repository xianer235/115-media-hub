"""订阅磁力离线兜底测试。

覆盖三块：
1. ``_subscription_cross_copy_dispatch`` 的返回值（磁力兜底要靠它判断「缺集是否已被补源接手」）。
2. ``_run_subscription_magnet_offline_import`` 的准入条件与「只取第一条候选」。
3. 开关在设置页/前端收集里的接线。
"""

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

from app import core
from app.services import subscription_task_runner as runner


class _FakeProvider:
    name = "115"
    label = "115网盘"
    supports_offline = True

    def get_cookie(self, cfg):
        return "cookie-115"

    def ensure_folder_id_by_path(self, cookie, path):
        return "cid-1"


def _base_task(**overrides):
    task = {
        "name": "测试剧",
        "title": "测试剧",
        "media_type": "tv",
        "provider": "115",
        "savepath": "剧集",
        "season": 1,
        "cross_copy_mode": "fallback",
        "cross_copy_sources": ["quark"],
    }
    task.update(overrides)
    return task


def _magnet_item(**overrides):
    item = {
        "id": 7,
        "title": "测试剧 S01E05 1080p",
        "link_type": "magnet",
        "link_url": "magnet:?xt=urn:btih:deadbeef",
    }
    item.update(overrides)
    return item


class CrossCopyDispatchReturnTest(unittest.IsolatedAsyncioTestCase):
    async def test_off_mode_returns_false(self):
        result = await runner._subscription_cross_copy_dispatch(
            _base_task(cross_copy_mode="off"), {}, [], 0, "auto", 0
        )
        self.assertFalse(result)

    async def test_no_usable_source_returns_false(self):
        with patch.object(runner, "write_subscription_log", new=AsyncMock()):
            result = await runner._subscription_cross_copy_dispatch(
                _base_task(cross_copy_sources=[]), {}, [], 0, "auto", 0
            )
        self.assertFalse(result)

    async def test_not_missing_returns_false(self):
        ranked = [{"item": _magnet_item(link_type="115share", link_url="https://115.com/s/abc"), "episode": 9}]
        with patch.object(runner, "write_subscription_log", new=AsyncMock()):
            result = await runner._subscription_cross_copy_dispatch(
                _base_task(), {}, ranked, 3, "auto", 12
            )
        self.assertFalse(result)

    async def test_no_cross_candidates_returns_false(self):
        with patch.object(runner, "write_subscription_log", new=AsyncMock()), patch.object(
            runner, "find_subscription_cross_copy_candidates", new=AsyncMock(return_value={"candidates": []})
        ):
            result = await runner._subscription_cross_copy_dispatch(
                _base_task(), {}, [], 3, "auto", 12
            )
        self.assertFalse(result)

    async def test_registered_jobs_return_true(self):
        with patch.object(runner, "write_subscription_log", new=AsyncMock()), patch.object(
            runner,
            "find_subscription_cross_copy_candidates",
            new=AsyncMock(return_value={"candidates": [{"item": _magnet_item()}]}),
        ), patch.object(
            runner,
            "register_cross_copy_from_candidates",
            return_value={"registered": [11], "skipped": [], "logs": []},
        ), patch.object(runner, "cleanup_staging_empty_folders", return_value=0):
            result = await runner._subscription_cross_copy_dispatch(
                _base_task(), {}, [], 3, "auto", 12
            )
        self.assertTrue(result)


class MagnetOfflineGateTest(unittest.IsolatedAsyncioTestCase):
    def _kwargs(self, **overrides):
        kwargs = {
            "task": _base_task(),
            "task_name": "测试剧",
            "cfg": {"subscription_magnet_offline_fallback": True},
            "provider": "115",
            "provider_meta": _FakeProvider(),
            "cookie_115": "cookie-115",
            "offline_candidates": [_magnet_item()],
            "ranked_candidates": [],
            "last_episode": 3,
            "known_total": 12,
            "single_season_episode_upper_bound": 12,
            "existing_folder_episodes": {1, 2, 3},
            "existing_episode_scan_ready": True,
            "folder_id": "cid-1",
            "effective_savepath": "剧集/测试剧 (2025)/Season 01",
            "base_savepath": "剧集",
            "monitor_task_name": "",
            "subscription_run_id": "run-1",
            "batch_refresh_enabled": False,
            "cross_copy_registered": False,
            "import_timeout_seconds": 90,
        }
        kwargs.update(overrides)
        return kwargs

    async def test_switch_off_skips(self):
        with patch.object(runner, "_run_subscription_manual_offline_import", new=AsyncMock()) as import_mock:
            result = await runner._run_subscription_magnet_offline_import(
                **self._kwargs(cfg={"subscription_magnet_offline_fallback": False})
            )
        self.assertIsNone(result)
        import_mock.assert_not_awaited()

    async def test_non_115_target_skips(self):
        with patch.object(runner, "_run_subscription_manual_offline_import", new=AsyncMock()) as import_mock:
            result = await runner._run_subscription_magnet_offline_import(
                **self._kwargs(task=_base_task(provider="quark"), provider="quark")
            )
        self.assertIsNone(result)
        import_mock.assert_not_awaited()

    async def test_cross_copy_already_registered_skips(self):
        with patch.object(runner, "_run_subscription_manual_offline_import", new=AsyncMock()) as import_mock:
            result = await runner._run_subscription_magnet_offline_import(
                **self._kwargs(cross_copy_registered=True)
            )
        self.assertIsNone(result)
        import_mock.assert_not_awaited()

    async def test_no_offline_candidates_skips(self):
        with patch.object(runner, "_run_subscription_manual_offline_import", new=AsyncMock()) as import_mock:
            result = await runner._run_subscription_magnet_offline_import(
                **self._kwargs(offline_candidates=[])
            )
        self.assertIsNone(result)
        import_mock.assert_not_awaited()

    async def test_not_missing_skips(self):
        ranked = [{"item": _magnet_item(link_type="115share"), "episode": 9}]
        with patch.object(runner, "_run_subscription_manual_offline_import", new=AsyncMock()) as import_mock:
            result = await runner._run_subscription_magnet_offline_import(
                **self._kwargs(ranked_candidates=ranked)
            )
        self.assertIsNone(result)
        import_mock.assert_not_awaited()

    async def test_only_first_candidate_is_submitted(self):
        first = _magnet_item(id=7)
        second = _magnet_item(id=8, link_url="magnet:?xt=urn:btih:cafe")
        import_mock = AsyncMock(return_value={"ok": True, "job_id": 1, "imported_episodes": [5]})
        with patch.object(runner, "write_subscription_log", new=AsyncMock()), patch.object(
            runner, "_run_subscription_manual_offline_import", new=import_mock
        ):
            result = await runner._run_subscription_magnet_offline_import(
                **self._kwargs(offline_candidates=[first, second])
            )
        self.assertEqual(result, {"ok": True, "job_id": 1, "imported_episodes": [5]})
        import_mock.assert_awaited_once()
        self.assertEqual(import_mock.await_args.kwargs["item"]["id"], 7)


class MagnetOfflineSettingWiringTest(unittest.TestCase):
    def _read(self, *parts):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, *parts), encoding="utf-8") as fh:
            return fh.read()

    def test_config_default_is_false(self):
        cfg = core.normalize_config({})
        self.assertIn("subscription_magnet_offline_fallback", cfg)
        self.assertFalse(cfg["subscription_magnet_offline_fallback"])

    def test_settings_page_has_checkbox(self):
        html = self._read("templates", "partials", "pages", "settings.html")
        self.assertIn('id="subscription_magnet_offline_fallback"', html)

    def test_settings_payload_collects_checkbox(self):
        js = self._read("static", "js", "modules", "tabs", "settings.js")
        self.assertIn("subscription_magnet_offline_fallback", js)


if __name__ == "__main__":
    unittest.main()
