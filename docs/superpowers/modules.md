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
- **会做**：频道同步与分类、资源文本预览/导入、解析 magnet / ED2K / 直链与 115·夸克·天翼·123·阿里分享、提交导入任务（转存 / 离线 / 跨盘）、浏览网盘目录；任务可取消、清理、删除。**分享转存类任务「提交受理」不等于完成**：夸克 `/share/sharepage/save` 只返回 task_id，任务会先调 `wait_share_save` 等异步任务结束，再按落盘宽限期（`RESOURCE_SHARE_LANDING_TIMEOUT_SECONDS`，默认 120 秒）轮询目标目录确认文件真的出现，确认到才写 `completed`；超时未确认写 `submitted` 并注明「文件可能稍后出现」，把「已提交」和「已落地」分开，避免用户看到完成却在目录里找不到。**两条容易漏的路径也堵上了**：网盘不回 `task_id` 时不能当「同步完成」（改为按目录核对）；`submitted` 里的「未确认落地」不会被 `recover_submitted_resource_jobs_without_monitor` 改成 `completed`（靠 `extra_json.share_landing.confirmed=false` 区分），否则这个新状态只活 20 秒。
- **不会做**：不生成 STRM、不重命名整理；入库后是否刷新播放文件取决于是否命中监控任务（webhook / 导入完成触发）；超时未确认落地的任务不会自动重试转存（要重来就手动重跑），也不会替用户去猜「分享里到底有哪个文件」。
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
- **会做**：按名称搜索资源、按质量/集数筛选、转存或磁力离线入库、记录剧集台账、可选通知，并在入库后精准触发监控刷新（STRM）；**电视剧订阅自理新集**：入库后按任务自己的「入库后整理」选项（默认开启、standard 命名、中文标题）对本次新入库文件**原地改名**（只改文件名、不建目录、不移动，要求 `tmdb_id>0`），电影订阅不改名；「扫描链接」弹窗支持一次粘贴多条（每行一条，115 可混排分享/磁力/电驴），每条链接各自排一次任务按顺序执行；磁力/电驴走 115 离线时，115 报「下载完成」后还会在**宽限期（30 秒 / 每 10 秒一次 / 最多 3 次）**重扫中转目录，避免 115 目录列表滞后于一瞬间把「文件刚到」判成「没有文件」。
- **不会做**：不直接写 STRM 文件（生成交给文件夹监控 / 目录树），不整理你已有的库结构；**电视剧的原地改名只针对本次新入库文件，不承担「归档进片名文件夹」职责（那是接收夹的活），电影订阅 v1 一律不改名**；**跨盘补源只认夸克作源网盘**（`cross_copy_sources` 仅 `["quark"]`），阿里 / 115 作源未接。
- **跨盘补源触发口径**（2026-10-22 接通并修正判定时机；2026-10-23 删 prefer 档）：补源统一走 `_subscription_cross_copy_dispatch`，主链路里调用两次——**无候选时**在「等待资源」早退之前（本盘一条候选都没有必然缺，判定不依赖 `last_episode`）；**有候选时**在**目标目录扫描校准 `last_episode` 之后**（校准前是进度旧值，会恒判「本盘不缺」而永不补源，首轮真机就是这么一次都没触发的）。补源候选单独用夸克搜（`find_subscription_cross_copy_candidates`），不混进本盘候选。**模式只有 off / fallback 两态**（开 = fallback = 本盘缺才补：电影无候选算缺；电视剧候选集数取 `episode`/`range_end` 较大值，全都 ≤ `last_episode` 算缺）：同盘有资源时转存是服务端秒传，跨盘要下载再上传，命中也复制纯属浪费，还会因注册判缺用导入前状态与同盘导入重复下载同一批集。历史 `prefer` 值在 `normalize_subscription_cross_copy_mode` 里按 fallback 接管，存量任务不静默失效。
- **补源转存只转缺的集**（2026-10-22）：剧集任务 + 本盘已有进度时，`_stage_share_to_quark` 先调 `_scan_share_media_files` 只读地递归列分享文件，按集数挑出缺的（`_select_missing_episode_files` + `_dedupe_episode_files` 同集留最大），只把这几集转存进夸克中转；分享里没有缺集时一次转存都不发（连中转目录都不建）。扫不出文件（子目录 403 / 超过 `SHARE_SCAN_MAX_DIRS`）才退回整包转存，并在 `skipped` 里写明。**不要改回「整包转存后在中转里筛」**：下载虽然一样只下缺的，但夸克配额会被整包占住（不付费账号一个季包就满）。**退回整包前有体积闸门**（`staging_fallback_max_bytes`，环境变量 `CROSS_COPY_STAGING_FALLBACK_MAX_GB` 默认 10GB、0 = 不限制）：超过就跳过本轮并在 `skipped` 写明，宁可不补也不占配额。**判缺的输入必须区分「没扫成」和「真的没有」**：`_scan_subscription_existing_episodes_quietly` 失败返回 `None`（调用方退回 `last_episode` 口径），只有目录确实不存在才返回空集合——返回 `set()` 会被下游理解成「本盘一集都没有」，一次 Cookie 失效就会整季重下。
- **补源候选排序口径**（与主链路不同，别混用）：`find_subscription_cross_copy_candidates` 返回前会丢掉 `score < min_score` 和 `low_score_fallback` 的候选，再按「标题命中任务名优先 → 分数降序」重排。主链路的电视剧候选是「集数优先」排序，而跨盘候选多来自 TG 日报贴，容易解析出 1170 这类假集数，按集数取 top N 会把低分日报贴和**别的剧**顶到队首（实测《凡人修仙传》混进《光阴之外》的候选并排到第 3）。注册侧 `_pick_share_candidates` 另会跳过被长文本污染成 `...xxxhttps` 的链接。
- **源网盘界面只列夸克**（名单来自 `core.SUBSCRIPTION_CROSS_COPY_SOURCE_PROVIDERS`，与 `subscription_cross_copy.split_cross_copy_sources` 同源），历史上勾过的 115/阿里 不再静默——跑任务时写一条 warn 明确「暂未接通补源，本次已跳过」，没有可用源时也写一条，避免「开关是开的却什么都没发生」。
- **补源入库后按任务开关原地改名**（2026-10-22）：分享里复制过来的文件是分享原名（`S01E42.mp4`），跟订阅导入的 `剧名 (年份) - S01E42.mp4` 不一致，媒体库会有两种命名。所以单文件补源任务**复制成功后只在同一条 UPDATE 里打一个 `organize_state='pending'` 标记**（不额外写库），由 `subscription_cross_copy_organize` 的定时器成组（同目标目录 + 同任务）、等 90 秒防抖、CAS 抢占后调刮削的命名计划**原地改名**；开关沿用该订阅任务的「入库后整理（电视剧）」，关掉或 `tmdb_id<=0` 就标 `skipped` 不动手。文件夹任务与手动复制任务一律不标记。改名**只改文件名、不移动、不建目录**，所以不会把 Season 里的文件搬去别处。
- **补源落地后触发监控扫描**（2026-10-25，补 0.15.x 漏接线）：此前所有「文件落到 115」的链路（订阅导入、订阅批次收口、资源/离线导入、接收夹分发）都会按落点匹配监控任务并入队扫描，**只有跨盘复制收口没接**——复制进监控目录不出 STRM、要等下一次手动/cron 扫描（2026-10-20 的「联动验证」用的就是手动扫描，把缺口盖住了）。现在单文件补源在整理定时器分组改名结束（`_organize_group` 的 finally，成功/跳过/失败/异常都触发）后调 `trigger_cross_copy_monitor_refresh`，整包文件夹在 `_finish_folder_job` 收口直接触发（文件夹不改名，无顺序问题）。仅 115 目标、仅订阅补源；手动复制与非 115 目标不触发。**顺序不能反**：先改名再扫描——监控按改名后的文件名生成 STRM，放复制收口会扫出旧名 STRM，而改名事件不会追溯修正（新文件还不在监控索引里）。落点没纳入任何监控任务时写订阅日志「命中目录未纳入文件夹监控，入库后不会自动生成 STRM」（与订阅导入同文案）。**两条不误报口径**（2026-10-25 代码审查追加）：监控任务被明确停用（`enabled=False`）时入队返回 `disabled`，日志写「已停用，未自动扫描」而不能说「已触发」（否则用户去监控页面找不到运行记录）；目标网盘未配置时整组放弃触发（`monitor_ready=False`）——没有认证信息扫描必然失败，还会在「未配置」警告后再叠一条归因错误的提示。
- **补源落地后回写订阅状态**（2026-10-23）：补源是旁路——订阅主流程注册完跨盘复制任务就结束了，复制在 `cross_copy_jobs` 里独立跑，跑完没有任何代码回写 `subscription_task_state`，界面「最近命中 / 上次命中时间 / 追更进度」会一直停在上一次同盘导入的旧值（**目录里识别到的集数是对的**，那走实时扫描，只有这份持久化状态没跟上）。复制收口只打一个 `progress_state='pending'` 标记（与 `organize_state` 同一条 UPDATE），由 `subscription_cross_copy_progress` 定时器按订阅任务成组、过 30 秒防抖后**一次写回**：`last_episode` 取「已有进度」与「本组文件名解析出的集数最大值」的 max（不后退）、`stats.existing_episode_max` 同步抬高（界面「最近命中 · 3天前 · 已到 E42」读它）、`matched_resource_title` 写「任务名（夸克补源）」、`last_success_at` 刷成本次落地时间、detail 说明补了几集。整包文件夹补源解析不出集数时**只写命中记录不动进度**；订阅任务此刻正在跑就放回 `pending` 等下一轮，避免踩掉运行中状态。
- **命中后冷却（2026-10-26）**：命中并落入新资源后，暂停**自动**查询直到下一集播出前，避免重复空搜；未命中时频率完全不变（发现新集优先，不做未命中退避）。冷却锚点是库里已有的 `last_success_at`（每次命中都会刷新，所以一批新集分批上传时冷却会自动顺延，直到某一轮空手才真正计时）。终点的取值顺序：`hit_cooldown_mode=manual` 用命中 + `hit_cooldown_hours`；`off` 不冷却；`auto` 用「TMDB 下一集播出日 + 上次命中的时分 − 60 分钟」与「相邻两集播出日之差 × 0.85」取更早者，并封顶 7 天。**别把 `tmdb_next_air_date` 的 00:00 直接当终点**——命中那一轮刷新的 TMDB 里，`next_episode_to_air` 往往就是刚入库的这一集，日期已经在今天或昨天，直接当终点会让冷却永不触发。只拦 `cron` 触发，手动运行 / Seerr 点播 / 补源触发都不受限。**已完结只认 TMDB 的 `status ∈ {Ended, Canceled}`**（集数追平不算，避免 TMDB 集数滞后导致提前停摆）：跳过自动调度、列表标「已完结」、简介写「自动查询已停止，可手动运行」；手动跑一次若 TMDB 变回 `Returning Series` 会自动恢复。
- **相关代码**：`app/routes/subscription.py`、`app/services/subscription.py`、`app/services/subscription_cross_copy_organize.py`、`app/services/subscription_cross_copy_progress.py`；页面 `templates/partials/pages/subscription.html`
- **细节**：README 的「方案三 / 方案四」；磁力 / 电驴手动离线入库的实现说明用 `rg "磁力/电驴离线入库" docs/superpowers/handoff-archive.md` 定位

