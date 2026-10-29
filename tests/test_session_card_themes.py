# -*- coding: utf-8 -*-
"""会话小鱼详情卡的配色方案：几个命名好的方案里选，每一个都读得清。

回归：详情卡原先借用气泡样式的颜色，按钮底色用的是气泡的**边框色**。「吐气水泡」的
边框是深青色，按钮字又是深青灰——用户看到的是「背景色和底色分不清」。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QMenu

from pet import session_card_themes as themes
from pet.claude_session_info import SessionDetail
from pet.config import Config
from pet.session_pet_ui import SessionDetailCard
from pet.speech_bubble import BUBBLE_STYLE_PRESETS
from tests.test_session_pet_details import _session, shell  # noqa: F401 - shell 是 fixture

app = QApplication.instance() or QApplication([])

THEME_IDS = list(themes.CARD_THEMES)


# ---------------------------------------------------------------- 方案本身

def test_the_old_borrowed_colours_were_unreadable_with_the_breath_bubble_style():
    """现场：按钮底 = 气泡边框色，按钮字 = 气泡正文色。"""
    bubble = BUBBLE_STYLE_PRESETS["breath_bubble"]
    assert themes.contrast_ratio(bubble["foreground"], bubble["border"]) < 1.5


def test_there_are_a_handful_of_named_themes_and_one_is_the_default():
    assert 3 <= len(THEME_IDS) <= 5
    labels = [label for _id, label in themes.theme_choices()]
    assert all(labels) and len(set(labels)) == len(labels), "每个方案都要有名字，且不重名"
    assert themes.DEFAULT_CARD_THEME in themes.CARD_THEMES


@pytest.mark.parametrize("theme_id", THEME_IDS)
def test_every_theme_is_readable(theme_id):
    t, contrast = themes.CARD_THEMES[theme_id], themes.contrast_ratio
    assert contrast(t["text"], t["background"]) >= 7, "正文"
    assert contrast(t["muted"], t["background"]) >= 4.5, "次要文字"
    assert contrast(t["button_text"], t["button"]) >= 7, "按钮上的字"
    assert contrast(t["hover_text"], t["hover"]) >= 7, "鼠标悬停时按钮上的字"
    assert contrast(t["button_border"], t["background"]) >= 2, "按钮的描边：让按钮从卡片底上分出来"
    assert contrast(t["button"], t["background"]) >= 1.15, "按钮底不能和卡片底是同一个颜色"
    assert contrast(t["border"], t["background"]) >= 2, "卡片的边"
    assert contrast(t["disabled_text"], t["button"]) < contrast(t["button_text"], t["button"]), \
        "禁用的按钮要看得出是禁用的"
    assert contrast(t["accent_text"], t["accent"]) >= 7, "页头、主按钮、状态磁贴上的字"
    assert contrast(t["accent"], t["background"]) >= 1.5, "页头那条强调色要从卡片底上分出来"


def test_unknown_ids_fall_back_to_the_default():
    for value in (None, "", "neon", 3):
        assert themes.normalize_theme_id(value) == themes.DEFAULT_CARD_THEME
    assert themes.normalize_theme_id(" night ") == "night"


# ---------------------------------------------------------------- 配置

def test_the_choice_persists_and_bad_values_are_cleaned_on_load(tmp_path):
    config = Config(tmp_path)
    assert config.get("agent_link")["session_card_theme"] == themes.DEFAULT_CARD_THEME

    config.set("agent_link", {**config.get("agent_link"), "session_card_theme": "night"})
    config.save()
    assert Config(tmp_path).get("agent_link")["session_card_theme"] == "night"

    config.set("agent_link", {**config.get("agent_link"), "session_card_theme": "neon"})
    config.save()
    assert Config(tmp_path).get("agent_link")["session_card_theme"] == themes.DEFAULT_CARD_THEME


# ---------------------------------------------------------------- 详情卡

def _card(tmp_path, theme_id=None, bubble_style="breath_bubble") -> SessionDetailCard:
    config = Config(tmp_path)
    config.set("self_talk_bubble_style", bubble_style)
    if theme_id is not None:
        config.set("agent_link", {**config.get("agent_link"), "session_card_theme": theme_id})
    card = SessionDetailCard(config)
    card.show_detail(SessionDetail(title="修登录", last_prompt="为什么登录会跳两次？", cwd=r"C:\code\proj"), None)
    card.adjustSize()
    return card


def _painted(card: SessionDetailCard) -> tuple[QColor, QColor]:
    """卡片实际画出来的（卡片底色, 普通按钮底色）。"""
    image = card.grab().toImage()
    button = card.folder_btn
    corner = button.mapTo(card, button.rect().topRight())
    background = image.pixelColor(card._px(10), card.height() // 2)
    return background, image.pixelColor(corner.x() - card._px(4), corner.y() + card._px(4))


@pytest.mark.parametrize("theme_id", THEME_IDS)
def test_the_card_is_painted_in_the_chosen_theme(tmp_path, theme_id):
    card = _card(tmp_path, theme_id)
    try:
        theme = themes.CARD_THEMES[theme_id]
        background, button = _painted(card)
        assert background.name() == theme["background"]
        assert button.name() == theme["button"]
        assert themes.contrast_ratio(theme["button_text"], button.name()) >= 7
    finally:
        card.close()
        card.deleteLater()


@pytest.mark.parametrize("bubble_style", list(BUBBLE_STYLE_PRESETS))
def test_the_bubble_style_no_longer_decides_the_card_colours(tmp_path, bubble_style):
    card = _card(tmp_path, bubble_style=bubble_style)
    try:
        default = themes.CARD_THEMES[themes.DEFAULT_CARD_THEME]
        background, button = _painted(card)
        assert (background.name(), button.name()) == (default["background"], default["button"])
    finally:
        card.close()
        card.deleteLater()


# ---------------------------------------------------------------- 在哪里选

def _find(menu: QMenu, text: str):
    for action in menu.actions():
        if action.text() == text:
            return action
        if action.menu() is not None:
            found = _find(action.menu(), text)
            if found is not None:
                return found
    return None


def _theme_of(shell) -> str:  # noqa: F811
    return shell._config.get("agent_link")["session_card_theme"]


@pytest.mark.parametrize("which", ["session fish", "main fish"])
def test_both_menus_offer_the_themes_by_name(shell, which):  # noqa: F811
    fish = _session(shell)
    menu = shell._build_menu_for(fish if which == "session fish" else shell.sprite)

    entry = _find(menu, "详情卡配色")
    assert entry is not None and entry.menu() is not None
    choices = entry.menu().actions()
    assert [a.text() for a in choices] == [label for _id, label in themes.theme_choices()]
    assert [a.text() for a in choices if a.isChecked()] == [themes.CARD_THEMES[_theme_of(shell)]["label"]]

    night = next(a for a in choices if a.text() == themes.CARD_THEMES["night"]["label"])
    night.trigger()
    assert _theme_of(shell) == "night"


def test_a_new_choice_shows_on_the_card_the_next_time_it_opens(shell):  # noqa: F811
    fish = _session(shell)
    shell.session_actions.loader = lambda detail: detail
    shell._on_sprite_click(fish, "")
    card = shell.session_actions._card
    assert _painted(card)[0].name() == themes.CARD_THEMES[themes.DEFAULT_CARD_THEME]["background"]

    _find(shell._build_menu_for(fish), themes.CARD_THEMES["sakura"]["label"]).trigger()
    shell._on_sprite_click(fish, "")

    card = shell.session_actions._card
    assert card.isVisible()
    assert _painted(card)[0].name() == themes.CARD_THEMES["sakura"]["background"]
