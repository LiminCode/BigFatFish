# -*- coding: utf-8 -*-
"""设置窗口里的「工作简报」一节：设置已经搬到配置全景（ADR 0014，路线图 M3），这里只剩一行说明、一个跳过去的按钮和折叠的流程说明。

要守住的是「任何时刻一项设置只有一个编辑入口」：设置窗口里没有工作简报的控件，保存时也不碰这个键，
所以页面刚改的值不会被设置窗口的一次保存盖回去。按钮经设置进程 → 主进程的指令通道请主进程打开配置全景并翻到这一组。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet import overlay_settings_command as cmd
from pet import settings_work_briefing as swb
from pet import work_briefing as wb
from pet.config import Config
from pet.settings_widgets import SettingRow

app = QApplication.instance() or QApplication([])

OLD_ROWS = ("work_briefing_enabled", "work_briefing_weekdays", "work_briefing_time", "work_briefing_model",
            "work_briefing_model_custom", "work_briefing_effort", "work_briefing_prompt", "work_briefing_priority_rules",
            *(f"work_briefing_source_{s}" for s in wb.SOURCES))


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


def _dialog(tmp_path, monkeypatch, *, language: str = "zh", **settings):
    from pet import modern_settings_dialog as settings_mod

    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    monkeypatch.setattr(swb.claude_hooks, "wsl_exe", lambda: r"C:\Windows\System32\wsl.exe")
    config = Config(tmp_path)
    config.set("ui_language", language)
    if settings:
        config.set(wb.CONFIG_KEY, {**wb.normalize(None), **settings})
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


def test_the_section_only_says_where_the_settings_went_and_keeps_the_flow_help(tmp_path, monkeypatch):
    config, dialog = _dialog(tmp_path, monkeypatch, enabled=True, time="08:30")
    try:
        assert all(_row(dialog, row_id) is None for row_id in OLD_ROWS), "控件留在这里就是两个编辑入口"
        assert _page_of(dialog, "work_briefing_moved") == "简报与笔记"
        moved = _row(dialog, "work_briefing_moved")
        assert "配置全景" in moved.label.text() + moved.hint_label.text()
        assert dialog.work_briefing_open_panorama.text() == "到配置全景里改"
        assert dialog.work_briefing_open_panorama.accessibleName()
        body = _row(dialog, "work_briefing_flow").hint_label.text()
        for piece in ("什么时候", "发给 Claude 什么", "它能用什么", "结果放哪", "只读"):
            assert piece in body, piece
        assert dialog.work_briefing_flow_section.advanced, "说明默认收起"
    finally:
        _close(dialog)


def test_the_button_asks_the_fish_to_open_the_panorama_at_this_group(tmp_path, monkeypatch):
    config, dialog = _dialog(tmp_path, monkeypatch)
    try:
        dialog.work_briefing_open_panorama.click()
        command = cmd.consume_command(config.dir)
        assert command["command"] == cmd.CMD_OPEN_PANORAMA and command["focus"] == "work_briefing"
        assert "已经" in _row(dialog, "work_briefing_moved").hint_label.text()      # 点了有回应
    finally:
        _close(dialog)


def test_when_the_request_cannot_be_written_the_row_says_so(tmp_path, monkeypatch):
    config, dialog = _dialog(tmp_path, monkeypatch)
    monkeypatch.setattr(cmd, "write_command", lambda *a, **k: False)
    try:
        dialog.work_briefing_open_panorama.click()
        assert "没" in _row(dialog, "work_briefing_moved").hint_label.text()
    finally:
        _close(dialog)


def test_saving_the_window_leaves_what_the_page_wrote_alone(tmp_path, monkeypatch):
    config, dialog = _dialog(tmp_path, monkeypatch, enabled=False, time="09:00")
    try:
        page = Config(tmp_path)                                               # 窗口开着的时候，页面经主进程改了这一组
        page.set(wb.CONFIG_KEY, {**wb.normalize(None), "enabled": True, "time": "07:05", "prompt_zh": "页面上改的"})
        assert page.save()
        assert dialog._write_config()
        saved = wb.normalize(Config(tmp_path).get(wb.CONFIG_KEY))
        assert saved["enabled"] is True and saved["time"] == "07:05" and saved["prompt_zh"] == "页面上改的"
    finally:
        _close(dialog)


def test_the_section_speaks_english(tmp_path, monkeypatch):
    config, dialog = _dialog(tmp_path, monkeypatch, language="en")
    try:
        assert dialog.work_briefing_open_panorama.text() == "Change them in Config panorama"
        assert "Config panorama" in _row(dialog, "work_briefing_moved").hint_label.text()
        body = _row(dialog, "work_briefing_flow").hint_label.text()
        assert "What is sent to Claude" in body and "read-only" in body
    finally:
        _close(dialog)


# ---------------------------------------------------------------- 「简报与笔记」一级域（2026-10-24）

def _section_titles(page) -> list[str]:
    from pet.settings_widgets import SettingsSection

    return [s.title for s in page.findChildren(SettingsSection) if s.title]


def test_the_ai_assisted_sections_have_their_own_page_in_order(tmp_path, monkeypatch):
    """用户 2026-10-24：简报这些「定时让 AI 读、AI 协助记」的功能放到第一层，别埋在自动化与联动里。"""
    config, dialog = _dialog(tmp_path, monkeypatch)
    try:
        labels = [dialog.sidebar.item(i).text() for i in range(dialog.sidebar.count())]
        # 紧挨在「自动化与联动」前面（本夹具 include_ai=False，没有「AI 与对话」页）
        assert labels.index("简报与笔记") == labels.index("自动化与联动") - 1
        titles = _section_titles(dialog.pages.widget(labels.index("简报与笔记")))
        assert titles[:1] == ["这一页是什么"]
        wanted = ("工作简报", "Slack 关注", "工作笔记", "个人助理")
        assert [x for x in titles if x in wanted] == list(wanted)
        automation = _section_titles(dialog.pages.widget(labels.index("自动化与联动")))
        assert not any(x in wanted for x in automation), "搬走之后旧页不该再有"
        assert dialog.select_page("简报与笔记") and dialog.sidebar.currentItem().text() == "简报与笔记"
    finally:
        _close(dialog)


def test_the_page_speaks_english(tmp_path, monkeypatch):
    config, dialog = _dialog(tmp_path, monkeypatch, language="en")
    try:
        labels = [dialog.sidebar.item(i).text() for i in range(dialog.sidebar.count())]
        assert "Briefings & notes" in labels
        assert dialog.select_page("简报与笔记") and dialog.sidebar.currentItem().text() == "Briefings & notes"
    finally:
        _close(dialog)
