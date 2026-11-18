# -*- coding: utf-8 -*-
"""配置全景上改设置的入口（路线图 M3 第 4 步）：功能磁贴详情里的「设置」按钮 → 设置面板（``page/settings.js``）
→ 表单（``form.js``，测试见 ``test_panorama_form.py``）→ ``PATCH /api/settings/<组>``。

要守住的几件事：
- 只有设置表里登记了的功能才有按钮；离线快照没有服务可问，按钮是灰的；
- 改完设置服务会重新发布一次图，页面原地重画——**面板和里面没保存的字不能跟着没了**；
- 关面板时有没保存的字先提醒，再关一次才丢；
- 设置窗口里点「到配置全景里改」，打开的网址带着组名，页面画完就直接翻到那一组；
- 写请求带令牌、JSON、PATCH，服务的每一种回答（包括 4xx）都原样交给表单，只有连不上才算失败。

和其他页面测试一样在 Qt 自带的 JS 引擎里跑，DOM 和浏览器是假的（``test_panorama_page`` 的那一套）。
"""
from __future__ import annotations

import json

import pytest

from pet import i18n
from pet.panorama import render, sources
from tests import panorama_samples as samples
from tests.test_panorama_page import FAKE_BROWSER, FAKE_DOM, _evaluate


@pytest.fixture(scope="module")
def engine():
    from PySide6.QtQml import QJSEngine
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])                # 不能是 QCoreApplication，见 test_panorama_page 的同名夹具
    js = QJSEngine()
    yield js
    del js, app


@pytest.fixture(autouse=True)
def _chinese():
    i18n.set_language("zh")
    yield
    i18n.set_language("zh")


#: 假的服务：GET 一组设置回 DESC，PATCH 记下来、按 PATCHED 回答。宿主元素 settings-form 记下监听，测试自己触发事件。
API = """
var gets = [], patches = [], DESC = %s, PATCHED = [];
function settled(value, failed) {
  return {then: function (ok, err) {
    var handler = failed ? err : ok;
    if (!handler) return settled(value, failed);
    try { return settled(handler(value), false); } catch (e) { return settled(e, true); }
  }};
}
var API = function (path) { gets.push(path); return DESC === 'fail' ? settled(new Error('x'), true) : settled(DESC, false); };
API.patch = function (path, body) { patches.push({path: path, body: body});
  var r = PATCHED.shift(); return r ? settled(r, false) : settled(new Error('gone'), true); };
var formListeners = {};
_els['settings-form'] = {innerHTML: '', addEventListener: function (t, fn) { formListeners[t] = fn; },
  querySelector: function () { return null; }, querySelectorAll: function () { return []; }};
function fire(type, data, value) {
  var t = {dataset: data, value: value === undefined ? '' : value, checked: !!value};
  t.closest = function (sel) { var m = sel.match(/^\\[data-([a-z-]+)\\]$/); return m && m[1] in t.dataset ? t : null; };
  formListeners[type]({type: type, target: t, preventDefault: function () {}});
}
"""

REPORT = """
return JSON.stringify({gets: gets, patches: patches, detail: document.getElementById('detail').innerHTML,
  box: {hidden: document.getElementById('settings').hidden, html: document.getElementById('settings').innerHTML},
  form: document.getElementById('settings-form').innerHTML, note: document.getElementById('settings-note').textContent});
"""


def _desc(**changes) -> dict:
    desc = {"group": "work_briefing", "title": "工作简报", "zone": "work", "available": True, "unavailable": "", "version": "v1",
            "settings": [
                {"id": "enabled", "control": "toggle", "title": "开关", "hint": "", "value": False, "default": False,
                 "choices": [], "commit": "immediate", "disclosure": "primary", "depends_on": "", "builtin": None},
                {"id": "priority_rules", "control": "long_text", "title": "偏好", "hint": "", "value": "", "default": "",
                 "choices": [], "commit": "on_finish", "disclosure": "primary", "depends_on": "", "builtin": None}]}
    desc.update(changes)
    return desc


