# -*- coding: utf-8 -*-
"""设置页「托盘图标」一行（常规 · 窗口与系统）。控件、提示文字、保存都在这里。"""

from __future__ import annotations

from . import tray_icon
from .settings_widgets import ResourcePathPicker, SettingRow

_HINT = ("通知栏（系统托盘）里显示的图标。留空用角色头像；选一张图片就用它——"
         "方形、主体占满画面的图在托盘里最清楚。")
_UNUSABLE_HINT = "这个文件用不了（不存在或不是图片），会继续使用默认的角色头像。"


def tray_icon_rows(dialog) -> list[SettingRow]:
    """建出选择器（挂在 ``dialog.tray_icon_picker``）并返回设置行。"""
    picker = ResourcePathPicker(
        str(dialog.config.get(tray_icon.CONFIG_KEY, "") or ""),
        dialog_title="选择托盘图标", parent=dialog,
    )
    dialog.tray_icon_picker = picker
    row = SettingRow("tray_icon", "托盘图标", _HINT, picker, stacked=True)

    def sync_hint(*_args) -> None:
        text = picker.text()
        usable = not text or tray_icon.load_custom_pixmap(text) is not None
        row.hint_label.setText(_HINT if usable else _UNUSABLE_HINT)

    picker.edit.textChanged.connect(sync_hint)
    sync_hint()
    return [row]


def save_tray_icon_setting(dialog) -> None:
    picker = getattr(dialog, "tray_icon_picker", None)
    if picker is not None:
        dialog.config.set(tray_icon.CONFIG_KEY, picker.text())
