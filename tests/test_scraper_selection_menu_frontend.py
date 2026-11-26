"""文件管理勾选栏「更多」菜单与文件列表高度地板的回归测试。

两件事各自钉住：
1. 勾选栏常驻按钮只留 4 个动作 + 「更多」，移动 / 区间选择 / 扫描监控 / 查重收进菜单，
   手机上不再一口气堆 7~9 个按钮把文件列表挤没。
2. `syncScraperBrowserHeight` 不再只看视口高度，而是给文件列表留一个地板高度：
   搜索框、移动提示条、查重面板这些横条一开，面板长高（页面滚动）而不是把列表压扁。
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRAPER_TEMPLATE = ROOT / "templates/partials/pages/scraper.html"
SCRAPER_CORE = ROOT / "static/js/modules/scraper/core.js"
DUPLICATES_JS = ROOT / "static/js/modules/scraper/duplicates.js"
STYLESHEET = ROOT / "static/css/index.css"

PRIMARY_ACTIONS = (
    "select-range",
    "rename-selected",
    "prepare-copy",
    "prepare-move",
    "delete-selected",
    "open-batch",
)
MENU_ACTIONS = ("monitor-scan", "open-duplicates")


def selection_actions_block(template: str) -> str:
    start = template.index('class="scraper-selection-actions"')
    end = template.index('id="scraper-move-buffer"')
    return template[start:end]


def more_menu_block(template: str) -> str:
    start = template.index('id="scraper-selection-more-menu"')
    end = template.index('id="scraper-reopen-batch-btn"')
    return template[start:end]


class SelectionMoreMenuTest(unittest.TestCase):
    def setUp(self):
        self.template = SCRAPER_TEMPLATE.read_text(encoding="utf-8")

    def test_primary_row_keeps_only_common_actions(self):
        block = selection_actions_block(self.template)
        menu_start = block.index('data-scraper-more')
        primary = block[:menu_start]
        for action in PRIMARY_ACTIONS:
            self.assertIn(f'data-scraper-action="{action}"', primary)
        for action in MENU_ACTIONS:
            self.assertNotIn(f'data-scraper-action="{action}"', primary)

    def test_low_frequency_actions_live_in_menu(self):
        menu = more_menu_block(self.template)
        for action in MENU_ACTIONS:
            self.assertIn(f'data-scraper-action="{action}"', menu)
        self.assertIn('role="menu"', menu)
        self.assertIn('role="menuitem"', menu)

    def test_more_button_starts_collapsed(self):
        template = self.template
        start = template.index('id="scraper-more-btn"')
        tag_start = template.rindex("<", 0, start)
        tag_end = template.index(">", start)
        tag = template[tag_start:tag_end]
        self.assertIn('aria-expanded="false"', tag)
        self.assertIn('aria-controls="scraper-selection-more-menu"', tag)
        self.assertNotIn("disabled", tag)

        menu_start = template.index('id="scraper-selection-more-menu"')
        menu_tag_end = template.index(">", menu_start)
        self.assertIn("hidden", template[menu_start:menu_tag_end])

    def test_duplicates_button_still_disabled_by_default(self):
        template = self.template
        start = template.index('data-scraper-action="open-duplicates"')
        tag_start = template.rindex("<", 0, start)
        tag_end = template.index(">", start)
        self.assertIn("disabled", template[tag_start:tag_end])


class SelectionMoreScriptTest(unittest.TestCase):
    def setUp(self):
        self.source = SCRAPER_CORE.read_text(encoding="utf-8")

    def test_toggle_action_is_wired_before_generic_handlers(self):
        self.assertIn("if (action === 'toggle-more') {", self.source)
        self.assertIn("function toggleSelectionMore(", self.source)
        self.assertIn("function closeSelectionMore(", self.source)

    def test_clicking_menu_item_closes_menu(self):
        self.assertIn("if (actionButton.closest('#scraper-selection-more-menu')) {", self.source)
        block = self.source[self.source.index("if (actionButton.closest('#scraper-selection-more-menu')) {"):]
        self.assertIn("closeSelectionMore();", block[:400])

    def test_click_outside_page_closes_menu(self):
        # 点页面里任何非「更多」区域的元素都收起菜单（换网盘、面包屑、点文件行进目录都算），
        # 避免它一直盖在文件列表上。
        body = self.source[self.source.index("function handleClick(event) {"):]
        top = body[:400]
        self.assertIn("closest?.('[data-scraper-more]')", top)
        self.assertIn("closeSelectionMore();", top)

    def test_escape_closes_menu_first(self):
        body = self.source[self.source.index("function handleGlobalKeydown(event) {"):]
        body = body[: body.index("function bindEvents()")]
        self.assertLess(body.index("scraper-selection-more-menu"), body.index("scraper-batch-panel"))

    def test_more_button_hides_when_menu_is_empty(self):
        # 预览模式下菜单项全被收起，「更多」不该留一个空壳按钮。
        block = self.source[self.source.index("const moreButton = $('scraper-more-btn');"):]
        block = block[:600]
        self.assertIn("anyVisible", block)
        self.assertIn("moreButton.classList.toggle('hidden', !anyVisible)", block)


class BrowserHeightFloorTest(unittest.TestCase):
    def setUp(self):
        self.source = SCRAPER_CORE.read_text(encoding="utf-8")
        self.duplicates = DUPLICATES_JS.read_text(encoding="utf-8")

    def height_body(self) -> str:
        start = self.source.index("function syncScraperBrowserHeight() {")
        end = self.source.index("function scheduleBrowserHeightSync(", start)
        return self.source[start:end]

    def test_panel_height_accounts_for_chrome_above_the_list(self):
        body = self.height_body()
        self.assertIn("minListHeight", body)
        self.assertIn("chrome", body)
        self.assertIn("Math.max(available", body)
        self.assertIn("--scraper-browser-height", body)

    def test_mobile_gets_a_smaller_floor(self):
        body = self.height_body()
        self.assertIn("max-width: 760px", body)
        self.assertIn("288", body)

    def test_duplicates_panel_triggers_height_resync(self):
        self.assertIn("window.syncScraperBrowserHeight?.();", self.duplicates)
        # render() 与 close() 都要重算，否则关掉面板后列表还停在压缩状态。
        self.assertGreaterEqual(self.duplicates.count("window.syncScraperBrowserHeight?.();"), 2)

    def test_height_sync_is_scheduled_after_selection_render(self):
        block = self.source[self.source.index("const moreButton = $('scraper-more-btn');"):]
        block = block[:800]
        self.assertIn("scheduleBrowserHeightSync();", block)


class SelectionMoreStyleTest(unittest.TestCase):
    def setUp(self):
        self.stylesheet = STYLESHEET.read_text(encoding="utf-8")

    def test_menu_has_day_and_night_palette(self):
        self.assertIn(".scraper-selection-more-menu {", self.stylesheet)
        self.assertIn(".scraper-selection-more-menu.hidden { display: none; }", self.stylesheet)
        self.assertIn("html.theme-day .scraper-selection-more-menu", self.stylesheet)
        self.assertIn("html.theme-day .scraper-menu-item", self.stylesheet)

    def test_mobile_caps_duplicates_panel_height(self):
        start = self.stylesheet.index("@media (max-width: 760px) {")
        end = self.stylesheet.index("html.theme-day .scraper-page", start)
        mobile_block = self.stylesheet[start:end]
        self.assertIn("max-height: min(40vh, 360px);", mobile_block)

    def test_actions_container_never_clips_the_dropdown(self):
        # 「更多」下拉绝对定位在按钮下方，一旦被容器裁掉，点按钮就毫无反应。
        # overflow 只要有一个方向不是 visible，另一个方向也会被算成 auto —— 所以
        # 这个容器上不能出现 overflow-x: auto / hidden / scroll。
        block = self.stylesheet[self.stylesheet.index(".scraper-selection-actions {"):]
        block = block[: block.index("}")]
        # 注释里会提到这些取值（解释为什么不能用），先剥掉注释再断言。
        block = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
        self.assertIn("overflow: visible;", block)
        for clipped in ("overflow-x: auto", "overflow-x: hidden", "overflow: hidden", "flex-wrap: nowrap"):
            self.assertNotIn(clipped, block)

        mobile_start = self.stylesheet.index("@media (max-width: 760px) {")
        mobile_end = self.stylesheet.index("html.theme-day .scraper-page", mobile_start)
        mobile_block = self.stylesheet[mobile_start:mobile_end]
        # 手机端有两条都叫 .scraper-selection-actions 的规则（一条和 selection-state 并列
        # 只写 width: 100%），这里要的是带 flex-wrap 的排版规则本身。
        candidates = re.findall(r"\.scraper-selection-actions \{[^}]*\}", mobile_block)
        rule = next(item for item in candidates if "flex-wrap" in item)
        rule = re.sub(r"/\*.*?\*/", "", rule, flags=re.S)
        self.assertIn("overflow: visible;", rule)
        self.assertNotIn("overflow-x: auto", rule)
        self.assertNotIn("flex-wrap: nowrap", rule)


if __name__ == "__main__":
    unittest.main()
