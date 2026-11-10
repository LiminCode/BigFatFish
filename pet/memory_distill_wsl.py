# -*- coding: utf-8 -*-
"""会话记忆蒸馏·第三期（公司侧）——所有要进 WSL 才能做的事都经这里，全部走 ``wsl.exe``（``claude_hooks.run_wsl``）。

为什么要有公司侧：用户工作时在 WSL 里用登录**公司账号**的 Claude Code，那边的会话记录写在 WSL 自己的
``~/.claude/projects``，Windows 这边扫不到（桌面版开的 WSL 会话例外，它们存在 Windows 的 ``projects/ssh-*``）。

本文件现在只有抽取用的两个问询：默认发行版在不在跑、那边有哪些 transcript。都是阻塞调用，放后台线程。
"""
from __future__ import annotations

from typing import Callable

from . import claude_hooks
from . import memory_distill as md

WslRunner = Callable[..., tuple[int, str]]

LIST_TIMEOUT_S = 30.0          # 发行版冷启动要几秒
STATE_TIMEOUT_S = 10.0
#: 第一行：projects 目录在 Windows 这边的路径；之后每行「字节数<TAB>项目目录/会话.jsonl」。目录不存在只出第一行都没有。
LIST_COMMAND = ('d="$HOME/.claude/projects"; [ -d "$d" ] || exit 0; wslpath -w "$d"; '
                'find "$d" -mindepth 2 -maxdepth 2 -type f -name "*.jsonl" -printf "%s\\t%P\\n"')


def default_distro_running(runner: WslRunner = claude_hooks.run_wsl) -> bool:
    """默认发行版此刻在不在跑（``wsl.exe -l -v`` 里带 ``*`` 的那行）。这条命令本身不会把发行版拉起来。

    定时抽取靠它决定要不要去 WSL：没在跑就说明上次扫过之后那边最多只多了关机前的一小段，没必要为了每小时
    一次的增量把整个发行版叫醒（别的发行版——比如 docker-desktop——在跑不算）。"""
    try:
        code, out = runner(["-l", "-v"], timeout=STATE_TIMEOUT_S)
    except Exception:  # noqa: BLE001 - 问不到就当没在跑
        return False
    if code != 0:
        return False
    for line in out.splitlines():
        if line.lstrip().startswith("*"):
            return "running" in line.lower()
    return False


def list_transcripts(runner: WslRunner = claude_hooks.run_wsl) -> md.RemoteListing | None:
    """默认发行版里 ``~/.claude/projects/*/*.jsonl`` 的清单（一次 ``find``，实测 91 个文件 0.1 s）。

    会把没在跑的发行版拉起来。问不到返回 None——和「问到了、一个文件都没有」不是一回事：前者不能动那边的游标。"""
    try:
        code, out = runner(["-e", "sh", "-c", LIST_COMMAND], timeout=LIST_TIMEOUT_S)
    except Exception:  # noqa: BLE001
        return None
    lines = [line.rstrip("\r") for line in out.splitlines() if line.strip()]
    if code != 0 or not lines or not _looks_like_dir(lines[0]):
        return None
    files: list[tuple[str, int]] = []
    for line in lines[1:]:
        size, sep, rel = line.partition("\t")
        if not sep or not size.strip().isdigit() or not rel.endswith(".jsonl"):
            continue
        files.append((rel.strip(), int(size)))
    return md.RemoteListing(root=lines[0].strip(), files=tuple(sorted(files)))


def _looks_like_dir(line: str) -> bool:
    """``wslpath -w`` 的输出：UNC（``\\\\wsl.localhost\\…``）或盘符路径（``/`` 开头的绝对路径也认，测试在
    非 Windows 上跑时临时目录长这样）。登录横幅之类的别的字不算。"""
    text = line.strip()
    return text.startswith(("\\\\", "/")) or (len(text) > 2 and text[1] == ":" and text[2] in "\\/")


__all__ = [name for name in dir() if not name.startswith("_")]
