# -*- coding: utf-8 -*-
"""灵动岛靠屏幕下半部分时，卡片开在胶囊**上方**，胶囊几乎不动（2026-11-07 用户要求）。

此前卡片永远长在胶囊下面：岛在任务栏上点开，整块窗口被 ``_clamp_rect`` 顶上去 1100 多像素，
胶囊跟着飞到屏幕上半部分，动画一卡一卡。现在 ``expand_card`` 比较两个方向各自夹屏后胶囊要
挪多远，挪得少的那个赢（相同取向下）；卡片在上时胶囊画在窗口底部、``_card_box`` 放在上面、
命中测试与绘制都按 ``_capsule_top()`` 偏移，``_rest_size`` / 行数预算 / 收起回原位都不变。

假屏驱动真实代码；动画用 ``_finish_animations`` 跳到终点。
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from pet.config import Config
from pet.dynamic_island import _CAPSULE_HEIGHT, DynamicIsland

TASKBAR = 48
MAIN = QRect(0, 0, 3072, 1280)
MAIN_WORK = QRect(0, 0, 3072, 1280 - TASKBAR)
PLAIN = QRect(0, 0, 1920, 1040)        # 工作区 = 物理屏
CARD = 900


def _qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


class _FakeScreen:
    def __init__(self, geometry: QRect, available: QRect):
        self._geometry, self._available = QRect(geometry), QRect(available)

    def geometry(self) -> QRect:
        return QRect(self._geometry)

    def availableGeometry(self) -> QRect:
        return QRect(self._available)

    def name(self) -> str:
        return "fake"


def _island(tmp_path: Path, screen: _FakeScreen, start: QPoint, *, card: int = CARD, style: str = "metro") -> DynamicIsland:
    _qapp()
    config = Config(tmp_path)
    config.set("dynamic_island", {"enabled": True, "style": style, "edge_dock": True, "dock_edge": "none",
                                  "x": start.x(), "y": start.y()})
    island = DynamicIsland(config)
    island._screen_at = lambda point: screen
    island._current_screen = lambda: screen
    island._card_height = lambda: card
    island.set_message_count(3)            # 铃铛在：命中测试用
    island.show()
    island.move(start)
    island._finish_animations()
    return island


def _expand(island: DynamicIsland) -> QRect:
    island.expand_card()
    island._finish_animations()
    return island.geometry()


def test_island_on_the_taskbar_opens_the_card_above_and_stays_put(tmp_path):
    start = QPoint(2045, MAIN.bottom() - _CAPSULE_HEIGHT + 1)   # 盖在任务栏上
    island = _island(tmp_path, _FakeScreen(MAIN, MAIN_WORK), start)
    try:
        capsule = island.geometry()
        card = _expand(island)
        assert island._debug_state()["card_above"] is True
        assert card.bottom() == capsule.bottom(), "胶囊不动，卡片往上长"
        assert card.height() == _CAPSULE_HEIGHT + CARD and card.top() >= MAIN.top()
        assert island._card_box.geometry().top() == 0, "卡片容器在胶囊上面"
        assert island._capsule_top() == card.height() - _CAPSULE_HEIGHT
        island.collapse_card()
        island._finish_animations()
        assert island.geometry() == capsule
        assert island._debug_state()["card_above"] is False
    finally:
        island.close()


def test_island_near_the_top_still_opens_downward(tmp_path):
    start = QPoint(500, 100)
    island = _island(tmp_path, _FakeScreen(MAIN, MAIN_WORK), start)
    try:
        card = _expand(island)
        assert island._debug_state()["card_above"] is False
        assert card.topLeft() == start
        assert island._card_box.geometry().top() == _CAPSULE_HEIGHT
        assert island._capsule_top() == 0
    finally:
        island.close()


def test_direction_is_whichever_moves_the_capsule_less(tmp_path):
    """两头都放不下时比位移：y=600 向上只挪 256、向下要挪 460 → 向上；y=300 反过来 → 向下。"""
    screen = _FakeScreen(PLAIN, PLAIN)
    island = _island(tmp_path, screen, QPoint(800, 600))
    try:
        card = _expand(island)
        assert island._debug_state()["card_above"] is True
        assert card.top() == PLAIN.top() and card.bottom() == PLAIN.top() + _CAPSULE_HEIGHT + CARD - 1
    finally:
        island.close()
    island = _island(tmp_path / "b", screen, QPoint(800, 300))
    try:
        card = _expand(island)
        assert island._debug_state()["card_above"] is False
        assert card.top() == PLAIN.bottom() - (_CAPSULE_HEIGHT + CARD) + 1
    finally:
        island.close()


def test_hit_tests_follow_the_capsule_to_the_bottom(tmp_path):
    start = QPoint(2045, MAIN.bottom() - _CAPSULE_HEIGHT + 1)
    island = _island(tmp_path, _FakeScreen(MAIN, MAIN_WORK), start)
    try:
        _expand(island)
        bell = island.message_button_rect()
        assert bell is not None
        shifted = QPointF(bell.center().x(), bell.center().y() + island._capsule_top())
        assert island._message_hit(shifted), "铃铛现在画在窗口底部那 44px 里"
        assert not island._message_hit(bell.center()), "窗口顶部是卡片，不是胶囊"
        block = island._metro_block_at(shifted)
        assert block is None or block in island.metro_blocks()
        assert island._metro_block_at(QPointF(10, 10)) is None
    finally:
        island.close()


def test_refresh_while_open_above_keeps_the_capsule_anchored(tmp_path):
    start = QPoint(2045, MAIN.bottom() - _CAPSULE_HEIGHT + 1)
    island = _island(tmp_path, _FakeScreen(MAIN, MAIN_WORK), start)
    try:
        card = _expand(island)
        island._card_height = lambda: CARD + 120           # 内容变多（比如又来了两条消息）
        island._refresh()
        island._finish_animations()
        grown = island.geometry()
        assert grown.bottom() == card.bottom() and grown.height() == card.height() + 120
    finally:
        island.close()


def test_refresh_during_the_expand_animation_only_retargets(tmp_path):
    """展开动画进行中 app 回推数据（_refresh）：画面上露出的那块不跳到整块，只改动画终点；动画走完落在终点。"""
    start = QPoint(2045, MAIN.bottom() - _CAPSULE_HEIGHT + 1)
    island = _island(tmp_path, _FakeScreen(MAIN, MAIN_WORK), start)
    try:
        capsule = island.geometry()
        island.expand_card()                                    # 动画起步：窗口已到位，画面只露胶囊
        assert island._geo_to is not None
        assert island._panel_rect().height() == _CAPSULE_HEIGHT
        island._card_height = lambda: CARD + 120
        island._refresh()
        assert island._panel_rect().height() < _CAPSULE_HEIGHT + CARD, "动画中不许整块闪现"
        assert island._geo_to.height() == _CAPSULE_HEIGHT + CARD + 120, "终点跟着新尺寸"
        assert island._geo_to.bottom() == capsule.bottom()
        island._finish_animations()
        assert island.geometry().height() == _CAPSULE_HEIGHT + CARD + 120
        assert island.geometry().bottom() == capsule.bottom()
        assert island._panel_rect() == island.rect()
    finally:
        island.close()


def _tick(island: DynamicIsland, dt: float = 0.03) -> None:
    island._anim_last = time.monotonic() - dt
    island._on_anim_tick()


def test_upward_expand_animates_without_moving_the_window(tmp_path):
    """向上展开：窗口一次到位、动画中几何一帧都不改（逐帧上移顶边的层叠窗会先按旧位图显示一帧，胶囊上下跳）；
    画面上露出的那块从胶囊往上长、底边贴着窗口底边，胶囊的像素位置全程不变。"""
    start = QPoint(2045, MAIN.bottom() - _CAPSULE_HEIGHT + 1)
    island = _island(tmp_path, _FakeScreen(MAIN, MAIN_WORK), start)
    try:
        capsule = island.geometry()
        island.expand_card()
        full = island.geometry()
        assert full.height() == _CAPSULE_HEIGHT + CARD and full.bottom() == capsule.bottom(), "窗口一次到位"
        capsule_top = island._capsule_top()
        assert capsule_top == full.height() - _CAPSULE_HEIGHT
        assert not island._card_box.mask().boundingRect().intersects(island._card_box.rect()), "第一帧前卡片全遮"
        heights = []
        for _ in range(4):
            _tick(island)
            assert island.geometry() == full, "动画中窗口不动"
            panel = island._panel_rect()
            assert panel.bottom() == full.height() - 1 and island._capsule_top() == capsule_top
            heights.append(panel.height())
            if island._geo_to is None:
                break
        assert heights == sorted(heights) and heights[0] < heights[-1], heights
        island._finish_animations()
        assert island.geometry() == full and island._panel_rect() == island.rect()
        assert island._card_box.mask().isEmpty(), "动画完遮罩撤掉"
        island.collapse_card()
        assert island.geometry() == full, "收起动画同样不动窗口"
        _tick(island)
        assert island.geometry() == full and island._capsule_top() == capsule_top
        island._finish_animations()
        assert island.geometry() == capsule
    finally:
        island.close()


def test_downward_expand_animates_without_moving_the_window(tmp_path):
    start = QPoint(500, 100)
    island = _island(tmp_path, _FakeScreen(MAIN, MAIN_WORK), start)
    try:
        island.expand_card()
        full = island.geometry()
        assert full.topLeft() == start and full.height() == _CAPSULE_HEIGHT + CARD
        for _ in range(3):
            _tick(island)
            assert island.geometry() == full and island._capsule_top() == 0
            assert island._panel_rect().top() == 0
            if island._geo_to is None:
                break
        island._finish_animations()
        assert island.geometry() == full and island._card_box.mask().isEmpty()
    finally:
        island.close()


def test_dragging_the_capsule_of_an_upward_card_keeps_it_under_the_cursor(tmp_path):
    """卡片在上方时窗口左上角是卡片顶：从胶囊起拖，胶囊要贴着光标走，不能往上跳一个卡片高。"""
    start = QPoint(2045, MAIN.bottom() - _CAPSULE_HEIGHT + 1)
    island = _island(tmp_path, _FakeScreen(MAIN, MAIN_WORK), start)
    try:
        _expand(island)
        assert island._debug_state()["card_above"]
        grab = QPoint(30, island._capsule_top() + 20)          # 按在胶囊上
        press_at = island.pos() + grab
        press = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(grab), QPointF(grab), QPointF(press_at),
                            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        island.mousePressEvent(press)
        far = press_at + QPoint(-300, -200)
        move = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(grab), QPointF(grab), QPointF(far),
                           Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        island.mouseMoveEvent(move)
        assert island._debug_state()["mode"] == "normal" and island.height() == _CAPSULE_HEIGHT
        assert island.pos() == far - QPoint(30, 20), "胶囊左上角 = 光标 − 在胶囊里的抓取点"
    finally:
        island.close()
