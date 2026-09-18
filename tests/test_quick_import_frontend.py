import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MONITOR_PAGE_PATH = ROOT / "templates/partials/pages/monitor_about.html"
MONITOR_MODAL_PATH = ROOT / "templates/partials/modals/monitor.html"
QUICK_IMPORT_MODAL_PATH = ROOT / "templates/partials/modals/quick_import.html"
INDEX_PAGE_PATH = ROOT / "templates/index.html"
INDEX_SCRIPT_PATH = ROOT / "static/js/index.js"
SETTINGS_MODULE_PATH = ROOT / "static/js/modules/tabs/settings.js"
BOOT_MODULE_PATH = ROOT / "static/js/modules/app/boot.js"
SCRAPER_ROUTES_PATH = ROOT / "app/routes/scraper.py"
RESOURCE_ROUTES_PATH = ROOT / "app/routes/resource.py"
RESOURCE_SERVICE_PATH = ROOT / "app/services/resource.py"
CLI_PATH = ROOT / "cli.py"


class QuickImportFrontendTest(unittest.TestCase):
    def test_monitor_page_has_quick_import_section(self):
        source = MONITOR_PAGE_PATH.read_text(encoding="utf-8")
        self.assertIn("接收夹快捷导入", source)
        self.assertIn('id="quick_import_enabled"', source)
        self.assertIn('id="quick-import-run-btn"', source)
        self.assertIn('onclick="runQuickImport()"', source)
        # 细节收进二级弹窗：卡片上只留摘要 + 开关 + 两个按钮
        self.assertIn('id="quick-import-summary"', source)
        self.assertIn('onclick="openQuickImportSettings()"', source)
        modal = QUICK_IMPORT_MODAL_PATH.read_text(encoding="utf-8")
        self.assertIn('id="quick-import-modal"', modal)
        self.assertIn('id="quick_import_inbox_path"', modal)
        self.assertIn('onclick="openQuickImportInboxPicker()"', modal)
        self.assertIn('id="quick-import-status"', modal)
        self.assertIn('id="quick-import-targets"', modal)
        self.assertIn("partials/modals/quick_import.html", INDEX_PAGE_PATH.read_text(encoding="utf-8"))

    def test_quick_import_uses_shared_panel_and_button_style(self):
        """弹窗里是左侧配置 + 右侧结果，状态面板复用 tg-proxy-status；卡片按钮沿用页面既有尺寸。"""
        modal = QUICK_IMPORT_MODAL_PATH.read_text(encoding="utf-8")
        source = MONITOR_PAGE_PATH.read_text(encoding="utf-8")
        self.assertIn("grid grid-cols-1 lg:grid-cols-2 gap-4 mt-5", modal)
        self.assertIn('id="quick-import-status" class="tg-proxy-status quick-import-result"', modal)
        self.assertIn('id="quick-import-targets" class="quick-import-targets"', modal)
        self.assertIn('id="quick-import-webhook-url"', modal)
        self.assertIn('onclick="copyQuickImportWebhookUrl()"', modal)
        self.assertIn(
            'id="quick-import-run-btn" type="button" onclick="runQuickImport()" '
            'class="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-bold min-h-[42px]"',
            source,
        )
        script = INDEX_SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn("function renderQuickImportTargets", script)
        self.assertIn("quick-import-chip", script)
        self.assertIn("function quickImportWebhookUrl", script)
        self.assertIn("function renderQuickImportWebhookUrl", script)
        self.assertIn("function copyQuickImportWebhookUrl", script)
        self.assertIn("window.location?.origin", script)
        self.assertIn("/webhook/quick-import", script)
        self.assertIn("window.copyQuickImportWebhookUrl = copyQuickImportWebhookUrl", script)
        self.assertIn("function renderQuickImportSummary", script)
        self.assertIn("function openQuickImportSettings", script)
        self.assertIn("function closeQuickImportSettings", script)
        self.assertIn("window.openQuickImportSettings = openQuickImportSettings", script)
        self.assertIn("window.closeQuickImportSettings = closeQuickImportSettings", script)
        self.assertIn("quick-import-modal-run-btn", script)
        self.assertIn("const showQuickImportStatus = (modifier, html)", script)
        self.assertIn("tg-proxy-status--loading", script)
        self.assertIn("tg-proxy-status--error", script)
        self.assertIn("tg-proxy-status-title", script)
        self.assertIn("tg-proxy-status-meta", script)
        # 行内配色不再夹在状态面板上：日间模式只有 tg-proxy-status 一套翻转规则。
        self.assertNotIn("border-amber-500/30 bg-amber-500/10", script)
        self.assertNotIn("border-sky-500/30 bg-sky-500/10", script)
        css = (ROOT / "static/css/index.css").read_text(encoding="utf-8")
        self.assertIn(".quick-import-result {", css)
        self.assertIn(".quick-import-chip {", css)
        self.assertIn("html.theme-day .quick-import-chip {", css)
        self.assertIn("prefers-reduced-motion", css)

    def test_webhook_entry_is_discoverable(self):
        """接收夹专用 webhook 要在界面上能看到、能复制，并在配置页有说明。"""
        script = INDEX_SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn("/webhook/quick-import", script)
        page = MONITOR_PAGE_PATH.read_text(encoding="utf-8")
        modal = QUICK_IMPORT_MODAL_PATH.read_text(encoding="utf-8")
        self.assertIn("设置 / 推送地址", page)
        self.assertIn("接收夹专用 Webhook", modal)
        self.assertIn("油猴脚本", modal)
        settings = (ROOT / "templates/partials/pages/settings.html").read_text(encoding="utf-8")
        self.assertIn("/webhook/quick-import", settings)
        self.assertIn("接收夹快捷导入", settings)

    def test_monitor_modal_has_quick_import_target(self):
        source = MONITOR_MODAL_PATH.read_text(encoding="utf-8")
        self.assertIn('id="monitor_quick_import_target"', source)
        self.assertIn("接收夹快捷导入目标", source)
        self.assertIn('<option value="movie">', source)
        self.assertIn('<option value="tv">', source)

    def test_index_script_wires_quick_import(self):
        source = INDEX_SCRIPT_PATH.read_text(encoding="utf-8")
        for marker in (
            "function renderQuickImportStatus",
            "async function refreshQuickImportStatus",
            "async function saveQuickImportSettings",
            "function openQuickImportInboxPicker",
            "async function runQuickImport",
            "quickImportStatusCache",
            "monitor_quick_import_target",
            "quick_import_target:",
            "window.refreshQuickImportStatus = refreshQuickImportStatus",
        ):
            self.assertIn(marker, source)
        self.assertIn("'/scraper/quick-import/run'", source)
        self.assertIn("'/scraper/quick-import/status'", source)

    def test_folder_picker_supports_quick_import_target(self):
        source = INDEX_SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn("monitorFolderPickerTargetId", source)
        self.assertIn("openMonitorFolderModal('quick_import_inbox_path')", source)

    def test_settings_module_collects_quick_import_fields(self):
        source = SETTINGS_MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("'quick_import_inbox_path'", source)
        self.assertIn("cfg.quick_import_enabled", source)

    def test_boot_loads_quick_import_status(self):
        source = BOOT_MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("refreshQuickImportStatus", source)


class QuickImportBackendWiringTest(unittest.TestCase):
    def test_routes_expose_quick_import_endpoints(self):
        source = SCRAPER_ROUTES_PATH.read_text(encoding="utf-8")
        self.assertIn('"/scraper/quick-import/run"', source)
        self.assertIn('"/scraper/quick-import/status"', source)

    def test_import_hooks_flag_inbox_jobs(self):
        routes = RESOURCE_ROUTES_PATH.read_text(encoding="utf-8")
        self.assertIn("is_quick_import_savepath", routes)
        self.assertIn("quick_import_inbox", routes)
        service = RESOURCE_SERVICE_PATH.read_text(encoding="utf-8")
        self.assertIn("quick_import_inbox", service)
        self.assertIn("run_quick_import", service)

    def test_cli_exposes_quick_import_actions(self):
        source = CLI_PATH.read_text(encoding="utf-8")
        self.assertIn("quick-import-run", source)
        self.assertIn("quick-import-status", source)


if __name__ == "__main__":
    unittest.main()
