import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "static/js/modules/resource/job-state.js"
JOBS_PATH = ROOT / "static/js/modules/resource/jobs.js"
JOB_MODAL_PATH = ROOT / "static/js/modules/resource/job-modal.js"
RESOURCE_TAB_PATH = ROOT / "static/js/modules/tabs/resource.js"
SCRAPER_CORE_PATH = ROOT / "static/js/modules/scraper/core.js"
CSS_PATH = ROOT / "static/css/index.css"


def run_job_state(expression: str):
    if not MODULE_PATH.exists():
        raise AssertionError(f"任务列表状态控制器尚未创建: {MODULE_PATH}")
    script = f"""
const fs = require('fs');
const vm = require('vm');
const context = {{ window: {{}} }};
vm.createContext(context);
vm.runInContext(fs.readFileSync({json.dumps(str(MODULE_PATH))}, 'utf8'), context);
const result = vm.runInContext({json.dumps(expression)}, context);
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr.strip())
    return json.loads(completed.stdout)


def run_job_actions(expression: str):
    script = f"""
const fs = require('fs');
const vm = require('vm');
const calls = [];
const context = {{
  calls,
  window: {{
    MediaHubApi: {{
      postJson: async (url, payload) => {{ calls.push(['post', url, payload]); return {{ ok: true }}; }},
    }},
    showAppConfirm: async message => {{ calls.push(['confirm', message]); return true; }},
  }},
}};
vm.createContext(context);
vm.runInContext(fs.readFileSync({json.dumps(str(JOBS_PATH))}, 'utf8'), context);
Promise.resolve(vm.runInContext({json.dumps(expression)}, context))
  .then(result => process.stdout.write(JSON.stringify(result)))
  .catch(error => {{ process.stderr.write(String(error?.stack || error)); process.exitCode = 1; }});
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr.strip())
    return json.loads(completed.stdout)


