# -*- coding: utf-8 -*-
"""桌面探测小工具（Windows）：光标可见性、前台窗口信息、系统空闲秒数。

模块名是历史遗留：「看看屏幕」和主动识屏在 2026-11-18 整个删掉了（ADR 0016），
截屏和调视觉模型的代码随之删除；这里只剩全屏 / 穿透 watcher、Slack 关注等还在用的探测函数。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import sys
from pathlib import Path

log = logging.getLogger('big-fat-fish')

CURSOR_SHOWING = 0x00000001
CURSOR_SUPPRESSED = 0x00000002


class _CursorInfo(ctypes.Structure):
    _fields_ = [
        ('cbSize', ctypes.c_uint),
        ('flags', ctypes.c_uint),
        # ctypes.wintypes does not expose HCURSOR on every Python build;
        # HANDLE has the same pointer-sized layout.
        ('hCursor', ctypes.wintypes.HANDLE),
        ('ptScreenPos', ctypes.wintypes.POINT),
    ]


def get_cursor_visibility(user32=None) -> str:
    """Return SHOWING, HIDDEN, SUPPRESSED, or UNKNOWN without changing input."""
    if sys.platform != 'win32':
        return 'UNKNOWN'
    try:
        user32 = user32 or ctypes.windll.user32
        get_cursor_info = user32.GetCursorInfo
        get_cursor_info.argtypes = [ctypes.POINTER(_CursorInfo)]
        get_cursor_info.restype = ctypes.wintypes.BOOL
        info = _CursorInfo()
        info.cbSize = ctypes.sizeof(_CursorInfo)
        if not get_cursor_info(ctypes.byref(info)):
            return 'UNKNOWN'
        if info.flags & CURSOR_SHOWING:
            return 'SHOWING'
        if info.flags & CURSOR_SUPPRESSED:
            return 'SUPPRESSED'
        return 'HIDDEN'
    except (AttributeError, OSError, TypeError, RuntimeError):
        return 'UNKNOWN'

MAX_EDGE = 768        # 缩到最长边 768px：够看懂屏幕，token 又不贵
JPEG_QUALITY = 70
DEFAULT_VISION_MODEL = 'deepseek-v4-flash-vision-exp'


def foreground_window_info() -> dict | None:
    """获取前台窗口详细信息：{hwnd, pid, process, title, rect(x,y,w,h)}。
    若窗口不可见/最小化/被 cloaked 或获取失败，返回 None。"""
    if sys.platform != 'win32':
        return None
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        # 显式声明签名：默认 restype=c_int 会在 64 位下截断 HWND/HANDLE
        user32.GetForegroundWindow.restype = ctypes.wintypes.HWND
        user32.IsWindowVisible.argtypes = [ctypes.wintypes.HWND]
        user32.IsIconic.argtypes = [ctypes.wintypes.HWND]
        user32.GetWindowRect.argtypes = [ctypes.wintypes.HWND, ctypes.POINTER(ctypes.wintypes.RECT)]
        user32.GetWindowTextLengthW.argtypes = [ctypes.wintypes.HWND]
        user32.GetWindowTextW.argtypes = [ctypes.wintypes.HWND, ctypes.c_wchar_p, ctypes.c_int]
        user32.GetWindowThreadProcessId.argtypes = [ctypes.wintypes.HWND, ctypes.POINTER(ctypes.c_ulong)]
        kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.QueryFullProcessImageNameW.argtypes = [
            ctypes.wintypes.HANDLE, ctypes.c_ulong, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong),
        ]
        kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None

        # 检查窗口可见性与最小化
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return None

        # 检查是否被 DWM 隐藏/幽灵（如虚拟桌面切换、UWP 挂起）
        # DWMWA_CLOAKED = 14；DWM 不可用时继续使用 User32 信息。
        dwmapi = None
        try:
            dwmapi = ctypes.windll.dwmapi
            dwmapi.DwmGetWindowAttribute.argtypes = [
                ctypes.wintypes.HWND, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong,
            ]
            dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
            cloaked = ctypes.c_int(0)
            if dwmapi.DwmGetWindowAttribute(
                hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
            ) == 0 and cloaked.value != 0:
                return None
        except (AttributeError, OSError, TypeError, RuntimeError):
            dwmapi = None

        # 获取窗口矩形边界：优先 DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS = 9)
        rect: tuple[int, int, int, int] | None = None
        if dwmapi is not None:
            try:
                rect_dwm = ctypes.wintypes.RECT()
                if dwmapi.DwmGetWindowAttribute(
                    hwnd, 9, ctypes.byref(rect_dwm), ctypes.sizeof(rect_dwm)
                ) == 0:
                    w = rect_dwm.right - rect_dwm.left
                    h = rect_dwm.bottom - rect_dwm.top
                    if w > 0 and h > 0:
                        rect = (rect_dwm.left, rect_dwm.top, w, h)
            except (AttributeError, OSError, TypeError, RuntimeError):
                pass

        if rect is None:
            rect_raw = ctypes.wintypes.RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(rect_raw)):
                w = rect_raw.right - rect_raw.left
                h = rect_raw.bottom - rect_raw.top
                if w > 0 and h > 0:
                    rect = (rect_raw.left, rect_raw.top, w, h)

        if rect is None:
            return None

        # 标题
        length = user32.GetWindowTextLengthW(hwnd)
        title = ''
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.strip()

        # PID 与 进程名
        pid = ctypes.c_ulong(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc = ''
        if pid.value:
            hproc = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
            if hproc:
                try:
                    pbuf = ctypes.create_unicode_buffer(260)
                    size = ctypes.c_ulong(260)
                    if kernel32.QueryFullProcessImageNameW(hproc, 0, pbuf, ctypes.byref(size)):
                        proc = Path(pbuf.value).name
                finally:
                    kernel32.CloseHandle(hproc)

        return {
            'hwnd': hwnd,
            'pid': pid.value,
            'process': proc,
            'title': title,
            'rect': rect,
        }
    except Exception:
        return None


def get_system_idle_seconds() -> float:
    """通过 GetLastInputInfo 获取系统键盘鼠标闲置秒数；非 Windows 恒返回 0.0。"""
    if sys.platform != 'win32':
        return 0.0
    try:
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [
                ('cbSize', ctypes.c_uint),
                ('dwTime', ctypes.c_ulong),
            ]

        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            uptime_ms = ctypes.windll.kernel32.GetTickCount()
            idle_ms = uptime_ms - info.dwTime
            return max(0.0, idle_ms / 1000.0)
    except Exception:
        pass
    return 0.0


