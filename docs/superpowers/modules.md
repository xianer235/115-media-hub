# 功能模块索引

> 这份文件只回答四个问题：**这个模块是干什么的、从哪进、会做什么、明确不做什么**。
> 它是索引，不是全集：架构不变量与产品口径细则看 `conventions.md`，当前状态看 `state.md`，
> 历史过程看 `handoff.md`，实现细节看 `specs/`。同一件事不要在这里和别处各写一遍。
>
> `相关代码` 里的文件路径是**必填项**：`tests/test_modules_doc.py` 会校验每个路由 / 服务 /
> provider 文件与页面模板都出现在本文档里，新增、改名或删除后忘了更新会直接测试失败。

## 怎么用

- 想知道"某功能在哪、能不能做某事"：先在本文档定位模块 → 看 `入口` 与 `不会做` → 细节再去 README 章节或 `specs/`。
- 改代码前先看 `不会做`：边界最容易被顺手改没（例：刮削页「扫描监控」按钮曾经顺手跑了自动整理，把用户已整理好的文件夹又套了一层）。
- 改完代码后按文末「维护规则」更新对应文档，别只改代码。

## 一、功能模块

### 资源中心（resource）
- **用途**：把外部资源变成网盘里的文件：同步 TG 频道、PanSou 盘搜、手动粘贴资源文本。
- **入口**：页面「资源中心」；`POST /resource/...`；CLI `resource ...`。
- **会做**：频道同步与分类、资源文本预览/导入、解析 magnet / ED2K / 直链与 115·夸克·天翼·123·阿里分享、提交导入任务（转存 / 离线 / 跨盘）、浏览网盘目录；任务可取消、清理、删除。
- **不会做**：不生成 STRM、不重命名整理；入库后是否刷新播放文件取决于是否命中监控任务（webhook / 导入完成触发）。
- **相关代码**：`app/routes/resource.py`、`app/services/resource.py`、`app/providers/pansou.py`；页面 `templates/partials/pages/resource.html`
- **细节**：`docs/superpowers/specs/2026-08-09-resource-sync-refresh-design.md`、`2026-08-27-cross-cloud-copy-design.md`

### 资源推荐（recommendation）
- **用途**：按 TMDB 排行榜 / 类型等条件发现影视，维护「想看」清单，再决定交给资源中心还是订阅。
- **入口**：页面「资源推荐」；`/recommendation/state`、`/recommendation/watchlist/*`。
- **会做**：拉取 trending / popular / discover 列表、增删改想看清单状态。
- **不会做**：不下载、不转存、不生成 STRM，也不会自动替你建订阅（要手动发起）。
- **相关代码**：`app/routes/recommendation.py`；页面 `templates/partials/pages/recommendation.html`

### 影视订阅（subscription）
- **用途**：按片名/剧名周期找资源并入库，持续追更。
- **入口**：页面「影视订阅」；`/subscription/...`；CLI `subscribe ...`。
- **会做**：按名称搜索资源、按质量/集数筛选、转存或磁力离线入库、记录剧集台账、可选通知，并在入库后精准触发监控刷新（STRM + 该任务的自动整理开关）；「扫描链接」弹窗支持一次粘贴多条（每行一条，115 可混排分享/磁力/电驴），每条链接各自排一次任务按顺序执行；磁力/电驴走 115 离线时，115 报「下载完成」后还会在**宽限期（30 秒 / 每 10 秒一次 / 最多 3 次）**重扫中转目录，避免 115 目录列表滞后于一瞬间把「文件刚到」判成「没有文件」。
- **不会做**：不直接写 STRM 文件（生成交给文件夹监控 / 目录树），不整理你已有的库结构。
- **相关代码**：`app/routes/subscription.py`、`app/services/subscription.py`；页面 `templates/partials/pages/subscription.html`
- **细节**：README 的「方案三 / 方案四」；磁力 / 电驴手动离线入库的实现说明用 `rg "磁力/电驴离线入库" docs/superpowers/handoff-archive.md` 定位

