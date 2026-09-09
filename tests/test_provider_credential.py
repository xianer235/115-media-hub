import unittest
import json
from unittest import mock

from app.routes import settings as settings_routes


class ProviderCredentialEndpointTest(unittest.IsolatedAsyncioTestCase):
    def _provider(self, name, label, config_keys):
        p = mock.Mock()
        p.name = name
        p.label = label
        p.config_keys = config_keys
        return p

    async def test_returns_primary_cookie_for_115(self):
        provider = self._provider("115", "115网盘", ["cookie_115"])
        cfg = {"cookie_115": "ABC=xyz"}
        with mock.patch.object(settings_routes, "_get_provider_or_none", return_value=provider), \
             mock.patch.object(settings_routes, "get_config", return_value=cfg):
            resp = await settings_routes.get_provider_credential("115")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.body)
        self.assertTrue(data["configured"])
        self.assertEqual(data["credential"], "ABC=xyz")
        self.assertEqual(data["credential_key"], "cookie_115")

    async def test_returns_access_token_for_aliyun(self):
        provider = self._provider("aliyun", "阿里云盘", ["aliyun_refresh_token"])
        cfg = {"aliyun_refresh_token": "tok123", "aliyun_token_is_access": True}
        with mock.patch.object(settings_routes, "_get_provider_or_none", return_value=provider), \
             mock.patch.object(settings_routes, "get_config", return_value=cfg):
            resp = await settings_routes.get_provider_credential("aliyun")
        data = json.loads(resp.body)
        self.assertEqual(data["credential"], "tok123")
        self.assertEqual(data["credential_key"], "aliyun_refresh_token")

    async def test_configured_false_when_empty(self):
        provider = self._provider("115", "115网盘", ["cookie_115"])
        cfg = {"cookie_115": ""}
        with mock.patch.object(settings_routes, "_get_provider_or_none", return_value=provider), \
             mock.patch.object(settings_routes, "get_config", return_value=cfg):
            resp = await settings_routes.get_provider_credential("115")
        data = json.loads(resp.body)
        self.assertFalse(data["configured"])
        self.assertEqual(data["credential"], "")

    async def test_unknown_provider_404(self):
        with mock.patch.object(settings_routes, "_get_provider_or_none", return_value=None):
            resp = await settings_routes.get_provider_credential("nope")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
