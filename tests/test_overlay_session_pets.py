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
    shell.set_session_pet_caption(sprite, "dsh-pet · 工作中")
    assert sprite.caption == "dsh-pet · 工作中"
    assert sprite.caption_tone == ""

    shell.set_session_pet_caption(sprite, "dsh-pet · 工作中", tone="working")
    assert sprite.caption_tone == "working", "文字没变、只换色调也要生效"


# ---------------------------------------------------------------- 控制器

@pytest.fixture
def controller(shell, monkeypatch):
    monkeypatch.setattr(SessionPetController, "WORK_CLIPS", ("act1",))
    monkeypatch.setattr(SessionPetController, "REST_CLIPS", ("idle1",))
    monkeypatch.setattr(SessionPetController, "REVIEW_CLIPS", ("click1",))
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
    assert fish.caption == "dsh-pet · 工作中"
    assert fish.caption_tone == "working", "标签底色跟着阶段走"
    assert shell.behavior.held(fish) == ("act1",)

    controller.on_session_update("claude", _update(phase="waiting", project="dsh-pet"))
    assert fish.caption == "dsh-pet · 等你批准"
    assert fish.caption_tone == "waiting"
    assert shell.behavior.held(fish) == ("act1",), "等批准时姿势不变，只换标签"

    controller.on_session_update("claude", _update(phase="resting", title="Fix login loop", project="dsh-pet"))
    assert fish.caption == "Fix login loop · 等你回复", "有标题用标题，没有才用项目名"
    assert fish.caption_tone == "review"
    assert shell.behavior.held(fish) == ("click1",)

    controller.on_session_update("claude", _update(phase="gone"))
    assert _session_pets(shell) == []


def test_a_finished_turn_waits_for_the_user_until_they_have_looked(shell, controller):
    """回合结束 ≠ 休息：用户还没去看之前是「等你回复」，看过了才落回「休息中」。"""
    key = ("claude", "A")
    controller.on_session_update("claude", _update(project="p"))
    (fish,) = _session_pets(shell)

    controller.on_session_update("claude", _update(phase="resting", project="p"))
    assert fish.caption == "p · 等你回复" and fish.caption_tone == "review"
    assert controller.sessions()[0]["phase"] == "review", "灵动岛的清单也要看得出来"
    finished = controller.since(key)

    controller.on_session_update("claude", _update(phase="resting", title="T", project="p"))
    assert fish.caption == "T · 等你回复", "回合结束后才到的标题不把它冲回休息中"
    assert controller.retitle(key, "改过的名字") is True
    assert fish.caption == "改过的名字 · 等你回复"

    assert controller.acknowledge(key) is True
    assert fish.caption == "改过的名字 · 休息中" and fish.caption_tone == "resting"
    assert shell.behavior.held(fish) == ("idle1",)
    assert controller.sessions()[0]["phase"] == "resting"
    assert controller.since(key) == finished, "「已 N 分钟」仍从回合结束算起"
    assert controller.acknowledge(key) is False, "已经看过了"

    controller.on_session_update("claude", _update(phase="resting", title="又改了", project="p"))
    assert fish.caption == "又改了 · 休息中", "看过之后不会自己变回等你回复"


def test_the_next_prompt_clears_the_reminder_and_the_next_finish_raises_it_again(shell, controller):
    controller.on_session_update("claude", _update(project="p"))
    (fish,) = _session_pets(shell)
    controller.on_session_update("claude", _update(phase="resting", project="p"))

    controller.on_session_update("claude", _update(phase="working", project="p"))   # 用户直接回复了
    assert fish.caption == "p · 工作中"
    assert controller.acknowledge(("claude", "A")) is False

    controller.on_session_update("claude", _update(phase="waiting", project="p"))
    controller.on_session_update("claude", _update(phase="resting", project="p"))
    assert fish.caption == "p · 等你回复"


def test_acknowledging_an_unknown_session_is_harmless(shell, controller):
    assert controller.acknowledge(("claude", "nope")) is False


def test_sessions_and_channels_get_separate_fish(shell, controller):
    controller.on_session_update("claude", _update("A", project="win-proj"))
    controller.on_session_update("claude", _update("B", project="other"))
    controller.on_session_update("claude_wsl", _update("A", project="work-proj"))

    assert sorted(f.caption for f in _session_pets(shell)) == [
        "other · 工作中", "win-proj · 工作中", "work-proj (WSL) · 工作中"]


