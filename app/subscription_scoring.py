from .core import *  # noqa: F401,F403

def pick_subscription_display_title(task: Dict[str, Any], item: Dict[str, Any], fallback: str = "未命名资源") -> str:
    payload_task = task if isinstance(task, dict) else {}
    payload_item = item if isinstance(item, dict) else {}

    candidate_values: List[str] = []
    for value in [
        payload_task.get("tmdb_title", ""),
        payload_task.get("title", ""),
        payload_item.get("title", ""),
        payload_task.get("tmdb_original_title", ""),
    ]:
        normalized = str(value or "").strip()
        if normalized:
            candidate_values.append(normalized)

    for field in ("tmdb_aliases", "aliases"):
        raw_values = payload_task.get(field, [])
        if not isinstance(raw_values, list):
            continue
        candidate_values.extend([str(value or "").strip() for value in raw_values if str(value or "").strip()])

    deduped_candidates = unique_preserve_order(candidate_values)
    for candidate in deduped_candidates:
        if contains_cjk_text(candidate):
            return candidate

    if str(payload_item.get("title", "") or "").strip():
        return str(payload_item.get("title", "") or "").strip()
    if deduped_candidates:
        return deduped_candidates[0]
    return str(fallback or "未命名资源").strip() or "未命名资源"

def build_subscription_text_tokens(text: str) -> List[str]:
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", " ", str(text or "").lower())
    tokens: List[str] = []
    for token in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", normalized):
        value = token.strip()
        if not value:
            continue
        if value in SUBSCRIPTION_STOP_WORDS:
            continue
        if value.isdigit() and len(value) <= 1:
            continue
        if len(value) <= 1 and not value.isdigit():
            continue
        tokens.append(value)
    return unique_preserve_order(tokens)

def build_subscription_query_tokens(task: Dict[str, Any]) -> List[str]:
    values = [task.get("title", ""), task.get("tmdb_title", ""), task.get("tmdb_original_title", "")]
    aliases = task.get("aliases", [])
    if isinstance(aliases, list):
        values.extend(aliases)
    tmdb_aliases = task.get("tmdb_aliases", [])
    if isinstance(tmdb_aliases, list):
        values.extend(tmdb_aliases)
    return unique_preserve_order(
        [token for value in values for token in build_subscription_text_tokens(str(value or ""))]
    )

def build_subscription_candidate_text(item: Dict[str, Any]) -> str:
    payload = item if isinstance(item, dict) else {}
    parts = [
        payload.get("title", ""),
        payload.get("raw_text", ""),
        payload.get("source_name", ""),
        payload.get("channel_name", ""),
    ]
    return re.sub(r"\s+", " ", " ".join(str(part or "").lower() for part in parts)).strip()

def compact_subscription_text(text: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(text or "").lower())

def strip_subscription_cjk_particles(text: str) -> str:
    return re.sub(r"[的之与和及·・]", "", str(text or ""))

def subscription_token_hit(token: str, text: str, text_compact: str) -> bool:
    normalized_token = str(token or "").strip().lower()
    if not normalized_token:
        return False
    if normalized_token in text:
        return True

    token_compact = compact_subscription_text(normalized_token)
    if not token_compact:
        return False
    if token_compact in text_compact:
        return True

    if re.search(r"[\u4e00-\u9fff]", token_compact):
        compact_without_particles = strip_subscription_cjk_particles(token_compact)
        if len(compact_without_particles) >= 2 and compact_without_particles in text_compact:
            return True
    return False

def detect_subscription_resolution(item: Dict[str, Any]) -> int:
    payload = item if isinstance(item, dict) else {}
    quality = str(payload.get("quality", "") or "").lower()
    text = f"{quality} {payload.get('title', '')} {payload.get('raw_text', '')}".lower()
    if re.search(r"\b(2160p|4k|uhd)\b", text):
        return 2160
    if re.search(r"\b(1080p|fhd)\b", text):
        return 1080
    if re.search(r"\b(720p|hd)\b", text):
        return 720
    if re.search(r"\b(480p|sd)\b", text):
        return 480
    if re.search(r"\b360p\b", text):
        return 360
    return 0

def score_subscription_title_signal(
    title: str,
    text: str,
    text_compact: str,
    exact_bonus: int,
    compact_bonus: int,
    cjk_bonus: int,
) -> int:
    title_norm = str(title or "").strip().lower()
    if not title_norm:
        return 0
    title_compact = compact_subscription_text(title_norm)
    if title_norm and title_norm in text:
        return int(exact_bonus)
    if title_compact and title_compact in text_compact:
        return int(compact_bonus)
    if title_compact:
        compact_without_particles = strip_subscription_cjk_particles(title_compact)
        if len(compact_without_particles) >= 2 and compact_without_particles in text_compact:
            return int(cjk_bonus)
    return 0

