# -*- coding: utf-8 -*-
"""笔记页的脚本（QJSEngine + 假 DOM）：``notelist.js`` 的纯函数直接调；``notes.js`` 整条路——取令牌、要数据、摆页面、选中、
动作 POST、等更新、连接断了。DOM 接线（closest / scrollIntoView）只在真浏览器里核对。"""
from __future__ import annotations

import json

import pytest
from PySide6.QtQml import QJSEngine
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet.panorama import render
from tests.test_panorama_page import FAKE_BROWSER, FAKE_DOM, _evaluate


@pytest.fixture(scope="module")
def engine():
    app = QApplication.instance() or QApplication([])
    i18n.set_language("zh")
    js = QJSEngine()
    yield js
    del js, app


S = {key: f"[{key}]" for key in render.NOTES_KEYS}
S.update(notes_count_open="{n} 待办", notes_count_due="{n} 有提醒", notes_count_busy="{n} 总结中", notes_count_done="{n} 已完成",
         notes_remind="提醒 {when}", notes_overdue="已过（{when}）", notes_confirm_delete="删「{title}」？", notes_failed="没办成：{error}",
         notes_watch_last="上次 {when}（{ago}）", notes_watch_found="{n} 条", notes_watch_next="下次 {when}")


def _note(**over):
    base = {"name": "n1", "title": "看一下 <PR>", "kind": "link", "status": "open", "open": True, "busy": False, "created": "2026-11-19T10:00:00",
            "created_text": "11-19 10:00", "remind_at": "2026-11-20T09:00:00", "remind_text": "11-20 09:00", "overdue": True, "reason": "早上先看",
            "tags": ["pr", "a&b"], "summary": "评审 <那个> PR", "details_html": "<ul>\n<li>先看</li>\n</ul>",
            "original_html": '<a href="https://x/1">https://x/1</a> 看一下', "links": ["https://x/1"],
            "usage": [{"key": "model", "text": "sonnet", "tip": "模型"}]}
    base.update(over)
    return base


DUE, LATER, BUSY, DONE = (_note(), _note(name="n2", title="Jira 单", kind="jira", remind_at="2026-11-21T09:00:00", remind_text="11-21 09:00", overdue=False, links=[], usage=[]),
                          _note(name="n3", title="刚记的", kind="text", busy=True, remind_at="", remind_text="", overdue=False, summary="", details_html="", links=[]),
                          _note(name="n4", title="做完的", kind="confluence", status="done", open=False, remind_at="", remind_text="", overdue=False, reason=""))
NOTES = [DUE, LATER, BUSY, DONE]
COUNTS = {"open": 3, "due": 2, "busy": 1, "done": 1}


def _pure(engine, expr: str):
    return _evaluate(engine, render.bundle(("util.js", "notelist.js")) + f"\nvar S = {json.dumps(S, ensure_ascii=False)}; var NOTES = {json.dumps(NOTES, ensure_ascii=False)};"
                     f"\nreturn JSON.stringify({expr});")


# ───────────────────────── 纯函数 ─────────────────────────

def test_filters_and_search_pick_the_right_notes(engine):
    names = lambda f, q="": _pure(engine, f"filterNotes(NOTES, '{f}', '{q}').map(function (n) {{ return n.name; }})")  # noqa: E731
    assert names("all") == ["n1", "n2", "n3", "n4"] and names("open") == ["n1", "n2", "n3"] and names("due") == ["n1", "n2"]
    assert names("busy") == ["n3"] and names("done") == ["n4"]
    assert names("all", "jira") == ["n2"] and names("all", "评审") == ["n1", "n2", "n4"] and names("open", "a&b") == ["n1", "n2", "n3"], "搜标题、摘要、标签、类型，不分大小写（n3 没有摘要）"
    assert names("all", "没有的") == []


def test_counts_and_filter_chips_show_numbers_and_hide_the_busy_chip_when_nothing_is_summarizing(engine):
    assert _pure(engine, "countsHtml({open: 3, due: 2, busy: 1, done: 1}, S)") == (
        '<span class="c open"><b>3</b>待办</span><span class="c due"><b>2</b>有提醒</span><span class="c busy"><b>1</b>总结中</span><span class="c done"><b>1</b>已完成</span>')
    assert '"c busy"' not in _pure(engine, "countsHtml({open: 1, due: 0, busy: 0, done: 0}, S)")
    chips = _pure(engine, "filterChips({open: 3, due: 2, busy: 0, done: 1}, 'due', S)")
    assert 'data-f="busy"' not in chips and '<button class="chip on" data-f="due" aria-pressed="true">[notes_filter_due]<span class="n">2</span></button>' in chips
    assert chips.startswith('<button class="chip" data-f="all" aria-pressed="false">[notes_filter_all]<span class="n">4</span></button>')
    assert 'data-f="busy"' in _pure(engine, "filterChips({open: 3, due: 2, busy: 1, done: 1}, 'all', S)")