def test_label_falls_back_to_a_short_session_id(shell, controller):
    controller.on_session_update("claude", _update("0123456789abcdef"))
    assert _session_pets(shell)[0].caption == "01234567 · 工作中"


def test_repeated_updates_do_not_restart_the_animation(shell, controller):
    controller.on_session_update("claude", _update(project="p"))
    fish = _session_pets(shell)[0]
    shell.behavior.play_once(fish, "click1")            # 用户点了它一下

    controller.on_session_update("claude", _update(title="New title", project="p"))

    assert fish.caption == "New title · 工作中"
    assert shell.behavior.anim_of(fish) == "click1", "阶段没变：只换标签，不打断正在播的动画"


def test_a_resting_session_does_not_summon_a_fish(shell, controller):
    """肥鱼启动时会话早就停了：不为它凭空生一只，等它下次提问。"""
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


@pytest.mark.parametrize("raw, expected", [(12, 12), ("9", 9), (0, 1), (999, 40), (20, 20), ("x", 6), (None, 6)])
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


def test_custom_limit_asks_for_a_number_and_the_menus_show_it(shell, controller, tmp_path):
    """用户 2026-11-02：上限要能随便填（要设 20，预设里没有）。「自定义…」弹数字框；填的值两处菜单都列出来并勾上；取消不动。"""
    from pet.session_pet_ui import SessionPetActions, build_session_pet_menu
    from pet.sprite_menu_facade import SpriteMenuFacade

    facade = SpriteMenuFacade(shell)
    asked: list = []
    facade.ask_session_pets_max(prompt=lambda cur: (asked.append(cur), (20, True))[1])
    assert asked == [6] and shell._session_pet_limit() == 20
    facade.ask_session_pets_max(prompt=lambda cur: (99, False))
    assert shell._session_pet_limit() == 20, "取消不动"
    facade.ask_session_pets_max(prompt=lambda cur: (999, True))
    assert shell._session_pet_limit() == 40, "超过硬顶按硬顶"
    facade.set_session_pets_max(20)

    # 小鱼自己的菜单：20 只 列出来并勾上，末尾有「自定义…」
    controller.on_session_update("claude", _update(project="dsh-pet"))
    sprite = _session_pets(shell)[0]
    actions = SessionPetActions(shell, controller, anchor_factory=lambda s: None)
    menu = build_session_pet_menu(shell, sprite, actions)
    settings = next(a for a in menu.actions() if a.text() == "会话小鱼设置").menu()
    limit_menu = next(a for a in settings.actions() if a.text() == "会话小鱼上限").menu()
    labels = [a.text() for a in limit_menu.actions() if not a.isSeparator()]
    assert labels == ["3 只", "6 只", "9 只", "12 只", "16 只", "20 只", "24 只", "自定义…"]
    assert [a.text() for a in limit_menu.actions() if a.isChecked()] == ["20 只"]
    menu.deleteLater()

    # 主肥鱼的共享菜单同样
    cfg = Config(base=tmp_path / "other")
    cfg.set("agent_link", {**(cfg.get("agent_link") or {}), "session_pets_max": 20})
    pet = _MenuPet(cfg, with_toggle=True)
    pet.set_session_pets_max = lambda n: None
    custom: list = []
    pet.ask_session_pets_max = lambda: custom.append(True)
    shared_limit = _menu_actions(pet)["会话小鱼上限"].menu()
    shared_labels = [a.text() for a in shared_limit.actions() if not a.isSeparator()]
    assert shared_labels == ["3 只", "6 只", "9 只", "12 只", "16 只", "20 只", "24 只", "自定义…"]
    assert [a.text() for a in shared_limit.actions() if a.isChecked()] == ["20 只"]
    next(a for a in shared_limit.actions() if a.text() == "自定义…").trigger()
    assert custom == [True]


# ---------------------------------------------------------------- 生成落点

def test_new_fish_never_land_on_top_of_existing_ones(shell):
    """新生成的鱼（会话小鱼、手动小肥鱼都算）不压住任何现有的鱼。"""
    for _ in range(4):
        assert shell.spawn_session_pet() is not None
    shell.spawn_pet()
    shell.spawn_pet()

    fish = [shell.sprite, *shell._spawned]
    bodies = [f.body_rect() for f in fish]
    for i, a in enumerate(bodies):
        for b in bodies[i + 1:]:
            assert not a.intersects(b), f"{a} 与 {b} 重叠"
        assert shell._bounds.contains(a), "落点在屏幕可用区内"


