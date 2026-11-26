# -*- coding: utf-8 -*-
"""个人助理的 Qt 侧：服务（定时 / 线程 / git 锁）、提醒、岛状态、「在 Obsidian 打开」。页面（简报、随手记输入区）在浏览器里，
见 test_personal_report_page。

纪律：不调 Anthropic、不起 git、不打开 Obsidian——全部用同步的假函数；样例文字中性。
"""
from __future__ import annotations

import datetime as dt
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet import personal_briefing as pb
from pet import personal_vault as pv
from pet.config import Config
from pet.personal_service import PersonalService
from pet.personal_ui import ALERT_ID, PersonalController

app = QApplication.instance() or QApplication([])

NOW = dt.datetime(2026, 10, 17, 9, 0)      # 星期六 09:00（默认 08:30 已过）
REPORT = "概要：先补周五的扫描。\n\n## 待复习\n- 风险观察（到期 09-20）\n\n## 今天\n无\n"


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


class _Fakes:
    """生成 / pull / sync / 打开 的替身：同步跑，记下参数与顺序。"""

    def __init__(self, *, ok=True, pull_ok=True, sync_ok=True, open_ok=True):
        self.order: list[str] = []
        self.generated: list[tuple] = []
        self.syncs: list[tuple] = []
        self.opened: list[str] = []
        self.ok, self.pull_ok, self.sync_ok, self.open_ok = ok, pull_ok, sync_ok, open_ok

    def generate(self, now, settings, provider, *, pull_note=""):
        self.order.append("generate")
        self.generated.append((now, settings, provider, pull_note))
        if not self.ok:
            return pb.PersonalBriefing(error="认证失败：API Key 无效或已失效", model=settings["model"] or provider.model)
        summary, markdown = pb.parse_text(REPORT)
        return pb.PersonalBriefing(ok=True, summary=summary, markdown=markdown, generated_at=now.isoformat(), seconds=63.4,
                                   turns=6, model="claude-sonnet-5-20260101", effort=settings["effort"] or provider.effort,
                                   tokens_in=48210, tokens_out=1130, files_read=["INDEX.md", "5-Daily/2026-10-17.md"],
                                   pull_note=pull_note)

    def pull(self, repo_dir, *, token=""):
        self.order.append("pull")
        return (True, "") if self.pull_ok else (False, "fatal: unable to access remote")

    def sync(self, repo_dir, paths, now, *, token=""):
        self.order.append("sync")
        self.syncs.append((repo_dir, list(paths), now, token))
        return (True, "") if self.sync_ok else (False, "remote: Permission denied\n[token scopes: repo]")

    def open(self, target):
        self.opened.append(target)
        return self.open_ok


class _Host:
    def __init__(self):
        self.bubbles, self.alerts, self.resolved = [], [], []

    def show_bubble(self, text, ms=0, **_):
        self.bubbles.append(text)

    def show_alert(self, text, **kw):
        self.alerts.append((text, kw))

    def resolve_alert(self, alert_id):
        self.resolved.append(alert_id)


class _Provider:
    model, effort, api_key, base_url, api_format = "claude-sonnet-5", "medium", "k", "https://api.anthropic.com", "auto"


@pytest.fixture
def clone(tmp_path):
    folder = tmp_path / "AI-Base"
    (folder / ".git").mkdir(parents=True)
    (folder / "INDEX.md").write_text("# map\n", encoding="utf-8")
    return folder


def _service(tmp_path, clone, fakes: _Fakes, *, now=NOW, enabled=True, **settings):
    config = Config(base=tmp_path / "cfg")
    config.set(pv.CONFIG_KEY, {"enabled": enabled, "repo_dir": str(clone), "time": "08:30", **settings})
    service = PersonalService(config, generate=fakes.generate, pull=fakes.pull, sync=fakes.sync,
                              spawn=lambda run: run(), now=lambda: now, opener=fakes.open,
                              token=lambda: "ghp_test", provider=lambda: _Provider())
    return service


# ---------------------------------------------------------------- 服务：简报
def test_the_service_pulls_first_then_generates_with_the_chat_provider_and_records_usage(tmp_path, clone):
    fakes = _Fakes()
    service = _service(tmp_path, clone, fakes, effort="high")
    finished = []
    service.finished.connect(lambda briefing, manual: finished.append((briefing, manual)))
    assert service.check() is True
    app.processEvents()
    assert fakes.order == ["pull", "generate"], "先拉远端再读"
    (when, settings, provider, pull_note), = fakes.generated
    assert when == NOW and settings["repo_dir"] == str(clone) and provider.api_key == "k" and pull_note == ""
    [(briefing, manual)] = finished
    assert briefing.ok and manual is False and briefing.tokens_in == 48210 and briefing.effort == "high"
    assert service.latest() == briefing and not service.busy and service.check() is False, "一天一次"
    assert service.busy_model == "claude-sonnet-5" and service.busy_effort == "high"


def test_a_failed_pull_is_noted_but_the_briefing_still_runs_on_the_local_copy(tmp_path, clone):
    fakes = _Fakes(pull_ok=False)
    service = _service(tmp_path, clone, fakes)
    assert service.generate_now() is True
    app.processEvents()
    assert fakes.generated[0][3] == "fatal: unable to access remote" and service.latest().pull_note.startswith("fatal")


