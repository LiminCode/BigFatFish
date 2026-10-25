# -*- coding: utf-8 -*-
"""近 7 天仪表盘：点灵动岛上的「今日用量」数字，在岛的上方弹出四张 Metro 磁贴。

钉住的行为：点数字（且只有显示用量时）才发请求；磁贴的大数字是今天、柱子是 7 天且今天在
最右；没有记录的天不装作是 0；窗口放在岛的上方、放不下就贴顶盖住岛（不放下面）；再点一次、按 Esc 都收起；
对话记录在后台线程读，开着时刷新，旧的在途结果作废。
"""

from __future__ import annotations

import datetime as dt
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from pet import activity_log
from pet.activity_log import ActivityLog, DaySummary
from pet.claude_week import DayUsage
from pet.config import Config
from pet.usage_dashboard import DashboardData, UsageDashboard, build_tiles, footer_text, place_above
from tests.test_island_info_slot import _island
from tests.test_island_personal import _release

app = QApplication.instance() or QApplication([])

TODAY = dt.date(2026, 10, 24)
WEEK = [TODAY - dt.timedelta(days=n) for n in range(6, -1, -1)]


def _at(day: dt.date, hour: int, minute: int = 0) -> float:
    return dt.datetime.combine(day, dt.time(hour, minute)).timestamp()


def _usage(tokens=(0, 0, 0, 0, 0, 1000, 2_380_000), prompts=(0, 1, 2, 3, 4, 5, 9)) -> list[DayUsage]:
    return [DayUsage(day, output=t, prompts=p) for day, t, p in zip(WEEK, tokens, prompts)]


def _activity() -> list[DaySummary]:
    days = [DaySummary(day) for day in WEEK]
    days[-2] = DaySummary(WEEK[-2], start=_at(WEEK[-2], 8, 30), end=_at(WEEK[-1], 1, 15),
                          active_minutes=300, focus_minutes=360)
    days[-1] = DaySummary(WEEK[-1], start=_at(WEEK[-1], 9, 12), end=_at(WEEK[-1], 21, 40),
                          active_minutes=250, focus_minutes=312)
    return days


# ---------------------------------------------------------------- 磁贴内容

def test_tiles_show_today_big_and_seven_bars_with_today_last():
    tokens, prompts, hours, focus = build_tiles(DashboardData(_usage(), _activity()))

    assert [tile.key for tile in (tokens, prompts, hours, focus)] == ["tokens", "prompts", "hours", "focus"]
    assert tokens.value == "2.38M" and prompts.value == "9"
    assert hours.value == "09:12–21:40" and focus.value == "5小时12分"
    for tile in (tokens, prompts, hours, focus):
        assert len(tile.bars) == 7 and tile.bars[-1].today and not any(b.today for b in tile.bars[:-1])
        assert tile.bars[-1].label == "六", "10/24 是星期六"
    assert prompts.sub == "7 天 24 · 日均 3.4"
    assert "10/24 六" in tokens.bars[-1].tip and "2.38M" in tokens.bars[-1].tip


def test_work_hours_are_floating_ranges_on_a_shared_clock_axis():
    hours = build_tiles(DashboardData(_usage(), _activity()))[2]

    assert hours.kind == "ranges"
    late = hours.bars[-2]
    assert (late.low, late.high) == (2.5, 19.25), "08:30 → 次日 01:15，从 6 点起算的小时数"
    assert hours.span == (2.0, 20.0) and hours.axis == ("08:00", "02:00"), "纵轴取整到整点，跨过零点照样画"
    assert hours.sub == "平均 08:51 上班 · 23:28 下班"
    assert hours.bars[0].low is None and "没有记录" in hours.bars[0].tip


def test_days_without_records_say_so_instead_of_zero():
    empty = [DaySummary(day) for day in WEEK]
    hours, focus = build_tiles(DashboardData(_usage(), empty))[2:]
    assert hours.value == focus.value == "—"
    assert hours.sub == focus.sub == "还没有记录"


def test_footer_says_since_when_activity_has_been_recorded():
    data = DashboardData(_usage(), _activity(), recording_since=WEEK[-2])
    assert "活动从 10/23 开始记录" in footer_text(data)
    full = DashboardData(_usage(), _activity(), recording_since=WEEK[0] - dt.timedelta(days=3))
    assert "开始记录" not in footer_text(full), "记满 7 天就不用再说"


# ---------------------------------------------------------------- 摆在哪

def test_dashboard_sits_above_the_island_never_below():
    screen = QRect(0, 0, 1920, 1040)
    size = QSize(500, 480)
    above = place_above(QRect(700, 900, 300, 44), size, screen)
    assert above.bottom() < 900 and abs(above.center().x() - 850) <= 2, "岛的正上方、水平居中"
    near_top = place_above(QRect(700, 190, 300, 44), size, screen)
    assert near_top.top() == screen.top(), "上面放不下：贴着屏幕顶边盖在岛上，不放到岛下面"
    edge = place_above(QRect(1800, 900, 100, 44), size, screen)
    assert edge.right() <= screen.right(), "夹回屏幕里"