def _page(engine, steps: str, *, api: bool = True, desc=None) -> dict:
    data = json.dumps(render.page_data(sources.build(samples.facts())), ensure_ascii=False)
    script = (FAKE_DOM + API % json.dumps(desc if desc is not None else _desc(), ensure_ascii=False)
              + render.bundle(render.MODULES[:-1])
              + f"\nvar DATA = {data}; var view = start(DATA, undefined, {'API' if api else 'null'});\n" + steps + REPORT)
    return _evaluate(engine, script)


# ───────────────────────── 入口 ─────────────────────────

def test_the_settings_button_is_on_the_briefing_tile_and_opens_the_form(engine):
    out = _page(engine, "view.select('f_briefing');")
    assert 'data-settings="work_briefing"' in out["detail"] and "disabled" not in out["detail"].split('data-settings')[1].split('>')[0]
    assert out["gets"] == []                                              # 点之前不问
    out = _page(engine, "view.openSettings('work_briefing');")
    assert out["gets"] == ["/api/settings/work_briefing"]
    assert out["box"]["hidden"] is False and "工作简报" in out["box"]["html"]
    assert 'data-set="enabled"' in out["form"]
    assert 'data-settings="work_briefing"' in out["detail"]               # 磁贴也跟着选中了


def test_tiles_whose_settings_are_still_in_the_settings_window_have_no_button(engine):
    out = _page(engine, "view.select('f_screen');")                  # 看屏幕还没搬
    assert "data-settings" not in out["detail"]


def test_in_the_offline_snapshot_the_button_is_grey_and_explains_why(engine):
    out = _page(engine, "view.select('f_briefing'); view.openSettings('work_briefing');", api=False)
    button = out["detail"].split("data-settings")[1].split(">")[0]
    assert "disabled" in button and "title=" in button
    assert out["gets"] == [] and out["box"]["hidden"] is True


def test_an_unknown_group_opens_nothing(engine):
    out = _page(engine, "var ok = view.openSettings('nope'); if (ok) throw new Error('opened');")
    assert out["gets"] == [] and out["box"]["hidden"] is True


# ───────────────────────── 面板 ─────────────────────────

def test_a_change_goes_out_as_a_patch_with_the_version_it_was_made_on(engine):
    reply = {"status": 200, "body": {**_desc(version="v2"), "changed": ["enabled"]}}
    reply["body"]["settings"][0]["value"] = True
    out = _page(engine, f"PATCHED.push({json.dumps(reply, ensure_ascii=False)}); view.openSettings('work_briefing');"
                        "fire('change', {set: 'enabled'}, true);")
    assert out["patches"] == [{"path": "/api/settings/work_briefing", "body": {"base": "v1", "changes": {"enabled": True}}}]
    assert "已保存" in out["form"]


def test_the_panel_and_unsaved_text_survive_the_page_redrawing_itself(engine):
    """改完设置，服务重新发布一次图，页面原地重画：面板不能关，表单不能重建，打了一半的字还在。"""
    out = _page(engine, "view.openSettings('work_briefing'); fire('input', {draft: 'priority_rules'}, 'half typed');"
                        "var kept = view.capture(); view.dispose(); view = start(DATA, kept, API);"
                        "view.openSettings('work_briefing');"
                        "var st = settingsPanel(API, DATA.strings).state();"
                        "if (!st.open || st.form.dirty.join() !== 'priority_rules') throw new Error(JSON.stringify(st));"
                        "fire('click', {save: 'priority_rules'});")
    assert out["gets"] == ["/api/settings/work_briefing"]                 # 没有重新去要、没有重建
    assert out["box"]["hidden"] is False
    # 重画之后接着点「保存」，交出去的就是重画前打的那些字
    assert out["patches"][0]["body"]["changes"] == {"priority_rules": "half typed"}


