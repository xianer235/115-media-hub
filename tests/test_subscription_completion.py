"""订阅「完结」口径与媒体文件夹命名。

背景（2026-11-25 用户实测）：
1. 剧集一共 14 集、资源只更新到 13 集时，任务被标成「已完结」并停止自动查询。
   根因是「已到集数 >= 总集数」被当成完结，而总集数还会被资源包探测值（13）压低。
2. 按默认保存位置建的订阅任务不自建媒体文件夹（剧集甚至直接落 ``Season 01``），
   新建时也没带 TMDB 标记。
"""

import unittest
from unittest import mock

from app import core
from app import startup


TMDB_BINDING = {
    "tmdb_id": 1234,
    "tmdb_status": "Returning Series",
    "tmdb_total_episodes": 14,
    "tmdb_total_seasons": 1,
    "tmdb_season_episode_map": {"1": 14},
}


def build_tv_task(**overrides):
    task = {
        "name": "某剧 (2024)",
        "title": "某剧",
        "year": "2024",
        "media_type": "tv",
        "provider": "115",
        "season": 1,
        "savepath": "电视剧",
        "media_folder_layout": "folder",
        **TMDB_BINDING,
    }
    task.update(overrides)
    return task


class TvTotalEpisodesTest(unittest.TestCase):
    def test_tmdb_season_total_wins_over_smaller_resource_total(self):
        # 资源包写着「13 集」被同步成任务总集数，但 TMDB 记录 14 集 —— 不能压回 13
        task = build_tv_task(total_episodes=13)
        self.assertEqual(core.resolve_subscription_tv_total_episodes(task, state_total=13), 14)

    def test_larger_recorded_total_is_kept(self):
        # TMDB 落后（记 14）但库里已经到 15：上限取大的，不要压回去
        task = build_tv_task(total_episodes=15)
        self.assertEqual(core.resolve_subscription_tv_total_episodes(task, state_total=15), 15)

    def test_whole_show_total_is_not_used_for_single_season(self):
        # 历史脏值：全剧 24 集被写进单季任务，季映射是 12 集 → 仍按 12 集算
        task = build_tv_task(tmdb_total_episodes=24, tmdb_total_seasons=2,
                             tmdb_season_episode_map={"1": 12}, total_episodes=24)
        self.assertEqual(core.resolve_subscription_tv_total_episodes(task, state_total=24), 12)

    def test_without_tmdb_binding_falls_back_to_configured_total(self):
        task = {
            "title": "某剧",
            "media_type": "tv",
            "season": 1,
            "total_episodes": 13,
            "savepath": "电视剧",
        }
        self.assertEqual(core.resolve_subscription_tv_total_episodes(task), 13)


class FinishedStatusTest(unittest.TestCase):
    def test_only_tmdb_status_counts_as_finished(self):
        self.assertFalse(core.is_subscription_task_finished(build_tv_task()))
        self.assertTrue(core.is_subscription_task_finished(build_tv_task(tmdb_status="Ended")))
        self.assertTrue(core.is_subscription_task_finished(build_tv_task(tmdb_status="Canceled")))

    def test_scheduler_keeps_polling_when_episodes_are_missing(self):
        task = build_tv_task(tmdb_status="Ended")
        with mock.patch.object(
            startup,
            "load_subscription_task_state",
            return_value={"last_episode": 13, "total_episodes": 14},
        ):
            self.assertFalse(startup._subscription_finished_should_stop(task, "某剧 (2024)"))

    def test_scheduler_stops_when_progress_reached_total(self):
        task = build_tv_task(tmdb_status="Ended")
        with mock.patch.object(
            startup,
            "load_subscription_task_state",
            return_value={"last_episode": 14, "total_episodes": 14},
        ):
            self.assertTrue(startup._subscription_finished_should_stop(task, "某剧 (2024)"))

    def test_scheduler_stops_for_new_task_without_progress(self):
        task = build_tv_task(tmdb_status="Ended")
        with mock.patch.object(
            startup,
            "load_subscription_task_state",
            return_value={"last_episode": 0, "total_episodes": 0},
        ):
            self.assertTrue(startup._subscription_finished_should_stop(task, "某剧 (2024)"))


