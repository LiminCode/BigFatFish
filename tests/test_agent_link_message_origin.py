# -*- coding: utf-8 -*-
"""联动气泡的来源标注：``_show_link_bubble`` / 提醒带 ``origin``（通道 + 最近一条记录的会话），
旧桩 / 窄签名的窗不认 ``origin`` 也照样收到气泡。"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from pet.agent_link import AgentLinkManager
from pet.config import Config

app = QApplication.instance() or QApplication([])


class _WideWin:
    """认 origin 的窗（OverlayShell 的签名）。"""

    def __init__(self) -> None:
        self.bubbles: list[tuple[str, dict | None]] = []
        self.alerts: list[tuple[str, dict]] = []

    def isVisible(self):  # noqa: N802
        return True

    def show_bubble(self, text, duration_ms=3000, origin=None, **_kw):
        self.bubbles.append((text, origin))

    def show_alert(self, text, **kwargs):
        self.alerts.append((text, kwargs))


class _NarrowWin:
    """旧桩：show_bubble / show_alert 都不认 origin。"""

    def __init__(self) -> None:
        self.bubbles: list[str] = []
        self.alerts: list[str] = []

    def isVisible(self):  # noqa: N802
        return True

    def show_bubble(self, text, duration_ms=3000):
        self.bubbles.append(text)

    def show_alert(self, text, subtitle="", duration_ms=0, buttons=None, sticky=True, alert_id=""):
        self.alerts.append(text)


def _manager(tmp_path, win):
    return AgentLinkManager(win, Config(base=tmp_path), min_interval=0.0)


def test_link_bubble_carries_the_channel_and_the_session_of_the_latest_record(tmp_path):
    win = _WideWin()
    mgr = _manager(tmp_path, win)
    try:
        mgr._show_link_bubble("Claude Code 开始干活啦～", important=True, agent_key="claude")
        mgr._remember_dialogue_record("claude", {"event": "Stop", "sessionId": "sess-1"})
        mgr._show_link_bubble("Claude Code 干完活啦", important=True, agent_key="claude")
        mgr._remember_dialogue_record("claude_wsl", {"event": "Stop", "sessionId": "sess-wsl"})
        mgr._show_link_bubble("WSL 那边停了", important=True, agent_key="claude_wsl")
        mgr._show_link_bubble("全局提示", important=True)
        assert win.bubbles == [
            ("Claude Code 开始干活啦～", {"agent": "claude", "session_id": "", "name": "Claude Code"}),
            ("Claude Code 干完活啦", {"agent": "claude", "session_id": "sess-1", "name": "Claude Code"}),
            ("WSL 那边停了", {"agent": "claude_wsl", "session_id": "sess-wsl", "name": "Claude Code (WSL)"}),
            ("全局提示", None),
        ]
        assert mgr._bubble_origin("claude", "explicit")["session_id"] == "explicit", "给了会话 id 就用给的"
    finally:
        mgr.shutdown()


def test_failure_alert_and_interaction_alert_carry_their_session(tmp_path):
    win = _WideWin()
    mgr = _manager(tmp_path, win)
    try:
        mgr._on_execution_failed("claude", {"sessionId": "sess-9", "failureType": "tool_failed"})
        assert len(win.alerts) == 1
        text, kwargs = win.alerts[0]
        assert "失败" in text and kwargs["origin"] == {"agent": "claude", "session_id": "sess-9", "name": "Claude Code"}
        mgr._register_interaction("claude", kind="approval", text="有审批等你决定", rpc_id="r1", session_id="sess-7")
        text, kwargs = win.alerts[-1]
        assert text == "有审批等你决定" and kwargs["origin"]["session_id"] == "sess-7"
        assert kwargs["alert_type"] == "approval" and kwargs["priority"] == 0
    finally:
        mgr.shutdown()


def test_narrow_windows_still_get_the_bubble_and_the_alert(tmp_path):
    win = _NarrowWin()
    mgr = _manager(tmp_path, win)
    try:
        mgr._remember_dialogue_record("claude", {"event": "Stop", "sessionId": "sess-1"})
        mgr._show_link_bubble("干完活啦", important=True, agent_key="claude")
        mgr._on_execution_failed("claude", {"sessionId": "sess-9"})
        mgr._register_interaction("claude", kind="question", text="有问题要你答", rpc_id="q1", session_id="sess-7")
        assert win.bubbles == ["干完活啦"]
        assert len(win.alerts) == 2 and win.alerts[-1] == "有问题要你答"
    finally:
        mgr.shutdown()
