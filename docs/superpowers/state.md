# 项目当前状态

> 这是**每次会话开头唯一需要完整阅读**的状态文件，目标 ≤80 行。
> 最近交接条目：`docs/superpowers/handoff.md`；历史条目：`docs/superpowers/handoff-archive.md`
> （通常不用读，`rg "关键词" docs/superpowers/handoff-archive.md` 按需检索）。
> 长期不变的架构与产品口径：`docs/superpowers/conventions.md`。
>
> 维护方式：只写“现在是什么状态”，不写历史。有实质进展或发布后更新本文件，
> 历史过程写进 `handoff.md` 条目。

## 基线

- **更新日期**: 2026-10-08
- **分支**: `main`，与 `origin/main` 一致（接收夹解耦批已推送）
- **版本**: `0.14.1`（`version.json` 是唯一真源，与 `CHANGELOG.md` 顶部一致；0.14.1 修复与元数据同步在未提交改动里）
- **最近提交**: `35da703` Decouple inbox tasks from folder monitoring per provider（2026-10-08，接收夹解耦批 + 0.14.0 发布元数据，已推送）
- **工作区**: 未提交改动 = **0.14.1 发布批**（广告名假视频不再生成本地 STRM，见 `CHANGELOG.md`）**＋ 115 写操作「受理 + 回验落地」修复批**（`app/providers/pan115.py` 忙响应退避重试 + `move_proid` 查进度 + 逐条回验父目录 / 名字；`app/services/scraper.py`、`app/services/quick_import.py` 没确认落地就不排 STRM 同步、不删接收夹源目录，条目留接收夹等下一轮；spec：`docs/superpowers/specs/2026-10-08-115-move-task-acceptance.md`）。接收夹解耦批（含 0.14.0 元数据）已在 **`35da703`** 推送，详细内容见该提交与 `handoff.md` 历史条目。

## 最近一次验证

