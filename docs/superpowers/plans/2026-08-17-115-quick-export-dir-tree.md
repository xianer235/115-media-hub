# 115 快捷生成目录树 Implementation Plan

> **For agentic workers:** 按 Task 顺序实施，每步先写失败测试再实现。步骤使用 checkbox（`- [ ]`）跟踪。

**Goal:** 用户无需再去 115 生活 APP 手动生成目录树。在目录树同步页内选择 115 文件夹，调用官方服务端“导出目录树”接口生成树文件（同名、同层级替换旧文件），并可一键解析写入 STRM；生成的树可自动并入现有树源配置，定时同步/MD5 跳过继续生效。

**Architecture:** 复用现有 Cookie 直连 115 的能力（`pan115.py` 已有 webapi 封装、`tree.py` 已有下载/解析/STRM 写入管线）。新增：官方导出目录树接口封装、快捷生成任务编排（提交→轮询→下载留底→删旧→原地重命名→可选并入树源+触发同步）、`tree_export_jobs` 任务表、目录树同步页 UI（树源配置从设置页迁入 + 快捷生成表单 + 任务记录）。解析写入复用 `run_sync`，其余树源靠 MD5 跳过。

**Tech Stack:** Python 3、FastAPI 服务层、SQLite、`unittest`、原生 JS

---

## 已锁定的事实与规则

- 官方“导出目录树”是服务端异步任务：
  - 提交：`POST https://webapi.115.com/files/export_dir`，表单参数 `file_ids`（文件夹 id）、`target`（格式 `U_{aid}_{pid}`，默认 `U_1_0`）、`layer_limit`（0~25，不传=全部）、`not_suffix`。
  - 轮询：`GET https://webapi.115.com/files/export_dir?export_id=<id>`，`data` 为空=运行中；完成返回 `{export_id, file_id, file_name, pick_code}`。
  - 约束：同一时刻仅允许一个导出任务（不可并发、不可中止、超时自动取消）；空目录不导出；生成的文件不产生 life 事件。
- 树文件为 UTF-16 文本，行格式 `| `×深度 + `|-` + 名称；**首行第一个分隔符为空**（如根目录下 A 文件夹导出为 `|——A` 开头），解析器跳过空层后 A 落在第 1 层。
- 导出内容**以所选文件夹的父级为根**（真实校准 2026-08-17）：根级文件夹导出首行为 `|——根目录`，二级文件夹导出首行为 `|——父级`（如 `|——115影视小库` → `| |-电视剧小库`）。因此默认**排除层级=1**（去掉导出根层），**父文件夹路径前缀**自动填所选文件夹的父级链（根级文件夹为空），STRM 路径恢复为 `影视库/电视剧/...`。
- 树文件放置：与所选文件夹**同层级**（同父目录），文件名默认 `目录树.txt`，可改。
- 替换顺序：先下载新内容留底 → 删除同层级同名旧文件（进回收站）→ 原地重命名新文件；失败时本地留底仍在，旧文件可回收站恢复。
- 真实校准结论（Task 0 已完成）：`files/export_dir` 提交/轮询/结果字段确认；生成文件落在根目录，服务端命名为 `根目录<时间戳>_目录树.txt`（无规律）；UTF-16 编码；根目录列表可拿 `sha1`；`target=U_1_0`（aid=1）可用。

---

## 总体交互流程

1. 目录树同步页顶部为**树源配置**（从设置页迁入，含同步策略），维护 `path / 父文件夹路径前缀 / 排除层级`；
2. 中部为**快捷生成目录树**任务表单：文件选择器选文件夹 → 自动填充（树文件名=`目录树.txt`、位置=文件夹同级、父文件夹路径前缀=文件夹相对路径、排除层级=1）→ 用户可改 → 勾选“解析写入 STRM”；
3. 提交后生成后台任务并串行执行：提交官方导出（target=文件夹父目录）→ 轮询 → 下载留底 → 删除同层同名旧文件（回收站）→ 原地重命名 → （勾选时）并入/更新树源配置并触发 `run_sync`；
4. 任务记录列表展示最近任务（目录/树文件/状态/时间/export_id/文件名/条数），失败可重试；
5. 设置页不再出现任何目录树相关配置。

