# -*- coding: utf-8 -*-
"""设置窗口里的「会话记忆蒸馏」一节（简报与笔记）。

这一节的设置搬到了配置全景（ADR 0014，路线图 M4），在 ``pet/settings_table.py`` 里分成两组声明：
「抽取与个人侧」（``distill_personal``：总开关、扫不扫 WSL、保留天数、公司目录、个人侧的时刻 / 模型 / 强度 / 镜像 / 提示词）
和「公司侧」（``distill_work``：``work_*`` 那几项）。这里只剩两行「搬到哪了」和折叠的「这个功能怎么运作」说明。
这扇窗保存时不碰 ``memory_distill`` 这个键，页面改的值不会被它盖回去。逻辑见 ``memory_distill.py``。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget

from .i18n import t
from .settings_moved import moved_row
from .settings_widgets import SettingRow, SettingsSection

GROUP_IDS = ("distill_personal", "distill_work")


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
    """两行「搬到配置全景了」：按钮挂在 ``dialog.distill_personal_open_panorama`` / ``dialog.distill_work_open_panorama``。"""
    return [moved_row(dialog, group_id) for group_id in GROUP_IDS]
