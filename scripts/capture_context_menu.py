# -*- coding: utf-8 -*-
"""把右键菜单（新版模板）和它的「Agent 联动」子菜单在指定界面语言下渲染成 PNG，作为文案改动的证据。

用法：``python scripts/capture_context_menu.py <输出目录> [--language en|zh]``。不碰真实数据目录；
要真实字体请用 ``QT_QPA_PLATFORM=windows`` 跑（offscreen 没有字体，字会是方块）。
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="bff-capture-menu-")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def capture(out_dir: Path, language: str) -> list[Path]:
    import pet.autostart as autostart_mod
    import pet.catalog as catalog_mod
    from pet import claude_hooks
    from pet.sprite_menu_facade import build_sprite_full_menu
    from tests.test_sprite_menu_parity import _make_overlay

    app = QApplication.instance() or QApplication([])
    autostart_mod.is_enabled = lambda: False
    catalog_mod.list_available_characters = lambda: ["shenshen"]
    claude_hooks.wsl_exe = lambda: r"C:\Windows\System32\wsl.exe"
    out_dir.mkdir(parents=True, exist_ok=True)
    shell, _instance, _config = _make_overlay(Path(tempfile.mkdtemp(prefix="bff-menu-cfg-")), template="modern",
                                              values={"ui_language": language})
    menu = build_sprite_full_menu(shell)
    written = []
    menu.popup(QPoint(40, 40))
    for _ in range(5):
        app.processEvents()
    path = out_dir / f"menu-{language}.png"
    menu.grab().save(str(path))
    written.append(path)
    agent = next(action.menu() for action in menu.actions() if action.menu() is not None
                 and action.text() in ("Agent link", "Agent 联动"))
    agent.popup(QPoint(40, 40))
    for _ in range(5):
        app.processEvents()
    path = out_dir / f"menu-agent-link-{language}.png"
    agent.grab().save(str(path))
    written.append(path)
    agent.hide()
    menu.hide()
    shell._delete_runtime_marker()
    return written


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination")
    parser.add_argument("--language", choices=("zh", "en"), default="en")
    args = parser.parse_args()
    for file in capture(Path(args.destination), args.language):
        print(file, file.stat().st_size)
