# -*- coding: utf-8 -*-
"""随手记整理任务的 Qt 侧：什么时候跑、在哪个线程跑、结果怎么回界面线程。整理本身在 ``capture_organize``。

什么时候跑：

- **记下之后**：等 ``delay_minutes`` 分钟（默认 2）再整理，连着记几条就攒成一次；0 = 立刻；
- **启动后 1 分钟**、**每小时兜底**：收件箱里有东西才跑（手机上的 Claude 拿不准留下的、上次失败没整理掉的）；
  空的就什么都不做，连运行记录都不记；
- **配置全景上点「现在整理」**：开关关着也照样跑（是用户点的）。

开关只管上面三种自动的。跑起来在 daemon 线程里（几十秒一条），结果经排队信号回界面线程；``stop()`` 之后晚到的结果作废。
git 和随手记推送共用个人助理那把锁（``PersonalService.git_lock``）：同一个克隆上一次只有一条 git。
信号 ``started(手动?)`` / ``finished(Result, 手动?)`` 和别的定时服务同一个样子，运行记录直接接在上面（``run_recording``）。
"""
from __future__ import annotations

import datetime as dt
import logging
import threading
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from . import capture_organize as co
from . import personal_vault as pv

log = logging.getLogger(__name__)


def _spawn_thread(target: Callable[[], None]) -> None:
    threading.Thread(target=target, daemon=True, name="pet-capture-organize").start()


class CaptureOrganizer(QObject):
    started = Signal(bool)
    finished = Signal(object, bool)
    _done = Signal(int, object, bool)

    STARTUP_DELAY_MS = 60_000
    CHECK_INTERVAL_MS = 60 * 60_000

    def __init__(self, config, *, organize: Callable | None = None, spawn: Callable | None = None,
                 now: Callable[[], dt.datetime] | None = None, lock=None, token: Callable[[], str] | None = None,
                 provider: Callable | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        from .personal_service import resolve_chat_provider

        self._config = config
        self._organize = organize or co.run
        self._spawn = spawn or _spawn_thread
        self._now = now or dt.datetime.now
        self._lock = lock or threading.Lock()
        self._token = token or pv.github_token
        self._provider = provider or (lambda: resolve_chat_provider(config))
        self._generation = 0
        self._busy = False
        self._hourly = QTimer(self)
        self._hourly.timeout.connect(self.check)
        self._after_capture = QTimer(self)
        self._after_capture.setSingleShot(True)
        self._after_capture.timeout.connect(self.check)
        self._done.connect(self._on_done)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.stop)

    # ---------------------------------------------------------- 读
    def settings(self) -> dict:
        return co.normalize(self._config.get(co.CONFIG_KEY))

    def repo_dir(self) -> str:
        return pv.normalize(self._config.get(pv.CONFIG_KEY))["repo_dir"]

    def pending_count(self) -> int:
        return co.count_pending(self.repo_dir())

    @property
    def busy(self) -> bool:
        return self._busy

    def capture_timer_ms(self) -> int:
        """记下之后那个计时器定的是等多久（0 = 没在等）。"""
        return self._after_capture.interval() if self._after_capture.isActive() else 0

    # ---------------------------------------------------------- 什么时候跑
    def start(self) -> None:
        QTimer.singleShot(self.STARTUP_DELAY_MS, self.check)
        self._hourly.start(self.CHECK_INTERVAL_MS)

    def stop(self) -> None:
        self._hourly.stop()
        self._after_capture.stop()
        self._generation += 1
        self._busy = False

    def note_capture(self, *_args) -> None:
        """记下了一条（接在 ``PersonalService.capture_saved`` 上）：开着就（重新）开始等那几分钟。"""
        settings = self.settings()
        if not settings["enabled"]:
            self._after_capture.stop()
            return
        self._after_capture.start(settings["delay_minutes"] * 60_000)

    def check(self) -> bool:
        """自动的那几种：开着、没在跑、克隆在、收件箱里有东西才跑。"""
        if self._busy or not self.settings()["enabled"]:
            return False
        repo_dir = self.repo_dir()
        if not pv.repo_ready(repo_dir):
            return False
        held = co.unchanged_held(self._config.dir, repo_dir)          # 整理不了、之后没改过的：不再拿去问模型
        if not set(co.pending_paths(repo_dir)) - held:
            return False
        return self._launch(manual=False, exclude=held) == "started"

    def organize_now(self) -> str:
        """配置全景的「现在整理」：started / busy / empty（收件箱空）/ missing（克隆不在）/ failed（没有能用的模型服务）。"""
        if self._busy:
            return "busy"
        repo_dir = self.repo_dir()
        if not pv.repo_ready(repo_dir):
            return "missing"
        if not co.count_pending(repo_dir):
            return "empty"
        return self._launch(manual=True)

    # ---------------------------------------------------------- 跑
    def _launch(self, *, manual: bool, exclude=frozenset()) -> str:
        settings, now, repo_dir = self.settings(), self._now(), self.repo_dir()
        try:
            provider = self._provider()
        except Exception as exc:  # noqa: BLE001 - 没装聊天模块 / 没有服务商
            from .i18n import t

            result = co.Result(error=f"{t('personal.error.not_claude')}（{type(exc).__name__}）")
            self.finished.emit(result, manual)
            return "failed"
        self._generation += 1
        self._after_capture.stop()
        generation, organize, lock, token = self._generation, self._organize, self._lock, self._token
        self._busy = True
        self.started.emit(manual)

        def run() -> None:
            try:
                result = organize(repo_dir, settings, provider, lock=lock, token=token, now=now, exclude=set(exclude))
            except Exception as exc:  # noqa: BLE001 - 线程不许带病退出
                result = co.Result(error=f"{type(exc).__name__}: {exc}")
            try:
                self._done.emit(generation, (repo_dir, result), manual)
            except RuntimeError:
                pass  # 应用正在退出

        try:
            self._spawn(run)
        except Exception:  # noqa: BLE001
            log.exception("随手记整理：启动后台线程失败")
            self._busy = False
            return "failed"
        return "started"

    def _on_done(self, generation: int, done, manual: bool) -> None:
        if generation != self._generation:
            return
        self._busy = False
        repo_dir, result = done
        if result.ok:
            try:
                co.remember_held(self._config.dir, repo_dir, list(result.held), self._now())
            except OSError:
                log.warning("随手记整理：记不下整理不了的那几条", exc_info=True)
        log.info("随手记整理%s：整理 %d 条 · 跳过 %d · 失败 %d · 还剩 %d · %s · 用时 %.0f 秒 · 输入 %d / 输出 %d tokens%s",
                 "完成" if result.ok else "失败", result.organized, result.skipped, result.failed, result.left, result.model,
                 result.seconds, result.tokens_in, result.tokens_out, "" if result.ok else f"：{str(result.error)[:120]}")
        self.finished.emit(result, manual)
