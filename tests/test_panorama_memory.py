# -*- coding: utf-8 -*-
"""配置全景：记忆按作用域列出（机器 → 全局 / 项目），标出重复的和像是放错了作用域的。

探针读真的文件（临时目录里的假家目录）；判定是纯函数；图那一半喂虚构事实。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from pet import i18n
from pet.memory_distill_sink import BLOCK_END, BLOCK_START
from pet.panorama import claude_home_probe, memory_scope, sources
from tests import panorama_samples as samples

_MISSING_KEY = re.compile(r"panorama\.|stores\.(root\.|[a-z_]+\.(name|holds|why))")


@pytest.fixture(autouse=True)
def _chinese():
    i18n.set_language("zh")
    yield
    i18n.set_language("zh")


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def _memory(name: str, description: str, kind: str = "feedback", body: str = "BODY-TEXT") -> str:
    return f"---\nname: {name}\ndescription: {description}\nmetadata:\n  node_type: memory\n  type: {kind}\n---\n\n{body}\n"


# ───────────────────────── 探针 ─────────────────────────

def _fake_claude(root: Path) -> Path:
    claude = root / ".claude"
    _write(claude / "CLAUDE.md", f"# Mine\n\n## Tools\n- use tabs\n\n{BLOCK_START}\n## 会话里定下的规矩\n"
           f"- **画图只画机制** — 不画装饰（依据：某次会话）\n- **默认中文** 解释用中文\n<!-- 更新：2026-01-01 10:00 -->\n{BLOCK_END}\n\n## After\n")
    memory = claude / "projects" / "C--Users-dev-tomato" / "memory"
    _write(memory / "MEMORY.md", "- [Reply](reply.md) — hook\n")
    _write(memory / "reply.md", _memory("reply-in-chinese", "回复用中文；有推荐方案直接做"))
    _write(memory / "plain.md", "# 没有头的记忆\n\n第一段正文。\n")
    _write(memory / "quoted.md", '---\nname: "quoted name"\ndescription: \'single quoted\'\ntype: user\n---\nx\n')
    _write(claude / "projects" / "C--Users-dev-potato" / "memory" / "MEMORY.md", "")
    _write(claude / "projects" / "C--Users-dev-potato" / "memory" / "distill-abc.md", _memory("distilled", "来自蒸馏", "project"))
    _write(claude / "projects" / "C--Users-dev-empty" / "0f0f.jsonl", "TRANSCRIPT")
    return claude


def test_index_lists_every_memory_file_with_its_name_description_and_type(tmp_path):
    index = claude_home_probe.memory_index(str(_fake_claude(tmp_path)))
    projects = {p["name"]: p["entries"] for p in index["projects"]}
    assert set(projects) == {"C--Users-dev-tomato", "C--Users-dev-potato"}            # 没有记忆目录的项目不列
    tomato = {e["file"]: e for e in projects["C--Users-dev-tomato"]}
    assert set(tomato) == {"reply.md", "plain.md", "quoted.md"}                        # MEMORY.md 是目录，不算一条
    assert (tomato["reply.md"]["name"], tomato["reply.md"]["description"], tomato["reply.md"]["type"]) == (
        "reply-in-chinese", "回复用中文；有推荐方案直接做", "feedback")
    assert (tomato["quoted.md"]["name"], tomato["quoted.md"]["description"], tomato["quoted.md"]["type"]) == (
        "quoted name", "single quoted", "user")
    assert tomato["plain.md"]["name"] == "没有头的记忆" and tomato["plain.md"]["description"] == "" and tomato["plain.md"]["type"] == ""
    assert projects["C--Users-dev-potato"][0]["file"] == "distill-abc.md" and projects["C--Users-dev-potato"][0]["type"] == "project"
    assert index["entries"] == 4 and index["truncated"] is False
    assert len(tomato["reply.md"]["mtime"]) == 16 and tomato["reply.md"]["bytes"] > 0


def test_index_reads_the_managed_rules_and_the_headings_outside_the_block(tmp_path):
    index = claude_home_probe.memory_index(str(_fake_claude(tmp_path)))
    assert index["rules"] == [{"title": "画图只画机制", "text": "不画装饰（依据：某次会话）"}, {"title": "默认中文", "text": "解释用中文"}]
    assert index["sections"] == ["Mine", "Tools", "After"]                             # 受管块里的小标题不算你自己写的


def test_index_carries_descriptions_but_never_the_body_of_a_memory_file(tmp_path):
    dumped = json.dumps(claude_home_probe.memory_index(str(_fake_claude(tmp_path))), ensure_ascii=False)
    assert "BODY-TEXT" not in dumped and "第一段正文" not in dumped and "TRANSCRIPT" not in dumped


def test_index_cuts_long_text_and_caps_the_number_of_entries(tmp_path):
    claude = _fake_claude(tmp_path)
    memory = claude / "projects" / "C--Users-dev-many" / "memory"
    _write(memory / "MEMORY.md", "")
    _write(memory / "long.md", _memory("long", "字" * 1000))
    for i in range(claude_home_probe.MEMORY_ENTRY_LIMIT):
        _write(memory / f"n{i:04}.md", _memory(f"n{i}", "d"))
    index = claude_home_probe.memory_index(str(claude))
    assert index["truncated"] is True and index["entries"] == claude_home_probe.MEMORY_ENTRY_LIMIT
    longest = max(len(e["description"]) for p in index["projects"] for e in p["entries"])
    assert longest <= claude_home_probe.MEMORY_TEXT_LIMIT + 1


def test_index_of_a_home_without_claude_code_is_empty_not_an_error(tmp_path):
    assert claude_home_probe.memory_index(str(tmp_path / "nope")) == {
        "rules": [], "sections": [], "projects": [], "entries": 0, "truncated": False}
    assert claude_home_probe.probe(tmp_path)["memory_index"]["projects"] == []


# ───────────────────────── 判定 ─────────────────────────

def _entry(name: str, description: str = "", file: str = "", kind: str = "feedback") -> dict:
    return {"file": file or name + ".md", "name": name, "description": description, "type": kind, "bytes": 10, "mtime": "2026-01-02 03:04"}


def _index(rules=(), projects=None) -> dict:
    return {"rules": [{"title": t, "text": ""} for t in rules], "sections": [],
            "projects": [{"name": name, "entries": entries} for name, entries in (projects or {}).items()], "entries": 0, "truncated": False}


def _flags(view: dict, side: str, project: str, name: str) -> set:
    block = next(s for s in view["sides"] if s["id"] == side)
    entry = next(e for p in block["projects"] if p["name"] == project for e in p["entries"] if e["name"] == name)
    return set(entry["flags"])


def test_the_same_title_in_two_projects_is_a_duplicate_that_looks_global():
    view = memory_scope.analyse([("win", _index(projects={"A": [_entry("Run tests locally")], "B": [_entry("run-tests locally!")],
                                                           "C": [_entry("Something else")]}))])
    assert _flags(view, "win", "A", "Run tests locally") == {"dup", "to_global"}
    assert _flags(view, "win", "B", "run-tests locally!") == {"dup", "to_global"}        # 大小写和标点不算区别
    assert _flags(view, "win", "C", "Something else") == set()
    assert view["sides"][0]["counts"] == {"entries": 3, "dup": 2, "misplaced": 2}


def test_the_same_description_also_counts_even_when_the_titles_differ():
    long_text = "pytest needs these environment variables to run"
    view = memory_scope.analyse([("win", _index(projects={"A": [_entry("one", long_text)], "B": [_entry("two", long_text)],
                                                           "C": [_entry("three", "short"), _entry("four", "short")]}))])
    assert _flags(view, "win", "A", "one") == {"dup", "to_global"}
    assert _flags(view, "win", "C", "three") == set()                                    # 太短的说明不拿来比：撞上的多半是巧合


def test_two_entries_with_one_title_inside_one_project_are_duplicates_but_not_misplaced():
    view = memory_scope.analyse([("win", _index(projects={"A": [_entry("Same", file="a.md"), _entry("Same", file="b.md")]}))])
    assert _flags(view, "win", "A", "Same") == {"dup"}
    assert view["sides"][0]["counts"] == {"entries": 2, "dup": 2, "misplaced": 0}


def test_a_project_memory_that_repeats_a_global_rule_is_marked_as_already_global():
    view = memory_scope.analyse([("win", _index(rules=["Reply in Chinese"], projects={"A": [_entry("reply in chinese")]}))])
    assert _flags(view, "win", "A", "reply in chinese") == {"dup", "in_global"}
    rule = view["sides"][0]["rules"][0]
    assert rule["flags"] == ["dup"] and rule["twins"] == [{"side": "win", "project": "A", "title": "reply in chinese"}]


def test_the_same_thing_on_both_machines_is_noted_but_not_called_misplaced():
    view = memory_scope.analyse([("win", _index(rules=["Diagrams show mechanisms"], projects={"A": [_entry("Local notes")]})),
                                 ("wsl", _index(rules=["diagrams show mechanisms"], projects={"X": [_entry("local notes")]}))])
    assert _flags(view, "win", "A", "Local notes") == {"both_sides"}
    assert _flags(view, "wsl", "X", "local notes") == {"both_sides"}
    assert [s["rules"][0]["flags"] for s in view["sides"]] == [["both_sides"], ["both_sides"]]
    assert [s["counts"] for s in view["sides"]] == [{"entries": 1, "dup": 0, "misplaced": 0}] * 2


def test_twins_say_where_the_other_copy_lives():
    view = memory_scope.analyse([("win", _index(rules=["R"], projects={"C--Users-dev-tomato": [_entry("R")], "C--Users-dev-potato": [_entry("r")]}))])
    entry = view["sides"][0]["projects"][0]["entries"][0]
    assert {(t["side"], t["project"]) for t in entry["twins"]} == {("win", ""), ("win", "potato")}       # 空的项目 = 全局
    assert set(entry["flags"]) == {"dup", "to_global", "in_global"}


@pytest.mark.parametrize("name, label", [
    ("C--Users-dev-Github-tomato", "Github-tomato"), ("-home-dev-work-carrot", "work-carrot"), ("D--scratch", "D--scratch"),
    ("-mnt-c-Users-dev-notes", "notes"), ("plain", "plain"),
])
def test_project_folders_are_shown_without_the_home_prefix(name, label):
    assert memory_scope.project_label(name) == label


def test_an_empty_or_missing_index_gives_an_empty_side_not_an_error():
    view = memory_scope.analyse([("win", None), ("wsl", {})])
    assert [s["projects"] for s in view["sides"]] == [[], []] and view["sides"][0]["counts"]["entries"] == 0


# ───────────────────────── 图 ─────────────────────────

def test_the_graph_carries_the_memory_view_for_both_sides_with_text_in_the_interface_language():
    graph = sources.build(samples.facts())
    sides = {s["id"]: s for s in graph["memory"]["sides"]}
    assert sides["win"]["title"] == "个人 · 这台机器" and sides["wsl"]["title"].startswith("公司 · WSL")
    tomato = next(p for p in sides["win"]["projects"] if p["label"] == "tomato")
    run = next(e for e in tomato["entries"] if e["name"] == "本机测试方法")
    assert [f["kind"] for f in run["flags"]] == ["dup", "to_global", "both_sides"]
    assert run["flags"][0]["label"] == "重复" and "potato" in run["flags"][0]["tip"] and "公司" in run["flags"][2]["tip"]
    assert run["view"] == {"store": "claude_memory", "path": "projects/C--Users-dev-tomato/memory/run.md"}
    assert sides["win"]["rules"][0]["view"] == {"store": "claude_md", "path": "CLAUDE.md"}
    carrot = sides["wsl"]["projects"][0]["entries"][0]
    assert carrot["view"] == {"store": "claude_memory_wsl", "path": "projects/-home-dev-carrot/memory/notes.md"}     # 经 wsl.exe 读
    assert sides["wsl"]["rules"][0]["view"] == {"store": "claude_md_wsl", "path": "CLAUDE.md"}


def test_flags_become_one_note_per_side_and_the_memory_tiles_offer_the_view():
    graph = sources.build(samples.facts())
    notes = [q for q in graph["quests"] if q["node"] in ("mem_win", "mem_wsl")]
    text = next(q["text"] for q in notes if q["node"] == "mem_win" and "重复" in q["text"])
    assert "3 条重复" in text and "3 条像是放错了作用域" in text
    assert all(q["sev"] == "info" for q in notes)
    nodes = {n["id"]: n for n in graph["nodes"]}
    assert nodes["mem_win"]["memory"] == "win" and nodes["md_win"]["memory"] == "win"
    assert nodes["mem_wsl"]["memory"] == "wsl" and nodes["md_wsl"]["memory"] == "wsl"


def test_while_wsl_is_pending_or_absent_only_this_machine_is_listed():
    for state in ("pending", "absent", "error"):
        graph = sources.build(samples.facts(wsl=state))
        assert [s["id"] for s in graph["memory"]["sides"]] == ["win"]
        run = next(e for p in graph["memory"]["sides"][0]["projects"] for e in p["entries"] if e["name"] == "本机测试方法")
        assert "both_sides" not in [f["kind"] for f in run["flags"]]


def test_a_side_with_nothing_flagged_gets_no_note():
    win = samples.home()
    win["memory_index"] = _index(projects={"C--Users-dev-tomato": [_entry("only one")]})
    graph = sources.build(samples.facts(win=win, wsl="absent"))
    assert not any("重复" in q["text"] for q in graph["quests"])
    older = samples.home()
    older.pop("memory_index")                                                          # 老探针的结果（没有这一段）也画得出来
    assert sources.build(samples.facts(win=older, wsl="absent"))["memory"]["sides"][0]["projects"] == []


@pytest.mark.parametrize("language", ["zh", "en"])
def test_memory_text_exists_in_both_languages(language):
    i18n.set_language(language)
    assert not _MISSING_KEY.search(json.dumps(sources.build(samples.facts()), ensure_ascii=False))
