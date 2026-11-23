# -*- coding: utf-8 -*-
"""时间轴页（``/report/activity``）：什么时候跑了什么、对知识库的仓库做了什么，按时间倒序排成一条瀑布流。

配置全景是某一刻的截面；这一页是时间轴。它有两个来源（ADR 0019），在这里按**提交号**对上：

- **运行记录**（``run_journal``）：肥鱼自己跑的每一件事——哪个任务、被什么触发、每步多久、结果；
- **git**：个人知识库克隆里「远端分支」的提交（``git log @{upstream}``，一条本地命令，不联网）。

一次同步在运行记录里写下它推上去的提交号（``pushed_ids``）。对得上的提交挂在那次运行下面；对不上的是别处写的
（云端的会话、别的机器、肥鱼里还没接入运行记录的功能），单独成行。**远端的提交只和上一次核对时一样新**，页面顶上写明是哪一刻。

三种行（``timeline``）：

- ``run``：一次有事可说的运行（办成了、没办成、等用户）；能展开看每步耗时和它推上去的提交；
- ``quiet``：同一个任务连着几次「跑了、没事可做」折成一行——每小时一次的核对不该把真正的变化淹掉；
  折叠不跨天（``outside`` 也是）：一行说的是哪一天的事，看日期小标题就知道；
- ``outside``：别处写的提交，同一个作者连着的几个折成一行，能展开。

页面上方是每个任务此刻的状态（``job_status``）：上次什么时候、结果、最近几次的色块条。

用的是报告页那张外壳：这里把整页内容渲染成 HTML 交出去（``html`` 字段），页面脚本不用认识它。**提交说明、作者名、
报错都是外面来的字，一律转义。** 提交说明只在这一页现读现画，不进运行记录、不落离线快照（报告页本来就不落）。

provider 要起 git，所以标了 ``off_gui``：服务在请求线程上调它，它只回一次界面线程（读克隆目录和主题偏好）。
"""
from __future__ import annotations

import datetime as dt
import html
import re
from pathlib import Path
from typing import Callable

from .. import personal_vault as pv
from ..i18n import t
from . import probes

REPORT = "activity"
RUNS = 300          # 最多看最近这么多条运行记录
COMMITS = 200       # 最多看远端分支上最近这么多个提交
STRIP = 12          # 每个任务的色块条留最近几次
GIT_TIMEOUT_S = 20.0
_RECORD, _FIELD = "\x1e", "\x1f"
_FILES = re.compile(r"(\d+) files? changed")


def _git_effect(run: dict) -> dict:
    return next((e for e in run.get("effects") or [] if isinstance(e, dict) and e.get("kind") == "git"), {})


# ───────────────────────── 读 git ─────────────────────────

def read_commits(repo_dir: str | Path, *, run: pv.GitRunner = pv.run_git, limit: int = COMMITS) -> list[dict]:
    """远端分支上最近的提交，新的在前：``{id（前 12 位）, at（本地时间）, author, subject, files}``。问不出来是空列表。

    ``at`` 用提交时间而不是写作时间：rebase 过的提交，落到远端的那一刻才是它在时间轴上的位置。"""
    code, out = run(repo_dir, ["log", "@{upstream}", f"-n{limit}", "--shortstat", "--date=format-local:%Y-%m-%d %H:%M:%S",
                               f"--format={_RECORD}%H{_FIELD}%cd{_FIELD}%an{_FIELD}%s"], timeout=GIT_TIMEOUT_S)
    if code != 0:
        return []
    commits = []
    for record in out.split(_RECORD)[1:]:
        head, _, rest = record.partition("\n")
        fields = head.split(_FIELD)
        if len(fields) != 4:
            continue
        files = _FILES.search(rest)
        commits.append({"id": fields[0][:12], "at": fields[1], "author": fields[2], "subject": fields[3], "files": int(files.group(1)) if files else 0})
    return commits


# ───────────────────────── 合并成一条时间轴 ─────────────────────────

