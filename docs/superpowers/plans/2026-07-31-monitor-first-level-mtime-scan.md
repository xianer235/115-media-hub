# 文件夹监控首层修改时间校验实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 将文件夹监控的目录时间剪枝改为固定读取监控根目录第一层，并且只跳过时间未变化、没有待补扫状态的第一层文件夹。

**Architecture:** 在 `monitor_dirs` 中新增与旧目录内部汇总时间分离的 `entry_modified` 字段，保存第一层文件夹条目自身时间。扫描根目录时逐个判断第一层文件夹；变化分支加入带首层基线的队列并完整递归，明确的 Webhook/资源局部刷新和关闭跳过开关时不应用首层剪枝。

**Tech Stack:** Python 3、FastAPI、SQLite、`unittest`、原生 JavaScript/HTML 模板

---

## 文件结构

- 修改 `app/db.py`：创建和迁移 `monitor_dirs.entry_modified`。
- 修改 `app/services/monitor.py`：维护首层条目基线，移除父目录最大时间和深层目录剪枝，保留失败补扫及缓存清理语义。
- 修改 `app/core.py`：监控汇总日志展示首层扫描统计；目录列表继续返回兼容的旧汇总时间和逐项时间。
- 修改 `tests/test_monitor_dir_rescan.py`：覆盖迁移、首层逐项判断、变化分支完整递归、全量恢复、失败与缺失。
- 修改 `templates/partials/modals/monitor.html`：说明只判断第一层以及关闭开关后的恢复方法。
- 修改 `CHANGELOG.md`：记录用户可见的监控行为修复。
- 修改 `docs/superpowers/handoff.md`：记录实现、验证结果和后续真实 115 验证事项。

### Task 1: 增加首层条目时间状态

**Files:**
- Modify: `app/db.py:136-143,388-403`
- Modify: `app/services/monitor.py:59-127,225-251`
- Test: `tests/test_monitor_dir_rescan.py:79-135,225-256`

- [x] **Step 1: 扩展测试辅助函数并写迁移失败测试**

让 `_insert_monitor_dir()` 接受 `entry_modified`，让 `_fetch_monitor_dir()` 返回四列，并要求旧数据库迁移后包含新字段且默认值为空：

```python
def _insert_monitor_dir(
    self,
    dir_rel_path: str,
    *,
    remote_modified: str,
    entry_modified: str = "",
    needs_rescan: int = 0,
    missing_confirmations: int = 0,
) -> None:
    with sqlite3.connect(self.db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO monitor_dirs(
                task_name, dir_rel_path, remote_modified, entry_modified,
                needs_rescan, missing_confirmations
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                TASK_NAME,
                dir_rel_path,
                remote_modified,
                entry_modified,
                needs_rescan,
                missing_confirmations,
            ),
        )

def _fetch_monitor_dir(self, dir_rel_path: str):
    with sqlite3.connect(self.db_path) as conn:
        return conn.execute(
            """
            SELECT remote_modified, entry_modified, needs_rescan, missing_confirmations
            FROM monitor_dirs
            WHERE task_name = ? AND dir_rel_path = ?
            """,
            (TASK_NAME, dir_rel_path),
        ).fetchone()
```

迁移测试新增：

```python
conn.execute(
    """
    INSERT INTO monitor_dirs(task_name, dir_rel_path, remote_modified)
    VALUES (?, ?, ?)
    """,
    (TASK_NAME, "Legacy", "2026-05-23 01:00:00"),
)
conn.commit()

# db.ensure_db() 迁移后
self.assertIn("entry_modified", columns)
with sqlite3.connect(legacy_db_path) as conn:
    default_value = conn.execute(
        "SELECT entry_modified FROM monitor_dirs WHERE dir_rel_path = 'Legacy'"
    ).fetchone()
self.assertEqual(default_value, ("",))
```

- [x] **Step 2: 运行测试确认失败**

Run:

```bash
.venv/bin/python -m unittest tests.test_monitor_dir_rescan.MonitorDirRescanTest.test_monitor_dir_migration_adds_rescan_columns -v
```

Expected: FAIL，`entry_modified` 不在 `monitor_dirs` 字段集合中。

- [x] **Step 3: 实现 SQLite 创建和增量迁移**

新表结构加入：

```sql
entry_modified TEXT NOT NULL DEFAULT ''
```

