# 115 网盘文件操作事件：接口调研与知识储备（2026-08-16）

> **状态：知识储备，暂不实施。**
> 2026-08-16 决策：不采用“轮询 115 事件接口自动同步”方案，不新增轮询服务；本文档保留调研结论、接口实测数据与设计备忘，供将来需要时直接参考。
> 当前线上兜底方案：刮削页“扫描监控/刷新 STRM”按钮（勾选条目后手动触发局部扫描，方案二，已实现）。

## 一、背景与决策

- 用户场景：在 115 官方网页/客户端（项目以外）复制、上传、删除、改名、移动文件时，115-media-hub 监控不会感知，STRM 漏检；`skip_by_dir_mtime` 对深层子目录尤其容易漏。
- 候选方案一：从 115 官方接口获取文件操作通知，自动触发监控目录局部扫描。
- 调研结论：
  - **115 没有可靠的官方实时推送**（详见参考项目调研）；
  - 社区标准做法 = **常驻服务轮询“生活事件”做增量**；
  - 我们的账号实测两个事件接口可用，事件覆盖复制/改名/移动/删除/上传，字段足以映射到监控目录。
- 最终决策（用户）：**暂不实施**，本次接口与调研信息作为知识储备留存。

## 二、参考项目调研（如何实现 / 如何设计 / 达到什么效果）

调研对象：p115client / p115tinydav、cloud-media-sync（CMS）、115_Auto_Symlink、q115-strm / qmediasync、OneStrm、suixing8/115-strm、cloud-fs。

| 项目 | 实现方式与设计 | 达到的效果 |
| --- | --- | --- |
| cloud-media-sync（CMS） | 增量同步直接依赖 115 生活事件接口，官方说明原话：“只需要请求一次接口就能知晓所有变动” | 后台常驻，一次拉取即覆盖全部操作 |
| p115tinydav | 首次全量入库 + 事件增量；被访问时再拉增量；长久不访问时 1 小时/次例行检查 | 常用目录近实时同步，冷门目录最迟 1 小时兜底 |
| q115-strm / qmediasync | 定时任务：全量刷新与增量刷新分开，增量 30 秒~5 分钟，全量 3 万文件约 30 分钟 | 分钟级增量同步 |
| OneStrm / 115_Auto_Symlink | 依赖 CloudDrive2 会员的“文件通知”把网盘变更推给本地；OneStrm 3 分钟收集一次，超过 10 个增量直接拉全库 | 3 分钟级“实时”；但来自挂载层（CD2 会员），不是 115 官方接口 |
| cloud-fs 等其余项目 | 均为常驻 Docker 服务（`--restart unless-stopped`） | 不依赖用户电脑/浏览器常开 |

### 关键结论

1. **部署形态**：所有参考项目都部署在 NAS/云主机等常驻设备上，没有依赖用户桌面或浏览器常开的方案。“用户不常开电脑”这个约束靠部署常驻服务解决，不靠操作端脚本。
2. **实时推送不可行**：
   - WebSocket（`ws.115.com`）存在，但 p115client 作者实测“消息类型有限（文件删除、云下载重试等）、覆盖极小、没有利用价值”；
   - 115 开放平台明确不支持“监听网盘事件、同步文件变更”，没有官方 webhook。
3. **社区标准做法 = 生活事件轮询做增量**，而不是逐文件扫描对比。
4. **差异点（对我们有利）**：CMS/p115client 文档声称“复制、改名无事件”，但我们实测 `life/recent_operations` 能拿到复制（type 18）、改名（type 24/20），覆盖强于 CMS 依赖的行为接口。
5. 前提条件：115 账号需开启“最近记录/生活事件”（一般默认开启，CMS 文档也强调）。

## 三、115 官方接口实测

使用项目配置中的 `cookie_115`（本机路径 `/Users/xianer/Documents/docker/115strmxianer/config/settings.json`）直连官方接口，只读探测，未做任何写操作。

### 3.1 事件源总览

