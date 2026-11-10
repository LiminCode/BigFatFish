# -*- coding: utf-8 -*-
"""会话记忆蒸馏·第三期（公司侧）——落盘：接受了的公司侧提案写到 WSL 里的 Claude Code 一定会读的地方。

和个人侧（``memory_distill_sink``）同样的两个落点、同样的格式，只是文件在 WSL 默认发行版里：

1. **全局**：WSL 的 ``~/.claude/CLAUDE.md`` 里的受管块（同样的起止标记）。机器只改块内，块外逐字不动；改之前把
   整个文件备份到本机候选库目录下的 ``backups/``（``CLAUDE.md.wsl.<时间>.bak``）。
2. **项目**：WSL 的 ``~/.claude/projects/<编码>/memory/distill-<id>.md`` + ``MEMORY.md`` 一行索引。

条目库是公司侧自己的一份（``entries-work.json``）：个人侧的 CLAUDE.md 块和个人知识库那篇都是从 ``entries.json``
整篇渲染的，公司侧的条目混进去就会被写进个人侧。

所有读写都经 ``wsl.exe``（不走 ``\\\\wsl.localhost`` 共享：经共享原子替换会把文件权限重置，见
``claude_hooks.WslSettingsStore``）；内容走标准输入 / 输出，实测逐字节保真。阻塞，放后台线程。
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from . import claude_hooks
from . import memory_distill as md
from . import memory_distill_sink as sink
from . import memory_distill_wsl as mdw
from .i18n import t

MISSING = "@@BFF-MISSING@@"
IO_TIMEOUT_S = 30.0
BACKUP_PREFIX = "CLAUDE.md.wsl."
#: 只碰 WSL 里 ``~/.claude`` 之下的文件，路径里只许这些字符（会放进 shell 的双引号里，``$HOME`` 留给那边展开）
_SAFE_PATH_RE = re.compile(r"\$HOME/\.claude/[A-Za-z0-9._/-]+")


def _safe(path: str) -> bool:
    return bool(_SAFE_PATH_RE.fullmatch(str(path or ""))) and ".." not in path


def read_text(path: str, runner: mdw.WslRunner = claude_hooks.run_wsl) -> str | None:
    """WSL 里一个文件的全文。不存在返回空串；**问不到返回 None**（不能当成空文件再写回去）；含解不出的字节也返回
    None（``run_wsl`` 会把它们换成替代字符，写回去就改了原文）。"""
    if not _safe(path):
        return None
    try:
        code, out = runner(["-e", "sh", "-c", f'f="{path}"; [ -f "$f" ] || {{ printf %s {MISSING}; exit 0; }}; cat "$f"'],
                           timeout=IO_TIMEOUT_S)
    except Exception:  # noqa: BLE001
        return None
    if code != 0 or "�" in out:
        return None
    return "" if out == MISSING else out


def write_text(path: str, text: str, runner: mdw.WslRunner = claude_hooks.run_wsl) -> bool:
    """原子写：同目录临时文件 → 照抄原文件权限 → ``mv``。目录不存在就建。"""
    if not _safe(path):
        return False
    command = (f'f="{path}"; d=$(dirname "$f"); t="$f.bff.tmp"; mkdir -p "$d" && cat > "$t" '
               f'&& {{ [ ! -f "$f" ] || chmod --reference="$f" "$t"; }} && mv "$t" "$f"')
    try:
        code, _out = runner(["-e", "sh", "-c", command], input_text=text, timeout=IO_TIMEOUT_S)
    except Exception:  # noqa: BLE001
        return False
    return code == 0


def remove(path: str, runner: mdw.WslRunner = claude_hooks.run_wsl) -> bool:
    if not _safe(path):
        return False
    try:
        code, _out = runner(["-e", "sh", "-c", f'f="{path}"; rm -f "$f"'], timeout=IO_TIMEOUT_S)
    except Exception:  # noqa: BLE001
        return False
    return code == 0


class _Failed(Exception):
    """WSL 那边某一步没成；消息是给人看的原因。"""


def _read(path: str, runner) -> str:
    text = read_text(path, runner)
    if text is None:
        raise _Failed(t("distill.work.sink_read_failed", path=path))
    return text


def _write(path: str, text: str, runner) -> None:
    if not write_text(path, text, runner):
        raise _Failed(t("distill.work.sink_write_failed", path=path))


def apply_proposal(proposal, now: dt.datetime, *, entries: sink.EntriesStore,
                   runner: mdw.WslRunner = claude_hooks.run_wsl, backup_dir: Path | str | None = None) -> sink.Applied:
    """接受了的公司侧提案 → 公司侧条目库 → WSL 里的 CLAUDE.md 受管块 / 项目 memory 文件。

    WSL 那边任何一步没成：报原因、把条目库退回这次之前的样子（再接受一次不会多出重复条目）。已经写成的文件不回滚
    ——它们是从条目库渲染的，下次成功时会被整块重写。"""
    outcome = sink.Applied(side=md.SIDE_WORK)
    before = entries.load()
    entry, previous = entries.apply(proposal, now)
    if entry is None:
        outcome.error = t("distill.sink.no_previous", title=proposal.replaces or proposal.title)
        return outcome
    outcome.entry_id = entry.id
    all_entries = entries.load()
    try:
        if entry.scope == "global" or (previous is not None and previous.scope == "global"):
            original = _read(mdw.GLOBAL_CLAUDE_MD, runner)
            updated = sink.splice_block(original, sink.render_block(all_entries, now))
            if updated != original:
                if backup_dir is not None and original:
                    folder = Path(backup_dir)
                    folder.mkdir(parents=True, exist_ok=True)
                    backup = folder / f"{BACKUP_PREFIX}{now:%Y%m%d-%H%M%S}.bak"
                    if not backup.exists():           # 同一秒里的第二次改动：留着更早的那份
                        backup.write_bytes(original.encode("utf-8"))
                _write(mdw.GLOBAL_CLAUDE_MD, updated, runner)
                outcome.claude_md = True
        if entry.scope == "project":
            folder = mdw.project_memory_dir(entry.project)
            path = f"{folder}/{entry.file_name}"
            index_path = f"{folder}/{sink.INDEX_FILE}"
            index = _read(index_path, runner)
            if entry.retired:
                if not remove(path, runner):
                    raise _Failed(t("distill.work.sink_write_failed", path=path))
                outcome.removed = True
            else:
                _write(path, sink.render_memory_file(entry), runner)
            _write(index_path, sink.index_text(index, entry, remove=entry.retired), runner)
            outcome.project_file = path
    except (_Failed, OSError) as exc:
        entries.save(before)
        outcome.error = str(exc) or type(exc).__name__
        outcome.claude_md = False
    return outcome


__all__ = [name for name in dir() if not name.startswith("_")]
