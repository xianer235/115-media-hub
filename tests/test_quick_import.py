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
        "distribute_targets": (
            dict(targets) if isinstance(targets, dict) else {"movie": "/115/电影", "tv": "/115/电视剧"}
        ),
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

    def test_same_provider_inbox_duplicates_collapse_to_one(self):
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

    def test_each_provider_keeps_its_own_inbox(self):
        """每个网盘一个接收夹：不同网盘各留一个，同网盘重复的只保留第一个。"""
        cfg = core.normalize_config(
            {
                "mount_points": [dict(item) for item in MOUNT_POINTS] + [{"provider": "quark", "prefix": "/quark"}],
                "monitor_tasks": [
                    {"name": "接收", "task_type": "inbox", "provider": "115", "scan_path": "/115/接收"},
                    {"name": "115第二个", "task_type": "inbox", "provider": "115", "scan_path": "/115/接收2"},
                    {"name": "夸克接收", "task_type": "inbox", "provider": "quark", "scan_path": "/quark/接收"},
                ],
            }
        )
        self.assertEqual([task["name"] for task in core.get_inbox_tasks(cfg)], ["接收", "夸克接收"])
        self.assertEqual([task["provider"] for task in core.get_inbox_tasks(cfg)], ["115", "quark"])

    def test_get_inbox_task_can_be_selected_by_name(self):
        cfg = core.normalize_config(
            {
                "mount_points": [dict(item) for item in MOUNT_POINTS] + [{"provider": "quark", "prefix": "/quark"}],
                "monitor_tasks": [
                    {"name": "接收", "task_type": "inbox", "provider": "115", "scan_path": "/115/接收"},
                    {"name": "夸克接收", "task_type": "inbox", "provider": "quark", "scan_path": "/quark/接收"},
                ],
            }
        )
        # 不传名字回退第一个（默认 115 那个）；传名字按名字取。
        self.assertEqual(core.get_inbox_task(cfg)["name"], "接收")
        self.assertEqual(core.get_inbox_task(cfg, "夸克接收")["provider"], "quark")
        self.assertEqual(core.get_inbox_task(cfg, "不存在的接收夹"), {})

    def test_non_115_inbox_cannot_keep_webhook_enabled(self):
        """Webhook 只对 115 的接收夹开放：手工改配置文件也留不下一个可用的 webhook。"""
        cfg = core.normalize_config(
            {
                "webhook_secret": "s3cret",
                "mount_points": [dict(item) for item in MOUNT_POINTS] + [{"provider": "quark", "prefix": "/quark"}],
                "monitor_tasks": [
                    {
                        "name": "接收",
                        "task_type": "inbox",
                        "provider": "115",
                        "scan_path": "/115/接收",
                        "webhook_enabled": True,
                    },
                    {
                        "name": "夸克接收",
                        "task_type": "inbox",
                        "provider": "quark",
                        "scan_path": "/quark/接收",
                        "webhook_enabled": True,
                    },
                ],
            }
        )
        self.assertTrue(core.get_inbox_task(cfg, "接收")["webhook_enabled"])
        self.assertFalse(core.get_inbox_task(cfg, "夸克接收")["webhook_enabled"])

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
        # 旧值「电影」是监控任务名：归一化迁移成该任务的扫描路径。
        self.assertEqual(inbox["distribute_targets"], {"movie": "/115/电影"})
        # 用户手动关掉的 webhook 不会被归一化重新打开。
        self.assertFalse(inbox["webhook_enabled"])

    def test_inbox_throttle_fields_have_defaults(self):
        cfg = core.normalize_config({})
        inbox = core.get_inbox_task(cfg)
        self.assertEqual(inbox["inbox_idle_seconds"], 120)
        self.assertEqual(inbox["inbox_max_items_per_run"], 100)
        self.assertEqual(inbox["inbox_batch_pause_seconds"], 5)

    def test_inbox_throttle_fields_clamp_to_supported_ranges(self):
        cfg = core.normalize_config(
            {
                "monitor_tasks": [
                    {
                        "name": "接收",
                        "task_type": "inbox",
                        "scan_path": "/115/接收",
                        "inbox_idle_seconds": 99999,
                        "inbox_max_items_per_run": 0,
                        "inbox_batch_pause_seconds": 99999,
                    }
                ]
            }
        )
        inbox = core.get_inbox_task(cfg)
        self.assertEqual(inbox["inbox_idle_seconds"], 3600)
        self.assertEqual(inbox["inbox_max_items_per_run"], 1)
        self.assertEqual(inbox["inbox_batch_pause_seconds"], 300)

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
        # 迁移把「任务名」换算成任务 scan_path（带 /115 前缀的远程路径）。
        self.assertEqual(inbox["distribute_targets"], {"movie": "/115/电影", "tv": "/115/电视剧"})
        for task in cfg["monitor_tasks"]:
            self.assertEqual(task["quick_import_target"], "")

    def test_migration_clears_unknown_target_name(self):
        """目标既不是远程路径、也匹配不到任何扫描任务时清空，交给校验提示用户重选。"""
        cfg = core.normalize_config(
            {
                "monitor_tasks": [
                    {
                        "name": "我的接收",
                        "task_type": "inbox",
                        "scan_path": "/115/接收",
                        "distribute_targets": {"movie": "已经被删掉的任务"},
                    }
                ]
            }
        )
        self.assertEqual(core.get_inbox_task(cfg)["distribute_targets"], {})

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
        self.assertEqual(conf["provider"], "115")
        self.assertEqual(conf["inbox_rel"], "接收")
        self.assertEqual(conf["targets"]["movie"]["scan_path"], "/115/电影")
        self.assertEqual(conf["targets"]["movie"]["scan_rel"], "电影")
        self.assertEqual(conf["targets"]["tv"]["scan_path"], "/115/电视剧")
        self.assertEqual(conf["targets"]["tv"]["scan_rel"], "电视剧")

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
            inbox=_inbox_task(targets={"movie": "/115/接收/电影"}),
        )
        self.assertIn("重叠", quick_import.validate_quick_import_config(overlap) or "")
        same = _cfg(
            tasks=[_task("就是接收夹", "/115/接收")],
            inbox=_inbox_task(targets={"movie": "/115/接收"}),
        )
        self.assertIn("重叠", quick_import.validate_quick_import_config(same) or "")

    def test_target_scrape_options_come_from_inbox_task(self):
        # 整理选项不再继承扫描任务；用接收夹任务自己的 auto_scrape_options。
        inbox = _inbox_task(auto_scrape_options={"file_name_mode": "keep", "title_language": "en"})
        conf = quick_import.build_quick_import_config(_cfg(inbox=inbox))
        options = quick_import._target_scrape_options(conf["targets"]["tv"])
        self.assertEqual(options["file_name_mode"], "keep")
        self.assertEqual(options["title_language"], "en")
        self.assertIn("delete_ad_files", options)

    def test_inbox_provider_drives_targets_and_savepath(self):
        """接收夹可以挂在任意网盘：provider 决定路径解析与 savepath 归属。"""
        cfg = {
            "mount_points": [dict(item) for item in MOUNT_POINTS] + [{"provider": "quark", "prefix": "/quark"}],
            "monitor_tasks": [
                _task("电影", "/115/电影"),
                _inbox_task(
                    name="夸克接收",
                    path="/quark/接收",
                    provider="quark",
                    targets={"movie": "/quark/电影"},
                ),
            ],
        }
        conf = quick_import.build_quick_import_config(cfg)
        self.assertEqual(conf["provider"], "quark")
        self.assertEqual(conf["inbox_rel"], "接收")
        self.assertEqual(conf["targets"]["movie"]["scan_rel"], "电影")
        # savepath 是网盘相对路径，provider 由接收夹任务内部决定。
        self.assertTrue(quick_import.is_quick_import_savepath(cfg, "接收/片名"))
        self.assertFalse(quick_import.is_quick_import_savepath(cfg, "电影/片名"))

    def test_cross_provider_target_reports_same_provider_hint(self):
        """目标落在别的网盘时要说清「必须和接收夹同盘」，不能只说「没指定目标」。"""
        cfg = {
            "mount_points": [dict(item) for item in MOUNT_POINTS] + [{"provider": "quark", "prefix": "/quark"}],
            "monitor_tasks": [
                _inbox_task(
                    name="夸克接收",
                    path="/quark/接收",
                    provider="quark",
                    targets={"movie": "/115/电影", "tv": "/quark/电视剧"},
                ),
            ],
        }
        message = quick_import.validate_quick_import_config(cfg) or ""
        self.assertIn("同一网盘", message)
        self.assertIn("电影", message)
        self.assertIn("quark", message)


