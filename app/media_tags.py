import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


MEDIA_TAG_GROUP_ORDER = ("resolution", "source", "group", "dynamic_range", "video", "audio", "language", "subtitle")
MEDIA_TAG_GROUPS = set(MEDIA_TAG_GROUP_ORDER)
MEDIA_AUDIO_CHANNEL_REGEX = re.compile(
    r"(?<![0-9])(?:1[ ]?[.]?[ ]?0|2[ ]?[.]?[ ]?0|2[ ]?[.]?[ ]?1|5[ ]?[.]?[ ]?1|6[ ]?[.]?[ ]?1|7[ ]?[.]?[ ]?1)(?![0-9])",
    re.IGNORECASE,
)


MEDIA_TAG_RULES: Tuple[Tuple[str, str, str], ...] = (
    ("resolution", r"(?<![A-Za-z0-9])(?:4320p|8k)(?![A-Za-z0-9])", "8K"),
    ("resolution", r"(?<![A-Za-z0-9])(?:2160p|4k|uhd)(?![A-Za-z0-9])", "2160p"),
    ("resolution", r"(?<![A-Za-z0-9])1440p(?![A-Za-z0-9])", "1440p"),
    ("resolution", r"(?<![A-Za-z0-9])1080p(?![A-Za-z0-9])", "1080p"),
    ("resolution", r"(?<![A-Za-z0-9])1080i(?![A-Za-z0-9])", "1080i"),
    ("resolution", r"(?<![A-Za-z0-9])720p(?![A-Za-z0-9])", "720p"),
    ("resolution", r"(?<![A-Za-z0-9])576p(?![A-Za-z0-9])", "576p"),
    ("resolution", r"(?<![A-Za-z0-9])480p(?![A-Za-z0-9])", "480p"),
    ("source", r"(?<![A-Za-z0-9])web[\s._-]?dl(?![A-Za-z0-9])", "WEB-DL"),
    ("source", r"(?<![A-Za-z0-9])web[\s._-]?rip(?![A-Za-z0-9])", "WEBRip"),
    ("source", r"(?<![A-Za-z0-9])(?:blu[\s._-]?ray|bdrip)(?![A-Za-z0-9])", "BluRay"),
    ("source", r"(?<![A-Za-z0-9])(?:bd[\s._-]?remux|remux)(?![A-Za-z0-9])", "REMUX"),
    ("source", r"(?<![A-Za-z0-9])hdtv(?![A-Za-z0-9])", "HDTV"),
    ("dynamic_range", r"(?<![A-Za-z0-9])(?:dolby[\s._-]?vision|dovi|dv)(?![A-Za-z0-9])", "DV"),
    ("dynamic_range", r"(?<![A-Za-z0-9])hdr10(?:\+|[\s._-]?plus)(?![A-Za-z0-9])", "HDR10+"),
    ("dynamic_range", r"(?<![A-Za-z0-9])hdr10(?![A-Za-z0-9+])", "HDR10"),
    ("dynamic_range", r"(?<![A-Za-z0-9])hlg(?![A-Za-z0-9])", "HLG"),
    ("dynamic_range", r"(?<![A-Za-z0-9])hdr(?![A-Za-z0-9])", "HDR"),
    ("dynamic_range", r"(?<![A-Za-z0-9])sdr(?![A-Za-z0-9])", "SDR"),
    ("video", r"(?<![A-Za-z0-9])(?:hevc|h[\s._-]?265|x265)(?![A-Za-z0-9])", "HEVC"),
    ("video", r"(?<![A-Za-z0-9])(?:avc|h[\s._-]?264|x264)(?![A-Za-z0-9])", "H.264"),
    ("video", r"(?<![A-Za-z0-9])av1(?![A-Za-z0-9])", "AV1"),
    ("video", r"(?<![A-Za-z0-9])vp9(?![A-Za-z0-9])", "VP9"),
    ("video", r"(?<![A-Za-z0-9])(?:10[\s._-]?bit|hi10p)(?![A-Za-z0-9])", "10bit"),
    ("audio", r"(?<![A-Za-z0-9])true[\s._-]?hd(?![A-Za-z])", "TrueHD"),
    ("audio", r"(?<![A-Za-z0-9])dts[\s._-]?hd[\s._-]?ma(?![A-Za-z])", "DTS-HD MA"),
    ("audio", r"(?<![A-Za-z0-9])dts[\s._-]?x(?![A-Za-z])", "DTS-X"),
    ("audio", r"(?<![A-Za-z0-9])dts[\s._-]?hd(?![\s._-]?ma)(?![A-Za-z])", "DTS-HD"),
    ("audio", r"(?<![A-Za-z0-9])dts(?![\s._-]?(?:hd|x))(?![A-Za-z])", "DTS"),
    ("audio", r"(?<![A-Za-z0-9])(?:ddp|dd\+|dolby[\s._-]?digital[\s._-]?plus)(?![A-Za-z])", "DDP"),
    ("audio", r"(?<![A-Za-z0-9])e[\s._-]?ac[\s._-]?3(?![A-Za-z])", "EAC3"),
    ("audio", r"(?<![A-Za-z0-9])(?:dd|dolby[\s._-]?digital)(?![\s._-]?plus)(?![A-Za-z+])", "DD"),
    ("audio", r"(?<![A-Za-z0-9])a[\s._-]?c[\s._-]?3(?![A-Za-z])", "AC3"),
    ("audio", r"(?<![A-Za-z0-9])aac(?![A-Za-z0-9])", "AAC"),
    ("audio", r"(?<![A-Za-z0-9])flac(?![A-Za-z0-9])", "FLAC"),
    ("audio", r"(?<![A-Za-z0-9])opus(?![A-Za-z0-9])", "Opus"),
    ("audio", r"(?<![A-Za-z0-9])mp3(?![A-Za-z0-9])", "MP3"),
    ("audio", r"(?<![A-Za-z0-9])atmos(?![A-Za-z0-9])", "Atmos"),
    # 音轨语言：整短语优先，独立“国语/粤语/英语/双语”要求两侧都不是中文或字母数字，
    # 避免把“我的英语老师 / 双语教师”这类真实片名误判成标签。
    ("language", r"国语中字", "国语"),
    ("language", r"粤语中字", "粤语"),
    ("language", r"英语中字", "英语"),
    ("language", r"国粤双语|国英双语|中英双语", "双语"),
    ("language", r"台配国语", "台配"),
    ("language", r"(?<![一-龥A-Za-z0-9])台配(?![一-龥A-Za-z0-9])", "台配"),
    ("language", r"(?<![一-龥A-Za-z0-9])国语(?![一-龥A-Za-z0-9])", "国语"),
    ("language", r"(?<![一-龥A-Za-z0-9])粤语(?![一-龥A-Za-z0-9])", "粤语"),
    ("language", r"(?<![一-龥A-Za-z0-9])英语(?![一-龥A-Za-z0-9])", "英语"),
    ("language", r"(?<![一-龥A-Za-z0-9])双语(?![一-龥A-Za-z0-9])", "双语"),
    # 字幕：整短语优先，避免“中英字幕 / 简中英字”再被拆成冗余小标签。
    ("subtitle", r"国语中字", "中字"),
    ("subtitle", r"粤语中字", "中字"),
    ("subtitle", r"英语中字", "中字"),
    ("subtitle", r"内封中字", "内封中字"),
    ("subtitle", r"外挂中字", "外挂中字"),
    ("subtitle", r"简中英字", "简中英字"),
    ("subtitle", r"双语字幕", "双语字幕"),
    ("subtitle", r"中英字幕", "中英字幕"),
    ("subtitle", r"国英字幕", "国英字幕"),
    ("subtitle", r"(?<![一-龥A-Za-z0-9])简中(?![一-龥A-Za-z0-9])", "简中"),
    ("subtitle", r"(?<![一-龥A-Za-z0-9])繁中(?![一-龥A-Za-z0-9])", "繁中"),
    ("subtitle", r"(?<![一-龥A-Za-z0-9])中字(?![一-龥A-Za-z0-9])", "中字"),
    ("subtitle", r"(?<![一-龥A-Za-z0-9])英字(?![一-龥A-Za-z0-9])", "英字"),
    ("subtitle", r"(?<![一-龥A-Za-z0-9])无字幕(?![一-龥A-Za-z0-9])", "无字幕"),
)