def test_a_row_carries_kind_selection_state_and_the_reminder(engine):
    row = _pure(engine, "rowHtml(NOTES[0], true, S)")
    assert row.startswith('<a class="row kind-link sel" href="#" data-note="n1" aria-current="true">')
    assert '<span class="t">看一下 &lt;PR&gt;</span>' in row and '<span class="ov">已过（11-20 09:00）</span>' in row
    assert '<span class="tag">pr</span><span class="tag">a&amp;b</span>' in row and row.endswith('<span class="st">●</span></a>')
    assert 'class="row kind-jira"' in _pure(engine, "rowHtml(NOTES[1], false, S)") and "提醒 11-21 09:00" in _pure(engine, "rowHtml(NOTES[1], false, S)")
    busy = _pure(engine, "rowHtml(NOTES[2], false, S)")
    assert 'class="row kind-text busy"' in busy and '<span class="st">[notes_busy_short]</span>' in busy
    done = _pure(engine, "rowHtml(NOTES[3], false, S)")
    assert 'class="row kind-confluence done"' in done and "[notes_done_mark]" in done and done.endswith('<span class="st">✓</span></a>')
    assert _pure(engine, "rowsHtml(NOTES, 'n2', S)").count('aria-current="true"') == 1


def test_the_detail_shows_summary_points_original_usage_and_the_right_buttons(engine):
    assert _pure(engine, "detailHtml(null, S)") == '<p class="pick">[notes_select]</p>'
    d = _pure(engine, "detailHtml(NOTES[0], S)")
    assert d.startswith('<header class="head kind-link"><span class="kind">[notes_kind_link]</span><h2>看一下 &lt;PR&gt;</h2><span class="badge ov">已过（11-20 09:00）</span></header>')
    assert '<p class="meta"><span>11-19 10:00</span><span>早上先看</span><span class="tag">pr</span><span class="tag">a&amp;b</span></p>' in d
    assert '<p class="summary">评审 &lt;那个&gt; PR</p><div class="points"><ul>\n<li>先看</li>\n</ul></div>' in d
    assert '<pre class="orig"><a href="https://x/1">https://x/1</a> 看一下</pre>' in d and '<span class="u" title="模型">sonnet</span>' in d
    acts = d[d.index('<div class="acts"'):]
    assert acts.startswith('<div class="acts" data-note="n1"><button class="btn" data-op="done">[notes_btn_done]</button><button class="btn ghost" data-op="open_link">')
    assert 'data-op="obsidian"' in acts and '<button class="btn ghost" data-op="resummarize">' in acts
    assert 'data-op="snooze" data-minutes="60"' in acts and 'data-minutes="180"' in acts and 'data-minutes="-1"' in acts
    assert acts.endswith('<button class="btn ghost danger" data-op="delete">[notes_btn_delete]</button></div></div>')
    later = _pure(engine, "detailHtml(NOTES[1], S)")
    assert 'data-op="open_link"' not in later and '<span class="badge">提醒 11-21 09:00</span>' in later and '<div class="usage">' not in later
    busy = _pure(engine, "detailHtml(NOTES[2], S)")
    assert '<p class="summary busy">[notes_busy]</p>' in busy and 'data-op="done"' not in busy and 'data-op="resummarize" disabled>' in busy
    done = _pure(engine, "detailHtml(NOTES[3], S)")
    assert 'data-op="done"' not in done and 'data-op="snooze"' not in done and '<span class="badge">[notes_done_mark]</span>' in done