### Seerr 点播对接（servarr）
- **用途**：让 Seerr / Jellyseerr / Overseerr 把本面板当成 Radarr / Sonarr 服务器，家人的点播请求自动转成订阅任务（电影一部一任务、剧集按季拆多任务，provider 固定 115），立即触发一次全量搜索，之后与手动订阅完全同链路。
- **入口**：Seerr 侧「设置 → Radarr / Sonarr」添加服务器（地址 = 面板地址，API Key = 设置页生成）；本侧入口是 `/api/v3/*` 端点。
- **会做**：16 个 Radarr/Sonarr v3 端点（system/status、qualityProfile、rootfolder、tag、languageprofile、movie 的 lookup/list/detail/add/delete、series 的 lookup/list/detail/add/update/delete）；X-Api-Key 鉴权；tvdbId 经 TMDB /find 转 tmdbId；删除点播连带删订阅任务。
- **不会做**：不实现 queue / command / health 端点；不接 TVDB 直连；不管 Seerr 用户权限；不代理播放；不新建第二套任务存储。
- **相关代码**：`app/routes/servarr.py`、`app/providers/tmdb.py`（find_tmdb_id_by_tvdb_id）；设置页「后台安全管理」的「点播接口 API Key / 点播默认保存目录」
- **细节**：`docs/superpowers/plans/2026-10-24-servarr-seerr-api.md`

