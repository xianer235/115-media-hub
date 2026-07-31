# Shared Text Selection Punctuation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve original semantic punctuation for manual text selection in both ED2K folder naming and scraper TMDB queries, while converting path separators to spaces and safely normalizing ED2K folder names.

**Architecture:** `MediaHubTextSelection` remains the single owner of token positions, legal-punctuation tokenization, exact contiguous-range composition, and path-separator normalization. `ResourceEd2kImport` adds ED2K-only folder normalization used before display and submission; `app.resource_ed2k` applies the same deterministic policy as backend defense. Scraper code continues consuming the shared tokenizer and composer unchanged.

> **2026-07-31 follow-up:** User feedback requires legal punctuation to appear as independent selectable boxes. Task 4 supersedes Task 1's earlier balanced-boundary expansion details; no hidden bracket completion remains.

**Tech Stack:** Browser JavaScript modules, Node `vm` logic tests, Python 3, FastAPI route tests, `unittest`.

---

### Task 1: Shared Punctuation-Aware Composition

**Files:**
- Modify: `tests/test_resource_ed2k_frontend.py`
- Modify: `tests/test_scraper_path_selection_frontend.py`
- Modify: `static/js/modules/app/text-selection.js`

- [ ] **Step 1: Write failing ED2K composition tests**

Change the existing readable-folder assertion to:

```python
self.assertEqual(result, "摇滚兄弟私生活 (2024) - S03E01-E08")
```

Add tests through `run_ed2k_frontend()` for these exact results:

```python
def test_title_composer_preserves_colon_and_balanced_parentheses(self):
    result = run_ed2k_frontend(
        "(() => { const tokens = api.tokenizeTitle('碟中谍：最终清算 (2025)'); "
        "return { full: api.composeFolderName(tokens, tokens.map((_, index) => index)), "
        "year: api.composeFolderName(tokens, [7]) }; })()"
    )
    self.assertEqual(result["full"], "碟中谍：最终清算 (2025)")
    self.assertEqual(result["year"], "(2025)")

def test_title_composer_preserves_balanced_square_brackets(self):
    result = run_ed2k_frontend(
        "(() => { const tokens = api.tokenizeTitle('标题 [tmdbid-123]'); "
        "return api.composeFolderName(tokens, [2]); })()"
    )
    self.assertEqual(result, "[tmdbid-123]")

def test_title_composer_omits_punctuation_across_unselected_words(self):
    result = run_ed2k_frontend(
        "(() => { const tokens = api.tokenizeTitle('标题：广告：正片'); "
        "return api.composeFolderName(tokens, [0,1,4,5]); })()"
    )
    self.assertEqual(result, "标题 正片")
```

- [ ] **Step 2: Write a failing scraper path test**

Add to `ScraperPathSelectionLogicTest`:

```python
def test_query_preserves_title_punctuation_but_flattens_path_separators(self):
    result = run_path_selection(
        "(() => { const selection = api.createSelection(["
        "{ is_dir: true, path: '电视剧/欧美/S.W.A.T. (2017)', parent_path: '电视剧/欧美' }"
        "], '电视剧/欧美'); selection.selectedIndexes = selection.tokens.map((_, index) => index); "
        "return api.composeQuery(selection); })()"
    )
    self.assertEqual(result, "电视剧 欧美 S.W.A.T. (2017)")
```

- [ ] **Step 3: Run tests and verify RED**

```bash
PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m unittest \
  tests.test_resource_ed2k_frontend.ResourceEd2kFrontendLogicTest \
  tests.test_scraper_path_selection_frontend.ScraperPathSelectionLogicTest
```

Expected: punctuation assertions fail because current `compose()` inserts spaces and discards punctuation.

- [ ] **Step 4: Implement contiguous source-range composition**

In `static/js/modules/app/text-selection.js`, add bracket maps for `()`, `[]`, `（）`, and `【】`. Add helpers that find the next non-whitespace source character, count bracket characters within a selected span, expand a span only when a real matching boundary exists, replace `/` and `\` with spaces, and collapse whitespace.

Replace `compose()` with this flow:

```javascript
function compose(tokens, selectedIndexes) {
    const sourceTokens = Array.isArray(tokens) ? tokens : [];
    const selected = Array.from(new Set(
        (Array.isArray(selectedIndexes) ? selectedIndexes : [])
            .map(Number)
            .filter(index => Number.isInteger(index) && index >= 0 && index < sourceTokens.length)
    )).sort((left, right) => left - right);
    if (!selected.length) return '';

    const ranges = [];
    for (const index of selected) {
        const previous = ranges[ranges.length - 1];
        if (previous && index === previous.endIndex + 1) previous.endIndex = index;
        else ranges.push({ startIndex: index, endIndex: index });
    }

    return normalizeComposedText(ranges.map(range => {
        const first = sourceTokens[range.startIndex] || {};
        const last = sourceTokens[range.endIndex] || {};
        const source = String(first.source || last.source || '');
        const boundaries = expandBalancedBoundaries(
            source,
            Number(first.start || 0),
            Number(last.end || 0)
        );
        return normalizeComposedText(source.slice(boundaries.start, boundaries.end));
    }).filter(Boolean).join(' '));
}
```

`expandBalancedBoundaries()` must support both cases: a selected token directly wrapped by a real pair such as `(2025)`, and a selected span containing an unmatched opening bracket whose real closing bracket is immediately after the span. It must never invent a missing bracket.

- [ ] **Step 5: Run tests and verify GREEN**

Run the focused command from Step 3. Expected: all shared ED2K and scraper path logic tests pass.

- [ ] **Step 6: Commit the shared behavior**

```bash
git add static/js/modules/app/text-selection.js \
  tests/test_resource_ed2k_frontend.py tests/test_scraper_path_selection_frontend.py