## 页面布局（目录树同步 tab）

自上而下分区卡片：**树源配置（含同步策略）** → **快捷生成目录树** → **任务记录** → **日志**。树源列表每行保留现有三列（树文件路径/父文件夹路径前缀/排除层级）+ 删除按钮；快捷生成表单在树源列表下方，避免与日志长列表混排。

---

### Task 1: 115 导出目录树接口封装

**Files:**
- Modify: `app/providers/pan115.py`
- Add: `tests/test_115_export_dir.py`

- [x] **Step 1: 写接口封装失败测试**

Mock `http_request_form_json` 与 `_request_115_webapi_json`，覆盖：提交成功返回 `export_id`、提交缺少 export_id 报错、轮询运行中返回空、轮询完成返回 `file_id/file_name/pick_code`、轮询超时抛带 export_id 的异常、115 拒绝（已有任务在跑）的清晰报错。

- [x] **Step 2: 实现 `submit_115_export_dir`**

`POST https://webapi.115.com/files/export_dir`，参数 `file_ids/target/layer_limit`，复用 `http_request_form_json` 与现有 115 headers，接入 Cookie 健康标记；返回 `data.export_id`。

- [x] **Step 3: 实现 `query_115_export_dir_status` 与 `wait_115_export_dir`**

GET 查询接口；`wait` 按 `check_interval`（默认 2 秒）轮询并走 `throttle_115_api_requests()`，完成返回结果字典，超时抛 `RuntimeError`（消息含 export_id，便于后续补查）。

- [x] **Step 4: 运行定向测试**

Run: `PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m unittest tests.test_115_export_dir`

Expected: PASS。

### Task 2: 快捷生成任务编排与任务表

**Files:**
- Modify: `app/db.py`（建表迁移 `tree_export_jobs`）
- Modify: `app/services/tree.py`（编排函数；下载/解析复用已有内部函数）
- Modify: `app/routes/tree.py`（`POST /tree/quick-export`、`GET /tree/quick-export/jobs`）
- Add: `tests/test_tree_quick_export.py`

- [x] **Step 1: 建 `tree_export_jobs` 表**

字段：`id, folder_path, folder_id, tree_path, tree_name, prefix, exclude, write_strm, export_id, file_id, file_name, pick_code, status, error, submitted_at, completed_at, synced_at, parsed_count, generated_count, created_at`。

- [x] **Step 2: 写编排失败测试（mock 115 接口）**

覆盖：提交→轮询→下载→删旧→重命名顺序与参数；同名旧文件不存在时跳过删除；解析开关开启时树源 upsert（同名 `path` 更新父文件夹路径前缀/排除层级）并触发 `run_sync`；未开启时不动配置不触发；导出 busy/超时/路径不存在分别落库失败且消息明确；任务串行（115 单任务约束）且并发提交只入队一个。

- [x] **Step 3: 实现单任务锁与队列**

模块级锁 + `task_status` 守卫，一次只允许一个导出任务；重复提交返回 `queued` 或明确报“已有导出任务在运行”。

- [x] **Step 4: 实现任务编排 `run_tree_task(task_id, full)`**

1) 校验 Cookie/文件夹路径，解析 folder_id 与父目录 id；2) 提交导出，`target=U_1_{父目录id}`；3) `wait` 轮询；4) 用 `pick_code` 下载字节并保存留底（`TREE_DIR/quick_<job_id>.txt`）；5) 解析目标路径同层同名旧文件并删除（进回收站）；6) 对导出文件 `rename_115_entry` 为配置名；7) 勾选解析时 upsert 树源并 `submit_background(run_sync)`；8) 更新任务记录与进度日志。

- [x] **Step 5: 实现路由**

`POST /tree/quick-export`（folder_path/tree_name/prefix/exclude/write_strm）、`GET /tree/quick-export/jobs`（最近 N 条，含 status/export_id/file_name/时间）。

- [x] **Step 6: 运行定向测试**

Run: `PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m unittest tests.test_tree_quick_export`

Expected: PASS。

### Task 3: 目录树同步页 UI 重构（配置迁入 + 快捷生成表单）

