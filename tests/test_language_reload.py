# -*- coding: utf-8 -*-
"""设置窗口（独立进程）改了界面语言 → 肥鱼主进程 ``Config.reload()`` 必须切到**磁盘上的新语言**。

2026-10-20 用户从英文切回中文后，笔记「重新总结」和简报仍出英文：reload 里 ``set_language`` 取的是合并前的旧值。
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from pet import i18n
from pet import work_briefing as wb
from pet import work_notes as wn
from pet.config import Config


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


def _switch_on_disk(config: Config, language: str) -> None:
    data = json.loads(config.path.read_text(encoding="utf-8"))
    data["ui_language"] = language
    config.path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_reload_switches_to_the_language_saved_by_the_settings_window(tmp_path):
    config = Config(tmp_path)
    config.set("ui_language", "en")
    config.save()
    assert i18n.current_language() == "en"
    _switch_on_disk(config, "zh")
    config.reload()
    assert config.get("ui_language") == "zh" and i18n.current_language() == "zh", "重载后立刻是新语言，不用重启"
    _switch_on_disk(config, "en")
    config.reload()
    assert i18n.current_language() == "en"


def test_after_the_switch_the_next_summary_and_briefing_prompts_follow(tmp_path):
    config = Config(tmp_path)
    config.set("ui_language", "en")
    config.save()
    now = dt.datetime(2026, 10, 20, 0, 37)
    note = wn.new_note("https://acme.slack.com/archives/C1/p1", now)
    assert wn.build_prompt(note, now).startswith("You are my work-notes assistant")
    _switch_on_disk(config, "zh")
    config.reload()
    prompt = wn.build_prompt(note, now)
    assert prompt.startswith("你是我的工作笔记助手") and "全部用中文写" in prompt and "即使原文和工具返回的内容是英文" in prompt
    briefing = wb.build_prompt(now, "")
    assert briefing.startswith("你是我的工作简报助手") and "全文用中文，即使消息、工单、邮件是英文的" in briefing
    i18n.set_language("en")
    assert "written entirely in English" in wb.build_prompt(now, "")
    assert "write everything in English" in wn.build_prompt(note, now)
