# -*- coding: utf-8 -*-
"""设置页「通知中心」一节（自动化与联动）：开关、多久读一次、认哪些应用。

控件、提示、保存都在这里；读取与跳转见 ``notification_center.py``。非 Windows / 没装 WinRT 通知包
时开关置灰并说明原因，其余照旧。
"""

from __future__ import annotations

from PySide6.QtWidgets import QLineEdit

from . import notification_center as nc
from .settings_widgets import BrowserSpinBox, SettingRow, ToggleSwitch
from .i18n import t

#: 提示文案存文案键，用时 t()
_ENABLED_HINT = "settings.notifications.enabled_hint"
_UNAVAILABLE_HINT = "settings.notifications.unavailable_hint"
_POLL_HINT = "settings.notifications.poll_hint"
_APPS_HINT = "settings.notifications.apps_hint"


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
    spin.setSuffix(t("settings.notifications.s"))
    spin.setValue(settings["poll_seconds"])
    dialog.notifications_poll_spin = spin

    edit = QLineEdit(dialog)
    edit.setText(", ".join(settings["apps"]))
    edit.setPlaceholderText(", ".join(nc.DEFAULT_APPS))
    dialog.notifications_apps_edit = edit

    return [
        SettingRow("notifications_enabled", t("settings.notifications.show_notifications"), t(_ENABLED_HINT if usable else _UNAVAILABLE_HINT), check),
        SettingRow("notifications_poll_seconds", t("settings.notifications.read_interval"), t(_POLL_HINT), spin),
        SettingRow("notifications_apps", t("settings.notifications.which_apps"), t(_APPS_HINT), edit, stacked=True),
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
