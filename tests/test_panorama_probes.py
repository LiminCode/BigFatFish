# -*- coding: utf-8 -*-
"""配置全景的探针：读真的文件（临时目录里的假 Claude Code 家目录），子进程边界用假的。"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

from pet.panorama import claude_home_probe, probes

SECRET = "sk-test-not-a-real-key-0123456789abcd"


def _fake_home(root: Path) -> Path:
    claude = root / ".claude"
    (claude / "projects" / "C--Users-dev-tomato" / "memory").mkdir(parents=True)
    (claude / "projects" / "C--Users-dev-empty").mkdir()
    (claude / "plugins").mkdir()
    fish = {"type": "command", "command": "python big-fat-fish-hook.py"}
    other = {"type": "command", "command": "play ding.wav"}
    (claude / "settings.json").write_text(json.dumps({
        "model": "sonnet", "effortLevel": "high", "permissions": {"allow": ["Bash(ls *)", "Read"]},
        "hooks": {"Stop": [{"hooks": [fish, other]}], "Notification": [{"hooks": [other]}]},
        "enabledPlugins": {"notes@acme": True}}), encoding="utf-8")
    (root / ".claude.json").write_text(json.dumps({
        "oauthAccount": {"emailAddress": "dev@home.example", "organizationName": "Home", "accessToken": SECRET},
        "mcpServers": {"acme-tools": {"type": "stdio", "env": {"TOKEN": SECRET}}},
        "claudeAiMcpEverConnected": ["claude.ai Calendar"]}), encoding="utf-8")
    (claude / ".credentials.json").write_text(json.dumps({"token": SECRET}), encoding="utf-8")
    (claude / "plugins" / "installed_plugins.json").write_text(json.dumps({"plugins": {"hooks@acme": []}}), encoding="utf-8")
    (claude / "CLAUDE.md").write_text(
        "# mine\n<!-- big-fat-fish:memory-distill:start -->\n## rules\n- **one** a\n- **two** b\n<!-- 更新：2026-01-01 10:00 -->\n"
        "<!-- big-fat-fish:memory-distill:end -->\n", encoding="utf-8")
    memory = claude / "projects" / "C--Users-dev-tomato" / "memory"
    (memory / "MEMORY.md").write_text("- index\n", encoding="utf-8")
    (memory / "distill-abc.md").write_text("x\n", encoding="utf-8")
    return root


def test_home_probe_reads_hooks_memory_and_the_managed_block(tmp_path):
    out = claude_home_probe.probe(_fake_home(tmp_path))
    assert out["hooks"] == {"Stop": {"total": 2, "fish": 1}, "Notification": {"total": 1, "fish": 0}}
    assert (out["model"], out["effort"], out["allow_rules"]) == ("sonnet", "high", 2)
    assert out["account"] == {"email": "dev@home.example", "organization": "Home"}
    assert out["plugins"] == ["hooks@acme", "notes@acme"] and out["mcp_servers"] == ["acme-tools"]
    assert out["ever_connected"] == ["claude.ai Calendar"]
    assert (out["projects"], out["memory_count"], out["distilled_files"]) == (2, 1, 1)
    assert out["memory_projects"][0]["name"] == "C--Users-dev-tomato" and out["memory_projects"][0]["files"] == 1
    md = out["claude_md"]
    assert md["managed_block"] and md["managed_rules"] == 2 and md["managed_updated"] == "2026-01-01 10:00"
    assert out["credentials_file"] is True and out["connectors"] is None       # 没让它跑 claude mcp list


def test_home_probe_never_carries_a_secret_out(tmp_path):
    dumped = json.dumps(claude_home_probe.probe(_fake_home(tmp_path)))
    assert SECRET not in dumped and "accessToken" not in dumped


def test_home_probe_survives_an_empty_or_broken_home(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text("{not json", encoding="utf-8")
    out = claude_home_probe.probe(tmp_path)
    assert out["hooks"] == {} and out["claude_md"]["exists"] is False and out["projects"] == 0
    assert out["credentials_file"] is False and out["account"] == {"email": "", "organization": ""}


def test_mcp_list_lines_become_connected_needs_auth_or_failed():
    rows = claude_home_probe.parse_mcp_list(
        "Checking MCP server health…\n\n"
        "claude.ai Docs: https://docs.example/mcp - ✔ Connected\n"
        "claude.ai Tickets: https://tickets.example/mcp - ! Needs authentication\n"
        "local-tool: npx tool (stdio) - ✘ Failed to connect\n")
    assert [(r["name"], r["state"]) for r in rows] == [("claude.ai Docs", "ok"), ("claude.ai Tickets", "auth"), ("local-tool", "bad")]


def test_providers_show_only_whether_a_key_exists_and_its_last_four():
    cfg = {"chat": {"active_provider": "a", "providers": {
        "a": {"name": "Main", "base_url": "https://api.acme.example/v1", "model": "acme-large", "api_key_ref": "provider/a"},
        "b": {"name": "Spare", "base_url": "https://b.example", "model": "m"},
        "c": {"name": "Legacy", "api_key": "plain-" + SECRET}, "d": "broken"}}}
    store = {"provider/a": SECRET, "provider/b": "short"}
    rows = {r["id"]: r for r in probes.providers(cfg, lambda ref: store.get(ref, ""))}
    assert set(rows) == {"a", "b", "c"}
    assert rows["a"]["active"] and rows["a"]["host"] == "api.acme.example" and rows["a"]["key"] == {"present": True, "tail": SECRET[-4:]}
    assert rows["b"]["key"] == {"present": True, "tail": ""} and rows["b"]["key_ref"] == "provider/b"   # 太短的 key 不露末位
    assert rows["c"]["key"]["present"] is True                                    # 旧配置里明文留着的 key 也算有
    assert SECRET not in json.dumps(rows)


def test_repo_info_strips_credentials_from_the_remote(tmp_path):
    calls = []

    def fake_git(folder, args, *, timeout):
        calls.append(args)
        answers = {"remote": "https://x-access-token:ghp_secret@github.com/acme/handbook.git\n", "rev-parse": "main\n", "log": "2026-01-02 03:04 · notes\n",
                   "rev-list": "46\t2\n", "status": " M note.md\0?? new.md\0 D gone.md\0"}
        return 0, answers[args[0]]

    info = probes.repo_info(tmp_path, fake_git)
    assert info["exists"] and info["remote"] == "https://github.com/acme/handbook.git" and info["branch"] == "main"
    assert info["unpushed"] == 2 and info["behind"] == 46 and info["dirty"] is True and (info["changes"], info["deletions"]) == (3, 1)
    assert ["rev-list", "--left-right", "--count", "@{upstream}...HEAD"] in calls   # 领先和落后一次问完；按本地记得的上游算，不联网
    assert not any(args[0] in ("fetch", "pull", "ls-remote") for args in calls)
    assert probes.repo_info(tmp_path / "missing", fake_git) == {
        "path": str(tmp_path / "missing"), "exists": False, "remote": "", "branch": "", "last_commit": "", "unpushed": None, "behind": None,
        "dirty": None, "changes": None, "deletions": None, "checked_at": "", "checked_age_s": None, "check_failed": False}
    broken = probes.repo_info(tmp_path, lambda *a, **k: (128, "fatal: not a git repository"))
    assert broken["remote"] == "" and broken["unpushed"] is None and broken["behind"] is None and broken["dirty"] is None   # 问不出来 ≠ 没有


def test_repo_info_says_a_clean_pushed_clone_has_nothing_left_behind(tmp_path):
    answers = {"remote": "", "rev-parse": "main\n", "log": "x\n", "rev-list": "0\t0\n", "status": ""}
    info = probes.repo_info(tmp_path, lambda folder, args, *, timeout: (0, answers[args[0]]))
    assert info["unpushed"] == 0 and info["behind"] == 0 and info["dirty"] is False and (info["changes"], info["deletions"]) == (0, 0)


def _clone_with(tmp_path, *, fetch_head=None, reflog=None):
    """一个假克隆：``fetch_head`` / ``reflog`` 是 (内容, 修改时间)；不给就是没有这个文件。"""
    git_dir = tmp_path / ".git"
    git_dir.mkdir(exist_ok=True)
    for relative, spec in (("FETCH_HEAD", fetch_head), ("logs/refs/remotes/origin/main", reflog)):
        if spec is None:
            continue
        path = git_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(spec[0], encoding="utf-8")
        os.utime(path, (spec[1], spec[1]))
    answers = {"remote": "", "rev-parse": "main\n", "log": "x\n", "rev-list": "0\t0\n", "status": ""}
    return lambda folder, args, *, timeout: (0, answers[args[0]])


NOW = 1_800_000_000.0


def test_repo_info_dates_the_last_contact_with_the_remote_from_the_last_fetch_that_worked(tmp_path):
    git = _clone_with(tmp_path, fetch_head=("abc\t\tbranch 'main' of x\n", NOW - 3600), reflog=("old\n", NOW - 90_000))
    info = probes.repo_info(tmp_path, git, now=NOW)
    assert info["checked_age_s"] == 3600 and info["check_failed"] is False
    assert info["checked_at"] == dt.datetime.fromtimestamp(NOW - 3600).strftime("%Y-%m-%d %H:%M")


def test_a_push_counts_as_contact_even_though_it_leaves_no_fetch_head(tmp_path):
    git = _clone_with(tmp_path, reflog=("update by push\n", NOW - 120))
    info = probes.repo_info(tmp_path, git, now=NOW)
    assert info["checked_age_s"] == 120 and info["check_failed"] is False


def test_a_failed_fetch_empties_fetch_head_and_must_not_pass_for_a_check(tmp_path):
    """git 在 fetch 失败时把 FETCH_HEAD 清空并更新它的修改时间（本机 git 2.55 实测）：空文件 = 最近一次没连上。"""
    git = _clone_with(tmp_path, fetch_head=("", NOW - 5), reflog=("update by push\n", NOW - 90_000))
    info = probes.repo_info(tmp_path, git, now=NOW)
    assert info["check_failed"] is True and info["checked_age_s"] == 90_000, "退回到上一次真的碰到远端的时间"
    alone = tmp_path / "alone"
    alone.mkdir()
    never = probes.repo_info(alone, _clone_with(alone, fetch_head=("", NOW - 5)), now=NOW)
    assert never["check_failed"] is True and never["checked_age_s"] is None and never["checked_at"] == ""


def test_a_clone_nobody_ever_fetched_has_no_check_time(tmp_path):
    info = probes.repo_info(tmp_path, _clone_with(tmp_path), now=NOW)
    assert info["checked_age_s"] is None and info["checked_at"] == "" and info["check_failed"] is False


def test_a_fresh_clone_counts_from_the_moment_it_was_cloned(tmp_path):
    """刚 ``git clone`` 下来：没有 FETCH_HEAD，分支的远端记录也还没有，只有 clone 写的 ``origin/HEAD``。"""
    git = _clone_with(tmp_path)
    head = tmp_path / ".git" / "logs" / "refs" / "remotes" / "origin" / "HEAD"
    head.parent.mkdir(parents=True)
    head.write_text("clone: from x\n", encoding="utf-8")
    os.utime(head, (NOW - 30, NOW - 30))
    assert probes.repo_info(tmp_path, git, now=NOW)["checked_age_s"] == 30


def test_wsl_side_pipes_the_probe_source_into_python_inside_the_distro():
    seen = {}

    def fake_wsl(args, *, input_text=None, timeout=30.0):
        seen.update(args=args, source=input_text, timeout=timeout)
        return 0, 'warning: noise before json\n{"home": "/home/dev", "hooks": {}}\n'

    assert probes.wsl_side(fake_wsl) == {"home": "/home/dev", "hooks": {}}
    assert seen["args"] == ["-e", "python3", "-", "--clone=~/Github/AI-Base-Memory", "--mirror-log=~/.cache/ai-base-mirror.log", "--mcp"]
    assert seen["timeout"] >= 60
    assert seen["source"] == probes.wsl_source()
    assert Path(claude_home_probe.__file__).read_text(encoding="utf-8").split("\n", 1)[1][:200] in seen["source"]
    probes.wsl_side(fake_wsl, with_mcp=False)
    assert seen["args"] == ["-e", "python3", "-", "--clone=~/Github/AI-Base-Memory", "--mirror-log=~/.cache/ai-base-mirror.log"]


def test_wsl_side_tells_no_wsl_from_a_failed_run():
    assert probes.wsl_side(lambda *a, **k: (127, "")) == {"absent": True}
    assert probes.wsl_side(lambda *a, **k: (1, "")) == {"error": "exit 1"}
    assert probes.wsl_side(lambda *a, **k: (0, "python3: not found")) == {"error": "exit 0"}


def test_windows_side_reports_the_last_sync_of_the_personal_clone_from_the_run_journal(tmp_path):
    from pet import run_journal

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text("{}", encoding="utf-8")
    cfg = {"personal": {"repo_dir": str(tmp_path / "no-vault")}, "work_notes": {"repo_dir": str(tmp_path / "no-notes")}}
    home = _fake_home(tmp_path / "home")
    probe = lambda: probes.windows_side(cfg, cfg_path=cfg_path, secret_get=lambda ref: "", home=home,  # noqa: E731
                                        run_git=lambda *a, **k: (1, ""))["vault_sync"]
    assert probe() == {"personal": None}, "还没同步过"
    journal = run_journal.Journal(tmp_path / run_journal.DIR_NAME)             # 数据目录 = config.json 所在的目录
    journal.start("vault_check", "manual").finish("ok")
    first = journal.start("vault_sync", "manual")
    first.effect("git", op="sync", repo="personal", conflicts=1, pulled=0, pushed=0)
    first.finish("needs_you")
    journal.start("vault_check", "manual").finish("noop")                      # 之后的核对不算同步
    last = probe()["personal"]
    assert last["result"] == "needs_you" and last["conflicts"] == 1 and last["at"] and "blocked" not in last


def test_the_schedule_probe_gives_the_settings_in_force_and_the_recent_runs_of_both_vault_jobs(tmp_path):
    from pet import run_journal

    clock = [dt.datetime(2026, 11, 22, 9, 0, 0)]
    journal = run_journal.Journal(tmp_path / run_journal.DIR_NAME, now=lambda: clock[0])
    assert probes.vault_schedule({}, tmp_path) == {
        "settings": {"enabled": False, "mode": "auto", "interval_minutes": 60, "idle_minutes": 5}, "runs": [], "last_age_s": None}
    for hour, job, result in ((9, "vault_sync", "ok"), (10, "work_briefing", "ok"), (11, "vault_check", "noop"), (12, "vault_sync", "needs_you")):
        clock[0] = dt.datetime(2026, 11, 22, hour, 0, 0)
        journal.start(job, "schedule").finish(result)
    now = dt.datetime(2026, 11, 22, 12, 30, 0).timestamp()
    info = probes.vault_schedule({"vault_sync": {"enabled": True, "interval_minutes": 30}}, tmp_path, now=now)
    assert info["settings"]["enabled"] is True and info["settings"]["interval_minutes"] == 30
    assert [(run["job"], run["result"]) for run in info["runs"]] == [("vault_sync", "needs_you"), ("vault_check", "noop"), ("vault_sync", "ok")], \
        "新的在前；别的任务的运行不算"
    assert info["last_age_s"] == 1800


def test_windows_side_collects_everything_without_touching_wsl(tmp_path):
    home = _fake_home(tmp_path / "home")
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text("{}", encoding="utf-8")
    cfg = {"chat": {"active_provider": "a", "providers": {"a": {"name": "Main", "model": "m"}}, "github_connector": True},
           "personal": {"repo_dir": str(tmp_path / "no-vault")}, "work_notes": {"repo_dir": str(tmp_path / "no-notes")}}
    facts = probes.windows_side(cfg, cfg_path=cfg_path, secret_get=lambda ref: SECRET if ref == "connector/github" else "",
                                api_health=("ok", "fine"), home=home, run_git=lambda *a, **k: (1, ""))
    assert "wsl" not in facts and facts["api_health"] == {"state": "ok", "detail": "fine"}
    assert facts["github_token"] == {"present": True, "tail": SECRET[-4:]} and facts["chat"]["github_connector"] is True
    assert facts["personal_vault"]["exists"] is False and facts["win"]["memory_count"] == 1
    assert facts["work_mirror"]["exists"] is False
    assert set(facts["features"]) == {"link_win", "session_fish", "session_history", "link_sounds", "chat", "distill_personal",
                                      "assistant", "capture", "vault_sync", "link_wsl", "briefing", "slack", "notes", "distill_work"}
    assert SECRET not in json.dumps(facts)


def test_windows_side_reads_which_commit_the_work_mirror_inside_the_personal_clone_came_from(tmp_path):
    vault = tmp_path / "vault"
    (vault / "4-Work").mkdir(parents=True)
    (vault / "4-Work" / "MIRROR.md").write_text("# 4-Work is a mirror\n\n- Source commit / 源提交: `ed00c3b` (2026-11-23T22:06:07-08:00)\n",
                                               encoding="utf-8")
    assert probes.mirror_info(vault) == {"path": str(vault / "4-Work"), "exists": True, "commit": "ed00c3b", "at": "2026-11-23T22:06:07-08:00"}
    (vault / "4-Work" / "MIRROR.md").unlink()
    assert probes.mirror_info(vault)["exists"] is False, "只有一个 4-Work 文件夹、没有镜像说明的，不算镜像"
    assert probes.mirror_info("")["exists"] is False
