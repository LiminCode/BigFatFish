# -*- coding: utf-8 -*-
"""设置的写入链路（ADR 0014）：页面提交一次改动，到它落进 config.json 之间的每一道检查。

三层各测各的：
1. ``settings_table.check_changes``——纯函数：哪一项、什么类型、功能自己的校验认不认；
2. ``settings_audit.AuditLog``——每次写入记一行；
3. ``panorama.settings_api``——拿真的 ``Config``（临时目录）：先重读、对版本、要么全存要么全不存、存不上就退回。

经本机服务和界面线程的整条路在 ``tests/test_panorama_settings_routes.py``。
"""
from __future__ import annotations

import json

import pytest

from pet import i18n
from pet import settings_audit
from pet import settings_table as st
from pet import work_briefing as wb
from pet.config import Config
from pet.panorama import settings_api as api

GROUP = st.group("work_briefing")


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    i18n.set_language("zh")
    monkeypatch.setattr(st.claude_hooks, "wsl_exe", lambda: "wsl.exe")     # 这一组要 WSL 才可用；测试机上当它有
    yield
    i18n.set_language("zh")


# ───────────────────────── 1. 校验一次改动 ─────────────────────────

def _check(changes, raw=None):
    return st.check_changes(GROUP, raw if raw is not None else {}, changes)


def test_good_changes_come_back_as_the_whole_group_normalised():
    new, errors = _check({"enabled": True, "time": "09:30", "sources.email": True})
    assert errors == [] and new == wb.normalize({"enabled": True, "time": "09:30", "sources": {"email": True}})
    assert new["sources"]["jira"] is True and new["model"] == "sonnet"                 # 没提到的项保持原样


@pytest.mark.parametrize("changes, setting, code", [
    ({"no_such": 1}, "no_such", "unknown"),
    ({"sources": {"jira": False}}, "sources", "unknown"),                 # 只能逐项改，不能整块换掉一层
    ({"enabled": "yes"}, "enabled", "type"),
    ({"enabled": 1}, "enabled", "type"),
    ({"time": 9}, "time", "type"),
    ({"prompt_zh": None}, "prompt_zh", "type"),
    ({"effort": "ultra"}, "effort", "not_a_choice"),
    ({"effort": "HIGH"}, "effort", "not_a_choice"),
    ({"time": "25:99"}, "time", "rejected"),                              # 功能自己的校验会把它悄悄换成 09:00
    ({"time": "9"}, "time", "rejected"),                                  # 会被改写成 09:00：要页面给规范的写法
    ({"model": "has spaces"}, "model", "rejected"),                       # 模型名会拼进 shell 命令
    ({"model": "sonnet; rm -rf ~"}, "model", "rejected"),
    ({"model": ""}, "model", "rejected"),
])
def test_a_change_the_table_or_the_feature_does_not_accept_is_named(changes, setting, code):
    new, errors = _check(changes)
    assert new is None and [(e["id"], e["code"]) for e in errors] == [(setting, code)]


def test_one_bad_change_rejects_the_whole_request():
    new, errors = _check({"enabled": True, "effort": "ultra", "time": "09:30", "model": "bad name"})
    assert new is None and {e["id"] for e in errors} == {"effort", "model"}


def test_text_is_trimmed_but_otherwise_kept_exactly():
    new, errors = _check({"priority_rules": "  QA 报的 bug 一律 ★★★\n第二行\n\n"})
    assert errors == [] and new["priority_rules"] == "QA 报的 bug 一律 ★★★\n第二行"
    assert _check({"prompt_zh": ""})[0]["prompt_zh"] == ""                              # 空 = 用内置


def test_custom_values_the_feature_accepts_are_fine_even_if_not_in_the_dropdown():
    new, errors = _check({"time": "07:05", "model": "claude-sonnet-5-5"})
    assert errors == [] and (new["time"], new["model"]) == ("07:05", "claude-sonnet-5-5")


@pytest.mark.parametrize("changes", [{}, None, [], "x", {"": True}])
def test_an_empty_or_malformed_set_of_changes_is_refused(changes):
    new, errors = _check(changes)
    assert new is None and errors


# ───────────────────────── 2. 审计记录 ─────────────────────────

def _entry(setting="time", old="09:00", new="09:30"):
    return {"group": "work_briefing", "setting": setting, "old": old, "new": new, "source": "page"}


def test_audit_appends_one_line_per_change_and_reads_newest_first(tmp_path):
    log = settings_audit.AuditLog(tmp_path / "settings-audit.jsonl", clock=lambda: "2026-01-02 03:04:05")
    log.append([_entry(), _entry("enabled", False, True)])
    log.append([_entry("effort", "high", "low")])
    rows = log.read()
    assert [r["setting"] for r in rows] == ["effort", "enabled", "time"]
    assert rows[0] == {"at": "2026-01-02 03:04:05", "group": "work_briefing", "setting": "effort", "old": "high", "new": "low", "source": "page"}
    assert len((tmp_path / "settings-audit.jsonl").read_text(encoding="utf-8").splitlines()) == 3
    assert [r["setting"] for r in log.read(limit=2)] == ["effort", "enabled"]


