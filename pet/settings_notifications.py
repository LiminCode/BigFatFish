# -*- coding: utf-8 -*-
"""设置页「通知中心」一节（自动化与联动）：开关、多久读一次、认哪些应用。

控件、提示、保存都在这里；读取与跳转见 ``notification_center.py``。非 Windows / 没装 WinRT 通知包
时开关置灰并说明原因，其余照旧。
"""

from __future__ import annotations

from PySide6.QtWidgets import QLineEdit

from . import notification_center as nc
from .settings_widgets import BrowserSpinBox, SettingRow, ToggleSwitch

_ENABLED_HINT = ("把 Windows 通知中心里的 Slack 通知铺在灵动岛的卡片里（胶囊上多一个铃铛），点一条就跳到 "
                 "Slack 里那条消息。Windows 要开着「让应用访问通知」。")
_UNAVAILABLE_HINT = "这台机器上用不了：需要 Windows，并装上 winrt-Windows.UI.Notifications(.Management)。"
_POLL_HINT = "隔几秒读一次通知中心（Windows 不给没有包身份的程序推送变更，只能自己看）。"
_APPS_HINT = "认哪些应用的通知：应用名片段，逗号分隔，不分大小写。默认只认 Slack。"


def notification_rows(dialog) -> list[SettingRow]:
    """建出控件并返回设置行。挂在 ``dialog`` 上：``notifications_enabled_check``、
    ``notifications_poll_spin``、``notifications_apps_edit``。"""
    settings = nc.normalize(dialog.config.get(nc.CONFIG_KEY))
    usable = nc.available()

    check = ToggleSwitch(dialog)
    check.setChecked(bool(settings["enabled"]))
    check.setEnabled(usable)
    dialog.notifications_enabled_check = check

    spin = BrowserSpinBox(dialog)
    spin.setRange(*nc.POLL_RANGE)
    spin.setSuffix(" 秒")
    spin.setValue(settings["poll_seconds"])
    dialog.notifications_poll_spin = spin

    edit = QLineEdit(dialog)
    edit.setText(", ".join(settings["apps"]))
    edit.setPlaceholderText(", ".join(nc.DEFAULT_APPS))
    dialog.notifications_apps_edit = edit

    return [
        SettingRow("notifications_enabled", "显示通知", _ENABLED_HINT if usable else _UNAVAILABLE_HINT, check),
        SettingRow("notifications_poll_seconds", "读取间隔", _POLL_HINT, spin),
        SettingRow("notifications_apps", "认哪些应用", _APPS_HINT, edit, stacked=True),
    ]


def save_notification_settings(dialog) -> None:
    check = getattr(dialog, "notifications_enabled_check", None)
    if check is None:
        return
    current = nc.normalize(dialog.config.get(nc.CONFIG_KEY))
    dialog.config.set(nc.CONFIG_KEY, nc.normalize({
        **current,
        "enabled": check.isChecked(),
        "poll_seconds": dialog.notifications_poll_spin.value(),
        "apps": dialog.notifications_apps_edit.text(),
    }))
