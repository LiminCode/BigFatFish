# -*- coding: utf-8 -*-
"""配置全景：工作空间——每个 Claude Code 在哪些项目目录里干过活、各有多少次会话、上次什么时候。

探针读真的文件（临时目录里的假家目录）；图那一半喂虚构事实。
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import pytest

from pet import i18n
from pet.panorama import claude_home_probe, render, sources
from tests import panorama_samples as samples

_MISSING_KEY = re.compile(r"panorama\.|stores\.(root\.|[a-z_]+\.(name|holds|why))")
STAMP = time.mktime((2026, 1, 2, 3, 4, 0, 0, 0, -1))


@pytest.fixture(autouse=True)
def _chinese():
    i18n.set_language("zh")
    yield
    i18n.set_language("zh")


def _node(graph: dict, node_id: str) -> dict:
    return next(n for n in graph["nodes"] if n["id"] == node_id)


def _item(node: dict, name: str) -> dict:
    return next(i for i in node["items"] if i["name"] == name)


def _session(folder: Path, name: str, cwd: str, age_days: float = 0, extra: str = "") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes((json.dumps({"type": "user", "cwd": cwd, "message": "SECRET-PROMPT"}) + "\n" + extra).encode("utf-8"))
    os.utime(path, (STAMP - age_days * 86400, STAMP - age_days * 86400))
    return path


@pytest.fixture
def home(tmp_path):
    """假家目录：一个在 ``.claude.json`` 里登记过的项目、一个目录已经删掉的、一个只能从会话记录认出来的、
    一个认不出来的、一个只有记忆没有会话的、两个空的。"""
    claude = tmp_path / ".claude"
    projects = claude / "projects"
    alive, gone, by_cwd = tmp_path / "repo-alive", tmp_path / "repo-gone", tmp_path / "repo-by-cwd"
    alive.mkdir(), by_cwd.mkdir()
    enc = claude_home_probe.encode_project_path
    _session(projects / enc(str(alive)), "a.jsonl", str(alive), age_days=2)
    _session(projects / enc(str(alive)), "b.jsonl", str(alive), age_days=0, extra="x" * 100)
    (projects / enc(str(alive)) / "memory").mkdir()
    (projects / enc(str(alive)) / "memory" / "MEMORY.md").write_text("", encoding="utf-8")
    (projects / enc(str(alive)) / "memory" / "note.md").write_text("n", encoding="utf-8")
    _session(projects / enc(str(gone)), "c.jsonl", str(gone), age_days=5)
    _session(projects / enc(str(by_cwd)), "d.jsonl", str(by_cwd), age_days=1)
    _session(projects / "mystery-folder", "e.jsonl", str(tmp_path / "somewhere-else"), age_days=3)
    (projects / "memory-only" / "memory").mkdir(parents=True)
    (projects / "memory-only" / "memory" / "kept.md").write_text("k", encoding="utf-8")
    (projects / "empty-one").mkdir()
    (projects / "empty-two").mkdir()
    state = {"projects": {
        str(alive).replace("\\", "/"): {"lastCost": 1.2345, "lastDuration": 754000, "lastLinesAdded": 120, "lastLinesRemoved": 30,
                                        "lastSessionId": "abc"},
        str(gone): {"lastCost": 0},
        str(tmp_path / "never-opened"): {},
    }}
    (tmp_path / ".claude.json").write_text(json.dumps(state), encoding="utf-8")
    return tmp_path, state


# ───────────────────────── 探针 ─────────────────────────

def test_project_paths_are_encoded_the_way_claude_code_names_its_folders():
    enc = claude_home_probe.encode_project_path
    assert enc("C:\\Users\\dev\\Github\\tomato") == "C--Users-dev-Github-tomato"
    assert enc("C:/Users/dev/Github/tomato") == "C--Users-dev-Github-tomato"
    assert enc("/home/dev/work/carrot.v2") == "-home-dev-work-carrot-v2"
    assert enc("/home/dev/.claude/worktrees/a_b") == "-home-dev--claude-worktrees-a-b"


def test_workspaces_list_every_project_with_sessions_or_memory_newest_first(home):
    root, state = home
    out = claude_home_probe.workspaces(str(root / ".claude"), state)
    names = [Path(row["path"]).name if row["path"] else row["name"] for row in out["projects"]]
    assert names == ["repo-alive", "repo-by-cwd", "mystery-folder", "repo-gone", "memory-only"]
    assert (out["total"], out["empty"], out["sessions"], out["missing"], out["truncated"]) == (7, 2, 5, 1, False)
    alive = out["projects"][0]
    assert (alive["sessions"], alive["memory"], alive["exists"], alive["last"]) == (2, 1, True, "2026-01-02 03:04")
    assert alive["bytes"] == sum(p.stat().st_size for p in (root / ".claude" / "projects" / alive["name"]).glob("*.jsonl"))
    assert out["bytes"] == sum(row["bytes"] for row in out["projects"])


def test_a_project_path_comes_from_the_state_file_or_from_a_transcript_that_agrees_with_the_folder(home):
    root, state = home
    rows = {row["name"]: row for row in claude_home_probe.workspaces(str(root / ".claude"), state)["projects"]}
    enc = claude_home_probe.encode_project_path
    assert rows[enc(str(root / "repo-alive"))]["path"] == str(root / "repo-alive").replace("\\", "/")      # 登记时怎么写的就怎么给
    assert rows[enc(str(root / "repo-by-cwd"))]["path"] == str(root / "repo-by-cwd")                        # 没登记：会话记录里的目录对得上才用
    assert rows["mystery-folder"]["path"] == "" and rows["mystery-folder"]["exists"] is None                # 对不上：宁可说不知道
    assert rows[enc(str(root / "repo-gone"))]["exists"] is False
    assert rows["memory-only"]["sessions"] == 0 and rows["memory-only"]["last"] == "" and rows["memory-only"]["memory"] == 1


def test_the_last_session_figures_come_from_the_state_file(home):
    root, state = home
    rows = {row["name"]: row for row in claude_home_probe.workspaces(str(root / ".claude"), state)["projects"]}
    alive = rows[claude_home_probe.encode_project_path(str(root / "repo-alive"))]
    assert alive["last_session"] == {"cost": 1.23, "minutes": 13, "added": 120, "removed": 30}
    assert rows["mystery-folder"]["last_session"] == {}
    assert rows[claude_home_probe.encode_project_path(str(root / "repo-gone"))]["last_session"] == {}       # 全是零：等于没有


def test_workspaces_never_carry_what_was_said_in_a_session(home):
    root, state = home
    assert "SECRET-PROMPT" not in json.dumps(claude_home_probe.workspaces(str(root / ".claude"), state))
    assert "SECRET-PROMPT" not in json.dumps(claude_home_probe.probe(root))


def test_the_list_is_capped_but_the_totals_are_not(home):
    root, state = home
    projects = root / ".claude" / "projects"
    for i in range(claude_home_probe.WORKSPACE_LIMIT + 4):
        _session(projects / f"bulk-{i:03}", "s.jsonl", "/nowhere", age_days=10 + i)
    out = claude_home_probe.workspaces(str(root / ".claude"), state)
    assert len(out["projects"]) == claude_home_probe.WORKSPACE_LIMIT and out["truncated"] is True
    assert out["total"] == 7 + claude_home_probe.WORKSPACE_LIMIT + 4 and out["sessions"] == 5 + claude_home_probe.WORKSPACE_LIMIT + 4
    assert out["projects"][0]["sessions"] == 2                                                             # 最近的还在最前面


def test_a_home_without_projects_gives_an_empty_answer(tmp_path):
    assert claude_home_probe.workspaces(str(tmp_path / "nope"), {}) == {
        "projects": [], "total": 0, "empty": 0, "sessions": 0, "bytes": 0, "missing": 0, "truncated": False}
    assert claude_home_probe.probe(tmp_path)["workspaces"]["projects"] == []


# ───────────────────────── 图 ─────────────────────────

def test_each_claude_code_gets_a_workspace_tile_listing_its_projects():
    graph = sources.build(samples.facts())
    tile = _node(graph, "ws_win")
    assert tile["kind"] == "workspace" and tile["region"] == "win" and tile["sub"] == "3 个项目 · 1 个目录已不在"
    assert [i["name"] for i in tile["items"]] == ["tomato", "mystery-folder", "potato"]
    tomato = _item(tile, "tomato")
    assert tomato["state"] == "ok" and tomato["detail"] == "3 次会话 · 2026-01-02 03:04"
    assert dict(tomato["more"]) == {"路径": "C:\\Users\\dev\\tomato", "会话原文": "3 次 · 1.0 MB", "记忆": "3 条",
                                    "上一次会话": "13 分钟 · $1.23 · +120 / −30 行"}
    assert any(e["from"] == "cc_win" and e["to"] == "ws_win" for e in graph["edges"])
    assert _node(graph, "ws_wsl")["region"] == "wsl" and _item(_node(graph, "ws_wsl"), "carrot")["state"] == "ok"


def test_a_project_whose_folder_is_gone_is_faint_and_one_whose_path_is_unknown_says_so():
    tile = _node(sources.build(samples.facts()), "ws_win")
    potato, mystery = _item(tile, "potato"), _item(tile, "mystery-folder")
    assert potato["state"] == "off" and "目录已经不在了" in dict(potato["more"])["状态"]
    assert mystery["state"] == "unknown" and dict(mystery["more"])["路径"].startswith("不知道")
    assert "上一次会话" not in dict(potato["more"])


def test_the_tile_adds_up_what_the_transcripts_take_and_counts_the_empty_folders():
    graph = sources.build(samples.facts())
    facts = dict(map(tuple, _node(graph, "ws_win")["facts"]))
    assert facts["会话原文合计"] == "6 次 · 1.2 MB" and facts["空的项目目录"] == "2 个"
    assert facts["位置"] == "C:\\Users\\dev\\.claude\\projects" and facts["上次探测"] == "2026-01-02 03:04:05"
    notes = [q for q in graph["quests"] if q["node"] == "ws_win"]
    assert [q["sev"] for q in notes] == ["info"] and "1 个项目的目录已经不在了" in notes[0]["text"]


def test_many_empty_project_folders_get_a_note_of_their_own():
    wsl = samples.wsl_home()
    wsl["workspaces"]["empty"], wsl["workspaces"]["total"] = 1533, 1534
    graph = sources.build(samples.facts(wsl=wsl))
    assert any(q["node"] == "ws_wsl" and "1533 个空的项目目录" in q["text"] for q in graph["quests"])
    assert not any(q["node"] == "ws_wsl" for q in sources.build(samples.facts())["quests"])                # 样例里公司侧一个空的都没有


def test_the_wsl_tile_waits_for_the_wsl_half_and_older_results_draw_without_it():
    for state in ("pending", "absent", "error"):
        assert not any(n["id"] == "ws_wsl" for n in sources.build(samples.facts(wsl=state))["nodes"])
    older = samples.home()
    older.pop("workspaces")
    assert not any(n["id"] == "ws_win" for n in sources.build(samples.facts(win=older))["nodes"])


@pytest.mark.parametrize("language", ["zh", "en"])
def test_workspace_text_exists_in_both_languages(language):
    i18n.set_language(language)
    wsl = samples.wsl_home()
    wsl["workspaces"].update(empty=40, truncated=True)
    assert not _MISSING_KEY.search(json.dumps(sources.build(samples.facts(wsl=wsl)), ensure_ascii=False))


def test_the_workspace_kind_has_its_icon_on_the_page():
    graph = sources.build(samples.facts())
    icon = graph["kinds"]["workspace"]["icon"]
    assert re.search(rf"^\s*{icon}:'", render.asset("util.js").decode("utf-8"), re.M)