git commit -m "保留大爆炸选词原文标点"
```

If `.git/index.lock` remains blocked, record the permission blocker and continue without claiming a commit.

### Task 2: Deterministic ED2K Folder Name Safety

**Files:**
- Modify: `tests/test_resource_ed2k_frontend.py`
- Modify: `tests/test_resource_ed2k.py`
- Modify: `tests/test_resource_offline_jobs.py`
- Modify: `static/js/modules/resource/ed2k-import.js`
- Modify: `static/js/modules/resource/import-modal.js`
- Modify: `app/resource_ed2k.py`
- Modify: `app/routes/resource.py`

- [ ] **Step 1: Write failing frontend normalizer tests**

Add exact assertions:

```python
def test_folder_name_normalizer_preserves_colon_and_replaces_unsafe_characters(self):
    result = run_ed2k_frontend(
        "api.normalizeFolderName('  碟中谍: 最终清算 / *?\"<>|  ')"
    )
    self.assertEqual(result, '碟中谍: 最终清算 ＊？＂＜＞｜')

def test_folder_name_normalizer_rejects_dot_names_and_limits_code_points(self):
    result = run_ed2k_frontend(
        "({ dot: api.normalizeFolderName('..'), long: api.normalizeFolderName('片'.repeat(121)) })"
    )
    self.assertEqual(result['dot'], '')
    self.assertEqual(len(result['long']), 120)
```

Add source-wiring tests that require `completeResourceEd2kTitleSelection()` and the ED2K submit branch to call `normalizeFolderName()`, with the submit branch assigning the normalized value back to `resourceEd2kState.folderName` before POST.

- [ ] **Step 2: Write failing backend normalizer and route tests**

Import `normalize_ed2k_folder_name` in `tests/test_resource_ed2k.py` and require:

```python
self.assertEqual(
    normalize_ed2k_folder_name('  碟中谍: 最终清算 / *?"<>|  '),
    '碟中谍: 最终清算 ＊？＂＜＞｜',
)
self.assertEqual(normalize_ed2k_folder_name('..'), '')
self.assertEqual(len(normalize_ed2k_folder_name('片' * 121)), 120)
```

Add a batch route regression in `ResourceEd2kBatchRouteTest` that submits `碟中谍: 最终清算 / *?"<>|` and asserts both `response["folder_name"]` and `response["savepath"]` use `碟中谍: 最终清算 ＊？＂＜＞｜`.

- [ ] **Step 3: Run tests and verify RED**

```bash
PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m unittest \
  tests.test_resource_ed2k_frontend.ResourceEd2kFrontendLogicTest \
  tests.test_resource_ed2k.ResourceEd2kFolderNameTest \
  tests.test_resource_offline_jobs.ResourceEd2kBatchRouteTest
```

Expected: normalizer APIs are missing, modal wiring assertions fail, and the route still strips punctuation through `sanitize_115_folder_name()`.

- [ ] **Step 4: Implement the frontend folder normalizer**

In `static/js/modules/resource/ed2k-import.js`, add and export:

```javascript
const FOLDER_CHARACTER_REPLACEMENTS = Object.freeze({
    '*': '＊', '?': '？', '"': '＂', '<': '＜', '>': '＞', '|': '｜',
});

function cleanFolderName(value) {
    return String(value || '')
        .replace(/[\u0000-\u001f\u007f]+/gu, '')
        .replace(/[\\/]+/gu, ' ')
        .replace(/[*?"<>|]/gu, character => FOLDER_CHARACTER_REPLACEMENTS[character] || '')
        .replace(/\s+/gu, ' ')
        .trim();
}

function normalizeFolderName(value, fallback = '') {
    let cleaned = cleanFolderName(value);
    if (!cleaned || cleaned === '.' || cleaned === '..') cleaned = cleanFolderName(fallback);
    if (!cleaned || cleaned === '.' || cleaned === '..') return '';
    return Array.from(cleaned).slice(0, 120).join('');
}
```

