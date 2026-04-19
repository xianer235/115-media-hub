import ast
import importlib.util
from pathlib import Path
import re
import sys
import types
import unittest

CSS_PATH = Path("/Users/xianer/Documents/code/115-media-hub/static/css/index.css")
JS_PATH = Path("/Users/xianer/Documents/code/115-media-hub/static/js/index.js")
TEMPLATE_PATH = Path("/Users/xianer/Documents/code/115-media-hub/templates/index.html")
SUBSCRIPTION_SERVICE_PATH = Path("/Users/xianer/Documents/code/115-media-hub/app/services/subscription.py")
TREE_SERVICE_PATH = Path("/Users/xianer/Documents/code/115-media-hub/app/services/tree.py")
CORE_PATH = Path("/Users/xianer/Documents/code/115-media-hub/app/core.py")


def _install_fastapi_stubs() -> None:
    if "fastapi" in sys.modules:
        return

    fastapi_module = types.ModuleType("fastapi")

    class _FakeFastAPI:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def add_middleware(self, *args, **kwargs) -> None:
            return None

        def mount(self, *args, **kwargs) -> None:
            return None

    fastapi_module.FastAPI = _FakeFastAPI
    fastapi_module.BackgroundTasks = type("BackgroundTasks", (), {})
    fastapi_module.Request = type("Request", (), {})
    sys.modules["fastapi"] = fastapi_module

    fastapi_responses = types.ModuleType("fastapi.responses")
    for name in (
        "FileResponse",
        "HTMLResponse",
        "JSONResponse",
        "RedirectResponse",
        "Response",
        "StreamingResponse",
    ):
        setattr(fastapi_responses, name, type(name, (), {}))
    sys.modules["fastapi.responses"] = fastapi_responses

    fastapi_staticfiles = types.ModuleType("fastapi.staticfiles")
    fastapi_staticfiles.StaticFiles = type("StaticFiles", (), {"__init__": lambda self, *args, **kwargs: None})
    sys.modules["fastapi.staticfiles"] = fastapi_staticfiles

    starlette_sessions = types.ModuleType("starlette.middleware.sessions")
    starlette_sessions.SessionMiddleware = type("SessionMiddleware", (), {})
    sys.modules["starlette.middleware.sessions"] = starlette_sessions