- 完整 `unittest discover -s tests -p 'test_*.py'` **1247 项零失败**（2026-10-08，115 写操作「受理 + 回验落地」：`pan115._call_115_write_with_retry`（忙响应 1/2/4/8 秒退避）/ `wait_115_move_progress` / `wait_115_writes_landed`（逐条回验，超 50 条按进度兜底）/ `get_115_file_info` 补 `parent_id`+`is_dir`；`scraper` 的搬运 / 改名与整理任务三步批量按 `landing` 收尾、未落地转 `needs_reconcile`；`quick_import` 待落地留条不排同步不删源。108s；新增 `tests.test_115_list_pagination.Pan115MoveAcceptanceTest` 11 项、`tests.test_scraper_monitor_sync.ScraperMoveLandingTest` 3 项、`tests.test_quick_import` 1 项；`scripts/check.sh --all`、`compileall app main.py`、`git diff --check`、`handoff.md` 体积预算（31780/32768）均通过。**实盘只做过只读探测，未在真实账号重放写入**）。
- 完整 `unittest discover -s tests -p 'test_*.py'` **1231 项零失败**（2026-10-08，0.14.1 发布前复跑：广告名不再生成本地 STRM + 广告识别扩展叠后缀 / 裸域名 / `other` 扩展名，107s）；`version.json` 解析通过且与 `CHANGELOG.md` 顶部版本号（`0.14.1`）一致；`compileall app main.py`、`git diff --check`、`handoff.md` 体积预算（32548/32768）均通过。
- `scripts/check.sh tests.test_monitor_dir_scan tests.test_scraper_batch_organize tests.test_scraper_monitor_sync tests.test_tree_streaming_sync tests.test_tree_tasks tests.test_monitor_dir_rescan tests.test_monitor_runs tests.test_monitor_log_readability tests.test_modules_doc` **428 项零失败**（2026-10-08，推广话术假视频不再生成 STRM + 广告识别扩到 `.mkv.strm` / `.DOC`：`app/services/scraper.py` 新增 `SCRAPER_STRIPPABLE_EXTENSIONS` / `_strip_scraper_compound_extensions` / `_SCRAPER_AD_NAME_DOMAIN_RE`，`_is_scraper_promotional_only` 先剥后缀链再判残留，`_is_scraper_ad_file` 的 `other` 分支纳入「整段只有推广话术」；`app/services/monitor.py` 扫描跳过广告文件并计 `skipped_ad_files`、`app/core.py`「生成汇总」补「（含广告 N）」、`monitor_changes._file_passes_filters` 与 `tree._scan_tree_text` 同口径；`tests.test_scraper_batch_organize` 新增 2 项、`tests.test_monitor_dir_scan` 新增 1 项）。
- `scripts/check.sh --all` 全量 **1228 项零失败**（2026-10-08，0.14.0 发布前复跑：接收夹按网盘隔离三层 + 落盘宽限重扫 + 发布元数据，106s；`compileall app main.py cli.py`、改动 JS `node --check`、`git diff --check`、`handoff.md` 体积预算 32502/32768 均通过）。
- `scripts/check.sh --all` 全量 **1212 项零失败**（2026-10-08，非 115 接收夹整理分发链路修复：`app/services/scraper.py` 的 `resolve_scraper_dest_folder_id` 从「非 115 直接抛错」改成通用实现——115 走分页版 `resolve_115_folder_id_by_path`，其他网盘走各自 provider 的 `resolve_folder_id_by_path`，找不到抛带完整路径的错；接收夹一进场就要用它解析接收目录 `base_rel` 与每个分发目标 `scan_rel` 的 cid，所以此前夸克/天翼/123/阿里接收夹一运行就报「目标路径操作当前仅支持 115」整轮失败；`app/services/quick_import.py` 的 `_dispatch_organized_entry` 另外两处漏传 `provider`（目标无同名文件夹时的搬运、并入已有文件夹前列同名）会退回默认 115，用非 115 的文件 ID 调 115 接口，一并补上。`tests.test_scraper_path_ops` 2 项断言改写；`tests.test_quick_import` 新增 2 项：夸克接收夹分发走夸克搬运、散文件并入已有文件夹按夸克列目录；`compileall app main.py`、`git diff --check`、`handoff.md` 体积预算 32526/32768 均通过）。
- `scripts/check.sh --all` 全量 **1209 项零失败**（2026-10-08，目录选择弹窗修正 + 新建文件夹：`templates/partials/modals/monitor.html` 的 h3 补 `id="monitor-folder-modal-title"`（此前缺 id，`index.js` 里的 provider 标题从未生效，夸克接收夹也显示「选择 115 监控文件夹」）、路径标签改 `id="monitor-folder-path-label"` 并按目标显示「当前监控路径 / 当前接收夹路径 / 当前分发目标」、新增 `monitor-folder-create-name` + `monitor-folder-create-btn`；`static/js/index.js` 新增 `setMonitorFolderCreateBusy` / `createMonitorFolderInCurrent()`（复用 `window.createResourceFolder(cid, name, { provider: monitorFolderProvider })`，建完清分支缓存、自动进入并提示点「选择当前目录」）与 `showMonitorNameHelp()`（非 115 接收夹不再提 webhook 地址）；`static/js/modules/app/boot.js` 补新建输入框回车提交；`tests.test_monitor_run_frontend` 新增 `MonitorFolderPickerTest` 4 项；`compileall app main.py`、改动 JS `node --check`、`git diff --check`、`handoff.md` 体积预算 30952/32768 均通过）。
- `scripts/check.sh --all` 全量 **1205 项零失败**（2026-10-07，两块任务列表的「i」说明各弹各的：`static/js/index.js` 新增 `INBOX_HELP_HTML`（接收夹链路：分类前的中转文件夹 / 立即整理并分发 / 每个网盘只能有一个 / 只搬运不生成 STRM / 整理节流 / 明确「文件夹监控是纯扫描，不会替你整理」），`showMonitorHelp(kind = 'scan')` 按 `kind === 'inbox'` 分派标题与正文；`templates/partials/pages/monitor_about.html` 两个按钮分别传 `'inbox'` / `'scan'` 并各自补 `aria-label` / `title`；`tests.test_monitor_run_frontend` 断言两个 onclick 变体 + 两份文案，新增 `test_inbox_help_talks_about_inbox_not_scan`；`compileall app main.py`、改动 JS `node --check`、`git diff --check`、`handoff.md` 体积预算 32760/32768 均通过）。
- `scripts/check.sh --all` 全量 **1204 项零失败**（2026-10-07，非 115 接收夹的 webhook 对齐 + 任务名示例文案：弹窗里「推送地址」整块（地址 + 复制 + 油猴脚本说明）跟着开关一起收起、只留「立即整理并分发」，任务卡片简介改成「非 115 网盘不支持 Webhook」；服务端 `ensure_inbox_task` 归一化清掉非 115 接收夹的 `webhook_enabled`，`/webhook/{任务名}` 对非 115 接收夹直接 400；`syncMonitorNameHint()` 让任务名示例跟着类型走（接收夹「例如：接收」，非 115 带网盘名，扫描任务仍是「例如：自存影视」），非 115 接收夹的标签退回「任务名」；新增 `test_non_115_inbox_cannot_keep_webhook_enabled` / `test_rejects_webhook_for_non_115_inbox` / `test_monitor_name_hint_follows_task_type`；`compileall app main.py`、改动 JS `node --check`、`git diff --check`、`handoff.md` 体积预算均通过）。
- `scripts/check.sh --all` 全量 **1201 项零失败**（2026-10-07，两块任务列表各自新增、弹窗去掉「任务类型」下拉：类型改由入口决定——`static/js/index.js` 新增模块变量 `monitorFormType`（`openNewMonitorTask`=scan / `openNewInboxTask`=inbox / `editMonitorTask` 沿用任务原类型），`currentMonitorFormData` / `monitorFormTaskType` 改读它，删掉 `syncMonitorTaskTypeOptions`；`templates/partials/modals/monitor.html` 删类型下拉与 `monitor-task-type-hint`；`templates/partials/pages/monitor_about.html` + `static/css/index.css` 新增 `.monitor-head-actions--solo`，把「新增接收夹」按钮从整条宽度收成内容宽度右对齐；`tests.test_quick_import_frontend` 类型锁用例改为断言「弹窗里没有 `monitor_task_type`」；`docs/superpowers/modules.md` 同步入口口径。`compileall app main.py`、改动 JS `node --check`、`git diff --check`、`handoff.md` 体积预算 32518/32768 均通过）。
- `scripts/check.sh --all` 全量 **1201 项零失败**（2026-10-07，接收夹新增先选网盘 + webhook 只给 115 + 新建任务不再显示已有运行状态：`static/js/index.js` 新增 `inboxProvidersTaken` / `renderMonitorInboxProviderHint`（占用网盘 `disabled` + 说明，新建默认落到空闲网盘）/ `monitorWebhookProviderSupported`（非 115 接收夹的 webhook 开关禁用并说明可用手动 / 定时替代），`renderInboxTaskStatus` 无任务名时只渲染占位说明、`refreshInboxTaskStatus` 按 `editingMonitorName` 取 per-inbox 状态，`currentMonitorFormData` 落库前把非 115 接收夹的 `webhook_enabled` 清成 false；`templates/partials/modals/monitor.html` 把网盘选择移到共用路径框前面并新增 `monitor-inbox-provider-row` / `webhook-provider-hint`；`tests.test_quick_import_frontend` 新增 3 项用例；`compileall app main.py`、改动 JS `node --check`、`git diff --check`、`handoff.md` 体积预算 32706/32768 均通过）。
- `scripts/check.sh --all` 全量 **1198 项零失败**（2026-10-07，文件夹监控任务弹窗去掉 webhook 开关下方的大块参数说明、只留开关旁的「i」提示按钮：`templates/partials/modals/monitor.html` 删 `#webhook-hint`、`static/js/index.js` 删 `refreshWebhookHint()`、`boot.js` 改调 `renderMonitorWebhookUrl()`、`static/css/index.css` 删 `.monitor-webhook-hint` 样式；`tests.test_quick_import_frontend` 同步改写；`compileall app main.py`、改动 JS `node --check`、`git diff --check`、`handoff.md` 体积预算 32098/32768 均通过）。
- `scripts/check.sh --all` 全量 **1198 项零失败**（2026-10-07，接收夹改「每个网盘一个」：内置「接收」保留为 115 的接收夹、其他网盘可新增；`app/core.py` 按 provider 去重 + `get_inbox_tasks` / `get_inbox_task(name=)`，`app/services/quick_import.py` 的 build / validate / `is_quick_import_savepath` / `run_quick_import` / `get_quick_import_status` 全部按接收夹区分，`app/routes/monitor.py` webhook 按任务名分派；新增 `tests.test_quick_import.MultiInboxFanoutTest` 4 项 + `test_each_provider_keeps_its_own_inbox` + `get_inbox_task` 按名字取；`tests.test_quick_import_frontend` 类型锁 / 新增接收夹用例改写；`compileall app main.py`、改动 JS `node --check`、`git diff --check`、`handoff.md` 体积预算 32764/32768 均通过）。
- `scripts/check.sh --all` 全量 **1192 项零失败**（2026-10-07，监控自动整理残留清理 + 接收夹跨盘提示：结论行去掉「自动整理」列、`monitor_changes` 空转的「新增媒体条目」产线整段删除、接收夹目标跨盘时校验明确提示；`tests.test_monitor_log_readability` / `tests.test_quick_import` / `tests.test_scraper_monitor_sync` / `tests.test_monitor_dir_scan` 同步改写；`compileall app main.py cli.py`、改动 JS `node --check`、`git diff --check`、`handoff.md` 体积预算均通过）。
- `scripts/check.sh --all` 全量 **1196 项零失败**（2026-10-07，接收夹多网盘解耦 + 监控回归纯扫描 + 订阅自理整理：`tests.test_quick_import` / `tests.test_monitor_dir_scan` / `tests.test_scraper_batch_organize` / `tests.test_subscription_manual_offline` / `tests.test_cli_payloads` / `tests.test_scraper_monitor_sync` / `tests.test_quick_import_frontend` 等均更新；`compileall app main.py cli.py`、改动 JS `node --check`、`git diff --check`、`handoff.md` 体积预算 31529/32768 均通过）。
- `scripts/check.sh --all` 全量 **1187 项零失败**（2026-10-07，115 离线入库宽限期重扫：`app/services/subscription_task_runner.py` 新增 `_wait_for_subscription_offline_staging_meta()`，完成判定后宽限期重扫中转目录（30 秒 / 每 10 秒一次 / 最多 3 次）；失败详情补「已等待 N 秒」）。
- `scripts/check.sh --all` 全量 **1185 项零失败**（2026-10-07，提交前复跑：包含订阅「扫描链接」多条粘贴与 `check.sh` 的 `handoff.md` 体积预算闸门；`compileall`、改动 JS `node --check`、`handoff` 预算 31441/32768 字节、`git diff --check` 均通过）。
- `scripts/check.sh tests.test_modules_doc tests.test_rotate_handoff` **14 项零失败**（2026-10-07，`check.sh` 新增 `handoff.md` 体积预算闸门）：`bash -n scripts/check.sh` 通过；闸门红色路径实测（追加交接条目后 33522 > 32768 即失败，`HANDOFF_BUDGET_BYTES=1000` 同样返回退出码 1）、绿色路径实测（轮转后 31441 字节，退出码 0）；`rotate_handoff.py` 轮转后条目数 19 + 334 = 353 与轮转前一致；`git diff --check` 通过。
- `scripts/check.sh --all` 全量 **1185 项零失败**（2026-10-07，新增一键验证脚本 + `backup/` 移出仓库 + AGENTS.md「长行搜索必须 `--max-columns 300`」；脚本内同时跑 `compileall`、改动 JS 的 `node --check`、`git diff --check`）。
- 完整 `unittest discover -s tests -p 'test_*.py'` **1185 项零失败**（2026-10-07，订阅「扫描链接」支持一次粘贴多条：前端多条解析 / 提取码分段、后端 `links[]` 入队 / 去重 / 部分失败、队列批量只 kick 一次）；`compileall app main.py`、改动 JS `node --check`、`git diff --check` 通过。
- 完整 `unittest discover -s tests -p 'test_*.py'` **1172 项零失败**（2026-10-06，0.13.4 集数识别修复：破折号 + 空格两种末尾裸数字）；`version.json` 解析通过且与 `CHANGELOG.md` 顶部版本号一致；`compileall app main.py`、`git diff --check` 通过。
- 完整 `unittest discover -s tests -p 'test_*.py'` **1169 项零失败**（2026-10-06，「`剧名/Season NN` 不再重复套层」修复）；`compileall app main.py`、`git diff --check` 通过。
- 完整 `unittest discover -s tests -p 'test_*.py'` **1165 项零失败**（2026-10-06，0.13.2 影视广告识别补充整句式推广话术与“伪装视频”判定）；
  `compileall app main.py`、`git diff --check` 通过。
