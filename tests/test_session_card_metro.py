# -*- coding: utf-8 -*-
"""会话小鱼详情卡的 Metro 改版（2026-10-28）：上下文用量、VS Code 工作区、磁贴式布局。

数据来源（2026-10-28 实测 Claude Code 2.1.309）：
- 每条主对话的 ``assistant`` 记录带 ``message.usage``；这一轮送进模型的上下文 =
  ``input_tokens + cache_creation_input_tokens + cache_read_input_tokens``；
- 自动压缩写一条 ``type=system, subtype=compact_boundary``，``compactMetadata.postTokens``
  是压缩后剩下的量；
- 会话记录和运行清单里都没有上下文窗口多大，只能按模型查（Claude API 文档的模型表）。

纪律：offscreen；不读真实的 ~/.claude 和 VS Code 记录（后端全部注入）。
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import claude_session_info as si
from pet import claude_session_jump as sj
from pet import session_card_themes as themes
from pet.claude_session_jump import OpenWorkspace
from pet.config import Config
from pet.session_pet_ui import SessionDetailCard, app_caption, context_text, phase_line, workspace_text
from tests.test_session_pet_details import SID, _pump, _session, shell  # noqa: F401 - shell 是 fixture

app = QApplication.instance() or QApplication([])


def _line(**entry) -> str:
    return json.dumps(entry, ensure_ascii=False, separators=(",", ":"))


def _assistant(*, fresh=2, written=2_320, read=135_043, sidechain=False, model="claude-opus-5-5") -> str:
    usage = {"input_tokens": fresh, "cache_creation_input_tokens": written,
             "cache_read_input_tokens": read, "output_tokens": 537}
    return _line(type="assistant", sessionId=SID, isSidechain=sidechain, effort="high",
                 message={"role": "assistant", "model": model, "content": [], "usage": usage})


def _compact(post: int) -> str:
    return _line(type="system", subtype="compact_boundary", sessionId=SID,
                 compactMetadata={"trigger": "auto", "preTokens": 900_000, "postTokens": post})


# ---------------------------------------------------------------- 上下文：用了多少

def test_context_used_is_everything_sent_in_the_latest_main_turn():
    text = "\n".join([
        _assistant(read=50_000),
        _assistant(),                                   # 最近一轮主对话：2 + 2320 + 135043
        _assistant(read=9_000_000, sidechain=True),     # 子代理的不算
    ]) + "\n"
    assert si.parse_transcript_tail(text)["context_tokens"] == 137_365


def test_a_compaction_after_the_latest_turn_resets_the_count():
    assert si.parse_transcript_tail(_assistant() + "\n" + _compact(17_091) + "\n")["context_tokens"] == 17_091
    # 压缩之后又回复过一轮：以那一轮为准
    text = _compact(17_091) + "\n" + _assistant(read=20_000) + "\n"
    assert si.parse_transcript_tail(text)["context_tokens"] == 22_322


def test_missing_or_strange_usage_leaves_it_unknown():
    no_usage = _line(type="assistant", sessionId=SID, message={"role": "assistant", "model": "m", "content": []})
    assert "context_tokens" not in si.parse_transcript_tail(no_usage + "\n")
    assert si.context_used({"input_tokens": "lots", "cache_read_input_tokens": -5}) == 0
    assert si.context_used(None) == 0


def test_the_detail_carries_it(tmp_path):
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(_assistant() + "\n", encoding="utf-8")
    detail = si.from_session("claude", {"sessionId": SID, "transcript": str(transcript)})
    si.load_local(detail, home=tmp_path, alive=lambda entry: True)
    assert detail.context_tokens == 137_365


# ---------------------------------------------------------------- 上下文：窗口多大

@pytest.mark.parametrize(("model", "window"), [
    ("claude-opus-5-5", 1_000_000), ("claude-fable-5-1", 1_000_000), ("claude-sonnet-5-5", 1_000_000),
    ("claude-haiku-5-5", 1_000_000), ("claude-opus-4-6", 1_000_000), ("claude-mythos-5-1", 1_000_000),
    ("claude-haiku-4-5", 200_000), ("claude-sonnet-4-5-20250929", 200_000),
    ("claude-sonnet-4-5[1m]", 1_000_000),
    ("gpt-5", 0), ("", 0),
])
def test_the_window_comes_from_the_model(model, window):
    assert si.context_window(model) == window


def test_the_card_line_shows_used_window_and_share():
    detail = si.SessionDetail(model="claude-opus-5-5", context_tokens=137_365)
    text, ratio, tip = context_text(detail)
    assert text == "137k / 1M · 14%" and ratio == pytest.approx(0.137365)
    assert "137,365" in tip and "1,000,000" in tip


def test_an_unknown_model_shows_only_the_count_and_no_bar():
    text, ratio, _tip = context_text(si.SessionDetail(model="mystery", context_tokens=4_200))
    assert text == "4.2k tokens" and ratio is None
    assert context_text(si.SessionDetail(model="claude-opus-5-5")) == ("", None, "")


def test_a_tiny_share_still_reads_as_at_least_one_percent():
    text, _ratio, _tip = context_text(si.SessionDetail(model="claude-opus-5-5", context_tokens=900))
    assert text.endswith("· 1%")


# ---------------------------------------------------------------- VS Code 工作区

def _ws(label, *roots, multi=False, storage=()):
    target = f"C:/code/{label}.code-workspace" if multi else roots[0]
    return OpenWorkspace(label, tuple(roots), target, multi_root=multi, storage=storage)


def _vscode(**over) -> si.SessionDetail:
    return si.SessionDetail(**{"session_id": SID, "entrypoint": "claude-vscode", "cwd": r"C:\code\shop\web", **over})


def test_the_workspace_is_the_window_that_contains_the_session():
    shop = _ws("shop", "C:/code/shop/web", "C:/code/shop/api", multi=True)
    other = _ws("blog", "C:/code/blog")
    assert sj.session_workspace(_vscode(), [other, shop], mentions=lambda folder, sid: 0) is shop


def test_vs_codes_own_record_beats_the_path_guess():
    alone = _ws("web", "C:/code/shop/web", storage=("s1",))
    shop = _ws("shop", "C:/code/shop/web", "C:/code/shop/api", multi=True, storage=("s2",))
    mentions = lambda folder, sid: 2 if folder == "s2" and sid == SID else 0  # noqa: E731
    assert sj.session_workspace(_vscode(), [alone, shop], mentions=mentions) is shop


def test_two_equally_good_windows_give_no_answer_unless_the_start_folder_decides():
    alone = _ws("web", "C:/code/shop/web")
    shop = _ws("shop", "C:/code/shop/api", "C:/code/shop/web", multi=True)
    none = lambda folder, sid: 0  # noqa: E731
    assert sj.session_workspace(_vscode(), [alone, shop], mentions=none) is None
    started = _vscode(extra={"start_cwd": r"C:\code\shop\api"})
    assert sj.session_workspace(started, [alone, shop], mentions=none) is shop


def test_attach_workspace_only_touches_vscode_sessions_and_survives_bad_records():
    shop = _ws("shop", "C:/code/shop/web", "C:/code/shop/api", multi=True)
    detail = sj.attach_workspace(_vscode(), workspaces=lambda: [shop])
    assert detail.extra["workspace"] == {"label": "shop", "target": "C:/code/shop.code-workspace",
                                         "multi_root": True, "folders": 2}
    terminal = sj.attach_workspace(_vscode(entrypoint="cli"), workspaces=lambda: [shop])
    assert "workspace" not in terminal.extra

    def broken():
        raise ValueError("bad storage.json")
    assert "workspace" not in sj.attach_workspace(_vscode(), workspaces=broken).extra


def test_workspace_line_wording():
    multi = si.SessionDetail(extra={"workspace": {"label": "shop", "multi_root": True, "folders": 3,
                                                  "target": "C:/code/shop.code-workspace"}})
    assert workspace_text(multi)[:2] == ("shop", "多文件夹工作区 · 3 个文件夹")
    single = si.SessionDetail(extra={"workspace": {"label": "web", "folders": 1, "target": "C:/code/web"}})
    assert workspace_text(single)[:2] == ("web", "VS Code 工作区")
    assert workspace_text(si.SessionDetail()) == ("", "", "")


# ---------------------------------------------------------------- 卡片

def _card(tmp_path, theme_id="sea") -> SessionDetailCard:
    config = Config(tmp_path)
    config.set("agent_link", {**config.get("agent_link"), "session_card_theme": theme_id})
    return SessionDetailCard(config)


def _full_detail(**over) -> si.SessionDetail:
    detail = _vscode(title="修登录", phase="working", model="claude-opus-5-5", effort="high",
                     last_prompt="为什么登录会跳两次？", git_branch="fix/login", context_tokens=137_365, **over)
    detail.extra["workspace"] = {"label": "shop", "multi_root": True, "folders": 3, "target": "C:/code/shop"}
    return detail


def test_the_card_lays_everything_out_as_tiles_and_rows(tmp_path):
    card = _card(tmp_path)
    try:
        card.show_detail(_full_detail(), 1000.0, now=1000.0 + 200)
        assert card.app_label.text() == "CLAUDE CODE · VS CODE 插件"
        assert card.title_label.text() == "修登录" and card.status_label.text() == "工作中"
        assert [card.tiles[k].value.text() for k in ("model", "effort", "time")] == ["Opus 5.5", "high", "3 分钟"]
        assert card.context_value.text() == "137k / 1M · 14%" and card.context_bar.ratio == pytest.approx(0.137365)
        assert card.workspace_row.text.text() == "shop" and card.workspace_row.sub.text() == "多文件夹工作区 · 3 个文件夹"
        assert card.folder_row.text.text() == r"C:\code\shop\web" and card.branch_row.text.text() == "fix/login"
        for widget in (*card.tiles.values(), card.context_box, card.context_bar, card.workspace_row):
            assert widget.isVisibleTo(card)
    finally:
        card.close()
        card.deleteLater()


def test_what_was_not_read_is_left_out_instead_of_shown_empty(tmp_path):
    card = _card(tmp_path)
    try:
        card.show_detail(si.SessionDetail(title="t", phase="resting", entrypoint="cli", cwd=r"C:\p",
                                          git_branch="HEAD", context_tokens=0), None)
        assert not any(tile.isVisibleTo(card) for tile in card.tiles.values())
        assert not card.context_box.isVisibleTo(card)
        assert not card.workspace_row.isVisibleTo(card) and not card.branch_row.isVisibleTo(card)
        assert card.folder_row.isVisibleTo(card)
        card.show_detail(si.SessionDetail(title="t", model="mystery", effort="high", context_tokens=500), None)
        assert card.tiles["model"].isVisibleTo(card) and card.tiles["effort"].isVisibleTo(card)
        assert card.context_box.isVisibleTo(card) and not card.context_bar.isVisibleTo(card), "不知道窗口就不画比例"
    finally:
        card.close()
        card.deleteLater()


@pytest.mark.parametrize("theme_id", list(themes.CARD_THEMES))
def test_metro_look_square_flat_and_an_accent_header(tmp_path, theme_id):
    card = _card(tmp_path, theme_id)
    try:
        card.show_detail(_full_detail(), None)
        card.adjustSize()
        image = card.grab().toImage()
        theme = themes.CARD_THEMES[theme_id]
        assert image.pixelColor(0, 0).name() == theme["border"], "方角：最角上那个像素就是边，不是透明的圆角外"
        assert image.pixelColor(card.width() - 1, card.height() - 1).name() == theme["border"]
        header = card.header.geometry()
        assert image.pixelColor(header.left() + 4, header.bottom() - 2).name() == theme["accent"]
        jump = card.jump_btn
        spot = jump.mapTo(card, jump.rect().topLeft())
        assert image.pixelColor(spot.x() + 3, spot.y() + 3).name() == theme["accent"], "主按钮用强调色"
    finally:
        card.close()
        card.deleteLater()


def test_status_and_caption_wording():
    assert phase_line(si.SessionDetail(phase="waiting", tool="Bash")) == "在等你批准：Bash"
    assert phase_line(si.SessionDetail(phase="review")) == "等你回复"
    assert app_caption(si.SessionDetail(entrypoint="claude-desktop")) == "CLAUDE CODE · CLAUDE 桌面版"
    assert app_caption(si.SessionDetail(agent="claude_wsl", entrypoint="cli")) == "CLAUDE CODE · 终端 · WSL"
    assert app_caption(si.SessionDetail()) == "CLAUDE CODE"


def test_clicking_a_vscode_session_fish_shows_its_workspace(shell):  # noqa: F811
    fish = _session(shell)
    actions = shell.session_actions

    def loader(detail):
        detail.entrypoint, detail.model, detail.context_tokens = "claude-vscode", "claude-opus-5-5", 50_000
        detail.extra["workspace"] = {"label": "proj", "folders": 1, "target": r"C:\code\proj"}
        return detail

    actions.loader = loader
    shell._on_sprite_click(fish, "")
    card = actions._card
    assert _pump(lambda: card.workspace_row.text.text() == "proj")
    assert card.context_value.text() == "50k / 1M · 5%"


def test_the_production_loader_adds_the_workspace(monkeypatch):
    from pet import session_pet_ui

    calls = []
    monkeypatch.setattr(si, "load", lambda detail: (calls.append("load"), detail)[1])
    monkeypatch.setattr(sj, "attach_workspace", lambda detail: (calls.append("workspace"), detail)[1])
    session_pet_ui.load_detail(si.SessionDetail())
    assert calls == ["load", "workspace"]


# ---------------------------------------------------------------- 共用图标库

def test_the_new_shared_icons_draw_in_the_colour_asked_for():
    """详情卡的图标走共用矢量图标库；新加的三个名字不能落到「认不出 → 画个圆」的兜底。"""
    from PySide6.QtWidgets import QWidget

    from pet.context_menus.icons import vector_widget_icon

    widget = QWidget()
    try:
        fallback = vector_widget_icon(widget, "no-such-icon", 16, "#ff0000").pixmap(16, 16).toImage()
        for name in ("folder", "branch", "jump"):
            image = vector_widget_icon(widget, name, 16, "#ff0000").pixmap(16, 16).toImage()
            assert image != fallback, name
            inked = [image.pixelColor(x, y) for x in range(16) for y in range(16) if image.pixelColor(x, y).alpha() > 200]
            assert inked and all(c.red() > 200 and c.green() < 60 for c in inked), f"{name} 要用给的颜色画"
    finally:
        widget.deleteLater()