class MultiInboxFanoutTest(unittest.TestCase):
    """每个网盘一个接收夹：状态与整理都要按接收夹分别处理，不能互相串号。"""

    @staticmethod
    def _two_provider_cfg():
        return {
            "mount_points": [dict(item) for item in MOUNT_POINTS] + [{"provider": "quark", "prefix": "/quark"}],
            "monitor_tasks": [
                _task("电影", "/115/电影"),
                _inbox_task(name="接收", path="/115/接收", provider="115", targets={"movie": "/115/电影"}),
                _inbox_task(name="夸克接收", path="/quark/接收", provider="quark", targets={"movie": "/quark/电影"}),
            ],
        }

    def test_status_snapshot_is_built_per_inbox(self):
        cfg = self._two_provider_cfg()
        with mock.patch.object(quick_import, "latest_monitor_run_progress", return_value={}), \
                mock.patch.object(quick_import, "list_quick_import_runs", return_value=[]), \
                mock.patch.object(quick_import, "list_inbox_recent_jobs", return_value=[]), \
                mock.patch.object(quick_import, "count_inbox_recent_jobs", return_value=0):
            first = quick_import._build_inbox_status(cfg, core.get_inbox_tasks(cfg)[0])
            second = quick_import._build_inbox_status(cfg, core.get_inbox_tasks(cfg)[1])
        self.assertEqual(first["task_name"], "接收")
        self.assertEqual(first["provider"], "115")
        self.assertIsNone(first["config_error"] or None)
        self.assertEqual(second["task_name"], "夸克接收")
        self.assertEqual(second["provider"], "quark")
        self.assertEqual(second["targets"]["movie"]["target_path"], "/quark/电影")

    def test_status_lists_every_inbox(self):
        cfg = self._two_provider_cfg()
        with mock.patch.object(quick_import, "get_config", return_value=cfg), \
                mock.patch.object(quick_import, "latest_monitor_run_progress", return_value={}), \
                mock.patch.object(quick_import, "list_quick_import_runs", return_value=[]), \
                mock.patch.object(quick_import, "list_inbox_recent_jobs", return_value=[]), \
                mock.patch.object(quick_import, "count_inbox_recent_jobs", return_value=0):
            status = quick_import.get_quick_import_status()
        self.assertEqual([item["task_name"] for item in status["inboxes"]], ["接收", "夸克接收"])

    def test_status_snapshot_carries_per_inbox_activity(self):
        """每张卡片只显示自己那份最近运行 / 最近接收，不能透传第一条或全局值。"""
        cfg = self._two_provider_cfg()
        runs_by_path = {"/115/接收": [{"id": 9, "summary": "115 的整理"}], "/quark/接收": []}

        def fake_runs(limit=20, inbox_path=""):
            return runs_by_path.get(inbox_path, [])

        with mock.patch.object(quick_import, "list_quick_import_runs", side_effect=fake_runs), \
                mock.patch.object(quick_import, "list_inbox_recent_jobs", return_value=[]), \
                mock.patch.object(quick_import, "count_inbox_recent_jobs", return_value=0), \
                mock.patch.object(quick_import, "latest_monitor_run_progress", return_value={}):
            first = quick_import._build_inbox_status(cfg, core.get_inbox_tasks(cfg)[0])
            second = quick_import._build_inbox_status(cfg, core.get_inbox_tasks(cfg)[1])
        self.assertEqual(first["latest"]["id"], 9)
        self.assertEqual(second["latest"], {})
        self.assertIn("recent_job_count_24h", first)
        self.assertIn("running", second)
        self.assertFalse(second["running"])
        self.assertEqual(first["latest_detail"], {})

    def test_task_running_is_scoped_by_name(self):
        quick_import._INBOX_RUNNING_TASK["name"] = ""
        quick_import._QUICK_IMPORT_CANCEL.clear()
        quick_import._QUICK_IMPORT_CANCEL_TASKS.clear()
        if not quick_import._QUICK_IMPORT_RUN_LOCK.acquire(timeout=0):
            self.fail("整理锁没被释放，测试状态被污染了")
        try:
            quick_import._INBOX_RUNNING_TASK["name"] = "夸克接收"
            self.assertTrue(quick_import.quick_import_task_running("夸克接收"))
            self.assertFalse(quick_import.quick_import_task_running("接收"))
            quick_import.request_quick_import_cancel("夸克接收")
            self.assertTrue(quick_import.quick_import_task_cancelling("夸克接收"))
            self.assertFalse(quick_import.quick_import_task_cancelling("接收"))
        finally:
            quick_import._INBOX_RUNNING_TASK["name"] = ""
            quick_import._QUICK_IMPORT_CANCEL.clear()
            quick_import._QUICK_IMPORT_CANCEL_TASKS.clear()
            quick_import._QUICK_IMPORT_RUN_LOCK.release()

    def test_inbox_delay_uses_target_inbox_idle_seconds(self):
        """静默窗口按接收夹各自读取，不能所有盘都用第一个接收夹的配置。"""
        cfg = self._two_provider_cfg()
        cfg["monitor_tasks"][1]["inbox_idle_seconds"] = 11
        cfg["monitor_tasks"][2]["inbox_idle_seconds"] = 22
        with mock.patch.object(quick_import, "get_config", return_value=cfg):
            self.assertEqual(quick_import._inbox_delay_seconds("接收"), 11)
            self.assertEqual(quick_import._inbox_delay_seconds("夸克接收"), 22)

    def test_run_loops_every_enabled_inbox_and_skips_disabled(self):
        cfg = self._two_provider_cfg()
        cfg["monitor_tasks"].append(
            _inbox_task(name="停用的接收夹", path="/quark/停用", provider="quark", enabled=False)
        )
        seen = []

        def fake_run(cfg_arg, inbox, **kwargs):
            seen.append(inbox["name"])
            return {"run_id": len(seen), "moved": [{"name": inbox["name"]}], "left": [], "summary": f"{inbox['name']} 完成"}

        with mock.patch.object(quick_import, "get_config", return_value=cfg), \
                mock.patch.object(quick_import, "_run_inbox_quick_import", side_effect=fake_run):
            result = quick_import.run_quick_import("manual")

        self.assertEqual(seen, ["接收", "夸克接收"])
        self.assertFalse(result.get("skipped"))
        self.assertEqual(len(result["moved"]), 2)
        self.assertEqual(len(result["results"]), 2)

    def test_one_inbox_failure_does_not_stop_the_others(self):
        cfg = self._two_provider_cfg()

        def fake_run(cfg_arg, inbox, **kwargs):
            if inbox["name"] == "夸克接收":
                raise RuntimeError("boom")
            return {"run_id": 1, "moved": [], "left": [], "summary": "ok"}

        with mock.patch.object(quick_import, "get_config", return_value=cfg), \
                mock.patch.object(quick_import, "_run_inbox_quick_import", side_effect=fake_run):
            result = quick_import.run_quick_import("manual")

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["errors"][0]["task_name"], "夸克接收")

    def test_manual_trigger_only_runs_target_inbox(self):
        cfg = self._two_provider_cfg()
        seen = []

        def fake_run(cfg_arg, inbox, **kwargs):
            seen.append(inbox["name"])
            return {"run_id": len(seen), "moved": [], "left": [], "summary": "ok"}

        with mock.patch.object(quick_import, "get_config", return_value=cfg), \
                mock.patch.object(quick_import, "_run_inbox_quick_import", side_effect=fake_run):
            result = quick_import.run_quick_import("manual", task_names={"夸克接收"})
        self.assertEqual(seen, ["夸克接收"])
        self.assertTrue(result.get("ok"))

    def test_unknown_task_name_skips_without_error(self):
        cfg = self._two_provider_cfg()
        with mock.patch.object(quick_import, "get_config", return_value=cfg), \
                mock.patch.object(quick_import, "_run_inbox_quick_import") as runner:
            result = quick_import.run_quick_import("manual", task_names={"不存在的接收夹"})
        self.assertTrue(result.get("skipped"))
        # 只有锁冲突才该被工作线程重试；这种「没命中接收夹」不能被当锁超时反复空转。
        self.assertEqual(result.get("reason"), "no_targets")
        runner.assert_not_called()

    def test_worker_loop_does_not_retry_no_targets(self):
        """已停用 / 不存在的接收夹返回 skipped 时不能被当锁超时反复重试（否则 5 秒空转一轮）。"""
        calls = []

        def fake_run(trigger, **kwargs):
            calls.append(kwargs.get("task_names"))
            return {
                "ok": True,
                "skipped": True,
                "reason": "no_targets",
                "summary": "没有需要整理的接收夹",
            }

        with quick_import._INBOX_TRIGGER_LOCK:
            quick_import._INBOX_TRIGGER_STATE.update(
                {"worker": None, "pending_tasks": set(), "trigger": "", "source_ref": ""}
            )
        with mock.patch.object(quick_import, "run_quick_import", side_effect=fake_run), \
                mock.patch.object(quick_import, "_wait_for_inbox_next_run"):
            quick_import._inbox_worker_loop("manual", "", {"夸克接收"})
        self.assertEqual(calls, [{"夸克接收"}])

    def test_cancel_only_affects_target_inbox(self):
        quick_import._QUICK_IMPORT_CANCEL.clear()
        quick_import._QUICK_IMPORT_CANCEL_TASKS.clear()
        quick_import._QUICK_IMPORT_RUN_LOCK.acquire()
        try:
            self.assertTrue(quick_import.request_quick_import_cancel("夸克接收"))
            self.assertTrue(quick_import._inbox_task_cancelled("夸克接收"))
            self.assertFalse(quick_import._inbox_task_cancelled("接收"))
        finally:
            quick_import._QUICK_IMPORT_RUN_LOCK.release()
            quick_import._QUICK_IMPORT_CANCEL.clear()
            quick_import._QUICK_IMPORT_CANCEL_TASKS.clear()


