# -*- coding: utf-8 -*-
"""设置窗口里的「Slack 关注」一节（简报与笔记）。

这一组的设置（开关、检查间隔、多久没动算离开、模型、effort、提示词）搬到了配置全景（ADR 0014，路线图 M4），
在 ``pet/settings_table.py`` 里声明；这里只剩「搬到哪了」那一行和折叠的「存档与 Slack 关注页」说明。
这扇窗保存时不碰 ``slack_watch`` 这个键，页面改的值不会被它盖回去。右键菜单里的开关和间隔由主进程直接写，照旧可用。
"""

from __future__ import annotations

from .i18n import t
from .settings_help import help_row
from .settings_moved import moved_row
from .settings_widgets import SettingRow

GROUP_ID = "slack_watch"


def slack_watch_rows(dialog) -> list[SettingRow]:
    return [
        moved_row(dialog, GROUP_ID),
        help_row(dialog, "slack_watch_archive", t("slack.notes.flow_title"), t("slack.notes.flow")),
    ]
