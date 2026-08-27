# 跨网盘复制（115 / 阿里云盘 / 夸克）流式中转设计

日期：2026-08-27

## 背景与目标

刮削页目前只支持同盘复制：前端 `copyHere` 在 `buffer.provider !== state.provider` 时直接拒绝，后端 `copy_scraper_entries` 也只调用目标盘 `provider.copy_entries`。用户在 115 / 阿里云盘 / 夸克 之间希望直接跨盘复制，替代“手动下载再上传”。

经用户确认：

- 只做 **流式中转（一边下载一边上传）**，不做跨盘秒传（不做 SHA1 / proof_code 预检）；
- 第一版支持 **115、阿里云盘、夸克** 三个网盘两两互传；
- 123 云盘、天翼云盘不在本次范围（上传链路要求整文件哈希，与“边下边传”冲突，后续单独评估）；
- 目标目录同名冲突沿用同盘语义：目标盘接口报错则任务失败并提示，不做自动改名或覆盖；
- 订阅自动跨盘互传（P2/P3）不在本次范围，但接口设计预留复用空间。

## 现状盘点

| 能力 | 115 | 阿里云盘 | 夸克 |
|---|---|---|---|
| 同盘复制 | ✅ `copy_entries` | ✅ | ✅ |
| 源盘下载直链 | ❌ `resolve_download_url` 未实现 | ❌ 未实现 | ❌ 未实现 |
| 目标盘分片上传 | ❌ 未实现 | ❌ 未实现 | ❌ 未实现 |
| 文件夹监控 / STRM | ✅ | ❌ | ❌ |

可以复用的现成基建：

- 刮削页：条目选择、剪贴板、路径快照、`request_id` 幂等习惯；
- 任务中心：`resource_jobs` 表 + `create_resource_job / update_resource_job / cancel_resource_job / retry_resource_job` + `/resource/jobs/state`、`/resource/jobs/cancel`、`/resource/jobs/retry` 接口；
- 监控触发：`match_monitor_tasks_for_paths` 按目标路径命中 115 监控任务，`queue_monitor_job` 提交刷新。

## 目标与边界

- 刮削页从 A 盘选择条目（文件或目录），切到 B 盘目录后“复制到此处”，提交后台跨盘复制任务；
- 任务在任务中心可见：实时进度（第几个文件、当前文件百分比/字节）、可取消、可重试；
- 目录条目递归展开为文件清单，目标盘按相对路径建目录，逐文件流式传输；
- 目标盘是 115 且目标路径命中监控任务时，任务完成后触发监控刷新（STRM / 自动刮削）；
- 失败重试从当前文件重头开始，不做断点续传；单文件内同一分片最多重试 3 次；
- 取消时若目标盘支持 abort 会话则尽力清理，否则保留已传分片并明确提示，不静默覆盖后续同名文件。

不在本次范围：秒传、断点续传、123/天翼、订阅自动跨盘互传、服务器中转（仅本机中转）。

## 组件设计

### A. Provider 接口扩展（`app/providers/base.py` + 三个实现）

新增能力位：

```python
supports_transfer_source: bool = False   # 可作跨盘复制源（提供下载直链）
supports_transfer_target: bool = False   # 可作跨盘复制目标（提供分片上传）
```

新增方法（三盘均需实现）：

```python
def resolve_download_url(self, cookie: str, file_id: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    """返回 {url, headers, supports_range}；supports_range=False 时服务层走临时文件兜底。"""

def create_upload_session(self, cookie: str, target_id: str, filename: str,
                          size: int, part_size: int) -> Dict[str, Any]:
    """创建目标盘上传会话，返回会话凭证（upload_id / part_urls 等）。"""

def upload_part(self, cookie: str, session: Dict[str, Any],
                part_number: int, data: bytes) -> Dict[str, Any]:
    """上传一个分片，返回该分片的 etag / 校验信息。"""

def complete_upload(self, cookie: str, session: Dict[str, Any],
                    parts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """完成上传，返回目标条目。"""

def abort_upload(self, cookie: str, session: Dict[str, Any]) -> None:
    """取消时尽力清理未完成会话（可选实现）。"""
```

