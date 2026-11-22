"""媒体库查重（duplicate_scan）单元测试。

重点守三件事：
1. 季集解析只认明确标记，认不出来归电影，不把剧情标题当集号；
2. 档位判定：SHA1 相同才是「同一份文件」，否则一律按同集不同版本（人工确认）；
3. 删除前校验：每组至少留一份、只删视频、不认前端伪造的 id。
"""

import unittest
from unittest import mock

from app.services import duplicate_scan as dup


class FakeProvider:
    """按 cid → 条目列表的假网盘，只实现 list_entries。"""

    def __init__(self, tree):
        self.tree = tree
        self.calls = []

    def list_entries(self, cookie, cid="0"):
        self.calls.append(str(cid))
        return [dict(item) for item in self.tree.get(str(cid), [])]


def _folder(name, cid):
    return {"id": str(cid), "name": name, "is_dir": True, "size": 0}


def _file(name, fid, sha1="", size=1000, modified_at="1700000000"):
    return {
        "id": str(fid),
        "name": name,
        "is_dir": False,
        "size": size,
        "sha1": sha1,
        "modified_at": modified_at,
    }


def _build_groups_of(items, root_path=""):
    """分类 + 分组的组合调用，测试里少写一层。"""
    return dup._build_groups(dup._classify_files([dict(item) for item in items]), root_path)


class ClassifyMediaFileTest(unittest.TestCase):
    def test_sxxexx_in_season_dir(self):
        identity = dup._classify_media_file("某剧 (2024)/Season 01", "某剧 (2024) - S01E03.mkv")
        self.assertEqual(identity["kind"], "tv")
        self.assertEqual(identity["series_dir"], "某剧 (2024)")
        self.assertEqual(identity["season"], 1)
        self.assertEqual(identity["episode"], 3)

    def test_flat_episode_uses_series_dir(self):
        identity = dup._classify_media_file("某剧 (2024)", "某剧 - S01E05.mkv")
        self.assertEqual(identity["kind"], "tv")
        self.assertEqual(identity["series_dir"], "某剧 (2024)")
        self.assertEqual(identity["season"], 1)
        self.assertEqual(identity["episode"], 5)

    def test_cn_episode_with_cn_season_dir(self):
        identity = dup._classify_media_file("某剧/第二季", "某剧 第8集.mkv")
        self.assertEqual(identity["kind"], "tv")
        self.assertEqual(identity["series_dir"], "某剧")
        self.assertEqual(identity["season"], 2)
        self.assertEqual(identity["episode"], 8)

    def test_ep_marker(self):
        identity = dup._classify_media_file("某剧/Season 03", "某剧.EP12.1080p.mkv")
        self.assertEqual(identity["season"], 3)
        self.assertEqual(identity["episode"], 12)

    def test_numeric_filename(self):
        self.assertEqual(
            dup._classify_media_file("某剧/Season 01", "03.mkv")["episode"], 3
        )
        self.assertEqual(
            dup._classify_media_file("某剧/Season 01", "第07话.mkv")["episode"], 7
        )

    def test_year_is_not_episode(self):
        identity = dup._classify_media_file("电影 (2023)", "电影.2023.mkv")
        self.assertEqual(identity["kind"], "movie")
        self.assertEqual(identity["episode"], 0)

    def test_movie_release_name_stays_movie(self):
        identity = dup._classify_media_file("电影 (2023)", "电影 (2023).2160p.WEB-DL.mkv")
        self.assertEqual(identity["kind"], "movie")
        self.assertEqual(identity["series_dir"], "电影 (2023)")

    def test_flat_and_season_dir_share_group_key(self):
        flat = dup._classify_media_file("某剧 (2024)", "某剧 - S01E01.mkv")
        nested = dup._classify_media_file("某剧 (2024)/Season 01", "某剧 - S01E01.mkv")
        self.assertEqual(flat["series_dir"], nested["series_dir"])
        self.assertEqual(flat["season"], nested["season"])
        self.assertEqual(flat["episode"], nested["episode"])

    def test_non_video_extension_filtered(self):
        self.assertFalse(dup.is_media_file("某剧.srt"))
        self.assertFalse(dup.is_media_file("某剧.nfo"))
        self.assertTrue(dup.is_media_file("某剧.mkv"))
        self.assertTrue(dup.is_media_file("某剧.MP4"))


