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

如果你使用本仓库直接构建镜像，仓库根目录下的油猴脚本 `115-magnet-helper-webhook.user.js` 不会参与镜像构建。
这是一个浏览器侧本地插件，不属于容器运行时所需文件，已通过 `.dockerignore` 排除。

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

## 油猴脚本插件

仓库根目录额外提供了一个油猴脚本：

- `115-magnet-helper-webhook.user.js`

这个脚本是浏览器侧辅助工具，不属于 `115-strm-web` 容器镜像内容，主要用于：

- 自动识别网页中的磁力链接并显示 `115` 按钮。
- 选择 115 云盘保存目录后，自动发起离线下载。
- 按保存目录绑定不同的 webhook 地址和延迟秒数。
- 在保存成功后，顺手触发你在 `115-strm-web` 中配置好的文件夹监控任务。

### 安装方法

推荐先安装浏览器扩展：

- Chrome / Edge：`Tampermonkey`
- Firefox：`Tampermonkey` 或 `Violentmonkey`

然后将仓库中的 `115-magnet-helper-webhook.user.js` 导入脚本管理器，保存并启用。

### 使用方法

1. 打开任意包含磁力链接的页面。
2. 页面中识别到 `magnet:` 链接后，旁边会出现 `115` 按钮。
3. 点击按钮，选择要保存到 115 云盘的目标文件夹。
4. 如果该文件夹已配置 webhook，脚本会在保存成功后自动再发起一次 webhook 请求。

### Webhook 管理

脚本内置了“按文件夹配置 webhook”的管理界面，支持：

- 为不同保存文件夹配置不同的 webhook 地址
- 配置对应的 `delayTime`
- 启用或停用单个文件夹的 webhook
- 手动测试当前 webhook 是否可达

打开方式有两种：

- Tampermonkey 菜单：`115云盘磁力助手 Webhook 增强版：管理文件夹 webhook`
- 点击 `115` 按钮后，在文件夹选择弹窗中点 `管理 webhook`

### 请求体说明

脚本触发 webhook 时，默认以 `POST` + `application/json` 发送，常见字段包括：

- `delayTime`：延迟秒数
- `title`：磁力链接中的资源标题，若可解析
- `folderId`：115 目标文件夹 ID
- `folderName`：115 目标文件夹名称

测试按钮还会额外带上：

- `event: "test"`：便于服务端区分测试请求

### 与容器的关系

- 这个脚本只运行在浏览器/Tampermonkey 中。
- 它不会进入 Docker 镜像，也不会在容器内执行。
- 容器内仍然只运行 `FastAPI` 服务本体。


## 使用建议

- 大库建议走目录树任务，小库或连载更新建议走文件夹监控任务。
- 监控任务目录很大时，建议优先启用 webhook 局部刷新，降低被限流/风控概率。
- 目录树导出较慢时，建议按子目录拆分多份目录树后在页面多源合并。

## 免责声明

本项目仅用于学习和个人自动化管理，请遵守 115、AList/OpenList 及相关平台的使用条款。
