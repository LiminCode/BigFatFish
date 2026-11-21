# -*- coding: utf-8 -*-
"""窗口的白天 / 黑夜（``pet/window_theme.py``，2026-11-21 从简报窗口的模块搬出来）：``system`` 跟系统、别的按字面；
色板就是 ``METRO_TOKENS`` 那张表的一份拷贝；偏好只有一个来源 ``context_menu_appearance.theme``，写回就落盘；
用量看板、岛的连接面板从同一处取 ``resolve_dark``。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from pet import island_connections_ui, usage_dashboard_ui
from pet import window_theme as wt
from pet.config import Config
from pet.theme_tokens import METRO_TOKENS

app = QApplication.instance() or QApplication([])


def test_resolve_dark_follows_the_preference(monkeypatch):
    assert wt.resolve_dark("dark") is True and wt.resolve_dark("light") is False
    monkeypatch.setattr(wt, "_system_dark", lambda: True)
    assert wt.resolve_dark("system") is True
    monkeypatch.setattr(wt, "_system_dark", lambda: False)
    assert wt.resolve_dark("system") is False and wt.resolve_dark("bogus") is False
    assert usage_dashboard_ui.resolve_dark is wt.resolve_dark and island_connections_ui.resolve_dark is wt.resolve_dark, "一个口径"


def test_window_tokens_are_the_metro_table_one_copy_each():
    light, dark = wt.window_tokens(False), wt.window_tokens(True)
    assert light == METRO_TOKENS["light"] and dark == METRO_TOKENS["dark"] and light["page"] != dark["page"]
    light["page"] = "#000000"
    assert METRO_TOKENS["light"]["page"] != "#000000", "改拷贝不碰那张表"


def test_the_preference_has_one_source_and_saving_writes_it_back(tmp_path):
    config = Config(base=tmp_path)
    assert wt.theme_preference(config) == "system" and wt.THEMES == ("system", "light", "dark")
    config.set("context_menu_appearance", {**config.get("context_menu_appearance"), "theme": "dark"})
    assert wt.theme_preference(config) == "dark"
    wt.save_theme_preference(config, "light")
    assert config.get("context_menu_appearance")["theme"] == "light"
    assert Config(base=tmp_path).get("context_menu_appearance")["theme"] == "light", "落盘了"
    assert wt.theme_preference(object()) == "system", "拿不到配置就当 system"
