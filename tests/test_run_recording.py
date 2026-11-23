# -*- coding: utf-8 -*-
"""把已有的定时功能接进运行记录（``pet/run_recording.py``）：不改那些服务，只听它们「开始了 / 结束了」的信号。

从公开面测：喂给记录器和服务信号一样的参数，看运行记录里落了什么。结果对象用真的数据类（``Briefing`` / ``WatchResult``）。
"""
from __future__ import annotations

import ast
import datetime as dt
from pathlib import Path

import pytest

from pet import run_journal, run_recording as rr
from pet import slack_watch as sw
from pet import work_briefing as wb

START = dt.datetime(2026, 11, 22, 9, 0, 0)


class _Clock:
    def __init__(self) -> None:
        self.elapsed = 0.0

    def timer(self) -> float:
        return self.elapsed


def _recorder(tmp_path, job, outcome, **options):
    clock = _Clock()
    journal = run_journal.Journal(tmp_path / "journal", now=lambda: START, timer=clock.timer)
    return rr.Recorder(journal, job, outcome, **options), journal, clock


def test_a_scheduled_briefing_is_one_row_with_how_long_it_took_and_what_it_cost(tmp_path):
    recorder, journal, clock = _recorder(tmp_path, rr.WORK_BRIEFING, rr.briefing_outcome)
    recorder.started(False)
    clock.elapsed = 94.0
    recorder.finished(wb.Briefing(ok=True, summary="三件事要看", markdown="# 今天\n- 机密", model="claude-opus-5-5", effort="high",
                                  tokens_in=41000, tokens_out=2300, turns=7, seconds=93.2), False)
    row, = journal.read()
    assert (row["job"], row["trigger"], row["result"], row["seconds"]) == ("work_briefing", "schedule", "ok", 94.0)
    assert row["effects"] == [{"kind": "model", "model": "claude-opus-5-5", "effort": "high", "tokens_in": 41000, "tokens_out": 2300, "turns": 7}]
    assert "三件事" not in str(row) and "机密" not in str(row), "运行记录里没有正文和概要"


def test_a_run_the_user_asked_for_is_marked_manual_and_a_failure_keeps_the_reason(tmp_path):
    recorder, journal, _ = _recorder(tmp_path, rr.PERSONAL_BRIEFING, rr.briefing_outcome)
    recorder.started(True)
    recorder.finished(wb.Briefing(ok=False, error="claude 退出码 1：not logged in"), True)
    row, = journal.read()
    assert (row["trigger"], row["result"], row["error"]) == ("manual", "failed", "claude 退出码 1：not logged in")


def test_a_finish_without_a_start_is_still_recorded(tmp_path):
    """个人简报没有可用的模型服务时，不发「开始」就直接发「结束」。"""
    recorder, journal, _ = _recorder(tmp_path, rr.PERSONAL_BRIEFING, rr.briefing_outcome)
    recorder.finished(wb.Briefing(ok=False, error="没有模型服务"), False)
    row, = journal.read()
    assert (row["trigger"], row["result"], row["seconds"]) == ("schedule", "failed", 0.0)


def test_two_runs_in_a_row_are_two_rows_each_with_its_own_duration(tmp_path):
    recorder, journal, clock = _recorder(tmp_path, rr.WORK_BRIEFING, rr.briefing_outcome)
    for started_at, took in ((0.0, 10.0), (100.0, 30.0)):
        clock.elapsed = started_at
        recorder.started(False)
        clock.elapsed = started_at + took
        recorder.finished(wb.Briefing(ok=True), False)
    assert [row["seconds"] for row in reversed(journal.read())] == [10.0, 30.0]


@pytest.mark.parametrize(("result", "fresh", "expected"), [
    (sw.WatchResult(ok=True, items=[{"title": "a"}, {"title": "b"}], turns=3), [{"title": "b"}], ("ok", {"kind": "found", "items": 2, "new": 1, "turns": 3})),
    (sw.WatchResult(ok=True, items=[{"title": "a"}], turns=2), [], ("noop", {"kind": "found", "items": 1, "new": 0, "turns": 2})),
    (sw.WatchResult(ok=False, error="wsl 没回话"), [], ("failed", {"kind": "found", "items": 0, "new": 0, "turns": 0}))])
def test_a_slack_check_is_ok_only_when_it_found_something_new(tmp_path, result, fresh, expected):
    recorder, journal, _ = _recorder(tmp_path, rr.SLACK_WATCH, rr.slack_outcome)
    recorder.started(False)
    recorder.finished(result, False, fresh)
    row, = journal.read()
    assert (row["result"], row["effects"][0]) == expected and "title" not in str(row)


def test_someone_is_told_after_each_row_and_their_failure_changes_nothing(tmp_path):
    told = []
    recorder, journal, _ = _recorder(tmp_path, rr.WORK_BRIEFING, rr.briefing_outcome, after=lambda: told.append(1))
    recorder.started(False)
    recorder.finished(wb.Briefing(ok=True), False)
    assert told == [1]

    def broken():
        raise RuntimeError("page is gone")

    recorder, journal, _ = _recorder(tmp_path / "b", rr.WORK_BRIEFING, rr.briefing_outcome, after=broken)
    recorder.finished(wb.Briefing(ok=True), False)
    assert len(journal.read()) == 1


def test_a_result_the_recorder_cannot_read_never_reaches_the_service(tmp_path):
    """记录器挂在服务的信号上：它出错不能让简报的结果传不到界面。"""
    recorder, journal, _ = _recorder(tmp_path, rr.WORK_BRIEFING, rr.briefing_outcome)
    recorder.started(False)
    recorder.finished(object(), False)                                     # 不是 Briefing
    recorder.finished()                                                    # 连参数都不对
    assert all(row["result"] == "failed" for row in journal.read())


def test_module_does_not_import_qt():
    tree = ast.parse(Path(rr.__file__).read_text(encoding="utf-8"))
    names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    names |= {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not any("PySide" in name for name in names)
