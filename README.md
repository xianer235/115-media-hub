# 115-strm-web

`115-strm-web` 是一个基于 FastAPI 的 Web 管理工具，用于把挂载在 AList/OpenList 的 115 媒体目录快速生成本地 `.strm` 文件，适配 Emby/Jellyfin/Plex 等媒体库。

项目包含两条任务线：

1. `目录树任务`：基于 115 官方目录树文件批量生成（适合大库、低频更新）。
2. `文件夹监控任务`：基于 AList/OpenList API 实时扫描生成（适合小库、频繁变动，支持 webhook）。

## 功能概览

- Web 后台管理：登录、参数配置、任务执行、日志查看。
- 目录树任务支持多源配置：每个源可配置 `父路径前缀`、`排除层级`。
- 文件夹监控任务支持：新增/编辑/删除、运行/中断、增量/全量、目录时间校验、重试、延时、体积过滤、定时执行。
- webhook 触发后优先尝试局部目录刷新，减少大目录全刷。
- 日志分离：目录树日志与监控日志独立，且支持页面一键清空。
- PC 和手机端响应式布局已适配。

## 快速部署

示例 `compose.yml`：

```yaml
services:
  115-strm-web:
    image: xianer235/115-strm-web:latest
    container_name: 115-strm-web
    restart: always
    ports:
      - "18080:18080"
    volumes:
      - ./strm:/app/strm
      - ./config:/app/config
      - ./log:/app/log
    environment:
      - TZ=Asia/Shanghai
```

启动：

```bash
docker compose up -d
```

访问：

- `http://服务器IP:18080`

首次默认账号密码：

- 用户名：`admin`
- 密码：`admin123`

## 目录说明

- `/app/strm`：生成的 `.strm` 文件目录。
- `/app/config/settings.json`：配置文件。
- `/app/config/data.db`：SQLite 任务状态数据库。
- `/app/log/task.log`：目录树任务日志。
- `/app/log/monitor.log`：文件夹监控日志。

## 页面说明

### 1) 文件夹监控任务

- 用于管理监控任务（运行、中断、编辑、删除）。
- 执行前会触发 `refresh=true`（reload）。
- 支持 webhook 触发和按分钟定时执行（`0` 表示关闭）。

### 2) 目录树任务

- 用于执行目录树下载、解析与批量生成 STRM。
- 支持：联网同步更新、本地调试解析、强制全量重刷。
- 支持显示下次自动执行时间（开启定时时显示）。

### 3) 参数配置

- `AList/OpenList 访问链接前缀`：如 `http://192.168.1.5:5244`
- `AList/OpenList Token`：目录树下载与 API 扫描统一认证。
- `115 挂载根路径`：如 `/115`
- `扫描后缀名` 默认值：
  - `mp4,mkv,avi,mov,wmv,flv,webm,vob,mpg,mpeg,ts,m2ts,mts,rmvb,rm,asf,3gp,m4v,f4v,iso`
- `目录树多源配置`：
  - `目录树下载 URL`
  - `父文件夹路径前缀`（用于路径补全）
  - `排除层级`（默认 `1`，最小建议 `1`）

## Webhook（CloudSaver）说明

服务端地址格式：

```text
http://你的IP:容器端口/webhook/任务名
```

请求建议：

- Method: `POST`
- Content-Type: `application/json`

本项目 webhook 仅接收以下参数：

- `savepath`：转存目标父路径，用于定位刷新范围。
- `sharetitle`（可选）：转存资源文件夹名；为空时回退按 `savepath` 刷新。
- `delayTime`（可选）：本次任务延时秒数，覆盖任务内默认延时。
- `title`（可选）：仅用于日志展示“转存内容”。

关键规则：

- 任务匹配以 URL 中的 `任务名` 为准（`/webhook/任务名`）。
- `savepath` 支持两种写法：`连载中` 或 `/连载中`（也可传更深路径）。
- `sharetitle` 不为空时，优先按 `savepath/sharetitle` 做局部刷新；为空时回退按 `savepath` 刷新。
- 实际目录定位会结合参数配置中的 `mount_path` 自动推导，不需要额外传挂载映射参数。
- 触发条件、变量映射、请求体内容拼装均在 CloudSaver 中配置；本项目不在本地页面配置这些规则。

CloudSaver 配置示例图：

<img width="2576" height="1444" alt="image" src="https://github.com/user-attachments/assets/0b454b91-32f4-46cc-97b6-1abc131875bb" />



## 使用建议

- 大库建议走目录树任务，小库或连载更新建议走文件夹监控任务。
- 监控任务目录很大时，建议优先启用 webhook 局部刷新，降低被限流/风控概率。
- 目录树导出较慢时，建议按子目录拆分多份目录树后在页面多源合并。

## 免责声明

本项目仅用于学习和个人自动化管理，请遵守 115、AList/OpenList 及相关平台的使用条款。
