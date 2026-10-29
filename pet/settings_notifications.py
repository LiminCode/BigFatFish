# -*- coding: utf-8 -*-
"""设置页「通知」一级域（2026-10-26 从「自动化与联动」里搬出来）的三节：

- 读取：开关、多久读一次、认哪些应用；
- 叠放：同一来源的通知怎么叠，每个应用一个选择（Slack 按频道、Chrome 按网站、整个应用一摞、不叠）；
- 弹窗：我们自己弹的通知（``notification_toast``）：开关、哪个角、哪块屏、停留几秒、最多同时几条。

控件、提示、保存都在这里；读取与跳转见 ``notification_center.py``。非 Windows / 没装 WinRT 通知包
时开关置灰并说明原因，其余照旧。
"""

from __future__ import annotations

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLineEdit

from . import notification_center as nc
from .settings_widgets import BrowserSpinBox, ModernSelect, SettingRow, SettingsSection, ToggleSwitch
from .i18n import t

#: 提示文案存文案键，用时 t()
_ENABLED_HINT = "settings.notifications.enabled_hint"
_UNAVAILABLE_HINT = "settings.notifications.unavailable_hint"
_POLL_HINT = "settings.notifications.poll_hint"
_APPS_HINT = "settings.notifications.apps_hint"
_CORNER_KEYS = {
    "top_right": "settings.notifications.corner_top_right",
    "top_left": "settings.notifications.corner_top_left",
    "bottom_right": "settings.notifications.corner_bottom_right",
    "bottom_left": "settings.notifications.corner_bottom_left",
}


#: 叠放选项的文案键：(应用, 选项) → 键
_STACK_KEYS = {
    ("slack", "off"): "settings.notifications.stack_off",
    ("slack", "channel"): "settings.notifications.stack_channel",
    ("slack", "app"): "settings.notifications.stack_app_slack",
    ("chrome", "off"): "settings.notifications.stack_off",
    ("chrome", "site"): "settings.notifications.stack_site",
    ("chrome", "app"): "settings.notifications.stack_app_chrome",
}


def _stack_select(dialog, app: str, current: str) -> ModernSelect:
    select = ModernSelect(dialog, width=200)
    for choice in nc.STACK_CHOICES[app]:
        select.addItem(t(_STACK_KEYS[(app, choice)]), choice)
    select.setCurrentData(current)
    return select


def notification_sections(dialog, parent) -> list[SettingsSection]:
    """「通知」页的三节：读取 / 叠放 / 弹窗。"""
    rows = notification_rows(dialog)
    by_key = {row.objectName().removeprefix("settingRow_"): row for row in rows}

    def pick(*keys):
        return [by_key[key] for key in keys]

    return [
        SettingsSection(t("settings.dlg.notifications_read"),
                        pick("notifications_enabled", "notifications_poll_seconds", "notifications_apps"), parent),
        SettingsSection(t("settings.dlg.notifications_stack"),
                        pick("notifications_stack_slack", "notifications_stack_chrome"), parent),
        SettingsSection(t("settings.dlg.notifications_toast"),
                        pick("notifications_toast", "notifications_toast_corner", "notifications_toast_screen",
                             "notifications_toast_seconds", "notifications_toast_max"), parent),
    ]


