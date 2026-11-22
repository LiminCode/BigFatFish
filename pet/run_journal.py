# -*- coding: utf-8 -*-
"""运行记录：肥鱼自己跑的每一件事记一行——哪个任务、被什么触发、每一步多久、结果、它对外面做了什么。

配置全景是某一刻的截面；这里是时间轴。它是三样东西共同的来源：磁贴上的运行历史条、每个定时任务此刻的状态、
按时间倒序的瀑布流页。仓库里发生了什么不记在这里——那本账是 git 自己；这里只记 git 不知道的那一半（谁、为什么、
多久、成没成），两边靠提交号对上。

落在数据目录的 ``run-journal/<年>-<月>.jsonl``，一行一个 JSON 对象::

    {"id": "20261122T150903-3f2a9c", "job": "vault_check", "trigger": "manual", "at": "2026-11-22 15:09:03",
     "seconds": 1.77, "result": "ok", "steps": [{"name": "fetch", "seconds": 1.7}],
     "effects": [{"kind": "git", "op": "fetch", "repo": "personal", "before": "1a2b3c4…", "after": "5d6e7f8…", "behind": 46, "ahead": 0}]}

- ``trigger``：``TRIGGERS`` 之一；``result``：``RESULTS`` 之一（``noop`` = 跑了、没事可做，页面上会折叠）。
- ``effects`` 是个通用的列表：``kind`` 说是哪一类（现在只有 ``git``），其余字段由那一类自己定。加一类效果不用改这里。
- **只记元数据**：没有正文、没有提交说明、没有文件名。``error`` 只留报错的末 ``ERROR_LIMIT`` 个字符。
- 按月分文件；整个月都早于 ``KEEP_DAYS`` 天之前的文件，在下一次写的时候删掉。不重写文件，所以不需要「写临时文件再替换」。

存储表里登记为日志、丢了不要紧（``run_journal``）：仓库那一半本来就在 git 里，丢的只是耗时和触发原因这类诊断信息。

**只用标准库、不碰 Qt。** 同步器、各个定时服务、页面的请求线程都会从后台线程来写，所以追加在一把锁里、一次 ``write``；
读的人最多看到末尾半行，解析不了的行跳过。写不进去只进日志、不抛：要记的那件事已经做完了，不能因为记不上就让它变成失败。
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import logging
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Iterator

log = logging.getLogger("big-fat-fish")

DIR_NAME = "run-journal"
KEEP_DAYS = 90
ERROR_LIMIT = 200
#: 被什么触发：到点 / 停笔一会儿之后 / 肥鱼启动后 / 睡眠唤醒后 / 用户点的 / 肥鱼自己的某个功能写完东西之后
TRIGGERS = ("schedule", "idle", "startup", "wake", "manual", "feature")
#: 结果：办成了并且有变化 / 跑了、没事可做 / 没办成 / 停下来等用户（冲突、待审核）/ 这次跳过（上一次还没跑完）
RESULTS = ("ok", "noop", "failed", "needs_you", "skipped")

_JOB = re.compile(r"[a-z][a-z0-9_]*")
_MONTH_FILE = re.compile(r"(\d{4})-(\d{2})\.jsonl")


class Run:
    """一次正在进行的运行。``step`` 给每一步计时，``effect`` 记它对外面做了什么，``finish`` 落盘（只落一次）。"""

    def __init__(self, journal: "Journal", job: str, trigger: str) -> None:
        self._journal = journal
        self._started_at, self._started = journal._now(), journal._timer()
        self._row = {"id": f"{self._started_at:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}", "job": job, "trigger": trigger,
                     "at": f"{self._started_at:%Y-%m-%d %H:%M:%S}", "seconds": 0.0, "result": "", "steps": [], "effects": []}
        self._done = False

    @contextlib.contextmanager
    def step(self, name: str) -> Iterator[None]:
        """给一步计时。那一步抛了异常也照样记下用了多久，异常原样往外抛。"""
        started = self._journal._timer()
        try:
            yield
        finally:
            self._row["steps"].append({"name": str(name), "seconds": round(self._journal._timer() - started, 2)})

    def effect(self, kind: str, **fields) -> None:
        self._row["effects"].append({"kind": str(kind), **fields})

    def finish(self, result: str, error: str = "") -> bool:
        """收尾并落盘；返回记没记上。第二次调用什么都不做（返回 ``False``）。"""
        if result not in RESULTS:
            raise ValueError(f"unknown result {result!r}")
        if self._done:
            return False
        self._done = True
        self._row["seconds"] = round(self._journal._timer() - self._started, 2)
        self._row["result"] = result
        error = str(error or "").strip()
        if error:
            self._row["error"] = error[-ERROR_LIMIT:]
        return self._journal._append(self._started_at, self._row)


class Journal:
    def __init__(self, directory: str | Path, *, keep_days: int = KEEP_DAYS, now: Callable[[], dt.datetime] = dt.datetime.now,
                 timer: Callable[[], float] = time.perf_counter) -> None:
        self.directory = Path(directory)
        self._keep_days, self._now, self._timer = keep_days, now, timer
        self._lock = threading.Lock()

    def start(self, job: str, trigger: str) -> Run:
        """开一条记录。任务名不是标识符、触发原因没在 ``TRIGGERS`` 里登记，是写代码的人的错：直接抛。"""
        if not _JOB.fullmatch(str(job)) or trigger not in TRIGGERS:
            raise ValueError(f"bad run: job={job!r} trigger={trigger!r}")
        return Run(self, job, trigger)

    def read(self, limit: int | None = None, *, job: str | None = None) -> list[dict]:
        """最近的记录，新的在前；``job`` 只要某一个任务的。解析不了的行跳过；目录不在就是空的。"""
        rows: list[dict] = []
        for path in sorted(self._month_files(), reverse=True):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for line in reversed(lines):
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict) or (job is not None and row.get("job") != job):
                    continue
                rows.append(row)
                if limit is not None and len(rows) >= limit:
                    return rows
        return rows

    def _month_files(self) -> list[Path]:
        try:
            return [path for path in self.directory.iterdir() if _MONTH_FILE.fullmatch(path.name)]
        except OSError:
            return []

    def _append(self, started_at: dt.datetime, row: dict) -> bool:
        line = json.dumps(row, ensure_ascii=False) + "\n"
        with self._lock:
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                with open(self.directory / f"{started_at:%Y-%m}.jsonl", "a", encoding="utf-8", newline="\n") as handle:
                    handle.write(line)
            except OSError as exc:
                log.warning("运行记录写不进去：%s（%s）", self.directory, exc)
                return False
            self._prune(started_at.date())
        return True

    def _prune(self, today: dt.date) -> None:
        """删掉整个月都在保留窗口之外的文件：那个月的最后一天早于「今天往前 ``keep_days`` 天」。"""
        cutoff = today - dt.timedelta(days=self._keep_days)
        for path in self._month_files():
            year, month = (int(part) for part in _MONTH_FILE.fullmatch(path.name).groups())
            if not 1 <= month <= 12:
                continue
            next_month = dt.date(year + 1, 1, 1) if month == 12 else dt.date(year, month + 1, 1)
            if next_month - dt.timedelta(days=1) < cutoff:
                try:
                    path.unlink()
                except OSError as exc:
                    log.warning("过期的运行记录删不掉：%s（%s）", path, exc)
