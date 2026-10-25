# -*- coding: utf-8 -*-
"""工作笔记的 Qt 侧：文件读写在 GUI 线程（本地 NTFS，毫秒级），总结与 git 在后台线程。

- ``add(text)``：立刻落盘、发 ``changed``，然后起一个 daemon 线程让 WSL 里的 Claude Code 总结
  （几十秒）；结果经信号排队回 GUI 线程，在那里**重新读一遍文件**再合并（用户可能已经在
  Obsidian 里改过），写回、再起线程 ``git add/commit/pull --rebase/push``。
- git 操作串行（一把锁）；总结可以并行（每条一个线程）。
- 每分钟看一眼有没有到点的提醒；只在人在电脑前（没锁屏、最近 10 分钟动过键鼠）时发
  ``reminder_due``，提醒过的时间点记在数据目录的状态文件里，不重复。
- 笔记文字不进日志。
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import threading
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from . import slack_watch as sw
from . import work_notes as wn
from .i18n import t

log = logging.getLogger(__name__)


def _spawn_thread(target: Callable[[], None]) -> None:
    threading.Thread(target=target, daemon=True, name="pet-work-notes").start()


#: 同一个仓库里 note/ 与 slack/ 两个服务的 git 操作串成一条（两把锁会撞 .git/index.lock）
_GIT_LOCK = threading.Lock()


def _open_target(target: str) -> bool:
    try:
        os.startfile(target)  # noqa: S606  （obsidian:// 协议或资源管理器打开文件夹）
        return True
    except (AttributeError, OSError):
        return False


class WorkNotesService(QObject):
    """``changed()``：笔记列表 / 内容变了；``summarized(name, ok, error)``；``synced(ok, error)``；
    ``reminder_due(Note)``：到点了、人也在。"""

    changed = Signal()
    summarized = Signal(str, bool, str)
    synced = Signal(bool, str)
    reminder_due = Signal(object)
    _summary_done = Signal(int, str, object)
    _sync_done = Signal(int, bool, str)

    STARTUP_DELAY_MS = 30_000
    CHECK_INTERVAL_MS = 60_000
    IDLE_LIMIT_S = 10 * 60

    def __init__(self, config, *, folder: str = wn.NOTES_DIR, label: str = "note", pull_on_start: bool = True,
                 summarize: Callable | None = None, sync: Callable | None = None,
                 pull: Callable | None = None, spawn: Callable | None = None,
                 now: Callable[[], dt.datetime] | None = None, active: Callable[[float], bool] | None = None,
                 opener: Callable[[str], bool] | None = None, parent: QObject | None = None) -> None:
        """``folder``：仓库里的子目录（``note`` = 工作笔记，``slack`` = Slack 关注存档）；``label`` 是提交说明的前缀。"""
        super().__init__(parent)
        self._config = config
        self._folder, self._label, self._pull_on_start = folder, label, pull_on_start
        self._summarize = summarize or wn.summarize
        self._sync = sync or wn.sync
        self._pull = pull or wn.pull
        self._spawn = spawn or _spawn_thread
        self._now = now or dt.datetime.now
        self._active = active or sw.session_active
        self._open = opener or _open_target
        self._generation = 0
        self._busy: set[str] = set()
        self._git_lock = _GIT_LOCK
        self._last_error = ""
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.check_reminders)
        self._summary_done.connect(self._on_summary_done)
        self._sync_done.connect(self._on_sync_done)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.stop)

    # ---------------------------------------------------------- 读
    def settings(self) -> dict:
        return wn.normalize(self._config.get(wn.CONFIG_KEY))

    def notes_dir(self) -> Path:
        return wn.notes_dir(self.settings(), self._folder)

    @property
    def folder(self) -> str:
        return self._folder

    def repo_ready(self) -> bool:
        """仓库副本在不在（``repo_dir/.git``）；不在的话笔记照样能记，只是推不上去。"""
        return (Path(self.settings()["repo_dir"]) / ".git").exists()

    def notes(self) -> list[wn.Note]:
        return wn.load_all(self.notes_dir())

    def note(self, name: str) -> wn.Note | None:
        return wn.load(self.notes_dir(), name)

    @property
    def busy_names(self) -> frozenset[str]:
        return frozenset(self._busy)

    def last_error(self) -> str:
        return self._last_error

    # ---------------------------------------------------------- 写
    def add(self, text: str) -> wn.Note | None:
        """记一条：立刻落盘，然后后台总结。空的不记。"""
        if not str(text or "").strip():
            return None
        note = wn.new_note(text, self._now())
        try:
            wn.save(self.notes_dir(), note)
        except OSError as exc:
            self._last_error = t("notes.sync.write_failed", error=exc.strerror or exc)
            log.warning("工作笔记：写文件失败", exc_info=True)
            self.changed.emit()
            return None
        self.changed.emit()
        # 先把原文推上去（总结可能失败，原文不能因此留在本地）；总结完再推一次
        self._start_sync(f"{self._label}: 记一条")
        self._start_summary(note)
        return note

    def add_slack_items(self, items: list[dict]) -> list[wn.Note]:
        """Slack 关注查到的新条目各存一条（不让 Claude 再读一遍），一起推一次；同一条链接 / 同一键已经存过的跳过。
        返回这次新存的那些。"""
        existing = self.notes()
        seen_links = {link for note in existing for link in note.links}
        seen_keys = {f"{note.original.splitlines()[0]}" for note in existing if note.original}
        folder, now, made = self.notes_dir(), self._now(), []
        for item in items:
            if not isinstance(item, dict) or not str(item.get("title") or "").strip():
                continue
            note = wn.note_from_slack_item(item, now)
            head = note.original.splitlines()[0] if note.original else ""
            if (note.links and note.links[0] in seen_links) or (not note.links and head in seen_keys):
                continue
            note = note.replace(name=wn.unique_name(folder, note.name))
            try:
                wn.save(folder, note)
            except OSError as exc:
                self._last_error = t("notes.sync.write_failed", error=exc.strerror or exc)
                log.warning("Slack 关注：写存档文件失败", exc_info=True)
                break
            seen_links.update(note.links)
            seen_keys.add(head)
            made.append(note)
        if made or self._last_error:
            self.changed.emit()
        if made:
            self._start_sync(f"{self._label}: {len(made)} 条")
        return made

    def resummarize(self, name: str) -> bool:
        note = self.note(name)
        if note is None or name in self._busy:
            return False
        self._start_summary(note)
        return True

    def mark_done(self, name: str) -> wn.Note | None:
        return self._update(name, wn.finish, f"{self._label}: 完成")

    def snooze(self, name: str, minutes: int) -> wn.Note | None:
        return self._update(name, lambda note: wn.snooze(note, minutes, self._now()), f"{self._label}: 稍后再提醒")

    def _update(self, name: str, change: Callable[[wn.Note], wn.Note], message: str) -> wn.Note | None:
        note = self.note(name)
        if note is None:
            return None
        updated = change(note)
        try:
            wn.save(self.notes_dir(), updated)
        except OSError as exc:
            self._last_error = t("notes.sync.write_failed", error=exc.strerror or exc)
            self.changed.emit()
            return None
        self.changed.emit()
        self._start_sync(message)
        return updated

    def delete(self, name: str) -> wn.Note | None:
        """删一条：文件从 note/ 里删掉，再推一次（仓库与 Obsidian 里一起消失）。不存在返回 None。"""
        note = self.note(name)
        if note is None:
            return None
        try:
            (self.notes_dir() / note.filename).unlink()
        except OSError as exc:
            self._last_error = f"删不掉笔记文件：{exc.strerror or exc}"
            self.changed.emit()
            return None
        self._busy.discard(name)
        self.changed.emit()
        self._start_sync(f"{self._label}: 删除")
        return note

    def open_link(self, name: str) -> bool:
        """在浏览器 / Slack 里打开这条的第一个链接；没有链接返回 False。"""
        note = self.note(name)
        if note is None or not note.links:
            return False
        return bool(self._open(note.links[0]))

    def open_in_obsidian(self, name: str) -> bool:
        """在 Obsidian 里打开这条；仓库没登记成库就退回打开文件夹，返回 False 让调用方提示一句。"""
        note = self.note(name)
        uri = wn.obsidian_uri(self.settings()["repo_dir"], note, folder=self._folder) if note is not None else ""
        self._open(uri or str(self.notes_dir()))
        return bool(uri)

    def open_folder(self) -> None:
        folder = self.notes_dir()
        folder.mkdir(parents=True, exist_ok=True)
        self._open(str(folder))

    # ---------------------------------------------------------- 后台：总结
    #: 总结失败自动再试的次数（模型偶尔不按约定输出 JSON 或用完轮数；实测同一条第二次就成了）
    RETRIES = 1

    def _start_summary(self, note: wn.Note, *, attempt: int = 0) -> None:
        self._busy.add(note.name)
        generation, summarize = self._generation, self._summarize
        settings = self.settings()
        now, model, name = self._now(), settings["model"], note.name
        # 用户改过的提示词按界面语言取（空 = 内置）；effort 一并带过去
        extra = {"effort": settings.get("effort", wn.wb.EFFORT),
                 "template": settings.get(f"prompt_{wn.wb.prompt_language()}", "")}

        def run() -> None:
            try:
                result = summarize(note, now, model, **extra)
            except Exception as exc:  # noqa: BLE001
                result = wn.SummaryResult(error=t("notes.sync.summary_crashed", name=type(exc).__name__))
            try:
                self._summary_done.emit(generation, name, (result, attempt))
            except RuntimeError:
                pass

        try:
            self._spawn(run)
        except Exception:  # noqa: BLE001
            log.exception("工作笔记：启动总结线程失败")
            self._busy.discard(note.name)
        self.changed.emit()

    def _on_summary_done(self, generation: int, name: str, payload) -> None:
        if generation != self._generation:
            return
        result, attempt = payload if isinstance(payload, tuple) else (payload, self.RETRIES)
        self._busy.discard(name)
        note = self.note(name)
        if note is None:
            self.summarized.emit(name, False, "笔记文件不见了")
            self.changed.emit()
            return
        if not result.ok and attempt < self.RETRIES and "WSL" not in result.error:
            log.info("工作笔记：总结失败（第 %d 次），再试一次", attempt + 1)
            self._start_summary(note, attempt=attempt + 1)
            return
        if result.ok:
            try:
                wn.save(self.notes_dir(), wn.apply_summary(note, result, self._now()))
            except OSError as exc:
                result = wn.SummaryResult(error=t("notes.sync.write_failed", error=exc.strerror or exc))
        self._last_error = "" if result.ok else result.error
        log.info("工作笔记：总结%s，用时 %.0f 秒，%d 轮%s", "完成" if result.ok else "失败", result.seconds,
                 result.turns, f"，被拒的工具 {len(result.denied)} 个" if result.denied else "")
        self.changed.emit()
        self.summarized.emit(name, result.ok, result.error)
        if result.ok:
            self._start_sync(f"{self._label}: 总结")

    # ---------------------------------------------------------- 后台：git
    def _start_sync(self, message: str) -> None:
        generation, sync, settings, lock = self._generation, self._sync, self.settings(), self._git_lock

        def run() -> None:
            with lock:
                try:
                    ok, out = sync(settings, message)
                except Exception as exc:  # noqa: BLE001
                    ok, out = False, t("notes.sync.commit_crashed", name=type(exc).__name__)
            try:
                self._sync_done.emit(generation, ok, out)
            except RuntimeError:
                pass

        try:
            self._spawn(run)
        except Exception:  # noqa: BLE001
            log.exception("工作笔记：启动 git 线程失败")

    def push_now(self) -> None:
        """再推一次（比如在终端里过了公司 git 钩子的检查之后）：本地已提交的都带上。"""
        self._start_sync(f"{self._label}: push")

    def pull_now(self) -> None:
        """启动时拉一次远端（别的机器 / 公司 AI 可能写过）。"""
        generation, pull, settings, lock = self._generation, self._pull, self.settings(), self._git_lock

        def run() -> None:
            with lock:
                try:
                    ok, out = pull(settings)
                except Exception as exc:  # noqa: BLE001
                    ok, out = False, t("notes.sync.pull_crashed", name=type(exc).__name__)
            try:
                self._sync_done.emit(generation, ok, out)
            except RuntimeError:
                pass

        try:
            self._spawn(run)
        except Exception:  # noqa: BLE001
            log.exception("工作笔记：启动 git 线程失败")

    def _on_sync_done(self, generation: int, ok: bool, out: str) -> None:
        if generation != self._generation:
            return
        self._last_error = "" if ok else wn.describe_sync_failure(out)
        if not ok:
            log.warning("工作笔记：git 失败：%s", out[-200:])
        self.changed.emit()
        self.synced.emit(ok, "" if ok else out)

    # ---------------------------------------------------------- 提醒
    def is_active(self) -> bool:
        return bool(self._active(self.IDLE_LIMIT_S))

    def check_reminders(self) -> list[wn.Note]:
        """到点、人在 → 记下已提醒、发 ``reminder_due``。"""
        try:
            if not self.is_active():
                return []
            state = wn.load_state(self._config.dir)
            due = wn.due_reminders(self.notes(), state, self._now())
            for note in due:
                wn.mark_alerted(state, note)
            if due:
                wn.save_state(self._config.dir, state)
        except Exception:  # noqa: BLE001
            log.exception("工作笔记：检查提醒失败")
            return []
        for note in due:
            self.reminder_due.emit(note)
        return due

    def start(self) -> None:
        if self._pull_on_start and self.repo_ready():
            QTimer.singleShot(self.STARTUP_DELAY_MS, self.pull_now)
        self._timer.start(self.CHECK_INTERVAL_MS)

    def stop(self) -> None:
        self._timer.stop()
        self._generation += 1
        self._busy.clear()