### 文件夹监控（folder monitor）
- **用途**：持续扫描网盘目录，为媒体文件生成 / 更新 `.strm`，并跟踪目录与文件的索引。
- **入口**：页面「文件夹监控」的监控卡片（运行、停止、定时、Webhook `POST /webhook/{任务名}`）；刮削页「扫描监控」按钮（`POST /monitor/scan`，局部指定目录）；CLI `monitor start|stop|list|logs`。
- **会做**：按 savepath / sharetitle / 指定目录确定范围 → 扫描子树 → 写或清理 STRM → 更新文件索引与首层时间基线 → 变更同步（网盘变更事件、待补扫范围、运行记录）；命中「整段名字只有推广话术」的假视频（`.mkv` / `.mp4` / `.DOC` / …）时跳过、不生成 STRM，已有的本地 STRM 按过期清理删掉。
- **不会做**：**任何扫描（含「扫描监控」按钮、变更同步、Webhook、定时）都不再自动整理，只生成 / 同步 STRM**，不整理、不改名、不移动；任何扫描都不删非受管文件；接收夹任务不参与目录扫描。
- **相关代码**：`app/routes/monitor.py`、`app/services/monitor.py`、`app/services/monitor_changes.py`、`app/services/monitor_runs.py`、`app/services/strm_files.py`；页面 `templates/partials/pages/monitor_about.html`
- **细节**：`docs/superpowers/specs/2026-09-23-folder-monitor-workflow-design.md`、`2026-09-26-folder-receive-monitor-runtime-design.md`、`2026-09-23-folder-monitor-log-redesign.md`

