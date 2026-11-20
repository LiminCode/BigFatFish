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
        "sources.suggestions": True, "prompt_zh": "", "prompt_en": "", "priority_rules": "", "extra_allowed_tools": []}
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


def test_toggles_and_choices_commit_at_once_and_text_and_lists_wait_for_the_user():
    for group in st.GROUPS:
        for setting in group.settings:
            expected = "on_finish" if setting.control in ("text", "long_text", "lines", "records") else "immediate"
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


# ───────────────────────── 数字的上下限（M4 起：Slack 关注的两个分钟数） ─────────────────────────

def test_slack_watch_is_declared_with_the_features_own_bounds_and_builtin_prompt():
    from pet import slack_watch as sw

    group = st.group("slack_watch")
    assert group.config_key == sw.CONFIG_KEY and group.zone == "work" and group.normalize is sw.normalize
    by_id = {s.id: s for s in group.settings}
    assert list(by_id) == ["enabled", "interval_minutes", "idle_minutes", "model", "effort", "prompt"]
    assert by_id["interval_minutes"].bounds == sw.INTERVAL_RANGE and by_id["idle_minutes"].bounds == sw.IDLE_RANGE
    assert by_id["interval_minutes"].unit and by_id["idle_minutes"].unit
    assert by_id["prompt"].disclosure == "advanced" and by_id["prompt"].builtin(sw.normalize({})) == sw.default_prompt_template()
    assert group.unavailable_text and group.available is not None


@pytest.mark.parametrize("language", ["zh", "en"])
def test_every_unit_has_its_text_in_both_languages(language):
    table = i18n.table(language)
    units = [s.unit for g in st.GROUPS for s in g.settings if s.unit]
    assert units and [key for key in units if not str(table.get(key) or "").strip()] == []


@pytest.mark.parametrize("value, code", [(4, "out_of_range"), (241, "out_of_range"), (7.5, "rejected"), ("15", "type")])
def test_a_number_outside_its_bounds_is_named_as_out_of_range(value, code):
    group = st.group("slack_watch")
    assert st.check_changes(group, {}, {"interval_minutes": value}) == (None, [{"id": "interval_minutes", "code": code}])
    final, errors = st.check_changes(group, {}, {"interval_minutes": 5, "idle_minutes": 240})
    assert errors == [] and final["interval_minutes"] == 5 and final["idle_minutes"] == 240


# ───────────────────────── 工作笔记（M4 第二项） ─────────────────────────

def test_work_notes_is_declared_with_both_prompts_and_the_features_own_normalize():
    from pet import work_notes as wn

    group = st.group("work_notes")
    assert group.config_key == wn.CONFIG_KEY and group.zone == "work" and group.normalize is wn.normalize
    by_id = {s.id: s for s in group.settings}
    assert list(by_id) == ["enabled", "repo_dir", "model", "effort", "prompt_zh", "prompt_en"]
    assert by_id["repo_dir"].control == "text" and by_id["model"].control == "choice_or_text"
    for language in ("zh", "en"):
        prompt = by_id[f"prompt_{language}"]
        assert prompt.disclosure == "advanced" and prompt.builtin(wn.normalize({})) == wn.default_prompt_template(language)
    assert group.unavailable_text == "notes.settings.no_wsl" and group.available is not None


def test_work_notes_writes_go_through_its_normalize():
    group = st.group("work_notes")
    final, errors = st.check_changes(group, {}, {"repo_dir": "  E:\\mem  ", "model": "claude-sonnet-5-5"})
    assert errors == [] and final["repo_dir"] == "E:\\mem" and final["model"] == "claude-sonnet-5-5"
    assert st.check_changes(group, {}, {"model": "bad model!"}) == (None, [{"id": "model", "code": "rejected"}])
    # 清空目录：功能会退回默认目录，写的时候不能悄悄这样做
    assert st.check_changes(group, {}, {"repo_dir": ""}) == (None, [{"id": "repo_dir", "code": "rejected"}])
    assert st.check_changes(group, {}, {"effort": "max"}) == (None, [{"id": "effort", "code": "not_a_choice"}])


# ───────────────────────── 个人助理（M4 第三项）：选项可以带显示文字 ─────────────────────────

def test_personal_is_declared_with_labelled_choices_for_following_chat():
    from pet import personal_vault as pv

    group = st.group("personal")
    assert group.config_key == pv.CONFIG_KEY and group.zone == "personal" and group.normalize is pv.normalize
    by_id = {s.id: s for s in group.settings}
    assert list(by_id) == ["enabled", "repo_dir", "time", "model", "effort"]
    assert by_id["time"].control == "choice_or_text" and by_id["time"].choices == pv.TIME_CHOICES
    assert by_id["model"].choices == ("", *pv.MODEL_CHOICES) and by_id["effort"].choices == ("", *pv.EFFORT_LEVELS)
    assert dict(by_id["model"].labels)[""] == "personal.settings.same_as_chat"
    assert set(dict(by_id["effort"].labels)) == {"", *pv.EFFORT_LEVELS}
    assert group.available is None                                          # 不靠 WSL，也不靠 git


