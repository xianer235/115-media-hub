import unittest
import json
import subprocess
from pathlib import Path
from unittest import mock

from app import core
from app.services import subscription_task_runner as runner


MAGNET_LINK = "magnet:?xt=urn:btih:AF33BD45B385B16A4BEF434C760E0182&dn=test"
ED2K_LINK = "ed2k://|file|test.mkv|104857600|0123456789abcdef0123456789abcdef|/"

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
        self.assertEqual(queue_job.call_args.args[1], "resource")

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
