# 115 Media Hub

`115 Media Hub` 是一个基于 FastAPI 的媒体自动化管理面板，把 `115` / `Quark` 网盘转存、`.strm` 生成、TG 资源同步、影视订阅追更放进同一个后台。

它适合希望直接用网盘 Cookie 驱动“生成播放链接”“转存后自动刷新”“按片名自动找资源”一体化流程的场景。

## AI 协作入口

- 如果你是新会话 AI / 编码 Agent，优先阅读仓库根目录的 `AGENTS.md`

## 近期更新（以 `version.json` 为准）

- 当前版本：`0.2.16`
- 频道订阅导入兼容 CloudSaver JSON 与盘搜 `export CHANNELS=...`，导出统一为 CloudSaver JSON 并先弹窗预览。
- 文件夹监控新建任务的目录列出后延时默认调整为 `250ms`。
- 补充油猴脚本与文件夹监控任务的参数关系说明，并优化日夜间模式下的可读性。

## 这项目能做什么（按模块）

| 模块 | 作用 |
| --- | --- |
| 资源中心 | 同步 TG 公开频道、手动预览/导入资源文本，支持 magnet、115 分享、Quark 分享入库并提交导入任务 |
| 影视订阅任务 | 电影/剧集自动匹配资源并入库，支持 115 / Quark 单网盘模式、周期时段调度、评分阈值、质量偏好、TMDB 绑定与追更状态 |
| 文件夹监控任务 | 扫描 115 网盘目录变化，支持手动、定时、Webhook 触发，并可按 savepath/sharetitle 局部刷新 |
| 目录树任务 | 基于 115 官方目录树 TXT 文件批量生成 `.strm`，支持多源路径、父目录前缀补全、排除层级与同步清理 |
| 企业微信通知推送 | 可对订阅成功和监控生成成功事件推送提醒，支持机器人和应用两种通道 |
| 115 每日签到 | 支持手动签到与每日定时签到，并在页面顶部展示签到状态 |
| 实时状态总线 | 前端通过 SSE (`/events`) 实时接收任务进度、日志和运行状态更新 |
| Web 管理后台 | 集中管理配置、任务、日志、版本提示，支持桌面和移动端 |

## 适合这些场景

- 大媒体库初始化：先用目录树任务一次性生成 `.strm`
- 连载或日更内容：用文件夹监控任务做增量刷新
- 转存成功后自动补扫：用 Webhook 触发指定监控任务
- 想减少手动找资源：用资源中心和影视订阅任务自动化处理

## 怎么选任务模式

| 需求 | 推荐方式 |
| --- | --- |
| 媒体库很大、更新不频繁 | `目录树任务` |
| 已有固定目录，想持续补新内容 | `文件夹监控任务` |
| 想按影片/剧集名称自动找资源 | `影视订阅任务` |
| 想把 115 转存、磁力离线、刷新串起来 | `资源中心 + Webhook + 文件夹监控任务` |
| 想导入 Quark 分享但不生成 115 strm 刷新 | `资源中心或影视订阅任务的 Quark 模式` |

## 功能检查结果（与当前代码对齐）

### 资源中心

- 支持 TG 频道订阅、同步、分页加载与关键词搜索，频道支持批量启停；导入兼容 CloudSaver JSON 与盘搜 `CHANNELS`，导出使用 CloudSaver JSON。
- 支持频道快捷管理、批量筛选/启停/删除、频道分类测试、频道同步后台执行。
- 频道模板导入会自动识别 CloudSaver JSON 与盘搜 `export CHANNELS=...`；导出时会先弹窗展示 CloudSaver JSON，可手动复制或点击按钮下载 JSON。
- 支持资源文本“预览解析”和“正式入库”两步，识别 magnet、115 分享、Quark 分享等常见格式。
- 导入任务支持 `magnet`、`115share`、`quark` 三类链路，并内置同资源+路径去重；115 / Quark 分享链接重复时可确认继续创建，适配同一分享分批转存。
- 支持浏览 115 / Quark 网盘目录、创建目录、预览分享链接目录树，并可选择分享子目录或文件后再转存。
- 支持资源快捷链接、分享目录搜索、分享目录选择计数、分享解析阶段耗时展示。
- 导入任务支持刷新、取消、重试、清理已完成/失败记录。

