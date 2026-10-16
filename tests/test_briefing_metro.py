# -*- coding: utf-8 -*-
"""简报窗口的 Windows Phone / Metro 风格 + 白天 / 黑夜 + 中英文（2026-10-15，用户点名）。

守住的：样式表里没有非零圆角；颜色令牌按 ``METRO_TOKENS`` 落到样式表；pivot 页头大而轻；
主题跟随「外观」里的偏好，右上角能当场切换并写回那个偏好，挂上来的「笔记」页跟着换色；
按钮是会倾斜的磁贴；窗口与气泡文字跟随界面语言。
"""
from __future__ import annotations

import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet import work_briefing as wb
from pet import work_briefing_ui as ui
from pet.config import Config
from pet.settings_theme_qss import METRO_TOKENS
from pet.settings_widgets import TiltButton
from pet.slack_watch_service import SlackWatchService
from pet.slack_watch_ui import SlackWatchController
from pet.work_briefing_service import WorkBriefingService
from pet.work_notes_ui import WorkNotesPanel

app = QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


# ---------------------------------------------------------------- 令牌与样式表
@pytest.mark.parametrize("dark", [False, True])
def test_the_briefing_stylesheet_is_square_and_uses_the_metro_tokens(dark):
    qss = ui._QSS.format(**ui.briefing_tokens(dark))
    radii = re.findall(r"border-radius:\s*([0-9]+)", qss)
    assert radii and all(value == "0" for value in radii)
    tokens = METRO_TOKENS["dark" if dark else "light"]
    for key in ("page", "tile", "tile_hover", "title", "muted", "outline", "accent", "selected", "field"):
        assert tokens[key] in qss, key
    assert "font-size: 28px" in qss and "font-weight: 300" in qss, "pivot 页头：大而轻"
    assert "Segoe UI" in qss


def test_extra_tokens_differ_between_day_and_night():
    light, dark = ui.briefing_tokens(False), ui.briefing_tokens(True)
    assert light["link"] != dark["link"] and light["chip"] != dark["chip"]
    assert light["page"] == METRO_TOKENS["light"]["page"] and dark["page"] == METRO_TOKENS["dark"]["page"]


def test_resolve_dark_follows_the_preference(monkeypatch):
    assert ui.resolve_dark("dark") is True and ui.resolve_dark("light") is False
    monkeypatch.setattr(ui, "_system_dark", lambda: True)
    assert ui.resolve_dark("system") is True
    monkeypatch.setattr(ui, "_system_dark", lambda: False)
    assert ui.resolve_dark("system") is False and ui.resolve_dark("bogus") is False


# ---------------------------------------------------------------- 窗口
def test_the_window_is_built_from_tilting_tiles_and_a_pivot_header():
    window = ui.WorkBriefingWindow(theme="light")
    try:
        assert isinstance(window.regenerate_btn, TiltButton) and isinstance(window.close_btn, TiltButton)
        assert isinstance(window.theme_btn, TiltButton) and window.theme_btn.objectName() == "themeToggle"
        assert window.tabs.tabBar().isVisibleTo(window) and window.tabs.tabText(0) == "简报"
        assert window.title_label.text() == "工作简报" and window.windowTitle() == "工作简报"
        assert not window.is_dark and window.theme_btn.text() == "☾"
    finally:
        window.close()


def test_the_toggle_switches_day_and_night_and_restyles_the_mounted_page():
    window = ui.WorkBriefingWindow(theme="light")
    panel = WorkNotesPanel(ui.briefing_tokens(False))
    window.add_tab("笔记", panel)
    changes = []
    window.theme_changed.connect(changes.append)
    try:
        window.toggle_theme()
        assert window.is_dark and window.theme == "dark" and changes == ["dark"]
        assert METRO_TOKENS["dark"]["page"] in window.styleSheet()
        assert panel._colors["link"] == ui.briefing_tokens(True)["link"], "笔记页跟着换色"
        assert window.theme_btn.text() == "☀"
        window.toggle_theme()
        assert not window.is_dark and changes == ["dark", "light"]
        assert METRO_TOKENS["light"]["page"] in window.styleSheet()
    finally:
        window.close()


