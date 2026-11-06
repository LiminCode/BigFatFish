# -*- coding: utf-8 -*-
"""今日用量：今天所有 Claude Code 对话用掉的 token（纯逻辑 + 文件读取，零 Qt）。

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
（``claude_usage_monitor``）。

**两个账号分开算**（2026-11-02）：Windows 本机的 ``~/.claude/projects`` 是一个账号；WSL
发行版里跑的 Claude Code（另一个账号）有自己的家目录，Windows 侧经
``\\\\wsl.localhost\\<发行版>\\home\\<用户>\\.claude\\projects`` 读。``UsageAccounts`` 给每个账号
一只 ``UsageMeter``（一只表可以跨好几个根：几个发行版 / 几个用户合成一个「WSL」账号），各出
一份 ``UsageTotals``；岛上的文案由 ``headline`` / ``detail`` 拼。WSL 那边读不到时要能容错：
没装 WSL → 只有一个账号、文案照旧；装了但读不到（发行版没在运行、共享刚起来还没就绪）→
「WSL --」、下一分钟再试；今天已经读到的数不因为中途读不到而丢。

访问 ``\\\\wsl.localhost`` 会把没在运行的发行版拉起来，所以先问一次
``wsl.exe --list --running``（约 50–150 ms，一个无窗口子进程），只碰在运行的。实测
（2026-11-02，WSL 侧 1009 个项目目录、今天 115 MB）：枚举一遍 1.1 s、首读 1.2 s，之后每分钟
只读追加的部分。目录枚举用 ``os.scandir`` 一次拿到 mtime（Windows 上目录项自带、不另 stat——
UNC 上每次 stat 都是一次往返）；子代理目录只看今天动过的那些会话下面的
（``<项目>/<会话>/subagents/``），不再全盘 ``glob``（那一遍在 UNC 上要 2 s）。
"""

from __future__ import annotations

from .i18n import t

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

_USAGE_MARK = b'"usage"'
#: usage 里的字段 → 本模块的名字
_FIELDS = (("input", "input_tokens"), ("output", "output_tokens"),
           ("cache_write", "cache_creation_input_tokens"), ("cache_read", "cache_read_input_tokens"))
#: 两个账号的键（也是 i18n ``usage.account.<键>`` 的后缀）
LOCAL_ACCOUNT = "windows"
WSL_ACCOUNT = "wsl"
_JOINER = " · "


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
        return t("usage.headline", tokens=format_tokens(self.tokens))

    @property
    def detail(self) -> str:
        return t("usage.detail", total=format_tokens(self.tokens), output=format_tokens(self.output),
                 input=format_tokens(self.input), cache_write=format_tokens(self.cache_write),
                 cache_read=format_tokens(self.cache_read))


def local_midnight(now: float) -> float:
    """``now`` 所在那一天的零点（本机时区）。"""
    return datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def _number(value) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------- 找文件

def _fresh(entry: os.DirEntry, since: float) -> bool:
    try:
        return entry.is_file() and entry.stat().st_mtime >= since
    except OSError:
        return False


def _subagent_files(folder: Path, since: float) -> list[Path]:
    try:
        with os.scandir(folder) as entries:
            return [Path(entry.path) for entry in entries if entry.name.endswith(".jsonl") and _fresh(entry, since)]
    except OSError:
        return []


def transcript_files(roots: Iterable[Path], since: float) -> tuple[list[Path], bool]:
    """各根下 ``since`` 之后动过的会话记录：主对话 jsonl 和它们的 ``subagents/*.jsonl``。

    返回 ``(文件, 至少一个根能枚举)``——后者让调用方分得清「没有新内容」和「根本读不到」。
    一层 ``os.scandir`` 顺手拿到 mtime，不另 stat（UNC 上每次 stat 都是一次往返）。
    """
    found: list[Path] = []
    reachable = False
    for root in roots:
        try:
            with os.scandir(root) as entries:
                projects = [entry.path for entry in entries if entry.is_dir()]
        except OSError:
            continue
        reachable = True
        for project in projects:
            try:
                with os.scandir(project) as entries:
                    sessions = [entry for entry in entries if entry.name.endswith(".jsonl") and _fresh(entry, since)]
            except OSError:
                continue
            for entry in sessions:
                found.append(Path(entry.path))
                found.extend(_subagent_files(Path(project) / entry.name[:-len(".jsonl")] / "subagents", since))
    return found, reachable


