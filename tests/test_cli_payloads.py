import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cli  # noqa: E402


class _RecordingClient:
    """Record HTTP calls; canned responses keyed by (method, path)."""

    def __init__(self, responses=None):
        self.responses = dict(responses or {})
        self.requests = []

    def json(self, method, path, body=None):
        self.requests.append((method, path, body))
        return self.responses.get((method, path), {})

    def request(self, method, path, body=None):
        self.requests.append((method, path, body))
        return _FakeResponse(200)


class _FakeResponse:
    def __init__(self, status_code, text="", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json = json_data or {}

    def json(self):
        return self._json


def _parse(argv):
    return cli._build_parser().parse_args(argv)


class CliPayloadTest(unittest.TestCase):
    def test_search_cancel_sends_empty_body(self):
        c = _RecordingClient()
        cli.cmd_search(_parse(["search", "--cancel"]), c)
        self.assertIn(("POST", "/resource/search/cancel", {}), c.requests)

    def test_jobs_clear_sends_empty_body(self):
        c = _RecordingClient()
        cli.cmd_jobs(_parse(["jobs", "clear"]), c)
        self.assertIn(("POST", "/resource/jobs/clear", {}), c.requests)

    def test_jobs_retry_sends_job_id(self):
        c = _RecordingClient()
        cli.cmd_jobs(_parse(["jobs", "retry", "--job-id", "7"]), c)
        self.assertIn(("POST", "/resource/jobs/retry", {"job_id": 7}), c.requests)

    def test_offline_list_requests_read_only_tasks(self):
        c = _RecordingClient(
            responses={
                ("GET", "/resource/offline/tasks?page=2"): {
                    "ok": True,
                    "tasks": [
                        {"name": "示例", "status": 2, "percent": 100, "info_hash": "hash", "wp_path_id": "0"}
                    ],
                }
            }
        )
        cli.cmd_offline(_parse(["offline", "list", "--page", "2"]), c)
        self.assertIn(("GET", "/resource/offline/tasks?page=2", None), c.requests)

    def test_jobs_retry_invalid_id_fails_cleanly(self):
        c = _RecordingClient()
        with self.assertRaises(SystemExit) as ctx:
            cli.cmd_jobs(_parse(["jobs", "retry", "--job-id", "abc"]), c)
        self.assertIn("任务 ID 无效", str(ctx.exception))
        self.assertEqual(c.requests, [])

    def test_resource_delete_sends_id(self):
        c = _RecordingClient()
        cli.cmd_resource(_parse(["resource", "delete", "--id", "123", "--yes"]), c)
        self.assertIn(("POST", "/resource/items/delete", {"id": 123}), c.requests)

    def test_tmdb_detail_invalid_id_fails_cleanly(self):
        c = _RecordingClient()
        with self.assertRaises(SystemExit) as ctx:
            cli.cmd_tmdb(_parse(["tmdb", "detail", "--tmdb-id", "abc", "--media-type", "movie"]), c)
        self.assertIn("TMDB ID 无效", str(ctx.exception))
        self.assertEqual(c.requests, [])

    def test_subscribe_remove_uses_delete_endpoint(self):
        c = _RecordingClient({
            ("GET", "/get_settings"): {"subscription_tasks": [{"name": "测试订阅"}]},
        })
        cli.cmd_subscribe(_parse(["subscribe", "remove", "测试订阅"]), c)
        self.assertIn(("POST", "/subscription/delete", {"name": "测试订阅"}), c.requests)

    def test_subscribe_add_infers_savepath_for_tv(self):
        c = _RecordingClient({
            ("GET", "/get_settings"): {
                "subscription_tasks": [],
                "resource_favorite_dirs": {"115": [{"name": "电视剧", "path": "/影视/电视剧"}]},
            },
        })
        cli.cmd_subscribe(_parse(["subscribe", "add", "某美剧", "--type", "tv"]), c)
        save_call = next(call for call in c.requests if call[0] == "POST" and call[1] == "/subscription/save")
        tasks = save_call[2]["tasks"]
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["savepath"], "/影视/电视剧")

    def test_subscribe_add_invalid_schedule_json_fails_cleanly(self):
        c = _RecordingClient()
        with self.assertRaises(SystemExit) as ctx:
            cli.cmd_subscribe(
                _parse(["subscribe", "add", "某美剧", "--schedule-weekdays", "not-json"]),
                c,
            )
        self.assertIn("JSON 数组", str(ctx.exception))
        self.assertFalse(any(call[0] == "POST" for call in c.requests))

    def test_settings_invalid_int_does_not_raise(self):
        c = _RecordingClient({
            ("GET", "/get_settings"): {"some_int": 5},
        })
        cli.cmd_settings(_parse(["settings", "some_int=abc"]), c)
        self.assertEqual(c.requests[0], ("GET", "/get_settings", None))
        self.assertEqual(c.requests[1], ("POST", "/save_settings", {"some_int": 5}))

    def test_monitor_start_requires_and_sends_name(self):
        c = _RecordingClient()
        cli.cmd_monitor(_parse(["monitor", "start", "影视监控"]), c)
        self.assertIn(("POST", "/monitor/start", {"name": "影视监控"}), c.requests)

    def test_monitor_remove_uses_delete_endpoint(self):
        c = _RecordingClient({
            ("GET", "/get_settings"): {"monitor_tasks": [{"name": "影视监控"}]},
        })
        cli.cmd_monitor(_parse(["monitor", "remove", "影视监控"]), c)
        self.assertIn(("POST", "/monitor/delete", {"name": "影视监控"}), c.requests)

    def test_strm_cleanup_sends_empty_body(self):
        c = _RecordingClient()
        cli.cmd_strm(_parse(["strm", "cleanup"]), c)
        self.assertIn(("POST", "/strm/orphan-metadata/delete", {}), c.requests)

    def test_scraper_jobs_clear_sends_empty_body(self):
        c = _RecordingClient()
        cli.cmd_scrape(_parse(["scrape", "jobs-clear"]), c)
        self.assertIn(("POST", "/scraper/jobs/clear", {}), c.requests)

    def test_scraper_batch_preferences_get(self):
        c = _RecordingClient()
        cli.cmd_scrape(_parse(["scrape", "batch-preferences", "get", "--provider", "115"]), c)
        self.assertIn(("GET", "/scraper/115/batch/preferences", None), c.requests)

    def test_scraper_batch_preferences_set_sends_options(self):
        c = _RecordingClient()
        cli.cmd_scrape(
            _parse(
                [
                    "scrape", "batch-preferences", "set", "--provider", "115",
                    "--options-json", '{"file_name_mode":"clean","delete_ad_files":true}',
                ]
            ),
            c,
        )
        self.assertIn(
            ("POST", "/scraper/115/batch/preferences", {"options": {"file_name_mode": "clean", "delete_ad_files": True}}),
            c.requests,
        )

    def test_scraper_batch_preferences_clear_sends_empty_options(self):
        c = _RecordingClient()
        cli.cmd_scrape(_parse(["scrape", "batch-preferences", "clear", "--provider", "115"]), c)
        self.assertIn(("POST", "/scraper/115/batch/preferences", {"options": {}}), c.requests)

    def test_scraper_batch_preferences_invalid_sub_fails_cleanly(self):
        c = _RecordingClient()
        with self.assertRaises(SystemExit) as ctx:
            cli.cmd_scrape(_parse(["scrape", "batch-preferences", "nope"]), c)
        self.assertIn("get | set | clear", str(ctx.exception))
        self.assertEqual(c.requests, [])

    def test_scraper_batch_preferences_invalid_json_fails_cleanly(self):
        c = _RecordingClient()
        with self.assertRaises(SystemExit) as ctx:
            cli.cmd_scrape(
                _parse(["scrape", "batch-preferences", "set", "--options-json", "{bad"]),
                c,
            )
        self.assertIn("合法 JSON", str(ctx.exception))
        self.assertEqual(c.requests, [])

    def test_scraper_rename_plan_sends_naming_options(self):
        c = _RecordingClient()
        cli.cmd_scrape(
            _parse(
                [
                    "scrape", "rename-plan", "/影视/旧剧集名", "--provider", "115",
                    "--file-name-mode", "keep", "--no-season-subfolder",
                    "--delete-ad-files", "--season", "2",
                ]
            ),
            c,
        )
        self.assertIn(
            (
                "POST",
                "/scraper/rename-plan",
                {
                    "entries": [{"path": "/影视/旧剧集名"}],
                    "provider": "115",
                    "options": {
                        "file_name_mode": "keep",
                        "use_season_subfolder": False,
                        "delete_ad_files": True,
                        "season": 2,
                    },
                },
            ),
            c.requests,
        )

    def test_monitor_add_auto_scrape_options(self):
        c = _RecordingClient({
            ("GET", "/get_settings"): {"monitor_tasks": []},
        })
        cli.cmd_monitor(
            _parse(
                [
                    "monitor", "add", "影视监控", "--scan-path", "/115/一级",
                    "--auto-scrape-on-new",
                    "--auto-scrape-options-json", '{"file_name_mode":"keep","delete_ad_files":true}',
                ]
            ),
            c,
        )
        saved = next(body for method, path, body in c.requests if path == "/save_settings")
        task = saved["monitor_tasks"][0]
        self.assertTrue(task["auto_scrape_on_new"])
        self.assertEqual(task["auto_scrape_options"]["file_name_mode"], "keep")
        self.assertEqual(task["auto_scrape_options"]["delete_ad_files"], True)

    def test_scraper_jobs_create_runs_identify_then_plan(self):
        plan = {
            "ok": True,
            "provider": "115",
            "ready": True,
            "actions": [{"ready": True, "old_path": "/电影/x.mkv", "new_path": "/电影/黑客帝国4.mkv"}],
        }
        c = _RecordingClient({
            ("POST", "/scraper/identify"): {"ok": True, "query": "黑客帝国4", "media_type": "movie"},
            ("GET", "/tmdb/search"): {"ok": True, "items": [{"id": 603, "media_type": "movie", "title": "黑客帝国4"}]},
            ("POST", "/scraper/rename-plan"): plan,
            ("POST", "/scraper/jobs/create"): {"ok": True, "job_id": 42},
        })
        cli.cmd_scrape(_parse(["scrape", "jobs-create", "/电影/x.mkv"]), c)
        self.assertEqual(c.requests[0], ("POST", "/scraper/identify", {"entries": [{"path": "/电影/x.mkv"}], "provider": "115"}))
        self.assertEqual(c.requests[1], ("GET", "/tmdb/search", {"q": "黑客帝国4", "media_type": "movie", "page": 1}))
        rename_plan_body = c.requests[2][2]
        self.assertEqual(rename_plan_body["entries"], [{"path": "/电影/x.mkv"}])
        self.assertEqual(rename_plan_body["tmdb"]["tmdb_id"], 603)
        self.assertEqual(rename_plan_body["tmdb"]["tmdb_media_type"], "movie")
        self.assertEqual(c.requests[3], ("POST", "/scraper/jobs/create", {"plan": plan}))

    def test_scraper_jobs_create_aborts_when_plan_not_ready(self):
        plan = {
            "ok": True,
            "provider": "115",
            "ready": False,
            "actions": [{"ready": False, "issue": "TMDB 未选择"}],
            "issues": ["TMDB 未选择"],
            "warnings": [],
        }
        c = _RecordingClient({
            ("POST", "/scraper/identify"): {"ok": True, "query": "黑客帝国4", "media_type": "movie"},
            ("GET", "/tmdb/search"): {"ok": True, "items": [{"id": 603, "media_type": "movie", "title": "黑客帝国4"}]},
            ("POST", "/scraper/rename-plan"): plan,
        })
        with self.assertRaises(SystemExit) as ctx:
            cli.cmd_scrape(_parse(["scrape", "jobs-create", "/电影/x.mkv"]), c)
        self.assertIn("冲突或未识别项", str(ctx.exception))
        self.assertNotIn(("POST", "/scraper/jobs/create", {"plan": plan}), c.requests)

    def test_watchlist_add_invalid_id_fails_cleanly(self):
        c = _RecordingClient()
        with self.assertRaises(SystemExit) as ctx:
            cli.cmd_watchlist(_parse(["watchlist", "add", "abc", "--title", "某片"]), c)
        self.assertIn("TMDB ID 无效", str(ctx.exception))
        self.assertEqual(c.requests, [])


if __name__ == "__main__":
    unittest.main()
