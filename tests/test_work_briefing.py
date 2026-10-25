# -*- coding: utf-8 -*-
"""工作简报：让 WSL 里登录着工作账号的 Claude Code 汇总 Jira / PR / Slack / 日程。

肥鱼自己用的是另一个账号的 API key，读不到工作账号的东西；它只负责定时触发、把结果
摆出来。这里守住的几条线：

- 交给 Claude Code 的工具只有读取类的，内置工具（Bash / 读写文件）一个不给；
- 模型名会拼进 shell 命令，配置里写了怪东西要退回默认值；
- 一天只自动生成一次，失败了隔一阵再试、试几次就算了；
- 这次无界面运行不该冒出一只会话小鱼。

纪律：不起真的 wsl.exe，不读真实的数据目录。
"""
from __future__ import annotations

import datetime as dt
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMenu

from pet import claude_hooks as ch
from pet import work_briefing as wb
from pet.config import Config
from pet.work_briefing_service import WorkBriefingService
from pet.work_briefing_ui import ALERT_ID, WorkBriefingController, WorkBriefingWindow
from tests.test_claude_hooks import _payload, _run_hook
from tests.test_session_pet_details import shell  # noqa: F401 - shell 是 fixture

app = QApplication.instance() or QApplication([])

MONDAY_10 = dt.datetime(2026, 10, 12, 10, 0)        # 星期一
TUESDAY_10 = dt.datetime(2026, 10, 13, 10, 0)
SATURDAY_10 = dt.datetime(2026, 10, 17, 10, 0)
ON = {"enabled": True, "time": "09:00", "weekdays_only": True, "model": "sonnet", "sources": dict(wb.DEFAULT_SOURCES)}

REPORT = "概要：先回两条私信，下午有例会。\n\n## Jira\n- DEMO-1：示例工单（进行中）\n\n## PR\n无\n"


def _claude_json(result=REPORT, **over) -> str:
    return json.dumps({"type": "result", "subtype": "success", "is_error": False, "num_turns": 9,
                       "result": result, "permission_denials": [], **over}, ensure_ascii=False)


def _prs(*titles) -> str:
    return json.dumps([{"repository": {"nameWithOwner": "acme/widgets"}, "number": 10 + i, "title": title,
                        "updatedAt": "2026-10-11T08:00:00Z", "isDraft": False} for i, title in enumerate(titles)])


# ---------------------------------------------------------------- 配置

def test_it_is_off_until_someone_turns_it_on(tmp_path):
    assert Config(tmp_path).get(wb.CONFIG_KEY) == {
        "enabled": False, "time": "09:00", "weekdays_only": True, "model": "sonnet", "effort": "high",
        "sources": dict(wb.DEFAULT_SOURCES), "prompt_zh": "", "prompt_en": "", "priority_rules": ""}
    assert wb.DEFAULT_SOURCES["email"] is False, "邮件默认关"


def test_the_setting_survives_a_restart_and_bad_values_are_cleaned(tmp_path):
    config = Config(tmp_path)
    config.set(wb.CONFIG_KEY, {**ON, "time": "08:30"})
    config.save()
    assert Config(tmp_path).get(wb.CONFIG_KEY) == wb.normalize({**ON, "time": "08:30"})

    config.set(wb.CONFIG_KEY, {"enabled": "yes", "time": "25:99", "model": "sonnet; rm -rf ~"})
    config.save()
    cleaned = Config(tmp_path).get(wb.CONFIG_KEY)
    assert cleaned["time"] == "09:00" and cleaned["model"] == "sonnet", "模型名会拼进 shell 命令"


@pytest.mark.parametrize("value, expected", [("7:05", "07:05"), (" 18:30 ", "18:30"), ("9", "09:00"),
                                             ("24:00", "09:00"), (None, "09:00"), ("soon", "09:00")])
def test_times_are_normalised(value, expected):
    assert wb.normalize_time(value) == expected


# ---------------------------------------------------------------- 什么时候该生成

def test_it_runs_once_the_time_has_come_on_a_workday():
    assert not wb.is_due(ON, {}, MONDAY_10.replace(hour=8, minute=59))
    assert wb.is_due(ON, {}, MONDAY_10.replace(hour=9, minute=0))
    assert wb.is_due(ON, {}, MONDAY_10.replace(hour=17)), "下午才开机也补上"
    assert not wb.is_due({**ON, "enabled": False}, {}, MONDAY_10)


