# ED2K Folder Title Placement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the ED2K title selector into the save-directory and child-folder controls, and hide it whenever child-folder creation is disabled.

**Architecture:** Keep file selection owned by the main ED2K card and move only the existing title-selector section into `resource-ed2k-folder-section`. Add one pure visibility helper to the existing ED2K frontend logic module so render behavior is testable without a browser, then let `renderResourceEd2kImport()` apply that result to the moved section.

**Tech Stack:** Jinja HTML templates, vanilla JavaScript, CSS, Python unittest with Node VM execution, Codex in-app Browser.

---

### Task 1: Lock the desired structure and visibility behavior

**Files:**
- Modify: `tests/test_resource_ed2k_frontend.py`
- Test: `tests/test_resource_ed2k_frontend.py`

- [ ] **Step 1: Add a template hierarchy parser and failing placement test**

Add `HTMLParser`, `TEMPLATE_PATH`, and an `IdHierarchyParser` test helper that records ancestor element IDs. Assert that `resource-ed2k-files-section` remains under `resource-import-main-column`, while `resource-ed2k-title-section` is under both `resource-import-save-panel` and `resource-ed2k-folder-section`.

```python
class IdHierarchyParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.ancestors = {}

    def handle_starttag(self, tag, attrs):
        node_id = dict(attrs).get("id", "")
        self.stack.append((tag, node_id))
        if node_id:
            self.ancestors[node_id] = [item_id for _, item_id in self.stack[:-1] if item_id]

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return
```

- [ ] **Step 2: Add a failing visibility test**

Exercise the ED2K pure frontend API and require the selector only when the import is active, resolved, and child-folder creation is enabled.

```python
result = run_ed2k_frontend(
    "({ enabled: api.shouldShowTitleSelector(true, true, true), "
    "disabled: api.shouldShowTitleSelector(true, true, false), "
    "loading: api.shouldShowTitleSelector(true, false, true) })"
)
self.assertEqual(result, {"enabled": True, "disabled": False, "loading": False})
```

- [ ] **Step 3: Run the tests and verify RED**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m unittest tests.test_resource_ed2k_frontend
```

Expected: failures because the title section is still in the main column and `shouldShowTitleSelector` does not exist.

### Task 2: Move the selector and apply the folder-creation state

**Files:**
- Modify: `templates/partials/modals/resource_import.html`
- Modify: `static/js/modules/resource/ed2k-import.js`
- Modify: `static/js/modules/resource/import-modal.js`
- Modify: `static/css/index.css`
- Test: `tests/test_resource_ed2k_frontend.py`

- [ ] **Step 1: Move the existing title section without changing IDs or handlers**

Remove `resource-ed2k-title-section` from `resource-ed2k-card` and insert the same section immediately after the `resource-ed2k-create-folder` label inside `resource-ed2k-folder-section`. Keep the file section in the main card.

- [ ] **Step 2: Add the pure visibility helper**

Add and export:

```javascript
function shouldShowTitleSelector(active, ready, createFolder) {
    return !!active && !!ready && createFolder !== false;
}
```

- [ ] **Step 3: Use the helper in the renderer**

Update `renderResourceEd2kImport()` so the moved title section is visible only when the helper returns true. Keep the files section controlled only by parse readiness.

```javascript
const showTitleSelector = window.ResourceEd2kImport.shouldShowTitleSelector(
    active,
    ready,
    resourceEd2kState.createFolder !== false
);
titleSection.classList.toggle('hidden', !showTitleSelector);
filesSection.classList.toggle('hidden', !ready);
```

- [ ] **Step 4: Give the moved subsection local spacing**

Add `resource-ed2k-folder-title-section` to the section and style it as an unframed subsection inside the existing save card. Reuse the existing token, action, day-mode, and mobile styles; do not add a nested card.

- [ ] **Step 5: Run the frontend tests and verify GREEN**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m unittest tests.test_resource_ed2k_frontend
```

Expected: all ED2K frontend tests pass.

### Task 3: Browser and repository verification

**Files:**
- Modify: `docs/superpowers/handoff.md`

- [ ] **Step 1: Check syntax and the complete suite**

Run:

```bash
node --check static/js/modules/resource/ed2k-import.js
node --check static/js/modules/resource/import-modal.js
PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m compileall app main.py
git diff --check
```

Expected: every command exits zero.

- [ ] **Step 2: Verify desktop and mobile behavior in the in-app Browser**

Open the provided Telegra.ph-backed resource and confirm:

- the file list remains in the main column and contains eight selected files;
- the title selector appears in the save settings after “新建文件夹”;
- disabling “新建文件夹” hides the selector and uses the parent path;
- re-enabling it restores the selector state;
- the reselect icon expands and scrolls to the moved selector;
- a 390px viewport has no horizontal overflow.

- [ ] **Step 3: Append the handoff entry**

Append the date, branch, changed behavior, verification evidence, and rebuild follow-up to `docs/superpowers/handoff.md`. Do not commit the overlapping implementation files unless the user explicitly requests a commit.
