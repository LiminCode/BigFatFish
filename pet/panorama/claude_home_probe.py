# -*- coding: utf-8 -*-
"""只读地探一个 Claude Code 家目录（``~/.claude`` 和 ``~/.claude.json``）。

**只用标准库**，这是有意的：同一份源码跑两遍。Windows 这边直接 import 调 ``probe()``；WSL 那边由
``pet.panorama.probes.wsl_side`` 把这个文件的文本从标准输入喂给发行版里的 ``python3 -``。两边由同一份
实现来读，不会各写一套然后慢慢读出两个结果。所以这里不能 import 肥鱼的任何模块。

这里什么都不写；凭据文件只看在不在，不读内容。
"""
from __future__ import annotations

import datetime as _dt
import glob
import json
import os
import re
import subprocess
import sys
import time

MARK = "big-fat-fish"
BLOCK_RE = re.compile(r"<!-- big-fat-fish:memory-distill:start -->(.*?)<!-- big-fat-fish:memory-distill:end -->", re.S)
MEMORY_LIST_LIMIT = 40
TOOL_DIRS = (".config/gh", ".aws", ".kube", ".codex", ".cursor", ".gemini")


def _load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _mtime(path):
    try:
        return _dt.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
    except OSError:
        return ""


def hooks_summary(settings):
    """``{事件: {"total": 挂了几条命令, "fish": 其中几条是肥鱼的}}``。"""
    out = {}
    hooks = settings.get("hooks")
    for event, groups in (hooks.items() if isinstance(hooks, dict) else ()):
        commands = [hook for group in (groups if isinstance(groups, list) else []) if isinstance(group, dict)
                    for hook in (group.get("hooks") or []) if isinstance(hook, dict)]
        out[event] = {"total": len(commands), "fish": sum(MARK in json.dumps(hook, ensure_ascii=False) for hook in commands)}
    return out


def claude_md_summary(path):
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return {"exists": False, "path": path}
    block = BLOCK_RE.search(text)
    updated = re.search(r"<!-- 更新：(.*?) -->", block.group(1)) if block else None
    return {"exists": True, "path": path, "bytes": len(text.encode("utf-8")), "lines": text.count("\n") + 1,
            "mtime": _mtime(path), "managed_block": bool(block),
            "managed_rules": len(re.findall(r"^- \*\*", block.group(1), re.M)) if block else 0,
            "managed_updated": updated.group(1) if updated else ""}


def parse_mcp_list(output):
    """``claude mcp list`` 的输出 → ``[{name, state: ok | auth | bad, detail}]``。"""
    rows = []
    for line in output.splitlines():
        name, colon, rest = line.strip().partition(": ")          # ``名字: 地址或命令 - 状态``；命令里可以有空格
        target, dash, status = rest.rpartition(" - ")
        if not (colon and dash and name and target):
            continue
        status = status.strip()
        state = "ok" if "Connected" in status else "auth" if "authentication" in status.lower() else "bad"
        rows.append({"name": name, "state": state, "detail": status})
    return rows


def _mcp_list(timeout):
    try:
        done = subprocess.run(["bash", "-lc", "cd ~ && claude mcp list 2>&1"], capture_output=True, text=True, timeout=timeout)
        return parse_mcp_list(done.stdout)
    except (OSError, subprocess.SubprocessError):
        return None


def _ssh_hosts(home):
    hosts = []
    try:
        with open(os.path.join(home, ".ssh", "config"), encoding="utf-8", errors="replace") as fh:
            for line in fh:
                match = re.match(r"\s*Host\s+(.+)", line)
                if match:
                    hosts += match.group(1).split()
    except OSError:
        pass
    return hosts


def probe(home, with_mcp=False, mcp_timeout=90):
    """地图上关于这一个家目录的全部事实。``with_mcp`` 会去跑 ``claude mcp list``（逐个体检，要几秒）。"""
    home = str(home)
    claude = os.path.join(home, ".claude")
    settings_path = os.path.join(claude, "settings.json")
    settings, state = _load(settings_path), _load(os.path.join(home, ".claude.json"))
    installed = _load(os.path.join(claude, "plugins", "installed_plugins.json"))
    memory = []
    for index in glob.glob(os.path.join(claude, "projects", "*", "memory", "MEMORY.md")):
        folder = os.path.dirname(index)
        memory.append({"name": os.path.basename(os.path.dirname(folder)), "path": folder, "mtime": _mtime(index),
                       "files": max(0, len(glob.glob(os.path.join(folder, "*.md"))) - 1)})
    memory.sort(key=lambda row: row["mtime"], reverse=True)
    connectors, seconds = None, None
    if with_mcp:
        started = time.time()
        connectors = _mcp_list(mcp_timeout)
        seconds = round(time.time() - started, 1)
    account = state.get("oauthAccount") or {}
    return {
        "home": home, "platform": sys.platform, "distro": os.environ.get("WSL_DISTRO_NAME", ""),
        "user": os.environ.get("USER") or os.environ.get("USERNAME") or "",
        "account": {"email": account.get("emailAddress", ""), "organization": account.get("organizationName", "")},
        "settings_path": settings_path, "settings_mtime": _mtime(settings_path),
        "model": str(settings.get("model") or ""), "effort": str(settings.get("effortLevel") or ""),
        "hooks": hooks_summary(settings), "allow_rules": len((settings.get("permissions") or {}).get("allow") or []),
        "plugins": sorted(set(settings.get("enabledPlugins") or {}) | set(installed.get("plugins") or {})),
        "mcp_servers": sorted(state.get("mcpServers") or {}), "state_path": os.path.join(home, ".claude.json"),
        "ever_connected": [str(name) for name in state.get("claudeAiMcpEverConnected") or []],
        "claude_md": claude_md_summary(os.path.join(claude, "CLAUDE.md")),
        "projects": len(glob.glob(os.path.join(claude, "projects", "*", ""))),
        "memory_count": len(memory), "memory_projects": memory[:MEMORY_LIST_LIMIT],
        "distilled_files": len(glob.glob(os.path.join(claude, "projects", "*", "memory", "distill-*.md"))),
        "credentials_path": os.path.join(claude, ".credentials.json"),
        "credentials_file": os.path.isfile(os.path.join(claude, ".credentials.json")),
        "tools": [name for name in TOOL_DIRS if os.path.exists(os.path.join(home, *name.split("/")))],
        "ssh_hosts": _ssh_hosts(home), "connectors": connectors, "mcp_probe_seconds": seconds,
    }


if __name__ == "__main__":
    print(json.dumps(probe(os.path.expanduser("~"), with_mcp="--mcp" in sys.argv), ensure_ascii=False))
