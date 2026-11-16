"""emby-bridge（极影视 → Seerr Emby 兼容桥）测试。

覆盖五个翻译点：T1 头改写、T2 /Auth/Keys 本地实现、T3 /Items?ids= 判重改写、
T4 CollectionType 补全、T5 来源白名单与开关。配置与 urllib 全部 mock，不真连
极影视。临时目录交给 tempfile（根在 run_tests.py 指定的会话目录）。
"""

import tempfile
import unittest
from unittest import mock

from app.services import emby_bridge as bridge


def _settings(**overrides):
    base = {
        "enabled": True,
        "upstream": "http://192.168.1.10:8021",
        "username": "xianer",
        "password": "secret",
        "allow_public": False,
    }
    base.update(overrides)
    return base


class ParseHeaderTest(unittest.TestCase):
    def test_parse_basic(self):
        fields = bridge._parse_media_browser_header(
            'MediaBrowser Client="Seerr", Device="Seerr", DeviceId="abc", Version="1.0.0"'
        )
        self.assertEqual(fields["Client"], "Seerr")
        self.assertEqual(fields["DeviceId"], "abc")

    def test_parse_with_token(self):
        fields = bridge._parse_media_browser_header(
            'MediaBrowser Client="Seerr", Device="Seerr", DeviceId="abc", Version="1.0.0", Token="tok123"'
        )
        self.assertEqual(fields["Token"], "tok123")

    def test_parse_missing_device_id(self):
        fields = bridge._parse_media_browser_header('MediaBrowser Client="Seerr", Device="Seerr"')
        self.assertNotIn("DeviceId", fields)


class RewriteHeadersTest(unittest.TestCase):
    def test_seerr_token_is_ignored_when_bridge_has_real_one(self):
        """Seerr 头上带的是桥伪造的伪 key，透传给极影视只会 401，必须用桥的真 token。"""
        out = bridge._rewrite_headers(
            {
                "Authorization": 'MediaBrowser Client="Seerr", Device="Seerr", DeviceId="abc", Version="1.0.0", Token="pseudo-key"',
                "Accept": "application/json",
            },
            token="real-token",
        )
        self.assertNotIn("Authorization", out)
        self.assertEqual(out["X-Emby-Token"], "real-token")
        self.assertIn("X-Emby-Authorization", out)
        self.assertIn('Client="Seerr"', out["X-Emby-Authorization"])

    def test_falls_back_to_seerr_token_when_bridge_has_none(self):
        out = bridge._rewrite_headers(
            {"Authorization": 'MediaBrowser Client="Seerr", Device="Seerr", DeviceId="abc", Version="1.0.0", Token="user-key"'},
            token="",
        )
        self.assertEqual(out["X-Emby-Token"], "user-key")

    def test_rewrite_uses_cached_token_when_seerr_has_none(self):
        out = bridge._rewrite_headers(
            {"Authorization": 'MediaBrowser Client="Seerr", Device="Seerr", DeviceId="abc", Version="1.0.0"'},
            token="real-token",
        )
        self.assertEqual(out["X-Emby-Token"], "real-token")

    def test_rewrite_fills_missing_device_id(self):
        out = bridge._rewrite_headers(
            {"Authorization": 'MediaBrowser Client="Seerr", Device="Seerr"'},
            token="real-token",
        )
        self.assertIn('DeviceId="115-media-hub-bridge"', out["X-Emby-Authorization"])


class CollectionTypeTest(unittest.TestCase):
    def test_views_fallback_counts_as_library_list(self):
        """极影视没有 /Library/MediaFolders，Seerr 回退 /Users/{uid}/Views，也要补类型。"""
        self.assertTrue(bridge._is_library_list_path("/Users/abc/Views"))
        self.assertTrue(bridge._is_library_list_path("/Library/MediaFolders"))
        self.assertFalse(bridge._is_library_list_path("/Users/abc/Items"))

    def test_movie_library_gets_movies(self):
        payload = {"Items": [{"Name": "电影库"}, {"Name": "电视剧库"}]}
        bridge._fill_collection_types(payload)
        self.assertEqual(payload["Items"][0]["CollectionType"], "movies")
        self.assertEqual(payload["Items"][1]["CollectionType"], "tvshows")

    def test_unknown_library_defaults_to_tvshows(self):
        payload = {"Items": [{"Name": "夸克"}]}
        bridge._fill_collection_types(payload)
        self.assertEqual(payload["Items"][0]["CollectionType"], "tvshows")

    def test_existing_collection_type_preserved(self):
        payload = {"Items": [{"Name": "电影库", "CollectionType": "boxsets"}]}
        bridge._fill_collection_types(payload)
        self.assertEqual(payload["Items"][0]["CollectionType"], "boxsets")


