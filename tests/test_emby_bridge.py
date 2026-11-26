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


class _BridgeHandleTestBase(unittest.TestCase):
    """直接调 bridge.handle 的公共夹具（不继承具体用例，避免子类把父类用例重跑一遍）。"""

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


class HandleDispatchTest(_BridgeHandleTestBase):
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

    def test_items_latest_rewritten_to_recent_items(self):
        """Recently Added Scan 的 /Items/Latest?Limit=12 被改成按日期降序拉最近 N 条。"""
        captured = {}

        def fake_forward(upstream, method, path, query, body, headers, read_timeout):
            captured["path"] = path
            captured["query"] = query
            return 200, {}, {"Items": [{"Id": "video_1", "Type": "Movie"}]}

        with mock.patch.object(bridge, "_forward_json", side_effect=fake_forward):
            with mock.patch.object(bridge, "_get_token", return_value={"token": "t", "uid": "uid123", "server_id": "s"}):
                status, _, payload = self._run_sync(
                    self._run("GET", "/Users/uid123/Items/Latest", query="Limit=12&ParentId=class_movies")
                )
        self.assertEqual(status, 200)
        # 路径 /Items/Latest → /Items（保留 /Users/{uid} 前缀）
        self.assertEqual(captured["path"], "/Users/uid123/Items")
        qs = dict(bridge.urllib.parse.parse_qsl(captured["query"]))
        self.assertEqual(qs["ParentId"], "class_movies")
        self.assertEqual(qs["SortBy"], "DateCreated")
        self.assertEqual(qs["SortOrder"], "Descending")
        self.assertEqual(qs["Recursive"], "true")
        self.assertEqual(int(qs["Limit"]), bridge._LATEST_ITEMS_LIMIT)

    def test_items_latest_without_parentid_passed_through(self):
        """缺 ParentId 时不动，直接透传（不给上游发坏查询）。"""
        captured = {}

        def fake_forward(upstream, method, path, query, body, headers, read_timeout):
            captured["path"] = path
            captured["query"] = query
            return 200, {}, {"Items": []}

        with mock.patch.object(bridge, "_forward_json", side_effect=fake_forward):
            with mock.patch.object(bridge, "_get_token", return_value={"token": "t", "uid": "uid123", "server_id": "s"}):
                status, _, _ = self._run_sync(
                    self._run("GET", "/Users/uid123/Items/Latest", query="Limit=12")
                )
        self.assertEqual(status, 200)
        self.assertEqual(captured["path"], "/Users/uid123/Items/Latest")


