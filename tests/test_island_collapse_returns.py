# -*- coding: utf-8 -*-
"""灵动岛收起卡片要回到展开前的位置（2026-11-06 用户报「岛不见了」）。

根因：卡片比屏幕剩余高度高时，``expand_card`` 的目标矩形被 ``_clamp_rect`` 顶到屏幕
顶边；``collapse_card`` 走 ``_target_rect`` 的普通分支，按**当前左上角**放胶囊，于是
胶囊留在被顶到的位置。实机卡片高 1182、屏高 1280，岛几乎在任何位置展开一次都会跑到
顶边（看起来像消失了）。展开期间别的什么挪过窗口（实机观察到 x 左移、机制未定）
同样会留下来。修法：展开前记住胶囊矩形，收起时回到它（仍按屏幕夹一次）。

用假屏驱动真实的展开 / 夹取 / 收起代码（同 ``test_dynamic_island_multiscreen_release``
的思路），卡片高度直接给定，不赌面板内容与字体度量；动画用 ``_finish_animations``
跳到终点，不用 sleep。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from pet.config import Config
from pet.dynamic_island import DynamicIsland

SCREEN = QRect(0, 0, 1920, 1040)
CARD_HEIGHT = 900          # 比屏幕剩余高度高：展开必被顶到顶边
START = QPoint(1200, 900)  # 屏幕下半部分（盖在任务栏上的典型位置）


def _qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


class _FakeScreen:
    def availableGeometry(self) -> QRect:
        return QRect(SCREEN)

    def geometry(self) -> QRect:
        return QRect(SCREEN)

    def name(self) -> str:
        return "fake"


def _island(tmp_path: Path) -> DynamicIsland:
    _qapp()
    config = Config(tmp_path)
    config.set("dynamic_island", {"enabled": True, "style": "metro", "edge_dock": True, "dock_edge": "none",
                                  "x": START.x(), "y": START.y()})
    island = DynamicIsland(config)
    screen = _FakeScreen()
    island._screen_at = lambda point: screen
    island._current_screen = lambda: screen
    island._card_height = lambda: CARD_HEIGHT
    island.show()
    island.move(START)
    island._finish_animations()
    return island


def _expand_settled(island: DynamicIsland) -> QRect:
    island.expand_card()
    island._finish_animations()
    return island.geometry()


def _collapse_settled(island: DynamicIsland) -> QRect:
    island.collapse_card()
    island._finish_animations()
    return island.geometry()


def test_collapse_returns_to_where_the_capsule_was(tmp_path: Path) -> None:
    island = _island(tmp_path)
    try:
        capsule = island.geometry()
        assert capsule.topLeft() == START
        card = _expand_settled(island)
        assert card.height() > capsule.height() and card.bottom() <= SCREEN.bottom()
        assert card.top() < START.y(), "卡片放不下，展开时应被顶上去"
        assert _collapse_settled(island) == capsule, "收起要回到展开前的胶囊矩形"
        assert island._debug_state()["mode"] == "normal"
    finally:
        island.close()


def test_collapse_undoes_a_move_that_happened_while_expanded(tmp_path: Path) -> None:
    """展开期间窗口被（不是用户拖拽地）挪了，收起仍回展开前的位置。"""
    island = _island(tmp_path)
    try:
        capsule = island.geometry()
        _expand_settled(island)
        island.move(700, island.y())
        assert _collapse_settled(island) == capsule
    finally:
        island.close()


def test_collapse_still_clamps_to_the_screen(tmp_path: Path) -> None:
    """记住的位置如果已经出屏（屏幕布局变了），收起仍按屏幕夹一次。"""
    island = _island(tmp_path)
    try:
        _expand_settled(island)
        island._rest_anchor = QPoint(SCREEN.right() + 500, SCREEN.bottom() + 500)
        rect = _collapse_settled(island)
        assert SCREEN.contains(rect), rect.getRect()
    finally:
        island.close()


def test_dragging_the_card_still_follows_the_cursor(tmp_path: Path) -> None:
    """拖拽起手会先收起卡片：胶囊跟着光标走，不能被「回原位」抢回去。"""
    island = _island(tmp_path)
    try:
        _expand_settled(island)
        grab = QPoint(30, 20)
        press_at = island.pos() + grab
        press = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(grab), QPointF(grab), QPointF(press_at),
                            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        island.mousePressEvent(press)
        far = press_at + QPoint(-400, -300)
        move = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(grab), QPointF(grab), QPointF(far),
                           Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        island.mouseMoveEvent(move)
        assert island._debug_state()["mode"] == "normal"
        assert island.pos() == far - grab, "拖拽中的胶囊应贴着光标"
        assert island._rest_anchor is None, "拖拽起手后不再有「回原位」"
    finally:
        island.close()


def test_position_applied_from_settings_while_expanded_wins(tmp_path: Path) -> None:
    """卡片开着时设置页改了 x/y（_apply_position）：收起落在新位置，不回旧位置。"""
    island = _island(tmp_path)
    try:
        _expand_settled(island)
        island._cfg = {**island._cfg, "x": 300, "y": 200}
        island._apply_position()
        rect = _collapse_settled(island)
        assert rect.topLeft() == QPoint(300, 200), rect.getRect()
    finally:
        island.close()
