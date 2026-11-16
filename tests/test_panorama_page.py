# -*- coding: utf-8 -*-
"""配置全景：把页面自己的脚本真跑一遍（Qt 自带的 JS 引擎 + 一个极简的假 DOM）。

版面和走线都在页面脚本里算。这里不看像素，看脚本产出的标记：每个节点一块磁贴、每条线一条路径，
坐标里没有 NaN / undefined。脚本有语法错误、或者某种图（没装 WSL、WSL 还在探测）让走线算崩，这里会红。

``app.js``（画图）和 ``boot.js``（决定数据从哪来）分开跑：后者用同步的假 ``fetch`` / 假定时器，
把「取令牌 → 要数据 → 等新数据 → 连接断了」整条路走一遍。
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
  querySelectorAll: function () { return []; }, body: _el(), documentElement: {lang: ''}, title: '', visibilityState: 'visible'};
var addEventListener = function () {}, navigator = {};
"""

#: boot.js 的假环境：fetch 同步返回「像 Promise 的东西」，定时器只把回调存起来等测试去触发。
FAKE_BROWSER = """
var calls = [], timers = [], intervals = [], reloads = 0, replaced = [], started = [], store = {};
var sessionStorage = {getItem: function (k) { return k in store ? store[k] : null; }, setItem: function (k, v) { store[k] = v; }};
var history = {replaceState: function (a, b, url) { replaced.push(url); location.hash = ''; }};
var location = {hash: '', pathname: '/', reload: function () { reloads++; }};
var setTimeout = function (fn) { timers.push(fn); }, setInterval = function (fn) { intervals.push(fn); };
function settled(value, failed) {
  return {then: function (ok, err) {
    var handler = failed ? err : ok;
    if (!handler) return settled(value, failed);
    try { return settled(handler(value), false); } catch (e) { return settled(e, true); }
  }};
}
var responses = [];
var fetch = function (path, options) {
  calls.push({path: path, token: options.headers['X-Panorama-Token']});
  var r = responses.shift();
  if (!r) return settled(new Error('network'), true);
  return settled({ok: r.status === 200, status: r.status, json: function () { return r.data; }}, false);
};
function start(data) { started.push(data.revision === undefined ? 'embedded' : data.revision); }
function tick() { var fn = timers.shift(); fn(); }
"""


@pytest.fixture(scope="module")
def engine():
    app = QCoreApplication.instance() or QCoreApplication([])
    js = QJSEngine()
    yield js
    del js, app


def _evaluate(engine, script: str) -> dict:
    result = engine.evaluate("(function () {" + script + "})()")
    assert not result.isError(), f"{result.toString()} (line {result.property('lineNumber').toInt()})"
    return json.loads(result.toString())


def _run(engine, graph: dict) -> dict:
    data = json.dumps(render.page_data(graph), ensure_ascii=False)
    return _evaluate(engine, FAKE_DOM + render.asset("app.js").decode("utf-8") + f"\nvar size = start({data});"
                     "var el = document.getElementById;"
                     "return JSON.stringify({map: el('map').innerHTML, width: size.width, height: size.height, "
                     "detail: el('detail').innerHTML, pending: el('pending').hidden, quests: el('quests').innerHTML, "
                     "meta: el('meta').textContent});")


def _boot(engine, setup: str, steps: str = "") -> dict:
    """跑 boot.js。``setup`` 在它之前布置环境，``steps`` 在它之后推进定时器。"""
    return _evaluate(engine, FAKE_DOM + FAKE_BROWSER + setup + render.asset("boot.js").decode("utf-8") + steps +
                     "\nreturn JSON.stringify({calls: calls, timers: timers.length, intervals: intervals.length, reloads: reloads, "
                     "replaced: replaced, started: started, store: store, hash: location.hash, "
                     "lost: document.getElementById('lost').hidden === false, lang: document.documentElement.lang, "
                     "title: document.title});")


def _reply(revision: int, *, pending: bool = False, status: int = 200) -> str:
    data = {"revision": revision, "meta": {"pending": pending}, "page": {"lang": "en", "title": "Config map"}}
    return json.dumps({"status": status, "data": data})


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


