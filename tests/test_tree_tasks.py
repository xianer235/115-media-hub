import asyncio
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from app import db
from app.core import build_tree_task_defaults, normalize_config, normalize_tree_task
from app.routes import tree as tree_routes
from app.services import strm_files, tree
from app import core as core_module


def _make_task(folder_path="影视库/电视剧", prefix="影视库", exclude=1, last_sha1="", last_md5=""):
    task = normalize_tree_task(
        {
            "folder_path": folder_path,
            "prefix": prefix,
            "exclude": exclude,
            "last_remote_sha1": last_sha1,
            "last_local_md5": last_md5,
        }
    )
    return task


class TreeTaskDefaultsTest(unittest.TestCase):
    def test_deep_folder_defaults(self):
        defaults = build_tree_task_defaults("影视库/电视剧")
        self.assertEqual(defaults["tree_name"], "目录树-影视库-电视剧")
        self.assertEqual(defaults["prefix"], "影视库")
        self.assertEqual(defaults["exclude"], 1)

    def test_root_level_folder_defaults(self):
        defaults = build_tree_task_defaults("影视库")
        self.assertEqual(defaults["tree_name"], "目录树-影视库")
        self.assertEqual(defaults["prefix"], "")

    def test_normalize_drops_legacy_tree_config(self):
        cfg = normalize_config(
            {
                "trees": [{"path": "old.txt", "prefix": "X", "exclude": 1}],
                "sync_mode": "full",
                "check_hash": True,
                "cron_hour": 30,
                "last_hash": "{}",
                "tree_tasks": [{"folder_path": "影视库/电影"}],
            }
        )
        self.assertNotIn("trees", cfg)
        self.assertNotIn("sync_mode", cfg)
        self.assertNotIn("cron_hour", cfg)
        self.assertEqual([task["folder_path"] for task in cfg["tree_tasks"]], ["影视库/电影"])
        self.assertEqual(cfg["tree_tasks"][0]["tree_name"], "目录树-影视库-电影")

    def test_name_conflict_helper(self):
        cfg = {
            "tree_tasks": [
                _make_task("影视库/电视剧"),
                _make_task("影视库/电影"),
            ]
        }
        conflict = tree.find_tree_task_name_conflict(cfg, "目录树-影视库-电视剧", "其它/路径")
        self.assertEqual(conflict["folder_path"], "影视库/电视剧")
        self.assertIsNone(tree.find_tree_task_name_conflict(cfg, "目录树-影视库-电视剧", "影视库/电视剧"))


