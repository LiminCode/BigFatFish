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
            assert _page_of(dialog, row_id) == "简报与笔记", row_id
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
                         "effort": "high", "prompt_zh": "", "prompt_en": "", "priority_rules": "",
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


# ---------------------------------------------------------------- effort / 提示词 / 优先级偏好（2026-10-24）

def test_effort_prompt_and_priority_rows_exist_and_show_the_builtin_prompt(tmp_path, monkeypatch):
    config, dialog = _dialog(tmp_path, monkeypatch, effort="medium",
                             sources={**wb.DEFAULT_SOURCES, "email": True})
    try:
        for row_id in ("work_briefing_effort", "work_briefing_prompt", "work_briefing_priority_rules"):
            assert _page_of(dialog, row_id) == "简报与笔记", row_id
        assert dialog.work_briefing_effort_select.currentData() == "medium"
        # 没改过：编辑框里是按当前来源开关拼出的内置模板（含邮件那一段），「恢复内置」置灰
        shown = dialog.work_briefing_prompt_edit.toPlainText()
        assert shown == wb.default_prompt_template("zh", {**wb.DEFAULT_SOURCES, "email": True})
        assert "邮件" in shown and "{now}" in shown and "{prs}" in shown
        assert not dialog.work_briefing_prompt_restore.isEnabled()
        assert dialog.work_briefing_priority_rules_edit.toPlainText() == ""
        hint = dialog.findChild(SettingRow, "settingRow_work_briefing_prompt").hint_label.text()
        assert "{now}" in hint and "来源开关" in hint
    finally:
        _close(dialog)


def test_saving_stores_the_prompt_only_when_it_differs_from_the_builtin(tmp_path, monkeypatch):
    config, dialog = _dialog(tmp_path, monkeypatch)
    try:
        dialog.work_briefing_effort_select.setCurrentIndex(dialog.work_briefing_effort_select.findData("xhigh"))
        dialog.work_briefing_priority_rules_edit.setPlainText("  QA 报的 bug 一律 ★★★  ")
        swb.save_work_briefing_settings(dialog)
        saved = config.get(wb.CONFIG_KEY)
        assert saved["effort"] == "xhigh" and saved["priority_rules"] == "QA 报的 bug 一律 ★★★"
        assert saved["prompt_zh"] == "" and saved["prompt_en"] == "", "和内置一字不差 → 存空串，跟着以后的版本更新"

        dialog.work_briefing_prompt_edit.setPlainText("我的模板 {now} {prs}")
        assert dialog.work_briefing_prompt_restore.isEnabled()
        swb.save_work_briefing_settings(dialog)
        assert config.get(wb.CONFIG_KEY)["prompt_zh"] == "我的模板 {now} {prs}"
        assert config.get(wb.CONFIG_KEY)["prompt_en"] == "", "只存当前界面语言那一份"

        dialog.work_briefing_prompt_restore.click()
        assert dialog.work_briefing_prompt_edit.toPlainText() == wb.default_prompt_template("zh", wb.DEFAULT_SOURCES)
        assert not dialog.work_briefing_prompt_restore.isEnabled()
        swb.save_work_briefing_settings(dialog)
        assert config.get(wb.CONFIG_KEY)["prompt_zh"] == ""
    finally:
        _close(dialog)


def test_an_edited_prompt_is_shown_on_reopen_and_the_english_page_edits_the_english_one(tmp_path, monkeypatch):
    config, dialog = _dialog(tmp_path, monkeypatch, prompt_zh="改过的中文模板 {now}")
    try:
        assert dialog.work_briefing_prompt_edit.toPlainText() == "改过的中文模板 {now}"
        assert dialog.work_briefing_prompt_restore.isEnabled()
    finally:
        _close(dialog)
    config, dialog = _dialog(tmp_path, monkeypatch, language="en", prompt_zh="改过的中文模板 {now}")
    try:
        assert dialog.work_briefing_prompt_edit.toPlainText() == wb.default_prompt_template("en", wb.DEFAULT_SOURCES)
        assert dialog.findChild(SettingRow, "settingRow_work_briefing_effort").label.text() == "Effort"
        dialog.work_briefing_prompt_edit.setPlainText("my template {now}")
        swb.save_work_briefing_settings(dialog)
        saved = config.get(wb.CONFIG_KEY)
        assert saved["prompt_en"] == "my template {now}" and saved["prompt_zh"] == "改过的中文模板 {now}"
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
