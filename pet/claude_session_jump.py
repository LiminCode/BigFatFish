# -*- coding: utf-8 -*-
"""跳到一个 Claude Code 会话所在的窗口（Windows；零 Qt）。

两类会话，能做到的程度不一样：

- **VS Code 插件里的会话**：先把承载它的那个 VS Code 窗口调到前台，再打开
  ``vscode://anthropic.claude-code/open?session=<id>``——插件会聚焦那个会话的标签页
  （官方文档有这个链接；会话必须属于**当前聚焦窗口**的工作区，否则插件会新开一个
  空对话，所以窗口没调对就不发链接）。
- **终端里的会话**：只能把承载它的终端窗口（Windows Terminal / VS Code 的内置终端）
  调到前台。具体是哪个标签页选不了——那是终端程序自己的界面，外面够不着。

怎么找窗口：

- VS Code 的所有窗口都属于同一个主进程，靠**标题**分辨：标题按 `` - `` 分段，其中一段
  是工作区的名字（默认标题与用户自定义的 ``window.title`` 里只要带 ``rootName`` 都
  满足）；WSL 远程窗口那一段是 ``名字 [WSL: 发行版]``。
- 工作区的名字不一定是会话所在的文件夹名：多文件夹工作区叫 ``<工作区文件名> (Workspace)``，
  会话的文件夹只是其中之一。所以先问 VS Code 自己（``opened_workspaces``：它在
  ``storage.json`` 里记着每个窗口开的是哪个文件夹 / 哪个工作区文件）会话属于哪个窗口，
  再按那个窗口的名字去标题里找。
- 最准的一条线索也在 VS Code 自己那里：每个窗口有一份状态库
  （``workspaceStorage/<id>/state.vscdb``），里面记着它开着哪些标签页，Claude 会话的标签页
  带着会话 ID（``session_windows``）。查得到就以它为准——同一个文件夹被两个工作区包含、
  或会话中途 cd 到了工作区外面，光看路径都分不出来。状态库是隔一阵才落盘的，刚开的
  会话可能还查不到，那时退回按路径和标题找。
- 标题分不清时（几个窗口同名、或标题被自定义得不带名字）：看哪个窗口的当前标签页正是
  这个对话；还不行就让 ``code`` 命令按确切的文件夹 / 工作区文件去聚焦——VS Code 按它
  去重，已经开着的不会新开。
- 本机终端会话顺着进程链往上找第一个拥有可见窗口的祖先进程。
- WSL 终端会话的进程链在发行版里，看不到 Windows 这一侧：用它环境变量里的
  ``TERM_PROGRAM`` / ``WT_SESSION`` 判断是 VS Code 终端还是 Windows Terminal。
"""
from __future__ import annotations

import json
import logging
import ntpath
import os
import posixpath
import shutil
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable
from urllib.parse import unquote, urlsplit

from .claude_session_info import ENTRY_VSCODE, SessionDetail
from .i18n import t

log = logging.getLogger(__name__)

VSCODE_PROCESSES = frozenset({"code.exe", "code - insiders.exe", "cursor.exe", "windsurf.exe",
                              "vscodium.exe"})
TERMINAL_PROCESSES = frozenset({"windowsterminal.exe", "wezterm-gui.exe", "alacritty.exe",
                                "conemu64.exe", "conemu.exe", "mintty.exe", "tabby.exe",
                                "hyper.exe"})
_URI = "vscode://anthropic.claude-code/open?session={session}"
#: 窗口调到前台后等这么久再发链接：链接由「最后活跃的 VS Code 窗口」处理
_URI_DELAY_S = 0.35
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
#: 各家 VS Code 系编辑器在 %APPDATA% 下的数据目录（里面的 storage.json 记着打开的窗口）
_VSCODE_DATA_DIRS = ("Code", "Code - Insiders", "Cursor", "Windsurf", "VSCodium")
_WORKSPACE_SUFFIX = ".code-workspace"
#: 窗口状态库里会提到会话 ID 的两项：打开着的标签页；Claude Code 插件自己的状态
_STATE_KEYS = ("memento/workbench.parts.editor", "Anthropic.claude-code")
#: 当前标签页的标题被截断成「前缀…」时，前缀至少这么长才拿来认对话
_MIN_TAB_PREFIX = 8