# ---------------------------------------------------------------- 一只表

class UsageMeter:
    """今天的用量（增量统计，见模块说明）。不是线程安全的：同一时刻只让一个线程调。

    ``roots``：要统计的 ``projects`` 目录（可以好几个）；不给就是本机 ``home/.claude/projects``。
    ``reachable``：上一次 ``refresh`` 时至少有一个根能枚举。
    """

    def __init__(self, home: Path | None = None, *, roots: Iterable[Path] | None = None,
                 clock: Callable[[], float] = time.time,
                 day_start: Callable[[float], float] = local_midnight) -> None:
        self.roots = [Path(root) for root in roots] if roots is not None else [
            (home or Path.home()) / ".claude" / "projects"]
        self._clock = clock
        self._day_start = day_start
        self._day: float | None = None
        self._messages: dict[tuple, tuple[int, int, int, int]] = {}
        self._files: dict[str, tuple[int, bytes]] = {}     # 路径 → (读到哪了, 没写完的那半行)
        self.bytes_read = 0
        self.reachable = False

    def refresh(self) -> UsageTotals:
        """读入新追加的记录，返回今天到现在的合计。"""
        day = self._day_start(self._clock())
        if day != self._day:                               # 过了零点：从头算
            self._day = day
            self._messages.clear()
            self._files.clear()
        files, self.reachable = transcript_files(self.roots, day)
        for path in files:
            self._read_new(path, day)
        sums = [sum(values[index] for values in self._messages.values()) for index in range(4)]
        return UsageTotals(*sums, messages=len(self._messages))

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


# ---------------------------------------------------------------- WSL 那边的根

def wsl_share(distro: str) -> Path:
    """发行版的根在 Windows 侧的共享路径（``\\\\wsl.localhost\\<发行版>``）。"""
    return Path("\\\\wsl.localhost\\" + distro)


def running_distros(*, runner: Callable | None = None) -> list[str]:
    """正在运行的 WSL 发行版名（``wsl.exe --list --running --quiet``）；没装 WSL / 失败 / 都没在跑 → 空。"""
    if runner is None:
        from .claude_hooks import run_wsl

        runner = run_wsl
    try:
        code, out = runner(["--list", "--running", "--quiet"], timeout=10)
    except Exception:  # noqa: BLE001 - 只是这一分钟不读 WSL
        return []
    if code != 0:
        return []
    names = (line.replace("\x00", "").strip() for line in str(out).splitlines())   # 偶见 UTF-16 残渣
    return [name for name in names if name]


def wsl_projects_roots(*, distros: list[str] | None = None, running: list[str] | None = None,
                       share: Callable[[str], Path] = wsl_share) -> list[Path] | None:
    """在运行的每个 WSL 发行版里、每个用户的 ``~/.claude/projects``（Windows 侧路径）。

    ``None`` = 这台机器没有 WSL 发行版（就一个账号）；``[]`` = 有发行版但现在读不到（没在运行、
    共享还没就绪、里面没装过 Claude Code）。没在运行的发行版不去碰：碰一下共享就会把它拉起来。
    阻塞：一次 wsl.exe + 每个在运行的发行版几次目录往返；调用方放后台线程。
    """
    if distros is None:
        from .vscode_workspaces import wsl_distros

        distros = wsl_distros()
    if not distros:
        return None
    live = {name.lower() for name in (running_distros() if running is None else running)}
    roots: list[Path] = []
    for distro in distros:
        if distro.lower() not in live:
            continue
        try:
            with os.scandir(share(distro) / "home") as entries:
                users = sorted(entry.path for entry in entries if entry.is_dir())
        except OSError:
            continue
        for user in users:
            projects = Path(user) / ".claude" / "projects"
            try:
                if projects.is_dir():
                    roots.append(projects)
            except OSError:
                continue
    return roots


