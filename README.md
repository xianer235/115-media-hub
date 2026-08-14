# 115 Media Hub

`115 Media Hub` 是一个基于 FastAPI 的媒体自动化管理面板，把 `115` / `Quark` / `天翼云盘` / `123云盘` / `阿里云盘` 等多网盘转存、115网盘的`.strm` 生成、TG 资源同步、影视订阅追更、刮削管理放进同一个后台。

它适合希望直接用网盘 Cookie 驱动"生成播放链接""转存后自动刷新""按片名自动找资源""批量重命名刮削"一体化流程的场景。

## 近期更新（以 `version.json` 为准）

- 当前版本：`0.6.2`
- 任务中心手机端操作按钮可收缩换行不再向左溢出，按钮文案精简（取消/重试/立即刷新/无需刷新/未绑定监控），禁用配色不变。
- 搜索/识别提示条与结果副标题的长关键词（磁力/链接）改为中间省略显示，避免手机端横向溢出；原文预览保留完整内容。
- 任务历史清理改为后台周期执行（默认每 10 分钟，`RESOURCE_JOB_PRUNE_INTERVAL_SECONDS` 可调），打开资源中心不再触发删除；保留上限 `RESOURCE_JOB_COMPLETED_KEEP` / `RESOURCE_JOB_FAILED_KEEP` 不变。
- 刮削交互与保留标签优化：批量搜索绑定结果展示封面、手机端工具栏一行显示、命名选项按文件夹结构/文件清理分组；保留标签新增“语言/字幕”；批量整理任务名展示 TMDB 绑定信息（单条“标题 (年份)”、多条“首部标题 等 N 项”）。
- 批量整理：勾选识别 → 批量计划/执行 → 监控目录 STRM 联动，支持整库按子目录自动拆分扫描（分类容器递归下探）。
- 识别核心升级：guessit 发布名解析 + TMDB 多候选打分（年份硬约束、别名破平局、中英混排拆词、噪声词库扩展）。
- 监控任务新增“新增资源自动刮削整理”，仅对高置信度自动匹配条目执行一次，失败仅记日志。
- 手动识别与批量识别合并为单一入口，预览、绑定、广告文件处理等交互全面优化。
- “需手动监控”提示可点击查看明细（事件号、操作类型、旧/新路径与处理提示），重新扫描后自动清除；刮削页 URL 参数仅在刮削 tab 生效。
- 刮削路径同步失败只写入监控日志并删除事件，不累计重试次数或持久化失败计数；普通文件夹监控变更仍保留原有退避重试。
- 刮削精准同步日志现在会列出实际删除、生成的本地 STRM 路径；文件夹操作只显示一行目录与计数摘要，避免大量展开。
- 修复 115 刮削批量改名的完整路径传递：监控目录内批量操作按“删旧 STRM、生成新 STRM”精准同步，避免重新全量访问网盘。
- 未知或不完整文件夹索引显示“需手动监控”，处理中断恢复会按顺序重放本地变更，避免漏掉文件或留下孤儿 STRM。
- 修复资源中心频道同步完成后空搜索首页不自动刷新；有搜索词时保留当前搜索结果，并补充同步状态竞态回归测试
- 频道同帖多种网盘、磁力、ED2K 和展示型直链统一保存，卡片支持按具体链接复制；下载/转存只显示当前可导入的链接。
- 修复任务中心“删除记录”按钮在浅色主题下不可见的问题，重新生成 Tailwind 样式补上缺失的工具类
- 修复活跃频道同步可能漏掉最新资源：同步取样按发布时间/消息号倒序收集，第一页超过每频道保留数量时仍取最新一批
- 资源任务弹窗头部只保留“任务列表”，去掉与“任务中心”重复的眉题
- Telegraph 电驴页面仅支持 `telegra.ph` 解析；直接电驴保持下载，普通直链与未接入网盘链接不会误触发解析
- 光鸭网盘保持链接识别展示，下载按钮会明确禁用；115、夸克、阿里、天翼和 123 云盘分享转存不受影响
- 刮削标准命名重复识别时自动跳过完整路径无变化文件，减少重复网盘访问，并在预览中显示跳过数量
- 频道资源卡片、频道摘要和频道管理统一使用资源类型标签，并适配日间与夜间模式
- 光鸭分享链接显示独立类型标签，但仍保持普通直链下载语义，不扩展未验证的转存能力
- 手机竖屏资源卡片的四个操作按钮改为底部单排，设置页同步明确磁力、电驴链接仅支持 115 网盘
- 多云盘支持：新增天翼云盘、123云盘、阿里云盘 provider，统一通过 Cookie 驱动
- 全局安全加固：API 认证中间件、CSRF 防护、bcrypt 密码哈希、登录失败限流
- 刮削管理：网盘文件浏览、TMDB 识别绑定、批量重命名预览与执行
- 资源推荐页：Explore 筛选与资源发现，支持多维度筛选与快速导入
- 目录树同步优化：流式解析降低内存峰值，支持超大目录树
- 监控智能补扫：失败子目录精准补扫，连续缺失确认后自动释放

