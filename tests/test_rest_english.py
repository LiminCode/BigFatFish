# -*- coding: utf-8 -*-
"""界面语言 = English 时，聊天窗（新版 / 旧版）、快速对话气泡、会话来源等文案也是英文；中文界面逐字不变；
这一轮新增的键两张表齐全、英文里不含中文。纯界面：不调模型、不碰真实数据目录。"""
from __future__ import annotations

import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from pet import i18n
from pet.chat import legacy_widgets, widgets
from pet.claude_session_info import ENTRY_CLI, ENTRY_VSCODE, SessionDetail
from pet.config import Config
from pet.quick_chat import QuickChatBubble

app = QApplication.instance() or QApplication([])
CJK = re.compile(r"[一-鿿]")
NEW_PREFIXES = ("chat.", "vision.ui.", "quick_chat.ui.", "file_interpret.ui.", "proactive.ui.", "app.ui.", "overlay.ui.",
                "feeding.ui.", "island.ui.", "todo.ui.", "fun_image.ui.", "personal.service.", "session_jump.ui.", "vscode.ui.",
                "lyrics.ui.", "click_talk.ui.", "slack.ui.", "agent_cost.ui.", "session_info.ui.")


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


def _config(tmp_path, language: str) -> Config:
    config = Config(tmp_path)
    config.set("ui_language", language)
    return config


def _visible_texts(root: QWidget) -> list[str]:
    texts = [root.windowTitle()]
    for widget in [root, *root.findChildren(QWidget)]:
        for getter in ("text", "placeholderText", "toolTip", "title"):
            method = getattr(widget, getter, None)
            if not callable(method):
                continue
            try:
                value = method()
            except TypeError:
                continue
            if isinstance(value, str) and value:
                texts.append(value)
    return texts


def _chinese_in(texts: list[str]) -> list[str]:
    return sorted({text for text in texts if CJK.search(text)})


def _close(*widgets_):
    for widget in widgets_:
        widget.close()
        widget.deleteLater()
    app.processEvents()


def test_the_modern_chat_window_speaks_english(tmp_path):
    window = widgets.ChatWindow(_config(tmp_path, "en"), "shenshen")
    try:
        assert _chinese_in(_visible_texts(window)) == []
        texts = _visible_texts(window)
        assert window.windowTitle() == "AI Chat" and "Start a new conversation" in texts and "Sessions" in texts
        assert any(text.startswith("Say something to the fish") for text in texts)
    finally:
        _close(window)


def test_the_classic_chat_window_and_quick_chat_speak_english(tmp_path):
    config = _config(tmp_path, "en")
    window = legacy_widgets.ChatWindow(config, "shenshen")
    bubble = QuickChatBubble(config)
    try:
        assert _chinese_in(_visible_texts(window)) == []
        assert _chinese_in(_visible_texts(bubble)) == []
        bubble_texts = _visible_texts(bubble)
        assert "Send" in bubble_texts and "Open chat window" in bubble_texts
    finally:
        _close(window, bubble)


def test_the_chinese_chat_window_is_unchanged(tmp_path):
    window = widgets.ChatWindow(_config(tmp_path, "zh"), "shenshen")
    try:
        texts = _visible_texts(window)
        assert window.windowTitle() == "AI 对话" and "开启新对话" in texts and "会话" in texts
        assert any(text.startswith("和肥鱼说点什么") for text in texts)
    finally:
        _close(window)


def test_session_origin_follows_the_language():
    i18n.set_language("en")
    assert SessionDetail(entrypoint=ENTRY_CLI).entry_text == "Terminal"
    assert SessionDetail(entrypoint=ENTRY_VSCODE).entry_text == "VS Code extension"
    assert SessionDetail(entrypoint="something-else").entry_text == "something-else", "不认识的入口原样显示"
    i18n.set_language("zh")
    assert SessionDetail(entrypoint=ENTRY_CLI).entry_text == "终端"


def test_every_new_key_has_both_languages_and_no_chinese_in_english():
    zh, en = i18n.table("zh"), i18n.table("en")
    keys = [key for key in zh if key.startswith(NEW_PREFIXES)]
    assert len(keys) >= 300
    assert [key for key in keys if key not in en] == []
    assert [key for key in keys if CJK.search(en[key])] == []
