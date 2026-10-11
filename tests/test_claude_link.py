# -*- coding: utf-8 -*-
"""Claude Code 联动的接线层：hooks 安装形态、WSL 通道、多会话收敛到气泡。

纯逻辑（脚本 / settings 合并 / 会话收敛）在 tests/test_claude_hooks.py；这里从
``ClaudeCodeMonitor`` 与 ``AgentLinkManager`` 的公开面测「事件文件里的一行」最终
变成什么信号、什么气泡。跨线程的用例一律轮询状态 + 宽预算，不用固定 sleep。
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox

from pet import claude_hooks, uninstall_cleanup
from pet.agent_link import AgentLinkManager, ClaudeCodeMonitor
from pet.config import Config
from pet.context_menus import shared as menu_shared


def _pump_until(predicate, budget_s: float = 20.0) -> bool:
    app = QApplication.instance() or QApplication([])
    deadline = time.monotonic() + budget_s
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _line(event: str, sid: str = "A", **extra) -> str:
    return json.dumps({"ts": 1.0, "agent": "claude", "event": event, "sessionId": sid, **extra}) + "\n"


class _Got(list):
    """Agent 级信号按到达顺序进列表本身；逐会话更新另存 ``sessions``（两条管线互不干扰）。"""

    def __init__(self) -> None:
        super().__init__()
        self.sessions: list = []


def _monitor(tmp_path, key: str = "claude"):
    """不起线程的监视器：直接驱动 ``_poll``，信号同步落进 ``got``。"""
    QApplication.instance() or QApplication([])
    mon = ClaudeCodeMonitor(key, tmp_path)
    mon.events_dir.mkdir(parents=True, exist_ok=True)
    mon.events_file.touch()
    mon._tailer.read_new_lines()        # 首读：定位到末尾（之后的追加才算新事件）
    got = _Got()
    mon.state_changed.connect(lambda k, s: got.append(("state", k, s)))
    mon.activity.connect(lambda k, t: got.append(("tool", k, t)))
    mon.session_done.connect(lambda k, p: got.append(("session_done", k, p)))
    mon.approval_requested.connect(lambda k, p: got.append(("approval_request", k, p)))
    mon.approval_resolved.connect(lambda k, p: got.append(("approval_resolved", k, p)))
    mon.session_update.connect(
        lambda k, p: got.sessions.append((k, p["sessionId"], p["phase"], p["title"] or p["project"])))
    return mon, got


def _append(mon, *lines: str) -> None:
    with open(mon.events_file, "a", encoding="utf-8") as handle:
        handle.write("".join(lines))
    mon._poll()


# ---------------------------------------------------------------- hooks 安装形态

def _install(tmp_path, monkeypatch) -> dict:
    settings = tmp_path / ".claude" / "settings.json"
    monkeypatch.setattr(ClaudeCodeMonitor, "get_settings_path", lambda: settings)
    events_file = tmp_path / "agent-events" / "claude.jsonl"
    events_file.parent.mkdir(parents=True, exist_ok=True)
    assert ClaudeCodeMonitor.install_hooks(events_file) is True
    return json.loads(settings.read_text(encoding="utf-8"))["hooks"]


def test_windows_install_sources_the_sh_script_under_git_bash(tmp_path, monkeypatch):
    """Windows + Git Bash：不起 PowerShell（每事件 284ms → 约 10ms），并钉住 shell。"""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(claude_hooks, "find_git_bash", lambda: r"C:\Git\bin\bash.exe")

    hooks = _install(tmp_path, monkeypatch)

    assert set(hooks) == set(ClaudeCodeMonitor.HOOK_EVENTS)
    assert {"Notification", "SessionEnd", "StopFailure"} <= set(hooks)
    hook = hooks["Stop"][-1]["hooks"][0]
    assert hook["shell"] == "bash"
    assert "powershell" not in hook["command"].lower()
    assert "claude_event_hook.sh" in hook["command"]
    assert "DSH_PET_EVENT=Stop " in hook["command"] and "DSH_PET_AGENT=claude " in hook["command"]
    assert "\\" not in hook["command"], "Git Bash 里路径一律正斜杠"
    assert (tmp_path / "agent-events" / "claude_event_hook.sh").is_file()


def test_windows_install_falls_back_to_powershell_without_git_bash(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(claude_hooks, "find_git_bash", lambda: None)

    hooks = _install(tmp_path, monkeypatch)

    hook = hooks["PreToolUse"][-1]["hooks"][0]
    assert hook["shell"] == "powershell"
    assert hook["command"].startswith("powershell ") and hook["command"].endswith(" PreToolUse claude")
    assert (tmp_path / "agent-events" / "claude_event_hook.ps1").is_file()


def test_posix_install_has_no_shell_field(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    hooks = _install(tmp_path, monkeypatch)
    hook = hooks["Stop"][-1]["hooks"][0]
    assert "shell" not in hook and "claude_event_hook.sh" in hook["command"]


def test_reinstall_replaces_entries_left_by_the_powershell_era(tmp_path, monkeypatch):
    """老用户升级：旧的 PowerShell 条目（带标记）被换成新命令，不留双份。"""
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    old = {"matcher": "", "x-dsh-pet": True, "hooks": [{
        "type": "command",
        "command": 'powershell -NoProfile -ExecutionPolicy Bypass -File "C:\\x\\claude_event_hook.ps1" Stop'}]}
    settings.write_text(json.dumps({"hooks": {"Stop": [old]}}), encoding="utf-8")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(claude_hooks, "find_git_bash", lambda: r"C:\Git\bin\bash.exe")

    hooks = _install(tmp_path, monkeypatch)

    assert len(hooks["Stop"]) == 1
    assert "claude_event_hook.sh" in hooks["Stop"][0]["hooks"][0]["command"]


# ---------------------------------------------------------------- 监视器：事件文件 → 信号

def test_two_sessions_do_not_end_each_other(tmp_path):
    mon, got = _monitor(tmp_path)

    _append(mon, _line("UserPromptSubmit", "A"), _line("PreToolUse", "B", tool="Bash"),
            _line("Stop", "A"))
    assert ("state", "claude", "attention") not in got, "B 还在忙：A 收工不能把 Agent 报成结束"
    assert ("session_done", "claude", {"sessionId": "A", "state": "attention"}) in got
    assert ("tool", "claude", "Bash") in got

    _append(mon, _line("Stop", "B"))
    assert got[-1] == ("state", "claude", "attention")


def test_tool_failure_is_not_reported_as_error(tmp_path):
    mon, got = _monitor(tmp_path)
    _append(mon, _line("UserPromptSubmit"), _line("PostToolUseFailure", tool="Bash"))
    assert ("state", "claude", "error") not in got
    assert got[-1] == ("state", "claude", "working")


def test_permission_prompt_becomes_an_approval_pair(tmp_path):
    mon, got = _monitor(tmp_path, "claude_wsl")
    approval = {"approvalId": "claude-permission:A"}

    _append(mon, _line("PreToolUse", tool="Bash"), _line("Notification", ntype="permission_prompt"))
    assert got[-1] == ("approval_request", "claude_wsl", approval)

    _append(mon, _line("PostToolUse", tool="Bash"))
    assert ("approval_resolved", "claude_wsl", approval) in got


def test_each_session_reports_its_own_phase_and_label(tmp_path):
    """会话小鱼的数据源：逐会话的阶段 + 标签，经监视器信号送出（不走 Agent 级状态机）。"""
    mon, got = _monitor(tmp_path, "claude_wsl")
    meta = json.dumps({"agent": "claude_wsl", "event": "SessionMeta", "sessionId": "A",
                       "project": "dsh-pet", "title": "Fix login loop"}) + "\n"

    _append(mon, _line("UserPromptSubmit", "A"), meta, _line("UserPromptSubmit", "B"), _line("Stop", "A"))

    assert got.sessions == [
        ("claude_wsl", "A", "working", ""),
        ("claude_wsl", "A", "working", "Fix login loop"),
        ("claude_wsl", "B", "working", ""),
        ("claude_wsl", "A", "resting", "Fix login loop"),
    ]


def test_stopping_the_monitor_retires_its_sessions(tmp_path):
    """关掉联动 = 这个通道的会话小鱼全部离场；否则它们会永远留在桌面上。"""
    mon, got = _monitor(tmp_path)
    _append(mon, _line("UserPromptSubmit", "A"), _line("UserPromptSubmit", "B"))
    got.sessions.clear()

    mon.stop()

    assert sorted(s[1:3] for s in got.sessions) == [("A", "gone"), ("B", "gone")]


def test_start_creates_the_events_file(tmp_path):
    """文件若由第一条事件创建，tailer 的防回放会把那一批事件整个跳掉。"""
    QApplication.instance() or QApplication([])
    mon = ClaudeCodeMonitor("claude", tmp_path)
    try:
        assert mon.start() is True
        assert mon.events_file.is_file()
        assert (mon.events_dir / "claude_event_hook.sh").is_file()
    finally:
        mon.stop()


def test_events_file_is_emptied_once_it_grows_past_the_limit(tmp_path, monkeypatch):
    mon, got = _monitor(tmp_path)
    monkeypatch.setattr(ClaudeCodeMonitor, "_TRIM_BYTES", 300)

    _append(mon, *[_line("SessionStart", f"s{i}") for i in range(10)])
    assert mon.events_file.stat().st_size == 0, "空闲且已读到末尾：清空"

    _append(mon, _line("UserPromptSubmit"))
    assert got[-1] == ("state", "claude", "thinking"), "清空后的新事件照常读到"


def test_events_file_is_not_emptied_while_a_session_is_busy(tmp_path, monkeypatch):
    """截断与 hook 追加之间有竞争窗口：忙的时候丢的可能就是 Stop。"""
    mon, got = _monitor(tmp_path)
    monkeypatch.setattr(ClaudeCodeMonitor, "_TRIM_BYTES", 300)

    _append(mon, _line("UserPromptSubmit"), *[_line("PreToolUse", tool="Read") for _ in range(10)])
    assert mon.events_file.stat().st_size > 300

    _append(mon, _line("Stop"))
    assert got[-1] == ("state", "claude", "attention")
    assert mon.events_file.stat().st_size == 0


# ---------------------------------------------------------------- 管理器：气泡

class _Win:
    cats = {"acts": ["写代码", "吃Token"]}
    idles = ["待机呼吸"]
    _bubble_busy_until = 0.0

    def __init__(self) -> None:
        self.bubbles: list[str] = []
        self.alerts: list[tuple[str, str]] = []
        self.resolved: list[str] = []
        self.idle_requests = 0

    def isVisible(self):
        return True

    def request_link_anim(self, name):
        pass

    def request_link_idle(self):
        self.idle_requests += 1

    def show_bubble(self, text, duration_ms=3000):
        self.bubbles.append(text)

    def show_alert(self, text, **kwargs):
        self.alerts.append((text, kwargs.get("alert_id", "")))

    def resolve_alert(self, alert_id):
        self.resolved.append(alert_id)


def _manager(tmp_path):
    QApplication.instance() or QApplication([])
    win = _Win()
    return AgentLinkManager(win, Config(base=tmp_path), min_interval=0.0), win


def test_session_done_bubbles_without_leaving_the_busy_state(tmp_path):
    mgr, win = _manager(tmp_path)
    mgr._on_agent_state("claude", "working")
    win.bubbles.clear()

    mgr._on_session_done("claude", {"sessionId": "A", "state": "attention"})

    assert len(win.bubbles) == 1 and "Claude Code" in win.bubbles[0]
    assert mgr._last_raw["claude"] == "working"
    assert win.idle_requests == 0, "别的会话还在忙：不许切回待机"
    assert "claude" not in mgr._done_pending

    mgr._on_session_done("claude", {"sessionId": "B", "state": "attention"})
    assert len(win.bubbles) == 1, "冷却内不连弹两条"


def test_claude_permission_prompt_shows_a_sticky_alert_and_clears_it(tmp_path):
    mgr, win = _manager(tmp_path)
    approval = {"approvalId": "claude-permission:A"}

    mgr._on_approval_request("claude_wsl", approval)

    assert len(win.alerts) == 1
    text, alert_id = win.alerts[0]
    assert "Claude Code (WSL)" in text
    assert "DSH" not in text, "Claude Code 的权限确认不在 DSH 界面里处理"

    mgr._on_approval_resolved("claude_wsl", approval)
    assert win.resolved == [alert_id]


def test_monitor_signals_reach_the_manager(tmp_path):
    """文件里的一行 → 监视器 → 管理器 → 气泡（两个通道各自署名）。"""
    mgr, win = _manager(tmp_path)
    mon = mgr.monitors["claude_wsl"]
    mon.events_dir.mkdir(parents=True, exist_ok=True)
    mon.events_file.touch()
    mon._tailer.read_new_lines()

    with open(mon.events_file, "a", encoding="utf-8") as handle:
        handle.write(_line("UserPromptSubmit", "A") + _line("PreToolUse", "B", tool="Bash")
                     + _line("Stop", "A"))
    mon._poll(gen=mon._emit_gen)

    assert _pump_until(lambda: any("Claude Code (WSL)" in b and "停" in b for b in win.bubbles))
    assert mgr._last_raw["claude_wsl"] == "working"


# ---------------------------------------------------------------- WSL 通道

class _FakeWsl:
    def __init__(self, content: str | None = None, *, fail_read: bool = False,
                 fail_write: bool = False, no_path: bool = False) -> None:
        self.content = content
        self.fail_read, self.fail_write, self.no_path = fail_read, fail_write, no_path
        self.writes = 0

    def __call__(self, args, *, input_text=None, timeout=30.0):
        if args[:2] == ["-e", "wslpath"]:
            if self.no_path:
                return 1, ""
            path = args[-1].replace("\\", "/")
            return 0, "/mnt/" + path[0].lower() + path[2:] + "\n"
        if input_text is not None:
            if self.fail_write:
                return 1, ""
            self.writes += 1
            self.content = input_text
            return 0, ""
        if self.fail_read:
            return 1, ""
        return 0, claude_hooks._MISSING if self.content is None else self.content


def _wsl_events_file(tmp_path) -> Path:
    events_file = tmp_path / "agent-events" / "claude_wsl.jsonl"
    events_file.parent.mkdir(parents=True, exist_ok=True)
    return events_file


def test_wsl_install_merges_into_the_distro_settings(tmp_path):
    user = {"matcher": "", "hooks": [{"type": "command", "command": "paplay ding.wav", "async": True}]}
    fake = _FakeWsl(json.dumps({"model": "x", "hooks": {"Stop": [user]}}))
    events_file = _wsl_events_file(tmp_path)

    ok, msg = ClaudeCodeMonitor.install_wsl_hooks(events_file, runner=fake)

    assert (ok, msg) == (True, "")
    data = json.loads(fake.content)
    assert data["model"] == "x"
    assert data["hooks"]["Stop"][0] == user, "用户自己的 hook 原样保留"
    ours = data["hooks"]["Stop"][1]
    assert ours["x-dsh-pet"] is True
    hook = ours["hooks"][0]
    assert "shell" not in hook
    assert "DSH_PET_AGENT=claude_wsl " in hook["command"]
    assert "/mnt/" in hook["command"] and "claude_wsl.jsonl" in hook["command"]
    assert "\\" not in hook["command"], "发行版里只认 Linux 路径"
    assert set(data["hooks"]) == set(ClaudeCodeMonitor.HOOK_EVENTS)
    assert events_file.is_file() and (events_file.parent / "claude_event_hook.sh").is_file()


def test_wsl_install_creates_settings_when_the_distro_has_none(tmp_path):
    fake = _FakeWsl(None)
    assert ClaudeCodeMonitor.install_wsl_hooks(_wsl_events_file(tmp_path), runner=fake)[0] is True
    assert set(json.loads(fake.content)["hooks"]) == set(ClaudeCodeMonitor.HOOK_EVENTS)


@pytest.mark.parametrize("fake", [
    _FakeWsl('{"a": 1}', no_path=True),
    _FakeWsl('{"a": 1}', fail_read=True),
    _FakeWsl("{not json"),
    _FakeWsl("[1, 2]"),
    _FakeWsl('{"a": 1}', fail_write=True),
])
def test_wsl_install_never_overwrites_settings_it_could_not_read(tmp_path, fake):
    before = fake.content
    ok, msg = ClaudeCodeMonitor.install_wsl_hooks(_wsl_events_file(tmp_path), runner=fake)
    assert ok is False and msg
    assert fake.content == before and fake.writes == 0


def test_wsl_uninstall_removes_only_ours(tmp_path):
    user = {"matcher": "", "hooks": [{"type": "command", "command": "paplay ding.wav"}]}
    fake = _FakeWsl(json.dumps({"hooks": {"Stop": [user]}}))
    ClaudeCodeMonitor.install_wsl_hooks(_wsl_events_file(tmp_path), runner=fake)

    assert ClaudeCodeMonitor.uninstall_wsl_hooks(runner=fake) is True
    assert json.loads(fake.content)["hooks"] == {"Stop": [user]}
    assert ClaudeCodeMonitor.uninstall_wsl_hooks(runner=_FakeWsl(None)) is True
    assert ClaudeCodeMonitor.uninstall_wsl_hooks(runner=_FakeWsl("{}", fail_read=True)) is False


def test_enabling_the_wsl_link_installs_in_the_background_then_turns_on(tmp_path, monkeypatch):
    mgr, win = _manager(tmp_path)
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    caller: dict = {}

    def _install(cls, events_file, **_kw):
        caller["thread"] = threading.current_thread().name
        caller["file"] = events_file
        return True, ""

    monkeypatch.setattr(ClaudeCodeMonitor, "install_wsl_hooks", classmethod(_install))

    assert mgr.set_enabled("claude_wsl", True) is False, "先回弹菜单，装完再自动开启"
    assert _pump_until(lambda: mgr.cfg.get("agent_link", {}).get("claude_wsl") is True)
    assert caller["thread"] == "claude-wsl-hooks-install", "wsl.exe 调用不许落在 GUI 线程"
    assert caller["file"].name == "claude_wsl.jsonl"
    assert mgr.monitors["claude_wsl"]._running is True
    assert any("Claude Code (WSL)" in b and "开启" in b for b in win.bubbles)


def test_wsl_link_stays_off_when_install_fails_or_is_declined(tmp_path, monkeypatch):
    mgr, win = _manager(tmp_path)
    called: list = []
    monkeypatch.setattr(ClaudeCodeMonitor, "install_wsl_hooks",
                        classmethod(lambda cls, f, **k: (called.append(f), (False, "WSL 没有响应"))[1]))

    assert mgr.set_enabled("claude_wsl", True) is False     # conftest：默认点「否」
    assert called == []

    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    assert mgr.set_enabled("claude_wsl", True) is False
    assert _pump_until(lambda: any("WSL 没有响应" in b for b in win.bubbles))
    assert mgr.cfg.get("agent_link", {}).get("claude_wsl") is False
    assert mgr.monitors["claude_wsl"]._running is False


def test_disabling_the_wsl_link_removes_hooks_off_the_gui_thread(tmp_path, monkeypatch):
    mgr, _win = _manager(tmp_path)
    cfg = dict(mgr.cfg.get("agent_link", {}))
    cfg["claude_wsl"] = True
    mgr.cfg.set("agent_link", cfg)
    done = threading.Event()
    seen: dict = {}

    def _uninstall(cls, **_kw):
        seen["thread"] = threading.current_thread().name
        done.set()
        return True

    monkeypatch.setattr(ClaudeCodeMonitor, "uninstall_wsl_hooks", classmethod(_uninstall))

    assert mgr.set_enabled("claude_wsl", False) is True
    assert done.wait(20.0)
    assert seen["thread"] == "claude-wsl-hooks-uninstall"
    assert mgr.cfg.get("agent_link", {}).get("claude_wsl") is False


# ---------------------------------------------------------------- 菜单与卸载清理

class _MenuPet:
    def __init__(self, cfg) -> None:
        self.cfg = cfg

    def toggle_agent_link(self, *_args) -> None:
        pass


def _agent_menu_labels(tmp_path) -> list[str]:
    QApplication.instance() or QApplication([])
    menu = QMenu()
    menu_shared.add_agent_link_menu(menu, _MenuPet(Config(base=tmp_path)))
    submenu = menu.actions()[0].menu()
    return [action.text() for action in submenu.actions()]


def test_menu_offers_the_wsl_channel_only_where_wsl_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(claude_hooks, "wsl_exe", lambda: None)
    assert "Claude Code (WSL)" not in _agent_menu_labels(tmp_path)

    monkeypatch.setattr(claude_hooks, "wsl_exe", lambda: r"C:\Windows\System32\wsl.exe")
    labels = _agent_menu_labels(tmp_path)
    assert labels.index("Claude Code (WSL)") == labels.index("Claude Code") + 1


def _cleanup(tmp_path, monkeypatch, *, enabled: bool) -> tuple[dict, list]:
    config = Config(base=tmp_path)
    if enabled:
        data = dict(config.get("agent_link", {}))
        data["claude_wsl"] = True
        config.set("agent_link", data)
    calls: list = []
    monkeypatch.setattr("pet.autostart.disable", lambda: True)
    monkeypatch.setattr("pet.agent_link.ClaudeCodeMonitor.uninstall_hooks", classmethod(lambda cls: True))
    monkeypatch.setattr("pet.agent_link.DshMonitor.uninstall_bridge", classmethod(lambda cls: True))
    monkeypatch.setattr("pet.agent_link.ClaudeCodeMonitor.uninstall_wsl_hooks",
                        classmethod(lambda cls, **k: (calls.append(1), True)[1]))
    monkeypatch.setattr(uninstall_cleanup, "other_instances_use_agent", lambda config, key: False)
    return uninstall_cleanup.run_uninstall_cleanup(config), calls


def test_uninstall_cleanup_leaves_wsl_alone_unless_the_channel_was_used(tmp_path, monkeypatch):
    """调 wsl.exe 会唤醒发行版：没开过这个通道的用户，卸载时不该为此等几秒。"""
    results, calls = _cleanup(tmp_path, monkeypatch, enabled=False)
    assert calls == [] and "claude_wsl_hooks" not in results


def test_uninstall_cleanup_removes_wsl_hooks_when_the_channel_was_on(tmp_path, monkeypatch):
    results, calls = _cleanup(tmp_path, monkeypatch, enabled=True)
    assert calls == [1] and results["claude_wsl_hooks"] is True
