# -*- coding: utf-8 -*-
"""配置全景：WSL 一侧补齐——那边的存储按文件数出来，那边的文件也能在页面上打开看。

WSL 本身在测试里没有：喂给 ``wsl.exe`` 的那段源码，这里用本机的 Python 在一个假的家目录上原样跑一遍
（同一段文本、同样从标准输入进），所以测到的就是真会送过去的东西。
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from pet import data_stores as ds
from pet import i18n
from pet.panorama import claude_home_probe, files, probes, sources, store_walk, wsl_file_agent
from tests import panorama_samples as samples

SECRET = "sk-test-not-a-real-key-0123456789abcd"


@pytest.fixture(autouse=True)
def _chinese():
    i18n.set_language("zh")
    yield
    i18n.set_language("zh")


def _write(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def _fake_wsl(home: Path):
    """假的 ``run_wsl``：把收到的源码交给本机 Python 跑，家目录指到 ``home``。记下每次调用。"""
    calls = []

    def run(args, *, input_text=None, timeout=30.0):
        calls.append({"args": args, "source": input_text})
        env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        done = subprocess.run([sys.executable, *args[2:]], input=(input_text or "").encode("utf-8"), capture_output=True, env=env, timeout=60)
        return done.returncode, done.stdout.decode("utf-8", "replace")

    run.calls = calls
    return run


@pytest.fixture
def wsl_home(tmp_path):
    home = tmp_path / "wslhome"
    claude = home / ".claude"
    _write(claude / "CLAUDE.md", "# team\nrule\n")
    _write(claude / "settings.json", json.dumps({"env": {"TOKEN": SECRET}}))
    _write(claude / ".credentials.json", json.dumps({"token": SECRET}))
    _write(claude / "projects" / "-home-dev-carrot" / "memory" / "MEMORY.md", "- index\n")
    _write(claude / "projects" / "-home-dev-carrot" / "memory" / "notes.md", "remember carrots\n")
    _write(claude / "projects" / "-home-dev-carrot" / "0f0f.jsonl", "TRANSCRIPT")
    _write(claude / "skills" / "deploy" / "SKILL.md", "how to deploy\n")
    _write(claude / "odd-new-thing.bin", "?")
    _write(home / ".claude.json", json.dumps({"mcpServers": {}}))
    _write(home / "outside.md", "OUTSIDE")
    return home


# ───────────────────────── 喂给 WSL 的那一份源码 ─────────────────────────

def test_the_piped_source_is_the_registry_the_walker_and_the_probe_in_one_file():
    source = probes.wsl_source()
    compile(source, "<wsl>", "exec")                                     # 拼出来的东西语法上是一个合法的文件
    assert source.count("from __future__ import annotations") == 1 and source.startswith("from __future__")
    for needle in ("STORES: tuple[Store, ...]", "def survey_tree(", "def probe(home"):
        assert needle in source


def test_the_three_modules_do_not_define_the_same_top_level_name():
    """拼在一起就落在同一个作用域里：两个模块各有一个同名的函数或常量，后一个会悄悄顶掉前一个。"""
    seen: dict[str, str] = {}
    for module in (ds, store_walk, claude_home_probe):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        for node in tree.body:
            names = [node.name] if isinstance(node, (ast.FunctionDef, ast.ClassDef)) else \
                [t.id for t in getattr(node, "targets", []) if isinstance(t, ast.Name)] if isinstance(node, ast.Assign) else []
            for name in names:
                assert name not in seen, f"{name} is defined in both {seen[name]} and {module.__name__}"
                seen[name] = module.__name__


def test_the_walker_only_uses_the_standard_library():
    for module in (store_walk, wsl_file_agent):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        assert all(isinstance(node, ast.ImportFrom) is False or node.level == 0 for node in ast.walk(tree))
        assert imported <= set(sys.stdlib_module_names) | {"__future__"}, (module.__name__, sorted(imported))


def test_the_probe_run_the_way_wsl_runs_it_also_surveys_the_storage(wsl_home):
    out = probes.wsl_side(_fake_wsl(wsl_home), with_mcp=False)
    storage = out["storage"]
    assert storage["path"].endswith(".claude") and storage["exists"] is True and storage["truncated"] is False
    assert {k: v["files"] for k, v in storage["stores"].items()} == {
        "claude_md_wsl": 1, "claude_settings_wsl": 1, "claude_login_wsl": 1, "claude_memory_wsl": 2,
        "claude_transcripts_wsl": 1, "claude_skills_wsl": 1}
    assert storage["unknown"] == ["odd-new-thing.bin"] and storage["unknown_count"] == 1
    assert out["memory_index"]["projects"][0]["name"] == "-home-dev-carrot"                # 原来那一半照旧
    dumped = json.dumps(out)
    assert SECRET not in dumped and "TRANSCRIPT" not in dumped and "OUTSIDE" not in dumped


def test_the_walk_on_this_side_is_the_same_code(tmp_path):
    _write(tmp_path / "config.json")
    _write(tmp_path / "mystery.bin")
    walked = store_walk.survey_tree("data", str(tmp_path), ds.match)
    assert walked["stores"]["config"]["files"] == 1 and walked["unknown"] == ["mystery.bin"]


# ───────────────────────── 图：WSL 一侧也有数了 ─────────────────────────

def test_wsl_stores_show_how_much_is_there_once_the_wsl_half_brought_a_survey():
    graph = sources.build(samples.facts())
    local = next(n for n in graph["nodes"] if n["id"] == "st_cc_wsl_local")
    rows = {i["id"]: i for i in local["items"]}
    assert rows["claude_md_wsl"]["detail"] == "1 个文件 · 300 B · 2026-01-02 03:04" and rows["claude_md_wsl"]["state"] == "warn"
    assert rows["claude_skills_wsl"]["state"] == "off" and rows["claude_skills_wsl"]["detail"] == "这台机器上没有"
    assert not any(label == "说明" and value for label, value in local["facts"])              # 不再说「这一侧没核对」
    assert "3 种" in local["sub"]


def test_unknown_files_on_the_wsl_side_get_their_tile_too():
    wsl = samples.wsl_home()
    wsl["storage"].update(unknown=["odd.bin"], unknown_count=1)
    graph = sources.build(samples.facts(wsl=wsl))
    tile = next(n for n in graph["nodes"] if n["id"] == "st_cc_wsl_unknown")
    assert [i["name"] for i in tile["items"]] == ["odd.bin"] and tile["region"] == "wsl"


def test_wsl_files_are_offered_for_viewing_where_the_survey_found_them():
    graph = sources.build(samples.facts())
    nodes = {n["id"]: n for n in graph["nodes"]}
    assert nodes["md_wsl"]["view"] == "claude_md_wsl" and nodes["mem_wsl"]["view"] == "claude_memory_wsl"
    assert nodes["set_wsl"]["view"] == "claude_settings_wsl"
    wsl_side = next(s for s in graph["memory"]["sides"] if s["id"] == "wsl")
    assert wsl_side["projects"][0]["entries"][0]["view"] == {"store": "claude_memory_wsl", "path": "projects/-home-dev-carrot/memory/notes.md"}
    assert wsl_side["rules"][0]["view"] == {"store": "claude_md_wsl", "path": "CLAUDE.md"}


def test_an_older_wsl_result_without_a_survey_is_listed_from_the_registry_alone():
    wsl = samples.wsl_home()
    wsl.pop("storage")
    graph = sources.build(samples.facts(wsl=wsl))
    nodes = {n["id"]: n for n in graph["nodes"]}
    assert all(i["detail"] == "" for i in nodes["st_cc_wsl_local"]["items"])
    assert "view" not in nodes["md_wsl"] and "view" not in nodes["mem_wsl"]
    assert "view" not in next(s for s in graph["memory"]["sides"] if s["id"] == "wsl")["projects"][0]["entries"][0]


# ───────────────────────── 读 WSL 里的文件 ─────────────────────────

@pytest.fixture
def reader(wsl_home, tmp_path):
    run = _fake_wsl(wsl_home)
    return files.Reader(config_dir=tmp_path / "data", home=tmp_path / "winhome", run_wsl=run), run


def test_wsl_stores_can_be_listed_and_read_through_the_runner(reader):
    read, run = reader
    listing = read.listing("claude_memory_wsl")
    assert [(f["path"], f["label"]) for f in listing["files"]] == [
        ("projects/-home-dev-carrot/memory/MEMORY.md", "-home-dev-carrot / MEMORY.md"),
        ("projects/-home-dev-carrot/memory/notes.md", "-home-dev-carrot / notes.md")]
    assert listing["files"][1]["bytes"] == 17 and len(listing["files"][1]["mtime"]) == 16
    out = read.read("claude_memory_wsl", "projects/-home-dev-carrot/memory/notes.md")
    assert out["text"] == "remember carrots\n" and out["binary"] is False and out["truncated"] is False and out["marks"] == []
    assert read.read("claude_md_wsl", "CLAUDE.md")["text"] == "# team\nrule\n"
    assert SECRET in read.read("claude_settings_wsl", "settings.json")["text"]              # 原样给，和这台机器上的一样
    assert [f["path"] for f in read.listing("claude_skills_wsl")["files"]] == ["skills/deploy/SKILL.md"]
    assert all(call["args"][:3] == ["-e", "python3", "-"] for call in run.calls)


@pytest.mark.parametrize("store_id, path, code", [
    ("claude_memory_wsl", "../../outside.md", "bad_path"),
    ("claude_memory_wsl", "projects/-home-dev-carrot/0f0f.jsonl", "bad_path"),             # 同一个项目目录下的会话原文
    ("claude_memory_wsl", "settings.json", "bad_path"),
    ("claude_settings_wsl", ".credentials.json", "bad_path"),
    ("claude_md_wsl", "/etc/passwd", "bad_path"),
    ("claude_login_wsl", ".credentials.json", "not_viewable"),
    ("claude_transcripts_wsl", "projects/-home-dev-carrot/0f0f.jsonl", "not_viewable"),
])
def test_a_refused_wsl_path_never_reaches_wsl(reader, store_id, path, code):
    """路径这边先查一遍：不合规的根本不会起 ``wsl.exe``。"""
    read, run = reader
    with pytest.raises(files.FileError) as caught:
        read.read(store_id, path)
    assert caught.value.code == code and run.calls == []


def test_a_wsl_file_that_is_missing_or_points_outside_is_refused_on_that_side(reader, wsl_home):
    read, run = reader
    with pytest.raises(files.FileError) as caught:
        read.read("claude_memory_wsl", "projects/-home-dev-carrot/memory/gone.md")
    assert caught.value.code == "not_found" and len(run.calls) == 1
    link = wsl_home / ".claude" / "projects" / "-home-dev-sneaky" / "memory"
    link.parent.mkdir(parents=True)
    if sys.platform == "win32":
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(wsl_home)], capture_output=True).returncode == 0
    else:
        os.symlink(wsl_home, link)
        made = True
    if not made:
        pytest.skip("cannot create a link here")
    with pytest.raises(files.FileError) as caught:
        read.read("claude_memory_wsl", "projects/-home-dev-sneaky/memory/outside.md")
    assert caught.value.code == "bad_path"
    assert not any("sneaky" in f["path"] for f in read.listing("claude_memory_wsl")["files"])


@pytest.mark.skipif(sys.platform != "win32", reason="uses a directory junction")
def test_a_link_inside_the_wsl_home_cannot_pass_one_file_off_as_another(reader, wsl_home):
    """根里面的一个链接指回根自己：``projects/x/memory/CLAUDE.md`` 看着是项目记忆，真身是全局规矩。
    还在根里面，但不是这条路径本来该在的地方——不给。"""
    read, _run = reader
    alias = wsl_home / ".claude" / "projects" / "-home-dev-alias" / "memory"
    alias.parent.mkdir(parents=True)
    if subprocess.run(["cmd", "/c", "mklink", "/J", str(alias), str(wsl_home / ".claude")], capture_output=True).returncode != 0:
        pytest.skip("cannot create a junction here")
    with pytest.raises(files.FileError) as caught:
        read.read("claude_memory_wsl", "projects/-home-dev-alias/memory/CLAUDE.md")
    assert caught.value.code == "bad_path"
    assert not any("alias" in f["path"] for f in read.listing("claude_memory_wsl")["files"])


def test_without_a_runner_or_when_wsl_does_not_answer_the_wsl_stores_are_unavailable(tmp_path):
    plain = files.Reader(config_dir=tmp_path, home=tmp_path)
    with pytest.raises(files.FileError) as caught:
        plain.read("claude_md_wsl", "CLAUDE.md")
    assert caught.value.code == "not_viewable"
    for answer in ((127, ""), (1, ""), (0, "python3: not found"), (0, "{not json")):
        broken = files.Reader(config_dir=tmp_path, home=tmp_path, run_wsl=lambda *a, answer=answer, **k: answer)
        for call in (lambda: broken.read("claude_md_wsl", "CLAUDE.md"), lambda: broken.listing("claude_md_wsl")):
            with pytest.raises(files.FileError) as caught:
                call()
            assert caught.value.code == "unavailable"


def test_the_agent_marks_the_managed_block_and_reports_binary_and_large_files(reader, wsl_home):
    from pet.memory_distill_sink import BLOCK_END, BLOCK_START

    read, _run = reader
    _write(wsl_home / ".claude" / "CLAUDE.md", f"mine\n{BLOCK_START}\n- **r** x\n{BLOCK_END}\n")
    assert read.read("claude_md_wsl", "CLAUDE.md")["marks"] == [{"from": 2, "to": 4, "kind": "managed"}]
    (wsl_home / ".claude" / "skills" / "deploy" / "logo.png").write_bytes(b"\x89PNG\x00\x00" + bytes(range(200)))
    assert read.read("claude_skills_wsl", "skills/deploy/logo.png")["binary"] is True
    _write(wsl_home / ".claude" / "skills" / "deploy" / "big.md", "y" * (files.MAX_BYTES + 10))
    big = read.read("claude_skills_wsl", "skills/deploy/big.md")
    assert big["truncated"] is True and len(big["text"]) == files.MAX_BYTES and big["bytes"] == files.MAX_BYTES + 10


def test_text_that_is_not_ascii_survives_the_trip(reader, wsl_home):
    read, _run = reader
    _write(wsl_home / ".claude" / "projects" / "-home-dev-carrot" / "memory" / "中文.md", "规矩：回答用中文 ✔\n")
    assert "projects/-home-dev-carrot/memory/中文.md" in [f["path"] for f in read.listing("claude_memory_wsl")["files"]]
    assert read.read("claude_memory_wsl", "projects/-home-dev-carrot/memory/中文.md")["text"] == "规矩：回答用中文 ✔\n"


def test_the_request_is_embedded_as_a_literal_not_passed_on_a_command_line(reader):
    """请求（含路径）写进源码里的一个字符串字面量，不经过 ``wsl.exe`` 的命令行：空格、引号、中文都不用操心转义。"""
    read, run = reader
    with pytest.raises(files.FileError):
        read.read("claude_memory_wsl", "projects/a b'c\"d/memory/x.md")
    assert run.calls[0]["args"] == ["-e", "python3", "-"]
    assert re.search(r"\nagent_main\('.*'\)\n$", run.calls[0]["source"], re.S) or 'agent_main("' in run.calls[0]["source"]
