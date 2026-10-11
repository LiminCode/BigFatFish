# -*- coding: utf-8 -*-
"""Claude 通道（Anthropic Messages API，官方 SDK），与 OpenAI 兼容通道并存。

桌宠的会话、识屏、文件解读都按 OpenAI 的消息形状组织（``role`` + ``content``，
图片是 ``image_url``）。本模块在边界上把它换成 Messages API 的形状，其余代码
不必知道对面是哪家：

- ``uses_anthropic(config)``：这个服务商走不走 Claude 通道。``api_format`` 明确写了
  就听它的；``auto``（默认）看地址是不是 ``api.anthropic.com``。
- ``AnthropicProvider.stream``：与 ``OpenAICompatibleProvider.stream`` 同签名的流式对话。
- ``describe_image``：识屏（一张截图 + 一段提示 → 一段话）。
- ``RoutingProvider`` / ``test_connection``：按配置选通道，调用方只认这两个入口。

与 OpenAI 兼容通道的几处有意差异：

- **不发 ``temperature``**：当前的 Claude 模型已移除采样参数，发了就是 400。
- **``max_tokens`` 至少 16000**：Claude Opus 5 默认开着自适应思考，思考与回答共用
  这份额度；沿用聊天设置里的 2048 会让回答被思考挤掉。
- **拒答要显式处理**：``stop_reason == "refusal"`` 时 HTTP 是 200，正文可能为空。
  对支持的模型默认开启服务端回退（``fallbacks: "default"``）——被拒的请求由
  Anthropic 推荐的备用模型重跑，按备用模型计费。
- **API Key 留空时**交给 SDK 从环境里找（``ANTHROPIC_API_KEY`` / ``ant auth login``
  的登录态），不是直接报「没配 Key」。

SDK 在函数内按需导入：没装 ``anthropic`` 的环境（含未收集它的打包变体）里，其它
服务商照常可用，只有真的选了 Claude 通道才报错。
"""

from __future__ import annotations

import base64
import threading
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlparse

from . import providers as _openai_compat
from .models import ProviderConfig
from .providers import ProviderError

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_BASE_URL = "https://api.anthropic.com"
_ANTHROPIC_HOST = "api.anthropic.com"
_MIN_MAX_TOKENS = 16000
_FALLBACK_BETA = "server-side-fallback-2026-07-01"
#: 默认开启服务端拒答回退的模型（见模块说明）
_FALLBACK_MODELS = frozenset({"claude-opus-5", "claude-fable-5-1"})


def uses_anthropic(config, base_url: str | None = None) -> bool:
    """这个服务商（或它名下 ``base_url`` 指向的那个端点）走不走 Claude 通道。

    ``base_url`` 用于识屏的独立视觉端点：它和聊天端点可以是两家，这时只看地址，
    ``api_format`` 说的是聊天端点，不能套到另一家头上。
    """
    own_url = str(getattr(config, "base_url", "") or "")
    url = own_url if base_url is None else str(base_url or "")
    if url == own_url:
        fmt = str(getattr(config, "api_format", "auto") or "auto").strip().lower()
        if fmt == "anthropic":
            return True
        if fmt == "openai":
            return False
    host = (urlparse(url).hostname or "").lower()
    return host == _ANTHROPIC_HOST or host.endswith("." + _ANTHROPIC_HOST)


def _sdk():
    try:
        import anthropic
    except ImportError as exc:
        raise ProviderError("没有安装 anthropic SDK，Claude 通道不可用（pip install anthropic）") from exc
    return anthropic


def _client(api_key: str, base_url: str, timeout: float, verify_ssl: bool, *, max_retries: int | None = None):
    sdk = _sdk()
    kwargs: dict[str, Any] = {"timeout": float(timeout)}
    api_key = str(api_key or "").strip()      # 粘贴带进来的空格 / 换行会让请求头非法
    if api_key:
        kwargs["api_key"] = api_key
    base = str(base_url or "").strip().rstrip("/")
    if base.endswith("/v1"):          # 按 OpenAI 的习惯多填了版本段：SDK 自己会补
        base = base[:-3]
    if base and base != DEFAULT_BASE_URL:
        kwargs["base_url"] = base
    if max_retries is not None:
        kwargs["max_retries"] = int(max_retries)
    if not verify_ssl:
        kwargs["http_client"] = sdk.DefaultHttpxClient(verify=False)
    try:
        return sdk.Anthropic(**kwargs)
    except sdk.AnthropicError as exc:   # 没有任何可用凭据时构造即失败
        raise ProviderError(f"Claude 通道没有可用的 API Key：{exc}") from exc


