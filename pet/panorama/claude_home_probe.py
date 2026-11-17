# -*- coding: utf-8 -*-
"""只读地探一个 Claude Code 家目录（``~/.claude`` 和 ``~/.claude.json``）。

**只用标准库**，这是有意的：同一份源码跑两遍。Windows 这边直接 import 调 ``probe()``；WSL 那边由
``pet.panorama.probes.wsl_side`` 把这个文件的文本从标准输入喂给发行版里的 ``python3 -``。两边由同一份
实现来读，不会各写一套然后慢慢读出两个结果。所以这里不能 import 肥鱼的任何模块。

这里什么都不写；凭据文件只看在不在，不读内容。连接器「连到哪」会带出来，但地址里的账号口令和查询串、
命令行里跟在 ``--token`` 这类参数后面的值、``KEY=值`` 里的值都换成占位符；环境变量和请求头只留名字。
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
MEMORY_ENTRY_LIMIT = 600        # 记忆索引最多收这么多条（所有项目加起来）
MEMORY_TEXT_LIMIT = 240         # 说明、规矩正文最多留这么多字
MEMORY_HEAD_BYTES = 4096        # 每个记忆文件只读开头这么多：名字和说明都在文件头里
WORKSPACE_LIMIT = 60            # 工作空间最多列这么多个项目（最近用过的在前；总数照实报）
SESSION_HEAD_BYTES = 65536      # 认项目路径时，一份会话记录只读开头这么多
_CWD_RE = re.compile(r'"cwd"\s*:\s*"((?:[^"\\]|\\.)*)"')
_FRONT_RE = re.compile(r"\ufeff?---\r?\n(.*?)\r?\n---", re.S)
_RULE_RE = re.compile(r"^- \*\*(.+?)\*\*[ \t]*(?:[—–-]+[ \t]*)?(.*)$", re.M)
TOOL_DIRS = (".config/gh", ".aws", ".kube", ".cursor", ".gemini")


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


def _cut(text):
    text = " ".join(str(text or "").split())
    return text if len(text) <= MEMORY_TEXT_LIMIT else text[:MEMORY_TEXT_LIMIT] + "…"


def _memory_entry(path):
    """一个记忆文件的名字、说明、类型（文件头里的 ``name`` / ``description`` / ``type``）。**不带正文。**"""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            head = fh.read(MEMORY_HEAD_BYTES)
        size = os.path.getsize(path)
    except OSError:
        return None
    meta = {}
    front = _FRONT_RE.match(head)
    for line in (front.group(1).splitlines() if front else ()):
        key, colon, value = line.strip().partition(":")
        value = value.strip().strip("\"'")
        if colon and value and key in ("name", "description", "type"):
            meta.setdefault(key, value)
    if "name" not in meta:                          # 没有文件头：拿第一个标题，再不行拿文件名
        heading = re.search(r"^#+[ \t]+(.+)$", head, re.M)
        meta["name"] = heading.group(1).strip() if heading else os.path.splitext(os.path.basename(path))[0]
    return {"file": os.path.basename(path), "name": _cut(meta["name"]), "description": _cut(meta.get("description", "")),
            "type": meta.get("type", ""), "bytes": size, "mtime": _mtime(path)}


def memory_index(claude):
    """这个家目录里的记忆，按作用域：``rules`` 是 CLAUDE.md 受管块里的每条规矩，``sections`` 是受管块之外你自己写的
    小标题，``projects`` 是各项目记忆目录里的每个文件（``MEMORY.md`` 是目录，不算）。只有名字和说明，没有正文。"""
    out = {"rules": [], "sections": [], "projects": [], "entries": 0, "truncated": False}
    try:
        with open(os.path.join(claude, "CLAUDE.md"), encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        text = ""
    block = BLOCK_RE.search(text)
    if block:
        out["rules"] = [{"title": _cut(title), "text": _cut(body)} for title, body in _RULE_RE.findall(block.group(1))]
    outside = BLOCK_RE.sub("", text)
    out["sections"] = [_cut(title) for title in re.findall(r"^#{1,3}[ \t]+(.+)$", outside, re.M)][:MEMORY_LIST_LIMIT]
    for folder in sorted(glob.glob(os.path.join(claude, "projects", "*", "memory"))):
        entries = []
        for path in sorted(glob.glob(os.path.join(folder, "*.md"))):
            if os.path.basename(path) == "MEMORY.md":
                continue
            if out["entries"] >= MEMORY_ENTRY_LIMIT:
                out["truncated"] = True
                break
            entry = _memory_entry(path)
            if entry:
                entries.append(entry)
                out["entries"] += 1
        if entries:
            out["projects"].append({"name": os.path.basename(os.path.dirname(folder)), "entries": entries})
    return out


_SECRETISH = re.compile(r"(?i)key|token|secret|passw|auth|credential|bearer")


def _now():
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def safe_url(url):
    """地址里去掉 ``账号:口令@`` 和查询串（查询串里常带 token）；去掉了查询串就留一个 ``?…`` 表示原来有。"""
    url = re.sub(r"^(\w+://)[^/@\s]+@", r"\1", str(url or "").strip())
    head, mark, _query = url.partition("?")
    return head.split("#", 1)[0] + ("?…" if mark else "")


def safe_command(parts):
    """命令行拼回一行：``--token X`` 的 X、``TOKEN=X`` 的 X 换成 ``***``。认的是参数名字像不像密钥，不是值。"""
    out, hide_next = [], False
    for part in (str(part) for part in parts):
        name, equals, _value = part.partition("=")
        if hide_next:
            out.append("***")
            hide_next = False
        elif equals and _SECRETISH.search(name):
            out.append(name + "=***")
        else:
            out.append(part)
            hide_next = part.startswith("-") and bool(_SECRETISH.search(part))
    return " ".join(out)


def _target(text):
    """``claude mcp list`` 里那一段「地址或命令」→（远程还是本地，能给人看的写法）。"""
    text = str(text or "").strip()
    if re.match(r"^https?://", text):
        return "remote", safe_url(text)
    return "local", safe_command(text.split())


def mcp_detail(state):
    """``~/.claude.json`` 里登记的 MCP 服务器：用户级的（``mcpServers``）在前，项目级的（``projects.<路径>.mcpServers``）在后。

    每条：名字、``kind``（配置里的 ``type``，没写就按有没有 ``url`` 猜 http / stdio）、``target``（地址或命令行，
    密钥换成占位符）、``env``（环境变量和请求头的**名字**）、``project``（项目级的才有）。
    """
    def rows(servers, project):
        out = []
        for name, cfg in sorted(servers.items()) if isinstance(servers, dict) else ():
            if not isinstance(cfg, dict):
                continue
            url = cfg.get("url")
            args = cfg.get("args") if isinstance(cfg.get("args"), list) else []
            names = [key for field in ("env", "headers") if isinstance(cfg.get(field), dict) for key in cfg[field]]
            out.append({"name": str(name), "kind": str(cfg.get("type") or ("http" if url else "stdio")),
                        "target": safe_url(url) if url else safe_command([cfg.get("command") or "", *args]).strip(),
                        "env": sorted(str(key) for key in names), "project": project})
        return out

    found = rows(state.get("mcpServers"), "")
    projects = state.get("projects")
    for path, cfg in sorted(projects.items()) if isinstance(projects, dict) else ():
        if isinstance(cfg, dict):
            found += rows(cfg.get("mcpServers"), str(path))
    return found


def encode_project_path(path):
    """Claude Code 给项目目录起名的办法：绝对路径里不是字母数字的字符都换成 ``-``。"""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def _session_cwd(path):
    """一份会话记录开头记着的工作目录；读不到就是空串。只找这一个字段，别的不看。"""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            found = _CWD_RE.search(fh.read(SESSION_HEAD_BYTES))
        return json.loads('"' + found.group(1) + '"') if found else ""
    except (OSError, ValueError):
        return ""


def _exists(path):
    """这个目录还在不在。路径是另一个系统的写法（在 WSL 里看到 ``C:\\…``，或者反过来）就答不了：``None``。"""
    if not path:
        return None
    if bool(re.match(r"^[A-Za-z]:[\\/]", path)) != (os.name == "nt"):
        return None
    return os.path.isdir(path)


def _last_session(cfg):
    """``~/.claude.json`` 里记的这个项目上一次会话的几个数：花了多少、多久、改了多少行。全是零就当没有。"""
    def number(key):
        try:
            return float(cfg.get(key) or 0)
        except (TypeError, ValueError):
            return 0.0

    out = {"cost": round(number("lastCost"), 2), "minutes": int(round(number("lastDuration") / 60000)),
           "added": int(number("lastLinesAdded")), "removed": int(number("lastLinesRemoved"))}
    return out if any(out.values()) else {}


def workspaces(claude, state):
    """这个 Claude Code 干过活的项目：``projects/`` 下每个有会话记录或有记忆的目录一条，最近用过的在前。

    真实路径优先取 ``~/.claude.json`` 里登记的那个（按 ``encode_project_path`` 对上目录名）；没登记的，
    最新一份会话记录里的工作目录**编码后正好等于目录名**才用——对不上就留空，不猜（会话中途换过目录的对不上）。
    既没有会话也没有记忆的目录只数个数（``empty``）。只读文件名、大小、时间和那一个字段，不带会话内容。
    """
    out = {"projects": [], "total": 0, "empty": 0, "sessions": 0, "bytes": 0, "missing": 0, "truncated": False}
    known = {}
    registered = state.get("projects") if isinstance(state.get("projects"), dict) else {}
    for path, cfg in registered.items():
        known.setdefault(encode_project_path(path), (str(path), cfg if isinstance(cfg, dict) else {}))
    rows = []
    for folder in glob.glob(os.path.join(claude, "projects", "*", "")):
        folder = folder.rstrip("\\/")
        name = os.path.basename(folder)
        stamps = []
        for session in glob.glob(os.path.join(folder, "*.jsonl")):
            try:
                stamps.append((os.path.getmtime(session), os.path.getsize(session), session))
            except OSError:
                continue
        memory = [m for m in glob.glob(os.path.join(folder, "memory", "*.md")) if os.path.basename(m) != "MEMORY.md"]
        out["total"] += 1
        if not stamps and not memory:
            out["empty"] += 1
            continue
        newest = max(stamps) if stamps else (0.0, 0, "")
        path, cfg = known.get(name, ("", {}))
        if not path and newest[2]:
            cwd = _session_cwd(newest[2])
            path = cwd if cwd and encode_project_path(cwd) == name else ""
        exists = _exists(path)
        rows.append({"name": name, "path": path, "exists": exists, "sessions": len(stamps),
                     "last": _mtime(newest[2]) if newest[2] else "", "bytes": sum(size for _, size, _ in stamps),
                     "memory": len(memory), "last_session": _last_session(cfg), "_stamp": newest[0]})
        out["sessions"] += len(stamps)
        out["bytes"] += rows[-1]["bytes"]
        out["missing"] += exists is False
    rows.sort(key=lambda row: (-row.pop("_stamp"), row["name"]))
    out["projects"], out["truncated"] = rows[:WORKSPACE_LIMIT], len(rows) > WORKSPACE_LIMIT
    return out


def parse_mcp_list(output):
    """``claude mcp list`` 的输出 → ``[{name, state: ok | auth | bad, detail, kind: remote | local, target}]``。"""
    rows = []
    for line in output.splitlines():
        name, colon, rest = line.strip().partition(": ")          # ``名字: 地址或命令 - 状态``；命令里可以有空格
        target, dash, status = rest.rpartition(" - ")
        if not (colon and dash and name and target):
            continue
        status = status.strip()
        state = "ok" if "Connected" in status else "auth" if "authentication" in status.lower() else "bad"
        kind, shown = _target(target)
        rows.append({"name": name, "state": state, "detail": status, "kind": kind, "target": shown})
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
    connectors, seconds, mcp_probed_at = None, None, ""
    if with_mcp:
        started = time.time()
        connectors = _mcp_list(mcp_timeout)
        seconds = round(time.time() - started, 1)
        mcp_probed_at = _now() if connectors is not None else ""
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
        "mcp_detail": mcp_detail(state), "probed_at": _now(), "mcp_probed_at": mcp_probed_at,
        "ever_connected": [str(name) for name in state.get("claudeAiMcpEverConnected") or []],
        "claude_md": claude_md_summary(os.path.join(claude, "CLAUDE.md")),
        "projects": len(glob.glob(os.path.join(claude, "projects", "*", ""))),
        "memory_count": len(memory), "memory_projects": memory[:MEMORY_LIST_LIMIT],
        "distilled_files": len(glob.glob(os.path.join(claude, "projects", "*", "memory", "distill-*.md"))),
        "memory_index": memory_index(claude), "workspaces": workspaces(claude, state),
        "credentials_path": os.path.join(claude, ".credentials.json"),
        "credentials_file": os.path.isfile(os.path.join(claude, ".credentials.json")),
        "tools": [name for name in TOOL_DIRS if os.path.exists(os.path.join(home, *name.split("/")))],
        "ssh_hosts": _ssh_hosts(home), "connectors": connectors, "mcp_probe_seconds": seconds,
    }


if __name__ == "__main__":
    print(json.dumps(probe(os.path.expanduser("~"), with_mcp="--mcp" in sys.argv), ensure_ascii=False))
