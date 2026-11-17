# -*- coding: utf-8 -*-
"""配置全景：连接器详情——每个 AI 连了什么、连到哪、是远程服务还是本地命令、什么状态、上次什么时候探的。

探针读真的文件（临时目录）和一段假的 ``claude mcp list`` 输出；图那一半喂虚构事实。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from pet import i18n
from pet.panorama import claude_home_probe, sources
from tests import panorama_samples as samples

SECRET = "sk-test-not-a-real-key-0123456789abcd"
_MISSING_KEY = re.compile(r"panorama\.|stores\.(root\.|[a-z_]+\.(name|holds|why))")


@pytest.fixture(autouse=True)
def _chinese():
    i18n.set_language("zh")
    yield
    i18n.set_language("zh")


def _node(graph: dict, node_id: str) -> dict:
    return next(n for n in graph["nodes"] if n["id"] == node_id)


def _item(node: dict, name: str) -> dict:
    return next(i for i in node["items"] if i["name"] == name)


# ───────────────────────── 探针：claude mcp list ─────────────────────────

MCP_LIST = f"""Checking MCP server health...

claude.ai Docs: https://docs.example/mcp?access_token={SECRET} - ✔ Connected
claude.ai Tickets: https://user:{SECRET}@tickets.example/sse - ! Needs authentication
acme-tools: npx -y @acme/tools --api-key {SECRET} --region eu - ✘ Failed to connect
plugin:notes:notes: uvx notes-server NOTES_TOKEN={SECRET} --port 8080 - ✔ Connected
"""


def test_mcp_list_rows_say_where_each_connector_points_and_what_kind_it_is():
    rows = {row["name"]: row for row in claude_home_probe.parse_mcp_list(MCP_LIST)}
    assert (rows["claude.ai Docs"]["kind"], rows["claude.ai Docs"]["target"]) == ("remote", "https://docs.example/mcp?…")
    assert (rows["claude.ai Tickets"]["kind"], rows["claude.ai Tickets"]["target"]) == ("remote", "https://tickets.example/sse")
    assert (rows["acme-tools"]["kind"], rows["acme-tools"]["target"]) == ("local", "npx -y @acme/tools --api-key *** --region eu")
    assert rows["plugin:notes:notes"]["target"] == "uvx notes-server NOTES_TOKEN=*** --port 8080"
    assert [rows[name]["state"] for name in ("claude.ai Docs", "claude.ai Tickets", "acme-tools")] == ["ok", "auth", "bad"]


def test_no_key_from_a_command_line_or_an_address_leaves_the_probe():
    assert SECRET not in json.dumps(claude_home_probe.parse_mcp_list(MCP_LIST))


# ───────────────────────── 探针：~/.claude.json 里登记的 MCP 服务器 ─────────────────────────

def _state() -> dict:
    return {
        "mcpServers": {
            "acme-tools": {"type": "stdio", "command": "npx", "args": ["-y", "@acme/tools", "--token", SECRET], "env": {"ACME_TOKEN": SECRET, "REGION": "eu"}},
            "wiki": {"type": "http", "url": f"https://wiki.example/mcp?key={SECRET}", "headers": {"Authorization": f"Bearer {SECRET}"}},
            "bare": {"command": "bare-server"},
            "broken": "not a dict",
        },
        "projects": {
            "/home/dev/work/carrot": {"mcpServers": {"carrot-db": {"command": "pg-mcp", "args": [f"PGPASSWORD={SECRET}"]}}},
            "/home/dev/work/empty": {"mcpServers": {}},
        },
    }


def test_registered_servers_are_listed_with_kind_target_and_the_names_of_their_variables():
    rows = {row["name"]: row for row in claude_home_probe.mcp_detail(_state())}
    assert set(rows) == {"acme-tools", "wiki", "bare", "carrot-db"}
    assert rows["acme-tools"] == {"name": "acme-tools", "kind": "stdio", "target": "npx -y @acme/tools --token ***",
                                  "env": ["ACME_TOKEN", "REGION"], "project": ""}
    assert rows["wiki"] == {"name": "wiki", "kind": "http", "target": "https://wiki.example/mcp?…", "env": ["Authorization"], "project": ""}
    assert rows["bare"]["kind"] == "stdio" and rows["bare"]["target"] == "bare-server" and rows["bare"]["env"] == []
    assert rows["carrot-db"]["project"] == "/home/dev/work/carrot" and rows["carrot-db"]["target"] == "pg-mcp PGPASSWORD=***"
    assert SECRET not in json.dumps(list(rows.values()))


def test_probe_reports_the_servers_and_when_it_looked(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude.json").write_text(json.dumps(_state()), encoding="utf-8")
    out = claude_home_probe.probe(tmp_path)
    assert [row["name"] for row in out["mcp_detail"]] == ["acme-tools", "bare", "wiki", "carrot-db"]     # 用户级的在前，项目级的在后
    assert out["mcp_servers"] == ["acme-tools", "bare", "broken", "wiki"]                                # 旧字段不变
    assert re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", out["probed_at"])
    assert out["mcp_probed_at"] == ""                                                                    # 没让它跑 claude mcp list
    assert SECRET not in json.dumps(out)


def test_an_empty_or_broken_state_file_gives_no_servers(tmp_path):
    assert claude_home_probe.mcp_detail({}) == [] and claude_home_probe.mcp_detail({"mcpServers": [], "projects": "x"}) == []
    assert claude_home_probe.probe(tmp_path)["mcp_detail"] == []


# ───────────────────────── 图 ─────────────────────────

def test_each_connector_says_where_it_points_what_kind_it_is_and_when_it_was_checked():
    graph = sources.build(samples.facts())
    docs = _item(_node(graph, "conn_w_ok"), "Docs")
    assert dict(docs["more"]) == {"连到哪": "https://docs.acme.example/mcp", "类型": "远程服务", "上次探测": "2026-01-02 03:04:11"}
    tickets = _item(_node(graph, "conn_w_rest"), "Tickets")
    assert dict(tickets["more"])["连到哪"] == "https://tickets.acme.example/sse" and tickets["state"] == "auth"
    assert ["上次探测", "2026-01-02 03:04:11"] in _node(graph, "conn_w_ok")["facts"]


def test_registered_servers_get_one_line_each_with_command_and_variable_names():
    graph = sources.build(samples.facts())
    tile = _node(graph, "mcp_wsl")
    row = _item(tile, "acme-tools")
    assert dict(row["more"]) == {"类型": "本地命令（stdio）", "连到哪": "npx -y @acme/tools --api-key ***", "环境变量": "ACME_TOKEN"}
    assert row["detail"] == "本地命令" and ["上次探测", "2026-01-02 03:04:05"] in tile["facts"]


def test_this_machine_gets_a_tile_for_its_servers_only_when_it_has_some():
    assert not any(n["id"] == "mcp_win" for n in sources.build(samples.facts())["nodes"])
    win = samples.home()
    win["mcp_detail"] = [{"name": "local-notes", "kind": "http", "target": "http://127.0.0.1:9000/mcp", "env": [], "project": "C:/Users/dev/tomato"}]
    graph = sources.build(samples.facts(win=win))
    row = _item(_node(graph, "mcp_win"), "local-notes")
    assert dict(row["more"]) == {"类型": "远程服务（http）", "连到哪": "http://127.0.0.1:9000/mcp", "只在这个项目": "C:/Users/dev/tomato"}
    assert any(e["from"] == "cc_win" and e["to"] == "mcp_win" and e["line"] == "connector" for e in graph["edges"])


def test_each_entry_point_says_when_it_was_last_looked_at_and_when_that_is_stale():
    graph = sources.build(samples.facts())
    assert ["上次探测", "2026-01-02 03:04:05"] in _node(graph, "cc_wsl")["facts"]
    assert ["上次探测", "2026-01-02 03:04:05"] in _node(graph, "cc_win")["facts"]
    stale = samples.facts()
    stale["refreshing"] = True                                           # 垫着上一轮的 WSL 结果，新的还在路上
    facts = dict(map(tuple, _node(sources.build(stale), "cc_wsl")["facts"]))
    assert facts["上次探测"].startswith("2026-01-02 03:04:05") and "正在重新探测" in facts["上次探测"]


def test_connectors_this_machine_cannot_check_say_so_instead_of_showing_a_time():
    graph = sources.build(samples.facts())
    rest = _node(graph, "conn_p_rest")
    assert not any(label == "上次探测" for label, _ in rest["facts"])
    assert all("more" not in item for item in rest["items"])


def test_older_probe_results_without_the_new_fields_still_draw():
    wsl = samples.wsl_home()
    for key in ("mcp_detail", "probed_at", "mcp_probed_at"):
        wsl.pop(key)
    for row in wsl["connectors"]:
        row.pop("target"), row.pop("kind")
    graph = sources.build(samples.facts(wsl=wsl))
    assert "more" not in _item(_node(graph, "conn_w_ok"), "Docs")
    assert _node(graph, "mcp_wsl")["sub"] == "acme-tools" and "items" not in _node(graph, "mcp_wsl")


@pytest.mark.parametrize("language", ["zh", "en"])
def test_connector_text_exists_in_both_languages(language):
    i18n.set_language(language)
    win = samples.home()
    win["mcp_detail"] = [{"name": "x", "kind": "sse", "target": "https://x.example", "env": ["K"], "project": "p"}]
    facts = samples.facts(win=win)
    facts["refreshing"] = True
    assert not _MISSING_KEY.search(json.dumps(sources.build(facts), ensure_ascii=False))


def test_sample_facts_stay_in_step_with_the_real_probe(tmp_path):
    """样例里连接器那几项的键，和真探针产出的一样（改了探针忘了改样例，图那一半的测试就测了个假东西）。"""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude.json").write_text(json.dumps(_state()), encoding="utf-8")
    real = claude_home_probe.probe(Path(tmp_path))
    sample = samples.wsl_home()
    assert set(real["mcp_detail"][0]) == set(sample["mcp_detail"][0])
    assert set(claude_home_probe.parse_mcp_list(MCP_LIST)[0]) == set(sample["connectors"][0])
    assert {"probed_at", "mcp_probed_at"} <= set(real) and {"probed_at", "mcp_probed_at"} <= set(sample)
