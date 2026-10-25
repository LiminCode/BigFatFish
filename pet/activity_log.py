# -*- coding: utf-8 -*-
"""人在电脑前的记录：哪几分钟动过键鼠（纯逻辑 + 本机探测，零 Qt）。

仪表盘里「上班 / 下班时间」和「专注时间」的数据来源。Windows 系统日志给不出这些：这台
机器从不睡眠（没有 Kernel-Power 42/107），锁屏审计（Security 4800/4801）默认没开，
2026-10-24 实测一周里只有 3 次开关机。所以由肥鱼自己记：``activity_tracker`` 每半分钟
问一次 ``GetLastInputInfo``，把「最后一次键鼠输入」所在的那一分钟记下来。

口径：

- **一天从早上 6 点算起**（``DAY_START_HOUR``）：凌晨 1 点还在用电脑算前一天的晚上。
- **上班** = 这一天第一分钟有输入的时刻；**下班** = 最后一分钟有输入的那一分钟结束时。
- **专注** = 有输入的分钟，加上两段输入之间不超过 ``FOCUS_GAP_MIN`` 分钟的空档（看文档、
  想事情时手不动）。更长的空档、锁屏、睡眠、肥鱼没开着的时间都不算。

存成一个小 JSON（``{"version": 1, "days": {"2026-10-24": [[起, 止), ...]}}``，分钟数从当天
6 点起算、左闭右开），只留最近 ``KEEP_DAYS`` 天。
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

DAY_START_HOUR = 6
FOCUS_GAP_MIN = 5
KEEP_DAYS = 14
_MAX_MINUTE = 25 * 60          # 夏令时那天一天可能有 25 小时


def work_day(when: float) -> dt.date:
    """``when`` 属于哪一天（早上 6 点换天，本机时区）。"""
    return (dt.datetime.fromtimestamp(when) - dt.timedelta(hours=DAY_START_HOUR)).date()


def day_origin(day: dt.date) -> float:
    """这一天从哪一刻算起（当天早上 6 点）。"""
    return dt.datetime.combine(day, dt.time(DAY_START_HOUR)).timestamp()


@dataclass(frozen=True)
class DaySummary:
    """一天的活动：没有记录时 ``start`` / ``end`` 是 None、专注是 0。"""

    day: dt.date
    start: float | None = None
    end: float | None = None
    active_minutes: int = 0
    focus_minutes: int = 0

    @property
    def recorded(self) -> bool:
        return self.start is not None


def _merge(spans: list[list[int]], minute: int) -> tuple[list[list[int]], bool]:
    """把一分钟并进有序的区间表；返回 (新表, 是否新记了一分钟)。"""
    for span in spans:
        if span[0] <= minute < span[1]:
            return spans, False
    spans = sorted(spans + [[minute, minute + 1]])
    merged: list[list[int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged, True


def summarize(day: dt.date, spans: list[list[int]]) -> DaySummary:
    if not spans:
        return DaySummary(day)
    origin = day_origin(day)
    active = sum(end - start for start, end in spans)
    gaps = sum(gap for gap in (spans[i + 1][0] - spans[i][1] for i in range(len(spans) - 1))
               if gap <= FOCUS_GAP_MIN)
    return DaySummary(day, start=origin + spans[0][0] * 60, end=origin + spans[-1][1] * 60,
                      active_minutes=active, focus_minutes=active + gaps)


class ActivityLog:
    """按天记「哪几分钟有输入」。不是线程安全的：只在 GUI 线程上用。"""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._days: dict[str, list[list[int]]] = {}
        self.dirty = False
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        days = data.get("days") if isinstance(data, dict) else None
        if not isinstance(days, dict):
            return
        for key, spans in days.items():
            try:
                dt.date.fromisoformat(str(key))
            except ValueError:
                continue
            clean = []
            for span in spans if isinstance(spans, list) else []:
                try:
                    start, end = int(span[0]), int(span[1])
                except (TypeError, ValueError, IndexError, KeyError):
                    continue
                if 0 <= start < end <= _MAX_MINUTE:
                    clean.append([start, end])
            minutes: list[list[int]] = []
            for start, end in sorted(clean):          # 坏文件里可能有重叠：重新合并一遍
                if minutes and start <= minutes[-1][1]:
                    minutes[-1][1] = max(minutes[-1][1], end)
                else:
                    minutes.append([start, end])
            if minutes:
                self._days[str(key)] = minutes

    def mark(self, when: float) -> bool:
        """``when`` 这一刻有过输入；返回是不是新记了一分钟。"""
        day = work_day(when)
        minute = int((when - day_origin(day)) // 60)
        if not 0 <= minute < _MAX_MINUTE:
            return False
        key = day.isoformat()
        spans, added = _merge(self._days.get(key, []), minute)
        if added:
            self._days[key] = spans
            self.dirty = True
        return added

    def summary(self, day: dt.date) -> DaySummary:
        return summarize(day, self._days.get(day.isoformat(), []))

    def first_day(self) -> dt.date | None:
        """最早有记录的那天（仪表盘说「从哪天开始记的」）。"""
        return dt.date.fromisoformat(min(self._days)) if self._days else None

    def save(self, today: dt.date | None = None) -> None:
        """写回磁盘（先写临时文件再替换）；顺手丢掉 ``KEEP_DAYS`` 天以前的。"""
        if today is not None:
            floor = (today - dt.timedelta(days=KEEP_DAYS - 1)).isoformat()
            for key in [key for key in self._days if key < floor]:
                del self._days[key]
        payload = json.dumps({"version": 1, "days": self._days}, separators=(",", ":"))
        temp = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text(payload, encoding="utf-8")
            os.replace(temp, self.path)
            self.dirty = False
        except OSError:
            log.warning("活动记录：写入 %s 失败", self.path, exc_info=True)


# ---------------------------------------------------------------- 本机探测

def last_input_age() -> float | None:
    """距最后一次键鼠输入多少秒；锁屏时、非 Windows、探测失败返回 None（这一刻不记）。"""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        from .slack_watch import input_desktop_name

        if input_desktop_name().lower() != "default":
            return None                                    # 锁屏 / 安全桌面

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint32)]

        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        ticks = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
        return ((ticks - info.dwTime) & 0xFFFFFFFF) / 1000.0  # 两个 32 位毫秒数：开机 49.7 天会回绕
    except Exception:  # noqa: BLE001 - 探测本身出错就这一刻不记
        return None
