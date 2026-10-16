# -*- coding: utf-8 -*-
"""设置页「Slack 关注」一节（自动化与联动）：开关、检查间隔、多久没动算离开、用哪个模型。

控件、提示、保存都在这里；判断与检查见 ``slack_watch.py``。右键菜单里的开关和间隔改的是同一份配置，
后台服务每分钟重读，最迟一分钟生效。没装 WSL 时开关置灰并说明原因。
"""

from __future__ import annotations

from PySide6.QtWidgets import QLineEdit

from . import claude_hooks
from . import slack_watch as sw
from .settings_widgets import BrowserSpinBox, ModernSelect, SettingRow, ToggleSwitch
from .i18n import t

#: 模型下拉里的几个常用名；配置里写了别的也认（当作自定义）
#: （值, 显示名的文案键）——显示名用时 t()
MODEL_CHOICES = (("sonnet", "settings.slack.model_sonnet"), ("haiku", "settings.slack.model_haiku"),
                 ("opus", "settings.slack.model_opus"))
CUSTOM = "__custom__"

#: 提示文案存文案键，用时 t()
_ENABLED_HINT = "settings.slack.enabled_hint"
_NO_WSL_HINT = "settings.slack.no_wsl_hint"
_INTERVAL_HINT = "settings.slack.interval_hint"
_IDLE_HINT = "settings.slack.idle_hint"
_MODEL_HINT = "settings.slack.model_hint"


def slack_watch_rows(dialog) -> list[SettingRow]:
    """建出控件并返回设置行。挂在 ``dialog`` 上：``slack_watch_enabled_check``、``slack_watch_interval_spin``、
    ``slack_watch_idle_spin``、``slack_watch_model_select``、``slack_watch_model_edit``。"""
    settings = sw.normalize(dialog.config.get(sw.CONFIG_KEY))
    usable = bool(claude_hooks.wsl_exe())

    check = ToggleSwitch(dialog)
    check.setChecked(bool(settings["enabled"]) and usable)
    check.setEnabled(usable)
    dialog.slack_watch_enabled_check = check

    interval = BrowserSpinBox(dialog)
    interval.setRange(*sw.INTERVAL_RANGE)
    interval.setSuffix(t("settings.slack.min"))
    interval.setValue(settings["interval_minutes"])
    dialog.slack_watch_interval_spin = interval

    idle = BrowserSpinBox(dialog)
    idle.setRange(*sw.IDLE_RANGE)
    idle.setSuffix(t("settings.slack.min"))
    idle.setValue(settings["idle_minutes"])
    dialog.slack_watch_idle_spin = idle

    select = ModernSelect(dialog, width=200)
    for value, label in MODEL_CHOICES:
        select.addItem(t(label), value)
    select.addItem(t("settings.slack.custom"), CUSTOM)
    edit = QLineEdit(dialog)
    edit.setPlaceholderText(t("settings.slack.e_g_claude_sonnet_5"))
    edit.setAccessibleName(t("settings.slack.custom_model_name"))
    known = {value for value, _label in MODEL_CHOICES}
    if settings["model"] in known:
        select.setCurrentIndex(max(0, select.findData(settings["model"])))
    else:
        select.setCurrentIndex(max(0, select.findData(CUSTOM)))
        edit.setText(settings["model"])
    edit.setVisible(select.currentData() == CUSTOM)
    select.currentIndexChanged.connect(lambda _index: edit.setVisible(select.currentData() == CUSTOM))
    dialog.slack_watch_model_select = select
    dialog.slack_watch_model_edit = edit

    return [
        SettingRow("slack_watch_enabled", t("settings.slack.check_automatically_while_i_m"), t(_ENABLED_HINT if usable else _NO_WSL_HINT), check),
        SettingRow("slack_watch_interval", t("settings.slack.check_interval"), t(_INTERVAL_HINT), interval),
        SettingRow("slack_watch_idle", t("settings.slack.away_after"), t(_IDLE_HINT), idle),
        SettingRow("slack_watch_model", t("settings.slack.model"), t(_MODEL_HINT), select),
        SettingRow("slack_watch_model_custom", t("settings.slack.custom_model_name"), "", edit, stacked=True),
    ]


def chosen_model(dialog) -> str:
    select = dialog.slack_watch_model_select
    value = select.currentData()
    if value == CUSTOM:
        value = dialog.slack_watch_model_edit.text()
    return sw.wb.normalize_model(value)


def save_slack_watch_settings(dialog) -> None:
    check = getattr(dialog, "slack_watch_enabled_check", None)
    if check is None:
        return
    current = sw.normalize(dialog.config.get(sw.CONFIG_KEY))
    dialog.config.set(sw.CONFIG_KEY, sw.normalize({
        **current,
        "enabled": check.isChecked(),
        "interval_minutes": dialog.slack_watch_interval_spin.value(),
        "idle_minutes": dialog.slack_watch_idle_spin.value(),
        "model": chosen_model(dialog),
    }))