class ScanPaginationTest(_BridgeHandleTestBase):
    """T6：Seerr 只发一次 /Items 且不翻页，桥代为翻页聚合成整个库。"""

    def _items(self, start, count, total):
        return {
            "Items": [{"Id": f"video_{i}", "Type": "Movie"} for i in range(start, start + count)],
            "TotalRecordCount": total,
            "StartIndex": start,
        }

    def test_recursive_library_query_is_paginated_and_merged(self):
        calls = []

        def fake_forward(upstream, method, path, query, body, headers, read_timeout):
            qs = dict(bridge.urllib.parse.parse_qsl(query))
            start = int(qs["StartIndex"])
            calls.append(start)
            # 上游按页返回：共 2500 条，每页 1000
            count = min(bridge._SCAN_PAGE_SIZE, 2500 - start)
            return 200, {}, self._items(start, count, 2500)

        with mock.patch.object(bridge, "_forward_json", side_effect=fake_forward):
            with mock.patch.object(bridge, "_get_token", return_value={"token": "t", "uid": "uid123", "server_id": "s"}):
                status, _, payload = self._run_sync(
                    self._run(
                        "GET",
                        "/Items",
                        query="Recursive=true&StartIndex=0&ParentId=class_movies&IncludeItemTypes=Series,Movie",
                    )
                )
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["Items"]), 2500)
        self.assertEqual(payload["TotalRecordCount"], 2500)
        self.assertEqual(calls, [0, 1000, 2000])

    def test_upstream_capping_page_size_still_fetches_everything(self):
        """极影视把单页压到 200 条时，游标必须按实际返回条数推进，否则跨页漏条目。"""
        calls = []
        upstream_cap = 200
        total_items = 700

        def fake_forward(upstream, method, path, query, body, headers, read_timeout):
            qs = dict(bridge.urllib.parse.parse_qsl(query))
            start = int(qs["StartIndex"])
            calls.append(start)
            count = min(upstream_cap, total_items - start)
            return 200, {}, self._items(start, max(0, count), total_items)

        with mock.patch.object(bridge, "_forward_json", side_effect=fake_forward):
            with mock.patch.object(bridge, "_get_token", return_value={"token": "t", "uid": "uid123", "server_id": "s"}):
                status, _, payload = self._run_sync(
                    self._run("GET", "/Items", query="Recursive=true&ParentId=class_movies")
                )
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["Items"]), total_items)
        self.assertEqual(calls, [0, 200, 400, 600])

    def test_upstream_ignoring_start_index_does_not_loop_forever(self):
        """极影视若忽略 StartIndex，反复给同一页，桥必须靠「没有新条目」停手。"""
        calls = []

        def fake_forward(upstream, method, path, query, body, headers, read_timeout):
            calls.append(query)
            return 200, {}, self._items(0, bridge._SCAN_PAGE_SIZE, 999999)

        with mock.patch.object(bridge, "_forward_json", side_effect=fake_forward):
            with mock.patch.object(bridge, "_get_token", return_value={"token": "t", "uid": "uid123", "server_id": "s"}):
                status, _, payload = self._run_sync(
                    self._run("GET", "/Items", query="Recursive=true&ParentId=class_movies")
                )
        self.assertEqual(status, 200)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(payload["Items"]), bridge._SCAN_PAGE_SIZE)

    def test_non_recursive_items_query_is_forwarded_once(self):
        calls = []

        def fake_forward(upstream, method, path, query, body, headers, read_timeout):
            calls.append(query)
            return 200, {}, {"Items": [], "TotalRecordCount": 0}

        with mock.patch.object(bridge, "_forward_json", side_effect=fake_forward):
            with mock.patch.object(bridge, "_get_token", return_value={"token": "t", "uid": "uid123", "server_id": "s"}):
                self._run_sync(self._run("GET", "/Items", query="Limit=10&SearchTerm=abc"))
        self.assertEqual(len(calls), 1)

    def test_ids_query_still_uses_rewrite_path(self):
        """ids= 判重请求不能被卷进翻页逻辑。"""
        self.assertFalse(bridge._is_full_scan_items("GET", "/Items", "ids=collection_1&Recursive=true&ParentId=class_1"))
        self.assertTrue(bridge._is_full_scan_items("GET", "/Items", "Recursive=true&ParentId=class_1"))
        self.assertTrue(bridge._is_full_scan_items("GET", "/Items", "recursive=True&ParentId=class_1"))
        self.assertFalse(bridge._is_full_scan_items("GET", "/Items", "Recursive=true"))
        self.assertFalse(bridge._is_full_scan_items("POST", "/Items", "Recursive=true&ParentId=class_1"))


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


