# -*- coding: utf-8 -*-
"""设置页「音乐关联」里的「浏览器媒体会话参与歌词」行（仅 Windows）。

**为什么单独一个模块**：``modern_settings_dialog.py`` 的行数预算已无余量（与
``settings_file_interpret.py`` 同口径）。

2026-10-15 之前这里还有「网易云 / QQ 音乐程序位置」两行和「自动检测播放器」按钮，
给右键菜单「打开网易云 / QQ 音乐给主人放歌」找程序用；那一整块随本地播放器启动一起
下线，听歌改为右键菜单「YouTube Music」（网页版，见 ``context_menus.shared.add_youtube_music``）。
"""

from __future__ import annotations

import sys

from .settings_widgets import SettingRow
from .i18n import t


def browser_media_supported() -> bool:
    """「浏览器媒体会话参与歌词」是否在本平台可用——SMTC 是 Windows 专属。"""
    return sys.platform == "win32"


def browser_media_rows(dialog) -> list[SettingRow]:
    """「浏览器媒体会话参与歌词」设置行（**仅 Windows**）。

    SMTC 是 Windows 专属能力：非 Windows 上这个开关既无效也不该出现
    （SETTINGS-CHANGE-GATES §4「永久不支持的能力不创建控件」）。控件本体也只在
    Windows 创建（``settings_pet_controls``），所以这里以「控件在不在」为准——
    与 ``cursor_hidden_passthrough`` 的处置一致，不会出现"控件在、行不在"的
    游离开关（那会被孤儿开关测试拦下）。

    hint 里如实写清代价：浏览器把网页视频也上报成音乐类型，开着就会对着视频
    显示「我在唱」并取词；网页版音乐平台（YouTube Music）需要它才有歌词。
    """
    check = getattr(dialog, "music_browser_media_check", None)
    if check is None or not browser_media_supported():
        return []
    return [
        SettingRow(
            "music_browser_media",
            t("settings.music.browser_media_sessions_take_part"),
            t("settings.music.when_off_whatever_plays_browser"),
            check,
        )
    ]
