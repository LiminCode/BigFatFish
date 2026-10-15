# -*- coding: utf-8 -*-
"""设置页「VS Code 工作区」一节（自动化与联动）：本机目录、每个 WSL 发行版各一个目录、菜单条数。

发行版列表来自本机的 WSL 注册表（``vscode_workspaces.wsl_distros``），默认发行版排最前并标出；
没装 WSL 就只有本机一行。控件、提示、保存都在这里。
"""

from __future__ import annotations

from PySide6.QtWidgets import QLineEdit

from . import vscode_workspaces as vw
from .settings_widgets import BrowserSpinBox, ResourcePathPicker, SettingRow

_SECTION_HINT = ("右键菜单「VS Code 工作区」除了列出开着的和最近用过的，还会列出下面这些目录里的 "
                 "*.code-workspace 文件。留空就不列。")
_LOCAL_HINT = "本机上的目录。" + _SECTION_HINT
_WSL_HINT = "这个发行版里的目录，按它里面的写法填（如 /home/me/workspace）。"
_MISSING_HINT = "这个目录现在打不开（不存在、没有权限，或发行版没在运行）；菜单里会少掉这一部分，其余照常。"
_LIMIT_HINT = "菜单最多列几条。顺序：开着的 → 上面这些目录里的 → 其余最近用过的（按时间）。"


def workspace_rows(dialog) -> list[SettingRow]:
    """建出控件并返回设置行。挂在 ``dialog`` 上：``vscode_workspace_dir_picker``、
    ``vscode_wsl_dir_edits``（发行版名 → 输入框）、``vscode_menu_limit_spin``。"""
    settings = vw.normalize(dialog.config.get(vw.CONFIG_KEY))
    rows: list[SettingRow] = []

    picker = ResourcePathPicker(settings["workspace_dir"], directory=True,
                                dialog_title="选择工作区文件所在的目录", parent=dialog)
    dialog.vscode_workspace_dir_picker = picker
    rows.append(_row_with_check("vscode_workspace_dir", "本机目录", _LOCAL_HINT, picker, picker.edit,
                                lambda text: vw.directory_exists(text)))

    dialog.vscode_wsl_dir_edits = {}
    distros = vw.wsl_distros()
    default = distros[0] if distros else ""
    for index, distro in enumerate(distros):
        edit = QLineEdit(dialog)
        edit.setText(settings["wsl_dirs"].get(distro, ""))
        edit.setPlaceholderText("/home/…/workspace")
        edit.setAccessibleName(f"{distro} 里的工作区目录")
        dialog.vscode_wsl_dir_edits[distro] = edit
        title = f"{distro}（默认发行版）" if distro == default else distro
        rows.append(_row_with_check(f"vscode_wsl_dir_{index}", title, _WSL_HINT, edit, edit,
                                    lambda text, distro=distro: vw.directory_exists(text, distro=distro)))

    spin = BrowserSpinBox(dialog)
    spin.setRange(*vw.LIMIT_RANGE)
    spin.setValue(settings["menu_limit"])
    dialog.vscode_menu_limit_spin = spin
    rows.append(SettingRow("vscode_menu_limit", "菜单条数", _LIMIT_HINT, spin))
    return rows


def _row_with_check(row_id, title, hint, control, edit, exists) -> SettingRow:
    row = SettingRow(row_id, title, hint, control, stacked=True)

    def sync_hint(*_args) -> None:
        text = edit.text().strip()
        row.hint_label.setText(hint if not text or exists(text) else _MISSING_HINT)

    edit.textChanged.connect(sync_hint)
    sync_hint()
    return row


def save_workspace_settings(dialog) -> None:
    picker = getattr(dialog, "vscode_workspace_dir_picker", None)
    spin = getattr(dialog, "vscode_menu_limit_spin", None)
    if picker is None or spin is None:
        return
    previous = vw.normalize(dialog.config.get(vw.CONFIG_KEY))
    wsl_dirs = dict(previous["wsl_dirs"])      # 本机没列出来的发行版（比如暂时卸了）：原样保留
    for distro, edit in (getattr(dialog, "vscode_wsl_dir_edits", None) or {}).items():
        wsl_dirs[distro] = edit.text()
    dialog.config.set(vw.CONFIG_KEY, vw.normalize({
        "workspace_dir": picker.text(), "wsl_dirs": wsl_dirs, "menu_limit": spin.value()}))