def _screen_select(dialog, current: str) -> ModernSelect:
    """主屏 / 光标所在的屏 / 每块屏一项（存屏幕名）。设置里记着的屏现在没接上：单列一项留着它。"""
    select = ModernSelect(dialog, width=260)
    select.addItem(t("settings.notifications.screen_primary"), nc.TOAST_SCREEN_PRIMARY)
    select.addItem(t("settings.notifications.screen_cursor"), nc.TOAST_SCREEN_CURSOR)
    primary = QGuiApplication.primaryScreen()
    for index, screen in enumerate(QGuiApplication.screens()):
        size = screen.size()
        label = f"{index + 1} · {screen.name()} · {size.width()}×{size.height()}"
        if screen is primary:
            label += t("settings.notifications.screen_primary_mark")
        select.addItem(label, screen.name())
    if select.findData(current) < 0:
        select.addItem(t("settings.notifications.screen_missing", name=current), current)
    select.setCurrentData(current)
    return select


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

    stack_slack = _stack_select(dialog, "slack", settings["stack"]["slack"])
    dialog.notifications_stack_slack_select = stack_slack
    stack_chrome = _stack_select(dialog, "chrome", settings["stack"]["chrome"])
    dialog.notifications_stack_chrome_select = stack_chrome

    toast = settings["toast"]
    toast_check = ToggleSwitch(dialog)
    toast_check.setChecked(bool(toast["enabled"]))
    toast_check.setEnabled(usable)
    dialog.notifications_toast_check = toast_check

    corner = ModernSelect(dialog, width=160)
    for key in nc.TOAST_CORNERS:
        corner.addItem(t(_CORNER_KEYS[key]), key)
    corner.setCurrentData(toast["corner"])
    dialog.notifications_corner_select = corner

    screen = _screen_select(dialog, toast["screen"])
    dialog.notifications_screen_select = screen

    seconds = BrowserSpinBox(dialog)
    seconds.setRange(*nc.TOAST_SECONDS_RANGE)
    seconds.setSuffix(t("settings.notifications.s"))
    seconds.setSpecialValueText(t("settings.notifications.toast_stay"))     # 0 = 一直留着
    seconds.setValue(toast["seconds"])
    dialog.notifications_toast_seconds_spin = seconds

    most = BrowserSpinBox(dialog)
    most.setRange(*nc.TOAST_MAX_RANGE)
    most.setValue(toast["max_visible"])
    dialog.notifications_toast_max_spin = most

    def follow_toggle(on: bool) -> None:
        for control in (corner, screen, seconds, most):
            control.setEnabled(bool(on) and usable)

    toast_check.toggled.connect(follow_toggle)
    follow_toggle(toast_check.isChecked())

    return [
        SettingRow("notifications_enabled", t("settings.notifications.show_notifications"), t(_ENABLED_HINT if usable else _UNAVAILABLE_HINT), check),
        SettingRow("notifications_poll_seconds", t("settings.notifications.read_interval"), t(_POLL_HINT), spin),
        SettingRow("notifications_apps", t("settings.notifications.which_apps"), t(_APPS_HINT), edit, stacked=True),
        SettingRow("notifications_stack_slack", t("settings.notifications.stack_slack"), t("settings.notifications.stack_slack_hint"), stack_slack),
        SettingRow("notifications_stack_chrome", t("settings.notifications.stack_chrome"), t("settings.notifications.stack_chrome_hint"), stack_chrome),
        SettingRow("notifications_toast", t("settings.notifications.toast"), t("settings.notifications.toast_hint"), toast_check),
        SettingRow("notifications_toast_corner", t("settings.notifications.toast_corner"), t("settings.notifications.toast_corner_hint"), corner),
        SettingRow("notifications_toast_screen", t("settings.notifications.toast_screen"), t("settings.notifications.toast_screen_hint"), screen),
        SettingRow("notifications_toast_seconds", t("settings.notifications.toast_seconds"), t("settings.notifications.toast_seconds_hint"), seconds),
        SettingRow("notifications_toast_max", t("settings.notifications.toast_max"), t("settings.notifications.toast_max_hint"), most),
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
        "stack": {
            "slack": dialog.notifications_stack_slack_select.currentData(),
            "chrome": dialog.notifications_stack_chrome_select.currentData(),
        },
        "toast": {
            "enabled": dialog.notifications_toast_check.isChecked(),
            "corner": dialog.notifications_corner_select.currentData(),
            "screen": dialog.notifications_screen_select.currentData(),
            "seconds": dialog.notifications_toast_seconds_spin.value(),
            "max_visible": dialog.notifications_toast_max_spin.value(),
        },
    }))
