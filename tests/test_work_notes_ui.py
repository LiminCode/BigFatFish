# -*- coding: utf-8 -*-
"""工作笔记的 Qt 侧：服务（线程 / 定时 / git）、提醒气泡、菜单入口。看、记、处理的页面在浏览器里（test_panorama_notes*）。

纪律：不起真的 wsl.exe、不碰真实数据目录、不真的打开 Obsidian。总结 / git 都用同步的假函数。
"""
from __future__ import annotations

import datetime as dt
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import claude_hooks as ch
from pet import work_notes as wn
from pet.config import Config
from pet.work_notes_service import WorkNotesService
from pet.work_notes_ui import ALERT_PREFIX, WorkNotesController
from tests.test_session_pet_details import shell  # noqa: F401 - shell 是 fixture
from tests.test_work_briefing import _find, briefing_shell  # noqa: F401 - fixture

app = QApplication.instance() or QApplication([])

NOW = dt.datetime(2026, 10, 15, 19, 40)
SLACK = "https://acme.slack.com/archives/C1/p1"


class _Fakes:
    """总结 / git / 打开 的替身：都同步跑，记下参数。"""

    def __init__(self, *, ok=True, remind_at="2026-10-16T09:00:00", git_ok=True, fail_first=0):
        self.summaries: list[str] = []
        self.syncs: list[str] = []
        self.pulls = 0
        self.opened: list[str] = []
        self.ok, self.remind_at, self.git_ok = ok, remind_at, git_ok
        self.fail_first = fail_first   # 前几次总结故意失败（模型偶尔不按约定输出）

    def summarize(self, note, now, model, **_kw):   # 服务会多传 effort / template
        self.summaries.append(note.name)
        if self.fail_first > 0:
            self.fail_first -= 1
            return wn.SummaryResult(error="Claude Code 的回答不是约定的 JSON：…")
        if not self.ok:
            return wn.SummaryResult(error="Slack 读不到")
        return wn.SummaryResult(ok=True, summary=f"摘要：{note.title}", details="- 要点", remind_at=self.remind_at,
                                reason="明早看", tags=["slack"], seconds=3.0)

    def sync(self, settings, message):
        self.syncs.append(message)
        return (True, "") if self.git_ok else (False, "fatal: could not read from remote")

    def pull(self, settings):
        self.pulls += 1
        return True, ""

    def open(self, target):
        self.opened.append(target)
        return True


@pytest.fixture
def repo(tmp_path):
    folder = tmp_path / "repo"
    (folder / ".git").mkdir(parents=True)
    return folder


def _service(tmp_path, repo, fakes: _Fakes, *, active=True, now=NOW):
    config = Config(base=tmp_path / "cfg")
    config.set(wn.CONFIG_KEY, {"enabled": True, "repo_dir": str(repo), "model": "sonnet"})
    return WorkNotesService(config, summarize=fakes.summarize, sync=fakes.sync, pull=fakes.pull,
                            spawn=lambda run: run(), now=lambda: now, active=lambda idle_s: active,
                            opener=fakes.open)


# ---------------------------------------------------------------- 服务
def test_adding_a_note_writes_the_file_summarizes_in_the_background_and_pushes(tmp_path, repo):
    fakes = _Fakes()
    service = _service(tmp_path, repo, fakes)
    changes, summarized, synced = [], [], []
    service.changed.connect(lambda: changes.append(1))
    service.summarized.connect(lambda *a: summarized.append(a))
    service.synced.connect(lambda *a: synced.append(a))

    note = service.add(f"{SLACK}\n老板说今天看")
    assert note is not None and (repo / "note" / note.filename).exists()
    saved = service.note(note.name)
    assert saved.original == f"{SLACK}\n老板说今天看" and saved.summary == "摘要：老板说今天看"
    assert saved.remind_at == "2026-10-16T09:00:00" and "slack" in saved.tags
    assert fakes.summaries == [note.name] and fakes.syncs == ["note: 记一条", "note: 总结"], "原文先推、总结完再推"
    assert summarized == [(note.name, True, "")] and synced == [(True, ""), (True, "")]
    assert service.busy_names == frozenset() and service.last_error() == ""
    assert len(changes) >= 3, "落盘、开始总结、总结完各发一次"


