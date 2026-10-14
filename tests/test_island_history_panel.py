# -*- coding: utf-8 -*-
"""灵动岛卡片里的「最近的对话」折叠框（纯界面：给它几行数据，它报用户点了什么）。"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QFontMetrics, QMouseEvent
from PySide6.QtWidgets import QApplication

from pet.island_history_panel import MAX_VISIBLE_ROWS, ROW_HEIGHT, SessionHistoryPanel

app = QApplication.instance() or QApplication([])

WIDTH = 308


def _rows(count: int = 3, **override) -> list[dict]:
    rows = []
    for index in range(count):
        rows.append({
            "key": ("claude", f"sid-{index}"), "label": f"对话 {index}", "where": "终端",
            "path": f"C:\\work\\project-{index}", "ago": f"{index + 1} 小时前", "live": False,
            "default": "terminal", **override})
    return rows


@pytest.fixture
def panel():
    panel = SessionHistoryPanel()
    panel.set_look(primary="#202124", secondary="#62676d", accent="#40b8ff", width=WIDTH)
    panel.events = []
    panel.toggled.connect(lambda is_open: panel.events.append(("toggled", is_open)))
    panel.activated.connect(lambda key: panel.events.append(("activated", key)))
    panel.action_requested.connect(lambda action, key: panel.events.append((action, key)))
    panel.show()
    yield panel
    panel.deleteLater()
    app.processEvents()


def _click(widget, button=Qt.MouseButton.LeftButton) -> None:
    centre = QPointF(widget.rect().center())
    for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
        event = QMouseEvent(kind, centre, QPointF(widget.mapToGlobal(centre.toPoint())),
                            button, button, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(widget, event)


def test_header_counts_the_conversations_and_starts_folded(panel):
    panel.set_rows(_rows(3))
    assert "最近的对话" in panel.header.text() and "3" in panel.header.text()
    assert panel.is_open() is False
    assert panel.body.isHidden(), "默认折着：不占卡片的地方"
    assert panel.sizeHint().height() < ROW_HEIGHT * 2


def test_clicking_the_header_unfolds_and_folds(panel):
    panel.set_rows(_rows(3))
    folded = panel.sizeHint().height()

    panel.header.click()
    assert panel.is_open() and not panel.body.isHidden()
    assert panel.sizeHint().height() >= folded + 3 * ROW_HEIGHT
    panel.header.click()
    assert not panel.is_open() and panel.sizeHint().height() == folded
    assert panel.events == [("toggled", True), ("toggled", False)]


def test_state_can_be_restored_without_echoing_back(panel):
    panel.set_rows(_rows(2))
    panel.set_open(True)
    assert panel.is_open() and panel.events == [], "恢复上次的状态不算用户操作"


def test_long_lists_scroll_instead_of_growing_the_card(panel):
    panel.set_rows(_rows(12))
    panel.set_open(True)
    assert panel.body.height() == MAX_VISIBLE_ROWS * ROW_HEIGHT
    assert len(panel.row_widgets()) == 12


def test_rows_show_title_time_and_where(panel):
    panel.set_rows(_rows(1, label="Fix login loop", where="VS Code", path="C:\\work\\api", ago="昨天"))
    panel.set_open(True)
    (row,) = panel.row_widgets()
    assert row.title.text() == "Fix login loop"
    assert row.ago.text() == "昨天"
    assert row.path.text() == "VS Code · C:\\work\\api"
    assert row.toolTip() == "C:\\work\\api", "悬停看完整路径"


def test_long_text_is_elided_to_the_row(panel):
    long_path = "C:\\Users\\limin\\AppData\\Local\\Temp\\claude\\" + "very-long-folder-name\\" * 6 + "cwd"
    panel.set_rows(_rows(1, label="一个特别特别特别特别特别特别特别特别特别特别长的会话标题", path=long_path))
    panel.set_open(True)
    app.processEvents()
    (row,) = panel.row_widgets()
    for label in (row.title, row.path):
        assert QFontMetrics(label.font()).horizontalAdvance(label.text()) <= label.width() + 1
    assert row.path.text().startswith("终端 · C:\\") and row.path.text().endswith("cwd"), "路径省略中间，两头留着"
    assert row.title.width() + row.ago.width() <= WIDTH


def test_live_sessions_are_marked(panel):
    panel.set_rows(_rows(1, live=True, ago="3 分钟前"))
    panel.set_open(True)
    assert panel.row_widgets()[0].ago.text() == "进行中"


def test_clicking_a_row_activates_it(panel):
    panel.set_rows(_rows(2))
    panel.set_open(True)
    app.processEvents()
    _click(panel.row_widgets()[1])
    assert panel.events == [("activated", ("claude", "sid-1"))]


def test_row_menu_offers_every_way_back(panel):
    panel.set_rows(_rows(1))
    menu = panel.row_menu(("claude", "sid-0"))
    labels = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert labels == ["在终端里恢复", "在 VS Code 里打开", "打开文件夹", "复制路径", "复制恢复命令",
                      "从列表移除", "清空列表"]
    for action in [a for a in menu.actions() if not a.isSeparator()]:
        action.trigger()
    assert [name for name, _key in panel.events] == [
        "terminal", "vscode", "folder", "copy_path", "copy_resume", "remove", "clear"]
    assert all(key == ("claude", "sid-0") for _name, key in panel.events)


def test_right_click_asks_for_the_menu_not_the_default_action(panel):
    panel.set_rows(_rows(1))
    panel.set_open(True)
    app.processEvents()
    asked = []
    panel.popup_row_menu = lambda key, pos: asked.append(key)
    _click(panel.row_widgets()[0], Qt.MouseButton.RightButton)
    assert asked == [("claude", "sid-0")] and panel.events == []


def test_unchanged_rows_are_not_rebuilt(panel):
    panel.set_rows(_rows(3))
    first = panel.row_widgets()
    panel.set_rows(_rows(3))
    assert panel.row_widgets() == first
    panel.set_rows(_rows(3, ago="刚刚"))
    assert [r.ago.text() for r in panel.row_widgets()] == ["刚刚"] * 3


def test_status_line_replaces_the_header_briefly(panel):
    panel.set_rows(_rows(2))
    normal = panel.header.text()
    panel.show_status("已在终端里恢复：对话 0")
    assert panel.header.text() == "已在终端里恢复：对话 0"
    panel._status_timer.timeout.emit()          # 不等真实的几秒
    assert panel.header.text() == normal


def test_empty_list_folds_away(panel):
    panel.set_rows(_rows(2))
    panel.set_open(True)
    panel.set_rows([])
    assert panel.row_widgets() == []
    assert panel.sizeHint().height() < ROW_HEIGHT * 2


def test_dragging_inside_the_list_does_not_count_as_a_click(panel):
    """滚动条 / 拖动误触：按下和抬起不在同一行附近就不算点击。"""
    panel.set_rows(_rows(2))
    panel.set_open(True)
    app.processEvents()
    row = panel.row_widgets()[0]
    press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(10, 10), QPointF(row.mapToGlobal(QPoint(10, 10))),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    release = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(10, 400), QPointF(row.mapToGlobal(QPoint(10, 400))),
                          Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(row, press)
    QApplication.sendEvent(row, release)
    assert panel.events == []


def test_ten_rows_are_visible_by_default_and_the_cap_is_adjustable(panel):
    """5 行太短（实机反馈）：默认露 10 行，可调；超出的照旧在框里滚动。"""
    assert MAX_VISIBLE_ROWS == 10
    panel.set_rows(_rows(14))
    panel.set_open(True)
    assert panel.body.height() == 10 * ROW_HEIGHT

    panel.set_max_visible(4)
    assert panel.body.height() == 4 * ROW_HEIGHT
    panel.set_max_visible(20)
    assert panel.body.height() == 14 * ROW_HEIGHT, "行数不到上限：有几行露几行"
    panel.set_max_visible(0)
    assert panel.body.height() == 1 * ROW_HEIGHT, "至少露一行"
    panel.set_max_visible("x")
    assert panel.body.height() == 10 * ROW_HEIGHT, "给的值不像话就用默认"


# ---------------------------------------------------------------- 卡片样式（2026-10-14：Windows Phone 式的平铺卡片）

def _pixel(widget, x: int, y: int):
    image = widget.grab().toImage()
    return image.pixelColor(min(x, image.width() - 1), min(y, image.height() - 1))


def _icon_pixels(row) -> list:
    image = row.icon.pixmap().toImage()
    return [image.pixelColor(x, y).rgba() for y in range(image.height()) for x in range(image.width())]


def test_each_row_shows_an_icon_for_where_it_was_opened(panel):
    panel.set_rows([
        {**_rows(1)[0], "key": ("claude", "a"), "host": "vscode"},
        {**_rows(1)[0], "key": ("claude", "b"), "host": "terminal"},
        {**_rows(1)[0], "key": ("claude_wsl", "c"), "host": "wsl"},
        {**_rows(1)[0], "key": ("claude", "d"), "host": "script"},
        {**_rows(1)[0], "key": ("claude", "e")},
    ])
    panel.set_open(True)
    app.processEvents()
    rows = panel.row_widgets()
    drawn = [_icon_pixels(row) for row in rows[:4]]
    assert all(any(px & 0xFF000000 for px in pixels) for pixels in drawn), "四种来源都有图标"
    assert len({tuple(pixels) for pixels in drawn}) == 4, "四种来源的图标各不相同"
    assert rows[4].icon.pixmap().isNull() and rows[4].icon.width() == rows[0].icon.width(), \
        "不知道从哪开的：留空位，文字仍对齐"
    assert all(row.title.x() == rows[0].title.x() for row in rows)


def test_header_and_rows_are_painted_as_tiles_not_bare_text(panel):
    panel.set_rows(_rows(2))
    panel.set_open(True)
    app.processEvents()
    header_fill = _pixel(panel.header, 4, panel.header.height() // 2)
    assert header_fill.alpha() > 0, "表头是一块卡片，不是透明底上的字"
    row = panel.row_widgets()[0]
    tile_fill = _pixel(row, row.width() // 2, 4)
    gap_fill = _pixel(row, row.width() // 2, row.height() - 1)
    assert tile_fill.alpha() > 0 and gap_fill.alpha() == 0, "行是一块卡片，卡片之间留缝"
    assert panel.header.font().bold()


def test_a_live_row_carries_an_accent_bar_on_its_left_edge(panel):
    panel.set_rows(_rows(1, live=True))
    panel.set_open(True)
    app.processEvents()
    row = panel.row_widgets()[0]
    bar = _pixel(row, 1, row.height() // 2)
    assert bar.name() == "#40b8ff", "进行中的行左边一道主题色条"
    panel.set_rows(_rows(1, live=False))
    app.processEvents()
    bar = _pixel(panel.row_widgets()[0], 1, ROW_HEIGHT // 2)
    assert bar.name() != "#40b8ff"


def test_tiles_follow_the_island_palette(panel):
    panel.set_rows(_rows(1))
    panel.set_open(True)
    app.processEvents()
    dark_tile = _pixel(panel.row_widgets()[0], 60, 4)
    panel.set_look(primary="#f0f0f5", secondary="#9a9aa3", accent="#40b8ff", width=WIDTH)
    app.processEvents()
    light_tile = _pixel(panel.row_widgets()[0], 60, 4)
    assert dark_tile.lightness() < light_tile.lightness(), "浅字（深底）用浅色卡片，深字（浅底）用深色卡片"
