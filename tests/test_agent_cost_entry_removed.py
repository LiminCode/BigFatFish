# -*- coding: utf-8 -*-
"""「显示本轮消费」（DeepSeek 余额差）从右键菜单和设置页下线；配置键与结算代码保留。

用户 2026-10-13：「自动化与联动里的消费统计可以去掉了，毕竟我们用不到 DeepSeek」。
它靠 DeepSeek 的余额接口算每轮花了多少钱，Claude 没有这种接口；Claude 的用量已经在
灵动岛的「今日用量」里。口径与「音乐」一样：只摘入口，不删后面的代码。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from pet import menu_layout
from pet.config import Config
from pet.context_menus import registry
from tests.test_menu_music_entries_removed import _ids
from tests.test_sprite_menu_parity import _all_labels, _make_overlay

app = QApplication.instance() or QApplication([])


def test_neither_menu_offers_the_per_turn_cost_toggle(tmp_path):
    assert "agent_cost" not in registry.ACTION_LABELS
    assert "agent_cost" not in _ids(menu_layout.load_default_menu_layout()["nodes"])
    for template in ("modern", "legacy"):
        shell, _instance, _config = _make_overlay(tmp_path / template, template=template)
        try:
            from pet.sprite_menu_facade import build_sprite_full_menu

            menu = build_sprite_full_menu(shell)
            assert "显示本轮消费" not in _all_labels(menu), template
            assert "黄金回旋" in _all_labels(menu), "同组的其他项还在（新版在「桌宠控制」里，旧版平铺）"
        finally:
            shell._delete_runtime_marker()


def test_the_settings_page_has_no_cost_section_any_more(tmp_path, monkeypatch):
    from pet import modern_settings_dialog as settings_mod

    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    dialog = settings_mod.ModernSettingsDialog(Config(tmp_path), include_ai=False)
    try:
        assert dialog.findChild(settings_mod.SettingRow, "settingRow_agent_cost") is None
        assert getattr(dialog, "agent_cost_check", None) is None
        titles = [w.text() for w in dialog.findChildren(settings_mod.QLabel) if w.text() == "消费统计"]
        assert titles == []
        assert dialog.findChild(settings_mod.SettingRow, "settingRow_vscode_workspace_dir") is not None, "同一页的其他节还在"
        dialog._save()
    finally:
        dialog.deleteLater()
    assert Config(tmp_path).get("agent_cost_enabled") is False, "保存不碰这个键"


def test_the_setting_itself_still_loads_and_a_saved_layout_drops_the_entry(tmp_path):
    config = Config(tmp_path)
    assert config.get("agent_cost_enabled") is False
    config.set("agent_cost_enabled", True)
    config.set("context_menu_layout", {"schema_version": 1, "nodes": [
        {"type": "submenu", "id": "pet_controls", "label": "桌宠控制", "visible": True, "children": [
            {"type": "action", "id": "agent_cost", "visible": True},
            {"type": "action", "id": "golden_spin", "visible": True}]},
        {"type": "action", "id": "modern_settings", "visible": True},
        {"type": "action", "id": "quit", "visible": True}]})
    config.save()
    reloaded = Config(tmp_path)
    assert reloaded.get("agent_cost_enabled") is True, "老配置里开着的照旧读进来（结算代码还在读它）"
    assert "agent_cost" not in _ids(reloaded.get("context_menu_layout")["nodes"])
    assert "golden_spin" in _ids(reloaded.get("context_menu_layout")["nodes"])
