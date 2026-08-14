import builtins
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cli  # noqa: E402


class _FakeResponse:
    def __init__(self, status_code, text="", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json = json_data or {}

    def json(self):
        return self._json


class _FakeSession:
    def __init__(self, status_code):
        self.status_code = status_code
        self.calls = []
        self.cookies = type("_Cookies", (), {"jar": []})()

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return _FakeResponse(self.status_code)

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return _FakeResponse(200, json_data={"ok": True})


class CliAuthTest(unittest.TestCase):
    def test_env_credentials_used_when_provided(self):
        with patch.object(cli, "MH_USERNAME", "admin"), patch.object(cli, "MH_PASSWORD", "secret"):
            self.assertEqual(cli.Client()._resolve_credentials(), ("admin", "secret"))

    def test_missing_credentials_non_tty_fails_clearly(self):
        with patch.object(cli, "MH_USERNAME", ""), patch.object(cli, "MH_PASSWORD", ""), patch.object(
            sys.stdin, "isatty", return_value=False
        ):
            with self.assertRaises(SystemExit) as ctx:
                cli.Client()._resolve_credentials()
            self.assertIn("MH_USERNAME/MH_PASSWORD", str(ctx.exception))

    def test_missing_credentials_tty_prompts(self):
        with patch.object(cli, "MH_USERNAME", ""), patch.object(cli, "MH_PASSWORD", ""), patch.object(
            sys.stdin, "isatty", return_value=True
        ), patch.object(builtins, "input", return_value="admin"), patch("getpass.getpass", return_value="secret"):
            self.assertEqual(cli.Client()._resolve_credentials(), ("admin", "secret"))

    def test_login_only_when_unauthorized(self):
        client = cli.Client("http://test.local")
        client._session = _FakeSession(status_code=401)
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(cli, "COOKIE_FILE", os.path.join(tmpdir, ".cookies.json")), patch.object(
                cli, "MH_USERNAME", "admin"
            ), patch.object(cli, "MH_PASSWORD", "secret"):
                client._login_if_needed()
            self.assertTrue(os.path.exists(os.path.join(tmpdir, ".cookies.json")))
        methods = [call[0] for call in client._session.calls]
        self.assertEqual(methods, ["GET", "POST"])
        post_call = client._session.calls[1]
        self.assertEqual(post_call[1], "/login")
        self.assertEqual(post_call[2]["json"], {"username": "admin", "password": "secret"})

    def test_no_login_when_authorized(self):
        client = cli.Client("http://test.local")
        client._session = _FakeSession(status_code=200)
        client._login_if_needed()
        self.assertEqual([call[0] for call in client._session.calls], ["GET"])


if __name__ == "__main__":
    unittest.main()
