# -*- coding: utf-8 -*-
"""设置窗口里的「Slack 关注」一节：设置已经搬到配置全景（ADR 0014，路线图 M4），这里只剩一行说明、一个跳过去的按钮
和折叠的「存档与 Slack 关注页」说明。

和工作简报那一组一样要守住「一项设置只有一个编辑入口」：设置窗口里没有这一组的控件，保存时也不碰 ``slack_watch`` 这个键。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet import overlay_settings_command as cmd
from pet import slack_watch as sw
from pet.config import Config
from pet.settings_widgets import SettingRow

app = QApplication.instance() or QApplication([])

OLD_ROWS = ("slack_watch_enabled", "slack_watch_interval", "slack_watch_idle", "slack_watch_model",
            "slack_watch_model_custom", "slack_watch_effort", "slack_watch_prompt")


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


def _dialog(tmp_path, monkeypatch, *, language: str = "zh", **settings):
    from pet import modern_settings_dialog as settings_mod

    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    config = Config(tmp_path)
    config.set("ui_language", language)
    if settings:
        config.set(sw.CONFIG_KEY, sw.normalize(settings))
    config.save()
    return config, settings_mod.ModernSettingsDialog(config, include_ai=False)


def _row(dialog, row_id: str):
    return dialog.findChild(SettingRow, f"settingRow_{row_id}")


def _page_of(dialog, row_id: str) -> str:
    row = _row(dialog, row_id)
    assert row is not None, row_id
    for index in range(dialog.pages.count()):
        if dialog.pages.widget(index).isAncestorOf(row):
            return dialog.sidebar.item(index).text()
    return ""


def _close(dialog):
    dialog.close()
    dialog.deleteLater()
    app.processEvents()


def test_the_section_only_says_where_the_settings_went_and_keeps_the_archive_help(tmp_path, monkeypatch):
    _config, dialog = _dialog(tmp_path, monkeypatch, enabled=True, interval_minutes=30)
    try:
        assert all(_row(dialog, row_id) is None for row_id in OLD_ROWS), "控件留在这里就是两个编辑入口"
        assert not hasattr(dialog, "slack_watch_enabled_check")
        assert _page_of(dialog, "slack_watch_moved") == "简报与笔记"
        moved = _row(dialog, "slack_watch_moved")
        assert "Slack 关注" in moved.hint_label.text() and "配置全景" in moved.hint_label.text()
        assert dialog.slack_watch_open_panorama.text() == "到配置全景里改"
        assert _page_of(dialog, "slack_watch_archive") == "简报与笔记"
    finally:
        _close(dialog)


def test_the_button_asks_the_fish_to_open_the_panorama_at_this_group(tmp_path, monkeypatch):
    config, dialog = _dialog(tmp_path, monkeypatch)
    try:
        dialog.slack_watch_open_panorama.click()
        command = cmd.consume_command(config.dir)
        assert command["command"] == cmd.CMD_OPEN_PANORAMA and command["focus"] == "slack_watch"
    finally:
        _close(dialog)


def test_saving_the_window_leaves_what_the_page_wrote_alone(tmp_path, monkeypatch):
    _config, dialog = _dialog(tmp_path, monkeypatch, enabled=False, interval_minutes=15)
    try:
        page = Config(tmp_path)                                               # 窗口开着的时候，页面经主进程改了这一组
        page.set(sw.CONFIG_KEY, sw.normalize({"enabled": True, "interval_minutes": 45, "prompt": "页面上改的"}))
        assert page.save()
        assert dialog._write_config()
        saved = sw.normalize(Config(tmp_path).get(sw.CONFIG_KEY))
        assert saved["enabled"] is True and saved["interval_minutes"] == 45 and saved["prompt"] == "页面上改的"
    finally:
        _close(dialog)


def test_the_section_speaks_english(tmp_path, monkeypatch):
    _config, dialog = _dialog(tmp_path, monkeypatch, language="en")
    try:
        assert dialog.slack_watch_open_panorama.text() == "Change them in Config panorama"
        assert "Slack watch" in _row(dialog, "slack_watch_moved").hint_label.text()
    finally:
        _close(dialog)
