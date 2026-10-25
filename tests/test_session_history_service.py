# -*- coding: utf-8 -*-
"""最近的对话：接线层（实时记录 + 后台回填 + 点一行做什么）。

回填要读 ``~/.claude`` / 起 wsl.exe：这里一律注入替身；线程用同步 spawn 顶替，只有一条
用例走真线程，验证结果确实排队回到 GUI 线程。
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from pet.claude_session_history import SessionHistory
from pet.session_history_service import SessionHistoryActions, SessionHistoryService

app = QApplication.instance() or QApplication([])

SID_A = "11111111-aaaa-4bbb-8ccc-000000000001"
SID_B = "22222222-aaaa-4bbb-8ccc-000000000002"


def _service(tmp_path=None, *, local=(), wsl=(), spawn=None, **kwargs):
    store = SessionHistory(None if tmp_path is None else tmp_path / "history.json")
    scans = {"local": 0, "wsl": 0}

    def scan_local(**_kwargs):
        scans["local"] += 1
        return list(local)

    def scan_wsl(**_kwargs):
        scans["wsl"] += 1
        return list(wsl)

    service = SessionHistoryService(
        store, scan_local=scan_local, scan_wsl=scan_wsl, spawn=spawn or (lambda fn: fn()), **kwargs)
    service.scans = scans
    service.changes = []
    service.changed.connect(lambda: service.changes.append(1))
    return service


def _update(sid=SID_A, phase="working", **fields):
    return {"sessionId": sid, "phase": phase, **fields}


# ---------------------------------------------------------------- 实时记录

def test_live_sessions_are_recorded_with_where_they_run():
    service = _service()
    service.on_session_update("claude", _update(title="Fix login loop", project="api", cwd="c:\\work\\api"))

    (entry,) = service.entries()
    assert (entry.agent, entry.session_id, entry.title, entry.cwd) == (
        "claude", SID_A, "Fix login loop", "C:\\work\\api")
    assert service.changes == [1]


def test_a_closing_session_keeps_its_row():
    service = _service()
    service.on_session_update("claude", _update(cwd="C:\\work\\api"))
    service.on_session_update("claude", _update(phase="gone"))
    assert [e.session_id for e in service.entries()] == [SID_A], "关掉的对话正是要记住的"


def test_chatter_does_not_flood_the_ui():
    """每次工具调用都来一条更新：内容没变就不通知界面。"""
    service = _service()
    for _ in range(20):
        service.on_session_update("claude", _update(cwd="C:\\work\\api", tool="Bash"))
    assert service.changes == [1]


def test_malformed_updates_are_ignored():
    service = _service()
    for bad in (None, "x", {}, {"sessionId": "", "phase": "working"}, {"sessionId": "a b", "cwd": "C:\\x"}):
        service.on_session_update("claude", bad)
    assert service.entries() == [] and service.changes == []


def test_switched_off_records_nothing_and_lists_nothing():
    state = {"on": True}
    service = _service(enabled=lambda: state["on"])
    service.on_session_update("claude", _update(cwd="C:\\work\\api"))
    state["on"] = False
    service.on_session_update("claude", _update(SID_B, cwd="C:\\other"))
    assert service.entries() == [], "关着就不显示"
    assert service.rescan(force=True) is False and service.scans["local"] == 0
    state["on"] = True
    assert [e.session_id for e in service.entries()] == [SID_A], "关着的那段时间没有记"


def test_service_subscribes_to_both_claude_channels():
    class _Signal:
        def __init__(self):
            self.slots = []

        def connect(self, slot):
            self.slots.append(slot)

    monitors = {"claude": SimpleNamespace(session_update=_Signal()),
                "claude_wsl": SimpleNamespace(session_update=_Signal()), "dsh": object()}
    service = _service()
    service.attach(SimpleNamespace(monitors=monitors))
    assert monitors["claude"].session_update.slots == [service.on_session_update]
    assert monitors["claude_wsl"].session_update.slots == [service.on_session_update]


# ---------------------------------------------------------------- 回填

_FOUND = {"agent": "claude", "session_id": SID_B, "cwd": "C:\\old\\project", "title": "Yesterday",
          "git_branch": "", "entrypoint": "cli", "seen": None}


def test_rescan_brings_in_sessions_from_when_the_pet_was_not_running():
    service = _service(local=[dict(_FOUND)])
    assert service.rescan() is True
    assert [(e.title, e.cwd, e.entrypoint) for e in service.entries()] == [("Yesterday", "C:\\old\\project", "cli")]
    assert service.changes == [1]


def test_rescan_is_throttled_unless_forced():
    service = _service(local=[dict(_FOUND)])
    service.rescan()
    assert service.rescan() is False, "卡片每次展开都会要一次：一分钟内不重复扫"
    assert service.scans["local"] == 1
    assert service.rescan(force=True) is True and service.scans["local"] == 2
    assert service.changes == [1], "扫到的没变化就不通知"


def test_wsl_is_only_scanned_when_that_channel_is_on():
    """起 wsl.exe 会把虚拟机拉起来：没开 WSL 联动就不碰它。"""
    state = {"wsl": False}
    service = _service(wsl=[{**_FOUND, "agent": "claude_wsl", "cwd": "/home/limin/x", "distro": "Ubuntu"}],
                       wsl_enabled=lambda: state["wsl"])
    service.rescan()
    assert service.scans == {"local": 1, "wsl": 0}
    state["wsl"] = True
    service.rescan(force=True)
    assert service.scans["wsl"] == 1
    assert [(e.agent, e.distro) for e in service.entries()] == [("claude_wsl", "Ubuntu")]


def test_a_scan_in_flight_is_not_started_twice():
    pending = []
    service = _service(local=[dict(_FOUND)], spawn=pending.append)
    assert service.rescan(force=True) is True
    assert service.rescan(force=True) is False
    pending.pop()()
    assert len(service.entries()) == 1
    assert service.rescan(force=True) is True


def test_a_crashing_scan_is_survivable():
    def boom(**_kwargs):
        raise RuntimeError("内部格式变了")

    service = SessionHistoryService(SessionHistory(None), scan_local=boom, scan_wsl=boom,
                                    spawn=lambda fn: fn())
    assert service.rescan(force=True) is True
    assert service.entries() == []
    assert service.rescan(force=True) is True, "失败后忙标志要放开"


def test_real_worker_thread_delivers_on_the_gui_thread():
    scan_threads, slot_threads = [], []

    def scan_local(**_kwargs):
        scan_threads.append(threading.current_thread())
        return [dict(_FOUND)]

    service = SessionHistoryService(SessionHistory(None), scan_local=scan_local, scan_wsl=lambda **_k: [])
    loop = QEventLoop()

    def on_change():
        slot_threads.append(threading.current_thread())
        loop.quit()

    service.changed.connect(on_change)
    service.rescan(force=True)
    QTimer.singleShot(30_000, loop.quit)        # 宽预算兜底：正常由事件唤醒
    loop.exec()

    assert len(service.entries()) == 1
    assert scan_threads and scan_threads[0] is not threading.main_thread()
    assert slot_threads == [threading.main_thread()]


# ---------------------------------------------------------------- 落盘

def test_changes_are_saved_after_a_short_delay_and_on_flush(tmp_path):
    service = _service(tmp_path)
    service.on_session_update("claude", _update(cwd="C:\\work\\api"))
    assert not (tmp_path / "history.json").exists(), "不在更新的那一刻写盘"
    assert service._save_timer.isActive()

    service._save_timer.timeout.emit()
    assert (tmp_path / "history.json").exists()

    service.on_session_update("claude", _update(SID_B, cwd="C:\\work\\web"))
    service.flush()                              # 退出时
    again = SessionHistory(tmp_path / "history.json")
    again.load()
    assert len(again.entries()) == 2 and not service._save_timer.isActive()


def test_remove_clear_and_panel_state_are_persisted(tmp_path):
    service = _service(tmp_path)
    service.on_session_update("claude", _update(cwd="C:\\a"))
    service.on_session_update("claude", _update(SID_B, cwd="C:\\b"))
    service.changes.clear()

    assert service.remove(("claude", SID_A)) is True
    assert [e.session_id for e in service.entries()] == [SID_B] and service.changes == [1]
    service.set_ui_open(True)
    service.flush()
    again = SessionHistory(tmp_path / "history.json")
    again.load()
    assert again.ui_open is True and len(again.entries()) == 1

    service.clear()
    assert service.entries() == []


def test_pinning_is_persisted_and_announced(tmp_path):
    service = _service(tmp_path)
    service.on_session_update("claude", _update(cwd="C:\\a"))
    service.on_session_update("claude", _update(SID_B, cwd="C:\\b"))
    service.changes.clear()

    assert service.set_pinned(("claude", SID_A), True) is True
    assert service.changes == [1] and service._save_timer.isActive()
    assert [(e.session_id, e.pinned) for e in service.entries()] == [(SID_A, True), (SID_B, False)]
    assert service.set_pinned(("claude", SID_A), True) is False and service.changes == [1]
    assert service.set_pinned(("claude", "gone"), True) is False

    service.flush()
    again = SessionHistory(tmp_path / "history.json")
    again.load()
    assert [(e.session_id, e.pinned) for e in again.entries()] == [(SID_A, True), (SID_B, False)]


# ---------------------------------------------------------------- 点一行

@pytest.fixture
def actions():
    log = SimpleNamespace(popen=[], vscode=[], opened=[], copied=[])

    def popen(argv):
        log.popen.append(argv)
        return True

    def open_vscode(detail):
        log.vscode.append((detail.agent, detail.cwd, detail.distro))
        return True

    acts = SessionHistoryActions(
        popen=popen, open_vscode=open_vscode, open_path=lambda p: log.opened.append(p) or True,
        copy=log.copied.append, which=lambda name: "C:\\wt.exe" if name == "wt" else None, wsl="C:\\wsl.exe")
    acts.log = log
    return acts


def _entry(agent="claude", **fields):
    store = SessionHistory(None)
    store.record(agent, SID_A, **fields)
    return store.entries()[0]


def test_terminal_session_resumes_in_a_terminal_there(actions):
    message = actions.activate(_entry(cwd="C:\\work\\api", entrypoint="cli"))
    assert actions.log.popen == [["C:\\wt.exe", "-d", "C:\\work\\api", "cmd", "/k", "claude", "--resume", SID_A]]
    assert "终端" in message


def test_vscode_session_opens_that_workspace(actions):
    message = actions.activate(_entry(cwd="C:\\work\\api", entrypoint="claude-vscode"))
    assert actions.log.vscode == [("claude", "C:\\work\\api", "")] and actions.log.popen == []
    assert "VS Code" in message


def test_wsl_vscode_session_opens_the_remote_workspace(actions):
    actions.activate(_entry("claude_wsl", cwd="/home/limin/work", distro="Ubuntu", entrypoint="claude-vscode"))
    assert actions.log.vscode == [("claude_wsl", "/home/limin/work", "Ubuntu")]


def test_vscode_falls_back_to_the_folder_when_the_code_command_is_missing(actions):
    actions._open_vscode = lambda _detail: False
    message = actions.activate(_entry(cwd="C:\\work\\api", entrypoint="claude-vscode"))
    assert actions.log.opened == ["C:\\work\\api"]
    assert "code" in message, "说清楚为什么只打开了文件夹"


def test_failed_terminal_launch_is_reported(actions):
    actions._popen = lambda _argv: False
    assert "打不开" in actions.activate(_entry(cwd="C:\\work\\api", entrypoint="cli"))


def test_folder_and_copy_actions(actions):
    entry = _entry("claude_wsl", cwd="/home/limin/work", distro="Ubuntu")
    actions.run("folder", entry)
    assert actions.log.opened == ["\\\\wsl.localhost\\Ubuntu\\home\\limin\\work"]
    actions.run("copy_path", entry)
    actions.run("copy_resume", entry)
    assert actions.log.copied == ["/home/limin/work", f"claude --resume {SID_A}"]
    assert actions.run("terminal", entry) and actions.log.popen, "来源是 VS Code 的也能强制在终端里恢复"
    assert actions.run("没这个动作", entry) == ""
