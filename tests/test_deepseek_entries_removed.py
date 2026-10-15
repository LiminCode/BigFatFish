# -*- coding: utf-8 -*-
"""DeepSeek 的入口 2026-10-14 全部下线：右键菜单的「DeepSeek 余额 / DeepSeek Harness / 打开网页版 DeepSeek」、
托盘里的同名三项、「Agent 联动」里的 DSH 开关、设置页的「随桌宠启动 dsh 服务 / 自启目标 / 点击显示余额」、
灵动岛「卡片内容」里的余额项。

和「音乐」「显示本轮消费」同一口径：只摘入口，余额查询（pet/balance.py）、Harness 启动器（pet/harness_launcher.py）、
DSH 监视器与各配置键都保留；用户老布局里残留的三个 action 在加载时清掉。
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from pet import config as config_mod
from pet.config import Config
from pet.context_menu import _FALLBACK_TEMPLATES, load_menu_template
from pet.context_menus import registry
from pet.menu_layout import load_default_menu_layout
from pet.settings_widgets import SettingRow

app = QApplication.instance() or QApplication([])

GONE_IDS = ("balance", "harness", "deepseek_web")
GONE_LABELS = ("DeepSeek 余额", "DeepSeek Harness", "启动 DeepSeek Harness", "打开网页版 DeepSeek", "DeepSeek Harness (DSH)")


def _ids(nodes) -> set[str]:
    found = set()
    for node in nodes:
        if isinstance(node, dict):
            found.add(str(node.get("id") or ""))
            found.update(_ids(node.get("children") or []))
    return found


def test_the_registry_and_templates_no_longer_know_the_three_actions():
    for action_id in GONE_IDS:
        assert action_id not in registry.MENU_ACTIONS.ids
        assert action_id not in registry.ACTION_LABELS and action_id not in registry.ACTION_ICONS
    assert not set(GONE_LABELS) & set(registry.ACTION_LABELS.values())
    for template_id in ("modern", "legacy"):
        for source in (load_menu_template(template_id), _FALLBACK_TEMPLATES[template_id]):
            items = {item for group in source["groups"] for item in group["items"]}
            assert not set(GONE_IDS) & items, (template_id, items)
    assert set(GONE_IDS).isdisjoint(_ids(load_default_menu_layout("modern-default-v1")["nodes"]))
    assert set(GONE_IDS) <= config_mod._MENU_LAYOUT_DROPPED_ACTIONS


def test_an_old_saved_layout_loses_the_three_actions_on_load(tmp_path):
    config = Config(tmp_path)
    layout = json.loads(json.dumps(load_default_menu_layout("modern-default-v1")))
    tools = next(node for node in layout["nodes"] if node.get("id") == "tools_help")
    tools["children"] = [{"type": "action", "id": action_id, "visible": True} for action_id in GONE_IDS] + tools["children"]
    config.set("context_menu_layout", layout)
    config.save()
    reloaded = Config(tmp_path).get("context_menu_layout")
    assert set(GONE_IDS).isdisjoint(_ids(reloaded["nodes"]))
    assert "github_project" in _ids(reloaded["nodes"])


def test_the_settings_page_has_no_harness_or_click_balance_rows(tmp_path, monkeypatch):
    from pet import modern_settings_dialog as settings_mod

    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    config = Config(tmp_path)
    config.set("harness_autostart", True)
    config.set("harness_launch_target", "desktop")
    config.set("click_show_balance", True)
    dialog = settings_mod.ModernSettingsDialog(config, include_ai=True)
    try:
        ids = {row.objectName() for row in dialog.findChildren(SettingRow)}
        for gone in ("settingRow_harness_autostart", "settingRow_harness_launch_target", "settingRow_click_balance"):
            assert gone not in ids
        assert "settingRow_autostart" in ids, "开机自启还在"
        titles = {label.text() for label in dialog.findChildren(QLabel, "sectionTitle")}
        assert "待分类（开发期）" not in titles
        select = dialog.island_card_source_select
        assert [select.itemData(i) for i in range(select.count())] == ["auto", "claude"]
        dialog._save()
        assert config.get("harness_autostart") is True and config.get("harness_launch_target") == "desktop"
        assert config.get("click_show_balance") is True, "下线只摘入口：旧配置值不被保存覆盖"
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_shared_builders_for_the_entries_are_gone():
    import pet.context_menus.shared as shared

    for name in ("add_balance", "add_harness", "add_deepseek_web", "open_deepseek_web", "DEEPSEEK_WEB_URL"):
        assert not hasattr(shared, name), name
    assert hasattr(shared, "add_agent_link_menu")
