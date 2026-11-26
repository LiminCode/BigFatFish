# -*- coding: utf-8 -*-
"""随手记复习的 Qt 侧：今天的一轮、打分、攒一攒再推、关掉再开接着推。

纪律：推送用同步的假函数（不起 git）；真的事件循环；样例文字中性。
"""
from __future__ import annotations

import datetime as dt
import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import capture_review as cr
from pet import personal_vault as pv
from pet.config import Config
from pet.review_service import ReviewService
from tests.test_capture_review import _note

app = QApplication.instance() or QApplication([])
NOW = dt.datetime(2026, 11, 26, 9, 0)


class _Sync:
    def __init__(self, ok=True):
        self.calls, self.ok = [], ok

    def __call__(self, repo_dir, paths, message, *, token=""):
        self.calls.append((list(paths), message, token))
        return (True, "") if self.ok else (False, "rejected: fetch first")


def _wait(predicate, budget=5.0):
    deadline = time.monotonic() + budget
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    return predicate()


@pytest.fixture
def setup(tmp_path):
    repo = tmp_path / "AI-Base"
    (repo / ".git").mkdir(parents=True)
    config = Config(base=tmp_path / "cfg")
    config.set(pv.CONFIG_KEY, {"repo_dir": str(repo)})
    sync = _Sync()
    service = ReviewService(config, spawn=lambda job: job(), now=lambda: NOW, token=lambda: "tok", sync=sync, head=lambda _r: "abcdef012345")
    pushes = []
    service.finished.connect(lambda result, manual: pushes.append((result, manual)))
    yield repo, config, sync, service, pushes
    service.stop()


def test_the_round_lists_todays_cards_and_what_comes_next(setup):
    repo, _config, _sync, service, _pushes = setup
    first = _note(repo, "a")
    _note(repo, "b", review="{next: 2026-12-02, interval: 7, count: 1, lapses: 0}")
    state = service.round()
    assert [c.path for c in state["cards"]] == [first] and state["due"] == 1 and state["done"] == 0
    assert state["next"] == dt.date(2026, 12, 2) and service.due_count() == 1


def test_grading_the_last_card_of_the_round_pushes_one_commit(setup):
    repo, config, sync, service, pushes = setup
    a, b = _note(repo, "a"), _note(repo, "b")
    assert service.grade(a, "remember") == {"state": "graded", "next": "2026-11-29", "interval": 3}
    assert sync.calls == [] and service.pending() == [a], "还有一条没打：先不推"
    assert service.grade(b, "forgot")["state"] == "graded"
    assert _wait(lambda: pushes)
    assert sync.calls == [([a, b], "Review: 2 notes\n\n" + a + "\n" + b, "tok")]
    assert pushes[0][0].ok and pushes[0][0].commit == "abcdef012345" and pushes[0][1] is False
    assert service.pending() == [] and service.sync_state == "pushed" and service.pushed_at == "09:00"
    assert cr.done_today(config.dir, NOW.date()) == 2
    assert service.round()["cards"] == []


def test_an_unfinished_round_waits_then_pushes_and_the_button_pushes_now(setup):
    repo, _config, sync, service, pushes = setup
    a = _note(repo, "a")
    _note(repo, "b")
    service.grade(a, "fuzzy")
    assert service._flush_timer.isActive() and service._flush_timer.interval() == ReviewService.FLUSH_DELAY_MS
    assert service.flush(manual=True) == "started" and _wait(lambda: pushes)
    assert pushes[0][1] is True and not service._flush_timer.isActive()
    assert service.flush() == "empty"


def test_a_failed_push_keeps_the_pending_notes_for_next_time(setup):
    repo, config, _sync, _service, _pushes = setup
    failing = _Sync(ok=False)
    service = ReviewService(config, spawn=lambda job: job(), now=lambda: NOW, token=lambda: "", sync=failing, head=lambda _r: "")
    a = _note(repo, "a")
    service.grade(a, "remember")
    assert _wait(lambda: service.sync_state == "failed")
    assert service.pending() == [a] and "fetch first" in service.sync_error
    restarted = ReviewService(config, spawn=lambda job: job(), now=lambda: NOW, token=lambda: "", sync=_Sync(), head=lambda _r: "x")
    assert restarted.pending() == [a], "重启后还记得没推的那条"
    assert restarted.flush() == "started" and _wait(lambda: restarted.pending() == [])
    service.stop()
    restarted.stop()


