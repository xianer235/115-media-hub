import unittest

from app import core
from app.subscription_scoring import (
    evaluate_subscription_candidate_title_match,
    filter_subscription_manifest_files_by_strict_identity,
    is_subscription_strict_title_match,
)
from app.services.subscription_share_selection import _build_tv_share_selection_from_manifest


class SubscriptionStrictTitleMatchingTest(unittest.TestCase):
    def test_new_subscription_keeps_strict_title_identity_off_by_default(self):
        # 默认关：严格模式对片名写法过于挑剔，漏掉资源的概率高于误入库。
        task = core.normalize_subscription_task(
            {
                "name": "遮天",
                "title": "遮天",
                "media_type": "tv",
                "savepath": "Library/遮天",
            }
        )

        self.assertFalse(task["strict_title_match"])
        self.assertFalse(is_subscription_strict_title_match(task))

    def test_synopsis_mention_does_not_match_an_unrelated_series(self):
        task = {
            "name": "遮天",
            "title": "遮天",
            "media_type": "tv",
            "tmdb_id": 111,
            "strict_title_match": True,
        }
        item = {
            "title": "锁簪 (2026) - S01E01-E24(完结)",
            "raw_text": "锁簪讲述山庄秘事，并逐步揭开背后的遮天阴谋。",
        }

        result = evaluate_subscription_candidate_title_match(task, item)

        self.assertFalse(result["matched"])
        self.assertEqual(result["match_reason"], "raw_text_only_match")

    def test_exact_episode_title_still_matches(self):
        task = {
            "name": "遮天",
            "title": "遮天",
            "media_type": "tv",
            "tmdb_id": 111,
            "strict_title_match": True,
        }
        item = {"title": "名称：遮天（第68集）", "raw_text": "遮天第68集更新。"}

        result = evaluate_subscription_candidate_title_match(task, item)

        self.assertTrue(result["matched"])
        self.assertEqual(result["match_reason"], "identity_title_match")

    def test_description_mention_does_not_match_an_unrelated_series(self):
        task = {
            "name": "完美世界",
            "title": "完美世界",
            "media_type": "tv",
            "tmdb_id": 124003,
            "strict_title_match": True,
        }
        item = {
            "title": "名称：人生复本 1-2季(2026)【更05集】",
            "raw_text": "描述：在第二季中，Leighton执着地追逐着创造完美世界的宏伟愿景。",
        }

        result = evaluate_subscription_candidate_title_match(task, item)

        self.assertFalse(result["matched"])
        self.assertEqual(result["match_reason"], "raw_text_only_match")

    def test_channel_prefix_and_quality_tags_do_not_hide_the_title(self):
        task = {
            "name": "诛仙",
            "title": "诛仙",
            "media_type": "tv",
            "tmdb_id": 206484,
            "strict_title_match": True,
        }
        items = [
            {"title": "🐾 动漫｜诛仙 (2022) S03E17 4K"},
            {"title": "资源名称：诛仙 4K 完结"},
        ]

        for item in items:
            with self.subTest(title=item["title"]):
                result = evaluate_subscription_candidate_title_match(task, item)
                self.assertTrue(result["matched"])
                self.assertEqual(result["match_reason"], "identity_title_match")

    def test_explicit_legacy_opt_out_remains_supported(self):
        self.assertFalse(is_subscription_strict_title_match({"strict_title_match": False}))

    def test_matching_share_title_does_not_allow_another_series_file(self):
        task = {"title": "小城良方", "media_type": "tv", "tmdb_id": 285625, "strict_title_match": True}
        manifest = {
            "share_root_title": "小城良方",
            "files": [
                {
                    "id": "wrong-show",
                    "name": "完美世界.S01E14.mkv",
                    "episodes": [14],
                    "size": 1500000000,
                }
            ],
            "covered_episodes": [14],
        }

        filtered = filter_subscription_manifest_files_by_strict_identity(task, manifest)

        self.assertEqual(len(filtered["manifest"]["files"]), 0)
        self.assertEqual(filtered["skipped_files"], 1)
        self.assertEqual(filtered["reason"], "strict_file_title_mismatch")

        selection, _stats = _build_tv_share_selection_from_manifest(manifest, {14}, task)
        self.assertEqual(selection.get("selected_ids", []), [])

    def test_file_title_guard_works_without_task_tmdb_id(self):
        task = {"title": "小城良方", "media_type": "tv", "strict_title_match": True}
        manifest = {
            "share_root_title": "小城良方",
            "files": [
                {"id": "ok", "name": "小城良方.S01E14.mkv", "episodes": [14], "size": 100},
                {"id": "wrong", "name": "完美世界.S01E14.mkv", "episodes": [14], "size": 100},
            ],
            "covered_episodes": [14],
        }

        filtered = filter_subscription_manifest_files_by_strict_identity(task, manifest)

        self.assertEqual([entry["id"] for entry in filtered["manifest"]["files"]], ["ok"])

    def test_live_style_episode_filename_and_generic_episode_are_preserved(self):
        task = {"title": "小城良方", "media_type": "tv", "tmdb_id": 285625, "strict_title_match": True}
        manifest = {
            "share_root_title": "小城良方",
            "files": [
                {"id": "live", "name": "小城良方 第14集.mkv", "episodes": [14], "size": 100},
                {"id": "generic", "name": "S01E15.mkv", "episodes": [15], "size": 100},
            ],
            "covered_episodes": [14, 15],
        }

        filtered = filter_subscription_manifest_files_by_strict_identity(task, manifest)

        self.assertEqual([entry["id"] for entry in filtered["manifest"]["files"]], ["live", "generic"])


if __name__ == "__main__":
    unittest.main()
