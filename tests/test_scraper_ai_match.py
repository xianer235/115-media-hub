import unittest
from unittest import mock

from app import core
from app.services import ai_match, scraper


def _runtime():
    return {
        "base_url": "http://x/v1",
        "api_key": "k",
        "model": "m",
        "temperature": 0,
        "timeout_seconds": 5,
        "max_concurrency": 3,
        "max_candidates": 5,
    }


def _fake_candidate(tmdb_id=603, media_type="movie", title="The Matrix", year="1999", popularity=30.0):
    return {
        "id": tmdb_id,
        "media_type": media_type,
        "title": title,
        "original_title": title,
        "year": year,
        "popularity": popularity,
        "vote_average": 8.2,
        "overview": "A hacker learns the truth.",
    }


class AiMatchJsonParseTest(unittest.TestCase):
    def test_parse_plain_json(self):
        self.assertEqual(ai_match._parse_json_object('{"keyword": "黑客帝国"}'), {"keyword": "黑客帝国"})

    def test_parse_fenced_json(self):
        text = '```json\n{"tmdb_id": 603, "confidence": 90}\n```'
        self.assertEqual(ai_match._parse_json_object(text), {"tmdb_id": 603, "confidence": 90})

    def test_parse_json_with_surrounding_text(self):
        text = '好的，结果是 {"keyword": "Matrix", "year": "1999"} 请查收'
        self.assertEqual(ai_match._parse_json_object(text), {"keyword": "Matrix", "year": "1999"})

    def test_parse_invalid_returns_none(self):
        self.assertIsNone(ai_match._parse_json_object("not json"))
        self.assertIsNone(ai_match._parse_json_object(""))
        self.assertIsNone(ai_match._parse_json_object("[1, 2, 3]"))


class _FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class AiMatchChatJsonTest(unittest.TestCase):
    def test_chat_json_ok(self):
        response = _FakeResponse(200, {"choices": [{"message": {"content": '{"keyword": "X"}'}}]})
        with mock.patch.object(ai_match.requests, "post", return_value=response) as post:
            data, error = ai_match._ai_chat_json(_runtime(), [{"role": "user", "content": "hi"}])
        self.assertEqual(error, "")
        self.assertEqual(data, {"keyword": "X"})
        self.assertEqual(post.call_count, 1)

    def test_chat_json_retries_without_json_mode_on_400(self):
        first = _FakeResponse(400, text="response_format not supported")
        second = _FakeResponse(200, {"choices": [{"message": {"content": '{"keyword": "Y"}'}}]})
        with mock.patch.object(ai_match.requests, "post", side_effect=[first, second]) as post:
            data, error = ai_match._ai_chat_json(_runtime(), [{"role": "user", "content": "hi"}])
        self.assertEqual(error, "")
        self.assertEqual(data, {"keyword": "Y"})
        self.assertEqual(post.call_count, 2)
        self.assertNotIn("response_format", post.call_args_list[1].kwargs["json"])

    def test_chat_json_http_error(self):
        with mock.patch.object(ai_match.requests, "post", return_value=_FakeResponse(500, text="boom")):
            data, error = ai_match._ai_chat_json(_runtime(), [])
        self.assertIsNone(data)
        self.assertIn("HTTP 500", error)

    def test_chat_json_timeout(self):
        with mock.patch.object(ai_match.requests, "post", side_effect=ai_match.requests.RequestException("timeout")):
            data, error = ai_match._ai_chat_json(_runtime(), [])
        self.assertIsNone(data)
        self.assertIn("AI 请求失败", error)


