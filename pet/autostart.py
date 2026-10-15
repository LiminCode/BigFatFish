# -*- coding: utf-8 -*-
"""
开机自启动管理（跨平台）。

- Windows：HKCU Run 注册表键（无需管理员权限）；
- macOS：LaunchAgents plist（~/Library/LaunchAgents/）；
- Linux：XDG autostart .desktop（~/.config/autostart/）。

设计原则：**系统自启配置是唯一真相**。菜单勾选状态直接查它们，不与 config.json
冗余存储，避免两处状态不同步。

命令按运行形态自适应：
- PyInstaller 打包（sys.frozen）：Windows 自启动先用 `start /D` 切到 exe 所在目录再启动 exe；
  macOS/Linux 指向 .app 内二进制自身 / onedir 内二进制自身；
- 源码运行：Windows 用 `BigFish.exe -m pet`（没生成过启动器时退回 `pythonw -m pet`），
  macOS/Linux 用 `python -m pet`（带工作目录）。
"""

from __future__ import annotations

import os
import re
import shlex
import sys
from pathlib import Path

from .app_identity import APP_NAME
from .config import APP_DIR_BASE, APP_DIR_NAME, LEGACY_APP_DIR_BASE, LEGACY_APP_DIR_NAME

# macOS LaunchAgent 按变体隔离（plist 文件名/Label），避免多版本互覆盖
_APP_BASE_ID = "com.limincode.big-fat-fish"
PLIST_LABEL = (
    _APP_BASE_ID
    if APP_DIR_NAME == APP_DIR_BASE
    else f"{_APP_BASE_ID}.{APP_DIR_NAME}"
)
# Windows 自启注册表值名按变体隔离（如 big-fat-fish-webm-chat）。
# 每个变体只管理自己的值，避免“关无 Chat 版把 Chat 版也关了”。
VALUE_NAME = APP_DIR_NAME
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
# 2026-10-11 改名前（dsh-pet-standalone）本变体用的自启标识：``adopt_legacy_entry`` 把
# 属于本程序的旧项换成新名字，免得开机时新旧两条各启动一次。
_LEGACY_BASE_ID = "com.merzlin.dsh-pet-standalone"
LEGACY_VALUE_NAME = LEGACY_APP_DIR_NAME
LEGACY_PLIST_LABEL = (
    _LEGACY_BASE_ID
    if LEGACY_APP_DIR_NAME == LEGACY_APP_DIR_BASE
    else f"{_LEGACY_BASE_ID}.{LEGACY_APP_DIR_NAME}"
)
_VARIANT_SUFFIXES = ("", "-webm", "-webm-chat", "-gif", "-gif-chat")
# 历史/各变体可能写入过的值名（新旧两个名字）；仅用于启动时清理“指向已不存在路径”的
# 失效项，不影响其他仍有效的变体自启。
KNOWN_VALUE_NAMES = tuple(
    f"{base}{suffix}" for base in (APP_DIR_BASE, LEGACY_APP_DIR_BASE) for suffix in _VARIANT_SUFFIXES
)

_IS_WIN = sys.platform == "win32"
_IS_MAC = sys.platform == "darwin"
_IS_LINUX = sys.platform.startswith("linux")

if _IS_WIN:
    import winreg


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"


def _desktop_path() -> Path:
    """Linux XDG autostart 目录（兼容无 XDG_CONFIG_HOME 的环境）。"""
    base = Path.home() / ".config"
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    if xdg:
        base = Path(xdg)
    return base / "autostart" / f"{PLIST_LABEL}.desktop"


def _linux_desktop_content() -> str:
    """Linux 自启 .desktop 内容；源码运行经 sh 切工作目录，打包运行直接指向二进制。"""
    if getattr(sys, "frozen", False):
        command = f"{shlex.quote(str(Path(sys.executable).resolve()))} --slot 0"
    else:
        root_quoted = shlex.quote(str(_project_root()))
        exe_quoted = shlex.quote(str(sys.executable))
        inner_cmd = f"cd {root_quoted} && exec {exe_quoted} -m pet --slot 0"
        command = f"/bin/sh -c {shlex.quote(inner_cmd)}"
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name=BigFatFish ({APP_DIR_NAME})\n"
        f"Exec={command}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
        "Comment=Desktop pet companion\n"
    )


def _pythonw_path() -> str:
    """Windows 源码运行时，取与 python.exe 同目录的 pythonw.exe（无控制台窗口）。"""
    exe = sys.executable
    if _IS_WIN and exe.lower().endswith("python.exe"):
        return exe[: -len("python.exe")] + "pythonw.exe"
    return exe


