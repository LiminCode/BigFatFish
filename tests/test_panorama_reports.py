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
    def __init__(self, briefing=None, *, busy=False, error="", started=True, trace=None):
        self._briefing, self.busy, self._error, self._started, self.asked = briefing, busy, error, started, 0
        self._trace = trace or {}

    def last_trace(self):
        return self._trace

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


TRACE = {"version": "2.1.329", "model": "claude-opus-5-5", "permission_mode": "auto", "turns": 12, "ok": True, "at": "2026-11-19T22:10:00",
         "servers": [{"name": "claude.ai Atlassian", "status": "needs-auth", "source": "claude.ai", "calls": 0, "allowed": True},
                     {"name": "claude.ai Slack", "status": "connected", "source": "claude.ai", "calls": 3, "allowed": True},
                     {"name": "plugin:atlassian:atlassian", "status": "weird", "source": "plugin", "calls": 0, "allowed": True}],
         "others": 23, "tools": ["mcp__claude_ai_Slack__slack_read_channel"], "allowed": ["a", "b", "c"],
         "calls": [{"n": 1, "tool": "mcp__claude_ai_Slack__slack_search_public_and_private", "args": "query=<to:me>", "ok": True},
                   {"n": 2, "tool": "mcp__claude_ai_Atlassian__getJiraIssue", "args": "key=X-1", "ok": False},
                   {"n": 3, "tool": "odd", "args": "", "ok": None}],
         "denied": ["mcp__claude_ai_Slack__slack_send_message"], "hooks": ["gitkraken-hooks:SessionStart"],
         "gh_command": "gh pr list", "command": "claude -p --tools ''", "prompt": "你是我的<助手>"}


def test_the_run_record_becomes_collapsible_sections_with_everything_escaped():
    data = reports.work_briefing(lambda: _Service(BRIEFING, trace=TRACE), _config())()
    titles = [section["title"] for section in data["details"]]
    assert titles == ["这次是怎么生成的（11-19 22:10）", "工具调用（3 次）", "那个账号自己的 hooks", "命令（肥鱼在 WSL 登录 shell 里跑的）",
                      "提示词（发出去的原文）"]
    first = data["details"][0]["html"]
    assert "Claude Code 2.1.329（claude-opus-5-5 · 权限模式 auto · 12 轮）" in first
    assert '<td>claude.ai Atlassian</td><td class="st needs-auth">没登录</td><td>要登录：在 WSL 里跑 claude mcp login &quot;claude.ai Atlassian&quot;，再重新生成</td>' in first
    assert '<td class="st connected">已连接</td><td>这次调了 3 次</td>' in first and '<td class="st other">weird</td><td>放行了，这次没用到</td>' in first
    assert "另有 23 个 MCP 服务器与简报无关" in first and "放行名单 3 条；这次实际存在的工具 1 个" in first
    calls = data["details"][1]["html"]
    assert '<li><code>slack_search_public_and_private</code> <span class="srv">claude_ai_Slack</span> query=&lt;to:me&gt; <span class="ok">✓</span></li>' in calls
    assert '<code>getJiraIssue</code> <span class="srv">claude_ai_Atlassian</span> key=X-1 <span class="bad">✗</span>' in calls
    assert '<li><code>odd</code> <span class="srv"></span>  </li>' in calls and "被拒的：mcp__claude_ai_Slack__slack_send_message" in calls
    assert data["details"][2]["html"] == "<p>gitkraken-hooks:SessionStart</p>"
    assert data["details"][3]["html"] == "<pre>gh pr list\nclaude -p --tools &#x27;&#x27;</pre>"
    assert data["details"][4]["html"] == '<p><a class="settings" href="__SETTINGS_URL__">到设置里改模板</a></p><pre>你是我的&lt;助手&gt;</pre>'
    assert data["settings_focus"] == "work_briefing"


def test_a_failed_run_is_marked_and_a_service_without_a_record_gives_no_sections():
    failed = reports.trace_sections({**TRACE, "ok": False, "servers": [], "calls": [], "hooks": [], "others": 0, "denied": []})
    assert failed[0]["title"] == "这次是怎么生成的（11-19 22:10 · 失败）" and "这次运行没有报告任何 MCP 服务器" in failed[0]["html"]
    assert failed[1]["html"] == '<p class="note">没有调用任何工具</p>' and failed[2]["html"] == '<p class="note">没有 hooks 运行</p>'
    assert reports.trace_sections({}) == []
    plain = reports.work_briefing(lambda: _Service(BRIEFING), _config())()
    assert plain["details"] == [], "老版本生成的简报：没有记录就不摆"


RENDERED = ("<p>开场白</p>\n<h3>Jira</h3>\n<ul>\n"
            '<li class="bug"><span class="star s3">★★★</span> 🐞 <a href="https://j.example/1">X-1</a> 崩溃 · <strong>有更新</strong>\n'
            "<ul>\n<li>QA 报的场景：…</li>\n</ul>\n</li>\n"
            '<li><span class="star s2">★★</span> X-2 普通</li>\n'
            '<li><span class="star s1">★</span> X-3 小事 · <strong>有更新</strong></li>\n</ul>\n'
            "<h3>日程</h3>\n<p>今天没有会。</p>\n<h3>建议先做</h3>\n<ol>\n<li>先修 X-1</li>\n</ol>")


def test_the_rendered_text_is_split_into_sections_with_top_level_counts():
    sections = reports.split_sections(RENDERED)
    assert [(s["id"], s["source"], s["title"], s["count"]) for s in sections] == [
        ("s1", "other", "", 0), ("s2", "jira", "Jira", 3), ("s3", "calendar", "日程", 0), ("s4", "suggestions", "建议先做", 1)]
    jira = sections[1]
    assert (jira["p3"], jira["p2"], jira["p1"], jira["bugs"], jira["updated"]) == (1, 1, 1, 1, 2), "嵌套的那一条不算"
    assert jira["html"].startswith("<ul>") and jira["html"].endswith("</ul>") and sections[0]["html"] == "<p>开场白</p>"
    assert sections[2]["html"] == "<p>今天没有会。</p>" and sections[3]["p3"] == 0
    assert reports.split_sections("<p>没有标题的内容</p>") == [] and reports.split_sections("") == []
    assert reports.source_of("Pull requests") == "pr" and reports.source_of("Slack 消息") == "slack" and reports.source_of("邮件") == "email"
    assert reports.source_of("随便") == "other"


def test_the_latest_briefing_is_rendered_with_its_usage_and_a_regenerate_button():
    data = reports.work_briefing(lambda: _Service(BRIEFING), _config())()
    assert data["id"] == "work_briefing" and data["title"] == "工作简报" and data["available"] is True and data["theme"] == "dark"
    assert data["summary"] == "先评审两个 PR" and data["generated"].startswith("生成于 11-19 09:00")
    assert data["html"].startswith("<h3>PR</h3>") and 'class="star s3"' in data["html"] and '<code class="chip">进行中</code>' in data["html"]
    assert [(s["source"], s["title"], s["count"], s["p3"]) for s in data["sections"]] == [("pr", "PR", 1, 1)]
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


def test_the_sprint_section_gets_its_own_source_colour():
    assert reports.source_of("当前 Sprint") == "sprint" and reports.source_of("Current sprint") == "sprint"
    assert reports.source_of("Jira") == "jira" and reports.source_of("工单") == "jira"
