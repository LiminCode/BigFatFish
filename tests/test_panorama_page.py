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
var _els = {}, _listeners = 0, _aborted = 0, _docListeners = {};
function _el() {
  return {style: {}, dataset: {}, clientWidth: 1600, hidden: true, textContent: '', placeholder: '', innerHTML: '', value: '',
    classList: {toggle: function () { return false; }, add: function () {}, remove: function () {}, contains: function () { return false; }},
    addEventListener: function () { _listeners++; }, insertAdjacentHTML: function () {}, scrollIntoView: function () {},
    querySelectorAll: function () { return []; }, querySelector: function () { return null; }};
}
var document = {getElementById: function (id) { return _els[id] || (_els[id] = _el()); },
  querySelectorAll: function () { return []; }, body: _el(), documentElement: {lang: ''}, title: '', visibilityState: 'visible',
  addEventListener: function (type, fn) { _docListeners[type] = fn; }};
var addEventListener = function () { _listeners++; }, navigator = {};
function AbortController() { this.signal = {}; this.abort = function () { _aborted++; }; }
"""

#: boot.js 的假环境：fetch 同步返回「像 Promise 的东西」，定时器只把回调存起来等测试去触发。
FAKE_BROWSER = """
var calls = [], timers = [], intervals = [], reloads = 0, replaced = [], started = [], disposed = [], store = {};
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
  if (r.hang) return {then: function () { return this; }};          // 服务把请求挂着：谁也不会被调到
  return settled({ok: r.status === 200, status: r.status, json: function () { return r.data; }}, false);
};
// 假的 start()：记下每次拿到的编号和 kept；返回的 view 记下谁被 dispose 了
function start(data, kept) {
  var n = started.length;
  started.push({revision: data.revision === undefined ? 'embedded' : data.revision, kept: kept === undefined ? null : kept});
  return {capture: function () { return {selected: 'seen-in-' + n}; }, dispose: function () { disposed.push(n); }};
}
function tick() { var fn = timers.shift(); fn(); }
"""

HANG = '{"hang": true}'
NOTHING_NEW = '{"status": 204}'


#: 跑完 start() 之后把页面上看得见的东西取回来
REPORT = ("var el = document.getElementById;"
          "return JSON.stringify({map: el('map').innerHTML, width: size.width, height: size.height, "
          "detail: el('detail').innerHTML, pending: el('pending').hidden, quests: el('quests').innerHTML, "
          "meta: el('meta').textContent});")


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
    return _evaluate(engine, FAKE_DOM + render.bundle(render.MODULES[:-1]) + f"\nvar size = start({data});" + REPORT)


def _boot(engine, setup: str, steps: str = "") -> dict:
    """跑 boot.js。``setup`` 在它之前布置环境，``steps`` 在它之后推进定时器。"""
    return _evaluate(engine, FAKE_DOM + FAKE_BROWSER + setup + render.bundle(("boot.js",)) + steps +
                     "\nreturn JSON.stringify({calls: calls, timers: timers.length, intervals: intervals.length, reloads: reloads, "
                     "replaced: replaced, started: started, disposed: disposed, store: store, hash: location.hash, "
                     "watching: Object.keys(_docListeners), "
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


# ---------------------------------------------------------------- 原地重画

def _redraw(engine, first: dict, second: dict, between: str) -> dict:
    """画 first，执行 ``between``（能用 ``view``），再按页面的顺序重画成 second：capture → dispose → start(新, kept)。"""
    one, two = (json.dumps(render.page_data(g), ensure_ascii=False) for g in (first, second))
    return _evaluate(engine, FAKE_DOM + render.bundle(render.MODULES[:-1]) + f"""
        var view = start({one}); var before = _listeners;
        {between}
        var kept = view.capture(); view.dispose();
        var size = start({two}, kept);
        var el = document.getElementById;
        return JSON.stringify({{kept: kept, aborted: _aborted, firstListeners: before, secondListeners: _listeners - before,
          detail: el('detail').innerHTML, map: el('map').innerHTML, query: el('q').value, pending: el('pending').hidden,
          after: size.capture()}});""")


def test_redraw_keeps_the_selected_node_and_shows_its_new_details(engine):
    i18n.set_language("zh")
    graph = sources.build(samples.facts(wsl="pending"))
    node = next(n for n in graph["nodes"] if n["region"] != "wsl" and n.get("facts"))
    out = _redraw(engine, graph, sources.build(samples.facts()), f"view.select({json.dumps(node['id'])});")
    assert out["kept"]["selected"] == node["id"] and out["after"]["selected"] == node["id"]
    assert node["title"] in out["detail"]                                # 详情是这个节点的，不是「怎么看这张图」
    assert out["pending"] is True                                        # 第一张图亮着的「还在探测」收起来了


def test_whatever_was_selected_while_waiting_is_still_selected_when_the_wsl_half_arrives(engine):
    """等 WSL 那一半的时候点了哪一块都行：那一半到了以后它仍然选中。靠的是节点标识在两张图里不变。"""
    i18n.set_language("zh")
    waiting, complete = sources.build(samples.facts(wsl="pending")), sources.build(samples.facts())
    assert {n["id"] for n in waiting["nodes"]} <= {n["id"] for n in complete["nodes"]}
    for node in waiting["nodes"]:
        out = _redraw(engine, waiting, complete, f"view.select({json.dumps(node['id'])});")
        assert out["after"]["selected"] == node["id"], node["title"]
        assert node["title"] in out["detail"], node["title"]


def test_redraw_drops_a_selection_that_no_longer_exists(engine):
    """选中的是 WSL 里的东西，新数据里 WSL 没了：回到没选中，不报错。"""
    i18n.set_language("zh")
    graph = sources.build(samples.facts())
    node = next(n for n in graph["nodes"] if n["region"] == "wsl")
    out = _redraw(engine, graph, sources.build(samples.facts(wsl="absent")), f"view.select({json.dumps(node['id'])});")
    assert out["kept"]["selected"] == node["id"] and out["after"]["selected"] is None
    assert "怎么看这张图" in out["detail"]


def test_redraw_keeps_the_search_text_when_nothing_is_selected(engine):
    i18n.set_language("zh")
    graph = sources.build(samples.facts())
    out = _redraw(engine, graph, graph, "document.getElementById('q').value = 'notion';")
    assert out["kept"] == {"selected": None, "lineOn": None, "query": "notion"} and out["query"] == "notion"


def test_a_storage_tile_lists_each_store_with_what_where_who_and_restore_source(engine):
    """存储磁贴点开：清单里每一项下面跟着几行说明（里面是什么、在哪、谁在写、丢了从哪恢复）。"""
    i18n.set_language("zh")
    graph = sources.build(samples.facts())
    out = _redraw(engine, graph, graph, "view.select('st_fish_local');")
    stores = [i for i in next(n for n in graph["nodes"] if n["id"] == "st_fish_local")["items"]]
    assert out["detail"].count('<dl class="more">') == len(stores)
    assert "memory-distill/entries.json" in out["detail"] and "丢了从哪恢复" in out["detail"]
    plain = _redraw(engine, graph, graph, "view.select('conn_w_ok');")       # 没有说明的清单照旧，不多出空壳
    assert '<dl class="more">' not in plain["detail"]


def test_redraw_removes_the_old_listeners_and_attaches_the_same_number_again(engine):
    """重画十次也只有一套监听：每次先把上一套整个摘掉。"""
    i18n.set_language("zh")
    graph = sources.build(samples.facts())
    out = _redraw(engine, graph, graph, "")
    assert out["aborted"] == 1 and out["firstListeners"] == out["secondListeners"] > 0


def test_first_draw_and_redraw_produce_the_same_map(engine):
    """重画只多一个「别重放入场动画」的标记，图本身和第一次画的一样。"""
    i18n.set_language("zh")
    graph = sources.build(samples.facts())
    assert _redraw(engine, graph, graph, "")["map"] == _run(engine, graph)["map"]


def test_view_select_ignores_an_unknown_node(engine):
    i18n.set_language("zh")
    graph = sources.build(samples.facts())
    out = _redraw(engine, graph, graph, "view.select('no-such-node');")
    assert out["kept"]["selected"] is None


# ---------------------------------------------------------------- 文件查看面板

#: 假的「向服务要东西」：同步返回像 Promise 的东西，记下问了什么；回答用完了就算连接断了
VIEW_API = """
var asked = [];
function done(value, failed) {
  return {then: function (ok, err) {
    var handler = failed ? err : ok;
    if (!handler) return done(value, failed);
    try { return done(handler(value), false); } catch (e) { return done(e, true); }
  }};
}
function fakeApi(replies) {
  return function (path) { asked.push(path); var r = replies.shift(); return r === undefined ? done(new Error('gone'), true) : done(r, false); };
}
"""


def _view(engine, replies, steps: str, *, api: bool = True) -> dict:
    """只跑查看面板这一个模块：``replies`` 是服务依次给的回答，``steps`` 里用 ``v`` 操作面板。"""
    i18n.set_language("zh")
    strings = json.dumps(render.page_strings(), ensure_ascii=False)
    source = f"fakeApi({json.dumps(replies, ensure_ascii=False)})" if api else "undefined"
    return _evaluate(engine, FAKE_DOM + VIEW_API + render.bundle(("util.js", "viewer.js")) + f"""
        var v = viewer({source}, {strings}, {{}});
        {steps}
        var el = document.getElementById;
        return JSON.stringify({{asked: asked, hidden: el('viewer').hidden, frame: el('viewer').innerHTML, files: el('viewer-files').innerHTML,
          oneFile: el('viewer-files').hidden, meta: el('viewer-meta').textContent, text: el('viewer-text').innerHTML}});""")


def _file(path: str, text: str, **extra) -> dict:
    return {"store": "claude_memory", "path": path, "text": text, "bytes": len(text), "mtime": "2026-01-02 03:04", "truncated": False,
            "marks": [], **extra}


def test_viewer_asks_for_the_list_then_reads_the_first_file(engine):
    listing = {"store": "claude_memory", "truncated": False, "files": [
        {"path": "projects/C--x/memory/a b.md", "label": "C--x / a b.md", "bytes": 9, "mtime": "2026-01-02 03:04"},
        {"path": "projects/C--x/memory/c.md", "label": "C--x / c.md", "bytes": 3, "mtime": "2026-01-01 00:00"}]}
    out = _view(engine, [listing, _file("projects/C--x/memory/a b.md", "hello\nworld")], "v.open('claude_memory', '项目记忆');")
    assert out["asked"] == ["/api/files?store=claude_memory", "/api/file?store=claude_memory&path=projects%2FC--x%2Fmemory%2Fa%20b.md"]
    assert out["hidden"] is False and "项目记忆" in out["frame"] and out["oneFile"] is False
    assert "C--x / a b.md" in out["files"] and 'data-file="projects/C--x/memory/c.md"' in out["files"]
    assert out["text"] == '<span class="ln">hello</span><span class="ln">world</span>'
    assert out["meta"].startswith("projects/C--x/memory/a b.md · 11 B · 2026-01-02 03:04")


def test_viewer_shows_file_content_as_text_never_as_markup(engine):
    """记忆文件里写了标签也只是几个字：进页面之前全部转义。"""
    nasty = '<script>alert(1)</script>\n<img src=x onerror="steal()">\n& done'
    listing = {"store": "claude_md", "truncated": False, "files": [{"path": "CLAUDE.md", "label": "<b>x</b>", "bytes": 1, "mtime": ""}]}
    out = _view(engine, [listing, _file("CLAUDE.md", nasty)], "v.open('claude_md', '<i>t</i>');")
    for part in (out["text"], out["files"], out["frame"]):
        assert "<script" not in part and "<img" not in part and "<i>" not in part and "<b>x" not in part
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out["text"] and "&amp; done" in out["text"]
    assert out["oneFile"] is True                                        # 只有一个文件：不显示左边那一栏


def test_viewer_tints_the_managed_block_and_says_when_the_file_was_cut(engine):
    listing = {"store": "claude_md", "truncated": False, "files": [{"path": "CLAUDE.md", "label": "CLAUDE.md", "bytes": 1, "mtime": ""}]}
    text = "mine\r\n<!-- start -->\r\n- rule\r\n<!-- end -->\r\ntail"
    reply = _file("CLAUDE.md", text, marks=[{"from": 2, "to": 4, "kind": "managed"}], truncated=True)
    out = _view(engine, [listing, reply], "v.open('claude_md', 'CLAUDE.md');")
    lines = re.findall(r'<span class="(ln[^"]*)">', out["text"])
    assert lines == ["ln", "ln managed", "ln managed", "ln managed", "ln"]
    assert "\r" not in out["text"]
    assert "受管块" in out["meta"] and "512 KB" in out["meta"]


def test_viewer_says_so_when_there_is_nothing_or_the_service_is_gone(engine):
    empty = _view(engine, [{"store": "claude_md", "files": [], "truncated": False}], "v.open('claude_md', 'x');")
    assert "这台机器上没有" in empty["text"] and len(empty["asked"]) == 1
    gone = _view(engine, [], "v.open('claude_md', 'x');")
    assert "读不到" in gone["text"]
    half = _view(engine, [{"store": "claude_md", "files": [{"path": "CLAUDE.md", "label": "CLAUDE.md", "bytes": 1, "mtime": ""}],
                           "truncated": False}], "v.open('claude_md', 'x');")
    assert "读不到" in half["text"] and len(half["asked"]) == 2           # 清单拿到了，读文件时断了


def test_viewer_closes_and_does_nothing_without_a_service(engine):
    listing = {"store": "claude_md", "files": [], "truncated": False}
    closed = _view(engine, [listing], "v.open('claude_md', 'x'); v.close();")
    assert closed["hidden"] is True and closed["frame"] == ""
    offline = _view(engine, [], "v.open('claude_md', 'x');", api=False)
    assert offline["asked"] == [] and offline["hidden"] is True          # 离线快照：没有服务可问，打不开


def _details(engine, graph: dict, node: str, api: str) -> str:
    data = json.dumps(render.page_data(graph), ensure_ascii=False)
    return _evaluate(engine, FAKE_DOM + VIEW_API + render.bundle(render.MODULES[:-1]) + f"""
        var view = start({data}, undefined, {api}); view.select({json.dumps(node)});
        return JSON.stringify({{detail: document.getElementById('detail').innerHTML}});""")["detail"]


def test_view_buttons_appear_where_the_graph_offers_them_and_are_disabled_in_the_snapshot(engine):
    i18n.set_language("zh")
    graph = sources.build(samples.facts())
    served = _details(engine, graph, "md_win", "fakeApi([])")
    assert 'data-view="claude_md"' in served and "disabled" not in served
    snapshot = _details(engine, graph, "md_win", "undefined")
    assert 'data-view="claude_md"' in snapshot and "disabled" in snapshot and "离线快照" in snapshot
    listed = _details(engine, graph, "st_fish_local", "fakeApi([])")
    assert listed.count("data-view=") == 1 and 'data-view="distill_entries"' in listed        # 样例里只有这一项有文件又能看
    assert "data-view=" not in _details(engine, graph, "set_win", "fakeApi([])")              # 设置文件不给看
    assert "data-view=" not in _details(engine, graph, "md_wsl", "fakeApi([])")               # WSL 一侧这一步还读不了


# ---------------------------------------------------------------- 原生模块

def test_modules_link_as_real_es_modules_and_draw_the_same_page_as_the_bundle(engine):
    """本机服务的页面由浏览器按 import 装配模块，离线快照用拼出来的一段脚本——两条路必须画出同一张图。

    这里让 JS 引擎按真正的模块规则去加载 ``app.js``：哪个模块 import 了别人没 export 的名字，这里就报链接错误。
    """
    i18n.set_language("zh")
    graph = sources.build(samples.facts())
    bundled = _run(engine, graph)

    js = QJSEngine()                                    # 模块在引擎里有缓存：单开一个，不污染别的用例
    setup = js.evaluate(FAKE_DOM)                       # 全局作用域里的假 DOM，模块看得见
    assert not setup.isError(), setup.toString()
    module = js.importModule(str(render.PAGE_DIR / "app.js"))
    assert not module.isError(), f"{module.toString()} (line {module.property('lineNumber').toInt()})"
    js.globalObject().setProperty("panoramaStart", module.property("start"))
    data = json.dumps(render.page_data(graph), ensure_ascii=False)
    result = js.evaluate(f"(function () {{ var size = panoramaStart({data});" + REPORT + "})()")
    assert not result.isError(), result.toString()
    assert json.loads(result.toString()) == bundled


def test_bundle_keeps_the_declared_order_and_strips_every_import_and_export():
    text = render.bundle()
    assert not re.search(r"^\s*(import|export)\b", text, re.M)
    positions = [text.index(marker) for marker in ("const esc = ", "function layout(", "function roads(", "function draw(",
                                                   "function interact(", "function start(", "PANORAMA_DATA")]
    assert positions == sorted(positions)
    for name in render.MODULES:
        for target in re.findall(r"^import \{[^}]*\} from '\./([a-z]+\.js)';", render.asset(name).decode("utf-8"), re.M):
            assert render.MODULES.index(target) < render.MODULES.index(name), f"{name} 依赖的 {target} 要排在它前面"


def test_bundler_refuses_import_forms_it_cannot_flatten(monkeypatch):
    """模块里写了打包不了的 import / export（默认导出、改名、import *），宁可报错也不拼出一段坏脚本。"""
    for bad in ("import * as util from './util.js';\n", "export default function () {}\n",
                "import {esc as e} from './util.js';\n", "import {esc}\n  from './util.js';\n", "export {esc};\n",
                "import {esc} from 'https://elsewhere.example/util.js';\n"):
        monkeypatch.setattr(render, "_text", lambda name, bad=bad: bad + "const x = 1;\n")
        with pytest.raises(RuntimeError):
            render.bundle(("util.js",))


# ---------------------------------------------------------------- boot.js：本机服务的页面

def test_served_page_takes_the_token_from_the_fragment_and_wipes_it_from_the_address_bar(engine):
    out = _boot(engine, f"location.hash = '#SECRET'; responses = [{_reply(1)}, {HANG}];")
    assert out["calls"][0] == {"path": "/api/graph", "token": "SECRET"}    # 令牌只走请求头
    assert all(call["token"] == "SECRET" and "SECRET" not in call["path"] for call in out["calls"])
    assert out["replaced"] == ["/"] and out["hash"] == ""                  # 地址栏里不留令牌
    assert out["store"] == {"panorama-token": "SECRET"}
    assert out["started"] == [{"revision": 1, "kept": None}] and not out["lost"]
    assert out["lang"] == "en" and out["title"] == "Config map"


def test_reloading_the_tab_gets_the_token_back_from_session_storage(engine):
    out = _boot(engine, f"store['panorama-token'] = 'KEPT'; responses = [{_reply(3)}, {HANG}];")
    assert out["calls"][0] == {"path": "/api/graph", "token": "KEPT"} and out["replaced"] == []
    assert out["started"] == [{"revision": 3, "kept": None}]


def test_served_page_then_waits_for_data_newer_than_what_it_has(engine):
    """拿到第一份之后带着它的编号去等更新的：一个挂着的请求，没有定时器在转。"""
    out = _boot(engine, f"location.hash = '#T'; responses = [{_reply(5)}, {HANG}];")
    assert out["calls"] == [{"path": "/api/graph", "token": "T"}, {"path": "/api/graph?after=5", "token": "T"}]
    assert out["timers"] == 0 and out["intervals"] == 0 and not out["lost"]
    assert out["watching"] == ["visibilitychange"]


def test_new_data_is_drawn_in_place_keeping_what_the_user_was_looking_at(engine):
    """数据变了不重载页面：先记下上一张图上选中的东西、摘掉旧监听，再用新数据画，然后接着等下一份。"""
    out = _boot(engine, f"location.hash = '#T'; responses = [{_reply(1, pending=True)}, {_reply(2)}, {HANG}];")
    assert out["reloads"] == 0
    assert out["started"] == [{"revision": 1, "kept": None}, {"revision": 2, "kept": {"selected": "seen-in-0"}}]
    assert out["disposed"] == [0]                                          # 旧的那张图的监听摘掉了，新的没动
    assert [c["path"] for c in out["calls"]] == ["/api/graph", "/api/graph?after=1", "/api/graph?after=2"]


def test_when_nothing_changed_the_page_asks_again_after_a_short_pause(engine):
    """服务挂了一阵说「没有新的」（204）：不立刻再问（出错时会空转），排一个定时器，到点带同一个编号再去等。"""
    setup = f"location.hash = '#T'; responses = [{_reply(1)}, {NOTHING_NEW}, {HANG}];"
    paused = _boot(engine, setup)
    assert len(paused["calls"]) == 2 and paused["timers"] == 1 and len(paused["started"]) == 1
    resumed = _boot(engine, setup, "tick();")
    assert [c["path"] for c in resumed["calls"]] == ["/api/graph", "/api/graph?after=1", "/api/graph?after=1"]
    assert resumed["timers"] == 0 and not resumed["lost"]


def test_a_hidden_tab_does_not_hold_a_request_and_resumes_when_shown(engine):
    """藏起来的标签页不占着服务：服务靠「没人在等」判断空闲。回到标签页就接着等，期间的新数据立刻拿到。"""
    setup = f"location.hash = '#T'; document.visibilityState = 'hidden'; responses = [{_reply(1)}, {_reply(2)}, {HANG}];"
    hidden = _boot(engine, setup)
    assert [c["path"] for c in hidden["calls"]] == ["/api/graph"] and hidden["timers"] == 0
    shown = _boot(engine, setup, "document.visibilityState = 'visible'; _docListeners.visibilitychange();")
    assert [c["path"] for c in shown["calls"]] == ["/api/graph", "/api/graph?after=1", "/api/graph?after=2"]
    assert [s["revision"] for s in shown["started"]] == [1, 2]


def test_becoming_visible_twice_does_not_stack_requests(engine):
    setup = f"location.hash = '#T'; responses = [{_reply(1)}, {HANG}, {HANG}];"
    out = _boot(engine, setup, "_docListeners.visibilitychange(); _docListeners.visibilitychange();")
    assert len(out["calls"]) == 2                                          # 已经有一个挂着：不再发第二个


@pytest.mark.parametrize("first", [_reply(0, status=401), "null"])
def test_served_page_says_so_when_it_cannot_reach_the_fish(engine, first):
    """令牌作废（401）或连不上：亮出「连接断了」，不画半张图。"""
    out = _boot(engine, f"location.hash = '#OLD'; responses = [{first}];".replace("[null]", "[]"))
    assert out["lost"] and out["started"] == [] and out["watching"] == []


def test_losing_the_service_later_shows_the_notice_keeps_the_map_and_stops_asking(engine):
    """肥鱼退出了：亮出「连接断了」，图留着；之后再切回这个标签页也不再去敲一个不存在的服务。"""
    setup = f"location.hash = '#T'; responses = [{_reply(1)}];"            # 第二个请求没人应
    out = _boot(engine, setup, "_docListeners.visibilitychange(); _docListeners.visibilitychange();")
    assert out["lost"] and len(out["started"]) == 1 and out["disposed"] == []
    assert len(out["calls"]) == 2 and out["timers"] == 0


# ---------------------------------------------------------------- boot.js：离线快照

def test_snapshot_uses_the_embedded_data_and_never_calls_the_service(engine):
    out = _boot(engine, "var PANORAMA_DATA = {meta: {pending: false}};")
    assert out["started"] == [{"revision": "embedded", "kept": None}]
    assert out["calls"] == [] and out["timers"] == 0 and out["intervals"] == 0 and out["watching"] == []


def test_pending_snapshot_rereads_its_own_file_a_bounded_number_of_times(engine):
    setup = "var PANORAMA_DATA = {meta: {pending: true}};"
    first = _boot(engine, setup, "tick();")
    assert first["reloads"] == 1 and first["hash"] == "1"                 # 重读次数记在 # 后面
    assert _boot(engine, setup + "location.hash = '#40';")["timers"] == 0  # 到头了就不再排下一次