def test_links_and_chips_take_the_theme_colours():
    window = ui.WorkBriefingWindow(theme="dark")
    try:
        window.show_briefing(wb.Briefing(ok=True, summary="s", markdown="- [DEMO-1](https://x/browse/DEMO-1) `进行中`",
                                         generated_at="2026-10-15T09:00:00", seconds=42))
        html = window.body.toHtml()
        assert ui.briefing_tokens(True)["link"] in html and ui.briefing_tokens(True)["chip"] in html
        assert "生成于 10-15 09:00 · 用时 42 秒" in window.meta_label.text()
    finally:
        window.close()


# ---------------------------------------------------------------- 偏好
def test_the_controller_follows_and_saves_the_appearance_theme(tmp_path):
    config = Config(base=tmp_path)
    config.set("context_menu_appearance", {**config.get("context_menu_appearance"), "theme": "dark"})
    service = WorkBriefingService(config, generate=lambda when, model: wb.Briefing(), spawn=lambda run: run())
    controller = ui.WorkBriefingController(_Host(), service)
    controller.open_window()
    try:
        assert controller.window.is_dark, "开窗口时跟「外观」里的主题"
        controller.window.toggle_theme()
        assert config.get("context_menu_appearance")["theme"] == "light", "切换写回同一个偏好"
        assert Config(base=tmp_path).get("context_menu_appearance")["theme"] == "light", "落盘了"
    finally:
        controller.window.close()


class _Host:
    def __init__(self):
        self.bubbles, self.alerts = [], []

    def show_bubble(self, text, ms=0, **_):
        self.bubbles.append(text)

    def show_alert(self, text, **kw):
        self.alerts.append((text, kw))

    def resolve_alert(self, alert_id):
        pass


# ---------------------------------------------------------------- 中英文
def test_the_briefing_window_and_bubbles_speak_english(tmp_path):
    config = Config(base=tmp_path)
    config.set("ui_language", "en")
    host = _Host()
    service = WorkBriefingService(config, generate=lambda when, model: wb.Briefing(error="boom"),
                                  spawn=lambda run: run())
    controller = ui.WorkBriefingController(host, service)
    controller.open_window()
    try:
        window = controller.window
        assert window.title_label.text() == "DAILY BRIEFING" and window.tabs.tabText(0) == "Briefing"
        assert window.regenerate_btn.text() == "Regenerate" and window.close_btn.text() == "Close"
        assert window.body.toPlainText().startswith("No briefing yet")
        controller.generate_now()
        # spawn 是同步的：失败那句先于「出发」那句冒出来，只看两句都在
        assert any(b.startswith("Off to see") for b in host.bubbles)
        assert any(b.startswith("Couldn't generate the briefing: boom") for b in host.bubbles)
        assert "Last attempt failed: boom" in window.status_label.text()
    finally:
        controller.window.close()


def test_the_slack_window_speaks_english_too(tmp_path):
    config = Config(base=tmp_path)
    config.set("ui_language", "en")
    service = SlackWatchService(config, generate=lambda *a: None, spawn=lambda run: run(), active=lambda s: True)
    controller = SlackWatchController(_Host(), service)
    controller.open_window()
    try:
        window = controller.window
        assert window.windowTitle() == "Slack Watch" and window.tabs.tabText(0) == "Slack"
        assert window.regenerate_btn.text() == "Check now" and window.body.toPlainText().startswith("Not checked yet")
    finally:
        controller.window.close()


def test_every_briefing_and_slack_key_has_both_languages():
    zh, en = i18n.table("zh"), i18n.table("en")
    keys = [k for k in zh if k.startswith(("briefing.", "slack."))]
    assert len(keys) >= 25 and all(k in en for k in keys)
