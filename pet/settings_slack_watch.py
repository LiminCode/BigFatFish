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

#: 模型下拉里的几个常用名；配置里写了别的也认（当作自定义）
MODEL_CHOICES = (("sonnet", "Sonnet（默认，便宜够用）"), ("haiku", "Haiku（最便宜）"), ("opus", "Opus（最贵）"))
CUSTOM = "__custom__"

_ENABLED_HINT = ("电脑在用时（没锁屏、最近动过键鼠）每隔一阵让 WSL 里的 Claude Code 经 Slack 连接器只读地看一眼，"
                 "有需要你回复 / 处理的消息就冒气泡。每次检查都是一次真实的模型调用，走那个账号的额度。")
_NO_WSL_HINT = "这台机器没有 WSL：Slack 关注要靠 WSL 里登录着工作账号的 Claude Code。"
_INTERVAL_HINT = "隔几分钟检查一次（人在电脑前时才计）。按一天在用 8 小时算：15 分钟 = 最多 32 次。"
_IDLE_HINT = "多久没动键鼠就算离开，离开后不检查；回来后下一分钟接着算。"
_MODEL_HINT = "交给 Claude Code 的模型别名（claude -p --model）。选「自定义」可以填完整模型名；只认字母数字和 . _ -。"


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
    interval.setSuffix(" 分钟")
    interval.setValue(settings["interval_minutes"])
    dialog.slack_watch_interval_spin = interval

    idle = BrowserSpinBox(dialog)
    idle.setRange(*sw.IDLE_RANGE)
    idle.setSuffix(" 分钟")
    idle.setValue(settings["idle_minutes"])
    dialog.slack_watch_idle_spin = idle

    select = ModernSelect(dialog, width=200)
    for value, label in MODEL_CHOICES:
        select.addItem(label, value)
    select.addItem("自定义…", CUSTOM)
    edit = QLineEdit(dialog)
    edit.setPlaceholderText("例如 claude-sonnet-5-5")
    edit.setAccessibleName("自定义模型名")
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
        SettingRow("slack_watch_enabled", "电脑在用时自动检查", _ENABLED_HINT if usable else _NO_WSL_HINT, check),
        SettingRow("slack_watch_interval", "检查间隔", _INTERVAL_HINT, interval),
        SettingRow("slack_watch_idle", "多久没动算离开", _IDLE_HINT, idle),
        SettingRow("slack_watch_model", "用哪个模型", _MODEL_HINT, select),
        SettingRow("slack_watch_model_custom", "自定义模型名", "", edit, stacked=True),
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
