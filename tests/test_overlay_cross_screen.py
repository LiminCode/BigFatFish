# -*- coding: utf-8 -*-
"""跨屏拖动：任何一只鱼都能拖到任何一块屏幕上，并且「看看屏幕」看的是它所在的那块。

真壳（``OverlayShell``）+ 真 ``PetSprite`` + 假屏（两块，逻辑坐标之间隔着空隙——
真实多显示器的常态）。屏幕表经 ``pet.overlay_screens.QGuiApplication`` 注入，拖拽
按真实入口走（合成窗 / 视口的鼠标处理器）。

纪律：offscreen；事件同步直调，不 sleep；跨线程（识屏 worker）用 Event 等待。
"""
from __future__ import annotations

import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

import tests.test_overlay_window_capabilities as cap
import tests.test_sprite_menu_facade as fac
from pet import overlay_screens, overlay_spawn_state
from pet.overlay_shell import OverlayShell
from pet.pet_sprite import PetSprite

app = QApplication.instance() or QApplication([])

MAIN_GEO = (0, 0, 1000, 600)
SIDE_GEO = (1200, -100, 800, 700)
SIDE_AVAIL = (1200, -100, 800, 660)


class FakeScreen(QObject):
    geometryChanged = Signal(QRect)
    availableGeometryChanged = Signal(QRect)

    def __init__(self, geo, avail, *, name, dpr=1.0):
        super().__init__()
        self._geo, self._avail = QRect(*geo), QRect(*avail)
        self._name, self._dpr = name, float(dpr)

    def geometry(self):
        return QRect(self._geo)

    def availableGeometry(self):
        return QRect(self._avail)

    def devicePixelRatio(self):
        return self._dpr

    def refreshRate(self):
        return 60.0

    def name(self):
        return self._name


class FakeGui:
    """``QGuiApplication`` 的屏幕面替身：在线屏幕表 + 按全局坐标查屏。"""

    def __init__(self, *screens):
        self.online = list(screens)

    def screens(self):
        return list(self.online)

    def screenAt(self, point):  # noqa: N802 (Qt 命名)
        for screen in self.online:
            if screen.geometry().contains(point):
                return screen
        return None


class Instance:
    def __init__(self, config):
        self.config = config

    def _create_library(self, character_id):
        return fac.RichLibrary()


@pytest.fixture
def desk(monkeypatch):
    main = FakeScreen(MAIN_GEO, MAIN_GEO, name="MAIN")
    side = FakeScreen(SIDE_GEO, SIDE_AVAIL, name="SIDE", dpr=2.0)
    gui = FakeGui(main, side)
    monkeypatch.setattr(overlay_screens, "QGuiApplication", gui)
    return main, side, gui


@pytest.fixture
def shells():
    made = []
    yield made
    for shell in made:
        shell.stop()
        shell.overlay.close()


def _shell(tmp_path, screen, shells, values=None):
    config = cap.CapConfig(tmp_path, values)
    shell = OverlayShell(
        app, Instance(config), screen=screen,
        sprite_factory=lambda lib, pos, scale: PetSprite(lib, pos=pos, scale=scale))
    shells.append(shell)
    assert shell.sprite.bind_clip("idle1") is True
    return shell


def _event(etype, point):
    buttons = (Qt.MouseButton.NoButton if etype == QEvent.Type.MouseButtonRelease
               else Qt.MouseButton.LeftButton)
    return QMouseEvent(etype, QPointF(point), QPointF(point), Qt.MouseButton.LeftButton,
                       buttons, Qt.KeyboardModifier.NoModifier)


