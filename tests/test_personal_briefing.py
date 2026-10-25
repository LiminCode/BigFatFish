# -*- coding: utf-8 -*-
"""个人简报的纯逻辑：提示词、结果解析、什么时候该做、带拒绝名单的只读工具、落盘。

纪律：不真的调 Anthropic——``complete`` 用假函数；知识库用临时目录里的中性样例。
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from pet import i18n
from pet import personal_briefing as pb
from pet import personal_vault as pv
from pet.chat.models import ProviderConfig

SAT_0900 = dt.datetime(2026, 10, 17, 9, 0)       # 星期六
ON = {"enabled": True, "repo_dir": "", "time": "08:30", "model": "", "effort": ""}

REPORT = "概要：先把周五的扫描补上。\n\n## 待复习\n- 风险观察（到期 2026-09-20）\n\n## 决策与检查点\n无\n"


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "AI-Base"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    (root / "INDEX.md").write_text("# AI-Base\n\n| 5-Daily | 日记 |\n", encoding="utf-8")
    (root / "6-Knowledge" / "login").mkdir(parents=True)
    (root / "6-Knowledge" / "login" / "Environments.md").write_text("host: example, password: hunter2\n", encoding="utf-8")
    (root / "6-Knowledge" / "Frequent Commands and Pass.md").write_text("ssh example\n", encoding="utf-8")
    (root / "5-Daily").mkdir()
    (root / "5-Daily" / "2026-10-17.md").write_text("今天：补扫描\n", encoding="utf-8")
    return root


class _Provider(ProviderConfig):
    pass


def _provider(**over) -> ProviderConfig:
    cfg = ProviderConfig("api-2", "Claude", base_url="https://api.anthropic.com", model="claude-sonnet-5", api_key="k")
    for key, value in over.items():
        setattr(cfg, key, value)
    return cfg


class _Completion:
    def __init__(self, text=REPORT, **over):
        self.text, self.model, self.input_tokens, self.output_tokens, self.rounds = text, "claude-sonnet-5-20260101", 48210, 1130, 6
        for key, value in over.items():
            setattr(self, key, value)


# ---------------------------------------------------------------- 提示词与解析

def test_the_prompt_says_read_only_names_the_sections_and_the_language():
    prompt = pb.build_prompt(SAT_0900)
    assert "2026-10-17 09:00" in prompt and "星期六" in prompt and "只读" in prompt and "INDEX.md" in prompt
    for section in ("## 待复习", "## 决策与检查点", "## 饮食 · 本周", "## 复习", "## 今天", "## 建议"):
        assert section in prompt
    assert "用中文写" in prompt and "密码" in prompt
    i18n.set_language("en")
    assert "用English写" in pb.build_prompt(SAT_0900)


def test_the_first_line_is_the_summary_and_the_rest_is_the_body():
    assert pb.parse_text(REPORT) == ("先把周五的扫描补上。", REPORT.split("\n", 1)[1].strip())
    assert pb.parse_text("**概要：** 短句\n\n正文") == ("短句", "正文")
    assert pb.parse_text("没按约定\n写") == (pb.FALLBACK_SUMMARY, "没按约定\n写")
    assert pb.parse_text("") == ("", "")


# ---------------------------------------------------------------- 什么时候该做

def test_it_runs_on_weekends_too_and_only_once_a_day():
    assert pb.is_due(ON, {}, SAT_0900), "个人简报周末也做"
    assert not pb.is_due(ON, {"done_date": "2026-10-17"}, SAT_0900)
    assert not pb.is_due(ON, {}, SAT_0900.replace(hour=8, minute=0))
    assert not pb.is_due({**ON, "enabled": False}, {}, SAT_0900)
    assert not pb.is_due(ON, {"attempt_date": "2026-10-17", "attempts": 1, "last_attempt": SAT_0900.timestamp() - 60}, SAT_0900)


# ---------------------------------------------------------------- 只读工具

def test_the_toolset_records_reads_and_refuses_credential_paths(vault):
    tools = pb.RecordingToolset(vault)
    assert tools.definitions and "只读" in tools.system_note
    assert "AI-Base" in tools.run("kb_read", {"path": "INDEX.md"})
    tools.run("kb_read", {"path": "/INDEX.md"})
    assert tools.run("kb_read", {"path": "5-Daily/2026-10-17.md"}).startswith("今天")
    assert tools.files_read == ["INDEX.md", "5-Daily/2026-10-17.md"], "去重、保序"
    from pet.chat.knowledge_base import KnowledgeBaseError

    for denied in ("6-Knowledge/login/Environments.md", "6-Knowledge/Frequent Commands and Pass.md", ".git/config",
                   ".obsidian/app.json"):
        with pytest.raises(KnowledgeBaseError):
            tools.run("kb_read", {"path": denied})
    with pytest.raises(KnowledgeBaseError):
        tools.run("kb_list", {"path": "6-Knowledge/login"})
    hits = tools.run("kb_search", {"query": "hunter2"})
    assert "没有找到" in hits, "搜索也走不进凭据目录"
    assert "config" not in tools.run("kb_search", {"query": "core"}), "搜索跳过 .git"
    assert "5-Daily/2026-10-17.md" in tools.run("kb_search", {"query": "扫描"})
    assert len(tools.files_read) == 2 and tools.calls >= 8


# ---------------------------------------------------------------- 生成

def test_generate_fills_model_effort_tokens_rounds_and_files(vault):
    calls = []

    def complete(prompt, system, provider, **kw):
        calls.append((prompt, system, provider, kw))
        kw["client_tools"].run("kb_read", {"path": "INDEX.md"})
        return _Completion()

    settings = {**ON, "repo_dir": str(vault), "effort": "high"}
    briefing = pb.generate(SAT_0900, settings, _provider(), pull_note="", complete=complete,
                           clock=iter([10.0, 73.4]).__next__)
    assert briefing.ok and briefing.summary == "先把周五的扫描补上。" and briefing.markdown.startswith("## 待复习")
    assert briefing.model == "claude-sonnet-5-20260101" and briefing.effort == "high", "模型名取 API 回的实际名字，强度取设置"
    assert (briefing.tokens_in, briefing.tokens_out, briefing.turns, briefing.seconds) == (48210, 1130, 6, 63.4)
    assert briefing.files_read == ["INDEX.md"] and briefing.generated_at == "2026-10-17T09:00:00"
    (prompt, system, provider, kw), = calls
    assert "只读" in prompt and kw["model"] == "claude-sonnet-5" and kw["effort"] == "high"
    assert kw["max_rounds"] == pb.MAX_TOOL_ROUNDS and kw["timeout"] == pb.TIMEOUT_S and provider.api_key == "k"


def test_generate_refuses_non_claude_providers_and_missing_clones(tmp_path, vault):
    calls = []
    openai = _provider(base_url="https://api.deepseek.com", model="deepseek-v4-flash")
    briefing = pb.generate(SAT_0900, {**ON, "repo_dir": str(vault)}, openai, complete=lambda *a, **k: calls.append(1))
    assert not briefing.ok and "Claude" in briefing.error and not calls
    briefing = pb.generate(SAT_0900, {**ON, "repo_dir": str(tmp_path / "missing")}, _provider(),
                           complete=lambda *a, **k: calls.append(1))
    assert not briefing.ok and "missing" in briefing.error and not calls


def test_a_provider_error_becomes_a_failed_briefing_that_still_lists_what_was_read(vault):
    from pet.chat.providers import ProviderError

    def complete(prompt, system, provider, **kw):
        kw["client_tools"].run("kb_read", {"path": "INDEX.md"})
        raise ProviderError("认证失败：API Key 无效或已失效", 401)

    briefing = pb.generate(SAT_0900, {**ON, "repo_dir": str(vault)}, _provider(), complete=complete)
    assert not briefing.ok and "认证失败" in briefing.error and briefing.files_read == ["INDEX.md"]


# ---------------------------------------------------------------- 落盘

def test_the_state_file_keeps_the_latest_briefing_with_its_usage(tmp_path):
    briefing = pb.PersonalBriefing(ok=True, summary="s", markdown="## 今天\n无", generated_at="2026-10-17T09:00:00",
                                   seconds=63.4, turns=6, model="claude-sonnet-5", effort="medium", tokens_in=48210,
                                   tokens_out=1130, files_read=["INDEX.md"], pull_note="")
    state = pb.record(tmp_path, briefing, SAT_0900)
    assert state["done_date"] == "2026-10-17" and state["attempts"] == 1
    assert json.loads((tmp_path / pb.STATE_FILE).read_text(encoding="utf-8"))["briefing"]["tokens_in"] == 48210
    back = pb.latest(tmp_path)
    assert back == briefing
    pb.record(tmp_path, pb.PersonalBriefing(error="boom"), SAT_0900.replace(hour=10))
    assert pb.latest(tmp_path) == briefing and pb.load_state(tmp_path)["error"] == "boom"
    assert pb.load_state(tmp_path)["attempts"] == 2
    assert pb.settings_of(type("C", (), {"get": lambda self, key: {"enabled": True}})()) == pv.normalize({"enabled": True})