## 核心功能

| 模块 | 作用 |
| --- | --- |
| 资源中心 | 同步 TG 公开频道、接入 PanSou 盘搜、手动预览/导入资源文本，支持 magnet、115/Quark/天翼/123/阿里分享入库并提交导入任务 |
| 资源推荐 | Explore 筛选与资源发现，多维度筛选与快速导入 |
| 影视订阅任务 | 电影/剧集自动匹配资源并入库，支持多网盘 provider、周期时段调度、评分阈值、质量偏好、TMDB 绑定与追更状态 |
| 文件夹监控任务 | 扫描网盘目录变化，支持手动、定时、Webhook 触发，并可按 savepath/sharetitle 局部刷新；智能补扫失败子目录 |
| 目录树任务 | 基于 115 官方目录树 TXT 文件批量生成 `.strm`，流式解析支持超大目录树 |
| 刮削管理 | 网盘文件浏览、TMDB 识别绑定、批量重命名预览与执行，支持任务中心统一管理 |
| 企业微信通知推送 | 可对订阅成功和监控生成成功事件推送提醒，支持机器人和应用两种通道 |
| 115 每日签到 | 支持手动签到与每日定时签到，并在页面顶部展示签到状态 |
| Web 管理后台 | 集中管理配置、任务、日志、版本提示，支持桌面和移动端 |

适合这些场景：

- 大媒体库初始化：先用目录树任务一次性生成 `.strm`
- 连载或日更内容：用文件夹监控任务做持续补扫和过期 STRM 清理
- 转存成功后自动补扫：用 Webhook 触发指定监控任务
- 想减少手动找资源：用资源中心和影视订阅任务自动化处理
- 需要批量重命名刮削：用刮削管理页面识别、绑定、预览和执行
- 多网盘混合使用：同一面板管理 115/Quark/天翼/123/阿里云盘

## 怎么选任务

| 需求 | 推荐方式 |
| --- | --- |
| 媒体库很大、更新不频繁 | `目录树任务` |
| 已有固定目录，想持续补新内容 | `文件夹监控任务` |
| 想按影片/剧集名称自动找资源 | `影视订阅任务` |
| 想把 115 转存、磁力离线、刷新串起来 | `资源中心 + Webhook + 文件夹监控任务` |
| 想导入 Quark 分享但不生成 115 strm 刷新 | `资源中心或影视订阅任务的 Quark 模式` |
| 需要批量重命名刮削网盘文件 | `刮削管理` |

## 快速开始

的镜像名为 `xianer235/115-media-hub:latest`：

```yaml
services:
  115-media-hub:
    image: xianer235/115-media-hub:latest
    container_name: 115-media-hub
    restart: unless-stopped
    ports:
      - "18080:18080"
    volumes:
      - ./strm:/app/strm
      - ./config:/app/config
      - ./logs:/app/logs
    environment:
      - TZ=Asia/Shanghai
```

其中 `./strm` 是输出给媒体服务器使用的目录，通常还需要再挂载给 Emby、Jellyfin 或 Plex；`./config` 和 `./logs` 建议持久化保留。

启动命令：

```bash
docker compose up -d
```

访问地址：

- `http://服务器IP:18080`

默认账号密码：

- 用户名：`admin`
- 密码：`admin123`

首次登录后，建议立刻到「参数配置」页修改后台账号密码，并配置 `webhook_secret`。

## 命令行工具（CLI）

`cli.py` 是运行在宿主机上的命令行客户端（不进入容器镜像），通过面板自身的 HTTP API 完成
搜索、订阅、转存、监控、刮削等操作，方便 AI 代理或脚本直接管理媒体中心，无需打开网页。