def run_resource_tab_refresh(page: int):
    script = f"""
const fs = require('fs');
const calls = [];
global.window = {{
  MediaHubApi: {{
    getJson: async url => {{
      calls.push(url);
      return {{ jobs: [], pagination: {{ page: {page}, page_size: 10 }} }};
    }},
  }},
}};
(async () => {{
  const source = fs.readFileSync({json.dumps(str(RESOURCE_TAB_PATH))}, 'utf8');
  const moduleUrl = `data:text/javascript;base64,${{Buffer.from(source).toString('base64')}}`;
  const resourceTab = await import(moduleUrl);
  await resourceTab.refreshResourceState({{
    getResourceState: () => ({{ search_source: 'tg' }}),
    getResourceJobsStateRequest: () => ({{ status: 'all', page: {page}, page_size: 10 }}),
    isDirectImportInput: () => false,
    applyResourceState: () => null,
  }});
  process.stdout.write(JSON.stringify(calls));
}})().catch(error => {{
  process.stderr.write(String(error?.stack || error));
  process.exitCode = 1;
}});
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr.strip())
    return json.loads(completed.stdout)


class ResourceJobStateFrontendTest(unittest.TestCase):
    def test_delete_action_confirms_record_only_and_refreshes_current_window(self):
        result = run_job_actions(
            """window.ResourceJobActions.triggerDelete({
                refreshResourceState: async options => calls.push(['refresh', options]),
                showToast: (message, options) => calls.push(['toast', message, options?.tone]),
            }, 42).then(() => calls)"""
        )
        self.assertEqual(result[1], ["post", "/resource/jobs/delete", {"job_id": 42}])
        self.assertEqual(result[2], ["refresh", {"allowSearch": False, "jobMode": "window"}])
        self.assertIn("不会删除网盘文件", result[0][1])
        self.assertEqual(result[3][0:2], ["toast", "任务 #42 的记录已删除"])

    def test_page_change_requests_a_single_ten_item_page(self):
        result = run_job_state(
            """(() => {
                const controller = window.ResourceJobState.create();
                const first = controller.begin();
                controller.accept(first, { jobs: [], pagination: { total: 80, page: 1, total_pages: 8 } });
                const second = controller.begin({ page: 2 });
                return [first, second].map(request => [request.page, request.page_size]);
            })()"""
        )
        self.assertEqual(result, [[1, 10], [2, 10]])

    def test_stale_response_cannot_overwrite_newer_page(self):
        result = run_job_state(
            """(() => {
                const controller = window.ResourceJobState.create();
                const first = controller.begin();
                const second = controller.begin({ page: 2 });
                const fresh = controller.accept(second, {
                    jobs: [{ id: 40 }, { id: 39 }],
                    pagination: { total: 40, page: 2, total_pages: 4 },
                });
                const stale = controller.accept(first, {
                    jobs: [{ id: 20 }],
                    pagination: { total: 20, page: 1, total_pages: 2 },
                });
                return {
                    freshAccepted: fresh.accepted,
                    staleAccepted: stale.accepted,
                    ids: controller.snapshot().jobs.map(job => job.id),
                    page: controller.snapshot().page,
                };
            })()"""
        )
        self.assertEqual(
            result,
            {"freshAccepted": True, "staleAccepted": False, "ids": [40, 39], "page": 2},
        )

    def test_poll_started_around_page_change_cannot_overwrite_selected_page(self):
        result = run_job_state(
            """(() => {
                const controller = window.ResourceJobState.create();
                const initial = controller.begin({ page: 1 });
                controller.accept(initial, {
                    jobs: [{ id: 10 }],
                    pagination: { page: 1, page_size: 10, total: 20, total_pages: 2 },
                });
                const pageRequest = controller.begin({ page: 2 });
                const pollRequest = controller.begin({ mode: 'poll' });
                const poll = controller.accept(pollRequest, {
                    jobs: [{ id: 10 }],
                    pagination: { page: 1, page_size: 10, total: 20, total_pages: 2 },
                });
                const page = controller.accept(pageRequest, {
                    jobs: [{ id: 20 }],
                    pagination: { page: 2, page_size: 10, total: 20, total_pages: 2 },
                });
                return {
                    pollAccepted: poll.accepted,
                    pageAccepted: page.accepted,
                    ids: controller.snapshot().jobs.map(job => job.id),
                    currentPage: controller.snapshot().pagination.page,
                };
            })()"""
        )
        self.assertEqual(result, {
            "pollAccepted": False,
            "pageAccepted": True,
            "ids": [20],
            "currentPage": 2,
        })

    def test_polling_refreshes_the_current_page_without_merging_history(self):
        result = run_job_state(
            """(() => {
                const controller = window.ResourceJobState.create();
                const initial = controller.begin({ page: 2 });
                controller.accept(initial, {
                    jobs: Array.from({ length: 10 }, (_, index) => ({ id: 30 - index, status: 'completed' })),
                    active_jobs: [],
                    pagination: { total: 40, page: 2, total_pages: 4 },
                });
                const poll = controller.begin({ mode: 'poll' });
                const result = controller.accept(poll, {
                    jobs: Array.from({ length: 10 }, (_, index) => ({ id: 30 - index, status: index === 0 ? 'submitted' : 'completed' })),
                    active_jobs: [{ id: 30, status: 'submitted' }],
                    pagination: { total: 40, page: 2, total_pages: 4 },
                });
                const snapshot = controller.snapshot();
                return {
                    pollPage: poll.page,
                    count: snapshot.jobs.length,
                    count: snapshot.jobs.length,
                    includesCurrent: snapshot.jobs.some(job => job.id === 30),
                    includesPrevious: snapshot.jobs.some(job => job.id === 40),
                };
            })()"""
        )
        self.assertEqual(
            result,
            {"pollPage": 2, "count": 10, "includesCurrent": True, "includesPrevious": False},
        )

    def test_filter_change_resets_window_to_first_page(self):
        result = run_job_state(
            """(() => {
                const controller = window.ResourceJobState.create();
                const first = controller.begin({ page: 3 });
                controller.accept(first, { jobs: [], pagination: { total: 60, page: 3, total_pages: 6 } });
                const filtered = controller.begin({ status: 'failed', reset: true });
                return [filtered.status, filtered.page, filtered.page_size, controller.snapshot().filter];
            })()"""
        )
        self.assertEqual(result, ["failed", 1, 10, "failed"])

    def test_failed_request_keeps_existing_jobs_and_restores_loading_state(self):
        result = run_job_state(
            """(() => {
                const controller = window.ResourceJobState.create();
                const initial = controller.begin();
                controller.accept(initial, {
                    jobs: [{ id: 20 }, { id: 19 }],
                    pagination: { total: 20, has_more: false },
                });
                const request = controller.begin({ extend: true });
                const failure = controller.reject(request, new Error('网络不可用'));
                const snapshot = controller.snapshot();
                return {
                    accepted: failure.accepted,
                    ids: snapshot.jobs.map(job => job.id),
                    loading: snapshot.loading,
                    error: snapshot.error,
                };
            })()"""
        )
        self.assertEqual(
            result,
            {"accepted": True, "ids": [20, 19], "loading": False, "error": "网络不可用"},
        )

    def test_page_response_replaces_previous_page_and_keeps_ten_items(self):
        result = run_job_state(
            """(() => {
                const controller = window.ResourceJobState.create();
                const first = controller.begin({ page: 1 });
                controller.accept(first, {
                    jobs: Array.from({ length: 10 }, (_, index) => ({ id: 10 - index })),
                    pagination: { page: 1, page_size: 10, total: 20, total_pages: 2 },
                });
                const second = controller.begin({ page: 2 });
                controller.accept(second, {
                    jobs: Array.from({ length: 10 }, (_, index) => ({ id: 20 - index })),
                    pagination: { page: 2, page_size: 10, total: 20, total_pages: 2 },
                });
                const snapshot = controller.snapshot();
                return {
                    count: snapshot.jobs.length,
                    ids: snapshot.jobs.map(job => job.id),
                    hasPreviousPageItem: snapshot.jobs.some(job => job.id === 10),
                    page: snapshot.pagination.page,
                };
            })()"""
        )
        self.assertEqual(result, {
            "count": 10,
            "ids": list(range(20, 10, -1)),
            "hasPreviousPageItem": False,
            "page": 2,
        })

    def test_task_pagination_uses_vertical_center_alignment_without_empty_row_spacing(self):
        source = JOB_MODAL_PATH.read_text(encoding="utf-8")
        self.assertIn("resource-job-pagination-label", source)
        self.assertNotIn('<span class="scraper-empty-row">第 ${escapeHtml(String(page))}', source)

    def test_nav_job_badge_does_not_overhang_above_button(self):
        css = CSS_PATH.read_text(encoding="utf-8")
        self.assertIn(".nav-task-center-btn .resource-job-trigger-badge", css)
        self.assertIn("transform: translateY(-50%);", css)
        self.assertNotIn("top: -0.28rem;", css)

    def test_resource_state_refresh_uses_the_current_page_contract(self):
        source = (ROOT / "static/js/modules/resource/core.js").read_text(encoding="utf-8")
        self.assertIn("params.set('job_page', String(jobRequest.page));", source)
        self.assertIn("params.set('job_page_size', String(jobRequest.page_size));", source)
        self.assertNotIn("params.set('job_offset', String(jobRequest.offset));", source)

    def test_resource_tab_refresh_keeps_the_selected_job_page(self):
        calls = run_resource_tab_refresh(3)
        self.assertEqual(len(calls), 1)
        self.assertIn("job_page=3", calls[0])
        self.assertIn("job_page_size=10", calls[0])
        self.assertNotIn("job_offset=", calls[0])
        self.assertNotIn("job_limit=", calls[0])

    def test_task_pagination_renders_page_buttons(self):
        source = JOB_MODAL_PATH.read_text(encoding="utf-8")
        self.assertIn('data-${action}="page-number"', source)
        self.assertIn("action: 'resource-job-action'", source)
        self.assertIn("action: 'scraper-job-action'", source)

    def test_task_pagination_has_separate_desktop_and_mobile_page_windows(self):
        modal_source = JOB_MODAL_PATH.read_text(encoding="utf-8")
        scraper_source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")
        for source in (modal_source, scraper_source):
            self.assertIn("resource-job-pagination-controls", source)
            self.assertIn("resource-job-pagination-pages-desktop", source)
            self.assertIn("resource-job-pagination-pages-mobile", source)
        self.assertIn("renderTaskPageButtons({ page: pageNumber, totalPages, maxVisible: 5", modal_source)
        self.assertIn("renderTaskPageButtons({ page: pageNumber, totalPages, maxVisible: 3", modal_source)
        self.assertIn("renderJobPageButtons(page, totalPages, 5)", scraper_source)
        self.assertIn("renderJobPageButtons(page, totalPages, 3)", scraper_source)

    def test_mobile_pagination_keeps_navigation_on_one_row(self):
        source = CSS_PATH.read_text(encoding="utf-8")
        self.assertIn(".resource-job-pagination-controls", source)
        self.assertIn(".resource-job-pagination-pages-mobile", source)
        self.assertRegex(
            source,
            r"@media\s*\(max-width:\s*640px\)[^{}]*\{[\s\S]*?\.resource-browser-load-more-row\s*\{[\s\S]*?flex-direction:\s*column;",
        )
        self.assertRegex(
            source,
            r"@media\s*\(max-width:\s*640px\)[^{}]*\{[\s\S]*?\.resource-job-pagination-controls\s*\{[\s\S]*?flex-wrap:\s*nowrap;",
        )

    def test_pagination_footer_does_not_shrink_inside_scroll_list(self):
        source = CSS_PATH.read_text(encoding="utf-8")
        self.assertRegex(
            source,
            r"\.resource-browser-load-more-row\s*\{[^}]*flex:\s*0\s+0\s+auto;",
        )
        self.assertNotRegex(
            source,
            r"\.resource-browser-load-more-row\s*\{[^}]*flex-shrink:\s*1;",
        )

    def test_task_page_buttons_use_neutral_inactive_and_solid_active_colors_in_both_themes(self):
        source = CSS_PATH.read_text(encoding="utf-8")
        self.assertRegex(
            source,
            r"\.resource-job-page-button-active\s*\{[^}]*background:\s*#0369a1;[^}]*color:\s*#ffffff;",
        )
        self.assertRegex(
            source,
            r"html\.theme-day \.resource-job-page-button\s*\{[^}]*background:\s*#ffffff;[^}]*color:\s*#334155;",
        )
        self.assertRegex(
            source,
            r"html\.theme-day \.resource-job-page-button-active\s*\{[^}]*background:\s*#0369a1;[^}]*color:\s*#ffffff;",
        )


if __name__ == "__main__":
    unittest.main()
