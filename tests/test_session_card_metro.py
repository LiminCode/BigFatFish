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
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from pet import claude_session_info as si
from pet import claude_session_jump as sj
from pet import session_card_themes as themes
from pet.claude_session_jump import OpenWorkspace
from pet.config import Config
from pet.session_pet_ui import SessionDetailCard, context_text, phase_line, workspace_text
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
    detail = _vscode(**{"title": "修登录", "phase": "working", "model": "claude-opus-5-5", "effort": "high",
                        "last_prompt": "为什么登录会跳两次？", "git_branch": "fix/login",
                        "context_tokens": 137_365, **over})
    detail.extra["workspace"] = {"label": "shop", "multi_root": True, "folders": 3, "target": "C:/code/shop"}
    return detail


def test_the_card_lays_everything_out_as_tiles_and_rows(tmp_path):
    card = _card(tmp_path)
    try:
        card.show_detail(_full_detail(), 1000.0, now=1000.0 + 200)
        assert card.app_label.text() == "VS Code 插件" and card.host_tile.isVisibleTo(card)
        assert card.title_label.text() == "修登录" and card.status_label.full_text == "工作中"
        assert [card.meta[k].value.text() for k in ("model", "effort", "time")] == ["Opus 5.5", "high", "3 分钟"]
        assert card.context_value.text() == "137k / 1M · 14%" and card.context_bar.ratio == pytest.approx(0.137365)
        assert card.workspace_row.text.full_text == "shop" and card.workspace_row.sub.text() == "多文件夹工作区 · 3 个文件夹"
        assert card.folder_row.text.full_text == r"C:\code\shop\web" and card.branch_row.text.full_text == "fix/login"
        for widget in (*card.meta.values(), card.context_box, card.context_bar, card.workspace_row):
            assert widget.isVisibleTo(card)
    finally:
        card.close()
        card.deleteLater()


def test_what_was_not_read_is_left_out_instead_of_shown_empty(tmp_path):
    card = _card(tmp_path)
    try:
        card.show_detail(si.SessionDetail(title="t", phase="resting", entrypoint="cli", cwd=r"C:\p",
                                          git_branch="HEAD", context_tokens=0), None)
        assert not any(chip.isVisibleTo(card) for chip in card.meta.values())
        assert not card.context_box.isVisibleTo(card)
        assert not card.workspace_row.isVisibleTo(card) and not card.branch_row.isVisibleTo(card)
        assert card.folder_row.isVisibleTo(card)
        card.show_detail(si.SessionDetail(title="t", model="mystery", effort="high", context_tokens=500), None)
        assert card.meta["model"].isVisibleTo(card) and card.meta["effort"].isVisibleTo(card)
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
    assert si.SessionDetail(entrypoint="claude-desktop").entry_text == "Claude 桌面版"
    assert si.SessionDetail(agent="claude_wsl", entrypoint="cli").entry_text == "终端 · WSL"


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
    assert _pump(lambda: card.workspace_row.text.full_text == "proj")
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


# ---------------------------------------------------------------- 第二轮（2026-10-28 用户看了实机卡片）：
# 字太大要能调；路径 / 分支用等宽字；模型那几项不重要、缩小；「在哪打开的」用那个程序的图标；
# 最近的问题和按钮在实机上被截掉了一截。

LONG_PROMPT = ("we need these: 1st, make them display more beautiful, can think of use icon, or use different "
               "font or size or color, I have no specific requirement, do it according your aesthetic. also, "
               "the model, effort, time, can do it more beautiful too, maybe can show the context limit")
LONG_PATH = r"C:\Users\me\Github\BigFatFish\.claude\worktrees\desktop-work-buddy-features-f7813f"


def _sized_card(tmp_path, size):
    config = Config(tmp_path)
    config.set("agent_link", {**config.get("agent_link"), "session_card_text_size": size})
    return SessionDetailCard(config)