class InboxAttributionTest(unittest.TestCase):
    """同名路径跨网盘时，导入落点与最近接收记录要按接收夹归属判定。"""

    def test_match_quick_import_inbox_respects_provider(self):
        cfg = MultiInboxFanoutTest._two_provider_cfg()
        self.assertEqual(
            str(quick_import.match_quick_import_inbox(cfg, "接收", provider="115").get("name", "")),
            "接收",
        )
        self.assertEqual(
            # 两个网盘的接收夹相对路径都是「接收」时，只有 provider 能区分归属。
            str(quick_import.match_quick_import_inbox(cfg, "接收", provider="quark").get("name", "")),
            "夸克接收",
        )
        # 相对路径落在别的网盘那个接收夹上时不算命中。
        other = MultiInboxFanoutTest._two_provider_cfg()
        other["monitor_tasks"][2]["scan_path"] = "/quark/夸克接收"
        self.assertEqual(quick_import.match_quick_import_inbox(other, "接收", provider="quark"), {})
        self.assertEqual(
            str(quick_import.match_quick_import_inbox(other, "夸克接收/子目录", provider="quark").get("name", "")),
            "夸克接收",
        )

    def test_match_quick_import_inbox_skips_disabled(self):
        cfg = MultiInboxFanoutTest._two_provider_cfg()
        cfg["monitor_tasks"][1]["enabled"] = False
        self.assertEqual(quick_import.match_quick_import_inbox(cfg, "接收", provider="115"), {})

    def test_is_quick_import_savepath_provider_scoped(self):
        cfg = MultiInboxFanoutTest._two_provider_cfg()
        self.assertTrue(quick_import.is_quick_import_savepath(cfg, "接收/片名", provider="115"))
        self.assertTrue(quick_import.is_quick_import_savepath(cfg, "接收/片名", provider="quark"))
        self.assertFalse(quick_import.is_quick_import_savepath(cfg, "接收/片名", provider="aliyun"))
        self.assertFalse(quick_import.is_quick_import_savepath(cfg, "电影/片名", provider="115"))


class InboxRecentJobsAttributionTest(unittest.TestCase):
    """resource_jobs 落库带接收夹归属，最近接收统计按归属过滤。"""

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

    def test_recent_jobs_filter_by_inbox_task_name(self):
        from app.resource_jobs import create_resource_jobs

        create_resource_jobs([
            (
                {"title": "115 的", "link_url": "magnet:?xt=urn:btih:AAA", "link_type": "magnet"},
                {"savepath": "接收", "inbox_task_name": "接收", "extra": {"quick_import_inbox": 1}},
            ),
            (
                {"title": "夸克的", "link_url": "magnet:?xt=urn:btih:BBB", "link_type": "magnet"},
                {"savepath": "接收", "inbox_task_name": "夸克接收", "extra": {"quick_import_inbox": 1}},
            ),
        ])
        only_115 = quick_import.list_inbox_recent_jobs("接收", 3, task_name="接收")
        self.assertEqual([job["title"] for job in only_115], ["115 的"])
        self.assertEqual(quick_import.count_inbox_recent_jobs("接收", 24, task_name="夸克接收"), 1)
        self.assertEqual(
            len(quick_import.list_inbox_recent_jobs("接收", 5)),
            2,
            "不传任务名时保持旧行为（只按路径统计）",
        )

    def test_find_existing_resource_job_scopes_by_inbox(self):
        from app.resource_jobs import create_resource_jobs, find_existing_resource_job

        resource = {"title": "同链接", "link_url": "magnet:?xt=urn:btih:CCC", "link_type": "magnet"}
        create_resource_jobs([
            (dict(resource), {"savepath": "接收", "inbox_task_name": "接收"}),
        ])
        self.assertTrue(find_existing_resource_job(resource, "接收", "接收"))
        self.assertEqual(find_existing_resource_job(resource, "接收", "夸克接收"), {})
        self.assertTrue(
            find_existing_resource_job(resource, "接收"),
            "不传接收夹时保持旧行为（只在路径维度查）",
        )


class InboxStagingGraceTest(unittest.TestCase):
    """转存/离线落盘滞后时，接收夹整理要先等一等再判定为空。"""

    def test_wait_for_inbox_children_rescans_until_content_appears(self):
        with mock.patch.object(
            quick_import, "_list_inbox_children", side_effect=[[], [], [{"id": "1", "name": "片名"}]]
        ) as lister, mock.patch.object(quick_import.time, "sleep") as sleeper:
            children = quick_import._wait_for_inbox_children("cid", "115")
        self.assertEqual([item["id"] for item in children], ["1"])
        self.assertEqual(lister.call_count, 3)
        self.assertEqual(sleeper.call_count, 2)

    def test_wait_for_inbox_children_gives_up_after_max_attempts(self):
        with mock.patch.object(quick_import, "_list_inbox_children", return_value=[]) as lister, \
                mock.patch.object(quick_import.time, "sleep"):
            children = quick_import._wait_for_inbox_children("cid", "115")
        self.assertEqual(children, [])
        self.assertEqual(lister.call_count, quick_import.INBOX_STAGING_MAX_ATTEMPTS)

    def test_empty_inbox_run_reports_staging_wait(self):
        cfg = MultiInboxFanoutTest._two_provider_cfg()
        inbox = core.get_inbox_task(cfg, "接收")
        identified = {"items": [], "picked": {}, "results": []}
        with mock.patch.object(quick_import, "resolve_scraper_dest_folder_id", return_value="cid"), \
                mock.patch.object(quick_import, "identify_scraper_batch_entries", return_value=identified), \
                mock.patch.object(quick_import, "_wait_for_inbox_children", return_value=[]), \
                mock.patch.object(quick_import, "_insert_quick_import_run", return_value=7), \
                mock.patch.object(quick_import, "create_monitor_run", return_value="run-1"), \
                mock.patch.object(quick_import, "start_monitor_run"), \
                mock.patch.object(quick_import, "finish_monitor_run"), \
                mock.patch.object(quick_import, "_finish_quick_import_run"):
            result = quick_import._run_inbox_quick_import(cfg, inbox)
        self.assertIn("已等待", result["summary"])
        self.assertEqual(result["moved"], [])


