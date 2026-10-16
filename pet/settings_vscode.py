# -*- coding: utf-8 -*-
"""设置页「VS Code 工作区」一节（自动化与联动）：本机目录、每个 WSL 发行版各一个目录、菜单条数。

发行版列表来自本机的 WSL 注册表（``vscode_workspaces.wsl_distros``），默认发行版排最前并标出；
没装 WSL 就只有本机一行。控件、提示、保存都在这里。
"""

from __future__ import annotations

from PySide6.QtWidgets import QLineEdit

from . import vscode_workspaces as vw
from .settings_widgets import BrowserSpinBox, ResourcePathPicker, SettingRow
from .i18n import t

#: 提示文案存文案键，用时 t()
_SECTION_HINT = "settings.vscode.section_hint"
_LOCAL_HINT = "settings.vscode.local_hint"   # 后面接 _SECTION_HINT
_WSL_HINT = "settings.vscode.wsl_hint"
_MISSING_HINT = "settings.vscode.missing_hint"
_LIMIT_HINT = "settings.vscode.limit_hint"


def workspace_rows(dialog) -> list[SettingRow]:
    """建出控件并返回设置行。挂在 ``dialog`` 上：``vscode_workspace_dir_picker``、
    ``vscode_wsl_dir_edits``（发行版名 → 输入框）、``vscode_menu_limit_spin``。"""
    settings = vw.normalize(dialog.config.get(vw.CONFIG_KEY))
    rows: list[SettingRow] = []

    picker = ResourcePathPicker(settings["workspace_dir"], directory=True,
                                dialog_title=t("settings.vscode.choose_folder_holds_workspace_files"), parent=dialog)
    dialog.vscode_workspace_dir_picker = picker
    rows.append(_row_with_check("vscode_workspace_dir", t("settings.vscode.local_folders"), t(_LOCAL_HINT) + t(_SECTION_HINT), picker, picker.edit,
                                lambda text: vw.directory_exists(text)))

    dialog.vscode_wsl_dir_edits = {}
    distros = vw.wsl_distros()
    default = distros[0] if distros else ""
    for index, distro in enumerate(distros):
        edit = QLineEdit(dialog)
        edit.setText(settings["wsl_dirs"].get(distro, ""))
        edit.setPlaceholderText("/home/…/workspace")
        edit.setAccessibleName(t("settings.vscode.workspace_folders_distro", distro=distro))
        dialog.vscode_wsl_dir_edits[distro] = edit
        title = t("settings.vscode.distro_default_distro", distro=distro) if distro == default else distro
        rows.append(_row_with_check(f"vscode_wsl_dir_{index}", title, t(_WSL_HINT), edit, edit,
                                    lambda text, distro=distro: vw.directory_exists(text, distro=distro)))

    spin = BrowserSpinBox(dialog)
    spin.setRange(*vw.LIMIT_RANGE)
    spin.setValue(settings["menu_limit"])
    dialog.vscode_menu_limit_spin = spin
    rows.append(SettingRow("vscode_menu_limit", t("settings.vscode.menu_items"), t(_LIMIT_HINT), spin))
    return rows


def _row_with_check(row_id, title, hint, control, edit, exists) -> SettingRow:
    row = SettingRow(row_id, title, hint, control, stacked=True)

    def sync_hint(*_args) -> None:
        text = edit.text().strip()
        row.hint_label.setText(hint if not text or exists(text) else t(_MISSING_HINT))

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
