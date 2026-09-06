import json
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_SELECTION_PATH = ROOT / "static/js/modules/app/text-selection.js"
MODULE_PATH = ROOT / "static/js/modules/resource/ed2k-import.js"
MODAL_MODULE_PATH = ROOT / "static/js/modules/resource/import-modal.js"
BROWSER_MODULE_PATH = ROOT / "static/js/modules/resource/browser.js"
FOLDER_API_MODULE_PATH = ROOT / "static/js/modules/resource/folder-api.js"
TEMPLATE_PATH = ROOT / "templates/partials/modals/resource_import.html"
CSS_PATH = ROOT / "static/css/index.css"


class IdHierarchyParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.ancestors = {}

    def handle_starttag(self, tag, attrs):
        node_id = dict(attrs).get("id", "")
        self.stack.append((tag, node_id))
        if node_id:
            self.ancestors[node_id] = [
                item_id for _, item_id in self.stack[:-1] if item_id
            ]

    def handle_startendtag(self, tag, attrs):
        node_id = dict(attrs).get("id", "")
        if node_id:
            self.ancestors[node_id] = [
                item_id for _, item_id in self.stack if item_id
            ]

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return


def run_ed2k_frontend(expression: str):
    script = f"""
const fs = require('fs');
const vm = require('vm');
const context = {{ window: {{}} }};
vm.createContext(context);
vm.runInContext(fs.readFileSync({json.dumps(str(TEXT_SELECTION_PATH))}, 'utf8'), context);
vm.runInContext(fs.readFileSync({json.dumps(str(MODULE_PATH))}, 'utf8'), context);
const sharedApi = context.window.MediaHubTextSelection;
const api = context.window.ResourceEd2kImport;
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


def render_share_browser_visibility(*, ed2k_mode: bool, is_share: bool):
    script = f"""
const fs = require('fs');
const vm = require('vm');

function createClassList(initial = []) {{
    const values = new Set(initial);
    return {{
        toggle(name, force) {{
            if (force === undefined ? !values.has(name) : force) values.add(name);
            else values.delete(name);
        }},
        add(name) {{ values.add(name); }},
        remove(name) {{ values.delete(name); }},
        contains(name) {{ return values.has(name); }},
    }};
}}

const elements = {{
    'resource-share-browser-card': {{ classList: createClassList(['hidden']) }},
    'resource-share-tree': {{ dataset: {{}}, innerHTML: '', scrollTop: 0 }},
    'resource-share-root-title': {{ innerHTML: '' }},
}};
const context = {{
    window: {{}},
    document: {{ getElementById: id => elements[id] || null }},
}};
vm.createContext(context);
vm.runInContext(fs.readFileSync({json.dumps(str(BROWSER_MODULE_PATH))}, 'utf8'), context);
context.window.ResourceBrowser.renderResourceShareBrowser({{
    resourceModalMode: 'import',
    showResourceShareBrowser: {json.dumps(not ed2k_mode)},
    resourceShareCurrentCid: '0',
    resourceShareSearchKeyword: '',
    resourceShareLoadingParents: {{}},
    resourceShareLoadingMoreParents: {{}},
    resourceShareHasMoreByParent: {{}},
    resourceShareDiagnosticsByParent: {{}},
    resourceShareTrail: [],
    resourceShareLoading: false,
    resourceShareError: '',
    resourceShareRootLoaded: false,
    resourceModalLinkType: {json.dumps('115' if is_share else 'ed2k')},
    isCurrentResource115Share: () => {json.dumps(is_share)},
    getResourceProviderLabel: () => '115',
    getCurrentResourceProvider: () => '115',
    syncResourceShareReceiveCodeSection: () => {{}},
    renderResourceImportBehaviorHint: () => {{}},
    renderResourceImportSummary: () => {{}},
    getCurrentResourceShareEntries: () => [],
    getFilteredCurrentResourceShareEntries: () => [],
    isLinkTypeCookieConfigured: () => true,
    isResourceShareEntryEffectivelySelected: () => false,
    escapeHtml: value => String(value),
}});
process.stdout.write(JSON.stringify({{
    hidden: elements['resource-share-browser-card'].classList.contains('hidden'),
}}));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


