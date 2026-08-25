# 115 Media Hub

`115 Media Hub` 是一个基于 FastAPI 的媒体自动化管理面板，把多网盘转存、115 网盘 `.strm` 生成、TG 资源同步、影视订阅追更、刮削管理放进同一个后台，并提供宿主机命令行客户端（`cli.py`），让 AI 代理或脚本无需打开网页即可完成同样的管理操作。

它适合希望直接用网盘 Cookie 驱动"生成播放链接""转存后自动刷新""按片名自动找资源""批量重命名刮削"一体化流程的场景。

## 功能总览

| 模块 | 作用 |
| --- | --- |
| 资源中心 | 同步 TG 公开频道、接入 PanSou 盘搜、手动预览/导入资源文本，支持 magnet、ED2K、直链与 115/Quark/天翼/123/阿里分享入库并提交导入任务 |
| 资源推荐 | Explore 筛选与资源发现，多维度筛选与快速导入 |
| 影视订阅任务 | 电影/剧集自动匹配资源并入库，支持多网盘 provider、周期时段调度、评分阈值、质量偏好、TMDB 绑定与追更状态 |
| 文件夹监控任务 | 扫描网盘目录变化，支持手动、定时、Webhook 触发，并可按 savepath/sharetitle 局部刷新；智能补扫失败子目录 |
| 目录树任务 | 选择 115 文件夹后调用官方“导出目录树”接口生成树文件，自动替换旧树并对比 sha1 增量更新 `.strm`，支持全量重写 |
| 刮削管理 | 网盘文件浏览、TMDB 识别绑定、批量重命名预览与执行，支持任务中心统一管理 |
| 命令行管理（CLI） | 宿主机命令行客户端，通过面板 HTTP API 完成搜索/订阅/转存/监控/刮削/STRM/运维，适合 AI 代理与脚本自动化 |
| 企业微信通知推送 | 可对订阅成功和监控生成成功事件推送提醒，支持机器人和应用两种通道 |
| 115 每日签到 | 支持手动签到与每日定时签到，并在页面顶部展示签到状态 |
| Web 管理后台 | 集中管理配置、任务、日志、版本提示，支持桌面和移动端 |

### 支持的网盘与资源来源

- 网盘：`115` / `Quark（夸克）` / `天翼云盘` / `123云盘` / `阿里云盘`，统一通过 Cookie 驱动；115 支持分享转存、磁力离线与 `.strm` 生成，其余网盘以分享/链接入库为主
- 资源来源：TG 公开频道同步、PanSou 盘搜、手动粘贴资源文本，支持 magnet、ED2K、直链与各网盘分享链接
- 元数据：TMDB 识别绑定（可配 API Key，支持自定义 API 与图片地址）
- 展示型链接：光鸭网盘分享链接仅在页面中识别并打标签，不提供转存/下载能力

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

镜像名为 `xianer235/115-media-hub:latest`：

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

默认账号密码（Web 面板）：

- 用户名：`admin`
- 密码：`admin123`

首次登录后，建议立刻到「参数配置」页修改后台账号密码，并配置 `webhook_secret`。命令行 CLI 不会使用默认口令自动登录，需显式提供凭据（见「命令行工具」）。

### 持久化目录

| 路径 | 说明 |
| --- | --- |
| `/app/strm` | 生成的 `.strm` 文件 |
| `/app/config/settings.json` | 系统配置文件 |
| `/app/config/data.db` | SQLite 数据库 |
| `/app/config/trees` | 目录树缓存和中间文件 |
| `/app/logs/task.log` | 目录树任务日志 |
| `/app/logs/monitor.log` | 文件夹监控日志 |
| `/app/logs/subscription.log` | 影视订阅日志 |

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
2. 在「目录树任务」里点击「+ 新增目录树任务」，选择 115 文件夹后保存（树文件名可编辑；父文件夹路径前缀与排除层级由所选文件夹自动推导、只读）
3. 点击任务卡片的“生成并同步”，官方服务器生成目录树（网盘根目录，`目录树-路径段…`），sha1 未变化时跳过下载/解析，变化时自动更新 `.strm`；需要重建树用“全量重写”，顶部“下载并生成”直接下载已存在的树文件并生成（导出超时后手动改名收尾），“同步策略”里可关闭 sha1 跳过或开启清理任务范围内的残留 STRM
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
`subscribe list|add|remove|start` / `jobs list|retry|cancel` / `scrape jobs-create|batch-preferences` /
`monitor list|start|stop` / `tree list|create|update|delete|defaults|run|full|jobs` /
`offline list [--page N]` / `sources search` / `daemon status|logs|restart`。

