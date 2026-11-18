# -*- coding: utf-8 -*-
"""配置全景：事实 → 图。喂虚构事实，看图上的节点、连线状态和待处理。"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from pet import i18n
from pet.panorama import features, sources
from pet.panorama.model import EDGE_STATES, NODE_STATES, Graph
from tests import panorama_samples as samples


@pytest.fixture(autouse=True)
def _chinese():
    i18n.set_language("zh")
    yield
    i18n.set_language("zh")


def _edge(graph: dict, source: str, target: str) -> dict:
    return next(e for e in graph["edges"] if e["from"] == source and e["to"] == target)


def _node(graph: dict, node_id: str) -> dict:
    return next(n for n in graph["nodes"] if n["id"] == node_id)


def _ids(graph: dict) -> set:
    return {n["id"] for n in graph["nodes"]}


def test_every_line_joins_two_tiles_that_exist_and_states_are_known():
    graph = sources.build(samples.facts())
    ids = _ids(graph)
    assert all(e["from"] in ids and e["to"] in ids for e in graph["edges"])
    assert {e["state"] for e in graph["edges"]} <= set(EDGE_STATES)
    assert {n["state"] for n in graph["nodes"]} <= set(NODE_STATES)
    assert all(q["node"] in ids for q in graph["quests"])
    regions = {r["id"] for r in graph["regions"]}
    assert all(n["region"] in regions for n in graph["nodes"])


def test_personal_features_run_to_the_service_in_use_and_follow_its_health():
    graph = sources.build(samples.facts(health="ok"))
    assert _edge(graph, "f_chat", "prov_api-1")["state"] == "live"
    assert _node(graph, "prov_api-1")["state"] == "live"
    assert not any(e["to"] == "prov_api-2" for e in graph["edges"])          # 不是使用中的那个，没有线
    broken = sources.build(samples.facts(health="bad"))
    assert _edge(broken, "f_chat", "prov_api-1")["state"] == "broken"
    assert any(q["sev"] == "bad" and q["node"] == "prov_api-1" for q in broken["quests"])
    unchecked = sources.build(samples.facts(health="unknown"))
    assert _edge(unchecked, "f_chat", "prov_api-1")["state"] == "unknown"


def test_a_feature_that_is_off_keeps_its_tile_but_every_line_goes_faint():
    cfg = samples.all_on_config()
    cfg["work_briefing"]["enabled"] = False
    cfg["memory_distill"]["enabled"] = False                                   # 总开关关了，公司侧也跟着关
    graph = sources.build(samples.facts(cfg=cfg))
    assert _node(graph, "f_briefing")["state"] == "off"
    assert _edge(graph, "f_briefing", "cc_wsl")["state"] == "off"
    assert _node(graph, "f_distill_work")["state"] == "off"
    assert {e["state"] for e in graph["edges"] if e["from"] == "f_distill_personal"} == {"off"}
    assert any(q["sev"] == "info" and q["node"] == "pet" for q in graph["quests"])


def test_a_feature_whose_settings_moved_to_the_page_opens_them_there_instead_of_naming_a_settings_page():
    """设置表里登记了的功能：磁贴带着那一组的 id（页面上出「设置」按钮），不再写「去设置窗口哪一页」。"""
    from pet import settings_table

    graph = sources.build(samples.facts())
    moved = {group.config_key: group.id for group in settings_table.GROUPS}
    for feature in features.FEATURES:
        node = _node(graph, f"f_{feature.id}")
        group_id = feature.settings_group or moved.get(feature.config_key)
        if group_id:
            assert node.get("settings") == group_id and "page" not in node, feature.id
            assert not feature.page, f"{feature.id}: 设置已经搬到页面上，别再指向设置窗口"
        else:
            assert "settings" not in node, feature.id
    assert _node(graph, "f_briefing")["settings"] == "work_briefing"
    assert _node(graph, "f_slack")["settings"] == "slack_watch"
    assert _node(graph, "f_notes")["settings"] == "work_notes"
    assert _node(graph, "f_assistant")["settings"] == "personal"
    assert _node(graph, "f_distill_personal")["settings"] == "distill_personal"
    assert _node(graph, "f_distill_work")["settings"] == "distill_work"           # 同一个配置键下的另一组
    assert _node(graph, "f_screen")["page"]                                    # 还没搬的照旧
    assert all(settings_table.group(f.settings_group) for f in features.FEATURES if f.settings_group)


def test_session_link_line_is_broken_when_the_switch_is_on_but_the_hooks_are_gone():
    graph = sources.build(samples.facts(wsl=samples.wsl_home(hooks={"Stop": {"total": 1, "fish": 0}})))
    assert _node(graph, "set_wsl")["state"] == "bad"
    assert _edge(graph, "f_link_wsl", "set_wsl")["state"] == "broken"
    assert any(q["sev"] == "bad" and q["node"] == "set_wsl" for q in graph["quests"])
    assert _edge(graph, "f_link_win", "set_win")["state"] == "live"            # 本机那边 hooks 在
    cfg = samples.all_on_config()
    cfg["agent_link"]["claude_wsl"] = False                                    # 开关本来就关着：不算坏
    quiet = sources.build(samples.facts(cfg=cfg, wsl=samples.wsl_home(hooks={})))
    assert _node(quiet, "set_wsl")["state"] == "off"
    assert not any(q["node"] == "set_wsl" for q in quiet["quests"])


def test_connectors_split_into_a_flowing_tile_and_a_tile_that_needs_attention():
    graph = sources.build(samples.facts())
    assert [i["name"] for i in _node(graph, "conn_w_ok")["items"]] == ["Docs"]
    assert _edge(graph, "cc_wsl", "conn_w_ok")["state"] == "live"
    assert _node(graph, "conn_w_rest")["state"] == "warn"
    assert _edge(graph, "cc_wsl", "conn_w_rest")["state"] == "warn"
    assert any(q["sev"] == "warn" and q["node"] == "conn_w_rest" for q in graph["quests"])
    # 个人账号的 connector 本机读不到现状：只有一块「探测不到」，线是点线
    assert "conn_p_ok" not in _ids(graph)
    assert _node(graph, "conn_p_rest")["state"] == "unknown"
    assert _edge(graph, "desktop", "conn_p_rest")["state"] == "unknown"


def test_without_wsl_the_work_side_is_simply_not_on_the_map():
    graph = sources.build(samples.facts(wsl="absent"))
    assert {r["zone"] for r in graph["regions"]} == {"personal"}
    assert not any(n["region"] in ("wsl", "cloud_work") for n in graph["nodes"])
    assert not any(e["to"] == "cc_wsl" for e in graph["edges"])                # 公司线的目标没了，线被丢掉而不是悬空
    assert graph["meta"]["pending"] is False


def test_wsl_failure_and_wsl_still_being_checked_are_told_apart():
    failed = sources.build(samples.facts(wsl="error"))
    assert _node(failed, "cc_wsl")["state"] == "bad"
    assert _edge(failed, "f_notes", "cc_wsl")["state"] == "broken"
    assert any(q["sev"] == "bad" and q["node"] == "cc_wsl" for q in failed["quests"])
    pending = sources.build(samples.facts(wsl="pending"))
    assert pending["meta"]["pending"] is True
    assert _node(pending, "cc_wsl")["state"] == "unknown"
    assert _edge(pending, "f_notes", "cc_wsl")["state"] == "unknown"
    assert not any(q["node"] == "cc_wsl" for q in pending["quests"])


def test_a_service_without_a_key_is_broken_whatever_the_health_check_said():
    graph = sources.build(samples.facts(providers=[samples.provider(key=False)]))
    assert _node(graph, "prov_api-1")["state"] == "bad"
    assert any(q["sev"] == "bad" and q["node"] == "prov_api-1" for q in graph["quests"])


def test_feature_table_reads_effective_settings_not_raw_keys():
    rows = features.read_all({})                                               # 空配置：全走各功能自己的默认
    assert rows["briefing"]["enabled"] is False and rows["notes"]["enabled"] is True
    assert rows["distill_work"]["enabled"] is False                            # 总开关默认关
    assert rows["link_win"]["enabled"] is True
    on = features.read_all({"memory_distill": {"enabled": True, "work_distill": False, "work_mirror_to_vault": True}})
    assert on["distill_personal"]["enabled"] is True and on["distill_work"]["enabled"] is False
    assert ["vault_work", "memory"] in on["distill_work"]["writes"]
    assert features.read_all({"slack_watch": {"enabled": True, "interval_minutes": 20}})["slack"]["every_minutes"] == 20
    assert {f.route for f in features.FEATURES} <= set(features.ROUTES)


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("wsl", ["ready", "absent", "error", "pending"])
def test_every_string_the_map_uses_exists_in_both_languages(language, wsl):
    """``t()`` 找不到键时会把键名原样返回：图里出现 ``panorama.`` 就是字表缺了一条。"""
    i18n.set_language(language)
    cfg = samples.all_on_config()
    cfg["slack_watch"]["enabled"] = False
    for health in ("ok", "bad"):
        for providers in (None, [samples.provider(key=False)], []):
            graph = sources.build(samples.facts(cfg=cfg, health=health, wsl=wsl, providers=providers))
            assert "panorama." not in json.dumps(graph, ensure_ascii=False)


def test_every_literal_key_in_the_package_is_in_both_tables():
    package = Path(sources.__file__).parent
    used = set()
    for path in package.glob("*.py"):
        used.update(re.findall(r'(?<![A-Za-z_])L\(\s*"([a-z0-9_.]+)"', path.read_text(encoding="utf-8")))
    assert len(used) > 100
    for language in ("zh", "en"):
        table = i18n.table(language)
        assert sorted(k for k in used if sources.PREFIX + k not in table) == []


def test_graph_refuses_unknown_states_and_duplicate_tiles():
    g = Graph()
    g.node("a", "win", 0, "entry", "A")
    with pytest.raises(ValueError):
        g.node("a", "win", 0, "entry", "again")
    with pytest.raises(ValueError):
        g.node("b", "win", 0, "entry", "B", state="fine")
    with pytest.raises(ValueError):
        g.edge("a", "b", "memory", "flowing")
    g.edge("a", "ghost", "memory")
    g.quest("info", "x", "ghost")
    out = g.to_dict()
    assert out["edges"] == [] and out["quests"] == []


def test_vault_tiles_are_named_after_the_clone_folder():
    graph = sources.build(samples.facts())
    assert _node(graph, "vault_personal")["title"] == "handbook 克隆"
    assert _node(graph, "vault_work")["title"] == "field-notes 克隆"
    assert _node(graph, "gh_personal")["title"] == "GitHub · acme-home" and _node(graph, "gh_work")["title"] == "GitHub · acme-work"
