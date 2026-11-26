# -*- coding: utf-8 -*-
"""随手记复习的 Qt 侧：给复习页今天的那一轮、收「记得 / 模糊 / 忘了」、攒一攒再推。逻辑在 ``capture_review``。

- **打分**在界面线程上：只改那条笔记的 ``review`` 一行（几毫秒）。拿 git 锁最多等 2 秒——正在推送时改文件会和 rebase 打架，
  等不到就回 ``busy``，页面让用户再点一次。
- **推送**一轮一个提交（``Review: N notes``）：这一轮打完了就推；没打完就在最后一次打分 2 分钟后推；启动时有上次没推的也推。
  在 daemon 线程里跑，和随手记推送、整理任务共用个人助理那把锁。还没推的几条记在本机（``capture-review.json``），关掉肥鱼也不丢。
- 信号：``changed()`` 页面该重画了；``started(手动?)`` / ``finished(ReviewPush, 手动?)`` 是一次推送，运行记录接在上面。
"""
from __future__ import annotations

import datetime as dt
import logging
import random
import threading
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from . import capture_organize as co
from . import capture_review as cr
from . import personal_vault as pv

log = logging.getLogger(__name__)


def _spawn_thread(target: Callable[[], None]) -> None:
    threading.Thread(target=target, daemon=True, name="pet-capture-review").start()


def _session_active() -> bool:
    from .slack_watch import session_active

    return session_active(ReviewService.ACTIVE_IDLE_S)


def _head(repo_dir) -> str:
    code, out = pv.run_git(repo_dir, ["rev-parse", "HEAD"])
    return out.strip()[:12] if code == 0 else ""


@dataclass
class ReviewPush:
    ok: bool = False
    state: str = "failed"         # ok / failed
    notes: int = 0
    commit: str = ""
    error: str = ""


