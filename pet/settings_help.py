# -*- coding: utf-8 -*-
"""设置页里的「这些设定怎么起作用」说明行：一行带排版（RichText）的长文，放进默认收起的折叠节。

工作笔记 / 个人助理的 ``flow_section`` 是同一写法；这里抽成通用的，给「人设与回复」「文案风格与模板」
这类纯解释用。说明文字放在设置行的提示标签里——它会按宽度换行、按主题取色；一个零尺寸的占位控件填
「控件」那一格。提示标签保持 objectName=settingHint：颜色由设置页样式表给，改名就成了白字。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget

from .settings_widgets import SettingRow, SettingsSection


def help_row(parent: QWidget, key: str, title: str, body_html: str, accessible_name: str = "") -> SettingRow:
    """一行说明：``title`` 是行标题（一句引子），``body_html`` 是带 <b> / <br> 的正文。"""
    placeholder = QWidget(parent)
    placeholder.setFixedSize(0, 0)
    row = SettingRow(key, title, body_html, placeholder)
    label: QLabel = row.hint_label
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setAccessibleName(accessible_name or title)
    return row


def help_section(parent: QWidget, key: str, section_title: str, title: str, body_html: str) -> SettingsSection:
    """默认收起的折叠节，里面只有一行说明。"""
    return SettingsSection(section_title, [help_row(parent, key, title, body_html, section_title)], parent, advanced=True)
