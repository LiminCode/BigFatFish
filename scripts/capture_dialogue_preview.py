# -*- coding: utf-8 -*-
"""「文案风格与模板」的只读预览与「改成我的台词」各渲染一张 PNG：选鲸鱼娘时折叠框里列出那套台词（只读）；
点按钮后切到自定义、可编辑。

用法：``python scripts/capture_dialogue_preview.py <输出目录> [--language zh|en]``。不碰真实数据目录；
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


def _scroll_to(dialog, row_id: str) -> None:
    row = dialog.findChild(SettingRow, f"settingRow_{row_id}")
    area = row.parentWidget()
    while area is not None and not isinstance(area, QScrollArea):
        area = area.parentWidget()
    if area is not None:
        area.verticalScrollBar().setValue(max(0, row.mapTo(area.widget(), QPoint(0, 0)).y() - 24))


def capture(out_dir: Path, language: str) -> list[Path]:
    app = QApplication.instance() or QApplication([])
    out_dir.mkdir(parents=True, exist_ok=True)
    settings_mod.autostart_mod.is_enabled = lambda: False
    config = Config(Path(tempfile.mkdtemp(prefix="bff-preview-cfg-")))
    config.set("ui_language", language)
    config.set("dialogue_mode", "whale_maid")
    i18n.set_language(language)
    dialog = settings_mod.ModernSettingsDialog(config, include_ai=False)
    dialog.resize(1180, 1000)
    dialog.show()
    dialog.select_page("自动化与联动")
    dialog.dialogue_phrases_box.set_expanded(True)
    app.processEvents()
    written = []
    _scroll_to(dialog, "dialogue_mode")
    app.processEvents()
    path = out_dir / f"preview-whale-maid-{language}.png"
    dialog.grab().save(str(path))
    written.append(path)
    dialog._adopt_builtin_phrases(confirm=lambda *_: True)
    app.processEvents()
    _scroll_to(dialog, "dialogue_mode")
    app.processEvents()
    path = out_dir / f"adopted-custom-{language}.png"
    dialog.grab().save(str(path))
    written.append(path)
    dialog.close()
    i18n.set_language("zh")
    return written


if __name__ == "__main__":
    os.environ["APPDATA"] = tempfile.mkdtemp(prefix="bff-capture-")
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    language = "en" if "--language" in sys.argv and sys.argv[sys.argv.index("--language") + 1] == "en" else "zh"
    target = Path(args[0]) if args else Path("docs/screenshots/dialogue-preview-2026-10-18")
    for file in capture(target, language):
        print(file, file.stat().st_size)
