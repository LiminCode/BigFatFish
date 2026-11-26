# -*- coding: utf-8 -*-
"""随手记的整理（零 Qt）：列收件、拼请求、收模型的输出、写盘、提交。

纪律：不调 Anthropic（``complete`` 用假函数）；最后两条用真 git（临时克隆 + 本机空仓库当远端），别的都不起 git。
样例文字中性，不放任何人的真实笔记。
"""
from __future__ import annotations

import base64
import datetime as dt
import subprocess
import threading
from pathlib import Path

import pytest

from pet import capture_inbox as ci
from pet import capture_organize as co
from pet import personal_vault as pv

NOW = dt.datetime(2026, 11, 25, 10, 30)
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
RULES = "# Rules\n\nFile name `9-Learning/Notes/YYYY-MM-DD <title>.md`; four sections.\n"

NOTE = """---
title: Habit stacking
tags: [reading, habits]
kind: post
source: https://example.com/post/42
captured: 2026-01-01 00:00
via: phone
review: {next: 2030-01-01, interval: 9, count: 9, lapses: 9}
---

## 原文存档
Stack a new habit on an old one.

![[assets/2026-11-24 0915 Habit stacking-1.png]]

## 要点
- Anchor to something you already do.

## 我的话
New habits ride on old ones.

## 关联
- [[7-Cognition/Example]] — same idea.
"""


class _Result:
    def __init__(self, text, *, model="claude-sonnet-5-5", tokens_in=1200, tokens_out=300, rounds=2):
        self.text, self.model, self.input_tokens, self.output_tokens, self.rounds = text, model, tokens_in, tokens_out, rounds


class _Provider:
    model, effort, api_key, base_url, api_format = "claude-sonnet-5-5", "medium", "k", "https://api.anthropic.com", "auto"


def _vault(tmp_path: Path, *, rules: bool = True) -> Path:
    root = tmp_path / "AI-Base"
    (root / ".git").mkdir(parents=True)
    (root / ci.INBOX_DIR).mkdir()
    (root / ci.INBOX_DIR / "README.md").write_text("# inbox readme\n", encoding="utf-8")
    if rules:
        (root / co.NOTES_DIR).mkdir(parents=True)
        (root / co.RULES_FILE).write_text(RULES, encoding="utf-8")
    return root


def _capture(root: Path, text: str = "Habit stacking\nhttps://example.com/post/42 stack a new habit on an old one.",
             images=(("png", PNG),), when=dt.datetime(2026, 11, 24, 9, 15)) -> list[str]:
    return ci.write_capture(root, text, [(f".{ext}", data) for ext, data in images], when, fallback="随手记")


# ───────────────────────── 设置 ─────────────────────────

REVIEW_DEFAULTS = {"review_enabled": True, "review_time": "09:00", "review_batch": 5, "review_random": True}


def test_settings_default_on_follow_chat_and_clamp_numbers():
    assert co.normalize(None) == {"enabled": True, "delay_minutes": 2, "max_per_run": 5, "model": "", "effort": "", "prompt": "",
                                  **REVIEW_DEFAULTS}
    clamped = co.normalize({"enabled": False, "delay_minutes": 999, "max_per_run": 0, "model": "bad model", "effort": "huge",
                            "prompt": "  mine {capture}  "})
    assert clamped == {"enabled": False, "delay_minutes": co.DELAY_RANGE[1], "max_per_run": co.BATCH_RANGE[0], "model": "",
                       "effort": "", "prompt": "mine {capture}", **REVIEW_DEFAULTS}
    assert co.normalize({"model": "claude-opus-5-5", "effort": "high"})["model"] == "claude-opus-5-5"
    review = co.normalize({"review_enabled": False, "review_time": "7:05", "review_batch": 99, "review_random": "yes"})
    assert (review["review_enabled"], review["review_time"], review["review_batch"], review["review_random"]) == (False, "07:05", 20, True)
    assert co.normalize({"review_time": "25:00"})["review_time"] == "09:00"
    assert co.normalize({"review_random": False})["review_random"] is False


# ───────────────────────── 收件 ─────────────────────────

