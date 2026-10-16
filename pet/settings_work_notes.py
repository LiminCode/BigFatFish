# -*- coding: utf-8 -*-
"""设置页「工作笔记」一节（自动化与联动）：开关、仓库副本目录、模型，以及一个会解释整条流程的图标。

控件、提示、保存都在这里；逻辑见 ``work_notes.py``。用户 2026-10-15 的要求：进设置页时要带解释——
一个浮动的「流程」图标，鼠标放上去就讲清楚这条流程，免得日子久了忘了细节。文案全部走 ``i18n.t``。
没装 WSL 时开关置灰并说明原因。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QLineEdit, QWidget

from . import claude_hooks
from . import work_notes as wn
from .i18n import t
from .settings_widgets import ModernSelect, SettingRow, SettingsSection, ToggleSwitch

#: 模型下拉里的几个常用名（和 Slack 关注一致）；配置里写了别的也认（当作自定义）
MODEL_CHOICES = (("sonnet", "Sonnet"), ("haiku", "Haiku"), ("opus", "Opus"))
CUSTOM = "__custom__"


def section_title() -> str:
    return t("notes.settings.section")


def flow_section(dialog) -> SettingsSection:
    """「这个功能怎么运作」：默认收起的折叠节，展开是一块带排版的说明磁贴（用户 2026-10-15：悬停的
    tooltip 没有排版，改成折叠节）。说明文字放在设置行的提示标签里——它会按宽度换行、按主题取色；
    一个零尺寸的占位控件填「控件」那一格。挂 ``dialog.work_notes_flow_label`` / ``work_notes_flow_section``。"""
    placeholder = QWidget(dialog)
    placeholder.setFixedSize(0, 0)
    row = SettingRow("work_notes_flow", t("notes.settings.flow_hint"), t("notes.settings.flow_tooltip"), placeholder)
    label: QLabel = row.hint_label      # 保持 objectName=settingHint：颜色由设置页样式表给，改名就成了白字
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setAccessibleName(t("notes.settings.flow"))
    dialog.work_notes_flow_label = label
    section = SettingsSection(t("notes.settings.flow"), [row], advanced=True)
    dialog.work_notes_flow_section = section
    return section


def work_notes_rows(dialog) -> list[SettingRow]:
    """建出控件并返回设置行。挂在 ``dialog`` 上：``work_notes_enabled_check``、``work_notes_repo_edit``、
    ``work_notes_model_select``、``work_notes_model_edit``、``work_notes_flow_button``。"""
    settings = wn.normalize(dialog.config.get(wn.CONFIG_KEY))
    usable = bool(claude_hooks.wsl_exe())

    check = ToggleSwitch(dialog)
    check.setChecked(bool(settings["enabled"]) and usable)
    check.setEnabled(usable)
    dialog.work_notes_enabled_check = check

    repo = QLineEdit(dialog)
    repo.setText(settings["repo_dir"])
    repo.setPlaceholderText(wn.default_repo_dir())
    repo.setMinimumWidth(360)   # Windows 路径较长，窄了只看得见尾巴
    repo.setAccessibleName(t("notes.settings.repo_dir"))
    dialog.work_notes_repo_edit = repo

    select = ModernSelect(dialog, width=200)
    for value, label in MODEL_CHOICES:
        select.addItem(label, value)
    select.addItem(t("notes.settings.custom_choice"), CUSTOM)
    edit = QLineEdit(dialog)
    edit.setPlaceholderText("claude-sonnet-5-5")
    edit.setAccessibleName(t("notes.settings.custom_model"))
    known = {value for value, _label in MODEL_CHOICES}
    if settings["model"] in known:
        select.setCurrentIndex(max(0, select.findData(settings["model"])))
    else:
        select.setCurrentIndex(max(0, select.findData(CUSTOM)))
        edit.setText(settings["model"])
    edit.setVisible(select.currentData() == CUSTOM)
    select.currentIndexChanged.connect(lambda _index: edit.setVisible(select.currentData() == CUSTOM))
    dialog.work_notes_model_select = select
    dialog.work_notes_model_edit = edit

    return [
        SettingRow("work_notes_enabled", t("notes.settings.enabled"),
                   t("notes.settings.enabled_hint") if usable else t("notes.settings.no_wsl"), check),
        SettingRow("work_notes_repo_dir", t("notes.settings.repo_dir"), t("notes.settings.repo_dir_hint"), repo),
        SettingRow("work_notes_model", t("notes.settings.model"), t("notes.settings.model_hint"), select),
        SettingRow("work_notes_model_custom", t("notes.settings.custom_model"), "", edit, stacked=True),
    ]


def chosen_model(dialog) -> str:
    select = dialog.work_notes_model_select
    value = select.currentData()
    if value == CUSTOM:
        value = dialog.work_notes_model_edit.text()
    return wn.wb.normalize_model(value)


def save_work_notes_settings(dialog) -> None:
    check = getattr(dialog, "work_notes_enabled_check", None)
    if check is None:
        return
    current = wn.normalize(dialog.config.get(wn.CONFIG_KEY))
    dialog.config.set(wn.CONFIG_KEY, wn.normalize({
        **current,
        "enabled": check.isChecked(),
        "repo_dir": dialog.work_notes_repo_edit.text().strip(),
        "model": chosen_model(dialog),
    }))
