# 接收夹多网盘解耦 + 监控回归本职 + 订阅自理整理

> 实施计划。目标读者是执行本方案的工程师 / 低思考模型：请严格照做，不要自行决策、
> 不要扩大范围；遇到方案未覆盖但必须决定的点，停下来问用户，不要猜。
> 日期 2026-10-07，版本基线 0.13.4（`version.json` 为准）。

## 一、目标与范围

1. 接收夹不再写死 115，支持选择任意网盘；分发目标从「监控任务名」改为「同盘上用户选择的文件夹」。
2. 分发后是否刷新 STRM 改为按包含关系自动判定：目标落在 115 某个监控任务扫描范围内才刷新，普通文件夹或其他网盘只移动、不处理。
3. 监控任务删除「新增资源自动整理」，回归纯扫描 + STRM。
4. 订阅改为自理整理自己的电视剧新集（原地改名）；电影订阅不改名、只刷 STRM。
5. 文件夹监控标签页上下分区：上部「接收夹整理」，下部「目录同步」；运行记录共用一张表 + 现有流程筛选。

明确不做：跨盘分发、其他网盘生成 STRM、目录树 / 播放代理扩展（继续仅 115）。

**实施顺序与耦合**：第二步（删监控自动整理）和第三步（订阅自理整理）必须**同一批提交、同一版本发布**。删掉监控自动整理后，订阅新集就没有任何整理入口了，直到第三步落地；中间态会静默丢整理，禁止单独交付第二步。

## 二、前置阅读与硬约束

- 开工前读 `docs/superpowers/state.md`、`docs/superpowers/conventions.md`、`docs/superpowers/modules.md`。
- 遵守 `AGENTS.md` 阅读纪律：`rg` 长行文件加 `--max-columns 300`，不要整读 `app/core.py` 等大文件。
- 全程用 `.venv/bin/python`；语法验证加 `PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache`。
- 不提交、不推送、不改 `version.json` / `CHANGELOG.md` / `README.md`。
- 不新写命名规则，全部复用现有刮削引擎 `app/services/scraper.py`。

## 三、第一步：接收夹多网盘 + 目标改文件夹

涉及：`app/services/quick_import.py`、`app/services/monitor.py`、`app/core.py`、`app/routes/monitor.py`、`app/routes/resource.py`、`static/js/index.js`。

- 删除 `app/services/quick_import.py:39` 的常量 `QUICK_IMPORT_PROVIDER = "115"`，全文件 19 处引用全部改成从接收夹任务读取的 provider（默认 `"115"`，用 `normalize_mount_provider` 归一化）。
- 接收夹任务新增 `provider`（默认 `"115"`）与 `auto_scrape_options`（整理选项）两个字段；在 `build_quick_import_config` 里从 `get_inbox_task(cfg)` 读取。
- **注意 `queue_inbox_dispatch_scan`（`app/services/monitor.py:2690`）内部也写死了 `"115"`**：给它加一个 `provider` 参数，并把它内部 `queue_monitor_dir_scan(cfg, "115", ...)` 的 `"115"` 换成该参数。`_queue_dispatch_child_run` 调它时传入 inbox provider。
- `distribute_targets` 值语义从「监控任务名」改为「远程文件夹路径（含挂载前缀，如 `/115/自存影视`）」。
- **迁移落点**：任务名 → `scan_path` 的换算必须放在「同时能看到 inbox 任务和 `monitor_tasks` 全表」的地方，不能在 `normalize_distribute_targets`（`app/core.py:1145`，它只有单个 target 值、没有任务表）。推荐放在 `get_config` / 配置 merge 的归一化收口（`app/core.py` 约 2822 附近的 `monitor_tasks` 归一化），或在 `ensure_inbox_task` 里。规则（幂等）：值能匹配到某扫描任务名且不是合法远程路径 → 替换成该任务 `scan_path`；匹配不到 → 清空目标，由校验提示用户重选。迁移后若目标是合法远程路径就不要再动。
- `_inbox_rel_path` / `_task_rel_path` 里 `resolve_provider_relative_path(..., expected_provider=...)` 改用 inbox provider。
- `build_quick_import_config` 的 targets 构建改为：目标 = 远程路径 → 用 inbox provider 解析出相对路径；整理选项不再从目标任务继承，改从 inbox 任务自身 `auto_scrape_options` 读（复用 `_normalize_scraper_batch_preferences`）。
- 分发后刷 STRM：仅当 inbox provider == `"115"` 且目标 rel_path 落在某监控任务 scan_path 内时，才排队子树扫描（`run_source="inbox_dispatch"`）；非 115 或未命中监控任务时跳过。`_queue_dispatch_child_run` / `_queue_dispatch_child_runs` 里写死的 provider 换成 inbox provider，并在不满足条件时返回空。
- `is_quick_import_savepath` 增加 provider 语义：**provider 从 inbox 配置内部推导**（`build_quick_import_config` 已有 inbox provider），不要指望调用方传（savepath 是相对路径、不带 provider）。用 inbox provider 解析 savepath，只有「同盘 + 相对路径落在接收夹内」返回 True。调用方：`app/routes/resource.py` 两处、`app/routes/monitor.py` 一处。
- `validate_quick_import_config`：路径重叠校验只比较同 provider 的扫描任务；「接收文件夹必须位于 115 网盘前缀下」改为按 inbox provider 动态提示。
- 文件内所有 `list_scraper_entries` / `find_scraper_media_folder` / `move_scraper_entries` / `delete_scraper_entries` / `resolve_scraper_dest_folder_id` 的 provider 参数改成 inbox provider。