def test_pending_lists_inbox_notes_oldest_first_and_skips_the_readme(tmp_path):
    root = _vault(tmp_path)
    second = _capture(root, "later thought", images=(), when=dt.datetime(2026, 11, 24, 21, 0))
    first = _capture(root)
    items = co.pending(root)
    assert [item.path for item in items] == [first[0], second[0]]
    item = items[0]
    assert (item.captured, item.via, item.source) == ("2026-11-24 09:15", "fish", "https://example.com/post/42")
    assert item.images == [first[1]]
    assert "Habit stacking" in item.text
    assert co.pending(tmp_path / "nowhere") == []


def test_the_request_carries_the_rules_the_capture_and_its_images(tmp_path):
    root = _vault(tmp_path)
    _capture(root)
    item = co.pending(root)[0]
    blocks = co.build_request(co.default_prompt_template(), co.read_rules(root), item, root, NOW)
    text = blocks[0]["text"]
    assert blocks[0]["type"] == "text"
    assert RULES.strip() in text and "Habit stacking" in text and item.path in text and "2026-11-25 10:30" in text
    assert "{rules}" not in text and "{capture}" not in text
    assert blocks[1] == {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                     "data": base64.b64encode(PNG).decode("ascii")}}
    custom = co.build_request("only {file}; keep {unknown} and {next: x}", "", item, root, NOW)
    assert custom[0]["text"] == f"only {item.path}; keep {{unknown}} and {{next: x}}"


def test_missing_rules_fall_back_to_the_builtin_summary(tmp_path):
    root = _vault(tmp_path, rules=False)
    assert co.read_rules(root) == co.FALLBACK_RULES
    assert "## 原文存档" in co.FALLBACK_RULES


# ───────────────────────── 收模型的输出 ─────────────────────────

def test_shape_fixes_the_fields_the_code_owns_names_the_file_and_moves_images(tmp_path):
    root = _vault(tmp_path)
    paths = _capture(root)
    item = co.pending(root)[0]
    shaped = co.shape("```markdown\n" + NOTE + "```\n", item, root, today=NOW.date())
    assert shaped.title == "Habit stacking"
    assert shaped.note == f"{co.NOTES_DIR}/2026-11-24 Habit stacking.md"
    image = f"{co.NOTES_DIR}/assets/2026-11-24 Habit stacking-1.png"
    assert shaped.moves == [(paths[1], image)]
    text = shaped.content
    assert text.startswith("---\ntitle: Habit stacking\n")
    assert "captured: 2026-11-24 09:15\n" in text and "via: fish\n" in text
    assert "review: {next: 2026-11-25, interval: 1, count: 0, lapses: 0}\n" in text
    assert "2030-01-01" not in text and "via: phone" not in text and "```" not in text
    assert "![[assets/2026-11-24 Habit stacking-1.png]]" in text and "0915" not in text
    assert f"<!-- by Claude, {NOW:%Y-%m-%d} -->" in text
    assert text.index("## 原文存档") < text.index("## 要点") < text.index("## 关联")


def test_shape_never_overwrites_and_adds_images_the_model_dropped(tmp_path):
    root = _vault(tmp_path)
    _capture(root)
    (root / co.NOTES_DIR / "2026-11-24 Habit stacking.md").write_text("older note\n", encoding="utf-8")
    item = co.pending(root)[0]
    dropped = NOTE.replace("![[assets/2026-11-24 0915 Habit stacking-1.png]]\n", "")
    shaped = co.shape(dropped, item, root, today=NOW.date())
    assert shaped.note == f"{co.NOTES_DIR}/2026-11-24 Habit stacking 2.md"
    assert "![[assets/2026-11-24 Habit stacking 2-1.png]]" in shaped.content
    assert shaped.content.index("Habit stacking 2-1.png") < shaped.content.index("## 要点")


