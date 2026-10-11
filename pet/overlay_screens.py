# -*- coding: utf-8 -*-
"""跨屏：哪只 sprite 住在哪块屏上。

overlay 拓扑只有一个合成窗，铺满一块屏（下称主屏；通常就是系统主屏）。所有 sprite
共用它的坐标系——这张平面可以延伸到窗口矩形之外：平面上的点 = 全局逻辑坐标 −
合成窗原点，所以别的屏幕在这张平面上各占一块矩形（屏与屏的逻辑坐标不连续，矩形
之间可以隔着空隙）。

一只 sprite 任意时刻只「住」在一块屏上：

- 住在主屏：``home_bounds is None``，边界就是壳的 ``_bounds``（改造前的全部行为）；
- 住在别的屏：``home_bounds`` = 那块屏的可用区在这张平面上的矩形，``home_screen``
  指向那块屏。游走 / 抛掷反弹 / 贴边探头都按它算（``sprite_bounds.bounds_for``），
  那块屏上开一个视口窗把它画出来（``overlay_viewport.OverlayViewport``）。

换屏只发生在拖拽途中：光标到了哪块屏，被拖的那只就改住哪块屏（``on_drag_moved``）。
不同屏上的 sprite 在平面上相隔很远，天然不会互相碰撞；屏与屏之间没有通道，抛出去
的鱼在自己那块屏的边上反弹。

屏幕拓扑变化（插拔 / 分辨率 / 主屏切换）走 ``reconcile``：屏还在就按比例留在原屏，
屏没了（或它成了主屏）就按比例回主屏。
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QGuiApplication

from .overlay_viewport import OverlayViewport

log = logging.getLogger(__name__)


def screen_label(screen) -> str:
    try:
        return str(screen.name())
    except Exception:
        return ""


def native_rect(screen) -> tuple[int, int, int, int]:
    """屏幕在虚拟桌面里的物理像素矩形 ``(左, 上, 右, 下)``（截屏用）。

    Qt 在 Windows 上保留每块屏的原生原点，只把尺寸按缩放换成逻辑值，所以
    原点直接取、宽高乘回 DPR。
    """
    geo = screen.geometry()
    dpr = float(screen.devicePixelRatio() or 1.0)
    width = max(1, int(round(geo.width() * dpr)))
    height = max(1, int(round(geo.height() * dpr)))
    return geo.x(), geo.y(), geo.x() + width, geo.y() + height


class ScreenRouter:
    """sprite ↔ 屏幕的归属表 + 副屏视口的生灭。

    ``screens`` / ``screen_at`` 可注入（测试用假屏，不依赖真实多显示器）。
    """

    def __init__(self, shell, *, screens=None, screen_at=None) -> None:
        self._shell = shell
        self._views: dict = {}  # screen -> OverlayViewport
        self.screens = screens or (lambda: list(QGuiApplication.screens()))
        self.screen_at = screen_at or (lambda point: QGuiApplication.screenAt(point))
        self._prune_scheduled = False

    # ---------------------------------------------------------------- 查询
    def is_foreign(self, sprite) -> bool:
        """是否住在主屏以外的屏上。"""
        return getattr(sprite, "home_bounds", None) is not None

    def screen_of(self, sprite):
        if self.is_foreign(sprite) and sprite.home_screen is not None:
            return sprite.home_screen
        return self._shell._screen

    def bounds_of(self, sprite) -> QRect:
        """该 sprite 的活动边界（合成窗坐标）。"""
        own = getattr(sprite, "home_bounds", None)
        return QRect(self._shell._bounds) if own is None else QRect(own)

    def name_of(self, sprite) -> str | None:
        """持久化用的屏名；住在主屏 = ``None``（重启后跟着主屏走）。"""
        if not self.is_foreign(sprite):
            return None
        return screen_label(sprite.home_screen) or None

    def find(self, name):
        """按名字找一块**非主屏**的在线屏幕；没有 / 就是主屏 → ``None``。"""
        if not name:
            return None
        for screen in self._other_screens():
            if screen_label(screen) == str(name):
                return screen
        return None

    def home_bounds(self, screen) -> QRect:
        """``screen`` 的可用区在合成窗坐标系里的矩形。"""
        origin = self._shell.overlay.geometry().topLeft()
        return QRect(screen.availableGeometry()).translated(-origin)

    @property
    def viewports(self) -> dict:
        return dict(self._views)

    def _other_screens(self) -> list:
        """主屏以外的在线屏幕。主屏自己不在在线清单里（壳被注入了一块清单外的
        屏）时视为单屏：没有可靠的屏幕表，不做任何换屏。"""
        main = self._shell._screen
        screens = list(self.screens())
        if not any(s is main for s in screens):
            return []
        return [s for s in screens if s is not main]

    def _sprites(self) -> list:
        shell = self._shell
        return [s for s in (shell.sprite, *shell._spawned) if s is not None]

    # ---------------------------------------------------------------- 接线
    def bind(self, overlay) -> None:
        """挂到（新的）合成窗上：拖拽换屏挂点 + 多屏时启用按全局坐标取事件位置。"""
        overlay._drag_moved_cb = self.on_drag_moved
        overlay.cross_screen = bool(self._other_screens())

    def rebind(self, overlay) -> None:
        """合成窗被重建（屏迁移）：旧视口全部作废，按新原点重新安置。"""
        for screen in list(self._views):
            self._drop_view(screen)
        self.bind(overlay)
        self.reconcile()

    # ---------------------------------------------------------------- 换屏
    def on_drag_moved(self, sprite, global_pos) -> None:
        """拖拽途中：光标到了别的屏上 → 被拖的这只改住那块屏。"""
        target = self.screen_at(global_pos)
        if target is None or target is self.screen_of(sprite):
            return
        if target is not self._shell._screen and not any(
                target is s for s in self._other_screens()):
            return
        self.rehome(sprite, target)
        rebase = getattr(sprite, "rebase_drag", None)
        if callable(rebase):
            rebase()

    def rehome(self, sprite, screen) -> None:
        """让 ``sprite`` 住到 ``screen`` 上：换边界（就地钳一次）、换 DPR、备好视口。"""
        shell = self._shell
        if screen is shell._screen:
            sprite.home_bounds = None
            bounds = QRect(shell._bounds)
        else:
            bounds = self.home_bounds(screen)
            sprite.home_bounds = QRect(bounds)
            self._ensure_view(screen)
        sprite.home_screen = screen
        set_dpr = getattr(sprite, "set_dpr", None)
        if callable(set_dpr):
            set_dpr(float(screen.devicePixelRatio()))
        sprite.set_bounds(QRect(bounds))
        self.schedule_prune()
        log.info("overlay: sprite 换屏 -> %s 边界=%s", screen_label(screen),
                 bounds.getRect())

    def reconcile(self, *_args) -> None:
        """屏幕拓扑 / 几何变化后重新安置住在别的屏上的 sprite，并对齐视口。"""
        shell = self._shell
        overlay = shell.overlay
        others = self._other_screens()
        overlay.cross_screen = bool(others)
        for sprite in self._sprites():
            if not self.is_foreign(sprite):
                continue
            old = QRect(sprite.home_bounds)
            screen = sprite.home_screen
            if screen is None or not any(screen is s for s in others):
                self._send_home(sprite)  # 屏没了，或者它现在就是主屏
                continue
            new = self.home_bounds(screen)
            if new != old:
                sprite.home_bounds = QRect(new)
                shell._migrate_sprite_position(old, new, sprite)
        for screen, view in list(self._views.items()):
            if view._host is not overlay:
                self._drop_view(screen)
            else:
                view.sync_geometry()
        for screen in self._occupied():
            self._ensure_view(screen)
        self.prune()  # 空视口在这里收（拖拽进行中会留到拖拽收尾）
        overlay.update()

    def _send_home(self, sprite) -> None:
        """所在屏不可用了：按它在那块屏上的相对位置回主屏。"""
        shell = self._shell
        old = QRect(sprite.home_bounds)
        sprite.home_bounds = None
        sprite.home_screen = shell._screen
        set_dpr = getattr(sprite, "set_dpr", None)
        if callable(set_dpr):
            set_dpr(float(shell._screen.devicePixelRatio()))
        shell._migrate_sprite_position(old, QRect(shell._bounds), sprite)
        log.info("overlay: sprite 所在屏不可用，回主屏")

    def forget_screen(self, screen) -> None:
        """一块副屏被拔掉：住在上面的 sprite 回主屏，它的视口关掉。"""
        for sprite in self._sprites():
            if self.is_foreign(sprite) and sprite.home_screen is screen:
                self._send_home(sprite)
        self._drop_view(screen)
        overlay = self._shell.overlay
        overlay.cross_screen = any(s is not screen for s in self._other_screens())
        overlay.update()

    # ---------------------------------------------------------------- 视口
    def _occupied(self) -> list:
        """有 sprite 住着的非主屏。"""
        result: list = []
        for sprite in self._sprites():
            if self.is_foreign(sprite) and sprite.home_screen is not None:
                if not any(sprite.home_screen is s for s in result):
                    result.append(sprite.home_screen)
        return result

    def _ensure_view(self, screen) -> None:
        if screen in self._views:
            return
        overlay = self._shell.overlay
        view = OverlayViewport(overlay, screen)
        self._views[screen] = view
        for name in ("geometryChanged", "availableGeometryChanged"):
            try:
                getattr(screen, name).connect(self.reconcile)
            except (AttributeError, TypeError, RuntimeError):
                pass  # 测试假屏可以没有这两个信号
        if overlay.isVisible():
            view.show()
        log.info("overlay: 副屏视口已建 %s 几何=%s", screen_label(screen),
                 view.geometry().getRect())

    def _drop_view(self, screen) -> None:
        view = self._views.pop(screen, None)
        if view is None:
            return
        for name in ("geometryChanged", "availableGeometryChanged"):
            try:
                getattr(screen, name).disconnect(self.reconcile)
            except (AttributeError, TypeError, RuntimeError):
                pass
        try:
            view.close()
            view.deleteLater()
        except RuntimeError:
            pass  # 宿主关闭时已连带销毁
        log.info("overlay: 副屏视口已关")

    def schedule_prune(self) -> None:
        """稍后关掉没有 sprite 住着的视口（不在当前事件处理器里关窗）。"""
        if self._prune_scheduled:
            return
        self._prune_scheduled = True
        QTimer.singleShot(0, self._shell, self._run_scheduled_prune)

    def _run_scheduled_prune(self) -> None:
        self._prune_scheduled = False
        self.prune()

    def prune(self) -> None:
        """关掉空视口。拖拽进行中不关：按下的那个视口还握着鼠标捕获，关了拖拽
        就断了——拖拽收尾时壳会再排一次（``OverlayShell._on_grab_finished``）。"""
        if getattr(self._shell.overlay, "_mouse_grab", None) is not None:
            return
        occupied = self._occupied()
        for screen in list(self._views):
            if not any(screen is s for s in occupied):
                self._drop_view(screen)

    def set_on_top(self, on: bool) -> None:
        """置顶开关跟随合成窗（改窗口标志会重建原生窗口并先隐藏，故补一次显示）。"""
        for view in self._views.values():
            was_visible = view.isVisible()
            view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(on))
            if was_visible:
                view.show()

    def close(self) -> None:
        for screen in list(self._views):
            self._drop_view(screen)
