# -*- coding: utf-8 -*-
"""设置页「工作简报」一节（简报与笔记）。

**工作简报的设置已经搬到配置全景**（2026-11-17，路线图 M3；决定见 ADR 0014）：开关、时间、工作日、模型、effort、
六个来源、提示词、优先级偏好都在那边改（声明在 ``settings_table.GROUPS``）。这一节只剩：

- 一行「搬到配置全景了」加一个跳过去的按钮（``settings_moved.moved_row``）；
- 默认收起的「这个功能怎么运作」：怎么做、什么时候做、发给 Claude 什么、它能用什么工具、结果放哪。

这扇窗保存时不再碰 ``work_briefing`` 这个键，所以页面上改的值不会被它盖回去。
``effort_select`` 留在这里是因为 Slack 关注、工作笔记、会话记忆蒸馏三节还在用它。
"""
from __future__ import annotations

from . import claude_hooks  # noqa: F401 - 测试和别处经这里替换 wsl_exe
from . import work_briefing as wb
from .i18n import t
from .settings_help import help_section
from .settings_moved import moved_row
from .settings_widgets import ModernSelect, SettingRow, SettingsSection

GROUP_ID = "work_briefing"                       # settings_table 里的组 id


def effort_select(dialog, current: str) -> ModernSelect:
    """effort 下拉（四档）；Slack 关注 / 工作笔记 / 会话记忆蒸馏共用。"""
    select = ModernSelect(dialog, width=140)
    for value in wb.EFFORT_CHOICES:
        select.addItem(value, value)
    select.setCurrentIndex(max(0, select.findData(wb.normalize_effort(current))))
    return select


def section_title() -> str:
    return t("briefing.settings.section")


def flow_section(dialog) -> SettingsSection:
    """「这个功能怎么运作」：怎么做、什么时候做、发给 Claude 什么、它能用什么工具、结果放哪。"""
    section = help_section(dialog, "work_briefing_flow", t("briefing.settings.flow"), t("briefing.settings.flow_hint"),
                           t("briefing.settings.flow_tooltip"))
    dialog.work_briefing_flow_section = section
    return section


def work_briefing_rows(dialog) -> list[SettingRow]:
    """这一节的行：只有「搬到配置全景了」那一行。"""
    return [moved_row(dialog, GROUP_ID)]
