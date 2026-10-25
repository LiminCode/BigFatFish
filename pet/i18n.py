# -*- coding: utf-8 -*-
"""界面文字的查表层：``t("island.card.chat")`` → 当前语言下的文字。

键是英文标识符（点分命名空间、下划线连词），文字在 ``pet/locale/<语言>.json`` 里。
中文是默认语言；英文表里缺某个键时退回中文（不会把键名显示给用户），仓库里由
``tests/test_i18n.py`` 保证两张表的键一致、代码里用到的键都在表里。

带数字的句子用 ``{n}`` 占位；英文有单复数的键写成 ``<键>.one`` / ``<键>.other``，
``t(key, n=…)`` 自己挑。当前语言由 ``Config`` 在加载 / 重载时设置（``ui_language``）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

LANGUAGES = ("zh", "en")
LANGUAGE_LABELS = {"zh": "中文", "en": "English"}
DEFAULT_LANGUAGE = "zh"
CONFIG_KEY = "ui_language"
LOCALE_DIR = Path(__file__).with_name("locale")

_tables: dict[str, dict[str, str]] = {}
_current = DEFAULT_LANGUAGE
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


def normalize_language(value) -> str:
    code = str(value or "").strip().lower()
    return code if code in LANGUAGES else DEFAULT_LANGUAGE


def set_language(value) -> str:
    """换语言；返回实际生效的代码。"""
    global _current
    _current = normalize_language(value)
    return _current


def current_language() -> str:
    return _current


def table(language: str) -> dict[str, str]:
    """一张语言表（读一次缓存）；文件缺失或坏了算空表。"""
    language = normalize_language(language)
    cached = _tables.get(language)
    if cached is None:
        try:
            data = json.loads((LOCALE_DIR / f"{language}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        cached = {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
        _tables[language] = cached
    return cached


def reload_tables() -> None:
    _tables.clear()


def _lookup(language: str, key: str, n) -> str | None:
    words = table(language)
    if n is not None:
        form = words.get(f"{key}.one" if n == 1 else f"{key}.other")
        if form is not None:
            return form
    return words.get(key)


def t(key: str, **values) -> str:
    """当前语言下 ``key`` 的文字，``values`` 填进 ``{占位符}``。缺翻译退回中文，再缺退回键名。"""
    n = values.get("n")
    text = _lookup(_current, key, n)
    if text is None and _current != DEFAULT_LANGUAGE:
        text = _lookup(DEFAULT_LANGUAGE, key, n)
    if text is None:
        return key
    if values:
        try:
            return text.format(**values)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def is_valid_key(key: str) -> bool:
    return bool(_KEY_RE.match(key))


def maybe_t(value: str, **values) -> str:
    """``value`` 是中文表里的键就翻译，否则原样返回——给「既可能传文案键、也可能传现成文字」的参数用
    （例如文件对话框的过滤器：默认值是键，调用方也可以传自己拼好的过滤器）。"""
    text = str(value or "")
    if is_valid_key(text) and text in table(DEFAULT_LANGUAGE):
        return t(text, **values)
    return text