COMPILED_MEDIA_TAG_RULES: Tuple[Tuple[str, re.Pattern[str], str], ...] = tuple(
    (group, re.compile(pattern, re.IGNORECASE), label)
    for group, pattern, label in MEDIA_TAG_RULES
)


def _normalize_media_tag_text(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or ""))


def _normalize_enabled_groups(enabled_groups: Any) -> Optional[set]:
    if enabled_groups is None:
        return None
    if isinstance(enabled_groups, dict):
        return {str(key or "").strip() for key, enabled in enabled_groups.items() if enabled and str(key or "").strip() in MEDIA_TAG_GROUPS}
    if isinstance(enabled_groups, (list, tuple, set)):
        return {str(item or "").strip() for item in enabled_groups if str(item or "").strip() in MEDIA_TAG_GROUPS}
    return set()


def _find_nearby_channel(text: str, start: int, end: int) -> Tuple[str, Optional[Tuple[int, int]]]:
    for match in MEDIA_AUDIO_CHANNEL_REGEX.finditer(text, end, min(len(text), end + 14)):
        if _is_false_audio_channel(text, match):
            continue
        return match.group(0), match.span()
    for match in MEDIA_AUDIO_CHANNEL_REGEX.finditer(text, max(0, start - 8), start):
        if _is_false_audio_channel(text, match):
            continue
        return match.group(0), match.span()
    return "", None


