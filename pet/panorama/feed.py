# -*- coding: utf-8 -*-
"""配置全景的发布台：存最近一次发布的数据，并让「等新数据」的请求等到有为止。

**只用标准库、不碰 Qt。** 三方都从这里走：

- 采集线程 ``publish()``：把新的一份放上来，编号（``revision``）加一，叫醒所有在等的请求；
- 本机服务的请求线程 ``latest()`` / ``wait_newer()``：页面第一次来拿现成的，之后带着手里的编号来等更新的；
- 退出应用时 ``close()``：在等的请求立刻放回去，之后再来等的也不再阻塞。

数据是整份替换的字节串，没有人原地改它，所以读的一方不需要拷贝。
"""
from __future__ import annotations

import threading
from typing import Callable


class Feed:
    def __init__(self) -> None:
        self._changed = threading.Condition()
        self._revision = 0
        self._payload: bytes | None = None
        self._closed = False
        self._waiting = 0

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def waiting(self) -> int:
        """这一刻有几个请求挂在 ``wait_newer`` 里（也就是有几个看得见的页面在等）。"""
        return self._waiting

    def latest(self) -> bytes | None:
        """最近一次发布的数据；还没发布过是 ``None``。"""
        return self._payload

    def publish(self, build: Callable[[int], bytes]) -> int:
        """发布新的一份。``build(编号)`` 返回要发布的字节串——编号要写进数据里，所以先定编号再构造。

        构造在锁外面做（它要序列化整张图）。同一时刻只有一个发布者（采集服务有「忙」标志），所以编号不会撞。
        """
        revision = self._revision + 1
        payload = build(revision)
        with self._changed:
            self._revision, self._payload = revision, payload
            self._changed.notify_all()
        return revision

    def wait_newer(self, after: int, timeout: float) -> bytes | None:
        """等到有一份不是 ``after`` 的就返回它；等满 ``timeout`` 秒、或发布台关了，返回 ``None``。

        「不是」而不只是「更新」：页面手里的编号比这里还大，说明那是肥鱼重启之前的编号（编号从头数了），
        它手里那份不是现在这一份，马上把现在的给它。"""
        def different() -> bool:
            return self._payload is not None and self._revision != after

        with self._changed:
            self._waiting += 1
            try:
                self._changed.wait_for(lambda: self._closed or different(), timeout)
            finally:
                self._waiting -= 1
            if different() and not self._closed:
                return self._payload
            return None

    def close(self) -> None:
        with self._changed:
            self._closed = True
            self._changed.notify_all()