def score_subscription_quality_preference(task: Dict[str, Any], item: Dict[str, Any]) -> Tuple[int, int, str]:
    resolution = detect_subscription_resolution(item)
    quality_priority = normalize_subscription_quality_priority(
        task.get("quality_priority", SUBSCRIPTION_QUALITY_PRIORITY_DEFAULT)
    )
    if resolution <= 0:
        return 0, 0, quality_priority

    normalized_resolution = 360
    if resolution >= 2160:
        normalized_resolution = 2160
    elif resolution >= 1080:
        normalized_resolution = 1080
    elif resolution >= 720:
        normalized_resolution = 720
    elif resolution >= 480:
        normalized_resolution = 480

    order = SUBSCRIPTION_QUALITY_PRIORITY_ORDERS.get(
        quality_priority, SUBSCRIPTION_QUALITY_PRIORITY_ORDERS[SUBSCRIPTION_QUALITY_PRIORITY_DEFAULT]
    )
    if normalized_resolution not in order:
        return 0, normalized_resolution, quality_priority
    index = order.index(normalized_resolution)
    bonus_map = {0: 12, 1: 9, 2: 6, 3: 3, 4: 1}
    return int(bonus_map.get(index, 0)), normalized_resolution, quality_priority

def parse_small_cjk_number(value: Any, default: int = 0, max_value: int = 200) -> int:
    text = str(value or "").strip()
    if not text:
        return default
    if re.fullmatch(r"\d{1,4}", text):
        parsed_int = int(text)
        return parsed_int if 0 < parsed_int <= max_value else default
    if not re.fullmatch(r"[零〇一二三四五六七八九十两兩]+", text):
        return default

    parsed = -1
    if "十" in text:
        parts = text.split("十")
        if len(parts) <= 2:
            head = parts[0]
            tail = parts[1] if len(parts) == 2 else ""
            if head:
                tens = CJK_NUMERAL_DIGITS.get(head, -1)
                if tens > 0:
                    ones = 0
                    if tail:
                        ones = CJK_NUMERAL_DIGITS.get(tail, -1)
                    if ones >= 0:
                        parsed = tens * 10 + ones
            else:
                ones = 0
                if tail:
                    ones = CJK_NUMERAL_DIGITS.get(tail, -1)
                if ones >= 0:
                    parsed = 10 + ones
    else:
        parsed = CJK_NUMERAL_DIGITS.get(text, -1)

    return parsed if 0 < parsed <= max_value else default

