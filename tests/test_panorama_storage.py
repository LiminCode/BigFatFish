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
    graph = sources.build(samples.facts())
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


@pytest.mark.parametrize("language", ["zh", "en"])
def test_storage_text_exists_in_both_languages(language):
    """``t()`` 找不到键会把键名原样返回：图里出现键的样子就是字表缺了一条。"""
    i18n.set_language(language)
    for backup in (None, {"auto": True, "repo": "acme/handbook", "backed_up_at": "2026-01-02 03:04", "error": "x"},
                   {"auto": True, "repo": "a/b", "backed_up_at": "", "paused": True}):
        facts = samples.facts(backup=backup, unknown=["leftover.md"])
        facts["personal_vault"].update(unpushed=1, dirty=True)
        dumped = json.dumps(sources.build(facts), ensure_ascii=False)
        assert not _MISSING_KEY.search(dumped), _MISSING_KEY.search(dumped)
    without = samples.facts()
    without.pop("storage")                                               # 老的事实（没有存储那一段）也画得出来
    assert not _MISSING_KEY.search(json.dumps(sources.build(without), ensure_ascii=False))
