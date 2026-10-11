# -*- coding: utf-8 -*-
"""护驾：小肥鱼围到主肥鱼身边（纯落点算法 + 飞行控制器）。

落点全部按**身体框**算——碰撞体就是身体框，落点之间、落点与主肥鱼之间留出间隙，
落地后才不会被碰撞世界当成重叠推开。飞行途中小肥鱼退出碰撞世界、播拖拽悬空
动画，到位再回来。
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPointF

from pet.pet_sprite import INTERACTION_DRAG, INTERACTION_NORMAL
from pet.sprite_rally import SpriteRallyWorld, escort_spots

BOUNDS = (0, 0, 1920, 1040)
ANCHOR = (900, 800, 120, 150)          # 主肥鱼身体框 (x, y, w, h)


def _overlaps(a, b, gap: int = 0) -> bool:
    return (a[0] < b[0] + b[2] + gap and b[0] < a[0] + a[2] + gap
            and a[1] < b[1] + b[3] + gap and b[1] < a[1] + a[3] + gap)


def _rects(sizes, spots):
    return [(s[0], s[1], w, h) for (w, h), s in zip(sizes, spots)]


# ---------------------------------------------------------------- 落点

def test_spots_never_overlap_each_other_or_the_main_fish():
    sizes = [(60, 75)] * 9 + [(120, 150)] * 3      # 会话小鱼（半大）+ 手动生的（等大）
    spots = escort_spots(sizes, ANCHOR, BOUNDS, gap=12)

    assert all(spot is not None for spot in spots)
    rects = _rects(sizes, spots)
    for i, a in enumerate(rects):
        assert not _overlaps(a, ANCHOR, gap=11), f"第 {i} 只贴到主肥鱼身上了：{a}"
        for b in rects[i + 1:]:
            assert not _overlaps(a, b, gap=11), f"{a} 与 {b} 之间没留够间隙"


def test_spots_stay_inside_the_usable_area():
    sizes = [(60, 75)] * 12
    anchor = (1790, 880, 120, 150)                  # 主肥鱼贴在右下角
    for x, y in escort_spots(sizes, anchor, BOUNDS):
        assert 0 <= x and x + 60 <= 1920 and 0 <= y and y + 75 <= 1040


def test_first_escorts_flank_the_main_fish_feet_aligned():
    """头两只一左一右贴着主肥鱼站，脚底对齐——这才叫护驾。"""
    (ax, ay, aw, ah), size = ANCHOR, (60, 75)
    first, second = escort_spots([size, size], ANCHOR, BOUNDS, gap=12)

    assert {first[1], second[1]} == {ay + ah - 75}, "脚底与主肥鱼对齐"
    assert sorted([first[0], second[0]]) == [ax - 12 - 60, ax + aw + 12]


def test_spots_are_near_the_main_fish():
    sizes = [(60, 75)] * 8
    cx, cy = ANCHOR[0] + ANCHOR[2] / 2, ANCHOR[1] + ANCHOR[3] / 2
    for x, y in escort_spots(sizes, ANCHOR, BOUNDS):
        assert abs(x + 30 - cx) <= 400 and abs(y + 37 - cy) <= 400


def test_obstacles_are_avoided():
    """灵动岛这类静态障碍：落点不许压上去（压上去落地就会被弹开）。"""
    island = (ANCHOR[0] + ANCHOR[2] + 4, ANCHOR[1], 200, 150)     # 正挡在主肥鱼右侧
    sizes = [(60, 75)] * 6
    rects = _rects(sizes, escort_spots(sizes, ANCHOR, BOUNDS, obstacles=[island]))
    assert all(not _overlaps(r, island, gap=11) for r in rects)


def test_no_room_gives_none_for_that_fish():
    spots = escort_spots([(60, 75), (60, 75)], (0, 0, 100, 100), (0, 0, 100, 100))
    assert spots == [None, None]


# ---------------------------------------------------------------- 飞行控制器

class _Sprite:
    def __init__(self, x: float, y: float) -> None:
        self.pos = QPointF(x, y)
        self.velocity = QPointF(5, 5)
        self.interaction_state = INTERACTION_NORMAL
        self.collision_suspended = False
        self.dragging = False

    def set_pos(self, pos) -> None:
        self.pos = QPointF(pos)

    def set_velocity(self, velocity) -> None:
        self.velocity = QPointF(velocity)


def _world(**kwargs):
    arrived: list = []
    world = SpriteRallyWorld(on_arrived=arrived.append, **kwargs)
    world.arrived = arrived
    return world


def _run(world, sprites, seconds: float, dt: float = 1 / 60) -> None:
    for _ in range(int(seconds / dt) + 1):
        world.tick(sprites, dt)


def test_takeoff_puts_the_fish_in_the_dangling_pose_out_of_the_collision_world():
    anchor, fish = _Sprite(500, 500), _Sprite(100, 100)
    world = _world()

    world.start(anchor, [(fish, QPointF(60, 0))])

    assert world.active(fish)
    assert fish.interaction_state == INTERACTION_DRAG, "拖拽态 = 行为控制器播拖拽悬空动画"
    assert fish.collision_suspended is True, "飞行途中不撞别的鱼，也不撞岛"
    assert fish.velocity == QPointF(0, 0)
    assert anchor.interaction_state == INTERACTION_NORMAL, "主肥鱼不动"


def test_fish_glides_to_its_spot_and_is_released_there():
    anchor, fish = _Sprite(500, 500), _Sprite(100, 100)
    world = _world()
    world.start(anchor, [(fish, QPointF(60, 0))])

    world.tick([anchor, fish], 1 / 60)
    assert fish.pos != QPointF(100, 100) and fish.pos != QPointF(560, 500), "是飞过去，不是瞬移"
    assert world.arrived == []

    _run(world, [anchor, fish], SpriteRallyWorld.MAX_DURATION_S)

    assert fish.pos == QPointF(560, 500)
    assert fish.interaction_state == INTERACTION_NORMAL
    assert fish.collision_suspended is False
    assert world.arrived == [fish] and not world.active(fish) and not world.active()


def test_flight_never_overshoots_and_only_gets_closer():
    anchor, fish = _Sprite(500, 500), _Sprite(0, 500)
    world = _world()
    world.start(anchor, [(fish, QPointF(60, 0))])
    last = 560.0
    for _ in range(200):
        world.tick([anchor, fish], 1 / 60)
        remaining = 560.0 - fish.pos.x()
        assert -1e-6 <= remaining <= last + 1e-6
        last = remaining


def test_spot_follows_the_main_fish_while_it_moves():
    """主肥鱼飞行途中自己走开了：落点跟着它走，落地照样贴在它身边、不压到它。"""
    anchor, fish = _Sprite(500, 500), _Sprite(100, 100)
    world = _world()
    world.start(anchor, [(fish, QPointF(60, 0))])
    anchor.pos = QPointF(800, 450)

    _run(world, [anchor, fish], SpriteRallyWorld.MAX_DURATION_S)

    assert fish.pos == QPointF(860, 450)


def test_a_fish_grabbed_by_the_user_mid_flight_is_handed_over():
    anchor, fish = _Sprite(500, 500), _Sprite(100, 100)
    world = _world()
    world.start(anchor, [(fish, QPointF(60, 0))])
    world.tick([anchor, fish], 1 / 60)

    fish.dragging = True                       # 用户真的拖住了它
    where = QPointF(fish.pos)
    world.tick([anchor, fish], 1 / 60)

    assert not world.active(fish) and fish.pos == where, "位置归鼠标，不再跟它抢"
    assert fish.collision_suspended is False
    assert fish.interaction_state == INTERACTION_DRAG, "拖拽态归真拖拽，不替它松手"
    assert world.arrived == []


def test_a_fish_that_left_mid_flight_is_forgotten():
    anchor, fish, gone = _Sprite(500, 500), _Sprite(100, 100), _Sprite(0, 0)
    world = _world()
    world.start(anchor, [(fish, QPointF(60, 0)), (gone, QPointF(-80, 0))])

    world.tick([anchor, fish], 1 / 60)          # gone 已不在场（会话结束 / 被退出）
    assert not world.active(gone) and world.active(fish)

    world.forget(fish)                          # sprite-removed 监听
    assert not world.active()


def test_rallying_again_mid_flight_restarts_from_where_the_fish_is():
    anchor, fish = _Sprite(500, 500), _Sprite(100, 100)
    world = _world()
    world.start(anchor, [(fish, QPointF(60, 0))])
    _run(world, [anchor, fish], 0.1)

    world.start(anchor, [(fish, QPointF(-80, 0))])
    _run(world, [anchor, fish], SpriteRallyWorld.MAX_DURATION_S)

    assert fish.pos == QPointF(420, 500)
    assert world.arrived == [fish], "只落地一次"


def test_longer_trips_take_longer_within_limits():
    anchor = _Sprite(500, 500)
    near, far = _Sprite(520, 500), _Sprite(-3000, 500)
    world = _world()
    world.start(anchor, [(near, QPointF(60, 0)), (far, QPointF(-80, 0))])

    _run(world, [anchor, near, far], SpriteRallyWorld.MIN_DURATION_S)
    assert not world.active(near) and world.active(far)

    _run(world, [anchor, near, far], SpriteRallyWorld.MAX_DURATION_S)
    assert not world.active()


def test_idle_world_does_nothing():
    world = _world()
    world.tick([_Sprite(0, 0)], 1 / 60)
    assert not world.active()


@pytest.mark.parametrize("dt", [0.0, 5.0])
def test_odd_frame_times_are_safe(dt):
    anchor, fish = _Sprite(500, 500), _Sprite(100, 100)
    world = _world()
    world.start(anchor, [(fish, QPointF(60, 0))])
    world.tick([anchor, fish], dt)
    assert 100 <= fish.pos.x() <= 560
