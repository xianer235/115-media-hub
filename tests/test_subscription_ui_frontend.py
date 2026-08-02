import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI_PATH = ROOT / "static/js/modules/subscription/ui.js"
LINK_TAGS_PATH = ROOT / "static/js/modules/resource/link-tags.js"
TEMPLATE_PATH = ROOT / "templates/index.html"


def run_subscription_ui(expression, provider_meta=None):
    provider_meta = provider_meta or []
    script = f"""
const fs = require('fs');
const vm = require('vm');
const context = {{
  window: {{ providerMeta: {json.dumps(provider_meta, ensure_ascii=False)} }},
  escapeHtml: value => String(value ?? ''),
}};
vm.createContext(context);
vm.runInContext(fs.readFileSync({json.dumps(str(LINK_TAGS_PATH))}, 'utf8'), context);
vm.runInContext(fs.readFileSync({json.dumps(str(UI_PATH))}, 'utf8'), context);
const result = vm.runInContext({json.dumps(expression)}, context);
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr.strip())
    return json.loads(completed.stdout)


class SubscriptionUiFrontendTest(unittest.TestCase):
    def test_resource_link_tags_load_before_subscription_ui(self):
        html = TEMPLATE_PATH.read_text(encoding="utf-8")
        self.assertLess(
            html.index('src="/static/js/modules/resource/link-tags.js'),
            html.index('src="/static/js/modules/subscription/ui.js'),
        )

    def test_subscription_provider_badges_use_global_tones(self):
        providers = [
            {"name": "115", "label": "115网盘", "link_type": "115share"},
            {"name": "quark", "label": "夸克网盘", "link_type": "quark"},
            {"name": "aliyun", "label": "阿里云盘", "link_type": "aliyun"},
            {"name": "123pan", "label": "123云盘", "link_type": "123pan"},
            {"name": "tianyi", "label": "天翼云盘", "link_type": "tianyi"},
            {"name": "future", "label": "未来网盘", "link_type": "future"},
        ]
        result = run_subscription_ui(
            "window.providerMeta.map(provider => getSubscriptionProviderBadgeMeta(provider.name))",
            providers,
        )
        self.assertEqual(
            [item["className"] for item in result],
            [
                "resource-link-tag resource-link-tag--blue",
                "resource-link-tag resource-link-tag--violet",
                "resource-link-tag resource-link-tag--orange",
                "resource-link-tag resource-link-tag--emerald",
                "resource-link-tag resource-link-tag--rose",
                "resource-link-tag resource-link-tag--neutral",
            ],
        )
        self.assertEqual(result[1]["label"], "夸克网盘")

    def test_subscription_last_hit_badge_uses_calendar_date_boundaries(self):
        now = "2026-08-31T12:00:00"
        values = [
            "2026-08-31T00:01:00",
            "2026-08-30T23:59:00",
            "2026-08-29T00:00:00",
            "2026-08-02T00:00:00",
            "2026-08-01T00:00:00",
            "2025-12-31T00:00:00",
            "2026-09-01T00:00:00",
        ]
        result = run_subscription_ui(
            f"{json.dumps(values)}.map(value => formatSubscriptionLastHitAge(value, {json.dumps(now)}))"
        )
        self.assertEqual(result, ["今天", "昨天", "2天前", "29天前", "08-01", "2025-12-31", "09-01"])

    def test_subscription_last_hit_badge_handles_missing_and_invalid_dates(self):
        result = run_subscription_ui(
            "({ none: buildSubscriptionLastHitBadge({}), unknown: buildSubscriptionLastHitBadge({ matched_resource_title: '仙逆' }), invalid: buildSubscriptionLastHitBadge({ last_success_at: 'bad' }) })"
        )
        self.assertIn("尚未命中", result["none"])
        self.assertIn("命中日期未知", result["unknown"])
        self.assertIn("尚未命中", result["invalid"])

    def test_subscription_last_hit_badge_and_detail_use_same_timestamp(self):
        task = {
            "matched_resource_title": "仙逆",
            "last_success_at": "2026-08-02T04:34:25",
        }
        result = run_subscription_ui(
            f"({{ badge: buildSubscriptionLastHitBadge({json.dumps(task, ensure_ascii=False)}), detail: buildSubscriptionLatestMatchText({json.dumps(task, ensure_ascii=False)}) }})"
        )
        self.assertIn("最近命中", result["badge"])
        self.assertIn("仙逆", result["detail"])
        self.assertIn("2026-08-02 04:34", result["detail"])


if __name__ == "__main__":
    unittest.main()
