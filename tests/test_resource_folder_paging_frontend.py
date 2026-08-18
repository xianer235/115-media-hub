import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FOLDER_API_PATH = ROOT / "static/js/modules/resource/folder-api.js"


def run_folder_api(expression: str, page_entries) -> dict:
    pages = [
        {
            "ok": True,
            "entries": page_entries[0],
            "summary": {"folder_count": len(page_entries[0]), "file_count": 0},
            "entries_complete": False,
            "count": 600,
            "next_offset": 300,
            "has_more": True,
        },
        {
            "ok": True,
            "entries": page_entries[1],
            "summary": {"folder_count": len(page_entries[1]), "file_count": 0},
            "entries_complete": False,
            "count": 600,
            "next_offset": 600,
            "has_more": False,
        },
    ]
    requested_urls = []
    script = f"""
const fs = require('fs');
const vm = require('vm');
let source = fs.readFileSync({json.dumps(str(FOLDER_API_PATH))}, 'utf8');
const requested = [];
const pages = {json.dumps(pages)};
const context = {{
  console,
  RESOURCE_FOLDER_BRANCH_CACHE_TTL_MS: 300000,
  RESOURCE_FOLDER_PAGE_LIMIT: 300,
  resourceFolderBranchCache: {{}},
  resourceFolderFetchInFlight: {{}},
  URLSearchParams,
  URL,
  getResourceFolderApiPrefix: (provider) => '/resource/browse/' + String(provider || '115').toLowerCase(),
  window: {{
    MediaHubApi: {{
      requestJson: async (url) => {{
        requested.push(url);
        return pages[requested.length - 1];
      }},
    }},
  }},
  document: {{ getElementById: () => null }},
  pages,
}};
vm.createContext(context);
vm.runInContext(source, context, {{ filename: 'folder-api.js' }});
Promise.resolve(vm.runInContext({json.dumps(expression)}, context))
  .then(result => process.stdout.write(JSON.stringify({{ result, requested }})))
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


class ResourceFolderPagingFrontendTest(unittest.TestCase):
    def test_fetch_folder_data_pages_with_offset_and_limit(self):
        first_page = [{"id": f"c{i}", "name": f"文件夹{i}", "is_dir": True} for i in range(300)]
        second_page = [{"id": f"c{i}", "name": f"文件夹{i}", "is_dir": True} for i in range(300, 600)]
        out = run_folder_api(
            "(async () => {"
            "const first = await fetchResourceFolderData('0', { provider: '115', foldersOnly: true, offset: 0, limit: 300 });"
            "const second = await fetchResourceFolderData('0', { provider: '115', foldersOnly: true, offset: first.next_offset, limit: 300 });"
            "return { firstCount: first.entries.length, firstNext: first.next_offset, firstHasMore: first.has_more, secondCount: second.entries.length, secondNext: second.next_offset, secondHasMore: second.has_more };"
            "})()",
            [first_page, second_page],
        )
        result = out["result"]
        self.assertEqual(result["firstCount"], 300)
        self.assertEqual(result["firstNext"], 300)
        self.assertTrue(result["firstHasMore"])
        self.assertEqual(result["secondCount"], 300)
        self.assertEqual(result["secondNext"], 600)
        self.assertFalse(result["secondHasMore"])
        self.assertTrue(any("offset=300" in url for url in out["requested"]))
        self.assertTrue(all("limit=300" in url for url in out["requested"]))

    def test_load_more_markup_wired_in_consumers(self):
        browser_source = (ROOT / "static/js/modules/resource/browser.js").read_text(encoding="utf-8")
        import_source = (ROOT / "static/js/modules/resource/import-modal.js").read_text(encoding="utf-8")
        subscription_source = (ROOT / "static/js/modules/subscription/folders.js").read_text(encoding="utf-8")
        index_source = (ROOT / "static/js/index.js").read_text(encoding="utf-8")
        self.assertIn('data-resource-folder-action="load-more-folders"', browser_source)
        self.assertIn("loadMoreResourceFolders", import_source)
        self.assertIn('data-subscription-folder-action="load-more"', subscription_source)
        self.assertIn("loadMoreSubscriptionFolders", subscription_source)
        self.assertIn('data-monitor-folder-action="load-more"', index_source)
        self.assertIn("loadMoreMonitorFolders", index_source)


if __name__ == "__main__":
    unittest.main()