# ================================================================ 一直在（2026-11-02）：认领 / 冻结 / 关闭决定

from pet.claude_session_history import SessionHistory  # noqa: E402
from pet.session_fish_decisions import SessionFishDecisions  # noqa: E402
from pet.session_history_service import SessionHistoryService  # noqa: E402

NOW = 1_800_000_000.0


@pytest.fixture
def persistent(shell, monkeypatch, tmp_path):
    """带「最近的对话」+ 落盘的关闭决定的控制器（保留 3 天，上限按壳的配置）。"""
    monkeypatch.setattr(SessionPetController, "WORK_CLIPS", ("act1",))
    monkeypatch.setattr(SessionPetController, "REST_CLIPS", ("idle1",))
    monkeypatch.setattr(SessionPetController, "REVIEW_CLIPS", ("click1",))
    monkeypatch.setattr(SessionPetController, "FROZEN_CLIPS", ("frozen1",))
    clock = {"now": NOW}
    store = SessionHistory(None, clock=lambda: clock["now"])
    history = SessionHistoryService(store, clock=lambda: 0.0)
    decisions = SessionFishDecisions(tmp_path / "session-fish.json", clock=lambda: clock["now"])
    ctl = SessionPetController(shell, enabled=lambda: True, decisions=decisions, keep_days=lambda: 3,
                               clock=lambda: clock["now"])
    ctl.attach_history(history)
    ctl.clock = clock
    ctl.history_store = store
    ctl.decisions = decisions
    return ctl


def _adopted(sid, phase="resting", **extra):
    return {"sessionId": sid, "phase": phase, "title": "", "project": "p", "adopted": "1", **extra}


def test_an_adopted_resting_session_does_get_a_fish(shell, persistent):
    """hook 事件里第一次看到休息中的会话不凭空生鱼（照旧）；从运行清单认领来的要生——它确实开着。"""
    persistent.on_session_update("claude", _update(phase="resting"))
    assert _session_pets(shell) == []
    persistent.on_session_update("claude", _adopted("A"))
    fish = _session_pets(shell)
    assert len(fish) == 1 and fish[0].caption.endswith("休息中")


def test_recent_conversations_without_a_process_become_frozen_fish(shell, persistent):
    """最近 X 天开过、进程已不在的对话：冻结的鱼；点开详情能认出它；超过 X 天自动离场。"""
    persistent.history_store.record("claude", "old-1111-aaaa", seen=NOW - 2 * 86400, cwd=r"C:\Users\me\Pet", title="旧对话")
    persistent.history_store.record("claude", "older-222-bbb", seen=NOW - 5 * 86400, cwd=r"C:\Users\me\Pet")
    persistent.reconcile()
    fish = _session_pets(shell)
    assert len(fish) == 1 and fish[0].caption == "旧对话 · 冻结" and fish[0].caption_tone == "frozen"
    key = ("claude", "old-1111-aaaa")
    assert persistent.key_of(fish[0]) == key
    assert persistent.describe(key)["phase"] == "frozen" and persistent.describe(key)["cwd"] == r"C:\Users\me\Pet"
    assert persistent.sessions() == [], "冻结的不算在用的会话（灵动岛汇总不变）"
    persistent.clock["now"] = NOW + 2 * 86400          # 现在距它 4 天 > 3 天
    persistent.reconcile()
    assert _session_pets(shell) == []


def test_a_frozen_conversation_that_comes_back_alive_thaws(shell, persistent):
    persistent.history_store.record("claude", "old-1111-aaaa", seen=NOW - 3600, cwd=r"C:\Users\me\Pet")
    persistent.reconcile()
    frozen = _session_pets(shell)[0]
    persistent.on_session_update("claude", _adopted("old-1111-aaaa"))
    fish = _session_pets(shell)
    assert len(fish) == 1 and fish[0] is not frozen and fish[0].caption.endswith("休息中")
    persistent.on_session_update("claude", _update("old-1111-aaaa", phase="gone"))
    persistent.reconcile()
    assert len(_session_pets(shell)) == 1 and _session_pets(shell)[0].caption.endswith("冻结"), "进程没了：回到冻结，不是消失"