- 完整 `unittest discover -s tests -p 'test_*.py'` **1163 项零失败**（2026-10-04，0.13.1 接收夹同片多版本合并）；
  另有 `tests.test_quick_import` / `test_scraper_batch_organize` / `test_scraper_folder_reuse` 单跑通过；`version.json` 解析与 CHANGELOG 顶部版本号一致。
- 完整 `unittest discover -s tests -p 'test_*.py'` **1142 项零失败**（2026-09-29，随 0.13.0 元数据同步）。这是当时的快照，不是长期基线，改动后需重跑。
- `compileall app main.py`、改动 JS `node --check`、`git diff --check` 通过。
- **未验证**：Docker 重建后的容器页面，以及真实 115 账号重跑；结论只能按“单元/静态通过、实盘待验”表述。

## 待办 / 未完成

- 容器重建后实测**115 写操作「受理 + 回验落地」修复批**（未提交）：① 接收夹里同时来多部影视，点「立即整理并分发」不再出现「移动[...]操作尚未执行完成，请稍后再试!」，也不再出现「文件没搬走却先扫目录」；② 若 115 受理后 30 秒内没回验到落地，条目应留在接收夹并写明「已提交给 115，但等待落地确认超时」，同时目标目录的同步事件由 `needs_reconcile` 兜底补扫；③ 确认已落地的那一批仍然照常生成 STRM（`move_progress` 到 100 → 回验父目录 / 名字通过）。实盘只做过只读探测（列目录、进度查询、`get_info`），写入路径没有被真实重放过。
- 未做：①（2026-09-18 spec §五 遗留）115 系统目录（我的接收 / 最近接收 / 离线下载 / 礼包文件）当接收夹 / 目标的拦截与提示、整理链路的 source→target 审计记录；②（2026-10-08 新增）订阅的磁力 / 电驴离线入库（`app/services/subscription_task_runner.py:1536`）仍是「受理完就刷监控」——已吃到忙响应退避重试，但没接落地回验，做法见 `docs/superpowers/specs/2026-10-08-115-move-task-acceptance.md` §六。
- 容器重建后实测**接收夹按网盘隔离的修复批**（未提交）：① 115 与夸克各一个接收夹，点其中一张卡片的「立即整理并分发」，另一张不应进入运行中；② 在某张卡片点「中断」不应打断另一张正在跑的整理；③ 两张卡片的「最近接收 24 小时」「最近整理」互相独立（同名 `/接收` 不再串账）；④ 夸克分享转存进接收夹后大文件夹也能在宽限期内被整理（不再空跑「没有可整理的内容」）；⑤ 禁用其中一个接收夹后，资源导入弹窗提示「已停用，保存后不会自动整理」。
- 已定口径（2026-10-08）：**通知只保留文件夹监控与订阅两条，接收夹整理不推通知**（成功 / 失败 / 留守都只在监控日志与卡片状态里看），原计划的「Task 7 接收夹通知」取消；手工放进接收夹不自动触发（只能定时 / 手动 / webhook）、不同网盘不并行整理（一把全局锁顺序跑），均维持现状。
- 容器重建后实测**非 115 接收夹整理分发**（夸克 / 天翼 / 123 / 阿里）：点「立即整理并分发」能识别 → 整理 → 搬进同盘目标（不再报「目标路径操作当前仅支持 115」）；重点复核目标目录**没有**同名文件夹时（整包搬运）与**已有**同名文件夹时（并入）两条分支都走对网盘。
- 容器重建后复核目录选择弹窗：夸克 / 天翼 / 123 / 阿里接收夹点「选择文件夹」时标题应是「选择 夸克网盘 文件夹」这类（此前写死「选择 115 监控文件夹」）；弹窗里能就地「新建文件夹」，建完自动进入、再点「选择当前目录」保存；非 115 接收夹点「任务名」旁的 i 不再提 webhook 地址。
- 待用户拍板：编辑已有接收夹时要不要允许**改网盘**（现在下拉不做禁用，只在保存时按「每个网盘只能有一个」拦重复；如果要禁止，就在编辑态把网盘也锁成只读）。
- 容器重建后复核接收夹弹窗：弹窗里已无「任务类型」下拉——从「新增接收夹」进来是接收夹类型、从「新增任务」进来是目录同步类型、编辑已有任务沿用原类型；新增时网盘列表里已被占用的网盘置灰并提示「已有且只能有一个」、默认落到空闲网盘；非 115 接收夹的 webhook 开关置灰翻不动；新建时状态区只显示「保存任务后…」占位，不出现已有接收夹的最近整理 / 运行状态；「新增接收夹」按钮宽度与「新增任务」一致（内容宽度、右对齐，窄屏仍占满）。
- 待用户拍板：接收夹现在**一律不能删除**（服务端 `/monitor/delete` 返回 400「接收夹任务是内置的，不能删除」+ 卡片不给删除按钮）。用户自建的、非 115 的接收夹是否要允许删除，还是继续用「启用本任务」开关代替？
- 容器重建后实测**接收夹多网盘**：接收夹挂非 115 网盘（如夸克）时只搬运、不刷 STRM；115 上目标未落在任何目录同步任务扫描范围时也不刷；命中范围才刷。
- 容器重建后实测**接收夹跨盘目标**：接收夹在夸克、目标填 `/115/...` 时保存 / 运行应被明确拦下（提示「必须和接收夹在同一网盘」），不再退化成 `115/...` 这种相对路径去分发。
- 容器重建后实测**订阅自理整理**：电视剧新集入库后按「入库后整理」原地改名（standard + 中文标题、不建目录）；电影订阅不改名仍只刷 STRM；关掉开关后完全不改；`tmdb_id<=0` 的订阅跳过改名。
- `scripts/rotate_handoff.py` 有个待定边界：距上次写交接超过 14 天、当天又没追加新条目时运行它，会把 `handoff.md` 的条目**全部**归档（`--min-entries` 只作用于窗口内的条目，兜不住这种情况），结果会话开头的「最近交接」变空；是否改成「窗口外也至少保留 N 条」待确认。
- 容器重建后在订阅「扫描链接」弹窗一次粘贴多条磁力/电驴链接，复核排队顺序、离线入库与命中挑选链路。
- 容器重建后用真实 115 订阅复核：`Renegade Immortal – 仙逆 Xian NI – 154.mkv`（破折号）与 `仙逆 154.mp4`（空格）这类「片名 + 分隔符 + 裸数字」文件都能被解析成第 154 集并被选中入库（旧口径下解析为空集、文件被直接跳过）。
- 容器重建后用真实 115 / 订阅链复核：订阅落进 `仙逆/Season 01` 的新集不再被自动整理搬进 `仙逆 (2023)/`；历史遗留的 `仙逆/仙逆 (2023)/Season 01/…` 是否需要回搬待用户确认。
- 0.14.0 的代码（接收夹解耦批已提交的 5 个提交 + 未提交的「按网盘隔离」三层）与发布元数据已就绪：5 个提交待推送 / 打 tag，未提交改动待提交，之后重建容器部署。
- 容器重建后用真实接收夹复核：整段名字只有推广话术的假 `.mkv/.mp4` 只被忽略（开启“删除广告文件”时才删除），不再被识别成正片；同口径已扩到 `.mkv.strm` / `.DOC` 与叠后缀（剥后缀 + 去网址后再判残留），且文件夹监控扫描 / 变更同步 / 目录树都不再为这类名字生成 STRM，上一轮已生成的本地 `.mkv.strm` 会被过期清理删掉。
- 容器重建后手动触发一次接收夹整理，确认同一部影视的多个版本/多个条目合并进同一个媒体文件夹（第二条文件名带 `(2)`），发行组命名的空壳目录被清理。
- 真实 115 重跑确认 `Curb.Your.Enthusiasm` S09/S10/S11 整季包落季与季包残留（`RARBG.txt`/空 `Subs`）清理。
- job #145 的 40 条错名字幕是否需要回改，待用户确认。
- 本地 0.13.0 容器重建与页面复核（按 `AGENTS.md` 的代理配置执行 `docker compose up -d --build`）。
- 容器重建后实测刮削页「扫描监控」：运行详情只应出现 STRM 生成，不再有自动整理动作（自动整理入口已在本次整段删除，代码层已保证）。

