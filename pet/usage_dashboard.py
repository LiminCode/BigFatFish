# -*- coding: utf-8 -*-
"""近 7 天仪表盘：点灵动岛上的「今日用量」数字，在岛的**上方**弹出四张 Metro 磁贴。

四张磁贴（每张一个大数字 = 今天，下面 7 根柱子 = 最近 7 天）：

- **用量**：每天的 Claude Code token（``claude_week``，和岛上「今日」同一口径、同一个数）；
- **发出的消息**：每天在所有 Claude Code 会话里发出去的消息数（``claude_week``）；
- **上下班**：每天第一次 / 最后一次动键鼠的时刻，6 点换天（``activity_log``）；
- **专注**：每天真在用电脑的时长——有输入的分钟加上不超过 5 分钟的空档（``activity_log``）。

``build_tiles`` 是纯函数（数据 → 每张磁贴的文字与柱子），界面在 ``usage_dashboard_ui``。
``UsageDashboard`` 是 GUI 线程上的控制器：读对话记录放 daemon 线程（首次约 0.3 秒，之后
几毫秒），结果经信号排队回来；活动记录在 GUI 线程的内存里，直接读。只在仪表盘打开时
读，开着时每分钟刷新一次，关着零开销。
"""

from __future__ import annotations

import datetime as dt
import logging
import math
import threading
import time
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QObject, QRect, Signal

from . import activity_log, claude_week
from .activity_log import DaySummary
from .claude_usage import format_tokens
from .claude_week import DayUsage
from .i18n import t

log = logging.getLogger(__name__)

#: 四张磁贴的底色（Windows Phone 的钴蓝 / 翡翠绿 / 品红 / 紫罗兰）。白字对比度都 ≥ 4.5:1
#: （翡翠绿 4.53 最紧，所以磁贴上的字一律纯白、不降透明度）。
TILE_COLORS = {"tokens": "#0050ef", "prompts": "#008a00", "hours": "#d80073", "focus": "#6a00ff"}
GAP = 8                       # 窗口与岛之间的距离


@dataclass(frozen=True)
class Bar:
    """一根柱子：``value`` 是柱高（0 = 没有）；``low`` / ``high`` 只给「上下班」那种悬浮区间用。"""

    label: str
    tip: str
    value: float = 0.0
    low: float | None = None
    high: float | None = None
    today: bool = False


@dataclass(frozen=True)
class Tile:
    key: str
    title: str
    value: str
    sub: str
    bars: tuple[Bar, ...]
    kind: str = "bars"                        # "bars" 或 "ranges"
    axis: tuple[str, str] = ("", "")          # ranges：上沿 / 下沿的钟点
    span: tuple[float, float] = (0.0, 1.0)    # ranges：纵轴范围（从 6 点起的小时数）

    @property
    def color(self) -> str:
        return TILE_COLORS[self.key]


@dataclass(frozen=True)
class DashboardData:
    usage: list[DayUsage]
    activity: list[DaySummary]
    recording_since: dt.date | None = None


# ---------------------------------------------------------------- 文字

def _clock(when: float) -> str:
    return dt.datetime.fromtimestamp(when).strftime("%H:%M")


def _hour_clock(hours: float) -> str:
    """从 6 点起的小时数 → 钟点（25.5 → 07:30）。"""
    minutes = int(round(hours * 60)) + activity_log.DAY_START_HOUR * 60
    return f"{(minutes // 60) % 24:02d}:{minutes % 60:02d}"


