import unittest
from unittest.mock import patch

from app.services.scraper import build_scraper_rename_plan, _resolve_scraper_auto_episode_info


class ScraperTvEpisodeSeasonTest(unittest.TestCase):
    def _run_plan(self, entry, options, tmdb, episode_overrides=None):
        payload = {
            "provider": "115",
            "base_cid": "0",
            "entries": [entry],
            "tmdb": tmdb,
            "options": {
                "selection_mode": "contents",
                "season": options.get("season", 1),
                "title_language": "zh",
                "preserve_file_info": False,
                "preserve_tags": {},
            },
        }
        if episode_overrides:
            payload["episode_overrides"] = episode_overrides
        with (
            patch("app.services.scraper._require_scraper_operation"),
            patch("app.services.scraper._require_provider_cookie", return_value="cookie"),
            patch("app.services.scraper._expand_selected_scraper_entries", return_value=([entry], [])),
            patch("app.services.scraper._walk_existing_folder", return_value=("", False)),
            patch("app.services.scraper._collect_scraper_action_warning", return_value=""),
        ):
            return build_scraper_rename_plan(payload)

    def _tmdb_binding(self, **overrides):
        payload = {
            "id": 94997,
            "media_type": "tv",
            "tmdb_media_type": "tv",
            "title": "龙之家族",
            "tmdb_title": "龙之家族",
            "tmdb_localized_title": "龙之家族",
            "tmdb_original_title": "House of the Dragon",
            "tmdb_english_title": "House of the Dragon",
            "year": "2022",
            "tmdb_year": "2022",
            "total_episodes": 8,
            "tmdb_total_episodes": 8,
            "total_seasons": 3,
            "tmdb_total_seasons": 3,
            "tmdb_season_episode_map": {"1": 10, "2": 10, "3": 8},
            "tmdb_episode_mode": "seasonal",
        }
        payload.update(overrides)
        return payload

    def test_explicit_season_wins_over_default_season_one(self):
        name = "House.Of.The.Dragon.S03E07.2160p.MAX.WEB\u2013DL.DV.HDR[Ben The Men].mp4"
        entry = {
            "id": "f1",
            "name": name,
            "is_dir": False,
            "parent_id": "0",
            "parent_path": "剧集",
            "path": f"剧集/{name}",
        }
        result = self._run_plan(entry, {"season": 1}, self._tmdb_binding())
        action = result["actions"][0]
        self.assertTrue(action["ready"])
        self.assertEqual(action["issue"], "")
        self.assertEqual(action["new_name"], "龙之家族 (2022) - S03E07.mp4")

    def test_parent_folder_season_used_for_episode_only_file(self):
        entry = {
            "id": "f2",
            "name": "07.mkv",
            "is_dir": False,
            "parent_id": "0",
            "parent_path": "孤独的美食家.S08",
            "path": "孤独的美食家.S08/07.mkv",
        }
        result = self._run_plan(entry, {"season": 1}, self._tmdb_binding())
        action = result["actions"][0]
        self.assertTrue(action["ready"])
        self.assertEqual(action["new_name"], "龙之家族 (2022) - S08E07.mkv")

    def test_no_season_marker_falls_back_to_default_season(self):
        entry = {
            "id": "f3",
            "name": "未知剧.E05.mkv",
            "is_dir": False,
            "parent_id": "0",
            "parent_path": "剧集",
            "path": "剧集/未知剧.E05.mkv",
        }
        result = self._run_plan(entry, {"season": 1}, self._tmdb_binding())
        action = result["actions"][0]
        self.assertTrue(action["ready"])
        self.assertEqual(action["new_name"], "龙之家族 (2022) - S01E05.mkv")

    def test_multi_season_absolute_mode_maps_explicit_season(self):
        tmdb = self._tmdb_binding(
            tmdb_episode_mode="absolute",
            tmdb_season_episode_map={"1": 10, "2": 10, "3": 8},
        )
        entry = {
            "id": "f4",
            "name": "House.Of.The.Dragon.S03E07.2160p.WEB-DL.mkv",
            "is_dir": False,
            "parent_id": "0",
            "parent_path": "剧集",
            "path": "剧集/House.Of.The.Dragon.S03E07.2160p.WEB-DL.mkv",
        }
        result = self._run_plan(entry, {"season": 1}, tmdb)
        action = result["actions"][0]
        self.assertTrue(action["ready"])
        self.assertEqual(action["new_name"], "龙之家族 (2022) - S03E07.mkv")

    def test_auto_episode_info_helper_prefers_file_season(self):
        from app.services.scraper import _build_task_from_tmdb

        task = _build_task_from_tmdb(self._tmdb_binding(), {"season": 1})
        entry = {
            "id": "f5",
            "name": "House.Of.The.Dragon.S03E07.2160p.WEB-DL.mkv",
            "is_dir": False,
            "parent_path": "剧集",
            "path": "剧集/House.Of.The.Dragon.S03E07.2160p.WEB-DL.mkv",
        }
        info, issue = _resolve_scraper_auto_episode_info(task, entry, 1)
        self.assertEqual(issue, "")
        self.assertEqual(info, {"season": 3, "episodes": [7]})


if __name__ == "__main__":
    unittest.main()
