# -*- coding: utf-8 -*-
"""笔记页的 Python 侧：provider 把 ``WorkNotesService`` 的现状翻成页面字典，``note_action`` 把页面的动作分发到服务；
服务按 provider 的 ``page`` 属性选外壳和界面文字；``open_report(note=)`` 把要选中的那条放进片段。
服务用假的（同步、不碰 WSL / git）；笔记文件写在 tmp 里。"""
from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet import slack_watch as sw
from pet import work_notes as wn
from pet.panorama import markdown, notes, render
from pet.panorama.actions import ActionError
from pet.panorama.service import PanoramaService

NOW = dt.datetime(2026, 11, 20, 18, 0)


@pytest.fixture(autouse=True)
def _lang():
    QApplication.instance() or QApplication([])
    i18n.set_language("zh")
    yield
    i18n.set_language("zh")


def _config(theme="dark"):
    return SimpleNamespace(get=lambda key, default=None: {"theme": theme} if key == "context_menu_appearance" else default)


class _Service:
    """``WorkNotesService`` 的替身：笔记在内存里，每个写动作记下来。"""

    def __init__(self, notes_=(), *, busy=(), error="", ready=True, repo_dir=r"C:\repo"):
        self._notes = {note.name: note for note in notes_}
        self.busy_names = frozenset(busy)
        self._error, self._ready, self._repo_dir = error, ready, repo_dir
        self.calls: list[tuple] = []

    def settings(self):
        return {"repo_dir": self._repo_dir}

    def repo_ready(self):
        return self._ready

    def notes(self):
        return list(self._notes.values())

    def note(self, name):
        return self._notes.get(name)

    def last_error(self):
        return self._error

    def add(self, text):
        self.calls.append(("add", text))
        if text == "坏":
            self._error = "磁盘满"
            return None
        note = wn.new_note(text, NOW)
        self._notes[note.name] = note
        return note

    def resummarize(self, name):
        self.calls.append(("resummarize", name))
        return name not in self.busy_names

    def mark_done(self, name):
        self.calls.append(("done", name))
        return self._notes[name]

    def snooze(self, name, minutes):
        self.calls.append(("snooze", name, minutes))
        return self._notes[name]

    def delete(self, name):
        self.calls.append(("delete", name))
        return self._notes.pop(name)

    def open_link(self, name):
        self.calls.append(("open_link", name))
        return bool(self._notes[name].links)

    def open_in_obsidian(self, name):
        self.calls.append(("obsidian", name))
        return name == "n-vault"

    def open_folder(self):
        self.calls.append(("folder",))

    def push_now(self):
        self.calls.append(("push",))


DUE = wn.Note(name="n-due", created="2026-11-19T10:00:00", title="看一下 PR", kind="link", original="https://x.example/pr/1 看一下",
              links=["https://x.example/pr/1"], tags=["pr", "review"], remind_at="2026-11-20T09:00:00", reason="早上先看",
              summary="评审那个 PR", details="- 先看 **测试**\n- 再看 `api.py`", model="claude-sonnet-5-5", tokens_in=1200, tokens_out=300,
              cost_usd=0.012, seconds=41.0, summarized_at="2026-11-19T10:01:00")
LATER = wn.Note(name="n-later", created="2026-11-18T09:00:00", title="Jira 单", kind="jira", original="AEL-1 <b>", remind_at="2026-11-21T09:00:00")
FRESH = wn.Note(name="n-fresh", created="2026-11-20T17:50:00", title="刚记的", kind="text", original="随手一句")
OLD = wn.Note(name="n-old", created="2026-11-17T09:00:00", title="更早的", kind="slack", original="x")
DONE = wn.Note(name="n-done", created="2026-11-19T12:00:00", title="做完的", kind="confluence", original="y", status=wn.STATUS_DONE,
               remind_at="2026-11-19T15:00:00", reason="不该再显示")


# ───────────────────────── provider ─────────────────────────

