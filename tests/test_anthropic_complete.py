# -*- coding: utf-8 -*-
"""``anthropic_provider.complete``：无头的一问一答，带本地工具循环，把用量 / 模型名收回来。

纪律：不发网络请求——``client`` 注入一个按脚本返回消息的假对象。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from pet.chat import anthropic_provider as ap
from pet.chat.models import ProviderConfig
from pet.chat.providers import ProviderError


def _usage(**kw):
    base = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    base.update(kw)
    return SimpleNamespace(**base)


def _text(text: str):
    return SimpleNamespace(type="text", text=text)


def _tool_use(name: str, **args):
    return SimpleNamespace(type="tool_use", id=f"toolu_{name}", name=name, input=args)


class _Stream:
    def __init__(self, final):
        self._final = final

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self._final


class _Client:
    """``client.messages.stream(**kwargs)`` 依次吐出脚本里的消息，并记下每次的参数。"""

    def __init__(self, finals):
        self.finals = list(finals)
        self.calls: list[dict] = []
        self.messages = SimpleNamespace(stream=self._stream)
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kwargs):
        self.calls.append(kwargs)
        return _Stream(self.finals.pop(0))


class _Tools:
    definitions = [{"name": "kb_read", "description": "read", "input_schema": {"type": "object", "properties": {}}}]
    system_note = "## 知识库\n先读 INDEX.md"

    def __init__(self):
        self.calls = []

    def run(self, name, tool_input):
        self.calls.append((name, tool_input))
        if tool_input.get("path") == "boom.md":
            raise RuntimeError("读不到")
        return "# INDEX"


def _config(**over) -> ProviderConfig:
    cfg = ProviderConfig("api-2", "Claude", base_url="https://api.anthropic.com", model="claude-sonnet-5", api_key="k",
                         timeout=60.0)
    for key, value in over.items():
        setattr(cfg, key, value)
    return cfg


def _final(content, stop_reason="end_turn", model="claude-sonnet-5-20260101", **usage):
    return SimpleNamespace(content=content, stop_reason=stop_reason, model=model, usage=_usage(**usage))


def test_a_tool_round_then_the_answer_sums_usage_and_counts_rounds():
    client = _Client([
        _final([_tool_use("kb_read", path="INDEX.md"), _tool_use("kb_read", path="boom.md")], "tool_use",
               input_tokens=1000, cache_creation_input_tokens=5000, output_tokens=80),
        _final([_text("概要：好。"), _text("\n\n## 今天\n无")], input_tokens=100, cache_read_input_tokens=6000, output_tokens=300),
    ])
    tools = _Tools()
    result = ap.complete("写简报", "你是助理", _config(), effort="high", client_tools=tools, client=client)
    assert result.text == "概要：好。\n\n## 今天\n无" and result.model == "claude-sonnet-5-20260101"
    assert (result.input_tokens, result.output_tokens, result.rounds, result.stop_reason) == (12100, 380, 1, "end_turn")
    first, second = client.calls
    assert first["model"] == "claude-sonnet-5" and first["max_tokens"] == 16000 and first["output_config"] == {"effort": "high"}
    assert first["system"] == "你是助理\n\n## 知识库\n先读 INDEX.md" and first["tools"] == _Tools.definitions
    assert first["cache_control"] == {"type": "ephemeral"} and "mcp_servers" not in first
    assert tools.calls == [("kb_read", {"path": "INDEX.md"}), ("kb_read", {"path": "boom.md"})]
    results = second["messages"][-1]["content"]
    assert results[0]["content"] == "# INDEX" and results[1]["is_error"] is True and "读不到" in results[1]["content"]
    assert second["messages"][-2]["role"] == "assistant"


def test_model_and_effort_fall_back_to_the_provider_config():
    client = _Client([_final([_text("ok")])])
    result = ap.complete("hi", "", _config(effort="low"), client=client)
    assert client.calls[0]["output_config"] == {"effort": "low"} and client.calls[0]["model"] == "claude-sonnet-5"
    assert result.rounds == 0 and result.text == "ok"
    client = _Client([_final([_text("ok")])])
    ap.complete("hi", "", _config(), model="claude-opus-5-5", effort="nonsense", client=client)
    assert client.calls[0]["model"] == "claude-opus-5-5" and client.calls[0]["output_config"] == {"effort": "medium"}
    client = _Client([_final([_text("ok")])])
    ap.complete("hi", "", _config(), model="claude-haiku-5-5", client=client)
    assert "output_config" not in client.calls[0], "Haiku 不收 effort（发了就是 400）"


def test_too_many_tool_rounds_empty_answers_and_refusals_raise():
    tools = _Tools()
    client = _Client([_final([_tool_use("kb_read", path="INDEX.md")], "tool_use")] * 3)
    with pytest.raises(ProviderError, match="轮数"):
        ap.complete("x", "", _config(), client_tools=tools, max_rounds=1, client=client)
    with pytest.raises(ProviderError, match="空回复"):
        ap.complete("x", "", _config(), client=_Client([_final([])]))
    with pytest.raises(ProviderError, match="拒绝"):
        ap.complete("x", "", _config(), client=_Client([_final([_text("")], "refusal")]))


def test_sdk_failures_are_translated():
    class _Boom:
        messages = SimpleNamespace(stream=lambda **kw: (_ for _ in ()).throw(TypeError("Could not resolve authentication method")))

    with pytest.raises(ProviderError, match="API Key"):
        ap.complete("x", "", _config(), client=_Boom())
