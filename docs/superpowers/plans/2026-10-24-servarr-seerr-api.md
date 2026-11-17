# Seerr 点播对接（Radarr/Sonarr v3 兼容层）执行方案

> 对应 Issue #16：兼容 Radarr/Sonarr API（servarr 兼容层）以对接 Seerr/Jellyseerr/Overseerr 生态。
>
> 本文档面向执行者（代码能力一般的 AI 或工程师），每一步都写明了：改哪个文件、在哪个位置、改成什么、为什么。**不要自行发挥，不要改动本文未提到的行为。** 与项目约定（`docs/superpowers/conventions.md`）冲突时，以约定为准并停下来报告。
>
> 2026-10-24 已与用户确认的产品决策见 §2；用户没问到的实现细节由本方案按行业惯例直接定死，执行时不要再去问。

---

## 1. 目标与范围

### 1.1 做什么

新增一组挂在 `/api/v3` 前缀下的 REST 端点，让 Seerr / Jellyseerr / Overseerr 把 115 Media Hub 当成一台 Radarr（电影）/ Sonarr（剧集）服务器：

- 家人在 Seerr 点播电影 / 剧集 → 本项目自动创建对应的**订阅任务**（provider 固定 115）→ 立即触发一次全量搜索 → 复用现有「找资源 → 转存 → 入库 → STRM」全链路。
- Seerr 管理员删除点播请求 → 连带删除对应订阅任务。
- 鉴权用设置页生成的一把 API Key（`X-Api-Key` 请求头），与面板登录会话完全隔离。

### 1.2 不做什么（防止范围蔓延）

- **不做** `/api/v3/queue`、`/api/v3/health`、`/api/v3/command`、`/api/v3/download` 等端点。Overseerr/Jellyseerr 的点播主链路只依赖本方案列出的 16 个端点（与 MoviePilot 已验证的最小集一致）。
- **不引入** TVDB 直连、TVDB API Key。tvdbId → tmdbId 只用 TMDB 自带的 `/find` 接口。
- **不新增**任何第三方依赖（项目铁律：零新增依赖）。
- **不做** Seerr 用户体系对接（权限、限额、通知都由 Seerr 自己管）。
- **不改动**订阅任务的既有结构、落点约定（电影 `<savepath>/片名 年份`、剧集 `<savepath>/Season NN` 自动生效）。
- **不动**版本号 / CHANGELOG / README（留到发版提交，见 §8）。

---

## 2. 已确认的产品决策（2026-10-24，用户拍板）

| # | 决策 | 取值 |
| --- | --- | --- |
| D1 | 点播任务的保存目录 | 新增配置项 `servarr_default_savepath`（115 网盘相对路径，如 `Seerr点播`）；**留空时拒绝点播**并提示去配置 |
| D2 | 点播后何时找资源 | **立即触发一次全量搜索**（`queue_subscription_job(name, "servarr")`；trigger 非 `cron`，走全量搜索分支，见 §4.4） |
| D3 | Seerr 删请求时的行为 | **连带删除订阅任务**：电影删该 tmdbId 的电影任务；剧集删该 tmdbId 的全部季任务 |
| D4 | 目标网盘 | 固定 `115` |

方案内补充定死的决策（无需再问用户）：

| # | 决策 | 取值 |
| --- | --- | --- |
| D5 | API Key | 单一全局配置 `servarr_api_key`；空 = 接口关闭（所有端点 503）；校验用 `hmac.compare_digest`；请求头 `X-Api-Key`，兼容 `Authorization: Bearer <key>` |
| D6 | servarr 侧资源 id | 项目订阅任务没有数字 id，**用 tmdbId 充当**（`GET /movie/{id}`、`DELETE /movie/{id}` 都按 tmdbId 查） |
| D7 | 剧集多季命名 | 按「这部剧有几季」判定：TMDB 季集映射有多个正季（映射为空时看总季数 > 1）→ name = `片名 (年份) S%02d`；全剧只有 1 季 → `片名 (年份)`。每季一个任务。与既有任务重名 → 追加 ` tmdb{tmdbId}` 后缀。**2026-11-17 修订**：原规则是「一次点播多季才带季号」，但 Seerr 是一季一次请求（且我们的 lookup 恒返回 id，它总走 PUT），结果逐季点播的任务名全都不带季号、互相去重成 ` tmdb1234` / ` (2)`；改为按剧判定 |
| D8 | 剧集身份解析 | Seerr 的 POST /series 只带 `tvdbId`，必须经 TMDB `/find/{tvdbId}?external_source=tvdb_id` 转 tmdbId。**TMDB 未配置或解析失败 → 明确报错，不创建无 TMDB 绑定的降级任务** |
| D9 | `hasFile` / `isAvailable` | 恒 `false` / `true`（Seerr 的「已可观看」状态靠它自己的 Plex/Emby 集成判断，不经我们） |
| D10 | `PUT /series` | 与 `POST /series` 同一处理函数 |
| D11 | DELETE 无匹配 | 返回 404（body `{"detail": "..."}`） |

---

## 3. 端点契约总表（16 个）

全部要求 `X-Api-Key` 校验（§4.2）。路由前缀 `/api/v3`，在 `app/main.py` 挂载时**不套** `_auth_deps`。

| # | 方法与路径 | 请求 | 响应 | 行为 |
| --- | --- | --- | --- | --- |
| 1 | `GET /system/status` | — | `ServarrSystemStatus` | 静态伪装数据，`version` 取 `version.json` |
| 2 | `GET /qualityProfile` | — | `[ServarrQualityProfile]` | 静态：`[{id:1, name:"默认", ...}]` |
| 3 | `GET /rootfolder` | — | `[ServarrRootFolder]` | 静态：`path` = 配置的默认保存目录（未配置时 `/`） |
| 4 | `GET /tag` | — | `[ServarrTag]` | 静态：`[{id:1, label:"默认"}]` |
| 5 | `GET /languageprofile` | — | `[ServarrLanguageProfile]` | 静态：`[{id:1, name:"默认", ...}]` |
| 6 | `GET /movie` | query `tmdbId?` | `[RadarrMovie]` | 电影订阅任务列表；带 tmdbId 则只返回该部（Seerr 靠它判断重复点播） |
| 7 | `GET /movie/lookup` | query `term`（`tmdb:603` 或裸数字） | `[RadarrMovie]` | 调 TMDB 详情；查不到返回 `[RadarrMovie()]`（空对象，不报错） |
| 8 | `GET /movie/{mid}` | path `mid` = tmdbId | `RadarrMovie` | 按 tmdbId 找电影订阅；无 → 404 |
| 9 | `POST /movie` | body `RadarrMovie`（`tmdbId` 必需） | `ServarrIdResponse` | 建电影订阅任务 + 立即跑；已存在则幂等返回已有 id |
| 10 | `DELETE /movie/{mid}` | path `mid` = tmdbId | `{"ok": true}` | 删该 tmdbId 的全部电影任务；无 → 404 |
| 11 | `GET /series` | query `tvdbId?` | `[SonarrSeries]` | 剧集订阅任务按 tmdbId 聚合成剧；带 tvdbId 时先转 tmdbId 再过滤 |
| 12 | `GET /series/lookup` | query `term`（`tvdb:12345` / `tmdb:123` / 裸数字 / 标题） | `[SonarrSeries]` | tvdb→tmdb 或标题搜索 → TMDB 详情 → 季列表（monitored 反映已订阅季） |
| 13 | `GET /series/{tid}` | path `tid` = tmdbId | `SonarrSeries` | 聚合该 tmdbId 的全部季任务；无 → 404 |
| 14 | `POST /series` | body `SonarrSeries`（`tvdbId` 或 `tmdbId` 至少一个） | `ServarrIdResponse` | 按 monitored 季逐季建任务 + 逐个立即跑；全部已存在则幂等返回 |
| 15 | `PUT /series` | 同 14 | 同 14 | 与 14 同一函数 |
| 16 | `DELETE /series/{tid}` | path `tid` = tmdbId | `{"ok": true}` | 删该 tmdbId 的全部季任务；无 → 404 |

