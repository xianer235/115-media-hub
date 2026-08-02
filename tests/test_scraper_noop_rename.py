import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.scraper import _execute_move_rename, build_scraper_rename_plan


ROOT = Path(__file__).resolve().parents[1]
SCRAPER_CORE_PATH = ROOT / "static/js/modules/scraper/core.js"


class ScraperNoopRenameTest(unittest.TestCase):
    def _plan_payload(self, entry):
        return {
            "provider": "115",
            "base_cid": "root",
            "entries": [entry],
            "tmdb": {
                "id": 42,
                "media_type": "movie",
                "title": "示例电影",
                "year": "2024",
            },
            "options": {
                "selection_mode": "contents",
                "title_language": "zh",
            },
        }

    def test_plan_omits_unchanged_file_before_remote_target_lookup(self):
        entry = {
            "id": "same-file",
            "name": "示例电影 (2024).mkv",
            "is_dir": False,
            "parent_id": "parent",
            "parent_path": "影视",
            "path": "影视/示例电影 (2024).mkv",
        }

        with (
            patch("app.services.scraper._require_scraper_operation"),
            patch("app.services.scraper._require_provider_cookie", return_value="cookie"),
            patch("app.services.scraper._expand_selected_scraper_entries", return_value=([entry], [])),
            patch("app.services.scraper._build_scraper_target_path", return_value=(entry["path"], "")),
            patch(
                "app.services.scraper._walk_existing_folder",
                side_effect=AssertionError("unchanged files must not resolve the target folder"),
            ),
            patch(
                "app.services.scraper._target_name_exists",
                side_effect=AssertionError("unchanged files must not check target conflicts"),
            ),
        ):
            result = build_scraper_rename_plan(self._plan_payload(entry))

        self.assertEqual(result["actions"], [])
        self.assertEqual(result["unchanged_count"], 1)
        self.assertEqual(result["ready_count"], 0)
        self.assertEqual(result["total_count"], 0)

    def test_execute_unchanged_path_skips_without_remote_lookup_or_provider_operation(self):
        action = {
            "id": 1,
            "entry_id": "same-file",
            "old_parent_id": "parent",
            "old_name": "示例电影.mkv",
            "new_name": "示例电影.mkv",
        }

        with (
            patch("app.services.scraper._target_name_exists") as target_name_exists,
            patch("app.services.scraper._rename_provider_entry") as rename_entry,
            patch("app.services.scraper._move_provider_entries") as move_entries,
        ):
            result = _execute_move_rename("115", "cookie", action, "parent")

        self.assertEqual(result, {"skipped": True, "detail": "文件名和目录未变化"})
        target_name_exists.assert_not_called()
        rename_entry.assert_not_called()
        move_entries.assert_not_called()

    def test_same_name_in_different_parent_still_moves_without_rename(self):
        action = {
            "id": 2,
            "entry_id": "moved-file",
            "old_parent_id": "source-parent",
            "old_name": "示例电影.mkv",
            "new_name": "示例电影.mkv",
        }

        with (
            patch("app.services.scraper._target_name_exists", return_value=False),
            patch("app.services.scraper._rename_provider_entry") as rename_entry,
            patch("app.services.scraper._move_provider_entries") as move_entries,
        ):
            result = _execute_move_rename("115", "cookie", action, "target-parent")

        self.assertFalse(result["skipped"])
        rename_entry.assert_not_called()
        move_entries.assert_called_once_with(
            "115",
            "cookie",
            ["moved-file"],
            "target-parent",
            "source-parent",
        )

    def test_changed_name_still_renames_without_move(self):
        action = {
            "id": 3,
            "entry_id": "renamed-file",
            "old_parent_id": "parent",
            "old_name": "原文件.mkv",
            "new_name": "新文件.mkv",
        }

        with (
            patch("app.services.scraper._target_name_exists", return_value=False),
            patch("app.services.scraper._rename_provider_entry") as rename_entry,
            patch("app.services.scraper._move_provider_entries") as move_entries,
        ):
            result = _execute_move_rename("115", "cookie", action, "parent")

        self.assertFalse(result["skipped"])
        rename_entry.assert_called_once_with("115", "cookie", "renamed-file", "新文件.mkv", "parent")
        move_entries.assert_not_called()

    def test_frontend_surfaces_unchanged_plan_count(self):
        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")

        self.assertIn("unchanged_count", source)
        self.assertIn("没有需要改名的文件", source)


if __name__ == "__main__":
    unittest.main()
