from .common import parse_int
from ..core import *  # noqa: F401,F403

def get_tmdb_runtime_config(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = cfg or get_config()
    enabled = bool(cfg.get("tmdb_enabled", False))
    api_key = str(cfg.get("tmdb_api_key", "")).strip()
    language = str(cfg.get("tmdb_language", "zh-CN") or "zh-CN").strip()
    if not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", language):
        language = "zh-CN"
    region = str(cfg.get("tmdb_region", "CN") or "CN").strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", region):
        region = "CN"
    try:
        cache_ttl_hours = int(cfg.get("tmdb_cache_ttl_hours", 24) or 24)
    except (TypeError, ValueError):
        cache_ttl_hours = 24
    cache_ttl_hours = max(1, min(24 * 30, cache_ttl_hours))
    return {
        "enabled": enabled,
        "api_key": api_key,
        "language": language,
        "region": region,
        "cache_ttl_hours": cache_ttl_hours,
        "cache_ttl_seconds": cache_ttl_hours * 3600,
    }

def build_tmdb_cache_key(path: str, params: Dict[str, Any]) -> str:
    normalized_params = {
        str(key): str(value)
        for key, value in sorted((params or {}).items(), key=lambda kv: str(kv[0]))
        if str(key).strip()
    }
    return safe_json_dumps(
        {
            "path": str(path or "").strip(),
            "params": normalized_params,
        }
    )

def prune_tmdb_cache(max_entries: int = 900) -> None:
    if len(tmdb_cache_entries) <= max_entries:
        return
    keys = sorted(
        tmdb_cache_entries.keys(),
        key=lambda cache_key: float((tmdb_cache_entries.get(cache_key) or {}).get("saved_at", 0) or 0),
    )
    overflow = max(0, len(keys) - max_entries)
    for key in keys[:overflow]:
        tmdb_cache_entries.pop(key, None)


def prune_tmdb_runtime_cache(cfg: Optional[Dict[str, Any]] = None, max_entries: int = 900) -> Dict[str, int]:
    runtime = get_tmdb_runtime_config(cfg or get_config())
    ttl_seconds = max(3600, int(runtime.get("cache_ttl_seconds", 24 * 3600) or 24 * 3600))
    now = time.time()
    removed_expired = 0
    for key, entry in list(tmdb_cache_entries.items()):
        saved_at = float((entry or {}).get("saved_at", 0) or 0)
        if saved_at <= 0 or now - saved_at > ttl_seconds:
            tmdb_cache_entries.pop(key, None)
            removed_expired += 1
    before_max_prune = len(tmdb_cache_entries)
    prune_tmdb_cache(max_entries=max_entries)
    return {
        "expired": removed_expired,
        "overflow": max(0, before_max_prune - len(tmdb_cache_entries)),
    }


def parse_tmdb_http_error(exc: Exception) -> str:
    status_code = 0
    if isinstance(exc, urllib.error.HTTPError):
        status_code = int(exc.code or 0)
    base = f"TMDB 请求失败（HTTP {status_code}）" if status_code > 0 else "TMDB 请求失败"
    try:
        body = exc.read().decode("utf-8", errors="ignore") if isinstance(exc, urllib.error.HTTPError) else ""
    except Exception:
        body = ""
    payload = safe_json_loads(body, {})
    if isinstance(payload, dict):
        message = str(payload.get("status_message", "") or payload.get("message", "") or "").strip()
        if message:
            base = f"{base}：{message}"
    if status_code == 401:
        return "TMDB API Key 无效或未授权"
    if status_code == 404:
        return "TMDB 资源不存在"
    if status_code == 429:
        return "TMDB 请求过于频繁，请稍后重试"
    return base

def tmdb_request_json(
    path: str,
    params: Optional[Dict[str, Any]] = None,
    cfg: Optional[Dict[str, Any]] = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    active_cfg = normalize_config(cfg or get_config())
    runtime = get_tmdb_runtime_config(active_cfg)
    if not runtime["enabled"]:
        raise RuntimeError("TMDB 增强未启用，请先在参数配置中开启")
    if not runtime["api_key"]:
        raise RuntimeError("TMDB API Key 未填写")
    proxy_url = build_tg_proxy_url(active_cfg)

    normalized_path = "/" + str(path or "").strip().lstrip("/")
    raw_params = dict(params or {})
    request_params: Dict[str, Any] = {}
    for key, value in raw_params.items():
        token_key = str(key or "").strip()
        if not token_key:
            continue
        token_value = str(value or "").strip()
        if token_value == "":
            continue
        request_params[token_key] = token_value
    request_params.setdefault("language", runtime["language"])
    if runtime["region"] and "region" not in request_params:
        request_params["region"] = runtime["region"]

    cache_key = build_tmdb_cache_key(normalized_path, request_params)
    now = time.time()
    cache_entry = tmdb_cache_entries.get(cache_key)
    ttl_seconds = max(3600, int(runtime.get("cache_ttl_seconds", 24 * 3600) or 24 * 3600))
    if cache_entry and not force_refresh:
        cached_at = float(cache_entry.get("saved_at", 0) or 0)
        if now - cached_at <= ttl_seconds:
            cached_data = cache_entry.get("data")
            if isinstance(cached_data, dict):
                return clone_jsonable(cached_data)
        else:
            tmdb_cache_entries.pop(cache_key, None)

    query_params = {**request_params, "api_key": runtime["api_key"]}
    query = urllib.parse.urlencode(query_params, doseq=True)
    request_url = f"{TMDB_API_BASE_URL}{normalized_path}"
    if query:
        request_url = f"{request_url}?{query}"
    try:
        payload = http_request_json(
            request_url,
            timeout=TMDB_REQUEST_TIMEOUT_SECONDS,
            extra_headers={"Accept": "application/json"},
            proxy_url=proxy_url,
        )
    except urllib.error.HTTPError as exc:
        raise RuntimeError(parse_tmdb_http_error(exc)) from exc
    except urllib.error.URLError as exc:
        reason = format_network_error(exc)
        if proxy_url:
            raise RuntimeError(f"TMDB 网络异常（代理 {proxy_url}）：{reason}") from exc
        raise RuntimeError(f"TMDB 网络异常：{reason}") from exc
    except json.JSONDecodeError as exc:
        preview = str(exc).split("响应不是 JSON（前 200 字符）:")[-1].strip() if "响应不是 JSON" in str(exc) else ""
        if preview:
            raise RuntimeError(f"TMDB 返回内容不是有效 JSON（可能代理或网络异常）：{preview[:100]}") from exc
        raise RuntimeError("TMDB 返回内容不是有效 JSON（可能代理或网络异常）") from exc
    except Exception as exc:
        raise RuntimeError(f"TMDB 请求失败：{exc}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("TMDB 返回格式异常")
    if payload.get("success") is False:
        message = str(payload.get("status_message", "") or payload.get("message", "") or "").strip()
        raise RuntimeError(f"TMDB 返回错误：{message or '未知错误'}")

    tmdb_cache_entries[cache_key] = {"saved_at": now, "data": clone_jsonable(payload)}
    prune_tmdb_cache()
    return payload

def build_tmdb_image_url(path: Any, size: str = "w342") -> str:
    raw_path = str(path or "").strip()
    if not raw_path:
        return ""
    normalized_path = raw_path if raw_path.startswith("/") else f"/{raw_path}"
    normalized_size = str(size or "w342").strip() or "w342"
    if not re.fullmatch(r"(?:w\d+|original)", normalized_size):
        normalized_size = "w342"
    return f"{TMDB_IMAGE_BASE_URL}/{normalized_size}{normalized_path}"

def normalize_tmdb_result_item(item: Dict[str, Any], media_type_hint: str = "") -> Dict[str, Any]:
    payload = item if isinstance(item, dict) else {}
    media_type = normalize_tmdb_media_type(payload.get("media_type", ""), fallback=media_type_hint)
    if not media_type:
        if payload.get("title") is not None or payload.get("release_date") is not None:
            media_type = "movie"
        elif payload.get("name") is not None or payload.get("first_air_date") is not None:
            media_type = "tv"
        else:
            media_type = normalize_tmdb_media_type(media_type_hint, fallback="movie")

    tmdb_id = max(0, parse_int(payload.get("id", 0), 0))
    if tmdb_id <= 0:
        return {}
    if media_type == "movie":
        title = str(payload.get("title", "") or "").strip()
        original_title = str(payload.get("original_title", "") or "").strip()
        date_field = str(payload.get("release_date", "") or "").strip()
    else:
        title = str(payload.get("name", "") or "").strip()
        original_title = str(payload.get("original_name", "") or "").strip()
        date_field = str(payload.get("first_air_date", "") or "").strip()
    if not title:
        return {}

    year = extract_year_from_date(date_field)
    try:
        vote_average = float(payload.get("vote_average", 0) or 0)
    except (TypeError, ValueError):
        vote_average = 0.0
    try:
        popularity = float(payload.get("popularity", 0) or 0)
    except (TypeError, ValueError):
        popularity = 0.0

    return {
        "id": tmdb_id,
        "media_type": media_type,
        "title": title,
        "original_title": original_title,
        "year": year,
        "overview": str(payload.get("overview", "") or "").strip(),
        "poster_url": build_tmdb_image_url(payload.get("poster_path", ""), "w342"),
        "backdrop_url": build_tmdb_image_url(payload.get("backdrop_path", ""), "w780"),
        "vote_average": round(vote_average, 1),
        "popularity": popularity,
    }

def search_tmdb_media(
    query: str,
    media_type: str = "",
    year: str = "",
    page: int = 1,
    cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    keyword = re.sub(r"\s+", " ", str(query or "").strip())
    if not keyword:
        return {"items": [], "page": 1, "total_pages": 1}

    normalized_year = normalize_tmdb_year(year)
    normalized_media_type = normalize_tmdb_media_type(media_type, fallback="")
    normalized_page = max(1, min(1000, int(page or 1)))
    endpoint = f"/search/{normalized_media_type}" if normalized_media_type else "/search/multi"
    params: Dict[str, Any] = {"query": keyword, "include_adult": "false", "page": str(normalized_page)}
    if normalized_year:
        if normalized_media_type == "movie":
            params["year"] = normalized_year
        elif normalized_media_type == "tv":
            params["first_air_date_year"] = normalized_year
    payload = tmdb_request_json(endpoint, params=params, cfg=cfg)
    raw_results = payload.get("results", []) if isinstance(payload.get("results"), list) else []
    total_pages = max(1, min(1000, int(payload.get("total_pages", 1) or 1)))

    items: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for raw_item in raw_results:
        item = normalize_tmdb_result_item(raw_item if isinstance(raw_item, dict) else {}, normalized_media_type)
        if not item:
            continue
        media = normalize_tmdb_media_type(item.get("media_type", ""), fallback="")
        if media not in ("movie", "tv"):
            continue
        if normalized_media_type and media != normalized_media_type:
            continue
        key = f"{media}:{int(item.get('id', 0) or 0)}"
        if key in seen:
            continue
        seen.add(key)
        items.append(item)

    def sort_key(item: Dict[str, Any]) -> Tuple[int, float, float, int]:
        year_matched = 1 if (normalized_year and str(item.get("year", "")) == normalized_year) else 0
        return (
            year_matched,
            float(item.get("popularity", 0) or 0),
            float(item.get("vote_average", 0) or 0),
            int(item.get("id", 0) or 0),
        )

    items.sort(key=sort_key, reverse=True)
    return {"items": items[: TMDB_SEARCH_LIMIT], "page": normalized_page, "total_pages": total_pages}


def get_tmdb_trending(
    media_type: str = "all",
    time_window: str = "week",
    page: int = 1,
    cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    normalized_media_type = normalize_tmdb_media_type(media_type, fallback="all")
    if normalized_media_type not in ("all", "movie", "tv"):
        normalized_media_type = "all"
    normalized_window = str(time_window or "week").strip().lower()
    if normalized_window not in ("day", "week"):
        normalized_window = "week"
    normalized_page = max(1, min(1000, int(page or 1)))

    payload = tmdb_request_json(
        f"/trending/{normalized_media_type}/{normalized_window}",
        params={"page": str(normalized_page)},
        cfg=cfg,
    )
    raw_results = payload.get("results", []) if isinstance(payload.get("results"), list) else []
    total_pages = max(1, min(1000, int(payload.get("total_pages", 1) or 1)))

    items: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for raw_item in raw_results:
        item = normalize_tmdb_result_item(raw_item if isinstance(raw_item, dict) else {}, "")
        if not item:
            continue
        media = normalize_tmdb_media_type(item.get("media_type", ""), fallback="")
        if media not in ("movie", "tv"):
            continue
        key = f"{media}:{int(item.get('id', 0) or 0)}"
        if key in seen:
            continue
        seen.add(key)
        items.append(item)

    return {"items": items[: TMDB_SEARCH_LIMIT], "page": normalized_page, "total_pages": total_pages}


def get_tmdb_popular(
    media_type: str = "movie",
    page: int = 1,
    cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    normalized_media_type = normalize_tmdb_media_type(media_type, fallback="movie")
    if normalized_media_type not in ("movie", "tv"):
        normalized_media_type = "movie"
    normalized_page = max(1, min(500, int(page or 1)))

    payload = tmdb_request_json(
        f"/{normalized_media_type}/popular",
        params={"page": str(normalized_page)},
        cfg=cfg,
    )
    raw_results = payload.get("results", []) if isinstance(payload.get("results"), list) else []
    total_pages = max(1, min(500, int(payload.get("total_pages", 1) or 1)))

    items: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for raw_item in raw_results:
        item = normalize_tmdb_result_item(raw_item if isinstance(raw_item, dict) else {}, normalized_media_type)
        if not item:
            continue
        media = normalize_tmdb_media_type(item.get("media_type", ""), fallback=normalized_media_type)
        if media not in ("movie", "tv"):
            continue
        key = f"{media}:{int(item.get('id', 0) or 0)}"
        if key in seen:
            continue
        seen.add(key)
        items.append(item)

    return {"items": items[: TMDB_SEARCH_LIMIT], "page": normalized_page, "total_pages": total_pages}


def get_tmdb_genre_list(
    media_type: str = "movie",
    cfg: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    normalized_media_type = normalize_tmdb_media_type(media_type, fallback="movie")
    if normalized_media_type not in ("movie", "tv"):
        normalized_media_type = "movie"

    payload = tmdb_request_json(
        f"/genre/{normalized_media_type}/list",
        params={},
        cfg=cfg,
    )
    raw_genres = payload.get("genres", []) if isinstance(payload.get("genres"), list) else []
    genres: List[Dict[str, Any]] = []
    for raw_genre in raw_genres:
        if not isinstance(raw_genre, dict):
            continue
        genre_id = max(0, parse_int(raw_genre.get("id", 0), 0))
        genre_name = str(raw_genre.get("name", "") or "").strip()
        if genre_id > 0 and genre_name:
            genres.append({"id": genre_id, "name": genre_name})
    return genres


def discover_tmdb_media(
    media_type: str = "movie",
    genres: str = "",
    sort_by: str = "popularity.desc",
    vote_average_gte: float = 0,
    primary_release_year: str = "",
    page: int = 1,
    cfg: Optional[Dict[str, Any]] = None,
    with_original_language: str = "",
    primary_release_date_gte: str = "",
    primary_release_date_lte: str = "",
    vote_count_gte: int = 0,
    with_runtime_gte: int = 0,
    with_runtime_lte: int = 0,
) -> Dict[str, Any]:
    normalized_media_type = normalize_tmdb_media_type(media_type, fallback="movie")
    if normalized_media_type not in ("movie", "tv"):
        normalized_media_type = "movie"
    normalized_page = max(1, min(500, int(page or 1)))

    valid_sort_options = ("popularity.desc", "popularity.asc", "vote_average.desc", "vote_average.asc",
                          "primary_release_date.desc", "primary_release_date.asc",
                          "first_air_date.desc", "first_air_date.asc")
    normalized_sort = sort_by if sort_by in valid_sort_options else "popularity.desc"

    params: Dict[str, Any] = {
        "page": str(normalized_page),
        "sort_by": normalized_sort,
        "include_adult": "false",
    }

    if genres:
        genre_ids = ",".join(g.strip() for g in str(genres).split(",") if g.strip().isdigit())
        if genre_ids:
            params["with_genres"] = genre_ids

    if vote_average_gte and float(vote_average_gte) > 0:
        params["vote_average.gte"] = str(min(10, max(0, float(vote_average_gte))))

    # 日期范围优先于单一年份
    has_date_range = bool(primary_release_date_gte or primary_release_date_lte)
    if has_date_range:
        date_gte = normalize_tmdb_year(primary_release_date_gte)
        date_lte = normalize_tmdb_year(primary_release_date_lte)
        if normalized_media_type == "movie":
            if date_gte:
                params["primary_release_date.gte"] = f"{date_gte}-01-01"
            if date_lte:
                params["primary_release_date.lte"] = f"{date_lte}-12-31"
        else:
            if date_gte:
                params["first_air_date.gte"] = f"{date_gte}-01-01"
            if date_lte:
                params["first_air_date.lte"] = f"{date_lte}-12-31"
    else:
        year_str = normalize_tmdb_year(primary_release_year)
        if year_str:
            if normalized_media_type == "movie":
                params["primary_release_year"] = year_str
            else:
                params["first_air_date_year"] = year_str

    if with_original_language and with_original_language.strip():
        params["with_original_language"] = with_original_language.strip()

    if vote_count_gte and int(vote_count_gte) > 0:
        params["vote_count.gte"] = str(int(vote_count_gte))

    if with_runtime_gte and int(with_runtime_gte) > 0:
        params["with_runtime.gte"] = str(int(with_runtime_gte))
    if with_runtime_lte and int(with_runtime_lte) > 0:
        params["with_runtime.lte"] = str(int(with_runtime_lte))

    payload = tmdb_request_json(
        f"/discover/{normalized_media_type}",
        params=params,
        cfg=cfg,
    )
    raw_results = payload.get("results", []) if isinstance(payload.get("results"), list) else []
    total_pages = max(1, min(500, int(payload.get("total_pages", 1) or 1)))

    items: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for raw_item in raw_results:
        item = normalize_tmdb_result_item(raw_item if isinstance(raw_item, dict) else {}, normalized_media_type)
        if not item:
            continue
        media = normalize_tmdb_media_type(item.get("media_type", ""), fallback=normalized_media_type)
        if media not in ("movie", "tv"):
            continue
        key = f"{media}:{int(item.get('id', 0) or 0)}"
        if key in seen:
            continue
        seen.add(key)
        items.append(item)

    return {"items": items[: TMDB_SEARCH_LIMIT], "page": normalized_page, "total_pages": total_pages}


def build_tmdb_aliases(detail: Dict[str, Any], media_type: str) -> List[str]:
    aliases: List[str] = []
    alternative_titles = detail.get("alternative_titles", {}) if isinstance(detail.get("alternative_titles"), dict) else {}
    if media_type == "movie":
        records = alternative_titles.get("titles", []) if isinstance(alternative_titles.get("titles"), list) else []
        for item in records:
            title = str((item or {}).get("title", "")).strip() if isinstance(item, dict) else ""
            if title:
                aliases.append(title)
    else:
        records = alternative_titles.get("results", []) if isinstance(alternative_titles.get("results"), list) else []
        for item in records:
            title = str((item or {}).get("title", "")).strip() if isinstance(item, dict) else ""
            if title:
                aliases.append(title)

    translations_root = detail.get("translations", {}) if isinstance(detail.get("translations"), dict) else {}
    translations = translations_root.get("translations", []) if isinstance(translations_root.get("translations"), list) else []
    translation_fields = ("title", "name", "original_title", "original_name")
    for item in translations:
        if not isinstance(item, dict):
            continue
        data = item.get("data", {}) if isinstance(item.get("data"), dict) else {}
        for field in translation_fields:
            title = str(data.get(field, "") or "").strip()
            if title:
                aliases.append(title)
    return unique_preserve_order(aliases)[:24]


def pick_tmdb_translation_title(detail: Dict[str, Any], language_prefixes: Tuple[str, ...]) -> str:
    translations_root = detail.get("translations", {}) if isinstance(detail.get("translations"), dict) else {}
    translations = translations_root.get("translations", []) if isinstance(translations_root.get("translations"), list) else []
    normalized_prefixes = tuple(str(item or "").strip().lower() for item in language_prefixes if str(item or "").strip())
    for item in translations:
        if not isinstance(item, dict):
            continue
        iso_639_1 = str(item.get("iso_639_1", "") or "").strip().lower()
        iso_3166_1 = str(item.get("iso_3166_1", "") or "").strip().lower()
        locale_key = "-".join(part for part in (iso_639_1, iso_3166_1) if part)
        if not any(locale_key.startswith(prefix) or iso_639_1 == prefix for prefix in normalized_prefixes):
            continue
        data = item.get("data", {}) if isinstance(item.get("data"), dict) else {}
        for field in ("title", "name", "original_title", "original_name"):
            title = str(data.get(field, "") or "").strip()
            if title:
                return title
    return ""


def infer_tmdb_episode_mode(detail: Dict[str, Any]) -> str:
    genres = detail.get("genres", []) if isinstance(detail.get("genres"), list) else []
    genre_names = " ".join(str((genre or {}).get("name", "") or "") for genre in genres if isinstance(genre, dict))
    has_animation_genre = any(int((genre or {}).get("id", 0) or 0) == 16 for genre in genres if isinstance(genre, dict))
    has_animation_keyword = bool(re.search(r"(动画|動畫|anime|animation)", genre_names, re.IGNORECASE))
    number_of_seasons = max(0, parse_int(detail.get("number_of_seasons", 0), 0))
    number_of_episodes = max(0, parse_int(detail.get("number_of_episodes", 0), 0))
    if (has_animation_genre or has_animation_keyword) and number_of_seasons >= 2 and number_of_episodes >= 20:
        return "absolute"
    return "seasonal"

def build_tmdb_task_binding(detail: Dict[str, Any], media_type: str = "") -> Dict[str, Any]:
    normalized_media_type = normalize_tmdb_media_type(detail.get("media_type", ""), fallback=media_type)
    task_binding = {
        "tmdb_id": int(detail.get("id", 0) or 0),
        "tmdb_media_type": normalized_media_type,
        "tmdb_title": str(detail.get("title", "") or "").strip(),
        "tmdb_original_title": str(detail.get("original_title", "") or "").strip(),
        "tmdb_localized_title": str(detail.get("localized_title", "") or detail.get("title", "") or "").strip(),
        "tmdb_english_title": str(detail.get("english_title", "") or "").strip(),
        "tmdb_poster_url": str(detail.get("poster_url", "") or "").strip(),
        "tmdb_year": normalize_tmdb_year(detail.get("year", "")),
        "tmdb_aliases": detail.get("aliases", []) if isinstance(detail.get("aliases"), list) else [],
        "tmdb_total_episodes": max(0, parse_int(detail.get("total_episodes", 0) or 0, 0)),
        "tmdb_total_seasons": max(0, parse_int(detail.get("total_seasons", 0) or 0, 0)),
        "tmdb_season_episode_map": detail.get("season_episode_map", {}) if isinstance(detail.get("season_episode_map"), dict) else {},
        "tmdb_episode_mode": normalize_tmdb_episode_mode(detail.get("episode_mode", "seasonal")),
    }
    if normalized_media_type != "tv":
        task_binding["tmdb_total_episodes"] = 0
        task_binding["tmdb_total_seasons"] = 0
        task_binding["tmdb_season_episode_map"] = {}
        task_binding["tmdb_episode_mode"] = "seasonal"
    return task_binding


def get_tmdb_media_detail(
    tmdb_id: int,
    media_type: str,
    cfg: Optional[Dict[str, Any]] = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    normalized_media_type = normalize_tmdb_media_type(media_type, fallback="")
    if normalized_media_type not in ("movie", "tv"):
        raise RuntimeError("TMDB 影视类型仅支持 movie 或 tv")
    normalized_tmdb_id = max(0, int(tmdb_id or 0))
    if normalized_tmdb_id <= 0:
        raise RuntimeError("TMDB ID 无效")

    detail = tmdb_request_json(
        f"/{normalized_media_type}/{normalized_tmdb_id}",
        params={"append_to_response": "alternative_titles,translations"},
        cfg=cfg,
        force_refresh=force_refresh,
    )
    normalized = normalize_tmdb_result_item(detail, normalized_media_type)
    if not normalized:
        raise RuntimeError("TMDB 详情解析失败")

    aliases = build_tmdb_aliases(detail, normalized_media_type)
    title = str(normalized.get("title", "") or "").strip()
    original_title = str(normalized.get("original_title", "") or "").strip()
    english_title = pick_tmdb_translation_title(detail, ("en",)) or (original_title if original_title and not contains_cjk_text(original_title) else "")
    localized_title = title
    aliases = [alias for alias in aliases if alias not in {title, original_title}]
    payload = {
        **normalized,
        "aliases": aliases,
        "localized_title": localized_title,
        "english_title": english_title,
        "status": str(detail.get("status", "") or "").strip(),
        "total_episodes": 0,
        "total_seasons": 0,
        "season_episode_map": {},
        "episode_mode": "seasonal",
    }
    if normalized_media_type == "tv":
        payload["total_episodes"] = max(0, parse_int(detail.get("number_of_episodes", 0), 0))
        payload["total_seasons"] = max(0, parse_int(detail.get("number_of_seasons", 0), 0))
        season_records = detail.get("seasons", []) if isinstance(detail.get("seasons"), list) else []
        season_episode_map: Dict[str, int] = {}
        for raw_season in season_records:
            if not isinstance(raw_season, dict):
                continue
            season_no = max(0, parse_int(raw_season.get("season_number", 0), 0))
            episode_count = max(0, parse_int(raw_season.get("episode_count", 0), 0))
            if season_no <= 0 or episode_count <= 0:
                continue
            season_episode_map[str(season_no)] = episode_count
        payload["season_episode_map"] = season_episode_map
        payload["episode_mode"] = infer_tmdb_episode_mode(detail)
    return payload
