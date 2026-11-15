# -*- coding: utf-8 -*-
"""配置全景的探针：只读地把本机事实读成一个 ``facts`` 字典，交给 ``sources.build``。

全部只读，而且会起子进程（git、wsl.exe），所以**只能在后台线程里调**。API key、GitHub token 这类秘密
只留「有没有 + 末 4 位」，值本身不进 ``facts``，也就进不了落盘的页面。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from .. import claude_hooks, config_backup, personal_vault, work_notes
from . import claude_home_probe, features

SecretGet = Callable[[str], str]
GitRunner = Callable[..., "tuple[int, str]"]
WSL_TIMEOUT_S = 150.0      # 发行版冷启动 + ``claude mcp list`` 逐个体检（实测 6-9 秒），留足余量
GIT_TIMEOUT_S = 10.0
TAIL_MIN_LENGTH = 12       # 比这短的秘密不露末位：露 4 位就是露了三分之一


def secret_tail(value: str) -> dict:
    value = str(value or "")
    return {"present": bool(value), "tail": value[-4:] if len(value) > TAIL_MIN_LENGTH else ""}


def providers(cfg: dict, secret_get: SecretGet) -> list[dict]:
    """模型服务列表：地址、模型、effort、是不是使用中的、key 在不在。"""
    chat = cfg.get("chat") if isinstance(cfg.get("chat"), dict) else {}
    rows = []
    for provider_id, raw in (chat.get("providers") or {}).items():
        if not isinstance(raw, dict):
            continue
        ref = str(raw.get("api_key_ref") or f"provider/{provider_id}")
        base_url = str(raw.get("base_url") or "")
        rows.append({
            "id": str(provider_id), "name": str(raw.get("name") or provider_id), "base_url": base_url,
            "host": urlparse(base_url).netloc, "model": str(raw.get("model") or ""), "effort": str(raw.get("effort") or ""),
            "api_format": str(raw.get("api_format") or ""), "active": provider_id == chat.get("active_provider"),
            "key_ref": ref, "key": secret_tail(secret_get(ref) or str(raw.get("api_key") or "")),
        })
    return rows


def repo_info(path: str | Path, run_git: GitRunner = personal_vault.run_git) -> dict:
    """一个本地克隆：在不在、远端（去掉内嵌凭据）、分支、最近一次提交。"""
    folder = Path(os.path.expandvars(str(path or "")))
    info = {"path": str(folder) if path else "", "exists": bool(path) and folder.is_dir(), "remote": "", "branch": "", "last_commit": ""}
    if not info["exists"]:
        return info

    def git(*args: str) -> str:
        code, out = run_git(folder, list(args), timeout=GIT_TIMEOUT_S)
        return out.strip() if code == 0 else ""

    info["remote"] = re.sub(r"(https?://)[^@/]+@", r"\1", git("remote", "get-url", "origin"))
    info["branch"] = git("rev-parse", "--abbrev-ref", "HEAD")
    info["last_commit"] = git("log", "-1", "--format=%cd · %s", "--date=format:%Y-%m-%d %H:%M")[:90]
    return info


def wsl_side(run_wsl: Callable[..., "tuple[int, str]"] = claude_hooks.run_wsl, *, with_mcp: bool = True) -> dict:
    """WSL 默认发行版里的 Claude Code。把 ``claude_home_probe`` 的源码从标准输入喂给那边的 ``python3``。

    返回探针结果；没有 WSL 是 ``{"absent": True}``；跑不起来是 ``{"error": 说明}``。
    """
    source = Path(claude_home_probe.__file__).read_text(encoding="utf-8")
    code, out = run_wsl(["-e", "python3", "-", *(["--mcp"] if with_mcp else [])], input_text=source, timeout=WSL_TIMEOUT_S)
    if code == 127:
        return {"absent": True}
    start = out.find("{")
    try:
        data = json.loads(out[start:]) if code == 0 and start >= 0 else None
    except ValueError:
        data = None
    return data if isinstance(data, dict) else {"error": f"exit {code}"}


def windows_side(cfg: dict, *, cfg_path: str | Path, secret_get: SecretGet, api_health: tuple[str, str] = ("unknown", ""),
                 home: str | Path | None = None, run_git: GitRunner = personal_vault.run_git) -> dict:
    """这台 Windows 上能读到的全部事实（不含 WSL）。``api_health`` 是岛上那个体检器的最近结论。"""
    started = time.perf_counter()
    cfg_path = Path(cfg_path)
    chat = cfg.get("chat") if isinstance(cfg.get("chat"), dict) else {}
    try:
        cfg_mtime = dt.datetime.fromtimestamp(cfg_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    except OSError:
        cfg_mtime = ""
    facts = {
        "taken_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "computer": os.environ.get("COMPUTERNAME", ""),
        "cfg_path": str(cfg_path), "cfg_mtime": cfg_mtime,
        "providers": providers(cfg, secret_get), "api_health": {"state": api_health[0], "detail": api_health[1]},
        "github_token": secret_tail(secret_get("connector/github")),
        "chat": {"github_connector": bool(chat.get("github_connector")), "knowledge_base_enabled": bool(chat.get("knowledge_base_enabled")),
                 "knowledge_base_repo": str(chat.get("knowledge_base_repo") or "")},
        "config_backup": config_backup.normalize(cfg.get("config_backup")),
        "features": features.read_all(cfg),
        "personal_vault": repo_info(personal_vault.normalize(cfg.get(personal_vault.CONFIG_KEY))["repo_dir"], run_git),
        "work_vault": repo_info(work_notes.normalize(cfg.get(work_notes.CONFIG_KEY))["repo_dir"], run_git),
        "win": claude_home_probe.probe(home or Path.home()),
    }
    facts["timing"] = {"windows_s": round(time.perf_counter() - started, 2)}
    return facts


def gather(cfg: dict, *, run_wsl: Callable[..., "tuple[int, str]"] = claude_hooks.run_wsl, with_mcp: bool = True, **kwargs) -> dict:
    """一口气采完两边（命令行入口用；应用里分两段，先出 Windows 那半张图）。"""
    facts = windows_side(cfg, **kwargs)
    started = time.perf_counter()
    facts["wsl"] = wsl_side(run_wsl, with_mcp=with_mcp)
    facts["timing"]["wsl_s"] = round(time.perf_counter() - started, 2)
    return facts
