# -*- coding: utf-8 -*-
"""会话小鱼的金色桂冠：给跑着指定模型的会话戴（不碰 Qt）。

配置 ``agent_link.crown_models`` 是一串小写的匹配片段：模型 id（``claude-fable-5-1``）里
含有任一片段就戴。片段可以是家族名（``fable``：这个家族的全部版本）或更具体的
（``opus-5-5``）。以后有更强的模型出现，在菜单里勾上它即可。
"""

from __future__ import annotations

import re

from .claude_session_info import model_label

CONFIG_KEY = "crown_models"
DEFAULT_TOKENS = ["fable"]
#: 菜单里固定列出的家族（按当前的强弱印象排）
FAMILIES = (("fable", "Fable"), ("opus", "Opus"), ("sonnet", "Sonnet"), ("haiku", "Haiku"))
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


def choices(tokens, seen_models=()) -> list[tuple[str, str, bool]]:
    """菜单用：``(片段, 文案, 是否勾选)``——四个家族在前，在场会话的具体型号在后（去重）。"""
    tokens = list(tokens or ())
    out = [(token, f"{label}（全部版本）", token in tokens) for token, label in FAMILIES]
    listed = {token for token, _label, _on in out}
    for model in seen_models:
        token = str(model or "").strip().lower()
        if token and token not in listed and _TOKEN_RE.match(token):
            listed.add(token)
            out.append((token, model_label(token), token in tokens))
    return out


def toggled(tokens, token: str, on: bool) -> list[str]:
    tokens = [t for t in normalize_tokens(list(tokens or ())) if t != token]
    if on and _TOKEN_RE.match(token):
        tokens.append(token)
    return tokens
