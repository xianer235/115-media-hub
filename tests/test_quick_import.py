import os
import tempfile
import unittest
from unittest import mock

from app import core, db
from app.services import monitor as monitor_service
from app.services import monitor_changes, quick_import, scraper


MOUNT_POINTS = [{"provider": "115", "prefix": "/115"}]


def _task(name="电影", scan_path="/115/电影", target="movie", auto_options=None):
    return {
        "name": name,
        "scan_path": scan_path,
        "target_path": name,
        "auto_scrape_on_new": True,
        "auto_scrape_options": auto_options if isinstance(auto_options, dict) else {},
        "quick_import_target": target,
    }


def _cfg(**overrides):
    cfg = {
        "mount_points": [dict(item) for item in MOUNT_POINTS],
        "quick_import_enabled": True,
        "quick_import_inbox_path": "/115/接收",
        "monitor_tasks": [
            _task("电影", "/115/电影", "movie", {"file_name_mode": "standard"}),
            _task("电视剧", "/115/电视剧", "tv", {"file_name_mode": "keep"}),
        ],
    }
    cfg.update(overrides)
    return cfg


def _item(index, name="片名", is_dir=True):
    return {
        "item_index": index,
        "name": name,
        "entry": {"id": f"e{index}", "name": name, "is_dir": is_dir, "parent_id": "inbox"},
        "files": [],
    }


class QuickImportConfigTest(unittest.TestCase):
    def test_disabled_by_default(self):
        cfg = core.normalize_config({})
        self.assertFalse(cfg["quick_import_enabled"])
        self.assertEqual(cfg["quick_import_inbox_path"], "")

    def test_normalize_config_keeps_inbox_path(self):
        cfg = core.normalize_config({"quick_import_enabled": True, "quick_import_inbox_path": "/115/接收/"})
        self.assertTrue(cfg["quick_import_enabled"])
        self.assertEqual(cfg["quick_import_inbox_path"], "/115/接收")

    def test_normalize_task_accepts_only_known_targets(self):
        task = core.normalize_task(
            {"name": "电影", "scan_path": "/115/电影", "target_path": "电影", "quick_import_target": "movie"}
        )
        self.assertEqual(task["quick_import_target"], "movie")
        bogus = core.normalize_task(
            {"name": "x", "scan_path": "/115/x", "target_path": "x", "quick_import_target": "anime"}
        )
        self.assertEqual(bogus["quick_import_target"], "")

    def test_build_config_maps_targets(self):
        conf = quick_import.build_quick_import_config(_cfg())
        self.assertTrue(conf["enabled"])
        self.assertEqual(conf["inbox_rel"], "接收")
        self.assertEqual(conf["targets"]["movie"]["task_name"], "电影")
        self.assertEqual(conf["targets"]["movie"]["scan_rel"], "电影")
        self.assertEqual(conf["targets"]["tv"]["task_name"], "电视剧")

    def test_is_quick_import_savepath(self):
        cfg = _cfg()
        self.assertTrue(quick_import.is_quick_import_savepath(cfg, "接收"))
        self.assertTrue(quick_import.is_quick_import_savepath(cfg, "接收/电影/片名"))
        self.assertFalse(quick_import.is_quick_import_savepath(cfg, "电影/片名"))
        self.assertFalse(quick_import.is_quick_import_savepath(cfg, ""))
        disabled = _cfg(quick_import_enabled=False)
        self.assertFalse(quick_import.is_quick_import_savepath(disabled, "接收/片名"))

    def test_validate_requires_inbox_and_target(self):
        self.assertIn("未启用", quick_import.validate_quick_import_config(_cfg(quick_import_enabled=False)) or "")
        self.assertIn("接收文件夹", quick_import.validate_quick_import_config(_cfg(quick_import_inbox_path="")) or "")
        no_target = _cfg(monitor_tasks=[_task("电影", "/115/电影", "")])
        self.assertIn("快捷导入目标", quick_import.validate_quick_import_config(no_target) or "")
        self.assertIsNone(quick_import.validate_quick_import_config(_cfg()))

    def test_validate_rejects_overlapping_scan_path(self):
        overlap = _cfg(monitor_tasks=[_task("接收子目录", "/115/接收/电影", "movie")])
        self.assertIn("重叠", quick_import.validate_quick_import_config(overlap) or "")
        same = _cfg(monitor_tasks=[_task("就是接收夹", "/115/接收", "movie")])
        self.assertIn("重叠", quick_import.validate_quick_import_config(same) or "")

    def test_target_scrape_options_come_from_task(self):
        conf = quick_import.build_quick_import_config(_cfg())
        options = quick_import._target_scrape_options(conf["targets"]["tv"])
        self.assertEqual(options["file_name_mode"], "keep")
        self.assertIn("title_language", options)
        self.assertIn("delete_ad_files", options)


