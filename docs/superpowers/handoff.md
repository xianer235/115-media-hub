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

- 2026-11-17 | main 工作区未提交 | 未改版本号 | 设置页「找不到设置」治理：每个分组（>1 子块）顶部加「组内快捷跳转」锚点条（`initSettingsSubgroupAnchors`，点一下滚到对应 subgroup 并高亮，标签优先取 `data-settings-anchor` 短名）；网络代理从「网络与通知」拆成独立 section（key=proxy），通知组改名「通知推送」，播放与影视库改名「播放与点播」，分组 6→7、step 重排 1..7 | 根因：用户反馈分组不合理、找不到想要的项；分组按技术领域切而非按功能直觉，组内子块无锚点只能滚着找，痛点重点「点播相关」 | `test_settings_layout_frontend`（SECTION_KEYS 加 proxy、areas 补 emby-bridge、titles 11→12）+ `test_settings_notify_ui` 共 19 条零失败；`check_js_syntax.py` 全量 33 文件通过；`git diff --check` 通过。**未在浏览器点过** | 用户到设置页看锚点条与分组效果，某个锚点名 / 分组归属不合适再调
- 2026-11-17 | main 工作区未提交 | 未改版本号 | 新增「Emby 兼容桥」emby-bridge：让 Seerr 把极影视当 Emby 服务器读其媒体库索引判重，免部署重复 Jellyfin。五个翻译点（头改写 Authorization→X-Emby-*、/Auth/Keys 本地实现、/Items?ids= 判重改写为 /Users/{uid}/Items/{id} 并包装成 {Items:[单条]}、媒体库 CollectionType 补 movies/tvshows、来源 IP 白名单默认只放内网） | 根因：极影视 Emby 层 4.7.0.0 协议偏差比预想大——实测 `/Items?ids=` 被忽略（判重必失败）、`/Auth/Keys` 直接 404、`CollectionType` 全 None、只认 `X-Emby-*` 头；Jellyseerr 3.5.2 源码核对确认 getItemData 靠 `Items[0].ProviderIds.Tmdb` 判重。全部用真实环境 + 源码钉死，见 specs | 新增 `tests/test_emby_bridge.py` 22 条零失败；`test_modules_doc` 5 条零失败；`compileall` + `check_js_syntax.py`（settings.js/index.js）+ `git diff --check` 通过；端到端真连 jys.shuxian.fun 登录成功、判重改写返回正确 Tmdb。**未在容器内跑全量、未真机接 Seerr** | 真机按 specs §6 验收：Seerr 加 Emby 服务器（URL Base=emby-bridge）→ 同步后库内影片显示「可获得」；验证前不删现有 Jellyfin
- 2026-11-16 | main 工作区未提交 | 未改版本号 | 设置页治理第一批：Seerr 电影/电视剧点播保存目录、磁力中转目录、各网盘「常用目录」全部接上「选择目录」；分区重排为「认证 → 代理 → 播放与扫描 → 存储 → TG → PanSou → TMDB → AI → 过滤词 → 通知 → 账号与密钥」，步骤号改回 1..11 连续 | 根因：这几处是手打 115 相对路径且保存时不校验，填错要等点播落错目录才发现；分区按上线顺序排，代理排第 5 但第 3 的 TG / 第 7 的 TMDB 都依赖它，`2b`/`6b` 是补丁式追加。实现上复用文件夹监控的目录弹窗（`openMonitorFolderModal` 新增回调模式，空 targetInputId + `onPick`，回传 `relative_path`），未新造选择器 | `test_settings_layout_frontend`（含新增「代理必须先于依赖它的分区」）+ `test_settings_path_picker` 7 条 + `test_monitor_run_frontend` / `test_quick_import_frontend` / `test_settings_notify_ui` / `test_settings_storage_ui` / `test_modules_doc` 共 **146 条零失败**；`compileall` 与 `node --check index.js / settings.js` 通过；模板标签配平用 html.parser 校验无未闭合。**未在容器内跑全量、未在浏览器点过** | 用户真机点一次三处「选择目录」确认弹窗能选到目录；下一步做分区合并（11 → 6 组，把 Seerr 那两块从安全区拆到播放区），那步要移动 DOM，先看一眼再动
- 2026-11-16 | main 工作区未提交 | 未改版本号 | 设置页 11 个分区合并为 6 组：网盘与账号 / 网络与通知 / 播放与影视库 / 来源与订阅 / 元数据识别 / 系统与存储；组内每块内容包成 `<div class="settings-subgroup" data-settings-subgroup="...">` + 小标题（`网盘与账号` 只有一块，不加标题）；Seerr 点播密钥与两个保存目录从「账号密钥」拆进「播放与影视库」；摘要函数改为按 6 个组键拼装（原 11 个键删掉） | 根因：分区按功能上线顺序追加（`2b`/`6b` 就是痕迹），一屏 11 张卡且「后台安全管理」混装账号 / 签名密钥 / Seerr / 油猴四类东西。合并靠脚本整体搬 section 块（不手搬 DOM），搬完用 html.parser 验标签配平、逐块核对代表字段归属、比对控件数量（showHelp 6 / ui-checkbox 10 / textarea 4 / number 12 前后一致） | `test_settings_layout_frontend` 13 条（新增「12 块内容合并后一块不少且只出现一次」「组内必须有小标题」「代理必须先于依赖它的分区」）、`test_settings_path_picker` 7 条、`test_scraper_noise_settings` / `test_settings_notify_ui` / `test_settings_storage_ui` / `test_modules_doc` 共 65 条零失败；全前端结构测试 **242 条零失败**；`compileall` + `node --check settings.js` 通过 | 用户看一眼 6 组的展开效果与组内小标题分隔线；满意后一起提交（挂 0.15.14 或并入下个版本）
- 2026-11-16 | main 工作区未提交 | 0.15.14 | 修 CI 失败：`Check JS syntax` 用 `--experimental-default-type=module`，runner 是 Node 24 且该参数已在 Node 23+ 移除，直接 `bad option`，33 个文件报错、21 秒 exit 1；改为新增 `scripts/check_js_syntax.py`（复制成 `.mjs` 再 `node --check`，不依赖 Node 版本），`check.sh` 与 CI 都调它，`test_js_module_syntax` 改为调用脚本并加 `--self-test` 防止检查器退化成静默全绿 | 根因：本机 Node 22 支持该实验参数，我把「本机跑通」当成通用写法写进 CI，没考虑 runner 的 Node 版本 | `check_js_syntax.py` 全量 33 个文件通过 + `--self-test` 能抓到故意写错的文件；`test_js_module_syntax` 2 条；`scripts/check.sh` 含 `--js static/js/index.js` 通过；本机 Python 3.9 / Node 22 与 CI 的 Python 3.12 / Node 24 均可用 | 推送后等 CI 转绿 → `gh workflow run ci.yml -f publish=true` 重建 0.15.14 镜像 → 打 tag v0.15.14 → 发 release
- 2026-11-16 | `0147c62` | 0.15.14 | 修「设置页 6 个分区展不开、快捷定位点了没反应」：`static/js/modules/tabs/settings.js` 的 `buildSettingsSectionSummary` 末尾多了一个 `}`（改摘要函数时脚本拼接留下的），整个 ESM 模块解析失败 → `initSettingsSectionNav` 从未执行；删掉多余 `}` 后恢复。同时补上 JS 语法门的真漏洞：`node --check` 对含 `export` 的 `.js` 静默返回 0，`scripts/check.sh` 与 CI 改用 `--experimental-default-type=module`，新增 `tests/test_js_module_syntax.py` 用 .mjs 副本兜底全量扫描 | 根因两层：① 上一轮「分组合并」用 python 脚本替换摘要函数，切割点停在 switch 的 `}` 而新文本自带函数收尾，多出一个 `}`；② 当时跑的 `node --check`（以及历史上每次声称「JS 语法通过」）对 ESM 文件根本不生效，等于没验证 | 新增测试 1 条（33 个 JS 全部按 ESM 解析通过）；`test_settings_layout_frontend` / `test_scraper_noise_settings` / `test_settings_path_picker` / `test_settings_notify_ui` / `test_settings_storage_ui` / `test_modules_doc` 共 66 条零失败；`scripts/check.sh --js static/js/modules/tabs/settings.js` 通过；六个分区的 head / body / 摘要占位 / aria-controls 用脚本逐组核对一致 | 用户硬刷新页面确认 6 组能展开、导航能跳；确认后把「目录选择器 + 分区重排 + 分组合并 + 本次修复」一起提交
- 2026-11-15 | main 未提交 | 未改版本号 | 修 issue #18：精准匹配不再被简介/描述里的季集字样误触发（`_is_subscription_strict_title_raw_line` 先排弱描述行，弱前缀补 描述/介绍/剧情简介），manifest 文件级独立校验视频 basename 剧名且无 `tmdb_id` 也校验，影视订阅只收「视频 + 外挂字幕」 | 根因：① 旧逻辑先查 TMDB/季集/etc 再排弱描述行，简介里"第二季"抢成了片名证据；② `filter_subscription_manifest_files_by_strict_identity` 只看文件 TMDB，task 无 tmdb_id 时整体放行，`完美世界.S01E14.mkv` 被当目标剧放过。采纳社区补丁但**剔除「精准匹配默认开」**（用户判断：严格漏资源的概率高于误入库）；视频白名单限定 tv/movie 且保留 srt/ass（否则刮削改名链路丢字幕，`test_scraper_batch_organize` 2 条挂） | `.venv/bin/python scripts/run_tests.py` 全量 2161 条零失败 | 回复 issue 致谢并说明取舍；提交时用 `Co-authored-by: dayang233` 署名
- 2026-11-15 | main 待推送 | 0.15.13 | 发版：订阅精准匹配误入库修复（功能见下一条）；`version.json` / `CHANGELOG.md` / `README.md` / `state.md` 四件套已改 | 发版原因：issue #18 两个问题确认为确定性 bug，全量 2161 条零失败后发布；**未采纳贡献者「精准匹配默认开」的建议**，默认仍是关 | `scripts/run_tests.py` 全量 2161 条零失败；`scripts/check.sh --changed` 通过 | 推送后确认 CI 测试绿 → 镜像 `0.15.13` 构建完成；issue 回帖致谢并说明取舍
