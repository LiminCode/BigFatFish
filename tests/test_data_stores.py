# -*- coding: utf-8 -*-
"""存储表（ADR 0015）：每种落盘数据登记一次，并且答得出「丢了从哪恢复」。

三类守卫：
1. 表自己站得住——标识唯一、取值合法、恢复来源和数据种类对得上；
2. 源码里出现的每个「像数据文件」的文件名，要么属于表里的一项，要么在 ``NOT_STORES`` 里写明它是什么；
3. 真机数据目录里见过的名字都认得出来（名字是通用的，不含任何个人内容）。
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

from pet import data_stores as ds
from pet import i18n

PET = Path(ds.__file__).resolve().parent
#: 只盯这几种扩展名：数据文件基本都是它们。`.done` / `.txt` 之类和文案键、提示词撞得太多，不盯。
_FILENAME = re.compile(r"^[A-Za-z0-9_.{}\-]+\.(?:json|jsonl|log|lock|pending|db|md)$")


def test_table_is_internally_consistent():
    ds.validate()
    ids = [store.id for store in ds.STORES]
    assert len(ids) == len(set(ids)) and all(re.fullmatch(r"[a-z][a-z0-9_]*", i) for i in ids)
    for store in ds.STORES:
        assert store.zone in ds.ZONES and store.root in ds.ROOTS and store.kind in ds.KINDS, store.id
        assert store.restore.source in ds.RESTORE_SOURCES, store.id
        assert store.patterns and store.writers, store.id


def test_validate_rejects_the_mistakes_it_exists_to_catch():
    good = ds.STORES[0]

    def broken(**changes):
        with pytest.raises(ValueError):
            ds.validate((ds.Store(**{**good.__dict__, **changes}),))

    broken(kind="nonsense")
    broken(root="nowhere")
    broken(zone="neither")
    broken(patterns=())
    broken(restore=ds.Restore("uncovered"))                               # 没覆盖却不说打算哪一步补
    broken(writers=())
    broken(writers=("用户",))                                              # 写的人是标识，不是给人看的话
    broken(restore=ds.Restore("git", via="config_backup"))                # 说进了仓库却不说哪个仓库
    broken(restore=ds.Restore("git", repo="kb_personal"))                 # 也不说靠哪个机制
    broken(kind="content", restore=ds.Restore("disposable"))              # 人或 AI 写的东西不能「丢了无所谓」
    broken(kind="settings", restore=ds.Restore("rebuild"))                # 设置重算不出来
    broken(kind="secret", restore=ds.Restore("git", repo="kb_personal", via="x"))   # 密钥只有一种恢复来源
    broken(kind="cache", restore=ds.Restore("secret"))
    with pytest.raises(ValueError):
        ds.validate((good, good))                                         # 标识重复


def test_content_and_settings_are_either_backed_up_or_listed_as_a_gap():
    """ADR 0015 的核心：人写的、AI 写的、用户设的，不许悄悄只存在本机。"""
    for store in ds.STORES:
        if store.kind in ("content", "settings"):
            assert store.restore.source in ("git", "uncovered"), store.id
    for store in ds.gaps():
        assert store.restore.plan, store.id


def test_standing_says_what_happens_to_each_store_if_the_disk_dies():
    by_id = {store.id: ds.standing(store) for store in ds.STORES}
    assert set(by_id.values()) == set(ds.STANDINGS)
    assert by_id["config"] == "kept" and by_id["kb_personal_repo"] == "kept"
    assert by_id["distill_entries"] == "local" and by_id["claude_md_wsl"] == "local"
    assert by_id["logs"] == "free" and by_id["claude_login"] == "free" and by_id["voice_cache"] == "free"
    # 密钥：定了做法（加密后进私有仓库）却还没做，所以现在算只在本机；做完把 plan 去掉就算留住了
    assert by_id["api_keys"] == "local"
    done = ds.Store("k", "personal", "keyring", ("x",), "secret", ("chat.models",), ds.Restore("secret"))
    assert ds.standing(done) == "kept"
    assert {store.id for store in ds.gaps()} == {i for i, s in by_id.items() if s == "local"}


@pytest.mark.parametrize("language", ["zh", "en"])
def test_every_store_and_root_is_described_in_both_languages(language):
    """表里只有标识；每一项叫什么、里面是什么、为什么是这个恢复来源，在字表里，两种语言都得有。"""
    table = i18n.table(language)
    missing = [f"stores.{ds.text_key(store)}.{part}" for store in ds.STORES for part in ("name", "holds", "why")
               if not str(table.get(f"stores.{ds.text_key(store)}.{part}") or "").strip()]
    missing += [f"stores.root.{root}" for root in ds.ROOTS if not str(table.get(f"stores.root.{root}") or "").strip()]
    assert missing == []
    described = {key.split(".")[1] for key in table if key.startswith("stores.") and not key.startswith("stores.root.")}
    assert described == {ds.text_key(store) for store in ds.STORES}, "字表里有表里已经没有的存储，删掉"


def test_every_filename_literal_in_the_code_is_accounted_for():
    """代码里新出现一个 ``"something.json"``，就得回答它是哪一项存储，或者写明它不是我们的数据。"""
    unknown = {}
    for path in sorted(PET.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            for literal in _literals(node):
                if _FILENAME.match(literal) and not ds.accounts_for(literal):
                    unknown.setdefault(literal, path.relative_to(PET).as_posix())
    assert not unknown, (
        "这些文件名既不在 pet/data_stores.py 的 STORES 里，也不在 NOT_STORES 里。"
        "新增了落盘数据就登记一项（并回答丢了从哪恢复）；不是我们的数据就加进 NOT_STORES 并写一句它是什么：\n"
        + "\n".join(f"  {name}    （{where}）" for name, where in sorted(unknown.items())))


def _literals(node) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):                                   # f"config-{slot}.json" → "config-{}.json"
        return ["".join(part.value if isinstance(part, ast.Constant) else "{}" for part in node.values)]
    return []


def test_not_stores_entries_are_all_still_in_the_code_and_explained():
    """``NOT_STORES`` 不能变成垃圾场：每一条都得还在代码里出现，并且有说明。"""
    source = "\n".join(path.read_text(encoding="utf-8") for path in PET.rglob("*.py") if path.name != "data_stores.py")
    for name, why in ds.NOT_STORES.items():
        assert why.strip(), name
        assert name.replace("{}", "") in source or name.split("{}")[0] in source, f"{name} 已经不在代码里了，从 NOT_STORES 删掉"


@pytest.mark.parametrize("name, expected", [
    ("config.json", "config"), ("config.json.bak", "config_local_copies"), ("config.json.corrupt-1700000000000-4242", "config_local_copies"),
    ("config.json.before-restore", "config_local_copies"), ("config-slot-2.json", "config_slots"),
    ("pet-12345.log", "logs"), ("pet-overlay-gate.log", "logs"), ("pet-runtime-v2-12345-slot-0.json", "runtime_markers"),
    ("overlay-instance.lock", "runtime_markers"), ("settings.lock", "runtime_markers"),
    ("memory-distill/entries.json", "distill_entries"), ("memory-distill/entries-work.json", "distill_entries_work"),
    ("memory-distill/proposals.json", "distill_proposals"), ("memory-distill/candidates/2026-01-02.jsonl", "distill_candidates"),
    ("sessions/abc123.json", "chat_sessions"), ("message-log.json", "message_log"),
    ("knowledge-base/current/notes/a.md", "knowledge_base_copy"), ("voice_chime_cache/ab/cd.mp3", "voice_cache"),
    ("panorama/panorama.html", "panorama_snapshot"),
])
def test_names_seen_in_a_real_data_directory_are_recognised(name, expected):
    store = ds.match("data", name)
    assert store is not None and store.id == expected, f"{name} → {store.id if store else None}"


@pytest.mark.parametrize("name, expected", [
    ("settings.json", "claude_settings"), ("CLAUDE.md", "claude_md"), (".credentials.json", "claude_login"),
    ("projects/C--work-thing/memory/MEMORY.md", "claude_memory"), ("projects/C--work-thing/memory/some-note.md", "claude_memory"),
    ("projects/C--work-thing/0f0f0f0f-aaaa.jsonl", "claude_transcripts"),
    ("projects/C--work-thing/0f0f0f0f-aaaa/tool-results/shot.jpg", "claude_transcripts"),
    ("projects/C--work-thing/0f0f0f0f-aaaa/subagents/agent.json", "claude_transcripts"),
    ("skills/my-skill/SKILL.md", "claude_skills"), ("plugins/installed_plugins.json", "claude_plugins"),
    ("file-history/abc/1", "claude_scratch"), ("settings.json.before-statusline-removal-2026-10-10", "claude_scratch"),
])
def test_names_seen_in_a_real_claude_home_are_recognised(name, expected):
    """记忆文件和会话原文在同一个项目目录下：记忆要认成记忆（该留），其余认成会话原文（有意不留）。"""
    assert ds.match("claude_home", name).id == expected
    assert ds.match("claude_home_wsl", name).id == expected + "_wsl"


def test_unregistered_lists_what_the_table_does_not_know():
    names = ["config.json", "pet-1.log", "brand-new-feature.json", "mystery/thing.bin"]
    assert ds.unregistered("data", names) == ["brand-new-feature.json", "mystery/thing.bin"]


def test_a_more_specific_pattern_wins_over_a_directory_wide_one():
    assert ds.match("data", "memory-distill/entries.json").id == "distill_entries"
    assert ds.match("data", "memory-distill/some-future-file.json").id == "distill_state"       # 目录里其余的归簿记


def test_module_does_not_import_qt_or_anything_outside_the_standard_library():
    tree = ast.parse(Path(ds.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "存储表不依赖包里别的模块"
            imported.add((node.module or "").split(".")[0])
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}, sorted(imported)
