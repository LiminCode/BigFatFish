# -*- coding: utf-8 -*-
"""今日用量：今天所有 Claude Code 对话用掉的 token（纯逻辑 + 本机读取，零 Qt）。

数字来自 Claude Code 自己的对话记录——``~/.claude/projects/<项目>/<会话>.jsonl`` 里每条
回复（``type: assistant``）带的 ``message.usage``。纯本地、不联网、不需要 API Key。
那是它的**内部格式**（字段随版本变），所以读不懂的行一律跳过，绝不因此出错。

实机核对过的三件事（2026-10-11，本机当天 35.7MB 记录）：

- **同一条回复会被写好几行**：流式回复的每个内容块各写一行、带同一个 ``message.id``
  （最多见过 10 行），后写的 ``output_tokens`` 更大。按 ``(message.id, requestId)`` 去重，
  每个字段取最大值。不去重会多算好几倍。
- **子代理的记录在另一个目录**：``<项目>/<会话>/subagents/*.jsonl``，一并统计。
- **一个对话可以跨过零点**：按每条记录自己的时间戳判断是不是今天（本机时区）。

「今日用量」= 输入 + 输出 + 缓存写入。**缓存读取单列、不计入**：它是同一段上下文每
一轮被重读一遍，量级是别的几十倍（当天 1.88 亿 vs 238 万），算进去就只剩它了。

``UsageMeter`` 是增量的：记住每个文件读到哪了，之后每次只读新追加的部分（首次
35.7MB 约 0.1 秒，之后通常几 KB）。阻塞调用，由调用方放到后台线程
（``claude_usage_monitor``）。只统计本机；WSL 发行版里的对话不在内。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

_USAGE_MARK = b'"usage"'
#: usage 里的字段 → 本模块的名字
_FIELDS = (("input", "input_tokens"), ("output", "output_tokens"),
           ("cache_write", "cache_creation_input_tokens"), ("cache_read", "cache_read_input_tokens"))
_PATTERNS = ("*/*.jsonl", "*/*/subagents/*.jsonl")


def format_tokens(count: int) -> str:
    """token 数的短写法：856 / 12.3K / 2.38M / 190M / 1.23B。"""
    count = max(0, int(count))
    if count < 1000:
        return str(count)
    for unit, size in (("K", 1e3), ("M", 1e6), ("B", 1e9)):
        value = count / size
        if value < 999.95 or unit == "B":
            if unit == "K":
                return f"{value:.1f}K"
            return f"{value:.2f}{unit}" if value < 9.995 else f"{value:.1f}{unit}" if value < 99.95 else f"{value:.0f}{unit}"
    return str(count)


@dataclass(frozen=True)
class UsageTotals:
    """一天的合计。"""

    input: int = 0
    output: int = 0
    cache_write: int = 0
    cache_read: int = 0
    messages: int = 0

    @property
    def tokens(self) -> int:
        """今日用量：输入 + 输出 + 缓存写入（不含缓存读取，见模块说明）。"""
        return self.input + self.output + self.cache_write

    @property
    def headline(self) -> str:
        return f"今日 {format_tokens(self.tokens)}"

    @property
    def detail(self) -> str:
        return (f"今日 Claude Code 用量 {format_tokens(self.tokens)}：输出 {format_tokens(self.output)}"
                f" · 输入 {format_tokens(self.input)} · 缓存写入 {format_tokens(self.cache_write)}"
                f"（另有缓存读取 {format_tokens(self.cache_read)}，不计入）")


def local_midnight(now: float) -> float:
    """``now`` 所在那一天的零点（本机时区）。"""
    return datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def _number(value) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


class UsageMeter:
    """今天的用量（增量统计，见模块说明）。不是线程安全的：同一时刻只让一个线程调。"""

    def __init__(self, home: Path | None = None, *, clock: Callable[[], float] = time.time,
                 day_start: Callable[[float], float] = local_midnight) -> None:
        self._projects = (home or Path.home()) / ".claude" / "projects"
        self._clock = clock
        self._day_start = day_start
        self._day: float | None = None
        self._messages: dict[tuple, tuple[int, int, int, int]] = {}
        self._files: dict[str, tuple[int, bytes]] = {}     # 路径 → (读到哪了, 没写完的那半行)
        self.bytes_read = 0

    def refresh(self) -> UsageTotals:
        """读入新追加的记录，返回今天到现在的合计。"""
        day = self._day_start(self._clock())
        if day != self._day:                               # 过了零点：从头算
            self._day = day
            self._messages.clear()
            self._files.clear()
        for path in self._todays_files(day):
            self._read_new(path, day)
        sums = [sum(values[index] for values in self._messages.values()) for index in range(4)]
        return UsageTotals(*sums, messages=len(self._messages))

    def _todays_files(self, day: float) -> list[Path]:
        found = []
        try:
            for pattern in _PATTERNS:
                for path in self._projects.glob(pattern):
                    try:
                        if path.stat().st_mtime >= day:
                            found.append(path)
                    except OSError:
                        continue
        except OSError:
            return []
        return found

    def _read_new(self, path: Path, day: float) -> None:
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
            if _USAGE_MARK in line:                        # 先粗筛：绝大多数行不带 usage
                self._count(line, day)

    def _count(self, line: bytes, day: float) -> None:
        try:
            record = json.loads(line)
        except ValueError:
            return
        message = record.get("message") if isinstance(record, dict) else None
        usage = message.get("usage") if isinstance(message, dict) else None
        if not isinstance(usage, dict):
            return
        try:
            when = datetime.fromisoformat(str(record.get("timestamp")).replace("Z", "+00:00")).timestamp()
        except ValueError:
            return
        if when < day:
            return
        key = (message.get("id") or record.get("uuid"), record.get("requestId"))
        values = tuple(_number(usage.get(source)) for _name, source in _FIELDS)
        previous = self._messages.get(key)
        self._messages[key] = values if previous is None else tuple(map(max, previous, values))
