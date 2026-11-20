# -*- coding: utf-8 -*-
"""工作简报的阅读页搬到浏览器之后，肥鱼这一侧的行为（2026-11-19）：

- 控制器接了「开报告页」那条路：「查看」开浏览器、打开即算读过、开不了冒气泡；页面开着看时新一份不再冒提醒；
- Qt 的 ``WorkBriefingWindow`` 只剩给笔记 / Slack 关注当壳：不带「简报」页；
- 右键菜单：「生成时间」子菜单没了，多一条「简报设置…」翻到配置全景那一组。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QMenu  # noqa: E402

from pet import claude_hooks, i18n  # noqa: E402
from pet import work_briefing_ui as ui  # noqa: E402
from pet.context_menus import shared  # noqa: E402
from pet.sprite_menu_facade import SpriteMenuFacade  # noqa: E402
from tests.test_work_briefing import FakeHost, _service  # noqa: E402

app = QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _chinese():
    i18n.set_language("zh")
    yield
    i18n.set_language("zh")


def _controller(tmp_path, *, opened=True, watched=False, **kwargs):
    service, made, _finished = _service(tmp_path, **kwargs)
    host, opens = FakeHost(), []
    controller = ui.WorkBriefingController(host, service, open_report=lambda: (opens.append(1), opened)[1],
                                           report_watched=lambda: watched)
    return controller, host, service, opens


def test_view_opens_the_browser_page_and_counts_as_read(tmp_path):
    controller, host, service, opens = _controller(tmp_path)
    states = []
    controller.state_changed.connect(states.append)
    service.check()
    app.processEvents()
    assert controller.island_state == "unread" and len(host.alerts) == 1

    controller.open_window()
    assert opens == [1] and controller.window is None, "开的是浏览器里的页，不是 Qt 窗口"
    assert controller.island_state == "idle" and states == ["unread", "idle"] and host.bubbles == []

    (_text, kwargs), = host.alerts
    dict(kwargs["buttons"])["查看"]()
    assert opens == [1, 1] and host.resolved == [ui.ALERT_ID], "提醒上的「查看」走同一条路"


def test_a_page_that_cannot_open_says_so_in_a_bubble(tmp_path):
    controller, host, _service_, opens = _controller(tmp_path, opened=False)
    controller.open_window()
    assert opens == [1] and host.bubbles == ["简报页打不开：本机服务起不来，看日志里「配置全景」那几行"]


def test_no_alert_while_the_page_is_open_in_the_browser(tmp_path):
    controller, host, service, _opens = _controller(tmp_path, watched=True)
    service.check()
    app.processEvents()
    assert host.alerts == [] and controller.island_state == "idle", "页面已经原地换成新的了"


def test_the_qt_window_is_only_a_shell_for_the_other_tabs(tmp_path):
    controller, _host, _service_, opens = _controller(tmp_path)
    controller.tab_providers.append(lambda: [("笔记", QLabel("n"))])
    controller.open_window(tab="笔记")
    try:
        assert opens == [], "给了 tab 开的是 Qt 窗口（那几页还在 Qt 里）"
        tabs = controller.window.tabs
        assert [tabs.tabText(i) for i in range(tabs.count())] == ["笔记"], "没有「简报」那一页"
        assert controller.window.briefing_page.isHidden()
    finally:
        controller.window.close()


def test_without_the_browser_path_the_old_window_still_has_its_briefing_page(tmp_path):
    service, _made, _finished = _service(tmp_path)
    controller = ui.WorkBriefingController(FakeHost(), service)
    controller.open_window()
    try:
        assert controller.window.tabs.tabText(0) == "简报"
    finally:
        controller.window.close()


# ---------------------------------------------------------------- 菜单

def _pet(**extra):
    calls = []
    return SimpleNamespace(
        work_briefing_settings=lambda: {"enabled": True, "time": "09:00"},
        open_work_briefing=lambda: calls.append("view"), generate_work_briefing=lambda: calls.append("generate"),
        toggle_work_briefing=lambda on: calls.append(("toggle", on)), **extra), calls


def _texts(menu: QMenu) -> list[str]:
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def test_the_briefing_menu_keeps_the_switch_and_commands_but_sends_values_to_the_panorama(monkeypatch):
    monkeypatch.setattr(claude_hooks, "wsl_exe", lambda: "wsl.exe")
    pet, calls = _pet(open_work_briefing_settings=lambda: calls.append("settings"))
    menu = QMenu()
    shared.add_work_briefing_menu(menu, pet)
    sub = menu.actions()[0].menu()
    assert menu.actions()[0].text() == "工作简报"
    assert _texts(sub) == ["查看最近一份", "现在生成", "工作日自动生成", "简报设置…"]
    assert all(a.menu() is None for a in sub.actions()), "没有「生成时间」这类选值子菜单了：在配置全景上改"
    sub.actions()[-1].trigger()
    assert calls == ["settings"]


def test_the_settings_entry_opens_the_panorama_at_the_briefing_group():
    opened = []
    SpriteMenuFacade.open_work_briefing_settings(SimpleNamespace(on_open_config_panorama=lambda focus="": opened.append(focus)))
    assert opened == ["work_briefing"]
    assert not hasattr(SpriteMenuFacade, "set_work_briefing_time"), "时间只在配置全景上改"
