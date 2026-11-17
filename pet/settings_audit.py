# -*- coding: utf-8 -*-
"""设置的审计记录：页面每改一项设置，这里记一行——什么时候、哪一组的哪一项、旧值、新值、从哪改的。

落在数据目录的 ``settings-audit.jsonl``，一行一个 JSON 对象，最多留 ``DEFAULT_LIMIT`` 行（超了丢最早的）。
旧值和新值**记原文**（提示词也记，这样页面上才做得了「改回去」）；单个值超过 ``VALUE_LIMIT`` 个字符截断并标出来。
所以这个文件里会有公司侧的提示词：它只留在这台机器上，不进任何仓库（存储表里登记为 ``mixed`` / ``disposable``）。

**只用标准库、不碰 Qt。** 写只发生在主进程的界面线程（写入链路的最后一步）；读可以在本机服务的请求线程。
追加是一次 ``write``，整理是写临时文件再替换，所以读的人看到的要么是旧的、要么是新的，最多末尾一行不完整——
读的时候跳过解析不了的行。
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
from pathlib import Path
from typing import Callable

log = logging.getLogger("big-fat-fish")

FILE_NAME = "settings-audit.jsonl"
DEFAULT_LIMIT = 500         # 最多留这么多行
VALUE_LIMIT = 8192          # 单个旧值 / 新值最多记这么多个字符


def _now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class AuditLog:
    def __init__(self, path: str | Path, *, limit: int = DEFAULT_LIMIT, clock: Callable[[], str] = _now) -> None:
        self.path = Path(path)
        self._limit = limit
        self._clock = clock

    def _lines(self) -> list[str]:
        try:
            return [line for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except (OSError, UnicodeDecodeError):
            return []

    def append(self, entries: list[dict]) -> bool:
        """记下一次写入里的每一项改动（``group`` / ``setting`` / ``old`` / ``new`` / ``source``）。返回记没记上。

        记不上只进日志、不抛：设置已经存好了，不能因为审计文件写不了就让用户以为没存上。
        """
        stamp = self._clock()
        fresh = []
        for entry in entries:
            row = {"at": stamp, **entry}
            cut = [key for key in ("old", "new") if isinstance(row.get(key), str) and len(row[key]) > VALUE_LIMIT]
            for key in cut:
                row[key] = row[key][:VALUE_LIMIT]
            if cut:
                row["truncated"] = cut
            fresh.append(json.dumps(row, ensure_ascii=False))
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            kept = self._lines()
            if len(kept) + len(fresh) <= self._limit:
                with open(self.path, "a", encoding="utf-8", newline="\n") as handle:
                    handle.write("".join(line + "\n" for line in fresh))
            else:                                   # 超了：留最近的那些，整份重写（先写临时文件再替换）
                temp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
                temp.write_text("".join(line + "\n" for line in (kept + fresh)[-self._limit:]), encoding="utf-8", newline="\n")
                os.replace(temp, self.path)
        except OSError as exc:
            log.warning("设置审计记录写不进去：%s（%s）", self.path, exc)
            return False
        return True

    def read(self, limit: int | None = None) -> list[dict]:
        """最近的记录，新的在前。解析不了的行跳过。"""
        rows = []
        for line in reversed(self._lines()):
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
                if limit is not None and len(rows) >= limit:
                    break
        return rows
