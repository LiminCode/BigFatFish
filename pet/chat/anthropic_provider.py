# -*- coding: utf-8 -*-
"""Claude 通道（Anthropic Messages API，官方 SDK），与 OpenAI 兼容通道并存。

肥鱼的会话、识屏、文件解读都按 OpenAI 的消息形状组织（``role`` + ``content``，
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
- **连接器**：``config.mcp_servers`` 非空时请求带上 MCP 服务器与对应 toolset（MCP
  connector，beta），由 Anthropic 的服务器替模型调用工具；回合以 ``pause_turn`` 收尾时
  自动续跑。挂不挂、挂哪些由 ``pet/chat/connectors.py`` 决定，识屏不挂。
- **本地工具**：``config.client_tools`` 非空时带上它的工具定义与用法说明；模型要调用时
  （``stop_reason == "tool_use"``）在本线程执行，把结果接回去再请求，直到模型说完。
  目前只有本地知识库（``pet/chat/knowledge_base.py``）。
- **API Key 留空时**交给 SDK 从环境里找（``ANTHROPIC_API_KEY`` / ``ant auth login``
  的登录态），不是直接报「没配 Key」。

SDK 在函数内按需导入：没装 ``anthropic`` 的环境（含未收集它的打包变体）里，其它
服务商照常可用，只有真的选了 Claude 通道才报错。
"""

from __future__ import annotations

import base64
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from . import providers as _openai_compat
from .models import ProviderConfig
from .providers import ProviderError
from ..i18n import t

DEFAULT_MODEL = "claude-sonnet-5"
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
DEFAULT_EFFORT = "medium"
DEFAULT_BASE_URL = "https://api.anthropic.com"
_ANTHROPIC_HOST = "api.anthropic.com"
_MIN_MAX_TOKENS = 16000
_FALLBACK_BETA = "server-side-fallback-2026-07-01"
#: 默认开启服务端拒答回退的模型（见模块说明）
_FALLBACK_MODELS = frozenset({"claude-opus-5", "claude-fable-5-1"})
_MCP_BETA = "mcp-client-2025-11-20"
#: 一个回合最多续跑几次 pause_turn（服务端工具跑得久时 API 会分段返回）
_MAX_PAUSE_RESUMES = 4
#: 一个回合最多执行几轮本地工具（每轮是一次完整请求）
_MAX_TOOL_ROUNDS = 8


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
        raise ProviderError(t("chat.claude.anthropic_sdk_not_installed_so")) from exc
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
        raise ProviderError(t("chat.claude.no_usable_api_key_claude", exc=exc)) from exc


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

def _effort_for(model: str, effort: str) -> str | None:
    """这个模型该发的 effort；不支持 effort 的模型返回 None（发了就是 400）。

    各代模型接受的档位不同：Haiku 4.5 / Sonnet 4.5 不支持；Opus 4.5 只有
    low / medium / high；``xhigh`` 从 Opus 4.7 才有。超出的档位降到该模型的最高一档。
    """
    name = str(model or "").lower()
    if "haiku" in name or "sonnet-4-5" in name:
        return None
    level = effort if effort in EFFORT_LEVELS else DEFAULT_EFFORT
    if "opus-4-5" in name and level in ("xhigh", "max"):
        return "high"
    if ("opus-4-6" in name or "sonnet-4-6" in name) and level == "xhigh":
        return "high"
    return level


def _open_stream(client, model: str, system: str, messages: list[dict], max_tokens: int,
                 effort: str = DEFAULT_EFFORT, mcp_servers: list[dict] | None = None, client_tools=None):
    kwargs: dict[str, Any] = {"model": model, "max_tokens": max(int(max_tokens), _MIN_MAX_TOKENS),
                              "messages": messages}
    if system:
        kwargs["system"] = system
    level = _effort_for(model, effort)
    if level is not None:
        kwargs["output_config"] = {"effort": level}
    betas: list[str] = []
    if model in _FALLBACK_MODELS:
        betas.append(_FALLBACK_BETA)
        kwargs["fallbacks"] = "default"
    if mcp_servers:
        # 连接器（pet/chat/connectors.py）：服务器和它的 toolset 必须成对出现。工具定义
        # 每次采样都带、体积大（GitHub 只读全套约 1.2 万 token），所以开两处提示缓存：
        # toolset 上的断点让工具定义跨会话命中；顶层的自动缓存让同一会话的后续轮次、
        # 以及工具调用后的续写命中。
        betas.append(_MCP_BETA)
        kwargs["mcp_servers"] = [dict(server) for server in mcp_servers]
        kwargs["tools"] = [{"type": "mcp_toolset", "mcp_server_name": server["name"]} for server in mcp_servers]
        kwargs["tools"][-1]["cache_control"] = {"type": "ephemeral"}
    if client_tools is not None:
        kwargs["tools"] = [*kwargs.get("tools", []), *client_tools.definitions]
    if "tools" in kwargs:      # 工具循环每一轮都重发整段前缀：顶层自动缓存让后续轮次命中
        kwargs["cache_control"] = {"type": "ephemeral"}
    if betas:
        return client.beta.messages.stream(betas=betas, **kwargs)
    return client.messages.stream(**kwargs)


