# -*- coding: utf-8 -*-
"""设置页「灵动岛 · 名字」：改岛上显示的名字（2026-11-14 用户问「为什么是 shenshen、在哪改」）。

岛上的名字就是当前角色的显示名（``Config.character_display_name``）：用户起的名字优先，
没起用角色包 manifest 的 ``name``，再没有就是角色 id——内置的 ``shenshen`` 包没写 name，
所以没改过名时岛上是 ``shenshen``。以前只能从右键菜单「切换角色 → 重命名当前角色…」改，
设置页里找不到。

这一行改的是同一个值（``character_aliases[当前角色]``），不另起一个「岛专用名」：
菜单、聊天窗、主动识屏提示里的名字跟着一起变，免得同一条鱼有两个名字。

- 留空 = 恢复默认（占位提示里写着默认名）；最长 24 字，和菜单改名一致；
- 跟「保存」一起生效；**没动这一栏就不写**——设置开着时用户从右键菜单改了名，
  保存不能把那个名字冲回打开设置时的旧值。
"""

from __future__ import annotations

from . import catalog
from .i18n import t
from .settings_widgets import _line_edit

#: 与 ``Config.set_character_alias`` 的截断长度一致
MAX_LENGTH = 24


def _current_character(config) -> str:
    return str(config.get("character", catalog.DEFAULT_CHARACTER))


def island_name_row(dialog):
    """建出输入框（挂在 ``dialog.island_name_edit``），返回设置行。"""
    from .settings_widgets import SettingRow

    character_id = _current_character(dialog.config)
    alias = dialog.config.character_alias(character_id)
    edit = _line_edit(alias, width=160)
    edit.setMaxLength(MAX_LENGTH)
    edit.setPlaceholderText(catalog.character_display_name(character_id))
    edit.setAccessibleName(t("settings.island_name.title"))
    dialog.island_name_edit = edit
    dialog._island_name_initial = alias
    return SettingRow(
        "dynamic_island_name_value",
        t("settings.island_name.title"),
        t("settings.island_name.hint"),
        edit,
    )


def save_island_name(dialog) -> None:
    """保存时写回当前角色的显示名（只在用户改过这一栏时写；不落盘，随对话框统一保存）。"""
    edit = getattr(dialog, "island_name_edit", None)
    if edit is None:
        return
    name = edit.text().strip()[:MAX_LENGTH]
    if name == getattr(dialog, "_island_name_initial", ""):
        return
    config = dialog.config
    aliases = config.get("character_aliases")
    aliases = dict(aliases) if isinstance(aliases, dict) else {}
    character_id = _current_character(config)
    if name:
        aliases[character_id] = name
    else:
        aliases.pop(character_id, None)
    config.set("character_aliases", aliases)
    dialog._island_name_initial = name
