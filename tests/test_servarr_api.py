"""servarr（Radarr/Sonarr v3 兼容层）接口测试。

覆盖 /api/v3 的 16 个端点：鉴权、静态端点、电影点播/查询、剧集点播/查询、
删除。配置读写全部 mock（内存 store，save_config 真实写回 store 才能测到
追加/删除逻辑）；TMDB 相关函数按用例 mock，不碰网络；queue_subscription_job /
schedule_ui_state_push / prune_subscription_state_for_missing_tasks mock 掉避免副作用。

不 mock normalize_subscription_task / build_tmdb_task_binding——要真实归一化，
这才测得到字段映射。临时目录交给 tempfile（根在 run_tests.py 指定的会话目录）。
"""

import shutil
import tempfile
import unittest
from contextlib import contextmanager
from unittest import mock

from fastapi.testclient import TestClient

from app.main import app
from app.routes import servarr as servarr_routes

API_KEY = "test-key-0123456789abcdef"
HEADERS = {"X-Api-Key": API_KEY}
TVDB_ID = 83245
TV_TMDB_ID = 1396

BASE_CFG = {
    "servarr_api_key": API_KEY,
    "servarr_default_savepath": "Seerr点播",
    "servarr_movie_savepath": "媒体库/网盘电影",
    "servarr_tv_savepath": "媒体库/网盘电视剧",
}

FAKE_MOVIE_DETAIL = {
    "id": 603,
    "title": "黑客帝国",
    "original_title": "The Matrix",
    "year": "1999",
    "media_type": "movie",
    "poster_url": "",
    "aliases": [],
    "total_episodes": 0,
    "total_seasons": 0,
    "season_episode_map": {},
    "episode_mode": "seasonal",
}

FAKE_TV_DETAIL = {
    "id": TV_TMDB_ID,
    "title": "绝命毒师",
    "original_title": "Breaking Bad",
    "year": "2008",
    "media_type": "tv",
    "poster_url": "",
    "aliases": [],
    "total_episodes": 44,
    "total_seasons": 2,
    "season_episode_map": {"1": 22, "2": 22},
    "episode_mode": "seasonal",
}


class _Patched:
    """_patched 上下文的产出：内存配置 + 各 mock。"""

    def __init__(self, store, save, queue, push, prune):
        self.store = store
        self.save = save
        self.queue = queue
        self.push = push
        self.prune = prune

    def tasks(self):
        return self.store.get("subscription_tasks", [])


def _movie_task(tmdb_id=603, name="黑客帝国 (1999)"):
    return {
        "name": name,
        "media_type": "movie",
        "tmdb_id": tmdb_id,
        "title": "黑客帝国",
        "year": "1999",
        "season": 1,
        "enabled": True,
    }


def _tv_task(tmdb_id=TV_TMDB_ID, season=1, name=None):
    return {
        "name": name or f"绝命毒师 (2008) S{season:02d}",
        "media_type": "tv",
        "tmdb_id": tmdb_id,
        "title": "绝命毒师",
        "year": "2008",
        "season": season,
        "enabled": True,
    }


class ServarrApiTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wb_servarr_")
        self.client = TestClient(app)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @contextmanager
    def _patched(
        self,
        cfg=None,
        tmdb_config_error=None,
        movie_detail=None,
        tv_detail=None,
        tvdb_to_tmdb=0,
        detail_exc=None,
    ):
        """把 servarr 路由的配置/TMDB/队列函数换成内存实现。

        save_config 真正写回 store（否则追加/删除逻辑测不到）；
        tmdb_config_error 非空模拟「TMDB 未配置」；tvdb_to_tmdb 模拟 find 结果。
        """
        store = dict(BASE_CFG)
        store.update(cfg or {})

        def fake_save(updated):
            store.clear()
            store.update(updated)

        def fake_detail(tmdb_id, media_type, cfg=None):
            if detail_exc is not None:
                raise detail_exc
            if media_type == "tv":
                return tv_detail if tv_detail is not None else FAKE_TV_DETAIL
            return movie_detail if movie_detail is not None else FAKE_MOVIE_DETAIL

        with mock.patch.object(servarr_routes, "get_config", side_effect=lambda: store), \
                mock.patch.object(servarr_routes, "save_config", side_effect=fake_save) as save_mock, \
                mock.patch.object(servarr_routes, "queue_subscription_job") as queue_mock, \
                mock.patch.object(servarr_routes, "schedule_ui_state_push") as push_mock, \
                mock.patch.object(servarr_routes, "validate_tmdb_runtime_config", return_value=tmdb_config_error), \
                mock.patch.object(servarr_routes, "get_tmdb_media_detail", side_effect=fake_detail), \
                mock.patch.object(servarr_routes, "find_tmdb_id_by_tvdb_id", return_value=tvdb_to_tmdb), \
                mock.patch.object(servarr_routes, "prune_subscription_state_for_missing_tasks") as prune_mock:
            yield _Patched(store=store, save=save_mock, queue=queue_mock, push=push_mock, prune=prune_mock)