def test_notes_are_ordered_due_first_then_newest_then_done_and_each_is_translated_for_the_page():
    service = _Service([OLD, DONE, FRESH, LATER, DUE], busy={"n-fresh"})
    data = notes.work_notes(lambda: service, _config(), now=lambda: NOW)()
    assert data["id"] == "work_notes" and data["page"] == "notes" and data["available"] is True and data["composer"] is True
    assert data["title"] == "工作笔记" and data["theme"] == "dark" and data["settings_focus"] == "work_notes"
    assert data["placeholder"].startswith("粘贴") and data["add_label"] == "记下" and "还没有笔记" in data["empty_text"]
    assert [n["name"] for n in data["notes"]] == ["n-due", "n-later", "n-fresh", "n-old", "n-done"], "有提醒的按时间、没提醒的新的在前、已完成最后"
    assert data["counts"] == {"open": 4, "due": 2, "busy": 1, "done": 1}
    due = data["notes"][0]
    assert due["open"] is True and due["overdue"] is True and due["remind_text"] == "11-20 09:00" and due["reason"] == "早上先看"
    assert due["created_text"] == "11-19 10:00" and due["kind"] == "link" and due["tags"] == ["pr", "review"] and due["links"] == ["https://x.example/pr/1"]
    assert due["summary"] == "评审那个 PR" and due["details_html"] == "<ul>\n<li>先看 <strong>测试</strong></li>\n<li>再看 <code class=\"chip\">api.py</code></li>\n</ul>"
    assert due["original_html"] == '<a href="https://x.example/pr/1" target="_blank" rel="noopener noreferrer">https://x.example/pr/1</a> 看一下'
    assert [u["key"] for u in due["usage"]] == ["model", "tokens_in", "tokens_out", "cost", "time"] and due["usage"][0]["text"] == "claude-sonnet-5-5"
    later = data["notes"][1]
    assert later["overdue"] is False and later["original_html"] == "AEL-1 &lt;b&gt;" and later["usage"] == [] and later["details_html"] == ""
    assert data["notes"][2]["busy"] is True
    done = data["notes"][4]
    assert done["open"] is False and done["remind_at"] == "" and done["remind_text"] == "" and done["reason"] == "" and done["overdue"] is False
    assert data["repo"] == {"ready": True, "dir": r"C:\repo", "status": ""}


def test_a_missing_repo_copy_and_a_git_failure_become_the_status_line():
    data = notes.work_notes(lambda: _Service([FRESH], ready=False, error="推不上去"), _config(), now=lambda: NOW)()
    assert data["repo"]["ready"] is False and "没找到仓库副本" in data["repo"]["status"] and data["repo"]["status"].endswith(" · 推不上去")
    data = notes.work_notes(lambda: _Service([FRESH], error="hook 拦住了"), _config(), now=lambda: NOW)()
    assert data["repo"] == {"ready": True, "dir": r"C:\repo", "status": "hook 拦住了"}


def test_without_the_service_the_page_only_says_it_is_unavailable():
    data = notes.work_notes(lambda: None, _config("light"))()
    assert data["available"] is False and data["notes"] == [] and data["theme"] == "light" and data["composer"] is True
    assert data["counts"] == {"open": 0, "due": 0, "busy": 0, "done": 0}


def test_english_follows_the_ui_language():
    i18n.set_language("en")
    data = notes.work_notes(lambda: _Service([FRESH]), _config(), now=lambda: NOW)()
    assert data["title"] == "Work notes" and data["add_label"] == "Save"


def test_linkify_escapes_everything_and_only_turns_bare_urls_into_links():
    assert markdown.linkify("看 https://a.example/x?q=1, 再看 <b>**不是粗体**</b>\n第二行") == (
        '看 <a href="https://a.example/x?q=1" target="_blank" rel="noopener noreferrer">https://a.example/x?q=1</a>, 再看 &lt;b&gt;**不是粗体**&lt;/b&gt;\n第二行')
    assert markdown.linkify("") == ""


# ───────────────────────── Slack 关注页 ─────────────────────────

class _Watch:
    """``SlackWatchService`` 的替身。"""

    def __init__(self, latest=None, *, busy=False, error="", interval=15, started=True):
        self._latest, self.busy, self._error, self._interval, self._started, self.asked = latest, busy, error, interval, started, 0

    def latest(self):
        return self._latest

    def last_error(self):
        return self._error

    def settings(self):
        return {"interval_minutes": self._interval}

    def check_now(self):
        self.asked += 1
        return self._started


RESULT = sw.WatchResult(ok=True, summary="发布窗口在等你拍板", items=[{"title": "a", "key": "k1"}, {"title": "b", "key": "k2"}],
                        checked_at="2026-11-20T17:48:00", seconds=31.0, turns=4)