# ---------------------------------------------------------------- boot.js：本机服务的页面

def test_served_page_takes_the_token_from_the_fragment_and_wipes_it_from_the_address_bar(engine):
    out = _boot(engine, f"location.hash = '#SECRET'; responses = [{_reply(1)}];")
    assert out["calls"] == [{"path": "/api/graph", "token": "SECRET"}]      # 令牌只走请求头
    assert out["replaced"] == ["/"] and out["hash"] == ""                  # 地址栏里不留令牌
    assert out["store"] == {"panorama-token": "SECRET"}
    assert out["started"] == [1] and not out["lost"]
    assert out["lang"] == "en" and out["title"] == "Config map"
    assert out["timers"] == 0                                              # 数据是完整的：不用再等


def test_reloading_the_tab_gets_the_token_back_from_session_storage(engine):
    out = _boot(engine, f"store['panorama-token'] = 'KEPT'; responses = [{_reply(3)}];")
    assert out["calls"] == [{"path": "/api/graph", "token": "KEPT"}] and out["replaced"] == [] and out["started"] == [3]


def test_served_page_waits_for_the_wsl_half_and_reloads_when_the_data_changes(engine):
    setup = f"location.hash = '#T'; responses = [{_reply(1, pending=True)}, {_reply(1, pending=True)}, {_reply(2)}];"
    waiting = _boot(engine, setup, "tick();")
    assert [c["path"] for c in waiting["calls"]] == ["/api/graph", "/api/graph"]
    assert waiting["reloads"] == 0 and waiting["timers"] == 1              # 还是那一份：接着等
    done = _boot(engine, setup, "tick(); tick();")
    assert done["reloads"] == 1 and done["timers"] == 0 and not done["lost"]


def test_served_page_gives_up_waiting_after_a_bounded_number_of_checks(engine):
    """肥鱼卡住或那一半永远探不完：页面不会无止境地问下去。"""
    setup = "location.hash = '#T'; responses = [];" + f"for (var i = 0; i < 200; i++) responses.push({_reply(1, pending=True)});"
    out = _boot(engine, setup, "var n = 0; while (timers.length && n < 500) { tick(); n++; }")
    assert len(out["calls"]) == 41 and out["timers"] == 0                  # 第一次 + 40 次


@pytest.mark.parametrize("first", [_reply(0, status=401), "null"])
def test_served_page_says_so_when_it_cannot_reach_the_fish(engine, first):
    """令牌作废（401）或连不上：亮出「连接断了」，不画半张图。"""
    out = _boot(engine, f"location.hash = '#OLD'; responses = [{first}];".replace("[null]", "[]"))
    assert out["lost"] and out["started"] == []


def test_served_page_tells_the_service_it_is_still_open_only_while_visible(engine):
    setup = f"location.hash = '#T'; responses = [{_reply(1)}, {json.dumps({'status': 200, 'data': {'ok': True}})}];"
    out = _boot(engine, setup, "document.visibilityState = 'hidden'; intervals[0](); "
                               "document.visibilityState = 'visible'; intervals[0](); intervals[0]();")
    assert out["intervals"] == 1
    assert [c["path"] for c in out["calls"]] == ["/api/graph", "/api/ping", "/api/ping"]   # 藏着的那次没问
    assert out["lost"]                                                     # 第二次探活没人应：服务已经停了


# ---------------------------------------------------------------- boot.js：离线快照

def test_snapshot_uses_the_embedded_data_and_never_calls_the_service(engine):
    out = _boot(engine, "var PANORAMA_DATA = {meta: {pending: false}};")
    assert out["started"] == ["embedded"] and out["calls"] == [] and out["timers"] == 0 and out["intervals"] == 0


def test_pending_snapshot_rereads_its_own_file_a_bounded_number_of_times(engine):
    setup = "var PANORAMA_DATA = {meta: {pending: true}};"
    first = _boot(engine, setup, "tick();")
    assert first["reloads"] == 1 and first["hash"] == "1"                 # 重读次数记在 # 后面
    assert _boot(engine, setup + "location.hash = '#40';")["timers"] == 0  # 到头了就不再排下一次