## 当前需要知道的上下文

- 接收夹（inbox）是**可选中转入口**，不是强制流程；旧的“直接推送到电影/电视剧监控目录”用法继续有效，两种并存。详细口径见 `conventions.md`。
- 接收夹**与网盘无关**：任务上的 `provider` 决定它挂在哪块盘（默认 115），**每个网盘一个**——内置的「接收」保留为 115 那份，其他网盘在「文件夹监控」页点「新增接收夹」各加一个；同一个网盘重复添加会被拦下，配置归一化也按 provider 去重、只保留第一个。分发目标必须**同盘**（`distribute_targets` 存远程路径，含挂载前缀）；只有 115 且目标命中某个目录同步任务扫描范围才刷 STRM，其他网盘只搬运（v1 不做跨盘分发 / 跨盘 STRM）。
- **自动整理只有两个入口**：接收夹负责“分类归档”（重命名后搬进同盘分类目录）、订阅负责“自理”（电视剧新集入库后原地改名）。文件夹监控是**纯扫描**——含「扫描监控」按钮、变更同步、Webhook、定时、卡片「运行」，都只生成 / 同步 STRM，不整理。
- “文件夹监控”与“接收夹”是两套触发方式，共用同一个全局 `webhook_secret`，但接收后的处理链路不同。
- 当前设计文档入口：`docs/superpowers/specs/2026-09-23-folder-monitor-workflow-design.md`（文件夹监控与接收夹）、`docs/superpowers/specs/2026-09-26-folder-receive-monitor-runtime-design.md`（运行时）。
- **功能模块索引**：`docs/superpowers/modules.md` 记录每个模块的用途 / 入口 / 会做 / 不会做；新增或改名路由、服务、provider、页面模板必须登记，`tests/test_modules_doc.py` 会校验覆盖率。
- **接收夹同一部影视合并**：同一 TMDB 条目的多个条目（电影多版本、同剧多季包）整理时会落进同一个媒体文件夹——文件夹撞名只保留一次改名、文件同名给后面的加 `(2)`；某个条目自己的冲突只留它自己，不连累同批其他条目。口径见 `conventions.md`。
