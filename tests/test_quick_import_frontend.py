"""接收夹任务（inbox）的前端与路由接线：它和扫描任务共用一套任务/路径/webhook 口径。"""

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MONITOR_PAGE_PATH = ROOT / "templates/partials/pages/monitor_about.html"
MONITOR_MODAL_PATH = ROOT / "templates/partials/modals/monitor.html"
QUICK_IMPORT_MODAL_PATH = ROOT / "templates/partials/modals/quick_import.html"
INDEX_PAGE_PATH = ROOT / "templates/index.html"
INDEX_SCRIPT_PATH = ROOT / "static/js/index.js"
SETTINGS_PAGE_PATH = ROOT / "templates/partials/pages/settings.html"
SETTINGS_MODULE_PATH = ROOT / "static/js/modules/tabs/settings.js"
BOOT_MODULE_PATH = ROOT / "static/js/modules/app/boot.js"
SCRAPER_ROUTES_PATH = ROOT / "app/routes/scraper.py"
MONITOR_ROUTES_PATH = ROOT / "app/routes/monitor.py"
RESOURCE_ROUTES_PATH = ROOT / "app/routes/resource.py"
RESOURCE_SERVICE_PATH = ROOT / "app/services/resource.py"
CLI_PATH = ROOT / "cli.py"


