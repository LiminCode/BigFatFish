# -*- coding: utf-8 -*-
"""设置页「Slack 关注」一节：开关、间隔、离开判定、模型，改了能存回去；没装 WSL 时开关置灰。"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from pet import settings_slack_watch as ssw
from pet import slack_watch as sw
from pet.config import Config

app = QApplication.instance() or QApplication([])


def _dialog(tmp_path, monkeypatch, *, wsl: bool = True, **settings):
    from pet import modern_settings_dialog as settings_mod

    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    monkeypatch.setattr(ssw.claude_hooks, "wsl_exe", lambda: r"C:\Windows\System32\wsl.exe" if wsl else None)
    config = Config(tmp_path)
    if settings:
        config.set(sw.CONFIG_KEY, settings)
    return config, settings_mod.ModernSettingsDialog(config, include_ai=False)


def _row_page(dialog, row_id: str) -> str:
    from pet.settings_widgets import SettingRow

    row = dialog.findChild(SettingRow, f"settingRow_{row_id}")
    assert row is not None, row_id
    for index in range(dialog.pages.count()):
        if dialog.pages.widget(index).isAncestorOf(row):
            return dialog.sidebar.item(index).text()
    return ""


def test_the_rows_live_in_automation_and_show_the_saved_values(tmp_path, monkeypatch):
    config, dialog = _dialog(tmp_path, monkeypatch, enabled=True, interval_minutes=30, idle_minutes=5, model="haiku")
    try:
        for row_id in ("slack_watch_enabled", "slack_watch_interval", "slack_watch_idle", "slack_watch_model"):
            assert _row_page(dialog, row_id) == "简报与笔记", row_id
        assert dialog.slack_watch_enabled_check.isChecked() and dialog.slack_watch_enabled_check.isEnabled()
        assert dialog.slack_watch_interval_spin.value() == 30 and dialog.slack_watch_idle_spin.value() == 5
        assert dialog.slack_watch_model_select.currentData() == "haiku"
        assert dialog.slack_watch_model_edit.isHidden(), "选的是常用名：自定义框收起"
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_changes_are_saved_back_through_normalize(tmp_path, monkeypatch):
    config, dialog = _dialog(tmp_path, monkeypatch)
    try:
        assert not dialog.slack_watch_enabled_check.isChecked(), "默认关"
        dialog.slack_watch_enabled_check.setChecked(True)
        dialog.slack_watch_interval_spin.setValue(45)
        dialog.slack_watch_idle_spin.setValue(20)
        select = dialog.slack_watch_model_select
        select.setCurrentIndex(select.findData(ssw.CUSTOM))
        assert not dialog.slack_watch_model_edit.isHidden()
        dialog.slack_watch_model_edit.setText(" claude-sonnet-5-5 ")
        ssw.save_slack_watch_settings(dialog)
        assert config.get(sw.CONFIG_KEY) == {"enabled": True, "interval_minutes": 45, "idle_minutes": 20,
                                             "model": "claude-sonnet-5-5", "effort": "high", "prompt": ""}
        dialog.slack_watch_model_edit.setText("rm -rf /")
        ssw.save_slack_watch_settings(dialog)
        assert config.get(sw.CONFIG_KEY)["model"] == "sonnet", "怪名字退回默认，不进 shell"
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_a_custom_model_name_in_the_config_shows_up_as_custom(tmp_path, monkeypatch):
    _config, dialog = _dialog(tmp_path, monkeypatch, model="claude-opus-5-5")
    try:
        assert dialog.slack_watch_model_select.currentData() == ssw.CUSTOM
        assert dialog.slack_watch_model_edit.text() == "claude-opus-5-5" and not dialog.slack_watch_model_edit.isHidden()
        assert ssw.chosen_model(dialog) == "claude-opus-5-5"
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_without_wsl_the_switch_is_greyed_out_and_saving_keeps_it_off(tmp_path, monkeypatch):
    config, dialog = _dialog(tmp_path, monkeypatch, wsl=False, enabled=True)
    try:
        check = dialog.slack_watch_enabled_check
        assert not check.isEnabled() and not check.isChecked()
        ssw.save_slack_watch_settings(dialog)
        assert config.get(sw.CONFIG_KEY)["enabled"] is False
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


# ---------------------------------------------------------------- effort / 提示词（2026-10-24）

def test_effort_and_prompt_rows_show_the_builtin_and_save_only_changes(tmp_path, monkeypatch):
    config, dialog = _dialog(tmp_path, monkeypatch, effort="low")
    try:
        assert _row_page(dialog, "slack_watch_effort") == "简报与笔记"
        assert _row_page(dialog, "slack_watch_prompt") == "简报与笔记"
        assert dialog.slack_watch_effort_select.currentData() == "low"
        assert dialog.slack_watch_prompt_edit.toPlainText() == sw.default_prompt_template()
        assert not dialog.slack_watch_prompt_restore.isEnabled()
        ssw.save_slack_watch_settings(dialog)
        assert config.get(sw.CONFIG_KEY)["prompt"] == "" and config.get(sw.CONFIG_KEY)["effort"] == "low"

        dialog.slack_watch_prompt_edit.setPlainText("我的 Slack 模板 {since}")
        ssw.save_slack_watch_settings(dialog)
        assert config.get(sw.CONFIG_KEY)["prompt"] == "我的 Slack 模板 {since}"
        dialog.slack_watch_prompt_restore.click()
        assert dialog.slack_watch_prompt_edit.toPlainText() == sw.default_prompt_template()
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
