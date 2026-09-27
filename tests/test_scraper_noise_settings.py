import unittest
from pathlib import Path
from unittest import mock

from app import core
from app.services import scraper


ROOT = Path(__file__).resolve().parents[1]


class ScraperNoiseSettingsTest(unittest.TestCase):
    def setUp(self):
        scraper._NOISE_RULES_CACHE.clear()

    def test_normalize_scraper_noise_words_dedupes_and_strips(self):
        self.assertEqual(
            core.normalize_scraper_noise_words([" 国语音轨 ", "无水印", "国语音轨"]),
            ["国语音轨", "无水印"],
        )
        self.assertEqual(
            core.normalize_scraper_noise_words("国语音轨,无水印\n国语音轨"),
            ["国语音轨", "无水印"],
        )

    def test_normalize_scraper_noise_words_limits_length_and_count(self):
        long_word = "长" * 60
        self.assertNotIn(long_word, core.normalize_scraper_noise_words([long_word]))
        many = [f"词{i}" for i in range(210)]
        self.assertEqual(len(core.normalize_scraper_noise_words(many)), 200)

    def test_normalize_config_keeps_custom_noise_words(self):
        cfg = core.normalize_config(
            {
                "scraper_noise_phrases": [" 自定义复合词 ", "自定义复合词", ""],
                "scraper_standalone_noise_words": "独立词A\n独立词B\n独立词A",
            }
        )
        self.assertEqual(cfg["scraper_noise_phrases"], ["自定义复合词"])
        self.assertEqual(cfg["scraper_standalone_noise_words"], ["独立词A", "独立词B"])
        empty = core.normalize_config({})
        self.assertEqual(empty["scraper_noise_phrases"], [])
        self.assertEqual(empty["scraper_standalone_noise_words"], [])

    def test_custom_compound_phrase_cleaned_anywhere(self):
        with mock.patch.object(
            scraper,
            "get_config",
            return_value={
                "scraper_noise_phrases": ["自定义复合词"],
                "scraper_standalone_noise_words": [],
            },
        ):
            self.assertEqual(
                scraper._extract_scraper_title_candidates("剧名.自定义复合词.2024.1080p.mkv"),
                ["剧名"],
            )
            self.assertTrue(scraper._is_scraper_generic_keyword("自定义复合词"))

    def test_custom_standalone_word_cleaned_only_at_boundary(self):
        with mock.patch.object(
            scraper,
            "get_config",
            return_value={
                "scraper_noise_phrases": [],
                "scraper_standalone_noise_words": ["测试词"],
            },
        ):
            self.assertEqual(
                scraper._extract_scraper_title_candidates("片名.测试词.2024.mkv"),
                ["片名"],
            )
            self.assertEqual(
                scraper._extract_scraper_title_candidates("测试词尾.2024.mkv"),
                ["测试词尾"],
            )
            self.assertTrue(scraper._is_scraper_generic_keyword("测试词"))
            self.assertFalse(scraper._is_scraper_generic_keyword("测试词尾"))

    def test_empty_custom_rules_keep_builtin_behavior(self):
        with mock.patch.object(
            scraper,
            "get_config",
            return_value={
                "scraper_noise_phrases": [],
                "scraper_standalone_noise_words": [],
            },
        ):
            self.assertEqual(
                scraper._extract_scraper_title_candidates("监狱星级餐厅.国语音轨.2024.1080p.mkv"),
                ["监狱星级餐厅"],
            )
            self.assertTrue(scraper._is_scraper_generic_keyword("国语音轨"))

    def test_rules_cache_refreshes_after_config_change(self):
        with mock.patch.object(
            scraper,
            "get_config",
            return_value={
                "scraper_noise_phrases": [],
                "scraper_standalone_noise_words": [],
            },
        ):
            self.assertFalse(scraper._is_scraper_generic_keyword("自定义词A"))
        with mock.patch.object(
            scraper,
            "get_config",
            return_value={
                "scraper_noise_phrases": ["自定义词A"],
                "scraper_standalone_noise_words": [],
            },
        ):
            self.assertTrue(scraper._is_scraper_generic_keyword("自定义词A"))


