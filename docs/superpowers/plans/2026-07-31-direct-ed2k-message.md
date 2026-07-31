# TG Single-File ED2K Message Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make TG channel messages containing a direct single-file ED2K link enter the existing ED2K import workflow.

**Architecture:** Reuse `extract_resource_links()` at the TG HTML parsing boundary instead of maintaining a second magnet/HTTP-only inline parser. Preserve the existing one-resource-per-post model, Telegram internal-link filtering, and `choose_resource_link()` priority.

**Tech Stack:** Python 3.9, `unittest`, FastAPI backend modules

---

### Task 1: Reproduce Direct ED2K Loss in TG Parsing

**Files:**
- Modify: `tests/test_resource_ed2k.py`

- [x] **Step 1: Import the TG page parser**

Add the production parser used by channel sync:

```python
from app.resource_tg import parse_telegram_posts_page
```

- [x] **Step 2: Add the failing regression test**

Add this test to `ResourceEd2kLinkingRegressionTest` using the reported movie message:

```python
def test_tg_channel_post_recognizes_direct_single_file_ed2k(self):
    link = (
        "ed2k://|file|寒战1994 (2026) - 2160p.WEB-DL.DV.H265.DTS."
        "{tmdb-1499071}.mkv|28700476657|01aae290682a3cd7a041c0b0a4634ca2|/"
    )
    raw_text = "\n".join(
        (
            "🎬 电影：寒战1994 (2026)",
            "🍿 TMDB ID: 1499071",
            "🔗 链接:",
            link,
            "#华语电影",
        )
    )
    html = (
        '<div class="tgme_widget_message" data-post="movies/1">'
        f'<div class="tgme_widget_message_text">{raw_text.replace(chr(10), "<br>")}</div>'
        "</div>"
    )

    post = parse_telegram_posts_page(
        html,
        {"channel_id": "movies", "name": "电影频道"},
        limit=10,
    )["posts"][0]

    self.assertEqual(post["link_url"], link)
    self.assertEqual(post["link_type"], "ed2k")
    self.assertEqual(post["title"], "🎬 电影：寒战1994 (2026)")
    self.assertIn(link, post["extra"]["all_links"])
```

- [x] **Step 3: Run the test and verify RED**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m unittest tests.test_resource_ed2k.ResourceEd2kLinkingRegressionTest.test_tg_channel_post_recognizes_direct_single_file_ed2k
```

Expected: FAIL because `post["link_url"]` is empty and `post["link_type"]` is `unknown`.

### Task 2: Centralize TG Post Link Extraction

**Files:**
- Modify: `app/resource_tg.py`
- Test: `tests/test_resource_ed2k.py`

- [x] **Step 1: Replace the duplicated inline protocol list**

Import the common extractor and remove the now-unused protocol regex imports:

```python
from .resource_linking import (
    RESOURCE_YEAR_REGEX,
    choose_resource_link,
    detect_resource_link_type,
    extract_resource_links,
    guess_resource_quality,
    pick_resource_title,
    strip_html_to_text,
)
```

Build all post candidates through the common extractor while retaining Telegram internal-link filtering:

```python
link_source = "\n".join([*hrefs, raw_text])
all_links = [
    link
    for link in extract_resource_links(link_source)
    if "t.me/" not in link
    and "telegram.me/" not in link
    and "telegram.org/" not in link
]
```

Keep the existing `choose_resource_link(all_links)` call and resource item construction unchanged.

- [x] **Step 2: Run the regression test and verify GREEN**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m unittest tests.test_resource_ed2k.ResourceEd2kLinkingRegressionTest.test_tg_channel_post_recognizes_direct_single_file_ed2k
```

Expected: PASS.

- [x] **Step 3: Run focused resource tests**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m unittest tests.test_resource_ed2k tests.test_resource_source_usage
```

Expected: all tests PASS.

### Task 3: Verify and Record the Fix

**Files:**
- Modify: `docs/superpowers/handoff.md`

- [x] **Step 1: Run the full test suite**

```bash
PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

Expected: all tests PASS, including the new regression test.

- [x] **Step 2: Run compile and diff checks**

```bash
PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m compileall app main.py
git diff --check
```

Expected: both commands exit successfully.

- [x] **Step 3: Append the handoff entry**

Append this line after replacing the test count with the verified final count if it differs:

```markdown
- 2026-07-31 18:57 CST | main | 修复 TG 频道消息直接分享单个 ED2K 文件时无法识别：根因是频道 HTML 解析器单独维护了仅支持 magnet/HTTP 的正文链接规则；现统一复用 `extract_resource_links()`，保留 Telegram 内部链接过滤、单资源模型和既有主链接优先级。新增用户电影消息回归测试，完整 unittest 预计 72 项、项目 `compileall` 与 `git diff --check` 通过。| 下一步：重新构建或重启服务后，在真实资源频道打开该电影条目，确认进入现有 ED2K 导入弹窗、默认选中唯一文件并可新建电影文件夹保存到 115。
```

- [x] **Step 4: Commit the implementation**

```bash
git add app/resource_tg.py tests/test_resource_ed2k.py docs/superpowers/handoff.md docs/superpowers/plans/2026-07-31-direct-ed2k-message.md
git commit -m "修复TG单文件ED2K资源识别"
```