def test_blank_text_is_not_a_note(tmp_path, repo):
    assert _service(tmp_path, repo, _Fakes()).add("   \n") is None


def test_a_failed_summary_keeps_the_note_and_reports_the_reason(tmp_path, repo):
    fakes = _Fakes(ok=False)
    service = _service(tmp_path, repo, fakes)
    reports = []
    service.summarized.connect(lambda *a: reports.append(a))
    note = service.add("看一下")
    saved = service.note(note.name)
    assert saved.summary == "" and saved.original == "看一下"
    assert reports == [(note.name, False, "Slack 读不到")]
    assert fakes.summaries == [note.name, note.name], "失败自动再试一次，再失败才报"
    assert fakes.syncs == ["note: 记一条"], "原文照样推上去，只是没有总结那一次"
    assert service.last_error() == "Slack 读不到"


def test_a_flaky_first_answer_is_retried_once_and_then_saved(tmp_path, repo):
    """2026-10-15 用户的第二条真实笔记：第一次 91 秒 5 轮失败，同一条再跑一次就成了。"""
    fakes = _Fakes(fail_first=1)
    service = _service(tmp_path, repo, fakes)
    reports = []
    service.summarized.connect(lambda *a: reports.append(a))
    note = service.add("看一下")
    assert fakes.summaries == [note.name, note.name]
    assert service.note(note.name).summary == "摘要：看一下"
    assert reports == [(note.name, True, "")], "中间那次失败不打扰用户"
    assert fakes.syncs == ["note: 记一条", "note: 总结"]


def test_a_missing_wsl_is_not_retried(tmp_path, repo):
    fakes = _Fakes()
    fakes.summarize = lambda note, now, model, **_kw: (fakes.summaries.append(note.name),
                                               wn.SummaryResult(error="没有找到 WSL：…"))[1]
    service = _service(tmp_path, repo, fakes)
    note = service.add("x")
    assert fakes.summaries == [note.name]


def test_git_failures_surface_in_last_error(tmp_path, repo):
    fakes = _Fakes(git_ok=False)
    service = _service(tmp_path, repo, fakes)
    service.add("x")
    assert "could not read" in service.last_error()


def test_snooze_and_done_rewrite_the_file_and_push(tmp_path, repo):
    fakes = _Fakes()
    service = _service(tmp_path, repo, fakes)
    note = service.add("x")
    later = service.snooze(note.name, 60)
    assert later.remind_at == "2026-10-15T20:40:00" and service.note(note.name).remind_at == "2026-10-15T20:40:00"
    done = service.mark_done(note.name)
    assert done.status == "done" and service.note(note.name).status == "done"
    assert fakes.syncs == ["note: 记一条", "note: 总结", "note: 稍后再提醒", "note: 完成"]
    assert service.snooze("nope", 60) is None and service.mark_done("nope") is None


def test_reminders_fire_once_per_time_and_only_when_someone_is_there(tmp_path, repo):
    fakes = _Fakes(remind_at="2026-10-15T19:50:00")
    service = _service(tmp_path, repo, fakes)
    due = []
    service.reminder_due.connect(lambda note: due.append(note.name))
    note = service.add("x")
    assert service.check_reminders() == [] and due == [], "还没到点"

    service._now = lambda: dt.datetime(2026, 10, 15, 19, 55)
    service._active = lambda idle_s: False
    assert service.check_reminders() == [] and due == [], "人不在不提醒"
    service._active = lambda idle_s: True
    assert [n.name for n in service.check_reminders()] == [note.name] and due == [note.name]
    assert service.check_reminders() == [] and due == [note.name], "同一个时间点只提醒一次"
    assert wn.load_state(service._config.dir)["alerted"] == {note.name: "2026-10-15T19:50:00"}

    service.snooze(note.name, 5)
    service._now = lambda: dt.datetime(2026, 10, 15, 20, 1)
    assert [n.name for n in service.check_reminders()] == [note.name], "稍后之后到点再提醒一次"


