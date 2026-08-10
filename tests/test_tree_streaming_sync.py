import asyncio
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from app import db
from app.services import strm_files, tree


class TreeStreamingSyncTest(unittest.TestCase):
    def test_mark_local_files_seen_batch_dedupes_same_scan_token(self):
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute(
                """
                CREATE TABLE local_files (
                    path_hash TEXT PRIMARY KEY,
                    relative_path TEXT,
                    scan_token TEXT NOT NULL DEFAULT ''
                )
                """
            )
            cursor = conn.cursor()

            fresh, duplicates = tree._mark_local_files_seen_batch(
                cursor,
                ["Show/S01E01.mkv", "Show/S01E01.mkv", "Show/S01E02.mkv"],
                "run-1",
            )
            self.assertEqual(fresh, ["Show/S01E01.mkv", "Show/S01E02.mkv"])
            self.assertEqual(duplicates, 1)

            fresh, duplicates = tree._mark_local_files_seen_batch(
                cursor,
                ["Show/S01E01.mkv", "Show/S01E02.mkv"],
                "run-1",
            )
            self.assertEqual(fresh, [])
            self.assertEqual(duplicates, 2)

            fresh, duplicates = tree._mark_local_files_seen_batch(
                cursor,
                ["Show/S01E01.mkv"],
                "run-2",
            )
            self.assertEqual(fresh, ["Show/S01E01.mkv"])
            self.assertEqual(duplicates, 0)
        finally:
            conn.close()

    def test_mark_local_files_seen_batch_dedupes_across_select_chunks(self):
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute(
                """
                CREATE TABLE local_files (
                    path_hash TEXT PRIMARY KEY,
                    relative_path TEXT,
                    scan_token TEXT NOT NULL DEFAULT ''
                )
                """
            )
            cursor = conn.cursor()
            paths = [f"Show/Episode-{idx:04d}.mkv" for idx in range(tree.TREE_SYNC_SQLITE_SELECT_CHUNK_SIZE + 5)]

            fresh, duplicates = tree._mark_local_files_seen_batch(cursor, paths, "run-1")
            self.assertEqual(fresh, paths)
            self.assertEqual(duplicates, 0)

            fresh, duplicates = tree._mark_local_files_seen_batch(cursor, paths, "run-1")
            self.assertEqual(fresh, [])
            self.assertEqual(duplicates, len(paths))
        finally:
            conn.close()

    def test_stream_tree_matches_to_cache_and_replay(self):
        raw_bytes = "\n".join(
            [
                "资源库",
                "| 电视剧",
                "| | Test.Show.S01E01.mkv",
                "| | Test.Show.S01E02.mkv",
                "| | README.txt",
            ]
        ).encode("utf-8")
        matched_paths = []

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, "tree-cache.txt")
            matched_count, lines_total, nodes_total = tree._stream_tree_matches_to_cache(
                cache_path,
                raw_bytes,
                {"mkv"},
                "TV",
                1,
                matched_paths.append,
            )

            replayed_paths = []
            replayed_count = tree._replay_tree_cache(cache_path, replayed_paths.append)

        self.assertEqual(matched_count, 2)
        self.assertEqual(lines_total, 5)
        self.assertEqual(nodes_total, 5)
        self.assertEqual(matched_paths, ["TV/电视剧/Test.Show.S01E01.mkv", "TV/电视剧/Test.Show.S01E02.mkv"])
        self.assertEqual(replayed_count, 2)
        self.assertEqual(replayed_paths, matched_paths)

    def test_run_sync_hash_hit_finishes_before_database_or_cache_replay(self):
        raw_tree = b"Library\n| Show\n| | Show.S01E01.mkv\n"
        cfg = {
            "trees": [
                {"path": "/media/one.txt", "prefix": "Library", "exclude": 1},
                {"path": "/media/two.txt", "prefix": "Archive", "exclude": 1},
            ],
            "cookie_115": "fake-cookie",
            "sync_mode": "incremental",
            "sync_clean": True,
            "check_hash": True,
        }
        tree_keys = [tree.build_tree_cache_key(item) for item in cfg["trees"]]
        signature = tree.build_tree_parse_signature(tree.hashlib.md5(raw_tree).hexdigest(), {"mkv"})
        cfg["last_hash"] = tree.json.dumps(
            {"version": 2, "tree_keys": tree_keys, "trees": {key: {"parse_signature": signature} for key in tree_keys}},
            ensure_ascii=False,
            sort_keys=True,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tree_dir = os.path.join(tmpdir, "tree-cache")
            os.makedirs(tree_dir, exist_ok=True)
            for item, key in zip(cfg["trees"], tree_keys):
                with open(os.path.join(tree_dir, f"raw_{key}.txt"), "wb") as f:
                    f.write(raw_tree)
                with open(os.path.join(tree_dir, f"cache_{key}.txt"), "w", encoding="utf-8") as f:
                    f.write("Library/Show/Show.S01E01.mkv\n")

            with patch.object(tree, "TREE_DIR", tree_dir), patch.object(tree, "get_config", return_value=cfg), patch.object(
                tree, "save_config", Mock()
            ), patch.object(tree, "validate_tree_runtime_config", return_value=""), patch.object(
                tree, "get_user_extensions", return_value={"mkv"}
            ), patch.object(tree, "get_mount_prefix", return_value="/115"), patch.object(
                tree, "_fetch_115_tree_file_bytes", return_value=raw_tree
            ), patch.object(tree, "ensure_db", side_effect=AssertionError("hash hit must not initialize database")), patch.object(
                tree, "open_db", side_effect=AssertionError("hash hit must not open database")
            ), patch.object(tree, "_replay_tree_cache", side_effect=AssertionError("hash hit must not replay cache")), patch.object(
                tree, "_stream_tree_matches_to_cache", side_effect=AssertionError("hash hit must not parse tree")
            ), patch.object(tree, "write_log", AsyncMock()), patch.object(
                tree, "update_progress", AsyncMock()
            ), patch.object(tree, "schedule_ui_state_push", Mock()), patch.object(
                tree, "release_process_memory", Mock()
            ):
                asyncio.run(tree.run_sync())

    def test_run_sync_hashes_all_sources_before_processing_mixed_changes(self):
        unchanged_raw = b"Library\n| Show\n| | Show.S01E01.mkv\n"
        changed_raw = b"Library\n| Show\n| | Show.S01E02.mkv\n"
        cfg = {
            "trees": [
                {"path": "/media/one.txt", "prefix": "Library", "exclude": 1},
                {"path": "/media/two.txt", "prefix": "Archive", "exclude": 1},
            ],
            "cookie_115": "fake-cookie",
            "sync_mode": "incremental",
            "sync_clean": True,
            "check_hash": True,
        }
        tree_keys = [tree.build_tree_cache_key(item) for item in cfg["trees"]]
        unchanged_signature = tree.build_tree_parse_signature(tree.hashlib.md5(unchanged_raw).hexdigest(), {"mkv"})
        changed_signature = tree.build_tree_parse_signature(tree.hashlib.md5(b"old").hexdigest(), {"mkv"})
        cfg["last_hash"] = tree.json.dumps(
            {
                "version": 2,
                "tree_keys": tree_keys,
                "trees": {
                    tree_keys[0]: {"parse_signature": unchanged_signature},
                    tree_keys[1]: {"parse_signature": changed_signature},
                },
            },
            ensure_ascii=False,
            sort_keys=True,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "data.db")
            tree_dir = os.path.join(tmpdir, "tree-cache")
            strm_root = os.path.join(tmpdir, "strm")
            events = []
            raw_by_source = {"media/one.txt": unchanged_raw, "media/two.txt": changed_raw}
            replay_tree_cache = tree._replay_tree_cache
            stream_tree_matches_to_cache = tree._stream_tree_matches_to_cache

            def fetch_tree_source(_cookie, source_rel):
                events.append(f"fetch:{source_rel}")
                return raw_by_source[source_rel]

            def replay_cached_source(*args, **kwargs):
                events.append("replay")
                return replay_tree_cache(*args, **kwargs)

            def parse_changed_source(*args, **kwargs):
                events.append("parse")
                return stream_tree_matches_to_cache(*args, **kwargs)

            os.makedirs(tree_dir, exist_ok=True)
            with open(os.path.join(tree_dir, f"cache_{tree_keys[0]}.txt"), "w", encoding="utf-8") as f:
                f.write("Library/Show/Show.S01E01.mkv\n")
            with patch.object(db, "DB_PATH", db_path), patch.object(tree, "DB_PATH", db_path), patch.object(tree, "TREE_DIR", tree_dir), patch.object(
                strm_files, "STRM_ROOT", strm_root
            ), patch.object(tree, "get_config", return_value=cfg), patch.object(tree, "save_config", Mock()), patch.object(
                tree, "validate_tree_runtime_config", return_value=""
            ), patch.object(tree, "get_user_extensions", return_value={"mkv"}), patch.object(
                tree, "get_mount_prefix", return_value="/115"
            ), patch.object(tree, "build_provider_remote_path", side_effect=lambda _cfg, _provider, path: f"/115/{path}"), patch.object(
                tree, "build_strm_play_url", side_effect=lambda _cfg, remote_path: f"strm://{remote_path}"
            ), patch.object(
                tree, "_fetch_115_tree_file_bytes", side_effect=fetch_tree_source
            ), patch.object(
                tree, "_replay_tree_cache", side_effect=replay_cached_source
            ), patch.object(
                tree, "_stream_tree_matches_to_cache", side_effect=parse_changed_source
            ), patch.object(tree, "write_log", AsyncMock()), patch.object(tree, "update_progress", AsyncMock()), patch.object(
                tree, "schedule_ui_state_push", Mock()
            ), patch.object(tree, "release_process_memory", Mock()):
                original_db_ensured = db._DB_ENSURED
                db._DB_ENSURED = False
                try:
                    asyncio.run(tree.run_sync())
                finally:
                    db._DB_ENSURED = original_db_ensured

            with open(os.path.join(tree_dir, f"cache_{tree_keys[1]}.txt"), "r", encoding="utf-8") as f:
                changed_cache = f.read()
            self.assertEqual(changed_cache, "Archive/Show/Show.S01E02.mkv\n")
            self.assertEqual(events, ["fetch:media/one.txt", "fetch:media/two.txt", "replay", "parse"])
            self.assertTrue(os.path.exists(strm_files.managed_strm_file_path("Library/Show/Show.S01E01.mkv", root=strm_root)))
            self.assertTrue(os.path.exists(strm_files.managed_strm_file_path("Archive/Show/Show.S01E02.mkv", root=strm_root)))

    def test_run_sync_replaces_scan_state_and_cleans_stale_strm(self):
        raw_tree = "\n".join(
            [
                "资源库",
                "| 剧集",
                "| | New.Show.S01E01.mkv",
                "| | New.Show.S01E02.mkv",
                "| | notes.txt",
            ]
        ).encode("utf-8")

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "data.db")
            tree_dir = os.path.join(tmpdir, "tree-cache")
            strm_root = os.path.join(tmpdir, "strm")
            os.makedirs(strm_root, exist_ok=True)

            stale_rel_path = "Old/Old.Show.S01E01.mkv"
            stale_target = strm_files.managed_strm_file_path(stale_rel_path, root=strm_root)
            os.makedirs(os.path.dirname(stale_target), exist_ok=True)
            with open(stale_target, "w", encoding="utf-8") as f:
                f.write("stale")

            cfg = {
                "trees": [{"path": "/media/tree.txt", "prefix": "Library", "exclude": 1}],
                "cookie_115": "fake-cookie",
                "sync_mode": "incremental",
                "sync_clean": True,
                "check_hash": False,
            }

            original_db_path = db.DB_PATH
            original_db_ensured = db._DB_ENSURED
            db.DB_PATH = db_path
            db._DB_ENSURED = False
            try:
                db.ensure_db()
                conn = sqlite3.connect(db_path)
                try:
                    conn.execute(
                        "INSERT INTO local_files (path_hash, relative_path, scan_token) VALUES (?, ?, ?)",
                        (
                            tree.hashlib.md5(stale_rel_path.encode("utf-8")).hexdigest(),
                            stale_rel_path,
                            "old-run",
                        ),
                    )
                    conn.commit()
                finally:
                    conn.close()

                with patch.object(tree, "DB_PATH", db_path), patch.object(tree, "TREE_DIR", tree_dir), patch.object(
                    strm_files, "STRM_ROOT", strm_root
                ), patch.object(tree, "get_config", return_value=cfg), patch.object(
                    tree, "save_config", Mock()
                ), patch.object(
                    tree, "validate_tree_runtime_config", return_value=""
                ), patch.object(
                    tree, "get_user_extensions", return_value={"mkv"}
                ), patch.object(
                    tree, "get_mount_prefix", return_value="/115"
                ), patch.object(
                    tree,
                    "build_provider_remote_path",
                    side_effect=lambda _cfg, _provider, rel_path: f"/115/{rel_path}",
                ), patch.object(
                    tree, "build_strm_play_url", side_effect=lambda _cfg, remote_path: f"strm://{remote_path}"
                ), patch.object(
                    tree, "_fetch_115_tree_file_bytes", return_value=raw_tree
                ), patch.object(
                    tree, "write_log", AsyncMock()
                ), patch.object(
                    tree, "update_progress", AsyncMock()
                ), patch.object(
                    tree, "schedule_ui_state_push", Mock()
                ), patch.object(
                    tree, "release_process_memory", Mock()
                ):
                    asyncio.run(tree.run_sync())

                new_targets = [
                    strm_files.managed_strm_file_path("Library/剧集/New.Show.S01E01.mkv", root=strm_root),
                    strm_files.managed_strm_file_path("Library/剧集/New.Show.S01E02.mkv", root=strm_root),
                ]
                for target in new_targets:
                    self.assertTrue(os.path.exists(target))
                    with open(target, "r", encoding="utf-8") as f:
                        self.assertTrue(f.read().startswith("strm:///115/Library/剧集/New.Show"))

                self.assertFalse(os.path.exists(stale_target))

                conn = sqlite3.connect(db_path)
                try:
                    rows = conn.execute(
                        "SELECT relative_path, scan_token FROM local_files ORDER BY relative_path"
                    ).fetchall()
                finally:
                    conn.close()

                self.assertEqual(
                    [row[0] for row in rows],
                    [
                        "Library/剧集/New.Show.S01E01.mkv",
                        "Library/剧集/New.Show.S01E02.mkv",
                    ],
                )
                self.assertEqual(len({row[1] for row in rows}), 1)
            finally:
                db.DB_PATH = original_db_path
                db._DB_ENSURED = original_db_ensured


if __name__ == "__main__":
    unittest.main()