def test_personal_writes_go_through_its_normalize():
    group = st.group("personal")
    final, errors = st.check_changes(group, {}, {"time": "21:00", "model": "", "effort": "max", "repo_dir": " E:\\AI-Base "})
    assert errors == [] and (final["time"], final["model"], final["effort"], final["repo_dir"]) == ("21:00", "", "max", "E:\\AI-Base")
    assert st.check_changes(group, {}, {"time": "25:00"}) == (None, [{"id": "time", "code": "rejected"}])
    assert st.check_changes(group, {}, {"model": "bad model!"}) == (None, [{"id": "model", "code": "rejected"}])
    assert st.check_changes(group, {}, {"effort": "huge"}) == (None, [{"id": "effort", "code": "not_a_choice"}])


@pytest.mark.parametrize("language", ["zh", "en"])
def test_every_choice_label_has_its_text_in_both_languages(language):
    table = i18n.table(language)
    keys = [key for g in st.GROUPS for s in g.settings for _value, key in s.labels]
    assert keys and [key for key in keys if not str(table.get(key) or "").strip()] == []


def test_validate_rejects_labels_that_cannot_work():
    group = st.group("personal")

    def broken(setting):
        settings = tuple(setting if s.id == setting.id else s for s in group.settings)
        with pytest.raises(ValueError):
            st.validate((st.Group(**{**{f: getattr(group, f) for f in group.__dataclass_fields__}, "settings": settings}),))

    broken(st.Setting("repo_dir", "text", labels=(("", "personal.settings.same_as_chat"),)))       # 只有下拉有选项文字
    broken(st.Setting("effort", "choice", choices=("", "low"), labels=(("max", "personal.settings.effort.max"),)))  # 不是可选值


def test_validate_rejects_bounds_that_cannot_work():
    group = st.group("slack_watch")

    def broken(setting):
        settings = tuple(setting if s.id == setting.id else s for s in group.settings)
        with pytest.raises(ValueError):
            st.validate((st.Group(**{**{f: getattr(group, f) for f in group.__dataclass_fields__}, "settings": settings}),))

    broken(st.Setting("enabled", "toggle", bounds=(0, 1)))                 # 只有数字有上下限
    broken(st.Setting("interval_minutes", "number", bounds=(240, 5)))       # 下限比上限大
    broken(st.Setting("interval_minutes", "number", bounds=(30, 60)))       # 默认的 15 不在范围里
    broken(st.Setting("interval_minutes", "number", bounds=(5,)))


def test_module_does_not_import_qt():
    """设置表要被本机服务的请求线程、以后的同步器、测试直接用：它和它带进来的模块都不能把 Qt 拉起来。"""
    tree = ast.parse(Path(st.__file__).read_text(encoding="utf-8"))
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert "PySide6" not in imported
    probe = "import sys, pet.settings_table; print(any(m.startswith('PySide6') for m in sys.modules))"
    done = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, cwd=Path(st.__file__).resolve().parents[1])
    assert done.returncode == 0 and done.stdout.strip() == "False", done.stderr[-400:]


# ───────────────────────── 会话记忆蒸馏（M4 第四项）：一个配置键、两组，外加「一行一个」的列表 ─────────────────────────

def test_memory_distill_is_two_groups_on_one_config_key():
    from pet import memory_distill as md

    personal, work = st.group("distill_personal"), st.group("distill_work")
    assert personal.config_key == work.config_key == md.CONFIG_KEY and personal.normalize is work.normalize is md.normalize
    assert (personal.zone, work.zone) == ("personal", "work")
    mine = {s.id: s for s in personal.settings}
    theirs = {s.id: s for s in work.settings}
    assert list(mine) == ["enabled", "scan_wsl", "keep_days", "work_roots", "daily_at", "model", "effort", "mirror_to_vault",
                          "prompt_zh", "prompt_en"]
    assert list(theirs) == ["work_distill", "work_daily_at", "work_model", "work_effort", "work_mirror_to_vault",
                            "work_prompt_zh", "work_prompt_en"]
    assert not set(mine) & set(theirs), "一项设置只有一个编辑入口"
    assert set(personal.not_editable) == set(theirs) and set(work.not_editable) == set(mine), "另一组的键写明去哪改"
    assert mine["work_roots"].control == "lines" and mine["keep_days"].bounds == (1, 3650)
    assert mine["model"].choices == ("", *md.MODEL_CHOICES) and dict(mine["model"].labels)[""] == "distill.settings.same_as_chat"
    assert theirs["work_model"].choices == md.WORK_MODEL_CHOICES
    for language in ("zh", "en"):
        assert mine[f"prompt_{language}"].builtin(md.normalize({})) == md.default_prompt_template(language)
        assert theirs[f"work_prompt_{language}"].builtin(md.normalize({})) == md.default_prompt_template(language)
    assert personal.available is None, "抽取和个人侧蒸馏不靠 WSL"
    assert work.available is not None and work.unavailable_text == "distill.settings.work_no_wsl"


