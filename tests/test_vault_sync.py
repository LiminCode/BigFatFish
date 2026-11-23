# -*- coding: utf-8 -*-
"""知识库同步器（``pet/vault_sync.py``）：一次同步 = 预检 → 提交本地改动 → fetch → rebase → 推送，每次记一行运行记录。

git 是真的：临时目录里一个裸仓库当远端，``mine`` 是肥鱼看护的克隆，``cloud`` 是另一个往远端写的人（云端的会话）。
只有「连不上远端」这种没法确定地造出来的情况才换假的 git。
"""
from __future__ import annotations

import ast
import datetime as dt
import subprocess
from pathlib import Path

import pytest

from pet import personal_vault as pv
from pet import run_journal
from pet import vault_sync as vs

NOW = dt.datetime(2026, 11, 22, 16, 5)


def _git(folder: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, f"git {' '.join(args)}: {done.stdout}{done.stderr}"
    return done.stdout.strip()


def _write(folder: Path, name: str, text: str) -> None:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _commit_and_push(folder: Path, name: str, text: str, message: str = "from the cloud") -> None:
    _write(folder, name, text)
    _git(folder, "add", "-A")
    _git(folder, "commit", "-q", "-m", message)
    _git(folder, "push", "-q")


class _World:
    def __init__(self, root: Path) -> None:
        self.remote, self.mine, self.cloud = root / "remote.git", root / "mine", root / "cloud"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.remote)], check=True)
        subprocess.run(["git", "clone", "-q", str(self.remote), str(self.cloud)], check=True, capture_output=True)
        _write(self.cloud, "INDEX.md", "# index\n")
        _write(self.cloud, "Notes/a.md", "line one\nline two\nline three\n")
        _git(self.cloud, "add", "-A")
        _git(self.cloud, "commit", "-q", "-m", "first")
        _git(self.cloud, "push", "-q", "-u", "origin", "main")
        subprocess.run(["git", "clone", "-q", str(self.remote), str(self.mine)], check=True, capture_output=True)
        self.journal = run_journal.Journal(root / "journal")
        self.sync = vs.VaultSync(journal=self.journal, token=lambda: "", now=lambda: NOW)

    def run(self, **options) -> vs.Outcome:
        return self.sync.sync(self.mine, **options)

    def remote_log(self) -> list[str]:
        return _git(self.remote, "log", "--format=%s", "main").splitlines()

    def last_row(self) -> dict:
        return self.journal.read(1)[0]


@pytest.fixture
def world(tmp_path, monkeypatch) -> _World:
    empty = tmp_path / "gitconfig"
    empty.write_text("", encoding="utf-8")
    for key, value in {"GIT_CONFIG_GLOBAL": str(empty), "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "Dev", "GIT_AUTHOR_EMAIL": "dev@home.example",
                       "GIT_COMMITTER_NAME": "Dev", "GIT_COMMITTER_EMAIL": "dev@home.example"}.items():
        monkeypatch.setenv(key, value)
    return _World(tmp_path)


# ───────────────────────── 一次同步 ─────────────────────────

def test_a_hand_edit_and_a_new_note_are_committed_and_pushed(world):
    _write(world.mine, "Notes/a.md", "line one\nline two changed\nline three\n")
    _write(world.mine, "Notes/new note.md", "fresh\n")
    out = world.run()
    assert (out.state, out.files, out.deletions, out.pulled, out.pushed) == ("synced", 2, 0, 0, 1)
    assert world.remote_log() == ["vault: 2026-11-22 16:05 · 2 files", "first"], "提交说明只有时间和文件数，没有文件名"
    state = pv.upstream_state(world.mine)
    assert _git(world.mine, "status", "--porcelain") == "" and (state["behind"], state["ahead"]) == (0, 0)
    row = world.last_row()
    assert (row["job"], row["trigger"], row["result"]) == ("vault_sync", "manual", "ok")
    effect, = row["effects"]
    assert effect["kind"] == "git" and effect["op"] == "sync" and effect["repo"] == "personal"
    assert effect["files"] == 2 and effect["pushed"] == 1 and effect["pulled"] == 0 and effect["committed"] == [out.committed]
    assert effect["before"] != effect["after"] and len(effect["after"]) == 12
    assert "new note" not in str(row) and "Notes" not in str(row), "运行记录里没有文件名"
    assert [step["name"] for step in row["steps"]] == ["commit", "fetch", "push"]


def test_remote_commits_are_pulled_in_without_touching_anything_else(world):
    _commit_and_push(world.cloud, "Notes/b.md", "written elsewhere\n")
    _commit_and_push(world.cloud, "Notes/c.md", "and another\n")
    out = world.run()
    assert (out.state, out.files, out.pulled, out.pushed, out.committed) == ("synced", 0, 2, 0, "")
    assert (world.mine / "Notes" / "c.md").read_text(encoding="utf-8") == "and another\n"
    assert world.last_row()["result"] == "ok" and world.last_row()["effects"][0]["pulled"] == 2


