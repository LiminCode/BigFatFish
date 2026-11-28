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
from PySide6.QtQml import QJSEngine
from PySide6.QtWidgets import QApplication

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
var requests = [], openedSettings = [], lastApi = null;
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
  requests.push({path: path, method: options.method || 'GET', headers: options.headers, body: options.body});
  var r = responses.shift();
  if (!r) return settled(new Error('network'), true);
  if (r.hang) return {then: function () { return this; }};          // 服务把请求挂着：谁也不会被调到
  return settled({ok: r.status === 200, status: r.status, json: function () { return r.data; }}, false);
};
// 假的 start()：记下每次拿到的编号和 kept；返回的 view 记下谁被 dispose 了、被要求翻到哪一组设置
function start(data, kept, api) {
  var n = started.length;
  lastApi = api || null;
  started.push({revision: data.revision === undefined ? 'embedded' : data.revision, kept: kept === undefined ? null : kept});
  return {capture: function () { return {selected: 'seen-in-' + n}; }, dispose: function () { disposed.push(n); },
          openSettings: function (group) { openedSettings.push(group); return true; }};
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
    # 必须是 QApplication，不能是光秃的 QCoreApplication：这个文件要是先跑，后面要建窗口的测试会拿到这个实例，
    # 建第一个控件时整个进程直接退出（没有异常、没有栈）。
    app = QApplication.instance() or QApplication([])
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
    return _evaluate(engine, FAKE_DOM + FAKE_BROWSER + setup + render.bundle(("client.js", "boot.js")) + steps +
                     "\nreturn JSON.stringify({calls: calls, timers: timers.length, intervals: intervals.length, reloads: reloads, "
                     "replaced: replaced, started: started, disposed: disposed, store: store, hash: location.hash, "
                     "watching: Object.keys(_docListeners), "
                     "lost: document.getElementById('lost').hidden === false, lostText: document.getElementById('lost').textContent, "
                     "lang: document.documentElement.lang, "
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
    assert out["detail"].count('<dl class="more" hidden>') == len(stores), "默认紧凑：说明折着，点 ▸ 展开"
    assert "memory-distill/entries.json" in out["detail"] and "丢了从哪恢复" in out["detail"]
    plain = _redraw(engine, graph, graph, "view.select('plug_wsl');")        # 没有说明的清单照旧，不多出空壳
    assert 'class="more"' not in plain["detail"] and 'data-toggle' not in plain["detail"]


def test_redraw_removes_the_old_listeners_and_attaches_the_same_number_again(engine):
    """重画十次也只有一套监听：每次先把上一套整个摘掉。

    例外是设置面板和右栏里的时间轴：它们整页只有一个、跨重画存活（不然重画会冲掉没保存的字、关掉正看着的时间轴），
    第一次画的时候各挂上一个，之后不再挂。"""
    i18n.set_language("zh")
    graph = sources.build(samples.facts())
    out = _redraw(engine, graph, graph, "")
    assert out["aborted"] == 1 and out["firstListeners"] == out["secondListeners"] + 2 and out["secondListeners"] > 0


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


def test_viewer_says_a_file_is_not_text_instead_of_showing_noise(engine):
    listing = {"store": "claude_skills", "truncated": False, "files": [{"path": "skills/a/logo.png", "label": "a / logo.png", "bytes": 9, "mtime": ""}]}
    out = _view(engine, [listing, _file("skills/a/logo.png", "", binary=True, bytes=2048)], "v.open('claude_skills', 'x');")
    assert "不是文本" in out["text"] and "2.0 KB" in out["meta"]


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
    assert listed.count("data-view=") == 3 and 'data-view="distill_entries"' in listed        # 样例里有文件的三项；密钥那一行没有
    assert 'data-view="claude_settings"' in _details(engine, graph, "set_win", "fakeApi([])") # 设置文件原样可看
    assert "data-view=" not in _details(engine, graph, "plug_win", "fakeApi([])")
    assert 'data-view="claude_md_wsl"' in _details(engine, graph, "md_wsl", "fakeApi([])")    # WSL 一侧也能看了


# ---------------------------------------------------------------- 「在 VS Code 打开」的链接

NEW_WINDOW = "?windowId=_blank"          # VS Code 认这个参数：在新窗口里打开，不塞进现有的窗口

def test_a_wsl_file_link_carries_a_line_number_so_vs_code_opens_it_as_a_file(engine):
    """VS Code 把 ``vscode://vscode-remote/…`` 的路径默认当**文件夹**开，只有结尾带 ``:行号`` 才当文件。
    不带的话点 WSL 里的 CLAUDE.md 会开出一个空白窗口。"""
    i18n.set_language("zh")
    graph = sources.build(samples.facts())
    remote = "vscode://vscode-remote/wsl+Ubuntu-24.04/home/dev/.claude"
    assert f'href="{remote}/CLAUDE.md:1{NEW_WINDOW}"' in _details(engine, graph, "md_wsl", "undefined")
    assert f'href="{remote}/settings.json:1{NEW_WINDOW}"' in _details(engine, graph, "set_wsl", "undefined")
    assert f'href="vscode://vscode-remote/wsl+Ubuntu-24.04/home/dev/.claude.json:1{NEW_WINDOW}"' in _details(engine, graph, "mcp_wsl", "undefined")


def test_a_wsl_folder_link_has_no_line_number(engine):
    i18n.set_language("zh")
    graph = sources.build(samples.facts())
    remote = "vscode://vscode-remote/wsl+Ubuntu-24.04/home/dev/.claude"
    assert f'href="{remote}/projects{NEW_WINDOW}"' in _details(engine, graph, "mem_wsl", "undefined")
    assert f'href="{remote}{NEW_WINDOW}"' in _details(engine, graph, "st_cc_wsl_local", "undefined")


def test_every_link_asks_vs_code_for_a_new_window(engine):
    """不带这个参数，VS Code 把文件开在最近用的那个窗口里，和手头的项目混在一起。"""
    i18n.set_language("zh")
    graph = sources.build(samples.facts())
    for node in ("md_win", "set_win", "vault_personal", "pet", "md_wsl", "mem_wsl"):
        links = re.findall(r'href="(vscode://[^"]+)"', _details(engine, graph, node, "undefined"))
        assert len(links) == 1 and links[0].endswith(NEW_WINDOW) and links[0].count("?") == 1, (node, links)


def test_windows_links_keep_their_shape_and_a_wsl_link_without_a_distro_is_not_offered(engine):
    i18n.set_language("zh")
    graph = sources.build(samples.facts())
    assert f'href="vscode://file/C:/Users/dev/.claude/CLAUDE.md{NEW_WINDOW}"' in _details(engine, graph, "md_win", "undefined")
    nameless = samples.wsl_home()
    nameless["distro"] = ""
    detail = _details(engine, sources.build(samples.facts(wsl=nameless)), "md_wsl", "undefined")
    assert "vscode://" not in detail and "/home/dev/.claude/CLAUDE.md" in detail      # 路径还在，只是不给一个打不开的链接


# ---------------------------------------------------------------- 记忆一览

def _memory(engine, graph: dict, steps: str, *, open_file: bool = True) -> dict:
    """只跑记忆面板这一个模块。``steps`` 里用 ``m`` 操作面板；点「查看」会把参数记进 ``opened``。"""
    strings = json.dumps(render.page_strings(), ensure_ascii=False)
    data = json.dumps({"memory": graph["memory"]}, ensure_ascii=False)
    opener = "function (store, title, path) { opened.push([store, title, path]); }" if open_file else "null"
    return _evaluate(engine, FAKE_DOM + render.bundle(("util.js", "memory.js")) + f"""
        var opened = [];
        var m = memory({data}, {strings}, {{}}, {opener});
        {steps}
        return JSON.stringify({{hidden: document.getElementById('memory').hidden, html: document.getElementById('memory').innerHTML}});""")


def test_memory_panel_lists_each_machine_then_global_then_projects(engine):
    i18n.set_language("zh")
    graph = sources.build(samples.facts())
    out = _memory(engine, graph, "m.open();")
    html = out["html"]
    assert out["hidden"] is False and html.count("<section>") == 2
    assert html.index("个人 · 这台机器") < html.index("公司 · WSL")
    personal = html[:html.index("公司 · WSL")]
    assert personal.index("全局 · CLAUDE.md") < personal.index("项目 · potato") < personal.index("项目 · tomato")
    for text in ("画图只画机制", "默认中文", "本机测试方法", "番茄的发布流程", "Carrot notes", "pytest 要设环境变量才能跑起来", "我的规矩"):
        assert text in html
    assert html.count('class="flag f-to_global"') == 2 and html.count('class="flag f-in_global"') == 1
    assert 'title="同一条在两个以上的项目里各记了一份' in html


def test_memory_panel_offers_view_only_for_files_this_machine_can_open(engine):
    i18n.set_language("zh")
    graph = sources.build(samples.facts())
    html = _memory(engine, graph, "m.open();")["html"]
    assert 'data-path="projects/C--Users-dev-tomato/memory/run.md"' in html and 'data-store="claude_md"' in html
    assert 'data-store="claude_memory_wsl" data-path="projects/-home-dev-carrot/memory/notes.md"' in html     # WSL 一侧也有
    assert "data-store=" not in _memory(engine, graph, "m.open();", open_file=False)["html"]      # 离线快照：一个按钮都没有


def test_memory_panel_can_show_only_what_is_flagged(engine):
    i18n.set_language("zh")
    graph = sources.build(samples.facts())
    html = _memory(engine, graph, "m.open(true);")["html"]
    assert "番茄的发布流程" not in html and "我的规矩" not in html and "本机测试方法" in html
    assert "看全部" in html and "只看有标记的" not in html


def test_memory_panel_escapes_names_and_descriptions(engine):
    i18n.set_language("zh")
    win = samples.home()
    win["memory_index"]["projects"][0]["entries"][0].update(name="<img src=x onerror=1>", description="<script>x</script>")
    win["memory_index"]["rules"][0].update(title="<b>bold</b>", text='"quoted" & <i>')
    html = _memory(engine, sources.build(samples.facts(win=win)), "m.open();")["html"]
    assert "<img" not in html and "<script>" not in html and "<b>bold" not in html
    assert "&lt;script&gt;x&lt;/script&gt;" in html and "&amp; &lt;i&gt;" in html


def test_memory_panel_closes_and_survives_a_graph_without_memory(engine):
    i18n.set_language("zh")
    graph = sources.build(samples.facts())
    closed = _memory(engine, graph, "m.open(); m.close();")
    assert closed["hidden"] is True and closed["html"] == ""
    empty = _memory(engine, {"memory": {"sides": []}}, "m.open();")
    assert "没有读到记忆" in empty["html"]


def test_memory_tiles_and_the_header_offer_the_overview(engine):
    i18n.set_language("zh")
    graph = sources.build(samples.facts())
    assert 'data-memory="1"' in _details(engine, graph, "mem_win", "undefined")
    assert 'data-memory="1"' in _details(engine, graph, "md_wsl", "undefined")
    assert "data-memory" not in _details(engine, graph, "set_win", "undefined")
    data = json.dumps(render.page_data(graph), ensure_ascii=False)
    out = _evaluate(engine, FAKE_DOM + render.bundle(render.MODULES[:-1]) + f"""
        start({data}); return JSON.stringify({{button: document.getElementById('memory-open').textContent}});""")
    assert out["button"] == "记忆一览"


def test_viewer_can_be_opened_straight_at_one_file(engine):
    listing = {"store": "claude_memory", "truncated": False, "files": [
        {"path": "projects/a/memory/first.md", "label": "a / first.md", "bytes": 1, "mtime": ""},
        {"path": "projects/a/memory/second.md", "label": "a / second.md", "bytes": 1, "mtime": ""}]}
    out = _view(engine, [listing, _file("projects/a/memory/second.md", "two")],
                "v.open('claude_memory', 't', 'projects/a/memory/second.md');")
    assert out["asked"][1] == "/api/file?store=claude_memory&path=projects%2Fa%2Fmemory%2Fsecond.md" and "two" in out["text"]


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


#: 横幅的两种话：外壳把「正在重连」放在 data-retry 里，正文是「接不上了」
BANNER = "document.getElementById('lost').dataset.retry = 'RETRY'; document.getElementById('lost').textContent = 'GONE';"


def _banner(out: dict) -> str:
    return out["lostText"] if out["lost"] else ""


@pytest.mark.parametrize("status", [401, 404])
def test_a_refused_token_is_final_no_retrying(engine, status):
    """令牌对不上（4xx）：重连也没用，亮出「接不上了」，不画半张图、不排重试。"""
    out = _boot(engine, BANNER + f"location.hash = '#OLD'; responses = [{_reply(0, status=status)}];")
    assert _banner(out) == "GONE" and out["started"] == [] and out["timers"] == 0


@pytest.mark.parametrize("first", ["null", _reply(0, status=503), _reply(0, status=500)])
def test_a_fish_that_is_not_there_yet_is_retried_until_it_is(engine, first):
    """连不上、服务说还没准备好：亮出「正在重连」，隔一会儿再要一份；要到了横幅收起、照常画图。"""
    setup = BANNER + f"location.hash = '#T'; responses = [{first}];".replace("[null]", "[]")
    waiting = _boot(engine, setup)
    assert _banner(waiting) == "RETRY" and waiting["started"] == [] and waiting["timers"] == 1
    back = _boot(engine, setup, f"responses.push({_reply(1)}); responses.push({HANG}); tick();")
    assert _banner(back) == "" and back["started"] == [{"revision": 1, "kept": None}]
    assert [c["path"] for c in back["calls"]] == ["/api/graph", "/api/graph", "/api/graph?after=1"]


def test_losing_the_fish_later_keeps_the_map_and_reconnects_with_a_fresh_copy(engine):
    """肥鱼退出 / 重启：图留着，横幅说正在重连；它回来后不带编号重新要一份（重启后编号从头数），原地重画、保留选中。"""
    setup = BANNER + f"location.hash = '#T'; responses = [{_reply(5)}];"   # 第二个请求没人应
    gone = _boot(engine, setup)
    assert _banner(gone) == "RETRY" and len(gone["started"]) == 1 and gone["disposed"] == [] and gone["timers"] == 1
    still = _boot(engine, setup, "tick();")                                # 还没回来：接着排下一次，不叠请求
    assert _banner(still) == "RETRY" and still["timers"] == 1 and len(still["calls"]) == 3
    back = _boot(engine, setup, f"tick(); responses.push({_reply(1)}); responses.push({HANG}); tick();")
    assert [c["path"] for c in back["calls"]] == ["/api/graph", "/api/graph?after=5", "/api/graph", "/api/graph",
                                                  "/api/graph?after=1"]
    assert back["started"][-1] == {"revision": 1, "kept": {"selected": "seen-in-0"}} and _banner(back) == ""


def test_a_hidden_tab_does_not_retry_until_it_is_shown(engine):
    setup = BANNER + f"location.hash = '#T'; responses = [{_reply(1)}];"
    hidden = _boot(engine, setup, "document.visibilityState = 'hidden'; tick();")
    assert len(hidden["calls"]) == 2 and hidden["timers"] == 0              # 到点了但藏着：不敲门
    shown = _boot(engine, setup, f"document.visibilityState = 'hidden'; tick(); responses.push({_reply(2)}); responses.push({HANG});"
                                 "document.visibilityState = 'visible'; _docListeners.visibilitychange();")
    assert [c["path"] for c in shown["calls"]][-2:] == ["/api/graph", "/api/graph?after=2"] and _banner(shown) == ""


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


# ───────────────────────── 待处理里的「修复」 ─────────────────────────

def _no_hooks_graph():
    return sources.build(samples.facts(win=samples.home(hooks={"Stop": {"total": 1, "fish": 0}})))


def test_a_quest_with_an_action_gets_a_repair_button_only_where_there_is_a_service(engine):
    i18n.set_language("zh")
    graph = _no_hooks_graph()
    data = json.dumps(render.page_data(graph), ensure_ascii=False)
    served = _evaluate(engine, FAKE_DOM + render.bundle(render.MODULES[:-1]) + f"\nvar size = start({data}, undefined, function () {{}});" + REPORT)
    assert served["quests"].count('data-action="repair_hooks"') == 1 and 'data-agent="claude"' in served["quests"]
    assert "disabled" not in served["quests"] and ">修复<" in served["quests"]
    snapshot = _run(engine, graph)
    assert 'data-action="repair_hooks"' in snapshot["quests"] and "disabled" in snapshot["quests"], "离线快照：按钮灰着"


REPAIR_HARNESS = """
var confirms = [], answer = true, posted = [], reply = {status: 200, body: {state: 'installed'}};
var confirm = function (text) { confirms.push(text); return answer; };
function done(value, failed) {
  return {then: function (ok, err) { var h = failed ? err : ok; if (!h) return done(value, failed);
    try { return done(h(value), false); } catch (e) { return done(e, true); } }};
}
var api = function () {}; api.post = function (path, body) { posted.push({path: path, body: body}); return reply === 'gone' ? done(new Error('gone'), true) : done(reply, false); };
var el = {dataset: {action: 'repair_hooks', agent: 'claude_wsl', side: 'wsl'}, disabled: false, textContent: '修复'};
var S = {repair: '修复', repair_confirm_win: 'WIN?', repair_confirm_wsl: 'WSL?', repair_working: '正在配置…', repair_installed: '已装好',
         repair_pending: '正在配置 WSL…', repair_failed: '没装成', repair_lost: '连接断了'};
"""


def _repair(engine, steps: str) -> dict:
    return _evaluate(engine, FAKE_DOM + REPAIR_HARNESS + render.bundle(("util.js", "repair.js")) + steps +
                     "\nreturn JSON.stringify({confirms: confirms, posted: posted, text: el.textContent, disabled: el.disabled, out: out});")


def test_repair_asks_first_posts_the_agent_and_writes_the_outcome_on_the_button(engine):
    out = _repair(engine, "var out = null; runAction(api, S, el).then(function (s) { out = s; });")
    assert out["confirms"] == ["WSL?"] and out["posted"] == [{"path": "/api/actions/repair_hooks", "body": {"agent": "claude_wsl"}}]
    assert out["out"] == "installed" and out["text"] == "已装好" and out["disabled"] is True


def test_declining_the_confirm_posts_nothing(engine):
    out = _repair(engine, "answer = false; var out = 'untouched'; runAction(api, S, el).then(function (s) { out = s; });")
    assert out["confirms"] == ["WSL?"] and out["posted"] == [] and out["out"] is None and out["text"] == "修复"


def test_a_failed_or_lost_repair_lets_the_user_try_again(engine):
    out = _repair(engine, "reply = {status: 500, body: {error: 'action_failed'}}; var out = null; runAction(api, S, el).then(function (s) { out = s; });")
    assert out["out"] == "failed" and out["text"] == "没装成" and out["disabled"] is False
    out = _repair(engine, "reply = 'gone'; var out = null; runAction(api, S, el).then(function (s) { out = s; });")
    assert out["out"] == "lost" and out["text"] == "连接断了" and out["disabled"] is False


# ───────────────────────── 动作按钮不只会「修复」：字、要不要先问、发什么，都跟着动作走（2026-11-22）─────────────────────────

def _stale_vault_graph():
    facts = samples.facts()
    facts["personal_vault"].update(checked_age_s=9 * 86400)
    return sources.build(facts)


def test_a_check_quest_gets_its_own_button_words_and_carries_its_body(engine):
    i18n.set_language("zh")
    data = json.dumps(render.page_data(_stale_vault_graph()), ensure_ascii=False)
    served = _evaluate(engine, FAKE_DOM + render.bundle(render.MODULES[:-1]) + f"\nvar size = start({data}, undefined, function () {{}});" + REPORT)
    assert served["quests"].count('data-action="check_remote"') == 1 and ">现在核对<" in served["quests"]
    assert 'data-words="check"' in served["quests"] and 'data-ask="0"' in served["quests"]
    assert 'data-body="{&quot;repo&quot;:&quot;personal&quot;}"' in served["quests"]


def test_a_tile_with_its_own_actions_shows_every_one_of_them_in_its_details(engine):
    """知识库克隆的磁贴自带两个动作：详情里两个按钮一直都在，不靠有没有待处理。"""
    i18n.set_language("zh")
    served = _details(engine, sources.build(samples.facts()), "vault_personal", "fakeApi([])")       # 又新又没有差距
    assert served.count('data-action="check_remote"') == 1 and served.count('data-action="sync_vault"') == 1
    assert ">现在核对<" in served and ">现在同步<" in served and "disabled" not in served
    assert served.index("check_remote") < served.index("sync_vault") < served.index("open_report"), "只读的那个排在前面"
    assert ">时间轴<" in served and 'data-body="{&quot;report&quot;:&quot;activity&quot;}"' in served
    assert 'data-words="sync"' in served and 'data-ask="0"' not in served.split('data-action="sync_vault"')[1].split(">")[0], \
        "同步要先问；核对不用"
    work = _details(engine, sources.build(samples.facts()), "vault_work", "fakeApi([])")
    assert re.findall(r'data-action="(\w+)"', work) == ["open_report"], "公司侧的克隆没有核对 / 同步，只有时间轴"
    hooks = _details(engine, _no_hooks_graph(), "set_win", "fakeApi([])")
    assert hooks.count('data-action="repair_hooks"') == 1, "没有自带动作的磁贴照旧用它名下那条待处理的动作"


SYNC_STEPS = """
el = {dataset: {action: 'sync_vault', agent: '', side: '', words: 'sync', body: '{"repo":"personal"}'}, disabled: false, textContent: '现在同步'};
S.sync = '现在同步'; S.sync_confirm_win = 'SYNC?'; S.sync_working = '正在同步…'; S.sync_synced = '同步好了'; S.sync_noop = '已经是最新的';
S.sync_conflict = '有冲突'; S.sync_failed = '没办成'; S.sync_busy = '稍等';
"""


def test_syncing_asks_first_and_posts_nothing_when_declined(engine):
    out = _repair(engine, SYNC_STEPS + "answer = false; var out = 'untouched'; runAction(api, S, el).then(function (s) { out = s; });")
    assert out["confirms"] == ["SYNC?"] and out["posted"] == [] and out["out"] is None and out["text"] == "现在同步"


@pytest.mark.parametrize(("state", "text", "again"), [("synced", "同步好了", False), ("noop", "已经是最新的", False),
                                                    ("conflict", "有冲突", False), ("failed", "没办成", True), ("busy", "稍等", True)])
def test_the_sync_button_says_how_it_went(engine, state, text, again):
    out = _repair(engine, SYNC_STEPS + f"reply = {{status: 200, body: {{state: '{state}'}}}}; var out = null; runAction(api, S, el).then(function (s) {{ out = s; }});")
    assert out["confirms"] == ["SYNC?"] and out["posted"] == [{"path": "/api/actions/sync_vault", "body": {"repo": "personal"}}]
    assert out["out"] == state and out["text"] == text and out["disabled"] is (not again)


def test_a_button_that_opened_a_page_can_be_pressed_again(engine):
    """「时间轴」开的是另一张页：图不会重画，按钮不能就此灰掉。"""
    steps = """
el = {dataset: {action: 'open_report', agent: '', side: '', words: 'activity', ask: '0', body: '{"report":"activity"}'}, disabled: false, textContent: '时间轴'};
S.activity = '时间轴'; S.activity_working = '正在打开…'; S.activity_opened = '已打开'; S.activity_failed = '打不开';
reply = {status: 200, body: {state: 'opened'}}; var out = null; runAction(api, S, el).then(function (s) { out = s; });"""
    out = _repair(engine, steps)
    assert out["confirms"] == [] and out["posted"] == [{"path": "/api/actions/open_report", "body": {"report": "activity"}}]
    assert out["out"] == "opened" and out["text"] == "已打开" and out["disabled"] is False


CHECK_STEPS = """
el = {dataset: {action: 'check_remote', agent: '', side: '', words: 'check', ask: '0', body: '{"repo":"personal"}'}, disabled: false, textContent: '现在核对'};
S.check = '现在核对'; S.check_working = '正在核对…'; S.check_checked = '核对过了'; S.check_failed = '没连上'; S.check_busy = '正在核对，稍等';
"""


def test_checking_does_not_ask_posts_the_body_and_uses_its_own_words(engine):
    out = _repair(engine, CHECK_STEPS + "reply = {status: 200, body: {state: 'checked'}}; var out = null; runAction(api, S, el).then(function (s) { out = s; });")
    assert out["confirms"] == [] and out["posted"] == [{"path": "/api/actions/check_remote", "body": {"repo": "personal"}}]
    assert out["out"] == "checked" and out["text"] == "核对过了" and out["disabled"] is True


@pytest.mark.parametrize(("reply", "state", "text"), [
    ("{status: 200, body: {state: 'failed'}}", "failed", "没连上"), ("{status: 200, body: {state: 'busy'}}", "busy", "正在核对，稍等"),
    ("{status: 500, body: {error: 'action_failed'}}", "failed", "没连上"), ("'gone'", "lost", "连接断了")])
def test_a_check_that_did_not_happen_can_be_tried_again(engine, reply, state, text):
    out = _repair(engine, CHECK_STEPS + f"reply = {reply}; var out = null; runAction(api, S, el).then(function (s) {{ out = s; }});")
    assert out["out"] == state and out["text"] == text and out["disabled"] is False


# ---------------------------------------------------------------- 详情栏：紧凑列表、逐条折叠、筛选、相对时间、把手（2026-11-20）

def test_lists_are_compact_by_default_with_a_fold_per_item_a_count_and_a_filter_when_long(engine):
    i18n.set_language("zh")
    graph = sources.build(samples.facts())
    long = _details(engine, graph, "st_fish_free", "undefined")           # 18 条：筛选框出现
    assert long.count('<div class="item" data-row=') == 18 and long.count('<dl class="more" hidden>') == 18
    assert long.count('<button class="fold" data-toggle=') == 18 and 'aria-expanded="false">▸</button>' in long
    assert '<span class="lcount">18 条</span>' in long and 'class="lfilter" data-filter="st_fish_free"' in long
    assert '<button class="peek" data-expand-all="1">全部展开</button>' in long
    short = _details(engine, graph, "st_cc_win_local", "undefined")       # 5 条：有折叠、没有筛选框
    assert '<span class="lcount">5 条</span>' in short and 'lfilter' not in short and 'data-expand-all' in short
    flat = _details(engine, graph, "plug_wsl", "undefined")               # 没有说明的条目：占位、无按钮
    assert '<i class="fold-gap"></i>' in flat and 'data-expand-all' not in flat


def test_timestamps_in_facts_get_a_relative_age(engine):
    i18n.set_language("zh")
    graph = sources.build(samples.facts())
    detail = _details(engine, graph, "conn_w_ok", "undefined")
    assert re.search(r'2026-01-02 03:04:11<span class="ago"> · \d+ 天前</span>', detail), "探测时间后面跟「N 天前」"


def test_the_age_and_filter_helpers_are_pure(engine):
    out = _evaluate(engine, render.bundle(("util.js",)) + """
      var S = {ago_now: '刚刚', ago_minutes: '{n} 分钟前', ago_hours: '{n} 小时前', ago_days: '{n} 天前'};
      var t0 = new Date(2026, 10, 20, 12, 0, 0).getTime();
      return JSON.stringify({
        now: ago('2026-11-20 11:59:30', S, t0), min: ago('2026-11-20 11:15', S, t0), hours: ago('2026-11-20 08:30:00', S, t0),
        days: ago('2026-11-17 20:00:00', S, t0), future: ago('2026-11-21 00:00:00', S, t0), text: ago('~/.claude.json', S, t0),
        empty: ago('', S, t0),
        m1: rowMatches({name: 'claude.ai Atlassian', detail: '远程服务', more: [['地址', 'https://mcp.atlassian.com/v1/mcp']]}, 'ATLAS'),
        m2: rowMatches({name: 'GitKraken', detail: '本地命令', more: [['地址', '/home/x/gk']]}, 'mcp.atlassian'),
        m3: rowMatches({name: 'x', detail: ''}, '   '),
        clamp: [clampAside(100), clampAside(500.4), clampAside(9999), clampAside('abc')]});""")
    assert out == {"now": "刚刚", "min": "45 分钟前", "hours": "3 小时前", "days": "2 天前", "future": "", "text": "", "empty": "",
                   "m1": True, "m2": False, "m3": True, "clamp": [300, 500, 720, 380]}


def test_the_shell_has_the_resize_handle_between_map_and_panel():
    shell = render.PAGE_DIR.joinpath("shell.html").read_text(encoding="utf-8")
    assert shell.index('id="stage"') < shell.index('class="gutter" id="gutter"') < shell.index("<aside>")
    css = render.PAGE_DIR.joinpath("app.css").read_text(encoding="utf-8")
    assert "var(--aside-w,380px)" in css and ".gutter{display:none}" in css


def test_vault_tiles_open_the_timeline_straight_from_their_face(engine):
    """磁贴正面的「时间轴」：三个克隆各一个；离线快照里是灰的（没有服务能开报告页）。"""
    i18n.set_language("zh")
    graph = sources.build(samples.facts())
    data = json.dumps(render.page_data(graph), ensure_ascii=False)
    served = _evaluate(engine, FAKE_DOM + render.bundle(render.MODULES[:-1]) + f"\nvar size = start({data}, undefined, function () {{}});" + REPORT)
    faces = re.findall(r'<button class="face"[^>]*>', served["map"])
    assert len(faces) == 9 and all('data-action="open_report"' in f and 'data-ask="0"' in f and "disabled" not in f for f in faces)
    assert served["map"].count(">时间轴</span>") == 4 and served["map"].count(">查看</span>") == 5
    tiles = {re.match(r'[^"]*" data-id="([^"]+)"', chunk).group(1): chunk for chunk in served["map"].split('<div class="tile ')[1:]}
    timeline = {"vault_personal", "vault_work", "vault_wsl", "f_vault_sync"}
    assert {tile for tile, body in tiles.items() if 'class="face"' in body and ">时间轴</span>" in body} == timeline
    assert all("has-face" in tiles[tile][:80] for tile in timeline)
    snapshot = re.findall(r'<button class="face"[^>]*>', _run(engine, graph)["map"])
    assert len(snapshot) == 9 and all("disabled" in f for f in snapshot)


def test_feature_tiles_open_their_own_page_from_the_face(engine):
    """工作简报 / 个人助理 / 工作笔记 / Slack 关注：正面「查看」开浏览器里那张页（不进右栏），图标是眼睛不是时钟。"""
    i18n.set_language("zh")
    data = json.dumps(render.page_data(sources.build(samples.facts())), ensure_ascii=False)
    served = _evaluate(engine, FAKE_DOM + render.bundle(render.MODULES[:-1]) + f"\nvar size = start({data}, undefined, function () {{}});" + REPORT)
    faces = re.findall(r'<button class="face".*?</button>', served["map"])
    pages = [f for f in faces if ">查看</span>" in f]
    assert sorted(re.search(r'&quot;report&quot;:&quot;(\w+)&quot;', f).group(1) for f in pages) == \
        ["personal_briefing", "personal_briefing", "slack_watch", "work_briefing", "work_notes"]   # 个人助理和随手记开同一张页
    assert all("data-show" not in f and 'data-words="open_page"' in f for f in pages)
    clock = next(f for f in faces if ">时间轴</span>" in f)
    assert all(re.search(r"<svg.*?</svg>", f).group(0) != re.search(r"<svg.*?</svg>", clock).group(0) for f in pages)


def test_a_face_button_keeps_its_icon_and_puts_its_label_back(engine):
    """磁贴正面的按钮很小：结果只写进字那一格（图标留着）、挂在悬停提示上，开了页的过一会儿换回原来的字——不再撑出磁贴。"""
    steps = """
var label = {textContent: '查看'}, later = null, delays = [];
var setTimeout = function (fn, ms) { later = fn; delays.push(ms); };
el = {dataset: {action: 'open_report', words: 'open_page', ask: '0', body: '{"report":"work_briefing"}'}, disabled: false,
      textContent: 'ICON查看', title: '', querySelector: function (sel) { return sel === 'span' ? label : null; }};
S.open_page = '查看'; S.open_page_working = '正在打开…'; S.open_page_opened = '已打开'; S.open_page_failed = '打不开';
reply = {status: 200, body: {state: 'opened'}}; var out = null; runAction(api, S, el).then(function (s) { out = s; });
var shown = label.textContent, tip = el.title; if (later) later();
"""
    out = _evaluate(engine, FAKE_DOM + REPAIR_HARNESS + render.bundle(("util.js", "repair.js")) + steps +
                    "\nreturn JSON.stringify({posted: posted, text: el.textContent, shown: shown, tip: tip, after: label.textContent,"
                    " disabled: el.disabled, delays: delays, out: out});")
    assert out["posted"] == [{"path": "/api/actions/open_report", "body": {"report": "work_briefing"}}] and out["out"] == "opened"
    assert out["text"] == "ICON查看", "按钮本身的内容（图标）没被整个换掉"
    assert out["shown"] == "已打开" and out["tip"] == "已打开" and out["after"] == "查看" and out["disabled"] is False
    assert len(out["delays"]) == 1


# ───────────────────────── 时间轴在右栏里看（2026-11-24）─────────────────────────

TIMELINE_HARNESS = """
var requests = [], posted = [], replies = [], timers = [];
var setTimeout = function (fn) { timers.push(fn); };
function done(value, failed) {
  return {then: function (ok, err) { var h = failed ? err : ok; if (!h) return done(value, failed);
    try { return done(h(value), false); } catch (e) { return done(e, true); } }};
}
var api = function (path) { requests.push(path); var r = replies.shift();
  if (r === undefined) return {then: function () { return this; }};          // 服务把「等更新的」挂着：谁也不会被调到
  return r === 'gone' ? done(new Error('gone'), true) : done(r, false); };
api.post = function (path, body) { posted.push({path: path, body: body}); return done({status: 200, body: {state: 'opened'}}, false); };
var S = {viewer_close: '关闭', viewer_loading: '正在读取…', timeline_newtab: '在新页面打开', timeline_failed: '时间轴读不出来',
         activity: '时间轴', activity_working: '正在打开…', activity_opened: '已在浏览器里打开'};
var faceButton = {dataset: {action: 'open_report', words: 'activity', ask: '0', body: '{"report":"activity"}', show: 'panel'}};
function payload(rev, html) { return {revision: rev, report: {title: '时间轴', summary: '最近 ' + rev + ' 次运行', generated: '核对于 11-24 08:00', html: html}}; }
"""


def _timeline(engine, steps: str) -> dict:
    return _evaluate(engine, FAKE_DOM + TIMELINE_HARNESS + render.bundle(("util.js", "repair.js", "timeline.js")) + steps +
                     "\nvar box = document.getElementById('timeline'), det = document.getElementById('detail');"
                     "return JSON.stringify({requests: requests, posted: posted, html: box.innerHTML, shown: box.hidden === false,"
                     " detailHidden: det.hidden === true, timers: timers.length});")


def test_the_face_button_says_its_report_opens_in_the_side_panel(engine):
    i18n.set_language("zh")
    data = json.dumps(render.page_data(sources.build(samples.facts())), ensure_ascii=False)
    served = _evaluate(engine, FAKE_DOM + render.bundle(render.MODULES[:-1]) + f"\nvar size = start({data}, undefined, function () {{}});" + REPORT)
    faces = [f for f in re.findall(r'<button class="face"[^>]*>', served["map"]) if "&quot;activity&quot;" in f]
    assert len(faces) == 4 and all('data-show="panel"' in face for face in faces)


def test_the_timeline_opens_in_the_side_panel_in_place_of_the_tile_details(engine):
    out = _timeline(engine, "replies = [payload(3, '<div class=\"waterfall\">ROWS</div>')];"
                            "var tl = timelinePanel(api, S); tl.openFrom(faceButton);")
    assert out["requests"] == ["/api/report/activity", "/api/report/activity?after=3"], "先要现成的，再挂着等更新的"
    assert out["shown"] and out["detailHidden"], "时间轴占了详情那张卡的位置"
    assert '<div class="waterfall">ROWS</div>' in out["html"] and "最近 3 次运行" in out["html"] and "核对于 11-24 08:00" in out["html"]
    assert 'data-tl-close="1"' in out["html"] and ">关闭<" in out["html"]
    assert 'data-action="open_report"' in out["html"] and ">在新页面打开<" in out["html"] and "data-show" not in out["html"], \
        "「在新页面打开」走原来的动作，不再进右栏"
    assert out["posted"] == [], "在右栏看不发 open_report"


def test_newer_timeline_data_redraws_the_panel_and_waits_again(engine):
    out = _timeline(engine, "replies = [payload(3, 'OLD'), payload(4, 'NEW')];"
                            "var tl = timelinePanel(api, S); tl.openFrom(faceButton);")
    assert out["requests"] == ["/api/report/activity", "/api/report/activity?after=3", "/api/report/activity?after=4"]
    assert "NEW" in out["html"] and "OLD" not in out["html"]
    nothing_new = _timeline(engine, "replies = [payload(3, 'OLD'), null];"
                                    "var tl = timelinePanel(api, S); tl.openFrom(faceButton);")
    assert nothing_new["timers"] == 1 and "OLD" in nothing_new["html"], "这段时间没有新的：隔一会儿再去等"


def test_closing_the_timeline_brings_the_details_back_and_ignores_late_answers(engine):
    out = _timeline(engine, "var tl = timelinePanel(api, S); tl.openFrom(faceButton); tl.close();"
                            "replies = [payload(9, 'LATE')];")
    assert not out["shown"] and not out["detailHidden"] and out["html"] == ""
    late = _timeline(engine, "var tl = timelinePanel(api, S); var first = api; replies = [];"
                             "tl.openFrom(faceButton); tl.close(); tl.isOpen() && (box.innerHTML = 'still');")
    assert late["html"] == ""


def test_a_timeline_that_cannot_be_read_says_so_and_stops_asking(engine):
    out = _timeline(engine, "replies = ['gone']; var tl = timelinePanel(api, S); tl.openFrom(faceButton);")
    assert out["shown"] and "时间轴读不出来" in out["html"] and out["requests"] == ["/api/report/activity"]


def test_without_a_service_the_timeline_panel_never_opens(engine):
    out = _timeline(engine, "var tl = timelinePanel(null, S); tl.openFrom(faceButton);")
    assert not out["shown"] and out["requests"] == []


def test_the_new_tab_button_inside_the_panel_still_opens_the_page(engine):
    out = _timeline(engine, "replies = [payload(3, 'ROWS')]; var tl = timelinePanel(api, S); tl.openFrom(faceButton);"
                            "var btn = {dataset: {action: 'open_report', words: 'activity', ask: '0', body: '{\"report\":\"activity\"}'},"
                            " disabled: false, textContent: ''}; runAction(api, S, btn);")
    assert out["posted"] == [{"path": "/api/actions/open_report", "body": {"report": "activity"}}]


def test_both_pages_carry_the_timeline_styles():
    assert "activity.css" in render.STYLES and "activity.css" in render.REPORT_STYLES
    assert ".waterfall{" in render.render(sources.build(samples.facts())), "离线快照也带着（样式内联进页面）"
    assert 'href="/activity.css"' in render.shell() and 'href="/activity.css"' in render.report_shell()
    assert ".waterfall{" not in render.asset("report.css").decode("utf-8"), "只在一处定义"
