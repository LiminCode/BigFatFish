# -*- coding: utf-8 -*-
"""交付证据与文档纪律的机器化校验。

`AGENTS.md` 的 **Delivery evidence discipline** 要求每个 PR 交付三份证据：
修改文件说明 / 性能分析 / 实机运行记录。2026-11-15 起证据写在 **PR 描述**里，
仓库不再为每个 PR 留一份报告文件；大改动另记一份 ADR（`docs/adr/`）。

本文件守四件事，都是「不守就会悄悄烂掉」的：

1. 规范还在：PR 描述模板存在且含三个证据章节，`AGENTS.md` 仍写明要求并指向模板；
2. 报告不长回来：`docs/` 下不再出现 `PR-REPORT-*.md`；
3. ADR 成形：每份 ADR 含「背景 / 决定 / 后果」三节，并在 `docs/adr/README.md` 登记；
4. 文档不成孤儿、链接不悬空：`docs/` 顶层每份文档都在 `docs/README.md` 登记，
   Markdown 里的相对链接、以及代码 / 文档里写的 `docs/….md` 路径都指向真实存在的文件。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import unquote

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
ADR_DIR = DOCS / "adr"

AGENTS = ROOT / "AGENTS.md"
PR_TEMPLATE = ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md"
DOCS_INDEX = DOCS / "README.md"
ADR_INDEX = ADR_DIR / "README.md"

# 三份证据：AGENTS.md 里的中文名 ↔ PR 描述模板里的英文章节名（PR 描述用英文写）。
EVIDENCE = {
    "修改文件说明": "What changed and why",
    "性能分析": "Performance",
    "实机运行记录": "Real-machine run",
}

ADR_SECTIONS = ("背景", "决定", "后果")
_ADR_NAME = re.compile(r"^\d{4}-[a-z0-9-]+\.md$")

# 会写到文档路径的地方：根级与 docs/ 的 Markdown、agent 技能、以及代码注释。
_MARKDOWN_ROOTS = ("docs", ".agents", ".github", "prompts", "tools")
_CODE_ROOTS = ("pet", "tests", "scripts", "tools")

_MD_LINK = re.compile(r"\]\(([^)\s]+)\)")
_CODE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
# `docs/xxx.md` 形式的仓库路径；前面是 `/` 的属于 URL 或相对链接，不算。
_DOCS_PATH = re.compile(r"(?<![\w/.-])docs/[\w./-]+\.md")


def _headings(text: str) -> list[str]:
    """取 Markdown 标题文本（去掉 # 与首尾空白），用于标题级匹配。"""
    return [
        line.lstrip("#").strip()
        for line in text.splitlines()
        if line.lstrip().startswith("#")
    ]


def _links(path: Path) -> list[str]:
    """文件里的 Markdown 链接目标；代码块和行内代码里的 `](…)` 是示例文字，不算。"""
    text = _CODE.sub("", path.read_text(encoding="utf-8"))
    return [unquote(target) for target in _MD_LINK.findall(text)]


def _markdown_files() -> list[Path]:
    files = sorted(ROOT.glob("*.md"))
    for name in _MARKDOWN_ROOTS:
        files.extend(sorted((ROOT / name).rglob("*.md")))
    return files


def _text_files() -> list[Path]:
    files = _markdown_files()
    for name in _CODE_ROOTS:
        files.extend(sorted((ROOT / name).rglob("*.py")))
    return [path for path in files if path != Path(__file__).resolve()]


def _adr_files() -> list[Path]:
    return sorted(path for path in ADR_DIR.glob("*.md") if _ADR_NAME.match(path.name))


ADRS = _adr_files()
ADR_IDS = [path.name for path in ADRS]


def test_pr_template_declares_the_three_evidence_sections():
    """PR 描述模板是提交者的复制源：必须存在，且标题里逐字有三个证据章节。"""
    assert PR_TEMPLATE.is_file(), f"PR 描述模板缺失：{PR_TEMPLATE}"
    headings = _headings(PR_TEMPLATE.read_text(encoding="utf-8"))
    for name, section in EVIDENCE.items():
        assert section in headings, (
            f"{PR_TEMPLATE.name} 缺少证据章节「{section}」（{name}）"
        )


