# -*- coding: utf-8 -*-
"""灵动岛上的名字（2026-11-14 用户问「为什么是 shenshen、在哪改」）。

- 岛上的名字和右键菜单 / 聊天窗 / 主动识屏用的是同一个「角色显示名」：
  用户起的名字优先，没起就用角色包 manifest 里的 name，再没有才是角色 id。
  以前岛自己拼 ``别名 or 角色id``，跳过了 manifest（Claude 角色显示成小写 claude）。
- 设置页「灵动岛」里「显示名字」下面多一行「名字」，直接改当前角色的显示名；
  留空 = 恢复默认。右键菜单「重命名当前角色…」改的是同一个值。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLineEdit

from pet.config import Config
from pet.dynamic_island import DynamicIsland

app = QApplication.instance() or QApplication([])


def _island(config: Config) -> DynamicIsland:
    island_cfg = dict(config.get("dynamic_island") or {})
    island_cfg.update({"enabled": True, "show_name": True, "x": 400, "y": 300})
    config.set("dynamic_island", island_cfg)
    return DynamicIsland(config)


def _dialog(config: Config, monkeypatch):
    from pet import modern_settings_dialog as settings_mod

    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    return settings_mod.ModernSettingsDialog(config, include_ai=False)


def _row(dialog, key):
    from pet.settings_widgets import SettingRow

    row = dialog.findChild(SettingRow, f"settingRow_{key}")
    assert row is not None, key
    return row


def _close(widget):
    widget.close()
    widget.deleteLater()
    app.processEvents()


# ------------------------------------------------------------ 岛上显示什么


def test_island_name_falls_back_to_manifest_name_not_raw_id(tmp_path):
    config = Config(tmp_path)
    config.set("character", "claude")  # manifest.json 里 name = "Claude"
    island = _island(config)
    try:
        assert island._character_name() == "Claude"
    finally:
        _close(island)


def test_island_name_uses_user_alias_first(tmp_path):
    config = Config(tmp_path)
    config.set("character", "shenshen")
    config.set_character_alias("shenshen", "大肥鱼")
    island = _island(config)
    try:
        assert island._character_name() == "大肥鱼"
    finally:
        _close(island)


def test_island_reads_manifest_once_per_character_but_alias_live(tmp_path, monkeypatch):
    """每帧绘制都会取名字：manifest 不能每帧读盘；换角色要重新取；改名立刻生效。"""
    from pet import catalog

    calls = []
    real = catalog.character_display_name

    def counting(character_id):
        calls.append(character_id)
        return real(character_id)

    monkeypatch.setattr(catalog, "character_display_name", counting)
    config = Config(tmp_path)
    config.set("character", "claude")
    island = _island(config)
    try:
        for _ in range(50):
            assert island._character_name() == "Claude"
        assert calls == ["claude"]  # 建岛时取过一次，之后都不再读盘
        config.set("character", "shenshen")
        assert island._character_name() == "shenshen"
        assert calls == ["claude", "shenshen"]
        config.set_character_alias("shenshen", "大肥鱼")
        assert island._character_name() == "大肥鱼"
    finally:
        _close(island)


# ------------------------------------------------------------ 设置页可以改


def test_settings_has_island_name_field_showing_current_alias(tmp_path, monkeypatch):
    config = Config(tmp_path)
    config.set("character", "shenshen")
    config.set_character_alias("shenshen", "深深")
    dialog = _dialog(config, monkeypatch)
    try:
        edit = _row(dialog, "dynamic_island_name_value").findChild(QLineEdit)
        assert edit is not None
        assert edit.text() == "深深"
        # 留空时显示的默认名（manifest name，没有就是角色 id）作为占位提示
        assert edit.placeholderText() == "shenshen"
        assert edit.maxLength() == 24
    finally:
        _close(dialog)


def test_saving_settings_writes_the_name_for_current_character(tmp_path, monkeypatch):
    config = Config(tmp_path)
    config.set("character", "shenshen")
    config.set_character_alias("claude", "老克")  # 别的角色的名字不受影响
    config.save()
    dialog = _dialog(config, monkeypatch)
    try:
        edit = _row(dialog, "dynamic_island_name_value").findChild(QLineEdit)
        edit.setText("  大肥鱼  ")
        assert dialog._write_config()
    finally:
        _close(dialog)
    reloaded = Config(tmp_path)
    assert reloaded.character_alias("shenshen") == "大肥鱼"
    assert reloaded.character_alias("claude") == "老克"
    assert reloaded.character_display_name("shenshen") == "大肥鱼"


def test_clearing_the_field_restores_default_name(tmp_path, monkeypatch):
    config = Config(tmp_path)
    config.set("character", "claude")
    config.set_character_alias("claude", "老克")
    dialog = _dialog(config, monkeypatch)
    try:
        _row(dialog, "dynamic_island_name_value").findChild(QLineEdit).setText("")
        assert dialog._write_config()
    finally:
        _close(dialog)
    reloaded = Config(tmp_path)
    assert reloaded.character_alias("claude") == ""
    assert reloaded.character_display_name("claude") == "Claude"


def test_saving_without_touching_field_keeps_menu_rename(tmp_path, monkeypatch):
    """设置开着时用户从右键菜单改了名：没碰这一栏就保存，不能把菜单改的名字冲掉。"""
    config = Config(tmp_path)
    config.set("character", "shenshen")
    config.save()
    dialog = _dialog(config, monkeypatch)
    try:
        other = Config(tmp_path)
        other.set_character_alias("shenshen", "菜单里改的")
        assert dialog._write_config()
    finally:
        _close(dialog)
    assert Config(tmp_path).character_alias("shenshen") == "菜单里改的"


def test_name_field_follows_show_name_and_island_toggles(tmp_path, monkeypatch):
    config = Config(tmp_path)
    island_cfg = dict(config.get("dynamic_island") or {})
    island_cfg.update({"enabled": True, "show_name": True})
    config.set("dynamic_island", island_cfg)
    dialog = _dialog(config, monkeypatch)
    try:
        row = _row(dialog, "dynamic_island_name_value")
        assert not row.isHidden()
        dialog.island_name_check.setChecked(False)
        assert row.isHidden()
        dialog.island_name_check.setChecked(True)
        assert not row.isHidden()
        dialog.island_enabled_check.setChecked(False)
        assert row.isHidden()
    finally:
        _close(dialog)
