# -*- coding: utf-8 -*-
"""右键菜单「VS Code 工作区」：开着的、最近用过的、用户目录里的工作区，点一下切过去或打开。

纪律：不读真实的 VS Code 数据目录，不起真的 code 命令，不碰真实窗口。
"""
from __future__ import annotations

import json
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMenu

from pet import claude_session_jump as jump
from pet import vscode_workspaces as vw
from pet.config import Config
from pet.vscode_workspaces import WorkspaceEntry
from tests.test_session_pet_details import shell  # noqa: F401 - shell 是 fixture

app = QApplication.instance() or QApplication([])

NOW = 1_800_000_000.0
UNC = r"\\wsl.localhost\Ubuntu-24.04\home\u\workspace"


def _entry(label, target, **over) -> WorkspaceEntry:
    return WorkspaceEntry(label, target, **{"wsl": target.startswith("/"), "distro": "Ubuntu-24.04" if target.startswith("/") else "", **over})


# ---------------------------------------------------------------- 配置

def test_defaults_and_cleaning(tmp_path):
    assert Config(tmp_path).get(vw.CONFIG_KEY) == {"workspace_dir": "", "menu_limit": 12}
    assert vw.normalize({"workspace_dir": f"  {UNC}  ", "menu_limit": "99"}) == {"workspace_dir": UNC, "menu_limit": 30}
    assert vw.normalize({"menu_limit": "many"})["menu_limit"] == 12
    assert vw.normalize(None)["menu_limit"] == 12


def test_the_setting_survives_a_restart(tmp_path):
    config = Config(tmp_path)
    config.set(vw.CONFIG_KEY, {"workspace_dir": UNC, "menu_limit": 5})
    config.save()
    assert Config(tmp_path).get(vw.CONFIG_KEY) == {"workspace_dir": UNC, "menu_limit": 5}


# ---------------------------------------------------------------- 目录里的工作区文件

def test_a_wsl_unc_directory_is_understood_as_a_folder_inside_the_distro():
    assert vw.parse_directory(UNC) == (True, "Ubuntu-24.04", "/home/u/workspace")
    assert vw.parse_directory(r"\\wsl$\Debian\srv") == (True, "Debian", "/srv")
    assert vw.parse_directory(r"D:\work\spaces") == (False, "", r"D:\work\spaces")
    assert vw.parse_directory("") == (False, "", "")


def test_scanning_lists_only_workspace_files_with_targets_the_code_command_understands():
    names = ["b.code-workspace", "notes.md", "a.code-workspace", "sub", "X.CODE-WORKSPACE"]
    wsl = vw.scan_workspace_dir(UNC, listdir=lambda path: list(names))
    assert [(e.label, e.target, e.wsl, e.distro, e.multi_root) for e in wsl] == [
        ("X", "/home/u/workspace/X.CODE-WORKSPACE", True, "Ubuntu-24.04", True),
        ("a", "/home/u/workspace/a.code-workspace", True, "Ubuntu-24.04", True),
        ("b", "/home/u/workspace/b.code-workspace", True, "Ubuntu-24.04", True)]
    local = vw.scan_workspace_dir(r"D:\work", listdir=lambda path: ["p.code-workspace"])
    assert local[0].target == r"D:\work\p.code-workspace" and not local[0].wsl


def test_an_unreadable_directory_is_simply_empty(tmp_path):
    def boom(path):
        raise OSError("nope")

    assert vw.scan_workspace_dir(UNC, listdir=boom) == []
    assert vw.scan_workspace_dir(str(tmp_path / "missing")) == []
    assert vw.scan_workspace_dir("") == []


# ---------------------------------------------------------------- 最近用过的

def _storage(appdata, wid, meta, age_s, *, editor="Code"):
    folder = appdata / editor / "User" / "workspaceStorage" / wid
    folder.mkdir(parents=True)
    (folder / "workspace.json").write_text(json.dumps(meta), encoding="utf-8")
    (folder / "state.vscdb").write_bytes(b"x")
    stamp = NOW - age_s
    os.utime(folder / "state.vscdb", (stamp, stamp))
    os.utime(folder / "workspace.json", (stamp - 10, stamp - 10))
    return folder