def _is_false_audio_channel(text: str, match: "re.Match[str]") -> bool:
    """把 10bit / hi10p 里的 “10” 排除掉，避免被当成 1.0 声道。"""
    if match.group(0) != "10":
        return False
    after = re.sub(r"[^a-z0-9]", "", text[match.end(): match.end() + 8].lower())
    before = re.sub(r"[^a-z0-9]", "", text[max(0, match.start() - 8): match.start()].lower())
    return after.startswith("bit") or before.endswith("bit") or before.endswith("hi")


def _add_media_tag(groups: Dict[str, List[str]], seen: set, group: str, label: str) -> None:
    if not group or not label:
        return
    key = (group, label.lower())
    if key in seen:
        return
    seen.add(key)
    groups.setdefault(group, []).append(label)


# 发布组 / 字幕组 / 压制组：整名末尾的 -GROUP，或显式的中文“XX字幕组”。为了避免把
# 分辨率、编码、语言后缀（zh-Hans）误判成组名，只在这些技术标签已经出现时才认定
# 末尾 -GROUP，并用停用词挡住常见技术 token。
MEDIA_RELEASE_GROUP_STOPWORDS = frozenset(
    {
        "hd", "dl", "ma", "x", "br", "us", "cn", "hk", "tw", "sg", "hans", "hant",
        "gb", "big5", "web", "webdl", "webrip", "bluray", "bdrip", "remux", "hdtv",
        "uhd", "4k", "8k", "2160p", "1080p", "1080i", "720p", "576p", "480p",
        "hdr", "hdr10", "hdr10plus", "sdr", "dv", "dovi", "hlg",
        "hevc", "avc", "h265", "h264", "x265", "x264", "av1", "vp9", "10bit",
        "8bit", "hi10p", "aac", "ac3", "eac3", "dd", "ddp", "truehd", "dts",
        "dtshd", "dtsma", "dtshdma", "hdma", "atmos", "flac", "mp3", "opus", "repack", "proper",
        "extended", "uncut", "internal", "multi", "complete", "directorcut",
        "fanedit", "remastered", "extendedcut", "finalcut",
    }
)
MEDIA_RELEASE_GROUP_TECH_GROUPS = ("resolution", "source", "dynamic_range", "video", "audio")
# 只剥离真实文件扩展名；不能用 os.path.splitext，否则 "H.264-NTb" 会把 ".264-NTb"
# 当成扩展名，末尾发布组就整段错位了。
MEDIA_TAG_FILE_EXT_RE = re.compile(
    r"\.(?:mkv|mp4|avi|ts|m2ts|wmv|mov|flv|webm|rmvb|rm|mpg|mpeg|vob|iso|m4v|3gp|m2v|mts|tp|divx|asf|ogm"
    r"|srt|ass|ssa|sub|vtt|idx|smi|sup|nfo|jpg|jpeg|png|webp|bmp|gif)$",
    re.IGNORECASE,
)


def _media_release_group_stopword(token: str) -> bool:
    compact = re.sub(r"[._\s-]+", "", str(token or "")).lower()
    return compact in MEDIA_RELEASE_GROUP_STOPWORDS


def _media_release_group_like(token: str) -> bool:
    """发布组判定：全大写可含数字（RARBG / D-Z0N3），或纯字母大小写混排（NTb / BlackTV / XviD）。

    混排要求“纯字母”是刻意收紧的：像 WEB-DL.x264.DDP5.1 这类由技术片段拼出来的
    尾巴同时含大小写和数字，不能当发布组。
    """
    text = str(token or "").strip()
    compact = re.sub(r"[._\s-]+", "", text)
    if not (3 <= len(compact) <= 24) or not re.search(r"[A-Za-z]", compact):
        return False
    if re.fullmatch(r"[A-Z0-9]+", compact):
        return True
    return bool(
        re.fullmatch(r"[A-Za-z]+", compact)
        and re.search(r"[A-Z]", compact)
        and re.search(r"[a-z]", compact)
    )


