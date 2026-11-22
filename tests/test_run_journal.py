# -*- coding: utf-8 -*-
"""运行记录（``pet/run_journal.py``）：肥鱼自己跑的每一件事记一行——哪个任务、被什么触发、每步多久、结果、对仓库做了什么。

从公开面测：开一条记录、记步骤和效果、收尾落盘；按月分文件、过期的整月删掉；读回来新的在前；写不进去不抛。
"""
from __future__ import annotations

import ast
import datetime as dt
import json
import threading
from pathlib import Path

import pytest

from pet import run_journal as rj

START = dt.datetime(2026, 11, 22, 15, 9, 3)


class _Clock:
    """假时钟：``now()`` 是墙上的时间，``timer()`` 是计时用的秒数；``tick`` 两个一起往前走。"""

    def __init__(self, now: dt.datetime = START) -> None:
        self.at, self.elapsed = now, 100.0

    def now(self) -> dt.datetime:
        return self.at

    def timer(self) -> float:
        return self.elapsed

    def tick(self, seconds: float) -> None:
        self.at += dt.timedelta(seconds=seconds)
        self.elapsed += seconds


def _journal(tmp_path, clock=None, **options) -> tuple[rj.Journal, _Clock]:
    clock = clock or _Clock()
    return rj.Journal(tmp_path / rj.DIR_NAME, now=clock.now, timer=clock.timer, **options), clock


def _lines(tmp_path, month: str) -> list[dict]:
    path = tmp_path / rj.DIR_NAME / f"{month}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_a_run_is_one_line_with_its_trigger_steps_effects_and_outcome(tmp_path):
    journal, clock = _journal(tmp_path)
    run = journal.start("vault_check", "manual")
    with run.step("fetch"):
        clock.tick(1.5)
    with run.step("compare"):
        clock.tick(0.25)
    run.effect("git", repo="personal", before="1a2b3c4", after="5d6e7f8", behind=46, ahead=0)
    assert run.finish("ok") is True
    row, = _lines(tmp_path, "2026-11")
    assert row["job"] == "vault_check" and row["trigger"] == "manual" and row["result"] == "ok"
    assert row["at"] == "2026-11-22 15:09:03" and row["seconds"] == 1.75, "记的是开始的时间和总共用了多久"
    assert row["steps"] == [{"name": "fetch", "seconds": 1.5}, {"name": "compare", "seconds": 0.25}]
    assert row["effects"] == [{"kind": "git", "repo": "personal", "before": "1a2b3c4", "after": "5d6e7f8", "behind": 46, "ahead": 0}]
    assert row["id"].startswith("20261122T150903-") and "error" not in row


def test_a_step_that_blows_up_is_still_timed_and_the_error_keeps_only_its_tail(tmp_path):
    journal, clock = _journal(tmp_path)
    run = journal.start("vault_sync", "schedule")
    with pytest.raises(RuntimeError):
        with run.step("push"):
            clock.tick(2)
            raise RuntimeError("boom")
    run.finish("failed", "x" * 500 + "fatal: unable to access")
    row, = _lines(tmp_path, "2026-11")
    assert row["steps"] == [{"name": "push", "seconds": 2.0}] and row["result"] == "failed"
    assert len(row["error"]) == rj.ERROR_LIMIT and row["error"].endswith("fatal: unable to access")


def test_finishing_twice_writes_once(tmp_path):
    journal, _ = _journal(tmp_path)
    run = journal.start("vault_check", "manual")
    assert run.finish("noop") is True and run.finish("failed", "late") is False
    assert [row["result"] for row in _lines(tmp_path, "2026-11")] == ["noop"]


