# -*- coding: utf-8 -*-
"""会话小鱼的名字跟着用户给会话改的名字走。

现场（2026-10-12）：在 Claude Code 里给会话改名之后，小鱼头顶的名字和详情卡的标题还是
改名前自动生成的那个。Claude Code 把两种名字分开记：

- 自动标题：transcript 里的 ``{"type":"ai-title","aiTitle":…}``，会话进行中不断追加；
- 用户改的名字：transcript 里的 ``{"type":"custom-title","customTitle":…}``，以及运行
  清单里的 ``"name": …, "nameSource": "user"``。

改名之后自动标题照样继续追加，所以「取最后一个 aiTitle」永远拿不到用户改的名字。

纪律：不读真实的 ~/.claude；hook 脚本用本机的 sh 真跑。
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import claude_session_info as si
from tests.test_claude_hooks import _meta_payload, _run_hook
from tests.test_session_pet_details import SID, _pump, _session, shell  # noqa: F401 - shell 是 fixture

app = QApplication.instance() or QApplication([])

AUTO, RENAMED = "自动生成的标题", "Renamed by hand"


def _line(**entry) -> str:
    return json.dumps(entry, ensure_ascii=False, separators=(",", ":"))


def _transcript_text(*records, filler: int = 0) -> str:
    """``records``：("ai", 标题) / ("custom", 名字)，中间夹正文行。"""
    lines = [_line(type="user", message={"content": "正文"}, cwd="C:\\proj", sessionId=SID)]
    for kind, value in records:
        if kind == "ai":
            lines.append(_line(type="ai-title", aiTitle=value, sessionId=SID))
        else:
            lines.append(_line(type="custom-title", customTitle=value, sessionId=SID))
        lines.append(_line(type="assistant", message={"content": "x" * filler}))
    return "\n".join(lines) + "\n"


def _transcript(tmp_path, *records, filler: int = 0):
    path = tmp_path / "transcript dir" / "session.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_transcript_text(*records, filler=filler), encoding="utf-8")
    return path


# ---------------------------------------------------------------- hook 脚本（小鱼头顶的名字）

def _meta_title(tmp_path, *records, filler: int = 0) -> str:
    transcript = _transcript(tmp_path, *records, filler=filler)
    records_out = _run_hook(tmp_path, "Stop", _meta_payload("Stop", transcript, "/home/u/proj"))
    return records_out[1]["title"]


def test_a_renamed_session_reports_the_users_name_even_though_auto_titles_keep_coming(tmp_path):
    title = _meta_title(tmp_path, ("ai", "旧标题"), ("custom", RENAMED), ("ai", AUTO), ("ai", AUTO + " 2"))
    assert title == RENAMED


def test_the_latest_rename_wins(tmp_path):
    title = _meta_title(tmp_path, ("custom", "第一次改的名字"), ("ai", AUTO), ("custom", RENAMED), ("ai", AUTO))
    assert title == RENAMED


def test_sessions_that_were_never_renamed_still_use_the_latest_auto_title(tmp_path):
    assert _meta_title(tmp_path, ("ai", "旧标题"), ("ai", AUTO)) == AUTO


def test_non_ascii_names_survive(tmp_path):
    assert _meta_title(tmp_path, ("ai", AUTO), ("custom", "改过的中文名字"), ("ai", AUTO)) == "改过的中文名字"


# ---------------------------------------------------------------- 会话记录与运行清单（详情卡的标题）

def test_transcript_parsing_prefers_the_users_name():
    parsed = si.parse_transcript_tail(_transcript_text(("ai", "旧"), ("custom", RENAMED), ("ai", AUTO)))
    assert parsed["title"] == RENAMED

    parsed = si.parse_transcript_tail(_transcript_text(("ai", "旧"), ("ai", AUTO)))
    assert parsed["title"] == AUTO


def _registry(tmp_path, **over):
    sessions = tmp_path / ".claude" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    entry = {"pid": 100, "sessionId": SID, "cwd": "C:\\proj", "startedAt": 1791671005108,
             "entrypoint": "claude-vscode", "version": "2.1.296", "name": "proj-53",
             "nameSource": "derived", **over}
    (sessions / "100.json").write_text(json.dumps(entry), encoding="utf-8")


def _loaded(tmp_path, transcript_text, **registry):
    _registry(tmp_path, **registry)
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(transcript_text, encoding="utf-8")
    detail = si.from_session("claude", {"sessionId": SID, "title": AUTO, "project": "proj",
                                        "transcript": str(transcript), "phase": "idle"})
    return si.load_local(detail, home=tmp_path, alive=lambda entry: True)


def test_the_card_title_is_the_users_name_when_the_transcript_has_one(tmp_path):
    detail = _loaded(tmp_path, _transcript_text(("ai", AUTO), ("custom", RENAMED), ("ai", AUTO)))
    assert detail.title == RENAMED, "hook 先前报上来的自动标题要让位"


def test_the_registry_name_counts_only_when_the_user_set_it(tmp_path):
    """运行清单里的 name 多数是自动拼的（``proj-53``）；只有 nameSource 是 user 的才是用户起的。"""
    renamed = _loaded(tmp_path, _transcript_text(("ai", AUTO)), name=RENAMED, nameSource="user")
    assert renamed.title == RENAMED, "改名记录已经滚出 transcript 尾部时，靠运行清单兜住"

    derived = _loaded(tmp_path, _transcript_text(("ai", AUTO)))
    assert derived.title == AUTO and derived.name == "proj-53"


# ---------------------------------------------------------------- 界面

def test_opening_the_card_also_corrects_the_name_above_the_fish(shell):  # noqa: F811
    """会话空闲时改的名字要等下一轮对话 hook 才会报上来；点开详情卡时顺手更新。"""
    fish = _session(shell, title=AUTO)
    actions = shell.session_actions

    def loader(detail):
        detail.title = RENAMED
        return detail

    actions.loader = loader
    shell._on_sprite_click(fish, "")

    card = actions._card
    assert _pump(lambda: card.title_label.text() == RENAMED)
    assert shell.session_pets.describe(("claude", "A"))["title"] == RENAMED
    assert shell.session_pets.sessions()[0]["title"] == RENAMED, "灵动岛里的会话清单同样更新"
