# -*- coding: utf-8 -*-
"""语音报时的内置台词库在设置页里看得见、改得了（中 / 英各一份），自定义台词改成**追加**而不是替换
（用户 2026-10-21）。

- ``voice_chime_builtin_quotes_zh / _en``：留空 = 代码里的内置库原样；填了 = 用户改过的库（一行一条）。
- 生效的库 = 内置（或改过的）+ 自定义追加，去重保序；轮换规则不变。
- 设置页：两个编辑框预填内置库全文，「恢复内置」一键还原；保存时和内置原文一样就存空串（以后代码里加新句子还能跟上）。
"""
from __future__ import annotations

import os
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet import voice_chime as vc
from pet.config import Config
from pet.voice_chime_quotes import CHINESE_QUOTES, ENGLISH_QUOTES

app = QApplication.instance() or QApplication([])
ZH_VOICE, EN_VOICE = "zh-CN-XiaoxiaoNeural", "en-US-GuyNeural"


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


# ---------------------------------------------------------------- 纯逻辑

def test_defaults_and_normalize_carry_the_two_new_keys():
    cfg = vc.default_chime_config()
    assert cfg["voice_chime_builtin_quotes_zh"] == "" and cfg["voice_chime_builtin_quotes_en"] == ""
    norm = vc.normalize_chime_config({"voice_chime_builtin_quotes_zh": "甲\n\n乙\n甲", "voice_chime_builtin_quotes_en": None})
    assert norm["builtin_quotes_zh"] == ("甲", "乙") and norm["builtin_quotes_en"] == ()
    assert vc.builtin_quotes_text("zh") == "\n".join(CHINESE_QUOTES) and vc.builtin_quotes_text("en") == "\n".join(ENGLISH_QUOTES)


def test_the_pool_is_builtin_plus_custom_appended_not_replaced():
    cfg = {"voice": ZH_VOICE, "custom_quotes_zh": ("我的一句", CHINESE_QUOTES[0], "我的另一句")}
    pool = vc.quote_pool(cfg)
    assert pool[: len(CHINESE_QUOTES)] == CHINESE_QUOTES, "内置库一条不少、顺序不变"
    assert pool[len(CHINESE_QUOTES):] == ("我的一句", "我的另一句"), "自定义追加在后面，和内置重复的不再加"
    assert vc.quote_pool({"voice": ZH_VOICE}) == CHINESE_QUOTES
    assert vc.quote_pool({"voice": EN_VOICE, "custom_quotes_en": ("Mine",)}) == ENGLISH_QUOTES + ("Mine",)
    assert vc.quote_pool({"voice": EN_VOICE, "custom_quotes_zh": ("仅中文",)}) == ENGLISH_QUOTES


def test_an_edited_builtin_library_takes_the_place_of_the_code_list():
    cfg = {"voice": ZH_VOICE, "builtin_quotes_zh": ("只留这句", "和这句"), "custom_quotes_zh": ("追加",)}
    assert vc.quote_pool(cfg) == ("只留这句", "和这句", "追加")
    assert vc.quote_pool({"voice": ZH_VOICE, "builtin_quotes_zh": ()}) == CHINESE_QUOTES, "空 = 用代码里的"
    day = [vc.pick_quote(datetime(2026, 9, 15, h, 0), cfg) for h in range(3)]
    assert set(day) == {"只留这句", "和这句", "追加"}, "改过的库照样走每天洗牌、日内顺序"
    en = {"voice": EN_VOICE, "builtin_quotes_en": ("Only this",)}
    assert vc.pick_quote(datetime(2026, 9, 15, 9, 0), en) == "Only this"


# ---------------------------------------------------------------- 设置页

def _page(tmp_path, **values):
    from pet.voice_chime_settings import VoiceChimeSettingsPage

    config = Config(base=tmp_path / "cfg")
    for key, value in values.items():
        config.set(key, value)
    return VoiceChimeSettingsPage(config), config


def test_the_page_shows_the_builtin_libraries_and_saves_blank_when_untouched(tmp_path):
    page, config = _page(tmp_path)
    assert page.builtin_zh_edit.toPlainText() == "\n".join(CHINESE_QUOTES)
    assert page.builtin_en_edit.toPlainText() == "\n".join(ENGLISH_QUOTES)
    assert page.restore_zh_btn.text() == "恢复内置" and not page.restore_zh_btn.isEnabled(), "没改过就没必要恢复"
    page.apply_to_config()
    assert config.get("voice_chime_builtin_quotes_zh") == "" and config.get("voice_chime_builtin_quotes_en") == ""
    page.builtin_zh_edit.setPlainText("只留这句\n和这句")
    assert page.restore_zh_btn.isEnabled()
    page.apply_to_config()
    assert config.get("voice_chime_builtin_quotes_zh") == "只留这句\n和这句" and config.get("voice_chime_builtin_quotes_en") == ""
    assert vc.normalize_chime_config(config)["builtin_quotes_zh"] == ("只留这句", "和这句")
    page.restore_zh_btn.click()
    assert page.builtin_zh_edit.toPlainText() == "\n".join(CHINESE_QUOTES) and not page.restore_zh_btn.isEnabled()
    page.apply_to_config()
    assert config.get("voice_chime_builtin_quotes_zh") == ""


def test_the_page_reloads_an_edited_library_and_the_custom_hint_says_append(tmp_path):
    page, _config = _page(tmp_path, voice_chime_builtin_quotes_en="Only this\nAnd this")
    assert page.builtin_en_edit.toPlainText() == "Only this\nAnd this" and page.restore_en_btn.isEnabled()
    assert page.builtin_zh_edit.toPlainText() == "\n".join(CHINESE_QUOTES)
    rows = {row.objectName(): row for row in page.findChildren(vc_settings_row_type())}
    hint = rows["settingRow_voice_chime_custom_quotes_zh"].hint_label.text()
    assert "追加" in hint and "替换" not in hint
    assert "内置" in rows["settingRow_voice_chime_builtin_quotes_zh"].hint_label.text()


def test_the_page_speaks_english(tmp_path):
    page, _config = _page(tmp_path, ui_language="en")
    assert i18n.current_language() == "en"
    assert page.restore_zh_btn.text() == "Restore built-in"
    rows = {row.objectName(): row for row in page.findChildren(vc_settings_row_type())}
    assert "append" in rows["settingRow_voice_chime_custom_quotes_en"].hint_label.text().lower()
    assert "built-in" in rows["settingRow_voice_chime_builtin_quotes_en"].hint_label.text().lower()
    zh, en = i18n.table("zh"), i18n.table("en")
    for key in ("settings.voice.builtin_lines_lyrics_chinese", "settings.voice.builtin_lines_lyrics_english",
                "settings.voice.restore_builtin", "settings.voice.builtin_lines_hint_zh", "settings.voice.builtin_lines_hint_en"):
        assert key in zh and key in en, key


def vc_settings_row_type():
    from pet.settings_widgets import SettingRow

    return SettingRow
