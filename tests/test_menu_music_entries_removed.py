# -*- coding: utf-8 -*-
"""右键菜单上不再有「音乐」：两套菜单、模板、注册表都没有它；歌词气泡与唱歌联动照旧。

用户 2026-10-13 的决定：音乐功能本身（设置页「音乐关联」、歌词气泡、唱歌动画）保留，
只把右键菜单上的那一组入口拿掉——「最小影响」。

守住的几条：

- 默认模板和旧版建造器都不再产出「音乐」子菜单；
- 注册表里没有 music_* 这些 id（菜单编辑器也就不再列出它们）；
- 用户以前保存过的菜单布局里若还留着这一组，加载时清掉、渲染时不留一个空壳；
- 歌词功能的配置项原样还在。
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMenu

from pet import menu_layout
from pet.config import Config
from pet.context_menu import load_menu_template
from pet.context_menus import build_legacy_menu, registry
from tests.test_sprite_menu_parity import _all_labels, _make_overlay

app = QApplication.instance() or QApplication([])

MUSIC_IDS = ("music", "music_pause", "music_next", "music_prev", "music_quit",
             "music_lyric_align", "music_open_netease", "music_open_qqmusic")


class _LegacyHost:
    """旧版建造器要的宿主面（照 test_desktop_pet_features 里那只替身）：配置 + 任意回调都接住。"""

    on_open_chat = lambda self: None  # noqa: E731
    idles, turns, moves, clicks, acts = ["待机"], ["转向"], ["移动"], ["点击"], ["动作"]
    playback_speed = 1.0
    drag_physics = False
    no_move = False
    scale = 1.0

    def __init__(self):
        self._data = {"character": "shenshen", "on_top": True, "context_menu_template": "legacy",
                      "music_lyric_enabled": True}

    @property
    def cfg(self):
        return self

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value

    def save(self):
        return None

    def icon_pixmap(self, size=64):
        from PySide6.QtGui import QPixmap

        pixmap = QPixmap(size, size)
        pixmap.fill()
        return pixmap

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def _ids(nodes) -> set[str]:
    found = set()
    for node in nodes:
        if isinstance(node, dict):
            found.add(str(node.get("id") or ""))
            found.update(_ids(node.get("children") or []))
    return found


def test_the_default_template_and_registry_no_longer_know_the_music_group():
    assert not _ids(menu_layout.load_default_menu_layout()["nodes"]) & set(MUSIC_IDS)
    assert not set(registry.ACTION_LABELS) & set(MUSIC_IDS)
    assert not set(registry.ACTION_ICONS) & set(MUSIC_IDS)


def test_neither_menu_shows_music_any_more(tmp_path, monkeypatch):
    import pet.autostart as autostart_mod
    import pet.catalog as catalog_mod

    monkeypatch.setattr(autostart_mod, "is_enabled", lambda: False)      # 不碰真实的开机自启项
    monkeypatch.setattr(catalog_mod, "list_available_characters", lambda: ["shenshen"])
    for template in ("modern", "legacy"):
        shell, _instance, config = _make_overlay(tmp_path / template, template=template)
        try:
            config.set("music_lyric_enabled", True)     # 歌词功能开着也不出菜单
            from pet.sprite_menu_facade import build_sprite_full_menu

            labels = _all_labels(build_sprite_full_menu(shell))
            assert "音乐" not in labels and not any(label.endswith("给主人放歌") for label in labels), template
        finally:
            shell._delete_runtime_marker()

    menu = QMenu()
    build_legacy_menu(menu, _LegacyHost(), load_menu_template("legacy"))
    assert "音乐" not in [action.text() for action in menu.actions()]


def test_a_saved_layout_that_still_has_the_group_renders_without_an_empty_shell(tmp_path):
    registered = set(registry.ACTION_LABELS)
    saved = {"schema_version": 1, "nodes": [
        {"type": "action", "id": "size", "visible": True},
        {"type": "submenu", "id": "music", "label": "音乐", "visible": True, "children": [
            {"type": "action", "id": "music_pause", "visible": True},
            {"type": "separator", "id": "music.separator-launch", "visible": True},
            {"type": "action", "id": "music_open_qqmusic", "visible": True},
        ]},
        {"type": "action", "id": "modern_settings", "visible": True},
        {"type": "action", "id": "quit", "visible": True},
    ]}
    result = menu_layout.resolve_menu_layout(saved, registered_actions=registered, available_actions=registered)
    assert "music" not in [node["id"] for node in result.nodes]
    assert all(node.get("children") for node in result.nodes if node["type"] == "submenu")

    config = Config(tmp_path)
    config.set("context_menu_layout", saved)
    config.save()
    reloaded = Config(tmp_path).get("context_menu_layout")
    assert not _ids(reloaded["nodes"]) & set(MUSIC_IDS), "加载时就把这一组清掉，和早先下线的几个 id 一样"


def test_the_lyric_feature_itself_is_untouched(tmp_path):
    config = Config(tmp_path)
    assert "music_lyric_enabled" in config.data and "music_player_paths" in config.data
    text = json.dumps(menu_layout.load_default_menu_layout(), ensure_ascii=False)
    assert "音乐" not in text and "music" not in text