class MonitorTaskTypeConstraintTest(unittest.TestCase):
    """同名任务类型不可更改；接收夹可以按网盘新增（每个网盘一个），扫描任务照旧。"""

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

    def test_new_inbox_task_is_allowed(self):
        """接收夹不再写死单例：可以按网盘新增，保存后由 ensure_inbox_task 按 provider 去重。"""
        existing = [{"name": "接收", "task_type": "inbox"}]
        posted = [
            {"name": "接收", "task_type": "inbox"},
            {"name": "夸克接收", "task_type": "inbox", "provider": "quark"},
        ]

        result = core.apply_task_type_constraints(existing, posted)

        by_name = {task["name"]: task for task in result}
        self.assertEqual(by_name["夸克接收"]["task_type"], "inbox")

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

    def test_season_pack_expands_into_show_season_folder(self):
        """发布式整季文件夹按集展开到 片名 (年份)/Season NN/，不再整包改名撞车。"""
        season_name = "Curb.Your.Enthusiasm.S09.1080p.WEBRip.x265-RARBG"
        season_entry = {
            "id": "s9",
            "name": season_name,
            "is_dir": True,
            "parent_id": "inbox",
            "parent_path": "接收",
            "path": f"接收/{season_name}",
        }
        files = [
            {
                "id": f"f{episode:02d}",
                "name": f"Curb.Your.Enthusiasm.S09E{episode:02d}.1080p.WEBRip.x265-RARBG.mkv",
                "is_dir": False,
                "size": 1,
                "parent_id": "s9",
            }
            for episode in (1, 2)
        ]
        files.append(
            {
                "id": "ad1",
                "name": "RARBG.txt",
                "is_dir": False,
                "size": 30,
                "parent_id": "s9",
            }
        )
        tmdb = {
            "tmdb_id": 4546,
            "tmdb_media_type": "tv",
            "tmdb_title": "抑制热情",
            "tmdb_localized_title": "抑制热情",
            "tmdb_original_title": "Curb Your Enthusiasm",
            "tmdb_aliases": [],
            "tmdb_year": "2000",
            "tmdb_season_episode_map": {"9": 10},
            "tmdb_episode_mode": "seasonal",
        }

        def fake_list(provider, cookie, cid, folders_only=False, offset=0, limit=0):
            return {"entries": [dict(item) for item in files] if cid == "s9" else []}

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
                    "base_cid": "inbox",
                    "base_path": "接收",
                    "entries": [season_entry],
                    "tmdb": tmdb,
                    "options": {
                        "title_language": "zh",
                        "file_name_mode": "standard",
                        "selection_mode": "contents",
                        "season": 9,
                        "force_media_folder": True,
                        "season_pack": True,
                        "include_tmdb_id": True,
                        "use_season_subfolder": True,
                    },
                }
            )

        self.assertEqual(plan["issues"], [])
        self.assertFalse(any(action.get("is_dir") for action in plan["actions"]))
        self.assertEqual(
            sorted(action["new_path"] for action in plan["actions"]),
            [
                "接收/抑制热情 (2000) [tmdbid-4546]/Season 09/RARBG.txt",
                "接收/抑制热情 (2000) [tmdbid-4546]/Season 09/抑制热情 (2000) - S09E01.mkv",
                "接收/抑制热情 (2000) [tmdbid-4546]/Season 09/抑制热情 (2000) - S09E02.mkv",
            ],
        )

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


