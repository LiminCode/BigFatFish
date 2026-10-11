# -*- coding: utf-8 -*-
"""程序在系统里的身份：名字（BigFish）与图标。

三处会显示它，各有各的来源：

- **任务栏按钮 / Alt-Tab**：图标取窗口图标（``apply_app_icon``）；归到哪个应用下
  由「应用用户模型 ID」决定（``set_process_identity``）——不设的话，从源码运行的
  桌宠窗口会和所有别的 Python 程序归成一组，用 Python 的图标。
- **任务管理器的进程名**：取 exe 的版本资源，程序自己改不了。从源码运行时由
  ``tools/make_launcher.py`` 生成的 ``BigFish.exe`` 解决；打包版本来就是自己的 exe。
- **托盘图标**：鱼的当前帧，另有来源，不归这里管。

主进程与设置页独立进程都调这两个函数，所以它们在任务栏上是同一个应用。本模块
不导入素材库等重模块——设置进程的模块集合必须保持精简。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

APP_NAME = "BigFish"
#: Windows 的应用用户模型 ID（任务栏按它分组）。改了它，用户钉在任务栏上的旧图标会失效。
APP_USER_MODEL_ID = "BigFish.DesktopPet"

_INTERPRETER_NAMES = frozenset({"python.exe", "pythonw.exe", "python", "python3"})


def set_process_identity() -> bool:
    """声明本进程属于 BigFish（要在创建任何窗口之前调）。非 Windows 无事可做。"""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        result = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            ctypes.c_wchar_p(APP_USER_MODEL_ID))
        return result == 0
    except (AttributeError, OSError):
        logging.debug("设置应用用户模型 ID 失败", exc_info=True)
        return False


def icon_path() -> Path | None:
    """应用图标文件（源码运行与带资源的打包布局都在 ``assets/icon.ico``）；没有返回 None。"""
    roots = [Path(__file__).resolve().parent.parent]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.insert(0, Path(meipass))
    for root in roots:
        candidate = root / "assets" / "icon.ico"
        if candidate.is_file():
            return candidate
    return None


def app_icon():
    """应用图标：先找图标文件；没有就取本程序 exe 里嵌的那个（解释器的图标不算）。"""
    from PySide6.QtGui import QIcon

    path = icon_path()
    if path is not None:
        return QIcon(str(path))
    exe = Path(sys.executable or "")
    if exe.name.lower() in _INTERPRETER_NAMES or not exe.is_file():
        return QIcon()
    from PySide6.QtCore import QFileInfo
    from PySide6.QtWidgets import QFileIconProvider

    return QFileIconProvider().icon(QFileInfo(str(exe)))


def apply_app_icon(app) -> bool:
    """给这个 QApplication 的所有窗口一个默认图标（任务栏 / Alt-Tab / 标题栏）。

    图标只是门面：任何一步出错都只记一笔，绝不挡住启动。
    """
    try:
        icon = app_icon()
        if icon.isNull():
            return False
        app.setWindowIcon(icon)
        return True
    except Exception:
        logging.debug("设置应用图标失败", exc_info=True)
        return False
