# -*- coding: utf-8 -*-
"""会话小鱼：每个在用的 Claude Code 会话一只临时 sprite（接线层）。

数据从 ``ClaudeCodeMonitor.session_update`` 来（见 ``pet/claude_hooks.py`` 的
``ClaudeSessionTracker``：会话第一次提问才出场、关闭会话才离场），到
``OverlayShell`` 的临时 sprite 去。主肥鱼照旧走 Agent 级的汇总状态管线——这里
只是给每个会话多一只各管各的小鱼，两条管线互不影响。

线程：监视器在 worker 线程里发信号；本类是 GUI 线程上的 QObject，
``on_session_update`` 以 bound method 连接，Qt 自动排队投递回 GUI 线程。
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from PySide6.QtCore import QObject, Slot

log = logging.getLogger(__name__)


class SessionPetController(QObject):
    """``(agent_key, sessionId)`` → 一只会话小鱼：标签 + 保持动画 + 生灭。"""

    #: 忙：在这组里轮播；休息：循环这一段。素材库里没有的自动跳过（换了角色），
    #: 一段都没有就不保持——小鱼退回普通的随机行为，标签照常显示。
    WORK_CLIPS: tuple[str, ...] = ("写代码", "吃Token")
    REST_CLIPS: tuple[str, ...] = ("原地小憩沉眠",)
    PHASE_TEXT = {"working": "写代码中", "waiting": "等你批准", "resting": "休息中"}
    #: 两个通道可能开着同名项目：WSL 那边的加个后缀区分
    CHANNEL_SUFFIX = {"claude_wsl": " (WSL)"}
    AGENT_KEYS = ("claude", "claude_wsl")

    def __init__(self, shell, *, enabled: Callable[[], bool], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._shell = shell
        self._enabled = enabled
        self._pets: dict[tuple[str, str], Any] = {}
        self._phases: dict[tuple[str, str], str] = {}

    def attach(self, manager) -> None:
        """订阅联动管理器里两个 Claude Code 通道的逐会话更新。"""
        monitors = getattr(manager, "monitors", None) or {}
        for key in self.AGENT_KEYS:
            signal = getattr(monitors.get(key), "session_update", None)
            if signal is not None:
                signal.connect(self.on_session_update)

    def clear(self) -> None:
        """所有会话小鱼离场（功能被关掉时）。"""
        for key in list(self._pets):
            self._retire(key)

    def _retire(self, key: tuple[str, str]) -> None:
        sprite = self._pets.pop(key, None)
        self._phases.pop(key, None)
        if sprite is not None and self._shell.is_session_pet(sprite):
            self._shell.remove_session_pet(sprite)
            log.info("会话小鱼离场 agent=%s session=%s", key[0], key[1][:8])

    @Slot(str, object)
    def on_session_update(self, agent_key, update) -> None:
        if not isinstance(update, dict):
            return
        key = (str(agent_key), str(update.get("sessionId") or ""))
        phase = str(update.get("phase") or "")
        shell = self._shell
        sprite = self._pets.get(key)
        if sprite is not None and not shell.is_session_pet(sprite):
            # 用户手动把这只退掉了（「退出这只」/「退出子肥鱼」）：忘掉它
            self._pets.pop(key, None)
            self._phases.pop(key, None)
            sprite = None
        if phase == "gone" or not self._enabled():
            self._retire(key)
            return
        if phase not in self.PHASE_TEXT:
            return
        if sprite is None:
            if phase == "resting":
                return  # 没赶上它干活（或刚被退掉）：不凭空生一只，等它下次提问
            sprite = shell.spawn_session_pet()
            if sprite is None:
                return  # 到上限：这个会话只体现在主肥鱼的汇总状态里
            self._pets[key] = sprite
            log.info("会话小鱼出场 agent=%s session=%s（在场 %d 只）", key[0], key[1][:8], len(self._pets))
        name = str(update.get("title") or update.get("project") or key[1][:8] or "Claude Code")
        shell.set_session_pet_caption(
            sprite, f"{name}{self.CHANNEL_SUFFIX.get(key[0], '')} · {self.PHASE_TEXT[phase]}")
        previous = self._phases.get(key)
        if previous == phase:
            return  # 只是标签变了：不重启正在播的动画
        self._phases[key] = phase
        if phase == "resting":
            clips = self.REST_CLIPS
        elif phase == "working" or previous is None:
            clips = self.WORK_CLIPS
        else:
            return  # 干活途中转入等批准：姿势不变，只换标签
        if not shell.behavior.hold(sprite, clips):
            log.debug("会话小鱼：素材库里没有 %s，退回随机行为", clips)