class MonitorAutoScrapeRemovedTest(unittest.TestCase):
    """监控不再自动整理：旧的自动刮削入口整段删除，整理改由接收夹 / 订阅自理。"""

    def test_monitor_module_has_no_auto_scrape_helper(self):
        self.assertFalse(hasattr(monitor_service, "_auto_scrape_new_media_items"))

    def test_normalize_task_drops_scan_auto_scrape_fields(self):
        scan = core.normalize_task(
            {
                "name": "电影",
                "scan_path": "/115/电影",
                "auto_scrape_on_new": True,
                "auto_scrape_options": {"file_name_mode": "keep"},
            }
        )
        self.assertEqual(scan["task_type"], "scan")
        self.assertNotIn("auto_scrape_on_new", scan)
        self.assertEqual(scan["auto_scrape_options"], {})


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
        # 子任务排队走的是真实监控队列；这里固定成一条假 run，避免测试里真的派发后台任务。
        self._child_run_patcher = mock.patch.object(
            quick_import,
            "_queue_dispatch_child_runs",
            return_value={"电影": "child-run-1", "电视剧": "child-run-1", "电视剧监控": "child-run-1"},
        )
        self._child_run_mock = self._child_run_patcher.start()

    def tearDown(self):
        self._child_run_patcher.stop()
        db.DB_PATH = self.original_db_path
        db._DB_ENSURED = self.original_db_ensured
        self.tmpdir.cleanup()

    def test_moves_movie_and_keeps_unmatched(self):
        cfg = _cfg(inbox=_inbox_task(auto_scrape_options={"file_name_mode": "standard"}))
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
                "items": [
                    {
                        "item_index": 1,
                        "title": "电影A",
                        "year": "2024",
                        "total": 1,
                        "ready": 1,
                        "issue_count": 0,
                    }
                ],
                "actions": [
                    {
                        "item_index": 1,
                        "action_index": 1,
                        "entry_id": "e1",
                        "is_dir": False,
                        "ready": True,
                        "issue": "",
                        "new_path": "接收/电影A (2024).mkv",
                    }
                ],
                "issues": [],
                "ready_count": 1,
            }

        with mock.patch.object(quick_import, "get_config", return_value=cfg), \
                mock.patch.object(quick_import, "resolve_scraper_dest_folder_id", side_effect=lambda provider, path: f"cid:{path}"), \
                mock.patch.object(quick_import, "identify_scraper_batch_entries", return_value=identified), \
                mock.patch.object(quick_import, "build_scraper_plan_for_batch", side_effect=plan_side_effect), \
                mock.patch.object(quick_import, "create_scraper_job_from_plan", return_value={"job_id": 11}), \
                mock.patch.object(quick_import, "submit_scraper_job", return_value=self._Future()), \
                mock.patch.object(quick_import, "_resolve_entry_after_organize", side_effect=lambda cid, summary, entry, provider: entry), \
                mock.patch.object(scraper, "find_scraper_media_folder", return_value={}), \
                mock.patch.object(scraper, "move_scraper_entries", side_effect=lambda *args, **kwargs: move_record.append(kwargs) or {}):
            result = quick_import.run_quick_import("test")

        self.assertEqual(len(result["moved"]), 1)
        self.assertEqual(result["moved"][0]["target"], "电影")
        self.assertEqual(result["moved"][0]["task_name"], "/115/电影")
        self.assertEqual(len(result["left"]), 1)
        self.assertIn("未匹配", result["left"][0]["reason"])
        self.assertEqual(move_record[0]["source_action"], "scraper-job:11:quick-import")
        self.assertEqual(move_record[0]["target_parent_path"], "电影")
        self.assertEqual(seen_options[0]["file_name_mode"], "standard")
        # 接收夹里可能是散文件，必须强制整理进媒体文件夹
        self.assertTrue(seen_options[0]["force_media_folder"])

    def test_quark_inbox_dispatch_moves_with_quark_provider(self):
        """接收夹挂在夸克、目标目录里还没有同名文件夹时，整理搬运必须走夸克网盘。

        历史 bug：这条分支漏传 provider，`_move_entries_into_folder` 退回默认的 115，
        于是用夸克的文件 ID 去调 115 接口，分发必然失败。
        """
        quark_scan = {
            "name": "夸克电影",
            "task_type": "scan",
            "enabled": True,
            "scan_path": "/quark/电影",
            "target_path": "夸克电影",
        }
        cfg = _cfg(
            tasks=[quark_scan],
            inbox=_inbox_task(
                name="夸克接收",
                path="/quark/接收",
                provider="quark",
                targets={"movie": "/quark/电影"},
            ),
            mount_points=[{"provider": "115", "prefix": "/115"}, {"provider": "quark", "prefix": "/quark"}],
        )
        identified = {
            "items": [_item(1, "电影A")],
            "picked": {1: {"id": 603, "media_type": "movie"}},
            "results": [{"item_index": 1, "status": "auto"}],
        }
        move_providers = []

        def fake_move(provider, *args, **kwargs):
            move_providers.append(provider)
            return {"monitor_sync": {"event_count": 0}}

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
                mock.patch.object(quick_import, "_resolve_entry_after_organize", side_effect=lambda cid, summary, entry, provider: entry), \
                mock.patch.object(scraper, "find_scraper_media_folder", return_value={}), \
                mock.patch.object(scraper, "move_scraper_entries", side_effect=fake_move):
            result = quick_import.run_quick_import("test")

        self.assertEqual(len(result["moved"]), 1)
        self.assertEqual(move_providers, ["quark"])

    def test_quark_inbox_merge_lists_existing_folder_with_quark_provider(self):
        """夸克接收夹的一条散文件并入目标里已有的媒体文件夹时，列目标文件夹也要用夸克。"""
        quark_scan = {
            "name": "夸克电影",
            "task_type": "scan",
            "enabled": True,
            "scan_path": "/quark/电影",
            "target_path": "夸克电影",
        }
        cfg = _cfg(
            tasks=[quark_scan],
            inbox=_inbox_task(
                name="夸克接收",
                path="/quark/接收",
                provider="quark",
                targets={"movie": "/quark/电影"},
            ),
            mount_points=[{"provider": "115", "prefix": "/115"}, {"provider": "quark", "prefix": "/quark"}],
        )
        identified = {
            "items": [_item(1, "电影A (2024).mkv", is_dir=False)],
            "picked": {1: {"id": 603, "media_type": "movie"}},
            "results": [{"item_index": 1, "status": "auto"}],
        }
        list_providers = []

        def fake_list(provider, cid, folders_only=False, **kwargs):
            list_providers.append(provider)
            return {"entries": []}

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
                mock.patch.object(quick_import, "_resolve_entry_after_organize", side_effect=lambda cid, summary, entry, provider: entry), \
                mock.patch.object(scraper, "find_scraper_media_folder", return_value={"id": "existing-cid", "name": "电影A (2024)"}), \
                mock.patch.object(scraper, "move_scraper_entries", return_value={"monitor_sync": {"event_count": 0}}), \
                mock.patch.object(scraper, "list_scraper_entries", side_effect=fake_list):
            quick_import.run_quick_import("test")

        self.assertTrue(list_providers)
        self.assertEqual(set(list_providers), {"quark"})

    def test_batch_size_processes_all_items_without_rescan(self):
        cfg = _cfg(inbox=_inbox_task(inbox_max_items_per_run=1))
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

        def plan_side_effect(provider, items, picked, options, **kwargs):
            return {
                "ok": True,
                "items": [{"title": "片名", "year": "2024"}],
                "issues": [],
                "ready_count": 1,
            }

        try:
            identify_mock = mock.MagicMock(return_value=identified)
            with mock.patch.object(quick_import, "get_config", return_value=cfg), \
                    mock.patch.object(quick_import, "resolve_scraper_dest_folder_id", side_effect=lambda provider, path: f"cid:{path}"), \
                    mock.patch.object(quick_import, "identify_scraper_batch_entries", identify_mock), \
                    mock.patch.object(quick_import, "build_scraper_plan_for_batch", side_effect=plan_side_effect), \
                    mock.patch.object(quick_import, "create_scraper_job_from_plan", return_value={"job_id": 11}), \
                    mock.patch.object(quick_import, "submit_scraper_job", return_value=self._Future()), \
                    mock.patch.object(quick_import, "_resolve_entry_after_organize", side_effect=lambda cid, summary, entry, provider: entry), \
                    mock.patch.object(scraper, "find_scraper_media_folder", return_value={}), \
                    mock.patch.object(scraper, "move_scraper_entries", return_value={}):
                result = quick_import.run_quick_import("test")

            self.assertEqual(identify_mock.call_count, 1)
            self.assertEqual(len(result["moved"]), 2)
            self.assertEqual(result["left"], [])
            with quick_import._INBOX_TRIGGER_LOCK:
                self.assertFalse(quick_import._INBOX_TRIGGER_STATE.get("pending"))
                self.assertFalse(quick_import._INBOX_TRIGGER_STATE.get("continuation"))
        finally:
            with quick_import._INBOX_TRIGGER_LOCK:
                quick_import._INBOX_TRIGGER_STATE.update(
                    {"worker": None, "pending": False, "trigger": "", "source_ref": "", "continuation": False}
                )
            quick_import._INBOX_TRIGGER_EVENT.clear()

    def test_move_event_records_identification_mapping(self):
        # 运行记录要能看清「原文件名 → 识别为」，包括来源/置信度/理由/tmdb。
        cfg = _cfg()
        identified = {
            "items": [_item(1, "Musica.2024.mkv", is_dir=False)],
            "picked": {
                1: {
                    "id": 1171826,
                    "media_type": "movie",
                    "title": "朱弦玉磐",
                    "year": "2024",
                    "source": "ai",
                    "ai_confidence": 88,
                    "ai_reason": "片名与年份一致",
                }
            },
            "results": [{"item_index": 1, "status": "suggest"}],
        }
        events = []
        with mock.patch.object(quick_import, "get_config", return_value=cfg), \
                mock.patch.object(quick_import, "resolve_scraper_dest_folder_id", side_effect=lambda provider, path: f"cid:{path}"), \
                mock.patch.object(quick_import, "identify_scraper_batch_entries", return_value=identified), \
                mock.patch.object(quick_import, "build_scraper_plan_for_batch", return_value={
                    "ok": True,
                    "items": [{"title": "朱弦玉磐", "year": "2024"}],
                    "issues": [],
                    "ready_count": 1,
                }), \
                mock.patch.object(quick_import, "create_scraper_job_from_plan", return_value={"job_id": 11}), \
                mock.patch.object(quick_import, "submit_scraper_job", return_value=self._Future()), \
                mock.patch.object(quick_import, "_resolve_entry_after_organize", side_effect=lambda cid, summary, entry, provider: entry), \
                mock.patch.object(scraper, "find_scraper_media_folder", return_value={}), \
                mock.patch.object(scraper, "move_scraper_entries", return_value={}), \
                mock.patch.object(quick_import, "record_monitor_run_event", side_effect=lambda *args, **kwargs: events.append(kwargs)):
            result = quick_import.run_quick_import("test")

        self.assertEqual(len(result["moved"]), 1)
        move_events = [event for event in events if event.get("operation") in ("move", "merge")]
        self.assertEqual(len(move_events), 1)
        detail = move_events[0]["detail"]
        self.assertEqual(detail["original_name"], "Musica.2024.mkv")
        self.assertEqual(detail["match_source"], "AI 识别")
        self.assertEqual(detail["confidence"], 88)
        self.assertEqual(detail["match_reason"], "片名与年份一致")
        self.assertEqual(detail["tmdb_id"], 1171826)
        self.assertEqual(detail["identified_year"], "2024")
        # 这条是散文件识别：运行记录要能看出条目类型。
        self.assertEqual(detail["entry_type"], "file")

    def test_mixed_result_finishes_immediately_with_left_items(self):
        """留在接收夹的条目按部分完成定稿；STRM 同步由独立任务各自记录，父运行不再等待。"""
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
                mock.patch.object(quick_import, "_resolve_entry_after_organize", side_effect=lambda cid, summary, entry, provider: entry), \
                mock.patch.object(scraper, "find_scraper_media_folder", return_value={}), \
                mock.patch.object(scraper, "move_scraper_entries", return_value={"monitor_sync": {"event_count": 1}}), \
                mock.patch.object(quick_import, "finish_monitor_run", wraps=monitor_runs.finish_run) as finish_run:
            result = quick_import.run_quick_import("test")

        finish_run.assert_called_once()
        self.assertEqual(finish_run.call_args.kwargs["status"], "partial")
        stored = monitor_runs.get_run_detail(finish_run.call_args.args[0])["run"]
        self.assertEqual(stored["status"], "partial")
        self.assertNotIn("waiting_children", stored["result"])
        self.assertEqual(result["left"][0]["reason_code"], "unrecognized")

    def test_dispatch_without_child_run_still_finishes_immediately(self):
        """子任务没排上也不再让接收夹等待：记录只覆盖识别与整理移动。"""
        cfg = _cfg()
        identified = {
            "items": [_item(1, "电影A")],
            "picked": {1: {"id": 603, "media_type": "movie"}},
            "results": [{"item_index": 1, "status": "auto"}],
        }
        self._child_run_mock.return_value = {}

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
                mock.patch.object(quick_import, "_resolve_entry_after_organize", side_effect=lambda cid, summary, entry, provider: entry), \
                mock.patch.object(scraper, "find_scraper_media_folder", return_value={}), \
                mock.patch.object(scraper, "move_scraper_entries", return_value={"monitor_sync": {"event_count": 1}}), \
                mock.patch.object(quick_import, "finish_monitor_run", wraps=monitor_runs.finish_run) as finish_run:
            result = quick_import.run_quick_import("test")

        finish_run.assert_called_once()
        self.assertEqual(finish_run.call_args.kwargs["status"], "completed")
        stored = monitor_runs.get_run_detail(finish_run.call_args.args[0])["run"]
        self.assertEqual(stored["status"], "completed")
        self.assertEqual(result["moved"][0]["run_id"], "")

    def test_tv_uses_inbox_organize_options(self):
        # 电视剧整理选项取自接收夹任务，不再继承电视剧扫描任务的旧开关。
        cfg = _cfg(inbox=_inbox_task(auto_scrape_options={"file_name_mode": "keep"}))
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
                mock.patch.object(quick_import, "_resolve_entry_after_organize", side_effect=lambda cid, summary, entry, provider: entry), \
                mock.patch.object(scraper, "find_scraper_media_folder", return_value={}), \
                mock.patch.object(scraper, "move_scraper_entries", return_value={}) as move:
            result = quick_import.run_quick_import("test")

        self.assertEqual(result["moved"][0]["target"], "电视剧")
        self.assertEqual(seen_options[0]["file_name_mode"], "keep")
        self.assertEqual(move.call_args.args[2], "cid:电视剧")

    def test_missing_target_keeps_item_in_inbox(self):
        cfg = _cfg(tasks=[_task("电影", "/115/电影")], inbox=_inbox_task(targets={"movie": "/115/电影"}))
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

    def test_empty_leftover_folder_is_cleaned_instead_of_left(self):
        """接收夹里整理残留的空壳目录直接清理，不再报“识别失败、留在接收夹”。"""
        from app.services import monitor_runs

        cfg = _cfg()
        identified = {
            "items": [
                {
                    "item_index": 1,
                    "name": "交锋 (2026) [tmdbid-294486]",
                    "entry": {
                        "id": "ghost-folder",
                        "name": "交锋 (2026) [tmdbid-294486]",
                        "is_dir": True,
                        "path": "最近接收/交锋 (2026) [tmdbid-294486]",
                        "parent_id": "cid:最近接收",
                    },
                }
            ],
            "picked": {},
            "results": [{"item_index": 1, "status": "manual"}],
        }
        deletes = []
        with mock.patch.object(quick_import, "get_config", return_value=cfg), \
                mock.patch.object(quick_import, "resolve_scraper_dest_folder_id", side_effect=lambda provider, path: f"cid:{path}"), \
                mock.patch.object(quick_import, "identify_scraper_batch_entries", return_value=identified), \
                mock.patch.object(quick_import, "_folder_contains_files", return_value=False), \
                mock.patch.object(
                    scraper,
                    "delete_scraper_entries",
                    side_effect=lambda *args, **kwargs: deletes.append((args, kwargs)) or {},
                ):
            result = quick_import.run_quick_import("test")

        self.assertEqual(result["left"], [])
        self.assertEqual(len(deletes), 1)
        self.assertEqual(deletes[0][0][1], ["ghost-folder"])
        run = monitor_runs.list_runs(run_kind="inbox")["runs"][0]
        # 这一轮只清理了空壳目录、没有分发内容：按“无变化”定稿。
        self.assertEqual(run["status"], "no_change")
        events = monitor_runs.get_run_detail(run["id"])["events"]
        cleanup_events = [event for event in events if event.get("operation") == "cleanup"]
        self.assertEqual(len(cleanup_events), 1)
        self.assertEqual(cleanup_events[0]["status"], "completed")

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

    def test_conflicting_item_does_not_block_other_items(self):
        """同一批里某个条目冲突时只留它自己，其他条目照常整理分发。"""
        cfg = _cfg()
        identified = {
            "items": [_item(1, "电影A"), _item(2, "电影B")],
            "picked": {
                1: {"id": 603, "media_type": "movie"},
                2: {"id": 604, "media_type": "movie"},
            },
            "results": [
                {"item_index": 1, "status": "auto"},
                {"item_index": 2, "status": "auto"},
            ],
        }
        plan = {
            "ok": True,
            "items": [
                {
                    "item_index": 1,
                    "title": "电影A",
                    "year": "2026",
                    "media_type": "movie",
                    "total": 1,
                    "ready": 1,
                    "issue_count": 0,
                },
                {
                    "item_index": 2,
                    "title": "电影B",
                    "year": "2026",
                    "media_type": "movie",
                    "total": 1,
                    "ready": 0,
                    "issue_count": 1,
                },
            ],
            "actions": [
                {
                    "item_index": 1,
                    "action_index": 1,
                    "entry_id": "e1",
                    "is_dir": False,
                    "ready": True,
                    "issue": "",
                    "new_path": "接收/电影A (2026).mkv",
                }
            ],
            "issues": ["条目 #2 电影B：目标目录中已有同名文件"],
            "ready_count": 1,
        }
        created_plans = []
        dispatched = []

        def create_side_effect(payload):
            created_plans.append(payload["plan"])
            return {"job_id": 9}

        def dispatch_side_effect(entry, **kwargs):
            dispatched.append(dict(entry))
            return {"merged": False, "target_folder": "电影A (2026)", "monitor_sync_events": 0}

        with mock.patch.object(quick_import, "get_config", return_value=cfg), \
                mock.patch.object(quick_import, "resolve_scraper_dest_folder_id", return_value="cid"), \
                mock.patch.object(quick_import, "identify_scraper_batch_entries", return_value=identified), \
                mock.patch.object(quick_import, "build_scraper_plan_for_batch", return_value=plan), \
                mock.patch.object(quick_import, "create_scraper_job_from_plan", side_effect=create_side_effect), \
                mock.patch.object(quick_import, "submit_scraper_job", return_value=self._Future()), \
                mock.patch.object(
                    quick_import,
                    "_resolve_entry_after_organize",
                    side_effect=lambda cid, summary, entry, provider: entry,
                ), \
                mock.patch.object(quick_import, "_dispatch_organized_entry", side_effect=dispatch_side_effect):
            result = quick_import.run_quick_import("test")

        # 只提交没冲突的条目 1；条目 2 自己的原因留在接收夹。
        self.assertEqual(len(created_plans), 1)
        self.assertEqual([action["item_index"] for action in created_plans[0]["actions"]], [1])
        self.assertEqual([entry["id"] for entry in dispatched], ["e1"])
        self.assertEqual([item["name"] for item in result["moved"]], ["电影A"])
        self.assertEqual(len(result["left"]), 1)
        self.assertEqual(result["left"][0]["name"], "电影B")
        self.assertEqual(result["left"][0]["reason_code"], "plan_conflict")
        self.assertIn("目标目录中已有同名文件", result["left"][0]["reason"])

    def test_merged_same_title_item_skips_dispatch_and_cleans_source(self):
        """同一部影视的另一个条目已并进媒体文件夹：只登记合并 + 清理空壳，不单独搬运。"""
        cfg = _cfg()
        named = "功夫女足(2026)[tmdbid-1491920]"
        junk = "【发布组】功夫女足[高码版].Kung.Fu.Soccer.2026.2160p-PandaQT"
        identified = {
            "items": [_item(1, named), _item(2, junk)],
            "picked": {
                1: {"id": 1491920, "media_type": "movie"},
                2: {"id": 1491920, "media_type": "movie"},
            },
            "results": [
                {"item_index": 1, "status": "auto"},
                {"item_index": 2, "status": "auto"},
            ],
        }
        merged_folder = "功夫女足 (2026) [tmdbid-1491920]"
        plan = {
            "ok": True,
            "items": [
                {
                    "item_index": 1,
                    "title": "功夫女足",
                    "year": "2026",
                    "media_type": "movie",
                    "total": 1,
                    "ready": 1,
                    "issue_count": 0,
                    "merged_into_folder": "",
                },
                {
                    "item_index": 2,
                    "title": "功夫女足",
                    "year": "2026",
                    "media_type": "movie",
                    "total": 1,
                    "ready": 1,
                    "issue_count": 0,
                    "merged_into_folder": merged_folder,
                },
            ],
            "actions": [
                {
                    "item_index": 1,
                    "action_index": 1,
                    "entry_id": "e1",
                    "is_dir": True,
                    "ready": True,
                    "issue": "",
                    "new_path": f"接收/{merged_folder}",
                }
            ],
            "issues": [],
            "ready_count": 1,
        }
        dispatched = []
        cleanup_inputs = []

        def dispatch_side_effect(entry, **kwargs):
            dispatched.append(dict(entry))
            return {"merged": False, "target_folder": merged_folder, "monitor_sync_events": 0}

        def cleanup_side_effect(leftovers, **kwargs):
            cleanup_inputs.append(list(leftovers))
            return []

        with mock.patch.object(quick_import, "get_config", return_value=cfg), \
                mock.patch.object(quick_import, "resolve_scraper_dest_folder_id", return_value="cid"), \
                mock.patch.object(quick_import, "identify_scraper_batch_entries", return_value=identified), \
                mock.patch.object(quick_import, "build_scraper_plan_for_batch", return_value=plan), \
                mock.patch.object(quick_import, "create_scraper_job_from_plan", return_value={"job_id": 12}), \
                mock.patch.object(quick_import, "submit_scraper_job", return_value=self._Future()), \
                mock.patch.object(
                    quick_import,
                    "_resolve_entry_after_organize",
                    side_effect=lambda cid, summary, entry, provider: entry,
                ), \
                mock.patch.object(quick_import, "_dispatch_organized_entry", side_effect=dispatch_side_effect), \
                mock.patch.object(quick_import, "_retry_inbox_cleanup", side_effect=cleanup_side_effect):
            result = quick_import.run_quick_import("test")

        # 只有条目 1 触发搬运；条目 2 记为合并并把空壳交给清理。
        self.assertEqual([entry["id"] for entry in dispatched], ["e1"])
        self.assertEqual(len(result["left"]), 0)
        self.assertEqual([item["name"] for item in result["moved"]], [named, junk])
        self.assertEqual(len(cleanup_inputs), 1)
        self.assertEqual([item["id"] for item in cleanup_inputs[0]], ["e2"])
        inbox_run = monitor_runs.list_runs(run_kind="inbox")["runs"][0]
        merge_events = [
            event
            for event in monitor_runs.get_run_detail(inbox_run["id"])["events"]
            if event.get("operation") == "merge" and event.get("category") == "remote"
        ]
        self.assertEqual(len(merge_events), 1)
        self.assertEqual(merge_events[0]["detail"]["new_name"], merged_folder)
        self.assertEqual(merge_events[0]["detail"]["merged_into_folder"], merged_folder)

    def test_multi_season_pack_stays_in_inbox_with_reason(self):
        """多季合集（S01-S03）暂不自动拆分，明确留在接收夹等人工处理。"""
        cfg = _cfg()
        identified = {
            "items": [_item(1, "Show.S01-S03.1080p.WEB-DL")],
            "picked": {1: {"id": 1, "media_type": "tv"}},
            "results": [{"item_index": 1, "status": "auto"}],
        }
        with mock.patch.object(quick_import, "get_config", return_value=cfg), \
                mock.patch.object(quick_import, "identify_scraper_batch_entries", return_value=identified), \
                mock.patch.object(quick_import, "resolve_scraper_dest_folder_id", return_value="cid"), \
                mock.patch.object(quick_import, "build_scraper_plan_for_batch") as build:
            result = quick_import.run_quick_import("test")

        build.assert_not_called()
        self.assertEqual(result["moved"], [])
        self.assertEqual(result["left"][0]["reason_code"], "multi_season_pack")
        self.assertIn("多季合集", result["left"][0]["reason"])

    def test_season_packs_dispatch_show_folder_once_and_clean_source(self):
        """同剧多个整季包整理进同一个剧集文件夹，只搬运一次，源季包目录交给清理。"""
        cfg = _cfg()
        names = [
            "Curb.Your.Enthusiasm.S09.1080p.WEBRip.x265-RARBG",
            "Curb.Your.Enthusiasm.S10.1080p.WEBRip.x265-RARBG",
            "Curb.Your.Enthusiasm.S11.1080p.WEBRip.x265-RARBG",
        ]
        items = [_item(index + 1, name) for index, name in enumerate(names)]
        picked = {
            index + 1: {"id": 4546, "media_type": "tv", "title": "抑制热情", "year": "2000"}
            for index in range(len(names))
        }
        identified = {
            "items": items,
            "picked": picked,
            "results": [{"item_index": index + 1, "status": "auto"} for index in range(len(names))],
        }
        plan = {
            "ok": True,
            "items": [
                {"item_index": index + 1, "title": "抑制热情", "year": "2000"}
                for index in range(len(names))
            ],
            "issues": [],
            "ready_count": len(names),
        }
        show_folder = {
            "id": "show",
            "name": "抑制热情 (2000) [tmdbid-4546]",
            "is_dir": True,
            "parent_id": "inbox",
        }
        dispatch_calls = []
        cleanup_inputs = []

        def resolve_side_effect(cid, summary, entry, provider):
            return dict(show_folder) if not entry else entry

        def dispatch_side_effect(entry, **kwargs):
            dispatch_calls.append({"entry": dict(entry), **kwargs})
            return {
                "merged": True,
                "target_folder": "抑制热情 (2000) [tmdbid-4546]",
                "monitor_sync_events": 1,
            }

        def cleanup_side_effect(leftovers, **kwargs):
            cleanup_inputs.append(list(leftovers))
            return []

        with mock.patch.object(quick_import, "get_config", return_value=cfg), \
                mock.patch.object(quick_import, "resolve_scraper_dest_folder_id", side_effect=lambda provider, path: f"cid:{path}"), \
                mock.patch.object(quick_import, "identify_scraper_batch_entries", return_value=identified), \
                mock.patch.object(quick_import, "build_scraper_plan_for_batch", return_value=plan), \
                mock.patch.object(quick_import, "create_scraper_job_from_plan", return_value={"job_id": 11}), \
                mock.patch.object(quick_import, "submit_scraper_job", return_value=self._Future()), \
                mock.patch.object(quick_import, "_resolve_entry_after_organize", side_effect=resolve_side_effect), \
                mock.patch.object(quick_import, "_dispatch_organized_entry", side_effect=dispatch_side_effect), \
                mock.patch.object(quick_import, "_retry_inbox_cleanup", side_effect=cleanup_side_effect), \
                mock.patch.object(scraper, "find_scraper_media_folder", return_value={}):
            result = quick_import.run_quick_import("test")

        self.assertEqual(result["left"], [])
        self.assertEqual(len(result["moved"]), 3)
        # 三个整季包整理进同一个剧集文件夹，只触发一次搬运。
        self.assertEqual(len(dispatch_calls), 1)
        self.assertEqual(dispatch_calls[0]["entry"]["id"], "show")
        self.assertEqual(len(cleanup_inputs), 1)
        self.assertEqual(len(cleanup_inputs[0]), 3)
        # 整季包识别的是目录：运行记录要能看出条目类型。
        inbox_run = monitor_runs.list_runs(run_kind="inbox")["runs"][0]
        move_events = [
            event
            for event in monitor_runs.get_run_detail(inbox_run["id"])["events"]
            if event.get("operation") in ("move", "merge")
        ]
        self.assertTrue(move_events)
        self.assertTrue(all(event["detail"].get("entry_type") == "folder" for event in move_events))

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
                mock.patch.object(quick_import, "_resolve_entry_after_organize", side_effect=lambda cid, summary, entry, provider: entry), \
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
                mock.patch.object(quick_import, "_wait_for_inbox_children", return_value=[]), \
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
            quick_import._QUICK_IMPORT_CANCEL_TASKS.clear()
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
            quick_import.request_quick_import_cancel("接收")
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
        self._child_run_patcher = mock.patch.object(
            quick_import,
            "_queue_dispatch_child_runs",
            return_value={"电影": "child-run-1", "电视剧": "child-run-1", "电视剧监控": "child-run-1"},
        )
        self._child_run_mock = self._child_run_patcher.start()

    def tearDown(self):
        self._child_run_patcher.stop()
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
        delete_side_effect=None,
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
            source_cid = str(kwargs.get("source_cid", "") or "")
            moved_ids = {str(value) for value in entry_ids}
            if source_cid in children_by_cid:
                # 移动成功后源目录里就不该再有这些子项，模拟真实网盘状态。
                children_by_cid[source_cid] = [
                    child
                    for child in children_by_cid[source_cid]
                    if str(child.get("id", "") or "") not in moved_ids
                ]
            names_by_cid.setdefault(str(target_cid), []).extend(
                str(item.get("name", "") or "") for item in kwargs.get("entries") or []
            )
            return {}

        def fake_plan(provider, items, picked, options, **kwargs):
            if isinstance(options_sink, list):
                options_sink.append(dict(options))
            return {
                "ok": True,
                "items": [
                    {
                        "item_index": 1,
                        "title": "王子与乞丐",
                        "year": "2026",
                        "total": 1,
                        "ready": 1,
                        "issue_count": 0,
                    }
                ],
                "actions": [
                    {
                        "item_index": 1,
                        "action_index": 1,
                        "entry_id": "inbox-folder",
                        "is_dir": True,
                        "ready": True,
                        "issue": "",
                        "new_path": "接收/王子与乞丐 (2026)",
                    }
                ],
                "issues": [],
                "ready_count": 1,
            }

        delete_calls = {"count": 0}

        def fake_delete(*args, **kwargs):
            if isinstance(delete_side_effect, list):
                index = delete_calls["count"]
                delete_calls["count"] += 1
                effect = delete_side_effect[index] if index < len(delete_side_effect) else None
                if effect is not None:
                    raise effect
                deletes.append(kwargs)
                return {}
            if delete_side_effect is not None:
                raise delete_side_effect
            deletes.append(kwargs)
            return {}

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
                mock.patch.object(scraper, "delete_scraper_entries", side_effect=fake_delete):
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

    def test_cleanup_delete_failure_keeps_dispatch_success(self):
        """内容已经搬进目标、只是接收夹空目录没删掉时，不能判成“搬运失败、留在接收夹”。"""
        from app.services import monitor_runs

        result, moves, deletes = self._run_once(
            existing_map={("cid:电视剧", "王子与乞丐 (2026)"): {"id": "target-folder", "name": "王子与乞丐 (2026)"}},
            folder_children={
                "inbox-folder": [{"id": "s1", "name": "Season 01", "is_dir": True}],
                "s1": [{"id": "f1", "name": "王子与乞丐 (2026) - S01E01.mkv", "is_dir": False}],
            },
            delete_side_effect=RuntimeError("115 删除失败（webapi/proapi 均未成功）"),
        )

        self.assertEqual([item["name"] for item in result["moved"]], ["王子与乞丐 (2026)"])
        self.assertEqual(result["left"], [])
        self.assertEqual(deletes, [])
        inbox_run = monitor_runs.list_runs(run_kind="inbox")["runs"][0]
        self.assertEqual(inbox_run["status"], "completed")
        detail = monitor_runs.get_run_detail(inbox_run["id"])
        cleanup_events = [event for event in detail["events"] if event.get("operation") == "cleanup"]
        self.assertEqual(len(cleanup_events), 1)
        self.assertEqual(cleanup_events[0]["status"], "pending")
        # 记录的是没能删掉的接收夹残留目录。
        self.assertIn("王子与乞丐 (2026)", cleanup_events[0]["title"])

    def test_cleanup_retry_success_leaves_no_problem_event(self):
        """派发当下删除失败、本轮收尾重试清掉时，不应该再留下“删除失败/待清理”记录。"""
        from app.services import monitor_runs

        result, moves, deletes = self._run_once(
            existing_map={("cid:电视剧", "王子与乞丐 (2026)"): {"id": "target-folder", "name": "王子与乞丐 (2026)"}},
            folder_children={
                "inbox-folder": [{"id": "f1", "name": "王子与乞丐 (2026) - S01E01.mkv", "is_dir": False}]
            },
            delete_side_effect=[RuntimeError("115 删除失败（webapi/proapi 均未成功）"), None],
        )

        self.assertEqual(len(result["moved"]), 1)
        self.assertEqual(result["left"], [])
        self.assertEqual(len(deletes), 1)
        run = monitor_runs.list_runs(run_kind="inbox")["runs"][0]
        self.assertEqual(run["status"], "completed")
        events = monitor_runs.get_run_detail(run["id"])["events"]
        self.assertEqual([e for e in events if e.get("status") == "pending"], [])
        cleanup_events = [e for e in events if e.get("operation") == "cleanup"]
        self.assertEqual(len(cleanup_events), 1)
        self.assertEqual(cleanup_events[0]["status"], "completed")

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


