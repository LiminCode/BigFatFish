# -*- coding: utf-8 -*-
"""报告页的数据（``pet/panorama/reports.py``）与「重新生成」动作：把简报服务的状态翻成页面要摆的那份字典。

页面不认功能，所以这份字典就是契约：标题 / 概要 / 生成行 / 用量 / 全文 HTML / 忙 / 错 / 按钮 / 有没有这项功能。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet import work_briefing as wb
from pet.panorama import actions, reports

app = QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _chinese():
    i18n.set_language("zh")
    yield
    i18n.set_language("zh")


def _config(theme="dark"):
    return SimpleNamespace(get=lambda key, default=None: {"theme": theme} if key == "context_menu_appearance" else default)


class _Service:
    def __init__(self, briefing=None, *, busy=False, error="", started=True):
        self._briefing, self.busy, self._error, self._started, self.asked = briefing, busy, error, started, 0

    def latest(self):
        return self._briefing

    def last_error(self):
        return self._error

    def generate_now(self):
        self.asked += 1
        return self._started


BRIEFING = wb.Briefing(ok=True, summary="先评审两个 PR", markdown="## PR\n- ★★★ [acme/w#1](https://x.example/1) `进行中`\n",
                       generated_at="2026-11-19T09:00:08", seconds=117.8, turns=12, model="claude-opus-5-5", effort="high",
                       tokens_in=406791, tokens_out=12012, cost_usd=1.25)


def test_the_latest_briefing_is_rendered_with_its_usage_and_a_regenerate_button():
    data = reports.work_briefing(lambda: _Service(BRIEFING), _config())()
    assert data["id"] == "work_briefing" and data["title"] == "工作简报" and data["available"] is True and data["theme"] == "dark"
    assert data["summary"] == "先评审两个 PR" and data["generated"].startswith("生成于 11-19 09:00")
    assert data["html"].startswith("<h3>PR</h3>") and 'class="star s3"' in data["html"] and '<code class="chip">进行中</code>' in data["html"]
    assert [u["key"] for u in data["usage"]] == ["model", "effort", "time", "tokens_in", "tokens_out", "cost"]
    assert data["usage"][0]["text"] == "claude-opus-5-5" and data["usage"][2]["text"] == "118 秒"
    assert data["usage"][3]["tip"] == "输入 406,791 tokens" and "1.25" in data["usage"][5]["text"]
    assert data["busy"] is False and data["error"] == ""
    assert data["action"] == {"name": "generate_report", "report": "work_briefing", "label": "重新生成",
                              "hint": "让 WSL 里的 Claude Code 重新读一遍并总结，大约一分钟"}


def test_no_briefing_yet_and_a_failed_attempt_and_busy():
    empty = reports.work_briefing(lambda: _Service(None), _config("light"))()
    assert empty["html"] == "" and empty["summary"] == "" and empty["usage"] == [] and empty["theme"] == "light"
    assert empty["empty_text"].startswith("还没有简报") and empty["busy_text"].startswith("正在生成")

    failed = reports.work_briefing(lambda: _Service(BRIEFING, error="boom"), _config())()
    assert failed["error"] == "上一次没生成出来：boom" and failed["html"], "上一份还在，错误另说"

    busy = reports.work_briefing(lambda: _Service(BRIEFING, busy=True), _config())()
    assert busy["busy"] is True


def test_without_the_service_the_report_only_says_it_is_unavailable():
    data = reports.work_briefing(lambda: None, _config())()
    assert data["available"] is False and data["html"] == "" and data["title"] == "工作简报"


def test_old_records_without_a_model_only_report_the_time():
    old = wb.Briefing(ok=True, summary="s", markdown="x", generated_at="2026-10-01T09:00:00", seconds=30)
    data = reports.work_briefing(lambda: _Service(old), _config())()
    assert [u["key"] for u in data["usage"]] == ["time"]


def test_english_strings_follow_the_ui_language():
    i18n.set_language("en")
    data = reports.work_briefing(lambda: _Service(BRIEFING), _config())()
    assert data["title"] == "Daily Briefing" and data["action"]["label"] == "Regenerate" and data["generated"].startswith("Generated 11-19")


# ---------------------------------------------------------------- 「重新生成」

def test_generate_reports_the_service_state():
    assert reports.generate_work_briefing(lambda: None)() == "unavailable"
    assert reports.generate_work_briefing(lambda: _Service(busy=True))() == "busy"
    ok = _Service()
    assert reports.generate_work_briefing(lambda: ok)() == "started" and ok.asked == 1
    assert reports.generate_work_briefing(lambda: _Service(started=False))() == "failed"


def test_the_generate_action_only_knows_registered_reports():
    run = actions.generate_report({"work_briefing": lambda: "started"})
    assert run({"report": "work_briefing"}) == {"report": "work_briefing", "state": "started"}
    for body in ({"report": "nope"}, {}, None, {"report": 3}):
        with pytest.raises(actions.ActionError) as caught:
            run(body)
        assert (caught.value.status, caught.value.code) == (400, "bad_report")