def test_shape_takes_skip_and_refuses_output_without_a_title(tmp_path):
    root = _vault(tmp_path)
    _capture(root)
    item = co.pending(root)[0]
    with pytest.raises(co.Skip) as skipped:
        co.shape("SKIP: the screenshot is unreadable", item, root, today=NOW.date())
    assert skipped.value.reason == "the screenshot is unreadable"
    for bad in ("Here is your note:\n## 要点\n- x", "---\ntags: [x]\n---\n## 要点\n", "---\ntitle: \n---\nbody"):
        with pytest.raises(co.BadOutput):
            co.shape(bad, item, root, today=NOW.date())
    unsafe = co.shape(NOTE.replace("title: Habit stacking", 'title: "A/B: why? <yes>"'), item, root, today=NOW.date())
    assert unsafe.note == f"{co.NOTES_DIR}/2026-11-24 A B why yes.md"


def test_apply_writes_notes_moves_images_and_removes_the_inbox_files(tmp_path):
    root = _vault(tmp_path)
    paths = _capture(root)
    item = co.pending(root)[0]
    shaped = co.shape(NOTE, item, root, today=NOW.date())
    written, removed = co.apply(root, [shaped])
    assert written == [shaped.note, shaped.moves[0][1]]
    assert removed == [paths[0], paths[1]]
    assert (root / shaped.note).read_text(encoding="utf-8") == shaped.content
    assert (root / shaped.moves[0][1]).read_bytes() == PNG
    assert not (root / paths[0]).exists() and not (root / paths[1]).exists()
    assert co.pending(root) == []
    assert co.commit_message([shaped]) == f"Notes: Habit stacking\n\nfrom {paths[0]}"
    assert co.commit_message([shaped, shaped]).startswith("Notes: 2 captures\n\n")


# ───────────────────────── 一次运行 ─────────────────────────

class _Git:
    def __init__(self, *, pull_ok=True, sync_ok=True):
        self.calls: list[tuple] = []
        self.pull_ok, self.sync_ok = pull_ok, sync_ok

    def pull(self, repo_dir, *, token=""):
        self.calls.append(("pull", token))
        return (True, "") if self.pull_ok else (False, "fatal: unable to access")

    def sync(self, repo_dir, paths, message, *, token="", removed=()):
        self.calls.append(("sync", list(paths), list(removed), message))
        return (True, "") if self.sync_ok else (False, "remote: Permission denied")

    def head(self, repo_dir):
        return "0123456789ab"


def _run(root, git, complete, exclude=(), **settings):
    return co.run(root, co.normalize(settings), _Provider(), lock=threading.Lock(), token=lambda: "t0ken", now=NOW,
                  complete=complete, pull=git.pull, sync=git.sync, head=git.head, clock=iter(range(0, 100, 7)).__next__,
                  exclude=exclude)


def test_a_run_pulls_organizes_each_capture_and_pushes_one_commit(tmp_path):
    root = _vault(tmp_path)
    first = _capture(root)
    second = _capture(root, "a passing thought", images=(), when=dt.datetime(2026, 11, 24, 22, 0))
    asked = []

    def complete(prompt, system, provider, **kw):
        asked.append((prompt, kw))
        title = "Habit stacking" if len(asked) == 1 else "A passing thought"
        return _Result(NOTE.replace("title: Habit stacking", f"title: {title}"))

    git = _Git()
    result = _run(root, git, complete, model="claude-opus-5-5", effort="high")
    assert result.ok and result.state == "ok"
    assert (result.organized, result.skipped, result.failed, result.left) == (2, 0, 0, 0)
    assert result.notes == [f"{co.NOTES_DIR}/2026-11-24 Habit stacking.md", f"{co.NOTES_DIR}/2026-11-24 A passing thought.md"]
    assert (result.model, result.effort, result.tokens_in, result.tokens_out, result.turns) == ("claude-sonnet-5-5", "high", 2400, 600, 4)
    assert result.commit == "0123456789ab" and result.seconds == 7
    assert asked[0][1]["model"] == "claude-opus-5-5" and asked[0][1]["effort"] == "high"
    assert asked[0][1]["client_tools"].definitions          # 只读的 kb 工具：找关联用
    assert git.calls[0] == ("pull", "t0ken")
    op, written, removed, message = git.calls[1]
    assert op == "sync" and message.startswith("Notes: 2 captures")
    assert set(removed) == {first[0], first[1], second[0]}
    assert set(written) == {*result.notes, f"{co.NOTES_DIR}/assets/2026-11-24 Habit stacking-1.png"}


