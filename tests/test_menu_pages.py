# -*- coding: utf-8 -*-
"""右键菜单重排（2026-11-21，用户：「浏览器页面要放在第一层」）：

- 根菜单第一组是五张页：工作简报 / 个人简报 / 工作笔记 / Slack 关注 / 配置全景；AI 对话 / 待办 / 会话记忆蒸馏一组；
  Agent 联动里不再有页；护驾 / 列队 11-21 收进「肥鱼控制」，11-25 用户说天天用，又回到根菜单紧跟彩蛋；
- 一项一件事：点了只开页（笔记开到列表，别的开页），没有子菜单；
- 壳上没挂控制器的页整项不出现（这台机器没 WSL / 没装聊天模块 / 功能关着）；
- 旧版扁平菜单、托盘菜单用同一张表；英文界面下的名字。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet.context_menus.registry import MENU_ACTIONS
from pet.context_menus.shared import PAGE_ENTRIES
from tests.test_session_pet_details import shell  # noqa: F401 - shell 是 fixture
from tests.test_work_briefing import _find

app = QApplication.instance() or QApplication([])
PAGES = ["工作简报", "个人简报", "工作笔记", "Slack 关注"]


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


class _Controller:
    def __init__(self, log, name):
        self._log, self._name = log, name

    def open_window(self):
        self._log.append(self._name)


class _Notes(_Controller):
    def open_notes(self, name=""):
        self._log.append((self._name, name))


def _mount(shell_):
    log = []
    shell_.work_briefing = _Controller(log, "work_briefing")
    shell_.personal = _Controller(log, "personal")
    shell_.work_notes = _Notes(log, "work_notes")
    shell_.slack_watch = _Controller(log, "slack_watch")
    shell_.memory_distill = _Controller(log, "memory_distill")
    return log


def _root(menu):
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def test_the_pages_are_the_first_group_and_each_entry_only_opens_its_page(shell):  # noqa: F811
    log = _mount(shell)
    menu = shell._build_menu_for(shell.sprite)
    root = _root(menu)
    assert root[1:3] == ["护驾", "列队"], root
    assert root[3:7] == PAGES, root
    assert root.index("Slack 关注") < root.index("AI 对话") < root.index("会话记忆蒸馏") < root.index("肥鱼控制") < root.index("Agent 联动")
    for label in PAGES + ["会话记忆蒸馏"]:
        assert _find(menu, label).menu() is None, f"{label} 不该是子菜单"
    agent_link = _find(menu, "Agent 联动").menu()
    assert not {a.text() for a in agent_link.actions()} & set(PAGES + ["会话记忆蒸馏"]), "Agent 联动里只剩通道和会话小鱼"
    controls = _find(menu, "肥鱼控制").menu()
    assert not {"护驾", "列队"} & set(_root(controls))
    for label in PAGES + ["会话记忆蒸馏"]:
        _find(menu, label).trigger()
    assert log == ["work_briefing", "personal", ("work_notes", ""), "slack_watch", "memory_distill"]
    icons = {action_id: MENU_ACTIONS.default_icon(action_id) for action_id, *_rest in PAGE_ENTRIES}
    assert icons == {"work_briefing": "briefing", "personal_briefing": "person", "work_notes": "note", "slack_watch": "slack",
                     "memory_distill": "automation"}
    assert all(not _find(menu, label).icon().isNull() for label in PAGES)


def test_pages_without_a_controller_do_not_appear(shell):  # noqa: F811
    root = _root(shell._build_menu_for(shell.sprite))
    assert not set(root) & set(PAGES + ["会话记忆蒸馏"])
    shell.work_notes = _Notes([], "work_notes")
    root = _root(shell._build_menu_for(shell.sprite))
    assert "工作笔记" in root and not set(root) & {"工作简报", "个人简报", "Slack 关注"}, "只出现挂了控制器的那张"


def test_the_legacy_menu_lists_the_same_pages_flat(shell):  # noqa: F811
    log = _mount(shell)
    shell._config.set("context_menu_template", "legacy")
    menu = shell._build_menu_for(shell.sprite)
    root = _root(menu)
    assert [label for label in root if label in PAGES + ["会话记忆蒸馏"]] == PAGES + ["会话记忆蒸馏"]
    assert all(_find(menu, label).menu() is None and _find(menu, label).icon().isNull() for label in PAGES), "旧版约定无图标"
    _find(menu, "个人简报").trigger()
    assert log == ["personal"]


def test_the_pages_speak_english(shell):  # noqa: F811
    _mount(shell)
    shell._config.set("ui_language", "en")
    try:
        root = _root(shell._build_menu_for(shell.sprite))
        assert root[3:7] == ["Work briefing", "Personal briefing", "Work notes", "Slack watch"] and "Session memory distill" in root
    finally:
        i18n.set_language("zh")


def test_the_tray_menu_lists_the_pages_too(tmp_path):
    from tests.test_overlay_spawn import _make_persistent_shell

    shell_, _ = _make_persistent_shell(tmp_path, {})
    try:
        log = _mount(shell_)
        shell_._refresh_tray_menu()
        labels = [a.text() for a in shell_.tray.contextMenu().actions() if not a.isSeparator()]
        start = labels.index("工作简报")
        assert labels[start:start + 5] == PAGES + ["会话记忆蒸馏"] and labels.index("退出子肥鱼") < start < labels.index("肥鱼设置")
        for action in shell_.tray.contextMenu().actions():
            if action.text() in ("工作笔记", "个人简报"):
                action.trigger()
        assert log == [("work_notes", ""), "personal"] or log == ["personal", ("work_notes", "")]
    finally:
        shell_._teardown_settings_command_watch()
        shell_._delete_runtime_marker()
        if getattr(shell_, "tray", None) is not None:
            shell_.tray.hide()
