# -*- coding: utf-8 -*-
"""把设置页「工作笔记」一节（含流程图标与它的悬停说明）在明 / 暗、中 / 英下各渲染一张 PNG。

用法：``python scripts/capture_work_notes_settings.py <输出目录>``。不碰真实数据目录。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="bff-capture-settings-")

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QColor, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pet import i18n  # noqa: E402
from pet.config import Config  # noqa: E402
from pet.settings_widgets import SettingRow, SettingsSection  # noqa: E402


def _section_of(dialog) -> SettingsSection:
    row = dialog.findChild(SettingRow, "settingRow_work_notes_flow")
    widget = row
    while widget is not None and not isinstance(widget, SettingsSection):
        widget = widget.parentWidget()
    assert widget is not None
    return widget


def capture(out_dir: Path) -> list[Path]:
    from pet import modern_settings_dialog as settings_mod

    app = QApplication.instance() or QApplication([])
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for language in ("zh", "en"):
        for theme in ("light", "dark"):
            config = Config(Path(tempfile.mkdtemp(prefix="bff-cfg-")))
            config.set("ui_language", language)
            config.set("context_menu_appearance", {**config.get("context_menu_appearance"), "theme": theme})
            dialog = settings_mod.ModernSettingsDialog(config, include_ai=False)
            dialog.resize(1100, 760)
            dialog.show()
            app.processEvents()
            section = _section_of(dialog)
            section.setFixedWidth(820)
            app.processEvents()
            shot = section.grab()
            # 把悬停说明画在截图下面（真实界面里是鼠标放到流程图标上弹出的 tooltip）
            tip = QLabel(dialog.work_notes_flow_button.toolTip())
            tip.setWordWrap(True)
            tip.setFixedWidth(820)
            tip.setStyleSheet("background: #fffbe6; color: #222; padding: 10px; font-size: 12px;")
            tip.adjustSize()
            app.processEvents()
            tip_shot = tip.grab()
            canvas = QPixmap(max(shot.width(), tip_shot.width()), shot.height() + tip_shot.height() + 12)
            canvas.fill(QColor("#ffffff"))
            painter = QPainter(canvas)
            painter.drawPixmap(QPoint(0, 0), shot)
            painter.drawPixmap(QPoint(0, shot.height() + 12), tip_shot)
            painter.end()
            path = out_dir / f"settings-work-notes-{theme}-{language}.png"
            canvas.save(str(path))
            written.append(path)
            dialog.close()
            dialog.deleteLater()
            app.processEvents()
    i18n.set_language("zh")
    return written


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/screenshots/work-notes-settings-2026-10-15")
    for file in capture(target):
        print(file, file.stat().st_size)
