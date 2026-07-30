# Scraper Path Token Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace scraper keyword suggestion chips with a reusable explosion-style selector whose source is the selected folder's full path and whose result fills the TMDB query input.

**Architecture:** Extract the ED2K tokenizer, range selection, and readable composition into an app-level pure JavaScript module. Add a small scraper-specific path resolver that chooses the selected folder path or the common parent path, then let the existing scraper core own only DOM rendering and gestures. Keep `/scraper/identify` compatible while stopping its suggested query from silently filling the manual input.

**Tech Stack:** Vanilla JavaScript, FastAPI/Jinja templates, CSS, Python `unittest`, Node `vm`, in-app Browser.

---

### Task 1: Extract the reusable text-selection engine

**Files:**
- Create: `static/js/modules/app/text-selection.js`
- Modify: `static/js/modules/resource/ed2k-import.js`
- Modify: `templates/index.html`
- Modify: `tests/test_resource_ed2k_frontend.py`

- [ ] **Step 1: Update the ED2K test harness to require a shared module**

Load `text-selection.js` before `ed2k-import.js`, then assert the public common API and the existing ED2K wrappers return identical tokens and composed text:

```python
TEXT_SELECTION_PATH = ROOT / "static/js/modules/app/text-selection.js"

vm.runInContext(fs.readFileSync({json.dumps(str(TEXT_SELECTION_PATH))}, 'utf8'), context);
vm.runInContext(fs.readFileSync({json.dumps(str(MODULE_PATH))}, 'utf8'), context);

def test_ed2k_uses_shared_text_selection_api(self):
    result = run_ed2k_frontend(
        "({ shared: context.window.MediaHubTextSelection.tokenize('摇滚兄弟 S03').map(x => x.text), "
        "ed2k: api.tokenizeTitle('摇滚兄弟 S03').map(x => x.text) })"
    )
    self.assertEqual(result["shared"], result["ed2k"])
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
.venv/bin/python -m unittest tests.test_resource_ed2k_frontend
```

Expected: FAIL because `static/js/modules/app/text-selection.js` and `window.MediaHubTextSelection` do not exist.

- [ ] **Step 3: Add the common pure API and delegate ED2K wrappers**

Expose one immutable global API:

```javascript
(function (global) {
    'use strict';

    const CJK_TOKEN_REGEX = /^[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]$/u;
    const TEXT_TOKEN_REGEX = /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]|[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*/gu;

    function tokenize(value) {
        const source = String(value || '');
        return Array.from(source.matchAll(TEXT_TOKEN_REGEX), match => ({
            text: match[0],
            start: Number(match.index || 0),
            end: Number(match.index || 0) + match[0].length,
            source,
            isCjk: CJK_TOKEN_REGEX.test(match[0]),
        }));
    }

    function applySelectionRange(selectedIndexes, startIndex, endIndex, shouldSelect) {
        const selected = new Set(
            (Array.isArray(selectedIndexes) ? selectedIndexes : [])
                .map(Number)
                .filter(value => Number.isInteger(value) && value >= 0)
        );
        const start = Math.max(0, Math.min(Number(startIndex) || 0, Number(endIndex) || 0));
        const end = Math.max(0, Math.max(Number(startIndex) || 0, Number(endIndex) || 0));
        for (let index = start; index <= end; index += 1) {
            if (shouldSelect) selected.add(index);
            else selected.delete(index);
        }
        return Array.from(selected).sort((left, right) => left - right);
    }

    function compose(tokens, selectedIndexes) {
        const selected = new Set((Array.isArray(selectedIndexes) ? selectedIndexes : []).map(Number));
        const chosen = (Array.isArray(tokens) ? tokens : [])
            .map((token, index) => ({ token, index }))
            .filter(item => selected.has(item.index));
        let result = '';
        let previous = null;
        chosen.forEach(item => {
            if (previous) {
                const source = String(item.token.source || previous.token.source || '');
                const gap = source.slice(Number(previous.token.end || 0), Number(item.token.start || 0));
                const adjacentCjk = item.index === previous.index + 1
                    && gap === ''
                    && previous.token.isCjk
                    && item.token.isCjk;
                if (!adjacentCjk && result && !result.endsWith(' ')) result += ' ';
            }
            result += String(item.token.text || '');
            previous = item;
        });
        return result.replace(/\s+/g, ' ').trim();
    }

    global.MediaHubTextSelection = Object.freeze({
        applySelectionRange,
        compose,
        tokenize,
    });
})(window);
```

