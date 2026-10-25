# -*- coding: utf-8 -*-
"""把简报窗口的「笔记」页（带底部基本信息栏）在白天 / 黑夜、中 / 英下各渲染一张 PNG，作为样式证据。

用法：``python scripts/capture_note_meta_bar.py <输出目录>``。不碰真实数据目录、不起 git：笔记是中性的样例。
要看真实字体用 ``QT_QPA_PLATFORM=windows``。
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
from pet.work_briefing_ui import WorkBriefingWindow, briefing_tokens, resolve_dark  # noqa: E402
from pet.work_notes_ui import WorkNotesPanel  # noqa: E402

NOW = dt.datetime(2026, 10, 20, 15, 41)
SAMPLES = {
    "zh": [("https://example.atlassian.net/browse/DEMO-12\n登录页偶发白屏", "登录页偶发白屏：周四前定位",
            "- 只在 Safari 17 上出现\n- 前端说可能是缓存头\n- 周四站会前给结论"),
           ("https://example.slack.com/archives/C1/p1\n问发布窗口定了没", "发布窗口还没定，等 PM 回复", "- 候选：周二晚 / 周四晚")],
    "en": [("https://example.atlassian.net/browse/DEMO-12\nLogin page sometimes blank", "Blank login page: find the cause by Thursday",
            "- Only on Safari 17\n- Frontend suspects cache headers\n- Conclusion before Thursday stand-up"),
           ("https://example.slack.com/archives/C1/p1\nIs the release window set?", "Release window not set yet, waiting on PM",
            "- Candidates: Tue evening / Thu evening")],
}


def _notes(language: str) -> list[wn.Note]:
    notes = []
    for index, (original, summary, details) in enumerate(SAMPLES[language]):
        note = wn.new_note(original, NOW - dt.timedelta(minutes=50 * index)).replace(
            summary=summary, details=details, tags=["jira" if index == 0 else "slack"],
            remind_at="2026-10-23T09:30:00", model="claude-sonnet-5-5", tokens_in=34641 - 9000 * index,
            tokens_out=412 + 50 * index, cost_usd=0.0283 - 0.006 * index, seconds=19.4 - 4 * index)
        notes.append(note)
    return notes


def capture(out_dir: Path) -> list[Path]:
    app = QApplication.instance() or QApplication([])
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for language in ("zh", "en"):
        i18n.set_language(language)
        for theme in ("light", "dark"):
            panel = WorkNotesPanel(briefing_tokens(resolve_dark(theme)))
            window = WorkBriefingWindow(theme=theme)
            window.add_tab(i18n.t("notes.tab"), panel)
            window.select_tab(i18n.t("notes.tab"))
            window.resize(960, 600)
            window.show()
            panel.show_notes(_notes(language))
            app.processEvents()
            path = out_dir / f"notes-meta-{theme}-{language}.png"
            window.grab().save(str(path))
            written.append(path)
            window.close()
    i18n.set_language("zh")
    return written


if __name__ == "__main__":
    os.environ["APPDATA"] = tempfile.mkdtemp(prefix="bff-capture-")
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/screenshots/note-meta-bar-2026-10-20")
    for file in capture(target):
        print(file, file.stat().st_size)