def test_reading_gives_the_newest_first_across_months_and_can_ask_for_one_job(tmp_path):
    journal, clock = _journal(tmp_path, _Clock(dt.datetime(2026, 10, 31, 23, 59, 0)))
    journal.start("vault_sync", "schedule").finish("noop")
    clock.tick(120)                                                       # 跨到 11 月
    journal.start("work_briefing", "schedule").finish("ok")
    clock.tick(60)
    journal.start("vault_sync", "idle").finish("ok")
    assert sorted(path.name for path in (tmp_path / rj.DIR_NAME).iterdir()) == ["2026-10.jsonl", "2026-11.jsonl"]
    assert [(row["job"], row["trigger"]) for row in journal.read()] == [
        ("vault_sync", "idle"), ("work_briefing", "schedule"), ("vault_sync", "schedule")]
    assert [row["trigger"] for row in journal.read(job="vault_sync")] == ["idle", "schedule"]
    assert [row["job"] for row in journal.read(limit=2)] == ["vault_sync", "work_briefing"]


def test_reading_skips_lines_it_cannot_parse(tmp_path):
    journal, _ = _journal(tmp_path)
    journal.start("vault_check", "manual").finish("ok")
    path = tmp_path / rj.DIR_NAME / "2026-11.jsonl"
    with open(path, "a", encoding="utf-8") as handle:
        handle.write('{"job": "half written\n[1, 2]\n')
    assert [row["job"] for row in journal.read()] == ["vault_check"]
    assert rj.Journal(tmp_path / "nowhere").read() == []


def test_whole_months_older_than_the_keep_window_are_dropped_on_the_next_write(tmp_path):
    folder = tmp_path / rj.DIR_NAME
    folder.mkdir()
    for name in ("2026-07.jsonl", "2026-08.jsonl", "2026-09.jsonl", "notes.txt", "2026-07.jsonl.bak"):
        (folder / name).write_text("{}\n", encoding="utf-8")
    journal, _ = _journal(tmp_path)                                         # 今天 11-22，留 90 天 → 8-24 之后的
    journal.start("vault_check", "manual").finish("ok")
    assert sorted(path.name for path in folder.iterdir()) == [
        "2026-07.jsonl.bak", "2026-08.jsonl", "2026-09.jsonl", "2026-11.jsonl", "notes.txt"], \
        "7 月整月都在窗口外：删；8 月还有几天在窗口里：留；不是运行记录的文件不碰"


@pytest.mark.parametrize(("job", "trigger"), [("vault_check", "cron"), ("Vault Check", "manual"), ("", "manual")])
def test_a_job_or_trigger_nobody_declared_is_a_programming_error(tmp_path, job, trigger):
    journal, _ = _journal(tmp_path)
    with pytest.raises(ValueError):
        journal.start(job, trigger)


def test_an_undeclared_result_is_a_programming_error_and_writes_nothing(tmp_path):
    journal, _ = _journal(tmp_path)
    run = journal.start("vault_check", "manual")
    with pytest.raises(ValueError):
        run.finish("great")
    assert not (tmp_path / rj.DIR_NAME).exists()


def test_a_journal_that_cannot_be_written_says_so_without_raising(tmp_path):
    (tmp_path / rj.DIR_NAME).write_text("a file where the folder should be", encoding="utf-8")
    journal, _ = _journal(tmp_path)
    assert journal.start("vault_check", "manual").finish("ok") is False, "要记的那件事已经做完了：记不上不能让它变成失败"


def test_runs_finishing_on_several_threads_each_keep_their_own_whole_line(tmp_path):
    journal = rj.Journal(tmp_path / rj.DIR_NAME)
    ready = threading.Barrier(8)

    def work(index: int) -> None:
        ready.wait(10)
        for step in range(25):
            run = journal.start("vault_sync", "schedule")
            run.effect("git", repo="personal", note=f"{index}-{step}" * 20)
            run.finish("ok")

    threads = [threading.Thread(target=work, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    rows = journal.read()
    assert len(rows) == 200 and len({row["id"] for row in rows}) == 200


def test_module_uses_only_the_standard_library():
    """纯逻辑：不碰 Qt，将来同步器、各个定时服务、页面都从后台线程调它。"""
    tree = ast.parse(Path(rj.__file__).read_text(encoding="utf-8"))
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {(node.module or ".").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert imported <= {"__future__", "contextlib", "datetime", "json", "logging", "os", "re", "threading", "time", "uuid", "pathlib", "typing"}
