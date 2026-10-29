# -*- coding: utf-8 -*-
"""会话「从哪开的」的图标：优先用本机装着的那个程序自己的图标，没有就用手绘的单色记号。

- ``vscode`` → VS Code 的 ``Code.exe``（用户目录安装 / 系统安装 / ``code`` 命令所在处）
- ``desktop`` → Claude 桌面版的 ``claude.exe``：商店版装在 ``WindowsApps`` 下（那个目录列不出来，
  安装位置从注册表的应用包仓库里查），老的独立安装版在 ``%LOCALAPPDATA%`` 下的 ``AnthropicClaude`` 里
- ``terminal`` → PowerShell（7 的 ``pwsh.exe``，没有就系统自带的 ``powershell.exe``）
- ``wsl`` → ``wsl.exe``（企鹅）
- ``script`` → 没有对应程序，直接用手绘记号

图标由 Windows 的外壳给（``QFileIconProvider``），第一次取要几毫秒，按 (种类, 尺寸, 缩放)
缓存。``WindowsApps`` 下的执行别名（``wt.exe`` / ``pwsh.exe`` 那种）给出来的是通用的程序
图标，不是本尊，所以不在候选里（2026-10-14 实测）。非 Windows 一律用手绘记号。
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Callable

from PySide6.QtGui import QIcon

#: 手绘记号（``context_menus.icons`` 里的名字）
FALLBACK_GLYPHS = {"vscode": "vscode", "desktop": "sparkle", "terminal": "terminal", "wsl": "ubuntu",
                   "script": "automation"}
#: 商店版 Claude 桌面版的包名前缀与发布者后缀（``Claude_<版本>_x64__pzs8sxrjxfjjc``）
_DESKTOP_PACKAGE = ("Claude_", "__pzs8sxrjxfjjc")
_PACKAGE_REPOSITORY = (r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion"
                       r"\AppModel\Repository\Packages")
_CACHE: dict[tuple[str, int, float], QIcon] = {}


def _env(name: str) -> str:
    return os.environ.get(name, "")


def _candidates(kind: str) -> list[str]:
    system_root = _env("SystemRoot") or r"C:\Windows"
    if kind == "vscode":
        found = []
        code = shutil.which("code")
        if code:
            # code.cmd 在 <安装目录>\bin\ 下；Code.exe 在安装目录
            found.append(str(Path(code).resolve().parent.parent / "Code.exe"))
        found += [os.path.join(_env("LOCALAPPDATA"), "Programs", "Microsoft VS Code", "Code.exe"),
                  os.path.join(_env("ProgramFiles"), "Microsoft VS Code", "Code.exe")]
        return found
    if kind == "desktop":
        found = [os.path.join(root, "app", "claude.exe") for root in _desktop_package_roots()]
        return found + [os.path.join(_env("LOCALAPPDATA"), "AnthropicClaude", "claude.exe")]
    if kind == "terminal":
        return [os.path.join(_env("ProgramFiles"), "PowerShell", "7", "pwsh.exe"),
                os.path.join(system_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")]
    if kind == "wsl":
        return [os.path.join(system_root, "System32", "wsl.exe")]
    return []


def _desktop_package_roots() -> list[str]:
    """商店版 Claude 桌面版装在哪（新版本在前）；读不到注册表就是空。"""
    try:
        import winreg
    except ImportError:
        return []
    prefix, publisher = _DESKTOP_PACKAGE
    roots: list[tuple[str, str]] = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _PACKAGE_REPOSITORY) as packages:
            index = 0
            while True:
                try:
                    name = winreg.EnumKey(packages, index)
                except OSError:
                    break
                index += 1
                if not (name.startswith(prefix) and name.endswith(publisher)):
                    continue
                try:
                    with winreg.OpenKey(packages, name) as package:
                        root, _kind = winreg.QueryValueEx(package, "PackageRootFolder")
                except OSError:
                    continue
                roots.append((name, str(root)))
    except OSError:
        return []
    return [root for _name, root in sorted(roots, reverse=True)]


def host_executable(kind: str, *, exists: Callable[[str], bool] = os.path.isfile) -> str:
    """这一类来源对应的程序；找不到返回空。"""
    if sys.platform != "win32":
        return ""
    for path in _candidates(kind):
        if path and exists(path):
            return path
    return ""


def _shell_icon(path: str) -> QIcon:
    from PySide6.QtCore import QFileInfo
    from PySide6.QtWidgets import QFileIconProvider

    return QFileIconProvider().icon(QFileInfo(path))


def host_icon(widget, kind: str, size: int, *, executable: Callable[[str], str] | None = None,
              provider: Callable[[str], QIcon] | None = None) -> QIcon:
    """``kind`` 的图标，按 ``size``（逻辑像素）裁好；不认识的种类返回空图标。"""
    from .context_menus.icons import vector_widget_icon
    from .context_menus.quick_launch import fitted_application_icon

    glyph = FALLBACK_GLYPHS.get(kind)
    if not glyph:
        return QIcon()
    dpr = float(widget.devicePixelRatioF() or 1.0)
    key = (kind, int(size), dpr)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    icon = QIcon()
    path = (executable or host_executable)(kind)      # 调用时才取默认：测试里替换模块级函数要生效
    if path:
        try:
            icon = (provider or _shell_icon)(path)
        except Exception:  # noqa: BLE001 - 外壳取图失败就退回手绘记号
            icon = QIcon()
    if not icon.isNull():
        icon = fitted_application_icon(icon, size, widget)
    else:
        icon = vector_widget_icon(widget, glyph, size)
    _CACHE[key] = icon
    return icon


def warm(widget, size: int, **overrides) -> int:
    """启动后预热：把几种来源的图标先取好。VS Code 那个第一次要外壳解包 150 ms（2026-10-14
    实测），放在第一次展开卡片时做会卡一下。返回这次真取了几个。"""
    before = len(_CACHE)
    for kind in FALLBACK_GLYPHS:
        host_icon(widget, kind, size, **overrides)
    return len(_CACHE) - before


def clear_cache() -> None:
    _CACHE.clear()
