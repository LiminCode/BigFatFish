# -*- coding: utf-8 -*-
"""设置页「VS Code 工作区」一节（自动化与联动）：工作区文件目录 + 菜单条数。控件、提示、保存都在这里。"""

from __future__ import annotations

import os

from . import vscode_workspaces as vw
from .settings_widgets import BrowserSpinBox, ResourcePathPicker, SettingRow

# 提示里不放长的、断不开的路径示例：紧凑宽度下它会把整页撑宽（设置行就不再折叠）
_DIR_HINT = ("右键菜单「VS Code 工作区」除了列出开着的和最近用过的，还会列出这个目录里的 "
             "*.code-workspace 文件。可以是本机目录，也可以是 WSL 里的目录"
             "（以 \\\\wsl.localhost 开头的那种路径）。留空就不列。")
_MISSING_HINT = "这个目录现在打不开（不存在或没有权限）；菜单里会少掉这一部分，其余照常。"
_LIMIT_HINT = "菜单最多列几条（开着的优先，其余按最后用过的时间）。"


def workspace_rows(dialog) -> list[SettingRow]:
    """建出两个控件（挂在 ``dialog.vscode_workspace_dir_picker`` / ``dialog.vscode_menu_limit_spin``）并返回设置行。"""
    settings = vw.normalize(dialog.config.get(vw.CONFIG_KEY))
    picker = ResourcePathPicker(settings["workspace_dir"], directory=True,
                                dialog_title="选择工作区文件所在的目录", parent=dialog)
    dialog.vscode_workspace_dir_picker = picker
    dir_row = SettingRow("vscode_workspace_dir", "工作区文件目录", _DIR_HINT, picker, stacked=True)

    def sync_hint(*_args) -> None:
        text = picker.text().strip()
        usable = not text or os.path.isdir(text)
        dir_row.hint_label.setText(_DIR_HINT if usable else _MISSING_HINT)

    picker.edit.textChanged.connect(sync_hint)
    sync_hint()

    spin = BrowserSpinBox(dialog)
    spin.setRange(*vw.LIMIT_RANGE)
    spin.setValue(settings["menu_limit"])
    dialog.vscode_menu_limit_spin = spin
    limit_row = SettingRow("vscode_menu_limit", "菜单条数", _LIMIT_HINT, spin)
    return [dir_row, limit_row]


def save_workspace_settings(dialog) -> None:
    picker = getattr(dialog, "vscode_workspace_dir_picker", None)
    spin = getattr(dialog, "vscode_menu_limit_spin", None)
    if picker is None or spin is None:
        return
    dialog.config.set(vw.CONFIG_KEY, vw.normalize({"workspace_dir": picker.text(), "menu_limit": spin.value()}))
