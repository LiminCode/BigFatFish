# -*- coding: utf-8 -*-
"""把已有的定时功能接进运行记录：不改那些服务，只听它们「开始了 / 结束了」的信号。零 Qt。

工作简报、个人简报、Slack 关注各有各的服务，都是同一个样子：``started(手动?)`` 开始、``finished(结果, 手动?, …)`` 结束。
这里的 ``Recorder`` 接在这两个信号上：开始时开一条运行记录，结束时把结果翻成运行记录里的那几项落盘。这样时间轴页、
功能磁贴上的历史条、「迟了」的判断，对它们和对知识库同步是同一套——而那几个服务一行都不用动。

每个功能一个「怎么读结果」的函数（``*_outcome``）：给它 ``finished`` 信号的参数，回 ``(手动?, 结果, 报错, 效果列表)``。
**只取数**：模型名、effort、token 数、轮数、条数。概要、正文、标题一个字都不进运行记录（ADR 0019）。

记录器挂在服务的信号上，和界面收结果是同一批槽，所以它**自己绝不往外抛**：读不懂结果就记一条失败，记不上就算了。
它在界面线程上跑（信号是排回界面线程的），做的事只有一次几百微秒的追加写。
"""
from __future__ import annotations

import logging
from typing import Callable

log = logging.getLogger(__name__)

#: 运行记录里的任务名
WORK_BRIEFING = "work_briefing"
PERSONAL_BRIEFING = "personal_briefing"
SLACK_WATCH = "slack_watch"
CAPTURE_ORGANIZE = "capture_organize"     # = capture_organize.JOB（这里不导入它：本模块只认信号参数的形状）

Outcome = Callable[..., "tuple[bool, str, str, list[dict]]"]


def briefing_outcome(briefing, manual: bool = False) -> tuple[bool, str, str, list[dict]]:
    """工作简报 / 个人简报的 ``finished(Briefing, 手动?)``。两种简报的结果对象字段一样。"""
    effect = {"kind": "model", "model": str(briefing.model or ""), "effort": str(briefing.effort or ""),
              "tokens_in": int(briefing.tokens_in or 0), "tokens_out": int(briefing.tokens_out or 0), "turns": int(briefing.turns or 0)}
    return bool(manual), "ok" if briefing.ok else "failed", "" if briefing.ok else str(briefing.error or ""), [effect]


def slack_outcome(result, manual: bool = False, fresh=()) -> tuple[bool, str, str, list[dict]]:
    """Slack 关注的 ``finished(WatchResult, 手动?, 新的几条)``。看了一眼、没有新的 = 跑了没事可做。"""
    effect = {"kind": "found", "items": len(result.items or []), "new": len(fresh or []), "turns": int(result.turns or 0)}
    state = "failed" if not result.ok else "ok" if fresh else "noop"
    return bool(manual), state, "" if result.ok else str(result.error or ""), [effect]


def organize_outcome(result, manual: bool = False) -> tuple[bool, str, str, list[dict]]:
    """随手记整理的 ``finished(Result, 手动?)``：用的模型、整理 / 跳过 / 失败 / 剩下几条；推上去了就带提交号，
    时间轴把那个提交挂在这次运行下面。笔记的标题和路径不进运行记录。"""
    effects = [{"kind": "model", "model": str(result.model or ""), "effort": str(result.effort or ""),
                "tokens_in": int(result.tokens_in or 0), "tokens_out": int(result.tokens_out or 0), "turns": int(result.turns or 0)},
               {"kind": "notes", "organized": int(result.organized or 0), "skipped": int(result.skipped or 0),
                "failed": int(result.failed or 0), "left": int(result.left or 0)}]
    if result.commit:
        effects.append({"kind": "git", "op": "commit", "repo": "personal", "pushed_ids": [str(result.commit)]})
    return bool(manual), str(result.state or "failed"), "" if result.ok else str(result.error or ""), effects


class Recorder:
    """一个功能的运行记录器。``started`` / ``finished`` 直接接到那个服务的同名信号上。
    ``after``：每落一行之后叫一声（时间轴页开着的话要重画）；它出错不影响任何事。"""

    def __init__(self, journal, job: str, outcome: Outcome, *, after: Callable[[], object] | None = None) -> None:
        self._journal, self._job, self._outcome, self._after = journal, job, outcome, after
        self._run = None

    def started(self, manual: bool = False, *_more) -> None:
        try:
            self._run = self._journal.start(self._job, "manual" if manual else "schedule")
        except Exception:  # noqa: BLE001 - 见模块说明：绝不往外抛
            log.exception("运行记录：%s 开始时没记上", self._job)
            self._run = None

    def finished(self, *args) -> None:
        run, self._run = self._run, None
        try:
            try:
                manual, state, error, effects = self._outcome(*args)
            except Exception as exc:  # noqa: BLE001 - 读不懂结果：照实记一条失败
                manual, state, error, effects = False, "failed", f"{type(exc).__name__}: {exc}", []
            if run is None:                                 # 没发「开始」就结束了（一上来就失败的那种）：现开一条，用时算 0
                run = self._journal.start(self._job, "manual" if manual else "schedule")
            for effect in effects:
                fields = dict(effect)
                run.effect(fields.pop("kind"), **fields)
            run.finish(state, error)
        except Exception:  # noqa: BLE001
            log.exception("运行记录：%s 结束时没记上", self._job)
            return
        if self._after is not None:
            try:
                self._after()
            except Exception:  # noqa: BLE001
                log.info("运行记录：%s 记完之后的通知没发出去", self._job, exc_info=True)
