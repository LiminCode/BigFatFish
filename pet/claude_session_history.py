# -*- coding: utf-8 -*-
"""最近的对话：记下每个 Claude Code 会话在哪打开的（纯逻辑 + 本机读取，零 Qt）。

为什么要记：Claude Code 的对话记录集中存在
``~/.claude/projects/<目录编码>/<会话ID>.jsonl``，但 ``claude --resume`` 只列**当前目录**
的会话——在某个目录开过一个对话、关掉、忘了是哪个目录，就没有入口了。

三块：

- ``SessionHistory``：一个会话一行（同一个会话再打开 = 就地更新），按最后活动时间
  留最近 N 天、最多 M 条；落盘到肥鱼配置目录的一个 JSON 文件。**只存路径、标题、
  入口这类信息，不存对话内容。**
- 回填（``scan_local`` / ``scan_wsl``）：肥鱼没开着时打开过的对话，从 Claude Code 自己
  的 transcript 里补出来。那是它的**内部格式**（字段随版本变），所以读不到就跳过，
  绝不因此出错。目录取会话**开头**那一条的 ``cwd``——那才是这份记录归属的目录
  （也就是能 ``--resume`` 的目录）；会话中途 ``cd`` 过，后面的 ``cwd`` 会变。
- 恢复（``terminal_resume_argv`` / ``default_action``）：回到那个目录、接着那个对话。

阻塞调用（读文件、起 wsl.exe）都由调用方放到后台线程（``session_history_service``）。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable, Iterable

from . import claude_hooks, claude_session_info
from .i18n import t
from .claude_session_info import ENTRY_CLI, ENTRY_VSCODE

log = logging.getLogger(__name__)

HISTORY_FILE = "claude-session-history.json"
DEFAULT_MAX_AGE_DAYS = 7
DEFAULT_MAX_ENTRIES = 30
_DAY_S = 86400.0
#: 最后活动时间差不到这么多就不算「值得落盘的变化」（每次工具调用都会来一条更新）
SAVE_GRANULARITY_S = 60.0
#: 回填时每份 transcript 只读头尾这么多字节
SCAN_BYTES = 64 * 1024
#: 回填一次最多看这么多份（按修改时间从新到旧）
SCAN_LIMIT = 80

WSL_AGENT = "claude_wsl"
#: 入口 → 列表里的说法
_WHERE_KEYS = {ENTRY_VSCODE: "history.where.vscode", ENTRY_CLI: "history.where.terminal", "sdk-cli": "history.where.script"}
#: 会话 ID 会拼进命令行：只放行 UUID 用得到的字符
_SESSION_ID_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z-]{7,63}$")
#: transcript 文件名：会话 ID（UUID）。同目录下 ``agent-*.jsonl`` 之类的不是会话
_TRANSCRIPT_STEM_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F-]{20,}$")
_MSYS_DRIVE_RE = re.compile(r"^/([A-Za-z])(/.*)?$")
_DRIVE_RE = re.compile(r"^([A-Za-z]):(.*)$")
_FIELDS = ("cwd", "title", "project", "entrypoint", "git_branch", "distro")


def normalize_cwd(agent: str, cwd: str) -> str:
    """同一个目录只留一种写法。

    本机会话的记录里同一个目录有三种写法：``C:\\…``、``c:\\…``（VS Code 给的小写盘符）
    和 ``/c/…``（Git Bash）。WSL 里的路径原样保留（那边 ``/c/`` 只是个普通目录）。
    """
    text = str(cwd or "").strip()
    if not text:
        return ""
    if agent == WSL_AGENT:
        return text.rstrip("/") or "/"
    msys = _MSYS_DRIVE_RE.match(text)
    if msys:
        text = f"{msys.group(1)}:{msys.group(2) or '/'}"
    drive = _DRIVE_RE.match(text)
    if not drive:
        return text.rstrip("\\/") or text
    rest = drive.group(2).replace("/", "\\").rstrip("\\")
    return f"{drive.group(1).upper()}:{rest or chr(92)}"


def ago_text(seconds: float) -> str:
    """多久以前（列表右侧那一栏）。"""
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return t("ago.now")
    if seconds < 3600:
        return t("ago.minutes", n=int(seconds // 60))
    if seconds < _DAY_S:
        return t("ago.hours", n=int(seconds // 3600))
    if seconds < 2 * _DAY_S:
        return t("ago.yesterday")
    return t("ago.days", n=int(seconds // _DAY_S))


@dataclass
class HistoryEntry:
    """一个开过的会话。"""

    agent: str
    session_id: str
    cwd: str = ""
    title: str = ""
    project: str = ""
    entrypoint: str = ""
    git_branch: str = ""
    distro: str = ""
    last_seen: float = 0.0

    @property
    def key(self) -> tuple[str, str]:
        return self.agent, self.session_id

    @property
    def is_wsl(self) -> bool:
        return self.agent == WSL_AGENT

    @property
    def folder(self) -> str:
        """目录的最后一段（项目文件夹名）。"""
        if not self.cwd:
            return ""
        return (PurePosixPath(self.cwd) if self.is_wsl else PureWindowsPath(self.cwd)).name

    @property
    def label(self) -> str:
        """列表里的主标题：会话标题 > 文件夹名 > 会话 ID 前 8 位。"""
        return self.title or self.folder or self.session_id[:8]

    @property
    def where(self) -> str:
        """从哪开的：「终端」「VS Code」「终端 · WSL」。"""
        key = _WHERE_KEYS.get(self.entrypoint)
        text = t(key) if key else ""
        if self.is_wsl:
            return t("history.where.wsl_suffix", text=text) if text else t("history.where.wsl")
        return text

    @property
    def host(self) -> str:
        """在哪开的，给列表挑图标：``vscode`` / ``terminal``（本机）/ ``wsl``（WSL 终端）/ ``script`` / 空。"""
        if self.entrypoint == ENTRY_VSCODE:
            return "vscode"
        if self.entrypoint == "sdk-cli":
            return "script"
        if self.is_wsl:
            return "wsl"
        return "terminal" if self.entrypoint == ENTRY_CLI else ""

    @property
    def resume_command(self) -> str:
        return f"claude --resume {self.session_id}"


def _clamp(value, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


class SessionHistory:
    """最近开过的会话（见模块说明）。不是线程安全的：只在 GUI 线程上用。"""

    def __init__(self, path: Path | str | None = None, *, max_age_days=DEFAULT_MAX_AGE_DAYS,
                 max_entries=DEFAULT_MAX_ENTRIES, clock: Callable[[], float] = time.time) -> None:
        self._path = Path(path) if path else None
        self._clock = clock
        self._entries: dict[tuple[str, str], HistoryEntry] = {}
        self.ui_open = False             # 灵动岛上那个折叠框开着没有（界面状态，跟着数据一起存）
        self.max_age_days = DEFAULT_MAX_AGE_DAYS
        self.max_entries = DEFAULT_MAX_ENTRIES
        self.configure(max_age_days, max_entries)

    def configure(self, max_age_days, max_entries) -> None:
        """保留天数（1–30）与条数上限（1–200）；给的值不像话就用默认。"""
        self.max_age_days = _clamp(max_age_days, DEFAULT_MAX_AGE_DAYS, 1, 30)
        self.max_entries = _clamp(max_entries, DEFAULT_MAX_ENTRIES, 1, 200)

    # ---------------------------------------------------------------- 记录
    def record(self, agent: str, session_id: str, *, seen: float | None = None, **fields) -> bool:
        """记一笔（没有就新建，有就更新）。返回有没有值得落盘的变化。

        空字段不覆盖已知的值；``seen`` 是最后活动时间（缺省 = 现在），只会往后走。
        """
        agent, session_id = str(agent or ""), str(session_id or "")
        if not agent or not _SESSION_ID_RE.match(session_id):
            return False
        now = self._clock()
        seen = now if seen is None else float(seen)
        values = {name: str(fields.get(name) or "").strip() for name in _FIELDS}
        values["cwd"] = normalize_cwd(agent, values["cwd"])
        entry = self._entries.get((agent, session_id))
        if entry is None:
            self._entries[(agent, session_id)] = HistoryEntry(
                agent=agent, session_id=session_id, last_seen=seen, **values)
            return True
        changed = False
        for name, value in values.items():
            if value and getattr(entry, name) != value:
                setattr(entry, name, value)
                changed = True
        if seen > entry.last_seen:
            changed = changed or seen - entry.last_seen >= SAVE_GRANULARITY_S
            entry.last_seen = seen
        return changed

    def merge(self, found: Iterable[dict]) -> bool:
        """并入回填扫到的会话（``scan_local`` / ``scan_wsl`` 的结果）。"""
        changed = False
        for item in found:
            item = dict(item)
            agent, session_id = item.pop("agent", ""), item.pop("session_id", "")
            changed = self.record(agent, session_id, **item) or changed
        return changed

    def remove(self, key: tuple[str, str]) -> bool:
        return self._entries.pop(tuple(key), None) is not None

    def clear(self) -> bool:
        had = bool(self._entries)
        self._entries.clear()
        return had

    # ---------------------------------------------------------------- 读取
    def _prune(self) -> list[HistoryEntry]:
        """丢掉过期的，返回可以列出来的（知道目录的），新的在前、不超过上限。"""
        cutoff = self._clock() - self.max_age_days * _DAY_S
        for key in [key for key, entry in self._entries.items() if entry.last_seen < cutoff]:
            del self._entries[key]
        listed = sorted((e for e in self._entries.values() if e.cwd),
                        key=lambda e: e.last_seen, reverse=True)
        for entry in listed[self.max_entries:]:
            del self._entries[entry.key]
        return listed[:self.max_entries]

    def entries(self) -> list[HistoryEntry]:
        return self._prune()

    # ---------------------------------------------------------------- 落盘
    def load(self) -> None:
        self._entries.clear()
        if self._path is None:
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        self.ui_open = bool(data.get("ui_open", False))
        rows = data.get("entries")
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            try:
                seen = float(row.get("last_seen") or 0.0)
            except (TypeError, ValueError):
                continue
            self.record(str(row.get("agent") or ""), str(row.get("session_id") or ""), seen=seen,
                        **{name: row.get(name) for name in _FIELDS if isinstance(row.get(name), str)})

    def save(self) -> bool:
        if self._path is None:
            return False
        data = {"version": 1, "ui_open": bool(self.ui_open),
                "entries": [asdict(entry) for entry in self._prune()]}
        temp = self._path.with_name(self._path.name + ".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(temp, self._path)
            return True
        except OSError:
            log.warning("最近的对话：写入 %s 失败", self._path, exc_info=True)
            return False


# ---------------------------------------------------------------- 回填
def parse_transcript_head(text: str) -> dict:
    """transcript 开头：每个字段取**最靠前**的一次出现（``cwd / entrypoint / git_branch``）。"""
    found: dict[str, str] = {}
    for line in text.splitlines():
        if not line.startswith("{"):
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        for key, source in (("cwd", "cwd"), ("entrypoint", "entrypoint"), ("git_branch", "gitBranch")):
            value = entry.get(source)
            if isinstance(value, str) and value:
                found.setdefault(key, value)
        if len(found) == 3:
            break
    return found


def _combine(agent: str, session_id: str, head_text: str, tail_text: str, seen: float) -> dict | None:
    head = parse_transcript_head(head_text)
    tail = claude_session_info.parse_transcript_tail(tail_text)
    cwd = normalize_cwd(agent, head.get("cwd") or tail.get("cwd") or "")
    if not cwd:
        return None
    return {
        "agent": agent, "session_id": session_id, "cwd": cwd, "title": tail.get("title", ""),
        "git_branch": tail.get("git_branch") or head.get("git_branch", ""),
        "entrypoint": head.get("entrypoint") or tail.get("entrypoint", ""), "seen": seen,
    }


def _read_head(path: Path, limit: int) -> str:
    try:
        with open(path, "rb") as handle:
            return handle.read(limit).decode("utf-8", "replace")
    except OSError:
        return ""


def scan_local(home: Path | None = None, *, max_age_days: int = DEFAULT_MAX_AGE_DAYS,
               now: float | None = None, limit: int = SCAN_LIMIT) -> list[dict]:
    """本机 ``~/.claude/projects`` 里最近动过的会话（阻塞：读文件）。"""
    projects = (home or Path.home()) / ".claude" / "projects"
    cutoff = (time.time() if now is None else now) - max_age_days * _DAY_S
    recent: list[tuple[float, Path]] = []
    try:
        for path in projects.glob("*/*.jsonl"):
            if not _TRANSCRIPT_STEM_RE.match(path.stem):
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime >= cutoff:
                recent.append((mtime, path))
    except OSError:
        return []
    found = []
    for mtime, path in sorted(recent, reverse=True)[:limit]:
        item = _combine("claude", path.stem, _read_head(path, SCAN_BYTES),
                        claude_session_info.read_tail(path, SCAN_BYTES), mtime)
        if item is not None:
            found.append(item)
    return found


#: 发行版里跑的那一段：列出最近动过的 transcript，各取头尾一小段。``$1`` = 天数
WSL_SCAN_SCRIPT = r'''
echo "@@distro ${WSL_DISTRO_NAME:-}"
d="$HOME/.claude/projects"
[ -d "$d" ] || exit 0
find "$d" -mindepth 2 -maxdepth 2 -name '*.jsonl' -mtime "-${1:-7}" -printf '%T@ %p\n' 2>/dev/null \
  | sort -rn | head -n ''' + str(SCAN_LIMIT) + r''' | while read -r t p; do
    echo "@@file $t $p"
    head -c ''' + str(SCAN_BYTES) + r''' "$p" 2>/dev/null; echo
    echo "@@tail"
    tail -c ''' + str(SCAN_BYTES) + r''' "$p" 2>/dev/null; echo
    echo "@@end"
done
:
'''


def parse_wsl_scan(text: str) -> list[dict]:
    """``WSL_SCAN_SCRIPT`` 的输出 → 与 ``scan_local`` 同形的列表（多一项 ``distro``）。"""
    distro, found = "", []
    block: dict | None = None
    for line in text.splitlines():
        if line.startswith("@@distro "):
            distro = line[len("@@distro "):].strip()
        elif line.startswith("@@file "):
            stamp, _sep, path = line[len("@@file "):].partition(" ")
            block = {"stamp": stamp, "stem": PurePosixPath(path).stem, "head": [], "tail": [], "part": "head"}
        elif block is None:
            continue
        elif line == "@@tail":
            block["part"] = "tail"
        elif line == "@@end":
            try:
                seen = float(block["stamp"])
            except ValueError:
                seen = None
            if seen is not None and _TRANSCRIPT_STEM_RE.match(block["stem"]):
                item = _combine(WSL_AGENT, block["stem"], "\n".join(block["head"]),
                                "\n".join(block["tail"]), seen)
                if item is not None:
                    found.append({**item, "distro": distro})
            block = None
        else:
            block[block["part"]].append(line)
    return found


def scan_wsl(*, runner=claude_hooks.run_wsl, max_age_days: int = DEFAULT_MAX_AGE_DAYS) -> list[dict]:
    """WSL 默认发行版里最近动过的会话（阻塞：一次 wsl.exe 调用；失败返回空）。"""
    code, out = runner(["-e", "sh", "-c", WSL_SCAN_SCRIPT, "sh", str(int(max_age_days))])
    if code != 0 and not out:
        return []
    return parse_wsl_scan(out)


# ---------------------------------------------------------------- 恢复
def default_action(entry: HistoryEntry) -> str:
    """点一行做什么：VS Code 里开的 → 打开那个工作区；其余 → 在终端里恢复。"""
    return "vscode" if entry.entrypoint == ENTRY_VSCODE else "terminal"


def terminal_resume_argv(entry: HistoryEntry, *, which: Callable[[str], str | None] = shutil.which,
                         wsl: str | None = None) -> list[str] | None:
    """在那个目录开一个终端并恢复这个会话的命令行；做不到返回 None。

    优先 Windows Terminal（``wt -d 目录``），没有就开普通控制台。WSL 会话进发行版
    （``wsl --cd 目录``），用登录 shell 起 claude（PATH 才齐），退出后留在 shell 里。
    """
    if not entry.cwd or not _SESSION_ID_RE.match(entry.session_id):
        return None
    terminal = which("wt")
    if entry.is_wsl:
        wsl_path = claude_hooks.wsl_exe() if wsl is None else wsl
        if not wsl_path:
            return None
        inner = [wsl_path, *(["-d", entry.distro] if entry.distro else []), "--cd", entry.cwd, "--",
                 "bash", "-lic", f"claude --resume {entry.session_id}; exec bash"]
        return [terminal, *inner] if terminal else ["cmd", "/c", "start", "", *inner]
    inner = ["cmd", "/k", "claude", "--resume", entry.session_id]
    if terminal:
        return [terminal, "-d", entry.cwd, *inner]
    return ["cmd", "/c", "start", "", "/D", entry.cwd, *inner]
