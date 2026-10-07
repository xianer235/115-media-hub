import unittest
import json
import subprocess
from pathlib import Path
from unittest import mock

from app import core
from app.routes import subscription as subscription_routes
from app.services import subscription_task_runner as runner
from app.services import subscription_runner as runner_module


MAGNET_LINK = "magnet:?xt=urn:btih:AF33BD45B385B16A4BEF434C760E0182&dn=test"
MAGNET_LINK_B = "magnet:?xt=urn:btih:BB44CE56C496C27B5CFE545D871F1293&dn=test2"
ED2K_LINK = "ed2k://|file|test.mkv|104857600|0123456789abcdef0123456789abcdef|/"
ED2K_LINK_WITH_SPACE = "ed2k://|file|Some Movie 2024.mkv|104857600|0123456789abcdef0123456789abcdef|/"

ROOT = Path(__file__).resolve().parents[1]
UI_PATH = ROOT / "static/js/modules/subscription/ui.js"
LINK_TAGS_PATH = ROOT / "static/js/modules/resource/link-tags.js"
SETTINGS_JS_PATH = ROOT / "static/js/modules/tabs/settings.js"
SETTINGS_HTML_PATH = ROOT / "templates/partials/pages/settings.html"


def build_task(**overrides):
    base = {
        "name": "测试任务",
        "title": "测试电影",
        "savepath": "电影",
        "provider": "115",
        "media_type": "movie",
    }
    base.update(overrides)
    return core.normalize_subscription_task(base)


class ManualOfflineCandidateTest(unittest.TestCase):
    def test_manual_search_result_uses_offline_link_type(self):
        with mock.patch.object(runner, "ensure_db"), mock.patch.object(
            runner, "open_db"
        ) as open_db, mock.patch.object(
            runner, "upsert_resource_item", return_value=(1001, {})
        ):
            open_db.return_value = mock.MagicMock()
            result = runner._build_manual_subscription_search_result(
                build_task(),
                "测试任务",
                {"link_url": MAGNET_LINK, "link_type": "magnet"},
                "115",
            )
        item = result["candidates"][0]["item"]
        self.assertEqual(item["link_type"], "magnet")
        self.assertTrue(item["extra"]["manual_subscription_link"])
        self.assertEqual(item["extra"]["manual_link_type"], "magnet")

    def test_manual_search_result_falls_back_to_share_type(self):
        with mock.patch.object(runner, "ensure_db"), mock.patch.object(
            runner, "open_db"
        ) as open_db, mock.patch.object(
            runner, "upsert_resource_item", return_value=(1002, {})
        ):
            open_db.return_value = mock.MagicMock()
            result = runner._build_manual_subscription_search_result(
                build_task(),
                "测试任务",
                {"link_url": "https://115.com/s/abc123"},
                "115",
            )
        item = result["candidates"][0]["item"]
        self.assertEqual(item["link_type"], "115share")

    def test_offline_candidate_gate_only_manual_links(self):
        manual = {
            "item": {
                "link_type": "magnet",
                "link_url": MAGNET_LINK,
                "extra": {"manual_subscription_link": True},
            }
        }
        self.assertEqual(runner._subscription_offline_candidate(manual)["link_type"], "magnet")

        search_candidate = {
            "item": {
                "link_type": "magnet",
                "link_url": MAGNET_LINK,
                "extra": {},
            }
        }
        self.assertEqual(runner._subscription_offline_candidate(search_candidate), {})

        share_candidate = {
            "item": {
                "link_type": "115share",
                "link_url": "https://115.com/s/abc123",
                "extra": {"manual_subscription_link": True},
            }
        }
        self.assertEqual(runner._subscription_offline_candidate(share_candidate), {})


