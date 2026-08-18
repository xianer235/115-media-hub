import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_JS_PATH = ROOT / "static/js/modules/recommendation/core.js"


class RecommendationPaginationScrollTest(unittest.TestCase):
    def test_go_to_page_scrolls_to_top(self):
        source = CORE_JS_PATH.read_text(encoding="utf-8")
        self.assertIn("function scrollRecommendationToTop()", source)
        self.assertIn("scrollRecommendationToTop();", source)
        self.assertIn("window.scrollTo({ top: 0, behavior: 'smooth' });", source)
        # 回顶必须发生在翻页分发之前，避免骨架屏高度收缩把滚动位置钳制在页面中间。
        dispatch_index = source.index("var ctx = recommendationPagination.currentContext;")
        scroll_index = source.index("scrollRecommendationToTop();")
        self.assertLess(scroll_index, dispatch_index)

    def _run_js(self, expression):
        dom_stub = r"""
const elements = {};
const makeEl = () => ({
  value: '',
  checked: false,
  innerText: '',
  innerHTML: '',
  className: '',
  dataset: {},
  style: {},
  scrollTop: 0,
  scrollHeight: 0,
  classList: { add() {}, remove() {}, toggle() {} },
  addEventListener() {},
  appendChild() {},
  setAttribute() {},
  focus() {},
});
"""
        script = f"""
const fs = require('fs');
const vm = require('vm');
let source = fs.readFileSync({json.dumps(str(CORE_JS_PATH))}, 'utf8');
source = source.replace(/^export /gm, '');
const scrollCalls = [];
{dom_stub}
const context = {{
  console,
  window: {{
    MediaHubApi: {{
      getJson: async (url) => {{
        if (url.includes('page=1')) return {{ items: [], page: 1, total_pages: 3 }};
        if (url.includes('page=2')) return {{ items: [], page: 2, total_pages: 3 }};
        return {{ items: [], page: 1, total_pages: 1 }};
      }},
      postJson: async () => ({{ ok: true }}),
      requestJson: async () => ({{ ok: true }}),
    }},
    scrollTo: (...args) => scrollCalls.push(args),
    matchMedia: () => ({{ matches: false }}),
    innerWidth: 1440,
    addEventListener() {{}},
    showToast() {{}},
    showAppConfirm: async () => true,
  }},
  document: {{
    body: makeEl(),
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
vm.runInContext(source, context, {{ filename: 'recommendation-core.js' }});
Promise.resolve(vm.runInContext({json.dumps(expression)}, context))
  .then(() => process.stdout.write(JSON.stringify({{ scrollCalls }})))
  .catch((error) => {{
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

    def test_page_flip_actually_calls_scroll_to_top(self):
        payload = self._run_js(
            "(async () => {"
            "  await loadRecommendationPopular('movie');"
            "  await goToRecommendationPage(2);"
            "})()"
        )
        self.assertEqual(payload["scrollCalls"], [[{ "top": 0, "behavior": "smooth" }]])


if __name__ == "__main__":
    unittest.main()
