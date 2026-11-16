import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_js_syntax.py"


class JsModuleSyntaxTest(unittest.TestCase):
    """前端模块必须能被浏览器按 ES Module 解析。

    背景（2026-11-16）：设置页做分组合并时，摘要函数里多了一个 `}`。
    `node --check static/js/modules/tabs/settings.js` 对这个文件返回 0 ——
    Node 对带 `export` 的 .js 会静默放过语法错误。结果本地和 CI 的 JS 语法门
    全部失守，坏文件进了工作区：设置页导航能画出来，但所有分区展不开。

    校验逻辑收在 `scripts/check_js_syntax.py`（复制成 .mjs 再 check，不依赖
    Node 版本——`--experimental-default-type=module` 在 Node 23+ 已被移除，
    CI 的 Node 24 因此挂过一次）。这里只负责两件事：全量文件必须通过，
    以及检查器本身必须还能抓到错误（防止它哪天退化成静默全绿）。
    """

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(CHECKER), *args],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )

    def test_checker_still_detects_broken_syntax(self):
        proc = self._run("--self-test")
        if "未找到 node" in (proc.stdout or ""):
            self.skipTest("未安装 node，跳过前端语法校验")
        self.assertEqual(
            proc.returncode,
            0,
            f"检查器自检失败，说明它已经抓不到语法错误：\n{proc.stdout}\n{proc.stderr}",
        )

    def test_every_static_js_file_parses_as_es_module(self):
        proc = self._run()
        if "未找到 node" in (proc.stdout or ""):
            self.skipTest("未安装 node，跳过前端语法校验")
        self.assertEqual(
            proc.returncode,
            0,
            "以下前端文件无法按 ES Module 解析（页面会整块失效）：\n" + (proc.stderr or proc.stdout),
        )
        self.assertIn("解析通过", proc.stdout)


if __name__ == "__main__":
    unittest.main()
