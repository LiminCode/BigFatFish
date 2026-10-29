# -*- coding: utf-8 -*-
"""会话小鱼详情卡的配色方案（纯数据，不依赖 Qt）。

详情卡原先借用「气泡样式」的三个颜色拼界面，按钮底色直接用气泡的边框色。气泡的边框
可以是深色（「吐气水泡」是深青 ``#0e5968``），按钮上的字又用气泡的正文色（深青灰
``#23444d``）——深底配深字，对比度只有 1.3，看不清。

所以详情卡改用自己的一组方案：每个方案把卡片底、正文、次要文字、按钮底、按钮字、
悬停态都明确写出来，不再从别处推导。用户只在几个命名好的方案里选，不开放自定义颜色
——自定义就又回到「能配出看不清的组合」。``tests/test_session_card_themes.py`` 对每个
方案逐项验对比度，新增或改动方案时过不了那里就别合。

``accent`` / ``accent_text``：详情卡改成 Metro 风格后（2026-10-28），页头那条带子、主按钮、状态
磁贴、上下文平条用的强调色。每个方案一个饱和的深色配白字——「深夜墨蓝」的悬停色是浅灰，
拿它当页头会在深色卡片上顶一块白板，所以单独给。
"""

from __future__ import annotations

from .i18n import t

#: 顺序即菜单里的顺序
CARD_THEMES: dict[str, dict[str, str]] = {
    "sea": {
        "label": "海盐青",
        "background": "#f1fafb", "border": "#0e5968", "shadow": "#0e5968",
        "text": "#12363d", "muted": "#47666c",
        "button": "#d3ecef", "button_border": "#7fb9c1", "button_text": "#0b3c45",
        "hover": "#0e5968", "hover_text": "#ffffff", "disabled_text": "#8aa3a8",
        "accent": "#0e5968", "accent_text": "#ffffff",
    },
    "cream": {
        "label": "奶油暖黄",
        "background": "#fffaf0", "border": "#d9a63c", "shadow": "#6b542b",
        "text": "#3a3020", "muted": "#6f6247",
        "button": "#f8e7b9", "button_border": "#d9a63c", "button_text": "#3a3020",
        "hover": "#5a4a22", "hover_text": "#fffaf0", "disabled_text": "#b3a684",
        "accent": "#7a4f0e", "accent_text": "#ffffff",
    },
    "paper": {
        "label": "素白纸张",
        "background": "#ffffff", "border": "#aeb8c6", "shadow": "#374151",
        "text": "#1f2430", "muted": "#5b6472",
        "button": "#e9edf3", "button_border": "#aeb8c6", "button_text": "#1f2430",
        "hover": "#1f2430", "hover_text": "#ffffff", "disabled_text": "#a3abb7",
        "accent": "#0b4f96", "accent_text": "#ffffff",
    },
    "night": {
        "label": "深夜墨蓝",
        "background": "#1f2430", "border": "#5a6684", "shadow": "#0c0e14",
        "text": "#f2f4f8", "muted": "#aab3c5",
        "button": "#343d53", "button_border": "#6a7798", "button_text": "#f2f4f8",
        "hover": "#e6eaf2", "hover_text": "#1f2430", "disabled_text": "#6d778c",
        "accent": "#2a5699", "accent_text": "#ffffff",
    },
    "sakura": {
        "label": "樱花粉",
        "background": "#fff4f6", "border": "#dc8aa2", "shadow": "#8a3350",
        "text": "#4a2530", "muted": "#7a5560",
        "button": "#fbdbe3", "button_border": "#dc8aa2", "button_text": "#4a2530",
        "hover": "#8a3350", "hover_text": "#ffffff", "disabled_text": "#c2a1aa",
        "accent": "#9c2f55", "accent_text": "#ffffff",
    },
}
DEFAULT_CARD_THEME = "sea"
CONFIG_KEY = "session_card_theme"      # 存在 agent_link 这个配置字典里


def normalize_theme_id(value) -> str:
    """认识的方案 id 原样返回；不认识的（手改配置、旧版本没有的方案）回到默认。"""
    theme_id = str(value or "").strip()
    return theme_id if theme_id in CARD_THEMES else DEFAULT_CARD_THEME


def card_theme(value) -> dict[str, str]:
    return CARD_THEMES[normalize_theme_id(value)]


def theme_choices() -> list[tuple[str, str]]:
    """``[(id, 名字), …]``，给菜单用。"""
    # 显示名跟随界面语言；CARD_THEMES 里的中文是 zh 原文
    return [(theme_id, t(f"menu.card_theme.{theme_id}")) for theme_id in CARD_THEMES]


def _luminance(color: str) -> float:
    value = color.lstrip("#")
    channels = []
    for index in (0, 2, 4):
        c = int(value[index:index + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(first: str, second: str) -> float:
    """WCAG 对比度（1 = 完全一样，21 = 黑白）。正文要求 ≥ 4.5。"""
    lighter, darker = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)
