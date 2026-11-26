import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "templates/index.html"
MODAL_HTML = ROOT / "templates/partials/modals/cross_copy.html"
JOB_MODAL_HTML = ROOT / "templates/partials/modals/resource_import.html"
UI_JS = ROOT / "static/js/modules/cross_copy/ui.js"
JOB_MODAL_JS = ROOT / "static/js/modules/resource/job-modal.js"
BOOT_JS = ROOT / "static/js/modules/app/boot.js"


class CrossCopyFrontendTest(unittest.TestCase):
    def test_page_loads_modal_and_script(self):
        index = INDEX_HTML.read_text(encoding="utf-8")
        self.assertIn('{% include "partials/modals/cross_copy.html" %}', index)
        self.assertIn("/static/js/modules/cross_copy/ui.js", index)

    def test_modal_has_source_and_target_pickers(self):
        modal = MODAL_HTML.read_text(encoding="utf-8")
        for element_id in (
            "cross-copy-modal",
            "cross-copy-source-provider",
            "cross-copy-source-trail",
            "cross-copy-source-list",
            "cross-copy-target-provider",
            "cross-copy-target-trail",
            "cross-copy-target-list",
            "cross-copy-summary",
            "cross-copy-submit",
        ):
            self.assertIn(f'id="{element_id}"', modal)
        self.assertIn("onCrossCopySourceProviderChange(this.value)", modal)
        self.assertIn("onCrossCopyTargetProviderChange(this.value)", modal)
        self.assertIn("submitCrossCopyTask()", modal)
        self.assertIn("closeCrossCopyModal()", modal)

    def test_task_center_exposes_cross_copy_tab_and_entry(self):
        job_modal = JOB_MODAL_JS.read_text(encoding="utf-8")
        job_modal_html = JOB_MODAL_HTML.read_text(encoding="utf-8")
        self.assertIn("{ value: 'cross_copy', label: '跨盘复制'", job_modal)
        self.assertIn("window.renderCrossCopyJobs", job_modal)
        self.assertIn("window.fetchCrossCopyJobs", job_modal)
        self.assertIn("window.getCrossCopyActiveCount", job_modal)
        self.assertIn('id="cross-copy-new-btn"', job_modal_html)
        self.assertIn("openCrossCopyModal()", job_modal_html)

    def test_cross_copy_tab_keeps_type_tab_highlight(self):
        """切到「跨盘复制」后，三个类型标签的高亮要跟上。
        cross_copy 模块通过 window 上的函数重绘标签，一旦那条链路断了，当前标签就一直是灰的。"""
        job_modal = JOB_MODAL_JS.read_text(encoding="utf-8")
        self.assertIn("renderTaskCenterTypeTabs,\n", job_modal)
        anchor = "if (typeof window.renderCrossCopyJobs === 'function') window.renderCrossCopyJobs();"
        self.assertIn(anchor, job_modal)
        before = job_modal[: job_modal.index(anchor)][-400:]
        self.assertIn("renderTaskCenterTypeTabs();", before)

    def test_boot_routes_cross_copy_tab_clicks(self):
        boot = BOOT_JS.read_text(encoding="utf-8")
        self.assertIn("['scraper', 'cross_copy'].includes(rawTab)", boot)
        self.assertIn("window.setCrossCopyFilter", boot)

    def test_ui_calls_backend_endpoints(self):
        ui = UI_JS.read_text(encoding="utf-8")
        self.assertIn("'/cross_copy/capabilities'", ui)
        self.assertIn("'/cross_copy/jobs?limit=100'", ui)
        self.assertIn("`/cross_copy/jobs/${encodeURIComponent(String(jobId))}/cancel`", ui)
        self.assertIn("`/cross_copy/jobs/${encodeURIComponent(String(jobId))}/pause`", ui)
        self.assertIn("`/cross_copy/jobs/${encodeURIComponent(String(jobId))}/resume`", ui)
        self.assertIn("`/cross_copy/jobs/${encodeURIComponent(String(jobId))}/retry`", ui)
        self.assertIn("`/cross_copy/jobs/${encodeURIComponent(String(jobId))}/delete`", ui)
        self.assertIn("'/cross_copy/jobs/clear'", ui)
        self.assertIn("`/resource/browse/${encodeURIComponent(provider)}/folders?", ui)
        self.assertIn("source_file_id: item.id", ui)
        self.assertIn("target_dir_id: targetDirId", ui)

    def test_records_can_be_cleared_like_other_tasks(self):
        """任务中心跨盘复制页签也要有「清空」，并且只清已结束的记录。"""
        job_modal = JOB_MODAL_JS.read_text(encoding="utf-8")
        ui = UI_JS.read_text(encoding="utf-8")
        self.assertIn("isCrossCopyTab", job_modal)
        self.assertIn("['resource', 'scraper', 'cross_copy'].includes(taskCenterTab)", job_modal)
        self.assertIn("clearCompletedCrossCopyJobs", job_modal)
        self.assertIn("clearTerminalCrossCopyJobs", job_modal)
        self.assertIn("清空复制", job_modal)
        self.assertIn("清空已结束", job_modal)
        # 单条记录删除按钮只给已结束的任务
        self.assertIn('data-cross-copy-action="delete"', ui)
        self.assertIn("const canDelete = !canCancel", ui)
        self.assertIn("只删记录，网盘上的文件不受影响", ui)

    def test_status_texts_are_plain_language(self):
        ui = UI_JS.read_text(encoding="utf-8")
        for text in ("排队中", "复制中", "已完成", "失败", "已取消", "已暂停", "秒传命中，未消耗上传流量"):
            self.assertIn(text, ui)

    def test_source_pane_keeps_folders_clickable_and_target_only_shows_folders(self):
        ui = UI_JS.read_text(encoding="utf-8")
        self.assertIn("if (pane.side === 'target')", ui)
        self.assertIn("return pane.entries.filter(entry => !!entry?.is_dir);", ui)

    def test_subscription_form_can_enable_cross_copy(self):
        subscription_modal = (ROOT / "templates/partials/modals/subscription.html").read_text(encoding="utf-8")
        subscription_ui = (ROOT / "static/js/modules/subscription/ui.js").read_text(encoding="utf-8")
        for element_id in (
            "subscription-cross-copy-block",
            "subscription-cross-copy-sources",
            "subscription-cross-copy-hint",
        ):
            self.assertIn(f'id="{element_id}"', subscription_modal)
        # 2026-10-23 起补源是单开关（开 = fallback），不再是 off/fallback/prefer 三选一
        self.assertIn('id="subscription-cross-copy-enabled"', subscription_modal)
        self.assertNotIn('name="subscription_cross_copy_mode"', subscription_modal)
        self.assertIn("cross_copy_mode: getSubscriptionCrossCopyMode()", subscription_ui)
        self.assertIn("cross_copy_sources: getSelectedSubscriptionCrossCopySources()", subscription_ui)
        self.assertIn("目前跨盘补源只支持夸克网盘，请勾选夸克作为源网盘", subscription_ui)
        self.assertIn("setSubscriptionCrossCopyMode(task.cross_copy_mode || 'off')", subscription_ui)


    def test_job_card_shows_paths_and_transfer_metrics(self):
        ui = UI_JS.read_text(encoding="utf-8")
        # 源/目标完整路径随任务提交
        self.assertIn("source_path: joinPanPath(sourceDir, item.name)", ui)
        self.assertIn("target_path: joinPanPath(targetPath, item.name)", ui)
        self.assertIn("function joinPanPath", ui)
        # 卡片字段与大小/速度文案
        for text in ("源文件", "目标文件", "已下载", "已上传", "cc-job-progress-meta"):
            self.assertIn(text, ui)
        self.assertIn("function getTransferLine", ui)
        self.assertIn("function formatSpeed", ui)
        # 读接口里进度对象携带的字节数与速度
        self.assertIn("progress.sent", ui)
        self.assertIn("progress.speed", ui)

    def test_modal_styles_transfer_meta_line(self):
        modal = MODAL_HTML.read_text(encoding="utf-8")
        self.assertIn(".cc-job-progress-meta", modal)

    def test_source_picker_supports_multi_select(self):
        ui = UI_JS.read_text(encoding="utf-8")
        modal = MODAL_HTML.read_text(encoding="utf-8")
        # 源侧勾选从单对象改成数组，切目录时重置的也是这个字段
        self.assertIn("selectedItems: [],", ui)
        self.assertIn("if (!opts.keepSelection) pane.selectedItems = [];", ui)
        self.assertNotIn("state.source.selected?.id", ui)
        self.assertNotIn("pane.selected = null", ui)
        # 勾选 / 全选本页 / 清空选择
        for function_name in (
            "function getSelectedItems",
            "function syncSourceSelectionBar",
            "function toggleSourceSelection",
            "function selectAllSourceFiles",
            "function clearSourceSelection",
        ):
            self.assertIn(function_name, ui)
        # 点源侧文件是切换勾选，文件夹仍然只是进目录
        self.assertIn("toggleSourceSelection(entryId);", ui)
        self.assertIn("if (!entry || entry.is_dir) return;", ui)
        # 勾选视觉：列表项角标 + 已选样式
        self.assertIn("cc-entry-check", ui)
        self.assertIn(".cc-entry-check", modal)
        self.assertIn(".cc-entry.is-selected .cc-entry-check", modal)
        # 源侧工具条与摘要下方的失败提示位
        for element_id in (
            "cross-copy-source-selection",
            "cross-copy-select-all",
            "cross-copy-clear-selection",
            "cross-copy-summary-note",
        ):
            self.assertIn(f'id="{element_id}"', modal)
        self.assertIn("全选本页", modal)
        self.assertIn("清空选择", modal)
        self.assertIn("selectAllCrossCopySources()", modal)
        self.assertIn("clearCrossCopySelection()", modal)
        self.assertIn("selectAllCrossCopySources: selectAllSourceFiles", ui)
        self.assertIn("clearCrossCopySelection: clearSourceSelection", ui)
        # 「已选 N 个 · 合计 X」以及多文件摘要文案
        self.assertIn("已选 ${items.length} 个${total > 0 ? ` · 合计 ${formatSize(total)}` : ''}", ui)
        self.assertIn("已选 ${items.length} 个文件", ui)
        self.assertIn("合计 ${formatSize(total)}", ui)

    def test_submit_creates_jobs_one_by_one_and_reports_failures(self):
        ui = UI_JS.read_text(encoding="utf-8")
        # 串行提交：for 循环里逐个 await，不发批量接口
        self.assertIn("for (let index = 0; index < items.length; index += 1)", ui)
        self.assertIn("await global.MediaHubApi.postJson('/cross_copy/jobs', {", ui)
        self.assertNotIn("Promise.all(items", ui)
        # 每个请求前检查弹窗是否被关掉或取消
        self.assertIn("if (!state.modalOpen || !state.submitting)", ui)
        # 进度文案
        self.assertIn("正在创建任务 ${progress.index}/${progress.total}…", ui)
        # 结果统计：成功 N 个、失败 M 个，并带上第一个错误原因
        self.assertIn("成功 ${created} 个，失败 ${failedItems.length} 个：${firstError}", ui)
        self.assertIn("失败 ${failedItems.length} 个：${firstError}", ui)
        self.assertIn("if (!firstError) firstError = ", ui)
        # 失败时保留弹窗，选中收缩到失败项方便重试（文件夹失败还原成「选中文件夹」）
        self.assertIn("state.source.selectedItems = failedItems", ui)
        self.assertIn("state.source.selectedFolder = failedItems.find(item => item.isDir) || null;", ui)
        # 空选提示
        self.assertIn("请先选择要复制的文件", ui)

    def test_file_manager_page_renamed_and_cross_paste_wired(self):
        index = INDEX_HTML.read_text(encoding="utf-8")
        self.assertIn("文件管理", index)
        self.assertNotIn(">刮削管理<", index)
        core = (ROOT / "static/js/modules/scraper/core.js").read_text(encoding="utf-8")
        # 跨网盘粘贴入口
        self.assertIn("async function crossCopyHere", core)
        self.assertIn("'/cross_copy/jobs'", core)
        self.assertIn("跨网盘复制到此", core)
        self.assertIn("先下载到本地再上传", core)
        self.assertIn("/cross_copy/capabilities", core)
        # 复制不再因为网盘不同而拒绝；跨盘移动被禁用（见 test_cross_cloud_move_is_blocked）
        self.assertNotIn("showToast('待复制条目与当前网盘不一致'", core)

    def test_source_pane_can_select_whole_folder(self):
        ui = UI_JS.read_text(encoding="utf-8")
        modal = MODAL_HTML.read_text(encoding="utf-8")
        # 文件夹与文件互斥：选文件夹清空文件，选文件清空文件夹
        self.assertIn("selectedFolder: null,", ui)
        self.assertIn("function getSelectedFolder", ui)
        self.assertIn("function toggleSourceFolder", ui)
        self.assertIn("state.source.selectedFolder = null;", ui)
        self.assertIn("state.source.selectedItems = [];", ui)
        # 源侧文件夹整行是选中，右侧「进入 ›」才进目录
        self.assertIn("data-cc-enter=\"1\"", ui)
        self.assertIn("enterSourceFolder(entryId);", ui)
        self.assertIn(".cc-entry-enter", modal)
        # 摘要对文件夹只说「待统计」，不为统计文件数再发请求
        self.assertIn("待统计", ui)
        self.assertNotIn("统计文件数", ui)
        # 提交时带上 source_is_dir
        self.assertIn("source_is_dir: !!item.isDir", ui)
        self.assertIn("source_is_dir: !!item.isDir,", ui)

    def test_folder_job_status_and_badge(self):
        ui = UI_JS.read_text(encoding="utf-8")
        # 部分失败：result.status=partial 显示成「部分完成」
        self.assertIn("partial: '部分完成'", ui)
        self.assertIn("resultStatus === 'partial' ? 'partial' : rawStatus", ui)
        self.assertIn("Number(job?.source_is_dir || 0) === 1", ui)
        self.assertIn("部分完成：共 ${filesTotal} 个文件，${filesFailed} 个失败", ui)
        self.assertIn("源文件夹", ui)
        self.assertIn("目标文件夹", ui)

    def test_file_manager_cross_paste_allows_folders(self):
        core = (ROOT / "static/js/modules/scraper/core.js").read_text(encoding="utf-8")
        # 不再拦截文件夹
        self.assertNotIn("跨网盘复制暂不支持文件夹", core)
        self.assertIn("source_is_dir: isDir", core)
        self.assertIn("文件夹会逐个文件复制，大文件夹会比较慢", core)

    def test_cross_cloud_move_is_blocked(self):
        """跨网盘移动禁用：只保留同盘移动，跨盘只能复制。"""
        core = (ROOT / "static/js/modules/scraper/core.js").read_text(encoding="utf-8")
        # 旧那句看不懂的提示已经删掉
        self.assertNotIn("待移动条目与当前网盘不一致", core)
        # 跨盘时按钮禁用 + 人话解释
        self.assertIn("const moveBlocked = mode === 'move' && crossCloud;", core)
        self.assertIn("不能跨网盘移动", core)
        self.assertIn("移动只能在同一个网盘内使用", core)
        self.assertIn("确认没问题再回源网盘自己删", core)
        # 给一个「改用复制」的出口，不用重新选一遍
        self.assertIn("convert-move-to-copy", core)
        self.assertIn("改用复制", core)
        # 移动请求带上来源网盘，后端据此二次拦截
        self.assertIn("source_provider: buffer.provider,", core)


if __name__ == "__main__":
    unittest.main()
