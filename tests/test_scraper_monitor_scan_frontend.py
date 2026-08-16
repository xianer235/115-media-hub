import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRAPER_CORE_PATH = ROOT / "static/js/modules/scraper/core.js"
SCRAPER_TEMPLATE_PATH = ROOT / "templates/partials/pages/scraper.html"


def run_scraper_core(expression: str, confirm_result: bool = True) -> dict:
    script = f"""
const fs = require('fs');
const vm = require('vm');
let source = fs.readFileSync({json.dumps(str(SCRAPER_CORE_PATH))}, 'utf8');
source = source.replace(/^export /m, '');
const calls = [];
const toasts = [];
const context = {{
  console,
  window: {{
    providerMeta: [],
    showAppConfirm: async () => {json.dumps(confirm_result)},
    showToast: (message, options) => toasts.push({{ message, options }}),
    MediaHubApi: {{
      getJson: async () => ({{}}),
      postJson: async (url, payload) => {{
        calls.push({{ url, payload }});
        return {{
          ok: true,
          tasks: [{{ task_name: '影视监控', status: 'queued', matched: 1 }}],
          unmatched: [],
        }};
      }},
    }},
  }},
  document: {{ getElementById: () => null, querySelector: () => null }},
  requestAnimationFrame: () => 0,
  setTimeout: () => 0,
  clearInterval: () => {{}},
  setInterval: () => 0,
}};
vm.createContext(context);
vm.runInContext(source, context, {{ filename: 'core.js' }});
Promise.resolve(vm.runInContext({json.dumps(expression)}, context))
  .then(result => process.stdout.write(JSON.stringify({{ result, calls, toasts }})))
  .catch(error => {{
    console.error(error);
    process.exit(1);
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


class ScraperMonitorScanFrontendTest(unittest.TestCase):
    def test_build_monitor_scan_scopes_maps_files_to_parent_and_dedupes(self):
        out = run_scraper_core(
            "(() => {"
            "state.provider = '115';"
            "return buildMonitorScanScopes(["
            "{ is_dir: true, path: '影视/电影', parent_path: '影视', name: '电影', id: '1' },"
            "{ is_dir: false, path: '影视/电影/A.mkv', parent_path: '影视/电影', name: 'A.mkv', id: '2' },"
            "{ is_dir: false, path: '影视/电影/B.mkv', parent_path: '影视/电影', name: 'B.mkv', id: '3' },"
            "{ is_dir: true, path: '影视/剧集', parent_path: '影视', name: '剧集', id: '4' }"
            "]);"
            "})()"
        )
        self.assertEqual(out["result"], ["影视/电影", "影视/剧集"])

    def test_scan_monitor_dir_posts_selected_scopes(self):
        out = run_scraper_core(
            "(async () => {"
            "state.provider = '115';"
            "state.selected.set('d1', { id: 'd1', name: '电影', is_dir: true, path: '影视/电影', parent_path: '影视' });"
            "state.selected.set('f1', { id: 'f1', name: 'A.mkv', is_dir: false, path: '影视/电影/A.mkv', parent_path: '影视/电影' });"
            "await scanMonitorDir();"
            "return true;"
            "})()"
        )
        self.assertEqual(out["result"], True)
        self.assertEqual(len(out["calls"]), 1)
        self.assertEqual(out["calls"][0]["url"], "/monitor/scan")
        self.assertEqual(out["calls"][0]["payload"]["provider"], "115")
        self.assertEqual(out["calls"][0]["payload"]["paths"], ["影视/电影"])
        self.assertTrue(any("已加入监控队列" in item["message"] for item in out["toasts"]))

    def test_scan_monitor_dir_requires_confirmation(self):
        out = run_scraper_core(
            "(async () => {"
            "state.provider = '115';"
            "state.selected.set('d1', { id: 'd1', name: '电影', is_dir: true, path: '影视/电影', parent_path: '影视' });"
            "await scanMonitorDir();"
            "return true;"
            "})()",
            confirm_result=False,
        )
        self.assertEqual(out["calls"], [])

    def test_scan_monitor_dir_rejects_over_cap_without_request(self):
        entries = ",".join(
            f"{{ id: 'd{i}', name: 'D{i}', is_dir: true, path: '影视/D{i}', parent_path: '影视' }}"
            for i in range(51)
        )
        out = run_scraper_core(
            "(async () => {"
            "state.provider = '115';"
            f"const entries = [{entries}];"
            "entries.forEach(item => state.selected.set(item.id, item));"
            "await scanMonitorDir();"
            "return true;"
            "})()"
        )
        self.assertEqual(out["calls"], [])
        self.assertTrue(any("50" in item["message"] for item in out["toasts"]))

    def test_template_contains_monitor_scan_button(self):
        template = SCRAPER_TEMPLATE_PATH.read_text(encoding="utf-8")
        self.assertIn('data-scraper-action="monitor-scan"', template)
        self.assertIn("扫描监控/刷新 STRM", template)

    def test_core_wires_monitor_scan_action(self):
        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")
        self.assertIn("if (action === 'monitor-scan') void scanMonitorDir();", source)
        self.assertIn("buildMonitorScanScopes(selectedEntries)", source)


if __name__ == "__main__":
    unittest.main()
