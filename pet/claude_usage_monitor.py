# -*- coding: utf-8 -*-
"""今日用量的定时刷新：灵动岛信息槽「今日用量」的数据来源（GUI 线程上的 QObject）。

``set_active(True)`` 起：立刻量一次，之后每分钟一次；``set_active(False)`` 停表，在途
的结果作废。只有信息槽选了「今日用量」且灵动岛开着时才是 active——别的时候零开销。

量用量（``claude_usage.UsageMeter.refresh``）要读文件，放在 daemon 线程里跑，结果经
信号排队回本对象所在的 GUI 线程。进程内共用一只 ``UsageMeter``：它是增量的，记着每个
文件读到哪了（首次约 0.1 秒，之后通常 2 毫秒）。
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from . import claude_usage

log = logging.getLogger(__name__)

_meter: claude_usage.UsageMeter | None = None


def _default_measure() -> claude_usage.UsageTotals:
    global _meter
    if _meter is None:
        _meter = claude_usage.UsageMeter()
    return _meter.refresh()


def _spawn_thread(target: Callable[[], None]) -> None:
    threading.Thread(target=target, daemon=True, name="pet-claude-usage").start()


class ClaudeUsageMonitor(QObject):
    """今天用了多少 token：``usage_changed(信息槽文案, 悬停说明)``。"""

    usage_changed = Signal(str, str)
    _measured = Signal(int, object)         # worker 线程 → GUI 线程（跨线程自动排队）

    INTERVAL_MS = 60_000

    def __init__(self, *, measure: Callable | None = None, spawn: Callable | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._measure = measure
        self._spawn = spawn or _spawn_thread
        self._active = False
        self._busy = False
        self._generation = 0
        self._last: tuple[str, str] | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(self.INTERVAL_MS)
        self._timer.timeout.connect(self.refresh)
        self._measured.connect(self._on_measured)

    def set_active(self, active: bool) -> None:
        active = bool(active)
        if active == self._active:
            return
        self._active = active
        self._generation += 1               # 开 / 关都换代：在途的旧结果作废
        self._busy = False
        self._last = None                   # 再打开要重新报一次
        if active:
            self._timer.start()
            self.refresh()
        else:
            self._timer.stop()

    def refresh(self) -> None:
        """立刻量一次（在途时不重复发起）。"""
        if not self._active or self._busy:
            return
        self._busy = True
        generation = self._generation
        measure = self._measure or _default_measure

        def run() -> None:
            try:
                totals = measure()
            except Exception:  # noqa: BLE001 - 对话记录是 Claude Code 的内部格式，随时可能变
                log.debug("今日用量：统计失败", exc_info=True)
                totals = None
            try:
                self._measured.emit(generation, totals)
            except RuntimeError:
                pass  # 应用正在退出：本对象已销毁

        try:
            self._spawn(run)
        except Exception:  # noqa: BLE001 - 起线程失败也要放开忙标志
            log.exception("今日用量：启动统计线程失败")
            self._busy = False

    def _on_measured(self, generation: int, totals) -> None:
        if generation != self._generation:
            return
        self._busy = False
        if totals is None:
            return
        announced = (totals.headline, totals.detail)
        if announced != self._last:
            self._last = announced
            self.usage_changed.emit(*announced)
