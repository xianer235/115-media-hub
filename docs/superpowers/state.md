# 项目当前状态

> 这是**每次会话开头唯一需要完整阅读**的状态文件，目标 ≤80 行。
> 最近交接条目：`docs/superpowers/handoff.md`；历史条目：`docs/superpowers/handoff-archive.md`
> （通常不用读，`rg "关键词" docs/superpowers/handoff-archive.md` 按需检索）。
> 长期不变的架构与产品口径：`docs/superpowers/conventions.md`。
>
> 维护方式：只写“现在是什么状态”，不写历史。有实质进展或发布后更新本文件，
> 历史过程写进 `handoff.md` 条目。

## 基线

- **更新日期**: 2026-10-04
- **分支**: `main`，与 `origin/main` 同步
- **版本**: `0.13.1`（`version.json` 是唯一真源，与 `CHANGELOG.md` 顶部一致）
- **最近提交**: `46c3156` 扫描监控不自动整理（2026-10-04），工作区另有 0.13.1 未提交改动
- **工作区**: 有未提交改动（最近条目见 `handoff.md`）

## 最近一次验证

- 完整 `unittest discover -s tests -p 'test_*.py'` **1165 项零失败**（2026-10-06，影视广告识别补充整句式推广话术与“伪装视频”判定）；
  `compileall app main.py`、`git diff --check` 通过。
- 完整 `unittest discover -s tests -p 'test_*.py'` **1163 项零失败**（2026-10-04，0.13.1 接收夹同片多版本合并）；
  另有 `tests.test_quick_import` / `test_scraper_batch_organize` / `test_scraper_folder_reuse` 单跑通过；`version.json` 解析与 CHANGELOG 顶部版本号一致。
- 完整 `unittest discover -s tests -p 'test_*.py'` **1142 项零失败**（2026-09-29，随 0.13.0 元数据同步）。这是当时的快照，不是长期基线，改动后需重跑。
- `compileall app main.py`、改动 JS `node --check`、`git diff --check` 通过。
- **未验证**：Docker 重建后的容器页面，以及真实 115 账号重跑；结论只能按“单元/静态通过、实盘待验”表述。

## 待办 / 未完成

- 容器重建后用真实接收夹复核：整段名字只有推广话术的假 `.mkv/.mp4` 只被忽略（开启“删除广告文件”时才删除），不再被识别成正片。
- 容器重建后手动触发一次接收夹整理，确认同一部影视的多个版本/多个条目合并进同一个媒体文件夹（第二条文件名带 `(2)`），发行组命名的空壳目录被清理。
- 真实 115 重跑确认 `Curb.Your.Enthusiasm` S09/S10/S11 整季包落季与季包残留（`RARBG.txt`/空 `Subs`）清理。
- job #145 的 40 条错名字幕是否需要回改，待用户确认。
- 本地 0.13.0 容器重建与页面复核（按 `AGENTS.md` 的代理配置执行 `docker compose up -d --build`）。
- 容器重建后实测刮削页「扫描监控」：运行详情只应出现 STRM 生成，不再有自动整理动作（2026-10-04 修复项）。

## 当前需要知道的上下文

- 接收夹（inbox）是**可选中转入口**，不是强制流程；旧的“直接推送到电影/电视剧监控目录”用法继续有效，两种并存。详细口径见 `conventions.md`。
- “文件夹监控”与“接收夹”是两套触发方式，共用同一个全局 `webhook_secret`，但接收后的处理链路不同。
- 当前设计文档入口：`docs/superpowers/specs/2026-09-23-folder-monitor-workflow-design.md`（文件夹监控与接收夹）、`docs/superpowers/specs/2026-09-26-folder-receive-monitor-runtime-design.md`（运行时）。
- **功能模块索引**：`docs/superpowers/modules.md` 记录每个模块的用途 / 入口 / 会做 / 不会做；新增或改名路由、服务、provider、页面模板必须登记，`tests/test_modules_doc.py` 会校验覆盖率。
- **接收夹同一部影视合并**：同一 TMDB 条目的多个条目（电影多版本、同剧多季包）整理时会落进同一个媒体文件夹——文件夹撞名只保留一次改名、文件同名给后面的加 `(2)`；某个条目自己的冲突只留它自己，不连累同批其他条目。口径见 `conventions.md`。
