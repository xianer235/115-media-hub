import os
import tempfile
import unittest
from unittest import mock

from app import core, db
from app.services import monitor as monitor_service
from app.services import monitor_changes, monitor_runs, quick_import, scraper


MOUNT_POINTS = [{"provider": "115", "prefix": "/115"}]


def _task(name="电影", scan_path="/115/电影", auto_options=None, enabled=True):
    return {
        "name": name,
        "task_type": "scan",
        "enabled": enabled,
        "scan_path": scan_path,
        "target_path": name,
        "auto_scrape_on_new": True,
        "auto_scrape_options": auto_options if isinstance(auto_options, dict) else {},
    }


def _inbox_task(name="接收", path="/115/接收", enabled=True, targets=None, **extra):
    task = {
        "name": name,
        "task_type": "inbox",
        "enabled": enabled,
        "scan_path": path,
        "distribute_targets": dict(targets) if isinstance(targets, dict) else {"movie": "电影", "tv": "电视剧"},
    }
    task.update(extra)
    return task


def _cfg(tasks=None, inbox=True, **overrides):
    """默认配置：两个扫描任务 + 一个启用中的接收夹任务。"""
    scan_tasks = list(tasks) if tasks is not None else [
        _task("电影", "/115/电影", {"file_name_mode": "standard"}),
        _task("电视剧", "/115/电视剧", {"file_name_mode": "keep"}),
    ]
    monitor_tasks = list(scan_tasks)
    if isinstance(inbox, dict):
        monitor_tasks.append(dict(inbox))
    elif inbox:
        monitor_tasks.append(_inbox_task())
    cfg = {
        "mount_points": [dict(item) for item in MOUNT_POINTS],
        "monitor_tasks": monitor_tasks,
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
    def test_inbox_task_is_seeded_by_default(self):
        """接收夹是内置槽位：全新配置里就已经有一个，用户只需要把它配好。"""
        cfg = core.normalize_config({})
        inbox = core.get_inbox_task(cfg)
        self.assertEqual(inbox["name"], "接收")
        self.assertEqual(inbox["task_type"], "inbox")
        self.assertTrue(inbox["enabled"])
        # 签名密钥默认未设置，webhook 默认关闭（设置密钥后才允许手动打开）。
        self.assertFalse(inbox["webhook_enabled"])
        self.assertEqual(inbox["scan_path"], "")
        self.assertIn("选择文件夹", quick_import.validate_quick_import_config(cfg) or "")

    def test_seeded_inbox_webhook_gates_on_secret(self):
        cfg = core.normalize_config({"webhook_secret": "s3cret"})
        self.assertFalse(core.get_inbox_task(cfg)["webhook_enabled"])

    def test_only_one_inbox_task_is_kept(self):
        cfg = core.normalize_config(
            {
                "monitor_tasks": [
                    {"name": "接收", "task_type": "inbox", "scan_path": "/115/接收"},
                    {"name": "第二个接收夹", "task_type": "inbox", "scan_path": "/115/接收2"},
                ]
            }
        )
        inboxes = [task for task in cfg["monitor_tasks"] if task["task_type"] == "inbox"]
        self.assertEqual(len(inboxes), 1)
        self.assertEqual(inboxes[0]["name"], "接收")
        self.assertEqual(inboxes[0]["scan_path"], "/115/接收")

    def test_configured_inbox_task_survives_normalize(self):
        cfg = core.normalize_config(
            {
                "monitor_tasks": [
                    {"name": "电影", "scan_path": "/115/电影"},
                    {
                        "name": "我的接收",
                        "task_type": "inbox",
                        "enabled": True,
                        "webhook_enabled": False,
                        "scan_path": "/115/临时",
                        "distribute_targets": {"movie": "电影"},
                    },
                ]
            }
        )
        inbox = core.get_inbox_task(cfg)
        self.assertEqual(inbox["name"], "我的接收")
        self.assertEqual(inbox["scan_path"], "/115/临时")
        self.assertEqual(inbox["distribute_targets"], {"movie": "电影"})
        # 用户手动关掉的 webhook 不会被归一化重新打开。
        self.assertFalse(inbox["webhook_enabled"])

    def test_normalize_config_migrates_legacy_global_inbox(self):
        cfg = core.normalize_config(
            {
                "mount_points": [dict(item) for item in MOUNT_POINTS],
                "quick_import_enabled": True,
                "quick_import_inbox_path": "/115/接收/",
                "monitor_tasks": [
                    _task("电影", "/115/电影"),
                    _task("电视剧", "/115/电视剧"),
                ],
            }
        )
        # 旧的两个全局字段被迁移进接收夹任务后不再保留。
        self.assertNotIn("quick_import_enabled", cfg)
        self.assertNotIn("quick_import_inbox_path", cfg)
        inbox = core.get_inbox_task(cfg)
        self.assertEqual(inbox["name"], "接收")
        self.assertTrue(inbox["enabled"])
        self.assertEqual(inbox["scan_path"], "/115/接收")
        # 迁移只跑一次：再归一化一次结果不变。
        self.assertEqual(core.normalize_config(cfg), cfg)

    def test_migration_collects_distribute_targets_from_scan_tasks(self):
        cfg = core.normalize_config(
            {
                "quick_import_enabled": True,
                "quick_import_inbox_path": "/115/接收",
                "monitor_tasks": [
                    {"name": "电影", "scan_path": "/115/电影", "quick_import_target": "movie"},
                    {"name": "电视剧", "scan_path": "/115/电视剧", "quick_import_target": "tv"},
                ],
            }
        )
        inbox = core.get_inbox_task(cfg)
        self.assertEqual(inbox["distribute_targets"], {"movie": "电影", "tv": "电视剧"})
        for task in cfg["monitor_tasks"]:
            self.assertEqual(task["quick_import_target"], "")

    def test_migration_enables_webhook_only_when_secret_is_set(self):
        base = {"quick_import_enabled": True, "quick_import_inbox_path": "/115/接收"}
        no_secret = core.normalize_config({**base, "monitor_tasks": [_task("电影", "/115/电影")]})
        self.assertFalse(core.get_inbox_task(no_secret)["webhook_enabled"])
        with_secret = core.normalize_config(
            {**base, "webhook_secret": "s3cret", "monitor_tasks": [_task("电影", "/115/电影")]}
        )
        self.assertTrue(core.get_inbox_task(with_secret)["webhook_enabled"])

    def test_normalize_task_type_and_enabled(self):
        inbox = core.normalize_task({"name": "接收", "task_type": "inbox", "enabled": True})
        self.assertEqual(inbox["task_type"], "inbox")
        self.assertTrue(inbox["enabled"])
        # 扫描任务是默认类型；老配置没有 enabled 时默认开启。
        scan = core.normalize_task({"name": "电影", "scan_path": "/115/电影"})
        self.assertEqual(scan["task_type"], "scan")
        self.assertTrue(scan["enabled"])
        bogus = core.normalize_task({"name": "x", "task_type": "anime"})
        self.assertEqual(bogus["task_type"], "scan")

    def test_normalize_distribute_targets_keeps_known_keys(self):
        targets = core.normalize_distribute_targets({"movie": " 电影 ", "tv": "", "anime": "x"})
        self.assertEqual(targets, {"movie": "电影"})

    def test_build_config_maps_targets(self):
        conf = quick_import.build_quick_import_config(_cfg())
        self.assertEqual(conf["task_name"], "接收")
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
        disabled = _cfg(inbox=_inbox_task(enabled=False))
        self.assertFalse(quick_import.is_quick_import_savepath(disabled, "接收/片名"))

    def test_validate_requires_enabled_inbox_path_and_target(self):
        self.assertIn("未启用", quick_import.validate_quick_import_config(_cfg(inbox=_inbox_task(enabled=False))) or "")
        self.assertIn("选择文件夹", quick_import.validate_quick_import_config(_cfg(inbox=_inbox_task(path=""))) or "")
        no_target = _cfg(inbox=_inbox_task(targets={}))
        self.assertIn("分发目标", quick_import.validate_quick_import_config(no_target) or "")
        self.assertIsNone(quick_import.validate_quick_import_config(_cfg()))

    def test_validate_rejects_overlapping_scan_path(self):
        overlap = _cfg(
            tasks=[_task("接收子目录", "/115/接收/电影")],
            inbox=_inbox_task(targets={"movie": "接收子目录"}),
        )
        self.assertIn("重叠", quick_import.validate_quick_import_config(overlap) or "")
        same = _cfg(
            tasks=[_task("就是接收夹", "/115/接收")],
            inbox=_inbox_task(targets={"movie": "就是接收夹"}),
        )
        self.assertIn("重叠", quick_import.validate_quick_import_config(same) or "")

    def test_target_scrape_options_come_from_task(self):
        conf = quick_import.build_quick_import_config(_cfg())
        options = quick_import._target_scrape_options(conf["targets"]["tv"])
        self.assertEqual(options["file_name_mode"], "keep")
        self.assertIn("title_language", options)
        self.assertIn("delete_ad_files", options)


class MonitorTaskTypeConstraintTest(unittest.TestCase):
    """任务类型不可更改：内置接收夹固定是接收夹，新增任务一律是普通扫描任务。"""

    def test_scan_task_cannot_become_inbox(self):
        existing = [{"name": "电影", "task_type": "scan"}, {"name": "接收", "task_type": "inbox"}]
        posted = [
            {"name": "电影", "task_type": "inbox", "distribute_targets": {"movie": "电影"}},
            {"name": "接收", "task_type": "inbox"},
        ]

        result = core.apply_task_type_constraints(existing, posted)

        by_name = {task["name"]: task for task in result}
        self.assertEqual(by_name["电影"]["task_type"], "scan")
        self.assertEqual(by_name["电影"]["distribute_targets"], {})
        self.assertEqual(by_name["接收"]["task_type"], "inbox")

    def test_inbox_cannot_become_scan(self):
        existing = [{"name": "接收", "task_type": "inbox"}, {"name": "电影", "task_type": "scan"}]
        posted = [{"name": "接收", "task_type": "scan"}, {"name": "电影", "task_type": "scan"}]

        result = core.apply_task_type_constraints(existing, posted)

        self.assertEqual(
            {task["name"]: task["task_type"] for task in result},
            {"接收": "inbox", "电影": "scan"},
        )

    def test_new_task_is_forced_to_scan(self):
        existing = [{"name": "接收", "task_type": "inbox"}]
        posted = [{"name": "接收", "task_type": "inbox"}, {"name": "新任务", "task_type": "inbox"}]

        result = core.apply_task_type_constraints(existing, posted)

        by_name = {task["name"]: task for task in result}
        self.assertEqual(by_name["新任务"]["task_type"], "scan")

    def test_inbox_rename_is_allowed(self):
        existing = [{"name": "接收", "task_type": "inbox"}, {"name": "电影", "task_type": "scan"}]
        posted = [
            {"name": "我的接收", "task_type": "inbox", "distribute_targets": {"movie": "电影"}},
            {"name": "电影", "task_type": "scan"},
        ]

        result = core.apply_task_type_constraints(existing, posted)

        by_name = {task["name"]: task for task in result}
        self.assertEqual(by_name["我的接收"]["task_type"], "inbox")
        self.assertEqual(by_name["我的接收"]["distribute_targets"], {"movie": "电影"})

    def test_change_matching_skips_inbox_task(self):
        """接收夹不是扫描目标：它的路径变更不该生成文件夹监控的变更事件。"""
        cfg = core.normalize_config(
            {
                "mount_points": [{"provider": "115", "prefix": "/115"}],
                "monitor_tasks": [
                    {"name": "电影监测", "scan_path": "/115/电影", "target_path": "电影"},
                    {"name": "接收", "task_type": "inbox", "scan_path": "/115/接收"},
                ],
            }
        )

        self.assertEqual(
            monitor_changes.match_monitor_tasks_for_paths(cfg, ["接收/片名"], provider="115"),
            [],
        )
        matched = monitor_changes.match_monitor_tasks_for_paths(cfg, ["电影/片名"], provider="115")
        self.assertEqual([task["name"] for task in matched], ["电影监测"])

    def test_queue_refuses_inbox_task(self):
        """任何扫描触发都不能把接收夹任务塞进扫描队列。"""
        cfg = core.normalize_config(
            {"monitor_tasks": [{"name": "接收", "task_type": "inbox", "scan_path": "/115/接收"}]}
        )

        with mock.patch.object(monitor_service, "get_config", return_value=cfg):
            self.assertEqual(monitor_service.queue_monitor_job("接收", "change"), "inbox")
            self.assertEqual(monitor_service.queue_monitor_job("接收", "manual"), "inbox")


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

    def test_forced_media_folder_keeps_task_naming_options(self):
        """强制归档散文件时要沿用监控任务的命名形状（TMDB ID + Season 子目录）。

        否则同一部剧：选文件夹整理得到「片名 (年份) [tmdbid-123]/Season 01/…」，
        接收夹/监控根目录的散文件却整理成「片名 (年份)/…」，两边永远对不上。
        """
        entry = {
            "id": "f1",
            "name": "剧集A (2026) - S01E01 - 1080p.WEB-DL.mkv",
            "is_dir": False,
            "parent_id": "inbox",
            "parent_path": "接收",
            "path": "接收/剧集A (2026) - S01E01 - 1080p.WEB-DL.mkv",
        }
        tmdb = {
            "tmdb_id": 328704,
            "tmdb_media_type": "tv",
            "tmdb_title": "剧集A",
            "tmdb_localized_title": "剧集A",
            "tmdb_original_title": "剧集A",
            "tmdb_aliases": [],
            "tmdb_year": "2026",
            "tmdb_season_episode_map": {"1": 8},
            "tmdb_episode_mode": "seasonal",
        }

        def build(**options):
            with (
                mock.patch.object(scraper, "_require_scraper_operation"),
                mock.patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
                mock.patch.object(scraper, "_target_name_exists", return_value=False),
                mock.patch.object(scraper, "_walk_existing_folder", return_value=("", False)),
                mock.patch.object(
                    scraper,
                    "get_config",
                    return_value={
                        "tmdb_enabled": True,
                        "tmdb_api_key": "key",
                        "tmdb_language": "zh-CN",
                        "tmdb_region": "CN",
                    },
                ),
            ):
                return scraper.build_scraper_rename_plan(
                    {
                        "provider": "115",
                        "base_cid": "inbox",
                        "base_path": "接收",
                        "entries": [entry],
                        "tmdb": tmdb,
                        "options": {"title_language": "zh", "file_name_mode": "standard", **options},
                    }
                )

        forced = build(force_media_folder=True, include_tmdb_id=True, use_season_subfolder=True, season=1)
        forced_path = forced["actions"][0]["new_path"]
        self.assertEqual(
            forced_path,
            "接收/剧集A (2026) [tmdbid-328704]/Season 01/剧集A (2026) - S01E01.mkv",
        )
        # 对照：不强制归档（旧的散文件整理）仍然只原地改名，不建文件夹、不写 TMDB ID、不加 Season
        plain = build(include_tmdb_id=True, use_season_subfolder=True, season=1)
        plain_path = plain["actions"][0]["new_path"]
        self.assertEqual(plain_path, "接收/剧集A (2026) - S01E01.mkv")

    def test_files_already_in_media_folder_are_not_nested(self):
        """文件已经在「片名 (年份) [tmdbid-x]/Season 01/」里时，就地整理，不能再套一层同名文件夹。

        监控自动刮削会把「片名 (年份)/Season 01」当成一个条目来整理（`parent_rel` 取新文件的父目录），
        此前会按"选中文件夹"的锚点再建一层 `片名 (年份) [tmdbid-x]/片名 (年份) [tmdbid-x]/`。
        """
        show = "剧集A (2026) [tmdbid-1]"
        entry = {
            "id": "f4",
            "name": "剧集A (2026) - S01E04.mkv",
            "is_dir": False,
            "parent_id": "season",
            "parent_path": f"115自存电视剧/{show}/Season 01",
            "path": f"115自存电视剧/{show}/Season 01/剧集A (2026) - S01E04.mkv",
        }
        tmdb = {
            "tmdb_id": 1,
            "tmdb_media_type": "tv",
            "tmdb_title": "剧集A",
            "tmdb_localized_title": "剧集A",
            "tmdb_original_title": "剧集A",
            "tmdb_aliases": [],
            "tmdb_year": "2026",
            "tmdb_season_episode_map": {"1": 8},
            "tmdb_episode_mode": "seasonal",
        }
        options = {
            "base_path": "115自存电视剧",
            "file_name_mode": "standard",
            "title_language": "zh",
            "organize_into_media_folder": True,
            "preserve_source_parent_path": False,
            "force_media_folder": True,
            "use_season_subfolder": True,
            "include_tmdb_id": True,
            "season": 1,
        }
        target, issue = scraper._build_scraper_target_path(
            entry,
            tmdb,
            options,
            folder_parent_path=show,
        )
        self.assertEqual(issue, "")
        self.assertEqual(target, f"{show}/Season 01/剧集A (2026) - S01E04.mkv")

        # 计划层同样要判定为"无需动作"，否则监控自动刮削每次都会再搬一次文件。
        # 这里复刻监控自动刮削的真实形态：条目是 Season 01 文件夹，且调用方没有传 base_path，
        # `build_scraper_rename_plan` 会用"选中文件夹的父目录"（= 剧集文件夹）兜底 base_path。
        files = [
            {"id": f"f{index}", "name": f"剧集A (2026) - S01E0{index}.mkv", "is_dir": False, "size": 1, "parent_id": "season"}
            for index in (2, 3)
        ]
        season_entry = {
            "id": "season",
            "name": "Season 01",
            "is_dir": True,
            "parent_id": "show",
            "parent_path": "115自存电视剧/剧集A (2026) [tmdbid-1]",
            "path": "115自存电视剧/剧集A (2026) [tmdbid-1]/Season 01",
        }

        def fake_list(provider, cookie, cid, folders_only=False, offset=0, limit=0):
            return {"entries": [dict(item) for item in files] if cid == "season" else []}

        with (
            mock.patch.object(scraper, "_require_scraper_operation"),
            mock.patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
            mock.patch.object(scraper, "_target_name_exists", return_value=False),
            mock.patch.object(scraper, "_walk_existing_folder", return_value=("", False)),
            mock.patch.object(scraper, "_list_provider_entries_payload", side_effect=fake_list),
            mock.patch.object(
                scraper,
                "get_config",
                return_value={"tmdb_enabled": True, "tmdb_api_key": "key", "tmdb_language": "zh-CN"},
            ),
        ):
            plan = scraper.build_scraper_rename_plan(
                {
                    "provider": "115",
                    "base_cid": "show",
                    "entries": [season_entry],
                    "tmdb": tmdb,
                    "options": {key: value for key, value in options.items() if key != "base_path"},
                }
            )
        self.assertEqual(plan["actions"], [])
        self.assertEqual(plan["unchanged_count"], len(files))

    def test_same_show_sibling_folder_does_not_block_plan(self):
        """接收夹里已有"同一部剧"的另一个名字（[tmdbid-…] 装饰）时，不该报冲突留守。

        实测就是这里让 `王子与乞丐 (2026)` 反复留在接收夹：它想改成
        `王子与乞丐 (2026) [tmdbid-328704]`，而这个名字被同批另一个文件夹占着。
        """
        plain = "王子与乞丐 (2026)"
        decorated = "王子与乞丐 (2026) [tmdbid-328704]"
        folder_entry = {
            "id": "plain",
            "name": plain,
            "is_dir": True,
            "parent_id": "inbox",
            "parent_path": "接收",
            "path": f"接收/{plain}",
        }
        files = [{"id": "f1", "name": "王子与乞丐 (2026) - S01E01.mkv", "is_dir": False, "size": 1}]

        def fake_list(provider, cookie, cid, folders_only=False, offset=0, limit=0):
            if cid == "plain":
                return {"entries": [dict(item) for item in files]}
            return {"entries": [{"id": "decorated", "name": decorated, "is_dir": True}]}

        tmdb = {
            "tmdb_id": 328704,
            "tmdb_media_type": "tv",
            "tmdb_title": "王子与乞丐",
            "tmdb_localized_title": "王子与乞丐",
            "tmdb_original_title": "王子与乞丐",
            "tmdb_aliases": [],
            "tmdb_year": "2026",
            "tmdb_season_episode_map": {"1": 8},
            "tmdb_episode_mode": "seasonal",
        }
        with (
            mock.patch.object(scraper, "_require_scraper_operation"),
            mock.patch.object(scraper, "_require_provider_cookie", return_value="cookie"),
            mock.patch.object(scraper, "_walk_existing_folder", return_value=("", False)),
            mock.patch.object(scraper, "_list_provider_entries_payload", side_effect=fake_list),
            mock.patch.object(scraper, "_get_scraper_entries_page", side_effect=lambda provider, cookie, cid, folders_only, offset, limit, cache=None: fake_list(provider, cookie, cid, folders_only, offset, limit)),
            mock.patch.object(
                scraper,
                "get_config",
                return_value={"tmdb_enabled": True, "tmdb_api_key": "key", "tmdb_language": "zh-CN"},
            ),
        ):
            plan = scraper.build_scraper_rename_plan(
                {
                    "provider": "115",
                    "base_cid": "inbox",
                    "base_path": "接收",
                    "entries": [folder_entry],
                    "tmdb": tmdb,
                    "options": {
                        "title_language": "zh",
                        "file_name_mode": "standard",
                        "rename_selected_folders": True,
                        "include_tmdb_id": True,
                        "use_season_subfolder": True,
                        "force_media_folder": True,
                        "season": 1,
                    },
                }
            )

        self.assertEqual(plan["issues"], [])
        self.assertFalse(any(action.get("is_dir") for action in plan["actions"]))
        self.assertEqual(
            plan["actions"][0]["new_path"],
            f"接收/{plain}/Season 01/王子与乞丐 (2026) - S01E01.mkv",
        )


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
                mock.patch.object(scraper, "find_scraper_media_folder", return_value={}), \
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

    def test_mixed_result_waits_when_dispatched_item_needs_strm_sync(self):
        cfg = _cfg()
        identified = {
            "items": [_item(1, "电影A"), _item(2, "无法识别")],
            "picked": {1: {"id": 603, "media_type": "movie"}},
            "results": [
                {"item_index": 1, "status": "auto"},
                {"item_index": 2, "status": "manual"},
            ],
        }

        with mock.patch.object(quick_import, "get_config", return_value=cfg), \
                mock.patch.object(quick_import, "resolve_scraper_dest_folder_id", side_effect=lambda provider, path: f"cid:{path}"), \
                mock.patch.object(quick_import, "identify_scraper_batch_entries", return_value=identified), \
                mock.patch.object(quick_import, "build_scraper_plan_for_batch", return_value={
                    "ok": True,
                    "items": [{"title": "电影A", "year": "2024"}],
                    "issues": [],
                    "ready_count": 1,
                }), \
                mock.patch.object(quick_import, "create_scraper_job_from_plan", return_value={"job_id": 11}), \
                mock.patch.object(quick_import, "submit_scraper_job", return_value=self._Future()), \
                mock.patch.object(quick_import, "_resolve_entry_after_organize", side_effect=lambda cid, summary, entry: entry), \
                mock.patch.object(scraper, "find_scraper_media_folder", return_value={}), \
                mock.patch.object(scraper, "move_scraper_entries", return_value={"monitor_sync": {"event_count": 1}}), \
                mock.patch.object(quick_import, "wait_monitor_run", wraps=monitor_runs.wait_run) as wait_run:
            result = quick_import.run_quick_import("test")

        wait_run.assert_called_once()
        self.assertEqual(result["left"][0]["reason_code"], "unrecognized")

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
                mock.patch.object(scraper, "find_scraper_media_folder", return_value={}), \
                mock.patch.object(scraper, "move_scraper_entries", return_value={}) as move:
            result = quick_import.run_quick_import("test")

        self.assertEqual(result["moved"][0]["target"], "电视剧")
        self.assertEqual(seen_options[0]["file_name_mode"], "keep")
        self.assertEqual(move.call_args.args[2], "cid:电视剧")

    def test_missing_target_keeps_item_in_inbox(self):
        cfg = _cfg(tasks=[_task("电影", "/115/电影")], inbox=_inbox_task(targets={"movie": "电影"}))
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
        self.assertEqual(result["left"][0]["reason_code"], "plan_conflict")

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
                mock.patch.object(scraper, "find_scraper_media_folder", return_value={}), \
                mock.patch.object(scraper, "move_scraper_entries", side_effect=RuntimeError("boom")):
            result = quick_import.run_quick_import("test")

        self.assertEqual(result["moved"], [])
        self.assertIn("搬运失败", result["left"][0]["reason"])
        self.assertEqual(result["left"][0]["reason_code"], "dispatch_failed")

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


    def test_cancel_request_only_works_while_running(self):
        self.assertFalse(quick_import.request_quick_import_cancel())
        self.assertTrue(quick_import._QUICK_IMPORT_RUN_LOCK.acquire(timeout=0))
        try:
            self.assertTrue(quick_import.request_quick_import_cancel())
            self.assertTrue(quick_import._QUICK_IMPORT_CANCEL.is_set())
        finally:
            quick_import._QUICK_IMPORT_CANCEL.clear()
            quick_import._QUICK_IMPORT_RUN_LOCK.release()
        self.assertFalse(quick_import.request_quick_import_cancel())

    def test_run_stops_when_cancel_requested(self):
        """点「中断」后：已整理完的保留，未处理的下一条目开始前停住并写 cancelled 记录。"""
        cfg = _cfg()
        identified = {
            "items": [_item(1, "电影A"), _item(2, "剧集B")],
            "picked": {
                1: {"id": 603, "media_type": "movie"},
                2: {"id": 1399, "media_type": "tv"},
            },
            "results": [
                {"item_index": 1, "status": "auto"},
                {"item_index": 2, "status": "auto"},
            ],
        }

        def identify_then_cancel(*args, **kwargs):
            # 模拟用户在识别阶段点了「中断」。
            quick_import._QUICK_IMPORT_CANCEL.set()
            return identified

        with mock.patch.object(quick_import, "get_config", return_value=cfg), \
                mock.patch.object(quick_import, "resolve_scraper_dest_folder_id", return_value="cid"), \
                mock.patch.object(quick_import, "identify_scraper_batch_entries", side_effect=identify_then_cancel), \
                mock.patch.object(quick_import, "build_scraper_plan_for_batch") as plan, \
                mock.patch.object(quick_import, "write_monitor_log_sync"):
            result = quick_import.run_quick_import("manual")

        self.assertTrue(result.get("cancelled"))
        plan.assert_not_called()
        self.assertIn("已中断", result["summary"])
        self.assertEqual(result["moved"], [])
        self.assertEqual([item["reason"] for item in result["left"]], ["已中断，未整理"] * 2)
        runs = quick_import.list_quick_import_runs(1)
        self.assertEqual(runs[0]["status"], "cancelled")
        self.assertFalse(quick_import._QUICK_IMPORT_CANCEL.is_set())


class QuickImportMergeIntoExistingFolderTest(unittest.TestCase):
    """目标监控目录里已有同名文件夹时，整理好的内容要并进去，而不是再搬一个同名文件夹过去。

    回归场景：接收夹里一次来了多个单集文件，每个文件各自整理成一个「片名 (年份)/」文件夹，
    整目录搬进监控目录时 115 会把后面几个自动改名成 「片名 (年份)(1)/(2)/(3)」。
    """

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

    def _run_once(
        self,
        *,
        existing_map=None,
        folder_children=None,
        folder_names=None,
        entry=None,
        options_sink=None,
    ):
        """跑一次快捷导入：接收夹里一个已整理好的「王子与乞丐 (2026)」文件夹。"""
        cfg = _cfg()
        inbox_entry = entry if isinstance(entry, dict) else {
            "id": "inbox-folder",
            "name": "王子与乞丐 (2026)",
            "is_dir": True,
        }
        identified = {
            "items": [_item(1, "王子与乞丐 (2026)")],
            "picked": {1: {"id": 328704, "media_type": "tv"}},
            "results": [{"item_index": 1, "status": "auto"}],
        }
        moves = []
        deletes = []
        children_by_cid = {str(key): list(value) for key, value in (folder_children or {}).items()}
        names_by_cid = {str(key): list(value) for key, value in (folder_names or {}).items()}

        def fake_list(provider, cid, *args, **kwargs):
            key = str(cid)
            if key in children_by_cid:
                return {"entries": [dict(child) for child in children_by_cid[key]]}
            if key in names_by_cid:
                return {
                    "entries": [
                        {"id": f"{key}-n{index}", "name": name, "is_dir": False}
                        for index, name in enumerate(names_by_cid[key])
                    ]
                }
            return {"entries": []}

        def fake_find(provider, parent_id, name):
            return dict((existing_map or {}).get((str(parent_id), str(name)), {}))

        def fake_move(provider, entry_ids, target_cid, **kwargs):
            moves.append({"entry_ids": list(entry_ids), "target_cid": target_cid, **kwargs})
            names_by_cid.setdefault(str(target_cid), []).extend(
                str(item.get("name", "") or "") for item in kwargs.get("entries") or []
            )
            return {}

        def fake_plan(provider, items, picked, options, **kwargs):
            if isinstance(options_sink, list):
                options_sink.append(dict(options))
            return {
                "ok": True,
                "items": [{"title": "王子与乞丐", "year": "2026"}],
                "issues": [],
                "ready_count": 1,
            }

        with mock.patch.object(quick_import, "get_config", return_value=cfg), \
                mock.patch.object(quick_import, "resolve_scraper_dest_folder_id", side_effect=lambda provider, path: f"cid:{path}"), \
                mock.patch.object(quick_import, "identify_scraper_batch_entries", return_value=identified), \
                mock.patch.object(quick_import, "build_scraper_plan_for_batch", side_effect=fake_plan), \
                mock.patch.object(quick_import, "create_scraper_job_from_plan", return_value={"job_id": 9}), \
                mock.patch.object(quick_import, "submit_scraper_job", return_value=self._Future()), \
                mock.patch.object(quick_import, "_resolve_entry_after_organize", return_value=inbox_entry), \
                mock.patch.object(scraper, "find_scraper_media_folder", side_effect=fake_find), \
                mock.patch.object(scraper, "list_scraper_entries", side_effect=fake_list), \
                mock.patch.object(scraper, "move_scraper_entries", side_effect=fake_move), \
                mock.patch.object(scraper, "delete_scraper_entries", side_effect=lambda *args, **kwargs: deletes.append(kwargs) or {}):
            result = quick_import.run_quick_import("test")
        return result, moves, deletes

    def test_episode_files_merge_into_existing_folder(self):
        result, moves, deletes = self._run_once(
            existing_map={("cid:电视剧", "王子与乞丐 (2026)"): {"id": "target-folder", "name": "王子与乞丐 (2026)"}},
            folder_children={
                "inbox-folder": [
                    {"id": "f1", "name": "王子与乞丐 (2026) - S01E01.mkv", "is_dir": False},
                    {"id": "f2", "name": "王子与乞丐 (2026) - S01E02.mkv", "is_dir": False},
                ]
            },
        )

        self.assertEqual(len(result["moved"]), 1)
        self.assertEqual(result["left"], [])
        # 只搬文件进已有文件夹，不再搬「片名 (年份)」文件夹本身
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0]["entry_ids"], ["f1", "f2"])
        self.assertEqual(moves[0]["target_cid"], "target-folder")
        self.assertEqual(moves[0]["target_parent_path"], "电视剧/王子与乞丐 (2026)")
        self.assertEqual(moves[0]["source_action"], "scraper-job:9:quick-import")
        self.assertEqual([item["path"] for item in moves[0]["entries"]], [
            "接收/王子与乞丐 (2026)/王子与乞丐 (2026) - S01E01.mkv",
            "接收/王子与乞丐 (2026)/王子与乞丐 (2026) - S01E02.mkv",
        ])
        # 接收夹里的空文件夹要清掉，避免每次导入都在接收夹留一个壳
        self.assertEqual(len(deletes), 1)
        self.assertEqual(deletes[0]["parent_id"], "cid:接收")
        self.assertEqual(deletes[0]["entries"][0]["id"], "inbox-folder")

    def test_duplicate_file_is_left_in_inbox(self):
        result, moves, deletes = self._run_once(
            existing_map={("cid:电视剧", "王子与乞丐 (2026)"): {"id": "target-folder", "name": "王子与乞丐 (2026)"}},
            folder_children={
                "inbox-folder": [{"id": "f1", "name": "王子与乞丐 (2026) - S01E01.mkv", "is_dir": False}]
            },
            folder_names={"target-folder": ["王子与乞丐 (2026) - S01E01.mkv"]},
        )

        self.assertEqual(result["moved"], [])
        self.assertEqual(moves, [])
        self.assertEqual(deletes, [])
        self.assertIn("已存在同名文件", result["left"][0]["reason"])

    def test_existing_destination_folder_skips_inbox_folder_rename(self):
        """目标监控目录已有这部剧的文件夹时，接收夹文件夹不必先改规范名。

        否则同批多个同名文件夹（片名 (2026) / (1) / (2)…）会互相撞成"当前目录中已有同名文件夹"，
        只能留在接收夹里——实测就是这样剩下一个没搬过去。
        """
        seen_options = []
        result, moves, deletes = self._run_once(
            existing_map={("cid:电视剧", "王子与乞丐 (2026)"): {"id": "target-folder", "name": "王子与乞丐 (2026)"}},
            folder_children={
                "inbox-folder": [{"id": "f1", "name": "王子与乞丐 (2026) - S01E01.mkv", "is_dir": False}]
            },
            options_sink=seen_options,
        )

        self.assertEqual(len(result["moved"]), 1)
        self.assertFalse(seen_options[0]["rename_selected_folders"])
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0]["target_cid"], "target-folder")

    def test_missing_destination_folder_keeps_folder_rename(self):
        """目标没有同名文件夹时保持原流程：先把接收夹文件夹改成规范名再整目录搬过去。"""
        seen_options = []
        result, moves, deletes = self._run_once(options_sink=seen_options)

        self.assertEqual(len(result["moved"]), 1)
        self.assertTrue(seen_options[0]["rename_selected_folders"])
        self.assertEqual(moves[0]["entry_ids"], ["inbox-folder"])

    def test_missing_folder_still_moves_whole_entry(self):
        result, moves, deletes = self._run_once()

        self.assertEqual(len(result["moved"]), 1)
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0]["entry_ids"], ["inbox-folder"])
        self.assertEqual(moves[0]["target_cid"], "cid:电视剧")
        self.assertEqual(moves[0]["target_parent_path"], "电视剧")
        self.assertEqual(deletes, [])

    def test_season_subfolder_merges_into_existing_season(self):
        result, moves, deletes = self._run_once(
            existing_map={
                ("cid:电视剧", "王子与乞丐 (2026)"): {"id": "target-folder", "name": "王子与乞丐 (2026)"},
                ("target-folder", "Season 01"): {"id": "season-folder", "name": "Season 01"},
            },
            folder_children={
                "inbox-folder": [{"id": "d1", "name": "Season 01", "is_dir": True}],
                "d1": [{"id": "f1", "name": "王子与乞丐 (2026) - S01E01.mkv", "is_dir": False}],
            },
        )

        self.assertEqual(len(result["moved"]), 1)
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0]["target_cid"], "season-folder")
        self.assertEqual(moves[0]["target_parent_path"], "电视剧/王子与乞丐 (2026)/Season 01")
        self.assertEqual(
            moves[0]["entries"][0]["path"],
            "接收/王子与乞丐 (2026)/Season 01/王子与乞丐 (2026) - S01E01.mkv",
        )
        # Season 01（已清空）和接收夹里那个空文件夹都要删掉
        self.assertEqual([item["entries"][0]["id"] for item in deletes], ["d1", "inbox-folder"])


if __name__ == "__main__":
    unittest.main()
