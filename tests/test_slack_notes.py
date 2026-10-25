# -*- coding: utf-8 -*-
"""Slack 关注的每一条都落成仓库里的 Markdown，并在简报窗口里多一页「Slack 关注」（用户 2026-10-20）。

- 每条需要你看的 Slack 消息 → ``AI-Base-Memory/slack/<日期-时间>-<标题>.md``（和笔记同一种 Obsidian 格式），
  同一条链接不重复存；和 note/ 一起提交推送。
- 「Slack 关注」页：最新的在最前；查看（开链接）/ 稍后 X 小时 / 完成；到点、人在 → 肥鱼再冒一次带按钮的气泡。
- 新条目的那个总提醒多一个「稍后 1 小时」，点了就把这批都放到一小时后。

纪律：不起真的 wsl.exe、不碰真实数据目录、不真的打开浏览器。git 用同步的假函数。
"""
from __future__ import annotations

import datetime as dt
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import claude_hooks as ch
from pet import i18n
from pet import slack_watch as sw
from pet import work_notes as wn
from pet.config import Config
from pet.slack_watch_service import SlackWatchService
from pet.slack_watch_ui import ALERT_ID, SlackWatchController
from pet.work_notes_service import WorkNotesService
from pet.work_notes_ui import SLACK_ALERT_PREFIX, WorkNotesController
from tests.test_slack_watch import ITEMS, _claude_json
from tests.test_work_notes_ui import _COLORS, _Fakes, _Host

app = QApplication.instance() or QApplication([])

NOW = dt.datetime(2026, 10, 20, 10, 30)
URGENT = {"title": "问你发布窗口定了没", "from": "#release", "link": "https://x.slack.com/archives/C1/p1",
          "urgency": "high", "key": "https://x.slack.com/archives/C1/p1"}
PLAIN = {"title": "私信：周会改到四点可以吗", "from": "Ann", "link": "", "urgency": "normal", "key": "Ann|私信：周会改到四点可以吗"}


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


@pytest.fixture
def repo(tmp_path):
    folder = tmp_path / "repo"
    (folder / ".git").mkdir(parents=True)
    return folder


def _slack_service(tmp_path, repo, fakes: _Fakes, *, active=True, now=NOW) -> WorkNotesService:
    config = Config(base=tmp_path / "cfg")
    config.set(wn.CONFIG_KEY, {"enabled": True, "repo_dir": str(repo), "model": "sonnet"})
    return WorkNotesService(config, folder=wn.SLACK_DIR, label="slack", summarize=fakes.summarize, sync=fakes.sync,
                            pull=fakes.pull, spawn=lambda run: run(), now=lambda: now, active=lambda idle_s: active,
                            opener=fakes.open)


# ---------------------------------------------------------------- 一条 Slack 消息 → 一条笔记

def test_a_slack_item_becomes_a_note_in_the_slack_folder():
    note = wn.note_from_slack_item(URGENT, NOW)
    assert note.name.startswith("2026-10-20-1030-") and note.kind == "slack" and note.status == "open"
    assert note.title == "问你发布窗口定了没" and note.links == [URGENT["link"]]
    assert note.tags == [wn.SLACK_TAG, "urgent"] and note.remind_at == "" and note.summary == ""
    assert "#release" in note.original and URGENT["link"] in note.original
    plain = wn.note_from_slack_item(PLAIN, NOW)
    assert plain.tags == [wn.SLACK_TAG] and plain.links == [] and "Ann" in plain.original
    assert wn.notes_dir({"repo_dir": "C:\\r"}, wn.SLACK_DIR) == wn.notes_dir({"repo_dir": "C:\\r"}).parent / "slack"
    assert wn.SLACK_DIR in wn.SYNC_PATHS and wn.NOTES_DIR in wn.SYNC_PATHS, "slack/ 和 note/ 一起提交"
    assert "'slack'" in wn.sync_command("C:\\r", "m")


def test_the_service_stores_fresh_items_once_and_pushes_them_together(tmp_path, repo):
    fakes = _Fakes()
    service = _slack_service(tmp_path, repo, fakes)
    made = service.add_slack_items([URGENT, PLAIN, dict(URGENT)])
    assert [n.title for n in made] == ["问你发布窗口定了没", "私信：周会改到四点可以吗"], "同一批里重复的链接只存一次"
    files = sorted(p.name for p in (repo / "slack").glob("*.md"))
    assert len(files) == 2 and all(name.startswith("2026-10-20-1030-") for name in files)
    assert (repo / "note").exists() is False, "笔记目录不受影响"
    assert fakes.syncs == ["slack: 2 条"] and fakes.summaries == [], "不让 Claude 再读一遍，只是存起来"
    again = service.add_slack_items([URGENT, {**PLAIN, "title": "私信：周会改到四点可以吗"}])
    assert again == [] and fakes.syncs == ["slack: 2 条"], "下次查到同样的链接 / 同一条，不再存、不再推"
    service._now = lambda: NOW + dt.timedelta(minutes=5)
    third = service.add_slack_items([{**PLAIN, "title": "问你发布窗口定了没", "key": "Ann|问你发布窗口定了没"}])
    assert len(third) == 1 and third[0].name == "2026-10-20-1035-问你发布窗口定了没"
    assert [n.title for n in service.notes()][0] == "问你发布窗口定了没", "最新的在最前"
    assert service.notes()[0].created == "2026-10-20T10:35:00"


