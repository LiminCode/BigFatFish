# -*- coding: utf-8 -*-
"""会话记忆蒸馏·第二期——落盘：接受了的提案写到以后的 Claude 一定会读的地方，并镜像进知识库。

三个落点（用户 2026-10-30 拍板）：

1. **全局**：``~/.claude/CLAUDE.md`` 里一个**受管区块**（起止注释标记）。机器只改块内，块外一个字不动；
   每次改之前把整个文件备份到候选库目录下的 ``backups/``。
2. **项目**：那个项目的 ``~/.claude/projects/<编码>/memory/`` 目录——一条一个文件（``distill-<id>.md``，
   和我手写的记忆同一种 frontmatter），``MEMORY.md`` 加一行索引。worktree 的会话归主仓库。
3. **镜像**：个人知识库 AI-Base 里的 ``User/Claude Memory.md``，整篇由条目库重新生成，commit + push。

条目库 ``entries.json`` 是唯一真相：CLAUDE.md 的块和知识库里的那篇都是从它渲染出来的，所以 change / retire
能真的改掉旧内容，而不是往后追加。
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from . import memory_distill_run as run
from . import personal_vault as pv

ENTRIES_FILE = "entries.json"
BACKUP_DIR = "backups"
BLOCK_START = "<!-- big-fat-fish:memory-distill:start -->"
BLOCK_END = "<!-- big-fat-fish:memory-distill:end -->"
VAULT_NOTE = "User/Claude Memory.md"
INDEX_FILE = "MEMORY.md"
FILE_PREFIX = "distill-"
MAX_DESCRIPTION = 120
_INDEX_LINE_RE = re.compile(r"^- \[[^\]]*\]\((distill-[0-9a-f]+)\.md\).*$", re.MULTILINE)


@dataclass
class Entry:
    id: str
    scope: str
    project: str
    type: str
    title: str
    why: str = ""
    how: str = ""
    evidence: list[str] = field(default_factory=list)
    accepted_at: str = ""
    updated_at: str = ""
    retired: bool = False
    retired_at: str = ""
    history: list[str] = field(default_factory=list)      # 改过它的提案 id

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Entry":
        known = {f.name for f in dataclasses.fields(cls)}
        clean = {k: v for k, v in (data or {}).items() if k in known}
        for name in ("id", "scope", "project", "type", "title"):
            clean.setdefault(name, "")
        if not isinstance(clean.get("evidence"), list):
            clean["evidence"] = []
        if not isinstance(clean.get("history"), list):
            clean["history"] = []
        return cls(**clean)

    @property
    def file_name(self) -> str:
        return f"{FILE_PREFIX}{self.id}.md"

    @property
    def description(self) -> str:
        text = " ".join((self.how or self.why or self.title).split())
        return text if len(text) <= MAX_DESCRIPTION else text[:MAX_DESCRIPTION - 1] + "…"


class EntriesStore:
    """``<root>/entries.json``：接受了的条目（含作废的，留历史）。"""

    def __init__(self, root: Path | str) -> None:
        self.path = Path(root) / ENTRIES_FILE

    def load(self) -> list[Entry]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        items = data.get("items") if isinstance(data, dict) else data
        return [Entry.from_dict(i) for i in items if isinstance(i, dict)] if isinstance(items, list) else []

    def save(self, items: Iterable[Entry]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"items": [e.to_dict() for e in items]}, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def active(self, scope: str | None = None, project: str | None = None) -> list[Entry]:
        items = [e for e in self.load() if not e.retired]
        if scope is not None:
            items = [e for e in items if e.scope == scope]
        if project is not None:
            items = [e for e in items if e.project.lower() == project.lower()]
        return items

    def find(self, title: str, scope: str, project: str) -> Entry | None:
        """按标题找（同作用域、同项目；大小写与空白不敏感）；change / retire 用。"""
        wanted = " ".join(str(title or "").split()).lower()
        if not wanted:
            return None
        for entry in self.active(scope, run.repo_root(project) if scope == "project" else ""):
            if " ".join(entry.title.split()).lower() == wanted:
                return entry
        return None

    def apply(self, proposal: run.Proposal, now: dt.datetime) -> tuple[Entry | None, Entry | None]:
        """把一条接受了的提案并进条目库。返回 (现在这条, 之前那条或 None)；retire 找不到旧条目时返回 (None, None)。"""
        stamp = now.isoformat(timespec="seconds")
        items = self.load()
        previous = self.find(proposal.replaces or proposal.title, proposal.scope, proposal.project)
        if proposal.action == "retire":
            if previous is None:
                return None, None
            for index, entry in enumerate(items):
                if entry.id == previous.id:
                    items[index] = dataclasses.replace(entry, retired=True, retired_at=stamp,
                                                       history=[*entry.history, proposal.id])
                    self.save(items)
                    return items[index], previous
            return None, None
        if proposal.action == "change" and previous is not None:
            for index, entry in enumerate(items):
                if entry.id == previous.id:
                    items[index] = dataclasses.replace(
                        entry, title=proposal.title, why=proposal.why or entry.why, how=proposal.how or entry.how,
                        type=proposal.type or entry.type, evidence=[*entry.evidence, *proposal.evidence][-6:],
                        updated_at=stamp, history=[*entry.history, proposal.id])
                    self.save(items)
                    return items[index], previous
        entry = Entry(id=proposal.id, scope=proposal.scope, project=run.repo_root(proposal.project), type=proposal.type,
                      title=proposal.title, why=proposal.why, how=proposal.how, evidence=list(proposal.evidence),
                      accepted_at=stamp, updated_at=stamp, history=[proposal.id])
        items.append(entry)
        self.save(items)
        return entry, None


# ---------------------------------------------------------------- 全局 CLAUDE.md 受管块


def render_block(entries: Iterable[Entry], now: dt.datetime | None = None) -> str:
    """受管块全文（含起止标记）。没有条目也留着空块，这样下次知道往哪写。"""
    lines = [BLOCK_START,
             "## 会话里定下的规矩（大肥鱼「会话记忆蒸馏」维护，每条经本人审核；要改请在肥鱼里改，别直接编辑这一段）"]
    for entry in entries:
        if entry.retired or entry.scope != "global":
            continue
        line = f"- **{entry.title}**"
        if entry.how:
            line += f" — {entry.how}"
        tail = []
        if entry.why:
            tail.append(entry.why)
        if entry.evidence:
            tail.append(f"依据：{entry.evidence[0]}")
        if tail:
            line += f"（{'；'.join(tail)}）"
        lines.append(line)
    if now is not None:
        lines.append(f"<!-- 更新：{now:%Y-%m-%d %H:%M} -->")
    lines.append(BLOCK_END)
    return "\n".join(lines)


def splice_block(original: str, block: str) -> str:
    """把受管块放进 CLAUDE.md：已有就原位替换，没有就追加到末尾（空一行）。块外一个字不动。"""
    start, end = original.find(BLOCK_START), original.find(BLOCK_END)
    if start >= 0 and end > start:
        return original[:start] + block + original[end + len(BLOCK_END):]
    body = original.rstrip("\n")
    return (body + "\n\n" if body else "") + block + "\n"


def write_claude_md(path: Path | str, entries: Iterable[Entry], *, backup_dir: Path | str | None = None,
                    now: dt.datetime | None = None) -> bool:
    """改之前整文件备份到 ``backup_dir``；内容没变就不写。返回写没写。"""
    path = Path(path)
    now = now or dt.datetime.now()
    try:
        original = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        original = ""
    updated = splice_block(original, render_block(entries, now))
    if updated == original:
        return False
    if backup_dir is not None and original:
        folder = Path(backup_dir)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"CLAUDE.md.{now:%Y%m%d-%H%M%S}.bak").write_text(original, encoding="utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(updated, encoding="utf-8", newline="\n")
    os.replace(tmp, path)
    return True


# ---------------------------------------------------------------- 项目 memory 目录


def render_memory_file(entry: Entry) -> str:
    """和我手写的记忆同一种样子：frontmatter（name / description / metadata.type）+ 正文 + Why + How。"""
    body = [f"---\nname: {entry.file_name[:-3]}\ndescription: {entry.description}\nmetadata:\n  type: {entry.type or 'feedback'}\n"
            f"  source: big-fat-fish memory-distill\n---\n", entry.title, ""]
    if entry.why:
        body += [f"**Why:** {entry.why}", ""]
    if entry.how:
        body += [f"**How to apply:** {entry.how}", ""]
    if entry.evidence:
        body += ["依据（原话）：", *[f"- {e}" for e in entry.evidence], ""]
    if entry.updated_at:
        body.append(f"（{entry.updated_at[:10]} 由会话记忆蒸馏写入，经本人审核）")
    return "\n".join(body).rstrip() + "\n"


def write_project_entry(memory_dir: Path | str, entry: Entry) -> Path:
    """写（或重写）``distill-<id>.md``，并在 MEMORY.md 里放一行索引（已有就替换那行）。"""
    folder = Path(memory_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / entry.file_name
    path.write_text(render_memory_file(entry), encoding="utf-8", newline="\n")
    _update_index(folder, entry, remove=False)
    return path


def remove_project_entry(memory_dir: Path | str, entry: Entry) -> bool:
    folder = Path(memory_dir)
    path = folder / entry.file_name
    existed = path.exists()
    if existed:
        path.unlink()
    _update_index(folder, entry, remove=True)
    return existed


def _update_index(folder: Path, entry: Entry, *, remove: bool) -> None:
    index = folder / INDEX_FILE
    try:
        text = index.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    stem = entry.file_name[:-3]
    lines = [line for line in text.splitlines() if not (_INDEX_LINE_RE.match(line) and f"({stem}.md)" in line)]
    if not remove:
        lines.append(f"- [{entry.title}]({entry.file_name}) — {entry.description}")
    index.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8", newline="\n")


# ---------------------------------------------------------------- 知识库镜像


def render_vault_note(entries: Iterable[Entry], now: dt.datetime) -> str:
    """AI-Base 里那篇：全局一节、每个项目一节；作废的单列在最后。整篇重新生成。"""
    items = list(entries)
    lines = ["---", "updated: " + now.strftime("%Y-%m-%d %H:%M"), "source: 大肥鱼 · 会话记忆蒸馏", "---", "",
             "# Claude Memory", "",
             "我在 Claude Code 里说过的话，经大肥鱼每日蒸馏、我逐条审核后留下的记忆条目。",
             "同一份内容写在 `~/.claude/CLAUDE.md` 的受管块（全局）和各项目的 memory 目录（项目）里，这篇是镜像，供回看与检索。", ""]
    lines += ["## 全局", ""]
    lines += [_note_line(e) for e in items if not e.retired and e.scope == "global"] or ["（还没有）"]
    projects = sorted({e.project for e in items if not e.retired and e.scope == "project"}, key=str.lower)
    for project in projects:
        lines += ["", f"## 项目 `{project}`", ""]
        lines += [_note_line(e) for e in items if not e.retired and e.scope == "project" and e.project == project]
    retired = [e for e in items if e.retired]
    if retired:
        lines += ["", "## 已作废", ""]
        lines += [f"- ~~{e.title}~~（{e.retired_at[:10]}）" for e in retired]
    return "\n".join(lines).rstrip() + "\n"


def _note_line(entry: Entry) -> str:
    line = f"- **{entry.title}**"
    if entry.how:
        line += f" — {entry.how}"
    if entry.why:
        line += f"  \n  为什么：{entry.why}"
    if entry.evidence:
        line += f"  \n  依据：{entry.evidence[0]}"
    line += f"  \n  （{(entry.updated_at or entry.accepted_at)[:10]}）"
    return line


def write_vault_note(repo_dir: Path | str, entries: Iterable[Entry], now: dt.datetime) -> Path:
    path = Path(repo_dir) / VAULT_NOTE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_vault_note(entries, now), encoding="utf-8", newline="\n")
    return path


def sync_vault(repo_dir: Path | str, now: dt.datetime, *, run_git: pv.GitRunner = pv.run_git, token: str = "") -> tuple[bool, str]:
    """add → 有变化才 commit → pull --rebase → push（和灵感记录同一条路）。阻塞，放线程里。"""
    return pv.sync_path(repo_dir, VAULT_NOTE, f"claude memory: {now:%Y-%m-%d %H:%M}", run=run_git, token=token)


# ---------------------------------------------------------------- 一条提案落到所有地方


@dataclass
class Applied:
    entry_id: str = ""
    claude_md: bool = False           # 全局块改了
    project_file: str = ""            # 写 / 删的项目 memory 文件
    removed: bool = False
    vault_written: bool = False
    error: str = ""

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


def apply_proposal(proposal: run.Proposal, now: dt.datetime, *, entries: EntriesStore, home: Path | None = None,
                   projects_root: Path | None = None, claude_md: Path | None = None, backup_dir: Path | None = None,
                   vault_dir: str | Path = "", mirror: bool = True,
                   project_dir_for: Callable[[str], Path] | None = None) -> Applied:
    """接受了的提案 → 条目库 → CLAUDE.md 受管块 / 项目 memory 文件 → 知识库那篇（只写文件；推送另起线程）。"""
    home = home or Path.home()
    projects_root = projects_root or (home / ".claude" / "projects")
    claude_md = claude_md or (home / ".claude" / "CLAUDE.md")
    outcome = Applied()
    entry, previous = entries.apply(proposal, now)
    if entry is None:
        outcome.error = "没找到要作废 / 修改的条目：" + (proposal.replaces or proposal.title)
        return outcome
    outcome.entry_id = entry.id
    all_entries = entries.load()
    try:
        if entry.scope == "global" or (previous is not None and previous.scope == "global"):
            outcome.claude_md = write_claude_md(claude_md, all_entries, backup_dir=backup_dir, now=now)
        if entry.scope == "project":
            folder = (project_dir_for or (lambda cwd: run.project_dir(cwd, projects_root)))(entry.project) / "memory"
            if entry.retired:
                outcome.removed = remove_project_entry(folder, entry)
                outcome.project_file = str(folder / entry.file_name)
            else:
                outcome.project_file = str(write_project_entry(folder, entry))
        if mirror and vault_dir and Path(vault_dir).is_dir():
            write_vault_note(vault_dir, all_entries, now)
            outcome.vault_written = True
    except OSError as exc:
        outcome.error = f"{type(exc).__name__}: {exc}"
    return outcome
