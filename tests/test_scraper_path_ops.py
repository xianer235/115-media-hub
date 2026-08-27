import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.routes import scraper as scraper_routes  # noqa: E402
from app.services import scraper as scraper_service  # noqa: E402
from app.providers import pan115  # noqa: E402


class _FakeRequest:
    def __init__(self, data):
        self._data = data
        self.query_params = dict((data or {}).get("_query", {}) or {})

    async def json(self):
        return self._data


class ScraperPathEntryTest(unittest.TestCase):
    def test_resolve_scraper_path_entry_115(self):
        with patch.object(scraper_service, "get_config", return_value={"cookie_115": "ck"}), patch.object(
            scraper_service, "resolve_115_folder_id_by_path", return_value="cid1"
        ), patch.object(
            scraper_service,
            "resolve_115_entry_by_name",
            return_value={"id": "fid9", "name": "x.mkv", "is_dir": False},
        ):
            entry = scraper_service.resolve_scraper_path_entry("115", "/电影/动作/x.mkv")
        self.assertEqual(entry["id"], "fid9")
        self.assertEqual(entry["parent_id"], "cid1")
        self.assertEqual(entry["path"], "电影/动作/x.mkv")
        self.assertFalse(entry["is_dir"])

    def test_resolve_scraper_path_entry_root_level(self):
        with patch.object(scraper_service, "get_config", return_value={"cookie_115": "ck"}), patch.object(
            scraper_service, "resolve_115_folder_id_by_path", return_value="cid0"
        ), patch.object(
            scraper_service,
            "resolve_115_entry_by_name",
            return_value={"id": "cid7", "name": "电影", "is_dir": True},
        ):
            entry = scraper_service.resolve_scraper_path_entry("115", "/电影")
        self.assertEqual(entry["id"], "cid7")
        self.assertEqual(entry["path"], "电影")
        self.assertTrue(entry["is_dir"])

    def test_resolve_scraper_path_entry_rejects_non_115(self):
        with patch.object(scraper_service, "get_config", return_value={"cookie_115": "ck"}):
            with self.assertRaises(RuntimeError) as ctx:
                scraper_service.resolve_scraper_path_entry("quark", "/电影/x.mkv")
            self.assertIn("仅支持 115", str(ctx.exception))

    def test_resolve_scraper_path_entry_missing_cookie(self):
        with patch.object(scraper_service, "get_config", return_value={"cookie_115": ""}):
            with self.assertRaises(RuntimeError):
                scraper_service.resolve_scraper_path_entry("115", "/电影/x.mkv")

    def test_resolve_scraper_dest_folder_id(self):
        with patch.object(scraper_service, "get_config", return_value={"cookie_115": "ck"}), patch.object(
            scraper_service, "resolve_115_folder_id_by_path", return_value="cid88"
        ):
            self.assertEqual(scraper_service.resolve_scraper_dest_folder_id("115", "/电影/新目录"), "cid88")

    def test_resolve_scraper_dest_folder_id_rejects_non_115(self):
        with patch.object(scraper_service, "get_config", return_value={"cookie_115": "ck"}):
            with self.assertRaises(RuntimeError) as ctx:
                scraper_service.resolve_scraper_dest_folder_id("quark", "/电影/新目录")
            self.assertIn("仅支持 115", str(ctx.exception))

    def test_resolve_selected_paths_propagates_errors(self):
        def _raise(_provider, _path):
            raise RuntimeError("115 Cookie 未配置")

        with patch.object(scraper_service, "resolve_scraper_path_entry", side_effect=_raise):
            with self.assertRaises(RuntimeError) as ctx:
                scraper_service._resolve_scraper_selected_paths(
                    "115",
                    [{"path": "/电影/x.mkv"}],
                )
            self.assertIn("Cookie", str(ctx.exception))

    def test_resolve_selected_paths_merges_resolved_entry(self):
        resolved = {"id": "fid1", "name": "x.mkv", "is_dir": False, "path": "电影/x.mkv"}
        with patch.object(scraper_service, "resolve_scraper_path_entry", return_value=resolved):
            items = scraper_service._resolve_scraper_selected_paths(
                "115",
                [{"path": "/电影/x.mkv", "extra": 1}],
            )
        self.assertEqual(items[0]["id"], "fid1")
        self.assertEqual(items[0]["extra"], 1)


class Pan115EntryResolveTest(unittest.TestCase):
    def test_raw_file_with_id_only_is_not_directory(self):
        with patch.object(pan115, "list_115_entries", return_value=[]), patch.object(
            pan115, "throttle_115_api_requests", return_value=None
        ), patch.object(
            pan115,
            "http_request_json",
            return_value={"state": True, "data": [{"id": "abc123", "n": "x.mkv", "s": 1024}]},
        ):
            entry = scraper_service.resolve_115_entry_by_name("ck", "0", "x.mkv")
        self.assertEqual(entry["id"], "abc123")
        self.assertFalse(entry["is_dir"])

    def test_raw_folder_with_cid_is_directory(self):
        with patch.object(pan115, "list_115_entries", return_value=[]), patch.object(
            pan115, "throttle_115_api_requests", return_value=None
        ), patch.object(
            pan115,
            "http_request_json",
            return_value={"state": True, "data": [{"cid": "cid9", "n": "电影"}]},
        ):
            entry = scraper_service.resolve_115_entry_by_name("ck", "0", "电影")
        self.assertEqual(entry["id"], "cid9")
        self.assertTrue(entry["is_dir"])


