# 115-strm-web

`115-strm-web` 是一个基于 FastAPI 的 Web 管理工具，用于把 115 网盘（挂载在 AList/OpenList）里的媒体文件快速生成本地 `.strm` 文件，适配 Emby/Jellyfin/Plex 等播放场景。

项目同时支持两条工作流：

1. `目录树任务`：基于 115 官方目录树文件批量生成（适合不常变化的大库,生成速度极快，避免频繁访问导致触发115风控）。
2. `文件夹监控任务`：基于 AList/OpenList API 实时扫描生成（适合小库、频繁变化目录，支持 webhook 触发）。

## 主要功能

- Web 后台管理（登录、参数配置、任务执行、日志查看）。
- 多目录树源合并解析（每个目录树可单独配置父路径和排除层级）。
- 扫描后缀可配置，支持一键恢复默认后缀。
- 文件夹监控任务支持：
  - 任务 CRUD（新增/编辑/删除）
  - 手动运行 / 中断
  - 增量/全量模式
  - 目录修改时间跳过
  - 读取失败重试（最多 5 次）
  - 目录读取延时、任务执行延时
  - 最小文件大小过滤
  - webhook 触发
  - 按分钟定时执行（0 表示关闭）
- 日志支持清理（目录树日志与文件夹监控日志分开清理）。
- 显示下次执行时间（开启定时时才显示）。

## 界面说明

## 1) 目录树任务

- 用于运行目录树解析与 STRM 生成。
- 支持联网同步、本地调试、强制全量重刷。
- 支持显示下次自动同步时间。

## 2) 参数配置

- `AList/OpenList 访问链接前缀`：例如 `http://192.168.1.5:5244`
- `AList/OpenList Token`：统一用于目录树下载和 API 扫描认证。
- `115 挂载根路径`：例如 `/115`
- `扫描后缀名` 默认：
  - `mp4,mkv,avi,mov,wmv,flv,webm,vob,mpg,mpeg,ts,m2ts,mts,rmvb,rm,asf,3gp,m4v,f4v,iso`
- `目录树多源配置`：
  - `目录树下载 URL`
  - `父文件夹路径前缀`（用于补全路径）
  - `排除层级`（默认 `1`，建议最小值为 `1`）
  - 说明：由于 115 目录树规则，建议优先保持排除层级 >= 1；需要补全路径时请使用父路径前缀，不建议把排除层级降到 0。

## 3) 文件夹监控任务

- 支持弹窗新增/编辑任务，任务列表中可直接运行、中断、编辑、删除。
- 执行前会触发 `refresh=true`（reload）。
- webhook 到达后，系统会优先尝试定位变化子目录并局部刷新，降低大目录全刷概率。

## webhook（CloudSaver）兼容说明

服务端地址格式：

```text
http://你的IP:容器端口/webhook/任务名
```

推荐请求方式：

- Method: `POST`
- Content-Type: `application/json`

推荐 JSON 字段：

- `delayTime`
- `event`
- `savepath`
- `xlist_path_fix`
- `title`

说明：

- 任务匹配以 URL 中的 `任务名` 为准（`/webhook/任务名`）。
- `strmtask` 为可选兼容字段，不再作为必填校验。

示例：

```json
{
  "delayTime": 0,
  "event": "cs_strm",
  "savepath": "/自存影视/115自存电视剧",
  "xlist_path_fix": "/115:/全部文件",
  "title": "/📺 正义女神 (2026) S01E07 4K WEB-DL AAC 6.12 GB"
}
```
使用cloud saver示例
<img width="1462" height="804" alt="cs配置方法" src="https://github.com/user-attachments/assets/d63e7809-cd1b-4bc3-aa3d-ac0b58de3161" />

## 部署

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

默认账号密码（首次）：

- 用户名：`admin`
- 密码：`admin123`

## 使用建议

- 大库走目录树任务，小库/连载更新走文件夹监控任务。
- 文件夹监控任务如果目录很大，建议：
  - 开启 webhook
  - 合理设置 `savepath/xlist_path_fix/title`
  - 让系统尽可能定位子目录刷新
- 若 115 目录树导出容易超时，建议按子目录拆分多份目录树，再在页面里多源配置合并。

## 免责声明

本项目仅用于学习和个人自动化管理，请遵守 115、AList/OpenList 及相关服务平台的使用条款。
