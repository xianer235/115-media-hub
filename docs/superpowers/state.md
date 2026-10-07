# 项目当前状态

> 这是**每次会话开头唯一需要完整阅读**的状态文件，目标 ≤80 行。
> 最近交接条目：`docs/superpowers/handoff.md`；历史条目：`docs/superpowers/handoff-archive.md`
> （通常不用读，`rg "关键词" docs/superpowers/handoff-archive.md` 按需检索）。
> 长期不变的架构与产品口径：`docs/superpowers/conventions.md`。
>
> 维护方式：只写“现在是什么状态”，不写历史。有实质进展或发布后更新本文件，
> 历史过程写进 `handoff.md` 条目。

## 基线

- **更新日期**: 2026-10-07
- **分支**: `main`，与 `origin/main` 同步
- **版本**: `0.13.4`（`version.json` 是唯一真源，与 `CHANGELOG.md` 顶部一致）
- **最近提交**: `4f9ef59` 集数识别补「片名 + 破折号/空格 + 裸数字」写法（2026-10-06，0.13.4 元数据已随提交入库）
- **工作区**: 有未提交改动（最新一批：接收夹多网盘解耦 + 监控回归纯扫描 + 订阅自理电视剧原地改名——`app/core.py` / `app/services/quick_import.py` / `app/services/monitor.py` / `app/services/subscription_task_runner.py` / `cli.py` / `static/js/index.js` / `static/js/modules/subscription/ui.js` / `templates/partials/modals/monitor.html` / `templates/partials/modals/subscription.html` / `templates/partials/pages/monitor_about.html` + 回归与文档；同批收尾还有结论行去掉「自动整理」列、`monitor_changes` 空转的「新增媒体条目」产线删除、接收夹分发目标跨盘提示；此前还有 订阅「扫描链接」多条粘贴、`scripts/check.sh` 一键验证与 `handoff.md` 体积预算、115 离线入库宽限期重扫 等，均未提交。最近条目见 `handoff.md` 顶部）

## 最近一次验证

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

- 容器重建后实测**接收夹多网盘**：接收夹挂非 115 网盘（如夸克）时只搬运、不刷 STRM；115 上目标未落在任何目录同步任务扫描范围时也不刷；命中范围才刷。
- 容器重建后实测**接收夹跨盘目标**：接收夹在夸克、目标填 `/115/...` 时保存 / 运行应被明确拦下（提示「必须和接收夹在同一网盘」），不再退化成 `115/...` 这种相对路径去分发。
- 容器重建后实测**订阅自理整理**：电视剧新集入库后按「入库后整理」原地改名（standard + 中文标题、不建目录）；电影订阅不改名仍只刷 STRM；关掉开关后完全不改；`tmdb_id<=0` 的订阅跳过改名。
- `scripts/rotate_handoff.py` 有个待定边界：距上次写交接超过 14 天、当天又没追加新条目时运行它，会把 `handoff.md` 的条目**全部**归档（`--min-entries` 只作用于窗口内的条目，兜不住这种情况），结果会话开头的「最近交接」变空；是否改成「窗口外也至少保留 N 条」待确认。
- 容器重建后在订阅「扫描链接」弹窗一次粘贴多条磁力/电驴链接，复核排队顺序、离线入库与命中挑选链路。
- 容器重建后用真实 115 订阅复核：`Renegade Immortal – 仙逆 Xian NI – 154.mkv`（破折号）与 `仙逆 154.mp4`（空格）这类「片名 + 分隔符 + 裸数字」文件都能被解析成第 154 集并被选中入库（旧口径下解析为空集、文件被直接跳过）。
- 容器重建后用真实 115 / 订阅链复核：订阅落进 `仙逆/Season 01` 的新集不再被自动整理搬进 `仙逆 (2023)/`；历史遗留的 `仙逆/仙逆 (2023)/Season 01/…` 是否需要回搬待用户确认。
- 0.13.3 的代码修复（`scraper.py` + 4 项回归）、文档与发布元数据已就绪，待提交 / 推送 / 打 tag，之后重建容器部署。
- 容器重建后用真实接收夹复核：整段名字只有推广话术的假 `.mkv/.mp4` 只被忽略（开启“删除广告文件”时才删除），不再被识别成正片。
- 容器重建后手动触发一次接收夹整理，确认同一部影视的多个版本/多个条目合并进同一个媒体文件夹（第二条文件名带 `(2)`），发行组命名的空壳目录被清理。
- 真实 115 重跑确认 `Curb.Your.Enthusiasm` S09/S10/S11 整季包落季与季包残留（`RARBG.txt`/空 `Subs`）清理。
- job #145 的 40 条错名字幕是否需要回改，待用户确认。
- 本地 0.13.0 容器重建与页面复核（按 `AGENTS.md` 的代理配置执行 `docker compose up -d --build`）。
- 容器重建后实测刮削页「扫描监控」：运行详情只应出现 STRM 生成，不再有自动整理动作（自动整理入口已在本次整段删除，代码层已保证）。

## 当前需要知道的上下文

- 接收夹（inbox）是**可选中转入口**，不是强制流程；旧的“直接推送到电影/电视剧监控目录”用法继续有效，两种并存。详细口径见 `conventions.md`。
- 接收夹**与网盘无关**：任务上的 `provider` 决定它挂在哪块盘（默认 115），分发目标必须**同盘**（`distribute_targets` 存远程路径，含挂载前缀）；只有 115 且目标命中某个目录同步任务扫描范围才刷 STRM，其他网盘只搬运（v1 不做跨盘分发 / 跨盘 STRM）。
- **自动整理只有两个入口**：接收夹负责“分类归档”（重命名后搬进同盘分类目录）、订阅负责“自理”（电视剧新集入库后原地改名）。文件夹监控是**纯扫描**——含「扫描监控」按钮、变更同步、Webhook、定时、卡片「运行」，都只生成 / 同步 STRM，不整理。
- “文件夹监控”与“接收夹”是两套触发方式，共用同一个全局 `webhook_secret`，但接收后的处理链路不同。
- 当前设计文档入口：`docs/superpowers/specs/2026-09-23-folder-monitor-workflow-design.md`（文件夹监控与接收夹）、`docs/superpowers/specs/2026-09-26-folder-receive-monitor-runtime-design.md`（运行时）。
- **功能模块索引**：`docs/superpowers/modules.md` 记录每个模块的用途 / 入口 / 会做 / 不会做；新增或改名路由、服务、provider、页面模板必须登记，`tests/test_modules_doc.py` 会校验覆盖率。
- **接收夹同一部影视合并**：同一 TMDB 条目的多个条目（电影多版本、同剧多季包）整理时会落进同一个媒体文件夹——文件夹撞名只保留一次改名、文件同名给后面的加 `(2)`；某个条目自己的冲突只留它自己，不连累同批其他条目。口径见 `conventions.md`。
