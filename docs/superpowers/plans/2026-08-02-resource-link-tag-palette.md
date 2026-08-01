# 频道资源类型标签与光鸭展示识别 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**状态:** 已完成；提交步骤因当前 `.git` 只读而跳过。

**Goal:** 在频道资源卡片、频道摘要和频道管理中统一展示资源类型标签与日夜配色，并让光鸭网盘只作为展示类型识别、继续沿用直链操作行为。

**Architecture:** 新建独立的前端 `ResourceLinkTags` 注册表，集中维护展示类型、文案、分类、色调、URL 规则和操作类型，并为频道条目提供展示统计。后端撤回全局 `guangya` 分类；资源操作继续使用注册表解析出的 `actionType`，资源展示则使用独立的 display type。

**Tech Stack:** Python 3.9、原生 JavaScript、CSS custom properties、`unittest`、Node `vm`。

---

### Task 1: 收敛后端光鸭分类范围

**Files:**
- Modify: `tests/test_resource_ed2k.py`
- Modify: `app/resource_linking.py`

- [x] **Step 1: 将现有光鸭测试改为操作类型回归测试**

把测试改为断言四种光鸭分享 URL 均由通用后端分类器返回 `link`，并保留主页反例：

```python
def test_guangya_share_urls_remain_generic_links_for_operations(self):
    for url in (
        "https://www.guangyapan.com/share/abc_123",
        "https://guangyapan.com/s/abc-123?pwd=1234",
        "https://www.guangyapan.com/link/abc123",
        "https://guangyapan.com/download/abc123",
    ):
        self.assertEqual(detect_resource_link_type(url), "link")
    self.assertEqual(detect_resource_link_type("https://www.guangyapan.com/"), "link")
```

- [x] **Step 2: 运行测试确认红灯**

```bash
PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache \
  .venv/bin/python -m unittest \
  tests.test_resource_ed2k.ResourceEd2kLinkingRegressionTest.test_guangya_share_urls_remain_generic_links_for_operations
```

Expected: FAIL，当前实现返回 `guangya`。

- [x] **Step 3: 移除全局 `guangya` URL 规则**

从 `RESOURCE_LINK_TYPE_PATTERNS` 删除：

```python
("guangya", re.compile(
    r"https?://(?:www\.)?guangyapan\.com/(?:share|s|link|download)/[a-z0-9_-]+",
    re.IGNORECASE,
)),
```

- [x] **Step 4: 运行定向测试确认绿灯**

重复 Step 2 命令。Expected: PASS。

### Task 2: 建立前端展示类型注册表

**Files:**
- Create: `tests/test_resource_link_tags_frontend.py`
- Create: `static/js/modules/resource/link-tags.js`

- [x] **Step 1: 编写注册表失败测试**

使用 Node `vm` 加载目标模块并检查：

```python
ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "static/js/modules/resource/link-tags.js"

def run_link_tags(expression: str):
    script = f"""
const fs = require('fs');
const vm = require('vm');
const context = {{ window: {{}} }};
vm.createContext(context);
vm.runInContext(fs.readFileSync({json.dumps(str(MODULE_PATH))}, 'utf8'), context);
const api = context.window.ResourceLinkTags;
process.stdout.write(JSON.stringify(({expression})));
"""
    completed = subprocess.run(
        ["node", "-e", script], cwd=ROOT, check=True,
        capture_output=True, text=True,
    )
    return json.loads(completed.stdout)
```

覆盖以下契约：

```python
def test_guangya_is_display_only(self):
    result = run_link_tags("({ display: api.resolveDisplayType({link_url: 'https://guangyapan.com/s/abc-123'}), action: api.resolveActionType({link_url: 'https://guangyapan.com/s/abc-123'}), meta: api.getTagMeta('guangya') })")
    self.assertEqual(result["display"], "guangya")
    self.assertEqual(result["action"], "link")
    self.assertEqual(result["meta"]["label"], "光鸭网盘")
    self.assertEqual(result["meta"]["tone"], "lime")

def test_registry_contains_all_builtin_types(self):
    expected = [
        "115share", "quark", "guangya", "aliyun", "baidu", "xunlei",
        "uc", "123pan", "tianyi", "pikpak", "lanzou", "google_drive",
        "onedrive", "mega", "magnet", "ed2k", "link", "unknown",
    ]
    self.assertEqual(run_link_tags("api.list().map(item => item.type)"), expected)
```