In `ResourceEd2kImport`, retain `tokenizeTitle`, `applySelectionRange`, and `composeFolderName` as compatibility wrappers around `MediaHubTextSelection`. Add the new script before all resource modules in `templates/index.html`.

- [ ] **Step 4: Run focused tests and JavaScript syntax checks**

Run:

```bash
.venv/bin/python -m unittest tests.test_resource_ed2k_frontend
node --check static/js/modules/app/text-selection.js
node --check static/js/modules/resource/ed2k-import.js
```

Expected: all ED2K frontend tests pass and both scripts parse successfully.

- [ ] **Step 5: Commit the shared engine checkpoint**

```bash
git add static/js/modules/app/text-selection.js static/js/modules/resource/ed2k-import.js templates/index.html tests/test_resource_ed2k_frontend.py
git commit -m "重构通用标题选词工具"
```

### Task 2: Resolve the scraper path source independently

**Files:**
- Create: `static/js/modules/scraper/path-selection.js`
- Create: `tests/test_scraper_path_selection_frontend.py`
- Modify: `templates/index.html`

- [ ] **Step 1: Write path-source and composition tests**

Use Node `vm` to load the common module and scraper helper. Cover these exact inputs:

```javascript
api.resolveSourcePath([
  { is_dir: true, path: '电视剧/小芳 (2026)', parent_path: '电视剧' }
], '电视剧') === '电视剧/小芳 (2026)'

api.resolveSourcePath([
  { is_dir: false, path: '电视剧/小芳/S01E01.mkv', parent_path: '电视剧/小芳' },
  { is_dir: false, path: '电视剧/小芳/S01E02.mkv', parent_path: '电视剧/小芳' }
], '电视剧/小芳') === '电视剧/小芳'

api.resolveSourcePath([
  { is_dir: true, path: '电视剧/小芳', parent_path: '电视剧' },
  { is_dir: false, path: '电视剧/另一部/E01.mkv', parent_path: '电视剧/另一部' }
], '') === '电视剧'
```

Also require `createSelection()` to produce no selected indexes by default and `composeQuery()` to use `MediaHubTextSelection.compose()`.

- [ ] **Step 2: Run the new test and verify RED**

Run:

```bash
.venv/bin/python -m unittest tests.test_scraper_path_selection_frontend
```

Expected: FAIL because `path-selection.js` does not exist.

- [ ] **Step 3: Implement the focused scraper helper**

Expose:

```javascript
window.ScraperPathSelection = Object.freeze({
    composeQuery(selection),
    createSelection(entries, currentParentPath),
    resolveSourcePath(entries, currentParentPath),
});
```

`resolveSourcePath()` returns the only selected directory's own normalized path. For every other selection shape it derives each item's parent path and returns their longest shared folder prefix, including an empty string for the root. `createSelection()` tokenizes that path with the common engine and initializes `selectedIndexes: []` and `expanded: true`.

- [ ] **Step 4: Register the helper and verify GREEN**

Add `path-selection.js` after `text-selection.js` in `templates/index.html` and run:

```bash
.venv/bin/python -m unittest tests.test_scraper_path_selection_frontend
node --check static/js/modules/scraper/path-selection.js
```

Expected: all path-source tests pass and the helper parses successfully.

- [ ] **Step 5: Commit the path resolver checkpoint**

```bash
git add static/js/modules/scraper/path-selection.js templates/index.html tests/test_scraper_path_selection_frontend.py
git commit -m "增加刮削完整路径选词模型"
```

### Task 3: Replace scraper keyword chips with the path selector

**Files:**
- Modify: `static/js/modules/scraper/core.js`
- Modify: `templates/partials/pages/scraper.html`
- Modify: `static/css/index.css`
- Modify: `tests/test_scraper_path_selection_frontend.py`

- [ ] **Step 1: Add failing integration assertions**

Require the template to label `#scraper-candidate-list` as full-path selection and the scraper source to contain the new token, completion, clear, and reselect actions while no longer rendering `data-scraper-keyword`. Assert that applying identify defaults does not assign `identifyResult.query` to `#scraper-manual-query`.

