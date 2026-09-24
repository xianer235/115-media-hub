import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import core, runtime_files


def write_lines(path: Path, lines) -> None:
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def segment_texts(page) -> str:
    return "\n".join(
        str(entry.get("text", ""))
        for segment in page.get("segments", [])
        for entry in segment.get("entries", [])
    )


class ClearLogFileTest(unittest.TestCase):
    """清空日志必须同时清掉轮转备份，否则界面里旧内容会“清不掉”。"""

    def test_clear_removes_rotated_backups(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp) / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / "monitor.log"
            for name in ("monitor.log", "monitor.log.1", "monitor.log.2"):
                write_lines(log_dir / name, ["旧日志内容"])

            with mock.patch.object(runtime_files, "LOG_DIR", str(log_dir)):
                runtime_files.clear_log_file(str(log_path), "09-24 10:00:00 监控日志已清空")

            self.assertEqual(log_path.read_text(encoding="utf-8"), "09-24 10:00:00 监控日志已清空\n")
            self.assertFalse((log_dir / "monitor.log.1").exists())
            self.assertFalse((log_dir / "monitor.log.2").exists())

    def test_clear_is_idempotent_without_backups(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp) / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / "monitor.log"

            with mock.patch.object(runtime_files, "LOG_DIR", str(log_dir)):
                runtime_files.clear_log_file(str(log_path), "第一次清空")
                runtime_files.clear_log_file(str(log_path), "第二次清空")

            self.assertEqual(log_path.read_text(encoding="utf-8"), "第二次清空\n")

    def test_cleared_monitor_log_page_no_longer_shows_old_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp) / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            monitor_log = log_dir / "monitor.log"
            write_lines(monitor_log, ["09-23 10:00:00 旧任务的分段内容"])
            write_lines(log_dir / "monitor.log.1", ["09-22 10:00:00 更旧任务的分段内容"])
            write_lines(log_dir / "monitor.log.2", ["09-21 10:00:00 最旧任务的分段内容"])

            with mock.patch.object(core, "MONITOR_LOG_PATH", str(monitor_log)), mock.patch.object(
                runtime_files, "LOG_DIR", str(log_dir)
            ):
                before = core.build_monitor_log_segment_page(source="file", limit=10)
                runtime_files.clear_log_file(str(monitor_log), "09-24 10:00:00 监控日志已清空")
                after = core.build_monitor_log_segment_page(source="file", limit=10)

            before_text = segment_texts(before)
            self.assertIn("旧任务的分段内容", before_text)
            self.assertIn("更旧任务的分段内容", before_text)
            self.assertIn("最旧任务的分段内容", before_text)

            after_text = segment_texts(after)
            self.assertIn("监控日志已清空", after_text)
            self.assertNotIn("旧任务的分段内容", after_text)
            self.assertNotIn("更旧任务的分段内容", after_text)
            self.assertNotIn("最旧任务的分段内容", after_text)


if __name__ == "__main__":
    unittest.main()
