# -*- coding: utf-8 -*-
"""会话记忆蒸馏·第二期——落盘：条目库、CLAUDE.md 受管块、项目 memory 目录、知识库镜像、一条提案落到所有地方。

全在 tmp 目录里；git 用假 runner。
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from pet import memory_distill_run as run
from pet import memory_distill_sink as sink
from pet import personal_vault as pv

NOW = dt.datetime(2026, 10, 31, 21, 40)
PET = r"C:\Users\me\Github\Pet"


def _proposal(title: str, *, action: str = "add", scope: str = "global", project: str = "", replaces: str = "",
              why: str = "因为", how: str = "这样用", evidence=("2026-10-30 Pet：原话",), kind: str = "feedback") -> run.Proposal:
    return run.Proposal(id=run.proposal_id(action, scope, project, title), action=action, scope=scope, project=project,
                        type=kind, title=title, why=why, how=how, evidence=list(evidence), replaces=replaces)


# ---------------------------------------------------------------- 条目库


def test_entries_add_change_retire(tmp_path):
    store = sink.EntriesStore(tmp_path)
    entry, previous = store.apply(_proposal("回复用中文"), NOW)
    assert previous is None and entry.title == "回复用中文" and entry.accepted_at.startswith("2026-10-31T21:40")
    changed, old = store.apply(_proposal("回复用中文，术语保留英文", action="change", replaces="回复用中文", why="", evidence=("新证据",)), NOW)
    assert old.id == entry.id and changed.id == entry.id, "change 保留原 id"
    assert changed.title == "回复用中文，术语保留英文" and changed.why == "因为", "没给 why 就留旧的"
    assert changed.evidence == ["2026-10-30 Pet：原话", "新证据"] and len(changed.history) == 2
    assert len(store.active()) == 1
    orphan, _ = store.apply(_proposal("新标题", action="change", replaces="不存在"), NOW)
    assert orphan.id != entry.id and len(store.active()) == 2, "change 找不到旧条目就当 add"
    retired, _ = store.apply(_proposal("回复用中文，术语保留英文", action="retire"), NOW)
    assert retired.retired and retired.retired_at and len(store.active()) == 1
    assert store.apply(_proposal("没有的", action="retire"), NOW) == (None, None)
    assert store.find("新标题", "global", "") is not None and store.find("新标题", "project", PET) is None


# ---------------------------------------------------------------- CLAUDE.md 受管块


def test_claude_md_block_is_spliced_in_place_and_the_rest_is_untouched(tmp_path):
    path = tmp_path / "CLAUDE.md"
    original = "## 我自己写的\n- 保持原样\n"
    path.write_text(original, encoding="utf-8")
    store = sink.EntriesStore(tmp_path)
    store.apply(_proposal("回复用中文"), NOW)
    store.apply(_proposal("项目里的", scope="project", project=PET), NOW)
    assert sink.write_claude_md(path, store.load(), backup_dir=tmp_path / "bak", now=NOW)
    text = path.read_text(encoding="utf-8")
    assert text.startswith(original + "\n" + sink.BLOCK_START)
    assert "- **回复用中文** — 这样用（因为；依据：2026-10-30 Pet：原话）" in text
    assert "项目里的" not in text, "项目条目不进全局块"
    assert text.rstrip().endswith(sink.BLOCK_END)
    assert list((tmp_path / "bak").glob("CLAUDE.md.*.bak"))[0].read_text(encoding="utf-8") == original
    assert not sink.write_claude_md(path, store.load(), backup_dir=tmp_path / "bak", now=NOW), "没变不写"
    store.apply(_proposal("回复用中文", action="retire"), NOW)
    assert sink.write_claude_md(path, store.load(), now=NOW)
    text2 = path.read_text(encoding="utf-8")
    assert text2.startswith(original + "\n" + sink.BLOCK_START) and "回复用中文" not in text2
    assert text2.count(sink.BLOCK_START) == 1 and text2.count(sink.BLOCK_END) == 1
    assert sink.splice_block("", "B") == "B\n" and sink.splice_block("x\n" + sink.BLOCK_START + "old" + sink.BLOCK_END + "\ny\n", "B") == "x\nB\ny\n"


# ---------------------------------------------------------------- 项目 memory 目录


def test_project_entry_file_and_index_line(tmp_path):
    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "MEMORY.md").write_text("- [旧的](old.md) — 手写的\n", encoding="utf-8")
    store = sink.EntriesStore(tmp_path)
    entry, _ = store.apply(_proposal("原始候选库放本地", scope="project", project=PET, kind="project"), NOW)
    path = sink.write_project_entry(memory, entry)
    assert path.name == f"distill-{entry.id}.md"
    text = path.read_text(encoding="utf-8")
    assert text.startswith(f"---\nname: distill-{entry.id}\ndescription: 这样用\nmetadata:\n  type: project\n")
    assert "原始候选库放本地\n\n**Why:** 因为\n\n**How to apply:** 这样用\n\n依据（原话）：\n- 2026-10-30 Pet：原话" in text
    index = (memory / "MEMORY.md").read_text(encoding="utf-8")
    assert index == f"- [旧的](old.md) — 手写的\n- [原始候选库放本地](distill-{entry.id}.md) — 这样用\n"
    sink.write_project_entry(memory, entry)
    assert (memory / "MEMORY.md").read_text(encoding="utf-8").count("distill-") == 1, "重写不重复索引"
    assert sink.remove_project_entry(memory, entry) and not path.exists()
    assert (memory / "MEMORY.md").read_text(encoding="utf-8") == "- [旧的](old.md) — 手写的\n"
    assert not sink.remove_project_entry(memory, entry)


# ---------------------------------------------------------------- 知识库镜像


def test_vault_note_is_regenerated_from_entries_and_synced(tmp_path):
    store = sink.EntriesStore(tmp_path)
    store.apply(_proposal("回复用中文"), NOW)
    store.apply(_proposal("候选库放本地", scope="project", project=PET), NOW)
    gone, _ = store.apply(_proposal("老规矩"), NOW)
    store.apply(_proposal("老规矩", action="retire"), NOW)
    vault = tmp_path / "vault"
    path = sink.write_vault_note(vault, store.load(), NOW)
    assert path == vault / "User" / "Claude Memory.md"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\nupdated: 2026-10-31 21:40\n")
    assert "## 全局\n\n- **回复用中文** — 这样用" in text and f"## 项目 `{PET}`\n\n- **候选库放本地**" in text
    assert "## 已作废\n\n- ~~老规矩~~（2026-10-31）" in text
    calls: list[list[str]] = []

    def git(repo_dir, args, **_kw):
        calls.append(args)
        return (1, "") if args[:3] == ["diff", "--cached", "--quiet"] else (0, "")

    ok, reason = sink.sync_vault(vault, NOW, run_git=git, token="tok")
    assert ok and reason == ""
    assert calls[0] == ["add", "--", "User/Claude Memory.md"] and calls[2][:3] == ["commit", "-q", "-m"]
    assert calls[2][3] == "claude memory: 2026-10-31 21:40" and calls[-1] == ["push", "-q"]
    assert pv.sync_inspiration(vault, NOW, run=git, token="") == (True, ""), "灵感记录还走同一条路"


# ---------------------------------------------------------------- 一条提案落到所有地方


def test_apply_proposal_writes_every_target(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "CLAUDE.md").write_text("mine\n", encoding="utf-8")
    projects = home / ".claude" / "projects"
    (projects / "c--Users-me-Github-Pet" / "memory").mkdir(parents=True)
    vault = tmp_path / "vault"
    vault.mkdir()
    entries = sink.EntriesStore(tmp_path / "store")
    kwargs = dict(entries=entries, home=home, backup_dir=tmp_path / "store" / "backups", vault_dir=vault)

    done = sink.apply_proposal(_proposal("回复用中文"), NOW, **kwargs)
    assert done.claude_md and done.project_file == "" and done.vault_written and done.error == ""
    assert sink.BLOCK_START in (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    assert (vault / "User" / "Claude Memory.md").exists()

    done = sink.apply_proposal(_proposal("候选库放本地", scope="project", project=PET + r"\.claude\worktrees\w1"), NOW, **kwargs)
    assert Path(done.project_file).parent == projects / "c--Users-me-Github-Pet" / "memory", "worktree 归主仓库，目录大小写不敏感"
    assert Path(done.project_file).exists() and not done.claude_md

    done = sink.apply_proposal(_proposal("候选库放本地", action="retire", scope="project", project=PET), NOW, **kwargs)
    assert done.removed and not Path(done.project_file).exists()
    missing = sink.apply_proposal(_proposal("没这条", action="retire"), NOW, **kwargs)
    assert missing.error.startswith("没找到") and missing.entry_id == ""

    quiet = sink.apply_proposal(_proposal("不镜像"), NOW, **{**kwargs, "mirror": False})
    assert quiet.claude_md and not quiet.vault_written
