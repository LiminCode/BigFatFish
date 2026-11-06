# -*- coding: utf-8 -*-
"""消息记录：大肥鱼头上冒过的每一条通知气泡都留一份（纯逻辑 + 一个 JSON 文件，零 Qt）。

为什么要有它（用户 2026-11-05）：气泡几秒就收，Slack 总结、「Claude Code 干完活啦」、
需要批准的提醒……错过了就没了。灵动岛展开的卡片里原来铺的是 Windows 通知中心里的 Slack
通知，现在换成这份记录：每条写明是哪个对话（会话小鱼卡片上那个标题 + 从哪开的）、什么时候、
说了什么。

进来的是什么：壳的 ``show_bubble`` / ``show_alert``（``OverlayShell``）与肥鱼隐藏时改道到岛的
反馈气泡——也就是「通知」性质的气泡。自言自语、识屏答复、会话小鱼动作的回执（「已复制」）不走
这两个口，所以不进记录。

每条记录：

- ``text`` / ``subtitle``：气泡正文与副标题；``kind`` 是 ``bubble``（限时）或 ``alert``（提醒队列）。
- ``agent`` / ``session_id``：来自哪个 Claude Code 会话（联动管理器知道时才有；大肥鱼自己的
  消息两者为空）。``title`` / ``host`` / ``where`` / ``path`` 是记录当时解析好的会话标题、
  来源图标种类、来源文字、工作目录——会话结束后记录还在，所以要在记录时定格。
- ``uid``：进程内外都稳定的递增整数（存盘里记着上一个号）。

「新的」= ``uid`` 大于用户上次打开消息框时看到的最大号（``seen_uid``）；跨重启有效。
同一条文案在 ``DEDUP_S`` 秒内重复到达（审批气泡被重新挂上、隐藏期改道又记一遍）只记一次。
只留最近 ``keep`` 条。文件 ``message-log.json``，和「最近的对话」放同一个目录。
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

LOG_FILE = "message-log.json"
DEFAULT_KEEP = 200
KEEP_RANGE = (10, 1000)
DEDUP_S = 60.0
KINDS = ("bubble", "alert")
_TEXT_LIMIT = 2000


@dataclass(frozen=True)
class Message:
    """一条记录。``key`` 是会话键 ``(agent, session_id)``，大肥鱼自己的消息为 None。"""

    uid: int
    at: float
    text: str
    subtitle: str = ""
    kind: str = "bubble"
    agent: str = ""
    session_id: str = ""
    title: str = ""
    host: str = ""
    where: str = ""
    path: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str] | None:
        return (self.agent, self.session_id) if self.agent and self.session_id else None

    def to_json(self) -> dict:
        data = asdict(self)
        if not data["extra"]:
            data.pop("extra")
        return data

    @classmethod
    def from_json(cls, data) -> "Message | None":
        if not isinstance(data, dict):
            return None
        try:
            uid, at = int(data["uid"]), float(data["at"])
        except (KeyError, TypeError, ValueError):
            return None
        text = str(data.get("text") or "")
        if uid <= 0 or not text:
            return None
        kind = str(data.get("kind") or "bubble")
        extra = data.get("extra")
        return cls(uid=uid, at=at, text=text[:_TEXT_LIMIT], subtitle=str(data.get("subtitle") or ""),
                   kind=kind if kind in KINDS else "bubble",
                   agent=str(data.get("agent") or ""), session_id=str(data.get("session_id") or ""),
                   title=str(data.get("title") or ""), host=str(data.get("host") or ""),
                   where=str(data.get("where") or ""), path=str(data.get("path") or ""),
                   extra=dict(extra) if isinstance(extra, dict) else {})


def _clamp(value, default: int, bounds: tuple[int, int]) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default
    return max(bounds[0], min(bounds[1], value))


class MessageLog:
    """最近的通知气泡，新的在前。不是线程安全的：只在 GUI 线程上用。

    ``listeners`` 里的回调在记录有变化（新增 / 移除 / 清空 / 看过）之后被调一次，不带参数。
    """

    def __init__(self, path: Path | str | None = None, *, keep: int = DEFAULT_KEEP,
                 clock: Callable[[], float] = time.time) -> None:
        self._path = Path(path) if path else None
        self._clock = clock
        self.keep = _clamp(keep, DEFAULT_KEEP, KEEP_RANGE)
        self._messages: list[Message] = []          # 新的在前
        self._next_uid = 1
        self._seen_uid = 0
        self.ui_open = True                          # 岛上的折叠框开着没有（界面状态，跟着数据一起存）
        self.listeners: list[Callable[[], None]] = []
        self._load()

    # ---------------------------------------------------------------- 读
    def messages(self) -> list[Message]:
        return list(self._messages)

    def __len__(self) -> int:
        return len(self._messages)

    def find(self, uid) -> Message | None:
        try:
            uid = int(uid)
        except (TypeError, ValueError):
            return None
        for message in self._messages:
            if message.uid == uid:
                return message
        return None

    def is_unread(self, message: Message) -> bool:
        return message.uid > self._seen_uid

    @property
    def unread_count(self) -> int:
        return sum(1 for message in self._messages if message.uid > self._seen_uid)

    # ---------------------------------------------------------------- 记
    def record(self, text: str, *, subtitle: str = "", kind: str = "bubble", agent: str = "",
               session_id: str = "", title: str = "", host: str = "", where: str = "", path: str = "",
               extra: dict | None = None) -> Message | None:
        """记一条；空文案不记，``DEDUP_S`` 秒内同一会话的同一条文案不重复记。返回新记录或 None。"""
        text = " ".join(str(text or "").split())[:_TEXT_LIMIT]
        if not text:
            return None
        now = self._clock()
        agent, session_id = str(agent or ""), str(session_id or "")
        if not (agent and session_id):
            agent = session_id = ""
        subtitle = " ".join(str(subtitle or "").split())
        for recent in self._messages:
            if now - recent.at > DEDUP_S:
                break
            if recent.text == text and recent.subtitle == subtitle and (recent.agent, recent.session_id) == (agent, session_id):
                return None
        message = Message(uid=self._next_uid, at=now, text=text, subtitle=subtitle,
                          kind=kind if kind in KINDS else "bubble", agent=agent, session_id=session_id,
                          title=str(title or ""), host=str(host or ""), where=str(where or ""),
                          path=str(path or ""), extra=dict(extra or {}))
        self._next_uid += 1
        self._messages.insert(0, message)
        del self._messages[self.keep:]
        self._changed()
        return message

    def mark_all_seen(self) -> bool:
        """用户打开了消息框：现有的都算看过。返回有没有变化。"""
        top = self._messages[0].uid if self._messages else self._next_uid - 1
        if top <= self._seen_uid:
            return False
        self._seen_uid = top
        self._changed()
        return True

    def remove(self, uid) -> bool:
        message = self.find(uid)
        if message is None:
            return False
        self._messages = [m for m in self._messages if m.uid != message.uid]
        self._changed()
        return True

    def clear(self) -> bool:
        if not self._messages:
            return False
        self._messages = []
        self._seen_uid = self._next_uid - 1
        self._changed()
        return True

    def retitle(self, key: tuple[str, str], **fields) -> bool:
        """会话标题 / 来源后来才知道：把这个会话已有的记录补上（只填空的字段）。"""
        changed = False
        updated = []
        for message in self._messages:
            if message.key == key:
                patch = {name: str(value) for name, value in fields.items()
                         if value and not getattr(message, name, None) and name in ("title", "host", "where", "path")}
                if patch:
                    message = replace(message, **patch)
                    changed = True
            updated.append(message)
        if changed:
            self._messages = updated
            self._changed()
        return changed

    # ---------------------------------------------------------------- 落盘
    def _changed(self) -> None:
        self.save()
        for listener in list(self.listeners):
            try:
                listener()
            except Exception:  # noqa: BLE001 - 一个听众出错不影响别的
                log.exception("消息记录：通知听众失败")

    def _load(self) -> None:
        if self._path is None:
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        messages = [m for m in (Message.from_json(item) for item in data.get("messages") or []) if m is not None]
        messages.sort(key=lambda m: m.uid, reverse=True)
        seen: set[int] = set()
        self._messages = [m for m in messages if not (m.uid in seen or seen.add(m.uid))][:self.keep]
        top = self._messages[0].uid if self._messages else 0
        self._next_uid = max(_clamp(data.get("next_uid"), 1, (1, 1 << 62)), top + 1)
        self._seen_uid = min(_clamp(data.get("seen_uid"), 0, (0, 1 << 62)), self._next_uid - 1)
        self.ui_open = bool(data.get("ui_open", True))

    def save(self) -> None:
        if self._path is None:
            return
        payload = json.dumps({"version": 1, "next_uid": self._next_uid, "seen_uid": self._seen_uid,
                              "ui_open": self.ui_open, "messages": [m.to_json() for m in self._messages]},
                             ensure_ascii=False, separators=(",", ":"))
        temp = self._path.with_name(self._path.name + ".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text(payload, encoding="utf-8")
            os.replace(temp, self._path)
        except OSError:
            log.warning("消息记录：写入 %s 失败", self._path, exc_info=True)
