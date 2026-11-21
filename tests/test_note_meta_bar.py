# -*- coding: utf-8 -*-
"""一次 ``claude -p`` 用量的「基本信息」怎么写（``note_meta_bar``）：数字缩写（34.6k）、花费三位小数、秒数取整，精确值在
悬停提示里；没有模型名（旧记录）只有用时；中英文跟界面语言；小图标按给的颜色画（黑夜用浅色）。

Qt 的那条信息栏 ``NoteMetaBar`` 2026-11-21 随简报窗口下线；浏览器里的报告页 / 笔记页用的就是这里的 ``usage_values``。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet import note_meta_bar as nmb

app = QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


@pytest.mark.parametrize("value, text", [(0, "0"), (999, "999"), (1000, "1k"), (34641, "34.6k"),
                                         (120000, "120k"), (1_234_567, "1.2M")])
def test_token_counts_are_abbreviated(value, text):
    assert nmb.short_count(value) == text


@pytest.mark.parametrize("value, text", [(0.0283158, "0.028"), (0.0004, "<0.001"), (1.5, "1.50"), (0.0, "0")])
def test_cost_text(value, text):
    assert nmb.short_cost(value) == text


def test_a_summarized_note_gives_every_item_with_its_exact_value_in_the_tip():
    values = nmb.usage_values("claude-sonnet-5-5", "", 34641, 4, 0.0283158, 9.7)
    assert {k: v[0] for k, v in values.items()} == {"time": "10 秒", "model": "claude-sonnet-5-5", "effort": "",
                                                     "tokens_in": "34.6k", "tokens_out": "4", "cost": "0.028"}
    assert values["tokens_in"][1] == "输入 34,641 tokens" and values["cost"][1] == "这次总结花了 $0.0283（Claude Code 报的）"
    assert values["time"][1] == "Claude Code 读了 9.7 秒" and values["model"][1] == "模型：claude-sonnet-5-5"
    assert nmb.usage_values("x", "high", 1, 2, 0.0, 3)["effort"] == ("high", "思考强度（effort）：high")


def test_an_unsummarized_record_only_has_the_time():
    assert nmb.usage_values("", "", 0, 0, 0.0, 61.4) == {"time": ("61 秒", "Claude Code 读了 61.4 秒")}


def test_english():
    i18n.set_language("en")
    values = nmb.usage_values("claude-sonnet-5-5", "", 34641, 4, 0.0283158, 9.7)
    assert values["time"][0] == "10 s" and values["tokens_in"][1] == "34,641 input tokens"
    assert values["cost"][1] == "Cost of this summary: $0.0283 (as reported by Claude Code)"


def test_icons_are_drawn_in_the_colour_they_are_given():
    def darkest(pixmap):
        image = pixmap.toImage()
        return min(image.pixelColor(x, y).lightness() for y in range(image.height()) for x in range(image.width())
                   if image.pixelColor(x, y).alpha() > 200)

    assert darkest(nmb.meta_icon("cost", "#9a9aa3")) > darkest(nmb.meta_icon("cost", "#6d6d6d")), "黑夜用浅色图标"
    for name in ("saved", "model", "tokens_in", "tokens_out", "effort", "time"):
        pixmap = nmb.meta_icon(name, "#333333", 14, 2.0)
        assert pixmap.width() == 28 and darkest(pixmap) < 128