def test_weekends_are_skipped_unless_asked_for():
    assert not wb.is_due(ON, {}, SATURDAY_10)
    assert wb.is_due({**ON, "weekdays_only": False}, {}, SATURDAY_10)


def test_one_briefing_a_day():
    done = {"done_date": "2026-10-12"}
    assert not wb.is_due(ON, done, MONDAY_10)
    assert wb.is_due(ON, done, TUESDAY_10)


def test_a_failed_attempt_is_retried_later_but_not_forever():
    failed = {"attempt_date": "2026-10-12", "attempts": 1, "last_attempt": MONDAY_10.timestamp()}
    assert not wb.is_due(ON, failed, MONDAY_10 + dt.timedelta(minutes=5))
    assert wb.is_due(ON, failed, MONDAY_10 + dt.timedelta(seconds=wb.RETRY_AFTER_S + 1))

    gave_up = {**failed, "attempts": wb.MAX_ATTEMPTS_PER_DAY}
    assert not wb.is_due(ON, gave_up, MONDAY_10 + dt.timedelta(hours=3))
    assert wb.is_due(ON, gave_up, TUESDAY_10), "第二天重新算"


# ---------------------------------------------------------------- 交给 Claude Code 的命令

WRITE_WORDS = ("send", "create", "edit", "update", "delete", "schedule", "add", "transition", "write",
               "reply", "draft", "trash", "label", "destructive")


def test_only_reading_tools_are_handed_over():
    tools = wb.allowed_tools()
    assert tools and all(name.startswith("mcp__") for name in tools), "不放行任何内置工具"
    for name in tools:
        action = name.rsplit("__", 1)[1].lower()
        assert not any(word in action for word in WRITE_WORDS), name
    assert any("Slack" in t for t in tools) and any("atlassian" in t.lower() for t in tools)


def test_writing_tools_are_refused_by_name_even_if_the_account_pre_approved_them():
    """那个账号自己的设置里可能放行过「发消息」之类的工具；拒绝规则压过放行规则。"""
    denied = wb.denied_tools()
    assert not set(denied) & set(wb.allowed_tools())
    for needle in ("slack_send_message", "createJiraIssue", "transitionJiraIssue", "delete_event"):
        assert any(name.endswith("__" + needle) for name in denied), needle
    assert "mcp__claude_ai_Gmail" in denied, "简报用不到邮件，整个连接器都不给"
    command = wb.claude_command("sonnet")
    assert "--disallowedTools" in command and all(f"'{name}'" in command for name in denied)


def test_the_command_runs_headless_with_builtin_tools_switched_off():
    command = wb.claude_command("sonnet")
    assert " claude -p " in command and "--output-format json" in command
    assert "--tools ''" in command, "Bash / 读写文件这些内置工具一个不给"
    assert "--no-session-persistence" in command, "不在工作账号的会话列表里留一条"
    assert f"{ch.HEADLESS_ENV}=1 " in command, "让肥鱼自己的 hook 认出这次运行"
    assert "bypassPermissions" not in command and "dangerously" not in command


def test_a_strange_model_name_never_reaches_the_shell():
    assert "--model 'sonnet'" in wb.claude_command("sonnet; rm -rf ~")
    assert "--model 'claude-opus-5-5'" in wb.claude_command("claude-opus-5-5")


# ---------------------------------------------------------------- PR 列表（肥鱼自己用 gh 查）

def test_pull_requests_are_listed_under_two_headings():
    text = wb.format_pull_requests(_prs("Fix login", "Add cache") + f"\n{wb.PR_MARK}\n" + _prs("My change"))
    assert "等我评审的（2）" in text and "我开的（1）" in text
    assert "acme/widgets#10 Fix login" in text and "acme/widgets#10 My change" in text


def test_a_failed_pr_query_says_so_instead_of_pretending_there_are_none():
    text = wb.format_pull_requests(f"gh: command not found\n{wb.PR_MARK}\n[]")
    assert "等我评审的：没查到" in text and "command not found" in text
    assert "我开的（0）" in text


