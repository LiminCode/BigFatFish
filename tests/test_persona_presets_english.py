# -*- coding: utf-8 -*-
"""内置表达风格的英文版（用户 2026-10-19：给两套预设各加一份英文 JSON，按界面语言切换）。

- ``<mode>.en.json`` 与中文版键集合一致、每条占位符不超出中文版用到的、条数与长度守同一契约；
- 界面语言 = en 时 ``builtin_phrases`` / ``PhrasePicker.get`` 用英文，zh 不变；缺键回退中文；
- 设置页的只读预览与「改成我的台词」也跟着界面语言。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from pet import i18n
from pet import persona_phrases as pp

PRESET_DIR = Path(__file__).resolve().parents[1] / "pet" / "persona_presets"
CJK = re.compile(r"[一-鿿]")
FIELD = re.compile(r"\{([A-Za-z_][A-Za-z0-9_.]*)")


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")
    pp.reload_builtin_presets()


def _read(name: str) -> dict:
    return json.loads((PRESET_DIR / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("mode", pp._BUILTIN_MODES)
def test_the_english_file_mirrors_the_chinese_one(mode):
    zh, en = _read(f"{mode}.json"), _read(f"{mode}.en.json")
    assert set(en) == set(zh), "英文版键集合必须和中文版一致"
    for key, lines in en.items():
        assert 1 <= len(lines) <= 8 and all(len(line) <= 240 for line in lines), key
        assert not any(CJK.search(line) for line in lines), f"{key} 的英文里还有中文"
        allowed = {field for line in zh[key] for field in FIELD.findall(line)}
        for line in lines:
            assert set(FIELD.findall(line)) <= allowed, f"{key} 用了中文版没有的占位符：{line}"


def test_builtin_phrases_follow_the_ui_language_and_fall_back_per_key(monkeypatch):
    assert "正在思考" in pp.builtin_phrases("legacy")["thinking"][0]
    i18n.set_language("en")
    assert pp.builtin_phrases("legacy")["thinking"][0] == "{name} is thinking."
    assert pp.builtin_phrases("whale_maid")["start"][0].startswith("Master~")
    assert pp.builtin_phrases("legacy", language="zh")["thinking"][0].startswith("{name} 正在思考")
    assert pp.builtin_phrases("legacy", language="fr") == pp.builtin_phrases("legacy", language="zh"), "没有的语言整套中文"
    monkeypatch.setitem(pp._presets_by_lang["en"], "legacy", {"start": ["{name} started."]})
    partial = pp.builtin_phrases("legacy")
    assert partial["start"] == ["{name} started."] and "正在思考" in partial["thinking"][0], "缺的键回退中文"


def test_the_picker_renders_english_and_the_fallback_stays_chinese():
    i18n.set_language("en")
    picker = pp.PhrasePicker()
    text = picker.get("whale_maid", "done.success", "回退", name="Claude Code")
    assert "Claude Code" in text and not CJK.search(text)
    assert picker.get("legacy", "no_such_event", "回退") == "回退"
    i18n.set_language("zh")
    assert "Claude Code" in picker.get("whale_maid", "done.success", "回退", name="Claude Code")
    assert CJK.search(picker.get("whale_maid", "done.success", "回退", name="Claude Code"))


def test_the_settings_preview_and_adopt_use_the_english_set(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from pet import modern_settings_dialog as settings_mod
    from pet.config import Config

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    config = Config(tmp_path)
    config.set("ui_language", "en")
    config.set("dialogue_mode", "whale_maid")
    dialog = settings_mod.ModernSettingsDialog(config, include_ai=False)
    try:
        preview = dialog.dialogue_phrase_edits["done.success"].toPlainText()
        assert preview == "\n".join(pp.builtin_phrases("whale_maid", language="en")["done.success"])
        assert dialog._adopt_builtin_phrases(confirm=lambda *_: True)
        assert dialog.dialogue_phrase_edits["start"].toPlainText().startswith("Master~")
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
