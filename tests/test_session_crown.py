# -*- coding: utf-8 -*-
"""会话小鱼头顶横幅左上角的金色桂冠：给指定模型的会话戴。

用户 2026-10-14：想一眼看出哪只小鱼跑的是最厉害的模型；给谁戴要能调（以后有更强的模型）。

数据流：hook 脚本在回合边界从会话记录尾部多取一个 ``"model":"claude-…"`` → 收敛器把它当
附加字段随会话更新捎带 → 会话小鱼控制器按配置 ``agent_link.crown_models`` 决定戴不戴 →
sprite 把桂冠画进标签胶囊。

纪律：不读真实的 ~/.claude；hook 脚本用本机的 sh 真跑。
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QMenu

from pet import claude_hooks as ch
from pet import session_crown as crown
from pet.config import Config
from tests.test_claude_hooks import _meta_payload, _run_hook
from tests.test_session_pet_details import SID, _session, shell  # noqa: F401 - shell 是 fixture

app = QApplication.instance() or QApplication([])


def _line(**entry) -> str:
    return json.dumps(entry, ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------- hook 脚本

def _meta(tmp_path, *lines) -> dict:
    transcript = tmp_path / "t dir" / "s.jsonl"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("\n".join(lines) + "\n", encoding="utf-8")
    records = _run_hook(tmp_path, "Stop", _meta_payload("Stop", transcript, "/home/u/proj"))
    return records[1]


def test_the_hook_reports_the_latest_model_in_the_transcript(tmp_path):
    meta = _meta(tmp_path,
                 _line(type="assistant", message={"model": "claude-opus-5-5", "content": []}),
                 _line(type="assistant", message={"model": "claude-fable-5-1", "content": []}),
                 _line(type="ai-title", aiTitle="t"))
    assert meta["model"] == "claude-fable-5-1"


def test_the_hook_leaves_the_model_empty_when_there_is_none_or_it_looks_wrong(tmp_path):
    assert _meta(tmp_path, _line(type="user", message={"content": "hi"})).get("model", "") == ""
    assert _meta(tmp_path, _line(type="assistant", message={"model": "gpt-9", "content": []})).get("model", "") == ""
    meta = _meta(tmp_path, _line(type="assistant", message={"model": "claude-x\" y", "content": []}))
    assert meta.get("model", "") == "", "带怪字符的不要"


# ---------------------------------------------------------------- 收敛器

def test_the_tracker_passes_the_model_along_and_reports_a_change_on_its_own():
    tracker = ch.ClaudeSessionTracker()
    tracker.feed({"event": "UserPromptSubmit", "sessionId": SID})
    tracker.feed({"event": "SessionMeta", "sessionId": SID, "title": "t", "project": "p", "model": "claude-opus-5-5"})
    updates = tracker.take_session_updates()
    assert updates and updates[-1]["model"] == "claude-opus-5-5"
    tracker.feed({"event": "SessionMeta", "sessionId": SID, "title": "t", "project": "p", "model": "claude-fable-5-1"})
    (update,) = tracker.take_session_updates()
    assert update["model"] == "claude-fable-5-1", "只有模型变了也要通知呈现层（桂冠要换）"
    tracker.feed({"event": "SessionMeta", "sessionId": SID, "title": "t", "project": "p", "model": "claude-fable-5-1"})
    assert tracker.take_session_updates() == [], "没变不吵"


# ---------------------------------------------------------------- 配置与匹配

def test_the_crown_goes_to_fable_by_default_and_the_list_is_cleaned(tmp_path):
    assert Config(tmp_path).get("agent_link")["crown_models"] == ["fable"]
    config = Config(tmp_path)
    config.set("agent_link", {**config.get("agent_link"), "crown_models": [" Opus-5-5 ", "fable", "", 3, "bad token!", "fable"]})
    config.save()
    assert Config(tmp_path).get("agent_link")["crown_models"] == ["opus-5-5", "fable"]


def test_a_model_is_crowned_when_any_token_is_part_of_its_id():
    assert crown.is_crowned("claude-fable-5-1", ["fable"])
    assert crown.is_crowned("claude-opus-5-5-20260601", ["opus-5-5"])
    assert not crown.is_crowned("claude-opus-5-5", ["fable"])
    assert not crown.is_crowned("", ["fable"]) and not crown.is_crowned("claude-fable-5-1", [])


# ---------------------------------------------------------------- 小鱼：戴不戴

def _update(shell, sid, model, phase="working"):  # noqa: F811
    shell.session_pets.on_session_update("claude", {"sessionId": sid, "phase": phase, "title": "t", "project": "p",
                                                    "model": model})


def test_the_fish_wears_the_crown_only_for_the_chosen_model(shell):  # noqa: F811
    _update(shell, "A", "claude-fable-5-1")
    _update(shell, "B", "claude-opus-5-5")
    a, b = shell.session_pets.sprite_of(("claude", "A")), shell.session_pets.sprite_of(("claude", "B"))
    assert a.caption_badge == "crown" and b.caption_badge == ""
    assert shell.session_pets.describe(("claude", "A"))["model"] == "claude-fable-5-1"

    _update(shell, "A", "claude-opus-5-5")
    assert a.caption_badge == "", "模型换了，桂冠摘掉"


def test_the_crown_follows_the_model_read_from_the_transcript(shell):  # noqa: F811
    """hook 只在回合开始 / 结束时报模型：会话中途换了模型（/model、/fast）的那一轮，
    hook 报的还是上一轮的。读会话记录发现的模型要当场换桂冠，不等下一回合。"""
    key = ("claude", "A")
    _update(shell, "A", "claude-opus-5-5")
    fish = shell.session_pets.sprite_of(key)
    assert fish.caption_badge == ""

    assert shell.session_pets.remodel(key, "claude-fable-5-1") is True
    assert fish.caption_badge == "crown"
    assert shell.session_pets.describe(key)["model"] == "claude-fable-5-1"
    assert shell.session_pets.seen_models() == ["claude-fable-5-1"], "菜单里列的具体型号也跟着换"

    assert shell.session_pets.remodel(key, "claude-fable-5-1") is False, "没变就不动"
    assert shell.session_pets.remodel(key, "") is False, "记录里读不到模型不算换"
    assert fish.caption_badge == "crown"
    assert shell.session_pets.remodel(("claude", "nobody"), "claude-fable-5-1") is False


def test_changing_the_choice_elsewhere_recrowns_the_fish_when_the_shell_refreshes(shell):  # noqa: F811
    """桂冠给哪个模型 2026-11-19 起在配置全景「会话小鱼」那组里改（一行一个片段）；壳的 ``refresh_settings`` 让在场的小鱼当场换。"""
    _update(shell, "A", "claude-fable-5-1")
    _update(shell, "B", "claude-opus-5-5")
    assert _find(shell._build_menu_for(shell.sprite), "桂冠给哪个模型") is None

    def choose(tokens):
        data = dict(shell._config.get("agent_link"))
        data["crown_models"] = tokens
        shell._config.set("agent_link", data)
        shell.refresh_settings()

    choose(["fable", "opus"])
    assert shell.session_pets.sprite_of(("claude", "B")).caption_badge == "crown"
    choose(["opus"])
    assert shell.session_pets.sprite_of(("claude", "A")).caption_badge == ""


def _find(menu: QMenu, text: str):
    for action in menu.actions():
        if action.text() == text:
            return action
        if action.menu() is not None:
            found = _find(action.menu(), text)
            if found is not None:
                return found
    return None


# ---------------------------------------------------------------- sprite：画出来

def _gold_pixels(sprite) -> int:
    image = sprite.caption_pixmap().toImage()
    count = 0
    for y in range(image.height()):
        for x in range(image.width() // 3):           # 只看左边三分之一
            c = image.pixelColor(x, y)
            if c.alpha() > 128 and c.red() > 170 and c.green() > 110 and c.blue() < 90:
                count += 1
    return count


def test_the_crown_is_painted_gold_at_the_left_of_the_banner(shell):  # noqa: F811
    _update(shell, "A", "claude-opus-5-5")
    sprite = shell.session_pets.sprite_of(("claude", "A"))
    plain_width = sprite.caption_rect().width()
    assert _gold_pixels(sprite) == 0

    _update(shell, "A", "claude-fable-5-1")
    assert sprite.caption_rect().width() > plain_width, "桂冠自己占一格，不压着字"
    assert _gold_pixels(sprite) > 15
    assert QColor(*sprite._CAPTION_TONES["working"][0]).alpha() > 0