class TestConnectionTest(unittest.TestCase):
    """设置页「测试连通性」：只读探测，登录一次 + 列一次库。"""

    def test_success_reports_libraries(self):
        items = {"Items": [{"Name": "电影库"}, {"Name": "电视剧库"}, {"Name": "连载中"}]}
        with mock.patch.object(bridge, "_do_login", return_value={"token": "t", "uid": "uid1", "server_id": "srv"}) as login, \
                mock.patch.object(bridge, "_forward_json", return_value=(200, {}, items)) as forward:
            result = bridge.test_connection("192.168.1.10:8021", "xianer", "secret")
        self.assertTrue(result["ok"])
        self.assertEqual(result["library_count"], 3)
        self.assertEqual(result["libraries"], ["电影库", "电视剧库", "连载中"])
        login.assert_called_once_with("http://192.168.1.10:8021", "xianer", "secret")
        self.assertEqual(forward.call_args[0][2], "/Users/uid1/Views")

    def test_wrong_password_returns_readable_message(self):
        import urllib.error

        err = urllib.error.HTTPError("http://x/Users/AuthenticateByName", 401, "Unauthorized", {}, None)
        with mock.patch.object(bridge, "_do_login", side_effect=err):
            result = bridge.test_connection("http://x", "xianer", "bad")
        self.assertFalse(result["ok"])
        self.assertIn("媒体库账号或密码", result["msg"])

    def test_unreachable_upstream(self):
        import urllib.error

        with mock.patch.object(bridge, "_do_login", side_effect=urllib.error.URLError("Connection refused")):
            result = bridge.test_connection("http://192.168.1.10:8021", "xianer", "secret")
        self.assertFalse(result["ok"])
        self.assertIn("连不上", result["msg"])

    def test_missing_fields_rejected_without_request(self):
        with mock.patch.object(bridge, "_do_login") as login:
            self.assertFalse(bridge.test_connection("", "xianer", "secret")["ok"])
            self.assertFalse(bridge.test_connection("http://x", "", "secret")["ok"])
            self.assertFalse(bridge.test_connection("http://x", "xianer", "")["ok"])
        login.assert_not_called()

    def test_empty_library_list_is_failure(self):
        with mock.patch.object(bridge, "_do_login", return_value={"token": "t", "uid": "u", "server_id": "s"}), \
                mock.patch.object(bridge, "_forward_json", return_value=(200, {}, {"Items": []})):
            result = bridge.test_connection("http://x", "xianer", "secret")
        self.assertFalse(result["ok"])
        self.assertIn("媒体库", result["msg"])


