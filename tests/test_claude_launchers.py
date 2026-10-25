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
#: 新会话开在已经信任过的 ``~/workspace``，不是整个家目录（用户 2026-10-15 的决定）
INNER = [WSL, "-d", "Ubuntu-24.04", "--cd", "~/workspace", "--", "bash", "-lic"]
SCRIPT = "claude; exec bash"
#: wt 把 ``;`` 当子命令分隔符（哪怕在引号里），交给它的脚本要写成 ``\;``
WT_SCRIPT = "claude\\; exec bash"


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
def test_windows_terminal_opens_a_login_shell_in_the_trusted_workspace_folder():
    argv = claude_launchers.wsl_claude_argv(which={"wt": WT}.get, wsl=WSL, distro="Ubuntu-24.04")
    assert argv == [WT, "-w", "new", *INNER, WT_SCRIPT]


def test_without_windows_terminal_a_console_window_is_opened():
    argv = claude_launchers.wsl_claude_argv(which=lambda name: None, wsl=WSL, distro="Ubuntu-24.04")
    assert argv == ["cmd", "/c", "start", "", *INNER, SCRIPT], "不经 wt 的那条不能转义"


def test_without_a_distro_name_the_default_distro_is_used():
    argv = claude_launchers.wsl_claude_argv(which={"wt": WT}.get, wsl=WSL, distro="")
    assert argv == [WT, "-w", "new", WSL, "--cd", "~/workspace", "--", "bash", "-lic", WT_SCRIPT]


def test_the_semicolon_is_escaped_only_on_the_windows_terminal_path():
    """2026-10-15 实机截图：wt 把 ``claude; exec bash`` 劈成两个标签，第二个拿着 ``exec bash``
    报 0x80070002。``\\;`` 经 wt 还原成 ``;``；``cmd /c start`` 不经 wt，照原样。"""
    assert claude_launchers.wt_script("claude; exec bash") == "claude\\; exec bash"
    via_wt = claude_launchers.wsl_claude_argv(which={"wt": WT}.get, wsl=WSL, distro="")[-1]
    via_cmd = claude_launchers.wsl_claude_argv(which=lambda name: None, wsl=WSL, distro="")[-1]
    assert ";" not in via_wt.replace("\\;", ""), "交给 wt 的脚本里不能剩下裸分号"
    assert via_cmd == SCRIPT


def test_without_wsl_there_is_no_command():
    assert claude_launchers.wsl_claude_argv(which={"wt": WT}.get, wsl="", distro="Ubuntu-24.04") is None


# ---------------------------------------------------------------- 新窗口摆到主屏左半边
WORK_AREA = (0, 0, 3840, 1540)


def test_the_left_half_keeps_the_full_working_height():
    assert claude_launchers.left_half(WORK_AREA) == (0, 0, 1920, 1540)
    assert claude_launchers.left_half((-1920, 40, 1920, 1000)) == (-1920, 40, 960, 1000)


class _Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class _Desktop:
    """假桌面：窗口何时出现、何时显示、摆了之后终端会不会改回去。"""

    def __init__(self, appear_after: int = 2, show_after: int = 3, revert_times: int = 0):
        self.polls = 0
        self.appear_after, self.show_after = appear_after, show_after
        self.revert_times = revert_times
        self.rects: dict[int, tuple] = {1: (242, 250, 1294, 755), 2: (0, 0, 10, 10)}
        self.moved: list[tuple[int, tuple]] = []

    def windows(self):
        self.polls += 1
        return {1, 2, 3} if self.polls >= self.appear_after else {1, 2}

    def visible(self, hwnd):
        return hwnd != 3 or self.polls >= self.show_after

    def move(self, hwnd, rect):
        self.moved.append((hwnd, rect))
        if self.revert_times > 0:
            self.revert_times -= 1
            self.rects[hwnd] = (55, 64, 2039, 2280)   # 终端显示时又套了一次自己的尺寸
        else:
            self.rects[hwnd] = rect
        return True

    def rect_of(self, hwnd):
        return self.rects.get(hwnd)


def _fit(desktop: _Desktop, clock: _Clock, **kw):
    return claude_launchers.fit_new_window(
        {1, 2}, windows=desktop.windows, visible=desktop.visible, rect_of=desktop.rect_of,
        work_area=lambda: WORK_AREA, move=desktop.move, sleep=clock.sleep, clock=clock, **kw)


