# -*- coding: utf-8 -*-
"""配置全景：把页面自己的脚本真跑一遍（Qt 自带的 JS 引擎 + 一个极简的假 DOM）。

版面和走线都在页面脚本里算。这里不看像素，看脚本产出的标记：每个节点一块磁贴、每条线一条路径，
坐标里没有 NaN / undefined。脚本有语法错误、或者某种图（没装 WSL、WSL 还在探测）让走线算崩，这里会红。
"""
from __future__ import annotations

import json
import re

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtQml import QJSEngine

from pet import i18n
from pet.panorama import render, sources
from tests import panorama_samples as samples

FAKE_DOM = """
var _els = {};
function _el() {
  return {style: {}, dataset: {}, clientWidth: 1600, hidden: true, textContent: '', placeholder: '', innerHTML: '',
    classList: {toggle: function () { return false; }, add: function () {}, remove: function () {}},
    addEventListener: function () {}, insertAdjacentHTML: function () {}, scrollIntoView: function () {},
    querySelectorAll: function () { return []; }, querySelector: function () { return null; }};
}
var document = {getElementById: function (id) { return _els[id] || (_els[id] = _el()); },
  querySelectorAll: function () { return []; }, body: _el()};
var addEventListener = function () {}, setTimeout = function () {}, location = {reload: function () {}}, navigator = {};
"""


@pytest.fixture(scope="module")
def engine():
    app = QCoreApplication.instance() or QCoreApplication([])
    js = QJSEngine()
    yield js
    del js, app


def _run(engine, graph: dict) -> dict:
    page = render.render(graph)
    script = page[page.index("<script>") + len("<script>"): page.rindex("</script>")]
    result = engine.evaluate("(function () {" + FAKE_DOM + script + "\nvar el = document.getElementById;"
                             "return JSON.stringify({map: el('map').innerHTML, width: W, height: H, detail: el('detail').innerHTML, "
                             "pending: el('pending').hidden, quests: el('quests').innerHTML, meta: el('meta').textContent});})()")
    assert not result.isError(), f"{result.toString()} (line {result.property('lineNumber').toInt()})"
    return json.loads(result.toString())


@pytest.mark.parametrize("wsl", ["ready", "absent", "error", "pending"])
def test_page_script_lays_out_every_tile_and_routes_every_line(engine, wsl):
    i18n.set_language("zh")
    graph = sources.build(samples.facts(wsl=wsl))
    out = _run(engine, graph)
    markup = out["map"]
    assert markup.count('class="tile ') == len(graph["nodes"])
    assert markup.count('<g class="edge ') == len(graph["edges"])
    assert "NaN" not in markup and "undefined" not in markup and "Infinity" not in markup
    assert out["width"] > 600 and out["height"] > 300
    assert markup.count('class="band"') == len({r["zone"] for r in graph["regions"]})     # 没装 WSL 就只有个人那一条带
    assert out["pending"] is (wsl != "pending")                                           # 还在探测时提示条露出来
    assert out["meta"] == render.summary(graph)


def test_every_tile_sits_inside_the_map_and_no_two_tiles_overlap(engine):
    i18n.set_language("zh")
    out = _run(engine, sources.build(samples.facts()))
    boxes = [tuple(float(v) for v in m) for m in
             re.findall(r'class="tile [^"]*" data-id="[^"]+" style="left:([\d.]+)px;top:([\d.]+)px;width:([\d.]+)px;height:([\d.]+)px', out["map"])]
    assert len(boxes) > 20
    for x, y, w, h in boxes:
        assert x >= 0 and y >= 0 and x + w <= out["width"] and y + h <= out["height"]
    for i, (x, y, w, h) in enumerate(boxes):
        for x2, y2, w2, h2 in boxes[i + 1:]:
            assert x + w <= x2 or x2 + w2 <= x or y + h <= y2 or y2 + h2 <= y


def test_page_text_follows_the_interface_language(engine):
    i18n.set_language("en")
    try:
        out = _run(engine, sources.build(samples.facts()))
    finally:
        i18n.set_language("zh")
    assert "How to read this map" in out["detail"] and "Snapshot" in out["meta"]
    assert not re.search(r"[一-鿿]", out["detail"] + out["meta"])