### 影视订阅任务

- 支持电影与剧集两类任务，支持 115 / Quark provider、多别名、排除词、年份、最小匹配分、质量偏好（清晰度优先策略）。
- 调度模型为“周几 + 时间窗口 + 窗口内间隔分钟”，可按任务独立启停。
- 支持 TMDB 搜索与绑定，自动带回别名、年份、总季/总集、分季集数映射。
- 115 模式支持固定分享链接导入、访问码、子目录路径和 CID 锚定；也可开启固定链接后补搜频道。
- Quark 模式使用独立评分与导入链路，支持指定 Quark 链接手动扫描；Quark 导入不联动文件夹监控刷新。
- 支持集数视图、任务进度重建、候选分享内容文件级筛选，减少整包误导入。

### 文件夹监控任务

- 支持手动运行、按分钟定时运行、Webhook 触发运行。
- Webhook 同时支持“普通目录刷新”与“磁力直导入”两种模式。
- 签名支持 `X-Webhook-Token` 或 `X-Webhook-Ts / X-Webhook-Nonce / X-Webhook-Sign`（HMAC-SHA256）。
- 新建监控任务的内置默认值：读取失败尝试次数 `3`，目录列出后延时 `250ms`，任务执行延时 `0s`。
- 支持任务取消、队列清理、日志清空，以及运行日志中的步骤化状态反馈。

### 目录树任务

- 只处理 115 官方目录树 TXT 文件，不承担目录递归扫描（目录扫描由“文件夹监控任务”负责）。
- 支持多源目录树文件路径、父目录前缀补全、排除层级、增量/全量写入模式。
- 支持 MD5 校验缓存：目录树内容无变化时复用缓存并跳过同步。
- 支持同步清理（删除本地已失效 `.strm`）。

### 参数与系统能力

- 支持 TG/TMDB 代理配置和延迟测试。
- 支持 115 / Quark Cookie 健康检测；分享失效、提取码错误等内容侧异常不会误判 Cookie 失效。
- 支持 115 每日签到（手动+定时）。
- 支持企业微信通知测试与运行时推送（订阅成功、监控成功）。
- 支持版本检查、关于页更新提示、SSE 实时状态推送。

## 快速开始

以下示例假设你发布的镜像名为 `xianer235/115-media-hub:latest`：

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

## 首次配置顺序

建议第一次按下面顺序配置，这样最省回头路：

1. 配置 `115 Cookie`（按需再填 `Quark Cookie`）
2. 配置 `STRM 对外访问地址`（例如 `http://192.168.1.20:18080`）
3. 根据账号风控策略调整 `115 API 最小间隔`、`目录缓存 TTL`、`下载链接缓存 TTL`
4. 确认 `扫描后缀名` 是否符合你的媒体类型
5. 如果要提升影视订阅识别准确率，再启用 `TMDB API Key`
6. 如果服务器访问 TG / TMDB 不稳定，再补充代理设置（同一套代理配置会同时用于 TG 与 TMDB）
7. 点击 Cookie 健康检测，确认 115 / Quark Cookie 可用
8. 如果要自动签到 115，再开启 `115 每日签到` 并设置签到时间
9. 如果要在任务成功后收到提醒，再配置「通知推送（企业微信）」并发送测试消息

## 推荐使用流程

### 方案一：先建库，再持续增量

1. 在「参数配置」中填好 115 Cookie 与 STRM 对外访问地址（网盘前缀映射已内置：`115 -> /115`、`Quark -> /quark`）
2. 在「目录树任务」里配置一个或多个目录树源
3. 先跑一次目录树任务，完成 `.strm` 初始化
4. 再为常更新目录添加「文件夹监控任务」，用于后续增量维护

### 方案二：转存完成后自动刷新

1. 创建一个开启了 Webhook 的文件夹监控任务
2. 让外部工具在转存完成后调用 `/webhook/{任务名}`
3. 服务端收到请求后，会优先按 `savepath` / `sharetitle` 做局部刷新

### 方案三：自动找资源并导入网盘

1. 在「资源中心」配置 TG 频道源，或手动粘贴资源文本
2. 按目标网盘配置 `115 Cookie` 或 `Quark Cookie`
3. 在「影视订阅任务」中创建订阅项，并选择 provider
4. 系统按周期匹配候选资源，并创建导入任务

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