class TreeTaskEngineTest(unittest.TestCase):
    def setUp(self):
        self._orig_task_running = tree.task_status["running"]
        tree.task_status["running"] = False

    def tearDown(self):
        tree.task_status["running"] = False
        tree._set_tree_task_running(False)

    def _patch_engine(self, cfg, task, raw_bytes=None, remote_sha1="", fake_download=True, wait_error=None):
        replace_state = {"renamed": False}
        server_name = "server-name.txt"
        remote_name = tree._tree_file_remote_name(str(task.get("tree_name", "")))

        def fake_list_entries(_cookie, _cid, **_kwargs):
            return [
                {
                    "id": "f1",
                    "name": remote_name if replace_state["renamed"] else server_name,
                    "is_dir": False,
                }
            ]

        def fake_rename_entry(*_args, **_kwargs):
            replace_state["renamed"] = True

        def fake_get_info(_cookie, file_id):
            return {
                "id": file_id,
                "name": remote_name if replace_state["renamed"] else server_name,
                "sha1": remote_sha1,
                "pick_code": "pc1",
            }

        patches = [
            patch.object(tree, "get_config", return_value=cfg),
            patch.object(tree, "save_config", Mock()),
            patch.object(tree, "validate_tree_runtime_config", return_value=""),
            patch.object(tree, "resolve_115_folder_id_by_path", return_value="123"),
            patch.object(tree, "submit_115_export_dir", return_value="export-1"),
            (
                patch.object(tree, "wait_115_export_dir", side_effect=wait_error)
                if wait_error is not None
                else patch.object(
                    tree,
                    "wait_115_export_dir",
                    return_value={"file_id": "f1", "file_name": "server-name.txt", "pick_code": "pc1"},
                )
            ),
            patch.object(tree, "get_115_file_sha1_by_id", return_value=remote_sha1),
            patch.object(tree, "list_115_entries", side_effect=fake_list_entries),
            patch.object(tree, "delete_115_entries", Mock()),
            patch.object(tree, "rename_115_entry", side_effect=fake_rename_entry),
            patch.object(tree, "get_115_file_info", side_effect=fake_get_info),
            patch.object(tree, "TREE_EXPORT_REPLACE_SETTLE_SECONDS", 0.0),
            patch.object(tree, "TREE_EXPORT_FILE_READY_INTERVAL_SECONDS", 0.0),
            patch.object(tree, "write_log", AsyncMock()),
            patch.object(tree, "update_progress", AsyncMock()),
            patch.object(tree, "schedule_ui_state_push", Mock()),
            patch.object(tree, "release_process_memory", Mock()),
            patch.object(tree, "get_user_extensions", return_value={"mkv"}),
            patch.object(tree, "get_mount_prefix", return_value="/115"),
            patch.object(
                tree,
                "build_provider_remote_path",
                side_effect=lambda _cfg, _provider, path: f"/115/{path}",
            ),
            patch.object(tree, "build_strm_play_url", side_effect=lambda _cfg, remote_path: f"strm://{remote_path}"),
        ]
        if raw_bytes is not None:
            patches.append(patch.object(tree, "_download_exported_tree_bytes", return_value=raw_bytes))
        elif fake_download:
            patches.append(
                patch.object(
                    tree,
                    "_download_exported_tree_bytes",
                    side_effect=AssertionError("sha1 相同或未变化时不应下载"),
                )
            )
        return patches

    def _run_engine(self, cfg, task, extra_patches=(), full=False, **engine_kwargs):
        cfg.setdefault("tree_tasks", [task])
        with ExitStack() as stack:
            for p in extra_patches:
                stack.enter_context(p)
            for p in self._patch_engine(cfg, task, **engine_kwargs):
                stack.enter_context(p)
            return asyncio.run(tree.run_tree_task(task["id"], full=full))

    def test_sha1_same_skips_download_and_parse(self):
        cfg = {"cookie_115": "cookie", "sha1_skip": True, "sync_clean": True}
        task = _make_task(last_sha1="same-sha1")
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "data.db")
            tree_dir = os.path.join(tmpdir, "tree-cache")
            os.makedirs(tree_dir, exist_ok=True)
            original_db_path, original_db_ensured = db.DB_PATH, db._DB_ENSURED
            db.DB_PATH, db._DB_ENSURED = db_path, False
            try:
                db.ensure_db()
                result = self._run_engine(
                    cfg,
                    task,
                    extra_patches=(patch.object(tree, "TREE_DIR", tree_dir),),
                    remote_sha1="same-sha1",
                )
                self.assertEqual(result["status"], "skipped")
                self.assertFalse(result["changed"])
                conn = sqlite3.connect(db_path)
                try:
                    row = conn.execute("SELECT changed, status FROM tree_export_jobs").fetchone()
                finally:
                    conn.close()
                self.assertEqual(row, (0, "completed"))
            finally:
                db.DB_PATH, db._DB_ENSURED = original_db_path, original_db_ensured

    def test_sha1_changed_downloads_parses_writes_and_cleans_scoped(self):
        raw_tree = "|——影视库\n| |-电视剧\n| | |-New.Show.S01E01.mkv\n| | |-notes.txt\n".encode("utf-8")
        cfg = {"cookie_115": "cookie", "sha1_skip": True, "sync_clean": True}
        task = _make_task(last_sha1="old-sha1")
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "data.db")
            tree_dir = os.path.join(tmpdir, "tree-cache")
            strm_root = os.path.join(tmpdir, "strm")
            os.makedirs(tree_dir, exist_ok=True)
            os.makedirs(strm_root, exist_ok=True)

            stale_in_scope = strm_files.managed_strm_file_path("影视库/电视剧/Old.Show.S01E99.mkv", root=strm_root)
            stale_out_scope = strm_files.managed_strm_file_path("影视库/电影/Old.Movie.mkv", root=strm_root)
            for target in (stale_in_scope, stale_out_scope):
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "w", encoding="utf-8") as f:
                    f.write("stale")

            original_db_path, original_db_ensured = db.DB_PATH, db._DB_ENSURED
            original_strm_root = strm_files.STRM_ROOT
            db.DB_PATH, db._DB_ENSURED = db_path, False
            strm_files.STRM_ROOT = strm_root
            try:
                db.ensure_db()
                conn = sqlite3.connect(db_path)
                try:
                    conn.execute(
                        "INSERT INTO local_files (path_hash, relative_path, scan_token) VALUES (?, ?, ?)",
                        (tree.hashlib.md5("影视库/电视剧/Old.Show.S01E99.mkv".encode("utf-8")).hexdigest(), "影视库/电视剧/Old.Show.S01E99.mkv", "old-run"),
                    )
                    conn.execute(
                        "INSERT INTO local_files (path_hash, relative_path, scan_token) VALUES (?, ?, ?)",
                        (tree.hashlib.md5("影视库/电影/Old.Movie.mkv".encode("utf-8")).hexdigest(), "影视库/电影/Old.Movie.mkv", "old-run"),
                    )
                    conn.commit()
                finally:
                    conn.close()
                result = self._run_engine(
                    cfg,
                    task,
                    extra_patches=(
                        patch.object(tree, "TREE_DIR", tree_dir),
                        patch.object(strm_files, "STRM_ROOT", strm_root),
                    ),
                    raw_bytes=raw_tree,
                    remote_sha1="new-sha1",
                )
                self.assertEqual(result["status"], "completed")
                self.assertTrue(result["changed"])
                target = strm_files.managed_strm_file_path("影视库/电视剧/New.Show.S01E01.mkv", root=strm_root)
                self.assertTrue(os.path.exists(target))
                with open(target, "r", encoding="utf-8") as f:
                    self.assertTrue(f.read().startswith("strm:///115/影视库/电视剧/New.Show.S01E01.mkv"))
                self.assertFalse(os.path.exists(stale_in_scope))
                self.assertTrue(os.path.exists(stale_out_scope))
                cfg_task = tree._get_tree_task_by_id(cfg, task["id"])
                self.assertEqual(cfg_task["last_remote_sha1"], "new-sha1")
                self.assertFalse(tree.task_status["running"])
                self.assertEqual(tree.task_status["progress"].get("percent"), 0)
            finally:
                db.DB_PATH, db._DB_ENSURED = original_db_path, original_db_ensured
                strm_files.STRM_ROOT = original_strm_root

    def test_full_rewrite_replays_cache_when_sha1_same(self):
        raw_tree = "|——影视库\n| |-电视剧\n| | |-Show.S01E01.mkv\n".encode("utf-8")
        cfg = {"cookie_115": "cookie", "sha1_skip": True, "sync_clean": True}
        task = _make_task(last_sha1="same-sha1")
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "data.db")
            tree_dir = os.path.join(tmpdir, "tree-cache")
            strm_root = os.path.join(tmpdir, "strm")
            os.makedirs(tree_dir, exist_ok=True)
            os.makedirs(strm_root, exist_ok=True)

            original_db_path, original_db_ensured = db.DB_PATH, db._DB_ENSURED
            original_strm_root = strm_files.STRM_ROOT
            db.DB_PATH, db._DB_ENSURED = db_path, False
            strm_files.STRM_ROOT = strm_root
            try:
                db.ensure_db()
                with ExitStack() as stack:
                    stack.enter_context(patch.object(tree, "TREE_DIR", tree_dir))
                    stack.enter_context(patch.object(strm_files, "STRM_ROOT", strm_root))
                    _tree_key, cache_path, raw_path = tree._tree_task_cache_paths(task)
                    with open(raw_path, "wb") as f:
                        f.write(raw_tree)
                    with open(cache_path, "w", encoding="utf-8") as f:
                        f.write("影视库/电视剧/Show.S01E01.mkv\n")
                    for p in self._patch_engine(cfg, task, remote_sha1="same-sha1", fake_download=False):
                        stack.enter_context(p)
                    cfg.setdefault("tree_tasks", [task])
                    result = asyncio.run(tree.run_tree_task(task["id"], full=True))
                self.assertEqual(result["status"], "completed")
                target = strm_files.managed_strm_file_path("影视库/电视剧/Show.S01E01.mkv", root=strm_root)
                self.assertTrue(os.path.exists(target))
            finally:
                db.DB_PATH, db._DB_ENSURED = original_db_path, original_db_ensured
                strm_files.STRM_ROOT = original_strm_root

    def test_replace_removes_old_then_renames(self):
        calls = []
        state = {"old_present": True, "renamed": False}
        tree_name = "目录树-影视库-电视剧"
        remote_name = tree._tree_file_remote_name(tree_name)

        def fake_list(_cookie, _cid, **_kwargs):
            return [
                {"id": "old-1", "name": remote_name, "is_dir": False},
                {"id": "new-1", "name": "server-name.txt", "is_dir": False},
            ]

        def fake_rename(*_args, **_kwargs):
            state["renamed"] = True
            calls.append("rename")

        def fake_info(_cookie, file_id):
            return {"id": file_id, "name": remote_name if state["renamed"] else "server-name.txt"}

        with patch.object(tree, "TREE_EXPORT_REPLACE_SETTLE_SECONDS", 0.0), patch.object(
            tree, "list_115_entries", side_effect=fake_list
        ), patch.object(
            tree, "delete_115_entries", side_effect=lambda *a, **k: (state.update(old_present=False), calls.append("delete"))
        ), patch.object(tree, "rename_115_entry", side_effect=fake_rename), patch.object(
            tree, "get_115_file_info", side_effect=fake_info
        ):
            tree._replace_115_tree_file("cookie", "new-1", tree_name)
        self.assertEqual(calls, ["delete", "rename"])

    def test_replace_skips_delete_when_same_id(self):
        calls = []
        remote_name = tree._tree_file_remote_name("目录树-影视库-电视剧")
        with patch.object(tree, "TREE_EXPORT_REPLACE_SETTLE_SECONDS", 0.0), patch.object(
            tree, "get_115_file_info", return_value={"id": "f1", "name": remote_name}
        ), patch.object(
            tree, "list_115_entries", return_value=[{"id": "f1", "name": remote_name, "is_dir": False}]
        ), patch.object(tree, "delete_115_entries", side_effect=lambda *a, **k: calls.append("delete")), patch.object(
            tree, "rename_115_entry", side_effect=lambda *a, **k: calls.append("rename")
        ):
            tree._replace_115_tree_file("cookie", "f1", "目录树-影视库-电视剧")
        self.assertEqual(calls, [])

    def test_replace_retries_after_name_collision(self):
        calls = []
        state = {"old_present": True, "renamed": False}
        tree_name = "目录树-影视库-电视剧"
        remote_name = tree._tree_file_remote_name(tree_name)
        collision_name = tree_name + "(1).txt"

        def fake_list(_cookie, _cid, **_kwargs):
            return [
                {"id": "old-1", "name": remote_name, "is_dir": False},
                {"id": "new-1", "name": collision_name, "is_dir": False},
            ]

        def fake_rename(*_args, **_kwargs):
            state["renamed"] = True
            calls.append("rename")

        def fake_info(_cookie, file_id):
            return {"id": file_id, "name": remote_name if state["renamed"] else collision_name}

        with patch.object(tree, "TREE_EXPORT_REPLACE_SETTLE_SECONDS", 0.0), patch.object(
            tree, "list_115_entries", side_effect=fake_list
        ), patch.object(
            tree, "delete_115_entries", side_effect=lambda *a, **k: (state.update(old_present=False), calls.append("delete"))
        ), patch.object(tree, "rename_115_entry", side_effect=fake_rename), patch.object(
            tree, "get_115_file_info", side_effect=fake_info
        ):
            tree._replace_115_tree_file("cookie", "new-1", tree_name)
        self.assertEqual(calls, ["delete", "rename"])

    def test_tree_file_remote_name_appends_txt(self):
        self.assertEqual(tree._tree_file_remote_name("目录树-影视库"), "目录树-影视库.txt")
        self.assertEqual(tree._tree_file_remote_name("目录树-影视库.txt"), "目录树-影视库.txt")
        self.assertEqual(tree._tree_file_remote_name(""), "")

    def test_tree_flow_total_seconds(self):
        self.assertEqual(tree._tree_flow_total_seconds({"a": 1.2, "b": 0.8}), "2.00秒")
        self.assertEqual(tree._tree_flow_total_seconds({}), "0.00秒")

    def test_run_raises_when_busy(self):
        tree.task_status["running"] = True
        with self.assertRaisesRegex(RuntimeError, "已有目录树任务"):
            asyncio.run(tree.run_tree_task("missing"))

    def test_wait_timeout_fails_with_manual_rename_guide(self):
        cfg = {"cookie_115": "cookie", "sha1_skip": True, "sync_clean": True}
        task = _make_task(last_sha1="old-sha1")
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "data.db")
            original_db_path, original_db_ensured = db.DB_PATH, db._DB_ENSURED
            db.DB_PATH, db._DB_ENSURED = db_path, False
            try:
                db.ensure_db()
                timeout_error = RuntimeError(
                    "115 导出目录树超时（1800 秒，export_id=export-1），任务可能仍在服务端执行"
                )
                with self.assertRaisesRegex(RuntimeError, "手动到 115 网盘根目录"):
                    self._run_engine(cfg, task, wait_error=timeout_error)
                conn = sqlite3.connect(db_path)
                try:
                    row = conn.execute("SELECT export_id, status, error FROM tree_export_jobs").fetchone()
                finally:
                    conn.close()
                self.assertEqual(row[0], "export-1")
                self.assertEqual(row[1], "failed")
                self.assertIn("目录树-影视库-电视剧.txt", row[2])
                self.assertIn("下载并生成", row[2])
                self.assertIn("生成并同步", row[2])
            finally:
                db.DB_PATH, db._DB_ENSURED = original_db_path, original_db_ensured

    def test_sync_existing_force_fetch_downloads_even_when_sha1_same(self):
        cfg = {"cookie_115": "cookie", "sha1_skip": True, "sync_clean": True}
        task = _make_task(last_sha1="same-sha1")
        entry = {
            "id": "f1",
            "name": tree._tree_file_remote_name(task["tree_name"]),
            "sha1": "same-sha1",
            "pick_code": "pc1",
        }
        fetch_calls = {"count": 0}

        def fake_fetch(_cookie, _source_rel):
            fetch_calls["count"] += 1
            return "|——影视库\n".encode("utf-8")

        with patch.object(tree, "_resolve_115_file_entry_by_relative_path", return_value=entry), patch.object(
            tree, "_fetch_115_tree_file_bytes", side_effect=fake_fetch
        ), patch.object(
            tree,
            "_sync_task_tree_bytes",
            AsyncMock(return_value={"matched_count": 1, "parsed_count": 1, "generated_count": 1}),
        ), patch.object(tree, "_upsert_tree_task", Mock()), patch.object(tree, "write_log", AsyncMock()):
            asyncio.run(tree._sync_existing_tree_task(cfg, task, force_fetch=True))
        self.assertEqual(fetch_calls["count"], 1)

    def test_sync_existing_skips_when_sha1_same_without_force_fetch(self):
        cfg = {"cookie_115": "cookie", "sha1_skip": True, "sync_clean": True}
        task = _make_task(last_sha1="same-sha1")
        entry = {
            "id": "f1",
            "name": tree._tree_file_remote_name(task["tree_name"]),
            "sha1": "same-sha1",
            "pick_code": "pc1",
        }
        with patch.object(tree, "_resolve_115_file_entry_by_relative_path", return_value=entry), patch.object(
            tree, "_fetch_115_tree_file_bytes", side_effect=AssertionError("sha1 相同且未强制下载时不应下载")
        ), patch.object(
            tree, "_sync_task_tree_bytes", AsyncMock(side_effect=AssertionError("不应解析"))
        ), patch.object(tree, "_upsert_tree_task", Mock(side_effect=AssertionError("不应更新任务"))), patch.object(
            tree, "write_log", AsyncMock()
        ):
            asyncio.run(tree._sync_existing_tree_task(cfg, task, force_fetch=False))


