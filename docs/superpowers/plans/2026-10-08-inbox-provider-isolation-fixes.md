# 接收夹「按网盘隔离」遗留问题修复计划

> **执行者须知**：本计划面向执行本方案的工程师 / 低思考模型，请严格照做，不要自行决策、
> 不要扩大范围；遇到方案未覆盖但必须决定的点，停下来问用户，不要猜。
> 建议配合 `superpowers:executing-plans`（本会话批量执行 + 检查点）或
> `superpowers:subagent-driven-development`（每个任务换一个执行者 + 两段评审）。
>
> 日期 2026-10-08。版本基线 `0.13.4`（`version.json` 为准）。
> 本计划默认**不提交、不推送、不改 `version.json` / `CHANGELOG.md` / `README.md`**；
> 每个任务末尾的提交步骤需用户明确授权后才执行。

**目标（Goal）**：把接收夹从「配置按网盘隔离、状态与触发仍是全局单例」修成真正的按网盘隔离，
并补上「文件落盘后才整理」的宽限重扫，让「保存进接收夹」稳定等于「会被整理」。

**架构（Architecture）**：不改数据模型主干。触发侧把全局单例状态改成「按接收夹任务名分桶」；
状态侧把 `_build_inbox_status` 补成每盘一份完整快照（含最近运行、最近接收、运行 / 中断标志），
前端保持现有合并方式即可生效；统计侧给 `resource_jobs` 补一列 `inbox_task_name`，把
「保存到接收夹」的归属从布尔标记升级成任务名。

**技术栈（Tech Stack）**：Python 3 / FastAPI（后端）、原生 JS（`static/js/index.js` +
`static/js/modules/resource/*`）、SQLite（`app/db.py`）、`unittest` + `scripts/check.sh`。

**Spec / 依据**：`docs/superpowers/specs/2026-09-23-folder-monitor-workflow-design.md`、
`docs/superpowers/specs/2026-09-26-folder-receive-monitor-runtime-design.md`、
`docs/superpowers/conventions.md`（接收夹口径）、
`docs/superpowers/plans/2026-10-07-inbox-multiprovider-monitor-subscription.md`（上一批解耦）。
本计划同时充当本轮缺陷清单。

## 全局约束（Global Constraints）

- 接收夹定义：`monitor_tasks` 里 `task_type == "inbox"` 的任务，**每个网盘最多一个**，provider 默认 `"115"`。
- 接收夹只做**同盘**分发；只有 115 且目标命中某个目录同步任务扫描范围时才刷 STRM。
- 自动整理入口只有两个：接收夹（分类归档）、订阅（电视剧新集原地改名）；本计划不新增第三个入口。
- 路径口径：`savepath` / `distribute_targets` 是**网盘相对路径**；任务上的 `scan_path` 是**带挂载前缀的远程路径**（如 `/115/接收`）。
- 验证统一用项目本地环境：`.venv/bin/python`、`scripts/check.sh ...`、`PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache`。
- 搜索长行文件（`handoff.md` / `handoff-archive.md` / `CHANGELOG.md`）必须加 `--max-columns 300`。
- 不引入新的命名规则、不重构整理引擎（复用 `app/services/scraper.py`）。
- 改完同步文档：`docs/superpowers/modules.md`、`state.md`、`handoff.md`（并跑 `scripts/rotate_handoff.py`）。

---

## 一、问题清单（审查结论，按影响排序）

### A. 触发时机：会出现「存进接收夹但不整理」

| ID | 问题 | 证据 |
| --- | --- | --- |
| A1 | **转存 / 离线任务提交成功后立刻（默认 4 秒）登记整理，而 115 / 夸克的转存是异步任务**；整理扫到空就直接收尾，**没有宽限重扫**，也不会自动补跑。 | `app/services/resource.py:1004-1008`、`static/js/modules/resource/folder-api.js:990`（默认 4 秒）、`app/services/quick_import.py:1378-1381`（扫空即 `finish_run("completed", 0, 0, ...)`） |
| A2 | 订阅链路已有同类宽限（30 秒 / 每 10 秒 / 最多 3 次），**接收夹没有对标实现**。 | 对比 `app/services/subscription_task_runner.py:897` `_wait_for_subscription_offline_staging_meta` |
| A3 | 115 离线「完成」早于目录列表（同一根因的历史案例），接收夹侧的触发点同样没有等待。 | `app/services/resource.py:196-225`（status==2 直接 `notify_quick_import("offline")`） |
| A4 | 手工把文件放进接收夹（115 / 夸克客户端、面板文件管理、其他工具）**永远不会触发**：接收夹被显式排除在变更同步之外，自身也没有目录轮询。 | `app/services/monitor_changes.py:179-181` |
| A5 | 空跑也写一条「已完成」运行记录，掩盖 A1；`summary` 只写「接收夹没有可整理的内容」。 | `app/services/quick_import.py:1379-1381` |

### B. 触发粒度：没按接收夹隔离

| ID | 问题 | 证据 |
| --- | --- | --- |
| B1 | `/monitor/start` 对 inbox 任务**丢弃请求里的任务名**，直接全局 `notify_quick_import("manual")`；`run_quick_import` 遍历所有启用接收夹。 | `app/routes/monitor.py:498-504`、`app/services/quick_import.py:2048-2055` |
| B2 | `/monitor/stop` 走全局 `request_quick_import_cancel()`，在一个盘的卡片点「中断」会打断别的盘正在跑的整理。 | `app/routes/monitor.py:531-538`、`app/services/quick_import.py:83-95` |
| B3 | 定时是「每任务判断、全局执行」：每个接收夹有自己的 `cron_minutes` 与 `monitor_next_run[name]`，到点却调全局 `_run_inbox_cron_import()`，周期短的盘把其他盘一起拖着超频跑。 | `app/startup.py:178-186`、`app/startup.py:53-59` |
| B4 | 触发协调状态是单个全局 worker + 单个 pending 标记，无法表达「只有夸克那份待跑」。 | `app/services/quick_import.py:70-135` |
| B5 | 整理全程只持有一个进程级锁并**顺序遍历所有接收夹**，一个盘慢会压住其他盘的「立即整理」，并回「已有接收夹整理在执行」。 | `app/services/quick_import.py:2046-2068` |
| B6 | `/scraper/quick-import/run` 只支持 `sub_path`，**没有任务名参数**，CLI / 脚本无法只跑某一个接收夹。 | `app/routes/scraper.py:391-409` |

### C. 状态聚合：所有卡片显示同一份状态（用户最初报告的现象）

| ID | 问题 | 证据 |
| --- | --- | --- |
| C1 | `get_quick_import_status()` 顶层 `latest` / `latest_detail` / `recent_jobs` / `recent_job_count_24h` / `running` / `pending_rerun` **是全局或第一个接收夹**的；`latest` 来自无过滤的 `list_quick_import_runs(1)`，`recent_*` 用 `inbox_tasks[0]` 的路径。 | `app/services/quick_import.py:748-775` |
| C2 | `_build_inbox_status()` 只产出 `task_name / provider / config_error / targets / active_run`，**缺 `latest` / `latest_detail` / `recent_jobs` / `recent_job_count_24h` / `running` / `cancelling` / `pending_rerun`**。 | `app/services/quick_import.py:720-745` |
| C3 | 前端 `inboxStatusForTask()` 用 `{ ...cache, ...match }` 合并，match 里没有的字段由全局值透传 → 卡片活动行、卡片展开说明、编辑弹窗三处都显示同一次运行 / 同一个计数；新建任务时（无 match）更是整份全局状态外泄。 | `static/js/index.js:3786-3793`、`3795-3818`、`5218-5223`、`3694-3760` |
| C4 | 卡片的「运行中 / 中断」按钮状态取自全局锁，A 盘在跑时 B 盘也显示运行中并能点中断；判定按钮动作也用全局值。 | `static/js/index.js:5326-5341`、`3843-3855` |

### D. 统计归属：同名路径跨盘串账