**路由声明顺序（FastAPI 按声明顺序匹配）**：`/movie/lookup` 必须声明在 `/movie/{mid}` **之前**，`/series/lookup` 必须声明在 `/series/{tid}` **之前**，否则 `lookup` 会被当成 `{mid}` 解析失败返回 422。

**Seerr 侧配置方法（写给用户的说明文案，放进设置页，见 §4.6）**：在 Seerr（Jellyseerr / Overseerr）的「设置 → Radarr / Sonarr」各加一条服务器：地址填 `http://面板地址:端口`，API Key 填设置页生成的同一个密钥；Radarr 管电影、Sonarr 管剧集。保存时 Seerr 会显示连接成功。

---

## 4. 改动清单（按依赖顺序执行）

### 4.1 `app/providers/tmdb.py` — 新增 tvdbId → tmdbId 查找（约 20 行）

**为什么**：Seerr 点播剧集只带 tvdbId，项目只用 TMDB，需要这座桥。TMDB 的 `/find` 接口正好做外部 id 映射，且复用现有 `tmdb_request_json`（自带缓存 / 代理 / 错误解析）。

**位置**：`build_tmdb_task_binding` 函数（约 546 行）之前，新增：

```python
def find_tmdb_id_by_tvdb_id(
    tvdb_id: int,
    cfg: Optional[Dict[str, Any]] = None,
    force_refresh: bool = False,
) -> int:
    """按 TVDB ID 查 TMDB 剧集 ID（Seerr 点播剧集只带 tvdbId）。

    走 TMDB /find 接口，命中返回 tmdb id，未命中返回 0（由调用方决定报错还是兜底）。
    """
    normalized_tvdb_id = max(0, int(tvdb_id or 0))
    if normalized_tvdb_id <= 0:
        return 0
    try:
        payload = tmdb_request_json(
            f"/find/{normalized_tvdb_id}",
            params={"external_source": "tvdb_id"},
            cfg=cfg,
            force_refresh=force_refresh,
        )
    except Exception:
        return 0
    results = payload.get("tv_results")
    if not isinstance(results, list):
        return 0
    for item in results:
        if not isinstance(item, dict):
            continue
        tmdb_id = max(0, parse_int(item.get("id", 0), 0))
        if tmdb_id > 0:
            return tmdb_id
    return 0
```

注意：异常吞掉返回 0 是**有意为之**——TMDB 临时故障时由调用方给 Seerr 一个明确错误，不让底层异常把栈泡到 HTTP 层。

### 4.2 `app/core.py` — 3 处小改动

**改动 C1：把新函数挂进 core 的共享命名空间**（项目路由统一 `from ..core import *` 拿 TMDB 函数）。

位置：约 7508 行 `from .providers.tmdb import (` 块内，在 `discover_tmdb_media,` 之后插入一行：

```python
    find_tmdb_id_by_tvdb_id,
```

**改动 C2：默认配置 + 保存排序**。

位置 a：`default_config()`（约 997 行起）里 `"webhook_secret": "",` 之后加两行：

```python
        "servarr_api_key": "",
        "servarr_default_savepath": "",
```

位置 b：`_SETTINGS_CONFIG_KEY_ORDER_AFTER_AUTH`（约 878 行起）里 `"webhook_secret",` 之后加两行：

```python
    "servarr_api_key",
    "servarr_default_savepath",
```

**改动 C3：CORS 允许 `X-Api-Key` 头**（让用户能从浏览器 console 直接测接口；Seerr 是服务端调用不受影响，但加上更完整）。

位置：约 339 行 `allow_headers=[ ... ]` 列表里，`"X-Requested-With",` 之后加一行：

```python
        "X-Api-Key",
```

### 4.3 `app/config_runtime.py` — 敏感键登记（1 行）

**为什么**：让 `/get_settings` 脱敏返回、保存时留空不覆盖（与 `webhook_secret` 同款机制）。

位置：`_STATIC_SENSITIVE_KEYS`（约 5-14 行）里 `"webhook_secret",` 之后加一行：

```python
    "servarr_api_key",
```

### 4.4 新建 `app/routes/servarr.py`（核心文件，约 520 行）

**为什么放这里**：与 `app/routes/subscription.py`（订阅任务）、`app/routes/monitor.py`（另一套免会话鉴权）同层的 HTTP 接口层；`test_modules_doc.py` 会校验 `app/**` 每个文件都在 `docs/superpowers/modules.md` 登记，别忘 §4.9。

**挂载方式**（§4.5）：`APIRouter(prefix="/api/v3")`，不带会话鉴权。

以下为完整代码，**照抄即可**（已按 Python 3.9 + pydantic v2 校验过语法；注意不能用 `str | int` 联合语法）：

