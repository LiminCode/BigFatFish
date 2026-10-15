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
  ``--cd ~`` 进家目录，登录 shell 起 ``claude``（PATH 才齐），退出后留在 shell 里。
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
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
    """在家目录开一个终端并起一个新的 ``claude`` 会话的命令行；没有 WSL 返回 None。

    ``distro``：None = 本机默认发行版（``wsl_distros()`` 第一项），空串 = 不指定（由 wsl.exe 选）。
    """
    wsl_path = claude_hooks.wsl_exe() if wsl is None else wsl
    if not wsl_path:
        return None
    if distro is None:
        distro = next(iter(wsl_distros()), "")
    inner = [wsl_path, *(["-d", distro] if distro else []), "--cd", "~", "--", "bash", "-lic"]
    terminal = which("wt")
    if terminal:
        return [terminal, *inner, wt_script(NEW_SESSION_SCRIPT)]
    return ["cmd", "/c", "start", "", *inner, NEW_SESSION_SCRIPT]


def launch_wsl_claude(argv: list[str]) -> bool:
    try:
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,  # noqa: S603
                         stderr=subprocess.DEVNULL, close_fds=True)
        return True
    except OSError:
        log.warning("启动 WSL 里的 Claude Code 失败：%s", argv[:1], exc_info=True)
        return False