def _check_final(final) -> None:
    if getattr(final, "stop_reason", None) != "refusal":
        return
    details = getattr(final, "stop_details", None)
    explanation = str(getattr(details, "explanation", "") or "").strip()
    raise ProviderError(t("chat.claude.claude_declined_request") + (f"：{explanation}" if explanation else ""))


def _translate_error(sdk, exc: Exception, model: str) -> ProviderError:
    """SDK 的类型化异常 → 肥鱼统一的 ProviderError（由具体到宽泛逐级匹配）。"""
    if isinstance(exc, sdk.AuthenticationError):
        return ProviderError(t("chat.claude.authentication_failed_api_key_invalid"), 401)
    if isinstance(exc, sdk.PermissionDeniedError):
        return ProviderError(t("chat.claude.api_key_has_no_access"), 403)
    if isinstance(exc, sdk.NotFoundError):
        return ProviderError(t("chat.claude.model_endpoint_not_found_model", model=model, DEFAULT_MODEL=DEFAULT_MODEL), 404)
    if isinstance(exc, sdk.RateLimitError):
        return ProviderError(t("chat.claude.too_many_requests_quota_exhausted"), 429)
    if isinstance(exc, sdk.APIStatusError):
        status = getattr(exc, "status_code", None)
        message = str(getattr(exc, "message", "") or exc)
        if "mcp_servers" in message:      # 连接器的服务器连不上 / Token 被拒：整条请求 400
            return ProviderError(t("chat.claude.connector_failed_check_its_token", message=message),
                                 status)
        return ProviderError(message, status)
    if isinstance(exc, sdk.APIConnectionError):
        return ProviderError(t("chat.claude.network_connection_failed_exc", exc=exc))
    if "authentication method" in str(exc):
        # 没有任何凭据时 SDK 抛的是 TypeError（不是它自己的异常基类），且要到发请求时才抛
        return ProviderError(t("chat.claude.no_api_key_configured_settings"))
    return ProviderError(t("chat.claude.claude_request_failed_exc", exc=exc))


def _run_client_tools(client_tools, content) -> list[dict]:
    """执行这一轮里模型要的所有本地工具；结果放进同一条 user 消息（拆开发会让模型不再并行调用）。

    工具自己出错不是请求失败：把错误原样告诉模型（``is_error``），由它换个办法或如实说明。
    """
    results: list[dict] = []
    for block in content:
        if getattr(block, "type", None) != "tool_use":
            continue
        result: dict[str, Any] = {"type": "tool_result", "tool_use_id": block.id}
        try:
            result["content"] = str(client_tools.run(block.name, block.input))
        except Exception as exc:  # noqa: BLE001 - 任何失败都要回给模型，不能让工作线程死掉
            result["content"], result["is_error"] = t("chat.claude.tool_failed_exc", exc=exc), True
        results.append(result)
    return results


