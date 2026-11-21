# -*- coding: utf-8 -*-
"""工作简报的阅读页搬到浏览器之后，肥鱼这一侧的行为（2026-11-19；11-21 删掉 Qt 窗口后收口）：

- 控制器只认「开报告页」那条路：「查看」开浏览器、打开即算读过、开不了冒气泡；页面开着看时新一份不再冒提醒；
- 没接页面（测试、旧接线）时「查看」也只能冒那句气泡：Qt 的 ``WorkBriefingWindow`` 没有了；
- 气泡文字跟界面语言；
- 右键菜单：「生成时间」子菜单没了，多一条「简报设置…」翻到配置全景那一组。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from pet import claude_hooks, i18n  # noqa: E402
from pet import work_briefing as wb  # noqa: E402
from pet import work_briefing_ui as ui  # noqa: E402
from pet.config import Config  # noqa: E402
from pet.context_menus import shared  # noqa: E402
from pet.sprite_menu_facade import SpriteMenuFacade  # noqa: E402
from pet.work_briefing_service import WorkBriefingService  # noqa: E402
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
    assert opens == [1] and not hasattr(controller, "window"), "开的是浏览器里的页；Qt 窗口没有了"
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


def test_without_the_browser_path_view_can_only_say_so(tmp_path):
    """没接 ``open_report``（旧接线、测试）：没有第二个看简报的地方了，「查看」只能说页打不开，未读也不算读过。"""
    service, _made, _finished = _service(tmp_path)
    host = FakeHost()
    controller = ui.WorkBriefingController(host, service)
    service.check()
    app.processEvents()
    assert controller.island_state == "unread"
    controller.open_window()
    assert host.bubbles == ["简报页打不开：本机服务起不来，看日志里「配置全景」那几行"] and controller.island_state == "unread"


def test_the_bubbles_speak_english(tmp_path):
    config = Config(base=tmp_path)
    config.set("ui_language", "en")
    host = FakeHost()
    service = WorkBriefingService(config, generate=lambda when, model, **_kw: wb.Briefing(error="boom"), spawn=lambda run: run())
    controller = ui.WorkBriefingController(host, service, open_report=lambda: False)
    controller.generate_now()
    # spawn 是同步的：失败那句先于「出发」那句冒出来，只看两句都在
    assert any(b.startswith("Off to see") for b in host.bubbles)
    assert any(b.startswith("Couldn't generate the briefing: boom") for b in host.bubbles)
    controller.open_window()
    assert host.bubbles[-1].startswith("Couldn't open the briefing page")
    zh, en = i18n.table("zh"), i18n.table("en")
    keys = [k for k in zh if k.startswith(("briefing.", "slack."))]
    assert len(keys) >= 25 and all(k in en for k in keys)


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
