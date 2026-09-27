import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETTINGS_TEMPLATE_PATH = ROOT / "templates/partials/pages/settings.html"
SETTINGS_MODULE_PATH = ROOT / "static/js/modules/tabs/settings.js"
INDEX_SCRIPT_PATH = ROOT / "static/js/index.js"
INDEX_CSS_PATH = ROOT / "static/css/index.css"

SECTION_KEYS = ["auth", "strm", "tg", "pansou", "proxy", "tmdb", "ai", "notify", "security", "filter"]


class SettingsSectionLayoutFrontendTest(unittest.TestCase):
    """设置页改成「顶部横向分区条 + 单开折叠卡片」后的结构回归。"""

    def setUp(self):
        self.template = SETTINGS_TEMPLATE_PATH.read_text(encoding="utf-8")

    def test_template_has_section_nav_with_expand_controls(self):
        self.assertIn('id="settings-section-navbar"', self.template)
        self.assertIn('id="settings-section-nav"', self.template)
        self.assertIn('aria-label="设置分区导航"', self.template)
        self.assertIn('onclick="expandAllSettingsSections()"', self.template)
        self.assertIn('onclick="collapseAllSettingsSections()"', self.template)

    def test_template_has_one_collapsible_card_per_section(self):
        for key in SECTION_KEYS:
            self.assertIn(f'data-settings-section="{key}"', self.template)
        self.assertEqual(self.template.count('class="settings-section-head"'), len(SECTION_KEYS))
        self.assertEqual(self.template.count("settings-section-body"), len(SECTION_KEYS))

    def test_template_drops_manual_order_and_numbered_titles(self):
        self.assertNotIn('style="order:', self.template)
        for step in ("1", "2", "3", "4", "5", "6", "6b", "7", "8", "9"):
            self.assertIn(f'data-settings-step="{step}"', self.template)
        self.assertNotIn(">9. 批量整理过滤词", self.template)
        self.assertIn(">批量整理过滤词（可选）<", self.template)

    def test_section_heads_control_existing_bodies(self):
        head_ids = re.findall(r'class="settings-section-head"[^>]*aria-controls="([^"]+)"', self.template)
        self.assertEqual(len(head_ids), len(SECTION_KEYS))
        self.assertEqual(len(set(head_ids)), len(SECTION_KEYS))
        for body_id in head_ids:
            self.assertIn(f'id="{body_id}"', self.template)
        # 折叠态在模板里默认收起，具体展开哪一个由 JS 决定。
        self.assertEqual(self.template.count('aria-expanded="false"'), len(SECTION_KEYS))

    def test_long_help_texts_are_folded(self):
        self.assertEqual(self.template.count('class="settings-help-fold"'), 3)
        self.assertEqual(self.template.count("<summary>查看说明"), 3)
        self.assertIn("兼容 DeepSeek / Qwen / OpenAI / 本地 Ollama", self.template)
        self.assertIn("推送范围：订阅成功入库", self.template)
        self.assertIn("油猴脚本和文件夹监控的关系", self.template)

    def test_save_button_lives_in_sticky_nav(self):
        # 底部固定保存条已移除，保存入口移进顶部吸顶条，释放页面底部空间。
        self.assertNotIn('id="settings-save-dock"', self.template)
        self.assertNotIn("settings-save-card", self.template)
        actions = re.search(r'<div class="settings-section-nav-actions">(.*?)</div>', self.template, re.S)
        self.assertIsNotNone(actions)
        self.assertIn('class="settings-section-save-btn"', actions.group(1))
        self.assertIn('onclick="saveSettings()"', actions.group(1))
        self.assertIn("保存全部配置", actions.group(1))
        css = INDEX_CSS_PATH.read_text(encoding="utf-8")
        self.assertNotIn("settings-save-card", css)
        self.assertNotIn("has-inline-save-dock", css)
        self.assertIn(".settings-section-save-btn", css)
        source = INDEX_SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertNotIn("syncSettingsSaveDock", source)
        boot_source = (ROOT / "static/js/modules/app/boot.js").read_text(encoding="utf-8")
        self.assertNotIn("syncSettingsSaveDock", boot_source)

    def test_settings_module_implements_section_nav(self):
        source = SETTINGS_MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("export function initSettingsSectionNav", source)
        self.assertIn("export function openSettingsSection", source)
        self.assertIn("export function expandAllSettingsSections", source)
        self.assertIn("export function collapseAllSettingsSections", source)
        self.assertIn("export function refreshSettingsSectionSummaries", source)
        self.assertIn("const SETTINGS_OPEN_SECTION_STORAGE_KEY = 'settings-open-section'", source)
        self.assertIn("localStorage.setItem(SETTINGS_OPEN_SECTION_STORAGE_KEY", source)
        # 单开手风琴：打开一个就收起其它，重复点击可收起。
        self.assertIn("cards.forEach((card) => setSettingsSectionOpen(card, card === target));", source)
        self.assertIn("classList.toggle('is-open'", source)
        self.assertIn("aria-current", source)

    def test_ensure_tab_data_initializes_section_nav(self):
        source = SETTINGS_MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("initSettingsSectionNav();", source)
        self.assertIn("refreshSettingsSectionSummaries();", source)

    def test_index_script_measures_toolbar_and_exposes_actions(self):
        source = INDEX_SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn("--shell-toolbar-h", source)
        self.assertIn("function expandAllSettingsSections()", source)
        self.assertIn("function collapseAllSettingsSections()", source)

    def test_styles_cover_sticky_nav_and_day_theme(self):
        css = INDEX_CSS_PATH.read_text(encoding="utf-8")
        self.assertIn(".settings-section-navbar", css)
        self.assertIn("top: calc(var(--shell-toolbar-h, 72px) + 8px);", css)
        self.assertIn(".settings-section-card:not(.is-open) > .settings-section-body", css)
        self.assertIn("html.theme-day .settings-section-navbar", css)
        self.assertIn(".settings-help-fold[open] > summary", css)


if __name__ == "__main__":
    unittest.main()