def test_same_minute_same_title_does_not_overwrite(tmp_path, repo):
    service = _slack_service(tmp_path, repo, _Fakes())
    first = service.add_slack_items([{**PLAIN, "key": "k1"}])
    second = service.add_slack_items([{**PLAIN, "from": "Bob", "key": "k2"}])
    assert first[0].name != second[0].name and second[0].name.endswith("-2")
    assert len(service.notes()) == 2


# ---------------------------------------------------------------- 稍后 → 到点再冒一次气泡

def test_snoozing_a_slack_item_brings_the_fish_back_with_view_snooze_done(tmp_path, repo):
    """用户 2026-10-20 问：稍后 X 小时，到点时大肥鱼会再次冒气泡提醒我吧？——会。"""
    fakes = _Fakes()
    service = _slack_service(tmp_path, repo, fakes)
    host = _Host()
    opened = []
    controller = WorkNotesController(host, service, colors=_COLORS, open_window=lambda: opened.append(1), slack=True)
    note, = service.add_slack_items([URGENT])
    assert service.check_reminders() == [], "刚存的不提醒（总提醒已经冒过一次）"
    service.snooze(note.name, 180)
    assert service.note(note.name).remind_at == "2026-10-20T13:30:00"
    service._now = lambda: NOW + dt.timedelta(hours=2)
    assert service.check_reminders() == [], "还没到点"
    service._now = lambda: NOW + dt.timedelta(hours=3, minutes=1)
    assert len(service.check_reminders()) == 1
    (text, kw), = host.alerts
    assert text == "问你发布窗口定了没" and kw["alert_id"] == SLACK_ALERT_PREFIX + note.name and kw["sticky"]
    assert kw["subtitle"] == "Slack 关注 · 问你发布窗口定了没" and kw["alert_type"] == "slack_watch"
    buttons = dict(kw["buttons"])
    assert list(buttons) == ["查看", "稍后 1 小时", "完成"]
    buttons["查看"]()
    assert fakes.opened == [URGENT["link"]] and opened == [], "有链接：查看 = 直接开那条 Slack 消息"
    assert host.resolved == [kw["alert_id"]]
    buttons["稍后 1 小时"]()
    assert service.note(note.name).remind_at == "2026-10-20T14:31:00"
    buttons["完成"]()
    assert service.note(note.name).status == "done" and service.note(note.name).remind_at == ""
    assert service.check_reminders() == [], "完成了就不再提醒"
    assert fakes.syncs[-3:] == ["slack: 稍后再提醒", "slack: 稍后再提醒", "slack: 完成"]


def test_viewing_an_item_without_a_link_opens_the_tab_instead(tmp_path, repo):
    fakes = _Fakes()
    service = _slack_service(tmp_path, repo, fakes)
    host = _Host()
    opened = []
    controller = WorkNotesController(host, service, colors=_COLORS, open_window=lambda: opened.append(1), slack=True)
    note, = service.add_slack_items([PLAIN])
    controller.view(note.name)
    assert fakes.opened == [] and opened == [1]
    assert controller.panel().current_name() == note.name


# ---------------------------------------------------------------- 「Slack 关注」页

def test_the_slack_page_has_no_input_but_a_view_button(tmp_path, repo):
    fakes = _Fakes()
    service = _slack_service(tmp_path, repo, fakes)
    controller = WorkNotesController(_Host(), service, colors=_COLORS, slack=True)
    panel = controller.panel()
    assert panel.input.isHidden() and panel.add_btn.isHidden() and not panel.view_btn.isHidden()
    assert panel.view_btn.text() == "查看" and "Slack 关注" in panel.hint_label.text()
    assert not panel.view_btn.isEnabled(), "没选中就不能点"
    service.add_slack_items([PLAIN, URGENT])
    service._now = lambda: NOW + dt.timedelta(minutes=1)
    service.add_slack_items([{**PLAIN, "title": "新来的一条", "key": "k3"}])
    assert [panel.list.item(i).text() for i in range(3)] == ["○ 新来的一条", "○ 问你发布窗口定了没", "○ 私信：周会改到四点可以吗"]
    panel.select(service.notes()[1].name)
    assert panel.view_btn.isEnabled()
    panel.view_btn.click()
    assert fakes.opened == [URGENT["link"]]
    assert "`urgent`" in panel.detail.toMarkdown() or "urgent" in panel.detail.toPlainText()


