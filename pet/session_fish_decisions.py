# -*- coding: utf-8 -*-
"""会话小鱼的「用户决定」：哪些会话被用户主动关掉了（纯逻辑 + 一个 JSON 文件，零 Qt）。

为什么要落盘（用户 2026-11-02）：小鱼要「一直在，除非我主动关闭」——重启肥鱼后从运行清单 /
最近的对话把会话认领回来时，必须记得哪些是用户关过的，不然一重启就全回来了。

语义：

- ``dismiss(key)``：用户点了「关闭这只」。到它**再次活跃**（又提了问 / 在等批准）为止不再为它生小鱼；
  冻结的（进程不在）、休息中的都算没活跃。
- ``revive(key)``：会话又活跃了，决定作废，小鱼照常出场。
- ``prune(keep)``：只保留还在名册里（运行清单 ∪ 最近 X 天的对话）的会话的决定；会话过期 / 真没了，
  决定跟着忘掉，新会话永远不会继承旧决定。

文件：``session-fish.json``，和「最近的对话」放同一个目录；只存会话 ID、通道、时间与当时的标题，不存对话内容。
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Callable, Iterable

log = logging.getLogger(__name__)

DECISIONS_FILE = "session-fish.json"
Key = tuple[str, str]


def _as_key(value) -> Key | None:
    try:
        agent, sid = value
    except (TypeError, ValueError):
        return None
    agent, sid = str(agent or ""), str(sid or "")
    return (agent, sid) if agent and sid else None


class SessionFishDecisions:
    """``{(agent, sessionId): {"at": 秒, "title": 标题}}``，变了就写盘。不是线程安全的：只在 GUI 线程上用。"""

    def __init__(self, path: Path | str | None = None, *, clock: Callable[[], float] = time.time) -> None:
        self._path = Path(path) if path else None
        self._clock = clock
        self._dismissed: dict[Key, dict] = {}

    # ---------------------------------------------------------------- 读
    def is_dismissed(self, key) -> bool:
        key = _as_key(key)
        return key is not None and key in self._dismissed

    def dismissed(self) -> list[Key]:
        return list(self._dismissed)

    def __len__(self) -> int:
        return len(self._dismissed)

    # ---------------------------------------------------------------- 改
    def dismiss(self, key, *, title: str = "") -> bool:
        key = _as_key(key)
        if key is None or key in self._dismissed:
            return False
        self._dismissed[key] = {"at": float(self._clock()), "title": str(title or "")[:80]}
        self.save()
        return True

    def revive(self, key) -> bool:
        """会话又活跃了：决定作废。返回之前是不是被关着。"""
        key = _as_key(key)
        if key is None or self._dismissed.pop(key, None) is None:
            return False
        self.save()
        return True

    def forget(self, key) -> bool:
        return self.revive(key)

    def prune(self, keep: Iterable) -> int:
        """只留 ``keep`` 里还有的会话的决定；返回丢掉了几条。"""
        wanted = {k for k in (_as_key(v) for v in keep) if k is not None}
        stale = [k for k in self._dismissed if k not in wanted]
        for k in stale:
            del self._dismissed[k]
        if stale:
            self.save()
        return len(stale)

    # ---------------------------------------------------------------- 盘
    def load(self) -> None:
        self._dismissed.clear()
        if self._path is None:
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        rows = data.get("dismissed") if isinstance(data, dict) else None
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            key = _as_key((row.get("agent"), row.get("session_id")))
            if key is None:
                continue
            try:
                at = float(row.get("at") or 0.0)
            except (TypeError, ValueError):
                at = 0.0
            self._dismissed[key] = {"at": at, "title": str(row.get("title") or "")[:80]}

    def save(self) -> bool:
        if self._path is None:
            return False
        rows = [{"agent": agent, "session_id": sid, **meta} for (agent, sid), meta in self._dismissed.items()]
        temp = self._path.with_name(self._path.name + ".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text(json.dumps({"version": 1, "dismissed": rows}, ensure_ascii=False, indent=1),
                            encoding="utf-8")
            os.replace(temp, self._path)
            return True
        except OSError:
            log.warning("会话小鱼：写入 %s 失败", self._path, exc_info=True)
            return False