def timeline(runs: list[dict], commits: list[dict]) -> list[dict]:
    """运行记录和提交排成一条，新的在前。``runs`` / ``commits`` 都是新的在前。纯函数。"""
    by_id = {commit["id"]: commit for commit in commits}
    pushed_by_fish: set[str] = set()
    items = []
    for run in runs:
        ids = [str(sha) for sha in _git_effect(run).get("pushed_ids") or []]
        pushed_by_fish.update(ids)
        items.append((str(run.get("at") or ""), 0, {"kind": "run", "at": str(run.get("at") or ""), "run": run,
                                                     "commits": [by_id[sha] for sha in ids if sha in by_id]}))
    for commit in commits:
        if commit["id"] not in pushed_by_fish:
            items.append((commit["at"], 1, {"kind": "outside", "at": commit["at"], "since": commit["at"], "author": commit["author"],
                                            "commits": [commit]}))
    items.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    rows: list[dict] = []
    for _at, _order, row in items:
        last = rows[-1] if rows else None
        if row["kind"] == "outside":
            if last and last["kind"] == "outside" and last["author"] == row["author"] and last["since"][:10] == row["at"][:10]:
                last["commits"].extend(row["commits"])
                last["since"] = row["at"]
            else:
                rows.append(row)
            continue
        run = row["run"]
        if run.get("result") == "noop":
            if last and last["kind"] == "quiet" and last["job"] == run.get("job") and last["since"][:10] == row["at"][:10]:
                last["count"] += 1
                last["since"] = row["at"]
            else:
                rows.append({"kind": "quiet", "at": row["at"], "since": row["at"], "job": run.get("job"), "trigger": run.get("trigger"), "count": 1})
            continue
        rows.append(row)
    return rows


def job_status(runs: list[dict]) -> list[dict]:
    """每个任务此刻的状态，最近跑过的在前：``{job, at, result, runs（一共几次）, strip（最近几次的结果，最新的在右）}``。"""
    jobs: dict[str, dict] = {}
    for run in runs:                                    # 新的在前：第一次见到的就是最近一次
        job = str(run.get("job") or "")
        entry = jobs.setdefault(job, {"job": job, "at": str(run.get("at") or ""), "result": str(run.get("result") or ""), "runs": 0, "strip": []})
        entry["runs"] += 1
        if len(entry["strip"]) < STRIP:
            entry["strip"].insert(0, str(run.get("result") or ""))
    return list(jobs.values())


# ───────────────────────── 说成人话 ─────────────────────────

def _name(prefix: str, key: str) -> str:
    """``activity.<前缀>.<键>`` 的字；字表里没有（还没起名字的任务）就原样显示那个键。"""
    full = f"activity.{prefix}.{key}"
    text = t(full)
    return key if text == full else text


def _what(run: dict) -> str:
    """一次运行做了什么，一句话。"""
    effect, result = _git_effect(run), run.get("result")
    if effect.get("conflicts"):
        return t("activity.did.conflict", n=effect["conflicts"])
    if effect.get("blocked"):
        return t("activity.did.blocked")
    if effect.get("review"):
        return t("activity.did.review", n=effect.get("files", 0), d=effect.get("deletions", 0))
    if result == "failed":
        return t("activity.did.failed")
    if effect.get("op") == "fetch":
        return t("activity.did.checked", behind=effect.get("behind", 0) or 0, ahead=effect.get("ahead", 0) or 0)
    if effect.get("op") == "sync":
        text = t("activity.did.synced", pulled=effect.get("pulled", 0), pushed=effect.get("pushed", 0))
        return text + (" · " + t("activity.did.committed", n=effect["files"]) if effect.get("files") else "")
    return _name("result", str(result or ""))


def _commit_list(commits: list[dict]) -> str:
    rows = "".join(f'<li><span class="wt">{html.escape(c["at"][11:16])}</span><code>{html.escape(c["id"][:7])}</code>'
                   f'<span class="ws">{html.escape(c["subject"])}</span><span class="wn">{html.escape(t("activity.files", n=c["files"]))}</span></li>'
                   for c in commits)
    return f'<ul class="wcommits">{rows}</ul>'


def _steps(run: dict) -> str:
    steps = [step for step in run.get("steps") or [] if isinstance(step, dict)]
    if not steps:
        return ""
    bars = "".join(f'<span style="flex:{max(float(step.get("seconds") or 0), 0.05):.2f}">{html.escape(str(step.get("name", "")))} '
                   f'{float(step.get("seconds") or 0):.1f}</span>' for step in steps)
    return f'<div class="wsteps">{bars}</div>'


