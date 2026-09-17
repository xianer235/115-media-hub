import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETTINGS_TEMPLATE_PATH = ROOT / "templates/partials/pages/settings.html"
SETTINGS_MODULE_PATH = ROOT / "static/js/modules/tabs/settings.js"
INDEX_SCRIPT_PATH = ROOT / "static/js/index.js"
SCRAPER_CORE_PATH = ROOT / "static/js/modules/scraper/core.js"
SETTINGS_ROUTES_PATH = ROOT / "app/routes/settings.py"
SCRAPER_SERVICE_PATH = ROOT / "app/services/scraper.py"


class AiMatchSettingsFrontendTest(unittest.TestCase):
    def test_settings_template_has_test_button_and_usage_panel(self):
        source = SETTINGS_TEMPLATE_PATH.read_text(encoding="utf-8")
        self.assertIn('id="ai_match_enabled"', source)
        self.assertIn('id="ai_match_base_url"', source)
        self.assertIn('id="ai_match_api_key"', source)
        self.assertIn('id="ai_match_model"', source)
        self.assertIn('id="ai_match_thinking_mode"', source)
        self.assertIn('id="ai_match_min_confidence"', source)
        self.assertIn('id="ai_match_cache_ttl_hours"', source)
        self.assertIn('id="ai-match-test-btn"', source)
        self.assertIn('onclick="testAiMatchConnection()"', source)
        self.assertIn('id="ai-match-test-status"', source)
        self.assertIn('id="ai-match-usage"', source)
        self.assertIn('onclick="loadAiMatchUsage()"', source)
        self.assertIn('onclick="resetAiMatchUsage()"', source)
        # 旧布尔开关应已被三态下拉替换。
        self.assertNotIn('id="ai_match_disable_thinking"', source)

    def test_settings_module_implements_test_and_usage_flows(self):
        source = SETTINGS_MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("export function renderAiMatchTestStatus", source)
        self.assertIn("export async function testAiMatchConnection", source)
        self.assertIn("export async function loadAiMatchUsage", source)
        self.assertIn("export async function resetAiMatchUsage", source)
        self.assertIn("'/settings/ai_match/test'", source)
        self.assertIn("'/settings/ai_match/usage'", source)
        self.assertIn("'/settings/ai_match/usage/reset'", source)
        self.assertIn("ai-match-usage", source)

    def test_index_script_exposes_global_handlers(self):
        source = INDEX_SCRIPT_PATH.read_text(encoding="utf-8")
        for name in (
            "function getCurrentAiMatchConfig",
            "function testAiMatchConnection",
            "function loadAiMatchUsage",
            "function resetAiMatchUsage",
            "function renderAiMatchTestStatus",
        ):
            self.assertIn(name, source)
        self.assertIn("ai_match_thinking_mode", source)
        self.assertIn("ai_match_cache_ttl_hours", source)


class AiMatchBatchVisibilityFrontendTest(unittest.TestCase):
    def test_suggest_branch_shows_ai_state(self):
        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")
        start = source.index("} else if (identify?.status === 'suggest'")
        end = source.index("} else if (item.no_media)", start)
        block = source[start:end]
        self.assertIn("is-ai", block)
        self.assertIn("AI 建议", block)
        self.assertIn("ai_error", block)
        self.assertIn("ai_low_confidence", block)

    def test_summary_reports_ai_state(self):
        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")
        self.assertIn("state.batchAiConfigError", source)
        self.assertIn("AI 未运行", source)
        self.assertIn("batchAiEnabled", source)

    def test_identify_batch_captures_ai_response_fields(self):
        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")
        start = source.index("async function identifyBatch()")
        end = source.index("function renderBatchItemSearch", start)
        block = source[start:end]
        self.assertIn("data.ai_usage", block)
        self.assertIn("data.ai_enabled", block)
        self.assertIn("data?.ai_config_error", block)


class AiMatchBackendSurfaceTest(unittest.TestCase):
    def test_settings_routes_expose_ai_endpoints(self):
        source = SETTINGS_ROUTES_PATH.read_text(encoding="utf-8")
        self.assertIn('"/settings/ai_match/test"', source)
        self.assertIn('"/settings/ai_match/usage"', source)
        self.assertIn('"/settings/ai_match/usage/reset"', source)
        self.assertIn("ai_match_test_connection", source)

    def test_batch_identify_returns_ai_state(self):
        source = SCRAPER_SERVICE_PATH.read_text(encoding="utf-8")
        self.assertIn('response["ai_enabled"] = True', source)
        self.assertIn('response["ai_config_error"] = config_error', source)
        self.assertIn('response["ai_usage"] = usage', source)


if __name__ == "__main__":
    unittest.main()
