# 极影视 → Seerr 的 Emby 兼容桥（emby-bridge）执行方案

> 目标：让 Seerr 通过**极影视已有的媒体库索引**判重，不再额外部署一套重复扫描的 Jellyfin。
> 本文档面向执行者（代码能力一般的 AI 或工程师），每一步都写明：改哪个文件、在哪、改成什么、为什么。
> **不要自行发挥，不要改动本文未提到的行为。** 与项目约定（`docs/superpowers/conventions.md`）冲突时，以约定为准并停下来报告。
>
> 状态：**实测完成，可实施**。协议细节已用真实极影视 + Jellyseerr 源码钉死（见 §2），不是纸面推演。

---

## 1. 目标与范围

### 1.1 做什么

在面板里新增一个 `/emby-bridge` 前缀的**反向代理 + 协议适配层**，让 Jellyseerr 把极影视当成一台标准 Emby 服务器：

- Seerr 登录桥 → 桥用面板里存的媒体库账号换极影视 token → 后续请求逐条翻译后转发。
- Seerr 拉媒体库列表、判重（"库里已有这部片吗"）→ 桥把极影视的返回翻译成 Seerr 认的格式。
- **目的只有一个：判重**。让 Seerr 知道库里已有什么，避免把已入库的片重复显示成「可请求」。下载/补源仍走现有 servarr 兼容层，与桥无关。

### 1.2 不做什么（防止范围蔓延）

- **不做**写操作：不建库、不删条目、不改极影视任何东西。
- **不代理播放流**：桥只转发 API JSON，不碰媒体流。
- **不替代极影视**，也不替代现有 Jellyfin 容器（桥跑稳前不删 Jellyfin）。
- **不新增**任何第三方依赖（项目铁律：零新增依赖）。转发用 Python 标准库 `urllib`（项目现有 `app/http_utils.py` 同源），token 缓存用内存 dict。
- **不改动** servarr 兼容层、订阅任务、落点约定。
- **不动**版本号 / CHANGELOG / README（留到发版提交）。

### 1.3 部署事实（2026-11-17 用户确认）

Seerr 与面板**在同一台 NAS、同一局域网、直连**（不经过反向代理）。因此「内网来源判定」直接读连接对端 IP，判断是否 RFC1918 / 回环即可，**不需要解析 `X-Forwarded-For`**。

---

## 2. 实测结论（2026-11-17，用真实环境钉死）

环境：极影视 Emby 层 `https://jys.shuxian.fun`（账号 `xianer`），Jellyseerr 3.5.2（`https://seerr.shuxian.fun`，源码 Fallenbagel/jellyseerr develop 分支，已克隆到 `/tmp/jellyseerr-src` 核对）。

### 2.1 极影视侧实测

| 项 | 实测结果 |
| --- | --- |
| 版本 / 名称 | `4.7.0.0`，ServerName「极影视」，ServerId `28196d9a...` |
| `POST /Users/AuthenticateByName` | 200，返回 `AccessToken`；同账号重复登录返回**同一 token 不轮换** |
| 鉴权头 | **只认 `X-Emby-Token` 头或 `X-Emby-Authorization` 内嵌 `Token=`**；`Authorization: MediaBrowser ...` 头 → 401 |
| `/Auth/Keys`（GET/POST） | **404 page not found**（极影视根本没实现） |
| 媒体库 `GET /Users/{uid}/Views` | 200，7 个库；**每个库 `CollectionType` 都是 `None`**（不是标准 `movies`/`tvshows`） |
| 条目 `GET /Users/{uid}/Items?Recursive=true` | 200；`Type`（Movie/Series）、`ProviderIds.Tmdb`、`ProductionYear` 齐全 |
| 单条 `GET /Users/{uid}/Items/{itemId}` | 200，返回 `ProviderIds.Tmdb` 等完整字段 |
| `/Items?ids={id}` | **忽略 `ids` 参数**，返回全部 7 个媒体库（`Items[0]` 是第一个库、`ProviderIds=None`） |
| `/Shows/{id}/Seasons` | 200，`IndexNumber` 正常 |
| `/Shows/{id}/Episodes?seasonId=N` | 200，`IndexNumber`/`SeasonId`/`SeriesId` 齐全；`LocationType=None` |
| 条目 ID 格式 | 自定义 `collection_xxx` / `season_xxx` / `video_xxx` / `people_xxx`（**非标准 UUID**） |

