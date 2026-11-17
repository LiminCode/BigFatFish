# -*- coding: utf-8 -*-
"""配置全景的探针：读真的文件（临时目录里的假 Claude Code 家目录），子进程边界用假的。"""
from __future__ import annotations

import json
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
                   "rev-list": "2\n", "status": " M note.md\n?? new.md\n"}
        return 0, answers[args[0]]

    info = probes.repo_info(tmp_path, fake_git)
    assert info["exists"] and info["remote"] == "https://github.com/acme/handbook.git" and info["branch"] == "main"
    assert info["unpushed"] == 2 and info["dirty"] is True
    assert ["rev-list", "--count", "@{upstream}..HEAD"] in calls                # 按本地记得的上游算，不联网
    assert probes.repo_info(tmp_path / "missing", fake_git) == {
        "path": str(tmp_path / "missing"), "exists": False, "remote": "", "branch": "", "last_commit": "", "unpushed": None, "dirty": None}
    broken = probes.repo_info(tmp_path, lambda *a, **k: (128, "fatal: not a git repository"))
    assert broken["remote"] == "" and broken["unpushed"] is None and broken["dirty"] is None      # 问不出来 ≠ 没有


def test_repo_info_says_a_clean_pushed_clone_has_nothing_left_behind(tmp_path):
    answers = {"remote": "", "rev-parse": "main\n", "log": "x\n", "rev-list": "0\n", "status": ""}
    info = probes.repo_info(tmp_path, lambda folder, args, *, timeout: (0, answers[args[0]]))
    assert info["unpushed"] == 0 and info["dirty"] is False


def test_wsl_side_pipes_the_probe_source_into_python_inside_the_distro():
    seen = {}

    def fake_wsl(args, *, input_text=None, timeout=30.0):
        seen.update(args=args, source=input_text, timeout=timeout)
        return 0, 'warning: noise before json\n{"home": "/home/dev", "hooks": {}}\n'

    assert probes.wsl_side(fake_wsl) == {"home": "/home/dev", "hooks": {}}
    assert seen["args"] == ["-e", "python3", "-", "--mcp"] and seen["timeout"] >= 60
    assert seen["source"] == probes.wsl_source()
    assert Path(claude_home_probe.__file__).read_text(encoding="utf-8").split("\n", 1)[1][:200] in seen["source"]
    probes.wsl_side(fake_wsl, with_mcp=False)
    assert seen["args"] == ["-e", "python3", "-"]


def test_wsl_side_tells_no_wsl_from_a_failed_run():
    assert probes.wsl_side(lambda *a, **k: (127, "")) == {"absent": True}
    assert probes.wsl_side(lambda *a, **k: (1, "")) == {"error": "exit 1"}
    assert probes.wsl_side(lambda *a, **k: (0, "python3: not found")) == {"error": "exit 0"}


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
    assert set(facts["features"]) == {"link_win", "chat", "screen", "file", "distill_personal", "assistant", "link_wsl",
                                      "briefing", "slack", "notes", "distill_work"}
    assert SECRET not in json.dumps(facts)
