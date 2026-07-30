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
                "电", "视", "剧", "摇", "滚", "兄", "弟", "私", "生", "活",
                "2024", "S03E01-E08", "完", "结",
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

    def test_title_tokenizer_splits_dot_connected_english_words(self):
        tokens = run_ed2k_frontend(
            "api.tokenizeTitle('Xiao.Fang.S01.2026.2160p.WEB-DL.H265.DDP5.1-BlackTV').map(item => item.text)"
        )

        self.assertEqual(
            tokens,
            ["Xiao", "Fang", "S01", "2026", "2160p", "WEB-DL", "H265", "DDP5", "1-BlackTV"],
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
            "return api.composeFolderName(tokens, [3,4,5,6,7,8,9,10,11]); })()"
        )

        self.assertEqual(result, "摇滚兄弟私生活 2024 S03E01-E08")

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
