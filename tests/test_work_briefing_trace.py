# -*- coding: utf-8 -*-
"""工作简报的运行记录（``work_briefing.parse_trace`` 等）：从 ``claude -p`` 的 stream-json 事件流里整理出
「这次用了哪些 MCP 服务器、调了什么工具、那个账号跑了什么 hooks」，加上肥鱼自己知道的命令 / 提示词 / 名单，
随简报存起来、给简报页摆。另有「额外放行的工具」这项设置。
"""
from __future__ import annotations

import datetime as dt
import json

from pet import work_briefing as wb
from tests.test_work_briefing import _claude_json

NOW = dt.datetime(2026, 11, 19, 9, 0)
SEARCH = "mcp__claude_ai_Slack__slack_search_public_and_private"
JQL = "mcp__claude_ai_Atlassian__searchJiraIssuesUsingJql"


def _stream(*, denials=(), result="Summary: ok\n## Jira\n读不到\n"):
    init = {"type": "system", "subtype": "init", "claude_code_version": "2.1.329", "model": "claude-opus-5-5",
            "permissionMode": "auto",
            "mcp_servers": [{"name": "claude.ai Atlassian", "status": "needs-auth", "source": "claude.ai"},
                            {"name": "claude.ai Slack", "status": "connected", "source": "claude.ai"},
                            {"name": "plugin:atlassian:atlassian", "status": "failed", "source": "plugin"},
                            {"name": "GitKraken", "status": "connected", "source": "user"},
                            {"name": "claude.ai Gmail", "status": "connected", "source": "claude.ai"}],
            "tools": [SEARCH, "mcp__claude_ai_Slack__slack_send_message", "mcp__GitKraken__git_status"]}
    events = [
        init,
        {"type": "system", "subtype": "hook_started", "hook_name": "gitkraken-hooks:SessionStart", "hook_event": "SessionStart"},
        {"type": "system", "subtype": "hook_started", "hook_name": "gitkraken-hooks:SessionStart"},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "先查 Slack"},
            {"type": "tool_use", "id": "t1", "name": SEARCH, "input": {"query": "to:me  after:2026-11-18", "limit": 20}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "…"}]}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t2", "name": JQL, "input": {"jql": "assignee = currentUser()"}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t2", "is_error": True, "content": "needs auth"}]}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t3", "name": "mcp__GitKraken__git_status", "input": "x" * 300}]}},
        {"type": "result", "subtype": "success", "is_error": False, "result": result, "num_turns": 3,
         "permission_denials": [{"tool_name": name} for name in denials], "modelUsage": {}},
    ]
    return "Welcome to Ubuntu\n" + "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n"


# ---------------------------------------------------------------- 事件流 → 运行记录

def test_the_trace_names_the_servers_that_matter_and_counts_the_rest():
    trace = wb.parse_trace(_stream(), allowed=wb.allowed_tools(), denied=wb.denied_tools())
    assert (trace["version"], trace["model"], trace["permission_mode"]) == ("2.1.329", "claude-opus-5-5", "auto")
    by_name = {item["name"]: item for item in trace["servers"]}
    assert list(by_name) == ["claude.ai Atlassian", "claude.ai Slack", "plugin:atlassian:atlassian", "GitKraken"]
    assert trace["others"] == 1, "Gmail（邮件默认关）没放行也没用到：只数个数"
    assert by_name["GitKraken"] == {"name": "GitKraken", "status": "connected", "source": "user", "calls": 1, "allowed": False}, "没放行却用到了的也列出来"
    assert by_name["claude.ai Atlassian"] == {"name": "claude.ai Atlassian", "status": "needs-auth", "source": "claude.ai", "calls": 1, "allowed": True}
    assert by_name["claude.ai Slack"]["calls"] == 1 and by_name["plugin:atlassian:atlassian"]["calls"] == 0
    assert by_name["plugin:atlassian:atlassian"]["allowed"] is True, "插件前缀在放行名单里，哪怕这次没加载"
    assert trace["tools"] == [SEARCH], "放行名单里这次真的存在的工具：发消息的没放行，GitKraken 的也没有"
    assert trace["denied_rules"] == list(wb.denied_tools())


def test_every_tool_call_is_listed_with_a_short_argument_line_and_its_outcome():
    trace = wb.parse_trace(_stream(denials=["mcp__claude_ai_Slack__slack_send_message"]), allowed=wb.allowed_tools())
    assert trace["calls"][0] == {"n": 1, "tool": SEARCH, "args": "query=to:me after:2026-11-18, limit=20", "ok": True}
    assert trace["calls"][1] == {"n": 2, "tool": JQL, "args": "jql=assignee = currentUser()", "ok": False}
    assert trace["calls"][2]["n"] == 3 and trace["calls"][2]["ok"] is None and trace["calls"][2]["args"].endswith("…")
    assert len(trace["calls"][2]["args"]) == 200, "参数摘要有上限"
    assert trace["hooks"] == ["gitkraken-hooks:SessionStart"], "同一个 hook 跑两次只记一次"
    assert trace["denied"] == ["mcp__claude_ai_Slack__slack_send_message"]