def test_open_in_obsidian_falls_back_to_the_folder_when_the_vault_is_not_registered(tmp_path, repo, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "no-obsidian"))
    fakes = _Fakes()
    service = _service(tmp_path, repo, fakes)
    note = service.add("x")
    assert service.open_in_obsidian(note.name) is False
    assert fakes.opened == [str(repo / "note")]
    monkeypatch.setattr(wn, "obsidian_vaults", lambda *a, **k: {"v": {"path": str(repo)}})
    assert service.open_in_obsidian(note.name) is True
    assert fakes.opened[-1].startswith("obsidian://open?vault=repo&file=note%2F")


def test_the_repo_must_exist_for_git_but_not_for_writing(tmp_path):
    fakes = _Fakes()
    service = _service(tmp_path, tmp_path / "missing", fakes)
    assert not service.repo_ready()
    note = service.add("x")
    assert note is not None and (tmp_path / "missing" / "note" / note.filename).exists()


class _Host:
    def __init__(self):
        self.bubbles, self.alerts, self.resolved = [], [], []

    def show_bubble(self, text, ms=0, **_):
        self.bubbles.append(text)

    def show_alert(self, text, **kw):
        self.alerts.append((text, kw))

    def resolve_alert(self, alert_id):
        self.resolved.append(alert_id)


def test_a_due_reminder_becomes_a_sticky_alert_with_view_snooze_and_done(tmp_path, repo):
    fakes = _Fakes(remind_at="2026-10-15T19:50:00")
    service = _service(tmp_path, repo, fakes)
    host = _Host()
    opened = []
    controller = WorkNotesController(host, service, open_report=lambda name: (opened.append(name), True)[1])
    note = service.add("x")
    service._now = lambda: dt.datetime(2026, 10, 15, 19, 55)
    service.check_reminders()
    (text, kw), = host.alerts
    assert text == "摘要：x" and kw["alert_id"] == ALERT_PREFIX + note.name and kw["sticky"] and kw["priority"] == 1
    buttons = dict(kw["buttons"])
    assert list(buttons) == ["查看", "稍后 1 小时", "完成"]
    buttons["查看"]()
    assert opened == [note.name] and host.resolved == [kw["alert_id"]], "「查看」开浏览器里的笔记页并选中它"
    buttons["稍后 1 小时"]()
    assert service.note(note.name).remind_at == "2026-10-15T20:55:00"
    buttons["完成"]()
    assert service.note(note.name).status == "done"


def test_a_failed_summary_is_said_in_a_bubble(tmp_path, repo):
    host = _Host()
    service = _service(tmp_path, repo, _Fakes(ok=False))
    WorkNotesController(host, service)
    service.add("x")
    assert any("没总结出来" in text for text in host.bubbles)


def test_delete_removes_the_file_and_pushes(tmp_path, repo):
    """用户 2026-10-15：notes 要能删。删前问一句现在在页面上（confirm，test_panorama_notes_page）；服务这一层：文件没了、推一次。"""
    fakes = _Fakes()
    service = _service(tmp_path, repo, fakes)
    note = service.add("要删的")
    path = repo / "note" / note.filename
    assert path.exists()
    assert service.delete(note.name) is not None
    assert not path.exists() and fakes.syncs[-1] == "note: 删除" and service.notes() == []
    assert service.delete("nope") is None


# ---------------------------------------------------------------- 开浏览器里的笔记页
def test_open_notes_goes_to_the_browser_page_and_only_says_so_when_it_cannot(tmp_path, repo):
    """2026-11-20 起笔记在浏览器里看（配置全景的笔记页）：open_report(name) 开它；Qt 的「笔记」页 11-21 删了，本机服务起不来只冒一句气泡。"""
    service = _service(tmp_path, repo, _Fakes())
    host, opened, can = _Host(), [], {"ok": True}
    notes = WorkNotesController(host, service, open_report=lambda name: (opened.append(name), can["ok"])[1])
    notes.open_notes("2026-11-20-1200-x")
    notes.open_notes()
    assert opened == ["2026-11-20-1200-x", ""] and host.bubbles == []
    can["ok"] = False
    notes.open_notes()
    assert opened[-1] == "" and host.bubbles == ["笔记页打不开：本机服务起不来，看日志里「配置全景」那几行"]
    WorkNotesController(host, service).open_notes()
    assert len(host.bubbles) == 2, "没接页面（旧接线、测试）：也只能这么说"
    WorkNotesController(host, service, slack=True).open_notes()
    assert host.bubbles[-1].startswith("Slack 关注页打不开")


