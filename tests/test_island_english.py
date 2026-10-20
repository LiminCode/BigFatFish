# -*- coding: utf-8 -*-
"""切到 English 之后，灵动岛胶囊与展开卡片上的文字是英文；切回中文和原来逐字相同。

第一片（2026-10-14）只覆盖岛：胶囊计数、卡片标题行、最近的对话、时间与来源、动作结果、
API 体检与余额的说明。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import claude_hooks as ch
from pet import i18n
from pet.claude_session_history import HistoryEntry, ago_text
from pet.config import Config
from pet.dynamic_island import DynamicIsland
from pet.island_history_panel import SessionHistoryPanel

app = QApplication.instance() or QApplication([])

SESSIONS = [
    {"agent": "claude", "sessionId": "a1", "project": "web", "phase": "working"},
    {"agent": "claude_wsl", "sessionId": "b2", "project": "api", "phase": "resting"},
    {"agent": "claude", "sessionId": "c3", "project": "cli", "phase": "resting"},
]


@pytest.fixture
def english():
    i18n.set_language("en")
    yield
    i18n.set_language("zh")


# ---------------------------------------------------------------- 纯函数：计数、标题、时间、来源

def test_capsule_counts_and_card_headline_in_english(english):
    assert ch.session_counts(SESSIONS) == [("working", "1 working"), ("resting", "2 napping")]
    headline, detail = ch.summarize_sessions(SESSIONS)
    assert headline == "Claude Code · 1 working · 2 napping"
    assert detail == "web · Working ｜ api (WSL) · Napping and 3 in all"
    assert ch.summarize_sessions([]) == ("Claude Code · nobody's on duty",
                                         "Sessions show up here once you ask them something")
    assert ch.PHASE_TEXT["waiting"] == "Needs OK" and ch.PHASE_TEXT["review"] == "Your turn"


def test_the_same_functions_still_say_exactly_what_they_used_to_in_chinese():
    i18n.set_language("zh")
    assert ch.session_counts(SESSIONS) == [("working", "1 工作中"), ("resting", "2 休息中")]
    assert ch.summarize_sessions(SESSIONS) == ("Claude Code · 1 个在干活 · 2 个休息中",
                                               "web · 工作中 ｜ api (WSL) · 休息中 等 3 个")
    assert ch.summarize_sessions([]) == ("Claude Code · 没有在用的会话", "会话提问后会出现在这里")
    assert dict(ch.PHASE_TEXT) == {"working": "工作中", "waiting": "等你批准", "review": "等你回复", "resting": "休息中"}


def test_time_and_origin_in_english(english):
    assert [ago_text(s) for s in (5, 60, 11 * 60, 3600, 3 * 3600, 90000, 3 * 86400)] == [
        "just now", "1 min ago", "11 min ago", "1 h ago", "3 h ago", "yesterday", "3 days ago"]
    assert HistoryEntry(agent="claude", session_id="x", entrypoint="cli").where == "Terminal"
    assert HistoryEntry(agent="claude_wsl", session_id="x", entrypoint="claude-vscode").where == "VS Code · WSL"
    assert HistoryEntry(agent="claude_wsl", session_id="x").where == "WSL"
    assert HistoryEntry(agent="claude", session_id="x", entrypoint="sdk-cli").where == "Script"


def test_time_and_origin_in_chinese_are_unchanged():
    i18n.set_language("zh")
    assert [ago_text(s) for s in (5, 11 * 60, 3 * 3600, 90000, 3 * 86400)] == ["刚刚", "11 分钟前", "3 小时前", "昨天", "3 天前"]
    assert HistoryEntry(agent="claude_wsl", session_id="x", entrypoint="cli").where == "终端 · WSL"


# ---------------------------------------------------------------- 控件：卡片、最近的对话

def _island(tmp_path) -> DynamicIsland:
    language = i18n.current_language()
    config = Config(tmp_path)          # 加载配置会按它的 ui_language 设语言：把当前语言写进去
    config.set("ui_language", language)
    config.set("dynamic_island", {"enabled": True, "show_icon": True, "show_name": True, "show_info": True,
                                  "info_mode": "usage_today", "show_status": True, "style": "dark", "x": 100, "y": 100})
    island = DynamicIsland(config)
    island.show()
    return island


def test_the_card_buttons_and_placeholders_follow_the_language(tmp_path, english):
    island = _island(tmp_path)
    try:
        island.expand_card()
        assert island._card_toggle_btn.text() == "Hide the fish"
        island.set_pet_visible(False)
        assert island._card_toggle_btn.text() == "Show the fish"
        assert island._card_chat_btn.text() == "Chat" and island._card_settings_btn.text() == "Settings"
        assert island._usage_text == "Today --" and island._balance_text == "Balance --"
        island.set_briefing_state("unread")
        assert island.briefing_tooltip() == "Daily Briefing · a fresh one is in"
    finally:
        island.close()


def test_the_history_panel_follows_the_language(english):
    panel = SessionHistoryPanel()
    panel.set_look(primary="#e5eaf5", secondary="#a0aabe", accent="#40b8ff", width=308)
    panel.set_rows([{"key": ("claude", "a"), "label": "web", "where": "Terminal", "host": "terminal",
                     "path": "C:\\w", "ago": "yesterday", "live": True}])
    assert panel.header_text == "Recent chats (1) · Expand"
    panel.set_open(True)
    assert panel.header_text == "Recent chats (1) · Collapse"
    assert panel.row_widgets()[0].ago.text() == "Live"
    labels = [a.text() for a in panel.row_menu(("claude", "a")).actions() if not a.isSeparator()]
    assert labels == ["Pin to top", "Resume in terminal", "Open in VS Code", "Open folder", "Copy path",
                      "Copy resume command", "Remove from list", "Clear list"]
    panel.deleteLater()


def test_switching_language_re_renders_the_open_island(tmp_path):
    """语言是运行中改的（设置窗口保存 → 配置重载）：岛上已经摆着的文字要跟着换。"""
    island = _island(tmp_path)
    try:
        island.expand_card()
        island.set_session_history([{"key": ("claude", "a"), "label": "web", "where": "终端", "host": "terminal",
                                     "path": "C:\\w", "ago": "昨天", "live": False}], is_open=True)
        assert island._card_chat_btn.text() == "聊天"
        i18n.set_language("en")
        island.refresh_from_config()
        assert island._card_chat_btn.text() == "Chat"
        assert island._history_panel.header_text == "Recent chats (1) · Collapse"
        assert island._card_toggle_btn.text() in ("Hide the fish", "Show the fish")
    finally:
        i18n.set_language("zh")
        island.close()


# ---------------------------------------------------------------- 设置页：常规 → 语言 / Language

def test_the_language_setting_lives_on_the_general_page_and_persists(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QLabel, QStackedWidget

    from pet import modern_settings_dialog as settings_mod

    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    dialog = settings_mod.ModernSettingsDialog(Config(tmp_path), include_ai=False)
    try:
        row = dialog.findChild(settings_mod.SettingRow, "settingRow_ui_language")
        assert row is not None
        widget, page = row, None
        while widget is not None:
            if isinstance(widget.parent(), QStackedWidget):
                page = widget
            widget = widget.parent()
        assert dialog.sidebar.item(page.parent().indexOf(page)).text() == "常规", "没被认领的行会掉进「待分类」"
        first = page.findChildren(settings_mod.SettingsSection)[0]
        assert [label.text() for label in first.findChildren(QLabel)][0] == "语言 / Language"
        assert dialog.ui_language_select.currentData() == "zh"
        dialog.ui_language_select.setCurrentIndex(dialog.ui_language_select.findData("en"))
        dialog._save()
    finally:
        dialog.deleteLater()
    assert Config(tmp_path).get("ui_language") == "en"
    i18n.set_language("zh")
