# -*- coding: utf-8 -*-
"""内置表达风格不再是黑箱（用户 2026-10-18）：

- 选「默认模式 / 鲸鱼娘女仆模式」时，逐事件编辑框只读地显示那套台词，折叠框改名；
- 「改成我的台词」把整套复制进自定义台词并切到自定义模式，之后可编辑；已有自定义内容时先确认；
- 预览期间保存不会把内置台词写进 dialogue_phrases，用户的自定义台词原样保留；
- 导出模板带当前显示的台词。
纯界面：不碰真实数据目录。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet.config import Config
from pet.persona_phrases import builtin_phrases, phrase_keys

app = QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


def _dialog(tmp_path, monkeypatch, *, mode="legacy", phrases=None, language="zh"):
    from pet import modern_settings_dialog as settings_mod

    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    config = Config(tmp_path)
    config.set("ui_language", language)
    config.set("dialogue_mode", mode)
    if phrases is not None:
        config.set("dialogue_phrases", phrases)
    config.save()
    return config, settings_mod.ModernSettingsDialog(config, include_ai=False)


def _close(dialog):
    dialog.close()
    dialog.deleteLater()
    app.processEvents()


def test_a_builtin_style_shows_its_lines_read_only(tmp_path, monkeypatch):
    config, dialog = _dialog(tmp_path, monkeypatch, mode="whale_maid")
    try:
        edit = dialog.dialogue_phrase_edits["done.success"]
        assert edit.isReadOnly() and edit.toPlainText() == "\n".join(builtin_phrases("whale_maid")["done.success"])
        assert all(e.isReadOnly() for e in dialog.dialogue_phrase_edits.values())
        assert not dialog.dialogue_scope_select.isEnabled(), "预览只有 global 一层"
        assert dialog.dialogue_phrases_box.toggle.text() == "「鲸鱼娘女仆模式」的台词（只读；要改先点「改成我的台词」）"
        assert dialog.dialogue_adopt_btn.text() == "以「鲸鱼娘女仆模式」为底改成我的台词" and not dialog.dialogue_adopt_btn.isHidden()
        dialog.dialogue_mode_select.setCurrentData("legacy")
        assert edit.toPlainText() == "\n".join(builtin_phrases("legacy")["done.success"])
        assert dialog.dialogue_phrases_box.toggle.text().startswith("「默认模式」的台词")
    finally:
        _close(dialog)


def test_previewing_never_overwrites_the_custom_lines_even_on_save(tmp_path, monkeypatch):
    config, dialog = _dialog(tmp_path, monkeypatch, mode="custom", phrases={"done.success": ["我的完成台词"]})
    try:
        edit = dialog.dialogue_phrase_edits["done.success"]
        assert not edit.isReadOnly() and edit.toPlainText() == "我的完成台词"
        assert dialog.dialogue_adopt_btn.isHidden() and dialog.dialogue_phrases_box.toggle.text() == "自定义台词（逐事件文案）"
        edit.setPlainText("改过的完成台词")
        dialog.dialogue_mode_select.setCurrentData("whale_maid")
        assert edit.isReadOnly() and "主人" in edit.toPlainText()
        dialog._save()
        saved = config.get("dialogue_phrases")
        saved_global = saved.get("global", saved) if isinstance(saved, dict) else {}
        assert saved_global.get("done.success") == ["改过的完成台词"], "预览期间保存：存的是用户的自定义台词"
        assert config.get("dialogue_mode") == "whale_maid"
        dialog.dialogue_mode_select.setCurrentData("custom")
        assert not edit.isReadOnly() and edit.toPlainText() == "改过的完成台词", "切回自定义：恢复用户的台词"
    finally:
        _close(dialog)


def test_adopting_copies_the_whole_set_and_switches_to_custom(tmp_path, monkeypatch):
    config, dialog = _dialog(tmp_path, monkeypatch, mode="whale_maid")
    try:
        assert dialog._adopt_builtin_phrases(confirm=lambda *_: pytest.fail("自定义台词是空的，不该问")) is True
        assert dialog.dialogue_mode_select.currentData() == "custom"
        edit = dialog.dialogue_phrase_edits["done.success"]
        assert not edit.isReadOnly() and edit.toPlainText() == "\n".join(builtin_phrases("whale_maid")["done.success"])
        assert dialog.dialogue_phrases_box.is_expanded() and dialog.dialogue_scope_select.isEnabled()
        edit.setPlainText("主人～改成我自己的话")
        dialog._save()
        saved = config.get("dialogue_phrases")
        saved_global = saved.get("global", saved) if isinstance(saved, dict) else {}
        assert saved_global["done.success"] == ["主人～改成我自己的话"]
        assert set(saved_global) >= {key for key in phrase_keys() if builtin_phrases("whale_maid").get(key)}, "整套都复制进去了"
        assert config.get("dialogue_mode") == "custom"
    finally:
        _close(dialog)


def test_adopting_over_existing_custom_lines_asks_first(tmp_path, monkeypatch):
    config, dialog = _dialog(tmp_path, monkeypatch, mode="legacy", phrases={"start": ["我自己的开场"]})
    try:
        asked = []

        def decline(host, mode_name):
            asked.append(mode_name)
            return False

        assert dialog._adopt_builtin_phrases(confirm=decline) is False
        assert asked == ["默认模式"] and dialog.dialogue_mode_select.currentData() == "legacy"
        assert dialog._adopt_builtin_phrases(confirm=lambda *_: True) is True
        assert dialog.dialogue_phrase_edits["start"].toPlainText() == "\n".join(builtin_phrases("legacy")["start"])
    finally:
        _close(dialog)


def test_the_preview_speaks_english(tmp_path, monkeypatch):
    config, dialog = _dialog(tmp_path, monkeypatch, mode="whale_maid", language="en")
    try:
        assert dialog.dialogue_adopt_btn.text().startswith("Start my lines from")
        assert dialog.dialogue_phrases_box.toggle.text().startswith("Lines of “") and "read-only" in dialog.dialogue_phrases_box.toggle.text()
    finally:
        _close(dialog)
