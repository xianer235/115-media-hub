# Seerr 扫描状态调查记录（2026-11-21）

> 用途：记录 Seerr（seerr.shuxian.fun）只读接口的返回结构、字段含义，以及一次「媒体总数卡在 5480 不涨」问题的排查结论，供以后开发 Seerr 集成时直接查。
> 全程只读，未对 Seerr / 极影视做任何写操作。

---

## 1. 环境与鉴权

- 地址：`https://seerr.shuxian.fun`（Jellyseerr，版本 3.5.x）
- 鉴权：请求头 `X-Api-Key: MTc5NDg2OTY4OTE3NzAyYTU4MWRlLWZjZTUtNGQxOS05NzJmLTYyNGZlNjk4M2NmZA==`
- 极影视（Emby 桥上游）：`http://192.168.0.2:5000`，URL Base `/emby-bridge`，ServerId `28196d9a28efb6156bd55c4656e195bb`

---

## 2. 用到的接口与返回结构

### 2.1 `GET /api/v1/settings/jobs` — 任务状态

返回 JSON 数组，每个元素：

```json
{
  "id": "jellyfin-full-scan",
  "name": "Jellyfin Full Library Scan",
  "type": "process",              // process | command
  "interval": "hours",
  "cronSchedule": "0 0 */72 * * *",
  "nextExecutionTime": "2026-11-22T00:00:00.000+08:00",
  "running": true                 // 是否正在跑
}
```

关键任务 id：
- `jellyfin-full-scan` — 全量扫描（本次排查对象）
- `jellyfin-recently-added-scan` — 最近新增扫描
- `radarr-scan` / `sonarr-scan` — Radarr/Sonarr 扫描
- `availability-sync` / `download-sync` 等

### 2.2 `GET /api/v1/media?take=0` — 媒体总数

`take=0` 时只返回分页元信息 + 空 results。`pageInfo.results` 即媒体总数：

```json
{
  "pageInfo": { "pages": 274, "pageSize": 20, "results": 5480, "page": 1 },
  "results": [ ... ]
}
```

**判断扫描是否涨数的唯一依据是 `pageInfo.results`。**

`take>0` 时 results 里每个媒体条目关键字段：
- `mediaType`：`movie` | `tv`
- `tmdbId`：TMDb ID（**入库条目的关键标识，匹配成功才有值**）
- `jellyfinMediaId`：`collection_xxx_<serverId>` 格式；非 Jellyfin 来源为 null
- `status` / `status4k`：可用性状态
- `seasons`：剧集的季信息
- `mediaUrl`：指向极影视 emby-bridge 的条目链接

### 2.3 `GET /api/v1/settings/logs?take=N` — 日志

**注意：`page` 参数不生效**（带 page=2 会返回 KeyError，实际总是不分页返回最新 N 条，按时间倒序）。结构：

```json
{
  "pageInfo": { "pages": 245, "pageSize": 40, "results": 9806, "page": 1 },
  "results": [
    {
      "label": "Jellyfin Sync",     // 扫描相关日志的 label
      "level": "debug|info|warn|error",
      "message": "Failed to process Jellyfin item, id: ...",
      "errorMessage": "Unable to find TMDb ID",
      "timestamp": "2026-11-20T19:05:22.707Z",
      "data": { "errorMessage": "...", "jellyfinitem": { ... } }
    }
  ]
}
```

Jellyfin Sync 关键 message（用于判断扫描进度/结果）：
- `Scan starting` — 一轮扫描开始
- `Beginning to process library: <库名>` — 开始处理某个库
- `Beginning to process recently added for library: <库名>` — 最近新增扫描
- `Updating existing title: <片名>` — 条目匹配成功（更新已有）
- `No information found for the show: <片名>` — 匹配不到（非致命，debug 级）
- `Failed to process Jellyfin item, id: <id>` — **处理失败（error 级）**
- `Full Scan Complete` — 全量扫描完成
- `Recently Added Scan Complete` — 最近新增扫描完成

### 2.4 `GET /api/v1/settings/jellyfin` — Jellyfin/Emby 服务器配置

返回 Seerr 里配置的 Jellyfin 服务器信息（含库列表）：

