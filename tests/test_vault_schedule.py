# -*- coding: utf-8 -*-
"""知识库的定时同步：设置、什么时候该跑（纯逻辑）、三种模式各做什么、Qt 侧的服务。

「什么时候该跑」直接喂时间和工作区的样子测；三种模式对真的 git 测（沿用同步器测试里的那个小世界）；服务把线程和时钟
换成记账的假货，从它的公开面测：到点了有没有跑、跑的是什么、跑完发了什么信号。
"""
from __future__ import annotations

import os
import time

import pytest
from PySide6.QtWidgets import QApplication

from pet import vault_sync as vs
from pet.vault_sync_service import VaultSyncService
from tests.test_vault_sync import _commit_and_push, _git, _write, world  # noqa: F401 - world 是 fixture

app = QApplication.instance() or QApplication([])
HOUR = 3600.0
T0 = 1_800_000_000.0
ON = vs.normalize({"enabled": True})


# ───────────────────────── 设置 ─────────────────────────

def test_the_defaults_are_off_auto_hourly_and_five_minutes_after_the_last_edit():
    assert vs.normalize(None) == {"enabled": False, "mode": "auto", "interval_minutes": 60, "idle_minutes": 5}
    assert vs.normalize({"enabled": True, "mode": "watch", "interval_minutes": 30, "idle_minutes": 0}) == {
        "enabled": True, "mode": "watch", "interval_minutes": 30, "idle_minutes": 0}


@pytest.mark.parametrize(("raw", "key", "expected"), [
    ({"enabled": "yes"}, "enabled", False), ({"mode": "yolo"}, "mode", "auto"), ({"interval_minutes": 1}, "interval_minutes", vs.INTERVAL_RANGE[0]),
    ({"interval_minutes": 10**6}, "interval_minutes", vs.INTERVAL_RANGE[1]), ({"interval_minutes": "soon"}, "interval_minutes", 60),
    ({"idle_minutes": -3}, "idle_minutes", 0), ({"idle_minutes": True}, "idle_minutes", 5)])
def test_values_nobody_should_have_written_fall_back_to_something_safe(raw, key, expected):
    assert vs.normalize(raw)[key] == expected


# ───────────────────────── 什么时候该跑 ─────────────────────────

def _decide(settings=ON, **overrides):
    facts = {"now": T0, "last_run": T0 - 600, "last_tick": T0 - 60, "started": True, "probe": None, "attempted": ""}
    facts.update(overrides)
    return vs.decide(settings, **facts)


def _edited(seconds_ago: float, *, content: int = 1, files: int = 1, mark: str = "a") -> vs.Probe:
    return vs.Probe(vs.Changes(files=files, content=content), T0 - seconds_ago, mark)


def test_switched_off_nothing_ever_runs():
    off = vs.normalize({"enabled": False})
    assert _decide(off, last_run=None) == "" and _decide(off, last_tick=T0 - 9 * HOUR) == "" and _decide(off, probe=_edited(HOUR)) == ""


def test_the_hourly_fallback_runs_when_the_last_run_is_an_interval_old_or_never_happened():
    assert _decide(last_run=T0 - HOUR + 1) == "" and _decide(last_run=T0 - HOUR) == "schedule" and _decide(last_run=None) == "schedule"
    half_hourly = vs.normalize({"enabled": True, "interval_minutes": 30})
    assert _decide(half_hourly, last_run=T0 - 1800) == "schedule" and _decide(half_hourly, last_run=T0 - 1799) == ""


def test_the_first_look_after_launch_catches_up_only_if_a_run_is_overdue():
    assert _decide(started=False, last_run=T0 - 2 * HOUR) == "startup" and _decide(started=False, last_run=None) == "startup"
    assert _decide(started=False, last_run=T0 - 600) == "", "十分钟前刚跑过：重启一下肥鱼不该再跑一次"


def test_waking_from_sleep_runs_once_instead_of_once_per_missed_hour():
    """电脑睡了一夜：醒来只补一次（两次检查之间隔了很久 = 中间睡过）。"""
    assert _decide(last_tick=T0 - 8 * HOUR, last_run=T0 - 8 * HOUR) == "wake"
    assert _decide(last_tick=T0 - 60, last_run=T0 - 60) == "", "那一次补完之后回到平常的节奏"
    assert _decide(last_tick=T0 - vs.WAKE_GAP_S, last_run=T0 - 600) == "", "正好卡在门槛上不算睡过"


