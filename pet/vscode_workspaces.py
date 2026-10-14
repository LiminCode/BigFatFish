# -*- coding: utf-8 -*-
"""右键菜单「VS Code 工作区」：列出开着的、最近用过的、以及用户目录里的工作区，点一下切过去或打开。

三个来源，全部只读：

1. **开着的窗口**：VS Code 自己的窗口清单（``claude_session_jump.opened_workspaces``）。
2. **最近用过的**：VS Code 给每个开过的文件夹 / 工作区留的状态目录
   （``workspaceStorage/<id>/``），拿里面 ``state.vscdb`` 的修改时间当「最后活动时间」。
   这个版本的 VS Code 已经不在全局状态库里存「最近打开」列表了（2026-10-13 实测），只能这样拿。
3. **用户指定的目录**里的 ``*.code-workspace`` 文件。目录可以是本机路径，也可以是
   ``\\\\wsl.localhost\\<发行版>\\…``——后者当成 WSL 里的工作区，打开时加 ``--remote``。

同一个工作区在几个来源里都出现时只留一条，开着的排最前，其余按最后活动时间倒序。

点一条：开着的就把那个窗口调到前台（和「跳到对话」同一套找窗口的办法）；没开的就
``code [--remote wsl+发行版] <路径>``——VS Code 按路径去重，已经开着的不会再开一个。
"""

from __future__ import annotations

import ntpath
import os
import posixpath
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import claude_session_jump as jump
from .claude_session_info import SessionDetail

CONFIG_KEY = "vscode_workspaces"
DEFAULT_LIMIT = 12
LIMIT_RANGE = (3, 30)
WORKSPACE_SUFFIX = ".code-workspace"
#: 「最近」只看这么久以内动过的状态目录；再久远的通常已经不在了
RECENT_WINDOW_S = 60 * 24 * 3600

_UNC_WSL_RE = re.compile(r"^[\\/]{2}(?:wsl\.localhost|wsl\$)[\\/]([^\\/]+)[\\/](.*)$", re.I)


@dataclass(frozen=True)
class WorkspaceEntry:
    label: str                 # 菜单上的名字：文件夹名，或工作区文件名（不含扩展名）
    target: str                # 交给 code 命令的路径（文件夹或工作区文件；WSL 的是发行版里的路径）
    wsl: bool = False
    distro: str = ""
    multi_root: bool = False
    open: bool = False         # 现在就开着一个窗口
    last_used: float = 0.0     # 最后活动时间（时间戳）；来自目录扫描的为 0

    @property
    def key(self) -> tuple[bool, str]:
        return self.wsl, self.target.lower()


# ---------------------------------------------------------------- 配置

def normalize(value) -> dict:
    raw = value if isinstance(value, dict) else {}
    try:
        limit = int(raw.get("menu_limit", DEFAULT_LIMIT))
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    return {
        "workspace_dir": str(raw.get("workspace_dir") or "").strip()[:1000],
        "menu_limit": max(LIMIT_RANGE[0], min(LIMIT_RANGE[1], limit)),
    }


# ---------------------------------------------------------------- 用户目录里的工作区文件

def parse_directory(path: str) -> tuple[bool, str, str]:
    """``(是否 WSL, 发行版, 发行版里 / 本机的路径)``。UNC 的 WSL 形式换算成发行版里的 POSIX 路径。"""
    text = str(path or "").strip()
    match = _UNC_WSL_RE.match(text)
    if match:
        distro, rest = match.group(1), match.group(2).replace("\\", "/").strip("/")
        return True, distro, "/" + rest
    return False, "", text


def scan_workspace_dir(path: str, *, listdir: Callable[[str], list[str]] | None = None) -> list[WorkspaceEntry]:
    """目录里的 ``*.code-workspace``（不递归）。目录不存在 / 读不了就是空。"""
    wsl, distro, inner = parse_directory(path)
    if not inner:
        return []
    try:
        names = sorted((listdir or os.listdir)(path))
    except (OSError, ValueError):
        return []
    entries = []
    for name in names:
        if not name.lower().endswith(WORKSPACE_SUFFIX):
            continue
        if wsl:
            target = posixpath.join(inner, name)
        else:
            target = ntpath.join(inner, name) if "\\" in inner or ntpath.splitdrive(inner)[0] else posixpath.join(inner, name)
        entries.append(WorkspaceEntry(name[:-len(WORKSPACE_SUFFIX)], target, wsl=wsl, distro=distro, multi_root=True))
    return entries


# ---------------------------------------------------------------- VS Code 自己记的

def open_entries(workspaces: list[jump.OpenWorkspace] | None = None) -> list[WorkspaceEntry]:
    """开着的窗口（顺序 = VS Code 清单里的顺序）。"""
    found = []
    for item in (jump.opened_workspaces() if workspaces is None else workspaces):
        distro = _distro_of(item)
        found.append(WorkspaceEntry(item.label, item.target, wsl=item.wsl, distro=distro,
                                    multi_root=item.multi_root, open=True, last_used=time.time()))
    return found


def _distro_of(item: jump.OpenWorkspace) -> str:
    return getattr(item, "distro", "") or ""


