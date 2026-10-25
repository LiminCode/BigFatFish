# -*- coding: utf-8 -*-
"""把设置页「语音 → 语音报时 → 台词/歌词」一节（内置库编辑框 + 自定义追加）渲染成 PNG（中 / 英）。

用法：``python scripts/capture_voice_chime_quotes.py <输出目录> [--language zh|en]``。不碰真实数据目录；
要看真实字体用 ``QT_QPA_PLATFORM=windows``。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication, QScrollArea  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pet import i18n, modern_settings_dialog as settings_mod  # noqa: E402
from pet.config import Config  # noqa: E402
from pet.settings_widgets import SettingRow  # noqa: E402


def capture(out_dir: Path, language: str) -> list[Path]:
    app = QApplication.instance() or QApplication([])
    out_dir.mkdir(parents=True, exist_ok=True)
    settings_mod.autostart_mod.is_enabled = lambda: False
    config = Config(Path(tempfile.mkdtemp(prefix="bff-chime-cfg-")))
    config.set("ui_language", language)
    config.set("voice_chime_enabled", True)
    config.set("voice_chime_custom_quotes_zh", "又是元气满满的一天～\n该起来喝口水、动一动啦。")
    config.set("voice_chime_custom_quotes_en", "Take a short break and stretch.")
    i18n.set_language(language)
    dialog = settings_mod.ModernSettingsDialog(config, include_ai=False)
    dialog.resize(1180, 1250)
    dialog.show()
    row = dialog.findChild(SettingRow, "settingRow_voice_chime_builtin_quotes_zh")
    for index in range(dialog.sidebar.count()):
        dialog.sidebar.setCurrentRow(index)
        app.processEvents()
        if row.isVisibleTo(dialog) and row.visibleRegion().isEmpty() is False:
            break
    area = row.parentWidget()
    while area is not None and not isinstance(area, QScrollArea):
        area = area.parentWidget()
    if area is not None:
        area.verticalScrollBar().setValue(max(0, row.mapTo(area.widget(), QPoint(0, 0)).y() - 48))
    app.processEvents()
    path = out_dir / f"voice-chime-quotes-{language}.png"
    dialog.grab().save(str(path))
    dialog.close()
    i18n.set_language("zh")
    return [path]


if __name__ == "__main__":
    os.environ["APPDATA"] = tempfile.mkdtemp(prefix="bff-capture-")
    os.environ["USERPROFILE"] = "C:\\Users\\me"     # 默认目录里别带本机用户名（截图进公开仓库）
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    language = "en" if "--language" in sys.argv and sys.argv[sys.argv.index("--language") + 1] == "en" else "zh"
    target = Path(args[0]) if args else Path("docs/screenshots/voice-chime-quotes-2026-10-21")
    for file in capture(target, language):
        print(file, file.stat().st_size)
