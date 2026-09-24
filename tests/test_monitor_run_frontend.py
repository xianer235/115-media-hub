import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN_VIEW_PATH = ROOT / "static/js/modules/monitor/run-view.js"
INDEX_CSS_PATH = ROOT / "static/css/index.css"
INDEX_JS_PATH = ROOT / "static/js/index.js"
MONITOR_PAGE_PATH = ROOT / "templates/partials/pages/monitor_about.html"


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


def run_index_async(expression: str):
    script = f"""
const fs = require('fs');
const vm = require('vm');
const runViewSource = fs.readFileSync({json.dumps(str(RUN_VIEW_PATH))}, 'utf8');
const source = fs.readFileSync({json.dumps(str(INDEX_JS_PATH))}, 'utf8');
const context = {{
    console,
    window: {{}},
    document: {{
        hidden: false,
        getElementById: () => null,
    }},
}};
vm.createContext(context);
vm.runInContext(runViewSource, context, {{ filename: 'run-view.js' }});
vm.runInContext(source, context, {{ filename: 'index.js' }});
(async () => {{
    const result = await vm.runInContext({json.dumps(expression)}, context);
    process.stdout.write(JSON.stringify(result));
}})().catch(error => {{
    console.error(error);
    process.exitCode = 1;
}});
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

    def test_skipped_inbox_item_is_rendered_as_finished_not_pending(self):
        html = run_view(
            "window.MonitorRunView.eventCard({category: 'problem', operation: 'leave_in_inbox', "
            "status: 'skipped', title: '无法识别', detail: {reason: '未匹配到 TMDB 条目'}, "
            "created_at: '2026-09-23 10:00:00'}, 0)"
        )

        self.assertIn("未处理", html)
        self.assertNotIn("等待处理", html)

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

    def test_inbox_left_metric_is_labeled_as_finished_unhandled_work(self):
        html = run_view(
            "window.MonitorRunView.listRow({id: 'run-left', task_name: '接收', subject: '混合结果', "
            "source: 'manual', status: 'partial', queued_at: '2026-09-23 10:00:00', "
            "result: {moved: 1, left: 1}})"
        )

        self.assertIn("未处理", html)
        self.assertNotIn("待处理", html)

    def test_run_list_distinguishes_workflow_from_trigger_and_shows_parent_context(self):
        html = run_view(
            "window.MonitorRunView.listRow({id: 'change-1', task_name: '电影', subject: '示例电影', "
            "run_kind: 'change', source: 'change', status: 'completed', "
            "parent_task_name: '接收', parent_subject: '示例电影'})"
        )

        self.assertIn("流程：增量变更同步", html)
        self.assertIn("启动：检测到网盘变更", html)
        self.assertIn("来自接收夹整理：接收 · 示例电影", html)

    def test_run_filter_controls_separate_task_workflow_and_trigger(self):
        page = MONITOR_PAGE_PATH.read_text(encoding="utf-8")
        source = INDEX_JS_PATH.read_text(encoding="utf-8")

        self.assertIn('id="monitor-run-kind-filter"', page)
        self.assertIn("全部配置任务", page)
        self.assertIn("全部启动方式", page)
        self.assertIn("检测到网盘变更", page)
        self.assertIn("run_kind: document.getElementById('monitor-run-kind-filter')?.value || ''", source)
        self.assertIn("接收夹整理", source)
        self.assertIn("目录监控", source)

    def test_cancelled_before_start_uses_cancelled_copy(self):
        html = run_view(
            "window.MonitorRunView.listRow({id: 'run-2', task_name: '电视剧', subject: '示例剧', "
            "source: 'manual', status: 'cancelled', queued_at: '2026-09-23 10:00:00'})"
        )

        self.assertIn("已取消", html)
        self.assertNotIn("已中断", html)

    def test_run_modal_uses_a_stable_dedicated_shell(self):
        css = INDEX_CSS_PATH.read_text(encoding="utf-8")

        self.assertIn("#monitor-run-modal .monitor-run-modal-shell", css)
        self.assertIn("height: min(82dvh, 50rem)", css)
        self.assertIn("#monitor-run-modal .monitor-run-modal-body { flex: 1 1 0;", css)

    def test_run_modal_keeps_tab_bar_out_of_flex_shrink(self):
        css = INDEX_CSS_PATH.read_text(encoding="utf-8")

        self.assertIn("#monitor-run-modal .monitor-run-tabs { flex: 0 0 auto;", css)
        self.assertIn("#monitor-run-modal .monitor-run-modal-body { flex: 1 1 0;", css)

    def test_retention_dialog_uses_readable_day_theme_text(self):
        css = INDEX_CSS_PATH.read_text(encoding="utf-8")

        self.assertIn(".monitor-run-retention-body {", css)
        self.assertIn("color: var(--run-text);", css)
        self.assertIn("html.theme-day .monitor-run-retention-body", css)
        self.assertIn("html.theme-day .monitor-run-retention-body .form-check-label", css)

    def test_cleanup_reports_empty_result_and_request_errors(self):
        source = INDEX_JS_PATH.read_text(encoding="utf-8")

        self.assertIn("没有早于 ${days} 天的已结束记录", source)
        self.assertIn("没有可清除的已结束记录", source)
        self.assertIn("清理过期记录失败，请稍后重试", source)
        self.assertIn("清除全部已结束记录失败，请稍后重试", source)
        self.assertIn("catch", source)

    def test_retention_dialog_separates_expired_and_all_finished_cleanup(self):
        page = MONITOR_PAGE_PATH.read_text(encoding="utf-8")
        source = INDEX_JS_PATH.read_text(encoding="utf-8")
        css = INDEX_CSS_PATH.read_text(encoding="utf-8")

        self.assertIn('class="monitor-run-retention-section"', page)
        self.assertIn('id="monitor-run-cleanup-expired"', page)
        self.assertIn('id="monitor-run-cleanup-all"', page)
        self.assertIn("清除全部已结束记录", page)
        self.assertIn("requestMonitorRunCleanup('expired'", source)
        self.assertIn("requestMonitorRunCleanup('all_finished'", source)
        self.assertIn("{ scope, days: scope === 'expired' ? days : 0, preview }", source)
        self.assertIn("monitor-run-cleanup-danger", css)

    def test_all_finished_cleanup_executes_after_app_confirmation(self):
        calls = run_index_async(
            """(async () => {
                const calls = [];
                showAppConfirm = async message => {
                    calls.push(['confirm', message]);
                    return true;
                };
                requestMonitorRunCleanup = async (scope, options = {}) => {
                    calls.push(['cleanup', scope, Boolean(options.preview)]);
                    return options.preview ? { count: 9 } : { deleted: 9 };
                };
                setMonitorRunRetentionResult = message => calls.push(['result', message]);
                refreshMonitorRuns = async force => calls.push(['refresh', force]);
                await runMonitorRunCleanupAll();
                return calls;
            })()"""
        )

        self.assertEqual(calls[0], ["cleanup", "all_finished", True])
        self.assertEqual(calls[1][0], "confirm")
        self.assertIn("9 条已结束记录", calls[1][1])
        self.assertEqual(calls[2], ["cleanup", "all_finished", False])
        self.assertEqual(calls[3], ["result", "已清除 9 条已结束记录。"])
        self.assertEqual(calls[4], ["refresh", True])

    def test_expired_cleanup_executes_after_app_confirmation(self):
        calls = run_index_async(
            """(async () => {
                const calls = [];
                monitorRunRetentionSettings = () => ({ mode: 'days', days: 30 });
                showAppConfirm = async message => {
                    calls.push(['confirm', message]);
                    return true;
                };
                requestMonitorRunCleanup = async (scope, options = {}) => {
                    calls.push(['cleanup', scope, Boolean(options.preview)]);
                    return options.preview ? { count: 4 } : { deleted: 4 };
                };
                setMonitorRunRetentionResult = message => calls.push(['result', message]);
                refreshMonitorRuns = async force => calls.push(['refresh', force]);
                await runMonitorRunCleanup();
                return calls;
            })()"""
        )

        self.assertEqual(calls[0], ["cleanup", "expired", True])
        self.assertEqual(calls[1][0], "confirm")
        self.assertIn("4 条早于 30 天", calls[1][1])
        self.assertEqual(calls[2], ["cleanup", "expired", False])
        self.assertEqual(calls[3], ["result", "已清理 4 条过期记录。"])
        self.assertEqual(calls[4], ["refresh", True])


if __name__ == "__main__":
    unittest.main()