def test_closing_with_unsaved_text_warns_once_then_closes(engine):
    out = _page(engine, "view.openSettings('work_briefing'); fire('input', {draft: 'priority_rules'}, 'unsaved');"
                        "var p = settingsPanel(API, DATA.strings); if (p.close()) throw new Error('closed at once');")
    assert out["box"]["hidden"] is False and out["note"]
    out = _page(engine, "view.openSettings('work_briefing'); fire('input', {draft: 'priority_rules'}, 'unsaved');"
                        "var p = settingsPanel(API, DATA.strings); p.close(); if (!p.close()) throw new Error('still open');")
    assert out["box"]["hidden"] is True


def test_closing_without_unsaved_text_just_closes_and_escape_works_too(engine):
    out = _page(engine, "view.openSettings('work_briefing');"
                        "_docListeners.keydown({key: 'Escape', preventDefault: function () {}});")
    assert out["box"]["hidden"] is True


def test_when_the_group_cannot_be_read_the_panel_says_so(engine):
    out = _page(engine, "view.openSettings('work_briefing');", desc="fail")
    assert out["box"]["hidden"] is False and "读不到" in out["form"]


# ───────────────────────── boot.js：网址里带着组名、写请求 ─────────────────────────

BOOT_REPORT = ("\nreturn JSON.stringify({calls: calls, requests: requests, replaced: replaced, store: store, "
               "opened: openedSettings, results: results});")


def _boot(engine, setup: str, steps: str = "") -> dict:
    return _evaluate(engine, FAKE_DOM + FAKE_BROWSER + "var results = [];" + setup + render.bundle(("boot.js",)) + steps + BOOT_REPORT)


def test_an_address_naming_a_group_opens_it_once_the_map_is_drawn(engine):
    out = _boot(engine, "location.hash = '#TOK&settings=work_briefing'; responses = [" + json.dumps(
        {"status": 200, "data": {"revision": 1, "meta": {}, "page": {"lang": "zh-CN", "title": "t"}}}) + ", {\"hang\": true}];")
    assert out["calls"][0] == {"path": "/api/graph", "token": "TOK"}      # 组名不是令牌的一部分
    assert out["store"]["panorama-token"] == "TOK" and out["replaced"] == ["/"]
    assert out["opened"] == ["work_briefing"]


def test_a_plain_address_opens_no_group(engine):
    out = _boot(engine, "location.hash = '#TOK'; responses = [" + json.dumps(
        {"status": 200, "data": {"revision": 1, "meta": {}, "page": {"lang": "zh-CN", "title": "t"}}}) + ", {\"hang\": true}];")
    assert out["opened"] == []


def test_a_write_is_a_json_patch_with_the_token_and_every_answer_reaches_the_form(engine):
    first = json.dumps({"status": 200, "data": {"revision": 1, "meta": {}, "page": {"lang": "zh-CN", "title": "t"}}})
    out = _boot(engine, f"location.hash = '#TOK'; responses = [{first}, {{\"hang\": true}},"
                        "{\"status\": 422, \"data\": {\"error\": \"invalid\", \"errors\": [{\"id\": \"time\", \"code\": \"rejected\"}]}}];",
                "lastApi.patch('/api/settings/work_briefing', {base: 'v1', changes: {time: 'x'}})"
                ".then(function (r) { results.push(r); });"
                "lastApi.patch('/api/settings/work_briefing', {base: 'v1', changes: {time: 'y'}})"
                ".then(function (r) { results.push(r); }, function () { results.push('lost'); });")
    patch = out["requests"][2]
    assert patch["method"] == "PATCH" and patch["headers"]["X-Panorama-Token"] == "TOK"
    assert patch["headers"]["Content-Type"] == "application/json"
    assert json.loads(patch["body"]) == {"base": "v1", "changes": {"time": "x"}}
    assert out["results"] == [{"status": 422, "body": {"error": "invalid", "errors": [{"id": "time", "code": "rejected"}]}}, "lost"]
