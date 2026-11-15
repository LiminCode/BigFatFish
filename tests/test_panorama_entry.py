# -*- coding: utf-8 -*-
"""配置全景的两个入口：右键菜单里的一项、岛上「模型连接」面板里的一个按钮，以及它们在 AppShell 里通到哪。"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QMenu

from pet import i18n
from pet.context_menus.registry import ACTION_ICONS, ACTION_LABELS, MENU_ACTIONS

app = QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _chinese():
    i18n.set_language("zh")
    yield
    i18n.set_language("zh")


class _FakeService:
    """替掉真服务：记下被打开了几次、体检结论读到什么，不起线程、不开浏览器。"""
    made: list = []

    def __init__(self, config, *, health=None, parent=None):
        self.config, self.health, self.opened = config, health, 0
        _FakeService.made.append(self)

    def open(self):
        self.opened += 1
        return True


@pytest.fixture
def fake_service(monkeypatch):
    from pet.panorama import service

    _FakeService.made = []
    monkeypatch.setattr(service, "PanoramaService", _FakeService)
    return _FakeService


# ---------------------------------------------------------------- 右键菜单

def test_menu_item_is_registered_with_a_label_and_an_icon():
    assert ACTION_LABELS["config_panorama"] == "配置全景" and ACTION_ICONS["config_panorama"] == "branch"
    assert "config_panorama" in MENU_ACTIONS.ids
    assert MENU_ACTIONS.label("config_panorama") == "配置全景"


class _Host:
    """菜单宿主的最小替身：没接的回调一律是 None（和没接线的窗口一样）。"""
    cfg: dict = {}

    def __init__(self, **callbacks):
        self.__dict__.update(callbacks)

    def __getattr__(self, name):
        return None


def test_menu_item_shows_only_for_a_host_that_can_open_it_and_calls_it():
    called = []
    host = _Host(on_open_config_panorama=lambda: called.append(True))
    assert "config_panorama" in MENU_ACTIONS.available_ids(host)
    assert "config_panorama" not in MENU_ACTIONS.available_ids(_Host())
    menu = QMenu()
    MENU_ACTIONS.populate(menu, host, [{"type": "action", "id": "config_panorama", "visible": True}])
    actions = [a for a in menu.actions() if not a.isSeparator()]
    assert [a.text() for a in actions] == ["配置全景"]
    actions[0].trigger()
    assert called == [True]


def test_english_menu_label_has_no_chinese():
    i18n.set_language("en")
    assert MENU_ACTIONS.label("config_panorama") == "Config panorama"


def test_default_layout_puts_it_in_tools_before_settings():
    import json
    from pathlib import Path

    import pet.menu_templates as templates

    nodes = json.loads((Path(templates.__file__).parent / "modern-default-v1.json").read_text(encoding="utf-8"))

    def flat(items):
        for item in items:
            yield item
            yield from flat(item.get("children") or [])

    rows = [n for n in flat(nodes["nodes"] if isinstance(nodes, dict) else nodes) if n.get("type") == "action"]
    ids = [n["id"] for n in rows]
    node = rows[ids.index("config_panorama")]
    assert node["visible"] is True and node["section"] == "tools"
    assert ids.index("todo_panel") < ids.index("config_panorama") < ids.index("modern_settings")


# ---------------------------------------------------------------- 岛的「模型连接」面板

def test_panel_button_asks_for_the_panorama_and_folds_the_panel():
    from tests.test_island_connections import _panel

    panel, _probed, _spawn, _monitor, _now = _panel()
    try:
        asked = []
        panel.panorama_requested.connect(lambda: asked.append(True))
        panel.toggle(QRect(700, 900, 300, 44), QRect(0, 0, 1920, 1040))
        button = panel.window.panorama_btn
        assert button.text() == "配置全景" and button.objectName() == "connectionsAction" and button.toolTip()
        button.click()
        assert asked == [True] and not panel.is_open(), "去看全景：面板收起"
    finally:
        panel.close()


def test_the_new_button_sits_on_its_own_row_and_never_widens_the_panel():
    """英文下原来两个按钮已经比磁贴宽：第三个再并排会把面板撑得更宽，所以另起一行。"""
    from pet.island_connections_ui import ConnectionsWindow

    for language in ("zh", "en"):
        i18n.set_language(language)
        window = ConnectionsWindow()
        try:
            window.adjustSize()
            window.layout().activate()
            first_row = window.recheck_btn.sizeHint().width() + window.settings_btn.sizeHint().width()
            assert window.panorama_btn.sizeHint().width() <= first_row, language
            assert window.panorama_btn.geometry().top() >= window.recheck_btn.geometry().bottom(), f"{language}: 应该在下一行"
            assert window.panorama_btn.geometry().left() == window.recheck_btn.geometry().left(), language
        finally:
            window.deleteLater()


# ---------------------------------------------------------------- AppShell

def test_shell_opens_the_panorama_from_the_island_panel_and_reuses_one_service(tmp_path, fake_service):
    from tests.test_island_shell_wiring import _make_shell, _teardown_shell

    shell = _make_shell(tmp_path)
    shell.app = app
    try:
        shell._sync_dynamic_island()
        shell.island.connections_requested.emit()
        panel = shell._connections_panel
        panel.window.panorama_btn.click()
        assert len(fake_service.made) == 1 and fake_service.made[0].opened == 1
        assert fake_service.made[0].config is shell.config
        shell._api_key_monitor.status_changed.emit("bad", "DeepSeek · 认证失败")
        state, _detail = fake_service.made[0].health()
        assert state == shell._api_key_monitor.state                        # 体检结论取自岛上的体检器
        shell.open_config_panorama()                                        # 右键菜单走的是同一个方法
        assert len(fake_service.made) == 1 and fake_service.made[0].opened == 2
    finally:
        panel = getattr(shell, "_connections_panel", None)
        if panel is not None:
            panel.close()
        _teardown_shell(shell)


def test_without_an_island_the_health_is_simply_unknown(tmp_path, fake_service):
    from tests.test_island_shell_wiring import _make_shell, _teardown_shell

    shell = _make_shell(tmp_path)
    shell.app = app
    try:
        shell.open_config_panorama()
        assert fake_service.made[0].health() == ("unknown", "")
    finally:
        _teardown_shell(shell)