class PrivateIpTest(unittest.TestCase):
    def test_rfc1918(self):
        self.assertTrue(bridge._is_private_ip("192.168.1.10"))
        self.assertTrue(bridge._is_private_ip("10.0.0.1"))
        self.assertTrue(bridge._is_private_ip("172.16.0.1"))

    def test_loopback(self):
        self.assertTrue(bridge._is_private_ip("127.0.0.1"))

    def test_public(self):
        self.assertFalse(bridge._is_private_ip("8.8.8.8"))

    def test_bad_ip(self):
        self.assertFalse(bridge._is_private_ip("not-an-ip"))


class HandleDispatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wb_embridge_")

    async def _run(self, method, path, query="", headers=None, settings=None, client_host="192.168.1.5"):
        headers = headers or {}
        headers = dict(headers)
        headers.setdefault("X-Bridge-Client-Host", client_host)
        patcher = mock.patch.object(bridge, "_bridge_settings", return_value=_settings(**(settings or {})))
        patcher.start()
        try:
            return await bridge.handle(method, path, query, headers, b"")
        finally:
            patcher.stop()

    def _run_sync(self, coro):
        import asyncio
        # 用 asyncio.run：Python 3.10+ 移除了 get_event_loop 的隐式建环（3.12 直接抛
        # RuntimeError），run 从 3.7 起跨版本稳定，且这里每次只需跑单个 coroutine。
        return asyncio.run(coro)

    def test_disabled_returns_404(self):
        status, _, _ = self._run_sync(self._run("GET", "/System/Info", settings={"enabled": False}))
        self.assertEqual(status, 404)

    def test_not_configured_returns_503(self):
        status, _, _ = self._run_sync(
            self._run("GET", "/System/Info", settings={"upstream": "", "username": "", "password": ""})
        )
        self.assertEqual(status, 503)

    def test_non_allowlisted_path_returns_404(self):
        status, _, _ = self._run_sync(self._run("GET", "/Plugins"))
        self.assertEqual(status, 404)

    def test_bare_users_path_is_forwarded(self):
        """Seerr 的 getUsers() 调 `GET /Users`（无尾斜杠），不能被白名单判成 404。"""
        seen = {}

        def fake_forward(upstream, method, path, query, body, headers, read_timeout):
            seen["path"] = path
            return 200, {}, {"Items": []}

        with mock.patch.object(bridge, "_forward_json", side_effect=fake_forward):
            with mock.patch.object(bridge, "_get_token", return_value={"token": "t", "uid": "u", "server_id": "s"}):
                status, _, _ = self._run_sync(self._run("GET", "/Users"))
        self.assertEqual(status, 200)
        self.assertEqual(seen["path"], "/Users")

    def test_media_folders_rewritten_to_views(self):
        """极影视没有 /Library/MediaFolders（404），桥用 /Users/{uid}/Views 顶替并补类型。"""
        seen = {}

        def fake_forward(upstream, method, path, query, body, headers, read_timeout):
            seen["path"] = path
            return 200, {}, {"Items": [{"Name": "电影库"}]}

        with mock.patch.object(bridge, "_forward_json", side_effect=fake_forward):
            with mock.patch.object(bridge, "_get_token", return_value={"token": "t", "uid": "u", "server_id": "s"}):
                status, _, out = self._run_sync(self._run("GET", "/Library/MediaFolders"))
        self.assertEqual(status, 200)
        self.assertEqual(seen["path"], "/Users/u/Views")
        self.assertEqual(out["Items"][0]["CollectionType"], "movies")

    def test_views_fallback_response_gets_collection_types(self):
        """端到端：/Users/{uid}/Views 的库列表回来时补上 movies / tvshows。"""
        payload = {"Items": [{"Name": "电影库"}, {"Name": "连载中"}]}
        with mock.patch.object(bridge, "_forward_json", return_value=(200, {}, payload)):
            with mock.patch.object(bridge, "_get_token", return_value={"token": "t", "uid": "u", "server_id": "s"}):
                status, _, out = self._run_sync(self._run("GET", "/Users/u/Views"))
        self.assertEqual(status, 200)
        self.assertEqual(out["Items"][0]["CollectionType"], "movies")
        self.assertEqual(out["Items"][1]["CollectionType"], "tvshows")

    def test_public_source_returns_403_when_not_allowed(self):
        status, _, _ = self._run_sync(self._run("GET", "/System/Info", client_host="8.8.8.8"))
        self.assertEqual(status, 403)

    def test_public_source_allowed_when_flag_on(self):
        with mock.patch.object(bridge, "_forward_json", return_value=(200, {}, {"ok": True})):
            with mock.patch.object(bridge, "_get_token", return_value={"token": "t", "uid": "u", "server_id": "s"}):
                status, _, _ = self._run_sync(
                    self._run("GET", "/System/Info", settings={"allow_public": True}, client_host="8.8.8.8")
                )
        self.assertEqual(status, 200)

    def test_auth_keys_post(self):
        status, _, payload = self._run_sync(self._run("POST", "/Auth/Keys"))
        self.assertEqual(status, 200)

    def test_auth_keys_get_returns_seerr_key(self):
        with mock.patch.object(bridge, "_stable_pseudo_key", return_value="deadbeef"):
            status, _, payload = self._run_sync(self._run("GET", "/Auth/Keys"))
        self.assertEqual(status, 200)
        self.assertEqual(payload["Items"][0]["AppName"], "Seerr")
        self.assertEqual(payload["Items"][0]["AccessToken"], "deadbeef")

    def test_items_ids_rewritten_to_user_items(self):
        captured = {}

        def fake_forward(upstream, method, path, query, body, headers, read_timeout):
            captured["path"] = path
            captured["query"] = query
            # 极影视 /Users/{uid}/Items/{id} 返回单条对象（不是 Items 数组）
            return 200, {}, {"Name": "消失的裂痕", "ProviderIds": {"Tmdb": "332911"}}

        with mock.patch.object(bridge, "_forward_json", side_effect=fake_forward):
            with mock.patch.object(bridge, "_get_token", return_value={"token": "t", "uid": "uid123", "server_id": "s"}):
                status, _, payload = self._run_sync(
                    self._run("GET", "/Items", query="ids=collection_xxx")
                )
        self.assertEqual(status, 200)
        self.assertTrue(captured["path"].startswith("/Users/uid123/Items/"))
        # 单条响应被包装成 Jellyseerr 期望的 {Items:[单条]} 结构
        self.assertIn("Items", payload)
        self.assertEqual(payload["TotalRecordCount"], 1)
        self.assertEqual(payload["Items"][0]["ProviderIds"]["Tmdb"], "332911")


