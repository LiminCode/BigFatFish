# -*- coding: utf-8 -*-
"""随手记整理任务的 Qt 侧：什么时候跑（记下后攒一攒、启动后、每小时兜底、页面上点的）、线程、结果排回界面线程。

纪律：整理本身用同步的假函数（不调模型、不起 git）；真的事件循环；样例文字中性。
"""
from __future__ import annotations

import datetime as dt
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import capture_inbox as ci
from pet import capture_organize as co
from pet import personal_vault as pv
from pet.capture_service import CaptureOrganizer
from pet.config import Config

app = QApplication.instance() or QApplication([])
NOW = dt.datetime(2026, 11, 25, 10, 30)


class _Provider:
    model, effort, api_key, base_url, api_format = "claude-sonnet-5-5", "medium", "k", "https://api.anthropic.com", "auto"


class _Organize:
    def __init__(self, result=None):
        self.calls: list[tuple] = []
        self.result = result or co.Result(ok=True, state="ok", organized=1, notes=["9-Learning/Notes/2026-11-25 x.md"])

    def __call__(self, repo_dir, settings, provider, *, lock, token, now, exclude=()):
        self.calls.append((repo_dir, settings, provider, now, token(), set(exclude)))
        return self.result


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
    organize = _Organize()
    service = CaptureOrganizer(config, organize=organize, spawn=lambda job: job(), now=lambda: NOW, token=lambda: "tok",
                               provider=lambda: _Provider())
    events = []
    service.started.connect(lambda manual: events.append(("started", manual)))
    service.finished.connect(lambda result, manual: events.append(("finished", result, manual)))
    yield repo, config, organize, service, events
    service.stop()


def _capture(repo):
    return ci.write_capture(repo, "a passing thought", [], NOW, fallback="随手记")


def test_check_does_nothing_while_the_inbox_is_empty(setup):
    repo, _config, organize, service, events = setup
    assert service.check() is False
    assert organize.calls == [] and events == []


def test_check_runs_when_the_inbox_has_captures_and_reports_back(setup):
    repo, _config, organize, service, events = setup
    _capture(repo)
    assert service.pending_count() == 1
    assert service.check() is True
    assert _wait(lambda: any(e[0] == "finished" for e in events))
    assert events[0] == ("started", False)
    assert events[1][1].organized == 1 and events[1][2] is False
    assert organize.calls[0][0] == str(repo) and organize.calls[0][4] == "tok"
    assert isinstance(organize.calls[0][2], _Provider) and not service.busy


def test_turned_off_means_no_automatic_runs_but_the_button_still_works(setup):
    repo, config, organize, service, events = setup
    config.set(co.CONFIG_KEY, {"enabled": False})
    _capture(repo)
    assert service.check() is False and organize.calls == []
    assert service.organize_now() == "started"
    assert _wait(lambda: len(events) == 2) and events[0] == ("started", True)


def test_organize_now_says_why_it_did_not_start(setup):
    repo, config, organize, service, events = setup
    assert service.organize_now() == "empty"
    config.set(pv.CONFIG_KEY, {"repo_dir": str(repo.parent / "missing")})
    assert service.organize_now() == "missing"
    assert organize.calls == [] and events == []


def test_a_capture_waits_the_configured_minutes_then_runs_once(setup):
    repo, config, organize, service, events = setup
    config.set(co.CONFIG_KEY, {"delay_minutes": 0})
    _capture(repo)
    service.note_capture()
    service.note_capture()                       # 两条连着记：攒成一次
    assert _wait(lambda: len(events) == 2)
    assert _wait(lambda: False, budget=0.2) is False
    assert len(organize.calls) == 1


def test_a_capture_with_a_delay_arms_a_timer_instead_of_running(setup):
    repo, config, organize, service, events = setup
    config.set(co.CONFIG_KEY, {"delay_minutes": 3})
    _capture(repo)
    service.note_capture()
    assert service.capture_timer_ms() == 3 * 60_000
    app.processEvents()
    assert organize.calls == []
    config.set(co.CONFIG_KEY, {"enabled": False, "delay_minutes": 3})
    service.note_capture()
    assert service.capture_timer_ms() == 0


def test_busy_refuses_a_second_run_and_stop_drops_a_late_result(setup):
    repo, config, organize, _service, _events = setup
    jobs = []
    service = CaptureOrganizer(config, organize=organize, spawn=jobs.append, now=lambda: NOW, token=lambda: "",
                               provider=lambda: _Provider())
    finished = []
    service.finished.connect(lambda result, manual: finished.append(result))
    _capture(repo)
    assert service.organize_now() == "started" and service.busy
    assert service.organize_now() == "busy" and service.check() is False
    service.stop()
    jobs[0]()
    _wait(lambda: False, budget=0.2)
    assert finished == [] and not service.busy


def test_a_capture_that_could_not_be_organized_is_not_retried_every_hour(setup):
    """模型说整理不了的那条：记下来；自动的那几种不再拿它去问模型（不白花 token），点「现在整理」或改过那条才重试。"""
    repo, config, organize, service, events = setup
    held = _capture(repo)[0]
    organize.result = co.Result(ok=True, state="needs_you", left=1, skipped=1, held=[(held, "unreadable")])
    assert service.check() is True and _wait(lambda: len(events) == 2)
    assert co.load_held(config.dir)[held]["reason"] == "unreadable"
    assert service.check() is False and len(organize.calls) == 1, "没改过：每小时兜底不再跑"
    assert service.organize_now() == "started" and _wait(lambda: len(events) == 4)
    assert organize.calls[-1][5] == set(), "手点的：连认得的那条也重试"
    later = ci.write_capture(repo, "another one", [], NOW.replace(minute=40), fallback="随手记")[0]
    assert service.check() is True and _wait(lambda: len(events) == 6)
    assert organize.calls[-1][5] == {held}, "新来的照常整理，认得的那条不带"
    assert later


def test_no_provider_finishes_with_a_failure_instead_of_starting(setup):
    repo, config, organize, _service, _events = setup
    service = CaptureOrganizer(config, organize=organize, spawn=lambda job: job(), now=lambda: NOW, token=lambda: "",
                               provider=lambda: (_ for _ in ()).throw(RuntimeError("no chat module")))
    finished = []
    service.finished.connect(lambda result, manual: finished.append((result, manual)))
    _capture(repo)
    assert service.organize_now() == "failed"
    assert finished and not finished[0][0].ok and finished[0][0].state == "failed" and organize.calls == []