### 接收夹（inbox，分类前的中转文件夹）
- **用途**：不想先挑分类时，先把磁力 / 转存 / 手动保存统一丢进来，由系统识别后再归类。
- **入口**：接收夹任务（`task_type=inbox`，**每个网盘一个**：内置的「接收」保留给 115，其他网盘在页面点「新增接收夹」各加一个；**类型由入口决定、弹窗里不再选**——「接收夹整理」列表的新增按钮进来就是接收夹，「文件夹监控任务列表」的新增按钮进来就是目录同步任务；新增时先选网盘，已被别的接收夹占用的网盘在列表里禁选；任务类型保存后不可改）的 Webhook（**只有 115 的接收夹能开**）、手动「立即整理并分发」、定时执行、离线下载完成回调、分享转存 / 离线任务完成后的自动触发（**按归属接收夹触发，不再全局扇出**）。
- **会做**：接收夹可挂在任意已配置网盘（任务上的 `provider`，默认 115）；识别电影 / 剧集 → 按**接收夹任务自己的**整理选项整理 → 移动进**同盘**的电影 / 电视剧目标文件夹（目标是同盘远程路径，不再写死 115）；**仅当接收夹在 115 上、目标落在某个目录同步任务扫描范围内、并且搬运已回验落地时**，才为分发条目排独立的目录扫描任务刷新 STRM——115 的移动 / 改名接口只是「受理」，没确认落地就不排扫描、也不删接收夹源目录，条目留在接收夹等下一轮（详见 `conventions.md` 的「115 写操作按「受理 + 回验落地」处理」）；**同一部影视的多个条目/多个版本合并进同一个媒体文件夹**（文件夹撞名只保留一次改名、内容并进去；文件同名给后面的加 `(2)` 序号），某个条目自己的冲突只留它自己；**每个接收夹的状态、最近运行、最近接收统计、运行/中断、静默窗口互相独立**（同名相对路径如 `/接收` 在不同网盘不会串账）；识别扫不到条目时会按落盘宽限期重扫一次（默认 30 秒 / 每 10 秒 / 最多 3 次，与订阅链路一致）。
- **不会做**：不是强制流程（直接推送到分类监控目录的老用法继续有效）；自己不是扫描目录；**除 115 外的网盘只搬运、不生成 STRM（v1 不做跨盘分发 / 跨盘 STRM）**，也不能开 webhook（脚本上报的保存路径按 115 根目录解析）——弹窗里开关禁用、连「推送地址」整块一起收起，保存与配置归一化都会清掉 `webhook_enabled`，`/webhook/{任务名}` 也直接 400 拒绝；低置信度 / 重名冲突 / 搬运失败会留在接收夹并写明原因；目标目录里已存在同名文件、且不是同一批正在整理的源文件时仍按冲突留守（不主动改出副本）；**手工放进接收夹（网盘客户端 / 面板文件管理 / 其他工具）不会自动触发**，只能靠定时、手动「立即整理并分发」或 webhook；**接收夹任务当前一律不能删除**（不想用就把「启用本任务」关掉）；多季合集（`S01-S03`）**不自动拆分**，留在接收夹等人工处理；接收夹整理**不推送通知**（口径：通知只保留文件夹监控与订阅两条，结果只看监控日志与卡片状态）。
- **相关代码**：`app/services/quick_import.py`、`app/routes/scraper.py`（快捷导入入口）
- **细节**：`docs/superpowers/specs/2026-09-23-folder-monitor-workflow-design.md` §3.4、`2026-09-26-folder-receive-monitor-runtime-design.md`

