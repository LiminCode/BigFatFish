# -*- coding: utf-8 -*-
"""复习页：服务端的数据（``reports.review_page``）和动作（``review_action``），以及页面脚本（QJSEngine + 假 DOM）——
一次一张卡、先回想再看答案、三个回答、键盘、推送按钮。

纪律：不起 git；ReviewService 用临时目录里的真笔记 + 同步的假推送；样例文字中性。
"""
from __future__ import annotations

import datetime as dt
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtQml import QJSEngine
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet import personal_vault as pv
from pet.config import Config
from pet.panorama import actions, render, reports
from pet.review_service import ReviewService
from tests.test_capture_review import _note
from tests.test_panorama_page import FAKE_BROWSER, FAKE_DOM, _evaluate

app = QApplication.instance() or QApplication([])
NOW = dt.datetime(2026, 11, 26, 9, 0)


@pytest.fixture(autouse=True)
def _chinese():
    i18n.set_language("zh")
    yield
    i18n.set_language("zh")


@pytest.fixture
def review(tmp_path):
    repo = tmp_path / "AI-Base"
    (repo / ".git").mkdir(parents=True)
    config = Config(base=tmp_path / "cfg")
    config.set(pv.CONFIG_KEY, {"repo_dir": str(repo)})
    service = ReviewService(config, spawn=lambda job: job(), now=lambda: NOW, sync=lambda *a, **k: (True, ""), head=lambda _r: "x")
    yield repo, config, service
    service.stop()


# ───────────────────────── 服务端 ─────────────────────────

def test_the_page_data_is_todays_round_with_rendered_answers_and_next_intervals(review):
    repo, config, service = review
    path = _note(repo, "habit", title="Habit <stacking>", review="{next: 2026-11-25, interval: 3, count: 1, lapses: 0}")
    _note(repo, "later", review="{next: 2026-12-02, interval: 7, count: 1, lapses: 0}")
    data = reports.review_page(lambda: service, config, now=lambda: NOW)()
    assert reports.review_page(lambda: service, config).page == "review"
    assert data["available"] is True and data["counts"] == {"due": 1, "done": 0} and len(data["cards"]) == 1
    card = data["cards"][0]
    assert card["path"] == path and card["title"] == "Habit <stacking>" and card["kind_text"] == "帖子" and card["captured"] == "2026-11-25"
    assert card["source_link"] is True and card["points_html"].startswith("<ul>") and "point one" in card["points_html"]
    assert "Small habits" in card["words_html"]
    assert [(c["answer"], c["label"], c["hint"]) for c in card["choices"]] == [
        ("remember", "记得", "7 天后再见"), ("fuzzy", "模糊", "3 天后再见"), ("forgot", "忘了", "1 天后再见")]
    assert "<stacking>" not in json.dumps(card["points_html"]), "笔记内容一律转义"


def test_the_page_says_when_nothing_is_due_and_when_it_cannot_work(review, tmp_path):
    repo, config, service = review
    _note(repo, "later", review="{next: 2026-12-02, interval: 7, count: 1, lapses: 0}")
    data = reports.review_page(lambda: service, config, now=lambda: NOW)()
    assert data["cards"] == [] and data["empty_text"] == "今天没有到期的笔记了。下一条在 12-02。"
    assert reports.review_page(lambda: None, config)()["available"] is False
    config.set(pv.CONFIG_KEY, {"repo_dir": str(tmp_path / "gone")})
    assert "找不到个人知识库的克隆" in reports.review_page(lambda: service, config)()["unavailable_text"]


