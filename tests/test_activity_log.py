# -*- coding: utf-8 -*-
"""人在电脑前的记录：仪表盘「上班 / 下班」「专注时间」的口径。

一天从早上 6 点算起；上班 = 第一分钟有输入，下班 = 最后一分钟有输入的那一分钟结束；
专注 = 有输入的分钟 + 两段之间不超过 5 分钟的空档。时间都按本机时区构造。
"""

from __future__ import annotations

import datetime as dt
import json

from PySide6.QtCore import QCoreApplication

from pet import activity_log
from pet.activity_log import ActivityLog, work_day
from pet.activity_tracker import ActivityTracker

app = QCoreApplication.instance() or QCoreApplication([])

DAY = dt.date(2026, 10, 20)


def _at(hour: int, minute: int = 0, second: int = 0, *, day: dt.date = DAY) -> float:
    return dt.datetime.combine(day, dt.time(hour, minute, second)).timestamp()


def _next(hour: int, minute: int = 0) -> float:
    return _at(hour, minute, day=DAY + dt.timedelta(days=1))


# ---------------------------------------------------------------- 换天

def test_day_turns_over_at_six_in_the_morning():
    assert work_day(_at(6, 0)) == DAY
    assert work_day(_at(23, 59)) == DAY
    assert work_day(_next(1, 30)) == DAY, "凌晨 1 点半还算前一天的晚上"
    assert work_day(_next(5, 59)) == DAY
    assert work_day(_next(6, 0)) == DAY + dt.timedelta(days=1)


# ---------------------------------------------------------------- 上下班与专注

def test_start_end_and_focus_with_short_gaps_filled(tmp_path):
    log = ActivityLog(tmp_path / "a.json")
    for minute in range(10):                     # 09:00–09:10 一直在动
        log.mark(_at(9, minute, 20))
    log.mark(_at(9, 14, 5))                      # 隔 4 分钟（看文档）：算专注
    for minute in range(40, 45):                 # 隔 25 分钟（走开了）：不算
        log.mark(_at(9, minute))
    log.mark(_next(1, 2))                    # 凌晨 1 点还在：下班时间算到 01:03

    summary = log.summary(DAY)

    assert summary.start == _at(9, 0)
    assert summary.end == _next(1, 3)
    assert summary.active_minutes == 10 + 1 + 5 + 1
    assert summary.focus_minutes == 10 + 4 + 1 + 5 + 1


def test_marking_the_same_minute_twice_is_idempotent(tmp_path):
    log = ActivityLog(tmp_path / "a.json")
    assert log.mark(_at(9, 0, 10)) is True
    log.dirty = False
    assert log.mark(_at(9, 0, 50)) is False
    assert log.dirty is False, "没有新分钟就不用落盘"
    assert log.summary(DAY).active_minutes == 1


def test_a_day_without_records_is_empty(tmp_path):
    summary = ActivityLog(tmp_path / "a.json").summary(DAY)
    assert not summary.recorded and summary.start is None and summary.focus_minutes == 0


# ---------------------------------------------------------------- 落盘

def test_round_trips_through_disk_and_drops_old_days(tmp_path):
    path = tmp_path / "sub" / "activity.json"
    log = ActivityLog(path)
    old = DAY - dt.timedelta(days=activity_log.KEEP_DAYS)
    log.mark(_at(10, 0, day=old))
    log.mark(_at(9, 0))
    log.mark(_at(9, 1))
    log.save(today=DAY)

    again = ActivityLog(path)
    assert again.summary(DAY).active_minutes == 2
    assert again.summary(old).recorded is False, "只留最近 KEEP_DAYS 天"
    assert again.first_day() == DAY
    assert not path.with_name("activity.json.tmp").exists()


def test_corrupt_or_foreign_files_are_ignored(tmp_path):
    path = tmp_path / "activity.json"
    path.write_text("{not json", encoding="utf-8")
    assert ActivityLog(path).first_day() is None
    path.write_text(json.dumps({"days": {"2026-10-20": [[5, 3], [1, 4], [2, 6], "x"],
                                         "bogus": [[1, 2]]}}), encoding="utf-8")
    log = ActivityLog(path)
    assert log.summary(DAY).active_minutes == 5, "重叠的区间合并，倒着的和坏的丢掉"
    assert log.first_day() == DAY


# ---------------------------------------------------------------- 定时采样

class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_tracker_marks_the_minute_of_the_last_input_and_throttles_saves(tmp_path):
    clock = Clock(_at(9, 0, 30))
    ages = iter([5.0, None, 700.0, 1.0])
    tracker = ActivityTracker(tmp_path, probe=lambda: next(ages), clock=clock)
    path = tmp_path / "activity.json"

    tracker.sample()                         # 5 秒前动过 → 09:00 这一分钟
    clock.now = _at(9, 0, 50)
    tracker.sample()                         # 锁屏：不记
    clock.now = _at(9, 1, 10)
    tracker.sample()                         # 700 秒前（太久，醒来时不可信）：不记
    assert not path.exists(), "不到 1 分钟不落盘"
    clock.now = _at(9, 1, 40)
    tracker.sample()                         # 09:01:39 → 09:01；距上次落盘已超 1 分钟
    assert path.exists()

    assert tracker.log.summary(DAY).active_minutes == 2
    tracker.stop()
    assert ActivityLog(path).summary(DAY).start == _at(9, 0)
