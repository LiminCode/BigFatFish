# -*- coding: utf-8 -*-
"""设置页「工作简报」一节：开关、工作日、时间、模型、六个来源开关能存回去；折叠的流程说明讲清怎么做 / 何时 / 发什么 / 能用什么；
没装 WSL 时开关置灰；中英文。"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet import settings_work_briefing as swb
from pet import work_briefing as wb
from pet.config import Config
from pet.settings_widgets import SettingRow

app = QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


def _dialog(tmp_path, monkeypatch, *, wsl: bool = True, language: str = "zh", **settings):
    from pet import modern_settings_dialog as settings_mod

    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    monkeypatch.setattr(swb.claude_hooks, "wsl_exe", lambda: r"C:\Windows\System32\wsl.exe" if wsl else None)
    config = Config(tmp_path)
    config.set("ui_language", language)
    if settings:
        config.set(wb.CONFIG_KEY, {**wb.normalize(None), **settings})
    return config, settings_mod.ModernSettingsDialog(config, include_ai=False)


def _page_of(dialog, row_id: str) -> str:
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
    config, dialog = _dialog(tmp_path, monkeypatch, enabled=True, weekdays_only=False, time="08:30", model="haiku",
                             sources={**wb.DEFAULT_SOURCES, "email": True, "slack": False})
    try:
        for row_id in ("work_briefing_flow", "work_briefing_enabled", "work_briefing_weekdays", "work_briefing_time",
                       "work_briefing_model", *(f"work_briefing_source_{s}" for s in wb.SOURCES)):
            assert _page_of(dialog, row_id) == "自动化与联动", row_id
        assert dialog.work_briefing_enabled_check.isChecked() and not dialog.work_briefing_weekdays_check.isChecked()
        assert dialog.work_briefing_time_select.currentData() == "08:30"
        assert dialog.work_briefing_model_select.currentData() == "haiku"
        checks = dialog.work_briefing_source_checks
        assert checks["email"].isChecked() and not checks["slack"].isChecked() and checks["jira"].isChecked()
        body = dialog.findChild(SettingRow, "settingRow_work_briefing_flow").hint_label.text()
        for piece in ("什么时候", "发给 Claude 什么", "它能用什么", "结果放哪", "只读", "gh", "不会"):
            assert piece in body, piece
        assert dialog.work_briefing_flow_section.advanced, "说明默认收起"
    finally:
        _close(dialog)


def test_saving_writes_sources_and_the_rest(tmp_path, monkeypatch):
    config, dialog = _dialog(tmp_path, monkeypatch)
    try:
        dialog.work_briefing_enabled_check.setChecked(True)
        dialog.work_briefing_weekdays_check.setChecked(False)
        dialog.work_briefing_time_select.setCurrentIndex(dialog.work_briefing_time_select.findData("10:00"))
        dialog.work_briefing_model_select.setCurrentIndex(dialog.work_briefing_model_select.findData(swb.CUSTOM))
        dialog.work_briefing_model_edit.setText("claude-opus-5-5")
        dialog.work_briefing_source_checks["email"].setChecked(True)
        dialog.work_briefing_source_checks["calendar"].setChecked(False)
        swb.save_work_briefing_settings(dialog)
        saved = config.get(wb.CONFIG_KEY)
        assert saved == {"enabled": True, "time": "10:00", "weekdays_only": False, "model": "claude-opus-5-5",
                         "sources": {**wb.DEFAULT_SOURCES, "email": True, "calendar": False}}
        assert any("Gmail" in name for name in wb.allowed_tools(saved["sources"])), "开了邮件 → 简报能用邮件工具"
    finally:
        _close(dialog)


def test_without_wsl_the_switch_is_off_and_explains_why(tmp_path, monkeypatch):
    config, dialog = _dialog(tmp_path, monkeypatch, wsl=False, enabled=True)
    try:
        assert not dialog.work_briefing_enabled_check.isEnabled() and not dialog.work_briefing_enabled_check.isChecked()
        assert "WSL" in dialog.findChild(SettingRow, "settingRow_work_briefing_enabled").hint_label.text()
    finally:
        _close(dialog)


def test_the_section_speaks_english(tmp_path, monkeypatch):
    config, dialog = _dialog(tmp_path, monkeypatch, language="en")
    try:
        assert dialog.findChild(SettingRow, "settingRow_work_briefing_source_email").label.text() == "Include email"
        body = dialog.findChild(SettingRow, "settingRow_work_briefing_flow").hint_label.text()
        assert "What is sent to Claude" in body and "read-only" in body and "Never" in body
        assert dialog.work_briefing_model_select.itemText(dialog.work_briefing_model_select.findData(swb.CUSTOM)) == "Custom…"
    finally:
        _close(dialog)