def test_edits_on_both_sides_that_do_not_collide_end_up_on_both(world):
    _commit_and_push(world.cloud, "Notes/a.md", "line one from the cloud\nline two\nline three\n")
    _write(world.mine, "Notes/a.md", "line one\nline two\nline three from here\n")
    out = world.run()
    assert (out.state, out.pulled, out.pushed) == ("synced", 1, 1)
    merged = "line one from the cloud\nline two\nline three from here\n"
    assert (world.mine / "Notes" / "a.md").read_text(encoding="utf-8") == merged
    _git(world.cloud, "pull", "-q")
    assert (world.cloud / "Notes" / "a.md").read_text(encoding="utf-8") == merged
    assert world.remote_log()[0] == "vault: 2026-11-22 16:05 · 1 files", "本地那个提交排在远端的后面：线性历史"


def test_nothing_to_do_is_a_noop_and_is_still_recorded(world):
    out = world.run(trigger="schedule")
    assert (out.state, out.files, out.pulled, out.pushed) == ("noop", 0, 0, 0)
    row = world.last_row()
    assert (row["trigger"], row["result"]) == ("schedule", "noop") and world.remote_log() == ["first"]


# ───────────────────────── 冲突：不自动选边 ─────────────────────────

def test_a_conflict_is_backed_out_and_nothing_is_lost_on_either_side(world):
    _commit_and_push(world.cloud, "Notes/a.md", "line one\nTHEIRS\nline three\n")
    _write(world.mine, "Notes/a.md", "line one\nMINE\nline three\n")
    out = world.run()
    assert (out.state, out.conflicts, out.pushed) == ("conflict", 1, 0)
    assert (world.mine / "Notes" / "a.md").read_text(encoding="utf-8") == "line one\nMINE\nline three\n", "工作区还是我的版本"
    assert _git(world.mine, "status", "--porcelain") == "" and not (world.mine / ".git" / "rebase-merge").exists(), "rebase 已经撤掉"
    assert _git(world.mine, "log", "--format=%s", "-1") == "vault: 2026-11-22 16:05 · 1 files", "我的改动留成了本地提交"
    state = pv.upstream_state(world.mine)
    assert (state["behind"], state["ahead"]) == (1, 1), "两边各多一个提交，谁也没盖掉谁"
    assert world.remote_log() == ["from the cloud", "first"]
    row = world.last_row()
    assert row["result"] == "needs_you" and row["effects"][0]["conflicts"] == 1 and row["effects"][0]["pushed"] == 0


def test_a_sync_after_the_conflict_was_resolved_by_hand_goes_through(world):
    _commit_and_push(world.cloud, "Notes/a.md", "line one\nTHEIRS\nline three\n")
    _write(world.mine, "Notes/a.md", "line one\nMINE\nline three\n")
    assert world.run().state == "conflict"
    _git(world.mine, "-c", "core.editor=true", "pull", "--rebase", "-X", "theirs", "-q")       # 用户自己在别处解决了
    out = world.run()
    assert out.state == "synced" and out.pushed == 1 and pv.upstream_state(world.mine)["ahead"] == 0


# ───────────────────────── 预检：不在一个半截的状态上动手 ─────────────────────────

@pytest.mark.parametrize(("marker", "reason"), [("rebase-merge", "in_progress"), ("MERGE_HEAD", "in_progress"), ("index.lock", "locked")])
def test_a_clone_in_the_middle_of_something_is_left_alone(world, marker, reason):
    _write(world.mine, "Notes/a.md", "edited\n")
    target = world.mine / ".git" / marker
    target.mkdir() if marker == "rebase-merge" else target.write_text("x", encoding="utf-8")
    out = world.run()
    assert (out.state, out.reason) == ("blocked", reason)
    assert _git(world.mine, "log", "--format=%s", "-1") == "first", "没有提交"
    row = world.last_row()
    assert row["result"] == "needs_you" and row["effects"][0]["blocked"] == reason and row["steps"] == []


def test_a_detached_head_or_a_branch_without_upstream_is_left_alone(world):
    _git(world.mine, "checkout", "-q", "--detach")
    assert (world.run().state, world.run().reason) == ("blocked", "no_upstream")
    _git(world.mine, "checkout", "-q", "-b", "scratch")
    assert world.run().reason == "no_upstream"


def test_a_folder_that_is_not_a_clone_is_missing_and_leaves_no_record(world, tmp_path):
    assert world.sync.sync(tmp_path / "nowhere").state == "missing" and world.journal.read() == []


# ───────────────────────── 设备状态：不单独触发，随车提交 ─────────────────────────

def test_device_state_alone_does_not_trigger_a_commit(world):
    _write(world.mine, ".obsidian/appearance.json", '{"theme": "obsidian"}\n')
    out = world.run()
    assert (out.state, out.files, out.committed) == ("noop", 0, "") and world.remote_log() == ["first"]
    assert _git(world.mine, "status", "--porcelain") != "", "那份设备状态还在工作区里，没被提交"


def test_device_state_rides_along_when_there_is_real_content_to_commit(world):
    _write(world.mine, ".obsidian/appearance.json", '{"theme": "obsidian"}\n')
    _write(world.mine, "Notes/a.md", "edited\n")
    out = world.run()
    assert (out.state, out.files) == ("synced", 2) and _git(world.mine, "status", "--porcelain") == ""


