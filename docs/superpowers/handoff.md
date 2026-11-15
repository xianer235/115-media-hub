# Agent Handoff

> 本文件只保留**最近**的交接条目（默认最近 14 天且 ≤32 KB），开头就能读完。
> 当前状态看 `docs/superpowers/state.md`（唯一需要每次完整阅读的状态文件）。
> 历史条目在 `docs/superpowers/handoff-archive.md`，通常无需阅读：
> `rg "关键词" docs/superpowers/handoff-archive.md` 按需检索即可。
> 归档中的“下一步”可能已经失效，不应视为当前任务；一切以代码和 `state.md` 为准。
>
> 维护方式：追加条目后执行 `.venv/bin/python scripts/rotate_handoff.py`
> （可加 `--dry-run` 预览），不要手工搬条目。

## 记录规则

- 仅在完成重要功能、重要修复，或需要其他 agent 接手时追加一条，不要记录调试过程。
- 每条必须是**一行**，格式为：
  `- YYYY-MM-DD | 分支或提交 | 版本 | 变更一句话 | 根因或影响 | 验证证据 | 下一步`
- 根因分析、改动清单、测试细节写进 commit message 或 `docs/superpowers/specs/` 文档，
  这里只留指针，避免同样的内容存两遍。
- “验证证据”写明跑过的命令与结论（如 `unittest 1142 项零失败`），不要粘贴完整输出。
- 涉及 CLI 可操作能力（刮削整理选项、监控任务配置、接口变更等）的改动，
  需同步补齐 `cli.py` 命令支持与 README CLI 文档，并在条目中注明。
- 条目超出保留窗口后由 `scripts/rotate_handoff.py` 移入归档，不要手工堆积。

## 交接记录

- 2026-11-15 | main 未提交 | 未改版本号 | 修 issue #18：精准匹配不再被简介/描述里的季集字样误触发（`_is_subscription_strict_title_raw_line` 先排弱描述行，弱前缀补 描述/介绍/剧情简介），manifest 文件级独立校验视频 basename 剧名且无 `tmdb_id` 也校验，影视订阅只收「视频 + 外挂字幕」 | 根因：① 旧逻辑先查 TMDB/季集/etc 再排弱描述行，简介里"第二季"抢成了片名证据；② `filter_subscription_manifest_files_by_strict_identity` 只看文件 TMDB，task 无 tmdb_id 时整体放行，`完美世界.S01E14.mkv` 被当目标剧放过。采纳社区补丁但**剔除「精准匹配默认开」**（用户判断：严格漏资源的概率高于误入库）；视频白名单限定 tv/movie 且保留 srt/ass（否则刮削改名链路丢字幕，`test_scraper_batch_organize` 2 条挂） | `.venv/bin/python scripts/run_tests.py` 全量 2161 条零失败 | 回复 issue 致谢并说明取舍；提交时用 `Co-authored-by: dayang233` 署名
- 2026-11-15 | main 待推送 | 0.15.13 | 发版：订阅精准匹配误入库修复（功能见下一条）；`version.json` / `CHANGELOG.md` / `README.md` / `state.md` 四件套已改 | 发版原因：issue #18 两个问题确认为确定性 bug，全量 2161 条零失败后发布；**未采纳贡献者「精准匹配默认开」的建议**，默认仍是关 | `scripts/run_tests.py` 全量 2161 条零失败；`scripts/check.sh --changed` 通过 | 推送后确认 CI 测试绿 → 镜像 `0.15.13` 构建完成；issue 回帖致谢并说明取舍
- 2026-11-02 | main 未提交 | 未改版本号 | 订阅任务新增「磁力/电驴离线兜底」：本盘分享转存 → 跨盘补源 → 磁力离线，最后手段才下种；全局单开关 `subscription_magnet_offline_fallback`（默认关） | 根因：订阅自动盘搜把 `magnet`/`ed2k` 在三层过滤掉（`subscription.py` 的 `include_magnet_for_115=False`、`pansou_cloud_types_for_provider_filter` 只返 `["115"]`、`_filter_subscription_supported_items` 只认 `115share`），离线链路只接「手动扫描链接」入口（`manual_subscription_link` 标记），所以盘搜搜到的磁力拿不到资源。改动：`core.py` 加配置键；`subscription.py` 开关驱动 `include_magnet_for_115`、把磁力候选单独抽成 `offline_candidates`（标题信号粗筛 + 失效链接缓存过滤，不参与分享过滤/评分）、落库拿 id 并随搜索结果返回；`_subscription_cross_copy_dispatch` 返回 `bool`（是否注册了补源任务）；新增 `_run_subscription_magnet_offline_import`（五道准入：开关/115/补源已覆盖/有候选/确实缺集）复用现成 `_run_subscription_manual_offline_import`；两处触发点（无候选早退前、有候选但 `successful_count==0` 时）接入并走各自成功收口 | `scripts/check.sh --changed` **2132 条零失败**（143.9s）；新增 `tests/test_subscription_magnet_offline_fallback.py` 14 条（dispatch 五分支返回 bool、helper 六条准入、只提交第一条、设置项三处接线）；`test_subscription_manual_offline` + `test_subscription_cross_copy` 123 条、订阅 UI / modules_doc / settings / 资源任务 / 存储共 94 条零失败；`node --check settings.js` 通过 | 真机按 `state.md` 待办 A-10 验证（开开关 + 缺集任务，确认补源优先、磁力最后、死种被缓存挡住）；发版前重建镜像
- 2026-11-02 | main `bfd56f5`+`74fe7c4`+`9d4297e`+`f6e7f09`（未推送） | 0.15.12 | 发版：订阅磁力离线兜底上四件套（`version.json` / `CHANGELOG.md` / `README.md` / `state.md`） | 功能见下一条；本版追加的三处修正：① 剧集候选全部转存失败时准入误判「本盘不缺」→ 按片种分开判（电影仍有候选就跳过，剧集只判已有集是否覆盖到目标总集）；② 无候选路径给挑集传空集合会整季重灌 → 先真扫目标目录，扫不到才退回「进度到 E{n}」；③ 排序改了候选顺序但上报仍取 `[0]` → helper 用 `result["selected_item"]` 带回真正下种那条。另修 `_is_subscription_full_bundle_title` 判据过松（「全高清 第05集」会当整季包，排序失效） | `test_subscription_magnet_offline_fallback` **32 条零失败**；订阅相关 7 模块 **203 条零失败**；`scripts/check.sh --changed` 全通过（含 `node --check`、`git diff --check`、handoff 31755/32768） | push → `git tag -a v0.15.12` → `gh release create`；真机按 `state.md` 待办 A-10 验证（开开关 + 缺集任务，确认补源优先、磁力最后、只搬缺集）