def test_recent_workspaces_come_from_the_state_folders_newest_first(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    local = "file:///" + str(proj).replace("\\", "/").replace(":", "%3A")
    _storage(tmp_path, "a", {"folder": local}, 3600)
    _storage(tmp_path, "b", {"folder": "vscode-remote://wsl%2Bubuntu-24.04/home/u/Github/core"}, 60)
    _storage(tmp_path, "c", {"workspace": {"configPath": "vscode-remote://wsl%2BUbuntu-24.04/home/u/ws/ops.code-workspace"}}, 600)
    _storage(tmp_path, "d", {"folder": "vscode-remote://wsl%2Bubuntu-24.04/home/u/Github/core"}, 7200, editor="Cursor")
    _storage(tmp_path, "gone", {"folder": "file:///c%3A/definitely/not/here"}, 30)
    _storage(tmp_path, "old", {"folder": "vscode-remote://wsl%2Bubuntu-24.04/home/u/ancient"}, vw.RECENT_WINDOW_S + 1)
    _storage(tmp_path, "ssh", {"folder": "vscode-remote://ssh-remote%2Bbox/home/u/x"}, 10)
    (tmp_path / "Code" / "User" / "workspaceStorage" / "junk").mkdir()
    (tmp_path / "Code" / "User" / "workspaceStorage" / "junk" / "workspace.json").write_text("{bad", encoding="utf-8")

    recent = vw.recent_entries(tmp_path, now=NOW)
    assert [(e.label, e.wsl, e.multi_root, e.distro) for e in recent] == [
        ("core", True, False, "ubuntu-24.04"), ("ops", True, True, "Ubuntu-24.04"), ("proj", False, False, "")]
    assert recent[0].last_used == NOW - 60, "同一个文件夹两个编辑器都开过：取最近的那次"
    assert recent[2].target.lower().endswith("/proj")


def test_no_appdata_means_no_recent_list(monkeypatch):
    monkeypatch.delenv("APPDATA", raising=False)
    assert vw.recent_entries(None) == []


# ---------------------------------------------------------------- 合并

def test_open_ones_first_then_by_recency_and_each_workspace_once():
    opened = [_entry("gateway", "/home/u/Github/gateway", open=True, last_used=NOW),
              _entry("BigFatFish", r"c:/Users/me/Github/BigFatFish", open=True, last_used=NOW)]
    recent = [_entry("core", "/home/u/Github/core", last_used=NOW - 10),
              _entry("gateway", "/home/u/Github/gateway", last_used=NOW - 20),
              _entry("ops", "/home/u/ws/ops.code-workspace", multi_root=True, last_used=NOW - 30),
              _entry("bigfatfish", r"C:/Users/me/Github/BigFatFish", last_used=NOW - 40)]
    scanned = [_entry("ops", "/home/u/ws/ops.code-workspace", multi_root=True),
               _entry("deploy", "/home/u/ws/deploy.code-workspace", multi_root=True)]
    listed = vw.list_workspaces({}, opened=opened, recent=recent, scanned=scanned)
    assert [(e.label, e.open) for e in listed] == [
        ("gateway", True), ("BigFatFish", True), ("core", False), ("ops", False), ("deploy", False)]
    assert vw.list_workspaces({"menu_limit": 3}, opened=opened, recent=recent, scanned=scanned)[-1].label == "core"


def test_same_named_entries_are_told_apart_by_parent_folder_or_workspace_marker():
    """实机：三个父目录下各开着一个同名项目，还有一个同名的工作区文件——菜单上不能是四行一样的字。"""
    opened = [_entry("core", "/home/u/Github/core", open=True, last_used=NOW),
              _entry("core", "/home/u/Github-2/core", open=True, last_used=NOW),
              _entry("core", r"C:/work/core", open=True, last_used=NOW)]
    scanned = [_entry("core", "/home/u/ws/core.code-workspace", multi_root=True),
               _entry("other", "/home/u/ws/other.code-workspace", multi_root=True)]
    listed = vw.list_workspaces({}, opened=opened, recent=[], scanned=scanned)
    assert [e.label for e in listed] == ["core · Github", "core · Github-2", "core · work", "core · 工作区", "other"]
    assert listed[0].target == "/home/u/Github/core", "只改显示的名字，路径不动"


def test_an_open_window_learns_its_distro_from_the_recent_record():
    opened = [_entry("core", "/home/u/Github/core", open=True, distro="")]
    recent = [_entry("core", "/home/u/Github/core", distro="Ubuntu-24.04", last_used=NOW)]
    (entry,) = vw.list_workspaces({}, opened=opened, recent=recent, scanned=[])
    assert entry.open and entry.distro == "Ubuntu-24.04"


# ---------------------------------------------------------------- 点一条

WINDOWS = [jump.Window(1, 10, "BigFatFish - a.py", "code.exe"),
           jump.Window(2, 10, "ops (Workspace) [WSL: Ubuntu-24.04] - b.py", "code.exe"),
           jump.Window(3, 10, "core [WSL: Ubuntu-24.04] - c.py", "code.exe"),
           jump.Window(4, 10, "core [WSL: Ubuntu-24.04] - d.py", "code.exe")]


class Desk:
    def __init__(self, focus_ok=True, launch_ok=True):
        self.log = []
        self.kwargs = dict(windows=lambda: list(WINDOWS),
                           focus=lambda hwnd: (self.log.append(("focus", hwnd)), focus_ok)[1],
                           launch=lambda detail, target: (self.log.append(("code", detail.is_wsl, detail.distro, target)), launch_ok)[1])


def test_an_open_workspace_is_brought_to_the_front():
    desk = Desk()
    ok, message = vw.activate(_entry("ops", "/home/u/ws/ops.code-workspace", multi_root=True, open=True), **desk.kwargs)
    assert ok and desk.log == [("focus", 2)] and "ops" in message

    desk = Desk()
    assert vw.activate(_entry("BigFatFish", r"c:/Users/me/Github/BigFatFish", open=True), **desk.kwargs)[0]
    assert desk.log == [("focus", 1)]


def test_when_the_window_cannot_be_told_apart_the_code_command_focuses_it_by_path():
    desk = Desk()
    ok, _ = vw.activate(_entry("core", "/home/u/Github-2/core", open=True), **desk.kwargs)
    assert ok and desk.log == [("code", True, "Ubuntu-24.04", "/home/u/Github-2/core")], "两个同名窗口：不蒙，让 VS Code 按路径去重"


def test_a_closed_workspace_is_opened_with_the_code_command():
    desk = Desk()
    ok, message = vw.activate(_entry("deploy", "/home/u/ws/deploy.code-workspace", multi_root=True), **desk.kwargs)
    assert ok and desk.log == [("code", True, "Ubuntu-24.04", "/home/u/ws/deploy.code-workspace")] and "打开" in message

    desk = Desk()
    assert vw.activate(_entry("p", r"D:\work\p.code-workspace", multi_root=True), **desk.kwargs)[0]
    assert desk.log == [("code", False, "", r"D:\work\p.code-workspace")]


def test_failures_are_reported_in_words():
    desk = Desk(launch_ok=False)
    ok, message = vw.activate(_entry("deploy", "/home/u/ws/deploy.code-workspace"), **desk.kwargs)
    assert not ok and "code 命令" in message
    ok, message = vw.activate(WorkspaceEntry("x", "/home/u/x", wsl=True, distro=""), **Desk().kwargs)
    assert not ok and "发行版" in message


# ---------------------------------------------------------------- 菜单

def _icon_pixels(action) -> list:
    image = action.icon().pixmap(32).toImage()
    return [image.pixelColor(x, y).rgba() for y in range(image.height()) for x in range(image.width())]


def _has_green_badge(action) -> bool:
    """图标右下角那一块有没有绿色（开着的标记）。"""
    image = action.icon().pixmap(32).toImage()
    w, h = image.width(), image.height()
    for y in range(int(h * 0.6), h):
        for x in range(int(w * 0.6), w):
            c = image.pixelColor(x, y)
            if c.alpha() > 128 and c.green() > c.red() + 60 and c.green() > c.blue() + 30:
                return True
    return False


def test_the_two_system_icons_exist_and_differ():
    from pet.context_menus.icons import badged_menu_icon, vector_menu_icon

    menu = QMenu()
    ubuntu, windows = vector_menu_icon(menu, "ubuntu"), vector_menu_icon(menu, "windows")
    assert not ubuntu.isNull() and not windows.isNull()
    assert ubuntu.pixmap(32).toImage() != windows.pixmap(32).toImage()
    plain = windows.pixmap(32).toImage()
    badged = badged_menu_icon(menu, "windows").pixmap(32).toImage()
    assert plain != badged
    bottom_right = badged.pixelColor(int(badged.width() * 0.8), int(badged.height() * 0.8))
    assert bottom_right.green() > bottom_right.red() + 60


def _find(menu: QMenu, text: str):
    for action in menu.actions():
        if action.text() == text:
            return action
        if action.menu() is not None:
            found = _find(action.menu(), text)
            if found is not None:
                return found
    return None


@pytest.fixture
def listed(monkeypatch):
    entries = [_entry("ops", "/home/u/ws/ops.code-workspace", multi_root=True, open=True, last_used=NOW),
               _entry("BigFatFish", r"c:/Users/me/Github/BigFatFish", open=True, last_used=NOW),
               _entry("deploy", "/home/u/ws/deploy.code-workspace", multi_root=True)]
    monkeypatch.setattr(vw, "open_entries", lambda workspaces=None: [e for e in entries if e.open])
    monkeypatch.setattr(vw, "recent_entries", lambda appdata=None, now=None: [])
    monkeypatch.setattr(vw, "scan_workspace_dir", lambda path, listdir=None: [e for e in entries if not e.open])
    return entries


@pytest.mark.parametrize("template", ["modern", "legacy"])
def test_the_main_fish_menu_lists_the_workspaces(shell, listed, template, monkeypatch):  # noqa: F811
    shell._config.set("context_menu_template", template)
    opened = []
    monkeypatch.setattr(vw, "activate", lambda entry, **kw: (opened.append(entry.label), (True, "ok"))[1])
    menu = shell._build_menu_for(shell.sprite)
    entry = _find(menu, "VS Code 工作区")
    assert entry is not None and entry.menu() is not None, template
    actions = [a for a in entry.menu().actions() if not a.isSeparator()]
    labels = [a.text() for a in actions]
    if template == "legacy":
        # 旧版菜单约定无图标：开着的 / WSL 仍靠文字标记
        assert labels == ["● ops [WSL]", "● BigFatFish", "deploy [WSL]"]
    else:
        # 新版：系统图标说明在哪（Ubuntu / Windows），开着的在图标右下角带绿点
        assert labels == ["ops", "BigFatFish", "deploy"]
        assert all(not a.icon().isNull() for a in actions)
        assert _has_green_badge(actions[0]) and _has_green_badge(actions[1]) and not _has_green_badge(actions[2])
        assert _icon_pixels(actions[0]) != _icon_pixels(actions[1]), "WSL 与本机的图标不一样"

    next(a for a in actions if a.text().startswith("deploy")).trigger()
    deadline = time.monotonic() + 5
    while not opened and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)
    assert opened == ["deploy"]


