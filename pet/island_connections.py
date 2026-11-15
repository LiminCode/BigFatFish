# -*- coding: utf-8 -*-
"""灵动岛「模型连接」面板：点岛上的连接图标，在岛的**上方**列出配置过的全部模型服务。

每个服务一张 Metro 实色磁贴：名称（在用的那一项标「使用中」）、模型、地址，以及连接状态——
绿 = 连得上，红 = 连不上（附原因），灰 = 还没查 / 正在查。

状态从哪来：

- **在用的那一项**直接用岛上的体检结论（``ApiKeyMonitor``，它本来就在定时查），不重复发请求；
- **其余各项**在面板打开时各查一次，走同一个体检函数（``api_key_monitor._default_probe``：Claude 用
  token 计数接口、不花输出额度；OpenAI 兼容发 max_tokens=1 的请求）。结论按「地址 / 模型 / Key」
  指纹缓存 ``RECHECK_AFTER_S``：半小时内再打开不重发；Key 或地址变了立刻重查；点「重新检查」全部重查。

线程：请求在 daemon 线程里跑，结果经信号排队回到 GUI 线程；每项每次发起带一个代号，晚到的旧结果丢弃。
``build_rows`` 是纯函数，界面在 ``island_connections_ui``。面板关着时零开销。
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, QRect, Signal

from . import api_key_monitor
from .i18n import t
from .usage_dashboard import place_above

log = logging.getLogger(__name__)

UNKNOWN, CHECKING, OK, BAD = "unknown", "checking", "ok", "bad"
_FINGERPRINT_FIELDS = ("base_url", "chat_path", "model", "api_format", "verify_ssl")


@dataclass(frozen=True)
class ServiceRow:
    """面板上的一行（一张磁贴）。"""

    provider_id: str
    name: str
    model: str
    host: str
    state: str
    detail: str
    in_use: bool


def _host(url: str) -> str:
    """地址只显示主机（含端口）：``https://api.deepseek.com/v1`` → ``api.deepseek.com``。"""
    url = str(url or "").strip()
    if not url:
        return ""
    parts = urlsplit(url if "://" in url else f"https://{url}")
    return parts.netloc or url


def _strip_name(detail: str, name: str) -> str:
    """岛上的体检结论以「服务名 · 」开头（磁贴上名字已经有了）：去掉，不重复。"""
    prefix = f"{name} · "
    return detail[len(prefix):] if name and detail.startswith(prefix) else detail


def _default_detail(state: str) -> str:
    return t("island.connections.checking") if state == CHECKING else t("island.connections.not_checked")


def build_rows(settings, statuses: dict, *, in_use: tuple[str, str]) -> list[ServiceRow]:
    """配置里的全部服务（配置顺序）→ 磁贴行。

    ``statuses``：``{provider_id: (状态, 说明)}``，其余各项的体检结论；``in_use``：岛上体检的
    ``(状态, 说明)``，给在用的那一项。
    """
    rows = []
    for pid, provider in settings.providers.items():
        name = str(getattr(provider, "name", "") or pid)
        active = pid == settings.active_provider
        state, detail = in_use if active else statuses.get(pid, (UNKNOWN, ""))
        state = state if state in (UNKNOWN, CHECKING, OK, BAD) else UNKNOWN
        detail = _strip_name(str(detail or ""), name) or _default_detail(state)
        rows.append(ServiceRow(str(pid), name, str(getattr(provider, "model", "") or ""),
                               _host(getattr(provider, "base_url", "")), state, detail, active))
    return rows


def _spawn_thread(target: Callable[[], None]) -> None:
    threading.Thread(target=target, daemon=True, name="pet-connections-probe").start()