def test_repo_status_and_watch_strip(engine):
    assert _pure(engine, "repoHtml({ready: true, status: ''}, S)") == ""
    assert _pure(engine, "repoHtml({ready: true, status: 'hook <x>'}, S)") == '<span title="hook &lt;x&gt;">hook &lt;x&gt;</span><button class="btn ghost" data-op="push">[notes_btn_push]</button>'
    assert "data-op" not in _pure(engine, "repoHtml({ready: false, status: '没找到'}, S)"), "仓库都不在就不给「再推一次」"
    assert _pure(engine, "watchHtml({}, S)") == '<span class="w">[notes_watch_never]</span>'
    w = _pure(engine, "watchHtml({checked_text: '14:32', ago_text: '12 分钟前', found: 2, next_text: '14:47', summary: '两条 <急>', error: '', busy: true}, S)")
    assert w == ('<span class="w">上次 14:32（12 分钟前）</span><span class="w"><b>2</b> 条</span><span class="w">下次 14:47</span>'
                 '<span class="w busy">[notes_watch_busy]</span><p class="sum">两条 &lt;急&gt;</p>')
    assert _pure(engine, "watchHtml({checked_text: 'x', error: '坏了'}, S)").endswith('<span class="bad">坏了</span>')


# ───────────────────────── 页面脚本 ─────────────────────────

NOTES_DOM = """
document.documentElement.dataset = {};
location.pathname = '/report/work_notes';
location.origin = 'http://127.0.0.1:1';
var confirms = [], answer = true;
var confirm = function (text) { confirms.push(text); return answer; };
var clicks = {};
['add', 'text', 'rows', 'detail', 'filters', 'search', 'repo', 'folder', 'watch', 'actions'].forEach(function (id) {
  document.getElementById(id).addEventListener = function (type, fn) { clicks[id + ':' + type] = fn; };
});
var dom = function () { var el = document.getElementById; return {title: el('title').textContent, counts: el('counts').innerHTML,
  composerHidden: el('composer').hidden, placeholder: el('text').placeholder, add: el('add').textContent, addDisabled: el('add').disabled,
  text: el('text').value, emptyHidden: el('empty').hidden, empty: el('empty').textContent, gridHidden: el('grid').hidden,
  filters: el('filters').innerHTML, rows: el('rows').innerHTML, detail: el('detail').innerHTML, status: el('status').textContent,
  statusClass: el('status').className, repo: el('repo').innerHTML, searchHidden: el('search').hidden, watchHidden: el('watch').hidden,
  watch: el('watch').innerHTML, lost: el('lost').hidden, theme: document.documentElement.dataset.theme, title_tag: document.title,
  settings: el('settings-link').href, folderHidden: el('folder').hidden}; };
var target = function (dataset, cls) { return {closest: function (sel) { return (!cls || sel.indexOf(cls) >= 0 || sel.indexOf('data-') >= 0) ? {dataset: dataset, disabled: false, closest: function (inner) { return inner === '.acts' ? {dataset: {note: 'n1'}} : {dataset: dataset}; }} : null; }}; };
"""


def _report(**over):
    base = {"id": "work_notes", "page": "notes", "title": "工作笔记", "theme": "dark", "available": True, "settings_focus": "work_notes",
            "composer": True, "placeholder": "粘贴…", "add_label": "记下", "add_hint": "h", "empty_text": "还没有笔记", "notes": NOTES, "counts": COUNTS,
            "repo": {"ready": True, "dir": "C:/r", "status": ""}, "watch": None, "action": None, "actions": []}
    base.update(over)
    return base


def _payload(revision=1, **over):
    return json.dumps(json.loads(render.report_payload(_report(**over), revision=revision, page="notes")), ensure_ascii=False)


def _ok(data: str) -> str:
    return '{"status": 200, "data": ' + data + "}"


def _page(engine, responses: list[str], steps: str = "", hash_: str = "#tok-1") -> dict:
    setup = NOTES_DOM + f"location.hash = '{hash_}';\nresponses = [" + ",".join(responses) + "];\n"
    return _evaluate(engine, FAKE_DOM + FAKE_BROWSER + setup + render.bundle(render.NOTES_MODULES) + steps +
                     "\nreturn JSON.stringify({dom: dom(), confirms: confirms, requests: requests.map(function (r) { return {path: r.path, method: r.method, "
                     "token: r.headers['X-Panorama-Token'], body: r.body ? JSON.parse(r.body) : undefined}; }), timers: timers.length, hash: location.hash, store: store});")