def test_memory_distill_writes_go_through_its_normalize_and_leave_the_other_side_alone():
    personal, work = st.group("distill_personal"), st.group("distill_work")
    raw = {"work_model": "opus", "work_daily_at": "22:00", "keep_days": 60}
    final, errors = st.check_changes(personal, raw, {"keep_days": 180, "model": "", "work_roots": [" F:\Only ", "", "E:\Corp"]})
    assert errors == [] and final["keep_days"] == 180 and final["work_roots"] == ["F:\Only", "E:\Corp"]
    assert (final["work_model"], final["work_daily_at"]) == ("opus", "22:00"), "改个人侧不碰公司侧"
    final, errors = st.check_changes(work, raw, {"work_model": "haiku", "work_effort": "low"})
    assert errors == [] and final["keep_days"] == 60 and final["work_model"] == "haiku"
    assert st.check_changes(personal, {}, {"keep_days": 0}) == (None, [{"id": "keep_days", "code": "out_of_range"}])
    assert st.check_changes(personal, {}, {"keep_days": 90.5}) == (None, [{"id": "keep_days", "code": "rejected"}])
    assert st.check_changes(personal, {}, {"work_roots": "D:\Corp"}) == (None, [{"id": "work_roots", "code": "type"}])
    assert st.check_changes(personal, {}, {"work_roots": ["D:\Corp", 3]}) == (None, [{"id": "work_roots", "code": "type"}])
    # 一行都不剩：功能会退回默认目录，写的时候不能悄悄这样做
    assert st.check_changes(personal, {}, {"work_roots": [" ", ""]}) == (None, [{"id": "work_roots", "code": "rejected"}])
    assert st.check_changes(personal, {}, {"model": "bad model!"}) == (None, [{"id": "model", "code": "rejected"}])
    assert st.check_changes(work, {}, {"work_model": "a b; c"}) == (None, [{"id": "work_model", "code": "rejected"}])
    assert st.check_changes(work, {}, {"enabled": True}) == (None, [{"id": "enabled", "code": "unknown"}]), "总开关在个人侧那一组"


def test_a_list_of_lines_is_its_own_control():
    group = st.group("distill_personal")
    lines = next(s for s in group.settings if s.id == "work_roots")
    assert "lines" in st.CONTROLS and lines.commit_policy == "on_finish", "一行一行打完再存"
    with pytest.raises(ValueError):                                       # 默认值是一串字，装不进列表
        st.validate((_group(settings=(st.Setting("time", "lines"),)),))
    with pytest.raises(ValueError):                                       # 默认值是列表，单行文本装不下
        st.validate((st.Group(**{**{f: getattr(group, f) for f in group.__dataclass_fields__},
                                 "settings": (st.Setting("work_roots", "text"),), "not_editable": {}}),))


# ───────────────────────── Claude Code 联动 / 会话小鱼 / 最近的对话（M4 第六项）：一个配置键、四组 ─────────────────────────

_AGENT_LINK_GROUPS = {"link_win": ("claude", "cursor", "opencode", "custom_agents"), "link_wsl": ("claude_wsl",),
                      "session_fish": ("session_pets", "session_pets_max", "session_fish_keep_days", "crown_models",
                                       "session_card_theme", "session_card_text_size"),
                      "session_history": ("session_history", "session_history_rows", "session_history_days", "session_history_max")}


