import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN_VIEW_PATH = ROOT / "static/js/modules/monitor/run-view.js"
INDEX_CSS_PATH = ROOT / "static/css/index.css"
INDEX_JS_PATH = ROOT / "static/js/index.js"
MONITOR_PAGE_PATH = ROOT / "templates/partials/pages/monitor_about.html"
MONITOR_TAB_MODULE_PATH = ROOT / "static/js/modules/tabs/monitor.js"


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

    def test_dialog_header_pins_actions_to_the_right(self):
        page = MONITOR_PAGE_PATH.read_text(encoding="utf-8")
        css = INDEX_CSS_PATH.read_text(encoding="utf-8")
        header_start = page.index('id="monitor-run-modal"')
        header = page[header_start:page.index('class="monitor-run-tabs"', header_start)]

        # 页头只允许“标题 + 右侧动作组”两种子元素：三个平级子元素时 space-between
        # 会把中间的按钮挤到弹窗中间，并且随窗口宽度漂移。
        actions_at = header.index('class="app-dialog-header-actions"')
        title_div_at = header.index("<div>")
        buttons = ("monitor-run-refresh", "monitor-run-close")
        self.assertLess(title_div_at, actions_at)
        for marker in buttons:
            self.assertGreater(header.index(marker), actions_at)
        self.assertLess(header.index(buttons[0]), header.index(buttons[1]))

        self.assertIn(".app-dialog-header > :first-child { flex: 1 1 auto; min-width: 0; }", css)
        self.assertIn("margin-left: auto;", css)

    def test_retention_dialog_uses_readable_day_theme_text(self):
        css = INDEX_CSS_PATH.read_text(encoding="utf-8")

        self.assertIn(".monitor-run-retention-body {", css)
        self.assertIn("color: var(--run-text);", css)
        self.assertIn("html.theme-day .monitor-run-retention-body", css)
        self.assertIn("html.theme-day .monitor-run-retention-body .form-check-label", css)

    def test_legacy_log_dialog_exposes_a_clear_button(self):
        page = MONITOR_PAGE_PATH.read_text(encoding="utf-8")
        source = INDEX_JS_PATH.read_text(encoding="utf-8")
        css = INDEX_CSS_PATH.read_text(encoding="utf-8")

        self.assertIn('id="monitor-legacy-log-clear"', page)
        self.assertIn('onclick="clearLegacyMonitorLogs()"', page)
        self.assertIn('id="monitor-legacy-log-status"', page)
        self.assertIn("async function clearLegacyMonitorLogs()", source)
        # 旧文本日志要能跑“加载 -> 清空 -> 重新加载”这一条链路。
        self.assertIn("async function loadLegacyMonitorLogs({ append = false } = {})", source)
        self.assertIn("await clearMonitorLogs();", source)
        self.assertIn("html.theme-day .monitor-legacy-log-status", css)

    def test_legacy_log_clear_runs_after_confirmation(self):
        calls = run_index_async(
            """(async () => {
                const calls = [];
                showAppConfirm = async message => {
                    calls.push(['confirm', message]);
                    return true;
                };
                clearMonitorLogs = async () => calls.push(['clear']);
                loadLegacyMonitorLogs = async () => calls.push(['reload']);
                setLegacyMonitorLogStatus = (message, tone) => calls.push(['status', message, tone || 'info']);
                showToast = () => calls.push(['toast']);
                await clearLegacyMonitorLogs();
                return calls;
            })()"""
        )

        self.assertEqual([entry[0] for entry in calls], ["confirm", "status", "clear", "reload", "status", "toast"])
        self.assertIn("历史文本日志", calls[0][1])
        self.assertEqual(calls[2], ["clear"])
        self.assertEqual(calls[3], ["reload"])
        self.assertEqual(calls[4], ["status", "已清空历史文本日志。运行记录未受影响。", "info"])

    def test_legacy_log_clear_keeps_logs_when_confirmation_is_rejected(self):
        calls = run_index_async(
            """(async () => {
                const calls = [];
                showAppConfirm = async message => {
                    calls.push(['confirm', message]);
                    return false;
                };
                clearMonitorLogs = async () => calls.push(['clear']);
                loadLegacyMonitorLogs = async () => calls.push(['reload']);
                await clearLegacyMonitorLogs();
                return calls;
            })()"""
        )

        self.assertEqual([entry[0] for entry in calls], ["confirm"])

    def test_legacy_log_clear_reports_request_failure(self):
        calls = run_index_async(
            """(async () => {
                const calls = [];
                showAppConfirm = async () => true;
                clearMonitorLogs = async () => { throw new Error('服务不可用'); };
                loadLegacyMonitorLogs = async () => calls.push(['reload']);
                setLegacyMonitorLogStatus = (message, tone) => calls.push(['status', message, tone || 'info']);
                await clearLegacyMonitorLogs();
                return calls;
            })()"""
        )

        self.assertEqual([entry[0] for entry in calls], ["status", "status"])
        self.assertEqual(calls[1][2], "error")
        self.assertIn("清空失败", calls[1][1])
        self.assertIn("服务不可用", calls[1][1])

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
        self.assertIn("days: scope === 'expired' ? days : 0,", source)
        self.assertIn("task_name: String(taskName || '').trim(),", source)
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

    def test_partial_run_without_problem_events_explains_itself(self):
        html = run_view(
            "window.MonitorRunView.detailHtml({"
            "run: {status: 'partial', run_kind: 'change', task_name: '电视剧', subject: '文件变更', "
            "summary: '已同步 1 条网盘变更，1 个目录需要手动监控', result: {completed: 1, manual_required: 1}}, "
            "events: [], counts: {process: 3, remote: 1, strm: 0, problem: 0}, total: 0, has_more: false"
            "}, 'problem')"
        )

        self.assertIn("monitor-run-derived-issues", html)
        self.assertIn("需要手动监控", html)
        self.assertNotIn("暂无问题记录", html)

    def test_completed_run_without_problem_events_keeps_empty_state(self):
        html = run_view(
            "window.MonitorRunView.detailHtml({"
            "run: {status: 'completed', run_kind: 'change', summary: '已同步 3 条网盘变更', result: {completed: 3}}, "
            "events: [], counts: {problem: 0}, total: 0, has_more: false"
            "}, 'problem')"
        )

        self.assertIn("暂无问题记录", html)
        self.assertNotIn("monitor-run-derived-issues", html)

    def test_problem_tab_count_matches_derived_items(self):
        detail = (
            "{run: {status: 'partial', result: {manual_required: 1, left: 2}}, "
            "counts: {process: 3, remote: 1, strm: 0, problem: 0}}"
        )

        self.assertEqual(run_view(f"window.MonitorRunView.tabCount({detail}, 'problem')"), 2)
        self.assertEqual(run_view(f"window.MonitorRunView.tabCount({detail}, 'remote')"), 1)
        self.assertEqual(
            run_view(
                "window.MonitorRunView.tabCount("
                "{run: {status: 'completed', result: {}}, counts: {problem: 0}}, 'problem')"
            ),
            0,
        )

    def test_filter_reset_button_clears_every_filter(self):
        page = MONITOR_PAGE_PATH.read_text(encoding="utf-8")
        self.assertIn('id="monitor-run-filter-reset"', page)
        self.assertIn("resetMonitorRunFilters()", page)

        calls = run_index_async(
            """(async () => {
                const calls = [];
                const values = {
                    'monitor-run-task-filter': '电视剧',
                    'monitor-run-kind-filter': 'change',
                    'monitor-run-source-filter': 'cron',
                    'monitor-run-status-filter': 'partial',
                };
                document.getElementById = id => (id in values ? { set value(next) { values[id] = next; }, get value() { return values[id]; } } : null);
                refreshMonitorRuns = async () => calls.push(['refresh']);
                await resetMonitorRunFilters();
                calls.push(['values', { ...values }]);
                return calls;
            })()"""
        )

        self.assertEqual(calls[0], ["refresh"])
        self.assertEqual(calls[1], ["values", {
            "monitor-run-task-filter": "",
            "monitor-run-kind-filter": "",
            "monitor-run-source-filter": "",
            "monitor-run-status-filter": "",
        }])

    def test_legacy_log_dialog_loads_older_entries(self):
        page = MONITOR_PAGE_PATH.read_text(encoding="utf-8")
        source = INDEX_JS_PATH.read_text(encoding="utf-8")
        self.assertIn('id="monitor-legacy-log-more"', page)
        self.assertIn("loadMoreLegacyMonitorLogs()", page)
        self.assertIn("async function loadLegacyMonitorLogs({ append = false } = {})", source)
        self.assertIn("offset=${offset}", source)

        calls = run_index_async(
            """(async () => {
                const calls = [];
                const body = { innerText: '旧的第二段' };
                document.getElementById = id => (id === 'monitor-legacy-log-body' ? body : null);
                window.MediaHubApi = {
                    getJson: async url => {
                        calls.push(['get', url]);
                        return { segments: [{ entries: [{ text: '更早的第一段' }] }], has_more: false, next_offset: 20 };
                    },
                };
                await loadLegacyMonitorLogs({ append: true });
                calls.push(['body', body.innerText]);
                return calls;
            })()"""
        )

        self.assertIn("offset=0", calls[0][1])
        self.assertEqual(calls[1], ["body", "更早的第一段\n旧的第二段"])

    def test_run_list_skips_unchanged_rerenders(self):
        source = INDEX_JS_PATH.read_text(encoding="utf-8")
        module_source = MONITOR_TAB_MODULE_PATH.read_text(encoding="utf-8")

        self.assertIn("function buildMonitorRunRenderKey", source)
        self.assertIn("if (forceRender || runRenderKey !== lastMonitorRunRenderKey) renderMonitorLogs();", source)
        self.assertIn("runRenderKey !== lastRunRenderKey", module_source)

        keys = run_index_async(
            """(() => {
                const base = { runs: [{ id: 'a', status: 'completed', summary: 'x', updated_at: 't' }], run_page: 1, tasks: [{ name: '电视剧', task_type: 'scan' }] };
                return {
                    stable: buildMonitorRunRenderKey(base) === buildMonitorRunRenderKey({ ...base }),
                    statusChanged: buildMonitorRunRenderKey(base) === buildMonitorRunRenderKey({ ...base, runs: [{ id: 'a', status: 'running', summary: 'x', updated_at: 't' }] }),
                    pageChanged: buildMonitorRunRenderKey(base) === buildMonitorRunRenderKey({ ...base, run_page: 2 }),
                };
            })()"""
        )

        self.assertTrue(keys["stable"])
        self.assertFalse(keys["statusChanged"])
        self.assertFalse(keys["pageChanged"])

    def test_run_list_renders_each_run_as_its_own_flat_row(self):
        html = run_view(
            """[
                window.MonitorRunView.listRow({
                    id: 'inbox-1', task_name: '最近接收', subject: '六部影视', run_kind: 'inbox',
                    source: 'manual', status: 'completed', queued_at: '2026-09-24 21:23:42',
                    summary: '已分发 1 项，后续同步全部完成（含自动补扫）。',
                    result: {moved: 1}, child_count: 1,
                }),
                window.MonitorRunView.listRow({
                    id: 'scan-1', task_name: '电视剧', subject: '影视1', run_kind: 'scan',
                    source: 'auto_rescan', status: 'completed', queued_at: '2026-09-24 21:23:58',
                    summary: '检查完成：新增或更新 1 个本地播放文件。',
                }),
            ].join('')"""
        )

        self.assertIn('data-run-id="inbox-1"', html)
        self.assertIn('data-run-id="scan-1"', html)
        self.assertIn("后续 1 项", html)
        self.assertIn("系统补扫", html)
        self.assertNotIn("monitor-run-group", html)
        self.assertNotIn("is-group-child", html)
        self.assertNotIn("listGroup", html)

    def test_run_detail_nests_downstream_chain(self):
        html = run_view(
            """window.MonitorRunView.detailHtml({
                run: {id: 'inbox-1', task_name: '最近接收', subject: '六部影视', run_kind: 'inbox',
                      status: 'completed', summary: '已分发 6 项，后续同步全部完成。', result: {moved: 6}},
                events: [], counts: {}, total: 0,
                descendants: [
                    {id: 'change-1', task_name: '电视剧', subject: '文件变更', status: 'completed', depth: 1},
                    {id: 'scan-1', task_name: '电视剧', subject: '影视1', status: 'completed', depth: 2},
                ],
            })"""
        )

        self.assertIn("monitor-run-child is-nested", html)
        self.assertIn("--run-depth:2", html)
        self.assertIn("后续同步", html)

    def test_run_list_stays_flat_and_keeps_activity_order(self):
        source = INDEX_JS_PATH.read_text(encoding="utf-8")
        css = INDEX_CSS_PATH.read_text(encoding="utf-8")

        self.assertIn("runs.map(window.MonitorRunView.listRow).join('')", source)
        self.assertIn("按最近活动排序 · 本页", source)
        self.assertNotIn("toggleMonitorRunGroup", source)
        self.assertNotIn("monitor-run-group", source)
        self.assertNotIn(".monitor-run-group", css)

    def test_render_key_tracks_every_dispatched_row(self):
        keys = run_index_async(
            """(() => {
                const head = { id: 'a', status: 'waiting', summary: '等待', updated_at: 't' };
                const dispatched = { id: 'b', status: 'running', summary: '同步中', updated_at: 't' };
                const base = { runs: [head, dispatched], run_page: 1 };
                return {
                    stable: buildMonitorRunRenderKey(base) === buildMonitorRunRenderKey({ runs: [head, dispatched], run_page: 1 }),
                    childChanged: buildMonitorRunRenderKey(base) === buildMonitorRunRenderKey(
                        { runs: [head, { ...dispatched, status: 'completed' }], run_page: 1 }),
                };
            })()"""
        )

        self.assertTrue(keys["stable"])
        self.assertFalse(keys["childChanged"])

    def test_task_scoped_clear_only_runs_for_a_selected_task(self):
        page = MONITOR_PAGE_PATH.read_text(encoding="utf-8")
        source = INDEX_JS_PATH.read_text(encoding="utf-8")

        self.assertIn('id="monitor-run-clear-task"', page)
        self.assertIn("clearMonitorRunTaskRecords()", page)
        self.assertIn("async function clearMonitorRunTaskRecords()", source)
        self.assertIn("task_name: String(taskName || '').trim(),", source)
        self.assertIn("syncMonitorRunTaskClearButton();", source)

        # 没选任务时按钮不出现在页面上，函数也不会发请求。
        none = run_index_async(
            """(async () => {
                const calls = [];
                requestMonitorRunCleanup = async () => { calls.push(['cleanup']); return { count: 1 }; };
                showAppConfirm = async () => { calls.push(['confirm']); return true; };
                await clearMonitorRunTaskRecords();
                return calls;
            })()"""
        )
        self.assertEqual(none, [])

        calls = run_index_async(
            """(async () => {
                const calls = [];
                monitorRunSelectedTaskName = () => '电视剧';
                requestMonitorRunCleanup = async (scope, options = {}) => {
                    calls.push(['cleanup', scope, Boolean(options.preview), options.taskName || '']);
                    return options.preview ? { count: 4 } : { deleted: 4 };
                };
                showAppConfirm = async message => { calls.push(['confirm', message]); return true; };
                showToast = message => calls.push(['toast', message]);
                refreshMonitorRuns = async () => calls.push(['refresh']);
                await clearMonitorRunTaskRecords();
                return calls;
            })()"""
        )

        self.assertEqual(calls[0], ["cleanup", "all_finished", True, "电视剧"])
        self.assertEqual(calls[1][0], "confirm")
        self.assertIn("电视剧", calls[1][1])
        self.assertIn("4 条已结束运行记录", calls[1][1])
        self.assertEqual(calls[2], ["cleanup", "all_finished", False, "电视剧"])
        self.assertIn("已清除", calls[3][1])
        self.assertEqual(calls[4], ["refresh"])

    def test_task_scoped_clear_keeps_records_when_confirmation_is_rejected(self):
        calls = run_index_async(
            """(async () => {
                const calls = [];
                monitorRunSelectedTaskName = () => '电影';
                requestMonitorRunCleanup = async (scope, options = {}) => {
                    calls.push(['cleanup', scope, Boolean(options.preview)]);
                    return options.preview ? { count: 2 } : { deleted: 2 };
                };
                showAppConfirm = async () => { calls.push(['confirm']); return false; };
                showToast = () => calls.push(['toast']);
                refreshMonitorRuns = async () => calls.push(['refresh']);
                await clearMonitorRunTaskRecords();
                return calls;
            })()"""
        )

        self.assertEqual([entry[0] for entry in calls], ["cleanup", "confirm"])


if __name__ == "__main__":
    unittest.main()
