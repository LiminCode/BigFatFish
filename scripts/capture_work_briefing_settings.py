# -*- coding: utf-8 -*-
"""把设置页「自动化与联动 → 工作简报」一节连同展开的「这个功能怎么运作」渲染成 PNG（中 / 英）。

用法：``python scripts/capture_work_briefing_settings.py <输出目录> [--language zh|en]``。不碰真实数据目录；
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
from pet import settings_work_briefing as swb  # noqa: E402
from pet.config import Config  # noqa: E402
from pet.settings_widgets import SettingRow  # noqa: E402


def capture(out_dir: Path, language: str) -> list[Path]:
    app = QApplication.instance() or QApplication([])
    out_dir.mkdir(parents=True, exist_ok=True)
    settings_mod.autostart_mod.is_enabled = lambda: False
    swb.claude_hooks.wsl_exe = lambda: r"C:\Windows\System32\wsl.exe"
    config = Config(Path(tempfile.mkdtemp(prefix="bff-briefing-cfg-")))
    config.set("ui_language", language)
    config.set("work_briefing", {"enabled": True, "time": "10:00", "weekdays_only": True, "model": "sonnet"})
    i18n.set_language(language)
    dialog = settings_mod.ModernSettingsDialog(config, include_ai=False)
    dialog.resize(1180, 1250)
    dialog.show()
    dialog.select_page("自动化与联动")
    dialog.work_briefing_flow_section.toggle.setChecked(True)
    app.processEvents()
    row = dialog.findChild(SettingRow, "settingRow_work_briefing_enabled")
    area = row.parentWidget()
    while area is not None and not isinstance(area, QScrollArea):
        area = area.parentWidget()
    if area is not None:
        area.verticalScrollBar().setValue(max(0, row.mapTo(area.widget(), QPoint(0, 0)).y() - 48))
    app.processEvents()
    path = out_dir / f"work-briefing-settings-{language}.png"
    dialog.grab().save(str(path))
    dialog.close()
    i18n.set_language("zh")
    return [path]


if __name__ == "__main__":
    os.environ["APPDATA"] = tempfile.mkdtemp(prefix="bff-capture-")
    os.environ["USERPROFILE"] = "C:\\Users\\me"     # 默认目录里别带本机用户名（截图进公开仓库）
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    language = "en" if "--language" in sys.argv and sys.argv[sys.argv.index("--language") + 1] == "en" else "zh"
    target = Path(args[0]) if args else Path("docs/screenshots/work-briefing-settings-2026-10-19")
    for file in capture(target, language):
        print(file, file.stat().st_size)
