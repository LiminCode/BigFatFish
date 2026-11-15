# -*- coding: utf-8 -*-
"""配置全景：图 → 自带数据的 HTML 文件。"""
from __future__ import annotations

import json
import re

import pytest

from pet import i18n
from pet.panorama import render, sources
from tests import panorama_samples as samples

CJK = re.compile(r"[一-鿿]")


@pytest.fixture(autouse=True)
def _chinese():
    i18n.set_language("zh")
    yield
    i18n.set_language("zh")


def _embedded(page: str) -> dict:
    line = next(l for l in page.splitlines() if l.startswith("const G = "))
    return json.loads(line[len("const G = "):].rstrip(";").replace("<\\/", "</"))


def test_page_carries_the_whole_graph_and_its_strings():
    graph = sources.build(samples.facts())
    page = render.render(graph)
    data = _embedded(page)
    assert [n["id"] for n in data["nodes"]] == [n["id"] for n in graph["nodes"]] and data["edges"] == graph["edges"]
    assert set(data["strings"]) == set(render.PAGE_KEYS) | {"state", "edge_state"}
    assert "2026-01-02 03:04:05" in data["meta"]["summary"] and "6.5" in data["meta"]["summary"]
    assert '<html lang="zh-CN">' in page and "__TITLE__" not in page and render.GRAPH_MARK not in page
    assert "http://" not in page and "https://" not in page.replace("https://api.acme.example", "").replace("https://github.com/", "")


def test_a_script_end_tag_inside_the_data_cannot_cut_the_page_short():
    graph = sources.build(samples.facts())
    graph["nodes"][0]["title"] = "</script><script>alert(1)</script>"
    page = render.render(graph)
    assert page.count("</script>") == 1                                        # 只有模板自己那一个
    assert _embedded(page)["nodes"][0]["title"] == "</script><script>alert(1)</script>"


def test_summary_says_when_the_wsl_half_is_not_in_yet():
    facts = samples.facts(wsl="pending")
    del facts["timing"]["wsl_s"]
    data = _embedded(render.render(sources.build(facts)))
    assert data["meta"]["pending"] is True and "WSL" not in data["meta"]["summary"]


def test_english_page_has_no_chinese_left_in_its_own_text():
    i18n.set_language("en")
    page = render.render(sources.build(samples.facts()))
    data = _embedded(page)
    assert '<html lang="en">' in page
    leftovers = [text for text in _strings(data) if CJK.search(text)]
    assert leftovers == ["连接成功"]                                            # 体检器给的结论原样转述，不归这张字表管


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def test_write_replaces_the_file_in_one_step(tmp_path):
    graph = sources.build(samples.facts())
    target = render.write(graph, tmp_path / "out")
    assert target == tmp_path / "out" / render.PAGE_NAME and _embedded(target.read_text(encoding="utf-8"))["nodes"]
    again = render.write(sources.build(samples.facts(wsl="absent")), tmp_path / "out")
    assert again == target and not list((tmp_path / "out").glob("*.tmp"))
    assert not any(n["region"] == "wsl" for n in _embedded(target.read_text(encoding="utf-8"))["nodes"])
