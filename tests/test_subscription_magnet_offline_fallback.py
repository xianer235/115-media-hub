"""订阅磁力离线兜底测试。

覆盖三块：
1. ``_subscription_cross_copy_dispatch`` 的返回值（磁力兜底要靠它判断「缺集是否已被补源接手」）。
2. ``_run_subscription_magnet_offline_import`` 的准入条件与「只取第一条候选」。
3. 开关在设置页/前端收集里的接线。
"""

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

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

    async def test_tv_fully_covered_skips(self):
        """已覆盖到目标总集时才不下种。"""
        with patch.object(runner, "_run_subscription_manual_offline_import", new=AsyncMock()) as import_mock:
            result = await runner._run_subscription_magnet_offline_import(
                **self._kwargs(existing_folder_episodes=set(range(1, 13)))
            )
        self.assertIsNone(result)
        import_mock.assert_not_awaited()

    async def test_tv_candidates_all_failed_still_falls_back(self):
        """候选集数比 last_episode 大但全部转存失败时，仍然要下磁力。

        这是兜底最该生效的场景：分享失效了，本盘确实缺集。
        """
        ranked = [{"item": _magnet_item(link_type="115share"), "episode": 12}]
        import_mock = AsyncMock(return_value={"ok": True, "job_id": 1, "imported_episodes": [4]})
        with patch.object(runner, "write_subscription_log", new=AsyncMock()), patch.object(
            runner, "_run_subscription_manual_offline_import", new=import_mock
        ):
            result = await runner._run_subscription_magnet_offline_import(
                **self._kwargs(ranked_candidates=ranked)
            )
        self.assertTrue(result.get("ok"))
        import_mock.assert_awaited_once()

    async def test_movie_with_candidates_skips(self):
        """电影有候选就不兜底，避免把已经在库的那部重复下种。"""
        ranked = [{"item": _magnet_item(link_type="115share"), "episode": 0}]
        with patch.object(runner, "_run_subscription_manual_offline_import", new=AsyncMock()) as import_mock:
            result = await runner._run_subscription_magnet_offline_import(
                **self._kwargs(task=_base_task(media_type="movie"), ranked_candidates=ranked)
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
        self.assertTrue(result["ok"])
        self.assertEqual(result["job_id"], 1)
        self.assertEqual(result["imported_episodes"], [5])
        import_mock.assert_awaited_once()
        self.assertEqual(import_mock.await_args.kwargs["item"]["id"], 7)

    async def test_result_carries_actually_submitted_item(self):
        """排序会改顺序，上层通知要挂真正下种的那条，不能拿盘搜的第一条。"""
        stale = _magnet_item(id=1, title="测试剧 S01E01 1080p")
        useful = _magnet_item(id=2, title="测试剧 S01E05 1080p", link_url="magnet:?xt=urn:btih:cafe")
        import_mock = AsyncMock(return_value={"ok": True, "job_id": 9, "imported_episodes": [5]})
        with patch.object(runner, "write_subscription_log", new=AsyncMock()), patch.object(
            runner, "_run_subscription_manual_offline_import", new=import_mock
        ):
            result = await runner._run_subscription_magnet_offline_import(
                **self._kwargs(
                    offline_candidates=[stale, useful],
                    existing_folder_episodes={1, 2, 3, 4, 6, 7, 8, 9, 10, 11},
                    single_season_episode_upper_bound=12,
                    known_total=12,
                )
            )
        self.assertEqual(import_mock.await_args.kwargs["item"]["id"], 2)
        self.assertEqual(result["selected_item"]["id"], 2)

    async def test_invalid_link_failure_is_recorded(self):
        """离线判无效要落失效链接缓存，否则死种每轮巡检都会重新提交一次。"""
        import_mock = AsyncMock(
            return_value={"ok": False, "last_failed_detail": "invalid magnet: resource not found"}
        )
        record_mock = MagicMock()
        with patch.object(runner, "write_subscription_log", new=AsyncMock()), patch.object(
            runner, "_run_subscription_manual_offline_import", new=import_mock
        ), patch.object(runner, "_record_subscription_invalid_link_cache", new=record_mock):
            result = await runner._run_subscription_magnet_offline_import(**self._kwargs())
        self.assertFalse(result["ok"])
        record_mock.assert_called_once()
        self.assertEqual(record_mock.call_args.args[0], "magnet:?xt=urn:btih:deadbeef")
        self.assertEqual(record_mock.call_args.args[1], "magnet")

    async def test_transient_failure_is_not_recorded(self):
        """超时/网络类失败只是暂时性的，不能当成死种永久跳过。"""
        import_mock = AsyncMock(
            return_value={"ok": False, "last_failed_detail": "115 离线任务超时，请稍后重试"}
        )
        record_mock = MagicMock()
        with patch.object(runner, "write_subscription_log", new=AsyncMock()), patch.object(
            runner, "_run_subscription_manual_offline_import", new=import_mock
        ), patch.object(runner, "_record_subscription_invalid_link_cache", new=record_mock):
            result = await runner._run_subscription_magnet_offline_import(**self._kwargs())
        self.assertFalse(result["ok"])
        record_mock.assert_not_called()


class MagnetExistingEpisodesTest(unittest.IsolatedAsyncioTestCase):
    """无候选路径挑集用的「本盘已有集」不能是空集合（会被当成整季都没有）。"""

    async def test_uses_scanned_episodes(self):
        with patch.object(
            runner,
            "_scan_subscription_existing_episodes_quietly",
            new=AsyncMock(return_value={1, 2, 3, 5}),
        ):
            episodes, last = await runner._resolve_subscription_magnet_existing_episodes(
                _base_task(), {}, 3
            )
        self.assertEqual(episodes, {1, 2, 3, 5})
        self.assertEqual(last, 5)

    async def test_scan_failure_falls_back_to_progress(self):
        with patch.object(
            runner,
            "_scan_subscription_existing_episodes_quietly",
            new=AsyncMock(return_value=None),
        ):
            episodes, last = await runner._resolve_subscription_magnet_existing_episodes(
                _base_task(), {}, 3
            )
        self.assertEqual(episodes, {1, 2, 3})
        self.assertEqual(last, 3)

    async def test_empty_scan_means_target_really_empty(self):
        """目录不存在是可靠信号（不是「没扫成」），照旧整季入库。"""
        with patch.object(
            runner,
            "_scan_subscription_existing_episodes_quietly",
            new=AsyncMock(return_value=set()),
        ):
            episodes, last = await runner._resolve_subscription_magnet_existing_episodes(
                _base_task(), {}, 4
            )
        self.assertEqual(episodes, set())
        self.assertEqual(last, 4)

    async def test_fresh_task_stays_empty(self):
        with patch.object(
            runner,
            "_scan_subscription_existing_episodes_quietly",
            new=AsyncMock(return_value=None),
        ):
            episodes, last = await runner._resolve_subscription_magnet_existing_episodes(
                _base_task(), {}, 0
            )
        self.assertEqual(episodes, set())
        self.assertEqual(last, 0)

    async def test_movie_skips_scan(self):
        scan_mock = AsyncMock(return_value={1, 2})
        with patch.object(runner, "_scan_subscription_existing_episodes_quietly", new=scan_mock):
            episodes, last = await runner._resolve_subscription_magnet_existing_episodes(
                _base_task(media_type="movie"), {}, 0
            )
        self.assertEqual(episodes, set())
        self.assertEqual(last, 0)
        scan_mock.assert_not_awaited()


class MagnetCandidateRankTest(unittest.TestCase):
    """磁力挑包顺序：先看能补上缺的哪几集，不是照着发布时间随便挑。"""

    def _rank(self, candidates, existing, total=12):
        return runner._rank_subscription_magnet_candidates(
            _base_task(), candidates, existing, total, total
        )

    def test_prefers_candidate_covering_missing_episode(self):
        """缺 E05 时，含 E05 的旧包要排在只含 E01 的新包前面。"""
        candidates = [
            {"id": 1, "title": "测试剧 S01E01 1080p"},
            {"id": 2, "title": "测试剧 S01E05 1080p"},
        ]
        ranked = self._rank(candidates, {1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12})
        self.assertEqual([item["id"] for item in ranked], [2, 1])

    def test_prefers_wider_coverage(self):
        """缺 E05+E06 时，覆盖 2 集的合集优于只覆盖 1 集的单集。"""
        candidates = [
            {"id": 1, "title": "测试剧 S01E05 1080p"},
            {"id": 2, "title": "测试剧 S01E01-E06 1080p"},
        ]
        ranked = self._rank(candidates, {1, 2, 3, 4, 7, 8, 9, 10, 11, 12})
        self.assertEqual([item["id"] for item in ranked], [2, 1])

    def test_full_bundle_counts_as_covering_earlier_episodes(self):
        """「全12集」只解析出集号 12，但 1~12 都有，缺 E05 时要认这条。"""
        candidates = [
            {"id": 1, "title": "测试剧 S01E01 1080p"},
            {"id": 2, "title": "测试剧 全12集"},
        ]
        ranked = self._rank(candidates, {1, 2, 3, 4, 6, 7, 8, 9, 10})
        self.assertEqual([item["id"] for item in ranked], [2, 1])

    def test_smaller_bundle_wins_on_equal_coverage(self):
        """同样只补 E05，别为了这一集去下整季。"""
        candidates = [
            {"id": 1, "title": "测试剧 S01E01-E12 1080p"},
            {"id": 2, "title": "测试剧 S01E05 1080p"},
        ]
        ranked = self._rank(candidates, {1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12})
        self.assertEqual([item["id"] for item in ranked], [2, 1])

    def test_unparsable_title_goes_last(self):
        candidates = [
            {"id": 1, "title": "测试剧"},
            {"id": 2, "title": "测试剧 S01E05 1080p"},
        ]
        ranked = self._rank(candidates, {1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12})
        self.assertEqual([item["id"] for item in ranked], [2, 1])

    def test_movie_keeps_original_order(self):
        candidates = [{"id": 1, "title": "测试剧 2025 2160p"}, {"id": 2, "title": "测试剧 2025 1080p"}]
        ranked = runner._rank_subscription_magnet_candidates(
            _base_task(media_type="movie"), candidates, set(), 0, 0
        )
        self.assertEqual([item["id"] for item in ranked], [1, 2])

    def test_quality_tag_is_not_treated_as_full_bundle(self):
        """「全高清」是画质标签，不能因为含「全」「集」就把单集包当整季包。"""
        self.assertFalse(runner._is_subscription_full_bundle_title("测试剧 全高清 第12集 1080p"))
        self.assertFalse(runner._is_subscription_full_bundle_title("测试剧 全国首播 第1集"))
        self.assertTrue(runner._is_subscription_full_bundle_title("测试剧 全12集"))
        self.assertTrue(runner._is_subscription_full_bundle_title("测试剧 全 12 話"))
        self.assertTrue(runner._is_subscription_full_bundle_title("测试剧 全集"))

    def test_full_bundle_tag_does_not_lift_plain_episode(self):
        """缺 E05：带「全高清」的单集包不能靠误判抢到含 E05 的包前面。"""
        candidates = [
            {"id": 1, "title": "测试剧 全高清 第12集"},
            {"id": 2, "title": "测试剧 S01E05 1080p"},
        ]
        ranked = self._rank(candidates, {1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12})
        self.assertEqual([item["id"] for item in ranked], [2, 1])


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