def test_device_state_is_committed_when_the_remote_has_news_so_the_rebase_starts_clean(world):
    _commit_and_push(world.cloud, "Notes/b.md", "written elsewhere\n")
    _write(world.mine, ".obsidian/appearance.json", '{"theme": "obsidian"}\n')
    out = world.run()
    assert (out.state, out.pulled, out.pushed, out.files) == ("synced", 1, 1, 1)
    assert _git(world.mine, "status", "--porcelain") == ""


# ───────────────────────── 守卫：没人点头时，大动作不自动提交 ─────────────────────────

def test_an_unapproved_run_will_not_commit_a_deletion(world):
    (world.mine / "Notes" / "a.md").unlink()
    out = world.run(trigger="schedule", approved=False)
    assert (out.state, out.reason, out.deletions) == ("review", "deletions", 1)
    assert world.remote_log() == ["first"] and _git(world.mine, "log", "--format=%s", "-1") == "first"
    assert world.last_row()["result"] == "needs_you" and world.last_row()["effects"][0]["review"] == "deletions"
    approved = world.run(trigger="manual", approved=True)                  # 用户在页面上点了「现在同步」并确认
    assert approved.state == "synced" and approved.deletions == 1
    _git(world.cloud, "pull", "-q")
    assert not (world.cloud / "Notes" / "a.md").exists()


def test_an_unapproved_run_will_not_commit_a_pile_of_files(world):
    for index in range(vs.REVIEW_ABOVE_FILES + 1):
        _write(world.mine, f"Notes/bulk-{index}.md", "x\n")
    out = world.run(approved=False)
    assert (out.state, out.reason, out.files) == ("review", "many_files", vs.REVIEW_ABOVE_FILES + 1)
    for path in (world.mine / "Notes").glob("bulk-*.md"):                  # 改动少的时候，没人点头也照常提交
        path.unlink()
    _write(world.mine, "Notes/one.md", "x\n")
    assert world.run(approved=False).state == "synced"


# ───────────────────────── 连不上远端 ─────────────────────────

def test_offline_the_local_commit_is_still_made_and_the_run_says_failed(world):
    _write(world.mine, "Notes/a.md", "edited offline\n")
    _git(world.mine, "remote", "set-url", "origin", str(world.remote.parent / "gone.git"))
    out = world.run()
    assert out.state == "failed" and out.committed and out.pushed == 0
    assert _git(world.mine, "log", "--format=%s", "-1") == "vault: 2026-11-22 16:05 · 1 files", "停笔的内容先存成本地提交"
    row = world.last_row()
    assert row["result"] == "failed" and row["error"] and row["effects"][0]["committed"] == [out.committed]


def test_a_push_that_loses_a_race_fetches_again_and_goes_through(world):
    """推送前的一瞬间远端又多了一个提交：被拒一次，重新拉取、rebase、再推。"""
    _write(world.mine, "Notes/a.md", "line one\nline two\nline three from here\n")
    real, raced = pv.run_git, []

    def racing(folder, args, **options):
        if args[0] == "push" and not raced:
            raced.append(True)
            _commit_and_push(world.cloud, "Notes/late.md", "slipped in\n")
        return real(folder, args, **options)

    out = vs.VaultSync(journal=world.journal, token=lambda: "", now=lambda: NOW, run=racing).sync(world.mine)
    assert (out.state, out.pushed, out.pulled) == ("synced", 1, 1)
    assert world.remote_log()[:2] == ["vault: 2026-11-22 16:05 · 1 files", "from the cloud"]


def test_only_one_sync_runs_at_a_time(world):
    answers = []
    real = pv.run_git

    def reentrant(folder, args, **options):
        if args[0] == "fetch" and not answers:
            answers.append(sync.sync(world.mine).state)
        return real(folder, args, **options)

    sync = vs.VaultSync(journal=world.journal, token=lambda: "", now=lambda: NOW, run=reentrant)
    assert sync.sync(world.mine).state == "noop" and answers == ["busy"]


# ───────────────────────── 纯函数 ─────────────────────────

def test_status_is_read_into_counts_and_device_state_is_told_apart():
    raw = " M Notes/a.md\0?? Notes/new note.md\0 D Notes/gone.md\0R  Notes/moved.md\0Notes/old name.md\0 M .obsidian/appearance.json\0"
    changes = vs.read_status(raw)
    assert (changes.files, changes.deletions, changes.content, changes.unmerged) == (5, 1, 4, 0)
    only_noise = vs.read_status(" M .obsidian/appearance.json\0?? .obsidian/plugins/x/data.json\0")
    assert (only_noise.files, only_noise.content) == (2, 0)
    assert vs.read_status("UU Notes/a.md\0").unmerged == 1 and vs.read_status("").files == 0


def test_module_does_not_import_qt():
    tree = ast.parse(Path(vs.__file__).read_text(encoding="utf-8"))
    names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    names |= {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not any("PySide" in name or name.startswith("pet.chat") for name in names)
