# -*- coding: utf-8 -*-
"""设置窗口里的「个人助理」一节：设置已经搬到配置全景（ADR 0014，路线图 M4），这里只剩一行说明、一个跳过去的按钮
和折叠的「这个功能怎么运作」说明。

和前面几组一样要守住「一项设置只有一个编辑入口」：设置窗口里没有这一组的控件，保存时也不碰 ``personal`` 这个键。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet import overlay_settings_command as cmd
from pet import personal_vault as pv
from pet.config import Config
from pet.settings_widgets import SettingRow

app = QApplication.instance() or QApplication([])

OLD_ROWS = ("personal_enabled", "personal_repo_dir", "personal_time", "personal_model", "personal_model_custom", "personal_effort")


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
        config.set(pv.CONFIG_KEY, pv.normalize(settings))
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


def test_the_section_only_says_where_the_settings_went(tmp_path, monkeypatch):
    _config, dialog = _dialog(tmp_path, monkeypatch, enabled=True, repo_dir=r"D:\vault\AI-Base", time="07:30")
    try:
        assert all(_row(dialog, row_id) is None for row_id in OLD_ROWS), "控件留在这里就是两个编辑入口"
        assert not hasattr(dialog, "personal_enabled_check") and not hasattr(dialog, "personal_model_select")
        assert _page_of(dialog, "personal_moved") == "简报与笔记"
        moved = _row(dialog, "personal_moved")
        assert "个人助理" in moved.hint_label.text() and "配置全景" in moved.hint_label.text()
        assert dialog.personal_open_panorama.text() == "到配置全景里改"
    finally:
        _close(dialog)


def test_the_flow_still_lives_in_a_collapsed_section(tmp_path, monkeypatch):
    _config, dialog = _dialog(tmp_path, monkeypatch)
    try:
        section = dialog.personal_flow_section
        assert section.toggle is not None and not section.card.isVisibleTo(section), "默认收起"
        assert "<b>" in dialog.personal_flow_label.text() and "只读" in dialog.personal_flow_label.text()
        assert _page_of(dialog, "personal_flow") == "简报与笔记"
    finally:
        _close(dialog)


def test_the_button_asks_the_fish_to_open_the_panorama_at_this_group(tmp_path, monkeypatch):
    config, dialog = _dialog(tmp_path, monkeypatch)
    try:
        dialog.personal_open_panorama.click()
        command = cmd.consume_command(config.dir)
        assert command["command"] == cmd.CMD_OPEN_PANORAMA and command["focus"] == "personal"
    finally:
        _close(dialog)


def test_saving_the_window_leaves_what_the_page_wrote_alone(tmp_path, monkeypatch):
    _config, dialog = _dialog(tmp_path, monkeypatch, enabled=False, time="08:30")
    try:
        page = Config(tmp_path)                                               # 窗口开着的时候，页面经主进程改了这一组
        page.set(pv.CONFIG_KEY, pv.normalize({"enabled": True, "repo_dir": r"E:\AI-Base", "time": "21:00",
                                              "model": "claude-haiku-5-5", "effort": "max"}))
        assert page.save()
        assert dialog._write_config()
        saved = pv.normalize(Config(tmp_path).get(pv.CONFIG_KEY))
        assert saved == {"enabled": True, "repo_dir": r"E:\AI-Base", "time": "21:00", "model": "claude-haiku-5-5", "effort": "max"}
    finally:
        _close(dialog)


def test_the_section_speaks_english(tmp_path, monkeypatch):
    _config, dialog = _dialog(tmp_path, monkeypatch, language="en")
    try:
        assert dialog.personal_open_panorama.text() == "Change them in Config panorama"
        assert "Personal assistant" in _row(dialog, "personal_moved").hint_label.text()
        assert "How the personal assistant flows" in dialog.personal_flow_label.text()
    finally:
        _close(dialog)
