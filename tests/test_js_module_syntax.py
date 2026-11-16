import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS_ROOT = ROOT / "static/js"


def _node_binary():
    return shutil.which("node")


class JsModuleSyntaxTest(unittest.TestCase):
    """前端模块必须能被浏览器按 ES Module 解析。

    背景（2026-11-16）：设置页做分组合并时，摘要函数里多了一个 `}`。
    `node --check static/js/modules/tabs/settings.js` 对这个文件返回 0 ——
    因为 Node 22 的语法检测会把带 `export` 的 .js 当成「检测不出来就当 CJS」，
    遇到 ESM 语法直接放过。结果本地和 CI 的 JS 语法门全部失守，
    坏文件进了工作区：设置页导航能画出来，但所有分区展不开、快捷定位点了没反应。

    所以这里改用「复制成 .mjs 再 --check」的方式：后缀决定解析模式，
    Node 会真正按 ES Module 校验。缺 node 的环境跳过，不制造假失败。
    """

    def test_every_static_js_file_parses_as_es_module(self):
        node = _node_binary()
        if not node:
            self.skipTest("未安装 node，跳过前端语法校验")

        files = sorted(JS_ROOT.rglob("*.js"))
        self.assertTrue(files, "static/js 下没有找到任何 .js 文件")

        # 临时文件只落在系统临时区，不写进工作区；安全中心拦删除时忽略清理失败。
        tmp_root = Path(tempfile.mkdtemp(prefix="115-media-hub-js-check-"))
        failures = []
        try:
            for path in files:
                mirror = tmp_root / (str(path.relative_to(JS_ROOT)).replace("/", "__") + ".mjs")
                mirror.write_bytes(path.read_bytes())
                proc = subprocess.run(
                    [node, "--check", str(mirror)],
                    capture_output=True,
                    text=True,
                )
                if proc.returncode != 0:
                    detail = (proc.stderr or proc.stdout or "").strip().splitlines()
                    hint = next((line for line in detail if line.strip()), "")
                    failures.append(f"{path.relative_to(ROOT)}: {hint}")
        finally:
            shutil.rmtree(tmp_root, ignore_errors=True)

        self.assertFalse(
            failures,
            "以下前端文件无法按 ES Module 解析（页面会整块失效）：\n" + "\n".join(failures),
        )


if __name__ == "__main__":
    unittest.main()