class TreeStartupIntegrityTest(unittest.TestCase):
    def test_startup_has_no_dangling_tree_cron_scheduler(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "app/startup.py").read_text(encoding="utf-8")
        self.assertNotIn("create_task(scheduler())", source)
        self.assertNotIn("tree-cron-sync", source)


class _FakeRequest:
    def __init__(self, data):
        self._data = data

    async def json(self):
        return self._data


class TreeTaskRouteTest(unittest.TestCase):
    def test_create_ignores_manual_prefix_and_exclude(self):
        cfg = {"cookie_115": "ck", "tree_tasks": []}
        saved = {}
        request = _FakeRequest(
            {
                "folder_path": "影视库/电视剧",
                "tree_name": "自定义名",
                "prefix": "乱填前缀",
                "exclude": 9,
            }
        )
        with patch.object(tree_routes, "get_config", return_value=cfg), patch.object(
            tree_routes, "save_config", side_effect=lambda payload: saved.update(payload)
        ), patch.object(tree_routes, "resolve_115_folder_id_by_path", return_value="cid1"):
            asyncio.run(tree_routes.create_tree_task(request))
        task = saved["tree_tasks"][0]
        self.assertEqual(task["tree_name"], "自定义名")
        self.assertEqual(task["prefix"], "影视库")
        self.assertEqual(task["exclude"], 1)

    def test_update_rederives_prefix_and_exclude_from_folder(self):
        cfg = {
            "cookie_115": "ck",
            "tree_tasks": [
                {
                    "id": "t1",
                    "folder_path": "影视库/电影",
                    "tree_name": "旧名",
                    "prefix": "旧前缀",
                    "exclude": 3,
                    "last_remote_sha1": "",
                    "last_local_md5": "",
                }
            ],
        }
        saved = {}
        request = _FakeRequest(
            {
                "folder_path": "影视库/电视剧",
                "tree_name": "新名",
                "prefix": "乱填前缀",
                "exclude": 9,
            }
        )
        with patch.object(tree_routes, "get_config", return_value=cfg), patch.object(
            tree_routes, "save_config", side_effect=lambda payload: saved.update(payload)
        ), patch.object(tree_routes, "resolve_115_folder_id_by_path", return_value="cid2"):
            asyncio.run(tree_routes.update_tree_task("t1", request))
        task = saved["tree_tasks"][0]
        self.assertEqual(task["tree_name"], "新名")
        self.assertEqual(task["prefix"], "影视库")
        self.assertEqual(task["exclude"], 1)