def test_grading_through_the_action_moves_to_the_next_card_and_reports_the_push(review):
    repo, config, service = review
    a, b = _note(repo, "a"), _note(repo, "b")
    act = reports.review_action(lambda: service)
    assert act({"op": "grade", "path": a, "answer": "remember"}) == {"op": "grade", "state": "graded", "next": "2026-11-29", "interval": 3}
    data = reports.review_page(lambda: service, config, now=lambda: NOW)()
    assert [c["path"] for c in data["cards"]] == [b] and data["counts"] == {"due": 1, "done": 1}
    assert data["sync"] == {"text": "1 条打了分，这一轮打完（或停手两分钟）一起推", "failed": False, "pending": 1}
    act({"op": "grade", "path": b, "answer": "fuzzy"})
    data = reports.review_page(lambda: service, config, now=lambda: NOW)()
    assert data["cards"] == [] and data["sync"]["text"] == "已推送到 GitHub（09:00）" and data["sync"]["pending"] == 0
    assert act({"op": "flush"}) == {"op": "flush", "state": "empty"}
    for bad, code in (({"op": "grade", "path": a, "answer": "maybe"}, "bad_answer"), ({"op": "grade", "answer": "remember"}, "bad_answer"),
                      ({"op": "nope"}, "bad_op")):
        with pytest.raises(actions.ActionError) as err:
            act(bad)
        assert err.value.code == code
    with pytest.raises(actions.ActionError) as gone:
        reports.review_action(lambda: None)({"op": "flush"})
    assert gone.value.status == 503


def test_the_briefing_page_offers_the_review_only_when_something_is_due(review):
    repo, config, service = review

    class _Personal:
        busy, busy_model, busy_effort, sync_state, sync_error, pushed_at, last_capture = False, "", "", "idle", "", "", ""

        def last_error(self):
            return ""

        def latest(self):
            return None

    build = reports.personal_briefing(lambda: _Personal(), config, review_of=lambda: service)
    assert [a["name"] for a in build()["actions"]] == ["open_obsidian"]
    _note(repo, "a")
    first = build()["actions"][0]
    assert first == {"name": "open_report", "report": "review", "label": "复习 1 条", "hint": "今天到期的笔记，一次一张卡"}


# ───────────────────────── 页面脚本 ─────────────────────────

@pytest.fixture(scope="module")
def engine():
    js = QJSEngine()
    yield js
    del js


REVIEW_DOM = """
document.documentElement.dataset = {};
location.pathname = '/report/review';
location.origin = 'http://127.0.0.1:1';
var clicks = {};
['card', 'push'].forEach(function (id) {
  document.getElementById(id).addEventListener = function (type, fn) { clicks[id + ':' + type] = fn; };
});
var dom = function () { var el = document.getElementById; return {title: el('title').textContent, counts: el('counts').textContent,
  card: el('card').innerHTML, cardHidden: el('card').hidden, empty: el('empty').textContent, emptyHidden: el('empty').hidden,
  status: el('status').textContent, sync: el('sync').textContent, syncClass: el('sync').className, pushHidden: el('push').hidden,
  push: el('push').textContent, keys: el('keys').textContent, lost: el('lost').hidden}; };
var press = function (op, answer) { clicks['card:click']({target: {closest: function () { return {disabled: false, dataset: {op: op, answer: answer}}; }}}); };
var key = function (k) { _docListeners.keydown({key: k, preventDefault: function () {}}); };
"""


def _report(review, now=NOW):
    repo, config, service = review
    return reports.review_page(lambda: service, config, now=lambda: now)()


def _payload(report: dict, revision: int = 1) -> str:
    return '{"status": 200, "data": ' + render.report_payload(report, revision=revision, page="review").decode("utf-8") + "}"


def _page(engine, responses: list[str], steps: str = "") -> dict:
    setup = REVIEW_DOM + "location.hash = '#tok-1';\nresponses = [" + ",".join(responses) + "];\n"
    return _evaluate(engine, FAKE_DOM + FAKE_BROWSER + setup + render.bundle(render.REVIEW_MODULES) + steps +
                     "\nreturn JSON.stringify({dom: dom(), requests: requests.map(function (r) { return {path: r.path, method: r.method, "
                     "body: r.body ? JSON.parse(r.body) : undefined}; })});")


