# -*- coding: utf-8 -*-
"""定时记下「人在电脑前」（GUI 线程上的 QObject）：仪表盘上下班 / 专注时间的数据来源。

每 ``INTERVAL_MS`` 问一次距最后一次键鼠输入多少秒（``activity_log.last_input_age``，
一次 ``OpenInputDesktop`` + ``GetLastInputInfo``，微秒级），把那次输入所在的一分钟记进
``ActivityLog``。同一分钟重复记是幂等的，所以半分钟一次足够不漏分钟。睡眠时定时器不
走、锁屏时探测返回 None，这两段自然不算。

落盘节流：有新分钟时最多每 ``SAVE_EVERY_S`` 写一次（几 KB），``stop()``（退出收口）再
写一次；崩溃最多丢几分钟。只在 Windows 上启动（别的平台探测恒为 None）。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QTimer

from . import activity_log

FILE_NAME = "activity.json"


class ActivityTracker(QObject):
    INTERVAL_MS = 30_000
    SAVE_EVERY_S = 300.0
    #: 最后一次输入比这更早就不记（刚从睡眠醒来时滴答数的算术不可信）
    MAX_AGE_S = 600.0

    def __init__(self, folder: Path, *, probe: Callable[[], float | None] = activity_log.last_input_age,
                 clock: Callable[[], float] = time.time, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.log = activity_log.ActivityLog(Path(folder) / FILE_NAME)
        self._probe = probe
        self._clock = clock
        self._last_save = clock()
        self._timer = QTimer(self)
        self._timer.setInterval(self.INTERVAL_MS)
        self._timer.timeout.connect(self.sample)

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()
            self.sample()

    def stop(self) -> None:
        self._timer.stop()
        self.flush()

    def sample(self) -> None:
        """问一次、记一次；够时间了顺手落盘。"""
        now = self._clock()
        age = self._probe()
        if age is not None and 0 <= age <= self.MAX_AGE_S:
            self.log.mark(now - age)
        if self.log.dirty and now - self._last_save >= self.SAVE_EVERY_S:
            self.flush()

    def flush(self) -> None:
        now = self._clock()
        if self.log.dirty:
            self.log.save(today=activity_log.work_day(now))
        self._last_save = now
