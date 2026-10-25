# -*- coding: utf-8 -*-
"""灵动岛的 Metro 样式（``dynamic_island.style = "metro"``，2026-10-24 用户要求）。

方角的平条；头像、「今日用量」、连接图标、简报 / 个人助理 / 铃铛各是一块方磁贴，磁贴之间
留一道缝；鼠标停在哪块上，那块就朝光标倾斜（和设置页磁贴同一个 ``tilt_transform``），
按下去倾斜更明显。颜色跟「外观」里的白天 / 黑夜（和简报窗口、仪表盘同一套令牌）。
别的三种样式（黑 / 白 / 玻璃）一点不变。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from pet import modern_settings_dialog as settings_mod
from pet.config import Config
from pet.dynamic_island import DynamicIsland

app = QApplication.instance() or QApplication([])


def _island(tmp_path, style: str = "metro", theme: str = "dark") -> DynamicIsland:
    config = Config(tmp_path)
    config.set("context_menu_appearance", {**dict(config.get("context_menu_appearance") or {}), "theme": theme})
    config.set("dynamic_island", {"enabled": True, "show_icon": True, "show_name": True, "show_info": True,
                                  "info_mode": "usage_today", "show_status": True, "style": style,
                                  "x": 100, "y": 100})
    island = DynamicIsland(config)
    island.set_usage_info("今日 1.50M", "明细")
    island.set_session_counts([("working", "1 工作中")])
    island.set_briefing_state("idle")
    island.set_personal_state("unread")
    island.set_notification_count(2)
    island.show()
    app.processEvents()
    return island


def _move(island, pos: QPointF, buttons=Qt.MouseButton.NoButton) -> None:
    event = QMouseEvent(QEvent.Type.MouseMove, pos, island.mapToGlobal(pos.toPoint()).toPointF(),
                        Qt.MouseButton.NoButton, buttons, Qt.KeyboardModifier.NoModifier)
    island.mouseMoveEvent(event)


def _press(island, pos: QPointF) -> None:
    event = QMouseEvent(QEvent.Type.MouseButtonPress, pos, island.mapToGlobal(pos.toPoint()).toPointF(),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    island.mousePressEvent(event)


# ---------------------------------------------------------------- 配置与设置页

def test_metro_is_a_valid_style_and_unknown_styles_still_fall_back(tmp_path):
    config = Config(tmp_path)
    for raw, expected in (("metro", "metro"), ("nonsense", "dark")):
        config.set("dynamic_island", {**config.get("dynamic_island"), "style": raw})
        config.save()
        assert Config(tmp_path).get("dynamic_island")["style"] == expected


def test_settings_offer_metro_and_save_it(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    dialog = settings_mod.ModernSettingsDialog(Config(tmp_path), include_ai=False)
    try:
        select = dialog.island_style_select
        assert [select.itemData(i) for i in range(select.count())] == ["dark", "light", "glass", "metro"]
        select.setCurrentData("metro")
        dialog.save_button.click()
        assert Config(tmp_path).get("dynamic_island")["style"] == "metro"
    finally:
        dialog._saved_via_button = True
        dialog.deleteLater()
        app.processEvents()


# ---------------------------------------------------------------- 磁贴

def test_every_icon_is_a_square_block_with_a_gap_between(tmp_path):
    island = _island(tmp_path)
    try:
        blocks = island.metro_blocks()
        assert list(blocks) == ["icon", "usage", "link", "briefing", "personal", "bell"]
        for name in ("icon", "link", "briefing", "personal", "bell"):
            assert blocks[name].width() == blocks[name].height() == 28, name
        ordered = sorted(blocks.values(), key=lambda rect: rect.left())
        for left, right in zip(ordered, ordered[1:]):
            assert right.left() - left.right() >= 2, "磁贴之间留缝，不粘在一起"
        assert all(rect.right() <= island.width() - 6 for rect in ordered), "都在胶囊里"
    finally:
        island.deleteLater()


def test_clickable_blocks_keep_their_buttons(tmp_path):
    island = _island(tmp_path)
    try:
        blocks = island.metro_blocks()
        for name, rect in (("briefing", island.briefing_button_rect()), ("personal", island.personal_button_rect()),
                           ("bell", island.notification_button_rect()), ("usage", island.usage_rect())):
            assert rect.contains(blocks[name].center()), name
            assert not rect.intersects(blocks["icon"]), "可点区不跨到别的磁贴上"
    finally:
        island.deleteLater()


def test_hovering_a_block_tilts_it_toward_the_cursor_and_pressing_tilts_more(tmp_path):
    island = _island(tmp_path)
    try:
        bell = island.metro_blocks()["bell"]
        _move(island, QPointF(bell.right() - 2, bell.center().y()))
        assert island.metro_hover() == "bell"
        hover_tilt = island.metro_tilt("bell")
        assert not hover_tilt.isIdentity()
        assert island.metro_tilt("briefing").isIdentity(), "只有鼠标下的那块倾斜"

        _press(island, QPointF(bell.right() - 2, bell.center().y()))
        pressed = island.metro_tilt("bell")
        assert pressed != hover_tilt

        island.leaveEvent(QEvent(QEvent.Type.Leave))
        assert island.metro_hover() is None and island.metro_tilt("bell").isIdentity()
    finally:
        island.deleteLater()


def test_paints_square_corners_in_metro_and_round_ones_otherwise(tmp_path):
    metro = _island(tmp_path / "m")
    dark = _island(tmp_path / "d", style="dark")
    try:
        corner = QPoint(7, 7)                           # 内缩 6px 之后的左上角
        assert metro.grab().toImage().pixelColor(corner).alpha() > 200, "方角：角上有底色"
        assert dark.grab().toImage().pixelColor(corner).alpha() < 60, "圆角胶囊：角上是透明的"
        bell = metro.metro_blocks()["bell"]
        _move(metro, QPointF(bell.right() - 2, bell.top() + 2))
        metro.grab()                                     # 倾斜中的那块照样画得出来
    finally:
        metro.deleteLater()
        dark.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("theme, page", [("dark", "#1b1b1f"), ("light", "#f2f2f2")])
def test_metro_follows_the_day_night_theme(tmp_path, theme, page):
    island = _island(tmp_path, theme=theme)
    try:
        background, _primary, _secondary = island._style_palette()
        assert background.name() == page
    finally:
        island.deleteLater()


def test_other_styles_have_no_blocks(tmp_path):
    island = _island(tmp_path, style="dark")
    try:
        assert island.metro_blocks() == {}
        bell = island.notification_button_rect()
        _move(island, bell.center())
        assert island.metro_hover() is None
    finally:
        island.deleteLater()
