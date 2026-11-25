"""探索页筛选参数拼装测试（不联网）。

只校验 `discover_tmdb_media` / `search_tmdb_keywords` 把前端条件翻译成 TMDB
query 参数的过程：区间、分类 AND/OR、排除分类、关键词、剧集状态与类型、
排序白名单。TMDB 请求本身用 mock 顶替，断言落到最终 params。
"""

import unittest
from unittest import mock

from app.providers import tmdb


class _CaptureRequest:
    """替换 tmdb_request_json，吃掉参数并返回固定的空结果。"""

    def __init__(self):
        self.calls = []

    def __call__(self, path, params=None, cfg=None, force_refresh=False):
        self.calls.append({"path": path, "params": dict(params or {})})
        return {"results": [], "total_pages": 1, "page": 1}

    @property
    def last_params(self):
        return self.calls[-1]["params"]


class DiscoverParamsTest(unittest.TestCase):
    def setUp(self):
        self.capture = _CaptureRequest()
        patcher = mock.patch.object(tmdb, "tmdb_request_json", self.capture)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _params(self, **kwargs):
        tmdb.discover_tmdb_media(**kwargs)
        return self.capture.last_params

    def test_genres_default_or_uses_pipe(self):
        params = self._params(genres="28,35")
        self.assertEqual(params["with_genres"], "28|35")

    def test_genres_and_mode_uses_comma(self):
        params = self._params(genres="28,35", genres_mode="and")
        self.assertEqual(params["with_genres"], "28,35")

    def test_genre_input_is_sanitised(self):
        params = self._params(genres="28, 35，abc、16", genres_mode="and")
        self.assertEqual(params["with_genres"], "28,35,16")

    def test_exclude_genres_and_keywords(self):
        params = self._params(without_genres="27,53", keywords="9715, 123")
        self.assertEqual(params["without_genres"], "27,53")
        # 关键词多选按「任一命中」，逗号是 AND 语义会导致空结果
        self.assertEqual(params["with_keywords"], "9715|123")

    def test_rating_and_vote_ranges(self):
        params = self._params(
            vote_average_gte=7.5, vote_average_lte=9,
            vote_count_gte=500, vote_count_lte=20000,
            with_runtime_gte=90, with_runtime_lte=150,
        )
        self.assertEqual(params["vote_average.gte"], "7.5")
        self.assertEqual(params["vote_average.lte"], "9.0")
        self.assertEqual(params["vote_count.gte"], "500")
        self.assertEqual(params["vote_count.lte"], "20000")
        self.assertEqual(params["with_runtime.gte"], "90")
        self.assertEqual(params["with_runtime.lte"], "150")

    def test_zero_bounds_are_omitted(self):
        params = self._params(vote_average_gte=0, vote_average_lte=0, vote_count_gte=0, vote_count_lte=0)
        self.assertNotIn("vote_average.gte", params)
        self.assertNotIn("vote_average.lte", params)
        self.assertNotIn("vote_count.gte", params)
        self.assertNotIn("vote_count.lte", params)

    def test_tv_status_and_type_applied_for_tv_only(self):
        params = self._params(media_type="tv", tv_status="3", tv_type="2")
        self.assertEqual(params["with_status"], "3")
        self.assertEqual(params["with_type"], "2")

        movie_params = self._params(media_type="movie", tv_status="3", tv_type="2")
        self.assertNotIn("with_status", movie_params)
        self.assertNotIn("with_type", movie_params)

    def test_invalid_tv_status_dropped(self):
        params = self._params(media_type="tv", tv_status="9", tv_type="x")
        self.assertNotIn("with_status", params)
        self.assertNotIn("with_type", params)

    def test_tv_type_accepts_video_bucket(self):
        # TMDB with_type 上限是 6（Video），状态只到 5
        self.assertEqual(self._params(media_type="tv", tv_type="6")["with_type"], "6")
        self.assertNotIn("with_type", self._params(media_type="tv", tv_type="7"))

    def test_year_range_becomes_date_bounds(self):
        params = self._params(primary_release_date_gte="2015", primary_release_date_lte="2020")
        self.assertEqual(params["primary_release_date.gte"], "2015-01-01")
        self.assertEqual(params["primary_release_date.lte"], "2020-12-31")

    def test_sort_whitelist_keeps_vote_count(self):
        self.assertEqual(self._params(sort_by="vote_count.desc")["sort_by"], "vote_count.desc")
        self.assertEqual(self._params(sort_by="hack.asc")["sort_by"], "popularity.desc")


class KeywordSearchTest(unittest.TestCase):
    def test_maps_keyword_results(self):
        payload = {"results": [{"id": 9715, "name": "superhero"}, {"id": 0, "name": "bad"}, {"id": 5, "name": ""}]}
        with mock.patch.object(tmdb, "tmdb_request_json", return_value=payload):
            items = tmdb.search_tmdb_keywords("super", cfg={})
        self.assertEqual(items, [{"id": 9715, "name": "superhero"}])

    def test_short_query_skips_request(self):
        with mock.patch.object(tmdb, "tmdb_request_json") as request:
            self.assertEqual(tmdb.search_tmdb_keywords("a", cfg={}), [])
        request.assert_not_called()


class RouteQueryParseTest(unittest.TestCase):
    """路由层的数值 query 解析：非法输入不能抛异常变成 500。"""

    @staticmethod
    def _request(query: str):
        from starlette.requests import Request

        return Request({
            "type": "http",
            "method": "GET",
            "path": "/tmdb/discover",
            "query_string": query.encode(),
            "headers": [],
        })

    def test_bad_float_falls_back_to_default(self):
        from app.routes import tmdb as routes

        self.assertEqual(routes._query_float(self._request("vote_average_lte=abc"), "vote_average_lte"), 0.0)
        self.assertEqual(routes._query_float(self._request("vote_average_lte=1e"), "vote_average_lte"), 0.0)

    def test_float_is_clamped_to_rating_range(self):
        from app.routes import tmdb as routes

        self.assertEqual(routes._query_float(self._request("vote_average_lte=99"), "vote_average_lte"), 10.0)
        self.assertEqual(routes._query_float(self._request("vote_average_gte=-3"), "vote_average_gte"), 0.0)

    def test_bad_int_falls_back_to_zero(self):
        from app.routes import tmdb as routes

        self.assertEqual(routes._query_int(self._request("vote_count_lte=abc"), "vote_count_lte"), 0)
        self.assertEqual(routes._query_int(self._request("vote_count_lte=500"), "vote_count_lte"), 500)


if __name__ == "__main__":
    unittest.main()
