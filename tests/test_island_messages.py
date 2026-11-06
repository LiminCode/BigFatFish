# -*- coding: utf-8 -*-
"""灵动岛上的「消息记录」：胶囊上的铃铛、卡片里的消息折叠框、AppShell 的接线（记录 → 行、点一行 → 切会话）。

面板与岛是纯界面：给数据，看它画了什么、报了什么。接线用 ``AppShell.__new__`` 的最小桩 +
真 ``MessageLog`` / 真 ``SessionHistory``，只有会话登记表 / 跳窗是替身。
"""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet.app import AppShell
from pet.claude_session_history import HISTORY_FILE, SessionHistory
from pet.config import Config
from pet.dynamic_island import DynamicIsland
from pet.island_message_panel import MAX_VISIBLE_ROWS, ROW_HEIGHT, MessagePanel, row_body, row_title
from pet.message_log import LOG_FILE, MessageLog
from pet.session_history_service import SessionHistoryService
from tests.test_island_shell_wiring import _teardown_shell

app = QApplication.instance() or QApplication([])

WIDTH = 308


def _rows(count: int = 3, **override) -> list[dict]:
    return [{"key": 100 + i, "title": f"修登录循环 {i}", "text": f"Claude Code 干完活啦，去看看成果吧～ 第 {i} 轮 " * 3,
             "subtitle": "", "ago": f"{i + 1} 分钟前", "unread": i == 0, "host": "vscode", "where": "VS Code",
             "path": "C:/repo", "session": True, "kind": "bubble", **override} for i in range(count)]


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