class QuickImportLeftReasonTest(unittest.TestCase):
    def test_reason_for_unmatched(self):
        self.assertIn("未匹配", quick_import._left_reason_from_result({"status": "manual"}))

    def test_reason_for_suggest(self):
        self.assertIn("未达自动匹配阈值", quick_import._left_reason_from_result({"status": "suggest"}))

    def test_reason_for_low_ai_confidence(self):
        message = quick_import._left_reason_from_result({"status": "suggest", "ai_low_confidence": 40})
        self.assertIn("40", message)

    def test_reason_for_ai_error(self):
        message = quick_import._left_reason_from_result({"ai_error": "AI 请求失败"})
        self.assertIn("AI 识别失败", message)


class SharedOrganizeFlowTest(unittest.TestCase):
    """监控自动刮削与快捷导入共用同一套整理流程。"""

    def test_identify_picks_auto_and_ai_candidates(self):
        items = [_item(1), _item(2), _item(3), _item(4)]
        results = [
            {"item_index": 1, "status": "auto", "auto_pick": {"id": 1, "media_type": "movie"}},
            {"item_index": 2, "status": "suggest", "ai_selected": {"id": 2, "media_type": "tv"}},
            {"item_index": 3, "status": "suggest"},
            {"item_index": 4, "status": "manual"},
        ]
        with mock.patch.object(scraper, "scan_scraper_batch_items", return_value={"items": items}), \
                mock.patch.object(scraper, "identify_scraper_batch_items", return_value={"results": results}):
            outcome = scraper.identify_scraper_batch_entries("115")
        self.assertEqual(sorted(outcome["picked"].keys()), [1, 2])
        self.assertEqual(outcome["picked"][1]["media_type"], "movie")
        self.assertEqual(outcome["picked"][2]["media_type"], "tv")

    def test_use_ai_false_ignores_ai_candidates(self):
        items = [_item(1), _item(2)]
        results = [
            {"item_index": 1, "status": "auto", "auto_pick": {"id": 1, "media_type": "movie"}},
            {"item_index": 2, "status": "suggest", "ai_selected": {"id": 2, "media_type": "tv"}},
        ]
        with mock.patch.object(scraper, "scan_scraper_batch_items", return_value={"items": items}), \
                mock.patch.object(scraper, "identify_scraper_batch_items", return_value={"results": results}):
            outcome = scraper.identify_scraper_batch_entries("115", use_ai=False)
        self.assertEqual(sorted(outcome["picked"].keys()), [1])

    def test_plan_filters_by_item_indexes(self):
        items = [_item(1), _item(2)]
        picked = {1: {"id": 1, "media_type": "movie"}, 2: {"id": 2, "media_type": "tv"}}
        with mock.patch.object(scraper, "build_scraper_batch_plan", return_value={"ok": True}) as build:
            scraper.build_scraper_plan_for_batch("115", items, picked, {}, item_indexes={2})
        payload = build.call_args.args[0]
        self.assertEqual([entry["item_index"] for entry in payload["items"]], [2])

    def test_plan_returns_empty_without_candidates(self):
        with mock.patch.object(scraper, "build_scraper_batch_plan") as build:
            outcome = scraper.build_scraper_plan_for_batch("115", [_item(1)], {}, {})
        self.assertEqual(outcome, {})
        build.assert_not_called()

    def test_plan_forwards_group_entries(self):
        item = _item(1, "剧集A")
        item["entries"] = [{"id": "e1", "name": "剧集A.S01E01.mkv"}, {"id": "e2", "name": "剧集A.S01E02.mkv"}]
        with mock.patch.object(scraper, "build_scraper_batch_plan", return_value={"ok": True}) as build:
            scraper.build_scraper_plan_for_batch("115", [item], {1: {"id": 1, "media_type": "tv"}}, {})
        payload = build.call_args.args[0]
        self.assertEqual(len(payload["items"][0]["entries"]), 2)

    def test_loose_file_forced_into_media_folder(self):
        entry = {"name": "追杀51号(2025)-2160p.UHDBlu-rayRemux.mkv", "parent_path": "接收"}
        tmdb = {
            "tmdb_media_type": "movie",
            "tmdb_title": "追杀51号",
            "tmdb_localized_title": "追杀51号",
            "tmdb_year": "2025",
            "title": "追杀51号",
            "year": "2025",
        }
        forced, issue = scraper._build_scraper_target_path(
            entry,
            tmdb,
            {
                "base_path": "接收",
                "file_name_mode": "standard",
                "title_language": "zh",
                "organize_into_media_folder": True,
                "preserve_source_parent_path": False,
            },
        )
        self.assertEqual(issue, "")
        self.assertTrue(forced.startswith("追杀51号 (2025)/"), forced)
        # 「保持原名」模式下也要建出媒体文件夹（文件名可保持原样）
        keep_folder, keep_issue = scraper._build_scraper_target_path(
            entry,
            tmdb,
            {
                "base_path": "接收",
                "file_name_mode": "keep",
                "title_language": "zh",
                "organize_into_media_folder": True,
                "preserve_source_parent_path": False,
                "force_media_folder": True,
            },
        )
        self.assertEqual(keep_issue, "")
        self.assertTrue(keep_folder.startswith("追杀51号 (2025)/"), keep_folder)
        self.assertIn("追杀51号(2025)-2160p.UHDBlu-rayRemux.mkv", keep_folder)
        # 对照：不强制整理媒体文件夹时只会原地改名，不会新建文件夹
        plain, _ = scraper._build_scraper_target_path(
            entry,
            tmdb,
            {
                "base_path": "接收",
                "file_name_mode": "standard",
                "title_language": "zh",
                "organize_into_media_folder": False,
                "preserve_source_parent_path": True,
            },
        )
        self.assertNotIn("/", plain)


