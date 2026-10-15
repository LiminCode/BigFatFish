# -*- coding: utf-8 -*-
"""Legacy context-menu layout.

Keep this module intentionally independent from ``modern.py``: preserving the
original interaction model is more important than sharing layout code.
"""
from __future__ import annotations

from PySide6.QtWidgets import QMenu

from .shared import (
    add_action,
    add_agent_link_menu,
    add_proactive_menu,
    add_autostart,
    add_clear_spawned_pets,
    add_drag_physics,
    add_edge_probe,
    add_golden_spin,
    add_vscode_workspaces_menu,
    add_claude_desktop,
    add_wsl_claude_code,
    add_youtube_music,
    add_no_move,
    add_on_top,
    add_quit,
    add_rally_pets,
    add_return_corner,
    add_spawn_pet,
    add_template_switch,
    build_animation_categories,
    build_character_menu,
    build_size_menu,
    build_speed_menu,
)


def build_legacy_menu(menu: QMenu, pet, template: dict) -> None:
    """Build only the classic flat menu and its original settings entry."""
    chat = getattr(pet, "on_open_chat", None)
    chat_settings = getattr(pet, "on_open_chat_settings", None)
    legacy_settings = getattr(pet, "on_open_legacy_settings", None)
    if chat is not None:
        add_action(menu, "AI 对话", None, chat, close_on_trigger=True)
    if chat_settings is not None:
        add_action(menu, "AI 设置", None, chat_settings, close_on_trigger=True)
    if legacy_settings is not None:
        add_action(menu, "肥鱼设置", None, legacy_settings, close_on_trigger=True)

    menu.addSeparator()
    build_animation_categories(menu, pet, icons=False, legacy_labels=True)
    build_speed_menu(menu, pet, icons=False)
    add_drag_physics(menu, pet, icons=False)
    build_character_menu(menu, pet, icons=False)

    menu.addSeparator()
    add_return_corner(menu, pet, icons=False)
    add_on_top(menu, pet, icons=False)
    add_no_move(menu, pet, icons=False)
    add_autostart(menu, icons=False)
    add_spawn_pet(menu, pet)
    add_rally_pets(menu, pet, icons=False)
    add_clear_spawned_pets(menu, pet, icons=False)
    add_golden_spin(menu, pet, icons=False)
    # legacy 布局约定无图标（测试 test_legacy_config_value_dispatches_legacy_layout 守着）
    # 「音乐」子菜单 2026-10-13 从右键菜单下线（歌词气泡 / 唱歌联动保留，入口在设置页），
    # 它的位置给了「VS Code 工作区」
    add_vscode_workspaces_menu(menu, pet, icons=False)
    add_youtube_music(menu, pet, icons=False)
    add_claude_desktop(menu, pet, icons=False)
    add_wsl_claude_code(menu, pet, icons=False)
    add_edge_probe(menu, pet, icons=False)
    build_size_menu(menu, pet, icons=False)

    menu.addSeparator()
    # 「DeepSeek Harness」「打开网页版 DeepSeek」2026-10-14 下线（DeepSeek 的东西用不到了）
    add_proactive_menu(menu, pet)
    add_agent_link_menu(menu, pet)

    menu.addSeparator()
    add_template_switch(menu, pet, str(template["switch_label"]), str(template["switch_to"]), icons=False)

    menu.addSeparator()
    add_quit(menu, pet, icons=False)