### 目录树同步（tree）
- **用途**：媒体库很大、更新不频繁时，用官方「导出目录树」一次性生成 STRM，规避风控。
- **入口**：页面「目录树同步」；`/tree/...`；CLI `tree run|full|list|...`。
- **会做**：调用官方导出接口（树文件放网盘根目录、同名旧树自动替换）→ 对比 sha1 → 增量或全量生成 `.strm`。
- **不会做**：不做实时监控（新增内容靠文件夹监控）；不整理、不改名、不移动网盘文件。
- **相关代码**：`app/routes/tree.py`、`app/services/tree.py`；页面 `templates/partials/pages/task.html`

### 文件管理（scraper）
- **用途**：网盘文件浏览 + 常用文件操作（复制 / 移动 / 重命名 / 删除 / 新建文件夹）+ TMDB 识别绑定 + 批量重命名，让文件名符合播放器与刮削器预期。跨网盘复制也从这里发起（复制 → 切到目标网盘 → 跨网盘粘贴），支持一次选多个文件和整个文件夹。**跨网盘只支持复制，不提供移动**：移动要删源文件，跨盘删源出错无法回滚，所以跨盘时「移动」按钮置灰并提示改用复制（待移动清单可一键转成待复制）；同盘移动不受影响。接口层 `/scraper/{provider}/move` 也会校验 `source_provider`，不一致直接 400，防止脚本绕过前端。
- **入口**：页面「文件管理」（模块名仍是 `scraper`，路由不变）；`/scraper/...`；`/cross_copy/...`；CLI `scrape ...`（含批量偏好设置）。
- **会做**：浏览多网盘目录、单个或批量识别（规则识别，可选 AI 候选兜底）、生成命名预览 → 确认执行 → 生成刮削任务并可回滚；115 的批量改名 / 移动会先等「受理结果回验落地」再按成功收尾监控同步事件（未确认落地时事件转 `needs_reconcile` 兜底重试，不判死）；跨网盘粘贴时先查能力矩阵，再弹确认框写明「先下载到本地暂存再上传、大文件慢、秒传命中只下载」，文件夹会额外提示逐个文件复制。
- **不会做**：不生成 STRM（改完由变更同步刷新播放文件）；页面操作必须先出预览再确认（自动整理链路除外，见文件夹监控 / 接收夹）；**不把已经落成 `剧名/Season NN/` 的内容再套一层媒体文件夹**（选中的是季目录、父目录名就是这部剧时就地整理，详见 `conventions.md` 的「整理锚点」）；跨网盘**移动**不支持文件夹，也不删源。
- **相关代码**：`app/routes/scraper.py`、`app/services/scraper.py`、`app/services/ai_match.py`、`app/services/cross_cloud_copy.py`、`app/services/cross_cloud_copy_folder.py`、`app/services/cross_copy_jobs.py`；页面 `templates/partials/pages/scraper.html`、弹窗 `templates/partials/modals/cross_copy.html`

### 参数配置（settings）
- **用途**：全局配置与运维入口：认证、签到、通知、代理、安全、AI、版本。
- **入口**：页面「参数配置」；`/get_settings`、`/save_settings`、`/settings/...`。
- **会做**：网盘认证（115 扫码或手动 Cookie、阿里云盘官方 OAuth、其余 Cookie / 凭证）、Cookie 体检与凭证复制、115 每日签到开关与手动签到、企业微信通知（四个场景开关：订阅更新成功、文件夹监控生成成功、跨盘复制按任务来源分订阅补源/手动复制；渠道配置共用，场景开关互不影响）、TG 代理与 PanSou / AI 连通测试、后台安全（登录密码、全局 `webhook_secret`）、本地暂存目录管理（单个容器内目录 `cross_copy_temp_dir`，空 = 默认 `/app/config/cross_copy_tmp`；保存前探测存在/可写/剩余空间；旧版「位置列表」配置读取时一次性迁移）、**夸克中转残留清理（`cross_copy_staging_retention_days`，0 = 关，默认 7 天；清理动作由 `cross_copy_staging_cleanup` 后台定时器执行，设置页只负责保存天数）**。
- **不会做**：不改任务、不动网盘文件、不生成 STRM；换暂存目录只改配置，不碰磁盘上的实际文件。
- **相关代码**：`app/routes/settings.py`、`app/services/sign115.py`、`app/services/notify.py`、`app/services/local_storage.py`；页面 `templates/partials/pages/settings.html`

