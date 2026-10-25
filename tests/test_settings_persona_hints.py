# -*- coding: utf-8 -*-
"""「人设」与「文案风格与模板」两处设置要说清：设定在哪里、怎么起作用、影响什么功能（用户 2026-10-18）。

- AI 与对话：人设 + 关于我从「模型与连接」挪到自己的一节「人设与回复」，后面跟一节默认收起的说明；
  提示里写明影响 / 不影响哪些功能，并指向台词模板所在的页。
- 自动化与联动：「表达风格」的提示不再说它管自言自语和主动气泡（它不管），只管 Agent 联动气泡与余额结果，
  并指向对话人设所在的页；留空的回退说法改成真实的（内置兜底文案）；加一节「这些台词怎么起作用」。
中英文都有。纯界面：不碰真实数据目录。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet.config import Config
from pet.settings_widgets import SettingRow, SettingsSection

app = QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


def _dialog(tmp_path, monkeypatch, language: str = "zh"):
    from pet import modern_settings_dialog as settings_mod

    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    config = Config(tmp_path)
    config.set("ui_language", language)
    return settings_mod.ModernSettingsDialog(config, include_ai=True)


def _close(dialog):
    dialog.close()
    dialog.deleteLater()
    app.processEvents()


def _section_of(dialog, row_id: str) -> SettingsSection:
    row = dialog.findChild(SettingRow, f"settingRow_{row_id}")
    assert row is not None, row_id
    parent = row.parentWidget()
    while parent is not None and not isinstance(parent, SettingsSection):
        parent = parent.parentWidget()
    assert parent is not None, row_id
    return parent


def _page_of(dialog, row_id: str) -> str:
    row = dialog.findChild(SettingRow, f"settingRow_{row_id}")
    for index in range(dialog.pages.count()):
        if dialog.pages.widget(index).isAncestorOf(row):
            return dialog.sidebar.item(index).text()
    return ""


def test_the_persona_lives_in_its_own_section_and_says_what_it_affects(tmp_path, monkeypatch):
    dialog = _dialog(tmp_path, monkeypatch)
    try:
        persona = _section_of(dialog, "system_prompt")
        assert persona is _section_of(dialog, "about_user") and persona is not _section_of(dialog, "api_key"), \
            "人设是全局的，不该夹在服务商的连接参数里"
        assert [row.objectName() for row in persona.rows] == ["settingRow_system_prompt", "settingRow_about_user"]
        assert _page_of(dialog, "system_prompt") == "AI 与对话"
        prompt_row = dialog.findChild(SettingRow, "settingRow_system_prompt")
        assert prompt_row.label.text() == "人设（System Prompt）"
        hint = prompt_row.hint_label.text()
        assert "不随上面的服务商切换" in hint and "对话窗" in hint and "看看屏幕" in hint
        assert "不影响" in hint and "文案风格与模板" in hint and "候选内容" in hint
        about = dialog.findChild(SettingRow, "settingRow_about_user").hint_label.text()
        assert "带上它的" in about and "不带的" in about and "看看屏幕" in about
        help_section = _section_of(dialog, "persona_help")
        assert help_section.advanced, "说明默认收起"
        body = dialog.findChild(SettingRow, "settingRow_persona_help").hint_label.text()
        assert "<b>" in body and "chat.default_system_prompt" in body and "persona_presets" not in body
        assert "两套" in body and "文案风格与模板" in body and "不经过模型" in body
    finally:
        _close(dialog)


def test_the_bubble_style_hint_tells_the_truth_and_has_its_own_explanation(tmp_path, monkeypatch):
    dialog = _dialog(tmp_path, monkeypatch)
    try:
        mode_row = dialog.findChild(SettingRow, "settingRow_dialogue_mode")
        hint = mode_row.hint_label.text()
        assert "自言自语" in hint and "不影响" in hint, "之前的提示说它管自言自语和主动气泡——它不管"
        assert "Agent 联动气泡" in hint and "不经过模型" in hint and "人设" in hint and "persona_presets" in hint
        assert _page_of(dialog, "dialogue_mode") == "自动化与联动"
        scope = dialog.findChild(SettingRow, "settingRow_dialogue_scope").hint_label.text()
        assert "内置兜底文案" in scope and "不是「默认模式」" in scope
        help_row = dialog.findChild(SettingRow, "settingRow_bubble_style_help")
        assert help_row is not None and _page_of(dialog, "bubble_style_help") == "自动化与联动"
        assert dialog.bubble_style_help_section.advanced
        body = help_row.hint_label.text()
        assert "dialogue_mode" in body and "dialogue_phrases" in body and "persona_presets" in body
        assert "专属文案 → 全局文案 → 内置兜底" in body and "不管：对话窗" in body
        # 说明节紧跟「文案风格与模板」之后、自定义台词折叠框之前
        layout = dialog.bubble_style_help_section.parentWidget().layout()
        index = layout.indexOf(dialog.bubble_style_help_section)
        assert layout.itemAt(index + 1).widget() is dialog.dialogue_phrases_box
        placeholders = [edit.placeholderText() for edit in dialog.dialogue_phrase_edits.values()]
        assert placeholders and all(p.startswith("留空用内置兜底文案") for p in placeholders)
        assert not any("基础模式" in p for p in placeholders)
    finally:
        _close(dialog)


def test_both_explanations_speak_english(tmp_path, monkeypatch):
    dialog = _dialog(tmp_path, monkeypatch, "en")
    try:
        assert dialog.findChild(SettingRow, "settingRow_system_prompt").label.text() == "Persona (system prompt)"
        assert "Does not affect" in dialog.findChild(SettingRow, "settingRow_system_prompt").hint_label.text()
        assert "two separate systems" in dialog.findChild(SettingRow, "settingRow_persona_help").hint_label.text()
        assert "never sent to a model" in dialog.findChild(SettingRow, "settingRow_dialogue_mode").hint_label.text()
        assert "no model is involved" in dialog.findChild(SettingRow, "settingRow_bubble_style_help").hint_label.text()
    finally:
        _close(dialog)