| ID | 问题 | 证据 |
| --- | --- | --- |
| D1 | `resource_jobs` 表没有 provider / 接收夹标识，落库只写布尔 `quick_import_inbox: 1`，无法回答「这是哪个接收夹收到的」。 | `app/db.py:201-222`、`app/routes/resource.py:1177`、`app/routes/resource.py:1330`、`app/routes/monitor.py:160` |
| D2 | `list_inbox_recent_jobs` / `count_inbox_recent_jobs` 只按 `savepath` 前缀匹配，115 与夸克都用 `/接收` 时互相串账（夸克那份会算进 115 的「最近接收 24 小时 N 个」）。 | `app/services/quick_import.py:672-717` |
| D3 | `is_quick_import_savepath()` 没有 provider 维度，且 `app/routes/resource.py` 两处调用连 provider 都没传（「任一启用接收夹命中即算命中」）。 | `app/services/quick_import.py:317-341`、`app/routes/resource.py:1143`、`app/routes/resource.py:1316` |
| D4 | `find_existing_resource_job` 只按 `savepath` 去重，同一链接导到不同网盘的同名目录会误判「已有导入记录」。 | `app/resource_jobs.py:146-168` |

### E. 参数、通知、能力缺口

| ID | 问题 | 证据 |
| --- | --- | --- |
| E1 | `_inbox_delay_seconds()` 取**第一个**接收夹的 `inbox_idle_seconds`，每盘配的静默窗口实际不生效。 | `app/services/quick_import.py:140-145` |
| E2 | 接收夹整理**不推通知**：`push_monitor_success_notification` 只在扫描链路调用，整理成功 / 失败都只在日志里。 | `app/services/monitor.py:1281`、`app/services/notify.py:908-916` |
| E3 | 多季合集（`S01-S03`）不自动拆分，只留在接收夹等人工处理（明确的能力缺口，非缺陷）。 | `app/services/quick_import.py:1445-1457` |
| E4 | 接收夹一律不能删除（服务端 400 + 卡片无删除按钮），用户自建的非 115 接收夹也删不掉。 | `app/routes/monitor.py:556-570`、`state.md` 待办 |
| E5 | CLI 无接收夹维度：`quick-import-status` 只打印第一个盘的 `inbox_path` / `targets` / `latest`；且它读的 `targets.*.task_name` 字段在新结构里已不存在，永远打印「(未标注)」。 | `cli.py:940-960`、`app/services/quick_import.py:737-743` |
| E6 | 前端 `resolveResourceMonitorTaskMatch` 只按路径匹配，不看 `enabled`：禁用中的接收夹仍提示「保存完成后自动整理分发」，后端 `is_quick_import_savepath` 却会跳过未启用接收夹。 | `static/js/modules/resource/core.js:1882-1919`、`app/services/quick_import.py:328-337` |

### 汇总：问题 → 任务映射

| 任务 | 覆盖问题 |
| --- | --- |
| Task 1 接收夹落盘宽限重扫 | A1 A2 A3 A5（部分） |
| Task 2 触发 / 中断按接收夹 | B1 B2 B3 B4 B6 |
| Task 3 导入任务归属 + 最近接收统计 | D1 D2 D3 D4 |
| Task 4 状态按接收夹聚合 | C1 C2 C3 C4 |
| Task 5 每盘静默窗口 | E1（B3 收尾） |
| Task 6 落点提示与禁用态一致 | E6（A5 收尾） |
| Task 7 接收夹整理通知（**已取消**，E2 按「不推通知」口径关闭） | E2 |
| Task 8 CLI / 文档 / 待拍板项 | E3 E4 E5、A4 方案决策 |

覆盖不到但已记录：B5（并发模型）与 E4（删除接收夹）属于产品决策，见「五、待用户拍板」。

---

## 二、文件结构（改动落点）

- `app/services/quick_import.py`：触发状态、宽限重扫、按任务名运行 / 中断、每盘状态快照、每盘静默窗口。**本轮改动最大的文件。**
- `app/routes/monitor.py`：`/monitor/start`、`/monitor/stop` 传任务名；webhook 归属字段。
- `app/routes/scraper.py`：`/scraper/quick-import/run` 支持任务名。
- `app/routes/resource.py`：落点判定带 provider + 记录 `inbox_task_name`。
- `app/services/resource.py`：触发时带上接收夹任务名；延迟整理透传任务名。
- `app/resource_jobs.py`、`app/db.py`：`resource_jobs` 新增 `inbox_task_name` 列与查询条件。
- `app/startup.py`：接收夹定时触发带任务名。
- `static/js/index.js`：`inboxStatusForTask` 不再透传全局状态；按钮状态用每盘字段。
- `static/js/modules/resource/core.js`：导入落点提示区分「已停用接收夹」。
- `tests/test_quick_import.py`、`tests/test_quick_import_frontend.py`、`tests/test_resource_offline_completion.py`：回归用例。
- `docs/superpowers/{modules,conventions,state,handoff}.md`：文档同步。

---

## 三、任务分解

### Task 1：接收夹落盘宽限重扫（P0，先做这个）

**Files:**
- Modify: `app/services/quick_import.py`（常量区、`_list_inbox_children` 之后、`_run_inbox_quick_import` 的扫描段）
- Test: `tests/test_quick_import.py`

**Interfaces:**
- Produces: `INBOX_STAGING_GRACE_SECONDS: int = 30`、`INBOX_STAGING_RESCAN_INTERVAL_SECONDS: int = 10`、`INBOX_STAGING_MAX_ATTEMPTS: int = 3`
- Produces: `_wait_for_inbox_children(base_cid, provider, *, max_attempts=INBOX_STAGING_MAX_ATTEMPTS, interval_seconds=INBOX_STAGING_RESCAN_INTERVAL_SECONDS) -> List[Dict[str, Any]]`
- Consumes: `_list_inbox_children(base_cid, provider)`（已有）、`identify_scraper_batch_entries(provider, entries, *, base_cid, base_path, use_ai=True)`（已有，接受 `entries`）

- [ ] **Step 1: 写失败用例**

在 `tests/test_quick_import.py` 的 `MultiInboxFanoutTest` 之后新增：

```python
class InboxStagingGraceTest(unittest.TestCase):
    """转存/离线落盘滞后时，接收夹整理要先等一等再判定为空。"""

    def test_wait_for_inbox_children_rescans_until_content_appears(self):
        with mock.patch.object(
            quick_import, "_list_inbox_children", side_effect=[[], [], [{"id": "1", "name": "片名"}]]
        ) as lister, mock.patch.object(quick_import.time, "sleep") as sleeper:
            children = quick_import._wait_for_inbox_children("cid", "115")
        self.assertEqual([item["id"] for item in children], ["1"])
        self.assertEqual(lister.call_count, 3)
        self.assertEqual(sleeper.call_count, 2)

    def test_wait_for_inbox_children_gives_up_after_max_attempts(self):
        with mock.patch.object(quick_import, "_list_inbox_children", return_value=[]) as lister, \
                mock.patch.object(quick_import.time, "sleep"):
            children = quick_import._wait_for_inbox_children("cid", "115")
        self.assertEqual(children, [])
        self.assertEqual(lister.call_count, quick_import.INBOX_STAGING_MAX_ATTEMPTS)

    def test_empty_inbox_run_reports_staging_wait(self):
        cfg = MultiInboxFanoutTest._two_provider_cfg()
        inbox = core.get_inbox_task(cfg, "接收")
        with mock.patch.object(quick_import, "resolve_scraper_dest_folder_id", return_value="cid"), \
                mock.patch.object(quick_import, "_wait_for_inbox_children", return_value=[]), \
                mock.patch.object(quick_import, "_insert_quick_import_run", return_value=7), \
                mock.patch.object(quick_import, "create_monitor_run", return_value="run-1"), \
                mock.patch.object(quick_import, "start_monitor_run"), \
                mock.patch.object(quick_import, "finish_monitor_run"), \
                mock.patch.object(quick_import, "_finish_quick_import_run"):
            result = quick_import._run_inbox_quick_import(cfg, inbox)
        self.assertIn("已等待", result["summary"])
        self.assertEqual(result["moved"], [])
```

- [ ] **Step 2: 跑用例确认失败**

