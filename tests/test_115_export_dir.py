import time
import unittest
from unittest.mock import patch

from app.providers import pan115


class Pan115ExportDirTest(unittest.TestCase):
    def setUp(self):
        self._health_success = patch.object(pan115, "mark_cookie_health_success")
        self._health_failure = patch.object(pan115, "mark_cookie_health_failure")
        self._health_success.start()
        self._health_failure.start()

    def tearDown(self):
        self._health_failure.stop()
        self._health_success.stop()

    def test_submit_returns_export_id(self):
        with patch.object(pan115, "http_request_form_json", return_value={"state": True, "data": {"export_id": "abc123"}}):
            export_id = pan115.submit_115_export_dir("cookie", "123", target="U_1_0", layer_limit=0)
        self.assertEqual(export_id, "abc123")

    def test_submit_forwards_layer_limit_and_target(self):
        captured = {}

        def fake_form_json(url, payload, **kwargs):
            captured["url"] = url
            captured["payload"] = payload
            return {"state": True, "data": {"export_id": "e1"}}

        with patch.object(pan115, "http_request_form_json", side_effect=fake_form_json):
            pan115.submit_115_export_dir("cookie", "456", target="U_1_7", layer_limit=3)
        self.assertEqual(captured["url"], "https://webapi.115.com/files/export_dir")
        self.assertEqual(captured["payload"], {"file_ids": "456", "target": "U_1_7", "layer_limit": 3})

    def test_submit_raises_when_state_false(self):
        with patch.object(pan115, "http_request_form_json", return_value={"state": False, "error": "已有任务在运行"}):
            with self.assertRaisesRegex(RuntimeError, "已有任务在运行"):
                pan115.submit_115_export_dir("cookie", "123")

    def test_submit_raises_when_export_id_missing(self):
        with patch.object(pan115, "http_request_form_json", return_value={"state": True, "data": {}}):
            with self.assertRaisesRegex(RuntimeError, "未返回任务 ID"):
                pan115.submit_115_export_dir("cookie", "123")

    def test_query_returns_empty_while_running(self):
        with patch.object(pan115, "_request_115_webapi_json", return_value={"state": True, "data": None}):
            self.assertEqual(pan115.query_115_export_dir_status("cookie", "e1"), {})

    def test_query_returns_completed_result(self):
        with patch.object(
            pan115,
            "_request_115_webapi_json",
            return_value={
                "state": True,
                "data": {
                    "export_id": "e1",
                    "file_id": "f1",
                    "file_name": "目录树.txt",
                    "pick_code": "pc1",
                },
            },
        ):
            data = pan115.query_115_export_dir_status("cookie", "e1")
        self.assertEqual(data["file_id"], "f1")
        self.assertEqual(data["pick_code"], "pc1")

    def test_wait_polls_until_completed(self):
        calls = {"count": 0}

        def fake_query(_cookie, _export_id):
            calls["count"] += 1
            if calls["count"] < 3:
                return {}
            return {"export_id": "e1", "file_id": "f1", "file_name": "x", "pick_code": "pc1"}

        with patch.object(pan115, "query_115_export_dir_status", side_effect=fake_query), patch.object(
            pan115, "throttle_115_api_requests", lambda: None
        ):
            data = pan115.wait_115_export_dir("cookie", "e1", timeout_seconds=10, check_interval=0)
        self.assertEqual(data["file_id"], "f1")
        self.assertEqual(calls["count"], 3)

    def test_wait_raises_on_timeout(self):
        started = time.monotonic()
        with patch.object(pan115, "query_115_export_dir_status", return_value={}), patch.object(
            pan115, "throttle_115_api_requests", lambda: None
        ):
            with self.assertRaisesRegex(RuntimeError, "e1"):
                pan115.wait_115_export_dir("cookie", "e1", timeout_seconds=1, check_interval=0)
        self.assertGreaterEqual(time.monotonic() - started, 1.0)

    def test_get_file_sha1_by_id_matches_entry(self):
        entries = [
            {"id": "f1", "name": "目录树-影视库.txt", "is_dir": False, "sha1": "abc123"},
            {"id": "f2", "name": "其它.txt", "is_dir": False, "sha1": "def456"},
        ]
        with patch.object(
            pan115, "get_115_file_info", side_effect=RuntimeError("not found")
        ), patch.object(pan115, "list_115_entries", return_value=entries):
            self.assertEqual(pan115.get_115_file_sha1_by_id("cookie", "f1"), "abc123")

    def test_get_file_sha1_by_id_returns_empty_when_missing(self):
        with patch.object(
            pan115, "get_115_file_info", side_effect=RuntimeError("not found")
        ), patch.object(pan115, "list_115_entries", return_value=[{"id": "f9", "name": "x", "is_dir": False}]):
            self.assertEqual(pan115.get_115_file_sha1_by_id("cookie", "f1", attempts=1), "")

    def test_get_file_sha1_by_id_uses_get_info_first(self):
        with patch.object(
            pan115, "get_115_file_info", return_value={"id": "f1", "name": "x", "sha1": "info-sha1", "pick_code": "pc"}
        ), patch.object(pan115, "list_115_entries", side_effect=AssertionError("不应走列表")):
            self.assertEqual(pan115.get_115_file_sha1_by_id("cookie", "f1"), "info-sha1")

    def test_get_file_info_parses_response(self):
        payload = {
            "state": True,
            "data": [
                {
                    "fid": "f1",
                    "n": "目录树-影视库.txt",
                    "sha": "abc123",
                    "pc": "pc1",
                    "s": 123,
                }
            ],
        }
        with patch.object(pan115, "_request_115_webapi_json", return_value=payload):
            info = pan115.get_115_file_info("cookie", "f1")
        self.assertEqual(info["name"], "目录树-影视库.txt")
        self.assertEqual(info["sha1"], "abc123")
        self.assertEqual(info["pick_code"], "pc1")

    def test_get_file_info_raises_when_state_false(self):
        with patch.object(pan115, "_request_115_webapi_json", return_value={"state": False, "error": "boom"}):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                pan115.get_115_file_info("cookie", "f1")


if __name__ == "__main__":
    unittest.main()
