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

    def test_default_year_is_current_year(self):
        """2026 年的今天：默认筛选就是今年，不再是不限。"""
        payload = self._eval(
            "(function () {"
            "  renderExploreYearOptions();"
            "  syncExploreFilterUi();"
            "  const now = new Date().getFullYear();"
            "  return {"
            "    now,"
            "    from: document.getElementById('rec-explore-year-from').value,"
            "    to: document.getElementById('rec-explore-year-to').value,"
            "    exact: document.getElementById('rec-explore-year-exact').value,"
            "    count: String(document.getElementById('rec-explore-filter-count').textContent || ''),"
            "    summary: String(document.getElementById('rec-explore-summary-text').textContent || ''),"
            "  };"
            "})()"
        )
        self.assertEqual(payload["from"], str(payload["now"]))
        self.assertEqual(payload["to"], str(payload["now"]))
        self.assertEqual(payload["exact"], str(payload["now"]))
        # 默认值不算「已选筛选」，否则一进页面就挂着数字
        self.assertEqual(payload["count"], "0")
        self.assertIn(str(payload["now"]) + " 年", payload["summary"])

    def test_year_options_stop_at_current_year(self):
        payload = self._eval(
            "(function () {"
            "  renderExploreYearOptions();"
            "  const html = document.getElementById('rec-explore-year-exact').innerHTML;"
            "  return {"
            "    now: new Date().getFullYear(),"
            "    hasNext: html.includes('>' + (new Date().getFullYear() + 1) + ' 年<'),"
            "    hasNow: html.includes('>' + new Date().getFullYear() + ' 年<'),"
            "  };"
            "})()"
        )
        self.assertTrue(payload["hasNow"])
        self.assertFalse(payload["hasNext"])

    def test_clearing_year_removes_default_and_counts_one(self):
        payload = self._eval(
            "(function () {"
            "  setExploreYearExact('');"
            "  const cleared = String(document.getElementById('rec-explore-filter-count').textContent || '');"
            "  setExploreYearExact('2020');"
            "  return {"
            "    cleared,"
            "    picked: String(document.getElementById('rec-explore-filter-count').textContent || ''),"
            "    summary: String(document.getElementById('rec-explore-summary-text').textContent || ''),"
            "  };"
            "})()"
        )
        self.assertEqual(payload["cleared"], "0")
        self.assertEqual(payload["picked"], "1")
        self.assertIn("2020 年", payload["summary"])

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


class SeasonListRenderTest(unittest.TestCase):
    """详情弹窗的季列表：有真实篇名就显示篇名，没有就回退「第 N 季」。"""

    def _render(self):
        dom_stub = r"""
const elements = {};
const makeEl = () => ({
  value: '', checked: false, innerText: '', innerHTML: '', className: '',
  dataset: {}, style: {},
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
    MediaHubApi: {{ getJson: async () => ({{}}), postJson: async () => ({{}}), requestJson: async () => ({{}}) }},
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
const expression = `(function () {{
  const item = {{ id: 1, media_type: 'tv', title: '奔跑吧·特别篇', year: '2020', vote_average: 9 }};
  const detail = {{
    status: 'Returning Series',
    total_seasons: 2,
    total_episodes: 11,
    season_episode_map: {{ '1': 6, '2': 5 }},
    season_names: {{ '1': '黄河篇1&2' }},
    aliases: [],
  }};
  renderRecDetailContent(item, detail);
  return {{ html: document.getElementById('rec-detail-content').innerHTML }};
}})()`;
process.stdout.write(JSON.stringify(vm.runInContext(expression, context)));
"""
        completed = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True)
        if completed.returncode != 0:
            raise AssertionError(completed.stderr.strip())
        return json.loads(completed.stdout)["html"]

    def test_real_season_name_and_fallback_are_both_rendered(self):
        html = self._render()
        self.assertIn("rec-detail-seasons", html)
        self.assertIn("黄河篇1&amp;2", html)
        self.assertIn("rec-detail-season-no", html)
        self.assertGreaterEqual(html.count("rec-detail-season-row"), 2)
        # 没名字的第二季回退成占位文案并打上 is-generic
        self.assertIn("第 2 季", html)
        self.assertIn("is-generic", html)
        self.assertIn("6 集", html)


if __name__ == "__main__":
    unittest.main()