Run: `scripts/check.sh tests.test_quick_import`
Expected: FAIL，报 `_wait_for_inbox_children` / `INBOX_STAGING_MAX_ATTEMPTS` 不存在

- [ ] **Step 3: 加常量与宽限重扫 helper**

在 `app/services/quick_import.py` 常量区（`QUICK_IMPORT_DEFAULT_BATCH_PAUSE_SECONDS` 附近）加：

```python
# 接收夹整理前的落盘宽限：转存 / 离线任务返回成功时目录列表常常还没刷新，
# 与订阅链路的 SUBSCRIPTION_OFFLINE_STAGING_* 对齐——扫空时按下面的参数重扫。
INBOX_STAGING_GRACE_SECONDS = 30
INBOX_STAGING_RESCAN_INTERVAL_SECONDS = 10
INBOX_STAGING_MAX_ATTEMPTS = 3
```

在 `_list_inbox_children()` 之后加：

```python
def _wait_for_inbox_children(
    base_cid: str,
    provider: str,
    *,
    max_attempts: int = INBOX_STAGING_MAX_ATTEMPTS,
    interval_seconds: float = INBOX_STAGING_RESCAN_INTERVAL_SECONDS,
) -> List[Dict[str, Any]]:
    """列接收夹内容；扫空时在宽限期内重扫，返回最后一次结果（可能仍为空）。

    转存 / 115 离线任务返回成功时目录列表常常滞后，立刻整理会扫到空并直接收尾；
    这里最多重扫 ``max_attempts`` 次，由调用方决定空扫时怎么记日志。
    """
    attempts = max(1, int(max_attempts or 1))
    interval = max(0.0, float(interval_seconds or 0))
    children: List[Dict[str, Any]] = []
    for attempt in range(1, attempts + 1):
        children = _list_inbox_children(base_cid, provider)
        if children or attempt >= attempts:
            return children
        if interval > 0:
            time.sleep(interval)
    return children
```

- [ ] **Step 4: 让 `_run_inbox_quick_import` 用宽限重扫**

把 `_run_inbox_quick_import` 里 `base_cid = resolve_scraper_dest_folder_id(provider, base_rel)` 到
`identified = identify_scraper_batch_entries(...)` 这一段替换为：

```python
            base_cid = resolve_scraper_dest_folder_id(provider, base_rel)
            children = _wait_for_inbox_children(base_cid, provider)
            if not children:
                waited = INBOX_STAGING_RESCAN_INTERVAL_SECONDS * (INBOX_STAGING_MAX_ATTEMPTS - 1)
                summary = f"接收夹没有可整理的内容（已等待 {waited} 秒）"
                finish_run(
                    "completed",
                    0,
                    0,
                    summary,
                    {"moved": [], "left": [], "staging_wait_seconds": waited},
                )
                return {"ok": True, "moved": [], "left": [], "summary": summary, "run_id": run_id}
            identified = identify_scraper_batch_entries(
                provider,
                children,
                base_cid=base_cid,
                base_path=base_rel,
            )
```

注意：**不要**删掉后面 `if not items:` 的兜底分支（那是「有内容但扫不出条目」的情况），
只把它的 `summary` 改成 `"接收夹有内容但没有可整理条目"`，避免和宽限超时混在一起。

- [ ] **Step 5: 跑用例确认通过**

Run: `scripts/check.sh tests.test_quick_import`
Expected: PASS；`MultiInboxFanoutTest` 等既有用例不回归

- [ ] **Step 6: 提交（需用户授权）**

```bash
git add app/services/quick_import.py tests/test_quick_import.py
git commit -m "fix(inbox): 接收夹整理前按宽限期重扫，避免转存/离线落盘滞后空跑"
```

---

### Task 2：触发与中断按接收夹（任务名分桶）

**Files:**
- Modify: `app/services/quick_import.py`（`_INBOX_TRIGGER_STATE`、`notify_quick_import`、`_inbox_worker_loop`、`request_quick_import_cancel`、`pending_quick_import_rerun`、`run_quick_import`、`_run_inbox_quick_import` 的取消判定）
- Modify: `app/routes/monitor.py:498-504`、`app/routes/monitor.py:531-538`
- Modify: `app/routes/scraper.py:391-409`
- Modify: `app/startup.py:53-59`、`app/startup.py:182-186`
- Test: `tests/test_quick_import.py`

**Interfaces:**
- Produces: `notify_quick_import(trigger="queued", *, source_ref="", task_name="")`（`task_name=""` = 所有启用的接收夹）
- Produces: `run_quick_import(trigger="manual", *, sub_path="", parent_run_id="", source_ref="", wait_for_lock=False, task_names: Optional[Set[str]] = None)`（`None` = 全部）
- Produces: `request_quick_import_cancel(task_name="") -> bool`、`pending_quick_import_rerun(task_name="") -> bool`
- Produces: `_inbox_task_cancelled(task_name) -> bool`、`_inbox_cancel_wait(seconds, task_name) -> bool`
- Consumes: Task 3 / Task 4 依赖本任务的 `task_name` 参数

- [ ] **Step 1: 写失败用例**

```python
    def test_manual_trigger_only_runs_target_inbox(self):
        cfg = self._two_provider_cfg()
        seen = []

        def fake_run(cfg_arg, inbox, **kwargs):
            seen.append(inbox["name"])
            return {"run_id": len(seen), "moved": [], "left": [], "summary": "ok"}

        with mock.patch.object(quick_import, "get_config", return_value=cfg), \
                mock.patch.object(quick_import, "_run_inbox_quick_import", side_effect=fake_run):
            result = quick_import.run_quick_import("manual", task_names={"夸克接收"})
        self.assertEqual(seen, ["夸克接收"])
        self.assertTrue(result.get("ok"))

    def test_cancel_only_affects_target_inbox(self):
        quick_import._QUICK_IMPORT_CANCEL.clear()
        quick_import._QUICK_IMPORT_CANCEL_TASKS.clear()
        quick_import._QUICK_IMPORT_RUN_LOCK.acquire()
        try:
            self.assertTrue(quick_import.request_quick_import_cancel("夸克接收"))
            self.assertTrue(quick_import._inbox_task_cancelled("夸克接收"))
            self.assertFalse(quick_import._inbox_task_cancelled("接收"))
        finally:
            quick_import._QUICK_IMPORT_RUN_LOCK.release()
            quick_import._QUICK_IMPORT_CANCEL.clear()
            quick_import._QUICK_IMPORT_CANCEL_TASKS.clear()
```

- [ ] **Step 2: 跑用例确认失败**

Run: `scripts/check.sh tests.test_quick_import`
Expected: FAIL（`run_quick_import` 不接受 `task_names`、`_QUICK_IMPORT_CANCEL_TASKS` 不存在）

- [ ] **Step 3: 触发器改成按任务名分桶**

替换 `_INBOX_TRIGGER_STATE` 与相关函数：

```python
_QUICK_IMPORT_CANCEL_TASKS: Set[str] = set()

_INBOX_TRIGGER_STATE: Dict[str, Any] = {
    "worker": None,
    "pending_tasks": set(),  # 待整理任务名；空集合 = 无预约；含 "" 表示全部启用的接收夹
    "trigger": "",
    "source_ref": "",
    "last_arrival_at": 0.0,
}


def request_quick_import_cancel(task_name: str = "") -> bool:
    """请求中断指定接收夹（空串 = 中断当前整轮）；没有在跑时返回 False。"""
    if not _QUICK_IMPORT_RUN_LOCK.locked():
        return False
    with _INBOX_TRIGGER_LOCK:
        _INBOX_TRIGGER_STATE["pending_tasks"] = set()
        _QUICK_IMPORT_CANCEL_TASKS.add(str(task_name or "").strip())
    _INBOX_TRIGGER_EVENT.set()
    _QUICK_IMPORT_CANCEL.set()
    return True


def _inbox_task_cancelled(task_name: str) -> bool:
    if not _QUICK_IMPORT_CANCEL.is_set():
        return False
    with _INBOX_TRIGGER_LOCK:
        return "" in _QUICK_IMPORT_CANCEL_TASKS or str(task_name or "").strip() in _QUICK_IMPORT_CANCEL_TASKS


def _inbox_cancel_wait(seconds: float, task_name: str) -> bool:
    """可被「本接收夹中断」打断的等待；返回 True 表示被中断。"""
    deadline = time.monotonic() + max(0.0, float(seconds or 0))
    while True:
        if _inbox_task_cancelled(task_name):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.25, remaining))
```