def test_the_slack_page_speaks_english(tmp_path, repo):
    service = _slack_service(tmp_path, repo, _Fakes())
    service._config.set("ui_language", "en")
    panel = WorkNotesController(_Host(), service, colors=_COLORS, slack=True).panel()
    assert panel.view_btn.text() == "Open" and "Slack Watch" in panel.hint_label.text()
    zh, en = i18n.table("zh"), i18n.table("en")
    keys = [k for k in zh if k.startswith("slack.notes.")]
    assert len(keys) >= 5 and all(k in en for k in keys)


# ---------------------------------------------------------------- 总提醒多一个「稍后 1 小时」，查看开到那一页

def test_new_items_are_archived_and_the_alert_can_snooze_them_all(tmp_path, repo):
    fakes = _Fakes()
    notes_service = _slack_service(tmp_path, repo, fakes)
    host = _Host()
    opened = []
    notes = WorkNotesController(host, notes_service, colors=_COLORS, open_window=lambda: opened.append(1), slack=True)
    config = notes_service._config
    config.set(sw.CONFIG_KEY, {"enabled": True, "interval_minutes": 15, "idle_minutes": 10, "model": "sonnet"})
    watch = SlackWatchService(config, generate=lambda when, since, model, **_kw: sw.parse_output(_claude_json()),
                              spawn=lambda run: run(), now=lambda: NOW, active=lambda idle_s: True)
    SlackWatchController(host, watch, notes=notes)
    watch.check()
    app.processEvents()
    stored = notes_service.notes()
    assert [n.title for n in stored] == [item["title"] for item in ITEMS], "两条都存进 slack/ 了"
    (text, kw), = host.alerts
    assert kw["alert_id"] == ALERT_ID
    buttons = dict(kw["buttons"])
    assert list(buttons) == ["查看", "稍后 1 小时", "知道了"]
    buttons["稍后 1 小时"]()
    assert all(n.remind_at == "2026-10-20T11:30:00" for n in notes_service.notes()) and host.resolved == [ALERT_ID]
    buttons["查看"]()
    assert opened == [1] and notes.panel().current_name() == stored[0].name
    # 下次查到同样两条：不是新的 → 不提醒也不重复存
    watch._generation += 0
    watch.check_now()
    app.processEvents()
    assert len(host.alerts) == 1 and len(notes_service.notes()) == 2


def test_without_the_notes_service_the_alert_is_as_before(tmp_path):
    from tests.test_slack_watch import FakeHost, _service

    service, _made = _service(tmp_path)
    host = FakeHost()
    SlackWatchController(host, service)
    service.check()
    app.processEvents()
    (_text, kw), = host.alerts
    assert [label for label, _cb in kw["buttons"]] == ["查看", "知道了"]


# ---------------------------------------------------------------- 接线

def test_the_app_mounts_the_slack_page_when_notes_are_enabled(tmp_path, monkeypatch):
    from pet.app import AppShell

    config = Config(base=tmp_path / "cfg")
    config.set(wn.CONFIG_KEY, {"enabled": True, "repo_dir": str(tmp_path / "repo"), "model": "sonnet"})
    monkeypatch.setattr(ch, "wsl_exe", lambda: "wsl.exe")

    class _Briefing:
        tab_providers: list = []

        def open_window(self, tab=""):
            pass

    class _Shell:
        pass

    fake = type("A", (), {})()
    fake.config, fake.app, fake._overlay_shell, fake._work_briefing = config, app, _Shell(), _Briefing()
    fake._start_slack_notes = lambda: AppShell._start_slack_notes(fake)
    AppShell._start_slack_watch(fake)
    try:
        assert fake._slack_watch is not None and fake._slack_notes is not None
        assert fake._slack_watch._notes is fake._slack_notes
        assert fake._slack_notes.service.notes_dir() == tmp_path / "repo" / "slack"
        assert len(_Briefing.tab_providers) == 1
        label, widget = _Briefing.tab_providers[0]()[0]
        assert label == "Slack 关注" and widget.input.isHidden()
    finally:
        fake._slack_notes.service.stop()
        fake._slack_watch.service.stop()

    config.set(wn.CONFIG_KEY, {"enabled": False, "repo_dir": str(tmp_path / "repo"), "model": "sonnet"})
    other = type("A", (), {})()
    other.config, other.app, other._overlay_shell, other._work_briefing = config, app, _Shell(), _Briefing()
    other._start_slack_notes = lambda: AppShell._start_slack_notes(other)
    _Briefing.tab_providers.clear()
    AppShell._start_slack_watch(other)
    try:
        assert getattr(other, "_slack_notes", None) is None and other._slack_watch._notes is None
        assert _Briefing.tab_providers == []
    finally:
        other._slack_watch.service.stop()
