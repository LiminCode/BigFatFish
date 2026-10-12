# -*- coding: utf-8 -*-
"""GitHub 连接器：桌宠对话经 Messages API 的 MCP connector 查 GitHub（只读）。

网络与系统钥匙串都是边界，用替身：假客户端按脚本吐流并记录请求，假钥匙串是
一个内存字典。真实链路（Claude API → GitHub MCP 服务器）见 PR 报告里的实机记录。
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from pet.chat import anthropic_provider as ap
from pet.chat import connectors
from pet.chat.models import ChatSettings, ProviderConfig
from pet.chat.providers import ProviderError

GITHUB = {"type": "url", "url": connectors.GITHUB_MCP_URL, "name": "github", "authorization_token": "ghp_test"}


# ---------------------------------------------------------------- 替身

class _ApiError(Exception):
    def __init__(self, message, status_code):
        super().__init__(message)
        self.message, self.status_code = message, status_code


class _FakeSdk:
    AnthropicError = APIStatusError = _ApiError

    class APIConnectionError(Exception):
        pass

    class AuthenticationError(_ApiError):
        pass

    class PermissionDeniedError(_ApiError):
        pass

    class NotFoundError(_ApiError):
        pass

    class RateLimitError(_ApiError):
        pass


class _Stream:
    def __init__(self, chunks, stop_reason="end_turn", error=None):
        self._chunks, self._error = list(chunks), error
        self.final = SimpleNamespace(stop_reason=stop_reason, stop_details=None,
                                     content=[SimpleNamespace(type="text", text=c) for c in chunks])

    def __enter__(self):
        if self._error is not None:
            raise self._error
        return self

    def __exit__(self, *_exc):
        return False

    @property
    def text_stream(self):
        yield from self._chunks

    def get_final_message(self):
        return self.final

    def close(self):
        pass


class _Client:
    """按顺序吐出给定的流；记录每次请求走的入口与参数。"""

    def __init__(self, *streams):
        self._streams = list(streams)
        self.calls: list[tuple[str, dict]] = []
        self.messages = SimpleNamespace(stream=lambda **kw: self._open("messages", kw))
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=lambda **kw: self._open("beta", kw)))

    def _open(self, surface, kwargs):
        self.calls.append((surface, kwargs))
        return self._streams.pop(0)


class _MemoryStore:
    """假钥匙串：实例共享一个字典。"""

    shared: dict[str, str] = {}
    writable = True

    def __init__(self, *_args, **_kwargs):
        pass

    def get(self, ref):
        return self.shared.get(ref, "") if ref else ""

    def set(self, ref, value):
        if not self.writable:
            return False
        self.shared[ref] = value
        return True


@pytest.fixture
def store(monkeypatch):
    _MemoryStore.shared, _MemoryStore.writable = {}, True
    monkeypatch.setattr("pet.chat.models.SecretStore", _MemoryStore)
    return _MemoryStore


def _use(monkeypatch, *streams) -> _Client:
    client = _Client(*streams)
    monkeypatch.setattr(ap, "_sdk", lambda: _FakeSdk)
    monkeypatch.setattr(ap, "_client", lambda *a, **k: client)
    return client


def _claude(**overrides) -> ProviderConfig:
    cfg = ProviderConfig("claude", name="Claude", base_url="https://api.anthropic.com",
                         model="claude-sonnet-5", api_key="sk-ant-test")
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def _run(config) -> list[str]:
    return list(ap.AnthropicProvider().stream([{"role": "user", "content": "嗨"}], config, threading.Event()))


# ---------------------------------------------------------------- 请求形状

def test_connector_servers_ride_along_with_their_toolsets(monkeypatch):
    client = _use(monkeypatch, _Stream(["查到了"]))

    assert _run(_claude(mcp_servers=[GITHUB])) == ["查到了"]

    surface, kwargs = client.calls[0]
    assert surface == "beta" and kwargs["betas"] == ["mcp-client-2025-11-20"]
    assert kwargs["mcp_servers"] == [GITHUB]
    assert kwargs["tools"] == [{"type": "mcp_toolset", "mcp_server_name": "github",
                                "cache_control": {"type": "ephemeral"}}], \
        "只带 mcp_servers 不带 toolset 会被 API 拒掉；toolset 上的缓存断点让约 1.2 万 token 的工具定义跨会话命中"
    assert kwargs["cache_control"] == {"type": "ephemeral"}, "同一会话的后续轮次靠顶层自动缓存命中"


def test_requests_without_connectors_are_unchanged(monkeypatch):
    client = _use(monkeypatch, _Stream(["好"]))

    _run(_claude())

    surface, kwargs = client.calls[0]
    assert surface == "messages"
    assert not {"mcp_servers", "tools", "betas", "cache_control"} & set(kwargs)


def test_connectors_combine_with_the_refusal_fallback(monkeypatch):
    client = _use(monkeypatch, _Stream(["好"]))

    _run(_claude(model="claude-opus-5", mcp_servers=[GITHUB]))

    surface, kwargs = client.calls[0]
    assert surface == "beta" and kwargs["fallbacks"] == "default"
    assert kwargs["betas"] == ["server-side-fallback-2026-07-01", "mcp-client-2025-11-20"]


def test_screen_reading_never_carries_connectors(monkeypatch):
    client = _use(monkeypatch, _Stream(["在写代码"]))

    ap.describe_image(b"jpeg", "截图", "你是桌宠", _claude(mcp_servers=[GITHUB]),
                      model="claude-sonnet-5", base_url="", api_key="k")

    assert "mcp_servers" not in client.calls[0][1], "识屏是后台定时请求，不该多花工具定义的钱"


def test_a_paused_turn_is_resumed_until_it_finishes(monkeypatch):
    """服务端工具跑得久时 API 以 pause_turn 收尾：把这段原样接回去再发，直到真的说完。"""
    paused = _Stream(["先查一下，"], stop_reason="pause_turn")
    client = _use(monkeypatch, paused, _Stream(["一共 3 条提交。"]))

    assert _run(_claude(mcp_servers=[GITHUB])) == ["先查一下，", "一共 3 条提交。"]

    assert len(client.calls) == 2
    resumed = client.calls[1][1]["messages"]
    assert resumed[-1] == {"role": "assistant", "content": paused.final.content}
    assert resumed[:-1] == client.calls[0][1]["messages"]


def test_a_turn_that_never_stops_pausing_is_cut_off(monkeypatch):
    client = _use(monkeypatch, *(_Stream(["…"], stop_reason="pause_turn") for _ in range(20)))

    with pytest.raises(ProviderError, match="没有说完"):
        _run(_claude(mcp_servers=[GITHUB]))

    assert len(client.calls) <= 6, "续跑必须有上限，不能把额度烧在一个停不下来的回合上"


def test_a_rejected_token_points_at_the_connector_setting(monkeypatch):
    """Token 失效时 API 报的是 400 + 一句英文；用户需要知道去哪儿改。"""
    _use(monkeypatch, _Stream([], error=_ApiError(
        "mcp_servers[0] 'github': Authentication error while communicating with MCP server. "
        "Please check your authorization token.", 400)))

    with pytest.raises(ProviderError) as info:
        _run(_claude(mcp_servers=[GITHUB]))

    assert info.value.status == 400
    assert "连接器" in str(info.value) and "Token" in str(info.value)
    assert "ghp_test" not in str(info.value)


# ---------------------------------------------------------------- 什么时候挂连接器

def _settings(**overrides) -> ChatSettings:
    settings = ChatSettings.defaults()
    settings.providers = {"claude": _claude()}
    settings.active_provider = "claude"
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings


def test_github_is_attached_only_when_enabled_with_a_token_on_the_claude_channel(store):
    on = _settings(github_connector=True)
    assert connectors.mcp_servers_for(on, on.active_config) == [], "没填 Token"

    store.shared[connectors.GITHUB_TOKEN_REF] = "  ghp_live \n"
    assert connectors.mcp_servers_for(on, on.active_config) == [
        {"type": "url", "url": "https://api.githubcopilot.com/mcp/readonly", "name": "github",
         "authorization_token": "ghp_live"}]

    assert connectors.mcp_servers_for(_settings(), _claude()) == [], "默认关闭"
    assert connectors.mcp_servers_for(on, ProviderConfig("ds")) == [], "OpenAI 兼容通道没有 MCP connector"
    gateway = _claude(base_url="https://gateway.corp.example/claude", api_format="anthropic")
    assert connectors.mcp_servers_for(on, gateway) == [], "MCP connector 只在直连 Claude API 时可用"


def test_the_switch_persists_and_the_token_never_reaches_disk(store):
    assert ChatSettings.defaults().github_connector is False
    saved = _settings(github_connector=True)
    saved.active_config.mcp_servers = [GITHUB]

    data = saved.to_dict(include_secrets=True)

    assert ChatSettings.from_dict(data).github_connector is True
    assert "ghp_test" not in repr(data), "运行期挂上的 Token 不能跟着 Provider 配置落盘"
    assert ChatSettings.from_dict(data).active_config.mcp_servers == []


def test_config_resolves_connectors_from_the_saved_settings(tmp_path, store):
    from pet.config import Config

    config = Config(base=tmp_path)
    settings = config.chat_settings()
    settings.providers = {"claude": _claude()}
    settings.active_provider = "claude"
    settings.github_connector = True
    config.set_chat_settings(settings)
    store.shared[connectors.GITHUB_TOKEN_REF] = "ghp_live"

    servers = config.resolve_mcp_servers(config.chat_settings().active_config)

    assert [s["name"] for s in servers] == ["github"] and servers[0]["authorization_token"] == "ghp_live"


# ---------------------------------------------------------------- 对话窗口接线

class _RecordingService:
    busy = False

    def __init__(self):
        self.sent: list[tuple[list, ProviderConfig]] = []

    def send(self, messages, config, request_id=None):
        self.sent.append((messages, config))
        return "rid-1"

    def stop(self):
        pass


def _github_ready_config(tmp_path, store):
    from pet.config import Config

    config = Config(base=tmp_path)
    settings = config.chat_settings()
    settings.providers = {"claude": _claude(api_key="")}
    settings.active_provider = "claude"
    settings.github_connector = True
    config.set_chat_settings(settings)
    store.shared.update({"provider/claude": "sk-ant-test", connectors.GITHUB_TOKEN_REF: "ghp_live"})
    return config


@pytest.mark.parametrize("window_path", ["pet.chat.widgets:ChatWindow", "pet.chat.legacy_widgets:ChatWindow"])
def test_chat_windows_send_with_the_connector_attached(tmp_path, store, window_path):
    import importlib

    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    module, name = window_path.split(":")
    window = getattr(importlib.import_module(module), name)(_github_ready_config(tmp_path, store), "shenshen")
    try:
        window.service = _RecordingService()
        window.input.setPlainText("我的仓库最近有什么提交？")
        window.send_message()
        _messages, sent = window.service.sent[0]
        assert [s["name"] for s in sent.mcp_servers] == ["github"]
    finally:
        window.close()


def test_quick_chat_sends_with_the_connector_attached(tmp_path, store):
    from PySide6.QtWidgets import QApplication

    from pet.quick_chat import QuickChatBubble

    QApplication.instance() or QApplication([])
    bubble = QuickChatBubble(_github_ready_config(tmp_path, store))
    try:
        bubble.service = _RecordingService()
        bubble.input.setText("我的仓库最近有什么提交？")
        bubble._send()
        assert [s["name"] for s in bubble.service.sent[0][1].mcp_servers] == ["github"]
    finally:
        bubble.close()


# ---------------------------------------------------------------- 设置页

def _page(tmp_path):
    from PySide6.QtWidgets import QApplication

    from pet.chat.ai_settings_page import _AiSettingsPage
    from pet.config import Config

    QApplication.instance() or QApplication([])
    config = Config(base=tmp_path)
    return config, _AiSettingsPage(config)


def test_settings_page_saves_the_switch_and_keeps_the_token_in_the_keyring(tmp_path, store):
    from pet.config import Config

    config, page = _page(tmp_path)
    try:
        assert page.github_connector.isChecked() is False, "默认关闭"
        page.github_connector.setChecked(True)
        page.github_token.setText("  ghp_from_ui ")
        page.save()
        config.save()
    finally:
        page.deleteLater()

    assert store.shared[connectors.GITHUB_TOKEN_REF] == "ghp_from_ui"
    assert "ghp_from_ui" not in config.path.read_text(encoding="utf-8")
    reopened_config = Config(base=tmp_path)
    assert reopened_config.chat_settings().github_connector is True
    _config, reopened = _page(tmp_path)
    try:
        assert reopened.github_connector.isChecked() is True
        assert reopened.github_token.text() == "", "已保存的 Token 不回显"
        reopened.save()                  # 输入框留空 = 不修改
    finally:
        reopened.deleteLater()
    assert store.shared[connectors.GITHUB_TOKEN_REF] == "ghp_from_ui"


def test_token_row_follows_the_switch(tmp_path, store):
    from pet.settings_widgets import SettingRow

    _config, page = _page(tmp_path)
    try:
        row = page.findChild(SettingRow, "settingRow_github_token")
        assert row.isHidden() is True
        page.github_connector.setChecked(True)
        assert row.isHidden() is False
    finally:
        page.deleteLater()


def test_switch_stays_off_when_the_token_cannot_be_stored(tmp_path, store, monkeypatch):
    """钥匙串不可用时 Token 存不下来：与其留一个每次都报错的开关，不如不开。"""
    from PySide6.QtWidgets import QMessageBox

    warnings: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, text, *a, **k: warnings.append(text))
    store.writable = False
    config, page = _page(tmp_path)
    try:
        page.github_connector.setChecked(True)
        page.github_token.setText("ghp_from_ui")
        page.save()
    finally:
        page.deleteLater()

    assert config.chat_settings().github_connector is False
    assert warnings and "Token" in warnings[0]
