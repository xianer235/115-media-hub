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


class ServarrCommandResponse(BaseModel):
    id: int = 1
    name: str = ""
    status: str = "completed"

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
    """校验 X-Api-Key / Query apikey / Bearer；未配置密钥时整个接口关闭（503），密钥不符 401。"""
    cfg = get_config()
    expected = str(cfg.get("servarr_api_key", "") or "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="点播接口未启用：请先在「参数配置 → 后台安全管理」生成 API Key",
        )
    provided = str(request.query_params.get("apikey", "") or request.query_params.get("api_key", "") or "").strip()
    if not provided:
        provided = str(request.headers.get("X-Api-Key", "") or "").strip()
    if not provided:
        auth_header = str(request.headers.get("Authorization", "") or "").strip()
        if auth_header.lower().startswith("bearer "):
            provided = auth_header[len("bearer "):].strip()
    # 按字节比较：verify 对非 ASCII 的 str 会抛 TypeError（密钥里含中文时变成 500）
    if not provided or not hmac.compare_digest(
        provided.encode("utf-8", "surrogateescape"),
        expected.encode("utf-8", "surrogateescape"),
    ):
        raise HTTPException(status_code=401, detail="API Key 无效")


servarr_auth = Depends(verify_servarr_api_key)


# ---------------------------------------------------------------- 内部工具

def _servarr_default_savepath(cfg: Dict[str, Any]) -> str:
    return normalize_relative_path(cfg.get("servarr_default_savepath", ""))


def _servarr_movie_savepath(cfg: Dict[str, Any]) -> str:
    return normalize_relative_path(cfg.get("servarr_movie_savepath", "") or cfg.get("servarr_default_savepath", ""))


def _servarr_tv_savepath(cfg: Dict[str, Any]) -> str:
    return normalize_relative_path(cfg.get("servarr_tv_savepath", "") or cfg.get("servarr_default_savepath", ""))


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
        subscription_cooldown_until.pop(name, None)
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


