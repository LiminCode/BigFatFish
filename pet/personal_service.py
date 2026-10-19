# -*- coding: utf-8 -*-
"""个人助理的 Qt 侧服务：每日个人简报的定时与后台线程、灵感记录的落盘与 git 推送、Obsidian 打开。

照工作简报 / 工作笔记的样子：每分钟看一眼「该不该生成」；真要生成时在 daemon 线程里先 ``git pull``
再调肥鱼自己的 Claude（个人 API key），结果经信号排队回 GUI 线程落盘；git 串行（一把锁）；
``stop()`` 之后晚到的结果作废（generation 计数）。日志只记成败 / 用时 / token，不记正文。
"""
from __future__ import annotations

import copy
import datetime as dt
import logging
import os
import threading
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from . import personal_briefing as pb
from . import personal_vault as pv
from .i18n import t

log = logging.getLogger(__name__)


def _spawn_thread(target: Callable[[], None]) -> None:
    threading.Thread(target=target, daemon=True, name="pet-personal").start()


def _open_target(target: str) -> bool:
    try:
        os.startfile(target)  # noqa: S606  （obsidian:// 协议或资源管理器打开文件夹）
        return True
    except (AttributeError, OSError):
        return False


def resolve_chat_provider(config):
    """「AI 对话」里当前的服务商（带解出来的 API key）；没装聊天模块时抛。"""
    settings = config.chat_settings()
    provider = copy.copy(settings.active_config)
    provider.api_key = config.resolve_api_key(provider)
    return provider


