# -*- coding: utf-8 -*-
"""AI 设置「模型服务」：一行一个的列表，保存过的 API Key 打开时看得见（遮着，可显示）。"""
from __future__ import annotations

from pet.config import Config
from tests.test_api_provider_list import _app, _modern_dialog


# ---------------------------------------------------------------- 模型服务列表 + 看得见的 API Key
# 2026-11-14 用户：「模型服务保存的时候似乎 API key 在下次 load 时显示不出来……每添加一个模型 API，都放在
# 一个列表中，在模型服务下面，点击可以查看 API key，更新模型和 API key。」
# 查证：Key 没丢——一直在系统钥匙串里（灵动岛体检用的就是它），只是 Key 输入框打开时永远是空的。

class _KeyStore:
    values: dict = {}
    writes: list = []

    def __init__(self, *_args, **_kwargs):
        pass

    available = True

    def get(self, ref):
        return self.values.get(ref, "")

    def set(self, ref, value):
        self.writes.append(ref)
        self.values[ref] = value
        return True


def _two_service_dialog(tmp_path, monkeypatch):
    monkeypatch.setattr("pet.chat.models.SecretStore", _KeyStore)
    _KeyStore.values = {"provider/openai-main": "sk-deepseek-saved", "provider/claude": "sk-ant-saved"}
    _KeyStore.writes = []
    cfg = Config(tmp_path)
    cfg.data["chat"] = {"active_provider": "openai-main", "providers": {
        "openai-main": {"name": "DeepSeek", "model": "deepseek-v4-flash", "api_key_ref": "provider/openai-main"},
        "claude": {"name": "Claude", "base_url": "https://api.anthropic.com", "model": "claude-sonnet-5-5",
                   "api_key_ref": "provider/claude"},
    }}
    cfg.save()
    return _modern_dialog(tmp_path, monkeypatch)


def test_modern_model_services_are_a_list_you_click(tmp_path, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QListWidget

    dlg = _two_service_dialog(tmp_path, monkeypatch)
    try:
        page = dlg.ai_page
        services = page.provider_combo
        assert isinstance(services, QListWidget), "每个模型服务一行，不用点开下拉框"
        assert services.count() == 2
        assert services.height() >= 2 * services.sizeHintForRow(0), "两行都看得见，不用滚"
        row = services.visualItemRect(services.item(1))
        QTest.mouseClick(services.viewport(), Qt.MouseButton.LeftButton, pos=row.center())
        assert page.model.text() == "claude-sonnet-5-5", "点一行，下面编辑的就是它"
        assert page.key.text() == "sk-ant-saved"
    finally:
        dlg.close()
        _app().processEvents()


def test_modern_saved_api_key_is_shown_masked_and_can_be_revealed(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QLineEdit

    dlg = _two_service_dialog(tmp_path, monkeypatch)
    try:
        page = dlg.ai_page
        assert page.key.text() == "sk-deepseek-saved", "保存过的 Key 打开设置时要看得见（遮着）"
        assert page.key.echoMode() == QLineEdit.EchoMode.Password
        page.key_reveal.click()
        assert page.key.echoMode() == QLineEdit.EchoMode.Normal, "点「显示」看明文"
        page.provider_combo.setCurrentData("claude")
        assert page.key.text() == "sk-ant-saved"
        assert page.key.echoMode() == QLineEdit.EchoMode.Password, "换一项就重新遮上"
        assert not page.key_reveal.isChecked()
    finally:
        dlg.close()
        _app().processEvents()


def test_modern_update_model_and_key_of_a_listed_service(tmp_path, monkeypatch):
    dlg = _two_service_dialog(tmp_path, monkeypatch)
    try:
        page = dlg.ai_page
        page.provider_combo.setCurrentData("claude")
        page.model.setText("claude-opus-5-5")
        page.key.setText("sk-ant-rotated")
        dlg.save_button.click()
        saved = Config(tmp_path).chat_settings()
        assert saved.providers["claude"].model == "claude-opus-5-5"
        assert _KeyStore.values["provider/claude"] == "sk-ant-rotated"
        assert _KeyStore.writes == ["provider/claude"], "没改的 Key 不重写钥匙串"
    finally:
        dlg.close()
        _app().processEvents()
    reopened = _modern_dialog(tmp_path, monkeypatch)
    try:
        page = reopened.ai_page
        page.provider_combo.setCurrentData("claude")
        assert page.key.text() == "sk-ant-rotated", "下次打开还看得见新 Key"
        assert page.model.text() == "claude-opus-5-5"
    finally:
        reopened.close()
        _app().processEvents()
