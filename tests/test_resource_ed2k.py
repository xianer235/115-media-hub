import unittest
import json
from unittest import mock

import requests


from app import resource_ed2k as resource_ed2k_module
from app.resource_ed2k import (
    extract_ed2k_items,
    extract_ed2k_page_title,
    parse_ed2k_link,
    resolve_ed2k_page,
)
from app.resource_linking import (
    detect_resource_link_type,
    extract_resource_candidates,
    extract_resource_links,
)
from app.resource_tg import parse_telegram_posts_page
from app.routes import resource as resource_routes


SAMPLE_LINK = (
    "ed2k://|file|摇滚兄弟私生活.2024 - S03E08 - 第 8 集 - "
    "2160p.Netflix.WEB-DL.DV.H265.DDP 5.1.{tmdb-254721}.mkv|"
    "7848651243|af33bd45b385b16a4bef434c760e0182|/"
)
TELEGRA_SAMPLE_LINKS = [
    "ed2k://|file|摇滚兄弟私生活.2024 - S03E08 - 第 8 集 - 2160p.Netflix.WEB-DL.DV.H265.DDP 5.1.{tmdb-254721}.mkv|7848651243|af33bd45b385b16a4bef434c760e0182|/",
    "ed2k://|file|摇滚兄弟私生活.2024 - S03E07 - 第 7 集 - 2160p.Netflix.WEB-DL.DV.H265.DDP 5.1.{tmdb-254721}.mkv|6646256336|a93b3760ed987f48e95dc5e36ea49fee|/",
    "ed2k://|file|摇滚兄弟私生活.2024 - S03E06 - 第 6 集 - 2160p.Netflix.WEB-DL.DV.H265.DDP 5.1.{tmdb-254721}.mkv|6314658524|55bc88c985b9b2952088cfad32776101|/",
    "ed2k://|file|摇滚兄弟私生活.2024 - S03E05 - 第 5 集 - 2160p.Netflix.WEB-DL.DV.H265.DDP 5.1.{tmdb-254721}.mkv|7708858319|08062feaebb5bf81baf738528002790c|/",
    "ed2k://|file|摇滚兄弟私生活.2024 - S03E04 - 第 4 集 - 2160p.Netflix.WEB-DL.DV.H265.DDP 5.1.{tmdb-254721}.mkv|6335725373|127c2b5d9c570aaf09b8b83645f62c72|/",
    "ed2k://|file|摇滚兄弟私生活.2024 - S03E03 - 第 3 集 - 2160p.Netflix.WEB-DL.DV.H265.DDP 5.1.{tmdb-254721}.mkv|6219197216|84f4c1ce5da0d4fa573d2600b1b6cecb|/",
    "ed2k://|file|摇滚兄弟私生活.2024 - S03E02 - 第 2 集 - 2160p.Netflix.WEB-DL.DV.H265.DDP 5.1.{tmdb-254721}.mkv|7609066339|81d1c370d7b3864bc9f0885cf3ee9f73|/",
    "ed2k://|file|摇滚兄弟私生活.2024 - S03E01 - 第 1 集 - 2160p.Netflix.WEB-DL.DV.H265.DDP 5.1.{tmdb-254721}.mkv|6334246284|71e56942f43653b6794f1dd710184732|/",
]


def public_dns(_host, port, **_kwargs):
    return [(2, 1, 6, "", ("93.184.216.34", port))]


