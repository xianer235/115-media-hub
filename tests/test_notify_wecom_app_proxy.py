"""企业微信应用模式支持自定义 API 反向代理地址（issue #1）。

背景：应用消息要求调用方出口 IP 在「企业可信 IP」列表里。家用宽带出口 IP 会变，
用户通常用一台固定 IP 的服务器把 qyapi.weixin.qq.com 反代出来，于是需要一个
「把官方域名换掉」的开关。这里锁定：默认直连、填了就替换、非法值报错而不是
悄悄回落官方域名（否则用户以为反代生效，实际仍被可信 IP 拦，极难排查）。
"""

import unittest
from unittest import mock

from app.services import notify


BASE_CFG = {
    "notify_push_enabled": True,
    "notify_channel": "wecom_app",
    "notify_wecom_app_corp_id": "ww-test-corp",
    "notify_wecom_app_agent_id": "1000002",
    "notify_wecom_app_secret": "test-secret",
    "notify_wecom_app_touser": "zhangsan",
}


def _cfg(**overrides):
    return {**BASE_CFG, **overrides}


class WecomAppApiBaseTest(unittest.TestCase):
    def setUp(self):
        notify.prune_notify_runtime_caches()

    def _token_url(self, cfg):
        runtime_cfg = notify.build_notify_runtime_config(cfg)
        with mock.patch.object(
            notify,
            "http_request_json",
            return_value={"errcode": 0, "access_token": "tok", "expires_in": 7200},
        ) as patched:
            notify._get_wecom_app_access_token(runtime_cfg, force_refresh=True)
        return patched.call_args[0][0]

    def _send_url(self, cfg):
        runtime_cfg = notify.build_notify_runtime_config(cfg)
        with mock.patch.object(notify, "_get_wecom_app_access_token", return_value="tok"), mock.patch.object(
            notify, "http_request_json", return_value={"errcode": 0}
        ) as patched:
            notify._send_wecom_app_markdown(runtime_cfg, "test")
        return patched.call_args[0][0]

    def test_default_uses_official_host(self):
        self.assertTrue(self._token_url(_cfg()).startswith("https://qyapi.weixin.qq.com/cgi-bin/gettoken?"))
        self.assertTrue(self._send_url(_cfg()).startswith("https://qyapi.weixin.qq.com/cgi-bin/message/send?"))

    def test_proxy_base_replaces_host(self):
        cfg = _cfg(notify_wecom_app_api_base="https://qyapi.example.com")
        self.assertTrue(self._token_url(cfg).startswith("https://qyapi.example.com/cgi-bin/gettoken?"))
        self.assertTrue(self._send_url(cfg).startswith("https://qyapi.example.com/cgi-bin/message/send?"))

    def test_proxy_base_keeps_path_prefix(self):
        cfg = _cfg(notify_wecom_app_api_base="https://proxy.example.com/wecom/")
        self.assertTrue(self._token_url(cfg).startswith("https://proxy.example.com/wecom/cgi-bin/gettoken?"))

    def test_proxy_base_strips_redundant_cgi_bin(self):
        # 用户常把接口地址整段抄进来，不能拼成 /cgi-bin/cgi-bin/。
        cfg = _cfg(notify_wecom_app_api_base="https://proxy.example.com/cgi-bin")
        self.assertTrue(self._token_url(cfg).startswith("https://proxy.example.com/cgi-bin/gettoken?"))

    def test_invalid_proxy_base_raises_instead_of_silent_fallback(self):
        cfg = _cfg(notify_wecom_app_api_base="proxy.example.com")
        with mock.patch.object(notify, "http_request_json") as patched:
            with self.assertRaises(RuntimeError) as ctx:
                notify._send_wecom_app_markdown(notify.build_notify_runtime_config(cfg), "test")
        self.assertIn("反向代理地址格式无效", str(ctx.exception))
        patched.assert_not_called()

    def test_trusted_ip_error_mentions_proxy_setting(self):
        runtime_cfg = notify.build_notify_runtime_config(_cfg())
        with mock.patch.object(notify, "_get_wecom_app_access_token", return_value="tok"), mock.patch.object(
            notify, "http_request_json", return_value={"errcode": 60020, "errmsg": "not allow to access from your ip"}
        ):
            with self.assertRaises(RuntimeError) as ctx:
                notify._send_wecom_app_markdown(runtime_cfg, "test")
        message = str(ctx.exception)
        self.assertIn("60020", message)
        self.assertIn("企业可信 IP", message)
        self.assertIn("反向代理地址", message)

    def test_runtime_config_keeps_raw_value_for_error_text(self):
        # 归一化只发生在发送时，配置里保留用户原样输入，报错才能指回他填的内容。
        runtime_cfg = notify.build_notify_runtime_config(_cfg(notify_wecom_app_api_base="  https://qyapi.example.com  "))
        self.assertEqual(runtime_cfg["wecom_app_api_base"], "https://qyapi.example.com")


class WecomAppProxyConfigTest(unittest.TestCase):
    def test_default_config_has_empty_api_base(self):
        cfg = notify.default_config()
        self.assertEqual(str(cfg.get("notify_wecom_app_api_base", "")), "")

    def test_normalize_config_fills_missing_api_base(self):
        merged = notify.normalize_config({"notify_wecom_app_corp_id": "ww1"})
        self.assertIn("notify_wecom_app_api_base", merged)


if __name__ == "__main__":
    unittest.main()
