# -*- coding: utf-8 -*-
"""配置全景的设置表单（``page/form.js``）：按本机服务给的描述画六种通用控件，改了就按保存时机交出去，
服务的每一种回答（存上了、值已经变了、哪几项不对、忙、连接断了）都有对应的样子。

页面上还没有入口（路线图 M3 第 4 步才接上），所以这里直接在 Qt 自带的 JS 引擎里跑这个模块：
一个假的宿主元素记下事件监听，测试自己触发事件；``send`` 是假的，同步返回、记下每次交出去的改动。
表单的描述有两种来源：手写的（覆盖每一种控件和边角），和 Python 那边 ``settings_api.describe`` 真给的（两边对得上）。
"""
from __future__ import annotations

import json

import pytest

from pet import i18n
from pet import settings_table as st
from pet import work_briefing as wb
from pet.panorama import render
from pet.panorama import settings_api as api
from tests.test_panorama_page import FAKE_DOM, _evaluate


@pytest.fixture(scope="module")
def engine():
    from PySide6.QtQml import QJSEngine
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])                # 不能是 QCoreApplication，见 test_panorama_page 的同名夹具
    js = QJSEngine()
    yield js
    del js, app

#: 假的宿主元素和事件；``send`` 按 ``replies`` 依次回答（没有了 = 连接断了；``"hang"`` = 一直不回）
HARNESS = """
var listeners = {}, sent = [];
var host = {innerHTML: '', addEventListener: function (t, fn) { listeners[t] = fn; },
  querySelector: function () { return null; }, querySelectorAll: function () { return []; }};
function done(value, failed) {
  return {then: function (ok, err) {
    var handler = failed ? err : ok;
    if (!handler) return done(value, failed);
    try { return done(handler(value), false); } catch (e) { return done(e, true); }
  }};
}
function sender(replies) {
  return function (changes, base) {
    sent.push({changes: changes, base: base});
    var r = replies.shift();
    if (r === 'hang') return {then: function () { return this; }};
    return r === undefined ? done(new Error('gone'), true) : done(r, false);
  };
}
function target(data, value, checked) {
  var t = {dataset: data, value: value === undefined ? '' : value, checked: !!checked};
  t.closest = function (sel) {
    var m = sel.match(/^\\[data-([a-z-]+)\\]$/);
    if (!m) return null;
    var key = m[1].replace(/-([a-z])/g, function (_, c) { return c.toUpperCase(); });
    return key in t.dataset ? t : null;
  };
  return t;
}
function fire(type, data, value, checked) { listeners[type]({type: type, target: target(data, value, checked), preventDefault: function () {}}); }
"""

REPORT = "return JSON.stringify({html: host.innerHTML, sent: sent, state: f.state()});"


def _desc(**changes) -> dict:
    """一份手写的描述：六种控件各一项，外加一项依赖开关的、一项收在「高级」里的。"""
    def row(sid, control, value, **extra):
        return {"id": sid, "control": control, "title": f"T:{sid}", "hint": f"H:{sid}", "value": value, "default": value,
                "choices": [], "commit": "on_finish" if control in ("text", "long_text") else "immediate",
                "disclosure": "primary", "depends_on": "", "builtin": None, **extra}

    desc = {"group": "demo", "title": "Demo", "zone": "work", "available": True, "unavailable": "", "version": "v1", "settings": [
        row("on", "toggle", False),
        row("level", "choice", "high", choices=["low", "high"]),
        row("time", "choice_or_text", "09:00", choices=["09:00", "10:00"]),
        row("count", "number", 3),
        row("name", "text", "abc"),
        row("prompt", "long_text", "", builtin="BUILTIN TEXT", disclosure="advanced"),
        row("rules", "long_text", "old rules", depends_on="on"),
    ]}
    desc.update(changes)
    return desc


def _ok(desc: dict, **values) -> dict:
    """服务对一次成功写入的回答：新的描述 + 真的变了的那几项。"""
    body = json.loads(json.dumps(desc))
    body["version"] = "v2"
    for row in body["settings"]:
        if row["id"] in values:
            row["value"] = values[row["id"]]
    body["changed"] = list(values)
    return {"status": 200, "body": body}