class OfflineSelectionTest(unittest.TestCase):
    def test_movie_selects_title_matched_best_file(self):
        task = build_task()
        files = [
            {
                "id": "a",
                "name": "测试电影.2024.1080p.mkv",
                "rel_path": "测试电影.2024.1080p.mkv",
                "size": 2000,
                "episodes": set(),
            },
            {
                "id": "b",
                "name": "Other.Movie.2020.mkv",
                "rel_path": "Other.Movie.2020.mkv",
                "size": 9000,
                "episodes": set(),
            },
        ]
        selection = runner._select_subscription_offline_entries(task, files, set(), 0)
        self.assertEqual(selection["selected_ids"], ["a"])

    def test_tv_selects_missing_episodes_best_quality(self):
        task = build_task(media_type="tv", title="测试剧集")
        files = [
            {
                "id": "e1",
                "name": "测试剧集.S01E01.1080p.mkv",
                "rel_path": "测试剧集.S01E01.1080p.mkv",
                "size": 1000,
                "episodes": {1},
            },
            {
                "id": "e2a",
                "name": "测试剧集.S01E02.720p.mkv",
                "rel_path": "测试剧集.S01E02.720p.mkv",
                "size": 800,
                "episodes": {2},
            },
            {
                "id": "e2b",
                "name": "测试剧集.S01E02.1080p.mkv",
                "rel_path": "测试剧集.S01E02.1080p.mkv",
                "size": 1200,
                "episodes": {2},
            },
        ]
        selection = runner._select_subscription_offline_entries(task, files, {1}, 0)
        self.assertEqual(set(selection["selected_ids"]), {"e2b"})
        self.assertEqual(set(selection["recorded_episodes"]), {2})

    def test_tv_selects_all_missing_episodes_not_single_fallback(self):
        task = build_task(media_type="tv", title="测试剧集")
        files = [
            {
                "id": "e1",
                "name": "测试剧集.S01E01.1080p.mkv",
                "rel_path": "测试剧集.S01E01.1080p.mkv",
                "size": 1000,
                "episodes": [1],
            },
            {
                "id": "e2",
                "name": "测试剧集.S01E02.1080p.mkv",
                "rel_path": "测试剧集.S01E02.1080p.mkv",
                "size": 1200,
                "episodes": [2],
            },
        ]
        selection = runner._select_subscription_offline_entries(task, files, set(), 0)
        self.assertEqual(set(selection["selected_ids"]), {"e1", "e2"})
        self.assertEqual(set(selection["recorded_episodes"]), {1, 2})

    def test_tv_selects_full_season_inside_torrent_folder(self):
        folder = (
            "【高清剧集网发布 www.BPHDTV.com】百花杀[60帧率版本][全36集]"
            "[国语配音+中文字幕].2026.2160p.WEB-DL.H265.60fps.DDP5.1.Atmos-BlackTV"
        )
        task = build_task(media_type="tv", title="百花杀", total_episodes=36)
        files = []
        for episode in (1, 2):
            leaf = (
                f"Blossoms.of.Power.S01E{episode:02d}.2026.2160p.WEB-DL.H265.60fps"
                ".DDP5.1.Atmos-BlackTV.mkv"
            )
            files.append(
                {
                    "id": f"f{episode}",
                    "name": leaf,
                    "rel_path": f"{folder}/{leaf}",
                    "size": 2000,
                    "episodes": [episode],
                }
            )
        selection = runner._select_subscription_offline_entries(task, files, set(), 36)
        self.assertEqual(set(selection["selected_ids"]), {"f1", "f2"})
        self.assertEqual(set(selection["recorded_episodes"]), {1, 2})

    def test_junk_file_detection(self):
        self.assertTrue(runner._is_subscription_offline_junk_file("xxx.sample.mkv"))
        self.assertTrue(runner._is_subscription_offline_junk_file("cover.jpg"))
        self.assertTrue(runner._is_subscription_offline_junk_file("movie.nfo"))
        self.assertFalse(runner._is_subscription_offline_junk_file("测试电影.mkv"))


class OfflineImportPipelineTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.task = build_task()
        self.item = {
            "id": 1001,
            "title": "测试电影",
            "link_url": MAGNET_LINK,
            "link_type": "magnet",
            "raw_text": MAGNET_LINK,
        }
        self.candidate = {
            "item": self.item,
            "score": 100,
            "episode": 0,
            "season": 0,
            "total": 0,
        }

    def build_provider(self):
        provider = mock.MagicMock()
        provider.label = "115网盘"

        def resolve_folder(cookie, path):
            mapping = {
                "云下载/磁力中转/测试任务": "staging-cid",
                "电影/测试电影 2024": "target-cid",
            }
            return mapping.get(path, "target-cid")

        provider.ensure_folder_id_by_path.side_effect = resolve_folder
        provider.submit_offline_task.return_value = {
            "state": True,
            "info_hash": "af33bd45b385b16a4bef434c760e0182",
        }
        provider.query_offline_tasks.return_value = {
            "tasks": [
                {
                    "info_hash": "af33bd45b385b16a4bef434c760e0182",
                    "url": "",
                    "name": "测试电影",
                    "status": 2,
                    "percentDone": 100,
                    "size": 1000,
                    "wp_path_id": "staging-cid",
                }
            ],
            "page_count": 1,
        }
        provider.list_entries.side_effect = lambda cookie, cid: (
            [
                {
                    "id": "file-1",
                    "name": "测试电影.2024.1080p.mkv",
                    "size": 1000,
                    "is_dir": False,
                    "modified_at": "",
                }
            ]
            if cid == "staging-cid"
            else []
        )
        provider.move_entries.return_value = {"state": True}
        provider.delete_entries.return_value = {"state": True}
        return provider

    async def test_pipeline_submits_moves_and_refreshes(self):
        provider = self.build_provider()
        with mock.patch.object(runner, "create_resource_job", return_value=77), mock.patch.object(
            runner, "update_resource_job"
        ), mock.patch.object(
            runner,
            "match_monitor_task_for_savepath",
            return_value={"task_name": "监控电影"},
        ), mock.patch.object(runner, "queue_monitor_job") as queue_job, mock.patch.object(
            runner, "create_subscription_match"
        ), mock.patch.object(
            runner, "write_subscription_log", new_callable=mock.AsyncMock
        ), mock.patch.object(runner, "upsert_subscription_task_state"), mock.patch.object(
            runner, "check_subscription_cancelled"
        ), mock.patch.object(
            runner, "now_text", return_value="2026-08-25 19:00:00"
        ), mock.patch.object(runner, "safe_json_dumps", side_effect=lambda value: "{}"):
            result = await runner._run_subscription_manual_offline_import(
                task=self.task,
                task_name="测试任务",
                cfg={"mount_points": [], "monitor_tasks": []},
                provider_meta=provider,
                cookie="cookie-115",
                candidate=self.candidate,
                item=self.item,
                link_type="magnet",
                staging_root="云下载/磁力中转",
                effective_savepath="电影/测试电影 2024",
                base_savepath="电影",
                folder_id="target-cid",
                monitor_task_name="",
                last_episode=0,
                known_total=0,
                single_season_episode_upper_bound=0,
                existing_folder_episodes=set(),
                existing_episode_scan_ready=False,
                subscription_run_id="run-1",
                batch_refresh_enabled=False,
                import_timeout_seconds=10,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["job_id"], 77)
        self.assertEqual(result["selected_savepath"], "电影/测试电影 2024")
        provider.submit_offline_task.assert_called_once()
        provider.move_entries.assert_called_once()
        move_call = provider.move_entries.call_args
        self.assertEqual(move_call.args[1], ["file-1"])
        self.assertEqual(move_call.args[2], "target-cid")
        queue_job.assert_called_once()
        self.assertEqual(queue_job.call_args.args[0], "监控电影")
        self.assertEqual(queue_job.call_args.args[1], "subscription")

    async def test_pipeline_submit_failure_returns_failure(self):
        provider = self.build_provider()
        provider.submit_offline_task.side_effect = RuntimeError("115 离线任务提交失败")
        with mock.patch.object(runner, "create_resource_job", return_value=78), mock.patch.object(
            runner, "update_resource_job"
        ), mock.patch.object(
            runner, "write_subscription_log", new_callable=mock.AsyncMock
        ), mock.patch.object(runner, "upsert_subscription_task_state"), mock.patch.object(
            runner, "check_subscription_cancelled"
        ), mock.patch.object(runner, "now_text", return_value="2026-08-25 19:00:00"), mock.patch.object(
            runner, "safe_json_dumps", side_effect=lambda value: "{}"
        ):
            result = await runner._run_subscription_manual_offline_import(
                task=self.task,
                task_name="测试任务",
                cfg={},
                provider_meta=provider,
                cookie="cookie-115",
                candidate=self.candidate,
                item=self.item,
                link_type="magnet",
                staging_root="云下载/磁力中转",
                effective_savepath="电影/测试电影 2024",
                base_savepath="电影",
                folder_id="target-cid",
                monitor_task_name="",
                last_episode=0,
                known_total=0,
                single_season_episode_upper_bound=0,
                existing_folder_episodes=set(),
                existing_episode_scan_ready=False,
                subscription_run_id="run-2",
                batch_refresh_enabled=False,
                import_timeout_seconds=10,
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["last_failed_detail"], "115 离线任务提交失败")
        self.assertEqual(result["failed_attempts"], 1)

    async def test_pipeline_rescans_staging_until_late_file_appears(self):
        """115 报「完成」时文件可能还没出现在目录列表里，宽限期内重扫应该能捞到。"""
        provider = self.build_provider()
        staging_calls = []

        def list_entries(cookie, cid):
            if cid != "staging-cid":
                return []
            staging_calls.append(cid)
            if len(staging_calls) < 2:
                return []
            return [
                {
                    "id": "file-1",
                    "name": "测试电影.2024.1080p.mkv",
                    "size": 1000,
                    "is_dir": False,
                    "modified_at": "",
                }
            ]

        provider.list_entries.side_effect = list_entries
        with mock.patch.object(
            runner, "SUBSCRIPTION_OFFLINE_STAGING_RESCAN_INTERVAL_SECONDS", 0.01, create=True
        ), mock.patch.object(runner, "create_resource_job", return_value=77), mock.patch.object(
            runner, "update_resource_job"
        ), mock.patch.object(
            runner, "match_monitor_task_for_savepath", return_value={}
        ), mock.patch.object(
            runner, "create_subscription_match"
        ), mock.patch.object(
            runner, "write_subscription_log", new_callable=mock.AsyncMock
        ), mock.patch.object(runner, "upsert_subscription_task_state"), mock.patch.object(
            runner, "check_subscription_cancelled"
        ), mock.patch.object(
            runner, "now_text", return_value="2026-10-07 15:20:00"
        ), mock.patch.object(runner, "safe_json_dumps", side_effect=lambda value: "{}"):
            result = await runner._run_subscription_manual_offline_import(
                task=self.task,
                task_name="测试任务",
                cfg={"mount_points": [], "monitor_tasks": []},
                provider_meta=provider,
                cookie="cookie-115",
                candidate=self.candidate,
                item=self.item,
                link_type="magnet",
                staging_root="云下载/磁力中转",
                effective_savepath="电影/测试电影 2024",
                base_savepath="电影",
                folder_id="target-cid",
                monitor_task_name="",
                last_episode=0,
                known_total=0,
                single_season_episode_upper_bound=0,
                existing_folder_episodes=set(),
                existing_episode_scan_ready=False,
                subscription_run_id="run-3",
                batch_refresh_enabled=False,
                import_timeout_seconds=10,
            )

        self.assertTrue(result["ok"])
        self.assertGreaterEqual(len(staging_calls), 2)
        provider.move_entries.assert_called_once()

    async def test_pipeline_reports_wait_time_when_staging_stays_empty(self):
        """宽限期内一直扫空时仍判失败，但失败详情要带上已等待时长。"""
        provider = self.build_provider()
        provider.list_entries.side_effect = lambda cookie, cid: []
        with mock.patch.object(
            runner, "SUBSCRIPTION_OFFLINE_STAGING_GRACE_SECONDS", 0, create=True
        ), mock.patch.object(
            runner, "SUBSCRIPTION_OFFLINE_STAGING_RESCAN_INTERVAL_SECONDS", 0, create=True
        ), mock.patch.object(runner, "create_resource_job", return_value=78), mock.patch.object(
            runner, "update_resource_job"
        ), mock.patch.object(
            runner, "write_subscription_log", new_callable=mock.AsyncMock
        ), mock.patch.object(runner, "upsert_subscription_task_state"), mock.patch.object(
            runner, "check_subscription_cancelled"
        ), mock.patch.object(
            runner, "now_text", return_value="2026-10-07 15:21:00"
        ), mock.patch.object(runner, "safe_json_dumps", side_effect=lambda value: "{}"):
            result = await runner._run_subscription_manual_offline_import(
                task=self.task,
                task_name="测试任务",
                cfg={},
                provider_meta=provider,
                cookie="cookie-115",
                candidate=self.candidate,
                item=self.item,
                link_type="magnet",
                staging_root="云下载/磁力中转",
                effective_savepath="电影/测试电影 2024",
                base_savepath="电影",
                folder_id="target-cid",
                monitor_task_name="",
                last_episode=0,
                known_total=0,
                single_season_episode_upper_bound=0,
                existing_folder_episodes=set(),
                existing_episode_scan_ready=False,
                subscription_run_id="run-4",
                batch_refresh_enabled=False,
                import_timeout_seconds=10,
            )

        self.assertFalse(result["ok"])
        self.assertIn("已等待", result["last_failed_detail"])
        provider.move_entries.assert_not_called()

    async def test_pipeline_stops_rescanning_after_max_attempts(self):
        """中转目录一直扫空时，重扫次数要有上限，不能一直等下去。"""
        provider = self.build_provider()
        staging_calls = []

        def list_entries(cookie, cid):
            if cid == "staging-cid":
                staging_calls.append(cid)
            return []

        provider.list_entries.side_effect = list_entries
        with mock.patch.object(
            runner, "SUBSCRIPTION_OFFLINE_STAGING_GRACE_SECONDS", 0.05, create=True
        ), mock.patch.object(
            runner, "SUBSCRIPTION_OFFLINE_STAGING_RESCAN_INTERVAL_SECONDS", 0.01, create=True
        ), mock.patch.object(
            runner, "SUBSCRIPTION_OFFLINE_STAGING_MAX_ATTEMPTS", 3, create=True
        ), mock.patch.object(runner, "create_resource_job", return_value=79), mock.patch.object(
            runner, "update_resource_job"
        ), mock.patch.object(
            runner, "write_subscription_log", new_callable=mock.AsyncMock
        ), mock.patch.object(runner, "upsert_subscription_task_state"), mock.patch.object(
            runner, "check_subscription_cancelled"
        ), mock.patch.object(
            runner, "now_text", return_value="2026-10-07 15:22:00"
        ), mock.patch.object(runner, "safe_json_dumps", side_effect=lambda value: "{}"):
            result = await runner._run_subscription_manual_offline_import(
                task=self.task,
                task_name="测试任务",
                cfg={},
                provider_meta=provider,
                cookie="cookie-115",
                candidate=self.candidate,
                item=self.item,
                link_type="magnet",
                staging_root="云下载/磁力中转",
                effective_savepath="电影/测试电影 2024",
                base_savepath="电影",
                folder_id="target-cid",
                monitor_task_name="",
                last_episode=0,
                known_total=0,
                single_season_episode_upper_bound=0,
                existing_folder_episodes=set(),
                existing_episode_scan_ready=False,
                subscription_run_id="run-5",
                batch_refresh_enabled=False,
                import_timeout_seconds=10,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(len(staging_calls), 3)
        provider.move_entries.assert_not_called()


def run_subscription_ui(expression, provider_meta=None):
    provider_meta = provider_meta or []
    script = f"""
const fs = require('fs');
const vm = require('vm');
const context = {{
  window: {{ providerMeta: {json.dumps(provider_meta, ensure_ascii=False)} }},
  escapeHtml: value => String(value ?? ''),
  detectResourceLinkTypeByUrl: url => {{
    const value = String(url || '').trim().toLowerCase();
    if (value.startsWith('magnet:')) return 'magnet';
    if (value.startsWith('ed2k://')) return 'ed2k';
    if (value.includes('115.com/s/')) return '115share';
    if (value.includes('pan.quark.cn/s/')) return 'quark';
    return '';
  }},
}};
vm.createContext(context);
vm.runInContext(fs.readFileSync({json.dumps(str(LINK_TAGS_PATH))}, 'utf8'), context);
vm.runInContext(fs.readFileSync({json.dumps(str(UI_PATH))}, 'utf8'), context);
const result = vm.runInContext({json.dumps(expression)}, context);
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr.strip())
    return json.loads(completed.stdout)


class SubscriptionOfflineFrontendTest(unittest.TestCase):
    def test_multiline_magnet_paste_returns_all_entries(self):
        provider_meta = [{"name": "115", "label": "115网盘", "link_type": "115share"}]
        text = f"{MAGNET_LINK}\n{MAGNET_LINK_B}"
        result = run_subscription_ui(
            f"extractSubscriptionLinkEntries({json.dumps(text)}, '115')",
            provider_meta=provider_meta,
        )
        self.assertEqual([item["link_url"] for item in result], [MAGNET_LINK, MAGNET_LINK_B])
        self.assertEqual(result[0]["raw_text"], MAGNET_LINK)
        self.assertEqual(result[1]["raw_text"], MAGNET_LINK_B)

    def test_multiline_share_links_keep_their_own_receive_code(self):
        provider_meta = [{"name": "115", "label": "115网盘", "link_type": "115share"}]
        text = "https://115.com/s/aaa111\n提取码：abcd\nhttps://115.com/s/bbb222\n提取码：efgh"
        result = run_subscription_ui(
            f"extractSubscriptionLinkEntries({json.dumps(text)}, '115')",
            provider_meta=provider_meta,
        )
        self.assertEqual(
            [item["link_url"] for item in result],
            ["https://115.com/s/aaa111", "https://115.com/s/bbb222"],
        )
        self.assertEqual(result[0]["raw_text"], "https://115.com/s/aaa111\n提取码：abcd")
        self.assertEqual(result[1]["raw_text"], "https://115.com/s/bbb222\n提取码：efgh")

    def test_ed2k_link_with_spaces_in_name_is_not_truncated(self):
        provider_meta = [{"name": "115", "label": "115网盘", "link_type": "115share"}]
        text = f"{ED2K_LINK_WITH_SPACE}\n{MAGNET_LINK}"
        result = run_subscription_ui(
            f"extractSubscriptionLinkEntries({json.dumps(text)}, '115')",
            provider_meta=provider_meta,
        )
        self.assertEqual([item["link_url"] for item in result], [ED2K_LINK_WITH_SPACE, MAGNET_LINK])

    def test_quark_entries_skip_magnet_lines(self):
        provider_meta = [{"name": "quark", "label": "夸克网盘", "link_type": "quark"}]
        text = f"{MAGNET_LINK}\nhttps://pan.quark.cn/s/abc123"
        result = run_subscription_ui(
            f"extractSubscriptionLinkEntries({json.dumps(text)}, 'quark')",
            provider_meta=provider_meta,
        )
        self.assertEqual([item["link_url"] for item in result], ["https://pan.quark.cn/s/abc123"])

    def test_115_scan_link_extracts_magnet(self):
        provider_meta = [{"name": "115", "label": "115网盘", "link_type": "115share"}]
        result = run_subscription_ui(
            f"extractFirstSubscriptionShareUrl('{MAGNET_LINK}', '115')",
            provider_meta=provider_meta,
        )
        self.assertEqual(result, MAGNET_LINK)

    def test_quark_scan_link_rejects_magnet(self):
        provider_meta = [{"name": "quark", "label": "夸克网盘", "link_type": "quark"}]
        result = run_subscription_ui(
            f"extractFirstSubscriptionShareUrl('{MAGNET_LINK}', 'quark')",
            provider_meta=provider_meta,
        )
        self.assertEqual(result, "")

    def test_magnet_staging_root_setting_entry_exists(self):
        settings_js = SETTINGS_JS_PATH.read_text(encoding="utf-8")
        settings_html = SETTINGS_HTML_PATH.read_text(encoding="utf-8")
        self.assertIn("magnet_staging_root", settings_js)
        self.assertIn("云下载/磁力中转", settings_js)
        self.assertIn("settings-magnet-provider-container", settings_html)


class SubscriptionQueueBatchTest(unittest.TestCase):
    def test_queue_jobs_appends_all_candidates_and_kicks_once(self):
        queue = []
        status = {"running": False, "queued": []}
        kicked = []
        with mock.patch.object(runner_module, "subscription_queue", queue), mock.patch.object(
            runner_module, "subscription_status", status
        ), mock.patch.object(runner_module, "schedule_ui_state_push"), mock.patch.object(
            runner_module,
            "submit_background",
            side_effect=lambda fn, *args, **kwargs: kicked.append((fn, args, kwargs)),
        ):
            result = runner_module.queue_subscription_jobs(
                "测试任务",
                "manual_link",
                [
                    {"link_url": MAGNET_LINK, "link_type": "magnet"},
                    {"link_url": MAGNET_LINK_B, "link_type": "magnet"},
                    {"link_url": MAGNET_LINK, "link_type": "magnet"},
                ],
            )
        self.assertEqual(result, "started")
        self.assertEqual([item["manual_candidate"]["link_url"] for item in queue], [MAGNET_LINK, MAGNET_LINK_B])
        self.assertEqual(status["queued"], ["测试任务", "测试任务"])
        self.assertEqual(len(kicked), 1)
        self.assertEqual(kicked[0][0], runner_module.start_next_subscription_job)

    def test_queue_jobs_while_running_does_not_kick_again(self):
        queue = []
        status = {"running": True, "queued": []}
        with mock.patch.object(runner_module, "subscription_queue", queue), mock.patch.object(
            runner_module, "subscription_status", status
        ), mock.patch.object(runner_module, "schedule_ui_state_push"), mock.patch.object(
            runner_module, "submit_background"
        ) as submit:
            result = runner_module.queue_subscription_jobs(
                "测试任务", "manual_link", [{"link_url": MAGNET_LINK, "link_type": "magnet"}]
            )
        self.assertEqual(result, "queued")
        self.assertEqual(len(queue), 1)
        submit.assert_not_called()

    def test_single_queue_helper_still_enqueues_empty_candidate(self):
        queue = []
        status = {"running": False, "queued": []}
        with mock.patch.object(runner_module, "subscription_queue", queue), mock.patch.object(
            runner_module, "subscription_status", status
        ), mock.patch.object(runner_module, "schedule_ui_state_push"), mock.patch.object(
            runner_module, "submit_background"
        ):
            result = runner_module.queue_subscription_job("测试任务", "cron")
        self.assertEqual(result, "started")
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["manual_candidate"], {})


class FakeJsonRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


def build_115_provider_meta():
    provider = mock.MagicMock()
    provider.label = "115网盘"
    provider.link_type = "115share"
    provider.supports_subscription = True
    provider.supports_offline = True
    return provider


class SubscriptionStartWithLinkRouteTest(unittest.IsolatedAsyncioTestCase):
    def endpoint(self):
        endpoint = next(
            (
                route.endpoint
                for route in subscription_routes.router.routes
                if getattr(route, "path", "") == "/subscription/start_with_link"
                and "POST" in getattr(route, "methods", set())
            ),
            None,
        )
        self.assertIsNotNone(endpoint, "POST /subscription/start_with_link 尚未注册")
        return endpoint

    async def run_endpoint(self, payload, provider_meta=None):
        endpoint = self.endpoint()
        config = {"subscription_tasks": [build_task()]}
        queued = []

        def fake_queue(task_name, trigger, candidates):
            queued.append((task_name, trigger, list(candidates)))
            return "queued"

        with mock.patch.object(subscription_routes, "get_config", return_value=config), mock.patch(
            "app.providers.registry.get_or_none", return_value=provider_meta or build_115_provider_meta()
        ), mock.patch.object(subscription_routes, "queue_subscription_jobs", side_effect=fake_queue):
            response = await endpoint(FakeJsonRequest(payload))
        return response, queued

    async def test_multiple_offline_links_queue_one_job_each(self):
        response, queued = await self.run_endpoint(
            {
                "name": "测试任务",
                "links": [
                    {"link_url": MAGNET_LINK, "raw_text": MAGNET_LINK},
                    {"link_url": ED2K_LINK_WITH_SPACE, "raw_text": ED2K_LINK_WITH_SPACE},
                ],
            }
        )
        self.assertTrue(response["ok"])
        self.assertEqual(response["submitted"], 2)
        self.assertEqual(len(queued), 1)
        task_name, trigger, candidates = queued[0]
        self.assertEqual(task_name, "测试任务")
        self.assertEqual(trigger, "manual_link")
        self.assertEqual([item["link_url"] for item in candidates], [MAGNET_LINK, ED2K_LINK_WITH_SPACE])
        self.assertEqual([item["link_type"] for item in candidates], ["magnet", "ed2k"])

    async def test_legacy_single_link_field_still_works(self):
        response, queued = await self.run_endpoint({"name": "测试任务", "link_url": MAGNET_LINK})
        self.assertTrue(response["ok"])
        self.assertEqual(response["submitted"], 1)
        self.assertEqual(queued[0][2][0]["link_url"], MAGNET_LINK)

    async def test_duplicate_links_are_deduped(self):
        response, queued = await self.run_endpoint(
            {
                "name": "测试任务",
                "links": [{"link_url": MAGNET_LINK}, {"link_url": MAGNET_LINK}],
            }
        )
        self.assertEqual(response["submitted"], 1)
        self.assertEqual(len(queued[0][2]), 1)

    async def test_invalid_link_returns_400_with_reason(self):
        response, queued = await self.run_endpoint(
            {"name": "测试任务", "links": [{"link_url": "https://pan.quark.cn/s/abc123"}]}
        )
        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["msg"], "请填写 115 分享链接")
        self.assertEqual(queued, [])

    async def test_partial_invalid_links_submit_the_valid_ones(self):
        response, queued = await self.run_endpoint(
            {
                "name": "测试任务",
                "links": [
                    {"link_url": "https://pan.quark.cn/s/abc123"},
                    {"link_url": MAGNET_LINK},
                ],
            }
        )
        self.assertTrue(response["ok"])
        self.assertEqual(response["submitted"], 1)
        self.assertEqual([item["link_url"] for item in queued[0][2]], [MAGNET_LINK])
        self.assertEqual(len(response["skipped"]), 1)
        self.assertEqual(response["skipped"][0]["msg"], "请填写 115 分享链接")