另加测试覆盖四种光鸭路径、主页/空 ID/相似域名反例、磁力、电驴、普通 HTTP、未知字符串、类别色调兜底和未登记类型回退。

- [x] **Step 2: 运行测试确认红灯**

```bash
.venv/bin/python -m unittest tests.test_resource_link_tags_frontend
```

Expected: ERROR/FAIL，模块尚不存在。

- [x] **Step 3: 实现只读注册表**

`link-tags.js` 使用 IIFE 并导出：

```javascript
(function (global) {
    'use strict';

    const CATEGORY_FALLBACK_TONES = Object.freeze({
        cloud: 'sky', offline: 'amber', direct: 'slate', unknown: 'neutral',
    });
    const DEFINITIONS = Object.freeze([
        { type: '115share', label: '115网盘', category: 'cloud', tone: 'blue', actionType: '115share', patterns: [/(?:https?:\/\/)?(?:115cdn|115|anxia)\.com\/s\/[a-z0-9]+/i] },
        { type: 'quark', label: '夸克网盘', category: 'cloud', tone: 'violet', actionType: 'quark', patterns: [/https?:\/\/(?:pan|www)\.quark\.cn\/s\/[a-z0-9]+/i] },
        { type: 'guangya', label: '光鸭网盘', category: 'cloud', tone: 'lime', actionType: 'link', patterns: [/https?:\/\/(?:www\.)?guangyapan\.com\/(?:share|s|link|download)\/[a-z0-9_-]+/i] },
        { type: 'aliyun', label: '阿里云盘', category: 'cloud', tone: 'orange', actionType: 'aliyun', patterns: [/https?:\/\/(?:www\.)?(?:aliyundrive|alipan)\.com\/s\/[a-z0-9]+/i] },
        { type: 'baidu', label: '百度网盘', category: 'cloud', tone: 'sky', actionType: 'baidu', patterns: [/https?:\/\/(?:pan|yun)\.baidu\.com\/(?:s\/|share\/)/i] },
        { type: 'xunlei', label: '迅雷网盘', category: 'cloud', tone: 'indigo', actionType: 'xunlei', patterns: [/https?:\/\/(?:pan|xlpan)\.xunlei\.com\/s\/[a-z0-9]+/i] },
        { type: 'uc', label: 'UC网盘', category: 'cloud', tone: 'amber', actionType: 'uc', patterns: [/https?:\/\/drive\.uc\.cn\/s\/[a-z0-9]+/i] },
        { type: '123pan', label: '123云盘', category: 'cloud', tone: 'emerald', actionType: '123pan', patterns: [/https?:\/\/(?:www\.)?(?:123pan|123684|123865|123912)\.(?:com|cn)\/s\/[a-z0-9_-]+(?:\.html?)?/i] },
        { type: 'tianyi', label: '天翼云盘', category: 'cloud', tone: 'rose', actionType: 'tianyi', patterns: [/https?:\/\/cloud\.189\.cn\/(?:t\/|web\/share)/i] },
        { type: 'pikpak', label: 'PikPak', category: 'cloud', tone: 'fuchsia', actionType: 'pikpak', patterns: [/https?:\/\/(?:www\.)?(?:mypikpak|pikpak)\.com\/s\/[a-z0-9]+/i] },
        { type: 'lanzou', label: '蓝奏云', category: 'cloud', tone: 'teal', actionType: 'lanzou', patterns: [/https?:\/\/(?:www\.)?lanzou[a-z0-9]*\.[a-z.]+\/[a-z0-9]+/i] },
        { type: 'google_drive', label: 'Google Drive', category: 'cloud', tone: 'green', actionType: 'google_drive', patterns: [/https?:\/\/drive\.google\.com\//i] },
        { type: 'onedrive', label: 'OneDrive', category: 'cloud', tone: 'cyan', actionType: 'onedrive', patterns: [/https?:\/\/(?:1drv\.ms|onedrive\.live\.com)\//i] },
        { type: 'mega', label: 'MEGA', category: 'cloud', tone: 'red', actionType: 'mega', patterns: [/https?:\/\/mega\.nz\//i] },
        { type: 'magnet', label: '磁力', category: 'offline', tone: 'yellow', actionType: 'magnet', prefixes: ['magnet:?'] },
        { type: 'ed2k', label: '电驴', category: 'offline', tone: 'pink', actionType: 'ed2k', prefixes: ['ed2k://'] },
        { type: 'link', label: '直链', category: 'direct', tone: 'slate', actionType: 'link', prefixes: ['http://', 'https://'] },
        { type: 'unknown', label: '待识别', category: 'unknown', tone: 'neutral', actionType: 'unknown' },
    ]);

    global.ResourceLinkTags = Object.freeze({
        detect, getTagMeta, list, resolveActionType, resolveDisplayType, summarize,
    });
})(window);
```

