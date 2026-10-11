# -*- coding: utf-8 -*-
"""护驾（主肥鱼右键菜单）：所有小肥鱼围到主肥鱼身边。

壳层接线：``OverlayShell.rally_pets`` 算落点 → ``SpriteRallyWorld`` 送过去；途中播
拖拽悬空动画、不参与碰撞，落地互不重叠。纯落点与飞行逻辑见 test_sprite_rally.py。
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

import tests.test_sprite_menu_facade as fac
from pet.context_menus.registry import ACTION_LABELS, MENU_ACTIONS
from pet.pet_sprite import INTERACTION_DRAG, INTERACTION_NORMAL
from pet.sprite_menu_facade import SpriteMenuFacade, build_sprite_full_menu
from pet.sprite_rally import SpriteRallyWorld
from tests.test_overlay_spawn import _make_persistent_shell

app = QApplication.instance() or QApplication([])

_DT = 1 / 60
_HANG = "被鼠标拖拽悬空反馈"


@pytest.fixture
def shell(tmp_path):
    shell, made = _make_persistent_shell(tmp_path, {"scale": 0.85})
    try:
        # 主肥鱼钉在原地：否则随机游走会让落点跟着它跑，断言没法写死
        shell.behavior.hold(shell.sprite, ("act1",))
        yield shell
    finally:
        shell._delete_runtime_marker()


def _give_hang_clip(shell, sprite) -> None:
    """替身素材库默认没有拖拽素材：补上，才看得出切的是哪一段。"""
    lib = sprite.library
    lib.drag = _HANG
    lib._clips[_HANG] = fac.FakeClip(_HANG, 24)
    shell.behavior._cats_cache.pop(lib, None)


def _small_fish(shell, *, session: int = 4, manual: int = 2) -> list:
    for _ in range(session):
        assert shell.spawn_session_pet() is not None
    for _ in range(manual):
        shell.spawn_pet()
    fish = list(shell._spawned)
    for sprite in fish:
        _give_hang_clip(shell, sprite)
    return fish


def _scatter(shell, fish) -> None:
    """把小肥鱼撒到屏幕各处（含互相压着的两只）。"""
    spots = [(40, 60), (1500, 80), (60, 700), (1700, 500), (900, 40), (905, 45), (300, 300), (1200, 200)]
    for sprite, (x, y) in zip(fish, spots):
        sprite.set_pos(QPointF(x, y))


def _fly(shell, seconds: float = SpriteRallyWorld.MAX_DURATION_S + 0.2) -> None:
    for _ in range(int(seconds / _DT) + 1):
        shell.driver.tick_sim(_DT)


def _gap(a, b) -> int:
    """两个身体框之间的间隙（负数 = 重叠）。"""
    dx = max(a.left() - b.right() - 1, b.left() - a.right() - 1)
    dy = max(a.top() - b.bottom() - 1, b.top() - a.bottom() - 1)
    return max(dx, dy)


# ---------------------------------------------------------------- 出发

def test_rally_sends_every_small_fish_dangling_and_leaves_the_main_fish_alone(shell):
    fish = _small_fish(shell)
    _scatter(shell, fish)
    main_pos = QPointF(shell.sprite.pos)

    assert shell.rally_pets() == len(fish) == 6

    for sprite in fish:
        assert sprite.interaction_state == INTERACTION_DRAG
        assert sprite.collision_suspended is True
        assert shell.behavior.state_of(sprite) == "drag"
        assert shell.behavior.anim_of(sprite) == _HANG, "立刻切到拖拽悬空动画，不等下一 tick"
    assert shell.sprite.interaction_state == INTERACTION_NORMAL
    assert shell.sprite.pos == main_pos


def test_rally_with_no_small_fish_does_nothing(shell):
    assert shell.rally_pets() == 0
    assert not shell._rally.active()


# ---------------------------------------------------------------- 途中与落地

def test_nobody_collides_on_the_way_or_on_arrival(shell):
    fish = _small_fish(shell)
    _scatter(shell, fish)
    hits: list = []
    shell.collision.add_collision_listener(lambda *args: hits.append(args))
    main_pos = QPointF(shell.sprite.pos)

    shell.rally_pets()
    _fly(shell)
    _fly(shell, 0.5)                    # 落地后再跑一会儿：重叠着落地会被碰撞世界推开

    assert hits == [], "途中穿过别的鱼不算撞，落地也不撞"
    assert shell.sprite.pos == main_pos, "主肥鱼没被挤开"


def test_fish_land_around_the_main_fish_without_overlapping(shell):
    fish = _small_fish(shell)
    _scatter(shell, fish)

    shell.rally_pets()
    _fly(shell)

    bodies = [sprite.body_rect() for sprite in fish]
    main = shell.sprite.body_rect()
    assert not shell._rally.active()
    for i, body in enumerate(bodies):
        assert _gap(body, main) >= 8, f"第 {i} 只贴到主肥鱼身上了"
        assert shell._bounds.contains(body), "落点在屏幕可用区内"
        # 「身边」按主肥鱼自己的个头算（替身素材没有身体框，整张画布都是身体）
        assert abs(body.center().x() - main.center().x()) <= 2.5 * main.width()
        assert abs(body.center().y() - main.center().y()) <= 2.5 * main.height()
        for other in bodies[i + 1:]:
            assert _gap(body, other) >= 8, f"{body} 与 {other} 没留够间隙"


def test_landed_fish_get_back_to_what_they_were_doing(shell):
    fish = _small_fish(shell, session=2, manual=1)
    session_fish = [s for s in fish if shell.is_session_pet(s)]
    for sprite in session_fish:
        shell.behavior.hold(sprite, ("act1",))          # 会话小鱼：「工作中」那一组

    shell.rally_pets()
    _fly(shell)

    for sprite in fish:
        assert sprite.interaction_state == INTERACTION_NORMAL
        assert sprite.collision_suspended is False
        assert shell.behavior.state_of(sprite) != "drag", "落地就不再悬空"
    for sprite in session_fish:
        assert shell.behavior.held(sprite) == ("act1",)
        assert shell.behavior.anim_of(sprite) == "act1", "接着播它那一组，不等掷骰"


def test_a_fish_dismissed_mid_flight_is_dropped_cleanly(shell):
    fish = _small_fish(shell, session=2, manual=0)
    _scatter(shell, fish)
    shell.rally_pets()
    shell.driver.tick_sim(_DT)

    shell.remove_session_pet(fish[0])
    _fly(shell)

    assert not shell._rally.active()
    assert fish[1].interaction_state == INTERACTION_NORMAL


# ---------------------------------------------------------------- 菜单

def _labels(menu) -> set:
    found = set()
    for action in menu.actions():
        if action.isSeparator():
            continue
        found.add(action.text())
        if action.menu() is not None:
            found |= _labels(action.menu())
    return found


def _action(menu, text):
    for action in menu.actions():
        if action.text() == text:
            return action
        if action.menu() is not None:
            found = _action(action.menu(), text)
            if found is not None:
                return found
    return None


def test_menu_action_is_registered_as_护驾():
    assert ACTION_LABELS["rally_pets"] == "护驾"
    assert "rally_pets" in MENU_ACTIONS.ids


def test_main_fish_menu_offers_rally_only_when_there_is_someone_to_call(shell):
    facade = SpriteMenuFacade(shell)
    assert "rally_pets" in MENU_ACTIONS.available_ids(facade)
    assert "rally_pets" not in MENU_ACTIONS.enabled_ids(facade), "一只小肥鱼都没有：置灰"

    shell.spawn_session_pet()
    assert "rally_pets" in MENU_ACTIONS.enabled_ids(facade)


def test_small_fish_menus_do_not_offer_rally(shell):
    shell.spawn_pet()
    child = shell._spawned[0]
    assert "rally_pets" not in MENU_ACTIONS.available_ids(SpriteMenuFacade(shell, child))


@pytest.mark.parametrize("template", ["modern", "legacy"])
def test_clicking_护驾_in_the_main_fish_menu_rallies(shell, template):
    shell._config.set("context_menu_template", template)
    fish = _small_fish(shell, session=2, manual=0)

    menu = build_sprite_full_menu(shell)
    shell.keep_alive = menu
    action = _action(menu, "护驾")
    assert action is not None and action.isEnabled(), f"{template} 菜单里要有「护驾」：{sorted(_labels(menu))}"
    action.trigger()

    assert all(shell._rally.active(sprite) for sprite in fish)


def test_modern_menu_puts_护驾_at_the_top_level(shell):
    shell._config.set("context_menu_template", "modern")
    shell.spawn_session_pet()
    menu = build_sprite_full_menu(shell)
    shell.keep_alive = menu
    assert "护驾" in {a.text() for a in menu.actions()}, "右键一眼看得到，不用翻子菜单"