def _run(engine, desc: dict, replies: list, steps: str, *, language: str = "zh") -> dict:
    i18n.set_language(language)
    strings = json.dumps(render.page_strings(), ensure_ascii=False)
    return _evaluate(engine, FAKE_DOM + HARNESS + render.bundle(("util.js", "form.js")) + f"""
        var f = settingsForm(host, {strings}, sender({json.dumps(replies, ensure_ascii=False)}), {{}});
        f.show({json.dumps(desc, ensure_ascii=False)});
        {steps}
        {REPORT}""")


@pytest.fixture(autouse=True)
def _chinese():
    i18n.set_language("zh")
    yield
    i18n.set_language("zh")


# ───────────────────────── 画 ─────────────────────────

def test_every_setting_is_drawn_with_its_title_hint_and_value_in_order(engine):
    out = _run(engine, _desc(), [], "")
    html = out["html"]
    for sid in ("on", "level", "time", "count", "name", "rules"):
        assert f'data-row="{sid}"' in html and f"T:{sid}" in html and f"H:{sid}" in html
    assert html.index('data-row="on"') < html.index('data-row="level"') < html.index('data-row="rules"')
    assert 'role="switch"' in html and 'value="high" selected' in html and 'value="3"' in html and 'value="abc"' in html
    assert ">old rules</textarea>" in html
    assert 'data-row="prompt"' not in html and "高级（1）" in html               # 「高级」默认收着，说有几项


def test_the_advanced_section_opens_and_shows_the_builtin_text_when_the_value_is_empty(engine):
    html = _run(engine, _desc(), [], "fire('click', {advanced: ''});")["html"]
    assert 'data-row="prompt"' in html and ">BUILTIN TEXT</textarea>" in html and "正在用内置的" in html
    assert 'data-builtin="prompt"' in html


def test_labels_point_at_their_controls_and_the_status_line_is_announced(engine):
    html = _run(engine, _desc(), [], "")["html"]
    assert '<label for="f-demo-time"' in html and 'id="f-demo-time"' in html
    assert 'role="status"' in html and 'aria-live="polite"' in html


def test_text_from_the_service_is_escaped_everywhere(engine):
    desc = _desc()
    desc["settings"][0].update(title="<b>t</b>", hint="<img src=x onerror=1>")
    desc["settings"][1].update(choices=["<x>", "high"], value="high")
    desc["settings"][4]["value"] = '"><script>1</script>'
    html = _run(engine, desc, [], "")["html"]
    assert "<b>t" not in html and "<img" not in html and "<script>" not in html and 'value="<x>"' not in html
    assert "&lt;b&gt;t&lt;/b&gt;" in html and "&quot;&gt;&lt;script&gt;" in html


# ───────────────────────── 开关和下拉：一动就存 ─────────────────────────

def test_a_toggle_is_sent_at_once_with_the_version_and_the_reply_is_shown(engine):
    desc = _desc()
    out = _run(engine, desc, [_ok(desc, on=True)], "fire('change', {set: 'on'}, '', true);")
    assert out["sent"] == [{"changes": {"on": True}, "base": "v1"}]
    assert out["state"]["version"] == "v2" and "已保存" in out["html"] and 'data-set="on" checked' in out["html"]


def test_a_choice_is_sent_as_its_value(engine):
    desc = _desc()
    out = _run(engine, desc, [_ok(desc, level="low")], "fire('change', {set: 'level'}, 'low');")
    assert out["sent"][0]["changes"] == {"level": "low"} and 'value="low" selected' in out["html"]


def test_choosing_custom_opens_a_text_box_and_only_its_value_is_sent(engine):
    desc = _desc()
    out = _run(engine, desc, [_ok(desc, time="07:05")], """
        fire('change', {set: 'time'}, '__custom__');
        var opened = host.innerHTML;
        fire('change', {custom: 'time'}, '  07:05 ');""")
    assert out["sent"] == [{"changes": {"time": "07:05"}, "base": "v1"}]
    assert 'data-custom="time"' in out["html"] and 'value="07:05"' in out["html"]


