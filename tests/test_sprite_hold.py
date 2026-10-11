# -*- coding: utf-8 -*-
"""BehaviorController.hold：让一只 sprite 保持在一组动画上（会话小鱼的「忙 / 休息」）。

``play_once`` 播一遍就回掷骰链；会话小鱼要的是「一直写代码，直到会话收工」。
保持期间不掷骰（所以也不会走开），一次性动作（点击、菜单播放）播完回到保持的那组。
"""

from __future__ import annotations

from pet.sprite_behavior import STATE_ACTS, BehaviorController
from tests.test_sprite_behavior import BOUNDS, ScriptedRng, _make_library, _make_sprite

MOVE_ROLL = 0.85    # 掷骰落在「移动」桶：没被保持住的 sprite 这时会走开


def _scene():
    lib = _make_library(idles=["idle1", "code1", "code2", "nap"])
    sprite = _make_sprite(lib, facing="right")
    controller = BehaviorController(BOUNDS, rng=ScriptedRng(rolls=[MOVE_ROLL] * 50, ints=(100, 0)))
    controller.predict_enabled = False
    return controller, sprite, lib


def _finish_clip(controller, sprite, lib) -> None:
    controller.tick([sprite], lib.duration(controller.anim_of(sprite)) + 0.1)


def test_hold_switches_at_once_and_rotates_through_the_set():
    c, sprite, lib = _scene()

    assert c.hold(sprite, ["code1", "code2"]) is True
    seen = [c.anim_of(sprite)]
    for _ in range(4):
        _finish_clip(c, sprite, lib)
        assert c.state_of(sprite) == STATE_ACTS, "保持期间不掷骰：不会走开，也不回待机"
        seen.append(c.anim_of(sprite))

    assert seen == ["code1", "code2", "code1", "code2", "code1"]
    assert c.held(sprite) == ("code1", "code2")


def test_hold_on_a_single_clip_loops_it():
    c, sprite, lib = _scene()
    c.hold(sprite, ["nap"])
    for _ in range(3):
        _finish_clip(c, sprite, lib)
        assert (c.state_of(sprite), c.anim_of(sprite)) == (STATE_ACTS, "nap")


def test_changing_the_held_set_takes_effect_immediately():
    """会话收工：从「写代码」换到「休息」不等当前这段播完。"""
    c, sprite, lib = _scene()
    c.hold(sprite, ["code1", "code2"])
    c.hold(sprite, ["nap"])
    assert c.anim_of(sprite) == "nap"
    _finish_clip(c, sprite, lib)
    assert c.anim_of(sprite) == "nap"


def test_one_shot_animation_returns_to_the_held_set():
    c, sprite, lib = _scene()
    c.hold(sprite, ["code1"])
    assert c.play_once(sprite, "idle1") is True
    _finish_clip(c, sprite, lib)
    assert (c.state_of(sprite), c.anim_of(sprite)) == (STATE_ACTS, "code1")


def test_releasing_the_hold_hands_back_to_the_dice_chain():
    c, sprite, lib = _scene()
    c.hold(sprite, ["code1"])
    assert c.hold(sprite, ()) is False
    assert c.held(sprite) == ()
    _finish_clip(c, sprite, lib)
    assert c.anim_of(sprite) != "code1", "解除后这段播完就回到随机行为"


def test_clips_missing_from_the_library_are_skipped():
    """换了角色：新角色没有「写代码」素材——有哪段用哪段，全没有就不保持。"""
    c, sprite, lib = _scene()
    # 测试替身库没有 names()（真 MovieLibrary 有）：补上，守卫才看得见「库里有什么」
    lib.names = lambda: ["idle1", "code1", "code2", "nap", "turn1", "walk", "click1"]
    assert c.hold(sprite, ["写代码", "code2"]) is True
    assert c.held(sprite) == ("code2",)

    before = c.anim_of(sprite)
    assert c.hold(sprite, ["写代码", "吃Token"]) is False
    assert c.held(sprite) == ()
    assert c.anim_of(sprite) == before, "没有可用素材：不打断正在播的动画"


def test_forget_drops_the_hold():
    c, sprite, lib = _scene()
    c.hold(sprite, ["code1"])
    c.forget(sprite)
    assert c.held(sprite) == ()
