import asyncio
import unittest
from datetime import datetime, timedelta
from unittest import mock

from app.services import subscription_offline_cleanup as cleanup


def _fmt(delta_days: float) -> str:
    return (datetime.now() - timedelta(days=delta_days)).strftime("%Y-%m-%d %H:%M:%S")


class FakeProvider:
    supports_offline = True

    def __init__(self):
        self.delete_calls = []

    def get_cookie(self, cfg):
        return "cookie-115"

    def list_entries(self, cookie, cid):
        if cid == "root":
            return [
                {"id": "t1", "name": "任务A", "is_dir": True},
                {"id": "t2", "name": "任务B", "is_dir": True},
            ]
        if cid == "t1":
            return [
                {"id": "t-dir", "name": "种子目录", "is_dir": True},
                {"id": "e-dir", "name": "空目录", "is_dir": True},
                {
                    "id": "f-fresh",
                    "name": "fresh.mkv",
                    "size": 1000,
                    "is_dir": False,
                    "modified_at": _fmt(0.1),
                },
            ]
        if cid == "t-dir":
            return [
                {
                    "id": "f-junk",
                    "name": "sample.mkv",
                    "size": 1,
                    "is_dir": False,
                    "modified_at": _fmt(0.1),
                },
                {
                    "id": "f-old",
                    "name": "old.mkv",
                    "size": 1000,
                    "is_dir": False,
                    "modified_at": _fmt(10),
                },
            ]
        if cid in ("e-dir", "t2"):
            return []
        return []

    def delete_entries(self, cookie, entry_ids, parent_id=""):
        self.delete_calls.append((list(entry_ids), str(parent_id or "")))
        return {"state": True}

    def resolve_folder_id_by_path(self, cookie, path):
        return "root"

    def query_offline_tasks(self, cookie, page=1):
        return {
            "tasks": [
                {
                    "info_hash": "hash-running",
                    "status": 1,
                    "percent": 50,
                    "wp_path_id": "t2",
                    "name": "运行中任务",
                }
            ],
            "page_count": 1,
        }


class SubscriptionOfflineCleanupTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.provider = FakeProvider()

    async def test_clean_task_removes_junk_expired_and_empty_dirs(self):
        result = await cleanup._clean_one_staging_task(
            self.provider,
            "cookie",
            "t1",
            "root",
        )
        self.assertEqual(result["junk_deleted"], 1)
        self.assertEqual(result["expired_deleted"], 1)
        self.assertEqual(result["kept_files"], 1)
        self.assertEqual(result["empty_dirs_deleted"], 2)
        deleted_ids = sorted(item for ids, _parent in self.provider.delete_calls for item in ids)
        self.assertEqual(deleted_ids, ["e-dir", "f-junk", "f-old", "t-dir"])

    async def test_running_task_skips_cleanup(self):
        result = await cleanup._clean_one_staging_task(
            self.provider,
            "cookie",
            "t2",
            "root",
            has_running_task=True,
        )
        self.assertTrue(result["skipped_running"])
        self.assertEqual(self.provider.delete_calls, [])

    async def test_periodic_cleanup_scans_staging_root_and_skips_running(self):
        with mock.patch.object(cleanup, "get_config", return_value={}), mock.patch.object(
            cleanup, "get_provider_or_none", return_value=self.provider
        ):
            stats = await cleanup.run_subscription_offline_staging_cleanup_once()
        self.assertEqual(stats["tasks_scanned"], 2)
        self.assertEqual(stats["skipped_running"], 1)
        self.assertEqual(stats["junk_deleted"], 1)
        self.assertEqual(stats["expired_deleted"], 1)
        self.assertEqual(stats["empty_dirs_deleted"], 2)
        self.assertEqual(stats["kept_files"], 1)
