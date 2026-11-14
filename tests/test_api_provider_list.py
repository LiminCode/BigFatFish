# -*- coding: utf-8 -*-
"""API/Provider 列表：设置页可添加、切换、删除多套 API 配置。"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

from pet.config import Config


def _app():
    return QApplication.instance() or QApplication([])


def test_chat_settings_provider_list_add_switch_delete(tmp_path):
    """AI 设置对话框：API 列表添加后能切换并保留编辑，删除后回到默认项。"""
    from pet.chat.settings_dialog import ChatSettingsDialog

    _app()
    cfg = Config(tmp_path)
    dlg = ChatSettingsDialog(cfg)
    try:
        assert dlg.provider_combo.count() == 1
        assert dlg.settings.active_provider == "openai-main"

        dlg._add_provider()
        new_pid = dlg.settings.active_provider
        assert dlg.provider_combo.count() == 2
        assert new_pid != "openai-main"
        assert new_pid in dlg.settings.providers

        # 修改新 API 后切到默认项再切回，草稿应保留
        dlg.name.setText("Second API")
        dlg.provider_combo.setCurrentIndex(dlg.provider_combo.findData("openai-main"))
        assert dlg.settings.active_provider == "openai-main"
        dlg.provider_combo.setCurrentIndex(dlg.provider_combo.findData(new_pid))
        assert dlg.name.text() == "Second API"

        # 删除新 API 后回到唯一默认项
        dlg._delete_provider()
        assert dlg.provider_combo.count() == 1
        assert dlg.settings.active_provider == "openai-main"
        assert dlg.settings.providers.keys() == {"openai-main"}
    finally:
        dlg.close()
        _app().processEvents()


def test_chat_settings_provider_id_not_reused_after_delete(tmp_path):
    """删除后再次添加不能复用已删除 provider_id，避免保存合并误过滤。"""
    from pet.chat.settings_dialog import ChatSettingsDialog

    _app()
    cfg = Config(tmp_path)
    dlg = ChatSettingsDialog(cfg)
    try:
        dlg._add_provider()
        first_pid = dlg.settings.active_provider
        dlg._delete_provider()
        dlg._add_provider()
        second_pid = dlg.settings.active_provider
        assert second_pid != first_pid
        assert first_pid not in dlg.settings.providers
        assert second_pid in dlg.settings.providers
    finally:
        dlg.close()
        _app().processEvents()


def test_chat_settings_provider_switch_keeps_key_draft(tmp_path):
    """切走再切回后，已录入但未保存的 API Key 不应被空输入框覆盖丢失。"""
    from pet.chat.settings_dialog import ChatSettingsDialog

    _app()
    cfg = Config(tmp_path)
    dlg = ChatSettingsDialog(cfg)
    try:
        dlg._add_provider()
        new_pid = dlg.settings.active_provider
        dlg.key.setText("sk-draft")

        # 切到默认项再切回：_load_provider_ui 会清空 Key 输入框
        dlg.provider_combo.setCurrentIndex(dlg.provider_combo.findData("openai-main"))
        assert dlg.settings.active_provider == "openai-main"
        dlg.provider_combo.setCurrentIndex(dlg.provider_combo.findData(new_pid))
        assert dlg.key.text() == ""
        assert dlg._provider_drafts[new_pid]["key"] == "sk-draft"
    finally:
        dlg.close()
        _app().processEvents()


def test_chat_settings_provider_list_save_persists_active_provider(tmp_path):
    """保存后 active_provider 与新增 Provider 应写入配置。"""
    from pet.chat.settings_dialog import ChatSettingsDialog

    _app()
    cfg = Config(tmp_path)
    dlg = ChatSettingsDialog(cfg)
    try:
        dlg._add_provider()
        new_pid = dlg.settings.active_provider
        dlg.name.setText("Second API")
        dlg.save()

        reloaded = cfg.chat_settings()
        assert reloaded.active_provider == new_pid
        assert new_pid in reloaded.providers
        assert reloaded.providers[new_pid].name == "Second API"
    finally:
        dlg.close()
        _app().processEvents()


def test_modern_ai_page_provider_list_add_switch_delete(tmp_path, monkeypatch):
    """现代设置 AI 页：API 列表同样支持添加/切换/删除。"""
    import pet.modern_settings_dialog as settings_mod

    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    _app()
    cfg = Config(tmp_path)
    dlg = settings_mod.ModernSettingsDialog(cfg, include_ai=True)
    try:
        page = dlg.ai_page
        assert page.provider_combo.count() == 1
        assert page.settings.active_provider == "openai-main"

        page._add_provider()
        new_pid = page.settings.active_provider
        assert page.provider_combo.count() == 2
        assert new_pid != "openai-main"

        page.name.setText("Second API")
        page.provider_combo.setCurrentData("openai-main")
        assert page.settings.active_provider == "openai-main"
        page.provider_combo.setCurrentData(new_pid)
        assert page.name.text() == "Second API"

        page._delete_provider()
        assert page.provider_combo.count() == 1
        assert page.settings.providers.keys() == {"openai-main"}
    finally:
        dlg.close()
        _app().processEvents()


# ---------------------------------------------------------------- 现代设置 AI 页：列表看得见自己的改动
# 2026-11-13 用户反馈：「添加了一个模型，保存后看不到在哪里」——下拉框里那一项一直显示添加时的
# 「DeepSeek 副本 · deepseek-v4-flash」，不跟名称 / 模型的编辑走，也看不出聊天在用哪一项。

def _modern_dialog(tmp_path, monkeypatch):
    import pet.modern_settings_dialog as settings_mod

    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    _app()
    return settings_mod.ModernSettingsDialog(Config(tmp_path), include_ai=True)


def _labels(page) -> list[str]:
    return [page.provider_combo.itemText(i) for i in range(page.provider_combo.count())]


def test_modern_provider_label_follows_name_and_model_edits(tmp_path, monkeypatch):
    from pet.i18n import t

    dlg = _modern_dialog(tmp_path, monkeypatch)
    try:
        page = dlg.ai_page
        page._add_provider()
        page.name.setText("Claude")
        page.model.setText("claude-sonnet-5-5")
        assert page.provider_combo.currentText().startswith("Claude · claude-sonnet-5-5"), _labels(page)
        assert t("settings.ai.in_use") not in page.provider_combo.currentText(), "新加的那项还没保存，不是在用的"
    finally:
        dlg.close()
        _app().processEvents()


def test_modern_provider_in_use_marker_moves_on_save(tmp_path, monkeypatch):
    from pet.i18n import t

    in_use = t("settings.ai.in_use")
    dlg = _modern_dialog(tmp_path, monkeypatch)
    try:
        page = dlg.ai_page
        assert in_use in _labels(page)[0], "聊天在用的那一项要标出来"
        page._add_provider()
        page.name.setText("Claude")
        page.model.setText("claude-sonnet-5-5")
        dlg.save_button.click()                       # 「保存」：写盘不关窗
        labels = _labels(page)
        assert in_use not in labels[0] and in_use in labels[1], labels
        assert labels[1].startswith("Claude · claude-sonnet-5-5")
        row = dlg.findChild(type(page._test_row), "settingRow_provider_list")
        assert row.hint_label.text() == t("settings.ai.pick_model_service_edit_switch"), "保存后提示复原"
        reloaded = dlg.config.chat_settings()
        assert reloaded.providers[reloaded.active_provider].name == "Claude"
    finally:
        dlg.close()
        _app().processEvents()


def test_modern_add_provider_says_what_to_do_next(tmp_path, monkeypatch):
    from pet.i18n import t

    dlg = _modern_dialog(tmp_path, monkeypatch)
    try:
        page = dlg.ai_page
        row = dlg.findChild(type(page._test_row), "settingRow_provider_list")   # 设置窗口会把行搬进自己的页面
        before = row.hint_label.text()
        page._add_provider()
        assert row.hint_label.text() == t("settings.ai.added_next_step", name=page.name.text())
        assert row.hint_label.text() != before
        assert page.name.selectedText() == page.name.text(), "名称已全选：直接打字就替换掉「副本」"
        page.provider_combo.setCurrentData("openai-main")
        assert row.hint_label.text() == before, "切走后提示复原"
    finally:
        dlg.close()
        _app().processEvents()


def test_modern_provider_section_uses_plain_words():
    """用户问「API 列表是什么」：分节名和提示不再用 API 列表 / Provider / active_provider 这类内部词。"""
    import json
    from pathlib import Path

    zh = json.loads((Path(__file__).resolve().parents[1] / "pet" / "locale" / "zh.json").read_text(encoding="utf-8"))
    for key in ("settings.ai.api_list", "settings.dlg.api_list", "settings.ai.provider_name",
                "settings.ai.pick_model_service_edit_switch", "settings.ai.check_current_provider_api_address"):
        text = zh[key]
        assert "API 列表" not in text and "Provider" not in text and "active_provider" not in text, (key, text)


def test_modern_select_item_text_can_change():
    from pet.settings_widgets import ModernSelect

    _app()
    select = ModernSelect()
    select.addItem("a", 1)
    select.addItem("b", 2)
    select.setItemText(0, "a2")
    select.setItemText(1, "b2")
    assert select.currentText() == "a2" and select.text() == "a2"
    assert select.itemText(1) == "b2"
