# 刮削精准同步日志明细 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在监控日志中可信地列出刮削精准同步实际删除和生成的本地 STRM，并用一行摘要表示文件夹操作。

**Architecture:** `monitor_changes.py` 在单个事件成功提交后返回结构化 `change_details`，文件事件保存有序的删除/生成项，文件夹事件只保存本地目录映射与实际计数。`monitor.py` 将这些内部结果格式化为现有监控日志；不修改数据库、公开接口或前端。

**Tech Stack:** Python 3.9、SQLite、FastAPI 服务层、`unittest`/`unittest.mock`

---

### Task 1: 返回已提交的结构化变更明细

**Files:**
- Modify: `app/services/monitor_changes.py`
- Test: `tests/test_scraper_monitor_sync.py`

- [x] **Step 1: 在现有三文件批量改名测试中加入失败断言**

在 `test_real_batch_plan_canonicalizes_relative_paths_and_renames_three_nested_files_without_remote_listing` 中断言 `result["change_details"]` 有三个文件事件，每个事件严格包含删除旧本地 `.strm`、生成新本地 `.strm` 两项。

```python
expected_details = [
    {
        "kind": "file",
        "changes": [
            {
                "action": "delete",
                "path": f"媒体库/一级/二级/{action['old_name']}.strm",
            },
            {
                "action": "generate",
                "path": f"媒体库/一级/二级/{action['new_name']}.strm",
            },
        ],
    }
    for action in plan["actions"]
]
self.assertEqual(result["change_details"], expected_details)
```

- [x] **Step 2: 扩展必要的安全回归断言**

在现有共享 STRM 删除测试中断言没有 `delete` 明细；在现有文件夹写入失败回滚测试中断言 `change_details == []`；在现有文件夹重命名测试中断言只返回一条 `kind=folder` 摘要且不包含内部文件列表。

```python
self.assertFalse(
    any(
        change.get("action") == "delete"
        for detail in result["change_details"]
        for change in detail.get("changes", [])
    )
)
self.assertEqual(result["change_details"], [])
folder_detail = result["change_details"][0]
self.assertEqual(folder_detail["kind"], "folder")
self.assertNotIn("changes", folder_detail)
```

- [x] **Step 3: 运行测试确认红灯**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_scraper_monitor_sync.ScraperMonitorSyncTest.test_real_batch_plan_canonicalizes_relative_paths_and_renames_three_nested_files_without_remote_listing \
  tests.test_scraper_monitor_sync.ScraperMonitorSyncTest.test_delete_keeps_shared_strm_referenced_by_another_monitor_task \
  tests.test_scraper_monitor_sync.ScraperMonitorSyncTest.test_indexed_folder_write_failure_restores_old_strms_and_removes_partial_new_files \
  tests.test_scraper_monitor_sync.ScraperMonitorSyncTest.test_folder_rename_removes_only_indexed_strm_and_keeps_metadata
