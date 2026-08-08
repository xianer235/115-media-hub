# Resource Sync Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore automatic resource-center refresh after channel synchronization completes when the search box is empty, while preserving active search results.

**Architecture:** Keep the existing SSE and compact polling paths. Make the existing channel-sync transition handler the single completion-refresh decision point, and pass the compact/full response context into it. The handler will skip the refresh whenever the current search input or resource state contains a search term.

**Tech Stack:** Browser JavaScript globals, Node VM frontend tests, Python `unittest`, FastAPI project validation commands.

---

### Task 1: Add the failing state-policy regression test

**Files:**
- Create: `tests/test_resource_sync_frontend.py`
- Test: `static/js/index.js` and `static/js/modules/resource/core.js` wiring

- [ ] **Step 1: Write the failing test**

  Load the small transition-policy fixture from the frontend source and assert that an active-to-finished transition requests a refresh only for an empty search term. Also assert that the resource core passes `refreshOnComplete: compactUpdate` when applying a state payload.

- [ ] **Step 2: Run the focused test and verify it fails**

  Run:

  ```bash
  .venv/bin/python -m unittest tests.test_resource_sync_frontend -v
  ```

  Expected: failure because the current source does not expose the tested policy and still passes `refreshOnComplete: false` for compact state application.

### Task 2: Implement the completion-refresh policy

**Files:**
- Modify: `static/js/index.js:1688-1738`
- Modify: `static/js/modules/resource/core.js:2804-2805`
- Modify: `templates/index.html:272-285` only if a testable helper module is needed

- [ ] **Step 1: Add the search-aware completion guard**

  In `handleResourceChannelSyncStateChange`, read `resource-search-input` first and fall back to `resourceState.search`. Gate the existing `refreshResourceState({ allowSearch: false })` call on the resulting term being empty.

- [ ] **Step 2: Pass compact response context from resource state application**

  Replace the unconditional `{ refreshOnComplete: false }` call with `{ refreshOnComplete: compactUpdate }`. A compact terminal response can then trigger the full refresh; a full response is already current and does not recurse.

- [ ] **Step 3: Run the focused regression test**

  Run:

  ```bash
  .venv/bin/python -m unittest tests.test_resource_sync_frontend -v
  ```

  Expected: all new tests pass, including empty-search refresh and non-empty-search preservation.

### Task 3: Verify the complete change

**Files:**
- Review: `git diff`, touched JavaScript files, and `tests/test_resource_sync_frontend.py`

- [ ] **Step 1: Run project checks**

  ```bash
  PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m compileall app main.py
  node --check static/js/index.js
  node --check static/js/modules/resource/core.js
  .venv/bin/python -m unittest discover -s tests
  git diff --check
  ```

- [ ] **Step 2: Review the diff for scope**

  Confirm that the change only alters completion-refresh selection and does not modify backend synchronization, search data, or provider behavior.

- [ ] **Step 3: Run runtime verification when Docker is available**

  ```bash
  export HTTP_PROXY=http://127.0.0.1:7897
  export HTTPS_PROXY=http://127.0.0.1:7897
  export NO_PROXY=localhost,127.0.0.1,registry-1.docker.io
  docker compose up -d --build
  ```

  Manually verify an empty search box receives new channel cards after completion and a non-empty search retains its existing result view.