- 完整命令列表见 `CLI-API-AUDIT.md`；每个子命令都支持 `--help` 查看参数
- 会话 Cookie 默认保存到 `/tmp/.115_cookies.txt`（权限 0600），可用 `MH_COOKIE_FILE` 覆盖
- `sources` / `daemon` 等容器运维命令需要宿主机安装 Docker，容器名自动识别 `115-media-hub` / `115-media-hub-test`，也可用环境变量 `MH_CONTAINER` 覆盖

批量整理与监控任务相关命令（0.7.1 起）：

```bash
# 读取 / 设置 / 清除某网盘的批量整理偏好（文件命名方式、文件夹开关、删除广告等）
.cli-venv/bin/python cli.py scrape batch-preferences get --provider 115
.cli-venv/bin/python cli.py scrape batch-preferences set --provider 115 --options-json '{"file_name_mode":"keep"}'
.cli-venv/bin/python cli.py scrape batch-preferences clear --provider 115

# 生成重命名预览时传入命名选项（keep 保持原名 / clean 仅清理广告 / standard 标准重命名）
.cli-venv/bin/python cli.py scrape rename-plan "/影视/剧集" --file-name-mode clean --no-season-subfolder --delete-ad-files

# 创建监控任务时启用新增资源自动刮削整理并配置该任务的整理选项
.cli-venv/bin/python cli.py monitor add 自存影视 --scan-path /115/自存影视 --auto-scrape-on-new --auto-scrape-options-json '{"file_name_mode":"keep","delete_ad_files":true}'
```

`scrape rename-plan` 支持 `--file-name-mode keep|clean|standard`、`--no-rename-folders`、`--no-season-subfolder`、`--include-tmdb-id`、`--delete-ad-files`、`--title-language auto|zh|en`、`--season`、`--episode-mode auto|seasonal|absolute`、`--preserve-file-info`，或直接用 `--options-json` 传完整选项对象；`monitor add` 还支持 `--auto-scrape-options-json` 传该任务的自动整理选项（未配置时保持默认行为）。

目录树任务相关命令（0.8.0 起）：

```bash
# 查看自动填充参数 / 创建任务（--folder 指定 115 文件夹路径，--name 可选）
.cli-venv/bin/python cli.py tree defaults --folder "影视库/电视剧"
.cli-venv/bin/python cli.py tree create --folder "影视库/电视剧" --name "目录树-电视剧"

# 列表 / 增量同步（run 不带 --id 时对所有任务仅做 sha1 对比更新）/ 全量重写
.cli-venv/bin/python cli.py tree list
.cli-venv/bin/python cli.py tree run --id <任务ID>
.cli-venv/bin/python cli.py tree full --id <任务ID>
```

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
- 脚本"延迟"是导入成功后等待几秒再刷新；填 0 或不填时使用监控任务默认延时
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

## 浏览器辅助脚本（油猴）

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

## 常用环境变量

大多数用户不需要改环境变量，先用页面里的「参数配置」即可。下面这些适合部署时按机器性能或网络情况调整：

- `TZ`：容器时区，建议 `Asia/Shanghai`
- `UVICORN_ACCESS_LOG`：是否启用 HTTP 访问日志，默认 `0`；排查接口访问时可设为 `1`
- `UI_PUSH_DEBOUNCE_SECONDS`：状态流推送合并等待秒数，默认 `0.35`；NAS 这类低功耗机器可适当调大
- `UI_STATUS_LOG_TAIL_LIMIT`：状态流里下发的日志尾部条数，默认 `160`；日志很多时可适当调小
- `UI_STATUS_STREAM_LOG_TAIL_LIMIT`：轮询/推送流单次下发的日志条数，默认 `40`
- `UI_STATUS_LOG_MEMORY_LIMIT`：内存里保留的状态日志条数，默认 `220`；只想保留更少历史时可调小
- `STRM_PROXY_MODE`：STRM 播放模式默认值，默认 `redirect_direct`
- `API_115_RATE_LIMIT_SECONDS`：115 API 最小间隔，默认 `0.35`；账号风控明显时可调大
- `API_115_LIST_CACHE_TTL_SECONDS`：115 目录列表缓存秒数，默认 `60`
- `API_115_LIST_CACHE_MAX_ROWS`：115 目录列表缓存最大行数，默认 `2000`
- `API_115_DOWNLOAD_URL_CACHE_TTL_SECONDS`：115 下载链接缓存秒数，默认 `20`
- `API_115_DOWNLOAD_URL_CACHE_MAX_ENTRIES`：115 下载链接缓存最大条数，默认 `1000`
- `TG_CHANNEL_THREADS_DEFAULT`：TG 同步默认线程数，默认 `6`；代理不稳时建议调低
- `TG_CHANNEL_SYNC_LIMIT_DEFAULT`：TG 同步时每个频道默认抓取资源数，默认 `10`，页面配置可覆盖
- `PANSOU_SEARCH_TIMEOUT_SECONDS`：PanSou 搜索请求超时秒数，默认 `15`
- `PANSOU_SEARCH_TOTAL_LIMIT`：PanSou 搜索结果截断上限，默认 `80`
- `TMDB_API_BASE_URL` / `TMDB_IMAGE_BASE_URL`：需要自定义 TMDB 访问地址时再配置
- `RESOURCE_JOB_COMPLETED_KEEP` / `RESOURCE_JOB_FAILED_KEEP`：任务中心完成/失败记录保留上限，默认 `1000` / `500`
- `RESOURCE_JOB_PRUNE_INTERVAL_SECONDS`：任务历史后台清理间隔秒数，默认 `600`（范围 60–86400）

