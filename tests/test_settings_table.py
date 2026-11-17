# -*- coding: utf-8 -*-
"""设置表（ADR 0014）：每一项设置声明一次——在哪个组、用什么控件、能取什么值、什么时候算存上。

三类守卫：
1. 表自己站得住——标识唯一、取值合法、依赖指得到、默认值和控件对得上；
2. 表和功能对得上——功能的 ``normalize`` 给出的每个键，要么在表里声明了，要么写明为什么不给改；
   表里的每个可选值过一遍 ``normalize`` 都不变（不然页面上选了它，存下去的却是别的）；
3. 每一项在两张字表里都有名字。
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from pet import i18n
from pet import settings_table as st
from pet import work_briefing as wb


def _group(**changes) -> st.Group:
    base = st.GROUPS[0]
    return st.Group(**{**{f: getattr(base, f) for f in base.__dataclass_fields__}, **changes})


def test_table_is_internally_consistent():
    st.validate()
    ids = [group.id for group in st.GROUPS]
    assert len(ids) == len(set(ids))
    for group in st.GROUPS:
        assert group.zone in st.ZONES and group.settings and callable(group.normalize)
        for setting in group.settings:
            assert setting.control in st.CONTROLS and setting.commit_policy in st.COMMITS and setting.disclosure in st.DISCLOSURES


def test_validate_rejects_the_mistakes_it_exists_to_catch():
    good = st.GROUPS[0]
    first = good.settings[0]

    def broken(*settings, **changes):
        with pytest.raises(ValueError):
            st.validate((_group(settings=settings or good.settings, **changes),))

    broken(st.Setting("enabled", "slider"))                               # 没有这种控件
    broken(st.Setting("enabled", "toggle", commit="whenever"))
    broken(st.Setting("enabled", "toggle", disclosure="secret"))
    broken(st.Setting("time", "choice"))                                  # 下拉却没有可选值
    broken(first, first)                                                  # 同一项声明了两次
    broken(st.Setting("no_such_key", "toggle"))                           # 功能里根本没有这个键
    broken(first, st.Setting("time", "choice_or_text", choices=wb.TIME_CHOICES, depends_on="nowhere"))
    broken(first, st.Setting("time", "choice_or_text", choices=wb.TIME_CHOICES, depends_on="model"))   # 只能依赖一个开关
    broken(st.Setting("time", "toggle"))                                  # 默认值是字符串，开关装不下
    broken(st.Setting("enabled", "long_text"))
    broken(zone="neither")
    broken(config_key="")
    with pytest.raises(ValueError):
        st.validate((good, good))                                         # 组的标识重复


def test_every_key_a_feature_reads_is_declared_or_explained():
    """功能加了一个设置项却没登记：页面上改不了它，而且没人知道。这条会点名。"""
    for group in st.GROUPS:
        produced = set(st.flatten(group.normalize({})))
        declared = {setting.id for setting in group.settings}
        assert declared <= produced, f"{group.id}: 表里声明了功能不认识的键 {sorted(declared - produced)}"
        missing = produced - declared - set(group.not_editable)
        assert not missing, (f"{group.id}: 这些键既没在 pet/settings_table.py 里声明，也没写进 not_editable 说明为什么不给改："
                             f"{sorted(missing)}")
        assert all(reason.strip() for reason in group.not_editable.values())
        assert set(group.not_editable) <= produced, f"{group.id}: not_editable 里有功能已经不产出的键"


def test_every_choice_survives_the_features_own_normalisation():
    """页面上选得到的每个值，存下去再读回来必须还是它。"""
    for group in st.GROUPS:
        for setting in group.settings:
            for choice in setting.choices:
                stored = st.get_path(group.normalize(st.set_path(group.normalize({}), setting.id, choice)), setting.id)
                assert stored == choice, f"{group.id}.{setting.id}: 选 {choice!r} 存下去变成了 {stored!r}"
            if setting.control == "choice":
                assert st.defaults(group)[setting.id] in setting.choices, f"{group.id}.{setting.id}: 默认值不在可选值里"


def test_defaults_are_what_the_feature_gives_for_an_empty_config():
    group = st.group("work_briefing")
    assert st.defaults(group) == {
        "enabled": False, "time": "09:00", "weekdays_only": True, "model": "sonnet", "effort": "high",
        "sources.jira": True, "sources.pr": True, "sources.slack": True, "sources.calendar": True, "sources.email": False,
        "sources.suggestions": True, "prompt_zh": "", "prompt_en": "", "priority_rules": ""}
    assert list(st.defaults(group)) == [setting.id for setting in group.settings]          # 顺序就是表里声明的顺序


def test_values_read_through_the_features_normalisation_not_the_raw_config():
    group = st.group("work_briefing")
    raw = {"enabled": True, "time": "25:99", "model": "has spaces", "sources": {"email": True, "bogus": True}, "extra": 1}
    values = st.values(group, raw)
    assert values["enabled"] is True and values["time"] == "09:00" and values["model"] == "sonnet"       # 不合法的读出来是默认
    assert values["sources.email"] is True and values["sources.jira"] is True and "sources.bogus" not in values
    assert st.values(group, None) == st.defaults(group) and st.values(group, "garbage") == st.defaults(group)


def test_paths_reach_into_nested_dictionaries_without_touching_the_original():
    data = {"a": 1, "b": {"c": 2}}
    assert st.flatten(data) == {"a": 1, "b.c": 2}
    assert st.get_path(data, "b.c") == 2 and st.get_path(data, "b.missing", "x") == "x"
    changed = st.set_path(data, "b.c", 3)
    assert changed == {"a": 1, "b": {"c": 3}} and data == {"a": 1, "b": {"c": 2}}
    assert st.set_path({}, "x.y", 1) == {"x": {"y": 1}}


def test_version_is_a_fingerprint_of_the_effective_values():
    group = st.group("work_briefing")
    base = st.version(group, {})
    assert base == st.version(group, None) == st.version(group, {"time": "09:00", "unknown_key": "ignored"})   # 生效值一样 → 版本一样
    assert st.version(group, {"time": "09:30"}) != base
    assert st.version(group, {"sources": {"email": True}}) != base
    assert len(base) == 16 and all(c in "0123456789abcdef" for c in base)


def test_a_long_text_knows_what_is_used_when_it_is_left_empty():
    group = st.group("work_briefing")
    prompt = next(s for s in group.settings if s.id == "prompt_zh")
    assert prompt.control == "long_text" and prompt.commit_policy == "on_finish" and prompt.disclosure == "advanced"
    off = wb.normalize({"sources": {"jira": False}})
    assert prompt.builtin(wb.normalize({})) == wb.default_prompt_template("zh", wb.DEFAULT_SOURCES)
    assert prompt.builtin(off) == wb.default_prompt_template("zh", off["sources"]) != prompt.builtin(wb.normalize({}))
    assert next(s for s in group.settings if s.id == "priority_rules").builtin is None


def test_toggles_and_choices_commit_at_once_and_text_waits_for_the_user():
    for group in st.GROUPS:
        for setting in group.settings:
            expected = "on_finish" if setting.control in ("text", "long_text") else "immediate"
            if not setting.commit:
                assert setting.commit_policy == expected, f"{group.id}.{setting.id}"


def test_availability_is_asked_each_time_and_a_group_without_a_condition_is_always_available():
    group = st.group("work_briefing")
    assert st.is_available(_group(available=lambda: False)) is False
    assert st.is_available(_group(available=None)) is True
    assert st.is_available(_group(available=lambda: 1 / 0)) is False                     # 条件自己出错：按不可用算，不抛给调用方
    assert isinstance(st.is_available(group), bool) and group.unavailable_text


@pytest.mark.parametrize("language", ["zh", "en"])
def test_every_group_and_setting_has_its_text_in_both_languages(language):
    table = i18n.table(language)
    missing = []
    for group in st.GROUPS:
        for key in (group.title_key, group.unavailable_text if group.available else None):
            if key and not str(table.get(key) or "").strip():
                missing.append(key)
        for setting in group.settings:
            if not str(table.get(st.title_key(group, setting)) or "").strip():
                missing.append(st.title_key(group, setting))
            hint = st.hint_key(group, setting)
            if hint in i18n.table("zh") or hint in i18n.table("en"):          # 说明可以没有；有就两边都得有
                if not str(table.get(hint) or "").strip():
                    missing.append(hint)
    assert missing == []


def test_group_lookup():
    assert st.group("work_briefing") is st.GROUPS[0]
    with pytest.raises(KeyError):
        st.group("no-such-group")


def test_module_does_not_import_qt():
    """设置表要被本机服务的请求线程、以后的同步器、测试直接用：它和它带进来的模块都不能把 Qt 拉起来。"""
    tree = ast.parse(Path(st.__file__).read_text(encoding="utf-8"))
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert "PySide6" not in imported
    probe = "import sys, pet.settings_table; print(any(m.startswith('PySide6') for m in sys.modules))"
    done = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, cwd=Path(st.__file__).resolve().parents[1])
    assert done.returncode == 0 and done.stdout.strip() == "False", done.stderr[-400:]