def test_the_slack_page_has_the_check_strip_the_check_button_and_the_archive_without_a_composer():
    watch, archive = _Watch(RESULT, interval=30), _Service([OLD, DONE])
    data = notes.slack_watch(lambda: archive, lambda: watch, _config(), now=lambda: NOW)()
    assert data["id"] == "slack_watch" and data["page"] == "notes" and data["title"] == "Slack 关注" and data["available"] is True
    assert data["composer"] is False and data["placeholder"] == "" and data["settings_focus"] == "slack_watch" and "Slack 关注记录" in data["empty_text"]
    assert data["watch"] == {"checked_at": "2026-11-20T17:48:00", "checked_text": "11-20 17:48", "ago_text": "12 分钟前", "found": 2,
                             "next_text": "18:18", "summary": "发布窗口在等你拍板", "error": "", "busy": False}
    assert data["action"] == {"name": "generate_report", "report": "slack_watch", "label": "现在检查", "hint": ""}
    assert [n["name"] for n in data["notes"]] == ["n-old", "n-done"] and data["counts"]["open"] == 1


def test_the_check_strip_shows_busy_failure_and_nothing_yet():
    data = notes.slack_watch(lambda: _Service(), lambda: _Watch(None, busy=True, error="没登录"), _config(), now=lambda: NOW)()
    assert data["watch"] == {"checked_at": "", "checked_text": "", "ago_text": "", "found": None, "next_text": "", "summary": "", "error": "没登录", "busy": True}
    old = sw.WatchResult(ok=True, checked_at="2026-11-18T09:00:00")
    assert notes.watch_block(_Watch(old), NOW)["ago_text"] == "2 天前" and notes.watch_block(_Watch(sw.WatchResult(ok=True, checked_at="坏")), NOW)["checked_text"] == ""
    assert notes.watch_block(_Watch(sw.WatchResult(ok=True, checked_at="2026-11-20T17:59:30")), NOW)["ago_text"] == "刚刚"
    assert notes.watch_block(_Watch(sw.WatchResult(ok=True, checked_at="2026-11-20T15:00:00")), NOW)["ago_text"] == "3 小时前"


def test_without_wsl_the_slack_page_is_unavailable_and_without_work_notes_only_the_strip_shows():
    data = notes.slack_watch(lambda: _Service([OLD]), lambda: None, _config(), now=lambda: NOW)()
    assert data["available"] is False and data["notes"] == [] and data["watch"] is None and "WSL" in data["unavailable_text"]
    data = notes.slack_watch(lambda: None, lambda: _Watch(RESULT), _config(), now=lambda: NOW)()
    assert data["available"] is True and data["watch"]["found"] == 2 and data["notes"] == [] and "工作笔记" in data["empty_text"]
    assert notes.work_notes(lambda: None, _config())()["unavailable_text"].startswith("这台机器上没有这项功能（工作笔记")


def test_check_slack_reports_the_service_state():
    assert notes.check_slack(lambda: None)() == "unavailable"
    busy = _Watch(None, busy=True)
    assert notes.check_slack(lambda: busy)() == "busy" and busy.asked == 0
    ok, failed = _Watch(None), _Watch(None, started=False)
    assert notes.check_slack(lambda: ok)() == "started" and ok.asked == 1 and notes.check_slack(lambda: failed)() == "failed"


def test_the_note_action_tells_the_two_pages_services_apart():
    work, slack = _Service([DUE]), _Service([OLD])
    handler = notes.note_action({"work_notes": lambda: work, "slack_watch": lambda: slack})
    assert handler({"report": "slack_watch", "op": "done", "name": "n-old"})["state"] == "done"
    assert handler({"report": "work_notes", "op": "done", "name": "n-old"})["state"] == "missing"
    assert slack.calls == [("done", "n-old")] and work.calls == []


# ───────────────────────── 动作 ─────────────────────────

def _run(service, **body):
    return notes.note_action({"work_notes": lambda: service})({"report": "work_notes", **body})


def test_add_saves_and_answers_with_the_new_name_or_why_not():
    service = _Service()
    out = _run(service, op="add", text="记一条 https://x.example/1")
    assert out["state"] == "saved" and out["name"] and service.calls == [("add", "记一条 https://x.example/1")]
    assert _run(service, op="add", text="   ")["state"] == "empty" and len(service.calls) == 1, "空的不叫服务"
    out = _run(service, op="add", text="坏")
    assert out["state"] == "failed" and out["error"] == "磁盘满"


