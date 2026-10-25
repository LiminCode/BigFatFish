# -*- coding: utf-8 -*-
"""笔记的「基本信息」（记下的时间、模型、tokens、花费、用时）挪到详情底部的一条小信息栏（2026-10-20 用户要求）。

以前这些是正文第二行的一串纯文字（「sonnet · 输入 34,641 / 输出 4 tokens · $0.028 · 10 秒」），和摘要抢地方。现在：

- 正文只留标题、类型、提醒 / 完成、标签——用户真正要看的；
- 详情下面一条不随正文滚动的信息栏，每项一个小图标 + 简短数字：时钟 = 记下的时间、火花 = 模型、
  向下 / 向上箭头 = 输入 / 输出 tokens、美元硬币 = 花费、秒表 = 用时；颜色用次要文字色，不抢眼；
- 数字缩写（34.6k），精确值在悬停提示里；没总结过的笔记只有时间那一项；没选中笔记时整条不出现；
- 白天 / 黑夜切换时图标跟着换色；中英文。
"""
from __future__ import annotations

import datetime as dt
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet import note_meta_bar as nmb
from pet import work_notes as wn
from pet.work_briefing_ui import briefing_tokens
from pet.work_notes_ui import WorkNotesPanel, detail_markdown

app = QApplication.instance() or QApplication([])

NOW = dt.datetime(2026, 10, 15, 19, 40)
LIGHT, DARK = briefing_tokens(False), briefing_tokens(True)


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


def _summarized() -> wn.Note:
    return wn.new_note("https://acme.slack.com/archives/C1/p1\n看一下发布窗口", NOW).replace(
        summary="摘要", details="- 要点", tags=["slack"], remind_at="2026-10-16T09:00:00",
        model="claude-sonnet-5-5", tokens_in=34641, tokens_out=4, cost_usd=0.0283158, seconds=9.7)


@pytest.fixture
def panel():
    panel = WorkNotesPanel(LIGHT)
    panel.resize(900, 560)
    panel.show()
    app.processEvents()
    yield panel
    panel.close()
    panel.deleteLater()
    app.processEvents()


def _texts(bar) -> dict:
    return {chip.key: chip.text.text() for chip in bar.chips() if not chip.isHidden()}


def test_the_body_no_longer_carries_the_usage_line():
    text = detail_markdown(_summarized(), False)
    for gone in ("claude-sonnet-5-5", "34,641", "$0.028", "记于"):
        assert gone not in text, f"「{gone}」挪到底部信息栏了"
    assert "提醒 10-16 09:00" in text and "`slack`" in text and "**摘要**" in text, "要看的还在正文"


def test_a_summarized_note_shows_every_item_with_an_icon_at_the_bottom(panel):
    note = _summarized()
    panel.show_notes([note])
    app.processEvents()
    bar = panel.meta_bar
    assert not bar.isHidden()
    assert _texts(bar) == {"saved": "10-15 19:40", "model": "claude-sonnet-5-5", "tokens_in": "34.6k",
                           "tokens_out": "4", "cost": "0.028", "time": "10 秒"}
    assert [chip.key for chip in bar.chips()] == ["saved", "model", "tokens_in", "tokens_out", "cost", "time"]
    icons = [chip.icon.pixmap().toImage() for chip in bar.chips()]
    assert all(not image.isNull() for image in icons)
    assert len({bytes(image.constBits()) for image in icons}) == 6, "每项一个不同的图标"
    detail_bottom = panel.detail.mapTo(panel, panel.detail.rect().bottomLeft()).y()
    assert bar.mapTo(panel, bar.rect().topLeft()).y() >= detail_bottom, "在详情下面，不随正文滚动"


def test_exact_values_are_in_the_tooltips(panel):
    panel.show_notes([_summarized()])
    tips = {chip.key: chip.toolTip() for chip in panel.meta_bar.chips()}
    assert tips["saved"] == "记于 10-15 19:40"
    assert tips["model"] == "模型：claude-sonnet-5-5"
    assert tips["tokens_in"] == "输入 34,641 tokens" and tips["tokens_out"] == "输出 4 tokens"
    assert tips["cost"] == "这次总结花了 $0.0283（Claude Code 报的）"
    assert tips["time"] == "Claude Code 读了 9.7 秒"
    assert "34,641" in panel.meta_bar.accessibleName(), "读屏也读得到全部"


def test_an_unsummarized_note_only_shows_when_it_was_saved(panel):
    panel.show_notes([wn.new_note("随手记一句", NOW)])
    assert _texts(panel.meta_bar) == {"saved": "10-15 19:40"}


def test_nothing_selected_hides_the_bar(panel):
    panel.show_notes([])
    assert panel.meta_bar.isHidden()


@pytest.mark.parametrize("value, text", [(0, "0"), (999, "999"), (1000, "1k"), (34641, "34.6k"),
                                         (120000, "120k"), (1_234_567, "1.2M")])
def test_token_counts_are_abbreviated(value, text):
    assert nmb.short_count(value) == text


@pytest.mark.parametrize("value, text", [(0.0283158, "0.028"), (0.0004, "<0.001"), (1.5, "1.50"), (0.0, "0")])
def test_cost_text(value, text):
    assert nmb.short_cost(value) == text


def test_icons_follow_the_day_night_theme(panel):
    panel.show_notes([_summarized()])
    cost = next(chip for chip in panel.meta_bar.chips() if chip.key == "cost")

    def darkest(image):
        return min(image.pixelColor(x, y).lightness() for y in range(image.height()) for x in range(image.width())
                   if image.pixelColor(x, y).alpha() > 200)

    light = darkest(cost.icon.pixmap().toImage())
    panel.apply_theme(DARK)
    dark = darkest(cost.icon.pixmap().toImage())
    assert dark > light, "黑夜用浅色图标"


def test_english(panel):
    i18n.set_language("en")
    panel.show_notes([_summarized()])
    tips = {chip.key: chip.toolTip() for chip in panel.meta_bar.chips()}
    assert _texts(panel.meta_bar)["time"] == "10 s"
    assert tips["saved"] == "Saved 10-15 19:40"
    assert tips["cost"] == "Cost of this summary: $0.0283 (as reported by Claude Code)"
    assert tips["tokens_in"] == "34,641 input tokens"


def test_the_slack_page_gets_the_same_bar():
    panel = WorkNotesPanel(DARK, slack=True)
    try:
        panel.show_notes([_summarized()])
        assert not panel.meta_bar.isHidden() and _texts(panel.meta_bar)["cost"] == "0.028"
    finally:
        panel.deleteLater()
        app.processEvents()
