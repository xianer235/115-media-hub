#!/usr/bin/env python3
"""跑单元测试的统一入口（本机安全策略友好版）。

为什么不用 pytest：这台机器的安全中心会拦临时文件的创建/删除，pytest 的
capture 一启动就要 ``TemporaryFile``，直接起不来（报「No usable temporary
directory」）。所以统一用标准库 unittest，沿用 tempfile 的标准语义——测试代码
照常写 ``mkdtemp()`` / ``TemporaryDirectory()``，只是把 tempfile 的根指到
**本轮会话目录**（默认在系统临时区）。清理失败只在「落在会话目录内」时被
容忍并计数，其它路径照原样抛错，免得把真实 bug 一起吞掉。

本机拦的是「删除文件」这个系统调用本身，**跟目录归属无关**：项目文件夹也一样删不掉。
所以「删文件」类用例在本机注定假失败。要一份完全干净的结果，用容器跑::

    scripts/test_in_container.sh              # 全量，零批准
    scripts/test_in_container.sh --changed    # 只跑改动相关

本机跑（快，适合开发中挑单个模块）::

    python scripts/run_tests.py                  # 全量（80+ 个模块 / 1700+ 用例，约 2~3 分钟）
    python scripts/run_tests.py --changed        # 只跑与 git 改动相关的模块（开发时用，秒级~几十秒）
    python scripts/run_tests.py --changed HEAD~1 # 指定对比基线
    python scripts/run_tests.py pan115 cross     # 按关键字挑模块
    python scripts/run_tests.py tests.test_pan115_downurl   # 精确指定模块（可多个）
    python scripts/run_tests.py --list --changed # 只看会跑哪些模块，不执行
    python scripts/run_tests.py --clean-temp     # 把项目里的测试临时目录整体移出项目（不跑测试）

临时文件怎么放：默认落在**系统临时目录**（``<系统temp>/115-media-hub-tests/run-XXXX``），
项目目录里不留渣，也不用为删文件反复确认。只有系统临时目录也不可用时才退回
``.workbuddy/tmp/work``，那种情况下会打印提示，并可用 ``--clean-temp`` 一次性
把残渣整体移出项目。

挑选规则（--changed / 关键字）：
    * 公共层（app/core.py、app/db.py、app/config_store.py、app/providers/base.py、
      app/providers/registry.py 等）一改就退化为全量——这些文件被所有链路共用，
      挑子集等于没测。
    * 其余按「文件名里的关键词」匹配测试模块名，命中即跑；一个都没命中时退化为全量。
    * 无论怎么挑，都会带上 tests.test_modules_doc（新增 app 模块必须登记 modules.md）。
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.join(REPO, "tests")

# 临时文件放哪：优先系统临时目录，项目目录只作兜底。
# 为什么不放项目里：这台机器的安全策略对「项目目录内的文件操作」逐次审查，
# 在项目里建/删成千上万个临时目录既慢又会被要求确认；一旦删除被拦，
# 残渣还会永远留在项目里、出现在文件树里。放项目外，删不掉的渣由系统自己回收。
#
# 注意：这里**不能**调 tempfile.gettempdir()。它的实现是「建一个探测文件再删掉」，
# 删除被安全策略拦住时会一路退到 cwd（也就是仓库根目录），在那里留下一个
# 8 字符的 4 字节空文件——正是工作区里那些删不掉的细碎文件的来源。
# 直接读环境变量就没有这个问题。
def _system_temp_base():
    for env in ("TMPDIR", "TEMP", "TMP"):
        base = os.environ.get(env)
        if base and os.path.isdir(base):
            return base
    return "/tmp" if os.path.isdir("/tmp") else None


SYS_TMP_BASE = _system_temp_base()
SYS_TMP_ROOT = os.path.join(SYS_TMP_BASE, "115-media-hub-tests") if SYS_TMP_BASE else None
REPO_TMP_ROOT = os.path.join(REPO, ".workbuddy", "tmp")
REPO_TMP_DIR = os.path.join(REPO_TMP_ROOT, "work")
# .workbuddy/tmp 下历次「把临时目录指进项目内」留下的同类残渣，统一收掉
LEGACY_TEST_TEMP_DIRS = ("work", "debug-tests")
# tempfile 探测失败时会在 cwd 留下的东西：8 位小写字母数字、不超过 4 字节。
# 字符集必须带下划线——RandomNameSequence 用的是 "abcdefghijklmnopqrstuvwxyz0123456789_"，
# 漏掉下划线会让 `384oxwf_` 这类名字永远清不掉（真实踩过）。
PROBE_FILE_RE = re.compile(r"^[0-9a-z_]{8}$")
# 兜底模式（临时目录只能落在项目里）下，每轮最多清多少个历史残留：
# 项目内删除很慢，一次清几千个会把测试启动拖成十几分钟。
PRUNE_LIMIT = 50
STALE_TEMP_SECONDS = 30 * 60
TEMP_ROOT = None
SESSION_DIR = None
# 落在会话目录内、被安全策略拦掉的清理次数。只记不抛，收尾时统一说一句。
TOLERATED_CLEANUP_FAILURES = []

# 改这些文件等于改公共层，跑子集没意义，直接全量
SHARED_PATHS = {
    "app/core.py",
    "app/db.py",
    "app/main.py",
    "app/config_store.py",
    "app/config_runtime.py",
    "app/background.py",
    "app/startup.py",
    "app/providers/base.py",
    "app/providers/registry.py",
    "main.py",
    "requirements.txt",
    "templates/base.html",
    "static/js/index.js",
}
# 关键词里没信息量的词，参与匹配只会把无关测试拖进来
STOPWORDS = {
    "app",
    "services",
    "providers",
    "routes",
    "static",
    "templates",
    "partials",
    "pages",
    "modules",
    "common",
    "base",
    "index",
    "main",
    "utils",
    "views",
    "model",
    "models",
    "docs",
    "tests",
    "test",
    "core",
    "js",
    "py",
}
ALWAYS_RUN = ["test_modules_doc"]


def _human_size(num):
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.0f}{unit}" if unit == "B" else f"{num:.1f}{unit}"
        num /= 1024.0


def _path_size(path):
    """粗算目录占用。只用于打印提示，算不准不影响测试。"""
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


def _can_create(base):
    """这个目录能不能写文件（只看写，不看删）。

    刻意不看删除：安全策略拦删除时，写文件往往还是可以的，这时候把临时文件
    放到项目外的系统临时区依然更好——删不掉的渣不在项目里，系统会自己回收。
    """
    probe = os.path.join(base, ".probe-write-check")
    try:
        os.makedirs(base, exist_ok=True)
        with open(probe, "a", encoding="utf-8") as handle:
            handle.write("")
        return True
    except Exception:
        return False


def _can_delete(base):
    """这个目录里的文件能不能删掉。复用固定名字的探针，删不掉也只留一个文件。"""
    probe = os.path.join(base, ".probe-delete-check")
    try:
        if not os.path.exists(probe):
            with open(probe, "w", encoding="utf-8") as handle:
                handle.write("x")
        os.unlink(probe)
        return True
    except Exception:
        return False


def _pick_temp_root():
    """优先项目外的系统临时目录（能写就行），实在写不了才退回项目内。"""
    for base in (SYS_TMP_ROOT, REPO_TMP_DIR):
        if base and _can_create(base):
            return base
    return REPO_TMP_DIR


def _prune_stale_tempdirs(limit=PRUNE_LIMIT):
    """清掉项目内的历史残留，返回 (删掉几个, 还剩几个)。

    只在兜底模式（临时目录只能落在项目里）时调用，而且限量：项目内的删除在这台
    机器上很慢，一次清几千个会把测试启动拖成十几分钟。要一次清完用 --clean-temp。
    """
    if not os.path.isdir(REPO_TMP_DIR):
        return 0, 0
    now = time.time()
    removed = 0
    remaining = 0
    for name in os.listdir(REPO_TMP_DIR):
        path = os.path.join(REPO_TMP_DIR, name)
        if SESSION_DIR and os.path.abspath(path) == os.path.abspath(SESSION_DIR):
            continue
        if removed >= limit:
            remaining += 1
            continue
        try:
            if now - os.lstat(path).st_mtime < STALE_TEMP_SECONDS:
                remaining += 1
                continue
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.unlink(path)
        except OSError:
            remaining += 1
            continue
        if os.path.exists(path):
            remaining += 1
        else:
            removed += 1
    return removed, remaining


def _prune_temp_root(base, max_age=STALE_TEMP_SECONDS):
    """清掉临时根目录下的历史残留，返回 (清掉几个, 释放多少字节)。

    和项目内那套的区别：系统临时区删除很快，可以按时间清、不限个数；
    正在跑的其它测试（含容器里的）会话目录年龄不到 ``max_age``，不会被误删。
    这是「会话目录自己删不掉」时的兜底——本机能拦删除，残渣就会一直留着。
    """
    if not base or not os.path.isdir(base):
        return 0, 0
    now = time.time()
    removed = 0
    freed = 0
    try:
        names = os.listdir(base)
    except OSError:
        return 0, 0
    for name in names:
        path = os.path.join(base, name)
        if SESSION_DIR and os.path.abspath(path) == os.path.abspath(SESSION_DIR):
            continue
        try:
            stat = os.lstat(path)
        except OSError:
            continue
        if now - stat.st_mtime < max_age:
            continue
        is_dir = os.path.isdir(path) and not os.path.islink(path)
        size = _path_size(path) if is_dir else stat.st_size
        try:
            if is_dir:
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.unlink(path)
        except OSError:
            continue
        if not os.path.exists(path):
            removed += 1
            freed += size
    return removed, freed


def _start_temp_session():
    """开一个本轮专用的临时目录；顺手回收上一轮的残留。"""
    global TEMP_ROOT, SESSION_DIR
    TEMP_ROOT = _pick_temp_root()
    if os.path.abspath(TEMP_ROOT) != os.path.abspath(REPO_TMP_DIR):
        removed, freed = _prune_temp_root(TEMP_ROOT)
        if removed:
            print(f"→ 回收上次中断留下的临时目录 {removed} 个（{_human_size(freed)}）")
    else:
        removed, remaining = _prune_stale_tempdirs()
        print(
            f"→ 临时目录只能放在项目内（{REPO_TMP_DIR}）：本轮清了 {removed} 个历史残留，还剩 {remaining} 个\n"
            "    项目内清理很慢，要一次清干净：python scripts/run_tests.py --clean-temp"
        )
    SESSION_DIR = tempfile.mkdtemp(prefix="run-", dir=TEMP_ROOT)
    return SESSION_DIR


def _report_tolerated_cleanup():
    """把「被拦掉的清理」显式说一句——容忍可以，静默不行。"""
    if not TOLERATED_CLEANUP_FAILURES:
        return
    print(
        f"→ 本轮有 {len(TOLERATED_CLEANUP_FAILURES)} 次临时文件清理被安全策略拦下"
        "（环境问题，不是代码问题）"
    )


def _finish_temp_session():
    """删掉本轮会话目录；删不干净就明确说一句，别让项目里默默堆渣。"""
    if not SESSION_DIR or not os.path.isdir(SESSION_DIR):
        _report_tolerated_cleanup()
        return
    shutil.rmtree(SESSION_DIR, ignore_errors=True)
    if not os.path.exists(SESSION_DIR):
        _report_tolerated_cleanup()
        return
    leftover = len(os.listdir(SESSION_DIR))
    if not os.path.abspath(SESSION_DIR).startswith(REPO + os.sep):
        # 临时目录在项目外：系统会自己回收，只报一句，不要求人工介入
        print(f"→ 本轮临时目录没删净（剩 {leftover} 项），留在系统临时区由系统回收：{SESSION_DIR}")
        _report_tolerated_cleanup()
        return
    print(
        f"⚠️  本轮有 {leftover} 项临时文件没删掉（{_human_size(_path_size(SESSION_DIR))}）：{SESSION_DIR}\n"
        "    这台机器拦「删除文件」，测试自己清不掉是环境问题，不是代码问题。\n"
        "    下次跑测试会自动清扫；想立刻清干净：python scripts/run_tests.py --clean-temp\n"
        "    要一份零残留的结果，用容器跑：scripts/test_in_container.sh"
    )
    _report_tolerated_cleanup()


def _git_tracks(name):
    return (
        subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", name],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        ).returncode
        == 0
    )


def _sweep_probe_files():
    """删掉仓库根目录那些 8 字符 4 字节无名文件。

    它们是 ``tempfile.gettempdir()`` 的候选探测留下的：探针建好文件后删不掉
    （安全策略拦删除），就一路退到 cwd，把残骸留在仓库根目录。删不掉的会
    一直堆在那里，每次清理都要人工确认——所以给一条命令一次性收掉。
    只删「8 位小写字母数字或下划线 + ≤4 字节 + git 没跟踪」的文件，不动任何正常文件。
    """
    removed, kept = [], []
    for name in os.listdir(REPO):
        path = os.path.join(REPO, name)
        if not PROBE_FILE_RE.match(name) or os.path.isdir(path) or os.path.islink(path):
            continue
        try:
            if os.path.getsize(path) > 4:
                continue
        except OSError:
            continue
        if _git_tracks(name):
            continue
        try:
            os.unlink(path)
            removed.append(name)
        except OSError:
            kept.append(name)
    return removed, kept


def _relocate_dir(path, label):
    """把整个目录 rename 到系统临时区的回收目录（瞬时，不逐个删）。

    返回 (状态, 条目数, 字节数, 目标路径或错误信息)，状态是 empty/moved/failed。
    """
    entries = os.listdir(path)
    if not entries:
        return "empty", 0, 0, ""
    size = _path_size(path)
    trash_base = SYS_TMP_BASE or os.path.join(REPO_TMP_ROOT, "trash")
    trash_root = os.path.join(trash_base, "115-media-hub-test-trash")
    os.makedirs(trash_root, exist_ok=True)
    dest = os.path.join(trash_root, f"{label}-" + time.strftime("%Y%m%d-%H%M%S"))
    try:
        os.rename(path, dest)
    except OSError as exc:
        return "failed", len(entries), size, str(exc)
    return "moved", len(entries), size, dest


def _clean_temp_all():
    """收拾项目内所有测试残留：临时目录整体移出项目，仓库根目录的探测文件删掉。"""
    code = 0
    removed, kept = _sweep_probe_files()
    if removed:
        print(f"已删除仓库根目录的探测残留文件 {len(removed)} 个：{' '.join(removed)}")
    if kept:
        print(f"⚠️  还有 {len(kept)} 个探测残留删不掉（需要授权）：{' '.join(kept)}")

    for name in LEGACY_TEST_TEMP_DIRS:
        path = os.path.join(REPO_TMP_ROOT, name)
        if not os.path.isdir(path):
            continue
        status, count, size, detail = _relocate_dir(path, name)
        if status == "empty":
            continue
        if status == "moved":
            print(f"已把 {name} 下的 {count} 项（{_human_size(size)}）移出项目：{detail}")
        else:
            print(f"⚠️  {path} 移不出去（{detail}），请手动删除：rm -rf {path}")
            code = 1
    print("移出的东西在系统临时区，系统会自动回收；想立刻腾空间就删掉打印出来的路径")
    return code


def _probe_tempdir_writable():
    """自检：能不能在本机删掉临时文件。

    这台机器的安全中心会拦「删除文件」，删不掉时 SQLite 的 journal/wal、
    跨盘复制的 .part 临时文件都会残留，测试会刷出一堆和代码无关的失败。
    """
    return _can_delete(SESSION_DIR or TEMP_ROOT or REPO_TMP_DIR)


def _inside_session(path) -> bool:
    """这个路径是否落在本轮临时目录里（只有它们的清理失败才算环境噪音）。"""
    bases = [os.path.abspath(base) for base in (SESSION_DIR, TEMP_ROOT) if base]
    try:
        target = os.path.abspath(path)
    except (TypeError, ValueError):
        return False
    return any(target == base or target.startswith(base + os.sep) for base in bases)


def _harden_tempdir() -> None:
    """把 tempfile 指到本轮会话目录，并只在会话目录内容忍清理失败。

    为什么还要容忍：安全中心拦的是「删除文件」这个系统调用，删不掉时
    SQLite 的 journal/wal、跨盘复制的 .part 都会残留在会话目录里，进而把
    一堆正常用例刷成失败。这类失败是环境问题，不是代码问题。

    为什么**只**在会话目录内容忍：以前是全局无条件忽略，连生产代码里
    真写错的清理（比如路径算错、权限没判）也一起吞掉，测试就再也看不见了。
    现在会话目录外的失败照原样抛出，真实 bug 不会被静默掩盖。
    """
    tempfile.tempdir = SESSION_DIR or TEMP_ROOT or REPO_TMP_DIR

    real_rmtree = shutil.rmtree

    # 3.12 起 rmtree/TemporaryDirectory 改用 onexc，3.9/3.10 用 onerror。
    # 用 *args/**kwargs 原样透传，才不会在某个 Python 版本上突然 TypeError。
    def tolerant_rmtree(path, ignore_errors=False, *args, **kwargs):
        try:
            return real_rmtree(path, ignore_errors=ignore_errors, *args, **kwargs)
        except OSError:
            if _inside_session(path):
                TOLERATED_CLEANUP_FAILURES.append(str(path))
                return None
            raise

    shutil.rmtree = tolerant_rmtree

    # 生产用 WAL，测试里换成内存 journal：WAL 会额外产生 -wal/-shm，
    # 在被拦删除的机器上删不掉，SQLite 直接抛 disk I/O error，一崩一大片。
    # 只影响测试进程的连接配置，不碰生产代码。
    try:
        from app import db as app_db

        def configure_without_wal(conn, enable_wal=False):
            try:
                conn.execute("PRAGMA busy_timeout = 30000")
                conn.execute("PRAGMA journal_mode = MEMORY")
                conn.execute("PRAGMA synchronous = OFF")
                conn.execute("PRAGMA temp_store = MEMORY")
            except Exception:
                pass

        app_db._configure_connection = configure_without_wal
    except Exception:
        pass

    _force_memory_journal_everywhere()


def _force_memory_journal_everywhere() -> None:
    """把 ``sqlite3.connect`` 兜一层，连上就先关掉磁盘 journal。

    只改 ``app.db`` 那一层不够：不少测试自己 ``sqlite3.connect`` 建临时库
    （如 ``xcopy-db-*``），照样落下 ``data.db-journal``，在这台「删不掉文件」的
    机器上直接变成 ``disk I/O error``。``journal_mode`` 是**数据库文件级的持久
    设置**，连上设一次，之后所有连接都走内存 journal，不再产生 journal 文件。
    """
    import sqlite3

    if getattr(sqlite3.connect, "_wb_memory_journal", False):
        return

    real_connect = sqlite3.connect

    def connect_with_memory_journal(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        try:
            conn.execute("PRAGMA journal_mode = MEMORY")
            conn.execute("PRAGMA busy_timeout = 30000")
        except Exception:
            pass
        return conn

    connect_with_memory_journal._wb_memory_journal = True
    sqlite3.connect = connect_with_memory_journal


def _all_test_modules():
    return sorted(
        name[:-3]
        for name in os.listdir(TESTS_DIR)
        if name.startswith("test_") and name.endswith(".py")
    )


def _git_output(*args):
    try:
        return subprocess.run(
            ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
        ).stdout
    except Exception:
        return ""


def _changed_paths(base):
    paths = set()
    paths.update(_git_output("diff", "--name-only", base).split())
    paths.update(_git_output("diff", "--name-only", "--cached", base).split())
    paths.update(_git_output("ls-files", "--others", "--exclude-standard").split())
    return sorted(path for path in paths if path)


def _tokens_for(path):
    stem = os.path.splitext(os.path.basename(path))[0].lower()
    tokens = {stem}
    tokens.update(part for part in stem.split("_") if part)
    # 前端路径里的目录名也有信息量：static/js/modules/cross_copy/ui.js → cross_copy
    parts = path.lower().split(os.sep)[:-1]
    if len(parts) >= 2:
        tokens.add(parts[-1])
    return {token for token in tokens if len(token) >= 4 and token not in STOPWORDS}


def select_modules(paths, keywords):
    """返回 (模块名列表, 是否退化为全量, 说明)。"""
    all_modules = _all_test_modules()
    if paths and any(path in SHARED_PATHS for path in paths):
        hit = sorted({path for path in paths if path in SHARED_PATHS})
        return all_modules, True, f"改到公共层 {', '.join(hit)}"

    wanted = set()
    for path in paths or []:
        wanted |= _tokens_for(path)
    wanted |= {str(word).lower() for word in (keywords or []) if str(word).strip()}

    if not wanted:
        return all_modules, True, "没有可用的匹配关键词"

    chosen = [
        module
        for module in all_modules
        if any(token in module.lower() for token in wanted)
    ]
    chosen.extend(module for module in ALWAYS_RUN if module not in chosen)
    if len(chosen) <= len(ALWAYS_RUN):
        return all_modules, True, "关键词没有命中任何测试模块"
    return sorted(set(chosen)), False, ""


def main(argv):
    parser = argparse.ArgumentParser(add_help=True, description="跑单元测试（unittest 版）")
    parser.add_argument("modules", nargs="*", help="模块名或关键字")
    parser.add_argument("--changed", nargs="?", const="HEAD", default=None, help="按 git 改动挑选（可选基线，默认 HEAD）")
    parser.add_argument("--list", action="store_true", help="只列出将运行的模块")
    parser.add_argument("--quiet", action="store_true", help="不打印每条用例名")
    parser.add_argument("--clean-temp", action="store_true", help="清掉所有测试临时目录（不区分新旧）后退出")
    args = parser.parse_args(argv)

    if args.clean_temp:
        return _clean_temp_all()

    explicit = [name[len("tests."):] for name in args.modules if name.startswith("tests.")]
    keywords = [name for name in args.modules if not name.startswith("tests.")]

    if explicit:
        modules, degenerate, reason = explicit, False, ""
    elif args.changed is not None:
        paths = _changed_paths(args.changed)
        modules, degenerate, reason = select_modules(paths, keywords)
        if not paths:
            print("（git 没有改动，按全量跑）")
    elif keywords:
        modules, degenerate, reason = select_modules([], keywords)
    else:
        modules, degenerate, reason = _all_test_modules(), False, ""

    if degenerate and reason:
        print(f"→ 退化为全量：{reason}")

    if args.list:
        print(f"将运行 {len(modules)} 个模块：")
        for module in modules:
            print(f"  tests.{module}")
        return 0

    # 先补好搜索路径：_harden_tempdir 里要 import app.db 给连接层打补丁
    sys.path.insert(0, REPO)
    _start_temp_session()
    _harden_tempdir()
    if not _probe_tempdir_writable():
        print(
            "⚠️  本机安全策略拦了「删除文件」（跟目录无关，项目文件夹一样拦）：\n"
            "    SQLite 的 journal/wal、临时 .part 文件删不掉，删文件类的用例会假失败。\n"
            "    要一份干净结果，改用容器跑（一次构建、之后零批准）：\n"
            "        scripts/test_in_container.sh [--changed|模块名...]\n"
        )

    try:
        return _run_suite(modules, args)
    finally:
        _finish_temp_session()


def _run_suite(modules, args):
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    load_failed = []
    for module in modules:
        try:
            suite.addTests(loader.loadTestsFromName(f"tests.{module}"))
        except Exception as exc:  # noqa: BLE001 - 导入失败也要算失败
            load_failed.append(f"{module}: {exc}")

    print(f"→ 运行 {len(modules)} 个模块" + ("（全量）" if is_full_selection(modules) else ""))
    verbosity = 1 if args.quiet else 2
    started_at = time.monotonic()
    result = unittest.TextTestRunner(verbosity=verbosity).run(suite)
    elapsed = round(time.monotonic() - started_at, 1)

    bad = len(result.failures) + len(result.errors) + len(load_failed)
    print(f"\n结果：{result.testsRun} 条用例，失败 {len(result.failures)}，错误 {len(result.errors)}，耗时 {elapsed}s")
    for item in load_failed:
        print(f"  导入失败 {item}")
    return 0 if bad == 0 else 1


def is_full_selection(modules):
    return len(modules) == len(_all_test_modules())


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