def _find_media_release_group(text: str, groups: Dict[str, List[str]]) -> Optional[Tuple[str, Tuple[int, int]]]:
    # 文件名可能带扩展名（.mkv/.mp4），先去掉再匹配末尾发布组，避免把 ".mkv" 当成组名。
    stem = MEDIA_TAG_FILE_EXT_RE.sub("", text)
    explicit = re.search(
        r"(?:^|[\s._\-\[\]()【】])([A-Za-z0-9\u4e00-\u9fff]{1,20}(?:字幕组|字幕組|压制组|壓制組))",
        stem,
    )
    if explicit:
        return explicit.group(1), explicit.span(1)
    if not any(groups.get(name) for name in MEDIA_RELEASE_GROUP_TECH_GROUPS):
        return None
    trailing = re.search(r"[-–—]([A-Za-z][A-Za-z0-9._]{1,23})\s*$", stem)
    if not trailing:
        return None
    token = trailing.group(1)
    if _media_release_group_stopword(token) or not _media_release_group_like(token):
        return None
    return token, trailing.span(1)


def parse_media_tags(text: Any) -> Dict[str, Any]:
    normalized_text = _normalize_media_tag_text(text)
    groups: Dict[str, List[str]] = {group: [] for group in MEDIA_TAG_GROUP_ORDER}
    seen = set()
    spans: List[Tuple[int, int]] = []

    for group, pattern, label in COMPILED_MEDIA_TAG_RULES:
        for match in pattern.finditer(normalized_text):
            tag_label = label
            span_start, span_end = match.span()
            if group == "audio" and label != "Atmos":
                channel, channel_span = _find_nearby_channel(normalized_text, span_start, span_end)
                if channel:
                    tag_label = f"{label} {channel}"
                    if channel_span:
                        span_start = min(span_start, channel_span[0])
                        span_end = max(span_end, channel_span[1])
            _add_media_tag(groups, seen, group, tag_label)
            spans.append((span_start, span_end))

    release_group = _find_media_release_group(normalized_text, groups)
    if release_group:
        label, span = release_group
        _add_media_tag(groups, seen, "group", label)
        spans.append(span)

    tags: List[str] = []
    for group in MEDIA_TAG_GROUP_ORDER:
        tags.extend(groups.get(group, []))

    return {
        "groups": groups,
        "tags": tags,
        "spans": _merge_spans(spans),
    }


def _merge_spans(spans: Sequence[Tuple[int, int]]) -> List[Tuple[int, int]]:
    merged: List[Tuple[int, int]] = []
    for start, end in sorted((max(0, start), max(0, end)) for start, end in spans if end > start):
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
            continue
        merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def filter_media_tag_labels(parsed: Dict[str, Any], enabled_groups: Any = None) -> List[str]:
    enabled = _normalize_enabled_groups(enabled_groups)
    groups = parsed.get("groups", {}) if isinstance(parsed, dict) else {}
    tags: List[str] = []
    for group in MEDIA_TAG_GROUP_ORDER:
        if enabled is not None and group not in enabled:
            continue
        values = groups.get(group, []) if isinstance(groups, dict) else []
        tags.extend(str(item or "").strip() for item in values if str(item or "").strip())
    return unique_media_tags(tags)


def media_tag_labels(text: Any, enabled_groups: Any = None) -> List[str]:
    return filter_media_tag_labels(parse_media_tags(text), enabled_groups)


def unique_media_tags(tags: Iterable[Any]) -> List[str]:
    seen = set()
    values: List[str] = []
    for item in tags:
        label = str(item or "").strip()
        key = label.lower()
        if not label or key in seen:
            continue
        seen.add(key)
        values.append(label)
    return values


def format_media_tag_summary(text: Any, separator: str = " / ", enabled_groups: Any = None) -> str:
    return separator.join(media_tag_labels(text, enabled_groups))


def remove_media_tags(text: Any) -> str:
    normalized_text = _normalize_media_tag_text(text)
    parsed = parse_media_tags(normalized_text)
    spans = parsed.get("spans", []) if isinstance(parsed, dict) else []
    if not spans:
        return normalized_text
    chunks: List[str] = []
    cursor = 0
    for start, end in spans:
        chunks.append(normalized_text[cursor:start])
        chunks.append(" ")
        cursor = end
    chunks.append(normalized_text[cursor:])
    return "".join(chunks)
