# -*- coding: utf-8 -*-
"""设置页「个人助理」一节：开关、克隆目录、时间、模型（可单独选）、思考强度（可单独选）能存回去；流程说明折叠节；中英文。"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet import personal_vault as pv
from pet import settings_personal as sp
from pet.config import Config

app = QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


def _dialog(tmp_path, monkeypatch, *, git: bool = True, language: str = "zh", **settings):
    from pet import modern_settings_dialog as settings_mod

    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    monkeypatch.setattr(sp.pv, "git_exe", lambda: r"C:\Program Files\Git\cmd\git.exe" if git else None)
    config = Config(tmp_path)
    config.set("ui_language", language)
    if settings:
        config.set(pv.CONFIG_KEY, {**pv.normalize(None), **settings})
    return config, settings_mod.ModernSettingsDialog(config, include_ai=False)


def _row_page(dialog, row_id: str) -> str:
    from pet.settings_widgets import SettingRow

    row = dialog.findChild(SettingRow, f"settingRow_{row_id}")
    assert row is not None, row_id
    for index in range(dialog.pages.count()):
        if dialog.pages.widget(index).isAncestorOf(row):
            return dialog.sidebar.item(index).text()
    return ""


def _close(dialog):
    dialog.close()
    dialog.deleteLater()
    app.processEvents()


def test_the_rows_live_in_automation_and_show_the_saved_values(tmp_path, monkeypatch):
    config, dialog = _dialog(tmp_path, monkeypatch, enabled=True, repo_dir=r"D:\vault\AI-Base", time="07:30",
                             model="claude-haiku-5-5", effort="low")
    try:
        for row_id in ("personal_flow", "personal_enabled", "personal_repo_dir", "personal_time", "personal_model", "personal_effort"):
            assert _row_page(dialog, row_id) == "简报与笔记", row_id
        assert dialog.personal_enabled_check.isChecked()
        assert dialog.personal_repo_edit.text() == r"D:\vault\AI-Base"
        assert dialog.personal_time_select.currentData() == "07:30"
        assert dialog.personal_model_select.currentData() == "claude-haiku-5-5" and dialog.personal_model_edit.isHidden()
        assert dialog.personal_effort_select.currentData() == "low"
        assert "<b>" in dialog.personal_flow_label.text() and "只读" in dialog.personal_flow_label.text()
    finally:
        _close(dialog)


def test_model_and_effort_can_be_chosen_separately_and_follow_chat_when_blank(tmp_path, monkeypatch):
    config, dialog = _dialog(tmp_path, monkeypatch)
    try:
        assert dialog.personal_model_select.currentData() == "" and dialog.personal_effort_select.currentData() == ""
        assert dialog.personal_model_select.itemText(0) == "跟 AI 对话一致" and dialog.personal_effort_select.itemText(0) == "跟 AI 对话一致"
        assert [dialog.personal_effort_select.itemData(i) for i in range(1, dialog.personal_effort_select.count())] == list(pv.EFFORT_LEVELS)
        dialog.personal_enabled_check.setChecked(True)
        dialog.personal_time_select.setCurrentIndex(dialog.personal_time_select.findData("21:00"))
        dialog.personal_model_select.setCurrentIndex(dialog.personal_model_select.findData(sp.CUSTOM))
        assert not dialog.personal_model_edit.isHidden()
        dialog.personal_model_edit.setText(" claude-fable-5-1 ")
        dialog.personal_effort_select.setCurrentIndex(dialog.personal_effort_select.findData("xhigh"))
        sp.save_personal_settings(dialog)
        assert config.get(pv.CONFIG_KEY) == {"enabled": True, "repo_dir": pv.default_repo_dir(), "time": "21:00",
                                             "model": "claude-fable-5-1", "effort": "xhigh"}
        dialog.personal_model_select.setCurrentIndex(0)
        dialog.personal_effort_select.setCurrentIndex(0)
        sp.save_personal_settings(dialog)
        assert config.get(pv.CONFIG_KEY)["model"] == "" and config.get(pv.CONFIG_KEY)["effort"] == ""
    finally:
        _close(dialog)


def test_a_custom_model_round_trips_and_a_missing_git_is_only_a_hint(tmp_path, monkeypatch):
    config, dialog = _dialog(tmp_path, monkeypatch, git=False, model="claude-opus-5")
    try:
        assert dialog.personal_model_select.currentData() == sp.CUSTOM and dialog.personal_model_edit.text() == "claude-opus-5"
        assert dialog.personal_enabled_check.isEnabled(), "简报不需要 git，开关照常可用"
        from pet.settings_widgets import SettingRow

        row = dialog.findChild(SettingRow, "settingRow_personal_enabled")
        assert "git" in row.hint_label.text()
    finally:
        _close(dialog)


def test_the_section_speaks_english(tmp_path, monkeypatch):
    config, dialog = _dialog(tmp_path, monkeypatch, language="en")
    try:
        from pet.settings_widgets import SettingRow

        row = dialog.findChild(SettingRow, "settingRow_personal_model")
        assert row.findChild(type(row), None) is None or True
        assert dialog.personal_model_select.itemText(0) == "Same as AI chat"
        assert dialog.personal_effort_select.itemText(2).startswith("Medium")
        assert "How the personal assistant flows" in dialog.personal_flow_label.text()
    finally:
        _close(dialog)