`list()` 返回去除 RegExp 的只读元数据副本；`summarize(items, fallback)` 按数量降序、注册顺序决胜，返回 `primary_link_type`、最多三个 `dominant_link_types` 和 `link_type_counts`，有条目时覆盖 fallback 的三个统计字段，无条目时保留 fallback。

- [x] **Step 4: 运行前端注册表测试确认绿灯**

重复 Step 2 命令。Expected: PASS。

### Task 3: 分离资源展示与操作调用链

**Files:**
- Modify: `tests/test_resource_link_tags_frontend.py`
- Modify: `templates/index.html`
- Modify: `static/js/modules/resource/core.js`

- [x] **Step 1: 增加集成失败测试**

静态检查以下约束：

```python
def test_link_tag_module_loads_before_resource_core(self):
    html = TEMPLATE_PATH.read_text(encoding="utf-8")
    self.assertLess(html.index("resource/link-tags.js"), html.index("resource/core.js"))

def test_resource_card_uses_display_type_but_actions_use_action_type(self):
    source = CORE_PATH.read_text(encoding="utf-8")
    self.assertIn("ResourceLinkTags.resolveActionType(item)", source)
    self.assertIn("getResourceDisplayLinkType(item)", source)
    self.assertIn("getResourceDisplayLinkTypeBadgeClass(displayType)", source)
```

并测试 `summarize()` 在两条光鸭、一条直链时返回 `guangya` 主类型，并列时按注册顺序排序。

- [x] **Step 2: 运行测试确认红灯**

```bash
.venv/bin/python -m unittest tests.test_resource_link_tags_frontend
```

Expected: FAIL，模板和资源核心尚未接入。

- [x] **Step 3: 接入注册表**

在 `templates/index.html` 的 `resource/core.js` 之前加载：

```html
<script src="/static/js/modules/resource/link-tags.js?v={{ asset_version }}"></script>
```

在 `core.js` 中：

- `detectResourceLinkTypeByUrl(url)` 改为 `ResourceLinkTags.resolveActionType({ link_url: url })`。
- `getEffectiveResourceLinkType(item)` 改为 `ResourceLinkTags.resolveActionType(item)`。
- 新增 `getResourceDisplayLinkType()`、`getResourceDisplayLinkTypeLabel()`、`getResourceDisplayLinkTypeBadgeClass()` 和 `buildResourceDisplayProfile()` 包装函数。
- 单条资源卡片先计算 `displayType`，徽标使用展示标签与 `.resource-link-tag--<tone>`；导入按钮仍使用 `getEffectiveResourceLinkType()`。
- 频道标题调用 `buildResourceDisplayProfile(sectionItems, serverProfile)`，并用主要展示类型渲染同色标签。
- 将四个展示包装函数导出到 `window`，供后加载的频道管理模块复用。

- [x] **Step 4: 运行集成测试确认绿灯**

重复 Step 2 命令。Expected: PASS。

### Task 4: 统一频道管理标签与配色样式

**Files:**
- Modify: `tests/test_resource_link_tags_frontend.py`
- Modify: `static/js/modules/resource/source-manager.js`
- Modify: `static/css/index.css`

- [x] **Step 1: 增加频道管理与 CSS 失败测试**

断言：

- `getResourceSourceProfileFromIndex()` 使用 `buildResourceDisplayProfile(section.items, fallbackProfile)`。
- 类型徽标使用 `getResourceDisplayLinkTypeBadgeClass(type)` 与 `getResourceDisplayLinkTypeLabel(type)`。
- CSS 定义 `.resource-link-tag`、18 个 `.resource-link-tag--<tone>`、日间覆盖和 unknown 虚线边框。
- CSS 中的 18 对日夜背景/文字色对比度均至少 `4.5:1`。

