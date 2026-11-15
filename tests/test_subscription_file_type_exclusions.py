import unittest

from app import core
from app.services import subscription_episode
from app.services.subscription_share_selection import _build_tv_share_selection_from_manifest


class SubscriptionFileTypeExclusionTest(unittest.TestCase):
    def test_normalize_file_extensions_accepts_common_input(self):
        self.assertEqual(
            core.normalize_subscription_exclude_file_extensions(".EXE， zip\nRAR, .7z"),
            ["exe", "zip", "rar", "7z"],
        )

    def test_task_default_file_extensions_can_be_removed(self):
        defaulted = core.normalize_subscription_task(
            {
                "name": "默认过滤",
                "title": "默认过滤",
                "savepath": "Library",
            }
        )
        self.assertEqual(defaulted["exclude_file_extensions"], ["zip", "rar"])

        removed = core.normalize_subscription_task(
            {
                "name": "删除默认过滤",
                "title": "删除默认过滤",
                "savepath": "Library",
                "exclude_file_extensions": [],
            }
        )
        self.assertEqual(removed["exclude_file_extensions"], [])

    def test_manifest_selection_excludes_configured_file_types_only(self):
        task = core.normalize_subscription_task(
            {
                "name": "类型过滤",
                "title": "类型过滤",
                "media_type": "tv",
                "savepath": "Library",
                "exclude_file_extensions": ["exe", "zip"],
            }
        )
        manifest = {
            "files": [
                {"id": "zip-file", "name": "类型过滤.S01E01.zip", "episodes": [1], "size": 100},
                {"id": "exe-file", "name": "类型过滤.S01E02.exe", "episodes": [2], "size": 100},
                {"id": "video-file", "name": "类型过滤.S01E03.mkv", "episodes": [3], "size": 100},
            ],
        }

        selection, stats = _build_tv_share_selection_from_manifest(manifest, {1, 2, 3}, task)

        self.assertEqual(selection["selected_ids"], ["video-file"])
        self.assertEqual(stats["covered_episodes"], [3])
        self.assertEqual(stats["skipped_excluded_file_types"], 2)

    def test_empty_file_extension_list_does_not_bypass_video_allowlist(self):
        # 清空「按后缀跳过」清单后，非视频文件依然不收：影视订阅只入库视频。
        task = core.normalize_subscription_task(
            {
                "name": "不过滤",
                "title": "不过滤",
                "media_type": "tv",
                "savepath": "Library",
                "exclude_file_extensions": [],
            }
        )
        manifest = {
            "files": [
                {"id": "zip-file", "name": "不过滤.S01E01.zip", "episodes": [1], "size": 100},
                {"id": "rar-file", "name": "不过滤.S01E02.rar", "episodes": [2], "size": 100},
            ],
        }

        selection, stats = _build_tv_share_selection_from_manifest(manifest, {1, 2}, task)

        self.assertEqual(selection.get("selected_ids", []), [])
        self.assertEqual(stats["covered_episodes"], [])
        self.assertEqual(stats["skipped_excluded_file_types"], 2)

    def test_tv_episode_selection_only_uses_video_files(self):
        task = core.normalize_subscription_task(
            {
                "name": "图片误判防护",
                "title": "图片误判防护",
                "media_type": "tv",
                "savepath": "Library",
            }
        )
        manifest = {
            "files": [
                {"id": "poster", "name": "poster.S01E01.jpg", "episodes": [1], "size": 100},
                {"id": "background", "name": "background.S01E02.png", "episodes": [2], "size": 100},
                {"id": "nfo", "name": "episode.S01E03.nfo", "episodes": [3], "size": 100},
                {"id": "video", "name": "episode.S01E01.mkv", "episodes": [1], "size": 100},
                {"id": "video-m4v", "name": "episode.S01E02.m4v", "episodes": [2], "size": 100},
            ],
        }

        selection, stats = _build_tv_share_selection_from_manifest(manifest, {1, 2, 3}, task)

        self.assertEqual(selection["selected_ids"], ["video", "video-m4v"])
        self.assertEqual(stats["covered_episodes"], [1, 2])
        self.assertEqual(stats["skipped_excluded_file_types"], 3)

    def test_external_subtitles_are_not_treated_as_non_media(self):
        # 外挂字幕要跟着视频入库（改名计划会带走 .srt/.ass），不能按「只收视频」排掉。
        task = core.normalize_subscription_task(
            {
                "name": "字幕跟随",
                "title": "字幕跟随",
                "media_type": "tv",
                "savepath": "Library",
                "exclude_file_extensions": [],
            }
        )

        for name in ("Show.S01E01.mkv", "Show.S01E01.zh.ass", "Show.S01E01.en.srt"):
            with self.subTest(name=name):
                self.assertFalse(subscription_episode._is_subscription_excluded_file_type(task, name))

        for name in ("poster.S01E01.jpg", "episode.S01E01.nfo", "Show.S01E01.zip"):
            with self.subTest(name=name):
                self.assertTrue(subscription_episode._is_subscription_excluded_file_type(task, name))


if __name__ == "__main__":
    unittest.main()
