# -*- coding: utf-8 -*-
"""灵动岛用量磁贴与近 7 天仪表盘的一组打磨（2026-11-05 用户反馈）：

- 用量那块磁贴比别的宽得多，同一套倾斜角（为 28px 方块调的）在它身上晃得太大 →
  角度按磁贴的长边反比缩小、透视视点等比拉远（``metro_tilt_params``），边缘位移不超过方块的；
- 信息槽不再写「今日」（悬停说明里仍有）；
- 两个账号的「Win / WSL」字样换成 Windows 四格窗 / Ubuntu 一环三点的记号（Metro 下；
  监视器多发一份结构化的分段，别的样式仍画文字）；
- 仪表盘窗口底色透明、每张磁贴底下一圈柔和阴影，页头 / 页脚文字带光晕保证在任何壁纸上可读；
- 岛可见期间 2 s 一轮看门狗：被别的置顶窗盖住才重新插回 topmost 带最上（真全屏 / 系统外壳
  在前台时不插）。

Qt offscreen 下没有真窗口 z 序，看门狗只测接线与判定；真机表现写在报告里。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QPointF, QRect
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from pet import claude_usage
from pet.claude_usage import AccountUsage, UsageTotals, detail, headline, headline_segments
from pet.dynamic_island import _METRO_BLOCK, _METRO_TILT_DEG, _METRO_TILT_DISTANCE, metro_tilt_params
from pet.settings_widgets import tilt_transform
from tests.test_island_info_slot import _island

app = QApplication.instance() or QApplication([])


def _two_accounts(wsl_total: UsageTotals | None = UsageTotals(output=1_100_000)) -> list[AccountUsage]:
    return [AccountUsage("windows", UsageTotals(output=2_380_000)), AccountUsage("wsl", wsl_total)]


# ---------------------------------------------------------------- 倾斜限幅

def test_square_block_keeps_the_tuned_tilt():
    degrees, distance = metro_tilt_params(QRect(0, 0, _METRO_BLOCK, _METRO_BLOCK))
    assert degrees == _METRO_TILT_DEG and distance == _METRO_TILT_DISTANCE


def test_wide_block_tilts_less_so_its_edge_moves_no_more_than_a_square_one():
    square = QRect(0, 0, _METRO_BLOCK, _METRO_BLOCK)
    wide = QRect(0, 0, 150, _METRO_BLOCK)
    degrees, distance = metro_tilt_params(wide)
    assert degrees[0] < _METRO_TILT_DEG[0] / 4 and distance > _METRO_TILT_DISTANCE * 4
    assert degrees[0] * 150 == pytest.approx(_METRO_TILT_DEG[0] * _METRO_BLOCK), "角度与长边成反比"

    def edge_shift(rect: QRect, params) -> float:
        # 光标压在右边缘中点，看左右两边缘的中点最多被挪了多远（倾斜带来的边缘位移）
        pos = QPoint(rect.right(), rect.center().y())
        transform = tilt_transform(rect, pos, degrees=params[0], distance=params[1])
        shifts = []
        for x in (rect.left(), rect.right()):
            mapped = transform.map(QPointF(x, rect.center().y()))
            shifts.append(abs(mapped.x() - x) + abs(mapped.y() - rect.center().y()))
        return max(shifts)

    tuned = (_METRO_TILT_DEG, _METRO_TILT_DISTANCE)
    assert edge_shift(wide, tuned) > 20, "原来的角度套在宽磁贴上：边缘挪出二十多像素，整块乱晃"
    assert edge_shift(wide, (degrees, distance)) <= edge_shift(square, tuned) + 0.5, "限幅后与方块相当"
    # 细高的磁贴同理按长边算
    tall_degrees, _ = metro_tilt_params(QRect(0, 0, _METRO_BLOCK, 84))
    assert tall_degrees[0] * 84 == pytest.approx(_METRO_TILT_DEG[0] * _METRO_BLOCK)


def test_island_usage_block_uses_the_scaled_tilt(tmp_path):
    island = _island(tmp_path, info_mode="usage_today", style="metro")
    try:
        island.set_usage_info("Win 2.38M · WSL 1.10M", "明细", headline_segments(_two_accounts()))
        rect = island.metro_blocks()["usage"]
        assert rect.width() > 3 * _METRO_BLOCK, "两个账号的磁贴确实宽"
        island._set_metro_hover("usage", QPoint(int(rect.right()) - 1, int(rect.center().y())))
        tilt = island.metro_tilt("usage")
        mapped = tilt.map(QPointF(rect.left(), rect.center().y()))
        assert abs(mapped.x() - rect.left()) < 2.0, "宽磁贴的边缘只动一点"
    finally:
        island.deleteLater()
        app.processEvents()


# ---------------------------------------------------------------- 文案与分段

def test_headline_drops_the_today_prefix():
    assert UsageTotals(output=2_380_000).headline == "2.38M"
    assert headline(_two_accounts()) == "Win 2.38M · WSL 1.10M"
    assert headline(_two_accounts(None)) == "Win 2.38M · WSL --"
    assert "今日" in UsageTotals(output=10).detail, "悬停说明里还说得清是今天"
    assert "今日" not in UsageTotals(output=10).headline


def test_headline_segments_name_the_account_for_the_icon():
    assert headline_segments(_two_accounts()) == [("windows", "Win", "2.38M"), ("wsl", "WSL", "1.10M")]
    assert headline_segments(_two_accounts(None)) == [("windows", "Win", "2.38M"), ("wsl", "WSL", "--")]
    one = [AccountUsage(claude_usage.LOCAL_ACCOUNT, UsageTotals(output=10))]
    assert headline_segments(one) == [], "一个账号：没有图标可配，还是一个数"


def test_monitor_announces_the_segments_too(tmp_path):
    from pet.claude_usage_monitor import ClaudeUsageMonitor

    del tmp_path
    monitor = ClaudeUsageMonitor(measure=lambda: None, spawn=lambda fn: fn())
    seen = []
    monitor.usage_changed.connect(lambda text, detail_text, segments: seen.append((text, segments)))
    try:
        monitor._on_measured(monitor._generation, _two_accounts())
        assert seen == [("Win 2.38M · WSL 1.10M", [("windows", "Win", "2.38M"), ("wsl", "WSL", "1.10M")])]
        monitor._on_measured(monitor._generation, UsageTotals(output=10))
        assert seen[-1] == ("10", [])
    finally:
        monitor.deleteLater()


def test_metro_usage_block_draws_icons_instead_of_the_labels(tmp_path):
    island = _island(tmp_path, info_mode="usage_today", style="metro")
    try:
        island.show()
        app.processEvents()
        segments = headline_segments(_two_accounts())
        island.set_usage_info(headline(_two_accounts()), detail(_two_accounts()), segments)
        glyphs = island.usage_segment_glyphs()
        assert glyphs == [("windows", "2.38M"), ("ubuntu", "1.10M")], "Win → 四格窗，WSL → Ubuntu 一环三点"
        width_with_icons = island.metro_blocks()["usage"].width()
        # 对照：没有分段（别的样式 / 一个账号）时按整段文字排
        island.set_usage_info(headline(_two_accounts()), detail(_two_accounts()), [])
        assert island.usage_segment_glyphs() == []
        width_with_text = island.metro_blocks()["usage"].width()
        assert width_with_icons < width_with_text, "图标比「Win」「WSL」字样省地方"
        # 不认识的账号键退回画它的短名
        island.set_usage_info("A 1 · B 2", "", [("mars", "A", "1"), ("wsl", "WSL", "2")])
        assert island.usage_segment_glyphs() == [("", "A 1"), ("ubuntu", "2")]
    finally:
        island.deleteLater()
        app.processEvents()


def test_segments_do_not_leak_into_other_styles(tmp_path):
    island = _island(tmp_path, info_mode="usage_today", style="dark")
    try:
        island.set_usage_info("Win 2.38M · WSL 1.10M", "明细", headline_segments(_two_accounts()))
        assert island._info_text() == "Win 2.38M · WSL 1.10M"
        assert island.usage_segment_glyphs() == [], "非 Metro 没有磁贴可画图标，照旧画文字"
    finally:
        island.deleteLater()


# ---------------------------------------------------------------- 仪表盘：透明底 + 阴影

def test_dashboard_background_is_transparent_and_tiles_cast_a_shadow():
    from pet.usage_dashboard import DashboardData, build_tiles
    from pet.usage_dashboard_ui import TILE_SHADOW_SPREAD, UsageDashboardWindow
    from tests.test_usage_dashboard import _activity, _usage

    window = UsageDashboardWindow()
    try:
        window.set_content(build_tiles(DashboardData(_usage(), _activity())), "")
        window.show()
        app.processEvents()
        image = window.grab().toImage()
        assert image.pixelColor(2, 2).alpha() == 0, "页面底色透明：磁贴直接浮在桌面上"
        tile = window.tiles[0]
        inside = image.pixelColor(tile.x() + 4, tile.y() + 4)
        assert inside.name() == tile.tile.color and inside.alpha() == 255
        below = image.pixelColor(tile.x() + tile.width() // 2, tile.y() + tile.height() + 2)
        assert 0 < below.alpha() < 255, "磁贴正下方 2px 是半透明的阴影"
        far = image.pixelColor(tile.x() + tile.width() // 2, tile.y() - TILE_SHADOW_SPREAD - 3)
        assert far.alpha() == 0, "阴影有边界，再远就是透明"
    finally:
        window.deleteLater()
        app.processEvents()


def test_dashboard_header_text_is_readable_on_any_wallpaper():
    from pet.usage_dashboard_ui import UsageDashboardWindow, halo_color

    window = UsageDashboardWindow()
    try:
        window.apply_theme("light")
        assert halo_color(QColor(window.colors["title"])).lightness() > 200, "深色字配浅色光晕"
        window.apply_theme("dark")
        assert halo_color(QColor(window.colors["title"])).lightness() < 60, "浅色字配深色光晕"
        assert window.title_label.halo().alpha() > 0
    finally:
        window.deleteLater()


# ---------------------------------------------------------------- 置顶看门狗

def test_topmost_watchdog_runs_only_while_visible(tmp_path):
    island = _island(tmp_path)        # 辅助函数已 show()
    try:
        app.processEvents()
        assert island._topmost_watch.isActive()
        assert island._topmost_watch.interval() == 2000
        island.hide()
        app.processEvents()
        assert not island._topmost_watch.isActive()
    finally:
        island.deleteLater()
        app.processEvents()


def test_topmost_watchdog_reasserts_only_when_something_covers_the_island(tmp_path):
    island = _island(tmp_path)
    calls = []
    try:
        app.processEvents()               # showEvent 排的那次重申先走完
        island.reassert_topmost = lambda: calls.append("reassert") or True
        island._occlusion_probe = lambda: (False, "")
        island._watch_topmost()
        assert calls == [], "没人盖着就不动 z 序"
        island._occlusion_probe = lambda: (True, "Chrome_WidgetWin_1")
        island._watch_topmost()
        assert calls == ["reassert"]
        island._shell_in_front = lambda: True
        island._watch_topmost()
        assert calls == ["reassert"], "开始菜单 / 任务栏弹出层在前台：不跟系统外壳抢"
    finally:
        island.deleteLater()
        app.processEvents()


def test_occlusion_probe_is_pure_over_a_fake_z_order():
    from pet.platform_win import occluder_above

    # 假 z 序（从上到下）：hwnd → (可见, 被 DWM 隐藏, 矩形, 类名, 本进程的)
    windows = {
        10: (True, False, QRect(0, 0, 100, 100), "Shell_TrayWnd", False),
        20: (False, False, QRect(0, 0, 4000, 4000), "Hidden", False),
        30: (True, True, QRect(0, 0, 4000, 4000), "Cloaked", False),
        35: (True, False, QRect(0, 0, 4000, 4000), "Qt663QWindowToolSaveBits", True),   # 自家的通知卡片
        40: (True, False, QRect(500, 500, 200, 200), "Chrome_WidgetWin_1", False),
        50: (True, False, QRect(900, 900, 100, 44), "Qt663QWindowToolSaveBits", True),
    }
    order = [10, 20, 30, 35, 40, 50]

    def prev(hwnd):
        index = order.index(hwnd)
        return order[index - 1] if index > 0 else 0

    def info(hwnd):
        return windows[hwnd]

    assert occluder_above(50, QRect(900, 900, 100, 44), prev=prev, info=info) == "", "只有自家的卡片压着：不算（通知卡片有自己的看门狗，两边会互相压）"
    assert occluder_above(50, QRect(600, 600, 100, 44), prev=prev, info=info) == "Chrome_WidgetWin_1"
    assert occluder_above(50, QRect(50, 50, 100, 44), prev=prev, info=info) == "Shell_TrayWnd", \
        "不可见 / 被 DWM 隐藏的窗不算盖住"
    assert occluder_above(50, QRect(2000, 2000, 100, 44), prev=prev, info=info) == ""