# ------------------------------------------------------------------ 鉴权

class ServarrAuthTest(ServarrApiTestBase):
    def test_no_api_key_configured_returns_503(self):
        with self._patched(cfg={"servarr_api_key": ""}):
            resp = self.client.get("/api/v3/system/status")
        self.assertEqual(resp.status_code, 503)
        self.assertIn("未启用", resp.json()["detail"])

    def test_wrong_api_key_returns_401(self):
        with self._patched():
            resp = self.client.get("/api/v3/system/status", headers={"X-Api-Key": "wrong-key"})
        self.assertEqual(resp.status_code, 401)

    def test_correct_api_key_and_bearer_both_accepted(self):
        with self._patched():
            resp = self.client.get("/api/v3/system/status", headers=HEADERS)
            self.assertEqual(resp.status_code, 200)
            resp_bearer = self.client.get(
                "/api/v3/system/status", headers={"Authorization": f"Bearer {API_KEY}"}
            )
            self.assertEqual(resp_bearer.status_code, 200)
            resp_query = self.client.get(
                f"/api/v3/system/status?apikey={API_KEY}"
            )
            self.assertEqual(resp_query.status_code, 200)

    def test_missing_key_header_returns_401(self):
        with self._patched():
            resp = self.client.get("/api/v3/system/status")
        self.assertEqual(resp.status_code, 401)


# ------------------------------------------------------------------ 静态端点

class ServarrStaticEndpointsTest(ServarrApiTestBase):
    def test_system_status(self):
        with self._patched():
            resp = self.client.get("/api/v3/system/status", headers=HEADERS)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["appName"], "115 Media Hub")
        self.assertTrue(data["version"])

    def test_quality_profile(self):
        with self._patched():
            resp = self.client.get("/api/v3/qualityProfile", headers=HEADERS)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], 1)
        self.assertEqual(data[0]["name"], "默认")
        self.assertTrue(data[0]["items"])

    def test_rootfolder_default_and_configured(self):
        with self._patched():
            resp = self.client.get("/api/v3/rootfolder", headers=HEADERS)
        self.assertEqual(resp.json(), [{"id": 1, "path": "/"}])

    def test_tag(self):
        with self._patched():
            resp = self.client.get("/api/v3/tag", headers=HEADERS)
        self.assertEqual(resp.json(), [{"id": 1, "label": "默认"}])

    def test_language_profile(self):
        with self._patched():
            resp = self.client.get("/api/v3/languageprofile", headers=HEADERS)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], 1)


# ------------------------------------------------------------------ 电影点播