# ---------------------------------------------------------------- 消息形状转换

def _image_block(url: str) -> dict | None:
    url = str(url or "").strip()
    if url.startswith("data:") and ";base64," in url:
        header, data = url[5:].split(";base64,", 1)
        return {"type": "image", "source": {"type": "base64", "media_type": header or "image/jpeg", "data": data}}
    if url.startswith(("http://", "https://")):
        return {"type": "image", "source": {"type": "url", "url": url}}
    return None


def _blocks(content: Any) -> list[dict]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content.strip() else []
    blocks: list[dict] = []
    for part in content if isinstance(content, list) else []:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text":
            text = str(part.get("text") or "")
            if text.strip():                       # 空文本块会被 API 拒绝
                blocks.append({"type": "text", "text": text})
        elif part.get("type") == "image_url":
            image = part.get("image_url")
            block = _image_block(image.get("url") if isinstance(image, dict) else image)
            if block is not None:
                blocks.append(block)
    return blocks


def _plain_text(content: Any) -> str:
    return "\n".join(b["text"] for b in _blocks(content) if b["type"] == "text")


def to_anthropic_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict]]:
    """OpenAI 形状的消息列表 → ``(system, messages)``。

    system 消息提到顶层；相邻同角色的消息合并；开头不是 user 的、结尾是 assistant
    的都去掉——Messages API 要求从 user 开始，而当前模型不接受「预填」的 assistant 结尾。
    """
    system: list[str] = []
    out: list[dict] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role, content = message.get("role"), message.get("content")
        if role == "system":
            text = _plain_text(content)
            if text:
                system.append(text)
            continue
        if role not in ("user", "assistant"):
            continue
        blocks = _blocks(content)
        if not blocks:
            continue
        if out and out[-1]["role"] == role:
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": role, "content": blocks})
    while out and out[0]["role"] != "user":
        out.pop(0)
    while out and out[-1]["role"] == "assistant":
        out.pop()
    return "\n\n".join(system), out


# ---------------------------------------------------------------- 请求

def _open_stream(client, model: str, system: str, messages: list[dict], max_tokens: int):
    kwargs: dict[str, Any] = {"model": model, "max_tokens": max(int(max_tokens), _MIN_MAX_TOKENS),
                              "messages": messages}
    if system:
        kwargs["system"] = system
    if model in _FALLBACK_MODELS:
        return client.beta.messages.stream(betas=[_FALLBACK_BETA], fallbacks="default", **kwargs)
    return client.messages.stream(**kwargs)


def _check_final(final) -> None:
    if getattr(final, "stop_reason", None) != "refusal":
        return
    details = getattr(final, "stop_details", None)
    explanation = str(getattr(details, "explanation", "") or "").strip()
    raise ProviderError("Claude 拒绝了这次请求" + (f"：{explanation}" if explanation else ""))


def _translate_error(sdk, exc: Exception, model: str) -> ProviderError:
    """SDK 的类型化异常 → 桌宠统一的 ProviderError（由具体到宽泛逐级匹配）。"""
    if isinstance(exc, sdk.AuthenticationError):
        return ProviderError("认证失败：API Key 无效或已失效", 401)
    if isinstance(exc, sdk.PermissionDeniedError):
        return ProviderError("这个 API Key 没有权限访问该模型或功能", 403)
    if isinstance(exc, sdk.NotFoundError):
        return ProviderError(f"模型或端点不存在：{model}（Claude 模型名形如 {DEFAULT_MODEL}）", 404)
    if isinstance(exc, sdk.RateLimitError):
        return ProviderError("请求过于频繁或额度不足，稍后再试", 429)
    if isinstance(exc, sdk.APIStatusError):
        status = getattr(exc, "status_code", None)
        return ProviderError(str(getattr(exc, "message", "") or exc), status)
    if isinstance(exc, sdk.APIConnectionError):
        return ProviderError(f"网络连接失败：{exc}")
    if "authentication method" in str(exc):
        # 没有任何凭据时 SDK 抛的是 TypeError（不是它自己的异常基类），且要到发请求时才抛
        return ProviderError("没有配置 API Key（设置 → AI 对话），环境里也没有 Anthropic 凭据")
    return ProviderError(f"Claude 请求失败：{exc}")


