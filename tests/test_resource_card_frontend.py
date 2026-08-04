import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = ROOT / "static/js/modules/tabs/settings.js"
CSS_PATH = ROOT / "static/css/index.css"
CORE_PATH = ROOT / "static/js/modules/resource/core.js"
IMPORT_MODAL_PATH = ROOT / "static/js/modules/resource/import-modal.js"


def extract_css_block(source: str, marker: str) -> str:
    start = source.rfind(marker)
    if start < 0:
        raise AssertionError(f"CSS block not found: {marker}")
    brace_start = source.index("{", start)
    depth = 0
    for index in range(brace_start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[brace_start + 1:index]
    raise AssertionError(f"CSS block is not closed: {marker}")


class ResourceCardFrontendTest(unittest.TestCase):
    def test_only_registry_declared_ed2k_items_can_open_offline_import(self):
        core = CORE_PATH.read_text(encoding="utf-8")
        modal = IMPORT_MODAL_PATH.read_text(encoding="utf-8")

        self.assertIn("function getResourceImportMode(item)", core)
        self.assertIn("getResourceImportMode(item) === 'ed2k-direct'", core)
        self.assertIn("getResourceImportMode(item) === 'ed2k-page'", core)
        self.assertNotIn("linkType === 'link' && /^https?:\\/\\//i.test(linkUrl)", core)
        self.assertIn("return '暂不支持下载';", core)
        self.assertIn("const importMode = getResourceImportMode(item);", modal)
        self.assertIn("importMode === 'ed2k-direct'", modal)

    def test_settings_copy_names_both_supported_offline_link_types(self):
        source = SETTINGS_PATH.read_text(encoding="utf-8")

        self.assertIn(">离线下载网盘</span>", source)
        self.assertIn(">磁力、电驴链接仅支持</span>", source)
        self.assertNotIn(">磁力下载网盘</span>", source)
        self.assertNotIn(">固定离线下载</span>", source)

    def test_phone_portrait_actions_span_card_in_one_four_column_row(self):
        css = CSS_PATH.read_text(encoding="utf-8")
        theme_day_start = css.index("html.theme-day {\n            --bg: #eef4fb")
        standard_mobile_start = css.rfind(
            "@media (max-width: 640px) {",
            0,
            theme_day_start,
        )
        portrait_marker = "@media (max-width: 640px) and (orientation: portrait)"
        self.assertGreater(css.rfind(portrait_marker), standard_mobile_start)
        mobile_portrait = extract_css_block(
            css,
            portrait_marker,
        )

        self.assertRegex(
            mobile_portrait,
            re.compile(
                r"\.resource-card\s*\{[^}]*grid-template-areas:\s*"
                r'"poster main"\s*"actions actions";',
                re.DOTALL,
            ),
        )
        self.assertRegex(
            mobile_portrait,
            re.compile(
                r"\.resource-card-actions\s*\{[^}]*display:\s*grid;[^}]*"
                r"grid-template-columns:\s*repeat\(4,\s*minmax\(0,\s*1fr\)\);"
                r"[^}]*width:\s*100%;",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            mobile_portrait,
            re.compile(
                r"\.resource-card-actions button,\s*"
                r"\.resource-card-actions a\s*\{[^}]*min-width:\s*0;[^}]*"
                r"padding-inline:\s*0\.35rem;",
                re.DOTALL,
            ),
        )


if __name__ == "__main__":
    unittest.main()
