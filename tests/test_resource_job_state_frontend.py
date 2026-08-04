import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "static/js/modules/resource/job-state.js"
JOBS_PATH = ROOT / "static/js/modules/resource/jobs.js"


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

    def test_load_more_requests_cumulative_windows_from_offset_zero(self):
        result = run_job_state(
            """(() => {
                const controller = window.ResourceJobState.create();
                const first = controller.begin();
                controller.accept(first, { jobs: [], pagination: { total: 80, has_more: true } });
                const second = controller.begin({ extend: true });
                controller.accept(second, { jobs: [], pagination: { total: 80, has_more: true } });
                const third = controller.begin({ extend: true });
                return [first, second, third].map(request => [request.offset, request.limit]);
            })()"""
        )
        self.assertEqual(result, [[0, 20], [0, 40], [0, 60]])

    def test_stale_response_cannot_overwrite_newer_cumulative_window(self):
        result = run_job_state(
            """(() => {
                const controller = window.ResourceJobState.create();
                const first = controller.begin();
                const second = controller.begin({ extend: true });
                const fresh = controller.accept(second, {
                    jobs: [{ id: 40 }, { id: 39 }],
                    pagination: { total: 40, has_more: false },
                });
                const stale = controller.accept(first, {
                    jobs: [{ id: 20 }],
                    pagination: { total: 20, has_more: false },
                });
                return {
                    freshAccepted: fresh.accepted,
                    staleAccepted: stale.accepted,
                    ids: controller.snapshot().jobs.map(job => job.id),
                    limit: controller.snapshot().windowSize,
                };
            })()"""
        )
        self.assertEqual(
            result,
            {"freshAccepted": True, "staleAccepted": False, "ids": [40, 39], "limit": 40},
        )

    def test_polling_merges_latest_jobs_and_active_jobs_without_shrinking_history(self):
        result = run_job_state(
            """(() => {
                const controller = window.ResourceJobState.create();
                const initial = controller.begin({ extend: true });
                controller.accept(initial, {
                    jobs: Array.from({ length: 40 }, (_, index) => ({ id: 40 - index, status: 'completed' })),
                    active_jobs: [],
                    pagination: { total: 40, has_more: false },
                });
                const poll = controller.begin({ mode: 'poll' });
                const result = controller.accept(poll, {
                    jobs: Array.from({ length: 20 }, (_, index) => ({ id: 41 - index, status: index === 0 ? 'submitted' : 'completed' })),
                    active_jobs: [{ id: 41, status: 'submitted' }],
                    pagination: { total: 41, has_more: true },
                });
                const snapshot = controller.snapshot();
                return {
                    pollLimit: poll.limit,
                    count: snapshot.jobs.length,
                    includesOldest: snapshot.jobs.some(job => job.id === 1),
                    includesActive: snapshot.jobs.some(job => job.id === 41),
                    needsCalibration: result.needsCalibration,
                };
            })()"""
        )
        self.assertEqual(
            result,
            {"pollLimit": 20, "count": 41, "includesOldest": True, "includesActive": True, "needsCalibration": True},
        )

    def test_filter_change_resets_window_to_first_page(self):
        result = run_job_state(
            """(() => {
                const controller = window.ResourceJobState.create();
                const first = controller.begin({ extend: true });
                controller.accept(first, { jobs: [], pagination: { total: 60, has_more: true } });
                const filtered = controller.begin({ status: 'failed', reset: true });
                return [filtered.status, filtered.offset, filtered.limit, controller.snapshot().filter];
            })()"""
        )
        self.assertEqual(result, ["failed", 0, 20, "failed"])

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


if __name__ == "__main__":
    unittest.main()