def test_the_prompt_carries_the_pr_list_and_looks_back_over_the_weekend_on_monday():
    monday = wb.build_prompt(MONDAY_10, "等我评审的（1）：\n- acme/widgets#10 Fix login")
    assert "acme/widgets#10 Fix login" in monday and "72 小时" in monday and "星期一" in monday
    assert "24 小时" in wb.build_prompt(TUESDAY_10, "")
    assert "只读" in monday


# ---------------------------------------------------------------- 读回结果

def test_the_first_line_becomes_the_summary():
    briefing = wb.parse_output(_claude_json())
    assert briefing.ok and briefing.summary == "先回两条私信，下午有例会。"
    assert briefing.markdown.startswith("## Jira") and "概要" not in briefing.markdown
    assert briefing.turns == 9


def test_shell_noise_around_the_json_is_ignored():
    assert wb.parse_output("Welcome to Ubuntu\n" + _claude_json() + "\n").ok


def test_a_report_without_the_summary_line_is_still_shown():
    briefing = wb.parse_output(_claude_json(result="## Jira\n无\n"))
    assert briefing.ok and briefing.summary and briefing.markdown.startswith("## Jira")


@pytest.mark.parametrize("stdout", ["", "bash: claude: command not found\n",
                                    _claude_json(is_error=True, subtype="error_max_turns", result=""),
                                    _claude_json(is_error=True, result="Please run /login"),
                                    _claude_json(result="   ")])
def test_anything_else_is_a_failure_with_a_reason(stdout):
    briefing = wb.parse_output(stdout)
    assert not briefing.ok and briefing.error and not briefing.markdown


def test_tools_that_were_refused_are_reported():
    briefing = wb.parse_output(_claude_json(permission_denials=[{"tool_name": "mcp__x__send_message"}]))
    assert briefing.denied == ["mcp__x__send_message"]


# ---------------------------------------------------------------- 一次完整的生成（假的 wsl）

class FakeWsl:
    def __init__(self, claude_stdout=None, pr_stdout=None):
        self.calls = []
        self._claude = _claude_json() if claude_stdout is None else claude_stdout
        self._prs = _prs("Fix login") + f"\n{wb.PR_MARK}\n[]" if pr_stdout is None else pr_stdout

    def __call__(self, args, *, input_text=None, timeout=30.0):
        self.calls.append((list(args), input_text, timeout))
        return (0, self._claude) if " claude -p " in args[-1] else (0, self._prs)


def test_generating_asks_gh_first_and_hands_the_list_to_claude():
    wsl = FakeWsl()
    briefing = wb.generate(MONDAY_10, "sonnet", run=wsl)

    assert briefing.ok and briefing.generated_at.startswith("2026-10-12T10:00")
    (gh_args, gh_input, _), (claude_args, prompt, timeout) = wsl.calls
    assert gh_args[:3] == ["-e", "bash", "-lc"] and "gh search prs" in gh_args[3] and gh_input is None
    assert claude_args[:3] == ["-e", "bash", "-lc"]
    assert "acme/widgets#10 Fix login" in prompt, "提示词从标准输入进去，不拼进命令行"
    assert "Fix login" not in claude_args[3]
    assert timeout >= 300, "连着读四个来源要一阵子"


def test_no_wsl_is_a_plain_failure():
    briefing = wb.generate(MONDAY_10, "sonnet", run=lambda *a, **k: (127, ""))
    assert not briefing.ok and "WSL" in briefing.error


# ---------------------------------------------------------------- 落盘

def test_the_latest_briefing_is_kept_and_a_later_failure_does_not_erase_it(tmp_path):
    assert wb.latest(tmp_path) is None
    good = wb.parse_output(_claude_json())
    wb.record(tmp_path, good, MONDAY_10)
    assert wb.latest(tmp_path).summary == good.summary
    assert wb.load_state(tmp_path)["done_date"] == "2026-10-12"

    wb.record(tmp_path, wb.Briefing(ok=False, error="超时"), TUESDAY_10)
    state = wb.load_state(tmp_path)
    assert wb.latest(tmp_path).summary == good.summary, "昨天那份还能看"
    assert state["done_date"] == "2026-10-12" and state["attempt_date"] == "2026-10-13" and state["attempts"] == 1
    assert state["error"] == "超时"

    wb.record(tmp_path, wb.Briefing(ok=False, error="超时"), TUESDAY_10)
    assert wb.load_state(tmp_path)["attempts"] == 2


