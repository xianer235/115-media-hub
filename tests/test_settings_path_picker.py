import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETTINGS_TEMPLATE = ROOT / "templates/partials/pages/settings.html"
SETTINGS_MODULE = ROOT / "static/js/modules/tabs/settings.js"
INDEX_SCRIPT = ROOT / "static/js/index.js"


class SettingsPathPickerFrontendTest(unittest.TestCase):
    """设置页的网盘路径改成「选择目录」后的结构回归。

    背景：Seerr 点播保存目录、磁力中转目录、常用目录原来都是手打相对路径，
    填错不报错，要等点播落错目录 / 资源导入找不到目录才发现。
    这里钉住三件事：设置页有三个入口、复用监控那套目录选择器、回传的是相对路径。
    """

    def setUp(self):
        self.template = SETTINGS_TEMPLATE.read_text(encoding="utf-8")
        self.settings = SETTINGS_MODULE.read_text(encoding="utf-8")
        self.index_script = INDEX_SCRIPT.read_text(encoding="utf-8")

    def test_template_has_picker_buttons_for_servarr_savepaths(self):
        self.assertIn('id="servarr_movie_savepath"', self.template)
        self.assertIn('id="servarr_tv_savepath"', self.template)
        self.assertIn("pickServarrSavepath('movie')", self.template)
        self.assertIn("pickServarrSavepath('tv')", self.template)

    def test_favorite_dir_block_mentions_picker(self):
        self.assertIn("从网盘选目录加入", self.template)

    def test_settings_module_exposes_three_pickers(self):
        for name in ("pickServarrSavepath", "pickMagnetStagingRoot", "appendFavoriteDirFromPicker"):
            self.assertIn(f"export function {name}(", self.settings)
            self.assertIn(f"window.{name} = {name};", self.settings)

    def test_pickers_reuse_monitor_folder_modal_in_callback_mode(self):
        # 复用同一个选择器：空 targetInputId + onPick 回调，避免再做一套目录树。
        self.assertIn("window.openMonitorFolderModal", self.settings)
        self.assertIn("onPick", self.settings)
        self.assertIn("relative_path", self.settings)
        self.assertIn("magnet_staging_root", self.settings)

    def test_favorite_dir_picker_renders_button_per_provider(self):
        self.assertIn("data-favorite-dir-picker", self.settings)
        self.assertIn("appendFavoriteDirFromPicker(", self.settings)

    def test_monitor_picker_supports_callback_without_breaking_input_mode(self):
        self.assertIn("monitorFolderPickerCallback", self.index_script)
        self.assertIn("relative_path: relativePath", self.index_script)
        # 原行为必须保留：默认仍写回 monitor_scan_path 输入框。
        self.assertIn("monitorFolderPickerTargetId || 'monitor_scan_path'", self.index_script)

    def test_relative_path_is_prefixed_before_resolving_trail(self):
        # 选择器内部按「带挂载前缀的绝对路径」回溯目录，设置页传的是相对路径，
        # 缺了补前缀这一步会静默退到根目录，所以要钉住这个函数。
        self.assertIn("function buildMonitorAbsolutePath(", self.index_script)
        self.assertIn("buildMonitorAbsolutePath(pickerOptions.initialPath", self.index_script)


if __name__ == "__main__":
    unittest.main()
