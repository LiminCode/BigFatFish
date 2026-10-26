# -*- coding: utf-8 -*-
"""设置页「通知中心」一节里的自家弹窗选项：开关、哪个角、哪块屏、停留几秒、最多几条。

从设置窗口这个公开入口建出来，改控件、保存，看配置。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from pet import notification_center as nc
from pet import settings_notifications
from pet.config import Config

app = QApplication.instance() or QApplication([])


@pytest.fixture
def make_dialog(tmp_path, monkeypatch):
    from pet import modern_settings_dialog as settings_mod

    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    monkeypatch.setattr(nc, "available", lambda: True)
    opened = []

    def make(notifications=None):
        config = Config(tmp_path)
        if notifications is not None:
            config.set(nc.CONFIG_KEY, notifications)
        dialog = settings_mod.ModernSettingsDialog(config, include_ai=True)
        opened.append(dialog)
        return dialog

    yield make
    for dialog in opened:
        dialog.close()
        dialog.deleteLater()
    app.processEvents()


def _datas(select):
    return [select.itemData(i) for i in range(select.count())]


def test_toast_rows_show_the_defaults(make_dialog):
    dialog = make_dialog()
    assert dialog.notifications_toast_check.isChecked() is False
    assert _datas(dialog.notifications_corner_select) == list(nc.TOAST_CORNERS)
    screens = _datas(dialog.notifications_screen_select)
    assert screens[:2] == [nc.TOAST_SCREEN_PRIMARY, nc.TOAST_SCREEN_CURSOR]
    assert screens[2:] == [s.name() for s in QGuiApplication.screens()], "每块屏一项，存屏幕名"
    assert dialog.notifications_corner_select.currentData() == "top_right"
    assert dialog.notifications_screen_select.currentData() == nc.TOAST_SCREEN_PRIMARY
    assert dialog.notifications_toast_seconds_spin.value() == nc.TOAST_DEFAULTS["seconds"]
    assert dialog.notifications_toast_max_spin.value() == nc.TOAST_DEFAULTS["max_visible"]


def test_toast_settings_round_trip_through_save(make_dialog):
    dialog = make_dialog()
    dialog.notifications_toast_check.setChecked(True)
    dialog.notifications_corner_select.setCurrentData("bottom_left")
    screen = QGuiApplication.screens()[-1].name()
    dialog.notifications_screen_select.setCurrentData(screen)
    dialog.notifications_toast_seconds_spin.setValue(9)
    dialog.notifications_toast_max_spin.setValue(3)
    settings_notifications.save_notification_settings(dialog)
    saved = nc.normalize(dialog.config.get(nc.CONFIG_KEY))
    screen = screen or nc.TOAST_SCREEN_PRIMARY          # offscreen 平台的屏没有名字
    assert saved["toast"] == {"enabled": True, "corner": "bottom_left", "screen": screen, "seconds": 9,
                              "max_visible": 3}
    assert saved["apps"] == ["slack"], "别的键原样留着"


def test_an_unplugged_screen_stays_selected_until_the_user_changes_it(make_dialog):
    toast = {**nc.TOAST_DEFAULTS, "screen": "Gone Monitor 27"}
    dialog = make_dialog({**nc.normalize(None), "toast": toast})
    select = dialog.notifications_screen_select
    assert select.currentData() == "Gone Monitor 27", "拔掉的屏不偷偷改成主屏"
    assert "Gone Monitor 27" in select.text()
    settings_notifications.save_notification_settings(dialog)
    assert nc.normalize(dialog.config.get(nc.CONFIG_KEY))["toast"]["screen"] == "Gone Monitor 27"


def test_toast_controls_follow_the_toggle(make_dialog):
    dialog = make_dialog()
    controls = (dialog.notifications_corner_select, dialog.notifications_screen_select,
                dialog.notifications_toast_seconds_spin, dialog.notifications_toast_max_spin)
    assert not any(c.isEnabled() for c in controls), "弹窗关着时这几项置灰"
    dialog.notifications_toast_check.setChecked(True)
    assert all(c.isEnabled() for c in controls)


def test_seconds_can_be_zero_meaning_stay(make_dialog):
    spin = make_dialog().notifications_toast_seconds_spin
    assert spin.minimum() == 0 and spin.maximum() == nc.TOAST_SECONDS_RANGE[1]
    assert spin.specialValueText(), "0 显示成「一直留着」"