def test_a_damaged_state_file_reads_as_empty(tmp_path):
    (tmp_path / wb.STATE_FILE).write_text("{not json", encoding="utf-8")
    assert wb.load_state(tmp_path) == {} and wb.latest(tmp_path) is None


# ---------------------------------------------------------------- hook：这次运行不冒小鱼

def test_the_headless_run_stays_out_of_the_event_file(tmp_path, monkeypatch):
    monkeypatch.setenv(ch.HEADLESS_ENV, "1")
    assert _run_hook(tmp_path, "SessionStart", _payload("SessionStart")) == []
    assert _run_hook(tmp_path, "Stop", _payload("Stop")) == []


def test_ordinary_sessions_still_report(tmp_path, monkeypatch):
    monkeypatch.delenv(ch.HEADLESS_ENV, raising=False)
    assert [r["event"] for r in _run_hook(tmp_path, "SessionStart", _payload("SessionStart"))] == ["SessionStart"]


# ---------------------------------------------------------------- 后台服务

def _service(tmp_path, settings=ON, now=MONDAY_10, result=None):
    config = Config(tmp_path)
    config.set(wb.CONFIG_KEY, dict(settings))
    made = []

    def generate(when, model, **_kw):
        made.append((when, model))
        return result or wb.parse_output(_claude_json())

    service = WorkBriefingService(config, generate=generate, spawn=lambda run: run(), now=lambda: now)
    finished = []
    service.finished.connect(lambda briefing, manual: finished.append((briefing, manual)))
    return service, made, finished


def test_the_service_generates_when_due_and_only_once(tmp_path):
    service, made, finished = _service(tmp_path)
    assert service.check() is True
    app.processEvents()

    assert made == [(MONDAY_10, "sonnet")]
    assert [(b.ok, manual) for b, manual in finished] == [(True, False)]
    assert service.latest().summary == "先回两条私信，下午有例会。"
    assert service.check() is False, "今天已经有了"


def test_the_service_does_nothing_while_switched_off_but_still_generates_on_request(tmp_path):
    service, made, finished = _service(tmp_path, settings={**ON, "enabled": False})
    assert service.check() is False and made == []

    assert service.generate_now() is True
    app.processEvents()
    assert len(made) == 1 and finished[0][1] is True


def test_a_failure_is_recorded_so_the_next_check_waits(tmp_path):
    service, made, finished = _service(tmp_path, result=wb.Briefing(ok=False, error="没登录"))
    service.check()
    app.processEvents()

    assert finished[0][0].error == "没登录" and service.latest() is None
    assert service.check() is False, "刚失败过，隔一阵再试"


def test_only_one_generation_at_a_time(tmp_path):
    config = Config(tmp_path)
    pending = []
    service = WorkBriefingService(config, generate=lambda when, model, **_kw: wb.parse_output(_claude_json()),
                                  spawn=pending.append, now=lambda: MONDAY_10)
    assert service.generate_now() is True and service.busy
    assert service.generate_now() is False

    pending.pop()()
    app.processEvents()
    assert not service.busy


# ---------------------------------------------------------------- 气泡与窗口

class FakeHost:
    def __init__(self):
        self.alerts, self.resolved, self.bubbles = [], [], []

    def show_alert(self, text, **kwargs):
        self.alerts.append((text, kwargs))

    def resolve_alert(self, alert_id):
        self.resolved.append(alert_id)

    def show_bubble(self, text, duration_ms=3200, **_kwargs):
        self.bubbles.append(text)


def _controller(tmp_path, **kwargs):
    service, made, _finished = _service(tmp_path, **kwargs)
    host = FakeHost()
    return WorkBriefingController(host, service), host, service, made


def test_a_finished_briefing_is_announced_with_a_way_to_read_it(tmp_path):
    controller, host, service, _made = _controller(tmp_path)
    service.check()
    app.processEvents()

    (text, kwargs), = host.alerts
    assert text == "先回两条私信，下午有例会。"
    assert kwargs["alert_id"] == ALERT_ID and kwargs["sticky"] is True
    labels = [label for label, _callback in kwargs["buttons"]]
    assert labels == ["查看", "知道了"]

    dict(kwargs["buttons"])["查看"]()
    window = controller.window
    assert window.isVisible() and host.resolved == [ALERT_ID]
    assert "DEMO-1" in window.body.toPlainText()
    window.close()


