import http.client
import re
import urllib.error
import unittest
from unittest import mock

import requests

from app.providers import pan115
from app.services import scraper as scraper_service


def _raw_entry(name, fid="", cid="0"):
    item = {"n": name, "s": 123}
    if fid:
        item["fid"] = str(fid)
        item["sha1"] = f"sha-{name}"
        item["pc"] = f"pc-{name}"
    else:
        item["cid"] = str(cid or "0")
    return item


def _page_payload(items, count, state=True):
    return {"state": state, "data": items, "count": count}


def _offset_from_url(url):
    match = re.search(r"offset=(\d+)", str(url))
    return int(match.group(1)) if match else 0


class Pan115ListPaginationTest(unittest.TestCase):
    def setUp(self):
        pan115._api_115_list_cache.clear()
        self.patches = [
            mock.patch.object(pan115, "throttle_115_api_requests"),
            mock.patch.object(pan115, "get_api_115_runtime_tuning", return_value={}),
            mock.patch.object(pan115, "mark_cookie_health_success"),
            mock.patch.object(pan115, "mark_cookie_health_failure"),
        ]
        for patcher in self.patches:
            patcher.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])

    def test_full_mode_merges_pages_sorted_and_complete(self):
        pages = [
            _page_payload(
                [
                    _raw_entry("b.txt", fid="f2"),
                    _raw_entry("A文件夹", cid="c1"),
                ],
                count=4,
            ),
            _page_payload(
                [
                    _raw_entry("a.txt", fid="f1"),
                    _raw_entry("B文件夹", cid="c2"),
                ],
                count=4,
            ),
        ]

        def fake_http(url, **_kwargs):
            return pages[_offset_from_url(url) // 2]

        with mock.patch.object(pan115, "_115_LIST_PAGE_LIMIT_DEFAULT", 2), mock.patch.object(
            pan115, "http_request_json", side_effect=fake_http
        ) as http_mock:
            payload = pan115.list_115_entries_payload("cookie", "0")

        self.assertEqual([item["name"] for item in payload["entries"]], ["A文件夹", "B文件夹", "a.txt", "b.txt"])
        self.assertTrue(payload["entries_complete"])
        self.assertFalse(payload["has_more"])
        self.assertEqual(payload["pages_scanned"], 2)
        self.assertEqual(payload["count"], 4)
        self.assertEqual(payload["next_offset"], 4)
        self.assertEqual(http_mock.call_count, 2)

    def test_paged_mode_returns_single_window_with_metadata(self):
        first_items = [_raw_entry(f"f{i}.txt", fid=f"f{i}") for i in range(20)]
        second_items = [_raw_entry(f"g{i}.txt", fid=f"g{i}") for i in range(20)]
        pages = [
            _page_payload(first_items, count=40),
            _page_payload(second_items, count=40),
        ]

        def fake_http(url, **_kwargs):
            return pages[_offset_from_url(url) // 20]

        with mock.patch.object(pan115, "http_request_json", side_effect=fake_http) as http_mock:
            first = pan115.list_115_entries_payload("cookie", "0", limit=20)
            second = pan115.list_115_entries_payload("cookie", "0", offset=20, limit=20)

        self.assertEqual(len(first["entries"]), 20)
        self.assertEqual(first["entries"][0]["name"], "f0.txt")
        self.assertTrue(first["has_more"])
        self.assertFalse(first["entries_complete"])
        self.assertEqual(first["next_offset"], 20)
        self.assertEqual(second["offset"], 20)
        self.assertEqual(second["entries"][0]["name"], "g0.txt")
        self.assertFalse(second["has_more"])
        self.assertEqual(http_mock.call_count, 2)

    def test_paged_folders_only_scans_until_page_limit_folders(self):
        first_items = [_raw_entry(f"file{i}.txt", fid=f"f{i}") for i in range(10)]
        first_items.extend(_raw_entry(f"文件夹{i}", cid=f"c{i}") for i in range(20))
        second_items = [_raw_entry(f"file2{i}.txt", fid=f"f2{i}") for i in range(5)]
        second_items.append(_raw_entry("文件夹C", cid="cC"))
        pages = [
            _page_payload(first_items, count=37),
            _page_payload(second_items, count=37),
        ]

        def fake_http(url, **_kwargs):
            return pages[_offset_from_url(url) // 30]

        with mock.patch.object(pan115, "http_request_json", side_effect=fake_http) as http_mock:
            first = pan115.list_115_entries_payload("cookie", "0", folders_only=True, limit=20)
            second = pan115.list_115_entries_payload(
                "cookie", "0", folders_only=True, offset=first["next_offset"], limit=20
            )

        self.assertEqual(len(first["entries"]), 20)
        self.assertEqual(first["entries"][0]["name"], "文件夹0")
        self.assertTrue(first["has_more"])
        self.assertEqual(first["next_offset"], 30)
        self.assertEqual([item["name"] for item in second["entries"]], ["文件夹C"])
        self.assertFalse(second["has_more"])
        self.assertFalse(second["entries_complete"])
        self.assertEqual(http_mock.call_count, 2)

    def test_retries_incomplete_read_then_succeeds(self):
        calls = []

        def flaky_http(url, **_kwargs):
            calls.append(url)
            if len(calls) == 1:
                raise http.client.IncompleteRead(b"")
            return _page_payload([_raw_entry("a.txt", fid="f1")], count=1)

        with mock.patch.object(pan115, "http_request_json", side_effect=flaky_http), mock.patch.object(
            pan115, "time", wraps=pan115.time
        ) as time_mock:
            payload = pan115.list_115_entries_payload("cookie", "0")

        self.assertEqual(len(payload["entries"]), 1)
        self.assertEqual(len(calls), 2)
        self.assertTrue(time_mock.sleep.called)

    def test_shrinks_page_size_when_large_page_truncated(self):
        calls = []

        def flaky(url, **_kwargs):
            calls.append(url)
            match = re.search(r"limit=(\d+)", str(url))
            limit = int(match.group(1)) if match else 0
            if limit > 100:
                raise http.client.IncompleteRead(b"")
            return _page_payload([_raw_entry("a.txt", fid="f1")], count=1)

        with mock.patch.object(pan115, "http_request_json", side_effect=flaky), mock.patch.object(
            pan115, "time", wraps=pan115.time
        ) as time_mock:
            payload = pan115.list_115_entries_payload("cookie", "0")

        self.assertEqual(len(payload["entries"]), 1)
        self.assertTrue(any("limit=100" in url for url in calls))
        self.assertTrue(time_mock.sleep.called)

    def test_does_not_retry_http_error(self):
        def http_405(_url, **_kwargs):
            raise urllib.error.HTTPError("https://aps.115.com/", 405, "blocked", None, None)

        with mock.patch.object(pan115, "http_request_json", side_effect=http_405) as http_mock:
            with self.assertRaises(urllib.error.HTTPError):
                pan115.list_115_entries_payload("cookie", "0")
        self.assertEqual(http_mock.call_count, 1)

    def test_hits_max_pages_cap_marks_incomplete(self):
        def full_page(_url, **_kwargs):
            return _page_payload(
                [_raw_entry(f"f{i}", fid=f"f{i}") for i in range(2)],
                count=100,
            )

        with mock.patch.object(pan115, "_115_LIST_PAGE_LIMIT_DEFAULT", 2), mock.patch.object(
            pan115, "_115_LIST_MAX_PAGES", 1
        ), mock.patch.object(pan115, "http_request_json", side_effect=full_page):
            payload = pan115.list_115_entries_payload("cookie", "0")

        self.assertFalse(payload["entries_complete"])
        self.assertTrue(payload["has_more"])
        self.assertEqual(payload["pages_scanned"], 1)

    def test_full_mode_cached_but_paged_mode_not_cached(self):
        def fake_http(_url, **_kwargs):
            return _page_payload([_raw_entry("a.txt", fid="f1")], count=1)

        with mock.patch.object(pan115, "http_request_json", side_effect=fake_http) as http_mock:
            first = pan115.list_115_entries_payload("cookie", "0")
            second = pan115.list_115_entries_payload("cookie", "0")
            self.assertEqual(first["entries"], second["entries"])
            self.assertEqual(http_mock.call_count, 1)

            paged_first = pan115.list_115_entries_payload("cookie", "0", limit=20)
            paged_second = pan115.list_115_entries_payload("cookie", "0", limit=20)
            self.assertEqual(paged_first["entries"], paged_second["entries"])
            self.assertEqual(http_mock.call_count, 3)

    def test_search_entries_builds_official_endpoint_and_normalizes(self):
        captured = {}

        def fake_webapi(url, **_kwargs):
            captured["url"] = url
            return {
                "state": True,
                "data": [
                    _raw_entry("命中.txt", fid="f1"),
                    _raw_entry("命中目录", cid="c1"),
                ],
                "count": 2,
            }

        with mock.patch.object(pan115, "_request_115_webapi_json", side_effect=fake_webapi) as webapi_mock:
            payload = pan115.search_115_entries("cookie", "0", "命中")

        self.assertIn("/files/search", captured["url"])
        self.assertIn("search_value=", captured["url"])
        self.assertEqual([item["name"] for item in payload["entries"]], ["命中.txt", "命中目录"])
        self.assertTrue(payload["search"])
        self.assertFalse(payload["has_more"])
        self.assertEqual(webapi_mock.call_count, 1)

    def test_search_entries_retries_connection_error(self):
        calls = []

        def flaky_webapi(url, **_kwargs):
            calls.append(url)
            if len(calls) == 1:
                raise requests.exceptions.ConnectionError("Connection broken: IncompleteRead(1 bytes read)")
            return {"state": True, "data": [_raw_entry("a.txt", fid="f1")], "count": 1}

        with mock.patch.object(pan115, "_request_115_webapi_json", side_effect=flaky_webapi):
            payload = pan115.search_115_entries("cookie", "0", "a")

        self.assertEqual(len(payload["entries"]), 1)
        self.assertEqual(len(calls), 2)

    def test_rename_115_entries_posts_multiple_names_in_one_request(self):
        with mock.patch.object(
            pan115, "http_request_form_json", return_value={"state": True}
        ) as form_mock, mock.patch.object(pan115, "invalidate_115_entries_cache"):
            result = pan115.rename_115_entries("cookie", {"f1": "甲", "f2": "乙"}, parent_cid="p1")

        self.assertEqual(form_mock.call_count, 1)
        payload = form_mock.call_args[0][1] if form_mock.call_args else {}
        self.assertEqual(payload, {"files_new_name[f1]": "甲", "files_new_name[f2]": "乙"})
        self.assertEqual(result["renames"], {"f1": "甲", "f2": "乙"})

    def test_rename_115_entry_single_wraps_batch(self):
        with mock.patch.object(
            pan115, "http_request_form_json", return_value={"state": True}
        ) as form_mock, mock.patch.object(pan115, "invalidate_115_entries_cache"):
            result = pan115.rename_115_entry("cookie", "f1", "甲", "p1")

        self.assertEqual(form_mock.call_count, 1)
        payload = form_mock.call_args[0][1] if form_mock.call_args else {}
        self.assertEqual(payload, {"files_new_name[f1]": "甲"})
        self.assertEqual(result["id"], "f1")
        self.assertEqual(result["name"], "甲")


class ScraperEntriesSearchTest(unittest.TestCase):
    def setUp(self):
        self.patches = [
            mock.patch.object(scraper_service, "_require_provider_cookie", return_value="cookie"),
            mock.patch.object(scraper_service, "_invalidate_provider_parent"),
        ]
        for patcher in self.patches:
            patcher.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])

    def test_list_scraper_entries_uses_official_search(self):
        search_payload = {
            "entries": [
                {"id": "f1", "name": "命中.txt", "is_dir": False, "cid": "", "fid": "f1"},
                {"id": "c1", "name": "命中目录", "is_dir": True, "cid": "c1", "fid": ""},
            ],
            "summary": {"folder_count": 1, "file_count": 1},
            "count": 2,
            "offset": 0,
            "next_offset": 2,
            "has_more": False,
            "entries_complete": True,
        }
        with mock.patch.object(scraper_service, "search_115_entries", return_value=search_payload) as search_mock:
            payload = scraper_service.list_scraper_entries("115", "0", False, "命中", 0, 300)

        search_mock.assert_called_once()
        self.assertEqual(payload["search_source"], "official")
        self.assertEqual(payload["search"], True)
        self.assertEqual(len(payload["entries"]), 2)
        self.assertFalse(payload["has_more"])

    def test_list_scraper_entries_falls_back_to_local_filter(self):
        list_payload = {
            "entries": [
                {"id": "f1", "name": "命中.txt", "is_dir": False, "cid": "", "fid": "f1"},
                {"id": "f2", "name": "其他.txt", "is_dir": False, "cid": "", "fid": "f2"},
            ],
            "summary": {"folder_count": 0, "file_count": 2},
            "count": 2,
            "offset": 0,
            "next_offset": 2,
            "has_more": False,
            "entries_complete": True,
        }
        with mock.patch.object(scraper_service, "search_115_entries", side_effect=RuntimeError("搜索失败")), mock.patch.object(
            scraper_service, "_list_provider_entries_payload", return_value=list_payload
        ) as list_mock:
            payload = scraper_service.list_scraper_entries("115", "0", False, "命中", 0, 300)

        list_mock.assert_called_once()
        self.assertEqual(payload["search_source"], "local")
        self.assertEqual([item["name"] for item in payload["entries"]], ["命中.txt"])


if __name__ == "__main__":
    unittest.main()