def test_audit_keeps_only_the_most_recent_entries(tmp_path):
    log = settings_audit.AuditLog(tmp_path / "a.jsonl", limit=5, clock=lambda: "t")
    for i in range(12):
        log.append([_entry(new=f"0{i % 10}:00")])
    rows = log.read()
    assert len(rows) == 5 and rows[0]["new"] == "01:00" and rows[-1]["new"] == "07:00"
    assert len((tmp_path / "a.jsonl").read_text(encoding="utf-8").splitlines()) == 5


def test_audit_cuts_a_very_long_value_and_says_so(tmp_path):
    log = settings_audit.AuditLog(tmp_path / "a.jsonl", clock=lambda: "t")
    log.append([_entry("prompt_zh", "", "字" * (settings_audit.VALUE_LIMIT + 50))])
    row = log.read()[0]
    assert len(row["new"]) == settings_audit.VALUE_LIMIT and row["truncated"] == ["new"] and row["old"] == ""


def test_audit_survives_a_missing_file_and_broken_lines(tmp_path):
    path = tmp_path / "a.jsonl"
    log = settings_audit.AuditLog(path, clock=lambda: "t")
    assert log.read() == []
    path.write_text('{"setting": "ok"}\n{broken\n\n[1, 2]\n', encoding="utf-8")
    assert [r["setting"] for r in log.read()] == ["ok"]
    log.append([_entry()])
    assert [r["setting"] for r in log.read()] == ["time", "ok"]


def test_audit_failure_to_write_is_reported_not_raised(tmp_path):
    log = settings_audit.AuditLog(tmp_path / "no-such-dir" / "deeper" / "a.jsonl", clock=lambda: "t")
    assert log.append([_entry()]) is True                                  # 目录没有就建
    blocked = tmp_path / "is-a-dir.jsonl"
    blocked.mkdir()
    assert settings_audit.AuditLog(blocked, clock=lambda: "t").append([_entry()]) is False


# ───────────────────────── 3. 读写一组设置：真的 Config ─────────────────────────

@pytest.fixture
def env(tmp_path):
    config = Config(base=tmp_path)
    config.set("work_briefing", wb.normalize({"enabled": False, "time": "09:00"}))
    config.set("on_top", False)
    assert config.save()
    audit = settings_audit.AuditLog(config.dir / "settings-audit.jsonl", clock=lambda: "2026-01-02 03:04:05")
    return config, audit


def _disk(config) -> dict:
    return json.loads(config.path.read_text(encoding="utf-8"))


def _write(env, changes, base=None):
    config, audit = env
    base = base if base is not None else api.read(config, "work_briefing")["version"]
    return api.write(config, "work_briefing", {"base": base, "changes": changes}, audit=audit)


def test_read_describes_every_setting_with_its_text_value_and_control(env):
    out = api.read(env[0], "work_briefing")
    assert out["group"] == "work_briefing" and out["title"] == "工作简报" and out["zone"] == "work"
    assert out["available"] is True and out["unavailable"] == "" and len(out["version"]) == 16
    rows = {row["id"]: row for row in out["settings"]}
    assert list(rows) == [s.id for s in GROUP.settings]
    assert rows["enabled"] == {"id": "enabled", "control": "toggle", "title": "工作日自动生成", "hint": rows["enabled"]["hint"],
                               "value": False, "default": False, "choices": [], "commit": "immediate", "disclosure": "primary",
                               "depends_on": "", "builtin": None}
    assert rows["effort"]["choices"] == ["low", "medium", "high", "xhigh"] and rows["time"]["control"] == "choice_or_text"
    assert rows["prompt_zh"]["commit"] == "on_finish" and rows["prompt_zh"]["builtin"] == wb.default_prompt_template("zh", wb.DEFAULT_SOURCES)
    assert rows["priority_rules"]["builtin"] is None and rows["enabled"]["hint"]


def test_read_says_when_the_group_cannot_work_on_this_machine(env, monkeypatch):
    monkeypatch.setattr(st.claude_hooks, "wsl_exe", lambda: "")
    out = api.read(env[0], "work_briefing")
    assert out["available"] is False and "WSL" in out["unavailable"]


def test_a_write_lands_on_disk_leaves_other_keys_alone_and_is_audited(env):
    config, audit = env
    out = _write(env, {"enabled": True, "time": "09:30"})
    assert out["changed"] == ["enabled", "time"]
    saved = _disk(config)
    assert saved["work_briefing"]["enabled"] is True and saved["work_briefing"]["time"] == "09:30" and saved["on_top"] is False
    assert {row["id"]: row["value"] for row in out["settings"]}["time"] == "09:30"
    assert out["version"] == api.read(config, "work_briefing")["version"] != ""
    assert [(r["setting"], r["old"], r["new"], r["source"]) for r in audit.read()] == [
        ("time", "09:00", "09:30", "page"), ("enabled", False, True, "page")]