def test_agent_link_is_four_groups_on_one_config_key():
    """按配置全景的账号带和磁贴分：本机联动、WSL 联动（公司带、要有 WSL）、会话小鱼、最近的对话。读写都走 config 的清洗函数。"""
    from pet import claude_hooks
    from pet.config import _clean_agent_link_data

    groups = {g.id: g for g in st.GROUPS if g.config_key == "agent_link"}
    assert set(groups) == set(_AGENT_LINK_GROUPS)
    for group_id, ids in _AGENT_LINK_GROUPS.items():
        assert [s.id for s in groups[group_id].settings] == list(ids), group_id
        for raw in ({}, {"claude": False, "session_pets_max": 99, "crown_models": ["Opus"], "extra": 1}):
            assert groups[group_id].normalize(raw) == _clean_agent_link_data(raw), "读写都走 config 的清洗（惰性导入，模块本身不带 Qt）"
    assert groups["link_wsl"].zone == "work" and groups["link_wsl"].available is not None and groups["link_wsl"].unavailable_text
    assert {groups[g].zone for g in ("link_win", "session_fish", "session_history")} == {"personal"}
    assert groups["link_wsl"].available() == bool(claude_hooks.wsl_exe())
    # 每个键恰好在一组里能改，另外三组写明去哪改；dsh / 音效在四组里都只说明不给改（自定义 Agent 2026-11-20 起在 link_win 里改）
    produced = set(st.flatten(_clean_agent_link_data({})))
    declared = {s.id for g in groups.values() for s in g.settings}
    assert declared <= produced and len(declared) == sum(len(g.settings) for g in groups.values())
    for g in groups.values():
        assert set(g.not_editable) == produced - {s.id for s in g.settings}, g.id
    for key in ("dsh", "sound_enabled", "sound_volume", "sound_start_path"):
        assert all(key in g.not_editable for g in groups.values()), key
    custom = next(s for s in groups["link_win"].settings if s.id == "custom_agents")
    assert custom.control == "records" and [name for name, _key in custom.fields] == ["key", "name", "path"]
    assert custom.commit_policy == "on_finish" and custom.disclosure == "advanced"


def test_records_is_its_own_control_and_needs_its_fields():
    """第八种控件：几列文本、一行一条。声明必须带 fields，别的控件不能带。"""
    assert "records" in st.CONTROLS
    rows = st.Setting("custom_agents", "records", fields=(("key", "k"), ("path", "p")))
    assert rows.commit_policy == "on_finish" and st._fits("records", []) and not st._fits("records", "x")
    with pytest.raises(ValueError, match="records need fields"):
        st.validate((_group(settings=(st.Setting("work_roots", "records"),)),))
    with pytest.raises(ValueError, match="only records have them"):
        st.validate((_group(settings=(st.Setting("work_roots", "lines", fields=(("a", "k"),)),)),))


def test_session_fish_declares_the_features_own_bounds_choices_and_labels():
    from pet import session_card_themes as themes
    from pet.config import SESSION_PETS_MAX_CAP

    fish = {s.id: s for s in st.group("session_fish").settings}
    assert fish["session_pets_max"].bounds == (1, SESSION_PETS_MAX_CAP) and fish["session_pets_max"].unit
    assert fish["session_fish_keep_days"].bounds == (1, 30) and fish["session_fish_keep_days"].unit == "settings.unit.days"
    assert fish["crown_models"].control == "lines"
    assert fish["session_card_theme"].control == "choice" and fish["session_card_theme"].choices == tuple(themes.CARD_THEMES)
    assert dict(fish["session_card_theme"].labels) == {theme_id: f"menu.card_theme.{theme_id}" for theme_id in themes.CARD_THEMES}
    assert fish["session_card_text_size"].control == "choice" and fish["session_card_text_size"].choices == themes.TEXT_SIZES
    assert [key for key, _text in fish["session_card_text_size"].labels] == list(themes.TEXT_SIZES), "整数下拉也配文字"
    history = {s.id: s for s in st.group("session_history").settings}
    assert history["session_history_rows"].bounds == (3, 20) and history["session_history_days"].bounds == (1, 30)
    assert history["session_history_max"].bounds == (1, 200)
    assert all(history[k].unit for k in ("session_history_rows", "session_history_days", "session_history_max"))


def test_agent_link_writes_go_through_the_config_cleaner_and_leave_the_other_groups_alone():
    fish, wsl = st.group("session_fish"), st.group("link_wsl")
    raw = {"claude": True, "claude_wsl": True, "crown_models": ["fable"], "session_card_text_size": 100}
    new, errors = st.check_changes(fish, raw, {"session_card_text_size": 115, "crown_models": ["opus", " haiku "]})
    assert errors == [] and new["session_card_text_size"] == 115 and new["crown_models"] == ["opus", "haiku"]
    assert new["claude"] is True and new["claude_wsl"] is True, "别的组的键原样留着"
    assert st.check_changes(fish, raw, {"session_card_text_size": "115"})[1] == [{"id": "session_card_text_size", "code": "not_a_choice"}]
    assert st.check_changes(fish, raw, {"crown_models": ["Fable"]})[1] == [{"id": "crown_models", "code": "rejected"}], "清洗会改成小写：拒"
    assert st.check_changes(fish, raw, {"session_pets_max": 41})[1] == [{"id": "session_pets_max", "code": "out_of_range"}]
    assert st.check_changes(st.group("session_history"), raw, {"session_history_max": 500})[1] == \
        [{"id": "session_history_max", "code": "out_of_range"}]
    new, errors = st.check_changes(wsl, raw, {"claude_wsl": False})
    assert errors == [] and new["claude_wsl"] is False and new["claude"] is True
    assert st.check_changes(wsl, raw, {"claude": False})[1] == [{"id": "claude", "code": "unknown"}], "本机那条在另一组"