def test_a_card_first_shows_only_the_question_then_the_answer_and_three_choices(engine, review):
    repo, _config, _service = review
    _note(repo, "a", title="Habit stacking")
    out = _page(engine, [_payload(_report(review)), '{"hang": true}'])
    dom = out["dom"]
    assert out["requests"][0]["path"] == "/api/report/review" and out["requests"][1]["path"] == "/api/report/review?after=1"
    assert dom["title"] == "复习" and dom["counts"] == "今天到期 1 条 · 已复习 0 条" and dom["cardHidden"] is False
    assert "<h2>Habit stacking</h2>" in dom["card"] and "看答案" in dom["card"] and "point one" not in dom["card"]
    assert "还剩 1 条" in dom["card"] and dom["keys"].startswith("空格看答案") and dom["pushHidden"] is True
    shown = _page(engine, [_payload(_report(review)), '{"hang": true}'], "\npress('show');")["dom"]["card"]
    assert "point one" in shown and "我的话" in shown and shown.count('data-op="grade"') == 3 and "7 天后再见" not in shown
    assert "3 天后再见" in shown and 'class="btn remember"' in shown
    by_key = _page(engine, [_payload(_report(review)), '{"hang": true}'], "\nkey(' ');")["dom"]["card"]
    assert "point one" in by_key, "空格也能看答案"


def test_an_answer_posts_the_grade_and_waits_for_the_next_card(engine, review):
    repo, _config, _service = review
    path = _note(repo, "a")
    graded = '{"status": 200, "data": {"op": "grade", "state": "graded", "next": "2026-11-29", "interval": 3}}'
    out = _page(engine, [_payload(_report(review)), '{"hang": true}', graded], "\npress('show'); press('grade', 'remember');")
    assert out["requests"][-1] == {"path": "/api/actions/review", "method": "POST", "body": {"op": "grade", "path": path, "answer": "remember"}}
    assert out["dom"]["status"] == "记下了，下次 2026-11-29" and "disabled" in out["dom"]["card"]
    early = _page(engine, [_payload(_report(review)), '{"hang": true}'], "\nkey('1');")
    assert len(early["requests"]) == 2, "还没看答案：按 1 不算数"
    by_key = _page(engine, [_payload(_report(review)), '{"hang": true}', graded], "\nkey(' '); key('3');")
    assert by_key["requests"][-1]["body"]["answer"] == "forgot"
    busy = '{"status": 200, "data": {"op": "grade", "state": "busy"}}'
    again = _page(engine, [_payload(_report(review)), '{"hang": true}', busy], "\npress('show'); press('grade', 'fuzzy');")["dom"]
    assert again["status"] == "正在推送，等一下再点" and "disabled" not in again["card"], "等不到锁：按钮还能再点"


def test_empty_day_unavailable_and_the_push_button(engine, review, tmp_path):
    repo, config, service = review
    _note(repo, "later", review="{next: 2026-12-02, interval: 7, count: 1, lapses: 0}")
    dom = _page(engine, [_payload(_report(review)), '{"hang": true}'])["dom"]
    assert dom["cardHidden"] is True and dom["emptyHidden"] is False and dom["empty"] == "今天没有到期的笔记了。下一条在 12-02。"
    off = reports.review_page(lambda: None, config)()
    dom = _page(engine, [_payload(off), '{"hang": true}'])["dom"]
    assert dom["empty"].startswith("复习要先接上个人助理") and dom["counts"] == ""
    waiting = {**_report(review), "sync": {"text": "1 条打了分", "failed": False, "pending": 1}}
    out = _page(engine, [_payload(waiting), '{"hang": true}', '{"status": 200, "data": {"op": "flush", "state": "started"}}'],
                "\nclicks['push:click']();")
    assert out["dom"]["pushHidden"] is False and out["dom"]["push"] == "现在推送" and out["dom"]["sync"] == "1 条打了分"
    assert out["requests"][-1]["body"] == {"op": "flush"} and out["dom"]["status"] == "开始推送"
    failed = {**_report(review), "sync": {"text": "没推上去", "failed": True, "pending": 1}}
    assert _page(engine, [_payload(failed), '{"hang": true}'])["dom"]["syncClass"] == "sync bad"


def test_the_shell_and_assets_are_served_and_every_page_string_exists_in_both_languages():
    shell = render.report_shell("review")
    assert '<script type="module" src="/review.js"></script>' in shell and 'id="card"' in shell
    for name in render.REVIEW_STYLES + render.REVIEW_MODULES:
        assert render.asset(name)
    for language in ("zh", "en"):
        table = i18n.table(language)
        assert [key for key in render.REVIEW_KEYS if not str(table.get(f"panorama.ui.{key}") or "").strip()] == []
