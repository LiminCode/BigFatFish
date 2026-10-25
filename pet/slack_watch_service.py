# -*- coding: utf-8 -*-
"""Slack 关注的定时与后台线程（判断与生成见 ``slack_watch.py``）。

每分钟看一眼「该不该查」：开关开着、人在电脑前、距上次够了一个间隔。真要查时在 daemon 线程里跑
（一次 wsl.exe，几十秒），结果经信号排队回到 GUI 线程，在那里落盘、算出哪些是新的，发 ``finished``。
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from . import slack_watch as sw

log = logging.getLogger(__name__)


def _spawn_thread(target: Callable[[], None]) -> None:
    threading.Thread(target=target, daemon=True, name="pet-slack-watch").start()


class SlackWatchService(QObject):
    """``started(手动?)`` / ``finished(WatchResult, 手动?, 新条目列表)``。"""

    started = Signal(bool)
    finished = Signal(object, bool, object)
    _done = Signal(int, object, bool)

    STARTUP_DELAY_MS = 90_000
    CHECK_INTERVAL_MS = 60_000

    def __init__(self, config, *, generate: Callable | None = None, spawn: Callable | None = None,
                 now: Callable[[], dt.datetime] | None = None, active: Callable[[float], bool] | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._generate = generate or sw.generate
        self._spawn = spawn or _spawn_thread
        self._now = now or dt.datetime.now
        self._active = active or sw.session_active
        self._generation = 0
        self._busy = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.check)
        self._done.connect(self._on_done)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.stop)

    @property
    def busy(self) -> bool:
        return self._busy

    def settings(self) -> dict:
        return sw.normalize(self._config.get(sw.CONFIG_KEY))

    def latest(self) -> sw.WatchResult | None:
        return sw.latest(self._config.dir)

    def last_error(self) -> str:
        return str(sw.load_state(self._config.dir).get("error") or "")

    def start(self) -> None:
        QTimer.singleShot(self.STARTUP_DELAY_MS, self.check)
        self._timer.start(self.CHECK_INTERVAL_MS)

    def stop(self) -> None:
        self._timer.stop()
        self._generation += 1
        self._busy = False

    def is_active(self) -> bool:
        """人在电脑前（没锁屏、最近动过键鼠）。"""
        return bool(self._active(self.settings()["idle_minutes"] * 60))

    def check(self) -> bool:
        if self._busy:
            return False
        try:
            settings = self.settings()
            due = sw.is_due(settings, sw.load_state(self._config.dir), self._now(), active=self.is_active())
        except Exception:  # noqa: BLE001
            log.exception("Slack 关注：读取配置失败")
            return False
        return due and self._launch(manual=False)

    def check_now(self) -> bool:
        """用户点了「现在检查」：不看开关和人在不在。已经在查就返回 False。"""
        return not self._busy and self._launch(manual=True)

    def _launch(self, *, manual: bool) -> bool:
        self._generation += 1
        generation, generate = self._generation, self._generate
        now = self._now()
        since, model = sw.since_for(sw.load_state(self._config.dir), now), self.settings()["model"]
        self._busy = True
        self.started.emit(manual)

        def run() -> None:
            try:
                result = generate(now, since, model)
            except Exception as exc:  # noqa: BLE001
                result = sw.WatchResult(error=f"检查时出错：{type(exc).__name__}",
                                        checked_at=now.isoformat(timespec="seconds"))
            try:
                self._done.emit(generation, result, manual)
            except RuntimeError:
                pass

        try:
            self._spawn(run)
        except Exception:  # noqa: BLE001
            log.exception("Slack 关注：启动后台线程失败")
            self._busy = False
            return False
        return True

    def _on_done(self, generation: int, result, manual: bool) -> None:
        if generation != self._generation:
            return
        self._busy = False
        fresh: list[dict] = []
        try:
            _state, fresh = sw.record(self._config.dir, result, self._now())
        except OSError:
            log.exception("Slack 关注：写状态文件失败")
        log.info("Slack 关注%s：用时 %.0f 秒，%d 轮，%d 条，新 %d 条%s", "完成" if result.ok else "失败",
                 result.seconds, result.turns, len(result.items), len(fresh),
                 f"，被拒的工具 {len(result.denied)} 个" if result.denied else "")
        self.finished.emit(result, manual, fresh)
