# 刮削监控路径同步 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让刮削任务确认成功后的本地 STRM 同步只依据路径关系执行，并让同步失败只留下监控日志。

**Architecture:** 网盘执行层继续使用文件和目录 ID 调用 115 接口；文件夹监控层把 `old_path -> new_path` 视为统一路径变换，不再用父目录 ID 判断 rename/move。刮削来源的已确认本地同步采用一次性消费，失败时恢复文件 journal、返回日志信息并删除队列事件；普通监控变更保持现有重试。

**Tech Stack:** Python 3、FastAPI 服务层、SQLite、`unittest`

---

### Task 1: 锁定路径同步语义

**Files:**
- Modify: `tests/test_scraper_monitor_sync.py`
- Modify: `app/services/monitor_changes.py`

- [ ] **Step 1: 写入父目录 ID 与路径冲突的失败测试**

新增一个已确认的 `scraper-job:*` rename/move 事件，令完整旧路径和新路径有效，但父目录 ID 与路径关系冲突；断言处理器仍按路径删除旧 STRM、生成新 STRM，并更新 `monitor_files`。

- [ ] **Step 2: 运行测试并确认当前错误**

Run: `PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m unittest tests.test_scraper_monitor_sync.ScraperMonitorSyncTest.test_confirmed_scraper_change_uses_paths_when_parent_ids_disagree`

Expected: FAIL，错误包含 `精准同步移动父目录路径与目录 ID 不一致`。

- [ ] **Step 3: 将确认事件归一化为路径操作**

在 `app/services/monitor_changes.py` 中让 rename/move 的本地计划只从 `dirname(old_path)` 与 `dirname(new_path)` 推导展示操作类型；删除父目录 ID 一致性校验。保留完整路径、监控范围、清单边界和共享输出冲突校验。

- [ ] **Step 4: 运行定向测试确认通过**

Run: `PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m unittest tests.test_scraper_monitor_sync.ScraperMonitorSyncTest.test_confirmed_scraper_change_uses_paths_when_parent_ids_disagree`

Expected: PASS。

### Task 2: 刮削路径同步失败只记录日志

**Files:**
- Modify: `tests/test_scraper_monitor_sync.py`
- Modify: `app/services/monitor_changes.py`
- Modify: `app/services/monitor.py`

- [ ] **Step 1: 写入一次性失败消费测试**

构造 `source_action=scraper-job:*`、`needs_reconcile=0` 的已确认事件，使本地 STRM 写入失败；断言 journal 恢复旧文件、结果包含错误、数据库事件已删除，且不存在 `retry_count` 累加和卡片失败计数。

- [ ] **Step 2: 写入普通事件重试保护测试**

使用非 `scraper-job:*` 事件触发相同本地错误；断言仍保存 `failed` 状态、`retry_count=1` 和未来的 `next_retry_at`。

- [ ] **Step 3: 运行测试并确认刮削事件测试失败**

Run: `PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m unittest tests.test_scraper_monitor_sync.ScraperMonitorSyncTest.test_confirmed_scraper_sync_failure_is_logged_and_deleted tests.test_scraper_monitor_sync.ScraperMonitorSyncTest.test_local_write_failure_is_retained_and_retried_with_backoff`

Expected: 第一项 FAIL，第二项 PASS。

- [ ] **Step 4: 实现来源明确的一次性消费**

在异常分支通过 `source_action.startswith("scraper-job:") and not needs_reconcile` 识别刮削确认事件。恢复 journal 后删除该事件，仍把 `event_id/error` 返回给日志层；其他事件继续执行原退避更新。

- [ ] **Step 5: 更新日志文案测试与实现**

断言刮削一次性失败日志为 `变更事件 #N 失败: 原因`，不再出现 `已保留重试`。普通事件仍使用 `失败，已保留重试`，避免日志误导。

### Task 3: 清理历史刮削失败事件

**Files:**
- Modify: `tests/test_scraper_monitor_sync.py`
- Modify: `app/services/monitor_changes.py`

- [ ] **Step 1: 写入启动恢复测试**

插入 `source_action=scraper-job:*` 且状态为 `failed` 的历史确认事件，以及一个普通失败事件；运行恢复后断言前者被删除、后者仍按原规则恢复或等待。

- [ ] **Step 2: 实现定向清理**

在 `recover_monitor_change_events()` 的恢复事务开头删除 `source_action LIKE 'scraper-job:%' AND status='failed' AND needs_reconcile=0` 的历史事件，不把删除数量计为重新排队数量。

- [ ] **Step 3: 运行精准同步定向测试**

Run: `PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m unittest tests.test_scraper_monitor_sync`

Expected: 全部通过。

### Task 4: 完整验证与交接

**Files:**
- Modify: `docs/superpowers/handoff.md`

- [ ] **Step 1: 运行完整测试**

Run: `PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m unittest discover -s tests`

Expected: 全部通过。

- [ ] **Step 2: 运行语法和差异检查**

Run: `PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m compileall app main.py`

Run: `git diff --check`

Expected: 两项退出码均为 0。

- [ ] **Step 3: 更新交接记录**

在 `docs/superpowers/handoff.md` 末尾记录路径层边界、一次性失败日志语义、测试结果和 Docker/真实 115 验证状态，不修改版本号，不提交、不推送。
