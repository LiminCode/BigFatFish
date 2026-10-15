# -*- coding: utf-8 -*-
"""最近的对话：接线层（GUI 线程上的 QObject）。

``SessionHistoryService`` 把三件事接到 ``claude_session_history.SessionHistory`` 上：

- 实时记录：订阅两个 Claude Code 通道的逐会话更新（与会话小鱼同一个信号，但各记
  各的——小鱼关着、超出上限的会话照样记）；
- 回填：后台线程扫 ``~/.claude/projects``（开了 WSL 联动才扫发行版里的那份——
  起 wsl.exe 会把虚拟机拉起来），结果经信号排队回 GUI 线程并入；
- 落盘：有变化后延时几秒写一次，退出时 ``flush``。

``SessionHistoryActions`` 是「点一行做什么」：终端里开的回终端恢复，VS Code 里开的打开
那个工作区；另有打开文件夹、复制路径 / 恢复命令。每个动作返回一句给用户看的话。
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from . import claude_session_history as history_mod
from .i18n import t
from . import claude_session_info, claude_session_jump
from .claude_session_history import HistoryEntry, SessionHistory

log = logging.getLogger(__name__)

AGENT_KEYS = ("claude", "claude_wsl")


def _default_scan_local(**kwargs) -> list:
    return history_mod.scan_local(**kwargs)


def _default_scan_wsl(**kwargs) -> list:
    return history_mod.scan_wsl(**kwargs)


def _spawn_thread(target: Callable[[], None]) -> None:
    threading.Thread(target=target, daemon=True, name="pet-session-history-scan").start()


class SessionHistoryService(QObject):
    """最近开过的会话：记录、回填、落盘（见模块说明）。"""

    changed = Signal()                  # 列表内容变了：界面刷新
    _scanned = Signal(object)           # worker 线程 → GUI 线程（跨线程自动排队）

    SAVE_DELAY_MS = 3_000
    RESCAN_MIN_INTERVAL_S = 60.0
    STARTUP_SCAN_DELAY_MS = 5_000

    def __init__(self, store: SessionHistory, *, enabled: Callable[[], bool] = lambda: True,
                 wsl_enabled: Callable[[], bool] = lambda: False,
                 limits: Callable[[], tuple] | None = None,
                 scan_local: Callable | None = None, scan_wsl: Callable | None = None,
                 spawn: Callable | None = None, clock: Callable[[], float] = time.monotonic,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._enabled = enabled
        self._wsl_enabled = wsl_enabled
        self._limits = limits
        self._scan_local = scan_local
        self._scan_wsl = scan_wsl
        self._spawn = spawn or _spawn_thread
        self._clock = clock
        self._scanning = False
        self._last_scan: float | None = None
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(self.SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self._save)
        self._startup_timer = QTimer(self)
        self._startup_timer.setSingleShot(True)
        self._startup_timer.setInterval(self.STARTUP_SCAN_DELAY_MS)
        self._startup_timer.timeout.connect(self.rescan)
        self._scanned.connect(self._on_scanned)

    def start(self) -> None:
        """读入上次的记录，稍后做第一次回填（不和启动抢时间）。"""
        self._store.load()
        self._startup_timer.start()

    def _apply_limits(self) -> None:
        if self._limits is not None:
            self._store.configure(*self._limits())

    def refresh(self) -> None:
        """开关 / 上限变了：让界面重新取一次。"""
        self.changed.emit()

    @property
    def store(self) -> SessionHistory:
        return self._store

    @property
    def ui_open(self) -> bool:
        return self._store.ui_open

    # ---------------------------------------------------------------- 读取
    def entries(self) -> list[HistoryEntry]:
        self._apply_limits()
        return self._store.entries() if self._enabled() else []

    def find(self, key) -> HistoryEntry | None:
        key = tuple(key)
        return next((entry for entry in self._store.entries() if entry.key == key), None)

    # ---------------------------------------------------------------- 实时记录
    def attach(self, manager) -> None:
        """订阅联动管理器里两个 Claude Code 通道的逐会话更新。"""
        monitors = getattr(manager, "monitors", None) or {}
        for key in AGENT_KEYS:
            signal = getattr(monitors.get(key), "session_update", None)
            if signal is not None:
                signal.connect(self.on_session_update)

    @Slot(str, object)
    def on_session_update(self, agent_key, update) -> None:
        if not isinstance(update, dict) or not self._enabled():
            return
        fields = {name: str(update.get(name) or "") for name in ("cwd", "title", "project")}
        if self._store.record(str(agent_key), str(update.get("sessionId") or ""), **fields):
            self._touched()

    # ---------------------------------------------------------------- 回填
    def rescan(self, *, force: bool = False) -> bool:
        """后台扫一遍最近的 transcript。返回是否真的发起了（在途 / 刚扫过 / 关着 = False）。"""
        if not self._enabled() or self._scanning:
            return False
        now = self._clock()
        if not force and self._last_scan is not None and now - self._last_scan < self.RESCAN_MIN_INTERVAL_S:
            return False
        self._last_scan = now
        self._scanning = True
        self._apply_limits()
        days = self._store.max_age_days
        with_wsl = bool(self._wsl_enabled())
        scan_local = self._scan_local or _default_scan_local
        scan_wsl = self._scan_wsl or _default_scan_wsl

        def run() -> None:
            found: list = []
            for scan in (scan_local, scan_wsl) if with_wsl else (scan_local,):
                try:
                    found.extend(scan(max_age_days=days))
                except Exception:  # noqa: BLE001 - transcript 是 Claude Code 的内部格式，随时可能变
                    log.debug("最近的对话：回填扫描失败", exc_info=True)
            try:
                self._scanned.emit(found)
            except RuntimeError:
                pass  # 应用正在退出：本对象已销毁

        try:
            self._spawn(run)
        except Exception:  # noqa: BLE001 - 起线程失败也要放开忙标志
            log.exception("最近的对话：启动回填线程失败")
            self._scanning = False
            return False
        return True

    def _on_scanned(self, found) -> None:
        self._scanning = False
        if self._store.merge(found or []):
            self._touched()

    # ---------------------------------------------------------------- 改动
    def remove(self, key) -> bool:
        if not self._store.remove(tuple(key)):
            return False
        self._touched()
        return True

    def clear(self) -> None:
        if self._store.clear():
            self._touched()

    def set_ui_open(self, is_open: bool) -> None:
        if self._store.ui_open != bool(is_open):
            self._store.ui_open = bool(is_open)
            self._save_timer.start()

    def _touched(self) -> None:
        self._save_timer.start()
        self.changed.emit()

    # ---------------------------------------------------------------- 落盘
    def _save(self) -> None:
        self._store.save()

    def flush(self) -> None:
        """有没写的就立刻写（退出时）。"""
        self._startup_timer.stop()
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._store.save()


# ---------------------------------------------------------------- 点一行
def _popen(argv: list[str]) -> bool:
    try:
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,  # noqa: S603
                         stderr=subprocess.DEVNULL, close_fds=True)
        return True
    except OSError:
        log.warning("最近的对话：启动 %s 失败", argv[:1], exc_info=True)
        return False


def _open_path(path: str) -> bool:
    try:
        os.startfile(path)  # noqa: S606  （资源管理器打开文件夹）
        return True
    except (AttributeError, OSError):
        return False


class SessionHistoryActions:
    """「最近的对话」里一行的动作。每个动作返回一句给用户看的话（空 = 没有可说的）。"""

    def __init__(self, *, popen: Callable = _popen, open_vscode: Callable = claude_session_jump.open_in_vscode,
                 open_path: Callable = _open_path, copy: Callable[[str], None] | None = None,
                 which: Callable = shutil.which, wsl: str | None = None) -> None:
        self._popen = popen
        self._open_vscode = open_vscode
        self._open_path = open_path
        self._copy = copy
        self._which = which
        self._wsl = wsl

    @staticmethod
    def _detail(entry: HistoryEntry) -> claude_session_info.SessionDetail:
        return claude_session_info.SessionDetail(
            agent=entry.agent, session_id=entry.session_id, title=entry.title, cwd=entry.cwd,
            entrypoint=entry.entrypoint, distro=entry.distro)

    def activate(self, entry: HistoryEntry) -> str:
        """点一行：VS Code 里开的打开那个工作区，其余在终端里恢复。"""
        return self.run(history_mod.default_action(entry), entry)

    def run(self, action: str, entry: HistoryEntry) -> str:
        handler = getattr(self, f"_do_{action}", None) if action.isidentifier() else None
        return handler(entry) if callable(handler) else ""

    def _do_terminal(self, entry: HistoryEntry) -> str:
        argv = history_mod.terminal_resume_argv(entry, which=self._which, wsl=self._wsl)
        if argv is None or not self._popen(argv):
            return t("history.result.no_terminal")
        return t("history.result.resumed", label=entry.label)

    def _do_vscode(self, entry: HistoryEntry) -> str:
        if self._open_vscode(self._detail(entry)):
            return t("history.result.opened_vscode", path=entry.folder or entry.cwd)
        if self._do_folder(entry) == "":
            return t("history.result.no_code_opened_folder")
        return t("history.result.no_code_no_folder")

    def _do_folder(self, entry: HistoryEntry) -> str:
        path = claude_session_jump.explorer_path(self._detail(entry))
        return "" if path and self._open_path(path) else t("history.result.no_folder")

    def _do_copy_path(self, entry: HistoryEntry) -> str:
        return self._copied(entry.cwd, t("history.result.copied_path"))

    def _do_copy_resume(self, entry: HistoryEntry) -> str:
        return self._copied(entry.resume_command, t("history.result.copied_resume"))

    def _copied(self, text: str, said: str) -> str:
        if self._copy is None or not text:
            return ""
        self._copy(text)
        return said
