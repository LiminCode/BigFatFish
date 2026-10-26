# -*- coding: utf-8 -*-
"""通知中心（纯逻辑部分）：配置归一化、「发送人: 消息」拆分、合并、跳转的决策。

纪律：不碰 WinRT、不开通知中心、不起 Slack——系统侧的函数都用假的替掉。
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from pet import notification_center as nc


def _notice(uid: int, created: float = 100.0, *, app: str = "Slack", app_id: str = "91750D7E.Slack_x!Slack",
            title: str = "#general", body: str = "Ann: hello", in_center: bool = True) -> nc.Notice:
    return nc.Notice(uid=uid, app=app, app_id=app_id, title=title, body=body, created=created, in_center=in_center)


# ---------------------------------------------------------------- 配置

def test_normalize_fills_defaults_and_clamps():
    assert nc.normalize(None) == {"enabled": True, "poll_seconds": 3, "keep": 50, "apps": ["slack"],
                                  "toast": nc.TOAST_DEFAULTS, "stack": nc.STACK_DEFAULTS}
    assert nc.normalize("junk") == nc.normalize({})
    out = nc.normalize({"enabled": "false", "poll_seconds": 0, "keep": 10_000, "apps": " Slack ,Teams,, slack"})
    assert out == {"enabled": False, "poll_seconds": 2, "keep": 200, "apps": ["slack", "teams"],
                   "toast": nc.TOAST_DEFAULTS, "stack": nc.STACK_DEFAULTS}
    assert nc.normalize({"apps": []})["apps"] == ["slack"], "清空应用名就退回默认，别变成什么都认"
    assert nc.normalize({"poll_seconds": "abc", "enabled": 1})["poll_seconds"] == 3


def test_toast_settings_are_normalised_inside_notifications():
    assert nc.TOAST_DEFAULTS["enabled"] is False, "实验功能默认关：开了会和系统横幅各弹一遍"
    out = nc.normalize({"toast": {"enabled": "yes", "corner": "bottom_left", "screen": " DELL G3223Q ",
                                  "seconds": 99999, "max_visible": 0}})["toast"]
    assert out == {"enabled": True, "corner": "bottom_left", "screen": "DELL G3223Q",
                   "seconds": nc.TOAST_SECONDS_RANGE[1], "max_visible": nc.TOAST_MAX_RANGE[0]}
    assert nc.normalize({"toast": {"corner": "middle", "screen": ""}})["toast"] == nc.TOAST_DEFAULTS
    assert nc.normalize({"toast": "junk"})["toast"] == nc.TOAST_DEFAULTS


def test_toast_seconds_allow_zero_for_stay_until_dismissed():
    assert nc.TOAST_SECONDS_RANGE[0] == 0 and nc.TOAST_SECONDS_RANGE[1] >= 600
    assert nc.normalize_toast({"seconds": 0})["seconds"] == 0
    assert nc.normalize_toast({"seconds": -5})["seconds"] == 0


_SLACK_C123 = nc.Notice(uid=1, app="Slack", app_id="91750D7E.Slack_x!Slack", title="#general", body="Ann: hi",
                        created=1, launch="slack://channel?id=C123&message=1.2&team=T9&origin=x",
                        activation="protocol")
_CHROME_GMAIL = nc.Notice(uid=5, app="Google Chrome", app_id="Chrome", title="New mail", body="hi\nmail.google.com",
                          created=1, launch="0|0|Default|0|https://mail.google.com/|p#https://mail.google.com#1",
                          activation="foreground")
_CHROME_BARE = nc.Notice(uid=6, app="Google Chrome", app_id="Chrome", title="x", body="y", created=1)


@pytest.mark.parametrize("notice, key", [
    (_SLACK_C123, "slack:T9:C123"),
    (nc.Notice(uid=2, app="Slack", app_id="91750D7E.Slack_x!Slack", title="#general", body="Bo: yo", created=1),
     "slack:#general"),
    (nc.Notice(uid=3, app="Slack", app_id="x", title="", body="", created=1), "slack"),
    (_CHROME_GMAIL, "chrome:mail.google.com"),
    (_CHROME_BARE, "chrome"),
    (nc.Notice(uid=4, app="Mail", app_id="Mail!App", title="Inbox", body="x", created=1), ""),
])
def test_source_key_by_default_groups_slack_by_channel_and_chrome_by_site(notice, key):
    assert nc.source_key(notice) == key


def test_stacking_choices_per_app():
    assert nc.STACK_DEFAULTS == {"slack": "channel", "chrome": "site"}
    assert nc.source_key(_SLACK_C123, {"slack": "app"}) == "slack", "整个 Slack 叠成一张"
    assert nc.source_key(_SLACK_C123, {"slack": "off"}) == "", "每条单独"
    assert nc.source_key(_CHROME_GMAIL, {"chrome": "app"}) == "chrome"
    assert nc.source_key(_CHROME_GMAIL, {"chrome": "off"}) == ""
    assert nc.normalize_stack({"slack": "weird", "chrome": "off"}) == {"slack": "channel", "chrome": "off"}
    assert nc.normalize_stack("junk") == nc.STACK_DEFAULTS
    assert set(nc.STACK_CHOICES) == {"slack", "chrome"}
    assert nc.STACK_CHOICES["slack"] == ("off", "channel", "app")
    assert nc.STACK_CHOICES["chrome"] == ("off", "site", "app")


def test_chrome_is_its_own_kind():
    assert _CHROME_GMAIL.kind == "chrome" and _SLACK_C123.kind == "slack"
    assert nc.Notice(uid=9, app="Mail", app_id="x", title="", body="", created=1).kind == "other"


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


# ---------------------------------------------------------------- launch（通知自己的启动参数）

_SLACK_TOAST = ('<toast launch="slack://channel?id=C1&amp;message=1.2&amp;team=T1" activationType="protocol">'
                '<visual><binding template="ToastGeneric"><text>#general</text></binding></visual></toast>')


def test_parse_launch_reads_the_toast_root_attributes():
    assert nc.parse_launch(_SLACK_TOAST) == ("protocol", "slack://channel?id=C1&message=1.2&team=T1")
    assert nc.parse_launch('<toast launch="action=open&amp;id=5"><visual/></toast>') == ("foreground", "action=open&id=5")
    assert nc.parse_launch(b"<toast/>") == ("foreground", "")
    assert nc.parse_launch("not xml") == ("", "")


@pytest.mark.parametrize("uri, ok", [
    ("slack://channel?id=C1&team=T1", True),
    ("msteams:/l/message/1", True),
    ("https://example.com/x", True),
    ("file:///C:/Windows/notepad.exe", False),
    (r"C:\Windows\notepad.exe", False),
    ("action=open&id=5", False),
    ("", False),
])
def test_only_real_uri_schemes_are_launched(uri, ok):
    assert nc.launchable_uri(uri) is ok


def _make_db(folder, rows):
    folder.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(folder / "wpndatabase.db")
    db.execute("CREATE TABLE Notification (Id INTEGER, Type TEXT, Payload BLOB)")
    db.executemany("INSERT INTO Notification VALUES (?, 'toast', ?)", rows)
    db.commit()
    db.close()


def test_launch_targets_reads_a_copy_of_the_database(tmp_path):
    source = tmp_path / "Notifications"
    _make_db(source, [(11, _SLACK_TOAST.encode("utf-8")), (12, b"<toast/>")])
    found = nc.launch_targets([11, 12, 13], source_dir=str(source))
    assert found == {11: ("protocol", "slack://channel?id=C1&message=1.2&team=T1"), 12: ("foreground", "")}
    assert nc.launch_targets([11], source_dir=str(tmp_path / "missing")) == {}
    assert nc.launch_targets([], source_dir=str(source)) == {}


def test_with_launch_fills_only_notices_that_lack_it():
    calls = []

    def lookup(uids):
        calls.append(sorted(uids))
        return {1: ("protocol", "slack://channel?id=C1")}

    ready = nc.replace(_notice(2), launch="slack://x", activation="protocol")
    out = nc.with_launch([_notice(1), ready, _notice(3)], lookup)
    assert calls == [[1, 3]], "已经有的不再查"
    assert (out[0].activation, out[0].launch) == ("protocol", "slack://channel?id=C1")
    assert out[1] is ready and out[2].launch == "" and out[2].activation == "none"
    assert nc.with_launch([ready], lookup) == [ready] and calls == [[1, 3]], "全都有就不碰数据库"


def test_activate_opens_a_protocol_launch_directly_even_when_gone_from_the_center():
    opened, invoked, removed = [], [], []
    notice = nc.replace(_notice(5, in_center=False), launch="slack://channel?id=C1&team=T1", activation="protocol")
    result = nc.activate(notice, team_id="T1", invoke=lambda n: invoked.append(n) or True, open_url=opened.append,
                         remove=removed.append)
    assert result == "launched"
    assert opened == ["slack://channel?id=C1&team=T1"] and invoked == [], "不开通知中心"
    assert removed == [], "已经不在通知中心里了"
    assert nc.activate(nc.replace(notice, in_center=True), team_id="T1", invoke=lambda n: True,
                       open_url=opened.append, remove=removed.append) == "launched"
    assert removed == [5], "像系统一样，点过的从通知中心拿掉"


def test_activate_without_a_usable_launch_keeps_the_old_path():
    opened = []
    foreground = nc.replace(_notice(5), launch="action=open", activation="foreground")
    assert nc.activate(foreground, team_id="T1", invoke=lambda n: True, open_url=opened.append) == "activated"
    unsafe = nc.replace(_notice(6), launch="file:///C:/x.exe", activation="protocol")
    assert nc.activate(unsafe, team_id="T1", invoke=lambda n: True, open_url=opened.append) == "activated"
    assert opened == []


def test_center_probe_uses_title_and_a_whitespace_normalised_body_prefix():
    title, probe = nc._center_probe(_notice(1, title=" #ops ", body="Ann:  first\n\nline " + "x" * 80))
    assert title == "#ops" and probe == "Ann: first line " + "x" * 14 and len(probe) == nc._BODY_PROBE_CHARS