class LegacyTreeConfigCleanupTest(unittest.TestCase):
    def test_cleanup_rewrites_when_legacy_keys_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "settings.json")
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "cookie_115": "ck",
                        "trees": [{"path": "x.txt", "prefix": "P", "exclude": 1}],
                        "sync_mode": "full",
                        "check_hash": True,
                        "cron_hour": 30,
                        "last_hash": "{}",
                    },
                    f,
                )
            saved = {}
            with patch.object(
                core_module, "CONFIG_PATH", config_path
            ), patch.object(
                core_module,
                "get_config",
                return_value={"cookie_115": "ck", "sha1_skip": True, "sync_clean": True},
            ), patch.object(
                core_module, "save_config", side_effect=lambda payload: saved.update(payload)
            ):
                changed = core_module.cleanup_legacy_tree_config_file()
            self.assertTrue(changed)
            for key in ("trees", "sync_mode", "check_hash", "cron_hour", "last_hash"):
                self.assertNotIn(key, saved)

    def test_cleanup_skips_when_no_legacy_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "settings.json")
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({"cookie_115": "ck", "tree_tasks": []}, f)
            with patch.object(core_module, "CONFIG_PATH", config_path), patch.object(
                core_module, "save_config", side_effect=AssertionError("不应重写配置")
            ):
                changed = core_module.cleanup_legacy_tree_config_file()
            self.assertFalse(changed)


if __name__ == "__main__":
    unittest.main()
