import http.client
import re
import urllib.error
import unittest
from unittest import mock

import requests

from app.providers import pan115
from app.services import scraper as scraper_service


def _raw_entry(name, fid="", cid="0", pid=""):
    item = {"n": name, "s": 123}
    if fid:
        item["fid"] = str(fid)
        item["sha1"] = f"sha-{name}"
        item["pc"] = f"pc-{name}"
    else:
        item["cid"] = str(cid or "0")
    if pid:
        item["pid"] = str(pid)
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
                    _raw_entry("命中.txt", fid="f1", pid="p1"),
                    _raw_entry("命中目录", cid="c1", pid="p2"),
                ],
                "count": 2,
            }

        with mock.patch.object(pan115, "_request_115_webapi_json", side_effect=fake_webapi) as webapi_mock:
            payload = pan115.search_115_entries("cookie", "0", "命中")

        self.assertIn("/files/search", captured["url"])
        self.assertIn("search_value=", captured["url"])
        self.assertEqual([item["name"] for item in payload["entries"]], ["命中.txt", "命中目录"])
        self.assertEqual([item["parent_id"] for item in payload["entries"]], ["p1", "p2"])
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

    def test_resolve_115_folder_path_builds_ancestors_from_medialist(self):
        captured = {}

        def fake_webapi(url, **_kwargs):
            captured["url"] = url
            return {
                "state": True,
                "path": [
                    {"cid": "p1", "name": "115自存电视剧", "pid": "0"},
                    {"cid": "c1", "name": "狂飙 (2023) [tmdbid-210757]", "pid": "p1"},
                ],
                "data": [],
            }

        with mock.patch.object(pan115, "_request_115_webapi_json", side_effect=fake_webapi) as webapi_mock:
            payload = pan115.resolve_115_folder_path("cookie", "c1")

        self.assertIn("/files/medialist", captured["url"])
        self.assertIn("cid=c1", captured["url"])
        self.assertEqual(
            payload["ancestors"],
            [
                {"id": "p1", "name": "115自存电视剧", "parent_id": "0"},
                {"id": "c1", "name": "狂飙 (2023) [tmdbid-210757]", "parent_id": "p1"},
            ],
        )
        self.assertEqual(payload["path"], "115自存电视剧/狂飙 (2023) [tmdbid-210757]")
        self.assertEqual(webapi_mock.call_count, 1)

    def test_resolve_115_folder_path_root_returns_empty_without_request(self):
        with mock.patch.object(pan115, "_request_115_webapi_json") as webapi_mock:
            payload = pan115.resolve_115_folder_path("cookie", "0")

        self.assertEqual(payload["cid"], "0")
        self.assertEqual(payload["path"], "")
        self.assertEqual(payload["ancestors"], [])
        webapi_mock.assert_not_called()

    def test_resolve_115_folder_path_raises_when_medialist_fails(self):
        with mock.patch.object(pan115, "_request_115_webapi_json", return_value={"state": False, "error": "boom"}):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                pan115.resolve_115_folder_path("cookie", "c1")

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

    def test_list_scraper_entries_official_search_marks_unknown_path(self):
        search_payload = {
            "entries": [
                {"id": "c1", "name": "命中目录", "is_dir": True, "cid": "c1", "fid": ""},
                {
                    "id": "c2",
                    "name": "带路径目录",
                    "is_dir": True,
                    "cid": "c2",
                    "fid": "",
                    "parent_id": "p_real",
                    "path": "真实/上级/带路径目录",
                },
            ],
            "summary": {"folder_count": 2, "file_count": 0},
            "count": 2,
            "offset": 0,
            "next_offset": 2,
            "has_more": False,
            "entries_complete": True,
        }
        with mock.patch.object(scraper_service, "search_115_entries", return_value=search_payload):
            payload = scraper_service.list_scraper_entries("115", "current_dir", False, "命中", 0, 300)

        entries = {item["id"]: item for item in payload["entries"]}
        self.assertTrue(entries["c1"]["search_result"])
        self.assertTrue(entries["c1"]["path_unknown"])
        self.assertEqual(entries["c1"]["parent_id"], "")
        self.assertEqual(entries["c1"]["path"], "命中目录")
        self.assertTrue(entries["c2"]["search_result"])
        self.assertFalse(entries["c2"]["path_unknown"])
        self.assertEqual(entries["c2"]["parent_id"], "p_real")
        self.assertEqual(entries["c2"]["path"], "真实/上级/带路径目录")

    def test_resolve_scraper_folder_path_115_uses_provider_resolver(self):
        resolved = {
            "cid": "c1",
            "path": "115自存电视剧/狂飙 (2023) [tmdbid-210757]",
            "ancestors": [
                {"id": "p1", "name": "115自存电视剧", "parent_id": "0"},
                {"id": "c1", "name": "狂飙 (2023) [tmdbid-210757]", "parent_id": "p1"},
            ],
        }
        with mock.patch.object(scraper_service, "resolve_115_folder_path", return_value=resolved) as resolver_mock:
            payload = scraper_service.resolve_scraper_folder_path("115", "c1")

        resolver_mock.assert_called_once_with("cookie", "c1")
        self.assertEqual(payload["path"], resolved["path"])
        self.assertEqual(payload["ancestors"], resolved["ancestors"])

    def test_resolve_scraper_folder_path_non_115_returns_empty(self):
        payload = scraper_service.resolve_scraper_folder_path("quark", "c1")

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["provider"], "quark")
        self.assertEqual(payload["path"], "")
        self.assertEqual(payload["ancestors"], [])


