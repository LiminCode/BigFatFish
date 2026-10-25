# -*- coding: utf-8 -*-
"""设置页「工作简报」一节（自动化与联动）：开关、只在工作日、几点、模型、**包含哪些来源**，以及折叠的流程说明。

此前简报只能在右键菜单里开关与定时，来源是写死的；用户 2026-10-19 要求能说明「怎么做、什么时候做、
发给 Claude 什么」，并且来源可配置（邮件 / Slack / Jira / GitHub PR / 日历 / 建议）。逻辑见 ``work_briefing.py``：
来源开关决定提示词里列哪些来源、输出哪几节，以及放行给 Claude Code 的只读工具。文案全部走 ``i18n.t``；
没装 WSL 时开关置灰并说明原因。
"""
from __future__ import annotations

from PySide6.QtWidgets import QLineEdit

from . import claude_hooks
from . import work_briefing as wb
from .i18n import t
from .settings_help import help_section
from .settings_widgets import ModernSelect, SettingRow, SettingsSection, ToggleSwitch

MODEL_CHOICES = (("sonnet", "Sonnet"), ("haiku", "Haiku"), ("opus", "Opus"))
CUSTOM = "__custom__"


def section_title() -> str:
    return t("briefing.settings.section")


def flow_section(dialog) -> SettingsSection:
    """「这个功能怎么运作」：怎么做、什么时候做、发给 Claude 什么、它能用什么工具、结果放哪。"""
    section = help_section(dialog, "work_briefing_flow", t("briefing.settings.flow"), t("briefing.settings.flow_hint"),
                           t("briefing.settings.flow_tooltip"))
    dialog.work_briefing_flow_section = section
    return section


def work_briefing_rows(dialog) -> list[SettingRow]:
    """建出控件并返回设置行。挂在 ``dialog`` 上：``work_briefing_enabled_check``、``work_briefing_weekdays_check``、
    ``work_briefing_time_select``、``work_briefing_model_select`` / ``_edit``、``work_briefing_source_checks``。"""
    settings = wb.normalize(dialog.config.get(wb.CONFIG_KEY))
    usable = bool(claude_hooks.wsl_exe())

    check = ToggleSwitch(dialog)
    check.setChecked(bool(settings["enabled"]) and usable)
    check.setEnabled(usable)
    dialog.work_briefing_enabled_check = check

    weekdays = ToggleSwitch(dialog)
    weekdays.setChecked(bool(settings["weekdays_only"]))
    dialog.work_briefing_weekdays_check = weekdays

    time_select = ModernSelect(dialog, width=120)
    choices = list(wb.TIME_CHOICES)
    if settings["time"] not in choices:
        choices.append(settings["time"])
        choices.sort()
    for value in choices:
        time_select.addItem(value, value)
    time_select.setCurrentIndex(max(0, time_select.findData(settings["time"])))
    dialog.work_briefing_time_select = time_select

    select = ModernSelect(dialog, width=200)
    for value, label in MODEL_CHOICES:
        select.addItem(label, value)
    select.addItem(t("briefing.settings.custom_choice"), CUSTOM)
    edit = QLineEdit(dialog)
    edit.setPlaceholderText("claude-sonnet-5-5")
    edit.setAccessibleName(t("briefing.settings.custom_model"))
    known = {value for value, _label in MODEL_CHOICES}
    if settings["model"] in known:
        select.setCurrentIndex(max(0, select.findData(settings["model"])))
    else:
        select.setCurrentIndex(max(0, select.findData(CUSTOM)))
        edit.setText(settings["model"])
    edit.setVisible(select.currentData() == CUSTOM)
    select.currentIndexChanged.connect(lambda _index: edit.setVisible(select.currentData() == CUSTOM))
    dialog.work_briefing_model_select = select
    dialog.work_briefing_model_edit = edit

    rows = [
        SettingRow("work_briefing_enabled", t("briefing.settings.enabled"),
                   t("briefing.settings.enabled_hint") if usable else t("briefing.settings.no_wsl"), check),
        SettingRow("work_briefing_weekdays", t("briefing.settings.weekdays"), t("briefing.settings.weekdays_hint"), weekdays),
        SettingRow("work_briefing_time", t("briefing.settings.time"), t("briefing.settings.time_hint"), time_select),
        SettingRow("work_briefing_model", t("briefing.settings.model"), t("briefing.settings.model_hint"), select),
        SettingRow("work_briefing_model_custom", t("briefing.settings.custom_model"), "", edit, stacked=True),
    ]
    dialog.work_briefing_source_checks = {}
    for source in wb.SOURCES:
        toggle = ToggleSwitch(dialog)
        toggle.setChecked(bool(settings["sources"].get(source)))
        dialog.work_briefing_source_checks[source] = toggle
        rows.append(SettingRow(f"work_briefing_source_{source}", t(f"briefing.settings.source.{source}"),
                               t(f"briefing.settings.source.{source}_hint"), toggle))
    return rows


def chosen_model(dialog) -> str:
    value = dialog.work_briefing_model_select.currentData()
    if value == CUSTOM:
        value = dialog.work_briefing_model_edit.text()
    return wb.normalize_model(value)


def save_work_briefing_settings(dialog) -> None:
    check = getattr(dialog, "work_briefing_enabled_check", None)
    if check is None:
        return
    current = wb.normalize(dialog.config.get(wb.CONFIG_KEY))
    dialog.config.set(wb.CONFIG_KEY, wb.normalize({
        **current,
        "enabled": check.isChecked(),
        "weekdays_only": dialog.work_briefing_weekdays_check.isChecked(),
        "time": dialog.work_briefing_time_select.currentData(),
        "model": chosen_model(dialog),
        "sources": {source: toggle.isChecked() for source, toggle in dialog.work_briefing_source_checks.items()},
    }))