```python
self.assertIn('aria-label="完整路径选词"', template_source)
self.assertIn('data-scraper-path-token-index', core_source)
self.assertIn("complete-path-selection", core_source)
self.assertIn("reopen-path-selection", core_source)
self.assertNotIn("data-scraper-keyword", core_source)
```

- [ ] **Step 2: Run integration tests and verify RED**

Run:

```bash
.venv/bin/python -m unittest tests.test_scraper_path_selection_frontend
```

Expected: FAIL because the old keyword-chip renderer is still present.

- [ ] **Step 3: Add path-selection state and rendering**

Add `identifyPathSelection` and `identifyPathGesture` to scraper state. Initialize them from `getEffectiveSelectedEntries()` before `/scraper/identify` is requested, reset them whenever selection context is invalidated, and render:

```html
<div class="scraper-path-selector">
  <div class="scraper-path-source">完整路径 电视剧/小芳 (2026)</div>
  <div class="scraper-path-tokens" role="listbox" aria-label="完整路径标题选词">
    <button class="scraper-path-token is-selected" data-scraper-path-token-index="0" role="option"></button>
  </div>
  <div class="scraper-path-actions">
    <button data-scraper-action="clear-path-selection">清空</button>
    <button data-scraper-action="complete-path-selection">完成选词</button>
  </div>
</div>
```

When collapsed, show the composed value and a Lucide-style existing edit/reselect icon button with `aria-label="重新选择 TMDB 搜索标题"`. Keep the manual input untouched until `complete-path-selection` runs.

- [ ] **Step 4: Add pointer range selection and preserve manual edits**

On pointer down, snapshot the base indexes and decide whether the gesture selects or deselects. On pointer move, use `document.elementFromPoint()` and the common `applySelectionRange()` API. End on pointer up/cancel. Completing selection writes the composed query once, focuses the manual input, and collapses the selector; reopening does not write the input.

- [ ] **Step 5: Add responsive day/night styles**

Use square 7px token corners, stable minimum token dimensions, `flex-wrap`, `touch-action: none`, and `overflow-wrap: anywhere`. Add explicit day-theme selected/unselected colors and a mobile rule that keeps actions and tokens within the viewport without horizontal scrolling.

- [ ] **Step 6: Run focused tests and syntax checks**

Run:

```bash
.venv/bin/python -m unittest tests.test_resource_ed2k_frontend tests.test_scraper_path_selection_frontend
node --check static/js/modules/app/text-selection.js
node --check static/js/modules/scraper/path-selection.js
node --check static/js/modules/scraper/core.js
node --check static/js/modules/resource/ed2k-import.js
```

Expected: all focused tests pass and all changed scripts parse successfully.

- [ ] **Step 7: Commit the scraper UI checkpoint**

```bash
git add static/js/modules/scraper/core.js templates/partials/pages/scraper.html static/css/index.css tests/test_scraper_path_selection_frontend.py
git commit -m "接入刮削完整路径大爆炸选词"
```

### Task 4: Full verification and collaboration handoff

**Files:**
- Modify: `docs/superpowers/handoff.md`

- [ ] **Step 1: Run the project verification suite**

```bash
PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m compileall app main.py
git diff --check
```

Expected: the full unittest suite passes, compileall reports no errors, and the diff check is silent.

- [ ] **Step 2: Verify the rendered flow in the in-app Browser**

The flow under test is: `#tab=scraper` -> select a folder or files -> click `识别` -> select path tokens -> click `完成选词` -> verify the TMDB search field contains only the selected title -> edit it -> reopen selection -> verify the edit remains until completing again.

At desktop and `390x844`, check page identity, meaningful DOM, no framework overlay, console errors/warnings, screenshot evidence, pointer selection, dark/day themes, and document/modal horizontal overflow.

- [ ] **Step 3: Append the required handoff entry**

Append one timestamped line describing the common text engine, scraper path rules, UI behavior, tests, browser evidence, and next step to `docs/superpowers/handoff.md`.

- [ ] **Step 4: Re-run final lightweight checks**

```bash
.venv/bin/python -m unittest tests.test_resource_ed2k_frontend tests.test_scraper_path_selection_frontend
git diff --check
git status --short --branch
```

Expected: focused tests pass, diff check is silent, and only intended handoff/implementation files remain in the final checkpoint.

- [ ] **Step 5: Commit the verification handoff**

```bash
git add docs/superpowers/handoff.md
git commit -m "记录刮削路径选词验证结果"
```
