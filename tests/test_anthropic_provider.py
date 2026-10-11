# -*- coding: utf-8 -*-
"""Claude 通道（pet/chat/anthropic_provider.py）。

网络边界用替身：``_client`` 返回假客户端，记录发出去的请求、按脚本吐流。SDK 的
异常类型用同名替身（真异常要拿 HTTP 响应对象才能构造）。另有几条用真 SDK 构造
客户端（不发请求），钉住本模块依赖的 SDK 接口确实存在。
"""

from __future__ import annotations

import base64
import threading
from types import SimpleNamespace

import pytest

from pet.chat import anthropic_provider as ap
from pet.chat.models import ChatSettings, ProviderConfig
from pet.chat.providers import ProviderError


# ---------------------------------------------------------------- 替身

class _FakeSdk:
    class AnthropicError(Exception):
        pass

    class APIConnectionError(AnthropicError):
        pass

    class APIStatusError(AnthropicError):
        def __init__(self, message="boom", status_code=500):
            super().__init__(message)
            self.message, self.status_code = message, status_code

    class AuthenticationError(APIStatusError):
        pass

    class PermissionDeniedError(APIStatusError):
        pass

    class NotFoundError(APIStatusError):
        pass

    class RateLimitError(APIStatusError):
        pass


class _FakeStream:
    def __init__(self, chunks, *, stop_reason="end_turn", explanation="", error=None, on_text=None):
        self._chunks, self._error, self._on_text = list(chunks), error, on_text
        self.closed = False
        self._final = SimpleNamespace(
            stop_reason=stop_reason,
            stop_details=SimpleNamespace(explanation=explanation) if stop_reason == "refusal" else None,
            content=[SimpleNamespace(type="thinking", thinking=""),
                     *(SimpleNamespace(type="text", text=c) for c in chunks)])

    def __enter__(self):
        if self._error is not None:
            raise self._error
        return self

    def __exit__(self, *_exc):
        self.closed = True
        return False

    @property
    def text_stream(self):
        for chunk in self._chunks:
            if self._on_text is not None:
                self._on_text(chunk)
            yield chunk

    def get_final_message(self):
        return self._final

    def close(self):
        self.closed = True


class _FakeClient:
    def __init__(self, stream):
        self.calls: list[tuple[str, dict]] = []
        self.counted: list[dict] = []
        self._stream = stream
        self.count_error = None
        self.messages = SimpleNamespace(stream=lambda **kw: self._open("messages", kw),
                                        count_tokens=self._count)
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=lambda **kw: self._open("beta", kw)))

    def _open(self, surface, kwargs):
        self.calls.append((surface, kwargs))
        return self._stream

    def _count(self, **kwargs):
        self.counted.append(kwargs)
        if self.count_error is not None:
            raise self.count_error
        return SimpleNamespace(input_tokens=1)


@pytest.fixture
def fake(monkeypatch):
    """装上假 SDK 与假客户端；返回一个可换流、可查调用的把手。"""
    handle = SimpleNamespace(client=_FakeClient(_FakeStream(["你", "好"])), client_args=[])

    def _client(api_key, base_url, timeout, verify_ssl, *, max_retries=None):
        handle.client_args.append({"api_key": api_key, "base_url": base_url, "timeout": timeout,
                                   "verify_ssl": verify_ssl, "max_retries": max_retries})
        return handle.client

    monkeypatch.setattr(ap, "_sdk", lambda: _FakeSdk)
    monkeypatch.setattr(ap, "_client", _client)
    return handle


def _claude(**overrides) -> ProviderConfig:
    cfg = ProviderConfig("claude", name="Claude", base_url="https://api.anthropic.com",
                         model="claude-opus-5", api_key="sk-ant-test")
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def _run(messages, config, cancel=None, holder=None) -> list[str]:
    return list(ap.AnthropicProvider().stream(messages, config, cancel or threading.Event(), holder))


# ---------------------------------------------------------------- 选通道

