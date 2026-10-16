# -*- coding: utf-8 -*-
"""右键菜单的英文界面（用户 2026-10-16：「go ahead for the 右键菜单」）。

守住的：
- 界面语言是 English 时，新版 / 旧版两种模板的右键菜单（含所有子菜单与置灰提示）没有中文，只剩彩蛋那一行的
  标题——它是配置里的内容（默认「厉害了我的鲸」，可在设置里改），不是界面文字；
- 会话小鱼的右键菜单、托盘菜单（含逐只子菜单标题）英文；
- 按文字找锚点的两处（新项插在「退出」前、「隐藏肥鱼」接在「退出子肥鱼」后）英文下照样对得上；
- 模板自带的子菜单（「肥鱼控制」「工具与帮助」）即使存在用户保存的编排里，英文下也翻译；用户自建 / 改过名的原样；
- 导入时求值的表（动作名、图标选项、开关标签、置灰原因）显示时跟随语言；
- 中文界面不受影响；menu.* 键中英占位符一致。
"""
from __future__ import annotations

import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet.context_menus.registry import MENU_ACTIONS, icon_choice_label
from tests.test_session_pet_details import _session, shell  # noqa: F401 - shell 是 fixture
from tests.test_sprite_menu_parity import _make_overlay

app = QApplication.instance() or QApplication([])
CJK = re.compile(r"[\u4e00-\u9fff]")
EGG_TITLE = "厉害了我的鲸"


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


@pytest.fixture
def stubs(monkeypatch):
    import pet.autostart as autostart_mod
    import pet.catalog as catalog_mod
    from pet import claude_hooks

    monkeypatch.setattr(autostart_mod, "is_enabled", lambda: False)
    monkeypatch.setattr(catalog_mod, "list_available_characters", lambda: ["shenshen"])
    monkeypatch.setattr(claude_hooks, "wsl_exe", lambda: r"C:\Windows\System32\wsl.exe")


def _walk(menu, path=()):
    for action in menu.actions():
        if action.isSeparator():
            continue
        yield path, action
        if action.menu() is not None:
            yield from _walk(action.menu(), path + (action.text(),))


def _labels(menu) -> list[str]:
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def _menu(tmp_path, template: str, language: str):
    from pet.sprite_menu_facade import build_sprite_full_menu

    shell_, _instance, _config = _make_overlay(tmp_path, template=template, values={"ui_language": language})
    menu = build_sprite_full_menu(shell_)
    shell_.keep_alive = menu
    return shell_, menu


@pytest.mark.parametrize("template", ["modern", "legacy"])
def test_the_english_right_click_menu_has_no_chinese_but_the_easter_egg_title(tmp_path, stubs, template):
    shell_, menu = _menu(tmp_path, template, "en")
    try:
        chinese = sorted(
            " › ".join(path + (action.text(),)) + (f"  [tip] {action.toolTip()}" if CJK.search(action.toolTip()) else "")
            for path, action in _walk(menu)
            if (CJK.search(action.text()) and action.text() != EGG_TITLE)
            or (CJK.search(action.toolTip()) and action.toolTip() != EGG_TITLE)
        )
        assert chinese == [], chinese
        top = _labels(menu)
        assert top[-2:] == ["Fish Settings", "Quit"], "设置在「退出」前（按文字找锚点英文下也对得上）"
        assert "Claude Code (WSL)" in top and "Agent link" in top
        if template == "modern":
            assert {"Fish controls", "Tools and help"} <= set(top), "模板自带子菜单名翻译"
        else:
            assert "Switch to the new menu" in top
    finally:
        shell_._delete_runtime_marker()


def test_the_chinese_right_click_menu_is_unchanged(tmp_path, stubs):
    shell_, menu = _menu(tmp_path, "modern", "zh")
    try:
        top = _labels(menu)
        for label in ("护驾", "AI 对话", "肥鱼控制", "工具与帮助", "Agent 联动", "肥鱼设置", "退出", "Claude Code（WSL）"):
            assert label in top, label
        assert top[-2:] == ["肥鱼设置", "退出"]
    finally:
        shell_._delete_runtime_marker()


