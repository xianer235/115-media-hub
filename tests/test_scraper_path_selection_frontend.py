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

    def test_query_preserves_title_punctuation_but_flattens_path_separators(self):
        result = run_path_selection(
            "(() => { const selection = api.createSelection(["
            "{ is_dir: true, path: '电视剧/欧美/S.W.A.T. (2017)', parent_path: '电视剧/欧美' }"
            "], '电视剧/欧美'); selection.selectedIndexes = selection.tokens.map((_, index) => index); "
            "return api.composeQuery(selection); })()"
        )

        self.assertEqual(result, "电视剧 欧美 S.W.A.T. (2017)")


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

    def test_scraper_selection_actions_keep_six_main_buttons_on_one_row(self):
        stylesheet = STYLESHEET_PATH.read_text(encoding="utf-8")
        start = stylesheet.index("@media (max-width: 760px) {")
        end = stylesheet.index("html.theme-day .scraper-page", start)
        mobile_block = stylesheet[start:end]

        self.assertIn("repeat(6, minmax(0, 1fr))", mobile_block)
        self.assertNotIn("repeat(5", mobile_block)
        self.assertNotIn("repeat(4", mobile_block)

    def test_scraper_options_expose_language_and_subtitle_preserve_tags(self):
        template = SCRAPER_TEMPLATE_PATH.read_text(encoding="utf-8")

        self.assertIn('data-scraper-tag="language"', template)
        self.assertIn('data-scraper-tag="subtitle"', template)
        audio_index = template.index('data-scraper-tag="audio"')
        language_index = template.index('data-scraper-tag="language"')
        subtitle_index = template.index('data-scraper-tag="subtitle"')
        self.assertLess(audio_index, language_index)
        self.assertLess(language_index, subtitle_index)

    def test_scraper_folder_options_grouped_before_file_cleanup(self):
        template = SCRAPER_TEMPLATE_PATH.read_text(encoding="utf-8")

        season_index = template.index('id="scraper-use-season-subfolder"')
        tmdb_index = template.index('id="scraper-include-tmdb-id"')
        rename_index = template.index('id="scraper-rename-selected-folders"')
        delete_index = template.index('id="scraper-delete-ad-files"')
        structure_index = template.index(">文件夹</div>")
        file_naming_index = template.index(">文件命名</div>")
        cleanup_index = template.index("文件清理")

        self.assertLess(structure_index, file_naming_index)
        self.assertLess(file_naming_index, cleanup_index)
        self.assertLess(structure_index, cleanup_index)
        self.assertLess(structure_index, season_index)
        self.assertLess(rename_index, season_index)
        self.assertLess(season_index, tmdb_index)
        self.assertLess(cleanup_index, delete_index)

    def test_completing_path_selection_clears_stale_tmdb_results_from_the_dom(self):
        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")
        start = source.index("function completeIdentifyPathSelection")
        end = source.index("\nfunction ", start + 1)
        function_body = source[start:end]

        self.assertIn("state.manualResults = [];", function_body)
        self.assertIn("renderIdentify();", function_body)

    def test_batch_search_results_render_tmdb_poster_covers(self):
        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")
        start = source.index("function renderBatchItemSearch")
        end = source.index("\nfunction ", start + 1)
        function_body = source[start:end]

        self.assertIn("renderPoster(candidate)", function_body)

        stylesheet = STYLESHEET_PATH.read_text(encoding="utf-8")
        self.assertIn(".scraper-batch-result", stylesheet)
        self.assertIn(".scraper-result-poster", stylesheet)

    def test_preview_allows_manual_episode_override_for_unrecognized_files(self):
        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")

        self.assertIn("data-scraper-manual-episode-input", source)
        self.assertIn("apply-manual-episode", source)
        self.assertIn("clear-manual-episode", source)

    def test_scraper_search_filters_loaded_entries_without_remote_reload(self):
        source = SCRAPER_CORE_PATH.read_text(encoding="utf-8")
        template = SCRAPER_TEMPLATE_PATH.read_text(encoding="utf-8")

        display_start = source.index("function getDisplayEntries()")
        display_end = source.index("\nfunction renderSortButton", display_start)
        display_body = source[display_start:display_end]
        self.assertIn("state.search", display_body)
        self.assertIn("state.entries", display_body)

        search_start = source.index("if (action === 'search')")
        search_end = source.index("if (action === 'clear-search')", search_start)
        clear_end = source.index("closeToolPopovers();", search_end) + len("closeToolPopovers();")
        search_body = source[search_start:clear_end]
        self.assertNotIn("loadEntries(", search_body)

        keydown_start = source.index("$('scraper-search-input')?.addEventListener('keydown'")
        keydown_end = source.index("});", keydown_start) + len("});")
        self.assertNotIn("loadEntries(", source[keydown_start:keydown_end])
        self.assertIn('placeholder="筛选已加载条目"', template)


if __name__ == "__main__":
    unittest.main()