旧表迁移加入：

```python
if "entry_modified" not in monitor_dir_columns:
    cursor.execute("ALTER TABLE monitor_dirs ADD COLUMN entry_modified TEXT NOT NULL DEFAULT ''")
```

保持迁移值为空字符串，不从旧 `remote_modified` 推导，确保升级后第一轮不能错误跳过。

- [x] **Step 4: 让目录状态读写完整保留新字段**

`_load_monitor_dir_state()` 返回：

```python
{
    "exists": True,
    "remote_modified": str(row[0] or ""),
    "entry_modified": str(row[1] or ""),
    "needs_rescan": bool(int(row[2] or 0)),
    "missing_confirmations": max(0, int(row[3] or 0)),
}
```

将 `_mark_monitor_dir_success()` 改为接受可选首层时间：

```python
def _mark_monitor_dir_success(
    cursor: sqlite3.Cursor,
    task_name: str,
    dir_rel_path: str,
    remote_modified: str,
    entry_modified: Optional[str] = None,
) -> None:
    state = _load_monitor_dir_state(cursor, task_name, dir_rel_path)
    next_entry_modified = (
        state["entry_modified"]
        if entry_modified is None
        else str(entry_modified or "")
    )
```

写回时同时包含 `entry_modified`；`_mark_monitor_dir_dirty()` 和 `_bump_missing_monitor_dir()` 也必须从旧状态原样写回该字段，不能因 `INSERT OR REPLACE` 清空成功基线。

- [x] **Step 5: 运行迁移和现有监控测试**

Run:

```bash
.venv/bin/python -m unittest tests.test_monitor_dir_rescan -v
```

Expected: PASS，现有断言已更新为四列状态。

- [ ] **Step 6: 提交状态迁移**

```bash
git add app/db.py app/services/monitor.py tests/test_monitor_dir_rescan.py
git commit -m "增加监控首层目录时间状态"
```

### Task 2: 用首层逐项判断替换父目录汇总剪枝

**Files:**
- Modify: `app/services/monitor.py:351-551`
- Test: `tests/test_monitor_dir_rescan.py:258-310`

- [x] **Step 1: 写父目录最大值不变的失败测试**

建立两个第一层文件夹：`SeasonA` 仍为最大时间且未变化，`SeasonB` 的时间从更早值变化但仍小于 `SeasonA`。根目录旧汇总值和本轮汇总值保持相同：

```python
def test_first_level_change_is_scanned_when_parent_max_time_is_unchanged(self):
    task = self._task(sync_clean=True, skip_by_dir_mtime=True)
    self._insert_monitor_dir("", remote_modified="2026-07-31 12:00:00")
    self._insert_monitor_dir(
        "SeasonA",
        remote_modified="2026-07-31 12:00:00",
        entry_modified="2026-07-31 12:00:00",
    )
    self._insert_monitor_dir(
        "SeasonB",
        remote_modified="2026-07-31 09:00:00",
        entry_modified="2026-07-31 09:00:00",
    )

    call_log = self._run_monitor(
        {
            "/115/Library": (
                "2026-07-31 12:00:00",
                [
                    _dir_item("SeasonA", "2026-07-31 12:00:00"),
                    _dir_item("SeasonB", "2026-07-31 11:00:00"),
                ],
            ),
            "/115/Library/SeasonB": (
                "2026-07-31 11:00:00",
                [_file_item("B01.mkv", "2026-07-31 11:00:00")],
            ),
        },
        task=task,
    )

    self.assertEqual(call_log, ["/115/Library", "/115/Library/SeasonB"])
```

- [x] **Step 2: 写变化分支必须完整递归的失败测试**

让第一层 `SeriesA` 发生变化，但第二层 `Season01` 的旧时间等于当前时间。预期仍读取第二层：

