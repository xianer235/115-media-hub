import unittest
from unittest import mock

from app.providers import pan115_qr


class Pan115QrHelperTest(unittest.TestCase):
    def test_apps_include_default_and_recommended(self):
        apps = pan115_qr.get_115_qr_apps()
        by_value = {item["value"]: item for item in apps}
        self.assertEqual(pan115_qr.get_115_qr_default_app(), "wechatmini")
        self.assertIn("wechatmini", by_value)
        self.assertTrue(by_value["wechatmini"]["default"])
        self.assertTrue(by_value["wechatmini"]["rec"])
        self.assertTrue(by_value["alipaymini"]["rec"])
        # 已下架的客户端不应出现在可选列表
        for deprecated in ("linux", "mac", "windows"):
            self.assertNotIn(deprecated, by_value)

    def test_normalize_app_falls_back_to_default(self):
        self.assertEqual(pan115_qr.normalize_115_qr_app("tv"), "tv")
        self.assertEqual(pan115_qr.normalize_115_qr_app("  ALIPAYMINI "), "alipaymini")
        self.assertEqual(pan115_qr.normalize_115_qr_app(""), "wechatmini")
        self.assertEqual(pan115_qr.normalize_115_qr_app("linux"), "wechatmini")

    def test_build_cookie_header_joins_nonempty_pairs(self):
        cookie = pan115_qr._build_cookie_header({"UID": "u1", "CID": "c1", "SEID": "s1", "KID": ""})
        self.assertEqual(cookie, "UID=u1; CID=c1; SEID=s1")

    def test_build_cookie_header_handles_non_dict(self):
        self.assertEqual(pan115_qr._build_cookie_header(None), "")
        self.assertEqual(pan115_qr._build_cookie_header("plain"), "")

    def test_build_image_url_quotes_uid(self):
        self.assertIn("uid=abc", pan115_qr.build_115_qrcode_image_url("abc"))
        self.assertIn("uid=a%26b", pan115_qr.build_115_qrcode_image_url("a&b"))

    def test_get_qrcode_token_raises_when_uid_missing(self):
        with mock.patch.object(pan115_qr, "http_request_json", return_value={"data": {"time": 1, "sign": "s"}}):
            with self.assertRaises(RuntimeError):
                pan115_qr.get_115_qrcode_token()

    def test_get_qrcode_status_returns_int(self):
        with mock.patch.object(pan115_qr, "http_request_json", return_value={"data": {"status": 1}}):
            self.assertEqual(pan115_qr.get_115_qrcode_status("u", "t", "s"), 1)

    def test_get_qrcode_status_raises_on_bad_shape(self):
        with mock.patch.object(pan115_qr, "http_request_json", return_value={"data": {}}):
            with self.assertRaises(RuntimeError):
                pan115_qr.get_115_qrcode_status("u", "t", "s")

    def test_post_qrcode_result_builds_cookie_uses_normalized_app(self):
        def fake_form_json(url, form_data, **kwargs):
            self.assertIn("alipaymini", url)
            self.assertEqual(form_data["app"], "alipaymini")
            self.assertEqual(form_data["account"], "u1")
            return {"data": {"cookie": {"UID": "u1", "CID": "c1", "SEID": "s1"}}}

        with mock.patch.object(pan115_qr, "http_request_form_json", side_effect=fake_form_json):
            cookie = pan115_qr.post_115_qrcode_result("u1", "ALIPAYMINI")
        self.assertEqual(cookie, "UID=u1; CID=c1; SEID=s1")

    def test_post_qrcode_result_raises_when_no_cookie(self):
        with mock.patch.object(pan115_qr, "http_request_form_json", return_value={"data": {"cookie": {}}}):
            with self.assertRaises(RuntimeError):
                pan115_qr.post_115_qrcode_result("u1", "wechatmini")


if __name__ == "__main__":
    unittest.main()