def recent_entries(appdata: str | os.PathLike | None = None, *, now: float | None = None) -> list[WorkspaceEntry]:
    """最近用过的（按状态目录里 ``state.vscdb`` 的修改时间倒序；``RECENT_WINDOW_S`` 以外的不要）。"""
    base = appdata if appdata is not None else os.environ.get("APPDATA")
    if not base:
        return []
    now = time.time() if now is None else now
    found: dict[tuple[bool, str], WorkspaceEntry] = {}
    for name in jump._VSCODE_DATA_DIRS:
        root = Path(base) / name / "User" / "workspaceStorage"
        try:
            folders = list(root.iterdir())
        except OSError:
            continue
        for folder in folders:
            entry = _entry_from_storage(folder, now)
            if entry is None:
                continue
            kept = found.get(entry.key)
            if kept is None or entry.last_used > kept.last_used:
                found[entry.key] = entry
    return sorted(found.values(), key=lambda item: -item.last_used)


def _entry_from_storage(folder: Path, now: float) -> WorkspaceEntry | None:
    import json

    try:
        meta = json.loads((folder / "workspace.json").read_text(encoding="utf-8"))
        stamp = max(((folder / child).stat().st_mtime for child in ("state.vscdb", "workspace.json")
                     if (folder / child).exists()), default=0.0)
    except (OSError, ValueError):
        return None
    if not isinstance(meta, dict) or not stamp or now - stamp > RECENT_WINDOW_S:
        return None
    uri = meta.get("folder")
    multi_root = False
    if not isinstance(uri, str):
        workspace = meta.get("workspace")
        uri = workspace.get("configPath") if isinstance(workspace, dict) else workspace
        multi_root = True
    parsed = jump._split_uri(uri) if isinstance(uri, str) else None
    if parsed is None:
        return None
    kind, distro, path = parsed
    target = jump._norm(path)
    name = posixpath.basename(target)
    label = name[:-len(WORKSPACE_SUFFIX)] if multi_root and name.endswith(WORKSPACE_SUFFIX) else name
    if not label:
        return None
    if kind == "local" and not os.path.exists(target):
        return None       # 文件夹已经删了：别列一条点了会报错的
    return WorkspaceEntry(label, target, wsl=kind == "wsl", distro=distro, multi_root=multi_root, last_used=stamp)


# ---------------------------------------------------------------- 合并

def list_workspaces(settings, *, opened: list[WorkspaceEntry] | None = None,
                    recent: list[WorkspaceEntry] | None = None,
                    scanned: list[WorkspaceEntry] | None = None) -> list[WorkspaceEntry]:
    """菜单要显示的那几条：开着的在前，其余按最后活动时间；同一个工作区只留一条。"""
    settings = normalize(settings)
    opened = open_entries() if opened is None else opened
    scanned = scan_workspace_dir(settings["workspace_dir"]) if scanned is None else scanned
    recent = recent_entries() if recent is None else recent
    merged: dict[tuple[bool, str], WorkspaceEntry] = {}
    for entry in opened:
        merged.setdefault(entry.key, entry)
    for entry in recent:
        kept = merged.get(entry.key)
        if kept is None:
            merged[entry.key] = entry
        elif kept.open and kept.distro == "" and entry.distro:
            merged[entry.key] = WorkspaceEntry(kept.label, kept.target, kept.wsl, entry.distro,
                                               kept.multi_root, True, kept.last_used)
    for entry in scanned:
        merged.setdefault(entry.key, entry)
    # 稳定排序：开着的几个之间保持 VS Code 清单里的顺序，不按名字重排
    ordered = sorted(merged.values(), key=lambda item: (not item.open, -item.last_used))
    return disambiguate(ordered[:settings["menu_limit"]])


def disambiguate(entries: list[WorkspaceEntry]) -> list[WorkspaceEntry]:
    """同名的条目加上能区分的后缀：文件夹带父目录名，工作区文件标「工作区」。

    实机上就有三个不同父目录下的同名项目同时开着，光看名字分不出哪个是哪个。"""
    from dataclasses import replace

    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.label] = counts.get(entry.label, 0) + 1
    out = []
    for entry in entries:
        if counts[entry.label] < 2:
            out.append(entry)
            continue
        if entry.multi_root:
            suffix = "工作区"
        else:
            suffix = posixpath.basename(posixpath.dirname(jump._norm(entry.target))) or entry.target
        out.append(replace(entry, label=f"{entry.label} · {suffix}"))
    return out


# ---------------------------------------------------------------- 点一条

def activate(entry: WorkspaceEntry, *, windows: Callable[[], list[jump.Window]] = jump.list_windows,
             focus: Callable[[int], bool] = jump.focus_window,
             launch: Callable[..., bool] = jump.open_in_vscode) -> tuple[bool, str]:
    """开着的调到前台，没开的用 code 命令打开。返回 (成功?, 给用户看的一句话)。阻塞几百毫秒。"""
    if entry.open:
        owner = jump.OpenWorkspace(entry.label, (entry.target,), entry.target, wsl=entry.wsl,
                                   multi_root=entry.multi_root)
        found = jump.vscode_candidates(windows(), entry.target, wsl=entry.wsl, owner=owner)
        if len(found) == 1 and focus(found[0].hwnd):
            return True, f"已切到 {entry.label}"
    detail = SessionDetail(agent="claude_wsl" if entry.wsl else "claude", cwd=entry.target, distro=entry.distro)
    if entry.wsl and not entry.distro:
        return False, f"不知道 {entry.label} 在哪个 WSL 发行版里"
    if not launch(detail, entry.target):
        return False, "找不到 code 命令，打不开 VS Code"
    return True, f"已{'切到' if entry.open else '打开'} {entry.label}"
