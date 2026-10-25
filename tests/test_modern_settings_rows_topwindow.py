# -*- coding: utf-8 -*-
"""设置窗的 SettingRow 不许以「顶层窗口」形态闪现（点设置时的无标题小弹窗）。

移植自上游 a8bc79e3（2026-10-13）。用户可见症状：从灵动岛 / 右键菜单 / 托盘任一入口打开
设置，加载期间反复弹出、消失一批无标题小窗口，主设置窗要等约 2 秒才出现。

根因：``SettingRow`` 在**还没有父对象**时被 ``setVisible(True)``。没有父对象的 QWidget
就是顶层窗口（``isWindow()`` 为真），``setVisible(True)`` 于是当场在桌面上开出一个真窗口
（``windowHandle()`` 非空），直到被 ``SettingsCard`` 的布局 reparent 才消失。本仓库里的
触发点是 ``pet/chat/ai_settings_page.py`` 构造期按当前值决定详情行显隐的那几处
（``_update_background_visibility`` / 视觉模型复用 / 知识库行）。

验收口径：监视构造期间**真实到达的 ``QEvent.Show``**——Qt 只在真把控件显示出来时派发它，
因此「一个 ``SettingRow`` 以顶层窗口身份收到 Show」逐字等于用户看到的那个闪烁窗口。
"""
from __future__ import annotations

import os
from contextlib import contextmanager

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication

import pet.modern_settings_dialog as settings_mod
from pet.config import Config
from pet.settings_widgets import SettingRow

app = QApplication.instance() or QApplication([])

#: 设置窗至少这么多行；低于它说明对话框没建起来，用例会变成空跑（假绿）。
_MIN_ROWS = 100


class _ShownAsTopLevelWindow(QObject):
    """记录以顶层窗口身份被显示出来的 ``SettingRow``（= 用户看到的游离小窗）。"""

    def __init__(self) -> None:
        super().__init__()
        #: ``(objectName, 是否已创建原生窗口)``——后者非空即桌面上真多了一个窗口
        self.rows: list[tuple[str, bool]] = []

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt 命名
        if event.type() == QEvent.Type.Show and isinstance(watched, SettingRow):
            if watched.isWindow():
                self.rows.append((watched.objectName(), watched.windowHandle() is not None))
        return False


@contextmanager
def _record_rows_shown_as_windows():
    watcher = _ShownAsTopLevelWindow()
    app.installEventFilter(watcher)
    try:
        yield watcher
    finally:
        app.removeEventFilter(watcher)


def _dialog(tmp_path, monkeypatch, tune=None):
    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    config = Config(base=tmp_path)
    if tune is not None:
        tune(config)
        assert config.save() is True
    with _record_rows_shown_as_windows() as watcher:
        dialog = settings_mod.ModernSettingsDialog(config, include_ai=True)
    return dialog, watcher


def _assert_no_free_window(dialog, watcher) -> None:
    rows = dialog.findChildren(SettingRow)
    assert len(rows) >= _MIN_ROWS, f"设置窗只建出 {len(rows)} 行，用例没覆盖到真实构造路径"
    offenders = [name for name, _handle in watcher.rows]
    assert offenders == [], (
        "构造设置窗期间有 SettingRow 以顶层窗口身份被显示（用户看到的闪烁小窗）："
        f"{offenders}；行的构造点必须传父对象，别让行在无父状态下 setVisible"
    )
    # 构造结束后所有行都应已在控件树里（有父对象）——游离行此时依然会在桌面上开窗
    assert [row.objectName() for row in rows if row.isWindow()] == []


def test_settings_window_construction_shows_no_free_row_window(tmp_path, monkeypatch):
    """默认配置：构造整窗期间一个行的顶层窗口都不许出现。"""
    dialog, watcher = _dialog(tmp_path, monkeypatch)
    try:
        _assert_no_free_window(dialog, watcher)
    finally:
        dialog.deleteLater()


def test_settings_window_with_every_dependent_row_visible_shows_no_free_row_window(
        tmp_path, monkeypatch):
    """依赖项全开：背景选了自定义图、视觉模型不复用、知识库开着时同样不许出现。

    这是真实用户的配置形态——比默认配置多出「背景五行 / 视觉三行 / 知识库行」这条
    动态显隐链，正是构造期 ``setVisible`` 叫得最响的时候。
    """
    def tune(config: Config) -> None:
        config.set("modern_chat_background", "C:/no/such/background.png")
        chat = dict(config.get("chat") or {})
        chat.update(vision_same=False)
        config.set("chat", chat)

    dialog, watcher = _dialog(tmp_path, monkeypatch, tune)
    try:
        assert dialog.ai_page is not None
        assert dialog.ai_page.background_select.currentData() == "custom"
        _assert_no_free_window(dialog, watcher)
    finally:
        dialog.deleteLater()