def _row(row: dict) -> str:
    time = html.escape(row["at"][11:16])
    if row["kind"] == "quiet":
        span = time if row["count"] == 1 else f'{html.escape(row["since"][11:16])}–{time}'
        return (f'<div class="wrow quiet"><span class="wt">{span}</span><span class="who fish">{html.escape(_name("trigger", str(row["trigger"])))}</span>'
                f'<span class="wm">{html.escape(_name("job", str(row["job"])))} · {html.escape(t("activity.quiet", n=row["count"]))}</span></div>')
    if row["kind"] == "outside":
        count = len(row["commits"])
        files = sum(c["files"] for c in row["commits"])
        return (f'<details class="wrow outside"><summary><span class="wt">{time}</span><span class="who other">{html.escape(row["author"])}</span>'
                f'<span class="wm">{html.escape(t("activity.outside", n=count))}</span>'
                f'<span class="we">{html.escape(t("activity.files", n=files))}</span></summary>{_commit_list(row["commits"])}</details>')
    run = row["run"]
    result = str(run.get("result") or "")
    head = (f'<span class="wt">{time}</span><span class="who fish">{html.escape(_name("trigger", str(run.get("trigger"))))}</span>'
            f'<span class="wm">{html.escape(_name("job", str(run.get("job"))))} · <span class="r-{html.escape(result)}">{html.escape(_what(run))}</span></span>'
            f'<span class="we">{html.escape(t("activity.seconds", n=run.get("seconds", 0)))}</span>')
    error = f'<p class="werr">{html.escape(str(run["error"]))}</p>' if run.get("error") else ""
    body = _steps(run) + (_commit_list(row["commits"]) if row["commits"] else "") + error
    if not body:
        return f'<div class="wrow run">{head}</div>'
    return f'<details class="wrow run"><summary>{head}</summary>{body}</details>'


def render(rows: list[dict], jobs: list[dict]) -> str:
    """整页内容的 HTML：上面每个任务一行状态，下面按天分组的瀑布流。没有东西可画返回空串。"""
    if not rows and not jobs:
        return ""
    parts = []
    if jobs:
        def strip(job: dict) -> str:
            return "".join(f'<i class="s-{html.escape(result)}" title="{html.escape(_name("result", result))}"></i>' for result in job["strip"])

        lines = "".join(
            f'<div class="wjob"><span class="wm">{html.escape(_name("job", job["job"]))}</span>'
            f'<span class="r-{html.escape(job["result"])}">{html.escape(_name("result", job["result"]))}</span>'
            f'<span class="wt">{html.escape(job["at"][5:16])}</span><span class="wstrip">{strip(job)}</span>'
            f'<span class="we">{html.escape(t("activity.runs", n=job["runs"]))}</span></div>' for job in jobs)
        parts.append(f'<section class="wjobs"><h3>{html.escape(t("activity.jobs_title"))}</h3>{lines}</section>')
    day = ""
    for row in rows:
        if row["at"][:10] != day:
            day = row["at"][:10]
            parts.append(f'<h3 class="wday">{html.escape(day)}</h3>')
        parts.append(_row(row))
    return f'<div class="waterfall">{"".join(parts)}</div>'


# ───────────────────────── provider ─────────────────────────

def provider(journal, context: Callable[[], dict], on_gui: Callable[[Callable[[], object]], object], *,
             run: pv.GitRunner = pv.run_git) -> Callable[[], dict]:
    """时间轴页的 provider。``context()`` 在界面线程上跑（经 ``on_gui``），给 ``{repo_dir, theme}``；其余都在调用它的那条线程上
    （请求线程）：读运行记录、起一次 ``git log``。读不到 git（目录不是克隆）就只画运行记录。"""
    def build() -> dict:
        ctx = on_gui(context)
        repo_dir = str(ctx.get("repo_dir") or "")
        runs = journal.read(RUNS)
        commits = read_commits(repo_dir, run=run) if repo_dir and pv.repo_ready(repo_dir) else []
        rows = timeline(runs, commits)
        outside = sum(len(row["commits"]) for row in rows if row["kind"] == "outside")
        checked = ""
        if commits:
            code, branch = run(repo_dir, ["rev-parse", "--abbrev-ref", "HEAD"], timeout=GIT_TIMEOUT_S)
            stamp, _failed = probes.remote_contact(Path(repo_dir), branch.strip() if code == 0 else "")
            checked = dt.datetime.fromtimestamp(stamp).strftime("%Y-%m-%d %H:%M") if stamp else ""
        return {
            "id": REPORT, "title": t("activity.title"), "theme": ctx.get("theme") or "dark", "available": True,
            "summary": t("activity.summary", runs=len(runs), outside=outside) if rows else "",
            "generated": t("activity.as_of", when=checked) if checked else "", "usage": [],
            "html": render(rows, job_status(runs)), "sections": [], "busy": False, "busy_text": "", "empty_text": t("activity.empty"),
            "error": "", "action": None, "actions": [], "composer": None, "details": [], "settings_focus": "",
        }

    build.off_gui = True
    return build
