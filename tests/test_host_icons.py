# -*- coding: utf-8 -*-
"""会话来源的图标：本机装着的程序（VS Code / PowerShell / wsl.exe）的真图标，没有就用手绘记号。

纪律：不依赖这台机器装了什么——程序在不在、外壳给什么图标都用替身注入；最后一条只断言
真机上「不抛、不空」。
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from pet import host_icons
from pet.context_menus.icons import vector_widget_icon

app = QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _fresh_cache():
    host_icons.clear_cache()
    yield
    host_icons.clear_cache()


def _pixels(icon: QIcon, size: int = 16) -> list:
    image = icon.pixmap(size, size).toImage()
    return [image.pixelColor(x, y).rgba() for y in range(image.height()) for x in range(image.width())]


def _red_square() -> QIcon:
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.fill(QColor("#e03030"))
    return QIcon(pixmap)


def test_the_programs_own_icon_is_used_when_it_is_installed():
    widget = QWidget()
    asked = []

    def provider(path):
        asked.append(path)
        return _red_square()

    icon = host_icons.host_icon(widget, "vscode", 16, executable=lambda kind: r"C:\apps\Code.exe", provider=provider)
    assert asked == [r"C:\apps\Code.exe"]
    centre = icon.pixmap(16, 16).toImage().pixelColor(8, 8)
    assert centre.red() > 180 and centre.green() < 90, "画出来的是程序给的那个图标"


def test_without_the_program_the_hand_drawn_glyph_is_used():
    widget = QWidget()
    icon = host_icons.host_icon(widget, "wsl", 16, executable=lambda kind: "", provider=lambda path: _red_square())
    assert _pixels(icon) == _pixels(vector_widget_icon(widget, "ubuntu", 16))
    assert host_icons.host_icon(widget, "nonsense", 16, executable=lambda kind: "").isNull()


def test_a_failing_shell_lookup_falls_back_too():
    widget = QWidget()

    def boom(path):
        raise OSError("shell said no")

    icon = host_icons.host_icon(widget, "terminal", 16, executable=lambda kind: r"C:\x\pwsh.exe", provider=boom)
    assert _pixels(icon) == _pixels(vector_widget_icon(widget, "terminal", 16))


def test_the_icon_is_fetched_once_per_kind_and_size():
    widget = QWidget()
    calls = []
    provider = lambda path: (calls.append(path), _red_square())[1]  # noqa: E731
    for _ in range(3):
        host_icons.host_icon(widget, "vscode", 16, executable=lambda kind: r"C:\apps\Code.exe", provider=provider)
    host_icons.host_icon(widget, "vscode", 24, executable=lambda kind: r"C:\apps\Code.exe", provider=provider)
    assert len(calls) == 2, "同一种类同一尺寸只问外壳一次"


def test_executables_are_looked_up_in_a_sensible_order(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\U\me\AppData\Local")
    monkeypatch.setenv("ProgramFiles", r"C:\Program Files")
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    monkeypatch.setattr(host_icons.shutil, "which", lambda name: None)

    present = {r"C:\U\me\AppData\Local\Programs\Microsoft VS Code\Code.exe",
               r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
               r"C:\Windows\System32\wsl.exe"}
    exists = lambda path: path in present  # noqa: E731
    assert host_icons.host_executable("vscode", exists=exists).endswith(r"Microsoft VS Code\Code.exe")
    assert host_icons.host_executable("terminal", exists=exists).endswith("powershell.exe"), "没有 pwsh 7 就用系统自带的"
    assert host_icons.host_executable("wsl", exists=exists).endswith("wsl.exe")
    assert host_icons.host_executable("script", exists=exists) == ""

    present.add(r"C:\Program Files\PowerShell\7\pwsh.exe")
    assert host_icons.host_executable("terminal", exists=exists).endswith("pwsh.exe"), "有 7 优先 7"

    monkeypatch.setattr(sys, "platform", "linux")
    assert host_icons.host_executable("vscode", exists=lambda path: True) == ""


def test_warming_fetches_every_kind_once_so_the_first_expand_does_not_pay():
    widget = QWidget()
    calls = []
    provider = lambda path: (calls.append(path), _red_square())[1]  # noqa: E731
    fetched = host_icons.warm(widget, 16, executable=lambda kind: f"C:\\x\\{kind}.exe", provider=provider)
    assert fetched == 5 and len(calls) == 5
    host_icons.host_icon(widget, "vscode", 16, executable=lambda kind: "C:\\x\\vscode.exe", provider=provider)
    assert len(calls) == 5, "预热过了：之后不再问外壳"
    assert host_icons.warm(widget, 16, provider=provider) == 0


def test_the_panel_schedules_the_warm_up(monkeypatch):
    from pet import island_history_panel as panel_mod

    scheduled = []
    monkeypatch.setattr(panel_mod.QTimer, "singleShot", lambda ms, fn: scheduled.append((ms, fn)))
    panel = panel_mod.SessionHistoryPanel()
    try:
        assert [ms for ms, _fn in scheduled] == [panel_mod._ICON_WARM_DELAY_MS]
        warmed = []
        monkeypatch.setattr(host_icons, "warm", lambda widget, size, **kw: warmed.append(size) or 4)
        scheduled[0][1]()
        assert warmed == [16]
    finally:
        panel.deleteLater()


def test_on_this_machine_every_kind_yields_some_icon_without_raising():
    widget = QWidget()
    for kind in ("vscode", "terminal", "wsl", "script"):
        assert not host_icons.host_icon(widget, kind, 16).isNull(), kind
