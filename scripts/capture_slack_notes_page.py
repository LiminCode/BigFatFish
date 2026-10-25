# -*- coding: utf-8 -*-
"""把简报窗口的「Slack 关注」页在白天 / 黑夜、中 / 英下各渲染一张 PNG，作为样式与文案的证据。

用法：``python scripts/capture_slack_notes_page.py <输出目录>``。不碰真实数据目录、不起 git、不开浏览器：
条目是中性的样例。要看真实字体用 ``QT_QPA_PLATFORM=windows``。
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pet import i18n, work_notes as wn  # noqa: E402
from pet.config import Config  # noqa: E402
from pet.work_briefing_ui import WorkBriefingWindow, briefing_tokens, resolve_dark  # noqa: E402
from pet.work_notes_service import WorkNotesService  # noqa: E402
from pet.work_notes_ui import WorkNotesController  # noqa: E402

ITEMS = [
    {"title": "问你发布窗口定了没", "from": "#release", "link": "https://example.slack.com/archives/C1/p1", "urgency": "high"},
    {"title": "私信：周会改到四点可以吗", "from": "Ann", "link": "https://example.slack.com/archives/D1/p2", "urgency": "normal"},
    {"title": "设计稿第 3 版发你了，看看配色", "from": "#design", "link": "https://example.slack.com/archives/C2/p3", "urgency": "normal"},
]
ITEMS_EN = [
    {"title": "Asking whether the release window is set", "from": "#release", "link": "https://example.slack.com/archives/C1/p1", "urgency": "high"},
    {"title": "DM: can we move the weekly to 4pm?", "from": "Ann", "link": "https://example.slack.com/archives/D1/p2", "urgency": "normal"},
    {"title": "Design v3 sent, please check the colours", "from": "#design", "link": "https://example.slack.com/archives/C2/p3", "urgency": "normal"},
]


class _Host:
    def show_bubble(self, *a, **k):
        pass

    def show_alert(self, *a, **k):
        pass

    def resolve_alert(self, *a):
        pass


def _service(base: Path, repo: Path, language: str) -> WorkNotesService:
    config = Config(base)
    config.set("ui_language", language)
    config.set(wn.CONFIG_KEY, {"enabled": True, "repo_dir": str(repo), "model": "sonnet"})
    clock = {"now": dt.datetime.now().replace(second=0, microsecond=0) - dt.timedelta(hours=3)}
    service = WorkNotesService(config, folder=wn.SLACK_DIR, label="slack", pull_on_start=False,
                               sync=lambda settings, message: (True, ""), pull=lambda settings: (True, ""),
                               spawn=lambda run: run(), now=lambda: clock["now"], active=lambda idle_s: True,
                               opener=lambda target: True)
    for item in (ITEMS_EN if language == "en" else ITEMS):
        service.add_slack_items([item])
        clock["now"] += dt.timedelta(minutes=50)
    notes = service.notes()
    service.snooze(notes[1].name, 180)
    service.mark_done(notes[2].name)
    return service


def capture(out_dir: Path) -> list[Path]:
    app = QApplication.instance() or QApplication([])
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for language in ("zh", "en"):
        i18n.set_language(language)
        for theme in ("light", "dark"):
            base = Path(tempfile.mkdtemp(prefix="bff-slack-cfg-"))
            repo = Path(tempfile.mkdtemp(prefix="bff-slack-repo-"))
            (repo / ".git").mkdir()
            service = _service(base, repo, language)
            colors = briefing_tokens(resolve_dark(theme))
            controller = WorkNotesController(_Host(), service, colors=colors, slack=True)
            window = WorkBriefingWindow(theme=theme)
            window.add_tab(i18n.t("slack.app"), controller.panel())
            window.select_tab(i18n.t("slack.app"))
            window.resize(960, 640)
            window.show()
            app.processEvents()
            path = out_dir / f"slack-notes-{theme}-{language}.png"
            window.grab().save(str(path))
            written.append(path)
            window.close()
    i18n.set_language("zh")
    return written


if __name__ == "__main__":
    os.environ["APPDATA"] = tempfile.mkdtemp(prefix="bff-capture-")
    os.environ["USERPROFILE"] = r"C:\Users\me"
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/screenshots/slack-notes-2026-10-20")
    for file in capture(target):
        print(file, file.stat().st_size)
