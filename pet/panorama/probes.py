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

from .. import claude_hooks, config_backup, data_stores, personal_vault, run_journal, vault_sync, work_notes
from . import claude_home_probe, features, storage_probe, store_walk

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


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def remote_contact(folder: Path, branch: str) -> tuple[float | None, bool]:
    """这个克隆上一次真的碰到远端是什么时候（时间戳，不知道是 ``None``），以及最近一次 fetch 是不是没连上。只看文件，不起进程。

    - ``.git/FETCH_HEAD``：每次 fetch / pull 都重写。**fetch 失败时 git 把它清空、修改时间照样更新**（本机 git 2.55 实测，
      本地路径和 https 都一样），所以只有非空的才算数；空的 = 最近一次没连上。
    - ``.git/logs/refs/remotes/origin/<分支>``：远端分支在本地的记录每动一次追加一行——push 成功也会动它，而 push 不写
      FETCH_HEAD。旁边的 ``origin/HEAD`` 是 clone 时写的：刚克隆下来、还没 fetch 过的，就按克隆那一刻算。
      几个里取最晚的。

    ``.git`` 不是目录（工作树、子模块）时两个都找不到，如实答不知道。
    """
    git_dir = folder / ".git"
    fetch_head = git_dir / "FETCH_HEAD"
    try:
        stat = fetch_head.stat()
        fetched, failed = (stat.st_mtime, False) if stat.st_size else (None, True)
    except OSError:
        fetched, failed = None, False
    remote_logs = git_dir / "logs" / "refs" / "remotes" / "origin"
    moved = _mtime(remote_logs / branch) if branch else None
    times = [stamp for stamp in (fetched, moved, _mtime(remote_logs / "HEAD")) if stamp is not None]
    return (max(times) if times else None), failed


def repo_info(path: str | Path, run_git: GitRunner = personal_vault.run_git, *, now: float | None = None) -> dict:
    """一个本地克隆：在不在、远端（去掉内嵌凭据）、分支、最近一次提交，和远端差多少、这个「差多少」有多旧。

    ``unpushed`` / ``behind``：比上游多出来 / 少掉的提交数。**按本地记得的上游算，不联网**——所以它们只和上一次碰到远端时
    一样新：``checked_at``（``YYYY-MM-DD HH:MM``，不知道是空串）、``checked_age_s``（距今秒数）、``check_failed``（最近一次
    fetch 没连上），见 ``remote_contact``。``dirty``：有没有还没提交的改动；``changes`` / ``deletions``：一共几个文件、其中删除几个
    （「现在同步」会把它们提交掉，所以点之前要让人看到这两个数）。问不出来（没有上游、git 失败）是 ``None``。
    """
    folder = Path(os.path.expandvars(str(path or "")))
    info = {"path": str(folder) if path else "", "exists": bool(path) and folder.is_dir(), "remote": "", "branch": "", "last_commit": "",
            "unpushed": None, "behind": None, "dirty": None, "changes": None, "deletions": None,
            "checked_at": "", "checked_age_s": None, "check_failed": False}
    if not info["exists"]:
        return info

    def git(*args: str) -> str:
        code, out = run_git(folder, list(args), timeout=GIT_TIMEOUT_S)
        return out.strip() if code == 0 else ""

    info["remote"] = re.sub(r"(https?://)[^@/]+@", r"\1", git("remote", "get-url", "origin"))
    info["branch"] = git("rev-parse", "--abbrev-ref", "HEAD")
    info["last_commit"] = git("log", "-1", "--format=%cd · %s", "--date=format:%Y-%m-%d %H:%M")[:90]
    counts = git("rev-list", "--left-right", "--count", "@{upstream}...HEAD").split()      # 「落后 领先」，一次问完
    if len(counts) == 2 and all(count.isdigit() for count in counts):
        info["behind"], info["unpushed"] = int(counts[0]), int(counts[1])
    code, out = run_git(folder, ["status", "--porcelain=v1", "-z"], timeout=GIT_TIMEOUT_S)
    if code == 0:                                       # 和同步器用同一个读法：它要提交的就是这里数出来的这些
        changes = vault_sync.read_status(out)
        info["dirty"], info["changes"], info["deletions"] = changes.files > 0, changes.files, changes.deletions
    checked, info["check_failed"] = remote_contact(folder, info["branch"])
    if checked is not None:
        info["checked_at"] = dt.datetime.fromtimestamp(checked).strftime("%Y-%m-%d %H:%M")
        info["checked_age_s"] = max(0, int((time.time() if now is None else now) - checked))
    return info


