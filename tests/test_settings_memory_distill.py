# -*- coding: utf-8 -*-
"""设置窗口里的「会话记忆蒸馏」一节：设置已经搬到配置全景（ADR 0014，路线图 M4），分成「抽取与个人侧」「公司侧」两组，
这里只剩两行说明、两个跳过去的按钮和折叠的「这个功能怎么运作」说明。

和前面几组一样要守住「一项设置只有一个编辑入口」：设置窗口里没有这两组的控件，保存时也不碰 ``memory_distill`` 这个键。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet import memory_distill as md
from pet import overlay_settings_command as cmd
from pet.config import Config
from pet.settings_widgets import SettingRow

app = QApplication.instance() or QApplication([])

OLD_ROWS = tuple(f"distill_{key}" for key in (
    "enabled", "scan_wsl", "keep_days", "work_roots", "daily_at", "model", "model_custom", "effort", "mirror", "prompt",
    "work_distill", "work_daily_at", "work_model", "work_model_custom", "work_effort", "work_mirror", "work_prompt"))


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
        config.set(md.CONFIG_KEY, md.normalize(settings))
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
    _config, dialog = _dialog(tmp_path, monkeypatch, enabled=True, keep_days=60, work_roots=[r"D:\Corp"])
    try:
        assert all(_row(dialog, row_id) is None for row_id in OLD_ROWS), "控件留在这里就是两个编辑入口"
        assert not hasattr(dialog, "distill_enabled_check") and not hasattr(dialog, "distill_work_check")
        for group_id, words in (("distill_personal", "个人侧"), ("distill_work", "公司侧")):
            assert _page_of(dialog, f"{group_id}_moved") == "简报与笔记"
            hint = _row(dialog, f"{group_id}_moved").hint_label.text()
            assert "会话记忆蒸馏" in hint and words in hint and "配置全景" in hint
            assert getattr(dialog, f"{group_id}_open_panorama").text() == "到配置全景里改"
    finally:
        _close(dialog)


def test_the_flow_still_lives_in_a_collapsed_section(tmp_path, monkeypatch):
    _config, dialog = _dialog(tmp_path, monkeypatch)
    try:
        section = dialog.distill_flow_section
        assert section.toggle is not None and not section.card.isVisibleTo(section), "默认收起"
        assert "<b>" in dialog.distill_flow_label.text() and "抽取" in dialog.distill_flow_label.text()
        assert _page_of(dialog, "distill_flow") == "简报与笔记"
    finally:
        _close(dialog)


@pytest.mark.parametrize("group_id", ["distill_personal", "distill_work"])
def test_each_button_asks_the_fish_to_open_the_panorama_at_its_group(tmp_path, monkeypatch, group_id):
    config, dialog = _dialog(tmp_path, monkeypatch)
    try:
        getattr(dialog, f"{group_id}_open_panorama").click()
        command = cmd.consume_command(config.dir)
        assert command["command"] == cmd.CMD_OPEN_PANORAMA and command["focus"] == group_id
    finally:
        _close(dialog)


def test_saving_the_window_leaves_what_the_page_wrote_alone(tmp_path, monkeypatch):
    _config, dialog = _dialog(tmp_path, monkeypatch, enabled=False, keep_days=60)
    try:
        page = Config(tmp_path)                                               # 窗口开着的时候，页面经主进程改了这两组
        written = md.normalize({"enabled": True, "keep_days": 180, "work_roots": [r"F:\Only"], "model": "claude-haiku-5-5",
                                "scan_wsl": False, "work_distill": False, "work_model": "opus", "work_prompt_zh": "公司侧：{candidates}"})
        page.set(md.CONFIG_KEY, written)
        assert page.save()
        assert dialog._write_config()
        assert md.normalize(Config(tmp_path).get(md.CONFIG_KEY)) == written
    finally:
        _close(dialog)


def test_the_section_speaks_english(tmp_path, monkeypatch):
    _config, dialog = _dialog(tmp_path, monkeypatch, language="en")
    try:
        assert dialog.distill_personal_open_panorama.text() == "Change them in Config panorama"
        assert "work side" in _row(dialog, "distill_work_moved").hint_label.text()
        assert "personal side" in _row(dialog, "distill_personal_moved").hint_label.text()
    finally:
        _close(dialog)
