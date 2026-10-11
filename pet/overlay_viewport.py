# -*- coding: utf-8 -*-
"""副屏视口：把主合成窗（宿主 overlay）里的 sprite 画到另一块屏幕上。

单合成窗只铺满一块屏；别的屏上要看得到、摸得到鱼，就各开一个视口窗。视口不
拥有任何 sprite，也不推进它们：

- **画**：宿主的 sprite 全在宿主坐标系里（= 全局逻辑坐标 − 宿主原点）；视口按
  自己的原点偏移平移 painter，把落在本屏上的那几只画出来。宿主每次 ``update``
  都会同步到视口（``OverlayWindow.update``）。
- **摸**：鼠标事件换算成宿主坐标后转交给宿主的处理器（按下 / 移动 / 松手 /
  右键菜单）。拖拽 grab、单击判别、弹弓瞄准、壳层回调因此只有宿主那一份，
  从哪块屏按下都走同一条路径。
- **穿透**：Windows 逐像素穿透沿用 ``WindowsPerPixelInputController``，命中判据
  取自宿主（``sprite_at``），所以没点到鱼的地方照样点得到下层应用。

显隐、不透明度、置顶都跟随宿主（``OverlayWindow.add_viewport`` 及其 show/hide/
close 事件），视口自己不做决定。
"""
from __future__ import annotations

import sys

import shiboken6
from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QContextMenuEvent, QMouseEvent, QPainter, QRegion
from PySide6.QtWidgets import QWidget

if sys.platform == "win32":
    from .platform_win import WindowsPerPixelInputController, _set_windows_no_activate


class OverlayViewport(QWidget):
    """宿主 overlay 在另一块屏上的画面与输入面。"""

    def __init__(self, host, screen) -> None:
        super().__init__(None)
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if host.windowFlags() & Qt.WindowType.WindowStaysOnTopHint:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        # 视口常在拖拽途中才被建出来：显示时绝不抢激活（否则可能打断鼠标捕获）
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._host = host
        self._screen = screen
        self._offset = QPoint(0, 0)
        self._input_controller = None
        self.sync_geometry()
        host.add_viewport(self)

    # ---------------------------------------------------------------- 几何
    @property
    def screen_ref(self):
        """本视口所在的屏（``QWidget.screen()`` 在窗口未显示前不可信，故自持）。"""
        return self._screen

    @property
    def offset(self) -> QPoint:
        """本窗左上角在宿主坐标系里的位置。"""
        return QPoint(self._offset)

    def world_rect(self) -> QRect:
        """本窗覆盖的宿主坐标矩形。"""
        return QRect(self._offset, self.size())

    def sync_geometry(self) -> None:
        """按所在屏的几何落位，并重算相对宿主原点的偏移（屏 / 宿主几何变化后调）。"""
        geo = self._screen.geometry()
        if self.geometry() != geo:
            self.setGeometry(geo)
        self._offset = geo.topLeft() - self._host.geometry().topLeft()

    def to_host(self, local) -> QPointF:
        return QPointF(local) + QPointF(self._offset)

    # ---------------------------------------------------------------- 画
    def update_from_host(self, *args) -> None:
        """宿主刷新的同步入口：脏区从宿主坐标平移到本窗坐标。"""
        if not shiboken6.isValid(self):
            return
        if not args:
            self.update()
            return
        region = args[0] if isinstance(args[0], QRegion) else QRegion(*args)
        if not region.boundingRect().intersects(self.world_rect()):
            return  # 绝大多数刷新落在别的屏上：不进 Qt 的区域运算
        self.update(region.translated(-self._offset))

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        host = self._host
        if not shiboken6.isValid(host):
            return
        painter = QPainter(self)
        region = event.region().translated(self._offset)
        painter.translate(-self._offset)
        for sprite in host.sprites:  # 与宿主同一份 z-order
            if not getattr(sprite, "visible", True):
                continue
            if region.intersects(sprite.rect()):
                sprite.paint(painter)
        host._paint_slingshot(painter)
        painter.end()

    # ---------------------------------------------------------------- 摸
    def _host_point(self, event) -> QPointF:
        """事件位置换算到宿主坐标：在本窗内按局部位置，拖出本屏后按全局位置。"""
        local = event.position()
        if self.rect().contains(local.toPoint()):
            return self.to_host(local)
        return event.globalPosition() - QPointF(self._host.geometry().topLeft())

    def _forward_mouse(self, event, handler) -> None:
        point = self._host_point(event)
        origin = QPointF(self._host.geometry().topLeft())
        forwarded = QMouseEvent(event.type(), point, point + origin, event.button(),
                                event.buttons(), event.modifiers())
        handler(forwarded)
        event.setAccepted(forwarded.isAccepted())

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        self._forward_mouse(event, self._host.mousePressEvent)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        self._forward_mouse(event, self._host.mouseMoveEvent)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        self._forward_mouse(event, self._host.mouseReleaseEvent)

    def contextMenuEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        host = self._host
        if host._context_menu_blocked():
            # 弹弓消费掉的右键：宿主靠 event() 拦，这里是直调处理器，得自己判
            event.ignore()
            return
        point = self.to_host(event.pos()).toPoint()
        forwarded = QContextMenuEvent(event.reason(), point, event.globalPos(),
                                      event.modifiers())
        host.contextMenuEvent(forwarded)
        event.setAccepted(forwarded.isAccepted())

    # ---------------------------------------------------------------- 穿透协议
    # WindowsPerPixelInputController 读的三样东西都取自宿主：用户穿透开关、
    # 拖拽进行中（拖拽期间整面不穿透）、光标处有没有 sprite 的不透明像素。
    @property
    def mouse_through(self) -> bool:
        return bool(self._host.mouse_through)

    @property
    def _press_global(self):
        return self._host._press_global

    def _is_transparent_at(self, local) -> bool:
        return self._host._is_transparent_at(self.to_host(local))

    # ---------------------------------------------------------------- 生命周期
    def showEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().showEvent(event)
        if sys.platform == "win32":
            if self._input_controller is None:
                self._input_controller = WindowsPerPixelInputController(self)
            else:
                self._input_controller.resume()
            _set_windows_no_activate(int(self.winId()))

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().hideEvent(event)
        if self._input_controller is not None:
            self._input_controller.stop()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if self._input_controller is not None:
            self._input_controller.stop()
            self._input_controller = None
        if shiboken6.isValid(self._host):
            self._host.remove_viewport(self)
        super().closeEvent(event)
