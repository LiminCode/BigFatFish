# -*- coding: utf-8 -*-
"""今日用量：把今天所有 Claude Code 对话用掉的 token 加起来（灵动岛信息槽）。

数字来自 Claude Code 自己的对话记录（``~/.claude/projects/**.jsonl`` 里每条回复带的
``usage``），纯本地、不联网。那是它的内部格式，所以读不懂的行一律跳过。实机核对过的
三个坑都在这里钉住：同一条回复会被写好几行（最多见过 10 行）、子代理的记录在另一个
目录、一个对话可以跨过零点。
"""

from __future__ import annotations

import json
import os

import pytest

from pet.claude_usage import (UsageAccounts, UsageMeter, UsageTotals, detail, format_tokens, headline,
                              running_distros, wsl_projects_roots, wsl_share)

DAY = 86400
NOW = 1_800_000_000 - (1_800_000_000 % DAY) + 15 * 3600      # 某天 15:00（按 UTC 算天，测试里不碰时区）
MIDNIGHT = NOW - 15 * 3600


def _stamp(unix: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(unix, timezone.utc).isoformat().replace("+00:00", "Z")


def _reply(message_id: str, *, at: float = NOW - 60, request: str = "", **usage) -> dict:
    fields = {"input": "input_tokens", "output": "output_tokens",
              "cache_write": "cache_creation_input_tokens", "cache_read": "cache_read_input_tokens"}
    return {"type": "assistant", "timestamp": _stamp(at), "requestId": request or f"req-{message_id}",
            "message": {"id": message_id, "model": "claude-opus-5-5",
                        "usage": {fields[name]: value for name, value in usage.items()}}}


def _write(path, records, *, mtime: float = NOW, mode: str = "w") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, mode, encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    os.utime(path, (mtime, mtime))


class Clock:
    def __init__(self) -> None:
        self.now = float(NOW)

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def home(tmp_path):
    return tmp_path


def _meter(home, clock=None) -> UsageMeter:
    clock = clock or Clock()
    meter = UsageMeter(home, clock=clock, day_start=lambda now: now - (now % DAY))
    meter.clock = clock
    return meter


def _projects(home):
    return home / ".claude" / "projects"


# ---------------------------------------------------------------- 数字怎么显示

@pytest.mark.parametrize("count, text", [
    (0, "0"), (856, "856"), (999, "999"), (1000, "1.0K"), (12_345, "12.3K"), (999_949, "999.9K"),
    (999_950, "1.00M"), (2_379_060, "2.38M"), (12_345_678, "12.3M"), (190_451_606, "190M"),
    (1_234_567_890, "1.23B"),
])
def test_format_tokens(count, text):
    assert format_tokens(count) == text


def test_headline_counts_new_tokens_and_keeps_cache_reads_apart():
    """缓存读取是同一段上下文每一轮被重读一遍，量级是别的几十倍：算进去就只剩它了。"""
    totals = UsageTotals(input=848, output=561_677, cache_write=1_816_535, cache_read=188_072_546, messages=372)
    assert totals.tokens == 848 + 561_677 + 1_816_535
    assert totals.headline == "今日 2.38M"
    assert totals.detail == ("今日 Claude Code 用量 2.38M：输出 561.7K · 输入 848 · 缓存写入 1.82M"
                             "（另有缓存读取 188M，不计入）")
    assert UsageTotals().headline == "今日 0"


# ---------------------------------------------------------------- 统计

def test_sums_every_reply_from_today_across_projects(home):
    _write(_projects(home) / "C--work-api" / "aaaa.jsonl", [
        {"type": "user", "timestamp": _stamp(NOW - 100), "message": {"role": "user"}},
        _reply("m1", input=10, output=200, cache_write=3000, cache_read=40_000),
        _reply("m2", input=1, output=50),
    ])
    _write(_projects(home) / "C--work-web" / "bbbb.jsonl", [_reply("m3", output=700, cache_read=5)])

    totals = _meter(home).refresh()

    assert totals == UsageTotals(input=11, output=950, cache_write=3000, cache_read=40_005, messages=3)


def test_one_reply_written_many_times_counts_once_with_its_final_numbers(home):
    """流式回复的每个内容块各写一行、带同一个 message id；后写的输出数更大。"""
    _write(_projects(home) / "p" / "aaaa.jsonl", [
        _reply("m1", input=5, output=10, cache_read=900),
        _reply("m1", input=5, output=120, cache_read=900),
        _reply("m1", input=5, output=388, cache_read=900),
        _reply("m2", output=7),
    ])
    assert _meter(home).refresh() == UsageTotals(input=5, output=395, cache_read=900, messages=2)


def test_subagent_transcripts_are_counted_too(home):
    _write(_projects(home) / "p" / "aaaa.jsonl", [_reply("m1", output=100)])
    _write(_projects(home) / "p" / "aaaa" / "subagents" / "agent-1.jsonl", [_reply("s1", output=40)])
    _write(_projects(home) / "p" / "aaaa" / "tool-results" / "x.jsonl", [_reply("t1", output=9999)])
    assert _meter(home).refresh().output == 140


def test_a_conversation_spanning_midnight_only_counts_todays_part(home):
    _write(_projects(home) / "p" / "aaaa.jsonl", [
        _reply("yesterday", at=MIDNIGHT - 10, output=1000),
        _reply("today", at=MIDNIGHT + 10, output=7),
    ])
    assert _meter(home).refresh().output == 7


def test_files_untouched_today_are_not_even_opened(home):
    _write(_projects(home) / "p" / "old.jsonl", [_reply("m1", output=5)], mtime=MIDNIGHT - 3600)
    meter = _meter(home)
    assert meter.refresh() == UsageTotals()
    assert meter.bytes_read == 0


def test_garbage_and_foreign_shapes_are_skipped(home):
    path = _projects(home) / "p" / "aaaa.jsonl"
    _write(path, [_reply("m1", output=3)])
    with open(path, "ab") as handle:
        handle.write(b'\xff\xfe not json "usage"\n')
        handle.write(b'{"type":"assistant","message":{"usage":"nope"},"timestamp":"x"}\n')
        handle.write(b'{"type":"assistant","message":{"id":"m9","usage":{"output_tokens":"many"}},"timestamp":"'
                     + _stamp(NOW).encode() + b'"}\n')
        handle.write(b'["usage"]\n')
    os.utime(path, (NOW, NOW))
    assert _meter(home).refresh() == UsageTotals(output=3, messages=2), "数字读不出来的那条按 0 记，不整条丢"
    assert _meter(home / "nowhere").refresh() == UsageTotals()


# ---------------------------------------------------------------- 增量

def test_later_refreshes_only_read_what_was_appended(home):
    path = _projects(home) / "p" / "aaaa.jsonl"
    _write(path, [_reply(f"m{i}", output=10) for i in range(50)])
    meter = _meter(home)
    assert meter.refresh().output == 500
    first = meter.bytes_read

    assert meter.refresh().output == 500
    assert meter.bytes_read == first, "没有新内容：一个字节都不读"

    _write(path, [_reply("new", output=1)], mode="a")
    assert meter.refresh().output == 501
    assert 0 < meter.bytes_read - first < first / 10


def test_a_line_caught_half_written_is_finished_next_time(home):
    path = _projects(home) / "p" / "aaaa.jsonl"
    line = (json.dumps(_reply("m1", output=42)) + "\n").encode()
    path.parent.mkdir(parents=True)
    path.write_bytes(line[:60])
    os.utime(path, (NOW, NOW))
    meter = _meter(home)
    assert meter.refresh() == UsageTotals()

    with open(path, "ab") as handle:
        handle.write(line[60:])
    os.utime(path, (NOW, NOW))
    assert meter.refresh().output == 42


def test_a_rewritten_file_is_read_again_without_double_counting(home):
    path = _projects(home) / "p" / "aaaa.jsonl"
    _write(path, [_reply("m1", output=10), _reply("m2", output=20), _reply("m3", output=30)])
    meter = _meter(home)
    assert meter.refresh().output == 60
    _write(path, [_reply("m1", output=10)])            # 文件变短了（被重写）
    assert meter.refresh().output == 60, "已经记下的回复不会因为文件变短而消失，也不会重复记"


def test_totals_start_over_at_midnight(home):
    path = _projects(home) / "p" / "aaaa.jsonl"
    _write(path, [_reply("m1", output=10)])
    meter = _meter(home)
    assert meter.refresh().output == 10

    meter.clock.now = NOW + DAY                      # 第二天 15:00
    assert meter.refresh() == UsageTotals(), "昨天的文件今天没动过"

    _write(path, [_reply("m2", at=NOW + DAY - 5, output=3)], mode="a", mtime=NOW + DAY)
    assert meter.refresh().output == 3, "同一个文件里昨天的那条不算"


# ---------------------------------------------------------------- 两个账号：Windows 本机 + WSL 发行版

def _accounts(home, wsl_roots, clock=None) -> UsageAccounts:
    return UsageAccounts(home, wsl_roots=wsl_roots, clock=clock or Clock(), day_start=lambda now: now - (now % DAY))


def test_a_meter_can_span_several_roots(home):
    _write(home / "a" / "p" / "s.jsonl", [_reply("m1", output=10)])
    _write(home / "b" / "q" / "s.jsonl", [_reply("m2", output=5)])
    meter = UsageMeter(roots=[home / "a", home / "b"], clock=Clock(), day_start=lambda now: now - (now % DAY))
    assert meter.refresh().output == 15


def test_the_two_accounts_are_counted_and_worded_apart(home):
    _write(_projects(home) / "p" / "s.jsonl", [_reply("m1", output=1000)])
    wsl = home / "wsl" / "projects"
    _write(wsl / "q" / "s.jsonl", [_reply("w1", output=300, input=5)])

    got = _accounts(home, lambda: [wsl]).refresh()

    assert [(a.key, a.label, a.totals.output) for a in got] == [("windows", "Win", 1000), ("wsl", "WSL", 300)]
    assert headline(got) == "今日 Win 1.0K · WSL 305"
    assert detail(got).splitlines() == [
        "Win：1.0K（输出 1.0K · 输入 0 · 缓存写入 0；另有缓存读取 0，不计入）",
        "WSL：305（输出 300 · 输入 5 · 缓存写入 0；另有缓存读取 0，不计入）"]


def test_without_wsl_the_wording_is_the_old_single_number(home):
    _write(_projects(home) / "p" / "s.jsonl", [_reply("m1", output=2_380_000)])
    got = _accounts(home, lambda: None).refresh()
    assert [a.key for a in got] == ["windows"]
    assert headline(got) == "今日 2.38M" and detail(got) == got[0].totals.detail


def test_an_unreachable_wsl_shows_dashes_then_recovers_and_keeps_todays_numbers(home):
    roots: list = []
    wsl = home / "wsl" / "projects"
    accounts = _accounts(home, lambda: list(roots))

    got = accounts.refresh()
    assert got[1].totals is None
    assert headline(got) == "今日 Win 0 · WSL --"
    assert detail(got).splitlines()[1].startswith("WSL：读不到")

    _write(wsl / "q" / "s.jsonl", [_reply("w1", output=7)])
    roots.append(wsl)
    assert accounts.refresh()[1].totals.output == 7
    roots.clear()                                           # 发行版停了：今天已经读到的数不丢
    assert accounts.refresh()[1].totals.output == 7


def test_wsl_roots_come_from_running_distros_and_their_home_folders(tmp_path):
    share = tmp_path / "share"
    (share / "Ubuntu" / "home" / "me" / ".claude" / "projects").mkdir(parents=True)
    (share / "Ubuntu" / "home" / "other").mkdir(parents=True)
    (share / "Debian" / "home" / "me" / ".claude" / "projects").mkdir(parents=True)
    unc = lambda distro: share / distro  # noqa: E731

    assert wsl_projects_roots(distros=["Ubuntu", "Debian"], running=["Ubuntu"], share=unc) == [
        share / "Ubuntu" / "home" / "me" / ".claude" / "projects"]
    assert wsl_projects_roots(distros=["Ubuntu", "Debian"], running=["Debian", "Ubuntu"], share=unc) == [
        share / "Ubuntu" / "home" / "me" / ".claude" / "projects", share / "Debian" / "home" / "me" / ".claude" / "projects"]
    assert wsl_projects_roots(distros=[], running=[], share=unc) is None, "没有 WSL：就一个账号"
    assert wsl_projects_roots(distros=["Ubuntu"], running=[], share=unc) == [], "没在运行：不碰共享（碰了会把它拉起来）"
    assert wsl_projects_roots(distros=["Ubuntu"], running=["Ubuntu"], share=lambda d: tmp_path / "nowhere") == []
    assert str(wsl_share("Ubuntu-24.04") / "home") == r"\\wsl.localhost\Ubuntu-24.04\home"


def test_running_distros_are_read_from_wsl_exe():
    assert running_distros(runner=lambda args, **kw: (0, "Ubuntu-24.04\r\n\r\ndocker-desktop\r\n")) == [
        "Ubuntu-24.04", "docker-desktop"]
    assert running_distros(runner=lambda args, **kw: (1, "")) == []
    assert running_distros(runner=lambda args, **kw: (0, "U\x00b\x00u\x00\n")) == ["Ubu"], "UTF-16 的残渣也认得"