## 四、第二步：监控删除自动整理

涉及：`app/services/monitor.py`、`app/core.py`、`static/js/index.js`、`templates`（如需要）。

- 删除 `run_monitor_task` 里对 `_auto_scrape_new_media_items` 的两个调用（一个带 `dir_scan_only` 判断、一个不带），删除不再被引用的 `_auto_scrape_new_media_items` 函数。
- **同时删除 `dir_scan_only` 的推导块（`app/services/monitor.py:976` 附近）**，以及它对应的跳过日志；它只为「扫描监控按钮跳过自动整理」存在，自动整理没了它整段都是死代码。
- 保留 `queue_monitor_dir_scan` 与 `queue_inbox_dispatch_scan`（接收夹分发还要用）。
- `normalize_task`（`app/core.py`）移除 `auto_scrape_on_new` / `auto_scrape_options` 的归一化输出；旧配置这两个字段可接受但直接丢弃。
- 前端监控任务编辑表单删除「新增资源自动整理」开关与选项块，删除 `monitor_auto_scrape_on_new`、`collectMonitorAutoScrapeOptions`、`syncMonitorAutoScrapeOptions`、`applyMonitorAutoScrapeOptions` 相关代码；删前先 `rg` 确认引用范围，别误删接收夹 / 刮削页仍在用的同名逻辑。
- 同步 `conventions.md` 与 `modules.md`：监控「不会做」从「自动整理只在新资源入盘链路」改为「任何扫描都不整理、只生成 / 同步 STRM」。

## 五、第三步：订阅自理整理

涉及：`app/services/subscription_task_runner.py`、`app/services/subscription.py`、`app/core.py`、`app/routes/subscription.py`、`templates/partials/pages/subscription.html`、`static/js`（订阅表单）。