def test_a_value_outside_the_choices_shows_up_in_the_custom_box(engine):
    html = _run(engine, _desc(), [], "")["html"]
    assert 'data-custom="time"' not in html                              # 09:00 在可选值里：不开自填框
    desc = _desc()
    desc["settings"][2]["value"] = "07:45"
    html = _run(engine, desc, [], "")["html"]
    assert 'value="__custom__" selected' in html and 'data-custom="time"' in html and 'value="07:45"' in html


def test_a_number_is_sent_as_a_number_and_a_non_number_is_not_sent(engine):
    desc = _desc()
    out = _run(engine, desc, [_ok(desc, count=5)], "fire('change', {set: 'count'}, '5'); fire('change', {set: 'count'}, 'abc');")
    assert out["sent"] == [{"changes": {"count": 5}, "base": "v1"}]
    assert out["state"]["errors"] == {"count": "type"} and "类型不对" in out["html"]


# ───────────────────────── 文本：等用户点保存 ─────────────────────────

def test_typing_in_text_does_not_send_marks_it_unsaved_and_save_sends_it(engine):
    desc = _desc()
    desc["settings"][0]["value"] = True                                   # rules 依赖这个开关
    out = _run(engine, desc, [_ok(desc, rules="new rules")], """
        fire('input', {draft: 'rules'}, 'new rules  ');
        var before = sent.length, dirty = f.state().dirty;
        fire('click', {save: 'rules'});
        sent.push({before: before, dirty: dirty});""")
    assert out["sent"][-1] == {"before": 0, "dirty": ["rules"]}
    assert out["sent"][0] == {"changes": {"rules": "new rules"}, "base": "v1"}
    assert out["state"]["dirty"] == [] and ">new rules</textarea>" in out["html"]


def test_revert_drops_an_unsaved_edit(engine):
    out = _run(engine, _desc(), [], "fire('input', {draft: 'name'}, 'typed'); fire('click', {revert: 'name'});")
    assert out["sent"] == [] and out["state"]["dirty"] == [] and 'value="abc"' in out["html"]


def test_saving_the_builtin_text_unchanged_stores_empty_and_restore_puts_the_builtin_back(engine):
    desc = _desc()
    desc["settings"][5]["value"] = "my own prompt"
    out = _run(engine, desc, [_ok(desc, prompt="")], """
        fire('click', {advanced: ''});
        fire('click', {builtin: 'prompt'});
        fire('click', {save: 'prompt'});""")
    assert out["sent"] == [{"changes": {"prompt": ""}, "base": "v1"}]
    plain = _run(engine, _desc(), [], "fire('click', {advanced: ''}); fire('input', {draft: 'prompt'}, ' BUILTIN TEXT\\n');")
    assert plain["state"]["dirty"] == []                                  # 内置文字原样：不算改过


def test_unsaved_text_survives_a_save_of_another_setting(engine):
    desc = _desc()
    out = _run(engine, desc, [_ok(desc, on=True)], "fire('input', {draft: 'name'}, 'half typed'); fire('change', {set: 'on'}, '', true);")
    assert out["state"]["dirty"] == ["name"] and 'value="half typed"' in out["html"]


# ───────────────────────── 服务说不 ─────────────────────────

def test_an_invalid_reply_marks_the_fields_and_keeps_what_was_typed(engine):
    reply = {"status": 422, "body": {"error": "invalid", "errors": [{"id": "name", "code": "rejected"}]}}
    out = _run(engine, _desc(), [reply], "fire('input', {draft: 'name'}, 'bad name'); fire('click', {save: 'name'});")
    assert out["state"]["errors"] == {"name": "rejected"} and out["state"]["dirty"] == ["name"]
    assert "肥鱼不认这个值" in out["html"] and 'value="bad name"' in out["html"] and "没存上" in out["html"]