def test_closing_a_fish_is_remembered_across_restarts_until_the_session_is_active_again(shell, persistent, tmp_path):
    persistent.history_store.record("claude", "old-1111-aaaa", seen=NOW - 3600, cwd=r"C:\Users\me\Pet")
    persistent.reconcile()
    assert persistent.dismiss(_session_pets(shell)[0])
    assert _session_pets(shell) == []
    persistent.reconcile()
    assert _session_pets(shell) == [], "同一轮里不回来"
    # 「重启」：同一份决定文件、新的控制器
    again = SessionFishDecisions(tmp_path / "session-fish.json")
    again.load()
    assert again.is_dismissed(("claude", "old-1111-aaaa"))
    persistent.on_session_update("claude", _adopted("old-1111-aaaa"))
    assert _session_pets(shell) == [], "认领回来也还是休息中：仍然关着"
    persistent.on_session_update("claude", _update("old-1111-aaaa", phase="working", project="p"))
    assert len(_session_pets(shell)) == 1, "又活跃了：决定作废，正常显示"
    again.load()
    assert not again.is_dismissed(("claude", "old-1111-aaaa"))


def test_decisions_about_sessions_that_left_the_roster_are_forgotten(shell, persistent):
    persistent.history_store.record("claude", "old-1111-aaaa", seen=NOW - 3600, cwd=r"C:\Users\me\Pet")
    persistent.reconcile()
    persistent.dismiss(_session_pets(shell)[0])
    persistent.clock["now"] = NOW + 4 * 86400
    persistent.reconcile()
    assert not persistent.decisions.is_dismissed(("claude", "old-1111-aaaa"))


def test_live_sessions_outrank_frozen_ones_when_the_cap_is_full(shell, persistent):
    data = dict(shell._config.get("agent_link"))
    data["session_pets_max"] = 2
    shell._config.set("agent_link", data)
    for i in range(3):
        persistent.history_store.record("claude", f"old-{i}-aaaaaaaa", seen=NOW - (i + 1) * 3600, cwd=r"C:\Users\me\Pet")
    persistent.reconcile()
    assert [persistent.key_of(s)[1] for s in _session_pets(shell)] == ["old-0-aaaaaaaa", "old-1-aaaaaaaa"], "最近的优先"
    persistent.on_session_update("claude", _update("live", project="p"))
    keys = [persistent.key_of(s)[1] for s in _session_pets(shell)]
    assert "live" in keys and len(keys) == 2 and "old-1-aaaaaaaa" not in keys, "活的进来，最旧的冻结鱼让位"


def test_frozen_fish_menu_offers_resume_instead_of_jump(shell, persistent, monkeypatch):
    from pet.session_pet_ui import SessionPetActions, build_session_pet_menu

    persistent.history_store.record("claude", "old-1111-aaaa", seen=NOW - 3600, cwd=r"C:\Users\me\Pet",
                                    entrypoint="claude-desktop", host_session="local_abc123def456")
    persistent.reconcile()
    sprite = _session_pets(shell)[0]
    actions = SessionPetActions(shell, persistent, anchor_factory=lambda s: None)
    opened: list = []
    actions.uri_opener = lambda uri: opened.append(uri) or True
    menu = build_session_pet_menu(shell, sprite, actions)
    labels = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert "在 Claude 桌面版重开这个对话" in labels and "关闭这只" in labels
    assert "在 Claude 桌面版打开" not in labels, "恢复那一项就是它：不重复"
    assert "跳到这个对话" not in labels and "让这只离场" not in labels
    assert actions.jump(sprite) is True
    assert opened == ["claude://claude.ai/epitaxy/local_abc123def456"], "冻结 + 桌面版：走深链"
    menu.deleteLater()


