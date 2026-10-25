# -*- coding: utf-8 -*-
"""Slack 关注：电脑在用时每隔几分钟让 WSL 里的 Claude Code 看一眼 Slack，有新的需要我管的就冒气泡。

守住的几条线：只放行 Slack 的读取类工具；锁屏 / 离开时不跑；同一条只提醒一次；什么新的都没有就安静；
失败只在手动时说。纪律：不起真的 wsl.exe、不碰真的桌面状态。
"""
from __future__ import annotations

import datetime as dt
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import slack_watch as sw
from pet.config import Config
from pet.slack_watch_service import SlackWatchService
from pet.slack_watch_ui import ALERT_ID, SlackWatchController

app = QApplication.instance() or QApplication([])

T0 = dt.datetime(2026, 10, 14, 14, 0)
ON = {"enabled": True, "interval_minutes": 15, "idle_minutes": 10, "model": "sonnet"}
ITEMS = [{"title": "问你发布窗口定了没", "from": "#release", "link": "https://x.slack.com/archives/C1/p1", "urgency": "high"},
         {"title": "私信：周会改到四点可以吗", "from": "Ann", "link": "", "urgency": "normal"}]


def _claude_json(payload=None, **over) -> str:
    text = json.dumps(payload if payload is not None else {"summary": "发布窗口在等你拍板", "items": ITEMS, "error": ""},
                      ensure_ascii=False)
    return json.dumps({"type": "result", "subtype": "success", "is_error": False, "num_turns": 5,
                       "result": text, "permission_denials": [], **over}, ensure_ascii=False)


# ---------------------------------------------------------------- 配置与节奏

def test_it_is_off_by_default_and_values_are_cleaned():
    assert sw.normalize(None) == {"enabled": False, "interval_minutes": 15, "idle_minutes": 10, "model": "sonnet"}
    out = sw.normalize({"enabled": True, "interval_minutes": 1, "idle_minutes": "abc", "model": "x; rm -rf"})
    assert out == {"enabled": True, "interval_minutes": 5, "idle_minutes": 10, "model": "sonnet"}
    assert sw.normalize({"enabled": "yes"})["enabled"] is False, "字符串布尔不算开"


def test_it_only_runs_when_switched_on_and_someone_is_at_the_computer():
    state = {"last_attempt": (T0 - dt.timedelta(minutes=20)).timestamp()}
    assert sw.is_due(ON, state, T0, active=True)
    assert not sw.is_due(ON, state, T0, active=False), "锁屏 / 离开了不跑"
    assert not sw.is_due({**ON, "enabled": False}, state, T0, active=True)
    assert not sw.is_due(ON, {"last_attempt": (T0 - dt.timedelta(minutes=14)).timestamp()}, T0, active=True)
    assert sw.is_due(ON, {}, T0, active=True), "从没查过：到了就查"


def test_repeated_failures_back_off_to_an_hour():
    state = {"last_attempt": (T0 - dt.timedelta(minutes=30)).timestamp(), "failures": 3}
    assert not sw.is_due(ON, state, T0, active=True)
    state["last_attempt"] = (T0 - dt.timedelta(minutes=61)).timestamp()
    assert sw.is_due(ON, state, T0, active=True)


def test_lookback_starts_at_the_last_success_but_never_more_than_a_day():
    assert sw.since_for({}, T0) == T0 - dt.timedelta(minutes=60)
    assert sw.since_for({"last_ok": (T0 - dt.timedelta(minutes=17)).isoformat()}, T0) == T0 - dt.timedelta(minutes=17)
    assert sw.since_for({"last_ok": (T0 - dt.timedelta(days=3)).isoformat()}, T0) == T0 - dt.timedelta(days=1)
    assert sw.since_for({"last_ok": "garbage"}, T0) == T0 - dt.timedelta(minutes=60)


def test_session_active_needs_an_unlocked_desktop_and_recent_input():
    assert sw.session_active(600, desktop=lambda: "Default", idle=lambda: 30.0)
    assert not sw.session_active(600, desktop=lambda: "Winlogon", idle=lambda: 1.0), "锁屏"
    assert not sw.session_active(600, desktop=lambda: "", idle=lambda: 1.0), "打不开输入桌面也算锁着"
    assert not sw.session_active(600, desktop=lambda: "Default", idle=lambda: 601.0), "离开太久"

    def boom():
        raise OSError("no user32")

    assert not sw.session_active(600, desktop=boom, idle=lambda: 0.0)


