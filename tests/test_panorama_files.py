# -*- coding: utf-8 -*-
"""配置全景的文件查看（只读）：页面只能读存储表里点了名、又在查看白名单里的文件，别的一概读不到。

读真的文件（临时目录）；接口那一半走真实的本机服务。
"""
from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import pytest

from pet import data_stores as ds
from pet import i18n
from pet.memory_distill_sink import BLOCK_END, BLOCK_START
from pet.panorama import files, routes, sources
from pet.panorama import server as srv
from pet.panorama.feed import Feed
from tests import panorama_samples as samples

SECRET = "sk-test-not-a-real-key-0123456789abcd"


def _write(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))                               # 不让平台把换行改掉：字节数和行号要对得上
    return path


@pytest.fixture
def reader(tmp_path):
    """一个假的数据目录和一个假的 Claude Code 家目录，里面该看的、不该看的都有。"""
    data, home = tmp_path / "data", tmp_path / "home"
    claude = home / ".claude"
    _write(data / "memory-distill" / "entries.json", '{"entries": [{"title": "规矩一"}]}')
    _write(data / "config.json", json.dumps({"chat": {"api_key": SECRET}}))
    _write(data / "sessions" / "a.json", "chat")
    _write(claude / "CLAUDE.md", f"# mine\nline two\n{BLOCK_START}\n- **one** a\n{BLOCK_END}\ntail\n")
    _write(claude / "projects" / "C--work-tomato" / "memory" / "MEMORY.md", "- index\n")
    _write(claude / "projects" / "C--work-tomato" / "memory" / "note.md", "remember this\n")
    _write(claude / "projects" / "C--work-potato" / "memory" / "MEMORY.md", "- other\n")
    _write(claude / "projects" / "C--work-tomato" / "0f0f.jsonl", "TRANSCRIPT")
    _write(claude / "settings.json", json.dumps({"env": {"TOKEN": SECRET}}))
    _write(claude / ".credentials.json", json.dumps({"token": SECRET}))
    _write(home / ".claude.json", json.dumps({"mcpServers": {"x": {"env": {"TOKEN": SECRET}}}}))
    _write(home / "outside.md", "OUTSIDE")
    return files.Reader(config_dir=data, home=home)


# ───────────────────────── 白名单 ─────────────────────────

def test_only_listed_content_stores_on_surveyed_roots_can_be_viewed():
    by_id = {store.id: store for store in ds.STORES}
    assert set(files.VIEWABLE) <= set(by_id)
    for store_id in files.VIEWABLE:
        assert by_id[store_id].kind == "content", store_id          # 设置文件里可能夹着密钥，不在这一步放开
        assert by_id[store_id].root in files.ROOTS, store_id        # WSL 里的要经 wsl.exe 读，这一步还没做
    for store in ds.STORES:
        if store.kind in ("secret", "login"):
            assert not files.viewable(store.id), store.id
    assert files.viewable("claude_md") and files.viewable("claude_memory") and files.viewable("distill_entries")
    assert not files.viewable("claude_md_wsl") and not files.viewable("no-such-store")


@pytest.mark.parametrize("store_id", ["config", "claude_settings", "claude_login", "claude_json", "api_keys", "chat_sessions",
                                      "claude_transcripts", "claude_md_wsl", "nope", ""])
def test_a_store_outside_the_whitelist_cannot_be_listed_or_read(reader, store_id):
    for call in (lambda: reader.listing(store_id), lambda: reader.read(store_id, "config.json")):
        with pytest.raises(files.FileError) as caught:
            call()
        assert caught.value.code == "not_viewable"


# ───────────────────────── 列出 ─────────────────────────

def test_listing_names_exactly_the_files_of_that_store(reader):
    out = reader.listing("claude_memory")
    assert [f["path"] for f in out["files"]] == [
        "projects/C--work-potato/memory/MEMORY.md", "projects/C--work-tomato/memory/MEMORY.md", "projects/C--work-tomato/memory/note.md"]
    assert out["files"][0]["bytes"] == 8 and len(out["files"][0]["mtime"]) == 16 and out["truncated"] is False
    assert [f["label"] for f in out["files"]] == ["C--work-potato / MEMORY.md", "C--work-tomato / MEMORY.md", "C--work-tomato / note.md"]
    assert reader.listing("claude_md")["files"][0]["label"] == "CLAUDE.md"
    assert [f["path"] for f in reader.listing("claude_md")["files"]] == ["CLAUDE.md"]
    assert [f["path"] for f in reader.listing("distill_entries")["files"]] == ["memory-distill/entries.json"]
    assert reader.listing("distill_entries_work")["files"] == []                  # 这台机器上没有：空清单，不是错


