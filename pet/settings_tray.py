# -*- coding: utf-8 -*-
"""设置页「托盘图标」一行（常规 · 窗口与系统）。控件、提示文字、保存都在这里。"""

from __future__ import annotations

from . import tray_icon
from .settings_widgets import ResourcePathPicker, SettingRow
from .i18n import t

#: 提示文案存文案键，用时 t()
_HINT = "settings.tray.hint"
_UNUSABLE_HINT = "settings.tray.unusable_hint"


def tray_icon_rows(dialog) -> list[SettingRow]:
    """建出选择器（挂在 ``dialog.tray_icon_picker``）并返回设置行。"""
    picker = ResourcePathPicker(
        str(dialog.config.get(tray_icon.CONFIG_KEY, "") or ""),
        dialog_title=t("settings.tray.choose_tray_icon"), parent=dialog,
    )
    dialog.tray_icon_picker = picker
    row = SettingRow("tray_icon", t("settings.tray.tray_icon"), t(_HINT), picker, stacked=True)

    def sync_hint(*_args) -> None:
        text = picker.text()
        usable = not text or tray_icon.load_custom_pixmap(text) is not None
        row.hint_label.setText(t(_HINT if usable else _UNUSABLE_HINT))

    picker.edit.textChanged.connect(sync_hint)
    sync_hint()
    return [row]


def save_tray_icon_setting(dialog) -> None:
    picker = getattr(dialog, "tray_icon_picker", None)
    if picker is not None:
        dialog.config.set(tray_icon.CONFIG_KEY, picker.text())
