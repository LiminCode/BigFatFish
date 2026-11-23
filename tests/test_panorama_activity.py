# -*- coding: utf-8 -*-
"""时间轴页（``pet/panorama/activity.py``）：运行记录和仓库的提交按时间排成一条瀑布流，靠提交号对账。

纯函数直接喂数据测；读 git 的那一步用假的执行器；provider 从公开面测（给它运行记录和一个克隆目录，看它交出什么）。
"""
from __future__ import annotations

import datetime as dt

import pytest

from pet import i18n, run_journal
from pet.panorama import activity

NOW = dt.datetime(2026, 11, 22, 18, 0, 0)


@pytest.fixture(autouse=True)
def _chinese():
    i18n.set_language("zh")
    yield
    i18n.set_language("zh")


def _run(at: str, job: str = "vault_sync", result: str = "ok", trigger: str = "manual", **effect) -> dict:
    return {"id": at, "job": job, "trigger": trigger, "at": f"2026-11-22 {at}", "seconds": 1.5, "result": result,
            "steps": [{"name": "fetch", "seconds": 1.0}, {"name": "push", "seconds": 0.5}],
            "effects": [{"kind": "git", "op": "sync" if job == "vault_sync" else "fetch", "repo": "personal", **effect}]}


def _commit(sha: str, at: str, author: str = "Cloud", subject: str = "a note", files: int = 1) -> dict:
    return {"id": sha, "at": f"2026-11-22 {at}", "author": author, "subject": subject, "files": files}


# ───────────────────────── 对账与合并 ─────────────────────────

def test_commits_a_run_pushed_sit_under_that_run_and_the_rest_stand_on_their_own():
    runs = [_run("14:02:00", pulled=1, pushed=1, pushed_ids=["aaaaaaaaaaaa"])]
    commits = [_commit("aaaaaaaaaaaa", "14:02:01", "Dev", "vault: 2026-11-22 14:02 · 2 files", 2), _commit("bbbbbbbbbbbb", "13:20:00")]
    rows = activity.timeline(runs, commits)
    assert [row["kind"] for row in rows] == ["run", "outside"]
    assert [c["id"] for c in rows[0]["commits"]] == ["aaaaaaaaaaaa"], "这次运行推上去的提交挂在它下面"
    assert rows[1]["author"] == "Cloud" and [c["id"] for c in rows[1]["commits"]] == ["bbbbbbbbbbbb"]
    assert rows[1]["at"] == "2026-11-22 13:20:00"


def test_outside_commits_next_to_each_other_by_one_author_fold_into_one_row():
    commits = [_commit("c3", "13:30:00"), _commit("c2", "13:20:00"), _commit("c1", "13:10:00"), _commit("d1", "12:00:00", "Someone else")]
    rows = activity.timeline([], commits)
    assert [(row["author"], len(row["commits"])) for row in rows] == [("Cloud", 3), ("Someone else", 1)]
    assert (rows[0]["at"], rows[0]["since"]) == ("2026-11-22 13:30:00", "2026-11-22 13:10:00")


def test_a_run_between_two_outside_commits_keeps_them_apart():
    rows = activity.timeline([_run("13:15:00", pulled=1)], [_commit("c2", "13:20:00"), _commit("c1", "13:10:00")])
    assert [row["kind"] for row in rows] == ["outside", "run", "outside"], "时间顺序比省地方要紧"


def test_runs_with_nothing_to_do_fold_into_one_quiet_row_per_job():
    runs = [_run("12:00:00", result="noop", trigger="schedule"), _run("11:00:00", result="noop", trigger="schedule"),
            _run("10:00:00", result="noop", trigger="schedule"), _run("09:30:00", job="vault_check", result="noop"),
            _run("09:00:00", pushed=1, pushed_ids=["a"])]
    rows = activity.timeline(runs, [])
    assert [(row["kind"], row.get("count")) for row in rows] == [("quiet", 3), ("quiet", 1), ("run", None)]
    assert (rows[0]["job"], rows[0]["at"], rows[0]["since"]) == ("vault_sync", "2026-11-22 12:00:00", "2026-11-22 10:00:00")


