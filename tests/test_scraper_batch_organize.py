import asyncio
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app import db
from app.services import monitor_changes
from app.services import monitor
from app.services import scraper


ROOT = Path(__file__).resolve().parents[1]
SCRAPER_CORE_PATH = ROOT / "static/js/modules/scraper/core.js"


class ScraperBatchOrganizeTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "data.db")
        self.strm_root = os.path.join(self.tmpdir.name, "strm")
        self.original_db_path = db.DB_PATH
        self.original_db_ensured = db._DB_ENSURED
        db.DB_PATH = self.db_path
        db._DB_ENSURED = False
        db.ensure_db()

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        db._DB_ENSURED = self.original_db_ensured
        self.tmpdir.cleanup()

    @staticmethod
    def _task(name="影视监控", scan_path="/115/Media", target_path="媒体库", **overrides):
        task = {
            "name": name,
            "scan_path": scan_path,
            "target_path": target_path,
            "skip_by_dir_mtime": True,
            "strm_write_mode": "incremental",
            "sync_clean": False,
            "incremental": True,
            "retries": 1,
            "list_delay_ms": 0,
            "min_file_size_mb": 0,
            "delay_seconds": 0,
            "cron_minutes": 0,
            "webhook_enabled": False,
        }
        task.update(overrides)
        return task

    def _cfg(self, *tasks):
        return {
            "monitor_tasks": list(tasks or (self._task(),)),
            "mount_points": [{"provider": "115", "prefix": "/115"}],
            "extensions": "mkv,mp4",
            "strm_proxy_base_url": "http://localhost:18080",
            "cookie_115": "cookie",
            "tmdb_enabled": True,
            "tmdb_api_key": "key",
            "tmdb_language": "zh-CN",
            "tmdb_region": "CN",
            "tmdb_cache_ttl_hours": 24,
        }

    def _strm_path(self, local_rel_path):
        return os.path.join(self.strm_root, local_rel_path + ".strm")

    def _insert_monitor_file(self, task_name, local_rel_path, remote_rel_path, *, modified="2026-08-09 10:00:00", size=1024):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO monitor_files(task_name, local_rel_path, remote_rel_path, remote_modified, file_size) "
                "VALUES (?, ?, ?, ?, ?)",
                (task_name, local_rel_path, remote_rel_path, modified, size),
            )

    def _write_strm(self, local_rel_path, content="old"):
        path = self._strm_path(local_rel_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        return path

    # ------------------------------------------------------------------
    # 批量扫描分组
    # ------------------------------------------------------------------

    def test_scan_groups_folders_and_media_files_and_skips_non_media(self):
        root_entries = [
            {"id": "d1", "name": "流浪地球 2024", "is_dir": True},
            {"id": "f1", "name": "星际穿越.2014.4K.mkv", "is_dir": False},
            {"id": "f2", "name": "说明.txt", "is_dir": False},
            {"id": "f3", "name": "合集.zip", "is_dir": False},
        ]
        folder_children = {
            "d1": [
                {"id": "d1c", "name": "Season 01", "is_dir": True},
                {"id": "f1a", "name": "流浪地球.S01E01.mkv", "is_dir": False},
            ],
            "d1c": [{"id": "f1b", "name": "流浪地球.S01E02.mkv", "is_dir": False}],
        }

        def fake_list(provider, cookie, cid, folders_only=False):
            return {"entries": folder_children.get(cid, root_entries)}

        with (
            patch.object(scraper, "_require_scraper_operation"),
            patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
            patch.object(scraper, "_list_provider_entries_payload", side_effect=fake_list),
        ):
            result = scraper.scan_scraper_batch_items("115", "root", "影视")

        items = result["items"]
        self.assertEqual(len(items), 2)
        folder_item, file_item = items
        self.assertEqual(folder_item["name"], "流浪地球 2024")
        self.assertTrue(folder_item["is_dir"])
        self.assertEqual([file["name"] for file in folder_item["files"]], [
            "流浪地球.S01E01.mkv",
            "流浪地球.S01E02.mkv",
        ])
        self.assertEqual(folder_item["parent_id"], "root")
        self.assertEqual(folder_item["path"], "影视/流浪地球 2024")
        self.assertFalse(folder_item["no_media"])
        self.assertEqual(file_item["name"], "星际穿越.2014.4K.mkv")
        self.assertFalse(file_item["is_dir"])
        self.assertEqual(file_item["files"], [file_item["entry"]])
        self.assertEqual(result["issues"], [])

    def test_scan_flags_empty_folder_and_uses_path_from_entry(self):
        root_entries = [{"id": "d1", "name": "空文件夹", "is_dir": True}]

        with (
            patch.object(scraper, "_require_scraper_operation"),
            patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
            patch.object(scraper, "_list_provider_entries_payload", return_value={"entries": root_entries}),
        ):
            result = scraper.scan_scraper_batch_items("115", "root", "影视")

        self.assertEqual(len(result["items"]), 1)
        self.assertTrue(result["items"][0]["no_media"])
        self.assertEqual(result["items"][0]["files"], [])

    def test_scan_uses_selected_entries_without_listing_root(self):
        selected = [
            {
                "id": "d1",
                "name": "流浪地球 2024",
                "is_dir": True,
                "parent_id": "root",
                "parent_path": "影视",
                "path": "影视/流浪地球 2024",
            },
            {
                "id": "f1",
                "name": "星际穿越.2014.4K.mkv",
                "is_dir": False,
                "parent_id": "root",
                "parent_path": "影视",
                "path": "影视/星际穿越.2014.4K.mkv",
            },
            {
                "id": "f2",
                "name": "说明.txt",
                "is_dir": False,
                "parent_id": "root",
                "parent_path": "影视",
                "path": "影视/说明.txt",
            },
        ]
        folder_children = {"d1": [{"id": "f1a", "name": "流浪地球.S01E01.mkv", "is_dir": False}]}

        def fake_list(provider, cookie, cid, folders_only=False):
            return {"entries": folder_children.get(cid, [])}

        with (
            patch.object(scraper, "_require_scraper_operation"),
            patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
            patch.object(scraper, "_list_provider_entries_payload", side_effect=fake_list),
        ):
            result = scraper.scan_scraper_batch_items("115", "root", "影视", selected=selected)

        # 根目录列表返回空，说明走的是勾选条目而不是整目录扫描
        items = result["items"]
        self.assertEqual(len(items), 2)
        names = [item["name"] for item in items]
        self.assertIn("流浪地球 2024", names)
        self.assertIn("星际穿越.2014.4K.mkv", names)
        self.assertNotIn("说明.txt", names)
        folder_item = next(item for item in items if item["is_dir"])
        self.assertEqual([file["name"] for file in folder_item["files"]], ["流浪地球.S01E01.mkv"])

    # ------------------------------------------------------------------
    # 批量自动识别
    # ------------------------------------------------------------------

    def test_identify_filters_generic_parent_folder_and_auto_picks_confident_match(self):
        item = {
            "item_index": 1,
            "name": "星际穿越.2014.4K.mkv",
            "entry": {
                "id": "f1",
                "name": "星际穿越.2014.4K.mkv",
                "is_dir": False,
                "parent_id": "root",
                "parent_path": "影视",
                "path": "影视/星际穿越.2014.4K.mkv",
            },
            "files": [],
        }
        captured_queries = []

        def fake_search(query, media_type, year, page, cfg):
            captured_queries.append((query, media_type, year))
            return {
                "items": [
                    {
                        "id": 1,
                        "media_type": "movie",
                        "title": "星际穿越",
                        "original_title": "Interstellar",
                        "year": "2014",
                        "popularity": 90,
                        "vote_average": 8.6,
                    },
                    {
                        "id": 2,
                        "media_type": "movie",
                        "title": "星际迷航",
                        "original_title": "Star Trek",
                        "year": "2013",
                        "popularity": 70,
                        "vote_average": 7.0,
                    },
                ]
            }

        with (
            patch.object(scraper, "search_tmdb_media", side_effect=fake_search),
            patch.object(
                scraper,
                "get_config",
                return_value={
                    "tmdb_enabled": True,
                    "tmdb_api_key": "key",
                    "tmdb_language": "zh-CN",
                    "tmdb_region": "CN",
                    "tmdb_cache_ttl_hours": 24,
                },
            ),
        ):
            result = scraper.identify_scraper_batch_items({"provider": "115", "items": [item]})

        identified = result["results"][0]
        self.assertTrue(identified["ok"])
        self.assertEqual(identified["query"], "星际穿越")
        self.assertEqual(identified["media_type"], "movie")
        self.assertEqual(identified["year"], "2014")
        self.assertEqual(identified["status"], "auto")
        self.assertEqual(identified["auto_pick"]["title"], "星际穿越")
        self.assertGreaterEqual(identified["confidence"], 80)
        self.assertEqual(captured_queries[0][0], "星际穿越")
        # 分数更高的候选排第一
        self.assertEqual(identified["candidates"][0]["id"], 1)

    def test_identify_low_confidence_stays_manual(self):
        item = {
            "item_index": 1,
            "name": "神秘文件A.mkv",
            "entry": {
                "id": "f1",
                "name": "神秘文件A.mkv",
                "is_dir": False,
                "parent_id": "root",
                "parent_path": "影视",
                "path": "影视/神秘文件A.mkv",
            },
            "files": [],
        }

        def fake_search(query, media_type, year, page, cfg):
            return {
                "items": [
                    {
                        "id": 99,
                        "media_type": "movie",
                        "title": "完全无关的电影",
                        "original_title": "Unrelated",
                        "year": "1999",
                        "popularity": 5,
                        "vote_average": 5.0,
                    }
                ]
            }

        with (
            patch.object(scraper, "search_tmdb_media", side_effect=fake_search),
            patch.object(
                scraper,
                "get_config",
                return_value={
                    "tmdb_enabled": True,
                    "tmdb_api_key": "key",
                    "tmdb_language": "zh-CN",
                    "tmdb_region": "CN",
                    "tmdb_cache_ttl_hours": 24,
                },
            ),
        ):
            result = scraper.identify_scraper_batch_items({"provider": "115", "items": [item]})

        identified = result["results"][0]
        self.assertEqual(identified["status"], "manual")
        self.assertIsNone(identified["auto_pick"])
        self.assertLess(identified["confidence"], 55)

    def test_identify_uses_folder_title_not_library_parent_folder(self):
        folder_name = "Governor (2026) [1080p] [WEBRip] [x265] [10bit] [5.1] [YTS.GG - YTS.BZ]"
        item = {
            "item_index": 1,
            "name": folder_name,
            "entry": {
                "id": "d1",
                "name": folder_name,
                "is_dir": True,
                "parent_id": "root",
                "parent_path": "电影小库",
                "path": f"电影小库/{folder_name}",
            },
            "files": [{"id": "f1", "name": "Governor.2026.1080p.mkv", "is_dir": False}],
        }
        captured_queries = []

        def fake_search(query, media_type, year, page, cfg):
            captured_queries.append((query, media_type, year))
            return {"items": []}

        with (
            patch.object(scraper, "search_tmdb_media", side_effect=fake_search),
            patch.object(
                scraper,
                "get_config",
                return_value={
                    "tmdb_enabled": True,
                    "tmdb_api_key": "key",
                    "tmdb_language": "zh-CN",
                    "tmdb_region": "CN",
                    "tmdb_cache_ttl_hours": 24,
                },
            ),
        ):
            result = scraper.identify_scraper_batch_items({"provider": "115", "items": [item]})

        identified = result["results"][0]
        self.assertEqual(identified["query"], "Governor")
        self.assertEqual(identified["media_type"], "movie")
        self.assertEqual(identified["year"], "2026")
        self.assertEqual(captured_queries[0][0], "Governor")

    def test_identify_falls_back_to_file_title_for_generic_folder_name(self):
        item = {
            "item_index": 1,
            "name": "电影小库",
            "entry": {
                "id": "d1",
                "name": "电影小库",
                "is_dir": True,
                "parent_id": "root",
                "parent_path": "根",
                "path": "根/电影小库",
            },
            "files": [{"id": "f1", "name": "流浪地球.2024.1080p.mkv", "is_dir": False}],
        }
        captured_queries = []

        def fake_search(query, media_type, year, page, cfg):
            captured_queries.append((query, media_type, year))
            return {"items": []}

        with (
            patch.object(scraper, "search_tmdb_media", side_effect=fake_search),
            patch.object(
                scraper,
                "get_config",
                return_value={
                    "tmdb_enabled": True,
                    "tmdb_api_key": "key",
                    "tmdb_language": "zh-CN",
                    "tmdb_region": "CN",
                    "tmdb_cache_ttl_hours": 24,
                },
            ),
        ):
            result = scraper.identify_scraper_batch_items({"provider": "115", "items": [item]})

        identified = result["results"][0]
        self.assertEqual(identified["query"], "流浪地球")
        self.assertEqual(identified["year"], "2024")
        self.assertEqual(captured_queries[0][0], "流浪地球")

    def test_strip_extension_keeps_release_group_bracket_tail(self):
        name = "Governor (2026) [1080p] [WEBRip] [x265] [10bit] [5.1] [YTS.GG - YTS.BZ]"
        self.assertEqual(scraper._strip_extension(name), name)
        self.assertEqual(scraper._clean_search_title(name), "Governor")

    def test_clean_search_title_strips_site_prefix_and_release_groups(self):
        dotted = "www.UIndex.org - Secrets to Kill For 2025 NORDiC 1080p WEB-DL DDP5.1 H.264-ADDICTION"
        spaced = "www UIndex org - Secrets to Kill For 2025 NORDiC 1080p WEB-DL DDP5 1 H 264-ADDICTION"
        self.assertEqual(scraper._clean_search_title(dotted), "Secrets to Kill For")
        self.assertEqual(scraper._clean_search_title(spaced), "Secrets to Kill For")
        self.assertEqual(
            scraper._clean_search_title("Movie.Name.2024.1080p.BluRay.x264-GROUP"),
            "Movie Name",
        )
        self.assertEqual(
            scraper._clean_search_title("The.Dark.Knight.2008.1080p.BluRay.x264.DDP5.1-HIGH"),
            "The Dark Knight",
        )

    def test_identify_cleans_site_prefix_and_release_groups_in_query(self):
        folder_name = "www.UIndex.org - Secrets to Kill For 2025 NORDiC 1080p WEB-DL DDP5.1 H.264-ADDICTION"
        item = {
            "item_index": 1,
            "name": folder_name,
            "entry": {
                "id": "d1",
                "name": folder_name,
                "is_dir": True,
                "parent_id": "root",
                "parent_path": "电影小库",
                "path": f"电影小库/{folder_name}",
            },
            "files": [],
        }
        captured_queries = []

        def fake_search(query, media_type, year, page, cfg):
            captured_queries.append((query, media_type, year))
            return {"items": []}

        with (
            patch.object(scraper, "search_tmdb_media", side_effect=fake_search),
            patch.object(
                scraper,
                "get_config",
                return_value={
                    "tmdb_enabled": True,
                    "tmdb_api_key": "key",
                    "tmdb_language": "zh-CN",
                    "tmdb_region": "CN",
                    "tmdb_cache_ttl_hours": 24,
                },
            ),
        ):
            result = scraper.identify_scraper_batch_items({"provider": "115", "items": [item]})

        identified = result["results"][0]
        self.assertEqual(identified["query"], "Secrets to Kill For")
        self.assertEqual(identified["year"], "2025")
        self.assertEqual(captured_queries[0], ("Secrets to Kill For", "movie", "2025"))

    def test_extract_title_candidates_uses_technical_markers_as_boundaries(self):
        self.assertEqual(
            scraper._extract_scraper_title_candidates(
                "www.UIndex.org - Secrets to Kill For 2025 NORDiC 1080p WEB-DL DDP5.1 H.264-ADDICTION"
            ),
            ["Secrets to Kill For"],
        )
        self.assertEqual(
            scraper._extract_scraper_title_candidates("S01E01 Show Name.mkv"),
            ["Show Name"],
        )
        self.assertEqual(
            scraper._extract_scraper_title_candidates("[abc字幕组] 电影名.2024.1080p.mkv"),
            ["电影名"],
        )
        self.assertEqual(
            scraper._extract_scraper_title_candidates("Movie.Name.2024.1080p.BluRay.x264-GROUP"),
            ["Movie Name"],
        )

    def test_degraded_query_hit_is_suggest_not_auto(self):
        entry = {
            "id": "d1",
            "name": "示例条目",
            "is_dir": True,
            "parent_id": "root",
            "parent_path": "影视",
            "path": "影视/示例条目",
        }
        item = {"item_index": 1, "name": "示例条目", "entry": entry, "files": []}

        def fake_payload(entry, files):
            return "主标题", "movie", "2024", ["主标题", "降级标题"]

        def fake_search(query, media_type, year, page, cfg):
            if query == "降级标题":
                return {
                    "items": [
                        {
                            "id": 9,
                            "media_type": "movie",
                            "title": "降级标题",
                            "original_title": "Degraded Title",
                            "year": "2024",
                            "popularity": 60,
                            "vote_average": 7.0,
                        }
                    ]
                }
            return {"items": []}

        with (
            patch.object(scraper, "_batch_item_query_payload", side_effect=fake_payload),
            patch.object(scraper, "search_tmdb_media", side_effect=fake_search),
            patch.object(
                scraper,
                "get_config",
                return_value={
                    "tmdb_enabled": True,
                    "tmdb_api_key": "key",
                    "tmdb_language": "zh-CN",
                    "tmdb_region": "CN",
                    "tmdb_cache_ttl_hours": 24,
                },
            ),
        ):
            result = scraper.identify_scraper_batch_items({"provider": "115", "items": [item]})

        identified = result["results"][0]
        self.assertEqual(identified["status"], "suggest")
        self.assertIsNone(identified["auto_pick"])
        self.assertLess(identified["confidence"], 80)

    def test_handle_click_dispatches_batch_buttons_before_action_guard(self):
        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")
        handle_source = source[source.index("function handleClick("):]
        batch_index = handle_source.index("data-batch-accept")
        guard_index = handle_source.index("if (!actionButton) return;")
        self.assertLess(
            batch_index,
            guard_index,
            "批量按钮处理必须位于 data-scraper-action 守卫之前，否则改绑/接受/搜索按钮点击无响应",
        )

    # ------------------------------------------------------------------
    # 批量计划合并
    # ------------------------------------------------------------------

    def test_batch_plan_merges_actions_and_detects_cross_item_target_conflict(self):
        tmdb = {"tmdb_id": 7, "media_type": "movie", "tmdb_media_type": "movie", "tmdb_year": "2024"}

        def fake_binding(binding, cfg):
            return {
                **binding,
                "tmdb_id": 7,
                "tmdb_media_type": "movie",
                "tmdb_title": "新标题",
                "tmdb_year": "2024",
                "tmdb_original_title": "New Title",
                "tmdb_localized_title": "新标题",
                "tmdb_aliases": [],
                "tmdb_total_episodes": 0,
                "tmdb_total_seasons": 0,
                "tmdb_season_episode_map": {},
                "tmdb_episode_mode": "seasonal",
            }

        payload = {
            "provider": "115",
            "base_cid": "root",
            "base_path": "影视",
            "options": {"title_language": "zh"},
            "items": [
                {
                    "item_index": 1,
                    "name": "文件夹A",
                    "entry": {"id": "d1", "name": "文件夹A", "is_dir": True, "parent_id": "root", "parent_path": "影视", "path": "影视/文件夹A"},
                    "tmdb": tmdb,
                },
                {
                    "item_index": 2,
                    "name": "文件夹B",
                    "entry": {"id": "d2", "name": "文件夹B", "is_dir": True, "parent_id": "root", "parent_path": "影视", "path": "影视/文件夹B"},
                    "tmdb": tmdb,
                },
            ],
        }

        def fake_item_plan(payload):
            entry = payload["entries"][0]
            is_dir = bool(entry.get("is_dir"))
            return {
                "actions": [
                    {
                        "entry_id": entry["id"],
                        "is_dir": is_dir,
                        "old_parent_id": entry.get("parent_id", "root"),
                        "old_name": entry["name"],
                        "old_path": entry.get("path", entry["name"]),
                        "new_parent_id": "root",
                        "new_name": "新标题 (2024)" if is_dir else "新标题 (2024).mkv",
                        "new_path": "影视/新标题 (2024)" if is_dir else "影视/新标题 (2024).mkv",
                        "target_parent_path": "",
                        "file_size": 0,
                        "remote_modified": "",
                        "issue": "",
                        "warning": "",
                        "ready": True,
                    }
                ],
                "issues": [],
                "warnings": [],
                "unchanged_count": 0,
            }

        with (
            patch.object(scraper, "_require_scraper_operation"),
            patch.object(scraper, "_resolve_batch_tmdb_binding", side_effect=fake_binding),
            patch.object(scraper, "build_scraper_rename_plan", side_effect=fake_item_plan),
            patch.object(
                scraper,
                "get_config",
                return_value={"tmdb_enabled": True, "tmdb_api_key": "key"},
            ),
        ):
            plan = scraper.build_scraper_batch_plan(payload)

        self.assertEqual(plan["total_count"], 2)
        self.assertEqual(plan["ready_count"], 1)
        self.assertEqual([action["action_index"] for action in plan["actions"]], [1, 2])
        self.assertEqual([action["item_index"] for action in plan["actions"]], [1, 2])
        self.assertTrue(plan["actions"][1]["issue"])
        self.assertFalse(plan["actions"][1]["ready"])
        self.assertTrue(any("与本批次其他条目重复" in issue for issue in plan["issues"]))
        self.assertEqual(len(plan["items"]), 2)
        self.assertEqual(plan["items"][0]["title"], "新标题")

    def test_batch_plan_reports_unbound_item_as_issue(self):
        payload = {
            "provider": "115",
            "base_cid": "root",
            "base_path": "影视",
            "options": {},
            "items": [
                {
                    "item_index": 1,
                    "name": "未绑定",
                    "entry": {"id": "d1", "name": "未绑定", "is_dir": True, "parent_id": "root", "parent_path": "影视", "path": "影视/未绑定"},
                    "tmdb": {},
                }
            ],
        }
        with (
            patch.object(scraper, "_require_scraper_operation"),
            patch.object(scraper, "_resolve_batch_tmdb_binding", return_value={}),
            patch.object(scraper, "get_config", return_value={"tmdb_enabled": True, "tmdb_api_key": "key"}),
        ):
            plan = scraper.build_scraper_batch_plan(payload)

        self.assertEqual(plan["actions"], [])
        self.assertEqual(plan["total_count"], 0)
        self.assertEqual(len(plan["issues"]), 1)
        self.assertIn("未绑定 TMDB", plan["issues"][0])

    # ------------------------------------------------------------------
    # 批量计划 → 任务执行 → 监控目录 STRM 同步
    # ------------------------------------------------------------------

    def test_batch_plan_job_syncs_monitored_folder_strm_without_remote_listing(self):
        task = self._task(scan_path="/115/一级", target_path="媒体库")
        cfg = self._cfg(task)
        tmdb = {"tmdb_id": 7, "media_type": "movie", "tmdb_media_type": "movie", "tmdb_year": "2024"}

        def fake_binding(binding, cfg):
            return {
                **binding,
                "tmdb_id": 7,
                "tmdb_media_type": "movie",
                "tmdb_title": "新标题",
                "tmdb_year": "2024",
                "tmdb_original_title": "New Title",
                "tmdb_localized_title": "新标题",
                "tmdb_aliases": [],
                "tmdb_total_episodes": 0,
                "tmdb_total_seasons": 0,
                "tmdb_season_episode_map": {},
                "tmdb_episode_mode": "seasonal",
            }

        def fake_item_plan(payload):
            entry = payload["entries"][0]
            return {
                "actions": [
                    {
                        "entry_id": entry["id"],
                        "is_dir": False,
                        "old_parent_id": entry.get("parent_id", "root"),
                        "old_name": entry["name"],
                        "old_path": entry.get("path", entry["name"]),
                        "new_parent_id": "root",
                        "new_name": "新标题 (2024).mkv",
                        "new_path": f"一级/二级/新标题 (2024).mkv",
                        "target_parent_path": "一级/二级",
                        "file_size": 1024,
                        "remote_modified": "2026-08-09 10:00:00",
                        "issue": "",
                        "warning": "",
                        "ready": True,
                    }
                ],
                "issues": [],
                "warnings": [],
                "unchanged_count": 0,
            }

        payload = {
            "provider": "115",
            "base_cid": "second-level-cid",
            "base_path": "一级/二级",
            "options": {"title_language": "zh"},
            "items": [
                {
                    "item_index": 1,
                    "name": "旧文件.mkv",
                    "entry": {
                        "id": "batch-file",
                        "name": "旧文件.mkv",
                        "is_dir": False,
                        "parent_id": "second-level-cid",
                        "parent_path": "一级/二级",
                        "path": "一级/二级/旧文件.mkv",
                    },
                    "tmdb": tmdb,
                }
            ],
        }
        with (
            patch.object(scraper, "_require_scraper_operation"),
            patch.object(scraper, "_resolve_batch_tmdb_binding", side_effect=fake_binding),
            patch.object(scraper, "build_scraper_rename_plan", side_effect=fake_item_plan),
            patch.object(scraper, "get_config", return_value=cfg),
        ):
            plan = scraper.build_scraper_batch_plan(payload)

        self.assertEqual(plan["ready_count"], 1)
        self._insert_monitor_file("影视监控", "媒体库/一级/二级/旧文件.mkv", "二级/旧文件.mkv")
        self._write_strm("媒体库/一级/二级/旧文件.mkv", "old")

        job_result = scraper.create_scraper_job_from_plan({"plan": plan})
        job_id = int(job_result["job_id"])
        with (
            patch.object(scraper, "get_config", return_value=cfg),
            patch.object(scraper, "_require_scraper_operation"),
            patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
            patch.object(scraper, "_target_name_exists", return_value=False),
            patch.object(scraper, "_rename_provider_entry", return_value={"state": True}),
            patch.object(scraper, "_move_provider_entries", return_value={"state": True}),
            patch.object(scraper, "_invalidate_provider_parent"),
            patch.object(monitor_changes, "_enqueue_task_names"),
        ):
            scraper.run_scraper_job(job_id)

        with (
            patch.object(monitor_changes, "STRM_ROOT", self.strm_root),
            patch.object(
                monitor_changes,
                "list_remote_dir",
                AsyncMock(side_effect=AssertionError("known batch renames must not list 115 directories")),
            ),
        ):
            result = asyncio.run(monitor_changes.process_monitor_change_events(cfg=cfg))

        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["deleted"], 1)
        self.assertEqual(result["generated"], 1)
        self.assertFalse(os.path.exists(self._strm_path("媒体库/一级/二级/旧文件.mkv")))
        self.assertTrue(os.path.exists(self._strm_path("媒体库/一级/二级/新标题 (2024).mkv")))
        with sqlite3.connect(self.db_path) as conn:
            indexed = conn.execute(
                "SELECT local_rel_path, remote_rel_path FROM monitor_files ORDER BY local_rel_path"
            ).fetchall()
        self.assertEqual(
            indexed,
            [("媒体库/一级/二级/新标题 (2024).mkv", "二级/新标题 (2024).mkv")],
        )

    # ------------------------------------------------------------------
    # 识别核心：guessit 结构化解析 + 候选打分
    # ------------------------------------------------------------------

    def test_extract_title_candidates_handles_path_multi_part_and_mixed_language(self):
        governor = "Governor (2026) [1080p] [WEBRip] [x265] [10bit] [5.1] [YTS.GG - YTS.BZ]"
        candidates = scraper._extract_scraper_title_candidates(f"电影小库/{governor}")
        self.assertEqual(candidates, ["Governor"])

        treme = scraper._extract_scraper_title_candidates(
            "Treme.1x03.Right.Place,.Wrong.Time.HDTV.XviD-NoTV.avi"
        )
        self.assertEqual(treme[0], "Treme")

        dune = scraper._extract_scraper_title_candidates(
            "Dune.Part.Two.2024.2160p.UHD.BluRay.x265.10bit.HDR.TrueHD.Atmos.7.1-GROUP"
        )
        self.assertIn("Dune Part Two", dune)

        mixed = scraper._extract_scraper_title_candidates(
            "疾速追杀4 John.Wick.Chapter.4.2023.1080p.WEB-DL.DDP5.1.H.264-ADDICTION"
        )
        self.assertIn("John Wick Chapter 4", mixed)
        self.assertIn("疾速追杀", mixed)

    def test_looks_like_tv_uses_guessit_for_1x03_format(self):
        self.assertTrue(
            scraper._looks_like_tv(["Treme.1x03.Right.Place,.Wrong.Time.HDTV.XviD-NoTV.avi"])
        )
        self.assertFalse(scraper._looks_like_tv(["E.T. the Extra-Terrestrial 1982 1080p.mkv"]))
        self.assertFalse(scraper._looks_like_tv(["星际穿越.2014.4K.mkv"]))

    def test_identify_full_path_entry_uses_last_path_component(self):
        folder_name = "Governor (2026) [1080p] [WEBRip] [x265] [10bit] [5.1] [YTS.GG - YTS.BZ]"
        full_path = f"电影小库/{folder_name}"
        item = {
            "item_index": 1,
            "name": full_path,
            "entry": {
                "id": "d1",
                "name": full_path,
                "is_dir": True,
                "parent_id": "root",
                "parent_path": "电影小库",
                "path": full_path,
            },
            "files": [],
        }
        captured_queries = []

        def fake_search(query, media_type, year, page, cfg):
            captured_queries.append((query, media_type, year))
            return {"items": []}

        with (
            patch.object(scraper, "search_tmdb_media", side_effect=fake_search),
            patch.object(
                scraper,
                "get_config",
                return_value={
                    "tmdb_enabled": True,
                    "tmdb_api_key": "key",
                    "tmdb_language": "zh-CN",
                    "tmdb_region": "CN",
                    "tmdb_cache_ttl_hours": 24,
                },
            ),
        ):
            result = scraper.identify_scraper_batch_items({"provider": "115", "items": [item]})

        identified = result["results"][0]
        self.assertEqual(identified["query"], "Governor")
        self.assertEqual(identified["year"], "2026")
        self.assertEqual(captured_queries[0], ("Governor", "movie", "2026"))

    def test_identify_year_conflict_does_not_auto_pick_remake(self):
        folder_name = "Robocop (2014) [1080p] [WEBRip] [x265] [5.1] [YTS.MX]"
        item = {
            "item_index": 1,
            "name": folder_name,
            "entry": {
                "id": "d1",
                "name": folder_name,
                "is_dir": True,
                "parent_id": "root",
                "parent_path": "电影小库",
                "path": f"电影小库/{folder_name}",
            },
            "files": [],
        }

        def fake_search(query, media_type, year, page, cfg):
            return {
                "items": [
                    {
                        "id": 1,
                        "media_type": "movie",
                        "title": "Robocop",
                        "original_title": "Robocop",
                        "year": "1987",
                        "popularity": 500,
                        "vote_average": 7.6,
                    },
                    {
                        "id": 2,
                        "media_type": "movie",
                        "title": "Robocop",
                        "original_title": "Robocop",
                        "year": "2014",
                        "popularity": 300,
                        "vote_average": 5.8,
                    },
                ]
            }

        with (
            patch.object(scraper, "search_tmdb_media", side_effect=fake_search),
            patch.object(
                scraper,
                "get_config",
                return_value={
                    "tmdb_enabled": True,
                    "tmdb_api_key": "key",
                    "tmdb_language": "zh-CN",
                    "tmdb_region": "CN",
                    "tmdb_cache_ttl_hours": 24,
                },
            ),
        ):
            result = scraper.identify_scraper_batch_items({"provider": "115", "items": [item]})

        identified = result["results"][0]
        self.assertEqual(identified["status"], "auto")
        self.assertEqual(identified["auto_pick"]["id"], 2)
        self.assertEqual(identified["auto_pick"]["year"], "2014")

    def test_identify_alias_enrichment_breaks_tie(self):
        item = {
            "item_index": 1,
            "name": "星际穿越.2014.4K.mkv",
            "entry": {
                "id": "f1",
                "name": "星际穿越.2014.4K.mkv",
                "is_dir": False,
                "parent_id": "root",
                "parent_path": "影视",
                "path": "影视/星际穿越.2014.4K.mkv",
            },
            "files": [],
        }

        def fake_search(query, media_type, year, page, cfg):
            return {
                "items": [
                    {
                        "id": 1,
                        "media_type": "movie",
                        "title": "Interstellar",
                        "original_title": "Interstellar",
                        "year": "2014",
                        "popularity": 90,
                        "vote_average": 8.6,
                    },
                    {
                        "id": 2,
                        "media_type": "movie",
                        "title": "星际争霸",
                        "original_title": "StarCraft",
                        "year": "2014",
                        "popularity": 80,
                        "vote_average": 7.0,
                    },
                ]
            }

        def fake_detail(tmdb_id, media_type, cfg):
            if tmdb_id == 1:
                return {"aliases": ["星际穿越"]}
            return {"aliases": []}

        with (
            patch.object(scraper, "search_tmdb_media", side_effect=fake_search),
            patch.object(scraper, "get_tmdb_media_detail", side_effect=fake_detail),
            patch.object(
                scraper,
                "get_config",
                return_value={
                    "tmdb_enabled": True,
                    "tmdb_api_key": "key",
                    "tmdb_language": "zh-CN",
                    "tmdb_region": "CN",
                    "tmdb_cache_ttl_hours": 24,
                },
            ),
        ):
            result = scraper.identify_scraper_batch_items({"provider": "115", "items": [item]})

        identified = result["results"][0]
        self.assertEqual(identified["status"], "auto")
        self.assertEqual(identified["auto_pick"]["id"], 1)
        self.assertEqual(identified["auto_pick"]["title"], "Interstellar")

    # ------------------------------------------------------------------
    # 非影视文件分类处理：字幕多语言唯一命名、海报/广告保留
    # ------------------------------------------------------------------

    @staticmethod
    def _tmdb_binding(title="Skurkarnas skurk", year="2026", media_type="movie"):
        return {
            "tmdb_id": 100,
            "tmdb_media_type": media_type,
            "tmdb_title": title,
            "tmdb_year": year,
            "tmdb_original_title": title,
            "tmdb_localized_title": title,
            "tmdb_aliases": [],
            "tmdb_total_episodes": 0,
            "tmdb_total_seasons": 0,
            "tmdb_season_episode_map": {},
            "tmdb_episode_mode": "seasonal",
        }

    def _rename_plan_with_files(self, files, tmdb, folder_name="Skurkarnas skurk (2026)", options=None):
        folder = {
            "id": "d1",
            "name": folder_name,
            "is_dir": True,
            "parent_id": "root",
            "parent_path": "影视",
            "path": f"影视/{folder_name}",
        }
        entries = []
        for index, name in enumerate(files, start=1):
            entries.append(
                {
                    "id": f"f{index}",
                    "name": name,
                    "is_dir": False,
                    "parent_id": "d1",
                    "parent_path": folder_name,
                    "path": f"{folder_name}/{name}",
                }
            )

        def fake_list(provider, cookie, cid, folders_only=False):
            if cid == "d1":
                return {"entries": entries}
            return {"entries": []}

        with (
            patch.object(scraper, "_require_scraper_operation"),
            patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
            patch.object(scraper, "_list_provider_entries_payload", side_effect=fake_list),
            patch.object(scraper, "_target_name_exists", return_value=False),
            patch.object(
                scraper,
                "get_config",
                return_value={"tmdb_enabled": True, "tmdb_api_key": "key", "tmdb_language": "zh-CN", "tmdb_region": "CN"},
            ),
        ):
            return scraper.build_scraper_rename_plan(
                {
                    "provider": "115",
                    "base_cid": "root",
                    "base_path": "影视",
                    "entries": [folder],
                    "tmdb": tmdb,
                    "options": {"title_language": "zh", **(options or {})},
                }
            )

    def test_scraper_file_category_classifies_media_subtitle_image_ad(self):
        self.assertEqual(scraper._scraper_file_category("Movie.mkv"), "video")
        self.assertEqual(scraper._scraper_file_category("Denmark.dan.srt"), "subtitle")
        self.assertEqual(scraper._scraper_file_category("poster.jpg"), "image")
        self.assertEqual(scraper._scraper_file_category("YTSYifyUP (TOR).txt"), "ad")
        self.assertEqual(scraper._scraper_file_category("readme.md"), "other")

    def test_scraper_subtitle_suffix_extracts_language_tags(self):
        self.assertEqual(scraper._scraper_subtitle_suffix("Denmark.dan.srt"), ".dan")
        self.assertEqual(scraper._scraper_subtitle_suffix("Movie.eng.srt"), ".eng")
        self.assertEqual(scraper._scraper_subtitle_suffix("Movie.zh-Hans.forced.srt"), ".zh-Hans.forced")
        self.assertEqual(scraper._scraper_subtitle_suffix("Movie.srt"), "")

    def test_scraper_ad_image_and_standard_image_detection(self):
        self.assertTrue(scraper._is_scraper_ad_image("YTS.GG - Official site.jpg"))
        self.assertTrue(scraper._is_scraper_ad_image("www.UIndex.org - Official site.jpg"))
        self.assertFalse(scraper._is_scraper_ad_image("Skurkarnas skurk (2026).jpg"))
        self.assertTrue(scraper._is_scraper_standard_image("poster.jpg"))
        self.assertTrue(scraper._is_scraper_standard_image("folder.jpg"))
        self.assertFalse(scraper._is_scraper_standard_image("Skurkarnas skurk (2026).jpg"))

    def test_build_rename_plan_keeps_subtitles_languages_and_skips_ad_files(self):
        tmdb = self._tmdb_binding()
        plan = self._rename_plan_with_files(
            [
                "Skurkarnas skurk (2026) [1080p WEBRip H.264].mp4",
                "Denmark.dan.srt",
                "English.eng.srt",
                "YTS.GG - Official site.jpg",
                "YTSYifyUP (TOR).txt",
            ],
            tmdb,
        )

        by_old_name = {action["old_name"]: action for action in plan["actions"]}
        self.assertEqual(by_old_name["Skurkarnas skurk (2026) [1080p WEBRip H.264].mp4"]["new_name"], "Skurkarnas skurk (2026).mp4")
        self.assertEqual(by_old_name["Denmark.dan.srt"]["new_name"], "Skurkarnas skurk (2026).dan.srt")
        self.assertEqual(by_old_name["English.eng.srt"]["new_name"], "Skurkarnas skurk (2026).eng.srt")
        self.assertNotIn("YTS.GG - Official site.jpg", by_old_name)
        self.assertNotIn("YTSYifyUP (TOR).txt", by_old_name)
        self.assertEqual(plan["ignored_count"], 2)
        self.assertTrue(any("已保留" in warning and "广告" in warning for warning in plan["warnings"]))

    def test_build_rename_plan_multiple_same_language_subtitles_get_unique_names(self):
        tmdb = self._tmdb_binding()
        plan = self._rename_plan_with_files(
            [
                "Skurkarnas skurk (2026).mp4",
                "Subtitle.A.dan.srt",
                "Subtitle.B.dan.srt",
            ],
            tmdb,
        )

        subtitle_actions = [action for action in plan["actions"] if action["old_name"].endswith(".srt")]
        self.assertEqual(len(subtitle_actions), 2)
        names = sorted(action["new_name"] for action in subtitle_actions)
        self.assertEqual(names, ["Skurkarnas skurk (2026) (2).dan.srt", "Skurkarnas skurk (2026).dan.srt"])
        self.assertTrue(all(action["ready"] for action in subtitle_actions))
        self.assertFalse(any(action["issue"] for action in subtitle_actions))

    def test_build_rename_plan_tv_subtitle_keeps_episode_code_and_language(self):
        tmdb = self._tmdb_binding(title="Show", year="2024", media_type="tv")
        plan = self._rename_plan_with_files(
            [
                "Show.S01E02.1080p.mkv",
                "Show.S01E02.dan.srt",
            ],
            tmdb,
            folder_name="Show",
        )

        by_old_name = {action["old_name"]: action for action in plan["actions"]}
        self.assertEqual(by_old_name["Show.S01E02.1080p.mkv"]["new_name"], "Show (2024) - S01E02.mkv")
        self.assertEqual(by_old_name["Show.S01E02.dan.srt"]["new_name"], "Show (2024) - S01E02.dan.srt")
        self.assertTrue(by_old_name["Show.S01E02.dan.srt"]["ready"])

    def test_batch_plan_propagates_ignored_count(self):
        payload = {
            "provider": "115",
            "base_cid": "root",
            "base_path": "影视",
            "options": {"title_language": "zh"},
            "items": [
                {
                    "item_index": 1,
                    "name": "文件夹A",
                    "entry": {"id": "d1", "name": "文件夹A", "is_dir": True, "parent_id": "root", "parent_path": "影视", "path": "影视/文件夹A"},
                    "tmdb": {"tmdb_id": 7, "media_type": "movie", "tmdb_media_type": "movie", "tmdb_year": "2024"},
                }
            ],
        }

        def fake_binding(binding, cfg):
            return {
                **binding,
                "tmdb_id": 7,
                "tmdb_media_type": "movie",
                "tmdb_title": "新标题",
                "tmdb_year": "2024",
                "tmdb_original_title": "New Title",
                "tmdb_localized_title": "新标题",
                "tmdb_aliases": [],
                "tmdb_total_episodes": 0,
                "tmdb_total_seasons": 0,
                "tmdb_season_episode_map": {},
                "tmdb_episode_mode": "seasonal",
            }

        def fake_item_plan(payload):
            return {
                "actions": [],
                "issues": [],
                "warnings": [],
                "unchanged_count": 0,
                "ignored_count": 2,
            }

        with (
            patch.object(scraper, "_require_scraper_operation"),
            patch.object(scraper, "_resolve_batch_tmdb_binding", side_effect=fake_binding),
            patch.object(scraper, "build_scraper_rename_plan", side_effect=fake_item_plan),
            patch.object(
                scraper,
                "get_config",
                return_value={"tmdb_enabled": True, "tmdb_api_key": "key"},
            ),
        ):
            plan = scraper.build_scraper_batch_plan(payload)

        self.assertEqual(plan["ignored_count"], 2)
        self.assertEqual(plan["items"][0]["ignored"], 2)

    # ------------------------------------------------------------------
    # 手动识别与批量识别合并：单一入口 + 行内大爆炸选词
    # ------------------------------------------------------------------

    def test_scraper_toolbar_merges_identify_into_single_entry(self):
        html_path = ROOT / "templates/partials/pages/scraper.html"
        html = html_path.read_text(encoding="utf-8")
        self.assertEqual(html.count('data-scraper-action="open-batch"'), 1)
        self.assertIn('scraper-action-label-full">批量整理</span>', html)
        self.assertIn('scraper-action-label-short">整理</span>', html)
        self.assertNotIn('data-scraper-action="identify"', html)
        # 工具栏只保留“退出预览”，不再有“退出识别”；旧面板头部的关闭图标保留。
        self.assertEqual(html.count('data-scraper-action="clear-identify"'), 1)
        self.assertIn('id="scraper-clear-plan-btn"', html)

    def test_render_selection_no_longer_manages_toolbar_exit_identify_button(self):
        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")
        render_selection_source = source[source.index("function renderSelection("):source.index("function renderSortButton(")]
        self.assertNotIn("clearIdentifyButton", render_selection_source)

    def test_handle_click_merges_identify_into_batch_entry(self):
        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")
        handle_source = source[source.index("function handleClick("):]
        guard_index = handle_source.index("const actionButton = event.target.closest('[data-scraper-action]')")
        self.assertIn("if (action === 'identify' || action === 'open-batch') openBatchPanel();", handle_source)
        self.assertLess(handle_source.index("data-batch-path-complete"), guard_index)
        self.assertLess(handle_source.index("data-batch-path-reopen"), guard_index)
        self.assertNotIn("toggleBatchPathToken(", handle_source)

    def test_batch_path_selection_supports_pointer_gesture(self):
        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")
        self.assertIn("function beginBatchPathSelection(", source)
        self.assertIn("function continueBatchPathSelection(", source)
        self.assertIn("function syncBatchPathTokenDom(", source)
        pointer_down = source[source.index("function handlePointerDown("):source.index("function handleGlobalPointerMove(")]
        self.assertIn("data-batch-path-token", pointer_down)
        pointer_move = source[source.index("function handleGlobalPointerMove("):source.index("function endIdentifyPathGesture(")]
        self.assertIn("continueBatchPathSelection(", pointer_move)
        self.assertIn("state.batchPathGesture = null;", source)

    def test_legacy_folder_scoped_syncs_skip_when_batch_panel_open(self):
        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")
        for function_name in (
            "syncIncludeTmdbIdControl",
            "syncSeasonSubfolderControl",
            "syncFolderRenameControl",
        ):
            function_source = source[source.index(f"function {function_name}("):source.index("function getDisplayEntries(")]
            self.assertIn("scraper-batch-panel", function_source)

    def test_preview_row_marks_ready_folders_with_folder_class(self):
        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")
        preview_source = source[source.index("const actionRows = planActions.map((action) => {"):source.index("function renderPlan()")]
        self.assertIn("action.is_dir ? 'is-ready is-ready-dir' : 'is-ready'", preview_source)

    def test_preview_folder_background_has_day_and_night_variants(self):
        css = (ROOT / "static/css/index.css").read_text(encoding="utf-8")
        self.assertIn(".scraper-preview-row.is-ready.is-ready-dir", css)
        self.assertIn("html.theme-day .scraper-preview-row.is-ready.is-ready-dir", css)

    def test_preview_hides_file_operations_and_exit_uses_danger_style(self):
        html = (ROOT / "templates/partials/pages/scraper.html").read_text(encoding="utf-8")
        clear_plan_line = next(line for line in html.splitlines() if 'id="scraper-clear-plan-btn"' in line)
        self.assertIn("scraper-danger-soft", clear_plan_line)

        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")
        render_selection_source = source[source.index("function renderSelection("):source.index("function renderSortButton(")]
        self.assertIn("button.classList.toggle('hidden', hasPlan);", render_selection_source)
        self.assertIn("renameButton.classList.toggle('hidden', hasPlan);", render_selection_source)
        self.assertIn("batchButton.classList.toggle('hidden', hasPlan);", render_selection_source)

    def test_scraper_url_persists_provider_and_folder_path(self):
        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")
        self.assertIn("function getScraperUrlParams(", source)
        self.assertIn("function syncScraperLocationHash(", source)
        self.assertIn("async function restoreScraperLocation(", source)
        self.assertIn("await restoreScraperLocation();", source)
        self.assertIn("history.replaceState(null, '', url);", source)
        sync_source = source[source.index("function syncScraperLocationHash("):source.index("async function restoreScraperLocation(")]
        self.assertNotIn("cid", sync_source)

        switch_source = source[source.index("async function switchProvider("):source.index("async function enterFolder(")]
        self.assertIn("syncScraperLocationHash();", switch_source)
        enter_source = source[source.index("async function enterFolder("):source.index("async function goTrail(")]
        self.assertIn("syncScraperLocationHash();", enter_source)
        go_trail_source = source[source.index("async function goTrail("):source.index("async function createFolder(")]
        self.assertIn("syncScraperLocationHash();", go_trail_source)

    def test_scraper_url_params_are_tab_scoped(self):
        import subprocess
        import tempfile

        url_sync = (ROOT / "static/js/modules/tabs/url-sync.js").read_text(encoding="utf-8")
        self.assertIn("TAB_OWNED_PARAMS", url_sync)
        self.assertIn("scraper: ['provider', 'path', 'cid']", url_sync)
        self.assertIn("keys.forEach(key => params.delete(key));", url_sync)

        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")
        sync_source = source[source.index("function syncScraperLocationHash("):source.index("async function restoreScraperLocation(")]
        self.assertIn("params.get('tab')", sync_source)

        with tempfile.TemporaryDirectory() as tmpdir:
            module_path = os.path.join(tmpdir, "url-sync.mjs")
            with open(module_path, "w", encoding="utf-8") as handle:
                handle.write(url_sync)
            script = (
                f"import {{buildHashWithTab}} from 'file://{module_path}';\n"
                "console.log(buildHashWithTab('monitor', '#tab=scraper&provider=115&path=abc&cid=1'));\n"
                "console.log(buildHashWithTab('scraper', '#tab=monitor&provider=115&path=abc'));\n"
            )
            result = subprocess.run(
                ["node", "--input-type=module", "-e", script],
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.strip().splitlines()
        self.assertEqual(lines[0], "#tab=monitor")
        self.assertIn("tab=scraper", lines[1])
        self.assertIn("provider=115", lines[1])

    def test_preview_offers_return_to_binding_interface(self):
        html = (ROOT / "templates/partials/pages/scraper.html").read_text(encoding="utf-8")
        self.assertIn('id="scraper-reopen-batch-btn"', html)
        self.assertIn('data-scraper-action="reopen-batch"', html)

        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")
        self.assertIn("function reopenBatchPanel(", source)
        self.assertIn("if (action === 'reopen-batch') reopenBatchPanel();", source)
        reopen_source = source[source.index("function reopenBatchPanel("):source.index("function getBatchItem(")]
        self.assertNotIn("resetBatchContext", reopen_source)
        render_selection_source = source[source.index("function renderSelection("):source.index("function renderSortButton(")]
        self.assertIn("reopenBatchButton.classList.toggle('hidden', !canReopen);", render_selection_source)

    def test_batch_binding_highlight_and_busy_animation(self):
        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")
        self.assertIn("const badgeClass = 'is-auto';", source)
        self.assertIn("const badgeText = status === 'auto' ? '自动匹配' : '已绑定';", source)
        render_batch_source = source[source.index("function renderBatch("):source.index("function toggleBatchInclude(")]
        self.assertIn("scraper-busy-spinner", render_batch_source)

        css = (ROOT / "static/css/index.css").read_text(encoding="utf-8")
        self.assertIn("@keyframes scraperSpin", css)
        self.assertIn(".scraper-busy-spinner", css)
        self.assertIn("html.theme-day .scraper-busy-spinner", css)
        self.assertIn(".scraper-batch-row.is-included", css)
        self.assertIn("html.theme-day .scraper-batch-row.is-included", css)

    def test_preview_warning_content_is_visible(self):
        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")
        toast_source = source[source.index("function showPlanReadyToast("):source.index("async function buildPlan(")]
        self.assertIn("warningText", toast_source)
        self.assertIn("warningNote", toast_source)
        entries_source = source[source.index("const planWarnings = Array.isArray(state.plan?.warnings)"):source.index("function renderPlan()")]
        self.assertIn("scraper-plan-warning-bar", entries_source)
        self.assertIn("warningBar + actionRows + unchangedHtml", entries_source)

        css = (ROOT / "static/css/index.css").read_text(encoding="utf-8")
        self.assertIn(".scraper-plan-warning-bar", css)
        self.assertIn("html.theme-day .scraper-plan-warning-bar", css)

    def test_common_noise_phrases_stripped_and_real_titles_kept(self):
        self.assertEqual(scraper._extract_scraper_title_candidates("监狱星级餐厅 无字片源"), ["监狱星级餐厅"])
        self.assertEqual(
            scraper._extract_scraper_title_candidates("监狱星级餐厅[无水印][国语版].2024.1080p.mkv"),
            ["监狱星级餐厅"],
        )
        self.assertEqual(scraper._extract_scraper_title_candidates("无字片源"), [])
        self.assertTrue(scraper._is_scraper_generic_keyword("无字片源"))
        self.assertEqual(scraper._extract_scraper_title_candidates("无字天书.S01E01.mkv"), ["无字天书"])
        self.assertEqual(scraper._extract_scraper_title_candidates("独家记忆.S01E01.mkv"), ["独家记忆"])

    def test_guoyu_dubbing_and_standalone_chinese_cleaned_but_embedded_kept(self):
        # 复合短语（国语配音/中文字幕等）任意位置清洗；单独“中文/国语”只按独立词清洗，
        # 不误伤“我的中文老师”这类真实片名。
        self.assertEqual(
            scraper._extract_scraper_title_candidates("监狱星级餐厅[国语配音][中文].2024.1080p.mkv"),
            ["监狱星级餐厅"],
        )
        self.assertEqual(
            scraper._extract_scraper_title_candidates("监狱星级餐厅.国语配音.中文.1080p.mkv"),
            ["监狱星级餐厅"],
        )
        self.assertEqual(
            scraper._extract_scraper_title_candidates("监狱星级餐厅.中文.国语.1080p.mkv"),
            ["监狱星级餐厅"],
        )
        self.assertTrue(scraper._is_scraper_generic_keyword("中文"))
        self.assertTrue(scraper._is_scraper_generic_keyword("国语"))
        self.assertEqual(scraper._extract_scraper_title_candidates("中文字幕"), [])
        self.assertFalse(scraper._is_scraper_generic_keyword("我的中文老师"))
        self.assertEqual(
            scraper._extract_scraper_title_candidates("我的中文老师.2024.mp4"),
            ["我的中文老师"],
        )

    def test_batch_matching_busy_shows_spinner_with_items(self):
        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")
        render_batch_source = source[source.index("function renderBatch("):source.index("function toggleBatchInclude(")]
        self.assertIn("scraper-busy-spinner inline", render_batch_source)
        self.assertNotIn("const busyRow = state.batchBusy", render_batch_source)

    def test_common_noise_phrases_strip_release_page_and_movie_word(self):
        self.assertEqual(scraper._extract_scraper_title_candidates("斯特林角 电影 地址发布页"), ["斯特林角"])
        self.assertEqual(scraper._extract_scraper_title_candidates("斯特林角[永久地址].2024.mp4"), ["斯特林角"])
        self.assertEqual(scraper._extract_scraper_title_candidates("电影往事.S01E01.mkv"), ["电影往事"])

    def test_is_scraper_ad_file_classifies_ad_png_txt_and_keeps_poster(self):
        self.assertTrue(scraper._is_scraper_ad_file("更多电视剧集下载请访问高清剧集网官网(www.BPHDTV.com) .png"))
        self.assertTrue(scraper._is_scraper_ad_file("YTSYifyUP (TOR).txt"))
        self.assertTrue(scraper._is_scraper_ad_file("movie.nfo"))
        self.assertFalse(scraper._is_scraper_ad_file("poster.jpg"))

    def test_build_rename_plan_creates_ad_delete_actions_when_enabled(self):
        tmdb = self._tmdb_binding(title="Show", year="2024", media_type="tv")
        files = [
            "Show.S01E01.1080p.mkv",
            "更多电视剧集下载请访问高清剧集网官网(www.BPHDTV.com) .png",
            "YTSYifyUP (TOR).txt",
        ]
        enabled = self._rename_plan_with_files(
            files,
            tmdb,
            folder_name="测试剧集",
            options={"delete_ad_files": True},
        )
        delete_actions = [action for action in enabled["actions"] if action.get("delete")]
        self.assertEqual(len(delete_actions), 2)
        self.assertTrue(all(action["ready"] for action in delete_actions))
        self.assertEqual(enabled["ignored_count"], 0)

        disabled = self._rename_plan_with_files(
            files,
            tmdb,
            folder_name="测试剧集",
            options={"delete_ad_files": False},
        )
        self.assertFalse(any(action.get("delete") for action in disabled["actions"]))
        self.assertEqual(disabled["ignored_count"], 2)

    def test_scraper_job_executes_ad_delete_action(self):
        cfg = self._cfg()
        plan = {
            "base_cid": "root",
            "base_path": "影视",
            "actions": [
                {
                    "entry_id": "f2",
                    "is_dir": False,
                    "old_parent_id": "root",
                    "old_name": "ad.png",
                    "old_path": "影视/ad.png",
                    "new_name": "",
                    "new_path": "",
                    "target_parent_path": "",
                    "file_size": 10,
                    "remote_modified": "",
                    "issue": "",
                    "warning": "",
                    "delete": True,
                    "ready": True,
                }
            ],
        }
        job = scraper.create_scraper_job_from_plan({"plan": plan})
        job_id = int(job["job_id"])
        with (
            patch.object(scraper, "get_config", return_value=cfg),
            patch.object(scraper, "_require_scraper_operation"),
            patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
            patch.object(scraper, "_delete_provider_entries", return_value={"state": True}) as delete_mock,
            patch.object(scraper, "_invalidate_provider_parent"),
        ):
            scraper.run_scraper_job(job_id)

        delete_mock.assert_called_once()
        with sqlite3.connect(self.db_path) as conn:
            status = conn.execute("SELECT status FROM scraper_jobs WHERE id = ?", (job_id,)).fetchone()[0]
            detail = conn.execute("SELECT status_detail FROM scraper_jobs WHERE id = ?", (job_id,)).fetchone()[0]
        self.assertEqual(status, "completed")
        self.assertIn("执行完成：1 项", detail)

    def test_batch_plan_passes_ad_delete_option_to_item_plans(self):
        payload = {
            "provider": "115",
            "base_cid": "root",
            "base_path": "影视",
            "options": {"title_language": "zh", "delete_ad_files": True},
            "items": [
                {
                    "item_index": 1,
                    "name": "文件夹A",
                    "entry": {"id": "d1", "name": "文件夹A", "is_dir": True, "parent_id": "root", "parent_path": "影视", "path": "影视/文件夹A"},
                    "tmdb": {"tmdb_id": 7, "media_type": "movie", "tmdb_media_type": "movie", "tmdb_year": "2024"},
                }
            ],
        }
        captured_options = []

        def fake_binding(binding, cfg):
            return {
                **binding,
                "tmdb_id": 7,
                "tmdb_media_type": "movie",
                "tmdb_title": "新标题",
                "tmdb_year": "2024",
                "tmdb_original_title": "New Title",
                "tmdb_localized_title": "新标题",
                "tmdb_aliases": [],
                "tmdb_total_episodes": 0,
                "tmdb_total_seasons": 0,
                "tmdb_season_episode_map": {},
                "tmdb_episode_mode": "seasonal",
            }

        def fake_item_plan(payload):
            captured_options.append(dict(payload.get("options", {})))
            return {
                "actions": [
                    {
                        "entry_id": "f1",
                        "is_dir": False,
                        "old_parent_id": "root",
                        "old_name": "ad.url",
                        "old_path": "影视/ad.url",
                        "new_name": "",
                        "new_path": "",
                        "target_parent_path": "",
                        "file_size": 10,
                        "remote_modified": "",
                        "issue": "",
                        "warning": "",
                        "delete": True,
                        "ready": True,
                    }
                ],
                "issues": [],
                "warnings": [],
                "unchanged_count": 0,
                "ignored_count": 0,
            }

        with (
            patch.object(scraper, "_require_scraper_operation"),
            patch.object(scraper, "_resolve_batch_tmdb_binding", side_effect=fake_binding),
            patch.object(scraper, "build_scraper_rename_plan", side_effect=fake_item_plan),
            patch.object(
                scraper,
                "get_config",
                return_value={"tmdb_enabled": True, "tmdb_api_key": "key"},
            ),
        ):
            plan = scraper.build_scraper_batch_plan(payload)

        self.assertEqual(captured_options[0].get("delete_ad_files"), True)
        self.assertEqual(plan["total_count"], 1)
        self.assertTrue(plan["actions"][0].get("delete"))

    def test_batch_plan_passes_file_name_mode_to_item_plans(self):
        payload = {
            "provider": "115",
            "base_cid": "root",
            "base_path": "影视",
            "options": {"title_language": "zh", "file_name_mode": "clean"},
            "items": [
                {
                    "item_index": 1,
                    "name": "文件夹A",
                    "entry": {"id": "d1", "name": "文件夹A", "is_dir": True, "parent_id": "root", "parent_path": "影视", "path": "影视/文件夹A"},
                    "tmdb": {"tmdb_id": 7, "media_type": "movie", "tmdb_media_type": "movie", "tmdb_year": "2024"},
                }
            ],
        }
        captured_options = []

        def fake_binding(binding, cfg):
            return {
                **binding,
                "tmdb_id": 7,
                "tmdb_media_type": "movie",
                "tmdb_title": "新标题",
                "tmdb_year": "2024",
                "tmdb_original_title": "New Title",
                "tmdb_localized_title": "新标题",
                "tmdb_aliases": [],
                "tmdb_total_episodes": 0,
                "tmdb_total_seasons": 0,
                "tmdb_season_episode_map": {},
                "tmdb_episode_mode": "seasonal",
            }

        def fake_item_plan(payload):
            captured_options.append(dict(payload.get("options", {})))
            return {
                "actions": [
                    {
                        "entry_id": "f1",
                        "is_dir": False,
                        "old_parent_id": "root",
                        "old_name": "Movie.2024.www.ad.com.1080p.mkv",
                        "old_path": "影视/文件夹A/Movie.2024.www.ad.com.1080p.mkv",
                        "new_name": "Movie.2024.1080p.mkv",
                        "new_path": "影视/文件夹A/Movie.2024.1080p.mkv",
                        "target_parent_path": "文件夹A",
                        "file_size": 10,
                        "remote_modified": "",
                        "issue": "",
                        "warning": "",
                        "ready": True,
                    }
                ],
                "issues": [],
                "warnings": [],
                "unchanged_count": 0,
                "ignored_count": 0,
            }

        with (
            patch.object(scraper, "_require_scraper_operation"),
            patch.object(scraper, "_resolve_batch_tmdb_binding", side_effect=fake_binding),
            patch.object(scraper, "build_scraper_rename_plan", side_effect=fake_item_plan),
            patch.object(
                scraper,
                "get_config",
                return_value={"tmdb_enabled": True, "tmdb_api_key": "key"},
            ),
        ):
            plan = scraper.build_scraper_batch_plan(payload)

        self.assertEqual(captured_options[0].get("file_name_mode"), "clean")
        self.assertEqual(plan["actions"][0]["new_name"], "Movie.2024.1080p.mkv")

    def test_frontend_ad_delete_switch_and_preview_rendering(self):
        html = (ROOT / "templates/partials/pages/scraper.html").read_text(encoding="utf-8")
        self.assertIn('id="scraper-delete-ad-files"', html)

        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")
        self.assertIn("delete_ad_files: !!$('scraper-delete-ad-files')?.checked", source)
        preview_source = source[source.index("const planWarnings = Array.isArray(state.plan?.warnings)"):source.index("function renderPlan()")]
        self.assertIn("'is-delete'", preview_source)
        self.assertIn("'删除'", preview_source)
        self.assertIn("（删除广告文件）", preview_source)
        execute_source = source[source.index("async function executePlan("):source.index("function handleClick(")]
        self.assertIn("删除广告文件", execute_source)

    @staticmethod
    def _library_entry(cid, name, is_dir, parent="影视/影视库"):
        return {
            "id": cid,
            "name": name,
            "is_dir": is_dir,
            "parent_id": "root" if parent == "影视/影视库" else parent,
            "parent_path": parent,
            "path": f"{parent}/{name}",
        }

    def test_scan_splits_library_folder_and_skips_unresolved(self):
        tree = {
            "root": [
                self._library_entry("dA", "电影A", True),
                self._library_entry("dTV", "电视剧", True),
                self._library_entry("f1", "散落.mkv", False),
                self._library_entry("dE", "空夹", True),
                self._library_entry("dC", "分类", True),
            ],
            "dA": [self._library_entry("fA", "movie.mkv", False, "影视/影视库/电影A")],
            "dTV": [self._library_entry("dB", "剧集B", True, "影视/影视库/电视剧")],
            "dB": [self._library_entry("dS01", "Season 01", True, "影视/影视库/电视剧/剧集B")],
            "dS01": [self._library_entry("fB", "剧集B.S01E01.mkv", False, "影视/影视库/电视剧/剧集B/Season 01")],
            "dE": [],
            "dC": [self._library_entry("dE2", "空夹2", True, "影视/影视库/分类")],
            "dE2": [],
        }

        def fake_list(provider, cookie, cid, folders_only=False):
            return {"entries": tree.get(cid, [])}

        root_entry = self._library_entry("root", "影视库", True, "影视")
        with (
            patch.object(scraper, "_require_scraper_operation"),
            patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
            patch.object(scraper, "_list_provider_entries_payload", side_effect=fake_list),
        ):
            result = scraper.scan_scraper_batch_items(
                "115",
                "root",
                "影视",
                [root_entry],
            )

        self.assertEqual([item["name"] for item in result["items"]], ["电影A", "剧集B", "散落.mkv"])
        self.assertEqual([item["item_index"] for item in result["items"]], [1, 2, 3])
        self.assertTrue(any("空夹" in issue and "已跳过" in issue for issue in result["issues"]))
        self.assertTrue(any("分类" in issue and "已跳过" in issue for issue in result["issues"]))

    def test_scan_auto_keeps_show_folder_as_single_item(self):
        root_entry = self._library_entry("root", "电影A", True, "影视")
        tree = {
            "root": [self._library_entry("fA", "movie.mkv", False, "影视/电影A")],
        }

        def fake_list(provider, cookie, cid, folders_only=False):
            return {"entries": tree.get(cid, [])}

        with (
            patch.object(scraper, "_require_scraper_operation"),
            patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
            patch.object(scraper, "_list_provider_entries_payload", side_effect=fake_list),
        ):
            result = scraper.scan_scraper_batch_items(
                "115",
                "root",
                "影视",
                [root_entry],
            )

        self.assertEqual([item["name"] for item in result["items"]], ["电影A"])
        self.assertEqual([item["item_index"] for item in result["items"]], [1])

    def test_scan_auto_splits_custom_library_with_two_show_folders(self):
        root_entry = self._library_entry("root", "我的收藏", True, "影视")
        tree = {
            "root": [
                self._library_entry("dA", "电影A", True, "影视/我的收藏"),
                self._library_entry("dB", "剧集B", True, "影视/我的收藏"),
            ],
            "dA": [self._library_entry("fA", "movie.mkv", False, "影视/我的收藏/电影A")],
            "dB": [self._library_entry("fB", "剧集B.S01E01.mkv", False, "影视/我的收藏/剧集B")],
        }

        def fake_list(provider, cookie, cid, folders_only=False):
            return {"entries": tree.get(cid, [])}

        with (
            patch.object(scraper, "_require_scraper_operation"),
            patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
            patch.object(scraper, "_list_provider_entries_payload", side_effect=fake_list),
        ):
            result = scraper.scan_scraper_batch_items("115", "root", "影视", [root_entry])

        self.assertEqual([item["name"] for item in result["items"]], ["电影A", "剧集B"])

    def test_scan_auto_keeps_multi_season_show_as_single_item(self):
        root_entry = self._library_entry("root", "剧集B", True, "影视")
        tree = {
            "root": [
                self._library_entry("dS01", "Season 01", True, "影视/剧集B"),
                self._library_entry("dS02", "Season 02", True, "影视/剧集B"),
            ],
            "dS01": [self._library_entry("f1", "剧集B.S01E01.mkv", False, "影视/剧集B/Season 01")],
            "dS02": [self._library_entry("f2", "剧集B.S02E01.mkv", False, "影视/剧集B/Season 02")],
        }

        def fake_list(provider, cookie, cid, folders_only=False):
            return {"entries": tree.get(cid, [])}

        with (
            patch.object(scraper, "_require_scraper_operation"),
            patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
            patch.object(scraper, "_list_provider_entries_payload", side_effect=fake_list),
        ):
            result = scraper.scan_scraper_batch_items("115", "root", "影视", [root_entry])

        self.assertEqual([item["name"] for item in result["items"]], ["剧集B"])

    def test_frontend_scan_auto_splits_without_manual_switch(self):
        html = (ROOT / "templates/partials/pages/scraper.html").read_text(encoding="utf-8")
        self.assertNotIn('id="scraper-split-library-folders"', html)
        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")
        scan_source = source[source.index("async function scanBatch("):source.index("async function identifyBatch(")]
        self.assertNotIn("split_folders", scan_source)

    def test_scan_split_mode_single_forces_single_item(self):
        root_entry = self._library_entry("root", "影视库", True, "影视")
        tree = {
            "root": [
                self._library_entry("dA", "电影A", True, "影视/影视库"),
                self._library_entry("dB", "剧集B", True, "影视/影视库"),
            ],
            "dA": [self._library_entry("fA", "movie.mkv", False, "影视/影视库/电影A")],
            "dB": [self._library_entry("fB", "剧集B.S01E01.mkv", False, "影视/影视库/剧集B")],
        }

        def fake_list(provider, cookie, cid, folders_only=False):
            return {"entries": tree.get(cid, [])}

        with (
            patch.object(scraper, "_require_scraper_operation"),
            patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
            patch.object(scraper, "_list_provider_entries_payload", side_effect=fake_list),
        ):
            result = scraper.scan_scraper_batch_items(
                "115",
                "root",
                "影视",
                [root_entry],
                split_mode="single",
            )

        self.assertEqual([item["name"] for item in result["items"]], ["影视库"])

    def test_scan_split_mode_split_forces_split_on_show_folder(self):
        root_entry = self._library_entry("root", "电影A", True, "影视")
        tree = {
            "root": [self._library_entry("fA", "movie.mkv", False, "影视/电影A")],
        }

        def fake_list(provider, cookie, cid, folders_only=False):
            return {"entries": tree.get(cid, [])}

        with (
            patch.object(scraper, "_require_scraper_operation"),
            patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
            patch.object(scraper, "_list_provider_entries_payload", side_effect=fake_list),
        ):
            result = scraper.scan_scraper_batch_items(
                "115",
                "root",
                "影视",
                [root_entry],
                split_mode="split",
            )

        self.assertEqual([item["name"] for item in result["items"]], ["movie.mkv"])

    def test_frontend_split_mode_control_at_top_and_payload(self):
        html = (ROOT / "templates/partials/pages/scraper.html").read_text(encoding="utf-8")
        self.assertIn('id="scraper-split-mode-text"', html)
        self.assertIn('data-split-mode="single"', html)
        self.assertIn('data-split-mode="split"', html)
        summary_index = html.index('id="scraper-batch-summary"')
        list_index = html.index('id="scraper-batch-list"')
        split_index = html.index("scraper-batch-split-mode")
        self.assertGreater(split_index, summary_index)
        self.assertLess(split_index, list_index)

        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")
        self.assertIn("function setBatchSplitMode(", source)
        self.assertIn("function renderBatchSplitMode(", source)
        scan_source = source[source.index("async function scanBatch("):source.index("async function identifyBatch(")]
        self.assertIn("split_mode: state.batchSplitMode || 'auto'", scan_source)
        render_batch_source = source[source.index("function renderBatch("):source.index("function toggleBatchInclude(")]
        self.assertIn("renderBatchSplitMode();", render_batch_source)
        handle_source = source[source.index("function handleClick("):]
        guard_index = handle_source.index("const actionButton = event.target.closest('[data-scraper-action]')")
        self.assertLess(handle_source.index("data-split-mode"), guard_index)

    def test_plan_marks_unchanged_rows_and_excludes_from_actions(self):
        tmdb = self._tmdb_binding(title="Show", year="2024", media_type="tv")
        plan = self._rename_plan_with_files(
            ["Show (2024) - S01E01.mkv"],
            tmdb,
            folder_name="Show (2024)",
            options={"use_season_subfolder": False, "rename_selected_folders": True},
        )
        self.assertEqual(plan["actions"], [])
        self.assertEqual(plan["unchanged_count"], 2)
        unchanged_names = [row["old_name"] for row in plan["unchanged_rows"]]
        self.assertIn("Show (2024)", unchanged_names)
        self.assertIn("Show (2024) - S01E01.mkv", unchanged_names)

    def test_batch_plan_collects_unchanged_rows_with_item_name(self):
        payload = {
            "provider": "115",
            "base_cid": "root",
            "base_path": "影视",
            "options": {"title_language": "zh"},
            "items": [
                {
                    "item_index": 1,
                    "name": "文件夹A",
                    "entry": {"id": "d1", "name": "文件夹A", "is_dir": True, "parent_id": "root", "parent_path": "影视", "path": "影视/文件夹A"},
                    "tmdb": {"tmdb_id": 7, "media_type": "movie", "tmdb_media_type": "movie", "tmdb_year": "2024"},
                }
            ],
        }

        def fake_binding(binding, cfg):
            return {
                **binding,
                "tmdb_id": 7,
                "tmdb_media_type": "movie",
                "tmdb_title": "新标题",
                "tmdb_year": "2024",
                "tmdb_original_title": "New Title",
                "tmdb_localized_title": "新标题",
                "tmdb_aliases": [],
                "tmdb_total_episodes": 0,
                "tmdb_total_seasons": 0,
                "tmdb_season_episode_map": {},
                "tmdb_episode_mode": "seasonal",
            }

        def fake_item_plan(payload):
            return {
                "actions": [],
                "issues": [],
                "warnings": [],
                "unchanged_count": 1,
                "unchanged_rows": [
                    {
                        "old_name": "a.mkv",
                        "old_path": "影视/a.mkv",
                        "new_name": "a.mkv",
                        "new_path": "影视/a.mkv",
                        "is_dir": False,
                    }
                ],
                "ignored_count": 0,
            }

        with (
            patch.object(scraper, "_require_scraper_operation"),
            patch.object(scraper, "_resolve_batch_tmdb_binding", side_effect=fake_binding),
            patch.object(scraper, "build_scraper_rename_plan", side_effect=fake_item_plan),
            patch.object(
                scraper,
                "get_config",
                return_value={"tmdb_enabled": True, "tmdb_api_key": "key"},
            ),
        ):
            plan = scraper.build_scraper_batch_plan(payload)

        self.assertEqual(plan["actions"], [])
        self.assertEqual(len(plan["unchanged_rows"]), 1)
        self.assertEqual(plan["unchanged_rows"][0]["item_name"], "文件夹A")

    def test_preview_renders_unchanged_rows_as_skipped(self):
        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")
        preview_source = source[source.index("const planWarnings = Array.isArray(state.plan?.warnings)"):source.index("function renderPlan()")]
        self.assertIn("state.plan?.unchanged_rows", preview_source)
        self.assertIn("is-unchanged", preview_source)
        self.assertIn("无变化", preview_source)

        css = (ROOT / "static/css/index.css").read_text(encoding="utf-8")
        self.assertIn(".scraper-preview-row.is-unchanged", css)
        self.assertIn("html.theme-day .scraper-preview-row.is-unchanged", css)
        self.assertIn(".scraper-preview-status.is-muted", css)

    def test_scan_merges_loose_tv_episode_files_into_one_item(self):
        entries = []
        for index in range(1, 21):
            name = f"逐玉.S01E{index:02d}.1080p.mkv"
            entries.append(
                {
                    "id": f"f{index}",
                    "name": name,
                    "is_dir": False,
                    "parent_id": "root",
                    "parent_path": "影视/剧集",
                    "path": f"影视/剧集/{name}",
                }
            )
        entries.append(
            {"id": "m1", "name": "MovieA.mkv", "is_dir": False, "parent_id": "root", "parent_path": "影视/电影", "path": "影视/电影/MovieA.mkv"}
        )
        entries.append(
            {"id": "m2", "name": "MovieB.mkv", "is_dir": False, "parent_id": "root", "parent_path": "影视/电影", "path": "影视/电影/MovieB.mkv"}
        )

        with (
            patch.object(scraper, "_require_scraper_operation"),
            patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
        ):
            result = scraper.scan_scraper_batch_items("115", "root", "影视", entries)

        names = [item["name"] for item in result["items"]]
        self.assertEqual(names, ["MovieA.mkv", "MovieB.mkv", "逐玉"])
        merged = next(item for item in result["items"] if item["name"] == "逐玉")
        self.assertEqual(len(merged["files"]), 20)
        self.assertEqual(len(merged["entries"]), 20)

    def test_batch_plan_expands_merged_tv_item_to_per_file_entries(self):
        files = [
            {
                "id": f"f{index}",
                "name": f"逐玉.S01E{index:02d}.1080p.mkv",
                "is_dir": False,
                "parent_id": "root",
                "parent_path": "影视/剧集",
                "path": f"影视/剧集/逐玉.S01E{index:02d}.1080p.mkv",
            }
            for index in range(1, 4)
        ]
        captured_entries = []
        payload = {
            "provider": "115",
            "base_cid": "root",
            "base_path": "影视",
            "options": {"title_language": "zh"},
            "items": [
                {
                    "item_index": 1,
                    "name": "逐玉",
                    "entry": files[0],
                    "entries": files,
                    "tmdb": {"tmdb_id": 7, "media_type": "tv", "tmdb_media_type": "tv", "tmdb_year": "2026"},
                }
            ],
        }

        def fake_binding(binding, cfg):
            return {
                **binding,
                "tmdb_id": 7,
                "tmdb_media_type": "tv",
                "tmdb_title": "逐玉",
                "tmdb_year": "2026",
                "tmdb_original_title": "Zhu Yu",
                "tmdb_localized_title": "逐玉",
                "tmdb_aliases": [],
                "tmdb_total_episodes": 20,
                "tmdb_total_seasons": 1,
                "tmdb_season_episode_map": {"1": 20},
                "tmdb_episode_mode": "seasonal",
            }

        def fake_item_plan(plan_payload):
            captured_entries.extend(list(plan_payload.get("entries", [])))
            return {
                "actions": [
                    {
                        "action_index": index,
                        "entry_id": files[index - 1]["id"],
                        "is_dir": False,
                        "old_parent_id": "root",
                        "old_name": files[index - 1]["name"],
                        "old_path": files[index - 1]["path"],
                        "new_name": f"逐玉 (2026) - S01E0{index}.mkv",
                        "new_path": files[index - 1]["path"],
                        "target_parent_path": "",
                        "file_size": 0,
                        "remote_modified": "",
                        "issue": "",
                        "warning": "",
                        "ready": True,
                    }
                    for index in range(1, 4)
                ],
                "issues": [],
                "warnings": [],
                "unchanged_count": 0,
                "ignored_count": 0,
            }

        with (
            patch.object(scraper, "_require_scraper_operation"),
            patch.object(scraper, "_resolve_batch_tmdb_binding", side_effect=fake_binding),
            patch.object(scraper, "build_scraper_rename_plan", side_effect=fake_item_plan),
            patch.object(
                scraper,
                "get_config",
                return_value={"tmdb_enabled": True, "tmdb_api_key": "key"},
            ),
        ):
            plan = scraper.build_scraper_batch_plan(payload)

        self.assertEqual(len(captured_entries), 3)
        self.assertEqual(plan["total_count"], 3)

    def test_tmdb_binding_keeps_poster_url_for_manual_binds(self):
        binding = scraper.build_tmdb_task_binding(
            {
                "id": 1,
                "media_type": "movie",
                "title": "星际穿越",
                "original_title": "Interstellar",
                "localized_title": "星际穿越",
                "year": "2014",
                "poster_url": "https://example.com/poster.jpg",
                "aliases": [],
                "season_episode_map": {},
                "episode_mode": "seasonal",
            },
            media_type="movie",
        )
        self.assertEqual(binding["tmdb_poster_url"], "https://example.com/poster.jpg")

    def test_batch_binding_row_renders_poster_on_right(self):
        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")
        render_batch_item_source = source[source.index("function renderBatchItem("):source.index("function renderBatch(")]
        self.assertIn("scraper-batch-poster", render_batch_item_source)
        self.assertIn("binding.tmdb_poster_url || binding.poster_url", render_batch_item_source)
        self.assertIn("scraper-batch-poster-col", render_batch_item_source)
        self.assertIn("scraper-batch-title", render_batch_item_source)

        css = (ROOT / "static/css/index.css").read_text(encoding="utf-8")
        self.assertIn(".scraper-batch-poster", css)
        self.assertIn(".scraper-batch-poster-col", css)
        self.assertIn(".scraper-batch-title", css)
        self.assertIn("html.theme-day .scraper-batch-poster", css)

    def test_batch_dialog_header_fixed_and_body_scrolls(self):
        html = (ROOT / "templates/partials/pages/scraper.html").read_text(encoding="utf-8")
        self.assertIn('class="scraper-batch-dialog-body"', html)
        css = (ROOT / "static/css/index.css").read_text(encoding="utf-8")
        self.assertIn(".scraper-batch-dialog .scraper-panel-head", css)
        self.assertIn(".scraper-batch-dialog-body", css)
        self.assertIn("flex-direction: column;", css)
        self.assertIn("overflow: hidden;", css)
        self.assertIn("html.theme-day .scraper-batch-dialog .scraper-panel-head", css)

    def test_monitor_task_normalizes_auto_scrape_on_new(self):
        from app.core import normalize_task

        base = {"name": "影视监控", "scan_path": "/115/一级", "target_path": "媒体库"}
        self.assertFalse(normalize_task(base)["auto_scrape_on_new"])
        self.assertTrue(normalize_task({**base, "auto_scrape_on_new": True})["auto_scrape_on_new"])
        self.assertEqual(normalize_task(base)["auto_scrape_options"], {})
        self.assertEqual(
            normalize_task({**base, "auto_scrape_options": {"file_name_mode": "keep"}})["auto_scrape_options"],
            {"file_name_mode": "keep"},
        )
        self.assertEqual(
            normalize_task({**base, "auto_scrape_options": "not-a-dict"})["auto_scrape_options"],
            {},
        )

    def test_auto_scrape_uses_task_auto_scrape_options(self):
        cfg = self._cfg()
        items = [
            {
                "id": "f1",
                "fid": "f1",
                "name": "逐玉.S01E01.mkv",
                "size": 1024,
                "remote_rel": "一级/逐玉.S01E01.mkv",
                "local_rel": "媒体库/一级/逐玉.S01E01.mkv",
            }
        ]
        scan_item = {
            "item_index": 1,
            "name": "逐玉",
            "entry": {
                "id": "f1",
                "name": "逐玉.S01E01.mkv",
                "is_dir": False,
                "parent_id": "cid1",
                "parent_path": "一级",
                "path": "一级/逐玉.S01E01.mkv",
            },
            "files": [{"id": "f1"}],
        }
        captured_options = []

        def fake_plan(payload):
            captured_options.append(dict(payload.get("options", {})))
            return {"ready_count": 1}

        with (
            patch.object(scraper, "_walk_existing_folder", return_value=("cid1", True)),
            patch.object(scraper, "scan_scraper_batch_items", return_value={"items": [scan_item]}),
            patch.object(
                scraper,
                "identify_scraper_batch_items",
                return_value={
                    "results": [
                        {
                            "item_index": 1,
                            "status": "auto",
                            "auto_pick": {"id": 1, "media_type": "tv", "title": "逐玉", "year": "2026"},
                        }
                    ]
                },
            ),
            patch.object(scraper, "build_scraper_batch_plan", side_effect=fake_plan),
            patch.object(scraper, "create_scraper_job_from_plan", return_value={"job_id": 9}),
            patch.object(scraper, "run_scraper_job"),
        ):
            message = monitor._auto_scrape_new_media_items(
                cfg,
                self._task(auto_scrape_options={"file_name_mode": "keep", "delete_ad_files": True}),
                items,
            )
        self.assertIn("已自动整理 1 项", message)
        self.assertEqual(captured_options[0]["file_name_mode"], "keep")
        self.assertEqual(captured_options[0]["delete_ad_files"], True)

        captured_options.clear()
        with (
            patch.object(scraper, "_walk_existing_folder", return_value=("cid1", True)),
            patch.object(scraper, "scan_scraper_batch_items", return_value={"items": [scan_item]}),
            patch.object(
                scraper,
                "identify_scraper_batch_items",
                return_value={
                    "results": [
                        {
                            "item_index": 1,
                            "status": "auto",
                            "auto_pick": {"id": 1, "media_type": "tv", "title": "逐玉", "year": "2026"},
                        }
                    ]
                },
            ),
            patch.object(scraper, "build_scraper_batch_plan", side_effect=fake_plan),
            patch.object(scraper, "create_scraper_job_from_plan", return_value={"job_id": 9}),
            patch.object(scraper, "run_scraper_job"),
        ):
            monitor._auto_scrape_new_media_items(cfg, self._task(), items)
        self.assertEqual(captured_options[0]["title_language"], "zh")
        self.assertEqual(captured_options[0]["delete_ad_files"], False)
        self.assertNotIn("file_name_mode", captured_options[0])

    def test_auto_scrape_helper_skips_non_auto_and_runs_auto(self):
        cfg = self._cfg()
        items = [
            {
                "id": "f1",
                "fid": "f1",
                "name": "逐玉.S01E01.mkv",
                "size": 1024,
                "remote_rel": "一级/逐玉.S01E01.mkv",
                "local_rel": "媒体库/一级/逐玉.S01E01.mkv",
            }
        ]
        scan_item = {
            "item_index": 1,
            "name": "逐玉",
            "entry": {
                "id": "f1",
                "name": "逐玉.S01E01.mkv",
                "is_dir": False,
                "parent_id": "cid1",
                "parent_path": "一级",
                "path": "一级/逐玉.S01E01.mkv",
            },
            "files": [{"id": "f1"}],
        }
        walk_calls = []
        scan_entries_calls = []

        def fake_walk(provider, cookie, base_cid, folder_path, **kwargs):
            walk_calls.append(folder_path)
            return ("cid1", True)

        def fake_scan(provider, base_cid, base_path, entries, **kwargs):
            scan_entries_calls.append(list(entries))
            return {"items": [scan_item]}

        with (
            patch.object(scraper, "_walk_existing_folder", side_effect=fake_walk),
            patch.object(scraper, "scan_scraper_batch_items", side_effect=fake_scan),
            patch.object(
                scraper,
                "identify_scraper_batch_items",
                return_value={"results": [{"item_index": 1, "status": "manual", "auto_pick": None}]},
            ),
            patch.object(scraper, "build_scraper_batch_plan") as plan_mock,
            patch.object(scraper, "create_scraper_job_from_plan") as job_mock,
            patch.object(scraper, "run_scraper_job") as run_mock,
        ):
            message = monitor._auto_scrape_new_media_items(cfg, self._task(), items)
        self.assertIn("无高置信度", message)
        plan_mock.assert_not_called()
        job_mock.assert_not_called()
        run_mock.assert_not_called()
        self.assertEqual(walk_calls, ["Media/一级", "Media"])
        self.assertTrue(scan_entries_calls)
        folder_entry = scan_entries_calls[0][0]
        self.assertTrue(folder_entry["is_dir"])
        self.assertEqual(folder_entry["name"], "一级")
        self.assertEqual(folder_entry["path"], "Media/一级")
        self.assertEqual(folder_entry["parent_id"], "cid1")

        with (
            patch.object(scraper, "_walk_existing_folder", return_value=("cid1", True)),
            patch.object(scraper, "scan_scraper_batch_items", return_value={"items": [scan_item]}),
            patch.object(
                scraper,
                "identify_scraper_batch_items",
                return_value={
                    "results": [
                        {
                            "item_index": 1,
                            "status": "auto",
                            "auto_pick": {"id": 1, "media_type": "tv", "title": "逐玉", "year": "2026"},
                        }
                    ]
                },
            ),
            patch.object(scraper, "build_scraper_batch_plan", return_value={"ready_count": 2}),
            patch.object(scraper, "create_scraper_job_from_plan", return_value={"job_id": 9}),
            patch.object(scraper, "run_scraper_job") as run_mock_auto,
        ):
            message = monitor._auto_scrape_new_media_items(cfg, self._task(), items)
        self.assertIn("已自动整理 2 项", message)
        run_mock_auto.assert_called_once_with(9)

    def test_monitor_task_modal_has_auto_scrape_toggle(self):
        html = (ROOT / "templates/partials/modals/monitor.html").read_text(encoding="utf-8")
        self.assertIn('id="monitor_auto_scrape_on_new"', html)
        self.assertIn('id="monitor-auto-scrape-options"', html)
        self.assertIn('id="monitor_asc_file_name_mode"', html)
        self.assertIn('id="monitor_asc_rename_folders"', html)
        self.assertIn('id="monitor_asc_season_subfolder"', html)
        self.assertIn('id="monitor_asc_include_tmdb_id"', html)
        self.assertIn('id="monitor_asc_delete_ad_files"', html)
        self.assertIn('data-monitor-asc-tag="audio"', html)
        index_source = (ROOT / "static/js/index.js").read_text(encoding="utf-8")
        self.assertIn("auto_scrape_on_new: document.getElementById('monitor_auto_scrape_on_new').checked", index_source)
        self.assertIn("auto_scrape_options: collectMonitorAutoScrapeOptions()", index_source)
        self.assertIn("monitor_auto_scrape_on_new').checked = !!task.auto_scrape_on_new", index_source)
        self.assertIn("applyMonitorAutoScrapeOptions(task.auto_scrape_options)", index_source)
        self.assertIn("function syncMonitorAutoScrapeOptions(", index_source)
        self.assertIn("function collectMonitorAutoScrapeOptions(", index_source)

    def test_manual_required_scopes_include_path_details(self):
        from app.services.monitor_changes import get_manual_required_monitor_scopes

        cfg = self._cfg()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO monitor_change_events(
                    dedupe_key, provider, operation, old_path, new_path, entry_snapshot_json,
                    task_name, source_action, status, created_at, updated_at
                ) VALUES (?, '115', 'rename', ?, ?, '{}', '影视监控', 'test', 'manual_required', '2026-08-13 10:00:00', '2026-08-13 10:00:00')
                """,
                ("mr-1", "/115/Media/旧夹", "/115/Media/二级/新夹"),
            )
        scopes = get_manual_required_monitor_scopes("影视监控", cfg=cfg)
        self.assertEqual(len(scopes), 1)
        self.assertEqual(scopes[0]["new_path"], "Media/二级/新夹")
        self.assertEqual(scopes[0]["old_path"], "Media/旧夹")
        self.assertEqual(scopes[0]["operation"], "rename")
        self.assertEqual(scopes[0]["remote_path"], "/115/Media/二级/新夹")
        self.assertTrue(scopes[0]["created_at"])

    def test_manual_required_modal_and_link_wiring(self):
        html = (ROOT / "templates/partials/modals/monitor.html").read_text(encoding="utf-8")
        self.assertIn('id="monitor-manual-required-modal"', html)
        self.assertIn('id="monitor-manual-required-list"', html)
        self.assertIn("rescanMonitorManualRequired()", html)

        index_source = (ROOT / "static/js/index.js").read_text(encoding="utf-8")
        self.assertIn("monitor-manual-required-link", index_source)
        self.assertIn("function openMonitorManualRequired(", index_source)
        self.assertIn("function closeMonitorManualRequired()", index_source)
        self.assertIn("async function rescanMonitorManualRequired()", index_source)
        self.assertIn("/monitor/manual-required?task_name=", index_source)
        self.assertIn("window.openMonitorManualRequired = openMonitorManualRequired;", index_source)
        self.assertIn("manualRequiredTaskArg", index_source)
        self.assertNotIn("openMonitorManualRequired('${escapeHtml(taskKey)}')", index_source)
        self.assertIn("OPERATION_LABELS", index_source)
        self.assertIn("该目录变更时内容清单未确认", index_source)

        css = (ROOT / "static/css/index.css").read_text(encoding="utf-8")
        self.assertIn(".monitor-manual-required-link", css)

    def test_batch_item_search_renders_path_selection_and_shared_search(self):
        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")
        self.assertIn("function renderBatchPathSelection(", source)
        self.assertIn("const pathHtml = renderBatchPathSelection(index);", source)
        self.assertIn("async function fetchTmdbSearch(", source)
        self.assertIn("state.manualResults = await fetchTmdbSearch(query, mediaType);", source)

    def test_batch_panel_contains_naming_options(self):
        html_path = ROOT / "templates/partials/pages/scraper.html"
        html = html_path.read_text(encoding="utf-8")
        batch_index = html.index('id="scraper-batch-panel"')
        build_index = html.index('id="scraper-batch-build-plan-btn"')
        for option_id in (
            "scraper-preserve-file-info",
            "scraper-include-tmdb-id",
            "scraper-use-season-subfolder",
            "scraper-rename-selected-folders",
        ):
            self.assertIn(option_id, html)
            self.assertGreater(html.index(option_id), batch_index)
            self.assertLess(html.index(option_id), build_index)

    def test_render_batch_syncs_naming_options(self):
        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")
        self.assertIn("function syncBatchOptionControls(", source)
        render_batch_source = source[source.index("function renderBatch("):source.index("function toggleBatchInclude(")]
        self.assertIn("syncBatchOptionControls();", render_batch_source)

    def test_folder_rename_on_renames_folder_and_moves_files(self):
        tmdb = self._tmdb_binding(title="逐玉", year="2026", media_type="tv")
        plan = self._rename_plan_with_files(
            ["Show.S01E01.mkv"],
            tmdb,
            folder_name="旧剧集名",
            options={"rename_selected_folders": True},
        )
        folder_actions = [action for action in plan["actions"] if action["is_dir"]]
        self.assertEqual([action["new_name"] for action in folder_actions], ["逐玉 (2026)"])
        file_actions = [action for action in plan["actions"] if not action["is_dir"]]
        self.assertTrue(file_actions[0]["new_path"].startswith("影视/逐玉 (2026)/Season 01/"))

    def test_folder_rename_off_keeps_files_inside_source_folder(self):
        tmdb = self._tmdb_binding(title="逐玉", year="2026", media_type="tv")
        plan = self._rename_plan_with_files(
            ["Show.S01E01.mkv", "Show.S01E02.mkv"],
            tmdb,
            folder_name="旧剧集名",
            options={"rename_selected_folders": False},
        )
        folder_actions = [action for action in plan["actions"] if action["is_dir"]]
        self.assertEqual(folder_actions, [])
        file_actions = [action for action in plan["actions"] if not action["is_dir"]]
        self.assertTrue(all(action["new_path"].startswith("影视/旧剧集名/Season 01/") for action in file_actions))
        self.assertTrue(all("逐玉 (2026) - S01E" in action["new_path"] for action in file_actions))

    def test_batch_folder_rename_with_tmdb_id_applies_to_multiple_folders(self):
        tmdb = self._tmdb_binding(title="逐玉", year="2026", media_type="tv")
        options = {"include_tmdb_id": True, "rename_selected_folders": True}
        plan_a = self._rename_plan_with_files(["Show.S01E01.mkv"], tmdb, folder_name="剧集A", options=options)
        plan_b = self._rename_plan_with_files(["Show.S01E01.mkv"], tmdb, folder_name="剧集B", options=options)
        folder_a = next(action for action in plan_a["actions"] if action["is_dir"])
        folder_b = next(action for action in plan_b["actions"] if action["is_dir"])
        self.assertEqual(folder_a["new_name"], "逐玉 (2026) [tmdbid-100]")
        self.assertEqual(folder_b["new_name"], "逐玉 (2026) [tmdbid-100]")

    # ------------------------------------------------------------------
    # 文件命名方式：keep（保持原名）/ clean（仅清理广告）/ standard（标准重命名）
    # ------------------------------------------------------------------

    def test_file_name_mode_keep_keeps_names_and_only_renames_folder(self):
        tmdb = self._tmdb_binding(title="逐玉", year="2026", media_type="tv")
        plan = self._rename_plan_with_files(
            ["Show.S01E01.mkv", "Show.S01E02.mkv"],
            tmdb,
            folder_name="旧剧集名",
            options={
                "rename_selected_folders": True,
                "use_season_subfolder": False,
                "file_name_mode": "keep",
            },
        )
        self.assertEqual(plan["options"]["file_name_mode"], "keep")
        folder_actions = [action for action in plan["actions"] if action["is_dir"]]
        self.assertEqual([action["new_name"] for action in folder_actions], ["逐玉 (2026)"])
        self.assertEqual(plan["unchanged_count"], 2)
        self.assertEqual(
            {row["old_name"] for row in plan["unchanged_rows"]},
            {"Show.S01E01.mkv", "Show.S01E02.mkv"},
        )
        file_actions = [action for action in plan["actions"] if not action["is_dir"]]
        self.assertEqual(file_actions, [])

    def test_file_name_mode_keep_with_season_subfolder_moves_files_keeping_names(self):
        tmdb = self._tmdb_binding(title="逐玉", year="2026", media_type="tv")
        plan = self._rename_plan_with_files(
            ["Show.S01E01.mkv"],
            tmdb,
            folder_name="旧剧集名",
            options={
                "rename_selected_folders": True,
                "use_season_subfolder": True,
                "file_name_mode": "keep",
            },
        )
        file_actions = [action for action in plan["actions"] if not action["is_dir"]]
        self.assertEqual(len(file_actions), 1)
        self.assertTrue(file_actions[0]["new_path"].startswith("影视/逐玉 (2026)/Season 01/"))
        self.assertEqual(file_actions[0]["new_name"], "Show.S01E01.mkv")

    def test_file_name_mode_clean_strips_ad_but_keeps_original_info(self):
        tmdb = self._tmdb_binding(title="逐玉", year="2026", media_type="tv")
        plan = self._rename_plan_with_files(
            ["Movie.2024.www.ad.com.1080p.mkv"],
            tmdb,
            folder_name="旧剧集名",
            options={
                "rename_selected_folders": True,
                "use_season_subfolder": False,
                "file_name_mode": "clean",
            },
        )
        file_actions = [action for action in plan["actions"] if not action["is_dir"]]
        self.assertEqual(len(file_actions), 1)
        self.assertEqual(file_actions[0]["new_name"], "Movie.2024.1080p.mkv")
        self.assertEqual(file_actions[0]["target_parent_path"], "旧剧集名")

    def test_file_name_mode_clean_without_ad_is_unchanged(self):
        tmdb = self._tmdb_binding(title="逐玉", year="2026", media_type="tv")
        plan = self._rename_plan_with_files(
            ["Show.S01E01.1080p.mkv"],
            tmdb,
            folder_name="旧剧集名",
            options={
                "rename_selected_folders": True,
                "use_season_subfolder": False,
                "file_name_mode": "clean",
            },
        )
        self.assertEqual(plan["unchanged_count"], 1)
        self.assertEqual(plan["unchanged_rows"][0]["new_name"], "Show.S01E01.1080p.mkv")

    def test_file_name_mode_default_stays_standard(self):
        tmdb = self._tmdb_binding(title="逐玉", year="2026", media_type="tv")
        plan = self._rename_plan_with_files(
            ["Show.S01E01.mkv"],
            tmdb,
            folder_name="旧剧集名",
            options={"rename_selected_folders": True},
        )
        self.assertEqual(plan["options"]["file_name_mode"], "standard")
        file_actions = [action for action in plan["actions"] if not action["is_dir"]]
        self.assertIn("逐玉 (2026) - S01E01", file_actions[0]["new_path"])

    def test_clean_scraper_filename_strips_ad_sites_only(self):
        cases = [
            ("Movie.2024.www.ad.com.1080p.mkv", "Movie.2024.1080p.mkv"),
            ("www.UIndex.org - Movie.2024.mkv", "Movie.2024.mkv"),
            ("UIndex.org - Movie.2024.mkv", "Movie.2024.mkv"),
            ("高清剧集网发布.Movie.2024.mkv", "Movie.2024.mkv"),
            ("Movie.2024.mkv", "Movie.2024.mkv"),
            ("Show.S01E01.1080p.mkv", "Show.S01E01.1080p.mkv"),
        ]
        for raw, want in cases:
            self.assertEqual(scraper._clean_scraper_filename(raw), want, raw)

    # ------------------------------------------------------------------
    # 剧集集数解析：EP02 不被年份抢占、纯数字序号可识别
    # ------------------------------------------------------------------

    def test_episode_code_regex_does_not_treat_word_ending_e_as_episode(self):
        from app.services.subscription_episode import parse_resource_episode_meta

        jade = "Pursuit.of.Jade.2026.EP02.HD1080P.X264.AAC.Mandarin.CHS.XLYS.mkv"
        meta = parse_resource_episode_meta({"title": jade, "raw_text": jade})
        self.assertEqual(meta["episode"], 2)
        self.assertEqual(meta["season"], 0)

        movie = parse_resource_episode_meta({"title": "Movie.2012.1080p.mkv", "raw_text": "Movie.2012.1080p.mkv"})
        self.assertEqual(movie["episode"], 0)

    def test_scraper_auto_episode_info_parses_ep02_without_year_collision(self):
        task = {
            "media_type": "tv",
            "season": 1,
            "multi_season_mode": False,
            "anime_mode": False,
            "tmdb_total_episodes": 24,
            "tmdb_total_seasons": 1,
            "tmdb_season_episode_map": {"1": 24},
            "tmdb_episode_mode": "seasonal",
        }
        names = [
            "Pursuit.of.Jade.2026.EP02.HD1080P.X264.AAC.Mandarin.CHS.XLYS.mkv",
            "Pursuit.of.Jade.2026.EP03.HD1080P.X264.AAC.Mandarin.CHS.XLYS.mkv",
        ]
        codes = []
        for name in names:
            info, issue = scraper._resolve_scraper_auto_episode_info(
                task,
                {"name": name, "path": name, "parent_path": "逐玉"},
                1,
            )
            self.assertEqual(issue, "")
            code, _ = scraper._format_tv_episode_code(info)
            codes.append(code)
        self.assertEqual(codes, ["S01E02", "S01E03"])

    def test_looks_like_tv_detects_bare_numeric_episode_files(self):
        self.assertTrue(scraper._looks_like_tv(["逐玉 (2026)", "01.mkv", "02.mkv"]))
        self.assertTrue(scraper._looks_like_tv(["Show", "01.1080p.mkv", "02.1080p.mkv"]))
        self.assertFalse(scraper._looks_like_tv(["电影库", "2012.1080p.mkv", "2013.1080p.mkv"]))

    def test_extract_numeric_episode_handles_number_plus_episode_title(self):
        self.assertEqual(scraper._extract_numeric_episode_from_filename("1. The Hedge Knight.mkv"), 1)
        self.assertEqual(scraper._extract_numeric_episode_from_filename("01 - Title.mkv"), 1)
        self.assertEqual(scraper._extract_numeric_episode_from_filename("02_Title.mkv"), 2)
        self.assertEqual(scraper._extract_numeric_episode_from_filename("01.1080p.mkv"), 1)
        self.assertEqual(scraper._extract_numeric_episode_from_filename("12 Monkeys.mkv"), 0)
        self.assertEqual(scraper._extract_numeric_episode_from_filename("2012.1080p.mkv"), 0)
        self.assertEqual(scraper._extract_numeric_episode_from_filename("2012.mkv"), 0)

    def test_scraper_auto_episode_info_parses_numbered_episode_title(self):
        task = {
            "media_type": "tv",
            "season": 1,
            "multi_season_mode": False,
            "anime_mode": False,
            "tmdb_total_episodes": 6,
            "tmdb_total_seasons": 1,
            "tmdb_season_episode_map": {"1": 6},
            "tmdb_episode_mode": "seasonal",
        }
        folder = "A.Knight.of.the.Seven.Kingdoms.S01.2160p.UHD.BluRay.REMUX.DV.HDR.HEVC.TrueHD.7.1.Atmos-SpaceHD13"
        info, issue = scraper._resolve_scraper_auto_episode_info(
            task,
            {"name": "1. The Hedge Knight.mkv", "path": "1. The Hedge Knight.mkv", "parent_path": folder},
            1,
        )
        self.assertEqual(issue, "")
        code, _ = scraper._format_tv_episode_code(info)
        self.assertEqual(code, "S01E01")

    def test_extract_title_candidates_strips_cn_ad_site_phrases(self):
        self.assertEqual(
            scraper._extract_scraper_title_candidates("高清剧集网发布 剧名.S01E01.1080p.mkv"),
            ["剧名"],
        )
        self.assertEqual(
            scraper._extract_scraper_title_candidates("【高清剧集网 www.gdjq.com 发布】剧名.S01E01.mkv"),
            ["剧名"],
        )
        self.assertEqual(
            scraper._extract_scraper_title_candidates("剧名.S01E01.1080p.高清剧集网发布.mkv"),
            ["剧名"],
        )
        self.assertEqual(scraper._extract_scraper_title_candidates("高清剧集网发布"), [])
        self.assertEqual(
            scraper._extract_scraper_title_candidates("蜘蛛侠纵横宇宙.S01E01.1080p.mkv"),
            ["蜘蛛侠纵横宇宙"],
        )

    def test_scraper_generic_keyword_filters_cn_ad_site_phrases(self):
        self.assertTrue(scraper._is_scraper_generic_keyword("高清剧集网发布"))
        self.assertTrue(scraper._is_scraper_generic_keyword("电影天堂"))
        self.assertFalse(scraper._is_scraper_generic_keyword("蜘蛛侠纵横宇宙"))

    def test_extract_title_candidates_splits_mixed_language_and_strips_subtitle_tags(self):
        name = "【高清剧集网发布 www.DDHDTV.com】男子心如钻[全30集][简繁英字幕].Strong.Will.S01.1080p.NF.WEB-DL.AAC.2.0.H.264-BlackTV"
        candidates = scraper._extract_scraper_title_candidates(name)
        self.assertEqual(candidates[0], "男子心如钻")
        self.assertIn("Strong Will", candidates)
        self.assertTrue(all("简繁英字幕" not in candidate and "www" not in candidate.lower() for candidate in candidates))
        cleaned = scraper._clean_search_title(name)
        self.assertNotIn("简繁英字幕", cleaned)
        self.assertNotIn("www", cleaned.lower())
        self.assertEqual(scraper._extract_scraper_title_candidates("【XX字幕组】剧名.S01E01.mkv"), ["剧名"])
        self.assertEqual(scraper._extract_scraper_title_candidates("男子心如钻[中英字幕].S01E01.mkv"), ["男子心如钻"])


class ScraperBatchJobTitleTest(unittest.TestCase):
    """批量任务任务名按实际执行的条目展示 TMDB 标题。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "data.db")
        self.original_db_path = db.DB_PATH
        self.original_db_ensured = db._DB_ENSURED
        db.DB_PATH = self.db_path
        db._DB_ENSURED = False
        db.ensure_db()

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        db._DB_ENSURED = self.original_db_ensured
        self.tmpdir.cleanup()

    @staticmethod
    def _job_payload(items, actions, tmdb=None):
        plan = {
            "provider": "115",
            "base_cid": "root",
            "base_path": "影视",
            "options": {},
            "tmdb": tmdb
            or {
                "batch": True,
                "title": "批量整理",
                "tmdb_id": 0,
                "media_type": "movie",
            },
            "items": items,
            "actions": actions,
        }
        return {"plan": plan}

    @staticmethod
    def _action(index, item_index=1):
        return {
            "action_index": index,
            "entry_id": f"f{index}",
            "is_dir": False,
            "old_path": f"影视/旧名{index}.mkv",
            "new_path": f"影视/新名 (2026) - S01E{index:02d}.mkv",
            "item_index": item_index,
            "item_name": f"条目{item_index}",
            "ready": True,
        }

    def _job_title(self, payload):
        result = scraper.create_scraper_job_from_plan(payload)
        job_id = int(result["job_id"])
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT tmdb_json FROM scraper_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        return json.loads(row[0])["title"]

    def test_single_executed_item_uses_tmdb_title_with_year(self):
        items = [{"item_index": 1, "name": "旧名1", "title": "云秀行", "year": "2026"}]
        payload = self._job_payload(items, [self._action(0, item_index=1)])

        self.assertEqual(self._job_title(payload), "云秀行 (2026)")

    def test_multiple_executed_items_use_first_title_with_count(self):
        items = [
            {"item_index": 1, "name": "旧名1", "title": "云秀行", "year": "2026"},
            {"item_index": 2, "name": "旧名2", "title": "大奉打更人", "year": "2024"},
        ]
        payload = self._job_payload(
            items,
            [self._action(0, item_index=1), self._action(1, item_index=2)],
        )

        self.assertEqual(self._job_title(payload), "云秀行 等 2 项")

    def test_partial_execution_names_after_executed_items_only(self):
        items = [
            {"item_index": 1, "name": "旧名1", "title": "云秀行", "year": "2026"},
            {"item_index": 2, "name": "旧名2", "title": "大奉打更人", "year": "2024"},
            {"item_index": 3, "name": "旧名3", "title": "凡人修仙传", "year": "2025"},
        ]
        payload = self._job_payload(
            items,
            [self._action(0, item_index=1), self._action(1, item_index=3)],
        )

        self.assertEqual(self._job_title(payload), "云秀行 等 2 项")

    def test_non_batch_job_keeps_binding_title(self):
        tmdb = {
            "tmdb_id": 239901,
            "media_type": "tv",
            "tmdb_title": "云秀行",
            "tmdb_year": "2026",
            "title": "云秀行",
        }
        payload = self._job_payload([], [self._action(0)], tmdb=tmdb)

        self.assertEqual(self._job_title(payload), "云秀行")

    def test_batch_without_item_summaries_keeps_default_title(self):
        payload = self._job_payload([], [self._action(0)])

        self.assertEqual(self._job_title(payload), "批量整理")

    # ------------------------------------------------------------------
    # 批量整理选项记忆（服务端、按网盘分开）
    # ------------------------------------------------------------------

    def test_batch_preferences_save_get_roundtrip_per_provider(self):
        options = {
            "split_mode": "split",
            "title_language": "zh",
            "season": "9",
            "episode_mode": "absolute",
            "include_tmdb_id": True,
            "use_season_subfolder": False,
            "rename_selected_folders": False,
            "delete_ad_files": True,
            "preserve_file_info": True,
            "preserve_tags": {"resolution": False},
            "file_name_mode": "clean",
            "unknown_field": "should-be-dropped",
        }
        saved = scraper.save_scraper_batch_preferences("115", options)
        self.assertTrue(saved["ok"])
        self.assertEqual(saved["options"]["season"], 9)
        self.assertEqual(saved["options"]["file_name_mode"], "clean")
        self.assertEqual(saved["options"]["preserve_tags"]["resolution"], False)
        self.assertEqual(saved["options"]["preserve_tags"]["source"], True)
        self.assertNotIn("unknown_field", saved["options"])

        loaded = scraper.get_scraper_batch_preferences("115")
        self.assertEqual(loaded["options"], saved["options"])
        self.assertEqual(loaded["provider"], "115")

        other = scraper.get_scraper_batch_preferences("quark")
        self.assertEqual(other["options"]["file_name_mode"], "standard")
        self.assertEqual(other["options"]["split_mode"], "auto")

    def test_batch_preferences_empty_options_resets_to_defaults(self):
        scraper.save_scraper_batch_preferences("115", {"file_name_mode": "keep", "delete_ad_files": True})
        reset = scraper.save_scraper_batch_preferences("115", {})
        self.assertEqual(reset["options"]["file_name_mode"], "standard")
        self.assertEqual(reset["options"]["delete_ad_files"], False)
        loaded = scraper.get_scraper_batch_preferences("115")
        self.assertEqual(loaded["options"]["file_name_mode"], "standard")

    def test_batch_preferences_rejects_invalid_provider(self):
        with self.assertRaises(RuntimeError):
            scraper.get_scraper_batch_preferences("not-a-provider")
        with self.assertRaises(RuntimeError):
            scraper.save_scraper_batch_preferences("not-a-provider", {"file_name_mode": "keep"})

    def test_batch_preferences_normalizes_invalid_values(self):
        saved = scraper.save_scraper_batch_preferences(
            "115",
            {
                "file_name_mode": "weird",
                "title_language": "jp",
                "episode_mode": "nope",
                "split_mode": "x",
                "season": 0,
            },
        )
        self.assertEqual(saved["options"]["file_name_mode"], "standard")
        self.assertEqual(saved["options"]["title_language"], "auto")
        self.assertEqual(saved["options"]["episode_mode"], "auto")
        self.assertEqual(saved["options"]["split_mode"], "auto")
        self.assertEqual(saved["options"]["season"], 1)

    # ------------------------------------------------------------------
    # 前端：文件命名方式控件、选项分组顺序、偏好加载/保存
    # ------------------------------------------------------------------

    def test_frontend_file_name_mode_control_and_option_group_order(self):
        html = (ROOT / "templates/partials/pages/scraper.html").read_text(encoding="utf-8")
        self.assertIn('id="scraper-file-name-mode"', html)
        self.assertIn('data-scraper-action="reset-batch-preferences"', html)
        folder_index = html.index(">文件夹</div>")
        file_index = html.index(">文件命名</div>")
        clean_index = html.index(">文件清理</div>")
        self.assertLess(folder_index, file_index)
        self.assertLess(file_index, clean_index)

    def test_frontend_collects_file_name_mode_in_payloads(self):
        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")
        self.assertIn("file_name_mode: String($('scraper-file-name-mode')?.value || 'standard')", source)
        self.assertIn("function syncFileNamingModeControls(", source)
        self.assertIn("function applyBatchPreferences(", source)
        self.assertIn("function loadBatchPreferences(", source)
        self.assertIn("function scheduleBatchPreferenceSave(", source)
        self.assertIn("function resetBatchPreferences(", source)

    def test_frontend_preference_save_and_reset_wired(self):
        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")
        handle_source = source[source.index("function handleClick("):]
        self.assertIn("if (action === 'reset-batch-preferences') void resetBatchPreferences();", handle_source)
        change_source = source[source.index("function handleChange("):]
        self.assertIn("scraper-file-name-mode", change_source)
        self.assertIn("scheduleBatchPreferenceSave();", change_source)
        self.assertIn("#scraper-delete-ad-files", change_source)