class InboxTriggerCoordinatorTest(unittest.TestCase):
    """接收夹触发协调：执行中再触发只预约下一轮，不丢任何一次触发。"""

    def setUp(self):
        with quick_import._INBOX_TRIGGER_LOCK:
            quick_import._INBOX_TRIGGER_STATE.update(
                {"worker": None, "pending_tasks": set(), "trigger": "", "source_ref": ""}
            )

    def tearDown(self):
        with quick_import._INBOX_TRIGGER_LOCK:
            quick_import._INBOX_TRIGGER_STATE.update(
                {"worker": None, "pending_tasks": set(), "trigger": "", "source_ref": ""}
            )

    def _wait_worker(self, timeout: float = 5.0) -> bool:
        import threading
        import time

        deadline = time.time() + timeout
        while time.time() < deadline:
            with quick_import._INBOX_TRIGGER_LOCK:
                worker = quick_import._INBOX_TRIGGER_STATE.get("worker")
            if not (isinstance(worker, threading.Thread) and worker.is_alive()):
                return True
            time.sleep(0.02)
        return False

    def test_trigger_during_run_schedules_one_more_round(self):
        calls = []

        def fake_run(trigger, **kwargs):
            calls.append(trigger)
            if len(calls) == 1:
                queued = quick_import.notify_quick_import("offline", source_ref="resource:9")
                self.assertTrue(queued["queued"])
                self.assertTrue(queued["running"])
            return {"ok": True, "summary": "done"}

        with mock.patch.object(quick_import, "run_quick_import", side_effect=fake_run):
            first = quick_import.notify_quick_import("manual")
            self.assertTrue(first["started"])
            self.assertTrue(self._wait_worker())

        # 第一轮执行中收到的触发会在本轮结束后自动补跑一轮，而不是被丢弃。
        self.assertEqual(len(calls), 2)
        self.assertFalse(quick_import.pending_quick_import_rerun())

    def test_idle_trigger_starts_worker_immediately(self):
        calls = []

        with mock.patch.object(
            quick_import,
            "run_quick_import",
            side_effect=lambda trigger, **kwargs: calls.append(trigger) or {"ok": True},
        ):
            result = quick_import.notify_quick_import("cron")
            self.assertTrue(result["started"])
            self.assertTrue(self._wait_worker())

        self.assertEqual(calls, ["cron"])