CLI 专属环境变量（见「命令行工具」）：`MH_USERNAME` / `MH_PASSWORD` / `MH_API_BASE` / `MH_COOKIE_FILE` / `MH_CONTAINER`。

## 近期更新（以 `version.json` 为准）

- 当前版本：`0.10.0`
- 订阅扫描链接支持一次性磁力/电驴离线入库：115 离线到 `云下载/磁力中转/<任务名>/` → 挑选命中文件移动到订阅 savepath → 精准刷新 STRM/自动刮削；垃圾文件即时清理、未命中保留 7 天、中转目录每 30 分钟定期清理；CLI `subscribe start-with-link` 同步支持。
- 手动磁力/电驴导入完成后按实际下载文件夹精确定位刷新，savepath 等于监控根目录时不再退化成全任务扫描。
- 变更同步体验：未知清单文件夹自动补扫（无需手动触发）、刮削任务自身动作不再重复自动刮削、汇总按净效果统计、空事件早退、汇总精简为事件分组。
- 文件夹监控日志可读性：任务开始即显示扫描范围、结束前输出结论行；汇总指标四色显示且 0 值低饱和。
- 批量整理修复：Season 目录内文件不再嵌套、选中季目录不再被重命名成片名、选项变更后执行前自动重建预览。
- 顶部“任务”按钮数字气泡竖屏不再被裁切。
- 目录树导出超时处理：「生成并同步」的官方导出等待时长默认提高到 30 分钟（`TREE_EXPORT_TIMEOUT_SECONDS` 可调），超时后任务明确失败并提示手动处理步骤（到 115 根目录找到新导出的树文件，删除旧标准名文件并改名为标准名，再点「下载并生成」）；顶部“全部同步”按钮改名为“下载并生成”，直接下载已存在的树文件并生成，不再按 sha1 跳过。
- 115 大目录读取分页重构 + 官方搜索：目录列表按服务端 offset 逐页拉取（完整模式自动合并、前端支持“加载更多”），每页对 `IncompleteRead`/断连/超时重试并在大响应被掐断时自动缩小单页；刮削页搜索框改为 115 官方搜索接口（`webapi.115.com/files/search`），不再拉全量本地过滤。
- 刮削整理重命名批量合并：官方 `batch_rename` 一次提交多个条目、移动按目标目录分组，大批量整理请求数从几十上百次降到个位数；修复深层文件夹整理被放到错误层级、刮削任务卡“等待执行”、预览加载慢等问题。
- 可靠性修复：刮削任务改走独立执行线程并在启动时自动恢复等待任务；NFO 作为媒体信息文件不再被当作广告删除；自动识别结束不再清空用户正在输入的手动搜索与绑定；搜索框应用/清除后保持展开便于连续输入。
- 115 云下载任务完成检测驱动磁力/电驴刷新：提交离线任务后后台轮询官方 `task_lists`，任务完成自动触发监控扫描，失败/超时置 failed 不自动扫描；任务中心磁力/电驴卡片展示 115 下载进度条；CLI 新增 `offline list [--page N]` 只读诊断命令。
- 文件浏览器统一组件补齐“修改时间”：资源导入分享目录选择器新增修改时间列（名称/修改时间/大小），后端统一透传分享/目录条目的时间字段，目标目录与订阅分享目录的时间列不再显示 `--`（115/夸克正常显示）。
- 订阅任务“扫描链接”弹窗新增一键粘贴按钮（与搜索框同款样式与剪贴板逻辑）。
- 前端显示修复：资源推荐页翻页回顶、刮削页手机端操作栏 7 按钮单行、日志头部按钮日间配色统一、目录树任务卡片移动端布局与操作按钮图标化。
- 目录树任务化改造：废弃旧 `trees` 静态树源/定时模式，改为“目录树任务”模型——每个任务绑定一个 115 文件夹，调用官方 `files/export_dir` 生成树文件（导出 → 删旧 → 原地重命名），远端 sha1 未变化则跳过下载/解析/写 STRM；默认增量，支持“全量重写”，清理残留按任务范围。设置页目录树配置迁移到同步页并自动清理旧字段；任务页改为订阅任务风格（弹窗新增/编辑、进度条、分步计时日志）。CLI 新增 `tree list|create|update|delete|defaults|run|full|jobs`。
- CLI 补齐：`scrape batch-preferences get|set|clear` 读写/清除批量整理偏好；`scrape rename-plan` 支持文件命名方式等命名选项；`monitor add` 支持 `--auto-scrape-on-new` 与自动整理选项。
- 批量整理体验优化：入口按钮统一为“批量整理”，命名选项按「文件夹 → 文件命名 → 文件清理」三段重排；新增“文件命名方式”三档——标准重命名 / 仅清理广告信息（保留原始命名）/ 保持原名（不重命名），保持原名与仅清理档位下文件不移动，Season 子文件夹作为独立结构操作仍可生效。
- 批量整理选项按网盘记忆：服务端保存每个网盘上次的整理选项，页面加载或切换网盘自动恢复，变更自动保存，支持一键“恢复默认”。
- 监控任务“新增资源自动刮削整理”支持按任务配置整理选项：文件夹重命名 / Season 子文件夹 / TMDB ID / 文件命名方式 / 保留细节 / 删除广告文件，每个任务独立保存；未配置任务保持原行为。
- 新增宿主机命令行 CLI（合并外部贡献 PR #5 并适配当前 API）：25 个子命令覆盖搜索/订阅/转存/监控/刮削/STRM/运维等，AI 代理或脚本可无需网页完成“搜索→订阅→转存→监控→STRM→播放”全流程；登录不再静默使用默认 `admin/admin123`，要求 `MH_USERNAME`/`MH_PASSWORD` 环境变量或交互式输入，会话 Cookie 默认落盘 `/tmp/.115_cookies.txt`（0600，可用 `MH_COOKIE_FILE` 覆盖）。
- CLI 体验修复：`search --cancel` 改为显式标志、`subscribe remove` 走 `/subscription/delete` 清除队列与运行记录、`monitor` 按任务名操作、`scrape jobs-create` 真实三步流（识别 → TMDB 选择 → 计划 → 建任务）；另有 `logs --tail N`、`resource delete --id`、非法 ID 中文提示等 12 项审查修复。
- 刮削 rename/move/copy/delete 接口支持可选 `path`（move/copy 另支持 `dest`）入参，仅 115 可用并复用现有分页路径解析；identify/rename-plan 支持纯路径条目；新增发现源注册表（Telegram / PanSou 内置）供 `sources` 命令使用。
- 修复阿里云盘 alist 中转域名失效。
- 更多 0.5.x / 0.6.x 的刮削、资源同步、任务中心与移动端优化详见 `CHANGELOG.md`。

## 版本与更新

- 当前版本信息见 `version.json`
- 历史变更见 `CHANGELOG.md`
- 仓库地址：<https://github.com/xianer235/115-media-hub>

## 免责声明

本项目仅用于个人技术研究与个人媒体库自动化管理，不提供任何破解、绕过授权或商业化分发能力，也不鼓励将其用于任何侵权或违规场景。使用本项目即表示你已知悉并同意以下事项：

- 请仅在你有合法访问权限的数据、账号和资源范围内使用本项目，并遵守你所在地区法律法规及相关平台条款。
- `115 Cookie`、Webhook 密钥等凭据由使用者自行妥善保管；因凭据泄露导致的账号风险、数据泄露或资产损失需自行承担。
- 项目依赖第三方平台与网络环境（如 115、TG、TMDB 等），相关接口策略、可用性和返回结果可能随时变化，本项目不承诺持续可用或结果绝对准确。
