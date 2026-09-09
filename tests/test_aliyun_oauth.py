import io
import time
import unittest
import urllib.error
from unittest import mock

from app.providers import aliyun, aliyun_oauth


class AliyunOAuthSessionTest(unittest.TestCase):
    def test_create_session_returns_state_and_authorize_url(self):
        from urllib.parse import parse_qs, urlparse

        session = aliyun_oauth.create_aliyun_oauth_session()
        self.assertIn("state", session)
        self.assertIn("authorize_url", session)
        self.assertTrue(session["code_verifier"])
        self.assertIn("client_id=" + aliyun_oauth.ALIYUN_OPEN_CLIENT_ID, session["authorize_url"])
        self.assertIn("redirect_uri=oob", session["authorize_url"])
        self.assertIn("response_type=code", session["authorize_url"])
        self.assertIn("code_challenge_method=plain", session["authorize_url"])
        self.assertIn("code_challenge=", session["authorize_url"])
        self.assertIn("state=", session["authorize_url"])
        # 阿里云盘个人版公开客户端使用 plain，code_challenge 直接等于 code_verifier
        query = parse_qs(urlparse(session["authorize_url"]).query)
        self.assertEqual(query["code_challenge"][0], session["code_verifier"])

    def test_exchange_code_uses_given_verifier(self):
        fake_resp = {"access_token": "at", "refresh_token": "rt", "expires_in": 7200}
        with mock.patch.object(aliyun_oauth, "http_request_form_json", return_value=fake_resp) as mock_post:
            result = aliyun_oauth.exchange_aliyun_code("CODE", "VERIFIER")
        self.assertEqual(result["access_token"], "at")
        self.assertEqual(result["refresh_token"], "rt")
        self.assertEqual(result["expires_in"], 7200)
        form_data = mock_post.call_args[0][1]
        self.assertEqual(form_data["code"], "CODE")
        self.assertEqual(form_data["grant_type"], "authorization_code")
        self.assertEqual(form_data["code_verifier"], "VERIFIER")
        self.assertEqual(form_data["redirect_uri"], "oob")

    def test_exchange_code_accepts_access_token_only(self):
        # 公开客户端（无 AppSecret）授权响应只有 access_token，没有 refresh_token
        fake_resp = {"access_token": "long_lived_at", "expires_in": 2592000, "token_type": "Bearer"}
        with mock.patch.object(aliyun_oauth, "http_request_form_json", return_value=fake_resp):
            result = aliyun_oauth.exchange_aliyun_code("CODE", "V")
        self.assertEqual(result["access_token"], "long_lived_at")
        self.assertEqual(result["refresh_token"], "")
        self.assertEqual(result["expires_in"], 2592000)

    def test_exchange_code_requires_code(self):
        with self.assertRaises(RuntimeError):
            aliyun_oauth.exchange_aliyun_code("   ", "V")

    def test_exchange_code_requires_verifier(self):
        with self.assertRaises(RuntimeError):
            aliyun_oauth.exchange_aliyun_code("CODE", "  ")

    def test_exchange_code_raises_when_no_token(self):
        with mock.patch.object(aliyun_oauth, "http_request_form_json", return_value={"error": "bad"}):
            with self.assertRaises(RuntimeError):
                aliyun_oauth.exchange_aliyun_code("CODE", "V")

    def test_exchange_code_surfaces_http_error_detail(self):
        http_error = urllib.error.HTTPError(
            "https://openapi.alipan.com/oauth/access_token",
            400,
            "Bad Request",
            {},
            io.BytesIO(b'{"message":"invalid_grant: code already used"}'),
        )
        with mock.patch.object(aliyun_oauth, "http_request_form_json", side_effect=http_error):
            with self.assertRaises(RuntimeError) as ctx:
                aliyun_oauth.exchange_aliyun_code("CODE", "V")
        self.assertIn("invalid_grant", str(ctx.exception))

    def test_authorization_code_normalization_extracts_from_url(self):
        self.assertEqual(
            aliyun_oauth._normalize_authorization_code("oob?code=abc123&state=xyz"),
            "abc123",
        )
        self.assertEqual(
            aliyun_oauth._normalize_authorization_code("https://x/oob?code=abc123"),
            "abc123",
        )

    def test_authorization_code_normalization_keeps_plain_value(self):
        self.assertEqual(aliyun_oauth._normalize_authorization_code("  tkn-123  "), "tkn-123")
        self.assertEqual(aliyun_oauth._normalize_authorization_code(""), "")

    def test_exchange_code_surfaces_code_not_found_hint(self):
        http_error = urllib.error.HTTPError(
            "https://openapi.alipan.com/oauth/access_token",
            400,
            "Bad Request",
            {},
            io.BytesIO(b'{"code":"InvalidCode","message":"code not found"}'),
        )
        with mock.patch.object(aliyun_oauth, "http_request_form_json", side_effect=http_error):
            with self.assertRaises(RuntimeError) as ctx:
                aliyun_oauth.exchange_aliyun_code("CODE", "V")
        text = str(ctx.exception)
        self.assertIn("code not found", text)
        self.assertIn("只能用一次", text)

    def test_build_refresh_payload_includes_client_id(self):
        payload = aliyun_oauth.build_aliyun_refresh_payload("rt")
        self.assertEqual(payload["grant_type"], "refresh_token")
        self.assertEqual(payload["refresh_token"], "rt")
        self.assertIn("client_id", payload)


