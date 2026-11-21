# -*- coding: utf-8 -*-
"""Qt 窗口的白天 / 黑夜：「外观」里的主题偏好 → 明 / 暗 → Metro 色板。

主题只有一个来源——``context_menu_appearance.theme``（``system`` / ``light`` / ``dark``）。会话记忆蒸馏的流程页、用量看板、
岛的连接面板都按它取色；窗口右上角 ☾ / ☀ 切换时写回同一个偏好，设置页和右键菜单跟着变——这是有意的全局白天 / 黑夜，
不要给某扇窗单独加主题键。浏览器里的页面（配置全景、报告页、笔记页）也读同一个偏好（``panorama.reports.theme``）。

这几个函数原来在简报窗口的模块里；简报窗口 2026-11-21 下线（内容页都搬进了浏览器，ADR 0018），它们搬到这里。
"""

from __future__ import annotations

from .settings_widgets import _system_dark
from .theme_tokens import METRO_TOKENS

THEMES = ("system", "light", "dark")


def resolve_dark(theme: str) -> bool:
    """``system`` 跟随系统；别的按字面。"""
    return theme == "dark" or (theme not in ("light",) and _system_dark())


def window_tokens(dark: bool) -> dict:
    """窗口样式表用的那张 Metro 色板（明或暗），一份拷贝。"""
    return dict(METRO_TOKENS["dark" if dark else "light"])


def theme_preference(config) -> str:
    """「外观」里的主题（system / light / dark）。"""
    try:
        return str((config.get("context_menu_appearance") or {}).get("theme") or "system")
    except Exception:  # noqa: BLE001
        return "system"


def save_theme_preference(config, theme: str) -> None:
    """窗口上切了白天 / 黑夜：写回同一个偏好（设置页、菜单也跟着变）。"""
    try:
        current = dict(config.get("context_menu_appearance") or {})
        current["theme"] = theme
        config.set("context_menu_appearance", current)
        config.save()
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).exception("保存主题偏好失败")