- [x] **Step 2: 运行测试确认红灯**

```bash
.venv/bin/python -m unittest tests.test_resource_link_tags_frontend
```

Expected: FAIL，频道管理仍读取操作 profile，CSS 只有三种卡片颜色。

- [x] **Step 3: 接入频道展示 profile**

`source-manager.js` 在有 section 条目时使用展示统计，类型筛选、类型列表、主类型文案和徽标统一读取展示类型；未加载条目时保留服务端 profile。数量并列调用注册表排名，不再按中文标签排序。

- [x] **Step 4: 实现内置色调令牌**

`.resource-link-tag` 统一读取 CSS 变量：

```css
.resource-link-tag {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    white-space: nowrap;
    border: 1px solid var(--tag-border);
    background: var(--tag-bg);
    color: var(--tag-text);
}
```

为 `blue/violet/lime/orange/sky/indigo/amber/emerald/rose/fuchsia/teal/green/cyan/red/yellow/pink/slate/neutral` 写入设计文档中的日夜三色值；`neutral` 使用 `border-style: dashed`。保留旧 `.resource-card-type-badge-*` 供任务中心和订阅模块使用，删除已无引用的 `.resource-source-manager-type-badge` 规则。

- [x] **Step 5: 运行测试确认绿灯**

重复 Step 2 命令。Expected: PASS。

### Task 5: 文档、回归和运行态验收

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/superpowers/specs/2026-08-01-guangya-link-recognition-design.md`
- Modify: `docs/superpowers/plans/2026-08-01-guangya-link-recognition.md`
- Modify: `docs/superpowers/handoff.md`

- [x] **Step 1: 同步文档状态**

在旧设计和旧计划顶部增加“已由 `2026-08-02-resource-link-tag-palette-design.md` / 当前实施计划取代”的说明；在 `CHANGELOG.md` 新增 `[Unreleased]`，说明光鸭仅做频道展示识别及资源类型标签统一配色；最终追加 handoff，记录代码、测试、浏览器结论和 `.git` 权限限制。版本仍为 `0.5.1`。

- [x] **Step 2: 运行定向测试**

```bash
PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache \
  .venv/bin/python -m unittest \
  tests.test_resource_link_tags_frontend tests.test_resource_ed2k \
  tests.test_resource_source_usage tests.test_resource_offline_jobs
```

Expected: 全部 PASS。

- [x] **Step 3: 运行完整自动验证**

```bash
PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache \
  .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache \
  .venv/bin/python -m compileall app main.py
node --check static/js/modules/resource/link-tags.js
node --check static/js/modules/resource/core.js
node --check static/js/modules/resource/source-manager.js
git diff --check
```

Expected: 单测无失败、Python 编译完成、三个 JS 语法检查退出码为 0、diff check 无输出。

- [x] **Step 4: 运行态与浏览器验收**

优先使用从当前工作区构建/同步的运行环境。验证桌面和 `390x844`，日间和夜间：

- 光鸭分享卡片显示“光鸭网盘”青柠绿标签，导入按钮仍是原有直链“下载”路径。
- 115、夸克、磁力、电驴、普通直链标签分别显示预定文案与颜色。
- 频道摘要与频道管理中的同类型标签一致。
- 标签组可换行，单个标签不拆字；标题、操作按钮不重叠，无横向溢出。
- 浏览器控制台无应用错误。

若本地 Uvicorn 因 `/app/config/data.db` 权限失败或现有容器并非当前工作区版本，明确报告阻塞，不把旧静态资源截图作为验收结果。

- [x] **Step 5: 提交（仅在 `.git` 可写时）**

当前环境无法写入 `.git/index.lock`，因此按条件跳过提交；改动保留在工作区。

```bash
git add app/resource_linking.py static/js/modules/resource/link-tags.js \
  static/js/modules/resource/core.js static/js/modules/resource/source-manager.js \
  static/css/index.css templates/index.html tests/test_resource_ed2k.py \
  tests/test_resource_link_tags_frontend.py CHANGELOG.md docs/superpowers
git commit -m "统一频道资源类型标签并修正光鸭识别范围"
```

当前沙箱若继续禁止写 `.git/index.lock`，保留未提交改动并在最终报告中说明。
