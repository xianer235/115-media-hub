import json
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "static/js/modules/resource/link-tags.js"
CORE_PATH = ROOT / "static/js/modules/resource/core.js"
SOURCE_MANAGER_PATH = ROOT / "static/js/modules/resource/source-manager.js"
CSS_PATH = ROOT / "static/css/index.css"
TEMPLATE_PATH = ROOT / "templates/index.html"


def run_link_tags(expression: str):
    if not MODULE_PATH.exists():
        raise AssertionError(f"资源标签模块尚未创建: {MODULE_PATH}")
    script = f"""
const fs = require('fs');
const vm = require('vm');
const context = {{ window: {{}} }};
vm.createContext(context);
vm.runInContext(fs.readFileSync({json.dumps(str(MODULE_PATH))}, 'utf8'), context);
const api = context.window.ResourceLinkTags;
const result = ({expression});
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


class ResourceLinkTagsRegistryTest(unittest.TestCase):
    def test_registry_contains_all_builtin_types_in_display_order(self):
        self.assertEqual(
            run_link_tags("api.list().map(item => item.type)"),
            [
                "115share",
                "quark",
                "guangya",
                "aliyun",
                "baidu",
                "xunlei",
                "uc",
                "123pan",
                "tianyi",
                "pikpak",
                "lanzou",
                "google_drive",
                "onedrive",
                "mega",
                "magnet",
                "ed2k",
                "link",
                "unknown",
            ],
        )

    def test_guangya_share_variants_are_display_only(self):
        urls = [
            "https://www.guangyapan.com/share/abc_123",
            "https://guangyapan.com/s/abc-123?pwd=1234",
            "https://www.guangyapan.com/link/abc123#code",
            "https://guangyapan.com/download/abc123",
        ]
        result = run_link_tags(
            f"{json.dumps(urls)}.map(link_url => ({{"
            "display: api.resolveDisplayType({ link_url }), "
            "action: api.resolveActionType({ link_url }), "
            "meta: api.getTagMeta(api.resolveDisplayType({ link_url }))"
            "}))"
        )

        self.assertEqual([item["display"] for item in result], ["guangya"] * 4)
        self.assertEqual([item["action"] for item in result], ["link"] * 4)
        self.assertTrue(all(item["meta"]["label"] == "光鸭网盘" for item in result))
        self.assertTrue(all(item["meta"]["category"] == "cloud" for item in result))
        self.assertTrue(all(item["meta"]["tone"] == "lime" for item in result))

    def test_guangya_non_share_urls_remain_direct_links(self):
        urls = [
            "https://guangyapan.com/",
            "https://guangyapan.com/s/",
            "https://guangyapan.com/folder/abc123",
            "https://guangyapan.com/s/abc123/extra",
            "https://guangyapan.com.example/s/abc123",
            "https://example.com/guangyapan.com/s/abc123",
        ]

        self.assertEqual(
            run_link_tags(
                f"{json.dumps(urls)}.map(link_url => api.resolveDisplayType({{ link_url }}))"
            ),
            ["link"] * len(urls),
        )

    def test_existing_cloud_url_patterns_keep_their_types(self):
        cases = [
            ["https://115.com/s/abc123", "115share"],
            ["https://pan.quark.cn/s/abc123", "quark"],
            ["https://www.aliyundrive.com/s/abc123", "aliyun"],
            ["https://pan.baidu.com/s/abc123", "baidu"],
            ["https://pan.xunlei.com/s/abc123", "xunlei"],
            ["https://drive.uc.cn/s/abc123", "uc"],
            ["https://www.123pan.com/s/abc-123.html", "123pan"],
            ["https://cloud.189.cn/t/abc123", "tianyi"],
            ["https://mypikpak.com/s/abc123", "pikpak"],
            ["https://www.lanzoui.com/abc123", "lanzou"],
            ["https://drive.google.com/file/d/abc123", "google_drive"],
            ["https://1drv.ms/u/s!abc123", "onedrive"],
            ["https://mega.nz/file/abc123", "mega"],
        ]

        self.assertEqual(
            run_link_tags(
                f"{json.dumps(cases)}.map(([link_url, expected]) => [api.detect(link_url), expected])"
            ),
            [[expected, expected] for _, expected in cases],
        )

    def test_protocol_and_generic_labels_are_localized(self):
        cases = [
            ["magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567", "magnet", "磁力"],
            ["ed2k://|file|movie.mkv|1024|0123456789abcdef0123456789abcdef|/", "ed2k", "电驴"],
            ["https://example.com/video.mkv", "link", "直链"],
            ["not-a-link", "unknown", "待识别"],
        ]
        result = run_link_tags(
            f"{json.dumps(cases)}.map(([link_url]) => {{ const type = api.resolveDisplayType({{ link_url }}); return [type, api.getTagMeta(type).label, api.resolveActionType({{ link_url }})]; }})"
        )

        self.assertEqual(
            result,
            [[type_name, label, type_name] for _, type_name, label in cases],
        )

    def test_specific_url_wins_over_stale_raw_type_and_old_guangya_is_preserved(self):
        result = run_link_tags(
            "({ "
            "specific: api.resolveDisplayType({ link_type: '115share', link_url: 'https://pan.quark.cn/s/abc123' }), "
            "oldDisplay: api.resolveDisplayType({ link_type: 'guangya', link_url: '' }), "
            "oldAction: api.resolveActionType({ link_type: 'guangya', link_url: '' }), "
            "missing: api.getTagMeta('future-cloud') "
            "})"
        )

        self.assertEqual(result["specific"], "quark")
        self.assertEqual(result["oldDisplay"], "guangya")
        self.assertEqual(result["oldAction"], "link")
        self.assertEqual(
            result["missing"],
            {
                "type": "unknown",
                "label": "待识别",
                "category": "unknown",
                "tone": "neutral",
                "actionType": "unknown",
                "order": 17,
            },
        )

    def test_summary_uses_display_types_and_registry_order_for_ties(self):
        items = [
            {"link_url": "https://guangyapan.com/s/one"},
            {"link_url": "https://guangyapan.com/share/two"},
            {"link_url": "https://example.com/file.mkv"},
        ]
        tied_items = [
            {"link_url": "https://pan.quark.cn/s/one"},
            {"link_url": "https://115.com/s/two"},
            {"link_url": "not-a-link"},
        ]
        result = run_link_tags(
            f"({{ normal: api.summarize({json.dumps(items)}, {{ latest_published_at: '2026-08-01' }}), tie: api.summarize({json.dumps(tied_items)}, {{}}) }})"
        )

        self.assertEqual(result["normal"]["primary_link_type"], "guangya")
        self.assertEqual(result["normal"]["dominant_link_types"], ["guangya", "link"])
        self.assertEqual(result["normal"]["link_type_counts"], {"guangya": 2, "link": 1})
        self.assertEqual(result["normal"]["latest_published_at"], "2026-08-01")
        self.assertEqual(result["tie"]["dominant_link_types"], ["115share", "quark", "unknown"])

    def test_summary_keeps_unknown_after_recognized_types_regardless_of_count(self):
        items = [
            {"link_url": "not-a-link"},
            {"link_url": "still-not-a-link"},
            {"link_url": "https://pan.quark.cn/s/abc123"},
        ]

        result = run_link_tags(f"api.summarize({json.dumps(items)}, {{}})")

        self.assertEqual(result["primary_link_type"], "quark")
        self.assertEqual(result["dominant_link_types"], ["quark", "unknown"])

    def test_summary_keeps_server_profile_when_items_are_not_loaded(self):
        fallback = {
            "primary_link_type": "quark",
            "dominant_link_types": ["quark", "115share"],
            "link_type_counts": {"quark": 4, "115share": 2},
            "latest_published_at": "2026-08-01",
        }

        self.assertEqual(
            run_link_tags(f"api.summarize([], {json.dumps(fallback)})"),
            fallback,
        )


class ResourceLinkTagsIntegrationTest(unittest.TestCase):
    def test_link_tag_module_loads_before_resource_core(self):
        html = TEMPLATE_PATH.read_text(encoding="utf-8")

        self.assertIn("/static/js/modules/resource/link-tags.js", html)
        self.assertLess(
            html.index("/static/js/modules/resource/link-tags.js"),
            html.index("/static/js/modules/resource/core.js"),
        )

    def test_resource_core_separates_action_and_display_types(self):
        source = CORE_PATH.read_text(encoding="utf-8")
        card_start = source.index("        function buildResourceCard(")
        card_end = source.index("\n        function ", card_start + 1)
        card_body = source[card_start:card_end]
        section_start = source.index("        function buildResourceSectionCard(")
        section_end = source.index("\n        function ", section_start + 1)
        section_body = source[section_start:section_end]

        self.assertIn("window.ResourceLinkTags.resolveActionType({ link_url: url })", source)
        self.assertIn("window.ResourceLinkTags.resolveActionType(item)", source)
        self.assertIn("const displayType = getResourceDisplayLinkType(item);", card_body)
        self.assertIn("getResourceDisplayLinkTypeBadgeClass(displayType)", card_body)
        self.assertIn("getResourceDisplayLinkTypeLabel(displayType)", card_body)
        self.assertIn("buildResourceDisplayProfile(sectionItems", section_body)
        self.assertIn("getResourceDisplayLinkTypeBadgeClass(primaryDisplayType)", section_body)

    def test_resource_core_exports_display_helpers_for_channel_manager(self):
        source = CORE_PATH.read_text(encoding="utf-8")
        export_start = source.index("        Object.assign(window, {")
        export_body = source[export_start:]

        for helper in (
            "buildResourceDisplayProfile",
            "getResourceDisplayLinkType",
            "getResourceDisplayLinkTypeBadgeClass",
            "getResourceDisplayLinkTypeLabel",
        ):
            self.assertIn(helper, export_body)

    def test_channel_manager_uses_display_profile_labels_and_badges(self):
        source = SOURCE_MANAGER_PATH.read_text(encoding="utf-8")
        profile_start = source.index("        function getResourceSourceProfileFromIndex(")
        profile_end = source.index("\n        function ", profile_start + 1)
        profile_body = source[profile_start:profile_end]
        badge_start = source.index("        function renderResourceSourceTypeBadges(")
        badge_end = source.index("\n        function ", badge_start + 1)
        badge_body = source[badge_start:badge_end]

        self.assertIn("buildResourceDisplayProfile(sectionItems, fallbackProfile)", profile_body)
        self.assertIn("getResourceDisplayLinkTypeBadgeClass(type)", badge_body)
        self.assertIn("getResourceDisplayLinkTypeLabel(type)", badge_body)
        self.assertNotIn("resource-source-manager-type-badge", badge_body)
        self.assertNotIn("getResourceLinkTypeLabel(", source)
        self.assertIn("window.ResourceLinkTags.getTagMeta(a[0]).order", source)


class ResourceLinkTagPaletteTest(unittest.TestCase):
    TONES = (
        "blue",
        "violet",
        "lime",
        "orange",
        "sky",
        "indigo",
        "amber",
        "emerald",
        "rose",
        "fuchsia",
        "teal",
        "green",
        "cyan",
        "red",
        "yellow",
        "pink",
        "slate",
        "neutral",
    )

    @staticmethod
    def _relative_luminance(color: str) -> float:
        channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [
            value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
            for value in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    @classmethod
    def _contrast_ratio(cls, first: str, second: str) -> float:
        high, low = sorted(
            (cls._relative_luminance(first), cls._relative_luminance(second)),
            reverse=True,
        )
        return (high + 0.05) / (low + 0.05)

    @staticmethod
    def _selector_variables(css: str, selector: str):
        match = re.search(
            rf"(?ms)^\s*{re.escape(selector)}\s*\{{(?P<body>.*?)^\s*\}}",
            css,
        )
        if not match:
            return {}
        return {
            key: value.lower()
            for key, value in re.findall(
                r"--tag-(bg|text|border):\s*(#[0-9a-fA-F]{6})",
                match.group("body"),
            )
        }

    def test_palette_defines_all_day_and_night_tones(self):
        css = CSS_PATH.read_text(encoding="utf-8")

        self.assertRegex(css, r"(?m)^\s*\.resource-link-tag\s*\{")
        for tone in self.TONES:
            night = self._selector_variables(css, f".resource-link-tag--{tone}")
            day = self._selector_variables(css, f"html.theme-day .resource-link-tag--{tone}")
            self.assertEqual(set(night), {"bg", "text", "border"}, tone)
            self.assertEqual(set(day), {"bg", "text", "border"}, tone)
            self.assertGreaterEqual(self._contrast_ratio(night["bg"], night["text"]), 4.5, tone)
            self.assertGreaterEqual(self._contrast_ratio(day["bg"], day["text"]), 4.5, tone)

    def test_unknown_tone_uses_a_non_color_signal(self):
        css = CSS_PATH.read_text(encoding="utf-8")
        match = re.search(
            r"(?ms)^\s*\.resource-link-tag--neutral\s*\{(?P<body>.*?)^\s*\}",
            css,
        )

        self.assertIsNotNone(match)
        self.assertIn("border-style: dashed", match.group("body"))


if __name__ == "__main__":
    unittest.main()
