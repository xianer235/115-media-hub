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
MONITOR_ROUTES_PATH = ROOT / "app/routes/monitor.py"
MONITOR_MODAL_PATH = ROOT / "templates/partials/modals/monitor.html"


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

    def test_move_detail_shows_identification_mapping(self):
        html = run_view(
            "window.MonitorRunView.detailRows({"
            "original_name: '[朱弦玉磐2024][简繁英字幕].Musica.2024.2160p.mkv', "
            "new_name: '朱弦玉磐 (2024) [tmdbid-1171826]', "
            "match_source: 'AI 识别', "
            "confidence: 88, "
            "match_reason: '片名与年份一致', "
            "tmdb_id: 1171826, "
            "identified_year: '2024'"
            "})"
        )

        self.assertIn("原文件名", html)
        self.assertIn("Musica.2024.2160p.mkv", html)
        self.assertIn("新名称", html)
        self.assertIn("朱弦玉磐 (2024) [tmdbid-1171826]", html)
        self.assertIn("识别来源", html)
        self.assertIn("AI 识别", html)
        self.assertIn("置信度", html)
        self.assertIn("识别理由", html)
        self.assertIn("TMDB ID", html)
        self.assertIn("识别年份", html)

    def test_tabs_are_mutually_exclusive(self):
        """页签互斥显示：切到哪一页只渲染该页内容，不再有原始事件折叠。"""
        detail = (
            "{run: {id: 'r1', run_kind: 'change', task_name: '电视剧', status: 'completed', result: {completed: 1}}, "
            "events: ["
            "{id: 'a', category: 'remote', operation: 'move', status: 'completed', title: 'X', "
            "detail: {old_path: '最近接收/X', new_path: '电影/X'}, created_at: '2026-09-23 10:00:01'},"
            "{id: 'b', category: 'strm', operation: 'write', status: 'completed', title: 'F.strm', "
            "detail: {strm_path: '电影/X/F.strm'}, created_at: '2026-09-23 10:00:02'},"
            "{id: 'c', category: 'problem', operation: 'read_dir', status: 'failed', title: '读取目录失败', "
            "detail: {error: 'timeout'}, created_at: '2026-09-23 10:00:03'}], "
            "counts: {remote: 1, strm: 1, problem: 1}, total: 3}"
        )
        overview = run_view(f"window.MonitorRunView.detailHtml({detail}, '')")
        remote = run_view(f"window.MonitorRunView.detailHtml({detail}, 'remote')")
        strm = run_view(f"window.MonitorRunView.detailHtml({detail}, 'strm')")
        problem = run_view(f"window.MonitorRunView.detailHtml({detail}, 'problem')")

        self.assertNotIn("monitor-run-event-row", overview)
        self.assertNotIn("monitor-run-line-list", overview)
        self.assertIn("原位置", remote)
        self.assertIn("最近接收/X", remote)
        self.assertIn("新位置", remote)
        self.assertIn("电影/X", remote)
        self.assertNotIn("F.strm", remote)
        self.assertIn("F.strm", strm)
        self.assertNotIn("读取目录失败", strm)
        self.assertIn("读取目录失败", problem)
        self.assertNotIn("最近接收/X", problem)
        for html in (overview, remote, strm, problem):
            self.assertNotIn("原始事件（", html)

    def test_tabs_follow_task_kind(self):
        """页签按任务类型匹配：接收夹没有本地文件，目录同步没有网盘操作（自动整理除外）。"""
        tabs = run_view(
            "(() => {"
            "const inbox = {run_kind: 'inbox', source: 'manual'};"
            "const scan = {run_kind: 'scan', source: 'manual'};"
            "const scanAuto = {run_kind: 'scan', source: 'manual'};"
            "const change = {run_kind: 'change', source: 'change'};"
            "const keys = defs => defs.map(item => item[0]).join(',');"
            "return {"
            "inbox: keys(window.MonitorRunView.tabDefsFor(inbox, {remote: 2, strm: 0, problem: 1})),"
            "scan: keys(window.MonitorRunView.tabDefsFor(scan, {remote: 0, strm: 9, problem: 0})),"
            "scanAuto: keys(window.MonitorRunView.tabDefsFor(scanAuto, {remote: 1, strm: 9, problem: 0})),"
            "change: keys(window.MonitorRunView.tabDefsFor(change, {remote: 1, strm: 3, problem: 0})),"
            "inboxResolved: window.MonitorRunView.resolveTab("
            "{run: inbox, counts: {remote: 2}}, 'strm'),"
            "scanResolved: window.MonitorRunView.resolveTab("
            "{run: scan, counts: {strm: 9}}, 'remote'),"
            "}; })()"
        )

        self.assertEqual(tabs["inbox"], ",remote,problem")
        self.assertEqual(tabs["scan"], ",strm,problem")
        self.assertEqual(tabs["scanAuto"], ",remote,strm,problem")
        self.assertEqual(tabs["change"], ",remote,strm,problem")
        # 不适用的页签一律回到概览，避免渲染出空的本地/网盘页。
        self.assertEqual(tabs["inboxResolved"], "")
        self.assertEqual(tabs["scanResolved"], "")

    def test_scan_without_auto_organize_has_no_remote_tab(self):
        html = run_view(
            "window.MonitorRunView.tabsHtml({run: {id: 's1', run_kind: 'scan', source: 'manual'}, "
            "counts: {remote: 0, strm: 12, problem: 0}}, '')"
        )

        self.assertNotIn("网盘变更", html)
        self.assertIn("本地文件", html)
        self.assertIn("问题", html)

    def test_problem_tab_renders_inbox_leftovers(self):
        html = run_view(
            "window.MonitorRunView.detailHtml({run: {id: 'i1', run_kind: 'inbox', task_name: '接收', "
            "status: 'partial', result: {left: 1}}, "
            "events: [{id: 'e1', category: 'problem', operation: 'leave_in_inbox', status: 'skipped', "
            "title: '无法识别', detail: {reason: '未匹配到 TMDB 条目'}, created_at: '2026-09-23 10:00:00'}], "
            "counts: {problem: 1}, total: 1}, 'problem')"
        )

        self.assertIn("保留在接收夹", html)
        self.assertIn("无法识别", html)
        self.assertIn("未匹配到 TMDB 条目", html)
        self.assertNotIn("等待处理", html)

    def test_list_keeps_problem_summary_and_defers_metrics_to_detail(self):
        html = run_view(
            "window.MonitorRunView.listRow({id: 'run-1', task_name: '电视剧', subject: '示例剧', "
            "source: 'webhook', status: 'partial', queued_at: '2026-09-23 10:00:00', "
            "summary: '1 个目录读取失败；已保护现有文件。', "
            "result: {generated: 12, failed_dirs: 1}})"
        )

        self.assertIn("1 个目录读取失败", html)
        self.assertIn("部分完成", html)
        # 列表只保留简要信息：来源和明细指标移入详情弹窗。
        self.assertNotIn("外部通知", html)
        self.assertNotIn("新增或更新", html)
        self.assertNotIn("失败目录", html)
        self.assertNotIn("partial", html)

    def test_inbox_left_metric_is_labeled_as_finished_unhandled_work(self):
        html = run_view(
            "window.MonitorRunView.detailHtml({run: {id: 'run-left', task_name: '接收', subject: '混合结果', "
            "source: 'manual', status: 'partial', queued_at: '2026-09-23 10:00:00', "
            "result: {moved: 1, left: 1}}, events: [], counts: {}, total: 0})"
        )

        self.assertIn("留在接收夹", html)
        self.assertNotIn("待处理", html)


    def test_run_detail_shows_kind_chip_and_parent_context(self):
        detail = (
            "{run: {id: 'change-1', task_name: '电影', subject: '示例电影', "
            "run_kind: 'change', source: 'change', status: 'completed', "
            "parent_task_name: '接收', parent_subject: '示例电影', queued_at: '2026-09-23 10:00:00'}, "
            "events: [{id: 'e1', category: 'remote', operation: 'move', status: 'completed', title: '示例电影', "
            "detail: {old_path: '最近接收/示例电影', new_path: '115自存电影/示例电影'}, created_at: '2026-09-23 10:00:01'}], "
            "counts: {remote: 1}, total: 1}"
        )
        overview = run_view(f"window.MonitorRunView.detailHtml({detail})")
        remote = run_view(f"window.MonitorRunView.detailHtml({detail}, 'remote')")

        self.assertIn("变更同步", overview)
        self.assertIn("来自接收夹整理：接收 · 示例电影", overview)
        self.assertIn("网盘变更", remote)
        self.assertIn("移动", remote)
        # 网盘明细写清原位置与新位置，而不是只给一条 A → B。
        self.assertIn("原位置", remote)
        self.assertIn("最近接收/示例电影", remote)
        self.assertIn("新位置", remote)
        self.assertIn("115自存电影/示例电影", remote)

    def test_run_filter_controls_separate_task_workflow_and_trigger(self):
        page = MONITOR_PAGE_PATH.read_text(encoding="utf-8")
        source = INDEX_JS_PATH.read_text(encoding="utf-8")

        self.assertIn('id="monitor-run-kind-filter"', page)
        self.assertIn("全部配置任务", page)
        self.assertIn("全部启动方式", page)
        # 启动方式只暴露用户视角的 5 组，内部来源细节留在记录里。
        for label in ("手动操作", "定时执行", "推送通知", "导入完成", "系统跟进"):
            self.assertIn(label, page)
        self.assertNotIn('value="auto_rescan"', page)
        self.assertNotIn('value="inbox_dispatch"', page)
        # 状态筛选同样按 4 组展示。
        for label in ("进行中", "已完成", "需处理", "已中断"):
            self.assertIn(label, page)
        self.assertIn("run_kind: document.getElementById('monitor-run-kind-filter')?.value || ''", source)
        self.assertIn("source_group: document.getElementById('monitor-run-source-filter')?.value || ''", source)
        self.assertIn("status_group: document.getElementById('monitor-run-status-filter')?.value || ''", source)
        self.assertIn("接收夹整理", source)
        self.assertIn("目录监控", source)
        # 接口必须把分组参数转发给后端。
        routes = MONITOR_ROUTES_PATH.read_text(encoding="utf-8")
        self.assertIn('source_group=str(request.query_params.get("source_group", "") or "")', routes)
        self.assertIn('status_group=str(request.query_params.get("status_group", "") or "")', routes)

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
        header = page[header_start:page.index('id="monitor-run-modal-body"', header_start)]

        # 页头只允许“标题 + 右侧动作组”两种子元素。
        actions_at = header.index('class="app-dialog-header-actions"')
        title_div_at = header.index("<div>")
        buttons = ("monitor-run-refresh", "monitor-run-close")
        self.assertLess(title_div_at, actions_at)
        for marker in buttons:
            self.assertIn(marker, header)
        self.assertIn(".monitor-run-modal-shell", css)

    def test_retention_dialog_uses_readable_day_theme_text(self):
        css = INDEX_CSS_PATH.read_text(encoding="utf-8")

        self.assertIn(".monitor-run-retention-body {", css)
        self.assertIn("color: var(--run-text);", css)
        self.assertIn("html.theme-day .monitor-run-retention-body", css)
        self.assertIn("html.theme-day .monitor-run-retention-body .form-check-label", css)

    def test_records_entry_is_named_management(self):
        """入口名字要覆盖"保留策略 + 手动清理"两件事，所以叫「记录管理」。"""
        page = MONITOR_PAGE_PATH.read_text(encoding="utf-8")
        source = INDEX_JS_PATH.read_text(encoding="utf-8")

        self.assertIn('onclick="openMonitorRunRetention()" class="log-header-btn">记录管理</button>', page)
        self.assertIn('id="monitor-run-retention-title" class="app-dialog-title">记录管理</div>', page)
        self.assertNotIn(">记录保留<", page)
        self.assertIn("可在“记录管理”里单独清理", source)
        # 弹窗里仍然是"保留策略 + 手动清理"两段，名字变了但功能不动。
        self.assertIn("保留策略", page)
        self.assertIn("手动清理", page)

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
        """没有逐条问题事件时，概览用“未完成内容”一行说明（问题页签仍在，用来看逐条问题）。"""
        html = run_view(
            "window.MonitorRunView.detailHtml({"
            "run: {status: 'partial', run_kind: 'change', task_name: '电视剧', subject: '文件变更', "
            "summary: '已同步 1 条网盘变更，1 个目录等待系统补扫', result: {completed: 1, manual_required: 1}}, "
            "events: [], counts: {process: 3, remote: 1, strm: 0, problem: 0}, total: 3, has_more: false"
            "})"
        )

        self.assertIn("monitor-run-derived-line", html)
        self.assertIn("等待系统补扫", html)
        self.assertIn("未完成内容", html)

    def test_completed_run_without_derived_issues_keeps_clean_result(self):
        html = run_view(
            "window.MonitorRunView.detailHtml({"
            "run: {status: 'completed', run_kind: 'change', summary: '已同步 3 条网盘变更', result: {completed: 3}}, "
            "events: [], counts: {problem: 0, remote: 3}, total: 3, has_more: false"
            "})"
        )

        self.assertNotIn("monitor-run-derived-line", html)
        self.assertIn("已同步 3 条网盘变更", html)


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

    def test_list_row_has_no_child_toggle(self):
        """列表精简：一行一个工作单元，不再有子任务折叠开关与行内子任务。"""
        html = run_view(
            """window.MonitorRunView.listRow({
                id: 'inbox-1', task_name: '最近接收', subject: '六部影视', run_kind: 'inbox',
                source: 'manual', status: 'completed', queued_at: '2026-09-24 21:23:42',
                summary: '已分发 1 项。',
                result: {moved: 1}, child_count: 1, children_done: 1,
                children: [{
                    id: 'scan-1', task_name: '电视剧', subject: '影视1', run_kind: 'scan',
                    source: 'inbox_dispatch', status: 'completed', queued_at: '2026-09-24 21:23:58',
                    summary: '检查完成：新增或更新 1 个本地播放文件。',
                    depth: 1,
                }],
            })"""
        )

        self.assertIn('data-run-id="inbox-1"', html)
        self.assertIn("接收夹整理", html)
        self.assertIn("已分发 1 项。", html)
        self.assertNotIn("scan-1", html)
        self.assertNotIn("data-run-group-toggle", html)
        self.assertNotIn("monitor-run-children", html)
        self.assertNotIn("子任务 1/1", html)


    def test_list_row_folds_dispatched_scan_upstream(self):
        """变更同步 + 它派生的目录同步合并成一行：主行是目录同步，副行说明上游。"""
        html = run_view(
            """window.MonitorRunView.listRow({
                id: 'scan-1', task_name: '电视剧', subject: '鱿鱼游戏：真人挑战赛 (2023) [tmdbid-204082]',
                run_kind: 'scan', source: 'inbox_dispatch', status: 'completed',
                queued_at: '2026-09-27T05:54:43', summary: '检查完成：新增或更新 6 个本地播放文件。',
                result: {generated: 6},
                upstream_change: {
                    id: 'change-1', run_kind: 'change', source: 'change', status: 'completed',
                    summary: '已同步 1 条网盘变更。', queued_at: '2026-09-27T05:54:43',
                },
            })"""
        )

        self.assertIn('data-run-id="scan-1"', html)
        self.assertIn("目录同步", html)
        self.assertIn("新增或更新 6 个本地播放文件", html)
        self.assertIn("上游：变更同步", html)
        self.assertIn("已同步 1 条网盘变更", html)
        # 上游只作副行说明，主行仍是唯一的可点目标，避免误点。
        self.assertEqual(html.count("data-run-id"), 1)

    def test_scan_detail_links_to_upstream_change(self):
        """目录同步详情给出可点开的上游变更同步，复用弹窗内的行点击委托。"""
        html = run_view(
            """window.MonitorRunView.detailHtml({
                run: {id: 'scan-1', task_name: '电视剧', subject: '示例剧', run_kind: 'scan',
                      status: 'completed', queued_at: '2026-09-27T05:54:43', started_at: '2026-09-27T05:54:43',
                      finished_at: '2026-09-27T05:54:57', summary: '检查完成：新增或更新 6 个本地播放文件。',
                      result: {generated: 6}},
                events: [], counts: {}, total: 0,
                upstream_change: {id: 'change-1', run_kind: 'change', source: 'change', status: 'completed',
                                  summary: '已同步 1 条网盘变更。', finished_at: '2026-09-27T05:54:43'},
            })"""
        )

        self.assertIn('class="monitor-run-upstream-row" data-run-id="change-1"', html)
        self.assertIn("上游 · 变更同步", html)
        self.assertIn("已同步 1 条网盘变更", html)

    def test_detail_without_upstream_keeps_layout(self):
        html = run_view(
            "window.MonitorRunView.detailHtml({run: {id: 's1', run_kind: 'scan', task_name: '电影', "
            "status: 'completed', summary: '检查完成', result: {generated: 1}}, events: [], counts: {}, total: 0})"
        )

        self.assertNotIn("monitor-run-upstream-row", html)


    def test_legacy_inbox_children_render_in_overview(self):
        """历史父子记录仍可读：接收夹概览底部列出旧子任务，可点开对应记录。"""
        html = run_view(
            """window.MonitorRunView.detailHtml({
                run: {id: 'inbox-1', task_name: '最近接收', subject: '六部影视', run_kind: 'inbox',
                      status: 'completed', summary: '成功分发 1 项，1 项 STRM 同步全部结束。', result: {moved: 1}},
                events: [],
                counts: {},
                children: [{id: 'scan-1', run_kind: 'scan', task_name: '电视剧', subject: '影视1', status: 'completed', depth: 1, result: {generated: 8}}],
                descendants: [{id: 'scan-1', run_kind: 'scan', task_name: '电视剧', subject: '影视1', status: 'completed', depth: 1, result: {generated: 8}}],
            })"""
        )

        self.assertIn("后续任务（历史记录）", html)
        self.assertIn('data-run-id="scan-1"', html)
        self.assertIn("影视1", html)
        self.assertIn("已完成", html)

    def test_problem_tab_keeps_raw_diagnostics(self):
        """问题页签给出中文原因，原始英文错误收进随行可展开的诊断块。"""
        html = run_view(
            """window.MonitorRunView.detailHtml({
                run: {id: 'run-1', task_name: '电视剧', subject: '示例剧', run_kind: 'scan',
                      status: 'failed', summary: '扫描失败', result: {failed_dirs: 1}},
                events: [
                    {id: 'run-2', category: 'problem', operation: 'read_dir', status: 'failed',
                     title: '读取目录失败', created_at: '2026-09-25 10:00:01',
                     detail: {error: 'permission denied for /115/TV/Show'}},
                ],
                counts: {problem: 1}, total: 1,
            }, 'problem')"""
        )

        self.assertIn("读取目录失败", html)
        self.assertIn("访问被拒绝", html)
        self.assertIn('<details class="monitor-run-diagnostic" open>', html)
        self.assertIn("permission denied for /115/TV/Show", html)


    def test_inbox_overview_has_two_step_strip(self):
        """接收夹概览只有两步：识别 → 整理移动；STRM 生成属于独立的目录同步任务。"""
        html = run_view(
            """window.MonitorRunView.detailHtml({
                run: {id: 'inbox-1', task_name: '接收', subject: '魔方小姐（2026）', run_kind: 'inbox',
                      status: 'completed', queued_at: '2026-09-26 15:42:00', started_at: '2026-09-26 15:42:00',
                      finished_at: '2026-09-26 15:42:06',
                      summary: '已分发 1 项。', result: {moved: 1, left: 0}},
                events: [
                    {id: 'e1', category: 'process', operation: 'identified', status: 'completed',
                     title: '识别完成', detail: {subjects: ['魔方小姐（2026）']}, created_at: '2026-09-26 15:42:02'},
                    {id: 'e2', category: 'remote', operation: 'move', status: 'completed', title: '魔方小姐 (2026)',
                     detail: {old_path: '最近接收/魔方小姐', new_path: '115自存电影/魔方小姐'}, created_at: '2026-09-26 15:42:03'},
                ],
                counts: {process: 1, remote: 1}, total: 2,
            })"""
        )

        self.assertIn("monitor-run-steps", html)
        self.assertIn("识别", html)
        self.assertIn("整理移动", html)
        self.assertIn("分发 1 项", html)
        self.assertNotIn("本地 STRM 同步", html)
        self.assertNotIn("monitor-run-line-list", html)
        self.assertNotIn("原始事件（", html)
        # 步骤只出现一次：概览的步骤条不再复制到别处。
        self.assertEqual(html.count("monitor-run-step-name"), 2)

    def test_inbox_overview_lists_original_and_organized_names(self):
        """接收夹概览显示原始名称 -> 整理后名称，并附识别来源与置信度。"""
        html = run_view(
            """window.MonitorRunView.detailHtml({
                run: {id: 'inbox-1', task_name: '接收', subject: '示例剧', run_kind: 'inbox',
                      status: 'completed', summary: '已分发 1 项。', result: {moved: 1, left: 0}},
                events: [],
                inbox_items: [
                    {original_name: '【原始文件夹】示例剧', new_name: '示例剧 (2024) [tmdbid-1]',
                     match_source: 'AI 识别', confidence: 68},
                ],
                counts: {}, total: 0,
            })"""
        )

        self.assertIn("已整理条目", html)
        self.assertIn("【原始文件夹】示例剧", html)
        self.assertIn("示例剧 (2024) [tmdbid-1]", html)
        self.assertIn("AI 识别 · 68", html)
        self.assertIn("monitor-run-inbox-pair", html)

    def test_inbox_overview_name_mapping_only_for_inbox_and_nonempty(self):
        scan = run_view(
            "window.MonitorRunView.detailHtml({run: {id: 's1', run_kind: 'scan', task_name: '电影', "
            "status: 'completed', summary: '检查完成', result: {generated: 1}}, events: [], "
            "inbox_items: [{original_name: 'A', new_name: 'B'}], counts: {}, total: 0})"
        )
        empty_inbox = run_view(
            "window.MonitorRunView.detailHtml({run: {id: 'i2', run_kind: 'inbox', task_name: '接收', "
            "status: 'no_change', summary: '没有需要分发的条目', result: {moved: 0}}, events: [], "
            "inbox_items: [], counts: {}, total: 0})"
        )

        self.assertNotIn("已整理条目", scan)
        self.assertNotIn("monitor-run-inbox-pair", scan)
        self.assertNotIn("已整理条目", empty_inbox)
        self.assertNotIn("monitor-run-inbox-pair", empty_inbox)

    def test_overview_scope_paths_render_line_by_line(self):
        """变更同步的多条范围路径要逐行展示，不能堆成一段。"""
        html = run_view(
            """window.MonitorRunView.detailHtml({
                run: {id: 'c1', run_kind: 'change', task_name: '电视剧', source: 'change', status: 'completed',
                      summary: '已同步 2 条网盘变更', scope: {kind: 'paths', paths: [
                        '电视剧/抑制热情 (2000) [tmdbid-4546]/Subs/S08E01',
                        '电视剧/抑制热情 (2000) [tmdbid-4546]/Subs/S08E02',
                      ]}},
                events: [], counts: {}, total: 0,
            })"""
        )

        self.assertIn("monitor-run-scope-paths", html)
        self.assertEqual(html.count('class="monitor-run-scope-path"'), 2)
        self.assertIn("S08E01", html)
        self.assertIn("S08E02", html)
        self.assertNotIn("S08E01、S08E02", html)

    def test_change_and_scan_overview_skip_step_strip(self):
        scan = run_view(
            "window.MonitorRunView.detailHtml({run: {id: 's1', run_kind: 'scan', task_name: '电影', "
            "status: 'completed', summary: '检查完成', result: {generated: 1}}, events: [], counts: {}, total: 0})"
        )
        change = run_view(
            "window.MonitorRunView.detailHtml({run: {id: 'c1', run_kind: 'change', task_name: '电影', "
            "status: 'completed', summary: '已同步 1 条网盘变更', result: {completed: 1}}, events: [], counts: {}, total: 0})"
        )

        self.assertNotIn("monitor-run-steps", scan)
        self.assertNotIn("monitor-run-steps", change)
        self.assertIn("monitor-run-simple", scan)
        self.assertIn("已同步 1 条网盘变更", change)


    def test_three_task_kinds_read_differently(self):
        """网盘变更页签按任务类型分组：接收夹两节、自动整理一节、变更同步一节。"""
        inbox_html = run_view(
            "window.MonitorRunView.detailHtml({run: {id: 'i1', run_kind: 'inbox', task_name: '接收', subject: 'X', "
            "status: 'completed', summary: '分发完成', result: {moved: 1}}, events: ["
            "{id: 'a', category: 'remote', operation: 'organize', status: 'completed', title: 'X', "
            "detail: {old_path: '最近接收/X 旧名', new_path: '最近接收/X'}, created_at: 't'},"
            "{id: 'b', category: 'remote', operation: 'move', status: 'completed', title: 'X', "
            "detail: {old_path: '最近接收/X', new_path: '电影/X'}, created_at: 't'}], "
            "counts: {remote: 2}, total: 2}, 'remote')"
        )
        scan_html = run_view(
            "window.MonitorRunView.detailHtml({run: {id: 's1', run_kind: 'scan', task_name: '电影', subject: '全部目录', "
            "status: 'completed', summary: '检查完成', result: {generated: 1}}, events: "
            "[{id: 'c', category: 'remote', operation: 'auto_organize', status: 'completed', title: '自动整理', "
            "detail: {summary: '自动整理完成'}, created_at: 't'}], counts: {remote: 1}, total: 1}, 'remote')"
        )
        change_html = run_view(
            "window.MonitorRunView.detailHtml({run: {id: 'c1', run_kind: 'change', task_name: '电影', subject: 'X', "
            "status: 'completed', summary: '已同步', result: {completed: 1}}, events: "
            "[{id: 'd', category: 'remote', operation: 'move', status: 'completed', title: 'X', "
            "detail: {old_path: '最近接收/X', new_path: '电影/X'}, created_at: 't'}], counts: {remote: 1}, total: 1}, 'remote')"
        )

        self.assertIn("整理重命名", inbox_html)
        self.assertIn("移动到监控文件夹", inbox_html)
        self.assertIn("原位置", inbox_html)
        self.assertIn("最近接收/X", inbox_html)
        self.assertIn("电影/X", inbox_html)
        self.assertNotIn("自动整理", inbox_html)
        self.assertIn("自动整理", scan_html)
        self.assertNotIn("整理重命名", scan_html)
        self.assertIn("网盘变更", change_html)
        self.assertNotIn("整理重命名", change_html)
        self.assertNotIn("移动到监控文件夹", change_html)

    def test_remote_event_extras_show_identification_mapping(self):
        html = run_view(
            "window.MonitorRunView.detailHtml({run: {id: 'i2', run_kind: 'inbox', task_name: '接收', subject: 'X', "
            "status: 'completed', summary: '分发完成', result: {moved: 1}}, events: "
            "[{id: 'e1', category: 'remote', operation: 'move', status: 'completed', title: 'X', "
            "detail: {original_name: '魔方小姐 2026.mkv', new_name: '魔方小姐 (2026)', old_path: '最近接收/魔方小姐', "
            "new_path: '电影/魔方小姐 (2026)', match_source: 'AI 识别', confidence: 96}, created_at: 't'}], "
            "counts: {remote: 1}, total: 1}, 'remote')"
        )

        # 接收夹明细写清原始与新位置、名称，识别信息随行。
        self.assertIn("原位置", html)
        self.assertIn("最近接收/魔方小姐", html)
        self.assertIn("原名称", html)
        self.assertIn("魔方小姐 2026.mkv", html)
        self.assertIn("新位置", html)
        self.assertIn("电影/魔方小姐 (2026)", html)
        self.assertIn("新名称", html)
        self.assertIn("AI 识别", html)
        self.assertIn("置信度", html)
        self.assertIn("96", html)

    def test_strm_rows_show_remote_and_local_paths(self):
        """监控任务的本地文件明细同时给出网盘位置/名称与本地位置/名称。"""
        html = run_view(
            "window.MonitorRunView.detailHtml({run: {id: 's11', run_kind: 'scan', task_name: '电影', "
            "status: 'completed', summary: '检查完成', result: {generated: 1}}, events: "
            "[{id: 'w1', category: 'strm', operation: 'write', status: 'completed', "
            "title: '片名 (2024).mkv.strm', "
            "detail: {strm_path: '/app/strm/电影/片名 (2024)/片名 (2024).mkv.strm', "
            "remote_path: '/115/电影/片名 (2024)/片名 (2024).mkv'}, created_at: 't'}], "
            "counts: {strm: 1}, total: 1}, 'strm')"
        )

        for label in ("网盘位置", "网盘名称", "本地位置", "本地名称"):
            self.assertIn(label, html)
        self.assertIn("/115/电影/片名 (2024)/片名 (2024).mkv", html)
        self.assertIn("/app/strm/电影/片名 (2024)/片名 (2024).mkv.strm", html)

    def test_change_file_event_shows_cloud_and_local_paths(self):
        """变更同步的文件级事件也要显示网盘与本地两侧路径（否则只剩一个文件名）。"""
        html = run_view(
            "window.MonitorRunView.detailHtml({run: {id: 'c9', run_kind: 'change', task_name: '电视剧', "
            "status: 'completed', summary: '已同步 1 条网盘变更', result: {completed: 1}}, events: "
            "[{id: 'g1', category: 'strm', operation: 'generate', status: 'completed', "
            "title: '交锋 (2026) - S01E36.mkv.strm', detail: {kind: 'file', "
            "strm_path: '115自存电视剧/交锋 (2026) [tmdbid-294486]/Season 01/交锋 (2026) - S01E36.mkv.strm', "
            "remote_path: '115自存电视剧/交锋 (2026) [tmdbid-294486]/Season 01/交锋 (2026) - S01E36.mkv'}, "
            "created_at: 't'}], counts: {strm: 1}, total: 1}, 'strm')"
        )

        self.assertIn("网盘位置", html)
        self.assertIn("[tmdbid-294486]/Season 01/交锋 (2026) - S01E36.mkv", html)
        self.assertIn("本地位置", html)
        self.assertIn("交锋 (2026) - S01E36.mkv.strm", html)

    def test_change_file_event_falls_back_to_new_paths(self):
        """旧记录只有 new_path / new_remote_path 时也要能显示两侧路径。"""
        html = run_view(
            "window.MonitorRunView.detailHtml({run: {id: 'c10', run_kind: 'change', task_name: '电视剧', "
            "status: 'completed', summary: '已同步 1 条网盘变更', result: {completed: 1}}, events: "
            "[{id: 'g2', category: 'strm', operation: 'generate', status: 'completed', title: '旧记录.strm', "
            "detail: {kind: 'file', "
            "new_path: '本地/电视剧/交锋/Season 01/交锋 - S01E36.mkv.strm', "
            "new_remote_path: '网盘/电视剧/交锋/Season 01/交锋 - S01E36.mkv'}, created_at: 't'}], "
            "counts: {strm: 1}, total: 1}, 'strm')"
        )

        self.assertIn("本地/电视剧/交锋/Season 01/交锋 - S01E36.mkv.strm", html)
        self.assertIn("网盘/电视剧/交锋/Season 01/交锋 - S01E36.mkv", html)


    def test_many_local_file_events_collapse_into_one_line(self):
        """本地文件页签逐行列出文件，并显示“已显示 X / 共 N 条”和加载更多。"""
        html = run_view(
            """window.MonitorRunView.detailHtml({
                run: {id: 's2', run_kind: 'scan', task_name: '电视剧', subject: '全部目录', status: 'completed',
                      summary: '检查完成：新增或更新 5 个本地播放文件。', result: {generated: 5}},
                events: [1,2,3,4,5].map(index => ({
                    id: 'f' + index, category: 'strm', operation: 'write', status: 'completed',
                    title: 'E0' + index + '.strm', created_at: '2026-09-26 15:00:0' + index,
                    detail: {strm_path: '电视剧/示例/E0' + index + '.strm'},
                })),
                counts: {strm: 5}, total: 5,
            }, 'strm')"""
        )

        self.assertEqual(html.count("monitor-run-event-row"), 5)
        self.assertIn("E01.strm", html)
        self.assertIn("已显示 5 / 共 5 条", html)

    def test_strm_tab_uses_authoritative_counts_and_load_more(self):
        """文件明细只加载了 4 条时，共 N 条取运行统计（100），并给出加载更多。"""
        html = run_view(
            """window.MonitorRunView.detailHtml({
                run: {id: 's9', run_kind: 'scan', task_name: '电视剧', subject: '全部目录', status: 'completed',
                      summary: '检查完成：新增或更新 100 个本地播放文件。', result: {generated: 100}},
                events: [1,2,3,4].map(index => ({
                    id: 'w' + index, category: 'strm', operation: 'write', status: 'completed',
                    title: 'E' + index + '.strm', created_at: 't', detail: {strm_path: '电视剧/E' + index + '.strm'},
                })),
                counts: {strm: 100}, total: 100, has_more: true,
            }, 'strm')"""
        )

        self.assertIn("已显示 4 / 共 100 条", html)
        self.assertIn("loadMoreMonitorRunEvents()", html)
        self.assertEqual(html.count("monitor-run-event-row"), 4)

    def test_strm_truncation_summary_row_keeps_title(self):
        """超过逐条上限时的汇总行要显示“另有 N 个…”而不是只剩范围路径。"""
        html = run_view(
            "window.MonitorRunView.detailHtml({run: {id: 's10', run_kind: 'change', task_name: '电视剧', "
            "status: 'completed', summary: '已同步', result: {completed: 1}}, events: "
            "[{id: 't1', category: 'strm', operation: 'sync', status: 'completed', "
            "title: '另有 30 个本地播放文件未逐条列出', "
            "detail: {step: 'STRM 同步', scope: '电视剧/示例剧', generated: 30, operation_label: '新增'}, "
            "created_at: 't'}], counts: {strm: 1}, total: 1}, 'strm')"
        )

        self.assertIn("另有 30 个本地播放文件未逐条列出", html)
        self.assertIn("电视剧/示例剧", html)
        self.assertIn("新增或更新 30 个", html)

    def test_inbox_has_no_local_file_tab(self):
        """接收夹只做识别与整理移动：页签里没有本地文件，切过去也回到概览。"""
        tabs = run_view(
            "window.MonitorRunView.tabsHtml({run: {id: 'i3', run_kind: 'inbox', source: 'manual'}, "
            "counts: {remote: 2, strm: 0, problem: 1}}, '')"
        )
        fallback = run_view(
            "window.MonitorRunView.detailHtml({run: {id: 'i3', run_kind: 'inbox', task_name: '接收', "
            "status: 'completed', summary: '已分发 1 项。', result: {moved: 1}}, events: [], "
            "counts: {remote: 2, strm: 0, problem: 1}, total: 0}, 'strm')"
        )

        self.assertIn("网盘变更", tabs)
        self.assertIn("问题", tabs)
        self.assertNotIn("本地文件", tabs)
        self.assertIn("运行结果", fallback)
        self.assertNotIn("接收夹整理只负责识别与移动", fallback)

    def test_auto_rescan_copy_stays_automatic(self):
        """补扫弹窗必须说明“系统自动按目录补扫”，不能退回“需手动监控 / 重新扫描”的口径。"""
        modal = MONITOR_MODAL_PATH.read_text(encoding="utf-8")
        source = INDEX_JS_PATH.read_text(encoding="utf-8")

        self.assertIn("待自动补扫目录", modal)
        self.assertIn("不需要手动操作", modal)
        self.assertIn("只自动尝试一次", modal)
        self.assertNotIn("需手动监控路径", modal)
        # 卡片把“补扫失败”单独标出来，提示需要人工处理。
        self.assertIn("补扫失败", source)
        self.assertIn("monitor-manual-required-link is-error", source)


    def test_delegated_local_files_read_as_a_sentence(self):
        waiting_html = run_view(
            """window.MonitorRunView.detailHtml({
                run: {id: 'change-2', run_kind: 'change', task_name: '电影', subject: '魔方小姐 (2026)',
                      status: 'waiting', source: 'change', queued_at: '2026-09-26 15:42:03',
                      summary: '已同步 1 条网盘变更，等待 1 个目录的自动补扫', result: {completed: 1, manual_required: 1}},
                events: [
                    {id: 'd1', category: 'remote', operation: 'move', status: 'completed', title: '魔方小姐',
                     detail: {old_path: '最近接收/魔方小姐', new_path: '115自存电影/魔方小姐'}, created_at: '2026-09-26 15:42:03'},
                    {id: 'd2', category: 'process', operation: 'delegated', status: 'waiting',
                     title: '本地播放文件由后续补扫任务生成', detail: {children: 1, independent_children: 0}, created_at: '2026-09-26 15:42:03'},
                ],
                counts: {process: 1, remote: 1}, total: 2,
            }, 'strm')"""
        )
        independent_html = run_view(
            """window.MonitorRunView.detailHtml({
                run: {id: 'change-3', run_kind: 'change', task_name: '电影', subject: '魔方小姐 (2026)',
                      status: 'no_change', source: 'change', queued_at: '2026-09-26 15:42:03',
                      summary: '已同步 1 条网盘变更。', result: {completed: 1, dispatched_items: 1}},
                events: [
                    {id: 'd3', category: 'process', operation: 'delegated', status: 'completed',
                     title: '本地播放文件由独立的目录同步任务生成', detail: {children: 0, independent_children: 1},
                     created_at: '2026-09-26 15:42:04'},
                ],
                counts: {process: 1}, total: 1,
            }, 'strm')"""
        )

        self.assertIn("等待 1 个目录补扫完成", waiting_html)
        self.assertIn("由 1 项独立的目录同步任务生成", independent_html)
        self.assertIn("各自留有单独记录", independent_html)

    def test_run_list_groups_children_and_keeps_activity_order(self):
        """列表按开始时间排序，且不再有父子折叠：工作单元各占一行。"""
        source = INDEX_JS_PATH.read_text(encoding="utf-8")
        css = INDEX_CSS_PATH.read_text(encoding="utf-8")

        self.assertIn("runs.map(window.MonitorRunView.listRow).join('')", source)
        self.assertIn("按开始时间排序 · 本页", source)
        self.assertNotIn("toggleMonitorRunGroup", source)
        self.assertNotIn("monitorRunExpandedGroups", source)
        self.assertNotIn("data-run-group-toggle", source)
        self.assertNotIn(".monitor-run-children", css)
        self.assertNotIn(".monitor-run-group-toggle", css)

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



