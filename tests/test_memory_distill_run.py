# -*- coding: utf-8 -*-
"""会话记忆蒸馏·第二期——蒸馏（纯逻辑）：定时、挑候选、现有记忆、提示词、解析提案、提案库、跑一次。

模型调用全是假函数；不碰真实 ``~/.claude``。
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace

from pet import memory_distill as md
from pet import memory_distill_run as run

NOW = dt.datetime(2026, 10, 31, 21, 35)
SETTINGS = {**md.normalize(None), "enabled": True, "daily_at": "21:30"}


def _row(text: str, *, n: int = 0, tag: str = md.TAG_TASK, side: str = md.SIDE_PERSONAL,
         project: str = r"C:\Users\me\Github\Pet", before: str = "") -> dict:
    return {"id": f"u{n}", "time": f"2026-10-31T{10 + n // 60:02d}:{n % 60:02d}:00Z", "side": side, "project": project,
            "session_id": "s", "entrypoint": "cli", "branch": "main", "before": before, "text": text, "tag": tag}


# ---------------------------------------------------------------- 定时


def test_is_due_follows_time_done_date_and_retry_rules():
    assert not run.is_due({**SETTINGS, "enabled": False}, {}, NOW)
    assert not run.is_due(SETTINGS, {}, NOW.replace(hour=21, minute=29))
    assert run.is_due(SETTINGS, {}, NOW)
    assert not run.is_due(SETTINGS, {"done_date": "2026-10-31"}, NOW), "今天做过"
    failed = run.mark_attempt({}, NOW.replace(minute=31))
    assert not run.is_due(SETTINGS, failed, NOW), "刚失败过，歇 20 分钟"
    assert run.is_due(SETTINGS, failed, NOW.replace(minute=52))
    third = run.mark_attempt(run.mark_attempt(failed, NOW), NOW)
    assert third["attempts"] == 3 and not run.is_due(SETTINGS, third, NOW.replace(hour=23)), "一天最多 3 次"


def test_state_round_trip(tmp_path):
    assert run.load_state(tmp_path) == {}
    run.save_state(tmp_path, {"done_date": "2026-10-31", "attempts": 1})
    assert run.load_state(tmp_path)["done_date"] == "2026-10-31"


# ---------------------------------------------------------------- 挑候选


def test_select_candidates_takes_personal_rows_after_the_last_run_in_time_order():
    rows = [_row("b", n=2), _row("a", n=1), _row("corp", n=3, side=md.SIDE_WORK), _row("old", n=0)]
    picked, newest = run.select_candidates(rows, {"last_candidate_time": "2026-10-31T10:00:00Z"})
    assert [r["text"] for r in picked] == ["a", "b"], "公司侧不送；上次之前的不送；按时间排"
    assert newest == "2026-10-31T10:02:00Z"
    assert run.select_candidates([], {}) == ([], "")


def test_select_candidates_drops_tasks_first_when_over_budget():
    rows = [_row(f"t{i}", n=i) for i in range(10)] + [_row("rule", n=20, tag=md.TAG_RULE), _row("fix", n=21, tag=md.TAG_CORRECTION)]
    picked, newest = run.select_candidates(rows, {}, limit=4)
    assert [r["text"] for r in picked] == ["t8", "t9", "rule", "fix"], "规则 / 纠正全留，任务留最新的"
    assert newest == "2026-10-31T10:21:00Z", "最新时间按全部候选算，下次不漏"


def test_format_candidates_is_one_line_each_with_the_question_before():
    text = run.format_candidates([_row("以后用 A", n=1, tag=md.TAG_RULE, before="用 A 还是 B？"), _row("继续", n=2)])
    lines = text.splitlines()
    assert len(lines) == 2
    assert "| Pet | rule]" in lines[0] and "Claude: “用 A 还是 B？” → 我: “以后用 A”" in lines[0]
    assert "我: “继续”" in lines[1] and "Claude:" not in lines[1]


# ---------------------------------------------------------------- 现有记忆


def test_project_dir_encoding_matches_claude_code_and_folds_worktrees(tmp_path):
    assert run.encode_project_dir(r"C:\Users\me\Github\Pet") == "C--Users-me-Github-Pet"
    assert run.repo_root(r"C:\Users\me\Github\Pet\.claude\worktrees\feat-1\sub") == r"C:\Users\me\Github\Pet\sub"
    assert run.encode_project_dir(r"C:\Users\me\Github\Pet\.claude\worktrees\feat-1") == "C--Users-me-Github-Pet"
    assert run.encode_project_dir("/home/me/Github/corp") == "-home-me-Github-corp"
    (tmp_path / "c--Users-me-Github-Pet").mkdir()
    assert run.project_dir(r"C:\Users\me\Github\Pet", tmp_path).name == "c--Users-me-Github-Pet", "已有目录大小写不敏感"
    assert run.project_dir(r"D:\New", tmp_path) == tmp_path / "D--New"


def test_memory_context_reads_claude_md_and_each_projects_index_with_limits(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "CLAUDE.md").write_text("## 规矩\n- 用中文", encoding="utf-8")
    memory = home / ".claude" / "projects" / "C--Users-me-Github-Pet" / "memory"
    memory.mkdir(parents=True)
    (memory / "MEMORY.md").write_text("- [a](a.md) — " + "x" * 5000, encoding="utf-8")
    rows = [_row("1"), _row("2", project=r"C:\Users\me\Github\Pet\.claude\worktrees\w1"), _row("3", project=r"D:\Other")]
    text = run.memory_context(rows, home=home, entries_text="- 已有条目")
    assert "### 全局 ~/.claude/CLAUDE.md\n## 规矩\n- 用中文" in text
    assert "### 已落盘的蒸馏条目\n- 已有条目" in text
    assert text.count("### 项目") == 1, "worktree 归主仓库，没有 memory 的项目不列"
    assert len(text) < 4200 + 400


# ---------------------------------------------------------------- 提案解析


RAW = """这是提案：
```json
[
 {"action": "add", "scope": "global", "type": "feedback", "title": "回复用中文", "why": "英语是第二语言",
  "how": "解释一律中文", "evidence": ["2026-10-30 Pet：explain in chinese from now on"]},
 {"action": "change", "scope": "project", "project": "Pet", "type": "project", "title": "原始候选库放本地",
  "replaces": "候选库进 git", "evidence": "2026-10-31 Pet：同意原始库放在本地"},
 {"action": "retire", "scope": "global", "title": "每日回顾任务"},
 {"action": "bogus", "scope": "global", "title": "丢掉"},
 {"action": "add", "scope": "global", "title": ""},
 {"action": "add", "scope": "global", "type": "feedback", "title": "回复用中文"}
]
```
"""


def test_parse_proposals_validates_items_and_maps_project_names_back_to_paths():
    items = run.parse_proposals(RAW, projects=[r"C:\Users\me\Github\Pet"], run_at="2026-10-31T21:35:00")
    assert [p.action for p in items] == ["add", "change", "retire"], "非法动作 / 空标题 / 重复的都丢"
    first, second, third = items
    assert first.scope == "global" and first.project == "" and first.evidence == ["2026-10-30 Pet：explain in chinese from now on"]
    assert second.project == r"C:\Users\me\Github\Pet" and second.replaces == "候选库进 git" and second.evidence == ["2026-10-31 Pet：同意原始库放在本地"]
    assert third.type == "feedback" and third.status == run.STATUS_PENDING and third.run_at == "2026-10-31T21:35:00"
    assert len({p.id for p in items}) == 3 and all(len(p.id) == 10 for p in items)
    assert run.parse_proposals("[]") == [] and run.parse_proposals("不是 JSON") == []
    assert run.parse_proposals('{"a": 1}') == [], "不是数组"
    unknown = run.parse_proposals('[{"action":"add","scope":"project","project":"Nope","title":"x"}]', projects=[])
    assert unknown[0].scope == "project" and unknown[0].project == "Nope", "对不回去就原样留着"
    noproj = run.parse_proposals('[{"action":"add","scope":"project","project":"","title":"x"}]')
    assert noproj[0].scope == "global", "项目作用域没写项目就当全局"


def test_proposal_store_merges_tracks_status_and_dismissed(tmp_path):
    store = run.ProposalStore(tmp_path)
    items = run.parse_proposals(RAW, projects=[r"C:\Users\me\Github\Pet"])
    assert store.add(items) == 3
    assert store.add(items) == 0, "同 id 不重复"
    assert [p.title for p in store.pending()] == ["回复用中文", "原始候选库放本地", "每日回顾任务"]
    first = store.get(items[0].id)
    first.status = run.STATUS_REJECTED
    store.update(first)
    assert store.dismissed_titles() == ["回复用中文"]
    assert store.counts() == {"pending": 2, "accepted": 0, "rejected": 1, "skipped": 0, "total": 3}
    assert store.add(items) == 0, "拒掉的也不会再进来"
    data = json.loads((tmp_path / run.PROPOSALS_FILE).read_text(encoding="utf-8"))
    assert data["items"][0]["status"] == "rejected"


# ---------------------------------------------------------------- 跑一次


def _complete(text: str, *, fail: bool = False):
    calls: list[dict] = []

    def fake(prompt, system, provider, *, model="", effort="", timeout=None):
        calls.append({"prompt": prompt, "model": model, "effort": effort, "timeout": timeout})
        if fail:
            raise RuntimeError("no network")
        return SimpleNamespace(text=text, model=model or "m", input_tokens=1200, output_tokens=300)

    fake.calls = calls
    return fake


def test_run_once_builds_the_prompt_calls_the_model_and_stores_proposals(tmp_path):
    store = run.ProposalStore(tmp_path)
    store.add([run.Proposal(id="dead", action="add", scope="global", project="", type="feedback", title="别提这条",
                            status=run.STATUS_REJECTED)])
    rows = [_row("以后用中文", n=1, tag=md.TAG_RULE, before="用什么语言？"), _row("corp", n=2, side=md.SIDE_WORK)]
    complete = _complete(RAW)
    settings = {**SETTINGS, "model": "claude-haiku-5-5", "effort": "low"}
    result, state = run.run_once(NOW, settings, rows, {}, SimpleNamespace(model="p", effort="high"),
                                 store=store, complete=complete, memory="### 现有记忆\n- x")
    assert result.ok and result.error == ""
    assert result.candidates == 1 and result.proposals == 3 and result.added == 3
    assert result.model == "claude-haiku-5-5" and result.effort == "low" and result.tokens_in == 1200 and result.tokens_out == 300
    call = complete.calls[0]
    assert call["model"] == "claude-haiku-5-5" and call["effort"] == "low" and call["timeout"] == run.TIMEOUT_S
    assert "Claude: “用什么语言？” → 我: “以后用中文”" in call["prompt"] and "corp" not in call["prompt"]
    assert "### 现有记忆\n- x" in call["prompt"] and "- 别提这条" in call["prompt"], "现有记忆和「别再提」都在提示词里"
    assert "{candidates}" not in call["prompt"]
    assert state["done_date"] == "2026-10-31" and state["last_candidate_time"] == "2026-10-31T10:01:00Z"
    assert state["last_result"]["added"] == 3 and state["last_error"] == ""
    assert len(store.pending()) == 3


def test_run_once_uses_the_providers_model_when_settings_say_same_as_chat(tmp_path):
    complete = _complete("[]")
    result, state = run.run_once(NOW, SETTINGS, [_row("x", n=1)], {}, SimpleNamespace(model="claude-opus-5-5", effort="xhigh"),
                                 store=run.ProposalStore(tmp_path), complete=complete, memory="")
    assert result.ok and complete.calls[0]["model"] == "claude-opus-5-5" and complete.calls[0]["effort"] == "high"
    assert result.proposals == 0 and state["done_date"] == "2026-10-31"


def test_run_once_with_nothing_new_marks_the_day_done_without_calling_the_model(tmp_path):
    complete = _complete("[]")
    result, state = run.run_once(NOW, SETTINGS, [], {"last_candidate_time": "2026-10-31T23:00:00Z"},
                                 SimpleNamespace(model="m"), store=run.ProposalStore(tmp_path), complete=complete)
    assert result.ok and result.candidates == 0 and complete.calls == []
    assert state["done_date"] == "2026-10-31" and state["last_candidate_time"] == "2026-10-31T23:00:00Z"


def test_run_once_failure_and_bad_output_keep_the_cursor_for_a_retry(tmp_path):
    rows = [_row("以后用中文", n=1, tag=md.TAG_RULE)]
    result, state = run.run_once(NOW, SETTINGS, rows, {}, SimpleNamespace(model="m"), store=run.ProposalStore(tmp_path),
                                 complete=_complete("", fail=True), memory="")
    assert not result.ok and result.error == "no network"
    assert "done_date" not in state and "last_candidate_time" not in state and state["attempts"] == 1
    result, state = run.run_once(NOW, SETTINGS, rows, {}, SimpleNamespace(model="m"), store=run.ProposalStore(tmp_path),
                                 complete=_complete("抱歉，我不会输出 JSON"), memory="")
    assert not result.ok and "JSON" in result.error and "last_candidate_time" not in state


def test_build_prompt_keeps_user_template_and_fills_three_placeholders():
    settings = {**SETTINGS, "prompt_zh": "候选：{candidates}\n记忆：{memory}\n别提：{dismissed}\n示例 {\"a\": 1}"}
    text = run.build_prompt(settings, [_row("x", n=1)], "M", ["旧条目"], "zh")
    assert text.startswith("候选：- [") and "记忆：M" in text and "别提：- 旧条目" in text and '{"a": 1}' in text
    empty = run.build_prompt(SETTINGS, [], "", [], "zh")
    assert "(无)" in empty and "{candidates}" not in empty
    assert "{dismissed}" in md.default_prompt_template("zh") and "{dismissed}" in md.default_prompt_template("en")
