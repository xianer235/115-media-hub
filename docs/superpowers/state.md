# 项目当前状态

> 这是**每次会话开头唯一需要完整阅读**的状态文件，目标 ≤80 行。
> 最近交接条目：`docs/superpowers/handoff.md`；历史条目：`docs/superpowers/handoff-archive.md`
> 长期不变的架构与产品口径：`docs/superpowers/conventions.md`。
>
> 维护方式：只写「现在是什么状态」，不写历史。有实质进展或发布后更新本文件。

## 基线

- **更新日期**: 2026-10-25（0.15.9：Seerr 点播对接 + 订阅跨盘补源落地后自动触发监控扫描）
- **分支**: `main`，0.15.1 ~ 0.15.8 已推送；**0.15.9 已改版本号待推送**；tag `v0.15.8` 已推并发布 Release，Docker 镜像 `xianer235/115-media-hub:0.15.8`（含 `latest`）由 GitHub Actions 自动构建（测试不绿就不构建）
- **版本**: `0.15.9`（2026-10-25：① 新增 Seerr / Jellyseerr / Overseerr 点播对接——Radarr/Sonarr v3 兼容层 16 端点，点播转订阅任务（provider 固定 115）并立即全量搜索，X-Api-Key 独立鉴权、密钥留空接口整体关闭；10-24 完成但一直未发版，随本版发出。② 修复跨盘补源复制进 115 监控目录后不触发扫描、不出 STRM——单文件补源在整理定时器分组改名结束后按落点匹配监控任务入队（先改名再扫描），整包文件夹补源在复制收口直接触发；仅 115 目标、仅订阅补源）
- **CI**: 单一工作流 `.github/workflows/ci.yml`（`docker-release.yml` 已并入并移除），**限定 `paths: version.json`，只在发版推送时触发**：`test` job 跑 `compileall` + 全量 `node --check` + `scripts/run_tests.py`，`build-and-push` 用 `needs: test` 挂在后面（`workflow_dispatch` 有 `publish` 开关，关掉只跑测试）。日常开发验证只用本机 `scripts/check.sh`，不要等 CI
- **本地不入库文件**: `AGENTS.md` / `CLAUDE.md` / `.workbuddy/` / `.claude/` / `.worktrees/` 是本机开发用，**按约定不入库**。任何测试/代码读它们前必须判存在（`test_modules_doc` 已这么做），否则干净 clone 跑测试必挂。
- **运行环境**: `docker compose` 服务名 `115-media-hub-test`（应用本体），端口 18080；`/app/storage` 已映射到宿主机 `/Users/xianer/Documents/docker/115strmxianer/storage`（virtiofs，空间读数正常）。挂载路径与端口已改为从根目录 `.env` 读取（模板 `.env.example`），本机 `.env` 写的是原来的绝对路径
- **最近提交**: `253b347` 修复补源不触发监控（main，未推送）；其前的 `900da5e` / `c4071d8` Seerr 点播对接同样未推送、未发版（随 0.15.9 一起发出）；0.15.9 发版四件套已随发版提交入库，待推送
- **工作区**: 0.15.9 发版四件套已提交（`version.json` / `CHANGELOG.md` / `README.md` / `state.md` / `handoff.md`），待 push → tag → release；仓库根 3 个探针残骸（`0u19ijd3` / `8vdkd0yh` / `clxjv4no`）待清



## 最近一次验证

