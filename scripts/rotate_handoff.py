#!/usr/bin/env python3
"""交接文档轮转工具。

职责：把 `docs/superpowers/handoff.md` 中超期或超出体积预算的条目，机械地移入
`docs/superpowers/handoff-archive.md`，让“每个会话开头要读的文件”保持很小。

设计约束（重要）：

1. 不丢条目：轮转前后两个文件的条目集合完全一致。
2. 可重复执行：同样的输入产生同样的输出，重复运行是空操作（幂等）。
3. 不碰人工内容：`## 交接记录` 之前的部分（说明、规则、历史专题）原样保留。

文件约定（两个文件一致）：

- 以 `## 交接记录` 这一行为分界；它之前是人工维护的头部，之后是条目。
- 一条记录 = 以 `- YYYY-MM-DD` 开头的一行。
- 如果文件里没有 `## 交接记录` 分界（例如早期的旧版 handoff），脚本按旧格式迁移：
  头部改用内置模板，文件里所有 `- YYYY-MM-DD` 行都按条目收集。

用法：

    .venv/bin/python scripts/rotate_handoff.py              # 按默认窗口轮转
    .venv/bin/python scripts/rotate_handoff.py --dry-run     # 只预览，不写文件
    .venv/bin/python scripts/rotate_handoff.py --check       # 需要轮转时退出码 1（给 CI 用）
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HANDOFF_PATH = REPO_ROOT / "docs" / "superpowers" / "handoff.md"
ARCHIVE_PATH = REPO_ROOT / "docs" / "superpowers" / "handoff-archive.md"

ENTRY_RE = re.compile(r"^- \d{4}-\d{2}-\d{2}")
SECTION_MARKER = "## 交接记录"

DEFAULT_KEEP_DAYS = 14
DEFAULT_MAX_BYTES = 32 * 1024
DEFAULT_MIN_ENTRIES = 10

# 旧版 handoff.md 没有分界行，迁移时用这份头部替换掉原来那段会过期的“当前状态”。
HANDOFF_HEAD = """# Agent Handoff

> 本文件只保留**最近**的交接条目（默认最近 14 天且 ≤32 KB），开头就能读完。
> 当前状态看 `docs/superpowers/state.md`（唯一需要每次完整阅读的状态文件）。
> 历史条目在 `docs/superpowers/handoff-archive.md`，通常无需阅读：
> `rg "关键词" docs/superpowers/handoff-archive.md` 按需检索即可。
> 归档中的“下一步”可能已经失效，不应视为当前任务；一切以代码和 `state.md` 为准。
>
> 维护方式：追加条目后执行 `.venv/bin/python scripts/rotate_handoff.py`
> （可加 `--dry-run` 预览），不要手工搬条目。

## 记录规则

- 仅在完成重要功能、重要修复，或需要其他 agent 接手时追加一条，不要记录调试过程。
- 每条必须是**一行**，格式为：
  `- YYYY-MM-DD | 分支或提交 | 版本 | 变更一句话 | 根因或影响 | 验证证据 | 下一步`
- 根因分析、改动清单、测试细节写进 commit message 或 `docs/superpowers/specs/` 文档，
  这里只留指针，避免同样的内容存两遍。
- “验证证据”写明跑过的命令与结论（如 `unittest 1142 项零失败`），不要粘贴完整输出。
- 涉及 CLI 可操作能力（刮削整理选项、监控任务配置、接口变更等）的改动，
  需同步补齐 `cli.py` 命令支持与 README CLI 文档，并在条目中注明。
- 条目超出保留窗口后由 `scripts/rotate_handoff.py` 移入归档，不要手工堆积。

## 交接记录
"""

ARCHIVE_HEAD = """# Agent Handoff Archive

> 本文件保存已轮转的历史交接条目，仅供追溯，通常无需阅读。
> 内容可能已被后续实现、产品决策或版本更新取代，请勿直接作为当前开发依据。
> 当前状态看 `docs/superpowers/state.md`；最近交接看 `docs/superpowers/handoff.md`。
> 检索方式：`rg "关键词" docs/superpowers/handoff-archive.md`，再按行范围读取。
>
> `## 交接记录` 下方的条目由 `.venv/bin/python scripts/rotate_handoff.py`
> 自动维护（按日期升序），请勿手工排序或搬动。

