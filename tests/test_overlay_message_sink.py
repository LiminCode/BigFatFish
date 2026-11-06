# -*- coding: utf-8 -*-
"""overlay 壳的消息记录口：``show_bubble`` / ``show_alert`` 进来的每条都先交给 ``message_sink``，
隐藏 / 抑制期照记（错过的才最该留着）；没有注入时什么都不发生；自言自语不进记录。"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from tests.test_overlay_chat_proactive import _make_shell

app = QApplication.instance() or QApplication([])


def test_bubbles_and_alerts_are_recorded_before_any_gate(tmp_path):
    shell, _ = _make_shell(tmp_path)
    try:
        shell.overlay.show()
        noted: list = []
        shell.message_sink = lambda text, subtitle, kind, origin: noted.append((text, subtitle, kind, origin))
        shell.show_bubble("干完活啦", origin={"agent": "claude", "session_id": "s1", "name": "Claude Code"})
        shell.show_alert("有审批等你决定", subtitle="Bash", alert_id="a", sticky=True,
                         origin={"agent": "claude", "session_id": "s1", "name": "Claude Code"})
        shell.set_bubble_suppressed(True)
        shell.show_bubble("设置页开着也记")
        shell.set_bubble_suppressed(False)
        shell.set_pet_visible(False)
        shell.show_bubble("隐藏着也记", subtitle="小字")
        assert noted == [
            ("干完活啦", "", "bubble", {"agent": "claude", "session_id": "s1", "name": "Claude Code"}),
            ("有审批等你决定", "Bash", "alert", {"agent": "claude", "session_id": "s1", "name": "Claude Code"}),
            ("设置页开着也记", "", "bubble", None),
            ("隐藏着也记", "小字", "bubble", None),
        ]
        assert shell._speech_bubble._raw_text != "隐藏着也记", "记了不等于弹了：隐藏期照旧不冒泡"
    finally:
        shell._delete_runtime_marker()


def test_self_talk_and_a_failing_sink_do_not_disturb_the_bubble(tmp_path):
    shell, _ = _make_shell(tmp_path)
    try:
        shell.overlay.show()
        noted: list = []
        shell.message_sink = lambda *args: noted.append(args)
        shell._show_self_talk_text("今天天气不错")
        assert noted == [], "自言自语不是通知"
        shell.show_bubble("没接记录也照常", origin="not a dict")
        assert noted[-1][3] is None, "来源不是字典就当没有"

        def boom(*_args):
            raise RuntimeError("sink down")

        shell.message_sink = boom
        shell.show_bubble("记录坏了气泡也要出")
        assert shell._speech_bubble._raw_text == "记录坏了气泡也要出"
        shell.message_sink = None
        shell.show_bubble("没注入")
    finally:
        shell._delete_runtime_marker()
