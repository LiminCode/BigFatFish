# -*- coding: utf-8 -*-
"""存储探针：存储表说的是设计，这里看的是此刻这台机器上的实际情况。

- ``survey``：把一个目录走一遍，每个文件归到存储表的哪一项（各有多少个、多大、最近什么时候动过），
  表不认得的文件报名字；
- ``named``：不能整个走一遍的地方（用户的家目录），只看表里点了名的那几个文件；
- ``backup_state``：配置备份开没开、推去哪、上次什么时候、上次成没成。

全部只读，**只看文件名、大小和修改时间，不打开任何文件**（配置备份的簿记除外，那是肥鱼自己的状态文件）。
会碰磁盘，只能在后台线程里调。
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from .. import config_backup
from .. import data_stores as ds
from . import store_walk

UNKNOWN_LIMIT = store_walk.WALK_UNKNOWN_LIMIT       # 不认得的文件最多报这么多个名字（总数照实报）
MAX_FILES = store_walk.WALK_MAX_FILES               # 一个目录最多数这么多个文件


def _stamp(seconds: float) -> str:
    try:
        return dt.datetime.fromtimestamp(seconds).strftime("%Y-%m-%d %H:%M") if seconds else ""
    except (OSError, OverflowError, ValueError):
        return ""


def _empty(root: Path) -> dict:
    return {"path": str(root), "exists": root.is_dir(), "files": 0, "truncated": False, "stores": {}, "unknown": [], "unknown_count": 0}


def _count(tally: dict, store_id: str, size: int, mtime: float) -> None:
    row = tally.setdefault(store_id, {"files": 0, "bytes": 0, "mtime": 0.0})
    row["files"] += 1
    row["bytes"] += size
    row["mtime"] = max(row["mtime"], mtime)


def _finish(out: dict, tally: dict, unknown: list[str]) -> dict:
    out["stores"] = {store_id: {**row, "mtime": _stamp(row["mtime"])} for store_id, row in sorted(tally.items())}
    unknown.sort()
    out["unknown"], out["unknown_count"] = unknown[:UNKNOWN_LIMIT], len(unknown)
    return out


def survey(root_key: str, root_dir: str | Path, *, max_files: int = MAX_FILES) -> dict:
    """``root_dir`` 下每个文件归哪一项。走目录的那段代码在 ``store_walk``（WSL 那边跑的是同一段）。"""
    return store_walk.survey_tree(root_key, str(Path(root_dir)), ds.match, max_files=max_files, unknown_limit=UNKNOWN_LIMIT)


def named(root_key: str, root_dir: str | Path) -> dict:
    """只看存储表里写了确切名字的那些文件（模式里没有通配符的）。"""
    root = Path(root_dir)
    out = _empty(root)
    tally: dict = {}
    for store in ds.STORES:
        if store.root != root_key:
            continue
        for pattern in store.patterns:
            if "*" in pattern:
                continue
            try:
                stat = (root / pattern).stat()
            except OSError:
                continue
            out["files"] += 1
            _count(tally, store.id, stat.st_size, stat.st_mtime)
    return _finish(out, tally, [])


def backup_state(cfg: dict, config_dir: str | Path, kb_repo: str = "") -> dict:
    """配置备份此刻的状态。``repo`` 是实际会推去的仓库（设置里没填就跟知识库同一个），空 = 没地方可去。"""
    settings = config_backup.normalize(cfg.get("config_backup"))
    state = config_backup.load_state(config_dir)
    failed = bool(state.error) and state.attempted_at >= state.backed_up_at
    return {"auto": settings["auto"], "repo": config_backup.target_repo(settings, kb_repo), "path": settings["path"],
            "backed_up_at": _stamp(state.backed_up_at), "error": state.error if failed else "", "paused": bool(state.rebuilt_at)}


def collect(cfg: dict, *, config_dir: str | Path, home: str | Path, kb_repo: str = "") -> dict:
    """Windows 这一侧的全部存储事实。WSL 里那个家目录由那边的探针自己数（见 ``probes.wsl_source``）。"""
    home = Path(home)
    return {"data": survey("data", config_dir), "claude_home": survey("claude_home", home / ".claude"),
            "home": named("home", home), "config_backup": backup_state(cfg, config_dir, kb_repo)}