```python
"""Radarr / Sonarr v3 兼容接口（servarr 层）。

把 Seerr / Jellyseerr / Overseerr 的点播请求转换成本项目的订阅任务：
电影点播 → 一个电影订阅任务；剧集点播 → 按季拆成多个剧集订阅任务。
鉴权用设置页生成的 API Key（X-Api-Key 请求头），不走面板登录会话。

只做「伪装成 Radarr/Sonarr」必需的最小端点集（与 MoviePilot 同名适配层对齐），
不实现 queue / command / health 等端点。端点契约见 docs/superpowers/plans/2026-10-24-servarr-seerr-api.md。
"""

import hmac
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..core import *  # noqa: F401,F403
from ..services.subscription import queue_subscription_job
from ..versioning import load_local_version

router = APIRouter(prefix="/api/v3", tags=["servarr"])

SERVARR_QUALITY_PROFILE_ID = 1
SERVARR_LANGUAGE_PROFILE_ID = 1
SERVARR_TAG_ID = 1
SERVARR_DEFAULT_PROFILE_NAME = "默认"
SERVARR_TRIGGER = "servarr"  # 非 cron：run_subscription_task 走全量搜索分支


# ---------------------------------------------------------------- 数据模型
# 字段与 Radarr/Sonarr v3 API 对齐；Seerr 只读它认识的字段，多余字段会被忽略。

class ServarrVersion(BaseModel):
    major: int = 0
    minor: int = 0
    build: int = 0
    revision: int = 0
    majorRevision: int = 0
    minorRevision: int = 0


class ServarrSystemStatus(BaseModel):
    appName: str
    instanceName: str
    version: str
    buildTime: str = ""
    isDebug: bool = False
    isProduction: bool = True
    isAdmin: bool = True
    isUserInteractive: bool = True
    startupPath: str = "/app"
    appData: str = "/app/config"
    osName: str = "linux"
    osVersion: str = ""
    isNetCore: bool = True
    isLinux: bool = True
    isOsx: bool = False
    isWindows: bool = False
    isDocker: bool = True
    mode: str = "console"
    branch: str = "main"
    databaseType: str = "sqLite"
    databaseVersion: ServarrVersion = Field(default_factory=ServarrVersion)
    authentication: str = "none"
    migrationVersion: int = 0
    urlBase: str = ""
    runtimeVersion: ServarrVersion = Field(default_factory=ServarrVersion)
    runtimeName: str = ""
    startTime: str = ""
    packageVersion: str = ""
    packageAuthor: str = "xianer235"
    packageUpdateMechanism: str = "builtIn"
    packageUpdateMechanismMessage: str = ""


class ServarrQuality(BaseModel):
    id: int = 0
    name: str = SERVARR_DEFAULT_PROFILE_NAME
    source: str = "0"
    resolution: int = 0


class ServarrQualityProfileItem(BaseModel):
    id: int = 0
    name: str = SERVARR_DEFAULT_PROFILE_NAME
    quality: ServarrQuality = Field(default_factory=ServarrQuality)
    items: List[str] = Field(default_factory=list)
    allowed: bool = True


class ServarrFormatItem(BaseModel):
    id: int = 0
    format: int = 0
    name: str = SERVARR_DEFAULT_PROFILE_NAME
    score: int = 0


class ServarrQualityProfile(BaseModel):
    id: int = SERVARR_QUALITY_PROFILE_ID
    name: str = SERVARR_DEFAULT_PROFILE_NAME
    upgradeAllowed: bool = True
    cutoff: int = 0
    items: List[ServarrQualityProfileItem] = Field(default_factory=list)
    minFormatScore: int = 0
    cutoffFormatScore: int = 0
    formatItems: List[ServarrFormatItem] = Field(default_factory=list)


class ServarrRootFolder(BaseModel):
    id: int = 1
    path: str = "/"
    accessible: bool = True
    freeSpace: int = 0
    unmappedFolders: List[str] = Field(default_factory=list)


class ServarrTag(BaseModel):
    id: int = SERVARR_TAG_ID
    label: str = SERVARR_DEFAULT_PROFILE_NAME


class ServarrLanguage(BaseModel):
    id: int = 1
    name: str = SERVARR_DEFAULT_PROFILE_NAME


class ServarrLanguageProfileItem(BaseModel):
    language: ServarrLanguage = Field(default_factory=ServarrLanguage)
    allowed: bool = True


class ServarrLanguageProfile(BaseModel):
    id: int = SERVARR_LANGUAGE_PROFILE_ID
    name: str = SERVARR_DEFAULT_PROFILE_NAME
    upgradeAllowed: bool = True
    cutoff: ServarrLanguage = Field(default_factory=ServarrLanguage)
    languages: List[ServarrLanguageProfileItem] = Field(default_factory=list)


class ServarrIdResponse(BaseModel):
    id: int = 0


class RadarrMovie(BaseModel):
    id: Optional[int] = None
    title: Optional[str] = None
    year: Optional[Union[int, str]] = None
    isAvailable: bool = True
    monitored: bool = True
    hasFile: bool = False
    tmdbId: Optional[int] = None
    imdbId: Optional[str] = None
    titleSlug: Optional[str] = None
    folderName: Optional[str] = None
    profileId: int = SERVARR_QUALITY_PROFILE_ID
    qualityProfileId: int = SERVARR_QUALITY_PROFILE_ID
    rootFolderPath: Optional[str] = None
    minimumAvailability: str = "released"
    added: Optional[str] = None


class SonarrSeason(BaseModel):
    seasonNumber: Optional[int] = None
    monitored: bool = False
    statistics: Optional[Dict[str, Any]] = None


class SonarrSeries(BaseModel):
    id: Optional[int] = None
    title: Optional[str] = None
    sortTitle: Optional[str] = None
    seasonCount: int = 0
    status: Optional[str] = None
    overview: Optional[str] = None
    network: Optional[str] = None
    airTime: Optional[str] = None
    remotePoster: Optional[str] = None
    seasons: List[SonarrSeason] = Field(default_factory=list)
    year: Optional[Union[int, str]] = None
    path: Optional[str] = None
    profileId: int = SERVARR_QUALITY_PROFILE_ID
    languageProfileId: int = SERVARR_LANGUAGE_PROFILE_ID
    seasonFolder: bool = True
    monitored: bool = True
    useSceneNumbering: bool = False
    runtime: Optional[int] = None
    tmdbId: Optional[int] = None
    imdbId: Optional[str] = None
    tvdbId: Optional[int] = None
    tvRageId: Optional[int] = None
    tvMazeId: Optional[int] = None
    firstAired: Optional[str] = None
    seriesType: str = "standard"
    cleanTitle: Optional[str] = None
    titleSlug: Optional[str] = None
    certification: Optional[str] = None
    genres: List[str] = Field(default_factory=list)
    tags: List[int] = Field(default_factory=list)
    added: Optional[str] = None
    ratings: Optional[Dict[str, Any]] = None
    qualityProfileId: int = SERVARR_QUALITY_PROFILE_ID
    statistics: Dict[str, Any] = Field(default_factory=dict)
    isAvailable: bool = True
    hasFile: bool = False


# ---------------------------------------------------------------- 鉴权

async def verify_servarr_api_key(request: Request) -> None:
    """校验 X-Api-Key；未配置密钥时整个接口关闭（503），密钥不符 401。"""
    cfg = get_config()
    expected = str(cfg.get("servarr_api_key", "") or "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="点播接口未启用：请先在「参数配置 → 后台安全管理」生成 API Key",
        )
    provided = str(request.headers.get("X-Api-Key", "") or "").strip()
    if not provided:
        auth_header = str(request.headers.get("Authorization", "") or "").strip()
        if auth_header.lower().startswith("bearer "):
            provided = auth_header[len("bearer "):].strip()
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="API Key 无效")


servarr_auth = Depends(verify_servarr_api_key)


# ---------------------------------------------------------------- 内部工具

def _servarr_default_savepath(cfg: Dict[str, Any]) -> str:
    return normalize_relative_path(cfg.get("servarr_default_savepath", ""))


def _subscription_tasks(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = cfg.get("subscription_tasks", [])
    if not isinstance(raw, list):
        return []
    return [normalize_subscription_task(task or {}) for task in raw]


def _task_tmdb_id(task: Dict[str, Any]) -> int:
    return max(0, int(task.get("tmdb_id", 0) or 0))


def _find_movie_task(cfg: Dict[str, Any], tmdb_id: int) -> Optional[Dict[str, Any]]:
    for task in _subscription_tasks(cfg):
        if str(task.get("media_type", "")) == "movie" and _task_tmdb_id(task) == tmdb_id:
            return task
    return None


def _series_season_tasks(cfg: Dict[str, Any], tmdb_id: int) -> List[Dict[str, Any]]:
    return [
        task
        for task in _subscription_tasks(cfg)
        if str(task.get("media_type", "")) == "tv" and _task_tmdb_id(task) == tmdb_id
    ]


def _servarr_title_year(title: str, year: str) -> str:
    title = str(title or "").strip()
    year = str(year or "").strip()
    return f"{title} ({year})" if year else title


def _append_subscription_tasks(new_tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把新订阅任务追加进配置并落库；与既有任务重名时加 tmdb 后缀保证可区分。

    只做追加，不走 /subscription/save 的整表替换（那条路由会顺带清队列/状态，追加场景不需要）。
    """
    cfg = get_config()
    tasks = _subscription_tasks(cfg)
    names = {str(task.get("name", "") or "") for task in tasks}
    appended: List[Dict[str, Any]] = []
    for task in new_tasks:
        name = str(task.get("name", "") or "")
        if name in names:
            name = f"{name} tmdb{_task_tmdb_id(task)}"
            suffix = 2
            while name in names:
                name = f"{name} ({suffix})"
                suffix += 1
            task = dict(task)
            task["name"] = name
        names.add(name)
        tasks.append(task)
        appended.append(task)
    updated = dict(cfg)
    updated["subscription_tasks"] = tasks
    save_config(updated)
    schedule_ui_state_push(0)
    return appended


def _drop_subscription_tasks(match) -> Dict[str, Any]:
    """删除订阅任务（match(task) 为 True 即删），返回 {"deleted": [...], "left": [...]}。

    复刻 /subscription/delete 的收尾：清队列 / 运行时状态 / 修剪任务状态 + 推 UI。
    """
    cfg = get_config()
    tasks = _subscription_tasks(cfg)
    left = [task for task in tasks if not match(task)]
    deleted = [task for task in tasks if match(task)]
    if not deleted:
        return {"deleted": [], "left": tasks}
    updated = dict(cfg)
    updated["subscription_tasks"] = left
    save_config(updated)
    deleted_names = {str(task.get("name", "")) for task in deleted}
    with subscription_queue_lock:
        subscription_queue[:] = [
            item for item in subscription_queue if item.get("task_name") not in deleted_names
        ]
        subscription_status["queued"] = [item["task_name"] for item in subscription_queue]
    for name in deleted_names:
        subscription_last_run.pop(name, None)
        subscription_next_run.pop(name, None)
    prune_subscription_state_for_missing_tasks(
        [str(task.get("name", "")) for task in left]
    )
    schedule_ui_state_push(0)
    return {"deleted": deleted, "left": left}


def _parse_tmdb_term(term: str) -> int:
    """lookup 的 term 解析：`tmdb:603` / 裸数字 → tmdb id；其他 → 0。"""
    token = str(term or "").strip()
    if token.lower().startswith("tmdb:"):
        token = token[len("tmdb:"):].strip()
    if not token.isdigit():
        return 0
    return max(0, int(token))


def _parse_tvdb_term(term: str) -> int:
    """lookup 的 term 解析：`tvdb:12345` / 裸数字 → tvdb id；其他 → 0。"""
    token = str(term or "").strip()
    if token.lower().startswith("tvdb:"):
        token = token[len("tvdb:"):].strip()
    if not token.isdigit():
        return 0
    return max(0, int(token))


def _movie_task_to_radarr(task: Dict[str, Any]) -> RadarrMovie:
    tmdb_id = _task_tmdb_id(task)
    return RadarrMovie(
        id=tmdb_id,
        title=str(task.get("title", "") or "").strip() or str(task.get("name", "") or ""),
        year=str(task.get("year", "") or ""),
        isAvailable=True,
        monitored=bool(task.get("enabled", True)),
        hasFile=False,
        tmdbId=tmdb_id,
        titleSlug=str(task.get("tmdb_original_title", "") or ""),
        folderName=str(task.get("name", "") or ""),
        profileId=SERVARR_QUALITY_PROFILE_ID,
        qualityProfileId=SERVARR_QUALITY_PROFILE_ID,
        added=None,
    )


def _series_tasks_to_sonarr(tasks: List[Dict[str, Any]], tvdb_id: int = 0) -> Optional[SonarrSeries]:
    if not tasks:
        return None
    first = tasks[0]
    tmdb_id = _task_tmdb_id(first)
    seasons = sorted(
        {
            max(1, int(task.get("season", 1) or 1))
            for task in tasks
        }
    )
    # 注意：订阅任务不持久化海报地址（normalize_subscription_task 会丢弃 tmdb_poster_url），
    # 这里不读海报；lookup 端点用的是实时 TMDB binding，才有海报。
    return SonarrSeries(
        id=tmdb_id,
        title=str(first.get("title", "") or "").strip() or str(first.get("name", "") or ""),
        sortTitle=str(first.get("name", "") or ""),
        seasonCount=len(seasons),
        seasons=[SonarrSeason(seasonNumber=season, monitored=True) for season in seasons],
        remotePoster=None,
        year=str(first.get("year", "") or ""),
        tmdbId=tmdb_id,
        tvdbId=tvdb_id or None,
        profileId=SERVARR_QUALITY_PROFILE_ID,
        languageProfileId=SERVARR_LANGUAGE_PROFILE_ID,
        qualityProfileId=SERVARR_QUALITY_PROFILE_ID,
        seasonFolder=True,
        monitored=True,
        isAvailable=True,
        hasFile=False,
    )


def _build_servarr_movie_task(tmdb_id: int, cfg: Dict[str, Any]) -> Dict[str, Any]:
    try:
        detail = get_tmdb_media_detail(tmdb_id, "movie", cfg)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"读取 TMDB 电影信息失败：{exc}") from exc
    binding = build_tmdb_task_binding(detail, media_type="movie")
    title = str(binding.get("tmdb_title") or detail.get("title") or "").strip()
    year = str(binding.get("tmdb_year") or "").strip()
    if not title:
        raise HTTPException(status_code=500, detail="TMDB 电影信息解析失败：标题为空")
    return normalize_subscription_task(
        {
            "name": _servarr_title_year(title, year),
            "provider": "115",
            "media_type": "movie",
            "title": title,
            "year": year,
            "season": 1,
            "savepath": _servarr_default_savepath(cfg),
            "enabled": True,
            "organize_on_import": True,
            **binding,
        }
    )


def _build_servarr_series_task(
    tmdb_id: int,
    season: int,
    title: str,
    year: str,
    binding: Dict[str, Any],
    cfg: Dict[str, Any],
    multi_season: bool,
) -> Dict[str, Any]:
    name = _servarr_title_year(title, year)
    if multi_season:
        name = f"{name} S{season:02d}"
    season_episode_map = binding.get("tmdb_season_episode_map") or {}
    total_episodes = max(0, int(season_episode_map.get(str(season), 0) or 0))
    return normalize_subscription_task(
        {
            "name": name,
            "provider": "115",
            "media_type": "tv",
            "title": title,
            "year": year,
            "season": season,
            "total_episodes": total_episodes,
            "savepath": _servarr_default_savepath(cfg),
            "enabled": True,
            "organize_on_import": True,
            **binding,
        }
    )


# ---------------------------------------------------------------- 静态端点（Seerr 连接测试用）

@router.get("/system/status", response_model=ServarrSystemStatus)
async def servarr_system_status(_: None = servarr_auth) -> ServarrSystemStatus:
    version = str(load_local_version().get("version", "dev") or "dev")
    return ServarrSystemStatus(
        appName="115 Media Hub",
        instanceName="115-media-hub",
        version=version,
    )


@router.get("/qualityProfile", response_model=List[ServarrQualityProfile])
async def servarr_quality_profiles(_: None = servarr_auth) -> List[ServarrQualityProfile]:
    return [
        ServarrQualityProfile(
            items=[
                ServarrQualityProfileItem(
                    quality=ServarrQuality(name=SERVARR_DEFAULT_PROFILE_NAME)
                )
            ],
            formatItems=[ServarrFormatItem()],
        )
    ]


@router.get("/rootfolder", response_model=List[ServarrRootFolder])
async def servarr_root_folders(_: None = servarr_auth) -> List[ServarrRootFolder]:
    savepath = _servarr_default_savepath(get_config())
    return [ServarrRootFolder(path=savepath or "/")]


@router.get("/tag", response_model=List[ServarrTag])
async def servarr_tags(_: None = servarr_auth) -> List[ServarrTag]:
    return [ServarrTag()]


@router.get("/languageprofile", response_model=List[ServarrLanguageProfile])
async def servarr_language_profiles(_: None = servarr_auth) -> List[ServarrLanguageProfile]:
    return [ServarrLanguageProfile()]


# ---------------------------------------------------------------- 电影端点

@router.get("/movie/lookup", response_model=List[RadarrMovie])
async def servarr_movie_lookup(term: str, _: None = servarr_auth) -> List[RadarrMovie]:
    """按 tmdb:ID 查电影；存在与否都不报错（Seerr 的连接测试与高级选项会调）。"""
    tmdb_id = _parse_tmdb_term(term)
    if tmdb_id <= 0:
        return []
    cfg = get_config()
    config_error = validate_tmdb_runtime_config(cfg)
    if config_error:
        return [RadarrMovie()]
    try:
        detail = get_tmdb_media_detail(tmdb_id, "movie", cfg)
    except Exception:
        return [RadarrMovie()]
    binding = build_tmdb_task_binding(detail, media_type="movie")
    title = str(binding.get("tmdb_title") or detail.get("title") or "").strip()
    year = str(binding.get("tmdb_year") or "").strip()
    existing = _find_movie_task(cfg, tmdb_id)
    return [
        RadarrMovie(
            id=tmdb_id,
            title=title,
            year=year,
            isAvailable=True,
            monitored=bool(existing),
            hasFile=False,
            tmdbId=tmdb_id,
            titleSlug=str(binding.get("tmdb_original_title") or ""),
            folderName=_servarr_title_year(title, year),
            profileId=SERVARR_QUALITY_PROFILE_ID,
            qualityProfileId=SERVARR_QUALITY_PROFILE_ID,
            rootFolderPath=_servarr_default_savepath(cfg) or None,
        )
    ]


@router.get("/movie", response_model=List[RadarrMovie])
async def servarr_movies(tmdbId: Optional[int] = None, _: None = servarr_auth) -> List[RadarrMovie]:
    """电影订阅列表；Seerr 用 tmdbId 参数判断某部电影是否已点播（重复点播防护）。"""
    cfg = get_config()
    tasks = [
        task
        for task in _subscription_tasks(cfg)
        if str(task.get("media_type", "")) == "movie"
    ]
    if tmdbId:
        tasks = [task for task in tasks if _task_tmdb_id(task) == tmdbId]
    return [_movie_task_to_radarr(task) for task in tasks]


@router.get("/movie/{mid}", response_model=RadarrMovie)
async def servarr_movie_detail(mid: int, _: None = servarr_auth) -> RadarrMovie:
    cfg = get_config()
    task = _find_movie_task(cfg, mid)
    if not task:
        raise HTTPException(status_code=404, detail="未找到该电影订阅")
    return _movie_task_to_radarr(task)


@router.post("/movie", response_model=ServarrIdResponse)
async def servarr_add_movie(movie: RadarrMovie, _: None = servarr_auth) -> ServarrIdResponse:
    """Seerr 电影点播：建一个电影订阅任务并立即跑一次全量搜索。"""
    tmdb_id = max(0, int(movie.tmdbId or 0))
    if tmdb_id <= 0:
        raise HTTPException(status_code=400, detail="请求缺少 tmdbId")
    cfg = get_config()
    if _find_movie_task(cfg, tmdb_id):
        # 幂等：已点播过直接返回，不重复建任务（Seerr 会显示「已请求」）。
        return ServarrIdResponse(id=tmdb_id)
    config_error = validate_tmdb_runtime_config(cfg)
    if config_error:
        raise HTTPException(status_code=400, detail=f"无法创建点播任务：{config_error}")
    if not _servarr_default_savepath(cfg):
        raise HTTPException(
            status_code=400,
            detail="未配置点播默认保存目录：请先在「参数配置 → 后台安全管理」填写",
        )
    task = _build_servarr_movie_task(tmdb_id, cfg)
    appended = _append_subscription_tasks([task])
    for item in appended:
        queue_subscription_job(str(item.get("name", "")), SERVARR_TRIGGER)
    return ServarrIdResponse(id=tmdb_id)


@router.delete("/movie/{mid}")
async def servarr_remove_movie(mid: int, _: None = servarr_auth) -> Dict[str, Any]:
    result = _drop_subscription_tasks(
        lambda task: str(task.get("media_type", "")) == "movie" and _task_tmdb_id(task) == mid
    )
    if not result["deleted"]:
        raise HTTPException(status_code=404, detail="未找到该电影订阅")
    return {"ok": True}


# ---------------------------------------------------------------- 剧集端点

@router.get("/series/lookup", response_model=List[SonarrSeries])
async def servarr_series_lookup(term: str, _: None = servarr_auth) -> List[SonarrSeries]:
    """按 tvdb:ID / tmdb:ID / 标题查剧集；季列表的 monitored 反映本项目的已订阅季。"""
    cfg = get_config()
    tvdb_id = _parse_tvdb_term(term)
    tmdb_id = _parse_tmdb_term(term)
    if tmdb_id <= 0 and tvdb_id <= 0:
        # 标题兜底：走 TMDB 标题搜索取第一个剧集结果（Overseerr 实际只发 tvdb:，这条是尽力而为）。
        title = str(term or "").strip()
        if not title:
            return [SonarrSeries()]
        config_error = validate_tmdb_runtime_config(cfg)
        if config_error:
            return [SonarrSeries()]
        try:
            searched = search_tmdb_media(title, "tv", "", 1, cfg)
        except Exception:
            return [SonarrSeries()]
        items = searched.get("items") if isinstance(searched, dict) else []
        if not isinstance(items, list) or not items:
            return [SonarrSeries()]
        first = items[0] if isinstance(items[0], dict) else {}
        tmdb_id = max(0, int(first.get("id", 0) or 0))
        if tmdb_id <= 0:
            return [SonarrSeries()]
    if tmdb_id <= 0 and tvdb_id > 0:
        config_error = validate_tmdb_runtime_config(cfg)
        if config_error:
            return [SonarrSeries()]
        tmdb_id = find_tmdb_id_by_tvdb_id(tvdb_id, cfg)
        if tmdb_id <= 0:
            return [SonarrSeries()]
    config_error = validate_tmdb_runtime_config(cfg)
    if config_error:
        return [SonarrSeries()]
    try:
        detail = get_tmdb_media_detail(tmdb_id, "tv", cfg)
    except Exception:
        return [SonarrSeries()]
    binding = build_tmdb_task_binding(detail, media_type="tv")
    season_episode_map = binding.get("tmdb_season_episode_map") or {}
    season_numbers = sorted(
        {int(key) for key in season_episode_map.keys() if int(key) > 0}
    )
    if not season_numbers:
        season_numbers = [1]
    existing_seasons = {
        max(1, int(task.get("season", 1) or 1))
        for task in _series_season_tasks(cfg, tmdb_id)
    }
    title = str(binding.get("tmdb_title") or detail.get("title") or "").strip()
    year = str(binding.get("tmdb_year") or "").strip()
    return [
        SonarrSeries(
            id=tmdb_id,
            title=title,
            sortTitle=title,
            seasonCount=len(season_numbers),
            seasons=[
                SonarrSeason(seasonNumber=season, monitored=season in existing_seasons)
                for season in season_numbers
            ],
            remotePoster=str(binding.get("tmdb_poster_url") or "") or None,
            year=year,
            tmdbId=tmdb_id,
            tvdbId=tvdb_id or None,
            profileId=SERVARR_QUALITY_PROFILE_ID,
            languageProfileId=SERVARR_LANGUAGE_PROFILE_ID,
            qualityProfileId=SERVARR_QUALITY_PROFILE_ID,
            seasonFolder=True,
            monitored=bool(existing_seasons),
            isAvailable=True,
            hasFile=False,
        )
    ]


@router.get("/series", response_model=List[SonarrSeries])
async def servarr_series(tvdbId: Optional[int] = None, _: None = servarr_auth) -> List[SonarrSeries]:
    """剧集订阅列表（按 tmdbId 聚合多季任务）；Seerr 用 tvdbId 参数判断是否已点播。"""
    cfg = get_config()
    tmdb_id = 0
    if tvdbId:
        config_error = validate_tmdb_runtime_config(cfg)
        if not config_error:
            tmdb_id = find_tmdb_id_by_tvdb_id(tvdbId, cfg)
        if tmdb_id <= 0:
            return []
    tasks = _subscription_tasks(cfg)
    if tmdb_id > 0:
        tasks = [task for task in tasks if _task_tmdb_id(task) == tmdb_id]
    else:
        tasks = [task for task in tasks if str(task.get("media_type", "")) == "tv"]
    grouped: Dict[int, List[Dict[str, Any]]] = {}
    for task in tasks:
        if str(task.get("media_type", "")) != "tv":
            continue
        key = _task_tmdb_id(task)
        if key <= 0:
            continue
        grouped.setdefault(key, []).append(task)
    result = []
    for tmdb_key in sorted(grouped.keys()):
        series = _series_tasks_to_sonarr(grouped[tmdb_key], tvdb_id=tvdbId or 0)
        if series:
            result.append(series)
    return result


@router.get("/series/{tid}", response_model=SonarrSeries)
async def servarr_series_detail(tid: int, _: None = servarr_auth) -> SonarrSeries:
    cfg = get_config()
    series = _series_tasks_to_sonarr(_series_season_tasks(cfg, tid))
    if not series:
        raise HTTPException(status_code=404, detail="未找到该剧集订阅")
    return series


@router.post("/series", response_model=ServarrIdResponse)
async def servarr_add_series(tv: SonarrSeries, _: None = servarr_auth) -> ServarrIdResponse:
    """Seerr 剧集点播：解析 tmdbId → 按 monitored 季逐季建订阅任务 → 逐个立即跑。"""
    tvdb_id = max(0, int(tv.tvdbId or 0))
    tmdb_id = max(0, int(tv.tmdbId or 0))
    if tmdb_id <= 0 and tvdb_id <= 0:
        raise HTTPException(status_code=400, detail="请求缺少 tmdbId 或 tvdbId")
    cfg = get_config()
    if tmdb_id <= 0:
        config_error = validate_tmdb_runtime_config(cfg)
        if config_error:
            raise HTTPException(status_code=400, detail=f"无法解析剧集信息：{config_error}")
        tmdb_id = find_tmdb_id_by_tvdb_id(tvdb_id, cfg)
        if tmdb_id <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"未找到 TVDB {tvdb_id} 对应的 TMDB 条目，无法创建点播任务",
            )
    config_error = validate_tmdb_runtime_config(cfg)
    if config_error:
        raise HTTPException(status_code=400, detail=f"无法创建点播任务：{config_error}")
    if not _servarr_default_savepath(cfg):
        raise HTTPException(
            status_code=400,
            detail="未配置点播默认保存目录：请先在「参数配置 → 后台安全管理」填写",
        )
    try:
        detail = get_tmdb_media_detail(tmdb_id, "tv", cfg)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"读取 TMDB 剧集信息失败：{exc}") from exc
    binding = build_tmdb_task_binding(detail, media_type="tv")
    title = str(tv.title or binding.get("tmdb_title") or detail.get("title") or "").strip()
    year = str(tv.year or binding.get("tmdb_year") or "").strip()
    if not title:
        raise HTTPException(status_code=500, detail="TMDB 剧集信息解析失败：标题为空")
    season_episode_map = binding.get("tmdb_season_episode_map") or {}
    wanted: List[int] = []
    for season in tv.seasons or []:
        number = max(0, int(season.seasonNumber or 0))
        if number > 0 and bool(season.monitored):
            wanted.append(number)
    wanted = list(dict.fromkeys(wanted))  # 去重保序
    if not wanted:
        # 请求体没带季（或全未监控）时订阅 TMDB 识别的全部季，识别不到兜底第 1 季。
        wanted = sorted({int(key) for key in season_episode_map.keys() if int(key) > 0}) or [1]
    existing_seasons = {
        max(1, int(task.get("season", 1) or 1))
        for task in _series_season_tasks(cfg, tmdb_id)
    }
    left_seasons = [season for season in wanted if season not in existing_seasons]
    if not left_seasons:
        return ServarrIdResponse(id=tmdb_id)
    multi_season = len(left_seasons) > 1
    new_tasks = [
        _build_servarr_series_task(tmdb_id, season, title, year, binding, cfg, multi_season)
        for season in left_seasons
    ]
    appended = _append_subscription_tasks(new_tasks)
    for item in appended:
        queue_subscription_job(str(item.get("name", "")), SERVARR_TRIGGER)
    return ServarrIdResponse(id=tmdb_id)


@router.put("/series", response_model=ServarrIdResponse)
async def servarr_update_series(tv: SonarrSeries, _: None = servarr_auth) -> ServarrIdResponse:
    """Seerr 更新剧集点播：与新增同逻辑（幂等）。"""
    return await servarr_add_series(tv=tv, _=None)


@router.delete("/series/{tid}")
async def servarr_remove_series(tid: int, _: None = servarr_auth) -> Dict[str, Any]:
    result = _drop_subscription_tasks(
        lambda task: str(task.get("media_type", "")) == "tv" and _task_tmdb_id(task) == tid
    )
    if not result["deleted"]:
        raise HTTPException(status_code=404, detail="未找到该剧集订阅")
    return {"ok": True}
```

