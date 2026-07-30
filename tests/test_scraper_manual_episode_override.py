import unittest
from unittest.mock import patch

from app.services.scraper import build_scraper_rename_plan


class ScraperManualEpisodeOverrideTest(unittest.TestCase):
    def test_manual_episode_override_makes_unrecognized_tv_file_executable(self):
        entry = {
            "id": "unknown-file",
            "name": "广告文本.mkv",
            "is_dir": False,
            "parent_id": "0",
            "parent_path": "孤独的美食家.S08",
            "path": "孤独的美食家.S08/广告文本.mkv",
        }
        payload = {
            "provider": "115",
            "base_cid": "0",
            "entries": [entry],
            "tmdb": {
                "id": 42,
                "media_type": "tv",
                "title": "示例剧",
                "year": "2024",
                "total_episodes": 12,
                "total_seasons": 1,
            },
            "options": {
                "selection_mode": "contents",
                "season": 1,
                "title_language": "zh",
            },
            "episode_overrides": {"unknown-file": 7},
        }

        with (
            patch("app.services.scraper._require_scraper_operation"),
            patch("app.services.scraper._require_provider_cookie", return_value="cookie"),
            patch("app.services.scraper._expand_selected_scraper_entries", return_value=([entry], [])),
            patch("app.services.scraper._walk_existing_folder", return_value=("", False)),
            patch("app.services.scraper._collect_scraper_action_warning", return_value=""),
        ):
            result = build_scraper_rename_plan(payload)

        action = result["actions"][0]
        self.assertTrue(action["ready"])
        self.assertEqual(action["manual_episode"], 7)
        self.assertIn("S08E07", action["new_name"])


if __name__ == "__main__":
    unittest.main()
