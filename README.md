# 115 Media Hub

`115 Media Hub` 是一个基于 FastAPI 的媒体自动化管理面板，把 `115` / `Quark` 网盘转存、`.strm` 生成、TG 资源同步、影视订阅追更放进同一个后台。

它适合希望直接用网盘 Cookie 驱动“生成播放链接”“转存后自动刷新”“按片名自动找资源”一体化流程的场景。

## 近期更新（以 `version.json` 为准）

- 当前版本：`0.3.1`
- 资源中心新增 `频道搜索 / 盘搜` 双搜索模式，支持分类筛选、耗时状态和搜索中断。
- PanSou 支持账号密码登录获取 JWT，并接入资源中心搜索与订阅候选召回。
- TG 频道管理收拢为“频道管理中心”，支持排序应用、批量置顶/置底和同步频道官方名称。

## 核心功能

| 模块 | 作用 |
| --- | --- |
| 资源中心 | 同步 TG 公开频道、可选接入 PanSou 盘搜、手动预览/导入资源文本，支持 magnet、115 分享、Quark 分享入库并提交导入任务 |
| 影视订阅任务 | 电影/剧集自动匹配资源并入库，支持 115 / Quark 单网盘模式、周期时段调度、评分阈值、质量偏好、TMDB 绑定与追更状态 |
| 文件夹监控任务 | 扫描 115 网盘目录变化，支持手动、定时、Webhook 触发，并可按 savepath/sharetitle 局部刷新 |
| 目录树任务 | 基于 115 官方目录树 TXT 文件批量生成 `.strm`，支持多源路径、父目录前缀补全、排除层级与同步清理 |
| 企业微信通知推送 | 可对订阅成功和监控生成成功事件推送提醒，支持机器人和应用两种通道 |
| 115 每日签到 | 支持手动签到与每日定时签到，并在页面顶部展示签到状态 |
| Web 管理后台 | 集中管理配置、任务、日志、版本提示，支持桌面和移动端 |

适合这些场景：

- 大媒体库初始化：先用目录树任务一次性生成 `.strm`
- 连载或日更内容：用文件夹监控任务做增量刷新
- 转存成功后自动补扫：用 Webhook 触发指定监控任务
- 想减少手动找资源：用资源中心和影视订阅任务自动化处理

## 怎么选任务

| 需求 | 推荐方式 |
| --- | --- |
| 媒体库很大、更新不频繁 | `目录树任务` |
| 已有固定目录，想持续补新内容 | `文件夹监控任务` |
| 想按影片/剧集名称自动找资源 | `影视订阅任务` |
| 想把 115 转存、磁力离线、刷新串起来 | `资源中心 + Webhook + 文件夹监控任务` |
| 想导入 Quark 分享但不生成 115 strm 刷新 | `资源中心或影视订阅任务的 Quark 模式` |

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
6. 如果要使用 PanSou 盘搜，在「PanSou 盘搜」里填写服务地址；如 PanSou 开启认证，再填写账号/密码，按需填写 src / channels / plugins 并点击测试
7. 如果服务器访问 TG / TMDB 不稳定，再补充代理设置（同一套代理配置会同时用于 TG 与 TMDB）
8. 点击 Cookie 健康检测，确认 115 / Quark Cookie 可用
9. 如果要自动签到 115，再开启 `115 每日签到` 并设置签到时间
10. 如果要在任务成功后收到提醒，再配置「通知推送（企业微信）」并发送测试消息

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

1. 在「资源中心」配置 TG 频道源，也可以在参数配置里开启 PanSou 后切到「盘搜」搜索，或手动粘贴资源文本
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

## 版本与更新

- 当前版本信息见 `version.json`
- 历史变更见 `CHANGELOG.md`
- 仓库地址：<https://github.com/xianer235/115-media-hub>

## 免责声明

本项目仅用于个人技术研究与个人媒体库自动化管理，不提供任何破解、绕过授权或商业化分发能力，也不鼓励将其用于任何侵权或违规场景。使用本项目即表示你已知悉并同意以下事项：

- 请仅在你有合法访问权限的数据、账号和资源范围内使用本项目，并遵守你所在地区法律法规及相关平台条款。
- `115 Cookie`、Webhook 密钥等凭据由使用者自行妥善保管；因凭据泄露导致的账号风险、数据泄露或资产损失需自行承担。
- 项目依赖第三方平台与网络环境（如 115、TG、TMDB 等），相关接口策略、可用性和返回结果可能随时变化，本项目不承诺持续可用或结果绝对准确。