`notify_quick_import` 增加 `task_name` 形参，把 `_INBOX_TRIGGER_STATE["pending"]` 全部替换成 `pending_tasks` 集合：

```python
def notify_quick_import(trigger: str = "queued", *, source_ref: str = "", task_name: str = "") -> Dict[str, Any]:
    normalized_trigger = str(trigger or "").strip().lower() or "queued"
    normalized_ref = str(source_ref or "").strip()
    normalized_task = str(task_name or "").strip()
    started_worker: Optional[threading.Thread] = None
    with _INBOX_TRIGGER_LOCK:
        _INBOX_TRIGGER_STATE["last_arrival_at"] = time.monotonic()
        worker = _INBOX_TRIGGER_STATE.get("worker")
        if isinstance(worker, threading.Thread) and worker.is_alive():
            current = str(_INBOX_TRIGGER_STATE.get("trigger", "") or "")
            if _inbox_trigger_priority(normalized_trigger) >= _inbox_trigger_priority(current):
                _INBOX_TRIGGER_STATE["trigger"] = normalized_trigger
                _INBOX_TRIGGER_STATE["source_ref"] = normalized_ref
            _INBOX_TRIGGER_STATE.setdefault("pending_tasks", set()).add(normalized_task)
            started, running = False, True
        else:
            _INBOX_TRIGGER_STATE["pending_tasks"] = {normalized_task}
            _INBOX_TRIGGER_STATE["trigger"] = normalized_trigger
            _INBOX_TRIGGER_STATE["source_ref"] = normalized_ref
            started_worker = threading.Thread(
                target=_inbox_worker_loop,
                args=(normalized_trigger, normalized_ref, {normalized_task}),
                name="inbox-quick-import",
                daemon=True,
            )
            _INBOX_TRIGGER_STATE["worker"] = started_worker
            started, running = True, False
    if started_worker is not None:
        started_worker.start()
    _INBOX_TRIGGER_EVENT.set()
    return {
        "ok": True,
        "started": started,
        "queued": True,
        "running": running,
        "summary": "已有接收夹整理在执行，已安排再跑一轮" if running else "已开始接收夹整理",
    }
```

`_inbox_worker_loop` 改为按任务集合跑：

```python
def _inbox_worker_loop(trigger: str, source_ref: str, task_names: Set[str]) -> None:
    current_trigger, current_ref, current_tasks = trigger, source_ref, set(task_names or set())
    while True:
        try:
            all_inboxes = "" in current_tasks
            wanted = {name for name in current_tasks if name}
            result = run_quick_import(
                current_trigger,
                source_ref=current_ref,
                task_names=None if all_inboxes else wanted,
                wait_for_lock=True,
            )
            if isinstance(result, dict) and result.get("skipped"):
                with _INBOX_TRIGGER_LOCK:
                    _INBOX_TRIGGER_STATE.setdefault("pending_tasks", set()).update(current_tasks)
                _INBOX_TRIGGER_EVENT.set()
                time.sleep(5)
                continue
        except Exception:
            logging.exception("接收夹整理执行失败")
        with _INBOX_TRIGGER_LOCK:
            pending = set(_INBOX_TRIGGER_STATE.get("pending_tasks") or set())
            if not pending:
                _INBOX_TRIGGER_STATE["worker"] = None
                _INBOX_TRIGGER_STATE["trigger"] = ""
                _INBOX_TRIGGER_STATE["source_ref"] = ""
                _INBOX_TRIGGER_EVENT.clear()
                return
            current_tasks = pending
            current_trigger = str(_INBOX_TRIGGER_STATE.get("trigger", "") or "queued")
            current_ref = str(_INBOX_TRIGGER_STATE.get("source_ref", "") or "")
            _INBOX_TRIGGER_STATE["pending_tasks"] = set()
        _wait_for_inbox_next_run(next(iter(current_tasks), ""))
```

`pending_quick_import_rerun(task_name="")` 改成读集合：

```python
def pending_quick_import_rerun(task_name: str = "") -> bool:
    normalized = str(task_name or "").strip()
    with _INBOX_TRIGGER_LOCK:
        pending = set(_INBOX_TRIGGER_STATE.get("pending_tasks") or set())
    if not pending:
        return False
    if not normalized:
        return True
    return normalized in pending or "" in pending
```

- [ ] **Step 4: `run_quick_import` 支持按任务过滤，取消按任务判定**

```python
def run_quick_import(
    trigger: str = "manual",
    *,
    sub_path: str = "",
    parent_run_id: str = "",
    source_ref: str = "",
    wait_for_lock: bool = False,
    task_names: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    ...
        cfg = get_config()
        inboxes = [task for task in get_inbox_tasks(cfg) if task.get("enabled")]
        if task_names is not None:
            wanted = {str(name or "").strip() for name in task_names if str(name or "").strip()}
            inboxes = [task for task in inboxes if str(task.get("name", "") or "").strip() in wanted]
        if not inboxes:
            return {
                "ok": True,
                "skipped": True,
                "moved": [],
                "left": [],
                "summary": "没有需要整理的接收夹（任务不存在、已停用或已被过滤）",
            }
    ...
    finally:
        _QUICK_IMPORT_CANCEL.clear()
        with _INBOX_TRIGGER_LOCK:
            _QUICK_IMPORT_CANCEL_TASKS.clear()
        _QUICK_IMPORT_RUN_LOCK.release()
```

`_QUICK_IMPORT_RUN_LOCK.acquire()` 成功后同样要清空 `_QUICK_IMPORT_CANCEL_TASKS`（与现在清 `_QUICK_IMPORT_CANCEL` 的位置一致）。

`_run_inbox_quick_import` 里 6 处取消判定改成带任务名（`task_label` 用该接收夹的 `conf["task_name"]`，已有变量，不要改成常量）：

- `if _QUICK_IMPORT_CANCEL.is_set():` → `if _inbox_task_cancelled(task_label):`（3 处，约 1397 / 1623 / 1716 行）
- `if _QUICK_IMPORT_CANCEL.wait(batch_pause_seconds):` → `if _inbox_cancel_wait(batch_pause_seconds, task_label):`（2 处，约 1490 / 1832 行）

- [ ] **Step 5: 路由与定时带上任务名**

`app/routes/monitor.py`：

```python
    if normalize_task_type(task.get("task_type")) == MONITOR_TASK_TYPE_INBOX:
        from ..services.quick_import import notify_quick_import

        result = notify_quick_import("manual", task_name=task_name)
        return {"ok": True, "status": str(result.get("summary", "") or ""), "result": result}
```

```python
        from ..services.quick_import import request_quick_import_cancel

        if not request_quick_import_cancel(task_name):
            return {"ok": False, "status": "idle", "cleared": 0}
```

`app/routes/scraper.py` 的 `/scraper/quick-import/run`：

```python
    task_name = str(payload.get("task_name", "") or "").strip()
    task_names = {task_name} if task_name else None
    result = await asyncio.to_thread(
        quick_import.run_quick_import,
        trigger,
        sub_path=sub_path,
        task_names=task_names,
        wait_for_lock=True,
    )
```

`app/startup.py`：

```python
async def _run_inbox_cron_import(task_name: str = "") -> None:
    """接收夹定时整理：只登记请求，实际整理在工作线程里串行执行。"""
    try:
        from .services.quick_import import notify_quick_import

        notify_quick_import("cron", task_name=task_name)
    except Exception:
        logging.exception("接收夹定时整理失败")
```

调度循环里 `asyncio.create_task(_run_inbox_cron_import())` → `asyncio.create_task(_run_inbox_cron_import(name))`。

- [ ] **Step 6: 跑用例确认通过**

