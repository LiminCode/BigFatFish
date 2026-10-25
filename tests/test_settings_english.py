# -*- coding: utf-8 -*-
"""设置窗口的英文界面（用户 2026-10-16：「这次翻译设置里的大多数选项」）。

守住的：
- 界面语言是 English 时，设置窗口里可见的文字（侧栏、页 / 节标题、行标题与提示、按钮、下拉项、占位）
  不再有中文，只剩有意保留的几处：语言那一行的中英双语标题、语言下拉里的「中文」自称、
  自定义中文台词框里的中文示例、内置对话背景主题的名字（内容名，不是界面文字）；
- 侧栏域名的中文是内部标识：英文界面下 select_page 用中文名和英文名都能跳；
- 导入时就求值的表（事件名、模板参数、侧栏域、文件过滤器、报时频率、音色、气泡方案……）显示时跟随语言；
- 中英两张表里 settings.* 的每个键，占位符一致；
- 中文界面不受影响。
"""
from __future__ import annotations

import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QAbstractButton, QApplication, QComboBox, QLabel, QLineEdit, QPlainTextEdit

from pet import i18n
from pet.config import Config

app = QApplication.instance() or QApplication([])
CJK = re.compile(r"[一-鿿]")
EN_DOMAINS = ["General", "Fish", "Interaction", "Menu", "Desktop widgets", "AI and chat", "Briefings & notes", "Automation", "Voice", "File recognition"]
ZH_DOMAINS = ["常规", "肥鱼", "互动", "菜单", "桌面组件", "AI 与对话", "简报与笔记", "自动化与联动", "语音", "文件识别"]


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


def _dialog(tmp_path, monkeypatch, language: str):
    from pet import modern_settings_dialog as settings_mod

    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    config = Config(tmp_path)
    config.set("ui_language", language)
    return settings_mod.ModernSettingsDialog(config, include_ai=True)


def _close(dialog):
    dialog.close()
    dialog.deleteLater()
    app.processEvents()


def _visible_texts(dialog) -> set[str]:
    from pet.settings_widgets import ModernSelect

    texts: set[str] = set()
    for label in dialog.findChildren(QLabel):
        texts.add(label.text())
    for button in dialog.findChildren(QAbstractButton):
        texts.update((button.text(), button.toolTip()))
    for edit in dialog.findChildren(QLineEdit) + dialog.findChildren(QPlainTextEdit):
        texts.add(edit.placeholderText())
    for combo in dialog.findChildren(QComboBox):
        texts.update(combo.itemText(i) for i in range(combo.count()))
    for select in dialog.findChildren(ModernSelect):
        texts.update(select.itemText(i) for i in range(select.count()))
    texts.update(dialog.sidebar.item(i).text() for i in range(dialog.sidebar.count()))
    return {text for text in texts if text}


def test_the_english_settings_window_has_no_chinese_left_except_on_purpose(tmp_path, monkeypatch):
    from pet.chat.themes import theme_names

    dialog = _dialog(tmp_path, monkeypatch, "en")
    try:
        allowed_names = {name for _key, name in theme_names()} | {"中文"}
        leftovers = sorted(
            text for text in _visible_texts(dialog)
            if CJK.search(text) and text not in allowed_names
            and "语言" not in text                     # 语言那一行有意中英双语
            and "今夜月明人尽望" not in text            # 自定义中文台词框里的中文示例
        )
        assert leftovers == [], leftovers
        assert [dialog.sidebar.item(i).text() for i in range(dialog.sidebar.count())] == EN_DOMAINS
        assert dialog.windowTitle() == "Fish Settings"
    finally:
        _close(dialog)


def test_the_chinese_settings_window_is_unchanged(tmp_path, monkeypatch):
    dialog = _dialog(tmp_path, monkeypatch, "zh")
    try:
        assert [dialog.sidebar.item(i).text() for i in range(dialog.sidebar.count())] == ZH_DOMAINS
        assert dialog.windowTitle() == "肥鱼设置"
        from pet.settings_widgets import SettingRow

        assert dialog.findChild(SettingRow, "settingRow_on_top").label.text() == "窗口置顶"
    finally:
        _close(dialog)


