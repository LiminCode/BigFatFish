# -*- coding: utf-8 -*-
"""知识库同步器：把一个本地克隆和它的远端对齐一次——提交本地改动、拉取远端的新提交、推送。零 Qt。

知识库是「家」（路线图 P3），所以这里守四条线：

1. **不在半截状态上动手**（预检）：克隆正在 rebase / merge、索引被锁、有没解决的冲突、当前分支没有上游——都停下来报，
   什么都不做。
2. **不自动选边**：本地提交 rebase 到远端上有冲突，就 ``rebase --abort``。本地提交留着、工作区还是用户的版本、远端一个字
   没动；结果是 ``conflict``，等用户自己处理。永远不用 ``-X ours`` / ``-X theirs``。
3. **没人点头时不提交大动作**（守卫）：有删除、或者一次改了超过 ``REVIEW_ABOVE_FILES`` 个文件，而调用方没带 ``approved``——
   结果是 ``review``，不提交。用户在页面上点「现在同步」并确认，就是点头。
4. **一次只跑一个**：一把锁。「现在核对」和它共用这把锁（``VaultSync.lock``）。

一次同步的顺序：预检 → 看工作区 → 有正文改动就先提交（本地操作，断网也做得成：停笔的内容先存下来）→ fetch →
落后就 rebase → 领先就推送。推送输给了别人（远端在这一瞬间又多了提交）就再来一轮，最多 ``MAX_ROUNDS`` 轮。

**设备状态不单独触发**：只有 ``NOISE`` 里的路径（Obsidian 的界面状态）变了，不提交；有正文改动时随车一起提交；
远端有新提交要 rebase 时也提交掉，好让 rebase 从干净的工作区开始。

每次真的跑了都在运行记录里记一行（任务 ``vault_sync``）。**记录里只有数：文件几个、删除几个、提交号**，没有文件名
（ADR 0019）。提交说明也只有时间和文件数。

git 经 ``personal_vault`` 跑：Windows 的 git.exe，碰远端时用钥匙串里的 GitHub Token。所以现在只接得了个人侧的克隆；
公司侧的 git 在 WSL 里，是以后的事。阻塞，放后台线程里调。
"""
from __future__ import annotations

import contextlib
import datetime as dt
import fnmatch
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import personal_vault as pv

JOB = "vault_sync"
#: 设备状态：这些路径的改动不单独触发同步（fnmatch，``*`` 可以跨目录）
NOISE = (".obsidian/*",)
#: 没人点头时，一次改动超过这么多个文件就不自动提交
REVIEW_ABOVE_FILES = 20
MAX_ROUNDS = 2
_UNMERGED = ("DD", "AU", "UD", "UA", "DU", "AA", "UU")
#: ``.git`` 下面的这些东西在，说明克隆正处在某个操作的半截
_HALFWAY = (("rebase-merge", "in_progress"), ("rebase-apply", "in_progress"), ("MERGE_HEAD", "in_progress"),
            ("CHERRY_PICK_HEAD", "in_progress"), ("REVERT_HEAD", "in_progress"), ("index.lock", "locked"))
_REJECTED = ("rejected", "fetch first", "non-fast-forward")
#: 结果 → 运行记录里的 result；``synced`` / ``noop`` 之外的都在这里
_RESULTS = {"synced": "ok", "noop": "noop", "failed": "failed", "conflict": "needs_you", "blocked": "needs_you", "review": "needs_you"}


@dataclass(frozen=True)
class Changes:
    """工作区里没提交的东西：一共几个文件、其中删除几个、不算设备状态的几个、没解决的冲突几个。"""

    files: int = 0
    deletions: int = 0
    content: int = 0
    unmerged: int = 0


@dataclass(frozen=True)
class Outcome:
    """一次同步的结果。``state``：``synced`` 有东西动了 / ``noop`` 没事可做 / ``conflict`` 有冲突、已撤回 /
    ``blocked`` 预检没过（``reason``：``in_progress`` / ``locked`` / ``unmerged`` / ``no_upstream``）/
    ``review`` 守卫拦下（``reason``：``deletions`` / ``many_files``）/ ``failed``（``error`` 是 git 的报错）/
    ``missing`` 目录不是克隆 / ``busy`` 上一次还没回来。"""

    state: str
    reason: str = ""
    files: int = 0
    deletions: int = 0
    committed: str = ""
    pulled: int = 0
    pushed: int = 0
    conflicts: int = 0
    error: str = ""


def read_status(raw: str, noise: tuple[str, ...] = NOISE) -> Changes:
    """``git status --porcelain=v1 -z`` 的输出读成几个数。改名 / 复制那种条目后面跟着一段旧路径，跳过。"""
    files = deletions = content = unmerged = 0
    parts = raw.split("\0")
    index = 0
    while index < len(parts):
        entry = parts[index]
        index += 1
        if len(entry) < 4:
            continue
        code, path = entry[:2], entry[3:]
        if "R" in code or "C" in code:
            index += 1
        files += 1
        deletions += "D" in code and code not in _UNMERGED
        unmerged += code in _UNMERGED
        content += not any(fnmatch.fnmatchcase(path, pattern) for pattern in noise)
    return Changes(files, deletions, content, unmerged)


class _NoRecord:
    """没给运行记录时的替身：什么都不记。"""

    def step(self, _name: str):
        return contextlib.nullcontext()

    def effect(self, _kind: str, **_fields) -> None:
        pass

    def finish(self, _result: str, _error: str = "") -> bool:
        return False