### 2.2 Jellyseerr 侧源码结论（`server/api/jellyfin.ts`）

| 关键函数 | 行为 | 对桥的要求 |
| --- | --- | --- |
| 构造函数（`Authorization` 头） | 发 `Authorization: MediaBrowser Client="Seerr", Device="Seerr", DeviceId="...", Version="1.0.0"[, Token="x"]` | 桥把它转成 `X-Emby-Authorization`（或抽 `Token` 放 `X-Emby-Token`） |
| `login` | `POST /Users/AuthenticateByName` 拿 `AccessToken` | 桥对上游用真实 token |
| `createApiToken` | `POST /Auth/Keys?App=Seerr` → `GET /Auth/Keys` → `Items.reverse().find(AppName==="Seerr").AccessToken` | 桥本地实现，返回 `{Items:[{AppName:"Seerr", AccessToken:"..."}]}` |
| `getLibraries` | `GET /Library/MediaFolders`（失败回退 `Views`）→ `mapLibraries` | `CollectionType==="movies"` 判 movie 否则 show；桥必须补 `CollectionType` |
| `getLibraryContents` | `GET /Items?IncludeItemTypes=Series,Movie,Others&Recursive=true&ParentId={id}` | 直接转发即可（**不用 `AnyProviderIdEquals`**） |
| `getItemData`（判重核心） | `GET /Items?ids={id}&fields=ProviderIds` 取 `Items[0].ProviderIds.Tmdb` | **极影视忽略 `ids` → 必须改写为 `/Users/{uid}/Items/{id}`** |
| `getSeasons` / `getEpisodes` | `/Shows/{id}/Seasons`、`/Shows/{id}/Episodes?seasonId=N` | 直接转发即可 |

### 2.3 由此确定的 5 个翻译点（桥的全部工作）

| # | Seerr 的行为 | 极影视对不上 | 桥的翻译 |
| --- | --- | --- | --- |
| T1 | 鉴权头写 `Authorization: MediaBrowser ...` | 只认 `X-Emby-*` | 头改写（见 §3.2） |
| T2 | 登录后调 `/Auth/Keys` 建 key | 404 | 本地实现，返回稳定伪 key |
| T3 | 判重用 `/Items?ids=` | 忽略 `ids` 参数 | **改写为 `/Users/{uid}/Items/{id}`** |
| T4 | 靠 `CollectionType` 分电影/剧集库 | 全 `None` | 返回时补 `movies`/`tvshows` |
| T5 | 公网直连 | 桥默认只放内网 | 来源 IP 白名单（§3.5） |

**T3 是判重成败的关键**：不改写的话，Seerr 会把库里 1.4 万条全判成「未拥有」，每部片都显示可请求。这是方案存在的真正理由，比头改写重要得多。

---

## 3. 技术设计

### 3.1 路由与挂载

- 新文件 `app/routes/emby_bridge.py`，`APIRouter(prefix="/emby-bridge")`，**不走面板登录会话**（与 `servarr.py` 同款：在 `app/main.py` 里不带 `_auth_deps` 地 `include_router`）。
- 一个兜底路由 `@router.api_route("/{path:path}", methods=[...])` 收下所有 `/emby-bridge/*` 请求，交给 service 处理。
- 桥关闭时，兜底路由直接返回 404（见 §3.5）。

### 3.2 服务层：`app/services/emby_bridge.py`

职责：登录与 token 缓存、白名单判定、头改写、请求改写与转发、响应改写。核心是**一个统一入口 `handle(request)`**，按路径分派到下面几类处理：

**（a）头改写（T1）**

把 Seerr 的 `Authorization: MediaBrowser Client="Seerr", Device="Seerr", DeviceId="...", Version="..."[, Token="x"]` 解析成 KV，然后：

- 抽出 `Token`（若有）→ 置入上游请求的 `X-Emby-Token` 头；
- 把除 Token 外的字段重拼成 `X-Emby-Authorization: MediaBrowser Client=..., Device=..., DeviceId=..., Version=...` 头发给上游；
- `DeviceId` 为空时补固定值 `115-media-hub-bridge`（极影视要求非空）。
- 上游返回的任何 `X-Emby-*` 头原样透传回 Seerr。

