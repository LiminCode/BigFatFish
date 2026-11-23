# -*- coding: utf-8 -*-
"""知识库定时同步的 Qt 侧：每分钟看一眼「该不该跑」，该跑就在后台线程里叫同步器跑一次，结果经信号排回界面线程。

照个人助理 / 工作简报那几个服务的样子：定时器在界面线程；真要干活时起一条 daemon 线程；``stop()`` 之后晚到的结果作废
（generation 计数）。什么时候该跑、三种模式各做什么，都在 ``vault_sync``（纯逻辑）里，这里只管时钟和线程。

每分钟那一下做的事很少：

- 开关关着：什么都不做，连工作区都不看；
- 到了周期、刚启动而上次已过期、刚从睡眠醒来：直接跑；
- 否则，如果开着「停笔后同步」：起一条线程看一眼工作区（一条本地 ``git status``，几十毫秒），有正文改动而且已经停笔够久才跑。
  ``watch`` 模式不提交，所以不看工作区。

「上一次运行是什么时候」启动时从运行记录里取（``last_run``），之后自己记；页面上手点的那几次也算（``note_run``）——
用户刚点过「现在同步」，没必要十分钟后再自动跑一遍。配置每次检查都重新读，改了设置最迟一分钟生效。
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from . import personal_vault as pv
from . import vault_sync as vs

log = logging.getLogger(__name__)


def _spawn_thread(target: Callable[[], None]) -> None:
    threading.Thread(target=target, daemon=True, name="pet-vault-sync").start()


class VaultSyncService(QObject):
    """``finished(Outcome, 触发原因)``：一次定时运行结束（界面线程）。只有真的跑了才发；看了一眼没事可做不发。"""

    finished = Signal(object, str)
    _done = Signal(int, object, str, str)       # generation, Outcome 或 None, 触发原因, 这次看到的工作区指纹

    STARTUP_DELAY_MS = 40_000
    TICK_MS = 60_000

    def __init__(self, config, syncer, *, last_run: Callable[[], float | None] | None = None, spawn: Callable | None = None,
                 clock: Callable[[], float] | None = None, probe: Callable | None = None, after: Callable[[], object] | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config, self._syncer = config, syncer
        self._read_last_run = last_run or (lambda: None)
        self._spawn = spawn or _spawn_thread
        self._clock = clock or time.time
        self._probe = probe or vs.probe
        self._after = after                         # 跑完之后在后台线程上叫一声（时间轴页开着的话要重画）
        self._generation = 0
        self._busy = False
        self._started = False                       # 做过第一次检查了没有
        self._last_run: float | None = None
        self._last_tick: float | None = None
        self._attempted = ""                        # 上次运行时工作区的指纹：同一批改动不每分钟重试
        self._runs = 0                              # 这个服务发起并跑完了几次
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.tick)
        self._done.connect(self._on_done)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.stop)

    @property
    def busy(self) -> bool:
        return self._busy

    def start(self) -> None:
        QTimer.singleShot(self.STARTUP_DELAY_MS, self.tick)
        self._timer.start(self.TICK_MS)

    def stop(self) -> None:
        self._timer.stop()
        self._generation += 1
        self._busy = False

    def note_run(self) -> None:
        """别处刚跑过一次核对或同步（页面上手点的）：周期从现在重新算。只写一个数，哪条线程来叫都行。"""
        self._last_run = self._clock()

    def tick(self) -> bool:
        """（界面线程）看一眼该不该跑；返回是否真的发起了一次运行。"""
        if self._busy:
            return False
        try:
            settings = vs.normalize(self._config.get(vs.CONFIG_KEY))
            repo_dir = pv.normalize(self._config.get(pv.CONFIG_KEY))["repo_dir"]
        except Exception:  # noqa: BLE001 - 配置读坏了也不能让定时器带病
            log.exception("知识库定时同步：读取配置失败")
            return False
        now = self._clock()
        if not self._started and self._last_run is None:
            self._last_run = self._read_last_run()
        facts = {"now": now, "last_run": self._last_run, "last_tick": self._last_tick, "started": self._started, "attempted": self._attempted}
        self._last_tick, self._started = now, True
        if not settings["enabled"] or not pv.repo_ready(repo_dir):
            return False
        trigger = vs.decide(settings, probe=None, **facts)
        watching_edits = settings["idle_minutes"] > 0 and settings["mode"] != "watch"
        if not trigger and not watching_edits:
            return False
        generation, syncer, probe, after, runs_before = self._generation, self._syncer, self._probe, self._after, self._runs
        self._busy = True

        def work() -> None:
            seen, outcome, why = "", None, trigger
            try:
                if not why:                             # 不到周期：看看是不是停笔够久了
                    look = probe(repo_dir)
                    seen, why = look.fingerprint, vs.decide(settings, probe=look, **facts)
                if why:
                    if not seen and watching_edits:     # 记下这次带着哪批改动跑的；不看改动的模式用不着
                        seen = probe(repo_dir).fingerprint
                    outcome = syncer.run_scheduled(repo_dir, settings, why)
            except Exception as exc:  # noqa: BLE001 - 线程不许带病退出；记成失败
                log.exception("知识库定时同步：这次运行出错")
                outcome = vs.Outcome("failed", error=f"{type(exc).__name__}: {exc}")
            if outcome is not None and after is not None and generation == self._generation:
                try:
                    after()
                except Exception:  # noqa: BLE001 - 通知不到旁人不算运行失败
                    log.info("知识库定时同步：运行之后的通知没发出去", exc_info=True)
            try:
                self._done.emit(generation, outcome, why, seen)
            except RuntimeError:
                pass                                    # 应用正在退出

        try:
            self._spawn(work)
        except Exception:  # noqa: BLE001
            log.exception("知识库定时同步：启动后台线程失败")
            self._busy = False
            return False
        # 到周期的那种当场就知道发起了；停笔的那种要等后台看完工作区——它已经回来了（测试里线程是同步的）才答得出
        return bool(trigger) or self._runs != runs_before

    def _on_done(self, generation: int, outcome, trigger: str, seen: str) -> None:
        if generation != self._generation:
            return
        self._busy = False
        if outcome is None:
            return
        self._runs += 1
        self._last_run, self._attempted = self._clock(), seen
        log.info("知识库定时同步：%s → %s%s", trigger, outcome.state, f"（{outcome.error[-120:]}）" if outcome.error else "")
        self.finished.emit(outcome, trigger)
