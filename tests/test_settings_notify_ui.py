"""设置页「通知推送」分区的前端结构回归（2026-10-21 接入跨盘复制开关）。

跨盘复制通知按任务来源分成两个开关（订阅补源 / 手动复制），放在既有
通知分区里，和订阅成功、监控成功两个开关并列。这里锁定模板结构与
settings.js / index.js 的接线，防止回归。
"""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETTINGS_TEMPLATE_PATH = ROOT / "templates/partials/pages/settings.html"
SETTINGS_MODULE_PATH = ROOT / "static/js/modules/tabs/settings.js"
INDEX_SCRIPT_PATH = ROOT / "static/js/index.js"

NOTIFY_SWITCH_IDS = [
    "notify_push_enabled",
    "notify_monitor_enabled",
    "cross_copy_notify_subscription",
    "cross_copy_notify_manual",
]


class SettingsNotifySectionFrontendTest(unittest.TestCase):
    def setUp(self):
        self.template = SETTINGS_TEMPLATE_PATH.read_text(encoding="utf-8")
        self.settings_js = SETTINGS_MODULE_PATH.read_text(encoding="utf-8")
        self.index_js = INDEX_SCRIPT_PATH.read_text(encoding="utf-8")

    def _notify_body(self):
        # 通知已并入「网络与通知」分组，按 subgroup 锚点取，不再有独立的 settings-body-notify。
        start = self.template.index('data-settings-subgroup="notify"')
        end = self.template.index("</section>", start)
        return self.template[start:end]

    def test_notify_section_has_four_switches(self):
        body = self._notify_body()
        for switch_id in NOTIFY_SWITCH_IDS:
            self.assertIn(f'id="{switch_id}"', body)
        self.assertEqual(body.count('class="ui-checkbox"'), len(NOTIFY_SWITCH_IDS))

    def test_cross_copy_switches_labelled_by_origin(self):
        body = self._notify_body()
        self.assertIn("启用订阅补源通知", body)
        self.assertIn("启用手动跨盘复制通知", body)
        # 合并后要让人知道两者的关系，否则「成功通知去哪了」说不清
        self.assertIn("只发一条汇总", body)

    def test_help_fold_mentions_cross_copy(self):
        body = self._notify_body()
        self.assertIn("跨盘补源", body)
        self.assertIn("手动跨盘复制结果", body)
        self.assertIn("补源失败始终单独提醒", body)

    def test_summary_counts_four_switches(self):
        for switch_id in NOTIFY_SWITCH_IDS:
            self.assertIn(f"'{switch_id}'", self.settings_js)
        self.assertIn("/4 个推送开关", self.settings_js)

    def test_collect_payload_includes_cross_copy_switches(self):
        self.assertIn("cfg.cross_copy_notify_subscription = !!document.getElementById('cross_copy_notify_subscription')?.checked;", self.settings_js)
        self.assertIn("cfg.cross_copy_notify_manual = !!document.getElementById('cross_copy_notify_manual')?.checked;", self.settings_js)

    def test_test_notify_payload_includes_cross_copy_switches(self):
        self.assertIn("cross_copy_notify_subscription: document.getElementById('cross_copy_notify_subscription').checked,", self.index_js)
        self.assertIn("cross_copy_notify_manual: document.getElementById('cross_copy_notify_manual').checked,", self.index_js)


if __name__ == "__main__":
    unittest.main()
