# -*- coding: utf-8 -*-
"""联动开着、但 ``settings.json`` 里没有肥鱼的 hooks：桌宠要说出来，并给一条走同意弹窗的修复路。

2026-11-14 一轮全量测试把开发机 WSL 里的 hooks 卸掉了，联动开关还开着，桌宠一声不吭，
用户看到的只是 WSL 的会话小鱼不再变状态。这里从 ``AgentLinkManager`` 的公开面测：

- 检查只读（本机读文件，WSL 一次 ``wsl.exe``，都在后台线程），判断不了就不提示；
- 缺了就冒一条气泡、``hooks_missing`` 报出来（菜单据此多出一条修复项）；
- 修复仍然是 ``set_enabled`` 的同意弹窗：用户点「否」什么都不写。

跨线程的用例一律轮询状态 + 宽预算，不用固定 sleep。
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox

from pet import claude_hooks
from pet.agent_link import AgentLinkManager, ClaudeCodeMonitor
from pet.config import Config
from pet.context_menus import shared as menu_shared

ALL = list(ClaudeCodeMonitor.HOOK_EVENTS)


def _pump_until(predicate, budget_s: float = 20.0) -> bool:
    app = QApplication.instance() or QApplication([])
    deadline = time.monotonic() + budget_s
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class _Win:
    cats = {"acts": ["写代码"]}
    idles = ["待机呼吸"]
    _bubble_busy_until = 0.0

    def __init__(self) -> None:
        self.bubbles: list[str] = []

    def isVisible(self):
        return True

    def request_link_anim(self, name):
        pass

    def request_link_idle(self):
        pass

    def show_bubble(self, text, duration_ms=3000):
        self.bubbles.append(text)


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    """一个假的用户目录：本机的 ``settings.json`` 指到这里；检查打开、不等启动延迟。"""
    fake_home = tmp_path / "home"
    monkeypatch.setattr(ClaudeCodeMonitor, "get_settings_path",
                        staticmethod(lambda: fake_home / ".claude" / "settings.json"))
    monkeypatch.setattr(AgentLinkManager, "CHECK_HOOKS_PRESENT", True)
    monkeypatch.setattr(AgentLinkManager, "_HOOKS_CHECK_DELAY_MS", 0)
    return fake_home


@pytest.fixture
def managers():
    made: list[AgentLinkManager] = []
    yield made
    for mgr in made:
        mgr.shutdown()


def _manager(tmp_path, managers, *, claude: bool = True, claude_wsl: bool = False):
    QApplication.instance() or QApplication([])
    config = Config(base=tmp_path / "cfg")
    config.set("agent_link", {**config.get("agent_link"), "claude": claude, "claude_wsl": claude_wsl})
    win = _Win()
    mgr = AgentLinkManager(win, config, min_interval=0.0)
    managers.append(mgr)
    return mgr, win


def _write_settings(home: Path, data: dict) -> Path:
    path = home / ".claude" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


_USER_HOOK = {"matcher": "", "hooks": [{"type": "command", "command": "my-own-hook"}]}


# ---------------------------------------------------------------- 本机通道

def test_link_on_without_hooks_says_so_and_reports_the_missing_events(tmp_path, home, managers):
    _write_settings(home, {"hooks": {"Stop": [_USER_HOOK]}})

    mgr, win = _manager(tmp_path, managers)

    assert _pump_until(lambda: mgr.hooks_missing("claude") is not None)
    assert list(mgr.hooks_missing("claude")) == ALL
    hints = [b for b in win.bubbles if "hooks" in b]
    assert len(hints) == 1 and "Claude Code" in hints[0]
    assert json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8")) == \
        {"hooks": {"Stop": [_USER_HOOK]}}, "检查只读，不许顺手写回去"


def test_the_hint_is_not_repeated_while_the_link_stays_on(tmp_path, home, managers, monkeypatch):
    _write_settings(home, {})
    calls: list = []
    real = ClaudeCodeMonitor.missing_hooks.__func__
    monkeypatch.setattr(ClaudeCodeMonitor, "missing_hooks",
                        classmethod(lambda cls: (calls.append(1), real(cls))[1]))
    mgr, win = _manager(tmp_path, managers)
    assert _pump_until(lambda: mgr.hooks_missing("claude") is not None)

    mgr.apply_config()      # 别的设置变了也会走到这里：通道没重启，就不再查、不再弹
    _pump_until(lambda: len(calls) > 1, budget_s=0.3)

    assert len(calls) == 1
    assert len([b for b in win.bubbles if "hooks" in b]) == 1


def test_all_hooks_present_stays_quiet(tmp_path, home, managers):
    assert ClaudeCodeMonitor.install_hooks(tmp_path / "cfg" / "agent-events" / "claude.jsonl") is True

    mgr, win = _manager(tmp_path, managers)

    assert _pump_until(lambda: mgr.hooks_missing("claude") is not None)
    assert mgr.hooks_missing("claude") == ()
    assert win.bubbles == []


@pytest.mark.parametrize("prepare", [
    lambda home: None,                                                        # 这台机器没有 ~/.claude：没用过 Claude Code
    lambda home: _write_settings(home, {}).write_text("{not json", "utf-8"),  # 读不懂：不知道就不说
    lambda home: _write_settings(home, {}).write_text("[1, 2]", "utf-8"),
])
def test_no_hint_when_it_cannot_tell(tmp_path, home, managers, prepare):
    prepare(home)

    mgr, win = _manager(tmp_path, managers)

    assert _pump_until(lambda: mgr.hooks_missing("claude") is not None)
    assert mgr.hooks_missing("claude") == ()
    assert win.bubbles == []


def test_a_claude_dir_without_settings_counts_as_missing(tmp_path, home, managers):
    """装了 Claude Code、联动默认开着、从没同意过注入：同样是「开着但没有 hooks」。"""
    (home / ".claude").mkdir(parents=True)

    mgr, _win = _manager(tmp_path, managers)

    assert _pump_until(lambda: mgr.hooks_missing("claude") is not None)
    assert list(mgr.hooks_missing("claude")) == ALL


def test_a_link_that_is_off_is_never_checked(tmp_path, home, managers, monkeypatch):
    _write_settings(home, {})
    monkeypatch.setattr(ClaudeCodeMonitor, "missing_hooks",
                        classmethod(lambda cls: pytest.fail("联动关着，不该去读 settings.json")))

    mgr, win = _manager(tmp_path, managers, claude=False)
    _pump_until(lambda: bool(win.bubbles), budget_s=0.3)

    assert mgr.hooks_missing("claude") is None and win.bubbles == []


# ---------------------------------------------------------------- 修复：仍然走同意弹窗

def test_repair_asks_first_and_writes_nothing_when_declined(tmp_path, home, managers):
    path = _write_settings(home, {"hooks": {"Stop": [_USER_HOOK]}})
    mgr, _win = _manager(tmp_path, managers)
    assert _pump_until(lambda: bool(mgr.hooks_missing("claude")))

    assert mgr.repair_hooks("claude") is False        # conftest：弹窗默认点「否」

    assert json.loads(path.read_text(encoding="utf-8")) == {"hooks": {"Stop": [_USER_HOOK]}}
    assert list(mgr.hooks_missing("claude")) == ALL
    assert mgr.cfg.get("agent_link")["claude"] is True, "拒绝修复不等于关掉联动"


def test_repair_installs_after_consent_and_clears_the_mark(tmp_path, home, managers, monkeypatch):
    path = _write_settings(home, {"hooks": {"Stop": [_USER_HOOK]}})
    mgr, _win = _manager(tmp_path, managers)
    assert _pump_until(lambda: bool(mgr.hooks_missing("claude")))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))

    assert mgr.repair_hooks("claude") is True

    data = json.loads(path.read_text(encoding="utf-8"))
    assert claude_hooks.missing_hook_events(data) == []
    assert data["hooks"]["Stop"][0] == _USER_HOOK, "用户自己的 hook 原样保留"
    assert mgr.hooks_missing("claude") == ()


def test_a_check_that_finishes_after_the_install_does_not_nag(tmp_path, home, managers, monkeypatch):
    """检查还在路上时用户已经同意并装好了：迟到的「缺」是旧结论，丢掉。"""
    _write_settings(home, {})
    started, release = threading.Event(), threading.Event()

    def _slow(cls):
        started.set()
        release.wait(20.0)
        return list(ALL)

    monkeypatch.setattr(ClaudeCodeMonitor, "missing_hooks", classmethod(_slow))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    mgr, win = _manager(tmp_path, managers)
    assert _pump_until(started.is_set)

    assert mgr.repair_hooks("claude") is True
    release.set()
    assert _pump_until(lambda: not any(t.name == "claude-hooks-check" for t in threading.enumerate()))
    _pump_until(lambda: bool(win.bubbles), budget_s=0.3)

    assert mgr.hooks_missing("claude") == ()
    assert [b for b in win.bubbles if "hooks" in b] == []


def test_turning_the_link_off_forgets_the_mark(tmp_path, home, managers):
    _write_settings(home, {})
    mgr, _win = _manager(tmp_path, managers)
    assert _pump_until(lambda: bool(mgr.hooks_missing("claude")))

    assert mgr.set_enabled("claude", False) is True

    assert mgr.hooks_missing("claude") is None


# ---------------------------------------------------------------- WSL 通道

class _FakeDistro:
    """wsl.exe 替身：按脚本内容回答；任何带输入的调用（= 写）都记下来。"""

    def __init__(self, content: str | None = None, *, claude_dir: bool = True, fail: bool = False) -> None:
        self.content, self.claude_dir, self.fail = content, claude_dir, fail
        self.calls = 0
        self.writes = 0

    def __call__(self, args, *, input_text=None, timeout=30.0):
        self.calls += 1
        if input_text is not None:
            self.writes += 1
            return 0, ""
        if self.fail:
            return 1, ""
        script = args[-1]
        if '[ -d "$d" ]' in script and not self.claude_dir:
            return 0, claude_hooks._NO_CLAUDE
        return 0, claude_hooks._MISSING if self.content is None else self.content


def _installed_settings(tmp_path) -> str:
    entries = {name: claude_hooks.hook_entry(f"cmd-{name}") for name in ALL}
    return json.dumps(claude_hooks.merge_hooks({"hooks": {"Stop": [_USER_HOOK]}}, entries))


def test_wsl_check_is_one_read_and_never_writes(tmp_path):
    stripped = _FakeDistro(json.dumps({"hooks": {"Stop": [_USER_HOOK]}}))
    assert ClaudeCodeMonitor.missing_wsl_hooks(runner=stripped) == ALL
    assert (stripped.calls, stripped.writes) == (1, 0)

    assert ClaudeCodeMonitor.missing_wsl_hooks(runner=_FakeDistro(_installed_settings(tmp_path))) == []
    assert ClaudeCodeMonitor.missing_wsl_hooks(runner=_FakeDistro(None)) == ALL, "有 ~/.claude、没有 settings.json"


@pytest.mark.parametrize("distro", [
    _FakeDistro(None, claude_dir=False),     # 发行版里没用过 Claude Code
    _FakeDistro("{}", fail=True),            # WSL 没响应
    _FakeDistro("{not json"),
    _FakeDistro("[1, 2]"),
])
def test_wsl_check_gives_no_verdict_when_it_cannot_tell(distro):
    assert ClaudeCodeMonitor.missing_wsl_hooks(runner=distro) is None
    assert distro.writes == 0


def test_wsl_link_on_without_hooks_is_checked_off_the_gui_thread(tmp_path, home, managers, monkeypatch):
    seen: dict = {}

    def _missing(cls, **_kwargs):
        seen["thread"] = threading.current_thread().name
        return list(ALL)

    monkeypatch.setattr(ClaudeCodeMonitor, "missing_wsl_hooks", classmethod(_missing))

    mgr, win = _manager(tmp_path, managers, claude=False, claude_wsl=True)

    assert _pump_until(lambda: bool(mgr.hooks_missing("claude_wsl")))
    assert seen["thread"] == "claude_wsl-hooks-check", "wsl.exe 调用不许落在 GUI 线程"
    hints = [b for b in win.bubbles if "hooks" in b]
    assert len(hints) == 1 and "Claude Code (WSL)" in hints[0]


def test_wsl_repair_clears_the_mark_once_the_background_install_lands(tmp_path, home, managers, monkeypatch):
    monkeypatch.setattr(ClaudeCodeMonitor, "missing_wsl_hooks", classmethod(lambda cls, **k: list(ALL)))
    monkeypatch.setattr(ClaudeCodeMonitor, "install_wsl_hooks", classmethod(lambda cls, f, **k: (True, "")))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    mgr, _win = _manager(tmp_path, managers, claude=False, claude_wsl=True)
    assert _pump_until(lambda: bool(mgr.hooks_missing("claude_wsl")))

    assert mgr.repair_hooks("claude_wsl") is False, "后台安装：先返回，装完再清标记"

    assert _pump_until(lambda: mgr.hooks_missing("claude_wsl") == ())
    assert mgr.cfg.get("agent_link")["claude_wsl"] is True


# ---------------------------------------------------------------- 菜单

class _MenuPet:
    def __init__(self, cfg, missing=()) -> None:
        self.cfg = cfg
        self._missing = set(missing)
        self.repaired: list[str] = []

    def toggle_agent_link(self, *_args) -> None:
        pass

    def agent_hooks_missing(self, key: str) -> bool:
        return key in self._missing

    def repair_agent_hooks(self, key: str) -> None:
        self.repaired.append(key)


def _agent_menu(tmp_path, monkeypatch, pet_factory):
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(claude_hooks, "wsl_exe", lambda: r"C:\Windows\System32\wsl.exe")
    config = Config(base=tmp_path / "menu")
    config.set("agent_link", {**config.get("agent_link"), "claude": True, "claude_wsl": True})
    pet = pet_factory(config)
    menu = QMenu()
    menu_shared.add_agent_link_menu(menu, pet)
    return menu, menu.actions()[0].menu().actions(), pet


def test_menu_adds_a_repair_item_under_the_channel_that_lost_its_hooks(tmp_path, monkeypatch):
    _menu, actions, pet = _agent_menu(tmp_path, monkeypatch, lambda cfg: _MenuPet(cfg, missing={"claude_wsl"}))
    labels = [action.text() for action in actions]

    repair = actions[labels.index("Claude Code (WSL)") + 1]
    assert "hooks" in repair.text() and not repair.isCheckable()
    assert len([label for label in labels if "hooks" in label]) == 1, "本机那条没缺，不多出修复项"

    repair.trigger()
    assert pet.repaired == ["claude_wsl"]


def test_menu_is_unchanged_when_nothing_is_missing(tmp_path, monkeypatch):
    _menu, actions, _pet = _agent_menu(tmp_path, monkeypatch, _MenuPet)
    assert [label for label in (action.text() for action in actions) if "hooks" in label] == []
