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
        "mcp_detail": [{"name": "acme-tools", "kind": "stdio", "target": "npx -y @acme/tools --api-key ***", "env": ["ACME_TOKEN"],
                        "project": ""}] if wsl else [],
        "probed_at": "2026-01-02 03:04:05", "mcp_probed_at": "2026-01-02 03:04:11" if connectors is not None else "",
        "ever_connected": [] if wsl else ["claude.ai Calendar", "claude.ai Mail"],
        "claude_md": {"exists": True, "path": claude + sep + "CLAUDE.md", "bytes": 120, "lines": 9, "mtime": "2026-01-02 03:04",
                      "managed_block": True, "managed_rules": 2, "managed_updated": "2026-01-01 10:00"},
        "projects": 4, "memory_count": 1,
        "memory_projects": [{"name": "C--Users-dev-tomato", "path": claude + sep + "projects", "mtime": "2026-01-02 03:04", "files": 2}],
        "distilled_files": 1, "memory_index": memory_index(wsl=wsl), "credentials_path": claude + sep + ".credentials.json", "credentials_file": True,
        "tools": [".config/gh"] if wsl else [".cursor"], "ssh_hosts": ["github.com", "10.0.0.1"] if wsl else [],
        "connectors": connectors, "mcp_probe_seconds": 6.1 if connectors is not None else None,
    }


def memory_index(*, wsl=False) -> dict:
    """``claude_home_probe.memory_index`` 的一份结果。两边故意放了几条一样的：全局里已有的、两个项目各记一份的、两台机器都有的。"""
    def entry(file: str, name: str, description: str, kind: str = "feedback") -> dict:
        return {"file": file, "name": name, "description": description, "type": kind, "bytes": 300, "mtime": "2026-01-02 03:04"}

    if wsl:
        return {"rules": [{"title": "画图只画机制", "text": "不画装饰"}], "sections": ["Team rules"], "entries": 1, "truncated": False,
                "projects": [{"name": "-home-dev-carrot", "entries": [entry("notes.md", "Carrot notes", "pytest 要设环境变量才能跑起来", "project")]}]}
    return {"rules": [{"title": "画图只画机制", "text": "不画装饰"}, {"title": "默认中文", "text": "解释用中文"}], "sections": ["我的规矩"],
            "entries": 4, "truncated": False,
            "projects": [
                {"name": "C--Users-dev-potato", "entries": [entry("run-env.md", "本机测试方法", "换了一种说法的说明文字", "project")]},
                {"name": "C--Users-dev-tomato", "entries": [
                    entry("release.md", "番茄的发布流程", "先打标签再推送", "project"),
                    entry("reply.md", "默认中文", "所有解释默认都用中文来写"),
                    entry("run.md", "本机测试方法", "pytest 要设环境变量才能跑起来", "project")]}]}


def wsl_home(**kwargs) -> dict:
    connectors = kwargs.pop("connectors", [
        {"name": "claude.ai Docs", "state": "ok", "detail": "✔ Connected", "kind": "remote", "target": "https://docs.acme.example/mcp"},
        {"name": "claude.ai Tickets", "state": "auth", "detail": "! Needs authentication", "kind": "remote",
         "target": "https://tickets.acme.example/sse"},
    ])
    return home(wsl=True, connectors=connectors, **kwargs)


def provider(provider_id="api-1", *, active=True, key=True) -> dict:
    return {"id": provider_id, "name": f"Service {provider_id}", "base_url": "https://api.acme.example", "host": "api.acme.example",
            "model": "acme-large", "effort": "medium", "api_format": "auto", "active": active, "key_ref": f"provider/{provider_id}",
            "key": {"present": key, "tail": "9z9z" if key else ""}}


def repo(name: str, owner: str, exists=True) -> dict:
    return {"path": f"C:\\Users\\dev\\{name}", "exists": exists, "remote": f"https://github.com/{owner}/{name}.git" if exists else "",
            "branch": "main" if exists else "", "last_commit": "2026-01-02 03:04 · notes" if exists else "",
            "unpushed": 0 if exists else None, "dirty": False if exists else None}


def storage(*, backup=None, unknown=()) -> dict:
    """``storage_probe.collect`` 的一份结果：数据目录和个人 Claude Code 家目录里各项有多少，配置备份此刻的状态。"""
    def seen(files: int, size: int) -> dict:
        return {"files": files, "bytes": size, "mtime": "2026-01-02 03:04"}

    def root(path: str, stores: dict, names=()) -> dict:
        return {"path": path, "exists": True, "files": sum(s["files"] for s in stores.values()) + len(names), "truncated": False,
                "stores": stores, "unknown": list(names), "unknown_count": len(names)}

    return {
        "data": root("C:\\Users\\dev\\cfg", {
            "config": seen(1, 4096), "distill_entries": seen(1, 2048), "chat_sessions": seen(12, 300_000), "message_log": seen(1, 9000),
            "logs": seen(3, 1_500_000), "voice_cache": seen(40, 6_000_000), "runtime_markers": seen(4, 900)}, unknown),
        "claude_home": root("C:\\Users\\dev\\.claude", {
            "claude_settings": seen(1, 3000), "claude_md": seen(1, 120), "claude_memory": seen(2, 500),
            "claude_transcripts": seen(30, 9_000_000), "claude_login": seen(1, 400)}),
        "home": root("C:\\Users\\dev", {"claude_json": seen(1, 20_000)}),
        "config_backup": {"auto": False, "repo": "acme/handbook", "path": ".big-fat-fish/config.json", "backed_up_at": "", "error": "",
                          "paused": False, **(backup or {})},
    }


def facts(*, cfg=None, health="ok", wsl="ready", win=None, providers=None, backup=None, unknown=()) -> dict:
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
        "win": win or home(), "wsl": wsl_value, "storage": storage(backup=backup, unknown=unknown),
        "timing": {"windows_s": 0.3, "wsl_s": 6.5},
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
