# -*- coding: utf-8 -*-
"""Metro 通知弹窗：摆放（四个角 × 哪块屏）、叠放、排队、到点消失、点击 / 关闭 / 划走。

动画时长在测试里设成 0，计时器直接触发——测的是叠放和状态，不是时序。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from pet import notification_center as nc
from pet import notification_toast as nt

app = QApplication.instance() or QApplication([])


def _notice(uid: int, **over) -> nc.Notice:
    base = dict(uid=uid, app="Demo App", app_id="Demo.App!App", title=f"Title {uid}", body=f"Body text {uid}",
                created=1_700_000_000.0 + uid)
    base.update(over)
    return nc.Notice(**base)


# ---------------------------------------------------------------- 配置
def test_normalize_fills_defaults_and_clamps():
    assert nt.normalize(None) == nt.DEFAULTS
    out = nt.normalize({"corner": "nowhere", "screen": "  ", "seconds": 999, "max_visible": 0, "theme": "x"})
    assert out == {**nt.DEFAULTS, "seconds": nt.SECONDS_RANGE[1], "max_visible": nt.MAX_VISIBLE_RANGE[0]}
    kept = nt.normalize({"corner": "bottom_left", "screen": r"\\.\DISPLAY2", "seconds": "8", "theme": "dark"})
    assert (kept["corner"], kept["screen"], kept["seconds"], kept["theme"]) == ("bottom_left", r"\\.\DISPLAY2", 8, "dark")


# ---------------------------------------------------------------- 摆放（纯函数）
AREA = QRect(100, 50, 1000, 400)        # 屏幕可用区：x 100..1099，y 50..449


@pytest.mark.parametrize("corner, first, second", [
    ("top_right", QPoint(1099 - 16 - 300 + 1, 50 + 16), QPoint(1099 - 16 - 300 + 1, 50 + 16 + 80 + 8)),
    ("top_left", QPoint(100 + 16, 50 + 16), QPoint(100 + 16, 50 + 16 + 80 + 8)),
    ("bottom_right", QPoint(1099 - 16 - 300 + 1, 450 - 16 - 80), QPoint(1099 - 16 - 300 + 1, 450 - 16 - 80 - 8 - 100)),
    ("bottom_left", QPoint(100 + 16, 450 - 16 - 80), QPoint(100 + 16, 450 - 16 - 80 - 8 - 100)),
])
def test_stack_positions_start_at_the_corner_and_grow_away_from_it(corner, first, second):
    positions = nt.stack_positions(AREA, corner, 300, [80, 100], margin=16, gap=8)
    assert positions == [first, second], "最新的贴着角，旧的往远离角的方向排"


def test_stack_positions_stop_when_the_screen_is_full():
    positions = nt.stack_positions(AREA, "top_right", 300, [150, 150, 150], margin=16, gap=8)
    assert len(positions) == 2, "第三张放不下就不给位置（留在队列里）"
    assert nt.stack_positions(AREA, "top_right", 300, [1000], margin=16, gap=8) == [QPoint(784, 66)], \
        "第一张再高也要给位置，不然一条都弹不出来"


class _Screen:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


def test_resolve_screen_by_name_cursor_or_primary():
    a, b, c = _Screen("A"), _Screen("B"), _Screen("C")
    assert nt.resolve_screen("B", [a, b, c], primary=a) is b
    assert nt.resolve_screen("gone", [a, b, c], primary=a) is a, "拔掉的屏退回主屏"
    assert nt.resolve_screen("primary", [a, b, c], primary=a) is a
    assert nt.resolve_screen("cursor", [a, b, c], primary=a, cursor=c) is c
    assert nt.resolve_screen("cursor", [a, b, c], primary=a, cursor=None) is a


def test_wrap_lines_elides_the_last_line():
    from PySide6.QtGui import QFont
    font = QFont()
    font.setPixelSize(13)
    lines = nt.wrap_lines("word " * 200, font, 200, 2)
    assert len(lines) == 2 and lines[-1].endswith("…")
    assert nt.wrap_lines("short", font, 200, 2) == ["short"]
    assert nt.wrap_lines("", font, 200, 2) == []


# ---------------------------------------------------------------- 叠放（Qt）
@pytest.fixture
def stack():
    s = nt.ToastStack(animate=False)
    s.apply_settings({"corner": "top_right", "screen": "primary", "seconds": 5, "max_visible": 3})
    yield s
    s.clear()
    app.processEvents()


def _area(stack):
    return stack.target_screen().availableGeometry()


def test_pushed_toasts_stack_from_the_chosen_corner(stack):
    for uid in (1, 2, 3):
        stack.push(_notice(uid))
    cards = stack.visible_cards()
    assert [c.notice.uid for c in cards] == [3, 2, 1], "最新的在最前（贴着角）"
    expected = nt.stack_positions(_area(stack), "top_right", nt.CARD_WIDTH, [c.height() for c in cards])
    assert [c.pos() for c in cards] == expected
    assert all(c.isVisible() for c in cards)


def test_more_than_max_visible_waits_and_shows_when_one_leaves(stack):
    for uid in (1, 2, 3, 4):
        stack.push(_notice(uid))
    assert [c.notice.uid for c in stack.visible_cards()] == [4, 3, 2]
    assert stack.queued_count() == 1
    stack.visible_cards()[0].dismiss("closed")
    app.processEvents()
    assert [c.notice.uid for c in stack.visible_cards()] == [3, 2, 1], "排队的补上来，剩下的往角那边挪"
    assert stack.queued_count() == 0


def test_expiry_dismisses_and_hover_pauses(stack):
    dismissed = []
    stack.dismissed.connect(lambda notice, reason: dismissed.append((notice.uid, reason)))
    stack.push(_notice(1))
    card = stack.visible_cards()[0]
    card.set_hovered(True)
    assert not card.timer_active(), "鼠标停着就不倒计时"
    card.set_hovered(False)
    assert card.timer_active()
    card.expire_now()
    app.processEvents()
    assert dismissed == [(1, "expired")]
    assert stack.visible_cards() == []


def test_click_activates_and_close_box_only_closes(stack):
    activated, dismissed = [], []
    stack.activated.connect(lambda notice: activated.append(notice.uid))
    stack.dismissed.connect(lambda notice, reason: dismissed.append((notice.uid, reason)))
    stack.push(_notice(1))
    stack.push(_notice(2))
    first, second = stack.visible_cards()
    QTest.mouseClick(first, Qt.MouseButton.LeftButton, pos=first.rect().center())
    app.processEvents()
    assert activated == [2] and dismissed == [(2, "activated")]
    QTest.mouseClick(second, Qt.MouseButton.LeftButton, pos=second.close_rect().center())
    app.processEvents()
    assert activated == [2] and dismissed[-1] == (1, "closed")


def test_swipe_toward_the_edge_dismisses(stack):
    dismissed = []
    stack.dismissed.connect(lambda notice, reason: dismissed.append(reason))
    stack.push(_notice(1))
    card = stack.visible_cards()[0]
    y = card.height() // 2
    QTest.mousePress(card, Qt.MouseButton.LeftButton, pos=QPoint(20, y))
    QTest.mouseMove(card, QPoint(20 + nt.CARD_WIDTH // 2, y))
    QTest.mouseRelease(card, Qt.MouseButton.LeftButton, pos=QPoint(20 + nt.CARD_WIDTH // 2, y))
    app.processEvents()
    assert dismissed == ["swiped"]


def test_changing_corner_moves_visible_cards(stack):
    stack.push(_notice(1))
    stack.apply_settings({"corner": "bottom_left"})
    card = stack.visible_cards()[0]
    assert card.pos() == nt.stack_positions(_area(stack), "bottom_left", nt.CARD_WIDTH, [card.height()])[0]


def test_same_uid_is_not_shown_twice(stack):
    stack.push(_notice(1))
    stack.push(_notice(1))
    assert len(stack.visible_cards()) == 1