### 文件夹监控（folder monitor）
- **用途**：持续扫描网盘目录，为媒体文件生成 / 更新 `.strm`，并跟踪目录与文件的索引。
- **入口**：页面「文件夹监控」的监控卡片（运行、停止、定时、Webhook `POST /webhook/{任务名}`）；刮削页「扫描监控」按钮（`POST /monitor/scan`，局部指定目录）；CLI `monitor start|stop|list|logs`。
- **会做**：按 savepath / sharetitle / 指定目录确定范围 → 扫描子树 → 写或清理 STRM → 更新文件索引与首层时间基线 → 变更同步（网盘变更事件、待补扫范围、运行记录）。
- **不会做**：「扫描监控」按钮只同步 STRM，**不整理、不改名、不移动**；任何扫描都不删非受管文件；接收夹任务不参与目录扫描。自动整理只发生在「新资源入盘」链路（变更同步 / Webhook / 定时 / 资源导入完成 / 接收夹分发）。
- **相关代码**：`app/routes/monitor.py`、`app/services/monitor.py`、`app/services/monitor_changes.py`、`app/services/monitor_runs.py`、`app/services/strm_files.py`；页面 `templates/partials/pages/monitor_about.html`
- **细节**：`docs/superpowers/specs/2026-09-23-folder-monitor-workflow-design.md`、`2026-09-26-folder-receive-monitor-runtime-design.md`、`2026-09-23-folder-monitor-log-redesign.md`

### 接收夹（inbox，分类前的中转文件夹）
- **用途**：不想先挑分类时，先把磁力 / 转存 / 手动保存统一丢进来，由系统识别后再归类。
- **入口**：接收夹任务（`task_type=inbox`，内置不可新建第二个、不可改类型）的 Webhook、手动「立即整理并分发」、定时执行、离线下载完成回调。
- **会做**：识别电影 / 剧集 → 按**目标监控任务**的整理选项整理 → 移动进该分类监控目录 → 为分发条目排独立的目录扫描任务刷新 STRM；**同一部影视的多个条目/多个版本合并进同一个媒体文件夹**（文件夹撞名只保留一次改名、内容并进去；文件同名给后面的加 `(2)` 序号），某个条目自己的冲突只留它自己。
- **不会做**：不是强制流程（直接推送到分类监控目录的老用法继续有效）；自己不是扫描目录；低置信度 / 重名冲突 / 搬运失败会留在接收夹并写明原因；目标目录里已存在同名文件、且不是同一批正在整理的源文件时仍按冲突留守（不主动改出副本）。
- **相关代码**：`app/services/quick_import.py`、`app/routes/scraper.py`（快捷导入入口）
- **细节**：`docs/superpowers/specs/2026-09-23-folder-monitor-workflow-design.md` §3.4、`2026-09-26-folder-receive-monitor-runtime-design.md`

### 目录树同步（tree）
- **用途**：媒体库很大、更新不频繁时，用官方「导出目录树」一次性生成 STRM，规避风控。
- **入口**：页面「目录树同步」；`/tree/...`；CLI `tree run|full|list|...`。
- **会做**：调用官方导出接口（树文件放网盘根目录、同名旧树自动替换）→ 对比 sha1 → 增量或全量生成 `.strm`。
- **不会做**：不做实时监控（新增内容靠文件夹监控）；不整理、不改名、不移动网盘文件。
- **相关代码**：`app/routes/tree.py`、`app/services/tree.py`；页面 `templates/partials/pages/task.html`

### 刮削管理（scraper）
- **用途**：网盘文件浏览 + TMDB 识别绑定 + 批量重命名 / 移动 / 删除，让文件名符合播放器与刮削器预期。
- **入口**：页面「刮削管理」；`/scraper/...`；CLI `scrape ...`（含批量偏好设置）。
- **会做**：浏览多网盘目录、单个或批量识别（规则识别，可选 AI 候选兜底）、生成命名预览 → 确认执行 → 生成刮削任务并可回滚。
- **不会做**：不生成 STRM（改完由变更同步刷新播放文件）；页面操作必须先出预览再确认（自动整理链路除外，见文件夹监控 / 接收夹）；**不把已经落成 `剧名/Season NN/` 的内容再套一层媒体文件夹**（选中的是季目录、父目录名就是这部剧时就地整理，详见 `conventions.md` 的「整理锚点」）。
- **相关代码**：`app/routes/scraper.py`、`app/services/scraper.py`、`app/services/ai_match.py`；页面 `templates/partials/pages/scraper.html`

### 参数配置（settings）
- **用途**：全局配置与运维入口：认证、签到、通知、代理、安全、AI、版本。
- **入口**：页面「参数配置」；`/get_settings`、`/save_settings`、`/settings/...`。
- **会做**：网盘认证（115 扫码或手动 Cookie、阿里云盘官方 OAuth、其余 Cookie / 凭证）、Cookie 体检与凭证复制、115 每日签到开关与手动签到、企业微信通知、TG 代理与 PanSou / AI 连通测试、后台安全（登录密码、全局 `webhook_secret`）。
- **不会做**：不改任务、不动网盘文件、不生成 STRM。
- **相关代码**：`app/routes/settings.py`、`app/services/sign115.py`、`app/services/notify.py`；页面 `templates/partials/pages/settings.html`