def test_edits_are_synced_once_the_user_has_stopped_typing_for_a_while():
    assert _decide(probe=_edited(4 * 60)) == "", "还在改：别在一句话写到一半的时候提交"
    assert _decide(probe=_edited(5 * 60)) == "idle"
    assert _decide(vs.normalize({"enabled": True, "idle_minutes": 0}), probe=_edited(HOUR)) == "", "0 = 停笔后不同步，只靠每小时那次"
    assert _decide(probe=vs.Probe(vs.Changes(), None, "")) == "", "没有改动"


def test_device_state_alone_does_not_count_as_an_edit():
    assert _decide(probe=_edited(HOUR, content=0, files=2)) == ""


def test_the_same_edits_are_not_retried_every_minute_after_a_run_that_could_not_take_them():
    """上次带着这些改动跑过了（冲突、等审核、没连上）：工作区没再变之前，停笔这条路不再触发；每小时那次照常。"""
    stuck = _edited(HOUR, mark="same")
    assert _decide(probe=stuck, attempted="same") == "" and _decide(probe=stuck, attempted="older") == "idle"
    assert _decide(probe=stuck, attempted="same", last_run=T0 - HOUR) == "schedule"


def test_watch_mode_never_reacts_to_edits_because_it_never_commits():
    watch = vs.normalize({"enabled": True, "mode": "watch"})
    assert _decide(watch, probe=_edited(HOUR)) == "" and _decide(watch, last_run=T0 - HOUR) == "schedule"


def test_probing_the_work_tree_finds_the_newest_edit_and_changes_with_it(world):  # noqa: F811
    assert vs.probe(world.mine) == vs.Probe(vs.Changes(), None, vs.probe(world.mine).fingerprint)
    _write(world.mine, "Notes/a.md", "edited\n")
    _write(world.mine, "Notes/new.md", "fresh\n")
    old, new = time.time() - 900, time.time() - 400
    os.utime(world.mine / "Notes" / "a.md", (old, old))
    os.utime(world.mine / "Notes" / "new.md", (new, new))
    first = vs.probe(world.mine)
    assert (first.changes.files, first.changes.content) == (2, 2) and first.newest_edit == pytest.approx(new, abs=2)
    os.utime(world.mine / "Notes" / "a.md", None)                          # 又动了同一个文件：git status 的输出没变，指纹要变
    assert vs.probe(world.mine).fingerprint != first.fingerprint
    (world.mine / "INDEX.md").unlink()
    assert vs.probe(world.mine).changes.deletions == 1, "删掉的文件没有修改时间可看，不能因此读不出来"


def test_a_deletion_on_its_own_still_has_a_time_so_it_is_noticed_after_the_pause(world):  # noqa: F811
    """实机上见过：只删了一篇笔记，停笔那条路一直不触发（没有文件可看修改时间），要等到下一个钟点。"""
    before = time.time()
    (world.mine / "Notes" / "a.md").unlink()
    look = vs.probe(world.mine)
    assert look.changes.deletions == 1 and look.newest_edit is not None and look.newest_edit >= before - 2, "用所在目录的修改时间"
    settings = vs.normalize({"enabled": True})
    facts = {"last_run": look.newest_edit, "last_tick": None, "started": True, "attempted": ""}
    assert vs.decide(settings, now=look.newest_edit + 299, probe=look, **facts) == ""
    assert vs.decide(settings, now=look.newest_edit + 300, probe=look, **facts) == "idle"


# ───────────────────────── 三种模式 ─────────────────────────

def test_auto_mode_commits_small_edits_and_holds_back_a_deletion(world):  # noqa: F811
    _write(world.mine, "Notes/a.md", "edited\n")
    assert world.sync.run_scheduled(world.mine, ON, "idle").state == "synced" and world.remote_log()[0].startswith("vault: ")
    (world.mine / "Notes" / "a.md").unlink()
    assert world.sync.run_scheduled(world.mine, ON, "schedule").state == "review"
    assert world.last_row()["trigger"] == "schedule" and world.last_row()["result"] == "needs_you"


