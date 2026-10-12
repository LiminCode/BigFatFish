# -*- coding: utf-8 -*-
"""工作简报第二轮：工单 / PR 点得开，灵动岛上有个按钮直接打开简报。

用户看到第一版后的两条反馈（2026-10-12）：

- 简报里的工单号、PR 号都是纯文字，想看得自己去搜；
- 想看简报得右键翻两层菜单，希望灵动岛最右边（连接图标右边）有个按钮。

链接分两层：提示词里要求模型写成链接；模型漏掉的由代码补——PR 的地址是 gh 查回来的，
工单的站点地址从正文里已有的任意一个工单链接认出来。认不出来就不补，绝不编。
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from pet import work_briefing as wb
from pet.config import Config
from pet.dynamic_island import DynamicIsland
from pet.work_briefing_ui import WorkBriefingWindow
from tests.test_work_briefing import MONDAY_10, FakeWsl, _claude_json, _controller

app = QApplication.instance() or QApplication([])

PR_URL = "https://github.com/acme/widgets/pull/10"
JIRA = "https://acme.atlassian.net/browse/"


def _prs(*titles) -> str:
    return json.dumps([{"repository": {"nameWithOwner": "acme/widgets"}, "number": 10 + i, "title": title,
                        "updatedAt": "2026-10-11T08:00:00Z", "isDraft": False,
                        "url": f"https://github.com/acme/widgets/pull/{10 + i}"} for i, title in enumerate(titles)])


# ---------------------------------------------------------------- 链接

def test_the_pr_list_given_to_the_model_carries_links():
    text = wb.format_pull_requests(_prs("Fix login") + f"\n{wb.PR_MARK}\n[]")
    assert f"[acme/widgets#10]({PR_URL}) Fix login" in text
    assert "url" in wb.pr_command(), "gh 得把链接一起查回来"


def test_the_prompt_asks_for_links_and_forbids_made_up_ones():
    prompt = wb.build_prompt(MONDAY_10, "")
    assert "/browse/" in prompt and "链接" in prompt and "不要编" in prompt


def test_pr_references_the_model_left_bare_are_linked_afterwards():
    links = wb.pull_request_links(_prs("Fix login") + f"\n{wb.PR_MARK}\n[]")
    assert links == {"acme/widgets#10": PR_URL, "widgets#10": PR_URL}

    out = wb.linkify("- widgets#10：修登录\n- acme/widgets#10 again\n- widgets#100 不认识", links)
    assert f"- [widgets#10]({PR_URL})：修登录" in out
    assert f"- [acme/widgets#10]({PR_URL}) again" in out
    assert "- widgets#100 不认识" in out, "没查到的编号不硬凑链接"


def test_jira_keys_are_linked_once_the_site_is_known_from_any_link_in_the_text():
    text = f"- [DEMO-1]({JIRA}DEMO-1) 一号\n- DEMO-22 二号，另见 DEMO-1。\n"
    out = wb.linkify(text, {})
    assert f"- [DEMO-22]({JIRA}DEMO-22) 二号" in out and f"另见 [DEMO-1]({JIRA}DEMO-1)。" in out
    assert out.count(f"[DEMO-1]({JIRA}DEMO-1)") == 2, "已经是链接的不再套一层"


def test_nothing_is_guessed_when_the_site_is_unknown():
    text = "- DEMO-22 二号\n"
    assert wb.linkify(text, {}) == text


def test_links_code_and_urls_are_left_alone():
    text = f"- [DEMO-1 的讨论]({JIRA}DEMO-1) · `DEMO-2` · {JIRA}DEMO-3 · [打开](https://x.test/a/DEMO-4)\n"
    assert wb.linkify(text, {}) == text


def test_generating_links_the_final_text():
    wsl = FakeWsl(claude_stdout=_claude_json(result="概要：看 PR。\n\n## PR\n- widgets#10 修登录\n"),
                  pr_stdout=_prs("Fix login") + f"\n{wb.PR_MARK}\n[]")
    briefing = wb.generate(MONDAY_10, "sonnet", run=wsl)
    assert f"[widgets#10]({PR_URL})" in briefing.markdown


def _fragments(window):
    block = window.body.document().begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            yield it.fragment()
            it += 1
        block = block.next()


def test_the_window_shows_links_and_status_chips():
    window = WorkBriefingWindow()
    md = f"## Jira\n- [DEMO-1]({JIRA}DEMO-1) 示例 · `进行中`\n"
    window.show_briefing(wb.Briefing(ok=True, summary="概要", markdown=md, generated_at="2026-10-12T09:00:00"))

    anchors = [(f.text(), f.charFormat().anchorHref()) for f in _fragments(window) if f.charFormat().isAnchor()]
    chips = [f.charFormat() for f in _fragments(window) if f.text() == "进行中"]
    assert ("DEMO-1", f"{JIRA}DEMO-1") in anchors
    assert window.body.openExternalLinks()
    assert chips and chips[0].background().style() != Qt.BrushStyle.NoBrush, "状态画成一个小标签"


# ---------------------------------------------------------------- 灵动岛上的按钮

def _island(tmp_path, **overrides) -> DynamicIsland:
    config = Config(tmp_path)
    config.set("dynamic_island", {"enabled": True, "show_icon": True, "show_name": True, "show_info": True,
                                  "show_status": True, "style": "dark", "x": 400, "y": 300, **overrides})
    island = DynamicIsland(config)
    island.show()
    return island


def _click(island, x: float) -> None:
    pos = QPointF(x, 22.0)
    for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
        pressed = Qt.MouseButton.LeftButton if kind == QEvent.Type.MouseButtonPress else Qt.MouseButton.NoButton
        QApplication.sendEvent(island, QMouseEvent(
            kind, pos, QPointF(island.mapToGlobal(pos.toPoint())), Qt.MouseButton.LeftButton, pressed,
            Qt.KeyboardModifier.NoModifier))


def test_the_island_has_no_briefing_button_until_told_so(tmp_path):
    island = _island(tmp_path)
    try:
        assert island.briefing_button_rect() is None
        plain = island.width()
        island.set_briefing_state("idle")
        assert island.width() > plain, "按钮自己占一格，不挤连接图标"
        rect = island.briefing_button_rect()
        assert rect is not None and rect.right() <= island.width()
        island.set_briefing_state("hidden")
        assert island.width() == plain and island.briefing_button_rect() is None
    finally:
        island.close()


def test_the_button_is_painted_in_its_own_cell_at_the_right_end(tmp_path):
    island = _island(tmp_path)
    try:
        island.set_briefing_state("idle")
        image = island._content_cache().toImage()
        rect = island.briefing_button_rect()
        dpr = image.devicePixelRatio()
        inked = sum(1 for x in range(int(rect.left() * dpr), min(image.width(), int(rect.right() * dpr)))
                    for y in range(image.height()) if image.pixelColor(x, y).alpha() > 128)
        assert inked > 20, "按钮那一格里真的画了东西"
        right_of_it = sum(1 for x in range(int(rect.right() * dpr), image.width())
                          for y in range(image.height()) if image.pixelColor(x, y).alpha() > 128)
        assert right_of_it == 0, "它是最右边的一个"
    finally:
        island.close()


def test_clicking_the_button_asks_for_the_briefing_and_does_not_open_the_card(tmp_path):
    island = _island(tmp_path)
    try:
        island.set_briefing_state("idle")
        asked = []
        island.briefing_requested.connect(lambda: asked.append(1))
        _click(island, island.briefing_button_rect().center().x())
        assert asked == [1] and island.mode != "expanded"

        _click(island, 30)
        assert asked == [1] and island.mode == "expanded", "点别处照旧展开卡片"
    finally:
        island.close()


def test_an_unread_briefing_looks_different_and_says_so(tmp_path):
    island = _island(tmp_path)
    try:
        island.set_briefing_state("idle")
        idle = island._content_cache().toImage()
        assert island.briefing_tooltip() == "工作简报"
        island.set_briefing_state("unread")
        assert island._content_cache().toImage() != idle
        assert "新" in island.briefing_tooltip()
    finally:
        island.close()


def test_the_controller_reports_unread_until_the_window_is_opened(tmp_path):
    controller, _host, service, _made = _controller(tmp_path)
    states = []
    controller.state_changed.connect(states.append)
    assert controller.island_state == "idle"

    service.check()
    app.processEvents()
    assert controller.island_state == "unread" and states == ["unread"]

    controller.open_window()
    assert controller.island_state == "idle" and states == ["unread", "idle"]
    controller.window.close()


def test_people_who_never_use_the_briefing_do_not_get_the_button(tmp_path):
    """装了 WSL 不等于要用简报：没开自动生成、也没生成过，岛上就不该多一个按钮。"""
    off = {"enabled": False, "time": "09:00", "weekdays_only": True, "model": "sonnet"}
    controller, _host, service, _made = _controller(tmp_path, settings=off)
    states = []
    controller.state_changed.connect(states.append)
    assert controller.island_state == "hidden"

    service._config.set(wb.CONFIG_KEY, {**off, "enabled": True})
    controller.refresh_state()
    assert states == ["idle"], "菜单里一打开，按钮就出现"

    service._config.set(wb.CONFIG_KEY, off)
    service.generate_now()
    app.processEvents()
    controller.open_window()
    assert controller.island_state == "idle", "关着自动生成但手动做过一份：按钮留着，好再打开看"
    controller.window.close()


def test_the_app_shows_the_button_only_when_the_briefing_is_wired_and_opens_it_on_click(tmp_path):
    """AppShell 的两段接线：把控制器的状态推给岛、把岛的点击交给控制器。"""
    from types import SimpleNamespace

    from pet.app import AppShell

    island = _island(tmp_path / "island")
    try:
        shell = SimpleNamespace(island=island, _work_briefing=None)
        AppShell._push_island_briefing_state(shell)
        assert island.briefing_button_rect() is None, "没接简报服务（没有 WSL）就没有按钮"

        controller, _host, service, _made = _controller(tmp_path / "briefing")
        shell._work_briefing = controller
        controller.state_changed.connect(lambda _state: AppShell._push_island_briefing_state(shell))
        AppShell._push_island_briefing_state(shell)
        assert island.briefing_tooltip() == "工作简报"

        service.check()
        app.processEvents()
        assert "新" in island.briefing_tooltip()

        AppShell._open_work_briefing_from_island(shell)
        assert controller.window.isVisible() and island.briefing_tooltip() == "工作简报"
        controller.window.close()
    finally:
        island.close()