def last_sync(config_dir: str | Path, repo: str) -> dict | None:
    """这个克隆上一次同步怎么样了：运行记录里最近一条 ``vault_sync``（它的 ``git`` 效果是这个仓库的）。没同步过是 ``None``。

    只取页面要说的那几项：什么时候、结果、拉了几个推了几个、撞了几个冲突、预检为什么没过、守卫为什么拦。"""
    for row in run_journal.Journal(Path(config_dir) / run_journal.DIR_NAME).read(20, job=vault_sync.JOB):
        effect = next((e for e in row.get("effects") or [] if isinstance(e, dict) and e.get("kind") == "git" and e.get("repo") == repo), None)
        if effect is not None:
            return {"at": str(row.get("at") or ""), "result": str(row.get("result") or ""),
                    **{key: effect[key] for key in ("pulled", "pushed", "conflicts", "blocked", "review") if effect.get(key)}}
    return None


def wsl_source() -> str:
    """喂给 WSL 的那一份源码：存储表、走目录的代码、家目录探针，三个文件按这个顺序拼成一个。

    三个都只用标准库。拼在一起后落在同一个作用域里：探针的入口看到 ``survey_tree`` 和 ``match`` 都在，
    就顺手把 ``~/.claude`` 走一遍，按存储表数出每一项有多少（结果里的 ``storage``）。
    ``from __future__`` 只能出现在文件开头，所以各自的那一行摘掉，开头统一放一行。
    """
    parts = [Path(module.__file__).read_text(encoding="utf-8") for module in (data_stores, store_walk, claude_home_probe)]
    marker = "from __future__ import annotations\n"
    return marker + "\n\n".join(part.replace(marker, "") for part in parts)


def wsl_side(run_wsl: Callable[..., "tuple[int, str]"] = claude_hooks.run_wsl, *, with_mcp: bool = True) -> dict:
    """WSL 默认发行版里的 Claude Code。把 ``wsl_source()`` 从标准输入喂给那边的 ``python3``。

    返回探针结果；没有 WSL 是 ``{"absent": True}``；跑不起来是 ``{"error": 说明}``。
    """
    source = wsl_source()
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
        "vault_sync": {"personal": last_sync(cfg_path.parent, "personal")},
        "win": claude_home_probe.probe(home or Path.home()),
    }
    storage_started = time.perf_counter()
    facts["storage"] = storage_probe.collect(cfg, config_dir=cfg_path.parent, home=home or Path.home(),
                                             kb_repo=facts["chat"]["knowledge_base_repo"])
    facts["timing"] = {"windows_s": round(time.perf_counter() - started, 2),
                       "storage_s": round(time.perf_counter() - storage_started, 2)}
    return facts


def gather(cfg: dict, *, run_wsl: Callable[..., "tuple[int, str]"] = claude_hooks.run_wsl, with_mcp: bool = True, **kwargs) -> dict:
    """一口气采完两边（命令行入口用；应用里分两段，先出 Windows 那半张图）。"""
    facts = windows_side(cfg, **kwargs)
    started = time.perf_counter()
    facts["wsl"] = wsl_side(run_wsl, with_mcp=with_mcp)
    facts["timing"]["wsl_s"] = round(time.perf_counter() - started, 2)
    return facts