class ResourceEd2kFrontendLogicTest(unittest.TestCase):
    @staticmethod
    def modal_function_body(name: str) -> str:
        source = MODAL_MODULE_PATH.read_text(encoding="utf-8")
        marker = f"        function {name}("
        start = source.index(marker)
        next_function = source.find("\n        function ", start + len(marker))
        return source[start:next_function if next_function >= 0 else len(source)]

    def test_title_tokenizer_splits_chinese_and_keeps_season_range(self):
        tokens = run_ed2k_frontend(
            "api.tokenizeTitle('📺 电视剧：摇滚兄弟私生活 (2024) - S03E01-E08(完结)').map(item => item.text)"
        )

        self.assertEqual(
            tokens,
            [
                "电", "视", "剧", "：", "摇", "滚", "兄", "弟", "私", "生", "活",
                "(", "2024", ")", "-", "S03E01", "-", "E08", "(", "完", "结", ")",
            ],
        )

    def test_ed2k_title_selection_uses_shared_text_selection_api(self):
        result = run_ed2k_frontend(
            "({ sharedTokens: sharedApi.tokenize('摇滚兄弟 S03').map(item => item.text), "
            "ed2kTokens: api.tokenizeTitle('摇滚兄弟 S03').map(item => item.text), "
            "sharedTitle: sharedApi.compose(sharedApi.tokenize('摇滚兄弟 S03'), [0,1,2,3,4]), "
            "ed2kTitle: api.composeFolderName(api.tokenizeTitle('摇滚兄弟 S03'), [0,1,2,3,4]) })"
        )

        self.assertEqual(result["sharedTokens"], result["ed2kTokens"])
        self.assertEqual(result["sharedTitle"], result["ed2kTitle"])

    def test_tokenizer_exposes_legal_punctuation_as_independent_tokens(self):
        result = run_ed2k_frontend(
            "api.tokenizeTitle('🎬 电影：奇谭：纸刃渡荒墟 (2026)').map(item => item.text)"
        )

        self.assertEqual(
            result,
            [
                "电", "影", "：", "奇", "谭", "：", "纸", "刃", "渡", "荒", "墟",
                "(", "2026", ")",
            ],
        )

    def test_title_tokenizer_exposes_dot_and_hyphen_as_independent_tokens(self):
        tokens = run_ed2k_frontend(
            "api.tokenizeTitle('Xiao.Fang.S01.2026.2160p.WEB-DL.H265.DDP5.1-BlackTV').map(item => item.text)"
        )

        self.assertEqual(
            tokens,
            [
                "Xiao", ".", "Fang", ".", "S01", ".", "2026", ".", "2160p", ".",
                "WEB", "-", "DL", ".", "H265", ".", "DDP5", ".", "1", "-", "BlackTV",
            ],
        )

    def test_drag_range_selects_and_deselects_contiguous_tokens(self):
        result = run_ed2k_frontend(
            "(() => { let selected = api.applySelectionRange([], 3, 9, true); "
            "selected = api.applySelectionRange(selected, 5, 7, false); return selected; })()"
        )

        self.assertEqual(result, [3, 4, 8, 9])

    def test_selected_title_tokens_compose_readable_folder_name(self):
        result = run_ed2k_frontend(
            "(() => { const tokens = api.tokenizeTitle('📺 电视剧：摇滚兄弟私生活 (2024) - S03E01-E08(完结)'); "
            "return api.composeFolderName(tokens, Array.from({ length: 14 }, (_, index) => index + 4)); })()"
        )

        self.assertEqual(result, "摇滚兄弟私生活 (2024) - S03E01-E08")

    def test_title_composer_preserves_colon_and_balanced_parentheses(self):
        result = run_ed2k_frontend(
            "(() => { const tokens = api.tokenizeTitle('碟中谍：最终清算 (2025)'); "
            "return { full: api.composeFolderName(tokens, tokens.map((_, index) => index)), "
            "year: api.composeFolderName(tokens, [9]), "
            "yearWithBrackets: api.composeFolderName(tokens, [8,9,10]) }; })()"
        )

        self.assertEqual(result["full"], "碟中谍：最终清算 (2025)")
        self.assertEqual(result["year"], "2025")
        self.assertEqual(result["yearWithBrackets"], "(2025)")

    def test_title_composer_preserves_balanced_square_brackets(self):
        result = run_ed2k_frontend(
            "(() => { const tokens = api.tokenizeTitle('标题 [tmdbid-123]'); "
            "return { open: api.composeFolderName(tokens, [2]), "
            "full: api.composeFolderName(tokens, [2,3,4,5,6]) }; })()"
        )

        self.assertEqual(result["open"], "[")
        self.assertEqual(result["full"], "[tmdbid-123]")

    def test_title_composer_preserves_chinese_bracket_pairs(self):
        result = run_ed2k_frontend(
            "(() => { const roundTokens = api.tokenizeTitle('标题（2025）'); "
            "const squareTokens = api.tokenizeTitle('标题【tmdbid-123】'); "
            "return { round: api.composeFolderName(roundTokens, [2,3,4]), "
            "square: api.composeFolderName(squareTokens, [2,3,4,5,6]) }; })()"
        )

        self.assertEqual(result["round"], "（2025）")
        self.assertEqual(result["square"], "【tmdbid-123】")

    def test_title_composer_omits_punctuation_across_unselected_words(self):
        result = run_ed2k_frontend(
            "(() => { const tokens = api.tokenizeTitle('标题：广告：正片'); "
            "return api.composeFolderName(tokens, [0,1,6,7]); })()"
        )

        self.assertEqual(result, "标题 正片")

    def test_title_composer_does_not_restore_unselectable_characters(self):
        result = run_ed2k_frontend(
            "(() => { const tokens = api.tokenizeTitle('片*名🎬/正?文'); "
            "return { tokens: tokens.map(item => item.text), "
            "folderName: api.composeFolderName(tokens, tokens.map((_, index) => index)) }; })()"
        )

        self.assertEqual(result["tokens"], ["片", "名", "正", "文"])
        self.assertEqual(result["folderName"], "片名 正文")

    def test_folder_name_normalizer_preserves_colon_and_replaces_unsafe_characters(self):
        result = run_ed2k_frontend(
            "typeof api.normalizeFolderName === 'function' "
            "? api.normalizeFolderName('  碟中谍: 最终清算 / *?\"<>|  ') : null"
        )

        self.assertEqual(result, "碟中谍: 最终清算 ＊？＂＜＞｜")

    def test_folder_name_normalizer_handles_controls_fallback_and_length(self):
        result = run_ed2k_frontend(
            "typeof api.normalizeFolderName === 'function' ? ({ "
            "control: api.normalizeFolderName('片' + String.fromCharCode(1) + '名'), "
            "dot: api.normalizeFolderName('..'), "
            "fallback: api.normalizeFolderName('..', '未命名'), "
            "long: api.normalizeFolderName('片'.repeat(121)) }) : null"
        )

        self.assertEqual(
            result,
            {
                "control": "片名",
                "dot": "",
                "fallback": "未命名",
                "long": "片" * 120,
            },
        )

    def test_title_completion_normalizes_the_folder_name(self):
        body = self.modal_function_body("completeResourceEd2kTitleSelection")

        self.assertIn("normalizeFolderName", body)

    def test_submit_normalizes_and_writes_back_the_folder_name(self):
        source = MODAL_MODULE_PATH.read_text(encoding="utf-8")
        start = source.index("                if (isResourceEd2kImportActive()) {")
        end = source.index("rememberResourceRefreshDelaySeconds", start)
        submit_body = source[start:end]

        self.assertIn("normalizeFolderName", submit_body)
        self.assertIn("resourceEd2kState.folderName = folderName;", submit_body)
        self.assertIn("folderNameInput.value = folderName;", submit_body)
        self.assertIn("syncResourceMonitorTaskOptions", submit_body)
        self.assertLess(
            submit_body.index("syncResourceMonitorTaskOptions"),
            submit_body.index("postJson('/resource/ed2k/jobs/create-batch'"),
        )

    def test_target_path_uses_optional_child_folder(self):
        result = run_ed2k_frontend(
            "({ withFolder: api.buildTargetSavepath('电视剧', '摇滚兄弟私生活 (2024) - S03', true), "
            "withoutFolder: api.buildTargetSavepath('电视剧', '忽略此名称', false) })"
        )

        self.assertEqual(result["withFolder"], "电视剧/摇滚兄弟私生活 (2024) - S03")
        self.assertEqual(result["withoutFolder"], "电视剧")

    def test_title_selector_visibility_requires_child_folder_creation(self):
        result = run_ed2k_frontend(
            "typeof api.shouldShowTitleSelector === 'function' ? "
            "({ enabled: api.shouldShowTitleSelector(true, true, true), "
            "disabled: api.shouldShowTitleSelector(true, true, false), "
            "loading: api.shouldShowTitleSelector(true, false, true), "
            "inactive: api.shouldShowTitleSelector(false, true, true) }) : "
            "({ missing: true })"
        )

        self.assertEqual(
            result,
            {
                "enabled": True,
                "disabled": False,
                "loading": False,
                "inactive": False,
            },
        )

    def test_title_selector_is_inside_folder_controls_not_file_column(self):
        parser = IdHierarchyParser()
        parser.feed(TEMPLATE_PATH.read_text(encoding="utf-8"))

        self.assertIn(
            "resource-import-main-column",
            parser.ancestors["resource-ed2k-files-section"],
        )
        self.assertNotIn(
            "resource-import-main-column",
            parser.ancestors["resource-ed2k-title-section"],
        )
        self.assertIn(
            "resource-import-save-panel",
            parser.ancestors["resource-ed2k-title-section"],
        )
        self.assertIn(
            "resource-ed2k-folder-section",
            parser.ancestors["resource-ed2k-title-section"],
        )

    def test_direct_ed2k_link_becomes_a_single_file_item(self):
        result = run_ed2k_frontend(
            "api.parseEd2kLink('ed2k://|file|%E6%91%87%E6%BB%9A%E5%85%84%E5%BC%9F.S03E01.mkv|1024|af33bd45b385b16a4bef434c760e0182|/')"
        )

        self.assertEqual(result["filename"], "摇滚兄弟.S03E01.mkv")
        self.assertEqual(result["size_bytes"], 1024)
        self.assertEqual(result["link_type"], "ed2k")

    def test_collect_direct_ed2k_items_preserves_post_order_and_skips_duplicates(self):
        first_link = "ed2k://|file|Episode-01.mkv|1024|af33bd45b385b16a4bef434c760e0182|/"
        second_link = "ed2k://|file|Episode-02.mkv|2048|a93b3760ed987f48e95dc5e36ea49fee|/"
        duplicate_link = first_link.replace("Episode-01", "Duplicate-name")
        result = run_ed2k_frontend(
            "typeof api.collectDirectEd2kItems === 'function' ? api.collectDirectEd2kItems({"
            f"extra: {{ all_links: [{json.dumps(first_link)}, 'https://example.com/file', "
            f"'ed2k://|file|broken|1|bad|/', {json.dumps(second_link)}, {json.dumps(duplicate_link)}] }}, "
            f"link_url: {json.dumps(first_link)}"
            "}).map(item => ({ id: item.id, link_url: item.link_url })) : null"
        )

        self.assertEqual(
            result,
            [
                {"id": "af33bd45b385b16a4bef434c760e0182:1024", "link_url": first_link},
                {"id": "a93b3760ed987f48e95dc5e36ea49fee:2048", "link_url": second_link},
            ],
        )

    def test_collect_direct_ed2k_items_falls_back_to_legacy_primary_link(self):
        link = "ed2k://|file|Legacy.mkv|1024|af33bd45b385b16a4bef434c760e0182|/"

        result = run_ed2k_frontend(
            "typeof api.collectDirectEd2kItems === 'function' ? "
            f"api.collectDirectEd2kItems({{ link_url: {json.dumps(link)} }}) : null"
        )

        self.assertEqual([item["link_url"] for item in result or []], [link])

    def test_folder_title_source_prefers_ed2k_filename_for_generic_record_title(self):
        result = run_ed2k_frontend("""
        (() => {
            const link = 'ed2k://|file|测试.片名.2026.1080p.mkv|12345|af33bd45b385b16a4bef434c760e0182|/';
            const item = { title: 'ED2K任务', link_url: link, extra: {} };
            const items = api.collectDirectEd2kItems(item);
            return {
                generic: api.isGenericResourceTitle('ED2K任务'),
                named: api.isGenericResourceTitle('测试.片名.2026.1080p.mkv'),
                titleSource: api.resolveFolderTitleSource(item, items),
            };
        })()
        """)
        self.assertTrue(result["generic"])
        self.assertFalse(result["named"])
        self.assertEqual(result["titleSource"], "测试.片名.2026.1080p.mkv")

    def test_direct_modal_title_resolution_falls_back_to_filename(self):
        source = MODAL_MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("resolveFolderTitleSource(item, items)", source)
        self.assertIn("importMode === 'ed2k-direct'", source)

    def test_resource_folder_recommendation_gated_to_link_type(self):
        source = MODAL_MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("function isResourceRecommendedFolderCandidate(", source)
        self.assertIn("return ['ed2k', 'magnet'].includes(linkType);", source)
        self.assertIn("getEffectiveResourceLinkType(item)", source)
        self.assertIn("applyResourceRecommendedFolderName();", source)

    def test_resource_folder_recommendation_falls_back_to_recognized_title(self):
        source = MODAL_MODULE_PATH.read_text(encoding="utf-8")
        folder_name = source[
            source.index("function getResourceRecommendedFolderName("):
            source.index("function applyResourceRecommendedFolderName(")
        ]
        self.assertIn("resourceEd2kState?.folderName", folder_name)
        self.assertIn("resourceEd2kState?.titleText || item?.title", folder_name)
        self.assertIn("fetchRecommendedFolderName(rawTitle, year, String(item?.raw_text || ''))", folder_name)

    def test_resource_folder_recommendation_uses_scraper_endpoint(self):
        source = MODAL_MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("async function fetchRecommendedFolderName(", source)
        self.assertIn("/resource/items/recommend_folder_name", source)
        self.assertIn("return fetchRecommendedFolderName(", source)
        self.assertIn("await getRecommendedResourceEd2kFolderName()", source)
        self.assertIn("await getResourceRecommendedFolderName()", source)

    def test_ed2k_folder_name_auto_recommends_on_resolve(self):
        source = MODAL_MODULE_PATH.read_text(encoding="utf-8")
        resolve_body = source[
            source.index("function applyResourceEd2kResolvedData("):
            source.index("async function initializeResourceEd2kImport(")
        ]
        self.assertIn("getRecommendedResourceEd2kFolderName()", resolve_body)
        self.assertIn("resourceEd2kState.folderName = recommendedFolderName;", resolve_body)
        self.assertIn("folderNameInput.value = recommendedFolderName;", resolve_body)

    def test_ed2k_folder_recommend_button_in_template(self):
        source = MODAL_MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("function applyRecommendedResourceEd2kFolderName(", source)
        self.assertIn("function getRecommendedResourceEd2kFolderName(", source)
        html = TEMPLATE_PATH.read_text(encoding="utf-8")
        self.assertIn('id="resource-ed2k-recommend-btn"', html)
        self.assertIn('onclick="applyRecommendedResourceEd2kFolderName()"', html)

    def test_ed2k_folder_input_row_grid_has_three_columns(self):
        css = CSS_PATH.read_text(encoding="utf-8")
        row_css = css[css.index(".resource-ed2k-folder-input-row {"):]
        self.assertIn("grid-template-columns: minmax(0, 1fr) auto 42px;", row_css)
        self.assertNotIn("grid-template-columns: minmax(0, 1fr) 42px;", row_css)

    def test_resource_folder_recommendation_button_in_template(self):
        html = TEMPLATE_PATH.read_text(encoding="utf-8")
        self.assertIn('id="resource-folder-recommend-btn"', html)
        self.assertIn('onclick="applyResourceRecommendedFolderName()"', html)

    def test_direct_ed2k_modal_initialization_uses_collected_items(self):
        source = MODAL_MODULE_PATH.read_text(encoding="utf-8")

        self.assertIn("collectDirectEd2kItems(item)", source)

    def test_frequent_ed2k_edits_do_not_redraw_the_whole_modal(self):
        for function_name in (
            "updateResourceEd2kFolderName",
            "setResourceEd2kFileChecked",
            "setAllResourceEd2kFilesChecked",
        ):
            with self.subTest(function_name=function_name):
                self.assertNotIn(
                    "renderResourceModalLayout",
                    self.modal_function_body(function_name),
                )

    def test_ed2k_import_hides_share_browser_but_normal_share_keeps_it(self):
        folder_api_source = FOLDER_API_MODULE_PATH.read_text(encoding="utf-8")

        self.assertIn("showResourceShareBrowser", folder_api_source)
        self.assertTrue(
            render_share_browser_visibility(ed2k_mode=True, is_share=False)["hidden"]
        )
        self.assertFalse(
            render_share_browser_visibility(ed2k_mode=False, is_share=True)["hidden"]
        )


if __name__ == "__main__":
    unittest.main()
