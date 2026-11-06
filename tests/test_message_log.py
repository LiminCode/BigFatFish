# -*- coding: utf-8 -*-
"""消息记录（``pet/message_log.py``）的纯逻辑：记、去重、新旧、落盘、移除、清空、补标题。"""
from __future__ import annotations

import json

from pet.message_log import DEDUP_S, LOG_FILE, Message, MessageLog


def _log(tmp_path, **kwargs):
    clock = [1_000_000.0]
    log = MessageLog(tmp_path / LOG_FILE, clock=lambda: clock[0], **kwargs)
    return log, clock


def test_records_newest_first_with_stable_uids_and_session_fields(tmp_path):
    log, clock = _log(tmp_path)
    first = log.record("Claude Code 干完活啦", agent="claude", session_id="abc", title="修登录循环", host="vscode",
                       where="VS Code", path="C:/repo")
    clock[0] += 5
    second = log.record("Slack · 3 条需要你看", subtitle="有急的", kind="alert")
    assert [m.uid for m in log.messages()] == [2, 1]
    assert first.key == ("claude", "abc") and second.key is None, "大肥鱼自己的消息没有会话键"
    assert first.title == "修登录循环" and first.host == "vscode" and first.where == "VS Code" and first.path == "C:/repo"
    assert second.kind == "alert" and second.subtitle == "有急的"
    assert log.record("   ", agent="claude", session_id="abc") is None, "空文案不记"
    assert log.record("半个键", agent="claude") .key is None, "只有通道没有会话 id：不算会话消息"


def test_same_text_within_the_window_is_recorded_once(tmp_path):
    log, clock = _log(tmp_path)
    assert log.record("需要你批准", agent="claude", session_id="a") is not None
    assert log.record("需要你批准", agent="claude", session_id="a") is None, "审批气泡重新挂上 / 隐藏期改道：同一条"
    assert log.record("需要你批准", agent="claude", session_id="b") is not None, "另一个会话的同一句话是另一条"
    assert log.record("需要你批准") is not None, "大肥鱼自己的同一句话也是另一条"
    clock[0] += DEDUP_S + 1
    assert log.record("需要你批准", agent="claude", session_id="a") is not None, "过了去重窗口再来就是新的一条"
    assert len(log) == 4


def test_unread_follows_the_seen_mark_and_survives_a_reload(tmp_path):
    log, clock = _log(tmp_path)
    log.record("一")
    log.record("二")
    assert log.unread_count == 2 and all(log.is_unread(m) for m in log.messages())
    assert log.mark_all_seen() is True and log.unread_count == 0
    assert log.mark_all_seen() is False, "没有新的就没变化"
    clock[0] += 1
    third = log.record("三")
    assert log.unread_count == 1 and log.is_unread(third)
    log.ui_open = False
    log.save()
    again = MessageLog(tmp_path / LOG_FILE)
    assert [m.text for m in again.messages()] == ["三", "二", "一"]
    assert again.unread_count == 1 and again.is_unread(again.messages()[0]), "看过没看过跨重启记得"
    assert again.ui_open is False
    fourth = again.record("四")
    assert fourth.uid == 4, "编号接着往下走，不和旧的撞"


def test_keep_limit_remove_clear_and_listeners(tmp_path):
    log, _clock = _log(tmp_path, keep=10)
    events = []
    log.listeners.append(lambda: events.append(len(log)))
    for i in range(12):
        log.record(f"消息 {i}")
    assert len(log) == 10 and log.messages()[-1].text == "消息 2", "只留最近 keep 条"
    assert log.remove(log.messages()[0].uid) is True and len(log) == 9
    assert log.remove(999) is False
    assert log.clear() is True and len(log) == 0 and log.unread_count == 0
    assert log.clear() is False
    assert events[-2:] == [9, 0] and len(events) == 14, "每次变化通知一次听众（12 记 + 1 移 + 1 清）"
    assert MessageLog(tmp_path / LOG_FILE).messages() == []


def test_retitle_fills_only_blank_fields_of_that_session(tmp_path):
    log, _clock = _log(tmp_path)
    log.record("开始干活啦", agent="claude", session_id="abc", title="Claude Code")
    log.record("干完活啦", agent="claude", session_id="abc")
    log.record("别的会话", agent="claude", session_id="zzz")
    assert log.retitle(("claude", "abc"), title="修登录循环", host="terminal", path="C:/repo") is True
    by_text = {m.text: m for m in log.messages()}
    assert by_text["干完活啦"].title == "修登录循环" and by_text["干完活啦"].host == "terminal"
    assert by_text["开始干活啦"].title == "Claude Code", "已经有标题的不覆盖"
    assert by_text["开始干活啦"].path == "C:/repo"
    assert by_text["别的会话"].title == ""
    assert log.retitle(("claude", "abc"), title="再改") is False, "没有空字段可填就没变化"


def test_bad_file_and_bad_entries_are_ignored(tmp_path):
    path = tmp_path / LOG_FILE
    path.write_text("not json", encoding="utf-8")
    assert MessageLog(path).messages() == []
    path.write_text(json.dumps({"version": 1, "next_uid": "x", "seen_uid": 99,
                                "messages": [{"uid": 5, "at": 1.0, "text": "好的"}, {"uid": 5, "at": 1.0, "text": "重复"},
                                             {"uid": "bad"}, {"uid": 2, "at": 2.0, "text": ""}, "junk"]}),
                    encoding="utf-8")
    log = MessageLog(path)
    assert [m.uid for m in log.messages()] == [5], "坏条目、重复编号、空文案都丢掉"
    assert log.unread_count == 0, "seen 超过最大编号就夹回去"
    assert log.record("新的").uid == 6
    assert Message.from_json({"uid": 1, "at": 0.0, "text": "x", "kind": "weird"}).kind == "bubble"


def test_without_a_path_it_only_lives_in_memory():
    log = MessageLog(None)
    assert log.record("hi") is not None and len(log) == 1
    log.save()
