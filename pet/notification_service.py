# -*- coding: utf-8 -*-
"""通知中心的轮询与状态（Qt 侧；读、合并、跳转本身见 ``notification_center.py``）。

隔 ``poll_seconds`` 秒在 daemon 线程里读一次通知中心，结果经信号排队回到本对象所在的 GUI
线程，在那里合并、算「哪些是新的」，再发 ``changed`` / ``unread_changed``。跳转也在工作线程里
跑（有深链接就直接打开；没有才打开通知中心、UIA 找、激活，最多等两秒），结果走 ``activation_done``。

「新的」= 出现之后用户还没打开过通知卡片；打开卡片（``mark_all_seen``）就全部算看过。
「刚到的」（``arrived``，给自家弹窗用）= 这一轮新出现的；开始读之后的第一轮是积压，只进岛、不弹。
用户在卡片里「移除」的记在 ``_hidden`` 里，之后再读到也不出现。折叠状态只记在内存里。
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from . import notification_center as nc

log = logging.getLogger(__name__)


def _spawn_thread(target: Callable[[], None]) -> None:
    threading.Thread(target=target, daemon=True, name="pet-notifications").start()


class NotificationService(QObject):
    """``changed(list[Notice])``（新到旧）/ ``unread_changed(int)`` / ``activation_done(Notice, str)`` /
    ``arrived(list[Notice])``（这一轮刚到的，旧到新）。"""

    changed = Signal(object)
    arrived = Signal(object)
    unread_changed = Signal(int)
    activation_done = Signal(object, str)
    _done = Signal(int, object, object)          # worker → GUI：(轮次, notices, logos)
    _activated = Signal(object, str)             # worker → GUI

    STARTUP_DELAY_MS = 6_000

    def __init__(self, config, *, read: Callable | None = None, activate: Callable | None = None,
                 remove: Callable | None = None, spawn: Callable | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._read = read or nc.read_toasts
        self._activate = activate or nc.activate
        self._remove = remove or nc.remove_from_center
        self._spawn = spawn or _spawn_thread
        self._generation = 0
        self._busy = False
        self._notices: list[nc.Notice] = []
        self._unread: set[int] = set()
        self._hidden: set[int] = set()
        self._logos: dict[str, bytes] = {}
        self._baselined = False                   # 第一轮读完之前，读到的都算积压（不发 arrived）
        self.ui_open = True                       # 卡片里的折叠框开着（只记在内存里）
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.poll)
        self._done.connect(self._on_done)
        self._activated.connect(self.activation_done)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.stop)

    # ---------------------------------------------------------------- 状态
    def settings(self) -> dict:
        return nc.normalize(self._config.get(nc.CONFIG_KEY))

    @property
    def enabled(self) -> bool:
        return bool(self.settings()["enabled"]) and nc.available()

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def notices(self) -> list[nc.Notice]:
        return list(self._notices)

    @property
    def logos(self) -> dict[str, bytes]:
        return dict(self._logos)

    @property
    def unread_count(self) -> int:
        return len(self._unread)

    @property
    def unread_uids(self) -> frozenset:
        return frozenset(self._unread)

    def notice(self, uid) -> nc.Notice | None:
        for item in self._notices:
            if item.uid == uid:
                return item
        return None

    # ---------------------------------------------------------------- 起停
    def start(self) -> None:
        """按配置开始轮询；第一次延后几秒，不和启动抢时间。"""
        self.apply_settings(first_poll_delay_ms=self.STARTUP_DELAY_MS)

    def apply_settings(self, *, first_poll_delay_ms: int = 0) -> None:
        """配置变了（开关 / 间隔 / 应用名）：重排定时器；关掉时停表、清空、通知岛。"""
        settings = self.settings()
        if not settings["enabled"] or not nc.available():
            self.stop()
            if self._notices or self._unread:
                self._notices, self._unread = [], set()
                self.changed.emit([])
                self.unread_changed.emit(0)
            return
        interval = int(settings["poll_seconds"]) * 1000
        if not self._timer.isActive() or self._timer.interval() != interval:
            self._timer.start(interval)
            if first_poll_delay_ms > 0:
                QTimer.singleShot(first_poll_delay_ms, self.poll)
            else:
                self.poll()

    def stop(self) -> None:
        self._timer.stop()
        self._generation += 1
        self._busy = False
        self._baselined = False

    # ---------------------------------------------------------------- 读
    def poll(self) -> bool:
        """读一轮；上一轮还没回来就跳过。返回是否真的发起了。"""
        if self._busy or not self._timer.isActive():
            return False
        self._generation += 1
        generation, read = self._generation, self._read
        fragments = tuple(self.settings()["apps"])
        known_logos, known = set(self._logos), tuple(self._notices)
        self._busy = True

        def run() -> None:
            try:
                notices, logos = read(fragments, want_logos=(), known=known)
                missing = {n.app_id for n in notices if n.app_id not in known_logos}
                if missing:
                    _again, logos = read(fragments, want_logos=missing, known=known)
            except Exception:  # noqa: BLE001 - 线程不许带病退出
                log.debug("通知中心：这一轮读取出错", exc_info=True)
                notices, logos = None, {}
            try:
                self._done.emit(generation, notices, logos)
            except RuntimeError:
                pass  # 应用正在退出

        try:
            self._spawn(run)
        except Exception:  # noqa: BLE001
            log.exception("通知中心：启动后台线程失败")
            self._busy = False
            return False
        return True

    def _on_done(self, generation: int, notices, logos) -> None:
        if generation != self._generation:
            return  # 已停止 / 配置重排后的旧结果
        self._busy = False
        if logos:
            self._logos.update({k: v for k, v in dict(logos).items() if v})
        if notices is None:
            return
        merged, new_uids = nc.merge(self._notices, notices, keep=self.settings()["keep"], hidden=self._hidden)
        if merged == self._notices and not new_uids:
            self._baselined = True
            return
        self._notices = merged
        if new_uids:
            self._unread.update(new_uids)
        self.changed.emit(self.notices)
        if new_uids:
            self.unread_changed.emit(self.unread_count)
        backlog, self._baselined = not self._baselined, True
        fresh = sorted((n for n in merged if n.uid in set(new_uids)), key=lambda n: (n.created, n.uid))
        if fresh and not backlog:
            self.arrived.emit(fresh)

    # ---------------------------------------------------------------- 用户动作
    def mark_all_seen(self) -> None:
        if self._unread:
            self._unread.clear()
            self.unread_changed.emit(0)

    def activate(self, uid) -> bool:
        """跳到这条对应的消息（工作线程里跑；结果走 ``activation_done``）。不认识的 uid 返回 False。"""
        notice = self.notice(uid)
        if notice is None:
            return False
        activate = self._activate
        self._unread.discard(notice.uid)
        self.unread_changed.emit(self.unread_count)

        def run() -> None:
            try:
                result = activate(notice)
            except Exception:  # noqa: BLE001
                log.debug("通知中心：跳转出错", exc_info=True)
                result = "failed"
            try:
                self._activated.emit(notice, result)
            except RuntimeError:
                pass

        self._spawn(run)
        return True

    def dismiss(self, uid) -> bool:
        """从卡片里移除（也从 Windows 通知中心里拿掉）。"""
        notice = self.notice(uid)
        if notice is None:
            return False
        self._hidden.add(notice.uid)
        self._notices = [n for n in self._notices if n.uid != notice.uid]
        self._unread.discard(notice.uid)
        if notice.in_center:
            remove = self._remove
            self._spawn(lambda: remove(notice.uid))
        self.changed.emit(self.notices)
        self.unread_changed.emit(self.unread_count)
        return True

    def clear(self) -> None:
        for notice in list(self._notices):
            self.dismiss(notice.uid)
