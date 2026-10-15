# -*- coding: utf-8 -*-
"""在线更新功能已从本分支移除（2026-10-11）。

这是从源码运行的 fork：「检查更新」查的是上游的发布版，「下载并安装」装的是上游的
安装包——装上只会多出一个不含本分支改动的独立程序。同步上游改动走 git。

移除范围：设置页「更新」页、右键菜单「检查更新」「夸克网盘下载」、托盘「检查更新」，
以及只为它们服务的 ``pet/updater.py`` / ``pet/update_settings.py``。本文件守住它们
不被合并悄悄带回来；保留下来的（版本号显示、设置页深链、GitHub 项目页）也在这里钉一下。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QMenu

PET_DIR = Path(__file__).resolve().parent.parent / "pet"
REMOVED_MODULES = ("updater", "update_settings")
REMOVED_ACTIONS = ("check_update", "quark_download")

app = QApplication.instance() or QApplication([])


def test_updater_modules_are_gone():
    present = [name for name in REMOVED_MODULES if (PET_DIR / f"{name}.py").exists()]
    assert present == [], f"更新模块被带回来了：{present}"


def test_nothing_in_the_app_refers_to_updating_any_more():
    """入口、接线、文案一起清掉：留下半截接线就是点了没反应的死按钮。"""
    pattern = re.compile(r"\bupdater\b|update_settings|UpdatePage|check_update|quark_download|"
                         r"QUARK_PAN_URL|检查更新|夸克网盘")
    offenders = []
    for path in sorted(PET_DIR.rglob("*")):
        if path.suffix not in {".py", ".json", ".qss"} or "__pycache__" in path.parts:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            # 唯一的例外：config.py 里「旧布局残留节点剔除表」必须点名这两个 id
            dropped_table = path.name == "config.py" and (
                "_MENU_LAYOUT_DROPPED_ACTIONS" in line or "同样在此剔除" in line)
            if pattern.search(line) and not dropped_table:
                offenders.append(f"{path.relative_to(PET_DIR)}:{lineno}: {line.strip()[:80]}")
    assert offenders == []


def test_menu_registry_no_longer_offers_update_or_download():
    from pet.context_menus.registry import ACTION_ICONS, ACTION_LABELS, MENU_ACTIONS

    for action_id in REMOVED_ACTIONS:
        assert action_id not in MENU_ACTIONS.ids
        assert action_id not in ACTION_LABELS
        assert action_id not in ACTION_ICONS
    assert "github_project" in MENU_ACTIONS.ids, "GitHub 项目页还在"


def test_default_menu_layout_has_no_update_entries():
    from pet.menu_layout import load_default_menu_layout

    def ids(nodes):
        for node in nodes:
            yield node.get("id")
            yield from ids(node.get("children", []))

    found = set(ids(load_default_menu_layout("modern-default-v1")["nodes"]))
    assert found.isdisjoint(REMOVED_ACTIONS)
    assert "github_project" in found, "「工具与帮助」里的项目页原样"
    assert found.isdisjoint({"balance", "harness", "deepseek_web"}), "DeepSeek 三项 2026-10-14 下线"


def test_saved_layout_drops_the_removed_update_entries(tmp_path):
    """菜单编辑器没有「删除菜单项」：旧布局里的残留节点要在载入时清掉，否则会一直
    被回存成「此平台不可用」的幽灵项。"""
    from pet.config import Config

    config = Config(tmp_path)
    config.set("context_menu_layout", {
        "schema_version": 1,
        "layout_id": "user",
        "nodes": [
            {"type": "action", "id": "check_update", "visible": True},
            {"type": "action", "id": "modern_settings", "visible": True},
            {
                "type": "submenu", "id": "tools_help", "label": "工具与帮助", "visible": True,
                "children": [
                    {"type": "action", "id": "check_update", "visible": True},
                    {"type": "action", "id": "github_project", "visible": True},
                    {"type": "action", "id": "quark_download", "visible": True},
                ],
            },
            {"type": "action", "id": "quit", "visible": True},
        ],
    })
    config.save()

    nodes = Config(tmp_path).get("context_menu_layout")["nodes"]
    assert [node["id"] for node in nodes] == ["modern_settings", "tools_help", "quit"]
    assert [child["id"] for child in nodes[1]["children"]] == ["github_project"]


def test_github_project_link_still_opens_the_repo(monkeypatch):
    from pet.context_menus import registry as registry_mod
    from pet.context_menus import shared

    opened: list = []
    monkeypatch.setattr(registry_mod.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()) or True)
    menu = QMenu()
    action = registry_mod._build_github(menu, None)
    action.trigger()
    assert opened == [shared.REPO_URL] and shared.REPO_URL.startswith("https://github.com/")


@pytest.fixture
def settings_dialog(tmp_path, monkeypatch):
    import pet.modern_settings_dialog as settings_mod
    from pet.config import Config

    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    dialog = settings_mod.ModernSettingsDialog(Config(tmp_path), include_ai=False)
    yield dialog
    dialog.close()


def test_settings_has_no_update_page_but_still_shows_the_version(settings_dialog):
    labels = [settings_dialog.sidebar.item(i).text() for i in range(settings_dialog.sidebar.count())]
    assert "更新" not in labels
    assert settings_dialog.select_page("更新") is False, "旧深链不再指向任何页"
    assert settings_dialog.version_footer.objectName() == "settingsVersion"
    assert settings_dialog.version_footer.text().startswith("版本 v")


def test_settings_process_page_deep_link_is_passed(tmp_path, monkeypatch):
    """设置页深链（``--settings-page``）本身与更新无关：原样保留。"""
    from pet.app import AppShell
    from pet.config import Config

    shell = AppShell.__new__(AppShell)
    shell.config = Config(tmp_path)
    shell._settings_process_running = lambda: False
    shell._settings_launch_pending = lambda: False
    shell._install_config_watcher = lambda: None
    shell._mark_settings_child = lambda active: None
    calls = []
    monkeypatch.setattr(
        shell,
        "_launch_settings_process",
        lambda instance=None, *, page=None: calls.append((instance, page)) or True,
    )
    instance = object()
    assert shell.open_settings_process(instance, page="语音") is True
    assert calls == [(instance, "语音")]


def test_shell_has_no_update_check():
    from pet.app import AppShell
    from pet.sprite_menu_facade import SpriteMenuFacade

    assert not hasattr(AppShell, "check_update")
    assert not hasattr(SpriteMenuFacade, "on_check_update")