class AiMatchRuntimeConfigTest(unittest.TestCase):
    def test_disabled_by_default(self):
        self.assertFalse(ai_match.build_ai_match_runtime_config({})["enabled"])
        self.assertEqual(ai_match.validate_ai_match_runtime_config({}), "AI 刮削辅助未启用")

    def test_enabled_requires_fields(self):
        missing = {
            "ai_match_enabled": True,
            "ai_match_base_url": "",
            "ai_match_api_key": "",
            "ai_match_model": "",
        }
        self.assertTrue(ai_match.validate_ai_match_runtime_config(missing))
        full = {
            "ai_match_enabled": True,
            "ai_match_base_url": "https://api.deepseek.com/v1/",
            "ai_match_api_key": "sk-test",
            "ai_match_model": "deepseek-chat",
        }
        self.assertIsNone(ai_match.validate_ai_match_runtime_config(full))
        runtime = ai_match.build_ai_match_runtime_config(full)
        self.assertEqual(runtime["base_url"], "https://api.deepseek.com/v1")
        self.assertEqual(runtime["timeout_seconds"], 20)
        self.assertEqual(runtime["max_concurrency"], 3)

    def test_normalize_config_defaults(self):
        cfg = core.normalize_config({})
        self.assertFalse(cfg["ai_match_enabled"])
        self.assertEqual(cfg["ai_match_base_url"], "")
        self.assertEqual(cfg["ai_match_api_key"], "")
        self.assertEqual(cfg["ai_match_model"], "")
        self.assertEqual(cfg["ai_match_timeout_seconds"], 20)
        self.assertEqual(cfg["ai_match_temperature"], 0)
        self.assertEqual(cfg["ai_match_max_concurrency"], 3)

    def test_normalize_config_clamps(self):
        cfg = core.normalize_config(
            {
                "ai_match_timeout_seconds": 999,
                "ai_match_temperature": 9,
                "ai_match_max_concurrency": 100,
                "ai_match_base_url": "http://x/v1/",
            }
        )
        self.assertEqual(cfg["ai_match_timeout_seconds"], 120)
        self.assertEqual(cfg["ai_match_temperature"], 2.0)
        self.assertEqual(cfg["ai_match_max_concurrency"], 8)
        self.assertEqual(cfg["ai_match_base_url"], "http://x/v1")


class AiMatchGenerateQueryTest(unittest.TestCase):
    def test_generate_query_ok(self):
        with mock.patch.object(
            ai_match,
            "_ai_chat_json",
            return_value=({"keyword": " 黑客帝国 ", "year": "1999", "media_type": "movie"}, ""),
        ):
            result = ai_match.ai_match_generate_query({"name": "黑客帝国4"}, runtime=_runtime())
        self.assertTrue(result["ok"])
        self.assertEqual(result["keyword"], "黑客帝国")
        self.assertEqual(result["year"], "1999")
        self.assertEqual(result["media_type"], "movie")

    def test_generate_query_rejects_bad_year_and_type(self):
        with mock.patch.object(
            ai_match,
            "_ai_chat_json",
            return_value=({"keyword": "X", "year": "19", "media_type": "anime"}, ""),
        ):
            result = ai_match.ai_match_generate_query({"name": "X"}, runtime=_runtime())
        self.assertEqual(result["year"], "")
        self.assertEqual(result["media_type"], "")

    def test_generate_query_empty_keyword(self):
        with mock.patch.object(ai_match, "_ai_chat_json", return_value=({"keyword": "   "}, "")):
            result = ai_match.ai_match_generate_query({"name": "X"}, runtime=_runtime())
        self.assertFalse(result["ok"])
        self.assertIn("关键词", result["error"])

    def test_generate_query_surfaces_error(self):
        with mock.patch.object(ai_match, "_ai_chat_json", return_value=(None, "AI 请求失败：boom")):
            result = ai_match.ai_match_generate_query({"name": "X"}, runtime=_runtime())
        self.assertFalse(result["ok"])
        self.assertIn("boom", result["error"])


class AiMatchSelectCandidateTest(unittest.TestCase):
    def test_select_ok(self):
        candidates = [_fake_candidate(), _fake_candidate(tmdb_id=604, title="The Matrix Reloaded")]
        with mock.patch.object(
            ai_match,
            "_ai_chat_json",
            return_value=({"tmdb_id": 604, "media_type": "movie", "confidence": 88, "reason": "续集"}, ""),
        ):
            result = ai_match.ai_match_select_candidate({"name": "黑客帝国2"}, candidates, runtime=_runtime())
        self.assertTrue(result["ok"])
        self.assertEqual(result["tmdb_id"], 604)
        self.assertEqual(result["confidence"], 88)

    def test_select_rejects_unknown_id(self):
        with mock.patch.object(ai_match, "_ai_chat_json", return_value=({"tmdb_id": 999, "confidence": 90}, "")):
            result = ai_match.ai_match_select_candidate({"name": "X"}, [_fake_candidate()], runtime=_runtime())
        self.assertFalse(result["ok"])

    def test_select_empty_candidates(self):
        result = ai_match.ai_match_select_candidate({"name": "X"}, [], runtime=_runtime())
        self.assertFalse(result["ok"])

    def test_select_clamps_confidence(self):
        with mock.patch.object(ai_match, "_ai_chat_json", return_value=({"tmdb_id": 603, "confidence": 250}, "")):
            result = ai_match.ai_match_select_candidate({"name": "X"}, [_fake_candidate()], runtime=_runtime())
        self.assertEqual(result["confidence"], 100)

    def test_select_surfaces_error(self):
        with mock.patch.object(ai_match, "_ai_chat_json", return_value=(None, "AI 接口返回 HTTP 500")):
            result = ai_match.ai_match_select_candidate({"name": "X"}, [_fake_candidate()], runtime=_runtime())
        self.assertFalse(result["ok"])
        self.assertIn("HTTP 500", result["error"])