class PersonalService(QObject):
    """``started(手动?)`` / ``finished(PersonalBriefing, 手动?)``；``inspiration_saved(path)``；
    ``synced(ok, error)``：灵感推送的结果；``changed()``：状态行该刷新了。"""

    started = Signal(bool)
    finished = Signal(object, bool)
    inspiration_saved = Signal(str)
    synced = Signal(bool, str)
    changed = Signal()
    _done = Signal(int, object, bool)
    _sync_done = Signal(int, bool, str)

    STARTUP_DELAY_MS = 25_000
    CHECK_INTERVAL_MS = 60_000

    def __init__(self, config, *, generate: Callable | None = None, pull: Callable | None = None,
                 sync: Callable | None = None, append: Callable | None = None, spawn: Callable | None = None,
                 now: Callable[[], dt.datetime] | None = None, opener: Callable[[str], bool] | None = None,
                 token: Callable[[], str] | None = None, provider: Callable | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._generate = generate or pb.generate
        self._pull = pull or pv.pull
        self._sync = sync or pv.sync_inspiration
        self._append = append or pv.append_inspiration
        self._spawn = spawn or _spawn_thread
        self._now = now or dt.datetime.now
        self._open = opener or _open_target
        self._token = token or pv.github_token
        self._provider = provider or (lambda: resolve_chat_provider(config))
        self._generation = 0
        self._busy = False
        self._busy_model = ""
        self._busy_effort = ""
        self._git_lock = threading.Lock()
        self._sync_state = "idle"        # idle / pushing / pushed / failed
        self._sync_error = ""
        self._pushed_at = ""
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.check)
        self._done.connect(self._on_done)
        self._sync_done.connect(self._on_sync_done)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.stop)

    # ---------------------------------------------------------- 读
    def settings(self) -> dict:
        return pv.normalize(self._config.get(pv.CONFIG_KEY))

    def repo_ready(self) -> bool:
        return pv.repo_ready(self.settings()["repo_dir"])

    def latest(self) -> pb.PersonalBriefing | None:
        return pb.latest(self._config.dir)

    def last_error(self) -> str:
        return str(pb.load_state(self._config.dir).get("error") or "")

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def busy_model(self) -> str:
        """正在生成的这份用的模型名（给「正在让 X 读…」那行）。"""
        return self._busy_model

    @property
    def busy_effort(self) -> str:
        return self._busy_effort

    @property
    def sync_state(self) -> str:
        return self._sync_state

    @property
    def sync_error(self) -> str:
        return self._sync_error

    @property
    def pushed_at(self) -> str:
        return self._pushed_at

    # ---------------------------------------------------------- 简报
    def start(self) -> None:
        QTimer.singleShot(self.STARTUP_DELAY_MS, self.check)
        self._timer.start(self.CHECK_INTERVAL_MS)

    def stop(self) -> None:
        self._timer.stop()
        self._generation += 1
        self._busy = False

    def check(self) -> bool:
        if self._busy:
            return False
        try:
            due = pb.is_due(self.settings(), pb.load_state(self._config.dir), self._now())
        except Exception:  # noqa: BLE001 - 配置读坏了也不能让定时器带病
            log.exception("个人简报：读取配置失败")
            return False
        return due and self._launch(manual=False)

    def generate_now(self) -> bool:
        return not self._busy and self._launch(manual=True)

    def _launch(self, *, manual: bool) -> bool:
        settings, now = self.settings(), self._now()
        try:
            provider = self._provider()
        except Exception as exc:  # noqa: BLE001 - 没装聊天模块 / 没有服务商
            briefing = pb.PersonalBriefing(error=f"{t('personal.error.not_claude')}（{type(exc).__name__}）",
                                           generated_at=now.replace(microsecond=0).isoformat())
            self._record(briefing)
            self.finished.emit(briefing, manual)
            return False
        self._generation += 1
        generation, generate, pull, token = self._generation, self._generate, self._pull, self._token
        self._busy = True
        self._busy_model = settings["model"] or str(getattr(provider, "model", "") or "")
        self._busy_effort = settings["effort"] or str(getattr(provider, "effort", "") or "")
        lock = self._git_lock
        self.started.emit(manual)

        def run() -> None:
            try:
                pull_note = ""
                if pv.repo_ready(settings["repo_dir"]):
                    with lock:
                        ok, out = pull(settings["repo_dir"], token=token())
                    pull_note = "" if ok else out
                briefing = generate(now, settings, provider, pull_note=pull_note)
            except Exception as exc:  # noqa: BLE001 - 任何失败都算「这次没生成」，线程不许带病退出
                briefing = pb.PersonalBriefing(error=t("personal.service.error_while_generating_name", name__=type(exc).__name__))
            try:
                self._done.emit(generation, briefing, manual)
            except RuntimeError:
                pass  # 应用正在退出

        try:
            self._spawn(run)
        except Exception:  # noqa: BLE001
            log.exception("个人简报：启动后台线程失败")
            self._busy = False
            return False
        return True

    def _record(self, briefing: pb.PersonalBriefing) -> None:
        try:
            pb.record(self._config.dir, briefing, self._now())
        except OSError:
            log.exception("个人简报：写状态文件失败")

    def _on_done(self, generation: int, briefing, manual: bool) -> None:
        if generation != self._generation:
            return
        self._busy = False
        self._record(briefing)
        log.info("个人简报%s：%s · 思考 %s · 用时 %.0f 秒 · 输入 %d / 输出 %d tokens · 工具 %d 轮 · 读了 %d 个文件%s",
                 "生成完成" if briefing.ok else "生成失败", briefing.model, briefing.effort, briefing.seconds,
                 briefing.tokens_in, briefing.tokens_out, briefing.turns, len(briefing.files_read),
                 "" if briefing.ok else f"：{briefing.error[:120]}")
        self.finished.emit(briefing, manual)

    # ---------------------------------------------------------- 灵感
    def add_inspiration(self, text: str) -> Path | None:
        """立刻追加到文件，然后后台 commit + push。空的不记；仓库副本不在就不记。"""
        if not str(text or "").strip():
            return None
        repo_dir = self.settings()["repo_dir"]
        if not pv.repo_ready(repo_dir):
            self._set_sync("failed", t("personal.inspiration.no_repo", path=repo_dir))
            return None
        try:
            path = self._append(repo_dir, text, self._now())
        except OSError as exc:
            self._set_sync("failed", t("personal.inspiration.write_failed", error=exc.strerror or str(exc)))
            log.warning("灵感记录：写文件失败", exc_info=True)
            return None
        self.inspiration_saved.emit(str(path))
        self._start_sync(repo_dir)
        return path

    def _start_sync(self, repo_dir: str) -> None:
        generation, sync, lock, now, token = self._generation, self._sync, self._git_lock, self._now(), self._token
        self._set_sync("pushing", "")

        def run() -> None:
            with lock:
                try:
                    ok, out = sync(repo_dir, now, token=token())
                except Exception as exc:  # noqa: BLE001
                    ok, out = False, t("personal.service.error_while_committing_name", name__=type(exc).__name__)
            try:
                self._sync_done.emit(generation, ok, out)
            except RuntimeError:
                pass

        try:
            self._spawn(run)
        except Exception:  # noqa: BLE001
            log.exception("灵感记录：启动 git 线程失败")
            self._set_sync("failed", "thread")

    def _on_sync_done(self, generation: int, ok: bool, out: str) -> None:
        if generation != self._generation:
            return
        if ok:
            self._pushed_at = f"{self._now():%H:%M}"
            self._set_sync("pushed", "")
        else:
            log.warning("灵感记录：git 失败：%s", out[-200:])
            self._set_sync("failed", out[-200:])
        self.synced.emit(ok, "" if ok else out)

    def _set_sync(self, state: str, error: str) -> None:
        self._sync_state, self._sync_error = state, error
        self.changed.emit()

    # ---------------------------------------------------------- Obsidian
    def open_in_obsidian(self) -> tuple[str, str]:
        """在 Obsidian 里打开 AI-Base；没登记成库就打开文件夹。返回 (obsidian / folder / failed, 目标)。"""
        repo_dir = self.settings()["repo_dir"]
        uri = pv.obsidian_vault_uri(repo_dir)
        if uri:
            return ("obsidian" if self._open(uri) else "failed"), repo_dir
        return ("folder" if self._open(repo_dir) else "failed"), repo_dir