**Files:**
- Modify: `templates/partials/pages/task.html`（目录树同步 tab：树源列表 + 同步策略 + 快捷生成表单 + 任务记录）
- Modify: `templates/partials/pages/settings.html`（移除目录树源/同步策略 section）
- Modify: `static/js/index.js`（`addTreeRow` 等逻辑随迁；新增快捷生成表单、自动填充、任务记录渲染、重试按钮）
- Add/Modify: `tests/test_tree_page_frontend.py`

- [x] **Step 1: 写前端迁移回归测试**

断言：设置页不再包含 `settings-tree-sources`/`settings-tree-sync`；任务页包含树源列表、同步策略控件、快捷生成表单与任务记录容器。

- [x] **Step 2: 迁移树源配置与同步策略 UI**

把设置页 section 3/4（树源配置 + 同步策略）迁入目录树同步 tab，字段名保持 **父文件夹路径前缀** 不变，说明更新为“导出内容不含上级目录，父文件夹路径前缀=所选文件夹完整相对路径，排除层级默认 1（去掉首层文件夹自身）”。

- [x] **Step 3: 实现快捷生成表单与自动填充**

文件夹选择复用现有 115 浏览组件/接口（`GET /resource/browse` 同款）；选择后自动填充：树文件名=`目录树.txt`、位置=文件夹同级（只读提示）、父文件夹路径前缀=文件夹相对路径、排除层级=1，均可修改；开关“解析写入 STRM”（默认开）。

- [x] **Step 4: 任务记录与重试**

渲染最近任务（目录/树文件/状态/时间/export_id/文件名/条数），失败任务提供“重试”按钮（重新排队，busy 时提示）。

- [x] **Step 5: 运行前端回归与静态检查**

Run: `PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m unittest tests.test_tree_page_frontend`、改动 JS `node --check`。

Expected: PASS。

### Task 4: 全量回归与静态检查

- [x] **Step 1: 运行完整测试**

Run: `PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m unittest discover -s tests`

Expected: 全量 PASS（现有 473 项 + 新增）。

- [x] **Step 2: 语法与差异检查**

Run: `PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m compileall app main.py`、`git diff --check`。

Expected: 全部通过。

### Task 5: 真实账号校准与容器验证

> 本任务含**写操作**（会在网盘生成树文件），需用户明确同意后执行；校准完成后删除临时文件。

- [x] **Step 1: 最小导出样例校准**

已用真实账号完成根级（`115自存电视剧`）与二级（`115影视小库/电视剧小库`）两次最小导出：确认响应字段、落盘根目录、首行 `|——根目录`/`|——父级` 空分隔符、UTF-16 编码、根目录列表可取 sha1；临时文件已删除（回收站可恢复）。

- [ ] **Step 2: Docker 重建与页面实测（待 Docker daemon 可用后执行）**

Run: `export HTTP_PROXY=http://127.0.0.1:7897; export HTTPS_PROXY=http://127.0.0.1:7897; export NO_PROXY=localhost,127.0.0.1,registry-1.docker.io; docker compose up -d --build`

实测：树源配置在同步页可增删改；快捷生成选文件夹自动填充参数；任务状态流转（提交→导出中→替换→同步→完成）；STRM 路径与文件夹结构一致；生成记录留痕；重试与 busy 提示。

---

## 决策点（实施前确认）

1. **同步策略随源配置一起迁入同步页** —— ✅ 已确认（注意页面布局分区，见“页面布局”一节）。
2. **“解析写入 STRM”的语义** —— ✅ 已确认：勾选 = 并入/更新树源配置 + 触发 `run_sync`；不勾选 = 只生成替换文件，不动配置。
3. `target` 的 `U_{aid}_{pid}` 假设 `aid=1` —— ✅ Task 0 真实校准已确认可用。

## 风险与兜底

- 115 单导出任务限制 → 全局串行 + busy 明确报错。
- 导出超时不可取消 → 任务保留 `export_id`，失败信息可查，用户可稍后重试（新任务）。
- 删旧后重命名失败 → 本地已留底，旧文件在回收站可恢复，任务落 failed 并提供重试。
- 同一树文件路径被多个文件夹映射 → 提交时校验冲突并警告。
