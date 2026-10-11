# -*- coding: utf-8 -*-
"""设置页的「保存」：写入配置但不关窗口，运行中的桌宠随即应用。

原来只有「保存并退出」（关窗口也会保存），想让改动立刻生效只能关掉设置再重开。
独立设置进程下应用靠主进程盯配置文件；进程内对话框靠 ``saved`` 信号。
"""

from __future__ import annotations

import pytest
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QFrame

from pet import modern_settings_dialog as settings_mod
from pet.config import Config
from pet.modern_settings_dialog import ModernSettingsDialog

app = QApplication.instance() or QApplication([])


@pytest.fixture
def autostart(monkeypatch):
    """系统登录项的替身：记录每次写入，绝不碰真实注册表。"""
    state = {"enabled": False, "calls": []}
    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: state["enabled"])

    def set_enabled(on):
        state["calls"].append(bool(on))
        state["enabled"] = bool(on)
        return True

    monkeypatch.setattr(settings_mod.autostart_mod, "set_enabled", set_enabled)
    return state


@pytest.fixture
def dialog(tmp_path, autostart):
    dialog = ModernSettingsDialog(Config(tmp_path), include_ai=False)
    dialog.base = tmp_path
    dialog.finished_results = []
    dialog.saved_count = []
    dialog.finished.connect(dialog.finished_results.append)
    dialog.saved.connect(lambda: dialog.saved_count.append(1))
    yield dialog
    dialog._saved_via_button = True      # 收尾不再触发关窗保存
    dialog.deleteLater()
    app.processEvents()


def _on_disk(dialog, key):
    return Config(dialog.base).get(key)


def test_save_button_sits_with_save_and_exit_in_the_sidebar(dialog):
    sidebar = dialog.findChild(QFrame, "sidebarPane")
    assert dialog.save_button.text() == "保存"
    assert dialog.save_button.parent() is sidebar
    assert dialog.save_exit_button.parent() is sidebar
    assert not dialog.save_button.isDefault() and not dialog.save_button.autoDefault(), \
        "在输入框里按回车不该触发保存"


def test_save_writes_the_config_and_keeps_the_window_open(dialog):
    before = bool(_on_disk(dialog, "no_move"))
    dialog.no_move_check.setChecked(not before)

    dialog.save_button.click()

    assert _on_disk(dialog, "no_move") is (not before)
    assert dialog.finished_results == [], "没有关窗口"
    assert dialog.saved_count == [1], "进程内宿主靠这个信号立刻应用"


def test_later_edits_are_still_saved_on_exit(dialog):
    dialog.no_move_check.setChecked(True)
    dialog.save_button.click()
    dialog.lock_position_check.setChecked(True)

    dialog.save_exit_button.click()

    assert _on_disk(dialog, "no_move") is True
    assert _on_disk(dialog, "lock_position") is True
    assert dialog.finished_results != []


def test_ctrl_s_saves(dialog):
    shortcuts = [s for s in dialog.findChildren(QShortcut)
                 if s.key() == QKeySequence(QKeySequence.StandardKey.Save)]
    assert len(shortcuts) == 1

    dialog.no_move_check.setChecked(True)
    shortcuts[0].activated.emit()

    assert _on_disk(dialog, "no_move") is True and dialog.finished_results == []


def test_failed_save_reports_nothing_as_saved(dialog, monkeypatch):
    monkeypatch.setattr(dialog, "_write_config", lambda: False)
    dialog.save_button.click()
    assert dialog.saved_count == []
    assert dialog.save_button.text() == "保存", "没存上就不显示「已保存」"


def test_button_confirms_the_save_then_returns_to_normal(dialog):
    dialog.save_button.click()
    assert dialog.save_button.text() == "已保存"
    dialog._save_feedback_timer.timeout.emit()      # 不等真实的 1.5 秒
    assert dialog.save_button.text() == "保存"


def test_autostart_is_applied_on_save_and_can_be_reverted_before_closing(dialog, autostart):
    """保存后再改回去：关窗时要认「上次保存的值」而不是「打开窗口时的值」。"""
    dialog.autostart_check.setChecked(True)
    dialog.save_button.click()
    assert autostart["calls"] == [True]

    dialog.save_button.click()
    assert autostart["calls"] == [True], "没再改动就不重复写登录项"

    dialog.autostart_check.setChecked(False)
    dialog.save_exit_button.click()
    assert autostart["calls"] == [True, False]


def test_in_process_host_applies_settings_as_soon_as_they_are_saved():
    """进程内对话框（关掉进程隔离时）：保存即走与关窗相同的应用链，但不丢对话框引用。"""
    from types import SimpleNamespace

    from pet.app import PetInstance

    applied: list = []
    dialog = object()
    owner = SimpleNamespace(
        modern_settings_dialog=dialog,
        shell=SimpleNamespace(_instances=[1], _apply_external_config_change=lambda: applied.append("apply"),
                              precache_self_talk_voice=lambda _why: applied.append("precache")),
    )

    PetInstance._modern_settings_saved(owner)

    assert applied == ["apply", "precache"]
    assert owner.modern_settings_dialog is dialog, "窗口还开着"
