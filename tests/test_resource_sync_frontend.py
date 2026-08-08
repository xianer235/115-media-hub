import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "static/js/index.js"
CORE_PATH = ROOT / "static/js/modules/resource/core.js"


def run_index(expression: str, search_input: str = ""):
    script = f"""
const fs = require('fs');
const vm = require('vm');
const context = {{
  console,
  window: {{}},
  document: {{
    hidden: false,
    getElementById: id => id === 'resource-search-input' ? {{ value: {json.dumps(search_input)} }} : null,
  }},
}};
vm.createContext(context);
vm.runInContext(fs.readFileSync({json.dumps(str(INDEX_PATH))}, 'utf8'), context);
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


class ResourceSyncFrontendTest(unittest.TestCase):
    def test_empty_search_refreshes_after_active_sync_finishes(self):
        result = run_index(
            """(() => {
                const calls = [];
                currentTab = 'resource';
                resourceState = { ...resourceState, search: '' };
                scheduleResourcePolling = () => {};
                setResourceTgHealthResult = () => {};
                applyResourceTgHealthFromSyncResult = () => {};
                refreshResourceState = options => calls.push(options);
                handleResourceChannelSyncStateChange(
                    { running: true },
                    { running: false, finished_at: '2026-08-09 10:00:00', last_result: {} },
                );
                return calls;
            })()"""
        )
        self.assertEqual(result, [{"allowSearch": False}])

    def test_search_results_are_preserved_after_active_sync_finishes(self):
        result = run_index(
            """(() => {
                const calls = [];
                currentTab = 'resource';
                resourceState = { ...resourceState, search: '' };
                scheduleResourcePolling = () => {};
                setResourceTgHealthResult = () => {};
                applyResourceTgHealthFromSyncResult = () => {};
                refreshResourceState = options => calls.push(options);
                handleResourceChannelSyncStateChange(
                    { running: true },
                    { running: false, finished_at: '2026-08-09 10:00:01', last_result: {} },
                );
                return calls;
            })()""",
            search_input="海边的曼彻斯特",
        )
        self.assertEqual(result, [])

    def test_resource_state_only_refreshes_after_compact_sync_completion(self):
        source = CORE_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "handleResourceChannelSyncStateChange(previousChannelSync, resourceState.channel_sync, { refreshOnComplete: compactUpdate });",
            source,
        )


if __name__ == "__main__":
    unittest.main()
