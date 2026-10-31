# -*- coding: utf-8 -*-
"""设置页「会话记忆蒸馏」一节（自动化与联动）：开关、保留天数、公司目录、每日时刻、模型、思考强度、提示词，
以及折叠的流程说明。

控件、提示、保存都在这里；逻辑见 ``memory_distill.py``。按用户 2026-10-24 的规矩，让 AI 干活的功能一开始就把
提示词明文摆出来、模型与 effort 可选、时机可调——第一期还不调模型，但这些项已经在。文案全部走 ``i18n.t``。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QLineEdit, QWidget

from . import memory_distill as md
from .i18n import t
from .settings_prompt_editor import PromptEditor
from .settings_widgets import ModernSelect, SettingRow, SettingsSection, ToggleSwitch
from .settings_work_briefing import effort_select

KEEP_DAYS_CHOICES = (30, 60, 90, 180, 365)
TIME_CHOICES = ("20:00", "21:00", "21:30", "22:00", "23:00")
ROOTS_SEPARATOR = ";"


def section_title() -> str:
    return t("distill.settings.section")


def flow_section(dialog) -> SettingsSection:
    """「这个功能怎么运作」：默认收起的折叠节（和工作笔记那节同一写法）。挂 ``dialog.distill_flow_label`` / ``distill_flow_section``。"""
    placeholder = QWidget(dialog)
    placeholder.setFixedSize(0, 0)
    row = SettingRow("distill_flow", t("distill.settings.flow_hint"), t("distill.settings.flow_tooltip"), placeholder)
    label: QLabel = row.hint_label      # 保持 objectName=settingHint：颜色由设置页样式表给
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setAccessibleName(t("distill.settings.flow"))
    dialog.distill_flow_label = label
    section = SettingsSection(t("distill.settings.flow"), [row], advanced=True)
    dialog.distill_flow_section = section
    return section


def distill_rows(dialog) -> list[SettingRow]:
    """建出控件并返回设置行。挂在 ``dialog`` 上：``distill_enabled_check``、``distill_keep_days_select``、
    ``distill_roots_edit``、``distill_time_select``、``distill_model_edit``、``distill_effort_select``、``distill_prompt_editor``。"""
    settings = md.normalize(dialog.config.get(md.CONFIG_KEY))

    check = ToggleSwitch(dialog)
    check.setChecked(bool(settings["enabled"]))
    dialog.distill_enabled_check = check

    keep = ModernSelect(dialog, width=120)
    for days in sorted({*KEEP_DAYS_CHOICES, settings["keep_days"]}):
        keep.addItem(t("distill.settings.days", days=days), days)
    keep.setCurrentIndex(max(0, keep.findData(settings["keep_days"])))
    dialog.distill_keep_days_select = keep

    roots = QLineEdit(dialog)
    roots.setText(ROOTS_SEPARATOR.join(settings["work_roots"]))
    roots.setPlaceholderText(md.default_work_root())
    roots.setMinimumWidth(200)
    roots.setAccessibleName(t("distill.settings.work_roots_label"))
    dialog.distill_roots_edit = roots

    time_select = ModernSelect(dialog, width=120)
    for choice in sorted({*TIME_CHOICES, settings["daily_at"]}):
        time_select.addItem(choice, choice)
    time_select.setCurrentIndex(max(0, time_select.findData(settings["daily_at"])))
    dialog.distill_time_select = time_select

    model = QLineEdit(dialog)
    model.setText(settings["model"])
    model.setPlaceholderText(md.DEFAULT_MODEL)
    model.setAccessibleName(t("distill.settings.model_label"))
    dialog.distill_model_edit = model
    effort = effort_select(dialog, settings["effort"])
    dialog.distill_effort_select = effort

    language = md.wb.prompt_language()
    prompt = PromptEditor(dialog, default=md.default_prompt_template(language), stored=settings[f"prompt_{language}"],
                          accessible_name=t("distill.settings.prompt"))
    dialog.distill_prompt_editor = prompt
    dialog.distill_prompt_language = language

    return [
        SettingRow("distill_enabled", t("distill.settings.enabled"), t("distill.settings.enabled_hint"), check),
        SettingRow("distill_keep_days", t("distill.settings.keep_days_label"), t("distill.settings.keep_days_hint"), keep),
        SettingRow("distill_work_roots", t("distill.settings.work_roots_label"), t("distill.settings.work_roots_hint"), roots),
        SettingRow("distill_daily_at", t("distill.settings.daily_at_label"), t("distill.settings.daily_at_hint"), time_select),
        SettingRow("distill_model", t("distill.settings.model_label"), t("distill.settings.model_hint"), model),
        SettingRow("distill_effort", t("distill.settings.effort_label"), t("distill.settings.effort_hint"), effort),
        SettingRow("distill_prompt", t("distill.settings.prompt"), t("distill.settings.prompt_hint"), prompt, stacked=True),
    ]


def save_distill_settings(dialog) -> None:
    check = getattr(dialog, "distill_enabled_check", None)
    if check is None:
        return
    current = md.normalize(dialog.config.get(md.CONFIG_KEY))
    roots = [part.strip() for part in dialog.distill_roots_edit.text().split(ROOTS_SEPARATOR) if part.strip()]
    dialog.config.set(md.CONFIG_KEY, md.normalize({
        **current,
        "enabled": check.isChecked(),
        "keep_days": dialog.distill_keep_days_select.currentData(),
        "work_roots": roots,
        "daily_at": dialog.distill_time_select.currentData(),
        "model": dialog.distill_model_edit.text().strip(),
        "effort": dialog.distill_effort_select.currentData(),
        f"prompt_{dialog.distill_prompt_language}": dialog.distill_prompt_editor.value(),
    }))