**代码自检要点（写完逐条过）**：

- 所有名字都来自 `from ..core import *`（`get_config` / `save_config` / `normalize_subscription_task` / `normalize_relative_path` / `validate_tmdb_runtime_config` / `get_tmdb_media_detail` / `build_tmdb_task_binding` / `search_tmdb_media` / `find_tmdb_id_by_tvdb_id`（§4.1 + §4.2 C1 挂进来）/ `schedule_ui_state_push` / `subscription_queue` / `subscription_queue_lock` / `subscription_status` / `subscription_last_run` / `subscription_next_run` / `prune_subscription_state_for_missing_tasks`）或显式 import（`queue_subscription_job` / `load_local_version` / fastapi / pydantic）。
- `servarr_update_series` 里调用 `servarr_add_series(tv=tv, _=None)`：`_` 参数名带下划线前缀是 FastAPI 依赖注入位，直接传 `None` 即可（依赖已在路由装饰器上生效）。
- `/movie/lookup`、`/series/lookup` 声明在 `/movie/{mid}`、`/series/{tid}` **之前**。
- 不能用 `str | int`（Python 3.9），已统一 `Optional[Union[int, str]]`。
- `queue_subscription_job(name, "servarr")`：trigger 不是 `cron`，`run_subscription_task` 走全量搜索分支（`app/services/subscription.py:1146` `incremental_search_enabled = trigger_mode == "cron"`），这正是点播要的行为。

