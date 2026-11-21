# -*- coding: utf-8 -*-
"""工作简报顶部也要有一条「这次用了什么」（用户 2026-10-24：和笔记一样，写明模型、effort、用时、token）。

守住的：effort 显式传给 ``claude -p``（结果 JSON 里不报 effort，不传就只能猜）；模型 / token / 花费取自
结果里的 ``modelUsage`` 与 ``total_cost_usd``，跟着简报落盘。页面上的用量条见 ``test_panorama_reports``。

纪律：不起真的 wsl.exe、不读真实数据目录。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet import work_briefing as wb
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