class MonitorRunTabbedDetailTest(unittest.TestCase):
    """详情是四个互斥页签：概览、网盘变更、本地文件、问题。"""

    def test_page_has_tabs_and_tab_switch_does_not_refetch(self):
        page = MONITOR_PAGE_PATH.read_text(encoding="utf-8")
        source = INDEX_JS_PATH.read_text(encoding="utf-8")

        self.assertIn('id="monitor-run-tabs"', page)
        self.assertIn('role="tablist"', page)
        self.assertIn("refreshMonitorRunDetail()", page)
        self.assertIn("function setMonitorRunTab(category)", source)
        self.assertIn("window.setMonitorRunTab = setMonitorRunTab", source)
        self.assertIn("async function loadMonitorRunDetail({ append = false, quiet = false } = {})", source)
        # 切页签只重渲染，不重新请求；加载更多才追加分页。
        tab_block = source[source.index("function setMonitorRunTab(category)"):source.index("async function openMonitorRun")]
        self.assertNotIn("MediaHubApi.getJson", tab_block)
        self.assertIn("window.MonitorRunView.tabsHtml(detail, activeMonitorRunCategory)", source)
        self.assertIn("window.MonitorRunView.detailHtml(detail, activeMonitorRunCategory)", source)
        self.assertNotIn("switchMonitorRunDetail", source)

    def test_tab_counts_come_from_run_counts(self):
        html = run_view(
            "window.MonitorRunView.tabsHtml({run: {id: 'c1', run_kind: 'change', source: 'change'}, "
            "counts: {remote: 4, strm: 0, problem: 2}}, '')"
        )

        self.assertIn("概览", html)
        self.assertIn("网盘变更", html)
        self.assertIn("本地文件", html)
        self.assertIn("问题", html)
        # 计数取整次运行的 counts，而不是已加载条数。
        self.assertIn('monitor-run-tab-count">4<', html)
        self.assertIn('monitor-run-tab-count">0<', html)
        self.assertIn('monitor-run-tab-count">2<', html)
        self.assertIn('data-monitor-run-tab="remote"', html)
        self.assertIn('aria-selected="true"', html)

    def test_result_keeps_at_most_three_metrics(self):
        html = run_view(
            "window.MonitorRunView.detailHtml({run: {id: 'r1', run_kind: 'inbox', task_name: '接收', status: 'partial', "
            "summary: '部分完成', result: {moved: 2, left: 1, generated: 8, deleted: 3, failed_dirs: 1}}, "
            "events: [], counts: {}, total: 0})"
        )

        self.assertIn("成功分发", html)
        self.assertIn("留在接收夹", html)
        self.assertIn("新增本地文件", html)
        self.assertNotIn("删除本地文件", html)
        self.assertNotIn("失败目录", html)
        # 未完成内容只用一句话补充；逐条问题在“问题”页签里看。
        self.assertIn("未完成内容：", html)
        self.assertNotIn("monitor-run-problem-link", html)


