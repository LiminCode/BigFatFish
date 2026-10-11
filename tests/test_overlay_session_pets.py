# -*- coding: utf-8 -*-
"""会话小鱼：每个在用的 Claude Code 会话一只临时 sprite。

两层：``OverlayShell`` 的临时 sprite（不占 slot 身份、不进活跃清单、不接管主
身份），与 ``SessionPetController``（监视器的 ``session_update`` → 生成 / 标签 /
保持动画 / 离场）。手动「生小肥鱼」的既有不变量由 test_overlay_spawn.py 钉着，
这里只测会话小鱼不去碰它们。
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication, QMenu

from pet import catalog
from pet import overlay_spawn_state as ovs
from pet.config import APP_DIR_NAME, Config
from pet.context_menus import shared as menu_shared
from pet.overlay_session_pets import SessionPetController
from tests.test_overlay_spawn import _make_persistent_shell

app = QApplication.instance() or QApplication([])


@pytest.fixture
def shell(tmp_path):
    shell, made = _make_persistent_shell(tmp_path, {"scale": 0.85})
    shell.made_libs = made
    try:
        yield shell
    finally:
        shell._delete_runtime_marker()


# ---------------------------------------------------------------- 临时 sprite

def test_session_pet_is_ephemeral(shell, tmp_path):
    """不占 slot 身份（身份永不回收，上限 128，自动生成会把它耗光）、不进活跃清单。"""
    config_dir = tmp_path / APP_DIR_NAME

    sprite = shell.spawn_session_pet()

    assert sprite in shell.overlay.sprites and shell.is_session_pet(sprite)
    assert ovs.load_active_slots(config_dir) == []
    assert list(config_dir.glob("config-slot-*.json")) == []
    shell.spawn_pet()                       # 手动生的小肥鱼照旧从 1 号身份起
    assert sorted(shell._spawned_slots.values()) == [1]
    assert ovs.load_active_slots(config_dir) == [1]


def test_session_pet_is_half_the_main_size_and_stays_that_way(shell):
    """会话小鱼是主肥鱼的一半大：一眼分得清，多只在场也不占地方。"""
    sprite = shell.spawn_session_pet()
    assert sprite.scale == pytest.approx(0.85 / 2)

    shell._sync_sprite_settings()           # 设置重下发（任意设置变更都会触发）
    assert sprite.scale == pytest.approx(0.85 / 2)


def test_session_pet_of_the_smallest_main_fish_is_still_half(tmp_path):
    """主肥鱼已是最小档（0.5）时，「小一号」无档可退——实机上就是这个配置。"""
    small_shell, _ = _make_persistent_shell(tmp_path, {"scale": 0.5})
    try:
        assert small_shell.spawn_session_pet().scale == pytest.approx(0.25)
    finally:
        small_shell._delete_runtime_marker()


def test_removing_a_session_pet_releases_its_library(shell):
    sprite = shell.spawn_session_pet()
    lib = sprite.library

    shell.remove_session_pet(sprite)

    assert sprite not in shell.overlay.sprites
    assert shell.is_session_pet(sprite) is False
    assert lib.shutdown_calls == 1
    shell.remove_session_pet(sprite)        # 重复移除无害
    assert lib.shutdown_calls == 1


def test_session_pets_are_capped(shell):
    pets = [shell.spawn_session_pet() for _ in range(shell.SESSION_PET_MAX)]
    assert all(p is not None for p in pets)
    assert shell.spawn_session_pet() is None
    shell.remove_session_pet(pets[0])
    assert shell.spawn_session_pet() is not None, "腾出位置后可以再生"


def test_session_pet_never_takes_over_the_main_identity(shell):
    """主肥鱼退出时提升的是手动生的小肥鱼；会话小鱼排在前面也不算。"""
    session = shell.spawn_session_pet()
    shell.spawn_pet()
    manual = [s for s in shell._spawned if s is not session][0]

    assert shell.exit_pet() is True

    assert shell.sprite is manual
    assert shell.is_session_pet(session), "会话小鱼原样留着"


def test_clearing_spawned_pets_also_dismisses_session_pets(shell):
    session = shell.spawn_session_pet()
    shell.clear_spawned_pets()
    assert session not in shell.overlay.sprites
    assert shell.is_session_pet(session) is False


def test_caption_setter_updates_the_sprite(shell):
    sprite = shell.spawn_session_pet()
    shell.set_session_pet_caption(sprite, "dsh-pet · 写代码中")
    assert sprite.caption == "dsh-pet · 写代码中"


# ---------------------------------------------------------------- 控制器

@pytest.fixture
def controller(shell, monkeypatch):
    monkeypatch.setattr(SessionPetController, "WORK_CLIPS", ("act1",))
    monkeypatch.setattr(SessionPetController, "REST_CLIPS", ("idle1",))
    state = {"on": True}
    ctl = SessionPetController(shell, enabled=lambda: state["on"])
    ctl.state = state
    return ctl


def _update(sid="A", phase="working", title="", project=""):
    return {"sessionId": sid, "phase": phase, "title": title, "project": project}


def _session_pets(shell) -> list:
    return [s for s in shell.overlay.sprites if shell.is_session_pet(s)]


def test_session_gets_a_fish_that_follows_its_phase(shell, controller):
    controller.on_session_update("claude", _update(project="dsh-pet"))
    (fish,) = _session_pets(shell)
    assert fish.caption == "dsh-pet · 写代码中"
    assert shell.behavior.held(fish) == ("act1",)

    controller.on_session_update("claude", _update(phase="waiting", project="dsh-pet"))
    assert fish.caption == "dsh-pet · 等你批准"
    assert shell.behavior.held(fish) == ("act1",), "等批准时姿势不变，只换标签"

    controller.on_session_update("claude", _update(phase="resting", title="Fix login loop", project="dsh-pet"))
    assert fish.caption == "Fix login loop · 休息中", "有标题用标题，没有才用项目名"
    assert shell.behavior.held(fish) == ("idle1",)

    controller.on_session_update("claude", _update(phase="gone"))
    assert _session_pets(shell) == []


def test_sessions_and_channels_get_separate_fish(shell, controller):
    controller.on_session_update("claude", _update("A", project="win-proj"))
    controller.on_session_update("claude", _update("B", project="other"))
    controller.on_session_update("claude_wsl", _update("A", project="work-proj"))

    assert sorted(f.caption for f in _session_pets(shell)) == [
        "other · 写代码中", "win-proj · 写代码中", "work-proj (WSL) · 写代码中"]


def test_label_falls_back_to_a_short_session_id(shell, controller):
    controller.on_session_update("claude", _update("0123456789abcdef"))
    assert _session_pets(shell)[0].caption == "01234567 · 写代码中"


def test_repeated_updates_do_not_restart_the_animation(shell, controller):
    controller.on_session_update("claude", _update(project="p"))
    fish = _session_pets(shell)[0]
    shell.behavior.play_once(fish, "click1")            # 用户点了它一下

    controller.on_session_update("claude", _update(title="New title", project="p"))

    assert fish.caption == "New title · 写代码中"
    assert shell.behavior.anim_of(fish) == "click1", "阶段没变：只换标签，不打断正在播的动画"


def test_a_resting_session_does_not_summon_a_fish(shell, controller):
    """桌宠启动时会话早就停了：不为它凭空生一只，等它下次提问。"""
    controller.on_session_update("claude", _update(phase="resting"))
    assert _session_pets(shell) == []


def test_dismissed_fish_returns_on_the_next_prompt_not_before(shell, controller):
    controller.on_session_update("claude", _update(project="p"))
    shell.exit_pet(_session_pets(shell)[0])             # 用户「退出这只」

    controller.on_session_update("claude", _update(phase="resting", project="p"))
    assert _session_pets(shell) == []
    controller.on_session_update("claude", _update(phase="working", project="p"))
    assert len(_session_pets(shell)) == 1


def test_sessions_beyond_the_cap_are_simply_not_shown(shell, controller):
    for i in range(shell.SESSION_PET_MAX + 2):
        controller.on_session_update("claude", _update(f"s{i}", project="p"))
    assert len(_session_pets(shell)) == shell.SESSION_PET_MAX
    controller.on_session_update("claude", _update("s0", phase="gone"))
    controller.on_session_update("claude", _update(f"s{shell.SESSION_PET_MAX}", project="p"))
    assert len(_session_pets(shell)) == shell.SESSION_PET_MAX, "有会话离场后，排队的会话下次更新时补上"


def test_switching_the_feature_off_dismisses_everything(shell, controller):
    controller.on_session_update("claude", _update("A", project="p"))
    controller.on_session_update("claude", _update("B", project="p"))

    controller.state["on"] = False
    controller.clear()
    assert _session_pets(shell) == []

    controller.on_session_update("claude", _update("A", project="p"))
    assert _session_pets(shell) == [], "关着的时候不再生成"


def test_malformed_updates_are_ignored(shell, controller):
    for bad in (None, "x", {}, {"sessionId": "A", "phase": "dancing"}):
        controller.on_session_update("claude", bad)
    assert _session_pets(shell) == []


def test_controller_subscribes_to_both_claude_channels():
    class _Signal:
        def __init__(self):
            self.slots = []

        def connect(self, slot):
            self.slots.append(slot)

    class _Mon:
        def __init__(self):
            self.session_update = _Signal()

    class _Manager:
        monitors = {"claude": _Mon(), "claude_wsl": _Mon(), "dsh": object()}

    ctl = SessionPetController(shell=None, enabled=lambda: True)
    ctl.attach(_Manager())
    assert _Manager.monitors["claude"].session_update.slots == [ctl.on_session_update]
    assert _Manager.monitors["claude_wsl"].session_update.slots == [ctl.on_session_update]


# ---------------------------------------------------------------- 开关

def test_session_pets_are_on_by_default_and_the_flag_is_normalised(tmp_path):
    cfg = Config(base=tmp_path)
    assert cfg.get("agent_link")["session_pets"] is True
    data = dict(cfg.get("agent_link"))
    data["session_pets"] = 0
    cfg.set("agent_link", data)
    cfg.save()
    assert Config(base=tmp_path).get("agent_link")["session_pets"] is False


class _MenuPet:
    def __init__(self, cfg, *, with_toggle: bool) -> None:
        self.cfg = cfg
        self.toggled: list = []
        if with_toggle:
            self.toggle_session_pets = self.toggled.append

    def toggle_agent_link(self, *_args) -> None:
        pass


def _menu_actions(pet) -> dict:
    menu = QMenu()
    menu_shared.add_agent_link_menu(menu, pet)
    submenu = menu.actions()[0].menu()
    pet.keep_alive = (menu, submenu)
    return {a.text(): a for a in submenu.actions() if not a.isSeparator()}


def test_menu_offers_the_switch_only_where_session_pets_exist(tmp_path):
    """旧拓扑（PetWindow）没有会话小鱼：没有这个能力就不放开关。"""
    assert "每个会话一只小鱼" not in _menu_actions(_MenuPet(Config(base=tmp_path), with_toggle=False))

    pet = _MenuPet(Config(base=tmp_path), with_toggle=True)
    action = _menu_actions(pet)["每个会话一只小鱼"]
    assert action.isCheckable() and action.isChecked() is True
    action.trigger()
    assert pet.toggled == [False]


def test_facade_toggle_persists_and_clears(shell):
    from pet.sprite_menu_facade import SpriteMenuFacade

    cleared: list = []
    shell.session_pets = type("_Ctl", (), {"clear": lambda self: cleared.append(1)})()
    facade = SpriteMenuFacade(shell)

    facade.toggle_session_pets(False)

    assert shell._config.get("agent_link")["session_pets"] is False
    assert cleared == [1]
    facade.toggle_session_pets(True)
    assert shell._config.get("agent_link")["session_pets"] is True
    assert cleared == [1], "打开时不用清"
    assert shell.sprite.pos != QPointF(-1, -1)


# ---------------------------------------------------------------- 会话登记表与上限

def test_controller_keeps_a_session_registry_independent_of_the_fish(shell, controller):
    """灵动岛卡片要的是「有哪些会话」，不是「有哪些鱼」：关掉小鱼、超出上限都照记。"""
    changes: list = []
    controller.sessions_changed.connect(lambda: changes.append(1))
    controller.state["on"] = False

    controller.on_session_update("claude", _update("A", project="p"))
    controller.on_session_update("claude", _update("A", project="p"))          # 内容没变
    controller.on_session_update("claude_wsl", _update("B", phase="resting", title="T"))

    assert _session_pets(shell) == []
    assert controller.sessions() == [
        {"agent": "claude", "sessionId": "A", "phase": "working", "title": "", "project": "p"},
        {"agent": "claude_wsl", "sessionId": "B", "phase": "resting", "title": "T", "project": ""},
    ]
    assert len(changes) == 2, "内容变化才通知"

    controller.on_session_update("claude", _update("A", phase="gone"))
    assert [s["sessionId"] for s in controller.sessions()] == ["B"]
    assert len(changes) == 3


def test_session_pet_limit_is_configurable(shell):
    data = dict(shell._config.get("agent_link"))
    data["session_pets_max"] = 2
    shell._config.set("agent_link", data)

    assert shell.spawn_session_pet() is not None
    assert shell.spawn_session_pet() is not None
    assert shell.spawn_session_pet() is None

    data["session_pets_max"] = 3
    shell._config.set("agent_link", data)
    assert shell.spawn_session_pet() is not None, "调大即时生效"


@pytest.mark.parametrize("raw, expected", [(12, 12), ("9", 9), (0, 1), (999, 24), ("x", 6), (None, 6)])
def test_session_pets_max_is_normalised(tmp_path, raw, expected):
    cfg = Config(base=tmp_path)
    assert cfg.get("agent_link")["session_pets_max"] == 6
    data = dict(cfg.get("agent_link"))
    data["session_pets_max"] = raw
    cfg.set("agent_link", data)
    cfg.save()
    assert Config(base=tmp_path).get("agent_link")["session_pets_max"] == expected


def test_menu_lets_the_user_pick_the_session_pet_limit(tmp_path):
    cfg = Config(base=tmp_path)
    pet = _MenuPet(cfg, with_toggle=True)
    picked: list = []
    pet.set_session_pets_max = picked.append

    limit_menu = _menu_actions(pet)["会话小鱼上限"].menu()
    choices = {a.text(): a for a in limit_menu.actions()}

    assert [a.text() for a in limit_menu.actions() if a.isChecked()] == ["6 只"]
    choices["12 只"].trigger()
    assert picked == [12]


def test_facade_persists_the_session_pet_limit(shell):
    from pet.sprite_menu_facade import SpriteMenuFacade

    SpriteMenuFacade(shell).set_session_pets_max(10)
    assert shell._config.get("agent_link")["session_pets_max"] == 10
    assert shell._session_pet_limit() == 10
