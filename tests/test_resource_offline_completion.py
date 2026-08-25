import json
import time
import unittest
from unittest import mock

from app.services import resource as resource_service


MAGNET_LINK = (
    "magnet:?xt=urn:btih:af33bd45b385b16a4bef434c760e0182&dn=example"
)
MAGNET_LINK_BASE32 = "magnet:?xt=urn:btih:ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
ED2K_LINK = (
    "ed2k://|file|摇滚兄弟私生活.2024 - S03E08.mkv|7848651243|"
    "af33bd45b385b16a4bef434c760e0182|/"
)


class FakeOfflineWatchProvider:
    name = "115"
    label = "115"
    supports_offline = True

    def __init__(self, tasks=None):
        self.tasks = list(tasks or [])
        self.calls = []

    def get_cookie(self, _cfg):
        return "cookie"

    def query_offline_tasks(self, cookie, page=1):
        self.calls.append((cookie, page))
        return {
            "tasks": self.tasks,
            "page": 1,
            "page_count": 1,
            "count": len(self.tasks),
            "total": len(self.tasks),
        }


def build_watch_job(**overrides):
    job = {
        "id": 71,
        "resource_id": 0,
        "title": "磁力任务 AF33BD45",
        "link_url": MAGNET_LINK,
        "link_type": "magnet",
        "folder_id": "season-folder",
        "savepath": "电视剧/整季",
        "monitor_task_name": "电视剧监控",
        "refresh_delay_seconds": 0,
        "auto_refresh": True,
        "status": "submitted",
        "last_triggered_at": "",
        "extra": {
            "offline_provider": "115",
            "offline_task_hash": "AF33BD45B385B16A4BEF434C760E0182",
            "offline_url": MAGNET_LINK,
            "offline_poll_started_at": "2026-08-18 10:00:00",
            "offline_poll_started_ts": time.time() - 60,
        },
    }
    job.update(overrides)
    return job


class OfflineIdentityTest(unittest.TestCase):
    def test_magnet_hash_extracted_uppercase(self):
        identity = resource_service.build_offline_job_identity(
            {"link_type": "magnet", "link_url": MAGNET_LINK}
        )
        self.assertEqual(identity["hash"], "AF33BD45B385B16A4BEF434C760E0182")

    def test_magnet_base32_hash_extracted(self):
        identity = resource_service.build_offline_job_identity(
            {"link_type": "magnet", "link_url": MAGNET_LINK_BASE32}
        )
        self.assertEqual(identity["hash"], "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")

    def test_ed2k_hash_extracted_uppercase(self):
        identity = resource_service.build_offline_job_identity(
            {"link_type": "ed2k", "link_url": ED2K_LINK}
        )
        self.assertEqual(identity["hash"], "AF33BD45B385B16A4BEF434C760E0182")

    def test_unknown_link_type_has_no_hash(self):
        identity = resource_service.build_offline_job_identity(
            {"link_type": "http", "link_url": "https://example.com/file"}
        )
        self.assertEqual(identity["hash"], "")


class OfflineTaskMatchTest(unittest.TestCase):
    def build_job(self, **overrides):
        return build_watch_job(**overrides)

    def test_info_hash_match_is_case_insensitive(self):
        task = {
            "info_hash": "af33bd45b385b16a4bef434c760e0182",
            "url": "",
            "wp_path_id": "season-folder",
        }
        self.assertEqual(resource_service._match_115_offline_task(task, self.build_job()), "exact")

    def test_url_match_without_hash(self):
        job = self.build_job(extra={"offline_url": MAGNET_LINK})
        task = {"info_hash": "", "url": MAGNET_LINK, "wp_path_id": "season-folder"}
        self.assertEqual(resource_service._match_115_offline_task(task, job), "exact")

    def test_legacy_job_without_stored_identity_derives_hash_from_link(self):
        job = self.build_job(extra={})
        task = {
            "info_hash": "af33bd45b385b16a4bef434c760e0182",
            "url": "",
            "wp_path_id": "season-folder",
        }
        self.assertEqual(resource_service._match_115_offline_task(task, job), "exact")

    def test_hash_inside_task_url_matches(self):
        task = {
            "info_hash": "",
            "url": "ed2k://|file|x.mkv|10|AF33BD45B385B16A4BEF434C760E0182|/",
            "wp_path_id": "season-folder",
        }
        self.assertEqual(resource_service._match_115_offline_task(task, self.build_job()), "exact")

    def test_folder_mismatch_is_reported(self):
        task = {
            "info_hash": "af33bd45b385b16a4bef434c760e0182",
            "url": "",
            "wp_path_id": "other-folder",
        }
        self.assertEqual(
            resource_service._match_115_offline_task(task, self.build_job()),
            "folder_mismatch",
        )

    def test_root_folder_id_skips_folder_guard(self):
        task = {
            "info_hash": "af33bd45b385b16a4bef434c760e0182",
            "url": "",
            "wp_path_id": "other-folder",
        }
        self.assertEqual(
            resource_service._match_115_offline_task(task, self.build_job(folder_id="0")),
            "exact",
        )

    def test_unrelated_task_does_not_match(self):
        task = {"info_hash": "deadbeef", "url": "", "wp_path_id": "season-folder"}
        self.assertEqual(resource_service._match_115_offline_task(task, self.build_job()), "")


class OfflineCompletionWatchTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        resource_service._offline_progress_write_state.clear()
        resource_service._offline_watch_running = False

    async def test_done_task_triggers_monitor_refresh(self):
        provider = FakeOfflineWatchProvider(
            tasks=[
                {
                    "info_hash": "af33bd45b385b16a4bef434c760e0182",
                    "url": "",
                    "name": "example",
                    "status": 2,
                    "percentDone": 100,
                    "size": 1000,
                    "wp_path_id": "season-folder",
                }
            ]
        )
        job = build_watch_job()
        with mock.patch.object(
            resource_service, "list_resource_jobs", return_value=[job]
        ), mock.patch.object(resource_service, "get_config", return_value={}), mock.patch.object(
            resource_service, "get_provider_or_none", return_value=provider
        ), mock.patch.object(resource_service, "update_resource_job") as update_job, mock.patch.object(
            resource_service, "trigger_resource_job_refresh"
        ) as trigger:
            await resource_service.poll_offline_resource_jobs_once()

        self.assertEqual(provider.calls, [("cookie", 1)])
        trigger.assert_awaited_once_with(71, reason="auto")
        extra_write = next(
            call for call in update_job.call_args_list
            if "extra_json" in call.kwargs or (call.args and "extra_json" in str(call.args))
        )
        extra = json.loads(extra_write.kwargs.get("extra_json", "{}"))
        self.assertEqual(extra["offline_status"], 2)

    async def test_failed_task_marks_job_failed(self):
        provider = FakeOfflineWatchProvider(
            tasks=[
                {
                    "info_hash": "af33bd45b385b16a4bef434c760e0182",
                    "url": "",
                    "name": "死种",
                    "status": -1,
                    "percentDone": 0,
                    "size": 0,
                    "wp_path_id": "season-folder",
                }
            ]
        )
        with mock.patch.object(
            resource_service, "list_resource_jobs", return_value=[build_watch_job()]
        ), mock.patch.object(resource_service, "get_config", return_value={}), mock.patch.object(
            resource_service, "get_provider_or_none", return_value=provider
        ), mock.patch.object(resource_service, "update_resource_job") as update_job:
            await resource_service.poll_offline_resource_jobs_once()

        self.assertTrue(
            any(
                call.kwargs.get("status") == "failed"
                for call in update_job.call_args_list
            )
        )

    async def test_running_task_writes_progress_detail(self):
        provider = FakeOfflineWatchProvider(
            tasks=[
                {
                    "info_hash": "af33bd45b385b16a4bef434c760e0182",
                    "url": "",
                    "name": "example",
                    "status": 1,
                    "percent": 45.0,
                    "size": 4600000000,
                    "wp_path_id": "season-folder",
                }
            ]
        )
        with mock.patch.object(
            resource_service, "list_resource_jobs", return_value=[build_watch_job()]
        ), mock.patch.object(resource_service, "get_config", return_value={}), mock.patch.object(
            resource_service, "get_provider_or_none", return_value=provider
        ), mock.patch.object(resource_service, "update_resource_job") as update_job:
            await resource_service.poll_offline_resource_jobs_once()

        progress_call = next(
            call for call in update_job.call_args_list
            if "offline_percent" in str(call.kwargs.get("extra_json", ""))
        )
        extra = json.loads(progress_call.kwargs["extra_json"])
        self.assertEqual(extra["offline_status"], 1)
        self.assertAlmostEqual(extra["offline_percent"], 45.0)
        self.assertIn("45%", progress_call.kwargs["status_detail"])
        self.assertIn("GB", progress_call.kwargs["status_detail"])

    async def test_delay_grace_skips_early_poll(self):
        provider = FakeOfflineWatchProvider()
        job = build_watch_job(
            refresh_delay_seconds=3600,
            extra={
                "offline_task_hash": "AF33BD45B385B16A4BEF434C760E0182",
                "offline_url": MAGNET_LINK,
                "offline_poll_started_at": "2026-08-18 10:00:00",
                "offline_poll_started_ts": time.time(),
            },
        )
        with mock.patch.object(
            resource_service, "list_resource_jobs", return_value=[job]
        ), mock.patch.object(resource_service, "get_config", return_value={}), mock.patch.object(
            resource_service, "get_provider_or_none", return_value=provider
        ):
            await resource_service.poll_offline_resource_jobs_once()

        self.assertEqual(provider.calls, [])

    async def test_timeout_marks_job_failed_without_scan(self):
        provider = FakeOfflineWatchProvider()
        job = build_watch_job(
            extra={
                "offline_task_hash": "AF33BD45B385B16A4BEF434C760E0182",
                "offline_url": MAGNET_LINK,
                "offline_poll_started_at": "2026-08-18 10:00:00",
                "offline_poll_started_ts": time.time() - 50000,
            }
        )
        with mock.patch.object(
            resource_service, "list_resource_jobs", return_value=[job]
        ), mock.patch.object(resource_service, "get_config", return_value={}), mock.patch.object(
            resource_service, "get_provider_or_none", return_value=provider
        ), mock.patch.object(resource_service, "update_resource_job") as update_job:
            await resource_service.poll_offline_resource_jobs_once()

        self.assertTrue(
            any(
                call.kwargs.get("status") == "failed"
                and "未确认 115 离线任务完成" in str(call.kwargs.get("status_detail", ""))
                for call in update_job.call_args_list
            )
        )

    async def test_folder_mismatch_skips_wait_and_scan(self):
        provider = FakeOfflineWatchProvider(
            tasks=[
                {
                    "info_hash": "af33bd45b385b16a4bef434c760e0182",
                    "url": "",
                    "name": "example",
                    "status": 1,
                    "percentDone": 10,
                    "size": 100,
                    "wp_path_id": "other-folder",
                }
            ]
        )
        with mock.patch.object(
            resource_service, "list_resource_jobs", return_value=[build_watch_job()]
        ), mock.patch.object(resource_service, "get_config", return_value={}), mock.patch.object(
            resource_service, "get_provider_or_none", return_value=provider
        ), mock.patch.object(resource_service, "update_resource_job") as update_job:
            await resource_service.poll_offline_resource_jobs_once()

        skip_call = next(
            call for call in update_job.call_args_list
            if "offline_skip_wait" in str(call.kwargs.get("extra_json", ""))
        )
        self.assertEqual(json.loads(skip_call.kwargs["extra_json"])["offline_skip_wait"], 1)

    def test_pending_counts_ignore_skipped_and_disabled_jobs(self):
        eligible = build_watch_job()
        skipped = build_watch_job(id=72, extra={"offline_skip_wait": 1})
        manual = build_watch_job(id=73, auto_refresh=False)
        other_task = build_watch_job(id=74, monitor_task_name="电影监控")
        with mock.patch.object(
            resource_service,
            "list_resource_jobs",
            return_value=[eligible, skipped, manual, other_task],
        ):
            counts = resource_service.pending_offline_job_counts_by_monitor()

        self.assertEqual(counts, {"电视剧监控": 1, "电影监控": 1})