class AiMatchFallbackIntegrationTest(unittest.TestCase):
    def _cfg(self):
        return {
            "ai_match_enabled": True,
            "ai_match_base_url": "http://x/v1",
            "ai_match_api_key": "k",
            "ai_match_model": "m",
            "ai_match_timeout_seconds": 5,
            "ai_match_temperature": 0,
            "ai_match_max_concurrency": 3,
            "tmdb_enabled": True,
            "tmdb_api_key": "key",
        }

    def test_use_ai_override(self):
        self.assertFalse(scraper._scraper_ai_match_requested({"use_ai": False}, self._cfg()))
        self.assertTrue(scraper._scraper_ai_match_requested({"use_ai": True}, {"ai_match_enabled": False}))
        self.assertTrue(scraper._scraper_ai_match_requested({}, self._cfg()))
        self.assertFalse(scraper._scraper_ai_match_requested({}, {}))

    def test_fallback_merges_ai_candidate_without_autopick(self):
        results = [
            {"item_index": 1, "ok": True, "status": "manual", "confidence": 0, "candidates": [], "media_type": "movie", "year": ""},
            {"item_index": 2, "ok": True, "status": "auto", "confidence": 90, "candidates": [], "media_type": "movie", "year": ""},
        ]
        raw_items = [
            {"item_index": 1, "name": "黑客帝国4", "entry": {"id": "1", "name": "黑客帝国4"}, "files": []},
            {"item_index": 2, "name": "已匹配", "entry": {"id": "2", "name": "已匹配"}, "files": []},
        ]
        candidate = _fake_candidate(tmdb_id=603, title="The Matrix", year="1999")
        with mock.patch(
            "app.services.ai_match.ai_match_generate_query",
            return_value={"ok": True, "keyword": "黑客帝国", "year": "1999", "media_type": "movie", "error": ""},
        ), mock.patch(
            "app.services.ai_match.ai_match_select_candidate",
            return_value={"ok": True, "candidate": candidate, "tmdb_id": 603, "media_type": "movie", "confidence": 92, "reason": "片名匹配", "error": ""},
        ), mock.patch.object(scraper, "_search_batch_tmdb_candidates", return_value=[candidate]):
            scraper._apply_ai_match_fallback(results, raw_items, {}, self._cfg())

        target = results[0]
        self.assertEqual(target["status"], "suggest")
        self.assertEqual(target["ai_keyword"], "黑客帝国")
        self.assertEqual(target["ai_confidence"], 92)
        self.assertEqual(target["ai_reason"], "片名匹配")
        self.assertEqual(target["candidates"][0]["id"], 603)
        self.assertEqual(target["candidates"][0]["source"], "ai")
        self.assertNotIn("auto_pick", target)
        self.assertEqual(results[1]["status"], "auto")
        self.assertNotIn("ai_keyword", results[1])

    def test_fallback_config_error_annotates_only_targets(self):
        results = [
            {"item_index": 1, "ok": True, "status": "manual", "candidates": [], "media_type": "movie", "year": ""},
            {"item_index": 2, "ok": True, "status": "auto", "candidates": [], "media_type": "movie", "year": ""},
        ]
        raw_items = [
            {"item_index": 1, "name": "X", "entry": {"id": "1", "name": "X"}, "files": []},
            {"item_index": 2, "name": "Y", "entry": {"id": "2", "name": "Y"}, "files": []},
        ]
        cfg = self._cfg()
        cfg["ai_match_model"] = ""
        scraper._apply_ai_match_fallback(results, raw_items, {}, cfg)
        self.assertIn("ai_error", results[0])
        self.assertNotIn("ai_error", results[1])

    def test_fallback_disabled_does_nothing(self):
        results = [{"item_index": 1, "ok": True, "status": "manual", "candidates": [], "media_type": "movie", "year": ""}]
        raw_items = [{"item_index": 1, "name": "X", "entry": {"id": "1", "name": "X"}, "files": []}]
        scraper._apply_ai_match_fallback(results, raw_items, {}, {"ai_match_enabled": False})
        self.assertNotIn("ai_keyword", results[0])
        self.assertNotIn("ai_error", results[0])

    def test_fallback_ai_failure_keeps_candidates(self):
        original = _fake_candidate(tmdb_id=111, title="Original")
        results = [
            {"item_index": 1, "ok": True, "status": "suggest", "candidates": [original], "media_type": "movie", "year": ""}
        ]
        raw_items = [{"item_index": 1, "name": "X", "entry": {"id": "1", "name": "X"}, "files": []}]
        with mock.patch(
            "app.services.ai_match.ai_match_generate_query",
            return_value={"ok": False, "keyword": "", "year": "", "media_type": "", "error": "AI 请求失败"},
        ):
            scraper._apply_ai_match_fallback(results, raw_items, {}, self._cfg())
        self.assertEqual(results[0]["ai_error"], "AI 请求失败")
        self.assertEqual(results[0]["candidates"][0]["id"], 111)

    def test_fallback_select_failure_still_merges_keyword_candidates(self):
        candidate = _fake_candidate(tmdb_id=603, title="The Matrix", year="1999")
        results = [
            {"item_index": 1, "ok": True, "status": "manual", "candidates": [], "media_type": "movie", "year": ""}
        ]
        raw_items = [{"item_index": 1, "name": "黑客帝国", "entry": {"id": "1", "name": "黑客帝国"}, "files": []}]
        with mock.patch(
            "app.services.ai_match.ai_match_generate_query",
            return_value={"ok": True, "keyword": "黑客帝国", "year": "1999", "media_type": "movie", "error": ""},
        ), mock.patch(
            "app.services.ai_match.ai_match_select_candidate",
            return_value={"ok": False, "candidate": {}, "error": "AI 候选选择失败"},
        ), mock.patch.object(scraper, "_search_batch_tmdb_candidates", return_value=[candidate]):
            scraper._apply_ai_match_fallback(results, raw_items, {}, self._cfg())

        self.assertEqual(results[0]["status"], "suggest")
        self.assertEqual(results[0]["candidates"][0]["id"], 603)
        self.assertEqual(results[0]["ai_error"], "AI 候选选择失败")
        self.assertNotIn("ai_selected", results[0])

    def test_fallback_parallel_targets(self):
        results = [
            {"item_index": index, "ok": True, "status": "manual", "candidates": [], "media_type": "movie", "year": ""}
            for index in (1, 2)
        ]
        raw_items = [
            {"item_index": index, "name": f"片{index}", "entry": {"id": str(index), "name": f"片{index}"}, "files": []}
            for index in (1, 2)
        ]
        candidate = _fake_candidate(tmdb_id=603, title="The Matrix", year="1999")
        with mock.patch(
            "app.services.ai_match.ai_match_generate_query",
            return_value={"ok": True, "keyword": "黑客帝国", "year": "1999", "media_type": "movie", "error": ""},
        ), mock.patch(
            "app.services.ai_match.ai_match_select_candidate",
            return_value={"ok": True, "candidate": candidate, "tmdb_id": 603, "media_type": "movie", "confidence": 80, "reason": "ok", "error": ""},
        ), mock.patch.object(scraper, "_search_batch_tmdb_candidates", return_value=[candidate]):
            scraper._apply_ai_match_fallback(results, raw_items, {}, self._cfg())
        for result in results:
            self.assertEqual(result["status"], "suggest")
            self.assertEqual(result["ai_keyword"], "黑客帝国")
            self.assertNotIn("auto_pick", result)