class AnthropicProvider:
    """流式对话；签名与 ``OpenAICompatibleProvider.stream`` 一致。"""

    def stream(self, messages: list[dict[str, Any]], config: ProviderConfig,
               cancel_event: threading.Event, response_holder: list | None = None) -> Iterator[str]:
        sdk = _sdk()
        system, convo = to_anthropic_messages(messages)
        if not convo:
            raise ProviderError("没有可发送的消息")
        model = str(config.model or "").strip() or DEFAULT_MODEL
        client = _client(config.api_key, config.base_url, config.timeout, config.verify_ssl)
        try:
            with _open_stream(client, model, system, convo, config.max_tokens) as stream:
                if response_holder is not None:
                    response_holder.append(stream)      # 取消时由 ChatService 调它的 close()
                for text in stream.text_stream:
                    if cancel_event.is_set():
                        return
                    yield text
                if cancel_event.is_set():
                    return
                _check_final(stream.get_final_message())
        except ProviderError:
            raise
        except Exception as exc:
            # 不只接 sdk.AnthropicError：SDK 有些失败抛内建异常（缺凭据是 TypeError），
            # 漏出去的话调用方的工作线程会直接死掉，界面永远等不到结果。
            if cancel_event.is_set():
                return                                   # 取消时连接被关掉引出的错误不算失败
            raise _translate_error(sdk, exc, model) from exc


def describe_image(jpeg_bytes: bytes, user_text: str, system_prompt: str, config: ProviderConfig, *,
                   model: str, base_url: str, api_key: str) -> str:
    """识屏：一张 JPEG + 一段提示 → 模型的一段话。失败抛 ProviderError。

    不自动重试（``max_retries=0``）：主动识屏按真实请求次数扣每日额度，SDK 悄悄重试
    会让实际请求数超过记账数。
    """
    sdk = _sdk()
    model = str(model or "").strip() or DEFAULT_MODEL
    client = _client(api_key, base_url, max(float(config.timeout), 60.0), config.verify_ssl, max_retries=0)
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                     "data": base64.standard_b64encode(jpeg_bytes).decode("ascii")}},
        {"type": "text", "text": user_text},
    ]
    try:
        with _open_stream(client, model, system_prompt, [{"role": "user", "content": content}],
                          _MIN_MAX_TOKENS) as stream:
            final = stream.get_final_message()
    except Exception as exc:
        raise _translate_error(sdk, exc, model) from exc
    _check_final(final)
    text = "".join(block.text for block in final.content if block.type == "text").strip()
    if not text:
        raise ProviderError("Claude 没说话（空回复）")
    return text


def _test_anthropic(config, timeout: float) -> tuple[bool, str]:
    """用 token 计数接口验证 Key 与模型名：不生成内容，不花输出额度。"""
    try:
        sdk = _sdk()
        model = str(config.model or "").strip() or DEFAULT_MODEL
        client = _client(config.api_key, config.base_url, timeout, config.verify_ssl, max_retries=0)
        try:
            client.messages.count_tokens(model=model, messages=[{"role": "user", "content": "ping"}])
        except Exception as exc:
            raise _translate_error(sdk, exc, model) from exc
    except ProviderError as exc:
        return False, str(exc)
    return True, f"连接成功（Claude · {model}）"


# ---------------------------------------------------------------- 按配置选通道

class RoutingProvider:
    """按服务商配置把请求交给 Claude 通道或 OpenAI 兼容通道。"""

    def __init__(self, openai_compatible=None, anthropic=None) -> None:
        self._openai = openai_compatible or _openai_compat.OpenAICompatibleProvider()
        self._anthropic = anthropic or AnthropicProvider()

    def stream(self, messages: list[dict[str, Any]], config: ProviderConfig,
               cancel_event: threading.Event, response_holder: list | None = None) -> Iterator[str]:
        target = self._anthropic if uses_anthropic(config) else self._openai
        yield from target.stream(messages, config, cancel_event, response_holder=response_holder)


def test_connection(config, timeout: float = 10.0) -> tuple[bool, str]:
    """设置页「测试连接」的统一入口：返回 (是否成功, 说明)。"""
    if uses_anthropic(config):
        return _test_anthropic(config, timeout)
    return _openai_compat.test_connection(config, timeout=timeout)
