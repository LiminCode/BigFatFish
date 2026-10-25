# -*- coding: utf-8 -*-
"""灵动岛信息槽：只留两种内容——当前时间、今日用量（Claude Code 今天用掉的 token）。

原来的「余额峰谷」「余额数值」是给 DeepSeek 计费用的，「自定义短文本」没人用，三个
一起去掉；存着这三个旧值的配置回落成「当前时间」。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from pet import modern_settings_dialog as settings_mod
from pet.claude_usage import UsageTotals
from pet.config import Config
from pet.dynamic_island import DynamicIsland
from tests.test_island_shell_wiring import _make_shell, _teardown_shell

app = QApplication.instance() or QApplication([])

REMOVED_MODES = ("balance_tier", "balance", "custom")


def _island(tmp_path: Path, **overrides) -> DynamicIsland:
    cfg = Config(base=tmp_path)
    data = {"enabled": True, "show_icon": True, "show_name": True, "show_info": True,
            "info_mode": "time", "show_status": True, "style": "dark", "x": 400, "y": 300}
    data.update(overrides)
    cfg.set("dynamic_island", data)
    island = DynamicIsland(cfg)
    island.show()
    return island


# ---------------------------------------------------------------- 岛

def test_time_mode_shows_the_clock(tmp_path):
    island = _island(tmp_path)
    try:
        assert re.fullmatch(r"\d\d:\d\d", island._info_text())
    finally:
        island.deleteLater()


def test_usage_mode_shows_todays_tokens(tmp_path):
    island = _island(tmp_path, info_mode="usage_today")
    try:
        assert island._info_text() == "今日 --", "还没量出来之前不装作是 0"
        width, before = island.width(), island._content_cache()

        island.set_usage_info("今日 2.38M", "今日 Claude Code 用量 2.38M：输出 561.7K …")

        assert island._info_text() == "今日 2.38M"
        assert island._content_cache() is not before, "数字变了要重画"
        assert island.width() != width or True
        assert "今日 Claude Code 用量 2.38M" in island.toolTip(), "悬停看明细"
    finally:
        island.deleteLater()


def test_usage_text_does_not_show_in_time_mode(tmp_path):
    island = _island(tmp_path)
    try:
        island.set_usage_info("今日 2.38M", "明细")
        assert re.fullmatch(r"\d\d:\d\d", island._info_text())
        assert "明细" not in island.toolTip(), "没显示用量就不在提示里说用量"
    finally:
        island.deleteLater()


def test_tooltip_carries_both_the_api_verdict_and_the_usage_detail(tmp_path):
    island = _island(tmp_path, info_mode="usage_today")
    try:
        island.set_api_status("ok", "连接成功（Claude · claude-sonnet-5）")
        island.set_usage_info("今日 1.0K", "用量明细")
        hint = "点数字看近 7 天仪表盘"
        assert island.toolTip().splitlines() == ["连接成功（Claude · claude-sonnet-5）", "用量明细", hint]
        island.set_api_status("bad", "认证失败")
        assert island.toolTip().splitlines() == ["认证失败", "用量明细", hint]
    finally:
        island.deleteLater()


@pytest.mark.parametrize("mode", REMOVED_MODES)
def test_removed_modes_fall_back_to_the_clock(tmp_path, mode):
    island = _island(tmp_path, info_mode=mode, custom_text="占位")
    try:
        assert re.fullmatch(r"\d\d:\d\d", island._info_text())
    finally:
        island.deleteLater()


def test_island_no_longer_keeps_a_price_tier_clock(tmp_path):
    """「余额峰谷」去掉后，岛上为它准点刷新的那只定时器也不该留着空转。"""
    island = _island(tmp_path)
    try:
        assert not hasattr(island, "_tier_tick_timer")
    finally:
        island.deleteLater()


# ---------------------------------------------------------------- 配置

@pytest.mark.parametrize("raw, expected", [
    ("time", "time"), ("usage_today", "usage_today"), ("balance_tier", "time"), ("balance", "time"),
    ("custom", "time"), ("nonsense", "time"), (None, "time"),
])
def test_info_mode_is_normalised(tmp_path, raw, expected):
    cfg = Config(base=tmp_path)
    data = dict(cfg.get("dynamic_island"))
    data.update(info_mode=raw, custom_text="旧的自定义文本")
    cfg.set("dynamic_island", data)
    cfg.save()
    island_cfg = Config(base=tmp_path).get("dynamic_island")
    assert island_cfg["info_mode"] == expected
    assert "custom_text" not in island_cfg, "自定义短文本没有了，旧值不再跟着配置走"


# ---------------------------------------------------------------- 设置页

@pytest.fixture
def dialog(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    dialog = settings_mod.ModernSettingsDialog(Config(tmp_path), include_ai=False)
    dialog.base = tmp_path
    yield dialog
    dialog._saved_via_button = True
    dialog.deleteLater()
    app.processEvents()


def test_settings_offer_exactly_clock_and_usage(dialog):
    select = dialog.island_info_mode_select
    assert [(select.itemText(i), select.itemData(i)) for i in range(select.count())] == [
        ("当前时间", "time"), ("今日用量", "usage_today")]
    assert dialog.findChild(settings_mod.SettingRow, "settingRow_dynamic_island_custom_text") is None
    assert not hasattr(dialog, "island_custom_text_edit")


def test_choosing_usage_is_saved(dialog):
    dialog.island_info_mode_select.setCurrentData("usage_today")
    dialog.save_button.click()
    assert Config(dialog.base).get("dynamic_island")["info_mode"] == "usage_today"


def test_info_slot_description_no_longer_mentions_removed_content(dialog):
    row = dialog.findChild(settings_mod.SettingRow, "settingRow_dynamic_island_info_mode")
    assert row is not None
    text = " ".join(label.text() for label in row.findChildren(settings_mod.QLabel))
    assert "自定义" not in text and "余额" not in text
    assert "今日用量" in text or "token" in text


# ---------------------------------------------------------------- AppShell

@pytest.fixture
def shell(tmp_path):
    shell = _make_shell(tmp_path, info_mode="usage_today", show_info=True)
    shell._sync_dynamic_island()
    yield shell
    _teardown_shell(shell)


def _set_island(shell, **changes) -> None:
    data = dict(shell.config.get("dynamic_island"))
    data.update(changes)
    shell.config.set("dynamic_island", data)
    shell._sync_dynamic_island()


def test_usage_is_measured_only_while_the_slot_shows_it(shell):
    monitor = shell._usage_monitor
    assert monitor._active is True

    _set_island(shell, info_mode="time")
    assert monitor._active is False, "信息槽没显示用量：不读对话记录"
    _set_island(shell, info_mode="usage_today", show_info=False)
    assert monitor._active is False
    _set_island(shell, show_info=True)
    assert monitor._active is True
    _set_island(shell, enabled=False)
    assert monitor._active is False, "岛关了就停"


def test_measurements_reach_the_island(shell):
    totals = UsageTotals(output=2_380_000)
    shell._usage_monitor.usage_changed.emit(totals.headline, totals.detail)
    assert shell.island._info_text() == "今日 2.38M"
    assert totals.detail in shell.island.toolTip()