def test_listing_is_capped_and_says_so(reader, tmp_path):
    for i in range(files.LIST_LIMIT + 3):
        _write(tmp_path / "home" / ".claude" / "projects" / "p" / "memory" / f"n{i:04}.md")
    out = reader.listing("claude_memory")
    assert len(out["files"]) == files.LIST_LIMIT and out["truncated"] is True


# ───────────────────────── 读 ─────────────────────────

def test_read_returns_the_text_and_marks_the_managed_block(reader):
    out = reader.read("claude_md", "CLAUDE.md")
    assert out["text"].startswith("# mine\nline two\n") and out["path"] == "CLAUDE.md" and out["truncated"] is False
    assert out["marks"] == [{"from": 3, "to": 5, "kind": "managed"}]              # 第 3–5 行（从 1 数）是蒸馏写的受管块
    assert reader.read("claude_memory", "projects/C--work-tomato/memory/note.md")["marks"] == []
    assert "规矩一" in reader.read("distill_entries", "memory-distill/entries.json")["text"]


@pytest.mark.parametrize("path", [
    "../outside.md", "..\\outside.md", "projects/../../outside.md", "projects/C--work-tomato/memory/../../../settings.json",
    "/etc/passwd", "C:/Windows/win.ini", "C:\\Windows\\win.ini", "\\\\server\\share\\x.md", "projects//memory/note.md",
    "./CLAUDE.md", "", "CLAUDE.md\x00.md", "projects/C--work-tomato/memory/",
])
def test_a_path_that_is_not_a_plain_relative_path_is_refused(reader, path):
    with pytest.raises(files.FileError) as caught:
        reader.read("claude_memory", path)
    assert caught.value.code == "bad_path"


@pytest.mark.parametrize("store_id, path", [
    ("claude_memory", "settings.json"),                                  # 同一个根下别的存储的文件
    ("claude_memory", ".credentials.json"),
    ("claude_memory", "projects/C--work-tomato/0f0f.jsonl"),             # 同一个项目目录下的会话原文
    ("claude_memory", "CLAUDE.md"),                                      # 能看，但不属于这一项
    ("claude_md", "projects/C--work-tomato/memory/note.md"),
    ("distill_entries", "config.json"),
    ("distill_entries", "sessions/a.json"),
])
def test_a_path_that_belongs_to_another_store_is_refused(reader, store_id, path):
    with pytest.raises(files.FileError) as caught:
        reader.read(store_id, path)
    assert caught.value.code == "bad_path"


def test_a_file_that_does_not_exist_is_not_found(reader):
    with pytest.raises(files.FileError) as caught:
        reader.read("claude_memory", "projects/C--work-tomato/memory/gone.md")
    assert caught.value.code == "not_found"


def test_a_link_that_points_outside_the_root_is_refused(reader, tmp_path):
    link = tmp_path / "home" / ".claude" / "projects" / "C--work-tomato" / "memory" / "escape.md"
    try:
        os.symlink(tmp_path / "home" / "outside.md", link)
    except (OSError, NotImplementedError):
        pytest.skip("this account cannot create symlinks")
    with pytest.raises(files.FileError) as caught:
        reader.read("claude_memory", "projects/C--work-tomato/memory/escape.md")
    assert caught.value.code == "bad_path"
    assert "projects/C--work-tomato/memory/escape.md" not in [f["path"] for f in reader.listing("claude_memory")["files"]]


@pytest.mark.skipif(sys.platform != "win32", reason="directory junctions are a Windows thing")
def test_a_directory_junction_that_leads_outside_the_root_is_refused(reader, tmp_path):
    """目录联接不要特权就能建：项目目录里放一个指到外面的 ``memory``，路径看着合规，真身却在根外面。"""
    outside = tmp_path / "elsewhere"
    _write(outside / "stolen.md", "OUTSIDE")
    junction = tmp_path / "home" / ".claude" / "projects" / "C--sneaky" / "memory"
    junction.parent.mkdir(parents=True)
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(outside)], capture_output=True)
    if made.returncode != 0:
        pytest.skip("cannot create a junction here")
    with pytest.raises(files.FileError) as caught:
        reader.read("claude_memory", "projects/C--sneaky/memory/stolen.md")
    assert caught.value.code == "bad_path"
    assert not any("sneaky" in f["path"] for f in reader.listing("claude_memory")["files"])


