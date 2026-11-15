# -*- coding: utf-8 -*-
"""应用里的「打开配置全景」：后台采集、分两段写页面、在 GUI 线程打开浏览器。

点一下之后：
1. 第一段采 Windows 这一侧（约 0.15 秒），WSL 那一侧先用上一轮的结果（没有就显示「正在探测…」），
   写出页面并打开浏览器——用户几乎立刻看到图。
2. 第二段去 WSL 里探测（``claude mcp list`` 逐个体检，6 秒上下），探完重写页面。页面在 ``meta.pending``
   为真时每隔几秒自己重读文件，所以不用任何服务器也能自己更新。

两段都在一条 daemon 线程里；结果经信号排队回 GUI 线程（``ConfigBackupSync`` 同一个模式）。
配置在 GUI 线程上拷贝一份再交给线程，线程不碰活的 ``Config``。
"""
from __future__ import annotations

import copy
import logging
import threading
import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication

from . import probes, render, sources

log = logging.getLogger(__name__)
OUT_SUBDIR = "panorama"


def _spawn_thread(target: Callable[[], None]) -> None:
    threading.Thread(target=target, daemon=True, name="pet-panorama").start()


def _open_in_browser(path: str) -> bool:
    return QDesktopServices.openUrl(QUrl.fromLocalFile(path))


def _secret_get(ref: str) -> str:
    from ..chat.models import SecretStore

    return SecretStore().get(ref)


class PanoramaService(QObject):
    """``finished(成功?, 页面路径或出错说明)``：一轮（含 WSL 那一段）结束。"""

    finished = Signal(bool, str)
    _stage = Signal(int, str, str)           # worker 线程 → GUI 线程：(第几轮, "page" | "done" | "error", 路径或说明)

    def __init__(self, config, *, health: Callable[[], tuple[str, str]] | None = None,
                 secret_get: Callable[[str], str] | None = None, windows: Callable[..., dict] | None = None,
                 wsl: Callable[[], dict] | None = None, write: Callable[[dict, Path], Path] | None = None,
                 open_page: Callable[[str], object] | None = None, spawn: Callable | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._health = health or (lambda: ("unknown", ""))
        self._secret_get = secret_get or _secret_get
        self._windows = windows or probes.windows_side
        self._wsl = wsl or probes.wsl_side
        self._write = write or (lambda facts, out_dir: render.write(sources.build(facts), out_dir))
        self._open_page = open_page or _open_in_browser
        self._spawn = spawn or _spawn_thread
        self._generation = 0
        self._busy = False
        self._last_wsl: dict | None = None      # 上一轮 WSL 的结果：下一次打开先拿它垫着
        self._last_wsl_seconds: float | None = None
        self._stage.connect(self._on_stage)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.stop)

    @property
    def page_path(self) -> Path:
        return Path(self._config.dir) / OUT_SUBDIR / render.PAGE_NAME

    def is_busy(self) -> bool:
        return self._busy

    def stop(self) -> None:
        """应用要退出：在跑的那一轮作废（它写完的文件留着，只是不再打开浏览器、不再报完成）。"""
        self._generation += 1
        self._busy = False

    def open(self) -> bool:
        """采一轮并打开页面；返回是否真的发起了新一轮。上一轮还没跑完时只把现有页面再打开一次。"""
        if self._busy:
            if self.page_path.is_file():
                self._open_page(str(self.page_path))
            return False
        try:
            cfg = copy.deepcopy(self._config.data)
            cfg_path, out_dir = Path(self._config.path), self.page_path.parent
            health = tuple(self._health())
        except Exception:  # noqa: BLE001 - 配置读坏了也不能让菜单项抛异常
            log.exception("配置全景：读取配置失败")
            return False
        self._generation += 1
        generation = self._generation
        previous, previous_seconds = self._last_wsl, self._last_wsl_seconds
        self._busy = True

        def emit(stage: str, text: str) -> None:
            try:
                self._stage.emit(generation, stage, text)
            except RuntimeError:
                pass  # 应用正在退出：本对象已销毁

        def run() -> None:
            try:
                facts = self._windows(cfg, cfg_path=cfg_path, secret_get=self._secret_get, api_health=health)
                if previous is not None:
                    facts["wsl"], facts["refreshing"] = previous, True
                    if previous_seconds is not None:
                        facts["timing"]["wsl_s"] = previous_seconds
                else:
                    facts["wsl"] = {"pending": True}
                emit("page", str(self._write(facts, out_dir)))
            except Exception as exc:  # noqa: BLE001 - 第一段就失败：没有页面可看
                log.exception("配置全景：采集失败")
                emit("error", f"{type(exc).__name__}: {exc}")
                return
            started = time.perf_counter()
            try:
                wsl = self._wsl()
            except Exception as exc:  # noqa: BLE001 - 探针自己把失败折成了字典；这里兜住意料之外的
                log.exception("配置全景：WSL 探测失败")
                wsl = {"error": f"{type(exc).__name__}: {exc}"}
            seconds = round(time.perf_counter() - started, 2)
            facts.pop("refreshing", None)
            facts["wsl"] = wsl
            facts["timing"]["wsl_s"] = seconds
            try:
                path = str(self._write(facts, out_dir))
            except Exception as exc:  # noqa: BLE001
                log.exception("配置全景：写页面失败")
                emit("error", f"{type(exc).__name__}: {exc}")
                return
            if generation == self._generation:      # 作废的那一轮不留结果给下一次垫底
                self._last_wsl, self._last_wsl_seconds = wsl, seconds
            emit("done", path)

        try:
            self._spawn(run)
        except Exception:  # noqa: BLE001 - 起线程失败也要释放忙状态
            log.exception("配置全景：启动线程失败")
            self._busy = False
            return False
        return True

    def _on_stage(self, generation: int, stage: str, text: str) -> None:
        if generation != self._generation:
            return
        if stage == "page":
            self._open_page(text)
            return
        self._busy = False
        if stage == "error":
            log.warning("配置全景没有生成：%s", text)
        self.finished.emit(stage == "done", text)
