# -*- coding: utf-8 -*-
"""灵动岛展开的卡片要整块放进所在屏幕的工作区（2026-11-06）。

实机卡片高 1182（消息记录 6 行 × 58 + 最近的对话 10 行 × 40 + 标题 / 按钮），主屏 1280 高、
工作区 1232：展开被 ``_clamp_rect`` 顶到屏幕顶边；1080 高的屏直接截掉卡片底部。修法：
卡片（胶囊 44 + 内容）总高按屏幕工作区算上限，放不下时先压两个折叠框的可见行数（哪个
更高先压哪个，各自最少 ``_CARD_FIT_MIN_ROWS`` 行，多出的在框里滚动）。卡片开在胶囊下方时夹屏按
工作区（卡片是阅读面，不盖任务栏）；岛靠屏幕下半部分时卡片开在胶囊**上方**、胶囊原地不动
（``test_island_card_opens_upward``），那时只要求卡片顶边不出工作区、整块在物理屏内。行数在展开、
折叠框开合、换屏时都重算。

用假屏驱动真实的展开 / 夹取 / 面板代码，面板里塞真实的行（不给定卡片高度）；动画用
``_finish_animations`` 跳到终点。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication

from pet import island_history_panel, island_message_panel
from pet.config import Config
from pet.dynamic_island import _CAPSULE_HEIGHT, _CARD_FIT_MIN_ROWS, _CARD_SCREEN_MARGIN, DynamicIsland

TASKBAR = 48
SHORT = QRect(0, 0, 1366, 768)                       # 老笔记本
SHORT_WORK = QRect(0, 0, 1366, 768 - TASKBAR)
MAIN = QRect(0, 0, 3072, 1280)                       # 实机主屏
MAIN_WORK = QRect(0, 0, 3072, 1280 - TASKBAR)
TALL = QRect(0, 0, 2160, 3840)                       # 竖屏：什么都放得下
TALL_WORK = QRect(TALL)
MESSAGES, HISTORY = 50, 13


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


def _messages(count: int) -> list[dict]:
    return [{"key": 100 + i, "title": f"修登录循环 {i}", "text": f"Claude Code 干完活啦，去看看成果吧～ 第 {i} 轮 " * 3,
             "subtitle": "", "ago": f"{i + 1} 分钟前", "unread": i == 0, "host": "vscode", "where": "VS Code",
             "path": "C:/repo", "session": True, "kind": "bubble"} for i in range(count)]


def _history(count: int) -> list[dict]:
    return [{"key": ("claude", f"sid-{i}"), "label": f"对话 {i}", "where": "终端", "host": "terminal",
             "path": f"C:\\p{i}", "ago": "昨天", "live": False} for i in range(count)]


class _Harness:
    def __init__(self, tmp_path: Path, screen: _FakeScreen, start: QPoint):
        _qapp()
        config = Config(tmp_path)
        config.set("dynamic_island", {"enabled": True, "style": "metro", "edge_dock": True, "dock_edge": "none",
                                      "x": start.x(), "y": start.y()})
        self.island = DynamicIsland(config)
        self.screen = screen
        self.island._screen_at = lambda point: self.screen
        self.island._current_screen = lambda: self.screen
        self.island.set_messages(_messages(MESSAGES), is_open=True)
        self.island.set_session_history(_history(HISTORY), is_open=True)
        self.island.show()
        self.island.move(start)
        self.island._finish_animations()

    def expand(self) -> QRect:
        self.island.expand_card()
        self.island._finish_animations()
        return self.island.geometry()

    def settle(self) -> QRect:
        self.island._finish_animations()
        return self.island.geometry()

    def rows(self) -> tuple[int, int]:
        return self.island._message_panel.visible_rows(), self.island._history_panel.visible_rows()

    def close(self) -> None:
        self.island.close()


@pytest.fixture
def short(tmp_path):
    h = _Harness(tmp_path, _FakeScreen(SHORT, SHORT_WORK), QPoint(900, 600))
    yield h
    h.close()


def _assert_inside(island: DynamicIsland, screen: QRect, work: QRect) -> None:
    rect = island.geometry()
    assert rect.height() <= work.height() - 2 * _CARD_SCREEN_MARGIN or island._debug_state()["mode"] != "expanded"
    if island._debug_state()["card_above"]:
        # 卡片在胶囊上方：胶囊留在原地（可能在任务栏上），卡片顶边不出工作区、整块在物理屏内
        assert rect.top() >= work.top(), f"卡片顶边 {rect.top()} 出了工作区"
        assert rect.bottom() <= screen.bottom(), f"卡片底边 {rect.bottom()} 出了屏幕"
    else:
        assert rect.bottom() <= work.bottom(), f"卡片底边 {rect.bottom()} 超出工作区 {work.bottom()}"
        assert rect.top() > work.top(), f"卡片被顶到顶边 y={rect.top()}"


def test_short_screen_card_stays_inside_the_work_area(short):
    short.expand()
    _assert_inside(short.island, SHORT, SHORT_WORK)
    msg_rows, hist_rows = short.rows()
    assert _CARD_FIT_MIN_ROWS <= msg_rows < island_message_panel.MAX_VISIBLE_ROWS
    assert _CARD_FIT_MIN_ROWS <= hist_rows < island_history_panel.MAX_VISIBLE_ROWS
    panel = short.island._message_panel
    assert panel.body.height() == msg_rows * island_message_panel.ROW_HEIGHT, "多出的行在框里滚动"
    assert short.island._debug_state()["mode"] == "expanded"


def test_rows_come_back_when_a_panel_is_folded(short):
    short.expand()
    squeezed = short.rows()
    short.island._message_panel._on_header_clicked()          # 用户折起「消息记录」
    short.settle()
    _assert_inside(short.island, SHORT, SHORT_WORK)
    assert short.rows()[1] > squeezed[1], "消息框折起来，让出的高度还给「最近的对话」"
    short.island._message_panel._on_header_clicked()          # 再展开：重新分配
    short.settle()
    _assert_inside(short.island, SHORT, SHORT_WORK)
    assert short.rows() == squeezed


def test_rows_follow_the_screen_the_island_is_on(short):
    short.expand()
    assert short.rows()[1] < island_history_panel.MAX_VISIBLE_ROWS
    short.screen = _FakeScreen(TALL, TALL_WORK)              # 岛被挪到了竖屏上
    short.island._refresh()
    short.settle()
    assert short.rows() == (island_message_panel.MAX_VISIBLE_ROWS, island_history_panel.MAX_VISIBLE_ROWS), \
        "放得下就露配置的行数，不留着矮屏的压缩"
    short.screen = _FakeScreen(SHORT, SHORT_WORK)
    short.island._refresh()
    short.settle()
    _assert_inside(short.island, SHORT, SHORT_WORK)


def test_main_screen_island_on_the_taskbar_stays_put_and_opens_upward(tmp_path):
    """实机：岛盖在任务栏上（y=1236），卡片开在它上方、胶囊不动，收起仍在任务栏上。"""
    start = QPoint(2045, MAIN.bottom() - _CAPSULE_HEIGHT + 1)
    h = _Harness(tmp_path, _FakeScreen(MAIN, MAIN_WORK), start)
    try:
        card = h.expand()
        _assert_inside(h.island, MAIN, MAIN_WORK)
        assert h.island._debug_state()["card_above"] and card.bottom() == MAIN.bottom(), "胶囊留在任务栏上"
        h.island.collapse_card()
        assert h.settle().topLeft() == start, "收起仍回展开前的位置（PR #25 的语义不变）"
    finally:
        h.close()


def test_tall_screen_keeps_the_configured_rows(tmp_path):
    h = _Harness(tmp_path, _FakeScreen(TALL, TALL_WORK), QPoint(500, 2000))
    try:
        h.expand()
        assert h.rows() == (island_message_panel.MAX_VISIBLE_ROWS, island_history_panel.MAX_VISIBLE_ROWS)
    finally:
        h.close()


def test_panels_never_go_below_the_minimum_rows(tmp_path):
    """屏幕矮到两框都压到底还放不下：行数停在下限，卡片整块仍在屏内（夹取兜底）。"""
    tiny = QRect(0, 0, 1280, 360)
    h = _Harness(tmp_path, _FakeScreen(tiny, tiny), QPoint(300, 300))
    try:
        rect = h.expand()
        assert h.rows() == (_CARD_FIT_MIN_ROWS, _CARD_FIT_MIN_ROWS)
        assert rect.top() == tiny.top(), "放不下就顶到顶边，这是兜底"
    finally:
        h.close()