- 脚本“请求地址”必须指向已开启 Webhook 的监控任务：`http://IP:端口/webhook/{任务名}`，后台用 `{任务名}` 找到要触发的文件夹监控任务
- 脚本“保存路径 savepath”是磁力离线下载到 115 的目标目录；它会拼到 115 挂载前缀后和监控任务“扫描路径”匹配
- 只有 `savepath` 落在该监控任务的扫描路径内，导入成功后才会自动触发刷新并生成 `.strm`
- 脚本“延迟”是导入成功后等待几秒再刷新；填 0 或不填时使用监控任务默认延迟
- 脚本“名称”只用于 Tampermonkey 任务列表显示，不参与后台匹配

安全校验：

- 如果 `webhook_secret` 留空，Webhook 不做鉴权
- 如果已配置 `webhook_secret`，支持两种校验方式
- 方式一：请求头 `X-Webhook-Token: <secret>`
- 方式二：签名头 `X-Webhook-Ts`、`X-Webhook-Nonce`、`X-Webhook-Sign`
- 签名基串为 `{ts}.{nonce}.{body}`，算法为 `HMAC-SHA256`

## 接口速查（常用）

页面与会话：

- `GET /login`：登录页
- `POST /login`：登录
- `GET /logout`：退出
- `GET /events`：SSE 状态流

配置与系统：

- `GET /get_settings` / `POST /save_settings`
- `GET /version`：版本检查状态
- `GET /strm/proxy?path=/...`：STRM 播放入口（默认 `302` 直跳 115 上游地址，支持附带 `pickcode` 跳过路径反查；`mode=relay` 时改为 `307` 跳转到容器内 relay，`mode=proxy` 时走服务端中继流）
- `GET /strm/relay?token=...`：STRM 中继拉流入口（内部临时令牌接口，给 `mode=relay` 使用）
- `GET /settings/cookies/status` / `POST /settings/cookies/check`：Cookie 健康状态与手动检测
- `POST /settings/tg_proxy/test`：TG 代理延迟测试
- `POST /settings/notify/test`：企业微信通知测试
- `GET /settings/115/sign/status` / `POST /settings/115/sign/run`

目录树：

- `POST /start`：启动目录树任务
- `GET /logs`：目录树状态与日志

资源中心：

- `GET /resource/state`
- `GET /resource/jobs/state`
- `POST /resource/sources/save`
- `POST /resource/quick_links/save`
- `POST /resource/channels/sync`
- `POST /resource/channels/classify`
- `POST /resource/channels/more`
- `POST /resource/items/preview_text`
- `POST /resource/items/import_text`
- `POST /resource/items/delete`
- `POST /resource/jobs/create`
- `POST /resource/jobs/refresh|cancel|retry|clear|clear_completed`
- `GET /resource/115/folders`
- `POST /resource/115/folders/create`
- `GET /resource/115/share_entries`
- `POST /resource/115/share_entries_preview`
- `GET /resource/quark/folders`
- `POST /resource/quark/folders/create`
- `GET /resource/quark/share_entries`
- `POST /resource/quark/share_entries_preview`
- `GET /resource/quark/probe`
- `GET /resource/image`

订阅与监控：

- `GET /subscription/status`
- `POST /subscription/save|start|stop|rebuild|delete`
- `GET /monitor/status`
- `POST /monitor/save|start|stop|delete`
- `POST /webhook/{task_name}`

订阅任务字段说明（新增）：

- `provider=115|quark`（单网盘模式，不混排候选）
- `provider=115`：候选仅 `magnet/115share`
- `provider=quark`：候选仅 `quark`，使用独立评分与导入链路（不联动监控刷新）

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
3. 分别按需开启“订阅更新成功推送”和“文件夹监控生成成功推送”。
4. 失败/跳过场景可在 Web 日志中排查具体原因。

