# -*- coding: utf-8 -*-
"""工作简报 / 工作笔记按界面语言出英文（用户 2026-10-19：界面是英文，简报和笔记还是中文），
以及简报的来源可配置：来源开关决定提示词里列哪些来源、输出哪几节、放行哪些只读工具、要不要先跑 gh。

纪律：不起真的 wsl.exe、不读真实数据目录。
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from pet import i18n
from pet import work_briefing as wb
from pet import work_notes as wn
from tests.test_work_briefing import MONDAY_10, REPORT

ALL = dict(wb.DEFAULT_SOURCES)


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


def _claude_json(result: str) -> str:
    return json.dumps({"type": "result", "subtype": "success", "is_error": False, "num_turns": 3, "result": result,
                       "permission_denials": []}, ensure_ascii=False)


# ---------------------------------------------------------------- 语言

def test_the_english_prompt_asks_for_an_english_briefing_with_english_headings():
    i18n.set_language("en")
    prompt = wb.build_prompt(MONDAY_10, "- acme/widgets#10 Fix login")
    assert prompt.startswith("You are my work-briefing assistant") and "written entirely in English" in prompt
    assert "Monday 2026-10-12 10:00" in prompt and "last 72 hours" in prompt and "read-only" in prompt
    assert "`## Jira`, `## PR`, `## Slack`, `## Calendar`, `## Do first` (at most 3 items)" in prompt
    assert "`Summary:`" in prompt and "acme/widgets#10 Fix login" in prompt
    assert "概要" not in prompt and "邮件" not in prompt and "Email" not in prompt, "邮件默认关，提示词里不提"
    assert wb.build_prompt(MONDAY_10, "", language="zh").startswith("你是我的工作简报助手")


def test_the_chinese_prompt_is_the_same_as_before():
    prompt = wb.build_prompt(MONDAY_10, "- acme/widgets#10 Fix login")
    assert "星期一" in prompt and "72 小时" in prompt and "只读" in prompt
    assert "`## Jira`、`## PR`、`## Slack`、`## 日程`、`## 建议先做`（最多 3 条）" in prompt
    assert "JQL：assignee = currentUser()" in prompt and "<pr_list>" in prompt


def test_the_summary_line_is_recognised_in_both_languages():
    english = wb.parse_output(_claude_json("Summary: reply to two DMs first.\n\n## Jira\nNone\n"))
    assert english.ok and english.summary == "reply to two DMs first." and english.markdown.startswith("## Jira")
    bold = wb.parse_output(_claude_json("**Summary:** short\n\nbody"))
    assert bold.summary == "short" and bold.markdown == "body"
    chinese = wb.parse_output(_claude_json(REPORT))
    assert chinese.summary == "先回两条私信，下午有例会。"
    i18n.set_language("en")
    assert wb.parse_output(_claude_json("no summary line\nbody")).summary == "Today's work briefing is ready."
    assert "Claude Code returned no result" in wb.parse_output("").error


def test_the_notes_prompt_switches_whole_template_with_the_language():
    note = wn.new_note("https://acme.slack.com/archives/C1/p1\nlook at this", dt.datetime(2026, 10, 15, 19, 40))
    assert wn.build_prompt(note, dt.datetime(2026, 10, 15, 19, 40)).startswith("你是我的工作笔记助手")
    i18n.set_language("en")
    prompt = wn.build_prompt(note, dt.datetime(2026, 10, 15, 19, 40))
    assert prompt.startswith("You are my work-notes assistant") and "write everything in English" in prompt
    assert '"title": "...", "summary": "...", "details"' in prompt and "<note>\nhttps://acme.slack.com" in prompt
    assert "Claude Code returned no result" in wn.parse_summary("", dt.datetime(2026, 10, 15, 19, 40)).error


# ---------------------------------------------------------------- 来源开关

def test_sources_are_normalised_with_email_off_by_default():
    assert wb.normalize_sources(None) == ALL and ALL["email"] is False
    assert wb.normalize_sources({"email": True, "slack": False, "bogus": True}) == {**ALL, "email": True, "slack": False}
    assert wb.normalize({"sources": {"jira": "yes"}})["sources"]["jira"] is False


def test_switched_off_sources_leave_the_prompt_and_the_tool_list():
    sources = {**ALL, "slack": False, "calendar": False, "suggestions": False}
    prompt = wb.build_prompt(MONDAY_10, "", sources=sources)
    assert "Slack：" not in prompt and "日历：" not in prompt and "建议先做" not in prompt
    assert "`## Slack`" not in prompt and "`## 日程`" not in prompt
    assert "1. Jira" in prompt and "2. PR" in prompt and "`## Jira`、`## PR`。" in prompt
    tools = wb.allowed_tools(sources)
    assert not any("Slack" in name or "Calendar" in name for name in tools) and any("atlassian" in name.lower() for name in tools)
    command = wb.claude_command("sonnet", sources)
    assert "slack_read_thread" not in command and "getJiraIssue" in command


def test_email_is_only_allowed_when_switched_on_and_never_its_writing_tools():
    assert not any("Gmail" in name for name in wb.allowed_tools()) and "mcp__claude_ai_Gmail" in wb.denied_tools()
    on = {**ALL, "email": True}
    tools = wb.allowed_tools(on)
    assert {name.rsplit("__", 1)[1] for name in tools if "Gmail" in name} == {"search_threads", "get_thread", "get_message"}
    denied = wb.denied_tools(on)
    assert "mcp__claude_ai_Gmail" not in denied, "邮件开着时不能把整个连接器拒掉"
    for needle in ("send_message", "reply", "forward", "create_draft", "trash_thread", "label_message", "delete_label"):
        assert any(name.endswith("__" + needle) and "Gmail" in name for name in denied), needle
    assert not set(denied) & set(tools)
    prompt = wb.build_prompt(MONDAY_10, "", sources=on)
    assert "5. 邮件" in prompt and "`## 邮件`" in prompt and "search_threads" in prompt


def test_generate_skips_gh_when_prs_are_off_and_passes_sources_to_the_command():
    calls = []

    def run(args, *, input_text=None, timeout=None):
        calls.append((args[-1], input_text))
        return 0, _claude_json(REPORT)

    briefing = wb.generate(MONDAY_10, "sonnet", sources={**ALL, "pr": False}, run=run)
    assert briefing.ok
    assert len(calls) == 1 and " claude -p " in calls[0][0], "PR 关着：不跑 gh"
    assert "<pr_list>" not in calls[0][1] and "`## PR`" not in calls[0][1]
    calls.clear()
    wb.generate(MONDAY_10, "sonnet", sources={**ALL, "email": True}, run=run)
    assert len(calls) == 2 and "gh search prs" in calls[0][0] and "search_threads" in calls[1][0]