def test_agents_documents_the_norm_and_points_at_the_template():
    """规范必须写在 AGENTS.md 里：只存在于聊天或某次 PR 描述里的纪律等于不存在。"""
    text = AGENTS.read_text(encoding="utf-8")
    for name in EVIDENCE:
        assert name in text, f"AGENTS.md 不再写明必备证据「{name}」"
    for pointer in (".github/PULL_REQUEST_TEMPLATE.md", "docs/adr/README.md", "CHANGELOG.md"):
        assert pointer in text, f"AGENTS.md 没有指向 {pointer}"


def test_no_per_pr_report_files_under_docs():
    """每个 PR 一份报告的做法已停用：证据进 PR 描述，长期知识进主题文档 / ADR。"""
    strays = sorted(path.relative_to(ROOT).as_posix() for path in DOCS.rglob("PR-REPORT-*.md"))
    assert not strays, (
        "docs/ 下不应再有 PR 报告文件，三份证据写进 PR 描述"
        f"（见 AGENTS.md Delivery evidence discipline）：{strays}"
    )


def test_adr_directory_has_an_index_that_says_when_to_write_one():
    assert ADR_INDEX.is_file(), f"ADR 索引缺失：{ADR_INDEX}"
    headings = _headings(ADR_INDEX.read_text(encoding="utf-8"))
    assert "什么时候写" in headings, "docs/adr/README.md 必须写明什么时候该写 ADR"
    assert ADRS, "docs/adr/ 下应至少有一份 ADR（文件名形如 0001-some-decision.md）"


@pytest.mark.parametrize("adr", ADRS, ids=ADR_IDS)
def test_adr_has_the_three_sections_and_is_indexed(adr: Path):
    headings = _headings(adr.read_text(encoding="utf-8"))
    missing = [section for section in ADR_SECTIONS if section not in headings]
    assert not missing, f"{adr.name} 缺少章节：{', '.join(missing)}（模板见 docs/adr/README.md）"
    assert adr.name in ADR_INDEX.read_text(encoding="utf-8"), (
        f"{adr.name} 未在 docs/adr/README.md 的索引里登记"
    )


def test_every_top_level_doc_is_listed_in_the_docs_index():
    """docs/ 顶层的每份文档都要在 docs/README.md 里有一行，否则就是没人找得到的孤儿。"""
    linked = {target.split("#")[0] for target in _links(DOCS_INDEX)}
    orphans = sorted(
        path.name for path in DOCS.glob("*.md")
        if path != DOCS_INDEX and path.name not in linked
    )
    assert not orphans, f"这些文档没有在 docs/README.md 登记：{orphans}"


def test_relative_markdown_links_resolve():
    """Markdown 里的相对链接必须指向存在的文件（CI 在区分大小写的文件系统上跑）。"""
    broken = []
    for path in _markdown_files():
        for target in _links(path):
            if "://" in target or target.startswith(("#", "mailto:")):
                continue
            written = Path(os.path.normpath(path.parent / target.split("#")[0]))
            if not _exists_exact(written):
                broken.append(f"{path.relative_to(ROOT).as_posix()} -> {target}")
    assert not broken, "悬空的相对链接：\n" + "\n".join(broken)


def test_docs_paths_written_in_code_and_docs_exist():
    """注释和文档里写的 `docs/….md` 路径要真实存在：文档改名 / 合并后别留下指路牌指向空地。"""
    missing = []
    for path in _text_files():
        for match in _DOCS_PATH.findall(path.read_text(encoding="utf-8", errors="replace")):
            if not _exists_exact(ROOT / match):
                missing.append(f"{path.relative_to(ROOT).as_posix()} -> {match}")
    assert not missing, "指向不存在文档的路径：\n" + "\n".join(sorted(set(missing)))


def _exists_exact(path: Path) -> bool:
    """存在且大小写逐段一致（Windows 文件系统不区分大小写，CI 的 Linux 区分）。

    传进来的必须是「照写的样子」拼出来的路径（不要先 resolve，那会把大小写改对）。
    """
    if not path.exists():
        return False
    try:
        relative = path.relative_to(ROOT)
    except ValueError:
        return True
    current = ROOT
    for part in relative.parts:
        if part not in {entry.name for entry in current.iterdir()}:
            return False
        current = current / part
    return True