- **0.15.9 发版前全量**（2026-10-25）：`scripts/check.sh --changed` **699 条零失败**，其中 `test_cross_copy_organize` + `test_cross_copy_jobs` 137 条零失败、新增 11 条回归（触发参数与订阅导入一致、先改名再触发、无监控任务时写警告、改名失败仍触发、订阅任务已删仍触发、非 115 不触发、文件夹触发 / 手动不触发、停用不谎报、未配置不触发）。**未在容器内跑**。
- **0.15.8 发版前全量**（2026-10-24）：本机 `scripts/check.sh --all` **2034 条零失败**（149s），新增 2 条回归：`test_resume_non_aligned_offset_rewinds_to_segment_boundary`（坏断点回退后照常续完并上传，`start_offset` 落在段边界）、`test_note_downloaded_snaps_to_segment_boundary`（`note_downloaded` 只记栅格值）。**未在容器内跑**。
- **0.15.7 发版前全量**（2026-10-23）：容器内 `scripts/check.sh --all --container` **2032 条零失败**，修复测试抖动后**连跑 9 次**均零失败（CI 跑的是同一条）。其中新增 `test_cross_copy_progress`（24 条）与 `test_notify_cross_copy_subscription`（6 条）钉住进度回写与通知合并。
- **0.15.6 发版前全量**（2026-10-23）：容器内 `scripts/test_in_container.sh` **1991 条零失败**（61.2s），也就是 CI 里跑的同一条命令；`node --check` 全量 33 个 JS 通过；`version.json` 变更检测用本地两段真实历史分别得到 `true` / `false`；工作流 YAML 经解析确认 `needs` / 条件 / 输出链正确。
- **订阅补源真机跑通（2026-10-22，`origin=subscription` 三条任务，用户中途手动取消）**：115 任务「光阴之外」（本盘已到 E41）一次跑出 3 条补源任务 `id=12/13/14`，`target_savepath=115连载中/光阴之外 (2025)/Season 01`，文件名 `S01E42/43/44.mp4`——**分享里 11 个文件只转存并注册了缺的 3 集**，说明「转存即挑缺集」生效。夸克中转目录 `/云下载/跨盘中转/光阴之外` 里正好只有这 3 个文件。取消后 `id=12/13` 保留 `resume_json`（断点可续传）、`id=14` 未开始；本机暂存留 2 个 `.part` 共 214MB。**「复制完成 + 中转副本被删」这一段仍缺一次完整真机**（用户主动中断）。附带发现 `/app/config/cross_copy_tmp` 有 3 个 10-21 的旧 `.part` 共 5.7GB（历史测试残留，与本次无关）。
- 补源模块单跑 `test_subscription_cross_copy` **78 条零失败**（含 `TestMissingEpisodeSelection` / `TestStagingCleanup` / `TestStageSharePrecision`）。
- 容器内实测补源搜索（「光阴之外」，provider=quark）：修复前 275 条候选按集数排序，TOP3 是 3 条 score 44 的 TG 日报贴 + 《凡人修仙传》；修复后过滤出 55 条，TOP15 全是《光阴之外》，TOP1 为 score 98 / E44（本盘 E41，正是缺的集）。
- 本机 8 模块 284 条零失败（`test_local_storage` / `test_settings_storage_ui` / `test_settings_layout_frontend` / `test_settings_notify_ui` / `test_modules_doc` / 复制引擎三件）。
- 容器内实测：挂 `/app/storage` 后自动进候选列表；空盘自动建 `cross_copy_tmp`；`/mnt/hdd`（宿主机路径）与 `/tmp/foo`（容器层）均被拒并给出挂载指引。
- **回归钉**：`TestResumeBootstrapChain`（首跑失败留断点 → 重跑零 Range 请求、跳过下载直接上传）、`TestResumeStateForDb`（含 on_part_done 闭包能落库）、并行 1/3/8 三元结果相等、失败/取消保留临时文件；**CLI `cross-copy` 命令组**（宿主机场，不进镜像：`capabilities` / `create` / `list|cancel|retry|delete|clear [--scope]`）payload 级测试钉住。
- **订阅补源自动链路模拟验证通过**（真实夸克分享 + 合成 115 订阅任务）：分享解析 → 注册 `origin=subscription` → 复制到 115 **落地 SHA1 逐字节一致** → 中转副本被删、夸克原片完好（转存自己分享被平台 404 拦下属规则，生产是他人分享不受影响）。
- **监控目录联动验证通过**：临时监控任务指向 115/跨盘复制测试/监控联动 → 跨盘复制影片文件（12.1s 秒传命中）→ 触发扫描 5 秒完成 → **STRM 生成**，指向本服务代理地址。产物已清理。
- **两个真机 bug 已修**（详见 handoff）：① 夸克 `sharepage/detail` 的 stoken 旧代码双重编码，服务端改单 decode 后含 `+/=` 的 stoken 必 400「非法token」，两处改单次编码 + 2 条回归用例；② `_stage_share_to_quark` 把 `list_share_entries` 的 `{"entries": [...]}` dict 当裸 list 迭代 → 分享永远「没有可转存的文件」，**转存整链原本不可用**（单测 fake 返回裸 list 掩盖了契约漂移，已连 fake 一起修）。

## 待办

### A. 需要用户操作

