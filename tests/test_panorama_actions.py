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


# ───────────────────────── 「现在核对」：让克隆去问一次远端（2026-11-22）─────────────────────────

class _Checker:
    """``check_remote`` 的几个边界换成记账的假货：界面线程、fetch、重探。"""

    def __init__(self, tmp_path, *, outcome=(True, ""), ready=True):
        self.repo = tmp_path / "vault"
        if ready:
            (self.repo / ".git").mkdir(parents=True)
        self.outcome, self.log = outcome, []

    def on_gui(self, work):
        self.log.append("gui")
        return work()

    def fetch(self, repo_dir, *, token):
        self.log.append(("fetch", str(repo_dir), token))
        return self.outcome

    def handler(self, **overrides):
        options = {"fetch": self.fetch, "token": lambda: "tok"}
        options.update(overrides)
        return actions.check_remote({"personal": lambda: str(self.repo)}, self.on_gui,
                                    lambda side: self.log.append(("refresh", side)), **options)


def test_checking_fetches_the_clone_off_the_gui_thread_then_reprobes_this_machine(tmp_path):
    checker = _Checker(tmp_path)
    run = checker.handler()
    assert run.off_gui is True, "fetch 要联网：不许占着界面线程等"
    assert run({"repo": "personal"}) == {"repo": "personal", "state": "checked"}
    assert checker.log == ["gui", ("fetch", str(checker.repo), "tok"), "gui", ("refresh", "win")]


def test_a_check_that_cannot_reach_the_remote_says_failed_and_still_reprobes(tmp_path):
    """没连上也要重探：git 已经把 FETCH_HEAD 清空了，磁贴要改口说「上次核对没连上」。"""
    checker = _Checker(tmp_path, outcome=(False, "fatal: unable to access"))
    assert checker.handler()({"repo": "personal"}) == {"repo": "personal", "state": "failed"}
    assert ("refresh", "win") in checker.log


def test_a_missing_clone_is_not_fetched(tmp_path):
    checker = _Checker(tmp_path, ready=False)
    assert checker.handler()({"repo": "personal"}) == {"repo": "personal", "state": "missing"}
    assert not any(isinstance(entry, tuple) for entry in checker.log)


def test_a_second_check_while_one_is_running_is_turned_away(tmp_path):
    checker = _Checker(tmp_path)
    answers = []

    def slow_fetch(repo_dir, *, token):
        answers.append(run({"repo": "personal"}))            # 第一次还没回来，又点了一次
        return True, ""

    run = checker.handler(fetch=slow_fetch)
    assert run({"repo": "personal"})["state"] == "checked" and answers == [{"repo": "personal", "state": "busy"}]
    assert run({"repo": "personal"})["state"] == "checked", "上一次结束后可以再核对"


def test_a_refresh_that_cannot_run_does_not_turn_a_good_check_into_an_error(tmp_path):
    checker = _Checker(tmp_path)

    def refresh(side):
        raise RuntimeError("gui is busy")

    run = actions.check_remote({"personal": lambda: str(checker.repo)}, checker.on_gui, refresh, fetch=checker.fetch, token=lambda: "")
    assert run({"repo": "personal"}) == {"repo": "personal", "state": "checked"}


@pytest.mark.parametrize("body", [{}, {"repo": "work"}, {"repo": 3}, "personal", None])
def test_only_registered_clones_can_be_checked(tmp_path, body):
    checker = _Checker(tmp_path)
    with pytest.raises(actions.ActionError) as caught:
        checker.handler()(body)
    assert (caught.value.status, caught.value.code) == (400, "bad_repo") and checker.log == []


# ───────────────────────── 核对一次 = 运行记录里的一行（瀑布流的第一种来源）─────────────────────────

class _States:
    """核对前后各问一次「远端分支此刻指向哪、差几个提交」；按脚本依次回答。"""

    def __init__(self, *answers):
        self.answers, self.asked = list(answers), []

    def __call__(self, repo_dir):
        self.asked.append(str(repo_dir))
        return self.answers.pop(0)


def _journaled(tmp_path, states, **overrides):
    from pet import run_journal

    checker = _Checker(tmp_path, **overrides)
    journal = run_journal.Journal(tmp_path / "journal")
    return checker, journal, checker.handler(journal=journal, state=states)


def test_a_check_that_brings_news_is_recorded_with_what_moved(tmp_path):
    states = _States({"head": "1a2b3c4d5e6f", "behind": 0, "ahead": 0}, {"head": "5d6e7f8a9b0c", "behind": 46, "ahead": 0})
    checker, journal, run = _journaled(tmp_path, states)
    assert run({"repo": "personal"})["state"] == "checked"
    row, = journal.read()
    assert (row["job"], row["trigger"], row["result"]) == ("vault_check", "manual", "ok")
    assert row["effects"] == [{"kind": "git", "op": "fetch", "repo": "personal", "before": "1a2b3c4d5e6f", "after": "5d6e7f8a9b0c",
                               "behind": 46, "ahead": 0}]
    assert [step["name"] for step in row["steps"]] == ["fetch"] and states.asked == [str(checker.repo)] * 2


def test_a_check_that_finds_nothing_new_is_a_noop(tmp_path):
    same = {"head": "1a2b3c4d5e6f", "behind": 0, "ahead": 2}
    _, journal, run = _journaled(tmp_path, _States(dict(same), dict(same)))
    run({"repo": "personal"})
    row, = journal.read()
    assert row["result"] == "noop" and row["effects"][0]["ahead"] == 2


def test_a_check_that_cannot_connect_is_recorded_as_failed_with_gits_last_words(tmp_path):
    before = {"head": "1a2b3c4d5e6f", "behind": 0, "ahead": 0}
    _, journal, run = _journaled(tmp_path, _States(dict(before), dict(before)), outcome=(False, "fatal: unable to access the remote"))
    assert run({"repo": "personal"})["state"] == "failed"
    row, = journal.read()
    assert row["result"] == "failed" and row["error"] == "fatal: unable to access the remote"


def test_a_check_that_never_ran_leaves_no_record(tmp_path):
    _, journal, run = _journaled(tmp_path, _States(), ready=False)
    assert run({"repo": "personal"})["state"] == "missing" and journal.read() == []


def test_checking_works_without_a_journal(tmp_path):
    checker = _Checker(tmp_path)
    assert checker.handler(state=_States({"head": "a", "behind": 0, "ahead": 0}, {"head": "a", "behind": 0, "ahead": 0}))(
        {"repo": "personal"})["state"] == "checked"
