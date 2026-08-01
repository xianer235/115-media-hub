# Guangya Link Recognition Implementation Plan

> **状态：已取代。** 本计划的后端全局分类做法已由 [频道资源类型标签与光鸭展示识别实施计划](./2026-08-02-resource-link-tag-palette.md) 取代，请勿继续按本文步骤实现。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recognize Guangya share URLs as `guangya` without enabling an unimplemented provider.

**Architecture:** Extend the existing central `RESOURCE_LINK_TYPE_PATTERNS` registry, so every caller of `detect_resource_link_type()` and `extract_resource_candidates()` receives the same classification. Keep the provider registry unchanged because link classification alone cannot implement authenticated file or share operations.

**Tech Stack:** Python 3.9, `re`, `unittest`.

---

### Task 1: Central Guangya share-link classification

**Files:**
- Modify: `tests/test_resource_ed2k.py`
- Modify: `app/resource_linking.py`

- [ ] **Step 1: Write the failing test**

```python
from app.resource_linking import detect_resource_link_type

def test_detect_resource_link_type_recognizes_guangya_share_urls(self):
    for url in (
        "https://www.guangyapan.com/share/abc_123",
        "https://guangyapan.com/s/abc-123?pwd=1234",
        "https://www.guangyapan.com/link/abc123",
        "https://guangyapan.com/download/abc123",
    ):
        self.assertEqual(detect_resource_link_type(url), "guangya")
    self.assertEqual(detect_resource_link_type("https://www.guangyapan.com/"), "link")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m unittest tests.test_resource_ed2k.ResourceEd2kLinkingRegressionTest.test_detect_resource_link_type_recognizes_guangya_share_urls`

Expected: FAIL because the URLs are currently classified as `link`.

- [ ] **Step 3: Write minimal implementation**

```python
("guangya", re.compile(
    r"https?://(?:www\\.)?guangyapan\\.com/(?:share|s|link|download)/[a-z0-9_-]+",
    re.IGNORECASE,
)),
```

Add the rule to `RESOURCE_LINK_TYPE_PATTERNS` in `app/resource_linking.py`. Do not add it to `choose_resource_link()` priority, since no provider is available to consume it.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m unittest tests.test_resource_ed2k.ResourceEd2kLinkingRegressionTest.test_detect_resource_link_type_recognizes_guangya_share_urls`

Expected: PASS.

- [ ] **Step 5: Run focused regression tests and static validation**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m unittest tests.test_resource_ed2k
PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m compileall app main.py
git diff --check
```

Expected: all tests pass, compilation succeeds, and diff check has no output.

- [ ] **Step 6: Append handoff record**

Append a concise `docs/superpowers/handoff.md` entry recording the new `guangya` classifier, the intentional lack of a provider registration, and the verification commands.
