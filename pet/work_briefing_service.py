# -*- coding: utf-8 -*-
"""工作简报的定时与后台线程（生成本身见 ``work_briefing.py``）。

每分钟看一眼「该不该生成」：开关开着、到了设定的时刻、今天还没有。判断只读配置和一个
很小的状态文件；真要生成时在 daemon 线程里跑（两次 wsl.exe，合计几十秒），结果经信号
排队回到本对象所在的 GUI 线程，在那里落盘并发出 ``finished``。

每次检查都重新读配置，所以菜单里改了开关或时间之后最迟一分钟生效。日志只记成败和
用时，不记简报的文字。
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from . import work_briefing as wb

log = logging.getLogger(__name__)


def _spawn_thread(target: Callable[[], None]) -> None:
    threading.Thread(target=target, daemon=True, name="pet-work-briefing").start()


class WorkBriefingService(QObject):
    """``started(手动?)`` / ``finished(Briefing, 手动?)``。"""

    started = Signal(bool)
    finished = Signal(object, bool)
    _done = Signal(int, object, bool)       # worker 线程 → GUI 线程（跨线程自动排队）

    STARTUP_DELAY_MS = 20_000
    CHECK_INTERVAL_MS = 60_000

    def __init__(self, config, *, generate: Callable | None = None, spawn: Callable | None = None,
                 now: Callable[[], dt.datetime] | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._generate = generate or wb.generate
        self._spawn = spawn or _spawn_thread
        self._now = now or dt.datetime.now
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
        return wb.normalize(self._config.get(wb.CONFIG_KEY))

    def latest(self) -> wb.Briefing | None:
        return wb.latest(self._config.dir)

    def last_error(self) -> str:
        return str(wb.load_state(self._config.dir).get("error") or "")

    def start(self) -> None:
        """开始定时检查；第一次延后 ``STARTUP_DELAY_MS``，不和启动抢时间。"""
        QTimer.singleShot(self.STARTUP_DELAY_MS, self.check)
        self._timer.start(self.CHECK_INTERVAL_MS)

    def stop(self) -> None:
        """停表；在途的结果作废（线程是 daemon，随进程结束）。"""
        self._timer.stop()
        self._generation += 1
        self._busy = False

    def check(self) -> bool:
        """到点就生成一次；返回是否真的发起了。"""
        if self._busy:
            return False
        try:
            due = wb.is_due(self.settings(), wb.load_state(self._config.dir), self._now())
        except Exception:  # noqa: BLE001 - 配置读坏了也不能让定时器带病
            log.exception("工作简报：读取配置失败")
            return False
        return due and self._launch(manual=False)

    def generate_now(self) -> bool:
        """用户点了「现在生成」：不看开关和时刻。已经在生成就返回 False。"""
        return not self._busy and self._launch(manual=True)

    def _launch(self, *, manual: bool) -> bool:
        self._generation += 1
        generation, generate = self._generation, self._generate
        settings = self.settings()
        now, model, sources = self._now(), settings["model"], settings["sources"]
        # 用户改过的提示词按界面语言取（空 = 内置）；effort 与优先级偏好一并带过去
        extra = {"effort": settings.get("effort", wb.EFFORT),
                 "template": settings.get(f"prompt_{wb.prompt_language()}", ""),
                 "priority_rules": settings.get("priority_rules", "")}
        self._busy = True
        self.started.emit(manual)

        def run() -> None:
            try:
                briefing = generate(now, model, sources=sources, **extra)
            except Exception as exc:  # noqa: BLE001 - 任何失败都算「这次没生成」，线程不许带病退出
                briefing = wb.Briefing(error=f"生成时出错：{type(exc).__name__}")
            try:
                self._done.emit(generation, briefing, manual)
            except RuntimeError:
                pass  # 应用正在退出：本对象已销毁

        try:
            self._spawn(run)
        except Exception:  # noqa: BLE001 - 起线程失败也要释放忙状态
            log.exception("工作简报：启动后台线程失败")
            self._busy = False
            return False
        return True

    def _on_done(self, generation: int, briefing, manual: bool) -> None:
        if generation != self._generation:
            return  # 已停止：晚到的旧结果
        self._busy = False
        try:
            wb.record(self._config.dir, briefing, self._now())
        except OSError:
            log.exception("工作简报：写状态文件失败")
        log.info("工作简报%s：用时 %.0f 秒，%d 轮%s", "生成完成" if briefing.ok else "生成失败",
                 briefing.seconds, briefing.turns, f"，被拒的工具 {len(briefing.denied)} 个" if briefing.denied else "")
        self.finished.emit(briefing, manual)
