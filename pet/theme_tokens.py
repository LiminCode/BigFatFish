# -*- coding: utf-8 -*-
"""Metro 颜色令牌（明 / 暗）：**唯一的一张表**。

Qt 这边的样式表（``settings_theme_qss``、灵动岛、通知卡片、简报窗口、用量看板）和配置全景的网页都从这里取颜色，
所以两边的强调色、输入框、按钮永远是同一个值。这个模块不 import Qt：网页那一侧在没有界面的进程里也要用它。

改颜色只改这里。网页拿到的是 ``tokens_css()`` 生成的 CSS 变量（``--m-<名字>``，下划线换成短横线）。
"""
from __future__ import annotations

#: 颜色令牌（明 / 暗）。测试按这张表核对 QSS 和网页样式里的值。
METRO_TOKENS = {
    "light": {
        "page": "#f2f2f2", "sidebar": "#e6e6e8", "tile": "#ffffff", "tile_hover": "#f7f7f7", "divider": "#ececec",
        "title": "#111111", "text": "#1f1f1f", "muted": "#6d6d6d", "disabled": "#a8a8a8",
        "outline": "#333333", "selected": "#0a84ff", "selected_text": "#ffffff", "accent": "#0a84ff",
        "field": "#ffffff", "field_border": "#b9b9b9", "match": "#dcebff",
    },
    "dark": {
        "page": "#1b1b1f", "sidebar": "#141417", "tile": "#2a2a2f", "tile_hover": "#33333a", "divider": "#38383f",
        "title": "#f4f4f6", "text": "#e6e6ea", "muted": "#9a9aa3", "disabled": "#6a6a72",
        "outline": "#e6e6e6", "selected": "#0a84ff", "selected_text": "#ffffff", "accent": "#0a84ff",
        "field": "#26262b", "field_border": "#4a4a54", "match": "#223a5c",
    },
}

CSS_PREFIX = "--m-"
#: 网页上切到浅色用的选择器。现在没有页面设它：地图自己的配色只有深色那一套，浅色等地图有了浅色配色再启用。
LIGHT_SELECTOR = ':root[data-theme="light"]'


def css_variables(theme: str) -> dict[str, str]:
    """一个主题的令牌 → CSS 变量名与值（``tile_hover`` → ``--m-tile-hover``）。"""
    return {CSS_PREFIX + key.replace("_", "-"): value for key, value in METRO_TOKENS[theme].items()}


def tokens_css() -> str:
    """给网页的令牌样式表：默认深色，``data-theme="light"`` 时换成浅色。"""
    def block(selector: str, theme: str) -> str:
        return selector + "{" + ";".join(f"{name}:{value}" for name, value in css_variables(theme).items()) + "}\n"

    return block(":root", "dark") + block(LIGHT_SELECTOR, "light")
