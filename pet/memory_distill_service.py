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
import shlex
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
from . import memory_distill_wsl as mdw
from . import memory_distill_wsl_sink as wsink
from . import personal_vault as pv
from . import vscode_workspaces as vw
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
#: 一趟抽取里 WSL 那半的结果：扫了 / 发行版没在跑所以没去（只有定时那趟会这样）/ 去了没问到 / 设置里关了
WSL_OK, WSL_ASLEEP, WSL_FAILED, WSL_OFF = "ok", "asleep", "failed", "off"
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

    @property
    def wsl(self) -> bool:
        """目录在 WSL 里（``\\\\wsl.localhost\\<发行版>\\…`` / ``\\\\wsl$\\…``）：入口上多一个「用 VS Code 打开」。"""
        return bool(self.path) and self.path.startswith("\\\\") and vw.parse_directory(self.path, default_distro=lambda: "")[0]


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
    _done = Signal(int, int, str, str, str)  # generation, added, error, wsl_dir, WSL 那半的结果（线程 → GUI）
    _wsl_done = Signal(str)                  # 单独探 WSL 目录的结果（线程 → GUI）
    vscode_done = Signal(bool, str, str)     # 「用 VS Code 打开」的结果：开成没有, 路径, 失败原因
    _vscode_done = Signal(bool, str, str)    # 同上，线程 → GUI
    _distill_done = Signal(int, object, bool, str)   # generation, RunResult, 手动?, 哪一侧
    _review_done = Signal(int, object, object)       # generation, 提案, Applied（公司侧落盘在线程里，线程 → GUI）
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
        self._generation = 0                 # 只在 stop() 时加一：停了之后才回来的线程结果一律不要
        self._busy = False
        self._distilling: set[str] = set()   # 正在蒸馏的侧（两侧各走各的模型，可以同时跑）
        self._applying: set[str] = set()     # 正在往 WSL 里写的公司侧提案 id
        self._syncing = False
        self._wsl_dir: str | None = None     # None = 还没问过
        self._probing_wsl = False
        self.last_error = ""
        self.wsl_scan_state = ""             # 上一趟抽取里 WSL 那半：""（还没抽过）/ ok / asleep / failed / off
        self.last_refresh_at = ""
        self.last_run: run.RunResult | None = None
        self.sync_state = ""                 # "" / pushing / pushed / failed
        self.sync_error = ""
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.check)
        self._done.connect(self._on_done)
        self._wsl_done.connect(self._on_wsl_done)
        self._vscode_done.connect(self.vscode_done)
        self._distill_done.connect(self._on_distill_done)
        self._review_done.connect(self._on_review_done)
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
        self._distilling.clear()
        self._applying.clear()
        self._syncing = False

    def check(self) -> None:
        """定时：开着才自动抽；到了每日时刻就蒸馏一次。"""
        settings = self.settings()
        if settings["enabled"]:
            self.refresh_now(manual=False)
        for side in md.SIDES:                # 两侧各有各的时刻（公司侧还有自己的开关）
            if run.is_due(md.side_settings(settings, side), self.distill_state(side), self._now()):
                self.distill_now(manual=False, side=side)

    def probe_wsl(self) -> bool:
        """开流程页时单独问一次 WSL 里 ``~/.claude`` 在哪（抽取没开的话没人会顺便问）。问过 / 正在问就不再问。"""
        if self._wsl_dir is not None or self._probing_wsl:
            return False
        self._probing_wsl = True
        runner = self._wsl_runner

        def work() -> None:
            try:
                found = wsl_claude_dir(runner)
            except Exception:  # noqa: BLE001 - 只是少一个入口
                found = ""
            try:
                self._wsl_done.emit(found)
            except RuntimeError:
                pass

        self._spawn(work)
        return True

    def _on_wsl_done(self, wsl_dir: str) -> None:
        self._probing_wsl = False
        self._wsl_dir = wsl_dir
        self.changed.emit()                  # 入口按钮按新路径重摆

    # ---------------------------------------------------------- 抽取
    def refresh_now(self, manual: bool = True) -> bool:
        """手动 / 定时都走这：后台线程里增量扫 + 清理过期日文件。忙着就不叠加。

        WSL 里的会话（公司侧）也在这一趟里扫：先在那边列清单，再经共享只读长了的文件。定时那趟只在默认发行版
        本来就在跑时才去（不为每小时一次的增量把它叫醒）；手动那趟一定去。WSL 那半失败不影响 Windows 这半。"""
        if self._busy:
            return False
        self._busy = True
        generation = self._generation
        store = self.store
        roots = self.transcript_roots()
        settings = self.settings()
        work_roots = tuple(settings["work_roots"])
        scan_wsl = bool(settings["scan_wsl"])
        need_wsl = self._wsl_dir is None and not self._probing_wsl
        if need_wsl:
            self._probing_wsl = True
        runner = self._wsl_runner

        def work() -> None:
            added, error, wsl_dir, wsl_state = 0, "", "", WSL_OFF
            try:
                remote = None
                if scan_wsl:
                    if not manual and not mdw.default_distro_running(runner):
                        wsl_state = WSL_ASLEEP
                    else:
                        remote = mdw.list_transcripts(runner)
                        wsl_state = WSL_OK if remote is not None else WSL_FAILED
                added = store.refresh(roots, work_roots=work_roots, remote=remote)
                store.prune()
                if need_wsl:
                    wsl_dir = wsl_claude_dir(runner)
            except Exception as exc:  # noqa: BLE001 - 报给页面，不让线程静默死掉
                log.exception("会话记忆蒸馏：抽取失败")
                error = f"{type(exc).__name__}: {exc}"
            try:
                self._done.emit(generation, added, error, wsl_dir if need_wsl else "\0", wsl_state)
            except RuntimeError:
                pass

        self._spawn(work)
        return True

    def _on_done(self, generation: int, added: int, error: str, wsl_dir: str, wsl_state: str) -> None:
        if generation != self._generation:
            return
        self._busy = False
        self.wsl_scan_state = wsl_state
        if wsl_dir != "\0":
            self._wsl_dir = wsl_dir
            self._probing_wsl = False
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
        stats["wsl"] = {"state": self.wsl_scan_state if self.settings()["scan_wsl"] else WSL_OFF,
                        "files": int(stats.get("files_remote", 0))}
        entries = self.entries().load()
        for key, side in (("distill", md.SIDE_PERSONAL), ("distill_work", md.SIDE_WORK)):
            state = self.distill_state(side)
            stats[key] = {"busy": side in self._distilling, "last_run_at": state.get("last_run_at", ""),
                          "last_error": state.get("last_error", ""), "last_result": state.get("last_result") or {},
                          "attempts": int(state.get("attempts") or 0)}
        stats["proposals"] = self.proposals().counts()
        for key, items in (("entries", entries), ("entries_work", self.entries(md.SIDE_WORK).load())):
            stats[key] = {"global": sum(1 for e in items if not e.retired and e.scope == "global"),
                          "project": sum(1 for e in items if not e.retired and e.scope == "project"),
                          "retired": sum(1 for e in items if e.retired)}
        stats["vault"] = {"state": self.sync_state, "error": self.sync_error, "dir": self.vault_dir()}
        return stats

    # ---------------------------------------------------------- 蒸馏（第二期）
    @property
    def root(self) -> Path:
        return md.store_root(self._config.dir)

    def distill_state(self, side: str = md.SIDE_PERSONAL) -> dict:
        return run.load_state(self.root, side)

    def proposals(self) -> run.ProposalStore:
        return run.ProposalStore(self.root)

    def entries(self, side: str = md.SIDE_PERSONAL) -> sink.EntriesStore:
        return sink.EntriesStore(self.root, side)

    def vault_dir(self) -> str:
        return pv.normalize(self._config.get(pv.CONFIG_KEY))["repo_dir"]

    @property
    def distilling(self) -> bool:
        return bool(self._distilling)

    def is_distilling(self, side: str) -> bool:
        return side in self._distilling

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

    def distill_now(self, manual: bool = True, side: str = md.SIDE_PERSONAL) -> bool:
        """把上次之后这一侧的候选交给模型，提案进提案库。后台线程；这一侧忙着不叠加。

        两侧走的路完全分开：个人侧用「AI 对话」里的服务商（个人 key）；公司侧只经 ``wsl.exe`` 交给 WSL 里登录着
        公司账号的 Claude Code，现有记忆也读 WSL 那份——公司会话的原话、公司侧的记忆与拒过的标题都不进个人 key。"""
        if side in self._distilling:
            return False
        now = self._now()
        settings = md.side_settings(self.settings(), side)
        state = self.distill_state(side)
        root, home = self.root, self._home
        provider, memory_fn = None, None
        entries_text = "\n".join(f"- [{e.scope}{' ' + e.project if e.project else ''}] {e.title} — {e.how or e.why}"
                                 for e in self.entries(side).active())      # 只带这一侧已落盘的条目
        if side == md.SIDE_WORK:
            runner = self._wsl_runner
            complete = mdw.make_complete(runner)

            def memory_fn(picked: list[dict]) -> str:
                return mdw.memory_context(picked, runner=runner, entries_text=entries_text)
        else:
            try:
                provider = self._resolve_provider()
                complete = self._resolve_complete()
            except Exception as exc:  # noqa: BLE001 - 没装聊天模块 / 没配 key
                result = run.RunResult(error=str(exc) or type(exc).__name__, run_at=now.isoformat(timespec="seconds"),
                                       side=side)
                run.save_state(root, {**run.mark_attempt(state, now), "last_error": result.error}, side)
                self.last_run = result
                self.distilled.emit(result, manual)
                self.changed.emit()
                return False
        self._distilling.add(side)
        generation = self._generation
        rows = self.store.read_all()
        store = self.proposals()

        def work() -> None:
            try:
                result, new_state = run.run_once(now, settings, rows, state, provider, store=store, complete=complete,
                                                 home=home, entries_text=entries_text, side=side, memory_fn=memory_fn)
                run.save_state(root, new_state, side)
            except Exception as exc:  # noqa: BLE001 - 不让线程静默死掉
                log.exception("会话记忆蒸馏：蒸馏失败")
                result = run.RunResult(error=f"{type(exc).__name__}: {exc}", run_at=now.isoformat(timespec="seconds"),
                                       side=side)
            try:
                self._distill_done.emit(generation, result, manual, side)
            except RuntimeError:
                pass

        self.changed.emit()                  # 先让页面显示「正在总结」，再起线程（测试里线程是同步的）
        self._spawn(work)
        return True

    def _on_distill_done(self, generation: int, result, manual: bool, side: str) -> None:
        if generation != self._generation:
            return
        self._distilling.discard(side)
        self.last_run = result
        self.changed.emit()                  # 先重摆数字（会清状态行），再报这一次的结果
        self.distilled.emit(result, manual)

    def review(self, pid: str, status: str, *, title: str | None = None, why: str | None = None,
               how: str | None = None) -> sink.Applied | None:
        """用户审一条：接受就立刻落盘（文件写入很快，在 GUI 线程），镜像推送另起线程；拒 / 跳过只记状态。

        公司侧的提案接受后落在 WSL 里，要起几次 wsl.exe（发行版冷启动要几秒）：放后台线程，这里立刻返回 None，
        结果从 ``reviewed`` 信号回来。两侧的落点完全分开——公司侧不碰个人侧的 CLAUDE.md / 项目 memory / 知识库。"""
        store = self.proposals()
        proposal = store.get(pid)
        if proposal is None or status not in run.STATUSES or pid in self._applying:
            return None
        if title is not None and title.strip():
            edited = " ".join(title.split())
            if edited != proposal.title and proposal.action in ("change", "retire") and not proposal.replaces:
                proposal.replaces = proposal.title     # 没写 replaces 时标题就是「指哪条」；改了措辞也得还指着它
            proposal.title = edited
        if why is not None:
            proposal.why = why.strip()
        if how is not None:
            proposal.how = how.strip()
        now = self._now()
        proposal.status = status
        proposal.reviewed_at = now.isoformat(timespec="seconds")
        applied = None
        if status == run.STATUS_ACCEPTED and proposal.side == md.SIDE_WORK:
            self._apply_work(proposal, now)
            return None
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

    def _apply_work(self, proposal: run.Proposal, now: dt.datetime) -> None:
        """公司侧提案落盘（后台线程）。提案库在这里先不动：落成了才记「已接受」，没落成还留在待审里。"""
        self._applying.add(proposal.id)
        generation = self._generation
        entries, runner, backup_dir = self.entries(md.SIDE_WORK), self._wsl_runner, self.root / sink.BACKUP_DIR

        def work() -> None:
            try:
                applied = wsink.apply_proposal(proposal, now, entries=entries, runner=runner, backup_dir=backup_dir)
            except Exception as exc:  # noqa: BLE001 - 不让线程静默死掉
                log.exception("会话记忆蒸馏：公司侧落盘失败")
                applied = sink.Applied(error=f"{type(exc).__name__}: {exc}", side=md.SIDE_WORK)
            try:
                self._review_done.emit(generation, proposal, applied)
            except RuntimeError:
                pass

        self._spawn(work)

    def _on_review_done(self, generation: int, proposal, applied) -> None:
        if generation != self._generation:
            return
        self._applying.discard(proposal.id)
        proposal.applied = applied.to_dict()
        proposal.status = run.STATUS_PENDING if applied.error else run.STATUS_ACCEPTED
        self.proposals().update(proposal)
        self.reviewed.emit(proposal.id, applied)
        self.changed.emit()

    def sync_vault(self) -> bool:
        """把知识库里那篇 commit + push（后台线程）。"""
        if self._syncing:
            return False
        repo_dir = self.vault_dir()
        if not repo_dir or not Path(repo_dir).is_dir():
            return False
        self._syncing = True
        self.sync_state = "pushing"
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

    def open_in_vscode(self, key: str) -> tuple[str, str]:
        """在 WSL 里对这个入口的目录执行 ``code .``：``wsl.exe -d <发行版> -e sh -c "cd <目录> && code ."``。
        后台线程（发行版冷启动要几秒），结果从 ``vscode_done`` 回来；这里立刻返回
        ``("launching" | "not_wsl" | "missing", 路径)``。

        实测（2026-10-31）：Windows 侧 ``code --remote wsl+<发行版> <路径>`` 返回 0 却不开窗口，
        WSL 里 ``code .`` 立刻开出远程窗口——所以走 WSL 这边。"""
        place = self.place(key)
        if place is None or not place.path:
            return "missing", ""
        if not place.wsl:
            return "not_wsl", place.path
        _wsl, distro, inner = vw.parse_directory(place.path, default_distro=lambda: "")
        runner, path = self._wsl_runner, place.path
        argv = ["-d", distro, "-e", "sh", "-c", f"cd {shlex.quote(inner)} && code ."]

        def work() -> None:
            try:
                code, out = runner(argv, timeout=60)
            except Exception as exc:  # noqa: BLE001 - 报给页面
                code, out = 1, f"{type(exc).__name__}: {exc}"
            try:
                self._vscode_done.emit(code == 0, path, "" if code == 0 else (out.strip()[-200:] or f"exit {code}"))
            except RuntimeError:
                pass

        self._spawn(work)
        return "launching", path

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