def test_an_empty_inbox_is_a_quiet_run_with_no_model_and_no_commit(tmp_path):
    root = _vault(tmp_path)
    git = _Git()
    result = _run(root, git, lambda *a, **k: pytest.fail("no model call"))
    assert result.ok and result.state == "noop" and result.organized == 0
    assert [call[0] for call in git.calls] == ["pull"]


def test_a_model_error_stops_the_run_and_leaves_the_inbox_alone(tmp_path):
    root = _vault(tmp_path)
    paths = _capture(root)
    _capture(root, "second", images=(), when=dt.datetime(2026, 11, 24, 23, 0))

    def complete(*_a, **_k):
        raise RuntimeError("认证失败：API Key 无效")

    git = _Git()
    result = _run(root, git, complete)
    assert not result.ok and result.state == "failed" and "API Key" in result.error
    assert (result.organized, result.failed, result.left) == (0, 1, 2)
    assert (root / paths[0]).exists() and [call[0] for call in git.calls] == ["pull"]


def test_skipped_and_unusable_outputs_stay_in_the_inbox_and_the_rest_goes_through(tmp_path):
    root = _vault(tmp_path)
    keep = _capture(root, "blurry", images=(), when=dt.datetime(2026, 11, 24, 8, 0))
    junk = _capture(root, "odd", images=(), when=dt.datetime(2026, 11, 24, 8, 30))
    good = _capture(root)
    replies = iter(["SKIP: unreadable", "no frontmatter at all", NOTE])
    git = _Git()
    result = _run(root, git, lambda *a, **k: _Result(next(replies)), max_per_run=5)
    assert result.ok and result.state == "ok"
    assert (result.organized, result.skipped, result.failed, result.left) == (1, 1, 1, 2)
    assert (root / keep[0]).exists() and (root / junk[0]).exists() and not (root / good[0]).exists()
    assert git.calls[-1][3].startswith("Notes: Habit stacking")
    assert result.held == [(keep[0], "unreadable"), (junk[0], "模型回的不是一条笔记")], "留在收件箱的每一条都说得出为什么"


def test_a_run_where_everything_was_held_back_waits_for_the_user(tmp_path):
    root = _vault(tmp_path)
    paths = _capture(root)
    git = _Git()
    result = _run(root, git, lambda *a, **k: _Result("SKIP: the screenshot is unreadable"))
    assert result.ok and result.state == "needs_you" and result.held == [(paths[0], "the screenshot is unreadable")]
    assert [call[0] for call in git.calls] == ["pull"], "什么都没整理：不提交"


def test_held_captures_are_not_retried_until_the_file_changes(tmp_path):
    root, config_dir = _vault(tmp_path), tmp_path / "cfg"
    held = _capture(root, "blurry", images=())[0]
    other = _capture(root, "fine", images=(), when=dt.datetime(2026, 11, 24, 10, 0))[0]
    assert co.unchanged_held(config_dir, root) == set()
    co.remember_held(config_dir, root, [(held, "unreadable")], NOW)
    assert co.unchanged_held(config_dir, root) == {held}
    assert co.load_held(config_dir)[held]["reason"] == "unreadable"
    asked = []
    _run(root, _Git(), lambda prompt, *a, **k: asked.append(prompt[0]["text"]) or _Result("SKIP: x"), exclude={held})
    assert len(asked) == 1 and other in asked[0] and held not in asked[0], "认得的那条不再拿去问模型"
    (root / held).write_text((root / held).read_text(encoding="utf-8") + "\nnow it says more\n", encoding="utf-8")
    assert co.unchanged_held(config_dir, root) == set(), "改过了：下一轮重试"
    (root / held).unlink()
    co.remember_held(config_dir, root, [], NOW)
    assert co.load_held(config_dir) == {}, "收件箱里没有了的就忘掉"


