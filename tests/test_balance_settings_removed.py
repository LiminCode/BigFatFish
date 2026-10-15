# -*- coding: utf-8 -*-
"""「余额与服务状态」（DeepSeek 余额刷新 / 峰谷文案 / 峰谷颜色）2026-10-14 从设置页下线。

配置键与余额代码保留：旧配置里的值原样留着、保存设置页不会动它们；设置页里不再有这些行、
也没有一行把它们落回「待分类」。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from pet.config import Config
from pet.settings_widgets import SettingRow

app = QApplication.instance() or QApplication([])

BALANCE_ROW_IDS = ("balance_refresh", "balance_tier_mode", "balance_tier_peak", "balance_tier_idle", "balance_tier_color")


def _dialog(tmp_path, monkeypatch, config=None):
    from pet import modern_settings_dialog as settings_mod

    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    return settings_mod.ModernSettingsDialog(config or Config(tmp_path), include_ai=True)


def test_the_balance_rows_and_section_are_gone(tmp_path, monkeypatch):
    dialog = _dialog(tmp_path, monkeypatch)
    try:
        ids = {row.objectName() for row in dialog.findChildren(SettingRow)}
        assert not {f"settingRow_{key}" for key in BALANCE_ROW_IDS} & ids
        assert not any(row.objectName().startswith("settingRow_balance_") for row in dialog.findChildren(SettingRow))
        titles = {label.text() for label in dialog.findChildren(QLabel, "sectionTitle")}
        assert "余额与服务状态" not in titles and "后台服务" not in titles
        assert "待分类（开发期）" not in titles, "下线不能靠把行丢进待分类"
        for name in ("balance_refresh_spin", "balance_tier_mode_select", "balance_tier_color_check"):
            assert not hasattr(dialog, name)
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_saving_the_page_leaves_the_old_balance_keys_untouched(tmp_path, monkeypatch):
    config = Config(tmp_path)
    config.set("balance_refresh_minutes", 30)
    config.set("balance_tier_labels_mode", "liangwen")
    config.set("balance_tier_color_enabled", False)
    dialog = _dialog(tmp_path, monkeypatch, config)
    try:
        dialog._save()
        assert config.get("balance_refresh_minutes") == 30
        assert config.get("balance_tier_labels_mode") == "liangwen"
        assert config.get("balance_tier_color_enabled") is False
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_no_setting_hint_mentions_deepseek(tmp_path, monkeypatch):
    dialog = _dialog(tmp_path, monkeypatch)
    try:
        hints = [label.text() for label in dialog.findChildren(QLabel, "settingHint")]
        offenders = [text for text in hints if "DeepSeek" in text or "deepseek" in text]
        assert offenders == [], offenders
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
