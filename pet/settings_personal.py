# -*- coding: utf-8 -*-
"""设置窗口里的「个人助理」一节（简报与笔记）。

这一组的设置（开关、AI-Base 克隆目录、每天几点、模型、思考强度）搬到了配置全景（ADR 0014，路线图 M4），
在 ``pet/settings_table.py`` 里声明；这里只剩「搬到哪了」那一行和折叠的「这个功能怎么运作」说明。
这扇窗保存时不碰 ``personal`` 这个键，页面改的值不会被它盖回去。逻辑见 ``personal_vault.py`` / ``personal_briefing.py``。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget

from .i18n import t
from .settings_moved import moved_row
from .settings_widgets import SettingRow, SettingsSection

GROUP_ID = "personal"


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
    return [moved_row(dialog, GROUP_ID)]
