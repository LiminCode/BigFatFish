# -*- coding: utf-8 -*-
"""右键菜单两条入口：「Claude Desktop」与「Claude Code（WSL）」。

用户 2026-10-15 的决定：肥鱼自己的聊天只有个人 key 加两类只读工具，想随时一键拉起「全功能」的
Claude——商店版 Claude Desktop，以及 WSL 里登录着另一个账号的 Claude Code。两条只进右键菜单
（新式 / 旧式都有），WSL 那条在家目录开一个新会话；没装的那条置灰而不是消失。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMenu

from pet import claude_launchers, menu_layout
from pet.context_menu import load_menu_template
from pet.context_menus import build_legacy_menu, registry, shared
from tests.test_menu_music_entries_removed import _LegacyHost
from tests.test_sprite_menu_parity import _make_overlay
from tests.test_youtube_music import _action

app = QApplication.instance() or QApplication([])

STORE_TARGET = r"shell:AppsFolder\Claude_pzs8sxrjxfjjc!Claude"
WT = r"C:\Users\me\AppData\Local\Microsoft\WindowsApps\wt.exe"
WSL = r"C:\Windows\System32\wsl.exe"
INNER = [WSL, "-d", "Ubuntu-24.04", "--cd", "~", "--", "bash", "-lic", "claude; exec bash"]


# ---------------------------------------------------------------- 找 Claude Desktop
def test_the_classic_installer_exe_wins_over_the_store_package(tmp_path, monkeypatch):
    exe = tmp_path / "AnthropicClaude" / "claude.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    target = claude_launchers.claude_desktop_target(
        enumerate_packages=lambda: ["Claude_2.37337.1.0_x64__pzs8sxrjxfjjc"])
    assert target == str(exe)


def test_the_store_package_becomes_an_apps_folder_target(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    packages = ["Microsoft.WindowsTerminal_1.21.0.0_x64__8wekyb3d8bbwe",
                "ClaudeNot_1.0.0.0_x64__zzzz",
                "Claude_2.37337.1.0_x64__pzs8sxrjxfjjc"]
    assert claude_launchers.claude_desktop_target(enumerate_packages=lambda: packages) == STORE_TARGET


def test_nothing_installed_means_an_empty_target(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert claude_launchers.claude_desktop_target(enumerate_packages=lambda: []) == ""
    assert claude_launchers.claude_desktop_target(enumerate_packages=lambda: ["Claude_broken"]) == ""


# ---------------------------------------------------------------- WSL 里起 claude 的命令行
def test_windows_terminal_opens_a_login_shell_in_the_home_directory():
    argv = claude_launchers.wsl_claude_argv(which={"wt": WT}.get, wsl=WSL, distro="Ubuntu-24.04")
    assert argv == [WT, *INNER]


def test_without_windows_terminal_a_console_window_is_opened():
    argv = claude_launchers.wsl_claude_argv(which=lambda name: None, wsl=WSL, distro="Ubuntu-24.04")
    assert argv == ["cmd", "/c", "start", "", *INNER]


def test_without_a_distro_name_the_default_distro_is_used():
    argv = claude_launchers.wsl_claude_argv(which={"wt": WT}.get, wsl=WSL, distro="")
    assert argv == [WT, WSL, "--cd", "~", "--", "bash", "-lic", "claude; exec bash"]


def test_without_wsl_there_is_no_command():
    assert claude_launchers.wsl_claude_argv(which={"wt": WT}.get, wsl="", distro="Ubuntu-24.04") is None


# ---------------------------------------------------------------- 菜单
@pytest.fixture
def installed(monkeypatch):
    """系统边界：两个程序都「装着」，启动只记参数、不真的拉起。"""
    launched: list[object] = []
    monkeypatch.setattr(claude_launchers, "claude_desktop_target", lambda: STORE_TARGET)
    monkeypatch.setattr(claude_launchers, "launch_claude_desktop",
                        lambda target: (launched.append(target), True)[1])
    monkeypatch.setattr(claude_launchers, "wsl_claude_argv", lambda: [WT, *INNER])
    monkeypatch.setattr(claude_launchers, "launch_wsl_claude",
                        lambda argv: (launched.append(list(argv)), True)[1])
    return launched


@pytest.fixture
def missing(monkeypatch):
    monkeypatch.setattr(claude_launchers, "claude_desktop_target", lambda: "")
    monkeypatch.setattr(claude_launchers, "wsl_claude_argv", lambda: None)


def test_default_template_lists_both_right_after_youtube_music():
    ids = [node.get("id") for node in menu_layout.load_default_menu_layout()["nodes"]]
    base = ids.index("youtube_music")
    assert ids[base + 1:base + 3] == ["claude_desktop", "wsl_claude_code"]
    assert registry.ACTION_LABELS["claude_desktop"] == "Claude Desktop"
    assert registry.ACTION_LABELS["wsl_claude_code"] == "Claude Code（WSL）"
    assert registry.ACTION_ICONS["claude_desktop"] == "sparkle"
    assert registry.ACTION_ICONS["wsl_claude_code"] == "ubuntu"


def _overlay_menu(tmp_path, monkeypatch, template):
    import pet.autostart as autostart_mod
    import pet.catalog as catalog_mod
    from pet.sprite_menu_facade import build_sprite_full_menu

    monkeypatch.setattr(autostart_mod, "is_enabled", lambda: False)
    monkeypatch.setattr(catalog_mod, "list_available_characters", lambda: ["shenshen"])
    shell, _instance, _config = _make_overlay(tmp_path, template=template)
    menu = build_sprite_full_menu(shell)
    shell.keep_alive = menu
    return shell, menu


@pytest.mark.parametrize("template", ["modern", "legacy"])
def test_clicking_launches_the_right_program(tmp_path, monkeypatch, installed, template):
    shell, menu = _overlay_menu(tmp_path, monkeypatch, template)
    try:
        desktop = _action(menu, "Claude Desktop")
        wsl = _action(menu, "Claude Code（WSL）")
        assert desktop is not None and desktop.isEnabled(), f"{template} 菜单里要有「Claude Desktop」"
        assert wsl is not None and wsl.isEnabled(), f"{template} 菜单里要有「Claude Code（WSL）」"
        desktop.trigger()
        wsl.trigger()
        assert installed == [STORE_TARGET, [WT, *INNER]]
    finally:
        shell._delete_runtime_marker()


@pytest.mark.parametrize("template", ["modern", "legacy"])
def test_entries_are_greyed_out_when_nothing_is_installed(tmp_path, monkeypatch, missing, template):
    shell, menu = _overlay_menu(tmp_path, monkeypatch, template)
    try:
        for label in ("Claude Desktop", "Claude Code（WSL）"):
            action = _action(menu, label)
            assert action is not None, f"{template}：没装也要留着条目（置灰），不是消失"
            assert not action.isEnabled()
            assert action.toolTip(), "置灰要说明为什么"
    finally:
        shell._delete_runtime_marker()


def test_a_failed_launch_tells_the_user_in_a_bubble(tmp_path, monkeypatch):
    monkeypatch.setattr(claude_launchers, "claude_desktop_target", lambda: STORE_TARGET)
    monkeypatch.setattr(claude_launchers, "launch_claude_desktop", lambda target: False)
    monkeypatch.setattr(claude_launchers, "wsl_claude_argv", lambda: [WT, *INNER])
    monkeypatch.setattr(claude_launchers, "launch_wsl_claude", lambda argv: False)
    shell, menu = _overlay_menu(tmp_path, monkeypatch, "modern")
    said: list[str] = []
    monkeypatch.setattr(shell, "show_bubble", lambda text, *a, **k: said.append(text))
    try:
        _action(menu, "Claude Desktop").trigger()
        _action(menu, "Claude Code（WSL）").trigger()
        assert len(said) == 2 and all(said)
    finally:
        shell._delete_runtime_marker()


def test_the_old_petwindow_menu_has_them_too(installed):
    menu = QMenu()
    build_legacy_menu(menu, _LegacyHost(), load_menu_template("legacy"))
    _action(menu, "Claude Desktop").trigger()
    _action(menu, "Claude Code（WSL）").trigger()
    assert installed == [STORE_TARGET, [WT, *INNER]]


def test_a_saved_menu_layout_picks_them_up_beside_youtube_music():
    registered = set(registry.MENU_ACTIONS.ids)
    saved = {"schema_version": 1, "layout_id": "user", "nodes": [
        {"type": "action", "id": "rally_pets", "visible": True},
        {"type": "action", "id": "youtube_music", "visible": True},
        {"type": "action", "id": "chat", "visible": True},
        {"type": "action", "id": "quit", "visible": True},
    ]}
    result = menu_layout.resolve_menu_layout(saved, registered_actions=registered,
                                             available_actions=registered)
    ids = [node["id"] for node in result.nodes]
    base = ids.index("youtube_music")
    assert ids[base + 1:base + 3] == ["claude_desktop", "wsl_claude_code"]
    mine = ["rally_pets", "youtube_music", "chat", "quit"]
    assert [i for i in ids if i in mine] == mine, "用户自己的顺序不动"