@dataclass(frozen=True)
class Window:
    hwnd: int
    pid: int
    title: str
    process: str = ""      # 进程名（小写）


@dataclass(frozen=True)
class JumpResult:
    ok: bool
    message: str


@dataclass(frozen=True)
class OpenWorkspace:
    """VS Code 的一个窗口开着的东西（来自它自己的记录）。"""
    label: str                    # 标题里那一段的名字：文件夹名，或工作区文件名（不含扩展名）
    roots: tuple[str, ...]        # 它包含的文件夹（斜杠统一成 /）
    target: str                   # 交给 code 命令就能聚焦到这个窗口的路径：文件夹，或工作区文件
    wsl: bool = False
    multi_root: bool = False
    storage: tuple[str, ...] = ()  # 它的状态库所在的目录（workspaceStorage/<id>），可能不止一个


# ---------------------------------------------------------------- 纯逻辑：挑窗口
def folder_name(cwd: str) -> str:
    """工作目录的最后一段（Windows 与 POSIX 路径都认）。"""
    text = str(cwd or "").rstrip("\\/")
    if not text:
        return ""
    if "\\" in text or (len(text) > 1 and text[1] == ":"):
        return PureWindowsPath(text).name
    return PurePosixPath(text).name


def _title_segments(title: str) -> list[str]:
    return [part.strip() for part in title.split(" - ") if part.strip()]


def _named(window: Window, matches: Callable[[str], bool], wsl: bool) -> bool:
    """标题里有没有一段的名字满足 ``matches``，且远程标记对得上。

    ``wsl=True`` 只认带 ``[WSL: …]`` 标记的那一段，反之只认不带任何远程标记的——同名
    项目在 Windows 和 WSL 各开一份时不会跳错。"""
    for segment in _title_segments(window.title):
        base, bracket, rest = segment.partition(" [")
        is_wsl = bracket != "" and rest.upper().startswith("WSL")
        if matches(base.strip()) and is_wsl == wsl and (wsl or bracket == ""):
            return True
    return False


def vscode_candidates(windows: list[Window], cwd: str, *, wsl: bool = False,
                      owner: OpenWorkspace | None = None) -> list[Window]:
    """标题对得上的 VS Code 窗口，按从前到后的层叠顺序（最近用过的在前）。

    知道会话属于哪个窗口（``owner``）时按那个窗口的名字找：多文件夹工作区的那一段是
    ``<名字> (Workspace)``，括号里的词随界面语言变，所以只认「名字 + 一对括号」。
    不知道时按会话的文件夹名找；工作目录可能是工作区的子目录，逐级往上，直到根目录。
    """
    candidates = [w for w in windows if w.process in VSCODE_PROCESSES]
    if owner is not None:
        label = owner.label
        if owner.multi_root:
            def matches(base: str) -> bool:
                return base.startswith(label + " (") and base.endswith(")")
        else:
            def matches(base: str) -> bool:
                return base == label
        return [w for w in candidates if _named(w, matches, wsl)]
    path = str(cwd or "").rstrip("\\/")
    for _ in range(8):
        name = folder_name(path)
        if not name:
            break
        found = [w for w in candidates if _named(w, lambda base, name=name: base == name, wsl)]
        if found:
            return found
        parent = path[:max(path.rfind("\\"), path.rfind("/"))]
        if not parent or parent == path:
            break
        path = parent
    return []