Run: `scripts/check.sh tests.test_quick_import tests.test_quick_import_frontend tests.test_monitor_webhook_quick_import`
Expected: PASS

- [ ] **Step 7: 提交（需用户授权）**

```bash
git add app/services/quick_import.py app/routes/monitor.py app/routes/scraper.py app/startup.py tests/test_quick_import.py
git commit -m "fix(inbox): 触发与中断按接收夹任务名隔离，不再全局扇出"
```

---

### Task 3：导入任务记录接收夹归属 + 最近接收统计

**Files:**
- Modify: `app/db.py`（`resource_jobs` 建表约 201-222 行 + 迁移块约 542-547 行）
- Modify: `app/resource_jobs.py`（`_build_resource_job_insert`、`create_resource_jobs` 的 INSERT、`find_existing_resource_job`）
- Modify: `app/services/quick_import.py`（新增 `match_quick_import_inbox`、改造 `is_quick_import_savepath`、`list_inbox_recent_jobs` / `count_inbox_recent_jobs` 加过滤）
- Modify: `app/routes/resource.py:1143-1177`、`app/routes/resource.py:1316-1349`
- Modify: `app/routes/monitor.py:157-163`（webhook extra）
- Modify: `app/services/resource.py:196-232`、`app/services/resource.py:645-655`、`app/services/resource.py:999-1008`
- Test: `tests/test_quick_import.py`、`tests/test_resource_offline_completion.py`

**Interfaces:**
- Produces: `match_quick_import_inbox(cfg, savepath, provider="") -> Dict[str, Any]`（返回命中的接收夹任务，未命中返回 `{}`）
- Produces: `list_inbox_recent_jobs(inbox_rel, limit=3, task_name="")`、`count_inbox_recent_jobs(inbox_rel, hours=24, task_name="")`
- Produces: `resource_jobs.inbox_task_name TEXT NOT NULL DEFAULT ''`
- Consumes: Task 2 的 `notify_quick_import(..., task_name=...)`

- [ ] **Step 1: 写失败用例**

```python
class InboxAttributionTest(unittest.TestCase):
    """同名路径跨网盘时，最近接收记录要按接收夹归属过滤。"""

    def test_match_quick_import_inbox_respects_provider(self):
        cfg = MultiInboxFanoutTest._two_provider_cfg()
        self.assertEqual(
            str(quick_import.match_quick_import_inbox(cfg, "接收", provider="115").get("name", "")),
            "接收",
        )
        self.assertEqual(quick_import.match_quick_import_inbox(cfg, "接收", provider="quark"), {})
        self.assertEqual(
            str(quick_import.match_quick_import_inbox(cfg, "接收/子目录", provider="quark").get("name", "")),
            "夸克接收",
        )
```

再来一条落库 / 过滤的集成断言（临时 DB 的写法沿用 `tests/test_quick_import.py:1023-1039` 已有的 setUp / tearDown）：

```python
class InboxRecentJobsAttributionTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.tmpdir.name, "data.db")

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        self.tmpdir.cleanup()

    def test_recent_jobs_filter_by_inbox_task_name(self):
        from app.resource_jobs import create_resource_jobs

        create_resource_jobs([
            (
                {"title": "115 的", "link_url": "magnet:?xt=urn:btih:AAA", "link_type": "magnet"},
                {"savepath": "接收", "inbox_task_name": "接收", "extra": {"quick_import_inbox": 1}},
            ),
            (
                {"title": "夸克的", "link_url": "magnet:?xt=urn:btih:BBB", "link_type": "magnet"},
                {"savepath": "接收", "inbox_task_name": "夸克接收", "extra": {"quick_import_inbox": 1}},
            ),
        ])
        only_115 = quick_import.list_inbox_recent_jobs("接收", 3, task_name="接收")
        self.assertEqual([job["title"] for job in only_115], ["115 的"])
        self.assertEqual(quick_import.count_inbox_recent_jobs("接收", 24, task_name="夸克接收"), 1)
```

- [ ] **Step 2: 跑用例确认失败**

Run: `scripts/check.sh tests.test_quick_import`
Expected: FAIL（`match_quick_import_inbox` 不存在）

- [ ] **Step 3: `resource_jobs` 增加归属列**

`app/db.py` 建表语句加一列（放在 `extra_json` 之后）：

```sql
                    extra_json TEXT NOT NULL DEFAULT '{}',
                    inbox_task_name TEXT NOT NULL DEFAULT ''
```

迁移块（紧挨现有的 `extra_json` 迁移）：

```python
            cursor.execute("PRAGMA table_info(resource_jobs)")
            job_columns = {str(row[1]) for row in cursor.fetchall()}
            if "extra_json" not in job_columns:
                cursor.execute("ALTER TABLE resource_jobs ADD COLUMN extra_json TEXT NOT NULL DEFAULT '{}'")
            if "inbox_task_name" not in job_columns:
                cursor.execute("ALTER TABLE resource_jobs ADD COLUMN inbox_task_name TEXT NOT NULL DEFAULT ''")
```

`app/resource_jobs.py`：`create_resource_jobs` 的 INSERT 列清单加 `inbox_task_name`（占位符同步 +1），
`_build_resource_job_insert` 的 `params` 末尾追加：

```python
            str(data.get("inbox_task_name", "")).strip(),
```

- [ ] **Step 4: 落点判定带 provider 并返回命中的接收夹**

`app/services/quick_import.py` 把 `is_quick_import_savepath` 拆成两半：

```python
def match_quick_import_inbox(
    cfg: Dict[str, Any],
    savepath: Any,
    provider: str = "",
) -> Dict[str, Any]:
    """返回 savepath 命中的接收夹任务；没命中返回空字典。

    savepath 是网盘相对路径（不带 provider），能确定落盘网盘时必须传 ``provider``；
    不传时退回「任一启用的接收夹命中即算命中」，只留给无法判定网盘的旧调用方。
    """
    relative = normalize_relative_path(str(savepath or "").strip())
    if not relative:
        return {}
    provider_key = normalize_mount_provider(provider)
    for candidate in get_inbox_tasks(cfg):
        if provider_key and _inbox_provider(cfg, candidate) != provider_key:
            continue
        conf = build_quick_import_config(cfg, candidate)
        if not conf["enabled"]:
            continue
        inbox_rel = str(conf.get("inbox_rel", "") or "").strip()
        if not inbox_rel:
            continue
        if relative == inbox_rel or relative.startswith(inbox_rel + "/"):
            return candidate
    return {}


def is_quick_import_savepath(
    cfg: Dict[str, Any],
    savepath: Any,
    inbox: Optional[Dict[str, Any]] = None,
    provider: str = "",
) -> bool:
    """导入落点是否落在接收夹内；传了 ``inbox`` 就只判这一个接收夹。"""
    if isinstance(inbox, dict) and inbox:
        conf = build_quick_import_config(cfg, inbox)
        if not conf["enabled"]:
            return False
        inbox_rel = str(conf.get("inbox_rel", "") or "").strip()
        relative = normalize_relative_path(str(savepath or "").strip())
        return bool(relative and inbox_rel and (relative == inbox_rel or relative.startswith(inbox_rel + "/")))
    return bool(match_quick_import_inbox(cfg, savepath, provider))
```

`list_inbox_recent_jobs` / `count_inbox_recent_jobs` 增加 `task_name` 过滤：

```python
def list_inbox_recent_jobs(inbox_rel: str, limit: int = 3, task_name: str = "") -> List[Dict[str, Any]]:
    ...
    wanted = str(task_name or "").strip()
    sql = "SELECT * FROM resource_jobs WHERE (savepath = ? OR savepath LIKE ?)"
    params: List[Any] = [prefix, f"{prefix}/%"]
    if wanted:
        sql += " AND inbox_task_name = ?"
        params.append(wanted)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(page_limit)
    cursor.execute(sql, tuple(params))
```

`count_inbox_recent_jobs` 同样在 WHERE 里加 `AND inbox_task_name = ?`。

- [ ] **Step 5: 调用方传 provider 并落库归属**

`app/routes/resource.py` 两处（ED2K 批量约 1143 行、`/resource/jobs/create` 约 1316 行）：