class TestConnectionRouteTest(unittest.TestCase):
    """路由层：密码留空时沿用已保存的密码（sensitive 合并），并把失败映射成 400。"""

    def setUp(self):
        from fastapi.testclient import TestClient
        from app.core import require_auth
        from app.main import app

        app.dependency_overrides[require_auth] = lambda: True
        self._app = app
        self._require_auth = require_auth
        self.client = TestClient(app)

    def tearDown(self):
        self._app.dependency_overrides.pop(self._require_auth, None)

    def test_route_preserves_saved_password_and_returns_payload(self):
        from app.routes import settings as settings_route

        seen = {}

        def fake_test(upstream, username, password):
            seen.update({"upstream": upstream, "username": username, "password": password})
            return {"ok": True, "msg": "已连上极影视", "latency_ms": 5, "library_count": 1, "libraries": ["电影库"]}

        with mock.patch.object(settings_route, "get_config", return_value={
            "emby_bridge_upstream": "http://old",
            "emby_bridge_username": "old-user",
            "emby_bridge_password": "saved-password",
        }), mock.patch.object(settings_route.emby_bridge_service, "test_connection", side_effect=fake_test):
            resp = self.client.post(
                "/settings/emby_bridge/test",
                json={"emby_bridge_upstream": "http://new", "emby_bridge_username": "new-user", "emby_bridge_password": ""},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        self.assertEqual(seen["upstream"], "http://new")
        self.assertEqual(seen["username"], "new-user")
        self.assertEqual(seen["password"], "saved-password")

    def test_route_maps_failure_to_400_with_msg(self):
        from app.routes import settings as settings_route

        with mock.patch.object(settings_route, "get_config", return_value={
            "emby_bridge_upstream": "http://x",
            "emby_bridge_username": "u",
            "emby_bridge_password": "p",
        }), mock.patch.object(
            settings_route.emby_bridge_service,
            "test_connection",
            return_value={"ok": False, "msg": "登录被拒绝", "latency_ms": 3},
        ):
            resp = self.client.post("/settings/emby_bridge/test", json={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["msg"], "登录被拒绝")


class ForwardRetryTest(unittest.TestCase):
    """_forward_raw 对「读响应体时连接中断」应做有限重试，对业务错误不重试。"""

    @staticmethod
    def _resp(fn):
        class _Resp:
            headers = {}
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return fn()

        return _Resp()

    def test_incomplete_read_retries_then_succeeds(self):
        import http.client

        payload = b'{"ok": true}'
        calls = []

        def read():
            calls.append(1)
            if len(calls) == 1:
                raise http.client.IncompleteRead(b"", 0)
            return payload

        def fake(req, timeout=None):
            return self._resp(read)

        with mock.patch.object(bridge, "_urlopen", side_effect=fake), \
                mock.patch.object(bridge.time, "sleep"):
            status, headers, body = bridge._forward_raw(
                "http://up", "GET", "/Items", "", b"", {}, read_timeout=10
            )
        self.assertEqual(status, 200)
        self.assertEqual(body, payload)
        self.assertEqual(len(calls), 2)  # 断连后重试了一次才成功

    def test_incomplete_read_exhausted_returns_502(self):
        import http.client

        def read():
            raise http.client.IncompleteRead(b"", 0)

        def fake(req, timeout=None):
            return self._resp(read)

        with mock.patch.object(bridge, "_urlopen", side_effect=fake), \
                mock.patch.object(bridge.time, "sleep"):
            status, headers, body = bridge._forward_raw(
                "http://up", "GET", "/Items", "", b"", {}, read_timeout=10
            )
        self.assertEqual(status, 502)
        self.assertEqual(body, b"")

    def test_http_error_not_retried(self):
        import io
        import urllib.error

        calls = []

        def fake_raise(req, timeout=None):
            calls.append(1)
            err = urllib.error.HTTPError("http://up", 500, "err", {}, io.BytesIO(b"boom"))
            raise err

        with mock.patch.object(bridge, "_urlopen", side_effect=fake_raise):
            status, headers, body = bridge._forward_raw(
                "http://up", "GET", "/Items", "", b"", {}, read_timeout=10
            )
        self.assertEqual(status, 500)
        self.assertEqual(len(calls), 1)  # 业务错误不重试


class TlsRetryTest(unittest.TestCase):
    """TLS 层断连（UNEXPECTED_EOF）也要按瞬时错误重试，证书错误不重试。"""

    @staticmethod
    def _resp(body=b'{"ok": true}'):
        class _Resp:
            headers = {}
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return body

        return _Resp()

    def test_ssl_eof_retried_then_succeeds(self):
        import ssl

        calls = []

        def fake(req, timeout=None):
            calls.append(1)
            if len(calls) == 1:
                raise ssl.SSLEOFError(8, "EOF occurred in violation of protocol")
            return self._resp()

        with mock.patch.object(bridge, "_urlopen", side_effect=fake), \
                mock.patch.object(bridge.time, "sleep"):
            status, _headers, body = bridge._forward_raw(
                "https://jys.example.com", "GET", "/Users/1/Items", "", b"", {}, read_timeout=30
            )
        self.assertEqual(status, 200)
        self.assertEqual(len(calls), 2)

    def test_urlerror_wrapping_ssl_eof_is_transient(self):
        import ssl
        import urllib.error

        wrapped = urllib.error.URLError(ssl.SSLEOFError(8, "EOF occurred in violation of protocol"))
        self.assertTrue(bridge._is_transient_network_error(wrapped))
        self.assertTrue(bridge._is_transient_network_error(ssl.SSLEOFError(8, "x")))
        self.assertTrue(bridge._is_transient_network_error(ssl.SSLError("EOF occurred in violation of protocol")))
        # DNS 解析失败 / 证书问题都是确定性的，重试没意义
        self.assertFalse(bridge._is_transient_network_error(urllib.error.URLError("Name or service not known")))
        self.assertFalse(bridge._is_transient_network_error(ssl.SSLCertVerificationError("bad cert")))

    def test_certificate_error_propagates_without_retry(self):
        import ssl

        calls = []

        def fake(req, timeout=None):
            calls.append(1)
            raise ssl.SSLCertVerificationError(1, "certificate verify failed")

        with mock.patch.object(bridge, "_urlopen", side_effect=fake), \
                mock.patch.object(bridge.time, "sleep"):
            with self.assertRaises(ssl.SSLCertVerificationError):
                bridge._forward_raw(
                    "https://jys.example.com", "GET", "/Users/1/Items", "", b"", {}, read_timeout=30
                )
        self.assertEqual(len(calls), 1)

    def test_login_retries_once_on_ssl_eof(self):
        import ssl

        calls = []
        fake_payload = b'{"AccessToken": "tok", "User": {"Id": "u1"}, "ServerId": "s1"}'

        def fake(req, timeout=None):
            calls.append(1)
            if len(calls) == 1:
                raise ssl.SSLEOFError(8, "EOF occurred in violation of protocol")
            return self._resp(fake_payload)

        with mock.patch.object(bridge, "_urlopen", side_effect=fake), \
                mock.patch.object(bridge.time, "sleep"):
            info = bridge._do_login("https://jys.example.com", "user", "pw")
        self.assertEqual(info["token"], "tok")
        self.assertEqual(len(calls), 2)


class MultiAddressConnectionTest(unittest.TestCase):
    """IPv6 先连上但 TLS 被掐断时，应回退到下一个地址（A 记录）。"""

    def test_falls_back_to_next_address_when_tls_fails(self):
        import socket
        import ssl as ssl_module

        from app import http_utils

        attempts = []

        class FakeSock:
            def __init__(self, family, *args, **kwargs):
                self.family = family

            def settimeout(self, _timeout):
                pass

            def connect(self, addr):
                attempts.append(addr[0])

            def close(self):
                pass

        class FakeContext:
            check_hostname = True
            verify_mode = ssl_module.CERT_REQUIRED

            def wrap_socket(self, sock, server_hostname=None):
                if sock.family == socket.AF_INET6:
                    raise ssl_module.SSLEOFError(8, "EOF occurred in violation of protocol")
                return "TLS-OK"

        addresses = [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::1", 443, 0, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.7", 443)),
        ]
        conn = http_utils.MultiAddressHTTPSConnection(
            "jys.example.com", 443, timeout=5, context=FakeContext(), check_hostname=None
        )
        with mock.patch.object(http_utils.socket, "getaddrinfo", return_value=addresses), \
                mock.patch.object(http_utils.socket, "socket", FakeSock):
            conn.connect()
        self.assertEqual(attempts, ["2001:db8::1", "192.0.2.7"])
        self.assertEqual(conn.connected_address, "192.0.2.7")
        self.assertEqual(conn.sock, "TLS-OK")