# ---------------------------------------------------------------- 两个账号

@dataclass(frozen=True)
class AccountUsage:
    """一个账号今天的用量；``totals`` 为 None = 这次读不到、今天也还没读到过。"""

    key: str
    totals: UsageTotals | None = None

    @property
    def label(self) -> str:
        return account_label(self.key)


def account_label(key: str) -> str:
    """账号在界面上的短名（Win / WSL）。"""
    return t(f"usage.account.{key}")


def _tokens_text(account: AccountUsage) -> str:
    return format_tokens(account.totals.tokens) if account.totals is not None else t("usage.none")


def headline(accounts: list[AccountUsage]) -> str:
    """信息槽文案：一个账号「2.38M」；两个「Win 2.38M · WSL 1.10M」（不再写「今日」，悬停说明里有）。"""
    if len(accounts) == 1 and accounts[0].totals is not None:
        return accounts[0].totals.headline
    items = _JOINER.join(t("usage.account_item", label=a.label, tokens=_tokens_text(a)) for a in accounts)
    return t("usage.headline.multi", accounts=items)


def headline_segments(accounts: list[AccountUsage]) -> list[tuple[str, str, str]]:
    """信息槽按账号画记号用的分段：[(账号键, 短名, 数字)]；一个账号时为空（那就是一个数，没有图标可配）。"""
    if len(accounts) == 1:
        return []
    return [(a.key, a.label, _tokens_text(a)) for a in accounts]


def detail(accounts: list[AccountUsage]) -> str:
    """悬停说明：一个账号一行。"""
    if len(accounts) == 1 and accounts[0].totals is not None:
        return accounts[0].totals.detail
    return "\n".join(_account_detail(a) for a in accounts)


def _account_detail(account: AccountUsage) -> str:
    totals = account.totals
    if totals is None:
        return t("usage.detail.unavailable", label=account.label)
    return t("usage.detail.account", label=account.label, total=format_tokens(totals.tokens),
             output=format_tokens(totals.output), input=format_tokens(totals.input),
             cache_write=format_tokens(totals.cache_write), cache_read=format_tokens(totals.cache_read))


class UsageAccounts:
    """两个账号各一只表：本机 ``home/.claude/projects`` 与 WSL 发行版里的（``wsl_roots`` 每次刷新问一遍）。

    不是线程安全的：同一时刻只让一个线程调（``claude_usage_monitor`` 保证在途只有一次）。
    """

    def __init__(self, home: Path | None = None, *, wsl_roots: Callable[[], list[Path] | None] | None = None,
                 clock: Callable[[], float] = time.time,
                 day_start: Callable[[float], float] = local_midnight) -> None:
        self._local = UsageMeter(home, clock=clock, day_start=day_start)
        self._wsl = UsageMeter(roots=[], clock=clock, day_start=day_start)
        self._wsl_roots = wsl_roots or wsl_projects_roots

    def refresh(self) -> list[AccountUsage]:
        accounts = [AccountUsage(LOCAL_ACCOUNT, self._local.refresh())]
        try:
            roots = self._wsl_roots()
        except Exception:  # noqa: BLE001 - 这一分钟当作读不到
            roots = []
        if roots is None:
            return accounts
        self._wsl.roots = [Path(root) for root in roots]
        totals = self._wsl.refresh()
        if not self._wsl.reachable and totals.messages == 0:
            return accounts + [AccountUsage(WSL_ACCOUNT, None)]
        return accounts + [AccountUsage(WSL_ACCOUNT, totals)]
