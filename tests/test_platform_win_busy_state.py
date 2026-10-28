# -*- coding: utf-8 -*-
"""_fs_user_busy_state 的 QUNS 口径回归测试（2026-09-23 实机频闪案）。

实机证据：overlay 合成窗（全屏置顶分层窗）可见时，Windows
SHQueryUserNotificationState 报 QUNS_BUSY(2)——若兜底把 BUSY 当全屏，
overlay 每显每隐形成 1Hz 自激频闪（soak 日志 64 次翻转）。只有
QUNS_RUNNING_D3D_FULL_SCREEN(3) / QUNS_PRESENTATION_MODE(4) 才是真全屏信号。
"""
from __future__ import annotations

import ctypes
import sys

import pytest

from pet import platform_win


@pytest.mark.skipif(sys.platform != "win32", reason="QUNS 是 Windows API")
@pytest.mark.parametrize("state,expected", [
    (1, False),   # QUNS_NOT_PRESENT
    (2, False),   # QUNS_BUSY——不收（自身 overlay 会触发， noisy）
    (3, True),    # QUNS_RUNNING_D3D_FULL_SCREEN
    (4, True),    # QUNS_PRESENTATION_MODE
    (5, False),   # QUNS_ACCEPTS_NOTIFICATIONS
    (6, False),   # QUNS_QUIET_TIME
])
def test_busy_state_quns_values(monkeypatch, state, expected):
    def fake_quns(buf):
        ctypes.cast(buf, ctypes.POINTER(ctypes.c_int)).contents.value = state
        return 0  # S_OK
    monkeypatch.setattr(ctypes.windll.shell32,
                        "SHQueryUserNotificationState", fake_quns)
    busy, raw = platform_win._fs_user_busy_state()
    assert busy is expected
    assert raw == state


# ---- 勿扰（quiet hours）：WNF_SHEL_QUIETHOURS_ACTIVE_PROFILE_CHANGED ----
# 2026-10-27 实机（Win11 26300）：通知面板里开勿扰 → 01000000，关掉 → 00000000。


def _fake_wnf(data: bytes, status: int = 0):
    def fake(name, type_id, scope, stamp, buf, size):
        assert ctypes.cast(name, ctypes.POINTER(ctypes.c_ulonglong)).contents.value == platform_win.WNF_QUIET_HOURS
        size_p = ctypes.cast(size, ctypes.POINTER(ctypes.c_ulong))
        ctypes.memmove(buf, data, len(data))
        size_p.contents.value = len(data)
        return status
    return fake


@pytest.mark.skipif(sys.platform != "win32", reason="WNF 是 Windows 内核接口")
@pytest.mark.parametrize("data,status,expected", [
    (b"\x00\x00\x00\x00", 0, 0),           # 勿扰关
    (b"\x01\x00\x00\x00", 0, 1),           # 勿扰开（仅优先通知）
    (b"\x02\x00\x00\x00", 0, 2),           # 仅闹钟
    (b"", 0, 0),                           # 没写过这个状态
    (b"\x01\x00\x00\x00", 0xC0000034, 0),  # 读失败 → 当没开（照常弹，不吞通知）
])
def test_quiet_hours_profile_decodes_wnf(monkeypatch, data, status, expected):
    monkeypatch.setattr(ctypes.windll.ntdll, "NtQueryWnfStateData", _fake_wnf(data, status))
    assert platform_win.quiet_hours_profile() == expected


@pytest.mark.skipif(sys.platform != "win32", reason="WNF 是 Windows 内核接口")
def test_quiet_hours_profile_real_call_returns_a_small_int():
    assert platform_win.quiet_hours_profile() in (0, 1, 2)