class Pan115MoveAcceptanceTest(unittest.TestCase):
    """115 写操作是"受理 + 排队执行"：忙响应要退避重试，受理后还要回验真的落地。

    回归场景：一次整理多部影视时，同一账号上一批移动还没跑完，接口返回
    ``990019 移动[...]操作尚未执行完成``。旧实现直接当失败，重试三次后整条报错，
    而此时监控同步已经先扫了一轮目录。
    """

    BUSY_MOVE = {
        "state": False,
        "errno": 990019,
        "error": "移动[xxx]操作尚未执行完成，请稍后再试！",
    }

    def test_busy_response_is_retried_with_backoff_and_same_move_proid(self):
        responses = [dict(self.BUSY_MOVE), {"state": True}]
        with mock.patch.object(pan115, "http_request_form_json", side_effect=responses) as request, \
                mock.patch.object(pan115, "throttle_115_api_requests"), \
                mock.patch.object(pan115.time, "sleep") as sleeper, \
                mock.patch.object(pan115, "invalidate_115_entries_cache"), \
                mock.patch.object(pan115, "mark_cookie_health_success"), \
                mock.patch.object(pan115, "mark_cookie_health_failure"):
            result = pan115.move_115_entries("cookie-value", ["e1", "e2"], "target-cid", "source-cid")

        self.assertEqual(request.call_count, 2)
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(result["retry_wait_seconds"], 1.0)
        sleeper.assert_called_once_with(1.0)
        first_payload = request.call_args_list[0].args[1]
        second_payload = request.call_args_list[1].args[1]
        # 同一个 move_proid 跨重试复用：115 按它记 move_progress，也靠它去重。
        self.assertTrue(first_payload["move_proid"])
        self.assertEqual(first_payload["move_proid"], second_payload["move_proid"])
        self.assertEqual(result["move_proid"], first_payload["move_proid"])

    def test_busy_response_exhausts_retries_then_raises(self):
        with mock.patch.object(pan115, "http_request_form_json", return_value=dict(self.BUSY_MOVE)) as request, \
                mock.patch.object(pan115, "throttle_115_api_requests"), \
                mock.patch.object(pan115.time, "sleep"), \
                mock.patch.object(pan115, "mark_cookie_health_success"), \
                mock.patch.object(pan115, "mark_cookie_health_failure"):
            with self.assertRaises(RuntimeError) as ctx:
                pan115.move_115_entries("cookie-value", ["e1"], "target-cid")

        self.assertEqual(request.call_count, 5)
        self.assertIn("尚未执行完成", str(ctx.exception))

    def test_busy_errno_table_matches_p115client(self):
        for errno in (990005, 990009, 990019, 590075, 51012):
            self.assertTrue(pan115._is_115_busy_write_response({"state": False, "errno": errno}))
        self.assertFalse(pan115._is_115_busy_write_response({"state": True}))
        self.assertFalse(pan115._is_115_busy_write_response({"state": False, "errno": 990001}))
        # 老接口用文案而不是 errno 表达同一个意思。
        self.assertTrue(
            pan115._is_115_busy_write_response({"state": False, "error": "操作太频繁，请稍后再试"})
        )

    def test_move_progress_polls_until_completed(self):
        responses = [{"state": True, "progress": 40}, {"state": True, "progress": 100}]
        with mock.patch.object(pan115, "_request_115_webapi_json", side_effect=responses), \
                mock.patch.object(pan115, "throttle_115_api_requests"), \
                mock.patch.object(pan115.time, "sleep"):
            progress = pan115.wait_115_move_progress(
                "cookie-value",
                "42",
                timeout_seconds=5,
                interval_seconds=0.5,
            )

        self.assertEqual(progress["status"], "completed")
        self.assertEqual(progress["progress"], 100)
        self.assertEqual(progress["polls"], 2)

    def test_move_progress_missing_task_record_is_not_a_failure(self):
        with mock.patch.object(pan115, "_request_115_webapi_json", return_value={"state": False, "errno": 990003}), \
                mock.patch.object(pan115, "throttle_115_api_requests"), \
                mock.patch.object(pan115.time, "sleep"):
            progress = pan115.wait_115_move_progress("cookie-value", "42", timeout_seconds=5)

        self.assertEqual(progress["status"], "unknown")

    def test_move_progress_timeout_keeps_last_progress(self):
        with mock.patch.object(pan115, "_request_115_webapi_json", return_value={"state": True, "progress": 30}), \
                mock.patch.object(pan115, "throttle_115_api_requests"), \
                mock.patch.object(pan115.time, "sleep"):
            progress = pan115.wait_115_move_progress(
                "cookie-value",
                "42",
                timeout_seconds=0,
                interval_seconds=0.5,
            )

        self.assertEqual(progress["status"], "timeout")
        self.assertEqual(progress["progress"], 30)

    def test_landing_pending_when_entry_is_still_under_source_parent(self):
        with mock.patch.object(
            pan115,
            "get_115_file_info",
            return_value={"parent_id": "old-cid", "name": "新名字"},
        ), mock.patch.object(pan115, "throttle_115_api_requests"), \
                mock.patch.object(pan115.time, "sleep"):
            landing = pan115.wait_115_writes_landed(
                "cookie-value",
                [{"id": "e1", "parent_id": "target-cid", "name": "新名字", "source_parent_id": "old-cid"}],
            )

        self.assertEqual(landing["status"], "pending")
        self.assertEqual(landing["pending_ids"], ["e1"])
        self.assertEqual(landing["attempts"], pan115._115_LANDING_VERIFY_ROUNDS)

    def test_landing_landed_when_parent_and_name_match(self):
        with mock.patch.object(
            pan115,
            "get_115_file_info",
            return_value={"parent_id": "target-cid", "name": "新名字"},
        ), mock.patch.object(pan115, "throttle_115_api_requests"), \
                mock.patch.object(pan115.time, "sleep"):
            landing = pan115.wait_115_writes_landed(
                "cookie-value",
                [{"id": "e1", "parent_id": "target-cid", "name": "新名字"}],
            )

        self.assertEqual(landing["status"], "landed")
        self.assertEqual(landing["pending_ids"], [])

    def test_landing_falls_back_to_source_removal_when_get_info_fails(self):
        with mock.patch.object(
            pan115,
            "get_115_file_info",
            side_effect=RuntimeError("115 文件不存在或已删除：e1"),
        ), mock.patch.object(pan115, "_verify_115_entries_removed", return_value=True), \
                mock.patch.object(pan115, "throttle_115_api_requests"), \
                mock.patch.object(pan115.time, "sleep"):
            landing = pan115.wait_115_writes_landed(
                "cookie-value",
                [{"id": "e1", "parent_id": "target-cid", "source_parent_id": "old-cid"}],
            )

        self.assertEqual(landing["status"], "landed")

    def test_landing_unknown_when_neither_side_can_be_confirmed(self):
        with mock.patch.object(pan115, "get_115_file_info", side_effect=RuntimeError("boom")), \
                mock.patch.object(pan115, "_verify_115_entries_removed", return_value=False), \
                mock.patch.object(pan115, "throttle_115_api_requests"), \
                mock.patch.object(pan115.time, "sleep"):
            landing = pan115.wait_115_writes_landed(
                "cookie-value",
                [{"id": "e1", "parent_id": "target-cid", "source_parent_id": "old-cid"}],
            )

        self.assertEqual(landing["status"], "unknown")
        self.assertEqual(landing["unknown_ids"], ["e1"])
        self.assertEqual(landing["pending_ids"], [])

    def test_get_file_info_reads_parent_from_cid_for_files_and_pid_for_folders(self):
        with mock.patch.object(
            pan115,
            "_request_115_webapi_json",
            return_value={"state": True, "data": [{"fid": "f1", "n": "Episode.mkv", "cid": "parent-1"}]},
        ):
            file_info = pan115.get_115_file_info("cookie-value", "f1")
        with mock.patch.object(
            pan115,
            "_request_115_webapi_json",
            return_value={"state": True, "data": [{"cid": "d1", "n": "片名 (2026)", "pid": "parent-2"}]},
        ):
            folder_info = pan115.get_115_file_info("cookie-value", "d1")

        self.assertEqual((file_info["parent_id"], file_info["is_dir"]), ("parent-1", False))
        self.assertEqual((folder_info["parent_id"], folder_info["is_dir"]), ("parent-2", True))

    def test_entries_beyond_verify_cap_follow_server_progress(self):
        """一批 100 条时只逐条回验前 50 条：超出的部分按服务端进度兜底，没跑完不算落地。"""
        cap = pan115._115_LANDING_VERIFY_MAX_ENTRIES
        expects = [{"id": f"e{index}", "parent_id": "target-cid"} for index in range(cap + 2)]

        with mock.patch.object(
            pan115,
            "get_115_file_info",
            return_value={"parent_id": "target-cid", "name": ""},
        ), mock.patch.object(
            pan115,
            "wait_115_move_progress",
            return_value={"status": "timeout", "progress": 60},
        ), mock.patch.object(pan115, "throttle_115_api_requests"), \
                mock.patch.object(pan115.time, "sleep"):
            landing = pan115.wait_115_writes_landed("cookie-value", expects, move_proid="42")

        self.assertEqual(landing["status"], "pending")
        self.assertEqual(landing["pending_ids"], [f"e{cap}", f"e{cap + 1}"])

        with mock.patch.object(
            pan115,
            "get_115_file_info",
            return_value={"parent_id": "target-cid", "name": ""},
        ), mock.patch.object(
            pan115,
            "wait_115_move_progress",
            return_value={"status": "completed", "progress": 100},
        ), mock.patch.object(pan115, "throttle_115_api_requests"), \
                mock.patch.object(pan115.time, "sleep"):
            landing = pan115.wait_115_writes_landed("cookie-value", expects, move_proid="42")

        self.assertEqual(landing["status"], "landed")
        self.assertEqual(landing["pending_ids"], [])