| 事件源 | 覆盖操作 | 识别方式 | 限制 |
| --- | --- | --- | --- |
| `life.115.com/api/1.0/web/1.0/life/recent_operations?limit=100` | 复制（18）、文件改名（24）、文件夹改名（20）、移动（6/5） | `behavior_type` 分组 + item `type` | 不含删除/上传；无服务端过滤/分页 |
| `webapi.115.com/behavior/detail?limit=200` | 删除（22）、上传（2）及全部历史流水 | item `type` | 无行为分组；偶发一次空返回需重试 |

### 3.2 接口详情

**`GET/POST https://life.115.com/api/1.0/web/1.0/life/recent_operations?limit=100`**

- 按 `behavior_type` 分组返回：`data.list[] = {behavior_type, date, items[]}`。
- `limit` 有效（1~100，默认 20）。

**`GET https://webapi.115.com/behavior/detail?limit=200`**

- 扁平历史流水（真实账号约 8000 条），无行为类型分组。

**`GET https://webapi.115.com/files/get_info?file_id=...`**

- 返回 `cid`（文件所在目录）/`pid`（父目录），可逐级上溯反查完整路径。
- 文件已删除时返回错误码 20018（“文件不存在或已删除”），可用于区分文件存在/已删除。

### 3.3 事件 type 代码表（实测 + p115client `BEHAVIOR_NAME_TO_TYPE` 对照）

| type | 含义 | 出现位置 |
| --- | --- | --- |
| 2 | 上传 | 仅 `behavior/detail`（实测 `SteamSetup.exe`） |
| 3 / 4 | 收藏 | 行为接口 |
| 5 | 移动图片 | `recent_operations` + `behavior/detail` |
| 6 | 移动文件 | `recent_operations` + `behavior/detail` |
| 10 | 浏览文档（噪音，应过滤） | `recent_operations` |
| 14 | 接收文件 | 行为接口 |
| 17 | 新建文件夹 | 行为接口 |
| 18 | 复制文件夹 | `recent_operations` + `behavior/detail`（实测） |
| 20 | 文件夹改名 | `recent_operations` + `behavior/detail`（实测） |
| 22 | 删除 | 仅 `behavior/detail`（实测） |
| 23 | 复制文件 | 行为接口 |
| 24 | 文件改名 | `recent_operations` + `behavior/detail`（实测） |

### 3.4 受控操作复测结果（2026-08-16，用户在 115 网页端操作后立即抓取）

| 操作 | 事件 | item.type | 出现位置 | 验证方式 |
| --- | --- | --- | --- | --- |
| 复制 | `copy_folder` | 18 | 两个接口都有 | 事件项 `parent_name=115连载中`，`get_info` 确认目标存在且带父链 `pid` |
| 重命名 | `file_rename` / `folder_rename` | 24 / 20 | 两个接口都有 | 事件项含 `file_name`、`parent_name` |
| 移动 | `move_file` / `move_image_file` | 6 / 5 | 两个接口都有 | 历史窗口内出现 |
| 删除 | （无分组标签） | 22 | **仅 `behavior/detail`** | type=22 的 `file_id` 经 `get_info` 返回“文件不存在或已删除”，对照组存在文件正常返回 |
| 上传 | （无分组标签） | 2 | **仅 `behavior/detail`** | 用户上传 `SteamSetup.exe`（source=macOS）后立即捕获，`get_info` 确认存在且 `cid`=父目录 |

### 3.5 事件字段与目录映射

每条事件项带：`file_id`、`parent_id`、`parent_name`（直接父目录 id 与名称）、`file_name`、`file_size`、`file_category`/`file_type`、`update_time`、`create_time`、`source`（来源客户端）、`sha1`、`pick_code`、`is_available`。

**不含完整父路径**。映射到监控任务需要：用 `parent_id` 经 `get_info` 逐级上溯出完整网盘路径（目录节点做内存缓存、节点间限速），再与监控任务 `scan_path`/`savepath` 比对；项目已有目录树同步与 `resolve_scraper_path_entry` 等路径解析能力可复用。