def test_each_op_reaches_the_matching_service_method():
    service = _Service([DUE, LATER], busy={"n-later"})
    assert _run(service, op="done", name="n-due")["state"] == "done"
    assert _run(service, op="snooze", name="n-due", minutes=180)["state"] == "done"
    assert _run(service, op="resummarize", name="n-due")["state"] == "started"
    assert _run(service, op="resummarize", name="n-later")["state"] == "busy"
    assert _run(service, op="open_link", name="n-due")["state"] == "opened"
    assert _run(service, op="open_link", name="n-later")["state"] == "no_link"
    assert _run(service, op="obsidian", name="n-due")["state"] == "folder"
    assert _run(service, op="folder")["state"] == "opened"
    assert _run(service, op="push")["state"] == "started"
    assert _run(service, op="delete", name="n-due")["state"] == "done" and service.note("n-due") is None
    assert _run(service, op="done", name="n-due")["state"] == "missing", "删掉之后再点：告诉页面它不在了"
    assert service.calls == [("done", "n-due"), ("snooze", "n-due", 180), ("resummarize", "n-due"), ("resummarize", "n-later"),
                             ("open_link", "n-due"), ("open_link", "n-later"), ("obsidian", "n-due"), ("folder",), ("push",), ("delete", "n-due")]


@pytest.mark.parametrize("body, code", [
    ({"report": "other", "op": "add"}, "bad_report"), ({"report": "work_notes", "op": "rename"}, "bad_op"),
    ({"report": "work_notes", "op": "done"}, "bad_name"), ({"report": "work_notes", "op": "snooze", "name": "n-due", "minutes": 7}, "bad_minutes"),
    ({"report": "work_notes", "op": "snooze", "name": "n-due", "minutes": True}, "bad_minutes"), ("nonsense", "bad_report"),
])
def test_bad_requests_are_refused_with_a_code(body, code):
    with pytest.raises(ActionError) as info:
        notes.note_action({"work_notes": lambda: _Service([DUE])})(body)
    assert info.value.code == code and info.value.status == 400


def test_no_service_means_503():
    with pytest.raises(ActionError) as info:
        notes.note_action({"work_notes": lambda: None})({"report": "work_notes", "op": "folder"})
    assert info.value.status == 503 and info.value.code == "unavailable"


# ───────────────────────── 服务：外壳、字表、片段 ─────────────────────────

class _FakeServer:
    def start(self):
        return "http://127.0.0.1:1/"

    def page_url(self, path="/"):
        return f"http://127.0.0.1:1{path}#TOKEN"

    def stop(self):
        pass


def _panorama(tmp_path, opened):
    config = SimpleNamespace(data={}, path=tmp_path / "config.json", dir=tmp_path)
    provider = notes.work_notes(lambda: _Service([FRESH]), _config(), now=lambda: NOW)
    return PanoramaService(config, windows=lambda *a, **k: {}, wsl=dict, write=lambda facts, out_dir: out_dir / "p.html",
                           open_page=opened.append, spawn=lambda run: None, server=_FakeServer(),
                           reports={"work_notes": provider, "demo": lambda: {"title": "x"}})


def test_the_service_picks_the_shell_and_strings_by_the_providers_page_attribute(tmp_path):
    service = _panorama(tmp_path, [])
    assert service.report_page("work_notes") == "notes" and service.report_page("demo") == "report" and service.report_page("nope") == "report"
    assert '<script type="module" src="/notes.js"></script>' in render.report_shell("notes") and "/notes.css" in render.report_shell("notes")
    assert '<script type="module" src="/report.js"></script>' in render.report_shell("report") and render.report_shell("odd") == render.report_shell()
    service.publish_report("work_notes", force=True)
    data = json.loads(service.report("work_notes", None, 0.0))
    assert set(data["strings"]) == set(render.NOTES_KEYS) and data["report"]["page"] == "notes" and data["page"]["title"] == "工作笔记 · 大肥鱼"
    service.publish_report("demo", force=True)
    assert set(json.loads(service.report("demo", None, 0.0))["strings"]) == set(render.REPORT_KEYS)


def test_opening_the_notes_page_can_point_at_one_note_in_the_fragment(tmp_path):
    opened = []
    service = _panorama(tmp_path, opened)
    assert service.open_report("work_notes", note="2026-11-20-1750-刚记的 x") is True
    assert opened == ["http://127.0.0.1:1/report/work_notes#TOKEN&note=2026-11-20-1750-%E5%88%9A%E8%AE%B0%E7%9A%84%20x"]
    assert service.open_report("work_notes") is True and opened[-1] == "http://127.0.0.1:1/report/work_notes#TOKEN"


def test_notes_assets_are_registered_and_bundle():
    for name in render.NOTES_MODULES + render.NOTES_STYLES:
        assert name in render.ASSETS
    assert "function detailHtml" in render.bundle(render.NOTES_MODULES)