class QuickImportNoDoubleScrapeGuardTest(unittest.TestCase):
    """防重复：刮削任务/快捷导入搬运产生的事件不能触发监控二次自动刮削。"""

    def test_scraper_job_events_are_ignored_for_auto_scrape(self):
        stats = {"new_media_items": [{"id": "1"}]}
        self.assertEqual(
            monitor_changes._collect_event_new_media_items({"source_action": "scraper-job:7:quick-import"}, stats),
            [],
        )
        self.assertEqual(
            monitor_changes._collect_event_new_media_items({"source_action": "scraper-job:1:forward"}, stats),
            [],
        )

    def test_direct_move_events_still_count(self):
        stats = {"new_media_items": [{"id": "1"}]}
        self.assertEqual(
            monitor_changes._collect_event_new_media_items({"source_action": "scraper:entry:move"}, stats),
            [{"id": "1"}],
        )
        self.assertEqual(monitor_changes._collect_event_new_media_items({}, stats), [{"id": "1"}])

    def test_move_source_action_is_forwarded(self):
        with mock.patch.object(scraper, "_prepare_scraper_monitor_sync", return_value={}) as prepare, \
                mock.patch.object(scraper, "_require_provider_cookie", return_value="cookie"), \
                mock.patch.object(scraper, "_build_transfer_monitor_snapshots", return_value=[]), \
                mock.patch.object(scraper, "_move_provider_entries", return_value={}), \
                mock.patch.object(scraper, "_invalidate_provider_parent"), \
                mock.patch.object(scraper, "_finish_scraper_monitor_sync", return_value={}):
            scraper.move_scraper_entries(
                "115",
                ["e1"],
                "target-cid",
                source_cid="inbox-cid",
                source_action="scraper-job:9:quick-import",
            )
        self.assertEqual(prepare.call_args.kwargs["source_action"], "scraper-job:9:quick-import")

    def test_move_source_action_defaults_to_direct_move(self):
        with mock.patch.object(scraper, "_prepare_scraper_monitor_sync", return_value={}) as prepare, \
                mock.patch.object(scraper, "_require_provider_cookie", return_value="cookie"), \
                mock.patch.object(scraper, "_build_transfer_monitor_snapshots", return_value=[]), \
                mock.patch.object(scraper, "_move_provider_entries", return_value={}), \
                mock.patch.object(scraper, "_invalidate_provider_parent"), \
                mock.patch.object(scraper, "_finish_scraper_monitor_sync", return_value={}):
            scraper.move_scraper_entries("115", ["e1"], "target-cid", source_cid="inbox-cid")
        self.assertEqual(prepare.call_args.kwargs["source_action"], "scraper:entry:move")