def test_text_size_is_its_own_setting_with_four_steps(tmp_path):
    config = Config(tmp_path)
    assert config.get("agent_link")["session_card_text_size"] == 100
    config.set("agent_link", {**config.get("agent_link"), "session_card_text_size": 115})
    config.save()
    assert Config(tmp_path).get("agent_link")["session_card_text_size"] == 115
    for bad in (999, "big", None):
        config.set("agent_link", {**config.get("agent_link"), "session_card_text_size": bad})
        config.save()
        assert Config(tmp_path).get("agent_link")["session_card_text_size"] == 100
    assert [size for size, _label in themes.text_size_choices()] == [85, 100, 115, 130]


def test_the_card_follows_its_text_size_not_the_bubble_scale(tmp_path):
    config = Config(tmp_path)
    config.set("bubble_text_scale", 200)
    card = SessionDetailCard(config)
    try:
        assert card.scale == 1.0, "气泡字再大，详情卡也按自己那一项"
        assert card.font().pixelSize() == 13
    finally:
        card.deleteLater()
    small, large = _sized_card(tmp_path / "s", 85), _sized_card(tmp_path / "l", 130)
    try:
        assert small.font().pixelSize() < 13 < large.font().pixelSize()
        assert small.width() < large.width()
    finally:
        small.deleteLater()
        large.deleteLater()


def test_both_menus_offer_the_text_size_and_reopening_uses_the_new_one(shell):  # noqa: F811
    from tests.test_session_card_themes import _find

    fish = _session(shell)
    actions = shell.session_actions
    actions.loader = lambda detail: detail
    actions.show_card(fish)
    first = actions._card
    assert first.scale == 1.0
    for menu in (shell._build_menu_for(fish), shell._build_menu_for(shell.sprite)):
        large = _find(menu, "大")
        assert large is not None and large.isCheckable() and not large.isChecked()
    _find(shell._build_menu_for(fish), "大").trigger()
    assert shell._config.get("agent_link")["session_card_text_size"] == 115
    actions.show_card(fish)
    assert actions._card is not first and actions._card.scale == 1.15


def test_secondary_facts_are_small_and_quiet(tmp_path):
    card = _card(tmp_path)
    try:
        card.show_detail(_full_detail(), 1000.0, now=1200.0)
        card.show()
        app.processEvents()
        chip = card.meta["model"]
        assert chip.value.font().pixelSize() < card.prompt_label.font().pixelSize(), "比正文小"
        assert chip.value.font().pixelSize() < card.title_label.font().pixelSize()
        assert chip.icon.width() <= card._px(12)
        assert chip.toolTip() == "模型: Opus 5.5" and chip.accessibleName() == "模型: Opus 5.5"
    finally:
        card.close()
        card.deleteLater()


@pytest.mark.parametrize(("entrypoint", "agent", "host"), [
    ("claude-desktop", "claude", "desktop"), ("claude-vscode", "claude", "vscode"),
    ("claude-vscode", "claude_wsl", "vscode"), ("cli", "claude", "terminal"), ("cli", "claude_wsl", "wsl"),
    ("sdk-cli", "claude", "script"), ("", "claude", ""),
])
def test_where_it_was_opened_picks_the_apps_icon(entrypoint, agent, host):
    from pet.claude_session_history import HistoryEntry

    assert si.SessionDetail(agent=agent, entrypoint=entrypoint).host == host
    assert HistoryEntry(agent=agent, session_id="x", entrypoint=entrypoint).host == host, "岛上的历史列表同一套"


