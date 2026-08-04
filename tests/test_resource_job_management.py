import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import db
from app import core
from app import resource_jobs
from app.routes import resource as resource_routes


class FakeJsonRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


class ResourceJobManagementTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        self.original_db_ensured = db._DB_ENSURED
        db.DB_PATH = str(Path(self.temp_dir.name) / "resource-jobs.db")
        db._DB_ENSURED = False
        db.ensure_db()
        self.invalidate_patcher = mock.patch.object(resource_jobs, "invalidate_resource_state_snapshot")
        self.signal_patcher = mock.patch.object(resource_jobs, "touch_resource_jobs_state_signal")
        self.invalidate_patcher.start()
        self.signal_patcher.start()

    def tearDown(self):
        self.signal_patcher.stop()
        self.invalidate_patcher.stop()
        db.DB_PATH = self.original_db_path
        db._DB_ENSURED = self.original_db_ensured
        self.temp_dir.cleanup()

    @staticmethod
    def response_json(response):
        return json.loads(response.body.decode("utf-8"))

    @staticmethod
    def delete_endpoint():
        endpoint = next(
            (
                route.endpoint
                for route in resource_routes.router.routes
                if getattr(route, "path", "") == "/resource/jobs/delete"
                and "POST" in getattr(route, "methods", set())
            ),
            None,
        )
        if endpoint is None:
            raise AssertionError("POST /resource/jobs/delete 尚未注册")
        return endpoint

    @staticmethod
    def insert_resource_item(status="completed"):
        now = db.now_text()
        with db.db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO resource_items(title, created_at, last_seen_at, status)
                VALUES (?, ?, ?, ?)
                """,
                ("测试资源", now, now, status),
            )
            resource_id = int(cursor.lastrowid)
            conn.commit()
        return resource_id

    @staticmethod
    def insert_job(resource_id, status="completed"):
        now = db.now_text()
        with db.db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO resource_jobs(resource_id, title, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (resource_id, "测试任务", status, now, now),
            )
            job_id = int(cursor.lastrowid)
            conn.commit()
        return job_id

    @staticmethod
    def resource_status(resource_id):
        with db.db_connection() as conn:
            row = conn.execute("SELECT status FROM resource_items WHERE id = ?", (resource_id,)).fetchone()
        return str(row[0]) if row else ""

    def test_delete_completed_job_removes_only_the_record(self):
        resource_id = self.insert_resource_item()
        job_id = self.insert_job(resource_id, "completed")

        result = resource_jobs.delete_resource_job(job_id)

        self.assertEqual(
            result,
            {"job_id": job_id, "deleted": 1, "reset_items": 1},
        )
        self.assertEqual(resource_jobs.get_resource_job(job_id), {})
        self.assertEqual(self.resource_status(resource_id), "new")

    def test_delete_failed_job_keeps_resource_state_when_another_job_remains(self):
        resource_id = self.insert_resource_item(status="failed")
        job_id = self.insert_job(resource_id, "failed")
        self.insert_job(resource_id, "completed")

        result = resource_jobs.delete_resource_job(job_id)

        self.assertEqual(result["deleted"], 1)
        self.assertEqual(result["reset_items"], 0)
        self.assertEqual(self.resource_status(resource_id), "failed")

    def test_delete_rejects_active_job_without_removing_it(self):
        resource_id = self.insert_resource_item(status="queued")
        job_id = self.insert_job(resource_id, "submitted")

        with self.assertRaisesRegex(RuntimeError, "仅支持删除已完成或失败的导入任务"):
            resource_jobs.delete_resource_job(job_id)

        self.assertEqual(resource_jobs.get_resource_job(job_id)["status"], "submitted")

    def test_delete_missing_job_reports_not_found(self):
        with self.assertRaisesRegex(LookupError, "任务不存在"):
            resource_jobs.delete_resource_job(999)

    def test_delete_last_job_resets_sqlite_sequence(self):
        resource_id = self.insert_resource_item()
        job_id = self.insert_job(resource_id, "completed")

        resource_jobs.delete_resource_job(job_id)

        recreated_id = resource_jobs.create_resource_job(
            {"id": resource_id, "title": "重新创建"},
            {"savepath": "电影"},
        )
        self.assertEqual(recreated_id, 1)

    def test_page_limit_accepts_the_full_history_window(self):
        page = resource_jobs.list_resource_jobs_page(limit=999999)

        self.assertEqual(page["pagination"]["limit"], 25000)

    async def test_resource_state_payload_keeps_the_full_history_window(self):
        with mock.patch.object(core, "get_config", return_value={}), mock.patch.object(
            core, "recover_resource_jobs_if_due", return_value={}
        ), mock.patch.object(
            core, "_build_resource_state_payload_snapshot", return_value={"ok": True}
        ) as build_snapshot:
            result = await core.build_resource_state_payload(job_limit=999999)

        self.assertEqual(result, {"ok": True})
        self.assertEqual(build_snapshot.call_args.args[5], 25000)

    async def test_delete_route_returns_contract_and_status_codes(self):
        endpoint = self.delete_endpoint()
        resource_id = self.insert_resource_item()
        completed_job_id = self.insert_job(resource_id, "completed")
        submitted_job_id = self.insert_job(resource_id, "submitted")

        invalid_response = await endpoint(FakeJsonRequest({"job_id": 0}))
        self.assertEqual(invalid_response.status_code, 400)
        self.assertEqual(self.response_json(invalid_response)["ok"], False)

        missing_response = await endpoint(FakeJsonRequest({"job_id": 99999}))
        self.assertEqual(missing_response.status_code, 404)
        self.assertEqual(self.response_json(missing_response)["ok"], False)

        active_response = await endpoint(FakeJsonRequest({"job_id": submitted_job_id}))
        self.assertEqual(active_response.status_code, 409)
        self.assertEqual(self.response_json(active_response)["ok"], False)

        success_response = await endpoint(FakeJsonRequest({"job_id": completed_job_id}))
        self.assertEqual(
            success_response,
            {"ok": True, "job_id": completed_job_id, "deleted": 1, "reset_items": 0},
        )


if __name__ == "__main__":
    unittest.main()
