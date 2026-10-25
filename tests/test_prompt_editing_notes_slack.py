# -*- coding: utf-8 -*-
"""工作笔记 / Slack 关注的提示词可见可改、effort 可选（用户 2026-10-24，和简报同一套口径）。

模板明文存配置（笔记按界面语言 prompt_zh / prompt_en，Slack 只有一份 prompt；空 = 内置），
占位符由 ``work_briefing.render_template`` 填（只换认识的名字，JSON 示例里的花括号原样保留）。
纪律：不起真的 wsl.exe、不读真实数据目录。
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from pet import i18n
from pet import slack_watch as sw
from pet import work_notes as wn

NOW = dt.datetime(2026, 10, 24, 9, 30)


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


def _ok_json(**fields) -> str:
    return json.dumps({"type": "result", "subtype": "success", "is_error": False, "num_turns": 2,
                       "result": json.dumps(fields, ensure_ascii=False), "permission_denials": []}, ensure_ascii=False)


class _Wsl:
    def __init__(self, stdout: str):
        self.calls, self._stdout = [], stdout

    def __call__(self, args, *, input_text=None, timeout=30.0):
        self.calls.append((list(args), input_text))
        return 0, self._stdout


# ---------------------------------------------------------------- 工作笔记

def test_notes_settings_grow_effort_and_prompt_overrides():
    settings = wn.normalize({"effort": "low", "prompt_zh": " 我的 {now} ", "prompt_en": "", "model": "haiku"})
    assert settings["effort"] == "low" and settings["prompt_zh"] == "我的 {now}" and settings["prompt_en"] == ""
    assert wn.normalize(None)["effort"] == "high" and wn.normalize({"effort": "nope"})["effort"] == "high"


@pytest.mark.parametrize("language", ["zh", "en"])
def test_the_notes_builtin_template_is_plain_text_with_placeholders(language):
    template = wn.default_prompt_template(language)
    assert "{now}" in template and "{original}" in template and "{language}" in template
    assert '{"title": "..."' in template and "{{" not in template, "编辑框里看到的就是发出去的，不带转义"
    note = wn.new_note("看一下 DEMO-1", NOW)
    assert wn.build_prompt(note, NOW, language) == wn.render_prompt(template, note, NOW)
    assert '{"title": "..."' in wn.build_prompt(note, NOW, language), "JSON 示例的花括号原样到了提示词里"


def test_an_edited_notes_template_is_sent_verbatim(tmp_path):
    note = wn.new_note("看一下 DEMO-1", NOW)
    wsl = _Wsl(_ok_json(title="t", summary="s", details="- d", remind_at=None, reason="r", tags=["x"], error=None))
    result = wn.summarize(note, NOW, "sonnet", run=wsl, effort="low", template="模板 {now}\n<note>\n{original}\n</note>")
    assert result.ok
    (args, prompt), = wsl.calls
    assert "--effort low" in args[3]
    assert prompt == "模板 2026-10-24 09:30\n<note>\n看一下 DEMO-1\n</note>"


# ---------------------------------------------------------------- Slack 关注

def test_slack_settings_grow_effort_and_prompt_override():
    settings = sw.normalize({"effort": "xhigh", "prompt": " 我的 {since} "})
    assert settings["effort"] == "xhigh" and settings["prompt"] == "我的 {since}"
    assert sw.normalize(None)["effort"] == "high" and sw.normalize(None)["prompt"] == ""


def test_the_slack_builtin_template_is_plain_text_and_renders_to_the_prompt_sent_today():
    template = sw.default_prompt_template()
    assert "{now}" in template and "{since}" in template and "{max_items}" in template
    assert '{"summary"' in template and "{{" not in template
    since = NOW - dt.timedelta(minutes=15)
    assert sw.build_prompt(NOW, since) == sw.render_prompt(template, NOW, since)
    assert '{"summary"' in sw.build_prompt(NOW, since)


def test_an_edited_slack_template_and_effort_reach_the_command(tmp_path):
    wsl = _Wsl(_ok_json(summary="", items=[], error=""))
    since = NOW - dt.timedelta(minutes=15)
    result = sw.generate(NOW, since, "sonnet", run=wsl, effort="medium", template="看 {since} 到 {now}，最多 {max_items} 条")
    assert result.ok
    (args, prompt), = wsl.calls
    assert "--effort medium" in args[3] and "--effort high" not in args[3]
    assert prompt == f"看 2026-10-24 09:15 到 2026-10-24 09:30，最多 {sw.MAX_ITEMS} 条"
    assert "--effort high" in sw.claude_command("sonnet")