def test_dismissing_just_closes_the_bubble(tmp_path):
    controller, host, service, _made = _controller(tmp_path)
    service.check()
    app.processEvents()
    dict(host.alerts[0][1]["buttons"])["知道了"]()
    assert host.resolved == [ALERT_ID] and controller.window is None


def test_a_failure_is_said_out_loud_not_swallowed(tmp_path):
    _controller_, host, service, _made = _controller(tmp_path, result=wb.Briefing(ok=False, error="没登录"))
    service.check()
    app.processEvents()
    assert host.alerts == [] and any("没登录" in text for text in host.bubbles)


def test_asking_for_one_now_says_it_has_started_and_does_not_start_twice(tmp_path):
    config = Config(tmp_path)
    pending = []
    service = WorkBriefingService(config, generate=lambda when, model, **_kw: wb.parse_output(_claude_json()),
                                  spawn=pending.append, now=lambda: MONDAY_10)
    host = FakeHost()
    controller = WorkBriefingController(host, service)

    controller.generate_now()
    controller.generate_now()
    assert len(pending) == 1 and len(host.bubbles) == 2, "第二次只是告诉用户还在生成"


def test_the_window_says_so_when_there_is_nothing_yet(tmp_path):
    controller, _host, _service_, _made = _controller(tmp_path, settings={**ON, "enabled": False})
    controller.open_window()
    window = controller.window
    assert window.isVisible() and "还没有" in window.body.toPlainText()
    assert window.regenerate_btn.isEnabled()
    window.close()


def test_the_window_can_ask_for_a_fresh_one(tmp_path):
    controller, host, _service_, made = _controller(tmp_path, settings={**ON, "enabled": False})
    controller.open_window()
    controller.window.regenerate_btn.click()
    app.processEvents()
    assert len(made) == 1 and "DEMO-1" in controller.window.body.toPlainText()
    controller.window.close()


def test_the_window_renders_markdown_headings_as_headings():
    window = WorkBriefingWindow()
    window.show_briefing(wb.parse_output(_claude_json()))
    assert "##" not in window.body.toPlainText() and "Jira" in window.body.toPlainText()


# ---------------------------------------------------------------- 菜单

def _find(menu: QMenu, text: str):
    for action in menu.actions():
        if action.text() == text:
            return action
        if action.menu() is not None:
            found = _find(action.menu(), text)
            if found is not None:
                return found
    return None


@pytest.fixture
def briefing_shell(shell, monkeypatch):  # noqa: F811
    monkeypatch.setattr(ch, "wsl_exe", lambda: "wsl.exe")
    service = WorkBriefingService(shell._config, generate=lambda when, model, **_kw: wb.parse_output(_claude_json()),
                                  spawn=lambda run: run(), now=lambda: MONDAY_10)
    shell.work_briefing = WorkBriefingController(shell, service)
    return shell


def test_the_menu_offers_the_briefing_under_agent_link(briefing_shell):
    menu = briefing_shell._build_menu_for(briefing_shell.sprite)
    entry = _find(menu, "工作简报")
    assert entry is not None and entry.menu() is not None
    assert [a.text() for a in entry.menu().actions() if not a.isSeparator()] == [
        "查看最近一份", "现在生成", "工作日自动生成", "生成时间"]

    toggle = _find(entry.menu(), "工作日自动生成")
    assert toggle.isCheckable() and not toggle.isChecked()
    island_states = []
    briefing_shell.work_briefing.state_changed.connect(island_states.append)
    toggle.trigger()
    assert briefing_shell._config.get(wb.CONFIG_KEY)["enabled"] is True
    assert island_states == ["idle"], "灵动岛上的按钮跟着出现"

    times = _find(entry.menu(), "生成时间").menu().actions()
    assert [a.text() for a in times if a.isChecked()] == ["09:00"]
    next(a for a in times if a.text() == "08:30").trigger()
    assert briefing_shell._config.get(wb.CONFIG_KEY)["time"] == "08:30"


def test_the_menu_has_no_briefing_without_wsl(shell, monkeypatch):  # noqa: F811
    monkeypatch.setattr(ch, "wsl_exe", lambda: None)
    assert _find(shell._build_menu_for(shell.sprite), "工作简报") is None