class ScraperNoiseSettingsFrontendTest(unittest.TestCase):
    def test_settings_page_has_noise_filter_section(self):
        html = (ROOT / "templates/partials/pages/settings.html").read_text(encoding="utf-8")
        self.assertIn('id="settings-scraper-filter"', html)
        self.assertIn('data-settings-step="9"', html)
        self.assertIn("批量整理过滤词（可选）", html)
        self.assertIn('id="scraper_noise_phrases"', html)
        self.assertIn('id="scraper_standalone_noise_words"', html)
        self.assertIn("内置默认过滤词表始终生效", html)

    def test_settings_page_filter_section_has_info_button(self):
        """标题旁的信息按钮：说明与案例放进弹窗，而不是堆在设置页正文里。"""
        html = (ROOT / "templates/partials/pages/settings.html").read_text(encoding="utf-8")
        self.assertIn("settings-title-with-info", html)
        self.assertIn("showScraperFilterHelp()", html)

    def test_scraper_filter_help_modal_covers_usage_config_and_examples(self):
        script = (ROOT / "static/js/index.js").read_text(encoding="utf-8")
        self.assertIn("function showHelpHtml(", script)
        self.assertIn("body.textContent = normalized;", script)
        self.assertIn("const SCRAPER_FILTER_HELP_HTML", script)
        self.assertIn("window.showScraperFilterHelp = showScraperFilterHelp", script)
        for marker in (
            "用在哪里",
            "两类词的区别",
            "怎么配置",
            "案例（按上面的规则提取到的片名）",
            "什么时候需要加",
            "监狱星级餐厅",
            "我的中文老师",
            "单个词 50 字以内",
        ):
            self.assertIn(marker, script)
        help_modal = (ROOT / "templates/partials/modals/resource_import.html").read_text(encoding="utf-8")
        self.assertIn('id="help-modal-title"', help_modal)
        css = (ROOT / "static/css/index.css").read_text(encoding="utf-8")
        self.assertIn(".help-rich-example", css)
        self.assertIn("html.theme-day .help-rich-text", css)

    def test_help_examples_match_real_cleaning_behavior(self):
        """弹窗里写的案例必须和真实行为一致，避免说明变成过期文案。"""
        builtin = {"scraper_noise_phrases": [], "scraper_standalone_noise_words": []}
        with mock.patch.object(scraper, "get_config", return_value=builtin):
            self.assertEqual(
                scraper._extract_scraper_title_candidates("监狱星级餐厅.国语音轨.2024.1080p.mkv"),
                ["监狱星级餐厅"],
            )
            self.assertEqual(
                scraper._extract_scraper_title_candidates("我的中文老师.2024.1080p.mkv"),
                ["我的中文老师"],
            )
        custom = {"scraper_noise_phrases": ["测试广告词"], "scraper_standalone_noise_words": ["测试"]}
        with mock.patch.object(scraper, "get_config", return_value=custom):
            self.assertEqual(
                scraper._extract_scraper_title_candidates("片名.测试广告词.2024.1080p.mkv"),
                ["片名"],
            )
            self.assertEqual(scraper._extract_scraper_title_candidates("测试尾缀.2024.mkv"), ["测试尾缀"])
            self.assertEqual(scraper._extract_scraper_title_candidates("测试.2024.mkv"), [])

    def test_settings_js_collects_keyword_lines(self):
        source = (ROOT / "static/js/modules/tabs/settings.js").read_text(encoding="utf-8")
        self.assertIn("function parseKeywordLines(", source)
        collect_source = source[source.index("function collectSettingsPayload("):source.index("function syncNotifyChannelUI(")]
        self.assertIn("cfg.scraper_noise_phrases = parseKeywordLines(", collect_source)
        self.assertIn("cfg.scraper_standalone_noise_words = parseKeywordLines(", collect_source)

    def test_boot_js_fills_array_settings_as_lines(self):
        source = (ROOT / "static/js/modules/app/boot.js").read_text(encoding="utf-8")
        fill_source = source[source.index("Object.keys(cfg).forEach(k => {"):source.index("applySensitiveConfigMeta(sensitiveMeta);")]
        self.assertIn("Array.isArray(cfg[k])", fill_source)
        self.assertIn("el.value = cfg[k].join('\\n')", fill_source)
