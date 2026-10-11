# -*- coding: utf-8 -*-
"""「最近的对话」接进灵动岛：卡片里的折叠框 ← 历史服务 ← 两个 Claude Code 通道。

三层：岛（折叠框放在卡片里、高度跟着长、开着时不自动收起）、AppShell（数据进岛、
点一行做什么）、OverlayShell（服务的生灭与配置开关）。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QMenu

from pet.claude_session_history import HISTORY_FILE, SessionHistory
from pet.config import APP_DIR_NAME, Config
from pet.context_menus import shared as menu_shared
from pet.dynamic_island import _CAPSULE_HEIGHT, DynamicIsland
from pet.island_history_panel import ROW_HEIGHT
from pet.session_history_service import SessionHistoryService
from tests.test_island_shell_wiring import _FakeSessionRegistry, _make_shell, _teardown_shell
from tests.test_overlay_spawn import _make_persistent_shell

app = QApplication.instance() or QApplication([])

SID_A = "11111111-aaaa-4bbb-8ccc-000000000001"
SID_B = "22222222-aaaa-4bbb-8ccc-000000000002"
ROWS = [
    {"key": ("claude", SID_A), "label": "Fix login loop", "where": "终端", "path": "C:\\work\\api",
     "ago": "昨天", "live": False},
    {"key": ("claude", SID_B), "label": "web", "where": "VS Code", "path": "C:\\work\\web",
     "ago": "2 天前", "live": False},
]


# ---------------------------------------------------------------- 岛

@pytest.fixture
def island(tmp_path):
    cfg = Config(base=tmp_path)
    cfg.set("dynamic_island", {"enabled": True, "x": 400, "y": 300, "style": "light"})
    island = DynamicIsland(cfg)
    island.show()
    yield island
    island.deleteLater()
    app.processEvents()


def _expand(island) -> None:
    island.expand_card()
    island._finish_animations()
    app.processEvents()


def test_card_is_unchanged_when_there_is_no_history(island):
    _expand(island)
    assert island._history_panel.isHidden()
    plain = island.height()
    island.set_session_history([])
    island._finish_animations()
    assert island.height() == plain


def test_history_shows_up_folded_then_grows_the_card_when_opened(island):
    _expand(island)
    plain = island.height()

    island.set_session_history(ROWS)
    island._finish_animations()
    app.processEvents()
    assert not island._history_panel.isHidden()
    folded = island.height()
    assert plain <= folded < plain + ROW_HEIGHT * 2, "折着只多一行标题"

    toggles = []
    island.history_toggled.connect(toggles.append)
    island._history_panel.header.click()
    island._finish_animations()
    app.processEvents()
    panel = island._history_panel
    assert island.height() > folded, "卡片长高（默认高度里的余量先被用掉，所以不是整整多出两行）"
    assert panel.body.height() == len(ROWS) * ROW_HEIGHT and panel.height() >= panel.body.height(), \
        "每一行都完整露出来，没被压扁"
    assert toggles == [True]
    box = island._card_box
    assert box.geometry().bottom() < island.height()
    for button in (island._card_toggle_btn, island._card_chat_btn, island._card_settings_btn):
        assert button.geometry().bottom() < box.height(), "按钮没被挤出卡片"

    island._history_panel.header.click()
    island._finish_animations()
    assert island.height() == folded


def test_restored_open_state_does_not_echo(island):
    toggles = []
    island.history_toggled.connect(toggles.append)
    island.set_session_history(ROWS, is_open=True)
    _expand(island)
    assert island._history_panel.is_open() and toggles == []
    assert island.height() >= _CAPSULE_HEIGHT + len(ROWS) * ROW_HEIGHT


def test_card_does_not_auto_collapse_while_the_list_is_open(island):
    island.set_session_history(ROWS)
    _expand(island)
    assert island._card_collapse_timer.isActive()

    island._history_panel.header.click()
    assert not island._card_collapse_timer.isActive(), "正在列表里找对话：别 15 秒就收走"
    island._history_panel.header.click()
    assert island._card_collapse_timer.isActive()

    island.collapse_card(animate=False)
    island.set_session_history(ROWS, is_open=True)
    _expand(island)
    assert not island._card_collapse_timer.isActive(), "上次就开着：展开卡片时同样不计时"


def test_row_clicks_and_menu_choices_come_out_of_the_island(island):
    seen = []
    island.history_activated.connect(lambda key: seen.append(("activated", key)))
    island.history_action.connect(lambda action, key: seen.append((action, key)))
    island.set_session_history(ROWS, is_open=True)
    _expand(island)

    island._history_panel.activated.emit(("claude", SID_A))
    island._history_panel.action_requested.emit("copy_path", ("claude", SID_B))
    assert seen == [("activated", ("claude", SID_A)), ("copy_path", ("claude", SID_B))]

    island.show_history_status("路径已复制")
    assert island._history_panel.header.text() == "路径已复制"


def test_panel_follows_the_island_theme_and_card_width(island):
    island.set_session_history(ROWS, is_open=True)
    _expand(island)
    assert island._history_panel._width == island._card_width() - 32
    data = dict(island._cfg)
    data["style"] = "dark"
    island.config.set("dynamic_island", data)
    island.refresh_from_config()
    assert island._history_panel._colors["primary"] != "#202124"


# ---------------------------------------------------------------- AppShell

class _Recorder:
    def __init__(self) -> None:
        self.activated, self.ran, self.jumped = [], [], []

    def activate(self, entry) -> str:
        self.activated.append(entry.key)
        return "已在终端里恢复"

    def run(self, action, entry) -> str:
        self.ran.append((action, entry.key))
        return "路径已复制"

    def jump_key(self, key) -> bool:
        self.jumped.append(tuple(key))
        return True


@pytest.fixture
def app_shell(tmp_path):
    shell = _make_shell(tmp_path)
    shell._sync_dynamic_island()
    store = SessionHistory(None)
    service = SessionHistoryService(store, scan_local=lambda **_k: [], scan_wsl=lambda **_k: [],
                                    spawn=lambda fn: fn())
    recorder = _Recorder()
    shell._overlay_shell = SimpleNamespace(
        session_pets=_FakeSessionRegistry([]), session_history=service, session_actions=recorder)
    shell._session_history_actions = recorder
    shell._wire_session_history()
    shell.recorder, shell.service = recorder, service
    yield shell
    _teardown_shell(shell)


def _live(shell, sid=SID_A, **fields):
    shell.service.on_session_update("claude", {"sessionId": sid, "phase": "working", **fields})


def test_recorded_sessions_appear_on_the_island(app_shell):
    _live(app_shell, cwd="C:\\work\\api", title="Fix login loop")
    rows = app_shell.island._history_panel._rows
    assert [(r["key"], r["label"], r["path"], r["ago"], r["live"]) for r in rows] == [
        (("claude", SID_A), "Fix login loop", "C:\\work\\api", "刚刚", False)]


def test_sessions_still_open_are_marked_live(app_shell):
    _live(app_shell, cwd="C:\\work\\api")
    app_shell._overlay_shell.session_pets._sessions = [{"agent": "claude", "sessionId": SID_A, "phase": "working",
                                                        "title": "", "project": "api"}]
    app_shell._on_claude_sessions_changed()
    assert app_shell.island._history_panel._rows[0]["live"] is True


def test_expanding_the_card_refreshes_the_list_from_disk(app_shell):
    found = [{"agent": "claude", "session_id": SID_B, "cwd": "C:\\old", "title": "Yesterday", "seen": None}]
    app_shell.service._scan_local = lambda **_k: found
    app_shell.island.expand_card()
    assert [r["label"] for r in app_shell.island._history_panel._rows] == ["Yesterday"]


def test_clicking_a_closed_session_goes_back_to_it(app_shell):
    _live(app_shell, cwd="C:\\work\\api")
    app_shell.island.history_activated.emit(("claude", SID_A))
    assert app_shell.recorder.activated == [("claude", SID_A)] and app_shell.recorder.jumped == []
    assert app_shell.island._history_panel.header.text() == "已在终端里恢复"


def test_clicking_a_live_session_jumps_to_its_window(app_shell):
    _live(app_shell, cwd="C:\\work\\api")
    app_shell._overlay_shell.session_pets._sessions = [{"agent": "claude", "sessionId": SID_A, "phase": "working"}]
    app_shell.island.history_activated.emit(("claude", SID_A))
    assert app_shell.recorder.jumped == [("claude", SID_A)] and app_shell.recorder.activated == [], \
        "还开着的对话：切到它的窗口，而不是再恢复一份"


def test_menu_actions_are_routed(app_shell):
    _live(app_shell, cwd="C:\\work\\api")
    _live(app_shell, SID_B, cwd="C:\\work\\web")

    app_shell.island.history_action.emit("copy_path", ("claude", SID_A))
    assert app_shell.recorder.ran == [("copy_path", ("claude", SID_A))]

    app_shell.island.history_action.emit("remove", ("claude", SID_A))
    assert [r["key"] for r in app_shell.island._history_panel._rows] == [("claude", SID_B)]

    app_shell.island.history_action.emit("clear", ("claude", SID_B))
    assert app_shell.island._history_panel._rows == []


def test_a_row_that_vanished_meanwhile_is_ignored(app_shell):
    app_shell.island.history_activated.emit(("claude", "gone"))
    app_shell.island.history_action.emit("copy_path", ("claude", "gone"))
    assert app_shell.recorder.activated == [] and app_shell.recorder.ran == []


def test_folding_is_remembered(app_shell):
    _live(app_shell, cwd="C:\\work\\api")
    app_shell.island.history_toggled.emit(True)
    assert app_shell.service.ui_open is True


# ---------------------------------------------------------------- OverlayShell

@pytest.fixture
def overlay_shell(tmp_path):
    shell, _made = _make_persistent_shell(tmp_path)
    try:
        yield shell
    finally:
        shell._delete_runtime_marker()


def test_overlay_shell_owns_a_history_service_backed_by_the_config_dir(overlay_shell, tmp_path):
    service = overlay_shell.session_history
    assert isinstance(service, SessionHistoryService)
    service.on_session_update("claude", {"sessionId": SID_A, "phase": "working", "cwd": "C:\\work\\api"})
    overlay_shell._flush_session_history()               # 退出步骤
    saved = SessionHistory(Path(tmp_path) / APP_DIR_NAME / HISTORY_FILE)
    saved.load()
    assert [e.cwd for e in saved.entries()] == ["C:\\work\\api"]


def test_history_can_be_switched_off_and_limits_follow_the_config(overlay_shell):
    service = overlay_shell.session_history
    service.on_session_update("claude", {"sessionId": SID_A, "phase": "working", "cwd": "C:\\a"})
    data = dict(overlay_shell._config.get("agent_link"))
    data.update(session_history_days=3, session_history_max=5)
    overlay_shell._config.set("agent_link", data)
    assert len(service.entries()) == 1
    assert (service.store.max_age_days, service.store.max_entries) == (3, 5)

    data["session_history"] = False
    overlay_shell._config.set("agent_link", data)
    assert service.entries() == []


@pytest.mark.parametrize("raw, expected", [
    ({}, (True, 7, 30)),
    ({"session_history": 0, "session_history_days": "3", "session_history_max": 999}, (False, 3, 200)),
    ({"session_history_days": 0, "session_history_max": "x"}, (True, 1, 30)),
])
def test_history_config_is_normalised(tmp_path, raw, expected):
    cfg = Config(base=tmp_path)
    data = dict(cfg.get("agent_link"))
    data.update(raw)
    cfg.set("agent_link", data)
    cfg.save()
    link = Config(base=tmp_path).get("agent_link")
    assert (link["session_history"], link["session_history_days"], link["session_history_max"]) == expected


# ---------------------------------------------------------------- 开关入口

class _MenuPet:
    def __init__(self, cfg, *, with_toggle: bool) -> None:
        self.cfg = cfg
        self.toggled: list = []
        if with_toggle:
            self.toggle_session_history = self.toggled.append

    def toggle_agent_link(self, *_args) -> None:
        pass


def _menu_actions(pet) -> dict:
    menu = QMenu()
    menu_shared.add_agent_link_menu(menu, pet)
    submenu = menu.actions()[0].menu()
    pet.keep_alive = (menu, submenu)
    return {a.text(): a for a in submenu.actions() if not a.isSeparator()}


def test_agent_link_menu_has_the_switch_only_where_the_feature_exists(tmp_path):
    assert "记录最近的对话" not in _menu_actions(_MenuPet(Config(base=tmp_path), with_toggle=False))

    pet = _MenuPet(Config(base=tmp_path), with_toggle=True)
    action = _menu_actions(pet)["记录最近的对话"]
    assert action.isCheckable() and action.isChecked() is True
    action.trigger()
    assert pet.toggled == [False]


def test_facade_toggle_persists_and_refreshes_the_island(overlay_shell):
    from pet.sprite_menu_facade import SpriteMenuFacade

    seen = []
    overlay_shell.session_history.changed.connect(lambda: seen.append(1))
    SpriteMenuFacade(overlay_shell).toggle_session_history(False)
    assert overlay_shell._config.get("agent_link")["session_history"] is False
    assert seen == [1], "关掉后岛上的列表要立刻收走"