安装依赖（仅宿主机需要，与容器镜像无关）：

```bash
python3 -m venv .cli-venv
.cli-venv/bin/pip install -r requirements-cli.txt
```

使用（登录账号密码与网页登录一致，需先设置环境变量；非交互环境未提供凭据时会直接报错）：

```bash
export MH_USERNAME=admin
export MH_PASSWORD=你的面板密码
export MH_API_BASE=http://127.0.0.1:18080   # 可选，默认即本机
.cli-venv/bin/python cli.py status
.cli-venv/bin/python cli.py search "黑客帝国 4K"
.cli-venv/bin/python cli.py subscribe list
```

常用命令：`status` / `version` / `search <关键词>|--cancel` / `channels sync` /
`subscribe list|add|remove|start` / `jobs list|retry|cancel` / `scrape jobs-create` /
`monitor list|start|stop` / `tree run` / `sources search` / `daemon status|logs|restart`。
完整命令列表见 `CLI-API-AUDIT.md`；`sources` / `daemon` 等容器运维命令需要宿主机安装 Docker，
容器名自动识别 `115-media-hub` / `115-media-hub-test`，也可用环境变量 `MH_CONTAINER` 覆盖。

## 首次配置顺序

建议第一次按下面顺序配置，这样最省回头路：

1. 配置 `115 Cookie`（按需再填 `Quark Cookie` 或其他云盘 Cookie）
2. 配置 `STRM 对外访问地址`（例如 `http://192.168.1.20:18080`）
3. 根据账号风控策略调整 `115 API 最小间隔`、`目录缓存 TTL`、`下载链接缓存 TTL`
4. 确认 `扫描后缀名` 是否符合你的媒体类型
5. 如果要提升影视订阅识别准确率，再启用 `TMDB API Key`
6. 如果要使用 PanSou 盘搜，在「PanSou 盘搜」里填写服务地址；如 PanSou 开启认证，再填写账号/密码，按需填写 src / channels / plugins 并点击测试
7. 如果服务器访问 TG / TMDB 不稳定，再补充代理设置（同一套代理配置会同时用于 TG 与 TMDB）
8. 点击 Cookie 健康检测，确认 115 / Quark / 天翼 / 123 / 阿里 Cookie 可用
9. 如果要自动签到 115，再开启 `115 每日签到` 并设置签到时间
10. 如果要在任务成功后收到提醒，再配置「通知推送（企业微信）」并发送测试消息

## 推荐使用流程

### 方案一：先建库，再持续增量

1. 在「参数配置」中填好 115 Cookie 与 STRM 对外访问地址（网盘前缀映射已内置：`115 -> /115`、`Quark -> /quark`、`天翼 -> /tianyi`、`123 -> /pan123`、`阿里 -> /aliyun`）
2. 在「目录树任务」里配置一个或多个目录树源
3. 先跑一次目录树任务，完成 `.strm` 初始化
4. 再为常更新目录添加「文件夹监控任务」，用于后续补扫与过期 STRM 清理

### 方案二：转存完成后自动刷新

1. 创建一个开启了 Webhook 的文件夹监控任务
2. 让外部工具在转存完成后调用 `/webhook/{任务名}`
3. 服务端收到请求后，会优先按 `savepath` / `sharetitle` 做局部刷新

### 方案三：自动找资源并导入网盘

1. 在「资源中心」配置 TG 频道源，也可以在参数配置里开启 PanSou 后切到「盘搜」搜索，或手动粘贴资源文本
2. 按目标网盘配置相应 Cookie（115 / Quark / 天翼 / 123 / 阿里）
3. 在「影视订阅任务」中创建订阅项，并选择 provider
4. 系统按周期匹配候选资源，并创建导入任务

### 方案四：批量重命名刮削

1. 进入「刮削管理」页面，浏览网盘目录
2. 选择需要刮削的文件或文件夹
3. 点击「识别与命名」，系统自动匹配 TMDB 信息
4. 确认识别结果后，预览新文件名
5. 执行批量重命名，支持回溯最近重命名记录

## Webhook 说明

Webhook 地址格式：

```text
POST /webhook/{任务名}
```

普通刷新请求示例：

