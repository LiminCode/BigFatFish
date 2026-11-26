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


def test_menu_sends_the_user_to_the_panorama_for_the_session_fish_settings(tmp_path):
    """上限 / 保留天数 / 配色 / 字号 / 桂冠 2026-11-19 起在配置全景「会话小鱼」那组里改：菜单只剩开关和一条跳过去的入口。"""
    pet = _MenuPet(Config(base=tmp_path), with_toggle=True)
    opened: list = []
    pet.open_session_fish_settings = lambda: opened.append(True)
    actions = _menu_actions(pet)
    assert "会话小鱼上限" not in actions and "冻结小鱼保留天数" not in actions and "详情卡配色" not in actions
    assert "详情卡文字大小" not in actions and "桂冠给哪个模型" not in actions
    actions["会话小鱼设置…"].trigger()
    assert opened == [True]
    assert "会话小鱼设置…" not in _menu_actions(_MenuPet(Config(base=tmp_path), with_toggle=False)), "旧拓扑没有会话小鱼"


def test_the_fish_menu_and_the_facade_open_the_panorama_at_the_session_fish_group(shell, controller):
    from pet.session_pet_ui import SessionPetActions, build_session_pet_menu
    from pet.sprite_menu_facade import SpriteMenuFacade

    focused: list = []
    shell.open_config_panorama = lambda focus="": focused.append(focus)
    controller.on_session_update("claude", _update(project="dsh-pet"))
    sprite = _session_pets(shell)[0]
    menu = build_session_pet_menu(shell, sprite, SessionPetActions(shell, controller, anchor_factory=lambda s: None))
    entry = next(a for a in menu.actions() if a.text() == "会话小鱼设置…")
    assert entry.menu() is None, "不再是子菜单"
    entry.trigger()
    assert focused == ["session_fish"]
    SpriteMenuFacade(shell).open_session_fish_settings()
    assert focused == ["session_fish", "session_fish"]
    menu.deleteLater()


def test_settings_changed_elsewhere_take_effect_when_the_shell_refreshes(shell, controller):
    """配置全景改的值经 AppShell 的应用链到 ``refresh_settings``：关开关 → 小鱼离场；上限读时取值；保留天数 → 核对名册。"""
    shell.session_pets = controller
    controller.on_session_update("claude", _update("A", project="p"))
    controller.on_session_update("claude", _update("B", project="p"))
    assert len(_session_pets(shell)) == 2
    data = dict(shell._config.get("agent_link"))
    data["session_pets_max"] = 2
    shell._config.set("agent_link", data)
    shell.refresh_settings()
    assert shell._session_pet_limit() == 2 and len(_session_pets(shell)) == 2
    reconciled: list = []
    controller.reconcile = lambda: reconciled.append(True)
    data["session_fish_keep_days"] = 14
    shell._config.set("agent_link", data)
    shell.refresh_settings()
    assert reconciled == [True]
    controller.state["on"] = False
    data["session_pets"] = False
    shell._config.set("agent_link", data)
    shell.refresh_settings()
    assert _session_pets(shell) == [], "关掉开关：在场的会话小鱼离场"


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


DESK_HOST = "local_1cf14c8e-3cd8-4542-8f62-c850603ec392"


@pytest.fixture
def running(shell, monkeypatch, tmp_path):
    """``persistent`` + a stand-in for the local Claude Code run list (``~/.claude/sessions``)."""
    monkeypatch.setattr(SessionPetController, "WORK_CLIPS", ("act1",))
    monkeypatch.setattr(SessionPetController, "REST_CLIPS", ("idle1",))
    monkeypatch.setattr(SessionPetController, "REVIEW_CLIPS", ("click1",))
    monkeypatch.setattr(SessionPetController, "FROZEN_CLIPS", ("frozen1",))
    clock = {"now": NOW}
    live: dict = {}
    store = SessionHistory(None, clock=lambda: clock["now"])
    history = SessionHistoryService(store, clock=lambda: 0.0)
    ctl = SessionPetController(shell, enabled=lambda: True, decisions=SessionFishDecisions(None),
                               keep_days=lambda: 3, clock=lambda: clock["now"], registry=lambda: dict(live))
    ctl.attach_history(history)
    ctl.live = live
    ctl.history_store = store
    return ctl