def test_notes_speak_english_when_the_ui_language_is_english(tmp_path, repo):
    """用户 2026-10-15：新功能要支持中英文（界面语言已经能切）。页面上的字见 test_panorama_notes；这里是服务写进文件的字和提示词。"""
    from pet import i18n

    service = _service(tmp_path, repo, _Fakes(remind_at="2026-10-16T09:00:00"))
    service._config.set("ui_language", "en")   # 和真实路径一样：语言由 Config 设置
    try:
        assert i18n.current_language() == "en"
        note = service.add("look at this")
        later = service.snooze(note.name, 60)
        assert later.reason == "Snoozed: remind again in 60 min"
        prompt = wn.build_prompt(later, NOW)
        assert prompt.startswith("You are my work-notes assistant") and "write everything in English" in prompt, \
            "2026-10-19 起英文界面用整套英文提示词，不只是「用 English 写」一句"
    finally:
        i18n.set_language("zh")


def test_the_menu_offers_the_notes_page_under_the_briefing(briefing_shell, tmp_path, repo):  # noqa: F811
    service = _service(tmp_path, repo, _Fakes())
    opened = []
    briefing_shell.work_notes = WorkNotesController(briefing_shell, service,
                                                    open_report=lambda name: (opened.append(name), True)[1])
    menu = briefing_shell._build_menu_for(briefing_shell.sprite)
    entry = _find(menu, "工作笔记")
    assert entry is not None
    agent_link = _find(menu, "Agent 联动").menu()
    assert entry in agent_link.actions(), "用户 2026-10-15：直接放在 Agent 联动 这一层，不藏在 工作简报 里"
    assert _find(_find(agent_link, "工作简报").menu(), "工作笔记") is None
    entry.trigger()
    assert opened == [""], "菜单项开的是浏览器里的笔记页"


def test_without_the_notes_service_the_menu_is_unchanged(briefing_shell):  # noqa: F811
    menu = briefing_shell._build_menu_for(briefing_shell.sprite)
    assert _find(menu, "工作笔记") is None


def test_every_notes_string_has_both_languages():
    from pet import i18n

    zh, en = i18n.table("zh"), i18n.table("en")
    keys = [k for k in zh if k.startswith("notes.")]
    assert len(keys) >= 30 and all(k in en for k in keys)
    for key, _minutes in wn.SNOOZE_CHOICES:
        assert key in zh and key in en


def test_the_app_wires_notes_only_when_enabled(tmp_path, monkeypatch):
    """接线函数本身：开关关着不建；开着就建控制器、挂到壳上，不再往简报窗口挂页（笔记在浏览器里看）。"""
    from pet.app import AppShell

    config = Config(base=tmp_path / "cfg")
    config.set(wn.CONFIG_KEY, {"enabled": False, "repo_dir": str(tmp_path), "model": "sonnet"})

    class _Briefing:
        pass

    class _Shell:
        pass

    fake = type("A", (), {})()
    fake.config, fake.app, fake._overlay_shell, fake._work_briefing = config, app, _Shell(), _Briefing()
    fake._open_report, fake._publish_report = lambda name, note="": True, lambda name: None
    AppShell._start_work_notes(fake)
    assert getattr(fake, "_work_notes", None) is None

    config.set(wn.CONFIG_KEY, {"enabled": True, "repo_dir": str(tmp_path), "model": "sonnet"})
    monkeypatch.setattr(ch, "wsl_exe", lambda: "wsl.exe")
    AppShell._start_work_notes(fake)
    assert fake._work_notes is not None and fake._overlay_shell.work_notes is fake._work_notes
    assert fake._work_notes._open_report is not None
    fake._work_notes.service.stop()