### 4.5 `app/main.py` — 挂载路由（2 行）

位置：约第 14 行 `from .routes.tmdb import router as tmdb_router` 之后加一行 import；约第 31 行 `app.include_router(cross_copy_router, dependencies=_auth_deps)` 之后加一行挂载：

```python
from .routes.servarr import router as servarr_router
```

```python
app.include_router(servarr_router)  # 自带 /api/v3 前缀与 X-Api-Key 鉴权，不走登录会话
```

**不要**给它加 `dependencies=_auth_deps`——Seerr 没有登录会话。

### 4.6 `templates/partials/pages/settings.html` — 设置页 UI

位置：`#settings-body-security` 区块内，webhook 密钥 `<label>`（约 789-799 行）之后、说明文字块（约 800 行）之前，插入：

```html
                        <label class="block">
                            <span class="text-xs text-slate-500 inline-flex items-center gap-2">
                                点播接口 API Key（Seerr / Jellyseerr / Overseerr 用）
                                <button type="button" class="info-dot" onclick="showHelp('用途：让 Seerr 等点播门户把 115 Media Hub 当成 Radarr / Sonarr 服务器。家人在 Seerr 点播后，这里会自动创建对应的订阅任务并立即开始找资源。留空则关闭点播接口。')">i</button>
                            </span>
                            <input id="servarr_api_key" class="w-full bg-slate-900 border-slate-700 rounded-xl p-3 text-sm mt-1" placeholder="建议 32 位随机字符串">
                            <div class="mt-2 flex items-center gap-2 flex-wrap">
                                <button type="button" onclick="generateServarrApiKey()" class="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold">随机生成密钥</button>
                                <span class="text-[11px] text-slate-500">生成后请点击“保存全部配置”。</span>
                            </div>
                        </label>
                        <label class="block">
                            <span class="text-xs text-slate-500">点播默认保存目录（115 网盘相对路径）</span>
                            <input id="servarr_default_savepath" class="w-full bg-slate-900 border-slate-700 rounded-xl p-3 text-sm mt-1" placeholder="例如：Seerr点播">
                            <div class="mt-1 text-[11px] text-slate-500">Seerr 点播创建的任务统一存到这里：电影自动建「片名 年份」子目录，剧集建「Season NN」子目录。留空则无法接受点播。</div>
                        </label>
                        <div class="text-xs text-slate-500 leading-6">
                            对接方法：在 Seerr（Jellyseerr / Overseerr）的「设置 → Radarr / Sonarr」里各添加一条服务器，地址填 <code>http://面板地址</code>，API Key 填上面生成的同一个密钥；Radarr 对应电影点播，Sonarr 对应剧集点播，保存后 Seerr 会显示连接成功。
                            <br>家人在 Seerr 提交点播后，本面板「影视订阅」页会出现对应任务并自动搜索资源，找到后自动转存、入库、生成 STRM，与手动订阅完全同链路；在 Seerr 删除点播请求会同时删掉这里的订阅任务。
                        </div>
```

