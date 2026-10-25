# -*- coding: utf-8 -*-
"""设置页「个人助理」一节（自动化与联动）：开关、AI-Base 克隆目录、每天几点、模型、思考强度，以及折叠的流程说明。

控件、提示、保存都在这里；逻辑见 ``personal_vault.py`` / ``personal_briefing.py``。模型与思考强度都能单独选
（用户 2026-10-17 要求），留「跟 AI 对话一致」就用聊天设置里的。没有 Windows 的 git 时开关照常可用（简报不需要
git），只在提示里说明灵感推不上去。文案全部走 ``i18n.t``。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QLineEdit, QWidget

from . import personal_vault as pv
from .i18n import t
from .settings_widgets import ModernSelect, SettingRow, SettingsSection, ToggleSwitch

SAME = ""              # 下拉里「跟 AI 对话一致」对应的值（配置里存空串）
CUSTOM = "__custom__"


def section_title() -> str:
    return t("personal.settings.section")


def flow_section(dialog) -> SettingsSection:
    """「这个功能怎么运作」：默认收起的折叠节（和工作笔记那节同一写法）。挂 ``dialog.personal_flow_label`` / ``personal_flow_section``。"""
    placeholder = QWidget(dialog)
    placeholder.setFixedSize(0, 0)
    row = SettingRow("personal_flow", t("personal.settings.flow_hint"), t("personal.settings.flow_tooltip"), placeholder)
    label: QLabel = row.hint_label      # 保持 objectName=settingHint：颜色由设置页样式表给
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setAccessibleName(t("personal.settings.flow"))
    dialog.personal_flow_label = label
    section = SettingsSection(t("personal.settings.flow"), [row], advanced=True)
    dialog.personal_flow_section = section
    return section


def personal_rows(dialog) -> list[SettingRow]:
    """建出控件并返回设置行。挂在 ``dialog`` 上：``personal_enabled_check``、``personal_repo_edit``、``personal_time_select``、
    ``personal_model_select`` / ``personal_model_edit``、``personal_effort_select``。"""
    settings = pv.normalize(dialog.config.get(pv.CONFIG_KEY))
    has_git = bool(pv.git_exe())

    check = ToggleSwitch(dialog)
    check.setChecked(bool(settings["enabled"]))
    dialog.personal_enabled_check = check

    repo = QLineEdit(dialog)
    repo.setText(settings["repo_dir"])
    repo.setPlaceholderText(pv.default_repo_dir())
    repo.setMinimumWidth(200)   # 比工作笔记那行窄：这行的标签更宽，控件再宽「自动化与联动」页在 720 的窄窗里就撑不下、别的行反而不换行（test_menu_layout 的 reflow 用例）
    repo.setAccessibleName(t("personal.settings.repo_dir"))
    dialog.personal_repo_edit = repo

    time_select = ModernSelect(dialog, width=120)
    choices = list(pv.TIME_CHOICES)
    if settings["time"] not in choices:
        choices.append(settings["time"])
        choices.sort()
    for value in choices:
        time_select.addItem(value, value)
    time_select.setCurrentIndex(max(0, time_select.findData(settings["time"])))
    dialog.personal_time_select = time_select

    model_select = ModernSelect(dialog, width=200)
    model_select.addItem(t("personal.settings.same_as_chat"), SAME)
    for value in pv.MODEL_CHOICES:
        model_select.addItem(value, value)
    model_select.addItem(t("personal.settings.custom_choice"), CUSTOM)
    model_edit = QLineEdit(dialog)
    model_edit.setPlaceholderText(pv.MODEL_CHOICES[0])
    model_edit.setAccessibleName(t("personal.settings.custom_model"))
    if settings["model"] in ("", *pv.MODEL_CHOICES):
        model_select.setCurrentIndex(max(0, model_select.findData(settings["model"])))
    else:
        model_select.setCurrentIndex(max(0, model_select.findData(CUSTOM)))
        model_edit.setText(settings["model"])
    model_edit.setVisible(model_select.currentData() == CUSTOM)
    model_select.currentIndexChanged.connect(lambda _index: model_edit.setVisible(model_select.currentData() == CUSTOM))
    dialog.personal_model_select = model_select
    dialog.personal_model_edit = model_edit

    effort_select = ModernSelect(dialog, width=160)
    effort_select.addItem(t("personal.settings.same_as_chat"), SAME)
    for level in pv.EFFORT_LEVELS:
        effort_select.addItem(f"{t('personal.settings.effort.' + level)} · {level}", level)
    effort_select.setCurrentIndex(max(0, effort_select.findData(settings["effort"])))
    dialog.personal_effort_select = effort_select

    enabled_hint = t("personal.settings.enabled_hint") + ("" if has_git else " " + t("personal.settings.no_git"))
    return [
        SettingRow("personal_enabled", t("personal.settings.enabled"), enabled_hint, check),
        SettingRow("personal_repo_dir", t("personal.settings.repo_dir"), t("personal.settings.repo_dir_hint"), repo),
        SettingRow("personal_time", t("personal.settings.time"), t("personal.settings.time_hint"), time_select),
        SettingRow("personal_model", t("personal.settings.model"), t("personal.settings.model_hint"), model_select),
        SettingRow("personal_model_custom", t("personal.settings.custom_model"), "", model_edit, stacked=True),
        SettingRow("personal_effort", t("personal.settings.effort"), t("personal.settings.effort_hint"), effort_select),
    ]


def chosen_model(dialog) -> str:
    value = dialog.personal_model_select.currentData()
    if value == CUSTOM:
        value = dialog.personal_model_edit.text()
    return pv.normalize_model(value)


def save_personal_settings(dialog) -> None:
    check = getattr(dialog, "personal_enabled_check", None)
    if check is None:
        return
    current = pv.normalize(dialog.config.get(pv.CONFIG_KEY))
    dialog.config.set(pv.CONFIG_KEY, pv.normalize({
        **current,
        "enabled": check.isChecked(),
        "repo_dir": dialog.personal_repo_edit.text().strip(),
        "time": dialog.personal_time_select.currentData(),
        "model": chosen_model(dialog),
        "effort": dialog.personal_effort_select.currentData(),
    }))
