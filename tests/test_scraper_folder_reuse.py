"""同名媒体文件夹复用：``[tmdbid-xxx]`` 与 115 自动追加的 ``(n)`` 后缀都算同一个文件夹。

背景：115 在创建/搬入重名文件夹时会自动改名成 ``片名 (2026)(1)``，旧版本写 TMDB ID 时
会在名字后追加 ``[tmdbid-123]``。如果查找现有文件夹时按"字面完全相同"比较，每次整理都会
再建一个文件夹，一个剧集目录最后会散成 片名/片名(1)/片名(2)/片名(3)。
"""

import unittest
from unittest import mock

from app.services import scraper as scraper_service


def _folder(entry_id, name):
    return {"id": entry_id, "cid": entry_id, "name": name, "is_dir": True}


class ScraperFolderNameKeyTest(unittest.TestCase):
    def test_key_ignores_tmdb_and_auto_index_suffix(self):
        key = scraper_service.scraper_folder_name_key
        self.assertEqual(key("王子与乞丐 (2026)"), key("王子与乞丐 (2026) [tmdbid-328704]"))
        self.assertEqual(key("王子与乞丐 (2026)"), key("王子与乞丐 (2026)(1)"))
        self.assertEqual(key("王子与乞丐 (2026)"), key(" 王子与乞丐  (2026) "))

    def test_key_keeps_real_differences(self):
        key = scraper_service.scraper_folder_name_key
        self.assertNotEqual(key("王子与乞丐 (2026)"), key("王子与乞丐 (2025)"))
        self.assertNotEqual(key("王子与乞丐 (2026)"), key("王子与乞丐 (2026) 第2季"))

    def test_match_prefers_exact_then_cleanest_name(self):
        match = scraper_service._match_scraper_folder_part
        entries = [
            _folder("c2", "王子与乞丐 (2026)(2)"),
            _folder("c1", "王子与乞丐 (2026)[tmdbid-328704]"),
        ]
        self.assertEqual(match(entries, "王子与乞丐 (2026)")["id"], "c2")
        entries.append(_folder("c0", "王子与乞丐 (2026)"))
        self.assertEqual(match(entries, "王子与乞丐 (2026)")["id"], "c0")
        self.assertIsNone(match(entries, "另一部片 (2026)"))


class ScraperFolderReuseTest(unittest.TestCase):
    """计划期/执行期的目录查找都要复用带命名装饰的现有文件夹。"""

    def _pages(self, entries):
        def fake_page(provider, cookie, cid, folders_only, offset, limit, cache=None):
            if offset:
                return {"entries": [], "has_more": False, "count": len(entries)}
            return {"entries": list(entries), "has_more": False, "count": len(entries)}

        return fake_page

    def test_walk_existing_folder_reuses_decorated_folder(self):
        entries = [_folder("root", "影视"), _folder("show", "王子与乞丐 (2026) [tmdbid-328704]")]
        with (
            mock.patch.object(scraper_service, "_get_scraper_entries_page", side_effect=self._pages(entries)),
            mock.patch.object(scraper_service, "_create_provider_folder") as create,
        ):
            cid, exists = scraper_service._walk_existing_folder("115", "cookie", "0", "影视/王子与乞丐 (2026)")

        self.assertTrue(exists)
        self.assertEqual(cid, "show")
        create.assert_not_called()

    def test_ensure_folder_from_base_reuses_decorated_folder(self):
        root_entries = [_folder("root", "影视")]
        show_entries = [_folder("show", "王子与乞丐 (2026)(1)")]

        def fake_page(provider, cookie, cid, folders_only, offset, limit, cache=None):
            entries = show_entries if cid == "root" else root_entries
            return {"entries": list(entries) if not offset else [], "has_more": False}

        with (
            mock.patch.object(scraper_service, "_get_scraper_entries_page", side_effect=fake_page),
            mock.patch.object(scraper_service, "_create_provider_folder") as create,
        ):
            cid = scraper_service._ensure_folder_from_base("115", "cookie", "0", "影视/王子与乞丐 (2026)")

        self.assertEqual(cid, "show")
        create.assert_not_called()

    def test_ensure_folder_from_base_does_not_match_other_title(self):
        def fake_page(provider, cookie, cid, folders_only, offset, limit, cache=None):
            entries = [_folder("other", "王子与乞丐 (2025)")] if cid == "root" else [_folder("other", "王子与乞丐 (2025)")]
            return {"entries": list(entries) if not offset else [], "has_more": False}

        with (
            mock.patch.object(scraper_service, "_get_scraper_entries_page", side_effect=fake_page),
            mock.patch.object(scraper_service, "_create_provider_folder", return_value={"id": "new"}) as create,
        ):
            cid = scraper_service._ensure_folder_from_base("115", "cookie", "0", "王子与乞丐 (2026)")

        self.assertEqual(cid, "new")
        self.assertEqual(create.call_count, 1)

    def test_find_scraper_media_folder_returns_decorated_match(self):
        entries = [
            _folder("other", "别的剧 (2026)"),
            _folder("show", "王子与乞丐 (2026) [tmdbid-328704]"),
        ]
        with (
            mock.patch.object(scraper_service, "_require_provider_cookie", return_value="cookie"),
            mock.patch.object(scraper_service, "_get_scraper_entries_page", side_effect=self._pages(entries)),
        ):
            matched = scraper_service.find_scraper_media_folder("115", "target-cid", "王子与乞丐 (2026)")

        self.assertEqual(matched.get("id"), "show")


if __name__ == "__main__":
    unittest.main()