def test_disabled_items_explain_themselves_in_english(tmp_path, stubs):
    shell_, menu = _menu(tmp_path, "modern", "en")
    try:
        rally = next(action for _path, action in _walk(menu) if action.text() == "Rally")
        assert not rally.isEnabled() and rally.toolTip() == "No little fish yet"
    finally:
        shell_._delete_runtime_marker()


def test_the_session_fish_menu_speaks_english(shell):  # noqa: F811
    shell._config.set("ui_language", "en")
    fish = _session(shell)
    menu = shell._build_menu_for(fish)
    assert _labels(menu)[1:] == ["Jump to this chat", "Show details", "Open project folder", "Copy resume command",
                                 "Copy session ID", "Send this one off", "Session fish settings"]
    settings = menu.actions()[-1].menu()
    assert _labels(settings)[:3] == ["One fish per session", "Session fish limit", "Detail card colors"]
    colors = settings.actions()[2].menu()
    assert "Sakura pink" in _labels(colors)


def test_the_tray_menu_speaks_english(tmp_path):
    from tests.test_overlay_tray_routing import _labels as tray_labels
    from tests.test_overlay_tray_routing import _tray_menu
    from tests.test_overlay_spawn import _make_persistent_shell

    shell_, _ = _make_persistent_shell(tmp_path, {"ui_language": "en"})
    try:
        shell_._refresh_tray_menu()
        labels = tray_labels(_tray_menu(shell_))
        for expected in ("Show / hide", "Back to the corner", "Spawn a little fish", "Close little fish",
                         "Fish Settings", "Click-through", "Start at sign-in", "Quit"):
            assert expected in labels, labels
        assert not [label for label in labels if CJK.search(label)]
        assert dict(shell_._pet_entries())[shell_.sprite] == "Main fish"
    finally:
        shell_._teardown_settings_command_watch()
        shell_._delete_runtime_marker()
        if getattr(shell_, "tray", None) is not None:
            shell_.tray.hide()


# ---------------------------------------------------------------- 导入时求值的表
def test_registry_tables_follow_the_language():
    i18n.set_language("en")
    assert MENU_ACTIONS.label("rally_pets") == "Rally" and MENU_ACTIONS.label("not_an_action") == "not_an_action"
    assert MENU_ACTIONS.disabled_reason("rally_pets") == "No little fish yet"
    assert MENU_ACTIONS.disabled_reason("modern_settings") == "This feature isn't turned on"
    assert MENU_ACTIONS.disabled_reason("nope") == "Unavailable right now"
    assert icon_choice_label("todo") == "To-do"
    assert MENU_ACTIONS.default_label({"type": "submenu", "id": "pet_controls", "label": "肥鱼控制"}) == "Fish controls"
    assert MENU_ACTIONS.default_label({"type": "submenu", "id": "pet_controls", "label": "我的控制"}) == "我的控制", \
        "用户改过名的子菜单原样"
    assert MENU_ACTIONS.default_label({"type": "submenu", "id": "custom_1", "label": "常用"}) == "常用"
    i18n.set_language("zh")
    assert MENU_ACTIONS.label("rally_pets") == "护驾"
    assert MENU_ACTIONS.disabled_reason("rally_pets") == "还没有小肥鱼"
    assert MENU_ACTIONS.default_label({"type": "submenu", "id": "pet_controls", "label": "肥鱼控制"}) == "肥鱼控制"


def test_session_status_line_speaks_english():
    from pet import session_pet_ui as spu

    i18n.set_language("en")
    assert spu.elapsed_text(30) == "just now" and spu.elapsed_text(3 * 60) == "3 min"
    assert spu.elapsed_text(65 * 60) == "1 h 5 min" and spu.elapsed_text(120 * 60) == "2 h"


def test_every_menu_key_keeps_its_placeholders_in_english():
    field = re.compile(r"(?<!\{)\{([A-Za-z_][A-Za-z0-9_]*)[^{}]*\}(?!\})")
    zh, en = i18n.table("zh"), i18n.table("en")
    keys = [key for key in zh if key.startswith("menu.")]
    assert len(keys) > 180
    assert [key for key in keys if key not in en] == []
    assert [key for key in keys if set(field.findall(zh[key])) != set(field.findall(en[key]))] == []
