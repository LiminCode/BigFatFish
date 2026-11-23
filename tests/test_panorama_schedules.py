# -*- coding: utf-8 -*-
"""定时功能在配置全景上的样子：功能表里登记了任务名的每一项，磁贴上都有运行历史、「上次运行」，该判断的判断迟没迟。

探针读真的运行记录文件；来源是纯函数，直接喂事实。
"""
from __future__ import annotations

import datetime as dt

import pytest

from pet import i18n, run_journal, run_recording, vault_sync
from pet.panorama import activity, features, probes, sources
from tests import panorama_samples as samples

DAY = 86400


@pytest.fixture(autouse=True)
def _chinese():
    i18n.set_language("zh")
    yield
    i18n.set_language("zh")


def _node(graph: dict, node_id: str) -> dict:
    return next(n for n in graph["nodes"] if n["id"] == node_id)


# ───────────────────────── 功能表 ─────────────────────────

def test_the_feature_table_says_which_jobs_belong_to_which_tile_and_how_lateness_is_judged():
    by_id = {feature.id: feature for feature in features.FEATURES}
    assert by_id["briefing"].jobs == (run_recording.WORK_BRIEFING,) and by_id["briefing"].late == "daily"
    assert by_id["assistant"].jobs == (run_recording.PERSONAL_BRIEFING,) and by_id["assistant"].late == "daily"
    assert by_id["slack"].jobs == (run_recording.SLACK_WATCH,) and by_id["slack"].late == "", "只在人在的时候跑：没法按钟点说它迟"
    assert by_id["vault_sync"].jobs == (vault_sync.JOB, vault_sync.CHECK_JOB) and by_id["vault_sync"].late == "interval"
    assert all(feature.late in ("", *features.LATE_RULES) for feature in features.FEATURES)
    jobs = [job for feature in features.FEATURES for job in feature.jobs]
    assert len(jobs) == len(set(jobs)), "一个任务只归一块磁贴"


@pytest.mark.parametrize("language", ["zh", "en"])
def test_every_registered_job_has_a_name_on_the_timeline(language):
    table = i18n.table(language)
    missing = [job for feature in features.FEATURES for job in feature.jobs if not str(table.get(f"activity.job.{job}") or "").strip()]
    assert missing == []


# ───────────────────────── 探针 ─────────────────────────

def test_the_probe_reads_the_journal_once_and_hands_each_feature_its_own_runs(tmp_path):
    clock = [dt.datetime(2026, 11, 22, 8, 30, 0)]
    journal = run_journal.Journal(tmp_path / run_journal.DIR_NAME, now=lambda: clock[0])
    for hour, job, result in ((8, "personal_briefing", "ok"), (9, "work_briefing", "failed"), (10, "slack_watch", "noop"),
                              (11, "slack_watch", "ok"), (12, "vault_sync", "ok"), (13, "vault_check", "noop")):
        clock[0] = dt.datetime(2026, 11, 22, hour, 0, 0)
        journal.start(job, "schedule").finish(result)
    now = dt.datetime(2026, 11, 22, 14, 0, 0).timestamp()
    info = probes.schedules(tmp_path, now=now)
    assert set(info) == {feature.id for feature in features.FEATURES if feature.jobs}
    assert [(run["job"], run["result"]) for run in info["slack"]["runs"]] == [("slack_watch", "ok"), ("slack_watch", "noop")]
    assert info["briefing"]["last_age_s"] == 5 * 3600 and info["assistant"]["runs"][0]["result"] == "ok"
    assert [run["job"] for run in info["vault_sync"]["runs"]] == ["vault_check", "vault_sync"], "核对和同步归同一块磁贴"
    assert probes.schedules(tmp_path / "nowhere")["briefing"] == {"runs": [], "last_age_s": None}
    schedule = probes.vault_schedule({}, tmp_path, now=now)
    assert schedule["runs"] == info["vault_sync"]["runs"] and schedule["settings"]["enabled"] is False


def test_a_busy_job_does_not_crowd_the_others_out_of_their_history(tmp_path):
    """Slack 关注一天上百条：往回看得够远，每天一次的简报才不会从历史里消失。"""
    clock = [dt.datetime(2026, 11, 21, 9, 0, 0)]
    journal = run_journal.Journal(tmp_path / run_journal.DIR_NAME, now=lambda: clock[0])
    journal.start("work_briefing", "schedule").finish("ok")
    for minute in range(300):
        clock[0] = dt.datetime(2026, 11, 21, 9, 0, 0) + dt.timedelta(minutes=10 * (minute + 1))
        journal.start("slack_watch", "schedule").finish("noop")
    info = probes.schedules(tmp_path)
    assert len(info["slack"]["runs"]) == probes.SCHEDULE_RUNS and len(info["briefing"]["runs"]) == 1


# ───────────────────────── 磁贴 ─────────────────────────

def _run(at: str, job: str, result: str, **effect) -> dict:
    return {"at": at, "job": job, "trigger": "schedule", "result": result, "effects": [effect] if effect else []}