class ServarrMovieApiTest(ServarrApiTestBase):
    def test_add_movie_creates_task_and_persists(self):
        with self._patched() as ctx:
            resp = self.client.post("/api/v3/movie", json={"tmdbId": 603}, headers=HEADERS)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"id": 603})
        self.assertEqual(ctx.save.call_count, 1)
        tasks = ctx.tasks()
        self.assertEqual(len(tasks), 1)
        task = tasks[0]
        self.assertEqual(task["name"], "黑客帝国 (1999)")
        self.assertEqual(task["provider"], "115")
        self.assertEqual(task["media_type"], "movie")
        self.assertEqual(task["savepath"], "Seerr点播")
        self.assertEqual(task["tmdb_id"], 603)
        self.assertEqual(task["tmdb_title"], "黑客帝国")
        self.assertEqual(task["tmdb_year"], "1999")
        self.assertTrue(task["enabled"])
        self.assertTrue(task["organize_on_import"])

    def test_add_movie_queues_job_immediately(self):
        with self._patched() as ctx:
            resp = self.client.post("/api/v3/movie", json={"tmdbId": 603}, headers=HEADERS)
        self.assertEqual(resp.status_code, 200)
        ctx.queue.assert_called_once_with("黑客帝国 (1999)", "servarr")

    def test_add_movie_idempotent_when_already_subscribed(self):
        cfg = {"subscription_tasks": [_movie_task()]}
        with self._patched(cfg) as ctx:
            resp = self.client.post("/api/v3/movie", json={"tmdbId": 603}, headers=HEADERS)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"id": 603})
        self.assertEqual(ctx.save.call_count, 0)
        self.assertEqual(len(ctx.tasks()), 1)

    def test_add_movie_without_tmdb_id_returns_400(self):
        with self._patched():
            resp = self.client.post("/api/v3/movie", json={"title": "黑客帝国"}, headers=HEADERS)
        self.assertEqual(resp.status_code, 400)

    def test_add_movie_without_default_savepath_returns_400(self):
        with self._patched(cfg={"servarr_default_savepath": "", "servarr_movie_savepath": ""}):
            resp = self.client.post("/api/v3/movie", json={"tmdbId": 603}, headers=HEADERS)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("未配置电影点播保存目录", resp.json()["detail"])

    def test_add_movie_with_tmdb_config_error_returns_400(self):
        with self._patched(tmdb_config_error="TMDB 增强未启用，请先在参数配置中开启"):
            resp = self.client.post("/api/v3/movie", json={"tmdbId": 603}, headers=HEADERS)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("TMDB 增强未启用", resp.json()["detail"])

    def test_add_movie_detail_failure_returns_500(self):
        with self._patched(detail_exc=RuntimeError("tmdb boom")):
            resp = self.client.post("/api/v3/movie", json={"tmdbId": 603}, headers=HEADERS)
        self.assertEqual(resp.status_code, 500)

    def test_movie_lookup_monitored_follows_subscription(self):
        with self._patched() as ctx:
            resp = self.client.get("/api/v3/movie/lookup", params={"term": "tmdb:603"}, headers=HEADERS)
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["tmdbId"], 603)
            self.assertFalse(data[0]["monitored"])
            ctx.store["subscription_tasks"] = [_movie_task()]
            resp = self.client.get("/api/v3/movie/lookup", params={"term": "tmdb:603"}, headers=HEADERS)
            self.assertTrue(resp.json()[0]["monitored"])

    def test_movie_lookup_non_numeric_term_returns_empty(self):
        with self._patched():
            resp = self.client.get("/api/v3/movie/lookup", params={"term": "abc"}, headers=HEADERS)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_movie_list_filters_by_tmdb_id(self):
        cfg = {
            "subscription_tasks": [
                _movie_task(603, "黑客帝国 (1999)"),
                _movie_task(155, "黑暗骑士 (2008)"),
            ]
        }
        with self._patched(cfg):
            resp = self.client.get("/api/v3/movie", params={"tmdbId": 603}, headers=HEADERS)
            self.assertEqual(len(resp.json()), 1)
            resp = self.client.get("/api/v3/movie", params={"tmdbId": 999}, headers=HEADERS)
            self.assertEqual(resp.json(), [])
            resp = self.client.get("/api/v3/movie", headers=HEADERS)
            self.assertEqual(len(resp.json()), 2)

    def test_movie_detail_found_and_not_found(self):
        cfg = {"subscription_tasks": [_movie_task()]}
        with self._patched(cfg):
            resp = self.client.get("/api/v3/movie/603", headers=HEADERS)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["tmdbId"], 603)
            resp = self.client.get("/api/v3/movie/999", headers=HEADERS)
            self.assertEqual(resp.status_code, 404)


# ------------------------------------------------------------------ 剧集点播