def find_vscode_window(windows: list[Window], cwd: str, *, wsl: bool = False,
                       owner: OpenWorkspace | None = None) -> Window | None:
    """``vscode_candidates`` 里最靠前（最近用过）的那个。"""
    found = vscode_candidates(windows, cwd, wsl=wsl, owner=owner)
    return found[0] if found else None


def _shows_session(window: Window, title: str) -> bool:
    """这个窗口的当前标签页是不是这个对话：标题里有一段等于会话标题，或是它被截断的前缀。"""
    title = str(title or "").strip()
    if len(title) < _MIN_TAB_PREFIX:
        return False
    for segment in _title_segments(window.title):
        if segment == title:
            return True
        if segment.endswith("…"):
            prefix = segment[:-1].rstrip()
            if len(prefix) >= _MIN_TAB_PREFIX and title.startswith(prefix):
                return True
    return False


# ---------------------------------------------------------------- VS Code 自己记的窗口清单
def _strip_jsonc(text: str) -> str:
    """去掉 JSONC 里的注释和行尾逗号（字符串里的 ``//`` 不动）。"""
    out: list[str] = []
    i, n, in_string = 0, len(text), False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 1
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
            out.append(ch)
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end < 0 else end
            continue
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        elif ch in "}]":
            while out and out[-1].isspace():
                out.pop()
            if out and out[-1] == ",":
                out.pop()
            out.append(ch)
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _split_uri(uri: str) -> tuple[str, str, str] | None:
    """窗口记录里的地址 → (``local`` / ``wsl``, 发行版, 路径)；别的远程（SSH 等）返回 None。"""
    try:
        parts = urlsplit(str(uri))
    except ValueError:
        return None
    path = unquote(parts.path)
    if parts.scheme == "file":
        if parts.netloc:                                   # file://server/share：UNC
            return "local", "", "//" + unquote(parts.netloc) + path
        return "local", "", path[1:] if len(path) > 2 and path[0] == "/" and path[2] == ":" else path
    if parts.scheme == "vscode-remote":
        kind, _plus, name = unquote(parts.netloc).partition("+")
        if kind == "wsl" and name:
            return "wsl", name, path
    return None


def _norm(path: str) -> str:
    return posixpath.normpath(str(path).replace("\\", "/"))


def _workspace_roots(text: str, config_path: str, distro: str) -> tuple[str, ...]:
    """工作区文件里的文件夹（相对路径相对工作区文件所在目录）。"""
    try:
        data = json.loads(_strip_jsonc(text))
    except ValueError:
        return ()
    base = posixpath.dirname(_norm(config_path))
    roots = []
    for item in (data.get("folders") if isinstance(data, dict) else None) or []:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("path"), str) and item["path"]:
            path = _norm(item["path"])
            absolute = path.startswith("/") or ntpath.isabs(item["path"])
            roots.append(path if absolute else posixpath.normpath(posixpath.join(base, path)))
        elif isinstance(item.get("uri"), str):
            parsed = _split_uri(item["uri"])
            if parsed is not None and parsed[1].lower() == distro.lower():
                roots.append(_norm(parsed[2]))
    return tuple(roots)


def workspaces_from_state(state: dict, read_text: Callable[[str, str], str | None]) -> list[OpenWorkspace]:
    """``storage.json`` 的内容 → 打开着的窗口。``read_text(路径, 发行版)`` 读工作区文件。"""
    windows_state = state.get("windowsState") if isinstance(state, dict) else None
    if not isinstance(windows_state, dict):
        return []
    entries = [windows_state.get("lastActiveWindow"), *(windows_state.get("openedWindows") or [])]
    found: dict[tuple, OpenWorkspace] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        identifier = entry.get("workspaceIdentifier")
        config = identifier.get("configURIPath") if isinstance(identifier, dict) else None
        folder = entry.get("folder")
        if isinstance(config, str):
            parsed = _split_uri(config)
            if parsed is None:
                continue
            kind, distro, path = parsed
            text = read_text(path, distro)
            roots = _workspace_roots(text, path, distro) if text else ()
            if not roots:
                continue
            name = posixpath.basename(_norm(path))
            label = name[:-len(_WORKSPACE_SUFFIX)] if name.endswith(_WORKSPACE_SUFFIX) else "Untitled"
            item = OpenWorkspace(label, roots, _norm(path), wsl=kind == "wsl", multi_root=True)
        elif isinstance(folder, str):
            parsed = _split_uri(folder)
            if parsed is None:
                continue
            kind, _distro, path = parsed
            root = _norm(path)
            item = OpenWorkspace(posixpath.basename(root), (root,), root, wsl=kind == "wsl")
        else:
            continue
        found.setdefault((item.wsl, item.target.lower()), item)
    return list(found.values())