- 订阅任务 schema 新增 `organize_on_import`（bool，默认 true）与 `organize_options`（复用 `_normalize_scraper_batch_preferences` 的字段集）。
- 归一化默认：`organize_on_import` 默认 true；`organize_options` 默认 = `title_language "zh"`、`file_name_mode "standard"`、`episode_mode "auto"`、`delete_ad_files false`，其余用 `_normalize_scraper_batch_preferences` 默认。**注意 `title_language "zh"` 是对引擎默认 `"auto"` 的有意覆盖，不要照抄引擎默认**。存量订阅统一默认 true，不做逐任务继承旧监控开关。
- **改名入口用 `build_scraper_rename_plan`（`app/services/scraper.py:3115`），不是 `_auto_scrape_new_media_items` / `build_scraper_organize_plan`**。后者会强制 `force_media_folder=True`、把文件归档进 `片名 (年份)/` 并移动，且写死 115，与「原地改名」相反。
- 触发条件：`media_type == "tv"` 且 `organize_on_import == true` 且订阅任务 `tmdb_id > 0`。三者任一不满足就跳过改名。
- TMDB 绑定来源：直接用订阅任务自带的 `tmdb_id` / `tmdb_media_type` / `tmdb_title` / `tmdb_year` / `tmdb_season_episode_map`（`normalize_subscription_task` 已产出，见 `app/core.py:2255` 附近）。构造 `build_scraper_rename_plan` 的 `payload["tmdb"]` 时带上这些字段。
- 文件条目来源：对本次新入库的文件，**不要假设 move 会保留原 fid**。用 `list_entries(target_cid)` 按「文件名 + 大小」匹配到目标盘文件，取其 fid 构造单个文件条目（`is_dir=False`、`parent_id=target_cid`、`parent_path=target_savepath`）。离线路径和分享/转存路径都要这么拿目标文件 id。
- 调用参数：`provider` = 订阅任务 provider；`base_cid=target_cid`、`base_path=target_savepath`；`options` 用 `organize_options`（`file_name_mode=standard` 得到 `标题 - S01E154.ext`，标题来自 `tmdb_title`）；`entries` 为上述单文件条目。这样 `folder_mode=False` → 只原地改文件名、不建目录、不移动。
- 改名结果兜底：`tmdb_id <= 0`、识别失败、计划为空或执行失败时保留原名并写订阅日志，不阻塞入库、不报错。
- `media_type == "movie"`：跳过改名。
- 改名后照旧 `queue_monitor_job(matched_name, "subscription", ...)` 刷 STRM（只有 115 且命中监控任务才排队，现有判断不变）。
- 前端订阅编辑表单加「入库后整理」开关 + 整理选项（标题语言 / 命名方式 / 是否删除广告文件），默认勾选、默认 standard + 中文 + 自动集数。

## 六、第四步：页面分区

涉及：`templates/partials/pages/monitor_about.html`、`static/js/modules/tabs/monitor.js`、`static/js/index.js`。

- 接收夹现在只是 `monitor_tasks` 里 `task_type=inbox` 的一张卡片，和扫描卡一起由 `renderMonitorTasks` 渲染。拆成独立 section 时要：按 `task_type` 过滤——上部只渲染 inbox 卡，下部只渲染 `task_type=scan` 卡；「新增任务」按钮只新建扫描任务；接收夹专属字段（webhook、分发目标、静默窗口等）随 inbox 卡一起迁到上部。
- 接收夹卡片加：provider 下拉、电影 / 电视剧两个目标文件夹选择器（只列同盘目录）、整理选项。
- 运行记录保持共用一张表 + 现有「流程类型」筛选，不拆分。

## 七、第五步：文档同步

- `modules.md`：更新「接收夹」「文件夹监控」「影视订阅」三个模块的「会做 / 不会做」边界。
- `conventions.md`：新增 / 改写四条长期口径——接收夹与网盘无关、整理入口收敛（订阅自理电视剧 + 接收夹负责分类归档）、监控纯扫描、订阅原地改名不建目录。
- `state.md` 更新基线 / 待办；`handoff.md` 追加一行交接记录并运行 `.venv/bin/python scripts/rotate_handoff.py`。

## 八、验证

- 语法：`PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m compileall app main.py`
- 相关测试：`scripts/check.sh tests.test_quick_import tests.test_monitor_dir_scan tests.test_monitor_webhook_quick_import tests.test_scraper_batch_organize tests.test_subscription_manual_offline tests.test_modules_doc`
- 全量：`scripts/check.sh --all`
- 改动 JS 逐个 `node --check`（`check.sh` 会自动挑，建议手动再跑一次改动文件）。
- 补齐 / 更新用例：接收夹多网盘与迁移、115 命中监控范围才刷 STRM、`is_quick_import_savepath` 带 provider、监控不再自动整理、订阅电视剧原地改名、订阅电影不改名仍刷 STRM、订阅开关关闭不改名、订阅 `tmdb_id<=0` 跳过改名。

## 九、假设与默认值

- v1 只做同盘分发；其他网盘不生成 STRM；目录树 / 播放代理继续仅 115。
- 订阅整理严格原地改名，不承担「归档进片名文件夹」职责（那是接收夹的活）；电影订阅 v1 一律不改名。
- 订阅改名只在任务 `tmdb_id > 0` 时进行；无 TMDB 绑定的订阅保持原名。
- 存量监控任务的整理开关直接废弃，不迁移到接收夹选项；接收夹整理选项用默认值起步。
- 存量订阅的整理开关统一默认开启，不做逐任务继承旧监控开关。
- 整理选项默认：standard 命名、中文标题（覆盖引擎默认 auto）、自动集数识别、不删广告文件。