class OfflineSubmitFlowTest(unittest.IsolatedAsyncioTestCase):
    class SubmitProvider:
        name = "115"
        label = "115"
        supports_offline = True
        supports_monitor = True

        def __init__(self, response):
            self.response = response

        def get_cookie(self, _cfg):
            return "cookie"

        def resolve_folder_id_by_path(self, _cookie, _savepath):
            return "season-folder"

        def submit_offline_task(self, _cookie, _link_url, _folder_id):
            return self.response

    async def test_duplicate_submit_keeps_manual_refresh_and_skips_wait(self):
        provider = self.SubmitProvider({"errcode": 10008, "message": "任务已存在"})
        job = {
            "id": 81,
            "resource_id": 0,
            "title": "摇滚兄弟私生活.2024 - S03E08.mkv",
            "link_url": ED2K_LINK,
            "link_type": "ed2k",
            "folder_id": "season-folder",
            "savepath": "电视剧/整季",
            "monitor_task_name": "电视剧监控",
            "refresh_delay_seconds": 4,
            "auto_refresh": True,
            "status": "pending",
            "extra": {"offline_provider": "115"},
            "extra_json": json.dumps({"offline_provider": "115"}),
        }
        updates = []
        with mock.patch.object(resource_service, "get_resource_job", return_value=job), mock.patch.object(
            resource_service, "get_resource_item", return_value={}
        ), mock.patch.object(resource_service, "get_config", return_value={}), mock.patch.object(
            resource_service, "get_provider_or_none", return_value=provider
        ), mock.patch.object(
            resource_service,
            "update_resource_job",
            side_effect=lambda job_id, **fields: updates.append((job_id, fields)),
        ), mock.patch.object(resource_service, "submit_background") as submit, mock.patch.object(
            resource_service, "release_process_memory"
        ):
            await resource_service.run_resource_job(81)

        final = updates[-1][1]
        self.assertEqual(final["status"], "submitted")
        extra = json.loads(final["extra_json"])
        self.assertEqual(extra["offline_skip_wait"], 1)
        self.assertEqual(extra["offline_task_hash"], "AF33BD45B385B16A4BEF434C760E0182")
        self.assertIn("已存在", final["status_detail"])
        submit.assert_not_called()

    async def test_normal_submit_records_identity_and_kicks_poller(self):
        provider = self.SubmitProvider({"message": "已接收"})
        job = {
            "id": 82,
            "resource_id": 0,
            "title": "磁力任务 AF33BD45",
            "link_url": MAGNET_LINK,
            "link_type": "magnet",
            "folder_id": "season-folder",
            "savepath": "电视剧/整季",
            "monitor_task_name": "电视剧监控",
            "refresh_delay_seconds": 4,
            "auto_refresh": True,
            "status": "pending",
            "extra": {"offline_provider": "115"},
            "extra_json": json.dumps({"offline_provider": "115"}),
        }
        updates = []
        with mock.patch.object(resource_service, "get_resource_job", return_value=job), mock.patch.object(
            resource_service, "get_resource_item", return_value={}
        ), mock.patch.object(resource_service, "get_config", return_value={}), mock.patch.object(
            resource_service, "get_provider_or_none", return_value=provider
        ), mock.patch.object(
            resource_service,
            "update_resource_job",
            side_effect=lambda job_id, **fields: updates.append((job_id, fields)),
        ), mock.patch.object(resource_service, "submit_background") as submit, mock.patch.object(
            resource_service, "release_process_memory"
        ):
            await resource_service.run_resource_job(82)

        final = updates[-1][1]
        extra = json.loads(final["extra_json"])
        self.assertEqual(extra["offline_task_hash"], "AF33BD45B385B16A4BEF434C760E0182")
        self.assertEqual(extra["offline_skip_wait"], 0)
        self.assertIn("等待 115 离线下载完成后", final["status_detail"])
        self.assertEqual(submit.call_args.args[0], resource_service.poll_offline_resource_jobs_once)


