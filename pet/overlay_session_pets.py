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
import time
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal, Slot

from . import claude_hooks

log = logging.getLogger(__name__)


class SessionPetController(QObject):
    """``(agent_key, sessionId)`` → 一只会话小鱼：标签 + 保持动画 + 生灭。"""

    #: 忙：在这组里轮播；休息：循环这一段；做完了等用户来看：庆祝一下再东张西望。
    #: 素材库里没有的自动跳过（换了角色），一段都没有就不保持——小鱼退回普通的
    #: 随机行为，标签照常显示。
    WORK_CLIPS: tuple[str, ...] = ("写代码", "吃Token")
    REST_CLIPS: tuple[str, ...] = ("原地小憩沉眠",)
    REVIEW_CLIPS: tuple[str, ...] = ("工作状态-雀跃庆祝", "工作状态-原地踱步张望")
    PHASE_TEXT = claude_hooks.PHASE_TEXT
    AGENT_KEYS = ("claude", "claude_wsl")

    #: 在用的会话有增减 / 换阶段 / 换标签（灵动岛卡片据此刷新）
    sessions_changed = Signal()
    #: 一个会话离场了（``(agent_key, sessionId)``）：详情缓存、正开着的详情卡据此收掉
    session_gone = Signal(object)

    def __init__(self, shell, *, enabled: Callable[[], bool], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._shell = shell
        self._enabled = enabled
        self._pets: dict[tuple[str, str], Any] = {}
        self._phases: dict[tuple[str, str], str] = {}
        # 在用的会话登记表：与「有没有鱼」无关——功能关着、超出上限的会话也照记，
        # 灵动岛卡片要的是「有哪些会话」。
        self._sessions: dict[tuple[str, str], dict] = {}
        # 详情用的附加信息：完整工作目录、transcript 路径、最近调用的工具、当前阶段
        # 的起始时刻。不进 _sessions——那张表的内容变化会触发灵动岛刷新。
        self._extras: dict[tuple[str, str], dict] = {}
        # 用户点了「让这只离场」的会话：到它关闭为止不再生小鱼
        self._dismissed: set[tuple[str, str]] = set()
        # 回合结束了、用户还没去看的会话：显示成「等你回复」而不是「休息中」
        self._unseen: set[tuple[str, str]] = set()

    # ------------------------------------------------------------ sprite ↔ 会话
    def key_of(self, sprite) -> tuple[str, str] | None:
        """这只 sprite 代表哪个会话（``(agent_key, sessionId)``）；不是会话小鱼 → None。"""
        for key, owned in self._pets.items():
            if owned is sprite:
                return key
        return None

    def sprite_of(self, key: tuple[str, str]):
        return self._pets.get(key)

    def describe(self, key: tuple[str, str]) -> dict | None:
        """一个会话的已知信息：``sessions()`` 的那几项 + ``cwd / transcript / tool``。"""
        info = self._sessions.get(key)
        if info is None:
            return None
        extras = self._extras.get(key, {})
        return {**info, **{k: v for k, v in extras.items() if k != "since"}}

    def since(self, key: tuple[str, str]) -> float | None:
        """当前阶段（工作中 / 等批准 / 休息中）是从什么时候开始的（Unix 秒）。

        「等你回复」与看过之后的「休息中」共用一个起点：回合结束的那一刻。"""
        return self._extras.get(key, {}).get("since")

    def acknowledge(self, key: tuple[str, str]) -> bool:
        """用户去看过这个会话了（点了「跳到对话」）：「等你回复」落回「休息中」。

        返回是否真的改了——本来就不在等回复（在干活、已经看过、不认识）返回 False。"""
        info = self._sessions.get(key)
        if info is None or key not in self._unseen:
            return False
        self._unseen.discard(key)
        log.info("会话已看过，落回休息 agent=%s session=%s", key[0], key[1][:8])
        self.on_session_update(key[0], {**info, **self._extras.get(key, {})})
        return True

    def dismiss(self, sprite) -> bool:
        """让这只小鱼离场，并且这个会话关闭之前不再为它生小鱼。"""
        key = self.key_of(sprite)
        if key is None:
            return False
        self._dismissed.add(key)
        self._retire(key)
        return True

    def retitle(self, key: tuple[str, str], title: str) -> bool:
        """把一个在场会话的标题改成 ``title``（头顶的名字、灵动岛清单随之更新）。

        用在「读会话记录时发现用户改过名」：hook 要到下一轮对话才会把新名字报上来，
        会话空闲期间改的名字先由这里补上。返回是否真的改了。"""
        info = self._sessions.get(key)
        title = str(title or "").strip()
        if info is None or not title or info.get("title") == title:
            return False
        self.on_session_update(key[0], {**info, **self._extras.get(key, {}), "title": title})
        return True

    def sessions(self) -> list[dict]:
        """在用的会话：``{"agent", "sessionId", "phase", "title", "project"}``，按出场先后。"""
        return [{"agent": key[0], **info} for key, info in self._sessions.items()]

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

    def _presented_phase(self, key: tuple[str, str], phase: str, previous: str) -> str:
        """收敛器报的阶段 → 显示的阶段：回合结束后、用户去看之前是 ``review``。

        收敛器只知道「回合结束了」（``resting``）；「用户看过没有」是这一层的事。
        刚从干活 / 等批准转入休息的会话记为没看过，到 ``acknowledge`` 或它的下一次
        提问为止。桌宠启动时就已经停着的会话不算——没人知道它是不是早被看过了。"""
        if phase == "review":       # 把自己登记表里的内容回放进来（retitle / acknowledge）
            phase = "resting"
        if phase != "resting":
            self._unseen.discard(key)
            return phase
        if previous in ("working", "waiting"):
            self._unseen.add(key)
            log.info("会话回合结束，等用户来看 agent=%s session=%s", key[0], key[1][:8])
        return "review" if key in self._unseen else "resting"

    @Slot(str, object)
    def on_session_update(self, agent_key, update) -> None:
        if not isinstance(update, dict):
            return
        key = (str(agent_key), str(update.get("sessionId") or ""))
        phase = str(update.get("phase") or "")
        if phase != "gone" and phase not in self.PHASE_TEXT:
            return
        if phase == "gone":
            changed = self._sessions.pop(key, None) is not None
            self._extras.pop(key, None)
            self._dismissed.discard(key)
            self._unseen.discard(key)
            self.session_gone.emit(key)
        else:
            previous_info = self._sessions.get(key)
            previous_phase = previous_info["phase"] if previous_info is not None else ""
            phase = self._presented_phase(key, phase, previous_phase)
            info = {"sessionId": key[1], "phase": phase,
                    "title": str(update.get("title") or ""), "project": str(update.get("project") or "")}
            changed = previous_info != info
            self._sessions[key] = info
            extras = self._extras.setdefault(key, {})
            for name in ("cwd", "transcript", "tool"):
                if update.get(name):
                    extras[name] = str(update[name])
            seen_now = previous_phase == "review" and phase == "resting"
            if previous_phase != phase and not seen_now:
                extras["since"] = time.time()
        if changed:
            self.sessions_changed.emit()
        shell = self._shell
        sprite = self._pets.get(key)
        if sprite is not None and not shell.is_session_pet(sprite):
            # 用户手动把这只退掉了（「退出这只」/「退出子肥鱼」）：忘掉它
            self._pets.pop(key, None)
            self._phases.pop(key, None)
            sprite = None
        if phase == "gone" or not self._enabled() or key in self._dismissed:
            self._retire(key)
            return
        if sprite is None:
            if phase in ("resting", "review"):
                return  # 没赶上它干活（或刚被退掉）：不凭空生一只，等它下次提问
            sprite = shell.spawn_session_pet()
            if sprite is None:
                return  # 到上限：这个会话只体现在主肥鱼的汇总状态里
            self._pets[key] = sprite
            log.info("会话小鱼出场 agent=%s session=%s（在场 %d 只）", key[0], key[1][:8], len(self._pets))
        shell.set_session_pet_caption(
            sprite, f"{claude_hooks.session_label(key[0], self._sessions[key])} · {self.PHASE_TEXT[phase]}",
            tone=phase)
        previous = self._phases.get(key)
        if previous == phase:
            return  # 只是标签变了：不重启正在播的动画
        self._phases[key] = phase
        if phase == "resting":
            clips = self.REST_CLIPS
        elif phase == "review":
            clips = self.REVIEW_CLIPS
        elif phase == "working" or previous is None:
            clips = self.WORK_CLIPS
        else:
            return  # 干活途中转入等批准：姿势不变，只换标签
        if not shell.behavior.hold(sprite, clips):
            log.debug("会话小鱼：素材库里没有 %s，退回随机行为", clips)