def test_an_invalid_toggle_goes_back_to_what_is_stored(engine):
    reply = {"status": 422, "body": {"error": "invalid", "errors": [{"id": "on", "code": "type"}]}}
    out = _run(engine, _desc(), [reply], "fire('change', {set: 'on'}, '', true);")
    assert 'data-set="on" checked' not in out["html"] and out["state"]["errors"] == {"on": "type"}


def test_a_stale_reply_takes_the_current_values_and_keeps_unsaved_text(engine):
    current = _desc(version="v9")
    current["settings"][1]["value"] = "low"
    reply = {"status": 409, "body": {"error": "stale", "current": current}}
    out = _run(engine, _desc(), [reply], "fire('input', {draft: 'name'}, 'mine'); fire('click', {save: 'name'});")
    assert out["state"]["version"] == "v9" and 'value="low" selected' in out["html"] and "值已经变了" in out["html"]
    assert out["state"]["dirty"] == ["name"]


@pytest.mark.parametrize("reply, words", [
    ({"status": 503, "body": {"error": "busy"}}, "肥鱼忙"),
    ({"status": 409, "body": {"error": "unavailable"}}, "用不了"),
    ({"status": 500, "body": {"error": "save_failed"}}, "没存上"),
    (None, "连接断了"),
])
def test_other_refusals_say_what_happened_and_change_nothing(engine, reply, words):
    out = _run(engine, _desc(), [reply] if reply else [], "fire('change', {set: 'on'}, '', true);")
    assert words in out["html"] and out["state"]["version"] == "v1" and 'data-set="on" checked' not in out["html"]


# ───────────────────────── 不能改的时候 ─────────────────────────

def test_while_a_save_is_on_its_way_everything_is_disabled_and_nothing_else_is_sent(engine):
    out = _run(engine, _desc(), ["hang"], "fire('change', {set: 'on'}, '', true); fire('change', {set: 'level'}, 'low');")
    assert len(out["sent"]) == 1 and "保存中" in out["html"] and out["html"].count(" disabled") >= 7


def test_a_group_that_cannot_work_here_says_why_and_offers_nothing_to_change(engine):
    out = _run(engine, _desc(available=False, unavailable="这台机器没有 WSL"), [], "fire('change', {set: 'on'}, '', true);")
    assert out["sent"] == [] and "这台机器没有 WSL" in out["html"] and out["html"].count(" disabled") >= 6


def test_a_setting_that_depends_on_a_switch_is_disabled_while_the_switch_is_off(engine):
    off = _run(engine, _desc(), [], "fire('input', {draft: 'rules'}, 'x'); fire('click', {save: 'rules'});")
    assert off["sent"] == [] and 'data-draft="rules" disabled' in off["html"]
    desc = _desc()
    desc["settings"][0]["value"] = True
    assert 'data-draft="rules" disabled' not in _run(engine, desc, [], "")["html"]


# ───────────────────────── 和 Python 那边对得上 ─────────────────────────

@pytest.mark.parametrize("language", ["zh", "en"])
def test_the_real_description_of_the_work_briefing_draws_every_setting(engine, monkeypatch, language):
    monkeypatch.setattr(st.claude_hooks, "wsl_exe", lambda: "wsl.exe")
    i18n.set_language(language)
    desc = api.describe(st.group("work_briefing"), wb.normalize({"time": "07:05", "model": "claude-sonnet-5-5"}))
    out = _run(engine, desc, [], "fire('click', {advanced: ''});", language=language)
    html = out["html"]
    for row in desc["settings"]:
        assert f'data-row="{row["id"]}"' in html, row["id"]
    assert html.count('role="switch"') == 8                               # 开关、只在工作日、6 个来源
    assert 'data-custom="time"' in html and 'value="07:05"' in html and 'data-custom="model"' in html
    assert html.count('data-builtin="') == 2                              # 两种语言的提示词
    assert "panorama." not in html


def test_every_form_string_exists_in_both_languages():
    keys = [key for key in render.PAGE_KEYS if key.startswith("form_")]
    assert len(keys) >= 15
    for language in ("zh", "en"):
        table = i18n.table(language)
        assert [key for key in keys if not str(table.get(f"panorama.ui.{key}") or "").strip()] == []
