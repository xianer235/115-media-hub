from pathlib import Path
import re
import unittest


CSS_PATH = Path("/Users/xianer/Documents/code/115-media-hub/static/css/index.css")
JS_PATH = Path("/Users/xianer/Documents/code/115-media-hub/static/js/index.js")


def extract_media_block(css: str, max_width: int) -> str:
    marker = f"@media (max-width: {max_width}px)"
    start = css.index(marker)
    block_start = css.index("{", start)
    depth = 1
    cursor = block_start + 1
    while depth and cursor < len(css):
        if css[cursor] == "{":
            depth += 1
        elif css[cursor] == "}":
            depth -= 1
        cursor += 1
    return css[block_start + 1:cursor - 1]


def extract_media_block_by_marker(css: str, marker: str) -> str:
    start = css.index(marker)
    block_start = css.index("{", start)
    depth = 1
    cursor = block_start + 1
    while depth and cursor < len(css):
        if css[cursor] == "{":
            depth += 1
        elif css[cursor] == "}":
            depth -= 1
        cursor += 1
    return css[block_start + 1:cursor - 1]


class ResourceCardCssBreakpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")
        cls.js = JS_PATH.read_text(encoding="utf-8")

    def test_1120_breakpoint_keeps_preview_width_in_sync(self) -> None:
        block = extract_media_block(self.css, 1120)
        self.assertRegex(
            block,
            re.compile(
                r"\.resource-card\s*>\s*\.resource-card-preview-trigger\s*\{[^}]*width:\s*58px;",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            block,
            re.compile(
                r"\.resource-card\s+\.resource-poster,\s*"
                r"\.resource-card\s+\.resource-placeholder\s*\{"
                r"[^}]*width:\s*58px;[^}]*height:\s*78px;",
                re.DOTALL,
            ),
        )

    def test_860_breakpoint_keeps_preview_width_in_sync(self) -> None:
        block = extract_media_block(self.css, 860)
        self.assertRegex(
            block,
            re.compile(
                r"\.resource-card\s*>\s*\.resource-card-preview-trigger\s*\{[^}]*width:\s*56px;",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            block,
            re.compile(
                r"\.resource-card\s+\.resource-poster,\s*"
                r"\.resource-card\s+\.resource-placeholder\s*\{"
                r"[^}]*width:\s*56px;[^}]*height:\s*74px;",
                re.DOTALL,
            ),
        )

    def test_portrait_breakpoint_centers_resource_actions(self) -> None:
        block = extract_media_block_by_marker(
            self.css,
            "@media (max-width: 1120px) and (orientation: portrait)",
        )
        self.assertRegex(
            block,
            re.compile(
                r"\.resource-card-actions\s*\{"
                r"[^}]*justify-content:\s*center;[^}]*padding-left:\s*0;",
                re.DOTALL,
            ),
        )

    def test_shell_floating_surfaces_use_translucent_glass_fill(self) -> None:
        self.assertRegex(
            self.css,
            re.compile(
                r"--shell-floating-fill:\s*linear-gradient\(180deg,\s*"
                r"rgba\(18,\s*25,\s*37,\s*0\.58\),\s*rgba\(9,\s*15,\s*25,\s*0\.42\)\);",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.css,
            re.compile(
                r"\.shell-toolbar,\s*"
                r"\.shell-mobile-nav\s*\{"
                r"[^}]*background:\s*var\(--shell-floating-fill\);"
                r"[^}]*backdrop-filter:\s*blur\(34px\)\s*saturate\(190%\);",
                re.DOTALL,
            ),
        )

    def test_day_theme_toolbar_and_mobile_nav_stay_frosted(self) -> None:
        self.assertRegex(
            self.css,
            re.compile(
                r"html\.theme-day\s+\.shell-toolbar,\s*"
                r"html\.theme-day\s+\.shell-mobile-nav\s*\{"
                r"[^}]*rgba\(255,\s*255,\s*255,\s*0\.68\)"
                r"[^}]*rgba\(241,\s*247,\s*255,\s*0\.5\)"
                r"[^}]*box-shadow:\s*0\s+20px\s+40px\s+rgba\(111,\s*135,\s*166,\s*0\.12\);",
                re.DOTALL,
            ),
        )

    def test_portrait_log_scrollbars_tune_vertical_and_horizontal_sizes(self) -> None:
        block = extract_media_block_by_marker(
            self.css,
            "@media (max-width: 1120px) and (orientation: portrait)",
        )
        self.assertRegex(
            block,
            re.compile(
                r"#log-box::-webkit-scrollbar,\s*#monitor-log-box::-webkit-scrollbar,\s*#subscription-log-box::-webkit-scrollbar\s*\{"
                r"[^}]*width:\s*10px;[^}]*height:\s*4px;",
                re.DOTALL,
            ),
        )

    def test_portrait_log_task_divider_switches_to_stacked_layout(self) -> None:
        block = extract_media_block_by_marker(
            self.css,
            "@media (max-width: 1120px) and (orientation: portrait)",
        )
        self.assertRegex(
            block,
            re.compile(
                r"\.log-task-divider\s*\{"
                r"[^}]*flex-direction:\s*column;[^}]*align-items:\s*flex-start;",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            block,
            re.compile(
                r"\.log-task-divider-rule\s*\{[^}]*display:\s*none;",
                re.DOTALL,
            ),
        )

    def test_monitor_task_divider_html_is_structured_for_responsive_layout(self) -> None:
        self.assertRegex(
            self.js,
            re.compile(r"function formatMonitorTaskDividerHtml\(text\) \{", re.DOTALL),
        )
        self.assertRegex(
            self.js,
            re.compile(
                r"if \(level === 'task-divider'\) return formatMonitorTaskDividerHtml\(text\);",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.js,
            re.compile(
                r"log-task-divider-time.*log-task-divider-rule.*log-task-divider-label",
                re.DOTALL,
            ),
        )


if __name__ == "__main__":
    unittest.main()
