# -*- coding: utf-8 -*-
"""工作笔记（纯逻辑层 ``pet/work_notes.py``）。

用户 2026-10-15 的需求：随手记一条 Slack 链接 / Jira 链接 / 片段，原文逐字保留；WSL 里的公司
Claude Code 去读那条消息 / 工单，写摘要、定下次提醒；笔记是 Obsidian 风格的 Markdown，存在
公司私有仓库 AI-Base-Memory 的 ``note/`` 目录（本地副本在 Windows，git 从 WSL 跑）。
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from pet import work_notes as wn

NOW = dt.datetime(2026, 10, 15, 19, 40, 0)
SLACK = "https://acme.slack.com/archives/C0123/p1760000000000100"
JIRA = "https://acme.atlassian.net/browse/OPS-1234"


# ---------------------------------------------------------------- 新建一条
def test_a_slack_link_becomes_a_note_with_the_original_kept_verbatim():
    text = f"  {SLACK}\n老板说这个要今天看一下  \n"
    note = wn.new_note(text, NOW)
    assert note.original == text, "原文一个字符都不动"
    assert note.kind == "slack" and note.links == [SLACK]
    assert note.created == "2026-10-15T19:40:00" and note.status == "open"
    assert note.title == "老板说这个要今天看一下", "标题取第一行不是链接的文字"
    assert note.name.startswith("2026-10-15-1940-") and note.name.endswith("老板说这个要今天看一下")
    assert "work/note" in note.tags and "slack" in note.tags


def test_a_jira_link_or_bare_key_is_recognised():
    assert wn.new_note(JIRA, NOW).kind == "jira"
    note = wn.new_note("OPS-1234 需要我评审方案", NOW)
    assert note.kind == "jira" and note.title == "OPS-1234 需要我评审方案"


def test_plain_text_without_links_is_just_text():
    note = wn.new_note("周五前把季度报告发给 Amy", NOW)
    assert note.kind == "text" and note.links == [] and note.title == "周五前把季度报告发给 Amy"


def test_a_link_only_note_gets_a_generic_title():
    assert wn.new_note(SLACK, NOW).title == "Slack 消息"
    assert wn.new_note(JIRA, NOW).title == "Jira OPS-1234"


def test_file_names_are_safe_and_short():
    name = wn.new_note("a/b\\c:d*e?f\"g<h>i|j " + "很长" * 40, NOW).name
    assert not any(ch in name for ch in '/\\:*?"<>|')
    assert len(name) <= 16 + wn.MAX_SLUG_CHARS


# ---------------------------------------------------------------- Markdown 往返
def test_render_and_parse_round_trip_keeps_every_field():
    note = wn.new_note(f"{JIRA}\n等 Bob 回复 \"方案 B\"", NOW)
    note = wn.apply_summary(note, wn.SummaryResult(
        ok=True, summary="OPS-1234 在等 Bob 的回复", details="- 工单状态：In Review\n- 负责人：Bob",
        remind_at="2026-10-16T09:00:00", reason="明早上班先看看 Bob 回了没有", tags=["jira", "ops"]), NOW)
    text = wn.render(note)
    assert text.startswith("---\n") and "\n## 原文\n" in text and "\n## AI 摘要\n" in text and "\n## 提醒\n" in text
    assert note.original.strip() in text
    back = wn.parse(text, note.name)
    assert back == note


def test_parse_tolerates_a_note_edited_by_hand_in_obsidian():
    text = (
        "---\n"
        "created: 2026-10-15T19:40:00\n"
        "title: 手改过的标题\n"
        "kind: text\n"
        "status: done\n"
        "tags:\n  - work/note\n  - 随手\n"
        "---\n"
        "# 手改过的标题\n\n"
        "## 原文\n\n原文第一行\n\n原文第二行 [[某个笔记]] #tag\n\n"
        "## AI 摘要\n\n**一句话**\n\n- 要点 1\n\n"
        "## 提醒\n\n（无）\n"
    )
    note = wn.parse(text, "2026-10-15-1940-x")
    assert note.title == "手改过的标题" and note.status == "done" and note.tags == ["work/note", "随手"]
    assert note.original == "原文第一行\n\n原文第二行 [[某个笔记]] #tag"
    assert note.summary == "一句话" and note.details == "- 要点 1"
    assert note.remind_at == "" and note.links == []


def test_notes_are_saved_atomically_and_listed_newest_first(tmp_path):
    folder = tmp_path / "note"
    older = wn.new_note("先记的", NOW - dt.timedelta(hours=1))
    newer = wn.new_note("后记的", NOW)
    wn.save(folder, older)
    wn.save(folder, newer)
    assert sorted(p.name for p in folder.iterdir()) == sorted([older.name + ".md", newer.name + ".md"])
    assert [n.title for n in wn.load_all(folder)] == ["后记的", "先记的"]
    (folder / "junk.txt").write_text("not a note", encoding="utf-8")
    (folder / "broken.md").write_text("no frontmatter at all", encoding="utf-8")
    assert [n.title for n in wn.load_all(folder)] == ["后记的", "先记的", "broken"], "读坏的只按标题兜底，不炸"


# ---------------------------------------------------------------- 让公司 Claude 总结
def test_the_prompt_quotes_the_original_and_asks_for_json_only():
    note = wn.new_note(f"{SLACK}\n看一下这个线程", NOW)
    prompt = wn.build_prompt(note, NOW)
    assert note.original in prompt and "2026-10-15 19:40" in prompt
    assert "JSON" in prompt and "remind_at" in prompt and "只读" in prompt


def _claude_json(payload: dict) -> str:
    return "junk from login shell\n" + json.dumps({"result": json.dumps(payload, ensure_ascii=False),
                                                 "subtype": "success", "num_turns": 5})


def test_a_good_answer_fills_summary_reminder_and_tags():
    out = _claude_json({"summary": "等 Bob 回复", "details": "- 状态 In Review", "remind_at": "2026-10-16T09:00",
                        "reason": "明早看", "tags": ["Jira", " ops ", "", "x" * 50]})
    result = wn.parse_summary(out, NOW)
    assert result.ok and result.summary == "等 Bob 回复" and result.details == "- 状态 In Review"
    assert result.remind_at == "2026-10-16T09:00:00" and result.reason == "明早看"
    assert result.tags == ["jira", "ops", "x" * wn.MAX_TAG_CHARS] and result.turns == 5


def test_model_tokens_and_cost_come_from_the_result_record():
    """用户 2026-10-15：每条笔记要能看到用了哪个模型、多少 token。字段来自 claude -p 的 modelUsage / total_cost_usd。"""
    record = {"result": json.dumps({"summary": "s", "remind_at": None}), "subtype": "success", "num_turns": 2,
              "total_cost_usd": 0.0283158,
              "modelUsage": {"claude-sonnet-5-5": {"inputTokens": 2, "outputTokens": 4, "cacheReadInputTokens": 28278,
                                                   "cacheCreationInputTokens": 6361, "costUSD": 0.0283158}}}
    result = wn.parse_summary(json.dumps(record), NOW)
    assert result.ok and result.model == "claude-sonnet-5-5"
    assert result.tokens_in == 2 + 28278 + 6361 and result.tokens_out == 4 and result.cost_usd == pytest.approx(0.0283158)

    note = wn.apply_summary(wn.new_note("x", NOW), wn.SummaryResult(ok=True, summary="s", model="claude-sonnet-5-5",
                                                                   tokens_in=34641, tokens_out=4, cost_usd=0.0283158,
                                                                   seconds=9.7), NOW)
    back = wn.parse(wn.render(note), note.name)
    assert (back.model, back.tokens_in, back.tokens_out, back.seconds) == ("claude-sonnet-5-5", 34641, 4, 9.7)
    assert back.cost_usd == pytest.approx(0.0283158, abs=1e-6)
    assert "model: claude-sonnet-5-5" in wn.render(note) and "tokens_in: 34641" in wn.render(note)
    assert "tokens_in" not in wn.render(wn.new_note("y", NOW)), "没总结过的不写用量字段"
    assert wn.usage_of({"usage": {"input_tokens": 5, "output_tokens": 7}}) == ("", 5, 7, 0.0), "没有 modelUsage 时退回 usage"


def test_a_reminder_in_the_past_or_malformed_is_dropped():
    assert wn.parse_summary(_claude_json({"summary": "s", "remind_at": "2026-10-15T08:00"}), NOW).remind_at == ""
    assert wn.parse_summary(_claude_json({"summary": "s", "remind_at": "下周吧"}), NOW).remind_at == ""
    assert wn.parse_summary(_claude_json({"summary": "s", "remind_at": None}), NOW).remind_at == ""


def test_failures_are_folded_into_an_error():
    assert "没有返回结果" in wn.parse_summary("", NOW).error
    assert "不是约定的 JSON" in wn.parse_summary(_claude_json_text("随便说两句"), NOW).error
    assert wn.parse_summary(_claude_json({"error": "Slack 读不到"}), NOW).error == "Slack 读不到"


def _claude_json_text(text: str) -> str:
    return json.dumps({"result": text, "subtype": "success"})


def test_summarize_runs_claude_in_wsl_with_read_only_tools_and_the_prompt_on_stdin():
    calls = []

    def run(args, *, input_text=None, timeout=None):
        calls.append((args, input_text, timeout))
        return 0, _claude_json({"summary": "ok", "remind_at": None})

    note = wn.new_note("看看", NOW)
    result = wn.summarize(note, NOW, "sonnet", run=run, clock=iter([10.0, 52.5]).__next__)
    assert result.ok and result.seconds == 42.5
    (args, prompt, timeout), = calls
    assert args[:3] == ["-e", "bash", "-lc"] and " claude -p " in args[-1] and "--tools ''" in args[-1]
    assert "slack_read_thread" in args[-1] and "getJiraIssue" in args[-1] and "slack_send_message" in args[-1]
    assert note.original in prompt and timeout == wn.CLAUDE_TIMEOUT_S


def test_without_wsl_summarize_says_so():
    result = wn.summarize(wn.new_note("x", NOW), NOW, "sonnet", run=lambda *a, **k: (127, ""))
    assert not result.ok and "WSL" in result.error


def test_apply_summary_keeps_the_original_and_records_when():
    note = wn.new_note("原文", NOW)
    done = wn.apply_summary(note, wn.SummaryResult(ok=True, summary="摘要", details="- a", remind_at="2026-10-16T09:00:00",
                                                   reason="r", tags=["jira"]), NOW)
    assert done.original == "原文" and done.summary == "摘要" and done.summarized_at == "2026-10-15T19:40:00"
    assert done.remind_at == "2026-10-16T09:00:00" and done.tags == ["work/note", "jira"]
    failed = wn.apply_summary(note, wn.SummaryResult(error="boom"), NOW)
    assert failed == note, "失败不动笔记"


# ---------------------------------------------------------------- 提醒
def test_due_reminders_are_open_notes_whose_time_has_come_and_not_yet_alerted():
    a = wn.new_note("a", NOW).replace(remind_at="2026-10-15T19:30:00")
    b = wn.new_note("b", NOW).replace(remind_at="2026-10-15T20:00:00")
    c = wn.new_note("c", NOW).replace(remind_at="2026-10-15T19:00:00", status="done")
    d = wn.new_note("d", NOW).replace(remind_at="2026-10-15T19:00:00")
    state = {"alerted": {d.name: "2026-10-15T19:00:00"}}
    assert [n.name for n in wn.due_reminders([a, b, c, d], state, NOW)] == [a.name]
    wn.mark_alerted(state, a)
    assert wn.due_reminders([a, b, c, d], state, NOW) == []
    assert wn.due_reminders([a.replace(remind_at="2026-10-15T19:35:00")], state, NOW), "改了时间就算新的一次"


def test_snooze_and_finish():
    note = wn.new_note("a", NOW).replace(remind_at="2026-10-15T19:30:00")
    later = wn.snooze(note, 60, NOW)
    assert later.remind_at == "2026-10-15T20:40:00" and later.status == "open" and "稍后" in later.reason
    assert wn.finish(note).status == "done" and wn.finish(note).remind_at == ""


# ---------------------------------------------------------------- git（从 WSL 跑）与路径
def test_windows_paths_become_mnt_paths_for_wsl():
    assert wn.wsl_path(r"C:\Users\me\WorkSpace\AI-Base-Memory") == "/mnt/c/Users/me/WorkSpace/AI-Base-Memory"
    assert wn.wsl_path("D:/x y/z") == "/mnt/d/x y/z"
    assert wn.wsl_path("/home/me/repo") == "/home/me/repo"


def test_sync_adds_commits_pulls_and_pushes_only_the_note_folder():
    calls = []

    def run(args, *, input_text=None, timeout=None):
        calls.append(args[-1])
        return 0, "ok"

    ok, _out = wn.sync({"repo_dir": r"C:\Users\me\WorkSpace\AI-Base-Memory"}, "note: 加一条", run=run)
    assert ok
    cmd = calls[-1]
    assert cmd.startswith("cd '/mnt/c/Users/me/WorkSpace/AI-Base-Memory' && ")
    assert "git add -A -- 'note' '.obsidian'" in cmd, "笔记和 Obsidian 库配置一起推" and "git commit -q -m 'note: 加一条'" in cmd
    assert "git pull -q --rebase" in cmd and "git push -q" in cmd
    assert cmd.index("git add") < cmd.index("git commit") < cmd.index("git pull") < cmd.index("git push")


def test_sync_reports_git_failures_with_the_tail_of_the_output():
    ok, out = wn.sync({"repo_dir": r"C:\r"}, "m", run=lambda *a, **k: (1, "fatal: could not read from remote"))
    assert not ok and "could not read" in out
    ok, out = wn.sync({"repo_dir": r"C:\r"}, "m", run=lambda *a, **k: (127, ""))
    assert not ok and "WSL" in out


# ---------------------------------------------------------------- Obsidian
def test_obsidian_uri_points_into_the_registered_vault(tmp_path):
    repo = tmp_path / "AI-Base-Memory"
    vaults = {"abc": {"path": str(repo)}, "def": {"path": str(tmp_path / "Other")}}
    note = wn.new_note("x", NOW)
    uri = wn.obsidian_uri(str(repo).upper(), note, vaults)
    assert uri.startswith("obsidian://open?vault=AI-Base-Memory&file=note%2F2026-10-15-1940-")
    assert wn.obsidian_uri(str(tmp_path / "nope"), note, vaults) == "", "没登记成库就给空，让调用方退回打开文件夹"


def test_obsidian_vaults_are_read_from_the_app_config(tmp_path, monkeypatch):
    cfg = tmp_path / "obsidian" / "obsidian.json"
    cfg.parent.mkdir()
    cfg.write_text(json.dumps({"vaults": {"a1": {"path": "C:\\v", "ts": 1}}}), encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert wn.obsidian_vaults() == {"a1": {"path": "C:\\v", "ts": 1}}
    cfg.write_text("{broken", encoding="utf-8")
    assert wn.obsidian_vaults() == {}


# ---------------------------------------------------------------- 配置
def test_settings_have_safe_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    settings = wn.normalize(None)
    assert settings == {"enabled": True, "repo_dir": str(tmp_path / "WorkSpace" / "AI-Base-Memory"), "model": "sonnet"}
    assert wn.normalize({"enabled": 0, "repo_dir": " D:\\x ", "model": "bad model!"}) == {
        "enabled": False, "repo_dir": "D:\\x", "model": "sonnet"}
    assert wn.notes_dir(settings) == tmp_path / "WorkSpace" / "AI-Base-Memory" / "note"


@pytest.mark.parametrize("value", ["", None, 5, [], {"repo_dir": ""}])
def test_bad_settings_fall_back_to_defaults(value):
    assert wn.normalize(value)["repo_dir"] == wn.default_repo_dir()
