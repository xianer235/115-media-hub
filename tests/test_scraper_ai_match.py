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
        "thinking_mode": "auto",
        "min_confidence": 0,
        "cache_ttl_seconds": 0,
    }


def _cached_runtime():
    runtime = dict(_runtime())
    runtime["cache_ttl_seconds"] = 3600
    return runtime


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


def _low_score_candidates():
    # 标题与关键词完全无关 -> 打分低且接近，确保走 AI 二次选择而不是跳过。
    return [
        _fake_candidate(tmdb_id=603, title="Totally Unrelated", year="1999"),
        _fake_candidate(tmdb_id=604, title="Another Unrelated", year="2001"),
    ]


class _FakeResponse:
    def __init__(self, status_code, payload=None, text="", headers=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _ok_response(content='{"keyword": "X"}', usage=None):
    payload = {"choices": [{"message": {"content": content}}]}
    if usage is not None:
        payload["usage"] = usage
    return _FakeResponse(200, payload)


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
            "ai_match_model": "deepseek-flash",
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
        self.assertEqual(cfg["ai_match_thinking_mode"], "auto")
        self.assertEqual(cfg["ai_match_min_confidence"], 60)
        self.assertEqual(cfg["ai_match_cache_ttl_hours"], 24)

    def test_min_confidence_legacy_default_upgraded(self):
        # 旧默认 0（不过滤）会在归一化时升级为 60；显式设置的非 0 值保持不变。
        self.assertEqual(core.normalize_config({"ai_match_min_confidence": 0})["ai_match_min_confidence"], 60)
        self.assertEqual(core.normalize_config({"ai_match_min_confidence": 80})["ai_match_min_confidence"], 80)

    def test_normalize_config_clamps(self):
        cfg = core.normalize_config(
            {
                "ai_match_timeout_seconds": 999,
                "ai_match_temperature": 9,
                "ai_match_max_concurrency": 100,
                "ai_match_min_confidence": 999,
                "ai_match_cache_ttl_hours": 99999,
                "ai_match_base_url": "http://x/v1/",
            }
        )
        self.assertEqual(cfg["ai_match_timeout_seconds"], 120)
        self.assertEqual(cfg["ai_match_temperature"], 2.0)
        self.assertEqual(cfg["ai_match_max_concurrency"], 8)
        self.assertEqual(cfg["ai_match_min_confidence"], 100)
        self.assertEqual(cfg["ai_match_cache_ttl_hours"], 720)
        self.assertEqual(cfg["ai_match_base_url"], "http://x/v1")

    def test_thinking_mode_default_and_legacy_migration(self):
        self.assertEqual(ai_match.build_ai_match_runtime_config({})["thinking_mode"], "auto")
        self.assertEqual(
            ai_match.build_ai_match_runtime_config({"ai_match_thinking_mode": "disabled"})["thinking_mode"],
            "disabled",
        )
        # 兼容 0.11.1 的布尔键：false -> enabled（不干预），true -> auto
        self.assertEqual(
            ai_match.build_ai_match_runtime_config({"ai_match_disable_thinking": False})["thinking_mode"],
            "enabled",
        )
        self.assertEqual(
            ai_match.build_ai_match_runtime_config({"ai_match_disable_thinking": True})["thinking_mode"],
            "auto",
        )
        migrated = core.normalize_config({"ai_match_disable_thinking": False})
        self.assertEqual(migrated["ai_match_thinking_mode"], "enabled")
        self.assertNotIn("ai_match_disable_thinking", migrated)

    def test_runtime_cache_and_confidence_defaults(self):
        runtime = ai_match.build_ai_match_runtime_config({})
        self.assertEqual(runtime["min_confidence"], 60)
        self.assertEqual(runtime["cache_ttl_hours"], 24)
        self.assertEqual(runtime["cache_ttl_seconds"], 24 * 3600)

    def test_base_url_normalization(self):
        cases = {
            "https://api.deepseek.com/": "https://api.deepseek.com",
            "https://api.deepseek.com/v1/": "https://api.deepseek.com/v1",
            "https://api.deepseek.com/chat/completions": "https://api.deepseek.com",
            "https://api.deepseek.com/v1/chat/completions": "https://api.deepseek.com/v1",
        }
        for raw, expected in cases.items():
            self.assertEqual(
                ai_match.build_ai_match_runtime_config({"ai_match_base_url": raw})["base_url"],
                expected,
            )

    def test_request_url_is_not_doubled(self):
        cfg = {
            "ai_match_enabled": True,
            "ai_match_base_url": "https://api.deepseek.com/chat/completions",
            "ai_match_api_key": "k",
            "ai_match_model": "deepseek-flash",
            "ai_match_cache_ttl_hours": 0,
        }
        runtime = ai_match.build_ai_match_runtime_config(cfg)
        with mock.patch.object(ai_match.requests, "post", return_value=_ok_response()) as post:
            ai_match._ai_chat_json(runtime, [])
        self.assertEqual(post.call_args.args[0], "https://api.deepseek.com/chat/completions")

    def test_validate_rejects_anthropic_endpoint_and_bad_scheme(self):
        base = {
            "ai_match_enabled": True,
            "ai_match_base_url": "https://api.deepseek.com/anthropic",
            "ai_match_api_key": "sk-test",
            "ai_match_model": "deepseek-flash",
        }
        message = ai_match.validate_ai_match_runtime_config(base)
        self.assertIn("Anthropic", message)
        bad_scheme = {**base, "ai_match_base_url": "api.deepseek.com"}
        scheme_message = ai_match.validate_ai_match_runtime_config(bad_scheme)
        self.assertIn("http", scheme_message)

    def test_validate_can_skip_enabled_check(self):
        cfg = {
            "ai_match_enabled": False,
            "ai_match_base_url": "https://api.deepseek.com",
            "ai_match_api_key": "sk-test",
            "ai_match_model": "deepseek-flash",
        }
        self.assertEqual(ai_match.validate_ai_match_runtime_config(cfg), "AI 刮削辅助未启用")
        self.assertIsNone(ai_match.validate_ai_match_runtime_config(cfg, require_enabled=False))


class AiMatchChatJsonTest(unittest.TestCase):
    def test_chat_json_ok(self):
        with mock.patch.object(ai_match.requests, "post", return_value=_ok_response()) as post:
            data, error, usage = ai_match._ai_chat_json(_runtime(), [{"role": "user", "content": "hi"}])
        self.assertEqual(error, "")
        self.assertEqual(data, {"keyword": "X"})
        self.assertEqual(post.call_count, 1)
        self.assertEqual(usage["total_tokens"], 0)

    def test_chat_json_returns_usage(self):
        response = _ok_response(
            usage={
                "prompt_tokens": 1200,
                "completion_tokens": 40,
                "total_tokens": 1240,
                "prompt_cache_hit_tokens": 1000,
            }
        )
        with mock.patch.object(ai_match.requests, "post", return_value=response):
            _data, error, usage = ai_match._ai_chat_json(_runtime(), [])
        self.assertEqual(error, "")
        self.assertEqual(usage["prompt_tokens"], 1200)
        self.assertEqual(usage["completion_tokens"], 40)
        self.assertEqual(usage["prompt_cache_hit_tokens"], 1000)
        self.assertEqual(usage["total_tokens"], 1240)

    def test_chat_json_retries_without_json_mode_on_400(self):
        first = _FakeResponse(400, text="response_format not supported")
        with mock.patch.object(ai_match.requests, "post", side_effect=[first, _ok_response()]) as post, \
                mock.patch.object(ai_match.time, "sleep") as sleep:
            data, error, _usage = ai_match._ai_chat_json(_runtime(), [{"role": "user", "content": "hi"}])
        self.assertEqual(error, "")
        self.assertEqual(data, {"keyword": "X"})
        self.assertEqual(post.call_count, 2)
        self.assertNotIn("response_format", post.call_args_list[1].kwargs["json"])
        sleep.assert_not_called()

    def test_chat_json_retries_on_500(self):
        responses = [_FakeResponse(500, text="boom"), _ok_response()]
        with mock.patch.object(ai_match.requests, "post", side_effect=responses) as post, \
                mock.patch.object(ai_match.time, "sleep") as sleep:
            data, error, _usage = ai_match._ai_chat_json(_runtime(), [])
        self.assertEqual(error, "")
        self.assertEqual(data, {"keyword": "X"})
        self.assertEqual(post.call_count, 2)
        sleep.assert_called()

    def test_chat_json_retries_on_timeout(self):
        with mock.patch.object(
            ai_match.requests,
            "post",
            side_effect=[ai_match.requests.RequestException("timeout"), _ok_response()],
        ) as post, mock.patch.object(ai_match.time, "sleep"):
            _data, error, _usage = ai_match._ai_chat_json(_runtime(), [])
        self.assertEqual(error, "")
        self.assertEqual(post.call_count, 2)

    def test_chat_json_gives_up_after_max_attempts(self):
        with mock.patch.object(ai_match.requests, "post", return_value=_FakeResponse(503, text="down")) as post, \
                mock.patch.object(ai_match.time, "sleep"):
            data, error, _usage = ai_match._ai_chat_json(_runtime(), [])
        self.assertIsNone(data)
        self.assertIn("HTTP 503", error)
        self.assertEqual(post.call_count, ai_match.AI_MATCH_MAX_ATTEMPTS)

    def test_chat_json_does_not_retry_plain_4xx(self):
        with mock.patch.object(ai_match.requests, "post", return_value=_FakeResponse(401, text="unauthorized")) as post, \
                mock.patch.object(ai_match.time, "sleep") as sleep:
            data, error, _usage = ai_match._ai_chat_json(_runtime(), [])
        self.assertIsNone(data)
        self.assertIn("HTTP 401", error)
        self.assertEqual(post.call_count, 1)
        sleep.assert_not_called()

    def test_chat_json_uses_retry_after_header(self):
        responses = [_FakeResponse(429, text="slow down", headers={"Retry-After": "3"}), _ok_response()]
        with mock.patch.object(ai_match.requests, "post", side_effect=responses), \
                mock.patch.object(ai_match.time, "sleep") as sleep:
            _data, error, _usage = ai_match._ai_chat_json(_runtime(), [])
        self.assertEqual(error, "")
        sleep.assert_called_once_with(3.0)

    def test_chat_json_timeout_error_message(self):
        with mock.patch.object(ai_match.requests, "post", side_effect=ai_match.requests.RequestException("timeout")), \
                mock.patch.object(ai_match.time, "sleep"):
            data, error, _usage = ai_match._ai_chat_json(_runtime(), [])
        self.assertIsNone(data)
        self.assertIn("AI 请求失败", error)


class AiMatchThinkingControlTest(unittest.TestCase):
    def _deepseek_runtime(self, thinking_mode="auto"):
        runtime = dict(_runtime())
        runtime["base_url"] = "https://api.deepseek.com/v1"
        runtime["model"] = "deepseek-flash"
        runtime["thinking_mode"] = thinking_mode
        return runtime

    def test_supports_thinking_control_by_host_or_model(self):
        self.assertTrue(
            ai_match._supports_thinking_control({"base_url": "https://api.deepseek.com/v1", "model": "x"})
        )
        self.assertTrue(
            ai_match._supports_thinking_control({"base_url": "http://local/v1", "model": "deepseek-flash"})
        )
        self.assertFalse(
            ai_match._supports_thinking_control({"base_url": "http://127.0.0.1:11434/v1", "model": "qwen2.5:7b"})
        )

    def test_auto_sends_disabled_for_deepseek(self):
        with mock.patch.object(ai_match.requests, "post", return_value=_ok_response()) as post:
            ai_match._ai_chat_json(self._deepseek_runtime(), [{"role": "user", "content": "hi"}])
        self.assertEqual(post.call_args.kwargs["json"]["thinking"], {"type": "disabled"})

    def test_auto_omits_thinking_for_unknown_endpoint(self):
        with mock.patch.object(ai_match.requests, "post", return_value=_ok_response()) as post:
            ai_match._ai_chat_json(_runtime(), [{"role": "user", "content": "hi"}])
        self.assertNotIn("thinking", post.call_args.kwargs["json"])

    def test_enabled_mode_never_sends_thinking(self):
        with mock.patch.object(ai_match.requests, "post", return_value=_ok_response()) as post:
            ai_match._ai_chat_json(self._deepseek_runtime("enabled"), [{"role": "user", "content": "hi"}])
        self.assertNotIn("thinking", post.call_args.kwargs["json"])

    def test_disabled_mode_sends_even_for_unknown_endpoint(self):
        runtime = dict(_runtime())
        runtime["thinking_mode"] = "disabled"
        with mock.patch.object(ai_match.requests, "post", return_value=_ok_response()) as post:
            ai_match._ai_chat_json(runtime, [{"role": "user", "content": "hi"}])
        self.assertEqual(post.call_args.kwargs["json"]["thinking"], {"type": "disabled"})

    def test_prompts_contain_lowercase_json(self):
        self.assertIn("json", ai_match._QUERY_SYSTEM_PROMPT)
        self.assertIn("json", ai_match._SELECT_SYSTEM_PROMPT)


class AiMatchCacheTest(unittest.TestCase):
    def setUp(self):
        ai_match.clear_ai_match_cache()

    def tearDown(self):
        ai_match.clear_ai_match_cache()

    def test_query_cache_hit_avoids_second_call(self):
        with mock.patch.object(ai_match.requests, "post", return_value=_ok_response()) as post:
            first = ai_match.ai_match_generate_query({"name": "片"}, runtime=_cached_runtime())
            second = ai_match.ai_match_generate_query({"name": "片"}, runtime=_cached_runtime())
        self.assertTrue(first["ok"])
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(second["keyword"], "X")
        self.assertEqual(post.call_count, 1)

    def test_query_cache_disabled_calls_every_time(self):
        with mock.patch.object(ai_match.requests, "post", return_value=_ok_response()) as post:
            ai_match.ai_match_generate_query({"name": "片"}, runtime=_runtime())
            ai_match.ai_match_generate_query({"name": "片"}, runtime=_runtime())
        self.assertEqual(post.call_count, 2)

    def test_cached_result_reports_cache_hit_usage(self):
        with mock.patch.object(ai_match.requests, "post", return_value=_ok_response()):
            ai_match.ai_match_generate_query({"name": "片"}, runtime=_cached_runtime())
            second = ai_match.ai_match_generate_query({"name": "片"}, runtime=_cached_runtime())
        self.assertEqual(second["usage"]["cache_hits"], 1)
        self.assertEqual(second["usage"]["calls"], 0)

    def test_select_cache_key_includes_candidates(self):
        candidates = [_fake_candidate(tmdb_id=603), _fake_candidate(tmdb_id=604, title="Sequel")]
        first_response = _FakeResponse(200, {"choices": [{"message": {"content": '{"tmdb_id": 603, "confidence": 80}'}}]})
        second_response = _FakeResponse(200, {"choices": [{"message": {"content": '{"tmdb_id": 604, "confidence": 80}'}}]})
        with mock.patch.object(ai_match.requests, "post", side_effect=[first_response, second_response]) as post:
            first = ai_match.ai_match_select_candidate({"name": "片"}, candidates, runtime=_cached_runtime())
            repeat = ai_match.ai_match_select_candidate({"name": "片"}, candidates, runtime=_cached_runtime())
            other = ai_match.ai_match_select_candidate({"name": "片"}, [candidates[0]], runtime=_cached_runtime())
        self.assertEqual(post.call_count, 2)
        self.assertTrue(repeat["cached"])
        self.assertFalse(other["cached"])

    def test_clear_cache(self):
        with mock.patch.object(ai_match.requests, "post", return_value=_ok_response()):
            ai_match.ai_match_generate_query({"name": "片"}, runtime=_cached_runtime())
        self.assertEqual(ai_match.clear_ai_match_cache(), 1)


class AiMatchUsageTest(unittest.TestCase):
    def setUp(self):
        ai_match.reset_ai_match_usage()
        ai_match.clear_ai_match_cache()

    def tearDown(self):
        ai_match.reset_ai_match_usage()
        ai_match.clear_ai_match_cache()

    def test_record_and_reset_usage(self):
        ai_match.record_ai_match_usage(
            {
                "calls": 1,
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "prompt_cache_hit_tokens": 60,
            },
            ok=True,
            latency_ms=123,
        )
        ai_match.record_ai_match_usage({"calls": 1}, ok=False, error="boom", latency_ms=45)
        usage = ai_match.get_ai_match_usage()
        self.assertEqual(usage["calls"], 2)
        self.assertEqual(usage["prompt_tokens"], 100)
        self.assertEqual(usage["completion_tokens"], 20)
        self.assertEqual(usage["total_tokens"], 120)
        self.assertEqual(usage["prompt_cache_hit_tokens"], 60)
        self.assertEqual(usage["last_latency_ms"], 45)
        self.assertEqual(usage["last_error"], "boom")
        self.assertTrue(usage["last_call_at"])
        reset = ai_match.reset_ai_match_usage()
        self.assertEqual(reset["calls"], 0)
        self.assertEqual(reset["last_error"], "")
        self.assertEqual(reset["total_tokens"], 0)

    def test_real_call_is_counted(self):
        response = _ok_response(usage={"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12})
        with mock.patch.object(ai_match.requests, "post", return_value=response):
            ai_match.ai_match_generate_query({"name": "片"}, runtime=_runtime())
        usage = ai_match.get_ai_match_usage()
        self.assertEqual(usage["calls"], 1)
        self.assertEqual(usage["total_tokens"], 12)

    def test_cache_hit_counted_as_cache_hit(self):
        with mock.patch.object(ai_match.requests, "post", return_value=_ok_response()):
            ai_match.ai_match_generate_query({"name": "片"}, runtime=_cached_runtime())
            ai_match.ai_match_generate_query({"name": "片"}, runtime=_cached_runtime())
        usage = ai_match.get_ai_match_usage()
        self.assertEqual(usage["calls"], 1)
        self.assertEqual(usage["cache_hits"], 1)


class AiMatchTestConnectionTest(unittest.TestCase):
    def setUp(self):
        ai_match.reset_ai_match_usage()
        ai_match.clear_ai_match_cache()

    def tearDown(self):
        ai_match.reset_ai_match_usage()
        ai_match.clear_ai_match_cache()

    def _cfg(self, **overrides):
        cfg = {
            # 刻意保持 enabled=False：测试连接不应受「启用」开关限制。
            "ai_match_enabled": False,
            "ai_match_base_url": "https://api.deepseek.com",
            "ai_match_api_key": "sk-test",
            "ai_match_model": "deepseek-flash",
            "ai_match_cache_ttl_hours": 24,
        }
        cfg.update(overrides)
        return cfg

    def test_test_connection_ok(self):
        content = '{"keyword": "杂役女仆", "year": "2026", "media_type": "tv"}'
        with mock.patch.object(ai_match.requests, "post", return_value=_ok_response(content)) as post:
            result = ai_match.ai_match_test_connection(self._cfg())
        self.assertTrue(result["ok"])
        self.assertEqual(result["keyword"], "杂役女仆")
        self.assertEqual(result["year"], "2026")
        self.assertEqual(result["media_type"], "tv")
        self.assertEqual(result["model"], "deepseek-flash")
        self.assertTrue(result["thinking_disabled"])
        self.assertEqual(post.call_args.args[0], "https://api.deepseek.com/chat/completions")
        self.assertEqual(post.call_args.kwargs["json"]["thinking"], {"type": "disabled"})
        self.assertIn("usage", result)

    def test_test_connection_requires_fields(self):
        result = ai_match.ai_match_test_connection(self._cfg(ai_match_api_key=""))
        self.assertFalse(result["ok"])
        self.assertIn("API Key", result["error"])
        self.assertEqual(result["latency_ms"], 0)

    def test_test_connection_reports_http_error(self):
        with mock.patch.object(ai_match.requests, "post", return_value=_FakeResponse(401, text="unauthorized")), \
                mock.patch.object(ai_match.time, "sleep"):
            result = ai_match.ai_match_test_connection(self._cfg())
        self.assertFalse(result["ok"])
        self.assertIn("HTTP 401", result["error"])

    def test_test_connection_does_not_use_cache(self):
        content = '{"keyword": "杂役女仆", "year": "2026", "media_type": "tv"}'
        with mock.patch.object(ai_match.requests, "post", return_value=_ok_response(content)) as post:
            ai_match.ai_match_test_connection(self._cfg())
            ai_match.ai_match_test_connection(self._cfg())
        self.assertEqual(post.call_count, 2)


class AiMatchGenerateQueryTest(unittest.TestCase):
    def test_generate_query_ok(self):
        with mock.patch.object(
            ai_match,
            "_ai_chat_json",
            return_value=({"keyword": " 黑客帝国 ", "year": "1999", "media_type": "movie"}, "", {}),
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
            return_value=({"keyword": "X", "year": "19", "media_type": "anime"}, "", {}),
        ):
            result = ai_match.ai_match_generate_query({"name": "X"}, runtime=_runtime())
        self.assertEqual(result["year"], "")
        self.assertEqual(result["media_type"], "")

    def test_generate_query_empty_keyword(self):
        with mock.patch.object(ai_match, "_ai_chat_json", return_value=({"keyword": "   "}, "", {})):
            result = ai_match.ai_match_generate_query({"name": "X"}, runtime=_runtime())
        self.assertFalse(result["ok"])
        self.assertIn("关键词", result["error"])

    def test_generate_query_surfaces_error(self):
        with mock.patch.object(ai_match, "_ai_chat_json", return_value=(None, "AI 请求失败：boom", {})):
            result = ai_match.ai_match_generate_query({"name": "X"}, runtime=_runtime())
        self.assertFalse(result["ok"])
        self.assertIn("boom", result["error"])
        self.assertEqual(result["usage"]["calls"], 1)


class AiMatchSelectCandidateTest(unittest.TestCase):
    def test_select_ok(self):
        candidates = [_fake_candidate(), _fake_candidate(tmdb_id=604, title="The Matrix Reloaded")]
        with mock.patch.object(
            ai_match,
            "_ai_chat_json",
            return_value=({"tmdb_id": 604, "media_type": "movie", "confidence": 88, "reason": "续集"}, "", {}),
        ):
            result = ai_match.ai_match_select_candidate({"name": "黑客帝国2"}, candidates, runtime=_runtime())
        self.assertTrue(result["ok"])
        self.assertEqual(result["tmdb_id"], 604)
        self.assertEqual(result["confidence"], 88)

    def test_select_rejects_unknown_id(self):
        with mock.patch.object(ai_match, "_ai_chat_json", return_value=({"tmdb_id": 999, "confidence": 90}, "", {})):
            result = ai_match.ai_match_select_candidate({"name": "X"}, [_fake_candidate()], runtime=_runtime())
        self.assertFalse(result["ok"])

    def test_select_empty_candidates(self):
        result = ai_match.ai_match_select_candidate({"name": "X"}, [], runtime=_runtime())
        self.assertFalse(result["ok"])

    def test_select_clamps_confidence(self):
        with mock.patch.object(ai_match, "_ai_chat_json", return_value=({"tmdb_id": 603, "confidence": 250}, "", {})):
            result = ai_match.ai_match_select_candidate({"name": "X"}, [_fake_candidate()], runtime=_runtime())
        self.assertEqual(result["confidence"], 100)

    def test_select_surfaces_error(self):
        with mock.patch.object(ai_match, "_ai_chat_json", return_value=(None, "AI 接口返回 HTTP 500", {})):
            result = ai_match.ai_match_select_candidate({"name": "X"}, [_fake_candidate()], runtime=_runtime())
        self.assertFalse(result["ok"])
        self.assertIn("HTTP 500", result["error"])


def _fallback_cfg(**overrides):
    cfg = {
        "ai_match_enabled": True,
        "ai_match_base_url": "http://x/v1",
        "ai_match_api_key": "k",
        "ai_match_model": "m",
        "ai_match_timeout_seconds": 5,
        "ai_match_temperature": 0,
        "ai_match_max_concurrency": 3,
        "ai_match_min_confidence": 0,
        "ai_match_cache_ttl_hours": 24,
        "ai_match_thinking_mode": "auto",
        "tmdb_enabled": True,
        "tmdb_api_key": "key",
    }
    cfg.update(overrides)
    return cfg


def _manual_result(item_index=1):
    return {
        "item_index": item_index,
        "ok": True,
        "status": "manual",
        "confidence": 0,
        "candidates": [],
        "media_type": "movie",
        "year": "",
    }


def _raw_item(item_index=1, name="黑客帝国4"):
    return {"item_index": item_index, "name": name, "entry": {"id": str(item_index), "name": name}, "files": []}


def _generated_ok(usage=None):
    return {
        "ok": True,
        "keyword": "黑客帝国",
        "year": "1999",
        "media_type": "movie",
        "error": "",
        "cached": False,
        "usage": {"calls": 1} if usage is None else usage,
    }


def _selected_ok(candidate, confidence=92, reason="片名匹配", usage=None):
    return {
        "ok": True,
        "candidate": candidate,
        "tmdb_id": int(candidate.get("id", 0) or 0),
        "media_type": "movie",
        "confidence": confidence,
        "reason": reason,
        "error": "",
        "cached": False,
        "usage": {"calls": 1} if usage is None else usage,
    }


class AiMatchFallbackIntegrationTest(unittest.TestCase):
    def setUp(self):
        ai_match.clear_ai_match_cache()

    def test_use_ai_override(self):
        self.assertFalse(scraper._scraper_ai_match_requested({"use_ai": False}, _fallback_cfg()))
        self.assertTrue(scraper._scraper_ai_match_requested({"use_ai": True}, {"ai_match_enabled": False}))
        self.assertTrue(scraper._scraper_ai_match_requested({}, _fallback_cfg()))
        self.assertFalse(scraper._scraper_ai_match_requested({}, {}))

    def test_fallback_merges_ai_candidate_without_autopick(self):
        results = [_manual_result(1), {**_manual_result(2), "status": "auto", "confidence": 90}]
        raw_items = [_raw_item(1), _raw_item(2, name="已匹配")]
        candidate = _fake_candidate(tmdb_id=603)
        with mock.patch(
            "app.services.ai_match.ai_match_generate_query",
            return_value=_generated_ok(),
        ), mock.patch(
            "app.services.ai_match.ai_match_select_candidate",
            return_value=_selected_ok(candidate),
        ), mock.patch.object(scraper, "_search_batch_tmdb_candidates", return_value=_low_score_candidates()):
            state = scraper._apply_ai_match_fallback(results, raw_items, {}, _fallback_cfg())

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
        self.assertEqual(state["usage"]["calls"], 2)
        self.assertTrue(state["requested"])
        self.assertEqual(state["config_error"], "")

    def test_fallback_skips_select_for_single_candidate(self):
        results = [_manual_result(1)]
        raw_items = [_raw_item(1)]
        candidate = _fake_candidate(tmdb_id=603)
        with mock.patch(
            "app.services.ai_match.ai_match_generate_query",
            return_value=_generated_ok(),
        ), mock.patch(
            "app.services.ai_match.ai_match_select_candidate",
            side_effect=AssertionError("不应调用二次选择"),
        ) as select, mock.patch.object(scraper, "_search_batch_tmdb_candidates", return_value=[candidate]):
            state = scraper._apply_ai_match_fallback(results, raw_items, {}, _fallback_cfg())

        select.assert_not_called()
        self.assertTrue(results[0]["ai_skipped_select"])
        self.assertEqual(results[0]["status"], "suggest")
        self.assertEqual(results[0]["ai_selected"]["id"], 603)
        self.assertEqual(state["usage"]["calls"], 1)

    def test_fallback_min_confidence_rejects_low_confidence(self):
        results = [_manual_result(1)]
        raw_items = [_raw_item(1)]
        candidate = _fake_candidate(tmdb_id=603)
        with mock.patch(
            "app.services.ai_match.ai_match_generate_query",
            return_value=_generated_ok(),
        ), mock.patch(
            "app.services.ai_match.ai_match_select_candidate",
            return_value=_selected_ok(candidate, confidence=40),
        ), mock.patch.object(scraper, "_search_batch_tmdb_candidates", return_value=_low_score_candidates()):
            scraper._apply_ai_match_fallback(results, raw_items, {}, _fallback_cfg(ai_match_min_confidence=90))

        self.assertEqual(results[0]["ai_low_confidence"], 40)
        self.assertNotIn("ai_selected", results[0])
        self.assertEqual(results[0]["status"], "manual")

    def test_fallback_prefers_deterministic_year_over_ai_year(self):
        # 文件名确定性年份（2024）比 AI 给出的年份（1999）更可靠，搜索要用确定性年份。
        results = [{**_manual_result(1), "year": "2024"}]
        raw_items = [_raw_item(1)]
        search_calls = []
        candidate = _fake_candidate(tmdb_id=603, year="2024")

        def fake_search(query, media_type, year, cfg):
            search_calls.append((query, media_type, year))
            return _low_score_candidates()

        with mock.patch(
            "app.services.ai_match.ai_match_generate_query",
            return_value=_generated_ok(),
        ), mock.patch(
            "app.services.ai_match.ai_match_select_candidate",
            return_value=_selected_ok(candidate),
        ), mock.patch.object(scraper, "_search_batch_tmdb_candidates", side_effect=fake_search):
            scraper._apply_ai_match_fallback(results, raw_items, {}, _fallback_cfg())

        self.assertEqual(search_calls[0][2], "2024")
        self.assertEqual(results[0]["ai_selected"]["id"], 603)

    def test_fallback_rejects_ai_candidate_with_conflicting_year(self):
        # 已知条目年份 2024，AI 却选了 2023 的候选：直接不采纳，避免同名异年错配。
        results = [{**_manual_result(1), "year": "2024"}]
        raw_items = [_raw_item(1)]
        conflicting = _fake_candidate(tmdb_id=1171826, title="为乐而生", year="2023")
        other = _fake_candidate(tmdb_id=603, title="Musica", year="2023")
        with mock.patch(
            "app.services.ai_match.ai_match_generate_query",
            return_value=_generated_ok(),
        ), mock.patch(
            "app.services.ai_match.ai_match_select_candidate",
            return_value=_selected_ok(conflicting, confidence=95),
        ), mock.patch.object(scraper, "_search_batch_tmdb_candidates", return_value=[conflicting, other]):
            scraper._apply_ai_match_fallback(results, raw_items, {}, _fallback_cfg())

        self.assertTrue(results[0].get("ai_year_conflict"))
        self.assertNotIn("ai_selected", results[0])
        self.assertEqual(results[0]["status"], "manual")

    def test_fallback_aggregates_usage(self):
        results = [_manual_result(1)]
        raw_items = [_raw_item(1)]
        candidate = _fake_candidate(tmdb_id=603)
        generated_usage = {"prompt_tokens": 1000, "completion_tokens": 20, "total_tokens": 1020, "calls": 1}
        select_usage = {
            "prompt_tokens": 800,
            "completion_tokens": 10,
            "total_tokens": 810,
            "prompt_cache_hit_tokens": 500,
            "calls": 1,
        }
        with mock.patch(
            "app.services.ai_match.ai_match_generate_query",
            return_value=_generated_ok(generated_usage),
        ), mock.patch(
            "app.services.ai_match.ai_match_select_candidate",
            return_value=_selected_ok(candidate, usage=select_usage),
        ), mock.patch.object(scraper, "_search_batch_tmdb_candidates", return_value=_low_score_candidates()):
            state = scraper._apply_ai_match_fallback(results, raw_items, {}, _fallback_cfg())

        self.assertEqual(state["usage"]["calls"], 2)
        self.assertEqual(state["usage"]["prompt_tokens"], 1800)
        self.assertEqual(state["usage"]["total_tokens"], 1830)
        self.assertEqual(state["usage"]["prompt_cache_hit_tokens"], 500)
        self.assertEqual(results[0]["ai_usage"]["calls"], 2)

    def test_fallback_config_error_annotates_only_targets(self):
        results = [_manual_result(1), {**_manual_result(2), "status": "auto"}]
        raw_items = [_raw_item(1), _raw_item(2, name="Y")]
        state = scraper._apply_ai_match_fallback(results, raw_items, {}, _fallback_cfg(ai_match_model=""))
        self.assertIn("ai_error", results[0])
        self.assertNotIn("ai_error", results[1])
        self.assertTrue(state["requested"])
        self.assertTrue(state["config_error"])
        self.assertEqual(state["usage"], {})

    def test_fallback_disabled_does_nothing(self):
        results = [_manual_result(1)]
        raw_items = [_raw_item(1)]
        state = scraper._apply_ai_match_fallback(results, raw_items, {}, {"ai_match_enabled": False})
        self.assertEqual(state, {"requested": False, "config_error": "", "usage": {}})
        self.assertNotIn("ai_keyword", results[0])
        self.assertNotIn("ai_error", results[0])

    def test_fallback_ai_failure_keeps_candidates(self):
        original = _fake_candidate(tmdb_id=111, title="Original")
        results = [{**_manual_result(1), "status": "suggest", "candidates": [original]}]
        raw_items = [_raw_item(1)]
        with mock.patch(
            "app.services.ai_match.ai_match_generate_query",
            return_value={"ok": False, "keyword": "", "year": "", "media_type": "", "error": "AI 请求失败", "usage": {"calls": 1}},
        ):
            scraper._apply_ai_match_fallback(results, raw_items, {}, _fallback_cfg())
        self.assertEqual(results[0]["ai_error"], "AI 请求失败")
        self.assertEqual(results[0]["candidates"][0]["id"], 111)

    def test_fallback_select_failure_still_merges_keyword_candidates(self):
        results = [_manual_result(1)]
        raw_items = [_raw_item(1)]
        with mock.patch(
            "app.services.ai_match.ai_match_generate_query",
            return_value=_generated_ok(),
        ), mock.patch(
            "app.services.ai_match.ai_match_select_candidate",
            return_value={"ok": False, "candidate": {}, "error": "AI 候选选择失败", "usage": {"calls": 1}},
        ), mock.patch.object(scraper, "_search_batch_tmdb_candidates", return_value=_low_score_candidates()):
            scraper._apply_ai_match_fallback(results, raw_items, {}, _fallback_cfg())

        self.assertEqual(results[0]["status"], "suggest")
        self.assertTrue(results[0]["candidates"])
        self.assertEqual(results[0]["ai_error"], "AI 候选选择失败")
        self.assertNotIn("ai_selected", results[0])

    def test_should_skip_ai_select_rules(self):
        self.assertFalse(scraper._should_skip_ai_select([]))
        self.assertTrue(scraper._should_skip_ai_select([{"score": 10}]))
        self.assertTrue(scraper._should_skip_ai_select([{"score": 90}, {"score": 10}]))
        self.assertFalse(scraper._should_skip_ai_select([{"score": 75}, {"score": 10}]))
        self.assertFalse(scraper._should_skip_ai_select([{"score": 90}, {"score": 85}]))

    def test_fallback_parallel_targets(self):
        results = [_manual_result(1), _manual_result(2)]
        raw_items = [_raw_item(1), _raw_item(2, name="片2")]
        candidate = _fake_candidate(tmdb_id=603)
        with mock.patch(
            "app.services.ai_match.ai_match_generate_query",
            return_value=_generated_ok(),
        ), mock.patch(
            "app.services.ai_match.ai_match_select_candidate",
            return_value=_selected_ok(candidate, confidence=80),
        ), mock.patch.object(scraper, "_search_batch_tmdb_candidates", return_value=_low_score_candidates()):
            scraper._apply_ai_match_fallback(results, raw_items, {}, _fallback_cfg())
        for result in results:
            self.assertEqual(result["status"], "suggest")
            self.assertEqual(result["ai_keyword"], "黑客帝国")
            self.assertNotIn("auto_pick", result)


class IdentifyBatchWiringTest(unittest.TestCase):
    def test_batch_identify_invokes_ai_fallback_and_reports_usage(self):
        raw = [_raw_item(1)]
        payload = {"provider": "115", "items": raw}
        item_result = _manual_result(1)
        seen = {}
        usage = {"calls": 2, "prompt_tokens": 100, "completion_tokens": 5, "total_tokens": 105, "cache_hits": 0, "prompt_cache_hit_tokens": 0}

        def fake_apply(results, raw_items, request_payload, cfg):
            seen["applied"] = True
            seen["results"] = results
            seen["raw_items"] = raw_items
            return {"requested": True, "config_error": "", "usage": usage}

        with mock.patch.object(scraper, "get_config", return_value={"tmdb_enabled": True, "tmdb_api_key": "k"}), \
                mock.patch.object(scraper, "validate_tmdb_runtime_config", return_value=None), \
                mock.patch.object(scraper, "_identify_scraper_batch_item", return_value=dict(item_result)), \
                mock.patch.object(scraper, "_apply_ai_match_fallback", side_effect=fake_apply):
            output = scraper.identify_scraper_batch_items(payload)

        self.assertTrue(seen.get("applied"))
        self.assertEqual(seen["results"][0]["item_index"], 1)
        self.assertEqual(seen["raw_items"], raw)
        self.assertEqual(output["results"][0]["item_index"], 1)
        self.assertEqual(output["ai_usage"], usage)
        self.assertTrue(output["ai_enabled"])
        self.assertNotIn("ai_config_error", output)

    def test_batch_identify_reports_ai_config_error(self):
        raw = [_raw_item(1)]
        payload = {"provider": "115", "items": raw}

        def fake_apply(results, raw_items, request_payload, cfg):
            return {"requested": True, "config_error": "AI 模型名称未填写", "usage": {}}

        with mock.patch.object(scraper, "get_config", return_value={"tmdb_enabled": True, "tmdb_api_key": "k"}), \
                mock.patch.object(scraper, "validate_tmdb_runtime_config", return_value=None), \
                mock.patch.object(scraper, "_identify_scraper_batch_item", return_value=_manual_result(1)), \
                mock.patch.object(scraper, "_apply_ai_match_fallback", side_effect=fake_apply):
            output = scraper.identify_scraper_batch_items(payload)

        self.assertTrue(output["ai_enabled"])
        self.assertEqual(output["ai_config_error"], "AI 模型名称未填写")
        self.assertNotIn("ai_usage", output)


if __name__ == "__main__":
    unittest.main()