def test_channel_is_picked_by_host_unless_the_format_says_otherwise():
    assert ap.uses_anthropic(_claude()) is True
    assert ap.uses_anthropic(_claude(base_url="https://api.anthropic.com/v1")) is True
    assert ap.uses_anthropic(ProviderConfig("ds")) is False, "默认的 DeepSeek 配置不受影响"
    assert ap.uses_anthropic(_claude(base_url="https://gateway.corp.example/claude")) is False
    assert ap.uses_anthropic(_claude(base_url="https://gateway.corp.example/claude", api_format="anthropic")) is True
    assert ap.uses_anthropic(_claude(api_format="openai")) is False


def test_separate_vision_endpoint_is_judged_by_its_own_address():
    """识屏走另一家（比如智谱的免费视觉）时，聊天端点的 api_format 不能套到它头上。"""
    cfg = _claude(api_format="anthropic")
    assert ap.uses_anthropic(cfg, "https://open.bigmodel.cn/api/paas/v4") is False
    ds = ProviderConfig("ds")
    assert ap.uses_anthropic(ds, "https://api.anthropic.com") is True


def test_api_format_round_trips_and_is_normalised():
    assert ProviderConfig("p").api_format == "auto"
    assert ProviderConfig.from_dict("p", {"api_format": "Anthropic"}).api_format == "anthropic"
    assert ProviderConfig.from_dict("p", {"api_format": "nonsense"}).api_format == "auto"
    settings = ChatSettings.from_dict({"providers": {"c": {"api_format": "anthropic"}}})
    assert ChatSettings.from_dict(settings.to_dict()).providers["c"].api_format == "anthropic"


# ---------------------------------------------------------------- 消息形状

