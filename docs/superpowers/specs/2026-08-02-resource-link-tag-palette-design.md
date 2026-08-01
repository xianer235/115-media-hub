# 频道资源类型标签与光鸭展示识别设计

**日期**: 2026-08-02
**状态**: 已确认
**取代方案**: `2026-08-01-guangya-link-recognition-design.md` 中的全局 `guangya` 分类方案

## 背景与结论

提交 `7c25393` 的标题把“光鸭网盘”写成了“光亚云盘”，这是中文名称笔误。代码标识 `guangya` 是“光鸭”的拼音，可以继续作为稳定内部键，不需要重命名，也不改写已经推送的提交历史。

现有实现还有两个实际问题：

1. `guangya` 被加入后端全局链接分类器，影响手工录入、订阅候选、资源操作判断等调用方，超出了“仅在频道资源展示中识别”的范围。
2. 资源卡片会再次使用前端 URL 规则判定类型，而前端没有光鸭规则；普通 HTTP 兜底因此把后端返回的 `guangya` 覆盖成 `link`，卡片最终仍显示“直链”。

本次从根因上拆分“展示类型”和“操作类型”：光鸭在卡片上显示为独立网盘标签，但操作层继续按既有直链处理，不新增网盘能力。

## 目标与边界

- 频道资源卡片、频道标题摘要和频道管理中的资源类型标签使用统一名称与配色。
- 光鸭分享 URL 显示为“光鸭网盘”，但仍沿用原有 `link` 操作类型。
- 支持的网盘、磁力、电驴、直链和未知类型由一个前端注册表管理。
- 日间和夜间主题都保持清晰可读；窄屏时标签组允许换行排列，单个标签保持一行且不挤压标题和操作区。
- 不新增 `GuangyaProvider`、认证字段、设置卡、转存、订阅、目录浏览或离线能力。
- 不增加用户自定义配色界面，不在任务中心和导入弹窗扩展光鸭专用语义。
- 不修改版本号；实现完成后只补充未发布变更说明和 agent 交接记录。

## 架构

### 1. 展示注册表

新增独立前端模块 `static/js/modules/resource/link-tags.js`，在资源核心模块之前加载，并通过只读的 `window.ResourceLinkTags` 暴露能力。每个类型只登记一次：

| 字段 | 含义 |
|---|---|
| `type` | 稳定的小写内部键，例如 `115share`、`guangya`、`ed2k` |
| `label` | 卡片显示文案 |
| `category` | `cloud`、`offline`、`direct` 或 `unknown` |
| `tone` | 内置色调键 |
| `patterns` | 仅用于展示识别的 URL/协议正则，具体规则排在 HTTP 通用规则之前 |
| `actionType` | 保持现有操作语义；默认等于 `type`，光鸭固定为 `link` |

模块提供四个稳定接口：

- `detect(url)`：按注册顺序识别最具体的展示类型。
- `resolveDisplayType(item)`：URL 的具体识别优先，其次使用已登记的 `item.link_type`，最后回退到 `link` 或 `unknown`。
- `resolveActionType(item)`：返回对应定义的 `actionType`，供现有导入、筛选和按钮判断使用。
- `getTagMeta(type)`：返回标签、分类和色调；未登记值统一回退为“待识别”与中性灰。

资源卡片不再用同一个函数同时决定“显示什么”和“能做什么”。卡片徽标使用 `resolveDisplayType()`；既有导入和操作判断通过 `resolveActionType()` 保持行为。光鸭的结果分别是 `guangya` 和 `link`。

除光鸭外，首版注册表逐条迁移当前 `detectResourceLinkTypeByUrl()` 已有的匹配规则，不扩宽既有识别范围。光鸭只匹配 `https://guangyapan.com` 或 `https://www.guangyapan.com` 下的 `/share/<id>`、`/s/<id>`、`/link/<id>`、`/download/<id>`，其中 ID 允许字母、数字、下划线和连字符；主页、空 ID、其他路径和相似域名仍按普通直链显示。

### 2. 后端范围收敛与兼容

从 `RESOURCE_LINK_TYPE_PATTERNS` 移除 `guangya`。因此后端的通用 `detect_resource_link_type()` 对光鸭 HTTP URL 继续返回 `link`，不会改变手工录入、任务创建或订阅行为，也不会注册 Provider。

不做数据库迁移。已经保存为 `guangya` 的历史条目在带 URL 时会被后端通用解析重新归为 `link`；前端仍可根据 URL 得到 `guangya` 展示类型。URL 缺失的旧条目不可执行资源操作，前端则可根据旧 `link_type` 保留光鸭标签。

频道标题摘要与频道管理不直接信任后端的操作类型统计：有频道条目时，前端按当前频道条目的展示类型重新汇总数量并选出主要类型；数量并列时按注册表顺序决定，`unknown` 始终排在最后；条目尚未加载时才回退到服务端 profile。这样光鸭频道能显示正确摘要，同时不把展示分类带回后端操作链路。

### 3. 标签样式与扩展规则

使用通用 `.resource-link-tag` 基础类和 `.resource-link-tag--<tone>` 色调类。基础类负责尺寸、字重、圆角、换行和边框；色调类只设置 `--tag-bg`、`--tag-text`、`--tag-border`。频道资源卡片、频道标题摘要和频道管理复用同一组类，任务中心保留原样。

新增链接类型时：

1. 在展示注册表增加一条定义并选择已有 `tone`。
2. 明确 `actionType`；只有真实能力已接入时才能指向新操作类型，否则使用 `link` 或 `unknown`。
3. 增加 URL 正例、反例、展示文案和操作类型测试。
4. 只有确实需要新颜色时才扩展色调表；普通新增类型不修改 CSS。

