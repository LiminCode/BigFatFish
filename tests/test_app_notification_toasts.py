# -*- coding: utf-8 -*-
"""壳层把「刚到的通知」接到自家弹窗：设置开着才弹、太旧的不弹、全屏时不弹、点了走同一条跳转路。

``AppShell`` 太重，不整个建：用一个只有这几样属性的替身调用它的方法（方法本身是公开 seam 上的胶水）。
"""
from __future__ import annotations

import os
import time
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import notification_center as nc
from pet import platform_win
from pet.app import AppShell
from pet.config import Config

app = QApplication.instance() or QApplication([])


class FakeService:
    def __init__(self):
        self.enabled = True
        self.logos = {"Slack!App": b"PNG"}
        self.activated = []

    def activate(self, uid):
        self.activated.append(uid)
        return True


def _shell(tmp_path, toast_enabled: bool):
    config = Config(tmp_path)
    config.set(nc.CONFIG_KEY, {**nc.normalize(None), "toast": {**nc.TOAST_DEFAULTS, "enabled": toast_enabled}})
    shell = types.SimpleNamespace(config=config, app=app, _notifications=FakeService(), _notification_toasts=None,
                                  NOTIFICATION_TOAST_FRESH_S=AppShell.NOTIFICATION_TOAST_FRESH_S)
    for name in ("_sync_notification_toasts", "_on_notifications_arrived", "_on_notification_toast_activated"):
        setattr(shell, name, types.MethodType(getattr(AppShell, name), shell))
    return shell


def _notice(uid, age_s=1.0):
    return nc.Notice(uid=uid, app="Slack", app_id="Slack!App", title="#t", body="b", created=time.time() - age_s)


@pytest.fixture(autouse=True)
def _not_fullscreen(monkeypatch):
    monkeypatch.setattr(platform_win, "_fs_user_busy_state", lambda: (False, 5))
    monkeypatch.setattr(platform_win, "quiet_hours_profile", lambda: 0)


def test_no_stack_while_the_setting_is_off(tmp_path):
    shell = _shell(tmp_path, toast_enabled=False)
    shell._sync_notification_toasts()
    assert shell._notification_toasts is None
    shell._on_notifications_arrived([_notice(1)])          # 不炸、不弹


def test_fresh_arrivals_pop_up_with_their_logo_and_old_ones_do_not(tmp_path):
    shell = _shell(tmp_path, toast_enabled=True)
    shell._sync_notification_toasts()
    stack = shell._notification_toasts
    stack._animate = False
    shell._on_notifications_arrived([_notice(1, age_s=AppShell.NOTIFICATION_TOAST_FRESH_S + 60), _notice(2)])
    assert [c.notice.uid for c in stack.visible_cards()] == [2]
    assert [e.logo for e in stack._entries] == [b"PNG"], "应用图标跟着进卡片"
    stack.clear()


def test_fullscreen_suppresses_popups(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_win, "_fs_user_busy_state", lambda: (True, 3))
    shell = _shell(tmp_path, toast_enabled=True)
    shell._sync_notification_toasts()
    shell._on_notifications_arrived([_notice(1)])
    assert shell._notification_toasts.visible_cards() == []


@pytest.mark.parametrize("profile", [1, 2])
def test_do_not_disturb_suppresses_popups(tmp_path, monkeypatch, profile):
    """勿扰（Windows 11 开勿扰实测 = 1 仅优先；2 = 仅闹钟）：不弹，跟 Windows 自己的横幅一样安静。"""
    monkeypatch.setattr(platform_win, "quiet_hours_profile", lambda: profile)
    shell = _shell(tmp_path, toast_enabled=True)
    shell._sync_notification_toasts()
    shell._on_notifications_arrived([_notice(1)])
    assert shell._notification_toasts.visible_cards() == []


def test_click_goes_through_the_service_and_turning_off_clears(tmp_path):
    shell = _shell(tmp_path, toast_enabled=True)
    shell._sync_notification_toasts()
    stack = shell._notification_toasts
    stack._animate = False
    shell._on_notifications_arrived([_notice(7)])
    card = stack.visible_cards()[0]
    card.clicked.emit(card.notice)
    assert shell._notifications.activated == [7]
    shell._on_notifications_arrived([_notice(8)])
    shell.config.set(nc.CONFIG_KEY, nc.normalize(None))     # 弹窗关掉
    shell._sync_notification_toasts()
    app.processEvents()
    assert stack.visible_cards() == []


def test_stacking_choice_from_config_reaches_the_popups(tmp_path):
    shell = _shell(tmp_path, toast_enabled=True)
    config = nc.normalize(shell.config.get(nc.CONFIG_KEY))
    shell.config.set(nc.CONFIG_KEY, {**config, "stack": {"slack": "off", "chrome": "app"}})
    shell._sync_notification_toasts()
    assert shell._notification_toasts.settings["stack"] == {"slack": "off", "chrome": "app"}