def test_ask_mode_never_commits_but_still_pulls_when_the_tree_is_clean(world):  # noqa: F811
    ask = vs.normalize({"enabled": True, "mode": "ask"})
    _commit_and_push(world.cloud, "Notes/b.md", "written elsewhere\n")
    assert world.sync.run_scheduled(world.mine, ask, "schedule").pulled == 1
    _write(world.mine, "Notes/a.md", "edited\n")
    _commit_and_push(world.cloud, "Notes/c.md", "more\n")
    out = world.sync.run_scheduled(world.mine, ask, "idle")
    assert (out.state, out.reason, out.files) == ("review", "ask", 1)
    assert _git(world.mine, "log", "--format=%s", "-1") == "from the cloud", "没有替用户提交"
    assert _git(world.mine, "status", "--porcelain") != "" and world.last_row()["effects"][0]["review"] == "ask"
    from pet import personal_vault as pv

    assert pv.upstream_state(world.mine)["behind"] == 1, "但远端的样子是刚问过的：磁贴上的「落后几个」是此刻的"


def test_watch_mode_only_fetches(world):  # noqa: F811
    watch = vs.normalize({"enabled": True, "mode": "watch"})
    _write(world.mine, "Notes/a.md", "edited\n")
    _commit_and_push(world.cloud, "Notes/b.md", "written elsewhere\n")
    out = world.sync.run_scheduled(world.mine, watch, "schedule")
    assert out.state == "checked" and _git(world.mine, "status", "--porcelain") != ""
    assert _git(world.mine, "log", "--format=%s", "-1") == "first", "不提交、不拉取、不推送"
    row = world.last_row()
    assert (row["job"], row["trigger"], row["result"]) == ("vault_check", "schedule", "ok") and row["effects"][0]["behind"] == 1
    assert world.sync.run_scheduled(world.mine, watch, "schedule").state == "checked" and world.last_row()["result"] == "noop"


# ───────────────────────── Qt 侧的服务 ─────────────────────────

class _Config:
    def __init__(self, tmp_path, **settings):
        self.data = {vs.CONFIG_KEY: settings, "personal": {"repo_dir": str(tmp_path / "vault")}}
        self.dir = tmp_path
        (tmp_path / "vault" / ".git").mkdir(parents=True, exist_ok=True)

    def get(self, key, default=None):
        return self.data.get(key, default)


class _Syncer:
    def __init__(self):
        self.calls, self.outcome = [], vs.Outcome("noop")

    def run_scheduled(self, repo_dir, settings, trigger):
        self.calls.append((settings["mode"], trigger))
        return self.outcome


class _Harness:
    def __init__(self, tmp_path, *, last_run=None, probe=None, **settings):
        self.now, self.probed, self.finished, self.told = T0, 0, [], 0
        self.syncer, self.probe_result = _Syncer(), probe or vs.Probe(vs.Changes(), None, "")
        self.config = _Config(tmp_path, **settings)

        def probe_work_tree(_folder):
            self.probed += 1
            return self.probe_result

        self.service = VaultSyncService(self.config, self.syncer, last_run=lambda: last_run, spawn=lambda work: work(),
                                        clock=lambda: self.now, probe=probe_work_tree, after=self._after)
        self.service.finished.connect(lambda outcome, trigger: self.finished.append((outcome.state, trigger)))

    def _after(self):
        self.told += 1

    def tick(self, minutes: float = 1) -> bool:
        self.now += minutes * 60
        return self.service.tick()


def test_the_service_does_nothing_while_the_switch_is_off(tmp_path):
    h = _Harness(tmp_path)
    assert h.tick() is False and h.tick(120) is False and h.syncer.calls == [] and h.probed == 0, "关着的时候连工作区都不看"


def test_the_first_tick_catches_up_and_then_the_hourly_rhythm_takes_over(tmp_path):
    h = _Harness(tmp_path, enabled=True, last_run=T0 - 2 * HOUR)
    assert h.tick() is True and h.syncer.calls == [("auto", "startup")] and h.finished == [("noop", "startup")] and h.told == 1
    assert [h.tick() for _ in range(59)] == [False] * 59, "一小时内不再跑"
    assert h.tick() is True and h.syncer.calls[-1] == ("auto", "schedule")


def test_a_fish_restarted_right_after_a_run_does_not_run_again(tmp_path):
    h = _Harness(tmp_path, enabled=True, last_run=T0 - 300)
    assert h.tick() is False and h.syncer.calls == []
    assert [h.tick() for _ in range(53)] == [False] * 53, "离上次运行还不到一小时"
    assert h.tick() is True and h.syncer.calls == [("auto", "schedule")]


