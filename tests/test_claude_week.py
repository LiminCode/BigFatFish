# -*- coding: utf-8 -*-
"""最近 7 天每天的 Claude Code 用量与「我发了几条消息」（仪表盘的两张磁贴）。

用量口径与灵动岛「今日用量」相同（同一条回复写好几行要去重、子代理目录一并算）；消息数
只数用户真正发出去的那几条——工具结果、子代理任务、系统注入、后台任务通知都不算。
"""

from __future__ import annotations

import datetime as dt
import json
import os

from pet.claude_usage import UsageMeter
from pet.claude_week import DAYS, WeekMeter, is_user_prompt

TODAY = dt.date(2026, 10, 24)
NOW = dt.datetime.combine(TODAY, dt.time(15, 0)).timestamp()


def _stamp(day: dt.date, hour: int = 10) -> str:
    local = dt.datetime.combine(day, dt.time(hour)).astimezone()
    return local.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _reply(mid: str, day: dt.date = TODAY, **usage) -> dict:
    return {"type": "assistant", "timestamp": _stamp(day), "requestId": f"req-{mid}",
            "message": {"id": mid, "usage": {"input_tokens": usage.get("i", 0), "output_tokens": usage.get("o", 0),
                                             "cache_creation_input_tokens": usage.get("w", 0),
                                             "cache_read_input_tokens": usage.get("r", 0)}}}


def _user(uuid: str, content, day: dt.date = TODAY, **flags) -> dict:
    return {"type": "user", "uuid": uuid, "timestamp": _stamp(day), "message": {"role": "user", "content": content},
            **flags}


def _write(path, records, *, mode: str = "w") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, mode, encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    os.utime(path, (NOW, NOW))


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> float:
        return self.now


def _meter(home, clock=None) -> WeekMeter:
    return WeekMeter(home, clock=clock or Clock())


def _session(home, name: str = "s1"):
    return home / ".claude" / "projects" / "proj" / f"{name}.jsonl"


# ---------------------------------------------------------------- 哪些算「我发的消息」

def test_only_real_prompts_count():
    assert is_user_prompt(_user("a", "修一下灵动岛"))
    assert is_user_prompt(_user("b", [{"type": "text", "text": "look"}, {"type": "image", "source": {}}]))
    assert is_user_prompt(_user("c", "<command-name>/model</command-name>")), "斜杠命令是自己敲的"
    assert is_user_prompt(_user("d", [{"type": "text", "text": "<browser_instruction>…</browser_instruction>帮我看看"}])), \
        "前面被注入了一段说明，也还是用户发的"

    assert not is_user_prompt(_user("e", [{"type": "tool_result", "content": "ok"}]))
    assert not is_user_prompt(_user("f", "子代理的任务", isSidechain=True))
    assert not is_user_prompt(_user("g", [{"type": "text", "text": "Base directory for this skill"}], isMeta=True))
    assert not is_user_prompt(_user("h", "This session is being continued", isCompactSummary=True))
    assert not is_user_prompt(_user("i", "<task-notification> <task-id>x</task-id>"))
    assert not is_user_prompt(_user("j", "<local-command-stdout>Set model</local-command-stdout>"))
    assert not is_user_prompt(_user("k", [{"type": "text", "text": "[Request interrupted by user]"}]))
    assert not is_user_prompt(_reply("m1", o=5))


# ---------------------------------------------------------------- 按天分桶

def test_seven_days_with_dedup_and_subagents(tmp_path):
    yesterday = TODAY - dt.timedelta(days=1)
    too_old = TODAY - dt.timedelta(days=DAYS)
    _write(_session(tmp_path), [
        _user("u1", "hi"),
        _reply("m1", o=10, i=1), _reply("m1", o=50, i=1, w=100, r=9000),   # 流式回复写两行：取最大
        _user("u2", [{"type": "tool_result", "content": "x"}]),
        _user("u3", "yesterday", day=yesterday), _reply("m2", day=yesterday, o=7),
        _user("u4", "a week ago", day=too_old), _reply("m3", day=too_old, o=1000),
    ])
    _write(tmp_path / ".claude" / "projects" / "proj" / "s1" / "subagents" / "agent-1.jsonl",
           [_user("u5", "sub task", isSidechain=True), _reply("m4", o=3)])

    days = _meter(tmp_path).refresh()

    assert [d.day for d in days] == [TODAY - dt.timedelta(days=n) for n in range(DAYS - 1, -1, -1)]
    today, before = days[-1], days[-2]
    assert (today.tokens, today.output, today.cache_read, today.prompts) == (50 + 1 + 100 + 3, 53, 9000, 1)
    assert (before.tokens, before.prompts) == (7, 1)
    assert sum(d.tokens for d in days) == 161, "7 天以前的不进窗口"


def test_today_matches_the_island_number(tmp_path):
    _write(_session(tmp_path), [_reply("m1", o=5, i=2, w=3), _reply("m2", o=1),
                                _reply("m3", day=TODAY - dt.timedelta(days=2), o=99)])
    island = UsageMeter(tmp_path, clock=Clock()).refresh()
    assert _meter(tmp_path).refresh()[-1].tokens == island.tokens == 11


def test_incremental_and_rolls_the_window_at_midnight(tmp_path):
    clock = Clock()
    meter = _meter(tmp_path, clock)
    path = _session(tmp_path)
    oldest = TODAY - dt.timedelta(days=DAYS - 1)
    _write(path, [_user("u1", "first", day=oldest), _reply("m1", day=oldest, o=4)])
    assert meter.refresh()[0].prompts == 1
    read = meter.bytes_read

    _write(path, [_user("u2", "second")], mode="a")
    assert meter.refresh()[-1].prompts == 1
    assert meter.bytes_read - read < 200, "只读新追加的那一行"

    clock.now += 86400                                 # 过了一天：最早那天滑出窗口
    days = meter.refresh()
    assert days[-1].day == TODAY + dt.timedelta(days=1)
    assert days[0].day == oldest + dt.timedelta(days=1)
    assert sum(d.prompts for d in days) == 1 and sum(d.tokens for d in days) == 0


def test_duplicated_records_are_counted_once(tmp_path):
    record = _user("same-uuid", "copied into a forked session")
    _write(_session(tmp_path, "a"), [record])
    _write(_session(tmp_path, "b"), [record])
    assert _meter(tmp_path).refresh()[-1].prompts == 1


def test_unreadable_lines_are_skipped(tmp_path):
    path = _session(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text('{"type":"user" broken\n[1,2]\n' + json.dumps(_user("u1", "ok")) + "\n", encoding="utf-8")
    os.utime(path, (NOW, NOW))
    assert _meter(tmp_path).refresh()[-1].prompts == 1
