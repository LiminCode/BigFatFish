# -*- coding: utf-8 -*-
"""设置页已经开着时把那扇窗调到前台，而不是只弹「请先关闭」（用户 2026-10-21）。

纪律：不枚举真实窗口、不动真实前台；窗口表和 focus 都是假的，锁用临时目录。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QLockFile

from pet import settings_focus as sf
from pet.claude_session_jump import Window


def _w(hwnd, pid, title):
    return Window(hwnd, pid, title, "python.exe")


def test_the_lock_tells_which_process_holds_the_settings_window(tmp_path):
    lock_path = tmp_path / "settings.lock"
    assert sf.settings_process_pid(lock_path) == 0, "没人持锁 = 0"
    holder = QLockFile(str(lock_path))
    assert holder.tryLock(0)
    try:
        assert sf.settings_process_pid(lock_path) == os.getpid()
    finally:
        holder.unlock()
    assert sf.settings_process_pid(lock_path) == 0


def test_the_settings_window_is_picked_by_pid_and_title():
    windows = [_w(1, 7, "Notepad"), _w(2, 9, "Something"), _w(3, 9, "肥鱼设置"), _w(4, 9, "Fish Settings")]
    assert sf.pick_settings_window(windows, 9).hwnd == 3
    assert sf.pick_settings_window([_w(2, 9, "Something"), _w(4, 9, "Fish Settings")], 9).hwnd == 4
    assert sf.pick_settings_window([_w(2, 9, "Something"), _w(5, 9, "Other")], 9).hwnd == 2, "没有像设置的标题就取最前面那扇"
    assert sf.pick_settings_window(windows, 8) is None
    assert sf.pick_settings_window([_w(6, 9, "")], 9) is None, "没标题的（隐藏的 Qt 辅助窗）不算"


def test_focus_goes_through_the_lock_holder_window_or_reports_false(tmp_path):
    lock_path = tmp_path / "settings.lock"
    focused: list[int] = []
    me = os.getpid()
    windows = [_w(11, me + 1, "肥鱼设置"), _w(12, me, "肥鱼设置"), _w(13, me, "Other")]
    assert sf.focus_settings_process(lock_path, windows=lambda: windows, focus=lambda h: focused.append(h) or True) is False
    assert focused == [], "没人持锁：不碰任何窗口"
    holder = QLockFile(str(lock_path))
    assert holder.tryLock(0)
    try:
        assert sf.focus_settings_process(lock_path, windows=lambda: windows, focus=lambda h: focused.append(h) or True)
        assert focused == [12], "只调持锁进程自己的设置窗"
        assert sf.focus_settings_process(lock_path, windows=lambda: [], focus=lambda h: True) is False
        assert sf.focus_settings_process(lock_path, windows=lambda: windows, focus=lambda h: False) is False
    finally:
        holder.unlock()
