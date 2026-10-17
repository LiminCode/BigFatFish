# -*- coding: utf-8 -*-
"""把「个人助理」窗口（简报页 + 灵感页）在白天 / 黑夜、中 / 英下各渲染一张 PNG，作为样式与文案的证据。

用法：``python scripts/capture_personal_window.py <输出目录>``。不碰真实数据目录、不调 Anthropic、不起 git：
简报与推送都是中性的样例。要看真实字体用 ``QT_QPA_PLATFORM=windows``。
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

from pet import i18n, personal_briefing as pb, personal_vault as pv  # noqa: E402
from pet.config import Config  # noqa: E402
from pet.personal_service import PersonalService  # noqa: E402
from pet.personal_ui import PersonalController  # noqa: E402

REPORT = ("概要：先把周五漏掉的扫描补上，再回一封邮件。\n\n"
          "## 待复习\n- 2026-09-10 风险观察（next_review 2026-09-20 已过）：窗口期的触发规则该重看一遍\n\n"
          "## 决策与检查点\n- 2026-10-16 · 字体链接修复：Status open，等重启后确认\n- 2026-10-04 · 本周计划 A：10-23 扫描后回看\n\n"
          "## 饮食 · 本周\n- 已记录 1/7 天；面 0/2 · 夜间面包 0\n- 本周扫描：周五早上起床后\n\n"
          "## 复习\n- 词：ubiquitous、tenuous、candor（最久没测）\n- 哲学：10-15 那条关于「廉价七成」的笔记\n\n"
          "## 今天\n- 5-Daily 今天还没有日记\n- 灵感：把阳台的灯换成感应的 · 周末整理旧书\n\n"
          "## 建议\n1. 补扫描并记录\n2. 回看风险观察的触发规则\n3. 晚饭前踩 30 分钟\n")


class _Host:
    def show_bubble(self, *a, **k):
        pass

    def show_alert(self, *a, **k):
        pass

    def resolve_alert(self, *a):
        pass


def _service(base: Path, clone: Path, language: str) -> PersonalService:
    config = Config(base)
    config.set("ui_language", language)
    config.set(pv.CONFIG_KEY, {"enabled": True, "repo_dir": str(clone), "time": "08:30", "model": "", "effort": ""})
    now = dt.datetime.now().replace(microsecond=0)

    def generate(when, settings, provider, *, pull_note=""):
        summary, markdown = pb.parse_text(REPORT)
        return pb.PersonalBriefing(ok=True, summary=summary, markdown=markdown, generated_at=when.isoformat(), seconds=71.2,
                                   turns=7, model="claude-sonnet-5-20260101", effort="medium", tokens_in=52340,
                                   tokens_out=1480, files_read=["INDEX.md", "3-Decisions/2026-10-16 Decision Log.md",
                                                                "User/Meal Log.md", "9-Learning/English-Vocab/quiz-log.md",
                                                                "User/灵感 Inspiration.md"])

    class _Provider:
        model, effort, api_key, base_url, api_format = "claude-sonnet-5", "medium", "k", "https://api.anthropic.com", "auto"

    service = PersonalService(config, generate=generate, pull=lambda repo, token="": (True, ""),
                              sync=lambda repo, when, token="": (True, ""), spawn=lambda run: run(), now=lambda: now,
                              opener=lambda target: True, token=lambda: "", provider=lambda: _Provider())
    service.generate_now()
    service.add_inspiration("把阳台的灯换成感应的")
    return service


def capture(out_dir: Path) -> list[Path]:
    app = QApplication.instance() or QApplication([])
    out_dir.mkdir(parents=True, exist_ok=True)
    clone = Path(tempfile.mkdtemp(prefix="bff-personal-clone-"))
    (clone / ".git").mkdir()
    (clone / "INDEX.md").write_text("# AI-Base\n", encoding="utf-8")
    written = []
    for language in ("zh", "en"):
        i18n.set_language(language)
        for theme in ("light", "dark"):
            base = Path(tempfile.mkdtemp(prefix="bff-personal-cfg-"))
            service = _service(base, clone, language)
            service._config.set("context_menu_appearance", {**(service._config.get("context_menu_appearance") or {}), "theme": theme})
            controller = PersonalController(_Host(), service)
            controller.open_window()
            window = controller.window
            window.resize(900, 720)
            for tab, suffix in ((0, "briefing"), (1, "ideas")):
                window.tabs.setCurrentIndex(tab)
                window.show()
                app.processEvents()
                path = out_dir / f"personal-{suffix}-{theme}-{language}.png"
                window.grab().save(str(path))
                written.append(path)
            window.close()
    i18n.set_language("zh")
    return written


if __name__ == "__main__":
    os.environ["APPDATA"] = tempfile.mkdtemp(prefix="bff-capture-")
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/screenshots/personal-2026-10-17")
    for file in capture(target):
        print(file, file.stat().st_size)
