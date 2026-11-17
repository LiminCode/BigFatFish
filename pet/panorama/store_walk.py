# -*- coding: utf-8 -*-
"""把一个目录走一遍，数出每个文件属于存储表的哪一项。

**只用标准库，也不 import 肥鱼的任何模块**——「一个路径属于哪一项」由调用方把判定函数传进来（``match``）。
这样同一段代码两处用：这台机器上由 ``storage_probe.survey`` 传 ``data_stores.match`` 调；WSL 那边由
``probes.wsl_source`` 把存储表、这个文件、家目录探针三份源码拼成一个文件，喂给发行版里的 ``python3 -``。

拼在一起就落在同一个作用域里，所以这里的名字都带 ``walk`` / ``survey`` 字样，别和另外两个文件撞
（``tests/test_panorama_wsl_side.py`` 查这一条）。

只看文件名、大小和修改时间，不打开任何文件；不跟符号链接和目录联接进去（免得绕圈，也免得数到别处的东西）。
"""
from __future__ import annotations

import datetime
import os

WALK_UNKNOWN_LIMIT = 30         # 不认得的文件最多报这么多个名字（总数照实报）
WALK_MAX_FILES = 50_000         # 一个目录最多数这么多个文件：会话记录攒多了也不至于拖住采集


def _walk_stamp(seconds):
    try:
        return datetime.datetime.fromtimestamp(seconds).strftime("%Y-%m-%d %H:%M") if seconds else ""
    except (OSError, OverflowError, ValueError):
        return ""


def survey_tree(root_key, root_dir, match, max_files=WALK_MAX_FILES, unknown_limit=WALK_UNKNOWN_LIMIT):
    """``root_dir`` 下每个文件归哪一项：``{path, exists, files, truncated, stores: {id: {files, bytes, mtime}}, unknown, unknown_count}``。

    ``match(root_key, 相对路径)`` 返回那一项（有 ``id``）或 ``None``；``None`` 的记进 ``unknown``（只记名字）。
    """
    root = str(root_dir)
    out = {"path": root, "exists": os.path.isdir(root), "files": 0, "truncated": False, "stores": {}, "unknown": [], "unknown_count": 0}
    if not out["exists"]:
        return out
    tally, unknown = {}, []
    prefix = len(root.rstrip("\\/")) + 1
    stack = [root]
    while stack and not out["truncated"]:
        try:
            entries = sorted(os.scandir(stack.pop()), key=lambda entry: entry.name)
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(entry.path)
                    continue
                stat = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if out["files"] >= max_files:
                out["truncated"] = True
                break
            out["files"] += 1
            relative = entry.path[prefix:].replace(os.sep, "/")
            store = match(root_key, relative)
            if store is None:
                unknown.append(relative)
                continue
            row = tally.setdefault(store.id, {"files": 0, "bytes": 0, "mtime": 0.0})
            row["files"] += 1
            row["bytes"] += stat.st_size
            row["mtime"] = max(row["mtime"], stat.st_mtime)
    out["stores"] = {store_id: dict(row, mtime=_walk_stamp(row["mtime"])) for store_id, row in sorted(tally.items())}
    unknown.sort()
    out["unknown"], out["unknown_count"] = unknown[:unknown_limit], len(unknown)
    return out