class InboxTaskFrontendTest(unittest.TestCase):
    def test_inbox_is_a_task_type_not_a_global_card(self):
        """接收夹不再是页面上的全局卡片：它是任务列表里的一个 inbox 任务。"""
        page = MONITOR_PAGE_PATH.read_text(encoding="utf-8")
        self.assertIn("文件夹监控任务列表", page)
        self.assertNotIn("接收夹快捷导入", page)
        self.assertNotIn('id="quick_import_enabled"', page)

        modal = MONITOR_MODAL_PATH.read_text(encoding="utf-8")
        self.assertIn('id="monitor_task_type"', modal)
        self.assertIn('<option value="inbox">', modal)
        self.assertIn('id="monitor_enabled"', modal)
        self.assertIn('id="monitor_inbox_target_movie"', modal)
        self.assertIn('id="monitor_inbox_target_tv"', modal)
        self.assertIn('id="monitor_inbox_webhook_url"', modal)
        self.assertIn('onclick="copyMonitorWebhookUrl()"', modal)
        self.assertIn('onclick="runInboxTaskNow()"', modal)
        self.assertIn('id="inbox-task-status"', modal)

        # 旧的二级弹窗整块删掉，配置回到任务编辑弹窗里。
        self.assertFalse(QUICK_IMPORT_MODAL_PATH.exists())
        self.assertNotIn("partials/modals/quick_import.html", INDEX_PAGE_PATH.read_text(encoding="utf-8"))

    def test_index_script_wires_inbox_task(self):
        script = INDEX_SCRIPT_PATH.read_text(encoding="utf-8")
        for marker in (
            "function applyMonitorTaskTypeUI",
            "function syncMonitorTaskTypeOptions",
            "function syncWebhookToggleState",
            "function buildInboxActivityHtml",
            "function populateMonitorInboxTargetSelects",
            "function monitorTaskWebhookUrl",
            "async function refreshInboxTaskStatus",
            "function maybeRefreshInboxTaskStatus",
            "async function copyMonitorWebhookUrl",
            "async function runInboxTaskNow",
            "inboxTaskStatusCache",
            "window.refreshInboxTaskStatus = refreshInboxTaskStatus",
            "window.copyMonitorWebhookUrl = copyMonitorWebhookUrl",
            "window.runInboxTaskNow = runInboxTaskNow",
        ):
            self.assertIn(marker, script)
        self.assertIn("'/scraper/quick-import/status'", script)
        self.assertIn("'/monitor/start'", script)
        # 旧接口地址、旧全局配置字段都不该再出现在前端。
        self.assertNotIn("/webhook/quick-import", script)
        self.assertNotIn("quick_import_enabled", script)
        self.assertNotIn("quick_import_inbox_path", script)

    def test_monitor_modal_reuses_one_path_field_for_both_types(self):
        modal = MONITOR_MODAL_PATH.read_text(encoding="utf-8")
        self.assertIn('id="monitor-scan-fields"', modal)
        self.assertIn('id="monitor-inbox-fields"', modal)
        self.assertIn('id="monitor-scan-path-label"', modal)
        self.assertIn('id="monitor-inbox-path-label"', modal)
        self.assertIn('id="monitor_scan_path"', modal)
        self.assertIn('onclick="openMonitorFolderModal()"', modal)
        # 同一个路径输入框同时服务扫描任务和接收夹任务。
        script = INDEX_SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn("function applyMonitorTaskTypeUI", script)
        self.assertIn("'monitor-scan-fields'", script)
        self.assertIn("'monitor-inbox-fields'", script)

    def test_inbox_task_is_builtin_and_not_deletable(self):
        """接收夹是内置槽位：默认就有一个，界面上不给新建第二个、也不给删除。"""
        script = INDEX_SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn("const deleteButton = isInboxTask ? '' : buildMonitorTaskIconButton({", script)
        # 任务类型不可更改：类型下拉锁死，只作为展示。
        self.assertIn("select.disabled = true;", script)
        self.assertIn("monitor-task-type-hint", script)
        self.assertIn("接收夹是内置固定任务：类型不能改", script)
        self.assertIn('id="monitor-task-type-hint"', MONITOR_MODAL_PATH.read_text(encoding="utf-8"))
        monitor_routes = MONITOR_ROUTES_PATH.read_text(encoding="utf-8")
        self.assertIn("接收夹任务是内置的，不能删除", monitor_routes)

    def test_webhook_gated_on_signing_secret(self):
        """webhook 只在设置了签名密钥后才能开启，避免全新安装暴露免鉴权入口。"""
        script = INDEX_SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn("'webhook_secret'", script)
        self.assertIn("sensitiveConfigMeta.webhook_secret", script)
        self.assertIn("checkbox.disabled = !hasSecret;", script)
        modal = MONITOR_MODAL_PATH.read_text(encoding="utf-8")
        self.assertIn('id="webhook-secret-hint"', modal)
        self.assertIn("Webhook 签名密钥", modal)

    def test_scan_only_fields_are_hidden_for_inbox(self):
        """重试次数/列出延时/大小过滤只对扫描任务有意义，应当收进扫描字段组。"""
        modal = MONITOR_MODAL_PATH.read_text(encoding="utf-8")
        scan_fields_start = modal.index('id="monitor-scan-fields"')
        inbox_fields_start = modal.index('id="monitor-inbox-fields"')
        scan_section = modal[scan_fields_start:inbox_fields_start]
        self.assertIn("monitor_retries", scan_section)
        self.assertIn("monitor_list_delay_ms", scan_section)
        self.assertIn("monitor_min_file_size_mb", scan_section)
        self.assertNotIn("monitor_delay_seconds", scan_section)
        # 定时执行对接收夹也生效（周期整理），所以不在扫描字段组里。
        self.assertNotIn("monitor_cron_minutes", scan_section)

    def test_rename_and_disable_are_explained_in_modal(self):
        script = INDEX_SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn("修改任务名会改变上面的 webhook 地址", script)
        modal = MONITOR_MODAL_PATH.read_text(encoding="utf-8")
        self.assertIn("定时和所有自动触发都停", modal)
        self.assertIn("接收夹任务会识别并分发一次", modal)

    def test_inbox_card_auto_refreshes_with_monitor_polling(self):
        """卡片上的最近接收 / 最近整理跟着既有状态轮询按 30s 节流刷新。"""
        script = INDEX_SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn("INBOX_STATUS_REFRESH_INTERVAL_MS = 30000", script)
        self.assertIn("maybeRefreshInboxTaskStatus()", script)
        # 两条 monitor 状态落地路径（tab 模块的 afterApply + 兜底分支）都要触发。
        self.assertGreaterEqual(script.count("maybeRefreshInboxTaskStatus();"), 2)

    def test_resource_import_understands_inbox_task(self):
        """接收夹不是监控任务：资源导入弹窗要说明会交给接收夹整理，而不是生成 STRM。"""
        resource_core = (ROOT / "static/js/modules/resource/core.js").read_text(encoding="utf-8")
        self.assertIn("matchedInbox", resource_core)
        self.assertIn("命中接收夹", resource_core)
        self.assertIn("导入后自动整理分发", resource_core)
        import_modal = (ROOT / "static/js/modules/resource/import-modal.js").read_text(encoding="utf-8")
        self.assertIn("data.quick_import_inbox", import_modal)
        self.assertIn("保存完成后会由接收夹自动识别整理并分发", import_modal)
        self.assertIn("String(task?.task_type || 'scan') !== 'inbox'", import_modal)

    def test_webhook_hint_teaches_root_relative_savepath(self):
        """保存路径统一从 115 根目录开始填；面板的 /115/xxx 只是显示形式。"""
        script = INDEX_SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn("115 根目录下的相对路径", script)
        modal = MONITOR_MODAL_PATH.read_text(encoding="utf-8")
        self.assertIn("根目录下的相对路径", modal)
        self.assertIn("不要带", modal)

    def test_nested_folder_picker_stacks_above_parent_modal(self):
        """「选择文件夹」是二级弹窗：模板里的 z-[56] 低于任务弹窗，必须靠动态层级抬升。"""
        script = INDEX_SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn("function stackModalLayer", script)
        self.assertIn("function readModalLayerBase", script)
        self.assertIn("function isModalOpen", script)
        self.assertIn("stackModalLayer(modal);", script)
        self.assertIn("document.querySelectorAll('div[id$=\"-modal\"]')", script)
        self.assertIn("z-[56]", MONITOR_MODAL_PATH.read_text(encoding="utf-8"))
        # 抬升后的上限必须低于“需要盖住弹窗”的应用对话框层级。
        ceiling_match = re.search(r"MODAL_LAYER_CEILING = (\d+)", script)
        self.assertIsNotNone(ceiling_match)
        app_dialog_match = re.search(
            r"\.app-dialog-modal \{[^}]*z-index:\s*(\d+)",
            (ROOT / "static/css/index.css").read_text(encoding="utf-8"),
        )
        self.assertIsNotNone(app_dialog_match)
        self.assertLess(int(ceiling_match.group(1)), int(app_dialog_match.group(1)))

    def test_settings_module_no_longer_collects_inbox_fields(self):
        source = SETTINGS_MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("quick_import_inbox_path", source)
        self.assertNotIn("quick_import_enabled", source)

    def test_boot_loads_inbox_task_status(self):
        source = BOOT_MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("refreshInboxTaskStatus", source)
        self.assertNotIn("refreshQuickImportStatus", source)

    def test_settings_page_explains_inbox_task(self):
        page = SETTINGS_PAGE_PATH.read_text(encoding="utf-8")
        self.assertIn("接收夹", page)
        self.assertIn("根目录下的相对路径", page)
        self.assertNotIn("/webhook/quick-import", page)


class InboxTaskBackendWiringTest(unittest.TestCase):
    def test_routes_expose_inbox_task_endpoints(self):
        source = SCRAPER_ROUTES_PATH.read_text(encoding="utf-8")
        self.assertIn('"/scraper/quick-import/run"', source)
        self.assertIn('"/scraper/quick-import/status"', source)
        monitor_routes = MONITOR_ROUTES_PATH.read_text(encoding="utf-8")
        # 旧的独立 webhook 已经删掉，接收夹走统一的 /webhook/{任务名}。
        self.assertNotIn('"/webhook/quick-import"', monitor_routes)
        self.assertIn('"/webhook/{task_name}"', monitor_routes)
        self.assertIn("_handle_inbox_webhook", monitor_routes)
        self.assertIn("normalize_userscript_savepath", monitor_routes)

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
