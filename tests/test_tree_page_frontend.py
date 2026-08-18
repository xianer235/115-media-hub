import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TASK_TEMPLATE_PATH = ROOT / "templates/partials/pages/task.html"
SETTINGS_TEMPLATE_PATH = ROOT / "templates/partials/pages/settings.html"
BOOT_JS_PATH = ROOT / "static/js/modules/app/boot.js"
TASK_JS_PATH = ROOT / "static/js/modules/tabs/task.js"
INDEX_CSS_PATH = ROOT / "static/css/index.css"


class TreePageTemplateTest(unittest.TestCase):
    def test_settings_page_no_longer_contains_tree_config(self):
        html = SETTINGS_TEMPLATE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("settings-tree-sources", html)
        self.assertNotIn("settings-tree-sync", html)
        self.assertNotIn("trees-container", html)
        self.assertNotIn("cron_hour", html)

    def test_task_page_contains_new_tree_ui(self):
        html = TASK_TEMPLATE_PATH.read_text(encoding="utf-8")
        for marker in (
            "tree-tasks-container",
            "tree_sha1_skip",
            "tree_sync_clean",
            "tree-task-add-btn",
            "tree-task-modal",
            "tree-task-save-btn",
            "tree-sync-all-btn",
            "openStrmCleanupTool()",
            "tree-strm-cleanup",
            "prog-step",
            "log-box",
            "对比 sha1",
        ):
            self.assertIn(marker, html)
        self.assertNotIn("next-run-container", html)
        self.assertNotIn("tree-folder-picker", html)
        self.assertNotIn("tree-jobs-container", html)

    def test_day_theme_covers_task_page_white_text(self):
        css = INDEX_CSS_PATH.read_text(encoding="utf-8")
        self.assertIn("html.theme-day #page-task .text-white:not(button):not(a)", css)

    def test_sync_all_button_uses_theme_aware_colors(self):
        html = TASK_TEMPLATE_PATH.read_text(encoding="utf-8")
        line = next((line for line in html.splitlines() if 'id="tree-sync-all-btn"' in line), "")
        self.assertIn("bg-slate-800", line)
        self.assertIn("text-slate-300", line)
        self.assertIn("hover:bg-slate-700", line)
        self.assertNotIn(" bg-slate-700 ", line)

    def test_sync_all_button_renamed_to_download_and_generate(self):
        html = TASK_TEMPLATE_PATH.read_text(encoding="utf-8")
        line = next((line for line in html.splitlines() if 'id="tree-sync-all-btn"' in line), "")
        self.assertIn(">下载并生成</button>", line)
        self.assertNotIn(">全部同步</button>", line)
        js = TASK_JS_PATH.read_text(encoding="utf-8")
        self.assertIn("'下载并生成已触发'", js)
        self.assertNotIn("'全部同步已触发'", js)

    def test_strm_cleanup_is_separate_group(self):
        html = TASK_TEMPLATE_PATH.read_text(encoding="utf-8")
        self.assertIn('id="tree-strm-cleanup"', html)
        self.assertLess(
            html.index('id="tree-strm-cleanup"'),
            html.index('onclick="openStrmCleanupTool()"'),
        )
        strategy = html[html.index('id="tree-sync-strategy"') : html.index('id="tree-strm-cleanup"')]
        self.assertNotIn("openStrmCleanupTool", strategy)

    def test_task_card_no_longer_repeats_flow_hint(self):
        source = TASK_JS_PATH.read_text(encoding="utf-8")
        self.assertNotIn("点击“生成并同步”：", source)

    def test_tree_task_card_stacks_info_and_actions_on_mobile(self):
        source = TASK_JS_PATH.read_text(encoding="utf-8")
        self.assertIn(
            '<div class="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-3">',
            source,
        )
        # 旧布局在手机端会把信息区压缩成窄条，导致卡片被顶得很高。
        self.assertNotIn(
            '<div class="flex flex-wrap items-start justify-between gap-3">',
            source,
        )

    def test_tree_task_actions_are_icon_buttons_with_tooltips(self):
        source = TASK_JS_PATH.read_text(encoding="utf-8")
        self.assertIn('class="tree-task-action-btn tree-task-icon-btn tree-task-action-btn-${item.tone}"', source)
        self.assertIn('title="${item.label}"', source)
        self.assertIn('aria-label="${item.label}"', source)
        for action, label in (
            ("run", "生成并同步"),
            ("full", "全量重写"),
            ("edit", "编辑"),
            ("delete", "删除"),
        ):
            self.assertIn(f"{{ action: '{action}', label: '{label}'", source)
        self.assertIn("function buildTreeTaskActionIcon", source)
        self.assertEqual(source.count('viewBox="0 0 24 24"'), 4)
        # 旧的纯文字按钮结构不再存在。
        self.assertNotIn('>生成并同步</button>', source)
        self.assertNotIn('>全量重写</button>', source)

    def test_tree_task_icon_buttons_have_fixed_size_css(self):
        css = INDEX_CSS_PATH.read_text(encoding="utf-8")
        self.assertIn(".tree-task-icon-btn {", css)
        self.assertIn("width: 38px;", css)
        self.assertIn("height: 38px;", css)
        self.assertIn(".tree-task-icon-btn svg {", css)
        self.assertIn("width: 18px;", css)
        self.assertIn(".tree-task-icon-btn:focus-visible {", css)

    def test_tree_action_buttons_use_theme_safe_classes(self):
        source = TASK_JS_PATH.read_text(encoding="utf-8")
        self.assertIn("{ action: 'edit', label: '编辑', tone: 'edit' }", source)
        self.assertIn("{ action: 'delete', label: '删除', tone: 'delete' }", source)
        self.assertIn("tree-task-action-btn-${item.tone}", source)
        self.assertNotIn("bg-slate-800 hover:bg-slate-700 text-slate-300", source)

    def test_tree_action_buttons_have_visible_css_body(self):
        css = INDEX_CSS_PATH.read_text(encoding="utf-8")
        self.assertIn(".tree-task-action-btn {", css)
        self.assertIn("background: rgba(30, 41, 59, 0.74);", css)
        self.assertIn("border: 1px solid rgba(71, 85, 105, 0.82);", css)
        self.assertIn("background: rgba(5, 150, 105, 0.22);", css)
        self.assertIn("background: rgba(220, 38, 38, 0.16);", css)
        self.assertIn("html.theme-day .tree-task-action-btn-run {\n            background: #059669;", css)
        self.assertIn("html.theme-day .tree-task-action-btn-full {\n            background: #b91c1c;", css)
        self.assertIn("html.theme-day .tree-task-action-btn-edit {\n            background: #475569;", css)
        self.assertIn("html.theme-day .tree-task-action-btn-delete {\n            background: #fee2e2;", css)

    def test_task_modal_stays_below_folder_picker(self):
        html = TASK_TEMPLATE_PATH.read_text(encoding="utf-8")
        self.assertIn('id="tree-task-modal" class="hidden fixed inset-0 bg-black/60 z-50 p-4"', html)

    def test_boot_no_longer_populates_legacy_tree_rows(self):
        source = BOOT_JS_PATH.read_text(encoding="utf-8")
        self.assertNotIn("trees-container", source)


