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

#: 不是给人用的发行版，设置页不列
_HIDDEN_DISTROS = {"docker-desktop", "docker-desktop-data", "rancher-desktop", "rancher-desktop-data"}


def normalize(value, *, default_distro: Callable[[], str] | None = None) -> dict:
    """``{"workspace_dir": 本机目录, "wsl_dirs": {发行版: 发行版里的目录}, "menu_limit": 条数}``。

    早先只有一个 ``workspace_dir``：里面填的若是 WSL 路径（``/home/…`` 或 ``\\\\wsl.localhost\\…``），
    搬到 ``wsl_dirs`` 对应的发行版下面。"""
    raw = value if isinstance(value, dict) else {}
    try:
        limit = int(raw.get("menu_limit", DEFAULT_LIMIT))
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    wsl_dirs: dict[str, str] = {}
    raw_dirs = raw.get("wsl_dirs")
    if isinstance(raw_dirs, dict):
        for distro, path in raw_dirs.items():
            distro, path = str(distro or "").strip(), str(path or "").strip()
            if distro and path:
                wsl_dirs[distro] = _inner_wsl_path(path)[:1000]
    local = str(raw.get("workspace_dir") or "").strip()[:1000]
    wsl, distro, inner = parse_directory(local, default_distro=default_distro or default_wsl_distro)
    if wsl:
        if distro and inner:
            wsl_dirs.setdefault(distro, inner)
        local = ""
    return {"workspace_dir": local, "wsl_dirs": wsl_dirs,
            "menu_limit": max(LIMIT_RANGE[0], min(LIMIT_RANGE[1], limit))}


def _inner_wsl_path(path: str) -> str:
    """发行版那一行里填的路径：POSIX 原样；误填成 UNC 形式的取它里面的那一段。"""
    wsl, _distro, inner = parse_directory(path, default_distro=lambda: "?")
    return inner if wsl else path


def wsl_distros(*, enumerate_registry: Callable[[], list[tuple[str, bool]]] | None = None) -> list[str]:
    """本机装着的 WSL 发行版，默认的排第一；Docker 之类的内部发行版不列。没有 WSL 返回空。"""
    pairs = (enumerate_registry or _registry_distros)()
    named = [(name, is_default) for name, is_default in pairs if name and name.lower() not in _HIDDEN_DISTROS]
    return [name for name, is_default in named if is_default] + [name for name, is_default in named if not is_default]


def _registry_distros() -> list[tuple[str, bool]]:
    import sys

    if sys.platform != "win32":
        return []
    try:
        import winreg

        found = []
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Lxss") as lxss:
            try:
                default = str(winreg.QueryValueEx(lxss, "DefaultDistribution")[0])
            except OSError:
                default = ""
            index = 0
            while True:
                try:
                    sub = winreg.EnumKey(lxss, index)
                except OSError:
                    break
                index += 1
                try:
                    with winreg.OpenKey(lxss, sub) as key:
                        found.append((str(winreg.QueryValueEx(key, "DistributionName")[0] or ""), sub == default))
                except OSError:
                    continue
        return found
    except (OSError, ValueError, TypeError):
        return []


# ---------------------------------------------------------------- 用户目录里的工作区文件

def default_wsl_distro() -> str:
    """默认 WSL 发行版的名字（注册表里记着，读一次不到 0.1 ms）；没有 WSL / 不是 Windows 返回空。"""
    import sys

    if sys.platform != "win32":
        return ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Lxss") as lxss:
            guid = winreg.QueryValueEx(lxss, "DefaultDistribution")[0]
            with winreg.OpenKey(lxss, str(guid)) as distro:
                return str(winreg.QueryValueEx(distro, "DistributionName")[0] or "")
    except (OSError, ValueError, TypeError):
        return ""


def parse_directory(path: str, *, default_distro: Callable[[], str] = default_wsl_distro) -> tuple[bool, str, str]:
    """``(是否 WSL, 发行版, 发行版里 / 本机的路径)``。

    认三种写法：``\\\\wsl.localhost\\<发行版>\\…`` / ``\\\\wsl$\\<发行版>\\…``（发行版写在路径里）、
    ``/home/me/workspace`` 这种 WSL 里的原生路径（按默认发行版）、本机路径。"""
    text = str(path or "").strip()
    match = _UNC_WSL_RE.match(text)
    if match:
        distro, rest = match.group(1), match.group(2).replace("\\", "/").strip("/")
        return True, distro, "/" + rest
    if text.startswith("/"):
        return True, default_distro() or "", posixpath.normpath(text.replace("\\", "/")).rstrip("/") or "/"
    return False, "", text


def listing_path(path: str, *, distro: str = "",
                 default_distro: Callable[[], str] = default_wsl_distro) -> str:
    """Windows 这边真正去读的路径：WSL 里的经 ``\\\\wsl.localhost\\<发行版>`` 共享；认不出发行版返回空。

    ``distro`` 给定时 ``path`` 是那个发行版里的目录（设置页按发行版分行填的那种）。"""
    if distro:
        wsl, found, inner = True, distro, _inner_wsl_path(str(path or "").strip())
        inner = posixpath.normpath(inner).rstrip("/") if inner else ""
    else:
        wsl, found, inner = parse_directory(path, default_distro=default_distro)
    if not inner:
        return ""
    if not wsl:
        return inner
    if not found:
        return ""
    return "\\\\wsl.localhost\\" + found + inner.replace("/", "\\")


def directory_exists(path: str, *, distro: str = "") -> bool:
    """设置页提示用：这个目录现在读得到吗。"""
    target = listing_path(path, distro=distro)
    return bool(target) and os.path.isdir(target)


def scan_workspace_dir(path: str, *, distro: str = "", listdir: Callable[[str], list[str]] | None = None,
                       default_distro: Callable[[], str] = default_wsl_distro) -> list[WorkspaceEntry]:
    """目录里的 ``*.code-workspace``（不递归）。目录不存在 / 读不了就是空。``distro`` 见 ``listing_path``。"""
    if distro:
        wsl, inner = True, _inner_wsl_path(str(path or "").strip())
        inner = posixpath.normpath(inner).rstrip("/") if inner else ""
    else:
        wsl, distro, inner = parse_directory(path, default_distro=default_distro)
    where = listing_path(path, distro=distro if wsl else "", default_distro=default_distro)
    if not inner or not where:
        return []
    try:
        names = sorted((listdir or os.listdir)(where))
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
    if scanned is None:
        scanned = scan_workspace_dir(settings["workspace_dir"])
        for distro, path in settings["wsl_dirs"].items():
            scanned += scan_workspace_dir(path, distro=distro)
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
    configured = {entry.key for entry in scanned}
    for entry in scanned:
        merged.setdefault(entry.key, entry)

    def rank(item: WorkspaceEntry) -> int:
        # 开着的 → 用户目录里的（他特意配的，不能被「最近」挤出条数上限）→ 其余最近用过的
        return 0 if item.open else 1 if item.key in configured else 2

    # 稳定排序：开着的几个之间保持 VS Code 清单里的顺序；目录里的按文件名；最近的按时间
    ordered = sorted(merged.values(), key=lambda item: (rank(item), -item.last_used))
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