Use it in `isResourceEd2kReady()`, `completeResourceEd2kTitleSelection()`, and immediately before the ED2K batch POST. Before POST, assign the normalized value to both state and `#resource-ed2k-folder-name` so the visible value matches the payload.

- [ ] **Step 5: Implement backend defense and route ownership**

In `app/resource_ed2k.py`, add `normalize_ed2k_folder_name()` with the same control-character removal, slash-to-space conversion, fixed fullwidth map, whitespace collapse, dot-name rejection, fallback handling, and 120-code-point limit. Export it through `__all__`.

In `app/routes/resource.py`, import it directly from `resource_ed2k` and replace only the ED2K batch route's `sanitize_115_folder_name()` call. Do not alter subscription or Quark naming behavior.

- [ ] **Step 6: Run tests and verify GREEN**

Run the focused command from Step 3, then:

```bash
PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m unittest \
  tests.test_resource_ed2k_frontend tests.test_scraper_path_selection_frontend \
  tests.test_resource_ed2k tests.test_resource_offline_jobs
```

Expected: all focused and related tests pass.

- [ ] **Step 7: Commit ED2K folder safety**

```bash
git add app/resource_ed2k.py app/routes/resource.py \
  static/js/modules/resource/ed2k-import.js static/js/modules/resource/import-modal.js \
  tests/test_resource_ed2k.py tests/test_resource_ed2k_frontend.py \
  tests/test_resource_offline_jobs.py
git commit -m "统一ED2K文件夹名称规范"
```

If `.git/index.lock` remains blocked, retain verified changes and report that no commit was created.

### Task 3: Documentation and Full Verification

**Files:**
- Modify: `docs/superpowers/handoff.md`

- [ ] **Step 1: Run the complete test suite**

```bash
PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

Expected: zero failures and errors.

- [ ] **Step 2: Run compile, syntax, and diff checks**

```bash
PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m compileall app main.py
node --check static/js/modules/app/text-selection.js
node --check static/js/modules/resource/ed2k-import.js
node --check static/js/modules/resource/import-modal.js
node --check static/js/modules/scraper/path-selection.js
git diff --check
```

Expected: every command exits zero.

- [ ] **Step 3: Run module-load and behavior smoke checks**

Reuse the Node `vm` harnesses in the frontend test files and explicitly confirm these outputs:

```text
碟中谍：最终清算 (2025)
电视剧 欧美 S.W.A.T. (2017)
碟中谍: 最终清算 ＊？＂＜＞｜
```

- [ ] **Step 4: Perform browser interaction verification**

Use the in-app browser only against a runtime rebuilt from the current workspace. Check ED2K and scraper manual selection at desktop and `390x844`, in day and night themes. Confirm punctuation remains, path separators become spaces, manual input remains editable, and neither panel overflows horizontally. If no rebuilt runtime exists, report browser verification as blocked by stale assets.

- [ ] **Step 5: Append the implementation handoff entry**

Append one timestamped line to `docs/superpowers/handoff.md` with branch, completed behavior, exact verification commands, browser result or blocker, and next deployment step.

- [ ] **Step 6: Final commit attempt**

```bash
git add docs/superpowers/handoff.md docs/superpowers/specs/2026-07-31-shared-text-selection-punctuation-design.md \
  docs/superpowers/plans/2026-07-31-shared-text-selection-punctuation.md
git commit -m "完成大爆炸标点保留优化"
```

If the sandbox still denies `.git/index.lock`, do not emit a commit directive and state the exact permission blocker in the handoff.

### Task 4: Make Legal Punctuation Independently Selectable

**Files:**
- Modify: `static/js/modules/app/text-selection.js`
- Modify: `tests/test_resource_ed2k_frontend.py`
- Verify: ED2K and scraper selection renderers

- [x] **Step 1: Reproduce the mismatch**

Confirm `🎬 电影：奇谭：纸刃渡荒墟 (2026)` renders only text tokens while the completed folder name contains hidden colons and parentheses.

- [x] **Step 2: Add failing shared-token tests**

Require `：`、`(`、`)`、`.` and `-` to appear as independent tokens, while emoji, path separators and unsafe folder characters remain excluded.

- [x] **Step 3: Replace hidden punctuation recovery**

Tokenize legal punctuation as single-character selection units and compose only the exact selected token ranges. Remove balanced-boundary expansion so an unselected bracket cannot enter the result.

- [x] **Step 4: Run full verification and browser QA**

Verify ED2K and scraper at desktop and mobile widths, confirm symbols have independent boxes, drag selection remains continuous, completed values match the selected boxes, and no horizontal overflow or console error is introduced.
