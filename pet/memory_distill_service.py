# -*- coding: utf-8 -*-
"""会话记忆蒸馏的 Qt 侧服务：定时增量抽取（后台线程）、候选库统计、各个记忆库的入口。

第一期只读不写：抽取 transcript 进本地候选库、给流程页报数字、打开目录 / Obsidian。蒸馏（模型调用）与审核是
第二期，``daily_at`` 已存在配置里但这里还不用它。阻塞的事（读 transcript、起 wsl.exe 问路径）都在线程里；
结果经 queued 信号回 GUI 线程。
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from . import claude_hooks
from . import memory_distill as md
from . import personal_vault as pv
from . import work_notes as wn

log = logging.getLogger("big-fat-fish")

#: 流程页上和菜单里的入口；``kind``：folder（资源管理器）/ vault（先试 Obsidian，再退回文件夹）/ file
PLACE_PERSONAL_VAULT = "personal_vault"
PLACE_WORK_VAULT = "work_vault"
PLACE_WINDOWS_CLAUDE = "windows_claude"
PLACE_WSL_CLAUDE = "wsl_claude"
PLACE_GLOBAL_CLAUDE_MD = "global_claude_md"
PLACE_CANDIDATES = "candidates"
PLACE_TRANSCRIPTS = "transcripts"
PLACE_ORDER = (PLACE_PERSONAL_VAULT, PLACE_WORK_VAULT, PLACE_WINDOWS_CLAUDE, PLACE_WSL_CLAUDE,
               PLACE_GLOBAL_CLAUDE_MD, PLACE_TRANSCRIPTS, PLACE_CANDIDATES)


@dataclass(frozen=True)
class Place:
    key: str
    side: str            # personal / work / shared
    kind: str            # folder / vault / file
    path: str            # 空 = 还不知道（WSL 那条要问过 wsl.exe 才知道）

    @property
    def exists(self) -> bool:
        """UNC（``\\\\wsl.localhost\\…``）不去 stat：发行版没起来时会卡几秒甚至报权限错，路径本来就是问 wslpath 得来的。"""
        if not self.path:
            return False
        if self.path.startswith("\\\\"):
            return True
        try:
            return Path(self.path).exists()
        except OSError:
            return False


def _spawn_thread(target: Callable[[], None]) -> None:
    threading.Thread(target=target, daemon=True, name="pet-memory-distill").start()


def _open_target(target: str) -> bool:
    try:
        os.startfile(target)  # noqa: S606  （obsidian:// 协议、文件夹或文件）
        return True
    except (AttributeError, OSError):
        return False


def wsl_claude_dir(runner=claude_hooks.run_wsl) -> str:
    """WSL 默认发行版里 ``~/.claude`` 的 Windows 路径（``\\\\wsl.localhost\\<发行版>\\home\\<用户>\\.claude``）。
    阻塞：一次 wsl.exe；没装 WSL 或失败返回空。"""
    if not claude_hooks.wsl_exe():
        return ""
    try:
        code, out = runner(["-e", "sh", "-c", 'wslpath -w "$HOME/.claude"'], timeout=10)
    except Exception:  # noqa: BLE001 - 只是少一个入口
        return ""
    path = out.strip().splitlines()[-1].strip() if code == 0 and out.strip() else ""
    return path if path.startswith("\\\\") else ""


class MemoryDistillService(QObject):
    """``refreshed(int)``：一次抽取完成（新增条数）；``changed``：统计数字变了；``failed(str)``：抽取报错。"""

    refreshed = Signal(int)
    changed = Signal()
    failed = Signal(str)
    _done = Signal(int, int, str, str)       # generation, added, error, wsl_dir（线程 → GUI）

    STARTUP_DELAY_MS = 40_000                # 比个人助理 / 工作笔记再晚一点，别和它们挤在启动那几秒
    REFRESH_INTERVAL_MS = 60 * 60 * 1000     # 每小时增量扫一次（实测无变化 11 ms、首扫 104 MB 0.9 s）

    def __init__(self, config, parent: QObject | None = None, *, spawn=_spawn_thread, roots=None,
                 wsl_runner=claude_hooks.run_wsl, opener=_open_target, now=None) -> None:
        super().__init__(parent)
        self._config = config
        self._spawn = spawn
        self._roots = roots
        self._wsl_runner = wsl_runner
        self._open = opener
        self._now = now or dt.datetime.now
        self._generation = 0
        self._busy = False
        self._wsl_dir: str | None = None     # None = 还没问过
        self.last_error = ""
        self.last_refresh_at = ""
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.check)
        self._done.connect(self._on_done)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.stop)

    # ---------------------------------------------------------- 配置与库
    def settings(self) -> dict:
        return md.normalize(self._config.get(md.CONFIG_KEY))

    @property
    def store(self) -> md.CandidateStore:
        return md.CandidateStore(md.store_root(self._config.dir), keep_days=self.settings()["keep_days"])

    def transcript_roots(self) -> list[Path]:
        return list(self._roots) if self._roots is not None else [md.projects_dir()]

    @property
    def busy(self) -> bool:
        return self._busy

    # ---------------------------------------------------------- 生命周期
    def start(self) -> None:
        QTimer.singleShot(self.STARTUP_DELAY_MS, self.check)
        self._timer.start(self.REFRESH_INTERVAL_MS)

    def stop(self) -> None:
        self._timer.stop()
        self._generation += 1
        self._busy = False

    def check(self) -> None:
        """定时：开着才自动抽。"""
        if self.settings()["enabled"]:
            self.refresh_now()

    # ---------------------------------------------------------- 抽取
    def refresh_now(self) -> bool:
        """手动 / 定时都走这：后台线程里增量扫 + 清理过期日文件。忙着就不叠加。"""
        if self._busy:
            return False
        self._busy = True
        self._generation += 1
        generation = self._generation
        store = self.store
        roots = self.transcript_roots()
        work_roots = tuple(self.settings()["work_roots"])
        need_wsl = self._wsl_dir is None
        runner = self._wsl_runner

        def work() -> None:
            added, error, wsl_dir = 0, "", ""
            try:
                added = store.refresh(roots, work_roots=work_roots)
                store.prune()
                if need_wsl:
                    wsl_dir = wsl_claude_dir(runner)
            except Exception as exc:  # noqa: BLE001 - 报给页面，不让线程静默死掉
                log.exception("会话记忆蒸馏：抽取失败")
                error = f"{type(exc).__name__}: {exc}"
            try:
                self._done.emit(generation, added, error, wsl_dir if need_wsl else "\0")
            except RuntimeError:
                pass

        self._spawn(work)
        return True

    def _on_done(self, generation: int, added: int, error: str, wsl_dir: str) -> None:
        if generation != self._generation:
            return
        self._busy = False
        if wsl_dir != "\0":
            self._wsl_dir = wsl_dir
        self.last_error = error
        if not error:
            self.last_refresh_at = self._now().isoformat(timespec="seconds")
        self.changed.emit()                  # 先让页面重摆数字，再报这一次的结果（结果那行不被重摆盖掉）
        if error:
            self.failed.emit(error)
        else:
            self.refreshed.emit(added)

    # ---------------------------------------------------------- 给页面的数字
    def stats(self) -> dict:
        stats = self.store.stats()
        stats["keep_days"] = self.settings()["keep_days"]
        stats["enabled"] = self.settings()["enabled"]
        stats["busy"] = self._busy
        stats["error"] = self.last_error
        return stats

    def recent(self, limit: int = 200) -> list[dict]:
        """最近的候选，新的在前。"""
        rows: list[dict] = []
        store = self.store
        for path in reversed(store.day_files()):
            rows.extend(reversed(store.read_day(path.stem)))
            if len(rows) >= limit:
                break
        return rows[:limit]

    # ---------------------------------------------------------- 入口
    def places(self) -> list[Place]:
        personal = pv.normalize(self._config.get(pv.CONFIG_KEY))["repo_dir"]
        work = wn.normalize(self._config.get(wn.CONFIG_KEY))["repo_dir"]
        home = Path.home() / ".claude"
        return [
            Place(PLACE_PERSONAL_VAULT, md.SIDE_PERSONAL, "vault", personal),
            Place(PLACE_WORK_VAULT, md.SIDE_WORK, "vault", work),
            Place(PLACE_WINDOWS_CLAUDE, md.SIDE_PERSONAL, "folder", str(home)),
            Place(PLACE_WSL_CLAUDE, md.SIDE_WORK, "folder", self._wsl_dir or ""),
            Place(PLACE_GLOBAL_CLAUDE_MD, "shared", "file", str(home / "CLAUDE.md")),
            Place(PLACE_TRANSCRIPTS, "shared", "folder", str(self.transcript_roots()[0])),
            Place(PLACE_CANDIDATES, "shared", "folder", str(self.store.candidates_dir)),
        ]

    def place(self, key: str) -> Place | None:
        return next((p for p in self.places() if p.key == key), None)

    def open_place(self, key: str) -> tuple[str, str]:
        """打开一个入口：``("obsidian" | "folder" | "file" | "missing" | "failed", 路径)``。"""
        place = self.place(key)
        if place is None or not place.path:
            return "missing", ""
        target = place.path
        if place.kind == "vault":
            uri = pv.obsidian_vault_uri(target)
            if uri and self._open(uri):
                return "obsidian", target
        if not place.exists:
            if key == PLACE_CANDIDATES:
                Path(target).mkdir(parents=True, exist_ok=True)      # 还没抽过：建出来再打开
            else:
                return "missing", target
        return ("file" if place.kind == "file" else "folder") if self._open(target) else "failed", target
