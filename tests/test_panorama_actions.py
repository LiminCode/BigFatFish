# -*- coding: utf-8 -*-
"""配置全景页面上的动作（``pet/panorama/actions.py``）：现在只有一个——给联动通道装 hooks。

动作不是改设置：它让主进程做一件事。这里从动作处理器的公开面测：参数校验、调管理器的「已同意、装」那一半、
装完让服务只重探那一侧；WSL 那条是后台装，处理器先回 pending，装完的信号到了再重探。
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, Signal

from pet.panorama import actions


class _Manager(QObject):
    install_finished = Signal(str, bool, str, int)

    def __init__(self, outcome: str) -> None:
        super().__init__()
        self.outcome, self.asked = outcome, []

    def install_hooks_consented(self, agent_key: str) -> str:
        self.asked.append(agent_key)
        return self.outcome


def _handler(manager, refreshed):
    return actions.repair_hooks(lambda: manager, refreshed.append)


def test_a_local_install_writes_at_once_and_reprobes_the_windows_side():
    manager, refreshed = _Manager("installed"), []
    out = _handler(manager, refreshed)({"agent": "claude"})
    assert out == {"agent": "claude", "state": "installed"} and manager.asked == ["claude"] and refreshed == ["win"]


def test_a_wsl_install_is_pending_and_the_wsl_side_is_reprobed_when_the_install_lands():
    manager, refreshed = _Manager("pending"), []
    run = _handler(manager, refreshed)
    assert run({"agent": "claude_wsl"}) == {"agent": "claude_wsl", "state": "pending"} and refreshed == []
    manager.install_finished.emit("claude_wsl", False, "no distro", 1)
    assert refreshed == [], "没装成就没什么可重探的"
    manager.install_finished.emit("claude_wsl", True, "", 2)
    assert refreshed == ["wsl"]
    run({"agent": "claude_wsl"})
    manager.install_finished.emit("claude_wsl", True, "", 3)
    assert refreshed == ["wsl", "wsl"], "同一个管理器只接一次信号，不会一次装完重探两遍"


def test_a_failed_install_says_so_and_reprobes_nothing():
    manager, refreshed = _Manager("failed"), []
    assert _handler(manager, refreshed)({"agent": "claude"}) == {"agent": "claude", "state": "failed"} and refreshed == []


@pytest.mark.parametrize("body", [{}, {"agent": "cursor"}, {"agent": 3}, "claude", None])
def test_only_the_two_hooked_channels_are_accepted(body):
    manager, refreshed = _Manager("installed"), []
    with pytest.raises(actions.ActionError) as caught:
        _handler(manager, refreshed)(body)
    assert (caught.value.status, caught.value.code) == (400, "bad_agent") and manager.asked == []


def test_without_a_link_manager_the_action_is_unavailable():
    with pytest.raises(actions.ActionError) as caught:
        actions.repair_hooks(lambda: None, lambda side: None)({"agent": "claude"})
    assert (caught.value.status, caught.value.code) == (503, "no_manager")
