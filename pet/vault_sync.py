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

每次真的跑了都在运行记录里记一行（任务 ``vault_sync``）。**记录里只有数：文件几个、删除几个、提交号**（``committed`` 是
本地刚建的那个，``pushed_ids`` 是真正到了远端的那几个——rebase 会换提交号），没有文件名
（ADR 0019）。提交说明也只有时间和文件数。

git 经 ``personal_vault`` 跑：Windows 的 git.exe，碰远端时用钥匙串里的 GitHub Token。所以现在只接得了个人侧的克隆；
公司侧的 git 在 WSL 里，是以后的事。阻塞，放后台线程里调。
"""
from __future__ import annotations

import contextlib
import datetime as dt
import fnmatch
import hashlib
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
#: 一次推送最多在运行记录里记这么多个提交号
PUSHED_IDS = 50
_UNMERGED = ("DD", "AU", "UD", "UA", "DU", "AA", "UU")
#: ``.git`` 下面的这些东西在，说明克隆正处在某个操作的半截
_HALFWAY = (("rebase-merge", "in_progress"), ("rebase-apply", "in_progress"), ("MERGE_HEAD", "in_progress"),
            ("CHERRY_PICK_HEAD", "in_progress"), ("REVERT_HEAD", "in_progress"), ("index.lock", "locked"))
_REJECTED = ("rejected", "fetch first", "non-fast-forward")
#: 结果 → 运行记录里的 result；``synced`` / ``noop`` 之外的都在这里
_RESULTS = {"synced": "ok", "noop": "noop", "failed": "failed", "conflict": "needs_you", "blocked": "needs_you", "review": "needs_you"}


CHECK_JOB = "vault_check"
CONFIG_KEY = "vault_sync"
#: 定时同步做到哪一步：``auto`` 自动提交（守卫拦大动作）/ ``ask`` 不替用户提交，只拉取、有改动就等用户 / ``watch`` 只问远端
MODES = ("auto", "ask", "watch")
DEFAULT_INTERVAL_MIN, INTERVAL_RANGE = 60, (15, 720)
DEFAULT_IDLE_MIN, IDLE_RANGE = 5, (0, 120)          # 0 = 停笔后不同步，只靠每隔一阵的那一次
#: 两次检查之间隔了这么久，就当电脑中间睡过（服务每分钟检查一次）
WAKE_GAP_S = 300.0
PROBE_FILES = 500                                   # 找「最近一次改动」时最多看这么多个文件的修改时间


def _clamp(value, default: int, bounds: tuple[int, int]) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return max(bounds[0], min(bounds[1], int(value)))


def normalize(value) -> dict:
    """定时同步的设置。默认关着：它会替用户提交和推送，得由用户自己打开。"""
    raw = value if isinstance(value, dict) else {}
    return {
        "enabled": raw.get("enabled", False) is True,
        "mode": raw.get("mode") if raw.get("mode") in MODES else "auto",
        "interval_minutes": _clamp(raw.get("interval_minutes"), DEFAULT_INTERVAL_MIN, INTERVAL_RANGE),
        "idle_minutes": _clamp(raw.get("idle_minutes"), DEFAULT_IDLE_MIN, IDLE_RANGE),
    }


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
    ``review`` 没提交、等用户（``reason``：``deletions`` / ``many_files`` 是守卫拦的，``ask`` 是「提交前问我」模式）/
    ``failed``（``error`` 是 git 的报错）/ ``missing`` 目录不是克隆 / ``busy`` 上一次还没回来。只问远端的那种运行
    （``check``）是 ``checked`` / ``failed``。"""

    state: str
    reason: str = ""
    files: int = 0
    deletions: int = 0
    committed: str = ""
    pulled: int = 0
    pushed: int = 0
    conflicts: int = 0
    error: str = ""


def _entries(raw: str) -> list[tuple[str, str]]:
    """``git status --porcelain=v1 -z`` 的输出拆成 ``(两位状态码, 路径)``。改名 / 复制那种条目后面跟着一段旧路径，跳过。"""
    entries = []
    parts = raw.split("\0")
    index = 0
    while index < len(parts):
        entry = parts[index]
        index += 1
        if len(entry) < 4:
            continue
        if "R" in entry[:2] or "C" in entry[:2]:
            index += 1
        entries.append((entry[:2], entry[3:]))
    return entries


def read_status(raw: str, noise: tuple[str, ...] = NOISE) -> Changes:
    """``git status --porcelain=v1 -z`` 的输出读成几个数。"""
    files = deletions = content = unmerged = 0
    for code, path in _entries(raw):
        files += 1
        deletions += "D" in code and code not in _UNMERGED
        unmerged += code in _UNMERGED
        content += not any(fnmatch.fnmatchcase(path, pattern) for pattern in noise)
    return Changes(files, deletions, content, unmerged)