1. **升到 0.15.9 并重启**（CI 构建的 `0.15.9` 含补源触发监控修复，也含 0.15.8 的断点回退修复；此前并行下载 / 断点续传那些都是 `docker cp` 热更文件，重启后才算正式生效）：`docker compose up -d --build`。
2. **真机联调 Seerr 点播对接**（0.15.9 新增，仅单测 + 容器全量，**未真机**）：按 `docs/seerr-setup-guide.md` 起 Seerr / Jellyfin 测试容器，在面板「后台安全管理」生成 API 密钥、填默认保存目录，Seerr 里加 Radarr/Sonarr 两条服务器（地址用 `host.docker.internal` 而非 `localhost`），跑电影点播 / 剧集点播 / 删除 / 接口关闭四步；预期点播变成订阅任务并立即搜索。排错见教程第九节。
3. **验证坏断点自愈（0.15.8 新增）**：现网那条报「续传起始偏移未按分段边界对齐（3828076306）」的补源任务，重建镜像后直接点「重试」——预期只补最后约 2.9MB、算完哈希后上传成功，不再需要「删除记录」。日志里应有 `cross-cloud resume offset 3828076306 not segment-aligned, rewinding to 3825205248`。
4. **跑完一次完整补源**（现在只差最后一段）：把取消的 3 条任务（`id=12/13/14`）点「重试」——前两条已有断点会续传，不必重下 214MB 以上的部分；预期看到落到 `115连载中/光阴之外 (2025)/Season 01` 并各出一个文件、夸克 `/云下载/跨盘中转/光阴之外` 三个中转副本被自动删。**0.15.9 起还应看到（补源触发监控，本次新修）**：订阅日志出现「跨盘补源已触发监控精准刷新」，「文件夹监控」页面对应任务自动跑一轮，「本地文件」页签里出现改名后的 `片名 (年份) - S01E42.strm`；若那里还是分享原名 `S01E42.strm`，说明改名没生效（查「入库后整理」开关与 TMDB 绑定）。**不打算重试的话要清中转目录**，那 3 个文件约 10.3GB 占着夸克配额。
5. 测试产物清理（都在各盘「跨盘复制测试」文件夹，确认不要就整目录删）：115 侧 `xcopy-a/b/c-aliyun/pan115`、`秒传验证`、`文件夹用例`、`xcopy-d-quark-src-3m.bin`、`监控联动`（已空）；阿里侧 `xcopy-a/b/c`、`文件夹用例`；夸克侧 `xcopy-d-quark-src-3m.bin`（原片）+ 空的「跨盘复制自测」。任务记录 14 条界面点「清空复制」即可。
6. **陈旧临时文件**（与本次补源无关，历史测试残留，容器内可直删）：`/app/config/cross_copy_tmp` 3 个 `.part` 共 5.7GB、`/app/storage/cross_copy_tmp` 2 个 `.part` 共 214MB（后者是本次取消任务留下的，重试会复用、成功后自动删）。
7. 接收夹 / 文件夹监控老待办（10-07~10-08 遗留）：要么集中复核，要么按「线上没报错即可用」关掉，等用户定。
7. **验证补源进度回写 + 通知合并**（2026-10-23 新增，仅单测 + 容器全量）：下一次实际补源落地后，① 群里只该收到 **1 条**「订阅更新成功」（带「来源：跨盘补源（夸克网盘 → 115网盘）」与新增集数）；② 订阅界面「最近命中 · N天前 · 已到 EXX」、追更进度前进到补进来的最高集、detail 出现「跨盘补源完成：从夸克补入 N 个文件（E42~E44）」。若补源任务已完成但界面没变，先查 `cross_copy_jobs.progress_state`（`pending` = 等定时器、`done` = 已写回）；若还是逐条「跨盘复制完成」，去设置页确认「订阅更新成功推送」是否打开（关着会走兜底老路径）。

### B. 已真机验证通过（勿重复）

- 阿里 ↔ 115 双向、秒传、文件夹复制、多分片+分片重试、双任务并行。
- **订阅补源触发 + 转存 + 注册 + 落点（2026-10-22 真机）**：115 任务自动判定缺集 → 夸克搜到候选 → 只转存缺的 3 集 → 注册 3 条 `origin=subscription` 任务 → 落 `Season 01`，全部成立。
- 订阅补源**下游链路**（注册→复制→删源→原片安全）、监控目录联动（复制落监控目录→扫描→STRM）。
- **补源入库后原地改名 / 夸克中转残留自动清理 / 手动转存等落地再判完成**（2026-10-22，容器全量 + 单测，**未真机**——用户本机走移动网络，明确说不验证）：三件都是「代码走通、测试钉住」，真机效果等下一次实际补源时看。
- 并行下载 / 断点续传：**仅容器全量 + 单测验证，未真机**（重建镜像后按 A-1 复核；A-2 的续传重试可顺带验证）。