def test_folding_stops_at_midnight_so_a_row_always_belongs_to_one_day():
    """实机上见过「11-19 · 26 个提交」其实是四天的：一行挂在哪个日期小标题下面，就只说那一天的事。"""
    commits = [_commit("c3", "09:00:00"), {**_commit("c2", "23:00:00"), "at": "2026-11-21 23:00:00"}, {**_commit("c1", "22:00:00"), "at": "2026-11-21 22:00:00"}]
    rows = activity.timeline([], commits)
    assert [(row["at"][:10], len(row["commits"])) for row in rows] == [("2026-11-22", 1), ("2026-11-21", 2)]
    quiet = [_run("00:30:00", result="noop"), {**_run("23:30:00", result="noop"), "at": "2026-11-21 23:30:00"}]
    assert [(row["at"][:10], row["count"]) for row in activity.timeline(quiet, [])] == [("2026-11-22", 1), ("2026-11-21", 1)]


def test_a_run_that_needs_the_user_is_never_folded_away():
    runs = [_run("12:00:00", result="needs_you", conflicts=1), _run("11:00:00", result="needs_you", conflicts=1),
            _run("10:00:00", result="failed")]
    assert [row["kind"] for row in activity.timeline(runs, [])] == ["run", "run", "run"]


# ───────────────────────── 每个任务此刻的状态 ─────────────────────────

def test_each_job_gets_its_last_outcome_and_a_strip_of_its_recent_runs():
    runs = [_run("17:00:00", result="needs_you", conflicts=1), _run("16:00:00", result="noop"), _run("15:00:00", result="ok", pushed=1),
            _run("14:00:00", job="vault_check", result="ok"), *[_run(f"{hour:02d}:30:00", result="noop") for hour in range(13, 0, -1)]]
    jobs = activity.job_status(runs)
    assert [job["job"] for job in jobs] == ["vault_sync", "vault_check"], "最近跑过的排前面"
    sync = jobs[0]
    assert (sync["at"], sync["result"], sync["runs"]) == ("2026-11-22 17:00:00", "needs_you", 16)
    assert sync["strip"] == ["noop"] * (activity.STRIP - 3) + ["ok", "noop", "needs_you"], "最近的在右边，只留最后几次"


# ───────────────────────── 读 git ─────────────────────────

def test_commits_are_read_from_the_upstream_branch_in_one_local_call(tmp_path):
    calls = []
    out = ("\x1e1111111111112222\x1f2026-11-22 13:20:00\x1fCloud\x1fAdd <b>note</b>\n\n 2 files changed, 3 insertions(+)\n"
           "\x1e3333333333334444\x1f2026-11-22 12:00:00\x1fDev\x1fvault: 2026-11-22 12:00 · 1 files\n\n 1 file changed, 1 deletion(-)\n"
           "\x1e5555555555556666\x1f2026-11-21 09:00:00\x1fDev\x1fempty commit\n")

    def git(folder, args, **options):
        calls.append(args)
        return 0, out

    commits = activity.read_commits(tmp_path, run=git)
    assert commits == [{"id": "111111111111", "at": "2026-11-22 13:20:00", "author": "Cloud", "subject": "Add <b>note</b>", "files": 2},
                       {"id": "333333333333", "at": "2026-11-22 12:00:00", "author": "Dev", "subject": "vault: 2026-11-22 12:00 · 1 files", "files": 1},
                       {"id": "555555555555", "at": "2026-11-21 09:00:00", "author": "Dev", "subject": "empty commit", "files": 0}]
    (args,) = calls
    assert args[:2] == ["log", "@{upstream}"] and "--shortstat" in args and f"-n{activity.COMMITS}" in args
    assert not any(word in args for word in ("fetch", "pull")), "不联网：远端的提交只和上次核对时一样新"
    assert activity.read_commits(tmp_path, run=lambda *a, **k: (128, "fatal: not a git repository")) == []


# ───────────────────────── 页面内容 ─────────────────────────

def test_everything_that_came_from_outside_is_escaped_in_the_page():
    runs = [_run("14:02:00", result="failed", pushed_ids=["aaaaaaaaaaaa"])]
    runs[0]["error"] = "fatal: <script>alert(1)</script>"
    commits = [_commit("aaaaaaaaaaaa", "14:02:01", "Dev", "note <img src=x onerror=1>"), _commit("bbbbbbbbbbbb", "13:20:00", "<i>Cloud</i>", "x & y")]
    html = activity.render(activity.timeline(runs, commits), activity.job_status(runs))
    assert "<script>" not in html and "<img" not in html and "<i>Cloud" not in html
    assert "&lt;script&gt;" in html and "x &amp; y" in html and "&lt;i&gt;Cloud&lt;/i&gt;" in html and "&lt;img" in html


