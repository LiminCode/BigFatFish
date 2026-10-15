# -*- coding: utf-8 -*-
"""灵动岛上的「通知」：胶囊上的铃铛（简报右边）、卡片里的通知折叠框、中英文案。

纯界面：给岛 / 面板数据，看它画了什么、报了什么。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QFont, QMouseEvent
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet.config import Config
from pet.dynamic_island import DynamicIsland
from pet.island_notification_panel import MAX_VISIBLE_ROWS, ROW_HEIGHT, NotificationPanel, body_lines

app = QApplication.instance() or QApplication([])

WIDTH = 308


def _rows(count: int = 3, **override) -> list[dict]:
    return [{"key": 100 + i, "title": f"#channel-{i}", "app": "Slack", "app_id": "slack!x", "sender": "Ann",
             "message": f"message number {i} " * 6, "ago": f"{i + 1} 分钟前", "unread": i == 0, "in_center": i != 2,
             **override} for i in range(count)]


def _island(tmp_path, *, language: str = "zh") -> DynamicIsland:
    config = Config(tmp_path)
    config.set("ui_language", language)
    config.set("dynamic_island", {"enabled": True, "show_icon": True, "show_name": True, "show_info": True,
                                  "info_mode": "time", "show_status": True, "style": "dark", "x": 100, "y": 100})
    island = DynamicIsland(config)
    island.show()
    return island


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


# ---------------------------------------------------------------- 胶囊上的铃铛

def test_bell_is_hidden_until_a_count_is_given_and_sits_right_of_the_briefing_icon(tmp_path):
    island = _island(tmp_path)
    try:
        base = island._capsule_width()
        assert island.notification_button_rect() is None and island.notification_tooltip() == ""
        island.set_notification_count(0)
        assert island._capsule_width() > base, "铃铛要占自己的一格"
        assert island.briefing_button_rect() is None
        bell_alone = island.notification_button_rect()
        island.set_briefing_state("idle")
        brief, bell = island.briefing_button_rect(), island.notification_button_rect()
        assert brief is not None and bell is not None and bell.left() >= brief.right(), "铃铛排在简报右边，可点区不重叠"
        assert bell.left() > bell_alone.left(), "简报出现后铃铛往右挪"
        island.set_notification_count(None)
        island.set_briefing_state("hidden")
        assert island.notification_button_rect() is None and island._capsule_width() == base
    finally:
        island.deleteLater()
        app.processEvents()


def test_bell_tooltip_count_and_cache_key_follow_the_count(tmp_path):
    island = _island(tmp_path)
    try:
        island.set_notification_count(0)
        assert island.notification_tooltip() == "通知"
        first = island._content_cache()
        island.set_notification_count(3)
        assert island.notification_tooltip() == "通知 · 3 条新的"
        assert island._content_cache() is not first, "未读数变了内容层要重画"
        i18n.set_language("en")
        assert island.notification_tooltip() == "Notifications · 3 new"
        island.set_notification_count(1)
        assert island.notification_tooltip() == "Notifications · 1 new"
    finally:
        island.deleteLater()
        app.processEvents()


def test_clicking_the_bell_expands_the_card_opens_the_panel_and_tells_the_app(tmp_path):
    island = _island(tmp_path)
    try:
        island.set_notification_count(2)
        island.set_notifications(_rows(2), is_open=False)
        events = []
        island.notifications_requested.connect(lambda: events.append("requested"))
        island.notification_toggled.connect(lambda is_open: events.append(("toggled", is_open)))
        rect = island.notification_button_rect()
        pos = QPointF(rect.center())
        press = QMouseEvent(QMouseEvent.Type.MouseButtonPress, pos, pos, island.mapToGlobal(pos.toPoint()),
                            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        release = QMouseEvent(QMouseEvent.Type.MouseButtonRelease, pos, pos, island.mapToGlobal(pos.toPoint()),
                              Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        island.mousePressEvent(press)
        island.mouseReleaseEvent(release)
        assert island.mode == "expanded"
        assert island._notice_panel.is_open() and island._notice_panel.isVisibleTo(island)
        assert events == [("toggled", True), "requested"]
        assert not island._card_collapse_timer.isActive(), "通知框开着时卡片不自动收起"
    finally:
        island.deleteLater()
        app.processEvents()


def test_panel_hidden_when_feature_is_off(tmp_path):
    island = _island(tmp_path)
    try:
        island.set_notifications(_rows(2), visible=False)
        assert island._notice_panel.isHidden()
        island.set_notifications([], visible=True)
        assert not island._notice_panel.isHidden(), "开着但没有通知：表头还在（通知 (0)）"
    finally:
        island.deleteLater()
        app.processEvents()


# ---------------------------------------------------------------- 卡片里的通知框

@pytest.fixture
def panel():
    panel = NotificationPanel()
    panel.set_look(primary="#e5eaf5", secondary="#a0aabe", accent="#40b8ff", width=WIDTH)
    panel.events = []
    panel.toggled.connect(lambda is_open: panel.events.append(("toggled", is_open)))
    panel.activated.connect(lambda key: panel.events.append(("activated", key)))
    panel.action_requested.connect(lambda action, key: panel.events.append((action, key)))
    panel.show()
    yield panel
    panel.deleteLater()
    app.processEvents()


def test_rows_render_title_sender_message_and_unread_bar(panel):
    panel.set_rows(_rows(3))
    rows = panel.row_widgets()
    assert len(rows) == 3 and panel.header_text == "通知 (3) · 收起"
    assert rows[0].title.text().startswith("#channel-0")
    assert rows[0].body.text().startswith("Ann: message number 0")
    assert rows[0].body.text().count("\n") == 1, "正文两行"
    assert rows[0].tile.property("unread") is True and rows[1].tile.property("unread") is False
    assert "#a0aabe" in rows[2].title.styleSheet(), "已不在通知中心里的：名字用次要色"
    assert "#e5eaf5" in rows[0].title.styleSheet()
    assert rows[0].icon.text() == "●", "没有应用图标时用一个点占位"
    assert panel.body.height() == 3 * ROW_HEIGHT
    panel.set_rows(_rows(MAX_VISIBLE_ROWS + 4))
    assert panel.body.height() == MAX_VISIBLE_ROWS * ROW_HEIGHT, "多了在框里滚动"


def test_logo_bytes_become_row_icons(panel):
    from PySide6.QtGui import QPixmap

    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.red)
    from PySide6.QtCore import QBuffer, QIODevice

    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buffer, "PNG")
    panel.set_rows(_rows(1))
    panel.set_logos({"slack!x": bytes(buffer.data())})
    row = panel.row_widgets()[0]
    assert row.icon.pixmap() is not None and not row.icon.pixmap().isNull() and row.icon.text() == ""
    panel.set_logos({"slack!x": b"not a png"})
    assert panel.row_widgets()[0].icon.text() == "●", "坏图标退回占位点"


def test_click_and_menu_report_keys(panel):
    panel.set_rows(_rows(2))
    row = panel.row_widgets()[1]
    center = QPointF(row.rect().center())
    for kind, button, buttons in ((QMouseEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton),
                                  (QMouseEvent.Type.MouseButtonRelease, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)):
        row_event = QMouseEvent(kind, center, center, row.mapToGlobal(center.toPoint()), button, buttons,
                                Qt.KeyboardModifier.NoModifier)
        (row.mousePressEvent if kind == QMouseEvent.Type.MouseButtonPress else row.mouseReleaseEvent)(row_event)
    assert panel.events == [("activated", 101)]
    menu = panel.row_menu(101)
    actions = [a for a in menu.actions() if not a.isSeparator()]
    assert [a.text() for a in actions] == ["跳到这条消息", "移除", "清空"]
    actions[1].trigger()
    assert panel.events[-1] == ("dismiss", 101)
    panel.header.click()
    assert panel.events[-1] == ("toggled", False) and panel.header_text == "通知 (2) · 展开"
    panel.show_status("正在跳到那条消息…")
    assert panel.header.text().startswith("正在跳到")
    menu.deleteLater()


def test_english_header_and_menu(panel):
    i18n.set_language("en")
    panel.set_rows(_rows(2))
    assert panel.header_text == "Notifications (2) · Collapse"
    assert [a.text() for a in panel.row_menu(1).actions() if not a.isSeparator()] == [
        "Jump to this message", "Dismiss", "Clear all"]


def test_body_lines_wraps_cjk_without_spaces_and_elides_the_tail():
    font = QFont()
    font.setPixelSize(10)
    lines = body_lines("甲" * 200, font, 120)
    assert len(lines) == 2 and lines[1].endswith("…") and all(len(line) < 200 for line in lines)
    short = body_lines("hi there", font, 200)
    assert short == ["hi there"]
    assert body_lines("", font, 200) == []
    assert body_lines("alpha beta gamma delta epsilon zeta eta theta iota kappa lambda", font, 90)[0].endswith(("a", "n")), "按空格断行"
    assert QPoint(0, 0) is not None
