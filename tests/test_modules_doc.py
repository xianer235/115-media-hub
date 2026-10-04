"""守住 docs/superpowers/modules.md 不被写漏、写空。

这份索引是“新增/改名模块必须登记”的唯一机械约束：漏登记就测试失败，
免得功能文档随着代码演进慢慢失真（历史教训见 2026-10-04 的「扫描监控」修复）。
"""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULES_DOC = ROOT / "docs/superpowers/modules.md"
AGENTS_DOC = ROOT / "AGENTS.md"

# (分组名, 目录, 路径前缀, 文件模式, 最低数量) —— 最低数量只用于防止 glob 失效，
# 不锁死具体个数：新增文件应该让“覆盖率”测试失败，而不是让数量断言失败。
SCAN_GROUPS = (
    ("路由", ROOT / "app/routes", "app/routes", "*.py", 10),
    ("服务", ROOT / "app/services", "app/services", "*.py", 15),
    ("provider", ROOT / "app/providers", "app/providers", "*.py", 12),
    ("页面模板", ROOT / "templates/partials/pages", "templates/partials/pages", "*.html", 5),
)

MODULE_FIELDS = ("**用途**", "**入口**", "**会做**", "**不会做**", "**相关代码**")


def read_modules_doc() -> str:
    return MODULES_DOC.read_text(encoding="utf-8")


def scan_files() -> dict:
    groups = {}
    for label, folder, prefix, pattern, _minimum in SCAN_GROUPS:
        rel_paths = sorted(
            f"{prefix}/{path.name}"
            for path in folder.glob(pattern)
            if path.name != "__init__.py"
        )
        groups[label] = rel_paths
    return groups


def module_sections(doc_text: str) -> list:
    """取第一节「功能模块」里的每个 ### 小节，返回 (标题, 正文)。"""
    sections = []
    try:
        body = doc_text.split("## 一、功能模块", 1)[1].split("## 二、", 1)[0]
    except IndexError:
        return sections
    current_title = ""
    current_lines = []
    for line in body.splitlines():
        if line.startswith("### "):
            if current_title:
                sections.append((current_title, "\n".join(current_lines)))
            current_title = line[4:].strip()
            current_lines = []
        elif current_title:
            current_lines.append(line)
    if current_title:
        sections.append((current_title, "\n".join(current_lines)))
    return sections


class ModulesDocTest(unittest.TestCase):
    def test_doc_exists_and_has_sections(self):
        self.assertTrue(MODULES_DOC.is_file(), "缺少 docs/superpowers/modules.md")
        doc_text = read_modules_doc()
        for heading in ("## 一、功能模块", "## 二、代码索引", "## 三、维护规则"):
            self.assertIn(heading, doc_text)

    def test_scan_groups_are_not_empty(self):
        """防止目录改名或 glob 写错导致覆盖率检查静默失效。"""
        groups = scan_files()
        for label, _folder, _prefix, _pattern, minimum in SCAN_GROUPS:
            self.assertGreaterEqual(
                len(groups[label]),
                minimum,
                f"{label} 只扫到 {len(groups[label])} 个文件，检查目录是否变了",
            )

    def test_every_module_file_is_listed(self):
        doc_text = read_modules_doc()
        missing = []
        for label, rel_paths in scan_files().items():
            for rel_path in rel_paths:
                if rel_path not in doc_text:
                    missing.append(f"{label}: {rel_path}")
        self.assertEqual(missing, [], "以下文件没有登记进 modules.md：" + "、".join(missing))

    def test_every_module_section_keeps_required_fields(self):
        sections = module_sections(read_modules_doc())
        self.assertGreaterEqual(len(sections), 8, "功能模块小节太少，检查标题层级是否被改动")
        for title, body in sections:
            for field in MODULE_FIELDS:
                self.assertIn(field, body, f"模块「{title}」缺少 {field} 字段")

    def test_agents_md_points_to_modules_doc(self):
        agents_text = AGENTS_DOC.read_text(encoding="utf-8")
        self.assertIn("docs/superpowers/modules.md", agents_text)


if __name__ == "__main__":
    unittest.main()
