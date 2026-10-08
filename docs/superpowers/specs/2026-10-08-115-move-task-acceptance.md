# 115 写操作是「受理 + 排队执行」：整理为什么会误报「操作尚未执行完成」（2026-10-08）

> 状态：**已实施**（`app/providers/pan115.py`、`app/services/scraper.py`、`app/services/quick_import.py`）。
> 触发背景：同时整理多部影视时，日志出现
> `搬运失败：移动[乌鸦学园 (2026)[tmdbid-298505]]操作尚未执行完成，请稍后再试!`，
> 另一部「极寒之境」留在接收夹，而目录同步其实已经先跑了一轮。

## 一、结论（先说结果）

- 115 的 `files/move`、`files/batch_rename`、`files/copy`、`rb/delete` 都只是**受理**：
  返回 `{"state": true}` 只代表请求进了服务端队列，不代表文件已经在目标目录里。
- 同一账号上一次写任务还没跑完就再发，会拿到 EBUSY 语义的响应：
  `990019`（移动操作尚未执行完成）/ `990009`（删除 / 复制进行中）/ `990005`（类似任务处理中）/
  `590075`、`51012`（操作太频繁）。**这类响应可以安全退避重试**，旧实现却直接当「搬运失败」。
- 受理之后必须回验「真的落地」再做后续动作：删接收夹源目录、把监控同步事件按成功收尾、排 STRM 扫描。
  旧实现把「受理成功」当「搬运完成」，于是文件还在路上就去扫目标目录，扫不到 → 重试 → 整条整理失败。

## 二、接口事实（只读探测 + p115client 对照）

- `POST https://webapi.115.com/files/move`：表单字段 `pid=目标cid`、`move_proid=客户端生成的任务 id`，
  条目用 `_build_115_indexed_fid_payload` 生成的下标形式。
- `GET https://webapi.115.com/files/move_progress?move_proid=X` → `{"state": true, "progress": N}`；
  `progress >= 100` 表示服务端任务跑完。查不到这个 id 时返回 `{"state": false, "errno": 990003}`
  （通常是任务已结束并被清理）——**不能当失败**。不带参数时返回 `progress = 100`。
- `move_proid` 是**客户端生成**的（我们用毫秒时间戳），115 按它记录进度、也按它去重；
  所以重试要复用同一个 id，不会重复执行同一次移动。
- `files/get_info` 的父目录字段**不对称**：文件带 `fid`、父目录在 `cid`；目录自身就是 `cid`、父目录在 `pid`。
  回验「搬到哪了」只能按这个规则取。
- errno 表对照 `p115client`（本地克隆在 `/tmp/p115client`，`p115client/client.py` 的 errno 段），
  `fs_move` / `fs_move_progress` 的用法同 §二 描述。

## 三、改动

- `app/providers/pan115.py`
  - `_call_115_write_with_retry`：写操作统一走「限频 + 忙响应退避重试」，
    退避 `1 / 2 / 4 / 8` 秒（首次立即执行，共 5 次尝试）；重命名 / 移动 / 复制 / 删除全部接入。
  - `move_115_entries` 生成并回传 `move_proid`；`wait_115_move_progress` 轮询进度。
  - `wait_115_writes_landed`：先看进度，再逐条 `get_info` 回验父目录 / 名字（最多 3 轮）；
    `get_info` 查不到时退回「源目录里已经没有了」判定；两边都确认不了才算 `unknown`。
    返回 `landed` / `pending` / `unknown`——只有 `pending` 会阻塞后续动作。
  - `get_115_file_info` 补 `parent_id` / `is_dir`（回验依赖它）。
- `app/services/scraper.py`
  - `_move_provider_entries` / `_rename_provider_entries` 带上 `landing`；`move_scraper_entries`、
    `rename_scraper_entry`、整理任务的三步批量（改名 / 只移动 / 移动+改名）都按 `landing` 收尾：
    未确认落地时 `confirm_monitor_change_events(succeeded=False)` → 事件转 `needs_reconcile` 兜底重试。
  - 失败恢复 / 回滚路径传 `verify_landing=False`，避免救援被等待拖慢。
- `app/services/quick_import.py`
  - 分发循环遇到 `pending_ids` 时：不排目录同步子任务、不删接收夹源目录，条目留在接收夹并写明原因
    （`reason_code=dispatch_pending`），下一轮重试。
  - 并入已有文件夹的收尾删除同样要求「没有待确认落地」才执行。

## 四、阈值与开关

| 项 | 默认 | 环境变量 |
| --- | --- | --- |
| 移动进度 / 落地等待上限 | 30 秒（夹取 5～300） | `API_115_MOVE_WAIT_SECONDS` |
| 改名落地等待上限 | 12 秒（夹取 3～120） | `API_115_RENAME_WAIT_SECONDS` |
| 忙响应退避 | 1 / 2 / 4 / 8 秒 | 无（源码常量） |
| 落地回验轮数 | 3 轮 | 无 |
| 逐条回验条数上限 | 50 条（超出按 `unknown`，不阻塞） | 无 |

## 五、验证

- 单元 / 静态：完整 `unittest discover -s tests -p 'test_*.py'` **1247 项零失败**（`scripts/check.sh --all` 通过，
  含 `compileall app main.py`、`git diff --check`、`handoff.md` 体积预算）。
  - `tests.test_115_list_pagination.Pan115MoveAcceptanceTest`：忙响应退避后成功且复用同一 `move_proid`、
    连续忙响应 5 次后抛错、进度轮询、`990003` 不判失败、`get_info` 父目录字段不对称。
  - `tests.test_scraper_monitor_sync.ScraperMoveLandingTest`：未确认落地 → 同步事件按失败收尾并写明原因；
    确认落地 → 按成功收尾；非 115 网盘不等 115 落地。
  - `tests.test_quick_import`：待确认落地时不排同步、不删源目录、条目留在接收夹。
- **尚未实盘验证**：只做了只读探测（列目录、进度查询、`get_info`），没有在真实账号上重放写入；
  容器重建后需要按 `state.md` 待办实盘复核一次「多部影视同时整理」。

## 六、与既有文档的关系

- `docs/superpowers/specs/2026-09-18-115-move-orphan-folder-risk.md` §五.2
  「搬完未回验就删源」的缺口由本次修复覆盖：现在删源前必须先回验落地。
- 该文 §五.1（未拦截 115 系统目录当接收夹 / 目标）与 §五.3（缺 source→target 审计）仍然存在，未在本次处理。
- **仍未接落地回验的同类链路**：订阅的磁力 / 电驴离线入库
  （`app/services/subscription_task_runner.py:1536` 调 `provider_meta.move_entries`，
  之后 §「先原地改名、再刷新 STRM」立刻 `queue_monitor_job`）——它现在已经吃到统一的忙响应退避重试
  （不再因 `990019` 直接失败），但仍然是「受理完就刷监控」。要接的话，得先接住 move 的返回值取
  `move_proid`，再回验落地，未确认时不要触发监控刷新。
- 忙响应是**瞬态**的：一旦 `state=true` 受理成功，115 会继续把任务跑完；
  因此「本轮没确认落地」不会丢内容——条目留在接收夹下一轮重试，监控事件也会由 `needs_reconcile` 兜底补扫。
