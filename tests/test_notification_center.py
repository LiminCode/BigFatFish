# -*- coding: utf-8 -*-
"""通知中心（纯逻辑部分）：配置归一化、「发送人: 消息」拆分、合并、跳转的决策。

纪律：不碰 WinRT、不开通知中心、不起 Slack——系统侧的函数都用假的替掉。
"""
from __future__ import annotations

import json

import pytest

from pet import notification_center as nc


def _notice(uid: int, created: float = 100.0, *, app: str = "Slack", app_id: str = "91750D7E.Slack_x!Slack",
            title: str = "#general", body: str = "Ann: hello", in_center: bool = True) -> nc.Notice:
    return nc.Notice(uid=uid, app=app, app_id=app_id, title=title, body=body, created=created, in_center=in_center)


# ---------------------------------------------------------------- 配置

def test_normalize_fills_defaults_and_clamps():
    assert nc.normalize(None) == {"enabled": True, "poll_seconds": 3, "keep": 50, "apps": ["slack"]}
    assert nc.normalize("junk") == nc.normalize({})
    out = nc.normalize({"enabled": "false", "poll_seconds": 0, "keep": 10_000, "apps": " Slack ,Teams,, slack"})
    assert out == {"enabled": False, "poll_seconds": 2, "keep": 200, "apps": ["slack", "teams"]}
    assert nc.normalize({"apps": []})["apps"] == ["slack"], "清空应用名就退回默认，别变成什么都认"
    assert nc.normalize({"poll_seconds": "abc", "enabled": 1})["poll_seconds"] == 3


def test_matches_app_looks_at_name_and_aumid_case_insensitively():
    assert nc.matches_app("Slack", "91750D7E.Slack_8she8kybcnzg4!Slack", ("slack",))
    assert nc.matches_app("", "com.squirrel.slack.slack", ("slack",))
    assert not nc.matches_app("Microsoft Teams", "MSTeams_8wekyb3d8bbwe!MSTeams", ("slack",))
    assert not nc.matches_app("Slack", "x", ("",)), "空片段不算匹配"


def test_star_fragment_matches_every_app():
    assert nc.matches_app("Windows PowerShell", "{1AC14E77}\\powershell.exe", ("*",))
    assert nc.matches_app("", "", ("slack", "*"))
    assert nc.normalize({"apps": ["*", "slack"]})["apps"] == ["*", "slack"]


# ---------------------------------------------------------------- 数据

def test_split_body_separates_sender_from_message():
    assert nc.split_body("Ann Lee: hello there") == ("Ann Lee", "hello there")
    assert nc.split_body("ops-bot: alert: disk 91%") == ("ops-bot", "alert: disk 91%")
    assert nc.split_body("[Grafana:9]  (firing) heap high") == ("", "[Grafana:9]  (firing) heap high"), "冒号后没空格不算发送人"
    assert nc.split_body("x" * 60 + ": y") == ("", "x" * 60 + ": y"), "太长的不像名字"
    assert nc.split_body("  \n ") == ("", "")
    notice = _notice(1, body="Ann: line one\nline two")
    assert (notice.sender, notice.message) == ("Ann", "line one\nline two")
    assert notice.kind == "slack" and _notice(2, app="Mail", app_id="x").kind == "other"


def test_merge_keeps_vanished_items_marked_and_reports_new_ones():
    known = [_notice(1, 10), _notice(2, 20)]
    fresh = [_notice(2, 20), _notice(3, 30)]
    merged, new = nc.merge(known, fresh, keep=50)
    assert [n.uid for n in merged] == [3, 2, 1], "新到旧"
    assert new == [3]
    assert merged[0].in_center and merged[1].in_center and not merged[2].in_center, "1 号已不在通知中心里：留下但标灰"
    again, new_again = nc.merge(merged, fresh, keep=50)
    assert again == merged and new_again == []


def test_merge_honours_hidden_and_keep():
    known = [_notice(i, i) for i in range(5)]
    merged, new = nc.merge(known, [_notice(9, 9), _notice(2, 2)], keep=3, hidden={9, 4})
    assert [n.uid for n in merged] == [3, 2, 1], "9 被用户移除过不再出现；4 也移除过；只留 3 条"
    assert new == []
    merged, new = nc.merge([], [_notice(7, 7, in_center=False)], keep=1)
    assert merged[0].in_center is True and new == [7], "这次读到的一定还在通知中心里"


# ---------------------------------------------------------------- 跳

def test_slack_team_id_reads_the_first_workspace(tmp_path):
    state = tmp_path / "root-state.json"
    state.write_text(json.dumps({"workspaces": {"T0123ABCD": {"id": "T0123ABCD", "name": "x", "domain": "x"}}}),
                     encoding="utf-8")
    assert nc.slack_team_id(files=[str(tmp_path / "missing.json"), str(state)]) == "T0123ABCD"
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    assert nc.slack_team_id(files=[str(tmp_path / "bad.json")]) == ""
    assert nc.fallback_url(_notice(1), "T0123ABCD") == "slack://open?team=T0123ABCD"
    assert nc.fallback_url(_notice(1), "") == "slack://open"
    assert nc.fallback_url(_notice(1, app="Mail", app_id="x"), "T1") == "", "不认识的应用没有退路"


@pytest.mark.parametrize("in_center, invoked, expected, urls", [
    (True, True, "activated", []),
    (True, False, "opened_app", ["slack://open?team=T1"]),
    (False, None, "opened_app", ["slack://open?team=T1"]),
])
def test_activate_prefers_the_notification_center_then_falls_back(in_center, invoked, expected, urls):
    calls, opened = [], []

    def invoke(notice):
        calls.append(notice.uid)
        return invoked

    result = nc.activate(_notice(5, in_center=in_center), team_id="T1", invoke=invoke, open_url=opened.append)
    assert result == expected
    assert calls == ([5] if in_center else []), "不在通知中心里就别去开它"
    assert opened == urls


def test_activate_reports_gone_or_failed():
    assert nc.activate(_notice(1, app="Mail", app_id="x", in_center=False), team_id="", invoke=lambda n: False,
                       open_url=lambda u: None) == "gone"

    def boom(url):
        raise OSError("no handler")

    assert nc.activate(_notice(1, in_center=False), team_id="T1", invoke=lambda n: False, open_url=boom) == "failed"

    def explode(notice):
        raise RuntimeError("UIA down")

    assert nc.activate(_notice(1), team_id="", invoke=explode, open_url=lambda u: None) == "opened_app", "UIA 炸了也走退路"


def test_center_probe_uses_title_and_a_whitespace_normalised_body_prefix():
    title, probe = nc._center_probe(_notice(1, title=" #ops ", body="Ann:  first\n\nline " + "x" * 80))
    assert title == "#ops" and probe == "Ann: first line " + "x" * 14 and len(probe) == nc._BODY_PROBE_CHARS