class BuildGroupsTest(unittest.TestCase):
    def _files(self, items):
        return [dict(item) for item in items]

    def test_exact_tier_when_sha1_equal(self):
        files = self._files(
            [
                {"id": "1", "name": "某剧 - S01E01.mkv", "rel_dir": "某剧/Season 01", "path": "某剧/Season 01/某剧 - S01E01.mkv", "size": 900, "sha1": "AAA", "modified_at": "1"},
                {"id": "2", "name": "某剧 - S01E01 副本.mkv", "rel_dir": "某剧/Season 01", "path": "某剧/Season 01/某剧 - S01E01 副本.mkv", "size": 900, "sha1": "AAA", "modified_at": "1"},
            ]
        )
        groups = _build_groups_of(files)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["tier"], "exact")
        self.assertEqual(groups[0]["reclaimable_bytes"], 900)
        keeps = [item for item in groups[0]["files"] if item.get("recommended_keep")]
        self.assertEqual(len(keeps), 1)

    def test_episode_tier_when_sha1_differs(self):
        files = self._files(
            [
                {"id": "1", "name": "某剧 - S01E01.1080p.mkv", "rel_dir": "某剧/Season 01", "path": "某剧/Season 01/a.mkv", "size": 900, "sha1": "AAA", "modified_at": "1"},
                {"id": "2", "name": "某剧 - S01E01.2160p.mkv", "rel_dir": "某剧/Season 01", "path": "某剧/Season 01/b.mkv", "size": 4000, "sha1": "BBB", "modified_at": "1"},
            ]
        )
        groups = _build_groups_of(files)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["tier"], "episode")
        # 同集不同版本不算「可释放」——删哪份没定，不能算成省下的空间。
        self.assertEqual(groups[0]["reclaimable_bytes"], 0)
        keep = [item for item in groups[0]["files"] if item.get("recommended_keep")][0]
        self.assertEqual(keep["id"], "2")
        self.assertEqual(keep["resolution"], "2160p")

    def test_flat_and_nested_merge_into_one_group(self):
        files = self._files(
            [
                {"id": "1", "name": "某剧 - S01E01.mkv", "rel_dir": "某剧", "path": "某剧/a.mkv", "size": 900, "sha1": "AAA", "modified_at": "1"},
                {"id": "2", "name": "某剧 - S01E01.mkv", "rel_dir": "某剧/Season 01", "path": "某剧/Season 01/a.mkv", "size": 900, "sha1": "AAA", "modified_at": "1"},
            ]
        )
        groups = _build_groups_of(files)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["tier"], "exact")

    def test_different_episodes_never_grouped(self):
        files = self._files(
            [
                {"id": "1", "name": "某剧 - S01E01.mkv", "rel_dir": "某剧", "path": "某剧/a.mkv", "size": 900, "sha1": "AAA", "modified_at": "1"},
                {"id": "2", "name": "某剧 - S01E02.mkv", "rel_dir": "某剧", "path": "某剧/b.mkv", "size": 900, "sha1": "AAA", "modified_at": "1"},
            ]
        )
        self.assertEqual(_build_groups_of(files), [])

    def test_single_file_is_not_a_group(self):
        files = self._files(
            [{"id": "1", "name": "某剧 - S01E01.mkv", "rel_dir": "某剧", "path": "某剧/a.mkv", "size": 900, "sha1": "AAA", "modified_at": "1"}]
        )
        self.assertEqual(_build_groups_of(files), [])


