# -*- coding: utf-8 -*-
"""设置页「工作笔记」一节：开关、仓库目录、模型能存回去；没装 WSL 时开关置灰；流程图标悬停讲整条流程；中英文。"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet import settings_work_notes as swn
from pet import work_notes as wn
from pet.config import Config
from pet.settings_widgets import TiltButton

app = QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


def _dialog(tmp_path, monkeypatch, *, wsl: bool = True, language: str = "zh", **settings):
    from pet import modern_settings_dialog as settings_mod

    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    monkeypatch.setattr(swn.claude_hooks, "wsl_exe", lambda: r"C:\Windows\System32\wsl.exe" if wsl else None)
    config = Config(tmp_path)
    config.set("ui_language", language)
    if settings:
        config.set(wn.CONFIG_KEY, {**wn.normalize(None), **settings})
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
    config, dialog = _dialog(tmp_path, monkeypatch, enabled=True, repo_dir=r"D:\notes\AI-Base-Memory", model="haiku")
    try:
        for row_id in ("work_notes_flow", "work_notes_enabled", "work_notes_repo_dir", "work_notes_model"):
            assert _row_page(dialog, row_id) == "自动化与联动", row_id
        assert dialog.work_notes_enabled_check.isChecked() and dialog.work_notes_enabled_check.isEnabled()
        assert dialog.work_notes_repo_edit.text() == r"D:\notes\AI-Base-Memory"
        assert dialog.work_notes_model_select.currentData() == "haiku"
        assert dialog.work_notes_model_edit.isHidden()
    finally:
        _close(dialog)


def test_the_flow_icon_explains_the_whole_flow_on_hover(tmp_path, monkeypatch):
    """用户 2026-10-15：进设置页要带解释——一个浮动的流程图标，悬停讲清楚流程，免得日久忘了细节。"""
    _config, dialog = _dialog(tmp_path, monkeypatch)
    try:
        button = dialog.work_notes_flow_button
        assert isinstance(button, TiltButton) and not button.icon().isNull()
        tip = button.toolTip()
        for step in ("1.", "2.", "3.", "4.", "5.", "只读", "Obsidian", "AI-Base-Memory", "token"):
            assert step in tip, step
        assert button.accessibleDescription() == tip, "读屏也能拿到同一段说明"
    finally:
        _close(dialog)


def test_changes_are_saved_back_through_normalize(tmp_path, monkeypatch):
    config, dialog = _dialog(tmp_path, monkeypatch)
    try:
        assert dialog.work_notes_enabled_check.isChecked(), "默认开"
        dialog.work_notes_enabled_check.setChecked(False)
        dialog.work_notes_repo_edit.setText("  E:\\mem  ")
        dialog.work_notes_model_select.setCurrentIndex(dialog.work_notes_model_select.findData(swn.CUSTOM))
        assert not dialog.work_notes_model_edit.isHidden(), "选了自定义：输入框出现"
        dialog.work_notes_model_edit.setText("claude-sonnet-5-5")
        swn.save_work_notes_settings(dialog)
        assert config.get(wn.CONFIG_KEY) == {"enabled": False, "repo_dir": "E:\\mem", "model": "claude-sonnet-5-5"}
        dialog.work_notes_model_edit.setText("bad model!")
        swn.save_work_notes_settings(dialog)
        assert config.get(wn.CONFIG_KEY)["model"] == "sonnet", "怪名字退回默认"
        dialog.work_notes_repo_edit.setText("")
        swn.save_work_notes_settings(dialog)
        assert config.get(wn.CONFIG_KEY)["repo_dir"] == wn.default_repo_dir(), "空目录退回默认"
    finally:
        _close(dialog)


def test_without_wsl_the_switch_is_greyed_out_with_a_reason(tmp_path, monkeypatch):
    _config, dialog = _dialog(tmp_path, monkeypatch, wsl=False, enabled=True)
    try:
        assert not dialog.work_notes_enabled_check.isEnabled() and not dialog.work_notes_enabled_check.isChecked()
        from pet.settings_widgets import SettingRow

        row = dialog.findChild(SettingRow, "settingRow_work_notes_enabled")
        assert "WSL" in row.hint_label.text()
    finally:
        _close(dialog)


def test_the_section_speaks_english(tmp_path, monkeypatch):
    _config, dialog = _dialog(tmp_path, monkeypatch, language="en")
    try:
        from pet.settings_widgets import SettingRow

        assert dialog.findChild(SettingRow, "settingRow_work_notes_enabled").label.text() == "Enable work notes"
        assert dialog.findChild(SettingRow, "settingRow_work_notes_flow").label.text() == "How it works"
        assert "read-only" in dialog.work_notes_flow_button.toolTip()
        assert dialog.work_notes_model_select.itemText(dialog.work_notes_model_select.findData(swn.CUSTOM)) == "Custom…"
    finally:
        _close(dialog)
