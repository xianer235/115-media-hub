"""极影视库存索引（jys_inventory）测试。

覆盖：条目抽取（有 TMDB ID 才收、BoxSet/Folder 等聚合类型过滤、Series 映射成 tv、
年份解析）、批量查询（精确匹配、空入参、非法 id）。数据库走项目自己的 DB_PATH，
用临时路径替换避免污染真实 data.db；极影视登录与拉库不真连，只测纯函数。
"""

import os
import unittest
from unittest import mock

from app.services import jys_inventory as jys
from app import db as db_module


def _item(**kw):
    base = {
        "Name": "测试片",
        "Type": "Movie",
        "ProductionYear": 2020,
        "ProviderIds": {"Tmdb": "12345"},
        "Id": "video_x",
    }
    base.update(kw)
    return base


class ExtractRowsTest(unittest.TestCase):
    def test_movie_with_tmdb(self):
        rows = jys._extract_inventory_rows([_item(Name="阿凡达", Type="Movie", ProductionYear=2009, ProviderIds={"Tmdb": "19995"})])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["tmdb_id"], 19995)
        self.assertEqual(rows[0]["media_type"], "movie")
        self.assertEqual(rows[0]["year"], 2009)

    def test_series_maps_to_tv(self):
        rows = jys._extract_inventory_rows([_item(Name="尚公主", Type="Series", ProductionYear=2025, ProviderIds={"Tmdb": "286171"})])
        self.assertEqual(rows[0]["media_type"], "tv")

    def test_skips_boxset_and_folder(self):
        items = [
            _item(Name="海贼王 剧场版（系列）", Type="BoxSet", ProviderIds=None),
            _item(Name="TMDB TOP100", Type="Folder", ProviderIds={}),
            _item(Name="正常电影", Type="Movie", ProviderIds={"Tmdb": "1"}),
        ]
        rows = jys._extract_inventory_rows(items)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "正常电影")

    def test_skips_missing_tmdb(self):
        rows = jys._extract_inventory_rows([
            _item(Name="无 ID 电影", Type="Movie", ProviderIds={}),
            _item(Name="无 ID 剧", Type="Series", ProviderIds=None),
        ])
        self.assertEqual(rows, [])

    def test_year_none_when_missing(self):
        rows = jys._extract_inventory_rows([_item(Name="无年份", Type="Movie", ProductionYear=None, ProviderIds={"Tmdb": "9"})])
        self.assertIsNone(rows[0]["year"])

    def test_skips_empty_name(self):
        rows = jys._extract_inventory_rows([_item(Name="", Type="Movie", ProviderIds={"Tmdb": "9"})])
        self.assertEqual(rows, [])

    def test_non_dict_item_ignored(self):
        rows = jys._extract_inventory_rows(["not-a-dict", None, 42])
        self.assertEqual(rows, [])


class QueryInventoryTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._td = tempfile.mkdtemp(prefix="jys-inventory-test-")
        self._patch = mock.patch.object(db_module, "DB_PATH", os.path.join(self._td, "test.db"))
        self._patch.start()
        db_module._DB_ENSURED = False

    def tearDown(self):
        self._patch.stop()
        import shutil
        shutil.rmtree(self._td, ignore_errors=True)

    def _seed(self, tmdb_ids):
        db_module.ensure_db()
        conn = db_module.open_db()
        try:
            conn.executemany(
                "INSERT OR REPLACE INTO jys_inventory (tmdb_id, name, year, media_type) VALUES (?, 'x', 2020, 'movie')",
                [(i,) for i in tmdb_ids],
            )
            conn.commit()
        finally:
            conn.close()

    def test_query_hits_exact_ids(self):
        self._seed([1, 2, 3])
        owned = jys.query_inventory([{"id": 1}, {"id": 2}, {"id": 999}])
        self.assertEqual(owned, {1: True, 2: True})

    def test_query_empty_input(self):
        self.assertEqual(jys.query_inventory([]), {})
        self.assertEqual(jys.query_inventory(None), {})

    def test_query_ignores_invalid_ids(self):
        self._seed([1])
        owned = jys.query_inventory([{"id": "abc"}, {"id": 0}, {"id": -5}, {"id": 1}])
        self.assertEqual(owned, {1: True})

    def test_query_accepts_tmdb_id_field(self):
        self._seed([7])
        owned = jys.query_inventory([{"tmdb_id": 7}])
        self.assertEqual(owned, {7: True})


class RefreshFailureTest(unittest.TestCase):
    """拉库全失败时不能把索引清空，错误文案要能照着排查。"""

    def setUp(self):
        import tempfile
        self._td = tempfile.mkdtemp(prefix="jys-inventory-test-")
        self._patch = mock.patch.object(db_module, "DB_PATH", os.path.join(self._td, "test.db"))
        self._patch.start()
        db_module._DB_ENSURED = False

    def tearDown(self):
        self._patch.stop()
        import shutil
        shutil.rmtree(self._td, ignore_errors=True)

    def _count(self):
        db_module.ensure_db()
        conn = db_module.open_db()
        try:
            return conn.execute("SELECT COUNT(*) FROM jys_inventory").fetchone()[0]
        finally:
            conn.close()

    def test_all_libraries_failing_keeps_previous_index(self):
        db_module.ensure_db()
        conn = db_module.open_db()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO jys_inventory (tmdb_id, name, year, media_type) VALUES (1, '旧片', 2020, 'movie')"
            )
            conn.commit()
        finally:
            conn.close()

        settings = {"enabled": True, "upstream": "https://jys.example.com", "username": "u", "password": "p"}
        views = {"Items": [{"Id": "lib1", "Name": "电影"}]}
        with mock.patch.object(jys, "_bridge_settings", return_value=settings), \
                mock.patch.object(jys, "_get_token", return_value={"uid": "u1", "token": "t", "server_id": "s"}), \
                mock.patch("app.services.emby_bridge._forward_json", return_value=(200, {}, views)), \
                mock.patch.object(jys, "_aggregate_items", return_value=(502, {}, {})):
            result = jys.refresh_jys_inventory()

        self.assertFalse(result["ok"])
        self.assertIn("保留上次索引", result["msg"])
        self.assertEqual(self._count(), 1)  # 旧索引没被清空

    def test_tls_error_message_points_at_network(self):
        import ssl

        exc = ssl.SSLEOFError(8, "EOF occurred in violation of protocol")
        message = jys._explain_refresh_error(exc)
        self.assertIn("TLS", message)
        self.assertIn("局域网", message)

    def test_plain_error_kept_as_is(self):
        self.assertEqual(jys._explain_refresh_error(RuntimeError("极影视登录未返回用户 ID / token")),
                         "极影视登录未返回用户 ID / token")


if __name__ == "__main__":
    unittest.main()
