# -*- coding: utf-8 -*-
"""工作简报里 bug 单要显眼（用户 2026-10-23：bug 优先级总是更高；被推回去时 QA 报的场景很容易漏看）。

守住的：bug 单单独查、不受「最多 15 条」的上限挤掉；Jira 一节里 bug 排最前、每条带 QA 报的场景；
「建议先做」先排 bug；窗口里 bug 那一行和它下面的场景行画上醒目的底色，别的行不画。

纪律：不起真的 wsl.exe、不读真实数据目录；工单都是虚构的。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet import work_briefing as wb
from pet import work_briefing_ui as ui
from tests.test_work_briefing import MONDAY_10

app = QApplication.instance() or QApplication([])

NO_JIRA = {**wb.DEFAULT_SOURCES, "jira": False}


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


# ---------------------------------------------------------------- 提示词

@pytest.mark.parametrize("language", ["zh", "en"])
def test_bugs_are_queried_on_their_own_so_the_cap_never_drops_them(language):
    prompt = wb.build_prompt(MONDAY_10, "", language=language)
    assert "issuetype = Bug AND statusCategory != Done ORDER BY priority DESC, updated DESC" in prompt
    assert "issuetype != Bug AND statusCategory != Done ORDER BY updated DESC" in prompt, "其余工单的查询把 bug 排除掉"


@pytest.mark.parametrize("language", ["zh", "en"])
def test_bugs_lead_the_jira_section_with_a_marker_and_the_reported_scenario(language):
    prompt = wb.build_prompt(MONDAY_10, "", language=language)
    assert f"{wb.BUG_MARK} [" in prompt, "bug 行以固定记号开头（前面是优先级星），窗口靠它上色"
    assert "getJiraIssue" in prompt
    scenario = "QA 报的场景" if language == "zh" else "QA's reported scenario"
    assert scenario in prompt


@pytest.mark.parametrize("language", ["zh", "en"])
def test_do_first_puts_bugs_ahead_of_other_work(language):
    prompt = wb.build_prompt(MONDAY_10, "", language=language)
    assert ("bug 排在其他工作前面" if language == "zh" else "bugs come before other work") in prompt


def test_without_jira_there_is_nothing_about_bugs():
    prompt = wb.build_prompt(MONDAY_10, "", sources=NO_JIRA, language="zh")
    assert wb.BUG_MARK not in prompt and "Bug" not in prompt and "bug" not in prompt


def test_the_atlassian_read_gateway_is_allowed_so_bug_comments_can_be_read():
    """2026-10-24 实机：模型读 bug 评论走的是插件的 discover / executeRead，没放行就被拒，QA 最后的回复就丢了。"""
    allowed, denied = wb.allowed_tools(), wb.denied_tools()
    for name in ("discover", "executeRead"):
        assert "mcp__plugin_atlassian_atlassian__" + name in allowed
    for name in ("executeWrite", "executeDestructive"):
        assert "mcp__plugin_atlassian_atlassian__" + name in denied and "mcp__plugin_atlassian_atlassian__" + name not in allowed
    assert not any(name.endswith("__executeRead") for name in wb.allowed_tools({**wb.DEFAULT_SOURCES, "jira": False}))


# ---------------------------------------------------------------- 窗口

BUG_REPORT = (
    "## Jira\n"
    f"- {wb.BUG_MARK} [DEMO-7](https://example.test/browse/DEMO-7) Login page freezes · `Open` · High\n"
    "  - QA 报的场景：Safari 17 上连点两次「登录」，页面卡住；预期跳到首页。\n"
    "- [DEMO-8](https://example.test/browse/DEMO-8) Tidy the build script · `Open` · Normal\n"
    "\n## 建议先做\n1. 先看 DEMO-7。\n"
)


def _backgrounds(window: ui.WorkBriefingWindow) -> dict[str, str]:
    """每个非空段落的文字 → 段落底色（没设底色是空串）。"""
    out = {}
    block = window.body.document().begin()
    while block.isValid():
        text = block.text().strip()
        if text:
            brush = block.blockFormat().background()
            out[text] = brush.color().name() if brush.style() != Qt.BrushStyle.NoBrush else ""
        block = block.next()
    return out


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_bug_lines_and_their_scenario_are_tinted_and_nothing_else(theme):
    window = ui.WorkBriefingWindow(theme=theme)
    try:
        window.show_briefing(wb.Briefing(ok=True, summary="s", markdown=BUG_REPORT,
                                         generated_at="2026-10-23T09:00:00", seconds=40))
        tint = ui.briefing_tokens(theme == "dark")["bug"]
        found = _backgrounds(window)
        bug = next(text for text in found if "DEMO-7" in text and "Login" in text)
        scenario = next(text for text in found if text.startswith("QA 报的场景"))
        other = next(text for text in found if "DEMO-8" in text)
        assert found[bug] == tint and found[scenario] == tint
        assert found[other] == "" and found["先看 DEMO-7。"] == ""
    finally:
        window.close()


def test_the_tint_follows_a_theme_switch():
    window = ui.WorkBriefingWindow(theme="light")
    try:
        window.show_briefing(wb.Briefing(ok=True, summary="s", markdown=BUG_REPORT,
                                         generated_at="2026-10-23T09:00:00", seconds=40))
        window.toggle_theme()
        bug = next(text for text in _backgrounds(window) if "DEMO-7" in text and "Login" in text)
        assert _backgrounds(window)[bug] == ui.briefing_tokens(True)["bug"]
    finally:
        window.close()


def test_the_bug_tint_differs_between_day_and_night():
    assert ui.briefing_tokens(False)["bug"] != ui.briefing_tokens(True)["bug"]