def test_the_page_takes_the_token_asks_for_its_notes_and_lays_them_out(engine):
    out = _page(engine, [_ok(_payload()), '{"hang": true}'])
    assert out["requests"][0] == {"path": "/api/report/work_notes", "method": "GET", "token": "tok-1"}
    assert out["requests"][1]["path"] == "/api/report/work_notes?after=1" and out["hash"] == ""
    dom = out["dom"]
    assert dom["title"] == "工作笔记" and dom["title_tag"] == "工作笔记 · 大肥鱼" and dom["theme"] == "dark" and dom["lost"] is True
    assert dom["composerHidden"] is False and dom["placeholder"] == "粘贴…" and dom["add"] == "记下" and dom["watchHidden"] is True
    assert dom["emptyHidden"] is True and dom["gridHidden"] is False and dom["searchHidden"] is True, "4 条还用不上搜索框"
    assert "<b>3</b>待办" in dom["counts"] and dom["repo"] == "" and dom["folderHidden"] is False
    assert dom["settings"] == "http://127.0.0.1:1/#tok-1&settings=work_notes"
    assert dom["rows"].count('<a class="row') == 4 and 'data-note="n1" aria-current="true"' in dom["rows"], "默认选中第一条未完成的"
    assert "<h2>看一下 &lt;PR&gt;</h2>" in dom["detail"] and out["store"]["report-token"] == "tok-1"


def test_the_fragment_can_name_the_note_to_select_and_the_choice_is_remembered(engine):
    out = _page(engine, [_ok(_payload()), '{"hang": true}'], hash_="#tok-1&note=n2")
    assert 'data-note="n2" aria-current="true"' in out["dom"]["rows"] and "<h2>Jira 单</h2>" in out["dom"]["detail"]
    assert out["store"]["notes-selected:work_notes"] == "n2"
    out = _page(engine, [_ok(_payload()), '{"hang": true}'], steps="\nclicks['rows:click']({target: target({note: 'n4'}), preventDefault: function () {}});")
    assert "<h2>做完的</h2>" in out["dom"]["detail"] and out["store"]["notes-selected:work_notes"] == "n4"


def test_filter_chips_and_search_narrow_the_list_without_asking_the_service(engine):
    out = _page(engine, [_ok(_payload()), '{"hang": true}'], steps="\nclicks['filters:click']({target: target({f: 'done'}, '.chip')});")
    assert out["dom"]["rows"].count('<a class="row') == 1 and 'data-note="n4"' in out["dom"]["rows"] and len(out["requests"]) == 2
    out = _page(engine, [_ok(_payload()), '{"hang": true}'], steps="\nclicks['search:input']({target: {value: 'jira'}});")
    assert out["dom"]["rows"].count('<a class="row') == 1 and 'data-note="n2"' in out["dom"]["rows"]


def test_empty_and_unavailable_states(engine):
    dom = _page(engine, [_ok(_payload(notes=[], counts={"open": 0, "due": 0, "busy": 0, "done": 0})), '{"hang": true}'])["dom"]
    assert dom["emptyHidden"] is False and dom["empty"] == "还没有笔记" and dom["gridHidden"] is True and dom["composerHidden"] is False
    dom = _page(engine, [_ok(_payload(available=False, notes=[])), '{"hang": true}'])["dom"]
    assert dom["empty"] == "这台机器上没有这项功能（工作笔记要装了 WSL、并在设置里打开才有）。" and dom["composerHidden"] is True and dom["folderHidden"] is True


def test_adding_a_note_posts_the_text_and_clears_the_box_when_saved(engine):
    steps = ("\ndocument.getElementById('text').value = '  ';\nclicks['add:click']();"
             "\nvar s1 = dom().status;\ndocument.getElementById('text').value = '记 https://x/2';"
             "\nresponses.push({status: 200, data: {report: 'work_notes', op: 'add', state: 'saved', name: 'n9'}});\nclicks['add:click']();")
    out = _page(engine, [_ok(_payload()), '{"hang": true}'], steps + "\nvar s2 = dom();")
    assert out["requests"][2] == {"path": "/api/actions/note", "method": "POST", "token": "tok-1", "body": {"report": "work_notes", "op": "add", "name": "", "text": "记 https://x/2"}}
    assert len(out["requests"]) == 3, "空的不发请求"
    assert out["dom"]["text"] == "" and out["dom"]["status"] == "已记下，WSL 里的 Claude Code 正在总结…" and out["dom"]["statusClass"] == "status ok"
    assert out["store"]["notes-selected:work_notes"] == "n9", "新记的那条变成选中的，等服务发布新数据时就显示它"