def _load_core_helpers():
    _install_fastapi_stubs()
    spec = importlib.util.spec_from_file_location("test_core_module", CORE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load core.py for tests")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.normalize_config, module.normalize_resource_source


normalize_config, normalize_resource_source = _load_core_helpers()


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
        cls.template_source = TEMPLATE_PATH.read_text(encoding="utf-8")
        cls.subscription_service = SUBSCRIPTION_SERVICE_PATH.read_text(encoding="utf-8")
        cls.tree_service = TREE_SERVICE_PATH.read_text(encoding="utf-8")
        cls.core_source = CORE_PATH.read_text(encoding="utf-8")

    def infer_log_level(self, text: str) -> str:
        module = ast.parse(self.core_source)
        target = None
        for node in module.body:
            if isinstance(node, ast.FunctionDef) and node.name == "infer_log_level_from_text":
                target = node
                break
        if target is None:
            self.fail("infer_log_level_from_text not found in core.py")
        isolated = ast.Module(body=[target], type_ignores=[])
        ast.fix_missing_locations(isolated)
        namespace = {}
        exec(compile(isolated, str(CORE_PATH), "exec"), namespace)
        return namespace["infer_log_level_from_text"](text)

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

    def test_860_breakpoint_uses_compact_channel_action_alignment(self) -> None:
        block = extract_media_block(self.css, 860)
        self.assertRegex(
            block,
            re.compile(
                r"\.resource-section-actions\s*\{"
                r"[^}]*justify-content:\s*flex-start;"
                r"[^}]*flex-wrap:\s*wrap;",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            block,
            re.compile(
                r"\.resource-section-toggle\s*\{[^}]*margin-left:\s*auto;",
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
                r"rgba\(18,\s*25,\s*37,\s*0\.68\),\s*rgba\(9,\s*15,\s*25,\s*0\.56\)\);",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.css,
            re.compile(
                r"--shell-glass-fill:\s*linear-gradient\(180deg,\s*"
                r"rgba\(18,\s*24,\s*35,\s*0\.9\),\s*rgba\(10,\s*16,\s*26,\s*0\.84\)\);",
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
                r"html\.theme-day\s+\.shell-rail,\s*"
                r"html\.theme-day\s+\.shell-toolbar,\s*"
                r"html\.theme-day\s+\.shell-mobile-nav,\s*"
                r"html\.theme-day\s+\.shell-more-menu\s*\{"
                r"[^}]*rgba\(255,\s*255,\s*255,\s*0\.985\)"
                r"[^}]*rgba\(241,\s*247,\s*255,\s*0\.94\)",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.css,
            re.compile(
                r"html\.theme-day\s+\.shell-toolbar,\s*"
                r"html\.theme-day\s+\.shell-mobile-nav\s*\{"
                r"[^}]*rgba\(255,\s*255,\s*255,\s*0\.84\)"
                r"[^}]*rgba\(241,\s*247,\s*255,\s*0\.72\)"
                r"[^}]*box-shadow:\s*0\s+20px\s+40px\s+rgba\(111,\s*135,\s*166,\s*0\.12\);",
                re.DOTALL,
            ),
        )

    def test_desktop_footer_spacing_is_tighter(self) -> None:
        self.assertRegex(
            self.css,
            re.compile(
                r"\.shell-workspace\s*\{[^}]*padding:\s*18px\s+0\s+28px;",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.css,
            re.compile(
                r"\.footer-text\s*\{[^}]*padding:\s*1\.4rem\s+0\s+1\.2rem\s+0;",
                re.DOTALL,
            ),
        )

    def test_1180_breakpoint_keeps_footer_closer_to_content(self) -> None:
        block = extract_media_block_by_marker(
            self.css,
            "@media (max-width: 1180px) {\n            .app-shell,\n            .app-shell[data-shell-expanded=\"true\"] {",
        )
        self.assertRegex(
            block,
            re.compile(
                r"\.shell-workspace\s*\{"
                r"[^}]*padding-top:\s*12px;[^}]*padding-bottom:\s*32px;",
                re.DOTALL,
            ),
        )

    def test_1024_breakpoint_keeps_footer_text_padding_tight(self) -> None:
        block = extract_media_block(self.css, 1024)
        self.assertRegex(
            block,
            re.compile(
                r"\.footer-text\s*\{[^}]*padding:\s*1rem\s+0\s+1rem;",
                re.DOTALL,
            ),
        )

    def test_subscription_footer_removed_and_monitor_footer_sticky_only_in_mobile_fullscreen_mode(self) -> None:
        compact_block = extract_media_block_by_marker(
            self.css,
            "@media (max-width: 768px) {\n            body { font-size: 15px; }",
        )
        self.assertNotRegex(
            compact_block,
            re.compile(r"#monitor-modal-footer\s*\{[^}]*position:\s*sticky;", re.DOTALL),
        )
        self.assertNotRegex(
            compact_block,
            re.compile(r"#subscription-modal-footer\s*\{", re.DOTALL),
        )

        mobile_block = extract_media_block_by_marker(
            self.css,
            "@media (max-width: 640px) {\n            body { font-size: 16px; }",
        )
        self.assertRegex(
            mobile_block,
            re.compile(r"#monitor-modal-footer\s*\{[^}]*position:\s*sticky;", re.DOTALL),
        )
        self.assertNotRegex(
            mobile_block,
            re.compile(r"#subscription-modal-footer\s*\{", re.DOTALL),
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
            re.compile(r"\[\-—━\]\{3,\}", re.DOTALL),
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

    def test_task_divider_supports_result_tone_variants(self) -> None:
        self.assertRegex(
            self.css,
            re.compile(
                r"\.log-task-divider\.log-task-divider-start\s*\{"
                r"[^}]*--log-task-divider-text:",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.css,
            re.compile(
                r"\.log-task-divider\.log-task-divider-success\s*\{"
                r"[^}]*--log-task-divider-text:",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.css,
            re.compile(
                r"\.log-task-divider\.log-task-divider-warn\s*\{"
                r"[^}]*--log-task-divider-text:",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.css,
            re.compile(
                r"\.log-task-divider\.log-task-divider-error\s*\{"
                r"[^}]*--log-task-divider-text:",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.css,
            re.compile(
                r"html\.theme-day\s+\.log-task-divider\.log-task-divider-success\s*\{"
                r"[^}]*--log-task-divider-text:\s*var\(--success\);",
                re.DOTALL,
            ),
        )

    def test_task_divider_tone_class_is_inferred_from_result_text(self) -> None:
        self.assertRegex(
            self.js,
            re.compile(r"function getTaskDividerTone\(label\) \{", re.DOTALL),
        )
        self.assertRegex(
            self.js,
            re.compile(r"/\(任务开始\|订阅开始\)/", re.DOTALL),
        )
        self.assertRegex(
            self.js,
            re.compile(r"/\(执行成功\|订阅成功\|已完成\|完成\)/", re.DOTALL),
        )
        self.assertRegex(
            self.js,
            re.compile(r"/\(已中断\|中断\|取消\)/", re.DOTALL),
        )
        self.assertRegex(
            self.js,
            re.compile(r"/\(执行失败\|失败\|异常\|错误\)/", re.DOTALL),
        )
        self.assertRegex(
            self.js,
            re.compile(
                r"return \['log-task-divider',\s*tone \? `log-task-divider-\$\{tone\}` : ''\]\.filter\(Boolean\)\.join\(' '\);",
                re.DOTALL,
            ),
        )

    def test_subscription_footer_includes_terminal_status_text(self) -> None:
        self.assertRegex(
            self.subscription_service,
            re.compile(
                r"tail_status_label\s*=\s*\{"
                r"[^}]*'completed':\s*'执行成功'"
                r"[^}]*'cancelled':\s*'已中断'"
                r"[^}]*'failed':\s*'执行失败'",
                re.DOTALL,
            ),
        )

    def test_summary_log_inference_keeps_failed_dir_metrics_as_info(self) -> None:
        self.assertEqual(
            self.infer_log_level("04-18 00:15:48 生成汇总: 新增/更新 0 | 跳过文件 89 | 跳过目录 0 | 失败目录 0"),
            "info",
        )
        self.assertRegex(
            self.subscription_service,
            re.compile(
                r"━━━━━━━━━━【订阅结束 \| \{task_name\} \| \{tail_status_label or '已结束'\}】━━━━━━━━━━",
                re.DOTALL,
            ),
        )

    def test_subscription_tasks_use_single_toggle_run_button(self) -> None:
        self.assertRegex(
            self.js,
            re.compile(r"data-subscription-action=\"toggle-run\"", re.DOTALL),
        )
        self.assertNotRegex(
            self.js,
            re.compile(r"data-subscription-action=\"start\"", re.DOTALL),
        )
        self.assertNotRegex(
            self.js,
            re.compile(r"data-subscription-action=\"stop\"", re.DOTALL),
        )
        self.assertRegex(
            self.js,
            re.compile(r"const toggleRunLabel = running\s*\?\s*'中断'\s*:\s*\(queued\s*\?\s*'排队中'\s*:\s*'运行'\);", re.DOTALL),
        )
        self.assertRegex(
            self.js,
            re.compile(r"const toggleRunAction = running\s*\?\s*'stop'\s*:\s*'start';", re.DOTALL),
        )

    def test_subscription_task_click_handler_routes_toggle_run(self) -> None:
        self.assertRegex(
            self.js,
            re.compile(
                r"if \(action === 'toggle-run'\) \{\s*"
                r"if \(btn\.dataset\.subscriptionRunAction === 'stop'\) await stopSubscriptionTask\(name\);\s*"
                r"else await startSubscriptionTask\(name\);\s*"
                r"return;\s*\}",
                re.DOTALL,
            ),
        )

    def test_subscription_tv_actions_fit_single_row_at_compact_breakpoint(self) -> None:
        block = extract_media_block_by_marker(
            self.css,
            "@media (orientation: portrait)",
        )
        self.assertRegex(
            block,
            re.compile(
                r"#page-subscription\s+\.subscription-task-actions\.subscription-task-actions-tv,\s*"
                r"#subscription-task-list\s+\.grid\.grid-cols-2\.sm\\:grid-cols-3\.md\\:grid-cols-5\s*\{"
                r"[^}]*grid-template-columns:\s*repeat\(5,\s*minmax\(0,\s*1fr\)\)\s*!important;",
                re.DOTALL,
            ),
        )

    def test_main_logs_use_structured_items_and_shared_log_renderer(self) -> None:
        self.assertRegex(
            self.core_source,
            re.compile(
                r'task_status\s*=\s*\{'
                r'[^}]*"logs":\s*\[\{"text":\s*"系统已就绪",\s*"level":\s*"info"\}\]',
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.core_source,
            re.compile(
                r'task_status\["logs"\]\s*=\s*\[\s*\{"text":\s*line,\s*"level":\s*infer_log_level_from_text\(line\)\}\s*for line in main_lines\s*\]',
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.js,
            re.compile(
                r"const logSignature = buildLogSignature\(logs,\s*\(item\)\s*=>\s*`\$\{item\?\.level \|\| 'info'\}:\$\{item\?\.text \|\| ''\}`\);",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.js,
            re.compile(
                r"logBox\.innerHTML = logs\.map\(item => `<div class=\"\$\{getLogEntryClass\(item\)\}\">\$\{formatMonitorLogHtml\(item\)\}</div>`\)\.join\(''\);",
                re.DOTALL,
            ),
        )

    def test_tree_task_logs_emit_task_divider_headers_and_footers(self) -> None:
        self.assertRegex(
            self.tree_service,
            re.compile(
                r"━━━━━━━━━━【任务开始 \| 目录树 \| 源 \{len\(trees\)\} 个 \| 模式 \{cfg\.get\('sync_mode', 'incremental'\)\} \| MD5校验 \{'开' if check_hash_enabled else '关'\}】━━━━━━━━━━",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.tree_service,
            re.compile(
                r"━━━━━━━━━━【任务结束 \| 目录树 \| MD5 校验命中】━━━━━━━━━━",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.tree_service,
            re.compile(
                r"━━━━━━━━━━【任务结束 \| 目录树 \| 执行成功】━━━━━━━━━━",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.tree_service,
            re.compile(
                r"━━━━━━━━━━【任务结束 \| 目录树 \| 执行失败】━━━━━━━━━━",
                re.DOTALL,
            ),
        )

    def test_theme_toggle_uses_icon_only_markup(self) -> None:
        self.assertRegex(
            self.template_source,
            re.compile(
                r"<button[^>]*id=\"theme-toggle\"[^>]*aria-label=\"切换夜间/日间模式\"[^>]*title=\"切换夜间/日间模式\"[^>]*>"
                r"\s*<span class=\"theme-toggle-icon\" aria-hidden=\"true\"></span>\s*</button>",
                re.DOTALL,
            ),
        )
        self.assertNotRegex(
            self.template_source,
            re.compile(
                r"<button[^>]*id=\"theme-toggle\"[^>]*>\s*(?:日间|夜间)\s*</button>",
                re.DOTALL,
            ),
        )

    def test_theme_toggle_css_uses_compact_icon_button_sizing(self) -> None:
        self.assertRegex(
            self.css,
            re.compile(
                r"#theme-toggle\.nav-action-btn\s*\{"
                r"[^}]*width:\s*40px;[^}]*min-width:\s*40px;[^}]*padding:\s*0;",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.css,
            re.compile(
                r"\.theme-toggle-icon\s*\{"
                r"[^}]*display:\s*inline-flex;[^}]*align-items:\s*center;[^}]*justify-content:\s*center;"
                r"[^}]*width:\s*18px;[^}]*height:\s*18px;",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.css,
            re.compile(
                r"\.theme-toggle-icon\s+svg\s*\{"
                r"[^}]*width:\s*18px;[^}]*height:\s*18px;",
                re.DOTALL,
            ),
        )

    def test_theme_toggle_js_updates_icon_and_accessibility_copy(self) -> None:
        self.assertRegex(
            self.js,
            re.compile(r"const THEME_DAY_ICON\s*=\s*`", re.DOTALL),
        )
        self.assertRegex(
            self.js,
            re.compile(r"const THEME_NIGHT_ICON\s*=\s*`", re.DOTALL),
        )
        self.assertRegex(
            self.js,
            re.compile(r"function updateThemeToggleButton\(isDay\) \{", re.DOTALL),
        )
        self.assertRegex(
            self.js,
            re.compile(r"btn\.querySelector\('\.theme-toggle-icon'\)", re.DOTALL),
        )
        self.assertRegex(
            self.js,
            re.compile(
                r"const label = isDay\s*\?\s*'当前为日间模式，点击切换为夜间模式'\s*:\s*'当前为夜间模式，点击切换为日间模式';",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.js,
            re.compile(r"btn\.setAttribute\('aria-label',\s*label\);", re.DOTALL),
        )
        self.assertRegex(
            self.js,
            re.compile(r"btn\.setAttribute\('title',\s*label\);", re.DOTALL),
        )
        self.assertRegex(
            self.js,
            re.compile(r"icon\.innerHTML = isDay \? THEME_DAY_ICON : THEME_NIGHT_ICON;", re.DOTALL),
        )
        self.assertNotRegex(
            self.js,
            re.compile(r"btn\.textContent = isDay \? '日间' : '夜间';", re.DOTALL),
        )

    def test_portrait_resource_job_modal_keeps_actions_in_top_right(self) -> None:
        block = extract_media_block_by_marker(
            self.css,
            "@media (max-width: 640px) {\n            body { font-size: 16px; }",
        )
        self.assertRegex(
            block,
            re.compile(
                r"\.resource-job-modal-header\s*\{"
                r"[^}]*flex-direction:\s*row;[^}]*justify-content:\s*space-between;",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            block,
            re.compile(
                r"\.resource-job-modal-actions\s*\{"
                r"[^}]*width:\s*auto;[^}]*flex-wrap:\s*nowrap;[^}]*justify-content:\s*flex-end;[^}]*align-self:\s*flex-start;",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            block,
            re.compile(
                r"\.resource-job-clear-dropdown\s*\{"
                r"[^}]*left:\s*auto;[^}]*right:\s*0;",
                re.DOTALL,
            ),
        )

    def test_resource_job_modal_removes_live_summary_copy(self) -> None:
        self.assertNotRegex(
            self.template_source,
            re.compile(r"id=\"resource-job-modal-summary\"", re.DOTALL),
        )
        self.assertNotRegex(
            self.js,
            re.compile(r"document\.getElementById\('resource-job-modal-summary'\)", re.DOTALL),
        )
        self.assertNotRegex(
            self.js,
            re.compile(r"最近 \$\{counts\.total\} 条任务，处理中 \$\{counts\.active\} 条，已完成 \$\{counts\.completed\} 条", re.DOTALL),
        )

    def test_day_theme_resource_job_meta_chips_use_light_surface_treatment(self) -> None:
        self.assertRegex(
            self.css,
            re.compile(
                r"html\.theme-day\s+\.resource-job-meta-chip\s*\{"
                r"[^}]*background:\s*rgba\(248,\s*250,\s*252,\s*0\.96\);"
                r"[^}]*border-color:\s*rgba\(191,\s*219,\s*254,\s*0\.9\);"
                r"[^}]*color:\s*#334155;",
                re.DOTALL,
            ),
        )

    def test_subscription_log_header_removes_helper_copy(self) -> None:
        self.assertNotRegex(
            self.template_source,
            re.compile(r"匹配评分、任务创建和追更状态都会记录在这里", re.DOTALL),
        )

    def test_portrait_resource_search_actions_use_two_column_grid(self) -> None:
        block = extract_media_block_by_marker(
            self.css,
            "@media (max-width: 1120px) and (orientation: portrait)",
        )
        self.assertRegex(
            block,
            re.compile(
                r"\.resource-search-controls\s*\{"
                r"[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\);",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            block,
            re.compile(
                r"\.resource-search-input-shell\s*\{"
                r"[^}]*grid-column:\s*1\s*/\s*-1;",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            block,
            re.compile(
                r"\.resource-search-btn\s*\{"
                r"[^}]*width:\s*100%;",
                re.DOTALL,
            ),
        )

    def test_portrait_resource_section_actions_use_compact_grid_layout(self) -> None:
        block = extract_media_block_by_marker(
            self.css,
            "@media (max-width: 1120px) and (orientation: portrait)",
        )
        self.assertRegex(
            block,
            re.compile(
                r"\.resource-section-actions\s*\{"
                r"[^}]*display:\s*grid;"
                r"[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)\s*auto;"
                r"[^}]*justify-content:\s*initial;",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            block,
            re.compile(
                r"\.resource-section-manage-btn,\s*\.resource-section-link\s*\{"
                r"[^}]*width:\s*100%;[^}]*min-width:\s*0;",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            block,
            re.compile(
                r"\.resource-section-toggle\s*\{[^}]*justify-self:\s*end;",
                re.DOTALL,
            ),
        )

    def test_resource_back_top_button_uses_arrow_glyph(self) -> None:
        self.assertRegex(
            self.template_source,
            re.compile(
                r"<button id=\"resource-back-top-btn\"[^>]*aria-label=\"回到资源页顶部\"[^>]*>\s*↑\s*</button>",
                re.DOTALL,
            ),
        )
        self.assertNotRegex(
            self.template_source,
            re.compile(
                r"<button id=\"resource-back-top-btn\"[^>]*>\s*回到顶部\s*</button>",
                re.DOTALL,
            ),
        )

    def test_mobile_resource_back_top_button_avoids_bottom_nav(self) -> None:
        block = extract_media_block_by_marker(
            self.css,
            "@media (max-width: 767px)",
        )
        self.assertRegex(
            block,
            re.compile(
                r"\.resource-back-top-btn\s*\{"
                r"[^}]*bottom:\s*calc\(env\(safe-area-inset-bottom\)\s*\+\s*6\.85rem\);"
                r"[^}]*z-index:\s*49;",
                re.DOTALL,
            ),
        )

    def test_switch_tab_tracks_scroll_position_per_module(self) -> None:
        self.assertRegex(
            self.js,
            re.compile(
                r"const\s+moduleScrollTopState\s*=\s*\{"
                r"[^}]*resource:\s*0,"
                r"[^}]*subscription:\s*0,"
                r"[^}]*monitor:\s*0,"
                r"[^}]*task:\s*0,"
                r"[^}]*settings:\s*0,"
                r"[^}]*about:\s*0",
                re.DOTALL,
            ),
        )

    def test_switch_tab_restores_scroll_position_when_switching_modules(self) -> None:
        self.assertRegex(
            self.js,
            re.compile(
                r"async function switchTab\(tab\)\s*\{"
                r"[\s\S]*?const prevTab = currentTab;"
                r"[\s\S]*?moduleScrollTopState\[prevTab\]\s*=\s*Math\.max\(0,\s*window\.scrollY\s*\|\|\s*window\.pageYOffset\s*\|\|\s*0\);"
                r"[\s\S]*?const targetScrollTop = Math\.max\(0,\s*Number\(moduleScrollTopState\[nextTab\]\s*\|\|\s*0\)\);"
                r"[\s\S]*?window\.scrollTo\(\s*0,\s*targetScrollTop\s*\);",
                re.DOTALL,
            ),
        )

    def test_resource_share_browser_uses_paged_requests(self) -> None:
        self.assertRegex(
            self.js,
            re.compile(
                r"params\.set\('paged',\s*'1'\);"
                r"[\s\S]*?params\.set\('limit',\s*String\(normalizedLimit\)\);",
                re.DOTALL,
            ),
        )
        self.assertNotRegex(
            self.js,
            re.compile(r"params\.set\('folders_only',\s*'1'\);", re.DOTALL),
        )
        self.assertRegex(
            self.js,
            re.compile(
                r"body:\s*JSON\.stringify\(\{"
                r"[\s\S]*?paged:\s*(?:true|\!\!paged),"
                r"[\s\S]*?offset:\s*normalizedOffset,"
                r"[\s\S]*?limit:\s*normalizedLimit",
                re.DOTALL,
            ),
        )

    def test_resource_share_browser_exposes_load_more_folder_action(self) -> None:
        self.assertRegex(
            self.js,
            re.compile(r"data-resource-share-action=\"load-more\"", re.DOTALL),
        )
        self.assertRegex(
            self.js,
            re.compile(
                r"if \(action === 'load-more'\)\s*\{\s*await loadMoreResourceShareCurrentFolder\(\);\s*\}",
                re.DOTALL,
            ),
        )

    def test_resource_share_submit_requires_selection_when_any_options_exist(self) -> None:
        self.assertRegex(
            self.js,
            re.compile(
                r"const hasLoadedShareSelectableOption = Object\.keys\(resourceShareEntryIndex \|\| \{\}\)\.length > 0;"
                r"[\s\S]*?!selectionState\.selected_ids\.length && hasLoadedShareSelectableOption\)",
                re.DOTALL,
            ),
        )

    def test_subscription_share_folder_browser_uses_paged_requests(self) -> None:
        self.assertRegex(
            self.js,
            re.compile(
                r"async function fetchSubscriptionShareFolderData\("
                r"[\s\S]*?body:\s*JSON\.stringify\(\{"
                r"[\s\S]*?paged:\s*(?:true|\!\!paged),"
                r"[\s\S]*?offset:\s*normalizedOffset,"
                r"[\s\S]*?limit:\s*normalizedLimit,",
                re.DOTALL,
            ),
        )

    def test_subscription_share_folder_browser_lists_current_level_entries(self) -> None:
        self.assertNotRegex(
            self.js,
            re.compile(
                r"const folders = getCurrentSubscriptionShareFolderEntries\(\)\.filter\(entry => !!entry\?\.is_dir\);",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.js,
            re.compile(
                r"const currentEntries = getCurrentSubscriptionShareFolderEntries\(\);"
                r"[\s\S]*?currentEntries\.map\(entry => buildResourceEntryRow\(entry,\s*\{"
                r"[\s\S]*?showOpenButton:\s*true,"
                r"[\s\S]*?openActionPrefix:\s*'subscription-share-folder',",
                re.DOTALL,
            ),
        )

    def test_subscription_share_folder_browser_exposes_load_more_action(self) -> None:
        self.assertRegex(
            self.js,
            re.compile(r"data-subscription-share-folder-action=\"load-more\"", re.DOTALL),
        )
        self.assertRegex(
            self.js,
            re.compile(
                r"if \(action === 'load-more'\)\s*\{\s*await loadMoreSubscriptionShareCurrentFolder\(\);\s*\}",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.js,
            re.compile(
                r"await loadSubscriptionShareFolderBranch\(branchId,\s*\{\s*append:\s*true\s*\}\);",
                re.DOTALL,
            ),
        )

    def test_narrow_screen_monitor_footer_keeps_two_columns_without_sticky(self) -> None:
        block = extract_media_block_by_marker(
            self.css,
            "@media (max-width: 768px) {\n            body { font-size: 15px; }",
        )
        self.assertRegex(
            block,
            re.compile(
                r"#monitor-modal-footer\s*\{"
                r"[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\);"
                r"[^}]*padding-bottom:\s*0\.78rem;",
                re.DOTALL,
            ),
        )
        self.assertNotRegex(
            block,
            re.compile(r"#monitor-modal-footer\s*\{[^}]*position:\s*sticky;", re.DOTALL),
        )
        self.assertNotRegex(
            block,
            re.compile(r"#subscription-modal-footer\s*\{", re.DOTALL),
        )

    def test_mobile_resource_import_footer_uses_dedicated_sticky_layout(self) -> None:
        block = extract_media_block_by_marker(
            self.css,
            "@media (max-width: 640px) {\n            body { font-size: 16px; }",
        )
        self.assertRegex(
            block,
            re.compile(
                r"#resource-import-footer\s*\{"
                r"[^}]*position:\s*sticky;"
                r"[^}]*bottom:\s*0;"
                r"[^}]*z-index:\s*16;"
                r"[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\);",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.css,
            re.compile(
                r"\.resource-import-footer-shell\s*\{"
                r"[^}]*position:\s*relative;"
                r"[^}]*isolation:\s*isolate;"
                r"[^}]*overflow:\s*hidden;"
                r"[^}]*background:\s*transparent;",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.css,
            re.compile(
                r"\.resource-import-footer-shell::before\s*\{"
                r"[^}]*border:\s*1px\s+solid\s+var\(--modal-footer-glass-stroke\);"
                r"[^}]*background:[^;]*var\(--modal-footer-glass-fill\);"
                r"[^}]*backdrop-filter:\s*blur\(46px\)\s*saturate\(220%\);",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            block,
            re.compile(
                r"#resource-import-footer\s+button\s*\{"
                r"[^}]*width:\s*100%;",
                re.DOTALL,
            ),
        )

    def test_mobile_resource_import_footer_uses_dedicated_glass_panel(self) -> None:
        self.assertRegex(
            self.css,
            re.compile(
                r"#resource-import-footer::before\s*\{"
                r"[^}]*background:[^;]*var\(--modal-footer-glass-fill\);"
                r"[^}]*backdrop-filter:\s*blur\(20px\)\s*saturate\(170%\);",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.css,
            re.compile(
                r"html\.theme-day\s*\{"
                r"[^}]*--modal-footer-glass-fill:\s*linear-gradient\(180deg,\s*rgba\(255,\s*255,\s*255,\s*0\.58\),\s*rgba\(237,\s*244,\s*255,\s*0\.4\)\);",
                re.DOTALL,
            ),
        )

    def test_resource_modal_layout_keeps_dedicated_footer_classes_when_toggling_columns(self) -> None:
        self.assertRegex(
            self.js,
            re.compile(
                r"footer\.className\s*=\s*showPrimaryAction\s*\?"
                r"\s*'resource-import-footer-shell grid grid-cols-1 md:grid-cols-2 gap-3 pt-2'"
                r"\s*:\s*'resource-import-footer-shell grid grid-cols-1 gap-3 pt-2';",
                re.DOTALL,
            ),
        )

    def test_subscription_modal_body_owns_scrollbar(self) -> None:
        self.assertRegex(
            self.css,
            re.compile(
                r"\.subscription-modal-shell\s*\{"
                r"[^}]*display:\s*flex;"
                r"[^}]*flex-direction:\s*column;"
                r"[^}]*overflow:\s*hidden;",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.css,
            re.compile(
                r"\.subscription-modal-body\s*\{"
                r"[^}]*overflow-y:\s*auto;"
                r"[^}]*scrollbar-gutter:\s*stable;",
                re.DOTALL,
            ),
        )

    def test_mobile_subscription_modal_uses_inline_action_buttons_without_legacy_footer(self) -> None:
        block = extract_media_block_by_marker(
            self.css,
            "@media (max-width: 640px) {\n            body { font-size: 16px; }",
        )
        self.assertRegex(
            block,
            re.compile(
                r"#subscription-modal\s+\.subscription-modal-shell\s*\{"
                r"[^}]*width:\s*100vw;"
                r"[^}]*height:\s*100dvh;",
                re.DOTALL,
            ),
        )
        self.assertNotRegex(
            block,
            re.compile(r"#subscription-modal-footer\s*\{", re.DOTALL),
        )
        self.assertNotRegex(
            self.template_source,
            re.compile(r"id=\"subscription-modal-footer\"", re.DOTALL),
        )
        self.assertRegex(
            self.template_source,
            re.compile(
                r"class=\"subscription-modal-actions-inline\s+grid\s+grid-cols-1\s+md:grid-cols-2\s+gap-3\s+pt-2\"",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.template_source,
            re.compile(
                r"<button[^>]*onclick=\"saveSubscriptionTask\(\)\"[^>]*class=\"[^\"]*task-modal-save-btn",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.template_source,
            re.compile(
                r"<button[^>]*onclick=\"closeSubscriptionModal\(\)\"[^>]*class=\"[^\"]*task-modal-cancel-btn",
                re.DOTALL,
            ),
        )

    def test_modal_footers_use_dedicated_footer_shell_classes(self) -> None:
        self.assertNotRegex(
            self.template_source,
            re.compile(
                r"id=\"subscription-modal-footer\"",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.template_source,
            re.compile(
                r"id=\"resource-import-footer\"[^>]*resource-import-footer-shell",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.template_source,
            re.compile(
                r"id=\"monitor-modal-footer\"[^>]*monitor-modal-footer-shell",
                re.DOTALL,
            ),
        )
        self.assertNotRegex(
            self.template_source,
            re.compile(
                r"id=\"(?:resource-import-footer|monitor-modal-footer)\"[^>]*modal-glass-footer",
                re.DOTALL,
            ),
        )
        self.assertNotIn("modal-glass-footer", self.js)

    def test_task_modal_footer_buttons_use_dedicated_visual_classes(self) -> None:
        self.assertRegex(
            self.template_source,
            re.compile(
                r"id=\"monitor-modal-footer\"[\s\S]*?<button[^>]*onclick=\"saveMonitorTask\(\)\"[^>]*class=\"[^\"]*task-modal-save-btn",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.template_source,
            re.compile(
                r"id=\"monitor-modal-footer\"[\s\S]*?<button[^>]*onclick=\"closeMonitorModal\(\)\"[^>]*class=\"[^\"]*task-modal-cancel-btn",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.template_source,
            re.compile(
                r"<button[^>]*onclick=\"saveSubscriptionTask\(\)\"[^>]*class=\"[^\"]*task-modal-save-btn",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.template_source,
            re.compile(
                r"<button[^>]*onclick=\"closeSubscriptionModal\(\)\"[^>]*class=\"[^\"]*task-modal-cancel-btn",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.css,
            re.compile(
                r"\.task-modal-save-btn,\s*\.task-modal-cancel-btn\s*\{"
                r"[^}]*min-height:\s*44px;"
                r"[^}]*font-size:\s*0\.9rem;",
                re.DOTALL,
            ),
        )

    def test_monitor_modal_body_owns_scrollbar(self) -> None:
        self.assertRegex(
            self.css,
            re.compile(
                r"\.monitor-modal-shell\s*\{"
                r"[^}]*display:\s*flex;"
                r"[^}]*flex-direction:\s*column;"
                r"[^}]*overflow:\s*hidden;",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.css,
            re.compile(
                r"\.monitor-modal-body\s*\{"
                r"[^}]*overflow-y:\s*auto;"
                r"[^}]*scrollbar-gutter:\s*stable;",
                re.DOTALL,
            ),
        )

    def test_task_modals_use_viewport_height_budget_outside_mobile_fullscreen(self) -> None:
        self.assertRegex(
            self.css,
            re.compile(
                r"#monitor-modal\s+\.monitor-modal-shell,\s*"
                r"#subscription-modal\s+\.subscription-modal-shell\s*\{"
                r"[^}]*--task-modal-overlay-pad:\s*1rem;"
                r"[^}]*--task-modal-top-gap:\s*clamp\(0\.35rem,\s*4vh,\s*2\.25rem\);"
                r"[^}]*max-height:\s*calc\(100vh\s*-\s*\(var\(--task-modal-overlay-pad,\s*1rem\)\s*\*\s*2\)\s*-\s*var\(--task-modal-top-gap,\s*1rem\)\);"
                r"[^}]*max-height:\s*calc\(100dvh\s*-\s*\(var\(--task-modal-overlay-pad,\s*1rem\)\s*\*\s*2\)\s*-\s*var\(--task-modal-top-gap,\s*1rem\)\);",
                re.DOTALL,
            ),
        )

    def test_mobile_monitor_modal_footer_uses_dedicated_sticky_layout(self) -> None:
        block = extract_media_block_by_marker(
            self.css,
            "@media (max-width: 640px) {\n            body { font-size: 16px; }",
        )
        self.assertRegex(
            block,
            re.compile(
                r"#monitor-modal\s+\.monitor-modal-shell\s*\{"
                r"[^}]*width:\s*100vw;"
                r"[^}]*height:\s*100dvh;",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            block,
            re.compile(
                r"#monitor-modal-footer\s*\{"
                r"[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\);",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            block,
            re.compile(
                r"#monitor-modal-footer\s*\{"
                r"[^}]*position:\s*sticky;"
                r"[^}]*bottom:\s*0;"
                r"[^}]*z-index:\s*16;"
                r"[^}]*padding-bottom:\s*max\(1\.42rem,\s*calc\(env\(safe-area-inset-bottom\)\s*\+\s*0\.56rem\)\);",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            block,
            re.compile(
                r"#monitor-modal-footer\s+button\s*\{"
                r"[^}]*width:\s*100%;",
                re.DOTALL,
            ),
        )

    def test_day_theme_modal_footers_use_light_glass_tokens(self) -> None:
        self.assertRegex(
            self.css,
            re.compile(
                r"html\.theme-day\s*\{"
                r"[^}]*--modal-footer-glass-fill:\s*linear-gradient\(180deg,\s*rgba\(255,\s*255,\s*255,\s*0\.58\),\s*rgba\(237,\s*244,\s*255,\s*0\.4\)\);"
                r"[^}]*--modal-footer-glass-stroke:\s*rgba\(129,\s*152,\s*182,\s*0\.34\);"
                r"[^}]*--modal-footer-glass-highlight:\s*rgba\(255,\s*255,\s*255,\s*0\.74\);"
                r"[^}]*--modal-footer-glass-shadow:\s*0\s+24px\s+48px\s+rgba\(111,\s*135,\s*166,\s*0\.16\);",
                re.DOTALL,
            ),
        )

    def test_resource_import_stepper_is_before_resource_selection_card(self) -> None:
        stepper_index = self.template_source.find('id="resource-import-stepper"')
        browser_index = self.template_source.find('id="resource-share-browser-card"')
        self.assertNotEqual(stepper_index, -1)
        self.assertNotEqual(browser_index, -1)
        self.assertLess(stepper_index, browser_index)

    def test_normalize_resource_source_treats_false_like_disabled(self) -> None:
        source = normalize_resource_source(
            {
                "name": "测试频道",
                "channel_id": "testchannel",
                "enabled": "false",
            }
        )
        self.assertFalse(source["enabled"])

    def test_normalize_config_treats_string_false_resource_source_as_disabled(self) -> None:
        cfg = normalize_config(
            {
                "resource_sources": [
                    {
                        "name": "测试频道",
                        "channel_id": "testchannel",
                        "enabled": "false",
                    }
                ]
            }
        )
        self.assertEqual(len(cfg["resource_sources"]), 1)
        self.assertFalse(cfg["resource_sources"][0]["enabled"])

    def test_resource_section_card_has_local_manage_entry(self) -> None:
        self.assertRegex(
            self.js,
            re.compile(
                r"data-resource-section-manage=\"\$\{escapeHtml\(section\.channel_id \|\| ''\)\}\"",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.js,
            re.compile(
                r"class=\"resource-section-manage-btn\"[^>]*>管理</button>",
                re.DOTALL,
            ),
        )

    def test_resource_channel_manage_modal_keeps_only_high_frequency_actions(self) -> None:
        self.assertRegex(
            self.template_source,
            re.compile(r"id=\"resource-channel-manage-modal\"", re.DOTALL),
        )
        self.assertRegex(
            self.template_source,
            re.compile(r"id=\"resource-channel-manage-name\"", re.DOTALL),
        )
        self.assertRegex(
            self.template_source,
            re.compile(r"id=\"resource-channel-manage-enabled\"", re.DOTALL),
        )
        self.assertRegex(
            self.template_source,
            re.compile(
                r"id=\"resource-channel-manage-pin-btn\"[^>]*>置顶（排序挪到1号）</button>",
                re.DOTALL,
            ),
        )

    def test_resource_channel_manage_modal_supports_save_and_pin_to_top(self) -> None:
        self.assertRegex(
            self.js,
            re.compile(r"function openResourceChannelManageModal\(channelId\) \{", re.DOTALL),
        )
        self.assertRegex(
            self.js,
            re.compile(r"function saveResourceChannelManage\(\) \{", re.DOTALL),
        )
        self.assertRegex(
            self.js,
            re.compile(r"function pinResourceChannelToTop\(\) \{", re.DOTALL),
        )
        self.assertRegex(
            self.js,
            re.compile(
                r"sources\.splice\(index,\s*1\);\s*sources\.unshift\(source\);",
                re.DOTALL,
            ),
        )

    def test_resource_type_badges_highlight_magnet_and_115share(self) -> None:
        self.assertRegex(
            self.js,
            re.compile(r"function getResourceLinkTypeBadgeClass\(linkType\) \{", re.DOTALL),
        )
        self.assertRegex(
            self.js,
            re.compile(r"resource-card-type-badge-magnet", re.DOTALL),
        )
        self.assertRegex(
            self.js,
            re.compile(r"resource-card-type-badge-115share", re.DOTALL),
        )
        self.assertRegex(
            self.js,
            re.compile(
                r"class=\"\$\{escapeHtml\(getResourceLinkTypeBadgeClass\(getEffectiveResourceLinkType\(item\)\)\)\}\"",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.css,
            re.compile(r"\.resource-card-type-badge-magnet\s*\{", re.DOTALL),
        )
        self.assertRegex(
            self.css,
            re.compile(r"\.resource-card-type-badge-115share\s*\{", re.DOTALL),
        )
        self.assertRegex(
            self.css,
            re.compile(r"html\.theme-day\s+\.resource-card-type-badge-magnet\s*\{", re.DOTALL),
        )
        self.assertRegex(
            self.css,
            re.compile(r"html\.theme-day\s+\.resource-card-type-badge-115share\s*\{", re.DOTALL),
        )


if __name__ == "__main__":
    unittest.main()
