import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_JS_PATH = ROOT / "static/js/modules/recommendation/core.js"
PAGE_TEMPLATE_PATH = ROOT / "templates/partials/pages/recommendation.html"


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


class RecommendationMediaTypeTest(unittest.TestCase):
    """媒体类型只留一处：顶部不再拆「热门电影 / 热门剧集」，改由内容头那一个开关驱动。"""

    def _eval(self, expression):
        dom_stub = r"""
const elements = {};
const makeEl = () => ({
  value: '', checked: false, innerText: '', innerHTML: '', className: '',
  dataset: {}, style: {}, scrollTop: 0, scrollHeight: 0,
  classList: { add() {}, remove() {}, toggle() {} },
  addEventListener() {}, appendChild() {}, setAttribute() {}, focus() {},
});
const requests = [];
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
    MediaHubApi: {{
      getJson: async (url) => {{ requests.push(url); return {{ items: [], page: 1, total_pages: 1 }}; }},
      postJson: async () => ({{}}),
      requestJson: async () => ({{}}),
    }},
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
context.window.__requests = requests;
vm.createContext(context);
vm.runInContext(source, context, {{ filename: 'recommendation-core.js' }});
Promise.resolve(vm.runInContext({json.dumps(expression)}, context))
  .then((result) => process.stdout.write(JSON.stringify(result)))
  .catch((error) => {{ console.error(error); process.exit(1); }});
"""
        completed = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True)
        if completed.returncode != 0:
            raise AssertionError(completed.stderr.strip())
        return json.loads(completed.stdout)

    def test_template_has_single_popular_tab(self):
        html = PAGE_TEMPLATE_PATH.read_text(encoding="utf-8")
        self.assertEqual(html.count('data-rec-tab="popular"'), 1)
        self.assertNotIn("热门电影", html)
        self.assertNotIn("热门剧集", html)
        # 搜索条里那套「全部/电影/剧集」下拉已删除，只剩内容头的一个开关
        self.assertNotIn("recommendation-media-type", html)
        self.assertEqual(html.count('id="rec-media-type"'), 1)

    def test_popular_falls_back_to_movie_when_type_is_all(self):
        urls = self._eval(
            "(async () => {"
            "  setRecommendationMediaType('all', false);"
            "  await loadRecommendationPopular();"
            "  return window.__requests;"
            "})()"
        )
        self.assertEqual(len(urls), 1)
        # TMDB 没有「全部热门片单」，全部应该落到电影而不是发出 media_type=all
        self.assertIn("media_type=movie", urls[0])

    def test_type_switch_drives_trending_popular_and_search(self):
        urls = self._eval(
            "(async () => {"
            "  setRecommendationMediaType('tv', false);"
            "  await loadRecommendationTrending('day');"
            "  await loadRecommendationPopular();"
            "  await searchRecommendationTmdb('dune');"
            "  return window.__requests;"
            "})()"
        )
        self.assertEqual(len(urls), 3)
        self.assertTrue(all("media_type=tv" in url for url in urls), urls)


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