```json
{
  "name": "极影视",
  "ip": "192.168.0.2",
  "port": "5000",
  "urlBase": "/emby-bridge",
  "libraries": [
    { "id": "class_50127c23-...", "name": "连载中", "enabled": true, "type": "show" },
    { "id": "class_f4c94a3d-...", "name": "电影库",   "enabled": true, "type": "movie" },
    { "id": "class_57da9e8b-...", "name": "电视剧库", "enabled": true, "type": "show" },
    { "id": "class_f7a890f1-...", "name": "纪录片库", "enabled": true, "type": "show" },
    { "id": "class_4b96164e-...", "name": "电影",     "enabled": true, "type": "movie" },
    { "id": "class_221cc6ee-...", "name": "电视剧",   "enabled": true, "type": "show" },
    { "id": "class_ce887681-...", "name": "夸克",     "enabled": false, "type": "show" }
  ],
  "serverId": "28196d9a28efb6156bd55c4656e195bb",
  "apiKey": "9827c00334efc9db..."
}
```

**注意：`/api/v1/settings/jellyfin/libraries` 是 404，库列表要读 `/settings/jellyfin` 里的 `libraries` 字段。**

---

## 3. 本次问题排查结论

### 3.1 现象

媒体总数 `pageInfo.results = 5480`，长期不涨；`jellyfin-full-scan running = true`；上一个 Full Scan 已在 2026-11-20 17:36 UTC 打出 `Full Scan Complete`，18:45 UTC 又启动新的一轮。

### 3.2 根因（已实锤）

**不是扫描中断，而是大量 Jellyfin 条目匹配不到 TMDb，Seerr 无法入库。**

证据链：
1. 失败条目清一色 `.strm` 占位文件，且 `jellyfinitem.ProviderIds` 字段**缺失或为空**（无 `Tmdb`）。
2. 成功入库的 5480 条，全部有 `tmdbId`。
3. Seerr 的 Jellyfin Sync 只认条目里的 `ProviderIds.Tmdb`（或能反推出的 TMDb ID），拿不到就报 `Unable to find TMDb ID`。

### 3.3 失败条目的分布（take=3000 采样，共 111 条失败）

按根路径分类：

| 分类 | 数量 | 说明 |
| --- | --- | --- |
| `115影视大库/大库-纪录片` | 58 | **重灾区**，几乎全是「盗火纪录片」目录的散 `.strm` |
| （无 Path，日志未带路径） | 44 | 多为老电影/动画电影（老少爷们上法场、精灵宝可梦系列等） |
| `115影视大库/大库-电影` | 4 | 动画电影、老电影1100部、自存电影挪移 |
| `115影视小库` | 3 | 测试片段类 |
| `/sata13/影视库`（本地文件，非 strm） | 2 | 追风筝的人、致命玩笑（普通 mkv，非占位） |

失败原因细分：
- `Unable to find TMDb ID` — 绝大多数（占大头）
- `[TMDB] Failed to find media using external IMDb ID: No movie or show returned from API for ID tt...` — 少数（有 IMDb 但 TMDB 查不到）

### 3.4 各库匹配情况（take=1000 采样，仅覆盖本轮已扫到的库）

| 库 | 类型 | 成功 | 失败 | 结论 |
| --- | --- | --- | --- | --- |
| 电视剧 | show | 421 | 0 | ✅ 全 |
| 连载中 | show | 5 | 0 | ✅ 全 |
| 电影库 | movie | 43 | 37 | ⚠️ 失败率约 46% |

（电视剧库 / 纪录片库 / 电影 三个库在本轮采样时未扫到，暂无法下结论。）

### 3.5 与设计文档的出入（重要）

`2026-11-17-emby-bridge-for-seerr-design.md` §2.1 实测结论称极影视条目「`ProviderIds.Tmdb` 齐全」。但本次调查发现：**散落的 `.strm` 占位文件（尤其纪录片、老电影）的 `ProviderIds` 是空的**。

结论：极影视对 `.strm` 占位文件的刮削深度不一致——能被正确识别/写入 Tmdb 的条目能入库，大量「盗火纪录片」等目录的散 strm 只做了基础识别、没写 Tmdb ProviderId，导致 Seerr 匹配失败。

### 3.6 后续开发提示

- 判定「全量扫描是否完成」不能只看 `running`，要看 `media?take=0` 的 `pageInfo.results` 是否涨到预期值。
- 要让媒体总数上到 2 万，需解决极影视侧 `.strm` 条目缺 Tmdb ProviderId 的问题（重刮或补元数据），不是 Seerr / emby-bridge 的问题。
- 日志接口 `page` 参数无效，翻页拿历史日志需换思路（或直接用更大 take）。