### 播放代理（STRM 网关）
- **用途**：播放器点开 `.strm` 时，把请求换成可播放的真实地址。
- **入口**：`/strm/proxy`、`/strm/relay`（由生成的 `.strm` 内容调用）；`/strm/orphan-metadata/*` 处理刮削残留目录。
- **会做**：按 pick_code 解析 115 下载地址（RSA 加密协议，带缓存与地址刷新）、中转或重定向，兼容 Range 请求。
- **不会做**：不管目录结构、不判断媒体是否合法、不写 STRM 文件。
- **相关代码**：`app/routes/strm.py`

### 登录与页面外壳
- **用途**：登录鉴权、页面外壳与油猴脚本分发。
- **入口**：`/login`、`/logout`、`/`；`/userscript/magnet-helper.user.js`。
- **会做**：会话鉴权（未登录跳登录页）、渲染单页外壳并内联各页面模板、SSE 状态推送（`/events`、`/status-summary`）。
- **不会做**：不承载业务逻辑；业务接口都在各自路由模块。
- **相关代码**：`app/routes/pages.py`、`app/routes/events.py`

## 二、代码索引（文件 → 职责）

### 路由（HTTP 接口层）`app/routes/`

| 文件 | 职责 |
| --- | --- |
| `app/routes/pages.py` | 登录 / 登出、会话鉴权、主页面渲染、油猴脚本下载 |
| `app/routes/settings.py` | 配置读写、Cookie 体检、TG 代理 / PanSou / 通知 / AI 连通测试、115 扫码登录、阿里 OAuth、签到、provider 列表与凭证复制 |
| `app/routes/resource.py` | 资源中心全部接口：频道同步与分类、文本预览导入、ED2K 解析、导入任务增删查、网盘浏览 |
| `app/routes/recommendation.py` | 资源推荐状态与想看清单 |
| `app/routes/scraper.py` | 网盘文件浏览 / 改名 / 移动 / 复制 / 删除、批量识别与命名计划、刮削任务创建与回滚、接收夹快捷导入触发 |
| `app/routes/monitor.py` | 监控 Webhook 接收与签名校验、任务增删改、手动与指定目录扫描、运行记录（详情 / 重试 / 取消 / 清理）、日志、油猴任务列表 |
| `app/routes/subscription.py` | 订阅任务增删改、手动开始（含磁力 / 电驴链接注入，支持一次提交多条 `links`）、剧集台账、进度重建 |
| `app/routes/tree.py` | 目录树任务增删改、运行 / 全量重写、全量同步、任务与日志查询 |
| `app/routes/tmdb.py` | TMDB 搜索 / 详情 / 类型 / 排行榜 / discover 接口 |
| `app/routes/strm.py` | 播放代理（`/strm/proxy`、`/strm/relay`）与孤儿刮削元数据清理 |
| `app/routes/events.py` | SSE 状态推送 `/events` 与 `/status-summary` |

### 服务（业务逻辑层）`app/services/`

| 文件 | 职责 |
| --- | --- |
| `app/services/monitor.py` | 文件夹监控扫描主流程：范围判定、STRM 生成 / 清理、索引与首层基线、触发来源分支 |
| `app/services/monitor_changes.py` | 网盘变更事件同步：精准更新 STRM、待补扫范围、事件状态流转 |
| `app/services/monitor_runs.py` | 监控运行记录的结构化生命周期（run / event / 父子链路 / 保留清理） |
| `app/services/strm_files.py` | 受管 STRM 文件读写删除、空目录清理、孤儿元数据目录判定 |
| `app/services/quick_import.py` | 接收夹：识别 → 整理 → 分发到目标监控目录 |
| `app/services/tree.py` | 目录树 TXT → STRM 生成与增量对比 |
| `app/services/scraper.py` | 刮削核心：识别、命名计划、批量作业执行与回滚 |
| `app/services/ai_match.py` | OpenAI 兼容大模型辅助识别（关键词生成 + 候选选择，带缓存 / 重试 / 用量统计） |
| `app/services/resource.py` | 资源导入任务执行（磁力离线、网盘转存 / 接收 / 保存） |
| `app/services/subscription.py` | 订阅编排入口，聚合下列订阅子模块 |
| `app/services/subscription_runner.py` | 订阅队列调度与并发控制（支持一次追加多条手动候选、只触发一次调度） |
| `app/services/subscription_task_runner.py` | 单个订阅任务的一次完整执行 |
| `app/services/subscription_episode.py` | 剧集 / 集数识别与台账证据 |
| `app/services/subscription_share_selection.py` | 分享内容筛选（剧集 / 标题 / 质量） |
| `app/services/subscription_share_runtime.py` | 分享浏览与转存运行时 |
| `app/services/subscription_state.py` | 订阅状态与追更进度持久化 |
| `app/services/subscription_offline_cleanup.py` | 离线导入未命中文件的保留与到期清理 |
| `app/services/notify.py` | 企业微信通知（机器人 Webhook / 自建应用两通道） |
| `app/services/sign115.py` | 115 每日签到 |

