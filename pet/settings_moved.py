# -*- coding: utf-8 -*-
"""设置窗口里「这一组设置搬到配置全景了」那一行（决定见 docs/adr/0014-panorama-becomes-the-console.md）。

设置正一组一组从这扇窗搬到配置全景页面上。搬一组的那个 PR 同时把这一组的控件和保存代码从这里删掉——任何时刻一项设置
只有一个编辑入口，这扇窗保存时也就不会把页面刚改的值盖回去。原处不是空着，而是留这一行：说一句搬到哪了，
外加一个按钮，点了经设置进程 → 主进程的指令通道（``overlay_settings_command``）请主进程打开配置全景，并直接翻到这一组。

以后每搬一组，在那一节里换上 ``moved_row(dialog, "<组 id>")`` 就行。组 id 是 ``settings_table.GROUPS`` 里的。
这个模块在设置进程里跑：不许导入 ``pet.app`` 这类重模块。
"""
from __future__ import annotations

from . import overlay_settings_command as command
from . import settings_table
from .i18n import t
from .settings_widgets import SettingRow, TiltButton


def open_in_panorama(dialog, group_id: str) -> bool:
    """请主进程打开配置全景并翻到这一组。只是写一个指令文件，主进程三秒内会取走；返回写没写成。"""
    return command.write_command(dialog.config.dir, command.CMD_OPEN_PANORAMA, focus=group_id)


def moved_row(dialog, group_id: str) -> SettingRow:
    """「搬走了」那一行；按钮挂在 ``dialog.<组 id>_open_panorama`` 上。点过之后说明换成「已经请肥鱼打开了」或写不成的原因。"""
    group = settings_table.group(group_id)
    name = t(group.title_key)
    button = TiltButton(t("settings.moved.open"), dialog)
    button.setAccessibleName(t("settings.moved.open_accessible", name=name))
    row = SettingRow(f"{group_id}_moved", t("settings.moved.title"), t("settings.moved.hint", name=name), button)

    def clicked() -> None:
        sent = open_in_panorama(dialog, group_id)
        row.hint_label.setText(t("settings.moved.sent" if sent else "settings.moved.not_sent"))

    button.clicked.connect(clicked)
    setattr(dialog, f"{group_id}_open_panorama", button)
    return row
