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
from . import memory_distill_run as run
from . import memory_distill_sink as sink
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
    distilled = Signal(object, bool)         # RunResult, 手动?（第二期）
    reviewed = Signal(str, object)           # 提案 id, Applied
    synced = Signal(bool, str)               # 知识库镜像推送的结果
    _done = Signal(int, int, str, str)       # generation, added, error, wsl_dir（线程 → GUI）
    _distill_done = Signal(int, object, bool)
    _sync_done = Signal(int, bool, str)

    STARTUP_DELAY_MS = 40_000                # 比个人助理 / 工作笔记再晚一点，别和它们挤在启动那几秒
    REFRESH_INTERVAL_MS = 60 * 60 * 1000     # 每小时增量扫一次（实测无变化 11 ms、首扫 104 MB 0.9 s）

    def __init__(self, config, parent: QObject | None = None, *, spawn=_spawn_thread, roots=None,
                 wsl_runner=claude_hooks.run_wsl, opener=_open_target, now=None, complete=None, provider=None,
                 home: Path | None = None, token=None, git=pv.run_git) -> None:
        super().__init__(parent)
        self._config = config
        self._spawn = spawn
        self._roots = roots
        self._wsl_runner = wsl_runner
        self._open = opener
        self._now = now or dt.datetime.now
        self._complete = complete                # None = anthropic_provider.complete（用时再导入）
        self._provider = provider                # None = 「AI 对话」里的服务商（个人 key）
        self._home = home                        # None = Path.home()
        self._token = token or pv.github_token
        self._git = git
        self._generation = 0
        self._busy = False
        self._distilling = False
        self._syncing = False
        self._wsl_dir: str | None = None     # None = 还没问过
        self.last_error = ""
        self.last_refresh_at = ""
        self.last_run: run.RunResult | None = None
        self.sync_state = ""                 # "" / pushing / pushed / failed
        self.sync_error = ""
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.check)
        self._done.connect(self._on_done)
        self._distill_done.connect(self._on_distill_done)
        self._sync_done.connect(self._on_sync_done)
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
        self._distilling = False
        self._syncing = False

    def check(self) -> None:
        """定时：开着才自动抽；到了每日时刻就蒸馏一次。"""
        settings = self.settings()
        if settings["enabled"]:
            self.refresh_now()
        if run.is_due(settings, self.distill_state(), self._now()):
            self.distill_now(manual=False)

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
        state = self.distill_state()
        entries = self.entries().load()
        stats["distill"] = {"busy": self._distilling, "last_run_at": state.get("last_run_at", ""),
                            "last_error": state.get("last_error", ""), "last_result": state.get("last_result") or {},
                            "attempts": int(state.get("attempts") or 0)}
        stats["proposals"] = self.proposals().counts()
        stats["entries"] = {"global": sum(1 for e in entries if not e.retired and e.scope == "global"),
                            "project": sum(1 for e in entries if not e.retired and e.scope == "project"),
                            "retired": sum(1 for e in entries if e.retired)}
        stats["vault"] = {"state": self.sync_state, "error": self.sync_error, "dir": self.vault_dir()}
        return stats

    # ---------------------------------------------------------- 蒸馏（第二期）
    @property
    def root(self) -> Path:
        return md.store_root(self._config.dir)

    def distill_state(self) -> dict:
        return run.load_state(self.root)

    def proposals(self) -> run.ProposalStore:
        return run.ProposalStore(self.root)

    def entries(self) -> sink.EntriesStore:
        return sink.EntriesStore(self.root)

    def vault_dir(self) -> str:
        return pv.normalize(self._config.get(pv.CONFIG_KEY))["repo_dir"]

    @property
    def distilling(self) -> bool:
        return self._distilling

    def _resolve_provider(self):
        if self._provider is not None:
            return self._provider
        from .personal_service import resolve_chat_provider

        return resolve_chat_provider(self._config)

    def _resolve_complete(self):
        if self._complete is not None:
            return self._complete
        from .chat import anthropic_provider as ap

        return ap.complete

    def distill_now(self, manual: bool = True) -> bool:
        """把上次之后的个人侧候选交给模型，提案进提案库。后台线程；忙着不叠加。"""
        if self._distilling:
            return False
        now = self._now()
        settings = self.settings()
        state = self.distill_state()
        try:
            provider = self._resolve_provider()
            complete = self._resolve_complete()
        except Exception as exc:  # noqa: BLE001 - 没装聊天模块 / 没配 key
            result = run.RunResult(error=str(exc) or type(exc).__name__, run_at=now.isoformat(timespec="seconds"))
            run.save_state(self.root, {**run.mark_attempt(state, now), "last_error": result.error})
            self.last_run = result
            self.distilled.emit(result, manual)
            self.changed.emit()
            return False
        self._distilling = True
        self._generation += 1
        generation = self._generation
        rows = self.store.read_all()
        store = self.proposals()
        entries_text = "\n".join(f"- [{e.scope}{' ' + e.project if e.project else ''}] {e.title} — {e.how or e.why}"
                                 for e in self.entries().active())
        root, home = self.root, self._home

        def work() -> None:
            try:
                result, new_state = run.run_once(now, settings, rows, state, provider, store=store, complete=complete,
                                                 home=home, entries_text=entries_text)
                run.save_state(root, new_state)
            except Exception as exc:  # noqa: BLE001 - 不让线程静默死掉
                log.exception("会话记忆蒸馏：蒸馏失败")
                result = run.RunResult(error=f"{type(exc).__name__}: {exc}", run_at=now.isoformat(timespec="seconds"))
            try:
                self._distill_done.emit(generation, result, manual)
            except RuntimeError:
                pass

        self.changed.emit()                  # 先让页面显示「正在总结」，再起线程（测试里线程是同步的）
        self._spawn(work)
        return True

    def _on_distill_done(self, generation: int, result, manual: bool) -> None:
        if generation != self._generation:
            return
        self._distilling = False
        self.last_run = result
        self.changed.emit()                  # 先重摆数字（会清状态行），再报这一次的结果
        self.distilled.emit(result, manual)

    def review(self, pid: str, status: str, *, title: str | None = None, why: str | None = None,
               how: str | None = None) -> sink.Applied | None:
        """用户审一条：接受就立刻落盘（文件写入很快，在 GUI 线程），镜像推送另起线程；拒 / 跳过只记状态。"""
        store = self.proposals()
        proposal = store.get(pid)
        if proposal is None or status not in run.STATUSES:
            return None
        if title is not None and title.strip():
            proposal.title = " ".join(title.split())
        if why is not None:
            proposal.why = why.strip()
        if how is not None:
            proposal.how = how.strip()
        now = self._now()
        proposal.status = status
        proposal.reviewed_at = now.isoformat(timespec="seconds")
        applied = None
        if status == run.STATUS_ACCEPTED:
            settings = self.settings()
            applied = sink.apply_proposal(proposal, now, entries=self.entries(), home=self._home,
                                          backup_dir=self.root / sink.BACKUP_DIR, vault_dir=self.vault_dir(),
                                          mirror=bool(settings.get("mirror_to_vault", True)))
            proposal.applied = applied.to_dict()
            if applied.error:
                proposal.status = run.STATUS_PENDING       # 没落成就还留在待审里
        store.update(proposal)
        if applied is not None and applied.vault_written:
            self.sync_vault()
        self.reviewed.emit(pid, applied)
        self.changed.emit()
        return applied

    def sync_vault(self) -> bool:
        """把知识库里那篇 commit + push（后台线程）。"""
        if self._syncing:
            return False
        repo_dir = self.vault_dir()
        if not repo_dir or not Path(repo_dir).is_dir():
            return False
        self._syncing = True
        self.sync_state = "pushing"
        self._generation += 1
        generation = self._generation
        now, git, token = self._now(), self._git, self._token

        def work() -> None:
            try:
                ok, reason = sink.sync_vault(repo_dir, now, run_git=git, token=token() if callable(token) else str(token or ""))
            except Exception as exc:  # noqa: BLE001
                ok, reason = False, f"{type(exc).__name__}: {exc}"
            try:
                self._sync_done.emit(generation, ok, reason)
            except RuntimeError:
                pass

        self._spawn(work)
        return True

    def _on_sync_done(self, generation: int, ok: bool, reason: str) -> None:
        self._syncing = False
        self.sync_state = "pushed" if ok else "failed"
        self.sync_error = "" if ok else reason
        self.synced.emit(ok, reason)
        self.changed.emit()

    def recent(self, limit: int = 200) -> list[dict]:
        """最近的候选，按时间新的在前（日文件里的顺序是扫到的顺序，不是时间顺序）。"""
        rows: list[dict] = []
        store = self.store
        for path in reversed(store.day_files()):
            rows.extend(sorted(store.read_day(path.stem), key=lambda r: str(r.get("time") or ""), reverse=True))
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
