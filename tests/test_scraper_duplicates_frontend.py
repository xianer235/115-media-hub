"""查重前端：入口只扫「勾中的那一处」，面板渲染走主题无关的类名。

两个断言点都是行为性回归，不检查源码字符串：
1. ``open({cid})`` 必须把勾选的文件夹 id 发给扫描接口，不传时退回当前目录；
2. 面板 meta 要带上服务端返回的实际扫描路径（用户得知道扫的是哪一层）。
"""

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DUPLICATES_JS = ROOT / "static/js/modules/scraper/duplicates.js"
SCRAPER_TEMPLATE = ROOT / "templates/partials/pages/scraper.html"

FAKE_RESULT = {
    "ok": True,
    "provider": "115",
    "root_path": "影视库/电视剧/某剧 (2024)",
    "groups": [
        {
            "group_id": "tv|某剧 (2024)|1|1",
            "kind": "tv",
            "tier": "exact",
            "label": "某剧 (2024) · S01E01",
            "reclaimable_bytes": 900,
            "files": [
                {
                    "id": "1",
                    "name": "某剧 - S01E01.1080p.mkv",
                    "path": "p/1.mkv",
                    "size": 900,
                    "resolution": "1080p",
                    "sha1_short": "ABCDEF12",
                    "recommended_keep": True,
                    "parent_id": "101",
                },
                {
                    "id": "2",
                    "name": "某剧 - S01E01 副本.mkv",
                    "path": "p/2.mkv",
                    "size": 900,
                    "resolution": "1080p",
                    "sha1_short": "ABCDEF12",
                    "recommended_keep": False,
                    "parent_id": "101",
                },
            ],
        }
    ],
    "series_hints": [],
    "scanned": {"dirs": 2, "entries": 4, "media_files": 2, "failed_dirs": 0, "truncated": False},
    "summary": {"group_count": 1, "exact_groups": 1, "episode_groups": 0, "duplicate_files": 2, "reclaimable_bytes": 900},
}


def run_duplicates_js(expression: str) -> dict:
    """在 node 里用桩 DOM 跑 duplicates.js，返回 expression 的结果与请求记录。"""
    script = f"""
const fs = require('fs');
const vm = require('vm');
let source = fs.readFileSync({json.dumps(str(DUPLICATES_JS))}, 'utf8');
source = source.replace('export function', 'function');
const nodes = {{}};
function node(id) {{
  if (!nodes[id]) {{
    nodes[id] = {{
      id, textContent: '', innerHTML: '', disabled: false, title: '', checked: false,
      classList: {{ add() {{}}, remove() {{}}, contains() {{ return false; }} }},
      removeAttribute() {{}}, setAttribute() {{}},
    }};
  }}
  return nodes[id];
}}
const calls = [];
const context = {{
  console,
  document: {{ getElementById: node }},
  window: {{
    MediaHubApi: {{
      postJson: async (url, payload) => {{
        calls.push({{ url, payload }});
        return {json.dumps(FAKE_RESULT)};
      }},
    }},
  }},
}};
vm.createContext(context);
vm.runInContext(source, context, {{ filename: 'duplicates.js' }});
const controller = vm.runInContext('createDuplicatesController', context)({{
  getProvider: () => '115',
  getCid: () => '900',
  showToast: () => {{}},
  showConfirm: async () => false,
  formatFileSize: (value) => `${{value}} B`,
  escapeHtml: (value) => String(value ?? ''),
  buildMutationRequestId: () => 'rid-1',
}});
Promise.resolve((async () => {{
  const result = await ({expression});
  return {{ result, meta: node('scraper-duplicates-meta').textContent }};
}})())
  .then(out => process.stdout.write(JSON.stringify({{ out, calls }})))
  .catch(error => {{ console.error(error); process.exit(1); }});
"""
    completed = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True)
    if completed.returncode != 0:
        raise AssertionError(completed.stderr.strip())
    return json.loads(completed.stdout)


class DuplicateScanTargetTest(unittest.TestCase):
    def test_open_with_folder_cid_scans_that_folder(self):
        data = run_duplicates_js("controller.open({ cid: '777' })")
        self.assertEqual(len(data["calls"]), 1)
        self.assertEqual(data["calls"][0]["url"], "/scraper/duplicates/scan")
        self.assertEqual(data["calls"][0]["payload"]["cid"], "777")
        self.assertEqual(data["calls"][0]["payload"]["provider"], "115")

    def test_open_without_cid_falls_back_to_current_folder(self):
        data = run_duplicates_js("controller.open()")
        self.assertEqual(data["calls"][0]["payload"]["cid"], "900")

    def test_meta_shows_scanned_path_from_server(self):
        data = run_duplicates_js("controller.open({ cid: '777' })")
        self.assertIn("影视库/电视剧/某剧 (2024)", data["out"]["meta"])


class DuplicatesEntryPointTest(unittest.TestCase):
    def setUp(self):
        self.template = SCRAPER_TEMPLATE.read_text(encoding="utf-8")

    def test_entry_button_sits_in_selection_actions(self):
        selection_bar = self.template.index('class="scraper-selection-actions"')
        button_index = self.template.index('data-scraper-action="open-duplicates"')
        self.assertGreater(button_index, selection_bar)

    def test_entry_button_disabled_by_default(self):
        start = self.template.index('data-scraper-action="open-duplicates"')
        tag_start = self.template.rindex("<", 0, start)
        tag_end = self.template.index(">", start)
        self.assertIn("disabled", self.template[tag_start:tag_end])

    def test_toolbar_has_no_duplicates_button(self):
        toolbar = self.template[: self.template.index('id="scraper-breadcrumbs"')]
        self.assertNotIn("open-duplicates", toolbar)


CORE_JS = ROOT / "static/js/modules/scraper/core.js"


def run_core_js(expression: str) -> dict:
    """在 node 里跑 core.js（桩 DOM），返回 expression 结果与 toast 记录。"""
    script = f"""
const fs = require('fs');
const vm = require('vm');
let source = fs.readFileSync({json.dumps(str(CORE_JS))}, 'utf8');
source = source.replace(/^export /m, '');
const toasts = [];
const context = {{
  console,
  window: {{
    providerMeta: [],
    showAppConfirm: async () => false,
    showToast: (message, options) => toasts.push({{ message, options }}),
    MediaHubApi: {{ getJson: async () => ({{}}), postJson: async () => ({{}}) }},
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
  .catch(error => {{ console.error(error); process.exit(1); }});
"""
    completed = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True)
    if completed.returncode != 0:
        raise AssertionError(completed.stderr.strip())
    return json.loads(completed.stdout)


class DuplicatesSelectionGuardTest(unittest.TestCase):
    """没勾选 / 勾多个时必须拦下来，否则手滑一下就把整库扫了。"""

    def test_rejects_without_selection(self):
        data = run_core_js("openDuplicatesForSelection()")
        self.assertEqual(len(data["toasts"]), 1)
        self.assertIn("请先勾选", data["toasts"][0]["message"])

    def test_rejects_multiple_selection(self):
        expression = """
            state.cid = '900';
            state.selected.set('1', { id: '1', name: '某剧 A', is_dir: true, parent_path: '' });
            state.selected.set('2', { id: '2', name: '某剧 B', is_dir: true, parent_path: '' });
            openDuplicatesForSelection()
        """
        data = run_core_js(expression)
        self.assertEqual(len(data["toasts"]), 1)
        self.assertIn("只能对一个", data["toasts"][0]["message"])


if __name__ == "__main__":
    unittest.main()
