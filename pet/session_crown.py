# -*- coding: utf-8 -*-
"""会话小鱼的金色桂冠：给跑着指定模型的会话戴（不碰 Qt）。

配置 ``agent_link.crown_models`` 是一串小写的匹配片段：模型 id（``claude-fable-5-1``）里
含有任一片段就戴。片段可以是家族名（``fable``：这个家族的全部版本）或更具体的
（``opus-5-5``）。以后有更强的模型出现，在菜单里勾上它即可。
"""

from __future__ import annotations

import re

CONFIG_KEY = "crown_models"
DEFAULT_TOKENS = ["fable"]
_TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,39}$")


def normalize_tokens(value) -> list[str]:
    """配置里的片段清单：小写、去空白、去重、丢掉不像样的；不是清单就回默认。"""
    if not isinstance(value, (list, tuple)):
        return list(DEFAULT_TOKENS)
    out: list[str] = []
    for item in value:
        token = str(item or "").strip().lower() if isinstance(item, str) else ""
        if token and _TOKEN_RE.match(token) and token not in out:
            out.append(token)
    return out


def is_crowned(model_id: str, tokens) -> bool:
    model = str(model_id or "").lower()
    return bool(model) and any(token and token in model for token in tokens or ())