def _drag(shell, sprite, to, *, release=True):
    """从 sprite 身上按下，把光标拖到全局逻辑坐标 ``to``（合成窗原点 = 全局原点）。"""
    sprite._rebuild_pixmap()   # 命中图在首次绘制时才建；这里没有窗口真的在画
    start = sprite.rect().center()
    overlay = shell.overlay
    overlay.mousePressEvent(_event(QEvent.Type.MouseButtonPress, start))
    assert overlay._mouse_grab is sprite, "前提：按在这只鱼身上"
    overlay.mouseMoveEvent(_event(QEvent.Type.MouseMove, start + QPoint(40, 0)))
    overlay.mouseMoveEvent(_event(QEvent.Type.MouseMove, QPoint(*to)))
    if release:
        overlay.mouseReleaseEvent(_event(QEvent.Type.MouseButtonRelease, QPoint(*to)))


def _inside(sprite, rect: QRect) -> bool:
    return rect.contains(sprite.body_rect())


# ---------------------------------------------------------------- 拖过去 / 拖回来
def test_dragging_a_fish_onto_another_screen_moves_it_there(tmp_path, desk, shells):
    main, side, _gui = desk
    shell = _shell(tmp_path, main, shells)
    sprite = shell.sprite
    assert shell.overlay.cross_screen is True

    _drag(shell, sprite, (1500, 250))

    assert sprite.home_screen is side
    assert sprite.home_bounds == QRect(*SIDE_AVAIL)
    assert _inside(sprite, QRect(*SIDE_AVAIL)), "落在副屏的可用区里，没有被主屏的边界拉回去"
    assert sprite.rect().contains(QPoint(1500, 250)), "鱼就在松手的光标底下"
    assert sprite.dpr == 2.0, "按它所在屏的缩放渲染"
    assert list(shell._screens.viewports) == [side], "副屏上有视口把它画出来"


def test_fish_on_another_screen_stays_there_while_the_world_keeps_ticking(tmp_path, desk, shells):
    main, _side, _gui = desk
    shell = _shell(tmp_path, main, shells)
    sprite = shell.sprite
    _drag(shell, sprite, (1500, 250))
    for _ in range(600):                      # 10 秒的行为 / 碰撞 / 物理 / 探头
        shell.driver.on_tick(1 / 60)
    assert _inside(sprite, QRect(*SIDE_AVAIL))
    shell._sync_geometry()                    # 主屏任务栏变化之类的几何同步
    assert sprite.home_bounds == QRect(*SIDE_AVAIL)
    assert _inside(sprite, QRect(*SIDE_AVAIL)), "主屏的边界更新不许波及住在别的屏上的鱼"


def test_dragging_back_returns_it_to_the_main_screen_and_closes_the_empty_viewport(
        tmp_path, desk, shells):
    main, _side, _gui = desk
    shell = _shell(tmp_path, main, shells)
    sprite = shell.sprite
    _drag(shell, sprite, (1500, 250))

    _drag(shell, sprite, (400, 300), release=False)
    assert sprite.home_bounds is None and sprite.home_screen is main
    shell._screens.prune()
    assert shell._screens.viewports, "拖拽还没松手：视口留着（它可能握着鼠标捕获）"
    shell.overlay.mouseReleaseEvent(_event(QEvent.Type.MouseButtonRelease, QPoint(400, 300)))
    shell._screens.prune()

    assert shell._screens.viewports == {}
    assert _inside(sprite, QRect(*MAIN_GEO))
    assert sprite.dpr == 1.0


def test_crossing_screens_does_not_turn_a_gentle_drop_into_a_throw(tmp_path, desk, shells):
    """屏与屏之间的坐标空隙在轨迹里是一次瞬移，不能被估成甩出的初速。"""
    main, _side, _gui = desk
    shell = _shell(tmp_path, main, shells)
    sprite = shell.sprite
    sprite.drag_physics = True
    _drag(shell, sprite, (1500, 250), release=False)
    assert sprite.drag_trail == [] or len(sprite.drag_trail) == 1
    shell.overlay.mouseReleaseEvent(_event(QEvent.Type.MouseButtonRelease, QPoint(1500, 250)))
    assert sprite.interaction_state == "normal"
    assert (sprite.velocity.x(), sprite.velocity.y()) == (0.0, 0.0)


