import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOOT_JS = ROOT / "static/js/modules/app/boot.js"
SUBSCRIPTION_UI = ROOT / "static/js/modules/subscription/ui.js"


class TextareaCaretFrontendTest(unittest.TestCase):
    """长文本框要把视口跟到光标处，否则用户看不到插入点（粘贴后停在开头最典型）。"""

    def test_boot_exposes_caret_visibility_helper(self):
        boot = BOOT_JS.read_text(encoding="utf-8")
        self.assertIn("function ensureTextareaCaretVisible(el)", boot)
        self.assertIn("window.ensureTextareaCaretVisible = ensureTextareaCaretVisible", boot)
        # 键盘、鼠标/触摸点击、拖选后都要校正一次
        self.assertIn("['keyup', 'click', 'select'].forEach", boot)
        self.assertIn("el.tagName !== 'TEXTAREA'", boot)
        # 没溢出就不该动滚动条（否则会在普通输入框里乱跳）
        self.assertIn("el.scrollHeight <= el.clientHeight + 1", boot)

    def _run_paste(self, expose_helper=True):
        """在 node vm 里跑一遍 pasteSubscriptionLinkScan，返回 textarea 的滚动调用记录。"""
        helper = (
            "window.ensureTextareaCaretVisible = target => {"
            "  __caretCalls.push(target && target.id);"
            "};"
            if expose_helper
            else ""
        )
        script = f"""
const fs = require('fs');
const vm = require('vm');
const el = {{
  id: 'subscription-link-scan-text',
  value: '',
  scrollTop: 0,
  scrollHeight: 640,
  clientHeight: 120,
  selectionStart: 0,
  selectionEnd: 0,
  focus() {{}},
  setSelectionRange(start, end) {{ this.selectionStart = start; this.selectionEnd = end; }},
}};
const context = {{
  window: {{}},
  __caretCalls: [],
  document: {{
    getElementById: id => (id === 'subscription-link-scan-text' ? el : null),
  }},
  navigator: {{ clipboard: {{ readText: async () => 'https://pan.quark.cn/s/aaa\\nhttps://pan.quark.cn/s/bbb' }} }},
  showToast: () => {{}},
  requestAnimationFrame: cb => {{ cb(); }},
  setTimeout: cb => {{ cb(); }},
  console,
}};
vm.createContext(context);
vm.runInContext({json.dumps(helper)}, context);
vm.runInContext(fs.readFileSync({json.dumps(str(SUBSCRIPTION_UI))}, 'utf8'), context);
(async () => {{
  await vm.runInContext('pasteSubscriptionLinkScan()', context);
  process.stdout.write(JSON.stringify({{
    value: el.value,
    selectionEnd: el.selectionEnd,
    scrollTop: el.scrollTop,
    caretCalls: context.__caretCalls,
  }}));
}})();
"""
        completed = subprocess.run(
            ["node", "-e", script],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            timeout=60,
        )
        if completed.returncode != 0:
            self.fail(f"node 执行失败：{completed.stderr.strip()[:800]}")
        return json.loads(completed.stdout.strip() or "{}")

    def test_link_scan_paste_keeps_caret_visible(self):
        result = self._run_paste(expose_helper=True)
        self.assertIn("pan.quark.cn", result.get("value") or "")
        self.assertEqual(result.get("selectionEnd"), len(result.get("value") or ""))
        # 粘贴后必须有一次把视口挪到光标的动作
        self.assertIn("subscription-link-scan-text", result.get("caretCalls") or [])

    def test_link_scan_paste_falls_back_to_bottom_scroll(self):
        result = self._run_paste(expose_helper=False)
        self.assertEqual(result.get("scrollTop"), 640)


if __name__ == "__main__":
    unittest.main()