class MediaFolderNameTest(unittest.TestCase):
    def test_movie_folder_uses_bracketed_year_and_tmdb_id(self):
        task = {"title": "让子弹飞", "year": "2010", "media_type": "movie", "tmdb_id": 27578, "media_folder_layout": "folder"}
        self.assertEqual(
            core.build_subscription_movie_savepath(task, "电影"),
            "电影/让子弹飞 (2010) [tmdbid-27578]",
        )

    def test_tv_folder_uses_bracketed_year_and_tmdb_id(self):
        task = build_tv_task()
        self.assertEqual(
            core.build_subscription_tv_savepath(task, "电视剧", season=1),
            "电视剧/某剧 (2024) [tmdbid-1234]/Season 01",
        )

    def test_existing_show_folder_is_reused_without_nesting(self):
        for savepath in ("电视剧/某剧", "电视剧/某剧 2024", "电视剧/某剧 (2024)", "电视剧/某剧 (2024) [tmdbid-1234]"):
            with self.subTest(savepath=savepath):
                task = build_tv_task(savepath=savepath)
                resolved = core.build_subscription_tv_savepath(task, savepath, season=1)
                self.assertEqual(resolved.count("某剧"), 1)
                self.assertTrue(resolved.endswith("/Season 01"))

    def test_numeric_movie_title_is_not_mistaken_for_a_year(self):
        # 片名本身就是年份数字（1917）：目录名「1917 (2019)」要能认出来，不再套一层
        task = {"title": "1917", "year": "2019", "media_type": "movie", "tmdb_id": 530915, "media_folder_layout": "folder"}
        self.assertEqual(
            core.build_subscription_movie_savepath(task, "电影/1917 (2019)"),
            "电影/1917 (2019)",
        )

    def test_season_folder_savepath_is_treated_as_show_folder(self):
        task = build_tv_task()
        self.assertEqual(
            core.build_subscription_tv_savepath(task, "电视剧/某剧 (2024)/Season 01", season=1),
            "电视剧/某剧 (2024)/Season 01",
        )

    def test_scan_savepath_points_at_show_folder(self):
        task = build_tv_task()
        self.assertEqual(
            core.resolve_subscription_tv_scan_savepath(task, "电视剧"),
            "电视剧/某剧 (2024) [tmdbid-1234]",
        )


class LegacyLayoutTest(unittest.TestCase):
    """老任务（没有 media_folder_layout 字段）必须保持原有目录结构不变。"""

    def test_legacy_movie_keeps_space_separated_year(self):
        task = {"title": "让子弹飞", "year": "2010", "media_type": "movie", "tmdb_id": 27578}
        self.assertEqual(
            core.build_subscription_movie_savepath(task, "电影"),
            "电影/让子弹飞 2010",
        )

    def test_legacy_tv_builds_season_directly_under_savepath(self):
        task = build_tv_task(media_folder_layout="")
        self.assertEqual(
            core.build_subscription_tv_savepath(task, "电视剧", season=1),
            "电视剧/Season 01",
        )

    def test_legacy_scan_savepath_is_savepath_itself(self):
        task = build_tv_task(media_folder_layout="")
        self.assertEqual(core.resolve_subscription_tv_scan_savepath(task, "电视剧"), "电视剧")

    def test_legacy_scan_savepath_strips_season_for_multi_season(self):
        task = build_tv_task(media_folder_layout="", multi_season_mode=True, anime_mode=True)
        self.assertEqual(
            core.resolve_subscription_tv_scan_savepath(task, "电视剧/某剧/Season 02"),
            "电视剧/某剧",
        )

    def test_layout_field_roundtrips_through_normalize(self):
        self.assertEqual(
            core.normalize_subscription_task({"title": "某剧", "savepath": "电视剧", "media_folder_layout": "folder"})[
                "media_folder_layout"
            ],
            "folder",
        )
        # 老任务缺字段 → 空字符串（旧布局）
        self.assertEqual(
            core.normalize_subscription_task({"title": "某剧", "savepath": "电视剧"})["media_folder_layout"],
            "",
        )
        # 未知值不当作新布局，避免手改配置把老任务升级
        self.assertEqual(
            core.normalize_subscription_task({"title": "某剧", "savepath": "电视剧", "media_folder_layout": "???"})[
                "media_folder_layout"
            ],
            "",
        )


if __name__ == "__main__":
    unittest.main()