### C. 已确认要做，排在后面

- 123 网盘 / 天翼：接上传与取链（现在只能浏览）。用户 2026-10-20：这两个盘现在不用，先放着。
- STRM 支持非 115（决定「复制到夸克能不能直接进媒体库播放」）。
- 夸克 / 阿里作目标时的上传会话续传（本期只做下载侧；预签名 / pre 会话跨进程复用需真机验证后再动）。
- **阿里作补源源**（等用户指令）：需要放开 PanSou 白名单里的阿里链接 + 接 `cross_copy_sources`。阿里源带 `content_hash`，115 可秒传、免下载，是收益最大的一条（夸克必须下载一遍算哈希）。
- **补源 multi_season 落点季号（已知边界，未修）**：本轮把「内嵌 `Season 2/` 子目录」的单季任务季号错位修了（用 `rel_path` 的父目录参与季号识别，季号不符丢弃）；但多季合一模式（`multi_season_mode`）下，`_cross_copy_target_savepath` 仍按 `candidate.season` 定落点、不按每个文件的季分目录——同一候选里不同季的文件会落到同一个 `Season` 目录。多季合一场景少，留待后续。

### 已定不做（不要再提案）

- 跨网盘移动（只复制）；非 115 目标自动刮削；纯流式边下边传。

## 当前需要知道的上下文

- **订阅命中后冷却已落地（2026-10-26，未发版）**：命中新集后暂停自动查询到下一集播出前；未命中频率完全不变（用户明确不做未命中退避，及时发现新集优先）。冷却锚点复用 `last_success_at`（每次命中刷新 → 分批上传顺延），终点 = min(下一集播出日当天+上次命中时分−60 分钟, 相邻两集播出日差×0.85)，封顶 7 天；任务级 `hit_cooldown_mode`（auto/manual/off）+ `hit_cooldown_hours`（1~336）。已完结只认 TMDB `status ∈ {Ended, Canceled}` 后停止自动调度、列表标「已完结」，手动跑一次变回 Returning 会自动恢复。**TMDB 的 `next_episode_to_air` 在命中那轮指的是刚入库那集，不能直接当终点**（方案审查抓到的失效点，有回归钉）。细节见 `modules.md` 订阅模块与 `conventions.md`「命中后冷却」三条红线。

