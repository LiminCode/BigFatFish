# -*- coding: utf-8 -*-
"""随手记复习的提醒：每天定点一批、白天随机一条，摆到宿主（岛 / 窗口）上；「开始复习」「看看」开复习页。

纪律：宿主和服务都是假的；样例文字中性。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet.review_ui import ALERT_ID, ReviewController

app = QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _chinese():
    i18n.set_language("zh")
    yield
    i18n.set_language("zh")


class _Host:
    def __init__(self):
        self.alerts, self.resolved, self.bubbles = [], [], []

    def show_alert(self, text, **kw):
        self.alerts.append((text, kw))

    def resolve_alert(self, alert_id):
        self.resolved.append(alert_id)

    def show_bubble(self, text, ms=0, **_):
        self.bubbles.append(text)


class _Service(QObject):
    remind = Signal(str, object)

    def __init__(self):
        super().__init__()
        self.spotlit = []

    def spotlight(self, path):
        self.spotlit.append(path)


def _controller(*, watched=False, opened=True):
    host, service, opens = _Host(), _Service(), []
    controller = ReviewController(host, service, open_report=lambda: opens.append(1) or opened, report_watched=lambda: watched)
    return host, service, opens, controller


def test_the_daily_reminder_is_an_alert_whose_button_opens_the_review_page():
    host, service, opens, _ctl = _controller()
    service.remind.emit("daily", {"count": 3})
    (text, kw), = host.alerts
    assert text == "今天有 3 条笔记该复习了" and kw["alert_id"] == ALERT_ID and kw["alert_type"] == "capture_review"
    labels = [label for label, _cb in kw["buttons"]]
    assert labels == ["开始复习", "稍后"]
    kw["buttons"][0][1]()
    assert opens == [1] and host.resolved == [ALERT_ID]
    kw["buttons"][1][1]()
    assert opens == [1] and host.resolved == [ALERT_ID, ALERT_ID]


def test_the_random_reminder_asks_about_one_note_and_puts_it_first():
    host, service, opens, _ctl = _controller()
    service.remind.emit("random", {"path": "9-Learning/Notes/x.md", "title": "Habit stacking"})
    (text, kw), = host.alerts
    assert text == "还记得「Habit stacking」讲了什么吗？" and [label for label, _ in kw["buttons"]] == ["看看", "跳过"]
    kw["buttons"][0][1]()
    assert service.spotlit == ["9-Learning/Notes/x.md"] and opens == [1]


def test_no_alert_while_the_review_page_is_open_and_a_bubble_when_it_cannot_open():
    host, service, _opens, _ctl = _controller(watched=True)
    service.remind.emit("daily", {"count": 2})
    assert host.alerts == []
    host, service, _opens, _ctl = _controller(opened=False)
    service.remind.emit("daily", {"count": 2})
    host.alerts[0][1]["buttons"][0][1]()
    assert host.bubbles == ["打不开复习页：本机服务没起来，看肥鱼日志"]