class Pan115DeleteVerificationTest(unittest.TestCase):
    """删除接口返回不明确时用父目录列表复核，避免把“其实已经清掉”误报成删除失败。"""

    def test_unrecognized_response_with_entry_gone_is_success(self):
        with mock.patch.object(pan115, "_request_115_delete_payload", return_value={"errno": 990001}), \
                mock.patch.object(pan115, "invalidate_115_entries_cache"), \
                mock.patch.object(pan115, "list_115_entries", return_value=[{"id": "keep-1", "name": "其他"}]), \
                mock.patch.object(pan115, "mark_cookie_health_success"), \
                mock.patch.object(pan115, "mark_cookie_health_failure"):
            result = pan115.delete_115_entries("cookie-value", ["gone-1"], parent_cid="parent-cid")

        self.assertEqual(result["ids"], ["gone-1"])
        self.assertTrue(result["response"].get("verified_removed"))

    def test_unrecognized_response_with_entry_present_still_raises(self):
        with mock.patch.object(pan115, "_request_115_delete_payload", return_value={"errno": 990001}), \
                mock.patch.object(pan115, "invalidate_115_entries_cache"), \
                mock.patch.object(pan115, "list_115_entries", return_value=[{"id": "gone-1", "name": "还在"}]), \
                mock.patch.object(pan115, "mark_cookie_health_success"), \
                mock.patch.object(pan115, "mark_cookie_health_failure") as health_failure:
            with self.assertRaises(RuntimeError):
                pan115.delete_115_entries("cookie-value", ["gone-1"], parent_cid="parent-cid")

        health_failure.assert_called_once()

    def test_verify_without_parent_never_deletes_blindly(self):
        self.assertFalse(pan115._verify_115_entries_removed("cookie-value", ["gone-1"], ""))


if __name__ == "__main__":
    unittest.main()