class SeriesHintsTest(unittest.TestCase):
    def test_same_series_in_two_named_dirs(self):
        files = [
            {"id": "1", "name": "某剧 - S01E01.mkv", "rel_dir": "某剧 (2024)/Season 01", "path": "a", "size": 1, "sha1": "A1", "modified_at": ""},
            {"id": "2", "name": "某剧 - S01E02.mkv", "rel_dir": "某剧 (2024)/Season 01", "path": "b", "size": 1, "sha1": "A2", "modified_at": ""},
            {"id": "3", "name": "某剧 - S01E01.mkv", "rel_dir": "某剧.2024.1080p.WEB-DL/Season 01", "path": "c", "size": 1, "sha1": "B1", "modified_at": ""},
        ]
        classified = dup._classify_files([dict(item) for item in files])
        hints = dup._build_series_hints(classified)
        self.assertEqual(len(hints), 1)
        self.assertEqual(hints[0]["year"], "2024")
        self.assertEqual(hints[0]["shared_episodes"], 1)
        # 整部剧各存一份时每集都不成组，提示仍然要出——这条就是防这个回归的。
        self.assertEqual(_build_groups_of(files), [])


class ScanEndToEndTest(unittest.TestCase):
    def _run_scan(self, tree, cid="0", options=None):
        provider = FakeProvider(tree)
        with mock.patch.object(dup, "_require_provider_cookie", return_value="cookie"), \
             mock.patch.object(dup, "_provider_or_none", return_value=provider), \
             mock.patch.object(dup, "resolve_scraper_folder_path", return_value={"path": "媒体库/电视剧"}):
            return dup.scan_duplicate_media("115", cid, options or {})

    def test_scan_reports_groups_and_summary(self):
        tree = {
            "0": [_folder("某剧 (2024)", "100")],
            "100": [_folder("Season 01", "101")],
            "101": [
                _file("某剧 - S01E01.mkv", "f1", sha1="AAA", size=900),
                _file("某剧 - S01E01 1080p.mkv", "f2", sha1="AAA", size=900),
                _file("某剧 - S01E02.mkv", "f3", sha1="CCC", size=800),
                _file("某剧 - S01E02 2160p.mkv", "f4", sha1="DDD", size=3000),
                _file("某剧.srt", "f5", sha1="EEE"),
            ],
        }
        result = self._run_scan(tree)
        self.assertTrue(result["ok"])
        self.assertEqual(result["root_path"], "媒体库/电视剧")
        self.assertEqual(result["summary"]["group_count"], 2)
        self.assertEqual(result["summary"]["exact_groups"], 1)
        self.assertEqual(result["summary"]["episode_groups"], 1)
        self.assertEqual(result["summary"]["duplicate_files"], 4)
        self.assertEqual(result["summary"]["reclaimable_bytes"], 900)
        # 字幕不参与查重。
        self.assertEqual(result["scanned"]["media_files"], 4)
        # 绝对路径带上了扫描根。
        first = result["groups"][0]["files"][0]
        self.assertTrue(first["path"].startswith("媒体库/电视剧/"))

    def test_scan_truncates_by_entry_limit(self):
        tree = {
            "0": [_folder("某剧", "100")],
            "100": [_file(f"某剧 - S01E{i:02d}.mkv", f"f{i}") for i in range(1, 30)],
        }
        result = self._run_scan(tree, options={"max_entries": 5})
        self.assertTrue(result["scanned"]["truncated"])

    def test_scan_skips_failed_dirs(self):
        class BrokenProvider(FakeProvider):
            def list_entries(self, cookie, cid="0"):
                if str(cid) == "100":
                    raise RuntimeError("boom")
                return super().list_entries(cookie, cid)

        provider = BrokenProvider({"0": [_folder("某剧", "100")]})
        with mock.patch.object(dup, "_require_provider_cookie", return_value="cookie"), \
             mock.patch.object(dup, "_provider_or_none", return_value=provider), \
             mock.patch.object(dup, "resolve_scraper_folder_path", return_value={"path": ""}):
            result = dup.scan_duplicate_media("115", "0", {})
        self.assertEqual(result["scanned"]["failed_dirs"], 1)
        self.assertEqual(result["groups"], [])