def _read_workspace_file(path: str, distro: str) -> str | None:
    """读一个工作区文件；WSL 里的经 ``\\\\wsl.localhost\\发行版\\…`` 读（发行版名不分大小写）。"""
    target = ("\\\\wsl.localhost\\" + distro + path.replace("/", "\\")) if distro else path
    try:
        with open(target, encoding="utf-8") as handle:
            return handle.read(1_000_000)
    except (OSError, ValueError):
        return None


def opened_workspaces(appdata: str | os.PathLike | None = None,
                      read_text: Callable[[str, str], str | None] = _read_workspace_file) -> list[OpenWorkspace]:
    """各家 VS Code 系编辑器当前开着的窗口（阻塞：读几个小文件）。读不到就是空。"""
    base = appdata if appdata is not None else os.environ.get("APPDATA")
    if not base:
        return []
    found: list[OpenWorkspace] = []
    for name in _VSCODE_DATA_DIRS:
        user = Path(base) / name / "User"
        try:
            state = json.loads((user / "globalStorage" / "storage.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        index = _storage_index(user)
        found.extend(replace(item, storage=tuple(index.get((item.wsl, item.target.lower()), ())))
                     for item in workspaces_from_state(state, read_text))
    return found


def _storage_index(user_dir: Path) -> dict[tuple[bool, str], list[str]]:
    """(是否 WSL, 文件夹或工作区文件) → 状态库目录。同一个目标可能有几个目录（地址里
    发行版名大小写不同就会各建一个），都留着。"""
    index: dict[tuple[bool, str], list[str]] = {}
    try:
        folders = list((user_dir / "workspaceStorage").iterdir())
    except OSError:
        return index
    for folder in folders:
        try:
            meta = json.loads((folder / "workspace.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        uri = (meta.get("folder") or meta.get("workspace")) if isinstance(meta, dict) else None
        if isinstance(uri, dict):
            uri = uri.get("configPath")
        parsed = _split_uri(uri) if isinstance(uri, str) else None
        if parsed is not None:
            index.setdefault((parsed[0] == "wsl", _norm(parsed[2]).lower()), []).append(str(folder))
    return index


def _state_mentions(storage_dir: str, session_id: str) -> int:
    """这个窗口的状态库提没提到这个会话：2 = 它是开着的一个标签页；1 = 只在插件的状态里；0 = 没有。"""
    db = Path(storage_dir) / "state.vscdb"
    if not db.is_file():
        return 0
    try:
        connection = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=1.0)
        try:
            rows = connection.execute(
                "SELECT key FROM ItemTable WHERE key IN (?, ?) AND instr(value, ?) > 0",
                (*_STATE_KEYS, session_id)).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return 0
    keys = {row[0] for row in rows}
    return 2 if _STATE_KEYS[0] in keys else 1 if keys else 0


def session_windows(workspaces: list[OpenWorkspace], session_id: str,
                    mentions: Callable[[str, str], int] = _state_mentions) -> list[OpenWorkspace]:
    """VS Code 自己记着这个会话开在哪个窗口里的话，返回那个窗口（阻塞：每个窗口查一次小库）。

    「是开着的标签页」压过「只在插件状态里出现过」；都没有返回空。"""
    if not session_id:
        return []
    scored = [(max((mentions(folder, session_id) for folder in w.storage), default=0), w) for w in workspaces]
    best = max((score for score, _w in scored), default=0)
    return [w for score, w in scored if score == best] if best else []


def owning_workspaces(workspaces: list[OpenWorkspace], cwd: str, *, wsl: bool) -> list[OpenWorkspace]:
    """工作目录落在哪些窗口的文件夹里；只留最贴近的（文件夹最深的）。

    通常只有一个。同一个文件夹既单独开了一个窗口、又是某个多文件夹工作区的一员时会有
    两个——光看路径分不出会话在哪一个里。"""
    path = _norm(cwd) if cwd else ""
    if not path or path == ".":
        return []
    if not wsl:
        path = path.lower()                     # Windows 路径不分大小写
    best: list[OpenWorkspace] = []
    depth = -1
    for workspace in workspaces:
        if workspace.wsl != wsl:
            continue
        deepest = max((len(root) for root in workspace.roots
                       if (path == (root if wsl else root.lower())
                           or path.startswith((root if wsl else root.lower()).rstrip("/") + "/"))),
                      default=-1)
        if deepest > depth:
            best, depth = [workspace], deepest
        elif deepest == depth and deepest >= 0:
            best.append(workspace)
    return best


def narrow_by_start(owners: list[OpenWorkspace], start_cwd: str, *, wsl: bool) -> list[OpenWorkspace]:
    """几个窗口都包含会话的目录时，用会话进程启动时所在的目录再筛一遍。

    VS Code 插件把进程起在工作区的第一个文件夹里（单文件夹窗口就是那个文件夹），所以
    「第一个文件夹正是启动目录」的窗口优先；一个都对不上就原样返回，不硬猜。"""
    if len(owners) < 2 or not start_cwd:
        return owners
    start = _norm(start_cwd) if wsl else _norm(start_cwd).lower()
    first = [o for o in owners if o.roots and (o.roots[0] if wsl else o.roots[0].lower()) == start]
    return first or owners


def owning_workspace(workspaces: list[OpenWorkspace], cwd: str, *, wsl: bool) -> OpenWorkspace | None:
    """会话属于哪个窗口；路径上分不出唯一的一个就返回 None。"""
    owners = owning_workspaces(workspaces, cwd, wsl=wsl)
    return owners[0] if len(owners) == 1 else None


def find_host_window(chain: list[tuple[int, str]], windows: list[Window], cwd: str,
                     hints: tuple[str, ...] = ()) -> Window | None:
    """本机终端会话的宿主窗口：进程链（自己 → 父 → …）里第一个有可见窗口的祖先。

    祖先是 VS Code 时（内置终端）它的窗口都归同一个进程，按工作区文件夹挑；挑不出就
    取最靠前的那个。祖先是 Windows Terminal 等时一个进程也可能有几个窗口：标题里含
    会话标题 / 名字（``hints``）的优先。
    """
    for pid, name in chain[1:]:
        owned = [w for w in windows if w.pid == pid]
        if not owned:
            continue
        if name.lower() in VSCODE_PROCESSES:
            # 按工作区认不出来时：本机会话不会在远程（WSL / SSH）窗口的终端里
            local = [w for w in owned if " [" not in w.title]
            return find_vscode_window(owned, cwd) or (local or owned)[0]
        return _pick_by_hints(owned, hints) or owned[0]
    return None


def _pick_by_hints(windows: list[Window], hints: tuple[str, ...]) -> Window | None:
    for hint in hints:
        hint = hint.strip()
        if len(hint) < 3:
            continue
        for window in windows:
            if hint in window.title:
                return window
    return None


def find_wsl_terminal_window(windows: list[Window], detail: SessionDetail,
                             env: dict[str, str], owner: OpenWorkspace | None = None) -> Window | None:
    """WSL 终端会话的宿主窗口（按它的环境变量猜是哪种终端）。"""
    hints = (detail.title, detail.name, detail.distro)
    if env.get("TERM_PROGRAM") == "vscode":
        return find_vscode_window(windows, detail.cwd, wsl=True, owner=owner)
    terminals = [w for w in windows if w.process in TERMINAL_PROCESSES]
    if env.get("WT_SESSION"):
        terminals = [w for w in terminals if w.process == "windowsterminal.exe"] or terminals
    return (_pick_by_hints(terminals, hints) or (terminals[0] if terminals else None)
            or find_vscode_window(windows, detail.cwd, wsl=True, owner=owner))


def session_uri(session_id: str) -> str:
    return _URI.format(session=session_id)


def explorer_path(detail: SessionDetail) -> str:
    """资源管理器能打开的项目路径（WSL 路径换成 ``\\\\wsl.localhost\\发行版\\…``）。"""
    cwd = detail.cwd
    if not cwd:
        return ""
    if detail.is_wsl:
        if not detail.distro or not cwd.startswith("/"):
            return ""
        return "\\\\wsl.localhost\\" + detail.distro + cwd.replace("/", "\\")
    return cwd


# ---------------------------------------------------------------- Win32
def list_windows() -> list[Window]:
    """可见、有标题的顶层窗口，按层叠顺序从前到后。非 Windows 返回空表。"""
    if sys.platform != "win32":
        return []
    import ctypes
    import ctypes.wintypes as wt

    user32 = ctypes.windll.user32
    found: list[tuple[int, int, str]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def visit(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if not length:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        found.append((int(hwnd), int(pid.value), buffer.value))
        return True

    user32.EnumWindows(visit, 0)
    names: dict[int, str] = {}
    try:
        import psutil

        for _hwnd, pid, _title in found:
            if pid not in names:
                try:
                    names[pid] = psutil.Process(pid).name().lower()
                except psutil.Error:
                    names[pid] = ""
    except ImportError:
        pass
    return [Window(hwnd, pid, title, names.get(pid, "")) for hwnd, pid, title in found]


def process_chain(pid: int) -> list[tuple[int, str]]:
    """``[(pid, 进程名), (父进程…), …]``；取不到返回空表。"""
    try:
        import psutil

        process = psutil.Process(pid)
        return [(process.pid, process.name())] + [(p.pid, p.name()) for p in process.parents()]
    except Exception:
        return []


def focus_window(hwnd: int) -> bool:
    """把窗口调到前台（最小化的先还原）。"""
    if sys.platform != "win32":
        return False
    import ctypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)            # SW_RESTORE

    def in_front() -> bool:
        return int(user32.GetForegroundWindow() or 0) == int(hwnd)

    # Windows 只让「刚收到用户输入的进程」换前台窗口。用户刚点过我们的菜单 / 卡片时
    # 第一招就成；否则（连续跳转、从后台线程调）逐级换更强的办法。成败一律看结果
    # ——SetForegroundWindow 的返回值在被拒绝时也可能是真（只闪任务栏）。
    user32.SetForegroundWindow(hwnd)
    if in_front():
        return True
    # 借前台线程的输入队列：挂上去之后本线程就有资格换前台
    foreground = user32.GetForegroundWindow()
    front_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
    this_thread = kernel32.GetCurrentThreadId()
    attached = bool(front_thread and front_thread != this_thread
                    and user32.AttachThreadInput(this_thread, front_thread, True))
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(this_thread, front_thread, False)
    if in_front():
        return True
    # 按一下 Alt：系统允许「正在处理按键」的进程设置前台窗口
    user32.keybd_event(0x12, 0, 0, 0)
    try:
        time.sleep(0.03)
        user32.SetForegroundWindow(hwnd)
    finally:
        user32.keybd_event(0x12, 0, 0x0002, 0)
    if in_front():
        return True
    user32.SwitchToThisWindow(hwnd, True)
    time.sleep(0.05)
    return in_front()


def open_uri(uri: str) -> bool:
    try:
        os.startfile(uri)  # noqa: S606  （交给系统的协议处理器：VS Code）
        return True
    except (AttributeError, OSError):
        return False


def vscode_command(detail: SessionDetail, target: str = "", *, code: str = "code") -> list[str] | None:
    """``code`` 命令的参数：打开 / 聚焦 ``target``（文件夹或工作区文件；空 = 会话的工作目录）。"""
    path = target or detail.cwd
    if not path:
        return None
    args = [code]
    if detail.is_wsl:
        if not detail.distro:
            return None
        args += ["--remote", f"wsl+{detail.distro}"]
    elif "/" in path and ntpath.splitdrive(path)[0]:
        path = path.replace("/", "\\")
    return [*args, path]


def vscode_target(detail: SessionDetail,
                  workspaces: Callable[[], list[OpenWorkspace]] = opened_workspaces) -> str:
    """这个会话的目录正开在哪个窗口里，就返回那个窗口的文件夹 / 工作区文件；都不在返回空。"""
    try:
        owner = owning_workspace(list(workspaces()), detail.cwd, wsl=detail.is_wsl)
    except Exception:  # noqa: BLE001 - VS Code 的记录读坏了只是少一条线索
        log.exception("读取 VS Code 的窗口记录失败")
        return ""
    return owner.target if owner is not None else ""


def open_in_vscode(detail: SessionDetail, target: str = "") -> bool:
    """用 ``code`` 命令打开 / 聚焦一个窗口（标题认不出窗口时的退路）。

    VS Code 按文件夹 / 工作区文件去重：``target`` 正是某个窗口开着的那个时只会聚焦它。
    只给会话的工作目录、而它其实是某个多文件夹工作区的一员时，会**新开**一个窗口——
    所以知道它属于哪个工作区时一定要把工作区文件传进来。"""
    code = shutil.which("code")
    args = vscode_command(detail, target or vscode_target(detail), code=code) if code else None
    if not args:
        return False
    try:
        subprocess.Popen(args, creationflags=_NO_WINDOW,  # noqa: S603
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------- 入口
def jump(detail: SessionDetail, *, wsl_env: dict[str, str] | None = None,
         windows: Callable[[], list[Window]] = list_windows,
         focus: Callable[[int], bool] = focus_window,
         chain: Callable[[int], list[tuple[int, str]]] = process_chain,
         uri: Callable[[str], bool] = open_uri,
         vscode: Callable[..., bool] = open_in_vscode,
         workspaces: Callable[[], list[OpenWorkspace]] = opened_workspaces,
         sleep: Callable[[float], None] = time.sleep) -> JumpResult:
    """跳到这个会话；返回给用户看的一句话结果。阻塞几百毫秒，放后台线程里调。"""
    if sys.platform != "win32" and windows is list_windows:
        return JumpResult(False, t("session_jump.ui.jumping_session_only_works_windows"))
    if detail.alive is False:
        return JumpResult(False, t("session_jump.ui.session_process_gone_reopen_resume"))
    all_windows = windows()
    try:
        known = list(workspaces())
    except Exception:  # noqa: BLE001 - VS Code 的记录读坏了只是少一条线索
        log.exception("读取 VS Code 的窗口记录失败")
        known = []
    if detail.entrypoint == ENTRY_VSCODE:
        return _jump_vscode(detail, all_windows, focus, uri, vscode, sleep, known)
    owner = owning_workspace(known, detail.cwd, wsl=detail.is_wsl)
    return _jump_terminal(detail, all_windows, focus, chain, wsl_env or {}, owner)


def _jump_vscode(detail, all_windows, focus, uri, vscode, sleep, known) -> JumpResult:
    wsl = detail.is_wsl
    owners = owning_workspaces(known, detail.cwd, wsl=wsl)
    recorded = [w for w in session_windows(known, detail.session_id) if w.wsl == wsl]
    if len(recorded) == 1:
        owners = recorded        # VS Code 自己记着它开在这个窗口里：比按路径推断的准
    owner = None
    if owners:      # 按从前到后的层叠顺序收：路径上分不出唯一一个时，几个窗口都是候选
        hits = {w.hwnd for o in owners for w in vscode_candidates(all_windows, detail.cwd, wsl=wsl, owner=o)}
        named = [w for w in all_windows if w.hwnd in hits]
    else:
        named = vscode_candidates(all_windows, detail.cwd, wsl=wsl)
    # 标题对得上的不止一个（同名项目开了几份）或一个都没有（标题里没带名字）：
    # 看哪个窗口的当前标签页正是这个对话。
    pool = named or [w for w in all_windows if w.process in VSCODE_PROCESSES
                     and (" [WSL" in w.title.upper()) == wsl]
    showing = next((w for w in pool if _shows_session(w, detail.title)), None)
    target = None
    if len(named) == 1:
        target = named[0]
    elif showing is not None:
        target = showing
    else:
        narrowed = narrow_by_start(owners, str(detail.extra.get("start_cwd") or ""), wsl=wsl)
        if len(narrowed) == 1:
            # 知道是哪个窗口了。它的标题独一无二就直接调到前台；同名的还有别的窗口（或标题
            # 里没带名字）就留给下面的 code 命令，按确切的文件夹 / 工作区文件去聚焦。
            owner = narrowed[0]
            mine = vscode_candidates(all_windows, detail.cwd, wsl=wsl, owner=owner)
            target = mine[0] if len(mine) == 1 else None
        elif named:
            target = named[0]    # 没有别的线索：取最近用过的那个
    if target is not None:
        if not focus(target.hwnd):
            return JumpResult(False, t("session_jump.ui.could_not_bring_vs_code"))
    elif not owners and known and detail.alive:
        # VS Code 的记录读得到，却没有哪个窗口包含这个目录：活着的会话一定在某个窗口里，
        # 只是认不出——这时去跑 code 命令只会新开一个窗口。
        return JumpResult(False, t("session_jump.ui.could_not_tell_which_vs"))
    elif not vscode(detail, owner.target if owner is not None else ""):
        return JumpResult(False, t("session_jump.ui.no_vs_code_window_has"))
    else:
        sleep(1.2)       # 让 code 命令把窗口聚焦好
    sleep(_URI_DELAY_S)
    if not uri(session_uri(detail.session_id)):
        return JumpResult(True, t("session_jump.ui.switched_vs_code_but_could"))
    return JumpResult(True, t("session_jump.ui.jumped_conversation_vs_code"))


def _jump_terminal(detail, all_windows, focus, chain, wsl_env, owner=None) -> JumpResult:
    if detail.is_wsl:
        target = find_wsl_terminal_window(all_windows, detail, wsl_env, owner)
    else:
        target = (find_host_window(chain(detail.pid), all_windows, detail.cwd,
                                   (detail.title, detail.name))
                  if detail.pid else None)
    if target is None:
        return JumpResult(False, t("session_jump.ui.could_not_find_terminal_window"))
    if not focus(target.hwnd):
        return JumpResult(False, t("session_jump.ui.could_not_bring_terminal_window"))
    if target.process not in VSCODE_PROCESSES:
        return JumpResult(True, t("session_jump.ui.switched_terminal_window_pick_tab"))
    if find_vscode_window([target], detail.cwd, wsl=detail.is_wsl, owner=owner) is None:
        # 终端的工作目录不是任何窗口的工作区：只能挑一个最近用过的 VS Code 窗口
        return JumpResult(True, t("session_jump.ui.switched_vs_code_could_not"))
    return JumpResult(True, t("session_jump.ui.switched_vs_code_terminal_pick"))