## 交接记录
"""


def normalize_head(head: str) -> str:
    """统一头部结尾：去掉多余空行，留恰好一个空行再接条目。"""
    return head.rstrip("\n") + "\n\n"


def read_text(path: Path, fallback: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return fallback


def display_path(path: Path) -> str:
    """打印用路径：能相对仓库显示就相对显示，否则退回绝对路径。"""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def split_document(text: str, fallback_head: str) -> tuple[str, list[str]]:
    """拆出“头部”和“条目列表”。

    找不到 `## 交接记录` 分界时，按旧版格式处理：头部用 fallback_head 替换，
    全文所有条目格式的行都视为条目。
    """
    lines = text.splitlines(keepends=True)
    marker_index = None
    for index, line in enumerate(lines):
        if line.strip() == SECTION_MARKER:
            marker_index = index
            break

    if marker_index is None:
        head = normalize_head(fallback_head)
        body = lines
    else:
        head = normalize_head("".join(lines[: marker_index + 1]))
        body = lines[marker_index + 1 :]

    entries = [line.strip() for line in body if ENTRY_RE.match(line)]
    return head, entries


def entry_sort_key(entry: str) -> tuple[str, str]:
    """按日期升序；同日条目按文本排序，保证重复执行结果稳定（幂等）。"""
    return (entry[2:12], entry)


def entry_date(entry: str) -> dt.date:
    return dt.date.fromisoformat(entry[2:12])


def merge_entries(*groups: list[str]) -> tuple[list[str], int]:
    """合并条目并去重，返回（按日期升序的列表, 被忽略的重复条数）。"""
    merged: list[str] = []
    seen: set[str] = set()
    duplicates = 0
    for group in groups:
        for entry in group:
            if entry in seen:
                duplicates += 1
                continue
            seen.add(entry)
            merged.append(entry)
    merged.sort(key=entry_sort_key)
    return merged, duplicates


def split_by_window(
    entries: list[str], as_of: dt.date, keep_days: int
) -> tuple[list[str], list[str]]:
    """按日期窗口分成（保留区, 归档区），两者都是升序。"""
    cutoff = as_of - dt.timedelta(days=keep_days)
    recent: list[str] = []
    older: list[str] = []
    for entry in entries:
        (recent if entry_date(entry) >= cutoff else older).append(entry)
    return recent, older


def trim_to_budget(
    recent: list[str], head: str, max_bytes: int, min_entries: int
) -> tuple[list[str], list[str]]:
    """在体积预算内尽量保留最新条目。

    从最新往旧累加，超出预算就停止；但至少保留 min_entries 条，
    避免在极端配置下把最近记录全部清空。返回（保留区升序, 溢出区升序）。
    """
    budget = max_bytes - len(head.encode("utf-8"))
    kept_desc: list[str] = []
    used = 0
    for entry in reversed(recent):
        size = len(entry.encode("utf-8")) + 1
        if len(kept_desc) >= min_entries and used + size > budget:
            break
        kept_desc.append(entry)
        used += size
    overflow_count = len(recent) - len(kept_desc)
    return recent[overflow_count:], recent[:overflow_count]


def build_rotation(
    handoff_text: str,
    archive_text: str,
    *,
    as_of: dt.date,
    keep_days: int = DEFAULT_KEEP_DAYS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    min_entries: int = DEFAULT_MIN_ENTRIES,
) -> tuple[str, str, dict[str, int]]:
    """计算轮转后的两个文件内容，不写盘。"""
    handoff_head, handoff_entries = split_document(handoff_text, HANDOFF_HEAD)
    archive_head, archive_entries = split_document(archive_text, ARCHIVE_HEAD)

    merged, duplicates = merge_entries(handoff_entries, archive_entries)
    recent, older = split_by_window(merged, as_of, keep_days)
    kept, overflow = trim_to_budget(recent, handoff_head, max_bytes, min_entries)

    # kept 是升序，写文件时倒序（最新的在最上面）。
    handoff_output = handoff_head + "".join(
        entry + "\n" for entry in reversed(kept)
    )
    archived = older + overflow
    archive_output = archive_head + "".join(entry + "\n" for entry in archived)

    stats = {
        "total": len(merged),
        "kept": len(kept),
        "archived": len(archived),
        "duplicates": duplicates,
        "handoff_bytes": len(handoff_output.encode("utf-8")),
        "archive_bytes": len(archive_output.encode("utf-8")),
    }
    return handoff_output, archive_output, stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="把超期/超预算的交接条目从 handoff.md 轮转到 handoff-archive.md",
    )
    parser.add_argument(
        "--keep-days",
        type=int,
        default=DEFAULT_KEEP_DAYS,
        help=f"handoff.md 保留最近多少天的条目（默认 {DEFAULT_KEEP_DAYS}）",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=DEFAULT_MAX_BYTES,
        help=f"handoff.md 的体积上限，单位字节（默认 {DEFAULT_MAX_BYTES}）",
    )
    parser.add_argument(
        "--min-entries",
        type=int,
        default=DEFAULT_MIN_ENTRIES,
        help=f"即使超出体积也要至少保留的条目数（默认 {DEFAULT_MIN_ENTRIES}）",
    )
    parser.add_argument(
        "--as-of",
        default=None,
        help="计算窗口的参考日期 YYYY-MM-DD，默认取今天",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印结果，不写文件")
    parser.add_argument(
        "--check", action="store_true", help="不写文件；需要轮转时退出码为 1"
    )
    args = parser.parse_args(argv)

    as_of = dt.date.fromisoformat(args.as_of) if args.as_of else dt.date.today()
    handoff_text = read_text(HANDOFF_PATH, HANDOFF_HEAD)
    archive_text = read_text(ARCHIVE_PATH, ARCHIVE_HEAD)

    handoff_output, archive_output, stats = build_rotation(
        handoff_text,
        archive_text,
        as_of=as_of,
        keep_days=args.keep_days,
        max_bytes=args.max_bytes,
        min_entries=args.min_entries,
    )
    changed = handoff_output != handoff_text or archive_output != archive_text

    print(
        f"总条目 {stats['total']} 条：保留 {stats['kept']} 条"
        f"（{stats['handoff_bytes']} 字节），归档 {stats['archived']} 条"
        f"（{stats['archive_bytes']} 字节）"
    )
    if stats["duplicates"]:
        print(f"注意：跳过了 {stats['duplicates']} 条重复条目")

    if args.check:
        if changed:
            print("需要轮转：请运行 .venv/bin/python scripts/rotate_handoff.py")
            return 1
        print("无需轮转")
        return 0

    if args.dry_run:
        print("dry-run：未写入文件" + ("（有变更）" if changed else "（无变更）"))
        return 0

    if not changed:
        print("无需轮转，文件未改动")
        return 0

    HANDOFF_PATH.write_text(handoff_output, encoding="utf-8")
    ARCHIVE_PATH.write_text(archive_output, encoding="utf-8")
    print(f"已写入 {display_path(HANDOFF_PATH)} 与 {display_path(ARCHIVE_PATH)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