class PlanDeletionTest(unittest.TestCase):
    def _groups(self):
        files = [
            {"id": "1", "name": "a.mkv", "rel_dir": "某剧/Season 01", "path": "某剧/Season 01/a.mkv", "size": 900, "sha1": "AAA", "modified_at": "1", "parent_id": "101"},
            {"id": "2", "name": "b.mkv", "rel_dir": "某剧/Season 01", "path": "某剧/Season 01/b.mkv", "size": 900, "sha1": "AAA", "modified_at": "1", "parent_id": "101"},
        ]
        return _build_groups_of(files)

    def test_plan_accepts_partial_delete(self):
        groups = self._groups()
        plan = dup.plan_duplicate_deletion("115", groups, ["1"])
        self.assertTrue(plan["ok"])
        self.assertEqual(plan["file_count"], 1)
        self.assertEqual(plan["items"][0]["parent_id"], "101")

    def test_plan_rejects_emptying_group(self):
        groups = self._groups()
        with self.assertRaises(RuntimeError):
            dup.plan_duplicate_deletion("115", groups, ["1", "2"])

    def test_plan_rejects_unknown_id(self):
        groups = self._groups()
        with self.assertRaises(RuntimeError):
            dup.plan_duplicate_deletion("115", groups, ["999"])

    def test_plan_rejects_non_media(self):
        groups = self._groups()
        groups[0]["files"].append(
            {"id": "9", "name": "某剧.srt", "path": "某剧/Season 01/某剧.srt", "size": 1, "parent_id": "101"}
        )
        with self.assertRaises(RuntimeError):
            dup.plan_duplicate_deletion("115", groups, ["9"])

    def test_plan_rejects_empty_selection(self):
        with self.assertRaises(RuntimeError):
            dup.plan_duplicate_deletion("115", self._groups(), [])

    def test_plan_rejects_too_many_files(self):
        groups = [
            {
                "group_id": "g1",
                "label": "某剧",
                "files": [
                    {"id": str(index), "name": f"{index}.mkv", "path": f"{index}.mkv", "size": 1, "parent_id": "1"}
                    for index in range(dup.MAX_DELETE_FILES + 1)
                ],
            }
        ]
        with self.assertRaises(RuntimeError):
            dup.plan_duplicate_deletion("115", groups, [str(index) for index in range(dup.MAX_DELETE_FILES + 1)])


class DeleteFilesTest(unittest.TestCase):
    def test_delete_splits_by_parent_and_reports(self):
        items = [
            {"id": "1", "name": "a.mkv", "path": "p/a.mkv", "parent_id": "101", "size": 10},
            {"id": "2", "name": "b.mkv", "path": "p/b.mkv", "parent_id": "101", "size": 20},
            {"id": "3", "name": "c.mkv", "path": "q/c.mkv", "parent_id": "202", "size": 30},
        ]
        calls = []

        def fake_delete(provider, entry_ids, parent_id="", entries=None, request_id=""):
            calls.append({"ids": list(entry_ids), "parent_id": parent_id, "request_id": request_id})
            return {"ok": True}

        with mock.patch.object(dup, "delete_scraper_entries", side_effect=fake_delete):
            result = dup.delete_duplicate_files("115", items, request_id="rid")

        self.assertEqual(result["deleted_count"], 3)
        self.assertEqual(result["deleted_size"], 60)
        self.assertEqual(len(calls), 2)
        self.assertEqual({call["parent_id"] for call in calls}, {"101", "202"})
        self.assertTrue(all(call["request_id"].startswith("rid:") for call in calls))

    def test_delete_collects_failures_without_aborting(self):
        items = [
            {"id": "1", "name": "a.mkv", "path": "p/a.mkv", "parent_id": "101", "size": 10},
            {"id": "2", "name": "b.mkv", "path": "q/b.mkv", "parent_id": "202", "size": 20},
        ]

        def fake_delete(provider, entry_ids, parent_id="", entries=None, request_id=""):
            if parent_id == "101":
                raise RuntimeError("删除失败")
            return {"ok": True}

        with mock.patch.object(dup, "delete_scraper_entries", side_effect=fake_delete):
            result = dup.delete_duplicate_files("115", items, request_id="rid")
        self.assertEqual(result["deleted_count"], 1)
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(result["failed"][0]["name"], "a.mkv")

    def test_delete_rejects_empty(self):
        with self.assertRaises(RuntimeError):
            dup.delete_duplicate_files("115", [])


if __name__ == "__main__":
    unittest.main()