def _registry_item(phase="resting", **extra):
    return {"phase": phase, "title": "", "project": "silly-knuth-a6a8db",
            "cwd": r"C:\w\silly-knuth-a6a8db", "transcript": "", "entrypoint": "claude-desktop",
            "host_session": DESK_HOST, **extra}


def test_a_recent_conversation_whose_process_is_still_running_is_not_frozen(shell, running):
    """User 2026-11-14: after a pet restart with the Claude Code link switched off, a conversation they had
    just typed into showed up as 冻结 (frozen). Frozen means the process is gone; the run list says it is not,
    so the fish shows the run list's state, follows it, and only freezes once the process really leaves."""
    key = ("claude", "9f597df0-2760-4b84-9a80-fc2f1ecf88fb")
    running.history_store.record(*key, seen=NOW - 600, cwd=r"C:\w\silly-knuth-a6a8db",
                                 title="Island display name configuration", entrypoint="claude-desktop")
    running.live[key] = _registry_item("resting")
    running.reconcile()
    (fish,) = _session_pets(shell)
    assert not running.is_frozen(key) and fish.caption_tone != "frozen"
    assert fish.caption.endswith("休息中")
    assert running.describe(key)["host_session"] == DESK_HOST, "the jump needs the desktop-side id"
    assert running.history_entry(key).host_session == DESK_HOST, "remembered for when it does freeze"

    running.live[key] = _registry_item("working")
    running.reconcile()
    assert _session_pets(shell)[0].caption.endswith("工作中"), "follows the run list's status"

    running.live.clear()                          # the conversation was closed
    running.reconcile()
    (fish,) = _session_pets(shell)
    assert running.is_frozen(key) and fish.caption.endswith("冻结")


def test_the_run_list_never_overrides_what_the_live_channel_reports(shell, running):
    """With the Claude Code link on, the channel owns the session's phase and its end."""
    key = ("claude", "live-1111-aaaa")
    running.on_session_update("claude", _update(key[1], phase="working", project="p"))
    running.live[key] = _registry_item("resting")
    running.reconcile()
    assert _session_pets(shell)[0].caption.endswith("工作中")
    running.live.clear()
    running.reconcile()
    (fish,) = _session_pets(shell)
    assert fish.caption.endswith("工作中") and not running.is_frozen(key)


def test_the_shell_feeds_the_fish_the_local_run_list(shell, monkeypatch):
    """The shell's controller reads the local run list (conftest stubs it empty, so tests never read
    this machine's ``~/.claude/sessions``)."""
    from pet import overlay_shell

    assert shell.session_pets._registry() == {}
    monkeypatch.setattr(overlay_shell, "_local_run_list",
                        lambda: {("claude", "9f597df0"): _registry_item("waiting")})
    assert shell.session_pets._registry() == {("claude", "9f597df0"): _registry_item("waiting")}


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


def _cap(shell, n):
    data = dict(shell._config.get("agent_link"))
    data["session_pets_max"] = n
    shell._config.set("agent_link", data)


def _fish_keys(shell, ctl):
    return sorted(ctl.key_of(s)[1] for s in _session_pets(shell))


