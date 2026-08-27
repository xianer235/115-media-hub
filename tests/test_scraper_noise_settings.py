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
        self.assertIn("9. 批量整理过滤词", html)
        self.assertIn('id="scraper_noise_phrases"', html)
        self.assertIn('id="scraper_standalone_noise_words"', html)
        self.assertIn("内置默认过滤词表始终生效", html)

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