def test_without_a_claude_provider_the_service_reports_instead_of_crashing(tmp_path, clone):
    service = _service(tmp_path, clone, _Fakes())

    def no_chat():
        raise ImportError("no anthropic")

    service._provider = no_chat
    finished = []
    service.finished.connect(lambda b, m: finished.append(b))
    assert service.generate_now() is False
    assert finished and "Claude" in finished[0].error and "ImportError" in finished[0].error
    assert "Claude" in service.last_error() and service.latest() is None


# ---------------------------------------------------------------- 服务：随手记
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8


def test_a_capture_is_written_to_the_inbox_then_committed_and_pushed_with_the_token(tmp_path, clone):
    fakes = _Fakes()
    service = _service(tmp_path, clone, fakes)
    saved, synced, changes = [], [], []
    service.capture_saved.connect(saved.append)
    service.synced.connect(lambda *a: synced.append(a))
    service.changed.connect(lambda: changes.append(service.sync_state))
    note = service.add_capture("把阳台的灯换成感应的", [(".png", PNG)])
    assert note == "0-Inbox/2026-10-17 0900 把阳台的灯换成感应的.md"
    assert "把阳台的灯换成感应的\n\n![[assets/" in (clone / note).read_text(encoding="utf-8")
    assert saved == [note] and service.last_capture == note
    assert fakes.syncs == [(str(clone), [note, "0-Inbox/assets/2026-10-17 0900 把阳台的灯换成感应的-1.png"], NOW, "ghp_test")]
    assert synced == [(True, "")] and changes == ["pushing", "pushed"] and service.pushed_at == "09:00"
    assert service.add_capture("   ") is None, "空的不记"
    assert service.add_capture("", [(".png", PNG)]) == "0-Inbox/2026-10-17 0900 截图.md", "只有图也记"


def test_a_failed_push_keeps_the_file_and_says_why(tmp_path, clone):
    fakes = _Fakes(sync_ok=False)
    service = _service(tmp_path, clone, fakes)
    note = service.add_capture("x")
    assert note is not None and (clone / note).exists()
    assert service.sync_state == "failed" and "token scopes: repo" in service.sync_error


def test_without_a_clone_nothing_is_written(tmp_path):
    service = _service(tmp_path, tmp_path / "missing", _Fakes())
    assert service.add_capture("x") is None
    assert service.sync_state == "failed" and "missing" in service.sync_error and not service.repo_ready()


# ---------------------------------------------------------------- 提醒与岛
def test_a_finished_briefing_is_an_alert_whose_view_opens_the_browser_page(tmp_path, clone):
    service = _service(tmp_path, clone, _Fakes(), model="claude-haiku-5-5", effort="low")
    host, opened = _Host(), []
    controller = PersonalController(host, service, open_report=lambda: (opened.append(1), True)[1])
    states = []
    controller.state_changed.connect(states.append)
    service.generate_now()
    app.processEvents()
    (text, kwargs), = host.alerts
    assert text == "先补周五的扫描。" and kwargs["alert_id"] == ALERT_ID and kwargs["alert_type"] == "personal_briefing"
    assert [label for label, _cb in kwargs["buttons"]] == ["查看", "知道了"] and states == ["unread"]
    dict(kwargs["buttons"])["查看"]()
    assert host.resolved == [ALERT_ID] and opened == [1] and states == ["unread", "idle"]


def test_island_state_is_hidden_until_enabled_or_generated(tmp_path, clone):
    service = _service(tmp_path, clone, _Fakes(), enabled=False)
    controller = PersonalController(_Host(), service, open_report=lambda: True)
    assert controller.island_state == "hidden"
    service.generate_now()
    app.processEvents()
    assert controller.island_state == "unread"
    controller.open_window()
    assert controller.island_state == "idle"
    assert PersonalController(_Host(), _service(tmp_path / "b", clone, _Fakes())).island_state == "idle"


def test_a_failed_briefing_is_a_bubble_not_an_alert(tmp_path, clone):
    service = _service(tmp_path, clone, _Fakes(ok=False))
    host = _Host()
    PersonalController(host, service)
    service.generate_now()
    app.processEvents()
    assert host.alerts == [] and host.bubbles and "认证失败" in host.bubbles[-1]


# ---------------------------------------------------------------- Obsidian
def test_open_in_obsidian_falls_back_to_the_folder_with_a_hint_until_the_vault_is_registered(tmp_path, clone, monkeypatch):
    fakes = _Fakes()
    service = _service(tmp_path, clone, fakes)
    host = _Host()
    controller = PersonalController(host, service)
    monkeypatch.setattr(pv.wn, "obsidian_vaults", lambda: {"x": {"path": r"G:\My Drive\AI-Base"}})
    controller.open_obsidian()
    assert fakes.opened == [str(clone)] and "Open folder as vault" in host.bubbles[-1] and str(clone) in host.bubbles[-1]
    monkeypatch.setattr(pv.wn, "obsidian_vaults", lambda: {"x": {"path": str(clone)}})
    controller.open_obsidian()
    assert fakes.opened[-1].startswith("obsidian://open?path=") and len(host.bubbles) == 1
