#!/usr/bin/env python3
"""校验前端 JS 语法（按 ES Module 解析）。

为什么不直接 `node --check foo.js`：
    Node 对 `.js` 里的 `export` 语法会静默放过（Node 22 实测返回 0），
    等于没检查——2026-11-16 设置页多写一个 `}` 就是这样漏过去的。

为什么不用 `--experimental-default-type=module`：
    该参数在 Node 23+ 被移除，Node 24 直接 `bad option`
    （GitHub Actions 的 runner 就是 Node 24，2026-11-16 因此挂过 CI）。

做法：把每个文件复制成 `.mjs` 再交给 `node --check`——后缀决定解析模式，
从 Node 10 到 24 行为一致，不依赖任何实验性参数。

用法：
    python scripts/check_js_syntax.py                # 全量扫描 static/js
    python scripts/check_js_syntax.py a.js b.js      # 只查指定文件（相对仓库根）
    python scripts/check_js_syntax.py --self-test    # 验证检查器本身能抓到错误
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = REPO_ROOT / "static" / "js"


def _node() -> str | None:
    return shutil.which("node")


def _check_one(node: str, source: Path, workdir: Path) -> str:
    """把 source 复制成 .mjs 再 check；返回空串表示通过，否则返回错误摘要。"""
    mirror = workdir / (source.name + ".mjs")
    mirror.write_bytes(source.read_bytes())
    proc = subprocess.run([node, "--check", str(mirror)], capture_output=True, text=True)
    if proc.returncode == 0:
        return ""
    output = (proc.stderr or proc.stdout or "").strip().splitlines()
    hint = next((line.strip() for line in output if line.strip()), "语法错误")
    # 报错里带的是临时镜像路径，换成源文件路径更好定位
    hint = hint.replace(str(mirror), str(source))
    return hint


def _self_test(node: str) -> int:
    """确认这套检查真的能抓到语法错误（防止参数退化后静默全绿）。"""
    with tempfile.TemporaryDirectory(prefix="115-media-hub-js-selftest-") as tmp:
        work = Path(tmp)
        bad = work / "bad.mjs"
        bad.write_text("export const a = 1;\n}\n", encoding="utf-8")
        good = work / "good.mjs"
        good.write_text("export const a = 1;\n", encoding="utf-8")
        bad_rc = subprocess.run([node, "--check", str(bad)], capture_output=True).returncode
        good_rc = subprocess.run([node, "--check", str(good)], capture_output=True).returncode
    if bad_rc == 0:
        print("✗ 自检失败：故意写错的文件被判定通过，说明检查器已经失效", file=sys.stderr)
        return 1
    if good_rc != 0:
        print("✗ 自检失败：正确文件被判定失败，检查器不可用", file=sys.stderr)
        return 1
    print("✓ 自检通过：错误文件能抓到、正确文件能放过")
    return 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        node = _node()
        if not node:
            print("跳过：未找到 node")
            return 0
        return _self_test(node)

    node = _node()
    if not node:
        print("跳过 JS 语法检查：未找到 node")
        return 0

    targets = [Path(arg) for arg in argv if not arg.startswith("-")]
    if targets:
        files = [p if p.is_absolute() else (REPO_ROOT / p) for p in targets]
        files = [p for p in files if p.suffix == ".js"]
        missing = [str(p) for p in files if not p.is_file()]
        if missing:
            print("找不到这些文件：\n" + "\n".join(missing), file=sys.stderr)
            return 1
    else:
        files = sorted(DEFAULT_ROOT.rglob("*.js"))

    if not files:
        print("没有需要检查的 JS 文件")
        return 0

    workdir = Path(tempfile.mkdtemp(prefix="115-media-hub-js-check-"))
    failures: list[str] = []
    try:
        for source in files:
            error = _check_one(node, source, workdir)
            if error:
                try:
                    shown = source.relative_to(REPO_ROOT)
                except ValueError:
                    shown = source
                failures.append(f"{shown}: {error}")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    if failures:
        print(f"✗ {len(failures)}/{len(files)} 个前端文件无法按 ES Module 解析：", file=sys.stderr)
        for line in failures:
            print(f"  {line}", file=sys.stderr)
        return 1

    print(f"✓ {len(files)} 个前端文件按 ES Module 解析通过")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