```

Expected: FAIL because `change_details` is absent.

- [x] **Step 4: 实现事件明细构建和提交后汇总**

在 `monitor_changes.py` 增加小型纯函数，根据事件计划、实际统计和有效上下文创建明细：

```python
def _build_committed_change_detail(
    plan: Dict[str, Any],
    stats: Dict[str, Any],
    *,
    effective_new_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    old_context = plan.get("old_context") if isinstance(plan.get("old_context"), dict) else {}
    new_context = effective_new_context or (
        plan.get("new_context") if isinstance(plan.get("new_context"), dict) else {}
    )
    if plan.get("is_dir"):
        return {
            "kind": "folder",
            "operation": str(plan.get("operation", "") or ""),
            "old_path": str(old_context.get("local_rel_path", "") or ""),
            "new_path": str(new_context.get("local_rel_path", "") or ""),
            "deleted": int(stats.get("deleted", 0) or 0),
            "generated": int(stats.get("generated", 0) or 0),
        }
    changes = []
    if int(stats.get("deleted", 0) or 0) > 0 and old_context:
        changes.append({"action": "delete", "path": f"{old_context['local_rel_path']}.strm"})
    if int(stats.get("generated", 0) or 0) > 0 and new_context:
        changes.append({"action": "generate", "path": f"{new_context['local_rel_path']}.strm"})
    return {"kind": "file", "changes": changes} if changes else {}
```

`_apply_precise_event` 和 `_reconcile_event` 在所有文件操作完成后把该明细放入本事件 `stats`。`process_monitor_change_events` 初始化 `change_details=[]`，并且只在 `conn.commit()` 成功后追加非空明细；异常分支回滚且不追加。

- [x] **Step 5: 运行四项定向测试确认转绿**

重复 Step 3 命令。Expected: 4 tests PASS。

### Task 2: 输出本地路径日志

**Files:**
- Modify: `app/services/monitor.py`
- Test: `tests/test_scraper_monitor_sync.py`

- [x] **Step 1: 扩展现有变更任务日志测试**

让 `test_monitor_change_task_summary_reports_manual_required_count` 的模拟结果包含两个文件明细和一个文件夹摘要，断言日志顺序为删除、生成、文件夹摘要、汇总，并断言换行路径被压成单行。

```python
change_details = [
    {
        "kind": "file",
        "changes": [
            {"action": "delete", "path": "媒体库/旧\n名称.mkv.strm"},
            {"action": "generate", "path": "媒体库/新名称.mkv.strm"},
        ],
    },
    {
        "kind": "folder",
        "operation": "move",
        "old_path": "媒体库/旧目录",
        "new_path": "媒体库/新目录",
        "deleted": 2,
        "generated": 2,
    },
]
```

- [x] **Step 2: 运行日志测试确认红灯**

Run:

```bash
.venv/bin/python -m unittest tests.test_scraper_monitor_sync.ScraperMonitorSyncTest.test_monitor_change_task_summary_reports_manual_required_count
```

Expected: FAIL because the detail lines are not logged.

- [x] **Step 3: 增加纯格式化辅助函数并写入日志**

在 `monitor.py` 增加路径单行化和文件夹标签函数；遍历 `change_details` 后再写现有汇总：

```python
def _single_line_monitor_change_path(value: Any) -> str:
    normalized = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    return " ".join(part.strip() for part in normalized.split("\n") if part.strip())

async def _write_monitor_change_details(details: Any) -> None:
    raw_details = details if isinstance(details, list) else []
    for detail in raw_details:
        if not isinstance(detail, dict):
            continue
        if detail.get("kind") == "file":
            changes = detail.get("changes", [])
            for change in changes if isinstance(changes, list) else []:
                if not isinstance(change, dict):
                    continue
                action = str(change.get("action", "") or "")
                label = {"delete": "删除 STRM", "generate": "生成 STRM"}.get(action, "")
                path = _single_line_monitor_change_path(change.get("path"))
                if not label or not path:
                    continue
                level = "info" if action == "delete" else "success"
                await write_monitor_log(f"{label}: {path}", level)
            continue
        if detail.get("kind") != "folder":
            continue
        operation = str(detail.get("operation", "") or "").strip().lower()
        old_path = _single_line_monitor_change_path(detail.get("old_path"))
        new_path = _single_line_monitor_change_path(detail.get("new_path"))
        deleted = max(0, int(detail.get("deleted", 0) or 0))
        generated = max(0, int(detail.get("generated", 0) or 0))
        if old_path and new_path:
            label = "文件夹复制" if operation == "copy" else "文件夹变更"
            subject = f"{old_path} -> {new_path}"
            counts = f"生成 {generated}" if operation == "copy" else f"删除 {deleted}，生成 {generated}"
        elif old_path:
            label = "文件夹删除"
            subject = old_path
            counts = f"删除 {deleted}"
        elif new_path:
            label = "文件夹新增"
            subject = new_path
            counts = f"生成 {generated}"
        else:
            continue
        await write_monitor_log(f"{label}: {subject}（{counts}）", "info")
```

未知 action、空路径或非字典条目直接跳过，避免输出不可信日志。

- [x] **Step 4: 运行日志测试确认转绿**

重复 Step 2 命令。Expected: PASS。

### Task 3: 同步版本说明并验证

**Files:**
- Modify: `version.json`
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `docs/superpowers/handoff.md`
- Modify: `docs/superpowers/specs/2026-08-10-scraper-monitor-change-log-design.md`

- [x] **Step 1: 更新版本元数据到 0.5.13**

将 `version.json` 更新为 `0.5.13` 和 `2026-08-10T00:00:00+08:00`，说明精准同步日志现在列出本地文件明细并汇总文件夹操作；在 CHANGELOG、README 和 handoff 同步相同版本与行为。设计说明记录最终实现口径，不增加无关变更。

- [x] **Step 2: 运行必要的定向测试**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_scraper_monitor_sync.ScraperMonitorSyncTest.test_real_batch_plan_canonicalizes_relative_paths_and_renames_three_nested_files_without_remote_listing \
  tests.test_scraper_monitor_sync.ScraperMonitorSyncTest.test_delete_keeps_shared_strm_referenced_by_another_monitor_task \
  tests.test_scraper_monitor_sync.ScraperMonitorSyncTest.test_indexed_folder_write_failure_restores_old_strms_and_removes_partial_new_files \
  tests.test_scraper_monitor_sync.ScraperMonitorSyncTest.test_folder_rename_removes_only_indexed_strm_and_keeps_metadata \
  tests.test_scraper_monitor_sync.ScraperMonitorSyncTest.test_monitor_change_task_summary_reports_manual_required_count
```

Expected: 5 tests PASS。

- [x] **Step 3: 运行项目级静态检查**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m compileall app main.py
.venv/bin/python -m json.tool version.json
git diff --check
```

Expected: all commands exit 0。没有 JS 改动，因此不运行 `node --check`。按用户要求不额外运行完整测试；现有 253 项完整测试已在 `0.5.12` 精准同步发布时通过，本次只运行受影响路径的必要回归。

- [x] **Step 4: 保持实现和版本改动未提交、未推送**

检查 `git status --short --branch`，确认只有本计划、代码、测试和发布说明变更。除已按设计流程提交的设计说明外，不创建实现提交，不推送，等待用户后续指令。