```python
        inbox_provider = offline_provider_name if is_offline_link else (
            share_provider.name if share_provider else ""
        )
        matched_inbox = match_quick_import_inbox(cfg, savepath, provider=inbox_provider)
        inbox_task_name = str(matched_inbox.get("name", "") or "").strip()
        quick_import_inbox = bool(inbox_task_name)
```

ED2K 批量那条链路 provider 固定 `"115"`。把 `"inbox_task_name": inbox_task_name`
同时写进 `data` 顶层（供 `_build_resource_job_insert` 落库）和 `extra`（供前端任务卡展示）。

`app/routes/monitor.py` 的 `_handle_inbox_webhook` extra 增加 `"inbox_task_name": task_name`，
并在 `_create_userscript_magnet_job` 的 `create_resource_job(..., data)` 里带上：

```python
            "inbox_task_name": str((extra or {}).get("inbox_task_name", "")).strip(),
```

`app/services/resource.py` 触发时带上任务名：

```python
        inbox_task_name = str(job.get("inbox_task_name", "") or "").strip() or str(
            job_extra_for_trigger.get("inbox_task_name", "") or ""
        ).strip()
        if bool(job_extra_for_trigger.get("quick_import_inbox")) and not is_offline_link:
            from . import quick_import as quick_import_service

            delay_seconds = max(0, int(job.get("refresh_delay_seconds", 0) or 0))
            if delay_seconds > 0:
                submit_background(
                    _run_quick_import_after_delay, delay_seconds, inbox_task_name, label="quick-import-delayed"
                )
            else:
                submit_background(
                    lambda: quick_import_service.notify_quick_import("import", task_name=inbox_task_name),
                    label="quick-import",
                )
```

`_run_quick_import_after_delay(delay_seconds: int, task_name: str = "")` 同样透传 `task_name`
（`notify_quick_import` 的 `task_name` 是 keyword-only，不能靠位置参数传）。

离线完成分支（`_apply_offline_task_state`，约 219-225 行）改成：

```python
                quick_import_service.notify_quick_import(
                    "offline",
                    source_ref=f"resource:{job_id}",
                    task_name=str(job.get("inbox_task_name", "") or job_extra.get("inbox_task_name", "") or "").strip(),
                )
```

- [ ] **Step 6: `find_existing_resource_job` 增加归属维度**

```python
def find_existing_resource_job(resource: Dict[str, Any], savepath: str, inbox_task_name: str = "") -> Dict[str, Any]:
```

SQL 在 `savepath = ?` 之后再加 `AND inbox_task_name = ?`，调用方（`app/routes/resource.py`、
`app/routes/monitor.py`）传入本次算出的 `inbox_task_name`；传 `""` 时维持旧行为（只看非接收夹记录）。

- [ ] **Step 7: 跑用例确认通过**

Run: `scripts/check.sh tests.test_quick_import tests.test_resource_offline_completion tests.test_monitor_webhook_quick_import`
Expected: PASS

- [ ] **Step 8: 提交（需用户授权）**

```bash
git add app/db.py app/resource_jobs.py app/services/quick_import.py app/routes/resource.py app/routes/monitor.py app/services/resource.py tests
git commit -m "fix(inbox): 导入任务记录接收夹归属，最近接收统计按接收夹过滤"
```

---

### Task 4：状态按接收夹聚合（用户最初报告的现象）

**Files:**
- Modify: `app/services/quick_import.py`（`list_quick_import_runs`、新增 `_INBOX_RUNNING_TASK` / `quick_import_task_running`、`_run_inbox_quick_import` 的运行标记、`_build_inbox_status`、`get_quick_import_status`）
- Modify: `static/js/index.js:3786-3793`、`static/js/index.js:3843-3855`
- Test: `tests/test_quick_import.py`、`tests/test_quick_import_frontend.py`

**Interfaces:**
- Produces: `list_quick_import_runs(limit=20, inbox_path="") -> List[Dict[str, Any]]`
- Produces: `quick_import_task_running(task_name) -> bool`、`quick_import_task_cancelling(task_name) -> bool`
- Consumes: Task 2 的取消分桶、Task 3 的 `list_inbox_recent_jobs(..., task_name=)`

- [ ] **Step 1: 写失败用例**

```python
    def test_status_snapshot_carries_per_inbox_activity(self):
        cfg = self._two_provider_cfg()
        runs_by_path = {"/115/接收": [{"id": 9, "summary": "115 的整理"}], "/quark/接收": []}

        def fake_runs(limit=20, inbox_path=""):
            return runs_by_path.get(inbox_path, [])

        with mock.patch.object(quick_import, "list_quick_import_runs", side_effect=fake_runs), \
                mock.patch.object(quick_import, "list_inbox_recent_jobs", return_value=[]), \
                mock.patch.object(quick_import, "count_inbox_recent_jobs", return_value=0), \
                mock.patch.object(quick_import, "latest_monitor_run_progress", return_value={}):
            first = quick_import._build_inbox_status(cfg, core.get_inbox_tasks(cfg)[0])
            second = quick_import._build_inbox_status(cfg, core.get_inbox_tasks(cfg)[1])
        self.assertEqual(first["latest"]["id"], 9)
        self.assertEqual(second["latest"], {})
        self.assertIn("recent_job_count_24h", first)
        self.assertIn("running", second)
```

前端用例在 `tests/test_quick_import_frontend.py` 增加源码断言：

```python
        self.assertIn("recent_jobs: []", script)
```

- [ ] **Step 2: 跑用例确认失败**

Run: `scripts/check.sh tests.test_quick_import tests.test_quick_import_frontend`
Expected: FAIL（`_build_inbox_status` 没有 `latest`）

- [ ] **Step 3: 后端补齐每盘快照**

`list_quick_import_runs` 增加 `inbox_path` 过滤：

```python
def list_quick_import_runs(limit: int = 20, inbox_path: str = "") -> List[Dict[str, Any]]:
    normalized_limit = max(1, min(200, int(limit or 20)))
    normalized_inbox = str(inbox_path or "").strip()
    ensure_db()

    def load() -> List[Dict[str, Any]]:
        with db_connection() as conn:
            cursor = conn.cursor()
            if normalized_inbox:
                cursor.execute(
                    "SELECT * FROM quick_import_runs WHERE inbox_path = ? ORDER BY id DESC LIMIT ?",
                    (normalized_inbox, normalized_limit),
                )
            else:
                cursor.execute(
                    "SELECT * FROM quick_import_runs ORDER BY id DESC LIMIT ?",
                    (normalized_limit,),
                )
            columns = [item[0] for item in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    return retry_sqlite_locked(load)
```

新增运行中标记与查询函数：

```python
_INBOX_RUNNING_TASK: Dict[str, str] = {"name": ""}


def quick_import_task_running(task_name: str) -> bool:
    return _QUICK_IMPORT_RUN_LOCK.locked() and str(_INBOX_RUNNING_TASK.get("name", "") or "").strip() == str(task_name or "").strip()


def quick_import_task_cancelling(task_name: str) -> bool:
    return quick_import_task_running(task_name) and _inbox_task_cancelled(task_name)
```

在 `_run_inbox_quick_import` 里 `conf = build_quick_import_config(cfg, inbox)` 之后写
`_INBOX_RUNNING_TASK["name"] = task_label`，并在该函数末尾已有的 `finally` 里清空
（现在那个 `finally` 只有注释和 `pass`，把清理放进去）。

`_build_inbox_status` 补字段：

```python
    inbox_path = str(conf.get("inbox_path", "") or "").strip()
    inbox_rel = str(conf.get("inbox_rel", "") or "").strip()
    task_name = str(conf.get("task_name", "") or "").strip()
    runs = list_quick_import_runs(1, inbox_path=inbox_path) if inbox_path else []
    latest = runs[0] if runs else {}
    detail = safe_json_loads(latest.get("detail_json", "{}"), {}) if latest else {}
    return {
        # ...原有字段保持不变...
        "latest": latest,
        "latest_detail": detail,
        "recent_jobs": list_inbox_recent_jobs(inbox_rel, 3, task_name=task_name),
        "recent_job_count_24h": count_inbox_recent_jobs(inbox_rel, 24, task_name=task_name),
        "running": quick_import_task_running(task_name),
        "cancelling": quick_import_task_cancelling(task_name),
        "pending_rerun": pending_quick_import_rerun(task_name),
    }
```