class ScraperPathOpsRouteTest(unittest.TestCase):
    def test_folder_path_endpoint_returns_real_path(self):
        resolved = {
            "ok": True,
            "provider": "115",
            "cid": "c1",
            "path": "115自存电视剧/狂飙 (2023) [tmdbid-210757]",
            "ancestors": [
                {"id": "p1", "name": "115自存电视剧", "parent_id": "0"},
                {"id": "c1", "name": "狂飙 (2023) [tmdbid-210757]", "parent_id": "p1"},
            ],
        }
        with patch.object(scraper_routes, "resolve_scraper_folder_path", return_value=resolved) as resolver:
            result = asyncio.run(
                scraper_routes.get_scraper_folder_path_endpoint(
                    "115", _FakeRequest({"_query": {"cid": "c1"}})
                )
            )

        self.assertTrue(result["ok"])
        resolver.assert_called_once_with("115", "c1")
        self.assertEqual(result["path"], resolved["path"])
        self.assertEqual(result["ancestors"], resolved["ancestors"])

    def test_rename_path_resolves_and_preserves_request_id(self):
        resolved = {"id": "fid1", "parent_id": "cid0", "name": "x.mkv", "is_dir": False, "path": "/电影/x.mkv"}
        with patch.object(scraper_routes, "resolve_scraper_path_entry", return_value=resolved), patch.object(
            scraper_routes, "rename_scraper_entry", return_value={"ok": True}
        ) as rename:
            result = asyncio.run(
                scraper_routes.rename_scraper_entry_endpoint(
                    "115", _FakeRequest({"path": "/电影/x.mkv", "name": "y.mkv", "request_id": "r1"})
                )
            )
        self.assertTrue(result["ok"])
        args = rename.call_args.args
        self.assertEqual(args[0], "115")
        self.assertEqual(args[1], "fid1")
        self.assertEqual(args[2], "cid0")
        self.assertEqual(args[3], "y.mkv")
        self.assertEqual(args[4], resolved)
        self.assertEqual(args[5], "r1")

    def test_rename_keeps_entry_id_input_path_free(self):
        with patch.object(scraper_routes, "rename_scraper_entry", return_value={"ok": True}) as rename:
            result = asyncio.run(
                scraper_routes.rename_scraper_entry_endpoint(
                    "115", _FakeRequest({"entry_id": "fid9", "name": "y.mkv", "entry": {"id": "fid9", "path": "/a/x.mkv"}})
                )
            )
        self.assertTrue(result["ok"])
        args = rename.call_args.args
        self.assertEqual(args[1], "fid9")
        self.assertEqual(args[4], {"id": "fid9", "path": "/a/x.mkv"})

    def test_move_path_and_dest_resolved(self):
        resolved = {"id": "fid1", "parent_id": "cid0", "name": "x.mkv", "is_dir": False, "path": "/电影/x.mkv"}
        with patch.object(scraper_routes, "resolve_scraper_path_entry", return_value=resolved), patch.object(
            scraper_routes, "resolve_scraper_dest_folder_id", return_value="cid88"
        ), patch.object(scraper_routes, "move_scraper_entries", return_value={"ok": True}) as move:
            result = asyncio.run(
                scraper_routes.move_scraper_entries_endpoint(
                    "115", _FakeRequest({"path": "/电影/x.mkv", "dest": "/电影/新目录", "request_id": "r2"})
                )
            )
        self.assertTrue(result["ok"])
        args = move.call_args.args
        self.assertEqual(args[1], ["fid1"])
        self.assertEqual(args[2], "cid88")
        self.assertEqual(args[3], "cid0")
        self.assertEqual(args[4], [resolved])
        self.assertEqual(args[5], "电影/新目录")
        self.assertEqual(args[6], "r2")

    def test_delete_path_sets_parent_from_resolved(self):
        resolved = {"id": "fid1", "parent_id": "cid0", "name": "x.mkv", "is_dir": False, "path": "/电影/x.mkv"}
        with patch.object(scraper_routes, "resolve_scraper_path_entry", return_value=resolved), patch.object(
            scraper_routes, "delete_scraper_entries", return_value={"ok": True}
        ) as delete:
            result = asyncio.run(
                scraper_routes.delete_scraper_entries_endpoint(
                    "115", _FakeRequest({"path": "/电影/x.mkv", "request_id": "r3"})
                )
            )
        self.assertTrue(result["ok"])
        args = delete.call_args.args
        self.assertEqual(args[1], ["fid1"])
        self.assertEqual(args[2], "cid0")
        self.assertEqual(args[3], [resolved])
        self.assertEqual(args[4], "r3")

    def test_non_115_path_returns_400(self):
        def _raise(_provider, _path):
            raise RuntimeError("路径操作当前仅支持 115，quark 请改用 entry_id/entry_ids 参数")

        with patch.object(scraper_routes, "resolve_scraper_path_entry", side_effect=_raise):
            response = asyncio.run(
                scraper_routes.rename_scraper_entry_endpoint(
                    "quark", _FakeRequest({"path": "/电影/x.mkv", "name": "y.mkv"})
                )
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("仅支持 115", response.body.decode())


if __name__ == "__main__":
    unittest.main()
