import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MONITOR_PAGE_PATH = ROOT / "templates/partials/pages/monitor_about.html"
MONITOR_MODAL_PATH = ROOT / "templates/partials/modals/monitor.html"
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
        self.assertIn('id="quick_import_inbox_path"', source)
        self.assertIn('onclick="openQuickImportInboxPicker()"', source)
        self.assertIn('id="quick-import-run-btn"', source)
        self.assertIn('onclick="runQuickImport()"', source)
        self.assertIn('id="quick-import-status"', source)
        self.assertIn('id="quick-import-targets"', source)

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