# ---------------------------------------------------------------- 岛上的入口

def test_clicking_the_usage_number_requests_the_dashboard(tmp_path):
    island = _island(tmp_path, info_mode="usage_today")
    try:
        island.set_usage_info("今日 2.38M", "明细")
        requested = []
        island.usage_dashboard_requested.connect(lambda: requested.append(True))
        rect = island.usage_rect()
        _release(island, QPointF(rect.center().x(), rect.center().y()))
        assert requested == [True]
        assert island._mode != "expanded", "点数字不展开卡片"
        _release(island, QPointF(island._toolbar_left() - 2, 20))  # 数字右边（状态区）照旧
        assert requested == [True]
    finally:
        island.deleteLater()


def test_the_clock_is_not_a_dashboard_button(tmp_path):
    island = _island(tmp_path)
    try:
        assert island.usage_rect() is None
    finally:
        island.deleteLater()


# ---------------------------------------------------------------- 控制器

class Spawn:
    def __init__(self) -> None:
        self.jobs = []

    def __call__(self, job) -> None:
        self.jobs.append(job)

    def run(self) -> None:
        jobs, self.jobs = self.jobs, []
        for job in jobs:
            job()
        app.processEvents()


def _dashboard(tmp_path, log=None):
    spawn = Spawn()
    calls = []

    def measure():
        calls.append(True)
        return _usage()

    dashboard = UsageDashboard(Config(base=tmp_path), activity=lambda: log, measure=measure, spawn=spawn,
                               clock=lambda: _at(TODAY, 15))
    return dashboard, spawn, calls


def test_toggle_opens_above_the_island_reads_in_the_background_and_closes(tmp_path):
    log = ActivityLog(tmp_path / "activity.json")
    log.mark(_at(TODAY, 9, 12))
    dashboard, spawn, calls = _dashboard(tmp_path, log)
    island = QRect(800, 700, 300, 44)
    try:
        dashboard.toggle(island, QRect(0, 0, 1920, 1040))
        window = dashboard.window
        assert window.isVisible() and window.geometry().bottom() < island.top()
        assert window.status_label.text() == "正在读对话记录…", "还没读完就先说在读"
        assert window.tiles[0].tile.value == "0"

        spawn.run()
        assert calls == [True]
        assert window.status_label.text() == ""
        assert window.tiles[0].tile.value == "2.38M"
        assert window.tiles[2].tile.value == "09:12–09:13"

        dashboard.toggle(island, QRect(0, 0, 1920, 1040))
        assert not window.isVisible(), "再点一次数字就收起"
    finally:
        if dashboard.window is not None:
            dashboard.window.deleteLater()
        app.processEvents()


def test_escape_closes_and_stale_results_are_dropped(tmp_path):
    dashboard, spawn, _calls = _dashboard(tmp_path)
    try:
        dashboard.toggle(QRect(800, 700, 300, 44), QRect(0, 0, 1920, 1040))
        stale = spawn.jobs[0]
        dashboard._busy = False
        dashboard.refresh()                               # 换代：前一次在途的结果作废
        stale()
        app.processEvents()
        assert dashboard._usage is None and dashboard._busy is True
        spawn.run()
        assert dashboard._usage is not None

        window = dashboard.window
        window.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        assert not window.isVisible()
    finally:
        if dashboard.window is not None:
            dashboard.window.deleteLater()
        app.processEvents()


def test_without_a_tracker_activity_tiles_are_empty(tmp_path):
    dashboard, _spawn, _calls = _dashboard(tmp_path, None)
    data = dashboard.data()
    assert [d.day for d in data.activity][-1] == activity_log.work_day(_at(TODAY, 15))
    assert not any(d.recorded for d in data.activity) and data.recording_since is None


def test_switching_theme_before_the_first_show_takes_effect():
    from pet.usage_dashboard_ui import UsageDashboardWindow

    window = UsageDashboardWindow()
    try:
        window.apply_theme("dark")
        window.apply_theme("light")
        window.show()
        app.processEvents()
        assert window.grab().toImage().pixelColor(4, 4).name() == window.colors["page"] == "#f2f2f2"
    finally:
        window.deleteLater()
        app.processEvents()


def test_the_island_does_not_jump_back_over_the_open_dashboard(tmp_path):
    """仪表盘贴顶盖在岛上时，岛不能因为「本进程窗口被激活」/ 心跳把自己顶回最上、挡住磁贴（实机截图）。"""
    from pet.usage_dashboard_ui import UsageDashboardWindow

    island = _island(tmp_path, info_mode="usage_today")
    window = UsageDashboardWindow()
    try:
        assert island.reassert_topmost() is True
        window.show()
        app.processEvents()
        assert island.reassert_topmost() is False
        window.hide()
        assert island.reassert_topmost() is True, "收起之后照常保活"
    finally:
        window.deleteLater()
        island.deleteLater()
        app.processEvents()
