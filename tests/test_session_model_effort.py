# -*- coding: utf-8 -*-
"""会话小鱼的详情卡显示这个会话在用的模型与 effort。

来源（2026-10-14 实测 Claude Code 2.1.296）：会话记录里每条 ``assistant`` 记录带
``message.model``（实际用的模型）、``requestedModel``、``effort``（会话级）与 ``perTurnEffort``
（这一轮实际的）。子代理的记录 ``isSidechain`` 为 true，不算主对话。

纪律：不读真实的 ~/.claude。
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from pet import claude_session_info as si
from pet.session_pet_ui import status_line
from tests.test_session_pet_details import SID, _pump, _session, shell  # noqa: F401 - shell 是 fixture

app = QApplication.instance() or QApplication([])


def _line(**entry) -> str:
    return json.dumps(entry, ensure_ascii=False, separators=(",", ":"))


def _assistant(model: str, *, effort="high", per_turn=None, sidechain=False, requested=None) -> str:
    entry = {"type": "assistant", "sessionId": SID, "isSidechain": sidechain, "effort": effort,
             "message": {"role": "assistant", "model": model, "content": []}}
    if per_turn is not None:
        entry["perTurnEffort"] = per_turn
    if requested is not None:
        entry["requestedModel"] = requested
    return _line(**entry)


def test_the_latest_main_conversation_turn_gives_the_model_and_effort():
    text = "\n".join([
        _line(type="user", message={"content": "hi"}, sessionId=SID, cwd="C:\\proj"),
        _assistant("claude-opus-5-5", effort="medium"),
        _assistant("claude-fable-5-1", effort="medium", per_turn="high"),
        _assistant("claude-haiku-5-5", effort="low", sidechain=True),          # 子代理：不算
        _line(type="ai-title", aiTitle="标题", sessionId=SID),
    ]) + "\n"
    parsed = si.parse_transcript_tail(text)
    assert parsed["model"] == "claude-fable-5-1"
    assert parsed["effort"] == "high", "这一轮实际的 effort 优先于会话级的"


def test_fallbacks_when_fields_are_missing():
    parsed = si.parse_transcript_tail(_line(type="assistant", sessionId=SID, requestedModel="claude-sonnet-5-5",
                                            effort="low", message={"role": "assistant", "content": []}) + "\n")
    assert parsed["model"] == "claude-sonnet-5-5" and parsed["effort"] == "low"
    assert "model" not in si.parse_transcript_tail(_line(type="user", message={"content": "x"}) + "\n")


def test_model_ids_get_readable_names():
    assert si.model_label("claude-fable-5-1") == "Fable 5.1"
    assert si.model_label("claude-opus-5-5") == "Opus 5.5"
    assert si.model_label("claude-sonnet-5-5-20260601") == "Sonnet 5.5"
    assert si.model_label("claude-haiku-5-5") == "Haiku 5.5"
    assert si.model_label("claude-opus-4-6") == "Opus 4.6"
    assert si.model_label("something-else") == "something-else", "认不出的原样给"
    assert si.model_label("") == ""


def test_the_detail_carries_them_and_the_status_line_shows_them(tmp_path):
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(_assistant("claude-fable-5-1", per_turn="max") + "\n", encoding="utf-8")
    detail = si.from_session("claude", {"sessionId": SID, "title": "t", "project": "p",
                                        "transcript": str(transcript), "phase": "resting"})
    si.load_local(detail, home=tmp_path, alive=lambda entry: True)
    assert detail.model == "claude-fable-5-1" and detail.effort == "max"
    assert status_line(detail, None) == "休息中 · Fable 5.1 · max"
    assert status_line(detail, 1000.0, now=1000.0 + 330) == "休息中 · Fable 5.1 · max · 已 5 分钟"
    bare = si.SessionDetail(phase="resting")
    assert status_line(bare, None) == "休息中", "没读到模型的会话一个字都不多"


def test_the_card_shows_the_model_and_effort(shell):  # noqa: F811
    fish = _session(shell)

    def loader(detail):
        detail.model, detail.effort = "claude-opus-5-5", "high"
        return detail

    shell.session_actions.loader = loader
    shell._on_sprite_click(fish, "")
    card = shell.session_actions._card
    assert _pump(lambda: "Opus 5.5 · high" in card.status_label.text())