实现要点（接口名以实测为准，先实现后真实账号验证）：

- **115**：下载直链复用官方下载解析；上传走 115 OSS 分片（初始化上传 → 各分片签名上传 → 完成），沿用现有 `http_request_form_json`、cookie 健康标记与限流；
- **阿里云盘**：下载直链走 OpenAPI 下载地址；上传走 `openFile/create`（带 `part_info_list`）→ 预签名 URL 分片 PUT → complete；不做 SHA1 预检即不做秒传；
- **夸克**：下载直链与分片上传走夸克 multipart 接口，逐分片计算并携带所需校验值。

所有请求继续遵守现有 `throttle()` 与 `mark_cookie_health_*` 约定；下载/上传直链和签名参数不得写入日志。

### B. 传输服务（新增 `app/services/cross_cloud_transfer.py`）

#### 1. 文件清单构建

对每个源条目：

- 文件：直接加入清单；
- 目录：递归 `list_entries` 展开，`rel_path` 保持相对目标目录的层级；
- 清单项：`{rel_path, name, file_id, size, is_dir}`，`size` 用于分片规划与进度。

构建阶段只做清单与目标目录创建，不传输数据；失败时任务立即失败，不留半成品目录（已建目录允许残留空目录，后续任务复用）。

#### 2. 单文件流式管道

```text
resolve_download_url(源)
  → 下载协程按固定分片（默认 8 MiB）读取
  → 有界队列（默认缓冲 3 片）
  → 上传协程逐片 upload_part
  → 全部完成 complete_upload
```

- 下载与上传是两个并发协程，队列满时下载暂停，真正做到边下边传且内存有界；
- 分片大小可由 provider 或配置覆盖；`part_size` 在 `create_upload_session` 时确定；
- 单分片上传失败重试 3 次（指数退避），仍失败则整个文件失败；
- 每个分片边界检查 `resource_job_cancel_requested`，取消时中止下载流、尽力 `abort_upload`；
- 源直链不支持 Range 时降级整文件下载到 `/tmp` 临时文件再上传（第一版保留该兜底，正常路径仍为流式）。

#### 3. 任务编排

```python
async def run_cross_cloud_transfer_job(job_id: int) -> None:
    # 1. 读取 job.extra：源/目标盘、源条目快照、目标路径
    # 2. 构建文件清单 + 目标目录
    # 3. 逐文件流式传输，update_resource_job 节流写进度（默认 2s）
    # 4. 全部完成 → status=completed
    # 5. 目标盘为 115 → match_monitor_tasks_for_paths + queue_monitor_job 触发刷新
    # 6. 异常/取消 → status=failed + 明确状态明细
```

进度明细示例：

```text
跨盘复制：3/10 个文件 · 正在复制 电影/01.mkv（45%）
```

### C. 任务接入（复用 `resource_jobs`）

- 提交时 `create_resource_job(resource={"id": 0, "title": "跨盘复制: A → B", ...}, data={...})`；
- `link_type` 使用占位 `"cross_cloud_transfer"`，`job_source` 写入 `"cross_cloud_transfer"`；
- `extra_json` 保存：`source_provider`、`target_provider`、`source_cid`、`target_path`、`target_cid`、`entries` 快照、`monitor_task_names`、`current_index/total_count`、`transferred_bytes/total_bytes`；
- `run_resource_job` 增加分发：`job_source == "cross_cloud_transfer"` 时转 `run_cross_cloud_transfer_job`，保证现有取消/重试接口直接可用；
- 不依赖 `resource_items`（`resource_id=0`），任务中心列表已按 `resource_jobs` 展示，无需改前端列表。

### D. API

新增 `POST /scraper/cross-copy`（路由放在 `app/routes/scraper.py`）：