def test_the_header_shows_the_apps_own_icon(tmp_path, monkeypatch):
    from PySide6.QtGui import QColor, QIcon, QPixmap

    from pet import host_icons

    host_icons.clear_cache()
    asked = []
    red = QPixmap(32, 32)
    red.fill(QColor("#ff0000"))
    monkeypatch.setattr(host_icons, "host_executable", lambda kind: (asked.append(kind), f"C:/{kind}.exe")[1])
    monkeypatch.setattr(host_icons, "_shell_icon", lambda path: QIcon(red))
    card = _card(tmp_path)
    try:
        card.show_detail(si.SessionDetail(entrypoint="claude-desktop", title="t"), None)
        assert asked == ["desktop"] and card.host_tile.isVisibleTo(card)
        image = card.host_tile.pixmap().toImage()
        assert image.pixelColor(image.width() // 2, image.height() // 2).name() == "#ff0000"
        assert card.app_label.text() == "Claude 桌面版"
    finally:
        card.close()
        card.deleteLater()
        host_icons.clear_cache()


def test_the_desktop_app_is_found_through_the_package_registry(monkeypatch):
    from pet import host_icons

    root = r"C:\Apps\Claude_4.29.0.0_x64__pzs8sxrjxfjjc"
    monkeypatch.setattr(host_icons.sys, "platform", "win32")
    monkeypatch.setattr(host_icons, "_desktop_package_roots", lambda: [root])
    found = host_icons.host_executable("desktop", exists=lambda path: path.startswith(root))
    assert found == root + r"\app\claude.exe"
    assert host_icons.FALLBACK_GLYPHS["desktop"] == "sparkle", "装没装都有个记号"


def test_a_long_question_shows_whole_lines_and_nothing_is_cut_off(tmp_path):
    """实机截图：英文的长问题只露出两行半，按钮上的字也被截掉（「Jump to cha」）。"""
    from PySide6.QtGui import QFontMetrics

    from pet import i18n

    previous = i18n.current_language()
    config = Config(tmp_path)              # 读配置会把界面语言设回配置里的那个：之后再切英文
    i18n.set_language("en")
    card = SessionDetailCard(config)
    try:
        card.show_detail(_full_detail(last_prompt=LONG_PROMPT, cwd=LONG_PATH), None)
        card.show()
        app.processEvents()
        prompt = card.prompt_label
        lines = prompt.text().split("\n")
        assert len(lines) == 4 and lines[-1].endswith("…") and prompt.toolTip() == LONG_PROMPT
        assert prompt.height() >= 4 * QFontMetrics(prompt.font()).lineSpacing(), "四行都要露出来"
        for button in (card.jump_btn, card.folder_btn, card.copy_btn):
            assert button.width() >= button.sizeHint().width(), "按钮上的字不能被截"
            assert button.mapTo(card, button.rect().topRight()).x() < card.width()
        assert card.copy_btn.toolTip() == "Copy resume command" and card.copy_btn.accessibleName()
    finally:
        card.close()
        card.deleteLater()
        i18n.set_language(previous)


def test_host_icons_are_warmed_at_the_cards_size(shell, monkeypatch):  # noqa: F811
    """桌面版的图标第一次从外壳取要 360 ms：启动稳定后按详情卡的尺寸先取好。"""
    from pet import host_icons

    sizes = []
    monkeypatch.setattr(host_icons, "warm", lambda widget, size, **_kw: sizes.append(size) or 0)
    shell._config.set("agent_link", {**shell._config.get("agent_link"), "session_card_text_size": 130})
    shell.session_actions._warm_host_icons()
    assert sizes == [21], "16 px × 130%"


def test_path_and_branch_share_one_tile_scroll_sideways_and_copy(tmp_path):
    """第四轮（2026-10-28 实机）：省略了看不全、也没法复制。现在两行放在一块磁贴里，放不下就
    左右滑（先停在最右端），字可以拖选，右边的按钮复制整个值。"""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QGuiApplication, QWheelEvent

    card = _card(tmp_path)
    try:
        branch = "claude/desktop-work-buddy-features-f7813f"
        card.show_detail(_full_detail(cwd=LONG_PATH, git_branch=branch), None)
        card.show()
        app.processEvents()
        folder = card.folder_row
        assert folder.parent() is card.places and card.branch_row.parent() is card.places, "同一块磁贴"
        assert folder.text.objectName() == "session-card-mono" and card.branch_row.text.objectName() == "session-card-mono"
        assert folder.text.text() == LONG_PATH, "不省略，全文都在"
        assert folder.text.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse, "能拖选"
        bar = folder.scroll.horizontalScrollBar()
        assert folder.overflows() and bar.value() == bar.maximum(), "先停在最右端：最后一层目录最有用"
        spot = QPointF(10, 5)
        wheel = QWheelEvent(spot, QPointF(folder.scroll.mapToGlobal(QPoint(10, 5))), QPoint(), QPoint(0, 120),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase,
                            False)
        app.sendEvent(folder.scroll.viewport(), wheel)
        assert bar.value() < bar.maximum(), "滚轮上下滚也当左右滑"
        folder.copy_btn.click()
        assert QGuiApplication.clipboard().text() == LONG_PATH
        assert card.result_label.text() == "路径已复制" and card.result_label.isVisibleTo(card)
        card.branch_row.copy_btn.click()
        assert QGuiApplication.clipboard().text() == branch and card.result_label.text() == "分支名已复制"
        assert folder.copy_btn.toolTip() == "复制路径" and folder.copy_btn.accessibleName() == "复制路径"

        card.show_detail(_full_detail(cwd=r"C:\p", git_branch="main"), None)
        app.processEvents()
        assert not card.folder_row.overflows(), "短的不出滚动条"
        card.show_detail(_full_detail(cwd="", git_branch=""), None)
        assert not card.places.isVisibleTo(card), "两行都没有就整块不显示"
    finally:
        card.close()
        card.deleteLater()


def test_tooltips_on_the_card_are_at_least_body_size(tmp_path):
    """第四轮：悬停提示的字比正文小，用户嫌看不清。"""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QEnterEvent
    from PySide6.QtWidgets import QToolTip

    card = _card(tmp_path)
    try:
        assert card.testAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips), "卡片不在前台也要能弹"
        long_name = "a-really-long-workspace-name-" * 4
        detail = _full_detail()
        detail.extra["workspace"] = {"label": long_name, "folders": 1, "target": "C:/x"}
        card.show_detail(detail, None)
        card.show()
        app.processEvents()
        label = card.workspace_row.text
        assert label.is_elided()
        spot = QPointF(4, 4)
        app.sendEvent(label, QEnterEvent(spot, spot, QPointF(label.mapToGlobal(spot.toPoint()))))
        assert QToolTip.isVisible() and QToolTip.text() == long_name, "省略了的一移上来就是全文"
        tip = next(w for w in QApplication.topLevelWidgets() if w.objectName() == "qtooltip_label" and w.isVisible())
        tip.ensurePolished()
        assert tip.font().pixelSize() >= card.font().pixelSize(), "提示的字不比正文小"
    finally:
        QToolTip.hideText()
        card.close()
        card.deleteLater()



