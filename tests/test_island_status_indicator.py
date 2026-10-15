# -*- coding: utf-8 -*-
"""灵动岛右侧状态区：API 连接图标（绿 = 可用，红 = 不可用）+ Claude Code 会话计数。

原来的状态圆点（蓝 = Agent 在忙 / 绿 = 肥鱼可见 / 灰 = 肥鱼隐藏）已换掉：Agent
在忙改由计数表达，肥鱼显隐看卡片按钮。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from pet.config import Config
from pet.dynamic_island import DynamicIsland

app = QApplication.instance() or QApplication([])

_STATUS_REGION_PX = 46      # 胶囊右端这一段只有状态图标（没有计数时）


def _island(tmp_path: Path, **overrides) -> DynamicIsland:
    cfg = Config(base=tmp_path)
    data = {
        "enabled": True, "show_icon": True, "show_name": True,
        "show_info": True, "info_mode": "custom", "custom_text": "测试文本",
        "show_status": True, "style": "dark", "x": 400, "y": 300,
    }
    data.update(overrides)
    cfg.set("dynamic_island", data)
    island = DynamicIsland(cfg)
    island.show()
    return island


def _tints(island, *, left: int | None = None) -> dict:
    """内容层里偏红 / 偏绿 / 其他（灰白）的不透明像素数；默认只数右端状态区。"""
    image = island._content_cache().toImage().convertToFormat(QImage.Format.Format_ARGB32)
    dpr = image.devicePixelRatio()
    start = int((island.width() - _STATUS_REGION_PX) * dpr) if left is None else int(left * dpr)
    counts = {"red": 0, "green": 0, "other": 0}
    for y in range(image.height()):
        for x in range(max(0, start), image.width()):
            color = image.pixelColor(x, y)
            if color.alpha() < 128:
                continue
            if color.red() > color.green() + 60 and color.red() > color.blue() + 60:
                counts["red"] += 1
            elif color.green() > color.red() + 60 and color.green() > color.blue() + 30:
                counts["green"] += 1
            else:
                counts["other"] += 1
    return counts


def test_icon_is_neutral_until_the_api_has_been_checked(tmp_path):
    island = _island(tmp_path)
    try:
        tints = _tints(island)
        assert tints["other"] > 0, "没查过也要画出图标"
        assert tints["red"] == 0 and tints["green"] == 0, "没查过就既不绿也不红"
    finally:
        island.deleteLater()


def test_icon_is_green_when_the_api_key_works_and_red_when_it_does_not(tmp_path):
    island = _island(tmp_path)
    try:
        island.set_api_status("ok", "连接成功（Claude · claude-sonnet-5）")
        ok = _tints(island)
        assert ok["green"] > 0 and ok["red"] == 0
        assert island.toolTip() == "连接成功（Claude · claude-sonnet-5）", "悬停能看到结论"

        island.set_api_status("bad", "认证失败：API Key 无效或已失效")
        bad = _tints(island)
        assert bad["red"] > 0 and bad["green"] == 0
        assert island.toolTip() == "认证失败：API Key 无效或已失效", "红了得说得出为什么"

        island.set_api_status("没见过的状态")
        unknown = _tints(island)
        assert unknown["red"] == 0 and unknown["green"] == 0
    finally:
        island.deleteLater()


def test_connected_and_broken_icons_differ_in_shape_not_only_colour(tmp_path):
    """红绿色弱的人也得分得清：断开的图标多一道斜杠、少中间那一横。"""
    island = _island(tmp_path)
    try:
        def mask():
            image = island._content_cache().toImage().convertToFormat(QImage.Format.Format_ARGB32)
            start = int((island.width() - _STATUS_REGION_PX) * image.devicePixelRatio())
            return [(x, y) for y in range(image.height()) for x in range(start, image.width())
                    if image.pixelColor(x, y).alpha() >= 128]

        island.set_api_status("ok")
        connected = mask()
        island.set_api_status("bad")
        assert mask() != connected
    finally:
        island.deleteLater()


def test_agent_activity_and_pet_visibility_no_longer_recolour_the_icon(tmp_path):
    island = _island(tmp_path)
    try:
        island.set_api_status("ok")
        before = island._content_cache()

        island.set_agent_active(True)
        island.set_pet_visible(False)

        assert island._content_cache() is before, "图标只表达 API 状态"
        assert _tints(island)["green"] > 0
    finally:
        island.deleteLater()


def test_session_counts_are_drawn_on_the_capsule(tmp_path):
    island = _island(tmp_path)
    try:
        bare_width = island.width()
        bare = island._content_cache()
        assert _tints(island, left=0)["green"] == 0

        island.set_session_counts([("working", "2 工作中"), ("resting", "1 休息中"), ("waiting", "2 等待中")])

        assert island.width() > bare_width, "胶囊加宽容纳计数"
        assert island._content_cache() is not bare
        assert _tints(island, left=0)["green"] > 0, "「工作中」那一段是绿色"

        wide = island.width()
        island.set_session_counts([("working", "1 工作中")])
        assert bare_width < island.width() < wide

        island.set_session_counts([])
        assert island.width() == bare_width, "没有会话就不占地方"
    finally:
        island.deleteLater()


def _blue_pixels(island) -> int:
    image = island._content_cache().toImage().convertToFormat(QImage.Format.Format_ARGB32)
    return sum(
        1 for y in range(image.height()) for x in range(image.width())
        if (c := image.pixelColor(x, y)).alpha() >= 128
        and c.blue() > c.red() + 60 and c.blue() > c.green() + 20)


def test_sessions_waiting_for_a_reply_are_counted_in_blue(tmp_path):
    island = _island(tmp_path)
    try:
        island.set_session_counts([("resting", "1 休息中")])
        plain = _blue_pixels(island)           # 胶囊上别的内容（头像）本来就可能带蓝
        island.set_session_counts([("review", "1 待回复")])
        assert _blue_pixels(island) > plain + 20, "「休息中」用次文字色，「待回复」是蓝字"
    finally:
        island.deleteLater()


def test_status_switch_hides_both_the_icon_and_the_counts(tmp_path):
    island = _island(tmp_path, show_status=False)
    try:
        width = island.width()
        island.set_api_status("ok")
        island.set_session_counts([("working", "2 工作中")])
        assert island.width() == width
        assert _tints(island, left=0)["green"] == 0
    finally:
        island.deleteLater()


def test_docked_strip_dot_follows_the_api_status(tmp_path):
    island = _island(tmp_path)
    try:
        neutral = island._status_color()
        assert abs(neutral.red() - neutral.green()) < 30
        island.set_api_status("ok")
        ok = island._status_color()
        assert ok.green() > ok.red() + 60
        island.set_api_status("bad")
        bad = island._status_color()
        assert bad.red() > bad.green() + 60
    finally:
        island.deleteLater()