class ReviewService(QObject):
    changed = Signal()
    remind = Signal(str, object)        # daily {count} / random {path, title}
    started = Signal(bool)
    finished = Signal(object, bool)
    _done = Signal(int, object, object, bool)

    FLUSH_DELAY_MS = 120_000
    STARTUP_DELAY_MS = 30_000
    LOCK_WAIT_S = 2.0
    CHECK_INTERVAL_MS = 60_000
    ACTIVE_IDLE_S = 5 * 60              # 随机那一下：最近 5 分钟动过键鼠才算人在

    def __init__(self, config, *, lock=None, token: Callable[[], str] | None = None, now: Callable[[], dt.datetime] | None = None,
                 spawn: Callable | None = None, sync: Callable | None = None, head: Callable | None = None,
                 active: Callable[[], bool] | None = None, rng=None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._lock = lock or threading.Lock()
        self._token = token or pv.github_token
        self._now = now or dt.datetime.now
        self._spawn = spawn or _spawn_thread
        self._sync = sync or pv.sync_path
        self._head = head or _head
        self._active = active or _session_active
        self._rng = rng or random.Random()
        self._check_timer = QTimer(self)
        self._check_timer.timeout.connect(self.check_reminders)
        self._generation = 0
        self._pushing = False
        self._sync_state, self._sync_error, self._pushed_at = "idle", "", ""
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.timeout.connect(lambda: self.flush(manual=False))
        self._done.connect(self._on_done)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.stop)

    # ---------------------------------------------------------- 读
    def repo_dir(self) -> str:
        return pv.normalize(self._config.get(pv.CONFIG_KEY))["repo_dir"]

    def repo_ready(self) -> bool:
        return pv.repo_ready(self.repo_dir())

    def today(self) -> dt.date:
        return self._now().date()

    def settings(self) -> dict:
        return co.normalize(self._config.get(co.CONFIG_KEY))

    def round(self, limit: int | None = None) -> dict:
        """今天这一轮：``{cards（ReviewNote，按顺序）, due（一共到期几条）, done（今天复习了几条）, next（之后最早哪天到期）}``。
        一轮几条按设置（``review_batch``）；随机冒出来、用户点了「看看」的那条（spotlight）不管到没到期都排第一张。"""
        items, today = cr.notes(self.repo_dir()), self.today()
        batch, total = cr.due(items, today, limit=limit or self.settings()["review_batch"])
        spot = cr.load_state(self._config.dir)["spotlight"]
        picked = next((note for note in items if note.path == spot), None) if spot else None
        if picked is not None:
            batch = [picked, *(note for note in batch if note.path != spot)]
        return {"cards": batch, "due": total, "done": cr.done_today(self._config.dir, today), "next": cr.next_due(items, today)}

    def spotlight(self, rel_path: str) -> None:
        """随机提醒上点了「看看」：这条排到复习页第一张，打完分就回原位。"""
        try:
            cr.mark(self._config.dir, spotlight=rel_path)
        except OSError:
            log.warning("复习：记不下要先看的那条", exc_info=True)
        self.changed.emit()

    def due_count(self) -> int:
        return cr.due(cr.notes(self.repo_dir()), self.today())[1]

    def pending(self) -> list[str]:
        return cr.load_state(self._config.dir)["pending"]

    @property
    def sync_state(self) -> str:
        return self._sync_state

    @property
    def sync_error(self) -> str:
        return self._sync_error

    @property
    def pushed_at(self) -> str:
        return self._pushed_at

    # ---------------------------------------------------------- 打分
    def grade(self, rel_path: str, answer: str) -> dict:
        """``{state: graded（带 next / interval）/ busy / missing / failed}``。"""
        if answer not in cr.ANSWERS:
            return {"state": "failed"}
        if not self._lock.acquire(timeout=self.LOCK_WAIT_S):
            return {"state": "busy"}
        try:
            review = cr.write_grade(self.repo_dir(), rel_path, answer, self.today())
        except cr.ReviewError:
            return {"state": "missing"}
        except OSError:
            log.warning("复习：写不进笔记", exc_info=True)
            return {"state": "failed"}
        finally:
            self._lock.release()
        try:
            state = cr.note_graded(self._config.dir, rel_path, self.today())
            if state["spotlight"] == rel_path:
                cr.mark(self._config.dir, spotlight="")
        except OSError:
            log.warning("复习：记不下还没推的那几条", exc_info=True)
        if self.due_count() == 0:
            self.flush(manual=False)                    # 这一轮打完了：现在就推
        else:
            self._flush_timer.start(self.FLUSH_DELAY_MS)
        self.changed.emit()
        return {"state": "graded", "next": review["next"].isoformat(), "interval": review["interval"]}

    # ---------------------------------------------------------- 提醒
    def check_reminders(self) -> str:
        """每分钟一次（界面线程，读一遍笔记头、几毫秒）：该提醒就发 ``remind`` 并记下今天提醒过。回发了哪种（空 = 没发）。
        今天随机那一下的时刻第一次看的时候定下来、记在本机。克隆不在、什么都读不到就什么都不做。"""
        if not self.repo_ready():
            return ""
        try:
            settings, now, config_dir = self.settings(), self._now(), self._config.dir
            today = now.date()
            state = cr.load_state(config_dir)
            if settings["review_random"] and state["random_date"] != today.isoformat():
                state = cr.mark(config_dir, random_date=today.isoformat(), random_at=cr.pick_slot(self._rng))
            items = cr.notes(self.repo_dir())
            batch, total = cr.due(items, today, limit=settings["review_batch"])
            want_random = settings["review_random"] and state["random_done"] != today.isoformat()
            kind = cr.decide(settings, state, now, due_count=total, active=bool(self._active()) if want_random else False,
                             notes=len(items))
            if kind == "daily":
                cr.mark(config_dir, daily=today.isoformat())
                self.remind.emit("daily", {"count": total})
            elif kind == "random":
                cr.mark(config_dir, random_done=today.isoformat())
                note = cr.random_pick(items, today, {n.path for n in batch}, self._rng)
                if note is None:
                    return ""
                self.remind.emit("random", {"path": note.path, "title": note.title})
            return kind
        except OSError:
            log.warning("复习：看提醒时读写失败", exc_info=True)
            return ""

    # ---------------------------------------------------------- 推送
    def start(self) -> None:
        if self.pending():
            QTimer.singleShot(self.STARTUP_DELAY_MS, lambda: self.flush(manual=False))
        QTimer.singleShot(self.STARTUP_DELAY_MS, self.check_reminders)
        self._check_timer.start(self.CHECK_INTERVAL_MS)

    def stop(self) -> None:
        self._check_timer.stop()
        self._flush_timer.stop()
        self._generation += 1
        self._pushing = False

    def flush(self, *, manual: bool = False) -> str:
        """把还没推的几条一起提交、推送：``started`` / ``busy`` / ``empty`` / ``missing``（克隆不在）。"""
        if self._pushing:
            return "busy"
        paths = self.pending()
        if not paths:
            return "empty"
        repo_dir = self.repo_dir()
        if not pv.repo_ready(repo_dir):
            return "missing"
        self._flush_timer.stop()
        self._generation += 1
        generation, lock, sync, head, token = self._generation, self._lock, self._sync, self._head, self._token
        self._pushing = True
        self._sync_state, self._sync_error = "pushing", ""
        self.started.emit(manual)
        self.changed.emit()

        def run() -> None:
            with lock:
                try:
                    ok, out = sync(repo_dir, paths, cr.commit_message(paths), token=token())
                    result = ReviewPush(ok=ok, state="ok" if ok else "failed", notes=len(paths), commit=head(repo_dir) if ok else "",
                                        error="" if ok else str(out or "push failed"))
                except Exception as exc:  # noqa: BLE001 - 线程不许带病退出
                    result = ReviewPush(notes=len(paths), error=f"{type(exc).__name__}: {exc}")
            try:
                self._done.emit(generation, paths, result, manual)
            except RuntimeError:
                pass

        try:
            self._spawn(run)
        except Exception:  # noqa: BLE001
            log.exception("复习：启动推送线程失败")
            self._pushing = False
            return "failed"
        return "started"

    def _on_done(self, generation: int, paths, result: ReviewPush, manual: bool) -> None:
        if generation != self._generation:
            return
        self._pushing = False
        if result.ok:
            try:
                cr.note_pushed(self._config.dir, list(paths))
            except OSError:
                log.warning("复习：记不下推完的那几条", exc_info=True)
            self._sync_state, self._sync_error, self._pushed_at = "pushed", "", f"{self._now():%H:%M}"
        else:
            log.warning("复习：推送失败：%s", result.error[-200:])
            self._sync_state, self._sync_error = "failed", result.error[-200:]
        self.finished.emit(result, manual)
        self.changed.emit()
