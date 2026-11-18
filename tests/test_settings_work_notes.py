# -*- coding: utf-8 -*-
"""设置窗口里的「工作笔记」一节：设置已经搬到配置全景（ADR 0014，路线图 M4），这里只剩一行说明、一个跳过去的按钮
和折叠的「这个功能怎么运作」说明（用户 2026-10-15：进设置页要带解释，免得日久忘了细节）。

和工作简报、Slack 关注一样要守住「一项设置只有一个编辑入口」：设置窗口里没有这一组的控件，保存时也不碰 ``work_notes`` 这个键。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet import overlay_settings_command as cmd
from pet import work_notes as wn
from pet.config import Config
from pet.settings_widgets import SettingRow

app = QApplication.instance() or QApplication([])

OLD_ROWS = ("work_notes_enabled", "work_notes_repo_dir", "work_notes_model", "work_notes_model_custom",
            "work_notes_effort", "work_notes_prompt")


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
        config.set(wn.CONFIG_KEY, wn.normalize(settings))
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
    _config, dialog = _dialog(tmp_path, monkeypatch, enabled=True, repo_dir=r"D:\notes\AI-Base-Memory", model="haiku")
    try:
        assert all(_row(dialog, row_id) is None for row_id in OLD_ROWS), "控件留在这里就是两个编辑入口"
        assert not hasattr(dialog, "work_notes_enabled_check") and not hasattr(dialog, "work_notes_prompt_editor")
        assert _page_of(dialog, "work_notes_moved") == "简报与笔记"
        moved = _row(dialog, "work_notes_moved")
        assert "工作笔记" in moved.hint_label.text() and "配置全景" in moved.hint_label.text()
        assert dialog.work_notes_open_panorama.text() == "到配置全景里改"
    finally:
        _close(dialog)


def test_the_flow_still_lives_in_a_collapsed_section_with_formatted_text(tmp_path, monkeypatch):
    from PySide6.QtCore import Qt

    _config, dialog = _dialog(tmp_path, monkeypatch)
    try:
        section = dialog.work_notes_flow_section
        assert section.toggle is not None and section.toggle.text() == "这个功能怎么运作"
        assert not section.card.isVisibleTo(section), "默认收起"
        section.toggle.setChecked(True)
        assert section.card.isVisibleTo(section), "点一下展开"
        label = dialog.work_notes_flow_label
        assert label.textFormat() == Qt.TextFormat.RichText and label.wordWrap()
        for step in ("<b>", "1.", "2.", "3.", "4.", "5.", "只读", "Obsidian", "AI-Base-Memory", "token"):
            assert step in label.text(), step
        assert _page_of(dialog, "work_notes_flow") == "简报与笔记"
    finally:
        _close(dialog)


def test_the_button_asks_the_fish_to_open_the_panorama_at_this_group(tmp_path, monkeypatch):
    config, dialog = _dialog(tmp_path, monkeypatch)
    try:
        dialog.work_notes_open_panorama.click()
        command = cmd.consume_command(config.dir)
        assert command["command"] == cmd.CMD_OPEN_PANORAMA and command["focus"] == "work_notes"
    finally:
        _close(dialog)


def test_saving_the_window_leaves_what_the_page_wrote_alone(tmp_path, monkeypatch):
    _config, dialog = _dialog(tmp_path, monkeypatch, enabled=True, model="sonnet")
    try:
        page = Config(tmp_path)                                               # 窗口开着的时候，页面经主进程改了这一组
        page.set(wn.CONFIG_KEY, wn.normalize({"enabled": False, "repo_dir": r"E:\mem", "model": "opus", "prompt_en": "from the page"}))
        assert page.save()
        assert dialog._write_config()
        saved = wn.normalize(Config(tmp_path).get(wn.CONFIG_KEY))
        assert saved["enabled"] is False and saved["repo_dir"] == r"E:\mem" and saved["model"] == "opus"
        assert saved["prompt_en"] == "from the page"
    finally:
        _close(dialog)


def test_the_section_speaks_english(tmp_path, monkeypatch):
    _config, dialog = _dialog(tmp_path, monkeypatch, language="en")
    try:
        assert dialog.work_notes_open_panorama.text() == "Change them in Config panorama"
        assert "Work notes" in _row(dialog, "work_notes_moved").hint_label.text()
        assert _row(dialog, "work_notes_flow").label.text().startswith("Expand to see")
        assert "read-only" in dialog.work_notes_flow_label.text()
        assert dialog.work_notes_flow_section.toggle.text() == "How it works"
    finally:
        _close(dialog)
