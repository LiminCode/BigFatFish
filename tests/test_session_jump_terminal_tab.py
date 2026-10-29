# -*- coding: utf-8 -*-
"""终端里的会话：Windows Terminal 窗口调到前台之后，再选中这个对话所在的标签页。

Claude Code 默认把终端标题设成对话标题，前面带状态符号（空闲 ``✳``，干活时是转圈的盲文点）。
Windows Terminal 的标签页在 UI 自动化里是 ``TabItem``，名字就是标题，能 ``Select()``。
2026-10-28 实机：本机 Windows Terminal 的标签页读得到名字、可选中。
"""
from __future__ import annotations

import pytest

from pet import claude_session_info as si
from pet import claude_session_jump as sj
from pet.claude_session_jump import Window


@pytest.mark.parametrize("names, hints, index", [
    (["Ubuntu-24.04", "✳ Fix the login redirect", "pwsh"], ("Fix the login redirect",), 1),
    (["⠂ Fix the login redirect", "pwsh"], ("Fix the login redirect",), 0),        # 干活中的转圈符号
    (["✳ Fix the login redirect loop", "✳ Fix the login redirect"], ("Fix the login redirect",), 1),  # 全等优先
    (["✳ shop-api-3f", "pwsh"], ("没对上的标题", "shop-api-3f"), 0),              # 标题对不上用名字
    (["Ubuntu-24.04", "pwsh"], ("Fix the login redirect",), None),
    (["✳ ab", "x"], ("ab",), None),                                                 # 太短的不认
])
def test_the_tab_showing_this_conversation_is_picked(names, hints, index):
    assert sj.pick_tab(names, hints) == index


class _Desk:
    def __init__(self, process="windowsterminal.exe", selected=True):
        self.log: list = []
        self.kwargs = dict(
            windows=lambda: [Window(5, 20, "✳ Fix the login redirect", process)],
            focus=lambda hwnd: (self.log.append(("focus", hwnd)), True)[1],
            chain=lambda pid: [(pid, "claude.exe"), (30, "pwsh.exe"), (20, process)],
            uri=lambda uri: True,
            vscode=lambda detail, target="": True,
            workspaces=lambda: [],
            sleep=lambda seconds: None,
            select_tab=lambda hwnd, hints: (self.log.append(("tab", hwnd, hints)), selected)[1])


def _detail(**over) -> si.SessionDetail:
    return si.SessionDetail(**{"agent": "claude", "session_id": "s1", "entrypoint": "cli", "pid": 40,
                               "cwd": r"C:\work\shop", "title": "Fix the login redirect", "name": "shop-3f",
                               "alive": True, **over})


def test_after_bringing_windows_terminal_up_the_conversation_tab_is_selected():
    desk = _Desk()
    result = sj.jump(_detail(), **desk.kwargs)
    assert desk.log == [("focus", 5), ("tab", 5, ("Fix the login redirect", "shop-3f"))]
    assert result.ok and result.message == sj.t("session_jump.ui.switched_terminal_tab")


def test_when_no_tab_matches_the_old_message_stays():
    desk = _Desk(selected=False)
    assert sj.jump(_detail(), **desk.kwargs).message == sj.t("session_jump.ui.switched_terminal_window_pick_tab")


def test_wsl_sessions_do_not_pick_a_tab_by_the_distro_name():
    desk = _Desk()
    detail = _detail(agent="claude_wsl", distro="Ubuntu-24.04", pid=None)
    sj.jump(detail, wsl_env={"WT_SESSION": "x"}, **desk.kwargs)
    assert ("tab", 5, ("Fix the login redirect", "shop-3f")) in desk.log, "发行版名会对上随便哪个 Ubuntu 标签页"


def test_other_terminals_are_not_asked_for_tabs():
    desk = _Desk(process="wezterm-gui.exe")
    assert sj.jump(_detail(), **desk.kwargs).message == sj.t("session_jump.ui.switched_terminal_window_pick_tab")
    assert desk.log == [("focus", 5)]