def test_a_long_gap_between_two_ticks_is_a_wake_up(tmp_path):
    h = _Harness(tmp_path, enabled=True, last_run=T0 - 60)
    assert h.tick() is False
    assert h.tick(8 * 60) is True and h.syncer.calls == [("auto", "wake")], "睡了八小时：醒来补一次"
    assert h.tick() is False and h.tick() is False


def test_the_service_syncs_edits_once_the_user_has_stopped_and_does_not_retry_them_every_minute(tmp_path):
    h = _Harness(tmp_path, enabled=True, last_run=T0 - 60)
    h.probe_result = vs.Probe(vs.Changes(files=1, content=1), T0, "edit-1")
    assert [h.tick() for _ in range(4)] == [False] * 4 and h.probed == 4, "刚改完：每分钟看一眼，还不动"
    h.syncer.outcome = vs.Outcome("conflict", conflicts=1)
    assert h.tick() is True and h.syncer.calls == [("auto", "idle")] and h.finished == [("conflict", "idle")]
    assert [h.tick() for _ in range(5)] == [False] * 5, "同样的改动撞过一次冲突：不每分钟再撞"
    h.probe_result = vs.Probe(vs.Changes(files=1, content=1), h.now - 600, "edit-2")       # 用户又改了
    assert h.tick() is True and h.syncer.calls[-1] == ("auto", "idle")


def test_a_run_started_from_the_page_resets_the_hourly_clock(tmp_path):
    h = _Harness(tmp_path, enabled=True, last_run=T0 - 60)
    h.tick(50)
    h.service.note_run()                                                   # 用户在页面上点了「现在同步」
    assert [h.tick() for _ in range(59)] == [False] * 59 and h.tick() is True


def test_the_mode_in_the_settings_is_the_mode_that_runs_and_watch_mode_never_probes(tmp_path):
    h = _Harness(tmp_path, enabled=True, mode="watch", last_run=None)
    h.probe_result = vs.Probe(vs.Changes(files=1, content=1), T0 - HOUR, "x")
    assert h.tick() is True and h.syncer.calls == [("watch", "startup")]
    assert h.tick() is False and h.probed == 0, "只看不动：不用盯着工作区"


def test_a_missing_clone_is_skipped_quietly(tmp_path):
    h = _Harness(tmp_path, enabled=True, last_run=None)
    h.config.data["personal"]["repo_dir"] = str(tmp_path / "nowhere")
    assert h.tick() is False and h.syncer.calls == []


def test_a_run_that_blows_up_frees_the_service_for_the_next_tick(tmp_path):
    h = _Harness(tmp_path, enabled=True, last_run=None)

    def boom(*_args):
        raise RuntimeError("git exploded")

    h.syncer.run_scheduled = boom
    assert h.tick() is True and h.finished == [("failed", "startup")] and h.service.busy is False


def test_a_result_that_arrives_after_stop_is_dropped(tmp_path):
    pending = []
    h = _Harness(tmp_path, enabled=True, last_run=None)
    h.service._spawn = pending.append
    assert h.tick() is True and h.service.busy is True
    h.service.stop()
    pending.pop()()
    assert h.finished == [] and h.told == 0


def test_the_service_learns_when_the_clone_was_last_touched_from_the_run_journal(tmp_path):
    import datetime as dt

    from pet import run_journal

    clock = [dt.datetime(2026, 11, 22, 9, 0, 0)]
    journal = run_journal.Journal(tmp_path / "journal", now=lambda: clock[0])
    assert vs.last_run_time(journal) is None
    journal.start("vault_sync", "manual").finish("ok")
    clock[0] = dt.datetime(2026, 11, 22, 10, 0, 0)
    journal.start("work_briefing", "schedule").finish("ok")                # 别的任务不算
    assert vs.last_run_time(journal) == dt.datetime(2026, 11, 22, 9, 0, 0).timestamp()
    clock[0] = dt.datetime(2026, 11, 22, 11, 0, 0)
    journal.start("vault_check", "manual").finish("noop")                  # 手点的核对也算碰过远端
    assert vs.last_run_time(journal) == dt.datetime(2026, 11, 22, 11, 0, 0).timestamp()
    assert vs.parse_at("not a time") is None