`get_quick_import_status` 顶层字段保留（兼容旧调用方 / CLI），但加注释说明「只代表第一个接收夹，
面板不要用」；新增 `"running_task": str(_INBOX_RUNNING_TASK.get("name", "") or "")`。

- [ ] **Step 4: 前端不再透传全局状态**

```js
        function inboxStatusForTask(taskName = '') {
            // 每个网盘一个接收夹：卡片按名字取自己那份；取不到就给一份空快照，
            // 绝不把全局的最近运行 / 最近接收透传给这张卡片。
            const cache = inboxTaskStatusCache && typeof inboxTaskStatusCache === 'object' ? inboxTaskStatusCache : {};
            const name = String(taskName || '').trim();
            const list = Array.isArray(cache.inboxes) ? cache.inboxes : [];
            const match = name ? list.find((item) => String(item?.task_name || '').trim() === name) : null;
            if (match) return { ...cache, ...match };
            return {
                latest: {}, latest_detail: {}, recent_jobs: [], recent_job_count_24h: 0,
                running: false, cancelling: false, pending_rerun: false,
            };
        }
```

`toggleInboxTaskRun` 用目标任务的运行状态：

```js
            const name = currentMonitorFormTaskName();
            const running = !!inboxStatusForTask(name).running;
```

- [ ] **Step 5: 跑用例确认通过**

Run: `scripts/check.sh tests.test_quick_import tests.test_quick_import_frontend tests.test_monitor_run_frontend`
Expected: PASS

- [ ] **Step 6: 提交（需用户授权）**

```bash
git add app/services/quick_import.py static/js/index.js tests
git commit -m "fix(inbox): 接收夹最近运行/最近接收状态按接收夹隔离"
```

---

### Task 5：每盘静默窗口

**Files:**
- Modify: `app/services/quick_import.py:140-160`（`_inbox_delay_seconds`、`_wait_for_inbox_next_run`）
- Test: `tests/test_quick_import.py`

**Interfaces:**
- Produces: `_inbox_delay_seconds(task_name: str = "") -> int`、`_wait_for_inbox_next_run(task_name: str = "") -> None`
- Consumes: Task 2 的 `_inbox_worker_loop`（已传任务名）

- [ ] **Step 1: 写失败用例**

```python
    def test_inbox_delay_uses_target_inbox_idle_seconds(self):
        cfg = self._two_provider_cfg()
        cfg["monitor_tasks"][1]["inbox_idle_seconds"] = 11
        cfg["monitor_tasks"][2]["inbox_idle_seconds"] = 22
        with mock.patch.object(quick_import, "get_config", return_value=cfg):
            self.assertEqual(quick_import._inbox_delay_seconds("接收"), 11)
            self.assertEqual(quick_import._inbox_delay_seconds("夸克接收"), 22)
```

- [ ] **Step 2: 跑用例确认失败**

Run: `scripts/check.sh tests.test_quick_import`
Expected: FAIL（`_inbox_delay_seconds` 不接受任务名 / 总是取第一个接收夹）

- [ ] **Step 3: 按任务名取配置**

```python
def _inbox_delay_seconds(task_name: str = "") -> int:
    try:
        cfg = get_config()
        wanted = str(task_name or "").strip()
        inbox = get_inbox_task(cfg, wanted) if wanted else get_inbox_task(cfg)
        conf = build_quick_import_config(cfg, inbox) if inbox else {}
    except Exception:
        conf = {}
    return max(0, int(conf.get("inbox_idle_seconds", QUICK_IMPORT_DEFAULT_IDLE_SECONDS) or 0))
```

`_wait_for_inbox_next_run(task_name="")` 里改成 `idle_seconds = _inbox_delay_seconds(task_name)`。

- [ ] **Step 4: 跑用例确认通过**

Run: `scripts/check.sh tests.test_quick_import`
Expected: PASS

- [ ] **Step 5: 提交（需用户授权）**

```bash
git add app/services/quick_import.py tests/test_quick_import.py
git commit -m "fix(inbox): 整理静默窗口按接收夹各自读取"
```

---

### Task 6：落点提示与禁用态一致

**Files:**
- Modify: `static/js/modules/resource/core.js:1882-1920`、`static/js/modules/resource/core.js:1992-2080`
- Test: `tests/test_quick_import_frontend.py`

**Interfaces:**
- Produces: `resolveResourceMonitorTaskMatch(...)` 返回值新增 `inboxEnabled: boolean`

- [ ] **Step 1: 写失败用例**

```python
        self.assertIn("inboxEnabled", core_js)
        self.assertIn("已停用，保存后不会自动整理", core_js)
```

- [ ] **Step 2: 跑用例确认失败**

Run: `scripts/check.sh tests.test_quick_import_frontend`
Expected: FAIL

- [ ] **Step 3: 提示按启用状态分流**

```js
            return {
                savepath: normalizedSavepath,
                fullPath,
                task: matchedTask,
                taskName: matchedTask?.name || '',
                scanPath: normalizeRemotePathInput(matchedTask?.scan_path || ''),
                inboxTask: matchedInbox,
                inboxTaskName: matchedInbox?.name || '',
                inboxEnabled: matchedInbox ? matchedInbox.enabled !== false : false,
                isInbox: !matchedTask && !!matchedInbox,
            };
```

`renderResourceImportBehaviorHint` 的 inbox 分支：

```js
                : (match.isInbox
                    ? (match.inboxEnabled
                        ? `映射到 ${providerLabel} 路径 ${match.fullPath}，命中接收夹“${match.inboxTaskName || '接收夹'}”，保存完成后自动整理分发，再由监控任务生成 STRM。`
                        : `映射到 ${providerLabel} 路径 ${match.fullPath}，接收夹“${match.inboxTaskName || '接收夹'}”已停用，保存后不会自动整理；请到「文件夹监控」页启用该接收夹。`)
                    : `映射到 ${providerLabel} 路径 ${match.fullPath}，未纳入文件夹监控，不会自动生成 STRM。`);
```

`syncResourceMonitorTaskOptions` 里 `displayInput.textContent` 的 inbox 分支同样加 `（已停用，不会自动整理）`。

- [ ] **Step 4: 跑用例确认通过**

Run: `scripts/check.sh tests.test_quick_import_frontend`
Expected: PASS

- [ ] **Step 5: 提交（需用户授权）**

```bash
git add static/js/modules/resource/core.js tests/test_quick_import_frontend.py
git commit -m "fix(inbox): 导入落点提示区分已停用接收夹"
```

---

### Task 7：接收夹整理通知（❌ 已决定不做 —— 2026-10-08 用户口径：通知只保留文件夹监控 + 订阅两条）

**Files:**
- Modify: `app/services/notify.py`（新增 `push_inbox_success_notification`）
- Modify: `app/services/quick_import.py`（`finish_run` 里调用）
- Test: `tests/test_quick_import.py`

**Interfaces:**
- Produces: `await push_inbox_success_notification(cfg, task: Dict[str, Any], moved: List[Dict[str, Any]], left: List[Dict[str, Any]], status: str) -> Dict[str, Any]`
- 复用开关（待确认）：`notify_monitor_enabled`

- [ ] **Step 1: 先问用户**

确认三点：① 接收夹整理完成后是否推企业微信；② 复用 `notify_monitor_enabled` 还是新增独立开关；
③ 只在有分发时推，还是失败（留在接收夹 / 整理异常）也推。**未确认前不要动代码。**

- [ ] **Step 2: 写失败用例**