class InboxDispatchChildRunTest(unittest.TestCase):
    """每个成功分发的条目都要有自己的 STRM 同步子任务（挂在父运行下）。"""

    def test_child_scope_prefers_media_folder(self):
        self.assertEqual(
            quick_import._dispatch_scan_scope_rel("电视剧", "如果还有明天 (2010)", True, {"merged": False}),
            "电视剧/如果还有明天 (2010)",
        )
        self.assertEqual(
            quick_import._dispatch_scan_scope_rel(
                "电影", "片名.mkv", False, {"merged": True, "target_folder": "片名 (2024)"}
            ),
            "电影/片名 (2024)",
        )
        # 散文件直接落在监控根目录时只能按任务目录整体刷新。
        self.assertEqual(
            quick_import._dispatch_scan_scope_rel("电影", "片名.mkv", False, {"merged": False}),
            "电影",
        )

    def test_child_scan_is_queued_as_independent_task(self):
        """分发出的扫描是独立记录：不挂接收夹父运行，来源由队列侧标注。"""
        config = {"mount_points": [dict(item) for item in MOUNT_POINTS]}
        with mock.patch("app.services.monitor.queue_inbox_dispatch_scan", return_value="child-1") as queued:
            run_id = quick_import._queue_dispatch_child_run(
                config,
                "115",
                "电视剧",
                "示例剧",
                True,
                {"merged": False},
            )

        self.assertEqual(run_id, "child-1")
        queued.assert_called_once_with(config, "电视剧/示例剧", "115")

    def test_queue_failure_does_not_break_dispatch(self):
        with mock.patch("app.services.monitor.queue_inbox_dispatch_scan", side_effect=RuntimeError("boom")):
            self.assertEqual(
                quick_import._queue_dispatch_child_run({}, "115", "电影", "片名", True, {"merged": False}),
                "",
            )

    def test_non_115_provider_never_refreshes_strm(self):
        """只有 115 才生成 STRM：其他网盘分发后只搬文件，不排队扫描。"""
        config = {"mount_points": [dict(item) for item in MOUNT_POINTS]}
        with mock.patch("app.services.monitor.queue_inbox_dispatch_scan") as queued:
            run_id = quick_import._queue_dispatch_child_run(
                config,
                "quark",
                "电视剧",
                "示例剧",
                True,
                {"merged": False},
            )
            mapping = quick_import._queue_dispatch_child_runs(config, "quark", ["电视剧/示例剧/S01"])
        self.assertEqual(run_id, "")
        self.assertEqual(mapping, {})
        queued.assert_not_called()

    def test_unmatched_scope_is_not_queued(self):
        """115 上但没命中任何监控任务扫描范围时同样不刷 STRM。"""
        config = {"mount_points": [dict(item) for item in MOUNT_POINTS]}
        with mock.patch.object(quick_import, "match_monitor_task_for_savepath", return_value={}), \
                mock.patch("app.services.monitor.queue_monitor_dir_scan") as queued:
            mapping = quick_import._queue_dispatch_child_runs(config, "115", ["随便/示例剧/S01"])
        self.assertEqual(mapping, {})
        queued.assert_not_called()

    def test_batch_scan_merges_scopes_before_queueing(self):
        config = {"mount_points": [dict(item) for item in MOUNT_POINTS]}
        with mock.patch.object(
            quick_import, "match_monitor_task_for_savepath", return_value={"task_name": "电视剧"},
        ), mock.patch(
            "app.services.monitor.queue_monitor_dir_scan",
            return_value={"tasks": [{"task_name": "电视剧", "run_id": "child-batch-1"}]},
        ) as queued:
            mapping = quick_import._queue_dispatch_child_runs(
                config,
                "115",
                ["电视剧/示例剧/S01", "电视剧/示例剧/S02", "电视剧/示例剧/S01"],
            )

        self.assertEqual(
            mapping,
            {"电视剧/示例剧/S01": "child-batch-1", "电视剧/示例剧/S02": "child-batch-1"},
        )
        queued.assert_called_once_with(
            config,
            "115",
            ["电视剧/示例剧/S01", "电视剧/示例剧/S02"],
            run_source="inbox_dispatch",
            force_new=False,
        )


if __name__ == "__main__":
    unittest.main()