def test_frozen_vs_code_fish_reopens_the_conversation_in_its_wsl_workspace(shell, persistent):
    """用户 2026-11-02：冻结的 VS Code 会话点了「跳到对话」看到的不是之前的对话——之前只开了工作区文件夹。
    现在：菜单说清是在 VS Code 里重开；点下去把带发行版名的详情交给重开那一路（它负责聚焦工作区 + 插件深链）。"""
    from PySide6.QtTest import QTest

    from pet.claude_session_jump import JumpResult
    from pet.session_pet_ui import SessionPetActions, build_session_pet_menu

    persistent.history_store.record("claude_wsl", "old-2222-bbbb", seen=NOW - 3600, cwd="/home/me/proj",
                                    entrypoint="claude-vscode", distro="Ubuntu-24.04")
    persistent.reconcile()
    sprite = _session_pets(shell)[0]
    actions = SessionPetActions(shell, persistent, anchor_factory=lambda s: None)
    handed: list = []
    actions.vscode_resumer = lambda detail: handed.append(detail) or JumpResult(True, "已让 VS Code 重开这个对话")
    menu = build_session_pet_menu(shell, sprite, actions)
    labels = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert "在 VS Code 里重开这个对话" in labels and "在 Claude 桌面版打开" not in labels
    assert actions.jump(sprite) is True, "冻结鱼的「跳转」就是重开"
    for _ in range(100):
        if handed:
            break
        QTest.qWait(20)
    assert len(handed) == 1
    detail = handed[0]
    assert (detail.session_id, detail.cwd, detail.entrypoint, detail.distro) == (
        "old-2222-bbbb", "/home/me/proj", "claude-vscode", "Ubuntu-24.04")
    assert detail.is_wsl
    menu.deleteLater()


def test_frozen_terminal_fish_says_it_resumes_in_a_terminal(shell, persistent):
    from pet.session_pet_ui import SessionPetActions, build_session_pet_menu

    persistent.history_store.record("claude", "old-3333-cccc", seen=NOW - 3600, cwd=r"C:\Users\me\Pet",
                                    entrypoint="cli")
    persistent.reconcile()
    sprite = _session_pets(shell)[0]
    actions = SessionPetActions(shell, persistent, anchor_factory=lambda s: None)
    menu = build_session_pet_menu(shell, sprite, actions)
    labels = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert "在终端里恢复这个对话" in labels
    menu.deleteLater()


@pytest.mark.parametrize("raw, expected", [({}, 3), ({"session_fish_keep_days": 14}, 14),
                                           ({"session_fish_keep_days": 99}, 30), ({"session_fish_keep_days": "x"}, 3)])
def test_session_fish_keep_days_is_normalised(tmp_path, raw, expected):
    cfg = Config(base=tmp_path)
    cfg.set("agent_link", {**(cfg.get("agent_link") or {}), **raw})
    assert cfg.get("agent_link")["session_fish_keep_days"] == expected


def test_facade_persists_the_keep_days_and_the_menu_offers_them(shell, tmp_path):
    from pet.sprite_menu_facade import SpriteMenuFacade

    SpriteMenuFacade(shell).set_session_fish_keep_days(7)
    assert shell._config.get("agent_link")["session_fish_keep_days"] == 7
    cfg = Config(base=tmp_path / "other")             # 壳的配置就在 tmp_path 下，另开一份看默认值
    pet = _MenuPet(cfg, with_toggle=True)
    picked: list = []
    pet.set_session_fish_keep_days = picked.append
    days_menu = _menu_actions(pet)["冻结小鱼保留天数"].menu()
    choices = {a.text(): a for a in days_menu.actions()}
    assert [a.text() for a in days_menu.actions() if a.isChecked()] == ["3 天"]
    choices["14 天"].trigger()
    assert picked == [14]


def test_a_shell_built_over_an_existing_history_does_not_spawn_during_its_own_init(tmp_path, monkeypatch):
    """实机 2026-11-02：历史里有 23 条近期对话，壳一建就生冻结鱼，而 sprite 落点要用的屏幕路由还没建好 → 启动失败。
    接上历史后第一次核对要延后；延后之后冻结鱼照常出场。"""
    import json
    import time as _time

    from PySide6.QtTest import QTest

    from pet.claude_session_history import HISTORY_FILE

    monkeypatch.setattr(SessionPetController, "FIRST_RECONCILE_MS", 0)
    config_dir = tmp_path / APP_DIR_NAME
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / HISTORY_FILE).write_text(json.dumps({"version": 1, "entries": [
        {"agent": "claude", "session_id": "old-1111-aaaa", "cwd": r"C:\Users\me\Pet", "title": "旧对话",
         "last_seen": _time.time() - 3600}]}), encoding="utf-8")
    shell, _ = _make_persistent_shell(tmp_path, {"scale": 0.85})
    try:
        assert _session_pets(shell) == [], "构造期间不生鱼"
        QTest.qWait(50)
        fish = _session_pets(shell)
        assert len(fish) == 1 and fish[0].caption == "旧对话 · 冻结"
    finally:
        shell._delete_runtime_marker()