未指定色调时按类别兜底：`cloud -> sky`、`offline -> amber`、`direct -> slate`、`unknown -> neutral`。

## 内置标签配色卡

### 类型映射

| 类型键 | 展示标签 | 类别 | 色调 | 操作类型 |
|---|---|---|---|---|
| `115share` | 115网盘 | cloud | blue | `115share` |
| `quark` | 夸克网盘 | cloud | violet | `quark` |
| `guangya` | 光鸭网盘 | cloud | lime | `link` |
| `aliyun` | 阿里云盘 | cloud | orange | `aliyun` |
| `baidu` | 百度网盘 | cloud | sky | `baidu` |
| `xunlei` | 迅雷网盘 | cloud | indigo | `xunlei` |
| `uc` | UC网盘 | cloud | amber | `uc` |
| `123pan` | 123云盘 | cloud | emerald | `123pan` |
| `tianyi` | 天翼云盘 | cloud | rose | `tianyi` |
| `pikpak` | PikPak | cloud | fuchsia | `pikpak` |
| `lanzou` | 蓝奏云 | cloud | teal | `lanzou` |
| `google_drive` | Google Drive | cloud | green | `google_drive` |
| `onedrive` | OneDrive | cloud | cyan | `onedrive` |
| `mega` | MEGA | cloud | red | `mega` |
| `magnet` | 磁力 | offline | yellow | `magnet` |
| `ed2k` | 电驴 | offline | pink | `ed2k` |
| `link` | 直链 | direct | slate | `link` |
| `unknown` | 待识别 | unknown | neutral | `unknown` |

颜色以辨识度优先，接近品牌印象但不追求复制品牌标准色，避免多个蓝色网盘在小标签中难以区分。

### 日夜颜色令牌

下表格式为“背景 / 文字 / 边框”。所有背景与文字组合的 WCAG 对比度均不低于 `7.97:1`。

| 色调 | 夜间 | 日间 |
|---|---|---|
| blue | `#1e3a8a / #dbeafe / #60a5fa` | `#dbeafe / #1e3a8a / #60a5fa` |
| violet | `#4c1d95 / #ede9fe / #a78bfa` | `#ede9fe / #4c1d95 / #a78bfa` |
| lime | `#365314 / #ecfccb / #a3e635` | `#ecfccb / #365314 / #a3e635` |
| orange | `#7c2d12 / #ffedd5 / #fb923c` | `#ffedd5 / #7c2d12 / #fb923c` |
| sky | `#0c4a6e / #e0f2fe / #38bdf8` | `#e0f2fe / #0c4a6e / #38bdf8` |
| indigo | `#312e81 / #e0e7ff / #818cf8` | `#e0e7ff / #312e81 / #818cf8` |
| amber | `#78350f / #fef3c7 / #fbbf24` | `#fef3c7 / #78350f / #fbbf24` |
| emerald | `#064e3b / #d1fae5 / #34d399` | `#d1fae5 / #064e3b / #34d399` |
| rose | `#881337 / #ffe4e6 / #fb7185` | `#ffe4e6 / #881337 / #fb7185` |
| fuchsia | `#701a75 / #fae8ff / #e879f9` | `#fae8ff / #701a75 / #e879f9` |
| teal | `#134e4a / #ccfbf1 / #2dd4bf` | `#ccfbf1 / #134e4a / #2dd4bf` |
| green | `#14532d / #dcfce7 / #4ade80` | `#dcfce7 / #14532d / #4ade80` |
| cyan | `#164e63 / #cffafe / #22d3ee` | `#cffafe / #164e63 / #22d3ee` |
| red | `#7f1d1d / #fee2e2 / #f87171` | `#fee2e2 / #7f1d1d / #f87171` |
| yellow | `#713f12 / #fef9c3 / #facc15` | `#fef9c3 / #713f12 / #facc15` |
| pink | `#831843 / #fce7f3 / #f472b6` | `#fce7f3 / #831843 / #f472b6` |
| slate | `#334155 / #f1f5f9 / #94a3b8` | `#f1f5f9 / #334155 / #94a3b8` |
| neutral | `#3f3f46 / #f4f4f5 / #a1a1aa` | `#f4f4f5 / #3f3f46 / #a1a1aa` |

`unknown` 额外使用虚线边框，避免只依赖颜色表达“尚未识别”。

## 测试与验收

- 后端回归：四种光鸭分享路径及带查询参数 URL 均保持操作类型 `link`，主页和未知路径同样不产生 `guangya` 全局分类。
- 前端注册表：四种光鸭分享 URL 的展示类型均为 `guangya`、标签为“光鸭网盘”、色调为 `lime`、操作类型为 `link`。
- 既有类型：18 个内置类型都有唯一键、合法类别、已存在色调和预期中文标签；具体 URL 规则优先于 HTTP 通用规则。
- 行为隔离：光鸭资源卡片仍保留原有直链操作路径，不出现 Provider、认证、转存或订阅入口；115、夸克、磁力、电驴和普通直链的操作行为不回退。
- 展示一致：资源卡片、频道标题摘要和频道管理对同一类型使用相同标签与色调；频道摘要可从条目重新得到光鸭主类型。
- 主题与响应式：在日间/夜间、桌面和 `390x844` 视口检查标签可读、可换行、不遮挡标题或按钮，并确认控制台无错误、页面无横向溢出。
- 工程验证：运行相关 Python/Node 单测、完整 `unittest`、项目 `compileall`、所有改动 JS 的 `node --check` 和 `git diff --check`。