class PseudoKeyTest(unittest.TestCase):
    def test_stable_across_calls(self):
        with mock.patch.object(bridge, "_get_token", return_value={"token": "t", "uid": "u", "server_id": "server-1"}):
            k1 = bridge._stable_pseudo_key(_settings())
            k2 = bridge._stable_pseudo_key(_settings())
        self.assertEqual(k1, k2)
        self.assertEqual(len(k1), 64)


class RoutePathTest(unittest.TestCase):
    """路由层必须把 ``{path:path}`` 捕获到的无斜杠路径补回前导斜杠。

    真实请求 ``/emby-bridge/System/Info`` 时 FastAPI 传进来的是 ``System/Info``；
    服务层白名单按 ``/System/`` 这类绝对路径判断，少了斜杠会全部 404（2026-11-17
    真机接 Seerr 时踩到，前端只报「无法连接到 Jellyfin 服务器」）。
    """

    def _request(self):
        import asyncio  # noqa: F401  （保持与其它用例一致的显式导入习惯）
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "server": ("test", 80),
            "path": "/emby-bridge/System/Info",
            "root_path": "",
            "query_string": b"",
            "headers": [(b"host", b"test")],
            "client": ("192.168.1.5", 1234),
        }
        return Request(scope)

    def test_forwarded_path_gets_leading_slash(self):
        import asyncio
        from app.routes import emby_bridge as bridge_route

        with mock.patch.object(bridge, "handle", return_value=(200, {}, {"ok": True})) as patched:
            asyncio.run(bridge_route.emby_bridge_forward(self._request(), "System/Info"))
        args = patched.call_args[0]
        self.assertEqual(args[1], "/System/Info")

    def test_leading_slash_not_doubled(self):
        import asyncio
        from app.routes import emby_bridge as bridge_route

        with mock.patch.object(bridge, "handle", return_value=(200, {}, {"ok": True})) as patched:
            asyncio.run(bridge_route.emby_bridge_forward(self._request(), "/System/Info"))
        args = patched.call_args[0]
        self.assertEqual(args[1], "/System/Info")


if __name__ == "__main__":
    unittest.main()