def test_a_large_file_is_cut_at_the_cap_and_says_so(reader, tmp_path):
    _write(tmp_path / "home" / ".claude" / "projects" / "p" / "memory" / "big.md", "é" * files.MAX_BYTES)
    out = reader.read("claude_memory", "projects/p/memory/big.md")
    assert out["truncated"] is True and out["bytes"] == 2 * files.MAX_BYTES
    assert len(out["text"].encode("utf-8")) <= files.MAX_BYTES + 3


def test_bytes_that_are_not_text_do_not_break_the_reader(reader, tmp_path):
    path = tmp_path / "home" / ".claude" / "projects" / "p" / "memory" / "odd.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"ok \xff\xfe still ok")
    assert "still ok" in reader.read("claude_memory", "projects/p/memory/odd.md")["text"]


# ───────────────────────── 接口：走真实的本机服务 ─────────────────────────

@pytest.fixture
def served(reader):
    feed = Feed()
    instance = srv.PanoramaServer(routes.build_router(feed, files=reader, wait_seconds=0.05), poll_seconds=0.02)
    instance.start()
    yield instance
    feed.close()
    instance.stop()


def _get(instance, path, *, token=True):
    headers = {"Host": f"127.0.0.1:{instance.port}"}
    if token:
        headers[srv.TOKEN_HEADER] = instance.token
    connection = http.client.HTTPConnection("127.0.0.1", instance.port, timeout=15.0)
    try:
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        body = response.read()
        return response.status, (json.loads(body) if body else None)
    finally:
        connection.close()


def test_file_api_lists_and_reads_through_the_service(served):
    status, listing = _get(served, "/api/files?store=claude_memory")
    assert status == 200 and len(listing["files"]) == 3 and listing["store"] == "claude_memory"
    path = quote("projects/C--work-tomato/memory/note.md", safe="")
    status, body = _get(served, f"/api/file?store=claude_memory&path={path}")
    assert status == 200 and body["text"] == "remember this\n"


def test_file_api_needs_the_token(served):
    assert _get(served, "/api/files?store=claude_memory", token=False)[0] == 401
    assert _get(served, "/api/file?store=claude_md&path=CLAUDE.md", token=False)[0] == 401


@pytest.mark.parametrize("query, status, code", [
    ("store=claude_settings&path=settings.json", 404, "not_viewable"),
    ("store=claude_login&path=.credentials.json", 404, "not_viewable"),
    ("store=claude_memory&path=..%2F..%2F.claude.json", 400, "bad_path"),
    ("store=claude_memory&path=settings.json", 400, "bad_path"),
    ("store=claude_memory&path=projects%2Fp%2Fmemory%2Fgone.md", 404, "not_found"),
    ("store=claude_memory", 400, "bad_path"),
    ("path=CLAUDE.md", 404, "not_viewable"),
])
def test_file_api_refuses_what_the_reader_refuses_and_never_leaks(served, query, status, code):
    got, body = _get(served, f"/api/file?{query}")
    assert got == status and body["error"] == code
    assert SECRET not in json.dumps(body) and "OUTSIDE" not in json.dumps(body)


def test_without_a_reader_the_file_api_does_not_exist():
    feed = Feed()
    instance = srv.PanoramaServer(routes.build_router(feed), poll_seconds=0.02)
    instance.start()
    try:
        assert _get(instance, "/api/files?store=claude_md")[0] == 404
    finally:
        feed.close()
        instance.stop()


# ───────────────────────── 图：哪些地方给「查看」 ─────────────────────────

def test_the_graph_offers_viewing_only_where_there_is_something_viewable_on_this_machine():
    i18n.set_language("zh")
    graph = sources.build(samples.facts())
    nodes = {n["id"]: n for n in graph["nodes"]}
    assert nodes["md_win"]["view"] == "claude_md" and nodes["mem_win"]["view"] == "claude_memory"
    offered = {i["id"]: i.get("view") for n in graph["nodes"] for i in n.get("items", []) if "id" in i}
    assert offered["distill_entries"] == "distill_entries" and offered["claude_md"] == "claude_md"
    assert offered["distill_entries_work"] is None                       # 这台机器上没有这个文件
    assert offered["claude_md_wsl"] is None and "view" not in nodes["md_wsl"]         # WSL 一侧这一步还读不了
    assert offered["config"] is None and offered["claude_settings"] is None and offered["api_keys"] is None
    assert {v for v in offered.values() if v} <= set(files.VIEWABLE)
