# -*- coding: utf-8 -*-
"""工作简报的提示词可见可改、effort 可选、三级优先级（用户 2026-10-24）。

- 发给 Claude 的提示词是一段**明文模板**：内置版由来源开关拼出来，占位符只有 {now} {hours} {prs}
  {priority_rules}；用户改过就整份存进配置（按界面语言分 prompt_zh / prompt_en），改过之后来源开关只管
  工具权限，提示词里要不要提某个来源由用户自己写。
- effort 显式传给 claude -p（low / medium / high / xhigh，默认 high）。
- 优先级：每条行首 ★★★ / ★★ / ★ 三级，由模型判断；用户的「优先级偏好」追加进提示词；窗口按星数上色。

纪律：不起真的 wsl.exe、不读真实数据目录。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet import work_briefing as wb
from pet import work_briefing_ui as ui
from tests.test_work_briefing import MONDAY_10, FakeWsl, _claude_json

app = QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


# ---------------------------------------------------------------- effort

def test_effort_is_a_setting_with_a_safe_default():
    assert wb.normalize({"effort": "medium"})["effort"] == "medium"
    assert wb.normalize({"effort": "max; rm -rf"})["effort"] == "high"
    assert wb.normalize(None)["effort"] == "high"
    assert "--effort medium" in wb.claude_command("sonnet", effort="medium")
    assert "--effort high" in wb.claude_command("sonnet")


# ---------------------------------------------------------------- 模板

def test_the_builtin_template_renders_to_exactly_the_prompt_sent_today():
    template = wb.default_prompt_template("zh", wb.DEFAULT_SOURCES)
    assert "{now}" in template and "{hours}" in template and "{prs}" in template and "{priority_rules}" in template
    assert wb.render_template(template, now="X", hours=72, prs="PRS", priority_rules="") \
        == wb.build_prompt(MONDAY_10, "PRS", language="zh").replace("2026-10-12 10:00 星期一", "X")


def test_render_template_only_touches_known_placeholders():
    rendered = wb.render_template('{now} {"summary": "..."} {unknown} {{x}}', now="N")
    assert rendered == 'N {"summary": "..."} {unknown} {{x}}'


def test_a_user_edited_template_is_sent_verbatim_with_placeholders_filled():
    template = "自定义：{now}，回看 {hours} 小时。\n{prs}\n{priority_rules}"
    prompt = wb.build_prompt(MONDAY_10, "- acme/widgets#10 Fix login", template=template, language="zh")
    assert prompt.startswith("自定义：2026-10-12 10:00 星期一，回看 72 小时。\n- acme/widgets#10 Fix login")
    assert "JQL" not in prompt, "改过的模板原样发，不再拼内置的来源段落"


def test_generate_passes_effort_and_the_edited_template(tmp_path):
    wsl = FakeWsl(claude_stdout=_claude_json())
    briefing = wb.generate(MONDAY_10, "sonnet", run=wsl, effort="low", template="T {now} {prs}", priority_rules="")
    assert briefing.ok and briefing.effort == "low"
    (_gh, _in, _t), (args, prompt, _timeout) = wsl.calls
    assert "--effort low" in args[3]
    assert prompt.startswith("T 2026-10-12 10:00 星期一 ") and "acme/widgets#10" in prompt


# ---------------------------------------------------------------- 优先级

@pytest.mark.parametrize("language", ["zh", "en"])
def test_the_builtin_prompt_asks_for_three_star_levels(language):
    prompt = wb.build_prompt(MONDAY_10, "", language=language)
    assert "★★★" in prompt and "★★ " in prompt and "★ " in prompt
    assert f"- ★★★ {wb.BUG_MARK} [" in prompt, "bug 行：星在前、🐞 在后"


def test_priority_rules_are_injected_only_when_set():
    plain = wb.build_prompt(MONDAY_10, "", language="zh")
    assert "优先级偏好" not in plain
    with_rules = wb.build_prompt(MONDAY_10, "", language="zh", priority_rules="QA 报的 bug 一律 ★★★")
    assert "优先级偏好" in with_rules and "QA 报的 bug 一律 ★★★" in with_rules
    assert wb.normalize({"priority_rules": "  x  "})["priority_rules"] == "x"


REPORT = ("## Jira\n"
          f"- ★★★ {wb.BUG_MARK} [DEMO-7](https://example.test/browse/DEMO-7) Login freezes · `Open` · High\n"
          "  - QA 报的场景：Safari 连点两次。\n"
          "- ★★ [DEMO-8](https://example.test/browse/DEMO-8) Tidy build · `Open`\n"
          "- ★ [DEMO-9](https://example.test/browse/DEMO-9) Docs typo · `Open`\n"
          "\n## 建议先做\n1. ★★★ 先看 DEMO-7。\n")


def _star_colors(window: ui.WorkBriefingWindow) -> dict[str, str]:
    """每个以星开头的段落 → 星那一段文字的前景色。"""
    out = {}
    block = window.body.document().begin()
    while block.isValid():
        text = block.text().strip()
        if text.startswith("★"):
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.text().strip().startswith("★"):
                    out[text] = frag.charFormat().foreground().color().name()
                    break
                it += 1
        block = block.next()
    return out


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_stars_are_coloured_by_level_and_bug_lines_still_get_their_tint(theme):
    window = ui.WorkBriefingWindow(theme=theme)
    try:
        window.show_briefing(wb.Briefing(ok=True, summary="s", markdown=REPORT, generated_at="2026-10-24T09:00:00", seconds=1))
        tokens = ui.briefing_tokens(theme == "dark")
        colors = _star_colors(window)
        three = next(v for k, v in colors.items() if "DEMO-7" in k)
        two = next(v for k, v in colors.items() if "DEMO-8" in k)
        one = next(v for k, v in colors.items() if "DEMO-9" in k)
        assert (three, two, one) == (tokens["p1"], tokens["p2"], tokens["p3"])
        assert next(v for k, v in colors.items() if "先看" in k) == tokens["p1"], "建议里的星也上色"
        # bug 行前面多了星，底色照旧
        block = window.body.document().begin()
        tinted = []
        while block.isValid():
            if block.blockFormat().background().style() != Qt.BrushStyle.NoBrush:
                tinted.append(block.text().strip())
            block = block.next()
        assert any("DEMO-7" in t for t in tinted) and any(t.startswith("QA") for t in tinted)
        assert not any("DEMO-8" in t for t in tinted)
    finally:
        window.close()