class AnthropicProvider:
    """流式对话；签名与 ``OpenAICompatibleProvider.stream`` 一致。"""

    def stream(self, messages: list[dict[str, Any]], config: ProviderConfig,
               cancel_event: threading.Event, response_holder: list | None = None) -> Iterator[str]:
        sdk = _sdk()
        system, convo = to_anthropic_messages(messages)
        if not convo:
            raise ProviderError(t("chat.claude.no_message_send"))
        model = str(config.model or "").strip() or DEFAULT_MODEL
        client = _client(config.api_key, config.base_url, config.timeout, config.verify_ssl)
        mcp_servers = list(getattr(config, "mcp_servers", None) or [])
        client_tools = getattr(config, "client_tools", None)
        note = str(getattr(client_tools, "system_note", "") or "").strip()
        if note:
            system = f"{system}\n\n{note}" if system else note
        pauses = tool_rounds = 0
        try:
            while pauses <= _MAX_PAUSE_RESUMES and tool_rounds <= _MAX_TOOL_ROUNDS:
                with _open_stream(client, model, system, convo, config.max_tokens,
                                  getattr(config, "effort", DEFAULT_EFFORT), mcp_servers, client_tools) as stream:
                    if response_holder is not None:
                        response_holder.append(stream)      # 取消时由 ChatService 调它的 close()
                    for text in stream.text_stream:
                        if cancel_event.is_set():
                            return
                        yield text
                    if cancel_event.is_set():
                        return
                    final = stream.get_final_message()
                _check_final(final)
                reason = getattr(final, "stop_reason", None)
                if reason == "pause_turn":
                    # 服务端工具（连接器）还没跑完：把这一段原样接回去，下一次请求从断点继续
                    pauses += 1
                    convo = [*convo, {"role": "assistant", "content": final.content}]
                elif reason == "tool_use" and client_tools is not None:
                    results = _run_client_tools(client_tools, final.content)
                    if cancel_event.is_set():
                        return
                    tool_rounds += 1
                    convo = [*convo, {"role": "assistant", "content": final.content},
                             {"role": "user", "content": results}]
                else:
                    return
            raise ProviderError(t("chat.claude.claude_never_finished_turn_too"))
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
                          _MIN_MAX_TOKENS, getattr(config, "effort", DEFAULT_EFFORT)) as stream:
            final = stream.get_final_message()
    except Exception as exc:
        raise _translate_error(sdk, exc, model) from exc
    _check_final(final)
    text = "".join(block.text for block in final.content if block.type == "text").strip()
    if not text:
        raise ProviderError(t("chat.claude.claude_said_nothing_empty_reply"))
    return text


@dataclass
class Completion:
    """``complete`` 的结果：正文 + 这次到底用了什么（模型名、token、几轮本地工具）。"""

    text: str = ""
    model: str = ""
    input_tokens: int = 0        # 含缓存读写
    output_tokens: int = 0
    rounds: int = 0              # 本地工具跑了几轮
    stop_reason: str = ""


def _usage_tokens(usage) -> tuple[int, int]:
    def _int(name: str) -> int:
        try:
            return int(getattr(usage, name, 0) or 0)
        except (TypeError, ValueError):
            return 0

    return (_int("input_tokens") + _int("cache_read_input_tokens") + _int("cache_creation_input_tokens"),
            _int("output_tokens"))


def complete(prompt: str, system: str, config: ProviderConfig, *, model: str = "", effort: str = "",
             client_tools=None, max_tokens: int = _MIN_MAX_TOKENS, max_rounds: int = _MAX_TOOL_ROUNDS,
             timeout: float | None = None, client=None) -> Completion:
    """无头的一问一答（带本地工具循环，不带连接器）：提示词进，正文 + 用量出。失败抛 ProviderError。

    给个人简报这类后台任务用：和 ``stream`` 同一套请求参数（effort、max_tokens 下限、提示缓存），
    但不流式、不可取消，并把 ``stream`` 丢掉的 ``usage`` / ``model`` 收回来给界面看。
    """
    sdk = _sdk()
    model = str(model or config.model or "").strip() or DEFAULT_MODEL
    effort = effort if effort in EFFORT_LEVELS else str(getattr(config, "effort", DEFAULT_EFFORT) or DEFAULT_EFFORT)
    note = str(getattr(client_tools, "system_note", "") or "").strip()
    if note:
        system = f"{system}\n\n{note}" if system else note
    if client is None:
        client = _client(config.api_key, config.base_url, timeout or max(float(config.timeout), 300.0), config.verify_ssl)
    convo: list[dict] = [{"role": "user", "content": prompt}]
    result = Completion(model=model)
    try:
        while True:
            with _open_stream(client, model, system, convo, max_tokens, effort, None, client_tools) as stream:
                final = stream.get_final_message()
            _check_final(final)
            tokens_in, tokens_out = _usage_tokens(getattr(final, "usage", None))
            result.input_tokens += tokens_in
            result.output_tokens += tokens_out
            result.model = str(getattr(final, "model", "") or result.model)
            result.stop_reason = str(getattr(final, "stop_reason", "") or "")
            if result.stop_reason == "tool_use" and client_tools is not None:
                result.rounds += 1
                if result.rounds > max_rounds:
                    raise ProviderError(t("chat.claude.claude_kept_calling_tools_without"))
                results = _run_client_tools(client_tools, final.content)
                convo = [*convo, {"role": "assistant", "content": final.content}, {"role": "user", "content": results}]
                continue
            break
    except ProviderError:
        raise
    except Exception as exc:
        raise _translate_error(sdk, exc, model) from exc
    result.text = "".join(getattr(block, "text", "") for block in final.content
                          if getattr(block, "type", None) == "text").strip()
    if not result.text:
        raise ProviderError(t("chat.claude.claude_said_nothing_empty_reply"))
    return result


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
    return True, t("chat.claude.connected_claude_model", model=model)


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