def test_hovering_or_clicking_the_row_icon_shows_the_whole_value(tmp_path):
    """第五轮（2026-10-28）：只想看一眼完整路径时，不用拖滚动条——移到前面的图标上（或点一下）就显示。"""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QEnterEvent, QMouseEvent
    from PySide6.QtWidgets import QToolTip

    card = _card(tmp_path)
    try:
        branch = "claude/desktop-work-buddy-features-f7813f"
        card.show_detail(_full_detail(cwd=LONG_PATH, git_branch=branch), None)
        card.show()
        app.processEvents()
        for row, full in ((card.folder_row, LONG_PATH), (card.branch_row, branch)):
            icon = row.icon
            spot = QPointF(3, 3)
            app.sendEvent(icon, QEnterEvent(spot, spot, QPointF(icon.mapToGlobal(QPoint(3, 3)))))
            assert QToolTip.isVisible() and QToolTip.text() == full, "移上来就是整个值"
            app.sendEvent(icon, QEvent(QEvent.Type.Leave))
            assert _pump(lambda: not QToolTip.isVisible(), 5.0), "移开就收"
            press = QMouseEvent(QEvent.Type.MouseButtonPress, spot, QPointF(icon.mapToGlobal(QPoint(3, 3))),
                                Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            app.sendEvent(icon, press)
            assert QToolTip.isVisible() and QToolTip.text() == full, "点一下也显示"
            QToolTip.hideText()
            assert _pump(lambda: not QToolTip.isVisible(), 5.0)
        assert card.folder_row.icon.cursor().shape() == Qt.CursorShape.PointingHandCursor, "看得出能点"
    finally:
        QToolTip.hideText()
        card.close()
        card.deleteLater()
