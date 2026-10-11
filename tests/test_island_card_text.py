# -*- coding: utf-8 -*-
"""灵动岛展开卡片的两行文字（标题行 / 详情行）：放不下就折行，绝不被卡片边缘裁掉。

实机（2026-10-11）：详情行「dsh-pet-indesktop 项目检查 · 工作中 ｜ DataPipelineLag…」
是不换行、不省略的单行 QLabel，会话标题一长就从右边溢出、显示不全。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QApplication

from pet.config import Config
from pet.dynamic_island import _CAPSULE_HEIGHT, DynamicIsland, wrap_elided

app = QApplication.instance() or QApplication([])

_HEADLINE = "Claude Code · 1 个在干活 · 2 个休息中"
_LONG_DETAIL = "dsh-pet-indesktop 项目检查 · 工作中 ｜ DataPipelineLagIncreaseInvestigation · 休息中 等 3 个"


def _font(px: int = 11) -> QFont:
    font = QFont()
    font.setPixelSize(px)
    return font


def _squash(text: str) -> str:
    return "".join(text.split())


# ---------------------------------------------------------------- 折行

def test_short_text_stays_on_one_line():
    assert wrap_elided("余额 ¥12.34", _font(), 300, 3) == ["余额 ¥12.34"]
    assert wrap_elided("", _font(), 300, 3) == []


def test_long_text_wraps_and_every_line_fits():
    font = _font()
    metrics = QFontMetrics(font)
    width = metrics.horizontalAdvance(_LONG_DETAIL) // 2     # 各平台字体宽度不同：按实测宽度取一半
    lines = wrap_elided(_LONG_DETAIL, font, width, 8)

    assert 1 < len(lines) <= 8
    assert all(metrics.horizontalAdvance(line) <= width for line in lines)
    assert _squash("".join(lines)) == _squash(_LONG_DETAIL), "行数够用就一个字都不丢"


def test_an_unbroken_run_is_broken_anywhere():
    """QLabel 自带换行只在词边界断：一长串路径 / 英文照样溢出。"""
    font = _font()
    metrics = QFontMetrics(font)
    lines = wrap_elided("C:/Users/limin/Github/" + "x" * 120, font, 200, 4)
    assert len(lines) > 1
    assert all(metrics.horizontalAdvance(line) <= 200 for line in lines)


def test_overflow_is_elided_on_the_last_line():
    font = _font()
    metrics = QFontMetrics(font)
    lines = wrap_elided("很长的会话标题 " * 40, font, 200, 2)
    assert len(lines) == 2
    assert lines[-1].endswith("…") and not lines[0].endswith("…")
    assert all(metrics.horizontalAdvance(line) <= 200 for line in lines)


def test_explicit_newlines_are_kept():
    assert wrap_elided("第一行\n第二行", _font(), 300, 3) == ["第一行", "第二行"]


# ---------------------------------------------------------------- 卡片

def _island(tmp_path: Path) -> DynamicIsland:
    cfg = Config(base=tmp_path)
    cfg.set("dynamic_island", {
        "enabled": True, "show_icon": True, "show_name": True, "show_info": True,
        "info_mode": "custom", "custom_text": "测试", "show_status": True,
        "style": "light", "x": 400, "y": 300,
    })
    island = DynamicIsland(cfg)
    island.show()
    return island


def _expand(island) -> None:
    island.expand_card()
    island._finish_animations()
    app.processEvents()


def _text_of_width(island, factor: float) -> str:
    """一段在详情行字体下约等于「卡片可用宽度 × factor」的文字（各平台字体宽度不同，按实测凑）。"""
    label = island._card_tier_label
    label.ensurePolished()
    metrics = QFontMetrics(label.font())
    target = (island._card_width() - 34) * factor
    text, unit = "", "会话标题很长·工作中｜"
    while metrics.horizontalAdvance(text) < target:
        text += unit[len(text) % len(unit)]
    return text


def _assert_card_text_fits(island) -> None:
    for label in (island._card_balance_label, island._card_tier_label, island._card_message_label):
        metrics = QFontMetrics(label.font())
        lines = label.text().split("\n")
        assert all(metrics.horizontalAdvance(line) <= label.width() for line in lines), \
            f"文字比标签宽：{lines} / {label.width()}"
        assert label.height() >= len(lines) * metrics.height(), "折出来的行不能被上下裁掉"
    box = island._card_box
    assert box.geometry().bottom() < island.height(), "卡片内容不能伸出窗口"
    for button in (island._card_toggle_btn, island._card_chat_btn, island._card_settings_btn):
        assert button.geometry().bottom() < box.height(), "按钮不能被挤出卡片"


def test_long_session_detail_is_fully_visible_in_the_card(tmp_path):
    island = _island(tmp_path)
    try:
        _expand(island)
        detail = _text_of_width(island, 1.6)      # 截图里那一行：比卡片宽出一大截
        island.set_balance_info(detail, _HEADLINE)
        island._finish_animations()
        app.processEvents()

        shown = island._card_tier_label.text()
        assert "\n" in shown, "一行放不下：折行"
        assert _squash(shown) == _squash(detail), "被卡片边缘裁掉的后半句必须看得到"
        assert island._card_tier_label.toolTip() == ""
        _assert_card_text_fits(island)
    finally:
        island.deleteLater()


def test_card_grows_when_every_row_is_full_and_shrinks_back(tmp_path, monkeypatch):
    """标题两行 + 详情三行 + 最近消息两行：默认高度装不下就长高，不去挤别的控件。

    默认高度里本来留有余量，装不装得下取决于平台字体的行高；这里把默认高度压到 0，
    让「高度跟着内容走」这条在任何字体下都成立。
    """
    from pet import dynamic_island

    monkeypatch.setattr(dynamic_island, "_CARD_HEIGHT", 0)
    island = _island(tmp_path)
    try:
        _expand(island)
        island.set_balance_info("dsh-pet · 工作中", _HEADLINE)
        island._finish_animations()
        short_height = island.height()
        assert short_height > _CAPSULE_HEIGHT

        island.set_last_message("最近一条消息也很长" * 20)
        headline = _text_of_width(island, 1.0)    # 标题行字号更大：这么长一定折成两行
        island.set_balance_info(_text_of_width(island, 2.6), headline)
        island._finish_animations()
        app.processEvents()
        assert island._card_tier_label.text().count("\n") == 2
        assert island._card_balance_label.text().count("\n") == 1
        assert island.height() > short_height
        _assert_card_text_fits(island)

        island.set_last_message("")
        island.set_balance_info("dsh-pet · 工作中", _HEADLINE)
        island._finish_animations()
        assert island.height() == short_height
    finally:
        island.deleteLater()


def test_headline_with_every_phase_also_fits(tmp_path):
    island = _island(tmp_path)
    try:
        _expand(island)
        island.set_balance_info(
            "work (WSL) · 等你批准", "Claude Code · 12 个等你批准 · 23 个在干活 · 34 个休息中")
        island._finish_animations()
        app.processEvents()
        _assert_card_text_fits(island)
    finally:
        island.deleteLater()


def test_text_too_long_for_the_card_is_elided_with_the_full_text_on_hover(tmp_path):
    island = _island(tmp_path)
    try:
        _expand(island)
        detail = _text_of_width(island, 6.0)
        island.set_balance_info(detail, _HEADLINE)
        island._finish_animations()
        app.processEvents()

        assert island._card_tier_label.text().endswith("…")
        assert island._card_tier_label.toolTip() == detail
        _assert_card_text_fits(island)

        island.set_balance_info("dsh-pet · 工作中", _HEADLINE)
        assert island._card_tier_label.toolTip() == "", "没省略就不挂提示"
    finally:
        island.deleteLater()


def test_long_last_message_takes_at_most_two_lines_and_is_not_clipped(tmp_path):
    """最近消息原来靠「按两行宽度省略 + QLabel 自动换行 + 限高」凑：换行位置对不上时
    会折出第三行，被限高上下裁掉（实机渲染可见半行字）。"""
    island = _island(tmp_path)
    try:
        _expand(island)
        island.set_last_message("最近一条 AI 回复也很长的时候，这一行最多两行，超出的部分省略。" * 4)
        island.set_balance_info(_text_of_width(island, 2.6), _HEADLINE)
        island._finish_animations()
        app.processEvents()

        shown = island._card_message_label.text()
        assert shown.count("\n") == 1 and shown.endswith("…")
        _assert_card_text_fits(island)
    finally:
        island.deleteLater()


def test_session_titles_are_never_parsed_as_rich_text(tmp_path):
    """会话标题是用户输入：带尖括号也按原样显示。"""
    island = _island(tmp_path)
    try:
        island.set_balance_info("<b>fix</b> login · 工作中", _HEADLINE)
        assert island._card_tier_label.text() == "<b>fix</b> login · 工作中"
        from PySide6.QtCore import Qt

        assert island._card_tier_label.textFormat() == Qt.TextFormat.PlainText
    finally:
        island.deleteLater()
