# -*- coding: utf-8 -*-
"""设置窗口里的「工作笔记」一节（简报与笔记）。

这一组的设置（开关、仓库副本目录、模型、effort、中 / 英文提示词）搬到了配置全景（ADR 0014，路线图 M4），
在 ``pet/settings_table.py`` 里声明；这里只剩「搬到哪了」那一行和折叠的「这个功能怎么运作」说明
（用户 2026-10-15：进设置页要带解释，免得日子久了忘了细节）。这扇窗保存时不碰 ``work_notes`` 这个键，
页面改的值不会被它盖回去。逻辑见 ``work_notes.py``。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget

from .i18n import t
from .settings_moved import moved_row
from .settings_widgets import SettingRow, SettingsSection

GROUP_ID = "work_notes"


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
    return [moved_row(dialog, GROUP_ID)]
