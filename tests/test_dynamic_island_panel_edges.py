# -*- coding: utf-8 -*-
"""灵动岛贴边停靠：被任务栏 / 系统面板占住的那一侧不算屏幕边缘。

此前停靠判定、细条位置、夹屏全部按 ``availableGeometry()``（工作区）算，
任务栏的上沿就成了"屏幕底边"：岛拖到任务栏上方 40px 内就被收成 16px 细条，
用户没法把岛**放在任务栏上面**。修法：只有工作区边与物理屏边重合的那几边
才可停靠（``dockable_edges``），被面板顶进来的边不参与就近判定；启动 /
刷新配置时存着的停靠边若落在这样的边上，按"不停靠"复位并落盘。

本机 Qt offscreen 平台没有任务栏，用假屏驱动真实的选屏 / 夹取 / 停靠代码
（同 ``test_dynamic_island_multiscreen_release.py`` 的假屏思路）。断言只依赖
假屏几何与窗口宽高，不用 sleep。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QGuiApplication, QMouseEvent
from PySide6.QtWidgets import QApplication

from pet.config import Config
from pet.dynamic_island import (
    _DOCK_THRESHOLD,
    _STRIP_THICKNESS,
    DynamicIsland,
    dock_edge_for,
    dockable_edges,
)

SCREEN = QRect(0, 0, 1920, 1080)
TASKBAR = 48
# Windows 底部任务栏：工作区比屏幕矮 48px
WORK_BOTTOM_BAR = QRect(0, 0, 1920, 1080 - TASKBAR)
# 任务栏靠左（Windows 10 允许）：工作区从 x=48 起
WORK_LEFT_BAR = QRect(TASKBAR, 0, 1920 - TASKBAR, 1080)
# 顶部系统栏 + 底部任务栏（macOS 菜单栏 / MyDockFinder 之类）
WORK_TOP_AND_BOTTOM = QRect(0, 24, 1920, 1080 - 24 - TASKBAR)


def _qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


class _FakeScreen:
    """QScreen 的最小替身：岛的选屏 / 夹取 / 停靠只读这两块几何。"""

    def __init__(self, geometry: QRect, available: QRect, name: str = "fake"):
        self._geometry = QRect(geometry)
        self._available = QRect(available)
        self._name = name

    def geometry(self) -> QRect:
        return QRect(self._geometry)

    def availableGeometry(self) -> QRect:
        return QRect(self._available)

    def name(self) -> str:
        return self._name


def _install_screen(monkeypatch, screen: _FakeScreen) -> None:
    monkeypatch.setattr(QGuiApplication, "screenAt", staticmethod(lambda _p: screen))
    monkeypatch.setattr(QGuiApplication, "primaryScreen", staticmethod(lambda: screen))


def _mouse(kind: QEvent.Type, widget, global_pos: QPoint,
           buttons=Qt.MouseButton.LeftButton) -> QMouseEvent:
    return QMouseEvent(kind, QPointF(widget.mapFromGlobal(global_pos)),
                       QPointF(global_pos), Qt.MouseButton.LeftButton,
                       buttons, Qt.KeyboardModifier.NoModifier)


def _drag_to(widget, target_global: QPoint) -> None:
    """完整拖一次：按下 → 移动（超过拖拽阈值）→ 在 target 松手。"""
    start = widget.geometry().center()
    widget.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, widget, start))
    mid = QPoint((start.x() + target_global.x()) // 2,
                 (start.y() + target_global.y()) // 2)
    widget.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, widget, mid))
    widget.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, widget, target_global))
    assert widget._dragging, "拖拽未起手（位移没过阈值）"
    widget.mouseReleaseEvent(
        _mouse(QEvent.Type.MouseButtonRelease, widget, target_global,
               buttons=Qt.MouseButton.NoButton))


def _island(tmp_path: Path, **overrides) -> DynamicIsland:
    cfg = Config(base=tmp_path)
    data = {
        "enabled": True, "show_icon": True, "show_name": True,
        "show_info": True, "info_mode": "time", "custom_text": "",
        "show_status": True, "style": "dark", "x": 800, "y": 500,
    }
    data.update(overrides)
    cfg.set("dynamic_island", data)
    return DynamicIsland(cfg)


# ------------------------------------------------------------ 纯函数
def test_dockable_edges_exclude_panel_sides():
    assert dockable_edges(SCREEN, SCREEN) == frozenset({"top", "bottom", "left", "right"})
    assert dockable_edges(WORK_BOTTOM_BAR, SCREEN) == frozenset({"top", "left", "right"})
    assert dockable_edges(WORK_LEFT_BAR, SCREEN) == frozenset({"top", "bottom", "right"})
    assert dockable_edges(WORK_TOP_AND_BOTTOM, SCREEN) == frozenset({"left", "right"})
    # 没有物理屏几何可比（屏对象缺失）→ 四边都算，保持旧行为
    assert dockable_edges(WORK_BOTTOM_BAR, None) == frozenset({"top", "bottom", "left", "right"})
    # 1~2px 的工作区误差不算面板（自动隐藏任务栏那类保留带不该夺走一条边）
    assert dockable_edges(QRect(0, 0, 1920, 1078), SCREEN) == \
        frozenset({"top", "bottom", "left", "right"})


def test_dock_edge_for_skips_excluded_edges():
    capsule = QRect(900, WORK_BOTTOM_BAR.bottom() - 43, 200, 44)  # 底贴任务栏上沿
    # 旧判定：距工作区底边 0 → bottom
    assert dock_edge_for(capsule, WORK_BOTTOM_BAR) == "bottom"
    # 底边被任务栏占住：不停靠（其余三边都远）
    edges = dockable_edges(WORK_BOTTOM_BAR, SCREEN)
    assert dock_edge_for(capsule, WORK_BOTTOM_BAR, edges=edges) == "none"
    # 同时贴着右边 → 就近落到仍可停靠的 right
    corner = QRect(1920 - 200 - 10, WORK_BOTTOM_BAR.bottom() - 43, 200, 44)
    assert dock_edge_for(corner, WORK_BOTTOM_BAR, edges=edges) == "right"
    # 所有边都不可停靠 → none
    assert dock_edge_for(QRect(0, 0, 200, 44), WORK_BOTTOM_BAR, edges=frozenset()) == "none"
    assert _DOCK_THRESHOLD > 0


# ------------------------------------------------------------ 真实松手路径
def test_drop_onto_the_taskbar_stays_there_without_docking(tmp_path, monkeypatch):
    """底部任务栏：松手时岛有一半压在任务栏上 → 就留在那儿（不推回工作区），也不收细条。"""
    _qapp()
    _install_screen(monkeypatch, _FakeScreen(SCREEN, WORK_BOTTOM_BAR))
    island = _island(tmp_path)
    try:
        island.show()
        # 松手光标在工作区最底一行：岛的中心落在任务栏上沿，下半截盖在任务栏上
        _drag_to(island, QPoint(island.x() + 10, WORK_BOTTOM_BAR.bottom()))
        island._finish_animations()
        state = island._debug_state()
        assert state["mode"] == "normal"
        assert state["dock_edge"] == "none"
        assert island.height() != _STRIP_THICKNESS
        assert WORK_BOTTOM_BAR.bottom() < island.geometry().bottom() <= SCREEN.bottom(), \
            "压在任务栏上的部分不被推回工作区"
        assert island.config.get("dynamic_island")["dock_edge"] == "none"

        # 再往下拖到屏幕最底：夹在物理屏幕内，整个岛盖在任务栏上
        _drag_to(island, QPoint(island.x() + 10, SCREEN.bottom() + 200))
        island._finish_animations()
        assert island.geometry().bottom() == SCREEN.bottom()
        assert island.geometry().top() > WORK_BOTTOM_BAR.bottom(), "整个岛都在任务栏那一条里"
        assert island._debug_state()["dock_edge"] == "none"

        # 顶边没有面板：照常停靠
        _drag_to(island, QPoint(island.x() + 10, WORK_BOTTOM_BAR.top() + 2))
        island._finish_animations()
        state = island._debug_state()
        assert state["mode"] == "docked"
        assert state["dock_edge"] == "top"
        assert island.height() == _STRIP_THICKNESS
    finally:
        island.hide()
        island.deleteLater()


def test_drop_beside_left_taskbar_does_not_dock(tmp_path, monkeypatch):
    _qapp()
    _install_screen(monkeypatch, _FakeScreen(SCREEN, WORK_LEFT_BAR))
    island = _island(tmp_path)
    try:
        island.show()
        _drag_to(island, QPoint(SCREEN.left() - 50, island.y() + 10))
        island._finish_animations()
        state = island._debug_state()
        assert state["mode"] == "normal"
        assert state["dock_edge"] == "none"
        assert island.x() == SCREEN.left(), "夹到物理屏左边，盖在左侧任务栏上"
        # 底边没有面板 → 仍能停靠到 bottom
        _drag_to(island, QPoint(island.x() + 10, WORK_LEFT_BAR.bottom()))
        island._finish_animations()
        assert island._debug_state()["dock_edge"] == "bottom"
    finally:
        island.hide()
        island.deleteLater()


def test_stale_bottom_dock_is_demoted_when_taskbar_occupies_it(tmp_path, monkeypatch):
    """升级前存下的 dock_edge=bottom 落在任务栏那一侧：启动即复位成不停靠并落盘。"""
    _qapp()
    _install_screen(monkeypatch, _FakeScreen(SCREEN, WORK_BOTTOM_BAR))
    island = _island(tmp_path, edge_dock=True, dock_edge="bottom",
                     y=WORK_BOTTOM_BAR.bottom() - _STRIP_THICKNESS + 1)
    try:
        island.show()
        island._finish_animations()
        state = island._debug_state()
        assert state["dock_edge"] == "none"
        assert state["mode"] == "normal"
        assert island.height() != _STRIP_THICKNESS
        assert WORK_BOTTOM_BAR.bottom() < island.geometry().bottom() <= SCREEN.bottom(), \
            "复位后留在任务栏上沿那一带，不被推回工作区"
        assert island.config.get("dynamic_island")["dock_edge"] == "none"
    finally:
        island.hide()
        island.deleteLater()


def test_saved_dock_on_free_edge_still_applies(tmp_path, monkeypatch):
    """对照：存的停靠边没被面板占 → 启动仍按旧行为停靠成细条。"""
    _qapp()
    _install_screen(monkeypatch, _FakeScreen(SCREEN, WORK_BOTTOM_BAR))
    island = _island(tmp_path, edge_dock=True, dock_edge="top", y=0)
    try:
        island.show()
        island._finish_animations()
        state = island._debug_state()
        assert state["dock_edge"] == "top"
        assert state["mode"] == "docked"
        assert island.height() == _STRIP_THICKNESS
    finally:
        island.hide()
        island.deleteLater()