class IdentifyBatchWiringTest(unittest.TestCase):
    def test_batch_identify_invokes_ai_fallback(self):
        raw = [{"item_index": 1, "name": "X", "entry": {"id": "1", "name": "X"}, "files": []}]
        payload = {"provider": "115", "items": raw}
        item_result = {
            "item_index": 1,
            "ok": True,
            "status": "manual",
            "candidates": [],
            "media_type": "movie",
            "year": "",
        }
        seen = {}

        def fake_apply(results, raw_items, request_payload, cfg):
            seen["applied"] = True
            seen["results"] = results
            seen["raw_items"] = raw_items

        with mock.patch.object(scraper, "get_config", return_value={"tmdb_enabled": True, "tmdb_api_key": "k"}), \
                mock.patch.object(scraper, "validate_tmdb_runtime_config", return_value=None), \
                mock.patch.object(scraper, "_identify_scraper_batch_item", return_value=dict(item_result)), \
                mock.patch.object(scraper, "_apply_ai_match_fallback", side_effect=fake_apply):
            output = scraper.identify_scraper_batch_items(payload)

        self.assertTrue(seen.get("applied"))
        self.assertEqual(seen["results"][0]["item_index"], 1)
        self.assertEqual(seen["raw_items"], raw)
        self.assertEqual(output["results"][0]["item_index"], 1)


if __name__ == "__main__":
    unittest.main()