class AliyunRefreshEndpointsTest(unittest.TestCase):
    def setUp(self):
        """每次测试重置 provider 内存中的 access_token 缓存，避免跨用例污染。"""
        self.provider = aliyun.AliyunProvider()

    def test_refresh_prefers_official_endpoint_with_client_id(self):
        fake_cfg = {"aliyun_token_is_access": False}

        def fake_post(url, data=None, json=None, headers=None, timeout=None):
            self.assertIn("openapi.alipan.com", url)
            self.assertEqual(data["client_id"], aliyun_oauth.ALIYUN_OPEN_CLIENT_ID)
            return mock.Mock(
                raise_for_status=mock.Mock(),
                json=mock.Mock(return_value={"access_token": "official_at", "expires_in": 7200, "default_drive_id": "d1"}),
            )

        with mock.patch("app.core.get_config", return_value=fake_cfg), mock.patch("requests.post", side_effect=fake_post):
            token = self.provider._ensure_access_token("rt")
        self.assertEqual(token, "official_at")
        self.assertEqual(self.provider._drive_id, "d1")

    def test_refresh_falls_back_when_official_rejects_token(self):
        calls = {"prefixes": []}
        fake_cfg = {"aliyun_token_is_access": False}

        def fake_post(url, data=None, json=None, headers=None, timeout=None):
            calls["prefixes"].append(url)
            if "openapi.alipan.com" in url:
                return mock.Mock(
                    raise_for_status=mock.Mock(),
                    json=mock.Mock(return_value={"error": "invalid_client", "message": "bad client"}),
                )
            return mock.Mock(
                raise_for_status=mock.Mock(),
                json=mock.Mock(return_value={"access_token": "alipan_at", "expires_in": 7200}),
            )

        with mock.patch("app.core.get_config", return_value=fake_cfg), mock.patch("requests.post", side_effect=fake_post):
            token = self.provider._ensure_access_token("rt")
        self.assertEqual(token, "alipan_at")
        self.assertIn("openapi.alipan.com", calls["prefixes"][0])
        self.assertIn("auth.alipan.com", calls["prefixes"][1])


class AliyunAccessTokenModeTest(unittest.TestCase):
    def test_ensure_access_token_uses_stored_long_lived_access(self):
        provider = aliyun.AliyunProvider()
        fake_cfg = {
            "aliyun_token_is_access": True,
            "aliyun_refresh_token": "ACCESS_TOKEN_XYZ",
            "aliyun_access_expires_at": time.time() + 3600,
        }
        with mock.patch("app.core.get_config", return_value=fake_cfg):
            token = provider._ensure_access_token("anything")
        self.assertEqual(token, "ACCESS_TOKEN_XYZ")

    def test_ensure_access_token_raises_when_expired_access(self):
        provider = aliyun.AliyunProvider()
        fake_cfg = {
            "aliyun_token_is_access": True,
            "aliyun_refresh_token": "ACCESS_TOKEN_XYZ",
            "aliyun_access_expires_at": time.time() - 10,
        }
        with mock.patch("app.core.get_config", return_value=fake_cfg):
            with self.assertRaises(RuntimeError):
                provider._ensure_access_token("anything")

    def test_ensure_access_token_falls_back_to_refresh_when_no_flag(self):
        provider = aliyun.AliyunProvider()
        fake_cfg = {"aliyun_token_is_access": False}

        def fake_post(url, data=None, json=None, headers=None, timeout=None):
            self.assertIn("openapi.alipan.com", url)
            return mock.Mock(
                raise_for_status=mock.Mock(),
                json=mock.Mock(return_value={"access_token": "refreshed_at", "expires_in": 7200}),
            )

        with mock.patch("app.core.get_config", return_value=fake_cfg), mock.patch("requests.post", side_effect=fake_post):
            token = provider._ensure_access_token("rt")
        self.assertEqual(token, "refreshed_at")


if __name__ == "__main__":
    unittest.main()
