# -*- coding: utf-8 -*-
"""设置页已经开着时，把那扇窗调到前台（用户 2026-10-21：以前只弹一条「请先关闭」的通知，窗口不动）。

独立设置进程是单实例，锁文件 ``settings.lock`` 由它持有；``QLockFile.getLockInfo`` 能读出持锁进程的
pid，再在顶层窗口里找这个 pid 的窗（优先标题像「设置 / Settings」的那扇），用会话跳转那套
``focus_window``（逐级绕过 Windows 的前台限制）调到前面。找不到窗或调不上来返回 False，调用方退回原来的通知。

非 Windows 上一律 False（没有 Win32 的窗口枚举）。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from .claude_session_jump import Window, focus_window, list_windows

log = logging.getLogger(__name__)

#: 设置窗标题里会出现的词（中 / 英界面各一）；都没有就取这个进程最前面那扇有标题的窗
_TITLE_HINTS = ("设置", "settings")


def settings_process_pid(lock_path: str | Path) -> int:
    """持有 ``settings.lock`` 的进程 pid；锁没人持有或读不出来返回 0。"""
    from PySide6.QtCore import QLockFile

    lock = QLockFile(str(lock_path))
    try:
        if lock.tryLock(0):
            lock.unlock()
            return 0
        info = lock.getLockInfo()
    except Exception:  # noqa: BLE001
        log.debug("读设置进程锁信息失败", exc_info=True)
        return 0
    values = list(info) if isinstance(info, (tuple, list)) else []
    if values and isinstance(values[0], bool):   # 某些绑定版本第一项是「成功与否」
        values = values[1:]
    try:
        return int(values[0]) if values else 0
    except (TypeError, ValueError):
        return 0


def pick_settings_window(windows: list[Window], pid: int) -> Window | None:
    """这个 pid 的窗里挑设置窗：标题含「设置 / Settings」的优先，否则取最前面那扇。"""
    mine = [window for window in windows if window.pid == pid and window.title]
    for window in mine:
        lowered = window.title.lower()
        if any(hint in lowered for hint in _TITLE_HINTS):
            return window
    return mine[0] if mine else None


def focus_settings_process(lock_path: str | Path, *, windows: Callable[[], list[Window]] = list_windows,
                           focus: Callable[[int], bool] = focus_window) -> bool:
    """把已开着的设置窗调到前台；成功 True。"""
    pid = settings_process_pid(lock_path)
    if not pid:
        return False
    window = pick_settings_window(windows(), pid)
    if window is None:
        log.info("设置进程 %d 在跑，但没找到它的窗口", pid)
        return False
    ok = bool(focus(window.hwnd))
    log.info("设置窗口%s前台（pid=%d，标题「%s」）", "已调到" if ok else "没能调到", pid, window.title)
    return ok