def test_a_working_session_displaces_the_longest_resting_fish_when_the_cap_is_full(shell, persistent):
    """User 2026-11-25: 20 open conversations, cap 12, every slot held by an idle (adopted) VS Code panel.
    The one they were typing into started working and never got a fish — only frozen fish ever made room.
    A session that is working / waiting outranks one that is just sitting there."""
    _cap(shell, 2)
    persistent.on_session_update("claude_wsl", _adopted("idle-old"))
    persistent.clock["now"] = NOW + 600
    persistent.on_session_update("claude_wsl", _adopted("idle-new"))
    persistent.clock["now"] = NOW + 1200
    persistent.on_session_update("claude_wsl", _adopted("busy"))
    assert _fish_keys(shell, persistent) == ["idle-new", "idle-old"], "认领来的休息中不挤休息中的活鱼"

    persistent.on_session_update("claude_wsl", _update("busy", phase="working", project="p"))
    assert _fish_keys(shell, persistent) == ["busy", "idle-new"], "干活的进来，休息最久的那只让位"
    assert ("claude_wsl", "idle-old") in {(s["agent"], s["sessionId"]) for s in persistent.sessions()}, \
        "让位的会话仍在用（灵动岛照记），只是没鱼"

    persistent.clock["now"] = NOW + 1800
    persistent.on_session_update("claude_wsl", _update("idle-old", phase="working", project="p"))
    assert _fish_keys(shell, persistent) == ["busy", "idle-old"], "它再干活时同样挤回来"


def test_a_displaced_live_session_gets_its_seat_back_before_any_frozen_fish(shell, persistent):
    """Real run 2026-11-25: a short `claude -p` displaced a resting fish, finished, and its frozen fish took the
    freed slot while the displaced (still open) conversation stayed fishless. Live outranks frozen here too."""
    _cap(shell, 2)
    persistent.on_session_update("claude_wsl", _adopted("idle-old"))
    persistent.clock["now"] = NOW + 600
    persistent.on_session_update("claude_wsl", _adopted("idle-new"))
    persistent.clock["now"] = NOW + 1200
    persistent.on_session_update("claude", _update("probe", phase="working", project="p"))
    assert _fish_keys(shell, persistent) == ["idle-new", "probe"]

    persistent.history_store.record("claude", "probe", seen=NOW + 1200, cwd=r"C:\tmp\probe")
    persistent.on_session_update("claude", _update("probe", phase="gone"))
    persistent.reconcile()
    assert _fish_keys(shell, persistent) == ["idle-new", "idle-old"], "空出来的位置先给开着的对话，不给冻结鱼"


def test_reseating_never_brings_back_a_fish_the_user_exited(shell, persistent):
    persistent.on_session_update("claude", _update("A", phase="working", project="p"))
    shell.exit_pet(_session_pets(shell)[0])             # 用户「退出这只」
    persistent.on_session_update("claude", _update("A", phase="resting", project="p"))
    persistent.reconcile()
    assert _session_pets(shell) == [], "补位只补满员时没拿到 / 被挤掉的，不补用户退掉的"


def test_busy_and_unseen_fish_are_never_displaced(shell, persistent):
    """Only plain 休息中 yields: a fish that is working, waiting for approval, or holding an unread answer stays."""
    _cap(shell, 2)
    persistent.on_session_update("claude", _update("A", phase="working", project="p"))
    persistent.on_session_update("claude", _update("A", phase="resting", project="p"))   # 回合结束 → 等你回复
    persistent.on_session_update("claude", _update("B", phase="waiting", project="p"))
    persistent.on_session_update("claude", _update("C", phase="working", project="p"))
    assert _fish_keys(shell, persistent) == ["A", "B"]


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