def parse_resource_episode_meta(item: Dict[str, Any]) -> Dict[str, int]:
    payload = item if isinstance(item, dict) else {}
    text = f"{payload.get('title', '')} {payload.get('raw_text', '')}"
    season = 0
    episode = 0
    total = 0
    range_start = 0
    range_end = 0

    def _parse_episode_value(raw_value: Any) -> int:
        token = str(raw_value or "").strip()
        if not token:
            return 0
        if re.fullmatch(r"\d{1,4}", token):
            return max(0, int(token or 0))
        return max(0, parse_small_cjk_number(token, default=0, max_value=5000))

    for pattern in RESOURCE_EPISODE_RANGE_REGEXES:
        range_match = pattern.search(text)
        if not range_match:
            continue
        start_episode = _parse_episode_value(range_match.group(1))
        end_episode = _parse_episode_value(range_match.group(2))
        if start_episode <= 0 and end_episode <= 0:
            continue
        matched_fragment = str(range_match.group(0) or "")
        has_episode_context = bool(
            re.search(r"(第|集|話|话|ep|e\d|更新|更至|更到|合集|合輯|完结|完結|全)", matched_fragment, re.IGNORECASE)
        )
        if start_episode >= 1900 and end_episode >= 1900 and (not has_episode_context):
            continue
        if max(start_episode, end_episode) > 300 and (not has_episode_context):
            continue
        if end_episode < start_episode:
            start_episode, end_episode = end_episode, start_episode
        range_start = start_episode
        range_end = end_episode
        break

    se_match = RESOURCE_SEASON_EPISODE_REGEX.search(text)
    if se_match:
        season = max(0, int(se_match.group(1) or 0))
        episode = max(0, int(se_match.group(2) or 0))
    else:
        season_match = RESOURCE_SEASON_ONLY_REGEX.search(text)
        if season_match:
            season = max(0, int(season_match.group(1) or 0))
        else:
            season_cn_match = RESOURCE_SEASON_ONLY_CN_REGEX.search(text)
            if season_cn_match:
                season = max(0, parse_small_cjk_number(season_cn_match.group(1), default=0, max_value=99))
            else:
                season_en_match = RESOURCE_SEASON_ENGLISH_REGEX.search(text)
                if season_en_match:
                    season = max(0, int(season_en_match.group(1) or 0))
        episode_match = (
            RESOURCE_EPISODE_ONLY_REGEX.search(text)
            or RESOURCE_EPISODE_ONLY_CN_REGEX.search(text)
            or RESOURCE_EPISODE_CODE_REGEX.search(text)
        )
        if episode_match:
            episode = _parse_episode_value(episode_match.group(1))
        if episode <= 0:
            for pattern in RESOURCE_EPISODE_PROGRESS_REGEXES:
                progress_match = pattern.search(text)
                if not progress_match:
                    continue
                episode = _parse_episode_value(progress_match.group(1))
                if episode > 0:
                    break

    if range_end > 0:
        episode = max(episode, range_end)
        if total <= 0 and range_start > 0 and range_start <= 1:
            total = max(total, range_end)

    for pattern in RESOURCE_TOTAL_EPISODES_REGEXES:
        matched = pattern.search(text)
        if matched:
            total = _parse_episode_value(matched.group(1))
            break

    has_collection_hint = bool(RESOURCE_COLLECTION_HINT_REGEX.search(text))
    if total > 0 and has_collection_hint:
        if range_end <= 0:
            range_start = 1
            range_end = total
        episode = max(episode, total)
    elif episode <= 0 and total > 0 and ("全集" in text or "完结" in text or "完結" in text):
        episode = total
    return {
        "season": season,
        "episode": episode,
        "total": total,
        "range_start": range_start,
        "range_end": range_end,
    }

def match_subscription_media_type(task: Dict[str, Any], item: Dict[str, Any]) -> Tuple[bool, str]:
    media_type = str(task.get("media_type", "movie") or "movie").strip().lower()
    anime_mode = is_subscription_anime_compatible_task(task)
    text = build_subscription_candidate_text(item)
    meta = parse_resource_episode_meta(item)
    has_episode_meta = bool(int(meta.get("season", 0) or 0) > 0 or int(meta.get("episode", 0) or 0) > 0 or int(meta.get("total", 0) or 0) > 0)
    tv_hint = bool(
        re.search(
            r"(电视剧|剧集|番剧|动漫|第\s*[一二三四五六七八九十两兩0-9]+\s*(?:季|集|话|話)|season\s*\d+|s\d{1,2}\s*e?\d{0,3}|ep\s*\d{1,3}|更新至\s*\d+\s*(?:集|話|话)|全\s*\d+\s*(?:集|話|话)|完结|完結)",
            text,
            re.IGNORECASE,
        )
    )
    movie_hint = bool(re.search(r"(电影|movie|film|剧场版|電影)", text, re.IGNORECASE))

    if media_type == "movie":
        if has_episode_meta:
            return False, "episode_like"
        if tv_hint:
            return False, "tv_like"
        return True, "ok"

    # tv 强分区：默认必须具备剧集证据（季/集元信息或电视剧关键词）
    if has_episode_meta or tv_hint:
        return True, "ok"
    if anime_mode and not movie_hint:
        # 连载动漫资源有时不包含标准季集标记，动漫兼容模式下允许放行到后续评分阶段。
        return True, "anime_relaxed"
    if movie_hint:
        return False, "movie_like"
    return False, "missing_episode_meta"

def detect_resource_year(item: Dict[str, Any]) -> str:
    payload = item if isinstance(item, dict) else {}
    known_year = str(payload.get("year", "") or "").strip()
    if re.fullmatch(r"(19|20)\d{2}", known_year):
        return known_year
    combined = f"{payload.get('title', '')} {payload.get('raw_text', '')}"
    matched = RESOURCE_YEAR_REGEX.search(combined)
    return matched.group(1) if matched else ""

