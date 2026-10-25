# -*- coding: utf-8 -*-
"""「关于我」：一段用户自己写的说明，对话时追加在人设后面。

人设有三个来源（调用方给的 > 角色包自带的 > 设置页的 System Prompt），后者会被前者
整个顶替；「关于我」不属于人设，无论最后用的是哪一个都要带上。
"""

from __future__ import annotations

import json

import pytest

from pet.chat.models import ChatSettings
from pet.chat.prompt import PromptBuilder

ABOUT = "用户叫小明，知识库在 GitHub 仓库 acme/handbook，先读 INDEX.md。"


def _settings(about: str = ABOUT) -> ChatSettings:
    settings = ChatSettings.defaults()
    settings.default_system_prompt = "你是鲸鱼娘。"
    settings.about_user = about
    return settings


def _system(builder: PromptBuilder, settings: ChatSettings, character: str = "shenshen", **kwargs) -> str:
    messages = builder.build_messages(settings, character, [], "嗨", **kwargs)
    assert messages[0]["role"] == "system" and messages[-1]["content"].endswith("] 嗨")   # 本轮消息带时间标记
    system, sep, note = messages[0]["content"].partition("\n\n【时间信息】")   # 时间说明接在最后，这里只看前面
    assert sep and note
    return system


def test_about_user_follows_the_settings_persona():
    assert _system(PromptBuilder(), _settings()) == f"你是鲸鱼娘。\n\n{ABOUT}"


def test_about_user_survives_a_persona_that_replaces_the_settings_prompt(tmp_path):
    """角色包自带人设时设置页的 System Prompt 整段不用——「关于我」不能跟着一起丢。"""
    (tmp_path / "fox").mkdir()
    (tmp_path / "fox" / "manifest.json").write_text(
        json.dumps({"chat": {"system_prompt": "你是狐狸。"}}, ensure_ascii=False), encoding="utf-8")
    builder = PromptBuilder(tmp_path)

    assert _system(builder, _settings(), "fox") == f"你是狐狸。\n\n{ABOUT}"
    assert _system(builder, _settings(), "fox", role_prompt="你是临时角色。") == f"你是临时角色。\n\n{ABOUT}"


@pytest.mark.parametrize("blank", ["", "   \n "])
def test_blank_about_user_leaves_the_prompt_untouched(blank):
    assert _system(PromptBuilder(), _settings(blank)) == "你是鲸鱼娘。"


def test_the_persona_itself_does_not_include_about_user():
    """effective_system_prompt 还用于文件解读等不带工具的请求，那里不追加。"""
    assert PromptBuilder().effective_system_prompt(_settings(), "shenshen") == "你是鲸鱼娘。"


def test_about_user_round_trips_and_defaults_to_empty():
    assert ChatSettings.defaults().about_user == ""
    assert ChatSettings.from_dict({}).about_user == ""
    assert ChatSettings.from_dict(_settings().to_dict()).about_user == ABOUT


# ---------------------------------------------------------------- 设置页与对话窗口

class _RecordingService:
    busy = False

    def __init__(self):
        self.sent: list = []

    def send(self, messages, config, request_id=None):
        self.sent.append((messages, config))
        return "rid-1"

    def stop(self):
        pass


@pytest.fixture
def no_keyring(monkeypatch):
    class _Store:
        def __init__(self, *_a, **_k):
            pass

        def get(self, _ref):
            return ""

        def set(self, _ref, _value):
            return True

    monkeypatch.setattr("pet.chat.models.SecretStore", _Store)


def test_settings_page_edits_and_persists_about_user(tmp_path, no_keyring):
    from PySide6.QtWidgets import QApplication

    from pet.chat.ai_settings_page import _AiSettingsPage
    from pet.config import Config
    from pet.settings_widgets import SettingRow

    QApplication.instance() or QApplication([])
    config = Config(base=tmp_path)
    page = _AiSettingsPage(config)
    try:
        assert page.findChild(SettingRow, "settingRow_about_user") is not None
        assert page.about_user.toPlainText() == ""
        page.about_user.setPlainText(f"  {ABOUT}\n")
        page.save()
        config.save()
    finally:
        page.deleteLater()

    assert Config(base=tmp_path).chat_settings().about_user == ABOUT
    reopened = _AiSettingsPage(Config(base=tmp_path))
    try:
        assert reopened.about_user.toPlainText() == ABOUT
    finally:
        reopened.deleteLater()


def test_chat_window_sends_about_user_with_the_persona(tmp_path, no_keyring):
    from PySide6.QtWidgets import QApplication

    from pet.chat.widgets import ChatWindow
    from pet.config import Config

    QApplication.instance() or QApplication([])
    config = Config(base=tmp_path)
    settings = config.chat_settings()
    settings.about_user = ABOUT
    config.set_chat_settings(settings)
    window = ChatWindow(config, "shenshen")
    try:
        window.service = _RecordingService()
        window.input.setPlainText("我最近在忙什么？")
        window.send_message()
        system = window.service.sent[0][0][0]
        assert system["role"] == "system" and f"\n\n{ABOUT}\n\n【时间信息】" in system["content"]
    finally:
        window.close()