def test_the_page_says_what_each_row_did_in_plain_words():
    runs = [_run("17:00:00", result="needs_you", conflicts=1, files=2, committed=["x"]),
            _run("15:00:00", result="ok", pulled=46, pushed=1, files=2, pushed_ids=["aaaaaaaaaaaa"]),
            _run("14:00:00", job="vault_check", result="ok", behind=46, ahead=0),
            _run("13:00:00", result="noop", trigger="schedule"), _run("12:00:00", result="noop", trigger="schedule")]
    commits = [_commit("aaaaaaaaaaaa", "15:00:01", "Dev", "vault: 2026-11-22 15:00 · 2 files", 2), _commit("c1", "13:30:00"), _commit("c0", "13:20:00")]
    html = activity.render(activity.timeline(runs, commits), activity.job_status(runs))
    assert "有冲突（1 个文件），已撤回" in html and "拉 46 · 推 1" in html and "落后 46 · 领先 0" in html
    assert "2 次，没有变化" in html and "Cloud" in html and "2 个提交" in html
    assert "你点的" in html and "定时" in html and "知识库同步" in html and "知识库核对" in html
    assert html.count("<details") >= 3, "能展开的行：有步骤或提交可看的运行、外部的提交"
    flow = html.split('class="wday"', 1)[1]                             # 任务状态那一段在上面，不算
    assert flow.index(">17:00<") < flow.index(">15:00<") < flow.index(">14:00<") < flow.index(">13:30<"), "新的在上"
    assert "2026-11-22" in html, "按天分组的小标题"


def test_an_empty_timeline_renders_nothing():
    assert activity.render([], []) == ""


# ───────────────────────── provider ─────────────────────────

def test_the_provider_reads_the_journal_and_git_off_the_gui_thread_and_hands_over_a_report(tmp_path):
    journal = run_journal.Journal(tmp_path / "journal", now=lambda: NOW)
    run = journal.start("vault_sync", "manual")
    run.effect("git", op="sync", repo="personal", pulled=0, pushed=1, pushed_ids=["aaaaaaaaaaaa"], files=1)
    run.finish("ok")
    log = []

    def on_gui(work):
        log.append("gui")
        return work()

    def git(folder, args, **options):
        log.append(args[0])
        if args[0] == "log":
            return 0, "\x1eaaaaaaaaaaaabbbb\x1f2026-11-22 18:00:01\x1fDev\x1fvault: now\n\n 1 file changed\n\x1ecccccccccccc0000\x1f2026-11-22 09:00:00\x1fCloud\x1fa note\n"
        return 0, "main\n"

    (tmp_path / ".git").mkdir()
    build = activity.provider(journal, lambda: {"repo_dir": str(tmp_path), "theme": "light"}, on_gui, run=git)
    assert build.off_gui is True, "它要起 git：不许在界面线程上做"
    data = build()
    assert data["id"] == activity.REPORT and data["title"] == "时间轴" and data["theme"] == "light" and data["available"] is True
    assert "知识库同步" in data["html"] and "Cloud" in data["html"] and data["sections"] == [] and data["action"] is None
    assert "1 次运行" in data["summary"] and "1 个提交不是这里推的" in data["summary"]
    assert log[0] == "gui" and "log" in log and log.count("gui") == 1, "只回一次界面线程（读克隆目录和主题）"


def test_the_provider_survives_a_folder_that_is_not_a_clone(tmp_path):
    journal = run_journal.Journal(tmp_path / "journal")
    build = activity.provider(journal, lambda: {"repo_dir": str(tmp_path / "nowhere"), "theme": "dark"}, lambda work: work(),
                              run=lambda *a, **k: (128, "fatal"))
    data = build()
    assert data["html"] == "" and data["empty_text"] and data["error"] == ""


@pytest.mark.parametrize("language", ["zh", "en"])
def test_every_trigger_result_and_known_job_has_a_name_in_both_languages(language):
    from pet import vault_sync
    from pet.panorama import actions

    table = i18n.table(language)
    wanted = [f"activity.trigger.{name}" for name in run_journal.TRIGGERS] + [f"activity.result.{name}" for name in run_journal.RESULTS]
    wanted += [f"activity.job.{name}" for name in (vault_sync.JOB, actions.CHECK_JOB)]
    assert [key for key in wanted if not str(table.get(key) or "").strip()] == []