def _win_source_program() -> str:
    """Windows 源码运行时自启动要启动的程序。

    优先解释器旁边的 ``BigFish.exe``（``tools/make_launcher.py`` 生成的改名解释器，
    任务管理器 / 任务栏里显示 BigFish 而不是 Python）；没生成过才用 pythonw.exe。
    """
    launcher = Path(sys.executable).parent / f"{APP_NAME}.exe"
    if launcher.is_file():
        return str(launcher)
    return _pythonw_path()


def _win_source_command(program: str) -> str:
    return f'cmd /c start "" /D "{_project_root()}" "{program}" -m pet --slot 0'


def _win_command_is_current(command: str) -> bool:
    """判断 Windows 自启命令是否已是“先切工作目录再启动”的新格式。"""
    return "cmd /c start" in command.lower()


def _win_command_needs_upgrade(command: str) -> bool:
    """已开启的自启命令是不是本程序此前写下的旧写法（需要换成现在的）。

    - 打包运行：旧版直接指向 exe、没切工作目录；
    - 源码运行：本检出此前写的 pythonw.exe 命令，而现在已有 BigFish.exe。只认
      **本检出自己**的那一条——别的检出 / 变体写的命令不是我们的，不动。
    """
    if getattr(sys, "frozen", False):
        return not _win_command_is_current(command)
    legacy = _win_source_command(str(Path(sys.executable).parent / "pythonw.exe")).lower()
    return command.lower() == legacy and _win_command().lower() != legacy