注意：类名全部复用 webhook 密钥区块现成的（`bg-slate-900` / `border-slate-700` / `rounded-xl` / `info-dot` 等），**不要发明新类名**（Tailwind 生成 CSS 里没有的类不生效）。`input` 的 id 必须与配置键同名（`servarr_api_key` / `servarr_default_savepath`），加载时 `boot.js` 按 id 自动回填、保存时 `standardIds` 按 id 收集（§4.7）。

### 4.7 `static/js/modules/tabs/settings.js` — 3 处小改动

**改动 J1：保存收集列表加两个字段**。位置：`standardIds` 数组（约 403-441 行）里 `'webhook_secret'` 之后（即数组最后一项之后）加：

```javascript
        'servarr_api_key',
        'servarr_default_savepath'
```

（保持数组格式：`'webhook_secret',` 末尾加逗号，再跟这两行。）

**改动 J2：新增密钥生成函数**。位置：`generateWebhookSecret` 函数（约 1051-1060 行）之后新增：

```javascript
export function generateServarrApiKey({ showToast } = {}) {
    const input = document.getElementById('servarr_api_key');
    if (!input) return;
    input.value = randomAlphaNumericSecret(32);
    input.focus();
    input.select();
    if (typeof showToast === 'function') {
        showToast('已生成随机密钥，请记得点击“保存全部配置”', { tone: 'success', duration: 3000, placement: 'top-center' });
    }
}
```