def _build_servarr_movie_task(
    tmdb_id: int,
    cfg: Dict[str, Any],
    fallback_title: str = "",
    fallback_year: str = "",
) -> Dict[str, Any]:
    binding = {}
    title = fallback_title
    year = fallback_year
    try:
        detail = get_tmdb_media_detail(tmdb_id, "movie", cfg)
        binding = build_tmdb_task_binding(detail, media_type="movie")
        title = str(binding.get("tmdb_title") or detail.get("title") or title).strip()
        year = str(binding.get("tmdb_year") or year).strip()
    except Exception:
        pass

    title = title or f"TMDB-{tmdb_id}"
    return normalize_subscription_task(
        {
            "name": _servarr_title_year(title, year),
            "provider": "115",
            "media_type": "movie",
            "title": title,
            "year": year,
            "season": 1,
            "savepath": _servarr_movie_savepath(cfg),
            "enabled": True,
            "organize_on_import": True,
            "cross_copy_mode": "fallback",
            "cross_copy_sources": ["quark"],
            "tmdb_id": tmdb_id,
            "tmdb_media_type": "movie",
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
    title = str(title or f"TMDB-{tmdb_id}").strip()
    year = str(year or "").strip()
    name = _servarr_title_year(title, year)
    if multi_season:
        name = f"{name} S{season:02d}"
    season_episode_map = binding.get("tmdb_season_episode_map") or {} if isinstance(binding, dict) else {}
    total_episodes = max(0, int(season_episode_map.get(str(season), 0) or 0))
    # 电视剧 savepath 强锁定为: 电视剧保存根目录 / 剧名(年份)
    tv_root = _servarr_tv_savepath(cfg)
    series_folder = _servarr_title_year(title, year)
    series_savepath = f"{tv_root}/{series_folder}" if tv_root else series_folder
    return normalize_subscription_task(
        {
            "name": name,
            "provider": "115",
            "media_type": "tv",
            "title": title,
            "year": year,
            "season": season,
            "total_episodes": total_episodes,
            "savepath": series_savepath,
            "enabled": True,
            "organize_on_import": True,
            "cross_copy_mode": "fallback",
            "cross_copy_sources": ["quark"],
            "tmdb_id": tmdb_id,
            "tmdb_media_type": "tv",
            **(binding if isinstance(binding, dict) else {}),
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
    """返回固定根路径，使 Seerr 前端无需用户手动选择保存目录。"""
    return [ServarrRootFolder(id=1, path="/")]


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
            rootFolderPath="/",
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


@router.post("/movie", response_model=Union[RadarrMovie, ServarrIdResponse])
async def servarr_add_movie(movie: RadarrMovie, _: None = servarr_auth) -> Union[RadarrMovie, ServarrIdResponse]:
    """Seerr 电影点播：建一个电影订阅任务并立即跑一次全量搜索。"""
    tmdb_id = max(0, int(movie.tmdbId or 0))
    if tmdb_id <= 0:
        raise HTTPException(status_code=400, detail="请求缺少 tmdbId")
    cfg = get_config()
    existing = _find_movie_task(cfg, tmdb_id)
    if not existing:
        config_error = validate_tmdb_runtime_config(cfg)
        if config_error:
            raise HTTPException(status_code=400, detail=f"无法创建点播任务：{config_error}")
        if not _servarr_movie_savepath(cfg):
            raise HTTPException(
                status_code=400,
                detail="未配置电影点播保存目录：请先在「参数配置 → 后台安全管理」填写",
            )
        task = _build_servarr_movie_task(tmdb_id, cfg, fallback_title=str(movie.title or ""), fallback_year=str(movie.year or ""))
        appended = _append_subscription_tasks([task])
        for item in appended:
            queue_subscription_job(str(item.get("name", "")), SERVARR_TRIGGER)
    
    title = movie.title or "Unknown"
    year = str(movie.year or "")
    slug = movie.titleSlug or str(tmdb_id)
    folder = movie.folderName or _servarr_title_year(title, year)
    return RadarrMovie(
        id=tmdb_id,
        title=title,
        year=year,
        isAvailable=True,
        monitored=True,
        hasFile=False,
        tmdbId=tmdb_id,
        titleSlug=slug,
        folderName=folder,
        profileId=SERVARR_QUALITY_PROFILE_ID,
        qualityProfileId=SERVARR_QUALITY_PROFILE_ID,
        rootFolderPath="/",
    )



@router.put("/movie", response_model=RadarrMovie)
async def servarr_update_movie(movie: RadarrMovie, _: None = servarr_auth) -> RadarrMovie:
    """Seerr 更新电影点播/监控状态。"""
    tmdb_id = max(0, int(movie.tmdbId or 0))
    if tmdb_id <= 0:
        raise HTTPException(status_code=400, detail="请求缺少 tmdbId")
    cfg = get_config()
    existing = _find_movie_task(cfg, tmdb_id)
    if not existing:
        await servarr_add_movie(movie, _)
    title = movie.title or "Unknown"
    year = str(movie.year or "")
    slug = movie.titleSlug or str(tmdb_id)
    folder = movie.folderName or _servarr_title_year(title, year)
    return RadarrMovie(
        id=tmdb_id,
        title=title,
        year=year,
        isAvailable=True,
        monitored=True,
        hasFile=False,
        tmdbId=tmdb_id,
        titleSlug=slug,
        folderName=folder,
        profileId=SERVARR_QUALITY_PROFILE_ID,
        qualityProfileId=SERVARR_QUALITY_PROFILE_ID,
        rootFolderPath="/",
    )


@router.delete("/movie/{mid}")
async def servarr_remove_movie(mid: int, _: None = servarr_auth) -> Dict[str, Any]:
    result = _drop_subscription_tasks(
        lambda task: str(task.get("media_type", "")) == "movie" and (
            _task_tmdb_id(task) == mid or str(mid) in str(task.get("name", ""))
        )
    )
    if not result["deleted"]:
        return {"ok": True, "deleted": False}
    return {"ok": True, "deleted": True}


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
            tmdb_id = tvdbId
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
    if not _servarr_tv_savepath(cfg):
        raise HTTPException(
            status_code=400,
            detail="未配置电视剧点播保存目录：请先在「参数配置 → 后台安全管理」填写",
        )
    binding = {}
    title = str(tv.title or "").strip()
    year = str(tv.year or "").strip()
    try:
        detail = get_tmdb_media_detail(tmdb_id, "tv", cfg)
        binding = build_tmdb_task_binding(detail, media_type="tv")
        title = str(binding.get("tmdb_title") or detail.get("title") or title).strip()
        year = str(binding.get("tmdb_year") or year).strip()
    except Exception:
        pass

    title = title or f"TMDB-{tmdb_id}" 
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
    cfg = get_config()
    target_tmdb_id = tid
    # 如果传进来的是 tvdbId，尝试转出 tmdb_id
    if target_tmdb_id > 0:
        mapped = find_tmdb_id_by_tvdb_id(target_tmdb_id, cfg)
        if mapped > 0:
            target_tmdb_id = mapped

    result = _drop_subscription_tasks(
        lambda task: str(task.get("media_type", "")) == "tv" and (
            _task_tmdb_id(task) == tid or _task_tmdb_id(task) == target_tmdb_id
        )
    )
    if not result["deleted"]:
        return {"ok": True, "deleted": False}
    return {"ok": True, "deleted": True}


@router.post("/command", response_model=ServarrCommandResponse)
async def servarr_command(body: Dict[str, Any], _: None = servarr_auth) -> ServarrCommandResponse:
    """响应 Seerr 发出的 MoviesSearch / SeriesSearch 命令。"""
    name = str(body.get("name", "") if isinstance(body, dict) else "")
    return ServarrCommandResponse(id=1, name=name, status="completed")

@router.get("/episode")
async def servarr_episodes(seriesId: Optional[int] = None, _: None = servarr_auth) -> List[Dict[str, Any]]:
    """响应 Sonarr 点播后查询剧集清单，返回空列表避免 404。"""
    return []
