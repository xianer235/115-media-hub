import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cli  # noqa: E402


class CliGrammarTest(unittest.TestCase):
    def _parse(self, argv):
        return cli._build_parser().parse_args(argv)

    def test_search_cancel_is_explicit_flag(self):
        args = self._parse(["search", "--cancel"])
        self.assertTrue(args.cancel)
        self.assertEqual(args.keyword, [])

    def test_search_keyword_not_treated_as_cancel(self):
        args = self._parse(["search", "cancel"])
        self.assertFalse(args.cancel)
        self.assertEqual(args.keyword, ["cancel"])
        args = self._parse(["search", "黑客帝国", "4K"])
        self.assertEqual(args.keyword, ["黑客帝国", "4K"])

    def test_subscribe_add_defaults(self):
        args = self._parse(["subscribe", "add", "黑客帝国4"])
        self.assertEqual(args.action, "add")
        self.assertEqual(args.name, ["黑客帝国4"])
        self.assertEqual(args.type, "movie")
        self.assertEqual(args.quality, "balanced")
        self.assertEqual(args.cron_minutes, 120)
        self.assertEqual(args.savepath, "")

    def test_scrape_jobs_create_accepts_tmdb_args(self):
        args = self._parse(
            ["scrape", "jobs-create", "/电影/x.mkv", "--tmdb-id", "123", "--media-type", "tv"]
        )
        self.assertEqual(args.action, "jobs-create")
        self.assertEqual(args.path, ["/电影/x.mkv"])
        self.assertEqual(args.tmdb_id, "123")
        self.assertEqual(args.media_type, "tv")

    def test_sources_search_grammar(self):
        args = self._parse(["sources", "search", "黑客帝国"])
        self.assertEqual(args.action, "search")
        self.assertEqual(args.keyword, ["黑客帝国"])

    def test_logs_tail_uses_flag(self):
        args = self._parse(["logs", "--tail", "50"])
        self.assertEqual(args.action, "")
        self.assertEqual(args.tail, 50)
        args = self._parse(["logs", "clear"])
        self.assertEqual(args.action, "clear")

    def test_resource_delete_uses_id_flag(self):
        args = self._parse(["resource", "delete", "--id", "123", "--yes"])
        self.assertEqual(args.action, "delete")
        self.assertEqual(args.resource_id, "123")
        self.assertTrue(args.yes)

    def test_unknown_command_rejected(self):
        with self.assertRaises(SystemExit):
            self._parse(["not-a-command"])


class CliHelperTest(unittest.TestCase):
    def test_parse_json_array_valid_and_invalid(self):
        self.assertEqual(cli._parse_json_array("[1,3,5]", "--schedule-weekdays"), [1, 3, 5])
        self.assertEqual(cli._parse_json_array("", "--schedule-weekdays"), [])
        with self.assertRaises(SystemExit) as ctx:
            cli._parse_json_array("not-json", "--schedule-weekdays")
        self.assertIn("JSON 数组", str(ctx.exception))

    def test_container_name_auto_detect(self):
        proc = type("_Proc", (), {"stdout": "115-media-hub-test\n"})()
        with patch.object(cli.subprocess, "run", return_value=proc):
            self.assertEqual(cli._resolve_container_name(), "115-media-hub-test")

    def test_container_name_falls_back_when_docker_missing(self):
        with patch.object(cli.subprocess, "run", side_effect=FileNotFoundError):
            self.assertEqual(cli._resolve_container_name(), "115-media-hub")

    def test_container_name_env_override_wins(self):
        with patch.dict("os.environ", {"MH_CONTAINER": "my-hub"}):
            self.assertEqual(cli._resolve_container_name(), "my-hub")


if __name__ == "__main__":
    unittest.main()
