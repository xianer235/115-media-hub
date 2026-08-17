import os
import sqlite3
import tempfile
import unittest

from app.services import tree


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


if __name__ == "__main__":
    unittest.main()