# ---------------------------------------------------------------- 命令与提示词

def test_only_slack_reading_tools_are_handed_over():
    allowed = sw.allowed_tools()
    assert allowed and all("slack" in name.lower() for name in allowed)
    assert all(not any(verb in name for verb in ("send", "schedule", "create", "update", "add_reaction")) for name in allowed)
    command = sw.claude_command("sonnet")
    assert "--tools ''" in command and "--output-format json" in command and "--no-session-persistence" in command
    assert "slack_send_message" in command.split("--disallowedTools", 1)[1]
    assert "atlassian" not in command.split("--allowedTools", 1)[1].split("--disallowedTools", 1)[0].lower()


def test_the_prompt_says_which_window_to_look_at():
    prompt = sw.build_prompt(T0, T0 - dt.timedelta(minutes=15))
    assert "2026-10-14 13:45" in prompt and "2026-10-14 14:00" in prompt and "只读" in prompt and '"items"' in prompt


# ---------------------------------------------------------------- 结果

def test_the_json_answer_becomes_items_with_keys():
    result = sw.parse_output("noise\n" + _claude_json())
    assert result.ok and result.summary == "发布窗口在等你拍板"
    assert [item["key"] for item in result.items] == ["https://x.slack.com/archives/C1/p1", "Ann|私信：周会改到四点可以吗"]
    assert result.items[0]["urgency"] == "high" and result.items[1]["urgency"] == "normal"
    assert "[打开](https://x.slack.com/archives/C1/p1)" in result.markdown and "**[急]**" in result.markdown


def test_fenced_or_chatty_json_is_still_read():
    payload = {"summary": "", "items": [{"title": "t", "from": "f", "link": "not a url", "urgency": "HIGH"}], "error": ""}
    result = sw.parse_output(json.dumps(
        {"type": "result", "subtype": "success", "result": "好的，结果如下：\n```json\n" + json.dumps(payload) + "\n```"}))
    assert result.ok and result.items[0]["link"] == "" and result.items[0]["urgency"] == "high"
    assert "没有需要你看的" not in result.markdown


@pytest.mark.parametrize("stdout, needle", [
    ("", "没有返回结果"),
    (json.dumps({"type": "result", "subtype": "error_max_turns", "result": ""}), "没有查完"),
    (json.dumps({"type": "result", "subtype": "success", "result": "我看不了 Slack"}), "不是约定的 JSON"),
    (_claude_json({"summary": "", "items": [], "error": "Slack 连接器没有授权"}), "Slack 连接器没有授权"),
])
def test_anything_else_is_a_failure_with_a_reason(stdout, needle):
    result = sw.parse_output(stdout)
    assert not result.ok and needle in result.error


def test_generate_sends_the_prompt_over_stdin_and_times_the_run():
    calls = []

    def wsl(args, *, input_text=None, timeout=None):
        calls.append((args, input_text, timeout))
        return 0, _claude_json()

    clock = iter([10.0, 52.5])
    result = sw.generate(T0, T0 - dt.timedelta(minutes=15), "sonnet", run=wsl, clock=lambda: next(clock))
    assert result.ok and result.seconds == 42.5 and result.checked_at == "2026-10-14T14:00:00"
    (args, prompt, timeout), = calls
    assert args[:3] == ["-e", "bash", "-lc"] and "claude -p" in args[3] and "13:45" in prompt
    assert sw.generate(T0, T0, "sonnet", run=lambda *a, **k: (127, "")).error.startswith("没有找到 WSL")


