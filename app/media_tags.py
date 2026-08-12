import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


MEDIA_TAG_GROUP_ORDER = ("resolution", "source", "dynamic_range", "video", "audio")
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
        return match.group(0), match.span()
    for match in MEDIA_AUDIO_CHANNEL_REGEX.finditer(text, max(0, start - 8), start):
        return match.group(0), match.span()
    return "", None


def _add_media_tag(groups: Dict[str, List[str]], seen: set, group: str, label: str) -> None:
    if not group or not label:
        return
    key = (group, label.lower())
    if key in seen:
        return
    seen.add(key)
    groups.setdefault(group, []).append(label)


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