**改动 J3：分区摘要显示点播接口状态**。位置：`buildSettingsSectionSummary` 的 `case 'security'`（约 182-186 行），把 return 改成：

```javascript
        case 'security': {
            const account = settingsValue('username') ? '账号已填' : '账号未填';
            const secretConfigured = !!settingsValue('webhook_secret') || !!latestSettingsSensitiveMeta.webhook_secret;
            const servarrConfigured = !!settingsValue('servarr_api_key') || !!latestSettingsSensitiveMeta.servarr_api_key;
            return `${account} · ${secretConfigured ? '签名密钥已配置' : '签名密钥未配置'}${servarrConfigured ? ' · 点播接口已开启' : ''}`;
        }
```

### 4.8 `static/js/index.js` — 2 处小改动

**改动 K1：敏感字段掩码名单**。位置：`getSensitiveSettingFields()`（约 310-329 行）的 fields 数组里 `'webhook_secret',` 之后加一行：

```javascript
                'servarr_api_key',
```

**改动 K2：全局按钮处理函数**。位置：`generateWebhookSecret` 包装函数（约 838-847 行）之后新增（index.js 顶层作用域即全局，inline onclick 可直接调）：

```javascript
        function generateServarrApiKey() {
            const settingsModule = tabRuntimeState.tabModuleCache.settings;
            if (settingsModule?.generateServarrApiKey) {
                settingsModule.generateServarrApiKey({ showToast });
                return;
            }
            void loadSettingsTabModule().then((mod) => {
                mod?.generateServarrApiKey?.({ showToast });
            });
        }
```

### 4.9 `docs/superpowers/modules.md` — 登记新模块（2 处，漏了测试会挂）

1. 「一、功能模块」里「影视订阅（subscription）」条目之后，新增一节：