def test_the_first_new_terminal_window_is_moved_to_the_left_half_once_it_is_shown():
    """2026-10-15 用户反馈：wt 自己开出来的窗口 2039×2280，比 1540 高的工作区还高。
    显示前摆的位置会被终端显示时盖掉，所以等它显示了再摆。"""
    desktop, clock = _Desktop(appear_after=2, show_after=3), _Clock()
    assert _fit(desktop, clock)
    assert desktop.moved == [(3, (0, 0, 1920, 1540))]
    assert desktop.polls == 3, "第 2 次轮询就枚举到了，但没显示，不摆"
    assert clock.now == pytest.approx(100.0 + 2 * claude_launchers.FIT_INTERVAL_S + claude_launchers.FIT_SETTLE_S)


def test_when_the_terminal_resizes_it_back_the_move_is_applied_again():
    desktop, clock = _Desktop(appear_after=1, show_after=1, revert_times=1), _Clock()
    assert _fit(desktop, clock)
    assert [hwnd for hwnd, _ in desktop.moved] == [3, 3] and desktop.rect_of(3) == (0, 0, 1920, 1540)


def test_after_the_last_attempt_it_stops_fighting_the_terminal():
    desktop, clock = _Desktop(appear_after=1, show_after=1, revert_times=99), _Clock()
    assert not _fit(desktop, clock)
    assert len(desktop.moved) == claude_launchers.FIT_ATTEMPTS


def test_when_no_window_shows_up_it_gives_up_quietly():
    desktop, clock = _Desktop(appear_after=10_000, show_after=10_000), _Clock()
    assert not _fit(desktop, clock, timeout=1.0)
    assert desktop.moved == [] and clock.now >= 101.0


def test_without_a_work_area_nothing_is_moved():
    desktop = _Desktop(appear_after=1, show_after=1)
    assert not claude_launchers.fit_new_window({1, 2}, windows=desktop.windows, visible=desktop.visible,
                                               rect_of=desktop.rect_of, work_area=lambda: None,
                                               move=desktop.move, sleep=lambda s: None)
    assert desktop.moved == []


def test_launching_through_windows_terminal_fits_the_window_in_the_background():
    import threading

    done = threading.Event()
    fitted: list[set] = []
    popened: list[list[str]] = []

    def fit(before):
        fitted.append(set(before))
        done.set()
        return True

    argv = [WT, "-w", "new", *INNER, WT_SCRIPT]
    assert claude_launchers.launch_wsl_claude(argv, popen=lambda a, **k: popened.append(list(a)), fit=fit)
    assert done.wait(5.0), "摆位要在后台线程里跑，不能卡住菜单"
    assert popened == [argv] and len(fitted) == 1


def test_the_console_fallback_is_not_fitted():
    fitted: list = []
    argv = ["cmd", "/c", "start", "", *INNER, SCRIPT]
    assert claude_launchers.launch_wsl_claude(argv, popen=lambda a, **k: None, fit=lambda b: fitted.append(b))
    assert fitted == [], "cmd 开的控制台不是 Windows Terminal，不去找它的窗口"


def test_a_failed_popen_reports_false_and_does_not_fit():
    fitted: list = []

    def boom(*_a, **_k):
        raise OSError("nope")

    argv = [WT, "-w", "new", *INNER, WT_SCRIPT]
    assert not claude_launchers.launch_wsl_claude(argv, popen=boom, fit=lambda b: fitted.append(b))
    assert fitted == []


# ---------------------------------------------------------------- 菜单
@pytest.fixture
def installed(monkeypatch):
    """系统边界：两个程序都「装着」，启动只记参数、不真的拉起。"""
    launched: list[object] = []
    monkeypatch.setattr(claude_launchers, "claude_desktop_target", lambda: STORE_TARGET)
    monkeypatch.setattr(claude_launchers, "launch_claude_desktop",
                        lambda target: (launched.append(target), True)[1])
    monkeypatch.setattr(claude_launchers, "wsl_claude_argv", lambda: [WT, "-w", "new", *INNER, WT_SCRIPT])
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
        assert installed == [STORE_TARGET, [WT, "-w", "new", *INNER, WT_SCRIPT]]
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
    monkeypatch.setattr(claude_launchers, "wsl_claude_argv", lambda: [WT, "-w", "new", *INNER, WT_SCRIPT])
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
    assert installed == [STORE_TARGET, [WT, "-w", "new", *INNER, WT_SCRIPT]]


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