def test_an_empty_list_explains_itself(shell, monkeypatch):  # noqa: F811
    monkeypatch.setattr(vw, "open_entries", lambda workspaces=None: [])
    monkeypatch.setattr(vw, "recent_entries", lambda appdata=None, now=None: [])
    entry = _find(shell._build_menu_for(shell.sprite), "VS Code 工作区")
    (hint,) = [a for a in entry.menu().actions() if not a.isSeparator()]
    assert not hint.isEnabled() and "设置" in hint.text()


def test_the_menu_limit_is_honoured(shell, monkeypatch):  # noqa: F811
    many = [_entry(f"w{i}", f"/home/u/w{i}", last_used=NOW - i) for i in range(20)]
    monkeypatch.setattr(vw, "open_entries", lambda workspaces=None: [])
    monkeypatch.setattr(vw, "recent_entries", lambda appdata=None, now=None: list(many))
    shell._config.set(vw.CONFIG_KEY, {"menu_limit": 4})
    entry = _find(shell._build_menu_for(shell.sprite), "VS Code 工作区")
    assert len([a for a in entry.menu().actions() if not a.isSeparator()]) == 4


# ---------------------------------------------------------------- 设置页

def _dialog(tmp_path, monkeypatch):
    from pet import modern_settings_dialog as settings_mod

    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    config = Config(tmp_path)
    return config, settings_mod, settings_mod.ModernSettingsDialog(config, include_ai=False)


def test_settings_offer_the_directory_and_the_limit_and_persist_them(tmp_path, monkeypatch):
    config, settings_mod, dialog = _dialog(tmp_path, monkeypatch)
    try:
        assert dialog.findChild(settings_mod.SettingRow, "settingRow_vscode_workspace_dir") is not None
        assert dialog.vscode_workspace_dir_picker.text() == "" and dialog.vscode_menu_limit_spin.value() == 12
        dialog.vscode_workspace_dir_picker.setText(f"  {tmp_path}  ")
        dialog.vscode_menu_limit_spin.setValue(7)
        dialog._save()
    finally:
        dialog.deleteLater()
    assert Config(tmp_path).get(vw.CONFIG_KEY) == {"workspace_dir": str(tmp_path), "menu_limit": 7}

    _config, settings_mod, reopened = _dialog(tmp_path, monkeypatch)
    try:
        assert reopened.vscode_workspace_dir_picker.text() == str(tmp_path)
        row = reopened.findChild(settings_mod.SettingRow, "settingRow_vscode_workspace_dir")
        reopened.vscode_workspace_dir_picker.setText(str(tmp_path / "nowhere"))
        assert "打不开" in row.hint_label.text()
    finally:
        reopened.deleteLater()