### 播放代理（STRM 网关）
- **用途**：播放器点开 `.strm` 时，把请求换成可播放的真实地址。
- **入口**：`/strm/proxy`、`/strm/relay`（由生成的 `.strm` 内容调用）；`/strm/orphan-metadata/*` 处理刮削残留目录。
- **会做**：按 pick_code 解析 115 下载地址（RSA 加密协议，带缓存与地址刷新）、中转或重定向，兼容 Range 请求。加密取链逻辑已下沉到 `app/providers/pan115_downurl.py`，本模块只保留薄封装，跨盘复制等 provider 侧调用复用同一套实现。
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
| `app/routes/cross_copy.py` | 跨盘复制：源×目标能力矩阵、任务增查、取消 / 重试、清除记录（批量 + 单条） |
| `app/routes/servarr.py` | Radarr/Sonarr v3 兼容层（Seerr 点播对接）：静态系统信息、电影/剧集查询与点播增删，X-Api-Key 鉴权，转订阅任务 |

### 服务（业务逻辑层）`app/services/`

| 文件 | 职责 |
| --- | --- |
| `app/services/monitor.py` | 文件夹监控扫描主流程：范围判定、STRM 生成 / 清理、索引与首层基线、触发来源分支 |
| `app/services/monitor_changes.py` | 网盘变更事件同步：精准更新 STRM、待补扫范围、事件状态流转 |
| `app/services/monitor_runs.py` | 监控运行记录的结构化生命周期（run / event / 父子链路 / 保留清理） |
| `app/services/strm_files.py` | 受管 STRM 文件读写删除、空目录清理、孤儿元数据目录判定 |
| `app/services/quick_import.py` | 接收夹：识别 → 整理 → 分发到同盘目标文件夹（仅 115 命中扫描范围才刷 STRM） |
| `app/services/tree.py` | 目录树 TXT → STRM 生成与增量对比 |
| `app/services/scraper.py` | 刮削核心：识别、命名计划、批量作业执行与回滚 |
| `app/services/ai_match.py` | OpenAI 兼容大模型辅助识别（关键词生成 + 候选选择，带缓存 / 重试 / 用量统计） |
| `app/services/resource.py` | 资源导入任务执行（磁力离线、网盘转存 / 接收 / 保存） |
| `app/services/subscription.py` | 订阅编排入口，聚合下列订阅子模块 |
| `app/services/subscription_runner.py` | 订阅队列调度与并发控制（支持一次追加多条手动候选、只触发一次调度） |
| `app/services/subscription_task_runner.py` | 单个订阅任务的一次完整执行；跨盘补源的「缺不缺 + 触发注册」也在这里（`_subscription_cross_copy_needed`） |
| `app/services/subscription_episode.py` | 剧集 / 集数识别与台账证据 |
| `app/services/subscription_share_selection.py` | 分享内容筛选（剧集 / 标题 / 质量） |
| `app/services/subscription_share_runtime.py` | 分享浏览与转存运行时 |
| `app/services/subscription_state.py` | 订阅状态与追更进度持久化 |
| `app/services/subscription_offline_cleanup.py` | 离线导入未命中文件的保留与到期清理 |
| `app/services/notify.py` | 企业微信通知（机器人 Webhook / 自建应用两通道）：订阅成功 / 监控成功 / 跨盘复制（按任务来源分开关）三个推送场景，渠道就绪检查 `notify_channel_ready` 与场景开关解耦；**订阅补源成功并入订阅成功那一条**（`push_cross_copy_subscription_notification`，文案同「订阅更新成功」，多一行「来源：跨盘补源（夸克 → 115）」，集数去重与同盘导入共用 `notification_dedupe` 表）；`subscription_cross_copy_notify_merged(cfg)` 是两个开关都开才合并的判据 |
| `app/services/sign115.py` | 115 每日签到 |
| `app/services/cross_cloud_copy.py` | 跨盘复制引擎（P0-B）：源直链下载（并行分段，`CROSS_COPY_DOWNLOAD_PARALLEL`，落盘后顺序算哈希）+ 同步 SHA1/MD5 + 内存/磁盘双通道 + 目标秒传/分片上传 + 取消/换链重试/幂等/孤儿清理；零流量路径（源端已知哈希 + 惰性 sink，秒传命中不下载）与断点续传管道（resume 状态就地更新 + on_resume_update 上报 + 失败保留临时文件） |
| `app/services/cross_cloud_copy_folder.py` | 整文件夹跨盘复制：BFS 递归建清单（上限 2000 文件 / 20 层，超限拒绝）、目标端逐级建目录、字节加权进度、单文件失败继续并汇总 partial |
| `app/services/media_hash_cache.py` | 文件哈希备忘录（media_hash_cache）：按 (provider, file_id) 沉淀已确认的 SHA1，查缓存校验 size、30 天过期，供跨盘复制复用零流量秒传；缓存故障不影响复制主流程 |
| `app/services/local_storage.py` | 本地暂存目录管理：容器内路径归一化、默认目录（config 卷下 `cross_copy_tmp`）、旧位置列表配置迁移、目录可用性探测、暂存目录解析、磁盘空间预检；挂载点枚举（解析 `/proc/mounts`，区分「真实挂载盘 / 容器可写层」）、候选目录列表、受控建目录（只允许在已挂载盘里建，防止把宿主机路径建成容器层目录） |
| `app/services/cross_copy_resume.py` | 跨盘复制断点续传状态管理：运行前校验（临时文件在/前缀完整/复探源哈希防旧内容上传）、全新骨架构造、可继承性判断、落库净化（深拷贝并剔除 on_part_done 等运行时字段，保证状态可 JSON 序列化）、作废与孤儿清理联动 |
| `app/services/cross_copy_staging_cleanup.py` | 夸克中转目录残留自动清理：定时（默认 1800 秒）扫 `${CROSS_COPY_STAGING_ROOT}` 下每个任务目录，按「条目修改时间早于 `cross_copy_staging_retention_days` 天」判定过期，只删过期条目、只删确认为空的目录，任务根目录与 `cid=="0"` 受保护；**运行中任务的条目一律不删**（先查 `cross_copy_jobs` 的活跃任务做保护集，查不到就整轮跳过）；删除是移进夸克回收站，配额不会立即释放；开关就是 `cross_copy_staging_retention_days`（设 0 = 关闭，默认 7 天） |
| `app/services/subscription_cross_copy_organize.py` | 订阅补源「入库后整理」定时器：捞 `organize_state='pending'` 且已过防抖窗口（90 秒）的任务 → 按（目标网盘 + 目标目录 + 订阅任务名）成组 → 沿用该订阅任务的「入库后整理」开关，调刮削命名计划**原地改名** → 把结果写回 `organize_*`。复制收口只打标记，真正的改名叫这里做（刮削任务最长几分钟，塞进复制收口会占死并发名额）；`locate_subscription_imported_files` 也从 runner 上移到这里 |
| `app/services/cross_copy_jobs.py` | 跨盘复制任务表（cross_copy_jobs）：创建 / 状态机 / 取消 / 重试 / 启动恢复 / 进度上报 / 完成失败通知（按 origin 选订阅补源/手动开关）/ 记录清除与自动裁剪 / 断点续传生命周期（骨架落库、终态保底、成功清除）；**订阅补源单文件任务复制成功时顺手把 `organize_state` 标成 `pending`（同一条 UPDATE），真正的改名交给 `subscription_cross_copy_organize` 的定时器**；**订阅补源任务（含整包文件夹）成功时同一条 UPDATE 打 `progress_state='pending'`，进度回写交给 `subscription_cross_copy_progress`**；**订阅补源成功不再逐文件发「跨盘复制完成」（`subscription_cross_copy_notify_merged` 为真时跳过），由进度回写成组发一条订阅通知；失败与手动复制照旧逐条发**；重试会清空这两个标记 |
| `app/services/subscription_cross_copy_progress.py` | 订阅补源「回写进度」定时器：捞 `progress_state='pending'` 且已过防抖窗口（30 秒）的任务 → 按订阅任务名成组 → 从落地文件名解析集数（复用订阅侧识别器）→ 一次写回 `subscription_task_state` 的 `last_episode`（与已有进度取 max，不后退）/ `matched_resource_title` / `last_success_at` / detail / stats。补源是旁路，没有它界面「最近命中 / 追更进度」会停在同盘导入的旧值；订阅任务正在跑时放回 `pending` 等下一轮。**写回后再发一条「订阅更新成功」**（`push_cross_copy_subscription_notification`，两个开关都开才发），所以补 5 集只收到 1 条汇总而不是 5 条搬运消息。攒批两道闸（`collect_notify_batch`）：该任务还有 pending/running 补源任务就先不发（跨盘一集几分钟、全局并发 2，兄弟任务不会同时完成）；发时按 `stats.cross_copy_notified_at` + `cross_copy_notified_job_id` 复合游标把上次通知之后完成的全部任务聚合起来（只用 id 会漏掉「重试后 id 不变、完成时间变晚」的那种）；游标缺失时只回溯 24 小时，不补发历史。通知失败不影响已写回的进度 |
| `app/services/subscription_cross_copy.py` | 订阅跨盘补源：夸克分享候选 → 转存夸克中转目录 → 注册复制任务（save_first + 去重）；**落点直接复用订阅导入的目录函数**（`core.build_subscription_movie_savepath` / `build_subscription_tv_savepath`，见 `_cross_copy_target_savepath`），不在这里另拼字符串；`split_cross_copy_sources` 负责区分「已接通/未接通」的源网盘，供主链路写跳过日志；**转存前先扫分享，只转存缺的集**（`_scan_share_media_files` + `_dedupe_episode_files`，2026-10-22；无缺集时一次转存都不发、连中转目录都不建，扫不动才退回整包）；**转存后必须等夸克异步任务落地再列目录**（`provider.wait_share_save`，save 只返回 task_id，2026-10-22 真机排查）；**按集筛缺覆盖「整季文件夹」和「散文件」两条路**（`_expand_staged_folder_media_files` + `_select_missing_episode_files`，判缺优先用 `existing_episodes` 集集合——能识别中间缺集，不传才退回比 `last_episode`；同一轮内按集去重，认不出集数的文件不复制）；`cleanup_staging_empty_folders` 在每轮注册后清中转目录的空文件夹（DFS 倒序、只删确认为空的、任务根与 `cid=="0"` 受保护）；由 `run_subscription_task` 主链路调用，夸克源候选由 `subscription.find_subscription_cross_copy_candidates` 搜出 |

