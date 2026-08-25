import unittest
from pathlib import Path

from app import core
from app.services import monitor


ROOT = Path(__file__).resolve().parents[1]
INDEX_JS_PATH = ROOT / "static/js/index.js"


class MonitorScopeLineTest(unittest.TestCase):
    @staticmethod
    def task():
        return core.normalize_task(
            {"name": "监控", "scan_path": "/115/剧集", "target_path": "剧集"}
        )

    def test_resource_trigger_with_hinted_path(self):
        line = monitor.build_monitor_scope_line(
            self.task(), "resource", hinted_path="/115/剧集/新剧"
        )
        self.assertEqual(line, "范围: /115/剧集/新剧")

    def test_webhook_fallback_full_task(self):
        line = monitor.build_monitor_scope_line(self.task(), "webhook")
        self.assertEqual(line, "范围: 全任务 /115/剧集")

    def test_manual_trigger_with_resolved_paths(self):
        line = monitor.build_monitor_scope_line(
            self.task(),
            "manual",
            resolved_paths=["/115/剧集/A", "/115/剧集/B"],
        )
        self.assertEqual(line, "范围: /115/剧集/A, /115/剧集/B")

    def test_manual_trigger_fallback_full_task(self):
        line = monitor.build_monitor_scope_line(self.task(), "manual", resolved_paths=[])
        self.assertEqual(line, "范围: 全任务 /115/剧集")

    def test_manual_required_scope_wins(self):
        line = monitor.build_monitor_scope_line(self.task(), "manual", manual_scope_count=2)
        self.assertEqual(line, "范围: 需补扫首层分支 2 条")

    def test_manual_force_all(self):
        line = monitor.build_monitor_scope_line(self.task(), "manual", manual_force_all=True)
        self.assertEqual(line, "范围: 需补扫全任务（首层强制扫描）")


class MonitorConclusionLineTest(unittest.TestCase):
    def test_conclusion_extracts_auto_scrape_count(self):
        stats = {"generated": 13, "skipped": 39, "deleted_files": 2}
        line = monitor.build_monitor_conclusion_line(stats, "已自动整理 7 项（任务 #80）")
        self.assertEqual(line, "结论: 新增/更新 13 | 跳过 39 | 自动整理 7 项 | 清理 2")

    def test_conclusion_without_auto_scrape(self):
        line = monitor.build_monitor_conclusion_line(
            {"generated": 1, "skipped": 0, "deleted_files": 0}
        )
        self.assertEqual(line, "结论: 新增/更新 1 | 跳过 0 | 自动整理 - | 清理 0")

    def test_conclusion_with_non_count_auto_message(self):
        line = monitor.build_monitor_conclusion_line(
            {"generated": 0, "skipped": 0, "deleted_files": 0},
            "新增条目无高置信度自动匹配",
        )
        self.assertEqual(line, "结论: 新增/更新 0 | 跳过 0 | 自动整理 已执行 | 清理 0")


class MonitorLogFrontendSourceTest(unittest.TestCase):
    def test_index_js_keeps_summary_decoration_without_icon_prefixes(self):
        source = INDEX_JS_PATH.read_text(encoding="utf-8")
        self.assertNotIn("function decorateMonitorLogText(text)", source)
        self.assertIn("首层汇总:", source)
        self.assertIn("变更同步汇总:", source)
        self.assertIn("decorateMonitorSummaryText(text)", source)
        self.assertIn(".split(/[|，]/)", source)
        for marker in (
            "'事件': 'summary-info'",
            "'完成': 'summary-positive'",
            "'失败': 'summary-fail'",
            "'生成 STRM': 'summary-positive'",
            "'删除 STRM': 'summary-delete'",
            "'局部读取目录': 'summary-info'",
            "'需补扫': 'summary-fail'",
            "'丢弃': 'summary-skip'",
        ):
            self.assertIn(marker, source)
