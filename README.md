# 115 Media Hub

`115 Media Hub` 是一个基于 FastAPI 的媒体自动化管理面板，把 `115`、`AList/OpenList`、`.strm`、TG 资源同步、影视订阅追更放进同一个后台。

它适合已经把 115 挂载到 AList/OpenList、并希望进一步把“生成播放链接”“转存后自动刷新”“按片名自动找资源”串起来的使用场景。

## AI 协作入口

- 如果你是新会话 AI / 编码 Agent，优先阅读仓库根目录的 `AGENTS.md`
- 详细上下文入口位于 `doc/README.md`
- 若文档与代码冲突，以代码为准，并在结束前回写 `doc/`

## 近期更新（0.1.11）

- 修复日间模式下集数视图切换按钮的对比度问题，当前视图与未激活视图的层级更清晰。
- 修复日间模式下资源导入流程提示与频道管理删除按钮的可见性问题，关键危险操作与当前步骤更容易识别。
- 提升夜间模式下 `115` 每日签到时间选择器的边框与输入层次，时间框在深色背景中更明显。

## 这项目能做什么（按模块）

| 模块 | 作用 |
| --- | --- |
| 资源中心 | 同步 TG 公开频道、手动预览/导入资源文本，支持 magnet 与 115 分享链接入库并提交导入任务 |
| 影视订阅任务 | 电影/剧集自动匹配资源并入库，支持周期时段调度、评分阈值、质量偏好、TMDB 绑定与追更状态 |
| 文件夹监控任务 | 扫描 AList/OpenList 目录变化，支持手动、定时、Webhook 触发，并可按 savepath/sharetitle 局部刷新 |
| 目录树任务 | 基于 115 目录树批量生成 `.strm` 文件，支持多源 URL、前缀映射、排除层级、哈希跳过与同步清理 |
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
| 想把转存、离线、刷新串起来 | `资源中心 + Webhook + 文件夹监控任务` |

## 功能检查结果（与当前代码对齐）

### 资源中心

- 支持 TG 频道订阅、同步、分页加载与关键词搜索，频道支持批量启停和 JSON 导入导出。
- 支持资源文本“预览解析”和“正式入库”两步，识别 magnet、115 分享链接等常见格式。
- 导入任务支持 `magnet` 和 `115share` 两类链路，并内置同资源+路径去重，避免重复提交。
- 支持浏览 115 网盘目录、创建目录、预览分享链接目录树，并可选择分享子目录后再转存。
- 导入任务支持刷新、取消、重试、清理已完成/失败记录。

### 影视订阅任务

- 支持电影与剧集两类任务，支持多别名、年份、最小匹配分、质量偏好（清晰度优先策略）。
- 调度模型为“周几 + 时间窗口 + 窗口内间隔分钟”，可按任务独立启停。
- 支持 TMDB 搜索与绑定，自动带回别名、年份、总季/总集、分季集数映射。
- 支持固定分享链接导入与子目录 CID 锚定；支持集数视图与任务进度重建。

### 文件夹监控任务

- 支持手动运行、按分钟定时运行、Webhook 触发运行。
- Webhook 同时支持“普通目录刷新”与“磁力直导入”两种模式。
- 签名支持 `X-Webhook-Token` 或 `X-Webhook-Ts / X-Webhook-Nonce / X-Webhook-Sign`（HMAC-SHA256）。
- 支持任务取消、队列清理、日志清空，以及运行日志中的步骤化状态反馈。

### 目录树任务

- 支持联网同步、本地调试解析、强制全量重刷三种启动方式。
- 支持多源目录树 URL、父目录前缀映射、排除层级、增量/全量写入模式。
- 支持哈希跳过与同步清理（删除本地已失效 `.strm`）。

### 参数与系统能力

- 支持 TG/TMDB 代理配置和延迟测试。
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

1. 配置 `AList/OpenList 访问链接前缀`，例如 `http://192.168.1.5:5244`
2. 配置 `AList/OpenList Token`
3. 配置 `115 挂载根路径`，默认通常是 `/115`
4. 确认 `扫描后缀名` 是否符合你的媒体类型
5. 如果要用资源中心提交 115 离线任务，再配置 `115 Cookie`
6. 如果要提升影视订阅识别准确率，再启用 `TMDB API Key`
7. 如果服务器访问 TG / TMDB 不稳定，再补充代理设置（同一套代理配置会同时用于 TG 与 TMDB）
8. 如果要自动签到 115，再开启 `115 每日签到` 并设置签到时间
9. 如果要在任务成功后收到提醒，再配置「通知推送（企业微信）」并发送测试消息

## 推荐使用流程

### 方案一：先建库，再持续增量

1. 在「参数配置」中填好 AList/OpenList 和挂载路径
2. 在「目录树任务」里配置一个或多个目录树源
3. 先跑一次目录树任务，完成 `.strm` 初始化
4. 再为常更新目录添加「文件夹监控任务」，用于后续增量维护

### 方案二：转存完成后自动刷新

1. 创建一个开启了 Webhook 的文件夹监控任务
2. 让外部工具在转存完成后调用 `/webhook/{任务名}`
3. 服务端收到请求后，会优先按 `savepath` / `sharetitle` 做局部刷新