- **订阅跨盘补源已在主链路接通（2026-10-22，仅夸克作源）**：统一入口是 `_subscription_cross_copy_dispatch`，主链路调两次——无候选时在「等待资源」早退前，有候选时在**目标目录扫描校准 `last_episode` 之后**（首轮真机踩到：判定放在校准前，用的是进度旧值 0，候选最高 E40 > 0 就判「本盘不缺」，整条链路一次都没触发）。夸克候选走 `subscription.find_subscription_cross_copy_candidates`（浅拷贝 task、provider 换 quark 复用同一套搜索评分），**新函数靠顶部 `globals().update` 注入，不要在 `subscription_task_runner.py` 里加 import（会循环）**；本盘缺才补（电视剧候选集数取 `episode`/`range_end` 较大值比 `last_episode`）。**2026-10-23 起模式只剩 off / fallback 两态**（订阅弹窗是单开关，文案重写为「本盘没有新资源时才跨盘复制」）：`prefer`（命中也复制）已删——同盘有资源时转存是服务端秒传，跨盘要下载再上传，命中也复制纯属浪费，且注册判缺用导入前状态、会与同盘导入重复下载同一批集并撞命名；历史 `prefer` 配置按 fallback 接管（`normalize_subscription_cross_copy_mode`），存量任务不静默失效。**落点与订阅导入一致**（`_cross_copy_target_savepath`：电影 `<savepath>/片名 年份`、剧集 `<savepath>/Season NN`，目标目录由 `ensure_folder_id_by_path` 自动建）。
- **补源候选不能沿用主链路的排序**（2026-10-22 真机发现）：`find_subscription_cross_copy_candidates` 过滤掉 `score < min_score` 与 `low_score_fallback`，再按「标题命中任务名优先 → 分数降序」重排；注册侧 `_pick_share_candidates` 跳过被长文本污染成 `...xxxhttps` 的链接。主链路按集数排序时，TG 日报贴的假集数（实测 1170）会把 score 44 的日报贴顶到榜首，而《凡人修仙传》这类别的剧也能挤进《光阴之外》的 top 3——补源注册不做逐文件内容校验，挑错就是把别人的剧复制进本剧目录。
- **夸克转存是异步任务，不能转完立刻列目录**（2026-10-22 真机：两条候选全部报「转存后没在中转目录找到新条目」）。`/share/sharepage/save` 只返回 `task_id`，实测小文件夹约 2 秒后条目才进目录。现在 `submit_share_receive` 之后调 `provider.wait_share_save` 轮询 `/1/clouddrive/task`（status=2 完成，默认最多 120 秒，`CROSS_COPY_STAGE_TASK_TIMEOUT` 可调），任务状态没确认也不直接判失败，再给 20 秒「列目录重试」可见窗口（`CROSS_COPY_STAGE_VISIBLE_TIMEOUT`）。**另一个后果**：上一轮其实已转存成功、只是列目录太早，文件留在中转目录里；所以 `already_staged` 分支现在会把目录里对应条目返回，交给注册侧查重后**补注册**（`find_processed_cross_copy_job` 挡住已成功/已取消的，failed 允许重试），否则永远补不上。
- **补源选集：在「转存」这一步就只转缺的集，不是整包转存后再筛**（2026-10-22）。剧集任务有本盘进度时，`_stage_share_to_quark` 先 `_scan_share_media_files` 只读递归扫分享（≤3 层、≤40 目录），`_select_missing_episode_files` 挑缺集、`_dedupe_episode_files` 同集留体积最大，只把这几集的 `fid` 提交转存——**分享里没有缺集时一次转存都不发、连中转目录都不建**。判缺口径是「目标目录实际已落盘的集集合」（`existing_episodes`，中间缺集也能补），拿不到集合才退回比 `last_episode`。散文件与整季文件夹**两条路都过这层筛**（以前只有文件夹筛，散文件无脑全注册）；`_expand_staged_folder_media_files` 展开文件夹后逐文件注册（`source_is_dir=False`）从而拍平，同一轮按集去重（先到先得），**认不出集数的文件一律不复制**（`4！2.mp4` 这类全角脏名解析不出来，宁可少补也不污染季目录）。扫不动（403 / 超层级）才退回整包并在 skipped 写明。
- **补源中转清理分两层**：① 源文件中转副本由 `cross_copy_jobs` 在单文件任务成功后自动删（条件 `origin=subscription` + 非文件夹 + 成功 + `cross_copy_delete_source_after`，默认开；**手动复制的源永不删**）；② 分享带进来的文件夹空壳由 `cleanup_staging_empty_folders()` 在每轮补源注册后按 DFS 倒序清，**只删确实为空的**，中转任务根目录永不删、`cid=="0"` 直接返回防御。**任务取消/失败后中转副本按设计保留**（要续传），用户不重试就一直占夸克配额。
- **补源「入库后整理」= 复制收口只打标记 + 定时器改名**（2026-10-22）：补进来的集是分享原名（`S01E42.mp4`），订阅导入的是 `光阴之外 (2025) - S01E42.mp4`，同一部剧两种命名。`cross_copy_jobs` 成功收口在**同一条 UPDATE** 里把 `organize_state` 标 `pending`（仅 `origin=subscription` + 非文件夹 + 成功；重试清空），`subscription_cross_copy_organize` 定时器（120 秒一轮）捞 90 秒防抖窗口外的、按（目标网盘 + 目标目录 + 订阅任务名）成组、CAS 抢占后调刮削命名计划**原地改名**（只改文件名、不移动、不建目录），开关沿用该订阅任务的「入库后整理（电视剧）」，关掉或 `tmdb_id<=0` 标 `skipped`。**别把改名塞回复制收口**：刮削任务阻塞最长几分钟，会占死并发名额。
- **夸克中转残留自动清理**（2026-10-22）：`cross_copy_staging_cleanup` 定时器（默认 1800 秒）扫中转根下每个任务目录，删掉超过 `cross_copy_staging_retention_days`（**0 = 关，默认 7 天**）没修改的条目与空目录；**活跃任务的条目受保护**（先查 `cross_copy_jobs` 活跃集，查不到就整轮跳过）；删除是进夸克回收站、**配额不会立即释放**。清掉之后旧任务「重试可续传」不成立，调小之前要知道这个代价。
- **源网盘界面只列夸克（2026-10-22）**：跨盘复制引擎支持 115/夸克/阿里互传，但补源只把「夸克 → 目标盘」接进了主链路。此前订阅弹窗按「能当源」的能力表列出阿里/115，勾了却不执行、日志一个字不写；现在前端收窄成只列已接通的源（`ui.js` 的 `SUBSCRIPTION_CROSS_COPY_SUPPORTED_SOURCES`，须与 `core.SUBSCRIPTION_CROSS_COPY_SOURCE_PROVIDERS` 一致），后端 `split_cross_copy_sources` 把历史配置/手工写入的未接通源识别出来写 warn（「暂未接通补源，本次已跳过」），无可用源时同样写 warn，不再静默。
- **跨盘复制三段式**：取链 → 分段下载（16MB 一段、**同任务内默认 3 路并发**，`CROSS_COPY_DOWNLOAD_PARALLEL` 1~8；落盘后按顺序整文件算哈希）→ 秒传探测 / 分片上传。任务全局并发默认 2（`CROSS_COPY_MAX_CONCURRENT`，硬上限 8），文件夹任务内部逐文件串行。
- **断点续传两层**（2026-10-21 起）：下载侧（连续前缀续下 / 哈希已有则整段跳过）+ 115 上传会话侧（`upload_id` + parts 对账，只补缺片）。状态挂 `cross_copy_jobs.resume_json`，失败/取消保留、成功清除、孤儿与删记录联动作废；续传前复探源哈希防旧内容上传。**落库必须过 `resume_state_for_db`**——`resume["upload"]["on_part_done"]` 是闭包，直接 `json.dumps` 会抛异常被吞掉，断点静默不落库。
- **暂存目录是单目录模型**（2026-10-21 起，原「位置列表」已下线）：配置只有 `cross_copy_temp_dir`（容器内绝对路径，空 = 默认 `/app/config/cross_copy_tmp`）；设置项 2b 只做「看当前目录状态 + 填容器内路径更换 + 恢复默认」；旧三字段（`local_storages`/`cross_copy_temp_storage`/`cross_copy_temp_subdir`）读取时自动迁移、保存新值后清除；接口是 `GET/POST /storage/temp-dir`。
- **跨盘复制通知按任务来源分两个开关**（2026-10-21 起，替代原单字段 `cross_copy_notify`）：`cross_copy_notify_subscription`（订阅补源，origin=subscription）与 `cross_copy_notify_manual`（手动复制），都在设置页「通知推送」分区，默认开；渠道就绪检查（`notify_channel_ready`，只看 webhook/应用凭证）与场景开关解耦——历史 bug 是跨盘通知曾绑在 `notify_push_enabled` 上，订阅开关关着就静默不推。
- **补源成功算订阅成功**（2026-10-23）：补源是订阅的另一种资源来源，不该只看到「跨盘复制完成」。两个开关（`notify_push_enabled` + `cross_copy_notify_subscription`）都开时，逐文件的搬运通知**不再发**，由 `subscription_cross_copy_progress` 成组发一条「订阅更新成功」（带新增集数/进度/`来源：跨盘补源（夸克 → 115）`）；只开补源开关时退回逐条发（消息不丢）；补源**失败始终单独提醒**。手动复制与 `notify_push_enabled` 无关，保持原样。
- **秒传的前提是目标端的哈希体系**：115 用 SHA1（大写）、夸克要 md5+sha1（**都小写**）、阿里要 `content_hash`。115 只给 SHA1，所以 **115 → 夸克/阿里 一定会下载一遍**，命中只是省掉上传。
- **签名类教训（4 个真机 bug 的共性）**：直链/签名 URL 取到什么样就请求什么样，绝不二次加工——`normalize_http_url` 不碰已有转义；夸克 `update/hash` 小写；115 直链 UA 绑定取链与下载共用同一套头；夸克 sharepage stoken 单次编码。mock 测不出这类问题，只有真机 + 特定条件才炸。
- **任务记录可以清**：批量（已完成 / 失败 / 已结束）+ 单条删除，只删记录、不删网盘文件；另有按条数保留的自动裁剪兜底。
- **监控扫描不自动周期跑**：所有监控任务 `cron_minutes=0`，靠事件（离线导入完成 / 接收夹分发 / 订阅导入 / **跨盘补源落地**，2026-10-25 补接）或手动「立即扫描」触发。跨盘补源落进 115 监控目录后会按落点匹配监控任务并入队扫描（单文件先改名再扫，见 modules.md 订阅模块）；落点没纳入监控时订阅日志写明「不会自动生成 STRM」。
- 接收夹是**可选中转入口**，与网盘无关（每个网盘一个），分发目标必须同盘；自动整理只有「接收夹」和「订阅」两个入口，文件夹监控是纯扫描。
