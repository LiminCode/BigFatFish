# -*- coding: utf-8 -*-
"""会话记忆蒸馏·第一期：从 Claude Code 的 transcript 抽「我说过的话」进本地候选库（纯函数 + 文件游标）。

数据形状来自 2026-10-30 对本机 ``~/.claude/projects`` 的实测：user 记录的 ``message.content`` 是字符串或
块列表（text / image / tool_result）；系统注入的消息带 ``origin.kind`` / ``turnOrigin`` 或以 ``<tag>`` /
``[Watch]`` 开头；AskUserQuestion 的回答在 tool_result 记录的 ``toolUseResult.answers`` 里。
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from pet import memory_distill as md

T0 = dt.datetime(2026, 10, 30, 9, 0, tzinfo=dt.timezone.utc)


def _rec(kind: str, content, *, n: int = 0, cwd: str = r"C:\Users\me\Github\Pet", sidechain: bool = False,
         entrypoint: str = "claude-desktop", **extra) -> str:
    record = {
        "type": kind, "isSidechain": sidechain, "uuid": f"{kind}-{n}", "sessionId": "sess-1",
        "timestamp": (T0 + dt.timedelta(minutes=n)).isoformat().replace("+00:00", "Z"),
        "cwd": cwd, "entrypoint": entrypoint, "gitBranch": "main",
        "message": {"role": kind, "content": content},
    }
    record.update(extra)
    return json.dumps(record, ensure_ascii=False)


def _assistant(text: str, n: int) -> str:
    return _rec("assistant", [{"type": "text", "text": text}], n=n)


def _lines(*records: str) -> str:
    return "".join(r + "\n" for r in records)


# ---------------------------------------------------------------- 分流与判噪 ----------------------------------------


def test_side_is_decided_by_path_not_by_entrypoint():
    """桌面版开的 WSL 会话也存在 Windows 的 ``~/.claude/projects/ssh-*`` 里（实测），所以按 cwd 分：
    POSIX 路径一律算公司侧；Windows 路径落在配置的公司目录下也算；其余个人。"""
    roots = (r"C:\Users\me\WorkSpace",)
    assert md.classify_side("/home/me/Github/corp-repo", roots) == md.SIDE_WORK
    assert md.classify_side(r"C:\Users\me\WorkSpace\corp", roots) == md.SIDE_WORK
    assert md.classify_side(r"c:\users\me\workspace\corp\sub", roots) == md.SIDE_WORK, "大小写与子目录"
    assert md.classify_side(r"C:\Users\me\WorkSpaceX", roots) == md.SIDE_PERSONAL, "只认目录边界，不认前缀"
    assert md.classify_side(r"C:\Users\me\Github\Pet", roots) == md.SIDE_PERSONAL
    assert md.classify_side("", roots) == md.SIDE_PERSONAL
    assert md.side_reason("/home/me/x", roots) == md.REASON_WSL
    assert md.side_reason(r"C:\Users\me\WorkSpace\corp", roots) == md.REASON_WORK_ROOT
    assert md.side_reason(r"C:\Users\me\Github\Pet", roots) == md.REASON_PERSONAL


@pytest.mark.parametrize("text", [
    "ok", "好的", "继续", "yes", "y", "嗯", "可以", "go ahead", "/compact", "/model opus",
    "[Request interrupted by user]", "<task-notification>done</task-notification>",
    "[Ticket watch] nothing new", "<ide_opened_file>a.py</ide_opened_file>", "",
    "This session is being continued from a previous conversation that ran out of context. Always…",
])
def test_noise_messages_are_skipped(text):
    assert md.is_noise(text), text


@pytest.mark.parametrize("text", ["以后回复都用中文", "不对，改回去", "we need this feature: record every message"])
def test_real_messages_are_kept(text):
    assert not md.is_noise(text)


def test_injected_blocks_are_stripped_but_my_words_survive():
    raw = "<system-reminder>\nstuff\n</system-reminder>\n以后 PR 描述用英文\n<ide_selection>x</ide_selection>"
    assert md.clean_text(raw) == "以后 PR 描述用英文"


def test_attachment_placeholders_are_not_my_words():
    """只发了一张图：客户端把正文写成「[Image: source: …]」，剥掉后是空的 → 噪音；图 + 话则留话。"""
    assert md.is_noise(md.clean_text("[Image: source: C:\\Users\\me\\x.png]"))
    assert md.clean_text("[Image: source: C:\\Users\\me\\x.png]\n字太大了") == "字太大了"
    assert md.clean_text("[Pasted text #1 +12 lines]\n按这个改") == "按这个改"


@pytest.mark.parametrize("text,tag", [
    ("以后回复都用中文", md.TAG_RULE),
    ("from now on, open PRs directly", md.TAG_RULE),
    ("记住：不要再用 git stash", md.TAG_RULE),
    ("不对，这个不是我要的，改回去", md.TAG_CORRECTION),
    ("don't use a font list, it maps the whole library", md.TAG_CORRECTION),
    ("决定：用 CLAUDE.md 受管块，不另开目录", md.TAG_DECISION),
    ("let's go with option B", md.TAG_DECISION),
    ("同意原始库放在本地。在页面上要加上原始库链接", md.TAG_DECISION),
    ("please add a button to the card", md.TAG_TASK),
])
def test_tagging_rules(text, tag):
    assert md.tag_for(text) == tag


# ---------------------------------------------------------------- 抽取 ----------------------------------------------


def test_extract_keeps_main_chain_human_turns_with_the_question_before_them():
    text = _lines(
        _assistant("要不要把路径放等宽字体？", 1),
        _rec("user", "要，用 Ubuntu Mono，以后分支也一样", n=2),
        _assistant("好", 3),
        _rec("user", [{"type": "text", "text": "ok"}], n=4),                              # 噪音
        _rec("user", "旁链里的话", n=5, sidechain=True),                                   # 子代理
        _rec("user", "<task-notification>x</task-notification>", n=6,
             origin={"kind": "task-notification"}, turnOrigin="task_notification"),       # 系统注入
        _rec("user", [{"type": "tool_result", "tool_use_id": "t1", "content": "out"}], n=7),  # 工具结果
        _rec("user", [{"type": "image", "source": {}}, {"type": "text", "text": "字太大了，改小"}], n=8),
    )
    found, state = md.extract(text, work_roots=())
    assert [c.text for c in found] == ["要，用 Ubuntu Mono，以后分支也一样", "字太大了，改小"]
    first = found[0]
    assert first.before == "要不要把路径放等宽字体？"
    assert first.tag == md.TAG_RULE and first.side == md.SIDE_PERSONAL
    assert first.session_id == "sess-1" and first.entrypoint == "claude-desktop" and first.branch == "main"
    assert first.project == r"C:\Users\me\Github\Pet" and first.time.startswith("2026-10-30T09:02")
    assert found[1].before == "好", "前文是最近一条 assistant 正文，中间的噪音不算"
    assert state.before == "好" and state.offset == len(text.encode("utf-8"))


def test_ask_user_question_answers_become_decisions():
    tool_result = _rec(
        "user", [{"type": "tool_result", "tool_use_id": "t9", "content": "Your questions have been answered"}], n=3,
        toolUseResult={"questions": [{"question": "落点选哪个？", "options": [{"label": "CLAUDE.md"}, {"label": "memory 目录"}]}],
                       "answers": {"落点选哪个？": "CLAUDE.md"}},
    )
    found, _state = md.extract(_lines(_assistant("我来问一下", 1), tool_result), work_roots=())
    assert len(found) == 1
    item = found[0]
    assert item.tag == md.TAG_DECISION
    assert item.question == "落点选哪个？" and item.answer == "CLAUDE.md"
    assert item.text == "落点选哪个？ → CLAUDE.md"
    assert item.before == "我来问一下"


def test_long_context_is_truncated_and_partial_last_line_waits():
    long_q = "问" * 2000
    body = _lines(_assistant(long_q, 1), _rec("user", "好，就这么办，以后都这样", n=2))
    partial = body + '{"type":"user","isSidechain":false,"message":{"role":"user","content":"还没写完'
    found, state = md.extract(partial, work_roots=())
    assert len(found) == 1
    assert len(found[0].before) == md.MAX_BEFORE_CHARS and found[0].before.endswith("…")
    assert state.offset == len(body.encode("utf-8")), "没换行的半行留到下次"


def test_extract_resumes_from_state():
    first = _lines(_assistant("A?", 1), _rec("user", "以后用 A", n=2))
    second = _lines(_rec("user", "不对，是 B", n=3))
    found1, state = md.extract(first, work_roots=())
    found2, state2 = md.extract(first + second, work_roots=(), state=state)
    assert [c.text for c in found1] == ["以后用 A"]
    assert [c.text for c in found2] == ["不对，是 B"]
    assert found2[0].before == "A?", "跨次扫描也记得上一条问题"
    assert state2.offset == len((first + second).encode("utf-8"))


def test_work_side_candidates_are_marked_at_extraction_time():
    text = _lines(_rec("user", "以后部署先跑 smoke", n=1, cwd="/home/me/Github/corp"))
    found, _ = md.extract(text, work_roots=())
    assert found[0].side == md.SIDE_WORK


# ---------------------------------------------------------------- 候选库 --------------------------------------------


def _write_transcript(root: Path, name: str, text: str) -> Path:
    folder = root / "projects" / "C--Users-me-Github-Pet"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.jsonl"
    path.write_text(text, encoding="utf-8")
    return path


def test_store_refresh_is_incremental_and_files_by_local_day(tmp_path):
    home = tmp_path / "home"
    path = _write_transcript(home, "s1", _lines(_assistant("A?", 1), _rec("user", "以后用 A", n=2)))
    store = md.CandidateStore(tmp_path / "store")
    assert store.refresh([home / "projects"], work_roots=()) == 1
    assert store.refresh([home / "projects"], work_roots=()) == 0, "没新内容不重复"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(_rec("user", "不对，是 B", n=3) + "\n")
    assert store.refresh([home / "projects"], work_roots=()) == 1
    rows = store.read_all()
    assert [r["text"] for r in rows] == ["以后用 A", "不对，是 B"]
    assert rows[0]["before"] == "A?"
    assert rows[0]["id"] == "user-2"
    day = dt.datetime.fromisoformat(rows[0]["time"]).astimezone().date().isoformat()
    assert (store.root / "candidates" / f"{day}.jsonl").exists()
    cursors = json.loads((store.root / "cursors.json").read_text(encoding="utf-8"))
    assert cursors["last_refresh"] and cursors["files"][str(path)]["offset"] == path.stat().st_size


def test_store_truncated_transcript_rescans_from_start(tmp_path):
    home = tmp_path / "home"
    path = _write_transcript(home, "s1", _lines(_rec("user", "以后用 A", n=1)))
    store = md.CandidateStore(tmp_path / "store")
    store.refresh([home / "projects"], work_roots=())
    path.write_text(_lines(_rec("user", "换了一个", n=1)), encoding="utf-8")   # 文件被重写、变短
    assert store.refresh([home / "projects"], work_roots=()) == 1
    assert [r["text"] for r in store.read_all()] == ["以后用 A", "换了一个"]


def test_store_prunes_days_older_than_retention(tmp_path):
    store = md.CandidateStore(tmp_path / "store", keep_days=90)
    old = store.root / "candidates" / "2026-01-01.jsonl"
    fresh = store.root / "candidates" / (dt.date.today().isoformat() + ".jsonl")
    old.parent.mkdir(parents=True)
    old.write_text("{}\n", encoding="utf-8")
    fresh.write_text("{}\n", encoding="utf-8")
    assert store.prune(today=dt.date.today()) == ["2026-01-01"]
    assert not old.exists() and fresh.exists()


def test_store_stats_count_today_total_sides_and_tags(tmp_path):
    home = tmp_path / "home"
    now = dt.datetime.now(dt.timezone.utc)
    stamp = now.isoformat().replace("+00:00", "Z")
    rows = [
        _rec("user", "以后用 A", n=1, timestamp=stamp),
        _rec("user", "不对，是 B", n=2, timestamp=stamp, cwd="/home/me/corp"),
        _rec("user", "please add a test", n=3, timestamp="2026-01-02T00:00:00Z"),
    ]
    _write_transcript(home, "s1", _lines(*rows))
    store = md.CandidateStore(tmp_path / "store")
    store.refresh([home / "projects"], work_roots=())
    stats = store.stats()
    assert stats["total"] == 3 and stats["today"] == 2
    assert stats["by_side"] == {md.SIDE_PERSONAL: 2, md.SIDE_WORK: 1}
    assert stats["by_tag"][md.TAG_RULE] == 1 and stats["by_tag"][md.TAG_CORRECTION] == 1 and stats["by_tag"][md.TAG_TASK] == 1
    assert stats["files"] == 1 and stats["last_refresh"]
    assert stats["days"] == 2


def test_store_survives_a_corrupt_line(tmp_path):
    home = tmp_path / "home"
    _write_transcript(home, "s1", "not json\n" + _lines(_rec("user", "以后用 A", n=1)))
    store = md.CandidateStore(tmp_path / "store")
    assert store.refresh([home / "projects"], work_roots=()) == 1


# ---------------------------------------------------------------- 配置 ----------------------------------------------


def test_config_defaults_and_normalization():
    base = md.normalize(None)
    assert base["enabled"] is False
    assert base["keep_days"] == 90
    assert base["work_roots"] == [md.default_work_root()]
    assert base["daily_at"] == "21:30"
    assert base["model"] == "" and base["effort"] == "high", "模型默认空 = 跟 AI 对话一致"
    assert md.normalize({"model": "claude-haiku-5-5"})["model"] == "claude-haiku-5-5"
    assert md.normalize({"model": "bad name!"})["model"] == ""
    assert base["prompt_zh"] == "" and base["prompt_en"] == ""
    fixed = md.normalize({"enabled": "yes", "keep_days": -5, "work_roots": "x", "daily_at": "25:99", "effort": "ultra"})
    assert fixed["enabled"] is True and fixed["keep_days"] == 90 and fixed["work_roots"] == [md.default_work_root()]
    assert fixed["daily_at"] == "21:30" and fixed["effort"] == "high"
    kept = md.normalize({"keep_days": 30, "work_roots": [r"D:\Corp", "", 3], "daily_at": "07:05"})
    assert kept["keep_days"] == 30 and kept["work_roots"] == [r"D:\Corp"] and kept["daily_at"] == "07:05"