class MonitorAutoScrapeRootFileTest(unittest.TestCase):
    """监控根目录下的散文件不能把监控目录本身当成条目去改名。"""

    def _run(self, scan_path, new_items):
        cfg = {"mount_points": [dict(item) for item in MOUNT_POINTS]}
        task = {"name": "电影", "scan_path": scan_path, "auto_scrape_options": {}}
        captured = {}

        def fake_scan(provider, base_cid, base_path, entries, *args, **kwargs):
            captured["entries"] = entries
            return {"items": []}

        with mock.patch.object(scraper, "_walk_existing_folder", return_value=("cid", True)), \
                mock.patch.object(scraper, "scan_scraper_batch_items", side_effect=fake_scan):
            monitor_service._auto_scrape_new_media_items(cfg, task, new_items)
        return captured.get("entries") or []

    def test_root_level_loose_file_becomes_file_entry(self):
        entries = self._run(
            "/115/115自存电影",
            [{"id": "f1", "fid": "f1", "name": "追杀51号(2025).mkv", "remote_rel": "追杀51号(2025).mkv"}],
        )
        self.assertEqual(len(entries), 1)
        self.assertFalse(entries[0]["is_dir"])
        self.assertEqual(entries[0]["parent_path"], "115自存电影")
        self.assertEqual(entries[0]["path"], "115自存电影/追杀51号(2025).mkv")
        self.assertEqual(entries[0]["id"], "f1")

    def test_subfolder_new_file_still_uses_folder_entry(self):
        entries = self._run(
            "/115/115自存电影",
            [{"id": "f2", "fid": "f2", "name": "片名.mkv", "remote_rel": "某片/片名.mkv"}],
        )
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0]["is_dir"])
        self.assertEqual(entries[0]["name"], "某片")
        self.assertEqual(entries[0]["parent_path"], "115自存电影")


