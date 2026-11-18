# -*- coding: utf-8 -*-
"""聊天服务地址的规范化（``normalize_chat_endpoint``）。

原先和「看看屏幕」的视觉模型测试放在 test_vision.py 里；看屏幕在 2026-11-18 删掉了（ADR 0016），只留下这几条。
"""


def test_endpoint_glm_v4_base():
    from pet.chat.providers import normalize_chat_endpoint
    assert normalize_chat_endpoint('https://open.bigmodel.cn/api/paas/v4') == \
        'https://open.bigmodel.cn/api/paas/v4/chat/completions'


def test_endpoint_openai_v1_base():
    from pet.chat.providers import normalize_chat_endpoint
    assert normalize_chat_endpoint('https://api.openai.com/v1') == \
        'https://api.openai.com/v1/chat/completions'


def test_endpoint_full_url_passthrough():
    from pet.chat.providers import normalize_chat_endpoint
    assert normalize_chat_endpoint('https://api.deepseek.com/v1/chat/completions') == \
        'https://api.deepseek.com/v1/chat/completions'


def test_endpoint_bare_host_appends_default_path():
    from pet.chat.providers import normalize_chat_endpoint
    assert normalize_chat_endpoint('https://api.deepseek.com') == \
        'https://api.deepseek.com/v1/chat/completions'