def _click(widget, pos: QPointF, button=Qt.MouseButton.LeftButton) -> None:
    press = QMouseEvent(QMouseEvent.Type.MouseButtonPress, pos, pos, widget.mapToGlobal(pos.toPoint()),
                        button, button, Qt.KeyboardModifier.NoModifier)
    release = QMouseEvent(QMouseEvent.Type.MouseButtonRelease, pos, pos, widget.mapToGlobal(pos.toPoint()),
                          button, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    widget.mousePressEvent(press)
    widget.mouseReleaseEvent(release)


# ---------------------------------------------------------------- 胶囊上的铃铛

def test_bell_tooltip_says_messages_and_follows_the_count(tmp_path):
    island = _island(tmp_path)
    try:
        assert island.message_button_rect() is None and island.message_tooltip() == ""
        island.set_message_count(0)
        assert island.message_tooltip() == "消息记录" and island.message_button_rect() is not None
        island.set_message_count(3)
        assert island.message_tooltip() == "消息记录 · 3 条新的"
        i18n.set_language("en")
        assert island.message_tooltip() == "Messages · 3 new"
        island.set_message_count(1)
        assert island.message_tooltip() == "Messages · 1 new"
    finally:
        island.deleteLater()
        app.processEvents()


def test_clicking_the_bell_expands_the_card_opens_the_panel_and_tells_the_app(tmp_path):
    island = _island(tmp_path)
    try:
        island.set_message_count(2)
        island.set_messages(_rows(2), is_open=False)
        events = []
        island.messages_requested.connect(lambda: events.append("requested"))
        island.message_toggled.connect(lambda is_open: events.append(("toggled", is_open)))
        _click(island, QPointF(island.message_button_rect().center()))
        assert island.mode == "expanded"
        assert island._message_panel.is_open() and island._message_panel.isVisibleTo(island)
        assert events == [("toggled", True), "requested"]
        assert not island._card_collapse_timer.isActive(), "消息框开着时卡片不自动收起"
    finally:
        island.deleteLater()
        app.processEvents()


def test_panel_hidden_when_there_is_no_log(tmp_path):
    island = _island(tmp_path)
    try:
        island.set_messages(_rows(2), visible=False)
        assert island._message_panel.isHidden()
        island.set_messages([], visible=True)
        assert not island._message_panel.isHidden(), "有记录服务但还没有消息：表头还在（消息记录 (0)）"
    finally:
        island.deleteLater()
        app.processEvents()


# ---------------------------------------------------------------- 卡片里的消息框

@pytest.fixture
def panel():
    panel = MessagePanel()
    panel.set_look(primary="#e5eaf5", secondary="#a0aabe", accent="#40b8ff", width=WIDTH)
    panel.events = []
    panel.toggled.connect(lambda is_open: panel.events.append(("toggled", is_open)))
    panel.activated.connect(lambda key: panel.events.append(("activated", key)))
    panel.action_requested.connect(lambda action, key: panel.events.append((action, key)))
    panel.show()
    yield panel
    panel.deleteLater()
    app.processEvents()


def test_rows_show_the_chat_title_the_bubble_text_and_the_unread_bar(panel):
    panel.set_rows(_rows(3))
    rows = panel.row_widgets()
    assert len(rows) == 3 and panel.header_text == "消息记录 (3) · 收起"
    assert rows[0].title.text().startswith("修登录循环 0")
    assert rows[0].body.text().startswith("Claude Code 干完活啦")
    assert rows[0].body.text().count("\n") == 1, "正文两行"
    assert rows[0].tile.property("unread") is True and rows[1].tile.property("unread") is False
    assert rows[0].icon.pixmap() is not None and not rows[0].icon.pixmap().isNull(), "来源图标（VS Code）"
    assert "VS Code · C:/repo" in rows[0].toolTip() and "修登录循环 0" in rows[0].toolTip()
    assert panel.body.height() == 3 * ROW_HEIGHT
    panel.set_rows(_rows(MAX_VISIBLE_ROWS + 4))
    assert panel.body.height() == MAX_VISIBLE_ROWS * ROW_HEIGHT, "多了在框里滚动"


def test_pet_rows_are_titled_big_fat_fish_and_join_the_subtitle(panel):
    panel.set_rows([{"key": 1, "title": "", "text": "Slack 上有 3 条需要你看", "subtitle": "Slack · 3 条需要你看",
                     "ago": "刚刚", "unread": True, "host": "", "session": False, "kind": "alert"}])
    row = panel.row_widgets()[0]
    assert row.title.text() == "大肥鱼"
    assert row.body.text().startswith("Slack 上有 3 条需要你看 · Slack")
    assert row.icon.pixmap() is not None and not row.icon.pixmap().isNull(), "大肥鱼的消息画一条小鱼"
    assert row_title({"title": ""}) == "大肥鱼" and row_body({"text": "a", "subtitle": "b"}) == "a · b"
    assert [a.text() for a in panel.row_menu(1).actions() if not a.isSeparator()] == ["移除", "清空"], "没有可去的对话"


def test_click_and_menu_report_keys(panel):
    panel.set_rows(_rows(2))
    row = panel.row_widgets()[1]
    _click(row, QPointF(row.rect().center()))
    assert panel.events == [("activated", 101)]
    menu = panel.row_menu(101)
    actions = [a for a in menu.actions() if not a.isSeparator()]
    assert [a.text() for a in actions] == ["切到这个对话", "移除", "清空"]
    actions[1].trigger()
    assert panel.events[-1] == ("dismiss", 101)
    panel.header.click()
    assert panel.events[-1] == ("toggled", False) and panel.header_text == "消息记录 (2) · 展开"
    panel.show_status("正在切到这个对话…")
    assert panel.header.text().startswith("正在切到")
    menu.deleteLater()


def test_english_header_and_menu(panel):
    i18n.set_language("en")
    panel.set_rows(_rows(2))
    assert panel.header_text == "Messages (2) · Collapse"
    assert [a.text() for a in panel.row_menu(100).actions() if not a.isSeparator()] == [
        "Switch to this chat", "Dismiss", "Clear all"]


def test_message_menu_uses_the_same_opaque_island_menu_style(panel):
    panel.set_rows(_rows(1))
    menu = panel.row_menu(100)
    assert menu.property("menuStyle") == "modern" and menu.property("modernDark") is True
    assert "background-color: #252525" in menu.styleSheet()
    menu.deleteLater()


# ---------------------------------------------------------------- AppShell 接线

class _Registry:
    def __init__(self, sessions) -> None:
        self._sessions = list(sessions)

    def sessions(self):
        return list(self._sessions)

    def describe(self, key):
        for info in self._sessions:
            if (info["agent"], info["sessionId"]) == key:
                return dict(info)
        return None


class _Jumper:
    def __init__(self) -> None:
        self.jumped: list = []

    def jump_key(self, key) -> bool:
        self.jumped.append(key)
        return True


def _shell(tmp_path, *, sessions=(), history_entries=()):
    cfg = Config(base=tmp_path)
    cfg.set("dynamic_island", {"enabled": True, "x": 400, "y": 300})
    shell = AppShell.__new__(AppShell)
    shell.config = cfg
    shell.island = None
    shell.island_collision = None
    shell.instance = None
    shell._instances = []
    store = SessionHistory(Path(cfg.dir) / HISTORY_FILE)
    for agent, sid, fields in history_entries:
        store.record(agent, sid, **fields)
    history = SessionHistoryService(store)
    shell._sync_dynamic_island()
    # 建岛之后再挂：这里只要 AppShell 读会话登记表 / 最近的对话 / 跳窗的那几面，不要整只 overlay 壳
    shell._overlay_shell = SimpleNamespace(session_pets=_Registry(sessions), session_history=history,
                                           session_actions=_Jumper(), message_sink=None,
                                           overlay=SimpleNamespace(isVisible=lambda: False))
    shell._start_message_log()
    return shell


def _close(shell) -> None:
    service = getattr(shell, "_notifications", None)
    if service is not None:
        service.stop()
    _teardown_shell(shell)


_LIVE = {"agent": "claude", "sessionId": "abcdefgh-1234", "phase": "working", "title": "", "project": "repo",
         "cwd": "C:/code/repo", "entrypoint": "cli"}


def test_recorded_bubbles_reach_the_island_with_the_chat_title_and_source(tmp_path):
    shell = _shell(tmp_path, sessions=[_LIVE], history_entries=[
        ("claude_wsl", "11111111-aaaa", {"title": "Ubuntu 里修 CI", "cwd": "/home/me/ci", "entrypoint": "claude-vscode"})])
    try:
        assert shell._overlay_shell.message_sink == shell._record_message, "壳的气泡口接到了记录上"
        sink = shell._overlay_shell.message_sink
        sink("Claude Code 干完活啦", "", "bubble", {"agent": "claude", "session_id": "abcdefgh-1234", "name": "Claude Code"})
        sink("WSL 那边需要你批准", "", "alert", {"agent": "claude_wsl", "session_id": "11111111-aaaa", "name": "Claude Code (WSL)"})
        sink("Slack 上有 2 条需要你看", "Slack · 2 条需要你看", "alert", None)
        sink("DSH 开始干活啦", "", "bubble", {"agent": "dsh", "session_id": "dsh-1", "name": "DSH"})
        sink("新会话还没登记", "", "bubble", {"agent": "claude", "session_id": "99999999-zzzz", "name": "Claude Code"})
        rows = shell.island._message_panel._rows
        assert [r["title"] for r in rows] == ["Claude Code", "DSH", "", "Ubuntu 里修 CI", "repo"]
        assert [r["session"] for r in rows] == [True, False, False, True, True], "DSH 不算会话；大肥鱼的没有会话"
        assert rows[-1]["host"] == "terminal" and rows[-1]["path"] == "C:/code/repo", "在用的会话：登记表里的目录与来源"
        assert rows[3]["host"] == "vscode" and rows[3]["where"] and rows[3]["path"] == "/home/me/ci", "关掉的会话：最近的对话里的"
        assert rows[2]["subtitle"] == "Slack · 2 条需要你看" and rows[2]["kind"] == "alert"
        assert shell.island.message_tooltip() == "消息记录 · 5 条新的"
        assert (Path(shell.config.dir) / LOG_FILE).exists(), "落盘了"
        shell._on_island_messages_opened()
        assert shell.island.message_tooltip() == "消息记录" and all(not r["unread"] for r in shell.island._message_panel._rows)
    finally:
        _close(shell)


def test_hidden_fish_feedback_bubble_is_recorded_once_even_after_the_alert(tmp_path, monkeypatch):
    shell = _shell(tmp_path)
    try:
        monkeypatch.setattr(shell, "_aggregate_pet_visible", lambda: True)   # 「其实可见」：改道面拒绝，但记录照记
        origin = {"agent": "claude", "session_id": "abcdefgh-1234", "name": "Claude Code"}
        assert shell._island_feedback_bubble("本轮运行失败", "", 3200, origin) is False
        shell._record_message("本轮运行失败", "", "alert", origin)
        assert len(shell._message_log()) == 1, "同一条文案隐藏期改道又来一遍：只记一次"
    finally:
        _close(shell)


def test_clicking_a_message_switches_to_a_live_chat_and_menu_actions_edit_the_log(tmp_path):
    shell = _shell(tmp_path, sessions=[_LIVE])
    try:
        log = shell._message_log()
        live = log.record("干完活啦", agent="claude", session_id="abcdefgh-1234", title="repo")
        gone = log.record("早就关了", agent="claude", session_id="00000000-gone", title="旧对话")
        pet = log.record("Slack 总结")
        shell._on_island_message_activated(live.uid)
        assert shell._overlay_shell.session_actions.jumped == [("claude", "abcdefgh-1234")]
        assert shell.island._message_panel.header.text().startswith("正在切到这个对话")
        shell._on_island_message_activated(gone.uid)
        assert shell.island._message_panel.header.text().startswith("这个对话已经不在")
        shell._on_island_message_activated(pet.uid)
        assert shell._overlay_shell.session_actions.jumped == [("claude", "abcdefgh-1234")], "大肥鱼的消息没有去处"
        shell._on_island_message_action("dismiss", pet.uid)
        assert [m.uid for m in log.messages()] == [gone.uid, live.uid]
        shell._on_island_message_toggled(False)
        assert MessageLog(Path(shell.config.dir) / LOG_FILE).ui_open is False, "折叠状态跟着数据一起存"
        shell._on_island_message_action("clear", None)
        assert len(log) == 0 and shell.island._message_panel._rows == [] and shell.island.message_tooltip() == "消息记录"
    finally:
        _close(shell)