class FakeResponse:
    def __init__(self, body="", status_code=200, headers=None):
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}
        self.encoding = "utf-8"
        self._body = body.encode("utf-8")
        self.closed = False

    def iter_content(self, chunk_size=65536):
        for offset in range(0, len(self._body), chunk_size):
            yield self._body[offset:offset + chunk_size]

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.trust_env = True

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class ResourceEd2kParsingTest(unittest.TestCase):
    def test_parse_ed2k_link_rejects_invalid_hash(self):
        with self.assertRaisesRegex(ValueError, "哈希"):
            parse_ed2k_link("ed2k://|file|第 1 集.mkv|1024|bad|/")

    def test_parse_ed2k_file_link_returns_file_metadata(self):
        item = parse_ed2k_link(SAMPLE_LINK)

        self.assertEqual(
            item["filename"],
            "摇滚兄弟私生活.2024 - S03E08 - 第 8 集 - 2160p.Netflix.WEB-DL.DV.H265.DDP 5.1.{tmdb-254721}.mkv",
        )
        self.assertEqual(item["size_bytes"], 7848651243)
        self.assertEqual(item["file_hash"], "af33bd45b385b16a4bef434c760e0182")
        self.assertEqual(item["link_url"], SAMPLE_LINK)

    def test_extract_ed2k_items_deduplicates_by_hash_and_size(self):
        duplicate_with_other_name = SAMPLE_LINK.replace("摇滚兄弟私生活.2024", "另一个文件名")
        html = f"<p>{SAMPLE_LINK}</p><p>{duplicate_with_other_name}</p><p>ed2k://|file|broken|1|bad|/</p>"

        items = extract_ed2k_items(html)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["filename"], parse_ed2k_link(SAMPLE_LINK)["filename"])

    def test_extract_ed2k_items_separates_links_on_same_line(self):
        second_link = SAMPLE_LINK.replace("S03E08", "S03E07").replace(
            "af33bd45b385b16a4bef434c760e0182",
            "a93b3760ed987f48e95dc5e36ea49fee",
        )

        items = extract_ed2k_items(f"<p>{SAMPLE_LINK} {second_link}</p>")

        self.assertEqual([item["link_url"] for item in items], [SAMPLE_LINK, second_link])

    def test_extracts_all_eight_files_from_supplied_telegra_sample(self):
        html = "<h1>摇滚兄弟私生活 (2024) - S03E01-E08(完结)</h1>\n" + "\n".join(TELEGRA_SAMPLE_LINKS)

        items = extract_ed2k_items(html)

        self.assertEqual(len(items), 8)
        self.assertEqual(items[0]["filename"], parse_ed2k_link(TELEGRA_SAMPLE_LINKS[0])["filename"])
        self.assertEqual(items[-1]["filename"], parse_ed2k_link(TELEGRA_SAMPLE_LINKS[-1])["filename"])

    def test_extract_page_title_prefers_visible_heading(self):
        html = """
        <html><head><title>站点标题</title><meta property="og:title" content="分享标题"></head>
        <body><h1>摇滚兄弟私生活 (2024) - S03E01-E08(完结)</h1></body></html>
        """

        title = extract_ed2k_page_title(html, fallback="频道标题")

        self.assertEqual(title, "摇滚兄弟私生活 (2024) - S03E01-E08(完结)")

    def test_extract_page_title_falls_back_to_channel_title(self):
        self.assertEqual(extract_ed2k_page_title("<html></html>", fallback="频道资源标题"), "频道资源标题")

    def test_resolve_page_uses_existing_proxy_configuration(self):
        session = FakeSession([FakeResponse(f"<h1>整季标题</h1><p>{SAMPLE_LINK}</p>")])
        cfg = {
            "tg_proxy_enabled": True,
            "tg_proxy_protocol": "http",
            "tg_proxy_host": "127.0.0.1",
            "tg_proxy_port": "7890",
        }

        result = resolve_ed2k_page(
            "https://example.com/share",
            cfg,
            session=session,
            dns_resolver=public_dns,
        )

        self.assertEqual(result["title"], "整季标题")
        self.assertEqual(len(result["items"]), 1)
        self.assertTrue(result["proxy_used"])
        self.assertEqual(
            session.calls[0][1]["proxies"],
            {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"},
        )
        self.assertFalse(session.trust_env)

    def test_resolve_page_rejects_private_target_before_request(self):
        session = FakeSession([])

        with self.assertRaisesRegex(ValueError, "公网"):
            resolve_ed2k_page(
                "http://127.0.0.1/resource",
                {},
                session=session,
                dns_resolver=public_dns,
            )

        self.assertEqual(session.calls, [])

    def test_resolve_page_revalidates_redirect_target(self):
        session = FakeSession(
            [
                FakeResponse(status_code=302, headers={"Location": "http://192.168.1.2/private"}),
            ]
        )

        with self.assertRaisesRegex(ValueError, "公网"):
            resolve_ed2k_page(
                "https://example.com/share",
                {},
                session=session,
                dns_resolver=public_dns,
            )

        self.assertEqual(len(session.calls), 1)


class ResourceEd2kFolderNameTest(unittest.TestCase):
    def normalizer(self):
        normalizer = getattr(resource_ed2k_module, "normalize_ed2k_folder_name", None)
        self.assertIsNotNone(normalizer, "缺少 ED2K 文件夹名称规范化函数")
        return normalizer

    def test_preserves_colon_and_replaces_cross_platform_unsafe_characters(self):
        self.assertEqual(
            self.normalizer()('  碟中谍: 最终清算 / *?"<>|  '),
            "碟中谍: 最终清算 ＊？＂＜＞｜",
        )

    def test_handles_controls_fallback_and_length(self):
        normalize = self.normalizer()

        self.assertEqual(normalize("片\x01名"), "片名")
        self.assertEqual(normalize(".."), "")
        self.assertEqual(normalize("..", fallback="未命名"), "未命名")
        self.assertEqual(normalize("片" * 121), "片" * 120)


class ResourceEd2kLinkingRegressionTest(unittest.TestCase):
    def test_guangya_share_urls_remain_generic_links_for_operations(self):
        for url in (
            "https://www.guangyapan.com/share/abc_123",
            "https://guangyapan.com/s/abc-123?pwd=1234",
            "https://www.guangyapan.com/link/abc123",
            "https://guangyapan.com/download/abc123",
        ):
            self.assertEqual(detect_resource_link_type(url), "link")
        self.assertEqual(detect_resource_link_type("https://www.guangyapan.com/"), "link")

    def test_extract_resource_links_keeps_ed2k_filename_spaces(self):
        links = extract_resource_links(f"资源如下：\n{SAMPLE_LINK}")

        self.assertEqual(links, [SAMPLE_LINK])

    def test_extract_resource_links_separates_ed2k_links_on_same_line(self):
        second_link = SAMPLE_LINK.replace("S03E08", "S03E07").replace(
            "af33bd45b385b16a4bef434c760e0182",
            "a93b3760ed987f48e95dc5e36ea49fee",
        )

        links = extract_resource_links(f"{SAMPLE_LINK} {second_link}")

        self.assertEqual(links, [SAMPLE_LINK, second_link])

    def test_telegra_page_stays_a_normal_external_link_during_channel_parse(self):
        page_url = (
            "https://telegra.ph/"
            "电视剧摇滚兄弟私生活-2024---S03E01-E08完结-07-24"
        )
        raw_text = "\n".join(
            (
                "📺 电视剧：摇滚兄弟私生活 (2024) - S03E01-E08(完结)",
                "🔗 链接:",
                page_url,
                "#综艺",
            )
        )

        candidates = extract_resource_candidates(raw_text, source_type="tg")

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["link_url"], page_url)
        self.assertEqual(candidates[0]["link_type"], "link")

    def test_tg_channel_post_recognizes_direct_single_file_ed2k(self):
        link = (
            "ed2k://|file|寒战1994 (2026) - 2160p.WEB-DL.DV.H265.DTS."
            "{tmdb-1499071}.mkv|28700476657|01aae290682a3cd7a041c0b0a4634ca2|/"
        )
        raw_text = "\n".join(
            (
                "🎬 电影：寒战1994 (2026)",
                "🍿 TMDB ID: 1499071",
                "🔗 链接:",
                link,
                "#华语电影",
            )
        )
        html = (
            '<div class="tgme_widget_message" data-post="movies/1">'
            f'<div class="tgme_widget_message_text">{raw_text.replace(chr(10), "<br>")}</div>'
            "</div>"
        )

        post = parse_telegram_posts_page(
            html,
            {"channel_id": "movies", "name": "电影频道"},
            limit=10,
        )["posts"][0]

        self.assertEqual(post["link_url"], link)
        self.assertEqual(post["link_type"], "ed2k")
        self.assertEqual(post["title"], "🎬 电影：寒战1994 (2026)")
        self.assertIn(link, post["extra"]["all_links"])


class FakeJsonRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


class ResourceEd2kResolveRouteTest(unittest.IsolatedAsyncioTestCase):
    def resolve_endpoint(self):
        endpoint = next(
            (
                route.endpoint
                for route in resource_routes.router.routes
                if getattr(route, "path", "") == "/resource/ed2k/resolve"
                and "POST" in getattr(route, "methods", set())
            ),
            None,
        )
        self.assertIsNotNone(endpoint, "POST /resource/ed2k/resolve 尚未注册")
        return endpoint

    @staticmethod
    def response_json(response):
        return json.loads(response.body.decode("utf-8"))

    async def test_resolve_endpoint_uses_current_config_and_resource_title(self):
        endpoint = self.resolve_endpoint()
        resolved = {
            "source_url": "https://example.com/share",
            "final_url": "https://example.com/final",
            "title": "页面标题",
            "items": [{"filename": "第 1 集.mkv", "link_url": SAMPLE_LINK}],
            "item_count": 1,
            "proxy_used": True,
        }
        config = {"tg_proxy_enabled": True, "tg_proxy_host": "127.0.0.1"}

        with mock.patch.object(resource_routes, "get_config", return_value=config), mock.patch.object(
            resource_routes,
            "resolve_ed2k_page",
            return_value=resolved,
        ) as resolver:
            response = await endpoint(
                FakeJsonRequest(
                    {
                        "url": "https://example.com/share",
                        "resource_title": "频道资源标题",
                    }
                )
            )

        self.assertEqual(response, {"ok": True, **resolved})
        resolver.assert_called_once_with(
            "https://example.com/share",
            config,
            fallback_title="频道资源标题",
        )

    async def test_resolve_endpoint_accepts_fallback_title_alias(self):
        endpoint = self.resolve_endpoint()
        resolved = {
            "source_url": "https://example.com/share",
            "final_url": "https://example.com/share",
            "title": "候选标题",
            "items": [],
            "item_count": 0,
            "proxy_used": False,
        }

        with mock.patch.object(resource_routes, "get_config", return_value={}), mock.patch.object(
            resource_routes,
            "resolve_ed2k_page",
            return_value=resolved,
        ) as resolver:
            response = await endpoint(
                FakeJsonRequest(
                    {
                        "url": "https://example.com/share",
                        "fallback_title": "候选标题",
                    }
                )
            )

        self.assertTrue(response["ok"])
        resolver.assert_called_once_with(
            "https://example.com/share",
            {},
            fallback_title="候选标题",
        )

    async def test_resolve_endpoint_rejects_missing_url_without_fetching(self):
        endpoint = self.resolve_endpoint()

        with mock.patch.object(resource_routes, "resolve_ed2k_page") as resolver:
            response = await endpoint(FakeJsonRequest({"resource_title": "标题"}))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            self.response_json(response),
            {"ok": False, "msg": "请填写 ED2K 资源外链"},
        )
        resolver.assert_not_called()

    async def test_resolve_endpoint_returns_clear_client_error(self):
        endpoint = self.resolve_endpoint()

        with mock.patch.object(resource_routes, "get_config", return_value={}), mock.patch.object(
            resource_routes,
            "resolve_ed2k_page",
            side_effect=ValueError("外链必须指向公网地址"),
        ):
            response = await endpoint(FakeJsonRequest({"url": "http://127.0.0.1/private"}))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            self.response_json(response),
            {"ok": False, "msg": "外链必须指向公网地址"},
        )

    async def test_resolve_endpoint_maps_connection_failure_to_client_error(self):
        endpoint = self.resolve_endpoint()

        with mock.patch.object(resource_routes, "get_config", return_value={}), mock.patch.object(
            resource_routes,
            "resolve_ed2k_page",
            side_effect=requests.ConnectionError("代理连接失败"),
        ):
            response = await endpoint(FakeJsonRequest({"url": "https://example.com/share"}))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            self.response_json(response),
            {"ok": False, "msg": "资源外链请求失败：代理连接失败"},
        )


if __name__ == "__main__":
    unittest.main()
