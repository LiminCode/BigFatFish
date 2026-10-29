# -*- coding: utf-8 -*-
"""肥鱼身上的文字统一用等线：气泡、对话气泡、头顶的常驻标签。

会话详情卡 2026-10-28 起是 Metro 风格，改用微软雅黑 UI（标题用它的细体，路径 / 分支用等宽字），
同样只点一个族。

纪律：offscreen；字体装没装只看文件（不调 QFontDatabase，见 pet/ui_fonts.py 的说明），
所以用例靠改环境变量造「装了 / 没装」，不依赖本机真的有什么字体。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

from pet import ui_fonts
from pet.config import Config

app = QApplication.instance() or QApplication([])


@pytest.fixture
def family(monkeypatch):
    """把气泡字体钉成等线（不管这台机器是什么平台、装没装）。"""
    ui_fonts.bubble_font_family.cache_clear()
    monkeypatch.setattr(ui_fonts, "_preferred_installed", lambda: True)
    yield ui_fonts.PREFERRED_FAMILY
    ui_fonts.bubble_font_family.cache_clear()


def _choose(monkeypatch, tmp_path, platform: str, *, installed: bool) -> str:
    monkeypatch.setattr(ui_fonts.sys, "platform", platform)
    fonts = tmp_path / "Windows" / "Fonts"
    fonts.mkdir(parents=True, exist_ok=True)
    if installed:
        (fonts / "Deng.ttf").write_bytes(b"")
    monkeypatch.setenv("WINDIR", str(tmp_path / "Windows"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    ui_fonts.bubble_font_family.cache_clear()
    try:
        return ui_fonts.bubble_font_family()
    finally:
        ui_fonts.bubble_font_family.cache_clear()


def test_dengxian_is_used_when_installed_and_each_platform_has_a_fallback(monkeypatch, tmp_path):
    assert _choose(monkeypatch, tmp_path, "win32", installed=True) == "DengXian"
    assert _choose(monkeypatch, tmp_path / "bare", "win32", installed=False) == "Microsoft YaHei UI"
    assert _choose(monkeypatch, tmp_path / "mac", "darwin", installed=True) == "PingFang SC"
    assert _choose(monkeypatch, tmp_path / "linux", "linux", installed=False) == ""


def test_a_font_installed_only_for_the_current_user_counts(monkeypatch, tmp_path):
    monkeypatch.setattr(ui_fonts.sys, "platform", "win32")
    monkeypatch.setenv("WINDIR", str(tmp_path / "Windows"))
    personal = tmp_path / "Local" / "Microsoft" / "Windows" / "Fonts"
    personal.mkdir(parents=True)
    (personal / "Dengb.ttf").write_bytes(b"")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    ui_fonts.bubble_font_family.cache_clear()
    try:
        assert ui_fonts.bubble_font_family() == "DengXian"
    finally:
        ui_fonts.bubble_font_family.cache_clear()


def test_css_names_exactly_one_family(family):
    assert ui_fonts.font_css() == 'font-family: "DengXian"; '
    assert "," not in ui_fonts.font_css(), "多族列表会让 Qt 枚举整个字体库"


def test_speech_bubble_text_and_its_buttons_use_the_bubble_font(family):
    from pet.speech_bubble import PetSpeechBubble

    bubble = PetSpeechBubble()
    try:
        bubble.show_text("今天想聊点什么？", QRect(400, 400, 200, 200), 1000)
        assert bubble.font().family() == family
        assert bubble.label.font().family() == family
        assert f'font-family: "{family}"' in bubble.label.styleSheet()
        assert bubble.label.font().pixelSize() > 0, "字号照旧由样式表给"
    finally:
        bubble.close()
        bubble.deleteLater()


def test_chat_bubble_uses_the_bubble_font(family, tmp_path):
    from pet.quick_chat import QuickChatBubble

    config = Config(tmp_path)
    chat = QuickChatBubble(config)
    try:
        for widget in (chat, chat.input, chat.output, chat.send_btn):
            assert widget.font().family() == family
        assert chat.input.font().pointSizeF() == pytest.approx(app.font().pointSizeF() * 1.25), \
            "只换字体族，放大倍数不变"
    finally:
        chat.close()
        chat.deleteLater()


@pytest.fixture
def metro_fonts(monkeypatch):
    """把 Metro 字体钉成 Windows 上的那几个（不管这台机器是什么平台、装没装）。"""
    for cached in (ui_fonts.metro_font_family, ui_fonts.mono_font_family):
        cached.cache_clear()
    monkeypatch.setattr(ui_fonts.sys, "platform", "win32")
    monkeypatch.setattr(ui_fonts, "_font_file_installed", lambda pattern: True)
    yield
    for cached in (ui_fonts.metro_font_family, ui_fonts.mono_font_family):
        cached.cache_clear()


def test_session_card_uses_single_metro_families(metro_fonts, tmp_path):
    from pet.session_pet_ui import SessionDetailCard

    card = SessionDetailCard(Config(tmp_path))
    try:
        card.ensurePolished()
        for widget in (card, card.prompt_label, card.jump_btn):
            widget.ensurePolished()
            assert widget.font().family() == "Microsoft YaHei UI"
        sheet = card.styleSheet()
        assert 'font-family: "Microsoft YaHei UI Light"' in sheet, "标题用细体"
        assert 'font-family: "Ubuntu Mono"' in sheet, "路径 / 分支用等宽字"
        assert all("," not in line.split("font-family:")[1].split(";")[0]
                   for line in sheet.splitlines() if "font-family:" in line), "只点一个族"
    finally:
        card.close()
        card.deleteLater()


def test_mono_falls_back_to_what_is_installed(monkeypatch):
    ui_fonts.mono_font_family.cache_clear()
    monkeypatch.setattr(ui_fonts.sys, "platform", "win32")
    monkeypatch.setattr(ui_fonts, "_font_file_installed", lambda pattern: pattern == "consola.ttf")
    try:
        assert ui_fonts.mono_font_family() == "Consolas"
    finally:
        ui_fonts.mono_font_family.cache_clear()


def test_fish_caption_uses_the_same_family_as_the_bubbles():
    from pet.pet_sprite import PetSprite

    assert PetSprite._CAPTION_FONT_FAMILY == ui_fonts.bubble_font_family()
