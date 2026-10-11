# -*- coding: utf-8 -*-
"""ClaudeUsageMonitor：定时在后台线程量一次今日用量，结果回 GUI 线程。

量用量要读 ``~/.claude``：这里一律注入替身；线程用同步 spawn 顶替，只有一条用例走
真线程。
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from pet.claude_usage import UsageTotals
from pet.claude_usage_monitor import ClaudeUsageMonitor

app = QApplication.instance() or QApplication([])


class _Measure:
    def __init__(self, totals=None) -> None:
        self.totals = totals if totals is not None else UsageTotals(output=1500)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if isinstance(self.totals, Exception):
            raise self.totals
        return self.totals


def _monitor(measure=None, *, spawn=None):
    monitor = ClaudeUsageMonitor(measure=measure or _Measure(), spawn=spawn or (lambda fn: fn()))
    monitor.seen = []
    monitor.usage_changed.connect(lambda headline, detail: monitor.seen.append((headline, detail)))
    return monitor


def test_idle_until_switched_on():
    measure = _Measure()
    monitor = _monitor(measure)
    assert measure.calls == 0 and not monitor._timer.isActive()


def test_switching_on_measures_at_once_and_then_every_minute():
    measure = _Measure(UsageTotals(output=2_380_000))
    monitor = _monitor(measure)

    monitor.set_active(True)

    assert monitor.seen == [("今日 2.38M", UsageTotals(output=2_380_000).detail)]
    assert monitor._timer.isActive() and monitor._timer.interval() == monitor.INTERVAL_MS == 60_000
    monitor._timer.timeout.emit()
    assert measure.calls == 2
    monitor.set_active(True)
    assert measure.calls == 2, "已经开着：不重复起"


def test_unchanged_numbers_are_not_re_announced():
    measure = _Measure()
    monitor = _monitor(measure)
    monitor.set_active(True)
    monitor._timer.timeout.emit()
    assert len(monitor.seen) == 1
    measure.totals = UsageTotals(output=9000)
    monitor._timer.timeout.emit()
    assert [headline for headline, _ in monitor.seen] == ["今日 1.5K", "今日 9.0K"]


def test_switching_off_stops_the_clock_and_drops_results_in_flight():
    pending = []
    measure = _Measure()
    monitor = _monitor(measure, spawn=pending.append)
    monitor.set_active(True)
    monitor.set_active(False)
    pending.pop()()
    assert monitor.seen == [] and not monitor._timer.isActive()

    monitor.set_active(True)
    pending.pop()()
    assert len(monitor.seen) == 1, "再打开要重新报一次（哪怕数字没变）"


def test_a_measurement_in_flight_is_not_doubled():
    pending = []
    measure = _Measure()
    monitor = _monitor(measure, spawn=pending.append)
    monitor.set_active(True)
    monitor._timer.timeout.emit()
    assert len(pending) == 1
    pending.pop()()
    monitor._timer.timeout.emit()
    assert len(pending) == 1


def test_a_crashing_measurement_is_survivable():
    measure = _Measure(RuntimeError("内部格式变了"))
    monitor = _monitor(measure)
    monitor.set_active(True)
    assert monitor.seen == []
    measure.totals = UsageTotals(output=10)
    monitor._timer.timeout.emit()
    assert [headline for headline, _ in monitor.seen] == ["今日 10"], "失败后忙标志要放开"


def test_real_worker_thread_delivers_on_the_gui_thread():
    measure_threads, slot_threads = [], []

    def measure():
        measure_threads.append(threading.current_thread())
        return UsageTotals(output=42)

    monitor = ClaudeUsageMonitor(measure=measure)
    loop = QEventLoop()

    def on_change(_headline, _detail):
        slot_threads.append(threading.current_thread())
        loop.quit()

    monitor.usage_changed.connect(on_change)
    monitor.set_active(True)
    QTimer.singleShot(30_000, loop.quit)        # 宽预算兜底：正常由事件唤醒
    loop.exec()
    monitor.set_active(False)

    assert measure_threads and measure_threads[0] is not threading.main_thread()
    assert slot_threads == [threading.main_thread()]
