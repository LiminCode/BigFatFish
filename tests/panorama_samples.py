# -*- coding: utf-8 -*-
"""配置全景测试用的虚构事实（没有一项来自真机）。"""
from __future__ import annotations

import copy

from pet.panorama import features

FISH_HOOKS = {"Stop": {"total": 1, "fish": 1}, "Notification": {"total": 2, "fish": 1}}


def home(*, hooks=None, connectors=None, wsl=False) -> dict:
    """``claude_home_probe.probe`` 的一份结果。"""
    root = "/home/dev" if wsl else "C:\\Users\\dev"
    sep = "/" if wsl else "\\"
    claude = root + sep + ".claude"
    return {
        "home": root, "platform": "linux" if wsl else "win32", "distro": "Ubuntu-24.04" if wsl else "", "user": "dev",
        "account": {"email": "dev@work.example" if wsl else "dev@home.example", "organization": "Acme" if wsl else ""},
        "settings_path": claude + sep + "settings.json", "settings_mtime": "2026-01-02 03:04",
        "model": "sonnet", "effort": "high", "hooks": copy.deepcopy(FISH_HOOKS if hooks is None else hooks), "allow_rules": 3,
        "plugins": ["notes@acme"], "mcp_servers": ["acme-tools"] if wsl else [], "state_path": root + sep + ".claude.json",
        "ever_connected": [] if wsl else ["claude.ai Calendar", "claude.ai Mail"],
        "claude_md": {"exists": True, "path": claude + sep + "CLAUDE.md", "bytes": 120, "lines": 9, "mtime": "2026-01-02 03:04",
                      "managed_block": True, "managed_rules": 2, "managed_updated": "2026-01-01 10:00"},
        "projects": 4, "memory_count": 1,
        "memory_projects": [{"name": "C--Users-dev-tomato", "path": claude + sep + "projects", "mtime": "2026-01-02 03:04", "files": 2}],
        "distilled_files": 1, "credentials_path": claude + sep + ".credentials.json", "credentials_file": True,
        "tools": [".config/gh"] if wsl else [".cursor"], "ssh_hosts": ["github.com", "10.0.0.1"] if wsl else [],
        "connectors": connectors, "mcp_probe_seconds": 6.1 if connectors is not None else None,
    }


def wsl_home(**kwargs) -> dict:
    connectors = kwargs.pop("connectors", [
        {"name": "claude.ai Docs", "state": "ok", "detail": "✔ Connected"},
        {"name": "claude.ai Tickets", "state": "auth", "detail": "! Needs authentication"},
    ])
    return home(wsl=True, connectors=connectors, **kwargs)


def provider(provider_id="api-1", *, active=True, key=True) -> dict:
    return {"id": provider_id, "name": f"Service {provider_id}", "base_url": "https://api.acme.example", "host": "api.acme.example",
            "model": "acme-large", "effort": "medium", "api_format": "auto", "active": active, "key_ref": f"provider/{provider_id}",
            "key": {"present": key, "tail": "9z9z" if key else ""}}


def repo(name: str, owner: str, exists=True) -> dict:
    return {"path": f"C:\\Users\\dev\\{name}", "exists": exists, "remote": f"https://github.com/{owner}/{name}.git" if exists else "",
            "branch": "main" if exists else "", "last_commit": "2026-01-02 03:04 · notes" if exists else ""}


def facts(*, cfg=None, health="ok", wsl="ready", win=None, providers=None) -> dict:
    """``probes.windows_side`` + WSL 那一半。``wsl``：ready / absent / error / pending，或直接给一个探针结果。"""
    wsl_value = {"ready": wsl_home(), "absent": {"absent": True}, "error": {"error": "exit 1"}, "pending": {"pending": True}}.get(wsl, wsl) \
        if isinstance(wsl, str) else wsl
    return {
        "taken_at": "2026-01-02 03:04:05", "computer": "DEVBOX", "cfg_path": "C:\\Users\\dev\\cfg\\config.json", "cfg_mtime": "2026-01-02 03:00",
        "providers": [provider(), provider("api-2", active=False)] if providers is None else providers,
        "api_health": {"state": health, "detail": "连接成功" if health == "ok" else "401"},
        "github_token": {"present": True, "tail": "t0k3"},
        "chat": {"github_connector": True, "knowledge_base_enabled": True, "knowledge_base_repo": "acme/handbook"},
        "config_backup": {"auto": False, "repo": "", "path": ".big-fat-fish/config.json"},
        "features": features.read_all(cfg if cfg is not None else all_on_config()),
        "personal_vault": repo("handbook", "acme-home"), "work_vault": repo("field-notes", "acme-work"),
        "win": win or home(), "wsl": wsl_value, "timing": {"windows_s": 0.3, "wsl_s": 6.5},
    }


def all_on_config() -> dict:
    return {
        "chat": {"enabled": True, "default_system_prompt": "be brief", "about_user": "", "github_connector": True,
                 "knowledge_base_enabled": True},
        "proactive_screen": {"enabled": True}, "file_interpret": {"enabled": True},
        "memory_distill": {"enabled": True, "work_distill": True}, "personal": {"enabled": True},
        "work_briefing": {"enabled": True}, "slack_watch": {"enabled": True}, "work_notes": {"enabled": True},
        "agent_link": {"claude": True, "claude_wsl": True},
    }