def test_single_screen_never_rehomes(tmp_path, desk, shells):
    main, _side, gui = desk
    gui.online = [main]
    shell = _shell(tmp_path, main, shells)
    assert shell.overlay.cross_screen is False
    _drag(shell, shell.sprite, (1500, 250))
    assert shell.sprite.home_bounds is None
    assert _inside(shell.sprite, QRect(*MAIN_GEO))
    assert shell._screens.viewports == {}


# ---------------------------------------------------------------- 其它鱼
def test_new_fish_spawn_next_to_the_main_fish_on_its_screen_without_overlap(
        tmp_path, desk, shells):
    main, side, _gui = desk
    shell = _shell(tmp_path, main, shells)
    _drag(shell, shell.sprite, (1500, 250))

    child = shell.spawn_session_pet()

    assert child is not None and child.home_screen is side
    assert _inside(child, QRect(*SIDE_AVAIL))
    assert not child.body_rect().intersects(shell.sprite.body_rect())


def test_a_child_fish_can_live_on_another_screen_while_the_main_fish_stays(
        tmp_path, desk, shells):
    main, side, _gui = desk
    shell = _shell(tmp_path, main, shells)
    child = shell.spawn_session_pet()
    assert child.bind_clip("idle1") is True
    _drag(shell, child, (1600, 300))
    assert child.home_screen is side and shell.sprite.home_bounds is None
    assert _inside(shell.sprite, QRect(*MAIN_GEO))
    shell.remove_session_pet(child)
    shell._screens.prune()
    assert shell._screens.viewports == {}, "副屏上最后一只走了，视口关掉"


# ---------------------------------------------------------------- 持久化
def test_position_is_saved_with_its_screen_and_restored_onto_it(tmp_path, desk, shells):
    main, side, _gui = desk
    shell = _shell(tmp_path, main, shells)
    _drag(shell, shell.sprite, (1500, 250))
    shell.save_position()
    saved = dict(shell._config._values)
    assert saved["screen_name"] == "SIDE"
    center = shell.sprite.body_rect().center()

    again = _shell(tmp_path, main, shells, saved)

    assert again.sprite.home_screen is side
    restored = again.sprite.body_rect().center()
    assert abs(restored.x() - center.x()) <= 2 and abs(restored.y() - center.y()) <= 2


def test_saved_screen_that_is_gone_falls_back_to_the_main_screen(tmp_path, desk, shells):
    main, _side, gui = desk
    gui.online = [main]
    shell = _shell(tmp_path, main, shells, {"rx": 0.5, "ry": 0.5, "screen_name": "SIDE"})
    assert shell.sprite.home_bounds is None
    assert _inside(shell.sprite, QRect(*MAIN_GEO))


def test_coming_back_to_the_main_screen_clears_the_saved_screen(tmp_path, desk, shells):
    main, _side, _gui = desk
    shell = _shell(tmp_path, main, shells)
    _drag(shell, shell.sprite, (1500, 250))
    shell.save_position()
    _drag(shell, shell.sprite, (400, 300))
    shell.save_position()
    assert shell._config._values["screen_name"] is None


def test_slot_geometry_remembers_and_forgets_the_screen(tmp_path):
    assert overlay_spawn_state.write_slot_geometry(
        tmp_path, 3, {"rx": 0.2, "ry": 0.3, "scale": 0.5, "screen_name": "SIDE"})
    assert overlay_spawn_state.read_slot_geometry(tmp_path, 3)["screen_name"] == "SIDE"
    assert overlay_spawn_state.write_slot_geometry(
        tmp_path, 3, {"rx": 0.4, "ry": 0.3, "scale": 0.5, "screen_name": None})
    assert "screen_name" not in overlay_spawn_state.read_slot_geometry(tmp_path, 3)