def test_only_new_items_are_announced_and_the_memory_follows_the_items(tmp_path):
    result = sw.parse_output(_claude_json())
    state, fresh = sw.record(tmp_path, result, T0)
    assert [item["title"] for item in fresh] == ["问你发布窗口定了没", "私信：周会改到四点可以吗"]
    assert state["failures"] == 0 and state["last_ok"] == "2026-10-14T14:00:00"
    again = sw.parse_output(_claude_json({"summary": "", "items": ITEMS[:1] + [{"title": "新的一条", "from": "Bob"}], "error": ""}))
    state, fresh = sw.record(tmp_path, again, T0 + dt.timedelta(minutes=15))
    assert [item["title"] for item in fresh] == ["新的一条"], "上次提醒过的不再冒"
    assert set(state["alerted"]) == {"https://x.slack.com/archives/C1/p1", "Bob|新的一条"}, "不在结果里的键忘掉"
    assert sw.latest(tmp_path).items[1]["title"] == "新的一条"
    state, fresh = sw.record(tmp_path, sw.WatchResult(error="超时"), T0 + dt.timedelta(minutes=30))
    assert state["failures"] == 1 and fresh == [] and sw.latest(tmp_path) is not None, "失败不抹掉上一次"


# ---------------------------------------------------------------- 服务与气泡

class FakeHost:
    def __init__(self):
        self.alerts, self.bubbles, self.resolved = [], [], []

    def show_alert(self, text, **kwargs):
        self.alerts.append((text, kwargs))

    def resolve_alert(self, alert_id):
        self.resolved.append(alert_id)

    def show_bubble(self, text, duration_ms=3200, **_kwargs):
        self.bubbles.append(text)


def _service(tmp_path, *, settings=ON, result=None, active=True, now=T0):
    config = Config(tmp_path)
    config.set(sw.CONFIG_KEY, settings)
    made = []

    def generate(when, since, model):
        made.append((when, since, model))
        return result if result is not None else sw.parse_output(_claude_json())

    service = SlackWatchService(config, generate=generate, spawn=lambda run: run(), now=lambda: now,
                                active=lambda idle_s: active)
    return service, made


def test_the_service_checks_when_due_and_not_while_the_computer_is_idle(tmp_path):
    service, made = _service(tmp_path)
    assert service.check() and len(made) == 1
    assert made[0][1] == T0 - dt.timedelta(minutes=60) and made[0][2] == "sonnet"
    assert not service.check(), "刚查过：要等一个间隔"
    idle, made_idle = _service(tmp_path / "idle", active=False)
    assert not idle.check() and made_idle == []
    assert idle.check_now() and len(made_idle) == 1, "手动检查不看人在不在"


def test_new_items_raise_an_alert_with_a_way_to_read_them(tmp_path):
    service, _made = _service(tmp_path)
    host = FakeHost()
    controller = SlackWatchController(host, service)
    service.check()
    app.processEvents()
    (text, kwargs), = host.alerts
    assert text == "发布窗口在等你拍板" and kwargs["alert_id"] == ALERT_ID and kwargs["priority"] == 1
    assert kwargs["subtitle"].startswith("Slack · 2 条") and "急" in kwargs["subtitle"]
    assert [label for label, _cb in kwargs["buttons"]] == ["查看", "知道了"]
    dict(kwargs["buttons"])["查看"]()
    window = controller.window
    assert window.isVisible() and host.resolved == [ALERT_ID] and window.windowTitle() == "Slack 关注"
    assert "发布窗口" in window.body.toPlainText()
    window.close()


def test_nothing_new_means_silence_unless_asked_by_hand(tmp_path):
    service, _made = _service(tmp_path)
    host = FakeHost()
    SlackWatchController(host, service)
    service.check_now()
    app.processEvents()
    assert len(host.alerts) == 1
    service.check_now()                      # 同一批结果：没有新的
    app.processEvents()
    assert len(host.alerts) == 1 and any("没有新的" in text for text in host.bubbles)


def test_failures_are_only_said_out_loud_for_manual_checks(tmp_path):
    service, _made = _service(tmp_path, result=sw.WatchResult(error="没登录"))
    host = FakeHost()
    SlackWatchController(host, service)
    service.check()
    app.processEvents()
    assert host.alerts == [] and host.bubbles == []
    service.check_now()
    app.processEvents()
    assert any("没登录" in text for text in host.bubbles) and service.last_error() == "没登录"


def test_the_window_says_so_when_there_is_nothing_yet(tmp_path):
    service, _made = _service(tmp_path, settings={**ON, "enabled": False})
    controller = SlackWatchController(FakeHost(), service)
    controller.open_window()
    assert controller.window.isVisible() and "还没有检查过" in controller.window.body.toPlainText()
    controller.window.close()