```markdown
### Seerr 点播对接（servarr）
- **用途**：让 Seerr / Jellyseerr / Overseerr 把本面板当成 Radarr / Sonarr 服务器，家人的点播请求自动转成订阅任务（电影一部一任务、剧集按季拆多任务，provider 固定 115），立即触发一次全量搜索，之后与手动订阅完全同链路。
- **入口**：Seerr 侧「设置 → Radarr / Sonarr」添加服务器（地址 = 面板地址，API Key = 设置页生成）；本侧入口是 `/api/v3/*` 端点。
- **会做**：16 个 Radarr/Sonarr v3 端点（system/status、qualityProfile、rootfolder、tag、languageprofile、movie 的 lookup/list/detail/add/delete、series 的 lookup/list/detail/add/update/delete）；X-Api-Key 鉴权；tvdbId 经 TMDB /find 转 tmdbId；删除点播连带删订阅任务。
- **不会做**：不实现 queue / command / health 端点；不接 TVDB 直连；不管 Seerr 用户权限；不代理播放；不新建第二套任务存储。
- **相关代码**：`app/routes/servarr.py`、`app/providers/tmdb.py`（find_tmdb_id_by_tvdb_id）；设置页「后台安全管理」的「点播接口 API Key / 点播默认保存目录」
- **细节**：`docs/superpowers/plans/2026-10-24-servarr-seerr-api.md`
```

2. 「二、代码索引」的路由表（约 100 行起）末尾加一行：

```markdown
| `app/routes/servarr.py` | Radarr/Sonarr v3 兼容层（Seerr 点播对接）：静态系统信息、电影/剧集查询与点播增删，X-Api-Key 鉴权，转订阅任务 |
```

### 4.10 `docs/superpowers/handoff.md` — 追加一行交接记录

在 `## 交接记录` 下追加（不要堆细节）：

```
- 2026-10-24 | main | 0.15.8 | 新增 Seerr 点播对接（Radarr/Sonarr v3 兼容层 /api/v3，16 端点，X-Api-Key 鉴权，点播转订阅任务并立即跑，删除连带删任务） | 家庭影院场景缺统一点播门户，复用订阅链路不造第二套 | tests/test_servarr_api.py 全绿 + 本机 check.sh 挑模块通过 | 真机联调 Seerr（用户侧）；发版提交
```

追加后运行 `.venv/bin/python scripts/rotate_handoff.py --dry-run` 看是否需要轮转（需要时才去掉 `--dry-run` 实跑）。

---

## 5. 测试：新建 `tests/test_servarr_api.py`

**测试基建**（照 `tests/test_settings_storage_ui.py` 的成熟模式）：

- `from fastapi.testclient import TestClient`；`from app.main import app`；`from app.routes import servarr as servarr_routes`。
- servarr 路由**不套** `require_auth`，不需要 `app.dependency_overrides`。
- 用 `mock.patch.object(servarr_routes, "get_config", ...)` / `"save_config"` 做内存配置；`save_config` 的 mock 要**真正写回内存字典**（封装一个 fake store），否则追加/删除逻辑测不到。
- `mock.patch.object(servarr_routes, "queue_subscription_job")` 记录调用；`mock.patch.object(servarr_routes, "schedule_ui_state_push")` 避免副作用；`mock.patch.object(servarr_routes, "get_tmdb_media_detail", return_value=FAKE_DETAIL)` / `"find_tmdb_id_by_tvdb_id", return_value=603` / `"validate_tmdb_runtime_config", return_value=None` 按用例开关。
- TMDB fake 详情至少包含：`{"id": 603, "title": "黑客帝国", "original_title": "The Matrix", "year": "1999", "media_type": "movie", "poster_url": "", "aliases": [], "total_episodes": 0, "total_seasons": 0, "season_episode_map": {}, "episode_mode": "seasonal"}`（电影）与剧集版（`season_episode_map: {"1": 22, "2": 22}`、`total_seasons: 2`、`media_type: "tv"`）。
- 临时目录用 `tempfile.mkdtemp(prefix="wb_servarr_")`（根由 `run_tests.py` 管），tearDown 里 `shutil.rmtree`。

**用例清单（约 30 条，每条独立 setUp）**：

鉴权：
1. 未配 `servarr_api_key` → 任一 GET 返回 503，detail 含「未启用」
2. 密钥错误 → 401
3. 密钥正确 → 200；`Authorization: Bearer <key>` 也认
4. 缺 Key 头 → 401

静态端点：
5. `GET /system/status` 200，`appName` / `version` 非空
6. `GET /qualityProfile` 返回 1 条，`id=1`、`name="默认"`、`items` 非空
7. `GET /rootfolder` 未配保存目录时 `path="/"`；配了返回配置值
8. `GET /tag` 返回 `[{id:1,label:"默认"}]`
9. `GET /languageprofile` 返回 1 条

电影点播：
10. `POST /movie`（tmdbId=603）成功：save_config 被调用 1 次；落库任务 `name="黑客帝国 (1999)"`、`provider="115"`、`media_type="movie"`、`savepath=配置值`、`tmdb_id=603`、`tmdb_title="黑客帝国"`、`tmdb_year="1999"`、`enabled=True`、`organize_on_import=True`
11. 同上：`queue_subscription_job` 被调用 1 次，参数 `("黑客帝国 (1999)", "servarr")`
12. 已存在同 tmdbId 电影任务时再 POST → save_config **不**被调用，返回 `{"id": 603}`
13. body 缺 tmdbId → 400
14. 未配默认保存目录 → 400，detail 含「未配置点播默认保存目录」
15. `validate_tmdb_runtime_config` 返回错误 → 400，detail 含该错误
16. `get_tmdb_media_detail` 抛异常 → 500

电影查询：
17. `GET /movie/lookup?term=tmdb:603` → 1 条，`tmdbId=603`、`monitored` 与订阅状态一致
18. `GET /movie/lookup?term=abc`（非数字）→ `[]`
19. `GET /movie?tmdbId=603` 有订阅 → 1 条；无订阅 → `[]`；无参 → 返回全部电影任务
20. `GET /movie/603` 有订阅 → 200；无 → 404

剧集点播：
21. `POST /series` 只带 tvdbId=83245 → `find_tmdb_id_by_tvdb_id` 被调用并补出 tmdbId，建 1 个任务（seasons=[{seasonNumber:1,monitored:true}]），name = `绝命毒师 (2008) S01`（按剧判定：测试用的 TMDB 详情有 2 季）
22. `POST /series` seasons=[1,2,3] 全 monitored → 建 3 个任务，name 分别为 `片名 (年份) S01/S02/S03`，`total_episodes` 分别取 season_episode_map 的 22/22/0
23. 第 2 季已存在时再 POST seasons=[2,3] → 只建第 3 季
24. 全部季已存在 → save_config 不调用，返回 `{"id": tmdbId}`
25. seasons 里 seasonNumber=0（特别季）或 monitored=false → 跳过
26. seasons 为空 → 用 TMDB 季兜底（本例建第 1、2 季两个任务）
27. 缺 tmdbId 又缺 tvdbId → 400
28. 未配默认保存目录 → 400
29. 与既有任务重名但（tmdbId/季）不同 → name 带 ` tmdb{tmdbId}` 后缀

剧集查询：
30. `GET /series/lookup?term=tvdb:83245` → 1 条 SonarrSeries，seasons 覆盖 1、2 季，monitored 与订阅一致，`tvdbId=83245`
31. `GET /series?tvdbId=83245` 有订阅 → 1 条聚合（seasonCount=2）；解析不到 tmdbId → `[]`
32. `GET /series/{tid}` 有订阅 → 200 且 seasons 正确；无 → 404

删除：
33. `DELETE /movie/603` 有订阅 → save_config 删除 + `prune_subscription_state_for_missing_tasks` 被调用；无 → 404
34. `DELETE /series/{tid}` 删除该 tmdbId 全部季任务；无 → 404
35. `PUT /series` 与 POST 同行为（复用同一条 fake 配置断言）

**禁止**：不要 mock `normalize_subscription_task`（要真实归一化，这才测得到字段映射）；不要碰真实 `settings.json`。

---

## 6. 执行顺序与验证

按 §4.1 → §4.2 → §4.3 → §4.4 → §4.5 → §4.6 → §4.7 → §4.8 → §4.9 → §4.10 → §5 顺序做（前面是后面的依赖）。

每步验证（适用哪个跑哪个，全绿才进下一步）：

```bash
# 1. Python 编译（改完 app/ 后）
PYTHONPYCACHEPREFIX=/tmp/115-media-hub-pycache .venv/bin/python -m compileall app main.py

# 2. JS 语法（改完 static/js 后）
node --check static/js/index.js
node --check static/js/modules/tabs/settings.js

# 3. 新测试
scripts/check.sh tests.test_servarr_api

# 4. 受影响模块回归（modules_doc 会校验新文件已登记）
scripts/check.sh tests.test_modules_doc tests.test_subscription_ui_frontend tests.test_settings_storage_ui
```

收尾：

```bash
python scripts/run_tests.py --clean-temp   # 清掉本轮临时目录（如有残渣）
```

**本机 `unittest` 不可直接 discover，必须走 `scripts/run_tests.py` / `scripts/check.sh`**（直接 discover 会刷假失败）。全量 `scripts/check.sh --all` 留给发版前，本次不要求。

**明确不做真机联调**：Seerr 侧的服务器添加、点播、删除属于用户侧操作，方案交付后由用户自行验证；执行者只保证单测与接口契约。Seerr 联调步骤（写给用户，放进交付说明，不要写进代码）：

1. 设置页「后台安全管理」→ 生成点播 API Key → 填「点播默认保存目录」（如 `Seerr点播`）→ 保存全部配置。
2. Seerr → Settings → Radarr：Server `http://<面板IP>:18080`，API Key 填刚生成的；Save 显示绿勾即通。
3. Seerr → Settings → Sonarr：同样再来一条（同一个 Key）。
4. 随便点播一部电影 / 一剧，看面板「影视订阅」页是否出现任务并开始搜索；在 Seerr 删掉该请求，看任务是否被删掉。

---

## 7. 已知限制（交付时如实告知用户）

- **必须配置 TMDB**（参数配置 → TMDB 元数据增强，启用 + API Key）。未配时电影点播直接报错提示，剧集点播因无法 tvdb→tmdb 也会报错。这是有意设计：降级建无绑定的任务匹配质量差，反而制造噪音。
- Seerr 的「已可观看」状态由 Seerr 自己的 Plex/Emby/Jellyfin 集成判断，不经过本面板；点播、追更、入库、STRM 不受影响。
- 删除点播 = 删除订阅任务（含其追更进度状态），这是 D3 确认的行为；只删任务记录，不删网盘上已入库的文件。
- `/api/v3` 端点只按 API Key 鉴权，没有限流；Key 即权限，不要外泄。面板本身该有的登录会话保护不变。

---

## 8. 版本与发布（本次不做）

- **不动** `version.json` / `CHANGELOG.md` / `README.md` / `state.md` 的版本相关内容。
- 功能提交信息建议：`feat: 新增 Seerr 点播对接（Radarr/Sonarr v3 兼容层）`，正文列 16 端点 + 两个配置键 + 测试证据。
- 发版（用户另行指示时）：版本号 patch 递增 + 发版四件套 + `gh release create`，流程按 `docs/superpowers/conventions.md`「许可与发版」与项目记忆执行。
