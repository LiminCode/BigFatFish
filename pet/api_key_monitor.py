# -*- coding: utf-8 -*-
"""AI 对话 API 体检：灵动岛「连接」图标的数据来源。

回答一个问题：现在选中的对话服务商，用配置里的 API Key 到底连不连得上。结论
三态——``ok``（绿）/ ``bad``（红：Key 无效、没权限、端点不通都算）/ ``unknown``
（还没查过，或这个构建没有 AI 对话）。

体检走设置页「测试连接」那条路径（``chat.anthropic_provider.test_connection``）：
Claude 通道用 token 计数接口，不花输出额度；OpenAI 兼容通道发一个 max_tokens=1 的
请求。什么时候查：

- 启动后延时一次（不和启动抢时间）；
- 服务商 / 模型 / Key 变了（``refresh``，由配置应用路径调用）；
- 之后定时复查：通过后 30 分钟一次，没通过 5 分钟一次（网络恢复后尽快转绿）；
- 一次成功的真实对话直接算通过（``note_success``），不额外发请求。

线程：请求在 daemon 线程里跑，结果经信号排队回到本对象所在的 GUI 线程；每次发起
带一个代号，配置变了或 ``stop`` 之后晚到的旧结果一律丢弃。
"""

from __future__ import annotations

import hashlib
import logging
import threading
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal

log = logging.getLogger(__name__)

UNKNOWN, OK, BAD = "unknown", "ok", "bad"

_CHECKING_TEXT = "正在检查 API 连接…"
_FINGERPRINT_FIELDS = ("provider_id", "base_url", "chat_path", "model", "api_format")


def _default_probe(provider) -> tuple[bool, str]:
    from .chat.anthropic_provider import test_connection

    return test_connection(provider, timeout=10.0)


def _spawn_thread(target: Callable[[], None]) -> None:
    threading.Thread(target=target, daemon=True, name="pet-api-key-probe").start()


class ApiKeyMonitor(QObject):
    """当前对话服务商的 API 可用性：``status_changed(状态, 说明)``。"""

    status_changed = Signal(str, str)
    _probed = Signal(int, bool, str)        # worker 线程 → GUI 线程（跨线程自动排队）

    STARTUP_DELAY_MS = 3_000
    OK_RECHECK_MS = 30 * 60_000
    BAD_RECHECK_MS = 5 * 60_000

    def __init__(self, config, *, chat_enabled: bool = True,
                 probe: Callable | None = None, spawn: Callable | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._chat_enabled = bool(chat_enabled)
        self._probe = probe
        self._spawn = spawn or _spawn_thread
        self._state, self._detail = UNKNOWN, ""
        self._fingerprint: tuple | None = None   # 上次体检的服务商指纹；None = 还没查过
        self._generation = 0
        self._busy = False
        self._running = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.check)
        self._probed.connect(self._on_probed)

    @property
    def state(self) -> str:
        return self._state

    @property
    def detail(self) -> str:
        return self._detail

    # ---------------------------------------------------------------- 生命周期
    def start(self) -> None:
        """开始体检（幂等）。第一次检查延后 ``STARTUP_DELAY_MS``。"""
        if self._running:
            return
        self._running = True
        if not self._chat_enabled:
            self._set(UNKNOWN, "此版本没有 AI 对话，不检查 API")
            return
        if self._fingerprint is None:
            self._set(UNKNOWN, _CHECKING_TEXT)
        self._timer.start(self.STARTUP_DELAY_MS)

    def stop(self) -> None:
        """停止体检：停表，在途的结果作废。"""
        self._running = False
        self._timer.stop()
        self._generation += 1
        self._busy = False

    # ---------------------------------------------------------------- 触发
    def refresh(self) -> None:
        """配置可能变了：服务商 / 模型 / Key 变了才重查，改别的设置不发请求。"""
        if not self._running or not self._chat_enabled or self._fingerprint is None:
            return  # 还没查过第一次：启动延时那一次会读到最新配置
        resolved = self._resolve()
        if resolved is not None and resolved[1] != self._fingerprint:
            self._launch(*resolved)

    def check(self) -> bool:
        """立刻体检一次；在途时不重复发起。返回是否真的发起了。"""
        if not self._running or not self._chat_enabled or self._busy:
            return False
        resolved = self._resolve()
        if resolved is None:
            self._set(UNKNOWN, "读取 AI 对话配置失败")
            self._timer.start(self.BAD_RECHECK_MS)
            return False
        self._launch(*resolved)
        return True

    def note_success(self) -> None:
        """一次真实对话成功了：等同体检通过（不额外发请求）。"""
        if self._running and self._chat_enabled and self._state != OK:
            self._set(OK, "最近一次对话成功")

    # ---------------------------------------------------------------- 内部
    def _resolve(self) -> tuple | None:
        """(带上真实 Key 的服务商配置, 指纹)；读配置失败返回 None。"""
        try:
            provider = self._config.chat_settings().active_config
            provider.api_key = self._config.resolve_api_key(provider)
        except Exception:  # noqa: BLE001 - 配置损坏不许拖垮岛
            log.exception("API 体检：读取对话配置失败")
            return None
        # 指纹只留 Key 的摘要：不可逆推原 Key，不落敏感信息
        digest = hashlib.sha256(str(provider.api_key or "").encode()).hexdigest()[:12]
        fingerprint = tuple(str(getattr(provider, name, "") or "") for name in _FINGERPRINT_FIELDS)
        return provider, fingerprint + (digest,)

    def _launch(self, provider, fingerprint: tuple) -> None:
        if self._fingerprint is not None and fingerprint != self._fingerprint:
            self._set(UNKNOWN, _CHECKING_TEXT)   # 换了服务商 / Key：旧结论不能挂在新配置上
        self._fingerprint = fingerprint
        self._generation += 1
        generation = self._generation
        self._busy = True
        self._timer.stop()
        probe = self._probe or _default_probe

        def run() -> None:
            try:
                ok, message = probe(provider)
            except Exception as exc:  # noqa: BLE001 - 任何失败都算「不可用」，线程不许带病退出
                ok, message = False, f"检查失败：{exc}"
            try:
                self._probed.emit(generation, bool(ok), str(message))
            except RuntimeError:
                pass  # 应用正在退出：本对象已销毁

        try:
            self._spawn(run)
        except Exception:  # noqa: BLE001 - 起线程失败也要释放忙状态
            log.exception("API 体检：启动检查线程失败")
            self._busy = False
            self._timer.start(self.BAD_RECHECK_MS)

    def _on_probed(self, generation: int, ok: bool, message: str) -> None:
        if generation != self._generation:
            return  # 配置变了 / 已停止：晚到的旧结果
        self._busy = False
        if (OK if ok else BAD) != self._state:
            log.info("API 体检：%s（%s）", "可用" if ok else "不可用", message)
        self._set(OK if ok else BAD, message)
        self._timer.start(self.OK_RECHECK_MS if ok else self.BAD_RECHECK_MS)

    def _set(self, state: str, detail: str) -> None:
        if (state, detail) == (self._state, self._detail):
            return
        self._state, self._detail = state, detail
        self.status_changed.emit(state, detail)
