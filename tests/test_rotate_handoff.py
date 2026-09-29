"""scripts/rotate_handoff.py 的回归测试。

这个脚本会重写交接文档，一旦出错就是丢历史记录，所以重点验证三件事：
不丢条目、重复执行幂等、体积预算确实生效。
"""

import datetime as dt
import importlib.util
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "rotate_handoff.py"

_spec = importlib.util.spec_from_file_location("rotate_handoff", SCRIPT_PATH)
rotate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rotate)

ENTRY_RE = rotate.ENTRY_RE
AS_OF = dt.date(2026, 9, 30)


def legacy_handoff_text(entries):
    """模拟旧版 handoff.md：没有 `## 交接记录` 分界，且头部状态会过期。"""
    body = "\n".join(entries)
    return (
        "# Agent Handoff\n"
        "\n"
        "## 当前状态\n"
        "\n"
        "- **日期**: 2026-08-19\n"
        "- **分支**: `main`\n"
        "\n"
        "## 最近重要交接\n"
        "\n"
        f"{body}\n"
    )


def archive_text(entries):
    body = "\n".join(entries)
    return "# Agent Handoff Archive\n\n## 交接记录\n\n" + body + "\n"


def entries_in(text):
    return [line for line in text.splitlines() if ENTRY_RE.match(line)]


class RotationTest(unittest.TestCase):
    def test_legacy_file_is_migrated_without_losing_entries(self):
        entries = [
            "- 2026-08-01 | `main` | 旧条目 A",
            "- 2026-09-29 | `main` | 新条目 B",
        ]
        handoff_out, archive_out, stats = rotate.build_rotation(
            legacy_handoff_text(entries),
            archive_text([]),
            as_of=AS_OF,
        )

        self.assertIn("## 交接记录", handoff_out)
        self.assertNotIn("2026-08-19", handoff_out)  # 过期的“当前状态”被模板替换
        self.assertEqual(stats["total"], 2)
        self.assertEqual(entries_in(handoff_out), [entries[1]])
        self.assertEqual(entries_in(archive_out), [entries[0]])

    def test_no_entry_is_lost_between_both_files(self):
        entries = [
            f"- 2026-08-{day:02d} | `main` | 历史条目 {day}" for day in range(1, 29)
        ] + ["- 2026-09-29 | `main` | 新条目"]
        handoff_out, archive_out, _ = rotate.build_rotation(
            legacy_handoff_text(entries),
            archive_text([]),
            as_of=AS_OF,
        )

        self.assertEqual(
            sorted(entries_in(handoff_out) + entries_in(archive_out)),
            sorted(entries),
        )

    def test_rotation_is_idempotent(self):
        entries = [
            f"- 2026-09-{day:02d} | `main` | 条目 {day} | " + "x" * 300
            for day in range(10, 30)
        ]
        handoff_text = legacy_handoff_text(entries)
        archive_in = archive_text([])

        first = rotate.build_rotation(handoff_text, archive_in, as_of=AS_OF)
        second = rotate.build_rotation(first[0], first[1], as_of=AS_OF)
        third = rotate.build_rotation(second[0], second[1], as_of=AS_OF)

        self.assertEqual(first[0], second[0])
        self.assertEqual(first[1], second[1])
        self.assertEqual(second[0], third[0])
        self.assertEqual(second[1], third[1])

    def test_budget_moves_overflow_entries_to_archive(self):
        entries = [
            f"- 2026-09-{day:02d} | `main` | 条目 {day} | " + "y" * 500
            for day in range(1, 30)
        ]
        handoff_out, archive_out, stats = rotate.build_rotation(
            legacy_handoff_text(entries),
            archive_text([]),
            as_of=AS_OF,
            keep_days=60,  # 只靠体积预算触发轮转
            max_bytes=8192,
            min_entries=5,
        )

        self.assertLessEqual(len(handoff_out.encode("utf-8")), 8192)
        self.assertGreaterEqual(stats["kept"], 5)
        self.assertLess(stats["kept"], len(entries))
        self.assertEqual(stats["kept"] + stats["archived"], 29)
        # 保留的一定是最新的那批：最旧的一天应当已经归档
        self.assertNotIn("条目 1 |", handoff_out)
        self.assertIn("条目 1 |", archive_out)
        self.assertEqual(entries_in(handoff_out)[0][:12], "- 2026-09-29")

    def test_min_entries_floor_wins_over_budget(self):
        entries = [
            f"- 2026-09-{day:02d} | `main` | 条目 {day} | " + "z" * 5000
            for day in range(20, 30)
        ]
        _, _, stats = rotate.build_rotation(
            legacy_handoff_text(entries),
            archive_text([]),
            as_of=AS_OF,
            max_bytes=1024,
            min_entries=10,
        )
        self.assertEqual(stats["kept"], 10)

    def test_duplicate_entries_are_merged(self):
        entry = "- 2026-08-01 | `main` | 同时出现在两份文件里"
        _, archive_out, stats = rotate.build_rotation(
            legacy_handoff_text([entry, "- 2026-09-29 | `main` | 新条目"]),
            archive_text([entry]),
            as_of=AS_OF,
        )
        self.assertEqual(stats["duplicates"], 1)
        self.assertEqual(len(entries_in(archive_out)), 1)


class MainCommandTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.handoff_path = root / "handoff.md"
        self.archive_path = root / "handoff-archive.md"

        self._original_handoff_path = rotate.HANDOFF_PATH
        self._original_archive_path = rotate.ARCHIVE_PATH
        rotate.HANDOFF_PATH = self.handoff_path
        rotate.ARCHIVE_PATH = self.archive_path
        self.addCleanup(self._restore_paths)

        self.handoff_path.write_text(
            legacy_handoff_text(
                [
                    "- 2026-08-01 | `main` | 旧条目",
                    "- 2026-09-29 | `main` | 新条目",
                ]
            ),
            encoding="utf-8",
        )
        self.archive_path.write_text(archive_text([]), encoding="utf-8")

    def _restore_paths(self):
        rotate.HANDOFF_PATH = self._original_handoff_path
        rotate.ARCHIVE_PATH = self._original_archive_path

    def run_main(self, *args):
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = rotate.main(list(args))
        return code, buffer.getvalue()

    def test_dry_run_does_not_touch_files(self):
        before = self.handoff_path.read_text(encoding="utf-8")
        code, output = self.run_main("--dry-run", "--as-of", AS_OF.isoformat())

        self.assertEqual(code, 0)
        self.assertIn("dry-run", output)
        self.assertEqual(self.handoff_path.read_text(encoding="utf-8"), before)

    def test_check_reports_pending_rotation(self):
        code, output = self.run_main("--check", "--as-of", AS_OF.isoformat())
        self.assertEqual(code, 1)
        self.assertIn("需要轮转", output)

    def test_real_run_then_check_is_clean(self):
        code, _ = self.run_main("--as-of", AS_OF.isoformat())
        self.assertEqual(code, 0)

        again, output = self.run_main("--check", "--as-of", AS_OF.isoformat())
        self.assertEqual(again, 0)
        self.assertIn("无需轮转", output)

        handoff_text = self.handoff_path.read_text(encoding="utf-8")
        archive_out = self.archive_path.read_text(encoding="utf-8")
        self.assertEqual(
            sorted(entries_in(handoff_text) + entries_in(archive_out)),
            ["- 2026-08-01 | `main` | 旧条目", "- 2026-09-29 | `main` | 新条目"],
        )


if __name__ == "__main__":
    unittest.main()
