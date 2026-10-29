# -*- coding: utf-8 -*-
"""Claude 桌面版（Code 标签页）里的会话：点会话小鱼直接跳到那个对话。

2026-10-28 实机：桌面版起的会话进程链往上第一个有窗口的祖先就是桌面版本身，原来当成
终端处理，只能把窗口调到前台、提示「具体标签页要自己选」。运行清单
``~/.claude/sessions/<pid>.json`` 里 ``entrypoint`` 是 ``claude-desktop``，``hostSessionId``
是桌面版那边的会话 id（``local_…``）；应用给每个会话的外链是
``claude://claude.ai/epitaxy/<id>``，打开它就切到那个对话。
"""
from __future__ import annotations

import pytest

from pet import claude_session_info as si
from pet import claude_session_jump as sj
from pet.claude_session_jump import Window

HOST = "local_0a1b2c3d-1111-4222-8333-444455556666"
LINK = f"claude://claude.ai/epitaxy/{HOST}"


@pytest.mark.parametrize("host, kept", [
    (HOST, HOST),
    ("", None),
    ("local_../../x", None),           # 不像 id 的不收
    ("session_01AbCdEfGh", None),      # 桌面版本地会话只认 local_…
])
def test_the_registry_host_session_is_kept(host, kept):
    detail = si.SessionDetail()
    si.apply_registry(detail, {"pid": 7, "entrypoint": "claude-desktop", "hostSessionId": host})
    assert detail.entrypoint == "claude-desktop"
    assert detail.extra.get("host_session") == kept


class _Desk:
    def __init__(self, uri_ok=True):
        self.log: list = []
        self.kwargs = dict(
            windows=lambda: [Window(1, 50, "Claude", "claude.exe")],
            focus=lambda hwnd: (self.log.append(("focus", hwnd)), True)[1],
            chain=lambda pid: [(pid, "claude.exe"), (50, "claude.exe")],
            uri=lambda uri: (self.log.append(("uri", uri)), uri_ok)[1],
            vscode=lambda detail, target="": (self.log.append(("code", target)), True)[1],
            workspaces=lambda: [],
            sleep=lambda seconds: None)


def _detail(**over) -> si.SessionDetail:
    detail = si.SessionDetail(**{"agent": "claude", "session_id": "7b58c690", "entrypoint": "claude-desktop",
                                 "cwd": r"C:\work\shop", "pid": 38428, "alive": True, **over})
    return detail


def test_a_desktop_session_opens_its_own_conversation_link():
    desk = _Desk()
    detail = _detail()
    detail.extra["host_session"] = HOST
    result = sj.jump(detail, **desk.kwargs)
    assert result.ok and desk.log == [("uri", LINK)], "不再只是把桌面版窗口调到前台"
    assert result.message == sj.t("session_jump.ui.jumped_conversation_claude_desktop")


def test_a_desktop_session_without_its_host_id_keeps_the_old_path():
    desk = _Desk()
    result = sj.jump(_detail(), **desk.kwargs)
    assert result.ok and desk.log == [("focus", 1)]


def test_a_failed_link_falls_back_to_bringing_the_window_up():
    desk = _Desk(uri_ok=False)
    detail = _detail()
    detail.extra["host_session"] = HOST
    assert sj.jump(detail, **desk.kwargs).ok and desk.log == [("uri", LINK), ("focus", 1)]
