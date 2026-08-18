import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MONITOR_TEMPLATE_PATH = ROOT / "templates/partials/pages/monitor_about.html"
SUBSCRIPTION_TEMPLATE_PATH = ROOT / "templates/partials/pages/subscription.html"
TASK_TEMPLATE_PATH = ROOT / "templates/partials/pages/task.html"
CSS_PATH = ROOT / "static/css/index.css"


class LogHeaderButtonsFrontendTest(unittest.TestCase):
    def test_log_header_buttons_use_dedicated_class(self):
        for template_path in (
            MONITOR_TEMPLATE_PATH,
            SUBSCRIPTION_TEMPLATE_PATH,
            TASK_TEMPLATE_PATH,
        ):
            html = template_path.read_text(encoding="utf-8")
            log_buttons = [
                line.strip()
                for line in html.splitlines()
                if "清空日志" in line or "加载更早" in line
            ]
            self.assertTrue(log_buttons)
            for line in log_buttons:
                # 不再依赖会被日间全局规则拍扁的 bg-slate-800/text-slate-300 工具类。
                self.assertIn("log-header-btn", line)
                self.assertNotIn("bg-slate-800", line)

    def test_log_header_buttons_have_night_and_day_styles(self):
        css = CSS_PATH.read_text(encoding="utf-8")
        self.assertIn(".log-header-btn {", css)
        self.assertIn("background: #1e293b;", css)
        self.assertIn("color: #cbd5e1;", css)
        self.assertIn(".log-header-btn:hover {\n            background: #334155;\n        }", css)
        self.assertIn("html.theme-day .log-header-btn {", css)
        self.assertIn("background: #e2e8f0 !important;", css)
        self.assertIn("border-color: #cbd5e1 !important;", css)
        self.assertIn("color: #334155 !important;", css)
        self.assertIn("html.theme-day .log-header-btn:hover {", css)
        self.assertIn("background: #cbd5e1 !important;", css)
        self.assertIn("color: #1e293b !important;", css)


if __name__ == "__main__":
    unittest.main()