```python
def test_changed_first_level_branch_does_not_prune_deeper_directories(self):
    task = self._task(sync_clean=True, skip_by_dir_mtime=True)
    self._insert_monitor_dir(
        "SeriesA",
        remote_modified="2026-07-30 10:00:00",
        entry_modified="2026-07-30 10:00:00",
    )
    self._insert_monitor_dir(
        "SeriesA/Season01",
        remote_modified="2026-07-31 10:00:00",
    )

    call_log = self._run_monitor(
        {
            "/115/Library": (
                "2026-07-31 11:00:00",
                [_dir_item("SeriesA", "2026-07-31 11:00:00")],
            ),
            "/115/Library/SeriesA": (
                "2026-07-31 10:00:00",
                [_dir_item("Season01", "2026-07-31 10:00:00")],
            ),
            "/115/Library/SeriesA/Season01": (
                "2026-07-31 10:00:00",
                [_file_item("E01.mkv", "2026-07-31 10:00:00")],
            ),
        },
        task=task,
    )

    self.assertEqual(
        call_log,
        [
            "/115/Library",
            "/115/Library/SeriesA",
            "/115/Library/SeriesA/Season01",
        ],
    )
```

- [x] **Step 3: 运行两个测试确认失败**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_monitor_dir_rescan.MonitorDirRescanTest.test_first_level_change_is_scanned_when_parent_max_time_is_unchanged \
  tests.test_monitor_dir_rescan.MonitorDirRescanTest.test_changed_first_level_branch_does_not_prune_deeper_directories -v
```

Expected: 第一个测试只记录根目录，第二个测试不读取 `Season01`。

- [x] **Step 4: 重构扫描队列和首层判断**

队列项携带第一层文件夹自身时间；根目录和深层目录使用 `None`：

```python
queue: List[Tuple[str, str, Optional[str]]] = [
    (start_remote_path, start_local_rel, None)
]

remote_dir, local_dir_rel, first_level_entry_modified = queue.pop(0)
```

删除访问目录后基于 `dir_state["remote_modified"] >= modified` 的整体提前跳过。只在处理任务根目录的直接文件夹时执行：

```python
is_first_level_dir = dir_rel == ""
allow_first_level_skip = (
    is_first_level_dir
    and task["skip_by_dir_mtime"]
    and not refresh_source_label
)

if (
    allow_first_level_skip
    and modified_at
    and child_state["entry_modified"]
    and child_state["entry_modified"] == modified_at
    and not child_has_dirty
):
    await mark_cached_dir_as_seen(conn, task_name, item_local_rel)
    continue

queue.append(
    (
        item_remote_path,
        item_local_rel,
        modified_at if is_first_level_dir else None,
    )
)
```

深层目录始终进入队列。目录成功处理时把队列携带的首层时间传入 `_mark_monitor_dir_success()`；`None` 表示保留原首层基线。

- [x] **Step 5: 更新队列回退路径**

Webhook/资源起始目录暂不可见、回退父目录时，插入三元组：

```python
queue.insert(0, (start_remote_path, start_local_rel, None))
```

明确刷新请求通过 `refresh_source_label` 禁止首层跳过，继续只扫描目标祖先链和目标子树。

- [x] **Step 6: 运行首层扫描测试**

Run:

```bash
.venv/bin/python -m unittest tests.test_monitor_dir_rescan -v
```

Expected: PASS；父目录最大值不再参与跳过，变化分支读取所有深层目录。

- [ ] **Step 7: 提交扫描重构**

```bash
git add app/services/monitor.py tests/test_monitor_dir_rescan.py
git commit -m "重构监控首层目录扫描"
```

### Task 3: 补齐基线重建、关闭开关和缺失补扫

**Files:**
- Modify: `app/services/monitor.py:143-251,416-546`
- Modify: `app/core.py:6665-6670`
- Test: `tests/test_monitor_dir_rescan.py`

- [x] **Step 1: 写旧缓存首次重建和关闭开关测试**

覆盖 `entry_modified` 为空时，即使旧 `remote_modified` 相同也必须扫描；关闭开关时，即使首层基线相同也必须完整递归。两次成功扫描后分别断言 `entry_modified` 已刷新：

```python
self.assertEqual(
    self._fetch_monitor_dir("SeriesA")[1],
    "2026-07-31 12:00:00",
)
```

- [x] **Step 2: 写空时间、时间回退和 dirty 覆盖测试**

分别让第一层当前时间为空、当前时间小于历史基线、后代 `needs_rescan=1`，三种情况都必须进入分支。时间回退测试必须证明判断使用 `==` 而不是 `>=`。

- [x] **Step 3: 写普通第一层目录缺失两次的测试**

不预设 `needs_rescan`，只给第一层目录写入 `entry_modified`。第一次成功根目录列表缺失后断言状态为 dirty 且 `missing_confirmations=1`；第二次仍缺失后断言整个状态子树删除。

- [x] **Step 4: 运行新增测试确认失败**

Run:

```bash
.venv/bin/python -m unittest tests.test_monitor_dir_rescan -v
```

Expected: 新增的普通缺失目录测试失败，因为当前实现只枚举 dirty 子目录；其余失败应与尚未完整实现的首层基线规则对应。

- [x] **Step 5: 将首层已跟踪目录纳入缺失确认**

新增查询任务所有已建立 `entry_modified` 的第一层目录辅助函数，并与 `_list_dirty_direct_children()` 的结果合并：

```python
def _list_tracked_first_level_dirs(
    cursor: sqlite3.Cursor,
    task_name: str,
) -> List[str]:
    cursor.execute(
        """
        SELECT dir_rel_path
        FROM monitor_dirs
        WHERE task_name = ? AND COALESCE(entry_modified, '') <> ''
        """,
        (task_name,),
    )
    return sorted(
        {
            normalize_relative_path(str(row[0] or "")).split("/", 1)[0]
            for row in cursor.fetchall()
            if normalize_relative_path(str(row[0] or ""))
        }
    )