# ───────────────────────── 定时：什么时候该跑 ─────────────────────────

@dataclass(frozen=True)
class Probe:
    """工作区此刻的样子：有哪些没提交的改动、其中最近一次改动是什么时候（时间戳；没有改动或看不出来是 ``None``）、
    一个指纹（改动的清单加上那个时间：同一个文件又被改了一次，清单不变，指纹也得变）。"""

    changes: Changes
    newest_edit: float | None
    fingerprint: str


def _stat_time(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def probe(repo_dir: str | Path, *, run: pv.GitRunner = pv.run_git) -> Probe:
    """看一眼工作区（一条本地 ``git status``，再看改动文件的修改时间）。阻塞几十毫秒，放后台线程里调。"""
    folder = Path(repo_dir)
    code, raw = run(folder, ["status", "--porcelain=v1", "-z"])
    if code != 0:
        return Probe(Changes(), None, "")
    newest = None
    for _code, path in _entries(raw)[:PROBE_FILES]:
        target = folder / path
        try:
            stamp = target.stat().st_mtime
        except OSError:                                 # 删掉的文件没有修改时间可看：看它所在的目录（删文件会动目录的修改时间）
            stamp = next((_stat_time(parent) for parent in target.parents if parent.exists()), None)
            if stamp is None:
                continue
        newest = stamp if newest is None else max(newest, stamp)
    return Probe(read_status(raw), newest, hashlib.sha1(f"{raw}\0{newest}".encode("utf-8", "replace")).hexdigest() if raw else "")


def decide(settings: dict, *, now: float, last_run: float | None, last_tick: float | None, started: bool, probe: Probe | None,
           attempted: str) -> str:
    """此刻该不该跑一次定时同步；该跑就返回触发原因（运行记录里的 ``trigger``），不该跑返回空串。纯函数。

    - ``wake``：两次检查之间隔了很久 = 电脑中间睡过。醒来补**一次**，不是每个错过的钟点各补一次；
    - ``startup``：肥鱼启动后的第一次检查，而且上一次运行已经过期（刚跑过又重启的，不再跑）；
    - ``schedule``：距上一次运行（不管是谁发起的）满了一个周期；
    - ``idle``：有正文改动、最后一次改动已经过了「停笔多久」，而且这批改动还没带着跑过（``attempted`` 是上次运行时的指纹：
      撞了冲突、等审核、没连上的那批改动，工作区没再变之前不每分钟重试；每个周期的那一次照常）。``watch`` 模式不提交，
      所以不看改动。只有设备状态变了不算。
    """
    if not settings["enabled"]:
        return ""
    overdue = last_run is None or now - last_run >= settings["interval_minutes"] * 60
    if last_tick is not None and now - last_tick > WAKE_GAP_S:
        return "wake"
    if not started:
        return "startup" if overdue else ""
    if overdue:
        return "schedule"
    idle = settings["idle_minutes"] * 60
    if (idle and settings["mode"] != "watch" and probe is not None and probe.changes.content and probe.newest_edit is not None
            and probe.fingerprint != attempted and now - probe.newest_edit >= idle):
        return "idle"
    return ""


def parse_at(text) -> float | None:
    """运行记录里的 ``at``（``YYYY-MM-DD HH:MM:SS``，本地时间）换成时间戳；读不懂是 ``None``。"""
    try:
        return dt.datetime.strptime(str(text), "%Y-%m-%d %H:%M:%S").timestamp()
    except ValueError:
        return None


def last_run_time(journal) -> float | None:
    """这个克隆上一次被核对或同步是什么时候（不管是定时的还是手点的），从运行记录里取；没有是 ``None``。
    定时服务启动时问一次：刚跑过又重启肥鱼的，不该马上再跑。"""
    for row in journal.read(200):
        if row.get("job") in (JOB, CHECK_JOB):
            return parse_at(row.get("at"))
    return None


def check_once(folder: str | Path, *, repo: str, trigger: str, journal, token: str = "",
               fetch: Callable[..., "tuple[bool, str]"] = pv.fetch, state: Callable[[str], dict] = pv.upstream_state) -> tuple[bool, str]:
    """问一次远端（``git fetch``，不动工作区和本地分支），给了 ``journal`` 就记一行（任务 ``vault_check``）：fetch 前后各问
    一次远端分支指向哪，动了 = ``ok``，没动 = ``noop``，没连上 = ``failed``。返回 ``(连上了?, git 的报错)``。
    页面上的「现在核对」和「只看不动」模式的定时运行都走这里。不拿锁：调用方拿。"""
    record = journal.start(CHECK_JOB, trigger) if journal is not None else None
    before = state(str(folder)) if record else {}
    with record.step("fetch") if record else contextlib.nullcontext():
        ok, reason = fetch(str(folder), token=token)
    if record:
        then = state(str(folder))
        record.effect("git", op="fetch", repo=repo, before=before.get("head", ""), after=then.get("head", ""),
                      behind=then.get("behind"), ahead=then.get("ahead"))
        record.finish("failed" if not ok else "ok" if then.get("head") != before.get("head") else "noop", "" if ok else reason)
    return ok, reason


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

    def run_scheduled(self, repo_dir: str | Path, settings: dict, trigger: str, *, repo: str = "personal") -> Outcome:
        """定时那条路的一次运行，做到哪一步看设置里的模式：``watch`` 只问远端；``ask`` 不替用户提交（有改动就停下等）；
        ``auto`` 自动提交、守卫拦大动作。三种都不带 ``approved``：没人点头。"""
        if settings["mode"] == "watch":
            return self.check(repo_dir, repo=repo, trigger=trigger)
        return self.sync(repo_dir, repo=repo, trigger=trigger, commit=settings["mode"] == "auto")

    def check(self, repo_dir: str | Path, *, repo: str = "personal", trigger: str = "manual") -> Outcome:
        """只问一次远端（见 ``check_once``）。结果是 ``checked`` / ``failed`` / ``missing`` / ``busy``。"""
        folder = Path(repo_dir)
        if not pv.repo_ready(folder):
            return Outcome("missing")
        if not self.lock.acquire(blocking=False):
            return Outcome("busy")
        try:
            ok, reason = check_once(folder, repo=repo, trigger=trigger, journal=self._journal, token=self._token(),
                                    fetch=lambda path, token: pv.fetch(path, run=self._run, token=token),
                                    state=lambda path: pv.upstream_state(path, run=self._run))
            return Outcome("checked") if ok else Outcome("failed", error=reason)
        finally:
            self.lock.release()

    def sync(self, repo_dir: str | Path, *, repo: str = "personal", trigger: str = "manual", approved: bool = False,
             commit: bool = True) -> Outcome:
        """同步一次。``approved``：用户明确点了头，守卫不拦。``commit=False``（「提交前问我」模式）：没点头就一个提交都不建——
        有改动时只问一次远端就停下，结果是 ``review``（原因 ``ask``）；工作区干净时照常拉取、推送。
        目录不是克隆、上一次还没回来，都不算跑过，不记。"""
        folder = Path(repo_dir)
        if not pv.repo_ready(folder):
            return Outcome("missing")
        if not self.lock.acquire(blocking=False):
            return Outcome("busy")
        try:
            record = self._journal.start(JOB, trigger) if self._journal is not None else _NoRecord()
            effect = {"before": "", "after": "", "files": 0, "deletions": 0, "committed": [], "pulled": 0, "pushed": 0}
            try:
                out = self._sync(folder, record, effect, approved, commit)
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

    def _sync(self, folder: Path, record, effect: dict, approved: bool, may_commit: bool) -> Outcome:
        counts = {"files": 0, "deletions": 0}

        def done(state: str, **fields) -> Outcome:
            effect.update(after=pv.upstream_state(folder, run=self._run)["head"] if effect["before"] else "", **counts,
                          **{key: fields[key] for key in ("conflicts",) if key in fields},
                          **({state: fields["reason"]} if state in ("blocked", "review") else {}))
            return Outcome(state, committed=effect["committed"][-1] if effect["committed"] else "", pulled=effect["pulled"],
                           pushed=effect["pushed"], **counts, **fields)

        def commit(changes: Changes) -> Outcome | None:
            """把工作区里的全部改动提交成一个提交。守卫拦下或 git 不干，返回那个结果；提交成了返回 ``None``。"""
            if not approved and not may_commit:             # 「提交前问我」：不提交。先问一次远端，磁贴上的差距才是此刻的
                counts.update(files=changes.files, deletions=changes.deletions)
                with record.step("fetch"):
                    self._remote(folder, "fetch", "-q")
                return done("review", reason="ask")
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
            # 推上去的是哪几个提交（rebase 之后的提交号：远端的历史里看到的就是这些）。时间轴页靠它认出「这是肥鱼推的」
            outgoing = [line[:12] for line in self._git(folder, "rev-list", f"-n{PUSHED_IDS}", "@{upstream}..HEAD")[1].split()]
            with record.step("push"):
                code, out = self._remote(folder, "push", "-q")
            if code == 0:
                effect["pushed"] = ahead
                effect["pushed_ids"] = outgoing
                break
            if attempt + 1 < MAX_ROUNDS and any(mark in out.lower() for mark in _REJECTED):
                continue                                    # 输给了别人：远端又多了提交，再拉一轮
            return done("failed", error=out.strip()[-300:])
        return done("synced" if effect["committed"] or effect["pulled"] or effect["pushed"] else "noop")