def _collect_subscription_title_signals(task: Dict[str, Any]) -> List[Tuple[str, int, int, int]]:
    title_signals: List[Tuple[str, int, int, int]] = [
        (str(task.get("title", "") or "").strip(), 14, 12, 10),
        (str(task.get("tmdb_title", "") or "").strip(), 13, 11, 9),
        (str(task.get("tmdb_original_title", "") or "").strip(), 12, 10, 8),
    ]
    aliases = task.get("aliases", [])
    if isinstance(aliases, list):
        title_signals.extend([(str(alias or "").strip(), 10, 8, 6) for alias in aliases[:6]])
    tmdb_aliases = task.get("tmdb_aliases", [])
    if isinstance(tmdb_aliases, list):
        title_signals.extend([(str(alias or "").strip(), 10, 8, 6) for alias in tmdb_aliases[:8]])
    return title_signals

def evaluate_subscription_candidate_title_match(task: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
    text = build_subscription_candidate_text(item)
    text_compact = compact_subscription_text(text)
    matched_titles: List[str] = []
    matched_score = 0
    seen_title_tokens: Set[str] = set()
    for title_value, exact_bonus, compact_bonus, cjk_bonus in _collect_subscription_title_signals(task):
        normalized_title = str(title_value or "").strip()
        normalized_key = compact_subscription_text(normalized_title)
        if not normalized_title or not normalized_key or normalized_key in seen_title_tokens:
            continue
        seen_title_tokens.add(normalized_key)
        signal_bonus = score_subscription_title_signal(
            normalized_title,
            text,
            text_compact,
            exact_bonus,
            compact_bonus,
            cjk_bonus,
        )
        if signal_bonus <= 0:
            continue
        matched_titles.append(normalized_title)
        matched_score = max(matched_score, int(signal_bonus))
    return {
        "matched": bool(matched_titles),
        "matched_score": int(matched_score),
        "matched_titles": matched_titles[:8],
    }

def match_subscription_exclude_keyword(task: Dict[str, Any], item: Dict[str, Any]) -> str:
    keywords = normalize_subscription_exclude_keywords((task or {}).get("exclude_keywords", []))
    if not keywords:
        return ""
    text = build_subscription_candidate_text(item)
    text_compact = compact_subscription_text(text)
    for keyword in keywords:
        normalized_keyword = str(keyword or "").strip().lower()
        if not normalized_keyword:
            continue
        if normalized_keyword in text:
            return keyword
        keyword_compact = compact_subscription_text(normalized_keyword)
        if keyword_compact and keyword_compact in text_compact:
            return keyword
    return ""

def score_subscription_candidate(
    task: Dict[str, Any],
    item: Dict[str, Any],
    query_tokens: List[str],
    last_episode: int,
) -> Dict[str, Any]:
    text = build_subscription_candidate_text(item)
    text_compact = compact_subscription_text(text)
    token_hits = sum(1 for token in query_tokens if subscription_token_hit(token, text, text_compact))
    # 别名过多时 token 总数会显著变大，限制分母避免有效命中被稀释
    token_denominator = max(1, min(8, len(query_tokens)))
    token_score = int((min(token_hits, token_denominator) / token_denominator) * 70)
    score = token_score

    title_eval = evaluate_subscription_candidate_title_match(task, item)
    title_bonus = int(title_eval.get("matched_score", 0) or 0)
    score += int(title_bonus)

    quality_bonus, resolution, quality_priority = score_subscription_quality_preference(task, item)
    score += int(quality_bonus)

    meta = parse_resource_episode_meta(item)
    media_type = str(task.get("media_type", "movie") or "movie").strip().lower()
    anime_mode_flag = is_subscription_anime_compatible_task(task)
    multi_season_mode = is_subscription_multi_season_mode(task)
    task_year = normalize_tmdb_year(task.get("year", "")) or normalize_tmdb_year(task.get("tmdb_year", ""))
    candidate_year = detect_resource_year(item)
    if task_year:
        if candidate_year == task_year:
            score += 12
        elif candidate_year:
            # 动漫和长连载经常出现不同年份打包（首播年 / 当前年 / 重制年），年份冲突仅做轻惩罚。
            if media_type == "tv" and anime_mode_flag:
                score -= 2
            elif media_type == "tv":
                score -= 8
            else:
                score -= 16

    if media_type == "movie":
        if meta["episode"] > 0:
            score -= 14
        if "电影" in text or "movie" in text or "film" in text:
            score += 6
    else:
        season = max(1, int(task.get("season", 1) or 1))
        anime_mode = anime_mode_flag
        episode_mode = resolve_subscription_tv_episode_mode(task)
        candidate_season = max(0, int(meta.get("season", 0) or 0))
        candidate_episode = max(0, int(meta.get("episode", 0) or 0))
        range_start = max(0, int(meta.get("range_start", 0) or 0))
        range_end = max(0, int(meta.get("range_end", 0) or 0))
        if multi_season_mode and candidate_season > 0:
            absolute_episode = convert_subscription_episode_to_absolute(task, candidate_season, candidate_episode)
            if absolute_episode > 0:
                candidate_episode = absolute_episode
            absolute_range_start, absolute_range_end = convert_subscription_episode_range_to_absolute(
                task, candidate_season, range_start, range_end
            )
            if absolute_range_end > 0:
                range_start = absolute_range_start
                range_end = absolute_range_end
        has_episode_range = range_end > 0 and range_start > 0
        if episode_mode == "absolute":
            if candidate_season > 0:
                score += 4
            elif candidate_season <= 0:
                # 多季合一或绝对集序下，不对任务季数做偏置。
                score += 2
        else:
            if candidate_season > 0:
                if candidate_season == season:
                    score += 10
                else:
                    score -= 6 if anime_mode else 18
            elif season == 1:
                score += 2
            elif anime_mode:
                score += 1

        if candidate_episode <= 0:
            score -= 4 if anime_mode else 8
        else:
            if candidate_episode <= last_episode:
                if has_episode_range and range_start <= max(1, last_episode):
                    # 区间包常用于补档，不能因为末集偏旧被提前淘汰。
                    score -= 1 if anime_mode else 2
                else:
                    # 旧集会在执行阶段被显式跳过，这里仅轻惩罚，避免评分阶段直接整体淘汰
                    score -= 4 if anime_mode else 6
            else:
                gap = candidate_episode - last_episode
                if gap == 1:
                    score += 16
                elif gap <= 4:
                    score += 11
                else:
                    score += 7
        if has_episode_range:
            range_size = max(1, range_end - range_start + 1)
            if range_start <= 1 and range_end >= max(1, last_episode):
                score += 14 if anime_mode else 8
            elif range_end > last_episode:
                score += 10 if anime_mode else 6
            elif range_start <= max(1, last_episode):
                score += 5 if anime_mode else 3
            if range_start <= 1 and range_size >= 24:
                score += 8 if anime_mode else 5
            if range_size >= 12:
                score += 4
        total_episodes = resolve_subscription_tv_total_episodes(task, state_total=0)
        if total_episodes > 0 and candidate_episode > total_episodes:
            score -= 24

    return {
        "item": item,
        "score": int(score),
        "token_hits": token_hits,
        "token_total": len(query_tokens),
        "season": int(meta.get("season", 0) or 0),
        "episode": int(candidate_episode if media_type == "tv" else max(0, int(meta.get("episode", 0) or 0))),
        "total": int(meta["total"] or 0),
        "range_start": int(range_start if media_type == "tv" else max(0, int(meta.get("range_start", 0) or 0))),
        "range_end": int(range_end if media_type == "tv" else max(0, int(meta.get("range_end", 0) or 0))),
        "resolution": int(resolution or 0),
        "quality_bonus": int(quality_bonus or 0),
        "quality_priority": quality_priority,
        "title_match": bool(title_eval.get("matched", False)),
        "title_match_score": int(title_eval.get("matched_score", 0) or 0),
        "title_match_titles": title_eval.get("matched_titles", []) if isinstance(title_eval.get("matched_titles"), list) else [],
    }

def score_subscription_candidate_quark(
    task: Dict[str, Any],
    item: Dict[str, Any],
    query_tokens: List[str],
    last_episode: int,
) -> Dict[str, Any]:
    scored = score_subscription_candidate(task, item, query_tokens, last_episode)
    media_type = str(task.get("media_type", "movie") or "movie").strip().lower()
    episode_hit = bool(
        int(scored.get("episode", 0) or 0) > 0
        or int(scored.get("range_end", 0) or 0) > 0
    )
    title_match = bool(scored.get("title_match", False))
    score_value = int(scored.get("score", 0) or 0)

    if not title_match:
        # 标题优先的频道候选要求强标题命中，纯“集数命中”不允许放行。
        score_value -= 80
        if media_type == "tv" and episode_hit:
            score_value -= 20
        scored["title_blocked"] = True
        scored["title_block_reason"] = "title_mismatch"
    else:
        score_value += 8 if int(scored.get("title_match_score", 0) or 0) >= 10 else 5
        if media_type == "tv":
            score_value += 6 if episode_hit else -8
        scored["title_blocked"] = False
        scored["title_block_reason"] = ""

    scored["score"] = int(score_value)
    return scored
