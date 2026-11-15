# -*- coding: utf-8 -*-
"""配置的每日自动备份（肥鱼主进程里的定时器；备份本身见 ``config_backup.py``）。

每隔一小段时间看一眼「该不该备份」：开关开着、仓库能定下来（设置里填的，或知识库那个）、
``needs_backup`` 说到点了且设置真的变了、钥匙串里有 Token。判断只读配置和一个很小的
状态文件，不发请求；真要备份时在 daemon 线程里上传，结果经信号排队回 GUI 线程。

配置按默认值重建过（``rebuilt_at``）时 ``needs_backup`` 一律说不——自动备份绝不能拿
一份默认配置顶掉 GitHub 上的好备份。

和知识库同步一样不需要「设置改了」的通知：每次检查都重新读配置。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from . import config_backup as cb

log = logging.getLogger(__name__)


def _spawn_thread(target: Callable[[], None]) -> None:
    threading.Thread(target=target, daemon=True, name="pet-config-backup").start()


def _kb_repo(config) -> str:
    try:
        return str(config.chat_settings().knowledge_base_repo or "")
    except Exception:  # noqa: BLE001 - 不带聊天的变体 / 聊天配置读坏了
        return ""


class ConfigBackupSync(QObject):
    """``finished(成功?, 说明)``：一次自动备份结束。"""

    finished = Signal(bool, str)
    _done = Signal(int, bool, str)          # worker 线程 → GUI 线程（跨线程自动排队）

    STARTUP_DELAY_MS = 60_000
    CHECK_INTERVAL_MS = 10 * 60_000

    def __init__(self, config, *, backup: Callable | None = None, token: Callable[[], str] | None = None,
                 spawn: Callable | None = None, clock: Callable[[], float] | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._backup = backup or cb.backup
        self._token = token or cb.stored_token
        self._spawn = spawn or _spawn_thread
        self._clock = clock or time.time
        self._generation = 0
        self._busy = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.check)
        self._done.connect(self._on_done)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.stop)

    def start(self) -> None:
        """开始定时检查；第一次延后 ``STARTUP_DELAY_MS``，不和启动抢时间。"""
        QTimer.singleShot(self.STARTUP_DELAY_MS, self.check)
        self._timer.start(self.CHECK_INTERVAL_MS)

    def stop(self) -> None:
        self._timer.stop()
        self._generation += 1
        self._busy = False

    def check(self) -> bool:
        """到点就备份一次；返回是否真的发起了。"""
        if self._busy:
            return False
        try:
            config = self._config
            if config.instance_id:
                return False               # 只备份主配置
            settings = cb.normalize(config.get("config_backup"))
            repo = cb.target_repo(settings, _kb_repo(config)) if settings["auto"] else ""
            if not repo or not cb.needs_backup(config.dir, config.path, self._clock()):
                return False
            token = self._token()
            if not token:
                return False
        except Exception:  # noqa: BLE001 - 配置读坏了也不能让定时器带病
            log.exception("配置自动备份：读取配置失败")
            return False
        self._generation += 1
        generation, backup, path = self._generation, self._backup, config.path
        self._busy = True

        def run() -> None:
            try:
                backup(path, repo, settings["path"], token)
                ok, message = True, f"{repo}:{settings['path']}"
            except Exception as exc:  # noqa: BLE001 - 任何失败都算「这次没备份上」
                ok, message = False, f"{repo}: {exc}"
            try:
                self._done.emit(generation, ok, message)
            except RuntimeError:
                pass  # 应用正在退出：本对象已销毁

        try:
            self._spawn(run)
        except Exception:  # noqa: BLE001 - 起线程失败也要释放忙状态
            log.exception("配置自动备份：启动线程失败")
            self._busy = False
            return False
        return True

    def _on_done(self, generation: int, ok: bool, message: str) -> None:
        if generation != self._generation:
            return
        self._busy = False
        log.info("配置自动备份%s：%s", "完成" if ok else "失败", message)
        self.finished.emit(ok, message)
