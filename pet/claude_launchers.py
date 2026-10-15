# -*- coding: utf-8 -*-
"""右键菜单两条「全功能 Claude」入口的纯逻辑（零 Qt）：找程序、拼命令行、拉起。

肥鱼自己的聊天走个人 key，只有本地知识库 / GitHub 两类只读工具；想要文件、命令、
另一个账号的连接器这些能力，得去 Claude Desktop 或 WSL 里的 Claude Code。这里只负责
「一键拉起」，不往里送任何内容。

- **Claude Desktop**：老式安装器装在 ``%LOCALAPPDATA%\\AnthropicClaude\\claude.exe``；
  商店版（MSIX）没有可直接执行的路径，用 ``shell:AppsFolder\\<家族名>!Claude`` 交给
  ShellExecute。包名从注册表的包仓库里找（``AppModel\\Repository\\Packages`` 下的子键，
  本机实测枚举一次不到几毫秒），不起 PowerShell。
- **Claude Code（WSL）**：照「最近的对话 → 在终端里继续」那条命令（
  ``claude_session_history.terminal_resume_argv``）：Windows Terminal 新开一个发行版标签，
  ``--cd ~/workspace`` 进用户选定的工作目录，登录 shell 起 ``claude``（PATH 才齐），退出后留在 shell 里。
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from typing import Callable

from . import claude_hooks
from .vscode_workspaces import wsl_distros

log = logging.getLogger(__name__)

#: 商店版包名前缀与应用 id（``AppxManifest.xml`` 里 ``<Application Id="Claude">``）
STORE_PACKAGE_PREFIX = "Claude_"
STORE_APP_ID = "Claude"
_PACKAGES_KEY = (r"Software\Classes\Local Settings\Software\Microsoft\Windows"
                 r"\CurrentVersion\AppModel\Repository\Packages")


# ---------------------------------------------------------------- Claude Desktop
def _classic_exe() -> str:
    base = os.environ.get("LOCALAPPDATA", "")
    if not base:
        return ""
    path = os.path.join(base, "AnthropicClaude", "claude.exe")
    return path if os.path.isfile(path) else ""


def _registry_packages() -> list[str]:
    """包仓库里的全部包全名（``名字_版本_架构__发布者``）；不是 Windows / 读不到返回空。"""
    if sys.platform != "win32":
        return []
    try:
        import winreg

        found = []
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _PACKAGES_KEY) as root:
            index = 0
            while True:
                try:
                    found.append(winreg.EnumKey(root, index))
                except OSError:
                    break
                index += 1
        return found
    except (OSError, ValueError, TypeError):
        return []


def _family_name(package: str) -> str:
    """``Claude_2.37337.1.0_x64__pzs8sxrjxfjjc`` → ``Claude_pzs8sxrjxfjjc``；认不出返回空。"""
    name, sep, publisher = package.rpartition("__")
    if not sep or not publisher or not name.startswith(STORE_PACKAGE_PREFIX):
        return ""
    base = name.split("_", 1)[0]
    return f"{base}_{publisher}" if base == STORE_PACKAGE_PREFIX[:-1] else ""


def claude_desktop_target(*, enumerate_packages: Callable[[], list[str]] | None = None) -> str:
    """交给 ``os.startfile`` 的目标：老式安装器的 exe 路径，或商店版的 ``shell:AppsFolder\\…``；没装返回空。"""
    exe = _classic_exe()
    if exe:
        return exe
    for package in (enumerate_packages or _registry_packages)():
        family = _family_name(str(package or ""))
        if family:
            return f"shell:AppsFolder\\{family}!{STORE_APP_ID}"
    return ""


def launch_claude_desktop(target: str) -> bool:
    try:
        os.startfile(target)  # noqa: S606  （ShellExecute：exe 路径或 shell:AppsFolder\…）
        return True
    except (AttributeError, OSError):
        log.warning("启动 Claude Desktop 失败：%s", target, exc_info=True)
        return False


# ---------------------------------------------------------------- Claude Code（WSL）
#: 新会话开在哪个目录（``wsl.exe --cd`` 认 ``~/…``）。不用家目录：Claude Code 的「信任此文件夹」
#: 按目录记，信任整个家目录等于放开家目录里的一切；``~/workspace`` 是用户 2026-10-15 选定的、
#: 已经信任过的目录，点开直接进对话。
WSL_START_DIR = "~/workspace"
#: 登录 shell 里跑的那一行：起 claude，退出后留在 shell 里
NEW_SESSION_SCRIPT = "claude; exec bash"


def wt_script(script: str) -> str:
    r"""交给 Windows Terminal 的 shell 脚本：分号要写成 ``\;``。

    ``wt`` 把参数里的 ``;`` 当成它自己的子命令分隔符——哪怕在引号里——
    ``claude; exec bash`` 会被劈成两个标签，第二个拿着 ``exec bash`` 报 0x80070002
    （2026-10-15 用户实机截图）。``\;`` 经 wt 还原成 ``;`` 再交给 wsl.exe（本机实测：
    ``bash -lic "touch /tmp/x\; exit"`` 只建了 ``/tmp/x``）。``cmd /c start`` 那条路
    不经 wt，不能转义。"""
    return script.replace(";", "\\;")


def wsl_claude_argv(*, which: Callable[[str], str | None] = shutil.which,
                    wsl: str | None = None, distro: str | None = None) -> list[str] | None:
    """在 ``WSL_START_DIR`` 开一个终端并起一个新的 ``claude`` 会话的命令行；没有 WSL 返回 None。

    ``distro``：None = 本机默认发行版（``wsl_distros()`` 第一项），空串 = 不指定（由 wsl.exe 选）。
    """
    wsl_path = claude_hooks.wsl_exe() if wsl is None else wsl
    if not wsl_path:
        return None
    if distro is None:
        distro = next(iter(wsl_distros()), "")
    inner = [wsl_path, *(["-d", distro] if distro else []), "--cd", WSL_START_DIR, "--", "bash", "-lic"]
    terminal = which("wt")
    if terminal:
        # ``-w new``：一定开新窗口（不往用户已开的窗口里塞标签），新窗口才好由 fit_new_window 摆位
        return [terminal, "-w", "new", *inner, wt_script(NEW_SESSION_SCRIPT)]
    return ["cmd", "/c", "start", "", *inner, NEW_SESSION_SCRIPT]


#: Windows Terminal 顶层窗口的类名（新旧版本都是它）
_TERMINAL_WINDOW_CLASS = "CASCADIA_HOSTING_WINDOW_CLASS"
_SPI_GETWORKAREA = 0x30
_SWP_NOZORDER, _SWP_NOACTIVATE = 0x0004, 0x0010
#: 等新窗口出现的预算与轮询间隔（本机实测 0.06 s 就有了）
FIT_TIMEOUT_S = 8.0
FIT_INTERVAL_S = 0.05

Rect = tuple[int, int, int, int]  # x, y, w, h


def terminal_windows() -> set[int]:
    """当前所有 Windows Terminal 顶层窗口的句柄（含还没显示的）；不是 Windows 返回空集。"""
    if sys.platform != "win32":
        return set()
    import ctypes
    import ctypes.wintypes as wt

    user32 = ctypes.windll.user32
    found: set[int] = set()
    buf = ctypes.create_unicode_buffer(64)

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def visit(hwnd, _lparam):
        user32.GetClassNameW(hwnd, buf, 64)
        if buf.value == _TERMINAL_WINDOW_CLASS:
            found.add(int(hwnd))
        return True

    user32.EnumWindows(visit, 0)
    return found


def primary_work_area() -> Rect | None:
    """主屏去掉任务栏后的区域（本进程的像素口径，和 ``SetWindowPos`` 一致）；不是 Windows 返回 None。"""
    if sys.platform != "win32":
        return None
    import ctypes
    import ctypes.wintypes as wt

    rect = wt.RECT()
    if not ctypes.windll.user32.SystemParametersInfoW(_SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
        return None
    return (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)


def left_half(work_area: Rect) -> Rect:
    x, y, w, h = work_area
    return (x, y, w // 2, h)


def move_window(hwnd: int, rect: Rect) -> bool:
    if sys.platform != "win32":
        return False
    import ctypes

    x, y, w, h = rect
    return bool(ctypes.windll.user32.SetWindowPos(hwnd, 0, x, y, w, h, _SWP_NOZORDER | _SWP_NOACTIVATE))


def is_window_visible(hwnd: int) -> bool:
    if sys.platform != "win32":
        return False
    import ctypes

    return bool(ctypes.windll.user32.IsWindowVisible(hwnd))


def window_rect(hwnd: int) -> Rect | None:
    if sys.platform != "win32":
        return None
    import ctypes
    import ctypes.wintypes as wt

    rect = wt.RECT()
    if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)


#: 摆完等多久再核对、最多摆几次（终端显示窗口时会再套一次自己记的尺寸）
FIT_SETTLE_S = 0.3
FIT_ATTEMPTS = 3


def fit_new_window(before: set[int], *, windows: Callable[[], set[int]] = terminal_windows,
                   visible: Callable[[int], bool] = is_window_visible,
                   rect_of: Callable[[int], Rect | None] = window_rect,
                   work_area: Callable[[], Rect | None] = primary_work_area,
                   move: Callable[[int, Rect], bool] = move_window,
                   sleep: Callable[[float], None] = time.sleep,
                   clock: Callable[[], float] = time.monotonic,
                   timeout: float = FIT_TIMEOUT_S, interval: float = FIT_INTERVAL_S,
                   settle: float = FIT_SETTLE_S, attempts: int = FIT_ATTEMPTS) -> bool:
    """等 ``before`` 之外第一个**显示出来**的终端窗口，把它摆到主屏左半边；超时 / 做不到返回 False。

    Windows Terminal 自己开的窗口尺寸不稳：本机（125% 缩放）有时是 ``initialCols/initialRows``
    算出来的 2039×2280（比 1540 高的工作区还高，用户 2026-10-15 反馈），有时是它记住的上一个
    窗口的尺寸。``wt --size`` 以字符格数计，换算要知道字体像素，不稳；所以在窗口出现后直接
    ``SetWindowPos``。实测窗口 0.1 s 内就能枚举到、0.2 s 显示；**显示前**摆的位置会被它显示时
    再套一次尺寸盖掉（2026-10-15 集成验证撞到），所以等它显示了再摆，摆完 ``settle`` 秒后核对，
    不对就再摆，最多 ``attempts`` 次。在后台线程跑，不碰 Qt。"""
    area = work_area()
    if area is None:
        return False
    target = left_half(area)
    deadline = clock() + timeout
    while True:
        shown = sorted(hwnd for hwnd in windows() - before if visible(hwnd))
        if shown:
            hwnd = shown[0]
            break
        if clock() >= deadline:
            log.warning("Claude Code（WSL）：%.0f 秒内没等到新的终端窗口，窗口大小由终端自己定", timeout)
            return False
        sleep(interval)
    for _attempt in range(attempts):
        if not move(hwnd, target):
            log.warning("Claude Code（WSL）：终端窗口 %s 摆位失败", hwnd)
            return False
        sleep(settle)
        if rect_of(hwnd) == target:
            return True
    log.warning("Claude Code（WSL）：终端窗口 %s 摆了 %d 次都被改回去，随它", hwnd, attempts)
    return False


def _is_windows_terminal(argv: list[str]) -> bool:
    return bool(argv) and os.path.basename(str(argv[0])).lower().split(".")[0] == "wt"


def launch_wsl_claude(argv: list[str], *, popen: Callable = subprocess.Popen,
                      fit: Callable[[set[int]], bool] = fit_new_window) -> bool:
    """拉起终端；是 Windows Terminal 的话再在后台把新窗口摆到主屏左半边（``fit_new_window``）。"""
    via_terminal = _is_windows_terminal(argv)
    before = terminal_windows() if via_terminal else set()
    try:
        popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,  # noqa: S603
              stderr=subprocess.DEVNULL, close_fds=True)
    except OSError:
        log.warning("启动 WSL 里的 Claude Code 失败：%s", argv[:1], exc_info=True)
        return False
    if via_terminal:
        threading.Thread(target=fit, args=(before,), name="bff-fit-terminal", daemon=True).start()
    return True
