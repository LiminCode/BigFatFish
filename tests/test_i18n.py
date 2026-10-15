# -*- coding: utf-8 -*-
"""界面文字的查表层（方案 B：英文标识符做键，中英两张表）。

守住的：两张表的键一致（英文允许用 ``.one`` / ``.other`` 代替一个键）；代码里用到的键都在
中文表里；缺翻译退回中文而不是键名；``ui_language`` 由 Config 加载 / 重载时设置。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from pet import i18n
from pet.config import Config

PET = Path(i18n.__file__).parent


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


def test_languages_normalise_and_default_to_chinese():
    assert i18n.normalize_language("en") == "en" and i18n.normalize_language(" EN ") == "en"
    for bad in ("", None, "fr", "zh-CN", 3):
        assert i18n.normalize_language(bad) == "zh"
    assert i18n.set_language("fr") == "zh" and i18n.current_language() == "zh"


def test_lookup_formats_placeholders_and_picks_plural_forms():
    i18n.set_language("zh")
    assert i18n.t("ago.minutes", n=11) == "11 分钟前"
    assert i18n.t("ago.minutes", n=1) == "1 分钟前", "中文没有单复数：一个键"
    i18n.set_language("en")
    assert i18n.t("ago.minutes", n=1) == "1 min ago"
    assert i18n.t("ago.minutes", n=11) == "11 min ago"
    assert i18n.t("history.result.resumed", label="web") == "Resumed in terminal: web"


def test_missing_english_falls_back_to_chinese_then_to_the_key(monkeypatch):
    i18n.set_language("en")
    monkeypatch.setitem(i18n.table("en"), "island.card.chat", None) if False else None
    en = dict(i18n.table("en"))
    en.pop("island.card.chat")
    monkeypatch.setitem(i18n._tables, "en", en)
    assert i18n.t("island.card.chat") == "聊天"
    assert i18n.t("no.such.key") == "no.such.key"
    assert i18n.t("ago.minutes", n=3, bogus=1) == "3 min ago", "多余的占位值不碍事"


def test_the_two_tables_cover_the_same_keys():
    zh, en = i18n.table("zh"), i18n.table("en")
    assert zh and en
    plural = {k.rsplit(".", 1)[0] for k in en if k.endswith((".one", ".other"))}
    for key in plural:
        assert f"{key}.one" in en and f"{key}.other" in en, f"英文复数要成对：{key}"
    missing_en = [k for k in zh if k not in en and k not in plural]
    extra_en = [k for k in en if k not in zh and k.rsplit(".", 1)[0] not in zh]
    assert missing_en == [], f"英文表缺：{missing_en}"
    assert extra_en == [], f"英文表多出：{extra_en}"
    bad = [k for k in list(zh) + list(en) if not i18n.is_valid_key(k)]
    assert bad == [], f"键名不合规（小写、点分、下划线）：{bad}"
    assert all(v.strip() for v in list(zh.values()) + list(en.values())), "没有空文案"


def test_every_key_used_in_code_exists_in_the_chinese_table():
    zh = i18n.table("zh")
    used = set()
    for path in PET.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        used.update(re.findall(r"\bt\(\s*\"([a-z0-9_.]+)\"", text))
    assert used, "代码里应该有 t(\"…\") 调用"
    missing = sorted(k for k in used if k not in zh)
    assert missing == [], f"代码里用了表里没有的键：{missing}"


def test_dynamic_phase_keys_exist():
    for phase in ("working", "waiting", "review", "resting"):
        for prefix in ("session.phase", "session.capsule", "session.count"):
            assert i18n.t(f"{prefix}.{phase}", n=2) != f"{prefix}.{phase}"


def test_config_sets_the_language_on_load_and_reload(tmp_path):
    config = Config(tmp_path)
    assert config.get("ui_language") == "zh" and i18n.current_language() == "zh"
    config.set("ui_language", "en")
    config.save()
    assert i18n.current_language() == "en", "set 之后立刻生效（进程内保存走这条路）"

    i18n.set_language("zh")
    other = Config(tmp_path)
    assert other.get("ui_language") == "en" and i18n.current_language() == "en", "从磁盘加载时设置"

    i18n.set_language("zh")
    other.reload()
    assert i18n.current_language() == "en", "外部改了配置、重载时也设置（设置窗口是另一个进程）"

    config.set("ui_language", "klingon")
    config.save()
    assert Config(tmp_path).get("ui_language") == "zh"