def test_a_write_with_a_stale_version_is_refused_and_hands_back_the_current_values(env):
    config, audit = env
    stale = api.read(config, "work_briefing")["version"]
    _write(env, {"time": "09:30"})
    before = config.path.read_bytes()
    with pytest.raises(api.SettingsError) as caught:
        _write(env, {"time": "10:00"}, base=stale)
    assert (caught.value.status, caught.value.code) == (409, "stale")
    assert {r["id"]: r["value"] for r in caught.value.detail["current"]["settings"]}["time"] == "09:30"
    assert config.path.read_bytes() == before and len(audit.read()) == 1


def test_an_invalid_write_changes_nothing_on_disk_or_in_memory(env):
    config, audit = env
    before = config.path.read_bytes()
    with pytest.raises(api.SettingsError) as caught:
        _write(env, {"enabled": True, "model": "sonnet; rm -rf ~"})
    assert (caught.value.status, caught.value.code) == (422, "invalid")
    assert [(e["id"], e["code"]) for e in caught.value.detail["errors"]] == [("model", "rejected")]
    assert config.path.read_bytes() == before and config.get("work_briefing")["enabled"] is False and audit.read() == []


def test_a_write_first_absorbs_what_another_process_saved(env):
    """设置进程刚存了别的键，主进程内存里还是旧的：这时页面来写，不能把那边的改动盖掉。"""
    config, _audit = env
    other = Config(base=config.dir.parent)                               # 另一个进程里的 Config
    other.set("on_top", True)
    assert other.save()
    assert config.get("on_top") is False                                 # 主进程还没重读
    _write(env, {"time": "09:30"})
    saved = _disk(config)
    assert saved["on_top"] is True and saved["work_briefing"]["time"] == "09:30"


def test_another_process_changing_the_same_group_makes_the_page_version_stale(env):
    config, _audit = env
    seen = api.read(config, "work_briefing")["version"]
    other = Config(base=config.dir.parent)
    other.set("work_briefing", wb.normalize({"time": "08:00"}))
    assert other.save()
    with pytest.raises(api.SettingsError) as caught:
        _write(env, {"effort": "low"}, base=seen)
    assert caught.value.code == "stale" and _disk(config)["work_briefing"]["time"] == "08:00"


def test_when_the_file_cannot_be_saved_memory_goes_back_and_nothing_is_audited(env, monkeypatch):
    config, audit = env
    monkeypatch.setattr(config, "save", lambda: False)
    with pytest.raises(api.SettingsError) as caught:
        _write(env, {"time": "09:30"})
    assert (caught.value.status, caught.value.code) == (500, "save_failed")
    assert config.get("work_briefing")["time"] == "09:00" and audit.read() == []


def test_writing_the_values_that_are_already_there_saves_nothing(env):
    config, audit = env
    before = config.path.stat().st_mtime_ns
    out = _write(env, {"time": "09:00", "enabled": False})
    assert out["changed"] == [] and config.path.stat().st_mtime_ns == before and audit.read() == []


def test_a_group_that_cannot_work_here_refuses_writes(env, monkeypatch):
    monkeypatch.setattr(st.claude_hooks, "wsl_exe", lambda: "")
    with pytest.raises(api.SettingsError) as caught:
        _write(env, {"enabled": True})
    assert (caught.value.status, caught.value.code) == (409, "unavailable")


@pytest.mark.parametrize("body", [None, [], "x", {}, {"changes": {"time": "09:30"}}, {"base": "x"}, {"base": 1, "changes": {"time": "09:30"}},
                                  {"base": "x", "changes": []}, {"base": "x", "changes": {}}])
def test_a_malformed_body_is_a_bad_request(env, body):
    with pytest.raises(api.SettingsError) as caught:
        api.write(env[0], "work_briefing", body, audit=env[1])
    assert (caught.value.status, caught.value.code) == (400, "bad_request")


def test_an_unknown_group_is_not_found(env):
    for call in (lambda: api.read(env[0], "nope"), lambda: api.write(env[0], "nope", {"base": "x", "changes": {"a": 1}}, audit=env[1])):
        with pytest.raises(api.SettingsError) as caught:
            call()
        assert (caught.value.status, caught.value.code) == (404, "unknown_group")


def test_the_audit_keeps_the_full_old_and_new_text_of_a_prompt(env):
    config, audit = env
    _write(env, {"prompt_zh": "第一版提示词"})
    _write(env, {"prompt_zh": "第二版提示词，改过了"})
    newest = audit.read()[0]
    assert (newest["old"], newest["new"]) == ("第一版提示词", "第二版提示词，改过了")