### 3.6 接口约束

- `behavior_type=` 过滤无效、`page=` 无效、`type=` 报错；无服务端过滤/分页/游标 → 需周期性拉最近 N 条，客户端按事件 id/`update_time` 做去重与增量游标。
- 偶发一次空返回，落地时需容忍空页/重试。
- 只读轮询接口，建议低频（1~5 分钟）以降低风控风险。

## 四、若将来实施的设计参考（仅备忘，不实施）

以下为当初的完整落地设计，留档供将来需要时直接复用（核心改动点已与本项目现有“指定目录扫描”通道对齐）。

### 机制

后台周期轮询双事件源（默认 300 秒，可调 60~3600），客户端按 type 过滤（忽略浏览 10、忽略非媒体扩展名的文件事件；文件夹事件始终触发），事件命中监控任务子树后，按任务分组调用 `queue_monitor_dir_scan`/`queue_monitor_job(task, "life", {"provider":"115","savepaths":[...]})`，复用 `run_monitor_task` 的 `savepaths` 子树扫描分支刷新 STRM。

### 事件源与过滤

- 双源合并：`recent_operations`（复制/改名/移动）+ `behavior/detail`（删除/上传）。
- 去重：游标水位 `update_time` + 同水位按事件 id 内存去重；`behavior/detail` 偶发空返回重试一次。
- 路径反查：`get_info` 沿 `pid` 上溯到挂载前缀根（如 `/115`），父目录已删除（20018）返回空并计数为 unresolved。

### 调度与触发

- `app/startup.py` 新增 `life_events_scheduler()`（启动后先睡 8s，按间隔循环 `asyncio.to_thread(poll_life_events_once)`）。
- 触发优先级表新增 `"life": 1`（低于 manual，仅高于 cron/队列）；`run_monitor_task` 的 savepaths 分支条件扩展为 `trigger in ("manual", "life")`。
- 状态摘要：`monitor_status["life"] = {enabled, last_poll_at, events_seen, matched_tasks, unresolved, last_error}`，随 `/monitor/status` 返回。

### 配置与设置页

- 配置键：`life_event_sync_enabled`（bool，默认 False）、`life_event_poll_interval_seconds`（int，默认 300，钳制 60~3600）。
- 设置页新增“115 最近操作同步”卡片：开关 + 轮询间隔输入框。
- 游标持久化：SQLite 新表 `life_event_state(account_key, last_update_time, last_event_id, last_poll_at)`，写入用 `retry_sqlite_locked`。

### 已知局限（若实施时需接受）

- 事件由官方异步生成，轮询存在秒级~分钟级延迟，不是实时通知。
- 删除事件若连同父目录一起删除，路径无法反查，跳过并告警，由手动扫描兜底。
- 移动事件按事件所在父目录入队；若 115 只产生目标侧事件，源目录过期 STRM 由后续全量/手动扫描清理。
- 非媒体文件事件不触发（避免 `SteamSetup.exe` 这类上传噪音）；文件夹事件始终触发。

## 五、遗留风险与注意事项

- 事件接口与页面筛选可能随 115 改版变化；若将来实现，需保留失败降级（探测失败则停用轮询并告警，不影响手动扫描）。
- `parent_id` 反查需要额外目录接口调用，量大时注意限速与缓存（可复用项目目录树缓存）。
- 本机 Cookie 路径为 `/Users/xianer/Documents/docker/115strmxianer/config/settings.json`；调试脚本留在 `/tmp` 使用，勿写入仓库。
- 旧版 p115client 要求 Python 3.12，本项目环境是 Python 3.9，不能直接引入依赖，只能参考其接口与 type 代码表。

## 相关链接

- 方案二（已实现）：刮削页“扫描监控/刷新 STRM”——`queue_monitor_dir_scan`、`POST /monitor/scan`、`run_monitor_task` 的 `savepaths` 子树扫描分支。
- 交接记录：`docs/superpowers/handoff.md`（2026-08-16 条目）。