class MonitorPageHelpTest(unittest.TestCase):
    """监控页头部说明改走信息按钮 + 弹窗，正文不再堆长文案。"""

    def test_header_copy_moves_into_help_button(self):
        html = MONITOR_PAGE_PATH.read_text(encoding="utf-8")
        self.assertIn("文件夹监控任务列表", html)
        self.assertIn('onclick="showMonitorHelp()"', html)
        self.assertIn('title="文件夹监控说明"', html)
        self.assertIn("monitor-head-title", html)
        # 原正文文案不再直接铺在页面上
        self.assertNotIn("扫描 115 网盘目录，生成或刷新本地", html)
        self.assertNotIn("命中 savepath 时会优先局部刷新", html)

    def test_help_modal_holds_monitor_copy(self):
        script = INDEX_JS_PATH.read_text(encoding="utf-8")
        self.assertIn("const MONITOR_HELP_HTML", script)
        self.assertIn("function showMonitorHelp()", script)
        self.assertIn("showHelpHtml('文件夹监控说明', MONITOR_HELP_HTML)", script)
        self.assertIn("window.showMonitorHelp = showMonitorHelp;", script)
        # 说明本身保留在弹窗里：局部刷新 + 路径匹配 + 跳过条件
        self.assertIn("资源导入 / Webhook 命中 savepath 时会优先局部刷新", script)
        self.assertIn("savepath 必须落在某条任务的扫描路径内", script)
        self.assertIn("文件大小过滤", script)


if __name__ == "__main__":
    unittest.main()
