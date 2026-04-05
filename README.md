# 115 Media Hub

`115 Media Hub` 是一个基于 FastAPI 的媒体自动化管理面板，把 `115`、`AList/OpenList`、`.strm`、TG 资源同步、影视订阅追更放进同一个后台。

它适合已经把 115 挂载到 AList/OpenList、并希望进一步把“生成播放链接”“转存后自动刷新”“按片名自动找资源”串起来的使用场景。

## 这项目能做什么

| 模块 | 作用 |
| --- | --- |
| 资源中心 | 同步 TG 公开频道资源，或手动粘贴 magnet / 网盘分享链接入库，并直接提交到 115 离线下载 |
| 影视订阅任务 | 按周期搜索候选资源，自动创建导入任务，支持电影和剧集追更 |
| 文件夹监控任务 | 扫描 AList/OpenList 目录变化，支持手动、定时、Webhook 触发 |
| 目录树任务 | 基于 115 目录树批量生成 `.strm` 文件，适合大库初始化和低频更新 |
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

TG 访问相关：

- `TG_CHANNEL_THREADS_DEFAULT`：TG 同步默认线程数，默认 `6`

TMDB 相关：

- `TMDB_REQUEST_TIMEOUT_SECONDS`：TMDB 请求超时，默认 `20`

频道缓存治理：

- `RESOURCE_CHANNEL_CACHE_LIMIT`
- `RESOURCE_CHANNEL_INACTIVE_CACHE_LIMIT`
- `RESOURCE_CHANNEL_CACHE_TTL_DAYS`
- `RESOURCE_CHANNEL_CACHE_GLOBAL_LIMIT`
- `RESOURCE_CHANNEL_CACHE_ACTIVE_MIN_KEEP`

## 浏览器辅助脚本

仓库根目录自带油猴脚本：

- `115-magnet-helper-webhook.user.js`

它是浏览器侧工具，不会打包进容器镜像。它的用途主要是：

- 在页面里识别磁力链接并辅助提交到 115
- 按保存目录绑定不同的 Webhook 地址
- 在离线任务提交后顺手触发服务端刷新

服务端同时提供下载入口：

- `GET /download/userscript/magnet-helper.user.js`

## 版本与更新

- 当前版本信息见 `version.json`
- 历史变更见 `CHANGELOG.md`
- 仓库地址：<https://github.com/xianer235/115-media-hub>

## 说明

本项目用于个人媒体库自动化管理，请结合你自己的使用环境和相关平台规则自行评估后使用。