**（b）`/Auth/Keys` 本地实现（T2）**

不转发，直接本地应答：

- `POST /Auth/Keys?App=Seerr` → 返回 200（body 可为空 JSON `{}`）；
- `GET /Auth/Keys` → 返回 `{"Items": [{"AppName": "Seerr", "AccessToken": "<稳定伪key>"}]}`。

伪 key = `sha256(ServerId + 用户名)` 十六进制，进程内缓存、重启不变。**这个 key 只用来糊弄 Seerr 的 `createApiToken`，不参与上游鉴权**——桥对上游永远用自己缓存极影视返回的真实 token。这是两层 token 的职责边界，别混。

**（c）判重请求改写（T3）**

上游路径是 `/Items` 且 query 带 `ids=` 时：

- 用 `ids` 的值去极影视 `GET /Users/{uid}/Items/{id}` 拿单条，返回 `{"Items": [<该条>], "TotalRecordCount": 1}`（uid 用桥登录时缓存下来的当前用户 id）。

**（d）媒体库返回改写（T4）**

`/Library/MediaFolders` 与 `/Users/{uid}/Views` 的返回里，把每个库的 `CollectionType` 补上：库名含「电影」→ `movies`，其余（电视剧/剧集/连载/纪录片等）→ `tvshows`。都判不出的按 `tvshows`（Seerr 默认把无类型库当剧集）。这一步不改上游其它字段。

**（e）其余请求透传**

白名单内的路径（见 §3.3）直接转发，method / query / body 原样，只做（a）的头改写。

### 3.3 透传白名单

只转发这些前缀，其余返回 404（不盲目全量转发，避免把极影视管理接口暴露给 Seerr）：

`/System/`、`/Users/`、`/Library/`、`/Items`、`/Shows/`、`/Images/`、`/DisplayPreferences/`、`/Branding/`、`/Sessions/`、`/Auth/Keys`。

### 3.4 token 缓存与 401 重登（单飞）

- 进程内缓存 `{token, uid, expire_ts}`；每次收到请求时若缓存有效则直接用。
- 上游返回 401 时：**单飞**（asyncio.Lock / 一个共享 future）重登一次，成功则换新 token 重试该请求**只一次**；失败则把 401 透传给 Seerr。防止并发扫库时多个请求同时触发重登。
- 账号密码只存面板配置，**不落日志**；所有转发日志里对 token 打码。

### 3.5 来源 IP 白名单与开关

- 总开关 `emby_bridge_enabled`（默认关）。关着时兜底路由直接 404。
- 请求进来先判来源 IP：非 RFC1918 / 非回环 → 403（`emby_bridge_allow_public` 打开时才放行公网）。因为 Seerr 与面板同局域网直连（§1.3），直接读 `request.client.host`，不信任任何转发头。
- 未配置 `emby_bridge_upstream` / 账号密码时，返回 503 并提示去配置。

### 3.6 转发方式（流式 + 超时）

- 用标准库 `urllib.request`（与 `app/http_utils.py` 一致），**按块读取**上游响应（`resp.read(64*1024)` 循环）用 `StreamingResponse` 回传，不把大 JSON 一次性读进内存（判重扫库响应可达几十 MB）。
- 超时拆分：连接超时短（如 10s）、读取超时长（如 120s，扫库请求可能几十秒才吐第一个字节）。

### 3.7 配置项（参数配置页）

| 项 | 说明 | 默认 |
| --- | --- | --- |
| `emby_bridge_enabled` | 总开关 | 关 |
| `emby_bridge_upstream` | 极影视地址，如 `http://192.168.0.2:8021` | 空 |
| `emby_bridge_username` / `emby_bridge_password` | 媒体库专用账号（不是极空间登录号） | 空 |
| `emby_bridge_allow_public` | 是否放行公网来源 | 关 |

密码按项目现有敏感配置项方式处理（`core.py` 里已有的敏感字段读写模式）。

---

## 4. 落地清单