### 方案三：自动找资源并导入 115

1. 在「资源中心」配置 TG 频道源，或手动粘贴资源文本
2. 配置 `115 Cookie`
3. 在「影视订阅任务」中创建订阅项
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
- `delayTime`：本次延时秒数，会覆盖任务默认延时
- `title`：只用于日志展示
- `magnet` / `link_url` / `url`：可选，可直接触发资源导入流程

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
- `POST /settings/tg_proxy/test`：TG 代理延迟测试
- `POST /settings/notify/test`：企业微信通知测试
- `GET /settings/115/sign/status` / `POST /settings/115/sign/run`

目录树：

- `POST /start`：启动目录树任务
- `GET /logs`：目录树状态与日志

资源中心：

- `GET /resource/state`
- `POST /resource/channels/sync`
- `POST /resource/items/preview_text`
- `POST /resource/items/import_text`
- `POST /resource/jobs/create`
- `POST /resource/jobs/refresh|cancel|retry|clear|clear_completed`
- `GET /resource/115/folders`
- `GET /resource/115/share_entries`

订阅与监控：

- `GET /subscription/status`
- `POST /subscription/save|start|stop|rebuild|delete`
- `GET /monitor/status`
- `POST /monitor/save|start|stop|delete`
- `POST /webhook/{task_name}`

## 企业微信通知推送（0.1.6）

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
pip install fastapi uvicorn pydantic python-multipart starlette itsdangerous requests
uvicorn main:app --host 0.0.0.0 --port 18080 --reload
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
- `VERSION_CACHE_TTL`：版本检查缓存秒数，默认 `21600`

订阅去重与重试：

- `SUBSCRIPTION_INVALID_LINK_CACHE_TTL_SECONDS`：订阅无效链接缓存时长，默认 `604800`
- `SUBSCRIPTION_DUPLICATE_VERIFY_RETRIES`：115 重复状态复核重试次数，默认 `2`
- `SUBSCRIPTION_DUPLICATE_VERIFY_DELAY_SECONDS`：重复复核重试间隔秒，默认 `3`

TG 访问相关：

- `TG_CHANNEL_THREADS_DEFAULT`：TG 同步默认线程数，默认 `6`
- `TG_SEARCH_PAGE_LIMIT`：单频道搜索分页大小，默认 `20`
- `TG_SEARCH_MAX_PAGES`：单频道搜索最大页数，默认 `6`
- `TG_SEARCH_TOTAL_LIMIT`：全局搜索返回上限，默认 `60`
- `TG_FETCH_RETRY_ATTEMPTS`：抓取重试次数，默认 `3`
- `TG_FETCH_RETRY_DELAY_SECONDS`：抓取重试退避系数，默认 `0.8`

TMDB 相关：

- `TMDB_REQUEST_TIMEOUT_SECONDS`：TMDB 请求超时，默认 `20`
- `TMDB_SEARCH_LIMIT`：TMDB 搜索结果截断上限，默认 `12`
- `TMDB_API_BASE_URL`：TMDB API 基础地址
- `TMDB_IMAGE_BASE_URL`：TMDB 图片基础地址

通知推送相关：

- `NOTIFY_DEDUPE_TTL_DAYS`：通知去重记录保留天数，默认 `180`，最小 `7`

频道缓存治理：

- `RESOURCE_CHANNEL_TYPE_SAMPLE_SIZE`：频道类型识别采样条数
- `RESOURCE_CHANNEL_TYPE_PAGE_LIMIT`：频道类型识别单页抓取条数
- `RESOURCE_CHANNEL_TYPE_MAX_PAGES`：频道类型识别最大抓取页数
- `RESOURCE_CHANNEL_CACHE_LIMIT`：单频道缓存保留上限
- `RESOURCE_CHANNEL_INACTIVE_CACHE_LIMIT`：未启用频道保留条数
- `RESOURCE_CHANNEL_CACHE_TTL_DAYS`：频道缓存按天过期
- `RESOURCE_CHANNEL_CACHE_GLOBAL_LIMIT`：全局频道缓存硬上限
- `RESOURCE_CHANNEL_CACHE_ACTIVE_MIN_KEEP`：活跃频道最小保留条数

分享目录预览缓存：

- `SHARE_SNAP_RATE_LIMIT_SECONDS`
- `SHARE_SNAP_CACHE_TTL_SECONDS`
- `SHARE_SNAP_CACHE_MAX_ROWS`

## 浏览器辅助脚本

仓库根目录自带油猴脚本：

- `115-magnet-helper-webhook.user.js`

它是浏览器侧工具，不会打包进容器镜像。它的用途主要是：

- 在页面里识别磁力链接并辅助提交到 115
- 按保存目录绑定不同的 Webhook 地址
- 在离线任务提交后顺手触发服务端刷新

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
- `115 Cookie`、`AList/OpenList Token`、Webhook 密钥等凭据由使用者自行妥善保管；因凭据泄露导致的账号风险、数据泄露或资产损失需自行承担。
- 项目依赖第三方平台与网络环境（如 115、TG、TMDB、AList/OpenList 等），相关接口策略、可用性和返回结果可能随时变化，本项目不承诺持续可用或结果绝对准确。