class ExploreScoreRangeTest(unittest.TestCase):
    """评分 / 投票数改成双端区间条后，仍只落到原来那对 state 字段（rating/ratingMax、voteCount/voteCountMax）。"""

    _eval = ExploreYearFilterTest._eval

    def test_rating_low_end_sets_only_lower_bound(self):
        payload = self._eval(
            "(function () {"
            "  document.getElementById('rec-explore-rating').value = '7.5';"
            "  document.getElementById('rec-explore-rating-max').value = '10';"
            "  onExploreRangeInput('rating', 'lo');"
            "  return {"
            "    rating: exploreFilterState.rating,"
            "    ratingMax: exploreFilterState.ratingMax,"
            "    text: String(document.getElementById('rec-explore-rating-value').textContent),"
            "    count: String(document.getElementById('rec-explore-filter-count').textContent || ''),"
            "    summary: getExploreSummaryText(),"
            "  };"
            "})()"
        )
        self.assertEqual(payload["rating"], "7.5")
        # 上端拉到顶就是「不限」，不能写成 '10'
        self.assertEqual(payload["ratingMax"], "")
        self.assertEqual(payload["text"], "≥ 7.5")
        # 一条区间只算一条筛选，不能因为两端都动就 +2
        self.assertEqual(payload["count"], "1")
        self.assertIn("评分≥7.5", payload["summary"])

    def test_rating_bounds_never_cross(self):
        payload = self._eval(
            "(function () {"
            "  document.getElementById('rec-explore-rating').value = '9';"
            "  document.getElementById('rec-explore-rating-max').value = '7';"
            "  onExploreRangeInput('rating', 'lo');"
            "  var afterLo = [exploreFilterState.rating, exploreFilterState.ratingMax];"
            "  document.getElementById('rec-explore-rating').value = '8';"
            "  document.getElementById('rec-explore-rating-max').value = '6';"
            "  onExploreRangeInput('rating', 'hi');"
            "  return { afterLo, afterHi: [exploreFilterState.rating, exploreFilterState.ratingMax] };"
            "})()"
        )
        # 拖左端超过右端 → 左端顶到右端；拖右端低于左端 → 右端顶到左端
        self.assertEqual(payload["afterLo"], ["7", "7"])
        self.assertEqual(payload["afterHi"], ["8", "8"])

    def test_vote_count_uses_discrete_stops(self):
        payload = self._eval(
            "(function () {"
            "  document.getElementById('rec-explore-vote-count').value = '3';"
            "  document.getElementById('rec-explore-vote-count-max').value = '8';"
            "  onExploreRangeInput('votes', 'lo');"
            "  var low = [exploreFilterState.voteCount, exploreFilterState.voteCountMax];"
            "  document.getElementById('rec-explore-vote-count-max').value = '4';"
            "  onExploreRangeInput('votes', 'hi');"
            "  return {"
            "    low,"
            "    range: [exploreFilterState.voteCount, exploreFilterState.voteCountMax],"
            "    text: String(document.getElementById('rec-explore-vote-count-value').textContent),"
            "  };"
            "})()"
        )
        # 档位 0/100/200/500/1000/2000/5000/10000/20000：下标 3 → 500，下标 4 → 1000
        self.assertEqual(payload["low"], ["500", ""])
        self.assertEqual(payload["range"], ["500", "1000"])
        self.assertEqual(payload["text"], "500 – 1000")

    def test_clearing_bounds_restores_idle_sliders(self):
        payload = self._eval(
            "(function () {"
            "  exploreFilterState.rating = '7';"
            "  exploreFilterState.ratingMax = '9';"
            "  exploreFilterState.voteCount = '500';"
            "  exploreFilterState.voteCountMax = '5000';"
            "  syncExploreRangeUi();"
            "  var busy = {"
            "    rating: [document.getElementById('rec-explore-rating').value,"
            "             document.getElementById('rec-explore-rating-max').value],"
            "    votes: [document.getElementById('rec-explore-vote-count').value,"
            "            document.getElementById('rec-explore-vote-count-max').value],"
            "  };"
            "  exploreFilterState.rating = '';"
            "  exploreFilterState.ratingMax = '';"
            "  exploreFilterState.voteCount = '';"
            "  exploreFilterState.voteCountMax = '';"
            "  syncExploreRangeUi();"
            "  return {"
            "    busy,"
            "    idle: [document.getElementById('rec-explore-rating').value,"
            "           document.getElementById('rec-explore-rating-max').value,"
            "           document.getElementById('rec-explore-vote-count').value,"
            "           document.getElementById('rec-explore-vote-count-max').value],"
            "    text: String(document.getElementById('rec-explore-rating-value').textContent),"
            "  };"
            "})()"
        )
        self.assertEqual(payload["busy"]["rating"], ["7", "9"])
        self.assertEqual(payload["busy"]["votes"], ["3", "6"])
        self.assertEqual(payload["idle"], ["0", "10", "0", "8"])
        self.assertEqual(payload["text"], "不限")


class SeasonListRenderTest(unittest.TestCase):
    """详情弹窗的季列表：有真实篇名就显示篇名，没有就回退「第 N 季」。"""

    def _render(self, owned=None, season_episode_map=None, season_names=None):
        season_map = season_episode_map if season_episode_map is not None else {'1': 6, '2': 5}
        season_name_map = season_names if season_names is not None else {'1': '黄河篇1&2'}
        owned_literal = json.dumps(owned or {}, ensure_ascii=False)
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
  recommendationOwned = {owned_literal};
  const item = {{ id: 1, media_type: 'tv', title: '奔跑吧·特别篇', year: '2020', vote_average: 9 }};
  const detail = {{
    status: 'Returning Series',
    total_seasons: 2,
    total_episodes: 11,
    season_episode_map: {json.dumps(season_map)},
    season_names: {json.dumps(season_name_map, ensure_ascii=False)},
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

    def test_season_fully_owned_shows_check_and_owned_class(self):
        html = self._render(
            owned={1: {"seasons": {"1": 6}}},
            season_episode_map={'1': 6, '2': 5},
        )
        self.assertIn("is-owned", html)
        self.assertIn("✓ 6 集", html)
        # 第二季库里没有 → 保持原样，不能被打上 is-owned
        self.assertIn("5 集", html)
        self.assertIn("极影视库：已有 1/2 季", html)

    def test_partial_season_shows_library_count(self):
        html = self._render(
            owned={1: {"seasons": {"1": 3, "2": 5}}},
            season_episode_map={'1': 6, '2': 5},
        )
        self.assertIn("is-partial", html)
        self.assertIn("库中 3/6 集", html)
        self.assertIn("✓ 5 集", html)
        self.assertIn("极影视库：已有 2/2 季", html)

    def test_owned_without_usable_season_numbers_says_so(self):
        # 极影视把集数当季号时（实测 6.6%），季行全对不上，顶部不能只说「已有」
        html = self._render(owned={1: {"seasons": {"452": 12}}})
        self.assertIn("已有（没识别到季号）", html)
        self.assertNotIn("is-owned", html)

    def test_no_owned_data_keeps_plain_season_list(self):
        html = self._render()
        self.assertNotIn("rec-detail-season-hint", html)
        self.assertNotIn("is-owned", html)
        self.assertNotIn("极影视库", html)


if __name__ == "__main__":
    unittest.main()