1. 新增 `app/services/emby_bridge.py`：登录、token 缓存、白名单、头改写、`/Auth/Keys` 本地实现、`/Items?ids=` 改写、`CollectionType` 补全、来源 IP 判定、流式转发、单飞重登。
2. 新增 `app/routes/emby_bridge.py`：`/emby-bridge` 兜底路由，调 service。
3. `app/main.py`：`from .routes.emby_bridge import router as emby_bridge_router` + `app.include_router(emby_bridge_router)`（不带 `_auth_deps`）。
4. `app/core.py`：配置读写接入（沿用 settings 模式）。
5. 前端：参数配置页新增一组字段 + 开关，原生 JS，改完 `node --check`。
6. **登记 `docs/superpowers/modules.md`**（`tests/test_modules_doc.py` 会校验，漏了直接红）。
7. 测试 `tests/test_emby_bridge.py`（见 §5），走 `scripts/run_tests.py`。

---

## 5. 测试（`tests/test_emby_bridge.py`，unittest）

- 头改写：`Authorization: MediaBrowser ...` 三种入参（带/不带 Token、缺 DeviceId）→ 正确产出 `X-Emby-Authorization` / `X-Emby-Token`。
- `/Auth/Keys`：POST 返回 200、GET 返回含 `AppName="Seerr"` + 稳定 `AccessToken` 的 `Items`。
- `/Items?ids=` 改写：请求被转成 `/Users/{uid}/Items/{id}`，返回结构为 `{Items:[单条]}`。
- `CollectionType` 补全：电影库名 → `movies`，其余 → `tvshows`。
- 401 重登一次 + 单飞：并发多请求只触发一次重登。
- 白名单外路径 404；公网来源 403（`allow_public` 关）；开关关 → 404。
- 未配置 upstream → 503。

用 `unittest.mock` patch 掉真实的 `urllib` 调用，不真连极影视。

---

## 6. 验收标准

1. `scripts/check.sh --all --container` 全绿。
2. 面板侧：`curl -H 'Authorization: MediaBrowser Client="Seerr", Device="Seerr", DeviceId="y", Version="1.0.0"' http://NAS:面板端口/emby-bridge/System/Info` → 200（返回极影视的 `{ServerName:"极影视",...}`）。
3. Seerr 实测：服务器类型选 **Emby**，地址填面板地址，URL Base 填 `emby-bridge`，账号密码填极影视媒体库账号 →
   - 登录成功、列出媒体库（电影库被正确识别为电影库）；
   - 同步完成，条目数接近极影视总量；
   - **搜索库里已有影片显示「可获得」，不是「请求」**（T3 判重改写的验证点）。
4. 关掉 `emby_bridge_enabled` 后 `/emby-bridge/*` 全部 404，面板其它功能不受影响。

---

## 7. 风险与边界

- **依赖极影视实现细节**：极空间若改版 Emby 层，桥可能失效。缓解：所有适配逻辑集中在一个 service 里，坏一处好改；总开关随时可关。
- **凭据暴露面**：桥拥有极影视账号能力。默认只放内网（§3.5），面板公网暴露时不要开 `allow_public`。
- **与现有 Jellyfin 的关系**：可并存。桥跑稳后再决定是否下线 Jellyfin，验证前不删。
- **`CollectionType` 补全靠库名启发式**：极影视库名不含「电影/电视剧」字眼时可能判错，属可接受边界（Seerr 里可手动改库类型）。
- **扫描速度由 Seerr 硬编码限速决定，不是桥的问题**（2026-11-17 实测）：`server/lib/scanners/baseScanner.ts` 里 `BUNDLE_SIZE = 20`、`UPDATE_RATE = 4 * 1000`，即**每 4 秒处理 20 条 = 5 条/秒**，Jellyfin 扫描器 `super('Jellyfin Sync')` 未覆盖、也没有环境变量可调。所以 2 万条的库全量扫描下限约 67 分钟，1.1 万条约 37 分钟。界面看到「每几秒刷新 20 个」正是这个节流在工作，说明单条处理 < 4 秒、链路健康；明显慢于 20 条/4 秒才是 TMDB 或 sqlite 在拖。桥侧只承担十几次分页请求（分钟级），不是瓶颈。
- **扫描期间不要重复点「执行扫描」**：会起新 session 把旧的一轮掐掉（`New session was started. Old session aborted.`），等于白跑。想省时间就少勾几个不点播的库，条目数直接按比例缩。