def test_messages_are_reshaped_for_the_messages_api():
    jpeg = base64.b64encode(b"jpeg-bytes").decode()
    system, convo = ap.to_anthropic_messages([
        {"role": "assistant", "content": "开场白（没有对应的 user，得丢掉）"},
        {"role": "system", "content": "你是桌宠"},
        {"role": "user", "content": "你好"},
        {"role": "user", "content": [
            {"type": "text", "text": "看这张图"},
            {"type": "text", "text": "   "},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{jpeg}"}},
            {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
        ]},
        {"role": "assistant", "content": ""},
        {"role": "tool", "content": "忽略"},
        {"role": "system", "content": "说中文"},
        {"role": "assistant", "content": "结尾的 assistant 是预填，得丢掉"},
    ])

    assert system == "你是桌宠\n\n说中文"
    assert convo == [{"role": "user", "content": [
        {"type": "text", "text": "你好"},
        {"type": "text", "text": "看这张图"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": jpeg}},
        {"type": "image", "source": {"type": "url", "url": "https://example.com/a.png"}},
    ]}]


# ---------------------------------------------------------------- 流式对话

def test_stream_yields_text_and_sends_a_clean_request(fake):
    holder: list = []
    out = _run([{"role": "system", "content": "你是桌宠"}, {"role": "user", "content": "嗨"}],
               _claude(temperature=0.7, max_tokens=2048), holder=holder)

    assert out == ["你", "好"]
    surface, kwargs = fake.client.calls[0]
    assert kwargs["model"] == "claude-opus-5" and kwargs["system"] == "你是桌宠"
    assert kwargs["messages"] == [{"role": "user", "content": [{"type": "text", "text": "嗨"}]}]
    assert kwargs["max_tokens"] >= 16000, "思考与回答共用额度：2048 会让回答被思考挤掉"
    assert "temperature" not in kwargs and "top_p" not in kwargs, "当前模型已移除采样参数，发了就是 400"
    assert "thinking" not in kwargs
    assert holder and hasattr(holder[0], "close"), "取消时 ChatService 靠它关连接"
    assert fake.client_args[0]["api_key"] == "sk-ant-test"


def test_refusal_fallback_is_on_for_supported_models_only(fake):
    _run([{"role": "user", "content": "嗨"}], _claude(model="claude-opus-5"))
    _run([{"role": "user", "content": "嗨"}], _claude(model="claude-haiku-4-5"))

    (surface1, kw1), (surface2, kw2) = fake.client.calls
    assert surface1 == "beta" and kw1["fallbacks"] == "default"
    assert kw1["betas"] == ["server-side-fallback-2026-07-01"]
    assert surface2 == "messages" and "fallbacks" not in kw2 and "betas" not in kw2


def test_blank_model_defaults_to_claude_opus_5(fake):
    _run([{"role": "user", "content": "嗨"}], _claude(model="  "))
    assert fake.client.calls[0][1]["model"] == "claude-opus-5"


def test_refusal_is_reported_not_swallowed(fake):
    fake.client = _FakeClient(_FakeStream([], stop_reason="refusal", explanation="policy"))
    with pytest.raises(ProviderError, match="拒绝.*policy"):
        _run([{"role": "user", "content": "嗨"}], _claude())


def test_cancel_stops_the_stream_quietly(fake):
    cancel = threading.Event()
    fake.client = _FakeClient(_FakeStream(["一", "二", "三"], on_text=lambda c: c == "二" and cancel.set()))
    assert _run([{"role": "user", "content": "嗨"}], _claude(), cancel=cancel) == ["一"]


def test_nothing_to_send_is_an_error(fake):
    with pytest.raises(ProviderError, match="没有可发送"):
        _run([{"role": "system", "content": "只有系统提示"}], _claude())
    assert fake.client.calls == []


@pytest.mark.parametrize("error, status, needle", [
    (_FakeSdk.AuthenticationError("bad key", 401), 401, "认证失败"),
    (_FakeSdk.PermissionDeniedError("no", 403), 403, "没有权限"),
    (_FakeSdk.NotFoundError("no model", 404), 404, "claude-opus-5"),
    (_FakeSdk.RateLimitError("slow down", 429), 429, "频繁"),
    (_FakeSdk.APIStatusError("overloaded", 529), 529, "overloaded"),
    (_FakeSdk.APIConnectionError("dns"), None, "网络连接失败"),
])
def test_sdk_errors_become_provider_errors(fake, error, status, needle):
    fake.client = _FakeClient(_FakeStream([], error=error))
    with pytest.raises(ProviderError) as info:
        _run([{"role": "user", "content": "嗨"}], _claude(model="deepseek-v4-flash"))
    assert info.value.status == status and needle in str(info.value)


def test_errors_caused_by_cancelling_are_not_failures(fake):
    cancel = threading.Event()
    cancel.set()
    fake.client = _FakeClient(_FakeStream([], error=_FakeSdk.APIConnectionError("closed")))
    assert _run([{"role": "user", "content": "嗨"}], _claude(), cancel=cancel) == []


# ---------------------------------------------------------------- 识屏

def test_describe_image_sends_the_screenshot_before_the_prompt(fake):
    fake.client = _FakeClient(_FakeStream(["在写代码呢"]))

    text = ap.describe_image(b"\xff\xd8jpeg", "这是截图", "你是桌宠", _claude(timeout=5),
                             model="claude-opus-5", base_url="https://api.anthropic.com", api_key="k")

    assert text == "在写代码呢"
    kwargs = fake.client.calls[0][1]
    image, prompt = kwargs["messages"][0]["content"]
    assert image == {"type": "image", "source": {
        "type": "base64", "media_type": "image/jpeg",
        "data": base64.standard_b64encode(b"\xff\xd8jpeg").decode()}}
    assert prompt == {"type": "text", "text": "这是截图"} and kwargs["system"] == "你是桌宠"
    args = fake.client_args[0]
    assert args["max_retries"] == 0, "识屏按真实请求次数扣每日额度，不许 SDK 悄悄重试"
    assert args["timeout"] >= 60 and args["api_key"] == "k"


def test_describe_image_rejects_empty_answers_and_refusals(fake):
    fake.client = _FakeClient(_FakeStream([]))
    with pytest.raises(ProviderError, match="空回复"):
        ap.describe_image(b"x", "t", "s", _claude(), model="m", base_url="", api_key="k")
    fake.client = _FakeClient(_FakeStream([], stop_reason="refusal"))
    with pytest.raises(ProviderError, match="拒绝"):
        ap.describe_image(b"x", "t", "s", _claude(), model="m", base_url="", api_key="k")


# ---------------------------------------------------------------- 路由与连接测试

class _Recorder:
    def __init__(self, name, log):
        self.name, self.log = name, log

    def stream(self, messages, config, cancel_event, response_holder=None):
        self.log.append((self.name, response_holder))
        yield self.name


def test_routing_provider_picks_the_channel_per_request():
    log: list = []
    router = ap.RoutingProvider(openai_compatible=_Recorder("openai", log), anthropic=_Recorder("claude", log))
    holder: list = []
    cancel = threading.Event()

    assert list(router.stream([], _claude(), cancel, response_holder=holder)) == ["claude"]
    assert list(router.stream([], ProviderConfig("ds"), cancel)) == ["openai"]
    assert log[0] == ("claude", holder), "response_holder 原样传下去（取消要用）"


def test_chat_service_routes_by_default():
    from PySide6.QtWidgets import QApplication

    from pet.chat.service import ChatService

    QApplication.instance() or QApplication([])
    assert isinstance(ChatService().provider, ap.RoutingProvider)


def test_connection_test_uses_token_counting_for_claude(fake, monkeypatch):
    ok, message = ap.test_connection(_claude(), timeout=3)
    assert ok is True and "claude-opus-5" in message
    assert fake.client.counted == [{"model": "claude-opus-5", "messages": [{"role": "user", "content": "ping"}]}]
    assert fake.client.calls == [], "不生成内容，不花输出额度"

    fake.client.count_error = _FakeSdk.AuthenticationError("bad", 401)
    assert ap.test_connection(_claude())[0] is False

    called: list = []
    monkeypatch.setattr(ap._openai_compat, "test_connection",
                        lambda config, timeout=10.0: (called.append(config.provider_id), (True, "ok"))[1])
    assert ap.test_connection(ProviderConfig("ds")) == (True, "ok")
    assert called == ["ds"]


# ---------------------------------------------------------------- 真 SDK（不发请求）

def test_real_sdk_client_is_built_from_the_provider_settings():
    anthropic = pytest.importorskip("anthropic")

    client = ap._client("sk-ant-x", "https://api.anthropic.com/v1/", 30.0, True)
    assert isinstance(client, anthropic.Anthropic)
    assert str(client.base_url).rstrip("/") == "https://api.anthropic.com", "多填的 /v1 要去掉"

    gateway = ap._client("k", "https://gateway.corp.example/claude", 5.0, False, max_retries=0)
    assert str(gateway.base_url).rstrip("/") == "https://gateway.corp.example/claude"
    assert gateway.max_retries == 0


def test_real_sdk_exposes_what_this_module_relies_on():
    anthropic = pytest.importorskip("anthropic")
    import inspect

    client = anthropic.Anthropic(api_key="x")
    beta_params = inspect.signature(client.beta.messages.stream).parameters
    assert {"fallbacks", "betas", "model", "max_tokens", "messages", "system"} <= set(beta_params)
    assert callable(client.messages.count_tokens)
    for name in ("AnthropicError", "APIConnectionError", "APIStatusError", "AuthenticationError",
                 "PermissionDeniedError", "NotFoundError", "RateLimitError", "DefaultHttpxClient"):
        assert hasattr(anthropic, name), name


def test_missing_sdk_is_reported_as_a_provider_error(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _no_anthropic(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("no anthropic")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_anthropic)
    with pytest.raises(ProviderError, match="anthropic SDK"):
        ap._sdk()


# ---------------------------------------------------------------- 识屏接线（pet/vision.py）

def _vision_call(monkeypatch, config, **kwargs):
    from pet import vision

    seen: dict = {}

    def _describe(jpeg, user_text, system_prompt, cfg, *, model, base_url, api_key):
        seen.update(jpeg=jpeg, user_text=user_text, system=system_prompt, model=model,
                    base_url=base_url, api_key=api_key)
        return "看到了"

    monkeypatch.setattr(ap, "describe_image", _describe)
    return vision._post_vision_request(b"jpeg", "notepad.exe | 记事本", "你是桌宠", config, **kwargs), seen


def test_screen_reading_goes_through_the_claude_channel(monkeypatch):
    text, seen = _vision_call(monkeypatch, _claude(), pet_name="大肥鱼")
    assert text == "看到了"
    assert seen["model"] == "claude-opus-5", "Claude 模型本身多模态，识屏直接用聊天模型"
    assert seen["api_key"] == "sk-ant-test" and seen["system"] == "你是桌宠"
    assert "屏幕截图" in seen["user_text"] and "大肥鱼" in seen["user_text"]


def test_screen_reading_respects_the_daily_budget(monkeypatch):
    from pet import vision

    monkeypatch.setattr(ap, "describe_image", lambda *a, **k: pytest.fail("额度用完后不该再发请求"))
    with pytest.raises(vision.VisionError, match="每日请求上限"):
        vision._post_vision_request(b"jpeg", "", "s", _claude(), consume_budget=lambda: False)


def test_screen_reading_on_a_separate_claude_endpoint_never_uses_the_chat_key(monkeypatch):
    """聊天用 DeepSeek、识屏单独指到 Claude：发过去的只能是识屏自己的 Key。"""
    config = ProviderConfig("ds", api_key="sk-deepseek-chat")
    config.vision_same_as_chat = False
    config.vision_base_url = "https://api.anthropic.com"
    config.vision_model = "claude-opus-5"
    config.vision_api_key = "sk-ant-vision"

    _text, seen = _vision_call(monkeypatch, config)
    assert seen["api_key"] == "sk-ant-vision" and seen["model"] == "claude-opus-5"

    from pet import vision

    config.vision_api_key = ""
    with pytest.raises(vision.VisionError, match="未配置 API Key"):
        vision._post_vision_request(b"jpeg", "", "s", config)


def test_claude_errors_surface_as_vision_errors(monkeypatch):
    from pet import vision

    def _boom(*_a, **_k):
        raise ProviderError("认证失败：API Key 无效或已失效", 401)

    monkeypatch.setattr(ap, "describe_image", _boom)
    with pytest.raises(vision.VisionError, match="认证失败"):
        vision._post_vision_request(b"jpeg", "", "s", _claude())


# ---------------------------------------------------------------- 实机事故回归（2026-10-10）
# 设置页点「测试连接」后按钮永远停在「测试中…」：Key 为空时 SDK 抛的是 TypeError
# （不是它自己的 AnthropicError），一路逃出 test_connection，测试线程直接死掉，
# 没有人把按钮恢复回来。

@pytest.fixture
def no_env_credentials(monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(name, raising=False)


def test_missing_key_fails_the_connection_test_instead_of_raising(no_env_credentials):
    pytest.importorskip("anthropic")
    ok, message = ap.test_connection(_claude(api_key=""), timeout=3)      # 真 SDK：凭据缺失在发请求前就报
    assert ok is False and "API Key" in message


def test_missing_key_fails_a_chat_with_a_provider_error(no_env_credentials):
    pytest.importorskip("anthropic")
    with pytest.raises(ProviderError, match="API Key"):
        _run([{"role": "user", "content": "嗨"}], _claude(api_key=""))


def test_pasted_key_whitespace_is_trimmed():
    """粘贴带进来的空格 / 换行会让请求头非法，SDK 只报一句 Connection error。"""
    pytest.importorskip("anthropic")
    assert ap._client("  sk-ant-x \n", "", 5.0, True).api_key == "sk-ant-x"


@pytest.mark.parametrize("error", [RuntimeError("something odd"), TypeError("bad arg"), ValueError("nope")])
def test_unexpected_sdk_exceptions_never_escape(fake, error):
    fake.client = _FakeClient(_FakeStream([], error=error))
    with pytest.raises(ProviderError, match="Claude 请求失败"):
        _run([{"role": "user", "content": "嗨"}], _claude())
    with pytest.raises(ProviderError, match="Claude 请求失败"):
        ap.describe_image(b"x", "t", "s", _claude(), model="m", base_url="", api_key="k")
    fake.client.count_error = error
    assert ap.test_connection(_claude())[0] is False


def test_settings_page_recovers_when_the_connection_test_blows_up(tmp_path):
    """测试线程里无论抛什么，按钮都得恢复——否则只能关掉设置窗口重开。"""
    import time

    from PySide6.QtWidgets import QApplication

    from pet.chat.ai_settings_page import _AiSettingsPage
    from pet.config import Config

    app = QApplication.instance() or QApplication([])
    page = _AiSettingsPage(Config(base=tmp_path))
    try:
        def _boom(provider, timeout=10.0):
            raise TypeError("Could not resolve authentication method")

        page._test_connection = _boom
        page._run_test()
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline and page.test_button.text() != "测试连接":
            app.processEvents()
            time.sleep(0.01)
        assert page.test_button.text() == "测试连接" and page.test_button.isEnabled()
        assert "Could not resolve authentication method" in page.test_result.text()
    finally:
        page.deleteLater()
