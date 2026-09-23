import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN_VIEW_PATH = ROOT / "static/js/modules/monitor/run-view.js"


def run_view(expression: str):
    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(RUN_VIEW_PATH))}, 'utf8');
const context = {{ window: {{}}, console }};
vm.createContext(context);
vm.runInContext(source, context, {{ filename: 'run-view.js' }});
process.stdout.write(JSON.stringify(vm.runInContext({json.dumps(expression)}, context)));
"""
    completed = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True)
    if completed.returncode != 0:
        raise AssertionError(completed.stderr.strip())
    return json.loads(completed.stdout)


class MonitorRunViewTest(unittest.TestCase):
    def test_detail_uses_chinese_allowlist_and_preserves_paths(self):
        html = run_view(
            "window.MonitorRunView.detailRows({"
            "old_path: '/115/Shows/Example S01', "
            "reason: '请求超时', "
            "subjects: ['Example S01'], "
            "internal_trace: 'must not leak'"
            "})"
        )

        self.assertIn("原路径", html)
        self.assertIn("/115/Shows/Example S01", html)
        self.assertIn("原因", html)
        self.assertIn("Example S01", html)
        self.assertNotIn("internal_trace", html)
        self.assertNotIn("must not leak", html)

    def test_historical_started_step_is_not_rendered_as_current_running(self):
        html = run_view(
            "window.MonitorRunView.eventCard({category: 'process', operation: 'started', "
            "status: 'running', title: '开始执行', created_at: '2026-09-23 10:00:00'}, 0)"
        )

        self.assertIn("已开始", html)
        self.assertNotIn("执行中", html)

    def test_list_keeps_problem_summary_when_metrics_exist(self):
        html = run_view(
            "window.MonitorRunView.listRow({id: 'run-1', task_name: '电视剧', subject: '示例剧', "
            "source: 'webhook', status: 'partial', queued_at: '2026-09-23 10:00:00', "
            "summary: '1 个目录读取失败；已保护现有文件。', "
            "result: {generated: 12, failed_dirs: 1}})"
        )

        self.assertIn("外部通知", html)
        self.assertIn("1 个目录读取失败", html)
        self.assertIn("新增或更新", html)
        self.assertIn("失败目录", html)
        self.assertNotIn("partial", html)

    def test_cancelled_before_start_uses_cancelled_copy(self):
        html = run_view(
            "window.MonitorRunView.listRow({id: 'run-2', task_name: '电视剧', subject: '示例剧', "
            "source: 'manual', status: 'cancelled', queued_at: '2026-09-23 10:00:00'})"
        )

        self.assertIn("已取消", html)
        self.assertNotIn("已中断", html)


if __name__ == "__main__":
    unittest.main()