```json
{
  "savepath": "/连载中",
  "sharetitle": "示例剧名",
  "delayTime": 30,
  "title": "CloudSaver 转存完成"
}
```

磁力导入请求示例：

```json
{
  "savepath": "/电影",
  "magnet": "magnet:?xt=urn:btih:xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "title": "示例电影",
  "delayTime": 10
}
```

常用字段：

- `savepath`：转存目标父目录。磁力导入场景下必填
- `sharetitle`：资源文件夹名。提供后会优先做更小范围的局部刷新
- `delayTime`：本次延时秒数；大于 0 时覆盖监控任务默认延时，不传或为 0 时使用任务默认延时
- `title`：只用于日志展示
- `magnet` / `link_url` / `url`：可选，可直接触发资源导入流程

油猴脚本任务和文件夹监控任务的关系：

- 脚本"请求地址"必须指向已开启 Webhook 的监控任务：`http://IP:端口/webhook/{任务名}`，后台用 `{任务名}` 找到要触发的文件夹监控任务
- 如果通过域名和 HTTPS 暴露服务，脚本和网页前端应使用反代入口：`https://域名/webhook/{任务名}`，不要把容器 HTTP 端口写成 `https://IP:端口`
- 脚本"保存路径 savepath"是磁力离线下载到 115 的目标目录；它会拼到 115 挂载前缀后和监控任务"扫描路径"匹配
- 只有 `savepath` 落在该监控任务的扫描路径内，导入成功后才会自动触发刷新并生成 `.strm`
- 脚本"延迟"是导入成功后等待几秒再刷新；填 0 或不填时使用监控任务默认延迟
- 脚本"名称"只用于 Tampermonkey 任务列表显示，不参与后台匹配

跨域调用：

- 后端默认允许跨域预检请求，普通网页前端可以用 `fetch` 调用 Webhook
- 默认允许来源为 `*`，不允许携带浏览器 Cookie
- 如需收窄来源，设置环境变量 `CORS_ALLOW_ORIGINS=https://example.com,https://app.example.com`
- 如需跨域携带 Cookie，必须设置具体来源，并设置 `CORS_ALLOW_CREDENTIALS=1`；不要和通配来源 `*` 混用
- Webhook 如果暴露到公网，建议始终配置 `webhook_secret`

安全校验：

- 如果 `webhook_secret` 留空，Webhook 不做鉴权
- 如果已配置 `webhook_secret`，支持两种校验方式
- 方式一：请求头 `X-Webhook-Token: <secret>`
- 方式二：签名头 `X-Webhook-Ts`、`X-Webhook-Nonce`、`X-Webhook-Sign`
- 签名基串为 `{ts}.{nonce}.{body}`，算法为 `HMAC-SHA256`

## 企业微信通知推送

配置入口：`参数配置 -> 通知推送（企业微信）`

支持两种通道：

- 企业微信群机器人（Webhook）
- 企业微信应用 API（发给个人成员）

推送事件：

- 订阅任务成功入库（仅成功事件）
- 文件夹监控成功生成 `.strm`

推送去重策略：

- 订阅事件按 `任务名 + 集数 + 保存路径` 去重，避免同一更新重复提醒。
- 去重记录会保存在数据库中，并按过期时间自动清理。

建议配置流程：

1. 先选择通知通道并填写必填参数。
2. 点击「发送测试消息」确认链路可用。
3. 分别按需开启"订阅更新成功推送"和"文件夹监控生成成功推送"。
4. 失败/跳过场景可在 Web 日志中排查具体原因。

## 持久化目录说明

- `/app/strm`：生成的 `.strm` 文件
- `/app/config/settings.json`：系统配置文件
- `/app/config/data.db`：SQLite 数据库
- `/app/config/trees`：目录树缓存和中间文件
- `/app/logs/task.log`：目录树任务日志
- `/app/logs/monitor.log`：文件夹监控日志
- `/app/logs/subscription.log`：影视订阅日志

## 常用环境变量

大多数用户不需要改环境变量，先用页面里的「参数配置」即可。下面这些适合部署时按机器性能或网络情况调整：

