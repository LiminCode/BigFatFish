# -*- coding: utf-8 -*-
"""QuickChatBubble 气泡外形回归。"""
from __future__ import annotations

from pet.quick_chat import _surface_radius
from pet.speech_bubble import BUBBLE_STYLE_PRESETS


def test_breath_bubble_preset_gets_rounded_fallback_radius():
    """breath_bubble 是 speech_bubble 专属有机形（preset 里 radius=0）：
    quick_chat 不支持该形状，直接按 0 渲染会变直角方框——同一
    self_talk_bubble_style 设置两套观感。必须给大圆角近似回退。"""
    preset = BUBBLE_STYLE_PRESETS["breath_bubble"]
    assert preset.get("shape") == "breath_bubble"
    assert _surface_radius(preset) > 0


def test_regular_preset_uses_own_radius():
    """普通预设用自己的 radius（回退不得影响既有外观）。"""
    preset = BUBBLE_STYLE_PRESETS["classic_top"]
    assert _surface_radius(preset) == float(preset.get("radius", 14))


def test_reply_renders_markdown(tmp_path):
    """快捷气泡的助手回复按 Markdown 渲染（对齐现代聊天窗的口径，上游 5b9b39a3）——
    上游用户反馈 v4.3.0 快捷气泡里 markdown 原文直出（**、## 符号裸露）。"""
    from PySide6.QtWidgets import QApplication

    from pet.config import Config
    from pet.quick_chat import QuickChatBubble

    app = QApplication.instance() or QApplication([])
    bubble = QuickChatBubble(Config(base=tmp_path))
    try:
        bubble._set_reply_text("重点**加粗**收尾")
        bubble._render_reply()
        assert "font-weight:700" in bubble.output.text() and "加粗" in bubble.output.text(), \
            f"markdown 未渲染: {bubble.output.text()[:80]}"  # Qt 写 span font-weight 而非 <strong>
    finally:
        bubble.close()
        app.processEvents()