class VaultSync:
    """``journal``：``run_journal.Journal``（不给就不记）；``token``：碰远端时用的 GitHub Token；``run``：git 的执行器。
    整个进程建一个：锁在它身上。"""

    def __init__(self, *, journal=None, token: Callable[[], str] = pv.github_token, run: pv.GitRunner = pv.run_git,
                 now: Callable[[], dt.datetime] = dt.datetime.now) -> None:
        self._journal, self._token, self._run, self._now = journal, token, run, now
        self.lock = threading.Lock()

    def sync(self, repo_dir: str | Path, *, repo: str = "personal", trigger: str = "manual", approved: bool = False) -> Outcome:
        """同步一次。``approved``：用户明确点了头，守卫不拦。目录不是克隆、上一次还没回来，都不算跑过，不记。"""
        folder = Path(repo_dir)
        if not pv.repo_ready(folder):
            return Outcome("missing")
        if not self.lock.acquire(blocking=False):
            return Outcome("busy")
        try:
            record = self._journal.start(JOB, trigger) if self._journal is not None else _NoRecord()
            effect = {"before": "", "after": "", "files": 0, "deletions": 0, "committed": [], "pulled": 0, "pushed": 0}
            try:
                out = self._sync(folder, record, effect, approved)
            except Exception as exc:  # noqa: BLE001 - 线程不许带病退出；记成失败
                out = Outcome("failed", error=f"{type(exc).__name__}: {exc}")
            record.effect("git", op="sync", repo=repo, **effect)
            record.finish(_RESULTS[out.state], out.error)
            return out
        finally:
            self.lock.release()

    # ------------------------------------------------------------------ 一次同步

    def _git(self, folder: Path, *args: str) -> tuple[int, str]:
        return self._run(folder, list(args))

    def _remote(self, folder: Path, *args: str) -> tuple[int, str]:
        return pv._remote(folder, list(args), run=self._run, token=self._token())

    def _halfway(self, folder: Path) -> str:
        git_dir = folder / ".git"
        return next((reason for name, reason in _HALFWAY if (git_dir / name).exists()), "")

    def _sync(self, folder: Path, record, effect: dict, approved: bool) -> Outcome:
        counts = {"files": 0, "deletions": 0}

        def done(state: str, **fields) -> Outcome:
            effect.update(after=pv.upstream_state(folder, run=self._run)["head"] if effect["before"] else "", **counts,
                          **{key: fields[key] for key in ("conflicts",) if key in fields},
                          **({state: fields["reason"]} if state in ("blocked", "review") else {}))
            return Outcome(state, committed=effect["committed"][-1] if effect["committed"] else "", pulled=effect["pulled"],
                           pushed=effect["pushed"], **counts, **fields)

        def commit(changes: Changes) -> Outcome | None:
            """把工作区里的全部改动提交成一个提交。守卫拦下或 git 不干，返回那个结果；提交成了返回 ``None``。"""
            if not approved and (changes.deletions or changes.files > REVIEW_ABOVE_FILES):
                counts.update(files=changes.files, deletions=changes.deletions)
                return done("review", reason="deletions" if changes.deletions else "many_files")
            with record.step("commit"):
                code, out = self._git(folder, "add", "-A")
                if code == 0:
                    code, out = self._git(folder, "commit", "-q", "-m", f"vault: {self._now():%Y-%m-%d %H:%M} · {changes.files} files")
            if code != 0:
                return done("failed", error=out.strip()[-300:])
            counts.update(files=changes.files, deletions=changes.deletions)
            effect["committed"].append(self._git(folder, "rev-parse", "HEAD")[1].strip()[:12])
            return None

        halfway = self._halfway(folder)
        if halfway:
            return done("blocked", reason=halfway)
        effect["before"] = pv.upstream_state(folder, run=self._run)["head"]
        if not effect["before"]:
            return done("blocked", reason="no_upstream")
        code, raw = self._git(folder, "status", "--porcelain=v1", "-z")
        if code != 0:
            return done("failed", error=raw.strip()[-300:])
        changes = read_status(raw)
        if changes.unmerged:
            return done("blocked", reason="unmerged")
        dirty = changes.files > 0
        if changes.content:                                 # 有正文改动：先存成本地提交（断网也做得成），设备状态随车
            stopped = commit(changes)
            if stopped:
                return stopped
            dirty = False
        for attempt in range(MAX_ROUNDS):
            with record.step("fetch"):
                code, out = self._remote(folder, "fetch", "-q")
            if code != 0:
                return done("failed", error=out.strip()[-300:])
            state = pv.upstream_state(folder, run=self._run)
            behind, ahead = state["behind"] or 0, state["ahead"] or 0
            if behind:
                if dirty:                                   # 只有设备状态变了，但要 rebase：提交掉，让 rebase 从干净的工作区开始
                    stopped = commit(changes)
                    if stopped:
                        return stopped
                    dirty = False
                with record.step("rebase"):
                    code, out = self._git(folder, "rebase", "-q", "@{upstream}")
                if code != 0:
                    conflicts = [line for line in self._git(folder, "diff", "--name-only", "--diff-filter=U")[1].splitlines() if line.strip()]
                    self._git(folder, "rebase", "--abort")
                    if conflicts:
                        return done("conflict", conflicts=len(conflicts))
                    return done("failed", error=out.strip()[-300:])
                effect["pulled"] += behind
                ahead = pv.upstream_state(folder, run=self._run)["ahead"] or 0
            if not ahead:
                break
            with record.step("push"):
                code, out = self._remote(folder, "push", "-q")
            if code == 0:
                effect["pushed"] = ahead
                break
            if attempt + 1 < MAX_ROUNDS and any(mark in out.lower() for mark in _REJECTED):
                continue                                    # 输给了别人：远端又多了提交，再拉一轮
            return done("failed", error=out.strip()[-300:])
        return done("synced" if effect["committed"] or effect["pulled"] or effect["pushed"] else "noop")
