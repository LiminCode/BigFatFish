# -*- coding: utf-8 -*-
"""对话连接器：让桌宠在对话里查外部服务，目前只有 GitHub（只读）。

走的是 Messages API 的 MCP connector：请求里带上 MCP 服务器地址和 Token，由
Anthropic 的服务器去连 GitHub 的远程 MCP 服务器、替模型调用工具，桌宠本地不跑
MCP 客户端。因此有两条限制：

- **只在直连 Claude API 时可用**。OpenAI 兼容通道没有这个功能；经第三方网关访问
  Claude 时网关不一定转发，Token 也不该交给它，所以一律不挂。
- **Token 会随每次请求发给 Anthropic**。地址固定用 ``/readonly``，GitHub 那一侧
  只暴露读工具，Token 权限再大也改不了仓库。

Token 存系统钥匙串（``connector/github``），开关存 ``chat.github_connector``。
"""

from __future__ import annotations

from urllib.parse import urlparse

from . import models as _models
from .anthropic_provider import _ANTHROPIC_HOST, uses_anthropic

GITHUB_MCP_URL = "https://api.githubcopilot.com/mcp/readonly"
GITHUB_SERVER_NAME = "github"
GITHUB_TOKEN_REF = "connector/github"


def _direct_to_anthropic(provider) -> bool:
    if not uses_anthropic(provider):
        return False
    url = str(getattr(provider, "base_url", "") or "").strip()
    if not url:                        # 地址留空时 SDK 用官方地址
        return True
    host = (urlparse(url).hostname or "").lower()
    return host == _ANTHROPIC_HOST or host.endswith("." + _ANTHROPIC_HOST)


def mcp_servers_for(settings, provider) -> list[dict]:
    """这次对话该挂的 MCP 服务器；不满足条件时是空列表（请求与没有连接器时完全一样）。"""
    if not getattr(settings, "github_connector", False) or not _direct_to_anthropic(provider):
        return []
    token = _models.SecretStore().get(GITHUB_TOKEN_REF).strip()
    if not token:
        return []
    return [{"type": "url", "url": GITHUB_MCP_URL, "name": GITHUB_SERVER_NAME, "authorization_token": token}]