class ResilientOpenerHandlerTest(unittest.TestCase):
    """opener 里的 HTTPS handler 不能依赖 CPython 私有属性（3.12 起没有 _check_hostname）。"""

    def test_https_open_only_passes_context(self):
        import ssl as ssl_module

        from app import http_utils

        captured = {}

        class RecordingHandler(http_utils._MultiAddressHTTPSHandler):
            def do_open(self, http_class, req, **kwargs):
                captured["http_class"] = http_class
                captured["kwargs"] = kwargs
                return "opened"

        context = ssl_module.create_default_context()
        handler = RecordingHandler(context=context)
        # 模拟 Python 3.12+：实例上根本没有 _check_hostname
        handler.__dict__.pop("_check_hostname", None)

        self.assertEqual(handler.https_open(None), "opened")
        self.assertIs(captured["http_class"], http_utils.MultiAddressHTTPSConnection)
        self.assertIs(captured["kwargs"].get("context"), context)
        self.assertNotIn("check_hostname", captured["kwargs"])

    def test_build_opener_returns_usable_opener(self):
        from app import http_utils

        opener = http_utils.build_resilient_https_opener()
        names = [type(h).__name__ for h in opener.handlers]
        self.assertIn("_MultiAddressHTTPSHandler", names)


if __name__ == "__main__":
    unittest.main()
