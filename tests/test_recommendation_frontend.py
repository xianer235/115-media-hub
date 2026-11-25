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


class ExploreYearFilterTest(unittest.TestCase):
    """年份筛选的三种入口（具体年份 / 近 N 年 / 起止输入）落到同一对 state 字段。"""

    def _eval(self, expression):
        dom_stub = r"""
const elements = {};
const makeEl = () => ({
  value: '', checked: false, innerText: '', innerHTML: '', className: '',
  dataset: {}, style: {}, scrollTop: 0, scrollHeight: 0,
  classList: { add() {}, remove() {}, toggle() {} },
  addEventListener() {}, appendChild() {}, setAttribute() {}, focus() {},
});
"""
        script = f"""
const fs = require('fs');
const vm = require('vm');
let source = fs.readFileSync({json.dumps(str(CORE_JS_PATH))}, 'utf8');
source = source.replace(/^export /gm, '');
{dom_stub}
const context = {{
  console,
  window: {{
    MediaHubApi: {{ getJson: async () => ({{ items: [], page: 1, total_pages: 1 }}), postJson: async () => ({{}}), requestJson: async () => ({{}}) }},
    scrollTo() {{}}, matchMedia: () => ({{ matches: false }}), innerWidth: 1440, addEventListener() {{}},
    showToast() {{}}, showAppConfirm: async () => true,
  }},
  document: {{
    body: makeEl(),
    getElementById: (id) => {{ if (!elements[id]) elements[id] = makeEl(); return elements[id]; }},
    querySelector: () => null,
    querySelectorAll: () => [],
    createElement: makeEl,
  }},
  requestAnimationFrame: () => 0, setTimeout: () => 0, setInterval: () => 0, clearInterval() {{}},
}};
vm.createContext(context);
vm.runInContext(source, context, {{ filename: 'recommendation-core.js' }});
const result = vm.runInContext({json.dumps(expression)}, context);
process.stdout.write(JSON.stringify(result));
"""
        completed = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True)
        if completed.returncode != 0:
            raise AssertionError(completed.stderr.strip())
        return json.loads(completed.stdout)

    def test_exact_year_sets_both_bounds_and_summary(self):
        payload = self._eval(
            "(function () {"
            "  setExploreYearExact('2024');"
            "  return {"
            "    from: document.getElementById('rec-explore-year-from').value,"
            "    to: document.getElementById('rec-explore-year-to').value,"
            "    summary: getExploreYearLabel(),"
            "  };"
            "})()"
        )
        self.assertEqual(payload["from"], "2024")
        self.assertEqual(payload["to"], "2024")
        self.assertEqual(payload["summary"], "2024 年")

    def test_recent_years_chip_uses_current_year_and_toggles_off(self):
        payload = self._eval(
            "(function () {"
            "  selectRecentYears(2);"
            "  const on = {"
            "    from: document.getElementById('rec-explore-year-from').value,"
            "    to: document.getElementById('rec-explore-year-to').value,"
            "  };"
            "  selectRecentYears(2);"
            "  const off = {"
            "    from: document.getElementById('rec-explore-year-from').value,"
            "    to: document.getElementById('rec-explore-year-to').value,"
            "  };"
            "  return { on, off, now: new Date().getFullYear() };"
            "})()"
        )
        self.assertEqual(int(payload["on"]["to"]), payload["now"])
        self.assertEqual(int(payload["on"]["from"]), payload["now"] - 1)
        self.assertEqual(payload["off"], {"from": "", "to": ""})

    def test_year_options_cover_recent_and_old_years(self):
        payload = self._eval(
            "(function () {"
            "  renderExploreYearOptions();"
            "  const html = document.getElementById('rec-explore-year-exact').innerHTML;"
            "  return {"
            "    now: new Date().getFullYear(),"
            "    hasNow: html.includes('>' + new Date().getFullYear() + ' 年<'),"
            "    hasOld: html.includes('>1950 年<'),"
            "    hasAny: html.includes('不限'),"
            "  };"
            "})()"
        )
        self.assertTrue(payload["hasNow"])
        self.assertTrue(payload["hasOld"])
        self.assertTrue(payload["hasAny"])


if __name__ == "__main__":
    unittest.main()