class TreeTaskJsWiringTest(unittest.TestCase):
    def _run_js(self, expression):
        dom_stub = r"""
const elements = {};
const makeEl = () => ({
  value: '',
  checked: false,
  innerText: '',
  innerHTML: '',
  dataset: {},
  style: {},
  scrollTop: 0,
  scrollHeight: 0,
  classList: { add() {}, remove() {}, toggle() {} },
  addEventListener() {},
  appendChild() {},
});
"""
        script = f"""
const fs = require('fs');
const vm = require('vm');
let source = fs.readFileSync({json.dumps(str(TASK_JS_PATH))}, 'utf8');
source = source.replace(/^export /gm, '');
const calls = [];
const toasts = [];
{dom_stub}
const context = {{
  console,
  window: {{
    MediaHubApi: {{
      getJson: async (url) => {{
        if (url === '/tree/tasks') return {{ tasks: [] }};
        if (url === '/tree/jobs') return {{ jobs: [] }};
        if (url === '/get_settings') return {{ sha1_skip: true, sync_clean: true }};
        return {{}};
      }},
      postJson: async (url, payload) => {{ calls.push({{ url, payload }}); return {{ ok: true }}; }},
      requestJson: async (url, options) => {{ calls.push({{ url, options }}); return {{ ok: true }}; }},
    }},
    showToast: (message, options) => toasts.push({{ message, options }}),
    showAppConfirm: async () => true,
  }},
  document: {{
    getElementById: (id) => {{ if (!elements[id]) elements[id] = makeEl(); return elements[id]; }},
    querySelector: () => null,
    querySelectorAll: () => [],
    createElement: makeEl,
  }},
  requestAnimationFrame: () => 0,
  setTimeout: () => 0,
  setInterval: () => 0,
  clearInterval: () => {{}},
}};
vm.createContext(context);
vm.runInContext(source, context, {{ filename: 'task.js' }});
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

    def test_trigger_task_posts_sync_all(self):
        payload = self._run_js(
            "triggerTask({ isRunning: false, setIsRunning: () => {} })"
        )
        self.assertEqual(payload["calls"], [{"url": "/tree/sync-all", "payload": {}}])
        self.assertTrue(payload["result"])

    def test_trigger_task_skips_when_running(self):
        payload = self._run_js(
            "triggerTask({ isRunning: true, setIsRunning: () => {} })"
        )
        self.assertEqual(payload["calls"], [])
        self.assertFalse(payload["result"])

    def test_save_new_task_posts_tree_tasks(self):
        payload = self._run_js(
            "(() => {"
            "  document.getElementById('tree_folder_path').value = '影视库/电视剧';"
            "  document.getElementById('tree_task_name').value = '目录树-影视库-电视剧';"
            "  return saveTreeTask();"
            "})()"
        )
        self.assertEqual(
            payload["calls"],
            [{
                "url": "/tree/tasks",
                "payload": {
                    "folder_path": "影视库/电视剧",
                    "tree_name": "目录树-影视库-电视剧",
                },
            }],
        )


if __name__ == "__main__":
    unittest.main()
