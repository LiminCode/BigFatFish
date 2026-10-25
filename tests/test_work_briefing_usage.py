# -*- coding: utf-8 -*-
"""工作简报顶部也要有一条「这次用了什么」（用户 2026-10-24：和笔记一样，写明模型、effort、用时、token）。

守住的：effort 显式传给 ``claude -p``（结果 JSON 里不报 effort，不传就只能猜）；模型 / token / 花费取自
结果里的 ``modelUsage`` 与 ``total_cost_usd``，跟着简报落盘；窗口里那条图标栏在「生成于」那行下面、
正文上面；「生成于」那行不再重复用时；旧简报没有用量时只显示用时；个人助理自己写元信息，不出这条栏。

纪律：不起真的 wsl.exe、不读真实数据目录。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet import work_briefing as wb
from pet import work_briefing_ui as ui
from tests.test_work_briefing import MONDAY_10, FakeWsl, _claude_json

app = QApplication.instance() or QApplication([])

USAGE = {"modelUsage": {"claude-sonnet-5-5": {"inputTokens": 1200, "outputTokens": 4321, "cacheReadInputTokens": 100000,
                                              "cacheCreationInputTokens": 22300}},
         "total_cost_usd": 0.8123}


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


def test_effort_is_passed_explicitly_so_what_is_shown_is_what_ran():
    assert f"--effort {wb.EFFORT}" in wb.claude_command("sonnet") and wb.EFFORT == "high"


def test_model_effort_tokens_and_cost_are_kept_with_the_briefing(tmp_path):
    briefing = wb.generate(MONDAY_10, "sonnet", run=FakeWsl(claude_stdout=_claude_json(**USAGE)))
    assert (briefing.model, briefing.effort) == ("claude-sonnet-5-5", "high")
    assert (briefing.tokens_in, briefing.tokens_out, briefing.cost_usd) == (123500, 4321, 0.8123)
    wb.record(tmp_path, briefing, MONDAY_10)
    again = wb.latest(tmp_path)
    assert (again.model, again.effort, again.tokens_in, again.tokens_out) == ("claude-sonnet-5-5", "high", 123500, 4321)


def _window_with(briefing: wb.Briefing, **kwargs) -> ui.WorkBriefingWindow:
    window = ui.WorkBriefingWindow(theme="light")
    window.show_briefing(briefing, **kwargs)
    return window


def _chips(window: ui.WorkBriefingWindow) -> dict[str, str]:
    return {chip.key: chip.text.text() for chip in window.usage_bar.chips() if not chip.isHidden()}


def test_the_usage_strip_sits_under_the_generated_line_and_above_the_body():
    briefing = wb.Briefing(ok=True, summary="s", markdown="## Jira\n无", generated_at="2026-10-24T10:00:00", seconds=175.9,
                           model="claude-sonnet-5-5", effort="high", tokens_in=123500, tokens_out=4321, cost_usd=0.8123)
    window = _window_with(briefing)
    try:
        assert not window.usage_bar.isHidden()
        assert _chips(window) == {"model": "claude-sonnet-5-5", "effort": "high", "time": "176 秒",
                                  "tokens_in": "124k", "tokens_out": "4.3k", "cost": "0.812"}
        page = window.briefing_page.layout()
        assert page.indexOf(window.meta_label) < page.indexOf(window.usage_bar) < page.indexOf(window.body)
        assert "生成于 10-24 10:00" in window.meta_label.text() and "秒" not in window.meta_label.text(), "用时挪到图标栏"
        tips = {chip.key: chip.toolTip() for chip in window.usage_bar.chips()}
        assert "123,500" in tips["tokens_in"] and "0.8123" in tips["cost"] and "high" in tips["effort"]
    finally:
        window.close()


def test_an_older_briefing_without_usage_shows_only_the_time():
    window = _window_with(wb.Briefing(ok=True, summary="s", markdown="m", generated_at="2026-10-23T10:00:00", seconds=79.4))
    try:
        assert _chips(window) == {"time": "79 秒"}
    finally:
        window.close()


def test_the_strip_speaks_english():
    i18n.set_language("en")
    window = _window_with(wb.Briefing(ok=True, summary="s", markdown="m", generated_at="2026-10-23T10:00:00", seconds=79.4,
                                      model="claude-sonnet-5-5", effort="high", tokens_in=1, tokens_out=2, cost_usd=0.01))
    try:
        assert _chips(window)["time"] == "79 s"
        assert window.meta_label.text().startswith("Generated 10-23 10:00") and " s " not in window.meta_label.text()
    finally:
        window.close()


def test_nothing_to_show_hides_the_strip_and_a_custom_meta_line_brings_its_own():
    window = ui.WorkBriefingWindow(theme="light")
    try:
        window.show_briefing(None)
        assert window.usage_bar.isHidden()
        window.show_briefing(wb.Briefing(ok=True, summary="s", markdown="m", generated_at="2026-10-23T10:00:00",
                                         seconds=5, model="x"), meta="个人助理自己的元信息")
        assert window.usage_bar.isHidden()
    finally:
        window.close()


def test_the_strip_recolours_with_the_theme():
    window = _window_with(wb.Briefing(ok=True, summary="s", markdown="m", generated_at="2026-10-23T10:00:00", seconds=5))
    try:
        window.toggle_theme()
        assert ui.briefing_tokens(True)["muted"] in window.usage_bar.styleSheet()
    finally:
        window.close()
