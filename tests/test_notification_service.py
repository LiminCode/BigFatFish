# -*- coding: utf-8 -*-
"""通知中心的轮询服务：读到的合并进来、算未读、用户动作、配置开关。

读 / 跳 / 移除都用假函数，线程用同步的「立刻跑」替掉——测的是状态机，不是线程。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import notification_center as nc
from pet.config import Config
from pet.notification_service import NotificationService

app = QApplication.instance() or QApplication([])


def _notice(uid: int, created: float = 100.0, **over) -> nc.Notice:
    base = dict(uid=uid, app="Slack", app_id="91750D7E.Slack_x!Slack", title="#general", body=f"Ann: msg {uid}",
                created=created)
    base.update(over)
    return nc.Notice(**base)


class FakeCenter:
    def __init__(self):
        self.items: list[nc.Notice] = []
        self.logo_requests: list[set] = []
        self.known_sizes: list[int] = []
        self.activated: list[int] = []
        self.removed: list[int] = []
        self.result = "activated"

    def read(self, fragments, *, want_logos=(), known=()):
        want = set(want_logos)
        self.logo_requests.append(want)
        self.known_sizes.append(len(tuple(known)))
        return list(self.items), {app_id: b"PNG" for app_id in want}

    def activate(self, notice):
        self.activated.append(notice.uid)
        return self.result

    def remove(self, uid):
        self.removed.append(uid)
        return True


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(nc, "available", lambda: True)
    config = Config(tmp_path)
    center = FakeCenter()
    service = NotificationService(config, read=center.read, activate=center.activate, remove=center.remove,
                                  spawn=lambda target: target())
    events = []
    service.changed.connect(lambda notices: events.append(("changed", [n.uid for n in notices])))
    service.unread_changed.connect(lambda n: events.append(("unread", n)))
    service.activation_done.connect(lambda notice, result: events.append(("done", notice.uid, result)))
    service.apply_settings()          # 打开时立刻读了一轮（空）
    events.clear()
    center.logo_requests.clear()
    yield config, center, service, events
    service.stop()


def test_poll_merges_counts_unread_and_fetches_logos_once(world):
    config, center, service, events = world
    center.items = [_notice(1, 10), _notice(2, 20)]
    assert service.poll()
    assert service.unread_count == 2 and [n.uid for n in service.notices] == [2, 1]
    assert events == [("changed", [2, 1]), ("unread", 2)]
    assert service.logos == {"91750D7E.Slack_x!Slack": b"PNG"}
    assert center.logo_requests == [set(), {"91750D7E.Slack_x!Slack"}], "第一遍不要图标，缺哪个应用的再补一遍"
    events.clear()
    assert service.poll() and events == [], "没变化不发信号"
    assert center.logo_requests[-1] == set(), "图标已经有了就不再要"
    center.items = [_notice(2, 20), _notice(3, 30)]
    service.poll()
    assert [(n.uid, n.in_center) for n in service.notices] == [(3, True), (2, True), (1, False)]
    assert service.unread_count == 3
    assert center.known_sizes[-1] == 2, "上一轮的结果传给读取函数复用"


def test_mark_seen_activate_dismiss_and_clear(world):
    config, center, service, events = world
    center.items = [_notice(1, 10), _notice(2, 20)]
    service.poll()
    service.mark_all_seen()
    assert service.unread_count == 0 and events[-1] == ("unread", 0)
    assert service.activate(2) and center.activated == [2] and events[-1] == ("done", 2, "activated")
    assert not service.activate(99)
    assert service.dismiss(2) and center.removed == [2] and [n.uid for n in service.notices] == [1]
    center.items = [_notice(1, 10), _notice(2, 20)]
    service.poll()
    assert [n.uid for n in service.notices] == [1], "移除过的再读到也不回来"
    service.clear()
    assert service.notices == [] and center.removed == [2, 1]


def test_disabling_in_config_stops_polling_and_empties_the_island(world):
    config, center, service, events = world
    center.items = [_notice(1, 10)]
    service.poll()
    assert service.enabled and service._timer.isActive()
    config.set("notifications", {"enabled": False})
    service.apply_settings()
    assert not service.enabled and not service._timer.isActive()
    assert events[-2:] == [("changed", []), ("unread", 0)]
    assert not service.poll(), "关着时 poll 什么也不做"
    config.set("notifications", {"enabled": True, "poll_seconds": 7})
    service.apply_settings()
    assert service._timer.isActive() and service._timer.interval() == 7000
    assert [n.uid for n in service.notices] == [1], "重新打开立刻读了一轮"


def test_late_results_from_a_stopped_round_are_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(nc, "available", lambda: True)
    pending = []
    service = NotificationService(Config(tmp_path), read=lambda fragments, want_logos=(), known=(): ([_notice(1)], {}),
                                  spawn=pending.append)
    service.apply_settings()
    assert service.busy and len(pending) == 1
    service.stop()
    pending[0]()                       # 线程这时才回来
    assert service.notices == [] and not service.busy


def test_read_failures_do_not_poison_the_service(tmp_path, monkeypatch):
    monkeypatch.setattr(nc, "available", lambda: True)

    def read(fragments, want_logos=(), known=()):
        raise RuntimeError("winrt hiccup")

    service = NotificationService(Config(tmp_path), read=read, spawn=lambda target: target())
    service.apply_settings()
    assert not service.busy and service.notices == []
    assert service.poll(), "下一轮照常发起"


def test_unavailable_platform_means_never_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(nc, "available", lambda: False)
    service = NotificationService(Config(tmp_path), read=lambda *a, **k: ([], {}), spawn=lambda target: target())
    service.start()
    assert not service.enabled and not service._timer.isActive()


def test_arrived_reports_new_notices_oldest_first_but_not_the_startup_backlog(tmp_path, monkeypatch):
    monkeypatch.setattr(nc, "available", lambda: True)
    center = FakeCenter()
    center.items = [_notice(1, 10), _notice(2, 20)]          # 启动前就在通知中心里的
    service = NotificationService(Config(tmp_path), read=center.read, activate=center.activate,
                                  remove=center.remove, spawn=lambda target: target())
    arrived = []
    service.arrived.connect(lambda notices: arrived.append([n.uid for n in notices]))
    service.apply_settings()
    assert arrived == [] and service.unread_count == 2, "积压的照样进岛，但不弹"
    center.items = [_notice(1, 10), _notice(2, 20), _notice(4, 40), _notice(3, 30)]
    service.poll()
    assert arrived == [[3, 4]], "旧的先弹，最新的最后弹（落在最靠角的位置）"
    service.poll()
    assert arrived == [[3, 4]], "没新的不发"
    service.stop()


def test_arrived_baseline_resets_when_turned_off_and_on(world):
    config, center, service, events = world
    arrived = []
    service.arrived.connect(lambda notices: arrived.append([n.uid for n in notices]))
    center.items = [_notice(1, 10)]
    service.poll()
    assert arrived == [[1]]
    config.set(nc.CONFIG_KEY, {**nc.normalize(None), "enabled": False})
    service.apply_settings()
    center.items = [_notice(1, 10), _notice(2, 20)]
    config.set(nc.CONFIG_KEY, nc.normalize(None))
    service.apply_settings()
    assert arrived == [[1]], "重新打开时通知中心里已有的算积压"