def test_ctrl_enter_in_the_box_also_saves(engine):
    steps = ("\ndocument.getElementById('text').value = 'x';\nresponses.push({status: 200, data: {state: 'saved', name: 'n9'}});"
             "\nclicks['text:keydown']({key: 'Enter', ctrlKey: true, preventDefault: function () {}});"
             "\nclicks['text:keydown']({key: 'Enter', ctrlKey: false, preventDefault: function () {}});")
    out = _page(engine, [_ok(_payload()), '{"hang": true}'], steps)
    assert [r["path"] for r in out["requests"]].count("/api/actions/note") == 1


def test_detail_buttons_post_their_op_delete_asks_first_and_the_answer_is_said(engine):
    steps = ("\nresponses.push({status: 200, data: {state: 'done'}});\nclicks['detail:click']({target: target({op: 'snooze', minutes: '180'}, '[data-op]')});"
             "\nanswer = false;\nclicks['detail:click']({target: target({op: 'delete'}, '[data-op]')});"
             "\nanswer = true;\nresponses.push({status: 200, data: {state: 'done'}});\nclicks['detail:click']({target: target({op: 'delete'}, '[data-op]')});"
             "\nresponses.push({status: 200, data: {state: 'folder'}});\nclicks['detail:click']({target: target({op: 'obsidian'}, '[data-op]')});"
             "\nvar s3 = dom().status;\nresponses.push({status: 503, data: {error: 'unavailable'}});\nclicks['folder:click']();")
    out = _page(engine, [_ok(_payload()), '{"hang": true}'], steps + "\nvar s4 = dom();")
    posts = [r["body"] for r in out["requests"] if r["method"] == "POST"]
    assert posts[0] == {"report": "work_notes", "op": "snooze", "name": "n1", "minutes": 180}
    ask = "删除「看一下 <PR>」？文件会从仓库里删掉并推送，Obsidian 里也会消失。"
    assert out["confirms"] == [ask, ask] and posts[1] == {"report": "work_notes", "op": "delete", "name": "n1"}, "答否不发请求，答是才发"
    assert posts[2]["op"] == "obsidian" and posts[3] == {"report": "work_notes", "op": "folder", "name": ""}
    assert out["dom"]["status"] == "没办成：unavailable" and out["dom"]["statusClass"] == "status bad"


def test_a_newer_copy_redraws_in_place_keeping_the_selection_and_nothing_new_retries_later(engine):
    newer = _payload(revision=2, notes=[LATER, DUE], counts={"open": 2, "due": 2, "busy": 0, "done": 0})
    out = _page(engine, [_ok(_payload()), '{"status": 204}'], steps=f"\nclicks['rows:click']({{target: target({{note: 'n2'}}), preventDefault: function () {{}}}});"
                f"\nresponses.push({{status: 200, data: {newer}}}); responses.push({{hang: true}});\ntick();")
    assert out["timers"] == 0 and out["requests"][-1]["path"] == "/api/report/work_notes?after=2"
    assert out["dom"]["rows"].count('<a class="row') == 2 and 'data-note="n2" aria-current="true"' in out["dom"]["rows"]


def test_losing_the_service_says_so_and_disables_saving(engine):
    out = _page(engine, [_ok(_payload())])
    assert out["dom"]["lost"] is False and out["dom"]["addDisabled"] is True


def test_the_watch_strip_and_its_check_button_use_the_report_action_channel(engine):
    watch = {"checked_text": "14:32", "ago_text": "12 分钟前", "found": 2, "next_text": "14:47", "summary": "两条", "error": "", "busy": False}
    action = {"name": "generate_report", "report": "slack_watch", "label": "现在检查", "hint": ""}
    steps = "\nresponses.push({status: 200, data: {state: 'started'}});\nclicks['watch:click']({target: target({name: 'generate_report', report: 'slack_watch'}, '[data-name]')});"
    out = _page(engine, [_ok(_payload(composer=False, watch=watch, action=action)), '{"hang": true}'], steps)
    assert out["dom"]["watchHidden"] is False and out["dom"]["composerHidden"] is True
    assert '<p class="sum">两条</p>' in out["dom"]["watch"] and out["dom"]["watch"].endswith('<button class="btn" id="action" data-name="generate_report" data-report="slack_watch" title="">现在检查</button>')
    assert out["requests"][-1] == {"path": "/api/actions/generate_report", "method": "POST", "token": "tok-1", "body": {"report": "slack_watch"}}
    assert out["dom"]["status"] == "已出发，大约一分钟…"