def test_a_frozen_desktop_fish_without_its_host_id_brings_up_claude_desktop_not_a_terminal(shell, persistent):
    """User 2026-11-14: 「跳到对话」 on a Claude desktop conversation opened a cmd window. The history row came
    from a transcript scan, which knows the entrypoint but not the desktop-side id, so the resume fell through
    to ``claude --resume`` in a terminal. A desktop conversation lives in the desktop app: bring that up."""
    from pet.claude_session_jump import JumpResult
    from pet.session_pet_ui import SessionPetActions, build_session_pet_menu

    persistent.history_store.record("claude", "9f597df0-2760", seen=NOW - 3600, cwd=r"C:\w\silly",
                                    entrypoint="claude-desktop")
    persistent.reconcile()
    sprite = _session_pets(shell)[0]
    actions = SessionPetActions(shell, persistent, anchor_factory=lambda s: None)
    opened, ran, raised = [], [], []
    actions.uri_opener = lambda uri: opened.append(uri) or True

    class _Runner:
        def run(self, action, entry):
            ran.append(action)
            return "opened a terminal"

    actions._history_actions = _Runner()
    actions.desktop_raiser = lambda: raised.append(True) or JumpResult(True, "switched to Claude desktop")
    menu = build_session_pet_menu(shell, sprite, actions)
    labels = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert "在 Claude 桌面版重开这个对话" in labels and "在终端里恢复这个对话" not in labels
    assert actions.jump(sprite) is True
    assert ran == [], "never a terminal for a desktop conversation"
    assert raised == [True] and opened == []
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
    actions.workspace_finder = lambda *_args, **_kwargs: {}      # 不读真实的 VS Code 状态库
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


def test_a_frozen_vs_code_fish_carries_the_workspace_the_history_remembers(shell, persistent):
    """用户 2026-11-08：原工作区关掉后，「跳到对话」把对话重开到了别的（恰好也包含这个目录的）工作区里。
    历史记着它当时的工作区，冻结鱼交给重开那一路的详情里要带着它。"""
    from PySide6.QtTest import QTest

    from pet.claude_session_jump import JumpResult
    from pet.session_pet_ui import SessionPetActions

    workspace = {"label": "deploy", "target": "/home/me/ws/deploy.code-workspace", "multi_root": True,
                 "roots": ["/home/me/proj", "/home/me/charts"]}
    persistent.history_store.record("claude_wsl", "old-2222-bbbb", seen=NOW - 3600, cwd="/home/me/proj",
                                    entrypoint="claude-vscode", distro="Ubuntu-24.04", workspace=workspace)
    persistent.reconcile()
    sprite = _session_pets(shell)[0]
    actions = SessionPetActions(shell, persistent, anchor_factory=lambda s: None)
    handed: list = []
    looked: list = []
    actions.vscode_resumer = lambda detail: handed.append(detail) or JumpResult(True, "ok")
    actions.workspace_finder = lambda *args, **kwargs: looked.append(args) or {}
    assert actions.jump(sprite) is True
    for _ in range(100):
        if handed:
            break
        QTest.qWait(20)
    assert handed[0].extra["workspace"] == workspace
    assert looked == [], "历史里有记录就不用去翻 VS Code 的状态库"


def test_an_old_frozen_fish_without_a_record_is_backfilled_from_vscodes_state(shell, persistent):
    from PySide6.QtTest import QTest

    from pet.claude_session_jump import JumpResult
    from pet.session_pet_ui import SessionPetActions

    persistent.history_store.record("claude_wsl", "old-2222-bbbb", seen=NOW - 3600, cwd="/home/me/proj",
                                    entrypoint="claude-vscode", distro="Ubuntu-24.04")
    persistent.reconcile()
    sprite = _session_pets(shell)[0]
    actions = SessionPetActions(shell, persistent, anchor_factory=lambda s: None)
    handed: list = []
    found = {"label": "deploy", "target": "/home/me/ws/deploy.code-workspace", "multi_root": True,
             "roots": ["/home/me/proj"], "folders": 1}
    actions.vscode_resumer = lambda detail: handed.append(detail) or JumpResult(True, "ok")
    actions.workspace_finder = lambda sid, **kwargs: found if (sid, kwargs) == (
        "old-2222-bbbb", {"wsl": True, "distro": "Ubuntu-24.04"}) else {}
    assert actions.jump(sprite) is True
    for _ in range(100):
        if handed and persistent.history_store.entries()[0].workspace:
            break
        QTest.qWait(20)
    assert handed[0].extra["workspace"] == found
    entry = persistent.history_store.entries()[0]
    assert entry.workspace["target"] == "/home/me/ws/deploy.code-workspace", "找回来的顺手记进历史"
    assert entry.last_seen == NOW - 3600, "补记不改最后活动时间"
    assert persistent.describe(("claude_wsl", "old-2222-bbbb"))["workspace"] == entry.workspace


