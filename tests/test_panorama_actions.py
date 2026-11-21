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


# ───────────────────────── 试听（会话提示音的设置页，2026-11-21） ─────────────────────────

class _Config:
    def __init__(self, agent_link: dict) -> None:
        self.data = {"agent_link": agent_link}

    def get(self, key, default=None):
        return self.data.get(key, default)


def _preview(played, agent_link=None):
    return actions.preview_sound(lambda: _Config(agent_link or {}), play=lambda path, volume: played.append((path, volume)))


def test_preview_plays_the_value_the_page_sends_at_the_groups_volume():
    from pet.click_sound import resolve_builtin_sound

    played = []
    out = _preview(played, {"sound_volume": 0.3})({"group": "link_sounds", "id": "sound_done_path", "value": "builtin:agent-bell"})
    assert out == {"group": "link_sounds", "id": "sound_done_path", "state": "played"}
    assert played == [(resolve_builtin_sound("builtin:agent-bell"), 0.3)]


def test_preview_without_a_value_plays_what_is_stored_and_a_custom_file_by_its_path(tmp_path):
    from pet.click_sound import resolve_builtin_sound

    custom = tmp_path / "ding.wav"
    custom.write_bytes(b"RIFF")
    played = []
    run = _preview(played, {"sound_start_path": str(custom)})
    assert run({"group": "link_sounds", "id": "sound_start_path"})["state"] == "played"
    assert run({"group": "link_sounds", "id": "sound_error_path"})["state"] == "played"      # 没存过：默认的内置音
    assert [p for p, _v in played] == [custom, resolve_builtin_sound("builtin:agent-error")]
    assert all(v == 0.65 for _p, v in played)                                                  # 音量取组里存着的（默认 0.65）


def test_preview_of_a_missing_file_says_so_instead_of_failing(tmp_path):
    played = []
    run = _preview(played)
    assert run({"group": "link_sounds", "id": "sound_done_path", "value": str(tmp_path / "gone.wav")})["state"] == "missing"
    assert run({"group": "link_sounds", "id": "sound_done_path", "value": "builtin:no-such"})["state"] == "missing"
    assert run({"group": "link_sounds", "id": "sound_done_path", "value": ""})["state"] == "missing"
    assert played == []


@pytest.mark.parametrize("body, status, code", [
    (None, 400, "bad_request"), ("x", 400, "bad_request"),
    ({"group": "nope", "id": "sound_done_path"}, 404, "unknown_group"),
    ({"group": "link_sounds", "id": "sound_volume"}, 400, "bad_setting"),            # 这一项没有试听按钮
    ({"group": "work_briefing", "id": "model"}, 400, "bad_setting"),
    ({"group": "link_sounds", "id": "sound_done_path", "value": 3}, 400, "bad_value"),
])
def test_preview_only_accepts_a_setting_that_declares_the_action(body, status, code):
    played = []
    with pytest.raises(actions.ActionError) as caught:
        _preview(played)(body)
    assert (caught.value.status, caught.value.code) == (status, code) and played == []


def test_preview_without_a_config_is_a_503():
    run = actions.preview_sound(lambda: None, play=lambda *_a, **_k: None)
    with pytest.raises(actions.ActionError) as caught:
        run({"group": "link_sounds", "id": "sound_done_path"})
    assert (caught.value.status, caught.value.code) == (503, "no_config")