def test_grading_refuses_unknown_answers_missing_notes_and_waits_for_a_busy_lock(setup):
    repo, config, _sync, _service, _pushes = setup
    a = _note(repo, "a")
    lock = threading.Lock()
    service = ReviewService(config, lock=lock, spawn=lambda job: job(), now=lambda: NOW, sync=_Sync())
    service.LOCK_WAIT_S = 0.05
    assert service.grade(a, "maybe") == {"state": "failed"}
    assert service.grade("9-Learning/Notes/missing.md", "remember") == {"state": "missing"}
    with lock:
        assert service.grade(a, "remember") == {"state": "busy"}
    assert "interval: 1, count: 0" in (repo / a).read_text(encoding="utf-8"), "等不到锁：一个字没改"
    service.stop()


def test_stop_drops_a_late_push_result(setup):
    repo, config, _sync, _service, _pushes = setup
    jobs, finished = [], []
    service = ReviewService(config, spawn=jobs.append, now=lambda: NOW, sync=_Sync(), head=lambda _r: "x")
    service.finished.connect(lambda r, m: finished.append(r))
    _note(repo, "a")
    _note(repo, "b")
    service.grade("9-Learning/Notes/a.md", "remember")
    assert service.flush() == "started" and service.flush() == "busy"
    service.stop()
    jobs[0]()
    _wait(lambda: False, budget=0.2)
    assert finished == [] and service.pending() == ["9-Learning/Notes/a.md"]


# ───────────────────────── 提醒 ─────────────────────────

def _reminding(config, now, *, active=True, seed=3):
    import random

    service = ReviewService(config, spawn=lambda job: job(), now=lambda: now, sync=_Sync(), head=lambda _r: "x",
                            active=lambda: active, rng=random.Random(seed))
    said = []
    service.remind.connect(lambda kind, payload: said.append((kind, payload)))
    return service, said


def test_the_daily_reminder_fires_once_with_the_count(setup):
    repo, config, _sync, _service, _pushes = setup
    _note(repo, "a")
    _note(repo, "b")
    early, said = _reminding(config, dt.datetime(2026, 11, 26, 8, 0))
    assert early.check_reminders() == "" and said == []
    service, said = _reminding(config, dt.datetime(2026, 11, 26, 9, 30))
    assert service.check_reminders() == "daily" and said == [("daily", {"count": 2})]
    assert service.check_reminders() in ("", "random") and [kind for kind, _ in said].count("daily") == 1, "一天一次"
    for one in (early, service):
        one.stop()


def test_the_random_reminder_puts_its_note_first_on_the_page_until_it_is_graded(setup):
    repo, config, _sync, _service, _pushes = setup
    import pet.capture_organize as co
    config.set(co.CONFIG_KEY, {"review_enabled": False})
    later = _note(repo, "later", review="{next: 2026-12-20, interval: 30, count: 3, lapses: 0}", title="Later idea")
    service, said = _reminding(config, dt.datetime(2026, 11, 26, 20, 59))
    assert service.check_reminders() == "random", "今天的时刻在 10–20 点之间，20:59 一定过了"
    slot = cr.load_state(config.dir)["random_at"]
    assert "10:00" <= slot < "20:00"
    assert said == [("random", {"path": later, "title": "Later idea"})] and service.check_reminders() == ""
    assert service.round()["cards"] == [], "没点「看看」之前不插队"
    service.spotlight(later)
    first = service.round()["cards"][0]
    assert first.path == later and service.round()["due"] == 0
    service.grade(later, "remember")
    assert service.round()["cards"] == [] and cr.load_state(config.dir)["spotlight"] == ""
    away, said_away = _reminding(config, dt.datetime(2026, 11, 27, 20, 59), active=False)
    assert away.check_reminders() == "" and said_away == [], "人不在电脑前：不冒"
    for one in (service, away):
        one.stop()


def test_the_round_size_follows_the_setting(setup):
    repo, config, _sync, service, _pushes = setup
    import pet.capture_organize as co
    for name in "abcdefg":
        _note(repo, name)
    assert len(service.round()["cards"]) == 5
    config.set(co.CONFIG_KEY, {"review_batch": 2})
    assert len(service.round()["cards"]) == 2 and service.round()["due"] == 7
