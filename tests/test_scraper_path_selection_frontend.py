import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_SELECTION_PATH = ROOT / "static/js/modules/app/text-selection.js"
PATH_SELECTION_PATH = ROOT / "static/js/modules/scraper/path-selection.js"
SCRAPER_CORE_PATH = ROOT / "static/js/modules/scraper/core.js"
SCRAPER_TEMPLATE_PATH = ROOT / "templates/partials/pages/scraper.html"
INDEX_TEMPLATE_PATH = ROOT / "templates/index.html"
STYLESHEET_PATH = ROOT / "static/css/index.css"


def run_path_selection(expression: str):
    script = f"""
const fs = require('fs');
const vm = require('vm');
const context = {{ window: {{}} }};
vm.createContext(context);
vm.runInContext(fs.readFileSync({json.dumps(str(TEXT_SELECTION_PATH))}, 'utf8'), context);
vm.runInContext(fs.readFileSync({json.dumps(str(PATH_SELECTION_PATH))}, 'utf8'), context);
const api = context.window.ScraperPathSelection;
const result = ({expression});
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


class ScraperPathSelectionLogicTest(unittest.TestCase):
    def test_single_folder_uses_its_full_path(self):
        result = run_path_selection(
            "api.resolveSourcePath(["
            "{ is_dir: true, name: '小芳 (2026)', path: '电视剧/小芳 (2026)', parent_path: '电视剧' }"
            "], '电视剧')"
        )

        self.assertEqual(result, "电视剧/小芳 (2026)")

    def test_selected_files_use_their_full_parent_path(self):
        result = run_path_selection(
            "api.resolveSourcePath(["
            "{ is_dir: false, path: '电视剧/小芳/S01E01.mkv', parent_path: '电视剧/小芳' },"
            "{ is_dir: false, path: '电视剧/小芳/S01E02.mkv', parent_path: '电视剧/小芳' }"
            "], '电视剧/小芳')"
        )

        self.assertEqual(result, "电视剧/小芳")

    def test_mixed_selection_uses_the_longest_common_parent(self):
        result = run_path_selection(
            "api.resolveSourcePath(["
            "{ is_dir: true, path: '电视剧/小芳', parent_path: '电视剧' },"
            "{ is_dir: false, path: '电视剧/另一部/E01.mkv', parent_path: '电视剧/另一部' }"
            "], '')"
        )

        self.assertEqual(result, "电视剧")

    def test_root_selection_keeps_an_empty_source_instead_of_using_filename(self):
        result = run_path_selection(
            "api.resolveSourcePath(["
            "{ is_dir: false, name: '电影.mkv', path: '电影.mkv', parent_path: '' }"
            "], '')"
        )

        self.assertEqual(result, "")

    def test_new_selection_is_unselected_and_composes_with_shared_rules(self):
        result = run_path_selection(
            "(() => { const selection = api.createSelection(["
            "{ is_dir: true, path: '媒体库/小芳 2026', parent_path: '媒体库' }"
            "], '媒体库'); const initialSelectedIndexes = selection.selectedIndexes.slice(); "
            "selection.selectedIndexes = [3,4,5]; return {"
            "source: selection.source, initialSelectedIndexes, selectedIndexes: selection.selectedIndexes, "
            "query: api.composeQuery(selection) }; })()"
        )

        self.assertEqual(result["source"], "媒体库/小芳 2026")
        self.assertEqual(result["initialSelectedIndexes"], [])
        self.assertEqual(result["selectedIndexes"], [3, 4, 5])
        self.assertEqual(result["query"], "小芳 2026")


class ScraperPathSelectionIntegrationTest(unittest.TestCase):
    def test_scraper_template_labels_the_full_path_selector_region(self):
        source = SCRAPER_TEMPLATE_PATH.read_text(encoding="utf-8")

        self.assertIn('id="scraper-candidate-list"', source)
        self.assertIn('aria-label="完整路径选词"', source)

    def test_shared_scripts_load_before_scraper_and_resource_consumers(self):
        source = INDEX_TEMPLATE_PATH.read_text(encoding="utf-8")

        text_selection_index = source.index("/static/js/modules/app/text-selection.js")
        path_selection_index = source.index("/static/js/modules/scraper/path-selection.js")
        app_index = source.index("/static/js/index.js")
        ed2k_index = source.index("/static/js/modules/resource/ed2k-import.js")
        self.assertLess(text_selection_index, path_selection_index)
        self.assertLess(path_selection_index, app_index)
        self.assertLess(text_selection_index, ed2k_index)

    def test_scraper_core_uses_path_tokens_instead_of_keyword_chips(self):
        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")

        self.assertIn("data-scraper-path-token-index", source)
        self.assertIn("complete-path-selection", source)
        self.assertIn("clear-path-selection", source)
        self.assertIn("reopen-path-selection", source)
        self.assertIn("重新选择 TMDB 搜索标题", source)
        self.assertNotIn("data-scraper-keyword", source)

    def test_backend_suggested_query_no_longer_fills_the_manual_input(self):
        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")
        start = source.index("function applyIdentifyManualSearchDefaults")
        end = source.index("\nfunction ", start + 1)
        function_body = source[start:end]

        self.assertNotIn("scraper-manual-query", function_body)
        self.assertNotIn("data.query", function_body)
        self.assertIn("data.media_type", function_body)

    def test_scraper_path_selector_has_responsive_day_and_night_styles(self):
        source = STYLESHEET_PATH.read_text(encoding="utf-8")

        self.assertIn(".scraper-path-tokens", source)
        self.assertIn(".scraper-path-token.is-selected", source)
        self.assertIn("html.theme-day .scraper-path-token", source)
        self.assertIn("overflow-wrap: anywhere", source)

    def test_completing_path_selection_clears_stale_tmdb_results_from_the_dom(self):
        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")
        start = source.index("function completeIdentifyPathSelection")
        end = source.index("\nfunction ", start + 1)
        function_body = source[start:end]

        self.assertIn("state.manualResults = [];", function_body)
        self.assertIn("renderIdentify();", function_body)


if __name__ == "__main__":
    unittest.main()