```python
    def test_inbox_run_with_moved_items_notifies_when_enabled(self):
        cfg = _cfg(inbox=False, notify_monitor_enabled=True)
        inbox = core.get_inbox_task(cfg, "接收")
        with mock.patch.object(quick_import, "get_config", return_value=cfg), \
                mock.patch.object(quick_import, "resolve_scraper_dest_folder_id", return_value="cid"), \
                mock.patch.object(quick_import, "_list_inbox_children", return_value=[{"id": "1", "is_dir": True}]), \
                mock.patch.object(quick_import, "identify_scraper_batch_entries", return_value={
                    "items": [_item(1)], "results": [], "picked": {1: {"media_type": "movie", "title": "片名"}},
                }), \
                mock.patch.object(quick_import, "_dispatch_organized_entry", return_value={
                    "moved": [{"name": "片名"}], "left": [], "monitor_sync_events": 0,
                }), \
                mock.patch.object(quick_import, "_insert_quick_import_run", return_value=7), \
                mock.patch.object(quick_import, "create_monitor_run", return_value="run-1"), \
                mock.patch.object(quick_import, "start_monitor_run"), \
                mock.patch.object(quick_import, "finish_monitor_run"), \
                mock.patch.object(quick_import, "_finish_quick_import_run"), \
                mock.patch.object(quick_import, "push_inbox_success_notification") as pusher:
            quick_import._run_inbox_quick_import(cfg, inbox)
        pusher.assert_awaited()
```

（`push_inbox_success_notification` 从 `..services.notify` 导入到 `quick_import` 模块命名空间，
测试用 `mock.AsyncMock` / `assert_awaited`；如果实现里改成同步函数，断言改成 `assert_called_once()`。
「空跑不推」用同一个骨架把 `_dispatch_organized_entry` 的返回值换成空 `moved`。）

- [ ] **Step 3: 实现**

调用点放在 `_run_inbox_quick_import` 的 `finish_run()` 内部（`finish_monitor_run` 之后、
`write_monitor_log_sync` 之前），整段包 `try/except`，推送失败只写日志，不影响整理结果。

- [ ] **Step 4: 跑用例确认通过**

Run: `scripts/check.sh tests.test_quick_import`
Expected: PASS

- [ ] **Step 5: 提交（需用户授权）**

```bash
git add app/services/notify.py app/services/quick_import.py tests/test_quick_import.py
git commit -m "feat(inbox): 接收夹整理完成后按开关推送通知"
```

---

### Task 8：CLI 与文档收口

**Files:**
- Modify: `cli.py:940-960`（`quick-import-status`）、`cli.py:845-851`（`monitor list`）
- Modify: `docs/superpowers/modules.md`、`docs/superpowers/conventions.md`、`docs/superpowers/state.md`、`docs/superpowers/handoff.md`

- [ ] **Step 1: CLI 按接收夹输出**

```python
    elif args.action == "quick-import-status":
        data = c.json("GET", "/scraper/quick-import/status")
        inboxes = data.get("inboxes") if isinstance(data.get("inboxes"), list) else []
        if not inboxes:
            print("没有接收夹任务")
            return
        for inbox in inboxes:
            name = str(inbox.get("task_name", "") or "(未命名)")
            provider = str(inbox.get("provider", "") or "115")
            enabled = "已启用" if inbox.get("enabled") else "未启用"
            print(f"接收夹「{name}」（{provider}，{enabled}）")
            print(f"  接收文件夹：{inbox.get('inbox_path') or '(未设置)'}")
            targets = inbox.get("targets") if isinstance(inbox.get("targets"), dict) else {}
            for key, label in (("movie", "电影"), ("tv", "电视剧")):
                path = str((targets.get(key) or {}).get("target_path", "") or "").strip()
                print(f"  {label}目标：{path or '(未设置)'}")
            latest = inbox.get("latest") if isinstance(inbox.get("latest"), dict) else {}
            print(f"  最近一次：{latest.get('summary') or '尚未执行过'}")
            print(f"  最近 24 小时接收：{int(inbox.get('recent_job_count_24h', 0) or 0)} 个")
            config_error = str(inbox.get("config_error", "") or "").strip()
            if config_error:
                print(f"  ⚠️ {config_error}")
```

`monitor list` 每行补任务类型与网盘：

```python
        kind = "接收夹" if str(t.get("task_type", "") or "scan") == "inbox" else "目录同步"
        provider = str(t.get("provider", "") or "") if kind == "接收夹" else ""
        print(f"  {enabled} {name}  [{kind}{f' · {provider}' if provider else ''}]  (扫描: {path}, 周期: {cron}分钟)")
```

- [ ] **Step 2: 文档同步**

- `modules.md` 接收夹条目：触发清单补「面板分享转存 / 离线回调按归属接收夹触发」；「不会做」补「手工放进接收夹不会自动触发（只能定时 / 手动 / webhook）」「接收夹当前不可删除」「多季合集不自动拆分」；「会做」补「每个接收夹的状态、运行、中断互相独立」。
- `conventions.md`：新增一条「接收夹的触发、状态、最近接收统计都按接收夹（网盘）隔离；同名相对路径在不同网盘互不影响」。
- `state.md`：更新基线与待办（删掉本轮已修条目，保留待拍板项）。
- `handoff.md`：追加一行 `- 2026-10-08 | 分支或提交 | 版本 | 变更一句话 | 根因或影响 | 验证证据 | 下一步`，随后跑 `.venv/bin/python scripts/rotate_handoff.py`。

- [ ] **Step 3: 跑用例确认通过**

Run: `scripts/check.sh tests.test_modules_doc tests.test_cli_grammar`
Expected: PASS

- [ ] **Step 4: 提交（需用户授权）**

```bash
git add cli.py docs/superpowers
git commit -m "chore(inbox): CLI 与文档同步接收夹按网盘隔离口径"
```

---

## 四、验证清单

- 语法 / 静态：`PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m compileall app main.py cli.py`
- 相关测试：`scripts/check.sh tests.test_quick_import tests.test_quick_import_frontend tests.test_resource_offline_completion tests.test_monitor_webhook_quick_import tests.test_monitor_run_frontend tests.test_modules_doc`
- 全量：`scripts/check.sh --all`
- 改动 JS 的 `node --check`（`check.sh` 会自动挑，建议手动再跑一次改动的文件）
- `git diff --check`；`handoff.md` 体积预算（`check.sh` 内置闸门）
- 容器重建后实盘复核（按 `AGENTS.md` 的代理配置执行 `docker compose up -d --build`）：
  1. 115 接收夹 + 夸克接收夹各一份，点其中一张卡片的「立即整理并分发」，另一张不应进入运行中；
  2. 夸克分享转存到夸克接收夹后，**大文件夹**也能在宽限期内被整理（不再空跑）；
  3. 两张卡片的「最近接收 24 小时」「最近整理」互相独立；
  4. 在夸克接收夹上点「中断」，115 那一轮不受影响；
  5. 禁用其中一个接收夹后，导入弹窗提示「已停用，保存后不会自动整理」。

## 五、待用户拍板（未拍板前不要动）

1. **手工放进接收夹要不要纳入触发**（问题 A4）：方案 A 让接收夹参与变更同步（仅 115，接口配额与风控成本最高）；方案 B 只做轻量轮询（复用定时）；方案 C 不做，写进文档。本计划默认 C。
2. **接收夹能不能删除**（问题 E4）：内置 115 接收夹保留；用户自建的非 115 接收夹是否放开删除，还是继续用「启用本任务」开关代替。
3. **编辑已有接收夹是否允许改网盘**：当前保存时按「每个网盘只能有一个」拦重复，编辑态下拉不禁用。
4. ~~**通知开关粒度**（Task 7）~~ **已定（2026-10-08，用户口径）**：接收夹整理**不推通知**，通知只保留文件夹监控 + 订阅两条；Task 7 取消，不要再实现。
5. **整理并发模型**（问题 B5）：是否允许不同网盘的接收夹并行整理（现在是一把全局锁顺序跑），并行会带来同名目标与日志交错的复杂度。

## 六、执行顺序与依赖

1. Task 1 独立可交付（P0，建议先单独验证再继续）。
2. Task 2 是 Task 4 / Task 5 的前置（任务名参数、取消分桶）。
3. Task 3 是 Task 4 的前置（`recent_*` 过滤需要归属列）。
4. Task 6 可并行做（纯前端 + 提示）。
5. Task 7 / Task 8 依赖拍板结果。