```json
{
  "source_provider": "115",
  "entry_ids": ["123", "124"],
  "entries": [{"id": "123", "name": "电影", "is_dir": true, ...}],
  "source_cid": "100",
  "target_provider": "aliyun",
  "target_cid": "root",
  "target_parent_path": "影视/跨盘",
  "request_id": "..."
}
```

校验与响应：

- 源/目标盘必须已启用且已配置认证，且具备 `supports_transfer_source/target`；
- 条目非空；搜索结果未知路径条目继续拦截（与同盘复制一致）；
- 源盘等于目标盘时拒绝并提示走同盘复制；
- 成功返回 `{"ok": true, "job_id": 123, "status": "pending", "title": "跨盘复制: 115 → 阿里云盘"}`；
- 任务查询/取消/重试复用现有 `/resource/jobs/state`、`/resource/jobs/cancel`、`/resource/jobs/retry`。

### E. 前端（`static/js/modules/scraper/core.js`）

- `copyHere()` 中把“跨盘直接拒绝”改为：
  - `buffer.provider !== state.provider` 时弹确认框：`将 N 个条目从 X 跨盘复制到 Y，将创建后台任务（耗时取决于网速），确定继续吗？`；
  - 确认后调 `POST /scraper/cross-copy`，清空剪贴板，toast `已提交跨盘复制任务 #id`；
  - 保持同盘复制走原 `/scraper/{provider}/copy` 不变；
- 后端校验失败时前端显示后端 msg，不重复维护能力清单。

## 测试计划

新增 `tests/test_cross_cloud_transfer.py`：

1. 文件清单构建：文件/目录递归、相对路径、大小字段、源目录展开失败；
2. 目标目录创建：复用 `ensure_folder_id_by_path`、失败冒泡；
3. 单文件流式管道：分片边界（正好整片/余量/空文件）、下载与上传并发、队列有界；
4. 分片重试：同一分片失败 3 次后文件失败；重试成功后继续；
5. 取消：分片边界触发取消、abort 尽力调用、状态为 failed 且明细含“已取消”；
6. 任务生命周期：pending → running → completed / failed；进度明细节流；
7. 115 目标监控触发：命中任务时 `queue_monitor_job` 调用、未命中不调用；
8. API 校验：未启用/未配置/不支持传输/同盘/空条目/未知路径；
9. 前端 VM 回归：跨盘确认与请求载荷、同盘原逻辑不变。

## 验证

- 全量 unittest、`PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m compileall app main.py`、改动 JS `node --check`、`git diff --check`；
- `docker compose up -d --build` 后真实账号验证：
  1. 115 → 阿里云盘：小目录（含子目录与若干文件）；
  2. 阿里云盘 → 夸克：单文件；
  3. 115 → 夸克：多文件，观察任务中心进度、取消一个、重试一个；
  4. 目标为 115 监控目录时确认 STRM / 自动刮削触发。

## 风险与兼容

- 三个盘的下载直链与分片上传均为逆向接口，先实现再以真实账号校准，文档不承诺固定 endpoint；
- 流式中转占用本机带宽，任务中心会明确展示进度；不做断点续传，失败重试从当前文件重头；
- 取消不保证目标盘已传分片被清理，但不会覆盖已完成任务（状态明细会写明“任务已取消，可能残留未完成分片”）；
- 不做秒传意味着 115 ↔ 阿里 不再有哈希加速路径，所有组合统一流式；
- `resource_jobs` 增加 `job_source=cross_cloud_transfer` 分支时保持现有离线/分享转存逻辑完全不动；
- 目标盘非 115 时不触发监控，与现有“非 115 无监控”能力一致。

## 实施顺序

1. `base.py` 接口扩展 + 115 / 阿里 / 夸克 的下载直链与分片上传实现；
2. `app/services/cross_cloud_transfer.py` + `run_resource_job` 分发；
3. `POST /scraper/cross-copy` + 前端跨盘确认；
4. 单测 + 全量回归 + Docker 真实账号验证；
5. 更新 `docs/superpowers/handoff.md` 交接记录。
