# -*- coding: utf-8 -*-
"""副屏视口：把主合成窗的 sprite 画到另一块屏上，并把鼠标事件转交回去。

覆盖 ``pet/overlay_viewport.py`` 与 ``OverlayWindow`` 的多屏接缝（``update`` 同步、
``_event_pos``、显隐 / 不透明度跟随）以及四个控制器共用的逐 sprite 边界
（``pet/sprite_bounds.py``）。

纪律：offscreen；假屏只提供几何 / DPR；事件同步直调处理器，不起事件循环、不 sleep。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QContextMenuEvent, QMouseEvent, QRegion
from PySide6.QtWidgets import QApplication

from pet.overlay_viewport import OverlayViewport
from pet.overlay_window import OverlayWindow
from pet.pet_sprite import INTERACTION_THROWN
from pet.sprite_bounds import bounds_for
from pet.sprite_physics import ThrowPhysicsController

app = QApplication.instance() or QApplication([])

RED = QColor(200, 30, 30)


class Screen:
    """假屏：只有几何与 DPR。"""

    def __init__(self, geo, *, dpr=1.0):
        self._geo = QRect(*geo)
        self._dpr = dpr

    def geometry(self):
        return QRect(self._geo)

    def availableGeometry(self):
        return QRect(self._geo)

    def devicePixelRatio(self):
        return self._dpr

    def refreshRate(self):
        return 60.0


class Block:
    """一块不透明色块的假 sprite（协议同 PetSprite 的子集）。"""

    def __init__(self, pos, size=(60, 40)):
        self.pos = QPointF(*pos)
        self._size = size
        self.velocity = QPointF(0, 0)
        self.scale = 1.0
        self.presses, self.moves, self.releases = [], [], []
        self.dragging = False

    def rect(self):
        return QRect(int(self.pos.x()), int(self.pos.y()), *self._size)

    def alpha_at(self, local):
        inside = 0 <= local.x() < self._size[0] and 0 <= local.y() < self._size[1]
        return 255 if inside else 0

    def advance(self, dt):
        return None

    def paint(self, painter):
        painter.fillRect(self.rect(), RED)

    def on_press(self, pos):
        self.presses.append(QPointF(pos))

    def begin_drag(self):
        self.dragging = True

    def on_move(self, pos):
        self.moves.append(QPointF(pos))

    def on_release(self, pos):
        self.releases.append(QPointF(pos))


MAIN = (0, 0, 800, 600)
SIDE = (1000, -200, 600, 900)   # 与主屏之间隔着一段不存在的坐标（真实多屏的常态）


def _pair():
    host = OverlayWindow(Screen(MAIN))
    view = OverlayViewport(host, Screen(SIDE))
    return host, view


def _close(host):
    host.close()
    host.deleteLater()


def _mouse(etype, local, global_pos=None, button=Qt.MouseButton.LeftButton):
    global_pos = local if global_pos is None else global_pos
    buttons = Qt.MouseButton.NoButton if etype == QEvent.Type.MouseButtonRelease else button
    return QMouseEvent(etype, QPointF(*local), QPointF(*global_pos), button, buttons,
                       Qt.KeyboardModifier.NoModifier)


# ---------------------------------------------------------------- 几何与绘制
def test_viewport_covers_its_screen_and_knows_its_offset_in_host_coordinates():
    host, view = _pair()
    try:
        assert view.geometry() == QRect(*SIDE)
        assert view.offset == QPoint(1000, -200)
        assert view.world_rect() == QRect(1000, -200, 600, 900)
        assert host.viewports == [view]
    finally:
        _close(host)


def test_viewport_paints_the_hosts_sprites_that_sit_on_its_screen():
    host, view = _pair()
    try:
        host.add_sprite(Block((1100, 50)))     # 住在副屏：视口局部 (100, 250)
        host.add_sprite(Block((100, 100)))     # 住在主屏：视口里看不到
        image = view.grab().toImage()
        assert image.pixelColor(110, 260) == RED
        assert image.pixelColor(300, 500).alpha() == 0
        assert image.pixelColor(110, 110).alpha() == 0, "主屏上的那只不该画进副屏"
    finally:
        _close(host)


def test_host_update_reaches_the_viewport_translated_and_only_when_it_overlaps():
    host, view = _pair()
    try:
        seen = []
        view.update = lambda *args: seen.append(args)   # 截住视口自己的 QWidget.update
        host.update(QRegion(QRect(1100, 50, 60, 40)))
        assert len(seen) == 1
        assert seen[0][0].boundingRect() == QRect(100, 250, 60, 40)
        host.update(QRegion(QRect(100, 100, 60, 40)))    # 只在主屏上的脏区
        assert len(seen) == 1, "与本屏无交集的刷新不该打扰视口"
        host.update()
        assert seen[-1] == (), "整面刷新照样同步"
    finally:
        _close(host)


# ---------------------------------------------------------------- 鼠标
def test_press_move_release_on_the_viewport_drive_the_hosts_grab_in_host_coordinates():
    host, view = _pair()
    try:
        block = Block((1100, 50))
        host.add_sprite(block)
        press = _mouse(QEvent.Type.MouseButtonPress, (110, 260), (1110, 60))
        view.mousePressEvent(press)
        assert press.isAccepted()
        assert host._mouse_grab is block
        assert block.presses == [QPointF(1110, 60)]

        view.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, (160, 300), (1160, 100)))
        assert block.dragging is True, "过阈值升级为真拖拽"
        assert block.moves == [QPointF(1160, 100)]

        view.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, (160, 300), (1160, 100)))
        assert block.releases == [QPointF(1160, 100)]
        assert host._mouse_grab is None
    finally:
        _close(host)


def test_press_on_empty_part_of_the_viewport_is_ignored():
    host, view = _pair()
    try:
        host.add_sprite(Block((1100, 50)))
        press = _mouse(QEvent.Type.MouseButtonPress, (400, 700), (1400, 500))
        view.mousePressEvent(press)
        assert not press.isAccepted()
        assert host._mouse_grab is None
    finally:
        _close(host)


def test_viewport_click_through_follows_the_hosts_sprites_and_drag_state():
    host, view = _pair()
    try:
        block = Block((1100, 50))
        host.add_sprite(block)
        assert view._is_transparent_at(QPoint(110, 260)) is False
        assert view._is_transparent_at(QPoint(400, 700)) is True
        assert view._press_global is None
        view.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, (110, 260), (1110, 60)))
        assert view._press_global == QPoint(1110, 60), "拖拽进行中：整面不穿透"
        host.mouse_through = True
        assert view.mouse_through is True
    finally:
        _close(host)


def test_drag_that_leaves_the_viewport_is_positioned_by_global_coordinates():
    """拖出本屏后 ``event.position()`` 是按本窗外推的值，不可信：改用全局坐标。"""
    host, view = _pair()
    try:
        block = Block((1100, 50))
        host.add_sprite(block)
        view.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, (110, 260), (1110, 60)))
        # 光标回到主屏 (300, 200)；视口局部位置给一个故意对不上的外推值
        view.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, (-900, 9999), (300, 200)))
        assert block.moves[-1] == QPointF(300, 200)
    finally:
        _close(host)


def test_host_drag_past_its_own_rect_uses_global_coordinates_only_in_cross_screen_mode():
    host, _view = _pair()
    try:
        block = Block((100, 100))
        host.add_sprite(block)
        host.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, (110, 110)))
        host.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, (880, 110), (1100, 300)))
        assert block.moves[-1] == QPointF(880, 110), "未开跨屏：事件位置原样使用"
        host.cross_screen = True
        host.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, (880, 110), (1100, 300)))
        assert block.moves[-1] == QPointF(1100, 300)
        host.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, (400, 300), (9, 9)))
        assert block.moves[-1] == QPointF(400, 300), "光标在本窗内：局部位置为准"
    finally:
        _close(host)


def test_drag_moved_hook_fires_with_the_global_cursor_once_the_drag_is_real():
    host, _view = _pair()
    try:
        block = Block((100, 100))
        host.add_sprite(block)
        calls = []
        host._drag_moved_cb = lambda sprite, point: calls.append((sprite, QPoint(point)))
        host.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, (110, 110)))
        host.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, (111, 110)))
        assert calls == [], "点击候选期（未过阈值）不报"
        host.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, (200, 150), (200, 150)))
        assert calls == [(block, QPoint(200, 150))]
    finally:
        _close(host)


def test_context_menu_on_the_viewport_reaches_the_host_at_host_coordinates():
    class Host(OverlayWindow):
        def contextMenuEvent(self, event):  # noqa: N802
            self.menu_at = (QPoint(event.pos()), QPoint(event.globalPos()))
            event.accept()

    host = Host(Screen(MAIN))
    view = OverlayViewport(host, Screen(SIDE))
    try:
        event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(110, 260),
                                  QPoint(1110, 60))
        view.contextMenuEvent(event)
        assert host.menu_at == (QPoint(1110, 60), QPoint(1110, 60))
    finally:
        _close(host)


# ---------------------------------------------------------------- 跟随宿主
def test_viewport_follows_the_hosts_visibility_opacity_and_lifetime():
    host, view = _pair()
    host.show()
    assert view.isVisible() is True
    host.hide()
    assert view.isVisible() is False
    host.show()
    assert view.isVisible() is True
    host.apply_opacity(40)
    assert abs(view.windowOpacity() - 0.4) < 0.01
    _close(host)
    assert host.viewports == []
    assert view.isVisible() is False


def test_viewport_added_later_picks_up_the_hosts_current_opacity():
    host = OverlayWindow(Screen(MAIN))
    try:
        host.apply_opacity(55)
        view = OverlayViewport(host, Screen(SIDE))
        assert abs(view.windowOpacity() - 0.55) < 0.01
    finally:
        _close(host)


def test_each_sprite_gets_the_dpr_of_the_screen_it_lives_on():
    class Dpr(Block):
        dpr = 0.0
        home_screen = None
        home_bounds = None

        def set_dpr(self, value):
            self.dpr = value

    host = OverlayWindow(Screen(MAIN, dpr=1.25))
    try:
        local, away = Dpr((10, 10)), Dpr((1100, 50))
        away.home_screen, away.home_bounds = Screen(SIDE, dpr=2.0), QRect(*SIDE)
        host.add_sprite(local)
        host.add_sprite(away)
        assert (local.dpr, away.dpr) == (1.25, 2.0)
        local.dpr = away.dpr = 0.0
        host._feed_dpr()
        assert (local.dpr, away.dpr) == (1.25, 2.0)
    finally:
        _close(host)


# ---------------------------------------------------------------- 逐 sprite 边界
def test_bounds_for_prefers_the_sprites_own_screen_and_keeps_the_rect_type():
    class Away:
        home_bounds = QRect(1000, -200, 600, 900)

    assert bounds_for(object(), QRect(0, 0, 800, 600)) == QRect(0, 0, 800, 600)
    assert bounds_for(Away(), QRect(0, 0, 800, 600)) == QRect(1000, -200, 600, 900)
    as_float = bounds_for(Away(), QRectF(0, 0, 800, 600))
    assert isinstance(as_float, QRectF) and as_float == QRectF(1000, -200, 600, 900)


def test_thrown_sprite_bounces_inside_the_screen_it_lives_on():
    block = Block((1300, 100))
    block.home_bounds = QRect(*SIDE)
    block.interaction_state = INTERACTION_THROWN
    block.body_rect = block.rect
    block.set_pos = lambda pos: setattr(block, "pos", QPointF(pos))
    block.set_velocity = lambda v: setattr(block, "velocity", QPointF(v))
    block.velocity = QPointF(-4000.0, 0.0)          # 朝主屏方向猛甩
    physics = ThrowPhysicsController(QRect(*MAIN))
    for _ in range(120):
        physics.tick([block], 0.016)
    assert block.pos.x() >= 1000, "在自己那块屏的左缘反弹，不会被主屏的边界吸过去"
    assert block.pos.x() + 60 <= 1600
