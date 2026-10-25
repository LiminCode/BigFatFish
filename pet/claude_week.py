# -*- coding: utf-8 -*-
"""最近 7 天每天的 Claude Code 用量与「我发了几条消息」（纯逻辑 + 本机读取，零 Qt）。

仪表盘的两张磁贴用它。数据和 ``claude_usage``（灵动岛「今日用量」）同一来源、同一口径：
``~/.claude/projects`` 下的对话记录，回复按 ``(message.id, requestId)`` 去重、字段取最大，
用量 = 输入 + 输出 + 缓存写入，子代理目录一并统计，**按自然日（零点）分天**——所以
仪表盘上「今天」那根柱子和岛上的数字是同一个数。

「发了几条消息」= 所有会话里用户真正发出去的那几条（``type: user``），下面这些不算
（2026-10-24 对本机一周记录逐类核对过）：

- 工具结果（``content`` 里有 ``tool_result``）——每次工具调用都会写一条 ``user`` 记录，
  一周 2252 条，是真消息的几十倍；
- 子代理收到的任务（``isSidechain``）、系统注入（``isMeta``：技能说明、图片来源、别的会话
  发来的消息）、压缩后的摘要（``isCompactSummary``）；
- Claude Code 自己写进来的文字：后台任务通知 ``<task-notification>``、本地命令的输出
  ``<local-command-stdout>`` 等、``[Request interrupted by user]``。

斜杠命令（``<command-name>``）是用户自己敲的，算一条。按 ``uuid`` 去重（复制出来的
会话会带着同样的记录）。

``WeekMeter`` 是增量的：和 ``UsageMeter`` 一样记住每个文件读到哪了。阻塞调用，放到
后台线程（``usage_dashboard``）。
"""

from __future__ import annotations

import datetime as dt
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .claude_usage import _FIELDS, _PATTERNS, _number

DAYS = 7
_USAGE_MARK = b'"usage"'
_USER_MARK = b'"user"'
_NOT_PROMPTS = ("<task-notification>", "<local-command-", "[Request interrupted")


@dataclass(frozen=True)
class DayUsage:
    day: dt.date
    input: int = 0
    output: int = 0
    cache_write: int = 0
    cache_read: int = 0
    prompts: int = 0

    @property
    def tokens(self) -> int:
        """和 ``UsageTotals.tokens`` 同一口径：不含缓存读取。"""
        return self.input + self.output + self.cache_write


def _local_day(stamp) -> dt.date | None:
    try:
        when = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        return when.date()
    return dt.datetime.fromtimestamp(when.timestamp()).date()


def is_user_prompt(record: dict) -> bool:
    """这条记录是不是用户自己发出去的一条消息（口径见模块说明）。"""
    if record.get("type") != "user":
        return False
    if any(record.get(flag) for flag in ("isSidechain", "isMeta", "isCompactSummary", "isVisibleInTranscriptOnly")):
        return False
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        blocks = [block for block in content if isinstance(block, dict)]
        if any(block.get("type") == "tool_result" for block in blocks):
            return False
        texts = [str(block.get("text") or "") for block in blocks if block.get("type") == "text"]
        if not texts and not any(block.get("type") == "image" for block in blocks):
            return False
        text = texts[0] if texts else ""
    else:
        return False
    return not text.lstrip().startswith(_NOT_PROMPTS)


class WeekMeter:
    """最近 ``DAYS`` 天（含今天）每天的用量与消息数。不是线程安全的：同一时刻只让一个线程调。"""

    def __init__(self, home: Path | None = None, *, clock: Callable[[], float] = time.time,
                 today: Callable[[float], dt.date] = lambda now: dt.datetime.fromtimestamp(now).date()) -> None:
        self._projects = (home or Path.home()) / ".claude" / "projects"
        self._clock = clock
        self._today = today
        self._replies: dict[tuple, tuple[dt.date, tuple[int, int, int, int]]] = {}
        self._prompts: dict[str, dt.date] = {}
        self._files: dict[str, tuple[int, bytes]] = {}
        self.bytes_read = 0

    def refresh(self) -> list[DayUsage]:
        """读入新追加的记录；返回从 6 天前到今天、每天一项（没数据的天全是 0）。"""
        today = self._today(self._clock())
        first = today - dt.timedelta(days=DAYS - 1)
        floor = dt.datetime.combine(first, dt.time()).timestamp()
        for path in self._recent_files(floor):
            self._read_new(path, first)
        for key in [key for key, (day, _values) in self._replies.items() if day < first]:
            del self._replies[key]
        for key in [key for key, day in self._prompts.items() if day < first]:
            del self._prompts[key]
        days = [first + dt.timedelta(days=offset) for offset in range(DAYS)]
        sums = {day: [0, 0, 0, 0] for day in days}
        for day, values in self._replies.values():
            if day in sums:
                sums[day] = [a + b for a, b in zip(sums[day], values)]
        counts = {day: 0 for day in days}
        for day in self._prompts.values():
            if day in counts:
                counts[day] += 1
        return [DayUsage(day, *sums[day], prompts=counts[day]) for day in days]

    def _recent_files(self, floor: float) -> list[Path]:
        found = []
        try:
            for pattern in _PATTERNS:
                for path in self._projects.glob(pattern):
                    try:
                        if path.stat().st_mtime >= floor:
                            found.append(path)
                    except OSError:
                        continue
        except OSError:
            return []
        return found

    def _read_new(self, path: Path, first: dt.date) -> None:
        offset, carry = self._files.get(str(path), (0, b""))
        try:
            with open(path, "rb") as handle:
                handle.seek(0, 2)
                size = handle.tell()
                if size < offset:                          # 文件变短了（被重写）：从头读
                    offset, carry = 0, b""
                if size == offset:
                    return
                handle.seek(offset)
                data = handle.read(size - offset)
        except OSError:
            return
        self.bytes_read += len(data)
        data = carry + data
        complete, _newline, rest = data.rpartition(b"\n")   # 最后一行可能只写了一半：留到下次
        self._files[str(path)] = (offset + len(data) - len(carry), rest)
        for line in complete.split(b"\n"):
            if _USAGE_MARK in line or _USER_MARK in line:   # 先粗筛：跳过绝大多数行的 JSON 解析
                self._count(line, first)

    def _count(self, line: bytes, first: dt.date) -> None:
        try:
            record = json.loads(line)
        except ValueError:
            return
        if not isinstance(record, dict):
            return
        day = _local_day(record.get("timestamp"))
        if day is None or day < first:
            return
        message = record.get("message")
        usage = message.get("usage") if isinstance(message, dict) else None
        if isinstance(usage, dict):                        # 和 UsageMeter 一样：带 usage 的都算
            key = (message.get("id") or record.get("uuid"), record.get("requestId"))
            values = tuple(_number(usage.get(source)) for _name, source in _FIELDS)
            previous = self._replies.get(key)
            self._replies[key] = (day, values if previous is None else tuple(map(max, previous[1], values)))
        elif is_user_prompt(record):
            self._prompts[str(record.get("uuid") or len(self._prompts))] = day
