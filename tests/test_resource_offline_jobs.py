import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import db
from app import resource_jobs
from app.routes import resource as resource_routes
from app.core import resource_item_matches_provider_filter
from app.resource_store import build_resource_job_snapshot
from app.services import resource as resource_service


SAMPLE_LINK = (
    "ed2k://|file|摇滚兄弟私生活.2024 - S03E08.mkv|7848651243|"
    "af33bd45b385b16a4bef434c760e0182|/"
)
SECOND_LINK = (
    "ed2k://|file|摇滚兄弟私生活.2024 - S03E07.mkv|6646256336|"
    "a93b3760ed987f48e95dc5e36ea49fee|/"
)


class FakeOfflineProvider:
    name = "115"
    label = "115"
    supports_offline = True
    supports_monitor = True

    def __init__(self, folder_id="season-folder", folder_error=None):
        self.folder_id = folder_id
        self.folder_error = folder_error
        self.ensure_calls = []
        self.resolve_calls = []
        self.submit_calls = []

    def get_cookie(self, _cfg):
        return "cookie"

    def ensure_folder_id_by_path(self, cookie, savepath):
        self.ensure_calls.append((cookie, savepath))
        if self.folder_error:
            raise self.folder_error
        return self.folder_id

    def resolve_folder_id_by_path(self, cookie, savepath):
        self.resolve_calls.append((cookie, savepath))
        if self.folder_error:
            raise self.folder_error
        return self.folder_id

    def submit_offline_task(self, cookie, link_url, folder_id):
        self.submit_calls.append((cookie, link_url, folder_id))
        return {"message": "已接收"}


class FakeJsonRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


class ResourceOfflineJobTest(unittest.IsolatedAsyncioTestCase):
    def test_legacy_magnet_filter_represents_all_offline_link_types(self):
        self.assertTrue(
            resource_item_matches_provider_filter(
                {"link_type": "ed2k", "link_url": SAMPLE_LINK},
                "magnet",
            )
        )

    def test_ed2k_snapshot_keeps_source_titles_and_original_page(self):
        snapshot = build_resource_job_snapshot(
            {
                "title": "摇滚兄弟私生活.2024 - S03E08.mkv",
                "link_url": SAMPLE_LINK,
                "link_type": "ed2k",
                "message_url": "https://telegra.ph/example",
                "extra": {
                    "source_url": "https://telegra.ph/example",
                    "source_resource_title": "频道资源标题",
                    "source_page_title": "页面标题",
                },
            },
            "ed2k",
        )

        self.assertEqual(snapshot["source_url"], "https://telegra.ph/example")
        self.assertEqual(snapshot["source_resource_title"], "频道资源标题")
        self.assertEqual(snapshot["source_page_title"], "页面标题")

    async def test_ed2k_job_uses_offline_provider(self):
        provider = FakeOfflineProvider()
        job = {
            "id": 31,
            "resource_id": 0,
            "title": "摇滚兄弟私生活.2024 - S03E08.mkv",
            "link_url": SAMPLE_LINK,
            "link_type": "ed2k",
            "folder_id": "season-folder",
            "savepath": "电视剧/摇滚兄弟私生活 (2024) - S03",
            "monitor_task_name": "电视剧监控",
            "refresh_delay_seconds": 4,
            "auto_refresh": False,
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
        ), mock.patch.object(resource_service, "release_process_memory"):
            await resource_service.run_resource_job(31)

        self.assertEqual(provider.submit_calls, [("cookie", SAMPLE_LINK, "season-folder")])
        self.assertEqual(updates[-1][1]["status"], "submitted")

    async def test_batch_prepares_target_folder_once_and_reuses_folder_id(self):
        runner = getattr(resource_service, "run_offline_resource_job_batch", None)
        self.assertIsNotNone(runner, "缺少统一离线批量任务协调器")
        provider = FakeOfflineProvider(folder_id="shared-folder")
        updates = []

        with mock.patch.object(resource_service, "get_config", return_value={}), mock.patch.object(
            resource_service, "get_provider_or_none", return_value=provider
        ), mock.patch.object(
            resource_service,
            "update_resource_job",
            side_effect=lambda job_id, **fields: updates.append((job_id, fields)),
        ), mock.patch.object(
            resource_service,
            "run_resource_job",
            new=mock.AsyncMock(),
        ) as job_runner:
            await runner(
                [41, 42],
                provider_name="115",
                savepath="电视剧/摇滚兄弟私生活 (2024) - S03",
                create_folder=True,
            )

        self.assertEqual(
            provider.ensure_calls,
            [("cookie", "电视剧/摇滚兄弟私生活 (2024) - S03")],
        )
        self.assertEqual(provider.resolve_calls, [])
        folder_updates = [fields["folder_id"] for _job_id, fields in updates if "folder_id" in fields]
        self.assertEqual(folder_updates, ["shared-folder", "shared-folder"])
        self.assertEqual(job_runner.await_args_list, [mock.call(41), mock.call(42)])

    async def test_batch_folder_failure_marks_every_job_with_traceable_error(self):
        runner = getattr(resource_service, "run_offline_resource_job_batch", None)
        self.assertIsNotNone(runner, "缺少统一离线批量任务协调器")
        provider = FakeOfflineProvider(folder_error=RuntimeError("创建季目录失败"))
        failed = []

        with mock.patch.object(resource_service, "get_config", return_value={}), mock.patch.object(
            resource_service, "get_provider_or_none", return_value=provider
        ), mock.patch.object(
            resource_service,
            "get_resource_job",
            side_effect=lambda job_id, include_private=False: {"id": job_id, "resource_id": 0},
        ), mock.patch.object(
            resource_service,
            "_mark_resource_job_failed",
            side_effect=lambda job_id, resource_id, detail: failed.append((job_id, resource_id, detail)),
        ), mock.patch.object(resource_service, "run_resource_job", new=mock.AsyncMock()) as job_runner:
            await runner(
                [51, 52],
                provider_name="115",
                savepath="电视剧/摇滚兄弟私生活 (2024) - S03",
                create_folder=True,
            )

        self.assertEqual([item[0] for item in failed], [51, 52])
        self.assertTrue(all("创建季目录失败" in item[2] for item in failed))
        job_runner.assert_not_awaited()

    async def test_magnet_job_keeps_legacy_magnet_provider_compatibility(self):
        provider = FakeOfflineProvider()
        job = {
            "id": 61,
            "resource_id": 0,
            "title": "旧磁力任务",
            "link_url": "magnet:?xt=urn:btih:1234567890123456789012345678901234567890",
            "link_type": "magnet",
            "folder_id": "legacy-folder",
            "savepath": "电影",
            "monitor_task_name": "",
            "auto_refresh": False,
            "extra": {"magnet_provider": "115"},
            "extra_json": json.dumps({"magnet_provider": "115"}),
        }

        with mock.patch.object(resource_service, "get_resource_job", return_value=job), mock.patch.object(
            resource_service, "get_resource_item", return_value={}
        ), mock.patch.object(resource_service, "get_config", return_value={}), mock.patch.object(
            resource_service, "get_provider_or_none", return_value=provider
        ), mock.patch.object(resource_service, "update_resource_job"), mock.patch.object(
            resource_service, "release_process_memory"
        ):
            await resource_service.run_resource_job(61)

        self.assertEqual(len(provider.submit_calls), 1)


class ResourceOfflineJobDatabaseTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        self.original_db_ensured = db._DB_ENSURED
        db.DB_PATH = str(Path(self.temp_dir.name) / "resource-jobs.db")
        db._DB_ENSURED = False
        db.ensure_db()

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        db._DB_ENSURED = self.original_db_ensured
        self.temp_dir.cleanup()

    def test_batch_job_creation_rolls_back_every_item_when_one_insert_fails(self):
        with db.db_connection() as conn:
            conn.execute(
                """
                CREATE TRIGGER fail_second_resource_job
                BEFORE INSERT ON resource_jobs
                WHEN NEW.title = '触发回滚'
                BEGIN
                    SELECT RAISE(ABORT, '测试批量回滚');
                END
                """
            )
            conn.commit()

        create_batch = getattr(resource_jobs, "create_resource_jobs", None)
        self.assertIsNotNone(create_batch, "缺少原子化批量任务创建接口")
        entries = [
            (
                {"id": 0, "title": "第一集", "link_url": SAMPLE_LINK, "link_type": "ed2k"},
                {"savepath": "电视剧/整季", "extra": {"offline_provider": "115"}},
            ),
            (
                {"id": 0, "title": "触发回滚", "link_url": SECOND_LINK, "link_type": "ed2k"},
                {"savepath": "电视剧/整季", "extra": {"offline_provider": "115"}},
            ),
        ]

        with mock.patch.object(resource_jobs, "invalidate_resource_state_snapshot"), mock.patch.object(
            resource_jobs, "touch_resource_jobs_state_signal"
        ):
            with self.assertRaisesRegex(Exception, "测试批量回滚"):
                create_batch(entries)

        with db.db_connection() as conn:
            count = conn.execute("SELECT COUNT(1) FROM resource_jobs").fetchone()[0]
        self.assertEqual(count, 0)

    async def test_retry_ed2k_job_keeps_provider_and_source_snapshot(self):
        job = {
            "id": 91,
            "resource_id": 0,
            "status": "failed",
            "title": "摇滚兄弟私生活.2024 - S03E08.mkv",
            "link_url": SAMPLE_LINK,
            "link_type": "ed2k",
            "folder_id": "season-folder",
            "savepath": "电视剧/摇滚兄弟私生活 (2024) - S03",
            "sharetitle": "",
            "monitor_task_name": "电视剧监控",
            "refresh_delay_seconds": 4,
            "auto_refresh": True,
            "message_url": "https://telegra.ph/example",
            "extra": {
                "offline_provider": "115",
                "offline_provider_label": "115",
                "source_url": "https://telegra.ph/example",
                "source_resource_title": "频道资源标题",
                "source_page_title": "页面标题",
            },
            "_snapshot": {
                "source_url": "https://telegra.ph/example",
                "source_resource_title": "频道资源标题",
                "source_page_title": "页面标题",
            },
        }

        with mock.patch.object(resource_service, "get_resource_job", return_value=job), mock.patch.object(
            resource_service, "create_resource_job", return_value=92
        ) as create_job, mock.patch.object(resource_service, "update_resource_job"), mock.patch.object(
            resource_service, "submit_background"
        ):
            result = await resource_service.retry_resource_job(91)

        self.assertEqual(result["job_id"], 92)
        resource, payload = create_job.call_args.args
        self.assertEqual(resource["link_type"], "ed2k")
        self.assertEqual(resource["extra"]["source_resource_title"], "频道资源标题")
        self.assertEqual(resource["extra"]["source_page_title"], "页面标题")
        self.assertEqual(payload["extra"]["offline_provider"], "115")


