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
  是工作区文件夹名（默认标题与用户自定义的 ``window.title`` 里只要带 ``rootName`` 都
  满足）；WSL 远程窗口那一段是 ``文件夹名 [WSL: 发行版]``。
- 本机终端会话顺着进程链往上找第一个拥有可见窗口的祖先进程。
- WSL 终端会话的进程链在发行版里，看不到 Windows 这一侧：用它环境变量里的
  ``TERM_PROGRAM`` / ``WT_SESSION`` 判断是 VS Code 终端还是 Windows Terminal。
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Callable

from .claude_session_info import ENTRY_VSCODE, SessionDetail

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


def find_vscode_window(windows: list[Window], cwd: str, *, wsl: bool = False) -> Window | None:
    """标题里有一段正好是这个工作区文件夹名的 VS Code 窗口。

    ``wsl=True`` 只认带 ``[WSL: …]`` 标记的那一段，反之只认不带的——同名项目在
    Windows 和 WSL 各开一份时不会跳错。会话的工作目录可能是工作区的子目录，所以
    逐级往上找，直到盘符 / 根目录。``windows`` 按从前到后的层叠顺序给，同名时取
    最靠前（最近用过）的那个。
    """
    candidates = [w for w in windows if w.process in VSCODE_PROCESSES]
    path = str(cwd or "").rstrip("\\/")
    for _ in range(8):
        name = folder_name(path)
        if not name:
            break
        for window in candidates:
            for segment in _title_segments(window.title):
                base, bracket, _rest = segment.partition(" [")
                is_wsl = bracket != "" and _rest.upper().startswith("WSL")
                remote = bracket != ""
                if base.strip() == name and is_wsl == wsl and (wsl or not remote):
                    return window
        parent = path[:max(path.rfind("\\"), path.rfind("/"))]
        if not parent or parent == path:
            break
        path = parent
    return None


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
                             env: dict[str, str]) -> Window | None:
    """WSL 终端会话的宿主窗口（按它的环境变量猜是哪种终端）。"""
    hints = (detail.title, detail.name, detail.distro)
    if env.get("TERM_PROGRAM") == "vscode":
        return find_vscode_window(windows, detail.cwd, wsl=True)
    terminals = [w for w in windows if w.process in TERMINAL_PROCESSES]
    if env.get("WT_SESSION"):
        terminals = [w for w in terminals if w.process == "windowsterminal.exe"] or terminals
    return (_pick_by_hints(terminals, hints) or (terminals[0] if terminals else None)
            or find_vscode_window(windows, detail.cwd, wsl=True))


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


def open_in_vscode(detail: SessionDetail) -> bool:
    """用 ``code`` 命令打开 / 聚焦工作区（标题认不出窗口时的退路；VS Code 自己去重）。"""
    code = shutil.which("code")
    if not code or not detail.cwd:
        return False
    args = [code]
    if detail.is_wsl:
        if not detail.distro:
            return False
        args += ["--remote", f"wsl+{detail.distro}"]
    args.append(detail.cwd)
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
         vscode: Callable[[SessionDetail], bool] = open_in_vscode,
         sleep: Callable[[float], None] = time.sleep) -> JumpResult:
    """跳到这个会话；返回给用户看的一句话结果。阻塞几百毫秒，放后台线程里调。"""
    if sys.platform != "win32" and windows is list_windows:
        return JumpResult(False, "跳转目前只支持 Windows")
    if detail.alive is False:
        return JumpResult(False, "这个会话的进程已经不在了，可以用恢复命令重新打开")
    all_windows = windows()
    if detail.entrypoint == ENTRY_VSCODE:
        return _jump_vscode(detail, all_windows, focus, uri, vscode, sleep)
    return _jump_terminal(detail, all_windows, focus, chain, wsl_env or {})


def _jump_vscode(detail, all_windows, focus, uri, vscode, sleep) -> JumpResult:
    target = find_vscode_window(all_windows, detail.cwd, wsl=detail.is_wsl)
    if target is not None:
        if not focus(target.hwnd):
            return JumpResult(False, "没能把 VS Code 窗口调到前台")
    elif not vscode(detail):
        return JumpResult(False, "没找到打开着这个项目的 VS Code 窗口")
    else:
        sleep(1.2)       # 让 code 命令把窗口聚焦好
    sleep(_URI_DELAY_S)
    if not uri(session_uri(detail.session_id)):
        return JumpResult(True, "已切到 VS Code，但没能打开那个对话")
    return JumpResult(True, "已跳到 VS Code 里的这个对话")


def _jump_terminal(detail, all_windows, focus, chain, wsl_env) -> JumpResult:
    if detail.is_wsl:
        target = find_wsl_terminal_window(all_windows, detail, wsl_env)
    else:
        target = (find_host_window(chain(detail.pid), all_windows, detail.cwd,
                                   (detail.title, detail.name))
                  if detail.pid else None)
    if target is None:
        return JumpResult(False, "没找到这个会话所在的终端窗口")
    if not focus(target.hwnd):
        return JumpResult(False, "没能把终端窗口调到前台")
    if target.process not in VSCODE_PROCESSES:
        return JumpResult(True, "已切到终端窗口（具体标签页要自己选）")
    if find_vscode_window([target], detail.cwd, wsl=detail.is_wsl) is None:
        # 终端的工作目录不是任何窗口的工作区：只能挑一个最近用过的 VS Code 窗口
        return JumpResult(True, "已切到 VS Code（认不出是哪个窗口的终端，可能不是这一个）")
    return JumpResult(True, "已切到 VS Code 的终端（具体标签页要自己选）")
