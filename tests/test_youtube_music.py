# -*- coding: utf-8 -*-
"""右键菜单「YouTube Music」；网易云 / QQ 音乐的启动与路径设置整块下线。

用户 2026-10-15 的决定：听歌用 YouTube Music，网页版就够——菜单里一项，点了用默认浏览器
打开首页，不自动开始播放；网易云 / QQ 音乐（找程序、设置页填路径、启动时扫盘找它们）删掉。
歌词与唱歌联动照旧（它们读的是系统媒体会话，Chrome 里的 YouTube Music 也在其中）。
"""
from __future__ import annotations

import importlib
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMenu

from pet import menu_layout
from pet.config import Config
from pet.context_menu import load_menu_template
from pet.context_menus import build_legacy_menu, registry, shared
from tests.test_menu_music_entries_removed import _LegacyHost, _ids
from tests.test_sprite_menu_parity import _make_overlay

app = QApplication.instance() or QApplication([])

URL = "https://music.youtube.com/"


@pytest.fixture
def opened(monkeypatch):
    """系统边界：交给默认浏览器打开的网址（不真的开浏览器）。"""
    urls: list[str] = []
    monkeypatch.setattr(shared.QDesktopServices, "openUrl",
                        lambda url: (urls.append(url.toString()), True)[1])
    return urls


def _action(menu: QMenu, label: str):
    for action in menu.actions():
        if action.text() == label:
            return action
        sub = action.menu()
        if sub is not None:
            found = _action(sub, label)
            if found is not None:
                return found
    return None


# ---------------------------------------------------------------- YouTube Music
def test_default_template_offers_youtube_music_next_to_the_vscode_entry():
    nodes = menu_layout.load_default_menu_layout()["nodes"]
    ids = [node.get("id") for node in nodes]
    assert ids.index("youtube_music") == ids.index("vscode_workspaces") + 1
    assert registry.ACTION_LABELS["youtube_music"] == "YouTube Music"


@pytest.mark.parametrize("template", ["modern", "legacy"])
def test_clicking_it_opens_the_home_page_in_the_default_browser(tmp_path, monkeypatch, opened, template):
    import pet.autostart as autostart_mod
    import pet.catalog as catalog_mod
    from pet.sprite_menu_facade import build_sprite_full_menu

    monkeypatch.setattr(autostart_mod, "is_enabled", lambda: False)
    monkeypatch.setattr(catalog_mod, "list_available_characters", lambda: ["shenshen"])
    shell, _instance, _config = _make_overlay(tmp_path, template=template)
    try:
        menu = build_sprite_full_menu(shell)
        shell.keep_alive = menu
        action = _action(menu, "YouTube Music")
        assert action is not None and action.isEnabled(), f"{template} 菜单里要有它"
        action.trigger()
        assert opened == [URL], "只打开首页，不带播放参数"
    finally:
        shell._delete_runtime_marker()


def test_the_old_petwindow_menu_has_it_too(opened):
    menu = QMenu()
    build_legacy_menu(menu, _LegacyHost(), load_menu_template("legacy"))
    action = _action(menu, "YouTube Music")
    assert action is not None
    action.trigger()
    assert opened == [URL]


def test_a_saved_menu_layout_picks_it_up_beside_the_vscode_entry():
    """用户保存过菜单编排：新入口按模板位置补进去，不打乱用户自己的顺序。"""
    registered = set(registry.MENU_ACTIONS.ids)
    saved = {"schema_version": 1, "layout_id": "user", "nodes": [
        {"type": "action", "id": "rally_pets", "visible": True},
        {"type": "action", "id": "size", "visible": True},
        {"type": "action", "id": "vscode_workspaces", "visible": True},
        {"type": "action", "id": "chat", "visible": True},
        {"type": "action", "id": "modern_settings", "visible": True},
        {"type": "action", "id": "quit", "visible": True},
    ]}
    result = menu_layout.resolve_menu_layout(saved, registered_actions=registered,
                                             available_actions=registered)
    ids = [node["id"] for node in result.nodes]
    assert ids.index("youtube_music") == ids.index("vscode_workspaces") + 1
    mine = ["rally_pets", "size", "vscode_workspaces", "chat", "modern_settings", "quit"]
    assert [i for i in ids if i in mine] == mine, "用户自己的顺序不动"


# ---------------------------------------------------------------- 网易云 / QQ 音乐下线
def test_the_local_player_launcher_is_gone():
    with pytest.raises(ImportError):
        importlib.import_module("pet.music_players")
    for name in ("add_music_open_netease", "add_music_open_qqmusic", "_launch_player_and_play"):
        assert not hasattr(shared, name), name


def test_the_player_path_setting_is_dropped_from_old_configs(tmp_path):
    import json

    from pet.config import APP_DIR_NAME

    path = tmp_path / APP_DIR_NAME / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "version": 4, "music_player_paths": {"netease": "D:/CloudMusic/cloudmusic.exe"},
        "music_lyric_enabled": True}), encoding="utf-8")
    config = Config(base=tmp_path)
    assert config.data["music_lyric_enabled"] is True, "读到的确实是这份旧配置；歌词功能的配置照旧"
    assert "music_player_paths" not in config.data, "旧配置里的路径加载时就丢掉"
    config.save()
    assert "music_player_paths" not in json.loads(path.read_text(encoding="utf-8"))
    assert "music_player_paths" not in Config(base=tmp_path / "fresh").data


def test_settings_page_no_longer_asks_where_the_players_are(tmp_path, monkeypatch):
    from pet import modern_settings_dialog as settings_mod
    from pet.settings_widgets import SettingRow

    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    dialog = settings_mod.ModernSettingsDialog(Config(base=tmp_path))
    try:
        ids = {row.objectName() for row in dialog.findChildren(SettingRow)}
        for gone in ("music_player_netease", "music_player_qqmusic", "music_player_detect"):
            assert f"settingRow_{gone}" not in ids, gone
        assert "settingRow_music_lyric" in ids, "歌词设置还在"
    finally:
        dialog.reject()
        app.processEvents()


def test_the_browser_lyric_switch_names_youtube_music_as_its_example(tmp_path, monkeypatch):
    from pet import modern_settings_dialog as settings_mod
    from pet.settings_widgets import SettingRow

    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    if not settings_mod.settings_music.browser_media_supported():
        pytest.skip("浏览器媒体会话开关只在 Windows 上有")
    dialog = settings_mod.ModernSettingsDialog(Config(base=tmp_path))
    try:
        row = dialog.findChild(SettingRow, "settingRow_music_browser_media")
        assert row is not None
        texts = " ".join(label.text() for label in row.findChildren(settings_mod.QLabel))
        assert "YouTube Music" in texts and "网易云" not in texts
    finally:
        dialog.reject()
        app.processEvents()


def test_the_default_menu_template_still_has_no_music_group():
    assert not _ids(menu_layout.load_default_menu_layout()["nodes"]) & {"music", "music_open_netease",
                                                                       "music_open_qqmusic"}