class ResourceEd2kBatchRouteTest(unittest.IsolatedAsyncioTestCase):
    def batch_endpoint(self):
        endpoint = next(
            (
                route.endpoint
                for route in resource_routes.router.routes
                if getattr(route, "path", "") == "/resource/ed2k/jobs/create-batch"
                and "POST" in getattr(route, "methods", set())
            ),
            None,
        )
        self.assertIsNotNone(endpoint, "POST /resource/ed2k/jobs/create-batch 尚未注册")
        return endpoint

    async def test_single_file_defaults_to_a_new_child_folder(self):
        endpoint = self.batch_endpoint()
        provider = FakeOfflineProvider()
        submitted = []

        with mock.patch.object(resource_routes, "get_config", return_value={}), mock.patch.object(
            resource_routes, "get_provider_or_none", return_value=provider
        ), mock.patch.object(
            resource_routes, "match_monitor_task_for_savepath", return_value={}
        ), mock.patch.object(
            resource_routes, "create_resource_jobs", return_value=[71]
        ) as create_jobs, mock.patch.object(
            resource_routes,
            "submit_background",
            side_effect=lambda fn, *args, **kwargs: submitted.append((fn, args, kwargs)),
        ):
            response = await endpoint(
                FakeJsonRequest(
                    {
                        "items": [{"link_url": SAMPLE_LINK}],
                        "parent_savepath": "电视剧",
                        "folder_name": "摇滚兄弟私生活 (2024) - S03",
                        "source_url": "https://telegra.ph/example",
                        "resource_title": "频道资源标题",
                        "page_title": "页面标题",
                    }
                )
            )

        self.assertTrue(response["ok"])
        self.assertEqual(response["savepath"], "电视剧/摇滚兄弟私生活 (2024) - S03")
        self.assertTrue(response["create_folder"])
        [(resource, payload)] = create_jobs.call_args.args[0]
        self.assertEqual(resource["title"], "摇滚兄弟私生活.2024 - S03E08.mkv")
        self.assertEqual(payload["extra"]["offline_provider"], "115")
        self.assertEqual(payload["folder_id"], "")
        self.assertEqual(len(submitted), 1)

    async def test_multiple_files_can_save_directly_to_selected_parent(self):
        endpoint = self.batch_endpoint()
        provider = FakeOfflineProvider()

        with mock.patch.object(resource_routes, "get_config", return_value={}), mock.patch.object(
            resource_routes, "get_provider_or_none", return_value=provider
        ), mock.patch.object(
            resource_routes, "match_monitor_task_for_savepath", return_value={}
        ), mock.patch.object(
            resource_routes, "create_resource_jobs", return_value=[81, 82]
        ) as create_jobs, mock.patch.object(resource_routes, "submit_background"):
            response = await endpoint(
                FakeJsonRequest(
                    {
                        "items": [{"link_url": SAMPLE_LINK}, {"link_url": SECOND_LINK}],
                        "parent_savepath": "电视剧",
                        "parent_folder_id": "tv-folder",
                        "create_folder": False,
                    }
                )
            )

        self.assertEqual(response["job_ids"], [81, 82])
        self.assertEqual(response["savepath"], "电视剧")
        self.assertFalse(response["create_folder"])
        self.assertEqual(
            [payload["folder_id"] for _resource, payload in create_jobs.call_args.args[0]],
            ["tv-folder", "tv-folder"],
        )


if __name__ == "__main__":
    unittest.main()