# ---------------------------------------------------------------- 屏幕拓扑变化
def test_unplugging_the_screen_brings_its_fish_back_to_the_main_screen(tmp_path, desk, shells):
    main, side, gui = desk
    shell = _shell(tmp_path, main, shells)
    _drag(shell, shell.sprite, (1600, 250))     # 副屏正中（横向 1/2）

    shell.handle_screen_removed(side)           # Qt 发信号时这块屏还在在线表里
    gui.online = [main]

    sprite = shell.sprite
    assert sprite.home_bounds is None and sprite.home_screen is main
    assert _inside(sprite, QRect(*MAIN_GEO))
    assert abs(sprite.rect().center().x() - 500) <= 2, "按它在那块屏上的相对位置回来"
    assert shell._screens.viewports == {}
    assert shell.overlay.cross_screen is False


def test_other_screen_geometry_change_keeps_the_fish_at_the_same_relative_spot(
        tmp_path, desk, shells):
    main, side, _gui = desk
    shell = _shell(tmp_path, main, shells)
    _drag(shell, shell.sprite, (1600, 250))
    side._geo = side._avail = QRect(1200, 0, 700, 650)   # 副屏变小并下移
    side.geometryChanged.emit(side.geometry())           # 走视口建立时接的真信号

    sprite = shell.sprite
    assert sprite.home_bounds == QRect(1200, 0, 700, 650)
    assert _inside(sprite, QRect(1200, 0, 700, 650))
    view = shell._screens.viewports[side]
    assert view.geometry() == QRect(1200, 0, 700, 650)


# ---------------------------------------------------------------- 看看屏幕
def test_native_rect_scales_the_size_but_not_the_origin():
    screen = FakeScreen((3840, -995, 1728, 3072), (3840, -995, 1728, 3072),
                        name="G3223Q", dpr=1.25)
    assert overlay_screens.native_rect(screen) == (3840, -995, 6000, 2845)


def test_look_at_screen_captures_the_screen_the_asking_fish_is_on(
        tmp_path, desk, shells, monkeypatch):
    from pet import vision

    main, _side, _gui = desk
    shell = _shell(tmp_path, main, shells)
    _drag(shell, shell.sprite, (1500, 250))
    captured, done = [], threading.Event()
    monkeypatch.setattr(vision, "capture_screen_bytes",
                        lambda rect=None: captured.append(rect) or b"jpeg")
    monkeypatch.setattr(vision, "foreground_app_info", lambda: "")
    monkeypatch.setattr(vision, "ask_about_screen",
                        lambda *args, **kwargs: (done.set(), "看到了")[1])

    class Settings:
        active_config = type("P", (), {"api_key": ""})()
        default_system_prompt = ""

    shell._config.chat_settings = lambda: Settings()
    shell._config.resolve_api_key = lambda provider: "k"
    shell._config.character_display_name = lambda cid: "鱼"

    shell.look_at_screen(shell.sprite)

    assert done.wait(20), "识屏 worker 没有跑到提问"
    deadline = time.monotonic() + 20
    while shell._look_busy and time.monotonic() < deadline:
        app.processEvents()
    assert captured == [(1200, -100, 1200 + 1600, -100 + 1400)], "副屏的物理像素矩形（dpr=2）"


def test_capture_screen_bytes_grabs_only_the_given_rect(monkeypatch):
    from PIL import Image, ImageGrab

    from pet import vision

    calls = []

    def grab(bbox=None, all_screens=False, **_kwargs):
        calls.append((bbox, all_screens))
        return Image.new("RGB", (64, 32), "white")

    monkeypatch.setattr(ImageGrab, "grab", grab)
    monkeypatch.setattr(vision, "_monitor_rect_at", lambda rect: tuple(rect))

    assert vision.capture_screen_bytes((3840, -995, 6000, 2845))[:2] == b"\xff\xd8"
    vision.capture_screen_bytes()

    assert calls == [((3840, -995, 6000, 2845), True), (None, True)]
