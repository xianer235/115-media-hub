import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRAPER_CORE_PATH = ROOT / "static/js/modules/scraper/core.js"


def run_scraper_entries(expression: str, get_json_payload: dict) -> dict:
    script = f"""
const fs = require('fs');
const vm = require('vm');
let source = fs.readFileSync({json.dumps(str(SCRAPER_CORE_PATH))}, 'utf8');
source = source.replace(/^export /m, '');
const toasts = [];
const context = {{
  console,
  URLSearchParams,
  URL,
  window: {{
    providerMeta: [],
    showToast: (message) => toasts.push(message),
    MediaHubApi: {{
      getJson: async () => ({json.dumps(get_json_payload)}),
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
  .then(result => process.stdout.write(JSON.stringify({{ result, toasts }})))
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


def run_scraper_identify(expression: str) -> dict:
    script = f"""
const fs = require('fs');
const vm = require('vm');
let source = fs.readFileSync({json.dumps(str(SCRAPER_CORE_PATH))}, 'utf8');
source = source.replace(/^export /m, '');
const context = {{
  console,
  URLSearchParams,
  URL,
  window: {{
    providerMeta: [],
    showToast: () => {{}},
    MediaHubApi: {{
      getJson: async () => ({{}}),
      postJson: async () => ({{ results: [] }}),
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
  .then(result => process.stdout.write(JSON.stringify({{ result }})))
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


class ScraperEntriesPagingFrontendTest(unittest.TestCase):
    def test_load_entries_first_page_sets_paging_metadata(self):
        out = run_scraper_entries(
            "(async () => {"
            "state.provider = '115';"
            "state.cid = 'c1';"
            "await loadEntries();"
            "return { count: state.entries.length, nextOffset: state.nextOffset, hasMore: state.hasMore, first: state.entries[0]?.name, entryError: state.entryError };"
            "})()",
            {
                "entries": [{"id": "f1", "name": "a.txt", "is_dir": False}],
                "summary": {"folder_count": 0, "file_count": 1},
                "count": 2,
                "next_offset": 1,
                "has_more": True,
            },
        )
        self.assertEqual(out["result"]["count"], 1)
        self.assertEqual(out["result"]["nextOffset"], 1)
        self.assertTrue(out["result"]["hasMore"])

    def test_load_entries_more_appends_and_uses_next_offset(self):
        out = run_scraper_entries(
            "(async () => {"
            "state.provider = '115';"
            "state.cid = 'c1';"
            "state.entries = [{ id: 'f1', name: 'a.txt', is_dir: false }];"
            "state.nextOffset = 1;"
            "state.hasMore = true;"
            "await loadEntries({ more: true });"
            "return { count: state.entries.length, names: state.entries.map(e => e.name), nextOffset: state.nextOffset, hasMore: state.hasMore, entryError: state.entryError };"
            "})()",
            {
                "entries": [{"id": "f2", "name": "b.txt", "is_dir": False}],
                "summary": {"folder_count": 0, "file_count": 2},
                "count": 2,
                "next_offset": 2,
                "has_more": False,
            },
        )
        self.assertEqual(out["result"]["count"], 2)
        self.assertEqual(out["result"]["names"], ["a.txt", "b.txt"])
        self.assertEqual(out["result"]["nextOffset"], 2)
        self.assertFalse(out["result"]["hasMore"])

    def test_search_action_triggers_server_reload_with_keyword(self):
        source = (ROOT / "static/js/modules/scraper/core.js").read_text(encoding="utf-8")
        self.assertIn("params.set('q', state.search)", source)
        self.assertIn("void loadEntries();", source)
        self.assertIn("data-scraper-action=\"load-more-entries\"", source)
        self.assertIn("params.set('limit', String(SCRAPER_ENTRY_PAGE_LIMIT))", source)

    def test_auto_identify_no_match_keeps_manual_search_and_binding(self):
        out = run_scraper_identify(
            "(async () => {"
            "state.provider = '115';"
            "state.batchScan = { items: [{ item_index: 1, name: 'X', entry: { id: 'f1' }, files: [] }] };"
            "state.batchSearchState = { '1': { open: true, query: '正在输入' } };"
            "state.batchBindings = { '1': { id: 99 } };"
            "state.batchIncluded = new Set([1]);"
            "await identifyBatch();"
            "return { query: state.batchSearchState['1']?.query, bindings: Object.keys(state.batchBindings), included: Array.from(state.batchIncluded) };"
            "})()"
        )
        self.assertEqual(out["result"]["query"], "正在输入")
        self.assertEqual(out["result"]["bindings"], ["1"])
        self.assertEqual(out["result"]["included"], [1])


if __name__ == "__main__":
    unittest.main()
