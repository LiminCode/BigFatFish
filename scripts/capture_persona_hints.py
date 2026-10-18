# -*- coding: utf-8 -*-
"""把「AI 与对话 → 人设与回复」和「自动化与联动 → 文案风格与模板」两处连同展开的说明节各渲染一张 PNG。

用法：``python scripts/capture_persona_hints.py <输出目录> [--language zh|en]``。不碰真实数据目录；
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
from pet.settings_widgets import SettingRow, SettingsSection  # noqa: E402


def _scroll_area(widget):
    parent = widget.parentWidget()
    while parent is not None and not isinstance(parent, QScrollArea):
        parent = parent.parentWidget()
    return parent


def _section_of(row):
    parent = row.parentWidget()
    while parent is not None and not isinstance(parent, SettingsSection):
        parent = parent.parentWidget()
    return parent


def capture(out_dir: Path, language: str) -> list[Path]:
    app = QApplication.instance() or QApplication([])
    out_dir.mkdir(parents=True, exist_ok=True)
    settings_mod.autostart_mod.is_enabled = lambda: False
    config = Config(Path(tempfile.mkdtemp(prefix="bff-persona-cfg-")))
    config.set("ui_language", language)
    i18n.set_language(language)
    dialog = settings_mod.ModernSettingsDialog(config, include_ai=True)
    dialog.resize(1180, 900)
    dialog.show()
    app.processEvents()
    written = []
    for page, anchor, help_row, suffix in (("AI 与对话", "system_prompt", "persona_help", "persona"),
                                           ("自动化与联动", "dialogue_mode", "bubble_style_help", "bubble-style")):
        dialog.select_page(page)
        section = _section_of(dialog.findChild(SettingRow, f"settingRow_{help_row}"))
        toggle = getattr(section, "toggle", None)      # 折叠节的表头是一个可勾选的按钮
        if toggle is not None:
            toggle.setChecked(True)
        app.processEvents()
        row = dialog.findChild(SettingRow, f"settingRow_{help_row}")    # 展开后的说明行要在画面里
        area = _scroll_area(row)
        if area is not None:
            area.ensureWidgetVisible(row, 0, 40)
            anchor_top = dialog.findChild(SettingRow, f"settingRow_{anchor}").mapTo(area.widget(), QPoint(0, 0)).y()
            area.verticalScrollBar().setValue(max(0, min(area.verticalScrollBar().value(), anchor_top - 24)))
        app.processEvents()
        path = out_dir / f"settings-{suffix}-{language}.png"
        dialog.grab().save(str(path))
        written.append(path)
    dialog.close()
    i18n.set_language("zh")
    return written


if __name__ == "__main__":
    os.environ["APPDATA"] = tempfile.mkdtemp(prefix="bff-capture-")
    os.environ["USERPROFILE"] = "C:\\Users\\me"     # 默认目录里别带本机用户名（截图进公开仓库）
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    language = "en" if "--language" in sys.argv and sys.argv[sys.argv.index("--language") + 1] == "en" else "zh"
    target = Path(args[0]) if args else Path("docs/screenshots/persona-hints-2026-10-18")
    for file in capture(target, language):
        print(file, file.stat().st_size)
