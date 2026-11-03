# -*- coding: utf-8 -*-
"""会话小鱼的「关闭」决定：落盘、跨重启、再活跃就作废、会话没了就忘。"""
from __future__ import annotations

import json

from pet.session_fish_decisions import DECISIONS_FILE, SessionFishDecisions

A, B = ("claude", "aaaaaaaa-1111"), ("claude_wsl", "bbbbbbbb-2222")


def test_dismiss_survives_a_reload_and_keeps_only_metadata(tmp_path):
    path = tmp_path / DECISIONS_FILE
    store = SessionFishDecisions(path, clock=lambda: 1000.0)
    assert store.dismiss(A, title="我的项目") and not store.dismiss(A), "重复关不算变化"
    assert store.is_dismissed(A) and not store.is_dismissed(B)

    again = SessionFishDecisions(path)
    again.load()
    assert again.is_dismissed(A) and again.dismissed() == [A]
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["dismissed"] == [{"agent": "claude", "session_id": "aaaaaaaa-1111", "at": 1000.0, "title": "我的项目"}]


def test_revive_clears_the_decision_and_prune_forgets_sessions_that_are_gone(tmp_path):
    store = SessionFishDecisions(tmp_path / DECISIONS_FILE)
    store.dismiss(A)
    store.dismiss(B)
    assert store.revive(A) and not store.revive(A)
    assert not store.is_dismissed(A) and store.is_dismissed(B)
    assert store.prune(keep=[A]) == 1, "B 不在名册里了：忘掉"
    assert len(store) == 0
    reloaded = SessionFishDecisions(tmp_path / DECISIONS_FILE)
    reloaded.load()
    assert len(reloaded) == 0


def test_bad_file_and_bad_keys_are_ignored(tmp_path):
    path = tmp_path / DECISIONS_FILE
    path.write_text("not json", encoding="utf-8")
    store = SessionFishDecisions(path)
    store.load()
    assert len(store) == 0
    assert not store.dismiss(("claude", "")) and not store.dismiss(None) and not store.is_dismissed(("", ""))
    path.write_text(json.dumps({"dismissed": [{"agent": "claude"}, 7, {"agent": "claude", "session_id": "x", "at": "?"}]}),
                    encoding="utf-8")
    store.load()
    assert store.dismissed() == [("claude", "x")]


def test_without_a_path_it_only_lives_in_memory():
    store = SessionFishDecisions(None)
    assert store.dismiss(A) and store.is_dismissed(A) and store.save() is False