def test_deep_links_accept_the_chinese_domain_name_in_an_english_window(tmp_path, monkeypatch):
    dialog = _dialog(tmp_path, monkeypatch, "en")
    try:
        assert dialog.select_page("自动化与联动"), "中文域名是内部标识：深链接照样认"
        assert dialog.sidebar.currentItem().text() == "Automation"
        assert dialog.select_page("Voice") and dialog.sidebar.currentItem().text() == "Voice"
        assert not dialog.select_page("no such page")
    finally:
        _close(dialog)


def test_rows_hints_and_buttons_speak_english(tmp_path, monkeypatch):
    from pet.settings_widgets import SettingRow

    dialog = _dialog(tmp_path, monkeypatch, "en")
    try:
        def row(key):
            found = dialog.findChild(SettingRow, f"settingRow_{key}")
            assert found is not None, key
            return found

        assert row("on_top").label.text() == "Always on top"
        assert row("on_top").hint_label.text() == "Keep the fish above other windows."
        assert row("slack_watch_interval").hint_label.text().startswith("Minutes between checks")
        assert row("vscode_menu_limit").hint_label.text().startswith("Most items the menu lists")
        assert row("tray_icon").hint_label.text().startswith("The icon shown in the notification area")
        assert dialog.save_button.text() == "Save"
        from pet.settings_widgets import ModernSelect

        items = {select.itemText(i) for select in dialog.findChildren(ModernSelect) for i in range(select.count())}
        for expected in ("On the hour", "By count", "Classic warm yellow · above", "Xiaoxiao (female · natural)",
                         "Fish widescreen", "Follow system"):
            assert expected in items, expected
    finally:
        _close(dialog)


def test_no_button_is_capped_narrower_than_its_english_text(tmp_path, monkeypatch):
    """2026-10-16 截图：「Choose…」「Preview」按中文定宽，英文被截成「hoose」「Previe」。"""
    from PySide6.QtWidgets import QPushButton

    dialog = _dialog(tmp_path, monkeypatch, "en")
    try:
        dialog.show()
        app.processEvents()
        capped = sorted(
            button.text() for button in dialog.findChildren(QPushButton)
            if button.text() and button.maximumWidth() < button.sizeHint().width()
        )
        assert capped == [], capped
    finally:
        _close(dialog)


def test_search_works_on_english_labels(tmp_path, monkeypatch):
    dialog = _dialog(tmp_path, monkeypatch, "en")
    try:
        dialog.search_edit.setText("Always on top")
        app.processEvents()
        assert dialog.search_status.text().endswith("· Always on top")
        dialog.search_edit.setText("zzzz-nothing")
        assert dialog.search_status.text() == "No matching settings"
    finally:
        _close(dialog)


# ---------------------------------------------------------------- 导入时求值的表：显示时跟随语言
def test_static_tables_follow_the_language():
    from pet import modern_settings_dialog as dlg
    from pet import settings_pet_controls as pc
    from pet.settings_widgets import AUDIO_NAME_FILTER, IMAGE_NAME_FILTER, domain_label

    i18n.set_language("en")
    assert dlg.dialogue_label("done.success") == "Task done"
    assert dlg.dialogue_label("not.a.key") == "not.a.key"
    assert dlg.dialogue_param("errorCode").startswith("error code")
    assert domain_label("自动化与联动") == "Automation" and domain_label("whatever") == "whatever"
    assert i18n.maybe_t(IMAGE_NAME_FILTER).startswith("Image files (")
    assert i18n.maybe_t(AUDIO_NAME_FILTER).startswith("Audio files (")
    assert i18n.maybe_t("Custom (*.x)") == "Custom (*.x)", "传现成文字原样返回"
    assert pc.stream_capture_hint().startswith("Lets tools such as OBS")
    i18n.set_language("zh")
    assert dlg.dialogue_label("done.success") == "任务完成"
    assert domain_label("自动化与联动") == "自动化与联动"
    assert pc.stream_capture_hint().startswith("让 OBS 等工具能够枚举并捕获肥鱼窗口。")


def test_every_settings_key_keeps_its_placeholders_in_english():
    field = re.compile(r"(?<!\{)\{([A-Za-z_][A-Za-z0-9_]*)[^{}]*\}(?!\})")
    zh, en = i18n.table("zh"), i18n.table("en")
    keys = [key for key in zh if key.startswith("settings.")]
    assert len(keys) > 700, "设置窗口的大多数文案都进了表"
    mismatched = [key for key in keys if set(field.findall(zh[key])) != set(field.findall(en.get(key, "")))]
    assert mismatched == []
    assert [key for key in keys if key not in en] == []