### 网盘与外部 provider `app/providers/`

| 文件 | 职责 |
| --- | --- |
| `app/providers/base.py` | `CloudProvider` 抽象基类：统一接口、限流、Cookie 存取 |
| `app/providers/registry.py` | provider 注册表：按名称 / link_type 查找、启用状态管理 |
| `app/providers/common.py` | provider 共用小工具 |
| `app/providers/pan115.py` | 115 网盘实现（目录、转存、离线、下载地址解析配合） |
| `app/providers/pan115_qr.py` | 115 扫码登录（客户端 / 设备选择；非官方接口，失败时可回退手动 Cookie） |
| `app/providers/quark.py` | 夸克网盘实现 |
| `app/providers/tianyi.py` | 天翼云盘实现 |
| `app/providers/pan123.py` | 123 云盘实现 |
| `app/providers/aliyun.py` | 阿里云盘实现 |
| `app/providers/aliyun_oauth.py` | 阿里云盘官方 OAuth（PKCE 扫码，无 AppSecret） |
| `app/providers/pansou.py` | PanSou 盘搜聚合 |
| `app/providers/tmdb.py` | TMDB API 客户端 |
| `app/providers/discovery_base.py` | 发现型 provider 抽象基类（自定义渠道继承即可） |
| `app/providers/discovery_registry.py` | 发现型 provider 注册表与内置实现 |

### 页面模板 `templates/partials/pages/`

| 文件 | 对应界面 |
| --- | --- |
| `templates/partials/pages/resource.html` | 资源中心 |
| `templates/partials/pages/recommendation.html` | 资源推荐 |
| `templates/partials/pages/subscription.html` | 影视订阅 |
| `templates/partials/pages/scraper.html` | 刮削管理（含「扫描监控」按钮） |
| `templates/partials/pages/monitor_about.html` | 文件夹监控 + 关于 |
| `templates/partials/pages/task.html` | 目录树同步 |
| `templates/partials/pages/settings.html` | 参数配置 |

页面外壳（导航、主题）在 `templates/index.html`，登录页在 `templates/login.html`。

## 三、维护规则

| 你改了什么 | 必须同步更新 |
| --- | --- |
| 新增 / 删除 / 改名 路由、服务、provider 文件或页面模板 | 本文档第二节对应表格，必要时补第一节模块条目（`tests/test_modules_doc.py` 会强制） |
| 模块的「会做 / 不会做」边界变了（新增触发入口、新增自动行为等） | 本文档该模块条目；若属于长期口径，同时写进 `conventions.md` |
| 完成重要功能或重要修复 | `docs/superpowers/handoff.md` 追加一行，并运行 `scripts/rotate_handoff.py` |
| 发布新版本 | `version.json`、`CHANGELOG.md`、`README.md`、`state.md` 一起对齐 |
| 当前状态 / 待办变化 | `state.md` |

校验命令：`scripts/check.sh tests.test_modules_doc`（等价的原始命令是 `.venv/bin/python -m unittest tests.test_modules_doc -v`；全量测试里也会跑到）。

工具约定（`AGENTS.md` 是本机文件、不入库，所以把常用约定同步在这里）：

- 检索 `handoff-archive.md` / `handoff.md` / `CHANGELOG.md` 这类「一行一条超长记录」的文件时加 `--max-columns`：
  `rg -n --max-columns 300 "关键词" docs/superpowers/handoff-archive.md`。
  不加参数时一次 `rg "订阅" docs/superpowers/handoff-archive.md` 会吐出约 30 KB，加了只剩约 1.5 KB。
- 本地验证统一走 `scripts/check.sh`（编译 + 改动 JS 的 `node --check` + 指定测试或 `--all` + `handoff.md` 体积预算 + `git diff --check`），用法见脚本头部注释。
  `handoff.md` 是「每个会话开头都要读」的文件，超过 32768 字节即判定失败，提示运行 `scripts/rotate_handoff.py`；预算可用环境变量 `HANDOFF_BUDGET_BYTES` 覆盖。