def test_a_live_fish_s_detail_card_notes_the_workspace_into_the_history(shell, persistent):
    """活着的会话打开详情卡 / 跳转时认出了工作区：记进「最近的对话」，将来冻结后按它重开。"""
    from pet import claude_session_info
    from pet.session_pet_ui import SessionPetActions

    persistent.on_session_update("claude_wsl", _adopted("live-1111-aaaa", cwd="/home/me/proj"))
    persistent.history_store.record("claude_wsl", "live-1111-aaaa", cwd="/home/me/proj", entrypoint="claude-vscode")
    actions = SessionPetActions(shell, persistent, anchor_factory=lambda s: None)
    detail = claude_session_info.SessionDetail(agent="claude_wsl", session_id="live-1111-aaaa", cwd="/home/me/proj",
                                               extra={"workspace": {"label": "ops", "target": "/home/me/ws/ops.code-workspace",
                                                                    "multi_root": True, "roots": ["/home/me/proj"], "folders": 1}})
    actions._on_detail_ready(("claude_wsl", "live-1111-aaaa"), detail)
    (entry,) = [e for e in persistent.history_store.entries() if e.session_id == "live-1111-aaaa"]
    assert entry.workspace == {"label": "ops", "target": "/home/me/ws/ops.code-workspace", "multi_root": True,
                               "roots": ["/home/me/proj"]}


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


# ---------------------------------------------------------------- 来源图标

def test_the_fish_shows_where_its_session_runs_next_to_the_label(shell, controller):
    """用户 2026-11-02：看不出哪只是 VS Code / 桌面版 / 终端。规则与详情卡同一份（``host_kind``）。"""
    controller.on_session_update("claude", _update(project="p") | {"entrypoint": "claude-vscode"})
    controller.on_session_update("claude_wsl", _update("B", project="p") | {"entrypoint": "cli"})
    controller.on_session_update("claude", _update("C", project="p") | {"entrypoint": "claude-desktop"})
    controller.on_session_update("claude", _update("D", project="p"))
    hosts = {controller.key_of(s)[1]: s.caption_host for s in _session_pets(shell)}
    assert hosts == {"A": "vscode", "B": "wsl", "C": "desktop", "D": ""}, "D 还不知道从哪开的：先不画"

    controller.on_session_update("claude", _update("D", project="p") | {"entrypoint": "cli"})
    assert controller.sprite_of(("claude", "D")).caption_host == "terminal", "运行清单补上入口后就有了"
    controller.on_session_update("claude", _update("D", phase="resting", project="p"))
    assert controller.sprite_of(("claude", "D")).caption_host == "terminal", "换阶段不丢"
    assert controller.remodel(("claude", "A"), "claude-fable-5-1") is True
    assert controller.sprite_of(("claude", "A")).caption_host == "vscode", "戴桂冠不丢"


def test_a_frozen_fish_shows_where_the_conversation_was_opened(shell, persistent):
    persistent.history_store.record("claude", "old-1111-aaaa", seen=NOW - 3600, cwd=r"C:\Users\me\Pet",
                                    entrypoint="claude-vscode")
    persistent.history_store.record("claude_wsl", "old-2222-aaaa", seen=NOW - 7200, cwd="/home/me/pet",
                                    entrypoint="cli")
    persistent.reconcile()
    hosts = {persistent.key_of(s)[1]: s.caption_host for s in _session_pets(shell)}
    assert hosts == {"old-1111-aaaa": "vscode", "old-2222-aaaa": "wsl"}