def _iter_known_win_values() -> list[tuple[str, str]]:
    """读取注册表里所有已知的本程序自启值（新旧名字），返回 [(name, command), ...]。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            found = []
            for name in KNOWN_VALUE_NAMES:
                try:
                    command, _ = winreg.QueryValueEx(key, name)
                except FileNotFoundError:
                    continue
                found.append((name, str(command or "")))
            return found
    except OSError:
        return []


def _win_command_target_exists(command: str) -> bool:
    """判断 Windows 自启命令引用的路径是否仍然存在。

    命令格式形如：
      cmd /c start "" /D "C:\\path\\to\\dir" "C:\\path\\to\\app.exe"
    只要任一被引用的非空路径已不存在，就视为失效自启项。
    """
    if not isinstance(command, str) or not command.strip():
        return False
    quoted = re.findall(r'"([^"]*)"', command)
    paths = [item for item in quoted if item.strip()]
    if not paths:
        return True
    return all(Path(item).exists() for item in paths)


def cleanup_stale_entries() -> int:
    """清理指向已不存在路径的失效开机自启项（Windows）。

    用户“更新后直接删除旧目录但忘了关自启”时，HKCU Run 里会残留指向
    已删除路径的命令，导致每次开机弹终端报“找不到文件夹”。这里只删除
    路径已失效的已知本程序自启项，不影响其他仍有效的变体自启。
    """
    if not _IS_WIN:
        return 0
    removed = 0
    try:
        for name, command in _iter_known_win_values():
            if _win_command_target_exists(command):
                continue
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
            ) as key:
                try:
                    winreg.DeleteValue(key, name)
                    removed += 1
                except FileNotFoundError:
                    pass
    except OSError:
        pass
    return removed


def _win_command_is_ours(command: str) -> bool:
    """这条自启命令是不是本程序（这份检出 / 这个安装目录）写的。"""
    anchor = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else _project_root()
    return str(anchor).lower() in str(command or "").lower()


def adopt_legacy_entry() -> bool:
    """把改名前写下的自启项换成新名字；返回是否处理了一条旧项。

    只认属于本程序的旧项（Windows 看命令里的目录；macOS / Linux 的旧文件名本身就按变体
    区分）。新项已经在时不覆盖它，只把旧的那条删掉。
    """
    if _IS_WIN:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                try:
                    legacy, _ = winreg.QueryValueEx(key, LEGACY_VALUE_NAME)
                except FileNotFoundError:
                    return False
                if not _win_command_is_ours(str(legacy or "")):
                    return False
                try:
                    winreg.QueryValueEx(key, VALUE_NAME)
                    has_new = True
                except FileNotFoundError:
                    has_new = False
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                if not has_new:
                    winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _win_command())
                winreg.DeleteValue(key, LEGACY_VALUE_NAME)
            return True
        except OSError:
            return False
    if _IS_MAC or _IS_LINUX:
        current = _plist_path() if _IS_MAC else _desktop_path()
        legacy_path = current.with_name(current.name.replace(PLIST_LABEL, LEGACY_PLIST_LABEL))
        if legacy_path == current or not legacy_path.exists():
            return False
        if not current.exists() and not enable():
            return False
        try:
            legacy_path.unlink()
        except OSError:
            return False
        return True
    return False


def is_enabled() -> bool:
    """当前变体是否已注册开机自启（只查当前变体自己的注册表值）。"""
    if not _IS_WIN:
        adopt_legacy_entry()
    if _IS_WIN:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                command, _ = winreg.QueryValueEx(key, VALUE_NAME)
                # 兼容旧版：已开启但仍是旧命令时自动升级为新命令——打包版避免开机自启
                # 因 CWD 不可写而解压失败，源码版换成 BigFish.exe（见上）。
                if isinstance(command, str) and _win_command_needs_upgrade(command):
                    try:
                        with winreg.OpenKey(
                            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
                        ) as write_key:
                            winreg.SetValueEx(
                                write_key, VALUE_NAME, 0, winreg.REG_SZ, _win_command()
                            )
                    except OSError:
                        # 只读场景（如权限异常）不强求升级，仍视为已启用
                        pass
                return True
        except FileNotFoundError:
            # 只认当前变体自己的值；其他变体的自启状态互不影响。
            # 例外：改名前本程序自己写的那一条，换成新名字后算作已开启。
            return adopt_legacy_entry()
    if _IS_MAC:
        return _plist_path().exists()
    if _IS_LINUX:
        path = _desktop_path()
        # 兼容手动删除或 DE 禁用：文件存在即视为已开启（与 macOS 同策略）
        return path.exists()
    return False


def _win_command() -> str:
    if getattr(sys, "frozen", False):
        # onefile 的 runtime_tmpdir="." 是相对“当前工作目录”解析的；
        # 开机自启（HKCU Run）默认工作目录可能是 System32 等不可写目录。
        # 用 start 先切到 exe 所在目录再启动 exe，既保证解压目录在 exe 同目录，
        # 又不会让 cmd 窗口一直等待肥鱼退出。开机自启固定指定 --slot 0。
        exe = Path(sys.executable).resolve()
        return f'cmd /c start "" /D "{exe.parent}" "{exe}" --slot 0'
    return _win_source_command(_win_source_program())


def _mac_program_args() -> list[str]:
    if getattr(sys, "frozen", False):
        # .app 内二进制路径，直接作为 LaunchAgent 程序运行
        return [str(sys.executable), "--slot", "0"]
    return [sys.executable, "-m", "pet", "--slot", "0"]


def enable() -> bool:
    """开启自启；返回是否写入成功（Windows 回读注册表验证，macOS 验证 plist 存在，Linux 验证 .desktop 存在）。"""
    if _IS_WIN:
        try:
            # 只写当前变体自己的值，不影响其他 Chat/无 Chat 变体的自启状态。
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _win_command())
            # 回读验证，防止写入被安全软件/策略静默拦截
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(value)
        except OSError:
            return False
    elif _IS_MAC:
        import plistlib

        try:
            _plist_path().parent.mkdir(parents=True, exist_ok=True)
            plist: dict = {
                "Label": PLIST_LABEL,
                "ProgramArguments": _mac_program_args(),
                "RunAtLoad": True,
            }
            if not getattr(sys, "frozen", False):
                plist["WorkingDirectory"] = str(_project_root())
            with _plist_path().open("wb") as f:
                plistlib.dump(plist, f)
            return _plist_path().exists()
        except OSError:
            return False
    elif _IS_LINUX:
        try:
            path = _desktop_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_linux_desktop_content(), encoding="utf-8")
            return path.exists()
        except OSError:
            return False
    return False


def disable() -> bool:
    """关闭自启；返回是否已清除。"""
    if _IS_WIN:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                try:
                    winreg.DeleteValue(key, VALUE_NAME)
                except FileNotFoundError:
                    pass
            return True
        except OSError:
            return False
    elif _IS_MAC:
        try:
            _plist_path().unlink(missing_ok=True)
            return True
        except OSError:
            return False
    elif _IS_LINUX:
        try:
            _desktop_path().unlink(missing_ok=True)
            return True
        except OSError:
            return False
    return True


def set_enabled(on: bool) -> bool:
    return enable() if on else disable()