def test_a_run_takes_at_most_max_per_run_and_counts_the_rest(tmp_path):
    root = _vault(tmp_path)
    for minute in range(3):
        _capture(root, f"thought {minute}", images=(), when=dt.datetime(2026, 11, 24, 9, minute))
    calls = []
    result = _run(root, _Git(), lambda *a, **k: calls.append(1) or _Result(NOTE.replace("Habit stacking", f"T{len(calls)}")),
                  max_per_run=2)
    assert (result.organized, result.left) == (2, 1) and len(calls) == 2


def test_a_push_failure_keeps_the_notes_and_reports_it(tmp_path):
    root = _vault(tmp_path)
    _capture(root)
    result = _run(root, _Git(sync_ok=False), lambda *a, **k: _Result(NOTE))
    assert not result.ok and result.state == "failed" and "Permission denied" in result.error
    assert result.organized == 1 and (root / result.notes[0]).exists() and result.commit == ""


def test_a_provider_that_is_not_claude_fails_before_reading_anything(tmp_path):
    root = _vault(tmp_path)
    _capture(root)

    class Other(_Provider):
        base_url, api_format = "https://example.invalid/v1", "openai"

    git = _Git()
    result = co.run(root, co.normalize({}), Other(), lock=threading.Lock(), token=lambda: "", now=NOW,
                    complete=lambda *a, **k: pytest.fail("no call"), pull=git.pull, sync=git.sync, head=git.head)
    assert not result.ok and result.state == "failed" and git.calls == []


# ───────────────────────── 真 git ─────────────────────────

def _git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def real_clone(tmp_path):
    if not pv.git_exe():
        pytest.skip("git is not installed")
    bare, clone = tmp_path / "remote.git", tmp_path / "AI-Base"
    _git("init", "-q", "--bare", "-b", "main", str(bare))
    _git("clone", "-q", str(bare), str(clone))
    _git("config", "user.email", "demo@example.invalid", cwd=clone)
    _git("config", "user.name", "Demo", cwd=clone)
    (clone / co.NOTES_DIR).mkdir(parents=True)
    (clone / co.RULES_FILE).write_text(RULES, encoding="utf-8")
    _git("add", "-A", cwd=clone)
    _git("commit", "-q", "-m", "init", cwd=clone)
    _git("push", "-q", "-u", "origin", "main", cwd=clone)
    return bare, clone


def test_sync_path_stages_removals_and_ignores_paths_git_never_knew(real_clone):
    bare, clone = real_clone
    paths = _capture(clone)
    assert pv.sync_path(clone, paths, "capture: x")[0]
    for path in paths:
        (clone / path).unlink()
    (clone / "new.md").write_text("new\n", encoding="utf-8")
    ok, out = pv.sync_path(clone, ["new.md"], "Notes: x", removed=[*paths, "0-Inbox/never-tracked.md"])
    assert ok, out
    files = _git("--git-dir", str(bare), "show", "--name-status", "--format=", "main")
    assert "A\tnew.md" in files and all(f"D\t{path}" in files for path in paths)
    assert _git("status", "--porcelain", cwd=clone) == ""


def test_a_real_run_lands_one_commit_on_the_remote(real_clone):
    bare, clone = real_clone
    paths = _capture(clone)
    assert pv.sync_path(clone, paths, ci.commit_message(NOW))[0]
    result = co.run(clone, co.normalize({}), _Provider(), lock=threading.Lock(), token=lambda: "", now=NOW,
                    complete=lambda *a, **k: _Result(NOTE))
    assert result.ok, result.error
    assert result.commit == _git("--git-dir", str(bare), "rev-parse", "main").strip()[:12]
    subject = _git("--git-dir", str(bare), "log", "-1", "--format=%s", "main").strip()
    assert subject == "Notes: Habit stacking"
    tree = _git("--git-dir", str(bare), "ls-tree", "-r", "--name-only", "main")
    assert f"{co.NOTES_DIR}/2026-11-24 Habit stacking.md" in tree and paths[0] not in tree
    assert _git("status", "--porcelain", cwd=clone) == ""