class QuickImportRunTest(unittest.TestCase):
    class _Future:
        def result(self, timeout=None):
            return None

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        self.original_db_ensured = db._DB_ENSURED
        db.DB_PATH = os.path.join(self.tmpdir.name, "data.db")
        db._DB_ENSURED = False
        db.ensure_db()

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        db._DB_ENSURED = self.original_db_ensured
        self.tmpdir.cleanup()

    def test_moves_movie_and_keeps_unmatched(self):
        cfg = _cfg()
        identified = {
            "items": [_item(1, "电影A"), _item(2, "乱七八糟")],
            "picked": {1: {"id": 603, "media_type": "movie"}},
            "results": [
                {"item_index": 1, "status": "auto"},
                {"item_index": 2, "status": "manual"},
            ],
        }
        seen_options = []
        move_record = []

        def plan_side_effect(provider, items, picked, options, **kwargs):
            seen_options.append(options)
            return {
                "ok": True,
                "items": [{"title": "电影A", "year": "2024"}],
                "issues": [],
                "ready_count": 1,
            }

        with mock.patch.object(quick_import, "get_config", return_value=cfg), \
                mock.patch.object(quick_import, "resolve_scraper_dest_folder_id", side_effect=lambda provider, path: f"cid:{path}"), \
                mock.patch.object(quick_import, "identify_scraper_batch_entries", return_value=identified), \
                mock.patch.object(quick_import, "build_scraper_plan_for_batch", side_effect=plan_side_effect), \
                mock.patch.object(quick_import, "create_scraper_job_from_plan", return_value={"job_id": 11}), \
                mock.patch.object(quick_import, "submit_scraper_job", return_value=self._Future()), \
                mock.patch.object(quick_import, "_resolve_entry_after_organize", side_effect=lambda cid, summary, entry: entry), \
                mock.patch.object(scraper, "move_scraper_entries", side_effect=lambda *args, **kwargs: move_record.append(kwargs) or {}):
            result = quick_import.run_quick_import("test")

        self.assertEqual(len(result["moved"]), 1)
        self.assertEqual(result["moved"][0]["target"], "电影")
        self.assertEqual(result["moved"][0]["task_name"], "电影")
        self.assertEqual(len(result["left"]), 1)
        self.assertIn("未匹配", result["left"][0]["reason"])
        self.assertEqual(move_record[0]["source_action"], "scraper-job:11:quick-import")
        self.assertEqual(move_record[0]["target_parent_path"], "电影")
        self.assertEqual(seen_options[0]["file_name_mode"], "standard")
        # 接收夹里可能是散文件，必须强制整理进媒体文件夹
        self.assertTrue(seen_options[0]["force_media_folder"])

    def test_tv_uses_tv_task_options(self):
        cfg = _cfg()
        identified = {
            "items": [_item(1, "剧集A")],
            "picked": {1: {"id": 1399, "media_type": "tv"}},
            "results": [{"item_index": 1, "status": "auto"}],
        }
        seen_options = []

        def plan_side_effect(provider, items, picked, options, **kwargs):
            seen_options.append(options)
            return {"ok": True, "items": [{"title": "剧集A", "year": "2024"}], "issues": [], "ready_count": 1}

        with mock.patch.object(quick_import, "get_config", return_value=cfg), \
                mock.patch.object(quick_import, "resolve_scraper_dest_folder_id", side_effect=lambda provider, path: f"cid:{path}"), \
                mock.patch.object(quick_import, "identify_scraper_batch_entries", return_value=identified), \
                mock.patch.object(quick_import, "build_scraper_plan_for_batch", side_effect=plan_side_effect), \
                mock.patch.object(quick_import, "create_scraper_job_from_plan", return_value={"job_id": 21}), \
                mock.patch.object(quick_import, "submit_scraper_job", return_value=self._Future()), \
                mock.patch.object(quick_import, "_resolve_entry_after_organize", side_effect=lambda cid, summary, entry: entry), \
                mock.patch.object(scraper, "move_scraper_entries", return_value={}) as move:
            result = quick_import.run_quick_import("test")

        self.assertEqual(result["moved"][0]["target"], "电视剧")
        self.assertEqual(seen_options[0]["file_name_mode"], "keep")
        self.assertEqual(move.call_args.args[2], "cid:电视剧")

    def test_missing_target_keeps_item_in_inbox(self):
        cfg = _cfg(monitor_tasks=[_task("电影", "/115/电影", "movie")])
        identified = {
            "items": [_item(1, "剧集A")],
            "picked": {1: {"id": 1399, "media_type": "tv"}},
            "results": [{"item_index": 1, "status": "auto"}],
        }
        with mock.patch.object(quick_import, "get_config", return_value=cfg), \
                mock.patch.object(quick_import, "resolve_scraper_dest_folder_id", return_value="cid"), \
                mock.patch.object(quick_import, "identify_scraper_batch_entries", return_value=identified), \
                mock.patch.object(quick_import, "build_scraper_plan_for_batch") as plan, \
                mock.patch.object(scraper, "move_scraper_entries") as move:
            result = quick_import.run_quick_import("test")

        plan.assert_not_called()
        move.assert_not_called()
        self.assertEqual(result["moved"], [])
        self.assertIn("电视剧", result["left"][0]["reason"])

    def test_plan_conflict_keeps_item_in_inbox(self):
        cfg = _cfg()
        identified = {
            "items": [_item(1, "电影A")],
            "picked": {1: {"id": 603, "media_type": "movie"}},
            "results": [{"item_index": 1, "status": "auto"}],
        }
        with mock.patch.object(quick_import, "get_config", return_value=cfg), \
                mock.patch.object(quick_import, "resolve_scraper_dest_folder_id", return_value="cid"), \
                mock.patch.object(quick_import, "identify_scraper_batch_entries", return_value=identified), \
                mock.patch.object(
                    quick_import,
                    "build_scraper_plan_for_batch",
                    return_value={
                        "ok": True,
                        "items": [{"title": "电影A"}],
                        "issues": ["条目 #1 电影A：目标目录中已有同名文件夹"],
                        "ready_count": 0,
                    },
                ), \
                mock.patch.object(quick_import, "create_scraper_job_from_plan") as create, \
                mock.patch.object(scraper, "move_scraper_entries") as move:
            result = quick_import.run_quick_import("test")

        create.assert_not_called()
        move.assert_not_called()
        self.assertIn("整理计划有冲突", result["left"][0]["reason"])

    def test_move_failure_keeps_item_and_records_reason(self):
        cfg = _cfg()
        identified = {
            "items": [_item(1, "电影A")],
            "picked": {1: {"id": 603, "media_type": "movie"}},
            "results": [{"item_index": 1, "status": "auto"}],
        }
        with mock.patch.object(quick_import, "get_config", return_value=cfg), \
                mock.patch.object(quick_import, "resolve_scraper_dest_folder_id", return_value="cid"), \
                mock.patch.object(quick_import, "identify_scraper_batch_entries", return_value=identified), \
                mock.patch.object(
                    quick_import,
                    "build_scraper_plan_for_batch",
                    return_value={"ok": True, "items": [{"title": "电影A"}], "issues": [], "ready_count": 1},
                ), \
                mock.patch.object(quick_import, "create_scraper_job_from_plan", return_value={"job_id": 5}), \
                mock.patch.object(quick_import, "submit_scraper_job", return_value=self._Future()), \
                mock.patch.object(quick_import, "_resolve_entry_after_organize", side_effect=lambda cid, summary, entry: entry), \
                mock.patch.object(scraper, "move_scraper_entries", side_effect=RuntimeError("boom")):
            result = quick_import.run_quick_import("test")

        self.assertEqual(result["moved"], [])
        self.assertIn("搬运失败", result["left"][0]["reason"])

    def test_run_records_status_row(self):
        cfg = _cfg()
        identified = {"items": [], "picked": {}, "results": []}
        with mock.patch.object(quick_import, "get_config", return_value=cfg), \
                mock.patch.object(quick_import, "resolve_scraper_dest_folder_id", return_value="cid"), \
                mock.patch.object(quick_import, "identify_scraper_batch_entries", return_value=identified):
            result = quick_import.run_quick_import("test")
        runs = quick_import.list_quick_import_runs(5)
        self.assertTrue(result["ok"])
        self.assertEqual(runs[0]["trigger"], "test")
        self.assertEqual(runs[0]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
