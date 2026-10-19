# -*- coding: utf-8 -*-
"""把 AI 对话窗（新版）与快速对话气泡按指定语言渲染成 PNG，作为英文化的证据。

用法：``python scripts/capture_chat_window.py <输出目录> [--language zh|en]``。不碰真实数据目录、不调模型。
要看真实字体用 ``QT_QPA_PLATFORM=windows``。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pet import i18n  # noqa: E402
from pet.chat.widgets import ChatWindow  # noqa: E402
from pet.config import Config  # noqa: E402


def capture(out_dir: Path, language: str) -> list[Path]:
    app = QApplication.instance() or QApplication([])
    out_dir.mkdir(parents=True, exist_ok=True)
    config = Config(Path(tempfile.mkdtemp(prefix="bff-chat-cfg-")))
    config.set("ui_language", language)
    i18n.set_language(language)
    window = ChatWindow(config, "shenshen")
    window.resize(980, 700)
    window.show()
    app.processEvents()
    path = out_dir / f"chat-window-{language}.png"
    window.grab().save(str(path))
    window.close()
    i18n.set_language("zh")
    return [path]


if __name__ == "__main__":
    os.environ["APPDATA"] = tempfile.mkdtemp(prefix="bff-capture-")
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    language = "en" if "--language" in sys.argv and sys.argv[sys.argv.index("--language") + 1] == "en" else "zh"
    target = Path(args[0]) if args else Path("docs/screenshots/chat-english-2026-10-19")
    for file in capture(target, language):
        print(file, file.stat().st_size)
