# -*- coding: utf-8 -*-
"""肥鱼身上的文字用哪种字体：气泡、对话气泡、会话详情卡、头顶的常驻标签。

统一用**等线**（DengXian，Windows 10/11 与 Office 自带）。没装它的机器退回各平台的
中文 UI 字体（Windows：微软雅黑 UI；macOS：苹方）；再没有就不点名，沿用 Qt 默认。

两条约束，都来自 ``context_menus/menu_styles/common.py`` 记录的那次实测：

- 只给**单个字体族**。Windows 上给 Qt 一个多族列表，它会为挑字形把整个字体库
  （五百多个文件、八百多 MB）映射进进程。
- 判断「装没装」只看字体文件在不在，不调 ``QFontDatabase``——枚举字体族本身就要
  十几 MB。

内存（2026-10-11 实测，Qt 6.11 / Windows 11，逐句量 RSS）：等线与微软雅黑 UI 画
「中文 + 英文」都是 +1MB；遇到字体里没有的字形（假名、✳ 这类符号）两者同样一次性
+51MB。Qt 默认的 Segoe UI 不含中文，画第一句中文就 +51MB——所以点名一个含中文的
字体只会更省。
"""
from __future__ import annotations

import functools
import os
import sys
from pathlib import Path

#: 首选：等线。族名用英文名，中文系统与英文系统都认。
PREFERRED_FAMILY = "DengXian"
_PREFERRED_FILES = ("Deng.ttf", "Dengb.ttf", "Dengl.ttf")
#: 没装等线时各平台的退路
_FALLBACK_FAMILY = {"win32": "Microsoft YaHei UI", "darwin": "PingFang SC"}


def _windows_font_dirs() -> list[Path]:
    dirs = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")   # 「仅为我安装」的字体
    return dirs


def _preferred_installed() -> bool:
    if sys.platform != "win32":
        return False
    for directory in _windows_font_dirs():
        try:
            if any((directory / name).is_file() for name in _PREFERRED_FILES):
                return True
        except OSError:
            continue
    return False


@functools.lru_cache(maxsize=1)
def bubble_font_family() -> str:
    """气泡类文字的字体族名；空串 = 不点名（沿用 Qt 默认字体）。"""
    if _preferred_installed():
        return PREFERRED_FAMILY
    return _FALLBACK_FAMILY.get(sys.platform, "")


def font_css() -> str:
    """样式表片段（``font-family: "…"; `` 或空串），拼在 ``font-size`` 旁边用。"""
    family = bubble_font_family()
    return f'font-family: "{family}"; ' if family else ""


def apply_family(widget) -> None:
    """把控件（及此后创建的子控件）的字体族换成气泡字体；字号等其余属性不动。"""
    family = bubble_font_family()
    if not family:
        return
    font = widget.font()
    font.setFamily(family)
    widget.setFont(font)