class ServarrSeriesApiTest(ServarrApiTestBase):
    def test_add_series_by_tvdb_id_resolves_tmdb_id(self):
        with self._patched(tvdb_to_tmdb=TV_TMDB_ID) as ctx:
            resp = self.client.post(
                "/api/v3/series",
                json={"tvdbId": TVDB_ID, "seasons": [{"seasonNumber": 1, "monitored": True}]},
                headers=HEADERS,
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"id": TV_TMDB_ID})
        tasks = ctx.tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["name"], "绝命毒师 (2008)")
        self.assertEqual(tasks[0]["season"], 1)
        self.assertEqual(tasks[0]["total_episodes"], 22)
        ctx.queue.assert_called_once_with("绝命毒师 (2008)", "servarr")

    def test_add_series_multi_season_creates_one_task_per_season(self):
        with self._patched() as ctx:
            resp = self.client.post(
                "/api/v3/series",
                json={
                    "tmdbId": TV_TMDB_ID,
                    "seasons": [
                        {"seasonNumber": 1, "monitored": True},
                        {"seasonNumber": 2, "monitored": True},
                        {"seasonNumber": 3, "monitored": True},
                    ],
                },
                headers=HEADERS,
            )
        self.assertEqual(resp.status_code, 200)
        tasks = ctx.tasks()
        self.assertEqual(
            [t["name"] for t in tasks],
            ["绝命毒师 (2008) S01", "绝命毒师 (2008) S02", "绝命毒师 (2008) S03"],
        )
        self.assertEqual([t["total_episodes"] for t in tasks], [22, 22, 0])
        self.assertEqual(ctx.queue.call_count, 3)

    def test_add_series_skips_existing_seasons(self):
        cfg = {"subscription_tasks": [_tv_task(season=2)]}
        with self._patched(cfg) as ctx:
            resp = self.client.post(
                "/api/v3/series",
                json={
                    "tmdbId": TV_TMDB_ID,
                    "seasons": [
                        {"seasonNumber": 2, "monitored": True},
                        {"seasonNumber": 3, "monitored": True},
                    ],
                },
                headers=HEADERS,
            )
        self.assertEqual(resp.status_code, 200)
        tasks = ctx.tasks()
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[-1]["season"], 3)

    def test_add_series_all_seasons_exist_is_idempotent(self):
        cfg = {"subscription_tasks": [_tv_task(season=1), _tv_task(season=2), _tv_task(season=3)]}
        with self._patched(cfg) as ctx:
            resp = self.client.post(
                "/api/v3/series",
                json={
                    "tmdbId": TV_TMDB_ID,
                    "seasons": [
                        {"seasonNumber": 1, "monitored": True},
                        {"seasonNumber": 2, "monitored": True},
                        {"seasonNumber": 3, "monitored": True},
                    ],
                },
                headers=HEADERS,
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"id": TV_TMDB_ID})
        self.assertEqual(ctx.save.call_count, 0)
        self.assertEqual(ctx.queue.call_count, 0)

    def test_add_series_skips_specials_and_unmonitored(self):
        with self._patched() as ctx:
            resp = self.client.post(
                "/api/v3/series",
                json={
                    "tmdbId": TV_TMDB_ID,
                    "seasons": [
                        {"seasonNumber": 0, "monitored": True},
                        {"seasonNumber": 1, "monitored": False},
                        {"seasonNumber": 2, "monitored": True},
                    ],
                },
                headers=HEADERS,
            )
        self.assertEqual(resp.status_code, 200)
        tasks = ctx.tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["season"], 2)
        self.assertEqual(tasks[0]["name"], "绝命毒师 (2008)")

    def test_add_series_without_seasons_falls_back_to_tmdb_seasons(self):
        with self._patched() as ctx:
            resp = self.client.post(
                "/api/v3/series", json={"tmdbId": TV_TMDB_ID, "seasons": []}, headers=HEADERS
            )
        self.assertEqual(resp.status_code, 200)
        tasks = ctx.tasks()
        self.assertEqual([t["season"] for t in tasks], [1, 2])
        self.assertEqual(
            [t["name"] for t in tasks], ["绝命毒师 (2008) S01", "绝命毒师 (2008) S02"]
        )

    def test_add_series_without_any_id_returns_400(self):
        with self._patched():
            resp = self.client.post("/api/v3/series", json={"title": "绝命毒师"}, headers=HEADERS)
        self.assertEqual(resp.status_code, 400)

    def test_add_series_without_default_savepath_returns_400(self):
        with self._patched(cfg={"servarr_default_savepath": "", "servarr_tv_savepath": ""}, tvdb_to_tmdb=TV_TMDB_ID):
            resp = self.client.post("/api/v3/series", json={"tmdbId": TV_TMDB_ID}, headers=HEADERS)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("未配置电视剧点播保存目录", resp.json()["detail"])

    def test_add_series_name_collision_gets_tmdb_suffix(self):
        cfg = {"subscription_tasks": [_movie_task(tmdb_id=999, name="绝命毒师 (2008)")]}
        with self._patched(cfg) as ctx:
            resp = self.client.post(
                "/api/v3/series",
                json={"tmdbId": TV_TMDB_ID, "seasons": [{"seasonNumber": 1, "monitored": True}]},
                headers=HEADERS,
            )
        self.assertEqual(resp.status_code, 200)
        new_task = ctx.tasks()[-1]
        self.assertEqual(new_task["name"], f"绝命毒师 (2008) tmdb{TV_TMDB_ID}")

    def test_add_series_unresolvable_tvdb_id_returns_400(self):
        with self._patched(tvdb_to_tmdb=0):
            resp = self.client.post("/api/v3/series", json={"tvdbId": TVDB_ID}, headers=HEADERS)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("对应的 TMDB 条目", resp.json()["detail"])

    def test_series_lookup_tvdb_term(self):
        with self._patched(tvdb_to_tmdb=TV_TMDB_ID):
            resp = self.client.get(
                "/api/v3/series/lookup", params={"term": f"tvdb:{TVDB_ID}"}, headers=HEADERS
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        series = data[0]
        self.assertEqual(series["tvdbId"], TVDB_ID)
        self.assertEqual(series["tmdbId"], TV_TMDB_ID)
        self.assertEqual(series["seasonCount"], 2)
        self.assertEqual([s["seasonNumber"] for s in series["seasons"]], [1, 2])
        self.assertFalse(any(s["monitored"] for s in series["seasons"]))

    def test_series_list_by_tvdb_id_and_unresolvable(self):
        cfg = {"subscription_tasks": [_tv_task(season=1), _tv_task(season=2)]}
        with self._patched(cfg, tvdb_to_tmdb=TV_TMDB_ID):
            resp = self.client.get("/api/v3/series", params={"tvdbId": TVDB_ID}, headers=HEADERS)
            self.assertEqual(len(resp.json()), 1)
            self.assertEqual(resp.json()[0]["seasonCount"], 2)
        with self._patched(cfg, tvdb_to_tmdb=0):
            resp = self.client.get("/api/v3/series", params={"tvdbId": TVDB_ID}, headers=HEADERS)
            self.assertEqual(resp.json(), [])

    def test_series_detail_found_and_not_found(self):
        cfg = {"subscription_tasks": [_tv_task(season=1), _tv_task(season=2)]}
        with self._patched(cfg):
            resp = self.client.get(f"/api/v3/series/{TV_TMDB_ID}", headers=HEADERS)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual([s["seasonNumber"] for s in resp.json()["seasons"]], [1, 2])
            resp = self.client.get("/api/v3/series/8888", headers=HEADERS)
            self.assertEqual(resp.status_code, 404)


# ------------------------------------------------------------------ 删除

class ServarrDeleteApiTest(ServarrApiTestBase):
    def test_delete_movie_removes_task_and_prunes_state(self):
        cfg = {"subscription_tasks": [_movie_task()]}
        with self._patched(cfg) as ctx:
            resp = self.client.delete("/api/v3/movie/603", headers=HEADERS)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json(), {"ok": True})
            self.assertEqual(ctx.save.call_count, 1)
            self.assertEqual(ctx.tasks(), [])
            self.assertEqual(ctx.prune.call_count, 1)
            resp = self.client.delete("/api/v3/movie/999", headers=HEADERS)
            self.assertEqual(resp.status_code, 404)

    def test_delete_series_removes_all_season_tasks(self):
        cfg = {"subscription_tasks": [_tv_task(season=1), _tv_task(season=2), _movie_task()]}
        with self._patched(cfg) as ctx:
            resp = self.client.delete(f"/api/v3/series/{TV_TMDB_ID}", headers=HEADERS)
            self.assertEqual(resp.status_code, 200)
            tasks = ctx.tasks()
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0]["media_type"], "movie")
            resp = self.client.delete("/api/v3/series/8888", headers=HEADERS)
            self.assertEqual(resp.status_code, 404)

    def test_put_series_matches_post_behavior(self):
        with self._patched() as ctx:
            resp = self.client.put(
                "/api/v3/series",
                json={"tmdbId": TV_TMDB_ID, "seasons": [{"seasonNumber": 1, "monitored": True}]},
                headers=HEADERS,
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"id": TV_TMDB_ID})
        tasks = ctx.tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["name"], "绝命毒师 (2008)")
        ctx.queue.assert_called_once_with("绝命毒师 (2008)", "servarr")


if __name__ == "__main__":
    unittest.main()