class OfflineFolderRefreshTest(unittest.IsolatedAsyncioTestCase):
    def test_resolve_offline_download_folder_hint_matches_seed_folder(self):
        class FakeFolderProvider:
            def list_entries(self, cookie, cid):
                return [
                    {"id": "d1", "name": "【高清剧集网发布】九门[全30集].BlackTV", "is_dir": True},
                    {"id": "f1", "name": "single.mkv", "is_dir": False},
                ]

        hint = resource_service.resolve_offline_download_folder_hint(
            FakeFolderProvider(),
            "cookie",
            "0",
            "【高清剧集网发布】九门[全30集].BlackTV",
        )
        self.assertEqual(hint, "【高清剧集网发布】九门[全30集].BlackTV")

    def test_resolve_offline_download_folder_hint_empty_when_single_file(self):
        class FakeFileProvider:
            def list_entries(self, cookie, cid):
                return [{"id": "f1", "name": "movie.mkv", "is_dir": False}]

        hint = resource_service.resolve_offline_download_folder_hint(
            FakeFileProvider(),
            "cookie",
            "0",
            "movie.mkv",
        )
        self.assertEqual(hint, "")

    async def test_trigger_refresh_uses_offline_folder_as_precise_scope(self):
        job = {
            "id": 71,
            "resource_id": 0,
            "title": "磁力任务 abcd",
            "savepath": "115自存电视剧",
            "sharetitle": "",
            "monitor_task_name": "监控-电视剧",
            "job_source": "manual_import",
            "refresh_target_type": "",
            "extra": {},
            "extra_json": "{}",
            "last_triggered_at": "",
        }
        captured = {}
        with mock.patch.object(
            resource_service, "get_resource_job", return_value=job
        ), mock.patch.object(
            resource_service,
            "get_config",
            return_value={"monitor_tasks": [{"name": "监控-电视剧"}]},
        ), mock.patch.object(
            resource_service,
            "queue_monitor_job",
            side_effect=lambda task, trigger, payload: captured.update(
                task=task, trigger=trigger, payload=payload
            )
            or "started",
        ), mock.patch.object(resource_service, "update_resource_job"), mock.patch.object(
            resource_service, "update_resource_item_status"
        ):
            result = await resource_service.trigger_resource_job_refresh(
                71,
                reason="auto",
                offline_folder_name="【高清剧集网发布】九门[全30集].BlackTV",
            )
        self.assertEqual(result["status"], "started")
        self.assertEqual(
            captured["payload"]["sharetitle"],
            "【高清剧集网发布】九门[全30集].BlackTV",
        )
        self.assertEqual(captured["payload"]["refresh_target_type"], "folder")


if __name__ == "__main__":
    unittest.main()
