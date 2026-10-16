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
from PySide6.QtWidgets import QApplication  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pet import i18n  # noqa: E402
from pet.config import Config  # noqa: E402
from pet.settings_widgets import SettingRow, SettingsSection  # noqa: E402


def _section_of(dialog, row_id: str) -> SettingsSection:
    row = dialog.findChild(SettingRow, row_id)
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
            section = _section_of(dialog, "settingRow_work_notes_enabled")
            flow = dialog.work_notes_flow_section
            # 切到这一节所在的页：没显示过的页不会排版，抓出来的是空白
            for index in range(dialog.pages.count()):
                if dialog.pages.widget(index).isAncestorOf(section):
                    dialog.pages.setCurrentIndex(index)
                    dialog.sidebar.setCurrentRow(index)
            flow.toggle.setChecked(True)   # 展开「这个功能怎么运作」
            for widget in (section, flow):
                widget.setFixedWidth(820)
            for _ in range(3):
                app.processEvents()
            shot, flow_shot = section.grab(), flow.grab()
            canvas = QPixmap(max(shot.width(), flow_shot.width()), shot.height() + flow_shot.height() + 12)
            canvas.fill(QColor(dialog.palette().window().color()))
            painter = QPainter(canvas)
            painter.drawPixmap(QPoint(0, 0), shot)
            painter.drawPixmap(QPoint(0, shot.height() + 12), flow_shot)
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