class ConnectionsPanel(QObject):
    """面板的开 / 关 / 查。``monitor`` 是岛上的 ``ApiKeyMonitor``（读 ``state`` / ``detail``，「重新检查」时
    调 ``check()``）；``probe`` / ``spawn`` / ``clock`` 供测试注入。"""

    settings_requested = Signal()             # 点了「去设置修改」
    panorama_requested = Signal()             # 点了「配置全景」
    _probed = Signal(str, int, bool, str)     # worker 线程 → GUI 线程：(服务, 代号, 通过?, 说明)

    RECHECK_AFTER_S = 30 * 60

    def __init__(self, config, *, monitor=None, probe: Callable | None = None, spawn: Callable | None = None,
                 clock: Callable[[], float] = time.monotonic, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self.monitor = monitor
        self._probe = probe
        self._spawn = spawn or _spawn_thread
        self._clock = clock
        #: provider_id → (状态, 说明, 指纹, 查的时刻)；正在查的状态是 CHECKING
        self._statuses: dict[str, tuple[str, str, tuple, float]] = {}
        self._tokens: dict[str, int] = {}
        self._in_use: tuple[str, str] | None = None   # 岛体检最近一次的结论（信号带来的）
        self.window = None
        self._probed.connect(self._on_probed)

    # ---------------------------------------------------------------- 开 / 关
    def _ensure_window(self):
        if self.window is None:
            from .island_connections_ui import ConnectionsWindow

            self.window = ConnectionsWindow()
            self.window.recheck_requested.connect(self.recheck)
            self.window.settings_requested.connect(self._open_settings)
            self.window.panorama_requested.connect(self._open_panorama)
        return self.window

    def is_open(self) -> bool:
        return self.window is not None and self.window.isVisible()

    def toggle(self, anchor: QRect, available: QRect) -> None:
        """点了岛上的连接图标：开着就关，关着就在岛的上方打开并查一遍（缓存还新的不查）。"""
        if self.is_open():
            self.window.hide()
            return
        window = self._ensure_window()
        window.apply_theme(self._theme())
        self.refresh()                          # 先标「正在检查」再画，免得一开就闪「还没检查」
        window.adjustSize()
        window.setGeometry(place_above(anchor, window.sizeHint(), available))
        window.show()
        window.raise_()
        window.activateWindow()                 # 激活了才能「点别处就收起」

    def close(self) -> None:
        if self.window is not None:
            self.window.hide()
            self.window.deleteLater()
            self.window = None

    def _open_settings(self) -> None:
        if self.window is not None:
            self.window.hide()
        self.settings_requested.emit()

    def _open_panorama(self) -> None:
        if self.window is not None:
            self.window.hide()
        self.panorama_requested.emit()

    def _theme(self) -> str:
        appearance = self.config.get("context_menu_appearance") if self.config is not None else None
        return str((appearance or {}).get("theme") or "system") if isinstance(appearance, dict) else "system"

    # ---------------------------------------------------------------- 数据
    def rows(self) -> list[ServiceRow]:
        try:
            settings = self.config.chat_settings()
        except Exception:  # noqa: BLE001 - 配置损坏不许拖垮岛
            log.exception("模型连接面板：读取对话配置失败")
            return []
        monitor = self.monitor
        in_use = self._in_use or ((getattr(monitor, "state", UNKNOWN), getattr(monitor, "detail", ""))
                                  if monitor else (UNKNOWN, ""))
        statuses = {pid: (state, detail) for pid, (state, detail, _fp, _at) in self._statuses.items()}
        return build_rows(settings, statuses, in_use=in_use)

    def on_monitor_changed(self, state: str | None = None, detail: str = "") -> None:
        """岛上的体检结论变了（接 ``ApiKeyMonitor.status_changed``）：记下结论，面板开着就重画。
        不带参数时改读 ``monitor.state`` / ``monitor.detail``。"""
        self._in_use = (str(state), str(detail or "")) if state is not None else None
        self._render()

    def _render(self) -> None:
        if self.window is not None:
            self.window.set_rows(self.rows())

    # ---------------------------------------------------------------- 体检
    def recheck(self) -> None:
        """「重新检查」：在用的那一项让岛重查，其余各项不论缓存都重查。"""
        if self.monitor is not None:
            try:
                self.monitor.check()
            except Exception:  # noqa: BLE001
                log.exception("模型连接面板：岛体检重查失败")
        self.refresh(force=True)

    def refresh(self, *, force: bool = False) -> None:
        """查一遍在用以外的各项：缓存过期、指纹变了或 ``force`` 时才发请求。"""
        try:
            settings = self.config.chat_settings()
        except Exception:  # noqa: BLE001
            log.exception("模型连接面板：读取对话配置失败")
            self._render()
            return
        now = self._clock()
        for pid in list(self._statuses):
            if pid not in settings.providers:
                self._statuses.pop(pid, None)   # 删掉的服务
        for pid, provider in settings.providers.items():
            if pid == settings.active_provider:
                continue                        # 岛上已经在查
            try:
                provider.api_key = self.config.resolve_api_key(provider)
            except Exception:  # noqa: BLE001
                log.exception("模型连接面板：读取 %s 的 Key 失败", pid)
                provider.api_key = ""
            fingerprint = self._fingerprint(provider)
            cached = self._statuses.get(pid)
            if (not force and cached is not None and cached[2] == fingerprint
                    and (cached[0] == CHECKING or now - cached[3] < self.RECHECK_AFTER_S)):
                continue
            self._launch(pid, provider, fingerprint, now)
        self._render()

    @staticmethod
    def _fingerprint(provider) -> tuple:
        # Key 只留摘要：不可逆推原 Key，不落敏感信息
        digest = hashlib.sha256(str(provider.api_key or "").encode()).hexdigest()[:12]
        return tuple(str(getattr(provider, name, "")) for name in _FINGERPRINT_FIELDS) + (digest,)

    def _launch(self, pid: str, provider, fingerprint: tuple, now: float) -> None:
        token = self._tokens.get(pid, 0) + 1
        self._tokens[pid] = token
        self._statuses[pid] = (CHECKING, "", fingerprint, now)
        probe = self._probe or (lambda p: api_key_monitor._default_probe(p))

        def run() -> None:
            try:
                ok, message = probe(provider)
            except Exception as exc:  # noqa: BLE001 - 任何失败都算「连不上」，线程不许带病退出
                ok, message = False, t("api.failed", error=exc)
            try:
                self._probed.emit(pid, token, bool(ok), str(message))
            except RuntimeError:
                pass  # 应用正在退出：本对象已销毁

        try:
            self._spawn(run)
        except Exception:  # noqa: BLE001 - 起线程失败也要把状态放回来
            log.exception("模型连接面板：启动检查线程失败")
            self._statuses[pid] = (UNKNOWN, "", (), now)

    def _on_probed(self, pid: str, token: int, ok: bool, message: str) -> None:
        if self._tokens.get(pid) != token:
            return                              # Key / 地址变了之后晚到的旧结果
        cached = self._statuses.get(pid)
        if cached is None:
            return                              # 服务已删除
        self._statuses[pid] = (OK if ok else BAD, message, cached[2], self._clock())
        self._render()