- `TZ`：容器时区，建议 `Asia/Shanghai`
- `UVICORN_ACCESS_LOG`：是否启用 HTTP 访问日志，默认 `0`；排查接口访问时可设为 `1`
- `UI_PUSH_DEBOUNCE_SECONDS`：状态流推送合并等待秒数，默认 `0.35`；NAS 这类低功耗机器可适当调大
- `UI_STATUS_LOG_TAIL_LIMIT`：状态流里下发的日志尾部条数，默认 `160`；日志很多时可适当调小
- `UI_STATUS_LOG_MEMORY_LIMIT`：内存里保留的状态日志条数，默认 `220`；只想保留更少历史时可调小
- `STRM_PROXY_MODE`：STRM 播放模式默认值，默认 `redirect_direct`
- `API_115_RATE_LIMIT_SECONDS`：115 API 最小间隔，默认 `0.35`；账号风控明显时可调大
- `API_115_LIST_CACHE_TTL_SECONDS`：115 目录列表缓存秒数，默认 `60`
- `API_115_DOWNLOAD_URL_CACHE_TTL_SECONDS`：115 下载链接缓存秒数，默认 `20`
- `TG_CHANNEL_THREADS_DEFAULT`：TG 同步默认线程数，默认 `6`；代理不稳时建议调低
- `TG_CHANNEL_SYNC_LIMIT_DEFAULT`：TG 同步时每个频道默认抓取资源数，默认 `10`，页面配置可覆盖
- `PANSOU_SEARCH_TIMEOUT_SECONDS`：PanSou 搜索请求超时秒数，默认 `15`
- `PANSOU_SEARCH_TOTAL_LIMIT`：PanSou 搜索结果截断上限，默认 `80`
- `TMDB_API_BASE_URL` / `TMDB_IMAGE_BASE_URL`：需要自定义 TMDB 访问地址时再配置

## 浏览器辅助脚本

仓库根目录自带油猴脚本（安装后显示为 `115-media-hub助手`）：

- `115-magnet-helper-webhook.user.js`

它是浏览器侧工具，镜像会随服务端一起包含，并通过后台安装入口提供给 Tampermonkey。它的用途主要是：

- 在页面里识别 magnet / torrent / 115 / 夸克分享链接并生成快捷操作
- 按保存目录绑定不同的 Webhook 地址
- 在离线任务提交后顺手触发服务端刷新
- 复制 115 / Quark 分享链接时保留快捷操作，不强制提交到后台

服务端同时提供下载入口：

- `GET /userscript/magnet-helper.user.js`（推荐，直接触发 Tampermonkey 安装）
- `GET /download/userscript/magnet-helper.user.js`（兼容旧地址，会重定向到新地址）

### iOS / iPadOS 使用

iOS 无法安装 Tampermonkey 等浏览器扩展，建议使用 App Store 的 Userscripts（开源免费）：

1. 安装并启用 Userscripts 扩展（设置 > Safari > 扩展，勾选“允许访问所有网站”）；
2. 用 Safari 打开 `https://你的域名/userscript/magnet-helper.user.js`，点右上角 Userscripts 图标安装；
3. 点击任意磁力/torrent 链接旁的“115”按钮：未配置任务时直接打开任务管理器，已配置时弹出任务选择器（底部有“任务管理”入口）；配置保存在脚本全局存储中，跨网站生效。

脚本已兼容 Userscripts 的异步 `GM_getValue/GM_setValue`；没有 `GM_xmlhttpRequest` 时会自动改用 `fetch`（后台默认开放跨域）；http 页面没有 WebCrypto 时使用内置 SHA-256/HMAC 签名兜底。

## 版本与更新

- 当前版本信息见 `version.json`
- 历史变更见 `CHANGELOG.md`
- 仓库地址：<https://github.com/xianer235/115-media-hub>

## 免责声明

本项目仅用于个人技术研究与个人媒体库自动化管理，不提供任何破解、绕过授权或商业化分发能力，也不鼓励将其用于任何侵权或违规场景。使用本项目即表示你已知悉并同意以下事项：

- 请仅在你有合法访问权限的数据、账号和资源范围内使用本项目，并遵守你所在地区法律法规及相关平台条款。
- `115 Cookie`、Webhook 密钥等凭据由使用者自行妥善保管；因凭据泄露导致的账号风险、数据泄露或资产损失需自行承担。
- 项目依赖第三方平台与网络环境（如 115、TG、TMDB 等），相关接口策略、可用性和返回结果可能随时变化，本项目不承诺持续可用或结果绝对准确。
