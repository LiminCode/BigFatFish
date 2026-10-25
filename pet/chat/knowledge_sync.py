# -*- coding: utf-8 -*-
"""本地知识库的每日同步（肥鱼主进程里的定时器；同步本身见 ``knowledge_base.py``）。

每隔一小段时间看一眼「该不该同步」：知识库开着、仓库写对了，并且本地还没有这个仓库
的副本或副本已经超过一天。判断只读一个很小的状态文件，不发请求；真要同步时在 daemon
线程里下载解压，结果经信号排队回到本对象所在的 GUI 线程。

不需要有人来通知「设置改了」：每次检查都重新读配置（外部改动由 AppShell 的配置
watcher 重载进内存），所以打开开关或换了仓库之后，最迟一个检查周期就会同步。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from . import knowledge_base as kb

log = logging.getLogger(__name__)


def _spawn_thread(target: Callable[[], None]) -> None:
    threading.Thread(target=target, daemon=True, name="pet-knowledge-sync").start()


class KnowledgeBaseSync(QObject):
    """``synced(成功?, 说明)``：一次同步结束。"""

    synced = Signal(bool, str)
    _finished = Signal(int, bool, str)      # worker 线程 → GUI 线程（跨线程自动排队）

    STARTUP_DELAY_MS = 8_000
    CHECK_INTERVAL_MS = 10 * 60_000

    def __init__(self, config, *, sync: Callable | None = None, spawn: Callable | None = None,
                 clock: Callable[[], float] | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._sync = sync or kb.sync
        self._spawn = spawn or _spawn_thread
        self._clock = clock or time.time
        self._generation = 0
        self._busy = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.check)
        self._finished.connect(self._on_finished)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.stop)

    @property
    def busy(self) -> bool:
        return self._busy

    def start(self) -> None:
        """开始定时检查；第一次延后 ``STARTUP_DELAY_MS``，不和启动抢时间。"""
        QTimer.singleShot(self.STARTUP_DELAY_MS, self.check)
        self._timer.start(self.CHECK_INTERVAL_MS)

    def stop(self) -> None:
        """停表；在途的同步结果作废（线程是 daemon，随进程结束）。"""
        self._timer.stop()
        self._generation += 1
        self._busy = False

    def check(self) -> bool:
        """到点就同步一次；返回是否真的发起了。"""
        if self._busy:
            return False
        try:
            settings = self._config.chat_settings()
            repo = kb.parse_repo(settings.knowledge_base_repo) if settings.knowledge_base_enabled else ""
            config_dir = self._config.dir
            if not kb.needs_sync(config_dir, repo, self._clock()):
                return False
            token = kb.stored_token()
        except Exception:  # noqa: BLE001 - 配置读坏了也不能让定时器带病
            log.exception("知识库同步：读取配置失败")
            return False
        self._generation += 1
        generation, sync = self._generation, self._sync
        self._busy = True

        def run() -> None:
            try:
                state = sync(config_dir, repo, token)
                ok, message = True, f"{repo}：{state.files} 个文件"
            except Exception as exc:  # noqa: BLE001 - 任何失败都算「这次没同步上」，线程不许带病退出
                ok, message = False, f"{repo}：{exc}"
            try:
                self._finished.emit(generation, ok, message)
            except RuntimeError:
                pass  # 应用正在退出：本对象已销毁

        try:
            self._spawn(run)
        except Exception:  # noqa: BLE001 - 起线程失败也要释放忙状态
            log.exception("知识库同步：启动同步线程失败")
            self._busy = False
            return False
        return True

    def _on_finished(self, generation: int, ok: bool, message: str) -> None:
        if generation != self._generation:
            return  # 已停止：晚到的旧结果
        self._busy = False
        log.info("知识库同步%s：%s", "完成" if ok else "失败", message)
        self.synced.emit(ok, message)