def _graph(feature: str, *, enabled=True, age=3600, runs=None, every_minutes=0, when="09:00") -> dict:
    facts = samples.facts()
    facts["features"][feature].update(enabled=enabled, every_minutes=every_minutes, when=when)
    default = [_run("2026-11-22 09:00:00", "work_briefing", "ok", kind="model", model="claude-opus-5-5", tokens_in=41000, tokens_out=2300),
               _run("2026-11-21 09:00:00", "work_briefing", "failed")]
    facts["schedules"] = {feature: {"runs": default if runs is None else runs, "last_age_s": age}}
    return sources.build(facts)


def test_a_daily_feature_shows_its_last_run_and_a_strip_and_keeps_its_own_sub_line():
    plain = samples.facts()
    plain["features"]["briefing"].update(enabled=True, every_minutes=0, when="09:00")
    before = _node(sources.build(plain), "f_briefing")                     # 同样的设置，只是没有运行历史
    tile = _node(_graph("briefing"), "f_briefing")
    assert tile["size"] == "tall" and tile["lines"] == ["上次 09:00"] and tile["state"] == "ok"
    assert tile["sub"] == before["sub"] and "09:00" in tile["sub"], "模型 · effort · 时间那一行不动"
    assert [(item["name"], item["state"]) for item in tile["items"]] == [("11-22 09:00", "ok"), ("11-21 09:00", "bad")]
    assert tile["items"][0]["detail"] == "定时 · 生成完成 · claude-opus-5-5 · 43300 tokens"
    assert any(label == "上次运行" and value.startswith("2026-11-22 09:00 · 生成完成") for label, value in tile["facts"])


def test_a_daily_feature_is_late_only_after_four_days_so_a_weekend_is_not_an_alarm():
    assert _node(_graph("briefing", age=3 * DAY + 3600), "f_briefing")["state"] == "ok", "周五到周一：正常"
    graph = _graph("briefing", age=4 * DAY + 1)
    tile = _node(graph, "f_briefing")
    assert tile["state"] == "warn" and tile["lines"] == ["迟了"]
    quest, = [q for q in graph["quests"] if q["node"] == "f_briefing"]
    assert quest["sev"] == "warn" and "工作简报迟了" in quest["text"] and "2026-11-22 09:00" in quest["text"]
    assert next(e for e in graph["edges"] if e["from"] == "f_briefing")["line"], "线还在"


def test_slack_watch_is_never_called_late_because_it_only_runs_while_someone_is_there():
    runs = [_run("2026-11-13 17:50:00", "slack_watch", "ok", kind="found", items=3, new=2), _run("2026-11-13 17:40:00", "slack_watch", "noop")]
    graph = _graph("slack", age=9 * DAY, runs=runs, every_minutes=10, when="")
    tile = _node(graph, "f_slack")
    assert tile["state"] == "ok" and tile["lines"] == ["上次 17:50"] and not any(q["node"] == "f_slack" and q["sev"] == "warn" for q in graph["quests"])
    assert tile["items"][0]["detail"] == "定时 · 新的 2 条" and tile["items"][1]["detail"] == "定时 · 没有变化"


def test_a_feature_that_is_switched_off_keeps_its_shape_and_only_gains_the_history():
    off = _node(_graph("briefing", enabled=False, age=30 * DAY), "f_briefing")
    assert off["state"] == "off" and off["size"] == "row" and "lines" not in off and len(off["items"]) == 2


def test_a_feature_that_has_not_run_since_the_journal_began_says_so():
    tile = _node(_graph("assistant", runs=[], age=None, when="08:30"), "f_assistant")
    assert tile["lines"] == ["还没跑过"] and tile["state"] == "ok" and ["上次运行", "还没跑过"] in tile["facts"]


def test_features_without_a_registered_job_are_left_exactly_as_they_were():
    plain, decorated = sources.build(samples.facts()), _graph("briefing")
    assert _node(plain, "f_notes") == _node(decorated, "f_notes") and _node(plain, "f_chat") == _node(decorated, "f_chat")


# ───────────────────────── 时间轴上怎么说 ─────────────────────────

def test_the_timeline_describes_model_runs_and_look_ups_in_their_own_words():
    assert activity.describe(_run("x", "work_briefing", "ok", kind="model", model="claude-opus-5-5", tokens_in=10, tokens_out=5)) == \
        "生成完成 · claude-opus-5-5 · 15 tokens"
    assert activity.describe(_run("x", "slack_watch", "ok", kind="found", items=3, new=1)) == "新的 1 条"
    assert activity.describe(_run("x", "slack_watch", "noop", kind="found", items=3, new=0)) == "没有变化"
    assert activity.describe(_run("x", "work_briefing", "failed", kind="model", model="")) == "没办成"
    rows = activity.timeline([_run("2026-11-22 09:00:00", "work_briefing", "ok", kind="model", model="m", tokens_in=1, tokens_out=1)], [])
    assert "工作简报" in activity.render(rows, activity.job_status([rows[0]["run"]]))