def test_a_prefix_rule_or_a_whole_server_rule_counts_as_covering_the_server():
    trace = wb.parse_trace(_stream(), allowed=["mcp__GitKraken__*"])
    assert [item["name"] for item in trace["servers"]] == ["claude.ai Atlassian", "claude.ai Slack", "GitKraken"]
    assert trace["tools"] == ["mcp__GitKraken__git_status"]
    assert wb.parse_trace(_stream(), allowed=["mcp__GitKraken"])["tools"] == ["mcp__GitKraven__git_status".replace("Kraven", "Kraken")]
    assert wb.server_slug("claude.ai Atlassian MCP") == "claude_ai_Atlassian_MCP"
    assert wb.server_slug("plugin:atlassian:atlassian") == "plugin_atlassian_atlassian"


def test_the_result_line_still_parses_from_a_stream_and_an_old_single_line_output_gives_an_empty_trace():
    briefing = wb.parse_output(_stream())
    assert briefing.ok and briefing.summary == "ok" and briefing.turns == 3
    old = wb.parse_trace(_claude_json())
    assert old["servers"] == [] and old["calls"] == [] and old["version"] == "" and old["others"] == 0
    assert wb.parse_trace("not json at all\n{broken")["calls"] == []


# ---------------------------------------------------------------- generate 填进去的那部分

def test_generate_keeps_the_command_the_prompt_and_the_lists_in_the_trace():
    seen = []

    def run(args, input_text=None, timeout=0):
        seen.append((args[-1], input_text))
        return 0, _stream()

    sources = {**wb.DEFAULT_SOURCES, "pr": False}
    briefing = wb.generate(NOW, "sonnet", sources=sources, run=run, extra_tools=["mcp__x__y", "Bash"])
    assert briefing.ok and len(seen) == 1
    command, prompt = seen[0]
    assert briefing.trace["command"] == command == wb.claude_command("sonnet", sources, "high", ["mcp__x__y"])
    assert "--output-format stream-json --verbose" in command and "'mcp__x__y'" in command and "Bash" not in command
    assert briefing.trace["prompt"] == prompt and briefing.trace["gh_command"] == ""
    assert briefing.trace["allowed"][-1] == "mcp__x__y" and briefing.trace["servers"][1]["name"] == "claude.ai Slack"


def test_the_trace_is_stored_once_per_attempt_and_a_failure_keeps_the_good_briefing(tmp_path):
    good = wb.parse_output(_stream())
    good.trace = {"command": "c1", "prompt": "p1", "calls": []}
    state = wb.record(tmp_path, good, NOW)
    assert "trace" not in state["briefing"], "简报本体里不带运行记录：单独存一份"
    assert state["trace"]["command"] == "c1" and state["trace"]["ok"] is True and state["trace"]["at"] == "2026-11-19T09:00:00"
    assert wb.latest(tmp_path).summary == "ok" and wb.last_trace(tmp_path)["prompt"] == "p1"

    wb.record(tmp_path, wb.Briefing(error="boom", trace={"command": "c2"}), NOW + dt.timedelta(hours=1))
    assert wb.last_trace(tmp_path)["command"] == "c2" and wb.last_trace(tmp_path)["ok"] is False
    assert wb.latest(tmp_path).summary == "ok", "失败不抹掉上一份简报"

    wb.record(tmp_path, wb.Briefing(error="no wsl"), NOW + dt.timedelta(hours=2))
    assert wb.last_trace(tmp_path)["command"] == "c2", "这次连事件流都没有：上一份记录留着"
    assert wb.last_trace(tmp_path / "nowhere") == {}


# ---------------------------------------------------------------- 额外放行的工具

def test_extra_tools_only_accept_mcp_names_and_prefixes():
    assert wb.normalize_tools(["mcp__claude_ai_Atlassian_MCP__*", " mcp__x__y ", "Bash", "mcp__a; rm -rf ~", "mcp__x__y", "", 3,
                               "mcp__a__*b"]) == ["mcp__claude_ai_Atlassian_MCP__*", "mcp__x__y"]
    assert wb.normalize_tools("mcp__a__b\nmcp__c") == ["mcp__a__b", "mcp__c"], "手写成一个字符串也认"
    assert wb.normalize({"extra_allowed_tools": "mcp__a__b"})["extra_allowed_tools"] == ["mcp__a__b"]
    assert wb.normalize({})["extra_allowed_tools"] == [] and wb.normalize_tools(None) == []


def test_extra_tools_join_the_allow_list_once_and_reach_the_command():
    builtin = wb.allowed_tools()
    allowed = wb.allowed_tools(None, ["mcp__claude_ai_Atlassian_MCP__*", builtin[0], "Bash"])
    assert allowed == builtin + ("mcp__claude_ai_Atlassian_MCP__*",)
    command = wb.claude_command("sonnet", extra=["mcp__claude_ai_Atlassian_MCP__*"])
    assert "'mcp__claude_ai_Atlassian_MCP__*'" in command.split("--disallowedTools")[0]


def test_the_service_hands_the_extra_tools_to_generate(tmp_path):
    from pet.config import Config
    from pet.work_briefing_service import WorkBriefingService
    from tests.test_work_briefing import MONDAY_10, ON

    config = Config(tmp_path)
    config.set(wb.CONFIG_KEY, {**ON, "extra_allowed_tools": ["mcp__x__y"]})
    seen = {}

    def generate(when, model, **kw):
        seen.update(kw)
        return wb.parse_output(_stream())

    service = WorkBriefingService(config, generate=generate, spawn=lambda run: run(), now=lambda: MONDAY_10)
    assert service.generate_now() is True
    assert seen["extra_tools"] == ["mcp__x__y"]