### 网盘与外部 provider `app/providers/`

| 文件 | 职责 |
| --- | --- |
| `app/providers/base.py` | `CloudProvider` 抽象基类：统一接口、限流、Cookie 存取、上传抽象（UploadSink/UploadResult/UploadError） |
| `app/providers/registry.py` | provider 注册表：按名称 / link_type 查找、启用状态管理 |
| `app/providers/common.py` | provider 共用小工具 |
| `app/providers/pan115.py` | 115 网盘实现（目录、转存、离线、下载地址解析配合、写操作受理重试与落地回验、上传/秒传：initupload + OSS 分片） |
| `app/providers/pan115_cipher.py` | 115 上传协议加密封装：纯 Python AES-128-CBC + LZ4 解压 + 载荷编解码（零第三方依赖） |
| `app/providers/pan115_downurl.py` | 115 大文件取链：RSA + XXTEA 加密的 `app/chrome/downurl` 通道（普通取链遇 50028 时回退），从 `routes/strm.py` 下沉 |
| `app/providers/pan115_qr.py` | 115 扫码登录（客户端 / 设备选择；非官方接口，失败时可回退手动 Cookie） |
| `app/providers/quark.py` | 夸克网盘实现（目录、分享解析/转存、写操作、下载直链、上传/秒传：md5+sha1 双哈希 + OSS 分片） |
| `app/providers/tianyi.py` | 天翼云盘实现 |
| `app/providers/pan123.py` | 123 云盘实现 |
| `app/providers/aliyun.py` | 阿里云盘实现（**双模式**：扫码授权 access_token 走 openapi.alipan.com `/adrive/v1.0/openFile/*`，网页会话 refresh_token 走 api.alipan.com；目录、分享解析/转存（仅网页模式）、写操作、上传/秒传：pre_hash + content_hash + proof_code + 10MB 分片） |
| `app/providers/aliyun_oauth.py` | 阿里云盘官方 OAuth（PKCE 扫码，无 AppSecret；scope 含 file:all:read/write） |
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
| `templates/partials/pages/scraper.html` | 文件管理（含「扫描监控」按钮） |
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
