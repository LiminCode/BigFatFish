# -*- coding: utf-8 -*-
"""把简报窗口（含「笔记」页）在白天 / 黑夜、中 / 英下各渲染一张 PNG，作为样式改动的证据。

用法：``python scripts/capture_briefing_window.py <输出目录>``（offscreen 也能跑）。不碰真实数据目录。
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

from pet import i18n, work_briefing as wb, work_notes as wn  # noqa: E402
from pet.work_briefing_ui import WorkBriefingWindow, briefing_tokens  # noqa: E402
from pet.work_notes_ui import WorkNotesPanel  # noqa: E402

SAMPLE = wb.Briefing(
    ok=True, summary="先回两条私信，下午三点有例会。", generated_at=dt.datetime.now().isoformat(timespec="seconds"),
    seconds=48, turns=12,
    markdown=("## Jira\n- [DEMO-12](https://example.atlassian.net/browse/DEMO-12) 登录页偶发白屏 · `进行中` · 高 · **有更新**\n"
              "- [DEMO-9](https://example.atlassian.net/browse/DEMO-9) 网关限流方案 · `待评审`\n\n"
              "## PR\n- [team/api#88](https://github.com/team/api/pull/88) 把 /connect 切到 Kong · 更新于 10-15\n\n"
              "## Slack\n- **等我回复**：Steven 问限流切换前副本数的事 [打开](https://example.slack.com/archives/C1/p1)\n\n"
              "## 日程\n- 15:00 平台例会\n\n## 建议先做\n1. 回 Steven\n2. 看 DEMO-12 的新评论\n"))


def sample_notes() -> list[wn.Note]:
    now = dt.datetime.now()
    first = wn.new_note("https://example.slack.com/archives/C1/p1\nSteven 问限流切换前副本数的事", now)
    first = wn.apply_summary(first, wn.SummaryResult(ok=True, summary="Steven 在等副本数与反亲和方案的答复",
                                                     details="- 工单 DEMO-9 状态 New，负责人是我\n- 下一步：查集群余量后回复",
                                                     remind_at=(now + dt.timedelta(hours=14)).isoformat(timespec="seconds"),
                                                     reason="明早上班先回", tags=["jira", "等回复"],
                                                     model="claude-sonnet-5-5", tokens_in=34641, tokens_out=612,
                                                     cost_usd=0.0412, seconds=14.3), now)
    second = wn.new_note("周五前把季度报告发给 Amy", now - dt.timedelta(hours=3))
    return [first, second]


def capture(out_dir: Path) -> list[Path]:
    app = QApplication.instance() or QApplication([])
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for language in ("zh", "en"):
        i18n.set_language(language)
        for theme in ("light", "dark"):
            window = WorkBriefingWindow(theme=theme)
            window.resize(640, 720)
            panel = WorkNotesPanel(briefing_tokens(theme == "dark"))
            panel.show_notes(sample_notes())
            window.add_tab(i18n.t("notes.tab"), panel)
            window.show_briefing(SAMPLE)
            for tab, suffix in ((0, "briefing"), (1, "notes")):
                window.tabs.setCurrentIndex(tab)
                window.show()
                app.processEvents()
                path = out_dir / f"{suffix}-{theme}-{language}.png"
                window.grab().save(str(path))
                written.append(path)
            window.close()
    i18n.set_language("zh")
    return written


if __name__ == "__main__":
    os.environ["APPDATA"] = tempfile.mkdtemp(prefix="bff-capture-")
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/screenshots/briefing-metro-2026-10-15")
    for file in capture(target):
        print(file, file.stat().st_size)
