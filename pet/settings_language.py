# -*- coding: utf-8 -*-
"""设置页「常规」里的「界面语言 (Language)」一行。控件、提示、保存都在这里。

目前只覆盖灵动岛胶囊与展开卡片（2026-10-14 第一片）；其余界面仍是中文，逐片推进。
"""

from __future__ import annotations

from . import i18n
from .settings_widgets import ModernSelect, SettingRow

_HINT = ("灵动岛胶囊与展开卡片上的文字用哪种语言；其余界面暂时仍是中文。保存后立即生效。 / "
         "Language of the island capsule and its card; the rest of the UI is still Chinese for now.")


def language_rows(dialog) -> list[SettingRow]:
    select = ModernSelect(dialog, width=160)
    for code in i18n.LANGUAGES:
        select.addItem(i18n.LANGUAGE_LABELS[code], code)
    current = i18n.normalize_language(dialog.config.get(i18n.CONFIG_KEY))
    select.setCurrentIndex(max(0, select.findData(current)))
    dialog.ui_language_select = select
    return [SettingRow("ui_language", "界面语言 (Language)", _HINT, select)]


def save_language_setting(dialog) -> None:
    select = getattr(dialog, "ui_language_select", None)
    if select is not None:
        dialog.config.set(i18n.CONFIG_KEY, i18n.normalize_language(select.currentData()))
