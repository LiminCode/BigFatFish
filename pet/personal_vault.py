# -*- coding: utf-8 -*-
"""个人助理的纯逻辑（零 Qt、不依赖 ``pet.chat``）：配置键、AI-Base 本地克隆、Windows git、Obsidian。

和工作笔记（``work_notes.py``）的差别：仓库是**个人**知识库 AI-Base 的本地克隆，git 直接用 Windows 的
``git.exe``（不经 WSL——那边登录的是公司账号），推送用肥鱼钥匙串里的 GitHub Token（和知识库同步 / GitHub
连接器共用的那一个），Token 只经环境变量交给 git，不进命令行。

随手记不经 AI：``capture_inbox`` 写进 ``0-Inbox/`` 一条一个文件，然后 ``sync_path`` add / commit / pull --rebase / push。
提交说明只有日期时间，不带正文；本模块也不记录正文到日志。

``config.py`` 在导入时就要用 ``normalize``，所以这里不能导入 ``pet.chat``（钥匙串 Token 的读取是惰性导入）。
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable
from urllib.parse import quote

from . import work_briefing as wb
from . import work_notes as wn

CONFIG_KEY = "personal"
DEFAULT_TIME = "08:30"
#: 没在 PATH 里时的 Git for Windows 默认位置
GIT_FALLBACK = r"C:\Program Files\Git\cmd\git.exe"
GIT_TIMEOUT_S = 120.0
#: 退到 Git Credential Manager 时它可能弹浏览器登录：给足时间
FIRST_PUSH_TIMEOUT_S = 240.0
#: 只问远端、不动工作区的 fetch：有人在页面上等结果
FETCH_TIMEOUT_S = 30.0
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
#: 设置页模型下拉里的几个常用名；留空 = 跟「AI 对话」里的模型一致
MODEL_CHOICES = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1")
TIME_CHOICES = ("07:00", "07:30", "08:00", "08:30", "09:00", "09:30", "10:00", "20:00", "21:00")

_AUTH_FAILED_MARKS = ("403", "401", "authentication failed", "could not read username", "permission denied",
                      "invalid username or token", "terminal prompts disabled")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

GitRunner = Callable[..., "tuple[int, str]"]


# ---------------------------------------------------------------- 配置

def default_repo_dir() -> str:
    base = os.environ.get("USERPROFILE") or str(Path.home())
    return os.path.join(base, "Github", "AI-Base")


def normalize_model(value) -> str:
    """空 = 跟聊天设置；否则只认模型名该有的字符。"""
    model = str(value or "").strip()
    return model if wb._MODEL_RE.fullmatch(model) else ""


def normalize_time(value) -> str:
    """同工作简报的写法，但退回的是这里的默认 08:30。"""
    match = wb._TIME_RE.fullmatch(str(value if value is not None else ""))
    if not match:
        return DEFAULT_TIME
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    return f"{hour:02d}:{minute:02d}" if hour < 24 and minute < 60 else DEFAULT_TIME


def normalize_effort(value) -> str:
    effort = str(value or "").strip().lower()
    return effort if effort in EFFORT_LEVELS else ""


def normalize(value) -> dict:
    data = value if isinstance(value, dict) else {}
    repo_dir = str(data.get("repo_dir") or "").strip() or default_repo_dir()
    return {
        "enabled": data.get("enabled", False) is True,
        "repo_dir": repo_dir,
        "time": normalize_time(data.get("time")),
        "model": normalize_model(data.get("model")),
        "effort": normalize_effort(data.get("effort")),
    }


def repo_ready(repo_dir: str | Path) -> bool:
    return (Path(repo_dir) / ".git").exists()


# ---------------------------------------------------------------- Windows git

def git_exe() -> str | None:
    if sys.platform != "win32":
        return shutil.which("git")
    found = shutil.which("git")
    if found:
        return found
    return GIT_FALLBACK if Path(GIT_FALLBACK).exists() else None


def run_git(repo_dir: str | Path, args: list[str], *, timeout: float = GIT_TIMEOUT_S,
            env: dict | None = None) -> tuple[int, str]:
    """在克隆目录里跑一条 git，返回 (返回码, stdout+stderr)。任何失败折成非零返回码；没有 git 是 127。"""
    exe = git_exe()
    if not exe:
        return 127, ""
    full_env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env or {})}
    try:
        proc = subprocess.run([exe, "-C", str(repo_dir), *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              env=full_env, creationflags=_NO_WINDOW, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, f"{type(exc).__name__}: {exc}"
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


def token_env(token: str) -> dict:
    """把 Token 作为 HTTP 头交给 git（环境变量，不进 argv / 不写文件），并关掉凭据助手免得它抢着问。"""
    token = str(token or "").strip()
    if not token:
        return {}
    basic = base64.b64encode(f"x-access-token:{token}".encode("utf-8")).decode("ascii")
    return {
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": "credential.helper", "GIT_CONFIG_VALUE_0": "",
        "GIT_CONFIG_KEY_1": "http.https://github.com/.extraheader", "GIT_CONFIG_VALUE_1": f"Authorization: Basic {basic}",
    }


def github_token() -> str:
    """钥匙串里的 GitHub Token（与知识库同步 / 连接器共用）；没装 ``pet.chat`` 或没存过就是空。"""
    try:
        from .chat.knowledge_base import stored_token
    except Exception:  # noqa: BLE001 - 不带聊天的打包变体
        return ""
    try:
        return str(stored_token() or "")
    except Exception:  # noqa: BLE001
        return ""


def describe_token_scopes(token: str, *, opener=None) -> str:
    """Token 的权限范围（给失败文案用）：classic PAT 回 ``X-OAuth-Scopes``；细粒度 Token 没有这个头。"""
    if not token:
        return ""
    import urllib.request

    opener = opener or urllib.request.urlopen
    req = urllib.request.Request("https://api.github.com/user",
                                 headers={"Authorization": f"Bearer {token}", "User-Agent": "big-fat-fish"})
    try:
        with opener(req, timeout=15) as response:
            scopes = response.headers.get("X-OAuth-Scopes")
    except Exception:  # noqa: BLE001
        return ""
    return str(scopes or "").strip() or "fine-grained"


def _auth_failed(out: str) -> bool:
    lowered = str(out or "").lower()
    return any(mark in lowered for mark in _AUTH_FAILED_MARKS)


def _remote(repo_dir, args: list[str], *, run: GitRunner, token: str, scopes=describe_token_scopes) -> tuple[int, str]:
    """要碰远端的命令：先用钥匙串 Token；被拒就让普通 git（Git Credential Manager）再试一次。"""
    if token:
        code, out = run(repo_dir, args, env=token_env(token))
        if code == 0 or not _auth_failed(out):
            return code, out
        hint = scopes(token)
        code, out = run(repo_dir, args, timeout=FIRST_PUSH_TIMEOUT_S)
        if code != 0:
            out = f"{out}\n[token scopes: {hint or '?'}]"
        return code, out
    return run(repo_dir, args, timeout=FIRST_PUSH_TIMEOUT_S)


def pull(repo_dir: str | Path, *, run: GitRunner = run_git, token: str = "") -> tuple[bool, str]:
    """拉远端（Obsidian / 网页端可能写过）；本地未提交的改动先藏起来再放回。"""
    code, out = _remote(repo_dir, ["pull", "-q", "--rebase", "--autostash"], run=run, token=token)
    if code != 0:
        run(repo_dir, ["rebase", "--abort"])
    return code == 0, "" if code == 0 else out.strip()[-300:]


def fetch(repo_dir: str | Path, *, run: GitRunner = run_git, token: str = "", timeout: float = FETCH_TIMEOUT_S) -> tuple[bool, str]:
    """只问一次远端、不动工作区和本地分支（配置全景的「现在核对」）：之后「领先 / 落后几个提交」才是此刻的。

    每次尝试最多等 ``timeout`` 秒（Token 一次，被拒后凭据助手一次），比推送短得多：点的人在等按钮上的结果。
    没连上时 git 会把 ``FETCH_HEAD`` 清空——探针靠这个认出「最近一次没连上」（``panorama.probes.remote_contact``）。"""
    def capped(folder, args, **options):
        return run(folder, args, **{**options, "timeout": min(options.get("timeout", timeout), timeout)})

    code, out = _remote(repo_dir, ["fetch", "-q"], run=capped, token=token)
    return code == 0, "" if code == 0 else out.strip()[-300:]


def upstream_state(repo_dir: str | Path, *, run: GitRunner = run_git) -> dict:
    """本地记得的远端分支此刻指向哪（提交号前 12 位）、本地比它落后 / 领先几个提交。两条本地命令，不联网。

    fetch 前后各问一次，就知道这次 fetch 带回了什么（运行记录里那条 ``git`` 效果）。问不出来（没有上游、不是克隆）
    时 ``head`` 是空串、两个数是 ``None``——问不出来不等于没有差距。"""
    code, out = run(repo_dir, ["rev-parse", "@{upstream}"])
    head = out.strip()[:12] if code == 0 else ""
    code, out = run(repo_dir, ["rev-list", "--left-right", "--count", "@{upstream}...HEAD"])
    counts = out.split() if code == 0 else []
    if len(counts) == 2 and all(count.isdigit() for count in counts):
        return {"head": head, "behind": int(counts[0]), "ahead": int(counts[1])}
    return {"head": head, "behind": None, "ahead": None}


def sync_path(repo_dir: str | Path, rel_path: str | list[str], message: str, *, run: GitRunner = run_git,
              token: str = "") -> tuple[bool, str]:
    """仓库里的一个或几个文件：add → 有变化才 commit → pull --rebase → push（随手记、会话记忆镜像共用）。"""
    paths = [rel_path] if isinstance(rel_path, str) else list(rel_path)
    code, out = run(repo_dir, ["add", "--", *paths])
    if code != 0:
        return False, out.strip()[-300:]
    code, out = run(repo_dir, ["diff", "--cached", "--quiet"])
    if code == 1:
        code, out = run(repo_dir, ["commit", "-q", "-m", message])
        if code != 0:
            return False, out.strip()[-300:]
    elif code != 0:
        return False, out.strip()[-300:]
    ok, reason = pull(repo_dir, run=run, token=token)
    if not ok:
        return False, reason
    code, out = _remote(repo_dir, ["push", "-q"], run=run, token=token)
    return code == 0, "" if code == 0 else out.strip()[-300:]


# ---------------------------------------------------------------- Obsidian

def obsidian_vault_uri(repo_dir: str | Path, vaults: dict | None = None) -> str:
    """克隆目录已登记成 Obsidian 库 → 打开它的 INDEX.md 的地址；没登记返回空。

    用 ``path=`` 而不是 ``vault=``：Drive 上那份旧库的名字也叫 AI-Base，按名字会打开错的那个。"""
    vaults = wn.obsidian_vaults() if vaults is None else vaults
    wanted = wn._norm(str(repo_dir))
    for vault in vaults.values():
        vault_path = str(vault.get("path") or "") if isinstance(vault, dict) else ""
        if vault_path and wn._norm(vault_path) == wanted:
            target = Path(repo_dir) / "INDEX.md"
            return "obsidian://open?path=" + quote(str(target if target.exists() else Path(repo_dir)), safe="")
    return ""


def summary_for_log(ok: bool, reason: str) -> str:
    """日志只记成败和原因，不记随手记的正文。"""
    return "ok" if ok else json.dumps(reason[-120:], ensure_ascii=False)