def format_duration(minutes: int) -> str:
    minutes = max(0, int(minutes))
    if minutes < 60:
        return t("dashboard.duration.minutes", m=minutes)
    return t("dashboard.duration", h=minutes // 60, m=minutes % 60)


def _weekday(day: dt.date) -> str:
    names = t("dashboard.weekdays").split(",")
    return names[day.weekday()] if len(names) == 7 else day.strftime("%a")


def _date(day: dt.date) -> str:
    return f"{day.month}/{day.day} {_weekday(day)}"


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


# ---------------------------------------------------------------- 磁贴

def build_tiles(data: DashboardData) -> list[Tile]:
    """数据 → 四张磁贴。今天总在最右边；没有记录的天柱子为空、提示写「没有记录」。"""
    return [_tokens_tile(data.usage), _prompts_tile(data.usage),
            _hours_tile(data.activity), _focus_tile(data.activity)]


def _count_bars(days: list[DayUsage], value: Callable[[DayUsage], int], tip: Callable[[DayUsage], str]):
    last = len(days) - 1
    return tuple(Bar(_weekday(d.day), tip(d), float(value(d)), today=i == last) for i, d in enumerate(days))


def _tokens_tile(days: list[DayUsage]) -> Tile:
    total = sum(d.tokens for d in days)
    today = days[-1].tokens if days else 0
    return Tile("tokens", t("dashboard.tokens"), format_tokens(today),
                t("dashboard.week_sub", total=format_tokens(total), avg=format_tokens(total // max(1, len(days)))),
                _count_bars(days, lambda d: d.tokens,
                            lambda d: t("dashboard.tip.tokens", date=_date(d.day), tokens=format_tokens(d.tokens),
                                        output=format_tokens(d.output))))


def _prompts_tile(days: list[DayUsage]) -> Tile:
    total = sum(d.prompts for d in days)
    avg = total / max(1, len(days))
    return Tile("prompts", t("dashboard.prompts"), str(days[-1].prompts if days else 0),
                t("dashboard.week_sub", total=total, avg=f"{avg:.1f}"),
                _count_bars(days, lambda d: d.prompts,
                            lambda d: t("dashboard.tip.prompts", date=_date(d.day), n=d.prompts)))


def _hours_since_origin(summary: DaySummary) -> tuple[float, float]:
    origin = activity_log.day_origin(summary.day)
    return (summary.start - origin) / 3600.0, (summary.end - origin) / 3600.0


def _hours_tile(days: list[DaySummary]) -> Tile:
    recorded = [d for d in days if d.recorded]
    spans = [_hours_since_origin(d) for d in recorded]
    if spans:
        top = math.floor(min(low for low, _high in spans))
        bottom = max(top + 1, math.ceil(max(high for _low, high in spans)))
    else:
        top, bottom = 3, 12                             # 没记录：画一根空轴（09:00–18:00）
    bars = []
    for i, summary in enumerate(days):
        today = i == len(days) - 1
        if summary.recorded:
            low, high = _hours_since_origin(summary)
            tip = t("dashboard.tip.hours", date=_date(summary.day), start=_clock(summary.start), end=_clock(summary.end))
            bars.append(Bar(_weekday(summary.day), tip, high - low, low=low, high=high, today=today))
        else:
            bars.append(Bar(_weekday(summary.day), t("dashboard.tip.empty", date=_date(summary.day)), today=today))
    latest = days[-1] if days else None
    value = (f"{_clock(latest.start)}–{_clock(latest.end)}" if latest is not None and latest.recorded
             else t("dashboard.none"))
    sub = (t("dashboard.hours.sub", start=_hour_clock(_average([low for low, _ in spans])),
             end=_hour_clock(_average([high for _, high in spans]))) if spans else t("dashboard.not_recorded"))
    return Tile("hours", t("dashboard.hours"), value, sub, tuple(bars), kind="ranges",
                axis=(_hour_clock(top), _hour_clock(bottom)), span=(float(top), float(bottom)))


def _focus_tile(days: list[DaySummary]) -> Tile:
    recorded = [d.focus_minutes for d in days if d.recorded]
    bars = tuple(
        Bar(_weekday(d.day),
            t("dashboard.tip.focus", date=_date(d.day), focus=format_duration(d.focus_minutes),
              active=format_duration(d.active_minutes)) if d.recorded else t("dashboard.tip.empty", date=_date(d.day)),
            float(d.focus_minutes), today=i == len(days) - 1)
        for i, d in enumerate(days))
    latest = days[-1] if days else None
    value = format_duration(latest.focus_minutes) if latest is not None and latest.recorded else t("dashboard.none")
    sub = (t("dashboard.focus.sub", avg=format_duration(round(_average(recorded))), best=format_duration(max(recorded)))
           if recorded else t("dashboard.not_recorded"))
    return Tile("focus", t("dashboard.focus"), value, sub, bars)


def footer_text(data: DashboardData) -> str:
    text = t("dashboard.footer", gap=activity_log.FOCUS_GAP_MIN)
    if data.recording_since is not None:
        first = data.activity[0].day if data.activity else None
        if first is None or data.recording_since > first:
            text += " " + t("dashboard.since", date=f"{data.recording_since.month}/{data.recording_since.day}")
    return text


# ---------------------------------------------------------------- 摆在哪

def place_above(anchor: QRect, size, available: QRect, gap: int = GAP) -> QRect:
    """窗口放在 ``anchor``（岛）正上方、水平居中；再夹回屏幕里。

    岛离屏幕顶边太近、上面放不下时，贴着顶边盖在岛上面——不放到岛下面（用户 2026-10-24：
    卡片是往下展开的，仪表盘要在上面）。
    """
    width, height = size.width(), size.height()
    x = anchor.center().x() - width // 2
    y = anchor.top() - gap - height
    x = max(available.left(), min(x, available.right() + 1 - width))
    y = max(available.top(), min(y, available.bottom() + 1 - height))
    return QRect(x, y, width, height)


# ---------------------------------------------------------------- 控制器

_meter: claude_week.WeekMeter | None = None


def _default_measure() -> list[DayUsage]:
    global _meter
    if _meter is None:
        _meter = claude_week.WeekMeter()
    return _meter.refresh()


def _spawn_thread(target: Callable[[], None]) -> None:
    threading.Thread(target=target, daemon=True, name="pet-usage-dashboard").start()


class UsageDashboard(QObject):
    """仪表盘的开 / 关 / 刷新。``activity`` 返回 ``ActivityLog``（没有记录器时返回 None）。"""

    _measured = Signal(int, object)          # worker 线程 → GUI 线程

    def __init__(self, config, *, activity: Callable[[], object] | None = None,
                 measure: Callable[[], list[DayUsage]] | None = None, spawn: Callable | None = None,
                 clock: Callable[[], float] = time.time, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self._activity = activity or (lambda: None)
        self._measure = measure or _default_measure
        self._spawn = spawn or _spawn_thread
        self._clock = clock
        self._busy = False
        self._generation = 0
        self._usage: list[DayUsage] | None = None
        self.window = None
        self._measured.connect(self._on_measured)

    def _ensure_window(self):
        if self.window is None:
            from .usage_dashboard_ui import UsageDashboardWindow

            self.window = UsageDashboardWindow()
            self.window.refresh_requested.connect(self.refresh)
        return self.window

    def is_open(self) -> bool:
        return self.window is not None and self.window.isVisible()

    def toggle(self, anchor: QRect, available: QRect) -> None:
        """点了岛上的数字：开着就关，关着就在岛的上方打开。"""
        if self.is_open():
            self.window.hide()
            return
        window = self._ensure_window()
        window.apply_theme(self._theme())
        self._render()
        window.adjustSize()
        window.setGeometry(place_above(anchor, window.sizeHint(), available))
        window.show()
        window.raise_()
        window.activateWindow()                 # 激活了才能「点别处就收起」
        self.refresh()

    def _theme(self) -> str:
        appearance = self.config.get("context_menu_appearance") if self.config is not None else None
        return str((appearance or {}).get("theme") or "system") if isinstance(appearance, dict) else "system"

    def refresh(self) -> None:
        """后台读一次对话记录（在途时不重复发起）；活动记录随结果一起重画。"""
        if self._busy:
            return
        self._busy = True
        self._generation += 1
        generation, measure = self._generation, self._measure

        def run() -> None:
            try:
                usage = measure()
            except Exception:  # noqa: BLE001 - 对话记录是 Claude Code 的内部格式，随时可能变
                log.debug("仪表盘：统计用量失败", exc_info=True)
                usage = None
            try:
                self._measured.emit(generation, usage)
            except RuntimeError:
                pass  # 应用正在退出：本对象已销毁

        try:
            self._spawn(run)
        except Exception:  # noqa: BLE001 - 起线程失败也要放开忙标志
            log.exception("仪表盘：启动统计线程失败")
            self._busy = False

    def _on_measured(self, generation: int, usage) -> None:
        if generation != self._generation:
            return
        self._busy = False
        if usage is not None:
            self._usage = list(usage)
        if self.window is not None:
            self._render()

    def data(self) -> DashboardData:
        now = self._clock()
        today = dt.datetime.fromtimestamp(now).date()
        usage = self._usage or [DayUsage(today - dt.timedelta(days=n)) for n in range(claude_week.DAYS - 1, -1, -1)]
        work_today = activity_log.work_day(now)
        work_days = [work_today - dt.timedelta(days=n) for n in range(claude_week.DAYS - 1, -1, -1)]
        log_ = self._activity()
        if log_ is None:
            return DashboardData(usage, [DaySummary(day) for day in work_days])
        return DashboardData(usage, [log_.summary(day) for day in work_days], recording_since=log_.first_day())

    def _render(self) -> None:
        data = self.data()
        self.window.set_content(build_tiles(data), footer_text(data), loading=self._usage is None)
