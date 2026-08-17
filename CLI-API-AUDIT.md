# CLI vs API 完整字段级审计

审计日期: 2026-07-09
方法: 逐行对比 cli.py 的 cmd_* 函数 HTTP 调用 payload vs 容器内 routes/*.py 端点处理函数的 data.get()/query_params.get() 读取

> 适配说明（2026-08-14，合并 PR #5 到 0.7.0）：CLI 仅在宿主机运行，登录账号密码与网页登录一致，
> 无凭据时不再使用默认 admin/admin123 自动登录，而是要求 `MH_USERNAME` / `MH_PASSWORD` 环境变量
> 或交互式输入；`search --cancel`、`subscribe remove`（走 `/subscription/delete`）、`monitor
> start/stop/remove`（按名称操作）、`scrape jobs-create`（识别→选 TMDB→生成计划）已按当前 API
> 适配；`scrape rename/move/copy/delete` 的路径入参仅支持 115，复用现有分页解析。容器运维命令
> （`sources` / `daemon`）需要宿主机 Docker，容器名自动识别 `115-media-hub` / `115-media-hub-test`，
> 也可用 `MH_CONTAINER` 覆盖。

## 严重程度定义

| 等级 | 含义 |
|------|------|
| **🔴 HIGH** | 命令无法正常工作（API 返回 400/404，或字段被完全忽略/误读） |
| **🟡 MEDIUM** | 功能受限但基本可用（缺少重要可配置参数） |
| **🟢 LOW** | 轻微功能缺失（缺少高级/可选参数） |

---

## 统一审计表

| # | 命令 | API 端点 | CLI 发送的字段 | API 读取的字段 | 问题 |
|---|------|----------|---------------|---------------|------|
| 1 | `status` | GET /status-summary | (无 body) | (无 body) | ✅ 无问题 |
| 2 | `version` | GET /version | (无 body) | refresh(query) | ✅ 无问题 |
| 3 | `search <keyword>` | GET /resource/state | `q, compact` | `q, search_source, provider_filter, search_id, job_limit, job_offset, job_status, compact, sync` | 🟢 缺 search_source/provider_filter/search_id/job_limit/job_offset/job_status/sync |
| 4 | `search cancel` | POST /resource/search/cancel | `{}` | `search_id(body)` | 🟢 缺 search_id，取消全部时无问题 |
| 5 | `channels sync` | POST /resource/channels/sync | `force` | `force, limit(body)` | 🟢 缺 limit(limit_per_channel) |
| 6 | `channels list` | GET /get_settings | (无) | (从 config 读取 resource_sources) | ✅ 无问题 |
| 7 | `channels classify` | POST /resource/channels/classify | `channel_id` | `channel_id, sample_size(body)` | 🟢 缺 sample_size |
| 8 | `channels more` | POST /resource/channels/more | `channel_id, limit` | `channel_id, limit, before, query, provider_filter(body)` | 🟡 缺 before(游标分页)/query(频道内搜索)/provider_filter |
| 9 | `channels sync-names` | POST /resource/channels/sync-names | `channel_ids` (list) | `channel_ids(body)` | ✅ 无问题 |
| 10 | `channels sync-cancel` | POST /resource/channels/sync/cancel | (无 body) | (无 body) | ✅ 无问题 |
| 11 | **`subscribe start`** | POST /subscription/start | **`task_name`** | **`name`(body)** | **🔴 字段名不匹配：CLI 发 `task_name`，API 读 `name`。带任务名启动时 API 收到空值 → 404** |
| 12 | `subscribe stop` | POST /subscription/stop | `{}` | `name(body)` | 🟢 空 body 停止全部，无问题 |
| 13 | `subscribe add` | POST /subscription/save | `tasks: [{name,media_type,title,keyword,quality,savepath,provider,season,total_episodes,aliases,exclude_keywords,min_score,anime_mode,strict_title_match,cron_minutes,enabled}]` | `tasks(body)` → `normalize_subscription_task()` 读 `name,media_type,title,keyword,quality,savepath,provider,season,total_episodes,aliases,exclude_keywords,min_score,anime_mode,strict_title_match,cron_minutes,enabled,...` | 🟡 缺 20+ 可选字段: year, exclude_file_extensions, quality_priority, min_file_size_mb, tmdb_id, tmdb_media_type, share_link_url, share_link_receive_code, share_subdir, fixed_link_channel_search, schedule_* 等。⏩ 送 `keyword` 字段（API 接受但未用于匹配逻辑——浪费） |
| 14 | `subscribe remove` | POST /save_settings (而非 POST /subscription/delete) | CLI 修改 `subscription_tasks` 列表 | `merge_settings()` + `normalize_subscription_task()` | 🟡 不走 /subscription/delete 端点 → 不清除 runtime 状态(队列/运行记录) |
| 15 | `subscribe status` | GET /subscription/status | (无) | `compact(query)` | ✅ 无问题 |
| 16 | `subscribe logs` | GET /subscription/logs | (无) | `after, before, limit(query)` | ✅ 无问题 |
| 17 | `subscribe logs-clear` | POST /subscription/logs/clear | (无 body) | (无 body) | ✅ 无问题 |
| 18 | `subscribe rebuild` | POST /subscription/rebuild | `name` | `name(body)` | ✅ 无问题 |
| 19 | `subscribe episodes` | GET /subscription/episodes | `name` (GET params) | `name(query)` | ✅ 无问题 |
| 20 | `subscribe start-with-link` | POST /subscription/start_with_link | `name, link_url, savepath` | `name, link_url/raw_text, receive_code(body)` | 🟢 savepath 不被该端点使用（垃圾字段）；缺 receive_code（非必填） |
| 21 | `jobs list` | GET /resource/jobs/state | `limit, status` | `limit, offset, status(query)` | 🟢 缺 offset |
| 22 | **`jobs create`** | POST /resource/jobs/create | `resource_id, savepath` | `resource_id/resource, savepath, receive_code, magnet_provider, auto_refresh, allow_duplicate, folder_id, sharetitle, refresh_delay_seconds, share_selection(body)` | 🟡 缺 receive_code/magnet_provider/auto_refresh/allow_duplicate/folder_id/sharetitle/refresh_delay_seconds/share_selection |
| 23 | `jobs retry` | POST /resource/jobs/retry | `job_id` | `job_id(body)` | ✅ 无问题 |
| 24 | `jobs refresh` | POST /resource/jobs/refresh | `job_id` | `job_id(body)` | ✅ 无问题 |
| 25 | `jobs cancel` | POST /resource/jobs/cancel | `job_id` | `job_id(body)` | ✅ 无问题 |
| 26 | `jobs clear` | POST /resource/jobs/clear | (无 body) | `scope(body)` | 🟢 缺 scope（默认 completed，无问题） |
| 27 | `jobs clear-completed` | POST /resource/jobs/clear_completed | (无 body) | (无 body) | ✅ 无问题 |
| 28 | `settings` (view) | GET /get_settings | (无) | (读取全部配置) | ✅ 无问题 |
| 29 | `settings key=val` | POST /save_settings | `{key: val, ...}` | `merge_settings()` | ✅ 无问题 |
| 30 | `settings --test-proxy` | POST /settings/tg_proxy/test | `{}` | `tg_proxy_enabled, tg_proxy_protocol, tg_proxy_host, tg_proxy_port(body)` | ✅ 空 body 使用当前配置默认值 |
| 31 | `settings --test-pansou` | POST /settings/pansou/test | `{}` | (从配置读取 normalized) | ✅ 空 body 使用当前配置 |
| 32 | `settings --test-notify` | POST /settings/notify/test | `{}` | `notify_push_enabled, notify_channel, ...(body)` | ✅ 空 body 使用当前配置 |
| 33 | `logs [--tail N]` | GET /logs | (无) | `compact(query)` | ✅ 无问题（尾数用 `--tail N` 指定，避免与 clear 位置参数冲突） |
| 34 | `logs clear` | POST /logs/clear | (无 body) | (无 body) | ✅ 无问题 |
| 35 | `cookies check` | POST /settings/cookies/check | `{}` | `providers, force(body)` | 🟢 空 body → 使用默认 providers 和 force, 无问题 |
| 36 | `cookies status` | GET /settings/cookies/status | (无) | `refresh(query)` | 🟢 缺 refresh |
| 37 | `cookies test` | POST /test_provider_cookie | `provider` | `provider, cookie, credentials(body)` | ✅ 无问题 |
| 38 | `sign run` | POST /settings/115/sign/run | (无 body) | (无 body) | ✅ 无问题 |
| 39 | `sign status` | GET /settings/115/sign/status | (无) | `refresh(query)` | ✅ 无问题 |
| 40 | `tmdb search` | GET /tmdb/search | `q, page` | `q, media_type, year, page(query)` | 🟢 缺 media_type, year |
| 41 | `tmdb popular` | GET /tmdb/popular | `page` | `media_type, page(query)` | 🟢 缺 media_type |
| 42 | `tmdb trending` | GET /tmdb/trending | `page` | `media_type, time_window, page(query)` | 🟢 缺 media_type, time_window |
| 43 | **`tmdb detail`** | GET /tmdb/detail | **`tmdb_id`** | **`tmdb_id, media_type(query)`** | **🔴 缺 media_type → API 返回 400 "TMDB 类型仅支持 movie / tv"** |
| 44 | `tmdb genres` | GET /tmdb/genres | (无) | `media_type(query)` | 🟢 缺 media_type（默认 movie） |
| 45 | `tmdb discover` | GET /tmdb/discover | `page` | `media_type, genres, sort_by, vote_average_gte, year, page, with_original_language, year_from, year_to, vote_count_gte, runtime_gte, runtime_lte(query)` | 🟢 缺所有过滤参数 |
| 46 | `sources save` | POST /resource/sources/save | `sources: [{channel_id, name}]` | `sources(body)` → `normalize_resource_source()` 接受更多字段 | 🟡 缺 url/notes/usage/enabled/sync_enabled/search_enabled |
| 47 | `providers` | GET /api/providers | (无) | (无) | ✅ 无问题 |
| 48 | **`browse ls`** | GET /resource/browse | **`provider_name, cid`** | **`provider(query), cid(query)`** | **🔴 字段名不匹配：CLI 发 `provider_name`，API 读 `provider` → provider 取默认值 "115"，始终只查 115** |
| 49 | **`browse tree`** | GET /resource/browse | **`provider_name, cid, folders_only`** | **`provider(query), cid, folders_only, compact, force_refresh(query)`** | **🔴 同 ls，provider_name→provider 不匹配**；🟢 缺 compact/force_refresh |
| 50 | `browse folders` | GET /resource/browse/{provider}/folders | `cid` | `cid, folders_only, compact, force_refresh(query)` | ✅ cid 从路径参数读 provider，从 query 读 cid；🟢 缺 compact/force_refresh |
| 51 | `browse create-folder` | POST /resource/browse/{provider}/folders/create | `cid, name` | `cid, name(body)` | ✅ 无问题 |
| 52 | **`share preview`** | GET /resource/browse/{provider}/share_entries | **`link_url, receive_code, cid`** | **`resource_id, cid, receive_code, paged, folders_only, force_refresh, offset, limit(query)`** | **🔴 结构性不匹配：API 从 `resource_id` 查 DB 获取链接 URL，CLI 传 `link_url` 直接被忽略。`link_url` 参数无对应处理。** 应改用 `share preview-batch`（POST 端点） |
| 53 | `share preview-batch` | POST /resource/browse/{provider}/share_entries_preview | `link_url` | `link_url, raw_text, receive_code, cid, paged, folders_only, force_refresh, offset, limit(body)` | 🟡 缺 raw_text/receive_code/cid/paged/folders_only/force_refresh/offset/limit |
| 54 | `share receive` | POST /resource/jobs/create | `resource_id, savepath` | (同 jobs create) | 🟡 同 jobs create，缺多个可选字段 |
| 55 | **`monitor add`** | POST /save_settings | `name, scan_path, cron_minutes, webhook_enabled, delay_seconds, enabled` | `normalize_task()` 接受 `name, scan_path, cron_minutes, webhook_enabled, delay_seconds, enabled, target_path, skip_by_dir_mtime, strm_write_mode, sync_clean, retries, list_delay_ms, min_file_size_mb` | 🟡 通过 /save_settings 间接保存；缺 target_path/skip_by_dir_mtime/strm_write_mode/sync_clean/retries/list_delay_ms/min_file_size_mb |
| 56 | `monitor start/stop/status/logs/logs-clear/userscript-jobs` | 各独立端点 | (无 body 或简单请求) | | ✅ 无问题 |
| 57 | `tree run/full/list/create/update/delete/defaults/jobs` | POST /tree/tasks/{id}/run、/full、POST /tree/tasks、POST /tree/tasks/{id}、DELETE、GET /tree/task-defaults、/tree/sync-all 等 | `folder_path/tree_name` | `folder_path, tree_name(body)`；prefix/exclude 由后端按文件夹自动推导，不接受手动覆盖 | 🟢 无参数缺失；`run` 不带 `--id` 时走 /tree/sync-all（不导出，仅对比更新） |
| 58 | `tree status` | GET /status-summary | (无) | (从 summary 读 main 字段) | ✅ 无问题 |
| 59 | `tree logs` | GET /tree/logs | (无) | `compact(query)` | ✅ 无问题 |
| 60 | `tree logs-clear` | POST /tree/logs/clear | (无 body) | (无 body) | ✅ 无问题 |
| 61 | **`scrape jobs-create`** | POST /scraper/jobs/create | **`path`** | **`plan.actions` (从 payload.get("plan", {}).get("actions", []))** | **🔴 结构性不匹配：`create_scraper_job_from_plan()` 读取 payload.plan.actions（改名计划操作列表），CLI 只发 `{"path": path}`，plan 和 actions 均为空 → API 返回 400 "没有可执行的改名计划"。需要先调 rename-plan 再提交** |
| 62 | **`scrape rename-warning`** | POST /scraper/{provider}/rename-warning | **`path`** | **`old_path, new_path(body)`** | **🔴 字段名不匹配：CLI 发 `path`，API 读 `old_path` AND `new_path`（两个都是必填）。缺少 new_path 导致 API 返回 400。** |
| 63 | `scrape identify` | POST /scraper/identify | `entries: [{path}]` | `payload.get("entries", [])` → `identify_scraper_media(payload)` | ✅ 已修复（原发 `{"path": path}`，现发 `{"entries": [{"path": path}]}`） |
| 64 | `scrape rename-plan` | POST /scraper/rename-plan | `entries: [{path}]` | `payload.get("entries", [])` → `build_scraper_rename_plan(payload)` | ✅ 已修复 |
| 65 | `scrape rename` | POST /scraper/{provider}/rename | `path, name` | `entry_id, parent_id, name, path(body)` — 有 path→entry_ids 回退 | ✅ 有回退机制 |
| 66 | `scrape move` | POST /scraper/{provider}/move | `path, dest` | `entry_ids, target_cid, dest, path(body)` — 有 path→entry_ids 和 dest→target_cid 回退 | ✅ 有回退机制 |
| 67 | `scrape copy` | POST /scraper/{provider}/copy | `path, dest` | `entry_ids, target_cid, dest, path(body)` — 有回退 | ✅ 有回退机制 |
| 68 | `scrape delete` | POST /scraper/{provider}/delete | `path` | `entry_ids, path(body)` — 有回退 | ✅ 有回退机制 |
| 69 | `scrape diff` | GET /scraper/jobs/state | `limit` | `limit, job_id(query)` | ✅ 无问题 |
| 70 | `scrape jobs` | GET /scraper/jobs/state | `limit, provider` | `limit, job_id(query)` | 🟢 provider 字段作为 GET params 传，API 用 `job_id` 而非 `provider`（provider 被忽略） |
| 71 | `scrape providers` | GET /scraper/providers | (无) | (无) | ✅ 无问题 |
| 72 | `scrape entries` | GET /scraper/{provider}/entries | (无) | `cid, force_refresh, keyword(query)` | ✅ 无问题 |
| 73 | `scrape folders` | POST /scraper/{provider}/folders | `cid` | `cid, name(body)` | ✅ 无问题 |
| 74 | `scrape rollback` | POST /scraper/jobs/{job_id}/rollback | (无 body) | (路径参数 job_id) | ✅ 无问题 |
| 75 | `scrape jobs-clear` | POST /scraper/jobs/clear | (无 body) | `scope(body)` | 🟢 缺 scope（默认 completed，无问题） |
| 76 | **`watchlist add`** | POST /recommendation/watchlist/add | `tmdb_id, title, media_type` | `tmdb_id, media_type, title, original_title, year, poster_url, overview, vote_average, tmdb_detail(body)` | ✅ 已修复（原缺 title，现完整） |
| 77 | **`watchlist remove`** | POST /recommendation/watchlist/remove | **`tmdb_id`** | **`id(body)`** | **🔴 字段名不匹配：CLI 发 `tmdb_id`，API 读 `id`（数据库记录 ID，不是 TMDB ID）。API 按 tmdb_id 查不到记录 → 无操作。应该发 `{"id": N}` 或者换个端点。** |
| 78 | **`watchlist update`** | POST /recommendation/watchlist/update_status | **`tmdb_id, status`** | **`id, status(body)`** | **🔴 同 remove，CLI 发 `tmdb_id` 但 API 读 `id`（DB 记录 ID）。status 值也不同：API 支持 `want/subscribed/done`，CLI 发 `watching/completed/pending/dropped`。** |
| 79 | `strm orphans` | GET /strm/orphan-metadata/preview | (无) | `root(query)` | ✅ 无问题 |
| 80 | `strm cleanup` | POST /strm/orphan-metadata/delete | `{}` | `paths, root(body)` | 🟢 空 body = 删除全部孤儿文件 |
| 81 | `strm dirs` | GET /strm/orphan-metadata/local-dirs | (无) | `path(query)` | ✅ 无问题 |
| 82 | `resource import` | POST /resource/items/import_text | `raw_text, provider` | `raw_text, source_name, source_type, channel_name, published_at, message_url(body)` | 🟢 缺 source_name/source_type/channel_name/published_at/message_url；⏩ `provider` 不被 API 使用（无对应处理） |
| 83 | `resource preview` | POST /resource/items/preview_text | `raw_text` | `raw_text, source_name, source_type, channel_name, published_at, message_url(body)` | 🟢 同 import，缺元数据字段 |
| 84 | `resource quick-links` | GET /get_settings + POST /save_settings | (通过 config 读写) | | ✅ 无问题 |
| 85 | `resource delete --id <资源ID>` | POST /resource/items/delete | `id` | `id(body)` | ✅ 无问题（ID 用 `--id` 传入，避免被 quick-links 子操作位置参数吞掉） |
| 86 | `health` | 多端点组合 | (无 body) | (无 body) | ✅ 无问题 |
| 87 | `stats` | GET /resource/state | `compact` | (同 search) | ✅ 无问题 |
| 88 | `daemon status/logs/restart` | docker CLI 而非 HTTP | (N/A) | (N/A) | ✅ 无问题 |
| 89 | `api <method> <path> [body]` | 通用 HTTP 代理 | (直接透传) | (直接透传) | ✅ 无问题 |

---

## 🔴 HIGH 严重性问题汇总

| # | 命令 | 问题 | 影响 |
|---|------|------|------|
| H1 | `subscribe start --name "xxx"` | CLI 发 `task_name`，API 读 `name` | 指定任务名启动时，API 收到 `{"task_name":"xxx"}`，查找 `data.get("name")` 返回空 → 404。**命令已损坏** |
| H2 | `tmdb detail --tmdb-id 123` | 缺 `media_type` 必填参数 | API 要求 media_type 必须是 movie/tv，缺省时返回 400。**命令已损坏** |
| H3 | `browse ls --provider quark` | CLI 发 `provider_name`，API 读 `provider` | 当指定 `--provider quark` 时，API 取默认值 "115"，忽略 CLI 传入值。**`--provider` 参数完全无效** |
| H4 | `browse tree --provider quark` | 同 ls | 同上 |
| H5 | `share preview <url>` | CLI 传 `link_url` 但 API 读 `resource_id`（从 DB 查） | `link_url` 被 API 完全忽略。无法通过原始链接预览分享内容。**命令已损坏** |
| H6 | `scrape jobs-create <path>` | CLI 发 `{"path": path}`，API 需 `{"plan": {"actions": [...]}}` | `create_scraper_job_from_plan()` 读空 `plan.actions` → 400 "没有可执行的改名计划"。**命令已损坏** |
| H7 | `scrape rename-warning <path>` | CLI 发 `path`，API 需 `old_path` + `new_path` | API 读 `data.get("old_path")` 和 `data.get("new_path")`，两者均空 → 400。**命令已损坏** |
| H8 | `watchlist remove <tmdb_id>` | CLI 发 `tmdb_id`，API 读 `id`（DB 记录 ID） | CLI 用 TMDB ID 查 API，API 查 DB 记录主键 ID。**`tmdb_id` 参数完全无效** |
| H9 | `watchlist update <tmdb_id> --status watching` | CLI 发 `tmdb_id`（API 读 `id`）+ status 值范围不匹配 | 同 remove，`tmdb_id` 变 `id` 不匹配。API 支持 `want/subscribed/done`，CLI 发 `watching/completed/pending/dropped`。**命令完全损坏** |
| H10 | `scrape jobs --provider 115` | CLI 发 `provider` 作为 GET 参数，API 不读 | API 的 GET /scraper/jobs/state 只读 `limit, job_id`，`provider` 被完全忽略。**`--provider` 参数无效** |

## 🟡 MEDIUM 严重性问题汇总

| # | 命令 | 问题 |
|---|------|------|
| M1 | `subscribe add` | 缺 20+ 可选字段（year, quality_priority, tmdb_id, schedule_* 等） |
| M2 | `subscribe remove` | 走 /save_settings 而非 /subscription/delete → 不清除运行时状态 |
| M3 | `channels more` | 缺 before(游标)/query(频道内搜索)/provider_filter |
| M4 | `jobs create` | 缺 receive_code/magnet_provider/auto_refresh/allow_duplicate/folder_id/sharetitle 等 |
| M5 | `share receive` | 同 jobs create |
| M6 | `share preview-batch` | 缺 raw_text/receive_code/cid/paged/folders_only/force_refresh 等 |
| M7 | `monitor add` | 缺 target_path/strm_write_mode/retries/list_delay_ms/min_file_size_mb 等 |
| M8 | `sources save` | 缺 url/notes/usage/enabled/sync_enabled/search_enabled |
| M9 | `resource import` | `provider` 字段不被 API 使用（浪费） |

## 🟢 LOW 严重性汇总

| # | 命令 | 缺省字段 |
|---|------|---------|
| L1 | `search` | search_source, provider_filter, search_id, job_limit/offset/job_status, sync |
| L2 | `channels sync` | limit(limit_per_channel) |
| L3 | `channels classify` | sample_size |
| L4 | `tmdb search` | media_type, year |
| L5 | `tmdb popular` | media_type |
| L6 | `tmdb trending` | media_type, time_window |
| L7 | `tmdb genres` | media_type |
| L8 | `tmdb discover` | 全部过滤参数 |
| L9 | `browse ls` | compact, force_refresh |
| L10 | `browse tree` | compact, force_refresh |
| L11 | `browse folders` | compact, force_refresh |
| L12 | `tree run` | --id |
| L13 | `subscribe start-with-link` | receive_code |
| L14 | `jobs list` | offset |
| L15 | `strm cleanup` | paths, root |
| L16 | `resource import/preview` | source_name, source_type, channel_name, published_at, message_url |

## Parser 参数缺失审计（_build_parser 中未暴露的参数）

| 子命令 | CLI 已有参数 | API 支持但 CLI 未暴露的字段 | 严重度 |
|--------|-------------|---------------------------|--------|
| `subscribe add` | --type, --quality, --savepath, --provider, --link, --title, --aliases, --season, --total-episodes, --exclude-keywords, --min-score, --anime-mode, --strict-match, --cron-minutes | --year, --exclude-file-extensions, --quality-priority, --min-file-size-mb, --tmdb-id, --link-receive-code, --share-subdir, --schedule-weekdays, --schedule-start-time, --schedule-end-time | 🟡 |
| `jobs create` | --resource-id, --savepath | --receive-code, --magnet-provider, --allow-duplicate, --folder-id, --sharetitle, --refresh-delay-seconds | 🟡 |
| `monitor add` | --scan-path, --cron-minutes, --webhook, --delay, --pause | --target-path, --strm-write-mode, --retries, --list-delay-ms, --min-file-size-mb | 🟢 |
| `sources save` | --channel, --title | --url, --usage, --enabled, --sync-enabled, --search-enabled | 🟢 |
| `channels more` | --channel, --limit | --before(游标), --query(频道内搜索), --provider-filter | 🟢 |
| `search` | keyword(位置参数), action | --search-source, --provider-filter, --job-limit, --job-offset, --job-status, --sync | 🟢 |
| `tmdb *` | keyword, --tmdb-id, --page | --media-type, --year, --time-window, --genres, --sort-by, --vote-average-gte | 🟡 |
| `share preview-batch` | url, --provider, --code, --cid | --raw-text, --paged, --folders-only, --force-refresh, --offset, --limit | 🟢 |
| `browse ls/tree` | --provider, --cid | --compact, --force-refresh | 🟢 |
| `browse folders` | --provider, --cid | --compact, --force-refresh | 🟢 |
| `resource import` | --text, --provider | --source-name, --source-type, --channel-name, --published-at, --message-url | 🟢 |
| `resource preview` | --text | --source-name, --source-type, --channel-name, --published-at, --message-url | 🟢 |

## 修复优先级排序

### P0 — 立即修（命令已损坏）
1. `watchlist remove` — 改 API 接受 `tmdb_id` 或 CLI 发 `id`（查 DB 获取记录 ID）
2. `watchlist update` — 同上 + 统一 status 值范围
3. `subscribe start` — 改 CLI 发 `name` 或 API 也接受 `task_name`
4. `browse ls/tree` — 改 CLI 发 `provider` 而非 `provider_name`
5. `scrape jobs-create` — 改 CLI 先调 rename-plan 获取 plan，再提交
6. `scrape rename-warning` — 改 CLI 发 `old_path`/`new_path` 或改 API 接受 `path` 单字段
7. `share preview` — 改走 POST `/share_entries_preview`（即 preview-batch）
8. `tmdb detail` — 加 `--type movie|tv` 参数

### P1 — 建议修
1. `subscribe remove` — 改用 POST /subscription/delete
2. `subscribe add` — 加 --year/--exclude-file-extensions/--quality-priority/--tmdb-id 参数
3. `resource import` — 移除无用 `provider` 字段
4. `scrape jobs` — 移除无用 `provider` 字段或改用 provider 路径参数

### P2 — 可延后
- 所有 🟢 级别的可选参数补齐
