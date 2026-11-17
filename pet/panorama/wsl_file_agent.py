# -*- coding: utf-8 -*-
"""在 WSL 里替页面读文件的那一小段。

页面要看 WSL 里那个 Claude Code 家目录的文件时，``files.Reader`` 把**这个文件的文本**加上一行
``agent_main('<请求>')``，从标准输入喂给发行版里的 ``python3 -``，结果是打印出来的一行 JSON。
所以这里**只用标准库**，不 import 肥鱼的任何模块。

请求里的路径在 Windows 那边已经过了三关（在查看名单里、是规矩的相对路径、按存储表正好属于那一项）；
这里守第四关，只有在 WSL 里面才守得了：**路径上不经过任何符号链接，而且是个普通文件**——解开链接后的真实位置
必须正好是「``~/.claude`` + 这条路径」。只查「还在根里面」不够：根里面的一个链接可以把一条看着无害的路径引到别的文件上。

输出只用 ASCII（非 ASCII 字符写成 ``\\uXXXX``）：不依赖管道两头的编码设置。
"""
from __future__ import annotations

import datetime
import json
import os

AGENT_BINARY_PROBE = 8192       # 开头这么多字节里有 NUL 就当它不是文字


def _agent_stamp(seconds):
    try:
        return datetime.datetime.fromtimestamp(seconds).strftime("%Y-%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return ""


def _agent_inside(root, relative):
    """解开链接后的真实路径。它必须正好是「根 + 这条相对路径」；路径上经过了链接、或者不是普通文件，返回 ``None``。"""
    real_root = os.path.realpath(root)
    real = os.path.realpath(os.path.join(root, *relative.split("/")))
    if not os.path.isfile(real):
        return None
    try:
        straight = os.path.relpath(real, real_root).replace(os.sep, "/") == relative
    except ValueError:                      # Windows 上不同盘符之间没有相对路径
        return None
    return real if straight else None


def agent_list(root, starts, names, limit):
    """``starts`` 这几个子目录下的所有文件，加上 ``names`` 这几个点了名的文件：相对路径、大小、修改时间。

    哪些真的属于要看的那一项，由 Windows 那边按存储表去筛；这里只保证每一个都在根里面。
    """
    found = set(names)
    for start in starts:
        stack = [os.path.join(root, *start.split("/")) if start else root]
        while stack and len(found) <= limit:
            try:
                entries = list(os.scandir(stack.pop()))
            except OSError:
                continue
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                    else:
                        found.add(os.path.relpath(entry.path, root).replace(os.sep, "/"))
                except OSError:
                    continue
    rows = []
    for relative in sorted(found):
        real = _agent_inside(root, relative)
        if real is None:
            continue
        try:
            stat = os.stat(real)
        except OSError:
            continue
        rows.append({"path": relative, "bytes": stat.st_size, "mtime": _agent_stamp(stat.st_mtime)})
    return {"files": rows[:limit], "truncated": len(rows) > limit}


def agent_read(root, relative, max_bytes):
    """读一个文件的文本，原样（最多 ``max_bytes``；不是 UTF-8 的字节换成替代符；不是文字的只说它不是）。"""
    if not os.path.lexists(os.path.join(root, *relative.split("/"))):
        return {"error": "not_found"}
    real = _agent_inside(root, relative)
    if real is None:
        return {"error": "bad_path"}
    try:
        stat = os.stat(real)
        with open(real, "rb") as handle:
            raw = handle.read(max_bytes + 1)
    except OSError:
        return {"error": "not_found"}
    binary = b"\x00" in raw[:AGENT_BINARY_PROBE]
    return {"text": "" if binary else raw[:max_bytes].decode("utf-8", "replace"), "bytes": stat.st_size,
            "mtime": _agent_stamp(stat.st_mtime), "truncated": not binary and len(raw) > max_bytes, "binary": binary}


def agent_main(request):
    """``request`` 是一段 JSON：``{"op": "list", "starts": [...], "names": [...], "limit": n}`` 或
    ``{"op": "read", "path": "相对路径", "max": n}``。根固定是 ``~/.claude``，请求改不了它。"""
    asked = json.loads(request)
    root = os.path.join(os.path.expanduser("~"), ".claude")
    if asked.get("op") == "list":
        answer = agent_list(root, list(asked.get("starts") or []), list(asked.get("names") or []), int(asked.get("limit") or 1000))
    elif asked.get("op") == "read":
        answer = agent_read(root, str(asked.get("path") or ""), int(asked.get("max") or 0))
    else:
        answer = {"error": "bad_request"}
    print(json.dumps(answer))