```

仅在处理监控根目录时合并该集合。出现的目录重置缺失次数；未出现的目录调用 `_bump_missing_monitor_dir()`，第二次确认后删除状态子树。

- [x] **Step 6: 增加首层统计日志**

`stats` 新增：

```python
"scanned_branches": 0,
"skipped_first_level_dirs": 0,
"rescan_branches": 0,
```

根目录决定队列时更新统计；`write_monitor_task_summary()` 使用 `.get()` 输出：

```python
f"首层汇总: 深扫分支 {stats.get('scanned_branches', 0)} | "
f"跳过文件夹 {stats.get('skipped_first_level_dirs', 0)} | "
f"待补扫分支 {stats.get('rescan_branches', 0)}"
```

- [x] **Step 7: 运行监控与数据库相关测试**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_monitor_dir_rescan \
  tests.test_tree_streaming_sync \
  tests.test_db_lock_retry -v
```

Expected: PASS。

- [ ] **Step 8: 提交边界行为**

```bash
git add app/services/monitor.py app/core.py tests/test_monitor_dir_rescan.py
git commit -m "完善监控首层补扫与缺失处理"
```

### Task 4: 更新用户说明并完成验证

**Files:**
- Modify: `templates/partials/modals/monitor.html:48-53`
- Modify: `CHANGELOG.md`
- Modify: `docs/superpowers/handoff.md`

- [x] **Step 1: 更新监控弹窗说明**

帮助文案改为：

```text
开启后，每次读取监控目录第一层，只深入扫描新增、发生变化或待补扫的第一层文件夹。更深层变化若没有同步更新第一层文件夹时间，可能无法自动发现；需要关闭本开关后手动运行一次完整扫描。读取失败的目录会自动保留待补扫状态。
```

备注压缩为移动端可读的一句：

```text
备注：只按第一层判断；深层遗漏时关闭本开关后手动完整扫描。
```

- [x] **Step 2: 更新变更记录和 handoff**

在当前版本的 `CHANGELOG.md` 增加首层逐项判断、变化分支完整递归和关闭开关恢复说明。`docs/superpowers/handoff.md` 追加时间、分支、实现内容、实际验证命令和下一步真实 115 观察事项。

- [x] **Step 3: 运行完整自动验证**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache \
  .venv/bin/python -m compileall app main.py
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
git diff --check
```

Expected: `compileall` 成功、完整 unittest 全部 PASS、`git diff --check` 无输出。

- [x] **Step 4: 检查前端模板和工作区差异**

Run:

```bash
rg -n "只按第一层判断|深层遗漏" templates/partials/modals/monitor.html CHANGELOG.md
git status --short
git diff --stat
```

Expected: 新说明同时出现在监控弹窗和变更记录中；状态只包含本计划列出的文件。

- [ ] **Step 5: 提交实现文档**

```bash
git add templates/partials/modals/monitor.html CHANGELOG.md docs/superpowers/handoff.md
git commit -m "更新监控首层扫描说明"
```

- [ ] **Step 6: 最终提交复核**

Run:

```bash
git status --short --branch
git log -4 --oneline
```

Expected: 工作区干净，最近提交依次覆盖状态迁移、扫描重构、边界处理和用户说明。
