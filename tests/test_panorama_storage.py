# -*- coding: utf-8 -*-
"""配置全景上的存储：存储表（设计）+ 探针（此刻这台机器上的实际情况）→ 磁贴、连线和待处理。

探针读真的文件（临时目录）；图那一半喂虚构事实。
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import pytest

from pet import config_backup, i18n
from pet import data_stores as ds
from pet.panorama import places, sources, storage_probe
from tests import panorama_samples as samples


_MISSING_KEY = re.compile(r"panorama\.|stores\.(root\.|[a-z_]+\.(name|holds|why))")


@pytest.fixture(autouse=True)
def _chinese():
    i18n.set_language("zh")
    yield
    i18n.set_language("zh")


def _node(graph: dict, node_id: str) -> dict:
    return next(n for n in graph["nodes"] if n["id"] == node_id)


def _edge(graph: dict, source: str, target: str) -> dict:
    return next(e for e in graph["edges"] if e["from"] == source and e["to"] == target)


def _item(node: dict, name: str) -> dict:
    return next(i for i in node["items"] if i["name"] == name)


def _write(root: Path, name: str, text: str = "x") -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ───────────────────────── 探针 ─────────────────────────

def test_survey_counts_every_file_under_the_store_that_owns_it(tmp_path):
    _write(tmp_path, "config.json", "12345")
    _write(tmp_path, "memory-distill/entries.json", "123")
    _write(tmp_path, "sessions/a.json")
    _write(tmp_path, "sessions/b.json", "xy")
    _write(tmp_path, "pet-1.log")
    out = storage_probe.survey("data", tmp_path)
    assert out["path"] == str(tmp_path) and out["files"] == 5 and not out["truncated"]
    assert out["stores"]["config"]["files"] == 1 and out["stores"]["config"]["bytes"] == 5
    assert out["stores"]["chat_sessions"] == {"files": 2, "bytes": 3, "mtime": out["stores"]["chat_sessions"]["mtime"]}
    assert out["stores"]["distill_entries"]["files"] == 1 and out["stores"]["logs"]["files"] == 1
    assert out["unknown"] == [] and out["unknown_count"] == 0


def test_survey_reports_files_the_registry_does_not_know_by_name_only(tmp_path):
    _write(tmp_path, "config.json")
    _write(tmp_path, "brand-new-feature.json", "SECRET-CONTENT")
    _write(tmp_path, "mystery/thing.bin", "SECRET-CONTENT")
    out = storage_probe.survey("data", tmp_path)
    assert out["unknown"] == ["brand-new-feature.json", "mystery/thing.bin"] and out["unknown_count"] == 2
    assert "SECRET-CONTENT" not in json.dumps(out)


def test_survey_caps_the_list_of_unknown_names_but_keeps_the_real_count(tmp_path):
    for i in range(storage_probe.UNKNOWN_LIMIT + 5):
        _write(tmp_path, f"odd/{i:03}.bin")
    out = storage_probe.survey("data", tmp_path)
    assert len(out["unknown"]) == storage_probe.UNKNOWN_LIMIT and out["unknown_count"] == storage_probe.UNKNOWN_LIMIT + 5


def test_survey_stops_at_the_file_cap_and_says_so(tmp_path):
    for i in range(12):
        _write(tmp_path, f"sessions/{i}.json")
    out = storage_probe.survey("data", tmp_path, max_files=10)
    assert out["truncated"] and out["files"] == 10


def test_survey_of_a_missing_directory_is_empty_not_an_error(tmp_path):
    out = storage_probe.survey("data", tmp_path / "nope")
    assert out["exists"] is False and out["stores"] == {} and out["files"] == 0


def test_newest_file_time_is_reported_per_store(tmp_path):
    old = _write(tmp_path, "sessions/a.json")
    new = _write(tmp_path, "sessions/b.json")
    stamp = time.mktime((2026, 1, 2, 3, 4, 0, 0, 0, -1))
    os.utime(old, (stamp - 86400, stamp - 86400))
    os.utime(new, (stamp, stamp))
    assert storage_probe.survey("data", tmp_path)["stores"]["chat_sessions"]["mtime"] == "2026-01-02 03:04"


def test_named_only_looks_at_the_files_the_registry_names_and_never_walks(tmp_path):
    """用户的家目录不能整个走一遍：只看表里点了名的那几个文件。"""
    _write(tmp_path, ".claude.json", "1234")
    _write(tmp_path, "Documents/private.txt")
    out = storage_probe.named("home", tmp_path)
    assert out["stores"] == {"claude_json": {"files": 1, "bytes": 4, "mtime": out["stores"]["claude_json"]["mtime"]}}
    assert out["unknown"] == [] and out["files"] == 1


def test_backup_state_tells_off_never_done_failed_and_paused_apart(tmp_path):
    cfg = {"config_backup": {"auto": False}}
    assert storage_probe.backup_state(cfg, tmp_path, "acme/handbook") == {
        "auto": False, "repo": "acme/handbook", "path": config_backup.DEFAULT_PATH, "backed_up_at": "", "error": "", "paused": False}
    state = config_backup.BackupState(repo="acme/handbook", path="x", backed_up_at=time.mktime((2026, 1, 2, 3, 4, 0, 0, 0, -1)))
    config_backup._save_state(tmp_path, state)
    on = storage_probe.backup_state({"config_backup": {"auto": True}}, tmp_path, "acme/handbook")
    assert on["auto"] and on["backed_up_at"] == "2026-01-02 03:04" and not on["error"]
    state.error, state.attempted_at = "HTTP 401", state.backed_up_at + 60
    config_backup._save_state(tmp_path, state)
    assert storage_probe.backup_state({"config_backup": {"auto": True}}, tmp_path, "")["error"] == "HTTP 401"
    state.rebuilt_at = 1.0
    config_backup._save_state(tmp_path, state)
    assert storage_probe.backup_state({"config_backup": {"auto": True}}, tmp_path, "")["paused"] is True


def test_backup_state_without_any_repository_has_nowhere_to_go(tmp_path):
    assert storage_probe.backup_state({"config_backup": {"auto": True}}, tmp_path, "")["repo"] == ""


# ───────────────────────── 版面声明 ─────────────────────────

def test_every_store_has_somewhere_to_appear_on_the_map():
    """表里加了一个新的根，却没说它画在图上哪里：这条会红。"""
    shown = {root for place in places.PLACES for root in place.roots}
    for store in ds.STORES:
        assert store.root in shown or store.id in places.OWN_TILE, store.id
    assert all(root in ds.ROOTS for root in shown)


# ───────────────────────── 图 ─────────────────────────

def test_each_place_is_split_by_what_happens_if_the_disk_dies():
    graph = sources.build(samples.facts())
    kept, local, free = (_node(graph, f"st_fish_{part}") for part in ("kept", "local", "free"))
    assert [i["name"] for i in kept["items"]] == ["肥鱼的设置"]
    assert {i["name"] for i in local["items"]} >= {"蒸馏条目（个人）", "聊天记录", "API Key 和 Token"}
    assert {i["name"] for i in free["items"]} >= {"运行日志", "语音和音效缓存"}
    assert local["state"] == "warn" and local["kind"] == "store"
    assert (kept["region"], kept["col"]) == (local["region"], local["col"]) == ("win", 1)
    assert _edge(graph, "pet", "st_fish_local")["line"] == "storage"
    assert _node(graph, "st_cc_win_local") and _node(graph, "st_cc_wsl_local")["region"] == "wsl"
    assert _edge(graph, "cc_wsl", "st_cc_wsl_local")["line"] == "storage"


def test_every_store_is_listed_exactly_once_in_the_tiles_of_its_place():
    graph = sources.build(samples.facts())
    listed = [i["id"] for n in graph["nodes"] if n["kind"] == "store" for i in n.get("items", []) if "id" in i]
    expected = [s.id for s in ds.STORES if s.id not in places.OWN_TILE]
    assert sorted(listed) == sorted(expected)


def test_an_item_says_what_it_holds_where_who_writes_it_and_where_it_comes_back_from():
    graph = sources.build(samples.facts())
    item = _item(_node(graph, "st_fish_local"), "蒸馏条目（个人）")
    more = dict(item["more"])
    assert "审核通过" in more["里面是什么"]
    assert more["在哪"] == "C:\\Users\\dev\\cfg → memory-distill/entries.json"
    assert more["谁在写"] == "memory_distill_sink"
    assert more["丢了从哪恢复"].startswith("还只在这台机器上") and "M6" in more["丢了从哪恢复"]
    assert item["detail"] == "1 个文件 · 2.0 KB · 2026-01-02 03:04" and item["state"] == "warn"


def test_a_store_with_nothing_on_this_machine_is_listed_faint_and_not_counted_as_a_gap():
    graph = sources.build(samples.facts())
    local = _node(graph, "st_fish_local")
    absent = _item(local, "分身的设置")
    assert absent["state"] == "off" and absent["detail"] == "这台机器上没有"
    quest = next(q for q in graph["quests"] if q["node"] == "st_fish_local")
    assert quest["sev"] == "warn" and "分身的设置" not in quest["text"] and "蒸馏条目（个人）" in quest["text"]
    present = sum(1 for i in local["items"] if i["state"] == "warn")
    assert f"{present} 种" in quest["text"] and f"{present} 种" in local["sub"]


def test_config_backup_switched_off_is_a_warning_and_its_line_to_github_is_faint():
    graph = sources.build(samples.facts())
    kept = _node(graph, "st_fish_kept")
    assert kept["state"] == "warn" and "没开" in kept["sub"]
    assert _edge(graph, "st_fish_kept", "gh_personal")["state"] == "off"
    assert any(q["sev"] == "warn" and q["node"] == "st_fish_kept" and "配置备份" in q["text"] for q in graph["quests"])
    assert _edge(graph, "pet", "gh_personal")["label"] == ""             # 「配置备份」这条线现在从设置那块磁贴出发


@pytest.mark.parametrize("backup, node_state, edge_state, words", [
    ({"auto": True, "repo": "acme/handbook", "backed_up_at": "2026-01-02 03:04"}, "ok", "ok", "2026-01-02 03:04"),
    ({"auto": True, "repo": "acme/handbook", "backed_up_at": ""}, "unknown", "unknown", "还没备份过"),
    ({"auto": True, "repo": "acme/handbook", "backed_up_at": "2026-01-02 03:04", "error": "HTTP 401"}, "warn", "broken", "HTTP 401"),
    ({"auto": True, "repo": "acme/handbook", "backed_up_at": "2026-01-02 03:04", "paused": True}, "warn", "warn", "暂停"),
    ({"auto": True, "repo": "", "backed_up_at": ""}, "warn", "off", "没开"),
])
def test_config_backup_state_drives_the_tile_and_the_line(backup, node_state, edge_state, words):
    graph = sources.build(samples.facts(backup=backup))
    kept = _node(graph, "st_fish_kept")
    assert kept["state"] == node_state and _edge(graph, "st_fish_kept", "gh_personal")["state"] == edge_state
    assert words in json.dumps(kept, ensure_ascii=False)


def test_backup_without_a_token_cannot_be_on():
    facts = samples.facts(backup={"auto": True, "repo": "acme/handbook", "backed_up_at": "2026-01-02 03:04"})
    facts["github_token"] = {"present": False, "tail": ""}
    assert _node(sources.build(facts), "st_fish_kept")["state"] == "warn"


def test_files_the_registry_does_not_know_get_their_own_tile_and_a_quest():
    graph = sources.build(samples.facts(unknown=["leftover.md", "odd/thing.bin"]))
    tile = _node(graph, "st_fish_unknown")
    assert tile["state"] == "unknown" and [i["name"] for i in tile["items"]] == ["leftover.md", "odd/thing.bin"]
    assert any(q["sev"] == "unknown" and q["node"] == "st_fish_unknown" and "leftover.md" in q["text"] for q in graph["quests"])
    assert not any(n["id"] == "st_fish_unknown" for n in sources.build(samples.facts())["nodes"])


def test_keyring_entries_are_counted_from_what_the_probe_already_knows():
    graph = sources.build(samples.facts())
    item = _item(_node(graph, "st_fish_local"), "API Key 和 Token")
    assert item["detail"] == "3 条" and item["state"] == "warn"            # 两个服务的 key + GitHub token


def test_the_wsl_side_is_shown_from_the_registry_alone_until_it_is_surveyed():
    older = samples.wsl_home()
    older.pop("storage")                                                 # 老探针的结果：那边没数过存储
    graph = sources.build(samples.facts(wsl=older))
    local = _node(graph, "st_cc_wsl_local")
    assert all(i["detail"] == "" and i["state"] == "warn" for i in local["items"])
    assert not any(n["id"].startswith("st_cc_wsl") for n in sources.build(samples.facts(wsl="pending"))["nodes"])
    assert not any(n["id"].startswith("st_cc_wsl") for n in sources.build(samples.facts(wsl="absent"))["nodes"])


def test_tiles_that_already_stand_for_a_store_say_where_it_comes_back_from():
    graph = sources.build(samples.facts())
    assert any(label == "丢了从哪恢复" and "还只在这台机器上" in value for label, value in _node(graph, "md_win")["facts"])
    assert any(label == "丢了从哪恢复" and "私有仓库" in value for label, value in _node(graph, "vault_personal")["facts"])


def test_a_clone_with_unpushed_commits_is_a_warning_and_uncommitted_edits_are_a_note():
    facts = samples.facts()
    facts["personal_vault"].update(unpushed=3, dirty=True)
    graph = sources.build(facts)
    assert _node(graph, "vault_personal")["state"] == "warn" and _edge(graph, "vault_personal", "gh_personal")["state"] == "warn"
    levels = {q["sev"] for q in graph["quests"] if q["node"] == "vault_personal"}
    assert levels == {"warn", "info"}
    clean = sources.build(samples.facts())
    assert _node(clean, "vault_personal")["state"] == "ok" and not any(q["node"] == "vault_personal" for q in clean["quests"])


def _vault_quests(graph: dict, node_id: str = "vault_personal") -> list[dict]:
    return [q for q in graph["quests"] if q["node"] == node_id]


def test_a_clone_behind_its_remote_is_a_warning_with_the_count_on_the_tile():
    facts = samples.facts()
    facts["personal_vault"].update(behind=46, dirty=True)
    graph = sources.build(facts)
    tile = _node(graph, "vault_personal")
    assert tile["state"] == "warn" and _edge(graph, "vault_personal", "gh_personal")["state"] == "warn"
    assert tile["sub"] == "↑0 ↓46 · 有改动"
    assert ["落后远端的提交", "46 个"] in tile["facts"]
    assert any(q["sev"] == "warn" and "46" in q["text"] for q in _vault_quests(graph))


@pytest.mark.parametrize("change", [{"checked_age_s": 9 * 86400}, {"checked_age_s": None, "checked_at": ""},
                                    {"check_failed": True}])
def test_a_clone_nobody_compared_with_the_remote_lately_is_unknown_not_green(change):
    """没联网核对过就不许显示绿色：领先 0、落后 0 只是按上次核对时远端的样子算出来的。"""
    facts = samples.facts()
    facts["personal_vault"].update(change)
    graph = sources.build(facts)
    assert _node(graph, "vault_personal")["state"] == "unknown"
    assert _edge(graph, "vault_personal", "gh_personal")["state"] == "unknown"
    quest, = _vault_quests(graph)
    assert quest["sev"] == "unknown"
    assert quest["action"] == {"name": "check_remote", "words": "check", "ask": False, "body": {"repo": "personal"}}
    fresh = sources.build(samples.facts())
    assert _node(fresh, "vault_personal")["state"] == "ok" and _vault_quests(fresh) == []


def test_the_tile_says_when_the_clone_last_met_its_remote():
    facts = samples.facts()
    tile = _node(sources.build(facts), "vault_personal")
    assert tile["sub"] == "↑0 ↓0" and tile["lines"] == ["核对于 01-02 03:04"]
    assert ["上次和远端核对", "2026-01-02 03:04"] in tile["facts"]
    facts["personal_vault"].update(check_failed=True)
    assert _node(sources.build(facts), "vault_personal")["lines"] == ["上次核对没连上"]
    facts["personal_vault"].update(check_failed=False, checked_at="", checked_age_s=None)
    assert _node(sources.build(facts), "vault_personal")["lines"] == ["还没和远端核对过"]


def test_a_known_gap_outranks_a_stale_check_and_still_offers_the_check():
    facts = samples.facts()
    facts["personal_vault"].update(behind=3, checked_age_s=9 * 86400)
    graph = sources.build(facts)
    assert _node(graph, "vault_personal")["state"] == "warn"
    assert {q["sev"] for q in _vault_quests(graph)} == {"warn", "unknown"}
    buttons = {q["sev"]: q["action"]["name"] for q in _vault_quests(graph) if "action" in q}
    assert buttons == {"unknown": "check_remote", "warn": "sync_vault"}, "太久没核对的那条给核对，落后的那条给同步"


@pytest.mark.parametrize("gap", [{"behind": 46}, {"unpushed": 2}])
def test_a_clone_with_a_known_gap_offers_the_sync_and_can_still_be_checked_from_its_tile(gap):
    """刚核对完、发现落后 46 个：那条「太久没核对」的待处理没了。有差距的那条给「现在同步」；想只再看一眼，
    磁贴详情里「现在核对」一直都在。"""
    facts = samples.facts()
    facts["personal_vault"].update(gap)
    graph = sources.build(facts)
    quest, = _vault_quests(graph)
    assert quest["sev"] == "warn" and quest["action"] == {"name": "sync_vault", "words": "sync", "body": {"repo": "personal"}}
    assert _node(graph, "vault_personal")["actions"] == [{"name": "check_remote", "words": "check", "ask": False, "body": {"repo": "personal"}}, {"name": "sync_vault", "words": "sync", "body": {"repo": "personal"}},
                                                         {"name": "open_report", "words": "activity", "ask": False, "body": {"report": "activity"}}]
    facts["work_vault"].update(gap)
    work = sources.build(facts)
    assert all("action" not in q for q in _vault_quests(work, "vault_work")), "公司侧的 git 在 WSL 里：页面上既不能核对也不能同步"
    assert [a["name"] for a in _node(work, "vault_work")["actions"]] == ["open_report"], "只能开时间轴"


def test_a_sync_that_backed_out_of_a_conflict_is_explained_until_the_two_sides_are_reconciled():
    """冲突之后克隆是「两边各多几个提交」。只看 ↑1 ↓47 不知道该怎么办：待处理里要说上次同步撞了冲突、已经撤回、下一步做什么。"""
    facts = samples.facts()
    facts["personal_vault"].update(unpushed=1, behind=47)
    facts["vault_sync"] = {"personal": {"at": "2026-11-22 17:00:00", "result": "needs_you", "conflicts": 1}}
    graph = sources.build(facts)
    conflict = next(q for q in _vault_quests(graph) if "冲突" in q["text"])
    assert conflict["sev"] == "warn" and "1 个文件" in conflict["text"] and "action" not in conflict
    assert ["上次同步", "2026-11-22 17:00 · 有冲突，已撤回"] in _node(graph, "vault_personal")["facts"]
    facts["personal_vault"].update(unpushed=0, behind=0)                    # 用户自己解决并推上去了：这条不再提
    assert not any("冲突" in q["text"] for q in _vault_quests(sources.build(facts)))


@pytest.mark.parametrize(("last", "words"), [
    ({"at": "2026-11-22 17:00:00", "result": "ok", "pulled": 46, "pushed": 1}, "2026-11-22 17:00 · 拉 46 推 1"),
    ({"at": "2026-11-22 17:00:00", "result": "noop"}, "2026-11-22 17:00 · 没有变化"),
    ({"at": "2026-11-22 17:00:00", "result": "failed"}, "2026-11-22 17:00 · 没办成"),
    ({"at": "2026-11-22 17:00:00", "result": "needs_you", "blocked": "in_progress"}, "2026-11-22 17:00 · 克隆在半截状态，没有动它"),
    (None, "")])
def test_the_tile_says_how_the_last_sync_went(last, words):
    facts = samples.facts()
    facts["vault_sync"] = {"personal": last}
    rows = [value for label, value in _node(sources.build(facts), "vault_personal")["facts"] if label == "上次同步" and value]
    assert rows == ([words] if words else []), "没同步过：这一行是空的，页面不画空行"


# ───────────────────────── 定时同步的磁贴：节奏、上次、历史条、迟了 ─────────────────────────

def _scheduled(*, enabled=True, mode="auto", age=600, runs=None, **settings) -> dict:
    facts = samples.facts()
    facts["features"]["vault_sync"] = {"enabled": enabled, "model": "", "effort": "", "when": "", "every_minutes": 60, "prompt_chars": 0,
                                       "writes": [["vault_personal", "github"]]}
    row = lambda at, result, trigger="schedule", **effect: {  # noqa: E731
        "at": f"2026-11-22 {at}", "job": "vault_sync", "trigger": trigger, "result": result,
        "effects": [{"kind": "git", "op": "sync", "repo": "personal", **effect}]}
    default = [row("13:00:00", "ok", pulled=3, pushed=1), row("12:00:00", "noop"), row("11:00:00", "needs_you", conflicts=1),
               row("10:05:00", "failed", "idle")]
    facts["vault_schedule"] = {"settings": {"enabled": enabled, "mode": mode, "interval_minutes": 60, "idle_minutes": 5, **settings},
                               "runs": default if runs is None else runs, "last_age_s": age}
    return sources.build(facts)


def test_the_schedule_tile_shows_its_rhythm_its_last_run_and_a_strip_of_recent_runs():
    tile = _node(_scheduled(), "f_vault_sync")
    assert tile["title"] == "知识库定时同步" and tile["state"] == "ok" and tile["size"] == "tall"
    assert tile["sub"] == "每 60 分钟 · 自动提交" and tile["lines"] == ["上次 13:00"]
    assert [(item["name"], item["state"]) for item in tile["items"]] == [
        ("11-22 13:00", "ok"), ("11-22 12:00", "unknown"), ("11-22 11:00", "warn"), ("11-22 10:05", "bad")], "新的在前：有变化绿、没事灰、等你琥珀、失败红"
    assert tile["items"][0]["detail"] == "定时 · 拉 3 · 推 1" and tile["items"][3]["detail"].startswith("停笔后 · ")
    assert ["做到哪一步", "自动提交"] in tile["facts"] and ["每隔多久", "每 60 分钟"] in tile["facts"] and ["停笔后同步", "停笔 5 分钟后"] in tile["facts"]
    assert any(label == "上次运行" and value.startswith("2026-11-22 13:00 · ") for label, value in tile["facts"])
    assert tile["settings"] == "vault_sync", "磁贴上有「设置」按钮，翻到这一组"


def test_the_line_from_the_schedule_to_the_clone_follows_the_schedule_not_the_hooks():
    """实机上见过这条线被画成断开：联动那几块磁贴的线看的是 hooks 在不在，定时同步不靠 hooks。"""
    assert _edge(_scheduled(), "f_vault_sync", "vault_personal")["state"] == "ok"
    assert _edge(_scheduled(enabled=False), "f_vault_sync", "vault_personal")["state"] == "off"
    assert _edge(_scheduled(age=3 * 3600), "f_vault_sync", "vault_personal")["state"] == "warn", "迟了：线跟着琥珀"
    hooks = sources.build(samples.facts(win=samples.home(hooks={"Stop": {"total": 1, "fish": 0}})))
    assert _edge(hooks, "f_link_win", "set_win")["state"] == "broken", "联动的线照旧看 hooks"


def test_a_schedule_that_has_missed_two_rounds_is_late_and_says_so():
    """该跑没跑要有人看得见：个人简报曾经停了九天没人知道。"""
    graph = _scheduled(age=2 * 3600 + 1)
    tile = _node(graph, "f_vault_sync")
    assert tile["state"] == "warn" and tile["lines"] == ["迟了"]
    quest, = [q for q in graph["quests"] if q["node"] == "f_vault_sync"]
    assert quest["sev"] == "warn" and "2026-11-22 13:00" in quest["text"]
    on_time = _scheduled(age=2 * 3600)
    assert _node(on_time, "f_vault_sync")["state"] == "ok" and not any(q["node"] == "f_vault_sync" for q in on_time["quests"])


def test_a_schedule_that_is_switched_off_is_never_late_but_keeps_its_history():
    graph = _scheduled(enabled=False, age=9 * 86400)
    tile = _node(graph, "f_vault_sync")
    assert tile["state"] == "off" and len(tile["items"]) == 4 and not any(q["node"] == "f_vault_sync" and q["sev"] == "warn" for q in graph["quests"])


def test_a_schedule_that_never_ran_says_so_and_watch_mode_does_not_claim_to_follow_edits():
    tile = _node(_scheduled(runs=[], age=None, mode="watch"), "f_vault_sync")
    assert tile["lines"] == ["还没跑过"] and tile["sub"] == "每 60 分钟 · 只看不动" and "items" not in tile
    assert ["停笔后同步", "不看停笔"] in tile["facts"] and ["上次运行", "还没跑过"] in tile["facts"]


def test_the_buttons_are_on_the_tile_even_when_there_is_nothing_to_do():
    graph = sources.build(samples.facts())
    assert [a["name"] for a in _node(graph, "vault_personal")["actions"]] == ["check_remote", "sync_vault", "open_report"]
    assert _vault_quests(graph) == []


def test_uncommitted_changes_say_how_many_files_and_deletions_and_offer_the_sync():
    """「现在同步」会把它们提交掉：点之前要看得到是几个文件、有没有删除。"""
    facts = samples.facts()
    facts["personal_vault"].update(dirty=True, changes=3, deletions=1)
    quest, = _vault_quests(sources.build(facts))
    assert quest["sev"] == "info" and quest["text"] == "handbook 克隆：3 个文件有没提交的改动，其中删除 1 个" and quest["action"]["name"] == "sync_vault"
    facts["personal_vault"].update(deletions=0)
    assert _vault_quests(sources.build(facts))[0]["text"] == "handbook 克隆：3 个文件有没提交的改动"
    facts["personal_vault"].update(behind=2)
    buttons = [q["sev"] for q in _vault_quests(sources.build(facts)) if "action" in q]
    assert buttons == ["warn"], "同步的按钮只出一个，挂在落后那条上"


def test_the_work_clone_shows_the_same_truth_but_cannot_be_checked_from_the_page():
    """公司侧的 git 在 WSL 里（SSH 密钥只在那边）：第一期只给个人侧的克隆「现在核对」。"""
    facts = samples.facts()
    facts["work_vault"].update(checked_age_s=9 * 86400)
    graph = sources.build(facts)
    assert _node(graph, "vault_work")["state"] == "unknown" and _edge(graph, "vault_work", "gh_work")["state"] == "unknown"
    quest, = _vault_quests(graph, "vault_work")
    assert quest["sev"] == "unknown" and "action" not in quest


@pytest.mark.parametrize("language", ["zh", "en"])
def test_storage_text_exists_in_both_languages(language):
    """``t()`` 找不到键会把键名原样返回：图里出现键的样子就是字表缺了一条。"""
    i18n.set_language(language)
    for backup in (None, {"auto": True, "repo": "acme/handbook", "backed_up_at": "2026-01-02 03:04", "error": "x"},
                   {"auto": True, "repo": "a/b", "backed_up_at": "", "paused": True}):
        facts = samples.facts(backup=backup, unknown=["leftover.md"])
        facts["personal_vault"].update(unpushed=1, behind=2, dirty=True, checked_age_s=9 * 86400)
        facts["work_vault"].update(check_failed=True)
        dumped = json.dumps(sources.build(facts), ensure_ascii=False)
        assert not _MISSING_KEY.search(dumped), _MISSING_KEY.search(dumped)
        never = samples.facts()
        never["personal_vault"].update(checked_at="", checked_age_s=None)
        assert not _MISSING_KEY.search(json.dumps(sources.build(never), ensure_ascii=False))
    without = samples.facts()
    without.pop("storage")                                               # 老的事实（没有存储那一段）也画得出来
    assert not _MISSING_KEY.search(json.dumps(sources.build(without), ensure_ascii=False))