## 本地开发运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 18080 --reload
```

## 持久化目录说明

- `/app/strm`：生成的 `.strm` 文件
- `/app/config/settings.json`：系统配置文件
- `/app/config/data.db`：SQLite 数据库
- `/app/config/trees`：目录树缓存和中间文件
- `/app/logs/task.log`：目录树任务日志
- `/app/logs/monitor.log`：文件夹监控日志
- `/app/logs/subscription.log`：影视订阅日志

## 常用环境变量

基础超时与调度：

- `SUBSCRIPTION_ATTEMPT_INTERVAL_SECONDS`：订阅候选尝试间隔，默认 `2`
- `SUBSCRIPTION_IMPORT_TIMEOUT_SECONDS`：订阅导入超时秒数，默认 `90`
- `RESOURCE_IMPORT_TIMEOUT_SECONDS`：资源导入超时秒数，默认 `90`
- `RESOURCE_JOB_STALE_RECOVER_SECONDS`：导入任务卡死恢复阈值，默认 `300`
- `RESOURCE_JOB_COMPLETED_KEEP` / `RESOURCE_JOB_FAILED_KEEP`：导入任务完成/失败记录保留数量，默认 `1000` / `500`
- `VERSION_CACHE_TTL`：版本检查缓存秒数，默认 `21600`

订阅去重与重试：

- `SUBSCRIPTION_INVALID_LINK_CACHE_TTL_SECONDS`：订阅无效链接缓存时长，默认 `604800`
- `SUBSCRIPTION_DUPLICATE_VERIFY_RETRIES`：115 重复状态复核重试次数，默认 `2`
- `SUBSCRIPTION_DUPLICATE_VERIFY_DELAY_SECONDS`：重复复核重试间隔秒，默认 `3`
- `SUBSCRIPTION_SHARE_SCAN_CONCURRENCY`：订阅分享内容扫描并发，默认 `3`
- `SUBSCRIPTION_SHARE_SCAN_REQUEST_TIMEOUT_SECONDS`：订阅分享扫描单请求超时，默认 `12`
- `SUBSCRIPTION_SHARE_SCAN_RATE_LIMIT_SECONDS`：订阅分享扫描限速间隔，默认 `0.25`
- `SUBSCRIPTION_QUARK_MIN_SCORE`：Quark 订阅默认最低分，默认 `60`
- `SUBSCRIPTION_QUARK_MAX_ATTEMPTS`：Quark 订阅候选尝试上限，默认 `60`

TG 访问相关：

- `TG_CHANNEL_THREADS_DEFAULT`：TG 同步默认线程数，默认 `6`
- `TG_SEARCH_PAGE_LIMIT`：单频道搜索分页大小，默认 `20`
- `TG_SEARCH_MAX_PAGES`：单频道搜索最大页数，默认 `6`
- `TG_SEARCH_MATCH_LIMIT_PER_CHANNEL`：单频道匹配结果上限，默认 `12`
- `TG_SEARCH_TOTAL_LIMIT`：全局搜索返回上限，默认 `60`
- `TG_SEARCH_CHANNEL_TIMEOUT_SECONDS`：单频道搜索整体超时，默认 `10`
- `TG_SEARCH_REQUEST_TIMEOUT_SECONDS`：单次 TG 请求超时，默认 `8`
- `TG_SEARCH_RETRY_ATTEMPTS`：TG 搜索请求重试次数，默认 `1`
- `TG_FETCH_RETRY_ATTEMPTS`：抓取重试次数，默认 `3`
- `TG_FETCH_RETRY_DELAY_SECONDS`：抓取重试退避系数，默认 `0.8`

115 / Quark / STRM 访问相关：

- `API_115_RATE_LIMIT_SECONDS`：115 API 最小间隔，默认 `0.35`
- `API_115_LIST_CACHE_TTL_SECONDS`：115 目录列表缓存秒数，默认 `60`
- `API_115_DOWNLOAD_URL_CACHE_TTL_SECONDS`：115 下载链接缓存秒数，默认 `20`
- `API_115_PICKCODE_CACHE_TTL_SECONDS`：STRM 路径反查 pickcode 缓存秒数，默认 `7200`
- `API_115_FOLDER_CID_CACHE_TTL_SECONDS`：115 文件夹 CID 缓存秒数，默认 `7200`
- `STRM_PROXY_MODE`：STRM 播放模式默认值，默认 `redirect_direct`
- `STRM_RELAY_CHUNK_SIZE`：STRM relay 分块大小，默认 `262144`
- `QUARK_SHARE_FAST_DEADLINE_SECONDS`：Quark 分享首屏 fast path 总 deadline，默认 `3`
- `RESOURCE_SHARE_BROWSE_RATE_LIMIT_SECONDS`：分享目录浏览限速，默认 `0.05`
- `RESOURCE_BROWSE_WORKERS` / `RESOURCE_115_SHARE_WORKERS` / `RESOURCE_QUARK_SHARE_WORKERS`：资源浏览线程数，默认 `4` / `3` / `4`

Cookie 健康检测：

- `COOKIE_HEALTH_MIN_REFRESH_INTERVAL_SECONDS`：Cookie 健康检测最小刷新间隔，默认 `20`
- `COOKIE_HEALTH_SUCCESS_UPDATE_INTERVAL_SECONDS`：Cookie 成功状态刷新间隔，默认 `90`

TMDB 相关：

- `TMDB_REQUEST_TIMEOUT_SECONDS`：TMDB 请求超时，默认 `20`
- `TMDB_SEARCH_LIMIT`：TMDB 搜索结果截断上限，默认 `12`
- `TMDB_API_BASE_URL`：TMDB API 基础地址
- `TMDB_IMAGE_BASE_URL`：TMDB 图片基础地址

通知推送相关：

- `NOTIFY_DEDUPE_TTL_DAYS`：通知去重记录保留天数，默认 `180`，最小 `7`

日志与可观测性：

- `UVICORN_ACCESS_LOG`：是否启用 HTTP 访问日志，默认 `0`（关闭，减少轮询刷屏；设为 `1` 可开启）
- `HTTP_TIMING_HEADER_ENABLED`：是否输出后端耗时响应头，默认 `0`
- `LOG_ROTATE_MAX_BYTES` / `LOG_ROTATE_BACKUPS`：日志滚动大小和备份数，默认 `5MB` / `2`
- `TEMPLATE_CACHE_SECONDS` / `ASSET_VERSION_CACHE_SECONDS`：模板与静态资源版本缓存秒数，默认 `30` / `30`

频道缓存治理：

- `RESOURCE_CHANNEL_TYPE_SAMPLE_SIZE`：频道类型识别采样条数，默认 `10`
- `RESOURCE_CHANNEL_TYPE_PAGE_LIMIT`：频道类型识别单页抓取条数
- `RESOURCE_CHANNEL_TYPE_MAX_PAGES`：频道类型识别最大抓取页数
- `RESOURCE_CHANNEL_CACHE_LIMIT`：单频道缓存保留上限，默认 `10`
- `RESOURCE_CHANNEL_INACTIVE_CACHE_LIMIT`：未启用频道保留条数
- `RESOURCE_CHANNEL_CACHE_TTL_DAYS`：频道缓存按天过期
- `RESOURCE_CHANNEL_CACHE_GLOBAL_LIMIT`：全局频道缓存硬上限
- `RESOURCE_CHANNEL_CACHE_ACTIVE_MIN_KEEP`：活跃频道最小保留条数

分享目录预览缓存：

- `SHARE_SNAP_RATE_LIMIT_SECONDS`：分享快照接口限速，默认 `0.2`
- `SHARE_SNAP_CACHE_TTL_SECONDS`：分享快照缓存秒数，默认 `300`
- `SHARE_SNAP_CACHE_MAX_ROWS`：分享快照缓存最大行数，默认 `3000`

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

## 版本与更新

- 当前版本信息见 `version.json`
- 历史变更见 `CHANGELOG.md`
- 仓库地址：<https://github.com/xianer235/115-media-hub>

## 免责声明

本项目仅用于个人技术研究与个人媒体库自动化管理，不提供任何破解、绕过授权或商业化分发能力，也不鼓励将其用于任何侵权或违规场景。使用本项目即表示你已知悉并同意以下事项：

- 请仅在你有合法访问权限的数据、账号和资源范围内使用本项目，并遵守你所在地区法律法规及相关平台条款。
- `115 Cookie`、Webhook 密钥等凭据由使用者自行妥善保管；因凭据泄露导致的账号风险、数据泄露或资产损失需自行承担。
- 项目依赖第三方平台与网络环境（如 115、TG、TMDB 等），相关接口策略、可用性和返回结果可能随时变化，本项目不承诺持续可用或结果绝对准确。
